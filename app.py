"""
Application Flask — apprentissage de Python par cartes de questions.

La correction des réponses n'est PAS implémentée ici : elle vit dans
database.valider_reponse(). Cette route l'expose au frontend via
POST /api/check. Le JavaScript ne recorrige jamais de son côté.
"""

from __future__ import annotations

import os
from functools import wraps
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory, session

import comptes
import progression as progression_mod
import repetition

from correcteur_llm import corriger
from correcteur_llm import etat as etat_llm
from correcteur_llm import lister_incidents
from qualite import (
    diagnostics,
    enregistrer_tentative,
    init_journal,
    kr20,
    resume,
    statistiques_cartes,
)
from comptes import ValeurRefusee
from database import (
    NIVEAU_MAX,
    NIVEAU_MIN,
    compter_par_niveau,
    controler_donnees,
    init_db,
    lire_carte,
    lister_cartes,
    lister_matieres,
)

RACINE = Path(__file__).resolve().parent

app = Flask(__name__, static_folder=None)

# La clé de session vient de l'environnement. En production, son absence est
# une erreur de configuration, et une erreur de configuration doit être
# bruyante : sans elle, les cookies de session sont forgeables et n'importe qui
# se fait passer pour n'importe quel apprenant. En développement, une clé
# éphémère est tirée à chaque démarrage — les sessions ne survivent pas à un
# redémarrage, ce qui est exactement ce qu'on veut d'un poste de travail.
_PRODUCTION = os.environ.get("FLASK_ENV", "").lower() == "production"
_CLE = os.environ.get("SECRET_KEY", "").strip()
if _PRODUCTION and (not _CLE or _CLE.lower() in {"changeme", "secret",
                                                 "a-changer", "exemple"}):
    raise RuntimeError(
        "SECRET_KEY absente ou laissée à sa valeur d'exemple alors que "
        "FLASK_ENV=production. Refus de démarrer.")
app.secret_key = _CLE or os.urandom(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=_PRODUCTION,
)

# CORS est facultatif : le frontend est servi par Flask lui-même, donc en
# même origine. On l'active seulement si le paquet est présent, pour ceux
# qui voudraient héberger le front ailleurs.
try:
    from flask_cors import CORS

    CORS(app)
except ImportError:  # pragma: no cover
    pass


# ---------------------------------------------------------------------------
# Fichiers statiques
# ---------------------------------------------------------------------------

@app.get("/")
def accueil():
    return send_from_directory(RACINE, "index.html")


@app.get("/<path:fichier>")
def statique(fichier: str):
    """Sert style.css, script.js, etc. — jamais la base ni le code Python."""
    interdits = {".py", ".db", ".sqlite", ".sqlite3", ".bak", ".backup"}
    if Path(fichier).suffix.lower() in interdits:
        return jsonify({"error": "Fichier non accessible"}), 403
    return send_from_directory(RACINE, fichier)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def compte_actuel() -> dict | None:
    """
    Le compte connecté, lu DANS LA SESSION et jamais dans la requête.

    C'est la règle de cloisonnement du projet, et elle tient en une phrase :
    aucune route ne lit un `compte_id` fourni par le client. Un identifiant de
    compte transmis en paramètre est ignoré, et sa présence est journalisée.
    """
    identifiant = session.get("compte_id")
    if not identifiant:
        return None
    compte = comptes.lire_compte(identifiant)
    if compte is None or not compte["actif"]:
        session.clear()
        return None
    return compte


def _refuser_compte_id_client() -> None:
    corps = request.get_json(silent=True) or {}
    fourni = corps.get("compte_id") or request.args.get("compte_id")
    if fourni:
        print(f"[cloisonnement] compte_id fourni par le client, ignoré : "
              f"{fourni!r} sur {request.path}")


def exige_compte(fonction):
    @wraps(fonction)
    def enveloppe(*args, **kwargs):
        _refuser_compte_id_client()
        compte = compte_actuel()
        if compte is None:
            return jsonify({"error": "Connexion requise"}), 401
        return fonction(compte, *args, **kwargs)
    return enveloppe


def exige_role(*roles):
    def decorateur(fonction):
        @wraps(fonction)
        def enveloppe(*args, **kwargs):
            _refuser_compte_id_client()
            compte = compte_actuel()
            if compte is None:
                return jsonify({"error": "Connexion requise"}), 401
            if compte["role"] not in roles and compte["role"] != "admin":
                return jsonify({"error": "Accès refusé"}), 403
            return fonction(compte, *args, **kwargs)
        return enveloppe
    return decorateur


def _niveau_valide(niveau) -> bool:
    return niveau is None or NIVEAU_MIN <= niveau <= NIVEAU_MAX


@app.get("/api/matieres")
def api_matieres():
    """Matières disponibles et leurs niveaux — une par paquet de contenu."""
    return jsonify(lister_matieres())


@app.get("/api/levels")
def api_niveaux():
    """Niveaux disponibles et nombre de cartes dans chacun."""
    return jsonify(compter_par_niveau())


@app.get("/api/cards")
def api_cartes():
    """
    Cartes d'un niveau.

    ?level=1        filtre par niveau
    ?shuffle=1      ordre aléatoire
    La colonne `reponse` est renvoyée pour permettre l'affichage de la
    correction APRÈS validation — le frontend ne s'en sert jamais pour
    corriger lui-même.
    """
    niveau = request.args.get("level", type=int)
    if not _niveau_valide(niveau):
        return jsonify({
            "error": f"Le niveau doit être compris entre {NIVEAU_MIN} et {NIVEAU_MAX}"
        }), 400

    melanger = request.args.get("shuffle", type=int) == 1
    matiere = request.args.get("matiere", type=str)
    return jsonify(lister_cartes(niveau=niveau, melanger=melanger,
                                 matiere=matiere))


@app.post("/api/check")
def api_corriger():
    """
    Corrige une réponse. SOURCE DE VÉRITÉ UNIQUE de la correction.

    Corps attendu : {"card_id": 12, "reponse": "while"}
    Réponse : {"statut": "correct"|"proche"|"incorrect", "correct": bool,
               "message": str, "reponse": str, "explication": str, ...}
    """
    donnees = request.get_json(silent=True) or {}
    card_id = donnees.get("card_id")
    proposee = donnees.get("reponse", "")
    revele = bool(donnees.get("revele"))

    try:
        card_id = int(card_id)
    except (TypeError, ValueError):
        return jsonify({"error": "card_id manquant ou invalide"}), 400

    carte = lire_carte(card_id)
    if carte is None:
        return jsonify({"error": f"Carte {card_id} introuvable"}), 404

    if revele:
        # L'apprenant renonce et demande la réponse : c'est une donnée
        # pédagogique, pas un non-événement.
        resultat = {"statut": "incorrect", "correct": False, "score": 0.0,
                    "raison": "solution_revelee", "source": "abandon"}
    else:
        # Cascade complète : déterministe, puis cache, puis LLM si nécessaire.
        # Ne lève jamais : sans moteur LLM, le verdict déterministe s'applique.
        resultat = corriger(proposee, carte)

    compte = compte_actuel()
    note = repetition.note_depuis_verdict(
        resultat["statut"],
        indice_vu=bool(donnees.get("indice_vu")),
        via_qcm=bool(donnees.get("via_qcm")),
        solution_vue=revele,
        duree_ms=int(donnees.get("duree_ms") or 0),
        duree_mediane_ms=0,
    )

    enregistrer_tentative(
        card_id, donnees.get("session_id"), proposee, resultat,
        duree_ms=donnees.get("duree_ms", 0),
        indice_vu=donnees.get("indice_vu", False),
        solution_vue=revele,
        compte_id=compte["id"] if compte else None,
        via_qcm=bool(donnees.get("via_qcm")),
        note=note,
    )

    # La progression ne doit jamais empêcher un apprenant de travailler : même
    # philosophie que la journalisation, et même traitement.
    etat_progression = None
    if compte:
        try:
            etat_progression = progression_mod.enregistrer(
                compte["id"], card_id, note)
        except Exception as erreur:  # pragma: no cover - garde-fou
            print(f"[progression] non enregistrée : {erreur}")

    messages = {
        "correct": "✓ Bonne réponse !",
        "proche": "≈ Vous y êtes presque — la formulation est incomplète.",
        "incorrect": "✗ Réponse à revoir. Plusieurs formulations sont acceptées.",
    }
    message = ("Réponse révélée — cette question ne compte pas."
               if revele else messages[resultat["statut"]])
    if resultat.get("source") in {"llm", "cache"} and resultat.get("justification"):
        message = f"{message} {resultat['justification']}"

    return jsonify({
        **resultat,
        "card_id": card_id,
        "message": message,
        "note": note,
        "progression": _progression_publiable(etat_progression),
        "reponse": carte["reponse"],
        "explication": carte["explication"],
        "exemple_code": carte["exemple_code"],
        "sortie_attendue": carte["sortie_attendue"],
        "erreur_frequente": carte["erreur_frequente"],
    })


def _progression_publiable(etat):
    """Ce que l'apprenant a le droit de voir de son propre état."""
    if not etat:
        return None
    return {
        "etat": etat["etat"],
        "repetitions": etat["repetitions"],
        "intervalle_j": etat["intervalle_j"],
        "du_le": etat["du_le"].isoformat() if etat["du_le"] else None,
    }


# ---------------------------------------------------------------------------
# Comptes
# ---------------------------------------------------------------------------

@app.post("/api/inscription")
def api_inscription():
    donnees = request.get_json(silent=True) or {}
    try:
        compte = comptes.creer_compte(
            donnees.get("identifiant", ""),
            donnees.get("mot_de_passe", ""),
            nom_affiche=donnees.get("nom_affiche", ""),
        )
    except ValeurRefusee as erreur:
        return jsonify({"error": str(erreur)}), 400

    # Le rôle ne se demande JAMAIS depuis le formulaire public : sinon
    # n'importe qui s'inscrit formateur et lit les promos qu'il crée.
    promo = None
    code = (donnees.get("code_invitation") or "").strip()
    if code:
        try:
            promo = comptes.inscrire(compte["id"], code)
        except ValeurRefusee as erreur:
            return jsonify({"error": str(erreur), "compte": compte}), 400

    reprises = 0
    session_anonyme = donnees.get("session_id")
    if session_anonyme:
        try:
            reprises = progression_mod.rejouer_session(compte["id"],
                                                       session_anonyme)
        except Exception as erreur:  # pragma: no cover - garde-fou
            print(f"[reprise] session anonyme non reprise : {erreur}")

    session.clear()
    session["compte_id"] = compte["id"]
    return jsonify({"compte": compte, "promo": promo,
                    "tentatives_reprises": reprises}), 201


@app.post("/api/connexion")
def api_connexion():
    donnees = request.get_json(silent=True) or {}
    try:
        compte = comptes.authentifier(donnees.get("identifiant", ""),
                                      donnees.get("mot_de_passe", ""))
    except ValeurRefusee as erreur:
        return jsonify({"error": str(erreur)}), 401
    session.clear()
    session["compte_id"] = compte["id"]
    return jsonify({"compte": compte})


@app.post("/api/deconnexion")
def api_deconnexion():
    session.clear()
    return "", 204


@app.get("/api/moi")
@exige_compte
def api_moi(compte):
    return jsonify({"compte": compte,
                    "promos": comptes.promos_de(compte["id"])})


@app.get("/api/moi/export")
@exige_compte
def api_export(compte):
    """Droit d'accès : tout ce que l'outil sait de cette personne."""
    return jsonify(comptes.exporter(compte["id"]))


@app.post("/api/moi/suppression")
@exige_compte
def api_suppression(compte):
    """Droit d'effacement : l'identité part, les statistiques restent,
    détachées et sans texte de réponse."""
    resultat = comptes.anonymiser(compte["id"])
    session.clear()
    return jsonify(resultat)


# ---------------------------------------------------------------------------
# Révision
# ---------------------------------------------------------------------------

@app.get("/api/revision")
@exige_compte
def api_revision(compte):
    niveau = request.args.get("level", type=int)
    if not _niveau_valide(niveau):
        return jsonify({"error": "Niveau hors bornes"}), 400
    limite = request.args.get("limite", type=int)
    cartes = progression_mod.file(
        compte["id"], matiere=request.args.get("matiere", type=str),
        niveau=niveau, limite=limite)
    return jsonify(cartes)


@app.get("/api/progression")
@exige_compte
def api_progression(compte):
    return jsonify(progression_mod.resume(
        compte["id"], matiere=request.args.get("matiere", type=str)))


# ---------------------------------------------------------------------------
# Formateur
# ---------------------------------------------------------------------------

@app.get("/api/formateur/promos")
@exige_role("formateur")
def api_promos(compte):
    return jsonify(comptes.promos_animees_par(compte["id"]))


@app.post("/api/formateur/promos")
@exige_role("formateur")
def api_creer_promo(compte):
    donnees = request.get_json(silent=True) or {}
    try:
        promo = comptes.creer_promo(donnees.get("nom", ""), compte["id"],
                                    debut=donnees.get("debut"),
                                    fin=donnees.get("fin"))
    except ValeurRefusee as erreur:
        return jsonify({"error": str(erreur)}), 400
    return jsonify(promo), 201


@app.get("/api/formateur/promo/<int:promo_id>")
@exige_role("formateur")
def api_promo(compte, promo_id):
    if not comptes.anime_la_promo(compte["id"], promo_id):
        # 404 et non 403 : un formateur n'a pas à apprendre qu'une promo
        # existe chez un confrère.
        return jsonify({"error": "Promo introuvable"}), 404
    apprenants = comptes.apprenants_de(promo_id)
    return jsonify({
        "promo": comptes.lire_promo(promo_id),
        "apprenants": [
            {**a, "progression": progression_mod.resume(a["id"])}
            for a in apprenants
        ],
    })


@app.get("/qualite")
def page_qualite():
    """Tableau de bord de la qualité des questions."""
    return send_from_directory(RACINE, "qualite.html")


@app.get("/api/qualite")
def api_qualite():
    """Vue d'ensemble et indices carte par carte."""
    return jsonify({"resume": resume(), "cartes": statistiques_cartes()})


@app.get("/api/qualite/diagnostics")
def api_diagnostics():
    """La file de relecture : ce qu'il faut corriger, et rien d'autre."""
    return jsonify(diagnostics())


@app.get("/api/qualite/niveau/<int:niveau>")
def api_kr20(niveau: int):
    if not NIVEAU_MIN <= niveau <= NIVEAU_MAX:
        return jsonify({"error": "Niveau hors bornes"}), 400
    return jsonify(kr20(niveau))


@app.get("/api/llm/status")
def api_etat_llm():
    """Quel moteur est configuré, répond-il, et avec quels modèles."""
    return jsonify(etat_llm())


@app.get("/api/llm/incidents")
def api_incidents_llm():
    """Tentatives de détournement du correcteur — vue formateur."""
    return jsonify(lister_incidents())


@app.get("/api/health")
def api_sante():
    """Contrôle d'intégrité : utile en CI et pour un déploiement."""
    problemes = controler_donnees()
    return jsonify({
        "ok": not problemes,
        "cartes": sum(n["total"] for n in compter_par_niveau()),
        "problemes": problemes,
    }), (200 if not problemes else 500)


# ---------------------------------------------------------------------------

def creer_app(chemin_base=None):
    """Point d'entrée pour les tests."""
    init_db(chemin_base)
    init_journal(chemin_base)
    comptes.init_comptes(chemin_base)
    return app


if __name__ == "__main__":
    total = init_db()
    print(f"Base prête : {total} cartes.")
    soucis = controler_donnees()
    if soucis:
        print(f"⚠️  {len(soucis)} anomalie(s) dans les données :")
        for s in soucis[:10]:
            print("   -", s)
    print("→ http://127.0.0.1:5000")
    app.run(debug=True, port=5000)

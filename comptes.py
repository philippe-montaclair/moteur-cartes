"""
Comptes, promos, inscriptions — et rien d'autre.

Ce module ne connaît ni Flask ni HTTP : il rend des dicts et lève des
`ValeurRefusee`. C'est ce qui permet de le tester sans monter d'application, et
c'est ce qui évite qu'une règle métier finisse dans une route.

Choix délibérément ennuyeux, et c'est une qualité :
  * `werkzeug.security` pour le hachage — livré avec Flask, rien à installer,
    jamais de hachage maison ;
  * pas de JWT — il n'y a ni service tiers ni application mobile à servir ;
  * pas de réinitialisation par courriel — un envoi de courriel est un service
    externe, donc une dépendance, et la promesse est « aucun appel externe
    requis pour fonctionner ». Le formateur réinitialise depuis son tableau
    de bord.

Note d'implémentation qui a son importance : ce module lit
`database.CHEMIN_BASE` **au moment de l'appel**, jamais par
`from database import CHEMIN_BASE`. Cet import-là copie la valeur à l'import et
c'est ce qui a obligé `conftest.py` à rediriger `qualite` et `correcteur_llm` un
par un pour qu'ils n'écrivent pas dans la base de production.
"""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta, timezone

from werkzeug.security import check_password_hash, generate_password_hash

import database
import migrations

ROLES = ("apprenant", "formateur", "admin")

LONGUEUR_MOT_DE_PASSE_MIN = 10
IDENTIFIANT_VALIDE = re.compile(r"^[^\s@]{1,64}(@[^\s@]{1,64})?$")

#: Limitation des tentatives de connexion. Comptée en base, pas en mémoire :
#: avec trois workers gunicorn, un compteur en mémoire en protège un sur trois.
ECHECS_MAX = 10
FENETRE_ECHECS_MIN = 15


class ValeurRefusee(ValueError):
    """Entrée invalide. Le message est destiné à l'utilisateur final."""


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


def _horodatage(quand: datetime | None = None) -> str:
    return (quand or _maintenant()).strftime("%Y-%m-%d %H:%M:%S")


def _connexion(chemin=None):
    return database.connexion(chemin or database.CHEMIN_BASE)


def init_comptes(chemin=None) -> int:
    """Prépare le schéma. Idempotent."""
    with _connexion(chemin) as conn:
        return migrations.migrer(conn)


# ---------------------------------------------------------------------------
# Création et authentification
# ---------------------------------------------------------------------------

def _verifier_identifiant(identifiant: str) -> str:
    identifiant = (identifiant or "").strip().lower()
    if not identifiant:
        raise ValeurRefusee("L'identifiant est obligatoire.")
    if not IDENTIFIANT_VALIDE.match(identifiant):
        raise ValeurRefusee("Identifiant invalide : ni espace, ni arobase "
                            "multiple.")
    return identifiant


def _verifier_mot_de_passe(mot_de_passe: str) -> str:
    if not mot_de_passe or len(mot_de_passe) < LONGUEUR_MOT_DE_PASSE_MIN:
        raise ValeurRefusee(
            f"Le mot de passe doit faire au moins "
            f"{LONGUEUR_MOT_DE_PASSE_MIN} caractères.")
    return mot_de_passe


def _publier(ligne) -> dict | None:
    """Ce qu'un compte laisse voir. Le hachage n'en fait JAMAIS partie."""
    if ligne is None:
        return None
    return {
        "id": ligne["id"],
        "identifiant": ligne["identifiant"],
        "role": ligne["role"],
        "nom_affiche": ligne["nom_affiche"],
        "cree_le": ligne["cree_le"],
        "actif": bool(ligne["actif"]),
        "anonymise": bool(ligne["anonymise_le"]),
    }


def creer_compte(identifiant: str, mot_de_passe: str, nom_affiche: str = "",
                 role: str = "apprenant", chemin=None) -> dict:
    identifiant = _verifier_identifiant(identifiant)
    _verifier_mot_de_passe(mot_de_passe)
    if role not in ROLES:
        raise ValeurRefusee(f"Rôle inconnu : {role}")

    init_comptes(chemin)
    empreinte = generate_password_hash(mot_de_passe)
    with _connexion(chemin) as conn:
        existe = conn.execute(
            "SELECT 1 FROM comptes WHERE identifiant = ?",
            (identifiant,)).fetchone()
        if existe:
            raise ValeurRefusee("Cet identifiant est déjà pris.")
        curseur = conn.execute(
            "INSERT INTO comptes (identifiant, mot_de_passe_hash, role, "
            "nom_affiche, cree_le) VALUES (?,?,?,?,?)",
            (identifiant, empreinte, role, (nom_affiche or "").strip()[:120],
             _horodatage()))
        nouveau = curseur.lastrowid
    return lire_compte(nouveau, chemin=chemin)


def lire_compte(compte_id: int, chemin=None) -> dict | None:
    with _connexion(chemin) as conn:
        return _publier(conn.execute(
            "SELECT * FROM comptes WHERE id = ?", (int(compte_id),)).fetchone())


def _echecs_recents(conn, identifiant: str) -> int:
    depuis = _horodatage(_maintenant() - timedelta(minutes=FENETRE_ECHECS_MIN))
    return conn.execute(
        "SELECT COUNT(*) FROM connexions_ratees "
        "WHERE identifiant = ? AND cree_le >= ?",
        (identifiant, depuis)).fetchone()[0]


def authentifier(identifiant: str, mot_de_passe: str, chemin=None) -> dict:
    """
    Rend le compte, ou lève `ValeurRefusee`.

    Le message est volontairement le même que l'identifiant soit inconnu ou le
    mot de passe faux : distinguer les deux dit à un inconnu quels comptes
    existent.
    """
    identifiant = (identifiant or "").strip().lower()
    init_comptes(chemin)

    # On ne lève RIEN à l'intérieur du bloc `with`. `database.connexion` ne
    # valide la transaction qu'en sortie normale : lever depuis l'intérieur
    # annulerait l'enregistrement de l'échec, et la limitation ne compterait
    # jamais rien. Défaut trouvé par `test_trop_de_tentatives_bloque`, le
    # 28 août — la première version faisait exactement ça.
    trop_d_essais = False
    compte = None
    with _connexion(chemin) as conn:
        if _echecs_recents(conn, identifiant) >= ECHECS_MAX:
            trop_d_essais = True
        else:
            ligne = conn.execute(
                "SELECT * FROM comptes WHERE identifiant = ?",
                (identifiant,)).fetchone()

            bon = (ligne is not None
                   and bool(ligne["actif"])
                   and ligne["anonymise_le"] is None
                   and check_password_hash(ligne["mot_de_passe_hash"],
                                           mot_de_passe or ""))
            if bon:
                conn.execute(
                    "UPDATE comptes SET derniere_connexion = ? WHERE id = ?",
                    (_horodatage(), ligne["id"]))
                conn.execute(
                    "DELETE FROM connexions_ratees WHERE identifiant = ?",
                    (identifiant,))
                compte = _publier(ligne)
            else:
                conn.execute(
                    "INSERT INTO connexions_ratees (identifiant, cree_le) "
                    "VALUES (?,?)", (identifiant, _horodatage()))

    if trop_d_essais:
        raise ValeurRefusee(
            "Trop de tentatives. Réessayez dans un quart d'heure.")
    if compte is None:
        raise ValeurRefusee("Identifiant ou mot de passe incorrect.")
    return compte


def changer_mot_de_passe(compte_id: int, nouveau: str, chemin=None) -> None:
    _verifier_mot_de_passe(nouveau)
    with _connexion(chemin) as conn:
        conn.execute("UPDATE comptes SET mot_de_passe_hash = ? WHERE id = ?",
                     (generate_password_hash(nouveau), int(compte_id)))


# ---------------------------------------------------------------------------
# Promos et inscriptions
# ---------------------------------------------------------------------------

def creer_promo(nom: str, formateur_id: int, debut=None, fin=None,
                chemin=None) -> dict:
    nom = (nom or "").strip()
    if not nom:
        raise ValeurRefusee("La promo doit avoir un nom.")
    formateur = lire_compte(formateur_id, chemin=chemin)
    if formateur is None or formateur["role"] not in ("formateur", "admin"):
        raise ValeurRefusee("Seul un formateur peut créer une promo.")

    code = secrets.token_urlsafe(9)
    with _connexion(chemin) as conn:
        curseur = conn.execute(
            "INSERT INTO promos (nom, formateur_id, code_invitation, debut, "
            "fin, cree_le) VALUES (?,?,?,?,?,?)",
            (nom, int(formateur_id), code, debut, fin, _horodatage()))
        promo_id = curseur.lastrowid
    return lire_promo(promo_id, chemin=chemin)


def lire_promo(promo_id: int, chemin=None) -> dict | None:
    with _connexion(chemin) as conn:
        ligne = conn.execute("SELECT * FROM promos WHERE id = ?",
                             (int(promo_id),)).fetchone()
    return dict(ligne) if ligne else None


def inscrire(compte_id: int, code_invitation: str, chemin=None) -> dict:
    with _connexion(chemin) as conn:
        promo = conn.execute(
            "SELECT * FROM promos WHERE code_invitation = ?",
            ((code_invitation or "").strip(),)).fetchone()
        if promo is None:
            raise ValeurRefusee("Code d'invitation inconnu.")
        conn.execute(
            "INSERT OR IGNORE INTO inscriptions (compte_id, promo_id, "
            "inscrit_le) VALUES (?,?,?)",
            (int(compte_id), promo["id"], _horodatage()))
        return dict(promo)


def promos_de(compte_id: int, chemin=None) -> list[dict]:
    """Les promos d'un apprenant, sorties comprises — c'est l'historique."""
    with _connexion(chemin) as conn:
        return [dict(r) for r in conn.execute(
            "SELECT p.*, i.inscrit_le, i.sorti_le FROM promos p "
            "JOIN inscriptions i ON i.promo_id = p.id "
            "WHERE i.compte_id = ? ORDER BY i.inscrit_le",
            (int(compte_id),))]


def promos_animees_par(formateur_id: int, chemin=None) -> list[dict]:
    with _connexion(chemin) as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM promos WHERE formateur_id = ? ORDER BY cree_le DESC",
            (int(formateur_id),))]


def apprenants_de(promo_id: int, chemin=None) -> list[dict]:
    with _connexion(chemin) as conn:
        return [_publier(r) for r in conn.execute(
            "SELECT c.* FROM comptes c JOIN inscriptions i "
            "ON i.compte_id = c.id WHERE i.promo_id = ? "
            "ORDER BY c.nom_affiche, c.identifiant", (int(promo_id),))]


def anime_la_promo(formateur_id: int, promo_id: int, chemin=None) -> bool:
    """LA fonction qui décide de tout le cloisonnement côté formateur."""
    promo = lire_promo(promo_id, chemin=chemin)
    if promo is None:
        return False
    compte = lire_compte(formateur_id, chemin=chemin)
    if compte and compte["role"] == "admin":
        return True
    return promo["formateur_id"] == int(formateur_id)


def est_inscrit(compte_id: int, promo_id: int, chemin=None) -> bool:
    with _connexion(chemin) as conn:
        return conn.execute(
            "SELECT 1 FROM inscriptions WHERE compte_id = ? AND promo_id = ?",
            (int(compte_id), int(promo_id))).fetchone() is not None


# ---------------------------------------------------------------------------
# RGPD — accès et effacement
# ---------------------------------------------------------------------------

def exporter(compte_id: int, chemin=None) -> dict:
    """Tout ce que l'outil sait de cette personne, et rien d'une autre."""
    with _connexion(chemin) as conn:
        compte = _publier(conn.execute(
            "SELECT * FROM comptes WHERE id = ?", (int(compte_id),)).fetchone())
        if compte is None:
            raise ValeurRefusee("Compte inconnu.")
        tentatives = [dict(r) for r in conn.execute(
            "SELECT carte_id, reponse, correct, statut, note, duree_ms, "
            "cree_le FROM tentatives WHERE compte_id = ? ORDER BY cree_le",
            (int(compte_id),))]
        progression = [dict(r) for r in conn.execute(
            "SELECT * FROM progression WHERE compte_id = ?",
            (int(compte_id),))]
    return {
        "version": 1,
        "edite_le": _horodatage(),
        "compte": compte,
        "promos": promos_de(compte_id, chemin=chemin),
        "progression": progression,
        "tentatives": tentatives,
    }


def anonymiser(compte_id: int, chemin=None) -> dict:
    """
    Efface l'identité, conserve les statistiques — détachées.

    Supprimer les tentatives détruirait les indices de qualité des questions,
    qui sont un actif produit et ne portent aucune identité une fois
    détachés. C'est conforme, et c'est à écrire dans l'information des
    personnes.
    """
    quand = _horodatage()
    with _connexion(chemin) as conn:
        ligne = conn.execute("SELECT * FROM comptes WHERE id = ?",
                             (int(compte_id),)).fetchone()
        if ligne is None:
            raise ValeurRefusee("Compte inconnu.")
        conn.execute(
            "UPDATE comptes SET identifiant = ?, mot_de_passe_hash = '', "
            "nom_affiche = '', actif = 0, anonymise_le = ? WHERE id = ?",
            (f"anonyme-{compte_id}-{secrets.token_hex(4)}", quand,
             int(compte_id)))
        # Les tentatives restent, sans identité et sans texte de réponse :
        # la réponse écrite peut contenir une donnée personnelle saisie à la
        # main. Les indices de qualité n'en ont pas besoin.
        conn.execute(
            "UPDATE tentatives SET compte_id = NULL, reponse = '' "
            "WHERE compte_id = ?", (int(compte_id),))
        conn.execute("DELETE FROM progression WHERE compte_id = ?",
                     (int(compte_id),))
        conn.execute("DELETE FROM inscriptions WHERE compte_id = ?",
                     (int(compte_id),))
    return {"anonymise_le": quand, "compte_id": int(compte_id)}

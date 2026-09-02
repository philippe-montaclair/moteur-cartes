"""
Tests des paquets de contenu multilingues et du type `vocabulaire`.

Le test décisif est `test_ajouter_une_matiere_ne_touche_pas_au_code` : il
vérifie que la langue vient du manifeste et non d'une constante du moteur.
C'est toute la thèse « un moteur, N paquets de contenu ».
"""

import json
import tempfile
from pathlib import Path

import correcteur_llm as llm
import database as db
from app import app
from conftest import carte_par_titre


def client():
    app.config["TESTING"] = True
    return app.test_client()


def carte(titre):
    return carte_par_titre(titre)


# ---------------------------------------------------------------------------
# Paquets et manifestes
# ---------------------------------------------------------------------------

def test_trois_matieres_chargees():
    matieres = {m["matiere"]: m for m in db.lister_matieres()}
    assert {"python", "anglais_info", "espagnol"} <= set(matieres)
    assert matieres["anglais_info"]["total"] >= 30
    assert matieres["espagnol"]["total"] >= 15


def test_le_manifeste_porte_la_langue():
    """La langue vient du paquet, pas d'une constante du moteur."""
    langues = {}
    for c in db.lister_cartes():
        langues.setdefault(c["matiere"], set()).add(c["langue"])

    assert langues["python"] == {"fr"}
    assert langues["espagnol"] == {"es"}
    # L'anglais mélange compréhension (réponse en français) et production
    # (réponse en anglais) : les deux langues coexistent dans le paquet.
    assert langues["anglais_info"] == {"fr", "en"}


def test_langue_reponse_deduite_de_la_langue_cible():
    dossier = db.DOSSIER_CONTENUS / "espagnol"
    manifeste = db.lire_manifeste(dossier)
    assert manifeste["langue_cible"] == "es"
    assert manifeste["langue_reponse"] == "es"

    manifeste_python = db.lire_manifeste(db.DOSSIER_CONTENUS / "python")
    assert manifeste_python["langue_reponse"] == "fr"


def test_ajouter_une_matiere_ne_touche_pas_au_code():
    """
    LE test de décision.

    On fabrique un paquet dans une langue jamais prévue par le moteur —
    l'allemand — avec ses propres cartes. Aucune ligne de `database.py`
    n'est modifiée : si cela fonctionne, la thèse du moteur tient.
    """
    with tempfile.TemporaryDirectory() as tmp:
        paquet = Path(tmp) / "allemand"
        paquet.mkdir()
        (paquet / "manifeste.json").write_text(json.dumps({
            "matiere": "allemand", "nom": "Allemand",
            "langue_enseignement": "fr", "langue_cible": "de",
            "type_defaut": "vocabulaire",
        }), encoding="utf-8")
        (paquet / "niveau_1.json").write_text(json.dumps([{
            "niveau": 1, "titre": "merci", "categorie": "Base",
            "question": "Comment dit-on « merci » en allemand ?",
            "reponse": "danke", "reponses_acceptees": ["danke", "danke schön"],
            "explication": "Formule de politesse de base.",
            "indice": "Cinq lettres.",
        }], ensure_ascii=False), encoding="utf-8")

        manifeste = db.lire_manifeste(paquet)
        assert manifeste["langue_reponse"] == "de"
        assert manifeste["type_defaut"] == "vocabulaire"

        brute = json.loads((paquet / "niveau_1.json").read_text(encoding="utf-8"))[0]
        fiche = {**db.DEFAUTS, **brute}
        fiche["langue"] = manifeste["langue_reponse"]
        fiche["type"] = manifeste["type_defaut"]

        assert db.valider_reponse("danke", fiche)["correct"] is True
        assert db.valider_reponse("Danke", fiche)["correct"] is True
        assert db.valider_reponse("danke schön", fiche)["correct"] is True
        assert db.valider_reponse("gracias", fiche)["correct"] is False


# ---------------------------------------------------------------------------
# Mots vides par langue
# ---------------------------------------------------------------------------

def test_les_mots_vides_dependent_de_la_langue():
    assert db.mots_significatifs("Le mot-clé est while", "fr") == ["while"]
    assert db.mots_significatifs("the keyword is while", "en") == ["while"]
    assert db.mots_significatifs("la palabra es hola", "es") == ["hola"]


def test_une_langue_inconnue_retombe_sur_le_francais():
    assert db.mots_significatifs("le mot est x", "xx") == ["x"]


# ---------------------------------------------------------------------------
# Type vocabulaire : tolérant sur la frappe, strict sur le mot
# ---------------------------------------------------------------------------

def test_vocabulaire_mot_exact():
    c = carte("lever une exception")
    assert c["type"] == "vocabulaire"
    for essai in ("raise", "Raise", "  RAISE  ", "to raise"):
        assert db.valider_reponse(essai, c)["correct"] is True, essai


def test_vocabulaire_pardonne_une_lettre_mais_montre_l_orthographe():
    """
    L'inverse du mode texte : on accepte la frappe, jamais l'à-peu-près, et
    on affiche toujours le mot exact — sinon on entérine la faute.
    """
    c = carte("lever une exception")
    r = db.valider_reponse("rais", c)
    assert r["correct"] is True
    assert r["raison"] == "faute_de_frappe"
    assert r["orthographe_exacte"] == "raise"


def test_vocabulaire_refuse_deux_lettres_d_ecart():
    c = carte("lever une exception")
    r = db.valider_reponse("raiz", c)
    assert r["correct"] is False
    assert r["statut"] == "proche"
    assert r["orthographe_exacte"] == "raise"


def test_vocabulaire_refuse_un_autre_mot():
    c = carte("lever une exception")
    r = db.valider_reponse("throw", c)
    assert r["correct"] is False
    assert r["statut"] == "incorrect"


def test_vocabulaire_ignore_les_accents_a_la_saisie():
    c = carte("bonjour")
    assert db.valider_reponse("buenos dias", c)["correct"] is True
    assert db.valider_reponse("buenos días", c)["correct"] is True


def test_vocabulaire_n_applique_aucune_tolerance_semantique():
    """
    En Python « les clés » ≈ « les clefs ». En vocabulaire, jamais :
    l'orthographe EST la compétence évaluée.
    """
    c = carte("merci")
    assert db.valider_reponse("gracias", c)["correct"] is True
    assert db.valider_reponse("merci en espagnol", c)["correct"] is False
    assert db.valider_reponse("un remerciement", c)["correct"] is False


def test_un_mot_trop_court_ne_beneficie_pas_de_la_tolerance():
    """Sur trois lettres, une lettre d'écart change trop souvent le mot."""
    fiche = {"id": 0, "reponse": "pan", "reponses_acceptees": '["pan"]',
             "mots_cles": "[]", "type": "vocabulaire", "langue": "es"}
    assert db.valider_reponse("pan", fiche)["correct"] is True
    assert db.valider_reponse("pon", fiche)["correct"] is False


def test_distance_edition():
    assert db.distance_edition("raise", "raise") == 0
    assert db.distance_edition("rais", "raise") == 1
    assert db.distance_edition("raize", "raise") == 1
    assert db.distance_edition("raiz", "raise") == 2
    assert db.distance_edition("", "abc") == 3


# ---------------------------------------------------------------------------
# Non-régression : Python ne doit rien perdre
# ---------------------------------------------------------------------------

def test_les_cartes_python_restent_tolerantes():
    c = carte("Répéter avec while")
    assert db.valider_reponse("Le mot-clé est while.", c)["correct"] is True
    c = carte("Reconnaître les types")
    assert db.valider_reponse("int, float, str et bool.", c)["correct"] is True


def test_integrite_de_tous_les_paquets():
    assert db.controler_donnees() == []


# ---------------------------------------------------------------------------
# Prompt LLM : la langue vient du contenu
# ---------------------------------------------------------------------------

def test_le_prompt_llm_suit_la_langue_de_la_carte():
    attendus = {
        "Parcourir un dictionnaire": "français",
        "bonjour": "espagnol",
        "lever une exception": "anglais",
    }
    for titre, langue in attendus.items():
        systeme = llm.construire_prompt(carte(titre), "x")[0]["content"]
        assert f"formation en {langue}" in systeme, (titre, systeme[:80])


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def test_api_matieres():
    donnees = client().get("/api/matieres").get_json()
    noms = {m["matiere"] for m in donnees}
    assert {"python", "anglais_info", "espagnol"} <= noms
    for m in donnees:
        assert m["niveaux"] and m["total"] > 0


def test_api_cards_filtre_par_matiere():
    cartes = client().get("/api/cards?level=1&matiere=espagnol").get_json()
    assert cartes
    assert all(c["matiere"] == "espagnol" for c in cartes)
    assert all(c["langue"] == "es" for c in cartes)


def test_api_check_sur_une_carte_de_vocabulaire():
    c = carte("bonjour")
    donnees = client().post("/api/check", json={
        "card_id": c["id"], "reponse": "ola",
    }).get_json()
    assert donnees["correct"] is True
    assert donnees["orthographe_exacte"] == "hola"

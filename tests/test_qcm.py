"""
Tests du QCM de rattrapage.

Chaque test fabrique un QCM porteur d'UN défaut précis et vérifie qu'il est
signalé. Un test qui passe sur un QCM sain ne prouverait rien.

Rappel de la règle que ces tests protègent : le QCM est un rattrapage, montré
seulement après une réponse libre fausse. Ses distracteurs sont donc lus par
quelqu'un qui vient de se tromper.
"""

import json

import database as db
from conftest import carte_par_titre
from fabrique.redaction import (PALIERS, consignes_de_palier,
                                construire_prompt_externe, gabarit_pour,
                                palier_du_niveau)
from fabrique.verificateurs import verifier_qcm

BON = {
    "options": ["else", "elif", "elseif", "then"],
    "reponse": 1,
    "pourquoi_faux": {"0": "n'teste rien", "2": "autre langage",
                      "3": "n'existe pas"},
}


def _qcm(**remplacements):
    return {**BON, **remplacements}


# ---------------------------------------------------------------------------
# Forme du QCM
# ---------------------------------------------------------------------------

def test_un_qcm_bien_forme_ne_dit_rien():
    assert db.defauts_du_qcm(_qcm()) == []


def test_une_carte_sans_qcm_reste_valide():
    """Les 345 cartes écrites avant le 28 août 2026 n'en ont pas. Elles ne
    doivent jamais être signalées pour ça."""
    assert db.defauts_du_qcm({}) == []
    assert db.defauts_du_qcm(None) == []


def test_le_nombre_d_options_est_impose():
    for options in (["a", "b", "c"], ["a", "b", "c", "d", "e"], []):
        assert db.defauts_du_qcm(_qcm(options=options)), options


def test_une_option_vide_est_signalee():
    assert db.defauts_du_qcm(_qcm(options=["else", "elif", "   ", "then"]))


def test_deux_options_identiques_sont_signalees():
    assert db.defauts_du_qcm(_qcm(options=["elif", "elif", "else", "then"]))


def test_la_reponse_doit_etre_un_index_entier():
    for mauvais in ("B", 1.0, None, -1, 4, True):
        assert db.defauts_du_qcm(_qcm(reponse=mauvais)), mauvais


def test_un_motif_de_rejet_manque():
    incomplet = _qcm(pourquoi_faux={"0": "raison"})
    defauts = db.defauts_du_qcm(incomplet)
    assert any("motif de rejet" in d for d in defauts)


def test_la_bonne_option_ne_doit_pas_etre_la_plus_longue():
    """Le biais le plus répandu des QCM écrits par un modèle : la bonne
    réponse est la plus détaillée. Un apprenant l'apprend en trois cartes."""
    bavard = _qcm(options=[
        "non", "oui",
        "peut-être", "jamais"])
    bavard["options"][1] = ("oui, parce que la condition est évaluée puis "
                            "le bloc exécuté dans l'ordre attendu")
    defauts = db.defauts_du_qcm(bavard)
    assert any("plus longue" in d for d in defauts)


def test_les_fourre_tout_sont_refuses():
    for piege in ("Toutes les réponses ci-dessus", "Aucune de ces réponses",
                  "A et B"):
        mauvais = _qcm(options=["else", "elif", "then", piege])
        assert any("fourre-tout" in d for d in db.defauts_du_qcm(mauvais)), piege


# ---------------------------------------------------------------------------
# Chargement
# ---------------------------------------------------------------------------

def test_la_colonne_qcm_existe():
    carte = db.lister_cartes(niveau=1)[0]
    assert "qcm" in carte.keys() if hasattr(carte, "keys") else "qcm" in carte


def test_les_cartes_du_depot_se_chargent_toujours():
    """Non-régression : l'ajout d'une colonne ne doit rien casser."""
    problemes = db.controler_donnees()
    assert problemes == [], problemes[:5]


def test_lire_qcm_survit_a_un_json_casse():
    assert db.lire_qcm({"qcm": "{ceci n'est pas du json"}) == {}
    assert db.lire_qcm({"qcm": "[1, 2]"}) == {}
    assert db.lire_qcm({"qcm": ""}) == {}


def test_lire_qcm_accepte_le_texte_et_le_dict():
    assert db.lire_qcm({"qcm": json.dumps(BON)})["reponse"] == 1
    assert db.lire_qcm({"qcm": BON})["reponse"] == 1


# ---------------------------------------------------------------------------
# Le vérificateur
# ---------------------------------------------------------------------------

def _carte_avec(qcm):
    carte = dict(carte_par_titre("Afficher un message"))
    carte["qcm"] = json.dumps(qcm, ensure_ascii=False)
    return carte


def test_le_verificateur_ignore_les_cartes_sans_qcm():
    assert verifier_qcm(db.lister_cartes(niveau=1)) == []


def test_le_verificateur_signale_un_qcm_mal_forme():
    signale = verifier_qcm([_carte_avec({"options": ["a", "b"], "reponse": 0})])
    assert signale and signale[0]["probleme"] == "qcm_invalide"


def test_une_bonne_option_hors_sujet_est_signalee():
    """Si la bonne option du QCM n'est pas acceptée comme réponse à la
    question ouverte, les deux ne portent pas sur la même notion."""
    qcm = {"options": ["print(\"Bonjour\")", "un tuple", "une boucle while",
                       "un dictionnaire"],
           "reponse": 1,
           "pourquoi_faux": {"0": "x", "2": "y", "3": "z"}}
    problemes = {s["probleme"] for s in verifier_qcm([_carte_avec(qcm)])}
    assert "qcm_hors_sujet" in problemes


def test_un_distracteur_juste_est_signale():
    """Un distracteur que le correcteur accepte n'est pas un distracteur."""
    qcm = {"options": ["un tuple", "print(\"Bonjour\")", "une boucle",
                       "un dictionnaire"],
           "reponse": 0,
           "pourquoi_faux": {"1": "x", "2": "y", "3": "z"}}
    problemes = {s["probleme"] for s in verifier_qcm([_carte_avec(qcm)])}
    assert "qcm_distracteur_juste" in problemes


def test_un_qcm_coherent_ne_declenche_rien():
    """Le pendant : à trop signaler, la file de relecture cesse d'être lue."""
    qcm = {"options": ["print(\"Bonjour\")", "un tuple", "une boucle while",
                       "un dictionnaire"],
           "reponse": 0,
           "pourquoi_faux": {"1": "x", "2": "y", "3": "z"}}
    assert verifier_qcm([_carte_avec(qcm)]) == []


# ---------------------------------------------------------------------------
# Les paliers de difficulté
# ---------------------------------------------------------------------------

def test_chaque_niveau_a_son_palier():
    for numero in range(1, 8):
        nom, palier = palier_du_niveau(numero)
        assert nom in PALIERS
        assert numero in palier["niveaux"]


def test_les_paliers_ne_se_chevauchent_pas():
    vus = []
    for palier in PALIERS.values():
        vus += list(palier["niveaux"])
    assert sorted(vus) == list(range(1, 8)), vus


def test_un_niveau_hors_grille_retombe_sur_expert():
    assert palier_du_niveau(9)[0] == "expert"


def test_les_consignes_changent_avec_le_niveau():
    debutant = consignes_de_palier(1)
    expert = consignes_de_palier(7)
    assert debutant != expert
    assert "1 à 3" in debutant and "7 à 10" in expert
    assert "très distinctes" in debutant
    assert "PARTIELLEMENT correctes" in expert


# ---------------------------------------------------------------------------
# Le cahier des charges donné au rédacteur
# ---------------------------------------------------------------------------

def test_le_prompt_porte_le_format_du_qcm():
    prompt = construire_prompt_externe("python", 2, nombre=3)
    for exige in ("qcm", "pourquoi_faux", "RATTRAPAGE", "quatre options",
                  "plus longue", "Palier de difficulté"):
        assert exige in prompt, f"« {exige} » absent du cahier des charges"


def test_le_prompt_montre_un_qcm_dans_son_gabarit():
    prompt = construire_prompt_externe("python", 2, nombre=3)
    debut = prompt.index("```json")
    gabarit = prompt[debut:prompt.index("```", debut + 7)]
    assert "\"qcm\"" in gabarit
    assert "\"pourquoi_faux\"" in gabarit


def test_une_matiere_de_vocabulaire_n_impose_pas_de_qcm():
    """
    Une carte qui demande la traduction d'un mot n'a pas de contexte à poser :
    lui imposer un QCM produirait quatre mots au hasard.

    Testé sur `gabarit_pour` et non sur le prompt complet, parce que les deux
    matières de vocabulaire du dépôt — `espagnol` et `anglais_info` — n'ont
    aucun `plan.json` et que la fabrique ne peut donc pas tourner sur elles.
    C'est un manque de contenu, relevé le 28 août ; ce n'est pas au test de
    l'attendre.
    """
    vocab = db.lire_manifeste(db.DOSSIER_CONTENUS / "espagnol")
    assert vocab["type_defaut"] == "vocabulaire"
    assert "qcm" not in gabarit_pour(vocab, 1)

    ordinaire = db.lire_manifeste(db.DOSSIER_CONTENUS / "python")
    assert "qcm" in gabarit_pour(ordinaire, 1)


def test_le_prompt_calibre_bien_le_niveau_demande():
    assert "1 à 3 (sur 10)" in construire_prompt_externe("python", 1, nombre=2)
    assert "7 à 10 (sur 10)" in construire_prompt_externe("python", 7, nombre=2)

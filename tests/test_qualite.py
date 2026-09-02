"""
Tests de la journalisation et des indices psychométriques.

Le test central est `test_la_discrimination_repere_une_question_ambigue` : il
simule une promo et vérifie que l'indice signale bien la carte piégée. Sans
lui, on livrerait des statistiques sans savoir si elles détectent quoi que ce
soit.
"""

import random
import tempfile
from pathlib import Path

import database
import qualite

BASE = Path(tempfile.gettempdir()) / "prompt_app_test_qualite.db"


def _base_neuve():
    BASE.unlink(missing_ok=True)
    database.init_db(BASE, forcer=True)
    qualite.init_journal(BASE)
    return BASE


def _cartes(n=None):
    cartes = database.lister_cartes(niveau=1, chemin=BASE)
    return cartes[:n] if n else cartes


def _tenter(carte_id, session, correct, **extra):
    return qualite.enregistrer_tentative(
        carte_id, session, extra.pop("reponse", "peu importe"),
        {"correct": correct,
         "statut": "correct" if correct else "incorrect",
         "source": "deterministe", "raison": ""},
        chemin=BASE, **extra)


# ---------------------------------------------------------------------------
# Identifiant de session
# ---------------------------------------------------------------------------

def test_identifiant_de_session_anonyme_accepte():
    assert qualite.session_valide("Sk3j9dl2mfqa8x7z")
    assert qualite.session_valide("abc-123_XYZ")


def test_identifiant_ressemblant_a_une_donnee_personnelle_refuse():
    """On ne veut pas d'adresse e-mail ni de nom saisi à la main en base."""
    for mauvais in ("jean.dupont@exemple.fr", "Jean Dupont", "", None, "abc"):
        assert not qualite.session_valide(mauvais), mauvais


def test_tentative_sans_session_valide_non_enregistree():
    _base_neuve()
    carte = _cartes(1)[0]
    assert _tenter(carte["id"], "jean@exemple.fr", True) is False
    assert qualite.premieres_tentatives(BASE) == []


# ---------------------------------------------------------------------------
# Journalisation
# ---------------------------------------------------------------------------

def test_une_tentative_est_enregistree():
    _base_neuve()
    carte = _cartes(1)[0]
    assert _tenter(carte["id"], "session-aaaa", True, duree_ms=4200,
                   indice_vu=True) is True

    lignes = qualite.premieres_tentatives(BASE)
    assert len(lignes) == 1
    assert lignes[0]["correct"] == 1
    assert lignes[0]["duree_ms"] == 4200
    assert lignes[0]["indice_vu"] == 1


def test_seule_la_premiere_tentative_compte():
    """
    Sinon les reprises gonflent le taux de réussite et la difficulté mesurée
    ne veut plus rien dire.
    """
    _base_neuve()
    carte = _cartes(1)[0]
    _tenter(carte["id"], "session-bbbb", False)
    _tenter(carte["id"], "session-bbbb", True)
    _tenter(carte["id"], "session-bbbb", True)

    lignes = qualite.premieres_tentatives(BASE)
    assert len(lignes) == 1
    assert lignes[0]["correct"] == 0, "c'est le premier essai qui fait foi"


def test_la_journalisation_ne_leve_jamais():
    """Un incident de journalisation ne doit jamais bloquer un apprenant."""
    assert qualite.enregistrer_tentative(
        1, "session-cccc", "x", {"correct": True},
        chemin=Path("/chemin/inexistant/ailleurs.db")) is False


# ---------------------------------------------------------------------------
# Indices
# ---------------------------------------------------------------------------

def test_la_difficulte_est_la_part_de_reussite():
    _base_neuve()
    carte = _cartes(1)[0]
    for i in range(10):
        _tenter(carte["id"], f"session-{i:04d}", correct=(i < 7))

    stat = next(s for s in qualite.statistiques_cartes(BASE)
                if s["carte_id"] == carte["id"])
    assert stat["reponses"] == 10
    assert stat["difficulte"] == 0.7


def test_aucun_indice_calcule_sous_le_seuil():
    """Avec cinq apprenants, les indices seraient du bruit : on se tait."""
    _base_neuve()
    carte = _cartes(1)[0]
    for i in range(5):
        _tenter(carte["id"], f"session-{i:04d}", correct=True)

    stat = next(s for s in qualite.statistiques_cartes(BASE)
                if s["carte_id"] == carte["id"])
    assert stat["discrimination"] is None
    assert stat["fiabilite"] == "insuffisant"
    assert qualite.diagnostics(BASE) == []


def test_la_discrimination_repere_une_question_ambigue():
    """
    LE test qui compte.

    On simule 60 apprenants d'aptitudes variées sur 12 cartes. Onze cartes se
    comportent normalement : plus l'apprenant est fort, plus il réussit. La
    douzième est AMBIGUË — on y répond à pile ou face, quel que soit le
    niveau. C'est exactement le profil de la carte « Parcourir un
    dictionnaire ».

    La discrimination doit s'effondrer sur elle, et sur elle seule.
    """
    _base_neuve()
    hasard = random.Random(20260818)
    cartes = _cartes(12)
    piegee = cartes[5]

    for i in range(60):
        session = f"session-{i:04d}"
        aptitude = (i + 1) / 61          # de 0,016 à 0,984
        for carte in cartes:
            if carte["id"] == piegee["id"]:
                reussi = hasard.random() < 0.5      # indépendant de l'aptitude
            else:
                reussi = hasard.random() < aptitude
            _tenter(carte["id"], session, reussi)

    stats = {s["carte_id"]: s for s in qualite.statistiques_cartes(BASE)}
    d_piegee = stats[piegee["id"]]["discrimination"]
    autres = [stats[c["id"]]["discrimination"] for c in cartes
              if c["id"] != piegee["id"]]

    assert d_piegee is not None
    assert d_piegee < qualite.DISCRIMINATION_FAIBLE, d_piegee
    assert min(autres) > qualite.DISCRIMINATION_FAIBLE, min(autres)

    signalees = {s["carte_id"] for s in qualite.diagnostics(BASE)
                 if s["probleme"] == "discrimination_faible"}
    assert signalees == {piegee["id"]}, "la carte ambiguë, et elle seule"


def test_les_formulations_refusees_frequentes_remontent():
    """La liste concrète des réponses à ajouter à `reponses_acceptees`."""
    _base_neuve()
    carte = _cartes(1)[0]
    for i in range(12):
        _tenter(carte["id"], f"session-{i:04d}", correct=False,
                reponse="les étiquettes" if i < 5 else f"variante {i}")

    stat = next(s for s in qualite.statistiques_cartes(BASE)
                if s["carte_id"] == carte["id"])
    formulations = {r["reponse"]: r["occurrences"] for r in stat["refus_frequents"]}
    assert formulations.get("les étiquettes") == 5

    problemes = {s["probleme"] for s in qualite.diagnostics(BASE)
                 if s["carte_id"] == carte["id"]}
    assert "formulations_a_ajouter" in problemes


def test_abandon_frequent_signale():
    _base_neuve()
    carte = _cartes(1)[0]
    for i in range(12):
        _tenter(carte["id"], f"session-{i:04d}", correct=False,
                solution_vue=(i < 9))

    problemes = {s["probleme"] for s in qualite.diagnostics(BASE)
                 if s["carte_id"] == carte["id"]}
    assert "abandon_frequent" in problemes


def test_carte_trop_facile_signalee():
    _base_neuve()
    carte = _cartes(1)[0]
    for i in range(20):
        _tenter(carte["id"], f"session-{i:04d}", correct=True)

    problemes = {s["probleme"] for s in qualite.diagnostics(BASE)
                 if s["carte_id"] == carte["id"]}
    assert "trop_facile" in problemes


# ---------------------------------------------------------------------------
# KR-20
# ---------------------------------------------------------------------------

def test_kr20_refuse_de_conclure_sans_donnees():
    _base_neuve()
    info = qualite.kr20(1, BASE)
    assert info["kr20"] is None
    assert info["interpretation"] == "données insuffisantes"


def test_kr20_calcule_sur_des_sessions_completes():
    _base_neuve()
    hasard = random.Random(7)
    cartes = database.lister_cartes(niveau=1, chemin=BASE)
    for i in range(15):
        aptitude = (i + 1) / 16
        for carte in cartes:                       # sessions COMPLÈTES
            _tenter(carte["id"], f"session-{i:04d}", hasard.random() < aptitude)

    info = qualite.kr20(1, BASE)
    assert info["sessions_completes"] == 15
    assert info["kr20"] is not None
    assert 0.0 < info["kr20"] <= 1.0
    assert info["kr20"] > 0.70, info["kr20"]


# ---------------------------------------------------------------------------
# Résumé
# ---------------------------------------------------------------------------

def test_le_resume_annonce_le_manque_de_volume():
    _base_neuve()
    r = qualite.resume(BASE)
    assert r["tentatives_totales"] == 0
    assert r["cartes_mesurables"] == 0
    assert "ne veulent rien dire" in r["message"]


def test_le_resume_compte_les_sessions():
    _base_neuve()
    cartes = _cartes(3)
    for i in range(4):
        for carte in cartes:
            _tenter(carte["id"], f"session-{i:04d}", correct=True)

    r = qualite.resume(BASE)
    assert r["sessions"] == 4
    assert r["tentatives_totales"] == 12


# ---------------------------------------------------------------------------
# Robustesse statistique
# ---------------------------------------------------------------------------

def test_borne_haute_de_correlation():
    """À n=70, l'erreur type vaut ~0,12 : la borne doit en tenir compte."""
    borne = qualite.borne_haute_correlation(0.0, 70)
    assert 0.15 < borne < 0.25, borne

    # Plus l'échantillon grandit, plus la borne se resserre sur l'estimation.
    assert qualite.borne_haute_correlation(0.0, 1000) < borne
    assert qualite.borne_haute_correlation(0.5, 100) > 0.5
    assert qualite.borne_haute_correlation(0.5, 3) is None


def test_une_discrimination_moyenne_bruitee_nest_pas_signalee():
    """
    Régression : avec un seuil brut à 0,20, une carte saine dont la
    discrimination mesurée tombait à 0,15 par hasard était accusée à tort.
    On exige désormais que la borne haute passe aussi sous le seuil.
    """
    _base_neuve()
    hasard = random.Random(4242)
    cartes = _cartes(10)
    for i in range(60):
        aptitude = (i + 1) / 61
        for carte in cartes:
            _tenter(carte["id"], f"session-{i:04d}", hasard.random() < aptitude)

    stats = qualite.statistiques_cartes(BASE)
    signalees = {s["carte_id"] for s in qualite.diagnostics(BASE)
                 if s["probleme"] == "discrimination_faible"}

    # Aucune carte n'est truquée ici : aucune ne doit être accusée,
    # même si l'estimation ponctuelle de l'une d'elles passe sous 0,20.
    assert signalees == set(), signalees
    assert any(s["discrimination"] is not None for s in stats)

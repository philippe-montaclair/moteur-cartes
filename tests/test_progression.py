"""
Tests de la persistance de la progression et de la file de révision.

`repetition.py` est testé séparément et sans base. Ici on vérifie ce que la
couche impure ajoute : l'écriture, la relecture, les compteurs du jour, et la
reprise d'une session anonyme.
"""

import secrets
from datetime import datetime, timedelta, timezone

import comptes
import database
import progression as P
import qualite
import repetition

MDP = "motdepasse-assez-long"
T0 = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)


def _compte():
    return comptes.creer_compte(f"p-{secrets.token_hex(5)}@test.fr", MDP)


def _cartes(n=3):
    return [c["id"] for c in database.lister_cartes(niveau=1)[:n]]


# ---------------------------------------------------------------------------
# Aller-retour en base
# ---------------------------------------------------------------------------

def test_un_etat_inconnu_est_l_etat_initial():
    compte = _compte()
    assert P.etat_de(compte["id"], 1) == repetition.etat_initial()


def test_l_etat_survit_a_la_relecture():
    compte = _compte()
    carte = _cartes(1)[0]
    ecrit = P.enregistrer(compte["id"], carte, 5, maintenant=T0, jitter=0.0)
    relu = P.etat_de(compte["id"], carte)
    for champ in ("etat", "facilite", "intervalle_j", "repetitions", "echecs"):
        assert relu[champ] == ecrit[champ], champ
    assert relu["du_le"] == ecrit["du_le"], "la date a été perdue à l'écriture"


def test_deux_reponses_ne_creent_qu_une_ligne():
    compte = _compte()
    carte = _cartes(1)[0]
    P.enregistrer(compte["id"], carte, 5, maintenant=T0, jitter=0.0)
    P.enregistrer(compte["id"], carte, 4, maintenant=T0, jitter=0.0)
    with database.connexion(database.CHEMIN_BASE) as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM progression WHERE compte_id = ? "
            "AND carte_id = ?", (compte["id"], carte)).fetchone()[0]
    assert n == 1


def test_deux_apprenants_ont_des_etats_independants():
    a, b = _compte(), _compte()
    carte = _cartes(1)[0]
    P.enregistrer(a["id"], carte, 5, maintenant=T0, jitter=0.0)
    assert P.etat_de(b["id"], carte)["etat"] == "neuve"


def test_suspendre_sort_la_carte_de_la_file():
    compte = _compte()
    cartes = _cartes(2)
    P.suspendre(compte["id"], cartes[0])
    file = P.file(compte["id"], niveau=1, maintenant=T0)
    assert cartes[0] not in [c["id"] for c in file]


# ---------------------------------------------------------------------------
# La file
# ---------------------------------------------------------------------------

def test_une_carte_vue_ne_revient_pas_tout_de_suite():
    compte = _compte()
    carte = _cartes(1)[0]
    P.enregistrer(compte["id"], carte, 5, maintenant=T0, jitter=0.0)
    file = P.file(compte["id"], niveau=1, maintenant=T0)
    assert carte not in [c["id"] for c in file]


def test_une_carte_due_revient():
    compte = _compte()
    carte = _cartes(1)[0]
    P.enregistrer(compte["id"], carte, 5, maintenant=T0, jitter=0.0)
    plus_tard = T0 + timedelta(days=3)
    file = P.file(compte["id"], niveau=1, maintenant=plus_tard)
    assert carte in [c["id"] for c in file]


def test_le_retard_passe_devant_le_neuf_en_base():
    compte = _compte()
    cartes = _cartes(3)
    P.enregistrer(compte["id"], cartes[2], 5, maintenant=T0, jitter=0.0)
    file = P.file(compte["id"], niveau=1, maintenant=T0 + timedelta(days=5))
    assert file[0]["id"] == cartes[2]


def test_la_file_respecte_le_plafond_de_neuves():
    compte = _compte()
    file = P.file(compte["id"], niveau=1, maintenant=T0)
    assert len(file) <= repetition.PLAFOND_NEUVES_PAR_JOUR


def test_la_limite_demandee_est_respectee():
    compte = _compte()
    assert len(P.file(compte["id"], niveau=1, limite=3, maintenant=T0)) == 3


# ---------------------------------------------------------------------------
# Compteurs du jour
# ---------------------------------------------------------------------------

def test_les_bornes_du_jour_encadrent_l_instant():
    debut, fin = P.bornes_du_jour(T0)
    assert debut <= T0 < fin
    assert (fin - debut) == timedelta(days=1)


def test_le_decalage_deplace_la_journee():
    """
    Un plafond quotidien qui se réinitialise à 2 h du matin est perçu comme un
    bug. Le décalage doit vraiment déplacer la borne — et dans le bon sens.

    Le sens est contre-intuitif et c'est pour ça qu'il est épinglé ici : pour un
    organisme à UTC+2, minuit local tombe à 22 h UTC **la veille**. La journée
    commence donc PLUS TÔT en UTC, pas plus tard. La première version de ce test
    affirmait l'inverse, le 28 août.
    """
    sans, _ = P.bornes_du_jour(T0, decalage_h=0)
    avec, _ = P.bornes_du_jour(T0, decalage_h=2)
    assert sans - avec == timedelta(hours=2)


def test_les_compteurs_partent_de_zero():
    compte = _compte()
    faits = P.compteurs_du_jour(compte["id"], T0)
    assert faits == {"neuves": 0, "revisions": 0}


# ---------------------------------------------------------------------------
# Reprise de la session anonyme
# ---------------------------------------------------------------------------

def _tenter_anonyme(session_id, carte_id, statut):
    return qualite.enregistrer_tentative(
        carte_id, session_id, "peu importe",
        {"correct": statut == "correct", "statut": statut,
         "source": "deterministe", "raison": ""})


def test_la_session_anonyme_est_reprise():
    compte = _compte()
    session_id = "anon-" + secrets.token_hex(4)
    cartes = _cartes(2)
    for carte in cartes:
        assert _tenter_anonyme(session_id, carte, "correct")

    reprises = P.rejouer_session(compte["id"], session_id)
    assert reprises == 2
    for carte in cartes:
        assert P.etat_de(compte["id"], carte)["etat"] != "neuve"


def test_la_reprise_ne_se_fait_qu_une_fois():
    """Rejouer deux fois doublerait la progression sans rien signaler."""
    compte = _compte()
    session_id = "anon-" + secrets.token_hex(4)
    _tenter_anonyme(session_id, _cartes(1)[0], "correct")
    assert P.rejouer_session(compte["id"], session_id) == 1
    assert P.rejouer_session(compte["id"], session_id) == 0


def test_la_reprise_ne_vole_pas_la_session_d_un_autre():
    a, b = _compte(), _compte()
    session_id = "anon-" + secrets.token_hex(4)
    _tenter_anonyme(session_id, _cartes(1)[0], "correct")
    assert P.rejouer_session(a["id"], session_id) == 1
    assert P.rejouer_session(b["id"], session_id) == 0
    assert P.resume(b["id"])["cartes_vues"] == 0


def test_une_session_vide_ne_fait_rien():
    compte = _compte()
    assert P.rejouer_session(compte["id"], "") == 0
    assert P.rejouer_session(compte["id"], "anon-jamais-vue") == 0


def test_un_echec_anonyme_est_repris_comme_un_echec():
    compte = _compte()
    session_id = "anon-" + secrets.token_hex(4)
    carte = _cartes(1)[0]
    _tenter_anonyme(session_id, carte, "incorrect")
    P.rejouer_session(compte["id"], session_id)
    assert P.etat_de(compte["id"], carte)["echecs"] == 1


# ---------------------------------------------------------------------------
# Résumé
# ---------------------------------------------------------------------------

def test_le_resume_compte_ce_qui_a_ete_vu():
    compte = _compte()
    cartes = _cartes(2)
    for carte in cartes:
        P.enregistrer(compte["id"], carte, 5, maintenant=T0, jitter=0.0)
    resume = P.resume(compte["id"])
    assert resume["cartes_vues"] == 2
    assert resume["cartes_total"] >= 2


def test_le_resume_d_un_compte_neuf_est_vide():
    assert P.resume(_compte()["id"])["cartes_vues"] == 0

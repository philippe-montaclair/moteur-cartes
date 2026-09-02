"""
Tests du moteur de répétition espacée.

Chaque test vise un défaut précis. Aucun ne se contente de vérifier qu'une
fonction rend quelque chose sur des données saines.

Le moteur est pur : ces tests n'ouvrent aucune base et ne touchent à aucun
fichier.
"""

from datetime import datetime, timedelta

import repetition as R

T0 = datetime(2026, 9, 1, 9, 0, 0)


# ---------------------------------------------------------------------------
# Traduction des verdicts en notes
# ---------------------------------------------------------------------------

def test_solution_revelee_vaut_zero():
    assert R.note_depuis_verdict("correct", solution_vue=True) == 0


def test_incorrect_vaut_un():
    assert R.note_depuis_verdict("incorrect") == 1


def test_rattrape_au_qcm_n_est_pas_une_maitrise():
    """Le point pédagogique central du QCM de rattrapage : reconnaître n'est
    pas produire. Une carte rattrapée ne doit jamais valoir 5."""
    assert R.note_depuis_verdict("rattrape") == 3
    assert R.note_depuis_verdict("correct", via_qcm=True) == 3


def test_indice_vu_abaisse_la_note():
    assert R.note_depuis_verdict("correct", indice_vu=True) == 3
    assert R.note_depuis_verdict("correct", indice_vu=False) == 5


def test_le_temps_separe_su_de_retrouve():
    rapide = R.note_depuis_verdict("correct", duree_ms=3000,
                                   duree_mediane_ms=8000)
    lent = R.note_depuis_verdict("correct", duree_ms=20000,
                                 duree_mediane_ms=8000)
    assert rapide == 5
    assert lent == 4


def test_sans_mediane_connue_on_ne_penalise_pas():
    """Régression : une carte neuve n'a pas de temps médian. Comparer à zéro
    classerait toutes les réponses en « lentes »."""
    assert R.note_depuis_verdict("correct", duree_ms=99999,
                                 duree_mediane_ms=0) == 5


# ---------------------------------------------------------------------------
# Le moteur
# ---------------------------------------------------------------------------

def test_note_hors_bornes_est_refusee():
    for mauvaise in (-1, 6, 2.5, "5", None):
        try:
            R.prochaine_echeance(R.etat_initial(), mauvaise, T0)
        except ValueError:
            continue
        except TypeError:
            continue
        raise AssertionError(f"note {mauvaise!r} acceptée à tort")


def test_carte_neuve_reussie_passe_par_les_etapes():
    etat = R.prochaine_echeance(R.etat_initial(), 4, T0)
    assert etat["etat"] == "apprentissage"
    assert etat["etape_appr"] == 1
    assert etat["du_le"] == T0 + timedelta(minutes=10)

    etat = R.prochaine_echeance(etat, 4, T0)
    assert etat["etat"] == "revision"
    assert etat["repetitions"] == 1
    assert etat["du_le"] == T0 + timedelta(days=1)


def test_note_cinq_fait_sauter_l_apprentissage():
    etat = R.prochaine_echeance(R.etat_initial(), 5, T0)
    assert etat["etat"] == "revision"
    assert etat["etape_appr"] == 0


def test_echec_ramene_la_carte_a_une_minute():
    etat = R.prochaine_echeance(R.etat_initial(), 5, T0)
    etat = R.prochaine_echeance(etat, 1, T0)
    assert etat["etat"] == "apprentissage"
    assert etat["repetitions"] == 0
    assert etat["intervalle_j"] == 0.0
    assert etat["du_le"] == T0 + timedelta(minutes=1)


def test_le_plancher_de_facilite_n_est_jamais_franchi():
    etat = R.etat_initial()
    for _ in range(50):
        etat = R.prochaine_echeance(etat, 1, T0)
    assert etat["facilite"] == R.FACILITE_PLANCHER


def test_facilite_monte_et_descend_des_bons_montants():
    depart = R.etat_initial()["facilite"]
    assert R.prochaine_echeance(R.etat_initial(), 5, T0)["facilite"] == \
        round(depart + R.FACILITE_FACILE, 4)
    assert R.prochaine_echeance(R.etat_initial(), 4, T0)["facilite"] == depart
    assert R.prochaine_echeance(R.etat_initial(), 3, T0)["facilite"] == \
        round(depart + R.FACILITE_DIFFICILE, 4)


def test_trois_echecs_marquent_la_carte_difficile():
    etat = R.etat_initial()
    for _ in range(R.ECHECS_AVANT_DIFFICILE):
        etat = R.prochaine_echeance(etat, 1, T0)
    assert etat["etat"] == "difficile"


def test_une_carte_difficile_redevient_ordinaire():
    etat = R.etat_initial()
    for _ in range(R.ECHECS_AVANT_DIFFICILE):
        etat = R.prochaine_echeance(etat, 1, T0)
    assert etat["etat"] == "difficile"
    etat = R.prochaine_echeance(etat, 5, T0)   # sort de l'apprentissage
    etat = R.prochaine_echeance(etat, 5, T0)
    assert etat["etat"] == "revision"


def test_les_intervalles_s_allongent():
    etat = R.prochaine_echeance(R.etat_initial(), 5, T0)   # → révision, 1 j
    assert etat["intervalle_j"] == 1
    etat = R.prochaine_echeance(etat, 4, T0)
    assert etat["intervalle_j"] == R.INTERVALLE_SECONDE_REVISION_J
    precedent = etat["intervalle_j"]
    etat = R.prochaine_echeance(etat, 4, T0)
    assert etat["intervalle_j"] > precedent


def test_difficile_allonge_moins_que_facile():
    base = R.prochaine_echeance(R.etat_initial(), 5, T0)
    base = R.prochaine_echeance(base, 4, T0)
    dur = R.prochaine_echeance(dict(base), 3, T0)["intervalle_j"]
    aise = R.prochaine_echeance(dict(base), 5, T0)["intervalle_j"]
    assert dur < aise


def test_le_moteur_est_deterministe_a_jitter_fixe():
    etat = R.prochaine_echeance(R.etat_initial(), 5, T0)
    a = R.prochaine_echeance(dict(etat), 4, T0, jitter=0.03)
    b = R.prochaine_echeance(dict(etat), 4, T0, jitter=0.03)
    assert a == b


def test_le_jitter_hors_bornes_est_ramene_aux_bornes():
    """Une erreur d'appel ne doit pas priver un apprenant de sa révision, ni
    lui envoyer la carte dans dix ans."""
    etat = R.prochaine_echeance(R.etat_initial(), 5, T0)
    exagere = R.prochaine_echeance(dict(etat), 4, T0, jitter=10.0)
    borne = R.prochaine_echeance(dict(etat), 4, T0, jitter=R.JITTER_MAX)
    assert exagere == borne


def test_une_carte_suspendue_ne_bouge_pas():
    etat = R.etat_initial()
    etat["etat"] = "suspendue"
    assert R.prochaine_echeance(dict(etat), 5, T0)["etat"] == "suspendue"


def test_un_etat_partiel_est_accepte():
    """Le moteur doit pouvoir être appelé sur une carte absente de la table
    `progression` — sinon la première réponse d'un apprenant plante."""
    etat = R.prochaine_echeance({"etat": "neuve"}, 5, T0)
    assert etat["facilite"] == round(R.FACILITE_INITIALE + R.FACILITE_FACILE, 4)


def test_les_champs_inconnus_sont_ignores():
    etat = R.prochaine_echeance({"etat": "neuve", "compte_id": 7,
                                 "bidon": "x"}, 4, T0)
    assert "compte_id" not in etat and "bidon" not in etat


# ---------------------------------------------------------------------------
# La file du jour
# ---------------------------------------------------------------------------

def _carte(cid, etat="revision", du=None):
    return {"carte_id": cid, "etat": etat, "du_le": du}


def test_le_retard_passe_avant_le_neuf():
    file = R.file_du_jour([
        _carte(1, "neuve"),
        _carte(2, "revision", T0 - timedelta(days=3)),
    ], T0)
    assert [c["carte_id"] for c in file] == [2, 1]


def test_la_plus_en_retard_passe_en_premier():
    file = R.file_du_jour([
        _carte(1, "revision", T0 - timedelta(days=1)),
        _carte(2, "revision", T0 - timedelta(days=9)),
    ], T0)
    assert [c["carte_id"] for c in file] == [2, 1]


def test_une_carte_pas_encore_due_est_ecartee():
    file = R.file_du_jour([_carte(1, "revision", T0 + timedelta(days=2))], T0)
    assert file == []


def test_une_carte_suspendue_n_est_jamais_proposee():
    file = R.file_du_jour([_carte(1, "suspendue", T0 - timedelta(days=5))], T0)
    assert file == []


def test_le_plafond_de_neuves_est_respecte():
    file = R.file_du_jour([_carte(i, "neuve") for i in range(100)], T0)
    assert len(file) == R.PLAFOND_NEUVES_PAR_JOUR


def test_le_plafond_compte_toutes_matieres_confondues():
    """Régression visée : compter par matière laisserait un apprenant qui suit
    trois matières recevoir soixante cartes neuves dans la journée."""
    file = R.file_du_jour([_carte(i, "neuve") for i in range(100)], T0,
                          deja_neuves=18)
    assert len(file) == 2


def test_plafond_deja_atteint_ne_rend_rien_de_neuf():
    file = R.file_du_jour([_carte(i, "neuve") for i in range(10)], T0,
                          deja_neuves=999)
    assert file == []

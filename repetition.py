"""
Répétition espacée — moteur pur.

Ce module ne lit rien, n'écrit rien, n'importe ni Flask ni sqlite3. Il prend un
état et une note, il rend un nouvel état. C'est la condition pour qu'on puisse
le remplacer un jour (FSRS ou autre) sans toucher à l'interface, et c'est la
condition pour que les tests soient reproductibles.

L'aléa n'est jamais tiré ici : il entre par le paramètre `jitter`. Un moteur qui
tire son propre hasard ne se teste pas.

Paramètres repris de la spécification espagnole, via FEUILLE_DE_ROUTE.md :
facteur de facilité initial 2,5, plancher 1,3, incréments 0,20 / 0,15 / 0,15,
deux étapes d'apprentissage à 1 et 10 minutes, variation aléatoire de ±5 %,
plafonds à 20 cartes neuves et 200 révisions par jour.

⚠️ L'AFFECTATION des trois incréments aux notes est une interprétation : la
spécification donne trois magnitudes (0,20 / 0,15 / 0,15) sans dire laquelle va
à quelle note. La lecture retenue est écrite ci-dessous, en clair, pour qu'elle
puisse être corrigée en un endroit si la spécification dit autre chose.
"""

from __future__ import annotations

from datetime import datetime, timedelta

# --------------------------------------------------------------------------
# Paramètres — tous nommés, aucun nombre magique dans le corps des fonctions
# --------------------------------------------------------------------------

FACILITE_INITIALE = 2.5
FACILITE_PLANCHER = 1.3

#: L'interprétation des trois incréments. À corriger ici, et nulle part ailleurs.
FACILITE_ECHEC = -0.20      # note 0-2 : la carte n'était pas sue
FACILITE_DIFFICILE = -0.15  # note 3   : sue, mais avec aide ou approximation
FACILITE_ACQUISE = 0.00     # note 4   : sue
FACILITE_FACILE = +0.15     # note 5   : sue vite et sans aide

#: Étapes d'apprentissage, en minutes. Une carte neuve les franchit avant
#: d'entrer en révision.
ETAPES_APPRENTISSAGE_MIN = (1, 10)

INTERVALLE_PREMIERE_REVISION_J = 1
INTERVALLE_SECONDE_REVISION_J = 6

#: Une réponse « difficile » en révision allonge à peine l'intervalle.
FACTEUR_DIFFICILE = 1.2

JITTER_MAX = 0.05           # ±5 %

PLAFOND_NEUVES_PAR_JOUR = 20
PLAFOND_REVISIONS_PAR_JOUR = 200

#: Nombre d'échecs à partir duquel la carte est marquée difficile. Ce n'est pas
#: une punition : c'est ce que le tableau de bord formateur remonte en premier.
ECHECS_AVANT_DIFFICILE = 3

ETATS = ("neuve", "apprentissage", "revision", "difficile", "suspendue")


def etat_initial() -> dict:
    """L'état d'une carte jamais vue. Aucune date : elle n'est pas encore due."""
    return {
        "etat": "neuve",
        "facilite": FACILITE_INITIALE,
        "intervalle_j": 0.0,
        "repetitions": 0,
        "echecs": 0,
        "etape_appr": 0,
        "du_le": None,
        "derniere_revue_le": None,
        "derniere_note": None,
    }


# --------------------------------------------------------------------------
# Du verdict de l'application à la note du moteur
# --------------------------------------------------------------------------

def note_depuis_verdict(statut: str, *, indice_vu: bool = False,
                        via_qcm: bool = False, solution_vue: bool = False,
                        duree_ms: int = 0, duree_mediane_ms: int = 0) -> int:
    """
    Traduit un verdict de l'application en note 0-5.

    C'est une décision pédagogique, pas un détail d'implémentation — d'où sa
    place dans une fonction nommée et testée plutôt que noyée dans une route.

    Les deux règles qui comptent :
      * une carte réussie au QCM de rattrapage n'est pas une carte maîtrisée ;
      * le temps de réponse sépare « su » de « retrouvé ».
    """
    if solution_vue:
        return 0
    if statut == "incorrect":
        return 1
    if statut in ("proche", "rattrape"):
        return 3
    if statut == "correct":
        if via_qcm:
            return 3
        if indice_vu:
            return 3
        if duree_mediane_ms and duree_ms > duree_mediane_ms:
            return 4
        return 5
    # Statut inconnu : on ne devine pas, on traite comme un échec léger.
    return 3


# --------------------------------------------------------------------------
# Le moteur
# --------------------------------------------------------------------------

def _borner_facilite(valeur: float) -> float:
    return max(FACILITE_PLANCHER, round(valeur, 4))


def _delta_facilite(note: int) -> float:
    if note <= 2:
        return FACILITE_ECHEC
    if note == 3:
        return FACILITE_DIFFICILE
    if note == 4:
        return FACILITE_ACQUISE
    return FACILITE_FACILE


def _applique_jitter(intervalle_j: float, jitter: float) -> float:
    """`jitter` est une fraction dans [-JITTER_MAX, +JITTER_MAX], fournie par
    l'appelant. Hors bornes, elle est ramenée aux bornes plutôt que refusée :
    une erreur d'appel ne doit pas priver un apprenant de sa révision."""
    jitter = max(-JITTER_MAX, min(JITTER_MAX, jitter))
    return round(intervalle_j * (1.0 + jitter), 4)


def prochaine_echeance(etat: dict, note: int, maintenant: datetime,
                       jitter: float = 0.0) -> dict:
    """
    Rend un NOUVEL état. N'écrit rien, ne lit rien, ne tire aucun hasard.

    `etat` peut être un état partiel ou vide : les champs manquants prennent
    la valeur de `etat_initial()`. C'est ce qui permet d'appeler le moteur sur
    une carte encore absente de la table `progression`.
    """
    if not isinstance(note, int) or not 0 <= note <= 5:
        raise ValueError(f"note hors bornes : {note!r} (attendu 0 à 5)")

    nouveau = etat_initial()
    nouveau.update({c: v for c, v in (etat or {}).items() if c in nouveau})

    if nouveau["etat"] == "suspendue":
        return nouveau  # une carte suspendue ne bouge pas

    nouveau["facilite"] = _borner_facilite(nouveau["facilite"] + _delta_facilite(note))
    nouveau["derniere_note"] = note
    nouveau["derniere_revue_le"] = maintenant

    en_apprentissage = nouveau["etat"] in ("neuve", "apprentissage")

    # ---- Échec : la carte redescend, quel que soit son état ----------------
    if note <= 2:
        nouveau["echecs"] += 1
        nouveau["repetitions"] = 0
        nouveau["etape_appr"] = 0
        nouveau["intervalle_j"] = 0.0
        nouveau["etat"] = ("difficile"
                           if nouveau["echecs"] >= ECHECS_AVANT_DIFFICILE
                           else "apprentissage")
        nouveau["du_le"] = maintenant + timedelta(
            minutes=ETAPES_APPRENTISSAGE_MIN[0])
        return nouveau

    # ---- Réussite pendant l'apprentissage ---------------------------------
    if en_apprentissage:
        derniere_etape = nouveau["etape_appr"] + 1 >= len(ETAPES_APPRENTISSAGE_MIN)
        if note == 5 or derniere_etape:
            # Sortie d'apprentissage : la carte entre en révision.
            nouveau["etat"] = "revision"
            nouveau["repetitions"] = 1
            nouveau["etape_appr"] = 0
            nouveau["intervalle_j"] = _applique_jitter(
                INTERVALLE_PREMIERE_REVISION_J, jitter)
        else:
            nouveau["etape_appr"] += 1
            nouveau["etat"] = "apprentissage"
            nouveau["du_le"] = maintenant + timedelta(
                minutes=ETAPES_APPRENTISSAGE_MIN[nouveau["etape_appr"]])
            return nouveau
    # ---- Réussite en révision ---------------------------------------------
    else:
        nouveau["repetitions"] += 1
        if nouveau["repetitions"] == 1:
            base = INTERVALLE_PREMIERE_REVISION_J
        elif nouveau["repetitions"] == 2:
            base = INTERVALLE_SECONDE_REVISION_J
        elif note == 3:
            base = max(INTERVALLE_PREMIERE_REVISION_J,
                       nouveau["intervalle_j"] * FACTEUR_DIFFICILE)
        else:
            base = max(INTERVALLE_PREMIERE_REVISION_J,
                       nouveau["intervalle_j"] * nouveau["facilite"])
        nouveau["intervalle_j"] = _applique_jitter(base, jitter)
        # Une carte difficile qui repasse deux révisions de suite redevient
        # une carte de révision ordinaire.
        if nouveau["etat"] == "difficile" and nouveau["repetitions"] >= 2:
            nouveau["etat"] = "revision"

    nouveau["du_le"] = maintenant + timedelta(days=nouveau["intervalle_j"])
    return nouveau


# --------------------------------------------------------------------------
# La file du jour
# --------------------------------------------------------------------------

def file_du_jour(candidats, maintenant: datetime, *,
                 deja_neuves: int = 0, deja_revisions: int = 0,
                 plafond_neuves: int = PLAFOND_NEUVES_PAR_JOUR,
                 plafond_revisions: int = PLAFOND_REVISIONS_PAR_JOUR,
                 limite: int | None = None) -> list:
    """
    Ordonne et plafonne les cartes à présenter.

    `candidats` : itérable de dicts portant au moins `carte_id`, `etat`,
    `du_le` (datetime ou None).

    Ordre : ce qui est en retard d'abord — une carte oubliée coûte plus cher
    qu'une carte neuve non vue —, puis les cartes difficiles, puis les neuves.

    Les plafonds sont comptés PAR APPRENANT ET PAR JOUR, toutes matières
    confondues. Compter par matière laisserait un apprenant qui suit trois
    matières recevoir soixante cartes neuves dans la journée.
    """
    dues, difficiles, neuves = [], [], []
    for c in candidats:
        etat = c.get("etat", "neuve")
        if etat == "suspendue":
            continue
        if etat == "neuve" or c.get("du_le") is None:
            neuves.append(c)
        elif c["du_le"] <= maintenant:
            (difficiles if etat == "difficile" else dues).append(c)

    dues.sort(key=lambda c: (c["du_le"], c["carte_id"]))
    difficiles.sort(key=lambda c: (c["du_le"], c["carte_id"]))
    neuves.sort(key=lambda c: c["carte_id"])

    place_revisions = max(0, plafond_revisions - deja_revisions)
    place_neuves = max(0, plafond_neuves - deja_neuves)

    revisions = (dues + difficiles)[:place_revisions]
    file = revisions + neuves[:place_neuves]
    return file[:limite] if limite else file

"""
Persistance de la progression — la couche impure autour de `repetition.py`.

Séparation à tenir : `repetition.py` décide, ce module écrit. Tout ce qui est
hasard, horloge et base de données vit ici ; rien de tout cela ne descend dans
le moteur, sinon il cesse d'être testable et remplaçable.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import database
import migrations
import repetition

FORMAT = "%Y-%m-%d %H:%M:%S"

CHAMPS = ("etat", "facilite", "intervalle_j", "repetitions", "echecs",
          "etape_appr", "du_le", "derniere_revue_le", "derniere_note")


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


def _texte(quand):
    if quand is None:
        return None
    return quand.strftime(FORMAT) if isinstance(quand, datetime) else str(quand)


def _date(texte):
    if not texte:
        return None
    if isinstance(texte, datetime):
        return texte
    try:
        return datetime.strptime(str(texte)[:19], FORMAT).replace(
            tzinfo=timezone.utc)
    except ValueError:
        return None


def _connexion(chemin=None):
    return database.connexion(chemin or database.CHEMIN_BASE)


def init_progression(chemin=None) -> int:
    with _connexion(chemin) as conn:
        return migrations.migrer(conn)


# ---------------------------------------------------------------------------
# Lecture et écriture d'un état
# ---------------------------------------------------------------------------

def etat_de(compte_id: int, carte_id: int, chemin=None) -> dict:
    with _connexion(chemin) as conn:
        ligne = conn.execute(
            "SELECT * FROM progression WHERE compte_id = ? AND carte_id = ?",
            (int(compte_id), int(carte_id))).fetchone()
    if ligne is None:
        return repetition.etat_initial()
    etat = repetition.etat_initial()
    for champ in CHAMPS:
        valeur = ligne[champ]
        etat[champ] = _date(valeur) if champ.endswith("_le") else valeur
    return etat


def _ecrire(compte_id: int, carte_id: int, etat: dict, conn) -> None:
    conn.execute(
        """INSERT INTO progression
             (compte_id, carte_id, etat, facilite, intervalle_j, repetitions,
              echecs, etape_appr, du_le, derniere_revue_le, derniere_note)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(compte_id, carte_id) DO UPDATE SET
             etat=excluded.etat, facilite=excluded.facilite,
             intervalle_j=excluded.intervalle_j,
             repetitions=excluded.repetitions, echecs=excluded.echecs,
             etape_appr=excluded.etape_appr, du_le=excluded.du_le,
             derniere_revue_le=excluded.derniere_revue_le,
             derniere_note=excluded.derniere_note""",
        (int(compte_id), int(carte_id), etat["etat"], etat["facilite"],
         etat["intervalle_j"], etat["repetitions"], etat["echecs"],
         etat["etape_appr"], _texte(etat["du_le"]),
         _texte(etat["derniere_revue_le"]), etat["derniere_note"]))


def enregistrer(compte_id: int, carte_id: int, note: int, maintenant=None,
                jitter=None, chemin=None) -> dict:
    """
    Applique le moteur et écrit le résultat. Rend le nouvel état.

    Le hasard est tiré ICI, jamais dans le moteur : c'est ce qui permet aux
    tests du moteur d'être reproductibles et à celui-ci d'être réaliste.
    """
    maintenant = maintenant or _maintenant()
    if jitter is None:
        jitter = random.uniform(-repetition.JITTER_MAX, repetition.JITTER_MAX)

    avant = etat_de(compte_id, carte_id, chemin=chemin)
    apres = repetition.prochaine_echeance(avant, note, maintenant, jitter)
    with _connexion(chemin) as conn:
        _ecrire(compte_id, carte_id, apres, conn)
    return apres


def suspendre(compte_id: int, carte_id: int, suspendue=True, chemin=None) -> None:
    etat = etat_de(compte_id, carte_id, chemin=chemin)
    etat["etat"] = "suspendue" if suspendue else "revision"
    with _connexion(chemin) as conn:
        _ecrire(compte_id, carte_id, etat, conn)


# ---------------------------------------------------------------------------
# Compteurs du jour
# ---------------------------------------------------------------------------

def bornes_du_jour(maintenant=None, decalage_h: float = 0.0):
    """
    Début et fin du « jour » d'un apprenant.

    `cree_le` est écrit par SQLite en UTC. Le décalage permet à un organisme de
    faire commencer la journée à minuit chez lui plutôt qu'à 2 h du matin — un
    plafond quotidien qui se réinitialise en pleine nuit est perçu comme un
    bug. Le réglage vivra plus tard dans les préférences de l'organisme ; il est
    ici pour que la question soit posée dans le code et pas oubliée.
    """
    maintenant = maintenant or _maintenant()
    local = maintenant + timedelta(hours=decalage_h)
    debut_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
    debut = debut_local - timedelta(hours=decalage_h)
    return debut, debut + timedelta(days=1)


def compteurs_du_jour(compte_id: int, maintenant=None, decalage_h: float = 0.0,
                      chemin=None) -> dict:
    """
    Cartes neuves et révisions déjà faites aujourd'hui, TOUTES MATIÈRES
    CONFONDUES. Compter par matière laisserait un apprenant qui suit trois
    matières recevoir soixante cartes neuves dans la journée.

    « Neuve » se lit dans les données, sans colonne supplémentaire : une carte
    est neuve aujourd'hui si sa PREMIÈRE tentative de cet apprenant date
    d'aujourd'hui.
    """
    debut, fin = bornes_du_jour(maintenant, decalage_h)
    d, f = _texte(debut), _texte(fin)
    with _connexion(chemin) as conn:
        neuves = conn.execute(
            "SELECT COUNT(*) FROM (SELECT carte_id, MIN(cree_le) AS premiere "
            "FROM tentatives WHERE compte_id = ? GROUP BY carte_id) "
            "WHERE premiere >= ? AND premiere < ?",
            (int(compte_id), d, f)).fetchone()[0]
        vues = conn.execute(
            "SELECT COUNT(DISTINCT carte_id) FROM tentatives "
            "WHERE compte_id = ? AND cree_le >= ? AND cree_le < ?",
            (int(compte_id), d, f)).fetchone()[0]
    return {"neuves": neuves, "revisions": max(0, vues - neuves)}


# ---------------------------------------------------------------------------
# La file de révision
# ---------------------------------------------------------------------------

def file(compte_id: int, matiere=None, niveau=None, limite=None,
         maintenant=None, decalage_h: float = 0.0, chemin=None) -> list[dict]:
    """
    Les cartes à présenter maintenant, dans l'ordre, plafonds appliqués.

    Rend les cartes complètes — le frontend n'a pas à faire un second appel.
    """
    maintenant = maintenant or _maintenant()
    cartes = database.lister_cartes(niveau=niveau, matiere=matiere,
                                    chemin=chemin)
    with _connexion(chemin) as conn:
        etats = {r["carte_id"]: r for r in conn.execute(
            "SELECT * FROM progression WHERE compte_id = ?",
            (int(compte_id),))}

    candidats = []
    for carte in cartes:
        ligne = etats.get(carte["id"])
        candidats.append({
            "carte_id": carte["id"],
            "etat": ligne["etat"] if ligne else "neuve",
            "du_le": _date(ligne["du_le"]) if ligne else None,
            "_carte": carte,
        })

    faits = compteurs_du_jour(compte_id, maintenant, decalage_h, chemin=chemin)
    choisis = repetition.file_du_jour(
        candidats, maintenant, deja_neuves=faits["neuves"],
        deja_revisions=faits["revisions"], limite=limite)
    return [c["_carte"] for c in choisis]


def resume(compte_id: int, matiere=None, chemin=None) -> dict:
    """Vue d'ensemble pour l'apprenant — et brique du tableau de bord."""
    with _connexion(chemin) as conn:
        lignes = list(conn.execute(
            "SELECT etat, COUNT(*) AS n FROM progression "
            "WHERE compte_id = ? GROUP BY etat", (int(compte_id),)))
        total_cartes = len(database.lister_cartes(matiere=matiere,
                                                  chemin=chemin))
        temps = conn.execute(
            "SELECT COALESCE(SUM(duree_ms), 0) FROM tentatives "
            "WHERE compte_id = ?", (int(compte_id),)).fetchone()[0]
    par_etat = {r["etat"]: r["n"] for r in lignes}
    vues = sum(par_etat.values())
    return {
        "cartes_total": total_cartes,
        "cartes_vues": vues,
        "par_etat": par_etat,
        "maitrisees": par_etat.get("revision", 0),
        "fragiles": par_etat.get("difficile", 0),
        "dues": len(file(compte_id, matiere=matiere, chemin=chemin)),
        "temps_ms": temps,
    }


# ---------------------------------------------------------------------------
# Reprise du visiteur anonyme
# ---------------------------------------------------------------------------

def rejouer_session(compte_id: int, session_id: str, chemin=None) -> int:
    """
    Rattache les tentatives d'une session anonyme à un compte, et reconstruit
    la progression en les rejouant **dans l'ordre chronologique**.

    Rejouer dans le désordre donnerait un état faux sans rien signaler : le
    moteur est séquentiel par construction.

    Rend le nombre de tentatives reprises. Idempotent : une tentative déjà
    rattachée à un compte n'est jamais reprise deux fois.
    """
    if not session_id:
        return 0
    with _connexion(chemin) as conn:
        lignes = list(conn.execute(
            "SELECT id, carte_id, statut, indice_vu, solution_vue, duree_ms, "
            "via_qcm, cree_le FROM tentatives "
            "WHERE session_id = ? AND compte_id IS NULL ORDER BY id",
            (str(session_id),)))
        if not lignes:
            return 0
        conn.execute(
            "UPDATE tentatives SET compte_id = ? "
            "WHERE session_id = ? AND compte_id IS NULL",
            (int(compte_id), str(session_id)))

    for ligne in lignes:
        note = repetition.note_depuis_verdict(
            ligne["statut"],
            indice_vu=bool(ligne["indice_vu"]),
            via_qcm=bool(ligne["via_qcm"]),
            solution_vue=bool(ligne["solution_vue"]))
        enregistrer(compte_id, ligne["carte_id"], note,
                    maintenant=_date(ligne["cree_le"]) or _maintenant(),
                    jitter=0.0, chemin=chemin)
    return len(lignes)

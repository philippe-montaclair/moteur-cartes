"""
Journalisation des tentatives et mesure de la qualité des questions.

POURQUOI CE MODULE
------------------
Une question ambiguë ne se voit pas à la relecture — la carte « Parcourir un
dictionnaire » a passé la relecture et le contrôle d'intégrité avant qu'un
apprenant ne bute dessus en trente secondes.

Elle se voit dans les DONNÉES. C'est le rôle de la psychométrie, et les
indices utilisés ici sont ceux de la théorie classique des tests :

- **difficulté (p)** : part d'apprenants qui réussissent l'item.
- **discrimination (corrélation point-bisériale corrigée)** : l'item
  sépare-t-il ceux qui maîtrisent de ceux qui ne maîtrisent pas ? Une question
  ambiguë est ratée autant par les bons que par les faibles : sa
  discrimination s'effondre. **C'est l'indice qui aurait signalé la carte du
  dictionnaire automatiquement.**
- **KR-20 (alpha de Cronbach pour items binaires)** : le niveau mesure-t-il
  une compétence cohérente ?

HONNÊTETÉ STATISTIQUE
---------------------
Ces indices exigent du volume. Avec cinq apprenants, ce sont des nombres au
hasard. Chaque résultat est donc accompagné d'un niveau de fiabilité, et rien
n'est affirmé en dessous du seuil (voir `FIABILITE`).
"""

from __future__ import annotations

import math
import re
from collections import defaultdict

import migrations
from database import CHEMIN_BASE, connexion, lister_cartes

# ---------------------------------------------------------------------------
# Seuils
# ---------------------------------------------------------------------------

#: Nombre de réponses distinctes nécessaires pour interpréter un indice.
FIABILITE = (
    (100, "fiable"),
    (30, "provisoire"),
    (10, "indicatif"),
    (0, "insuffisant"),
)

#: En dessous, aucune discrimination n'est calculée : le bruit dominerait.
MIN_DISCRIMINATION = 10

#: Un item hors de cette plage de difficulté n'apprend plus rien sur personne.
DIFFICULTE_TROP_FACILE = 0.95
DIFFICULTE_TROP_DIFFICILE = 0.20

#: Sous ce seuil, l'item ne sépare pas les apprenants : à revoir.
DISCRIMINATION_FAIBLE = 0.20

#: Sessions complètes nécessaires pour un KR-20 interprétable.
MIN_SESSIONS_KR20 = 10

#: Une formulation refusée n'est signalée que si elle revient chez plusieurs
#: apprenants ET représente une part notable des réponses. Sans ce double
#: seuil, la file de relecture se remplit de cas isolés.
MIN_REFUS_OCCURRENCES = 3
MIN_REFUS_PART = 0.05


SCHEMA = """
CREATE TABLE IF NOT EXISTS tentatives (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    carte_id      INTEGER NOT NULL,
    session_id    TEXT    NOT NULL,
    reponse       TEXT    NOT NULL DEFAULT '',
    correct       INTEGER NOT NULL,
    statut        TEXT    NOT NULL DEFAULT '',
    source        TEXT    NOT NULL DEFAULT '',
    raison        TEXT    NOT NULL DEFAULT '',
    indice_vu     INTEGER NOT NULL DEFAULT 0,
    solution_vue  INTEGER NOT NULL DEFAULT 0,
    duree_ms      INTEGER NOT NULL DEFAULT 0,
    cree_le       TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_tentatives_carte   ON tentatives(carte_id);
CREATE INDEX IF NOT EXISTS idx_tentatives_session ON tentatives(session_id);
"""

_SESSION_VALIDE = re.compile(r"^[A-Za-z0-9_-]{6,64}$")


def init_journal(chemin=None) -> None:
    """
    Prépare le journal.

    Depuis le 28 août, ce n'est plus un `CREATE TABLE IF NOT EXISTS` : c'est
    `migrations.migrer()`. Motif écrit en tête de `migrations.py` — élargir un
    `IF NOT EXISTS` sur une base existante ne fait rien, sans erreur et sans
    message. Le schéma du journal vit désormais dans les migrations, et
    `SCHEMA` n'est conservé que comme documentation de l'état d'origine.
    """
    with connexion(chemin or CHEMIN_BASE) as conn:
        migrations.migrer(conn)


# ---------------------------------------------------------------------------
# Écriture
# ---------------------------------------------------------------------------

def session_valide(session_id) -> bool:
    """
    Un identifiant de session est un jeton anonyme tiré par le navigateur.

    Il ne contient aucune donnée personnelle : on refuse tout ce qui pourrait
    en être une (adresse e-mail, nom saisi à la main…).
    """
    return bool(session_id) and bool(_SESSION_VALIDE.match(str(session_id)))


def enregistrer_tentative(carte_id, session_id, reponse, resultat,
                          duree_ms=0, indice_vu=False, solution_vue=False,
                          chemin=None, compte_id=None, via_qcm=False,
                          note=None) -> bool:
    """
    Enregistre une tentative. Ne lève jamais : la journalisation ne doit
    jamais empêcher un apprenant de travailler.
    """
    if not session_valide(session_id):
        return False
    try:
        init_journal(chemin)
        with connexion(chemin or CHEMIN_BASE) as conn:
            conn.execute(
                """INSERT INTO tentatives
                   (carte_id, session_id, reponse, correct, statut, source,
                    raison, indice_vu, solution_vue, duree_ms,
                    compte_id, via_qcm, note)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    int(carte_id), str(session_id), str(reponse)[:500],
                    int(bool(resultat.get("correct"))),
                    str(resultat.get("statut", "")),
                    str(resultat.get("source", "")),
                    str(resultat.get("raison", "")),
                    int(bool(indice_vu)), int(bool(solution_vue)),
                    max(0, int(duree_ms or 0)),
                    int(compte_id) if compte_id else None,
                    int(bool(via_qcm)),
                    int(note) if note is not None else None,
                ),
            )
        return True
    except Exception as e:  # base verrouillée, disque plein…
        print(f"[journal] tentative non enregistrée : {e}")
        return False


def purger_journal(chemin=None) -> int:
    with connexion(chemin or CHEMIN_BASE) as conn:
        migrations.migrer(conn)
        n = conn.execute("SELECT COUNT(*) FROM tentatives").fetchone()[0]
        conn.execute("DELETE FROM tentatives")
    return n


# ---------------------------------------------------------------------------
# Statistiques élémentaires
# ---------------------------------------------------------------------------

def _fiabilite(n: int) -> str:
    for seuil, etiquette in FIABILITE:
        if n >= seuil:
            return etiquette
    return "insuffisant"


def borne_haute_correlation(r: float, n: int, z: float = 1.645) -> float | None:
    """
    Borne haute de l'intervalle de confiance à 90 % d'une corrélation
    (transformation z de Fisher).

    POURQUOI CE N'EST PAS UN LUXE
    -----------------------------
    L'erreur type d'une corrélation vaut environ 1/√(n−3), soit ±0,12 pour 70
    apprenants. Comparer le point estimé à un seuil brut de 0,20 revient donc
    à signaler du bruit une fois sur deux : on accuserait des questions
    parfaitement saines.

    On ne signale un item que si l'on est raisonnablement sûr que sa
    discrimination est VRAIMENT basse — c'est-à-dire si même la borne haute
    passe sous le seuil.
    """
    if n < 5 or r is None or abs(r) >= 1:
        return None
    zr = math.atanh(r)
    erreur = 1 / math.sqrt(n - 3)
    return math.tanh(zr + z * erreur)


def _pearson(x: list[float], y: list[float]) -> float | None:
    """Corrélation de Pearson, en Python pur — pas de dépendance."""
    n = len(x)
    if n < 3:
        return None
    mx, my = sum(x) / n, sum(y) / n
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    dx = math.sqrt(sum((a - mx) ** 2 for a in x))
    dy = math.sqrt(sum((b - my) ** 2 for b in y))
    if dx == 0 or dy == 0:      # aucune variance : indice non défini
        return None
    return num / (dx * dy)


def premieres_tentatives(chemin=None) -> list[dict]:
    """
    Une seule tentative par (session, carte) : la PREMIÈRE.

    Sans cela, les reprises gonflent artificiellement le taux de réussite et
    la difficulté mesurée n'a plus de sens.
    """
    init_journal(chemin)
    with connexion(chemin or CHEMIN_BASE) as conn:
        lignes = conn.execute(
            """SELECT t.* FROM tentatives t
               JOIN (SELECT session_id, carte_id, MIN(id) AS premier
                     FROM tentatives GROUP BY session_id, carte_id) p
                 ON t.id = p.premier
               ORDER BY t.id"""
        ).fetchall()
    return [dict(l) for l in lignes]


def _matrice(tentatives) -> dict[str, dict[int, int]]:
    """session -> {carte: 0|1}"""
    matrice: dict[str, dict[int, int]] = defaultdict(dict)
    for t in tentatives:
        matrice[t["session_id"]][t["carte_id"]] = int(t["correct"])
    return matrice


# ---------------------------------------------------------------------------
# Indices par carte
# ---------------------------------------------------------------------------

def statistiques_cartes(chemin=None) -> list[dict]:
    """Difficulté, discrimination et signaux d'usage, carte par carte."""
    tentatives = premieres_tentatives(chemin)
    matrice = _matrice(tentatives)
    cartes = {c["id"]: c for c in lister_cartes(chemin=chemin)}

    par_carte: dict[int, list[dict]] = defaultdict(list)
    for t in tentatives:
        par_carte[t["carte_id"]].append(t)

    resultats = []
    for carte_id, carte in cartes.items():
        essais = par_carte.get(carte_id, [])
        n = len(essais)
        reussites = sum(t["correct"] for t in essais)

        stat = {
            "carte_id": carte_id,
            "titre": carte["titre"],
            "niveau": carte["niveau"],
            "categorie": carte["categorie"],
            "type": carte["type"],
            "reponses": n,
            "fiabilite": _fiabilite(n),
            "difficulte": round(reussites / n, 3) if n else None,
            "discrimination": None,
            "discrimination_borne_haute": None,
            "taux_proche": None,
            "taux_indice": None,
            "taux_solution": None,
            "duree_mediane_ms": None,
            "refus_frequents": [],
        }

        if n:
            stat["taux_proche"] = round(
                sum(1 for t in essais if t["statut"] == "proche") / n, 3)
            stat["taux_indice"] = round(
                sum(1 for t in essais if t["indice_vu"]) / n, 3)
            stat["taux_solution"] = round(
                sum(1 for t in essais if t["solution_vue"]) / n, 3)
            durees = sorted(t["duree_ms"] for t in essais if t["duree_ms"] > 0)
            if durees:
                stat["duree_mediane_ms"] = durees[len(durees) // 2]

            # Les formulations refusées les plus fréquentes : c'est la liste
            # concrète des réponses à ajouter à `reponses_acceptees`.
            refus: dict[str, int] = defaultdict(int)
            for t in essais:
                if not t["correct"] and t["reponse"].strip():
                    refus[t["reponse"].strip().lower()] += 1
            # Seuil double : au moins 3 apprenants ET au moins 5 % d'entre
            # eux. Sans la part relative, la file de relecture se remplirait
            # de formulations marginales et deviendrait inutilisable.
            stat["refus_frequents"] = [
                {"reponse": r, "occurrences": c, "part": round(c / n, 3)}
                for r, c in sorted(refus.items(), key=lambda kv: -kv[1])[:5]
                if c >= MIN_REFUS_OCCURRENCES and c / n >= MIN_REFUS_PART
            ]

        # Discrimination : corrélation entre la réussite à CET item et le
        # score de l'apprenant sur TOUS LES AUTRES (corrélation corrigée).
        if n >= MIN_DISCRIMINATION:
            item, reste = [], []
            for session, reponses in matrice.items():
                if carte_id not in reponses:
                    continue
                autres = [v for c, v in reponses.items() if c != carte_id]
                if not autres:
                    continue
                item.append(reponses[carte_id])
                reste.append(sum(autres) / len(autres))
            r = _pearson(item, reste)
            if r is not None:
                stat["discrimination"] = round(r, 3)
                borne = borne_haute_correlation(r, len(item))
                if borne is not None:
                    stat["discrimination_borne_haute"] = round(borne, 3)

        resultats.append(stat)

    return sorted(resultats, key=lambda s: (s["niveau"], s["carte_id"]))


# ---------------------------------------------------------------------------
# Cohérence interne d'un niveau
# ---------------------------------------------------------------------------

def kr20(niveau: int, chemin=None) -> dict:
    """
    KR-20 : cohérence interne d'un niveau (items binaires).

    Calculé uniquement sur les sessions ayant répondu à TOUTES les cartes du
    niveau — une matrice à trous rendrait l'indice ininterprétable.
    """
    cartes = [c["id"] for c in lister_cartes(niveau=niveau, chemin=chemin)]
    matrice = _matrice(premieres_tentatives(chemin))
    completes = [
        [reponses[c] for c in cartes]
        for reponses in matrice.values()
        if all(c in reponses for c in cartes)
    ]

    info = {
        "niveau": niveau,
        "cartes": len(cartes),
        "sessions_completes": len(completes),
        "kr20": None,
        "interpretation": "données insuffisantes",
    }
    if len(completes) < MIN_SESSIONS_KR20 or len(cartes) < 2:
        return info

    k = len(cartes)
    n = len(completes)
    variances = 0.0
    for i in range(k):
        p = sum(ligne[i] for ligne in completes) / n
        variances += p * (1 - p)

    totaux = [sum(ligne) for ligne in completes]
    moyenne = sum(totaux) / n
    var_totale = sum((t - moyenne) ** 2 for t in totaux) / n
    if var_totale == 0:
        return info

    valeur = (k / (k - 1)) * (1 - variances / var_totale)
    info["kr20"] = round(valeur, 3)
    info["interpretation"] = (
        "bonne cohérence" if valeur >= 0.80 else
        "cohérence acceptable" if valeur >= 0.70 else
        "cohérence faible — le niveau mélange des compétences différentes"
    )
    return info


# ---------------------------------------------------------------------------
# Diagnostic : la file de relecture
# ---------------------------------------------------------------------------

def diagnostics(chemin=None) -> list[dict]:
    """
    Ce que tu dois relire, et rien d'autre.

    Chaque signalement porte son niveau de confiance : rien n'est affirmé sur
    des effectifs trop faibles.
    """
    signalements = []
    for stat in statistiques_cartes(chemin):
        n = stat["reponses"]
        if n < MIN_DISCRIMINATION:
            continue

        base = {
            "carte_id": stat["carte_id"],
            "titre": stat["titre"],
            "niveau": stat["niveau"],
            "reponses": n,
            "fiabilite": stat["fiabilite"],
        }

        # On exige que même la BORNE HAUTE de l'intervalle de confiance passe
        # sous le seuil : sinon on signalerait du bruit d'échantillonnage.
        d = stat["discrimination"]
        borne = stat["discrimination_borne_haute"]
        if d is not None and borne is not None and borne < DISCRIMINATION_FAIBLE:
            signalements.append({**base,
                "probleme": "discrimination_faible",
                "gravite": "haute" if n >= 30 else "moyenne",
                "valeur": d,
                "borne_haute": borne,
                "explication": (
                    "L'item est raté autant par les apprenants forts que par "
                    "les faibles. Énoncé ambigu, réponse attendue trop "
                    "étroite, ou notion mal formulée."),
            })

        p = stat["difficulte"]
        if p is not None and p < DIFFICULTE_TROP_DIFFICILE:
            signalements.append({**base,
                "probleme": "trop_difficile", "gravite": "moyenne", "valeur": p,
                "explication": (
                    f"Seuls {p:.0%} réussissent. Question mal posée, ou "
                    "prérequis manquant à ce niveau."),
            })
        elif p is not None and p > DIFFICULTE_TROP_FACILE:
            signalements.append({**base,
                "probleme": "trop_facile", "gravite": "basse", "valeur": p,
                "explication": (
                    f"{p:.0%} de réussite : l'item n'apprend plus rien. "
                    "À déplacer vers un niveau inférieur ou à retirer."),
            })

        if stat["refus_frequents"]:
            signalements.append({**base,
                "probleme": "formulations_a_ajouter",
                "gravite": "moyenne",
                "valeur": stat["refus_frequents"],
                "explication": (
                    "Ces réponses reviennent souvent et sont refusées. Si "
                    "elles sont justes, ajoute-les à `reponses_acceptees`."),
            })

        if stat["taux_solution"] is not None and stat["taux_solution"] > 0.5:
            signalements.append({**base,
                "probleme": "abandon_frequent", "gravite": "moyenne",
                "valeur": stat["taux_solution"],
                "explication": (
                    "Plus d'un apprenant sur deux révèle la réponse sans "
                    "essayer. Question décourageante ou incompréhensible."),
            })

    ordre = {"haute": 0, "moyenne": 1, "basse": 2}
    return sorted(signalements, key=lambda s: (ordre[s["gravite"]], -s["reponses"]))


def resume(chemin=None) -> dict:
    """Vue d'ensemble, avec le volume encore nécessaire pour conclure."""
    stats = statistiques_cartes(chemin)
    tentatives = premieres_tentatives(chemin)
    sessions = {t["session_id"] for t in tentatives}
    exploitables = [s for s in stats if s["reponses"] >= MIN_DISCRIMINATION]
    niveaux = sorted({s["niveau"] for s in stats})

    return {
        "tentatives_totales": len(tentatives),
        "sessions": len(sessions),
        "cartes": len(stats),
        "cartes_mesurables": len(exploitables),
        "signalements": len(diagnostics(chemin)),
        "kr20_par_niveau": [kr20(n, chemin) for n in niveaux],
        "seuils": {
            "min_discrimination": MIN_DISCRIMINATION,
            "fiable_a_partir_de": FIABILITE[0][0],
        },
        "message": (
            f"{len(exploitables)}/{len(stats)} cartes ont assez de réponses "
            f"pour être mesurées (seuil : {MIN_DISCRIMINATION})."
            if exploitables else
            f"Aucune carte n'atteint encore {MIN_DISCRIMINATION} réponses. "
            "Les indices ne veulent rien dire avant."
        ),
    }


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "purger":
        print(f"{purger_journal()} tentatives supprimées.")
        sys.exit(0)

    print(json.dumps(resume(), ensure_ascii=False, indent=2))
    soucis = diagnostics()
    if soucis:
        print(f"\n{len(soucis)} carte(s) à relire :")
        for s in soucis[:15]:
            print(f"  [{s['gravite']}] #{s['carte_id']} « {s['titre']} » — "
                  f"{s['probleme']} ({s['fiabilite']}, n={s['reponses']})")

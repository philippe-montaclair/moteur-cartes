"""
Migrations de schéma — explicites, ordonnées, versionnées.

Pourquoi ce fichier existe, et c'est le point important :

`qualite.init_journal()` pose aujourd'hui un `CREATE TABLE IF NOT EXISTS
tentatives (…)`. Sur une base qui existe déjà, ÉLARGIR ce texte n'a AUCUN effet :
la table reste telle qu'elle est, sans erreur et sans message. C'est la même
famille de piège que celui rencontré dans `database.py` — où `CREATE INDEX ON
cards(matiere)` échouait sur une base d'avant la refonte multi-matières — mais en
pire : celui-là n'échouait même pas, il aurait menti.

`cards` échappe à ce problème parce qu'elle est une PROJECTION de `contenus/` :
`init_db()` la reconstruit dès qu'une colonne manque. `tentatives`,
`progression` et `comptes` portent de vraies données. Elles se migrent.

Règles :
  * une migration n'est jamais modifiée après avoir été appliquée quelque part ;
  * on en ajoute une nouvelle à la suite ;
  * chaque migration s'exécute dans une transaction : elle passe entièrement
    ou pas du tout ;
  * `migrer()` est idempotent — l'appeler deux fois ne fait rien la seconde.
"""

from __future__ import annotations

import sqlite3

VERSION_CIBLE = 4


SCHEMA_VERSION = """
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER NOT NULL,
    applique_le TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""


# ---------------------------------------------------------------------------
# Migration 1 — l'existant, repris tel quel pour partir d'un état connu
# ---------------------------------------------------------------------------

M001 = """
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


# ---------------------------------------------------------------------------
# Migration 2 — comptes, promos, inscriptions, progression
# ---------------------------------------------------------------------------

M002 = """
CREATE TABLE IF NOT EXISTS comptes (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    identifiant        TEXT    NOT NULL UNIQUE,
    mot_de_passe_hash  TEXT    NOT NULL,
    role               TEXT    NOT NULL DEFAULT 'apprenant',
    nom_affiche        TEXT    NOT NULL DEFAULT '',
    cree_le            TEXT    NOT NULL,
    derniere_connexion TEXT,
    actif              INTEGER NOT NULL DEFAULT 1,
    anonymise_le       TEXT
);

CREATE TABLE IF NOT EXISTS promos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    nom             TEXT    NOT NULL,
    formateur_id    INTEGER NOT NULL REFERENCES comptes(id),
    code_invitation TEXT    NOT NULL UNIQUE,
    debut           TEXT,
    fin             TEXT,
    cree_le         TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS inscriptions (
    compte_id  INTEGER NOT NULL REFERENCES comptes(id),
    promo_id   INTEGER NOT NULL REFERENCES promos(id),
    inscrit_le TEXT    NOT NULL,
    sorti_le   TEXT,
    PRIMARY KEY (compte_id, promo_id)
);

CREATE TABLE IF NOT EXISTS progression (
    compte_id         INTEGER NOT NULL REFERENCES comptes(id),
    carte_id          INTEGER NOT NULL,
    etat              TEXT    NOT NULL DEFAULT 'neuve',
    facilite          REAL    NOT NULL DEFAULT 2.5,
    intervalle_j      REAL    NOT NULL DEFAULT 0,
    repetitions       INTEGER NOT NULL DEFAULT 0,
    echecs            INTEGER NOT NULL DEFAULT 0,
    etape_appr        INTEGER NOT NULL DEFAULT 0,
    du_le             TEXT,
    derniere_revue_le TEXT,
    derniere_note     INTEGER,
    PRIMARY KEY (compte_id, carte_id)
);

CREATE INDEX IF NOT EXISTS idx_progression_du
    ON progression(compte_id, du_le);
CREATE INDEX IF NOT EXISTS idx_inscriptions_promo
    ON inscriptions(promo_id);
"""


# ---------------------------------------------------------------------------
# Migration 3 — rattachement des tentatives à un compte
# ---------------------------------------------------------------------------
#
# `session_id` RESTE : c'est lui qui porte le visiteur anonyme, et c'est lui qui
# alimente `qualite.py` sans aucune identité. `compte_id` est nullable pour la
# même raison.

M003 = [
    ("tentatives", "compte_id", "ALTER TABLE tentatives ADD COLUMN compte_id INTEGER"),
    ("tentatives", "via_qcm", "ALTER TABLE tentatives ADD COLUMN via_qcm INTEGER NOT NULL DEFAULT 0"),
    ("tentatives", "note", "ALTER TABLE tentatives ADD COLUMN note INTEGER"),
]

M003_INDEX = """
CREATE INDEX IF NOT EXISTS idx_tentatives_compte ON tentatives(compte_id);
"""


# ---------------------------------------------------------------------------
# Migration 4 — limitation des tentatives de connexion
# ---------------------------------------------------------------------------
#
# En base et pas en mémoire : avec plusieurs processus gunicorn, un compteur en
# mémoire protège un worker sur trois et laisse passer les deux autres.

M004 = """
CREATE TABLE IF NOT EXISTS connexions_ratees (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    identifiant TEXT NOT NULL,
    cree_le     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ratees ON connexions_ratees(identifiant, cree_le);
"""


# ---------------------------------------------------------------------------

def _colonnes(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def version_actuelle(conn: sqlite3.Connection) -> int:
    conn.executescript(SCHEMA_VERSION)
    ligne = conn.execute(
        "SELECT MAX(version) FROM schema_version").fetchone()
    return (ligne[0] or 0) if ligne else 0


def _appliquer_001(conn: sqlite3.Connection) -> None:
    conn.executescript(M001)


def _appliquer_002(conn: sqlite3.Connection) -> None:
    conn.executescript(M002)


def _appliquer_004(conn: sqlite3.Connection) -> None:
    conn.executescript(M004)


def _appliquer_003(conn: sqlite3.Connection) -> None:
    presentes = _colonnes(conn, "tentatives")
    for _table, colonne, requete in M003:
        if colonne not in presentes:
            conn.execute(requete)
    conn.executescript(M003_INDEX)


MIGRATIONS = {
    1: _appliquer_001,
    2: _appliquer_002,
    3: _appliquer_003,
    4: _appliquer_004,
}


def migrer(conn: sqlite3.Connection) -> int:
    """
    Applique les migrations manquantes. Rend la version atteinte.

    Chaque migration est isolée dans sa propre transaction : si la troisième
    échoue, la base reste à la version 2 — cohérente, et diagnosticable.
    """
    depart = version_actuelle(conn)
    for numero in range(depart + 1, VERSION_CIBLE + 1):
        if numero not in MIGRATIONS:
            # Une VERSION_CIBLE qui dépasse les migrations écrites est une
            # erreur de programmation. Elle doit se dire, pas se traduire en
            # KeyError trois appels plus loin.
            raise RuntimeError(
                f"migration {numero} déclarée par VERSION_CIBLE "
                f"({VERSION_CIBLE}) mais absente de MIGRATIONS")
        appliquer = MIGRATIONS[numero]
        try:
            conn.execute("BEGIN")
            appliquer(conn)
            conn.execute(
                "INSERT INTO schema_version (version, applique_le) "
                "VALUES (?, datetime('now'))", (numero,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return version_actuelle(conn)

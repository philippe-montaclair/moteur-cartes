"""
Tests des migrations de schéma.

Le défaut visé est nommé dans `migrations.py` : un `CREATE TABLE IF NOT EXISTS`
élargi ne modifie pas une table existante, sans erreur ni message. Ces tests
partent d'une base au schéma du 21 août et vérifient qu'elle arrive au schéma
courant sans perdre une ligne.
"""

import sqlite3
import tempfile
from pathlib import Path

import migrations

#: Le schéma tel qu'il était le 21 août 2026 — recopié, pas importé : un test
#: qui importe le code qu'il vérifie ne vérifie rien.
SCHEMA_21_AOUT = """
CREATE TABLE tentatives (
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
"""


def _base_vide():
    dossier = tempfile.mkdtemp(prefix="mig_")
    return sqlite3.connect(Path(dossier) / "test.db")


def _colonnes(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _tables(conn):
    return {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}


def test_base_neuve_atteint_la_version_cible():
    conn = _base_vide()
    assert migrations.migrer(conn) == migrations.VERSION_CIBLE


def test_les_quatre_tables_sont_creees():
    conn = _base_vide()
    migrations.migrer(conn)
    assert {"comptes", "promos", "inscriptions",
            "progression"} <= _tables(conn)


def test_migrer_deux_fois_ne_change_rien():
    conn = _base_vide()
    migrations.migrer(conn)
    avant = sorted(_tables(conn)), sorted(_colonnes(conn, "tentatives"))
    assert migrations.migrer(conn) == migrations.VERSION_CIBLE
    assert (sorted(_tables(conn)), sorted(_colonnes(conn, "tentatives"))) == avant
    lignes = conn.execute(
        "SELECT COUNT(*) FROM schema_version").fetchone()[0]
    assert lignes == migrations.VERSION_CIBLE


def test_une_base_du_21_aout_est_migree_sans_perte():
    """LE test qui compte : c'est la base réelle de production qui est simulée ici."""
    conn = _base_vide()
    conn.executescript(SCHEMA_21_AOUT)
    conn.execute(
        "INSERT INTO tentatives (carte_id, session_id, reponse, correct) "
        "VALUES (?, ?, ?, ?)", (12, "abcdef12", "while", 1))
    conn.commit()

    assert "compte_id" not in _colonnes(conn, "tentatives")
    migrations.migrer(conn)

    colonnes = _colonnes(conn, "tentatives")
    assert {"compte_id", "via_qcm", "note"} <= colonnes
    lignes = conn.execute("SELECT * FROM tentatives").fetchall()
    assert len(lignes) == 1, "une tentative existante a été perdue"
    assert conn.execute(
        "SELECT reponse FROM tentatives").fetchone()[0] == "while"
    assert conn.execute(
        "SELECT compte_id FROM tentatives").fetchone()[0] is None


def test_les_anciennes_tentatives_restent_anonymes():
    """`session_id` reste : c'est lui qui porte le visiteur anonyme et qui
    alimente les indices de qualité sans aucune identité."""
    conn = _base_vide()
    conn.executescript(SCHEMA_21_AOUT)
    conn.execute(
        "INSERT INTO tentatives (carte_id, session_id, reponse, correct) "
        "VALUES (?, ?, ?, ?)", (12, "abcdef12", "while", 1))
    conn.commit()
    migrations.migrer(conn)
    assert conn.execute(
        "SELECT session_id FROM tentatives").fetchone()[0] == "abcdef12"


def test_une_version_cible_sans_migration_se_dit():
    """Trouvé par le test suivant, le 28 août : `migrer` levait un KeyError
    trois appels plus loin au lieu de nommer le défaut."""
    conn = _base_vide()
    cible = migrations.VERSION_CIBLE
    migrations.VERSION_CIBLE = cible + 5
    try:
        migrations.migrer(conn)
        raise AssertionError("une version cible impossible a été acceptée")
    except RuntimeError as erreur:
        assert "absente de MIGRATIONS" in str(erreur)
    finally:
        migrations.VERSION_CIBLE = cible


def test_une_migration_qui_echoue_laisse_la_base_intacte():
    """Une migration à moitié appliquée est pire qu'une migration absente."""
    conn = _base_vide()
    migrations.migrer(conn)

    def casse(_conn):
        _conn.execute("CREATE TABLE temoin (x INTEGER)")
        raise RuntimeError("échec simulé")

    suivante = migrations.VERSION_CIBLE + 1
    migrations.MIGRATIONS[suivante] = casse
    cible = migrations.VERSION_CIBLE
    migrations.VERSION_CIBLE = suivante
    try:
        migrations.migrer(conn)
        raise AssertionError("l'échec n'a pas été propagé")
    except RuntimeError:
        pass
    finally:
        migrations.VERSION_CIBLE = cible
        del migrations.MIGRATIONS[suivante]

    assert "temoin" not in _tables(conn), "la table fautive a survécu"
    assert migrations.version_actuelle(conn) == cible


def test_la_progression_est_unique_par_compte_et_carte():
    conn = _base_vide()
    migrations.migrer(conn)
    conn.execute("INSERT INTO comptes (identifiant, mot_de_passe_hash, cree_le)"
                 " VALUES ('a', 'x', '2026-09-01')")
    conn.execute("INSERT INTO progression (compte_id, carte_id) VALUES (1, 5)")
    try:
        conn.execute("INSERT INTO progression (compte_id, carte_id) "
                     "VALUES (1, 5)")
    except sqlite3.IntegrityError:
        return
    raise AssertionError("un doublon de progression a été accepté")


def test_un_identifiant_de_compte_est_unique():
    conn = _base_vide()
    migrations.migrer(conn)
    conn.execute("INSERT INTO comptes (identifiant, mot_de_passe_hash, cree_le)"
                 " VALUES ('a@b.fr', 'x', '2026-09-01')")
    try:
        conn.execute("INSERT INTO comptes "
                     "(identifiant, mot_de_passe_hash, cree_le) "
                     "VALUES ('a@b.fr', 'y', '2026-09-01')")
    except sqlite3.IntegrityError:
        return
    raise AssertionError("deux comptes avec le même identifiant")

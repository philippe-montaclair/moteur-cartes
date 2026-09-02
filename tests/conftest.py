"""Configuration commune aux tests."""

import importlib
import sys
import tempfile
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

import database  # noqa: E402

# La suite de tests ne doit JAMAIS écrire dans prompt_app.db : un instrument
# qui détruit ce qu'il mesure ne mesure rien. Base jetable, hors du projet.
BASE_TEST = Path(tempfile.gettempdir()) / "prompt_app_tests.db"


def _preparer_base():
    """Reconstruit une base de test isolée à partir des fichiers JSON.

    `qualite` et `correcteur_llm` font `from database import CHEMIN_BASE`,
    ce qui copie la valeur au moment de leur import : réaffecter la seule
    variable de `database` laisserait ces deux modules écrire dans la base
    de production. Les trois sont donc redirigés explicitement.
    """
    if BASE_TEST.exists():
        BASE_TEST.unlink()

    database.CHEMIN_BASE = BASE_TEST
    for nom in ("qualite", "correcteur_llm"):
        try:
            module = importlib.import_module(nom)
        except ImportError:
            continue
        module.CHEMIN_BASE = BASE_TEST

    database.init_db(forcer=True)


_preparer_base()


def carte_par_titre(titre: str):
    """Retrouve une carte par son titre — lisible dans les tests."""
    for carte in database.lister_cartes():
        if carte["titre"] == titre:
            return carte
    raise AssertionError(f"Carte introuvable : {titre}")


def fausse_carte(reponse, acceptees=None, mots_cles=None, type_="texte"):
    """Fabrique une carte minimale, sans passer par la base."""
    import json
    return {
        "id": 0,
        "reponse": reponse,
        "reponses_acceptees": json.dumps(acceptees if acceptees is not None else []),
        "mots_cles": json.dumps(mots_cles if mots_cles is not None else []),
        "type": type_,
    }

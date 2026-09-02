"""
Lanceur de tests sans dépendance.

Utilisez pytest si vous l'avez :  .venv/bin/pytest -q
Ce script existe uniquement pour pouvoir vérifier la suite sur une machine
où pytest n'est pas installable. Il collecte les mêmes fichiers tests/test_*.py
et exécute les mêmes fonctions test_*.
"""

import sys
import traceback
from pathlib import Path

RACINE = Path(__file__).resolve().parent
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "tests"))


def main() -> int:
    import importlib

    reussis, echecs = 0, []

    for fichier in sorted((RACINE / "tests").glob("test_*.py")):
        module = importlib.import_module(fichier.stem)
        for nom in sorted(dir(module)):
            if not nom.startswith("test_"):
                continue
            fonction = getattr(module, nom)
            if not callable(fonction):
                continue
            try:
                fonction()
                reussis += 1
                print(".", end="", flush=True)
            except Exception:
                echecs.append((f"{fichier.stem}::{nom}", traceback.format_exc()))
                print("F", end="", flush=True)

    print()
    for nom, trace in echecs:
        print(f"\n{'=' * 70}\nÉCHEC : {nom}\n{'-' * 70}\n{trace}")

    total = reussis + len(echecs)
    print(f"\n{reussis}/{total} tests réussis"
          + (f", {len(echecs)} échec(s)" if echecs else ""))
    return 1 if echecs else 0


if __name__ == "__main__":
    sys.exit(main())

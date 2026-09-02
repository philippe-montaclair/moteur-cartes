"""
Le plan d'une matière : ce que chaque niveau doit couvrir.

POURQUOI CE FICHIER EXISTE
--------------------------
Les seize spécifications de `projets_applis/` décrivent toutes la même chose :
sept ou huit niveaux, trente cartes chacun, une liste de notions par niveau.
Cette liste était jusqu'ici dans un `.odt` que personne ne lit au moment de
produire — donc recopiée à la main dans un prompt, donc oubliée à moitié.

`plan.json` la met à côté du contenu, dans un format que la fabrique lit. Le
prompt de rédaction se construit à partir de là : il ne peut plus oublier un
thème, ni redemander un titre déjà pris.

RÈGLE — un plan ne modifie aucun `.py`. Ajouter une matière, c'est écrire deux
fichiers JSON : `manifeste.json` (comment on corrige) et `plan.json` (ce qu'on
enseigne).
"""

from __future__ import annotations

import json
from pathlib import Path

from database import DOSSIER_CONTENUS

NOM_PLAN = "plan.json"

#: Un niveau sans source d'ancrage est rédigeable, mais le prompt le dira :
#: le rédacteur travaillera alors de mémoire, et c'est exactement ce que la
#: fabrique cherche à éviter. La valeur par défaut n'est donc pas « pas de
#: source » mais « source manquante, à constituer ».
SANS_SOURCE = None


class ErreurPlan(ValueError):
    """Le plan est absent, illisible, ou incomplet."""


def chemin_plan(matiere: str) -> Path:
    return DOSSIER_CONTENUS / matiere / NOM_PLAN


def lire_plan(matiere: str) -> dict:
    """Charge et valide le plan d'une matière."""
    chemin = chemin_plan(matiere)
    if not chemin.exists():
        raise ErreurPlan(
            f"Aucun plan pour « {matiere} » : {chemin} est absent. "
            "Un plan décrit les niveaux et les thèmes de chaque niveau.")
    try:
        plan = json.loads(chemin.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ErreurPlan(f"{chemin} n'est pas un JSON valide : {e}") from e

    if plan.get("matiere") != matiere:
        raise ErreurPlan(
            f"{chemin} déclare la matière « {plan.get('matiere')} » alors "
            f"qu'il est rangé sous « {matiere} ».")

    niveaux = plan.get("niveaux")
    if not isinstance(niveaux, list) or not niveaux:
        raise ErreurPlan(f"{chemin} ne décrit aucun niveau.")

    numeros = []
    for n in niveaux:
        if not isinstance(n, dict):
            raise ErreurPlan(f"{chemin} : un niveau n'est pas un objet.")
        for cle in ("numero", "titre", "themes"):
            if cle not in n:
                raise ErreurPlan(f"{chemin} : niveau sans « {cle} ».")
        if not isinstance(n["themes"], list) or not n["themes"]:
            raise ErreurPlan(
                f"{chemin} : le niveau {n['numero']} n'a aucun thème.")
        numeros.append(n["numero"])

    if len(set(numeros)) != len(numeros):
        raise ErreurPlan(f"{chemin} : deux niveaux portent le même numéro.")

    plan.setdefault("cartes_par_niveau", 30)
    return plan


def niveau_du_plan(matiere: str, numero: int) -> dict:
    plan = lire_plan(matiere)
    for n in plan["niveaux"]:
        if int(n["numero"]) == int(numero):
            n.setdefault("cartes", plan["cartes_par_niveau"])
            return n
    disponibles = ", ".join(str(n["numero"]) for n in plan["niveaux"])
    raise ErreurPlan(
        f"Le plan de « {matiere} » n'a pas de niveau {numero} "
        f"(disponibles : {disponibles}).")


def chemin_source(matiere: str, niveau: dict) -> Path | None:
    """Le fichier d'ancrage d'un niveau, s'il est déclaré ET présent."""
    relatif = niveau.get("source")
    if not relatif:
        return SANS_SOURCE
    chemin = DOSSIER_CONTENUS.parent / relatif
    return chemin if chemin.exists() else SANS_SOURCE


def matieres_planifiees() -> list[str]:
    """Les matières qui ont un plan, dans l'ordre alphabétique."""
    if not DOSSIER_CONTENUS.is_dir():
        return []
    return sorted(d.name for d in DOSSIER_CONTENUS.iterdir()
                  if (d / NOM_PLAN).exists())


def etat_des_plans() -> list[dict]:
    """
    Tableau de bord : par matière et par niveau, ce qui existe déjà.

    Sert à répondre en une commande à « où en est-on », sans ouvrir un
    document qui prétend le savoir.
    """
    from database import lister_cartes

    lignes = []
    for matiere in matieres_planifiees():
        plan = lire_plan(matiere)
        for n in plan["niveaux"]:
            numero = int(n["numero"])
            fichier = DOSSIER_CONTENUS / matiere / f"niveau_{numero}.json"
            ecrites = 0
            if fichier.exists():
                try:
                    ecrites = len(json.loads(fichier.read_text(encoding="utf-8")))
                except (json.JSONDecodeError, TypeError):
                    ecrites = -1
            lignes.append({
                "matiere": matiere,
                "niveau": numero,
                "titre": n["titre"],
                "visees": n.get("cartes", plan["cartes_par_niveau"]),
                "ecrites": ecrites,
                "source": bool(chemin_source(matiere, n)),
                "themes": len(n["themes"]),
            })
    return lignes

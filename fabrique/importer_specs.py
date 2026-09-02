"""
Extraction des plans depuis les seize spécifications `.odt`.

POURQUOI CE FICHIER EXISTE, ET POURQUOI IL NE SERVIRA QU'UNE FOIS
-----------------------------------------------------------------
Les spécifications de `projets_applis/` décrivent toutes la même structure :
sept ou huit niveaux, une trentaine de cartes chacun, une liste de notions par
niveau. Cette liste était recopiée à la main dans un prompt à chaque fois —
donc oubliée à moitié, donc jamais la même d'un niveau à l'autre.

Ce module la lit à la source et produit un `plan.json` par matière. Passé ce
point, c'est `plan.json` qui fait foi : les `.odt` restent la trace de la
commande d'origine, ils ne sont plus dans la boucle de production.

    python -m fabrique.importer_specs --dossier projets_applis
"""

from __future__ import annotations

import html
import json
import re
import zipfile
from pathlib import Path

from database import DOSSIER_CONTENUS

#: matière → nom du fichier de spécification
SPECS = {
    "python": "prompt app python.odt",
    "sql": "prompt app sql.odt",
    "linux": "prompt app linux.odt",
    "pandas": "prompt app pandas.odt",
    "wiki": "prompt app wiki.odt",
    "ia": "prompt app ia.odt",
    "ml": "prompt app ML.odt",
    "rag": "prompt app rag.odt",
}

#: Un thème plus long que ça n'est pas un thème, c'est une phrase de contexte
#: ramassée par erreur. Un thème plus court qu'un mot n'en est pas un non plus.
LONGUEUR_THEME = (2, 60)

#: Le nombre de notions listées dépasse parfois le nombre de cartes visées.
#: On garde toutes les notions : c'est au rédacteur d'arbitrer, pas à
#: l'extracteur — qui n'a aucun moyen de savoir laquelle compte le moins.
THEMES_MAX = 40

_NIVEAU = re.compile(r"Niveau\s+(\d+)\s*[—–-]\s*([^\n]+)")

#: Fin de la liste des notions : la spécification enchaîne sur une section
#: numérotée (« 3. Format de chaque carte »). Sans cette borne, le DERNIER
#: niveau de chaque matière ramassait les noms de champs du gabarit — `id`,
#: `titre`, `question` — comme s'ils étaient des notions à enseigner. Défaut
#: réel, trouvé sur les huit matières avant tout usage : python 7 et pandas 7
#: portaient neuf faux thèmes chacun.
#:
#: La borne ne peut PAS être une liste de mots interdits : `id` est une vraie
#: commande Linux, `titre` une vraie notion de wiki et de document. C'est la
#: position qui distingue, pas le vocabulaire.
_FIN_SECTION = re.compile(r"^\s*\d+\.\s+\S", re.M)

#: Étiquettes d'introduction que la spécification place avant la liste :
#: « Notions : » n'est pas une notion à enseigner. Elles se retrouvaient dans
#: les thèmes, donc dans les prompts, donc dans le rapport de couverture qui
#: reprochait au lot de ne pas les couvrir.
ETIQUETTES = {"notions", "notion", "themes", "thèmes", "contenu", "sujets"}


def texte_odt(chemin: Path) -> str:
    brut = zipfile.ZipFile(chemin).read("content.xml").decode("utf-8")
    brut = re.sub(r"<text:p[^>]*>", "\n", brut)
    brut = re.sub(r"<text:list-item>", "\n", brut)
    brut = html.unescape(re.sub(r"<[^>]+>", "", brut))
    return re.sub(r"\n{2,}", "\n", brut)


def extraire_niveaux(texte: str) -> list[dict]:
    morceaux = _NIVEAU.split(texte)
    niveaux = []
    for i in range(1, len(morceaux) - 1, 3):
        numero = int(morceaux[i])
        titre = morceaux[i + 1].strip().rstrip(".")
        corps = morceaux[i + 2].split("Niveau")[0]
        borne = _FIN_SECTION.search(corps)
        if borne:
            corps = corps[:borne.start()]
        m = re.search(r"cartes? sur\s*:?(.*)", corps, re.S)
        brut = m.group(1) if m else corps
        themes = [t.strip(" ;. ") for t in re.split(r"[;\n]", brut)]
        themes = [t for t in themes
                  if LONGUEUR_THEME[0] <= len(t) <= LONGUEUR_THEME[1]
                  and t.rstrip(":").strip().lower() not in ETIQUETTES]
        if themes:
            niveaux.append({"numero": numero, "titre": titre,
                            "themes": themes[:THEMES_MAX]})
    return niveaux


def construire_plan(matiere: str, chemin_spec: Path,
                    cartes_par_niveau: int = 30) -> dict:
    niveaux = extraire_niveaux(texte_odt(chemin_spec))
    if not niveaux:
        raise ValueError(f"aucun niveau reconnu dans {chemin_spec}")
    for n in niveaux:
        n["source"] = f"sources/{matiere}/niveau_{n['numero']}.md"
    return {
        "matiere": matiere,
        "cartes_par_niveau": cartes_par_niveau,
        "origine": chemin_spec.name,
        "niveaux": niveaux,
    }


def ecrire_plans(dossier_specs: Path, journal=print) -> list[str]:
    ecrits = []
    for matiere, nom in SPECS.items():
        chemin = dossier_specs / nom
        if not chemin.exists():
            journal(f"  {matiere:8} spécification absente ({nom})")
            continue
        cible = DOSSIER_CONTENUS / matiere
        cible.mkdir(parents=True, exist_ok=True)

        # Un plan VERROUILLÉ porte une décision éditoriale prise à la main —
        # la frontière IA / ML, par exemple. Le régénérer depuis le `.odt`
        # l'effacerait en silence, et la décision serait à reprendre sans que
        # personne sache qu'elle avait été prise.
        existant = cible / "plan.json"
        if existant.exists():
            try:
                if json.loads(existant.read_text(encoding="utf-8")).get("verrouille"):
                    journal(f"  {matiere:8} VERROUILLÉ — laissé tel quel")
                    continue
            except json.JSONDecodeError:
                pass

        plan = construire_plan(matiere, chemin)
        (cible / "plan.json").write_text(
            json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        total = sum(len(n["themes"]) for n in plan["niveaux"])
        journal(f"  {matiere:8} {len(plan['niveaux'])} niveaux, "
                f"{total} notions")
        ecrits.append(matiere)
    return ecrits


if __name__ == "__main__":
    import argparse

    a = argparse.ArgumentParser(prog="fabrique.importer_specs")
    a.add_argument("--dossier", default="projets_applis")
    args = a.parse_args()
    print("Plans écrits :")
    ecrire_plans(Path(args.dossier))

"""
La boucle : rédiger, contrôler, corriger, sans copier-coller entre les deux.

CE QUI N'ALLAIT PAS
-------------------
La chaîne `prompt → autre modèle → importer` marche, et elle a produit trois
paquets en une heure. Mais elle demande à un humain de porter le prompt d'un
côté, la réponse de l'autre, et de recommencer à chaque rejet. Sur 62 niveaux,
c'est 62 allers-retours — et le rejet est la norme, pas l'exception : sur les
cinq premiers lots, trois ont été refusés.

Ce module ferme la boucle. Il produit, pour chaque tour, un **dossier de
travail** autosuffisant :

    fabrique/travaux/<matiere>_niveau_<n>/
        tour_1.md          le prompt de rédaction
        tour_1.json        ce que le rédacteur a rendu
        tour_2.md          le prompt + les corrections exigées
        rapport.json       l'historique des tours et des signalements

Le tour N+1 n'est pas le tour N relancé : il porte **ce qui a été refusé et
pourquoi**, carte par carte. Un rédacteur qui reçoit « ta carte X a un titre
qui donne la réponse » corrige ; un rédacteur qui reçoit le même prompt
recommence les mêmes fautes.

CE QUE CE MODULE NE FAIT PAS
----------------------------
Il n'appelle aucun modèle. Le rédacteur peut être une IA tierce dans un
onglet, un sous-agent, ou `fabrique generer` sur un modèle local — la boucle
est la même, et c'est voulu : elle survit au changement de rédacteur.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from fabrique.redaction import construire_prompt_externe

DOSSIER_TRAVAUX = Path(__file__).resolve().parent / "travaux"

#: Au-delà, on arrête et on regarde à la main. Une boucle qui tourne sans
#: converger ne produit pas du contenu, elle produit de la dépense.
TOURS_MAX = 3

ENTETE_CORRECTIONS = """\

---

# ⚠️ CORRECTIONS EXIGÉES — lis ceci avant de rédiger

Un lot a déjà été rendu pour ce niveau, au tour {tour}. Il a été **refusé**
par les vérificateurs automatiques. Tu reprends le travail : produis un lot
complet et corrigé, pas un correctif partiel.

Ce qui a été refusé, et pourquoi :
"""


def dossier(matiere: str, numero: int) -> Path:
    chemin = DOSSIER_TRAVAUX / f"{matiere}_niveau_{numero}"
    chemin.mkdir(parents=True, exist_ok=True)
    return chemin


def _rapport(chemin: Path) -> dict:
    fichier = chemin / "rapport.json"
    if fichier.exists():
        return json.loads(fichier.read_text(encoding="utf-8"))
    return {"tours": []}


def _formuler(signalements: list[dict]) -> list[str]:
    """Les signalements, dits comme des consignes plutôt que des constats."""
    consignes = {
        "titre_revele_reponse":
            "réécris le titre pour qu'il nomme le THÈME et non la réponse",
        "titre_deja_pris":
            "choisis un autre titre : celui-ci est déjà pris dans la matière",
        "notion_deja_enseignee":
            "supprime cette carte et traite une autre notion de la liste : "
            "celle-ci est déjà enseignée",
        "filet_trop_large":
            "resserre `mots_cles` : le filet accepte la réponse d'une autre carte",
        "filet_purement_litteral":
            "ajoute des `mots_cles` : le filet ne tient que par sa liste littérale",
        "hors_sujet":
            "reprends la liste numérotée des notions et traite celles qui manquent",
        "recouvrement_entre_matieres":
            "change de périmètre : ce lot redit une matière voisine",
        "exemple_non_executable":
            "corrige `exemple_code` ou `sortie_attendue` : l'exemple ne produit "
            "pas ce qui est annoncé",
        "meme_reponse":
            "deux cartes attendent la même réponse — n'en garde qu'une",
    }
    lignes = []
    for gravite in ("haute", "moyenne", "basse"):
        lot = [s for s in signalements if s["gravite"] == gravite]
        if not lot:
            continue
        lignes.append("")
        lignes.append(f"## Gravité {gravite} — {len(lot)} point(s)")
        lignes.append("")
        for s in lot[:25]:
            consigne = consignes.get(s["probleme"], "corrige ce point")
            lignes.append(f"- **« {s['titre']} »** — {consigne}.")
            lignes.append(f"  *Constat : {s['explication'][:220]}*")
        if len(lot) > 25:
            lignes.append(f"- … et {len(lot) - 25} autre(s), même famille.")
    return lignes


def preparer_tour(matiere: str, numero: int, nombre: int | None = None,
                  journal=print) -> Path:
    """
    Écrit le prompt du prochain tour, corrections comprises s'il y en a.

    Retourne le chemin du fichier à donner au rédacteur.
    """
    chemin = dossier(matiere, numero)
    rapport = _rapport(chemin)
    tour = len(rapport["tours"]) + 1

    if tour > TOURS_MAX:
        raise RuntimeError(
            f"{matiere} niveau {numero} : {TOURS_MAX} tours sans converger. "
            "Ce n'est plus un problème de rédaction — relis le plan, la source "
            "d'ancrage, ou le seuil qui refuse.")

    texte = construire_prompt_externe(matiere, numero, nombre)

    if rapport["tours"]:
        dernier = rapport["tours"][-1]
        texte += ENTETE_CORRECTIONS.format(tour=dernier["tour"])
        texte += "\n".join(_formuler(dernier["signalements"]))
        texte += (
            "\n\nRends de nouveau **le lot complet**, corrigé, dans un seul "
            "bloc JSON.")

    fichier = chemin / f"tour_{tour}.md"
    fichier.write_text(texte, encoding="utf-8")
    journal(f"  tour {tour} préparé : {fichier} ({len(texte)} caractères)")
    return fichier


def enregistrer_tour(matiere: str, numero: int, resultat: dict,
                     journal=print) -> dict:
    """Consigne le résultat d'un import dans l'historique du niveau."""
    chemin = dossier(matiere, numero)
    rapport = _rapport(chemin)
    rapport["tours"].append({
        "tour": len(rapport["tours"]) + 1,
        "date": datetime.now().isoformat(timespec="seconds"),
        "retenues": resultat["retenues"],
        "attendues": resultat["attendues"],
        "par_gravite": resultat["par_gravite"],
        "livrable": resultat["livrable"],
        "signalements": resultat["signalements"],
    })
    (chemin / "rapport.json").write_text(
        json.dumps(rapport, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    dernier = rapport["tours"][-1]
    journal(f"  tour {dernier['tour']} consigné — "
            f"{'livrable' if dernier['livrable'] else 'refusé'}")
    return rapport


def etat_boucles() -> list[dict]:
    """Où en est chaque niveau engagé dans la boucle."""
    if not DOSSIER_TRAVAUX.is_dir():
        return []
    lignes = []
    for chemin in sorted(DOSSIER_TRAVAUX.iterdir()):
        fichier = chemin / "rapport.json"
        if not fichier.exists():
            continue
        rapport = json.loads(fichier.read_text(encoding="utf-8"))
        if not rapport["tours"]:
            continue
        dernier = rapport["tours"][-1]
        lignes.append({
            "niveau": chemin.name,
            "tours": len(rapport["tours"]),
            "retenues": dernier["retenues"],
            "attendues": dernier["attendues"],
            "livrable": dernier["livrable"],
            "haute": dernier["par_gravite"]["haute"],
        })
    return lignes

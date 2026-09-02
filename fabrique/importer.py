"""
Le retour : reprendre ce qu'un autre modèle a rédigé, sans lui faire confiance.

POURQUOI
--------
Le chemin « je colle un prompt dans une IA, je récupère du JSON, je le range
dans `contenus/` » a produit le seul paquet défectueux des quatre : 27 titres
sur 30 donnaient la réponse. Le défaut n'a pas été vu parce que rien ne se
tenait entre le presse-papier et le dossier de contenu.

Ce module est ce qui se tient là. Il accepte n'importe quelle sortie — bloc
de code markdown, JSON nu, bavardage autour — et refuse de rien activer :

    texte collé  →  extraction  →  normalisation  →  vérificateurs
                                                     ├─ propositions/
                                                     └─ quarantaine/

Rien n'atterrit dans `contenus/<matiere>/niveau_N.json` sans une action
explicite (`--activer`), et jamais si un signalement grave subsiste.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from database import DEFAUTS, DOSSIER_CONTENUS, lire_manifeste, lister_cartes
from fabrique.generer import _nettoyer
from fabrique.plan import niveau_du_plan

DOSSIER_FABRIQUE = Path(__file__).resolve().parent
DOSSIER_QUARANTAINE = DOSSIER_FABRIQUE / "quarantaine"

#: Un bloc ```json … ``` d'abord ; à défaut, le premier tableau JSON complet.
_BLOC = re.compile(r"```(?:json)?\s*(?P<corps>[\[{].*?)```", re.S)


class ErreurImport(ValueError):
    """Le texte fourni ne contient pas de cartes exploitables."""


class ErreurTronquee(ErreurImport):
    """Le flux s'arrête au milieu d'une carte — il y a de quoi reprendre."""

    def __init__(self, message: str, recuperees: list):
        super().__init__(message)
        self.recuperees = recuperees


def _objets_complets(texte: str) -> list:
    """
    Les objets JSON complets d'un flux interrompu.

    Balaye les accolades en tenant compte des chaînes et des échappements —
    un `{` dans une explication ne compte pas. S'arrête au premier objet
    inachevé et rend ce qui précède.
    """
    objets, profondeur, debut = [], 0, None
    dans_chaine = echappe = False
    for i, c in enumerate(texte):
        if dans_chaine:
            if echappe:
                echappe = False
            elif c == "\\":
                echappe = True
            elif c == '"':
                dans_chaine = False
            continue
        if c == '"':
            dans_chaine = True
        elif c == "{":
            if profondeur == 0:
                debut = i
            profondeur += 1
        elif c == "}":
            profondeur -= 1
            if profondeur == 0 and debut is not None:
                try:
                    objets.append(json.loads(texte[debut:i + 1]))
                except json.JSONDecodeError:
                    pass
                debut = None
    return objets


def extraire_json(texte: str) -> list:
    """
    Retrouve le tableau de cartes dans une réponse de modèle.

    Tolérant par construction : les modèles encadrent, commentent, s'excusent.
    Ce qui compte est que la tolérance s'arrête ici — une fois extraites, les
    cartes passent les mêmes contrôles que n'importe quelles autres.
    """
    candidats = [m.group("corps") for m in _BLOC.finditer(texte)]
    if not candidats:
        debut = texte.find("[")
        fin = texte.rfind("]")
        if debut != -1 and fin > debut:
            candidats = [texte[debut:fin + 1]]

    for brut in candidats:
        try:
            donnees = json.loads(brut)
        except json.JSONDecodeError:
            continue
        if isinstance(donnees, dict):
            donnees = donnees.get("cartes", [])
        if isinstance(donnees, list) and donnees:
            return donnees

    # Rien n'a pu être lu en entier. Avant d'abandonner, on regarde si le
    # flux est TRONQUÉ — c'est le cas le plus fréquent en pratique : le
    # modèle a été coupé par sa limite de sortie au milieu d'une carte.
    # Dire « aucun JSON trouvé » serait un mauvais diagnostic, et il
    # enverrait relancer toute la génération alors qu'il suffit de demander
    # la suite.
    recuperees = _objets_complets(texte)
    if recuperees:
        raise ErreurTronquee(
            f"Le JSON est tronqué : {len(recuperees)} carte(s) complète(s) "
            "avant la coupure, puis un objet inachevé. Le modèle a été coupé "
            "par sa limite de sortie. Demande-lui la suite à partir de la "
            f"carte {len(recuperees) + 1}, ou relance en deux lots.",
            recuperees)

    raise ErreurImport(
        "Aucun tableau JSON exploitable trouvé. Attendu : un bloc ```json "
        "contenant un tableau d'objets, ou le tableau seul.")


def preparer(cartes_brutes: list, matiere: str, numero: int) -> tuple[list, list]:
    """Normalise au schéma du moteur. Retourne (cartes propres, écartées)."""
    dossier = DOSSIER_CONTENUS / matiere
    manifeste = lire_manifeste(dossier)

    propres, ecartees = [], []
    for rang, brute in enumerate(cartes_brutes, 1):
        propre = _nettoyer(brute, manifeste, numero)
        if propre is None:
            ecartees.append({
                "rang": rang,
                "motif": "champs obligatoires manquants (titre, question ou "
                         "réponse vide)",
                "carte": brute,
            })
            continue
        propre["matiere"] = matiere
        propre.setdefault("langue", manifeste.get("langue_reponse")
                          or manifeste["langue_enseignement"]
                          or DEFAUTS["langue"])
        propres.append(propre)
    return propres, ecartees


def _autres_matieres(matiere: str) -> list:
    """Les cartes déjà livrées des AUTRES matières, pour le contrôle 12."""
    try:
        return [c for c in lister_cartes() if c["matiere"] != matiere]
    except Exception:
        return []


def controler(cartes: list, matiere: str, deja: list | None = None) -> list[dict]:
    """
    Les vérificateurs déterministes, sur des cartes qui ne sont pas en base.

    On leur adjoint les cartes déjà livrées de la matière : un doublon ou un
    filet trop large ne se voit qu'en confrontant le lot neuf à l'existant.
    Les signalements portant sur une carte déjà livrée sont écartés — ils ne
    sont pas le sujet de cet import.
    """
    from fabrique.verificateurs import (
        verifier_couverture, verifier_doublons, verifier_execution,
        verifier_filets, verifier_recouvrement_matieres, verifier_titre,
        verifier_notions_uniques, verifier_titres_uniques)

    neuves = {id(c) for c in cartes}
    try:
        existantes = [dict(c) for c in lister_cartes(matiere=matiere)]
    except Exception:
        existantes = []
    ensemble = cartes + existantes

    titres_neufs = {c.get("titre") for c in cartes}
    signalements = []
    for fonction in (verifier_execution, verifier_titre):
        signalements += fonction(cartes)

    # Conformité à la commande, et recouvrement avec les autres matières :
    # deux questions qui ne se posent qu'au niveau du LOT, pas de la carte.
    niveau_lot = cartes[0].get("niveau") if cartes else None
    if niveau_lot is not None:
        # La couverture se mesure sur le NIVEAU une fois complété, pas sur le
        # lot seul. Sans ça, un complément de 11 cartes se voyait reprocher de
        # ne pas couvrir les 20 notions d'un niveau dont 39 cartes étaient
        # déjà en place — l'instrument accusait le seul lot qu'il voyait.
        signalements += verifier_couverture(matiere, niveau_lot,
                                            (deja or []) + cartes)
        toutes = cartes + [dict(c) for c in _autres_matieres(matiere)]
        signalements += [s for s in verifier_recouvrement_matieres(toutes)
                         if s.get("matiere") == matiere
                         and s.get("niveau") == niveau_lot]
    for fonction in (verifier_doublons, verifier_filets, verifier_titres_uniques,
                     verifier_notions_uniques):
        signalements += [s for s in fonction(ensemble)
                         if s.get("titre") in titres_neufs]
    del neuves
    return signalements


def importer(texte: str, matiere: str, numero: int,
             activer: bool = False, journal=print,
             dossier_sortie: Path | None = None,
             fusionner: bool = False) -> dict:
    """
    Le trajet complet, de la réponse d'un modèle au fichier de propositions.

    `activer=True` n'écrit dans `contenus/` **que** si aucun signalement de
    gravité haute ne subsiste et qu'aucune carte n'a été écartée.
    """
    niveau = niveau_du_plan(matiere, numero)
    attendu = niveau.get("cartes", 30)

    # En fusion, le lot n'est pas le niveau : c'est un complément. Ce qui est
    # attendu, c'est le TOTAL une fois ajouté à ce qui existe déjà. Sans cette
    # distinction, un complément de 16 cartes serait éternellement refusé pour
    # ne pas en faire 30.
    fichier_actif = DOSSIER_CONTENUS / matiere / f"niveau_{numero}.json"
    deja = []
    if fusionner and fichier_actif.exists():
        deja = json.loads(fichier_actif.read_text(encoding="utf-8"))

    brutes = extraire_json(texte)
    journal(f"{len(brutes)} objet(s) extrait(s) — {attendu} attendu(s)"
            + (f", dont {len(deja)} déjà en place" if deja else ""))

    cartes, ecartees = preparer(brutes, matiere, numero)
    journal(f"{len(cartes)} carte(s) au schéma, {len(ecartees)} écartée(s)")

    signalements = controler(cartes, matiere, deja)
    par_gravite = {g: sum(1 for s in signalements if s["gravite"] == g)
                   for g in ("haute", "moyenne", "basse")}
    journal(f"{len(signalements)} signalement(s) — "
            f"{par_gravite['haute']} haute, {par_gravite['moyenne']} moyenne, "
            f"{par_gravite['basse']} basse")

    # Une carte signalée gravement ne part pas avec les autres.
    titres_graves = {s["titre"] for s in signalements if s["gravite"] == "haute"}
    retenues = [c for c in cartes if c.get("titre") not in titres_graves]
    quarantaine = [c for c in cartes if c.get("titre") in titres_graves]

    # `dossier_sortie` existe pour les tests, et le motif compte : sans lui,
    # lancer la suite écrasait `_propositions_niveau_2.json` et la quarantaine
    # du vrai contenu avec la carte factice d'un test. C'est exactement le
    # défaut trouvé le 19/08 dans `conftest.py`, qui reconstruisait la base de
    # production : on ne pouvait plus distinguer « j'ai testé » de « j'ai
    # écrasé ». Un test qui écrit dans le dossier de production ne teste pas,
    # il abîme.
    dossier = Path(dossier_sortie) / matiere if dossier_sortie \
        else DOSSIER_CONTENUS / matiere
    quarantaine_dossier = Path(dossier_sortie) / "quarantaine" if dossier_sortie \
        else DOSSIER_QUARANTAINE
    dossier.mkdir(parents=True, exist_ok=True)
    quarantaine_dossier.mkdir(parents=True, exist_ok=True)

    fichier_propositions = dossier / f"_propositions_niveau_{numero}.json"
    fichier_propositions.write_text(
        json.dumps(retenues, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")

    fichier_quarantaine = quarantaine_dossier / f"{matiere}_niveau_{numero}.json"
    fichier_quarantaine.write_text(json.dumps(
        {"cartes_retenues_ailleurs": len(retenues),
         "ecartees_au_schema": ecartees,
         "mises_en_quarantaine": quarantaine,
         "signalements": signalements},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Le même seuil que `fabrique contrat`, sans quoi `--activer` mettrait en
    # service un niveau que le contrat refuserait juste après. Les filets en
    # gravité BASSE ne bloquent pas : ils disent « ce filet ne tient que par
    # sa liste », ce qui est une faiblesse, pas un défaut.
    filets_bloquants = [s for s in signalements
                        if s["probleme"].startswith("filet_")
                        and s["gravite"] in ("haute", "moyenne")]
    total = deja + retenues if fusionner else retenues
    livrable = (not quarantaine and not ecartees
                and par_gravite["haute"] == 0
                and not filets_bloquants
                and len(total) == attendu)

    active = False
    if activer:
        if livrable:
            fichier_actif.write_text(
                json.dumps(total, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8")
            active = True
            journal(f"activé : {fichier_actif}")
        else:
            journal("NON activé : le lot ne remplit pas le contrat de livraison.")

    return {
        "matiere": matiere,
        "niveau": numero,
        "attendues": attendu,
        "extraites": len(brutes),
        "retenues": len(retenues),
        "deja_en_place": len(deja),
        "total": len(total),
        "ecartees": len(ecartees),
        "quarantaine": len(quarantaine),
        "par_gravite": par_gravite,
        "signalements": signalements,
        "livrable": livrable,
        "activee": active,
        "fichier_propositions": str(fichier_propositions),
        "fichier_quarantaine": str(fichier_quarantaine),
    }

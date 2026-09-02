#!/usr/bin/env python3
"""
Démonstration — ce que ce dépôt fait, en quinze secondes et sans serveur.

    python demonstration.py

Rien n'est simulé : les cartes viennent du paquet livré, et les verdicts
sortent du correcteur réellement utilisé par l'application.
"""

from __future__ import annotations

import json
import sys

from database import (controler_donnees, defauts_du_qcm, init_db,
                      lister_cartes, valider_reponse)
from fabrique.verificateurs import verifier_qcm


VERT, ROUGE, GRIS, FIN = "\033[32m", "\033[31m", "\033[90m", "\033[0m"
if not sys.stdout.isatty():
    VERT = ROUGE = GRIS = FIN = ""


def titre(numero: int, texte: str) -> None:
    print(f"\n{'─' * 72}\n{numero}. {texte}\n{'─' * 72}")


def verdict(reponse: str, resultat: dict, attendu: bool) -> None:
    ok = resultat["correct"] is attendu
    marque = f"{VERT}✓{FIN}" if ok else f"{ROUGE}✗{FIN}"
    etat = "accepté " if resultat["correct"] else "refusé  "
    print(f"  {marque} {etat} « {reponse} »")
    if not ok:
        print(f"      {ROUGE}CE N'EST PAS LE COMPORTEMENT ATTENDU{FIN}")


# ---------------------------------------------------------------------------

def correction_sur_carte_reelle() -> None:
    titre(1, "Le correcteur, sur une carte réellement livrée")

    cartes = [c for c in lister_cartes(niveau=1, matiere="python")
              if json.loads(c["reponses_acceptees"] or "[]")]
    carte = cartes[0]
    autre = next(c for c in cartes[1:]
                 if c["reponse"].strip() != carte["reponse"].strip())

    print(f"\n  Question : {carte['question']}")
    print(f"  Réponse attendue : {carte['reponse']}\n")

    print(f"  {GRIS}Les formulations prévues sont acceptées :{FIN}")
    for variante in json.loads(carte["reponses_acceptees"])[:4]:
        verdict(variante, valider_reponse(variante, carte), attendu=True)

    print(f"\n  {GRIS}La réponse d'une AUTRE carte ne l'est pas — un filet qui")
    print(f"  accepte la réponse voisine ne mesure plus rien :{FIN}")
    verdict(autre["reponse"], valider_reponse(autre["reponse"], carte),
            attendu=False)


def les_deux_gardes() -> None:
    titre(2, "Deux gardes nées de défauts réels, et non de tests théoriques")

    def carte(reponse, acceptees, mots, type_="texte"):
        return {"id": 0, "reponse": reponse, "type": type_,
                "reponses_acceptees": json.dumps(acceptees),
                "mots_cles": json.dumps(mots)}

    print(f"\n  {GRIS}Polarité — une négation n'enlève aucun mot, elle inverse")
    print(f"  le sens. Trois chemins d'acceptation sur quatre validaient donc")
    print(f"  le contraire de la bonne réponse.{FIN}")
    c = carte("C'est un entier.", ["C'est un entier.", "un entier"],
              [["entier"]])
    verdict("c'est un entier", valider_reponse("c'est un entier", c), True)
    verdict("ce n'est pas un entier",
            valider_reponse("ce n'est pas un entier", c), False)

    print(f"\n  {GRIS}Réponse noyée — « str » compté parmi quatre mots porteurs")
    print(f"  est un élément d'énumération, pas une réponse.{FIN}")
    c = carte("str", ["str"], [["str"]], type_="mot_cle")
    verdict("str", valider_reponse("str", c), True)
    verdict("int, float, str et bool",
            valider_reponse("int, float, str et bool", c), False)


def qcm_refuse() -> None:
    titre(3, "Le vérificateur de QCM refuse ce qu'un modèle produit spontanément")

    exemples = [
        ("la bonne option est la plus longue — un apprenant l'apprend "
         "en trois cartes",
         {"options": ["non", "peut-être", "jamais",
                      "oui, parce que la condition est évaluée puis le bloc "
                      "exécuté dans l'ordre attendu"],
          "reponse": 3, "pourquoi_faux": {"0": "x", "1": "y", "2": "z"}}),
        ("une option fourre-tout",
         {"options": ["else", "elif", "then", "Aucune de ces réponses"],
          "reponse": 1, "pourquoi_faux": {"0": "x", "2": "y", "3": "z"}}),
        ("un distracteur sans motif de rejet",
         {"options": ["else", "elif", "then", "when"],
          "reponse": 1, "pourquoi_faux": {"0": "x"}}),
    ]
    print()
    for description, qcm in exemples:
        defauts = defauts_du_qcm(qcm)
        marque = f"{VERT}✓{FIN}" if defauts else f"{ROUGE}✗ NON DÉTECTÉ{FIN}"
        print(f"  {marque} {description}")
        for d in defauts:
            print(f"      {GRIS}→ {d}{FIN}")

    print(f"\n  {GRIS}Et le contrôle que seul le paquet complet permet : un")
    print(f"  distracteur que le correcteur accepte n'est pas un distracteur.{FIN}")
    carte = dict(lister_cartes(niveau=1, matiere="python")[0])
    carte["qcm"] = json.dumps({
        "options": ["un tuple", carte["reponse"], "une boucle", "un module"],
        "reponse": 0, "pourquoi_faux": {"1": "x", "2": "y", "3": "z"}})
    for signalement in verifier_qcm([carte]):
        print(f"  {VERT}✓{FIN} {signalement['probleme']} — "
              f"{signalement['explication'][:64]}…")


def integrite_du_paquet() -> None:
    titre(4, "Le contrôle qui tourne à chaque démarrage et en intégration continue")

    cartes = lister_cartes()
    problemes = controler_donnees()
    matieres = sorted({c["matiere"] for c in cartes})

    print(f"\n  {len(cartes)} cartes, {len(matieres)} paquets : "
          f"{', '.join(matieres)}")
    print(f"  {GRIS}Chaque réponse attendue est rejouée à travers le")
    print(f"  validateur. Une carte dont la bonne réponse serait refusée")
    print(f"  fait échouer le démarrage — et la CI.{FIN}")
    if problemes:
        print(f"\n  {ROUGE}{len(problemes)} anomalie(s) :{FIN}")
        for p in problemes[:5]:
            print(f"    - {p}")
    else:
        print(f"\n  {VERT}✓{FIN} aucune anomalie sur les "
              f"{len(cartes)} cartes.")


def main() -> int:
    print("\n  moteur-cartes — démonstration")
    total = init_db()
    print(f"  {GRIS}base construite depuis contenus/ : {total} cartes{FIN}")

    correction_sur_carte_reelle()
    les_deux_gardes()
    qcm_refuse()
    integrite_du_paquet()

    print(f"\n{'─' * 72}")
    print("  Pour l'interface : python app.py  →  http://127.0.0.1:5000")
    print("  Pour la suite    : pytest -q")
    print(f"{'─' * 72}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

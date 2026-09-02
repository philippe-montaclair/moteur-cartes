"""
Le contrat de livraison — la seule phrase qui décide si un niveau est fini.

POURQUOI
--------
« La fabrique tourne » ne veut rien dire, et « le niveau est prêt » encore
moins tant que personne n'a écrit ce que « prêt » veut dire. Un document qui
l'écrit ne bloque rien : on le relit quand on a déjà décidé. Ce module en fait
une commande qui **sort en code 1**.

Les cinq clauses, et pourquoi chacune :

1. le compte y est                 — 30 cartes annoncées, 30 cartes présentes ;
2. zéro signalement de gravité haute ;
3. aucun filet d'acceptation signalé, même en gravité moyenne — c'est la
   clause plus stricte que la suite générale, et c'est voulu : on ne livre
   pas un niveau neuf avec un filet qu'on sait défectueux, alors qu'on ne
   repeint pas en rouge du contenu déjà en service ;
4. tous les `exemple_code` s'exécutent et produisent leur sortie annoncée ;
5. le paquet a été joué en entier une fois — clause **humaine**, que le code
   ne peut pas vérifier et qu'il refuse donc de déclarer remplie tout seul.

La cinquième n'est pas décorative. Les deux défauts du 19 août 2026 — la fuite
par le titre et l'ordre d'initialisation de la base — étaient invisibles à
116 tests verts et à une passe de vérification complète. Ils sont sortis en
dix minutes d'usage réel. Aucune fabrique ne remplace le fait de jouer le
paquet ; elle réduit ce qu'il reste à y trouver.
"""

from __future__ import annotations

import json
from pathlib import Path

from database import DOSSIER_CONTENUS, lister_cartes
from fabrique.plan import niveau_du_plan

TEMOIN = Path(__file__).resolve().parent / "joues.json"


def marquer_joue(matiere: str, numero: int, par: str = "") -> None:
    """Enregistre qu'un humain a joué ce niveau en entier."""
    from datetime import date
    temoins = json.loads(TEMOIN.read_text(encoding="utf-8")) if TEMOIN.exists() else {}
    temoins[f"{matiere}/{numero}"] = {"date": date.today().isoformat(), "par": par}
    TEMOIN.write_text(json.dumps(temoins, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")


def a_ete_joue(matiere: str, numero: int) -> dict | None:
    if not TEMOIN.exists():
        return None
    return json.loads(TEMOIN.read_text(encoding="utf-8")).get(f"{matiere}/{numero}")


def evaluer(matiere: str, numero: int) -> dict:
    """Les cinq clauses, chacune avec son verdict et sa preuve."""
    from fabrique.verificateurs import (
        verifier_execution, verifier_filets, verifier_titre, verifier_doublons,
        verifier_notions_uniques, verifier_titres_uniques)

    plan_niveau = niveau_du_plan(matiere, numero)
    attendu = plan_niveau.get("cartes", 30)

    fichier = DOSSIER_CONTENUS / matiere / f"niveau_{numero}.json"
    if not fichier.exists():
        return {
            "matiere": matiere, "niveau": numero, "rempli": False,
            "clauses": [{"nom": "le fichier de niveau existe", "rempli": False,
                         "preuve": f"{fichier} est absent"}],
        }

    cartes = [c for c in lister_cartes(matiere=matiere) if c["niveau"] == numero]
    if not cartes:  # base non initialisée : on lit le fichier
        cartes = json.loads(fichier.read_text(encoding="utf-8"))
        for c in cartes:
            c.setdefault("matiere", matiere)

    # L'unicité des titres se juge sur TOUTE la matière, pas sur le niveau :
    # un homonyme à un autre niveau est exactement le cas qu'on veut attraper.
    toute_la_matiere = list(lister_cartes(matiere=matiere)) or cartes
    signalements = (verifier_execution(cartes) + verifier_titre(cartes)
                    + verifier_doublons(cartes) + verifier_filets(cartes)
                    + [s for s in (verifier_titres_uniques(toute_la_matiere)
                                   + verifier_notions_uniques(toute_la_matiere))
                       if s.get("niveau") == numero])
    hautes = [s for s in signalements if s["gravite"] == "haute"]
    # Gravité basse exclue : `filet_purement_litteral` signale une faiblesse
    # (le filet ne tient que par sa liste littérale), pas un défaut. Le faire
    # bloquer rendrait le contrat impossible à remplir, et un contrat qu'on ne
    # peut pas remplir ne se lit plus.
    filets = [s for s in signalements if s["probleme"].startswith("filet_")
              and s["gravite"] in ("haute", "moyenne")]
    executions = [s for s in signalements
                  if s["probleme"].startswith(("exemple_", "execution_",
                                               "sortie_"))]
    joue = a_ete_joue(matiere, numero)

    clauses = [
        {"nom": "le compte y est",
         "rempli": len(cartes) == attendu,
         "preuve": f"{len(cartes)} carte(s) pour {attendu} annoncée(s)"},
        {"nom": "aucun signalement grave",
         "rempli": not hautes,
         "preuve": f"{len(hautes)} signalement(s) de gravité haute"},
        {"nom": "aucun filet d'acceptation signalé",
         "rempli": not filets,
         "preuve": f"{len(filets)} signalement(s) de filet"},
        {"nom": "les exemples de code s'exécutent",
         "rempli": not executions,
         "preuve": f"{len(executions)} exemple(s) en défaut"},
        {"nom": "le paquet a été joué en entier par un humain",
         "rempli": bool(joue),
         "preuve": (f"joué le {joue['date']}" + (f" par {joue['par']}" if joue.get("par") else ""))
                   if joue else
                   "jamais déclaré — `python -m fabrique joue --matiere "
                   f"{matiere} --niveau {numero}` après l'avoir fait"},
    ]

    return {
        "matiere": matiere, "niveau": numero,
        "titre": plan_niveau["titre"],
        "rempli": all(c["rempli"] for c in clauses),
        "clauses": clauses,
        "signalements": signalements,
    }

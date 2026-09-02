"""
Ligne de commande de la fabrique.

VÉRIFIER — les huit contrôles sur ce qui est en place
    python -m fabrique verifier
    python -m fabrique verifier --matiere python --avec-llm

ÉTAT — où en est chaque matière, chaque niveau
    python -m fabrique etat

RÉDIGER PAR UN AUTRE MODÈLE — le chemin recommandé
    python -m fabrique prompt --matiere python --niveau 2 > prompt.md
    (coller dans une conversation neuve, récupérer la réponse dans reponse.md)
    python -m fabrique importer --matiere python --niveau 2 --fichier reponse.md

RÉDIGER PAR APPEL DIRECT — quand un modèle est branché
    python -m fabrique generer --matiere python --niveau 2 --nombre 8 \
                               --source sources/python/niveau_2.md

LIVRER
    python -m fabrique joue    --matiere python --niveau 2 --par mon-nom
    python -m fabrique contrat --matiere python --niveau 2   # code 1 si non
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from fabrique.verificateurs import verifier_tout  # noqa: E402

FICHIER_FILE = RACINE / "fabrique" / "file_de_relecture.json"


def _afficher(rapport: dict, limite: int = 20) -> None:
    par_gravite = rapport["par_gravite"]
    total = sum(par_gravite.values())
    print()
    if not total:
        print(f"Aucun signalement sur {rapport['cartes_verifiees']} carte(s).")
        return

    print(f"{total} signalement(s) — "
          f"{par_gravite['haute']} haute, {par_gravite['moyenne']} moyenne, "
          f"{par_gravite['basse']} basse")
    print()
    for s in rapport["signalements"][:limite]:
        etiquette = f"#{s['carte_id']} « {s['titre']} »" if s["carte_id"] else "(données)"
        print(f"  [{s['gravite']:7}] {s['probleme']:32} {etiquette}")
        print(f"            {s['explication']}")
    if total > limite:
        print(f"\n  … et {total - limite} autre(s). Détail complet dans "
              f"{FICHIER_FILE.relative_to(RACINE)}")


def commande_verifier(args) -> int:
    rapport = verifier_tout(matiere=args.matiere, avec_llm=args.avec_llm,
                            tirages=args.tirages)
    FICHIER_FILE.parent.mkdir(exist_ok=True)
    FICHIER_FILE.write_text(
        json.dumps(rapport, ensure_ascii=False, indent=2), encoding="utf-8")
    _afficher(rapport)
    print(f"\nFile de relecture : {FICHIER_FILE.relative_to(RACINE)}")
    return 1 if rapport["par_gravite"]["haute"] else 0


def commande_generer(args) -> int:
    from database import DOSSIER_CONTENUS, lister_cartes
    from fabrique.generer import generer

    source = Path(args.source).read_text(encoding="utf-8")
    existantes = [c["titre"] for c in lister_cartes(matiere=args.matiere)]
    themes = [t.strip() for t in (args.themes or "").split(",") if t.strip()]

    cartes = generer(args.matiere, args.niveau, args.nombre, source,
                     themes=themes or None, existantes=existantes)
    if not cartes:
        print("Aucune carte exploitable produite.")
        return 1

    sortie = Path(args.sortie or (DOSSIER_CONTENUS / args.matiere
                                  / f"_propositions_niveau_{args.niveau}.json"))
    sortie.write_text(json.dumps(cartes, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print(f"\n{len(cartes)} carte(s) écrite(s) dans {sortie}")
    print("Ces cartes ne sont PAS encore chargées : le nom du fichier ne "
          "correspond pas au motif niveau_*.json.")
    print("Relis-les, puis renomme le fichier pour les activer, et relance :")
    print("    python database.py && python -m fabrique verifier --avec-llm")
    return 0


def commande_prompt(args) -> int:
    from fabrique.redaction import construire_prompt_externe

    texte = construire_prompt_externe(args.matiere, args.niveau, args.nombre)
    if args.sortie:
        Path(args.sortie).write_text(texte, encoding="utf-8")
        print(f"prompt écrit dans {args.sortie} ({len(texte)} caractères)")
    else:
        print(texte)
    return 0


def commande_importer(args) -> int:
    from fabrique.importer import ErreurImport, ErreurTronquee, importer

    texte = Path(args.fichier).read_text(encoding="utf-8")
    try:
        rapport = importer(texte, args.matiere, args.niveau, args.activer,
                           fusionner=args.fusionner)
    except ErreurTronquee as e:
        print(f"Import interrompu : {e}")
        print(f"\n  Les {len(e.recuperees)} cartes complètes sont récupérables : "
              "relance l'import une fois la suite obtenue et collée à la fin "
              "du même fichier.")
        return 1
    except ErreurImport as e:
        print(f"Import impossible : {e}")
        return 1

    print()
    for s in rapport["signalements"][:20]:
        print(f"  [{s['gravite']:7}] {s['probleme']:28} « {s['titre']} »")
        print(f"            {s['explication'][:140]}")
    print()
    from fabrique.boucle import enregistrer_tour
    enregistrer_tour(args.matiere, args.niveau, rapport, journal=lambda *a: None)

    print(f"  propositions : {rapport['fichier_propositions']}")
    print(f"  quarantaine  : {rapport['fichier_quarantaine']}")
    if rapport["activee"]:
        print("  niveau ACTIVÉ.")
    elif rapport["livrable"]:
        print("  lot conforme — relancer avec --activer pour le mettre en service.")
    else:
        print("  lot NON conforme : relire la quarantaine avant d'activer.")
    return 0 if rapport["livrable"] else 1


def commande_tour(args) -> int:
    from fabrique.boucle import preparer_tour

    fichier = preparer_tour(args.matiere, args.niveau, args.nombre)
    print(f"\nÀ donner au rédacteur : {fichier}")
    print("Puis :  python -m fabrique importer --matiere "
          f"{args.matiere} --niveau {args.niveau} --fichier <sa réponse>")
    return 0


def commande_etat(args) -> int:
    from fabrique.plan import etat_des_plans

    lignes = etat_des_plans()
    if not lignes:
        print("Aucune matière n'a de plan.json.")
        return 1

    print(f"{'matière':16} {'niv':>3} {'écrites':>8} {'visées':>7}  "
          f"{'source':6} titre")
    print("-" * 78)
    total_e = total_v = 0
    for l in lignes:
        total_e += max(0, l["ecrites"])
        total_v += l["visees"]
        marque = "oui" if l["source"] else "—"
        print(f"{l['matiere']:16} {l['niveau']:>3} {l['ecrites']:>8} "
              f"{l['visees']:>7}  {marque:6} {l['titre'][:38]}")
    print("-" * 78)
    print(f"{'TOTAL':16} {'':>3} {total_e:>8} {total_v:>7}  "
          f"soit {total_e * 100 // max(1, total_v)} %")
    return 0


def commande_joue(args) -> int:
    from fabrique.contrat import marquer_joue

    marquer_joue(args.matiere, args.niveau, args.par or "")
    print(f"noté : {args.matiere} niveau {args.niveau} joué en entier.")
    return 0


def commande_contrat(args) -> int:
    from fabrique.contrat import evaluer

    rapport = evaluer(args.matiere, args.niveau)
    print()
    print(f"{rapport['matiere']} — niveau {rapport['niveau']}"
          + (f" : {rapport.get('titre', '')}" if rapport.get("titre") else ""))
    print()
    for clause in rapport["clauses"]:
        marque = "✔" if clause["rempli"] else "✘"
        print(f"  {marque}  {clause['nom']:44} {clause['preuve']}")
    print()
    if rapport["rempli"]:
        print("  LIVRABLE.")
        return 0
    print("  NON LIVRABLE — les clauses non remplies sont ci-dessus.")
    return 1


def main() -> int:
    analyseur = argparse.ArgumentParser(
        prog="fabrique", description="Fabrique de contenu : vérifier et générer.")
    sous = analyseur.add_subparsers(dest="commande", required=True)

    v = sous.add_parser("verifier", help="passe tous les vérificateurs")
    v.add_argument("--matiere", help="limiter à une matière")
    v.add_argument("--avec-llm", action="store_true",
                   help="active le détecteur d'ambiguïté (lent)")
    v.add_argument("--tirages", type=int, default=5,
                   help="réponses indépendantes par carte (défaut : 5)")
    v.set_defaults(fonction=commande_verifier)

    g = sous.add_parser("generer", help="propose des cartes à partir d'une source")
    g.add_argument("--matiere", required=True)
    g.add_argument("--niveau", type=int, required=True)
    g.add_argument("--nombre", type=int, default=10)
    g.add_argument("--source", required=True, help="fichier de référence")
    g.add_argument("--themes", help="thèmes séparés par des virgules")
    g.add_argument("--sortie", help="fichier de propositions")
    g.set_defaults(fonction=commande_generer)

    p_ = sous.add_parser("prompt",
                         help="produit le prompt de rédaction pour un autre modèle")
    p_.add_argument("--matiere", required=True)
    p_.add_argument("--niveau", type=int, required=True)
    p_.add_argument("--nombre", type=int, help="défaut : ce que dit le plan")
    p_.add_argument("--sortie", help="fichier ; sinon sortie standard")
    p_.set_defaults(fonction=commande_prompt)

    i = sous.add_parser("importer",
                        help="reprend la réponse d'un modèle et la contrôle")
    i.add_argument("--matiere", required=True)
    i.add_argument("--niveau", type=int, required=True)
    i.add_argument("--fichier", required=True,
                   help="la réponse du modèle, telle quelle")
    i.add_argument("--activer", action="store_true",
                   help="met en service SI le contrat est rempli")
    i.add_argument("--fusionner", action="store_true",
                   help="complète le niveau existant au lieu de le remplacer")
    i.set_defaults(fonction=commande_importer)

    tr = sous.add_parser("tour",
                        help="prépare le prompt du prochain tour, corrections comprises")
    tr.add_argument("--matiere", required=True)
    tr.add_argument("--niveau", type=int, required=True)
    tr.add_argument("--nombre", type=int)
    tr.set_defaults(fonction=commande_tour)

    e = sous.add_parser("etat", help="où en est chaque matière")
    e.set_defaults(fonction=commande_etat)

    j = sous.add_parser("joue", help="déclare qu'un niveau a été joué en entier")
    j.add_argument("--matiere", required=True)
    j.add_argument("--niveau", type=int, required=True)
    j.add_argument("--par", help="qui l'a joué")
    j.set_defaults(fonction=commande_joue)

    c = sous.add_parser("contrat", help="le niveau est-il livrable ? code 1 sinon")
    c.add_argument("--matiere", required=True)
    c.add_argument("--niveau", type=int, required=True)
    c.set_defaults(fonction=commande_contrat)

    args = analyseur.parse_args()
    return args.fonction(args)


if __name__ == "__main__":
    sys.exit(main())

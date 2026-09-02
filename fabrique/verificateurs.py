"""
Les vérificateurs de la fabrique de contenu.

POURQUOI CE MODULE EXISTE
-------------------------
Écrire 1 200 cartes à la main est hors de portée ; les faire écrire par un
agent sans contrôle produit du contenu plausible et faux. À 2 % d'erreur —
le taux observé sur les 54 premières cartes — cela fait 24 cartes fautives
découvertes une par une par des apprenants, chez des clients.

Le levier n'est donc pas le générateur, c'est cette liste de contrôles.
L'humain ne relit que ce qui est signalé.

LES DOUZE VÉRIFICATEURS
-----------------------
1. schéma et champs obligatoires        déterministe   (dans database.py)
2. la réponse attendue est acceptée     déterministe   (dans database.py)
3. `exemple_code` s'exécute vraiment    déterministe   ← ici
4. détecteur d'ambiguïté                LLM            ← ici
5. doublons et recouvrements            déterministe   ← ici
6. calibrage de difficulté              LLM            ← ici
7. le titre trahit-il la réponse ?      déterministe   ← ici   (19/08/2026)
8. le filet d'acceptation, deux faces   déterministe   ← ici   (19/08/2026)
9. unicité des titres dans la matière   déterministe   ← ici   (19/08/2026)
10. unicité des notions entre niveaux    déterministe   ← ici   (19/08/2026)
11. le lot couvre-t-il les thèmes du plan ?  déterministe ← ici   (19/08/2026)
12. deux matières, la même leçon ?       déterministe   ← ici   (19/08/2026)

Seuls 4 et 6 consomment un modèle, et hors ligne, par lots.

LE HUITIÈME, ET POURQUOI IL EXISTE
----------------------------------
Les sept premiers ne mesurent le filet d'acceptation que dans un sens :
est-il assez large ? Aucun ne demande s'il est trop large. Or élargir est la
réaction naturelle quand une bonne réponse est refusée — et si l'on cède à
chaque refus, le filet finit par tout accepter et l'instrument ne mesure plus
rien. Le contrôle 8 pose donc les deux questions à la fois, sans modèle :

- **face étroite** — chaque `reponses_acceptees` doit être acceptée ;
- **face large** — la réponse d'une AUTRE carte du même niveau doit être
  refusée. Si la carte « liste » accepte « tuple », elle n'enseigne plus rien.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections import defaultdict
from difflib import SequenceMatcher

from database import (
    TYPE_CODE,
    _couverture_mots_cles,
    controler_donnees,
    groupes_mots_cles,
    lire_manifeste,
    lister_cartes,
    normaliser_reponse,
    paquets_de_contenu,
    reponses_de_la_carte,
    valider_reponse,
)

#: Temps maximal accordé à l'exécution d'un exemple.
DELAI_EXECUTION = 5

#: Au-delà, deux ÉNONCÉS se ressemblent.
SEUIL_DOUBLON = 0.82

#: …mais un énoncé proche ne suffit pas : les cartes de vocabulaire et de
#: définition partagent un gabarit par construction. Il faut que la RÉPONSE
#: se ressemble aussi pour parler de doublon.
SEUIL_REPONSE_PROCHE = 0.60

#: Nombre de réponses indépendantes demandées au modèle par carte.
TIRAGES_AMBIGUITE = 5

#: Au-dessus de cette part d'accord avec la réponse de référence, la carte
#: est considérée comme saine et n'est pas examinée plus loin.
SEUIL_CARTE_SAINE = 0.8

#: En dessous, et si les réponses obtenues concordent entre elles, c'est la
#: réponse ATTENDUE qui est probablement trop étroite — pas l'énoncé.
SEUIL_ACCORD = 0.6


def _signalement(carte, probleme, gravite, explication, **extra):
    return {
        "carte_id": carte.get("id"),
        "matiere": carte.get("matiere", ""),
        "niveau": carte.get("niveau"),
        "titre": carte.get("titre", ""),
        "probleme": probleme,
        "gravite": gravite,
        "explication": explication,
        **extra,
    }


# ---------------------------------------------------------------------------
# 1 et 2 — déjà déterministes, on les enveloppe pour un rapport unique
# ---------------------------------------------------------------------------

def verifier_donnees(chemin=None) -> list[dict]:
    """Schéma, JSON, et réponse attendue acceptée par le correcteur."""
    return [
        {"carte_id": None, "matiere": "", "niveau": None, "titre": "",
         "probleme": "donnees_invalides", "gravite": "haute",
         "explication": message}
        for message in controler_donnees(chemin)
    ]


# ---------------------------------------------------------------------------
# 3 — l'exemple de code s'exécute-t-il vraiment ?
# ---------------------------------------------------------------------------

#: Un exemple contenant ces appels ne peut pas être exécuté sans interaction
#: ni effet de bord : on ne le vérifie pas, on le déclare tel quel.
NON_EXECUTABLE = ("input(", "open(", "import os", "import sys",
                  "subprocess", "requests", "urllib")


def _ressemble_a_une_erreur(texte: str) -> bool:
    return bool(texte) and ("Error" in texte or "Warning" in texte)


def executer_exemple(code: str) -> tuple[str, str, bool]:
    """
    Exécute un exemple dans un sous-processus isolé.

    Ce n'est PAS le bac à sable des exercices d'apprenants : c'est un outil
    d'auteur, exécuté localement sur du contenu qu'on écrit soi-même. Il ne
    doit jamais être exposé sur un serveur.
    """
    try:
        resultat = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=DELAI_EXECUTION,
        )
        return resultat.stdout.strip(), resultat.stderr.strip(), True
    except subprocess.TimeoutExpired:
        return "", f"délai de {DELAI_EXECUTION} s dépassé", False
    except Exception as e:  # pragma: no cover
        return "", f"{type(e).__name__}: {e}", False


def verifier_execution(cartes=None, chemin=None) -> list[dict]:
    """
    `exemple_code` produit-il bien `sortie_attendue` ?

    Élimine toute une classe d'erreurs qu'aucune relecture ne rattrape : un
    exemple qui ne tourne pas, ou dont la sortie annoncée est fausse.
    """
    executables = {
        m["matiere"] for _, m in paquets_de_contenu()
        if lire_manifeste(_dossier_de(m["matiere"])).get("code_executable")
    }
    signalements = []

    for carte in (cartes if cartes is not None else lister_cartes(chemin=chemin)):
        if carte.get("matiere") not in executables:
            continue
        code = (carte.get("exemple_code") or "").strip()
        attendu = (carte.get("sortie_attendue") or "").strip()
        if not code or not attendu:
            continue
        if any(motif in code for motif in NON_EXECUTABLE):
            continue

        stdout, stderr, termine = executer_exemple(code)
        if not termine:
            signalements.append(_signalement(
                carte, "exemple_bloque", "haute",
                f"L'exemple ne se termine pas : {stderr}"))
            continue

        # Une carte peut viser une erreur : la sortie attendue est alors le
        # message d'exception, qui arrive sur la sortie d'erreur.
        if _ressemble_a_une_erreur(attendu):
            derniere = stderr.splitlines()[-1].strip() if stderr else ""
            if attendu.split(":")[0] not in derniere:
                signalements.append(_signalement(
                    carte, "erreur_attendue_absente", "haute",
                    f"Attendu « {attendu} », obtenu « {derniere or '(aucune erreur)'} »",
                    obtenu=derniere))
            continue

        if stderr and not stdout:
            signalements.append(_signalement(
                carte, "exemple_en_erreur", "haute",
                f"L'exemple lève une erreur imprévue : "
                f"{stderr.splitlines()[-1] if stderr else ''}",
                obtenu=stderr[-200:]))
            continue

        if stdout != attendu:
            signalements.append(_signalement(
                carte, "sortie_differente", "moyenne",
                f"Attendu « {attendu} », obtenu « {stdout} »",
                obtenu=stdout))

    return signalements


def _dossier_de(matiere: str):
    for dossier, manifeste in paquets_de_contenu():
        if manifeste["matiere"] == matiere:
            return dossier
    raise KeyError(matiere)


# ---------------------------------------------------------------------------
# 5 — doublons et recouvrements
# ---------------------------------------------------------------------------

def verifier_doublons(cartes=None, chemin=None) -> list[dict]:
    """
    Deux cartes qui testent la même chose.

    Contrôle purement déterministe, et le moins cher de la liste : il évite
    qu'un générateur produise trois fois la même question sous trois
    formulations.
    """
    cartes = cartes if cartes is not None else lister_cartes(chemin=chemin)
    par_groupe: dict[tuple, list] = defaultdict(list)
    for carte in cartes:
        par_groupe[(carte.get("matiere"), carte.get("niveau"))].append(carte)

    signalements = []
    for (matiere, niveau), lot in par_groupe.items():
        for i, a in enumerate(lot):
            qa = normaliser_reponse(a.get("question"))
            ra = normaliser_reponse(a.get("reponse"))
            for b in lot[i + 1:]:
                qb = normaliser_reponse(b.get("question"))
                rb = normaliser_reponse(b.get("reponse"))

                if ra and ra == rb:
                    signalements.append(_signalement(
                        a, "meme_reponse", "moyenne",
                        f"Même réponse que #{b.get('id')} « {b.get('titre')} » : "
                        f"« {a.get('reponse')} »",
                        autre_id=b.get("id"), autre_titre=b.get("titre")))
                    continue

                # Comparer les énoncés seuls ne dit rien : « Comment dit-on
                # *bonjour* en espagnol ? » et « … *merci* … » se ressemblent
                # à 85 % tout en testant deux mots différents. Deux cartes ne
                # font double emploi que si l'énoncé ET la réponse coïncident.
                ressemblance = SequenceMatcher(None, qa, qb).ratio()
                proximite_reponse = SequenceMatcher(None, ra, rb).ratio()
                if ressemblance >= SEUIL_DOUBLON and proximite_reponse >= SEUIL_REPONSE_PROCHE:
                    signalements.append(_signalement(
                        a, "question_similaire", "basse",
                        f"Question proche de #{b.get('id')} "
                        f"« {b.get('titre')} » ({ressemblance:.0%}), "
                        f"pour une réponse proche à {proximite_reponse:.0%}",
                        autre_id=b.get("id"), ressemblance=round(ressemblance, 3),
                        proximite_reponse=round(proximite_reponse, 3)))
    return signalements


# ---------------------------------------------------------------------------
# 4 et 6 — détecteur d'ambiguïté et calibrage (LLM)
# ---------------------------------------------------------------------------

_PROMPT_SYSTEME = (
    "Tu réponds à des questions de cours, brièvement et directement. "
    "Tu ne connais PAS la réponse attendue : tu réponds de ton mieux. "
    'Réponds UNIQUEMENT par un objet JSON de la forme {"reponse": "…"}, '
    "sans explication ni phrase d'introduction."
)


def _repondre_a_l_aveugle(carte, tirages=TIRAGES_AMBIGUITE):
    """
    Fait répondre le modèle à la question SANS lui montrer la solution.

    C'est le cœur du détecteur : une question bien formulée conduit un
    répondeur compétent à la bonne réponse, de façon reproductible. Une
    question ambiguë produit des réponses qui divergent — c'est exactement
    le profil de la carte « Parcourir un dictionnaire », dont l'énoncé ne
    disait pas que `personne` était un dictionnaire.
    """
    import correcteur_llm as llm

    config = llm.Config()
    if not config.actif:
        raise llm.ErreurLLM(f"Backend « {config.backend} » inactif")
    modele = llm._choisir_modele(config)

    consigne = [f"Question : {carte.get('question')}"]
    if carte.get("categorie"):
        consigne.append(f"Domaine : {carte['categorie']}")
    consigne.append("Réponds de façon courte et précise.")

    reponses = []
    for tirage in range(tirages):
        charge = llm._requete(
            f"{config.url}/chat/completions",
            {
                "model": modele,
                "messages": [
                    {"role": "system", "content": _PROMPT_SYSTEME},
                    {"role": "user", "content": "\n".join(consigne)},
                ],
                # Température élevée : on CHERCHE la divergence. À zéro, un
                # modèle répéterait la même réponse et l'ambiguïté resterait
                # invisible.
                "temperature": 0.9,
                "max_tokens": 120,
                "response_format": {"type": "json_object"},
                "seed": 1000 + tirage,
            },
            config.cle, config.timeout,
        )
        try:
            contenu = charge["choices"][0]["message"]["content"]
            reponses.append(str(json.loads(contenu).get("reponse", "")).strip())
        except Exception:
            continue
    return [r for r in reponses if r]


def verifier_ambiguite(cartes=None, chemin=None, tirages=TIRAGES_AMBIGUITE,
                       journal=print) -> list[dict]:
    """
    Le vérificateur le plus rentable de la liste.

    Deux signaux distincts, qui ne veulent pas dire la même chose :

    - **réponses divergentes** → l'énoncé est ambigu ;
    - **réponses convergentes mais toutes refusées** → l'énoncé est clair,
      mais la réponse attendue est trop étroite, ou fausse.
    """
    import correcteur_llm as llm

    cartes = cartes if cartes is not None else lister_cartes(chemin=chemin)
    signalements = []

    for carte in cartes:
        try:
            reponses = _repondre_a_l_aveugle(carte, tirages)
        except llm.ErreurLLM as e:
            journal(f"[ambiguite] interrompu : {e}")
            break
        if not reponses:
            continue

        acceptees = sum(1 for r in reponses
                        if valider_reponse(r, carte)["correct"])
        accord = acceptees / len(reponses)
        distinctes = len({normaliser_reponse(r) for r in reponses})
        divergence = distinctes / len(reponses)

        # Un répondeur compétent retrouve la réponse d'une carte bien posée
        # de façon reproductible : au-delà de ce seuil, la carte est saine.
        # Le test porte sur l'accord ET la divergence, jamais sur l'accord
        # seul — une carte à 60 % d'accord dont les réponses partent dans
        # tous les sens reste suspecte.
        if accord >= SEUIL_CARTE_SAINE:
            continue

        if divergence >= 0.6:
            signalements.append(_signalement(
                carte, "enonce_ambigu", "haute",
                f"Sur {len(reponses)} réponses indépendantes, {distinctes} "
                f"formulations différentes et {acceptees} acceptées. "
                "L'énoncé se prête à plusieurs lectures.",
                accord=round(accord, 2), reponses_obtenues=reponses[:5]))
        elif accord < SEUIL_ACCORD:
            signalements.append(_signalement(
                carte, "reponse_attendue_trop_etroite", "haute",
                f"Les réponses obtenues concordent entre elles mais aucune "
                f"n'est acceptée ({acceptees}/{len(reponses)}). La réponse "
                "attendue est peut-être trop étroite — ou fausse.",
                accord=round(accord, 2), reponses_obtenues=reponses[:5]))

    return signalements


def verifier_calibrage(cartes=None, chemin=None, **kwargs) -> list[dict]:
    """
    Une carte de niveau 1 que le modèle rate systématiquement n'est pas de
    niveau 1 — ou n'est pas claire. Réutilise le travail du détecteur
    d'ambiguïté plutôt que de repayer des appels.
    """
    signalements = []
    for s in verifier_ambiguite(cartes, chemin, **kwargs):
        if s.get("niveau") == 1 and s.get("accord", 1) == 0:
            signalements.append({
                **s, "probleme": "niveau_probablement_trop_eleve",
                "gravite": "moyenne",
                "explication": (
                    "Aucune des réponses indépendantes n'est acceptée sur une "
                    "carte de niveau 1. Soit la notion n'est pas de ce niveau, "
                    "soit l'énoncé est à revoir."),
            })
    return signalements


# ---------------------------------------------------------------------------
# 7 — le titre trahit-il la réponse ?
# ---------------------------------------------------------------------------

#: Mots grammaticaux écartés avant comparaison : « un token » et « Token »
#: nomment la même chose, et l'apprenant qui lit le second en en-tête tient
#: déjà le premier.
ARTICLES = {
    "un", "une", "le", "la", "les", "des", "du", "de", "d", "l",
    "son", "sa", "ses", "leur", "leurs", "au", "aux", "a",
}

#: En dessous, une inclusion ne prouve rien : « type » se retrouve dans trop
#: de réponses pour que la coïncidence soit informative.
LONGUEUR_NOYAU_MINIMALE = 4


def _noyau(texte) -> str:
    """Le texte réduit à ce qui porte le sens, articles retirés."""
    return " ".join(m for m in normaliser_reponse(texte).split()
                    if m not in ARTICLES)


def verifier_titre(cartes=None, chemin=None) -> list[dict]:
    """
    Le titre s'affiche AVANT que l'élève réponde : s'il contient la réponse,
    la carte donne sa solution en en-tête et ne mesure plus rien.

    Contrôle né d'un cas réel, le 19 août 2026 : 27 cartes RAG sur 30 étaient
    titrées du mot même qu'elles demandaient — « Ancrage » pour « l'ancrage ».
    Les six autres vérificateurs comparent des cartes entre elles ou une
    réponse au correcteur ; aucun ne regardait ce que l'écran montre. Une
    suite de 116 tests verts et une passe de vérification complète les ont
    laissées passer.
    """
    cartes = cartes if cartes is not None else lister_cartes(chemin=chemin)

    signalements = []
    for carte in cartes:
        titre, reponse = _noyau(carte.get("titre")), _noyau(carte.get("reponse"))
        if not titre or not reponse:
            continue

        if titre == reponse:
            motif = "Le titre est la réponse"
        elif (len(titre) >= LONGUEUR_NOYAU_MINIMALE and titre in reponse) or \
             (len(reponse) >= LONGUEUR_NOYAU_MINIMALE and reponse in titre):
            motif = "Le titre contient la réponse"
        else:
            continue

        # Gravité « moyenne » et non « haute », et le motif compte : depuis que
        # l'affichage masque le titre avant la saisie, la carte reste livrable
        # — elle fonctionne et n'enseigne rien de faux. Ce qui subsiste est un
        # défaut d'étiquetage. Classer en « haute » laisserait 30 alertes
        # rouges permanentes, et une suite durablement rouge cesse d'être lue.
        signalements.append(_signalement(
            carte, "titre_revele_reponse", "moyenne",
            f"{motif} : « {carte.get('titre')} » pour « {carte.get('reponse')} ». "
            f"L'élève la lit en en-tête avant d'avoir répondu.",
            titre_noyau=titre, reponse_noyau=reponse))
    return signalements


# ---------------------------------------------------------------------------
# 8 — le filet d'acceptation, ses deux faces
# ---------------------------------------------------------------------------

#: Deux cartes dont les réponses se ressemblent à ce point ne sont pas un
#: filet trop large : c'est un doublon, et le contrôle 5 s'en occupe. Les
#: confondre produirait deux signalements pour un seul défaut.
SEUIL_REPONSES_JUMELLES = 0.75

#: Nombre maximal de cartes voisines confrontées à chaque carte. Le contrôle
#: est quadratique ; au-delà, on paie cher un signal qu'on a déjà.
VOISINES_MAX = 40


def _englobe(large: str, etroite: str) -> bool:
    """
    La réponse `large` contient-elle tout ce qui porte le sens dans `etroite` ?

    La comparaison se fait sur le noyau — articles retirés — sinon « un
    prompt » ne serait pas vu comme englobé par « le prompt engineering »,
    à cause de « un » contre « le ». Un déterminant ne distingue pas deux
    réponses, et le laisser peser ferait passer pour une confusion ce qui
    n'est qu'une réponse plus bavarde.
    """
    mots_e = [m for m in _noyau(etroite).split() if m]
    return bool(mots_e) and set(mots_e).issubset(set(_noyau(large).split()))


def verifier_filets(cartes=None, chemin=None) -> list[dict]:
    """
    Le filet accepte-t-il ce qu'il doit, et refuse-t-il ce qu'il doit ?

    Entièrement déterministe : aucun appel de modèle. Les reformulations
    légitimes sont déjà écrites dans la carte (`reponses_acceptees`), et les
    quasi-justes fausses sont fournies gratuitement par les cartes voisines —
    même matière, même niveau, réponse différente.

    Né du 19 août 2026 : trois filets « comment qualifie-t-on » élargis à la
    main après avoir refusé une réponse juste, et deux refus examinés puis
    maintenus. La règle écrite ce jour-là — *on élargit quand l'énoncé
    autorise la réponse, jamais parce que la réponse est du bon voisinage* —
    vivait dans la tête d'une personne. Ce contrôle la rend mécanique.
    """
    cartes = cartes if cartes is not None else lister_cartes(chemin=chemin)

    signalements = []

    # --- face étroite : le filet tient-il par autre chose que sa liste ? ---
    #
    # Demander « chaque réponse déclarée est-elle acceptée ? » ne prouve rien :
    # elle est acceptée parce qu'elle est déclarée, à l'identique. La question
    # utile est ailleurs — si l'on retire la liste littérale, le MÉCANISME
    # (mots-clés, expression contenue, mots essentiels) rattrape-t-il encore
    # ces formulations ? Si aucune ne passe, la carte ne tient que par ses
    # littéraux : la première variante qu'un apprenant inventera sera refusée.
    for carte in cartes:
        # `reponses_de_la_carte` décode le champ, qui arrive tantôt en liste
        # (proposition fraîche), tantôt en texte JSON (lu en base) — le lire à
        # la main ferait itérer sur les caractères.
        attendues = [r for r in reponses_de_la_carte(carte) if str(r).strip()]
        canonique = str(carte.get("reponse", "")).strip()
        variantes = [r for r in attendues
                     if normaliser_reponse(r) != normaliser_reponse(canonique)]
        if not variantes:
            continue

        sans_liste = dict(carte)
        sans_liste["reponses_acceptees"] = json.dumps([canonique])
        rattrapees = [r for r in variantes
                      if valider_reponse(r, sans_liste)["correct"]]
        if not rattrapees:
            signalements.append(_signalement(
                carte, "filet_purement_litteral", "basse",
                f"Aucune des {len(variantes)} reformulations déclarées n'est "
                "rattrapée par les mots-clés : le filet ne tient que par sa "
                "liste. Une formulation non prévue sera refusée.",
                variantes=variantes[:5]))

    # --- face large : le filet ne prend pas la réponse d'une voisine -------
    par_groupe = defaultdict(list)
    for carte in cartes:
        par_groupe[(carte.get("matiere"), carte.get("niveau"))].append(carte)

    for lot in par_groupe.values():
        for carte in lot:
            ra = normaliser_reponse(carte.get("reponse"))
            if not ra:
                continue
            declarees = {normaliser_reponse(r) for r in reponses_de_la_carte(carte)}
            captures = []
            for autre in lot[:VOISINES_MAX]:
                if autre is carte:
                    continue
                rb = normaliser_reponse(autre.get("reponse"))
                if not rb or rb == ra:
                    continue
                # Réponses jumelles : c'est un doublon, pas un filet large.
                if SequenceMatcher(None, ra, rb).ratio() >= SEUIL_REPONSES_JUMELLES:
                    continue
                # Deux cartes peuvent partager une bonne réponse sans qu'un
                # filet soit trop large : « quel type renvoie input() ? » et
                # « quel est le type du texte ? » admettent tous deux « str ».
                # Si la carte DÉCLARE accepter cette formulation, ce n'est pas
                # une capture, c'est une réponse juste.
                if normaliser_reponse(autre.get("reponse")) in declarees:
                    continue
                if not valider_reponse(autre.get("reponse"), carte)["correct"]:
                    continue
                # Deux captures très différentes, à ne pas confondre.
                #
                # Si la réponse voisine CONTIENT la réponse attendue — « int,
                # float, str et bool » là où « int » est demandé — l'apprenant
                # n'a pas confondu deux notions : il en a dit plus que demandé,
                # et le correcteur a reconnu ce qu'il cherchait. C'est un
                # défaut de précision de l'énoncé, pas une validation
                # d'erreur : gravité moyenne.
                #
                # Si elle ne la contient pas, le filet valide une réponse
                # franchement autre. Là, la carte n'enseigne plus rien :
                # gravité haute.
                # Englobante aussi quand la réponse voisine porte toutes
                # les notions obligatoires de la carte : « les documents
                # externes fournis » dit bien « externes ». L'apprenant a la
                # notion, il l'a noyée dans une phrase — c'est un défaut de
                # précision, pas une confusion.
                englobante = (_englobe(rb, ra)
                              or _couverture_mots_cles(rb, groupes_mots_cles(carte)) == 1.0)
                captures.append((autre.get("id"), autre.get("titre"),
                                 autre.get("reponse"), englobante))
            if captures:
                for grave in (True, False):
                    lot_capture = [c for c in captures if c[3] is not grave]
                    if not lot_capture:
                        continue
                    details = " ; ".join(
                        f"« {r} » (#{i} {ti})" for i, ti, r, _ in lot_capture[:3])
                    if grave:
                        # Gravité « moyenne », et le motif est écrit ici pour
                        # ne pas se relire de travers dans six mois.
                        #
                        # Un filet trop large n'enseigne rien de faux : la
                        # carte reste juste, son explication reste vraie, elle
                        # est livrable. Ce qu'elle perd, c'est le pouvoir de
                        # séparer un apprenant qui sait d'un apprenant qui
                        # confond. C'est un défaut de MESURE, pas de contenu.
                        #
                        # Le classer « haute » laisserait la suite durablement
                        # rouge sur du contenu déjà livré — et une suite
                        # durablement rouge cesse d'être lue (décision du
                        # 19/08 sur le contrôle du titre, même raisonnement).
                        # Le barrage est ailleurs, et il est plus strict :
                        # `fabrique contrat` refuse un niveau qui porte le
                        # moindre signalement de filet. On ne livre pas un
                        # niveau neuf avec ce défaut ; on ne repeint pas en
                        # rouge ce qui est déjà en service.
                        signalements.append(_signalement(
                            carte, "filet_trop_large", "moyenne",
                            f"Le filet accepte la réponse de "
                            f"{len(lot_capture)} autre(s) carte(s) du même "
                            f"niveau : {details}. Un apprenant qui confond "
                            "deux notions est validé.",
                            captures=[{"id": i, "titre": ti, "reponse": r}
                                      for i, ti, r, _ in lot_capture[:5]]))
                    else:
                        # Gravité BASSE, et le motif compte. Une réponse
                        # voisine qui contient la réponse attendue est le plus
                        # souvent une SPÉCIALISATION : « chemin absolu » là où
                        # « chemin » est demandé, « modèle de langage » là où
                        # « modèle » est demandé. L'apprenant qui répond ça
                        # n'a rien confondu — il a répondu plus précisément
                        # que l'énoncé ne l'exigeait.
                        #
                        # Le classer « moyenne » bloquait la livraison de tout
                        # niveau contenant un terme générique ET ses
                        # spécialisations, c'est-à-dire de tout niveau 1 de
                        # toute matière. Un contrat qu'aucun lot ne peut
                        # remplir ne se lit plus : c'est la même faute que
                        # d'avoir une suite durablement rouge.
                        signalements.append(_signalement(
                            carte, "filet_englobant", "basse",
                            f"Le filet accepte {len(lot_capture)} réponse(s) "
                            f"plus large(s) qui contiennent la réponse "
                            f"attendue : {details}. L'énoncé gagnerait à "
                            "demander la réponse la plus courte.",
                            captures=[{"id": i, "titre": ti, "reponse": r}
                                      for i, ti, r, _ in lot_capture[:5]]))

    return signalements


# ---------------------------------------------------------------------------
# 9 — deux cartes ne portent pas le même titre dans une matière
# ---------------------------------------------------------------------------

def verifier_notions_uniques(cartes=None, chemin=None) -> list[dict]:
    """
    La même notion enseignée deux fois dans une matière, à deux niveaux.

    Né du même import du 19 août 2026 que le contrôle précédent, et il attrape
    ce que celui-ci laisse passer. Sur les 30 cartes reçues pour le niveau 2 de
    Python, **huit portaient une réponse déjà enseignée au niveau 1** — mais
    seules sept portaient aussi le même titre. La huitième, « Visiter les
    éléments un à un » pour `for`, s'appelait autrement que « Parcourir avec
    for » et serait passée entière.

    D'où la leçon, plus utile que le contrôle : **le titre n'identifie pas la
    notion, la réponse l'identifie.** Un modèle à qui l'on donne la liste des
    titres pris renomme ; il ne cesse pas d'enseigner la même chose. La liste
    à lui donner est celle des RÉPONSES déjà enseignées, et c'est ce que le
    prompt de rédaction fait désormais.

    Deux cartes de MÊME niveau qui partagent une réponse relèvent de
    `verifier_doublons` — inutile de les signaler deux fois.
    """
    cartes = cartes if cartes is not None else lister_cartes(chemin=chemin)

    par_reponse = defaultdict(list)
    for carte in cartes:
        reponse = normaliser_reponse(carte.get("reponse"))
        # Une réponse d'un seul caractère, ou vide, n'identifie rien.
        if len(reponse) >= 2:
            par_reponse[(carte.get("matiere"), reponse)].append(carte)

    signalements = []
    for (_, reponse), lot in par_reponse.items():
        niveaux = {c.get("niveau") for c in lot}
        if len(lot) < 2 or len(niveaux) < 2:
            continue
        plus_bas = min(n for n in niveaux if n is not None)
        for carte in lot:
            if carte.get("niveau") == plus_bas:
                continue
            premiere = next(c for c in lot if c.get("niveau") == plus_bas)
            signalements.append(_signalement(
                carte, "notion_deja_enseignee", "haute",
                f"La réponse « {carte.get('reponse')} » est déjà enseignée au "
                f"niveau {plus_bas} par « {premiere.get('titre')} ». Deux "
                "cartes pour une notion : l'apprenant révise deux fois la "
                "même chose et le niveau annoncé ne contient pas ce qu'il "
                "annonce.",
                niveau_dejaVu=plus_bas, autre_titre=premiere.get("titre"),
                autre_id=premiere.get("id")))
    return signalements


def verifier_titres_uniques(cartes=None, chemin=None) -> list[dict]:
    """
    Un titre identique à deux endroits d'une matière, même à deux niveaux
    différents.

    Né du premier import réel, le 19 août 2026 : le prompt de rédaction
    donnait au modèle la liste des 54 titres déjà pris, avec la consigne de
    ne pas les refaire. Il en a repris **sept sur trente**. Aucun des huit
    vérificateurs ne l'a vu — `verifier_doublons` regroupe par (matière,
    niveau), et c'est délibéré : deux cartes de niveaux différents peuvent
    légitimement se ressembler. Mais elles ne peuvent pas porter le même
    titre, sans quoi l'apprenant ne sait plus laquelle il révise et le
    formateur ne sait plus laquelle échoue.

    La leçon, plus large que ce contrôle : **une consigne dans un prompt
    n'est pas un contrôle.** Tout ce qu'on demande à un modèle de respecter
    doit être vérifié après coup, sinon on ne l'a pas demandé, on l'a espéré.
    """
    cartes = cartes if cartes is not None else lister_cartes(chemin=chemin)

    par_titre = defaultdict(list)
    for carte in cartes:
        titre = normaliser_reponse(carte.get("titre"))
        if titre:
            par_titre[(carte.get("matiere"), titre)].append(carte)

    signalements = []
    for (_, _titre), lot in par_titre.items():
        if len(lot) < 2:
            continue
        niveaux = sorted({c.get("niveau") for c in lot})
        for carte in lot[1:]:
            signalements.append(_signalement(
                carte, "titre_deja_pris", "haute",
                f"« {carte.get('titre')} » est porté par {len(lot)} cartes de "
                f"la matière (niveau(x) {', '.join(str(n) for n in niveaux)}). "
                "Un titre identifie une carte : deux cartes homonymes ne se "
                "distinguent plus, ni pour l'apprenant, ni dans un tableau de "
                "bord.",
                niveaux=niveaux,
                autres_ids=[c.get("id") for c in lot if c is not carte][:5]))
    return signalements


# ---------------------------------------------------------------------------
# 11 — le lot répond-il à la commande ?
# ---------------------------------------------------------------------------

#: En dessous de cette part de thèmes couverts, le lot ne traite pas le
#: niveau qu'on lui a demandé. Le seuil est bas volontairement : un thème
#: peut être couvert par une carte qui ne le nomme pas.
COUVERTURE_MINIMALE = 0.55


def _theme_couvert(theme: str, corpus: str) -> bool:
    """Le thème apparaît-il dans le texte des cartes ?"""
    mots = [m for m in normaliser_reponse(theme).split() if len(m) > 3]
    return bool(mots) and all(m in corpus for m in mots)


def verifier_couverture(matiere: str, numero: int, cartes) -> list[dict]:
    """
    Les thèmes que le plan demandait sont-ils traités ?

    Les dix contrôles précédents examinent les cartes une à une, ou les unes
    contre les autres. Aucun ne demandait la chose la plus simple : **le lot
    répond-il à la commande ?**

    Né du premier import du paquet Machine Learning, le 19 août 2026. Trente
    cartes bien formées, zéro signalement grave, et **aucune** sur les notions
    propres au niveau : biais, variance, hyperparamètre, corrélation et
    causalité, échantillon d'entraînement et de test. Le modèle avait rendu un
    autre paquet — bon, mais pas celui-là. Un contrôle de qualité qui ne
    vérifie pas la conformité à la commande laisse passer le hors-sujet.
    """
    from fabrique.plan import niveau_du_plan

    try:
        niveau = niveau_du_plan(matiere, numero)
    except Exception:
        return []
    themes = [t for t in niveau["themes"] if len(t) > 3]
    if not themes:
        return []

    corpus = normaliser_reponse(" ".join(
        f"{c.get('titre','')} {c.get('question','')} {c.get('reponse','')} "
        f"{c.get('explication','')} {c.get('categorie','')}" for c in cartes))

    absents = [t for t in themes if not _theme_couvert(t, corpus)]
    part = 1 - len(absents) / len(themes)
    if part >= COUVERTURE_MINIMALE:
        return []

    modele = cartes[0] if cartes else {"matiere": matiere, "niveau": numero}
    return [_signalement(
        {**dict(modele), "titre": f"(lot {matiere} niveau {numero})"},
        "hors_sujet", "haute",
        f"Le lot ne couvre que {part:.0%} des {len(themes)} notions demandées "
        f"par le plan. Absentes : "
        + ", ".join(absents[:10]) + ("…" if len(absents) > 10 else "")
        + ". Le lot est peut-être bon, mais ce n'est pas celui qui a été "
        "commandé.",
        couverture=round(part, 2), themes_absents=absents[:20])]


# ---------------------------------------------------------------------------
# 12 — deux matières enseignent-elles la même chose ?
# ---------------------------------------------------------------------------

#: Au-delà, deux niveaux de matières différentes ne sont plus voisins : ils
#: sont le même paquet. Un formateur qui achète les deux paie deux fois.
RECOUVREMENT_MAXIMAL = 0.60


def verifier_recouvrement_matieres(cartes=None, chemin=None) -> list[dict]:
    """
    La même leçon vendue sous deux noms.

    Découvert au même import : le niveau 1 de Machine Learning partageait
    **29 réponses sur 29** avec le niveau 1 d'IA, titres réécrits. Les deux
    plans, eux, ne se recoupaient que sur 10 thèmes sur 30 : ce n'est donc pas
    une fatalité des matières voisines, c'est le lot qui avait dérivé.

    Aucun des contrôles précédents ne pouvait le voir : tous travaillent à
    l'intérieur d'une matière. Celui-ci regarde entre elles — et c'est le seul
    endroit d'où le défaut est visible.
    """
    cartes = cartes if cartes is not None else lister_cartes(chemin=chemin)

    par_lot = defaultdict(set)
    for carte in cartes:
        reponse = normaliser_reponse(carte.get("reponse"))
        if len(reponse) >= 2:
            par_lot[(carte.get("matiere"), carte.get("niveau"))].add(reponse)

    signalements = []
    for (matiere, niveau), reponses in sorted(par_lot.items()):
        if not reponses:
            continue
        for (autre_m, autre_n), autres in sorted(par_lot.items()):
            if autre_m == matiere or not autres:
                continue
            part = len(reponses & autres) / len(reponses)
            if part < RECOUVREMENT_MAXIMAL:
                continue
            signalements.append(_signalement(
                {"matiere": matiere, "niveau": niveau,
                 "titre": f"(lot {matiere} niveau {niveau})"},
                "recouvrement_entre_matieres", "haute",
                f"{part:.0%} des réponses de ce lot sont aussi celles de "
                f"« {autre_m} » niveau {autre_n} ({len(reponses & autres)} "
                f"sur {len(reponses)}). Deux matières qui enseignent la même "
                "chose ne font pas deux produits.",
                autre_matiere=autre_m, autre_niveau=autre_n,
                part=round(part, 2)))
    return signalements


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

ORDRE_GRAVITE = {"haute": 0, "moyenne": 1, "basse": 2}


def verifier_tout(matiere=None, avec_llm=False, chemin=None,
                  tirages=TIRAGES_AMBIGUITE, journal=print) -> dict:
    """
    Passe tous les vérificateurs et retourne la file de relecture.

    Les contrôles déterministes tournent toujours. Ceux qui consomment un
    modèle ne s'exécutent que sur demande explicite : ils sont lents, et
    l'essentiel se détecte sans eux.
    """
    cartes = lister_cartes(matiere=matiere, chemin=chemin)
    journal(f"{len(cartes)} carte(s) à vérifier"
            + (f" — matière « {matiere} »" if matiere else ""))

    signalements = []
    for nom, fonction in (
        ("données", lambda: verifier_donnees(chemin)),
        ("exécution des exemples", lambda: verifier_execution(cartes, chemin)),
        ("doublons", lambda: verifier_doublons(cartes, chemin)),
        ("titre révélateur", lambda: verifier_titre(cartes, chemin)),
        ("filets d'acceptation", lambda: verifier_filets(cartes, chemin)),
        ("QCM de rattrapage", lambda: verifier_qcm(cartes, chemin)),
        ("unicité des titres", lambda: verifier_titres_uniques(cartes, chemin)),
        ("unicité des notions", lambda: verifier_notions_uniques(cartes, chemin)),
        ("recouvrement entre matières",
         lambda: verifier_recouvrement_matieres(cartes, chemin)),
    ):
        trouves = fonction()
        journal(f"  {nom:26} {len(trouves)} signalement(s)")
        signalements += trouves

    if avec_llm:
        trouves = verifier_ambiguite(cartes, chemin, tirages, journal)
        journal(f"  {'ambiguïté des énoncés':26} {len(trouves)} signalement(s)")
        signalements += trouves

        calibrage = [s for s in trouves
                     if s.get("niveau") == 1 and s.get("accord", 1) == 0]
        journal(f"  {'calibrage de niveau':26} {len(calibrage)} signalement(s)")
    else:
        journal("  ambiguïté et calibrage     non exécutés (option --avec-llm)")

    signalements.sort(key=lambda s: (ORDRE_GRAVITE.get(s["gravite"], 3),
                                     s.get("matiere") or "",
                                     s.get("carte_id") or 0))

    return {
        "cartes_verifiees": len(cartes),
        "matiere": matiere,
        "llm_utilise": avec_llm,
        "signalements": signalements,
        "par_gravite": {
            g: sum(1 for s in signalements if s["gravite"] == g)
            for g in ("haute", "moyenne", "basse")
        },
    }


# ---------------------------------------------------------------------------
# Vérificateur 13 — le QCM de rattrapage
# ---------------------------------------------------------------------------
#
# Déterministe, donc gratuit, donc toujours actif. Le QCM est facultatif : une
# carte qui n'en a pas n'est jamais signalée. Mais un QCM présent doit être
# valide, sans quoi il enseigne à deviner au lieu d'enseigner la notion.

def verifier_qcm(cartes=None, chemin=None) -> list[dict]:
    """
    Contrôle la forme et la loyauté des QCM.

    Les contrôles de forme viennent de `database.defauts_du_qcm`, partagés avec
    le chargement — un seul endroit décide de ce qu'est un QCM valide.

    Ce vérificateur y ajoute le seul contrôle qui demande la carte entière, et
    c'est celui qui compte : **la bonne option doit être acceptée comme réponse
    à la question ouverte.** Si elle ne l'est pas, le QCM et la question ne
    portent pas sur la même notion, et l'apprenant est corrigé deux fois de
    deux façons différentes.
    """
    from database import defauts_du_qcm, lire_qcm, valider_reponse

    cartes = cartes if cartes is not None else lister_cartes(chemin=chemin)
    signalements = []

    for carte in cartes:
        qcm = lire_qcm(carte)
        if not qcm:
            continue

        for defaut in defauts_du_qcm(qcm):
            gravite = "haute" if ("options" in defaut or "reponse" in defaut
                                  or "identiques" in defaut) else "moyenne"
            signalements.append(_signalement(
                carte, "qcm_invalide", gravite, defaut))

        options = qcm.get("options") or []
        index = qcm.get("reponse")
        if not isinstance(index, int) or not 0 <= index < len(options):
            continue

        bonne = str(options[index])
        if not valider_reponse(bonne, carte)["correct"]:
            signalements.append(_signalement(
                carte, "qcm_hors_sujet", "haute",
                "la bonne option du QCM n'est pas acceptée comme réponse à la "
                "question ouverte : le QCM et la question ne portent pas sur "
                "la même notion",
                option=bonne))

        for i, option in enumerate(options):
            if i == index:
                continue
            if valider_reponse(str(option), carte)["correct"]:
                signalements.append(_signalement(
                    carte, "qcm_distracteur_juste", "haute",
                    f"le distracteur « {option} » est accepté comme bonne "
                    "réponse par le correcteur : il n'est pas faux",
                    option=str(option)))

    return signalements

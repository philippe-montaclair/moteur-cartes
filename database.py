"""
Base de données et validation des réponses.

RÈGLE D'ARCHITECTURE
--------------------
La correction des réponses est implémentée ICI, et NULLE PART AILLEURS.
Le JavaScript n'a pas le droit de recorriger : il appelle POST /api/check.

C'est le point qui faisait échouer la version précédente : deux
implémentations (Python + JS) qui divergeaient. Une seule source de vérité.
"""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from difflib import SequenceMatcher
from pathlib import Path

RACINE = Path(__file__).resolve().parent
CHEMIN_BASE = RACINE / "prompt_app.db"
DOSSIER_CONTENUS = RACINE / "contenus"
DOSSIER_DONNEES = RACINE / "data"      # ancien emplacement, encore accepté

NIVEAU_MIN = 1
NIVEAU_MAX = 7

# Types de question : détermine la stratégie de comparaison.
TYPE_MOT_CLE = "mot_cle"          # réponse courte et précise : while, def, int
TYPE_CODE = "code"                # instruction : nombres.append(4)
TYPE_TEXTE = "texte"              # explication libre
TYPE_VOCABULAIRE = "vocabulaire"  # un mot dans une langue étrangère
TYPES_VALIDES = {TYPE_MOT_CLE, TYPE_CODE, TYPE_TEXTE, TYPE_VOCABULAIRE}

COLONNES = (
    "id", "matiere", "langue", "niveau", "titre", "question", "reponse",
    "explication", "exemple_code", "sortie_attendue", "erreur_frequente",
    "indice", "mots_cles", "difficulte", "prerequis", "categorie", "type",
    "reponses_acceptees", "qcm",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    matiere            TEXT    NOT NULL DEFAULT 'python',
    langue             TEXT    NOT NULL DEFAULT 'fr',
    niveau             INTEGER NOT NULL,
    titre              TEXT    NOT NULL,
    question           TEXT    NOT NULL,
    reponse            TEXT    NOT NULL,
    explication        TEXT    NOT NULL DEFAULT '',
    exemple_code       TEXT    NOT NULL DEFAULT '',
    sortie_attendue    TEXT    NOT NULL DEFAULT '',
    erreur_frequente   TEXT    NOT NULL DEFAULT '',
    indice             TEXT    NOT NULL DEFAULT '',
    mots_cles          TEXT    NOT NULL DEFAULT '[]',
    difficulte         INTEGER NOT NULL DEFAULT 1,
    prerequis          TEXT    NOT NULL DEFAULT '',
    categorie          TEXT    NOT NULL DEFAULT '',
    type               TEXT    NOT NULL DEFAULT 'texte',
    reponses_acceptees TEXT    NOT NULL DEFAULT '[]',
    qcm                TEXT    NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_cards_niveau  ON cards(niveau);
CREATE INDEX IF NOT EXISTS idx_cards_matiere ON cards(matiere, niveau);
"""


# ---------------------------------------------------------------------------
# Connexion
# ---------------------------------------------------------------------------

def get_connection(chemin: Path | str | None = None) -> sqlite3.Connection:
    """Ouvre une connexion SQLite dont les lignes se lisent comme des dicts."""
    connection = sqlite3.connect(str(chemin or CHEMIN_BASE))
    connection.row_factory = sqlite3.Row
    return connection


@contextmanager
def connexion(chemin: Path | str | None = None):
    """Connexion en gestionnaire de contexte, fermée quoi qu'il arrive."""
    conn = get_connection(chemin)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

_APOSTROPHES = {"’": "'", "‘": "'", "´": "'"}
_GUILLEMETS = {"“": '"', "”": '"', "«": '"', "»": '"'}

# Mots vides, PAR LANGUE.
#
# C'était le seul endroit où le moteur restait verrouillé en français : une
# liste française appliquée à de l'espagnol ne retire rien, et la tolérance
# s'effondre. La langue est désormais portée par le paquet de contenu
# (`contenus/<matiere>/manifeste.json`) et stockée sur chaque carte.
MOTS_VIDES_FR = {
    "a", "au", "aux", "avec", "c", "ce", "ces", "cet", "cette", "d", "dans",
    "de", "des", "du", "elle", "en", "est", "et", "eux", "il", "ils", "j",
    "je", "l", "la", "le", "les", "leur", "lui", "ma", "mais", "me", "meme",
    "mes", "moi", "mon", "n", "ne", "nos", "notre", "nous", "on", "ont", "ou",
    "par", "pas", "pour", "qu", "que", "qui", "sa", "se", "ses", "son", "sont",
    "sur", "ta", "te", "tes", "toi", "ton", "tu", "un", "une", "vos", "votre",
    "vous", "y", "s", "t", "il", "cela", "ca", "donc", "alors", "car",
    # Formules de remplissage propres à cet exercice
    "mot", "mots", "cle", "cles", "reponse", "instruction", "fonction",
    "methode", "utiliser", "utilise", "on", "faut", "il", "s", "agit",
    "permet", "sert", "ecrit", "ecrire",
}

MOTS_VIDES_EN = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "of", "to", "in", "on", "at", "by", "for", "with", "from", "as", "that",
    "this", "these", "those", "it", "its", "and", "or", "not", "you", "we",
    "they", "he", "she", "i", "do", "does", "did", "has", "have", "had",
    "will", "would", "can", "could", "means", "meaning", "word", "keyword",
    "answer",
}

MOTS_VIDES_ES = {
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "al",
    "a", "en", "y", "o", "que", "es", "son", "ser", "estar", "esta", "este",
    "se", "lo", "por", "para", "con", "su", "sus", "no", "si", "palabra",
    "respuesta",
}

MOTS_VIDES_PAR_LANGUE = {
    "fr": MOTS_VIDES_FR,
    "en": MOTS_VIDES_EN,
    "es": MOTS_VIDES_ES,
}

#: Compatibilité avec le code existant qui importait `MOTS_VIDES`.
MOTS_VIDES = MOTS_VIDES_FR


def _sans_accents(texte: str) -> str:
    decompose = unicodedata.normalize("NFD", texte)
    return "".join(c for c in decompose if unicodedata.category(c) != "Mn")


def _uniformiser_signes(texte: str) -> str:
    for source, cible in {**_APOSTROPHES, **_GUILLEMETS}.items():
        texte = texte.replace(source, cible)
    return texte


def normaliser_reponse(texte) -> str:
    """
    Normalisation pour les réponses en français ou les mots-clés.

    Minuscules, accents supprimés, ponctuation remplacée par des espaces,
    espaces multiples réduits. Les opérateurs Python (// / % ** == != <= >=)
    sont préservés car ils PORTENT le sens de la réponse.

    >>> normaliser_reponse("Le mot-clé est while.")
    'le mot cle est while'
    >>> normaliser_reponse("int, float, str et bool.")
    'int float str et bool'
    """
    if texte is None:
        return ""
    texte = _uniformiser_signes(str(texte))
    texte = _sans_accents(texte).lower()

    # On protège les symboles porteurs de sens avant de détruire la
    # ponctuation. Sans cela, la réponse « # » se normaliserait en chaîne
    # vide et deviendrait impossible à valider.
    # Le tiret simple est volontairement absent : en français il sert de
    # trait d'union (« mot-clé ») bien plus souvent que de soustraction.
    operateurs = ["**", "//", "==", "!=", "<=", ">=", "+=", "-=",
                  "%", "/", "*", "+", "<", ">", "=", "#", ":"]
    for i, op in enumerate(operateurs):
        texte = texte.replace(op, f" \x00{i}\x00 ")

    texte = re.sub(r"[^\w\s\x00]", " ", texte, flags=re.UNICODE)

    for i, op in enumerate(operateurs):
        texte = texte.replace(f"\x00{i}\x00", op)

    return re.sub(r"\s+", " ", texte).strip()


def normaliser_code(texte) -> str:
    """
    Normalisation pour une instruction Python.

    Tous les espaces sont supprimés et les guillemets uniformisés, pour que
    `nombres.append( 4 )` == `nombres.append(4)` et que "a" == 'a'.
    La casse est ignorée : à ce niveau, on corrige une idée, pas une syntaxe
    exacte.
    """
    if texte is None:
        return ""
    texte = _uniformiser_signes(str(texte)).lower()
    texte = texte.replace('"', "'")
    return re.sub(r"\s+", "", texte)


def mots_significatifs(texte, langue: str = "fr") -> list[str]:
    """Tokens de la réponse, mots vides de la langue retirés."""
    vides = MOTS_VIDES_PAR_LANGUE.get((langue or "fr").lower(), MOTS_VIDES_FR)
    return [m for m in normaliser_reponse(texte).split() if m not in vides]


def distance_edition(a: str, b: str) -> int:
    """
    Distance de Levenshtein, en Python pur.

    Sert au type `vocabulaire` : une lettre d'écart est pardonnée (frappe),
    deux ne le sont pas (le mot n'est pas su).
    """
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    precedente = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        courante = [i]
        for j, cb in enumerate(b, 1):
            courante.append(min(
                precedente[j] + 1,          # suppression
                courante[j - 1] + 1,        # insertion
                precedente[j - 1] + (ca != cb),  # substitution
            ))
        precedente = courante
    return precedente[-1]


# ---------------------------------------------------------------------------
# Lecture tolérante des colonnes JSON
# ---------------------------------------------------------------------------

def charger_liste_json(valeur) -> list:
    """
    Lit une colonne JSON sans jamais lever d'exception.

    C'était l'autre source de pannes : une ligne contenant `[]`, `NULL`,
    du JSON invalide ou une simple chaîne faisait planter (ou renvoyer vide)
    la validation. Ici, tout cas dégradé retourne une liste exploitable.
    """
    if valeur is None:
        return []
    if isinstance(valeur, (list, tuple)):
        return [v for v in valeur if v not in (None, "")]

    texte = str(valeur).strip()
    if not texte or texte in {"[]", "null", "None"}:
        return []

    try:
        charge = json.loads(texte)
    except (ValueError, TypeError):
        # Tolérance : "while, le mot-clé while" -> liste séparée par virgules
        return [p.strip() for p in texte.split(",") if p.strip()]

    if isinstance(charge, str):
        return [charge] if charge.strip() else []
    if isinstance(charge, (list, tuple)):
        return [v for v in charge if v not in (None, "", [])]
    return [str(charge)]


def reponses_de_la_carte(carte) -> list[str]:
    """
    Toutes les formulations acceptées pour une carte.

    `reponse` sert TOUJOURS de filet de sécurité : même si
    `reponses_acceptees` est vide, corrompu ou mal rempli, la réponse
    canonique reste acceptée.
    """
    acceptees = [str(r) for r in charger_liste_json(carte["reponses_acceptees"])]
    canonique = str(carte["reponse"] or "").strip()
    if canonique and canonique not in acceptees:
        acceptees.append(canonique)
    return acceptees


def groupes_mots_cles(carte) -> list[list[str]]:
    """
    `mots_cles` décrit les notions OBLIGATOIRES de la réponse.

    Chaque élément est soit un mot, soit une liste de synonymes acceptés.
    Exemple : [["decimal", "float", "virgule"], ["entier", "entiere"]]
    signifie « la réponse doit évoquer le décimal ET l'entier ».
    """
    groupes = []
    for element in charger_liste_json(carte["mots_cles"]):
        if isinstance(element, (list, tuple)):
            variantes = [str(v) for v in element if str(v).strip()]
        else:
            variantes = [str(element)]
        if variantes:
            groupes.append(variantes)
    return groupes


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

#: Au-delà de ce rapport entre la longueur de la réponse donnée et celle de
#: l'expression attendue, la contenir ne prouve plus rien.
#:
#: Défaut trouvé le 19/08/2026 par le vérificateur de filets. La carte
#: « quel opérateur accepte l'une ou l'autre condition ? », réponse `or`,
#: acceptait « valeur truthy ou falsy » — parce que « ou » y figure comme mot
#: entier. Elle aurait accepté « je ne sais pas, ou alors non ». Même patron
#: sur la carte du type de `input`, dont la réponse acceptée « str » se
#: retrouve dans « int, float, str et bool ».
#:
#: Le contrôle des bornes de mot évitait « int » dans « print ». Il ne
#: protégeait pas contre le fragment noyé dans une phrase — parce qu'une
#: réponse courte est presque toujours contenue quelque part.
#: Mots de liaison : les trouver dans une phrase n'apprend rien sur ce que
#: la phrase dit. Séparé des mots vides, qui servent à une autre comparaison.
LIAISONS = {"ou", "et", "ni", "or", "de", "du", "la", "le", "un", "en",
            "a", "y", "si", "ce", "se", "on", "il"}

#: En dessous, une expression est trop courte pour que sa seule présence dans
#: une phrase soit une preuve. Deux ou trois caractères se retrouvent partout.
LONGUEUR_EXPRESSION_SURE = 4


def _contient_expression(texte_normalise: str, attendu: str) -> bool:
    """
    L'expression attendue apparaît-elle comme un mot entier, et pèse-t-elle
    assez dans la réponse pour que ce soit une preuve ?

    Deux gardes, et la seconde a coûté un défaut réel :

    1. **Bornes de mot** — « int » ne doit pas être trouvé dans « print ».
    2. **Proportion** — une expression courte noyée dans une phrase longue
       n'est pas une réponse. « or » figure dans « valeur truthy ou falsy » ;
       ça n'en fait pas la bonne réponse à « quel opérateur… ».
    """
    attendu = normaliser_reponse(attendu)
    if not attendu:
        return False
    motif = r"(?<!\w)" + re.escape(attendu) + r"(?!\w)"
    if re.search(motif, texte_normalise) is None:
        return False

    if len(attendu) >= LONGUEUR_EXPRESSION_SURE:
        return True

    return preuve_courte_suffisante(texte_normalise, attendu)


def preuve_courte_suffisante(texte_normalise: str, attendu: str) -> bool:
    """
    Une expression courte trouvée dans une réponse en est-elle une PREUVE ?

    Au-delà de `LONGUEUR_EXPRESSION_SURE`, oui : un mot de cinq lettres ne
    se trouve pas par hasard. En dessous, deux cas — et deux seulement — où
    la trouver ne prouve rien.

    La première version de cette garde comparait les longueurs — refusée par
    les tests en trois minutes : « le type est int » est cinq fois plus long
    que « int » et reste la bonne réponse. Le rapport de longueur ne
    discrimine pas ; la FORME de la réponse, si.

    ⚠️ **Cette fonction est appelée par les DEUX chemins d'acceptation**, et
    c'est le motif de son extraction, le 2 septembre 2026. Écrite le 21 août
    à l'intérieur de `_contient_expression`, elle ne protégeait que le chemin
    des `reponses_acceptees`. Le chemin des `mots_cles` avait sa propre
    comparaison et acceptait toujours : sur la carte réelle attendant « str »,
    « int, float, str et bool » était noté **correct**, c'est-à-dire
    exactement le défaut que le 21 août déclarait corrigé.

    C'est la troisième fois sur ce projet qu'une règle vraie dans un chemin
    est fausse dans l'autre. La leçon est toujours la même : **une garde se
    pose là où la décision se prend, pas là où on l'a remarquée.**
    """
    if len(attendu) >= LONGUEUR_EXPRESSION_SURE:
        return True

    # 1. Un mot de liaison. « ou » se trouve dans n'importe quelle phrase :
    #    « valeur truthy ou falsy » n'est pas une réponse à « quel opérateur
    #    accepte l'une ou l'autre condition ? ».
    if attendu in LIAISONS:
        return False

    # 2. Une énumération. « str » est un élément de « int, float, str et
    #    bool » ; l'apprenant a listé les types, il n'a pas répondu « str ».
    #
    #    Le repère n'est PAS la virgule : `normaliser_reponse` l'a déjà
    #    retirée, et le premier essai a échoué pour cette raison. C'est le
    #    nombre de mots PORTEURS qui distingue — « le type est int » en a
    #    deux, « int float str et bool » en a quatre.
    if len(mots_significatifs(texte_normalise)) >= 4:
        return False

    return True


def _couverture_mots_cles(reponse_normalisee: str, groupes: list[list[str]]) -> float:
    """Part des notions obligatoires effectivement présentes (0.0 à 1.0)."""
    if not groupes:
        return 0.0
    trouves = 0
    for variantes in groupes:
        for variante in variantes:
            cible = normaliser_reponse(variante)
            if not cible:
                continue
            # Les mots longs tolèrent une variation de terminaison :
            # « entier » valide « entière » et « entiers ».
            # Les mots courts exigent une correspondance exacte, sinon
            # « in » validerait « int ».
            if len(cible) >= 5:
                motif = r"(?<!\w)" + re.escape(cible)
            else:
                motif = r"(?<!\w)" + re.escape(cible) + r"(?!\w)"
            if not re.search(motif, reponse_normalisee):
                continue
            # La même garde que sur l'autre chemin, et au même endroit :
            # trouver « str » dans « int, float, str et bool » ne prouve pas
            # que l'apprenant a répondu « str ». Corrigé le 02/09/2026.
            if not preuve_courte_suffisante(reponse_normalisee, cible):
                continue
            trouves += 1
            break
    return trouves / len(groupes)


#: Marqueurs de négation, comparés sur le texte NORMALISÉ (minuscules,
#: accents retirés) mais AVANT le retrait des mots vides — « pas » en est un,
#: et le laisser filtrer effaçait la négation avant qu'on puisse la voir.
#:
#: Découvert le 19 août 2026 par le vérificateur de filets, sur le premier
#: import des paquets IA et Linux : la carte « apprentissage supervisé »
#: acceptait « apprentissage non supervisé », et la carte « c'est un entier »
#: acceptait « ce n'est pas un entier ». Trois chemins d'acceptation sur
#: quatre validaient le contraire de la bonne réponse — parce qu'ils comptent
#: des mots présents et qu'une négation, elle, n'ajoute rien : elle inverse.
NEGATIONS = {
    "non", "pas", "jamais", "aucun", "aucune", "ni", "sans", "nul", "nulle",
    "rien", "faux", "no", "not", "never", "neither",
}


def _polarite(texte: str) -> bool:
    """Le texte porte-t-il une négation ? Comparé sur le texte normalisé."""
    return bool(NEGATIONS & set(normaliser_reponse(texte).split()))


def _similarite(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _recouvrement_tokens(donnee: list[str], attendue: list[str]) -> float:
    """Part des mots significatifs attendus que l'utilisateur a bien écrits."""
    if not attendue:
        return 0.0
    ensemble = set(donnee)
    presents = sum(1 for mot in set(attendue) if mot in ensemble)
    return presents / len(set(attendue))


def valider_reponse(reponse_utilisateur, carte) -> dict:
    """
    Corrige une réponse.

    Retourne {"statut": "correct" | "proche" | "incorrect",
              "correct": bool, "score": float, "raison": str}

    « proche » n'est pas une réussite, mais permet un retour pédagogique utile
    au lieu d'un simple « faux ».
    """
    brute = "" if reponse_utilisateur is None else str(reponse_utilisateur).strip()
    if not brute:
        return {"statut": "incorrect", "correct": False, "score": 0.0,
                "raison": "reponse_vide"}

    type_carte = (carte["type"] or TYPE_TEXTE).strip().lower()
    if type_carte not in TYPES_VALIDES:
        type_carte = TYPE_TEXTE

    acceptees = reponses_de_la_carte(carte)
    langue = (carte["langue"] if "langue" in carte.keys() else "fr") or "fr"

    # --- 0. Mode vocabulaire -------------------------------------------------
    # L'inverse exact du mode texte. En Python, « clés » ≈ « clefs » : la
    # formulation n'est pas la compétence évaluée. En vocabulaire,
    # `receive` ≠ `recieve` : L'ORTHOGRAPHE EST LA COMPÉTENCE. Appliquer ici
    # la tolérance sémantique reviendrait à valider des fautes.
    if type_carte == TYPE_VOCABULAIRE:
        donnee = normaliser_reponse(brute)
        meilleure_distance = None
        mot_vise = ""
        longueur_cible = 0
        for attendue in acceptees:
            cible = normaliser_reponse(attendue)
            if not cible:
                continue
            if donnee == cible:
                return {"statut": "correct", "correct": True, "score": 1.0,
                        "raison": "mot_exact"}
            d = distance_edition(donnee, cible)
            if meilleure_distance is None or d < meilleure_distance:
                meilleure_distance, mot_vise, longueur_cible = d, attendue, len(cible)

        # Une seule lettre d'écart : accepté, mais on montre l'orthographe
        # exacte — sinon on entérine la faute au lieu de l'enseigner.
        #
        # Le seuil porte sur le mot ATTENDU, pas sur la saisie : sur trois
        # lettres, une lettre d'écart ne relève plus de la frappe mais d'un
        # autre mot (« pan » / « pon »).
        if meilleure_distance == 1 and longueur_cible >= 4:
            return {"statut": "correct", "correct": True, "score": 0.9,
                    "raison": "faute_de_frappe",
                    "orthographe_exacte": mot_vise}
        if meilleure_distance is not None and meilleure_distance <= 2:
            return {"statut": "proche", "correct": False, "score": 0.5,
                    "raison": "orthographe_trop_eloignee",
                    "orthographe_exacte": mot_vise}
        return {"statut": "incorrect", "correct": False, "score": 0.0,
                "raison": "mot_different"}

    # --- 1. Mode code : comparaison sans espaces, ponctuation significative --
    if type_carte == TYPE_CODE:
        donnee = normaliser_code(brute)
        meilleure = 0.0
        for attendue in acceptees:
            cible = normaliser_code(attendue)
            if not cible:
                continue
            if donnee == cible:
                return {"statut": "correct", "correct": True, "score": 1.0,
                        "raison": "code_identique"}
            # L'instruction attendue est présente dans la phrase de
            # l'utilisateur : « la réponse est len(mot) », « len(mot). »
            # Seuil de 4 caractères pour éviter les coïncidences.
            if len(cible) >= 4 and cible in donnee:
                return {"statut": "correct", "correct": True, "score": 0.96,
                        "raison": "code_contenu"}
            # Fragment juste mais incomplet : « append » pour
            # « nombres.append(4) ». On le signale plutôt que de le rejeter.
            if len(donnee) >= 3 and donnee in cible:
                meilleure = max(meilleure, 0.75)
            meilleure = max(meilleure, _similarite(donnee, cible))
        if meilleure >= 0.72:
            return {"statut": "proche", "correct": False, "score": meilleure,
                    "raison": "code_incomplet"}
        return {"statut": "incorrect", "correct": False, "score": meilleure,
                "raison": "code_different"}

    # --- 2. Modes mot-clé et texte ------------------------------------------
    donnee = normaliser_reponse(brute)
    tokens_donnee = mots_significatifs(brute, langue)

    # On distingue deux mesures : le recouvrement de SENS (mots significatifs
    # partagés) et la ressemblance de CARACTÈRES. Seule la première justifie
    # un « presque » — sinon « les valeurs » passerait pour proche de
    # « les clés du dictionnaire » par simple similitude de lettres.
    meilleur_sens = 0.0
    meilleure = 0.0
    for attendue in acceptees:
        cible = normaliser_reponse(attendue)
        if not cible:
            continue

        # 2a. Égalité après normalisation.
        #     « int, float, str et bool. » == « int, float, str et bool »
        if donnee == cible:
            return {"statut": "correct", "correct": True, "score": 1.0,
                    "raison": "identique"}

        # 2b. La formulation attendue est contenue dans la phrase de
        #     l'utilisateur. « Le mot-clé est while. » contient « while ».
        #     …sauf si l'utilisateur a nié ce qu'il cite : « ce n'est pas
        #     while » contient « while » tout en disant le contraire.
        if _contient_expression(donnee, cible) and \
                _polarite(donnee) == _polarite(cible):
            return {"statut": "correct", "correct": True, "score": 0.97,
                    "raison": "expression_contenue"}

        # 2c. Mêmes mots significatifs, ordre ou liaisons différents.
        tokens_cible = mots_significatifs(attendue, langue)
        meme_polarite = _polarite(donnee) == _polarite(cible)
        if tokens_cible and meme_polarite and \
                set(tokens_cible) == set(tokens_donnee):
            return {"statut": "correct", "correct": True, "score": 0.95,
                    "raison": "memes_mots"}

        if tokens_cible:
            recouvrement = _recouvrement_tokens(tokens_donnee, tokens_cible)
            meilleur_sens = max(meilleur_sens, recouvrement)
            # 2d. L'essentiel des notions attendues est présent — et la
            #     phrase ne les nie pas. « apprentissage non supervisé »
            #     contient les deux mots de « apprentissage supervisé ».
            if recouvrement >= 0.8 and len(tokens_cible) >= 2 and meme_polarite:
                return {"statut": "correct", "correct": True,
                        "score": recouvrement, "raison": "mots_essentiels"}

        meilleure = max(meilleure, _similarite(donnee, cible))

    # 2e. Filet de sécurité : les notions obligatoires sont-elles là ?
    groupes = groupes_mots_cles(carte)
    couverture = _couverture_mots_cles(donnee, groupes)
    reponse_canonique = str(carte["reponse"] if "reponse" in carte.keys() else "")
    if groupes and couverture == 1.0 and \
            _polarite(donnee) == _polarite(reponse_canonique):
        return {"statut": "correct", "correct": True, "score": 1.0,
                "raison": "mots_cles_requis"}

    sens = max(meilleur_sens, couverture)
    score = max(sens, meilleure)
    # « presque » exige un vrai recouvrement de sens, ou une ressemblance
    # littérale très forte (faute de frappe sur la bonne réponse).
    if sens >= 0.5 or meilleure >= 0.85:
        return {"statut": "proche", "correct": False, "score": score,
                "raison": "partiellement_juste"}
    return {"statut": "incorrect", "correct": False, "score": score,
            "raison": "different"}


def reponse_acceptee(reponse_utilisateur, reponses_acceptees) -> bool:
    """
    Compatibilité avec l'ancienne signature du projet.

    Conservée pour ne pas casser du code existant : renvoie simplement un
    booléen à partir d'une liste de réponses acceptées.
    """
    carte = {
        "reponse": "",
        "reponses_acceptees": json.dumps(list(reponses_acceptees or [])),
        "mots_cles": "[]",
        "type": TYPE_TEXTE,
    }
    return valider_reponse(reponse_utilisateur, carte)["correct"]


# ---------------------------------------------------------------------------
# Chargement des questions
# ---------------------------------------------------------------------------

DEFAUTS = {
    "explication": "", "exemple_code": "", "sortie_attendue": "",
    "erreur_frequente": "", "indice": "", "mots_cles": [],
    "difficulte": 1, "prerequis": "", "categorie": "", "type": TYPE_TEXTE,
    "reponses_acceptees": [], "matiere": "python", "langue": "fr",
    "qcm": {},
}

MANIFESTE_DEFAUT = {
    "matiere": "", "nom": "", "description": "",
    "langue_enseignement": "fr",   # langue dans laquelle l'apprenant réfléchit
    "langue_reponse": "",          # langue des réponses ; défaut = enseignement
    "langue_cible": "",            # langue étudiée, pour une matière de langue
    "type_defaut": TYPE_TEXTE,
}


def lire_manifeste(dossier: Path) -> dict:
    """
    Lit `manifeste.json` d'un paquet de contenu.

    C'est lui qui porte la langue : ajouter l'allemand devient un dossier,
    jamais un correctif dans le code.
    """
    manifeste = dict(MANIFESTE_DEFAUT)
    manifeste["matiere"] = dossier.name
    manifeste["nom"] = dossier.name.replace("_", " ").capitalize()

    fichier = dossier / "manifeste.json"
    if fichier.exists():
        manifeste.update(json.loads(fichier.read_text(encoding="utf-8")))

    if not manifeste["langue_reponse"]:
        # Pour une matière de langue, la réponse est écrite dans la langue
        # cible ; pour les autres, dans la langue d'enseignement.
        manifeste["langue_reponse"] = (
            manifeste["langue_cible"] or manifeste["langue_enseignement"]
        )
    return manifeste


def paquets_de_contenu() -> list[tuple[Path, dict]]:
    """
    Tous les paquets disponibles : `contenus/<matiere>/`.

    L'ancien emplacement `data/` reste accepté et devient la matière
    « python », pour qu'une installation existante continue de fonctionner.
    """
    paquets = []
    if DOSSIER_CONTENUS.is_dir():
        for dossier in sorted(DOSSIER_CONTENUS.iterdir()):
            if dossier.is_dir() and any(dossier.glob("niveau_*.json")):
                paquets.append((dossier, lire_manifeste(dossier)))
    if not paquets and DOSSIER_DONNEES.is_dir():
        manifeste = dict(MANIFESTE_DEFAUT)
        manifeste.update({"matiere": "python", "nom": "Python"})
        manifeste["langue_reponse"] = "fr"
        paquets.append((DOSSIER_DONNEES, manifeste))
    return paquets


def lire_fichiers_questions() -> list[dict]:
    """Lit tous les paquets et complète les champs manquants."""
    cartes = []
    for dossier, manifeste in paquets_de_contenu():
        for fichier in sorted(dossier.glob("niveau_*.json")):
            contenu = json.loads(fichier.read_text(encoding="utf-8"))
            for brute in contenu:
                carte = {**DEFAUTS, **brute}
                carte.setdefault("type", manifeste["type_defaut"])
                if not brute.get("type"):
                    carte["type"] = manifeste["type_defaut"]
                carte["matiere"] = manifeste["matiere"]
                carte["langue"] = brute.get("langue") or manifeste["langue_reponse"]
                for obligatoire in ("niveau", "titre", "question", "reponse"):
                    if not str(carte.get(obligatoire, "")).strip():
                        raise ValueError(
                            f"{fichier.name} : champ '{obligatoire}' manquant "
                            f"pour « {carte.get('titre', '?')} »"
                        )
                cartes.append(carte)
    return cartes


def lister_matieres(chemin=None) -> list[dict]:
    """Matières disponibles, avec leur nombre de cartes par niveau."""
    manifestes = {m["matiere"]: m for _, m in paquets_de_contenu()}
    with connexion(chemin) as conn:
        lignes = conn.execute(
            "SELECT matiere, niveau, COUNT(*) AS total FROM cards "
            "GROUP BY matiere, niveau ORDER BY matiere, niveau"
        ).fetchall()

    par_matiere: dict[str, dict] = {}
    for ligne in lignes:
        info = par_matiere.setdefault(ligne["matiere"], {
            "matiere": ligne["matiere"],
            "nom": manifestes.get(ligne["matiere"], {}).get(
                "nom", ligne["matiere"]),
            "description": manifestes.get(ligne["matiere"], {}).get(
                "description", ""),
            "langue_cible": manifestes.get(ligne["matiere"], {}).get(
                "langue_cible", ""),
            "niveaux": [], "total": 0,
        })
        info["niveaux"].append({"niveau": ligne["niveau"], "total": ligne["total"]})
        info["total"] += ligne["total"]
    return list(par_matiere.values())


def init_db(chemin: Path | str | None = None, forcer: bool = False) -> int:
    """
    Crée le schéma et charge les questions. Retourne le nombre de cartes.

    Les questions du JSON font autorité : à chaque appel avec `forcer`,
    la table est reconstruite. Sans `forcer`, on ne recharge que si vide.
    """
    chemin = Path(chemin or CHEMIN_BASE)
    cartes = lire_fichiers_questions()

    with connexion(chemin) as conn:
        # Une base héritée d'une version précédente peut porter d'autres
        # colonnes (`tags`, `erreurs_frequentes`…) ou en manquer (`matiere`,
        # `langue`). Ce contrôle vient AVANT la création du schéma, et c'est
        # tout l'enjeu : `CREATE TABLE IF NOT EXISTS` laisse la vieille table
        # en place sans rien dire, puis `CREATE INDEX ... ON cards(matiere)`
        # échoue sur une base d'avant la refonte multi-matières. Placée après,
        # cette réparation n'était jamais atteinte.
        presentes = {r[1] for r in conn.execute("PRAGMA table_info(cards)")}
        if presentes and set(COLONNES) - presentes:
            conn.executescript("DROP TABLE IF EXISTS cards;")
            forcer = True

        conn.executescript(SCHEMA)

        deja = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
        if deja and not forcer:
            return deja

        conn.execute("DELETE FROM cards")
        conn.executemany(
            """INSERT INTO cards
               (matiere, langue, niveau, titre, question, reponse, explication,
                exemple_code, sortie_attendue, erreur_frequente, indice,
                mots_cles, difficulte, prerequis, categorie, type,
                reponses_acceptees, qcm)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    c["matiere"], c["langue"],
                    c["niveau"], c["titre"], c["question"], c["reponse"],
                    c["explication"], c["exemple_code"], c["sortie_attendue"],
                    c["erreur_frequente"], c["indice"],
                    json.dumps(c["mots_cles"], ensure_ascii=False),
                    c["difficulte"], c["prerequis"], c["categorie"], c["type"],
                    json.dumps(c["reponses_acceptees"], ensure_ascii=False),
                    json.dumps(c.get("qcm") or {}, ensure_ascii=False),
                )
                for c in cartes
            ],
        )
        return len(cartes)


# ---------------------------------------------------------------------------
# Accès aux cartes
# ---------------------------------------------------------------------------

def lister_cartes(niveau: int | None = None, melanger: bool = False,
                  matiere: str | None = None, chemin=None) -> list[dict]:
    conditions, parametres = [], []
    if niveau is not None:
        conditions.append("niveau = ?")
        parametres.append(niveau)
    if matiere:
        conditions.append("matiere = ?")
        parametres.append(matiere)

    ou = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    ordre = "RANDOM()" if (melanger and niveau is not None) else "matiere, niveau, id"

    with connexion(chemin) as conn:
        lignes = conn.execute(
            f"SELECT * FROM cards{ou} ORDER BY {ordre}", parametres
        ).fetchall()
    return [dict(l) for l in lignes]


def lire_carte(card_id: int, chemin=None) -> sqlite3.Row | None:
    with connexion(chemin) as conn:
        return conn.execute(
            "SELECT * FROM cards WHERE id = ?", (card_id,)
        ).fetchone()


def compter_par_niveau(chemin=None) -> list[dict]:
    with connexion(chemin) as conn:
        lignes = conn.execute(
            "SELECT niveau, COUNT(*) AS total FROM cards "
            "GROUP BY niveau ORDER BY niveau"
        ).fetchall()
    return [dict(l) for l in lignes]


# ---------------------------------------------------------------------------
# Contrôle d'intégrité
# ---------------------------------------------------------------------------

#: Un QCM comporte toujours quatre options. Trois distracteurs, c'est le
#: standard : moins, le hasard paie trop ; plus, l'apprenant lit en diagonale.
OPTIONS_QCM = 4


def lire_qcm(carte) -> dict:
    """
    Le QCM d'une carte, ou `{}` si elle n'en a pas.

    Le champ est FACULTATIF : les cartes écrites avant le 28 août 2026 n'en
    ont pas, et elles restent valides. Une carte sans QCM n'affiche pas de
    rattrapage, c'est tout.
    """
    try:
        brut = carte["qcm"]
    except (KeyError, IndexError, TypeError):
        return {}
    if not brut:
        return {}
    if isinstance(brut, dict):
        return brut
    try:
        valeur = json.loads(str(brut))
    except ValueError:
        return {}
    return valeur if isinstance(valeur, dict) else {}


def defauts_du_qcm(qcm: dict) -> list[str]:
    """
    Ce qui cloche dans un QCM, en français. Liste vide = QCM valide.

    Déterministe et sans LLM : un QCM mal formé doit être refusé au
    chargement, pas découvert par un apprenant.
    """
    if not qcm:
        return []
    problemes = []
    options = qcm.get("options")
    if not isinstance(options, list) or len(options) != OPTIONS_QCM:
        return [f"le QCM doit porter exactement {OPTIONS_QCM} options"]
    if any(not str(o).strip() for o in options):
        problemes.append("une option est vide")
    normalisees = [str(o).strip().lower() for o in options]
    if len(set(normalisees)) != len(normalisees):
        problemes.append("deux options sont identiques")

    index = qcm.get("reponse")
    if not isinstance(index, int) or isinstance(index, bool) \
            or not 0 <= index < OPTIONS_QCM:
        problemes.append("« reponse » doit être l'index entier de la bonne "
                         f"option, entre 0 et {OPTIONS_QCM - 1}")
        return problemes

    pourquoi = qcm.get("pourquoi_faux") or {}
    if not isinstance(pourquoi, dict):
        problemes.append("« pourquoi_faux » doit être un objet")
    else:
        manquants = [str(i) for i in range(OPTIONS_QCM)
                     if i != index and not str(pourquoi.get(str(i), "")).strip()]
        if manquants:
            problemes.append("motif de rejet manquant pour les options "
                             + ", ".join(manquants))

    # Le biais le plus répandu des QCM écrits par un modèle : la bonne réponse
    # est la plus détaillée. Un apprenant l'apprend en trois cartes et ne lit
    # plus la question.
    longueurs = [len(str(o)) for o in options]
    if longueurs[index] == max(longueurs) and \
            longueurs[index] > 1.4 * (sum(longueurs) - longueurs[index]) / 3:
        problemes.append("la bonne option est nettement la plus longue : "
                         "elle se devine sans lire la question")

    # Les fourre-tout se disent de trop de façons pour être listés un par un
    # (« aucune de ces réponses », « aucune des propositions », « aucune des
    # réponses ci-dessus »…). On cherche donc le quantificateur ET l'objet.
    for i, texte in enumerate(normalisees):
        quantificateur = any(mot in texte for mot in
                             ("toutes", "aucune", "aucun "))
        objet = any(mot in texte for mot in
                    ("répons", "reponse", "proposition", "ci-dessus",
                     "ci dessus", "précédent", "precedent"))
        combinaison = texte.strip() in ("a et b", "b et c", "a et c",
                                        "a, b et c")
        if (quantificateur and objet) or combinaison:
            problemes.append(f"l'option {i} est un fourre-tout "
                             "(« toutes les réponses », « aucune »)")
    return problemes


def controler_donnees(chemin=None) -> list[str]:
    """
    Vérifie que chaque carte est corrigeable.

    Détecte exactement les pannes suspectées dans l'ancienne base :
    `reponses_acceptees` vide, JSON invalide, type inconnu, ou carte dont
    la réponse canonique elle-même serait refusée par le validateur.
    """
    problemes = []
    for carte in lister_cartes(chemin=chemin):
        etiquette = f"#{carte['id']} « {carte['titre']} »"

        if (carte["type"] or "").strip().lower() not in TYPES_VALIDES:
            problemes.append(f"{etiquette} : type inconnu « {carte['type']} »")

        brut = str(carte["reponses_acceptees"] or "").strip()
        if brut and brut != "[]":
            try:
                json.loads(brut)
            except ValueError:
                problemes.append(f"{etiquette} : reponses_acceptees JSON invalide")

        if not reponses_de_la_carte(carte):
            problemes.append(f"{etiquette} : aucune réponse acceptée")

        brut_qcm = str(carte["qcm"] or "").strip()
        if brut_qcm and brut_qcm not in ("{}", "null"):
            try:
                json.loads(brut_qcm)
            except ValueError:
                problemes.append(f"{etiquette} : qcm JSON invalide")
        for defaut in defauts_du_qcm(lire_qcm(carte)):
            problemes.append(f"{etiquette} : QCM — {defaut}")

        # Le test qui compte : la bonne réponse doit être reconnue.
        for attendue in reponses_de_la_carte(carte):
            resultat = valider_reponse(attendue, carte)
            if not resultat["correct"]:
                problemes.append(
                    f"{etiquette} : la réponse acceptée « {attendue} » "
                    f"est refusée par le validateur ({resultat['raison']})"
                )
    return problemes


if __name__ == "__main__":
    total = init_db(forcer=True)
    print(f"Base initialisée : {total} cartes.")
    soucis = controler_donnees()
    if soucis:
        print(f"\n{len(soucis)} problème(s) détecté(s) :")
        for s in soucis:
            print("  -", s)
    else:
        print("Contrôle d'intégrité : aucune anomalie.")

# Anglais informatique et multilingue : contexte, critique, proposition

*18 août 2026 — trois itérations, après lecture des seize prompts de
`projets_applis`.*

---

## Ce que j'ai trouvé dans tes prompts

**Il n'y a pas quinze applis. Il y en a seize, et la seizième est déjà une
appli de langues.**

`prompts apprentissage agent.odt` contient une spécification complète pour
apprendre **le vocabulaire espagnol** : 150 mots en 6 thèmes, moteur SM-2
détaillé au centième près, trois formats de question selon la maturité de la
carte, règles de tirage des distracteurs, tolérance orthographique d'une
lettre. C'est de loin ta spécification la plus aboutie — nettement plus que
celle de Python.

Ta question sur le multilingue n'est donc pas prospective : **tu l'avais déjà
écrite, sans faire le lien avec le reste.**

### Les seize domaines, classés par durée de vie

C'est le classement qui devrait décider de l'ordre, et il n'est pas celui de
l'enthousiasme :

| Rang | Domaines | Stabilité du contenu | Correction |
|---|---|---|---|
| **1** | Python, SQL, Linux, **anglais informatique**, espagnol | stables sur 10 ans | objective |
| **2** | pandas, méthodologie, méthodologie info., wiki, **RAG (concepts)** | stables sur 5 ans | mixte |
| **3** | IA, ML, prompt engineering, RAG outillé (niveaux 6–8) | concepts stables, exemples périssables | difficile |
| **4** | LangChain/LangGraph, n8n, agentique, évaluation IA | **périment en 6–12 mois** | difficile |

**Le RAG conceptuel (niveaux 1 à 5) a été remonté au rang 2** : le découpage,
les embeddings et l'ancrage sur les sources ne périment pas — les
bibliothèques qui les implémentent, si. C'est aussi la matière où tes propres
sources écrites sont les plus fournies. Détail du raisonnement dans
`FEUILLE_DE_ROUTE.md`.

Le rang 4 représente quatre de tes seize projets. Écrire 210 cartes sur
LangChain aujourd'hui, c'est signer pour les réécrire l'an prochain — et un
formateur qui enseigne à partir de contenu périmé perd sa crédibilité
immédiatement. **Ce n'est pas une raison de ne jamais les faire, c'en est une
de ne pas commencer par là.**

Le rang 1 a la propriété inverse : `SELECT` et `for` s'écriront pareil dans
dix ans.

---

## Itération 1 — L'anglais informatique n'est pas la seizième matière

C'est le point que j'avais manqué la dernière fois.

Regarde ce que les quinze autres ont en commun : `NameError: name 'x' is not
defined`, `SELECT … WHERE … GROUP BY`, `permission denied`, `deprecated since
version 3.9`, `raise`, `fetch`, `handle`, `retrieve`. **Toutes tes matières
s'enseignent en français mais se pratiquent en anglais.**

L'anglais informatique n'est pas le frère des quinze autres. C'en est le
**substrat**. Et cela a trois conséquences concrètes.

**Son contenu se déduit des autres matières.** `NameError: name 'x' is not
defined` est simultanément une carte Python et une carte d'anglais. Aucune
autre paire de matières de ta liste ne compose ainsi. C'est la seule qui
devient *moins chère* à mesure que les autres grossissent.

**Elle résout un vrai blocage, pas un blocage supposé.** Pour un débutant
francophone, l'obstacle numéro un n'est pas la syntaxe — c'est de rester
bloqué devant un message d'erreur qu'il ne lit pas. Ce n'est pas un cours de
langue, c'est **une compétence de débogage**. Un formateur qui annonce « à la
fin, vous saurez lire vos messages d'erreur » vend quelque chose de très
concret.

**Les faux amis sont un contenu à haute valeur et à coût nul.** `library`
n'est pas *librairie*, `actually` n'est pas *actuellement*, `eventually` n'est
pas *éventuellement*, `to support` n'est pas *supporter*, `digital` n'est pas
*digital*. Ce sont exactement les mots qui induisent un développeur
francophone en erreur, et ils ne périment jamais.

**Ma réserve honnête :** comme produit autonome vendu seul, « l'anglais
informatique » est un marché étroit. Comme **module inclus dans une formation
Python ou SQL**, c'est un différenciateur réel. Ne le construis pas comme une
appli — construis-le comme la matière qui rend les autres utilisables.

---

## Itération 2 — « La plus simple » : vrai, mais sous condition

Oui, c'est la plus simple. À une condition de périmètre qu'il faut poser
maintenant, parce qu'elle décide de tout.

Une matière linguistique se découpe en trois compétences aux coûts très
inégaux :

| Compétence | Exemple | Correction | Coût |
|---|---|---|---|
| **Réceptive** | que signifie `deprecated` ? | fermée, objective | **nul** — le moteur actuel suffit |
| **Productive bornée** | comment dit-on « boucle » ? | un mot, tolérance orthographique | faible |
| **Productive libre** | rédige un message de commit | texte libre | le puits sans fond |
| **Audio** | écoute, prononciation | ni synthèse ni reconnaissance | hors périmètre |

**Cantonnée aux deux premières lignes, l'anglais informatique est la matière
la moins chère de tes seize.** Étendue aux deux dernières, elle devient la
plus chère. Ta spécification espagnole a d'ailleurs déjà tranché correctement
sans le dire : QCM pour les cartes neuves, production pour les cartes en
cours, sens inverse pour les cartes mûres. Le format suit la maturité, et
l'espace des réponses reste toujours fermé.

### Une correction que je dois à ma propre affirmation

J'ai écrit la dernière fois que l'anglais ne demanderait **aucune ligne de
code**. C'est vrai pour une carte du type « Comment dit-on *boucle* en
anglais ? » — elle s'écrit aujourd'hui, en `type: mot_cle`, sans rien
toucher.

Ce n'est **pas** vrai pour ce que ta spécification espagnole décrit :

- le **format QCM** avec distracteurs tirés du même thème et de la même
  nature grammaticale n'existe pas dans le moteur ;
- la **tolérance d'une seule lettre** avec affichage de l'orthographe exacte
  n'existe pas non plus.

Le test de décision reste valable — 30 cartes d'anglais sans toucher au code —
mais le moteur complet de langues demande deux ajouts. Autant le savoir avant
de compter les heures.

---

## Itération 3 — Multilingue : le moteur est verrouillé en français à un endroit

« Pourquoi pas n'importe quelle langue » recouvre trois questions dont les
coûts n'ont rien à voir.

**(a) La langue de l'interface.** Les libellés sont écrits en dur dans
`index.html` et `script.js`. Les extraire est un travail modeste et
parfaitement reportable : tes apprenants sont francophones.

**(b) La langue d'enseignement.** Apprendre l'anglais *en français*, *en
espagnol*, ou apprendre le français informatique *en anglais*. **C'est de la
donnée, pas du code.** Un dossier de contenu par paire. Coût nul.

**(c) La langue cible.** Anglais, espagnol, allemand. Donnée également.

**Mais il existe un endroit — un seul — où le moteur est verrouillé en
français, et c'est celui qui compte.** Dans `database.py` :

```python
MOTS_VIDES = {"le", "la", "les", "est", "de", "du", "et", "mot", "cle", …}
```

Cette liste de mots vides français est ce qui permet d'accepter « Le mot-clé
est while. » pour « while ». Appliquée à de l'espagnol ou de l'allemand, elle
ne retire rien et la tolérance s'effondre. S'ajoutent la suppression des
accents — correcte en écriture latine, dénuée de sens en cyrillique ou en
japonais — et le prompt du correcteur LLM, qui annonce littéralement « une
formation Python en français ».

**Sortir la langue du code vers le paquet de contenu coûte une heure
aujourd'hui. Avec cinq matières et trois langues en place, c'est une refonte
transverse.**

### Et une différence de fond que le mot « multilingue » masque

Une carte de langue ne se corrige pas comme une carte de Python.

En Python, « les clés » ≈ « les clefs » : la formulation n'est pas la
compétence évaluée, donc la tolérance est une qualité. En vocabulaire,
`loop` ≠ `loops` et `receive` ≠ `recieve` : **l'orthographe EST la
compétence**. Y appliquer mon validateur tolérant reviendrait à valider des
fautes.

Ta spécification espagnole avait déjà la bonne réponse : *« une seule lettre
d'écart est acceptée, mais l'écran affiche l'orthographe exacte avec la lettre
manquante mise en évidence »*. Tolérant sur la frappe, strict sur le mot, et
pédagogique dans les deux cas.

**Le vrai enjeu du multilingue n'est donc pas la traduction. C'est que les
cartes de langue exigent un mode de correction distinct.**

---

## Proposition

### Le paquet de contenu déclare sa langue

```
contenus/
  python/
    manifeste.json      { "langue_enseignement": "fr", "mots_vides": "fr" }
    niveau_1.json
  anglais_info/
    manifeste.json      { "langue_enseignement": "fr", "langue_cible": "en",
                          "mode_defaut": "vocabulaire" }
    niveau_1.json
  espagnol/
    manifeste.json      { "langue_enseignement": "fr", "langue_cible": "es",
                          "mode_defaut": "vocabulaire" }
    niveau_1.json
```

`mots_vides` et la langue du prompt LLM sortent du code. Ajouter l'allemand
devient un dossier, jamais un correctif.

### Un quatrième type de carte

Aux trois types existants — `mot_cle`, `code`, `texte` — s'ajoute
`vocabulaire` :

- distance d'édition ≤ 1 acceptée, mais l'orthographe exacte est affichée
  avec l'écart mis en évidence ;
- accents et casse ignorés à la saisie, montrés à la correction ;
- pas de mots vides, pas de recouvrement sémantique : le mot est le mot.

Il sert **à l'anglais et à l'espagnol que tu as déjà spécifié**. Écrit une
fois, utilisé deux fois — c'est le test qu'il s'agit bien d'un moteur.

### Les 30 cartes du test de décision

Pas du vocabulaire général : ce qui débloque réellement un débutant
francophone.

| Thème | Exemples | Cartes |
|---|---|---|
| **Messages d'erreur** | `is not defined`, `out of range`, `unexpected indent`, `permission denied` | 10 |
| **Faux amis** | library ≠ librairie, actually ≠ actuellement, eventually, to support, digital | 8 |
| **Verbes de la documentation** | raise, fetch, retrieve, parse, handle, wrap, override, deprecate | 7 |
| **Structures de doc** | `unless`, `provided that`, `whether`, `as of version` | 5 |

### Séquence

1. **Sortir la langue vers le manifeste** — 1 h. À faire avant tout le reste,
   pas après.
2. **Ajouter le type `vocabulaire`** — 2 h. Sert immédiatement à deux
   matières.
3. **Écrire les 30 cartes d'anglais informatique** — 1 journée.
4. **Compter les fichiers `.py` modifiés à l'étape 3.** Zéro : la thèse du
   moteur est prouvée, les seize matières deviennent un actif. Non nul : le
   moteur n'en est pas un, et il faut le corriger avant d'écrire la moindre
   carte supplémentaire.

### Ce que je continue de te déconseiller

- **Commencer par le rang 4** (LangChain, n8n, agentique, évaluation IA).
  Contenu qui périme en six mois, correction difficile, et crédibilité en jeu.
  Le RAG conceptuel n'en fait plus partie, mais il vient après les trois
  matières déjà commencées, pas avant.
- **L'audio.** Synthèse et reconnaissance vocales sont un projet à part
  entière, sans rapport avec ce moteur.
- **Traduire l'interface** avant d'avoir un apprenant non francophone.

---

## En un paragraphe

L'anglais informatique n'est pas ta seizième matière : c'est le substrat des
quinze autres, son contenu se déduit d'elles, et il répond au blocage numéro
un du débutant francophone — lire ses messages d'erreur. C'est bien la matière
la plus simple, à condition de la cantonner au réceptif et au productif borné.
Le multilingue, lui, n'est pas un problème de traduction mais de correction :
une carte de langue exige un mode strict là où une carte de Python exige un
mode tolérant, et le moteur est aujourd'hui verrouillé en français à un
endroit précis — la liste des mots vides. Sortir cette langue vers le paquet
de contenu coûte une heure maintenant et une refonte plus tard. Et tu as déjà
écrit, sans le voir, la spécification d'un moteur de langues plus abouti que
celui de Python : c'est elle qu'il faut réutiliser, pas réécrire.

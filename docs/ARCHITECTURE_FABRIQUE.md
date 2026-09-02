# Fabrique et déploiement — trois itérations, puis une proposition

*19 août 2026. Répond à trois exigences posées ensemble : que les applis
tournent **en local sur un ordinateur et sur un téléphone via API**, que les
questions soient **produites automatiquement**, et qu'**un autre LLM serve de
juge**. Rien ici n'est appliqué : c'est une proposition.*

---

## Ce que j'ai compté avant d'écrire

Pas repris de la passation — recompté sur le disque, parce qu'un artefact qui
rend compte de son propre travail n'est pas une source sur son propre travail.

| Vérifié | Valeur |
|---|---|
| Cartes réellement présentes | **129** — python 54, anglais_info 30, rag 30, espagnol 15 |
| Niveaux existants | **`niveau_1` uniquement**, pour les quatre paquets |
| Tests | **121** (fabrique 29, validation 22, llm 22, multilingue 20, qualité 18, api 10) |
| Vérificateurs dans `fabrique/verificateurs.py` | **7** |
| Backend LLM | `LLM_BACKEND=off` |
| Cartes jamais sorties de la fabrique | **129 sur 129** |

Deux corrections à apporter aux documents de pilotage :

**1. `FEUILLE_DE_ROUTE.md` est périmé sur le point qui commande la suite.** Sa
table annonce « à faire » pour l'exécution du code, le détecteur d'ambiguïté,
les doublons et le calibrage. Les quatre existent : `verifier_execution`,
`verifier_ambiguite`, `verifier_doublons`, `verifier_calibrage`, écrits le
18 août à 21 h 53, après la rédaction de la feuille. **L'étape A est
terminée** et la feuille dit le contraire.

**2. Le générateur n'a jamais produit une seule carte du dépôt.** Les 129
cartes viennent de deux chemins manuels : rédaction directe, ou copier-coller
du prompt `PROMPT_RAG_NIVEAU_1.md` dans une IA tierce. Le paquet fabriqué par
le second chemin est **le seul défectueux des quatre** (27 titres sur 30
donnaient la réponse). Ce n'est pas une information sur cette IA : c'est une
information sur le chemin. **La chaîne outillée est complète, débranchée, et
non éprouvée.**

---

## Itération 1 — le déploiement décide de l'architecture, pas l'inverse

« En local sur des ordis **et** sur des téléphones avec des API » n'est pas une
option de configuration : c'est ce qui dit où le moteur a le droit de tourner.
Trois postures, et il faut nommer celle qu'on refuse.

| | **A — poste local** | **B — serveur + navigateur mobile** | **C — téléphone hors ligne** |
|---|---|---|---|
| Où tourne le moteur | sur la machine de l'apprenant | sur un VPS | nulle part |
| Correction | déterministe + Ollama/LM Studio en recours | déterministe + API distante en recours | il faudrait réécrire `valider_reponse` en JavaScript |
| Coût marginal | 0 | hébergement + jetons | 0 |
| Données | chez l'apprenant | sur le VPS | sur le téléphone |
| Bac à sable d'exécution | **c'est son ordinateur** — le risque disparaît | serveur exposé, projet en soi | — |
| Verdict | ✅ | ✅ | ⛔ **à refuser par son nom** |

**La posture C est le piège, et il faut l'écrire pour ne pas y revenir.** Un
téléphone qui corrige hors ligne suppose une seconde implémentation du
correcteur en JavaScript. Deux moteurs qui divergeront au premier élargissement
de filet, et la fin de la règle debout depuis le début : *ne jamais
réintroduire de logique de correction dans `script.js`*. **Le téléphone est un
client, jamais un hôte.**

Ce que le téléphone mérite en revanche, et qui ne coûte presque rien : une
**coquille PWA** — `manifest.json`, un service worker qui met en cache le
front et les cartes du niveau en cours, les réponses mises en file et postées
au retour du réseau. Une centaine de lignes, zéro moteur dupliqué, et c'est la
version honnête de « ça marche sur téléphone ». `index.html` porte déjà
`<meta name="viewport">` ; le socle est là.

### La conséquence que personne n'a encore tirée

En posture B, un seul serveur : les verdicts du LLM s'accumulent dans le cache
pour tous les apprenants. En posture A, **chaque apprenant démarre avec un
cache vide** — donc chaque formulation inattendue coûte 5 à 20 secondes
d'attente sur son processeur, sur la carte où il était en train d'apprendre.

Donc : **la fabrique ne livre pas des cartes, elle livre des cartes *et* leur
surface d'acceptation pré-calculée.** Un `cache_amorce.json` par matière,
produit hors ligne en même temps que le paquet, chargé à l'installation. C'est
la même donnée que le cache actuel `(carte, réponse normalisée, modèle) →
verdict`, simplement calculée d'avance au lieu d'être apprise sur le dos du
premier utilisateur.

Cela change la définition du livrable, et donc tout le reste de ce document.

---

## Itération 2 — la fabrique à trois rôles, et aucun modèle ne se juge

L'exigence « un autre LLM pour juge » est juste, et elle est plus forte que ce
qu'elle a l'air de demander. Aujourd'hui `_repondre_a_l_aveugle()` appelle
`llm.Config()` — **le même backend et le même modèle que le correcteur**.
Rédacteur, juge et correcteur sont un seul modèle. Le détecteur d'ambiguïté
demande donc à un modèle de trouver ambigu ce qu'un modèle identique a trouvé
clair. C'est un contrôle qui se ressemble.

### Trois rôles, trois règles

| Rôle | Qui | Voit la réponse ? | Décide ? |
|---|---|---|---|
| **Rédacteur** | modèle fort, hors ligne, par lots | il l'écrit | non — il propose |
| **Juge** | **autre modèle, autre famille**, local | **jamais** | non — il signale |
| **Arbitre** | code déterministe | oui | **oui, et il ne discute pas** |

- **R1 — aucun modèle ne valide sa propre production.**
- **R2 — le juge ne voit jamais la réponse attendue.**
- **R3 — un signalement d'un modèle n'est pas un verdict**, c'est une entrée
  dans la file de relecture. Seul le déterministe rejette tout seul.

### Pourquoi le juge local peut être plus faible, et pourquoi c'est un atout

L'intuition dit qu'il faut le meilleur modèle pour juger. C'est faux ici,
parce qu'on ne lui demande pas d'avoir raison : on lui demande d'être **un
autre esprit** et d'être **reproductible ou pas**. Si un petit modèle, sans
voir la réponse, converge cinq fois sur la bonne, la carte est non ambiguë *a
fortiori*. C'est la divergence qui est le signal, pas la justesse.

Un seul piège à écarter : divergence ≠ difficulté. Une carte de niveau 6 fera
diverger un 8B sans être ambiguë. D'où **deux étages** : le juge local produit
le signal sur toutes les cartes ; seules les cartes signalées montent à un
modèle fort pour arbitrage. Le coût reste local.

### L'épreuve qui manque vraiment : le filet à deux faces

`verifier_ambiguite` sait déjà lire deux signaux — divergence, et convergence
avec refus (« filet trop étroit »). C'est bien la moitié du problème. **L'autre
moitié n'existe pas, et c'est celle qui détruit l'instrument.**

Le 19 août, deux refus ont été examinés et maintenus, trois filets élargis, et
la règle écrite ce jour-là est exactement la bonne : *on élargit quand l'énoncé
autorise la réponse, jamais parce que la réponse est du bon voisinage.* Cette
règle est aujourd'hui dans la tête de l'auteur. À 129 cartes, ça tient. À 360,
non.

Épreuve proposée, par carte, entièrement automatique :

1. le juge produit **10 reformulations légitimes** de la bonne réponse —
   telles qu'un apprenant les écrirait, sans voir `reponses_acceptees` ;
2. le juge produit **5 réponses quasi-justes mais fausses** — du bon
   voisinage, et pourtant à refuser ;
3. le correcteur déterministe passe sur les 15 ;
4. **contrat : 10 acceptées, 5 refusées.** Un faux refus est un signalement
   « filet trop étroit ». Un faux accord est un signalement « filet trop
   large ».

C'est le point où le reste de la chaîne se joue, parce qu'un filet qui accepte
tout est aussi ruineux qu'un filet qui refuse tout — et beaucoup plus difficile
à voir. Une suite de contrôles qui ne mesure que dans un sens finit toujours
par être élargie jusqu'à ne plus rien mesurer.

### Budget, chiffré

Par carte : 5 tirages à l'aveugle + 1 appel de reformulation = **6 inférences
locales**.

| Lot | Cartes | Inférences | Durée à 4 s |
|---|---|---|---|
| Python 2 à 7 | 180 | 1 080 | ~1 h 15 |
| Produit minimum (Python + RAG + anglais) | 360 | 2 160 | ~2 h 30 |
| Vague 1 complète | 1 350 | 8 100 | ~9 h |

Une nuit, zéro euro, et c'est exactement le régime déjà écrit dans
`STRATEGIE.md` : *la génération de contenu ne tourne jamais en ligne*.

---

## Itération 3 — les trois manques qui décident réellement de l'issue

### a) L'ancrage n'existe pas

`generer()` **exige** `--source`, tronque à 12 000 caractères, et la consigne
n°9 dit « n'invente rien qui ne figure pas dans la source ». Il n'y a **aucun
dossier `sources/`** dans le dépôt. Aujourd'hui, cette règle est décorative :
la source, c'est ce qu'on aura sous la main au moment de lancer la commande.

À constituer une fois, et c'est un travail de bibliothécaire, pas de
développeur :

```
sources/
  python/niveau_2.md        extraits de la doc officielle française
  python/niveau_3.md         (docs.python.org/fr/3), ~12 000 car. par niveau
  rag/*.md                   extraits de METHODE_montage_RAG_client,
                             rag-vs-wiki/protocole.md, demonstrateur_*
  anglais_info/*.md          messages d'erreur réels relevés dans tes dépôts
```

Pour le RAG, la source est **déjà écrite et elle est à toi** : c'est le seul
paquet dont le contenu ne peut pas être obtenu par quelqu'un d'autre avec le
même prompt. C'est aussi le seul qui fasse la publicité de la prestation.

### b) La boucle de retour est ouverte

Le cache enregistre `(carte, réponse, verdict, justification)`. Chaque fois que
le LLM tranche « correct » sur une formulation absente de
`reponses_acceptees`, c'est **une proposition d'élargissement de filet gagnée
sur un apprenant réel** — la meilleure qui soit, parce qu'elle n'est pas
inventée. Aujourd'hui elle dort dans le cache et personne ne la lit.

Une commande `fabrique moissonner` qui remonte ces cas en file de relecture
fait progresser les filets avec l'usage, sans rien changer au moteur. C'est
aussi, accessoirement, le premier chiffre qu'un formateur regarderait : *sur
quelles cartes mes stagiaires ont-ils raison alors que l'appli dit non ?*

### c) Le contrat de livraison n'est pas écrit

« La fabrique tourne » ne veut rien dire. **Un niveau est livrable quand :**

- 0 signalement de gravité haute ;
- ≤ 2 de gravité moyenne, motivées par écrit ;
- 100 % des `exemple_code` exécutés et conformes à `sortie_attendue` ;
- 30/30 cartes passent l'épreuve du filet à deux faces ;
- le paquet a été **joué en entier une fois**, à la main, sur téléphone et sur
  ordinateur.

Et ce contrat se vérifie **en une commande qui sort en code 1 si elle échoue**.
Sinon c'est un document, et un document ne bloque rien.

Le dernier point n'est pas décoratif : les deux défauts du 19 août — la fuite
par le titre et le bug d'ordre dans `init_db` — étaient invisibles à
116 tests verts *et* à une passe de vérification complète. Ils sont sortis en
dix minutes d'usage. **Aucune fabrique ne remplace le fait de jouer le paquet.**
Elle réduit ce qu'il reste à trouver ainsi, elle ne l'annule pas.

---

## Les priorités entre matières, révisées

Deux tables coexistent et ne donnent pas le même ordre : les **rangs**
(`ordre_applis_constructibles`, critère = durée de vie) et les **vagues**
(`FEUILLE_DE_ROUTE`, critère = coût de développement). Il en manque une
troisième, qui tranche : **le coût de vérification.**

| Matière | Rang | Vague | Coût de vérif. | Position proposée |
|---|:--:|:--:|---|---|
| **Python 2–7** (180) | 1 | 1 | **le plus bas** — type `code`, comparaison de chaîne normalisée, `exemple_code` exécutable : l'arbitre déterministe tranche presque tout, le juge sert peu | **1er, sans discussion** |
| **RAG 1–5** (120 de plus) | 2 | 1 | élevé — type `texte`, tout repose sur les filets et le juge | **2e** — sources internes, valeur commerciale, et c'est le cas difficile : le vrai test de la fabrique |
| **Anglais info 2–3** (60) | 1 | 1 | bas | 3e |
| **Méthodo, méthodo info, wiki** (550) | 2 | 1 | élevé | 4e, et seulement si un utilisateur les demande |
| **SQL** (400) | 1 | 2 | **nul** — on exécute, on compare les résultats. Correction totalement objective | **remonte si la posture A est retenue** (voir ci-dessous) |
| **Linux, pandas** (550) | 1–2 | 2 | nul à bas | après SQL |
| **IA, ML, prompt eng., RAG 6–8** (690) | 3 | 3 | élevé + péremption | dernier, avec date obligatoire dans chaque explication |
| **LangChain, n8n, agentique, éval IA** | 4 | — | — | **non** |

Deux inflexions par rapport à la feuille de route :

**SQL remonte, à cause de la posture.** « Le bac à sable avant un client payant »
était un argument de **sécurité serveur** : exécuter du code arbitraire sur un
VPS exposé. En posture A, l'apprenant exécute du SQL **sur son propre
ordinateur** — le risque n'existe plus. Et SQLite en mémoire est le bac à sable
le plus simple des trois. À creuser aussi : `sql.js` (SQLite compilé en
WebAssembly) exécute la requête **dans le navigateur**, y compris sur
téléphone, sans rien exposer côté serveur. Ça vaut une demi-journée d'épreuve
avant de trancher — pas une décision aujourd'hui.

**L'espagnol s'arrête à 15, et je le dis franchement.** Passer à 150 demande
135 cartes de vocabulaire : aucune source interne réemployée, aucune valeur
commerciale, et des milliers de paquets Anki gratuits font déjà mieux. Ces
15 cartes ont servi — elles ont prouvé qu'une langue non prévue passe sans
toucher au moteur. C'est un test réussi, pas un produit à finir.

**Et la cible de 1 350 cartes est une cible d'inventaire.** Le produit minimum
défendable : **Python 210 + RAG 150 = 360 cartes**, deux matières complètes
dont une qui fait la publicité de la prestation de montage RAG. Le reste après
un utilisateur.

---

## Séquence proposée

Chaque étape a un critère de réussite vérifiable, et rien ne commence tant que
la précédente n'est pas verte.

| | Étape | Critère de réussite | Où |
|---|---|---|---|
| **0** | Séparer les modèles : `LLM_MODELE_JUGE` distinct de `LLM_MODELE`, et refus explicite si les deux sont égaux | un test qui échoue quand rédacteur = juge | Mac |
| **1** | Constituer `sources/python/niveau_2..7.md` et `sources/rag/` | six fichiers ≤ 12 000 car., chacun tracé à sa source | **ici** (ce conteneur a le réseau, le pont Cowork ne l'a pas) |
| **2** | 8ᵉ vérificateur — filet à deux faces (10 acceptées / 5 refusées) | tourne sur les 129 cartes existantes et signale les 3 filets déjà élargis le 19/08 | Mac |
| **3** | Commande `fabrique lot --matiere python --niveaux 2-7` : générer → vérifier → ne garder que ce qui passe → file de relecture | une commande, un rapport, code 1 si haute | Mac |
| **4** | **Python niveau 2 de bout en bout** — 30 cartes par la fabrique | contrat de livraison rempli, paquet joué en entier | Mac |
| **5** | `cache_amorce.json` + coquille PWA | le niveau 2 se joue sur téléphone, avion activé, sans écran blanc | Mac |
| **6** | `fabrique moissonner` — le cache nourrit les filets | ≥ 1 élargissement proposé à partir d'un usage réel | Mac |

L'étape 4 est le point de décision réel : **c'est la première fois que le
projet saura si sa fabrique produit des cartes livrables.** Si le niveau 2
sort avec plus de cinq signalements hauts, le problème n'est pas le contenu,
c'est la fabrique — et on s'arrête là plutôt que de lancer les cinq niveaux
suivants.

---

## Ce que je déconseille, et pourquoi

- **Le correcteur en JavaScript pour le hors-ligne téléphone.** Deux moteurs,
  une divergence garantie. La coquille PWA couvre 90 % du besoin réel.
- **Lancer les six niveaux Python d'un coup.** Le niveau 2 d'abord, joué,
  relu. Une fabrique non éprouvée qui produit 180 cartes produit 180 cartes à
  reprendre.
- **Faire juger par le même modèle que le rédacteur.** C'est l'état actuel du
  code, et c'est ce que la nouvelle exigence corrige.
- **Élargir un filet parce qu'un refus était vexant.** La règle du 19/08 est
  bonne ; l'épreuve à deux faces est là pour qu'elle survive au volume.
- **L'espagnol à 150, la méthodologie, le wiki** avant qu'un utilisateur les
  demande. 550 cartes que personne n'a réclamées.
- **Le rang 4** — LangChain, n8n, agentique, évaluation d'applis IA. Inchangé.

---

## En un paragraphe

La chaîne est déjà écrite : générateur ancré, sept vérificateurs, cascade de
correction, cache, journal d'incidents, indices de qualité. Elle est
débranchée (`LLM_BACKEND=off`) et n'a jamais produit une carte du dépôt. Ce
qui manque n'est donc pas de l'outillage, c'est trois choses : **des sources**
sur lesquelles ancrer, **un second modèle** pour que le juge ne soit plus le
rédacteur, et **un contrat de livraison** qui sorte en code 1. La contrainte de
déploiement, elle, ne complique rien — elle simplifie : le téléphone est un
client, jamais un hôte, ce qui protège l'unicité du correcteur et fait remonter
SQL dans l'ordre des matières. Et la cible n'est pas 1 350 cartes : c'est
Python complet et RAG complet, 360 cartes, dont l'une des deux fait la
publicité de ce que tu vends.

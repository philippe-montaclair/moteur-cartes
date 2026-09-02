# Diagnostic sur le code d'origine

Établi le 18 août 2026 en lisant les fichiers réels du projet, pas d'après
une description.

## Ton hypothèse de départ était fausse — et c'est une bonne nouvelle

Tu soupçonnais les données :

> certaines lignes pourraient contenir `[]` ; certaines réponses pourraient
> être stockées avec un JSON incorrect

**Vérification sur `prompt_app.db` :**

| Contrôle | Résultat |
|---|---|
| Cartes de niveau 1 | 50 |
| `reponses_acceptees` vides ou `[]` | **0** |
| `reponses_acceptees` en JSON invalide | **0** |

La base était saine. Inutile d'aller plus loin de ce côté : les trois bugs
étaient dans le code.

---

## Bug n°1 — `isCorrect()` jetait son propre travail

```javascript
function isCorrect(given, expected) {
  const givenText = normalize(given);      // calculé…
  const expectedText = normalize(expected); // …calculé…

  if (!givenText || !expectedText) {
    return false;
  }

  return compact(given) === compact(expected);  // …puis ignoré !
}
```

`givenText` et `expectedText` ne servent qu'à tester si la chaîne est vide.
La comparaison finale repart des arguments **bruts** via `compact()`.

Et `compact()` ne neutralise pas la ponctuation :

```javascript
function normalize(text) {
  return String(text).toLowerCase().normalize('NFD')
    .replace(/[̀-ͯ]/g, '')   // accents : OK
    .replace(/[«»"'`]/g, '')           // guillemets : OK
    .replace(/\s+/g, ' ').trim();      // espaces : OK
    //  ⟵ ni les points, ni les virgules, ni les tirets
}
```

Conséquence directe : **un point final suffisait à invalider une réponse.**

| Saisie | Attendu | Résultat |
|---|---|---|
| `int, float, str et bool.` | `int, float, str et bool` | ✗ refusé |
| `int, float, str et bool` | `int, float, str et bool` | ✓ accepté |

C'est exactement l'intermittence que tu décrivais — « *parfois refusée* ».
Elle dépendait de la ponctuation que l'utilisateur tapait.

---

## Bug n°2 — la bonne réponse affichée était elle-même refusée

Le plus coûteux des trois.

```javascript
if (!acceptedAnswers.length) {
  acceptedAnswers = [card.reponse];   // ⟵ seulement si la liste est VIDE
}
```

`card.reponse` ne servait de secours **que** si `reponses_acceptees` était
vide. Or elle ne l'était jamais (0 cas sur 50). Donc la réponse canonique —
celle que l'application montre à l'apprenant comme étant la bonne — n'était
jamais dans la liste des réponses acceptées.

Sur tes cartes réelles :

| Carte | `reponse` affichée | `reponses_acceptees` | La recopier ? |
|---|---|---|---|
| Calculer un quotient | `/ produit un quotient décimal ; // réalise une division entière.` | `["/ et //", "/ : division décimale ; // : division entière"]` | ✗ **refusée** |
| Compter des répétitions | `print est exécuté 3 fois.` | `["3", "3 fois", "trois fois"]` | ✗ **refusée** |
| Répéter avec while | `Le mot-clé est while.` | `["while"]` | ✗ **refusée** |

Un apprenant qui recopiait mot pour mot la correction qu'on venait de lui
montrer était noté faux. Voilà pourquoi ces trois cartes précises revenaient
dans ta liste de problèmes.

---

## Bug n°3 — deux moteurs de correction qui divergent

`database.py` :

```python
def normaliser_reponse(texte):
    texte = unicodedata.normalize("NFKC", texte)
    texte = texte.strip().lower()
    texte = re.sub(r"\s+", " ", texte)   # espaces CONSERVÉS
    return texte
```

`script.js` : `compact()` **supprime** tous les espaces.

Les deux implémentations ne normalisaient donc même pas de la même façon.
Ajoute que `reponse_acceptee()` en Python n'utilisait pas non plus
`card.reponse` en secours, et le tableau est complet : **tes 9 tests
validaient un code qui ne corrigeait jamais à l'écran.**

C'est ce qui rendait la panne insaisissable. Aucune modification de
`isCorrect` ne pouvait converger, puisque le comportement testé et le
comportement observé venaient de deux sources différentes.

---

## Ce qui a été fait

1. **Une seule correction**, dans `database.valider_reponse()`, exposée par
   `POST /api/check`. `script.js` ne compare plus rien — c'est écrit en tête
   du fichier pour que la logique ne soit pas réintroduite.
2. **La ponctuation est neutralisée**, sauf les symboles qui portent le sens
   (`/`, `//`, `%`, `**`, `==`, `!=`, `#`).
3. **`reponse` est toujours acceptée**, quoi que contienne
   `reponses_acceptees`. Le bug n°2 est structurellement impossible.
4. **`controler_donnees()` rejoue la réponse attendue de chaque carte** à
   travers le validateur. Le bug n°2 aurait été détecté au premier lancement.

---

## Tes 50 questions n'ont pas été perdues

Elles sont exportées dans `data/_questions_originales.json`, converties au
nouveau format. Ce fichier **n'est pas chargé automatiquement** (le
chargeur ne lit que `data/niveau_*.json`), pour éviter les doublons avec les
54 questions fournies.

Pour les utiliser à la place :

```bash
mv data/niveau_1.json data/_questions_fournies.json
mv data/_questions_originales.json data/niveau_1.json
python database.py     # signale toute carte non validable
pytest -q
```

Deux points à relire si tu les réactives :

- **le champ `type`** a été deviné (`code` si la réponse ressemble à une
  instruction, `texte` sinon). Il commandait `question` pour les 50 cartes,
  ce qui n'est pas une valeur reconnue. Vérifie-le carte par carte : c'est
  lui qui règle la sévérité de la correction ;
- **`mots_cles` est vide** pour toutes. L'ancienne colonne `tags` a été
  conservée sous `_tags_origine` mais n'est pas utilisée : des tags de
  recherche ne sont pas des notions obligatoires, les confondre créerait de
  faux positifs. Remplis `mots_cles` sur les questions d'explication, c'est
  ce qui rend la correction robuste aux reformulations.

## Différences de schéma relevées

La base réelle ne portait pas tout à fait les noms annoncés :

| Annoncé | Réel dans `prompt_app.db` | Retenu |
|---|---|---|
| `erreur_frequente` | `erreurs_frequentes` | `erreur_frequente` |
| `mots_cles` | `tags` | `mots_cles` (autre rôle) |

La nouvelle base étant régénérée depuis le JSON, ces écarts n'ont pas de
conséquence — mais ils expliquent pourquoi certaines requêtes écrites de
mémoire échouaient.

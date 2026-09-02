# Source d'ancrage — Python niveau 2 : conditions et boucles

> **Provenance.** Extraits fidèles de la documentation officielle Python en
> français, consultée le **19 août 2026** :
> `docs.python.org/fr/3/tutorial/controlflow.html` (§ 4.1 à 4.6) et
> `docs.python.org/fr/3/library/stdtypes.html` (valeurs booléennes, opérations
> booléennes, comparaisons). Python 3.
>
> **Règle d'usage.** Ce fichier est la *seule* matière autorisée pour rédiger
> les cartes du niveau 2. Toute affirmation d'une carte doit pouvoir être
> retrouvée ici. Ce qui ne s'y trouve pas ne s'invente pas : voir la section
> « Lacunes déclarées » en fin de fichier.

---

## 1. L'instruction `if` / `elif` / `else`

```python
x = int(input("Please enter an integer: "))
if x < 0:
    x = 0
    print('Negative changed to zero')
elif x == 0:
    print('Zero')
elif x == 1:
    print('Single')
else:
    print('More')
```

Il peut y avoir un nombre quelconque de parties `elif`, et la partie `else`
est facultative. Le mot clé `elif` est un raccourci pour *else if*, et permet
de gagner un niveau d'indentation. Une séquence `if` … `elif` … `elif` … est
par ailleurs équivalente aux instructions `switch` ou `case` disponibles dans
d'autres langages.

## 2. Les comparaisons

Il y a huit opérations de comparaison en Python. Elles ont toutes la même
priorité, qui est **supérieure** à celle des opérations booléennes.

| Opération | Signification |
|---|---|
| `<` | strictement inférieur |
| `<=` | inférieur ou égal |
| `>` | strictement supérieur |
| `>=` | supérieur ou égal |
| `==` | égal |
| `!=` | différent |
| `is` | identité d'objet |
| `is not` | contraire de l'identité d'objet |

**Chaînage.** Les comparaisons peuvent être enchaînées arbitrairement : par
exemple, `x < y <= z` est équivalent à `x < y and y <= z`, sauf que `y` n'est
évalué **qu'une seule fois** (mais dans les deux cas `z` n'est pas évalué du
tout quand `x < y` est faux).

Sauf indication contraire, des objets de types différents ne sont jamais
égaux. L'opérateur `==` est toujours défini ; les opérateurs `<`, `<=`, `>` et
`>=` ne le sont que là où ils ont un sens — ils lèvent une `TypeError` quand
l'un des arguments est un nombre complexe, par exemple.

Le comportement de `is` et `is not` ne peut pas être personnalisé ; ils
peuvent être appliqués à deux objets quelconques et **ne lèvent jamais
d'exception**.

## 3. Les opérations booléennes `and`, `or`, `not`

Classées par priorité **ascendante** :

| Opération | Résultat | Note |
|---|---|---|
| `x or y` | si `x` est vrai, alors `x`, sinon `y` | court-circuit |
| `x and y` | si `x` est faux, alors `x`, sinon `y` | court-circuit |
| `not x` | si `x` est faux, alors `True`, sinon `False` | priorité basse |

1. `or` est un opérateur **court-circuit** : il n'évalue le deuxième argument
   que si le premier est faux.
2. `and` est un opérateur **court-circuit** : il n'évalue le deuxième argument
   que si le premier est vrai.
3. `not` a une priorité inférieure à celle des opérateurs non booléens : donc
   `not a == b` est interprété comme `not (a == b)`, et `a == not b` est une
   **erreur de syntaxe**.

Les opérations et fonctions natives dont le résultat est booléen renvoient
toujours `0` ou `False` pour faux et `1` ou `True` pour vrai — **exception
importante : `or` et `and` renvoient toujours l'une de leurs opérandes**, pas
un booléen.

## 4. Les valeurs de vérité (*truthy* et *falsy*)

Tout objet peut être comparé à une valeur booléenne, typiquement dans une
condition `if` ou `while`, ou comme opérande des opérations booléennes.

Par défaut, un objet est considéré comme **vrai**, sauf si sa classe définit
une méthode `__bool__()` qui renvoie `False`, ou une méthode `__len__()` qui
renvoie zéro.

Objets natifs considérés comme **faux** :

- les constantes définies comme fausses : `None` et `False` ;
- zéro de tout type numérique : `0`, `0.0`, `0j`, `Decimal(0)`, `Fraction(0, 1)` ;
- les chaînes et collections vides : `''`, `()`, `[]`, `{}`, `set()`, `range(0)`.

## 5. Les opérations `in` et `not in`

Deux autres opérations, de même priorité syntaxique que les comparaisons :
`in` et `not in`. Elles sont prises en charge par les types **itérables** ou
qui implémentent la méthode `__contains__()`.

## 6. L'instruction `for`

L'instruction `for` de Python est un peu différente de celle du C ou du
Pascal. Au lieu de toujours itérer sur une suite arithmétique de nombres, ou
de laisser définir le pas et la condition de fin, **`for` itère sur les
éléments d'une séquence** (liste, chaîne de caractères…), dans l'ordre où ils
y apparaissent.

```python
words = ['cat', 'window', 'defenestrate']
for w in words:
    print(w, len(w))
```

Sortie :

```
cat 3
window 6
defenestrate 12
```

**Modifier une collection pendant qu'on itère dessus peut s'avérer délicat.**
Il est généralement plus simple de boucler sur une copie, ou de créer une
nouvelle collection :

```python
users = {'Hans': 'active', 'Éléonore': 'inactive', '景太郎': 'active'}

# Stratégie : itérer sur une copie
for user, status in users.copy().items():
    if status == 'inactive':
        del users[user]

# Stratégie : créer une nouvelle collection
active_users = {}
for user, status in users.items():
    if status == 'active':
        active_users[user] = status
```

## 7. La fonction `range()`

Pour itérer sur une suite de nombres, la fonction native `range()` génère des
suites arithmétiques :

```python
for i in range(5):
    print(i)
```

Sortie : `0`, `1`, `2`, `3`, `4`.

**Le dernier élément fourni en paramètre ne fait jamais partie de la suite
générée** : `range(10)` génère 10 valeurs, de 0 à 9. On peut spécifier une
valeur de début et un pas, y compris négatif :

```python
>>> list(range(5, 10))
[5, 6, 7, 8, 9]

>>> list(range(0, 10, 3))
[0, 3, 6, 9]

>>> list(range(-10, -100, -30))
[-10, -40, -70]
```

Pour itérer sur les indices d'une séquence, on peut combiner `range()` et
`len()` :

```python
a = ['Mary', 'had', 'a', 'little', 'lamb']
for i in range(len(a)):
    print(i, a[i])
```

Dans la plupart des cas, il est cependant plus pratique d'utiliser
`enumerate()`.

**Un *range* n'est pas une liste :**

```python
>>> range(10)
range(0, 10)
```

L'objet renvoyé se comporte presque comme une liste, mais ce n'en est pas
une : il génère les éléments au fur et à mesure de l'itération, sans
réellement produire la liste, **économisant ainsi de l'espace**. On appelle
de tels objets des **itérables**. `for` est une construction qui accepte un
itérable ; `sum()` est un exemple de fonction qui en accepte un :

```python
>>> sum(range(4))  # 0 + 1 + 2 + 3
6
```

## 8. Les instructions `break` et `continue`

`break` interrompt la boucle `for` ou `while` **la plus profonde**.

```python
for n in range(2, 10):
    for x in range(2, n):
        if n % x == 0:
            print(f"{n} equals {x} * {n//x}")
            break
```

Sortie :

```
4 equals 2 * 2
6 equals 2 * 3
8 equals 2 * 4
9 equals 3 * 3
```

`continue` fait passer la boucle à son **itération suivante** :

```python
for num in range(2, 10):
    if num % 2 == 0:
        print(f"Found an even number {num}")
        continue
    print(f"Found an odd number {num}")
```

## 9. La clause `else` d'une boucle

Dans une boucle `for` ou `while`, `break` peut être couplé à une clause
`else`. **Si la boucle finit sans exécuter le `break`, alors la clause `else`
s'exécute.**

- Dans une boucle `for`, `else` s'exécute après la dernière itération,
  c'est-à-dire uniquement si la boucle n'a pas été interrompue.
- Dans une boucle `while`, `else` s'exécute lorsque la condition devient
  fausse.
- Dans les deux cas, `else` **n'est pas** exécutée si la boucle a été
  interrompue par un `break`. Un `return` ou une exception ignorent également
  la clause `else`.

```python
for n in range(2, 10):
    for x in range(2, n):
        if n % x == 0:
            print(n, 'equals', x, '*', n//x)
            break
    else:
        # loop fell through without finding a factor
        print(n, 'is a prime number')
```

(Ce code est correct : la clause `else` est rattachée à la boucle `for`, et
**non** à l'instruction `if`.)

La clause `else` d'une boucle est plus proche de celle d'un `try` que de celle
d'un `if` : celle d'un `try` s'exécute quand aucune exception n'est
déclenchée, celle d'une boucle quand aucun `break` n'intervient.

## 10. L'instruction `pass`

`pass` ne fait rien. Elle est utilisée lorsqu'une instruction est
syntaxiquement nécessaire mais qu'aucune action ne doit être effectuée.

```python
while True:
    pass  # Busy-wait for keyboard interrupt (Ctrl+C)
```

```python
class MyEmptyClass:
    pass
```

```python
def initlog(*args):
    pass   # Remember to implement this!
```

---

## Lacunes déclarées — à ne pas combler de mémoire

Les notions suivantes figurent dans la spécification du niveau 2
(`projets_applis/prompt app python.odt`) mais **ne sont pas couvertes par les
deux pages consultées**. Aucune carte ne doit être rédigée dessus tant que la
source correspondante n'a pas été ajoutée à ce fichier :

- **la boucle `while`** — sa syntaxe et sa sémantique propre
  (`docs.python.org/fr/3/tutorial/introduction.html`, § « Premiers pas vers la
  programmation », et `reference/compound_stmts.html#while`) ;
- **compteur et accumulateur** — motifs d'écriture, absents de la doc
  officielle en tant que tels ; source pédagogique à choisir et à citer ;
- **validation d'une saisie** — dépend de `input()`, à ancrer sur
  `library/functions.html#input` ;
- **recherche dans une séquence** — à ancrer sur
  `tutorial/datastructures.html` ;
- **erreurs fréquentes dans les conditions** — à construire à partir des
  messages réels de `library/exceptions.html`, pas d'une liste de mémoire.

Ces cinq lacunes valent environ 8 à 10 cartes sur 30. Le niveau 2 est donc
rédigeable à hauteur d'une vingtaine de cartes avec ce fichier seul.

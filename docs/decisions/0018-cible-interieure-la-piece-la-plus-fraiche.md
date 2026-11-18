# 0018. La cible intérieure reste la pièce la plus fraîche, et les capteurs le disent

- **Date** : 18/11/2026
- **État** : acceptée
- **Rouvrir si** : le modèle apprend le poêle ; une prévision de la pièce chauffée deviendrait
  alors possible, et utile (l'heure où elle passera sous le seuil d'allumage).

## Contexte

Le modèle d'inertie et le conseil d'aération suivent `int_temp_min`, le minimum des sondes
intérieures, hérité de l'amont. L'été, toutes les pièces se valent à peu près. L'hiver, poêle en
marche, la pièce du poêle prend environ +3,3 °C par cycle et la sonde éloignée +1,1 °C : le
minimum est alors cette sonde éloignée 94 % du temps. Les deux capteurs publiés dans HA
s'appelaient "Température intérieure prévue" sans dire de quelle pièce il s'agissait.

Rejoué le 18/11/2026 sur la copie de la base : chaque semaine prédite avec des paramètres
appris sur les seules données antérieures (décision 0017), erreur absolue moyenne sur 0 à 24 h,
modèle puis persistance de la dernière mesure.

| Semaine | Minimum | Pièce du poêle | Pièce éloignée |
|---|---|---|---|
| 08/10 | 0,35 / 0,43 | 0,31 / 0,41 | 0,29 / 0,54 |
| 15/10 | 0,42 / 0,49 | 0,72 / 0,78 | 0,41 / 0,54 |
| 22/10 (poêle) | 0,70 / 0,55 | 1,42 / 1,29 | 0,62 / 0,53 |
| 29/10 (poêle) | 0,82 / 0,61 | 1,42 / 1,33 | 0,84 / 0,56 |
| 05/11 (poêle) | 0,64 / 0,66 | 1,03 / 1,06 | 0,68 / 0,60 |
| 12/11 (poêle) | 1,16 / 1,07 | 1,92 / 1,85 | 1,04 / 1,00 |

Pour le conseil (saison froide, soleil au-dessus de 10°), du 23/09 au 18/11 : 299 pas
favorables sur le minimum, 237 sur la pièce du poêle. Sur 33 pas, l'extérieur dépassait le
minimum sans dépasser la pièce du poêle, jamais pendant les créneaux d'hiver du 10 et du 11/11 :
poêle éteint, les deux pièces y étaient à 0,5 °C l'une de l'autre.

## Décision

- **La cible reste le minimum des sondes intérieures**, pour le modèle comme pour le conseil.
- **Les deux capteurs intérieurs publiés le disent** : libellés "Pièce la plus fraîche, prévue
  dans 6 h" et "Pièce la plus fraîche, maximum prévu sur 24 h", attribut `cible`. Les
  identifiants d'entité ne changent pas : le tableau de bord et d'éventuelles automatisations
  les nomment.

## Options écartées

| Option | Pourquoi pas ici |
|---|---|
| Prendre la pièce du poêle comme cible | sans le poêle dans le modèle, l'erreur double et ne bat plus la persistance ; c'est la pièce que le poêle règle, sa prévision attend la piste du poêle |
| Cible selon la saison (minimum l'été, pièce du poêle l'hiver) | même défaut l'hiver, et deux jeux de paramètres à tenir |
| Comparer le conseil d'hiver au maximum des sondes (ouvrir seulement si toutes les pièces y gagnent) | symétrique du minimum d'été, mais 41 % de pas favorables en moins pour éviter 33 pas en deux mois, tous hors des vrais créneaux d'hiver |
| Renommer les entités | casse ce qui les nomme, pour un gain que le libellé et l'attribut donnent déjà |

## Conséquences

- La prévision publiée reste la plus fiable des trois cibles, mais ne parle pas de la pièce
  où l'on vit l'hiver. L'heure où celle-ci passera sous 18 °C poêle éteint a été essayée
  ensuite, et écartée ([décision 0019](0019-poele-regime-regule.md)).
- Le libellé et l'attribut se mettent à jour à la publication suivante, sans action dans HA.
  Les cartes du tableau de bord qui portent leur propre nom le gardent.

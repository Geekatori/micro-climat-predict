# 0011. La puissance du poêle est archivée, sans être lue par le modèle

- **Date** : 23/09/2026
- **État** : acceptée
- **Rouvrir si** : l'archive couvre assez de cycles de chauffe pour écrire un modèle hivernal.

## Contexte

La maison est chauffée par un poêle à granulés, dont la puissance électrique remonte dans HA.
L'enregistreur de HA purge son historique en dix jours : sans archive, l'historique de chauffe
dont un futur modèle hivernal aura besoin serait perdu.

## Décision

Le collecteur archive la puissance du poêle (`STOVE_POWER_ENTITY`, en W) dans la colonne
`stove_power`. C'est un signal en marches : il est rééchantillonné au **maximum** par pas de
10 minutes et prolongé, jamais interpolé. Le modèle ne le lit pas encore.

## Options écartées

| Option | Pourquoi pas ici |
|---|---|
| Laisser l'historique dans HA | purgé en dix jours |
| Moyenne ou interpolation par pas | lisse les marches : un allumage bref disparaîtrait |

## Conséquences

- La prévision intérieure d'hiver ne sait pas encore que le poêle chauffe (voir les limites dans
  [`architecture.md`](../architecture.md#limites-connues)).

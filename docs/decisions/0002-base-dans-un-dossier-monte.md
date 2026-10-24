# 0002. La base SQLite vit dans `./data`, monté depuis le dossier du projet

- **Date** : 04/09/2026
- **État** : acceptée
- **Rouvrir si** : la base doit quitter SQLite, ou être sauvegardée autrement que par le dossier
  du projet.

## Contexte

L'amont rangeait `metrics.db` dans un volume anonyme. Un volume anonyme ne suit pas la
sauvegarde du dossier du projet, et se perd au premier `docker compose down -v`.

## Décision

Les trois services montent `./data` (bind mount) sur `/app/data`. La base, les modèles
entraînés, le mode saisonnier (`season.json`) et le suivi de publication (`publication_ha.json`)
y vivent.

## Options écartées

| Option | Pourquoi pas ici |
|---|---|
| Volume anonyme (amont) | ne suit pas les sauvegardes du dossier |

## Conséquences

- La base suit les sauvegardes du dossier du projet.
- `data/` est ignoré par git : rien de la maison ne part dans le dépôt.

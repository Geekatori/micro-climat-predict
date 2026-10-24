# 0004. L'ordonnanceur est une image construite, avec `tzdata` dedans

- **Date** : 09/09/2026
- **État** : acceptée
- **Rouvrir si** : l'ordonnanceur passe à un outil qui gère le fuseau sans `tzdata` dans l'image.

## Contexte

L'amont lançait `image: alpine` suivi d'un `apk add tzdata` au démarrage. Cet `apk` dépendait
du réseau au boot du serveur ; son échec, avalé par `|| true`, laissait `crond` en UTC sans une
ligne de journal.

## Décision

`scheduler/Dockerfile` part d'Alpine 3.22 et installe `tzdata` à la construction. Le fuseau vient
de `TZ`, passé par le compose (`Europe/Paris` par défaut). L'entraînement tourne à 5 h 30 heure
locale.

## Options écartées

| Option | Pourquoi pas ici |
|---|---|
| `apk add tzdata` au démarrage (amont) | dépend du réseau au boot, échoue en silence |

## Conséquences

- L'image de l'ordonnanceur se reconstruit avec les autres : `docker compose build --pull` met
  aussi Alpine à jour.

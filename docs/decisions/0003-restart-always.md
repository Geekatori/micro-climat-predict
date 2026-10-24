# 0003. Les conteneurs sont en `restart: always`, pas `unless-stopped`

- **Date** : 09/09/2026
- **État** : acceptée
- **Rouvrir si** : la pile quitte Unraid pour un hôte où l'arrêt du système ne fait pas de
  `docker stop` explicite.

## Contexte

Sur Unraid, l'arrêt de l'array fait un `docker stop` explicite sur chaque conteneur. Un
conteneur en `unless-stopped` arrêté ainsi est considéré comme arrêté par l'utilisateur, et ne
repart pas au boot suivant.

## Décision

`restart: always` pour les quatre services, posé une fois dans le bloc commun `x-common` du
`docker-compose.yml`.

## Options écartées

| Option | Pourquoi pas ici |
|---|---|
| `unless-stopped` (amont) | la pile reste éteinte après un redémarrage d'Unraid |

## Conséquences

- Un conteneur arrêté à la main repart au prochain démarrage du démon Docker : pour le garder
  éteint, `docker compose down` plutôt que `docker stop`.

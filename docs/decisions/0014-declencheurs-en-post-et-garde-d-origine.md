# 0014. Les déclencheurs de l'interface sont en POST, sous garde d'origine, et le reset total est verrouillé

- **Date** : 09/10/2026
- **État** : acceptée
- **Rouvrir si** : l'interface reçoit une authentification qui couvre déjà ces cas.

## Contexte

`/trigger-*` et `/api/backfill-co2` étaient des GET : un lien préchargé ou une balise `<img>`
suffisait à lancer une collecte, un entraînement, ou le reset total de la base et des modèles.
`/admin` n'a pas d'authentification ([0001](0001-ports-en-boucle-locale.md)).

## Décision

- `/trigger-season`, `/trigger-collect`, `/trigger-train`, `/trigger-clear-cache`,
  `/trigger-clear`, `/api/backfill-co2` et `/api/publish-ha` n'acceptent que `POST` (un GET
  répond 405). Les boutons de `/admin` sont des formulaires.
- **Garde d'origine** : le POST seul ne suffit pas, une page tierce ouverte sur le LAN peut poster
  un formulaire simple. Toute requête POST, PUT, PATCH ou DELETE dont l'en-tête `Origin` (à défaut
  `Referer`) désigne un autre `hôte:port` que l'en-tête `Host` reçoit 403. Sans aucun des deux
  (planificateur, `curl`), elle passe. `ALLOWED_ORIGINS` admet d'autres origines.
- **Reset total** (`/trigger-clear`) : 403 tant que `ALLOW_RESET=1` n'est pas dans
  l'environnement du web-ui ; autorisé, il exige le champ `confirm=SUPPRIMER`, que `/admin` fait
  saisir.

## Options écartées

| Option | Pourquoi pas ici |
|---|---|
| GET (amont) | un simple lien suffit à lancer une action |

## Conséquences

- Le planificateur appelle la publication par `wget --post-data=`.
- Un nom servi par un proxy doit être ajouté à `ALLOWED_ORIGINS`, sinon ses POST reçoivent 403.
- Remettre `ALLOW_RESET=0` après usage.

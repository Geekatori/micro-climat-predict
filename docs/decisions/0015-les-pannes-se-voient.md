# 0015. Les pannes se voient : collecte en 502, entités muettes journalisées, route de fraîcheur

- **Date** : 09/10/2026 (journalisation des entités du web-ui : 15/09/2026)
- **État** : acceptée
- **Rouvrir si** : une panne passe encore inaperçue plusieurs heures.

## Contexte

Chez l'amont, plusieurs pannes restaient silencieuses : une collecte sans aucun point de HA
répondait succès, le web-ui affichait `--` pour une entité injoignable sans laisser de trace,
et une publication ou un entraînement pouvaient échouer des jours sans autre trace que les
journaux, une sonde externe ne voyant que la collecte.

## Décision

- **Collecte en échec** : quand HA ne fournit pas de réponse exploitable (éteint, jeton révoqué,
  réponse illisible même en partie) ou aucun point pour l'extérieur ou pour tous les capteurs
  intérieurs, `/api/collect` répond 502 et note `error` dans `collection_logs`, cause comprise.
  Un capteur secondaire muet (humidité, CO₂, poêle) est seulement cité dans le message de la
  collecte réussie. La météo est enregistrée quand même. Une collecte réussie note le nombre de
  points HA reçus.
- **Entités muettes** : le web-ui journalise chaque entité HA injoignable ou non numérique.
- **Fraîcheur** : `GET /health/fraicheur` sur le web-ui répond 503 dès que la collecte, la
  publication ou l'entraînement ont cessé de réussir (seuils dans
  [`reference.md`](../reference.md#la-route-de-fraîcheur)). Une sonde externe (Gatus) la consulte.
- **Ping de la collecte**, facultatif (ajouté le 26/10/2026) : `HC_COLLECT_URL` renseignée, le
  planificateur pingue cette URL après chaque collecte réussie, et `/fail` après un échec. Un
  Healthchecks voit ainsi aussi une collecte qui ne part plus du tout.

## Options écartées

| Option | Pourquoi pas ici |
|---|---|
| Succès sur réponse partielle (amont) | une collecte vide passait pour réussie |
| Sonder `/api/status/*` | ne couvre pas la publication, et lit SQLite pendant l'entraînement |

## Conséquences

- Le `wget` du planificateur échoue sur une collecte en 502 : le ping de la collecte envoie
  `/fail` au lieu d'un battement vert.

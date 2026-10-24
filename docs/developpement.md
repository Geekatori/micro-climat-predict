# micro-climat-predict : développement

## Tester une modification

Lancer la pile en local comme en [installation](installation.md#démarrer), avec un `.env` qui
pointe vers une instance Home Assistant. Après un changement de code :

```bash
docker compose config -q && docker compose up -d --build <service>
```

Le moteur se rejoue sur la base réelle en relançant un entraînement (`POST /api/train`) puis en
lisant `/api-meteo/analysis` et `/api-meteo/forecast`.

## Sous Docker Desktop et WSL2

Docker Desktop en mode réseau miroir ne joint pas le LAN, donc pas Home Assistant.
`compose.wsl.yml` et `scripts/wsl-ha-relay.py` contournent ce cas : leur mode d'emploi est dans
leurs en-têtes. Inutile sur un serveur Linux, où les conteneurs joignent le LAN directement.

## Les règles du code

- Une entité HA vient toujours de l'environnement : rien de propre à une maison dans le code. Hors
  compose, les identifiants de l'amont restent les valeurs par défaut.
- Les horodatages du moteur sont en UTC naïf ; ils sont convertis en ISO 8601 avec fuseau avant
  publication dans HA. L'heure d'affichage `Europe/Paris` est en dur (hérité de l'amont).
- Un signal en marches (puissance du poêle) se rééchantillonne au maximum et se prolonge, jamais
  par interpolation ([décision 0011](decisions/0011-poele-archive-hors-modele.md)).
- Une panne doit se voir : une route qui ne reçoit rien d'exploitable répond en erreur et le
  journalise, plutôt que d'afficher `--` ou de répondre succès
  ([décision 0015](decisions/0015-les-pannes-se-voient.md)).
- Toute route qui déclenche une action est en POST, sous la garde d'origine
  ([décision 0014](decisions/0014-declencheurs-en-post-et-garde-d-origine.md)).
- Ce qui doit survivre au reset total vit hors de `metrics.db`, comme `season.json`.
- Les différences avec l'amont sont tenues dans
  [`differences-avec-l-amont.md`](differences-avec-l-amont.md) : en ajouter une ligne à chaque
  écart.

# micro-climat-predict : installation

Du dossier vide au service qui prédit. Il faut Docker avec Compose v2, une instance Home
Assistant joignable depuis le serveur et un jeton longue durée.

## Configurer

Dans un terminal sur le serveur, dans le dossier du dépôt cloné :

```bash
cp .env.example .env       # HA_URL, HA_TOKEN, LAT/LON, entités
```

Renseigner `.env` d'après [`reference.md`](reference.md#configuration) : une entité laissée vide
désactive le capteur correspondant.

## Démarrer

```bash
docker compose up --build -d
curl "http://127.0.0.1:8732/api/collect?days=10"   # première collecte, 10 jours d'historique HA
curl -X POST http://127.0.0.1:8731/api/train        # premier entraînement
```

Interface : `http://127.0.0.1:8730` (`/`, `/graphs`, `/admin`, `/logs`). Choisir la saison dans
`/admin` (« chaud » par défaut).

## Ouvrir l'interface au réseau

Les ports 8730 (web-ui), 8731 (ml-engine) et 8732 (data-collector) sont liés à `127.0.0.1`. Seule
l'interface peut être ouverte au réseau, en donnant à `WEB_BIND` l'adresse du serveur. La page
`/admin` n'a aucune authentification : sur un LAN, mettre un reverse proxy ou un VPN devant
([décision 0001](decisions/0001-ports-en-boucle-locale.md)), et déclarer son nom dans
`ALLOWED_ORIGINS`.

## Sur Unraid

`UNRAID_ICON_URL` donne l'icône des quatre conteneurs dans l'onglet Docker ; le lien vers
l'interface (`net.unraid.docker.webui`) est déjà dans le compose. Les conteneurs sont en
`restart: always` pour repartir après un arrêt de l'array
([décision 0003](decisions/0003-restart-always.md)).

## Brancher la supervision

- `/health/fraicheur` sur le web-ui, pour une sonde HTTP externe
  ([`reference.md`](reference.md#la-route-de-fraîcheur)).
- `HC_COLLECT_URL` dans `.env` : chaque collecte pingue un Healthchecks, et une collecte vide
  (502) pingue `/fail` ([décision 0015](decisions/0015-les-pannes-se-voient.md)). Recréer
  `cron` après l'avoir changée : la crontab s'écrit au démarrage du conteneur.

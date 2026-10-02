# micro-climat-predict

**micro-climat-predict** est une application conteneurisée conçue pour collecter, stocker et analyser les données micro-climatiques locales (via Home Assistant) et les croiser avec des données météorologiques ouvertes (Open-Meteo) ainsi qu'avec des modèles de positionnement solaire précis. L'objectif final est d'alimenter un moteur de machine learning pour prédire l'évolution thermique intérieure (notamment l'impact des ombres de la rue).

Ce dépôt est un fork de [jmfavreau/micro-climat-predict](https://codeberg.org/jmfavreau/micro-climat-predict)
(AGPL-3.0), adapté à une autre maison : autres capteurs, pas de CO₂, un poêle à granulés,
hébergement sur un NAS. Le code complet de cette version est publié ici conformément à la
licence. Les différences avec l'amont sont listées [plus bas](#différences-avec-lamont).

## Architecture

Quatre services Docker Compose, un réseau interne, une base SQLite partagée dans `./data` :

1. **`data-collector`** (FastAPI) : lit l'historique des capteurs dans Home Assistant et
   l'historique plus les prévisions d'Open-Meteo, consolide le tout au pas de 10 minutes
   dans `metrics.db`.
2. **`ml-engine`** (FastAPI + scikit-learn + scipy) : entraîne un modèle de gradient boosting
   pour l'extérieur, un second pour l'intérieur, et ajuste un modèle d'inertie thermique
   paramétrique. Sert les prévisions et le conseil d'aération.
3. **`web-ui`** (FastAPI + Tailwind + ApexCharts) : tableau de bord, administration, journaux,
   et publication des prédictions dans Home Assistant.
4. **`cron`** (busybox crond) : collecte à h+08 et h+38, publication HA à h+12 et h+42,
   entraînement à 5 h 30 heure locale.

## Démarrage

```bash
cp .env.example .env       # HA_URL, HA_TOKEN, LAT/LON, entités
docker compose up --build -d
curl "http://127.0.0.1:8732/api/collect?days=10"   # première collecte, 10 jours d'historique HA
curl -X POST http://127.0.0.1:8731/api/train        # premier entraînement
```

Interface : http://127.0.0.1:8730 (`/`, `/graphs`, `/admin`, `/logs`).

Les ports 8730 (web-ui), 8731 (ml-engine) et 8732 (data-collector) sont liés à `127.0.0.1`.
Seule l'interface peut être ouverte au réseau, par `WEB_BIND`. La page `/admin` n'a aucune
authentification : sur un LAN, mettre un reverse proxy ou un VPN devant.

## Configuration

Tout passe par `.env` (modèle dans `.env.example`). Une entité laissée vide désactive le
capteur correspondant. Hors compose, les identifiants de l'amont restent les valeurs par
défaut du code.

| Variable | Rôle |
|---|---|
| `HA_URL`, `HA_TOKEN` | instance Home Assistant et jeton longue durée |
| `LAT`, `LON` | Open-Meteo, course du soleil, qualité de l'air |
| `EXT_ENTITY`, `HUM_ENTITY` | température et humidité extérieures |
| `INT_TEMP_ENTITY`, `INT_HUM_ENTITY`, `HA_COR_TEMP`, `COR_HUM_ENTITY` | sondes intérieures ; `int_temp_min` est le minimum des températures présentes |
| `HA_INTERIOR_TEMP_MIN` | entité affichée sur la page d'accueil (chez l'amont, un capteur template du minimum intérieur) |
| `CO2_ENTITY` | détection des ouvertures de fenêtres ; vide = pas de détection |
| `STOVE_POWER_ENTITY` | puissance du poêle en W, archivée mais pas encore lue par le modèle |
| `INT_HOT_THRESHOLD_C` | seuil « intérieur chaud » du détecteur CO₂ (23 °C) |
| `FAVORABLE_MARGIN_CHAUD`, `FAVORABLE_MARGIN_FROID` | hystérésis du conseil d'aération (0,5 et 0,3 °C) |
| `HA_SENSOR_PREFIX`, `HA_PUBLISH_HORIZON_HOURS` | capteurs publiés dans HA (`micro_climat`, 6 h) |
| `WEB_BIND`, `WEB_PORT`, `ML_PORT`, `COLLECTOR_PORT`, `TZ` | réseau, fuseau du planificateur |
| `UNRAID_ICON_URL` | icône de l'onglet Docker d'Unraid, vide ailleurs |

## Différences avec l'amont

- **Entités HA configurables** par `.env` au lieu d'être codées dans `data-collector/main.py`.
- **Ports liés à `127.0.0.1`** et déplacés en 8730 à 8732.
- **SQLite en bind mount `./data`** au lieu d'un volume anonyme : la base suit les sauvegardes
  du dossier.
- **`LAT`/`LON` transmis au `ml-engine`** : l'amont calculait la position du soleil sur ses
  coordonnées par défaut quelle que soit la configuration.
- **Cron d'entraînement** : `/api/train` est en POST, `wget` l'appelait en GET. Il tourne à
  5 h 30 heure locale ; `tzdata` est dans l'image de l'ordonnanceur (`scheduler/Dockerfile`,
  Alpine 3.22). L'`apk add tzdata` au démarrage dépendait du réseau au boot, et son échec,
  avalé par `|| true`, laissait `crond` en UTC sans une ligne de log.
- **`restart: always`** au lieu de `unless-stopped` : sur Unraid, l'arrêt de l'array fait un
  `docker stop` explicite, et un conteneur `unless-stopped` arrêté ainsi ne repart pas au
  boot suivant.
- **Historique HA : timeout 120 s et `no_attributes`** : dix jours sur six entités dépassaient
  les 20 s, en silence.
- **Colonnes vides tolérées** dans le `ml-engine` : une colonne entièrement NULL sort de SQLite
  en dtype `object` et faisait échouer `interpolate()`.
- **Puissance du poêle archivée** (`stove_power`, en W). L'enregistreur HA purge en dix
  jours ; la colonne garde l'historique de chauffe pour un futur modèle hivernal. Signal en
  marches : rééchantillonné au maximum par pas et prolongé, jamais interpolé.
- **Mode saisonnier** et **heure de fermeture**, voir ci-dessous.
- **Publication des prédictions dans HA**, voir ci-dessous.
- **Qualité de l'air par Open-Meteo** au lieu de `PM25_ENTITY` / `PM10_ENTITY`.
- **Sondes de santé** sur les trois services web (`/openapi.json` toutes les 60 s). Pas `/` :
  le collecteur et le moteur n'ont pas de route racine. Pas `/api/status/*` : ces routes
  lisent SQLite et clignoteraient pendant l'entraînement.
- **Reset total** : supprime les trois fichiers de modèle réellement produits. L'amont ne
  supprimait que `model_int.joblib`, qui n'existe pas.
- **Pannes visibles** : le web-ui journalise chaque entité HA injoignable ou non numérique au
  lieu d'afficher `--` sans trace.

## Mode saisonnier

Le conseil d'aération a un sens, et il s'inverse avec la saison : en été on ouvre quand
l'extérieur repasse sous l'intérieur, en saison froide quand il passe au-dessus. Le mode se
règle depuis `/admin` (« chaud » par défaut) et vit dans `data/season.json`, hors de
`metrics.db`, pour survivre au reset total. La bascule vide les caches de prévision.

Deux instants sont calculés, ouverture puis fermeture. Quand l'extérieur est déjà favorable,
seule la fermeture est annoncée : l'ouverture vaut `unknown` avec `creneau_en_cours: true`.
L'état courant se juge sur l'intérieur mesuré (dernier point de moins d'une heure), pas sur
la simulation, qui dérive de plusieurs degrés dans le passé. Sans mesure fraîche, on lit le
premier pas futur, qui repart lui aussi de la dernière mesure.

L'hystérésis dépend de la saison : 0,5 °C en saison chaude, 0,3 °C en saison froide. En
automne les deux courbes se frôlent : à 0,5 °C, un créneau réel de trois heures ne tenait pas
six pas consécutifs et le conseil sautait au lendemain, hors de l'horizon de 18 h. 0,3, 0,2 et
0,1 donnent le même créneau. La durée de stabilité reste à six pas (une heure) dans les deux
saisons.

Le détecteur d'ouverture par le CO₂ s'inverse aussi. Son critère d'été (intérieur plus chaud
que l'extérieur et qui baisse) décrit toutes les nuits d'hiver, et aurait exclu de
l'ajustement les données dont un modèle hivernal a besoin. Faute de capteur CO₂ sur cette
installation, la branche froide n'a jamais tourné sur des données réelles.

## Publication dans Home Assistant

Le web-ui pousse quatre capteurs par `POST /api/states/<entity_id>`, toutes les 30 minutes
ou à la main par `GET /api/publish-ha`. Rien à ajouter dans `configuration.yaml`, aucun
port à ouvrir : le trafic ne part que vers HA.

| Entité | Contenu |
|---|---|
| `sensor.<prefix>_ouverture_fenetres` | heure d'ouverture conseillée (`device_class: timestamp`) ; attributs `mode_saison`, `creneau_en_cours` |
| `sensor.<prefix>_fermeture_fenetres` | heure de fermeture conseillée ; attribut `mode_saison` |
| `sensor.<prefix>_interieur_dans_6h` | température intérieure prévue à `HA_PUBLISH_HORIZON_HOURS` |
| `sensor.<prefix>_interieur_max_24h` | maximum intérieur prévu sur 24 h, horaire du pic en attribut |

Limites assumées : un état écrit ainsi vit en mémoire dans HA, disparaît à chaque
redémarrage et revient à la publication suivante ; sans identifiant unique, ces entités ne
sont ni renommables ni rattachables à une pièce. MQTT lèverait les deux. Les horodatages du
moteur sont en UTC naïf et convertis en ISO 8601 avec fuseau avant publication. Sans donnée
exploitable, la publication est sautée plutôt que d'écraser les états par `unknown`.

Pour une automatisation de notification : l'heure est republiée toutes les 30 minutes et
peut osciller d'un pas, ce qui réarme un déclencheur template à chaque passage. Prévoir un
anti-rebond de quelques heures sur `last_triggered`. Pour tracer la courbe prédite dans HA,
`/api-meteo/forecast` expose la série complète ; `apexcharts-card` la trace, `mini-graph-card`
ne trace pas le futur.

## Qualité de l'air extérieur

PM2.5 et PM10 de la page d'accueil viennent de l'API qualité de l'air d'Open-Meteo
(`fetch_air_quality()` dans `web-ui/main.py`, cache de 15 min, pas de clé). C'est une valeur
modélisée CAMS sur la maille, pas une mesure en station : les intégrations HA Atmo France
exposent un indice de 1 à 6, pas une concentration en µg/m³.

## Limites connues

- Sans capteur CO₂, pas de détection d'ouverture : le modèle d'inertie ne distingue pas les
  périodes fenêtres ouvertes, ce qui dégrade la prévision intérieure en été.
- En plein hiver l'extérieur ne dépasse jamais l'intérieur : les capteurs d'ouverture et de
  fermeture restent `unknown` des semaines durant. C'est attendu. L'aération d'hygiène
  relèverait d'une règle distincte, non écrite.
- `stove_power` est archivé mais pas encore lu par le modèle.
- L'heure locale d'affichage est `Europe/Paris`, en dur dans le moteur et l'interface
  (hérité de l'amont).

## Exploitation

**Image de base** : `docker compose build --pull && docker compose up -d`.
**Changement de code** : `docker compose config -q && docker compose up -d --build <service>`,
sans `--pull`.

**Test sous Docker Desktop / WSL2** : le réseau miroir ne joint pas le LAN.
`scripts/wsl-ha-relay.py` relaie le TCP vers HA depuis l'hôte WSL, et `compose.wsl.yml` fait
résoudre `HA_HOST` vers cet hôte. Le TLS traverse intact.

```bash
python3 scripts/wsl-ha-relay.py <ip-home-assistant>:8123 &
docker compose -f docker-compose.yml -f compose.wsl.yml up -d
```

## Licence

AGPL-3.0, comme l'amont. Voir `LICENSE`.

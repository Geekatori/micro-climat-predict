# micro-climat-predict : référence

Ce qui est : services, configuration, fichiers, routes, entités publiées. Le fonctionnement du
moteur est dans [`architecture.md`](architecture.md).

## Services et ports

| Service | Conteneur | Port publié | Rôle |
|---|---|---|---|
| `data-collector` | `mcp-data-collector` | `127.0.0.1:8732` (`COLLECTOR_PORT`) | collecte HA et Open-Meteo |
| `ml-engine` | `mcp-ml-engine` | `127.0.0.1:8731` (`ML_PORT`) | entraînement, prévisions, conseil |
| `web-ui` | `mcp-web-ui` | `${WEB_BIND:-127.0.0.1}:8730` (`WEB_PORT`) | interface, publication HA |
| `cron` | `mcp-scheduler` | aucun | busybox crond, fuseau `TZ` |

Dans le conteneur, chaque service web écoute sur 8000 ; entre eux, ils se joignent par le réseau
interne `meteo_network` (`http://ml-engine:8000`, `http://data-collector:8000`). Seule l'interface
peut être ouverte au réseau, par `WEB_BIND` ([décision 0001](decisions/0001-ports-en-boucle-locale.md)).
L'interface sert `/`, `/graphs`, `/admin`, `/logs` et `/widget`.

## Configuration

Tout passe par `.env` (modèle dans `.env.example`). Une entité laissée vide désactive le capteur
correspondant. Hors compose, les identifiants de l'amont restent les valeurs par défaut du code.

| Variable | Rôle |
|---|---|
| `HA_URL`, `HA_TOKEN` | instance Home Assistant et jeton longue durée |
| `LAT`, `LON` | Open-Meteo, course du soleil, qualité de l'air |
| `EXT_ENTITY`, `HUM_ENTITY` | température et humidité extérieures |
| `INT_TEMP_ENTITY`, `INT_HUM_ENTITY`, `HA_COR_TEMP`, `COR_HUM_ENTITY` | sondes intérieures ; `int_temp_min` est le minimum des températures présentes |
| `HA_INTERIOR_TEMP_MIN` | entité affichée sur la page d'accueil (chez l'amont, un capteur template du minimum intérieur) |
| `CO2_ENTITY` | CO₂ collecté, archivé et affiché ; vide = pas de CO₂ |
| `CO2_MODELE` | `1` : le modèle d'inertie lit le CO₂ (détection d'ouverture) ; `0` par défaut ([décision 0012](decisions/0012-co2-collecte-hors-modele.md)) |
| `STOVE_POWER_ENTITY` | puissance du poêle en W, archivée mais pas encore lue par le modèle ([décision 0011](decisions/0011-poele-archive-hors-modele.md)) |
| `INT_HOT_THRESHOLD_C` | seuil « intérieur chaud » du détecteur CO₂ (23 °C) |
| `FAVORABLE_MARGIN_CHAUD`, `FAVORABLE_MARGIN_FROID` | hystérésis du conseil d'aération (0,5 et 0,3 °C, [décision 0009](decisions/0009-hysteresis-par-saison.md)) |
| `SUN_MIN_ELEVATION_FROID` | hauteur minimale du soleil pour une ouverture en saison froide (10°) ; lue par le moteur, absente du compose ([décision 0016](decisions/0016-pas-d-ouverture-soleil-bas-en-saison-froide.md)) |
| `HA_SENSOR_PREFIX`, `HA_PUBLISH_HORIZON_HOURS` | capteurs publiés dans HA (`micro_climat`, 6 h) |
| `WEB_BIND`, `WEB_PORT`, `ML_PORT`, `COLLECTOR_PORT`, `TZ` | réseau, fuseau du planificateur |
| `ALLOW_RESET` | `1` autorise le reset total de `/admin` ; absent ou `0` (défaut), la route répond 403 |
| `ALLOWED_ORIGINS` | facultatif, séparées par des virgules : origines admises par la garde d'origine en plus de l'hôte de la requête, par exemple un nom servi par un proxy |
| `UNRAID_ICON_URL` | icône de l'onglet Docker d'Unraid, vide ailleurs (le label est alors sans effet) |

Le mode saisonnier n'est pas une variable d'environnement : il se règle depuis `/admin`
([décision 0008](decisions/0008-mode-saisonnier.md)).

## Planification

L'ordonnanceur (`cron`) appelle les services par le réseau interne, en heure locale (`TZ`) :

| Quand | Appel |
|---|---|
| h+08 et h+38 | `wget -qO- http://data-collector:8000/api/collect` |
| h+12 et h+42 | `wget -qO- --post-data= http://web-ui:8000/api/publish-ha` |
| 5 h 30 | `wget -qO- --post-data= http://ml-engine:8000/api/train` |

## Fichiers de `data/`

Monté sur `/app/data` dans les trois services web ([décision 0002](decisions/0002-base-dans-un-dossier-monte.md)).

| Fichier | Contenu | Effacé par le reset total |
|---|---|---|
| `metrics.db` | base SQLite, au pas de 10 minutes ; journaux de collecte dans `collection_logs` | oui |
| `model_ext.joblib`, `model_int_gb.joblib`, `model_int_std.joblib` | les trois modèles entraînés | oui |
| `season.json` | mode saisonnier, « chaud » par défaut | non |
| `publication_ha.json` | essais de publication dans HA, lus par `/health/fraicheur` | non |

## Routes

Relevées dans le code. Toutes les routes qui déclenchent une action sont en POST
([décision 0014](decisions/0014-declencheurs-en-post-et-garde-d-origine.md)).

| Service | Route | Rôle |
|---|---|---|
| web-ui | `POST /trigger-collect?days=N`, `/trigger-train`, `/trigger-season`, `/trigger-clear-cache` | boutons de `/admin` |
| web-ui | `POST /trigger-clear` | reset total, verrouillé par `ALLOW_RESET` et `confirm=SUPPRIMER` |
| web-ui | `POST /api/publish-ha` | publication dans HA |
| web-ui | `POST /api/backfill-co2?days=N` | reprise de l'historique de CO₂ de HA (30 jours par défaut) |
| web-ui | `GET /api-meteo/forecast` | la série prédite complète |
| web-ui | `GET /api-meteo/analysis` | le conseil d'aération, `favorable_now` compris |
| web-ui | `GET /health/fraicheur` | fraîcheur de la collecte, de la publication et de l'entraînement |
| data-collector | `GET /api/collect?days=N` | collecte ; 502 quand HA ne fournit rien ([décision 0015](decisions/0015-les-pannes-se-voient.md)) |
| ml-engine | `POST /api/train` | entraînement |
| ml-engine | `GET`, `POST /api/season` | lire ou changer le mode saisonnier |

## Entités publiées dans Home Assistant

Le web-ui pousse quatre capteurs par `POST /api/states/<entity_id>`, toutes les 30 minutes ou à
la main par `POST /api/publish-ha` ([décision 0006](decisions/0006-publication-ha-par-l-api-rest.md)).

| Entité | Contenu |
|---|---|
| `sensor.<prefix>_ouverture_fenetres` | heure d'ouverture conseillée (`device_class: timestamp`) ; attributs `mode_saison`, `creneau_en_cours` |
| `sensor.<prefix>_fermeture_fenetres` | heure de fermeture conseillée ; attribut `mode_saison` |
| `sensor.<prefix>_interieur_dans_6h` | température intérieure prévue à `HA_PUBLISH_HORIZON_HOURS` |
| `sensor.<prefix>_interieur_max_24h` | maximum intérieur prévu sur 24 h, horaire du pic en attribut |

Les horodatages du moteur sont en UTC naïf et convertis en ISO 8601 avec fuseau avant
publication. Sans donnée exploitable, la publication est sautée plutôt que d'écraser les états
par `unknown`.

## La route de fraîcheur

`GET /health/fraicheur` sur le web-ui répond 200 si :

- la dernière collecte et la dernière publication HA réussies ont moins de 75 min (rythme de
  30 min : un passage manqué est toléré, le deuxième signalé) ;
- le dernier entraînement réussi a moins de 26 h (quotidien à 5 h 30, jour de 25 h du changement
  d'heure compris).

Sinon 503, avec le détail en JSON. Avant la première publication, la route répond 503.

## Qualité de l'air

PM2.5 et PM10 de la page d'accueil viennent de l'API qualité de l'air d'Open-Meteo
(`fetch_air_quality()` dans `web-ui/main.py`, cache de 15 min, pas de clé) : une valeur modélisée
CAMS sur la maille, pas une mesure en station ([décision 0007](decisions/0007-qualite-de-l-air-par-open-meteo.md)).

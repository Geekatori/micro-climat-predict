# micro-climat-predict

**micro-climat-predict** est une application conteneurisée conçue pour collecter, stocker et analyser les données micro-climatiques locales (via Home Assistant) et les croiser avec des données météorologiques ouvertes (Open-Meteo) ainsi qu'avec des modèles de positionnement solaire précis. L'objectif final est d'alimenter un moteur de machine learning pour prédire l'évolution thermique intérieure (notamment l'impact des ombres de la rue).

> **Ce qu'il reste à faire : [TODO.md](TODO.md)**, par priorité.

## Architecture du Projet

Le projet repose sur une architecture de microservices avec Docker Compose :

1. **`data-collector`** (FastAPI) :
   - Interroge l'API de Home Assistant pour récupérer les températures et humidités intérieures/extérieures.
   - Interroge l'API Open-Meteo pour récupérer l'historique et les prévisions de température, d'humidité et de vitesse du vent.
   - Calcule mathématiquement la position du soleil (élévation et azimut) pour chaque intervalle de temps.
   - Stocke et consolide le tout dans une base de données SQLite unique avec une stratégie de mise à jour glissante.

2. **`ml-engine`** (FastAPI + Scikit-Learn) :
   - Entraîne des modèles de régression (Gradient Boosting) pour anticiper l'évolution thermique.
   - Fournit des endpoints de prévision pour les températures intérieures et extérieures.

3. **`web-ui`** (FastAPI + TailwindCSS + ApexCharts) :
   - Fournit un tableau de bord visuel et interactif avec bascule de vue 24h/7j.
   - Se connecte désormais directement à l'API de Home Assistant pour afficher les courbes en temps réel tout en s'appuyant sur le moteur ML et SQLite pour les prévisions futures.
   - Propose des pages d'administration et de suivi des logs d'opérations.
   - Permet de déclencher manuellement les collectes et les entraînements à la demande.

## Prérequis

- Docker et Docker Compose installés sur votre machine.
- Une instance Home Assistant accessible avec un Token d'accès longue durée (Long-Lived Access Token).

## Configuration

1. Créez un fichier `.env` à la racine du projet en vous basant sur l'exemple ci-dessous :

```env
WEB_PORT=8000
HA_URL=[http://homeassistant.local:8123](http://homeassistant.local:8123)
HA_TOKEN=votre_token_longue_duree_home_assistant
LAT=45.7797
LON=3.0863
```

2. Vérifiez que les identifiants de vos entités de capteurs Home Assistant correspondent à ceux définis dans data-collector/main.py.

## Lancement

Lancez l'ensemble des services avec la commande suivante :

```bash
docker compose up --build -d
```

L'interface web est ensuite accessible sur : http://localhost:8000 (ou le port configuré dans votre compose).

## Licence

Ce projet est sous licence AGPL-3.0 (GNU Affero General Public License v3.0).
Vous êtes libre de l'utiliser, de le modifier et de le distribuer, sous réserve que toute modification ou version réseau dérivée mette également son code source à disposition sous la même licence. Voir le fichier LICENSE pour plus de détails.

---

## Fork : adaptation à une autre maison

Ce dépôt est un fork de [jmfavreau/micro-climat-predict](https://codeberg.org/jmfavreau/micro-climat-predict)
(AGPL-3.0), dont le développement amont s'est arrêté en septembre 2026. Le code source complet
de cette version modifiée est publié ici, conformément à la licence.

### Ce qui change par rapport à l'amont

- **Entités Home Assistant configurables** dans `.env` au lieu d'être codées en dur dans
  `data-collector/main.py`. Une variable vide désactive le capteur (`CO2_ENTITY=` si l'on n'a
  pas de capteur CO₂ ; le modèle fonctionne alors sans détection d'ouverture de fenêtre).
- **Ports liés à `127.0.0.1`** et déplacés hors des plages courantes (8730 à 8732 au lieu de
  8000 à 8002) : rien n'est exposé sur le réseau. Mettre un reverse proxy ou
  Tailscale devant si besoin.
- **Base SQLite en bind mount `./data`** plutôt qu'un volume Docker anonyme, pour qu'elle
  suive les sauvegardes du dossier.
- **`LAT`/`LON` transmis au `ml-engine`** (l'amont calculait la position du soleil sur les
  coordonnées par défaut, quelle que soit la configuration).
- **Cron d'entraînement corrigé** : la route `/api/train` est en POST, `wget` l'appelait en GET.
- **Timeout Home Assistant** porté à 120 s et réponse allégée avec `no_attributes` : dix jours
  d'historique sur six entités dépassaient les 20 s de l'amont et l'échec était silencieux.
- **Colonnes vides tolérées** dans le `ml-engine` : une colonne entièrement NULL sortait de
  SQLite en dtype `object` et faisait échouer l'interpolation.

### Démarrage

```bash
cp .env.example .env      # puis renseigner HA_URL, HA_TOKEN, LAT/LON et les entités
docker compose up --build -d
curl "http://127.0.0.1:8732/api/collect?days=10"   # première collecte (10 jours d'historique HA)
curl -X POST http://127.0.0.1:8731/api/train        # premier entraînement
```

Interface : http://127.0.0.1:8730 (accueil), `/graphs`, `/admin`, `/logs`.
Ensuite le planificateur collecte à h+08 et h+38 et réentraîne chaque nuit à **5 h 30 heure
locale** (le conteneur installe `tzdata` et lit `TZ`, sinon busybox raisonnerait en UTC).
L'horaire évite volontairement les sauvegardes de 3 h 03 et 4 h 00.

### Test sous Docker Desktop / WSL2

Docker Desktop en mode réseau miroir ne joint pas le LAN, donc pas Home Assistant. Contournement :

```bash
python3 scripts/wsl-ha-relay.py 192.168.1.X:8123 &        # relais TCP sur l'hôte WSL
docker compose -f docker-compose.yml -f compose.wsl.yml up -d
```

`compose.wsl.yml` fait résoudre `HA_HOST` vers l'hôte WSL ; le TLS traverse le relais intact.
Inutile sur un serveur Linux classique (Unraid, etc.).

### Limites connues

- La détection d'ouverture des fenêtres repose sur un capteur CO₂. Sans lui, le modèle
  d'inertie ne distingue pas les périodes fenêtres ouvertes, ce qui dégrade la prévision
  intérieure en été. Pistes : ajouter un capteur CO₂ Zigbee, ou remplacer la détection par les
  capteurs d'ouverture de fenêtres quand ils existent.
- `HA_INTERIOR_TEMP_MIN` (page d'accueil) attend une entité HA ; l'amont utilise un capteur
  template calculant le minimum des sondes intérieures. À défaut, pointer sur une sonde unique.

### Intégration Home Assistant

Le projet **pousse** ses prédictions dans HA (`POST /api/states/...`) au lieu d'attendre que HA
vienne les chercher. Aucune ligne à ajouter dans `configuration.yaml`, aucun port à ouvrir : le
trafic ne part que vers HA. C'est le bon compromis quand on n'a pas d'accès shell sur l'instance.

Trois capteurs sont écrits, tous préfixés par `HA_SENSOR_PREFIX` (`micro_climat` par défaut) :

| Entité | Contenu |
|---|---|
| `sensor.<prefix>_ouverture_fenetres` | heure conseillée d'ouverture (`device_class: timestamp`) |
| `sensor.<prefix>_interieur_dans_6h` | température intérieure prévue à l'horizon `HA_PUBLISH_HORIZON_HOURS` |
| `sensor.<prefix>_interieur_max_24h` | maximum intérieur prévu sur 24 h, horaire du pic en attribut |

Publication toutes les 30 minutes par le planificateur, aux minutes 12 et 42, soit quatre
minutes après chaque collecte. Déclenchement manuel :

```bash
curl http://127.0.0.1:8730/api/publish-ha
```

**Deux limites assumées.** Un état écrit par `POST /api/states` vit en mémoire : il disparaît à
chaque redémarrage de HA et revient à la publication suivante, donc au pire trente minutes plus
tard. Et faute d'identifiant unique, ces entités ne sont ni renommables ni rattachables à une
pièce depuis l'interface. Passer à MQTT lèvera les deux, au prix d'un broker à installer.

**Fuseau horaire.** Le moteur de prédiction travaille en temps universel naïf. La publication
convertit en ISO 8601 avec fuseau explicite, sinon HA afficherait l'heure d'ouverture avec deux
heures de retard en été.

**Courbe de prévision.** `mini-graph-card` ne trace que l'historique enregistré, jamais le futur.
Pour afficher la courbe prédite dans HA, il faut `apexcharts-card` (HACS) alimentée par la série
complète, exposée sur `/api-meteo/forecast`.

Un bloc Lovelace prêt à coller pour un dashboard Bubble Card se trouve dans
`~/perso/home-assistant/lovelace-micro-climat.yaml`.

**Notification d'anticipation.** L'automatisation HA `ouverture_fenetres_anticipee`
(« Notification : ouvrir les fenêtres bientôt ») prévient 30 minutes avant la bascule prévue,
à partir de `sensor.<prefix>_ouverture_fenetres`. Son déclencheur est un template contenant
`now()`, donc réévalué chaque minute, et qui ne se déclenche qu'au passage de faux à vrai :
une seule notification par bascule.

Elle est le pendant *prédictif* des quatre automatisations « Rue plus froide/chaude que… »
qui, elles, constatent la bascule au moment où elle arrive. Les deux se cumulent donc le même
soir : à surveiller si le nombre de notifications devient gênant. Et comme le capteur reste
indisponible tout l'hiver (voir les limites du modèle hivernal), elle est silencieuse en
saison froide par construction.

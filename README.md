# micro-climat-predict

**micro-climat-predict** est une application conteneurisée conçue pour collecter, stocker et analyser les données micro-climatiques locales (via Home Assistant) et les croiser avec des données météorologiques ouvertes (Open-Meteo) ainsi qu'avec des modèles de positionnement solaire précis. L'objectif final est d'alimenter un moteur de machine learning pour prédire l'évolution thermique intérieure (notamment l'impact des ombres de la rue).

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
- **Ordonnanceur construit localement** (`scheduler/Dockerfile`, Alpine 3.22 + `tzdata`) au lieu
  d'`image: alpine:3.20` avec un `apk add tzdata` dans la commande. Deux raisons : 3.20 est en fin
  de vie depuis le 01/04/2026, et l'`apk add` rendait le service dépendant du réseau **au boot** —
  son échec était avalé par un `|| true` et `crond` repartait en UTC, décalant l'entraînement de
  5 h 30 d'une à deux heures sans une ligne de log. Vérifiable : `docker run --rm --network none
  -e TZ=Europe/Paris micro-climat-predict-cron date +%Z` doit répondre `CEST`/`CET`, jamais `UTC`.
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
locale** (`tzdata` est dans l'image de l'ordonnanceur et `TZ` vient du compose, sinon busybox
raisonnerait en UTC).

### Test sous Docker Desktop / WSL2

Docker Desktop en mode réseau miroir ne joint pas le LAN, donc pas Home Assistant. Contournement :

```bash
python3 scripts/wsl-ha-relay.py <ip-home-assistant>:8123 &        # relais TCP sur l'hôte WSL
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
- La ligne **CO₂** de la page d'accueil est vide sur cette installation : aucun capteur de
  qualité de l'air n'existe dans l'instance HA (constat du 15/09/2026 — 385 entités, zéro en
  `µg/m³` ou en `ppm`, et `/api/config` ne liste que le composant de base `air_quality`). Il
  faut un capteur CO₂ réel, comme dit au premier point ; `CO2_ENTITY` ne pointe aujourd'hui
  sur rien. Les particules, elles, ne passent plus par HA — voir ci-dessous.

### Qualité de l'air extérieur

Les particules du bloc « Qualité de l'air extérieur » viennent de l'**API qualité de l'air
d'Open-Meteo**, pas de Home Assistant. Le web-ui l'interroge directement dans
[`fetch_air_quality()`](web-ui/main.py), en parallèle de la lecture HA, avec un cache mémoire de
15 minutes (l'amont ne publie qu'un point par heure). Aucune clé, aucun compte : il suffit de
`LAT` / `LON` dans le `.env`, déjà présents pour le collecteur et désormais transmis aussi au
web-ui.

Pourquoi pas Home Assistant, alors que le code d'origine lisait `PM25_ENTITY` / `PM10_ENTITY`
(défauts `sensor.atmo_auvergne_rhone_alpes_atmo_pm25` / `_pm10`) — deux noms hérités de l'amont
qui ne correspondaient à aucune intégration installée ici, d'où les `-- µg/m³` :

- l'intégration HACS pour la région est [`sebcaps/atmofrance`](https://github.com/sebcaps/atmofrance),
  qui demande un compte sur le portail de données Atmo France et crée des entités
  `sensor.pm25_<commune>` ;
- mais elle expose un **indice ATMO de 1 (bon) à 6 (extrêmement mauvais)**, pas une
  concentration. Afficher cet indice dans un bloc libellé `µg/m³` aurait été faux, et le
  relibeller aurait changé la nature de l'information affichée.

Le choix retenu (15/09/2026) garde donc les µg/m³, au prix explicite d'une **valeur modélisée
CAMS sur la maille et non mesurée en station**. Le lien « détails » du bloc pointe toujours vers
la dataviz de la station Atmo FR07004, mais l'attribution le dit maintenant : la valeur affichée
est Open-Meteo, la station est là pour recouper.

Les variables `PM25_ENTITY` et `PM10_ENTITY` n'existent plus, ni dans le code ni dans le
`docker-compose.yml` ; elles peuvent être retirées du `.env`.

### Mode saisonnier : évacuer ou faire entrer la chaleur

Le conseil d'aération a un **sens**, et ce sens s'inverse avec la saison. En été on ouvre quand
l'extérieur repasse sous l'intérieur, pour évacuer. D'octobre à avril on cherche l'inverse : le
milieu de journée est le seul moment où l'extérieur dépasse l'intérieur, et c'est là qu'ouvrir
fait entrer de la chaleur gratuite.

Le mode se règle **depuis `/admin`**, section « Mode saisonnier », et vaut « chaud » par défaut.
Deux boutons, pas de calendrier : une règle par mois se trompe sur les canicules de septembre et
les redoux de mars, et une règle sur les données demande un seuil qu'il faudrait régler à
l'aveugle. Le choix tient dans `data/season.json`, **hors de `metrics.db`** : le « Reset Total »
de la même page supprime la base et les modèles, et le réglage de saison n'a aucune raison de
partir avec eux. La bascule vide les caches de prévision au passage, sans quoi le conseil
resterait celui de l'autre saison jusqu'à la collecte suivante, une demi-heure plus tard.

**Deux instants sont désormais publiés, pas un.** L'heure de fermeture existait en creux dans le
code d'origine, jamais exposée. Elle compte plus en saison froide qu'en saison chaude : laisser
ouvert après le croisement rend la chaleur qu'on venait de faire entrer, alors qu'en été on peut
laisser ouvert la nuit entière sans dommage.

Quand l'extérieur est **déjà** favorable, il n'y a pas d'heure d'ouverture à annoncer, seulement
une heure de fermeture. L'entité d'ouverture passe alors à `unknown` avec `creneau_en_cours: true`
en attribut, et l'interface affiche « Fermer à 17:10 » plutôt qu'un créneau complet.

**L'hystérésis dépend de la saison, et ce n'est pas un réglage de confort.** En été l'inversion
du soir vaut plusieurs degrés en une heure : exiger un demi-degré d'écart ne coûte rien. En
automne les deux courbes se frôlent, et cette même marge mange presque tout le créneau. Mesuré
sur Tower le 23/09/2026 : l'extérieur passe au-dessus de l'intérieur de 15h30 à 18h40, trois
heures, mais ne dépasse +0,5 °C que cinq pas de dix minutes de suite là où il en faut six. Le
conseil sautait donc la journée pour désigner le lendemain, au-delà des dix-huit heures
d'horizon, et ne sortait pas du tout. D'où `FAVORABLE_MARGIN_FROID`, à **0,3 °C** par défaut
contre 0,5 en saison chaude (`FAVORABLE_MARGIN_CHAUD`), qui rend le vrai créneau, 15h50 à 18h40.
Le choix n'est pas sur le fil : 0,3, 0,2 et 0,1 donnent le même résultat, c'est un plateau.

La durée de stabilité, elle, reste à six pas dans les deux saisons. C'est le bon bouton à ne
**pas** tourner : à 0,5 °C et quatre pas, la même journée rendait un créneau de cinquante
minutes, ce qui n'est pas ce que dit la courbe.

Le seuil qui gouverne la détection, lui, reste un réglage d'expert : `INT_HOT_THRESHOLD_C`
(23 °C par défaut), naguère codé en dur. Il ne sert qu'à la reconstitution des périodes fenêtres
ouvertes à partir du CO₂, donc à rien tant que le capteur n'est pas là.

**Ce que la bascule répare au passage.** Le détecteur d'ouverture par le CO₂ tenait pour une
aération tout intérieur plus chaud que l'extérieur qui se met à baisser. C'est le bon signe en
été ; en hiver c'est la description de **toutes les nuits**, l'intérieur y étant chauffé et
l'extérieur toujours plus froid. Laissé tel quel, le mode froid aurait marqué des nuits entières
« fenêtres ouvertes », ce qui les aurait exclues de l'ajustement du modèle d'inertie via
`is_fit_ready`, soit exactement les données dont un modèle hivernal a besoin. Les critères de
température sont donc inversés eux aussi. Réserve à connaître : **faute de capteur CO₂ sur cette
installation, la branche froide n'a jamais tourné sur des données réelles.** À vérifier à la pose
de l'Apollo AIR-1, pas avant.

### Intégration Home Assistant

Le projet **pousse** ses prédictions dans HA (`POST /api/states/...`) au lieu d'attendre que HA
vienne les chercher. Aucune ligne à ajouter dans `configuration.yaml`, aucun port à ouvrir : le
trafic ne part que vers HA. C'est le bon compromis quand on n'a pas d'accès shell sur l'instance.

Quatre capteurs sont écrits, tous préfixés par `HA_SENSOR_PREFIX` (`micro_climat` par défaut) :

| Entité | Contenu |
|---|---|
| `sensor.<prefix>_ouverture_fenetres` | heure conseillée d'ouverture (`device_class: timestamp`) |
| `sensor.<prefix>_fermeture_fenetres` | heure conseillée de fermeture, même classe |
| `sensor.<prefix>_interieur_dans_6h` | température intérieure prévue à l'horizon `HA_PUBLISH_HORIZON_HOURS` |
| `sensor.<prefix>_interieur_max_24h` | maximum intérieur prévu sur 24 h, horaire du pic en attribut |

Les deux premiers portent en attribut le `mode_saison` en vigueur, de quoi conditionner une
automatisation sans la dupliquer. Et l'entité d'ouverture porte `creneau_en_cours` : vrai quand
l'extérieur est **déjà** favorable, c'est-à-dire quand l'entité est à `unknown` non pas faute de
conseil, mais parce que les fenêtres devraient déjà être ouvertes. Sans cet attribut les deux
situations seraient indiscernables, et une automatisation qui teste `unknown` ne saurait pas
laquelle elle regarde.

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
(« Notification : ouvrir ou fermer les fenêtres bientôt ») prévient **30 minutes avant
l'ouverture** conseillée et **15 minutes avant la fermeture**, à partir des deux capteurs
d'horodatage. Chaque déclencheur est un template contenant `now()`, donc réévalué chaque minute,
et qui ne se déclenche qu'au passage de faux à vrai : une seule notification par instant. Un
identifiant de déclencheur (`ouverture` / `fermeture`) choisit le texte.

Le sens du message suit le mode saisonnier, lu sur l'attribut `mode_saison` du capteur :
« Ouvrir pour faire entrer la chaleur… Fermer vers 18h30 » en saison froide, « l'extérieur
repasse sous l'intérieur » en saison chaude. Faute d'attribut (les états disparaissent au
redémarrage de HA, trente minutes au plus), le texte retombe sur la saison chaude, comme le
projet. Rendu vérifié par `/api/template` sur les états réels le 23/09/2026 ; la version
précédente est sauvegardée dans `~/perso/home-assistant/backup-2026-09-23/`.

Elle est le pendant *prédictif* des quatre automatisations « Rue plus froide/chaude que… »
qui, elles, constatent la bascule au moment où elle arrive. Les deux se cumulent donc : à
surveiller si le nombre de notifications devient gênant, d'autant que la fermeture en ajoute
une par créneau.

En plein hiver l'extérieur ne dépasse jamais l'intérieur : les capteurs restent alors inconnus
des semaines durant, et l'automatisation muette avec eux. C'est le comportement attendu, pas une
panne : l'aération hivernale d'hygiène relève d'une règle distincte qui n'existe pas encore (P6
du TODO).

## Sondes de santé

Posées le 09/09/2026 ([P2-09](../audit-docker/plan/p2-09-healthchecks.md)) sur les **trois services
web**. `docker ps` affiche désormais *(healthy)* à côté de leurs noms.

```
python3 -c "…urlopen('http://127.0.0.1:8000/openapi.json')"   toutes les 60 s, 3 échecs
```

**Pourquoi `/openapi.json` et pas `/`** : `data-collector` et `ml-engine` n'ont **pas de route
racine** — ils répondent 404, et `urlopen` lève sur un 404. La sonde proposée au départ les aurait
déclarés malades **pour toujours**. Mesuré avant de la poser, pas après.

**Pourquoi pas `/api/status/last-collection` et `/api/status/last-training`**, qui seraient plus
parlantes : elles lisent la base SQLite. Un verrou pendant l'entraînement de 5 h 30 ferait
clignoter la sonde, et une sonde qui crie faux apprend à ignorer le signal.

**`cron` (`mcp-scheduler`) reste sans sonde, exprès.** Il n'expose rien, et ce qui compte pour lui
— l'heure juste — n'est pas testable par une sonde périodique. Un `pgrep crond` dirait « en vie »
alors que le service peut être décalé de deux heures : une sonde qui rassure à tort. Son vrai
problème a été traité autrement (`scheduler/Dockerfile`, Alpine 3.22 + `tzdata` dans l'image).

## Mettre à jour

L'image est **construite ici**, donc `docker compose pull` ne sert à rien : il n'y a pas d'amont à
tirer. Ce qui se met à jour, c'est l'**image de base** et les dépendances — et c'est `--pull` qui
va les chercher. Sans lui, `build` réutilise l'image de base déjà présente et une mise à jour
n'entre jamais.

```bash
cd /chemin/vers/micro-climat-predict
docker compose build --pull
docker compose up -d
```

Vérifier ensuite : `docker ps --filter name=mcp-web-ui` et l'interface sur `http://<hôte>:8730/`.

`diun` ne surveille pas cette image (elle n'existe dans aucun registre) mais il surveille son
**image de base**, à déclarer dans le `watch.yml` de diun.

### Déployer un changement de code, ce qui n'est pas la même chose

Ce qui précède met à jour l'**image de base**. Pour porter une modification du code, `--pull`
est au contraire à éviter : il ferait entrer une nouvelle image de base dans un déploiement
ciblé, donc un changement sans rapport avec le correctif. Ne reconstruire que le service
touché :

```bash
docker compose up -d --build web-ui
```

L'enchaînement par `&&` avec une validation préalable n'est pas cosmétique — si la recette
devient invalide, la reconstruction n'a pas lieu et le conteneur en service reste debout :

```bash
docker compose config -q && docker compose up -d --build web-ui
```

**Deux pièges, si la copie déployée n'est pas un clone de ce dépôt.** Rien n'impose qu'elle en
soit un : un `rsync` ou une copie manuelle sont des installations parfaitement valides.

1. Ne pas supposer un `git pull`. Sur une copie sans `.git`, il échoue en
   `not a git repository` — et comme les commandes d'une boucle de déploiement sont souvent
   indépendantes, le `build` qui suit s'exécute quand même, sur des sources inchangées : il
   réutilise le cache, aucun conteneur n'est recréé, et **rien ne signale que le déploiement
   n'a pas eu lieu**. Vérifier plutôt le résultat sur la page servie.
2. La copie déployée peut porter des retouches locales que ce dépôt n'a pas — une URL en dur
   là où le dépôt met un gabarit, par exemple. Écraser les fichiers en bloc les perdrait
   silencieusement. Comparer avant, et épargner les fichiers qui divergent.

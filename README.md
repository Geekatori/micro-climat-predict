# micro-climat-predict

**micro-climat-predict** est une application conteneurisée conçue pour collecter, stocker et analyser les données micro-climatiques locales (via Home Assistant) et les croiser avec des données météorologiques ouvertes (Open-Meteo) ainsi qu'avec des modèles de positionnement solaire précis. L'objectif final est d'alimenter un moteur de machine learning pour prédire l'évolution thermique intérieure (notamment l'impact des ombres de la rue).

Ce dépôt est un fork de [jmfavreau/micro-climat-predict](https://codeberg.org/jmfavreau/micro-climat-predict)
(AGPL-3.0), adapté à une autre maison : autres capteurs, un CO₂ collecté mais pas encore lu par
le modèle, un poêle à granulés, hébergement sur un NAS. Le code complet de cette version est
publié ici conformément à la licence. Les différences avec l'amont sont listées
[plus bas](#différences-avec-lamont).

| | |
|---|---|
| Services | quatre conteneurs Docker Compose : `data-collector`, `ml-engine`, `web-ui`, `cron` |
| Interface | `http://127.0.0.1:8730` (`/`, `/graphs`, `/admin`, `/logs`), sans authentification ; ouvrable au réseau par `WEB_BIND` |
| Données | SQLite et modèles dans `./data`, sauvegardés avec le dossier du projet |
| Sorties | conseil d'aération (ouverture, fermeture) et prévisions intérieures, publiés dans Home Assistant |
| Configuration | `.env`, modèle dans `.env.example` |

## Je veux…

| … | Aller à |
|---|---|
| installer, démarrer | [`docs/installation.md`](docs/installation.md) |
| mettre à jour, déployer une modification, lancer une action à la main | [`docs/exploitation.md`](docs/exploitation.md) |
| comprendre une erreur, un capteur `unknown` | [`docs/exploitation.md`, « Dépanner »](docs/exploitation.md#dépanner) |
| connaître une variable, un port, une route, une entité publiée | [`docs/reference.md`](docs/reference.md) |
| comprendre le moteur et le conseil d'aération, ses limites | [`docs/architecture.md`](docs/architecture.md) |
| développer, tester une modification | [`docs/developpement.md`](docs/developpement.md) |
| savoir ce qui diffère de l'amont | [`docs/differences-avec-l-amont.md`](docs/differences-avec-l-amont.md) |

## Différences avec l'amont

En bref : entités HA configurables, ports en boucle locale, base dans `./data`, mode saisonnier
avec heure de fermeture, publication des prédictions dans Home Assistant, CO₂ et puissance du
poêle archivés, qualité de l'air par Open-Meteo, déclencheurs en POST, pannes visibles, et
plusieurs corrections. La liste complète, avec le pourquoi de chaque écart :
[`docs/differences-avec-l-amont.md`](docs/differences-avec-l-amont.md).

## Les décisions

Les choix propres à ce fork. Chaque fiche dit quand la rouvrir.

| | Décision |
|---|---|
| [0001](docs/decisions/0001-ports-en-boucle-locale.md) | Les ports sont liés à 127.0.0.1, seule l'interface peut s'ouvrir au réseau |
| [0002](docs/decisions/0002-base-dans-un-dossier-monte.md) | La base SQLite vit dans `./data`, monté depuis le dossier du projet |
| [0003](docs/decisions/0003-restart-always.md) | Les conteneurs sont en `restart: always`, pas `unless-stopped` |
| [0004](docs/decisions/0004-ordonnanceur-construit-avec-tzdata.md) | L'ordonnanceur est une image construite, avec `tzdata` dedans |
| [0005](docs/decisions/0005-sondes-sur-openapi.md) | Les sondes de santé interrogent `/openapi.json` |
| [0006](docs/decisions/0006-publication-ha-par-l-api-rest.md) | Les prédictions sont publiées dans HA par l'API REST, pas par MQTT |
| [0007](docs/decisions/0007-qualite-de-l-air-par-open-meteo.md) | La qualité de l'air vient d'Open-Meteo, pas d'entités HA |
| [0008](docs/decisions/0008-mode-saisonnier.md) | Le conseil d'aération a un mode saisonnier, réglé dans `/admin` |
| [0009](docs/decisions/0009-hysteresis-par-saison.md) | L'hystérésis vaut 0,5 °C en saison chaude, 0,3 °C en saison froide |
| [0010](docs/decisions/0010-etat-courant-sur-la-mesure.md) | L'état courant du conseil se juge sur l'intérieur mesuré, pas sur la simulation |
| [0011](docs/decisions/0011-poele-archive-hors-modele.md) | La puissance du poêle est archivée, sans être lue par le modèle |
| [0012](docs/decisions/0012-co2-collecte-hors-modele.md) | Le CO₂ est collecté, mais le modèle ne le lit pas (`CO2_MODELE=0`) |
| [0013](docs/decisions/0013-simulation-depuis-le-debut-des-donnees.md) | La simulation d'inertie part du début des données |
| [0014](docs/decisions/0014-declencheurs-en-post-et-garde-d-origine.md) | Les déclencheurs sont en POST, sous garde d'origine ; le reset total est verrouillé |
| [0015](docs/decisions/0015-les-pannes-se-voient.md) | Les pannes se voient : collecte en 502, entités muettes journalisées, route de fraîcheur |
| [0016](docs/decisions/0016-pas-d-ouverture-soleil-bas-en-saison-froide.md) | En saison froide, pas d'ouverture tant que le soleil est sous 10° |
| [0017](docs/decisions/0017-inertie-recalee-chaque-jour.md) | Le modèle d'inertie s'ajuste sur des simulations recalées chaque jour sur la mesure |
| [0018](docs/decisions/0018-cible-interieure-la-piece-la-plus-fraiche.md) | La cible intérieure reste la pièce la plus fraîche, et les capteurs publiés le disent |
| [0019](docs/decisions/0019-poele-regime-regule.md) | Poêle en marche, la prévision revient vers le niveau des 24 dernières heures |

## Licence

AGPL-3.0, comme l'amont. Voir `LICENSE`.

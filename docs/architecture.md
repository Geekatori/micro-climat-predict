# micro-climat-predict : architecture

Quatre services Docker Compose, un réseau interne (`meteo_network`), une base SQLite partagée
dans `./data`. Les ports, routes et fichiers sont relevés dans [`reference.md`](reference.md).

## Les services

1. **`data-collector`** (FastAPI) : lit l'historique des capteurs dans Home Assistant et
   l'historique plus les prévisions d'Open-Meteo, consolide le tout au pas de 10 minutes dans
   `metrics.db`. L'historique HA est demandé avec un timeout de 120 s et `no_attributes`.
2. **`ml-engine`** (FastAPI + scikit-learn + scipy) : entraîne un modèle de gradient boosting
   pour l'extérieur, un second pour l'intérieur, et ajuste un modèle d'inertie thermique
   paramétrique. Sert les prévisions et le conseil d'aération.
3. **`web-ui`** (FastAPI + Tailwind + ApexCharts) : tableau de bord, administration, journaux,
   et publication des prédictions dans Home Assistant.
4. **`cron`** (busybox crond, image construite dans `scheduler/`) : collecte à h+08 et h+38,
   publication HA à h+12 et h+42, entraînement à 5 h 30 heure locale.

Seul le web-ui peut être exposé au réseau ; il parle au moteur et au collecteur par le réseau
interne ([décision 0001](decisions/0001-ports-en-boucle-locale.md)).

## Les signaux collectés

- **Températures et humidités** : extérieur (`EXT_ENTITY`, `HUM_ENTITY`) et sondes intérieures.
  `int_temp_min` est le minimum des températures intérieures présentes.
- **CO₂** (`CO2_ENTITY`) : collecté, archivé et affiché ; lu par le modèle seulement si
  `CO2_MODELE=1` ([décision 0012](decisions/0012-co2-collecte-hors-modele.md)).
- **Puissance du poêle** (`stove_power`, en W) : signal en marches, rééchantillonné au maximum
  par pas et prolongé, jamais interpolé ; archivé
  ([décision 0011](decisions/0011-poele-archive-hors-modele.md)), et lu seulement pour savoir
  si le poêle a tourné dans les 24 dernières heures
  ([décision 0019](decisions/0019-poele-regime-regule.md)).
- **Fenêtre ouverte** (`WINDOW_ENTITY`, colonne `window_open`) : un détecteur d'ouverture, en
  marches comme le poêle. Là où il a une valeur, il fait le drapeau de fenêtre ouverte, à la
  place de la détection par le CO₂
  ([décision 0021](decisions/0021-detecteur-d-ouverture-comme-drapeau-de-fenetre.md)).
- **Météo et soleil** : historique et prévisions d'Open-Meteo, course du soleil sur `LAT`/`LON`
  (transmis aussi au `ml-engine`).
- **Qualité de l'air** : lue à la volée par le web-ui chez Open-Meteo, pas archivée
  ([décision 0007](decisions/0007-qualite-de-l-air-par-open-meteo.md)).

Une colonne entièrement NULL sort de SQLite en dtype `object` : le moteur la tolère avant
`interpolate()`.

L'interpolation comble les trous entre deux relevés, jamais après le dernier : les pas de
prévision météo, plus récents que toute mesure, restent sans mesure et n'entrent pas dans
l'entraînement.

Une sonde figée (24 pas identiques) est écartée, puis l'extérieur manquant est rempli par
Open-Meteo pour la simulation et le conseil. Le modèle extérieur, lui, n'apprend que sur la
mesure réelle, gardée avant ce remplissage dans `ext_mesure`.

Le modèle extérieur apprend l'écart entre cette mesure et Open-Meteo, sur les 30 derniers jours,
sans lire la mesure du pas précédent : il corrige tous les pas d'un coup, passé et futur. Dans le
futur, l'écart du dernier relevé s'ajoute et s'éteint en 3 h
([décision 0020](decisions/0020-modele-exterieur-direct-sur-30-jours.md)). Il reste un biais
d'environ +0,4 °C, surtout la nuit.

## Le modèle d'inertie

Le modèle d'inertie est une équation pas à pas : à chaque pas de 10 minutes, l'intérieur se
rapproche de l'extérieur lissé sur 3 h (`a`, majoré par le vent), gagne le rayonnement direct
(`b`) et la hauteur du soleil (`e`), l'occupation par le CO₂ si elle est lue (`d`), et un terme
constant (`c`, perte ou apport). La variation est bornée à ±0,7 °C par pas.

La simulation repart de la mesure chaque jour à minuit UTC ; le futur repart de la dernière
mesure. Les paramètres sont ajustés sur ces journées recalées, sur tout l'historique
([décision 0013](decisions/0013-simulation-depuis-le-debut-des-donnees.md)), à moindres carrés
robustes et dans des bornes qui couvrent une maison réelle
([décision 0017](decisions/0017-inertie-recalee-chaque-jour.md)). L'erreur journalisée à
l'entraînement est donc celle d'une prévision à 0 à 24 h.

Poêle en marche dans les 24 dernières heures, le futur ne suit plus l'équation : il revient de
la dernière mesure vers la moyenne mesurée de ces 24 h, avec une constante de 6 h. Le poêle
tient la maison dans une bande, une chute passive n'arriverait pas
([décision 0019](decisions/0019-poele-regime-regule.md)).
Quand `CO2_MODELE=1`, un détecteur d'ouverture par le CO₂ exclut de l'ajustement les périodes
fenêtres ouvertes ; son critère s'inverse avec la saison, et son seuil « intérieur chaud » est
`INT_HOT_THRESHOLD_C` ([décision 0008](decisions/0008-mode-saisonnier.md)).

## Le conseil d'aération

- **Le sens** dépend du mode saisonnier : en saison chaude on ouvre quand l'extérieur repasse
  sous l'intérieur, en saison froide quand il passe au-dessus. Le mode se règle depuis `/admin`,
  vit dans `data/season.json`, et sa bascule vide les caches de prévision
  ([décision 0008](decisions/0008-mode-saisonnier.md)). Fichier absent : saison chaude, comme
  l'amont ; fichier illisible : saison chaude aussi, mais le journal du moteur le dit.
- **Le pic extérieur** du jour n'est annoncé qu'en saison chaude : en saison froide, il
  n'appelle aucun geste.
- **Deux instants** sont calculés, ouverture puis fermeture, sur un horizon de 18 h. Quand
  l'extérieur est déjà favorable, seule la fermeture est annoncée : l'ouverture vaut `unknown`
  avec `creneau_en_cours: true`.
- **L'état courant** se juge sur l'intérieur mesuré (dernier point de moins d'une heure), pas sur
  la simulation passée. Sans mesure fraîche, on lit le
  premier pas futur, qui repart lui aussi de la dernière mesure
  ([décision 0010](decisions/0010-etat-courant-sur-la-mesure.md)).
- **L'hystérésis** vaut 0,5 °C en saison chaude, 0,3 °C en saison froide ; une bascule n'est
  retenue qu'après six pas consécutifs (une heure) dans les deux saisons
  ([décision 0009](decisions/0009-hysteresis-par-saison.md)).
- **En saison froide**, aucune ouverture tant que le soleil est sous 10°
  ([décision 0016](decisions/0016-pas-d-ouverture-soleil-bas-en-saison-froide.md)).

## La publication dans Home Assistant

Le web-ui pousse quatre capteurs par l'API REST de HA, toutes les 30 minutes : rien à ajouter
dans `configuration.yaml`, aucun port à ouvrir, le trafic ne part que vers HA. Les états vivent
en mémoire dans HA et reviennent à la publication suivante après un redémarrage
([décision 0006](decisions/0006-publication-ha-par-l-api-rest.md)). Les entités sont listées dans
[`reference.md`](reference.md#entités-publiées-dans-home-assistant).

## Limites connues

- **CO₂ collecté, pas encore lu par le modèle** (`CO2_MODELE=0`) : les seuils de détection
  d'ouverture viennent de la maison de l'amont, et marquent des heures de fausses ouvertures en
  saison froide. Les recaler sur quelques semaines de vrais relevés avant d'activer
  ([décision 0012](decisions/0012-co2-collecte-hors-modele.md)).
- Sans détecteur d'ouverture (`WINDOW_ENTITY`) ni CO₂ lu, le modèle d'inertie ne distingue pas
  les périodes fenêtres ouvertes, ce qui dégrade la prévision intérieure en été. Le détecteur ne
  couvre qu'une fenêtre ; son archive commence à sa mise en service, dix jours plus tôt au mieux.
- La branche froide du détecteur CO₂ n'a jamais tourné sur des données réelles.
- En plein hiver l'extérieur ne dépasse jamais l'intérieur : les capteurs d'ouverture et de
  fermeture restent `unknown` des semaines durant. C'est attendu. L'aération d'hygiène
  relèverait d'une règle distincte, non écrite.
- Le modèle ne simule pas le poêle : poêle en marche, la prévision revient vers le niveau des
  24 dernières heures, sans les oscillations de chaque cycle
  ([décision 0019](decisions/0019-poele-regime-regule.md)).
- La cible du modèle intérieur est `int_temp_min`, le minimum des sondes intérieures : poêle en
  marche, c'est le plus souvent la sonde la plus éloignée du poêle. Les capteurs publiés le
  disent ([décision 0018](decisions/0018-cible-interieure-la-piece-la-plus-fraiche.md)). La
  pièce du poêle n'a pas de prévision propre : poêle éteint, son heure de passage sous 18 °C
  se prévoit à 2 h près seulement ([décision 0019](decisions/0019-poele-regime-regule.md)).
- L'heure locale d'affichage est `Europe/Paris`, en dur dans le moteur et l'interface (hérité
  de l'amont).
- Sans identifiant unique, les entités publiées dans HA ne sont ni renommables ni rattachables à
  une pièce ; MQTT lèverait cette limite ([décision 0006](decisions/0006-publication-ha-par-l-api-rest.md)).

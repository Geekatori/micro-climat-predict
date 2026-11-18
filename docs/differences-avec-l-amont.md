# micro-climat-predict : différences avec l'amont

Ce dépôt est un fork de [jmfavreau/micro-climat-predict](https://codeberg.org/jmfavreau/micro-climat-predict)
(AGPL-3.0), adapté à une autre maison. Voici ce qui diffère de l'amont, et pourquoi.

## Configuration et déploiement

- **Entités HA configurables** par `.env` au lieu d'être codées dans `data-collector/main.py`
  ([`reference.md`](reference.md#configuration)).
- **Ports liés à `127.0.0.1`** et déplacés en 8730 à 8732 ; seule l'interface peut s'ouvrir au
  réseau, par `WEB_BIND` ([décision 0001](decisions/0001-ports-en-boucle-locale.md)).
- **SQLite en bind mount `./data`** au lieu d'un volume anonyme : la base suit les sauvegardes du
  dossier ([décision 0002](decisions/0002-base-dans-un-dossier-monte.md)).
- **`restart: always`** au lieu de `unless-stopped`, pour Unraid
  ([décision 0003](decisions/0003-restart-always.md)).
- **Cron d'entraînement** : `/api/train` est en POST, `wget` l'appelait en GET. Il tourne à
  5 h 30 heure locale ; `tzdata` est dans l'image de l'ordonnanceur (`scheduler/Dockerfile`,
  Alpine 3.22) au lieu d'un `apk add` au démarrage
  ([décision 0004](decisions/0004-ordonnanceur-construit-avec-tzdata.md)).
- **Sondes de santé** sur les trois services web (`/openapi.json` toutes les 5 min)
  ([décision 0005](decisions/0005-sondes-sur-openapi.md)).

## Corrections

- **`LAT`/`LON` transmis au `ml-engine`** : l'amont calculait la position du soleil sur ses
  coordonnées par défaut quelle que soit la configuration.
- **Historique HA : timeout 120 s et `no_attributes`** : dix jours sur six entités dépassaient
  les 20 s, en silence.
- **Colonnes vides tolérées** dans le `ml-engine` : une colonne entièrement NULL sort de SQLite
  en dtype `object` et faisait échouer `interpolate()`.
- **Pas de mesure inventée après la dernière** : l'interpolation recopiait la dernière mesure
  sur les pas de prévision météo, et environ 3 h 40 de ces valeurs entraient dans
  l'entraînement comme des relevés.
- **Connexions SQLite toujours refermées** : une écriture qui échouait laissait sa connexion
  ouverte avec sa transaction, et la base restait verrouillée pour les trois services jusqu'au
  redémarrage. Toute connexion passe par `connexion()`, qui valide ou annule puis ferme, et
  attend un verrou 30 s au lieu de 5.
- **Reset total** : supprime les trois fichiers de modèle réellement produits. L'amont ne
  supprimait que `model_int.joblib`, qui n'existe pas.
- **Entraînement possible juste après un reset** : la table `training_logs` n'était créée qu'au
  démarrage du `ml-engine`. Après un reset, la base recréée par le collecteur ne l'avait pas :
  `/api/train` répondait 500 et `/health/fraicheur` restait en 503 jusqu'au redémarrage du
  moteur. Elle est recréée avant chaque écriture et chaque lecture.
- **Le modèle extérieur apprend sur la mesure réelle** : une sonde figée est écartée, puis le
  trou est rempli par Open-Meteo pour la simulation. Le modèle apprenait aussi sur ces lignes,
  avec un écart à Open-Meteo nul, et sa correction se tassait vers Open-Meteo. Sa cible est
  désormais `ext_mesure`, la mesure gardée avant ce remplissage.
- **Modèle extérieur direct, appris sur 30 jours** : il ne relit plus sa propre prévision du pas
  précédent, et se réentraîne sur toute sa fenêtre au lieu des 80 % les plus anciens. La
  prévision surestimait l'extérieur de 1,4 °C en moyenne et annonçait de fausses ouvertures en
  saison froide ([décision 0020](decisions/0020-modele-exterieur-direct-sur-30-jours.md)).
- **Pic extérieur à 0 °C annoncé** : un pic à 0,0 °C était lu comme absent et le message de
  pic disparaissait.
- **`/api/forecast/smart` n'écrit plus dans le cache de simulation** : il travaille sur une
  copie, les autres routes ne voient plus ses prédictions court terme.
- **Simulation d'inertie depuis le début des données**, et non depuis le premier relevé de CO₂
  ([décision 0013](decisions/0013-simulation-depuis-le-debut-des-donnees.md)).
- **Modèle d'inertie ajusté sur des journées recalées** : la simulation repart de la mesure
  chaque jour, et les paramètres sont cherchés par moindres carrés robustes dans des bornes
  larges, au lieu d'une grille dont le couplage à l'extérieur plafonnait à plus de 400 jours de
  constante de temps. La simulation libre de l'amont dérivait de plusieurs degrés et gelait les
  paramètres ([décision 0017](decisions/0017-inertie-recalee-chaque-jour.md)).
- **Poêle en marche, prévision ramenée au niveau des 24 dernières heures** au lieu de la chute
  passive du modèle ([décision 0019](decisions/0019-poele-regime-regule.md)).
- **État courant du conseil jugé sur la mesure**, pas sur la simulation du passé
  ([décision 0010](decisions/0010-etat-courant-sur-la-mesure.md)).

## Fonctions ajoutées

- **Mode saisonnier** et **heure de fermeture** : le conseil d'aération s'inverse en saison
  froide ([décision 0008](decisions/0008-mode-saisonnier.md)), avec une hystérésis propre à
  chaque saison ([décision 0009](decisions/0009-hysteresis-par-saison.md)) et pas d'ouverture
  soleil bas en saison froide ([décision 0016](decisions/0016-pas-d-ouverture-soleil-bas-en-saison-froide.md)).
- **Publication des prédictions dans HA** ([décision 0006](decisions/0006-publication-ha-par-l-api-rest.md)).
  Les capteurs intérieurs nomment leur cible, la pièce la plus fraîche
  ([décision 0018](decisions/0018-cible-interieure-la-piece-la-plus-fraiche.md)).
- **CO₂ collecté, archivé et affiché**, lu par le modèle seulement si `CO2_MODELE=1`
  ([décision 0012](decisions/0012-co2-collecte-hors-modele.md)).
- **Puissance du poêle archivée** (`stove_power`, en W) pour un futur modèle hivernal
  ([décision 0011](decisions/0011-poele-archive-hors-modele.md)).
- **Qualité de l'air par Open-Meteo** au lieu de `PM25_ENTITY` / `PM10_ENTITY`
  ([décision 0007](decisions/0007-qualite-de-l-air-par-open-meteo.md)).

## Sécurité et pannes visibles

- **Déclencheurs en POST** : `/trigger-*` et `/api/backfill-co2` étaient des GET, qu'un lien
  préchargé ou une balise `<img>` suffisait à lancer ; garde d'origine sur tous les POST ; reset
  total désactivé sauf `ALLOW_RESET=1`, avec saisie de `SUPPRIMER`
  ([décision 0014](decisions/0014-declencheurs-en-post-et-garde-d-origine.md)).
- **Pannes visibles** : le web-ui journalise chaque entité HA injoignable ou non numérique au
  lieu d'afficher `--` sans trace ; `/api/collect` répond 502 quand HA ne fournit rien ; route
  `/health/fraicheur` ; ping Healthchecks facultatif après chaque collecte, `HC_COLLECT_URL`
  ([décision 0015](decisions/0015-les-pannes-se-voient.md)).

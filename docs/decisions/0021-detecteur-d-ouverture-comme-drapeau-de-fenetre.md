# 0021. Un détecteur d'ouverture donne le drapeau de fenêtre ouverte, à la place du CO₂

- **Date** : 18/11/2026
- **État** : acceptée
- **Rouvrir si** : une autre fenêtre pèse sur la cible intérieure (il faudrait combiner plusieurs
  détecteurs), ou le drapeau sert un jour au conseil d'aération.

## Contexte

Le modèle d'inertie sait déjà quoi faire d'une fenêtre ouverte : la simulation repart de la
mesure à chaque pas ouvert et au pas qui suit la fermeture, et l'ajustement écarte ces pas. Mais
le drapeau ne venait que de la détection par le CO₂, coupée ([décision 0012](0012-co2-collecte-hors-modele.md)) :
le modèle ne voyait jamais de fenêtre ouverte, et apprenait les aérations comme des pertes de la
maison.

La maison a un détecteur d'ouverture sur la fenêtre du salon, dans HA, que le collecteur ne lisait
pas. L'enregistreur de HA ne garde que dix jours ; relevé le 18/11/2026, ce détecteur n'a noté
aucune ouverture depuis le 13/11, ceux des autres pièces en notent bien : il fonctionne, la
fenêtre est restée fermée.

## Décision

- **`WINDOW_ENTITY`** (vide par défaut) nomme un `binary_sensor` d'ouverture. Le collecteur
  l'archive dans la colonne `window_open`, `1` ouverte, `0` fermée ; `unavailable` et `unknown`
  sont ignorés comme un relevé illisible.
- C'est un signal en marches, traité comme la puissance du poêle : chaque pas de 10 min vaut le
  maximum de ses relevés (une ouverture de trois minutes marque son pas), prolongé jusqu'au
  relevé suivant, jamais interpolé, ni par le collecteur ni par le moteur.
- **Là où la colonne a une valeur, elle fait le drapeau `window_open_flag`**, à la place de la
  détection par le CO₂. Ailleurs (avant l'archive, détecteur muet, futur), rien ne change.

## Options écartées

| Option | Pourquoi pas ici |
|---|---|
| Activer la détection par le CO₂ | ses seuils ne sont pas recalés sur cette maison ; la décision 0012 tient |
| Combiner plusieurs détecteurs | la cible est la pièce la plus fraîche, et une seule fenêtre a un détecteur dans les pièces mesurées ; une liste d'entités compliquerait la lecture de l'historique pour un cas qui n'existe pas |
| Une route de reprise comme `/api/backfill-co2` | `/api/collect?days=10` relit déjà dix jours d'historique, tout ce que HA garde |
| Se servir du drapeau dans le conseil (ne pas annoncer une ouverture déjà faite) | autre sujet ; à ouvrir si les notifications agacent |

## Conséquences

- L'archive commence au déploiement, ou dix jours plus tôt par une collecte `days=10`. Tant que
  la fenêtre reste fermée, la prévision ne change pas.
- Fenêtre ouverte, ces pas sortent de l'ajustement du modèle d'inertie, et la simulation repart
  de la mesure à la fermeture. La courbe passée affiche le modèle à gradient pendant l'ouverture
  (`/validation`, mode 3).
- Le CO₂ peut toujours être activé (`CO2_MODELE=1`) : le détecteur l'emporte là où il a une
  valeur.

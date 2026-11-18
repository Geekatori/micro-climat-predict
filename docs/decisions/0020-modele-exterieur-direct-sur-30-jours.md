# 0020. Le modèle extérieur corrige Open-Meteo sans relire sa propre prévision, appris sur 30 jours

- **Date** : 18/11/2026
- **État** : acceptée
- **Rouvrir si** : la sonde extérieure change de place ou d'abri (son écart à Open-Meteo jour et
  nuit changera), ou le biais rejoué repasse au-dessus de +1 °C sur une saison.

## Contexte

Le modèle extérieur de l'amont apprend l'écart entre la mesure et Open-Meteo. Il lisait parmi
ses entrées la mesure du pas précédent (`ext_temp_lag1`) : dans le futur, il relisait sa propre
prévision, pas après pas, sur 36 h. Il était entraîné sur les 80 % les plus anciens de
l'historique, sans réentraînement sur le tout.

Relevé le 18/11/2026 sur la copie de la base, 67 départs toutes les 12 h du 15/10 au 17/11,
erreur sur 0 à 24 h :

- la prévision publiée surestimait l'extérieur de 1,37 °C en moyenne (erreur absolue 1,52 °C),
  plus qu'Open-Meteo brut (1,33 °C, biais -0,26) ;
- la sonde lit environ 1,1 °C de plus qu'Open-Meteo la nuit et 1,1 °C de moins à midi. Relue en
  boucle, la correction de nuit se propageait au jour ;
- en saison froide, ce biais suffit à annoncer une ouverture : l'extérieur prévu dépasse
  l'intérieur l'après-midi alors que la mesure n'y arrive pas. La seule ouverture notifiée à
  tort sur la période, le 09/11, venait de là.

## Décision

- **Le modèle extérieur ne lit plus la mesure précédente** : il corrige Open-Meteo à partir de
  la prévision et de ses valeurs des heures et des jours précédents, de l'humidité, du vent et
  de la position du soleil, d'un seul coup sur tous les pas (`FEATURES_EXT`).
- **Le premier écart du futur est rappelé** : l'écart entre la dernière mesure et la prévision
  à cet instant s'ajoute au futur et s'éteint avec une constante de 3 h (`EXT_RAPPEL_H`).
- **Il apprend sur les 30 derniers jours de mesure** (`EXT_FENETRE_JOURS`), évalue sa RMSE sur
  les 20 % les plus récents, puis se réentraîne sur toute la fenêtre avant d'être enregistré.
- Un modèle enregistré de l'ancien format (14 entrées) est ignoré jusqu'à l'entraînement
  suivant : la simulation garde alors Open-Meteo brut pour l'extérieur.

Rejoué sur les mêmes 67 départs :

| Variante | Erreur absolue 0 à 24 h | Biais | À +1 h |
|---|---|---|---|
| Déployée (récursive, 80 %) | 1,52 | +1,37 | 1,47 |
| Open-Meteo brut | 1,33 | -0,26 | |
| Récursive, réentraînée sur tout | 0,99 | +0,57 | |
| Directe, tout l'historique | 0,93 | +0,55 | |
| Directe, tout l'historique, rappel 3 h | 0,88 | | |
| **Directe, 30 jours, rappel 3 h** | **0,74** | **+0,42** | **0,36** |

## Options écartées

| Option | Pourquoi pas ici |
|---|---|
| Garder la lecture de la mesure précédente, réentraîner sur tout | corrige le plus gros du biais, mais reste derrière le modèle direct (0,99 contre 0,93 à historique égal) |
| Fenêtre de 14 ou 7 jours | biais plus faible (+0,18, -0,11) mais erreur plus grande (0,80, 0,83) : trop peu de nuits froides pour apprendre l'écart de la sonde |
| Profil horaire moyen de l'écart à Open-Meteo | 1,05 à 1,21 : l'écart dépend du ciel et du vent plus que de l'heure seule |
| Tout l'historique pondéré par l'ancienneté (demi-vie 5, 10 ou 20 jours) | 0,80 à 0,85, sans gain sur la fenêtre de 30 jours, plus simple à lire |

## Conséquences

- Rejoué sur le conseil d'aération (saison froide, départs de 06h à 14h UTC, ouvertures
  annoncées dans les 18 h) : les vrais créneaux des 10 et 11/11 restent annoncés, la fausse
  ouverture du 09/11 disparaît. Restent trois jours limites (15/10, 16/10, 27/10) : la veille et
  l'avant-veille des deux premiers avaient de vrais créneaux, le 27/10 trois pas favorables.
- Il reste un biais d'environ +0,4 °C, surtout la nuit.
- Après le déploiement, un entraînement à la main est nécessaire : jusque-là, l'extérieur
  prévu est Open-Meteo brut.
- La courbe passée du modèle extérieur (graphes, `/validation`) est celle du modèle direct,
  appris sur ces mêmes jours : elle flatte l'erreur affichée sur les 30 derniers jours. La
  `rmse_ext` de l'entraînement, elle, est mesurée sur des jours que le modèle n'a pas vus.

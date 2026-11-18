# 0017. Le modèle d'inertie s'ajuste sur des simulations recalées chaque jour

- **Date** : 18/11/2026
- **État** : acceptée
- **Rouvrir si** : le modèle apprend le poêle (la chauffe changera ce qu'il faut mesurer), ou la
  prévision à 24 h cesse de battre la persistance hors chauffe.

## Contexte

L'ajustement de l'amont simulait l'intérieur librement depuis le début des données, puis
cherchait les paramètres dans une grille de 3⁵ points affinée par Nelder-Mead, en ne comptant que
les pas où la simulation restait à moins de 2,5 °C de la mesure.

Relevé le 18/11/2026 sur trois mois de données :

- la simulation libre avait dérivé jusqu'à -12,6 °C pour un intérieur mesuré à 19 °C ;
- plus aucun pas postérieur au 22/10 n'entrait dans le score : quatorze entraînements de suite
  ont rendu les mêmes paramètres au bit près ;
- les paramètres étaient en butée de grille. `a` plafonnait à 1,6e-5 par pas, soit une constante
  de temps de plus de 400 jours, quand les nuits sans chauffage mesurent environ 100 h. Toute la
  perte passait par le terme constant `c`, -0,078 °C/h quel que soit le froid dehors.

## Décision

- **La simulation repart de la mesure chaque jour à minuit UTC** (`RECALAGE_PAS`, 144 pas), et
  aussi au premier pas mesuré et pendant les fenêtres ouvertes. Le futur repart toujours de la
  dernière mesure.
- **L'ajustement porte sur ces journées recalées**, sur tout le passé, à moindres carrés robustes
  (`least_squares`, perte `soft_l1`, échelle 0,5 °C), avec des bornes larges : `a` de 1e-5 à
  2e-2 par pas (constante de temps de 8 h à plus d'un an), `c` de -0,05 à 0,05 (perte ou apport
  constant). Trois départs pour `a`. `d` (CO₂) n'est ajusté que si le CO₂ est lu.
- L'entraînement journalise et renvoie l'erreur absolue moyenne de ces journées
  (`mae_int_std`), et `rmse_int_std` devient une vraie RMSE.

## Options écartées

| Option | Pourquoi pas ici |
|---|---|
| Garder la grille en élargissant ses bornes | 3⁵ simulations par entraînement, et un pas de grille trop grossier sur quatre ordres de grandeur |
| Ajuster sur les 14 ou 30 derniers jours | rejoué semaine par semaine : 14 jours rend un `a` instable, 30 jours ne fait pas mieux que tout le passé |
| Recalage toutes les 6 h | les capteurs publiés regardent jusqu'à 24 h ; un horizon plus court flatte le modèle sans servir la publication |
| Retirer les heures de chauffe du score | relève de l'apprentissage du poêle, chantier suivant ([décision 0011](0011-poele-archive-hors-modele.md)) |

## Conséquences

Rejoué sur la copie de la base du 18/11, chaque semaine prédite avec des paramètres appris sur
les seules données antérieures (erreur absolue moyenne sur 0 à 24 h) :

| Semaine | Anciens paramètres | Persistance | Recalé, tout le passé |
|---|---|---|---|
| 01/10 | 0,30 | 0,26 | 0,26 |
| 08/10 | 0,49 | 0,43 | 0,35 |
| 15/10 | 0,49 | 0,49 | 0,42 |
| 22/10 (poêle) | 0,78 | 0,55 | 0,70 |
| 29/10 (poêle) | 0,81 | 0,61 | 0,82 |
| 05/11 (poêle) | 0,74 | 0,66 | 0,64 |
| 12/11 (poêle) | 1,34 | 1,07 | 1,16 |

- Hors chauffe, le modèle bat la persistance ; poêle en marche, il reste derrière elle. Seul un
  modèle qui connaît le poêle peut combler cet écart.
- Les paramètres bougent de nouveau d'un jour à l'autre. Sur trois mois : constante de temps
  d'environ 230 h, `c` proche de zéro, gains solaires divisés par deux.
- L'entraînement complet passe à environ 1,5 s.
- La courbe passée du modèle d'inertie (graphes, `/validation`) suit la mesure à un jour près,
  au lieu de dériver : son erreur affichée est celle d'une prévision à 0 à 24 h.
- Le conseil d'aération change peu. Rejoué sur dix journées : mêmes ouvertures sur les vrais
  créneaux, plus de fausse ouverture le 16/11. Les heures de fermeture tardives (01h10 au lieu
  de 16h30 le 10/11) viennent du modèle extérieur, qui prévoit 2 à 3 °C de trop le soir.
- Elle précise la [décision 0013](0013-simulation-depuis-le-debut-des-donnees.md) sans la
  remplacer : l'ajustement porte toujours sur tout l'historique.
- La condition de réouverture de la [décision 0010](0010-etat-courant-sur-la-mesure.md) est
  remplie (la simulation du passé ne dérive plus), mais elle tient : une mesure de moins d'une
  heure reste plus sûre qu'une simulation recalée jusqu'à 24 h plus tôt.

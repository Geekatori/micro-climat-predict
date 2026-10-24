# 0016. En saison froide, pas d'ouverture tant que le soleil est sous 10°

- **Date** : 15/10/2026
- **État** : acceptée
- **Rouvrir si** : un vrai créneau est perdu à cause du seuil, ou les simulations cessent de
  dériver en soirée.

## Contexte

En saison froide, on ouvre pour faire entrer un air réchauffé par le soleil. Soleil bas ou
couché, l'extérieur baisse, et un « croisement » prévu ne vient que des dérives des deux
simulations : des ouvertures étaient annoncées à 20 h ou 22 h en octobre 2026.

## Décision

En saison froide, aucune ouverture n'est retenue tant que la hauteur du soleil est sous
`SUN_MIN_ELEVATION_FROID` (10° par défaut, lu dans l'environnement du moteur, absent du compose).
À 10°, les vrais créneaux mesurés de fin septembre et d'octobre sont gardés.

## Options écartées

| Option | Pourquoi pas ici |
|---|---|
| Laisser le conseil tel quel | ouvertures annoncées le soir |

## Conséquences

- Le seuil ne touche pas la saison chaude.
- Pour le changer, ajouter la variable à l'environnement du `ml-engine` dans le compose.

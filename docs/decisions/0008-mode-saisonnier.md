# 0008. Le conseil d'aération a un mode saisonnier, réglé dans `/admin`

- **Date** : 23/09/2026
- **État** : acceptée
- **Rouvrir si** : le mode doit basculer seul (par la température ou la date), ou une troisième
  saison apparaît.

## Contexte

L'amont ne connaissait que l'été : ouvrir quand l'extérieur repasse sous l'intérieur, pour
évacuer la chaleur. En saison froide, on ouvre au contraire pour faire entrer un air réchauffé
par le soleil, quand l'extérieur passe au-dessus de l'intérieur.

## Décision

- Deux modes, « chaud » (par défaut) et « froid ». Le sens du conseil s'inverse avec le mode.
- Le mode se règle depuis `/admin` et vit dans `data/season.json`, hors de `metrics.db`, pour
  survivre au reset total. Ce n'est pas une variable d'environnement. La bascule vide les caches
  de prévision.
- Le détecteur d'ouverture par le CO₂ s'inverse aussi. Son critère d'été (intérieur plus chaud
  que l'extérieur et qui baisse) décrit toutes les nuits d'hiver, et aurait exclu de
  l'ajustement les données dont un modèle hivernal a besoin.
- Deux instants sont calculés, ouverture puis fermeture (l'amont ne donnait que l'ouverture).

## Options écartées

| Option | Pourquoi pas ici |
|---|---|
| Variable d'environnement | un changement de saison demanderait de recréer le conteneur |
| Mode rangé dans `metrics.db` | effacé par le reset total |

## Conséquences

- La branche froide du détecteur CO₂ n'a jamais tourné sur des données réelles : le modèle ne lit
  pas le CO₂, voir [0012](0012-co2-collecte-hors-modele.md).
- La marge du conseil dépend aussi de la saison, voir [0009](0009-hysteresis-par-saison.md).

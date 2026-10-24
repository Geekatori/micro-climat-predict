# 0009. L'hystérésis du conseil vaut 0,5 °C en saison chaude, 0,3 °C en saison froide

- **Date** : 23/09/2026
- **État** : acceptée
- **Rouvrir si** : un créneau réel est encore perdu ou un conseil clignote, rejoué sur les
  données de la maison.

## Contexte

Sans hystérésis autour du croisement des deux courbes, un frôlement ferait clignoter le conseil
d'un pas à l'autre. En été, l'inversion du soir vaut plusieurs degrés en une heure : un
demi-degré ne coûte rien. En automne, les deux courbes se frôlent : à 0,5 °C, un créneau réel de
trois heures ne tenait pas six pas consécutifs, et le conseil sautait au lendemain, hors de
l'horizon de 18 h.

## Décision

0,5 °C en saison chaude, 0,3 °C en saison froide (`FAVORABLE_MARGIN_CHAUD`,
`FAVORABLE_MARGIN_FROID`). À 0,3 °C le créneau d'automne est rendu entier ; 0,2 et 0,1 donnent le
même. La durée de stabilité reste à six pas (une heure) dans les deux saisons.

## Options écartées

| Option | Pourquoi pas ici |
|---|---|
| 0,5 °C toute l'année | perd les créneaux d'automne |
| 0,2 ou 0,1 °C en saison froide | même créneau qu'à 0,3, avec moins de marge contre le clignotement |
| Raccourcir la stabilité | laisserait passer les creux passagers |

## Conséquences

- Les deux valeurs se règlent dans `.env` sans toucher au code.

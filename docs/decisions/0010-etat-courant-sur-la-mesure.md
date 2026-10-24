# 0010. L'état courant du conseil se juge sur l'intérieur mesuré, pas sur la simulation

- **Date** : 28/09/2026, complétée le 30/09/2026 (repli sur le premier pas futur) et le
  15/10/2026 (hystérésis sur l'état courant)
- **État** : acceptée
- **Rouvrir si** : la simulation du passé cesse de dériver de la mesure, ou la sonde intérieure
  rapporte assez souvent pour qu'une mesure soit toujours fraîche.

## Contexte

Pour dire si l'on est déjà dans un créneau favorable, l'amont comparait l'extérieur mesuré à la
simulation d'intérieur du passé. Cette simulation dérive de plusieurs degrés sous la mesure,
alors que le futur repart de la dernière mesure : « pas encore favorable » au dernier point
passé, « favorable » dès le premier pas futur. Une ouverture était donc annoncée au pas suivant
à chaque publication.

## Décision

- L'état courant se juge sur `int_temp_min` mesuré, si le dernier point a moins d'une heure.
- Sans mesure fraîche, on lit le premier pas futur, qui repart lui aussi de la dernière mesure,
  et non la simulation passée.
- Hystérésis sur l'état courant : on entre dans le créneau à la marge
  ([0009](0009-hysteresis-par-saison.md)), on n'en sort qu'en repassant le croisement.
- Quand l'extérieur est déjà favorable, seule la fermeture est annoncée : l'ouverture vaut
  `unknown` avec `creneau_en_cours: true`.

## Options écartées

| Option | Pourquoi pas ici |
|---|---|
| Simulation du passé (amont) | dérive de plusieurs degrés, annonce une ouverture à chaque passage |

## Conséquences

- L'heure publiée peut encore osciller d'un pas d'une publication à l'autre : côté HA, une
  notification tirée de ces capteurs demande un anti-rebond (voir
  [`exploitation.md`](../exploitation.md#brancher-une-notification-dans-home-assistant)).

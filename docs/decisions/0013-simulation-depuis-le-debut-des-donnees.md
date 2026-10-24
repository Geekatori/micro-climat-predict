# 0013. La simulation d'inertie part du début des données, pas du premier relevé de CO₂

- **Date** : 15/10/2026
- **État** : acceptée
- **Rouvrir si** : le modèle d'inertie change de forme, ou une source arrivée tard doit borner la
  fenêtre d'ajustement.

## Contexte

Chez l'amont, la simulation d'inertie démarrait au premier relevé de CO₂. Brancher un capteur
de CO₂ réduisait donc l'ajustement aux jours suivants. Rejoué : simulation démarrant au 08/10
au lieu du 24/08, terme solaire `e` tombé à zéro.

## Décision

La simulation d'inertie démarre au début des données, CO₂ présent ou non.

## Options écartées

| Option | Pourquoi pas ici |
|---|---|
| Démarrer au premier relevé de CO₂ (amont) | perd des semaines d'historique, et le terme solaire avec |

## Conséquences

- Brancher un nouveau capteur ne réduit plus la fenêtre d'ajustement.

# 0012. Le CO₂ est collecté, mais le modèle ne le lit pas (`CO2_MODELE=0`)

- **Date** : 15/10/2026
- **État** : acceptée, complétée par la [décision 0021](0021-detecteur-d-ouverture-comme-drapeau-de-fenetre.md) (18/11/2026)
- **Rouvrir si** : quelques semaines de vrais relevés de CO₂ ont permis de recaler les seuils de
  détection d'ouverture sur cette maison.

## Contexte

Chez l'amont, le modèle d'inertie détecte les fenêtres ouvertes par le CO₂, avec des seuils
calés sur sa maison. Rejoué le 15/10/2026 sur la base réelle, avec une semaine de CO₂
**synthétique** vers 450 ppm (le niveau mesuré au salon ; le capteur n'est collecté que depuis le
15/10) : en saison froide, le critère « CO₂ sous 700 ppm, extérieur plus chaud, intérieur qui
monte » marque 58 pas (près de 10 h) « fenêtres ouvertes » sans ouverture réelle.

## Décision

Le CO₂ est collecté dès que `CO2_ENTITY` est renseigné, archivé et affiché. Le modèle d'inertie
ne le lit que si `CO2_MODELE=1` ; le défaut est `0`.

## Options écartées

| Option | Pourquoi pas ici |
|---|---|
| Activer le détecteur tel quel | des heures de fausses ouvertures en saison froide |
| Ne pas collecter le CO₂ | il faut des semaines de vrais relevés pour recaler les seuils |

## Conséquences

- Tant que le CO₂ n'est pas lu, pas de détection d'ouverture : le modèle d'inertie ne distingue
  pas les périodes fenêtres ouvertes, ce qui dégrade la prévision intérieure en été. Un
  détecteur d'ouverture y pourvoit depuis la décision 0021.

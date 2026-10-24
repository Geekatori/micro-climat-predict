# 0007. La qualité de l'air vient d'Open-Meteo, pas d'entités Home Assistant

- **Date** : 15/09/2026
- **État** : acceptée
- **Rouvrir si** : un capteur de particules mesure en µg/m³ à proximité et remonte dans HA.

## Contexte

L'amont lisait PM2.5 et PM10 dans des entités HA (`PM25_ENTITY`, `PM10_ENTITY`). Cette maison
n'a pas de capteur de particules, et les intégrations HA Atmo France exposent un indice de 1 à
6, pas une concentration en µg/m³.

## Décision

La page d'accueil lit PM2.5 et PM10 dans l'API qualité de l'air d'Open-Meteo
(`fetch_air_quality()` dans `web-ui/main.py`), sur `LAT`/`LON`, avec un cache de 15 min et sans
clé. `PM25_ENTITY` et `PM10_ENTITY` disparaissent.

## Options écartées

| Option | Pourquoi pas ici |
|---|---|
| Entités HA (amont) | pas de capteur ici |
| Intégration Atmo France | un indice de 1 à 6, pas une concentration |

## Conséquences

- C'est une valeur modélisée CAMS sur la maille, pas une mesure en station.

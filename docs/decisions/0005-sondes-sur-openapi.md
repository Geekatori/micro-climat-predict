# 0005. Les sondes de santé interrogent `/openapi.json`

- **Date** : 09/09/2026
- **État** : acceptée
- **Rouvrir si** : les services gagnent une route de santé dédiée qui ne lit pas SQLite.

## Contexte

Les trois services FastAPI n'avaient pas de sonde. Les images `python:3.11-slim` n'ont ni
`curl` ni `wget`.

## Décision

Une sonde commune (bloc `x-healthcheck` du compose), en Python, interroge
`http://127.0.0.1:8000/openapi.json` toutes les 60 s. La réponse prouve que uvicorn a chargé
l'application avec ses routes.

## Options écartées

| Option | Pourquoi pas ici |
|---|---|
| `/` | le collecteur et le moteur n'ont pas de route racine, et `urlopen` lève sur un 404 |
| `/api/status/*` | ces routes lisent SQLite et clignoteraient pendant l'entraînement |

## Conséquences

- La sonde dit que le service répond, pas que les données sont fraîches : c'est le rôle de
  `/health/fraicheur`, voir [0015](0015-les-pannes-se-voient.md).

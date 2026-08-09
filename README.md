# micro-climat-predict

**micro-climat-predict** est une application conteneurisée conçue pour collecter, stocker et analyser les données micro-climatiques locales (via Home Assistant) et les croiser avec des données météorologiques ouvertes (Open-Meteo) ainsi qu'avec des modèles de positionnement solaire précis. L'objectif final est d'alimenter un moteur de machine learning pour prédire l'évolution thermique intérieure (notamment l'impact des ombres de la rue).

## Architecture du Projet

Le projet repose sur une architecture de microservices avec Docker Compose :

1. **`data-collector`** (FastAPI) :
   - Interroge l'API de Home Assistant pour récupérer les températures et humidités intérieures/extérieures.
   - Interroge l'API Open-Meteo pour récupérer l'historique et les prévisions de température, d'humidité et de vitesse du vent.
   - Calcule mathématiquement la position du soleil (élévation et azimut) pour chaque intervalle de temps.
   - Stocke et consolide le tout dans une base de données SQLite unique avec une stratégie de mise à jour glissante.

2. **`ml-engine`** (FastAPI + Scikit-Learn) :
   - Entraîne des modèles de régression (Random Forest) pour anticiper l'évolution thermique.
   - Fournit des endpoints de prévision pour les températures intérieures et extérieures.

3. **`web-ui`** (FastAPI + TailwindCSS + ApexCharts) :
   - Fournit un tableau de bord visuel et interactif avec bascule de vue 24h/7j.
   - Se connecte désormais directement à l'API de Home Assistant pour afficher les courbes en temps réel tout en s'appuyant sur le moteur ML et SQLite pour les prévisions futures.
   - Propose des pages d'administration et de suivi des logs d'opérations.
   - Permet de déclencher manuellement les collectes et les entraînements à la demande.

## Prérequis

- Docker et Docker Compose installés sur votre machine.
- Une instance Home Assistant accessible avec un Token d'accès longue durée (Long-Lived Access Token).

## Configuration

1. Créez un fichier `.env` à la racine du projet en vous basant sur l'exemple ci-dessous :

```env
WEB_PORT=8000
HA_URL=[http://homeassistant.local:8123](http://homeassistant.local:8123)
HA_TOKEN=votre_token_longue_duree_home_assistant
LAT=45.7797
LON=3.0863
```

2. Vérifiez que les identifiants de vos entités de capteurs Home Assistant correspondent à ceux définis dans data-collector/main.py.

## Lancement

Lancez l'ensemble des services avec la commande suivante :

```bash
docker compose up --build -d
```

L'interface web est ensuite accessible sur : http://localhost:8000 (ou le port configuré dans votre compose).

## Licence

Ce projet est sous licence AGPL-3.0 (GNU Affero General Public License v3.0).
Vous êtes libre de l'utiliser, de le modifier et de le distribuer, sous réserve que toute modification ou version réseau dérivée mette également son code source à disposition sous la même licence. Voir le fichier LICENSE pour plus de détails.

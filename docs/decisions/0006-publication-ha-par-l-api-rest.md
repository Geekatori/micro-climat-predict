# 0006. Les prédictions sont publiées dans Home Assistant par l'API REST, pas par MQTT

- **Date** : 04/09/2026
- **État** : acceptée
- **Rouvrir si** : il faut des entités persistantes au redémarrage de HA, renommables ou
  rattachées à une pièce.

## Contexte

Les prévisions et le conseil d'aération ne se voyaient que dans l'interface du projet. Les
avoir dans Home Assistant permet de les afficher et d'en tirer des notifications.

## Décision

Le web-ui pousse quatre capteurs par `POST /api/states/<entity_id>`, avec le jeton déjà utilisé
pour la collecte. Rien à ajouter dans `configuration.yaml`, aucun port à ouvrir : le trafic ne
part que vers HA. Sans donnée exploitable, la publication est sautée plutôt que d'écraser les
états par `unknown`.

## Options écartées

| Option | Pourquoi pas ici |
|---|---|
| MQTT avec découverte automatique | lèverait les deux limites ci-dessous, mais demande un broker et sa configuration |

## Conséquences

- Limites assumées : un état écrit ainsi vit en mémoire dans HA, disparaît à chaque redémarrage
  de HA et revient à la publication suivante ; sans identifiant unique, ces entités ne sont ni
  renommables ni rattachables à une pièce.
- Le détail des entités est dans [`reference.md`](../reference.md#entités-publiées-dans-home-assistant).

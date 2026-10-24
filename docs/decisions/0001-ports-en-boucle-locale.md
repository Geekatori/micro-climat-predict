# 0001. Les ports sont liés à 127.0.0.1, seule l'interface peut s'ouvrir au réseau

- **Date** : 04/09/2026
- **État** : acceptée
- **Rouvrir si** : un service autre que l'interface doit être joint depuis une autre machine, ou
  l'interface reçoit une authentification.

## Contexte

Chez l'amont, les trois services web publiaient leurs ports sur toutes les interfaces. Le
collecteur et le moteur n'ont aucune authentification, l'interface non plus, et `/admin` lance
la collecte, l'entraînement et le reset total.

## Décision

Les ports passent en 8730 (web-ui), 8731 (ml-engine) et 8732 (data-collector), tous liés à
`127.0.0.1`. Seule l'interface peut être ouverte au réseau, en donnant à `WEB_BIND` l'adresse du
serveur. Le moteur et le collecteur restent sur la boucle locale : l'interface et
l'ordonnanceur les joignent par le réseau interne du compose.

## Options écartées

| Option | Pourquoi pas ici |
|---|---|
| Garder les ports de l'amont sur toutes les interfaces | expose deux API sans authentification qui écrivent dans la base |

## Conséquences

- `/admin` n'a aucune authentification : une interface ouverte sur un LAN demande un reverse
  proxy ou un VPN devant.
- Les déclencheurs de l'interface sont protégés autrement, voir
  [0014](0014-declencheurs-en-post-et-garde-d-origine.md).

# 0019. Poêle en marche, la prévision revient vers le niveau des 24 dernières heures

- **Date** : 18/11/2026
- **État** : acceptée
- **Rouvrir si** : le poêle change de pilotage (programmation horaire, consigne déplacée), ou une
  sonde de la pièce chauffée entre dans la cible.

## Contexte

Le modèle d'inertie ne connaît pas le poêle. Poêle en marche, sa prévision à 24 h faisait moins
bien que la persistance de la dernière mesure ([décision 0017](0017-inertie-recalee-chaque-jour.md)).
L'archive couvre 58 cycles depuis le 19/10, ce que la [décision 0011](0011-poele-archive-hors-modele.md)
attendait pour s'en servir.

Ce que disent les mesures :

- le poêle se comporte en thermostat sur la pièce chauffée : il repart vers 17,8 °C et s'arrête
  vers 21 °C, après 4 à 10 h d'arrêt ;
- après un arrêt, l'écart entre la pièce chauffée et la pièce éloignée fond avec une constante
  d'environ 3 h ; la pièce éloignée rend ensuite la chaleur stockée pendant la chauffe (jusqu'à
  -1,8 °C en 6 h après un arrêt du matin, quand le modèle passif prévoyait des gains solaires).

## Décision

- **Quand le poêle a tourné dans les 24 dernières heures** (plus de 5 W sur un pas), le futur
  de la prévision intérieure vaut `M + (T0 - M)·exp(-t / 6 h)` : `M` la moyenne mesurée de la
  cible sur ces 24 h, `T0` la dernière mesure. Sinon, le modèle d'inertie.
- Le passé (graphes, `/validation`) et l'ajustement ne changent pas.

Rejoué sur la copie de la base du 18/11, départs où le poêle avait tourné dans les 24 h,
erreur absolue moyenne sur 0 à 24 h, paramètres déployés :

| Semaine | Modèle d'inertie | Persistance | Retour au niveau des 24 h |
|---|---|---|---|
| 22/10 | 0,68 | 0,55 | 0,48 |
| 29/10 | 0,83 | 0,61 | 0,48 |
| 05/11 | 0,80 | 0,79 | 0,79 |
| 12/11 | 1,11 | 1,03 | 0,91 |

## Options écartées

| Option | Pourquoi pas ici |
|---|---|
| Masquer les heures de chauffe à l'ajustement | rejoué : la prévision publiée perd de 0,05 à 0,15 °C. Elle ignore le poêle à venir, et l'ajustement non masqué compense la chauffe en moyenne |
| Terme de chauffe `h·poêle`, le futur au taux de marche des 24 ou 48 dernières heures | rejoué : à égalité avec le modèle sans chauffe, toujours derrière la persistance |
| Scénario "poêle éteint" : heure où la pièce chauffée passera sous 18 °C | rejoué sur 58 arrêts : 1,4 à 2,5 h d'erreur, toujours en retard, et une simple courbe moyenne fait aussi bien que les modèles à deux pièces. Le poêle repartant de lui-même vers 17,8 °C, ce serait surtout l'heure de son prochain allumage |
| Simuler le thermostat dans le futur | demande un modèle de la pièce chauffée à deux nœuds et une masse cachée ; le gain sur le retour au niveau n'est pas démontré |

## Conséquences

- Les deux capteurs intérieurs publiés suivent le niveau tenu par le poêle au lieu d'une chute
  passive qui n'arrive pas.
- Le conseil d'aération change peu. Rejoué sur dix journées de chauffe : vrais créneaux des 10
  et 11/11 identiques (poêle éteint depuis plus de 24 h), quatre fausses ouvertures du 14/11
  supprimées, plus de fermeture annoncée à 01h00 le 06/11.
- Le jour où le poêle est arrêté pour de bon, la prévision tient le niveau des 24 h jusqu'à ce
  que le dernier pas de marche sorte de la fenêtre, puis repasse au modèle d'inertie.
- Le moteur interpole `stove_power` dans les trous, ce que le collecteur évitait (décision
  0011) ; sans effet ici, où seul compte "plus de 5 W au moins une fois en 24 h".

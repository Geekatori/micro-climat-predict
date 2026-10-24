## Documentation

Rangée selon la méthode de documentation de l'auteur du fork (`methode-documentation.md`, hors
de ce dépôt). Lire la carte (`README.md`) avant de chercher, et écrire au bon endroit plutôt
que d'ajouter un fichier.

| Où | Contenu |
| --- | --- |
| `README.md` | la carte et la vitrine du fork : présentation, lien vers l'amont, tableau « Je veux… », liste des décisions, licence |
| `docs/exploitation.md` | les gestes : mettre à jour l'image, déployer un changement de code, lancer une action à la main, changer de saison, reset total, vérifier, notification HA, dépanner, sauvegarde |
| `docs/reference.md` | services et ports, variables de `.env`, planification, fichiers de `data/`, routes, entités publiées dans HA, route de fraîcheur, qualité de l'air |
| `docs/installation.md` | configurer, démarrer, ouvrir l'interface au réseau, Unraid, supervision |
| `docs/architecture.md` | les services, les signaux collectés, le modèle d'inertie, le conseil d'aération, la publication HA, les limites connues |
| `docs/developpement.md` | tester une modification, Docker Desktop et WSL2, règles du code |
| `docs/differences-avec-l-amont.md` | chaque écart avec l'amont, avec son lien vers la décision |
| `docs/decisions/` | une fiche par décision, numérotée ; une nouvelle décision prend le numéro suivant et sa ligne dans le README ; une décision remplacée garde sa fiche (état « remplacée par ») |
| `docs/wip/` | local, ignoré par git |

- Un document versionné décrit l'état actuel. L'historique est dans git ; l'ancien README unique
  est au commit `920cbae` et avant.
- **Le dépôt est public** (fork AGPL-3.0, publié sur GitHub). Aucune adresse IP du réseau local,
  aucun nom de machine, chemin d'exploitation ou secret dans un fichier suivi. Les commandes de
  la doc s'écrivent pour « le serveur qui héberge la pile », sans le nommer.
- `TODO.md` et `LOCAL.md` sont ignorés par git : ce sont des notes locales. Rien de leur contenu
  ne se recopie dans un fichier suivi.
- Le `docker-compose.yml` renvoie à `docs/differences-avec-l-amont.md` dans son en-tête : ne pas
  renommer ce fichier sans changer le commentaire. Les commentaires du compose portent aussi des
  décisions (0001, 0003, 0004, 0005, 0012) : les garder alignés avec `docs/decisions/`.
- Un nouvel écart avec l'amont prend sa ligne dans `docs/differences-avec-l-amont.md`.
- Rédaction en français, sans tiret long.

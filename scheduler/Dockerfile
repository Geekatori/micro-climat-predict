# Ordonnanceur du fork : busybox crond, et rien d'autre.
#
# Deux raisons d'avoir un Dockerfile plutot qu'`image: alpine:3.20` dans le compose :
#   - 3.20 est en fin de vie depuis le 01/04/2026, plus aucun correctif de securite ;
#   - `apk add tzdata` au demarrage rendait le service dependant du reseau AU BOOT du
#     NAS, c'est-a-dire au moment ou le reseau n'est pas encore forcement la. En cas
#     d'echec, le `|| true` l'avalait en silence et crond raisonnait en UTC :
#     l'entrainement de 5h30 partait a 7h30 en ete, 6h30 en hiver, et les collectes
#     horaires se decalaient d'autant. Aucune ligne de log ne le disait.
#
# tzdata est donc dans l'image. Le fuseau lui-meme vient de TZ, passe par le compose.
FROM alpine:3.22
RUN apk add --no-cache tzdata

# Ordonnanceur : busybox crond, avec tzdata dans l'image.
#
# Image construite plutôt qu'`image: alpine` suivi d'un `apk add tzdata` au démarrage :
# cet apk dépendait du réseau au boot du serveur, son échec était avalé par `|| true`
# et crond tournait en UTC sans rien dire. Le fuseau vient de TZ, passé par le compose.
FROM alpine:3.22
RUN apk add --no-cache tzdata

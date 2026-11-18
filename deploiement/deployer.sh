#!/usr/bin/env bash
# Envoie l'application sur le serveur et la (re)démarre. À lancer depuis la racine du projet, après dcb.pipeline.
# Variables attendues : DCB_SSH (ex. root@serveur), DCB_CLE (clé SSH), DCB_HOTE (nom de domaine servi).
set -euo pipefail
: "${DCB_SSH:?}" "${DCB_CLE:?}" "${DCB_HOTE:?}"
SSH=(ssh -i "$DCB_CLE" -o IdentitiesOnly=yes -o BatchMode=yes "$DCB_SSH")
CIBLE=/docker/dcb

"${SSH[@]}" "mkdir -p $CIBLE/deploiement/entrepot"
# seuls le code, les paramètres, le référentiel, les tables finales et l'interface partent :
# ni data/raw, ni le Data Pack, ni .git, ni le suivi
tar -czf - --exclude='__pycache__' --exclude='node_modules' --exclude='interface/dist'   config.yaml src referentiel data/processed outputs/tableau_de_bord outputs/web interface deploiement/Dockerfile   deploiement/docker-compose.yml deploiement/requirements_service.txt deploiement/deployer.sh deploiement/sauvegarder.sh   | "${SSH[@]}" "rm -rf $CIBLE/src $CIBLE/data/processed $CIBLE/outputs $CIBLE/interface $CIBLE/referentiel && tar -xzf - -C $CIBLE"
# premier déploiement : entrepôt initial et jeton d'administration (aléatoire, reste sur le serveur)
if [ -f data/entrepot/entrepot.sqlite ] && ! "${SSH[@]}" "test -f $CIBLE/deploiement/entrepot/entrepot.sqlite"; then
  "${SSH[@]}" "cat > $CIBLE/deploiement/entrepot/entrepot.sqlite" < data/entrepot/entrepot.sqlite
fi
"${SSH[@]}" "cd $CIBLE/deploiement && chown -R 10001:10001 entrepot 2>/dev/null; test -f .env || (umask 077 && echo DCB_JETON_ADMIN=\$(head -c 24 /dev/urandom | base64 | tr -d '/+=') > .env)"
"${SSH[@]}" "cd $CIBLE && DCB_HOTE=$DCB_HOTE docker compose -f deploiement/docker-compose.yml up -d --build 2>&1 | tail -5"

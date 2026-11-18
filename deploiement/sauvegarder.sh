#!/usr/bin/env bash
# Sauvegarde de l'entrepôt des données (SQLite), sans arrêter le service.
#
# À lancer sur le serveur, depuis le dossier deploiement/ :   bash sauvegarder.sh [dossier_des_sauvegardes]
# Exemple de planification quotidienne à 2 h (crontab -e) :
#   0 2 * * * cd /docker/dcb/deploiement && bash sauvegarder.sh /var/backups/yennenga >> /var/log/yennenga_sauvegarde.log 2>&1
#
# Restauration : arrêter le service (docker compose stop), copier la sauvegarde choisie sur
# entrepot/entrepot.sqlite, puis docker compose start. Chaque lot importé reste visible dans son journal.
set -euo pipefail

DOSSIER="${1:-./sauvegardes}"
GARDER="${DCB_SAUVEGARDES_GARDEES:-30}"
mkdir -p "$DOSSIER"
CIBLE="$DOSSIER/entrepot_$(date +%Y%m%d_%H%M%S).sqlite"

# l'API de sauvegarde de SQLite produit une copie cohérente même pendant une écriture
docker compose exec -T dcb python -c "
import sqlite3, sys
src = sqlite3.connect('/app/data/entrepot/entrepot.sqlite')
dst = sqlite3.connect('/tmp/sauvegarde.sqlite')
src.backup(dst); dst.close(); src.close()
ok = sqlite3.connect('/tmp/sauvegarde.sqlite').execute('PRAGMA integrity_check').fetchone()[0]
sys.exit(0 if ok == 'ok' else 1)
"
docker compose exec -T dcb cat /tmp/sauvegarde.sqlite > "$CIBLE"
docker compose exec -T dcb rm -f /tmp/sauvegarde.sqlite
gzip -f "$CIBLE"
echo "sauvegarde : $CIBLE.gz ($(du -h "$CIBLE.gz" | cut -f1))"

# rotation : on garde les $GARDER plus récentes
ls -1t "$DOSSIER"/entrepot_*.sqlite.gz 2>/dev/null | tail -n +"$((GARDER + 1))" | xargs -r rm -f --

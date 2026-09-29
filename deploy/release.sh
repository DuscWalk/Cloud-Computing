#!/usr/bin/env bash
set -euo pipefail

revision="${1:-}"
[[ "$revision" =~ ^[0-9a-f]{40}$ ]] || { echo 'Expected a full commit SHA'; exit 1; }
[[ -f .env ]] || { echo 'Create the production .env on ECS first'; exit 1; }
[[ "$(id -un)" == 'duscwalk' ]] || { echo 'Deploy as duscwalk'; exit 1; }

exec 9>.deploy.lock
flock -n 9 || { echo 'Another deployment is running'; exit 1; }
umask 077
mkdir -p backups
export BACKEND_IMAGE="ghcr.io/duscwalk/cloud-computing-api:$revision"
export FRONTEND_IMAGE="ghcr.io/duscwalk/cloud-computing-web:$revision"

docker compose pull api migrate cleanup web
if docker compose ps --status running --services | grep -qx mysql; then
    backup="backups/pre-$revision-$(date -u +%Y%m%dT%H%M%SZ).sql"
    docker compose exec -T mysql sh -c \
        'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqldump -uroot --single-transaction --no-tablespaces attendance' > "$backup"
    test -s "$backup"
fi
docker compose up -d --no-build --wait --wait-timeout 180 mysql redis
docker compose run --rm --no-deps migrate python -c \
    'from app.config import get_settings; assert get_settings().env == "production", "Set APP_ENV=production"'
# Run migrations exactly once per release, including when the migrate container already exited.
docker compose run --rm --no-deps migrate
docker compose up -d --no-build --no-deps api cleanup web
for attempt in {1..30}; do
    if docker compose exec -T web wget -q -O - http://localhost/api/health/ready; then
        # Keep later maintenance commands on the deployed images, without relying on
        # environment variables that disappear when this SSH session ends.
        python3 - <<'PY'
import os
from pathlib import Path

path = Path('.env')
keys = ('BACKEND_IMAGE', 'FRONTEND_IMAGE')
lines = [line for line in path.read_text().splitlines() if not line.startswith(tuple(k + '=' for k in keys))]
lines.extend(f'{key}={os.environ[key]}' for key in keys)
temporary = path.with_name('.env.next')
temporary.write_text('\n'.join(lines) + '\n')
temporary.chmod(0o600)
temporary.replace(path)
PY
        printf '\n%s\n' "$revision" > .deployed-revision
        echo 'Deployment healthy'
        exit 0
    fi
    sleep 2
done
echo 'Readiness failed. Inspect logs; database was backed up. No automatic schema downgrade.'
exit 1

#!/usr/bin/env bash
set -euo pipefail
umask 022

# Only the dedicated server checkout is reset. Data and secrets live beside it.
cd /opt/stockpi/app
exec 9>/opt/stockpi/deploy.lock
flock -n 9 || { echo 'Another deployment is running.' >&2; exit 1; }
test -d .git
test -x /opt/stockpi/venv/bin/python
test -r /opt/stockpi/env/stockpi.env

git fetch --prune origin
# CI supplies the revision whose checks passed. Refuse if main advanced meanwhile.
expected_revision=${1:-}
if [[ -n "$expected_revision" ]]; then
    [[ "$expected_revision" =~ ^[0-9a-f]{40}$ ]] || { echo 'Invalid deployment revision.' >&2; exit 1; }
    [[ "$(git rev-parse origin/main)" == "$expected_revision" ]] || {
        echo 'main changed after CI started; deploy from the newer workflow run.' >&2
        exit 1
    }
fi
git reset --hard origin/main
/opt/stockpi/venv/bin/python -m pip install -r backend/requirements.txt
(
    cd frontend
    npm ci
    npm run build
)

# Do not overwrite the installed Nginx config: Certbot may have updated it.
sudo -n /usr/sbin/nginx -t
sudo -n /usr/bin/systemctl restart stockpi-backend
curl --fail --silent --show-error --retry 15 --retry-delay 2 --retry-connrefused \
    --max-time 5 http://127.0.0.1:8000/health
sudo -n /usr/bin/systemctl reload nginx
printf '\nDeployed commit: '
git rev-parse HEAD

# Stockpi on Ubuntu Lightsail (no Docker)

This prepares one Ubuntu 24.04 server for `https://stockpi.vkotian.com`.
No AWS SDK, container runtime, or live broker execution is involved.

## Layout

```text
/opt/stockpi/
├── app/                   # Git checkout, disposable deployment code
│   ├── backend/
│   └── frontend/dist/     # Built React files served by Nginx
├── venv/                  # Python virtual environment
├── env/stockpi.env        # Server-only configuration and secrets
├── data/
│   ├── stockpi.db         # SQLite database
│   ├── stockpi.zerodha-session.json  # Owner-only session credential
│   └── backtests/         # Isolated historical run databases
└── backups/               # Database backups, not part of deployment
```

Git resets only `app/`. The environment, database, session file, and backtests
survive deployment. Do not copy development databases or credentials into Git.

## 1. Server packages

Attach a Lightsail static public IP. Allow inbound TCP 80 and 443; allow SSH
(22) for your administrators and deployment runner. Do not open port 8000.

```bash
sudo apt update
sudo apt install -y nginx git python3-venv python3-pip curl ca-certificates \
  build-essential sqlite3 util-linux certbot python3-certbot-nginx
```

Install Node.js **22.12 or newer in the 22.x line** system-wide (Vite 7 needs a
modern Node version). For example, use the official NodeSource installer:

```bash
curl -fsSL https://deb.nodesource.com/setup_22.x -o /tmp/nodesource_setup.sh
# Inspect the downloaded installer before running it with sudo.
sudo bash /tmp/nodesource_setup.sh
sudo apt install -y nodejs
node --version
npm --version
```

Node/npm must be available in a non-interactive SSH session, not only through a
shell-specific version manager. Python 3.12 is supplied by Ubuntu 24.04.

## 2. Directories and source

```bash
sudo install -d -o ubuntu -g ubuntu -m 755 /opt/stockpi
sudo install -d -o ubuntu -g ubuntu -m 700 /opt/stockpi/env /opt/stockpi/data /opt/stockpi/backups
sudo -u ubuntu git clone --branch main https://github.com/vinay-kotian/market-signal.git /opt/stockpi/app
sudo -u ubuntu python3 -m venv /opt/stockpi/venv
```

The `main` branch must contain these deployment files before the first deploy.
The current development branch is not deployed automatically. If the repository
is private, configure a read-only GitHub deploy key for the server's ubuntu user
and clone via SSH. Verify GitHub's host key before recording it in known_hosts;
`git fetch origin` must work without interactive prompts.

Nginx's www-data user needs directory traversal access through `/opt/stockpi/app`
and read access to `frontend/dist`; keep checkout directories at 755 and public
build files readable. Keep `env/`, `data/`, and `backups/` at 700.

## 3. Environment file

```bash
sudo install -o ubuntu -g ubuntu -m 600 /opt/stockpi/app/deploy/.env.example /opt/stockpi/env/stockpi.env
sudo -u ubuntu nano /opt/stockpi/env/stockpi.env
```

Replace API-key/secret placeholders only on the server. Start with SIMULATED to
verify deployment, then set MARKET_DATA_MODE=ZERODHA when ready. Keep
EXECUTION_MODE=PAPER. Do not also configure a conflicting TRADE_MODE.

Required production values:

```dotenv
DATABASE_PATH=/opt/stockpi/data/stockpi.db
EXECUTION_MODE=PAPER
ZERODHA_REDIRECT_URL=https://stockpi.vkotian.com/api/zerodha/callback
FRONTEND_URL=https://stockpi.vkotian.com
```

This is a systemd EnvironmentFile: use `KEY=value`, not `export KEY=value`.
Systemd loads it on start/restart; `.env` files in the repository aren't loaded.
The database parent must already exist and be writable by ubuntu. Without
DATABASE_PATH, local development still uses `backend/levels.sqlite3`.

Register the exact HTTPS callback above in Kite's developer console. The app
preserves `/api` in the login link and cookie path; Nginx strips `/api` before
forwarding the request. Login cookies are Secure in production. Nginx access
logs omit query strings so callback tokens are not recorded there.

## 4. Install systemd and Nginx

```bash
sudo install -m 644 /opt/stockpi/app/deploy/systemd/stockpi-backend.service /etc/systemd/system/stockpi-backend.service
sudo systemctl daemon-reload
sudo systemctl enable stockpi-backend
sudo install -m 644 /opt/stockpi/app/deploy/nginx/stockpi.conf /etc/nginx/sites-available/stockpi
sudo ln -sfn /etc/nginx/sites-available/stockpi /etc/nginx/sites-enabled/stockpi
sudo nginx -t
sudo systemctl enable nginx
sudo systemctl start nginx
```

No certificates or SSL paths are present in the supplied Nginx file. Keep the
installed file after Certbot edits it; deployment deliberately does not overwrite
it. When changing service/config files later, install them explicitly, run
`systemctl daemon-reload` / `nginx -t`, and restart/reload as appropriate.

The deployment script runs as ubuntu and needs passwordless permission for only
these commands (Lightsail's default ubuntu account may already have sudo):

```sudoers
ubuntu ALL=(root) NOPASSWD: /usr/sbin/nginx -t, /usr/bin/systemctl restart stockpi-backend, /usr/bin/systemctl reload nginx
```

If needed, add that rule with `sudo visudo -f /etc/sudoers.d/stockpi-deploy`.
Do not run the deployment script as root.

## 5. First deployment and HTTPS

```bash
bash /opt/stockpi/app/deploy/scripts/deploy.sh
curl --fail http://127.0.0.1:8000/health
curl --fail -H 'Host: stockpi.vkotian.com' http://127.0.0.1/api/health
```

Create a DNS A record for `stockpi.vkotian.com` pointing to the Lightsail static
IP. Only publish an AAAA record if IPv6 is configured and reachable. Once DNS
and HTTP work, install HTTPS:

```bash
sudo certbot --nginx -d stockpi.vkotian.com
sudo certbot renew --dry-run
curl --fail https://stockpi.vkotian.com/api/health
```

Certbot updates the installed Nginx config with certificates and HTTPS redirect.
Verify `/connection` loads the SPA and `/api/connection` returns JSON, then test
Connect Zerodha in the browser. Keep one Uvicorn worker: connection state,
subscriptions, and strategy history are process-local. The service trusts
forwarded headers only from Nginx on 127.0.0.1.

The current application has no user access controls for its trading/configuration
APIs. Restrict site access to intended users (for example with Nginx access
controls) before exposing it broadly. PAPER-only execution does not make those
APIs private. Keep the browser login/callback accessible to the intended user.

## 6. GitHub Actions

`.github/workflows/deploy.yml` tests backend/frontend, builds React, and then
SSHs to Lightsail on **push to main**, or a manual workflow_dispatch run on main.
The deploy job uses `needs: test`, so failed checks prevent SSH deployment.
A manually selected non-main branch runs checks only; its deployment is skipped.
CI passes its tested commit ID to deploy.sh. The script verifies origin/main
still matches that commit before resetting; if main advanced, use the newer run.
Deploys are serialized; a running deployment is not cancelled by a newer push.

Create a GitHub environment named `production`, restricted to the main branch,
and add these environment secrets:

- `LIGHTSAIL_HOST`: server static IP or SSH hostname (without a URL scheme).
- `LIGHTSAIL_USER`: SSH login user, normally `ubuntu` for this server layout.
  A different user needs equivalent checkout/venv access and the documented sudo permissions.
- `LIGHTSAIL_SSH_KEY`: dedicated private SSH key whose public key is in
  `/home/ubuntu/.ssh/authorized_keys`.
- `LIGHTSAIL_KNOWN_HOSTS`: verified SSH known_hosts entry for that exact host.
  Check the fingerprint independently using the Lightsail console. CI does not
  trust an unverified runtime ssh-keyscan result.

### Create the deployment SSH key

On your trusted workstation, create a dedicated key for this deployment:

```bash
ssh-keygen -t ed25519 -C stockpi-github-actions -f ~/.ssh/stockpi_actions -N ''
```

The unattended key has no passphrase; protect the private file and store its
contents only in LIGHTSAIL_SSH_KEY. Never commit it. Add the **public** file
`~/.ssh/stockpi_actions.pub` as a new line in the server user's
`~/.ssh/authorized_keys` using your existing administration connection.
Do not overwrite other authorized keys. Permissions should be 700 on `.ssh`
and 600 on `authorized_keys`.

For host verification, use the Lightsail console to obtain the server's ED25519
host fingerprint:

```bash
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

On your workstation, collect the candidate host key and compare its fingerprint
with that console result (replace HOST with LIGHTSAIL_HOST):

```bash
ssh-keyscan -t ed25519 HOST > /tmp/stockpi_known_hosts
ssh-keygen -lf /tmp/stockpi_known_hosts
```

Only after they match, put that known_hosts line in LIGHTSAIL_KNOWN_HOSTS. This
extra value pins the server identity; it is public host-key data, not a production
application secret. Test the key without deploying:

```bash
ssh -i ~/.ssh/stockpi_actions -o IdentitiesOnly=yes -o BatchMode=yes \
  -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/tmp/stockpi_known_hosts \
  ubuntu@HOST 'test -x /opt/stockpi/app/deploy/scripts/deploy.sh'
```

### Run the workflow manually

Once the workflow is on the repository's default branch, open GitHub → Actions
→ Test and deploy Stockpi → Run workflow → select **main**. Watch the test job,
then the deploy job. This is a real deployment, not a dry run. A test failure
skips deployment. Any protection rules on the single production environment also
apply. Confirm the deployed commit in the job log and visit `/api/health`.

### Troubleshoot deployment failures

- **Backend/frontend test failure:** inspect the failing test step; run the same
  commands locally, fix, and push. Deployment is correctly skipped.
- **Missing secret:** check all four names in the production environment and
  confirm the environment permits main. Never echo secret values into logs.
- **SSH timeout:** check LIGHTSAIL_HOST, port 22, instance status, and firewall
  access from GitHub-hosted runners.
- **Permission denied (publickey):** check LIGHTSAIL_USER, the installed public
  key, directory permissions, and that LIGHTSAIL_SSH_KEY contains the complete
  matching private key, including its BEGIN/END lines.
- **Host key verification failed:** verify the new fingerprint independently
  before updating LIGHTSAIL_KNOWN_HOSTS. Do not disable verification.
- **git fetch denied:** fix the separate server-to-GitHub credentials for origin.
- **sudo requires a password:** apply the narrow sudoers rule above for the
  configured deployment user. CI cannot respond to password prompts.
- **main changed after CI started:** run the newer successful main workflow.
- **npm/python missing:** install them system-wide / at the documented venv path;
  non-interactive SSH doesn't load your terminal's version-manager setup.
- **Health check or restart failure:** use `journalctl -u stockpi-backend`, check
  the server environment file and data-directory permissions, and run `nginx -t`.

Zerodha secrets stay in the server environment file, not GitHub Actions. The
GitHub-to-server SSH key and server-to-GitHub read-only deploy key are separate.
Test SSH reachability from the deployment runner; its source IP may differ from
your workstation. No server credentials are required for CI's mocked tests.

The script locks out simultaneous manual deploys, fetches and resets the dedicated
checkout to origin/main, installs requirements, runs npm ci/build, tests Nginx,
restarts FastAPI, waits for health, and reloads Nginx. It never runs git clean or
removes the external database. Do not edit code directly in this checkout:
`git reset --hard` intentionally discards tracked changes there.

This is a simple in-place deployment, not atomic/zero-downtime release management.
A failed dependency/build step leaves the previous backend process running but
may leave the checkout/build partially updated. A failed restart may leave it
unavailable; inspect logs and redeploy a fix. No automatic rollback is claimed.
Dependencies are installed from the repository; npm uses its committed lockfile,
while Python currently uses the existing unpinned requirements file.

## Operations and backups

```bash
sudo systemctl status stockpi-backend nginx
sudo journalctl -u stockpi-backend -n 100 --no-pager
sudo journalctl -u stockpi-backend -f
sudo tail -f /var/log/nginx/stockpi.error.log
sudo systemctl restart stockpi-backend
sudo nginx -t
sudo systemctl reload nginx
```

Before deployment/schema changes, take a consistent SQLite backup (not a raw
copy of a live database):

```bash
sqlite3 /opt/stockpi/data/stockpi.db ".backup '/opt/stockpi/backups/stockpi-before-deploy.db'"
chmod 600 /opt/stockpi/backups/stockpi-before-deploy.db
```

Keep backups off the instance as well, protect them, and test restoration.
Deployments do not touch or restore backups automatically. Session files are
credentials; do not publish them with frontend files or debug output.

References: [Nginx proxy_pass](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_pass),
[Uvicorn deployment](https://www.uvicorn.org/deployment/),
[Certbot](https://certbot.eff.org/instructions?ws=nginx&os=pip),
[GitHub Actions secrets](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets).

## Browser WebSocket upgrade (existing HTTPS installations)

The application now serves `/ws/market`. The repository Nginx config includes
its upgrade proxy; the deployment script intentionally does not overwrite your
installed Certbot configuration. On an existing server, edit:

```bash
sudo nano /etc/nginx/sites-available/stockpi
```

Copy only the `location /ws/ { ... }` block from
`/opt/stockpi/app/deploy/nginx/stockpi.conf` into the HTTPS server block for
`stockpi.vkotian.com`. Preserve Certbot's certificate paths, HTTPS redirects,
React fallback and `/api/` proxy. The /ws proxy must retain its full path
(`proxy_pass http://127.0.0.1:8000;`, without a trailing slash).

```bash
sudo nginx -t
sudo systemctl reload nginx
```

Keep one backend worker. The same Nginx site access restrictions must cover
`/ws/` as well as `/api/`. Chrome's Network → WS should show a 101 response for
`wss://stockpi.vkotian.com/ws/market`. A 200 HTML response means the location
block is missing; 502 means the backend cannot be reached. See
[the live data audit](../docs/live-data-flow.md) for event/reconnect verification.

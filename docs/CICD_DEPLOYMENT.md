# CI/CD Deployment

This project deploys automatically when code is merged to `main` or `master`.

## Flow

1. Pull requests to `development`, `main`, or `master` run tests.
2. Pushes to `main` or `master` run tests.
3. If tests pass, GitHub Actions syncs the repository to the server over SSH.
4. The server installs dependencies into a Python virtualenv and restarts Uvicorn.

The deployment keeps `.env` and SQLite data on the server. They are not overwritten by CI/CD.
The app runs from `/opt/market-signal/.venv` and listens on `127.0.0.1:8000`.

## One-Time Server Setup

Install Python runtime tools on the server:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git rsync nginx certbot python3-certbot-nginx
```

Create the deploy directory:

```bash
sudo mkdir -p /opt/market-signal
sudo chown -R "$USER:$USER" /opt/market-signal
```

After the first deploy, edit the server-side `.env`:

```bash
nano /opt/market-signal/.env
```

Keep these defaults until you are ready for live trading:

```env
TRADING_MODE=PAPER
ENABLE_LIVE_TRADING=false
```

## GitHub Secrets

Add these repository secrets in GitHub:

```text
DEPLOY_HOST=your.server.ip.or.domain
DEPLOY_USER=ubuntu
DEPLOY_SSH_KEY=private SSH key that can log in as DEPLOY_USER
```

Optional:

```text
DEPLOY_PORT=22
DEPLOY_PATH=/opt/market-signal
```

## Process Management

CI/CD restarts the app with:

```bash
nohup .venv/bin/uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Runtime files are stored under:

```text
/opt/market-signal/logs/uvicorn.log
/opt/market-signal/run/uvicorn.pid
/opt/market-signal/data/market_signal.db
```

Check the app on the server:

```bash
curl http://127.0.0.1:8000/health
tail -f /opt/market-signal/logs/uvicorn.log
```

## Nginx Reverse Proxy

The app listens only on `127.0.0.1:8000`. Put Nginx or Caddy in front of it.

Example Nginx site:

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable HTTPS:

```bash
sudo certbot --nginx -d your-domain.com
```

## Zerodha Callback

Set the Zerodha developer callback URL to:

```text
https://your-domain.com/zerodha/callback
```

Then set the same value in `/opt/market-signal/.env`:

```env
KITE_REDIRECT_URL=https://your-domain.com/zerodha/callback
FRONTEND_URL=https://your-domain.com
CORS_ORIGINS=https://your-domain.com
```

# CI/CD Deployment

This project deploys automatically when code is merged to `main` or `master`.

## Flow

1. Pull requests to `development`, `main`, or `master` run tests.
2. Pushes to `main` or `master` run tests.
3. If tests pass, GitHub Actions syncs the repository to the server over SSH.
4. The server rebuilds and restarts the app with Docker Compose.

The deployment keeps `.env` and SQLite data on the server. They are not overwritten by CI/CD.

## One-Time Server Setup

Install Docker on the server:

```bash
sudo apt update
sudo apt install -y ca-certificates curl git rsync
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo tee /etc/apt/keyrings/docker.asc >/dev/null
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
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

## Nginx Reverse Proxy

The Docker Compose file exposes FastAPI only on `127.0.0.1:8000`. Put Nginx or Caddy in front of it.

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
sudo apt install -y nginx certbot python3-certbot-nginx
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

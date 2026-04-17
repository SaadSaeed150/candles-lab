# Server Setup & Deployment Guide

Reproduce the full Candles Lab (Paper Trading Simulation System) on a fresh server.

---

## 1. System Requirements

| Component        | Version / Spec                        |
|------------------|---------------------------------------|
| **OS**           | Ubuntu 22.04+ (or any modern Linux)   |
| **Python**       | 3.11.x                                |
| **Node.js**      | 22.x LTS (npm 10.x)                  |
| **PostgreSQL**   | 15+ (with optional TimescaleDB 2.x extension) |
| **Redis**        | 7.x                                  |
| **Git**          | 2.x                                  |

### Hardware (minimum for light workloads)

- 2 vCPUs
- 4 GB RAM (8 GB recommended — Celery workers + Daphne + Next.js)
- 40 GB disk

---

## 2. Install System Dependencies

```bash
sudo apt update && sudo apt upgrade -y

# Core tools
sudo apt install -y build-essential git curl wget software-properties-common

# Python 3.11
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt install -y python3.11 python3.11-venv python3.11-dev

# PostgreSQL 15
sudo apt install -y postgresql-15 postgresql-client-15

# (Optional) TimescaleDB — hypertables for time-series data
# Follow: https://docs.timescale.com/install/latest/self-hosted/installation-linux/
# After install, add to postgresql.conf:
#   shared_preload_libraries = 'timescaledb'
# Then: sudo systemctl restart postgresql

# Redis
sudo apt install -y redis-server
sudo systemctl enable redis-server

# Node.js 22 LTS
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs
```

---

## 3. Create the PostgreSQL Database

```bash
sudo -u postgres psql <<SQL
CREATE USER trading_user WITH PASSWORD 'CHANGE_ME_STRONG_PASSWORD';
CREATE DATABASE trading_db OWNER trading_user;
GRANT ALL PRIVILEGES ON DATABASE trading_db TO trading_user;

-- Only if TimescaleDB is installed:
\c trading_db
CREATE EXTENSION IF NOT EXISTS timescaledb;
SQL
```

---

## 4. Clone the Repository

```bash
cd /opt   # or wherever you host applications
git clone <YOUR_REPO_URL> candles-lab
cd candles-lab
```

---

## 5. Python Backend Setup

### 5.1 Virtual environment & dependencies

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 5.2 Full Python dependency list (from `requirements.txt`)

| Category             | Packages                                                                 |
|----------------------|--------------------------------------------------------------------------|
| Django core          | `django>=5.0,<6.0`, `djangorestframework>=3.15,<4.0`, `django-cors-headers>=4.3,<5.0` |
| Database             | `psycopg[binary]>=3.1,<4.0`                                             |
| Cache / broker       | `redis>=5.0,<6.0`                                                       |
| Async / WebSocket    | `channels>=4.0,<5.0`, `channels-redis>=4.2,<5.0`, `daphne>=4.1,<5.0`   |
| Background tasks     | `celery>=5.4,<6.0`, `django-celery-beat>=2.6,<3.0`, `django-celery-results>=2.5,<3.0` |
| Auth                 | `djangorestframework-simplejwt>=5.3,<6.0`                               |
| Exchange connectors  | `python-binance>=1.0.19,<2.0`, `alpaca-py>=0.30,<1.0`, `websockets>=13.0,<14.0` |
| Data / analysis      | `numpy>=1.26,<3.0`, `pandas>=2.2,<3.0`                                  |
| Testing              | `pytest`, `pytest-django`, `pytest-asyncio`, `pytest-cov`, `factory-boy`, `responses`, `aioresponses` |
| Linting              | `ruff>=0.4,<1.0`                                                        |

---

## 6. Environment Variables

Copy the template and fill in real values:

```bash
cp .env.example .env
```

> **Important:** The application reads env vars via `os.environ.get()`. The `.env` file is **not** auto-loaded by the app. You must either:
> - `export` each variable, or
> - Source the file: `set -a && source .env && set +a` before running any process, or
> - Use a process manager (systemd `EnvironmentFile=`, supervisor, etc.)

### Complete variable reference

| Variable | Default | Description |
|----------|---------|-------------|
| `DJANGO_SECRET_KEY` | insecure placeholder | **Must change in production.** Generate with `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"` |
| `DJANGO_DEBUG` | `True` | Set to `False` in production |
| `DJANGO_ALLOWED_HOSTS` | `*` | Comma-separated hostnames, e.g. `yourdomain.com,www.yourdomain.com` |
| `POSTGRES_DB` | `trading_db` | Database name |
| `POSTGRES_USER` | `postgres` | Database user |
| `POSTGRES_PASSWORD` | `postgres` | Database password |
| `POSTGRES_HOST` | `localhost` | Database host |
| `POSTGRES_PORT` | `5432` | Database port |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL (cache + Channels) |
| `CELERY_BROKER_URL` | same as `REDIS_URL` | Celery message broker |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:3000,...` | Comma-separated origins for CORS |
| `USE_SQLITE` | _(unset)_ | Set to `true` to force SQLite (dev only) |
| **Exchange API keys** | | |
| `BINANCE_API_KEY` | _(empty)_ | Binance API key |
| `BINANCE_API_SECRET` | _(empty)_ | Binance API secret |
| `ALPACA_API_KEY` | _(empty)_ | Alpaca API key |
| `ALPACA_API_SECRET` | _(empty)_ | Alpaca API secret |
| `ALPACA_BASE_URL` | `https://paper-api.alpaca.markets` | Alpaca endpoint (paper or live) |
| **Data collection** | | |
| `TRADING_SYMBOLS` | `BTCUSDT,ETHUSDT,...` (10 pairs) | Crypto symbols to track |
| `TRADING_DEFAULT_TIMEFRAME` | `1m` | Candle timeframe |
| `ORDER_BOOK_DEPTH_LIMIT` | `20` | Order book depth |
| `DATA_COLLECTION_INTERVAL_SECONDS` | `60` | Collection poll interval |
| `TWELVEDATA_API_KEY` | _(empty)_ | Twelve Data API key (forex) |
| `FOREX_SYMBOLS` | `EUR/USD,USD/JPY,...` (10 pairs) | Forex pairs to track |
| `FOREX_POLL_INTERVAL_SECONDS` | `300` | Forex poll interval |
| `POLYGON_API_KEY` | _(empty)_ | Polygon.io API key (US stocks) |
| `STOCK_SYMBOLS` | `AAPL,MSFT,...` (10 tickers) | Stock tickers to track |
| `STOCK_POLL_INTERVAL_SECONDS` | `60` | Stock poll interval |
| `FINNHUB_API_KEY` | _(empty)_ | Finnhub API key (stocks fallback) |

---

## 7. Django Setup

```bash
source .venv/bin/activate
set -a && source .env && set +a

python manage.py migrate
python manage.py createsuperuser   # for admin access
python manage.py collectstatic --noinput   # if serving static files via Nginx
```

### Key Django settings

| Setting | Value |
|---------|-------|
| `DJANGO_SETTINGS_MODULE` | `trading_system.config.settings` |
| `ASGI_APPLICATION` | `trading_system.config.asgi.application` |
| `WSGI_APPLICATION` | `trading_system.config.wsgi.application` |
| Auth backend | JWT via `djangorestframework-simplejwt` (access: 30 min, refresh: 7 days) |
| Pagination | `PageNumberPagination`, page size 100 |
| Time zone | `UTC` |
| Logging | Console handler; `DEBUG` level when `DJANGO_DEBUG=True`, `INFO` otherwise |

---

## 8. Frontend Setup (Next.js)

```bash
cd frontend
npm install
npm run build      # production build
```

### Frontend stack

| Package | Version |
|---------|---------|
| Next.js | ^15.3.0 |
| React | ^19.1.0 |
| lightweight-charts | ^4.2.2 |
| lucide-react | ^0.487.0 |
| clsx | ^2.1.1 |
| Tailwind CSS | ^4.1.4 (via PostCSS) |
| TypeScript | ^5.8.3 |

### API proxy (Next.js rewrites in `next.config.ts`)

In development, Next.js proxies these paths to the Django backend at `127.0.0.1:8000`:

- `/api/*` -> `http://127.0.0.1:8000/api/*`
- `/ws/*` -> `http://127.0.0.1:8000/ws/*`

In production with Nginx, these rewrites are unnecessary — Nginx handles routing directly.

---

## 9. Running the Services

### 9.1 All processes needed

| # | Process | Command | Port |
|---|---------|---------|------|
| 1 | **Django (ASGI via Daphne)** | `daphne -b 0.0.0.0 -p 8000 trading_system.config.asgi:application` | 8000 |
| 2 | **Celery worker** | `celery -A trading_system worker -l info` | — |
| 3 | **Celery beat** | `celery -A trading_system beat -l info` | — |
| 4 | **Next.js frontend** | `cd frontend && npm run start` | 3000 |

### 9.2 systemd service files (recommended for production)

#### `/etc/systemd/system/candles-django.service`

```ini
[Unit]
Description=Candles Lab - Django (Daphne ASGI)
After=network.target postgresql.service redis-server.service

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/candles-lab
EnvironmentFile=/opt/candles-lab/.env
ExecStart=/opt/candles-lab/.venv/bin/daphne -b 0.0.0.0 -p 8000 trading_system.config.asgi:application
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

#### `/etc/systemd/system/candles-celery-worker.service`

```ini
[Unit]
Description=Candles Lab - Celery Worker
After=network.target postgresql.service redis-server.service

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/candles-lab
EnvironmentFile=/opt/candles-lab/.env
ExecStart=/opt/candles-lab/.venv/bin/celery -A trading_system worker -l info
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

#### `/etc/systemd/system/candles-celery-beat.service`

```ini
[Unit]
Description=Candles Lab - Celery Beat
After=network.target postgresql.service redis-server.service

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/candles-lab
EnvironmentFile=/opt/candles-lab/.env
ExecStart=/opt/candles-lab/.venv/bin/celery -A trading_system beat -l info
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

#### `/etc/systemd/system/candles-frontend.service`

```ini
[Unit]
Description=Candles Lab - Next.js Frontend
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/candles-lab/frontend
ExecStart=/usr/bin/npm run start
Restart=always
RestartSec=5
Environment=NODE_ENV=production
Environment=PORT=3000

[Install]
WantedBy=multi-user.target
```

#### Enable and start all services

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now candles-django candles-celery-worker candles-celery-beat candles-frontend
```

---

## 10. Nginx Reverse Proxy (recommended)

```nginx
upstream django_backend {
    server 127.0.0.1:8000;
}

upstream nextjs_frontend {
    server 127.0.0.1:3000;
}

server {
    listen 80;
    server_name yourdomain.com;

    # API and admin — proxy to Django
    location /api/ {
        proxy_pass http://django_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /admin/ {
        proxy_pass http://django_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # WebSocket — proxy to Daphne
    location /ws/ {
        proxy_pass http://django_backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # Django static files (after collectstatic)
    location /static/ {
        alias /opt/candles-lab/staticfiles/;
    }

    # Everything else — proxy to Next.js
    location / {
        proxy_pass http://nextjs_frontend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Then enable the site:

```bash
sudo apt install -y nginx
sudo ln -s /etc/nginx/sites-available/candles-lab /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

For HTTPS, use Certbot:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.com
```

---

## 11. Production Checklist

- [ ] `DJANGO_DEBUG=False`
- [ ] `DJANGO_SECRET_KEY` set to a strong random value
- [ ] `DJANGO_ALLOWED_HOSTS` set to your domain(s)
- [ ] `CORS_ALLOWED_ORIGINS` set to your frontend URL
- [ ] PostgreSQL password is strong and unique
- [ ] All API keys (Binance, Alpaca, Twelve Data, Polygon, Finnhub) are populated
- [ ] `collectstatic` has been run and Nginx serves `/static/`
- [ ] Firewall allows only ports 80, 443, and 22 (SSH)
- [ ] Redis is bound to `127.0.0.1` (not exposed publicly)
- [ ] PostgreSQL is bound to `127.0.0.1` (not exposed publicly)
- [ ] systemd services are enabled and running
- [ ] Log rotation is configured for Django, Celery, and Nginx logs
- [ ] Backups for the PostgreSQL database are scheduled
- [ ] SSL/TLS is configured via Certbot

---

## 12. Project Layout Reference

```
candles-lab/
├── manage.py
├── requirements.txt
├── pytest.ini
├── .env.example
├── .env                          # not committed
├── .gitignore
├── run_simulation.py             # standalone sim (no DB needed)
├── chart.html                    # standalone HTML chart
├── trading_system/
│   ├── __init__.py               # imports celery_app
│   ├── config/
│   │   ├── settings.py           # all Django + Celery + trading config
│   │   ├── celery.py             # Celery app definition
│   │   ├── asgi.py               # ASGI entrypoint (Daphne)
│   │   ├── wsgi.py               # WSGI entrypoint
│   │   └── urls.py               # root URL config
│   ├── core/                     # engine, trader, context, strategy registry
│   ├── strategies/               # strategy interface + implementations
│   ├── data/                     # data feed, Django models, migrations
│   │   └── migrations/
│   │       └── 0002_timescaledb_hypertables.py
│   └── api/                      # DRF views, serializers, WebSocket consumers
│       └── routing.py            # WebSocket URL routing
├── tests/                        # pytest suite
└── frontend/                     # Next.js 15 dashboard
    ├── package.json
    ├── next.config.ts
    ├── postcss.config.mjs
    ├── tsconfig.json
    └── src/
```

---

## 13. Useful Commands

```bash
# Activate the virtualenv
source /opt/candles-lab/.venv/bin/activate
set -a && source /opt/candles-lab/.env && set +a

# Run database migrations
python manage.py migrate

# Create a superuser
python manage.py createsuperuser

# Run tests
pytest

# Check service status
sudo systemctl status candles-django candles-celery-worker candles-celery-beat candles-frontend

# View logs
sudo journalctl -u candles-django -f
sudo journalctl -u candles-celery-worker -f

# Restart everything
sudo systemctl restart candles-django candles-celery-worker candles-celery-beat candles-frontend
```

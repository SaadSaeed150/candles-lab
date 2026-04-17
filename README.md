# Paper Trading Simulation System

A modular, plug-and-play paper-trading engine built with Django, DRF, Celery, and Django Channels.

## Quick start

```bash
# 1. Create a virtual environment
python -m venv .venv && source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy and configure environment variables
cp .env.example .env

# 4a. Run standalone simulation (no database needed)
python run_simulation.py

# 4b. Or start the Django API server (requires PostgreSQL + Redis)
python manage.py migrate
python manage.py runserver

# 4c. Or start with WebSocket support (via Daphne)
daphne trading_system.config.asgi:application

# 5. Start Celery worker (for background tasks)
celery -A trading_system worker -l info

# 6. Start Celery beat (for scheduled tasks)
celery -A trading_system beat -l info
```

## API endpoints

### Auth

| Method | Path                | Description                    |
|--------|---------------------|--------------------------------|
| POST   | `/api/auth/login/`  | Get JWT access + refresh token |
| POST   | `/api/auth/refresh/`| Refresh an access token        |
| POST   | `/api/auth/register/`| Create a new account          |
| GET    | `/api/auth/me/`     | Current user profile           |

### Trading

| Method | Path                          | Description                         |
|--------|-------------------------------|-------------------------------------|
| POST   | `/api/simulate/`              | Run a simulation, return results    |
| GET    | `/api/balance/`               | Balance from the last simulation    |
| GET    | `/api/trades/`                | Persisted trade history             |
| GET    | `/api/strategies/`            | List registered strategy names      |
| GET    | `/api/runs/`                  | List strategy runs                  |
| GET    | `/api/runs/<id>/`             | Strategy run detail                 |
| GET    | `/api/runs/<id>/signals/`     | Signals for a specific run          |
| GET    | `/api/runs/<id>/equity/`      | Equity curve for a specific run     |
| GET    | `/api/market-data/`           | Query stored market data            |

### WebSocket

| Path                         | Description                     |
|------------------------------|----------------------------------|
| `ws/market/<symbol>/`        | Real-time candle updates         |
| `ws/signals/<run_id>/`       | Real-time strategy signals       |

## Adding a new strategy

1. Create a file in `trading_system/strategies/`.
2. Subclass `BaseStrategy` and implement `on_data(data, context)`.
3. Register it: `registry.register("my_strategy", MyStrategy)`.

```python
from trading_system.strategies.base import BaseStrategy
from trading_system.core import registry

class MyStrategy(BaseStrategy):
    def on_data(self, data, context):
        return {"action": "HOLD"}

registry.register("my_strategy", MyStrategy)
```

4. Import the module in `registry.load_defaults()` or pass the name at runtime.

## Project layout

```
trading_system/
├── core/          Engine, trader, context, strategy registry
├── strategies/    Strategy interface + implementations
├── data/          Data feed, Django models, migrations
├── api/           DRF views, serializers, WebSocket consumers, URL routing
└── config/        Django settings, Celery, ASGI, root URLs
```

## Tech stack

- **Backend**: Django 5 + DRF + Django Channels
- **Database**: PostgreSQL / TimescaleDB (hypertables for time-series)
- **Cache & Broker**: Redis
- **Task Queue**: Celery + django-celery-beat
- **Auth**: JWT (djangorestframework-simplejwt)
- **Testing**: pytest + factory-boy

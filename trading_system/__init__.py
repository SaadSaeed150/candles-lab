"""
Trading system package.

Ensures the Celery app is loaded when Django starts,
so that @shared_task decorators use it.
"""

from trading_system.config.celery import app as celery_app

__all__ = ["celery_app"]

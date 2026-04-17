"""
Celery application for the trading system.

Auto-discovers tasks from all installed Django apps.
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "trading_system.config.settings")

app = Celery("trading_system")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

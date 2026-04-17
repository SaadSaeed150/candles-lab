"""
WSGI config for the trading_system project.
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "trading_system.config.settings")

application = get_wsgi_application()

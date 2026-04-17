"""
ASGI entrypoint — routes HTTP and WebSocket traffic.

HTTP requests go to Django, WebSocket connections go to Channels consumers.
"""

import os

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "trading_system.config.settings")

django_asgi_app = get_asgi_application()

from trading_system.api.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AllowedHostsOriginValidator(
            URLRouter(websocket_urlpatterns),
        ),
    }
)

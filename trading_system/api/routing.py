"""
WebSocket URL routing for Django Channels.
"""

from django.urls import re_path

from trading_system.api import consumers

websocket_urlpatterns = [
    re_path(r"ws/market/(?P<symbol>\w+)/$", consumers.MarketDataConsumer.as_asgi()),
    re_path(r"ws/signals/(?P<run_id>\d+)/$", consumers.StrategySignalConsumer.as_asgi()),
]

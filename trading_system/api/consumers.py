"""
Django Channels WebSocket consumers for real-time data streaming.

MarketDataConsumer  — streams live candle updates for a symbol.
StrategySignalConsumer — streams strategy signals for a specific run.
"""

import json
import logging

from channels.generic.websocket import AsyncWebsocketConsumer

logger = logging.getLogger(__name__)


class MarketDataConsumer(AsyncWebsocketConsumer):
    """Pushes real-time candle data to connected clients.

    Clients connect to ws/market/<symbol>/ and receive candle
    updates published to the `market_<symbol>` channel group.
    """

    async def connect(self) -> None:
        self.symbol = self.scope["url_route"]["kwargs"]["symbol"]
        self.group_name = f"market_{self.symbol}"

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        logger.info("WebSocket connected: market/%s", self.symbol)

    async def disconnect(self, close_code: int) -> None:
        await self.channel_layer.group_discard(self.group_name, self.channel_name)
        logger.info("WebSocket disconnected: market/%s (code=%s)", self.symbol, close_code)

    async def market_update(self, event: dict) -> None:
        """Handler for messages sent to the market group."""
        await self.send(text_data=json.dumps(event["data"]))


class StrategySignalConsumer(AsyncWebsocketConsumer):
    """Pushes real-time strategy signals to connected clients.

    Clients connect to ws/signals/<run_id>/ and receive signal
    updates published to the `signals_<run_id>` channel group.
    """

    async def connect(self) -> None:
        self.run_id = self.scope["url_route"]["kwargs"]["run_id"]
        self.group_name = f"signals_{self.run_id}"

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        logger.info("WebSocket connected: signals/%s", self.run_id)

    async def disconnect(self, close_code: int) -> None:
        await self.channel_layer.group_discard(self.group_name, self.channel_name)
        logger.info("WebSocket disconnected: signals/%s (code=%s)", self.run_id, close_code)

    async def signal_update(self, event: dict) -> None:
        """Handler for messages sent to the signals group."""
        await self.send(text_data=json.dumps(event["data"]))

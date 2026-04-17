"""Tests for PaperTrader — the core execution engine."""

import pytest
from trading_system.core.trader import PaperTrader, PositionSizing, Trade, OpenPosition


class TestOpenLong:
    def test_buy_opens_long_position(self, trader, candle):
        result = trader.execute({"action": "BUY"}, candle)

        assert result["executed"] == "BUY"
        assert result["side"] == "LONG"
        assert "BTCUSDT" in trader.positions
        assert trader.positions["BTCUSDT"].side == "LONG"
        assert trader.balance == 0.0

    def test_buy_quantity_uses_full_balance(self, trader, candle):
        result = trader.execute({"action": "BUY"}, candle)
        expected_qty = 10_000 / candle["close"]
        assert abs(result["quantity"] - expected_qty) < 0.01

    def test_buy_skips_when_already_in_position(self, trader, candle):
        trader.execute({"action": "BUY"}, candle)
        result = trader.execute({"action": "BUY"}, candle)

        assert result["executed"] == "SKIP"
        assert result["reason"] == "position_exists"

    def test_buy_with_percent_sizing(self, trader_percent_sizing, candle):
        result = trader_percent_sizing.execute({"action": "BUY"}, candle)

        expected_qty = (10_000 * 0.5) / candle["close"]
        assert abs(result["quantity"] - expected_qty) < 0.01
        assert trader_percent_sizing.balance > 0


class TestCloseLong:
    def test_sell_closes_long_and_calculates_pnl(self, trader, candle):
        trader.execute({"action": "BUY"}, candle)

        sell_candle = {**candle, "close": 110.0, "time": "2026-01-01T00:01:00"}
        result = trader.execute({"action": "SELL"}, sell_candle)

        assert result["executed"] == "SELL"
        assert result["pnl"] > 0
        assert "BTCUSDT" not in trader.positions
        assert trader.balance > 0
        assert len(trader.trade_history) == 1

    def test_sell_with_loss(self, trader, candle):
        trader.execute({"action": "BUY"}, candle)

        sell_candle = {**candle, "close": 90.0, "time": "2026-01-01T00:01:00"}
        result = trader.execute({"action": "SELL"}, sell_candle)

        assert result["pnl"] < 0
        assert trader.trade_history[0].pnl < 0

    def test_sell_no_position_opens_short(self, trader, candle):
        candle_above = {**candle, "close": 115.0}
        result = trader.execute({"action": "SELL"}, candle_above)

        assert result["executed"] == "SHORT"
        assert result["side"] == "SHORT"


class TestShortSelling:
    def test_short_opens_short_position(self, trader, candle):
        result = trader.execute({"action": "SHORT"}, candle)

        assert result["executed"] == "SHORT"
        assert result["side"] == "SHORT"
        assert trader.positions["BTCUSDT"].side == "SHORT"

    def test_cover_closes_short(self, trader, candle):
        trader.execute({"action": "SHORT"}, candle)

        cover_candle = {**candle, "close": 95.0, "time": "2026-01-01T00:01:00"}
        result = trader.execute({"action": "COVER"}, cover_candle)

        assert result["executed"] == "COVER"
        assert result["pnl"] > 0
        assert "BTCUSDT" not in trader.positions

    def test_short_profit_when_price_drops(self, trader, candle):
        trader.execute({"action": "SHORT"}, candle)

        cover_candle = {**candle, "close": 90.0, "time": "2026-01-01T00:01:00"}
        result = trader.execute({"action": "COVER"}, cover_candle)

        assert result["pnl"] > 0

    def test_short_loss_when_price_rises(self, trader, candle):
        trader.execute({"action": "SHORT"}, candle)

        cover_candle = {**candle, "close": 115.0, "time": "2026-01-01T00:01:00"}
        result = trader.execute({"action": "COVER"}, cover_candle)

        assert result["pnl"] < 0


class TestCommission:
    def test_commission_deducted_on_trade(self, trader_with_fees, candle):
        trader_with_fees.execute({"action": "BUY"}, candle)

        sell_candle = {**candle, "close": 102.0, "time": "2026-01-01T00:01:00"}
        trader_with_fees.execute({"action": "SELL"}, sell_candle)

        trade = trader_with_fees.trade_history[0]
        assert trade.commission > 0
        assert trade.net_pnl < trade.pnl

    def test_zero_commission_when_rate_is_zero(self, trader, candle):
        trader.execute({"action": "BUY"}, candle)

        sell_candle = {**candle, "close": 105.0, "time": "2026-01-01T00:01:00"}
        trader.execute({"action": "SELL"}, sell_candle)

        trade = trader.trade_history[0]
        assert trade.commission == 0


class TestStopLossTakeProfit:
    def test_stop_loss_triggers_on_long(self, trader, candle):
        trader.execute({"action": "BUY", "stop_loss": 95.0}, candle)

        sl_candle = {**candle, "close": 94.0, "time": "2026-01-01T00:01:00"}
        trader.execute({"action": "HOLD"}, sl_candle)

        assert "BTCUSDT" not in trader.positions
        assert len(trader.trade_history) == 1
        assert trader.trade_history[0].pnl < 0

    def test_take_profit_triggers_on_long(self, trader, candle):
        trader.execute({"action": "BUY", "take_profit": 110.0}, candle)

        tp_candle = {**candle, "close": 112.0, "time": "2026-01-01T00:01:00"}
        trader.execute({"action": "HOLD"}, tp_candle)

        assert "BTCUSDT" not in trader.positions
        assert trader.trade_history[0].pnl > 0

    def test_stop_loss_triggers_on_short(self, trader, candle):
        trader.execute({"action": "SHORT", "stop_loss": 108.0}, candle)

        sl_candle = {**candle, "close": 110.0, "time": "2026-01-01T00:01:00"}
        trader.execute({"action": "HOLD"}, sl_candle)

        assert "BTCUSDT" not in trader.positions
        assert trader.trade_history[0].pnl < 0


class TestMultiplePositions:
    def test_multiple_symbols(self):
        trader = PaperTrader(
            balance=20_000, commission_rate=0, slippage_rate=0,
            max_positions=3, position_sizing=PositionSizing.PERCENT,
            position_size_value=0.4,
        )

        btc = {"symbol": "BTCUSDT", "close": 100.0, "time": "2026-01-01T00:00:00"}
        eth = {"symbol": "ETHUSDT", "close": 50.0, "time": "2026-01-01T00:00:00"}

        trader.execute({"action": "BUY"}, btc)
        trader.execute({"action": "BUY"}, eth)

        assert len(trader.positions) == 2
        assert "BTCUSDT" in trader.positions
        assert "ETHUSDT" in trader.positions

    def test_max_positions_enforced(self):
        trader = PaperTrader(balance=30_000, commission_rate=0, slippage_rate=0, max_positions=1)

        btc = {"symbol": "BTCUSDT", "close": 100.0, "time": "2026-01-01T00:00:00"}
        eth = {"symbol": "ETHUSDT", "close": 50.0, "time": "2026-01-01T00:00:00"}

        trader.execute({"action": "BUY"}, btc)
        result = trader.execute({"action": "BUY"}, eth)

        assert result["executed"] == "SKIP"
        assert result["reason"] == "max_positions"
        assert len(trader.positions) == 1


class TestSnapshot:
    def test_snapshot_contains_key_fields(self, trader, candle):
        trader.execute({"action": "BUY"}, candle)
        snap = trader.snapshot()

        assert "balance" in snap
        assert "open_positions" in snap
        assert "trade_count" in snap
        assert "total_pnl" in snap
        assert "total_net_pnl" in snap


class TestShortAccounting:
    """Verify that short positions produce correct balance and equity."""

    def test_short_round_trip_balance_is_correct(self):
        """After short open+close with zero fees, balance = initial + pnl."""
        trader = PaperTrader(balance=10_000, commission_rate=0, slippage_rate=0)
        candle = {"symbol": "SYM", "close": 100.0, "time": "2026-01-01T00:00:00"}

        trader.execute({"action": "SHORT"}, candle)
        cover_candle = {**candle, "close": 90.0, "time": "2026-01-01T00:01:00"}
        trader.execute({"action": "COVER"}, cover_candle)

        expected_pnl = (100 - 90) * (10_000 / 100)
        assert abs(trader.balance - (10_000 + expected_pnl)) < 0.01

    def test_short_loss_balance_is_correct(self):
        trader = PaperTrader(balance=10_000, commission_rate=0, slippage_rate=0)
        candle = {"symbol": "SYM", "close": 100.0, "time": "2026-01-01T00:00:00"}

        trader.execute({"action": "SHORT"}, candle)
        cover_candle = {**candle, "close": 110.0, "time": "2026-01-01T00:01:00"}
        trader.execute({"action": "COVER"}, cover_candle)

        expected_pnl = (100 - 110) * (10_000 / 100)
        assert abs(trader.balance - (10_000 + expected_pnl)) < 0.01

    def test_total_equity_decreases_when_short_loses(self):
        trader = PaperTrader(balance=10_000, commission_rate=0, slippage_rate=0)
        candle = {"symbol": "SYM", "close": 100.0, "time": "2026-01-01T00:00:00"}
        trader.execute({"action": "SHORT"}, candle)

        equity_at_entry = trader.total_equity(100.0)
        equity_when_losing = trader.total_equity(110.0)
        assert equity_when_losing < equity_at_entry

    def test_total_equity_increases_when_short_wins(self):
        trader = PaperTrader(balance=10_000, commission_rate=0, slippage_rate=0)
        candle = {"symbol": "SYM", "close": 100.0, "time": "2026-01-01T00:00:00"}
        trader.execute({"action": "SHORT"}, candle)

        equity_at_entry = trader.total_equity(100.0)
        equity_when_winning = trader.total_equity(90.0)
        assert equity_when_winning > equity_at_entry


class TestDeterministicSlippage:
    def test_same_seed_gives_same_results(self):
        results = []
        for _ in range(2):
            trader = PaperTrader(
                balance=10_000, commission_rate=0, slippage_rate=0.01,
                random_seed=42,
            )
            candle = {"symbol": "SYM", "close": 100.0, "time": "2026-01-01T00:00:00"}
            res = trader.execute({"action": "BUY"}, candle)
            results.append(res["entry_price"])

        assert results[0] == results[1]

    def test_different_seeds_give_different_results(self):
        prices = []
        for seed in (42, 99):
            trader = PaperTrader(
                balance=10_000, commission_rate=0, slippage_rate=0.01,
                random_seed=seed,
            )
            candle = {"symbol": "SYM", "close": 100.0, "time": "2026-01-01T00:00:00"}
            res = trader.execute({"action": "BUY"}, candle)
            prices.append(res["entry_price"])

        assert prices[0] != prices[1]


class TestTradeDataclass:
    def test_net_pnl_calculation(self):
        trade = Trade(
            symbol="BTC", side="LONG", entry_price=100, exit_price=110,
            quantity=10, pnl=100, commission=5, slippage=2,
            opened_at="", closed_at="",
        )
        assert trade.net_pnl == 93.0

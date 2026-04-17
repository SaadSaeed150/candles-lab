"""
REST API views for the paper-trading simulation.

Endpoints:
    POST /api/auth/register/   — create a new user account
    GET  /api/auth/me/         — current user profile
    POST /api/simulate/        — run a full simulation, return results
    GET  /api/balance/         — current trader balance (last sim)
    GET  /api/trades/          — completed trade history (from DB)
    GET  /api/strategies/      — list registered strategy names
    GET  /api/runs/            — list strategy runs
    GET  /api/runs/<id>/       — strategy run detail
    GET  /api/runs/<id>/signals/ — signals for a run
    GET  /api/runs/<id>/equity/  — equity curve for a run
    GET  /api/market-data/     — query stored market data
"""

from django.utils import timezone as tz
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from trading_system.api.serializers import (
    BookTickerSnapshotSerializer,
    EquityCurveSerializer,
    MarketDataSerializer,
    OrderBookSnapshotSerializer,
    RegisterSerializer,
    SimulationRequestSerializer,
    StrategyRunSerializer,
    StrategySignalSerializer,
    TickerSnapshotSerializer,
    TradeRecordSerializer,
    UserSerializer,
)
from trading_system.core import registry
from trading_system.core.engine import TradingEngine
from trading_system.core.trader import PaperTrader
from trading_system.data.feed import generate_feed
from trading_system.data.models import (
    BookTickerSnapshot,
    EquityCurve,
    MarketData,
    OrderBookSnapshot,
    StrategyRun,
    StrategySignal,
    TickerSnapshot,
    TradeRecord,
)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@api_view(["POST"])
@permission_classes([AllowAny])
def register(request: Request) -> Response:
    """Create a new user account and return user data."""
    ser = RegisterSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    user = ser.save()
    return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def current_user(request: Request) -> Response:
    """Return the currently authenticated user."""
    return Response(UserSerializer(request.user).data)


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

_last_engine: TradingEngine | None = None


@api_view(["POST"])
def simulate(request: Request) -> Response:
    """Run a paper-trading simulation and return the full result set."""
    global _last_engine

    ser = SimulationRequestSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    params = ser.validated_data

    registry.load_defaults()

    try:
        strategy_cls = registry.get(params["strategy"])
    except KeyError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    strategy = strategy_cls()
    trader = PaperTrader(balance=params["initial_balance"])
    engine = TradingEngine(strategy=strategy, trader=trader)

    # Create a StrategyRun record
    run = StrategyRun.objects.create(
        user=request.user if request.user.is_authenticated else None,
        strategy_name=params["strategy"],
        mode="paper",
        symbol=params["symbol"],
        exchange=params.get("exchange", "binance"),
        timeframe=params.get("timeframe", "1m"),
        config=params,
        status="running",
        initial_balance=params["initial_balance"],
    )

    feed = generate_feed(
        symbol=params["symbol"],
        start_price=params["start_price"],
        num_points=params["num_points"],
    )

    results = engine.run(feed)
    _last_engine = engine

    user_or_none = request.user if request.user.is_authenticated else None

    # Persist completed trades
    for trade in trader.trade_history:
        TradeRecord.objects.create(
            user=user_or_none,
            run=run,
            symbol=trade.symbol,
            side=trade.side,
            entry_price=trade.entry_price,
            exit_price=trade.exit_price,
            quantity=trade.quantity,
            pnl=trade.pnl,
            commission=trade.commission,
            slippage=trade.slippage,
            opened_at=trade.opened_at,
            closed_at=trade.closed_at,
        )

    # Persist signals
    for sig in engine.signals:
        StrategySignal.objects.create(
            run=run,
            timestamp=sig["timestamp"],
            action=sig["action"],
            price=sig.get("price", 0),
            confidence=sig.get("confidence") or 0,
            stop_loss=sig.get("stop_loss"),
            take_profit=sig.get("take_profit"),
            meta=sig.get("meta", {}),
        )

    # Persist equity curve
    for snap in trader.equity_snapshots:
        EquityCurve.objects.create(
            run=run,
            timestamp=snap["timestamp"],
            balance=snap["balance"],
            unrealised_pnl=snap.get("unrealised_pnl", 0),
            total_equity=snap["total_equity"],
            drawdown=snap.get("drawdown", 0),
        )

    # Compute metrics
    metrics = engine.compute_metrics()

    # Finalize the run
    last_price = results[-1]["data"]["close"] if results else 0
    final_equity = trader.total_equity(last_price)
    run.status = "completed"
    run.finished_at = tz.now()
    run.final_balance = final_equity
    run.metrics = metrics
    run.save(update_fields=["status", "finished_at", "final_balance", "metrics"])

    return Response({
        "run_id": run.id,
        "ticks_processed": len(results),
        "final_balance": final_equity,
        "trades_completed": len(trader.trade_history),
        "total_pnl": metrics.get("total_pnl", 0),
        "total_net_pnl": metrics.get("total_net_pnl", 0),
        "win_rate": metrics.get("win_rate", 0),
        "sharpe_ratio": metrics.get("sharpe_ratio", 0),
        "max_drawdown_pct": metrics.get("max_drawdown_pct", 0),
        "results": results,
    })


@api_view(["GET"])
def balance(request: Request) -> Response:
    """Return the balance snapshot from the most recent simulation."""
    if _last_engine is None:
        return Response(
            {"error": "No simulation has been run yet."},
            status=status.HTTP_404_NOT_FOUND,
        )
    return Response(_last_engine.trader.snapshot())


@api_view(["GET"])
def trades(request: Request) -> Response:
    """Return persisted trade history from the database."""
    qs = TradeRecord.objects.all()

    if request.user.is_authenticated:
        qs = qs.filter(user=request.user)

    run_id = request.query_params.get("run")
    if run_id:
        qs = qs.filter(run_id=run_id)

    symbol = request.query_params.get("symbol")
    if symbol:
        qs = qs.filter(symbol=symbol)

    qs = qs.order_by("id")[:200]
    return Response(TradeRecordSerializer(qs, many=True).data)


@api_view(["GET"])
def strategies(request: Request) -> Response:
    """List all registered strategy names."""
    registry.load_defaults()
    return Response({"strategies": registry.available()})


# ---------------------------------------------------------------------------
# Strategy runs
# ---------------------------------------------------------------------------

@api_view(["GET"])
def strategy_runs(request: Request) -> Response:
    """List strategy runs, optionally filtered by mode or strategy."""
    qs = StrategyRun.objects.all()

    if request.user.is_authenticated:
        qs = qs.filter(user=request.user)

    mode = request.query_params.get("mode")
    if mode:
        qs = qs.filter(mode=mode)

    strategy_name = request.query_params.get("strategy")
    if strategy_name:
        qs = qs.filter(strategy_name=strategy_name)

    qs = qs[:100]
    return Response(StrategyRunSerializer(qs, many=True).data)


@api_view(["GET"])
def strategy_run_detail(request: Request, run_id: int) -> Response:
    """Get detailed info about a single strategy run."""
    try:
        run = StrategyRun.objects.get(pk=run_id)
    except StrategyRun.DoesNotExist:
        return Response({"error": "Run not found."}, status=status.HTTP_404_NOT_FOUND)
    return Response(StrategyRunSerializer(run).data)


@api_view(["GET"])
def run_signals(request: Request, run_id: int) -> Response:
    """List signals for a specific strategy run."""
    qs = StrategySignal.objects.filter(run_id=run_id)[:1000]
    return Response(StrategySignalSerializer(qs, many=True).data)


@api_view(["GET"])
def run_equity(request: Request, run_id: int) -> Response:
    """Return the equity curve for a specific strategy run."""
    qs = EquityCurve.objects.filter(run_id=run_id)
    return Response(EquityCurveSerializer(qs, many=True).data)


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------

@api_view(["GET"])
def market_data_list(request: Request) -> Response:
    """Query stored market data with optional symbol/timeframe filters.

    Returns the most recent candles first (up to `limit`, default 500).
    The response is sorted ascending by time for charting convenience.
    """
    qs = MarketData.objects.all()

    symbol = request.query_params.get("symbol")
    if symbol:
        qs = qs.filter(symbol=symbol)

    timeframe = request.query_params.get("timeframe")
    if timeframe:
        qs = qs.filter(timeframe=timeframe)

    exchange = request.query_params.get("exchange")
    if exchange:
        qs = qs.filter(exchange=exchange)

    limit = min(int(request.query_params.get("limit", 500)), 5000)

    latest = qs.order_by("-time")[:limit]
    results = sorted(latest, key=lambda x: x.time)

    return Response(MarketDataSerializer(results, many=True).data)


# ---------------------------------------------------------------------------
# Data ingestion
# ---------------------------------------------------------------------------

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def backfill(request: Request) -> Response:
    """Trigger a historical data backfill as a background Celery task."""
    from trading_system.data.tasks import backfill_historical

    symbol = request.data.get("symbol")
    exchange = request.data.get("exchange", "binance")
    timeframe = request.data.get("timeframe", "1m")
    start = request.data.get("start")
    end = request.data.get("end")

    if not symbol or not start or not end:
        return Response(
            {"error": "symbol, start, and end are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    task = backfill_historical.delay(
        symbol=symbol,
        exchange=exchange,
        timeframe=timeframe,
        start_iso=start,
        end_iso=end,
    )

    return Response({
        "task_id": task.id,
        "status": "queued",
        "message": f"Backfill started for {exchange}:{symbol} {timeframe}",
    }, status=status.HTTP_202_ACCEPTED)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def start_stream(request: Request) -> Response:
    """Start a live data stream as a background Celery task."""
    from trading_system.data.tasks import start_live_stream

    symbol = request.data.get("symbol")
    exchange = request.data.get("exchange", "binance")
    timeframe = request.data.get("timeframe", "1m")

    if not symbol:
        return Response(
            {"error": "symbol is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    task = start_live_stream.delay(
        symbol=symbol,
        exchange=exchange,
        timeframe=timeframe,
    )

    return Response({
        "task_id": task.id,
        "status": "queued",
        "message": f"Live stream started for {exchange}:{symbol} {timeframe}",
    }, status=status.HTTP_202_ACCEPTED)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def import_csv(request: Request) -> Response:
    """Import candles from a CSV file as a background Celery task."""
    from trading_system.data.tasks import ingest_csv

    file_path = request.data.get("file_path")
    symbol = request.data.get("symbol")
    exchange = request.data.get("exchange", "manual")
    timeframe = request.data.get("timeframe", "1d")

    if not file_path or not symbol:
        return Response(
            {"error": "file_path and symbol are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    task = ingest_csv.delay(
        file_path=file_path,
        symbol=symbol,
        exchange=exchange,
        timeframe=timeframe,
    )

    return Response({
        "task_id": task.id,
        "status": "queued",
        "message": f"CSV import started for {symbol} from {file_path}",
    }, status=status.HTTP_202_ACCEPTED)


@api_view(["GET"])
def task_status(request: Request, task_id: str) -> Response:
    """Check the status of a background Celery task."""
    from celery.result import AsyncResult

    result = AsyncResult(task_id)
    response = {
        "task_id": task_id,
        "status": result.status,
    }

    if result.ready():
        response["result"] = result.result
    elif result.failed():
        response["error"] = str(result.result)

    return Response(response)


# ---------------------------------------------------------------------------
# Backtesting
# ---------------------------------------------------------------------------

@api_view(["POST"])
def run_backtest(request: Request) -> Response:
    """Trigger a backtest as a background Celery task."""
    from trading_system.backtesting.tasks import run_backtest as backtest_task

    strategy = request.data.get("strategy")
    if not strategy:
        return Response(
            {"error": "strategy is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    task = backtest_task.delay(
        strategy_name=strategy,
        symbol=request.data.get("symbol", "BTCUSDT"),
        exchange=request.data.get("exchange", "binance"),
        timeframe=request.data.get("timeframe", "1m"),
        start=request.data.get("start"),
        end=request.data.get("end"),
        initial_balance=float(request.data.get("initial_balance", 10_000)),
        commission_rate=float(request.data.get("commission_rate", 0.001)),
        slippage_rate=float(request.data.get("slippage_rate", 0.0005)),
        position_sizing=request.data.get("position_sizing", "all_in"),
        feed_source=request.data.get("feed_source", "synthetic"),
        csv_path=request.data.get("csv_path"),
        synthetic_points=int(request.data.get("synthetic_points", 100)),
        synthetic_start_price=float(request.data.get("synthetic_start_price", 100)),
        user_id=request.user.id if request.user.is_authenticated else None,
    )

    return Response({
        "task_id": task.id,
        "status": "queued",
        "message": f"Backtest started for {strategy}",
    }, status=status.HTTP_202_ACCEPTED)


@api_view(["POST"])
def run_backtest_sync(request: Request) -> Response:
    """Run a backtest synchronously and return results immediately.

    Suitable for small backtests (< 1000 data points). For large
    backtests, use the async /api/backtest/ endpoint instead.
    """
    from trading_system.backtesting.report import generate_detailed
    from trading_system.backtesting.runner import BacktestConfig, BacktestRunner

    strategy = request.data.get("strategy")
    if not strategy:
        return Response(
            {"error": "strategy is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    config = BacktestConfig(
        strategy_name=strategy,
        symbol=request.data.get("symbol", "BTCUSDT"),
        exchange=request.data.get("exchange", "binance"),
        timeframe=request.data.get("timeframe", "1m"),
        initial_balance=float(request.data.get("initial_balance", 10_000)),
        commission_rate=float(request.data.get("commission_rate", 0.001)),
        slippage_rate=float(request.data.get("slippage_rate", 0.0005)),
        feed_source=request.data.get("feed_source", "synthetic"),
        synthetic_points=int(request.data.get("synthetic_points", 100)),
        synthetic_start_price=float(request.data.get("synthetic_start_price", 100)),
    )

    runner = BacktestRunner(config)
    result = runner.run()
    report = generate_detailed(result)

    return Response(report)


@api_view(["POST"])
def compare_strategies_view(request: Request) -> Response:
    """Compare multiple strategies as a background Celery task."""
    from trading_system.backtesting.tasks import compare_strategies as compare_task

    strategy_names = request.data.get("strategies", [])
    if not strategy_names or len(strategy_names) < 2:
        return Response(
            {"error": "At least 2 strategies are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    task = compare_task.delay(
        strategy_names=strategy_names,
        symbol=request.data.get("symbol", "BTCUSDT"),
        exchange=request.data.get("exchange", "binance"),
        timeframe=request.data.get("timeframe", "1m"),
        initial_balance=float(request.data.get("initial_balance", 10_000)),
        feed_source=request.data.get("feed_source", "synthetic"),
        synthetic_points=int(request.data.get("synthetic_points", 100)),
        user_id=request.user.id if request.user.is_authenticated else None,
    )

    return Response({
        "task_id": task.id,
        "status": "queued",
        "message": f"Comparing strategies: {', '.join(strategy_names)}",
    }, status=status.HTTP_202_ACCEPTED)


# ---------------------------------------------------------------------------
# Order Book / Ticker / Book Ticker data
# ---------------------------------------------------------------------------

@api_view(["GET"])
def order_book_list(request: Request) -> Response:
    """Query stored order book snapshots."""
    qs = OrderBookSnapshot.objects.all()

    symbol = request.query_params.get("symbol")
    if symbol:
        qs = qs.filter(symbol=symbol)

    exchange = request.query_params.get("exchange")
    if exchange:
        qs = qs.filter(exchange=exchange)

    qs = qs[:500]
    return Response(OrderBookSnapshotSerializer(qs, many=True).data)


@api_view(["GET"])
def ticker_list(request: Request) -> Response:
    """Query stored 24h ticker snapshots."""
    qs = TickerSnapshot.objects.all()

    symbol = request.query_params.get("symbol")
    if symbol:
        qs = qs.filter(symbol=symbol)

    exchange = request.query_params.get("exchange")
    if exchange:
        qs = qs.filter(exchange=exchange)

    qs = qs[:500]
    return Response(TickerSnapshotSerializer(qs, many=True).data)


@api_view(["GET"])
def book_ticker_list(request: Request) -> Response:
    """Query stored book ticker (best bid/ask) snapshots."""
    qs = BookTickerSnapshot.objects.all()

    symbol = request.query_params.get("symbol")
    if symbol:
        qs = qs.filter(symbol=symbol)

    exchange = request.query_params.get("exchange")
    if exchange:
        qs = qs.filter(exchange=exchange)

    qs = qs[:500]
    return Response(BookTickerSnapshotSerializer(qs, many=True).data)


@api_view(["GET"])
def collection_symbols(request: Request) -> Response:
    """Return the configured list of symbols being collected."""
    from django.conf import settings as s
    symbols = getattr(s, "TRADING_SYMBOLS", [])
    return Response({
        "symbols": symbols,
        "count": len(symbols),
        "timeframe": getattr(s, "TRADING_DEFAULT_TIMEFRAME", "1m"),
        "order_book_depth": getattr(s, "ORDER_BOOK_DEPTH_LIMIT", 20),
    })


# ---------------------------------------------------------------------------
# Data collection triggers
# ---------------------------------------------------------------------------

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def start_data_collection(request: Request) -> Response:
    """Start the combined market data stream for all configured symbols."""
    from trading_system.data.tasks import start_market_data_stream

    symbols = request.data.get("symbols")
    timeframe = request.data.get("timeframe", "1m")

    task = start_market_data_stream.delay(
        symbols=symbols,
        timeframe=timeframe,
    )

    return Response({
        "task_id": task.id,
        "status": "queued",
        "message": "Market data stream started",
    }, status=status.HTTP_202_ACCEPTED)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def trigger_order_book_collection(request: Request) -> Response:
    """Manually trigger an order book collection for all symbols."""
    from trading_system.data.tasks import collect_order_books

    task = collect_order_books.delay(
        symbols=request.data.get("symbols"),
    )

    return Response({
        "task_id": task.id,
        "status": "queued",
        "message": "Order book collection started",
    }, status=status.HTTP_202_ACCEPTED)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def backfill_all(request: Request) -> Response:
    """Backfill historical klines for all configured symbols."""
    from trading_system.data.tasks import backfill_all_symbols

    task = backfill_all_symbols.delay(
        timeframe=request.data.get("timeframe", "1m"),
        start_iso=request.data.get("start", ""),
        end_iso=request.data.get("end", ""),
        exchange=request.data.get("exchange", "binance"),
    )

    return Response({
        "task_id": task.id,
        "status": "queued",
        "message": "Backfill started for all symbols",
    }, status=status.HTTP_202_ACCEPTED)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def trigger_forex_collection(request: Request) -> Response:
    """Trigger a one-time forex data poll for all configured pairs."""
    from trading_system.data.tasks import collect_forex

    task = collect_forex.delay(
        symbols=request.data.get("symbols"),
        timeframe=request.data.get("timeframe", "5m"),
        count=request.data.get("count", 1),
    )

    return Response({
        "task_id": task.id,
        "status": "queued",
        "message": "Forex collection started",
    }, status=status.HTTP_202_ACCEPTED)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def trigger_forex_backfill(request: Request) -> Response:
    """Backfill historical forex data for all configured pairs."""
    from trading_system.data.tasks import backfill_forex

    task = backfill_forex.delay(
        symbols=request.data.get("symbols"),
        timeframe=request.data.get("timeframe", "5m"),
        start_iso=request.data.get("start", ""),
        end_iso=request.data.get("end", ""),
    )

    return Response({
        "task_id": task.id,
        "status": "queued",
        "message": "Forex backfill started",
    }, status=status.HTTP_202_ACCEPTED)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def trigger_stock_collection(request: Request) -> Response:
    """Trigger a one-time stock data poll for all configured symbols."""
    from trading_system.data.tasks import collect_stocks

    task = collect_stocks.delay(
        symbols=request.data.get("symbols"),
        timeframe=request.data.get("timeframe", "1m"),
        count=request.data.get("count", 1),
    )

    return Response({
        "task_id": task.id,
        "status": "queued",
        "message": "Stock collection started",
    }, status=status.HTTP_202_ACCEPTED)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def trigger_stock_backfill(request: Request) -> Response:
    """Backfill historical stock data for all configured symbols."""
    from trading_system.data.tasks import backfill_stocks

    task = backfill_stocks.delay(
        symbols=request.data.get("symbols"),
        timeframe=request.data.get("timeframe", "1m"),
        start_iso=request.data.get("start", ""),
        end_iso=request.data.get("end", ""),
    )

    return Response({
        "task_id": task.id,
        "status": "queued",
        "message": "Stock backfill started",
    }, status=status.HTTP_202_ACCEPTED)

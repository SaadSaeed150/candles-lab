"""
URL routing for the trading API.
"""

from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from trading_system.api import views

def _dual(route: str, view, **kwargs):
    """Register both with and without trailing slash to avoid redirect loops."""
    name = kwargs.get("name", "")
    clean = route.rstrip("/")
    if hasattr(view, "as_view"):
        return [
            path(f"{clean}/", view.as_view(), name=name),
            path(f"{clean}", view.as_view(), name=f"{name}_noslash"),
        ]
    return [
        path(f"{clean}/", view, name=name),
        path(f"{clean}", view, name=f"{name}_noslash"),
    ]


urlpatterns = [
    # Auth
    *_dual("auth/login", TokenObtainPairView, name="token_obtain_pair"),
    *_dual("auth/refresh", TokenRefreshView, name="token_refresh"),
    *_dual("auth/register", views.register, name="register"),
    *_dual("auth/me", views.current_user, name="current_user"),

    # Simulation / trading
    *_dual("simulate", views.simulate, name="simulate"),
    *_dual("balance", views.balance, name="balance"),
    *_dual("trades", views.trades, name="trades"),
    *_dual("strategies", views.strategies, name="strategies"),

    # Strategy runs
    *_dual("runs", views.strategy_runs, name="strategy_runs"),
    *_dual("runs/<int:run_id>", views.strategy_run_detail, name="strategy_run_detail"),
    *_dual("runs/<int:run_id>/signals", views.run_signals, name="run_signals"),
    *_dual("runs/<int:run_id>/equity", views.run_equity, name="run_equity"),

    # Market data
    *_dual("market-data", views.market_data_list, name="market_data_list"),
    *_dual("order-books", views.order_book_list, name="order_book_list"),
    *_dual("tickers", views.ticker_list, name="ticker_list"),
    *_dual("book-tickers", views.book_ticker_list, name="book_ticker_list"),
    *_dual("collection/symbols", views.collection_symbols, name="collection_symbols"),

    # Data ingestion
    *_dual("data/backfill", views.backfill, name="backfill"),
    *_dual("data/backfill-all", views.backfill_all, name="backfill_all"),
    *_dual("data/stream", views.start_stream, name="start_stream"),
    *_dual("data/collect", views.start_data_collection, name="start_data_collection"),
    *_dual("data/collect-order-books", views.trigger_order_book_collection, name="trigger_order_book_collection"),
    *_dual("data/import-csv", views.import_csv, name="import_csv"),
    *_dual("data/collect-forex", views.trigger_forex_collection, name="trigger_forex_collection"),
    *_dual("data/backfill-forex", views.trigger_forex_backfill, name="trigger_forex_backfill"),
    *_dual("data/collect-stocks", views.trigger_stock_collection, name="trigger_stock_collection"),
    *_dual("data/backfill-stocks", views.trigger_stock_backfill, name="trigger_stock_backfill"),
    *_dual("data/task/<str:task_id>", views.task_status, name="task_status"),

    # Backtesting
    *_dual("backtest", views.run_backtest, name="run_backtest"),
    *_dual("backtest/sync", views.run_backtest_sync, name="run_backtest_sync"),
    *_dual("backtest/compare", views.compare_strategies_view, name="compare_strategies"),
]

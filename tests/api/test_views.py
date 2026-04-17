"""Tests for API views."""

import pytest
from unittest.mock import patch

pytestmark = pytest.mark.django_db


class TestStrategiesEndpoint:
    def test_strategies_list(self, client):
        response = client.get("/api/strategies/")

        assert response.status_code == 200
        data = response.json()
        assert "strategies" in data
        assert "sample" in data["strategies"]


class TestSimulateEndpoint:
    def test_simulate_default_params(self, client):
        response = client.post(
            "/api/simulate/",
            data={"strategy": "sample", "num_points": 10},
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert "ticks_processed" in data
        assert data["ticks_processed"] == 10
        assert "final_balance" in data
        assert "run_id" in data

    def test_simulate_invalid_strategy(self, client):
        response = client.post(
            "/api/simulate/",
            data={"strategy": "nonexistent"},
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_simulate_custom_balance(self, client):
        response = client.post(
            "/api/simulate/",
            data={"strategy": "sample", "initial_balance": 50000, "num_points": 10},
            content_type="application/json",
        )

        assert response.status_code == 200


class TestBalanceEndpoint:
    def test_balance_no_sim_returns_404(self, client):
        from trading_system.api import views
        views._last_engine = None

        response = client.get("/api/balance/")
        assert response.status_code == 404

    def test_balance_after_sim(self, client):
        client.post(
            "/api/simulate/",
            data={"strategy": "sample", "num_points": 5},
            content_type="application/json",
        )

        response = client.get("/api/balance/")
        assert response.status_code == 200
        data = response.json()
        assert "balance" in data


class TestRegisterEndpoint:
    def test_register_new_user(self, client):
        response = client.post(
            "/api/auth/register/",
            data={
                "username": "testuser",
                "email": "test@example.com",
                "password": "securepass123",
            },
            content_type="application/json",
        )

        assert response.status_code == 201
        data = response.json()
        assert data["username"] == "testuser"

    def test_register_duplicate_username(self, client):
        client.post(
            "/api/auth/register/",
            data={
                "username": "dupuser",
                "email": "dup1@example.com",
                "password": "securepass123",
            },
            content_type="application/json",
        )

        response = client.post(
            "/api/auth/register/",
            data={
                "username": "dupuser",
                "email": "dup2@example.com",
                "password": "securepass123",
            },
            content_type="application/json",
        )

        assert response.status_code == 400


class TestBacktestSyncEndpoint:
    def test_backtest_sync_returns_report(self, client):
        response = client.post(
            "/api/backtest/sync/",
            data={
                "strategy": "sample",
                "feed_source": "synthetic",
                "synthetic_points": 20,
            },
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert "overview" in data
        assert "performance" in data
        assert "trades" in data

    def test_backtest_sync_missing_strategy(self, client):
        response = client.post(
            "/api/backtest/sync/",
            data={},
            content_type="application/json",
        )

        assert response.status_code == 400

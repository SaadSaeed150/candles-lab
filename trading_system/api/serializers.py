"""
DRF serializers for all API resources.
"""

from django.contrib.auth.models import User
from rest_framework import serializers

from trading_system.data.models import (
    BookTickerSnapshot,
    EquityCurve,
    MarketData,
    OrderBookSnapshot,
    StrategyRun,
    StrategySignal,
    TickerSnapshot,
    TradeRecord,
    UserProfile,
)


class MarketDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = MarketData
        fields = "__all__"


class TradeRecordSerializer(serializers.ModelSerializer):
    net_pnl = serializers.FloatField(read_only=True)

    class Meta:
        model = TradeRecord
        fields = "__all__"


class StrategyRunSerializer(serializers.ModelSerializer):
    trade_count = serializers.IntegerField(source="trades.count", read_only=True)

    class Meta:
        model = StrategyRun
        fields = "__all__"


class StrategySignalSerializer(serializers.ModelSerializer):
    class Meta:
        model = StrategySignal
        fields = "__all__"


class EquityCurveSerializer(serializers.ModelSerializer):
    class Meta:
        model = EquityCurve
        fields = "__all__"


class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = [
            "default_balance",
            "risk_tolerance",
            "timezone",
            "binance_api_key",
            "alpaca_api_key",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]


class UserSerializer(serializers.ModelSerializer):
    profile = UserProfileSerializer(read_only=True)

    class Meta:
        model = User
        fields = ["id", "username", "email", "date_joined", "profile"]
        read_only_fields = ["id", "date_joined"]


class RegisterSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)

    def validate_username(self, value: str) -> str:
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("Username already taken.")
        return value

    def validate_email(self, value: str) -> str:
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("Email already registered.")
        return value

    def create(self, validated_data: dict) -> User:
        user = User.objects.create_user(
            username=validated_data["username"],
            email=validated_data["email"],
            password=validated_data["password"],
        )
        UserProfile.objects.create(user=user)
        return user


class OrderBookSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderBookSnapshot
        fields = "__all__"


class TickerSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = TickerSnapshot
        fields = "__all__"


class BookTickerSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = BookTickerSnapshot
        fields = "__all__"


class SimulationRequestSerializer(serializers.Serializer):
    """Validates the payload for starting a new simulation run."""

    strategy = serializers.CharField(default="sample")
    symbol = serializers.CharField(default="BTCUSDT")
    exchange = serializers.CharField(default="binance")
    timeframe = serializers.CharField(default="1m")
    num_points = serializers.IntegerField(default=50, min_value=1, max_value=10_000)
    start_price = serializers.FloatField(default=105.0)
    initial_balance = serializers.FloatField(default=10_000.0)

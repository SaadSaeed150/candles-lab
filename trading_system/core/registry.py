"""
Strategy registry — maps string names to strategy classes for dynamic loading.

New strategies only need to be added here (or auto-discovered) to become
available system-wide.
"""

from __future__ import annotations

import importlib
import logging
from typing import Type

from trading_system.strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, Type[BaseStrategy]] = {}


def register(name: str, cls: Type[BaseStrategy]) -> None:
    """Register a strategy class under the given name."""
    if not issubclass(cls, BaseStrategy):
        raise TypeError(f"{cls.__name__} must be a subclass of BaseStrategy")
    _REGISTRY[name] = cls
    logger.debug("Registered strategy '%s' → %s", name, cls.__name__)


def get(name: str) -> Type[BaseStrategy]:
    """Look up a strategy class by its registered name."""
    if name not in _REGISTRY:
        raise KeyError(
            f"Strategy '{name}' not found. Available: {list(_REGISTRY.keys())}"
        )
    return _REGISTRY[name]


def available() -> list[str]:
    """Return the names of all registered strategies."""
    return list(_REGISTRY.keys())


def load_defaults() -> None:
    """Import built-in strategy modules so they self-register."""
    importlib.import_module("trading_system.strategies.sample_strategy")
    importlib.import_module("trading_system.strategies.ma_crossover")

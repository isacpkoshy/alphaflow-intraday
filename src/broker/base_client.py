"""
Base Abstract Broker Interface for Algorithmic Execution.
Provides a unified contract for Indian brokers (Dhan, Zerodha, Fyers).
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from enum import Enum


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_LOSS_LIMIT = "SL"
    STOP_LOSS_MARKET = "SL-M"


class ProductType(str, Enum):
    INTRADAY = "INTRADAY"   # MIS (5x Leverage)
    CNC = "CNC"             # Delivery / Cash (1x Leverage)
    MTF = "MTF"             # Margin Trade Funding (up to 4x)
    MARGIN = "MARGIN"       # Normal F&O


class TransactionType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class BaseBrokerClient(ABC):
    """Abstract interface defining required broker functionality."""

    @abstractmethod
    def connect(self) -> bool:
        """Validate credentials and establish connection."""
        pass

    @abstractmethod
    def get_funds(self) -> Dict[str, Any]:
        """Fetch available cash, utilized margin, and collateral."""
        pass

    @abstractmethod
    def get_profile(self) -> Dict[str, Any]:
        """Fetch user profile and trading segment permissions."""
        pass

    @abstractmethod
    def place_order(
        self,
        symbol: str,
        transaction_type: TransactionType,
        quantity: int,
        order_type: OrderType,
        product_type: ProductType,
        price: float = 0.0,
        trigger_price: float = 0.0,
        tag: str = ""
    ) -> Dict[str, Any]:
        """Place a live equity or derivative order."""
        pass

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order."""
        pass

    @abstractmethod
    def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """Fetch the latest status of an order."""
        pass

    @abstractmethod
    def get_positions(self) -> List[Dict[str, Any]]:
        """Fetch all open intraday and delivery positions."""
        pass

    @abstractmethod
    def place_gtt_stop(
        self,
        symbol: str,
        transaction_type: TransactionType,
        quantity: int,
        trigger_price: float,
        limit_price: float,
        product_type: ProductType = ProductType.CNC
    ) -> Dict[str, Any]:
        """Place a server-side broker GTT forever stop loss."""
        pass

    @abstractmethod
    def cancel_gtt_stop(self, gtt_id: str) -> bool:
        """Cancel an active GTT stop order."""
        pass

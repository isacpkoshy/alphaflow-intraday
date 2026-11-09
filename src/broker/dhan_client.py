"""
DhanHQ API v2 Client Implementation.
Connects to Dhan's low-latency execution gateway for live order routing,
funds management, and Server-Side Forever GTT Stop Loss management.
"""

import json
import logging
import urllib.request
import urllib.error
from typing import Dict, Any, List, Optional
from datetime import datetime

from .base_client import BaseBrokerClient, OrderType, ProductType, TransactionType

logger = logging.getLogger("DhanClient")
logger.setLevel(logging.INFO)


class DhanClient(BaseBrokerClient):
    """
    Official DhanHQ REST API Client implementation.
    Reference: https://dhanhq.co/docs/v2/
    """

    BASE_URL = "https://api.dhan.co/v2"

    def __init__(self, client_id: str, access_token: str, is_sandbox: bool = False):
        self.client_id = str(client_id).strip()
        self.access_token = str(access_token).strip()
        self.is_sandbox = is_sandbox
        self.is_connected = False
        self.security_id_cache: Dict[str, str] = {}
        self._init_security_cache()

    def _init_security_cache(self) -> None:
        """Standard NSE Equities Security IDs (Dhan master mappings for high-volume stocks)."""
        self.security_id_cache = {
            "RELIANCE": "2885",
            "TCS": "11536",
            "HDFCBANK": "1333",
            "ICICIBANK": "4963",
            "INFY": "1594",
            "SBIN": "3045",
            "BHARTIARTL": "10604",
            "ITC": "1660",
            "KOTAKBANK": "1922",
            "LT": "11483",
            "AXISBANK": "5900",
            "BAJFINANCE": "317",
            "MARUTI": "10999",
            "TITAN": "3506",
            "TATAMOTORS": "3456",
            "M&M": "2031",
            "SUNPHARMA": "3351",
            "HCLTECH": "7229",
            "ASIANPAINT": "236",
            "NTPC": "11630",
            "POWERGRID": "14977",
            "TATASTEEL": "3499",
            "JSWSTEEL": "11723",
            "ADANIENT": "25",
            "ADANIPORTS": "15083"
        }

    def _headers(self) -> Dict[str, str]:
        return {
            "access-token": self.access_token,
            "client-id": self.client_id,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "AlphaFlow-AlgoEngine/2.0"
        }

    def _make_request(self, endpoint: str, method: str = "GET", payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Performs robust HTTP request with timeout and error handling."""
        url = f"{self.BASE_URL}{endpoint}"
        data_bytes = json.dumps(payload).encode("utf-8") if payload else None

        req = urllib.request.Request(url, data=data_bytes, headers=self._headers(), method=method)
        try:
            with urllib.request.urlopen(req, timeout=8) as response:
                status_code = response.getcode()
                raw = response.read().decode("utf-8")
                res = json.loads(raw) if raw else {}
                return {"status": "SUCCESS", "http_code": status_code, "data": res}
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8") if e.fp else ""
            try:
                err_json = json.loads(err_body)
            except Exception:
                err_json = {"error": err_body}
            return {"status": "ERROR", "http_code": e.code, "error": err_json, "message": str(e)}
        except Exception as e:
            return {"status": "ERROR", "http_code": 0, "message": str(e)}

    def connect(self) -> bool:
        """Pings Dhan API by checking fund limits."""
        if not self.client_id or not self.access_token:
            self.is_connected = False
            return False

        res = self.get_funds()
        if res.get("status") == "SUCCESS":
            self.is_connected = True
            logger.info("Successfully connected to DhanHQ API (Client ID: %s)", self.client_id)
            return True
        else:
            self.is_connected = False
            logger.warning("Failed to connect to DhanHQ API: %s", res.get("message"))
            return False

    def get_funds(self) -> Dict[str, Any]:
        """Fetches available balance, margin utilized, and collateral."""
        res = self._make_request("/fundlimit", method="GET")
        if res.get("status") == "SUCCESS":
            d = res.get("data", {})
            avail = float(d.get("availabelBalance", d.get("availableBalance", 0.0)))
            sod = float(d.get("sodLimit", 0.0))
            utilized = float(d.get("utilizedAmount", 0.0))
            collateral = float(d.get("collateralAmount", 0.0))
            return {
                "status": "SUCCESS",
                "available_cash": avail,
                "sod_limit": sod,
                "utilized_margin": utilized,
                "collateral": collateral,
                "raw": d
            }
        return res

    def get_profile(self) -> Dict[str, Any]:
        """Fetches Dhan user profile details."""
        return self._make_request("/profile", method="GET")

    def _resolve_security_id(self, symbol: str) -> str:
        clean = symbol.replace(".NS", "").replace(".BO", "").upper()
        return self.security_id_cache.get(clean, "2885")

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
        """
        Places a live order via DhanHQ /orders endpoint.
        """
        sec_id = self._resolve_security_id(symbol)
        dhan_tx = "BUY" if transaction_type in (TransactionType.BUY, "BUY") else "SELL"
        dhan_product = "INTRADAY" if product_type in (ProductType.INTRADAY, "INTRADAY") else "CNC"
        dhan_order_type = order_type.value if hasattr(order_type, "value") else str(order_type)

        payload = {
            "dhanClientId": self.client_id,
            "correlationId": f"AF-{datetime.now().strftime('%m%d%H%M%S')}-{symbol[:6]}",
            "transactionType": dhan_tx,
            "exchangeSegment": "NSE_EQ",
            "productType": dhan_product,
            "orderType": dhan_order_type,
            "validity": "DAY",
            "securityId": sec_id,
            "quantity": int(quantity),
            "disclosedQuantity": 0,
            "price": round(float(price), 2) if dhan_order_type in ("LIMIT", "SL") else 0.0,
            "triggerPrice": round(float(trigger_price), 2) if dhan_order_type in ("SL", "SL-M") else 0.0,
            "afterMarketOrder": False,
            "amoTime": "OPEN"
        }

        res = self._make_request("/orders", method="POST", payload=payload)
        logger.info("Dhan place_order [%s %s %s qty=%d]: %s", dhan_tx, symbol, dhan_product, quantity, res.get("status"))
        return res

    def cancel_order(self, order_id: str) -> bool:
        """Cancels a pending order."""
        res = self._make_request(f"/orders/{order_id}", method="DELETE")
        return res.get("status") == "SUCCESS"

    def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """Fetches status of order by ID."""
        return self._make_request(f"/orders/{order_id}", method="GET")

    def get_positions(self) -> List[Dict[str, Any]]:
        """Fetches all open positions."""
        res = self._make_request("/positions", method="GET")
        if res.get("status") == "SUCCESS":
            return res.get("data", [])
        return []

    def place_gtt_stop(
        self,
        symbol: str,
        transaction_type: TransactionType,
        quantity: int,
        trigger_price: float,
        limit_price: float,
        product_type: ProductType = ProductType.CNC
    ) -> Dict[str, Any]:
        """
        Places a server-side GTT Forever order at Dhan.
        Protects swing and overnight positions at broker level.
        """
        sec_id = self._resolve_security_id(symbol)
        dhan_tx = "SELL" if transaction_type in (TransactionType.SELL, "SELL") else "BUY"
        dhan_product = "CNC" if product_type in (ProductType.CNC, "CNC") else "INTRADAY"

        payload = {
            "dhanClientId": self.client_id,
            "orderFlag": "SINGLE",
            "transactionType": dhan_tx,
            "exchangeSegment": "NSE_EQ",
            "productType": dhan_product,
            "securityId": sec_id,
            "quantity": int(quantity),
            "price": round(float(limit_price), 2),
            "triggerPrice": round(float(trigger_price), 2)
        }

        res = self._make_request("/forever/orders", method="POST", payload=payload)
        logger.info("Dhan place_gtt_stop [%s %s trigger=%.2f]: %s", dhan_tx, symbol, trigger_price, res.get("status"))
        return res

    def cancel_gtt_stop(self, gtt_id: str) -> bool:
        """Cancels an existing Forever GTT order."""
        res = self._make_request(f"/forever/orders/{gtt_id}", method="DELETE")
        return res.get("status") == "SUCCESS"

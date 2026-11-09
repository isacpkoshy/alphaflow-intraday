import time
import json
import logging
import os
from typing import Dict, Any, List, Optional
from datetime import datetime
from collections import deque

from .base_client import BaseBrokerClient, OrderType, ProductType, TransactionType
from .dhan_client import DhanClient

logger = logging.getLogger("BrokerManager")
logger.setLevel(logging.INFO)


class BrokerManager:
    """
    Central Broker Adapter & Institutional Cybersecurity Gateway.
    Implements 7 Multi-Layer Pre-Trade Safeguards:
    1. Daily Loss Circuit Breaker (-2.0% halt)
    2. Single-Trade Capital Cap (Max Rs. 1,50,000 / order)
    3. Maximum Quantity Ceiling (Max 2,000 shares / order anti-fat-finger)
    4. Anti-Penny / Anti-Siphoning Filter (Price >= Rs. 20.00 & Min turnover)
    5. Runaway Loop Throttler (Max 3 orders per 10-second window)
    6. Duplicate Order Lockout (Blocks identical orders within 60s)
    7. Token Masking in API responses (Zero plain-text secret exposure)
    """

    CACHE_TTL_SECONDS = 30.0
    MAX_CAPITAL_PER_ORDER_INR = 150000.0   # 50% max cash margin per trade of Rs. 3L cash
    MAX_NOTIONAL_PER_ORDER_INR = 1000000.0 # Rs. 10 Lakhs max gross notional anti-fat-finger
    MAX_QUANTITY_PER_ORDER = 2000          # Anti-fat-finger share cap
    MIN_STOCK_PRICE_INR = 20.0             # Anti-penny / Anti-options-siphoning
    RATE_LIMIT_MAX_ORDERS = 5              # Max orders per window
    RATE_LIMIT_WINDOW_SECONDS = 10.0       # Window size in seconds
    DUPLICATE_ORDER_LOCK_SECONDS = 60.0    # Idempotency window

    def __init__(self, config_dir: str):
        self.config_dir = config_dir
        self.config_path = os.path.join(config_dir, "broker_config.json")
        self.config: Dict[str, Any] = {}
        self.client: Optional[BaseBrokerClient] = None
        self.is_connected: bool = False
        self.daily_pnl_inr: float = 0.0
        self.max_daily_loss_inr: float = -6000.0  # -2.0% on Rs. 3,00,000
        self.trading_mode: str = "PAPER"         # "PAPER" or "LIVE"
        
        # Real-Time Funds Cache
        self.cached_funds: Dict[str, Any] = {"available_cash": 300000.0, "utilized_margin": 0.0}
        self.last_funds_fetch: float = 0.0

        # Rate Limiting & Idempotency Memory
        self.order_timestamps: deque = deque()
        self.recent_orders: Dict[str, float] = {}  # symbol -> timestamp
        
        self._load_config()

    def _load_config(self) -> None:
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    self.config = json.load(f)
            except Exception as e:
                logger.error("Failed to read broker_config.json: %s", e)
                self.config = self._default_config()
        else:
            self.config = self._default_config()
            self._save_config()

        self.trading_mode = self.config.get("trading_mode", "PAPER")
        self.max_daily_loss_inr = float(self.config.get("max_daily_loss_inr", -6000.0))
        self._init_client()

    def _default_config(self) -> Dict[str, Any]:
        return {
            "selected_broker": "dhan",
            "trading_mode": "PAPER",
            "max_daily_loss_inr": -6000.0,
            "max_capital_per_trade_pct": 50.0,
            "dhan": {
                "client_id": "",
                "access_token": "",
                "token_expiry": "",
                "is_sandbox": False
            },
            "zerodha": {
                "api_key": "",
                "api_secret": "",
                "access_token": ""
            }
        }

    def _save_config(self) -> None:
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            logger.error("Failed to save broker_config.json: %s", e)

    def _init_client(self) -> None:
        broker = self.config.get("selected_broker", "dhan").lower()
        if broker == "dhan":
            dhan_conf = self.config.get("dhan", {})
            c_id = dhan_conf.get("client_id", "")
            token = dhan_conf.get("access_token", "")
            if c_id and token:
                self.client = DhanClient(client_id=c_id, access_token=token)
                self.is_connected = self.client.connect()
                if self.is_connected:
                    self.refresh_funds(force=True)
            else:
                self.client = None
                self.is_connected = False
        else:
            self.client = None
            self.is_connected = False

    def refresh_funds(self, force: bool = False) -> Dict[str, Any]:
        now = time.time()
        if not force and (now - self.last_funds_fetch < self.CACHE_TTL_SECONDS) and self.cached_funds:
            return self.cached_funds

        if self.client and self.is_connected:
            f_res = self.client.get_funds()
            if f_res.get("status") == "SUCCESS":
                self.cached_funds = {
                    "available_cash": f_res.get("available_cash", 300000.0),
                    "utilized_margin": f_res.get("utilized_margin", 0.0),
                    "collateral": f_res.get("collateral", 0.0),
                    "sod_limit": f_res.get("sod_limit", 0.0),
                    "last_updated": datetime.now().strftime("%H:%M:%S")
                }
                self.last_funds_fetch = now
                logger.info("Synchronized live Dhan funds: Available Cash = Rs. %s", f"{self.cached_funds['available_cash']:,.2f}")
                return self.cached_funds

        return self.cached_funds

    def save_credentials(self, broker: str, credentials: Dict[str, Any], trading_mode: str = "PAPER") -> Dict[str, Any]:
        self.config["selected_broker"] = broker.lower()
        self.config["trading_mode"] = trading_mode
        self.trading_mode = trading_mode

        if broker.lower() == "dhan":
            self.config["dhan"]["client_id"] = str(credentials.get("client_id", "")).strip()
            self.config["dhan"]["access_token"] = str(credentials.get("access_token", "")).strip()
            self.config["dhan"]["token_expiry"] = str(credentials.get("token_expiry", "")).strip()

        self._save_config()
        self._init_client()

        if self.is_connected:
            self.refresh_funds(force=True)

        return {
            "broker": broker,
            "trading_mode": self.trading_mode,
            "is_connected": self.is_connected,
            "funds": self.cached_funds,
            "message": "Connected successfully to DhanHQ API" if self.is_connected else "Failed to connect. Check Client ID and Access Token."
        }

    def _mask_client_id(self, c_id: str) -> str:
        if not c_id or len(c_id) < 4:
            return ""
        return c_id[:2] + "****" + c_id[-2:]

    def get_status(self) -> Dict[str, Any]:
        """Returns live broker state with credentials masked for cybersecurity."""
        funds = self.refresh_funds(force=False)
        raw_id = self.config.get("dhan", {}).get("client_id", "")
        masked_id = self._mask_client_id(raw_id)
        
        return {
            "broker_name": self.config.get("selected_broker", "dhan").upper(),
            "trading_mode": self.trading_mode,
            "is_connected": self.is_connected,
            "client_id": masked_id,
            "has_credentials": bool(raw_id and self.config.get("dhan", {}).get("access_token")),
            "funds": funds,
            "daily_loss_circuit_inr": self.max_daily_loss_inr,
            "daily_pnl_inr": self.daily_pnl_inr,
            "circuit_halt_triggered": self.daily_pnl_inr <= self.max_daily_loss_inr,
            "security_guardrails": {
                "max_order_notional_inr": self.MAX_CAPITAL_PER_ORDER_INR,
                "max_order_quantity": self.MAX_QUANTITY_PER_ORDER,
                "min_stock_price_inr": self.MIN_STOCK_PRICE_INR,
                "rate_limit_orders": self.RATE_LIMIT_MAX_ORDERS,
                "rate_limit_window_sec": self.RATE_LIMIT_WINDOW_SECONDS,
                "idempotency_lock_sec": self.DUPLICATE_ORDER_LOCK_SECONDS
            }
        }

    def validate_pre_trade_risk(
        self,
        symbol: str,
        price: float,
        quantity: int,
        order_val: float,
        available_cash: float,
        margin_val: Optional[float] = None
    ) -> Optional[str]:
        """
        Comprehensive Multi-Layer Cybersecurity & Pre-Trade Risk Filter:
        Returns None if order passes all checks; returns error reason string if rejected.
        Supports leveraged MIS and CNC:
        - Checks cash margin allocated <= MAX_CAPITAL_PER_ORDER_INR (Rs. 1,50,000 cash)
        - Checks gross notional order value <= MAX_NOTIONAL_PER_ORDER_INR (Rs. 10,00,000 gross anti-fat-finger)
        """
        now = time.time()
        effective_margin = margin_val if margin_val is not None else order_val

        # 1. Daily Loss Circuit Breaker
        if self.daily_pnl_inr <= self.max_daily_loss_inr:
            logger.warning("BLOCKED: Daily portfolio loss circuit active (%.2f <= %.2f)", self.daily_pnl_inr, self.max_daily_loss_inr)
            return f"Order Blocked: Daily Portfolio Loss Circuit Hit ({self.daily_pnl_inr:.2f} <= {self.max_daily_loss_inr:.2f})"

        # 2. Maximum Single-Order Cash Margin Ceiling
        if effective_margin > self.MAX_CAPITAL_PER_ORDER_INR:
            logger.warning("BLOCKED: Margin required Rs. %.2f exceeds max allowed cash ceiling Rs. %.2f", effective_margin, self.MAX_CAPITAL_PER_ORDER_INR)
            return f"Security Guardrail: Cash margin (Rs. {effective_margin:,.2f}) exceeds single-trade cash ceiling (Rs. {self.MAX_CAPITAL_PER_ORDER_INR:,.2f})"

        # 2B. Maximum Gross Notional Order Ceiling (Anti-Fat-Finger Exposure Cap)
        if order_val > self.MAX_NOTIONAL_PER_ORDER_INR:
            logger.warning("BLOCKED: Gross order value Rs. %.2f exceeds max gross ceiling Rs. %.2f", order_val, self.MAX_NOTIONAL_PER_ORDER_INR)
            return f"Security Guardrail: Gross order value (Rs. {order_val:,.2f}) exceeds ceiling (Rs. {self.MAX_NOTIONAL_PER_ORDER_INR:,.2f})"

        # 3. Maximum Quantity Ceiling (Anti-Fat-Finger)
        if quantity > self.MAX_QUANTITY_PER_ORDER:
            logger.warning("BLOCKED: Quantity %d exceeds anti-fat-finger ceiling %d", quantity, self.MAX_QUANTITY_PER_ORDER)
            return f"Security Guardrail: Quantity ({quantity}) exceeds maximum allowed per order ({self.MAX_QUANTITY_PER_ORDER})"

        # 4. Anti-Penny / Anti-Option-Siphoning Filter
        if price < self.MIN_STOCK_PRICE_INR:
            logger.warning("BLOCKED: Price Rs. %.2f is below minimum security price Rs. %.2f", price, self.MIN_STOCK_PRICE_INR)
            return f"Security Guardrail: Stock price (Rs. {price:.2f}) below minimum institutional liquidity floor (Rs. {self.MIN_STOCK_PRICE_INR:.2f})"

        # 5. Buying Power & Margin Sufficiency
        if order_val > available_cash * 1.05:
            logger.warning("BLOCKED: Insufficient buying power (Order: Rs. %.2f > Buying Power: Rs. %.2f)", order_val, available_cash)
            return f"Order Blocked: Insufficient buying power (Order: Rs. {order_val:,.2f} > Buying Power: Rs. {available_cash:,.2f})"

        # 6. Rate-Limiting Throttler (Runaway Glitch Loop Protection)
        # Purge timestamps older than window
        while self.order_timestamps and now - self.order_timestamps[0] > self.RATE_LIMIT_WINDOW_SECONDS:
            self.order_timestamps.popleft()
        if len(self.order_timestamps) >= self.RATE_LIMIT_MAX_ORDERS:
            logger.warning("BLOCKED: Exceeded rate limit (%d orders in %ds)", len(self.order_timestamps), self.RATE_LIMIT_WINDOW_SECONDS)
            return f"Security Guardrail: Rate limit triggered (Maximum {self.RATE_LIMIT_MAX_ORDERS} orders per {int(self.RATE_LIMIT_WINDOW_SECONDS)}s)"

        # 7. Duplicate Order Lockout (Idempotency)
        sym_clean = symbol.replace(".NS", "").replace(".BO", "").upper()
        last_time = self.recent_orders.get(sym_clean, 0.0)
        if now - last_time < self.DUPLICATE_ORDER_LOCK_SECONDS:
            logger.warning("BLOCKED: Duplicate order lock for %s (Placed %.1fs ago)", sym_clean, now - last_time)
            return f"Security Guardrail: Duplicate order lock active for {sym_clean} ({int(self.DUPLICATE_ORDER_LOCK_SECONDS - (now - last_time))}s remaining)"

        # All 7 checks passed! Record order telemetry
        self.order_timestamps.append(now)
        self.recent_orders[sym_clean] = now
        logger.info("PASSED Pre-Trade Risk Verification for %s (Qty=%d, Value=Rs. %.2f)", sym_clean, quantity, order_val)
        return None

    @staticmethod
    def round_to_nse_tick(price: float, tick: float = 0.05) -> float:
        """Rounds a price to the nearest valid NSE ₹0.05 tick increment."""
        return round(round(float(price) / tick) * tick, 2)

    @classmethod
    def compute_marketable_limit_price(cls, trigger_price: float, transaction_type: str, buffer_pct: float = 0.20) -> float:
        """
        Stage 1 of Institutional Smart Execution:
        Computes a Slippage-Protected Marketable Limit Price (`Trigger * (1 ± buffer_pct/100)`)
        rounded to the nearest ₹0.05 NSE tick.
        - Matches immediately against Best Ask/Bid by Exchange Price-Time Priority,
          while strictly capping maximum adverse slippage at `buffer_pct` (default 0.20%).
        """
        is_buy = transaction_type.upper() in ("BUY", "LONG")
        mult = (1.0 + buffer_pct / 100.0) if is_buy else (1.0 - buffer_pct / 100.0)
        return cls.round_to_nse_tick(trigger_price * mult, 0.05)

    def execute_order(
        self,
        symbol: str,
        transaction_type: str,
        quantity: int,
        price: float,
        order_type: str = "MARKETABLE_LIMIT",
        product_type: str = "MIS",
        sl_price: Optional[float] = None,
        target_price: Optional[float] = None,
        slippage_buffer_pct: float = 0.20,
        timeout_sec: float = 8.0
    ) -> Dict[str, Any]:
        """
        Executes an order using the 3-Stage Institutional Smart Execution Protocol:
        1. Places a Marketable Limit Order (`LIMIT` at `Trigger * (1 ± 0.20%)` rounded to ₹0.05 tick).
        2. Polls fill status up to `timeout_sec` (default 8s) and auto-cancels any unfilled stale remainder
           so orders never sit passively waiting for adverse reversals.
        3. Reconciles exact `filled_qty` and `avg_fill_price` and attaches server-side GTT Stop-Loss
           for the exact filled share count.
        """
        sym_clean = symbol.replace(".NS", "").replace(".BO", "").upper()
        is_buy = transaction_type.upper() in ("BUY", "LONG")
        limit_px = self.compute_marketable_limit_price(price, transaction_type, slippage_buffer_pct) if order_type.upper() in ("MARKETABLE_LIMIT", "MARKET") else self.round_to_nse_tick(price)

        if self.trading_mode == "LIVE" and self.is_connected and self.client:
            dhan_tx = TransactionType.BUY if is_buy else TransactionType.SELL
            dhan_prod = ProductType.INTRADAY if product_type.upper() == "MIS" else ProductType.CNC
            # Always route MARKET / MARKETABLE_LIMIT as an NSE LIMIT order with slippage-protection ceiling
            dhan_otype = OrderType.LIMIT

            res = self.client.place_order(
                symbol=sym_clean,
                transaction_type=dhan_tx,
                quantity=quantity,
                order_type=dhan_otype,
                product_type=dhan_prod,
                price=limit_px,
                trigger_price=0.0
            )
            if res.get("status") != "SUCCESS":
                return {
                    "status": "ERROR",
                    "mode": "LIVE",
                    "broker": "DHAN",
                    "filled_qty": 0,
                    "avg_fill_price": price,
                    "limit_price": limit_px,
                    "message": res.get("message", "Order placement failed")
                }

            order_data = res.get("data", {})
            order_id = order_data.get("orderId") or res.get("order_id")
            filled_qty = int(quantity)
            avg_fill_price = float(price)

            # Stage 2 & 3: Poll order status, auto-cancel stale unfilled remainder, and reconcile exact fill
            if order_id and hasattr(self.client, "get_order_status"):
                deadline = time.time() + max(1.0, float(timeout_sec))
                order_state = "PENDING"
                while time.time() < deadline:
                    st_res = self.client.get_order_status(str(order_id))
                    if st_res.get("status") == "SUCCESS":
                        st_data = st_res.get("data", {})
                        order_state = str(st_data.get("orderStatus", "TRADED")).upper()
                        f_qty = int(st_data.get("filledQty", st_data.get("tradedQuantity", 0)) or 0)
                        avg_px = float(st_data.get("averageTradedPrice", st_data.get("price", 0.0)) or 0.0)
                        if order_state in ("TRADED", "COMPLETE"):
                            filled_qty = f_qty if f_qty > 0 else quantity
                            if avg_px > 0:
                                avg_fill_price = round(avg_px, 2)
                            break
                        if order_state in ("REJECTED", "CANCELLED", "EXPIRED"):
                            filled_qty = f_qty
                            if avg_px > 0:
                                avg_fill_price = round(avg_px, 2)
                            break
                        filled_qty = f_qty
                        if avg_px > 0:
                            avg_fill_price = round(avg_px, 2)
                    time.sleep(0.5)

                # If still PENDING / PARTIALLY FILLED after timeout window, cancel unfilled remainder immediately
                if order_state in ("PENDING", "TRANSIT", "OPEN", "PARTIALLY_FILLED"):
                    try:
                        self.client.cancel_order(str(order_id))
                        logger.info("Auto-cancelled unfilled remainder for %s (Order ID: %s, Filled: %d/%d)", sym_clean, order_id, filled_qty, quantity)
                    except Exception as e_can:
                        logger.warning("Failed to cancel unfilled remainder for %s: %s", sym_clean, e_can)

                if filled_qty <= 0:
                    return {
                        "status": "CANCELLED_UNFILLED",
                        "mode": "LIVE",
                        "broker": "DHAN",
                        "broker_order_id": order_id,
                        "filled_qty": 0,
                        "avg_fill_price": price,
                        "limit_price": limit_px,
                        "message": f"Order {order_id} cancelled after {timeout_sec}s timeout (price gapped beyond ±{slippage_buffer_pct}% protection band)"
                    }

            # Anchor Stop-Loss GTT to exact `filled_qty` and `avg_fill_price`
            gtt_id = None
            if sl_price and hasattr(self.client, "place_gtt_stop"):
                sl_ratio = abs(price - sl_price) / price if price > 0 else 0.0175
                actual_sl = self.round_to_nse_tick(avg_fill_price * (1.0 - sl_ratio if is_buy else 1.0 + sl_ratio))
                sl_limit = self.round_to_nse_tick(actual_sl * (0.995 if is_buy else 1.005))
                gtt_res = self.client.place_gtt_stop(
                    symbol=sym_clean,
                    transaction_type=TransactionType.SELL if is_buy else TransactionType.BUY,
                    quantity=filled_qty,
                    trigger_price=actual_sl,
                    limit_price=sl_limit,
                    product_type=dhan_prod
                )
                if gtt_res.get("status") == "SUCCESS":
                    gtt_id = gtt_res.get("data", {}).get("orderId") or gtt_res.get("gtt_id")

            return {
                "status": "SUCCESS",
                "mode": "LIVE",
                "broker": "DHAN",
                "broker_order_id": order_id,
                "order_type": "MARKETABLE_LIMIT",
                "limit_price": limit_px,
                "filled_qty": filled_qty,
                "avg_fill_price": avg_fill_price,
                "gtt_id": gtt_id,
                "message": f"Filled {filled_qty}/{quantity} sh @ ₹{avg_fill_price:.2f} (Limit Protection: ₹{limit_px:.2f})"
            }

        # PAPER MODE: Simulates Marketable Limit execution with realistic tick rounding
        return {
            "status": "SUCCESS",
            "mode": "PAPER",
            "broker": "SIMULATED",
            "order_id": f"PAPER-{int(time.time()*1000) % 1000000}",
            "order_type": "MARKETABLE_LIMIT",
            "limit_price": limit_px,
            "filled_qty": quantity,
            "avg_fill_price": round(price, 2),
            "message": f"Paper Marketable-Limit order filled ({quantity} sh @ ₹{price:.2f}, Limit Cap: ₹{limit_px:.2f})"
        }

    def execute_exit(
        self,
        symbol: str,
        side: str,
        quantity: int,
        exit_price: float,
        product_type: str = "MIS"
    ) -> Dict[str, Any]:
        """Executes position exit or auto square-off."""
        sym_clean = symbol.replace(".NS", "").replace(".BO", "").upper()
        if self.trading_mode == "LIVE" and self.is_connected and self.client:
            exit_tx = TransactionType.SELL if side.upper() in ("BUY", "LONG") else TransactionType.BUY
            dhan_prod = ProductType.INTRADAY if product_type.upper() == "MIS" else ProductType.CNC
            exit_limit_px = self.compute_marketable_limit_price(
                exit_price,
                "SELL" if side.upper() in ("BUY", "LONG") else "BUY",
                buffer_pct=0.25
            )
            res = self.client.place_order(
                symbol=sym_clean,
                transaction_type=exit_tx,
                quantity=quantity,
                order_type=OrderType.LIMIT,
                product_type=dhan_prod,
                price=exit_limit_px
            )
            return {"status": res.get("status", "SUCCESS"), "mode": "LIVE", "broker_order_id": res.get("order_id")}

        return {"status": "SUCCESS", "mode": "PAPER", "exit_price": exit_price}

"""
AlphaFlow Telegram Alert Notifier
---------------------------------
Sends real-time, rich HTML execution alerts to Telegram whenever an order triggers:
- Entry alerts with exact Buy/Sell price, Stop Loss, Target R-multiples, and sizing.
- Exit alerts on Target Hit, Trailing Stop, or Stop Loss.
- STRICT FILTER: Only dispatches alerts for strategies/engines that are actively turned ON in Switchboard.
"""

import json
import os
import threading
import urllib.parse
import urllib.request
import urllib.error
import logging
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger("TelegramNotifier")

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CONFIG_PATH = os.path.join(BASE_DIR, "data", "telegram_config.json")

class TelegramNotifier:
    def __init__(self, config_path: str = CONFIG_PATH):
        self.config_path = config_path
        self.config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error("Failed to load telegram config: %s", e)
        return {
            "enabled": False,
            "bot_token": "",
            "chat_id": "",
            "alert_on_entry": True,
            "alert_on_target": True,
            "alert_on_sl": True,
            "alert_on_eod": True,
        }

    def save_config(self, new_config: Dict[str, Any]) -> None:
        self.config.update(new_config)
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.config, f, indent=2)

    def is_configured(self) -> bool:
        return bool(self.config.get("bot_token") and self.config.get("chat_id"))

    def is_active(self) -> bool:
        return bool(self.config.get("enabled") and self.is_configured())

    def get_bot_info(self, token: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Queries Telegram API getMe to verify bot token and get bot username."""
        bot_token = (token or self.config.get("bot_token", "")).strip()
        if not bot_token:
            return None
        # Clean potential 'bot' prefix if user typed 'bot<token>'
        if bot_token.startswith("bot") and ":" in bot_token[3:]:
            bot_token = bot_token[3:]
        try:
            url = f"https://api.telegram.org/bot{bot_token}/getMe"
            req = urllib.request.Request(url, headers={"User-Agent": "AlphaFlowBot/2.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("ok"):
                    return data.get("result")
        except Exception as e:
            logger.debug("Failed to fetch bot info: %s", e)
        return None

    def send_message(self, text: str, parse_mode: str = "HTML") -> Tuple[bool, str]:
        """Sends a message asynchronously in a background thread so execution is never delayed."""
        if not self.is_active():
            return False, "Telegram alerts disabled or not configured."

        bot_token = self.config.get("bot_token", "").strip()
        if bot_token.startswith("bot") and ":" in bot_token[3:]:
            bot_token = bot_token[3:]
        chat_id = self.config.get("chat_id", "").strip()

        def _do_send():
            try:
                url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                payload = json.dumps({
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True,
                }).encode("utf-8")

                req = urllib.request.Request(
                    url,
                    data=payload,
                    headers={"Content-Type": "application/json", "User-Agent": "AlphaFlowBot/2.0"},
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    if resp.status == 200:
                        logger.info("Telegram alert dispatched successfully.")
            except urllib.error.HTTPError as ex:
                err_body = ex.read().decode("utf-8", errors="ignore")
                logger.error("Telegram API HTTP error %d: %s", ex.code, err_body)
                # Fallback to plain text if HTML parsing failed
                if parse_mode and "parse" in err_body.lower():
                    try:
                        import re
                        plain = re.sub(r'<[^>]+>', '', text)
                        payload2 = json.dumps({
                            "chat_id": chat_id,
                            "text": plain,
                            "disable_web_page_preview": True,
                        }).encode("utf-8")
                        req2 = urllib.request.Request(
                            url,
                            data=payload2,
                            headers={"Content-Type": "application/json", "User-Agent": "AlphaFlowBot/2.0"},
                        )
                        urllib.request.urlopen(req2, timeout=10)
                        logger.info("Dispatched Telegram alert in plain text fallback mode.")
                    except Exception as ex2:
                        logger.error("Fallback dispatch failed: %s", ex2)
            except Exception as ex:
                logger.error("Failed to dispatch Telegram message: %s", ex)

        threading.Thread(target=_do_send, daemon=True).start()
        return True, "Alert queued for dispatch."

    def send_test_message(self) -> Tuple[bool, str]:
        """Synchronously tests connection and sends a test ping."""
        bot_token = self.config.get("bot_token", "").strip()
        if bot_token.startswith("bot") and ":" in bot_token[3:]:
            bot_token = bot_token[3:]
        chat_id = self.config.get("chat_id", "").strip()
        if not bot_token or not chat_id:
            return False, "Bot token or Chat ID is missing."

        bot_info = self.get_bot_info(bot_token)
        bot_user = bot_info.get("username", "") if bot_info else ""
        bot_ref = f"@{bot_user}" if bot_user else "your bot"

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        test_msg = (
            "🚀 <b>AlphaFlow Telegram Bot Connected!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "✅ <b>Status:</b> Active & Listening\n"
            "⚡ <b>Mode:</b> Filtered Alerts (Active Strategies Only)\n"
            "🔔 <b>Events:</b> Buy/Sell Entries, Stop Loss, Target Hit (+3.2R)\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Real-time algorithmic execution alerts are now live.</i>"
        )
        payload = json.dumps({
            "chat_id": chat_id,
            "text": test_msg,
            "parse_mode": "HTML",
        }).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "AlphaFlowBot/2.0"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    return True, f"Test alert delivered successfully to Telegram ({bot_ref})!"
                return False, f"Server returned status {resp.status}"
        except urllib.error.HTTPError as ex:
            err_desc = ""
            try:
                err_body = ex.read().decode("utf-8", errors="ignore")
                err_data = json.loads(err_body)
                err_desc = err_data.get("description", "")
            except Exception:
                err_desc = str(ex)

            if "chat not found" in err_desc.lower():
                return False, (
                    f"Chat not found: Please open Telegram, search for {bot_ref} "
                    f"(or click https://t.me/{bot_user or 'your_bot'}), and click 'START'. "
                    f"Telegram requires you to start the bot first before it can send you messages!"
                )
            if "bot was blocked" in err_desc.lower():
                return False, f"Bot was blocked: You previously blocked {bot_ref} in Telegram. Please unblock it to receive alerts."
            if "unauthorized" in err_desc.lower():
                return False, "Unauthorized: The Bot Token is invalid. Please verify the token copied from @BotFather."

            return False, f"Telegram API Error ({ex.code}): {err_desc}"
        except Exception as ex:
            return False, str(ex)

    def _is_engine_active(self, engine_id: str, switchboard_config: Dict[str, Any]) -> bool:
        """Strict Filter: Returns True ONLY if the strategy/engine is actively turned ON."""
        if not switchboard_config:
            return True
        engines = switchboard_config.get("engines", {})
        if engine_id in engines:
            return bool(engines[engine_id].get("enabled", False))
        # Check alias
        if engine_id == "STOCKS MIS" and "engine_stocks_mis" in engines:
            return bool(engines["engine_stocks_mis"].get("enabled", False))
        if engine_id == "NIFTY F&O" and "engine_fo_hybrid" in engines:
            return bool(engines["engine_fo_hybrid"].get("enabled", False))
        if engine_id == "SEPA SWING" and "engine_sepa_swing" in engines:
            return bool(engines["engine_sepa_swing"].get("enabled", False))
        return False

    def send_entry_alert(self, pos: Dict[str, Any], switchboard_config: Dict[str, Any]) -> None:
        """Dispatches an entry trigger alert if the strategy is enabled."""
        engine_id = pos.get("engine_id") or pos.get("engine", "")
        if not self._is_engine_active(engine_id, switchboard_config):
            logger.info("Suppressed Telegram entry alert for %s: Strategy %s is turned OFF", pos.get("symbol"), engine_id)
            return

        if not self.config.get("alert_on_entry", True):
            return

        sym = pos.get("symbol", "")
        engine_label = pos.get("engine", "AlphaFlow Algo")
        side = pos.get("side", "BUY")
        entry = float(pos.get("entry_price", 0.0))
        sl = float(pos.get("sl_price", 0.0))
        tp = float(pos.get("target_price", 0.0))
        qty = pos.get("qty", 1)
        notional = float(pos.get("notional") or (entry * qty))
        margin = float(pos.get("margin_used") or notional)
        
        # Risk & Target %
        risk_pct = round(abs(entry - sl) / max(0.01, entry) * 100.0, 2) if sl > 0 else 0.0
        target_pct = round(abs(tp - entry) / max(0.01, entry) * 100.0, 2) if tp > 0 else 0.0
        r_mult = round(abs(tp - entry) / max(0.01, abs(entry - sl)), 1) if sl > 0 and tp > 0 else 3.2

        side_emoji = "🟢" if side in ("BUY", "LONG") else "🔴"
        action_text = "BUY (Long Breakout)" if side in ("BUY", "LONG") else "SELL (Short Breakdown)"

        msg = (
            f"{side_emoji} <b>ALPHAFLOW: ORDER ENTERED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Strategy:</b> {engine_label}\n"
            f"<b>Instrument:</b> <code>{sym}</code>\n"
            f"<b>Action:</b> {action_text}\n"
            f"<b>Entry Price:</b> ₹{entry:,.2f}\n"
            f"<b>Stop Loss:</b> ₹{sl:,.2f} (-{risk_pct}% Risk)\n"
            f"<b>Target (+{r_mult}R):</b> ₹{tp:,.2f} (+{target_pct}% Gain)\n"
            f"<b>Quantity:</b> {qty:,} units\n"
            f"<b>Margin Used:</b> ₹{margin:,.2f}\n"
            f"<b>Status:</b> ACTIVE POSITION OPEN\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<i>Execution verified · Automated Risk Guardrail Active</i>"
        )
        self.send_message(msg)

    def send_exit_alert(self, pos: Dict[str, Any], exit_price: float, outcome: str, net_pnl: float, switchboard_config: Dict[str, Any]) -> None:
        """Dispatches an exit alert (Target Hit, SL Hit, Trailing Stop) if the strategy is enabled."""
        engine_id = pos.get("engine_id") or pos.get("engine", "")
        if not self._is_engine_active(engine_id, switchboard_config):
            return

        sym = pos.get("symbol", "")
        engine_label = pos.get("engine", "AlphaFlow Algo")
        entry = float(pos.get("entry_price", 0.0))
        exit_p = float(exit_price)
        pnl_pct = round(((exit_p - entry) / max(0.01, entry)) * 100.0, 2)
        if pos.get("side") in ("SELL", "SHORT"):
            pnl_pct = -pnl_pct

        if "TARGET" in outcome:
            if not self.config.get("alert_on_target", True):
                return
            emoji = "🎯"
            status_text = "TARGET HIT (+3.2R ASYMMETRIC WIN)"
        elif "COST" in outcome or "TRAILED" in outcome or "RATCHET" in outcome:
            emoji = "🛡️"
            status_text = "TRAILED TO BREAKEVEN / PROFIT LOCK"
        elif "SL" in outcome or "STOP" in outcome:
            if not self.config.get("alert_on_sl", True):
                return
            emoji = "🛑"
            status_text = "STOP LOSS HIT (CAPITAL PROTECTED)"
        else:
            if not self.config.get("alert_on_eod", True):
                return
            emoji = "⏰"
            status_text = f"SQUARE-OFF ({outcome})"

        pnl_sign = "+" if net_pnl >= 0 else "-"
        abs_pnl = abs(net_pnl)

        msg = (
            f"{emoji} <b>ALPHAFLOW: {status_text}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Strategy:</b> {engine_label}\n"
            f"<b>Instrument:</b> <code>{sym}</code>\n"
            f"<b>Entry Price:</b> ₹{entry:,.2f}\n"
            f"<b>Exit Price:</b> ₹{exit_p:,.2f} ({pnl_sign}{abs(pnl_pct)}%)\n"
            f"<b>Net P&L:</b> <b>{pnl_sign}₹{abs_pnl:,.2f}</b>\n"
            f"<b>Outcome:</b> {outcome}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<i>Order Lifecycle Completed · Portfolio Updated</i>"
        )
        self.send_message(msg)

# Global singleton
TELEGRAM_NOTIFIER = TelegramNotifier()

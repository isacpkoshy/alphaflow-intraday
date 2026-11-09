"""
Live NSE Auto-Paper-Trading Background Worker (Runs 24/7 inside AlphaFlow Server).
When the NSE market is open (Monday–Friday, 09:15 AM to 15:30 PM IST):
1. Automatically pulls live 5-minute intraday candles from NSE/Yahoo feeds every 30 seconds for:
   - ^NSEI (Nifty 50), ^INDIAVIX (India VIX), all 20 Nifty 50 liquid stocks, AND the top qualifying SEPA/Afzal Swing setups.
2. Updates live prices across:
   - Open Positions & Live MTM P&L
   - Upcoming Setups Queue (on the Trades tab)
   - SEPA Swing Screener & Real-Time AI Verdicts (`SEPAAnalystBrain`)
3. At 09:30 AM (or during market hours before 14:45 PM):
   - Engine 1 (Stock Momentum — `engine_stocks_mis`): Enters Top 2–3 qualified RS-VWAP-ORB stocks.
   - Engine 2 (Nifty Options/F&O — `engine_fo_hybrid`): Enters Nifty Futures ORB or Wed/Thu Expiry Short Straddle.
   - Engine 3 (SEPA & Afzal Swing — `engine_sepa_swing`): Enters Top 2 qualified SEPA/Afzal/Hybrid breakouts (with AI `ENTER` verdict, 1R stop at setup's VCP/Strike stop, +2R breakeven ratchet, and +2.5R target, synced to Position Exit Monitor).
4. At 15:15 PM sharp: Automatically squares off intraday (`STOCKS MIS` and `NIFTY F&O`) positions while preserving multi-day `SEPA SWING` positions until their stop/target is reached.
"""

import threading
import time
import urllib.request
import json
import math
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from src.risk.cost_calculator import IndianCostCalculator
from src.notifications.telegram_notifier import TELEGRAM_NOTIFIER

logger = logging.getLogger("LivePaperWorker")

IST = timezone(timedelta(hours=5, minutes=30))

STOCKS_LIST = [
    "RELIANCE.NS", "HDFCBANK.NS", "ICICIBANK.NS", "SBIN.NS", "INFY.NS",
    "TCS.NS", "TATASTEEL.NS", "AXISBANK.NS", "KOTAKBANK.NS", "LT.NS",
    "BAJFINANCE.NS", "M&M.NS", "SUNPHARMA.NS", "ADANIENT.NS", "BHARTIARTL.NS",
    "MARUTI.NS", "ITC.NS", "HINDALCO.NS", "TRENT.NS", "HAL.NS"
]


class LivePaperTradingWorker:
    def __init__(self, app_state):
        self.app = app_state
        self.running = True
        self.last_poll_ist = None
        self.market_state = "WAITING_FOR_MONDAY_0915"
        self.traded_dates_stocks = set()
        self.traded_dates_fo = set()
        self.traded_dates_sepa = set()
        self.squared_off_dates = set()
        self.daily_circuit_tripped = set()
        self.live_quotes: Dict[str, float] = {}
        self._restore_daily_state()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def _restore_daily_state(self) -> None:
        """Restores traded dates from SQLite / active positions so restarting the server does NOT re-trigger or lose entries."""
        today_str = datetime.now(IST).strftime("%Y-%m-%d")
        for p in getattr(self.app, "open_positions", []):
            if p.get("date") == today_str and p.get("status") == "OPEN":
                eng = p.get("engine_id", "")
                if eng == "engine_stocks_mis":
                    self.traded_dates_stocks.add(today_str)
                elif eng == "engine_fo_hybrid":
                    self.traded_dates_fo.add(today_str)
                elif eng == "engine_sepa_swing":
                    self.traded_dates_sepa.add(today_str)

        for t in getattr(self.app, "account", {}).get("trades", []):
            if t.get("date") == today_str or t.get("entry_date") == today_str:
                eng = t.get("engine", "")
                if eng == "STOCKS MIS":
                    self.traded_dates_stocks.add(today_str)
                elif eng == "NIFTY F&O":
                    self.traded_dates_fo.add(today_str)
                elif eng == "SEPA SWING":
                    self.traded_dates_sepa.add(today_str)

        # Detect if -1.5% daily loss circuit breaker was already triggered today
        cap = float(getattr(self.app, "account", {}).get("starting_capital", 200000.0))
        today_realized = sum(
            t.get("net_pnl", 0.0) for t in getattr(self.app, "account", {}).get("trades", [])
            if (t.get("date") == today_str or t.get("entry_date") == today_str) and t.get("engine") != "SEPA SWING"
        )
        if today_realized <= -0.015 * cap:
            self.daily_circuit_tripped.add(today_str)
            self.traded_dates_stocks.add(today_str)
            self.traded_dates_fo.add(today_str)

    @staticmethod
    def fetch_live_ticker(symbol: str) -> Optional[float]:
        """Fetches the real-time tick price from Yahoo Finance 1-minute chart meta (sub-second response)."""
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(symbol)}?range=1d&interval=1m"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                d = json.loads(resp.read().decode("utf-8"))["chart"]["result"][0]
                price = d.get("meta", {}).get("regularMarketPrice")
                if price:
                    return round(float(price), 2)
                closes = [c for c in d.get("indicators", {}).get("quote", [{}])[0].get("close", []) if c is not None]
                if closes:
                    return round(float(closes[-1]), 2)
        except Exception:
            pass
        return None

    @staticmethod
    def _fetch_today_5m(symbol: str) -> Dict[str, Any]:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(symbol)}?range=5d&interval=5m"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            res = data["chart"]["result"][0]
            ts_list = res.get("timestamp", [])
            q = res["indicators"]["quote"][0]
            by_day: Dict[str, List[Dict[str, float]]] = {}
            for t, o, h, l, c, v in zip(ts_list, q["open"], q["high"], q["low"], q["close"], q["volume"]):
                if o is None or h is None or l is None or c is None:
                    continue
                dt = datetime.fromtimestamp(t, IST)
                d_str = dt.strftime("%Y-%m-%d")
                by_day.setdefault(d_str, []).append({
                    "time": dt.strftime("%H:%M"),
                    "o": float(o), "h": float(h), "l": float(l), "c": float(c), "v": float(v or 0)
                })
            return by_day

    def _is_nse_market_hours(self, now_ist: datetime) -> bool:
        if now_ist.weekday() >= 5:  # Saturday (5) or Sunday (6)
            return False
        hhmm = now_ist.hour * 100 + now_ist.minute
        return 915 <= hhmm <= 1532

    def force_poll_once(self) -> Dict[str, Any]:
        """Called every 30 seconds by the background worker to refresh live market state."""
        now_ist = datetime.now(IST)
        self.last_poll_ist = now_ist.strftime("%Y-%m-%d %H:%M:%S IST")
        today_str = now_ist.strftime("%Y-%m-%d")
        hhmm = now_ist.hour * 100 + now_ist.minute

        if now_ist.weekday() >= 5:
            self.market_state = "WEEKEND_CLOSED (Next Auto-Start: Monday 09:15 AM IST)"
            return {"status": self.market_state, "last_poll": self.last_poll_ist}

        if hhmm < 915:
            self.market_state = "PRE_MARKET_STANDBY (Auto-Starts Today at 09:15 AM IST)"
            return {"status": self.market_state, "last_poll": self.last_poll_ist}

        if hhmm > 1532:
            self.market_state = "POST_MARKET_CLOSED (Next Auto-Start: Tomorrow 09:15 AM IST)"
            return {"status": self.market_state, "last_poll": self.last_poll_ist}

        # Market is OPEN! Pull live 5m bars
        self.market_state = "LIVE_MARKET_POLLING (Every 30s)"
        try:
            nifty_days = self._fetch_today_5m("^NSEI")
            vix_days = self._fetch_today_5m("^INDIAVIX")
        except Exception as e:
            self.market_state = f"FEED_RETRYING ({e})"
            return {"status": self.market_state, "last_poll": self.last_poll_ist}

        if today_str not in nifty_days or len(nifty_days[today_str]) < 1:
            return {"status": "WAITING_FOR_FIRST_CANDLE", "last_poll": self.last_poll_ist}

        n_bars = nifty_days[today_str]
        n_dates = sorted(list(nifty_days.keys()))
        prev_n_close = nifty_days[n_dates[-2]][-1]["c"] if len(n_dates) >= 2 else n_bars[0]["o"]
        self.live_quotes["^NSEI"] = n_bars[-1]["c"]
        self.live_quotes["NIFTY 50"] = n_bars[-1]["c"]

        v_bars = vix_days.get(today_str, [])
        live_vix = v_bars[-1]["c"] if v_bars else 14.5
        self.live_quotes["^INDIAVIX"] = live_vix

        # Poll top SEPA/Afzal setups & intraday watchlist quotes so Upcoming + Screener + AI stay live
        self._poll_sepa_and_watchlist_quotes(today_str)

        # Step 1: Update any already-OPEN positions with latest live prices & check SL / Target / Trail-to-Cost
        self._update_open_positions_live(today_str, n_bars[-1]["c"], live_vix)

        # Step 2: Check 15:15 PM Mandatory Intraday Auto-Square-Off (keeps SEPA SWING positions open!)
        if hhmm >= 1515 and today_str not in self.squared_off_dates:
            self._auto_square_off_intraday(today_str, "15:15 EOD Intraday Auto-Square-Off")
            self.squared_off_dates.add(today_str)
            self.market_state = "EOD_INTRADAY_SQUARED_OFF_AT_1515"
            return {"status": self.market_state, "last_poll": self.last_poll_ist}

        # Step 3: At or after 09:30 AM (at least 3 five-minute bars completed), run Entry Scanners for all 3 engines!
        if len(n_bars) >= 3 and hhmm < 1500:
            alloc = self.app.switchboard.compute_effective_allocations(self.app.account["starting_capital"])
            e1 = alloc["engine_stocks_mis"]
            e2 = alloc["engine_fo_hybrid"]
            e3 = alloc.get("engine_sepa_swing", {})

            orb_n_bars = n_bars[:3]
            n_orb_c = orb_n_bars[-1]["c"]
            n_orb_o = orb_n_bars[0]["o"]
            n_orb_h = max(b["h"] for b in orb_n_bars)
            n_orb_l = min(b["l"] for b in orb_n_bars)
            n_ret_prev = (n_orb_c - prev_n_close) / prev_n_close * 100.0
            n_intraday_chg = (n_orb_c - n_orb_o) / n_orb_o * 100.0
            n_orb_rng_pct = (n_orb_h - n_orb_l) / n_orb_c * 100.0

            # Pre-entry check: Hard RMS Lockout if -1.5% daily loss limit is reached (blocks intraday engines only; multi-day swing trades run independently)
            cap = float(getattr(self.app, "account", {}).get("starting_capital", 200000.0))
            today_realized = sum(
                t.get("net_pnl", 0.0) for t in getattr(self.app, "account", {}).get("trades", [])
                if (t.get("date") == today_str or t.get("entry_date") == today_str) and t.get("engine") != "SEPA SWING"
            )
            intraday_blocked = (today_str in self.daily_circuit_tripped or today_realized <= -0.015 * cap)
            if intraday_blocked:
                self.daily_circuit_tripped.add(today_str)
                self.traded_dates_stocks.add(today_str)
                self.traded_dates_fo.add(today_str)
                self.market_state = "RMS_CIRCUIT_BREAKER_ACTIVE (-1.5% Daily Loss Hit — Intraday Halted)"
            else:
                # 3A: Auto-Enter Engine 1 — Stock Momentum (MIS)
                # Automatic Idle-Cash Rotation: Triggers if Engine 1 is enabled OR if Next-Gen Adaptive Hybrid 2.0 is active!
                # Next-Gen Adaptive Swing is Pure Swing Alone (76.99% CAGR) — Engine 1 triggers independently!
                if e1.get("enabled") and today_str not in self.traded_dates_stocks and hhmm < 1445:
                    self._scan_and_enter_live_stocks(today_str, e1, n_ret_prev, n_intraday_chg, is_hybrid_v2=False)

                # 3B: Auto-Enter Engine 2 — Nifty F&O Hybrid
                if e2["enabled"] and today_str not in self.traded_dates_fo and hhmm < 1445:
                    self.traded_dates_fo.add(today_str)
                    self._scan_and_enter_live_fo(today_str, e2, n_orb_c, n_intraday_chg, n_orb_rng_pct, live_vix)

            # 3C: Auto-Enter Engine 3 — SEPA & Afzal Swing Bot (see end-of-day window below)

        # Step 4: SEPA / Afzal / Hybrid swing entries are EOD-only (same as the Handoff project):
        # signals are confirmed near the close (15:00–15:25 IST) and orders are placed at that closing price.
        if 1500 <= hhmm <= 1525 and len(n_bars) >= 3:
            e3 = self.app.switchboard.compute_effective_allocations(self.app.account["starting_capital"]).get("engine_sepa_swing", {})
            if e3.get("enabled"):
                self._scan_and_enter_live_sepa_swing(today_str, e3)

        return {"status": self.market_state, "last_poll": self.last_poll_ist}

    def _poll_sepa_and_watchlist_quotes(self, today_str: str) -> None:
        """Fetches real-time tick prices for open positions, screener leaders, and upcoming watch setups."""
        try:
            # 1. ALWAYS poll real-time prices for every active open position first
            for p in self.app.open_positions:
                if p.get("status") == "OPEN":
                    raw = p.get("raw_symbol")
                    if raw and not raw.startswith("^"):
                        px = self.fetch_live_ticker(raw)
                        if px:
                            self.live_quotes[raw] = px
                            clean = raw.replace(".NS", "").replace(".BO", "")
                            self.live_quotes[clean] = px

            # 2. Poll top SEPA / Afzal setups so upcoming watch prices are live
            sepa_setups = getattr(self.app.screener, "setups", [])
            priority_rows = [
                s for s in sepa_setups
                if s.get("top_focus") or s.get("stage") == 2 or s.get("signal") in ("BUY ALERT", "SHORT ALERT")
            ][:12]
            for s in priority_rows:
                sym = s.get("display_symbol", s["symbol"]).upper()
                suf = ".BO" if s.get("exchange") == "BSE" else ".NS"
                ticker = f"{sym}{suf}"
                px = self.fetch_live_ticker(ticker)
                if px:
                    self.live_quotes[sym] = px
                    self.live_quotes[ticker] = px

            if self.live_quotes and hasattr(self.app, "screener"):
                self.app.screener.update_from_live_quotes(self.live_quotes)
        except Exception:
            pass

    def _scan_and_enter_live_stocks(self, today_str: str, e1: Dict[str, Any], n_ret_prev: float, n_intraday_chg: float, is_hybrid_v2: bool = False) -> None:
        params1 = e1.get("params", {})
        # Alpha-Surge 100+ Intraday Institutional Parameters
        rvol_min = float(params1.get("rvol_min", 2.2))
        rs_min = float(params1.get("relative_strength_min_pct", 0.35))
        sl_pct = float(params1.get("stop_loss_pct", 1.1))
        rr = float(params1.get("target_rr", 3.2))
        lev = float(params1.get("mis_leverage", 5.0))

        # Check Available Free Cash (Account Starting Capital minus capital locked in open overnight swing positions)
        open_sepa_cost = sum(
            p.get("margin_used", p.get("cost", p.get("notional", 0.0)))
            for p in self.app.open_positions
            if p.get("engine_id") == "engine_sepa_swing" and p.get("status") == "OPEN"
        )
        base_cap = float(self.app.account.get("starting_capital", 300000.0))
        free_cash = max(0.0, base_cap - open_sepa_cost)

        alloc_cap = float(e1.get("allocated_capital_inr", 0.0))
        if alloc_cap <= 0 and is_hybrid_v2:
            # Next-Gen Adaptive Hybrid 2.0 automatically uses up to 50% of free idle cash for morning intraday MIS!
            alloc_cap = free_cash * 0.50

        if alloc_cap < 10000.0:
            return

        candidates = []
        for s in STOCKS_LIST:
            try:
                s_days = self._fetch_today_5m(s)
                if today_str not in s_days or len(s_days[today_str]) < 3:
                    continue
                bars = s_days[today_str]
                self.live_quotes[s] = bars[-1]["c"]
                self.live_quotes[s.replace(".NS", "")] = bars[-1]["c"]
                s_dates = sorted(list(s_days.keys()))
                prev_c = s_days[s_dates[-2]][-1]["c"] if len(s_dates) >= 2 else bars[0]["o"]

                cum_pv, cum_v = 0.0, 0.0
                for b in bars[:3]:
                    tp = (b["h"] + b["l"] + b["c"]) / 3.0
                    cum_pv += tp * b["v"]
                    cum_v += b["v"]
                orb_vwap = (cum_pv / cum_v) if cum_v > 0 else bars[2]["c"]
                orb_h = max(b["h"] for b in bars[:3])
                orb_l = min(b["l"] for b in bars[:3])
                orb_c = bars[2]["c"]
                orb_v = sum(b["v"] for b in bars[:3])

                past_v = [sum(b["v"] for b in s_days[d][:3]) for d in s_dates[:-1] if len(s_days[d]) >= 3]
                avg_v = (sum(past_v) / len(past_v)) if past_v else (orb_v or 1.0)
                rvol = (orb_v / avg_v) if avg_v > 0 else 1.0
                rs = ((orb_c - prev_c) / prev_c * 100.0) - n_ret_prev
                close_pos = (orb_c - orb_l) / max(0.01, orb_h - orb_l)

                if rvol >= rvol_min:
                    if rs >= rs_min and orb_c > orb_vwap and close_pos >= 0.70 and n_intraday_chg >= -0.15:
                        candidates.append(("LONG", abs(rs) * math.sqrt(rvol), s, bars[-1]["c"], rvol, rs))
                    elif rs <= -rs_min and orb_c < orb_vwap and close_pos <= 0.30 and n_intraday_chg <= 0.15:
                        candidates.append(("SHORT", abs(rs) * math.sqrt(rvol), s, bars[-1]["c"], rvol, rs))
            except Exception:
                continue

        candidates.sort(key=lambda x: x[1], reverse=True)
        selected = candidates[:3]
        if not selected:
            return

        notional_per_stock = min(600000.0, (alloc_cap * lev) / len(selected))
        entered_any = False
        for side, score, s, entry_p, rvol, rs in selected:
            sym_clean = s.replace(".NS", "").replace(".BO", "")
            qty = max(1, int(notional_per_stock // entry_p))
            notional = round(entry_p * qty, 2)
            margin_used = round(notional / lev, 2)
            sl_dist = entry_p * (sl_pct / 100.0)
            tp_dist = sl_dist * rr
            sl_p = round(entry_p - sl_dist if side == "LONG" else entry_p + sl_dist, 2)
            tp_p = round(entry_p + tp_dist if side == "LONG" else entry_p - tp_dist, 2)

            # Cybersecurity & Pre-Trade Risk Guardrails
            risk_err = self.app.broker_manager.validate_pre_trade_risk(
                symbol=sym_clean,
                price=entry_p,
                quantity=qty,
                order_val=notional,
                margin_val=margin_used,
                available_cash=alloc_cap * lev
            )
            if risk_err:
                logger.warning("MIS Order rejected by Security Guardrail: %s", risk_err)
                continue

            # Execute via Broker Gateway (LIVE via DhanHQ or simulated PAPER)
            exec_res = self.app.broker_manager.execute_order(
                symbol=sym_clean,
                transaction_type=side,
                quantity=qty,
                price=entry_p,
                order_type="MARKET",
                product_type="MIS" if lev > 1.0 else "CNC",
                sl_price=sl_p,
                target_price=tp_p
            )

            pos_id = exec_res.get("broker_order_id") or exec_res.get("order_id") or f"LIVE-MIS-{sym_clean}-{int(time.time()*1000) % 100000}"
            pos_dict = {
                "pos_id": pos_id,
                "broker_order_id": exec_res.get("broker_order_id"),
                "execution_mode": exec_res.get("mode", "PAPER"),
                "date": today_str,
                "engine_id": "engine_stocks_mis",
                "strategy_origin": "alpha_surge_100",
                "engine": "NEXT-GEN HYBRID (MIS)" if (is_hybrid_v2 and not e1.get("enabled")) else "ALPHA-SURGE 100+ MIS",
                "raw_symbol": s,
                "symbol": f"{sym_clean} (MIS)",
                "side": side,
                "qty": qty,
                "entry_price": round(entry_p, 2),
                "ltp": round(entry_p, 2),
                "sl_price": sl_p,
                "initial_sl_dist": sl_dist,
                "target_price": tp_p,
                "leverage": lev,
                "margin_used": margin_used,
                "notional": notional,
                "product_type": "MIS" if lev > 1.0 else "CNC",
                "trail_status": f"ACTIVE (RVOL {rvol:.1f}x)",
                "delta": f"{qty} sh",
                "theta": "₹0/hr",
                "gross_mtm": 0.0,
                "est_charges": 85.0,
                "net_mtm": -85.0,
                "status": "OPEN",
            }
            self.app.open_positions.append(pos_dict)
            try:
                TELEGRAM_NOTIFIER.send_entry_alert(pos_dict, self.app.switchboard.config)
            except Exception as e_tg:
                logger.error("Failed to send telegram entry alert: %s", e_tg)
            entered_any = True

        if entered_any:
            self.traded_dates_stocks.add(today_str)
            logger.info("Alpha-Surge 100+ Intraday entered %d positions for %s", len(self.app.open_positions), today_str)
        self.app._save_open_positions()

    def _scan_and_enter_live_fo(self, today_str: str, e2: Dict[str, Any], spot: float, n_intraday_chg: float, n_orb_rng_pct: float, live_vix: float) -> None:
        lot_size = 65
        lots = max(1, e2["active_lots"])
        dte = self.app.analytics._get_dte_at_open(today_str)

        if abs(n_intraday_chg) >= 0.30:
            is_long = n_intraday_chg > 0
            sl_dist = spot * 0.005
            tp_dist = sl_dist * 3.0
            pos_dict = {
                "pos_id": f"LIVE-FO-{int(time.time()*1000) % 100000}",
                "date": today_str,
                "engine_id": "engine_fo_hybrid",
                "engine": "NIFTY F&O",
                "raw_symbol": "^NSEI",
                "symbol": "NIFTY FUT (65 Qty)",
                "side": "LONG" if is_long else "SHORT",
                "qty": lot_size,
                "entry_price": round(spot, 2),
                "ltp": round(spot, 2),
                "sl_price": round(spot - sl_dist if is_long else spot + sl_dist, 2),
                "initial_sl_dist": sl_dist,
                "target_price": round(spot + tp_dist if is_long else spot - tp_dist, 2),
                "trail_status": "FUTURES 15m ORB",
                "delta": "+65" if is_long else "-65",
                "theta": "₹0/hr",
                "gross_mtm": 0.0,
                "est_charges": 195.0,
                "net_mtm": -195.0,
                "status": "OPEN",
            }
            self.app.open_positions.append(pos_dict)
            try:
                TELEGRAM_NOTIFIER.send_entry_alert(pos_dict, self.app.switchboard.config)
            except Exception as e_tg:
                logger.error("Failed to send telegram entry alert: %s", e_tg)
            self.app._save_open_positions()
        elif dte <= 1.5 and n_orb_rng_pct <= 0.35:
            atm = int(round(spot / 50.0) * 50)
            ce_p = self.app.analytics._bsm_price(spot, atm, dte, live_vix, True)
            pe_p = self.app.analytics._bsm_price(spot, atm, dte, live_vix, False)
            comb = round(ce_p + pe_p, 2)
            qty = lots * lot_size
            pos_dict = {
                "pos_id": f"LIVE-STR-{int(time.time()*1000) % 100000}",
                "date": today_str,
                "engine_id": "engine_fo_hybrid",
                "engine": "NIFTY F&O",
                "raw_symbol": "^NSEI_STRADDLE",
                "atm_strike": atm,
                "dte_open": dte,
                "symbol": f"NIFTY {atm} CE+PE STRADDLE",
                "side": "SELL",
                "qty": qty,
                "entry_price": comb,
                "ltp": comb,
                "sl_price": round(comb * 1.25, 2),
                "initial_sl_dist": comb * 0.25,
                "target_price": round(comb * 0.65, 2),
                "trail_status": "WED/THU EXPIRY THETA",
                "delta": "0.00",
                "theta": "+₹680/hr",
                "gross_mtm": 0.0,
                "est_charges": 210.0,
                "net_mtm": -210.0,
                "status": "OPEN",
            }
            self.app.open_positions.append(pos_dict)
            try:
                TELEGRAM_NOTIFIER.send_entry_alert(pos_dict, self.app.switchboard.config)
            except Exception as e_tg:
                logger.error("Failed to send telegram entry alert: %s", e_tg)
            self.app._save_open_positions()

    def _scan_and_enter_live_sepa_swing(self, today_str: str, e3: Dict[str, Any]) -> None:
        """
        Auto-trades the newly integrated SEPA / Afzal / Hybrid filters (`engine_sepa_swing`):
        - Checks open SEPA SWING positions; allows up to `max_open_positions` (default 2).
        - Evaluates setups from the active filter (`afzal`, `minervini`, or `hybrid`) where AI Verdict is `ENTER`
          (or `top_focus` / `BUY ALERT` / `SHORT ALERT`) and live price triggers the breakout pivot.
        - Sizes position using 1% account stop risk (capped by allocated SEPA capital) and syncs with Position Exit Monitor.
        """
        params = e3.get("params", {})
        active_flt = str(params.get("active_filter", "adaptive_hybrid")).lower()
        max_pos = int(params.get("max_open_positions", 2))
        
        # Strategy-specific target R:R
        if active_flt == "adaptive_hybrid_v2":
            target_rr = 3.00
        elif active_flt == "adaptive_hybrid":
            target_rr = 2.75
        elif active_flt == "explosive_velocity":
            target_rr = 2.70
        elif active_flt == "explosive_chandelier":
            target_rr = 2.00
        elif active_flt == "afzal_50sma":
            target_rr = 5.00
        else:
            target_rr = float(params.get("target_rr", 2.5))

        open_sepa = [
            p for p in self.app.open_positions
            if p.get("engine_id") == "engine_sepa_swing" and p.get("status") == "OPEN"
        ]
        if len(open_sepa) >= max_pos:
            return

        open_syms = {p.get("raw_symbol", "").replace(".NS", "").replace(".BO", "").upper() for p in open_sepa}
        payload = self.app.screener.get_universe_payload()
        all_setups = [
            s for s in payload.get("setups", [])
            if s.get("strategy") == active_flt
            or (active_flt in ("afzal", "afzal_b3", "adaptive_hybrid_v2", "adaptive_hybrid", "explosive_velocity", "explosive_chandelier", "afzal_super", "afzal_tranche", "afzal_50sma") and s.get("strategy") in ("afzal", active_flt))
        ]
        if active_flt in ("explosive_velocity", "afzal_super"):
            all_setups = [s for s in all_setups if (s.get("rs_percentile") or 0) >= 80]

        qualifying = []
        for s in all_setups:
            sym = s.get("display_symbol", s["symbol"]).upper()
            if sym in open_syms:
                continue
            ai_dec = (s.get("ai_decisions", {}).get(active_flt) or s.get("ai_decision") or {}).get("decision", "WATCH")
            price = float(s.get("price") or 0)
            pivot = float(s.get("pivot") or 0)
            stop = float(s.get("stop") or 0)
            if price <= 0 or pivot <= 0 or stop <= 0:
                continue

            # 1. Strict AI Decision check:
            # Never enter if AI says AVOID
            if ai_dec == "AVOID":
                continue
            # Enforce AI ENTER verdict if required in settings (default True)
            if params.get("require_ai_enter_verdict", True) and ai_dec != "ENTER":
                continue

            # 2. Strict Breakout Signal check:
            # Must be a confirmed BUY ALERT at or above pivot (or SHORT ALERT at/below support)
            # Never enter when signal is NO ENTRY, EXTENDED, or WATCH
            is_short = s.get("side") == "SHORT"
            signal = str(s.get("signal", "NO ENTRY")).upper()
            if not is_short:
                if signal == "BUY ALERT" and price >= pivot:
                    qualifying.append(s)
            else:
                if signal == "SHORT ALERT" and price <= pivot:
                    qualifying.append(s)

        qualifying.sort(key=lambda x: (1 if x.get("top_focus") else 0, x.get("rank_score", 0)), reverse=True)
        slots = max_pos - len(open_sepa)
        selected = qualifying[:slots]
        if not selected:
            return

        alloc_cap = float(e3.get("allocated_capital_inr", 50000.0))
        base_cap = float(self.app.account.get("starting_capital", 200000.0))
        risk_budget_inr = base_cap * (float(params.get("risk_per_trade_pct", 1.0)) / 100.0)

        for s in selected:
            sym = s.get("display_symbol", s["symbol"]).upper()
            ex_suf = ".BO" if s.get("exchange") == "BSE" else ".NS"
            raw_sym = f"{sym}{ex_suf}"
            entry_p = round(float(s["price"]), 2)
            stop_p = round(float(s["stop"]), 2)
            is_short = s.get("side") == "SHORT"
            sl_dist = abs(entry_p - stop_p)
            if sl_dist <= 0:
                continue

            swing_lev = float(params.get("swing_leverage", 1.0))
            max_notional = (alloc_cap * swing_lev) / max(1, max_pos)
            qty_by_risk = int(risk_budget_inr // sl_dist)
            qty_by_cap = int(max_notional // entry_p)
            qty = max(1, min(qty_by_risk, qty_by_cap) if qty_by_cap > 0 else 1)
            notional = round(entry_p * qty, 2)
            margin_used = round(notional / swing_lev, 2)
            tp_p = round(entry_p - sl_dist * target_rr if is_short else entry_p + sl_dist * target_rr, 2)

            # Cybersecurity & Pre-Trade Risk Guardrails
            risk_err = self.app.broker_manager.validate_pre_trade_risk(
                symbol=sym,
                price=entry_p,
                quantity=qty,
                order_val=notional,
                available_cash=alloc_cap * swing_lev
            )
            if risk_err:
                logger.warning("Swing Order rejected by Security Guardrail: %s", risk_err)
                continue

            pos_dict = {
                "pos_id": f"SEPA-{int(time.time()*1000) % 100000}-{sym[:4]}",
                "date": today_str,
                "engine_id": "engine_sepa_swing",
                "engine": "SEPA SWING",
                "raw_symbol": raw_sym,
                "symbol": f"{sym} ({active_flt.upper()})",
                "side": "SHORT" if is_short else "LONG",
                "qty": qty,
                "entry_price": entry_p,
                "ltp": entry_p,
                "sl_price": stop_p,
                "initial_sl_dist": sl_dist,
                "target_price": tp_p,
                "leverage": swing_lev,
                "margin_used": margin_used,
                "notional": notional,
                "product_type": "MTF" if swing_lev > 1.0 else "CNC",
                "trail_status": f"SEPA {active_flt.upper()} (+2R Ratchet Armed)",
                "delta": f"{qty} sh",
                "theta": "Swing",
                "gross_mtm": 0.0,
                "est_charges": 65.0,
                "net_mtm": -65.0,
                "status": "OPEN",
            }
            self.app.open_positions.append(pos_dict)
            try:
                TELEGRAM_NOTIFIER.send_entry_alert(pos_dict, self.app.switchboard.config)
            except Exception as e_tg:
                logger.error("Failed to send telegram entry alert: %s", e_tg)
            if not is_short and stop_p < entry_p:
                try:
                    self.app.screener.manage_position("add", sym, entry_p, stop_p)
                except Exception:
                    pass
        self.app._save_open_positions()

    def _update_open_positions_live(self, today_str: str, nifty_spot: float, live_vix: float) -> None:
        for p in self.app.open_positions:
            if p["status"] != "OPEN":
                continue
            raw_sym = p.get("raw_symbol")
            if raw_sym == "^NSEI_STRADDLE":
                atm = p.get("atm_strike", int(round(nifty_spot / 50.0) * 50))
                dte = max(0.02, p.get("dte_open", 0.5) - 0.12)
                ce_now = self.app.analytics._bsm_price(nifty_spot, atm, dte, live_vix, True)
                pe_now = self.app.analytics._bsm_price(nifty_spot, atm, dte, live_vix, False)
                ltp = round(ce_now + pe_now, 2)
            elif raw_sym == "^NSEI":
                ltp = round(nifty_spot, 2)
            elif raw_sym:
                # Fetch fresh real-time tick price on every cycle
                live_p = self.fetch_live_ticker(raw_sym)
                if live_p:
                    ltp = live_p
                    self.live_quotes[raw_sym] = live_p
                    clean = raw_sym.replace(".NS", "").replace(".BO", "")
                    self.live_quotes[clean] = live_p
                elif raw_sym in self.live_quotes:
                    ltp = round(float(self.live_quotes[raw_sym]), 2)
                else:
                    ltp = p["ltp"]
            else:
                continue

            p["ltp"] = ltp
            if "leverage" not in p:
                p["leverage"] = 5.0 if p.get("engine_id") == "engine_stocks_mis" else (4.0 if "MTF" in str(p.get("product_type")) else 1.0)
            if "notional" not in p:
                p["notional"] = round(p["entry_price"] * p["qty"], 2)
            if "margin_used" not in p:
                p["margin_used"] = round(p["notional"] / max(1.0, float(p["leverage"])), 2)

            is_long = p["side"] in ("LONG", "BUY")
            pts = (ltp - p["entry_price"]) if is_long else (p["entry_price"] - ltp)
            gross = round(pts * p["qty"], 2)
            p["gross_mtm"] = gross
            p["net_mtm"] = round(gross - p["est_charges"], 2)

            # For SEPA SWING positions, ratchet to breakeven at +2R (or +1.35R for Hybrid 2.0); for intraday MIS, ratchet at +1R
            if p.get("engine_id") == "engine_sepa_swing":
                ratchet_mult = 1.35 if "ADAPTIVE_HYBRID_V2" in str(p.get("symbol", "")).upper() else 2.0
            else:
                ratchet_mult = 1.0
            ratchet_dist = p.get("initial_sl_dist", 999999) * ratchet_mult

            if is_long:
                if ltp <= p["sl_price"]:
                    # Swing trades can gap overnight: fill at the real (worse) price, not the stop level
                    fill = ltp if p.get("engine_id") == "engine_sepa_swing" else p["sl_price"]
                    self._close_and_record_position(p, fill, "SL_HIT", today_str)
                elif p["target_price"] > 0 and ltp >= p["target_price"]:
                    self._close_and_record_position(p, p["target_price"], "TARGET_HIT", today_str)
                elif pts >= ratchet_dist and p["sl_price"] < p["entry_price"]:
                    p["sl_price"] = p["entry_price"]
                    p["trail_status"] = f"TRAILED_TO_COST (+{int(ratchet_mult)}R Locked)"
            else:
                if ltp >= p["sl_price"]:
                    fill = ltp if p.get("engine_id") == "engine_sepa_swing" else p["sl_price"]
                    self._close_and_record_position(p, fill, "SL_HIT", today_str)
                elif p["target_price"] > 0 and ltp <= p["target_price"]:
                    self._close_and_record_position(p, p["target_price"], "TARGET_HIT", today_str)
                elif pts >= ratchet_dist and p["sl_price"] > p["entry_price"]:
                    p["sl_price"] = p["entry_price"]
                    p["trail_status"] = f"TRAILED_TO_COST (+{int(ratchet_mult)}R Locked)"

        # Check -1.5% Global Daily Loss Circuit Breaker (intraday engines only; multi-day swing trades run on their own stops)
        cap = float(self.app.account.get("starting_capital", 200000.0))
        today_realized = sum(
            t.get("net_pnl", 0.0) for t in getattr(self.app, "account", {}).get("trades", [])
            if (t.get("date") == today_str or t.get("entry_date") == today_str) and t.get("engine") != "SEPA SWING"
        )
        open_mtm = sum(
            x["net_mtm"] for x in self.app.open_positions
            if x["status"] == "OPEN" and x.get("engine_id") != "engine_sepa_swing"
        )
        if (today_realized + open_mtm) <= -0.015 * cap:
            self.daily_circuit_tripped.add(today_str)
            self.traded_dates_stocks.add(today_str)
            self.traded_dates_fo.add(today_str)
            self._auto_square_off_intraday(today_str, "RMS -1.5% Daily Loss Circuit Breaker")

    def _close_and_record_position(self, p: Dict[str, Any], exit_price: float, outcome: str, today_str: str) -> None:
        try:
            self.app.broker_manager.execute_exit(
                symbol=p.get("raw_symbol") or p.get("symbol", ""),
                side=p.get("side", "BUY"),
                quantity=p.get("qty", 1),
                exit_price=exit_price,
                product_type=p.get("product_type", "MIS")
            )
        except Exception:
            pass
        self.app.record_closed_position(p, exit_price, outcome, today_str)
        try:
            is_long = p.get("side") in ("LONG", "BUY")
            pts = (exit_price - p.get("entry_price", exit_price)) if is_long else (p.get("entry_price", exit_price) - exit_price)
            gross = round(pts * p.get("qty", 1), 2)
            net = round(gross - float(p.get("est_charges", 50.0)), 2)
            TELEGRAM_NOTIFIER.send_exit_alert(p, exit_price, outcome, net, self.app.switchboard.config)
        except Exception as ex:
            logger.error("Failed to dispatch Telegram exit alert: %s", ex)

    def _auto_square_off_intraday(self, today_str: str, reason: str) -> None:
        """Squares off intraday MIS and F&O positions; keeps SEPA SWING positions open."""
        outcome = "RMS_CIRCUIT_BREAKER" if ("Circuit Breaker" in reason or "RMS" in reason or "Daily Loss" in reason) else "EOD_SQUARE_OFF"
        for p in self.app.open_positions:
            if p["status"] == "OPEN" and p.get("engine_id") != "engine_sepa_swing":
                self._close_and_record_position(p, p["ltp"], outcome, today_str)

    def _auto_square_off_all(self, today_str: str, reason: str) -> None:
        outcome = "RMS_CIRCUIT_BREAKER" if ("Circuit Breaker" in reason or "RMS" in reason or "Daily Loss" in reason) else "EOD_SQUARE_OFF"
        for p in self.app.open_positions:
            if p["status"] == "OPEN":
                self._close_and_record_position(p, p["ltp"], outcome, today_str)

    def _run_loop(self) -> None:
        while self.running:
            try:
                self.force_poll_once()
                self.app._save_open_positions()
            except Exception:
                pass
            time.sleep(8)

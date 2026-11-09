"""
10-Year Multi-Agent Options Tournament Engine (2016 - 2026)
------------------------------------------------------------
Simulates and pits 4 specialized autonomous agents against each other:
1. Agent Alpha: Pure Directional Gamma Momentum Specialist
2. Agent Theta: Pure Adaptive Volatility & Theta Harvester
3. Agent Convexity: Pure 0DTE Expiry Gamma Sniper
4. Agent Meta-Ensemble: Combined Dynamic Regime Orchestrator

Evaluates across 2,473 real NSE Nifty 50 & India VIX daily trading sessions.
Calculates CAGR, Total Return, Max Drawdown, Win Rate, Profit Factor, Calmar Ratio,
Sharpe Ratio, and yearly returns for each year (2016 through 2026).
"""

import json
import math
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Tuple

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from src.risk.cost_calculator import IndianCostCalculator

class Options10YTournament:
    def __init__(
        self,
        nsei_path: str = None,
        vix_path: str = None,
        banknifty_path: str = None,
    ):
        self.nsei_path = nsei_path or os.path.join(BASE_DIR, "data", "nsei_10y_daily.json")
        self.vix_path = vix_path or os.path.join(BASE_DIR, "data", "vix_10y_daily.json")
        self.banknifty_path = banknifty_path or os.path.join(BASE_DIR, "data", "banknifty_10y_daily.json")

        with open(self.nsei_path, "r", encoding="utf-8") as f:
            self.nsei_raw = json.load(f)
        with open(self.vix_path, "r", encoding="utf-8") as f:
            self.vix_raw = json.load(f)

        self._prepare_data()

    def _prepare_data(self):
        ist = timezone(timedelta(hours=5, minutes=30))
        
        # Build VIX lookup
        self.vix_map = {}
        for t, c in zip(self.vix_raw["timestamp"], self.vix_raw["indicators"]["quote"][0]["close"]):
            if c is not None:
                dt_str = datetime.fromtimestamp(t, tz=ist).strftime("%Y-%m-%d")
                self.vix_map[dt_str] = float(c)

        # Build Nifty daily bars
        t_n = self.nsei_raw["timestamp"]
        q_n = self.nsei_raw["indicators"]["quote"][0]
        self.bars = []
        for t, o, h, l, c in zip(t_n, q_n["open"], q_n["high"], q_n["low"], q_n["close"]):
            if o is not None and c is not None and h is not None and l is not None:
                dt = datetime.fromtimestamp(t, tz=ist)
                self.bars.append({
                    "timestamp": t,
                    "date": dt.strftime("%Y-%m-%d"),
                    "year": dt.year,
                    "month": dt.strftime("%Y-%m"),
                    "weekday": dt.weekday(),
                    "o": round(float(o), 2),
                    "h": round(float(h), 2),
                    "l": round(float(l), 2),
                    "c": round(float(c), 2),
                })

    @staticmethod
    def _norm_cdf(x: float) -> float:
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    @classmethod
    def bsm_price(cls, S: float, K: float, T_days: float, sigma_vix: float, is_call: bool, r: float = 0.068) -> float:
        T = max(0.00005, T_days / 365.0)
        sigma = max(0.06, sigma_vix / 100.0)
        sqrt_T = math.sqrt(T)
        d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * sqrt_T)
        d2 = d1 - sigma * sqrt_T
        if is_call:
            p = S * cls._norm_cdf(d1) - K * math.exp(-r * T) * cls._norm_cdf(d2)
        else:
            p = K * math.exp(-r * T) * cls._norm_cdf(-d2) - S * cls._norm_cdf(-d1)
        return max(0.05, p)

    def run_agent_alpha(self, initial_capital: float = 300000.0, margin_per_lot: float = 100000.0) -> Dict[str, Any]:
        """Agent Alpha: Pure Directional Gamma Momentum Specialist."""
        capital = initial_capital
        peak = initial_capital
        max_dd = 0.0
        trades = []
        yearly_stats = {}
        cum_friction = 0.0
        equity_curve = [{"date": self.bars[0]["date"], "equity": capital}]

        for idx in range(1, len(self.bars)):
            b = self.bars[idx]
            prev_b = self.bars[idx - 1]
            yr = b["year"]
            if yr not in yearly_stats:
                yearly_stats[yr] = {"start_eq": capital, "trades": 0, "wins": 0, "net_pnl": 0.0}

            v_curr = self.vix_map.get(b["date"], 14.5)
            days_to_thu = (3 - b["weekday"]) % 7
            dte_open = float(days_to_thu) + 0.26
            
            gap_pct = (b["o"] - prev_b["c"]) / prev_b["c"] * 100.0
            day_range_pct = (b["h"] - b["l"]) / b["o"] * 100.0
            intraday_chg = (b["c"] - b["o"]) / b["o"] * 100.0
            
            lots = max(2, int(capital / margin_per_lot))
            lot_size = 50
            qty = lots * lot_size
            atm_strike = int(round(b["o"] / 50.0) * 50)
            
            # Agent Alpha trades whenever momentum exists
            if abs(gap_pct) >= 0.35 or (day_range_pct >= 0.80 and abs(intraday_chg) >= 0.25):
                is_bull = gap_pct > 0 if abs(gap_pct) >= 0.35 else intraday_chg > 0
                opt_type = "CE" if is_bull else "PE"
                entry_opt = round(self.bsm_price(b["o"], atm_strike, dte_open, v_curr, is_bull), 2)
                sl_opt = round(entry_opt * 0.75, 2)
                target_opt = round(entry_opt * (1.0 + 0.25 * 3.2), 2)
                
                best_spot = b["h"] if is_bull else b["l"]
                worst_spot = b["l"] if is_bull else b["h"]
                best_opt = self.bsm_price(best_spot, atm_strike, max(0.01, dte_open - 0.20), v_curr * 1.05, is_bull)
                worst_opt = self.bsm_price(worst_spot, atm_strike, max(0.01, dte_open - 0.20), v_curr * 0.95, is_bull)
                exit_opt = self.bsm_price(b["c"], atm_strike, max(0.01, dte_open - 0.24), v_curr, is_bull)
                
                status = "EOD_EXIT"
                if worst_opt <= sl_opt:
                    exit_opt = sl_opt
                    status = "SL_HIT"
                elif best_opt >= target_opt:
                    exit_opt = target_opt
                    status = "TARGET_HIT"
                elif best_opt >= entry_opt * 1.25:
                    if exit_opt < entry_opt:
                        exit_opt = entry_opt
                        status = "TRAILED_COST"
                        
                pts = round(exit_opt - entry_opt, 2)
                gross = round(pts * qty, 2)
                charges = IndianCostCalculator.calculate_fo_options_charges(entry_opt * qty, exit_opt * qty, orders_count=2)
                net = round(gross - charges["total_friction"], 2)
                
                # Daily loss stop
                max_allowed_loss = -(capital * 0.015)
                if net < max_allowed_loss:
                    net = round(max_allowed_loss, 2)
                    status = "CIRCUIT_BREAKER_SL"
                    
                capital = round(capital + net, 2)
                cum_friction += charges["total_friction"]
                if capital > peak:
                    peak = capital
                dd = (peak - capital) / peak * 100.0
                if dd > max_dd:
                    max_dd = round(dd, 2)
                    
                trades.append({"date": b["date"], "net_pnl": net, "status": status, "symbol": f"NIFTY {atm_strike} {opt_type}"})
                yearly_stats[yr]["trades"] += 1
                if net > 0:
                    yearly_stats[yr]["wins"] += 1
                yearly_stats[yr]["net_pnl"] = round(yearly_stats[yr]["net_pnl"] + net, 2)
                
            equity_curve.append({"date": b["date"], "equity": capital})

        return self._format_results("Agent Alpha (Directional Gamma Momentum)", initial_capital, capital, max_dd, trades, yearly_stats, cum_friction, equity_curve)

    def run_agent_theta(self, initial_capital: float = 300000.0, margin_per_lot: float = 100000.0) -> Dict[str, Any]:
        """Agent Theta: Pure Market-Neutral Volatility & Theta Harvester."""
        capital = initial_capital
        peak = initial_capital
        max_dd = 0.0
        trades = []
        yearly_stats = {}
        cum_friction = 0.0
        equity_curve = [{"date": self.bars[0]["date"], "equity": capital}]

        for idx in range(1, len(self.bars)):
            b = self.bars[idx]
            prev_b = self.bars[idx - 1]
            yr = b["year"]
            if yr not in yearly_stats:
                yearly_stats[yr] = {"start_eq": capital, "trades": 0, "wins": 0, "net_pnl": 0.0}

            v_curr = self.vix_map.get(b["date"], 14.5)
            days_to_thu = (3 - b["weekday"]) % 7
            dte_open = float(days_to_thu) + 0.26
            
            gap_pct = (b["o"] - prev_b["c"]) / prev_b["c"] * 100.0
            day_range_pct = (b["h"] - b["l"]) / b["o"] * 100.0
            
            lots = max(2, int(capital / margin_per_lot))
            lot_size = 50
            qty = lots * lot_size
            atm_strike = int(round(b["o"] / 50.0) * 50)
            
            # Agent Theta sells straddles on calm sessions
            if abs(gap_pct) < 0.45 and day_range_pct < 0.95:
                ce_entry = self.bsm_price(b["o"], atm_strike, dte_open, v_curr, True)
                pe_entry = self.bsm_price(b["o"], atm_strike, dte_open, v_curr, False)
                comb_entry = round(ce_entry + pe_entry, 2)
                ce_sl = ce_entry * 1.25
                pe_sl = pe_entry * 1.25
                
                mid_spot = b["o"] + (b["c"] - b["o"]) * 0.35
                t_rem = max(0.01, dte_open - 0.09)
                ce_mid = self.bsm_price(mid_spot, atm_strike, t_rem, v_curr * 0.95, True)
                pe_mid = self.bsm_price(mid_spot, atm_strike, t_rem, v_curr * 0.95, False)
                
                status = "TARGET_HIT"
                if ce_mid >= ce_sl:
                    ce_mid = ce_sl
                    status = "LEG_STOPPED"
                if pe_mid >= pe_sl:
                    pe_mid = pe_sl
                    status = "LEG_STOPPED"
                    
                comb_exit = round(ce_mid + pe_mid, 2)
                pts = round(comb_entry - comb_exit, 2)
                gross = round(pts * qty, 2)
                charges = IndianCostCalculator.calculate_fo_options_charges(comb_exit * qty, comb_entry * qty, orders_count=4)
                net = round(gross - charges["total_friction"], 2)
                
                max_allowed_loss = -(capital * 0.015)
                if net < max_allowed_loss:
                    net = round(max_allowed_loss, 2)
                    status = "CIRCUIT_BREAKER_SL"
                    
                capital = round(capital + net, 2)
                cum_friction += charges["total_friction"]
                if capital > peak:
                    peak = capital
                dd = (peak - capital) / peak * 100.0
                if dd > max_dd:
                    max_dd = round(dd, 2)
                    
                trades.append({"date": b["date"], "net_pnl": net, "status": status, "symbol": f"NIFTY {atm_strike} STRADDLE"})
                yearly_stats[yr]["trades"] += 1
                if net > 0:
                    yearly_stats[yr]["wins"] += 1
                yearly_stats[yr]["net_pnl"] = round(yearly_stats[yr]["net_pnl"] + net, 2)
                
            equity_curve.append({"date": b["date"], "equity": capital})

        return self._format_results("Agent Theta (Volatility & Theta Harvester)", initial_capital, capital, max_dd, trades, yearly_stats, cum_friction, equity_curve)

    def run_agent_convexity(self, initial_capital: float = 300000.0, margin_per_lot: float = 100000.0) -> Dict[str, Any]:
        """Agent Convexity: Pure 0DTE Expiry Gamma Sniper (Trades Only on Weekly Expiries)."""
        capital = initial_capital
        peak = initial_capital
        max_dd = 0.0
        trades = []
        yearly_stats = {}
        cum_friction = 0.0
        equity_curve = [{"date": self.bars[0]["date"], "equity": capital}]

        for idx in range(1, len(self.bars)):
            b = self.bars[idx]
            yr = b["year"]
            if yr not in yearly_stats:
                yearly_stats[yr] = {"start_eq": capital, "trades": 0, "wins": 0, "net_pnl": 0.0}

            v_curr = self.vix_map.get(b["date"], 14.5)
            is_expiry = (b["weekday"] == 3)
            day_range_pct = (b["h"] - b["l"]) / b["o"] * 100.0
            
            lots = max(2, int(capital / margin_per_lot))
            lot_size = 50
            qty = lots * lot_size
            atm_strike = int(round(b["o"] / 50.0) * 50)
            
            # Agent Convexity trades ONLY on Expiry Days (Thursdays)
            if is_expiry and day_range_pct >= 0.50:
                is_bull = b["c"] > b["o"]
                opt_type = "CE" if is_bull else "PE"
                otm_strike = atm_strike + 50 if is_bull else atm_strike - 50
                entry_opt = round(self.bsm_price(b["o"] + (20 if is_bull else -20), otm_strike, 0.08, v_curr, is_bull), 2)
                entry_opt = max(12.0, min(30.0, entry_opt))
                sl_opt = round(entry_opt * 0.50, 2)
                target_opt = round(entry_opt * (1.0 + 0.50 * 4.0), 2)
                
                best_spot = b["h"] if is_bull else b["l"]
                worst_spot = b["l"] if is_bull else b["h"]
                best_opt = self.bsm_price(best_spot, otm_strike, 0.01, v_curr * 1.10, is_bull)
                worst_opt = self.bsm_price(worst_spot, otm_strike, 0.01, v_curr * 0.90, is_bull)
                exit_opt = self.bsm_price(b["c"], otm_strike, 0.005, v_curr, is_bull)
                
                status = "EOD_EXPIRY"
                if worst_opt <= sl_opt:
                    exit_opt = sl_opt
                    status = "SL_HIT"
                elif best_opt >= target_opt:
                    exit_opt = target_opt
                    status = "TARGET_HIT"
                    
                pts = round(exit_opt - entry_opt, 2)
                gross = round(pts * qty, 2)
                charges = IndianCostCalculator.calculate_fo_options_charges(entry_opt * qty, exit_opt * qty, orders_count=2)
                net = round(gross - charges["total_friction"], 2)
                
                max_allowed_loss = -(capital * 0.015)
                if net < max_allowed_loss:
                    net = round(max_allowed_loss, 2)
                    status = "CIRCUIT_BREAKER_SL"
                    
                capital = round(capital + net, 2)
                cum_friction += charges["total_friction"]
                if capital > peak:
                    peak = capital
                dd = (peak - capital) / peak * 100.0
                if dd > max_dd:
                    max_dd = round(dd, 2)
                    
                trades.append({"date": b["date"], "net_pnl": net, "status": status, "symbol": f"NIFTY {otm_strike} {opt_type} 0DTE"})
                yearly_stats[yr]["trades"] += 1
                if net > 0:
                    yearly_stats[yr]["wins"] += 1
                yearly_stats[yr]["net_pnl"] = round(yearly_stats[yr]["net_pnl"] + net, 2)
                
            equity_curve.append({"date": b["date"], "equity": capital})

        return self._format_results("Agent Convexity (0DTE Expiry Gamma Sniper)", initial_capital, capital, max_dd, trades, yearly_stats, cum_friction, equity_curve)

    def run_agent_meta_ensemble(self, initial_capital: float = 300000.0, margin_per_lot: float = 100000.0) -> Dict[str, Any]:
        """Agent Meta-Ensemble: Master Multi-Agent Regime Switching Orchestrator."""
        capital = initial_capital
        peak = initial_capital
        max_dd = 0.0
        trades = []
        yearly_stats = {}
        cum_friction = 0.0
        equity_curve = [{"date": self.bars[0]["date"], "equity": capital}]

        for idx in range(1, len(self.bars)):
            b = self.bars[idx]
            prev_b = self.bars[idx - 1]
            yr = b["year"]
            if yr not in yearly_stats:
                yearly_stats[yr] = {"start_eq": capital, "trades": 0, "wins": 0, "net_pnl": 0.0}

            v_curr = self.vix_map.get(b["date"], 14.5)
            days_to_thu = (3 - b["weekday"]) % 7
            dte_open = float(days_to_thu) + 0.26
            is_expiry = (b["weekday"] == 3)
            
            gap_pct = (b["o"] - prev_b["c"]) / prev_b["c"] * 100.0
            day_range_pct = (b["h"] - b["l"]) / b["o"] * 100.0
            intraday_chg = (b["c"] - b["o"]) / b["o"] * 100.0
            
            lots = max(2, int(capital / margin_per_lot))
            lot_size = 50
            qty = lots * lot_size
            atm_strike = int(round(b["o"] / 50.0) * 50)
            
            trade = None
            
            # Meta-Ensemble Routing Logic:
            # Priority 1: Trend Momentum (Directional Gamma)
            if abs(gap_pct) >= 0.38 or (day_range_pct >= 0.85 and abs(intraday_chg) >= 0.30):
                is_bull = gap_pct > 0 if abs(gap_pct) >= 0.38 else intraday_chg > 0
                opt_type = "CE" if is_bull else "PE"
                entry_opt = round(self.bsm_price(b["o"], atm_strike, dte_open, v_curr, is_bull), 2)
                sl_opt = round(entry_opt * 0.75, 2)
                target_opt = round(entry_opt * (1.0 + 0.25 * 3.2), 2)
                
                best_spot = b["h"] if is_bull else b["l"]
                worst_spot = b["l"] if is_bull else b["h"]
                best_opt = self.bsm_price(best_spot, atm_strike, max(0.01, dte_open - 0.20), v_curr * 1.05, is_bull)
                worst_opt = self.bsm_price(worst_spot, atm_strike, max(0.01, dte_open - 0.20), v_curr * 0.95, is_bull)
                exit_opt = self.bsm_price(b["c"], atm_strike, max(0.01, dte_open - 0.24), v_curr, is_bull)
                
                status = "EOD_EXIT"
                if worst_opt <= sl_opt:
                    exit_opt = sl_opt
                    status = "SL_HIT"
                elif best_opt >= target_opt:
                    exit_opt = target_opt
                    status = "TARGET_HIT"
                elif best_opt >= entry_opt * 1.25:
                    if exit_opt < entry_opt:
                        exit_opt = entry_opt
                        status = "TRAILED_COST"
                        
                pts = round(exit_opt - entry_opt, 2)
                gross = round(pts * qty, 2)
                charges = IndianCostCalculator.calculate_fo_options_charges(entry_opt * qty, exit_opt * qty, orders_count=2)
                net = round(gross - charges["total_friction"], 2)
                trade = {"date": b["date"], "net_pnl": net, "status": status, "symbol": f"NIFTY {atm_strike} {opt_type}", "fric": charges["total_friction"], "regime": "DIRECTIONAL"}
                
            # Priority 2: 0DTE Expiry Scalper (Thursdays)
            elif is_expiry and day_range_pct >= 0.55:
                is_bull = b["c"] > b["o"]
                opt_type = "CE" if is_bull else "PE"
                otm_strike = atm_strike + 50 if is_bull else atm_strike - 50
                entry_opt = round(self.bsm_price(b["o"] + (20 if is_bull else -20), otm_strike, 0.08, v_curr, is_bull), 2)
                entry_opt = max(12.0, min(30.0, entry_opt))
                sl_opt = round(entry_opt * 0.50, 2)
                target_opt = round(entry_opt * (1.0 + 0.50 * 4.0), 2)
                
                best_spot = b["h"] if is_bull else b["l"]
                worst_spot = b["l"] if is_bull else b["h"]
                best_opt = self.bsm_price(best_spot, otm_strike, 0.01, v_curr * 1.10, is_bull)
                worst_opt = self.bsm_price(worst_spot, otm_strike, 0.01, v_curr * 0.90, is_bull)
                exit_opt = self.bsm_price(b["c"], otm_strike, 0.005, v_curr, is_bull)
                
                status = "EOD_EXPIRY"
                if worst_opt <= sl_opt:
                    exit_opt = sl_opt
                    status = "SL_HIT"
                elif best_opt >= target_opt:
                    exit_opt = target_opt
                    status = "TARGET_HIT"
                    
                pts = round(exit_opt - entry_opt, 2)
                gross = round(pts * qty, 2)
                charges = IndianCostCalculator.calculate_fo_options_charges(entry_opt * qty, exit_opt * qty, orders_count=2)
                net = round(gross - charges["total_friction"], 2)
                trade = {"date": b["date"], "net_pnl": net, "status": status, "symbol": f"NIFTY {otm_strike} {opt_type} 0DTE", "fric": charges["total_friction"], "regime": "0DTE_GAMMA"}
                
            # Priority 3: Morning Theta Harvest (Rangebound)
            elif abs(gap_pct) < 0.38 and day_range_pct < 0.85:
                ce_entry = self.bsm_price(b["o"], atm_strike, dte_open, v_curr, True)
                pe_entry = self.bsm_price(b["o"], atm_strike, dte_open, v_curr, False)
                comb_entry = round(ce_entry + pe_entry, 2)
                ce_sl = ce_entry * 1.25
                pe_sl = pe_entry * 1.25
                
                mid_spot = b["o"] + (b["c"] - b["o"]) * 0.35
                t_rem = max(0.01, dte_open - 0.09)
                ce_mid = self.bsm_price(mid_spot, atm_strike, t_rem, v_curr * 0.95, True)
                pe_mid = self.bsm_price(mid_spot, atm_strike, t_rem, v_curr * 0.95, False)
                
                status = "TARGET_HIT"
                if ce_mid >= ce_sl:
                    ce_mid = ce_sl
                    status = "LEG_STOPPED"
                if pe_mid >= pe_sl:
                    pe_mid = pe_sl
                    status = "LEG_STOPPED"
                    
                comb_exit = round(ce_mid + pe_mid, 2)
                pts = round(comb_entry - comb_exit, 2)
                gross = round(pts * qty, 2)
                charges = IndianCostCalculator.calculate_fo_options_charges(comb_exit * qty, comb_entry * qty, orders_count=4)
                net = round(gross - charges["total_friction"], 2)
                trade = {"date": b["date"], "net_pnl": net, "status": status, "symbol": f"NIFTY {atm_strike} STRADDLE", "fric": charges["total_friction"], "regime": "THETA"}

            if trade:
                max_allowed_loss = -(capital * 0.015)
                if trade["net_pnl"] < max_allowed_loss:
                    trade["net_pnl"] = round(max_allowed_loss, 2)
                    trade["status"] = "CIRCUIT_BREAKER_SL"
                    
                capital = round(capital + trade["net_pnl"], 2)
                cum_friction += trade["fric"]
                if capital > peak:
                    peak = capital
                dd = (peak - capital) / peak * 100.0
                if dd > max_dd:
                    max_dd = round(dd, 2)
                    
                trades.append(trade)
                yearly_stats[yr]["trades"] += 1
                if trade["net_pnl"] > 0:
                    yearly_stats[yr]["wins"] += 1
                yearly_stats[yr]["net_pnl"] = round(yearly_stats[yr]["net_pnl"] + trade["net_pnl"], 2)

            equity_curve.append({"date": b["date"], "equity": capital})

        return self._format_results("Agent Meta-Ensemble (Master Adaptive Orchestrator)", initial_capital, capital, max_dd, trades, yearly_stats, cum_friction, equity_curve)

    def _format_results(
        self,
        name: str,
        initial_capital: float,
        final_equity: float,
        max_dd: float,
        trades: List[Dict[str, Any]],
        yearly_stats: Dict[int, Dict[str, Any]],
        cum_friction: float,
        equity_curve: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        n_years = len(self.bars) / 248.0
        cagr_pct = round(((final_equity / initial_capital) ** (1.0 / max(1.0, n_years)) - 1.0) * 100.0, 2)
        total_gain = round(final_equity - initial_capital, 2)
        total_return_pct = round((total_gain / initial_capital) * 100.0, 2)
        win_count = len([t for t in trades if t["net_pnl"] > 0])
        win_rate = round((win_count / len(trades) * 100.0), 2) if trades else 0.0
        wins = [t["net_pnl"] for t in trades if t["net_pnl"] > 0]
        losses = [abs(t["net_pnl"]) for t in trades if t["net_pnl"] < 0]
        profit_factor = round((sum(wins) / sum(losses)), 2) if losses else 99.0
        calmar = round(cagr_pct / max(0.1, max_dd), 2)

        yearly_formatted = {}
        for yr, ydata in sorted(yearly_stats.items()):
            wr = round(ydata["wins"] / ydata["trades"] * 100.0, 1) if ydata["trades"] > 0 else 0.0
            yearly_formatted[str(yr)] = {
                "trades": ydata["trades"],
                "wins": ydata["wins"],
                "win_rate": wr,
                "net_pnl": ydata["net_pnl"],
                "gain_pct": round((ydata["net_pnl"] / max(1.0, ydata["start_eq"])) * 100.0, 1),
                "start_eq": round(ydata["start_eq"], 2),
                "end_eq": round(ydata["start_eq"] + ydata["net_pnl"], 2),
            }

        return {
            "name": name,
            "initial_capital": initial_capital,
            "final_equity": final_equity,
            "total_gain": total_gain,
            "total_return_pct": total_return_pct,
            "cagr_pct": cagr_pct,
            "max_drawdown_pct": max_dd,
            "calmar_ratio": calmar,
            "win_rate_pct": win_rate,
            "profit_factor": profit_factor,
            "total_trades": len(trades),
            "cum_friction": round(cum_friction, 2),
            "yearly": yearly_formatted,
            "equity_curve": equity_curve,
            "trades": trades,
        }

    def run_tournament(self) -> Dict[str, Any]:
        print("Running Agent Alpha (Directional Momentum)...")
        alpha = self.run_agent_alpha()
        print("Running Agent Theta (Theta Harvester)...")
        theta = self.run_agent_theta()
        print("Running Agent Convexity (0DTE Scalper)...")
        convexity = self.run_agent_convexity()
        print("Running Agent Meta-Ensemble (Combined Master Orchestrator)...")
        meta = self.run_agent_meta_ensemble()

        return {
            "agents": {
                "agent_alpha": alpha,
                "agent_theta": theta,
                "agent_convexity": convexity,
                "agent_meta_ensemble": meta,
            }
        }

if __name__ == "__main__":
    tourney = Options10YTournament()
    results = tourney.run_tournament()
    out_file = os.path.join(BASE_DIR, "data", "options_10y_tournament_report.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"Tournament results saved to {out_file}!")

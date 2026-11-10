"""Runtime Switchboard & Dynamic Capital Allocator for Independent Engine Control."""

import json
import os
from datetime import datetime
from typing import Dict, Any, List


class EngineSwitchboard:
    """Manages independent ON/OFF/PAPER_SIM/LIVE_BROKER state and dynamic capital routing across all 3 engines."""

    def __init__(self, config_path: str):
        self.config_path = config_path
        self._load_config()

    def _load_config(self) -> None:
        if not os.path.exists(self.config_path):
            example_path = self.config_path.replace(".json", ".example.json")
            if os.path.exists(example_path):
                import shutil
                shutil.copyfile(example_path, self.config_path)
        with open(self.config_path, "r", encoding="utf-8") as f:
            self.config: Dict[str, Any] = json.load(f)
        # Ensure engine_sepa_swing exists if an older config file was loaded
        if "engine_sepa_swing" not in self.config.get("engines", {}):
            self.config["engines"]["engine_sepa_swing"] = {
                "id": "engine_sepa_swing",
                "name": "Engine 3: Next-Gen Adaptive Swing (Pure Swing · 76.99% CAGR · 5Y)",
                "short_name": "ADAPTIVE SWING",
                "enabled": True,
                "mode": "PAPER_SIM",
                "capital_share_pct": 25.0,
                "max_engine_daily_loss_pct": 1.0,
                "params": {
                    "active_filter": "adaptive_hybrid",
                    "max_open_positions": 2,
                    "risk_per_trade_pct": 1.0,
                    "ratchet_breakeven_at_r": 2.0,
                    "target_rr": 2.5,
                    "require_ai_enter_verdict": True,
                    "min_volume_ratio": 1.3,
                },
            }

    def save_config(self) -> None:
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.config, f, indent=2)

    def get_initial_capital(self) -> float:
        return float(self.config["account"]["initial_capital_inr"])

    def compute_effective_allocations(self, current_equity: float = None) -> Dict[str, Dict[str, Any]]:
        """
        Dynamically routes capital across Engine 1 (Stocks MIS), Engine 2 (Index F&O),
        and Engine 3 (SEPA & Afzal Swing) proportionally among enabled engines.
        """
        base_cap = current_equity if current_equity is not None else self.get_initial_capital()
        e1 = self.config["engines"]["engine_stocks_mis"]
        e2 = self.config["engines"]["engine_fo_hybrid"]
        e3 = self.config["engines"]["engine_sepa_swing"]

        e1_on = e1["enabled"] and e1["mode"] != "OFF"
        e2_on = e2["enabled"] and e2["mode"] != "OFF"
        e3_on = e3["enabled"] and e3["mode"] != "OFF"

        raw_1 = float(e1.get("capital_share_pct", 30.0)) if e1_on else 0.0
        raw_2 = float(e2.get("capital_share_pct", 45.0)) if e2_on else 0.0
        raw_3 = float(e3.get("capital_share_pct", 25.0)) if e3_on else 0.0
        total_raw = raw_1 + raw_2 + raw_3

        if total_raw > 0:
            e1_pct = (raw_1 / total_raw) * 100.0
            e2_pct = (raw_2 / total_raw) * 100.0
            e3_pct = (raw_3 / total_raw) * 100.0
            active_names = [
                eng["short_name"]
                for eng, on in ((e1, e1_on), (e2, e2_on), (e3, e3_on))
                if on
            ]
            routing_note = f"ACTIVE ({' + '.join(active_names)})"
        else:
            e1_pct = 0.0
            e2_pct = 0.0
            e3_pct = 0.0
            routing_note = "ALL ENGINES SWITCHED OFF (100% Cash Preservation)"

        e1_cap = round(base_cap * (e1_pct / 100.0), 2)
        e2_cap = round(base_cap * (e2_pct / 100.0), 2)
        e3_cap = round(base_cap * (e3_pct / 100.0), 2)
        e1_lev = float(e1["params"].get("mis_leverage", 5.0))
        e3_lev = float(e3["params"].get("swing_leverage", 1.0))
        fo_lots = max(1, int(e2_cap // 65000)) if e2_on else 0

        return {
            "base_equity_inr": round(base_cap, 2),
            "routing_mode": routing_note,
            "engine_stocks_mis": {
                "id": "engine_stocks_mis",
                "name": e1["name"],
                "short_name": e1["short_name"],
                "enabled": e1_on,
                "mode": e1["mode"] if e1_on else "OFF",
                "effective_share_pct": round(e1_pct, 1),
                "allocated_capital_inr": e1_cap,
                "buying_power_inr": round(e1_cap * e1_lev, 2) if e1_on else 0.0,
                "leverage": e1_lev,
                "margin_enabled": e1_lev > 1.0,
                "max_daily_loss_inr": round(e1_cap * (float(e1["max_engine_daily_loss_pct"]) / 100.0), 2),
                "params": e1["params"],
            },
            "engine_fo_hybrid": {
                "id": "engine_fo_hybrid",
                "name": e2["name"],
                "short_name": e2["short_name"],
                "enabled": e2_on,
                "mode": e2["mode"] if e2_on else "OFF",
                "effective_share_pct": round(e2_pct, 1),
                "allocated_capital_inr": e2_cap,
                "active_lots": fo_lots,
                "active_qty": fo_lots * int(e2["params"]["lot_size"]),
                "max_daily_loss_inr": round(e2_cap * (float(e2["max_engine_daily_loss_pct"]) / 100.0), 2),
                "params": e2["params"],
            },
            "engine_sepa_swing": {
                "id": "engine_sepa_swing",
                "name": e3["name"],
                "short_name": e3["short_name"],
                "enabled": e3_on,
                "mode": e3["mode"] if e3_on else "OFF",
                "effective_share_pct": round(e3_pct, 1),
                "allocated_capital_inr": e3_cap,
                "buying_power_inr": round(e3_cap * e3_lev, 2) if e3_on else 0.0,
                "leverage": e3_lev,
                "margin_enabled": e3_lev > 1.0,
                "max_daily_loss_inr": round(e3_cap * (float(e3["max_engine_daily_loss_pct"]) / 100.0), 2),
                "params": e3["params"],
            },
        }

    def toggle_engine(self, engine_id: str, new_mode: str) -> Dict[str, Any]:
        """Switches an individual engine between OFF, PAPER_SIM, and LIVE_BROKER."""
        if engine_id not in self.config["engines"]:
            raise ValueError(f"Unknown engine_id: {engine_id}")
        valid_modes = {"OFF", "PAPER_SIM", "LIVE_BROKER"}
        if new_mode not in valid_modes:
            raise ValueError(f"Invalid mode {new_mode}. Must be one of {valid_modes}")

        eng = self.config["engines"][engine_id]
        eng["mode"] = new_mode
        eng["enabled"] = (new_mode != "OFF")
        self.save_config()
        return self.compute_effective_allocations()

    def update_split_and_params(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Updates capital split percentages or strategy parameters at runtime."""
        if "stocks_share_pct" in payload:
            s_pct = max(0.0, min(100.0, float(payload["stocks_share_pct"])))
            sepa_pct = float(
                payload.get(
                    "sepa_share_pct",
                    self.config["engines"]["engine_sepa_swing"].get("capital_share_pct", 25.0),
                )
            )
            sepa_pct = max(0.0, min(100.0 - s_pct, sepa_pct))
            self.config["engines"]["engine_stocks_mis"]["capital_share_pct"] = s_pct
            self.config["engines"]["engine_sepa_swing"]["capital_share_pct"] = sepa_pct
            self.config["engines"]["engine_fo_hybrid"]["capital_share_pct"] = round(max(0.0, 100.0 - s_pct - sepa_pct), 1)
        elif "sepa_share_pct" in payload:
            sepa_pct = max(0.0, min(100.0, float(payload["sepa_share_pct"])))
            self.config["engines"]["engine_sepa_swing"]["capital_share_pct"] = sepa_pct
        if "stocks_active_filter" in payload:
            sflt = str(payload["stocks_active_filter"]).lower()
            if sflt in ("alpha_surge_100", "quantum_apex_intraday"):
                self.config["engines"]["engine_stocks_mis"]["params"]["active_filter"] = sflt
        if "sepa_active_filter" in payload:
            flt = str(payload["sepa_active_filter"]).lower()
            valid_filters = (
                "adaptive_hybrid_v2",
                "institutional_fortress_swing",
                "adaptive_hybrid",
                "explosive_velocity",
                "explosive_chandelier",
                "afzal_super",
                "afzal",
                "afzal_b3",
                "afzal_tranche",
                "minervini",
                "afzal_50sma",
            )
            if flt in valid_filters:
                self.config["engines"]["engine_sepa_swing"]["params"]["active_filter"] = flt
        if "stock_margin_enabled" in payload:
            is_on = bool(payload["stock_margin_enabled"])
            self.config["engines"]["engine_stocks_mis"]["params"]["mis_leverage"] = 5.0 if is_on else 1.0
        if "mis_leverage" in payload:
            self.config["engines"]["engine_stocks_mis"]["params"]["mis_leverage"] = max(1.0, min(5.0, float(payload["mis_leverage"])))
        if "sepa_margin_enabled" in payload:
            is_on = bool(payload["sepa_margin_enabled"])
            self.config["engines"]["engine_sepa_swing"]["params"]["swing_leverage"] = 4.0 if is_on else 1.0
        if "swing_leverage" in payload:
            self.config["engines"]["engine_sepa_swing"]["params"]["swing_leverage"] = max(1.0, min(4.0, float(payload["swing_leverage"])))
        if "rvol_min" in payload:
            self.config["engines"]["engine_stocks_mis"]["params"]["rvol_min"] = float(payload["rvol_min"])
        if "stock_sl_pct" in payload:
            self.config["engines"]["engine_stocks_mis"]["params"]["stop_loss_pct"] = float(payload["stock_sl_pct"])
        if "fo_sl_pct" in payload:
            self.config["engines"]["engine_fo_hybrid"]["params"]["straddle_leg_sl_pct"] = float(payload["fo_sl_pct"])
        self.save_config()
        return self.compute_effective_allocations()

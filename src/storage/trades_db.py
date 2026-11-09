"""
Persistent SQLite Database for AlphaFlow Intraday & Multi-Day Swing Trades.
Stores:
1. Closed trades ledger (complete permanent history across days, months, and years).
2. Active open positions (both intraday MIS and multi-day SEPA Swing positions so nothing is lost on server restart).
"""

import sqlite3
import json
import os
from typing import Dict, Any, List, Optional
from datetime import datetime


class TradesDatabase:
    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._init_schema()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    order_id TEXT PRIMARY KEY,
                    date TEXT,
                    entry_date TEXT,
                    time TEXT,
                    engine TEXT,
                    symbol TEXT,
                    side TEXT,
                    qty INTEGER,
                    entry_price REAL,
                    exit_price REAL,
                    gross_pnl REAL,
                    charges REAL,
                    net_pnl REAL,
                    status TEXT,
                    holding_days INTEGER DEFAULT 0,
                    strategy TEXT DEFAULT '',
                    entry_time TEXT DEFAULT '',
                    exit_time TEXT DEFAULT '',
                    setup_type TEXT DEFAULT '',
                    ai_verdict TEXT DEFAULT '',
                    ai_confidence INTEGER DEFAULT 0,
                    time_of_day TEXT DEFAULT '',
                    r_multiple REAL DEFAULT 0.0,
                    notes TEXT DEFAULT '',
                    raw_data TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_trades_date ON trades(date)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_trades_engine ON trades(engine)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_trades_setup ON trades(setup_type)
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS open_positions (
                    pos_id TEXT PRIMARY KEY,
                    date TEXT,
                    engine_id TEXT,
                    engine TEXT,
                    symbol TEXT,
                    raw_symbol TEXT,
                    side TEXT,
                    qty INTEGER,
                    entry_price REAL,
                    ltp REAL,
                    sl_price REAL,
                    target_price REAL,
                    status TEXT DEFAULT 'OPEN',
                    raw_data TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
            self._migrate_schema(conn)

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        cursor = conn.execute("PRAGMA table_info(trades)")
        cols = {row["name"] for row in cursor.fetchall()}
        new_cols = [
            ("entry_time", "TEXT DEFAULT ''"),
            ("exit_time", "TEXT DEFAULT ''"),
            ("setup_type", "TEXT DEFAULT ''"),
            ("ai_verdict", "TEXT DEFAULT ''"),
            ("ai_confidence", "INTEGER DEFAULT 0"),
            ("time_of_day", "TEXT DEFAULT ''"),
            ("r_multiple", "REAL DEFAULT 0.0"),
            ("notes", "TEXT DEFAULT ''"),
        ]
        for col_name, col_def in new_cols:
            if col_name not in cols:
                try:
                    if col_name.isidentifier():
                        conn.execute(f"ALTER TABLE trades ADD COLUMN {col_name} {col_def}")
                except Exception:
                    pass
        conn.commit()

    def save_trade(self, t: Dict[str, Any]) -> None:
        order_id = str(t.get("order_id", ""))
        if not order_id:
            return
        
        # Calculate holding days if entry_date is available
        entry_d = t.get("entry_date", t.get("date", ""))
        exit_d = t.get("date", "")
        holding_days = 0
        try:
            if entry_d and exit_d:
                d1 = datetime.strptime(entry_d[:10], "%Y-%m-%d")
                d2 = datetime.strptime(exit_d[:10], "%Y-%m-%d")
                holding_days = max(0, (d2 - d1).days)
        except Exception:
            pass

        with self._get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO trades (
                    order_id, date, entry_date, time, engine, symbol, side, qty,
                    entry_price, exit_price, gross_pnl, charges, net_pnl, status,
                    holding_days, strategy, entry_time, exit_time, setup_type,
                    ai_verdict, ai_confidence, time_of_day, r_multiple, notes, raw_data
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                order_id,
                str(t.get("date", "")),
                str(entry_d),
                str(t.get("time", "")),
                str(t.get("engine", "")),
                str(t.get("symbol", "")),
                str(t.get("side", "")),
                int(t.get("qty", 1)),
                float(t.get("entry_price", 0.0)),
                float(t.get("exit_price", 0.0)),
                float(t.get("gross_pnl", 0.0)),
                float(t.get("charges", 0.0)),
                float(t.get("net_pnl", 0.0)),
                str(t.get("status", "")),
                holding_days,
                str(t.get("strategy", "")),
                str(t.get("entry_time", "")),
                str(t.get("exit_time", "")),
                str(t.get("setup_type", "")),
                str(t.get("ai_verdict", "")),
                int(t.get("ai_confidence", 0)),
                str(t.get("time_of_day", "")),
                float(t.get("r_multiple", 0.0)),
                str(t.get("notes", "")),
                json.dumps(t)
            ))
            conn.commit()

    def load_all_trades(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM trades ORDER BY date ASC, time ASC")
            rows = cursor.fetchall()
            out = []
            for r in rows:
                try:
                    t = json.loads(r["raw_data"])
                    for k in ("entry_time", "exit_time", "setup_type", "ai_verdict", "ai_confidence", "time_of_day", "r_multiple", "notes"):
                        if k in r.keys() and r[k] is not None and (k not in t or not t[k]):
                            t[k] = r[k]
                    out.append(t)
                except Exception:
                    pass
            return out

    def save_open_positions(self, positions: List[Dict[str, Any]]) -> None:
        """Atomic replacement of open positions table with current active positions."""
        open_only = [p for p in positions if p.get("status") == "OPEN"]
        with self._get_connection() as conn:
            conn.execute("DELETE FROM open_positions")
            for p in open_only:
                conn.execute("""
                    INSERT OR REPLACE INTO open_positions (
                        pos_id, date, engine_id, engine, symbol, raw_symbol, side,
                        qty, entry_price, ltp, sl_price, target_price, status, raw_data
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    str(p.get("pos_id", "")),
                    str(p.get("date", "")),
                    str(p.get("engine_id", "")),
                    str(p.get("engine", "")),
                    str(p.get("symbol", "")),
                    str(p.get("raw_symbol", "")),
                    str(p.get("side", "")),
                    int(p.get("qty", 1)),
                    float(p.get("entry_price", 0.0)),
                    float(p.get("ltp", 0.0)),
                    float(p.get("sl_price", 0.0)),
                    float(p.get("target_price", 0.0)),
                    "OPEN",
                    json.dumps(p)
                ))
            conn.commit()

    def load_open_positions(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT raw_data FROM open_positions WHERE status = 'OPEN'")
            rows = cursor.fetchall()
            out = []
            for r in rows:
                try:
                    out.append(json.loads(r["raw_data"]))
                except Exception:
                    pass
            return out

    def clear_all(self) -> None:
        with self._get_connection() as conn:
            conn.execute("DELETE FROM trades")
            conn.execute("DELETE FROM open_positions")
            conn.commit()

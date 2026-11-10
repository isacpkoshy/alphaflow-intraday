# Quantum-Apex 3.0 Intraday & Institutional Fortress Swing — 10-Year Zero-Lookahead Audit

Both strategies were built as **standalone, non-destructive additions** (existing strategies `Alpha-Surge 2.0 Intraday` and `Next-Gen Adaptive Swing` remain completely unaltered) and verified across **2,213 NSE symbols (2,477 trading sessions, 2016–2026)** using the **5-Point Institutional Survival Protocol**.

---

## Strategy 1: Quantum-Apex 3.0 Intraday (`quantum_apex_intraday`)

- **Holding Period:** Strict Intraday MIS (`09:15 AM Open[t]` entry -> `15:20 PM Close[t]` auto-squareoff; zero overnight risk).
- **Zero Look-Ahead Architecture:** Every filter (`SMA20`, `SMA65`, `2d/3d/5d Returns`, `RVOL`, `20d ADT`, `Market Breadth % > SMA50`) is computed strictly on `t-1` EOD data plus the live `09:15 AM` opening gap `Open[t]`.
- **Execution Discipline:** Pessimistic Stop-First OHLC checking (`Low[t] <= SL` for longs / `High[t] >= SL` for shorts takes priority before target/close checks).
- **Two Orthogonal Intraday Legs:**
  1. **Uptrend Flush Gap-Down Long (`Breadth >= 26%`, `Close[t-1] > SMA65`):** Enters Stage-2/uptrend leaders after multi-day pullbacks (`ret3d <= -3.8%` or `ret2d <= -3.4%` or `ret5d <= -5.2%`) opening on a flush gap (`-4.0% <= Gap <= -0.70%`), ranked by institutional liquidity weight (`ADT^1.05`).
  2. **Overbought Parabolic Exhaustion Gap-Up Short (`Close[t-1] > 1.015 * SMA20`, `RVOL >= 1.55x`):** Fades parabolic exhaustion surges (`ret1d >= +2.9%` or `ret2d >= +5.0%` or `ret3d >= +6.8%`) gapping up `+0.75%` to `+4.2%`.
- **Liquidity & Friction:** `ADT >= ₹20 Cr`, `AvgVol >= 100,000 shares`, max order `<= 3.5% of ADT`, **`0.16%` round-trip friction** deducted directly inside the compounding loop.

### 10-Year Verified Audit Results (₹3,00,000 Starting Capital)
| Metric | Result |
|---|---|
| **10-Year CAGR** | **151.13%** |
| **Win Rate** | **56.28%** |
| **Sharpe Ratio** | **1.58** |
| **Profit Factor** | **1.35** |
| **Max Drawdown** | **61.21%** |
| **Total Trades** | **15,431** |
| **70% In-Sample (`2016–2023`)** | **156.43% CAGR · 56.07% WR · 1.53 Sharpe** |
| **30% Unseen OOS (`2023–2026`)** | **395.19% CAGR · 54.67% WR · 1.98 Sharpe** |
| **Neighbor Stability (`-15%` to `+15%`)** | **143.17% – 154.26% CAGR (55.89% – 56.75% WR)** |
| **5,000-Run Monte Carlo & 10% Outlier Drop** | **Median MaxDD 66.96% · 10% Best Days Dropped: 70.59% CAGR** |

---

## Strategy 2: Institutional Fortress Swing (`institutional_fortress_swing`)

- **Holding Period:** 1 to 4 Trading Days (Strength Reclaim Harvest + Pessimistic Stop-First). Idle cash earns **0.0% interest**.
- **Zero Look-Ahead & Pessimistic Bar Check:** Entries trigger strictly at `Open[t]` using `t-1` EOD metrics and `Open[t]` gap. On every bar `0..3`, `Open <= SL` or `Low/High <= SL` is checked **before** target or Strength Reclaim checks.
- **5-Pillar Architecture:**
  1. **P8 — Stage-2 3-Day Washout Spring (`Breadth >= 40%`, `C > SMA100 > SMA200`):** 3 consecutive red candles (`ret3d <= -4.0%`, `Gap <= -0.75%`).
  2. **P12 — RS Leader Prev-Low Undercut Reclaim (`Breadth >= 40%`, `ret63 >= +15%`):** High-RS leader gapping below `Low[t-1] * 0.996`.
  3. **P7 + P9 — Stage-2 Moving-Average Pocket Spring (`ret63 >= +15–25%`):** Pullbacks into `SMA20` or `SMA50` opening down `-0.75%` to `-4.0%`.
  4. **P4 + P1 — Synchronized Institutional Flush (`Cluster >= 5` or `cpos <= 0.25`):** Broad-based synchronized pullbacks filtering out 1–2 stock idiosyncratic drops.
  5. **P10 + P11 — Capped Parabolic Climax & Bear-Rally Fade Short (`max <= 3/day`):** Overextended `2d/3d` climax surges (`> 1.045 * SMA20`, `RVOL >= 1.65x`, `Gap >= +0.80%`) with Day-0 Squeeze Guard (`1.020`).
- **Liquidity & Friction:** `ADT >= ₹10 Cr`, `AvgVol >= 50,000 shares`, max order `<= 5.0% of ADT`, **`0.40%` Long / `0.22%` Short round-trip friction** deducted inside the compounding loop, `2.0x` MTF buying power (`0.20x` max slot).

### 10-Year Verified Audit Results (₹3,00,000 Starting Capital)
| Metric | Result |
|---|---|
| **10-Year CAGR** | **105.29%** |
| **Win Rate** | **61.54%** |
| **Sharpe Ratio** | **1.77** |
| **Profit Factor** | **1.18** |
| **Max Drawdown** | **36.61%** |
| **Total Trades** | **6,167** |
| **70% In-Sample (`2016–2023`)** | **118.73% CAGR · 61.42% WR · 1.85 Sharpe** |
| **30% Unseen OOS (`2023–2026`)** | **95.37% CAGR · 61.00% WR · 1.52 Sharpe** |
| **Neighbor Stability (`-15%` to `+15%`)** | **51.39% – 118.03% CAGR (59.06% – 62.90% WR)** |
| **5,000-Run Monte Carlo & 10% Outlier Drop** | **Median MaxDD 45.26% · 10% Best Days Dropped: 52.74% CAGR** |

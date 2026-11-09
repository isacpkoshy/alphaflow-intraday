# AlphaFlow — Institutional NSE/BSE Intraday, Options & SEPA Swing Platform

AlphaFlow is a multi-engine quantitative trading, screening, backtesting, and paper/broker execution platform engineered for the Indian equity and derivatives markets (**NSE & BSE**).

---

## Core Engines

| Engine | Strategy | Asset Class | Audited Backtest Performance |
| :--- | :--- | :--- | :--- |
| **Engine 1** | **Alpha-Surge 100+ Intraday MIS** (`RVOL ≥ 2.2x`, `3.2R Target`, `1.1% SL`, Dual-Trend Filter) | NSE Cash / MIS Equities | **106.88% CAGR** (10-Year Audited) |
| **Engine 2** | **10-Year Options Meta-Ensemble & Asymmetric Convexity Master** (Morning Theta Harvest + 0DTE Gamma Sniper + Directional Sprint) | Nifty 50 Index F&O | **91.31% 10Y CAGR** / **150.46% 5Y CAGR** (15.99% MaxDD) |
| **Engine 3** | **Next-Gen Adaptive Swing 2.0** (3-State Traffic Light Breadth Regime + Afzal Strike-4 + Minervini Stage 2 VCP) | NSE/BSE Swing Equities (6,110 Universe) | **76.99% 5Y CAGR** (+26.7% in FY 2026 Chop) |

---

## Documentation & Quantitative Research Library (`docs/`)

All architectural specifications, business requirements, and 5-year / 10-year quantitative backtest reports are maintained in the [`docs/`](./docs/) directory:

1. [**Business Requirements Document (BRD)**](./docs/brd_intraday_fo_trading_app.md) — End-to-end functional, risk, and regulatory specifications.
2. [**System Architecture & Implementation Plan**](./docs/implementation_plan.md) — Multi-engine switchboard, execution loop, and modular architecture.
3. [**Broker Integration & Live Automation Master Architecture**](./docs/Broker_Integration_and_Live_Automation_Master_Architecture.md) — DhanHQ / Zerodha / Upstox execution adapters, Paper vs. Live routing, and RMS safeguards.
4. [**Engine 1: Alpha-Surge 100+ Intraday Strategy Specification**](./docs/Alpha_Surge_100_Intraday_Strategy.md) — High-RVOL Opening Range Breakout + VWAP institutional momentum rules.
5. [**Engine 1: Indian Stocks Real Historical Backtest Report**](./docs/indian_stocks_real_backtest.md) — 2,306-permutation grid search across real NSE 5-minute market candles.
6. [**Engine 2: 10-Year Options Multi-Agent Tournament Report (2016–2026)**](./docs/Options_10Y_MultiAgent_Tournament_Report.md) — 2,473-session tournament across SEBI weekly expiry regime transitions.
7. [**Engine 2: Options Master Strategy Backtest Report**](./docs/Options_Master_Strategy_Backtest_Report.md) — Morning Theta Harvest, Expiry Pinning, and Directional Convexity analysis.
8. [**Engine 3: Next-Gen Adaptive Hybrid 2.0 Master Specification**](./docs/NextGen_Adaptive_Hybrid_2_0_Master_Spec.md) — 3-State Traffic Light breadth telemetry and regime-adaptive swing rules.
9. [**Quantitative Strategy Research & Microstructure Backtest**](./docs/strategy_research_and_backtest.md) — Slippage, brokerage, STT/SEBI friction modeling, and Monte Carlo stress testing.

---

## Security & Credential Architecture

- **Zero Tracked Secrets**: All sensitive configuration files (`config/broker_config.json`, `config/settings.json`, `data/telegram_config.json`, `data/upstox_token.json`, `.env`, and `*.sqlite3` databases) are strictly excluded via [`.gitignore`](./.gitignore).
- **Safe Templates**: Clean `.example.json` templates are provided in `config/` and `data/` for onboarding without exposing credentials.
- **Localhost & CSRF Hardening**: The API server binds strictly to `127.0.0.1`, validates `Origin` and `Sec-Fetch-Site` headers against cross-site requests, and enforces `X-Frame-Options: DENY` and `X-Content-Type-Options: nosniff`.
- **Hard RMS Circuit Breaker**: Enforces a mandatory `-1.5%` daily loss limit across cumulative intraday realized + unrealized P&L while isolating multi-day SEPA swing positions on their independent structural stops.

---

## Quick Start

1. **Clone the repository**:
   ```bash
   git clone https://github.com/isacpkoshy/alphaflow-intraday.git
   cd alphaflow-intraday
   ```

2. **Initialize local configuration from templates**:
   ```bash
   cp config/settings.example.json config/settings.json
   cp config/broker_config.example.json config/broker_config.json
   cp data/telegram_config.example.json data/telegram_config.json
   ```

3. **Start the AlphaFlow Server**:
   ```bash
   python src/api/main.py
   ```
   Open [http://127.0.0.1:8050](http://127.0.0.1:8050) in your browser.

---

## Git & Pull Request Workflow

All changes to this repository follow a strict **Feature Branch → Pull Request → Review & Security Scan → Merge to `master`** workflow. Direct pushes to `master` are prohibited for ongoing development. See [`CONTRIBUTING.md`](./CONTRIBUTING.md) for full details.

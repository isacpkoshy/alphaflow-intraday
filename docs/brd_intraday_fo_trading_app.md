# Business Requirements Document (BRD): Automated Intraday Options & Futures Trading Platform ("Project AlphaFlow")

**Document Version:** 1.0  
**Target Asset Classes:** Equity Index & Stock Futures, Weekly/Monthly Index Options  
**Trading Horizon:** Strictly Intraday (0DTE / Intraday Square-Off, Zero Overnight Carry)

---

## 1. Executive Summary & Business Objectives

### 1.1 Purpose
Retail and proprietary traders attempting manual intraday execution on Futures and Options (F&O) face three structural barriers:
1. **Execution Latency & Multi-Leg Slippage**: Simultaneous entry/adjustment of 2–4 option legs and futures hedges cannot be executed manually during volatility spikes without severe price slippage.
2. **Emotional Override**: Traders frequently widen stop-losses on losing short straddles or exit winning futures breakouts prematurely.
3. **Regime Blindness**: Deploying static option-selling systems during high-momentum trend days results in catastrophic drawdowns that wipe out weeks of theta gains.

**Project AlphaFlow** is an automated, low-latency intraday algorithmic trading platform that ingests real-time tick data, classifies the morning market regime, executes the **Regime-Adaptive Intraday Hybrid Engine (RAIHE-F&O)**, manages dynamic Greek/leg adjustments, and enforces hard portfolio-level circuit breakers.

### 1.2 Target Business KPIs (Success Metrics)
| KPI Category | Metric | Target Benchmark |
| :--- | :--- | :--- |
| **Profitability** | Net Annualized Return (after brokerage, STT/CTT, exchange fees, & slippage) | $\ge 45\% - 65\%$ on deployed margin |
| **Risk-Adjusted Return** | Annualized Net Sharpe Ratio / Calmar Ratio | Sharpe $\ge 2.5$ \| Calmar $\ge 5.0$ |
| **Capital Preservation** | Maximum Daily MTM Loss / Max Peak-to-Trough Drawdown | Daily Loss $\le -1.5\%$ \| Max Drawdown $\le -9.0\%$ |
| **Execution Quality** | Tick-to-Order Internal Latency (99th percentile) | $< 50\text{ ms}$ internal processing; $< 150\text{ ms}$ broker round-trip |
| **Operational Reliability** | System Uptime During Market Hours (09:00 – 15:35) | $\ge 99.95\%$ (Zero orphaned open legs at EOD) |

---

## 2. Stakeholder & Persona Analysis

1. **Quantitative Trader / Strategy Owner**: Configures parameter grids, runs walk-forward backtests, reviews daily execution slippage reports, and approves regime thresholds.
2. **Risk Officer / Account Owner**: Monitors real-time Mark-to-Market (MTM) PnL, margin utilization, Net Portfolio Greeks ($\Delta, \Gamma, \Theta, \mathcal{V}$), and controls the **Emergency Panic Kill-Switch**.
3. **DevOps / System Administrator**: Monitors WebSocket feed health, broker API token auto-refresh, order rate-limit compliance, and audit log persistence.

---

## 3. Scope Definition

### 3.1 In-Scope
- **Multi-Broker API Adapter**: Support for Indian F&O brokers (Zerodha Kite Connect, Angel One SmartAPI, DhanHQ, Fyers, Symphony XTS) and/or US F&O brokers (Interactive Brokers TWS/Gateway, Tradier, Alpaca) via a unified interface.
- **Historical & Live Data Engine**: Tick-level WebSocket ingestion, 1-minute/5-minute bar aggregation, real-time Option Chain builder, and Black-Scholes-Merton (BSM) Implied Volatility & Greek calculator.
- **Vectorized + Event-Driven Backtesting Suite**: Combinatorial grid search, transaction cost modeling, and Walk-Forward Optimization (WFO).
- **Live & Paper Execution Engine**: State-machine-driven order lifecycle ( Basket Orders, Iceberg/Slicing for freeze limits, Limit-to-Market fallback).
- **Real-Time Risk Management System (RMS)**: Pre-trade checks, leg-level SL trailing, MTM circuit breakers, and mandatory EOD auto-square-off.
- **Command Center Web Dashboard**: Live PnL, Greek exposure gauges, trade blotter, and manual override controls.

### 3.2 Out-of-Scope (Phase 1)
- Overnight positional holding or multi-day swing trading.
- High-Frequency colocation market-making (sub-microsecond FPGA/C++ co-location).
- Multi-tenant public SaaS billing/subscription management (Phase 1 is single-tenant / prop desk deployment).

---

## 4. Functional Requirements (FR)

### Module A: Market Data & Option Chain Engine
| ID | Requirement Description | Priority | Acceptance Criteria |
| :--- | :--- | :---: | :--- |
| **FR-01** | **Real-Time WebSocket Tick Ingestion**: Ingest Spot Index, Front-Month Futures, and Option Chain ticks ($\pm 10$ strikes from ATM) via binary WebSocket streams. | P0 | Reconnects within $<2\text{s}$ on disconnect; detects stale ticks ($>3\text{s}$ old) and pauses new entries. |
| **FR-02** | **Dynamic ATM & Synthetic Straddle Calculator**: Continuously resolve exact At-The-Money (ATM) strike based on Futures price and compute Combined Premium ($CP_t = CE + PE$) and Straddle-VWAP ($SVWAP_t$). | P0 | $CP_t$ and $SVWAP_t$ update every second with $<5\text{ms}$ compute overhead. |
| **FR-03** | **Real-Time Greeks & IV Engine**: Calculate Implied Volatility (IV) and Greeks ($\Delta, \Gamma, \Theta, \mathcal{V}$) for all active option strikes using vectorized Newton-Raphson BSM on every 1-second snapshot. | P0 | Portfolio net $\Delta$ accurate within $\pm 0.01$ of exchange reference values. |
| **FR-04** | **Morning Regime Telemetry (09:15–09:30)**: Compute 15m ORB High/Low, 15m ADX, Opening Volume Ratio vs. 10-day average, and VIX intraday change at 09:30:00 sharp. | P0 | Emits deterministic `RegimeClassifiedEvent` (`RANGING`, `TRENDING`, or `SHOCK`) within $50\text{ms}$ of the 09:30 candle close. |

### Module B: Backtesting & Permutation Optimization Suite
| ID | Requirement Description | Priority | Acceptance Criteria |
| :--- | :--- | :---: | :--- |
| **FR-05** | **Realistic Friction & Slippage Modeling**: Deduct exact statutory costs (Brokerage, STT/CTT, Exchange Turnover, SEBI/Regulatory fees, Stamp Duty, GST) plus configurable tick slippage ($1-2$ ticks on options, $0.02\%$ on futures). | P0 | Backtest PnL report displays both Gross PnL and Net-of-Friction PnL side by side. |
| **FR-06** | **Combinatorial Permutation & Grid Search**: Run multi-parameter sweeps across ADX cutoffs, ORB windows, SL percentages, Trail-to-Cost flags, and Delta-Hedge thresholds. | P0 | Generates ranked CSV/JSON tearsheets sorted by Sharpe, Calmar, and Profit Factor. |
| **FR-07** | **Walk-Forward Validation (Anti-Overfitting)**: Split historical data into rolling In-Sample (e.g., 6 months optimization) and Out-of-Sample (e.g., 2 months blind test) windows. | P1 | Flags any parameter set whose Out-of-Sample Sharpe drops by $>35\%$ vs. In-Sample. |

### Module C: Strategy Execution & Smart Order Router (SOR)
| ID | Requirement Description | Priority | Acceptance Criteria |
| :--- | :--- | :---: | :--- |
| **FR-08** | **Margin-Optimized Multi-Leg Ordering**: Always execute Long OTM Hedge Wings *before* Short ATM Straddle legs so exchange span margin benefit is granted immediately without peak-margin penalties. | P0 | 100% of hedged option baskets execute BUY legs first, confirmed `COMPLETE`, before firing SELL legs. |
| **FR-09** | **Freeze Quantity Slicing & Iceberg Execution**: Automatically split large F&O orders exceeding exchange freeze limits into compliant child slices. | P0 | Orders exceeding freeze limits are sliced and dispatched in parallel batches within API rate limits. |
| **FR-10** | **Chasing Limit Order with Marketable Fallback**: Place entries as Limit Orders at `Best Ask/Bid + N ticks`. If unfilled after $2\text{ seconds}$, modify price to current book; after $5\text{ seconds}$, convert to Marketable Limit. | P0 | Zero unhedged/partial basket states left hanging for $>5\text{ seconds}$. |
| **FR-11** | **Automated Leg Adjustment (Trail-to-Cost & Futures Delta-Hedge)**: When one short option leg hits its $+20\%$ SL, automatically modify the surviving option leg's SL order to entry price and trigger the Futures Delta-Hedge if ORB breaks. | P0 | SL modification and Futures hedge dispatch occur within $<100\text{ms}$ of leg stop fill confirmation. |
| **FR-12** | **Dual Execution Mode (Live vs. Shadow Paper Trading)**: Allow toggling any strategy instance between `PAPER_SIM` (live ticks, simulated fills with order-book depth check) and `LIVE_BROKER`. | P0 | Switching modes requires zero code changes via UI/config flag. |

### Module D: Risk Management System (Pre-Trade & In-Trade RMS)
| ID | Requirement Description | Priority | Acceptance Criteria |
| :--- | :--- | :---: | :--- |
| **FR-13** | **Hard Daily MTM Loss Circuit Breaker**: Continuously evaluate `Realized PnL + Unrealized MTM`. If net loss breaches `-1.5%` of opening equity, trigger global portfolio flatten and lock trading for the remainder of the day. | P0 | Circuit breaker executes independently of strategy thread; cannot be bypassed by strategy signals. |
| **FR-14** | **Trailing MTM Profit Lock**: Once net intraday MTM crosses `+2.0%` of equity, activate a dynamic floor at `+1.4%` that trails upward as MTM grows. | P1 | Automatically squares off all positions if MTM pulls back to the locked floor. |
| **FR-15** | **Pre-Trade Fat-Finger & Margin Gate**: Reject any order that exceeds maximum single-order notional value, maximum daily trade count, or available free margin buffer ($<15\%$ free cash remaining). | P0 | Rejected orders log a critical alert without crashing the strategy loop. |
| **FR-16** | **Mandatory End-of-Day (EOD) Auto-Square-Off**: At `15:15:00` (configurable), cancel all open pending orders and flatten all short legs first, followed by long hedge legs and futures. | P0 | Account holds exactly `0` open intraday positions by `15:16:00` every trading day. |
| **FR-17** | **Orphaned Leg & Broker Reconciliation Loop**: Poll broker `get_positions()` and `get_orders()` every $10\text{ seconds}$ to reconcile internal state against actual exchange state. | P0 | Any discrepancy triggers an immediate reconciliation alert and auto-hedges or flattens mismatched legs. |

### Module E: Monitoring, Alerting & Audit Compliance
| ID | Requirement Description | Priority | Acceptance Criteria |
| :--- | :--- | :---: | :--- |
| **FR-18** | **Real-Time Web Dashboard & Panic Button**: Display live MTM curve, active legs, Net Portfolio Greeks, regime state, and a 1-click **"PANIC FLATTEN ALL"** button. | P0 | Panic button flattens all positions and disables strategy engine within $<1\text{ second}$. |
| **FR-19** | **Multi-Channel Push Notifications**: Send instant Telegram / Discord / Webhook alerts for morning authentication, regime classification, order fills, SL hits, and RMS triggers. | P1 | Alerts delivered within $<2\text{ seconds}$ of event occurrence. |
| **FR-20** | **Immutable Regulatory Audit Trail**: Log every signal, order payload, broker response, IP address, and RMS check to append-only storage for a minimum of 5 years. | P0 | Full chronological reconstruction of any trading session available for compliance inspection. |

---

## 5. Non-Functional Requirements (NFR)

1. **Latency & Throughput (NFR-01)**:
   - Tick ingestion to indicator update: $< 5\text{ ms}$.
   - Signal generation to broker REST/WebSocket dispatch: $< 25\text{ ms}$.
   - Capability to process $2,000+\text{ ticks/second}$ during market open (09:15 AM) without event-loop backpressure.
2. **Fault Tolerance & Crash Recovery (NFR-02)**:
   - All strategy state (entry prices, active order IDs, regime state, trailing SL watermarks) must be persisted to Redis + PostgreSQL/TimescaleDB on every state transition.
   - If the process crashes and restarts mid-day, it must recover state from Redis/DB + Broker API within $<5\text{ seconds}$ without duplicating orders.
3. **Security & Credential Hygiene (NFR-03)**:
   - Broker API keys, secrets, and TOTP seeds must be encrypted at rest (AES-256 / OS Keyring / Vault) and never committed to source control.
   - Dashboard access protected by JWT authentication and IP allowlisting.
4. **Rate-Limit Compliance (NFR-04)**:
   - Built-in Token Bucket rate limiter strictly enforcing broker order/second limits (e.g., max 10 orders/sec, 200 orders/min) to prevent API ban during volatility spikes.

---

## 6. Regulatory & Exchange Compliance Matrix

- **Automated TOTP / OAuth Session Generation**: Compliant daily pre-market login workflow (08:45 AM) refreshing session tokens before the 09:00 AM pre-open session.
- **Order-to-Trade Ratio (OTR) Governance**: Prevent excessive stop-loss order modifications by enforcing a minimum price change threshold ($>0.25\%$ move) before issuing an `order_modify` API call.
- **Static IP & Algo Registration Readiness**: Architecture supports deployment on a dedicated static IP VPS (AWS Mumbai `ap-south-1` for NSE/BSE or AWS `us-east-1` for CME/CBOE) to satisfy exchange static-IP whitelisting mandates.
- **Prevention of Self-Trade**: Pre-trade check verifies that a new buy/sell order on a strike does not cross an existing resting opposite limit order from the same account.

---

## 7. Risk Register & Mitigation Matrix

| Risk Event | Severity | Likelihood | Automated Mitigation Strategy |
| :--- | :---: | :---: | :--- |
| **Broker API Outage / Order Rejection During Crash** | Critical | Medium | Dual-path execution: Maintain active OTM protective wings at the exchange level + exchange-resident `SL-L` (Stop-Loss Limit) orders so protection remains active even if local server loses internet. |
| **Flash Spike / Illiquid Option Strike Whip** | High | Medium | Liquidity gate refuses entry if bid-ask spread $> 1.5\%$ of option premium; use Limit orders with wide marketable protection band instead of raw Market orders. |
| **WebSocket Feed Freeze (Silent Disconnect)** | High | High | Heartbeat watchdog checks tick timestamps every $1,000\text{ ms}$. If no tick arrives for $3\text{ seconds}$ during market hours, force socket recycling and fallback to REST quote polling. |
| **Clock Drift Between Server & Exchange** | Medium | Low | Enforce NTP (`chrony`) synchronization every 15 minutes; reject startup if system clock drift $> 100\text{ ms}$. |

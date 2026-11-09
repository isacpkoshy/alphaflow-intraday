"""Exact Indian NSE Statutory Charges, STT, GST, Brokerage & Slippage Calculator."""

from typing import Dict


class IndianCostCalculator:
    """Computes exact itemized charges for NSE Intraday Cash (MIS) and NSE Index F&O."""

    @staticmethod
    def calculate_mis_equity_charges(buy_turnover: float, sell_turnover: float, orders_count: int = 2) -> Dict[str, float]:
        """
        NSE Cash Intraday (MIS) Statutory Charges:
        - Brokerage: min(₹20, 0.03% of turnover) per executed order
        - STT: 0.025% on SELL turnover only
        - NSE Exchange Turnover Charge: 0.00297% on total turnover (Buy + Sell)
        - SEBI Turnover Fee: 0.0001% on total turnover
        - Stamp Duty: 0.003% on BUY turnover
        - GST: 18% on (Brokerage + Exchange Charge + SEBI Fee)
        - Slippage (Bid-Ask + Impact): 0.025% per side (0.05% on one-way notional)
        """
        total_turnover = buy_turnover + sell_turnover
        brokerage_buy = min(20.0, buy_turnover * 0.0003)
        brokerage_sell = min(20.0, sell_turnover * 0.0003)
        brokerage = brokerage_buy + brokerage_sell if orders_count == 2 else min(20.0 * orders_count, total_turnover * 0.0003)

        stt = sell_turnover * 0.00025
        exchange_txn = total_turnover * 0.0000297
        sebi_fee = total_turnover * 0.000001
        stamp_duty = buy_turnover * 0.00003
        gst = 0.18 * (brokerage + exchange_txn + sebi_fee)
        slippage = buy_turnover * 0.0005  # 0.05% round-trip slippage

        total_statutory = brokerage + stt + exchange_txn + sebi_fee + stamp_duty + gst
        total_with_slippage = total_statutory + slippage

        return {
            "brokerage": round(brokerage, 2),
            "stt": round(stt, 2),
            "exchange_txn": round(exchange_txn, 2),
            "sebi_fee": round(sebi_fee, 2),
            "stamp_duty": round(stamp_duty, 2),
            "gst": round(gst, 2),
            "slippage": round(slippage, 2),
            "total_statutory": round(total_statutory, 2),
            "total_friction": round(total_with_slippage, 2),
        }

    @staticmethod
    def calculate_fo_options_charges(buy_premium_turnover: float, sell_premium_turnover: float, orders_count: int = 4) -> Dict[str, float]:
        """
        NSE Index Options Intraday Statutory Charges:
        - Brokerage: ₹20 flat per order
        - STT: 0.15% on SELL premium turnover (Revised Union Budget rate)
        - NSE Exchange Turnover Charge (Options): 0.03503% on premium turnover
        - SEBI Turnover Fee: 0.0001% on premium turnover
        - Stamp Duty: 0.003% on BUY premium turnover
        - GST: 18% on (Brokerage + Exchange Charge + SEBI Fee)
        - Slippage: ~0.35% of premium turnover across legs
        """
        total_turnover = buy_premium_turnover + sell_premium_turnover
        brokerage = 20.0 * orders_count
        stt = sell_premium_turnover * 0.0015
        exchange_txn = total_turnover * 0.0003503
        sebi_fee = total_turnover * 0.000001
        stamp_duty = buy_premium_turnover * 0.00003
        gst = 0.18 * (brokerage + exchange_txn + sebi_fee)
        slippage = total_turnover * 0.0035

        total_statutory = brokerage + stt + exchange_txn + sebi_fee + stamp_duty + gst
        total_with_slippage = total_statutory + slippage

        return {
            "brokerage": round(brokerage, 2),
            "stt": round(stt, 2),
            "exchange_txn": round(exchange_txn, 2),
            "sebi_fee": round(sebi_fee, 2),
            "stamp_duty": round(stamp_duty, 2),
            "gst": round(gst, 2),
            "slippage": round(slippage, 2),
            "total_statutory": round(total_statutory, 2),
            "total_friction": round(total_with_slippage, 2),
        }

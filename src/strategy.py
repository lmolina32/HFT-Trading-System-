#!/usr/bin/env python3

import logging

from .order_book import OrderBookManager
from .order_entry import OrderEntryClient
from .safety import PnLTracker, PositionTracker, ExposureTracker, RiskTracker

log: logging.Logger = logging.getLogger("strategy")


def weigthed_mid(bid_prc: float, bid_qty: int, ask_prc: float, ask_qty: int) -> float:
    total = bid_qty + ask_qty
    if total == 0:
        return (bid_prc + ask_prc) / 2.0
    imbalance = bid_qty / total
    return bid_prc * (1.0 - imbalance) + ask_prc * imbalance


class ImbalanceSignal:
    def __init__(self, alpha: float = 1.0) -> None:
        self.alpha = alpha

    def signal(
        self, bid_prc: float, bid_qty: int, ask_prc: float, ask_qty: int
    ) -> float:
        mid = (bid_prc + ask_prc) / 2.0
        return self.alpha * (weigthed_mid(bid_prc, bid_qty, ask_prc, ask_qty) - mid)


class TradeImpactSignal:
    def __init__(self) -> None:
        pass


class FairValueEngine:
    def __init__(self) -> None:
        pass


class RecetTrade: ...


class SymbolState:
    def __init__(self) -> None:
        pass


class OrderStrategy:
    def __init__(self, client: OrderEntryClient, manager: OrderBookManager) -> None:
        self.client = client
        self.manager = manager
        self.enabled = True

    def stop(self) -> None:
        self.enabled = False
        # TODO: get flat
        self.client.cancel_all_orders()

    def on_market_data_update(self) -> None: ...


# mean reversion for ETFs


def microprice_calc(orderbook):
    # mean reversion
    best_bid, bid_qty = orderbook.book.get_best_bid()
    best_ask, ask_qty = orderbook.book.get_best_ask()
    return (best_bid * ask_qty)(best_ask * bid_qty) / (
        bid_qty + ask_qty
    )  # double check this equation. i got it from gemini.


# def main():


# spoofing check


# sending spoofing


# market maker; try to keep internal bookeeping of queues for orders we have placed. if too far back in line, cancel.
# IMPORTANT we dont get spoofed so we dont cancel an order we r in good standing for.
# signals that trigger this are important

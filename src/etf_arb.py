#!/usr/bin/env python3

import time
import logging
import requests

from .order_entry_protocol import Side, OrderReject, ErrorMessage
from .order_book import OrderBookManager
from .order_entry import OrderEntryClient

log = logging.getLogger("etf_arb")

ETF_SYM = 13
UNDERLYING_SYMS = list(range(3, 13))
ARB_ORDER_ID_BASE = 5_000_000


class ETFArbEngine:
    __slots__ = (
        "manager",
        "client",
        "session",
        "base_url",
        "threshold",
        "_cooldown_until",
        "_next_oid",
    )

    def __init__(
        self,
        manager: OrderBookManager,
        client: OrderEntryClient,
        username: str,
        password: str,
        base_url: str = "http://129.74.160.245:5000",
        threshold: int = 100,
    ) -> None:
        self.manager = manager
        self.client = client
        self.session = requests.Session()
        self.session.auth = (username, password)
        self.session.headers.update({"Content-Type": "application/json"})
        self.base_url = base_url
        self.threshold = threshold
        self._cooldown_until: float = 0.0
        self._next_oid: int = ARB_ORDER_ID_BASE

    def step(self) -> None:
        now = time.monotonic()
        if now < self._cooldown_until:
            return

        undy_book = self.manager.books.get(ETF_SYM)
        if undy_book is None:
            return
        undy_bid, _ = undy_book.get_best_bid()
        undy_ask, _ = undy_book.get_best_ask()
        if undy_bid <= 0 or undy_ask <= 0:
            return

        basket_ask, basket_bid = self._basket_prices()
        if basket_ask is None:
            return

        # Create arb: buy basket at ask, create UNDY, sell UNDY at bid
        create_profit = undy_bid - basket_ask
        # Redeem arb: buy UNDY at ask, redeem it, sell basket at bid
        redeem_profit = basket_bid - undy_ask

        if create_profit >= self.threshold:
            log.info(
                "CREATE ARB opportunity: profit=%d UNDY_bid=%d basket_ask=%d",
                create_profit,
                undy_bid,
                basket_ask,
            )
            self._execute_create_arb(undy_bid)
        elif redeem_profit >= self.threshold:
            log.info(
                "REDEEM ARB opportunity: profit=%d basket_bid=%d UNDY_ask=%d",
                redeem_profit,
                basket_bid,
                undy_ask,
            )
            self._execute_redeem_arb(undy_ask)

    def _execute_create_arb(self, undy_bid: int) -> None:
        """Buy 1 of each underlying (IOC), create 1 UNDY, sell 1 UNDY (IOC)."""
        filled: list[int] = []

        for sym in UNDERLYING_SYMS:
            book = self.manager.books.get(sym)
            if book is None:
                break
            ask, _ = book.get_best_ask()
            if ask <= 0:
                break
            oid = self._alloc_oid()
            resp = self.client.immediate_or_cancel(oid, sym, Side.BUY, 1, ask)
            if resp and not self._is_reject(resp[0]):
                filled.append(sym)
            else:
                log.warning("CREATE ARB: IOC buy failed sym=%d — aborting", sym)
                break

        if len(filled) == len(UNDERLYING_SYMS):
            try:
                r = self.session.post(
                    f"{self.base_url}/create",
                    json={"amount": 1},
                    timeout=1.0,
                )
                data = r.json()
                if r.status_code == 200 and data.get("success"):
                    # ETF service consumed underlying positions — adjust our tracker
                    for sym in UNDERLYING_SYMS:
                        self.client.position_tracker.update_position(sym, 0, 1)
                    self.client.position_tracker.update_position(ETF_SYM, 1, 0)

                    # Sell the freshly created UNDY
                    oid = self._alloc_oid()
                    self.client.immediate_or_cancel(
                        oid, ETF_SYM, Side.SELL, 1, undy_bid
                    )
                    log.info(
                        "CREATE ARB complete. UNDY balance: %s",
                        data.get("undy_balance"),
                    )
                else:
                    log.error("CREATE failed: %s", data.get("message"))
                    self._unwind(filled, Side.SELL)
            except requests.RequestException as exc:
                log.error("CREATE REST error: %s", exc)
                self._unwind(filled, Side.SELL)
        else:
            # Partial — unwind what we bought
            log.warning(
                "CREATE ARB partial (%d/%d) — unwinding",
                len(filled),
                len(UNDERLYING_SYMS),
            )
            self._unwind(filled, Side.SELL)

        self._cooldown_until = time.monotonic() + 2.0

    def _execute_redeem_arb(self, undy_ask: int) -> None:
        """Buy 1 UNDY (IOC), redeem it, sell 1 of each underlying (IOC)."""
        oid = self._alloc_oid()
        resp = self.client.immediate_or_cancel(oid, ETF_SYM, Side.BUY, 1, undy_ask)
        if not resp or self._is_reject(resp[0]):
            log.warning("REDEEM ARB: IOC buy UNDY failed")
            self._cooldown_until = time.monotonic() + 1.0
            return

        try:
            r = self.session.post(
                f"{self.base_url}/redeem",
                json={"amount": 1},
                timeout=1.0,
            )
            data = r.json()
            if r.status_code == 200 and data.get("success"):
                # ETF service gave us underlyings — adjust tracker
                self.client.position_tracker.update_position(ETF_SYM, 0, 1)
                for sym in UNDERLYING_SYMS:
                    self.client.position_tracker.update_position(sym, 1, 0)

                # Sell all 10 underlyings
                sold: list[int] = []
                for sym in UNDERLYING_SYMS:
                    book = self.manager.books.get(sym)
                    if book is None:
                        continue
                    bid, _ = book.get_best_bid()
                    if bid <= 0:
                        continue
                    oid = self._alloc_oid()
                    resp2 = self.client.immediate_or_cancel(oid, sym, Side.SELL, 1, bid)
                    if resp2 and not self._is_reject(resp2[0]):
                        sold.append(sym)
                    else:
                        log.warning("REDEEM ARB: IOC sell failed sym=%d", sym)
                log.info(
                    "REDEEM ARB complete: sold %d/%d underlyings",
                    len(sold),
                    len(UNDERLYING_SYMS),
                )
            else:
                log.error("REDEEM failed: %s", data.get("message"))
        except requests.RequestException as exc:
            log.error("REDEEM REST error: %s", exc)

        self._cooldown_until = time.monotonic() + 2.0

    def _basket_prices(self) -> tuple:
        """Return (best_ask_sum, best_bid_sum) for all underlyings, or (None, None)."""
        ask_sum = 0
        bid_sum = 0
        for sym in UNDERLYING_SYMS:
            book = self.manager.books.get(sym)
            if book is None:
                return None, None
            bid, _ = book.get_best_bid()
            ask, _ = book.get_best_ask()
            if bid <= 0 or ask <= 0:
                return None, None
            bid_sum += bid
            ask_sum += ask
        return ask_sum, bid_sum

    def _unwind(self, syms: list, side: int) -> None:
        """IOC unwind positions for a list of symbols."""
        for sym in syms:
            book = self.manager.books.get(sym)
            if book is None:
                continue
            if side == Side.SELL:
                price, _ = book.get_best_bid()
            else:
                price, _ = book.get_best_ask()
            if price <= 0:
                continue
            oid = self._alloc_oid()
            self.client.immediate_or_cancel(oid, sym, side, 1, price)

    def _alloc_oid(self) -> int:
        oid = self._next_oid
        self._next_oid += 1
        return oid

    @staticmethod
    def _is_reject(resp: object) -> bool:
        return isinstance(resp, (OrderReject, ErrorMessage))

#!/usr/bin/env python3

"""
flatten.py — clear all open positions recorded in team2_state.json.

Usage:
    python3 -m src.flatten [--state-path PATH]

Logs in, loads positions and open-orders from the state file, cancels any
leftover open orders, then sends marketable IOC orders to close every
non-zero position. No market-data subscription needed: SELLs go out at a
very low (still tick-aligned) price, BUYs at a very high one, so any
liquidity on the opposite side fills them. Saves the cleared state on exit.
"""

from __future__ import annotations

import logging
import sys
import time

from .order_book import OrderBookManager
from .order_entry import OrderEntryClient
from .order_entry_protocol import Side
from .state import StateStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("flatten")

MARKETABLE_SELL_PRICE = 10
MARKETABLE_BUY_PRICE = 1_000_000_000

SETTLE_PAUSE_S = 0.2

MAX_PASSES = 3


def _flatten_once(client: OrderEntryClient, oid_start: int) -> int:
    """One pass: send a marketable IOC for every non-zero position. Returns next oid."""
    oid = oid_start
    snapshot = dict(client.position_tracker.symbol_position)
    for sym, pos in snapshot.items():
        if pos == 0:
            continue
        if pos > 0:
            log.info(
                "flatten SELL sym=%d qty=%d @ %d (IOC)", sym, pos, MARKETABLE_SELL_PRICE
            )
            try:
                client.immediate_or_cancel(
                    oid, sym, Side.SELL, pos, MARKETABLE_SELL_PRICE
                )
            except Exception as exc:
                log.error("flatten SELL failed sym=%d: %s", sym, exc)
        else:
            qty = abs(pos)
            log.info(
                "flatten BUY sym=%d qty=%d @ %d (IOC)", sym, qty, MARKETABLE_BUY_PRICE
            )
            try:
                client.immediate_or_cancel(
                    oid, sym, Side.BUY, qty, MARKETABLE_BUY_PRICE
                )
            except Exception as exc:
                log.error("flatten BUY failed sym=%d: %s", sym, exc)
        oid += 1
    return oid


def _parse_args(argv: list[str]) -> str:
    state_path = "team2_state.json"
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--state-path" and i + 1 < len(argv):
            state_path = argv[i + 1]
            i += 2
            continue
        if a in ("-h", "--help"):
            print("Usage: python3 -m src.flatten [--state-path PATH]")
            sys.exit(0)
        print(f"unknown arg: {a}")
        sys.exit(1)
    return state_path


def main() -> None:
    state_path = _parse_args(sys.argv[1:])

    state_store = StateStore(state_path)
    manager = OrderBookManager()
    client = OrderEntryClient(order_manager=manager, state_store=state_store)
    client.login()

    n_pos, n_ord = client.load_state()
    log.info(
        "loaded from %s: open_positions=%d open_orders=%d",
        state_path,
        n_pos,
        n_ord,
    )

    if n_ord:
        log.info("cancelling %d leftover open order(s) before flatten", n_ord)
        try:
            client.cancel_all_orders()
        except Exception as exc:
            log.error("cancel_all_orders failed: %s", exc)

    if n_pos == 0:
        log.info("no open positions in %s — nothing to flatten", state_path)
        client.shutdown()
        return

    log.info("flattening %d position(s) via marketable IOC...", n_pos)
    oid = 14_000_000
    for pass_idx in range(MAX_PASSES):
        oid = _flatten_once(client, oid)
        time.sleep(SETTLE_PAUSE_S)
        remaining = {
            sym: pos
            for sym, pos in client.position_tracker.symbol_position.items()
            if pos != 0
        }
        if not remaining:
            log.info("flatten: all positions cleared after %d pass(es)", pass_idx + 1)
            break
        log.warning(
            "flatten: residual after pass %d: %s — retrying", pass_idx + 1, remaining
        )
    else:
        residual = {
            sym: pos
            for sym, pos in client.position_tracker.symbol_position.items()
            if pos != 0
        }
        log.error(
            "flatten: GAVE UP after %d passes; residual: %s", MAX_PASSES, residual
        )

    client.shutdown()


if __name__ == "__main__":
    main()

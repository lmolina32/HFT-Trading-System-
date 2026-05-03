#!/usr/bin/env python3

"""
state.py: Persist per-symbol position and realized cash to disk.

Without this, the trading system starts every session assuming it is flat,
even when a prior crash left real inventory on the exchange. The store is
written atomically (tmp + rename) so a crash mid-write cannot corrupt it.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Dict, Tuple

log = logging.getLogger("state")


class StateStore:
    __slots__ = ("path",)

    def __init__(self, path: str) -> None:
        self.path = path

    def save(
        self,
        positions: Dict[int, int],
        cash: Dict[int, float],
        open_orders: Dict[int, Tuple[int, int, int, int, int]],
    ) -> None:
        """Write state atomically. Errors are logged, not raised — persistence
        failure must not kill a running trader.

        open_orders is the order_id → (symbol, side, qty, price, filled) map.
        We persist it so that after a crash/restart, any FILLs the exchange
        echoes for orders we placed before the crash can still be attributed
        to the correct symbol/side — OrderFill carries only the order_id.
        """
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(
                    {
                        "positions": {str(k): v for k, v in positions.items()},
                        "cash": {str(k): v for k, v in cash.items()},
                        "open_orders": {
                            str(oid): list(cfg) for oid, cfg in open_orders.items()
                        },
                    },
                    f,
                )
            os.replace(tmp, self.path)
        except OSError as exc:
            log.error("StateStore.save failed (%s): %s", self.path, exc)

    def load(
        self,
    ) -> Tuple[
        Dict[int, int], Dict[int, float], Dict[int, Tuple[int, int, int, int, int]]
    ]:
        """Return (positions, cash, open_orders). Empty if file missing or unreadable."""
        try:
            with open(self.path) as f:
                data = json.load(f)
        except FileNotFoundError:
            log.info("StateStore.load: %s missing — starting fresh", self.path)
            return {}, {}, {}
        except (OSError, json.JSONDecodeError) as exc:
            log.error(
                "StateStore.load failed (%s): %s — starting fresh", self.path, exc
            )
            return {}, {}, {}
        try:
            positions = {
                int(k): int(v)
                for k, v in data.get("positions", {}).items()
                if int(k) >= 1
            }
            cash = {
                int(k): float(v) for k, v in data.get("cash", {}).items() if int(k) >= 1
            }
            dropped_cash = [k for k in data.get("cash", {}) if int(k) < 1]
            if dropped_cash:
                log.warning(
                    "StateStore.load: dropped orphan cash keys %s (legacy bug)",
                    dropped_cash,
                )
            open_orders: Dict[int, Tuple[int, int, int, int, int]] = {}
            for k, v in data.get("open_orders", {}).items():
                if not isinstance(v, list) or len(v) != 5:
                    continue
                open_orders[int(k)] = tuple(int(x) for x in v)  # type: ignore[assignment]
        except (TypeError, ValueError) as exc:
            log.error(
                "StateStore.load: corrupt %s: %s — starting fresh", self.path, exc
            )
            return {}, {}, {}
        return positions, cash, open_orders

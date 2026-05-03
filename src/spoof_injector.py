#!/usr/bin/env python3
"""
SpoofInjector: integrated multicast TradeSummary spoofer.

Lives in the trader's process. tick() is called once per poll cycle from
run_market_data; observe() is called once per parsed live message. A burst
fires 5-7 spoofs spread across many poll iterations (200us-2ms between
spoofs) so it looks like a real cluster of trades and never blocks the
trading hot path for more than one sendto() call at a time.

TX socket has IP_MULTICAST_LOOP=0 — this trader never receives its own
packets, so the local seq_tracker, book, and strategy are unaffected.
"""

from __future__ import annotations

import logging
import random
import socket
import struct
import time
from typing import Dict, Optional

from .market_data_struct import MAGIC_NUMBER, MSG_TYPE, TradeSummary

LIVE_MCAST_ADDR = "239.0.0.1"
MCAST_PORT = 12345

MD_HEADER_FORMAT = "<QHIQB"
MD_HEADER_SIZE = struct.calcsize(MD_HEADER_FORMAT)
TS_BODY_FORMAT = "<IBIi"
TS_BODY_SIZE = struct.calcsize(TS_BODY_FORMAT)
TS_TOTAL_SIZE = MD_HEADER_SIZE + TS_BODY_SIZE

SIDE_BUY = 1
SIDE_SELL = 2

SYMBOL_TICKS: dict[int, int] = {
    1: 10, 2: 5, 3: 5, 4: 5, 5: 5, 6: 5, 7: 5,
    8: 5, 9: 5, 10: 5, 11: 5, 12: 5, 13: 10,
}

log = logging.getLogger("spoof_injector")


class _Burst:
    __slots__ = ("symbol", "aggressor_side", "remaining", "next_send_at")

    def __init__(
        self,
        symbol: int,
        aggressor_side: int,
        remaining: int,
        next_send_at: float,
    ) -> None:
        self.symbol = symbol
        self.aggressor_side = aggressor_side
        self.remaining = remaining
        self.next_send_at = next_send_at


class SpoofInjector:
    __slots__ = (
        "tx_sock",
        "enabled",
        "warmup_until",
        "next_burst_at",
        "active_burst",
        "last_price",
        "last_spoofed_seq",
        "min_interval",
        "max_interval",
        "target_symbols",
        "min_gap_us",
        "max_gap_us",
    )

    def __init__(
        self,
        local_ip: str,
        enabled: bool = True,
        min_interval_s: float = 60.0,
        max_interval_s: float = 120.0,
        warmup_s: float = 30.0,
        target_symbols: tuple[int, ...] = (1, 2, 13),
        min_gap_us: float = 200.0,
        max_gap_us: float = 2000.0,
    ) -> None:
        self.enabled = enabled
        self.min_interval = min_interval_s
        self.max_interval = max_interval_s
        self.target_symbols = target_symbols
        self.min_gap_us = min_gap_us
        self.max_gap_us = max_gap_us
        self.last_price: Dict[int, int] = {}
        self.last_spoofed_seq: int = 0
        self.active_burst: Optional[_Burst] = None
        now = time.monotonic()
        self.warmup_until: float = now + warmup_s
        self.next_burst_at: float = (
            now + warmup_s + random.uniform(min_interval_s, max_interval_s)
        )
        self.tx_sock = self._make_tx_socket(local_ip)
        log.info(
            "SpoofInjector ready warmup=%.0fs first_burst_in=%.0fs",
            warmup_s,
            self.next_burst_at - now,
        )

    @staticmethod
    def _make_tx_socket(local_ip: str) -> socket.socket:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        s.setsockopt(
            socket.IPPROTO_IP,
            socket.IP_MULTICAST_IF,
            socket.inet_aton(local_ip),
        )
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 0)
        s.setblocking(False)
        return s

    def observe(self, msg: object) -> None:
        if isinstance(msg, TradeSummary) and msg.last_price > 0:
            self.last_price[msg.symbol] = msg.last_price

    def tick(self, expected_seq: int) -> None:
        if not self.enabled:
            return
        now = time.monotonic()
        if now < self.warmup_until:
            return

        burst = self.active_burst
        if burst is not None:
            if now >= burst.next_send_at:
                self._fire_one(expected_seq, now)
            return

        if now >= self.next_burst_at:
            self._start_burst(now)

    def _start_burst(self, now: float) -> None:
        known = [s for s in self.target_symbols if s in self.last_price]
        if not known:
            self.next_burst_at = now + 30.0
            return
        sym = random.choice(known)
        agg = random.choice([SIDE_BUY, SIDE_SELL])
        n = 10
        self.active_burst = _Burst(
            symbol=sym, aggressor_side=agg, remaining=n, next_send_at=now
        )
        log.info(
            "SPOOF BURST start sym=%d agg=%s n=%d ref_px=%d",
            sym,
            "BUY" if agg == SIDE_BUY else "SELL",
            n,
            self.last_price[sym],
        )

    def _fire_one(self, expected_seq: int, now: float) -> None:
        burst = self.active_burst
        if burst is None:
            return
        ref_price = self.last_price.get(burst.symbol)
        if ref_price is None or ref_price <= 0:
            self.active_burst = None
            self._reschedule(now)
            return

        tick_size = SYMBOL_TICKS.get(burst.symbol, 5)
        jitter = random.randint(-2, 2) * tick_size
        price = max(tick_size, ref_price + jitter)
        qty = random.randint(2, 6)
        seq = max(expected_seq, self.last_spoofed_seq + 1)

        packet = self._build_trade_summary(
            seq_num=seq,
            symbol=burst.symbol,
            aggressor_side=burst.aggressor_side,
            quantity=qty,
            last_price=price,
        )
        try:
            self.tx_sock.sendto(packet, (LIVE_MCAST_ADDR, MCAST_PORT))
            self.last_spoofed_seq = seq
        except BlockingIOError:
            pass

        burst.remaining -= 1
        if burst.remaining <= 0:
            self.active_burst = None
            self._reschedule(now)
        else:
            burst.next_send_at = now + 0.3

    def _reschedule(self, now: float) -> None:
        self.next_burst_at = now + 30.0
        log.info("SPOOF BURST end, next in %.1fs", self.next_burst_at - now)

    @staticmethod
    def _build_trade_summary(
        seq_num: int,
        symbol: int,
        aggressor_side: int,
        quantity: int,
        last_price: int,
    ) -> bytes:
        header = struct.pack(
            MD_HEADER_FORMAT,
            MAGIC_NUMBER,
            TS_TOTAL_SIZE,
            seq_num,
            time.time_ns(),
            int(MSG_TYPE.TRADE_SUMMARY),
        )
        body = struct.pack(
            TS_BODY_FORMAT, symbol, aggressor_side, quantity, last_price
        )
        return header + body

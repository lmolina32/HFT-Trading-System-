#!/usr/bin/env python3

from __future__ import annotations

import sys
import select
import logging
import threading

from .multicast import create_multicast_socket
from .order_book import (
    OrderBookManager,
    SnapShotSynchronizer,
    SequenceTracker,
    dispatch_live_message,
)
from .order_entry import OrderEntryClient
from .order_entry_protocol import Side
from .market_data_struct import MDHeader, MAGIC_NUMBER, TradeSummary
from .parser import parse_message
from .strategy import OrderStrategy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        # logging.FileHandler("trade_engine.log"),
    ],
)
log = logging.getLogger("main")

LIVE_MCAST_ADDR = "239.0.0.1"
SNAP_MCAST_ADDR = "239.0.0.2"
MCAST_PORT = 12345
MAX_UDP_PAYLOAD = 1500


def _process_buffer(
    buf: bytearray,
    buf_len: int,
    manager: OrderBookManager,
    seq_tracker: SequenceTracker,
    synchronizer: SnapShotSynchronizer,
    strategy: OrderStrategy,
) -> int:
    """Returns number of unconsumed bytes remaining in buf."""
    mv = memoryview(buf)
    pos = 0

    while buf_len - pos >= MDHeader.STRUCT_SIZE:
        # Zero-copy: header view directly into the bytearray
        header = MDHeader(mv[pos : pos + MDHeader.STRUCT_SIZE])

        if buf_len - pos < header.length:
            break  # incomplete packet — wait for more data

        # Zero-copy: full packet view, no bytes() copy
        packet_mv = mv[pos : pos + header.length]
        pos += header.length

        if header.magic_number == MAGIC_NUMBER:
            if not synchronizer.sync:
                synchronizer.buffer_live_message(header, parse_message(packet_mv))
            else:
                seq_tracker.check(header.seq_num)
                msg = parse_message(packet_mv)
                dispatch_live_message(header, msg, manager)
                if strategy is not None:
                    # Feed trade summaries for signal detection
                    if isinstance(msg, TradeSummary):
                        strategy.on_trade_summary(
                            msg.symbol,
                            msg.aggressor_side,
                            msg.total_quantity,
                            msg.last_price,
                            header.timestamp,
                        )
                    # Let strategy re-evaluate quotes
                    strategy.on_market_data_update()

                if header.seq_num % 10_000 == 0:
                    for sym, book in sorted(manager.books.items()):
                        bb = book.get_best_bid()
                        ba = book.get_best_ask()
                        log.info(
                            f"seq={header.seq_num} sym={sym}: "
                            f"BID={bb[1] if bb else '-'}@{bb[0] if bb else '-'} | "
                            f"ASK={ba[1] if ba else '-'}@{ba[0] if ba else '-'} "
                            f"volume={book.total_volume}"
                        )
        else:
            if not synchronizer.sync:
                synchronizer.handle_snapshot_message(header, parse_message(packet_mv))
                if synchronizer.snap_complete:
                    log.info("Snapshot complete for all symbols\n\n")
                    synchronizer.replay_buffered_messages()
                    for sym, book in sorted(manager.books.items()):
                        log.info(f" {book}")

    # Compact: slide unconsumed tail to front (single C-level memmove)
    remaining = buf_len - pos
    if remaining and pos:
        buf[:remaining] = mv[pos : pos + remaining]

    return remaining


def run_market_data(
    local_ip: str,
    manager: OrderBookManager,
    seq_tracker: SequenceTracker,
    synchronizer: SnapShotSynchronizer,
    client: OrderEntryClient,
    strategy: OrderStrategy,
) -> None:
    live_sock = create_multicast_socket(LIVE_MCAST_ADDR, MCAST_PORT, local_ip)
    snap_sock = create_multicast_socket(SNAP_MCAST_ADDR, MCAST_PORT, local_ip)

    sockets = [live_sock, snap_sock]
    fd_to_sock = {s.fileno(): s for s in sockets}

    # Pre-allocate once — no per-packet heap allocation
    live_buf = bytearray(1 << 16)
    snap_buf = bytearray(1 << 16)
    live_mv = memoryview(live_buf)
    snap_mv = memoryview(snap_buf)
    live_len = 0
    snap_len = 0

    try:
        poller: select.epoll = select.epoll()
        use_epoll = True
        for sock in sockets:
            poller.register(sock.fileno(), select.EPOLLIN)
    except AttributeError:
        poller = None
        use_epoll = False

    log.info("=" * 60)
    log.info("NDFEX Market Data Feed Handler started")
    log.info(f"LIVE channel:     {LIVE_MCAST_ADDR}:{MCAST_PORT}")
    log.info(f"SNAPSHOT channel: {SNAP_MCAST_ADDR}:{MCAST_PORT}")
    log.info("=" * 60)

    try:
        if use_epoll:
            assert poller is not None
            while True:
                events = poller.poll(timeout=0.0)
                for fd, event in events:
                    if not (event & select.EPOLLIN):
                        continue
                    sock = fd_to_sock.get(fd)
                    if sock is None:
                        continue
                    try:
                        if fd == live_sock.fileno():
                            # Write directly into the buffer — no intermediate bytes object
                            n = sock.recv_into(live_mv[live_len:], MAX_UDP_PAYLOAD)
                            live_len += n
                            live_len = _process_buffer(
                                live_buf,
                                live_len,
                                manager,
                                seq_tracker,
                                synchronizer,
                                strategy,
                            )

                        elif fd == snap_sock.fileno():
                            if not synchronizer.sync:
                                n = sock.recv_into(snap_mv[snap_len:], MAX_UDP_PAYLOAD)
                                snap_len += n
                                snap_len = _process_buffer(
                                    snap_buf,
                                    snap_len,
                                    manager,
                                    seq_tracker,
                                    synchronizer,
                                    strategy,
                                )
                            else:
                                # Drain kernel buffer so it doesn't overflow, discard payload
                                sock.recv(MAX_UDP_PAYLOAD)
                                snap_len = 0

                    except BlockingIOError:
                        pass
        else:
            # select() fallback — same buffer logic, just different polling
            data_buf = bytearray(1 << 16)
            data_mv = memoryview(data_buf)
            data_len = 0
            while True:
                readable, _, _ = select.select(sockets, [], [], 0)
                for sock in readable:
                    try:
                        n = sock.recv_into(data_mv[data_len:], MAX_UDP_PAYLOAD)
                        data_len += n
                        data_len = _process_buffer(
                            data_buf,
                            data_len,
                            manager,
                            seq_tracker,
                            synchronizer,
                            strategy,
                        )
                    except BlockingIOError:
                        pass

    except KeyboardInterrupt:
        log.info("\nShutting down")
    finally:
        if poller is not None:
            poller.close()
        live_sock.close()
        snap_sock.close()


def run_order_entry_cli(client: OrderEntryClient) -> None:
    """Interactive CLI for manual order entry.

    Commands:
        buy  <oid> <sym> <qty> <price>
        sell <oid> <sym> <qty> <price>
        del  <oid>
        mod  <oid> <side> <qty> <price>
        ioc  <oid> <sym> <side> <qty> <price>
        pnl  <sym>
        pos  <sym>
        all
        cancel
        quit
    """
    client.login()

    while True:
        try:
            line = input("> ").strip()
        except EOFError:
            break
        if not line:
            continue

        parts = line.split()
        cmd = parts[0].lower()

        try:
            if cmd == "buy":
                _, oid, sym, qty, price = parts
                client.new_order(int(oid), int(sym), Side.BUY, int(qty), int(price))
            elif cmd == "sell":
                _, oid, sym, qty, price = parts
                client.new_order(int(oid), int(sym), Side.SELL, int(qty), int(price))
            elif cmd == "del":
                _, oid = parts
                client.delete_order(int(oid))
            elif cmd == "mod":
                _, oid, side, qty, price = parts
                s = Side.BUY if side.lower() == "buy" else Side.SELL
                client.modify_order(int(oid), s, int(qty), int(price))
            elif cmd == "ioc":
                _, oid, sym, side, qty, price = parts
                s = Side.BUY if side.lower() == "buy" else Side.SELL
                client.immediate_or_cancel(int(oid), int(sym), s, int(qty), int(price))
            elif cmd == "pnl":
                _, sym = parts
                print(f"PnL for sym={sym}: {client.get_pnl(int(sym)):.2f}")
            elif cmd == "pos":
                _, sym = parts
                print(
                    f"Position for sym={sym}: {client.position_tracker.get_position(int(sym))}"
                )
            elif cmd == "cancel":
                client.cancel_all_orders()
            elif cmd == "all":
                print(client.open_orders)
            elif cmd == "quit":
                break
            else:
                print(f"unknown command: {cmd}")
        except (ValueError, TypeError) as e:
            print(f"bad input: {e}")

    client.shutdown()


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <local_ip>")
        sys.exit(1)
    manager: OrderBookManager = OrderBookManager()
    seq_tracker: SequenceTracker = SequenceTracker()
    synchronizer: SnapShotSynchronizer = SnapShotSynchronizer(manager, seq_tracker)

    local_ip: str = sys.argv[1]
    client = OrderEntryClient(order_manager=manager)
    client.login()
    strategy: OrderStrategy = OrderStrategy(client, manager)
    try:
        run_market_data(local_ip, manager, seq_tracker, synchronizer, client, strategy)
    finally:
        log.error("\n\nShutting down all orders")
        strategy.stop()
        client.shutdown()


if __name__ == "__main__":
    main()

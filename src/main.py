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
from .market_data_struct import MDHeader, MAGIC_NUMBER
from .parser import parse_message

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("trade_engine.log"),
    ],
)
log = logging.getLogger("main")

LIVE_MCAST_ADDR = "239.0.0.1"
SNAP_MCAST_ADDR = "239.0.0.2"
MCAST_PORT = 12345
MAX_UDP_PAYLOAD = 1500


def _process_buffer(
    data_buffer: bytes,
    manager: OrderBookManager,
    seq_tracker: SequenceTracker,
    synchronizer: SnapShotSynchronizer,
) -> bytes:
    while len(data_buffer) >= MDHeader.STRUCT_SIZE:
        header = MDHeader(data_buffer[: MDHeader.STRUCT_SIZE])
        if len(data_buffer) < header.length:
            break
        packet = data_buffer[: header.length]
        data_buffer = data_buffer[header.length :]
        if header.magic_number == MAGIC_NUMBER:
            if not synchronizer.sync:
                synchronizer.buffer_live_message(header, parse_message(packet))
            else:
                seq_tracker.check(header.seq_num)
                dispatch_live_message(
                    header,
                    parse_message(packet),
                    manager,
                )
                if header.seq_num % 1000 == 0:
                    for sym, book in sorted(manager.books.items()):
                        bb = book.get_best_bid()
                        ba = book.get_best_ask()
                        log.info(
                            f"seq={header.seq_num} sym={sym}: "
                            f"BID={bb[1] if bb else '-'}@"
                            f"{bb[0] if bb else '-'} | "
                            f"ASK={ba[1] if ba else '-'}@"
                            f"{ba[0] if ba else '-'} "
                            f"volume={book.total_volume}"
                        )

        else:
            if not synchronizer.sync:
                synchronizer.handle_snapshot_message(header, parse_message(packet))
                if synchronizer.snap_complete:
                    log.info("Snapshot complete for all symbols\n\n")
                    synchronizer.replay_buffered_messages()
                    for sym, book in sorted(manager.books.items()):
                        log.info(f" {book}")
    return data_buffer


def run_market_data(
    local_ip: str,
    manager: OrderBookManager,
    seq_tracker: SequenceTracker,
    synchronizer: SnapShotSynchronizer,
) -> None:

    # Create multicast sockets
    live_sock = create_multicast_socket(LIVE_MCAST_ADDR, MCAST_PORT, local_ip)
    snap_sock = create_multicast_socket(SNAP_MCAST_ADDR, MCAST_PORT, local_ip)

    sockets = [live_sock, snap_sock]
    fd_to_sock = {s.fileno(): s for s in sockets}

    data_buffer: bytes = b""

    # create epoll
    try:
        poller: select.epoll = select.epoll()
        use_poll: bool = True
        for sock in sockets:
            poller.register(sock.fileno(), select.EPOLLIN)
    except AttributeError:
        poller = None
        use_poll = False
        log.info("epoll not available, using select()")

    log.info("=" * 60)
    log.info("NDFEX Market Data Feed Handler started")
    log.info(f"LIVE channel:     {LIVE_MCAST_ADDR}:{MCAST_PORT}")
    log.info(f"SNAPSHOT channel: {SNAP_MCAST_ADDR}:{MCAST_PORT}")
    log.info("=" * 60)
    data_buffer: bytes = b""

    try:
        if use_poll:
            assert poller is not None
            while True:
                events = poller.poll(timeout=0.0)
                for fd, event in events:
                    if event & select.EPOLLIN:
                        sock = fd_to_sock.get(fd)
                        if sock is None:
                            continue
                        try:
                            data = sock.recv(MAX_UDP_PAYLOAD)
                            if data:
                                clean_data = "".join(f"{b:02x}" for b in data).rstrip()
                                data_buffer += bytes.fromhex(clean_data)
                                data_buffer = _process_buffer(
                                    data_buffer, manager, seq_tracker, synchronizer
                                )
                        except BlockingIOError:
                            pass  # No data available
                        break
                # this is where we call trading strat
                    
                    
            # this while loop updates the order book with the current market data being read in from the live and snapshot channels. 
            # TODO: should we strategy be called here, idea is that we update on current market data being read in from epoll. Then once we have an updated order book from the live channel at that instance, we can perform trades. Only downside, since we are using python this will probably be slow and new orders (buy/sell/modifies etc.) are being sent by exchange so we do not have the most up to date view of the market data. But based on the structure of our code (market data on background, order_entry on main thread)  I think it makes the most logical sense to place it here (to sync). I don't want to run it with threads (reader-writer lock) because then we have to deal explicitly with the OS with locks. Given that we are using python we are still probably using a lot of sys calls but I would try to avoid more. We can also try to do single producer single consumer model where we push on the market data into a buffer (queue) and then the consumer is polling on the queue to see new market data, if not polling performing startegy + risk checking. But this is also similar to the model we have right now so I don't know what else to do. We do need to run this as a daemon on the background and have the main thread taking in user input. The main thread is our last line of defense if something happens, if we see our system going crazy we can send a delete all orders + quit to log us out and shut everything off. But in theory, everything will be happening in the background thread (updating orderbook + order entries (strategy) + risk checking). 
        else: # should we just shut down here instead?
            while True:
                readable, _, _ = select.select(sockets, [], [], 0)
                for sock in readable:
                    try:
                        data = sock.recv(MAX_UDP_PAYLOAD)
                        if data:
                            clean_data = "".join(f"{b:02x}" for b in data).rstrip()
                            data_buffer += bytes.fromhex(clean_data)
                            data_buffer = _process_buffer(
                                data_buffer, manager, seq_tracker, synchronizer
                            )
                    except BlockingIOError:
                        pass  # No data available
                        
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
    md_thread = threading.Thread(
        target=run_market_data,
        args=(local_ip, manager, seq_tracker, synchronizer),
        daemon=True,
    )

    md_thread.start()

    client = OrderEntryClient(order_manager=manager)
    try:
        run_order_entry_cli(client)
    except SystemExit as e:
        log.error("Emergency shutdown: %s", e)
    finally:
        log.error("\n\nShutting down all orders")
        client.shutdown()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3

import sys
import select
import logging
from parser import parse_message
from multicast import create_multicast_socket
from order_book import (
    OrderBookManager,
    SnapShotSynchronizer,
    SequenceTracker,
    parse_live_message,
    trade_body,
)
from market_data_struct import MDHeader, MAGIC_NUMBER

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")

LIVE_MCAST_ADDR = "239.0.0.1"
SNAP_MCAST_ADDR = "239.0.0.2"
MCAST_PORT = 12345
MAX_UDP_PAYLOAD = 1500


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <local_ip>")
        sys.exit(1)

    local_ip = sys.argv[1]

    # Create multicast sockets
    live_sock = create_multicast_socket(LIVE_MCAST_ADDR, MCAST_PORT, local_ip)
    snap_sock = create_multicast_socket(SNAP_MCAST_ADDR, MCAST_PORT, local_ip)

    sockets = [live_sock, snap_sock]

    manager: OrderBookManager = OrderBookManager()
    seq_tracker: SequenceTracker = SequenceTracker()
    synchronizer: SnapShotSynchronizer = SnapShotSynchronizer(manager, seq_tracker)
    # buf: bytearray = bytearray(MAX_UDP_PAYLOAD)
    # view = memoryview(buf)
    data_buffer: bytes = b""

    # create epoll
    try:
        poller: select.epoll = select.epoll()
        use_poll: bool = True
        for sock in sockets:
            poller.register(sock.fileno(), select.EPOLLIN)
    except AttributeError:
        use_poll = False
        log.info("epoll not available, using select()")

    log.info("=" * 60)
    log.info("NDFEX Market Data Feed Handler started")
    log.info(f"LIVE channel:     {LIVE_MCAST_ADDR}:{MCAST_PORT}")
    log.info(f"SNAPSHOT channel: {SNAP_MCAST_ADDR}:{MCAST_PORT}")
    log.info("=" * 60)

    try:
        if use_poll:
            while True:
                events: list[tuple[int, int]] = poller.poll(timeout=0.0)

                for fd, event in events:
                    if event & select.EPOLLIN:
                        for sock in sockets:
                            if sock.fileno() == fd:
                                try:
                                    data = sock.recv(MAX_UDP_PAYLOAD)
                                    if data:
                                        clean_data = "".join(
                                            f"{b:02x}" for b in data
                                        ).rstrip()
                                        data_buffer += bytes.fromhex(clean_data)
                                        while len(data_buffer) >= MDHeader.STRUCT_SIZE:
                                            header = MDHeader(
                                                data_buffer[: MDHeader.STRUCT_SIZE]
                                            )
                                            if len(data_buffer) < header.length:
                                                break
                                            packet = data_buffer[: header.length]
                                            data_buffer = data_buffer[header.length :]
                                            if header.magic_number == MAGIC_NUMBER:
                                                if not synchronizer.sync:
                                                    synchronizer.buffer_live_message(
                                                        header, parse_message(packet)
                                                    )
                                                else:
                                                    seq_tracker.check(header.seq_num)
                                                    parse_live_message(
                                                        header,
                                                        parse_message(packet),
                                                        manager,
                                                    )
                                                    if header.seq_num % 1000 == 0:
                                                        for sym, book in sorted(
                                                            manager.books.items()
                                                        ):
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
                                                    synchronizer.handle_snapshot_message(
                                                        header, parse_message(packet)
                                                    )
                                                    if synchronizer.snap_complete:
                                                        log.info(
                                                            "Snapshot complete for all symbols\n\n"
                                                        )
                                                        synchronizer.replay_buffered_messages()
                                                        for sym, book in sorted(
                                                            manager.books.items()
                                                        ):
                                                            log.info(f" {book}")
                                except BlockingIOError:
                                    pass
                                break
        else:
            readable, _, _ = select.select(sockets, [], [], 0)
            for sock in readable:
                try:
                    data = sock.recv(1500)
                    if data:
                        print(f"Read {len(data)} bytes")
                        # Print hex dump
                        hex_str = ":".join(f"{b:02x}" for b in data)
                        print(hex_str)
                except BlockingIOError:
                    pass  # No data available
    except KeyboardInterrupt:
        log.info("\nShutting down")
    finally:
        live_sock.close()
        snap_sock.close()


if __name__ == "__main__":
    main()

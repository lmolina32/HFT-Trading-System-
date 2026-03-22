#!/usr/bin/env python3

import threading
import sys
import struct
from order_book import OrderBookManager, SnapShotSynchronizer, SequenceTracker, parse_live_message
from market_data_struct import MDHeader, MAGIC_NUMBER
from parsey import parse_message
from order_entry import OrderEntryClient
from order_entry_protocol import Side

def run_market_data(order_manager):
    '''main from parsey.py'''
    synchronizer = SnapShotSynchronizer(order_manager)
    seq_tracker = SequenceTracker()
    buffer = b''

    for line in sys.stdin:
        hex_line = line.rstrip()
        if hex_line.startswith(("Read", "Subscribed", "Listening")):
            continue

        hexString = hex_line.replace(':', '')
        data = bytes.fromhex(hexString)
        buffer += data

        while len(buffer) >= 23:
            magic, length, seq_num, timestamp, msg_type = struct.unpack('<QHIQB', buffer[:23])
            header = MDHeader(buffer[:23])
            if len(buffer) < header.length:
                break

            packet = buffer[:length]
            buffer = buffer[length:]

            # Process LIVE Channel
            if header.magic_number == MAGIC_NUMBER:
                if not synchronizer.sync:
                    synchronizer.buffer_live_message(header, parse_message(packet))
                else:
                    seq_tracker.check(header.seq_num)
                    parse_live_message(header, parse_message(packet), order_manager)
                    if header.seq_num % 1000 == 0:
                        for sym, book in sorted(order_manager.books.items()):
                            bb = book.get_best_bid()
                            ba = book.get_best_ask()
                            print(
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
                        print("Snapshot complete for all symbols")
                        synchronizer.replay_buffered_messages()
                        for sym, book in sorted(order_manager.books.items()):
                            print(f" {book}")

def run_order_entry(client):
    ''' main() from order_entry.py, but am connecting it here to syncrhonize'''
    client.log_in()

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
            elif cmd == "quit":
                break
            else:
                print(f"unknown command: {cmd}")
        except (ValueError, TypeError) as e:
            print(f"bad input: {e}")

def main():
    order_manager = OrderBookManager()  # shared between market data and order entry. need for pnl current market value.

    # market data runs in background thread reading from stdin
    md_thread = threading.Thread(target=run_market_data, args=(order_manager,), daemon=True)
    md_thread.start()

    # order entry runs in main thread
    client = OrderEntryClient(order_manager=order_manager)
    run_order_entry(client)

if __name__ == '__main__':
    main()
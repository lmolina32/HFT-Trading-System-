#!/usr/bin/env python3

import sys
import struct
import heapq
from dataclasses import dataclass
from typing import Dict, Optional, Tuple, List
from market_data_struct import *
from order_book import *

def parse_message(data):
    """Parse a binary message and return the appropriate message object"""
    if len(data) < MDHeader.STRUCT_SIZE:
        print(f"Error: Data read in is less thatn {MDHeader.STRUCT_SIZE}, check multicast for errors")
        return None

    # Parse header to determine message type
    header = MDHeader(data)

    # Create appropriate message object based on type
    if header.msg_type == MSG_TYPE.NEW_ORDER:
        return NewOrder(data)
    elif header.msg_type == MSG_TYPE.DELETE_ORDER:
        return DeleteOrder(data)
    elif header.msg_type == MSG_TYPE.MODIFY_ORDER:
        return ModifyOrder(data)
    elif header.msg_type == MSG_TYPE.TRADE:
        return Trade(data)
    elif header.msg_type == MSG_TYPE.TRADE_SUMMARY:
        return TradeSummary(data)
    elif header.msg_type == MSG_TYPE.SNAPSHOT_INFO:
        return SnapshotInfo(data)
    elif header.msg_type == MSG_TYPE.HEARTBEAT:
        return {}
    else:
        print(f"{header.msg_type}")
        return header

def main():
    order_manager = OrderBookManager()
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



if __name__ == '__main__':
    main()


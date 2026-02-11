#!/usr/bin/env python3

import sys
import struct
import heapq
from dataclasses import dataclass
from typing import Dict, Optional, Tuple, List
from market_data_struct import *
from order_book import *

@dataclass
class PriceLevel:
    price: int
    total_qty: int = 0
    order_count: int = 0


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
        return header  # Just return header for unknown types

def main():
    order_manager = OrderBookManager()
    synchronizer = SnapShotSynchronizer(order_manager)
    seq_tracker = SequenceTracker()

    buffer = b''
    old = None
    flag = False

    for line in sys.stdin:
        line = line.rstrip()
        if line.startswith(("Read", "Subscribed", "Listening")):
            continue

        hex_line, read_amt = line.split()
        hexString = hex_line.replace(':', '')
        data = bytes.fromhex(hexString)
        buffer += data

        while len(buffer) >= 23:
            magic, length, seq_num, timestamp, msg_type = struct.unpack('<QHIQB', buffer[:23])
            header = MDHeader(buffer[:23])
            if len(buffer) < header.length:
                break


            packet = buffer[:length]
            buffer = buffer[length:]  # Remove processed packet from buffer

            # Process the packet
            #print(struct.pack('<Q', header.magic), f"Magic: {magic:016x} Length: {length} Sequence: {seq_num} Timestamp: {timestamp} Message Type: {msg_type}")
            #print(parse_message(packet))
            print(header)
            print(parse_message(packet))
            continue

            if header.magic_number == MAGIC_NUMBER:
                #if flag and header.seq_num != old_seq_num + 1:

                    #print("this is the seq", header.seq_num)
                    #raise Exception(f"ERROR missed packet {seq_num}")
                #flag = True
                #old_seq_num = header.seq_num
                if not synchronizer.sync:
                    synchronizer.buffer_live_message(header, parse_message(packet))
                else:
                    seq_tracker.check(header.seq_num)
                    parse_live_message(header, parse_message(packet), order_manager)
            else:
                if not synchronizer.sync:
                    synchronizer.handle_snapshot_message(header, parse_message(packet))
                    print(header)
                    print(parse_message(packet))

                    if synchronizer.snap_complete:
                        print("snapshot complete for all symbols")
                        synchronizer.replay_buffered_messages()



if __name__ == '__main__':
    main()


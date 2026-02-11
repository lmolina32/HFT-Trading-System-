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

def parse_live_message(header: MDHeader, body: any, manager: OrderBookManager) -> None:
    if header.msg_type == MSG_TYPE.NEW_ORDER:
        print("new Order")
        manager.process_new_order(
            seq_num=header.seq_num,
            timestamp=header.timestamp,
            order_id=body.order_id,
            symbol=body.symbol,
            side=body.side,
            qty=body.quantity,
            price=body.price,
            flags=body.flags
        )
        print(manager.books.get(1, {}))
        print(manager.books.get(2, {}))
    elif header.msg_type == MSG_TYPE.DELETE_ORDER:
        manager.process_delete_order(
            seq_num=header.seq_num,
            order_id=body.order_id
        )
        print(manager.books.get(1, {}))
        print(manager.books.get(2, {}))
    elif header.msg_type == MSG_TYPE.MODIFY_ORDER:
        manager.process_modify_order(
            seq_num=header.seq_num,
            order_id=body.order_id,
            side=body.side,
            qty=body.quantity,
            price=body.price
        )
        print(manager.books.get(1, {}))
        print(manager.books.get(2, {}))
    elif header.msg_type == MSG_TYPE.TRADE:
        manager.process_trade(
            seq_num=header.seq_num,
            order_id=body.order_id,
            qty=body.quantity,
            price=body.price
        )
        print(manager.books.get(1, {}))
        print(manager.books.get(2, {}))
    elif header.msg_type == MSG_TYPE.TRADE_SUMMARY:
        manager.process_trade_summary(
            seq_num=header.seq_num,
            symbol=body.symbol,
            aggressor=body.aggressor_side,
            total_qty=body.total_quantity,
            last_price=body.last_price
        )
        print(manager.books.get(1, {}))
        print(manager.books.get(2, {}))
    elif header.msg_type == MSG_TYPE.SNAPSHOT_INFO:
        print(manager.books.get(1, {}))
        print(manager.books.get(2, {}))
    elif header.msg_type == MSG_TYPE.HEARTBEAT:
        manager.process_heartbeat(seq_num=header.seq_num)
        print(f"seq={header.seq_num}: HEARTBEAT")
        print(manager.books.get(1, {}))
        print(manager.books.get(2, {}))




def main():
    order_manager = OrderBookManager()
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
            if flag and header.seq_num != old_seq_num + 1:
                print("this is the seq", header.seq_num)
                raise Exception(f"ERROR missed packet {seq_num}")
            flag = True
            old_seq_num = header.seq_num


            packet = buffer[:length]
            buffer = buffer[length:]  # Remove processed packet from buffer

            # Process the packet
            #print(struct.pack('<Q', header.magic), f"Magic: {magic:016x} Length: {length} Sequence: {seq_num} Timestamp: {timestamp} Message Type: {msg_type}")
            print(parse_message(packet))
            if header.magic_number == MAGIC_NUMBER:
                parse_live_message(header, parse_message(packet), order_manager)



if __name__ == '__main__':
    main()


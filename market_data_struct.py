#!/usr/bin/env python3

import struct
from enum import IntEnum
from dataclasses import dataclass
from typing import Optional, Dict, Tuple, List

# Magic numbers
GO_IRISH = b"GOIRISH!"  # 8 bytes
MAGIC_NUMBER = struct.unpack('<Q', GO_IRISH)[0]  # little-endian uint64

SNAPSHOT = b"SNAPSHOT"  # 8 bytes
SNAPSHOT_MAGIC_NUMBER = struct.unpack('<Q', SNAPSHOT)[0]  # little-endian uint64


class MSG_TYPE(IntEnum):
    HEARTBEAT = 0
    NEW_ORDER = 1
    DELETE_ORDER = 2
    MODIFY_ORDER = 3
    TRADE = 4
    TRADE_SUMMARY = 5
    SNAPSHOT_INFO = 6


class SIDE(IntEnum):
    BUY = 1
    SELL = 2


class MDHeader:
    """Market Data Header - 23 bytes"""
    STRUCT_FORMAT = '<QHIQB'  # little-endian: uint64, uint16, uint32, uint64, uint8
    STRUCT_SIZE = struct.calcsize(STRUCT_FORMAT)

    def __init__(self, data):
        unpacked = struct.unpack(self.STRUCT_FORMAT, data[:self.STRUCT_SIZE])
        self.magic_number = unpacked[0]
        self.length = unpacked[1]
        self.seq_num = unpacked[2]
        self.timestamp = unpacked[3]
        self.msg_type = MSG_TYPE(unpacked[4])

    def __repr__(self):
        return (f"MDHeader(magic={self.magic_number:016x}, length={self.length}, "
                f"seq_num={self.seq_num}, timestamp={self.timestamp}, "
                f"msg_type={self.msg_type.name})")


class NewOrder:
    """New Order Message - header + 21 bytes"""
    BODY_FORMAT = '<QIBIiB'  # uint64, uint32, uint8, uint32, int32, uint8
    BODY_SIZE = struct.calcsize(BODY_FORMAT)

    def __init__(self, data):
        self.header = MDHeader(data)
        body_start = MDHeader.STRUCT_SIZE
        unpacked = struct.unpack(self.BODY_FORMAT, data[body_start:body_start + self.BODY_SIZE])
        self.order_id = unpacked[0]
        self.symbol = unpacked[1]
        self.side = SIDE(unpacked[2])
        self.quantity = unpacked[3]
        self.price = unpacked[4]
        self.flags = unpacked[5]

    def __repr__(self):
        return (f"NewOrder(order_id={self.order_id}, symbol={self.symbol}, "
                f"side={self.side.name}, quantity={self.quantity}, "
                f"price={self.price}, flags={self.flags})")


class DeleteOrder:
    """Delete Order Message - header + 8 bytes"""
    BODY_FORMAT = '<Q'  # uint64
    BODY_SIZE = struct.calcsize(BODY_FORMAT)

    def __init__(self, data):
        self.header = MDHeader(data)
        body_start = MDHeader.STRUCT_SIZE
        self.order_id = struct.unpack(self.BODY_FORMAT, data[body_start:body_start + self.BODY_SIZE])[0]

    def __repr__(self):
        return f"DeleteOrder(order_id={self.order_id})"


class ModifyOrder:
    """Modify Order Message - header + 17 bytes"""
    BODY_FORMAT = '<QBIi'  # uint64, uint8, uint32, int32
    BODY_SIZE = struct.calcsize(BODY_FORMAT)

    def __init__(self, data):
        self.header = MDHeader(data)
        body_start = MDHeader.STRUCT_SIZE
        unpacked = struct.unpack(self.BODY_FORMAT, data[body_start:body_start + self.BODY_SIZE])
        self.order_id = unpacked[0]
        self.side = SIDE(unpacked[1])
        self.quantity = unpacked[2]
        self.price = unpacked[3]

    def __repr__(self):
        return (f"ModifyOrder(order_id={self.order_id}, side={self.side.name}, "
                f"quantity={self.quantity}, price={self.price})")


class Trade:
    """Trade Message - header + 16 bytes"""
    BODY_FORMAT = '<QIi'  # uint64, uint32, int32
    BODY_SIZE = struct.calcsize(BODY_FORMAT)

    def __init__(self, data):
        self.header = MDHeader(data)
        body_start = MDHeader.STRUCT_SIZE
        unpacked = struct.unpack(self.BODY_FORMAT, data[body_start:body_start + self.BODY_SIZE])
        self.order_id = unpacked[0]
        self.quantity = unpacked[1]
        self.price = unpacked[2]

    def __repr__(self):
        return (f"Trade(order_id={self.order_id}, quantity={self.quantity}, "
                f"price={self.price})")


class TradeSummary:
    """Trade Summary Message - header + 17 bytes"""
    BODY_FORMAT = '<IBIi'  # uint32, uint8, uint32, int32
    BODY_SIZE = struct.calcsize(BODY_FORMAT)

    def __init__(self, data):
        self.header = MDHeader(data)
        body_start = MDHeader.STRUCT_SIZE
        unpacked = struct.unpack(self.BODY_FORMAT, data[body_start:body_start + self.BODY_SIZE])
        self.symbol = unpacked[0]
        self.aggressor_side = SIDE(unpacked[1])
        self.total_quantity = unpacked[2]
        self.last_price = unpacked[3]

    def __repr__(self):
        return (f"TradeSummary(symbol={self.symbol}, aggressor_side={self.aggressor_side.name}, "
                f"total_quantity={self.total_quantity}, last_price={self.last_price})")


class SnapshotInfo:
    """Snapshot Info Message - header + 16 bytes"""
    BODY_FORMAT = '<IIII'  # uint32, uint32, uint32, uint32
    BODY_SIZE = struct.calcsize(BODY_FORMAT)

    def __init__(self, data):
        self.header = MDHeader(data)
        body_start = MDHeader.STRUCT_SIZE
        unpacked = struct.unpack(self.BODY_FORMAT, data[body_start:body_start + self.BODY_SIZE])
        self.symbol = unpacked[0]
        self.bid_count = unpacked[1]
        self.ask_count = unpacked[2]
        self.last_md_seq_num = unpacked[3]

    def __repr__(self):
        return (f"SnapshotInfo(symbol={self.symbol}, bid_count={self.bid_count}, "
                f"ask_count={self.ask_count}, last_md_seq_num={self.last_md_seq_num})")

@dataclass
class PriceLevel:
    price: int
    total_qty: int = 0
    order_count: int = 0

@dataclass
class BBORecord:
    seq_num: int
    symbol: int
    best_bid_price: Optional[int]
    best_bid_qty: Optional[int]
    best_ask_price: Optional[int]
    best_ask_qty: Optional[int]

@dataclass
class Order:
    order_id: int
    symbol: int
    side: SIDE
    quantity: int
    price: int
    timestamp: int

# Calculate max message size
MAX_MSG_SIZE = max(
    MDHeader.STRUCT_SIZE + NewOrder.BODY_SIZE,
    MDHeader.STRUCT_SIZE + DeleteOrder.BODY_SIZE,
    MDHeader.STRUCT_SIZE + ModifyOrder.BODY_SIZE,
    MDHeader.STRUCT_SIZE + Trade.BODY_SIZE,
    MDHeader.STRUCT_SIZE + TradeSummary.BODY_SIZE,
    MDHeader.STRUCT_SIZE + SnapshotInfo.BODY_SIZE
)

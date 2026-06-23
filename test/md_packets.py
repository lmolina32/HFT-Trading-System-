"""Helpers for building raw market-data packets used in tests."""

import struct

import _path_setup  # noqa: F401

from src.market_data_struct import MAGIC_NUMBER, MSG_TYPE, SNAPSHOT_MAGIC_NUMBER


MD_HEADER_FORMAT = "<QHIQB"
MD_HEADER_SIZE = struct.calcsize(MD_HEADER_FORMAT)


def _header(magic: int, length: int, seq_num: int, timestamp: int, msg_type: int) -> bytes:
    return struct.pack(MD_HEADER_FORMAT, magic, length, seq_num, timestamp, msg_type)


def new_order_packet(
    seq_num: int,
    timestamp: int,
    order_id: int,
    symbol: int,
    side: int,
    quantity: int,
    price: int,
    flags: int = 0,
    *,
    magic: int = MAGIC_NUMBER,
) -> bytes:
    body = struct.pack("<QIBIiB", order_id, symbol, side, quantity, price, flags)
    return _header(magic, MD_HEADER_SIZE + len(body), seq_num, timestamp, MSG_TYPE.NEW_ORDER) + body


def delete_order_packet(seq_num: int, timestamp: int, order_id: int) -> bytes:
    body = struct.pack("<Q", order_id)
    return _header(MAGIC_NUMBER, MD_HEADER_SIZE + len(body), seq_num, timestamp, MSG_TYPE.DELETE_ORDER) + body


def modify_order_packet(
    seq_num: int,
    timestamp: int,
    order_id: int,
    side: int,
    quantity: int,
    price: int,
) -> bytes:
    body = struct.pack("<QBIi", order_id, side, quantity, price)
    return _header(MAGIC_NUMBER, MD_HEADER_SIZE + len(body), seq_num, timestamp, MSG_TYPE.MODIFY_ORDER) + body


def trade_packet(
    seq_num: int,
    timestamp: int,
    order_id: int,
    quantity: int,
    price: int,
) -> bytes:
    body = struct.pack("<QIi", order_id, quantity, price)
    return _header(MAGIC_NUMBER, MD_HEADER_SIZE + len(body), seq_num, timestamp, MSG_TYPE.TRADE) + body


def trade_summary_packet(
    seq_num: int,
    timestamp: int,
    symbol: int,
    aggressor_side: int,
    total_quantity: int,
    last_price: int,
) -> bytes:
    body = struct.pack("<IBIi", symbol, aggressor_side, total_quantity, last_price)
    return _header(MAGIC_NUMBER, MD_HEADER_SIZE + len(body), seq_num, timestamp, MSG_TYPE.TRADE_SUMMARY) + body


def snapshot_info_packet(
    seq_num: int,
    timestamp: int,
    symbol: int,
    bid_count: int,
    ask_count: int,
    last_md_seq_num: int,
) -> bytes:
    body = struct.pack("<IIII", symbol, bid_count, ask_count, last_md_seq_num)
    return _header(SNAPSHOT_MAGIC_NUMBER, MD_HEADER_SIZE + len(body), seq_num, timestamp, MSG_TYPE.SNAPSHOT_INFO) + body


def snapshot_new_order_packet(
    seq_num: int,
    timestamp: int,
    order_id: int,
    symbol: int,
    side: int,
    quantity: int,
    price: int,
) -> bytes:
    return new_order_packet(
        seq_num, timestamp, order_id, symbol, side, quantity, price,
        magic=SNAPSHOT_MAGIC_NUMBER,
    )


def heartbeat_packet(seq_num: int, timestamp: int) -> bytes:
    return _header(MAGIC_NUMBER, MD_HEADER_SIZE, seq_num, timestamp, MSG_TYPE.HEARTBEAT)

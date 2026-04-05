#!/usr/bin/env python3

from __future__ import annotations

from .market_data_struct import (
    MSG_TYPE,
    MDHeader,
    NewOrder,
    DeleteOrder,
    ModifyOrder,
    Trade,
    TradeSummary,
    SnapshotInfo,
    MarketDataMessage,
)

_MSG_CONSTRUCTORS: dict[int, type] = {
    MSG_TYPE.NEW_ORDER: NewOrder,
    MSG_TYPE.DELETE_ORDER: DeleteOrder,
    MSG_TYPE.MODIFY_ORDER: ModifyOrder,
    MSG_TYPE.TRADE: Trade,
    MSG_TYPE.TRADE_SUMMARY: TradeSummary,
    MSG_TYPE.SNAPSHOT_INFO: SnapshotInfo,
}


def parse_message(data: bytes) -> MarketDataMessage:
    """Parse a binary message and return the appropriate message object"""
    if len(data) < MDHeader.STRUCT_SIZE:
        raise ValueError(
            f"Data read in is less than {MDHeader.STRUCT_SIZE}, check multicast for errors"
        )

    msg_type_raw: int = data[22]

    if msg_type_raw == MSG_TYPE.HEARTBEAT:
        return MDHeader(data)

    constructor = _MSG_CONSTRUCTORS.get(msg_type_raw)
    if constructor is None:
        raise ValueError(f"Unknown msg_type={msg_type_raw}")

    return constructor(data)

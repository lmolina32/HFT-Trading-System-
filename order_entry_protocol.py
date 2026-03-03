#!/usr/bin/env python3

"""
order_entry_protocol.py: structs for order entry in NDFEX
"""

import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import ClassVar

OE_PROTOCOL_VERSION = 1

# ── Enums ────────────────────────────────────────────────────────────────────

class MsgType(IntEnum):
    NEW_ORDER       = 1
    DELETE_ORDER    = 2
    MODIFY_ORDER    = 3
    LOGIN           = 99
    LOGIN_RESPONSE  = 100
    ACK             = 101
    REJECT          = 102
    FILL            = 103
    CLOSE           = 104
    ERROR           = 105

class RejectReason(IntEnum):
    NONE               = 0
    UNKNOWN_SYMBOL     = 1
    INVALID_ORDER      = 2
    DUPLICATE_ORDER_ID = 3
    UNKNOWN_ORDER_ID   = 4
    INVALID_PRICE      = 5
    INVALID_QUANTITY   = 6
    INVALID_SIDE       = 7
    UNKNOWN_SESSION_ID = 8
    DUPLICATE_LOGIN    = 9

class LoginStatus(IntEnum):
    SUCCESS               = 0
    INVALID_USERNAME      = 5
    INVALID_PASSWORD      = 6
    INVALID_SESSION       = 7
    SESSION_ALREADY_ACTIVE = 8
    DUPLICATE_LOGIN      = 9
    INVALID_CLIENT_ID    = 10

class OrderFlags(IntEnum):
    NONE = 0
    IOC  = 1

class FillFlags(IntEnum):
    NONE         = 0
    PARTIAL_FILL = 1
    CLOSED       = 2

class Side(IntEnum):
    BUY  = 1  # CANNOT BE 0. chat autofilled this and it was WRONG.
    SELL = 2

# ── Headers ──────────────────────────────────────────────────────────────────

@dataclass
class OeRequestHeader:
    # H=uint16, B=uint8, B=uint8, I=uint32, I=uint32, Q=uint64
    FORMAT: ClassVar[str] = "<HBBIIQ"
    SIZE:   ClassVar[int] = struct.calcsize(FORMAT)

    length:    int
    msg_type:  int
    version:   int
    seq_num:   int
    client_id: int
    session_id: int

    def pack(self) -> bytes:
        return struct.pack(
            self.FORMAT,
            self.length, self.msg_type, self.version,
            self.seq_num, self.client_id, self.session_id
        )

    @classmethod
    def unpack(cls, data: bytes) -> "OeRequestHeader":
        fields = struct.unpack(cls.FORMAT, data[:cls.SIZE])
        return cls(*fields)


@dataclass
class OeResponseHeader:
    # H=uint16, B=uint8, B=uint8, I=uint32, I=uint32, I=uint32
    FORMAT: ClassVar[str] = "<HBBIII"
    SIZE:   ClassVar[int] = struct.calcsize(FORMAT)

    length:      int
    msg_type:    int
    version:     int
    seq_num:     int
    last_seq_num: int
    client_id:   int

    def pack(self) -> bytes:
        return struct.pack(
            self.FORMAT,
            self.length, self.msg_type, self.version,
            self.seq_num, self.last_seq_num, self.client_id
        )

    @classmethod
    def unpack(cls, data: bytes) -> "OeResponseHeader":
        fields = struct.unpack(cls.FORMAT, data[:cls.SIZE])
        return cls(*fields)

# ── Messages ─────────────────────────────────────────────────────────────────

@dataclass
class Login:
    FORMAT: ClassVar[str] = OeRequestHeader.FORMAT + "16s16s"
    SIZE:   ClassVar[int] = struct.calcsize(FORMAT)

    header:   OeRequestHeader
    username: bytes   # max 16 bytes
    password: bytes   # max 16 bytes

    def pack(self) -> bytes:
        return struct.pack(
            self.FORMAT,
            self.header.length, self.header.msg_type, self.header.version,
            self.header.seq_num, self.header.client_id, self.header.session_id,
            self.username.ljust(16, b'\x00')[:16],
            self.password.ljust(16, b'\x00')[:16]
        )

    @classmethod
    def unpack(cls, data: bytes) -> "Login":
        fields = struct.unpack(cls.FORMAT, data[:cls.SIZE])
        header = OeRequestHeader(*fields[:7])
        return cls(header, fields[7], fields[8])


@dataclass
class LoginResponse:
    FORMAT: ClassVar[str] = OeResponseHeader.FORMAT + "QB"
    SIZE:   ClassVar[int] = struct.calcsize(FORMAT)

    header:      OeResponseHeader
    session_id: int
    status:      int   # LoginStatus

    def pack(self) -> bytes:
        return struct.pack(
            self.FORMAT,
            self.header.length, self.header.msg_type, self.header.version,
            self.header.seq_num, self.header.last_seq_num, self.header.client_id,
            self.session_id, self.status
        )

    @classmethod
    def unpack(cls, data: bytes) -> "LoginResponse":
        fields = struct.unpack(cls.FORMAT, data[:cls.SIZE])
        header = OeResponseHeader(*fields[:6])
        return cls(header, fields[6], fields[7])


@dataclass
class NewOrder:
    FORMAT: ClassVar[str] = OeRequestHeader.FORMAT + "QIBIiB"
    SIZE:   ClassVar[int] = struct.calcsize(FORMAT)

    header:   OeRequestHeader
    order_id: int
    symbol:   int
    side:      int   # Side
    quantity: int
    price:    int
    flags:    int   # OrderFlags

    def pack(self) -> bytes:
        return struct.pack(
            self.FORMAT,
            self.header.length, self.header.msg_type, self.header.version,
            self.header.seq_num, self.header.client_id, self.header.session_id,
            self.order_id, self.symbol, self.side, self.quantity, self.price, self.flags
        )

    @classmethod
    def unpack(cls, data: bytes) -> "NewOrder":
        fields = struct.unpack(cls.FORMAT, data[:cls.SIZE])
        header = OeRequestHeader(*fields[:7])
        return cls(header, *fields[7:])


@dataclass
class DeleteOrder:
    FORMAT: ClassVar[str] = OeRequestHeader.FORMAT + "Q"
    SIZE:   ClassVar[int] = struct.calcsize(FORMAT)

    header:   OeRequestHeader
    order_id: int

    def pack(self) -> bytes:
        return struct.pack(
            self.FORMAT,
            self.header.length, self.header.msg_type, self.header.version,
            self.header.seq_num, self.header.client_id, self.header.session_id,
            self.order_id
        )

    @classmethod
    def unpack(cls, data: bytes) -> "DeleteOrder":
        fields = struct.unpack(cls.FORMAT, data[:cls.SIZE])
        header = OeRequestHeader(*fields[:7])
        return cls(header, fields[7])


@dataclass
class ModifyOrder:
    FORMAT: ClassVar[str] = OeRequestHeader.FORMAT + "QBIi"
    SIZE:   ClassVar[int] = struct.calcsize(FORMAT)

    header:   OeRequestHeader
    order_id: int
    side:      int   # Side
    quantity: int
    price:    int

    def pack(self) -> bytes:
        return struct.pack(
            self.FORMAT,
            self.header.length, self.header.msg_type, self.header.version,
            self.header.seq_num, self.header.client_id, self.header.session_id,
            self.order_id, self.side, self.quantity, self.price
        )

    @classmethod
    def unpack(cls, data: bytes) -> "ModifyOrder":
        fields = struct.unpack(cls.FORMAT, data[:cls.SIZE])
        header = OeRequestHeader(*fields[:7])
        return cls(header, *fields[7:])


@dataclass
class OrderAck:
    FORMAT: ClassVar[str] = OeResponseHeader.FORMAT + "QQIi"
    SIZE:   ClassVar[int] = struct.calcsize(FORMAT)

    header:         OeResponseHeader
    order_id:       int
    exch_order_id: int
    quantity:       int
    price:          int

    def pack(self) -> bytes:
        return struct.pack(
            self.FORMAT,
            self.header.length, self.header.msg_type, self.header.version,
            self.header.seq_num, self.header.last_seq_num, self.header.client_id,
            self.order_id, self.exch_order_id, self.quantity, self.price
        )

    @classmethod
    def unpack(cls, data: bytes) -> "OrderAck":
        fields = struct.unpack(cls.FORMAT, data[:cls.SIZE])
        header = OeResponseHeader(*fields[:6])
        return cls(header, *fields[6:])


@dataclass
class OrderReject:
    FORMAT: ClassVar[str] = OeResponseHeader.FORMAT + "QB"
    SIZE:   ClassVar[int] = struct.calcsize(FORMAT)

    header:         OeResponseHeader
    order_id:       int
    reject_reason: int   # RejectReason

    def pack(self) -> bytes:
        return struct.pack(
            self.FORMAT,
            self.header.length, self.header.msg_type, self.header.version,
            self.header.seq_num, self.header.last_seq_num, self.header.client_id,
            self.order_id, self.reject_reason
        )

    @classmethod
    def unpack(cls, data: bytes) -> "OrderReject":
        fields = struct.unpack(cls.FORMAT, data[:cls.SIZE])
        header = OeResponseHeader(*fields[:6])
        return cls(header, *fields[6:])


@dataclass
class OrderFill:
    FORMAT: ClassVar[str] = OeResponseHeader.FORMAT + "QIiB"
    SIZE:   ClassVar[int] = struct.calcsize(FORMAT)

    header:   OeResponseHeader
    order_id: int
    quantity: int
    price:    int
    flags:    int   # FillFlags

    def pack(self) -> bytes:
        return struct.pack(
            self.FORMAT,
            self.header.length, self.header.msg_type, self.header.version,
            self.header.seq_num, self.header.last_seq_num, self.header.client_id,
            self.order_id, self.quantity, self.price, self.flags
        )

    @classmethod
    def unpack(cls, data: bytes) -> "OrderFill":
        fields = struct.unpack(cls.FORMAT, data[:cls.SIZE])
        header = OeResponseHeader(*fields[:6])
        return cls(header, *fields[6:])


@dataclass
class OrderClosed:
    FORMAT: ClassVar[str] = OeResponseHeader.FORMAT + "Q"
    SIZE:   ClassVar[int] = struct.calcsize(FORMAT)

    header:   OeResponseHeader
    order_id: int

    def pack(self) -> bytes:
        return struct.pack(
            self.FORMAT,
            self.header.length, self.header.msg_type, self.header.version,
            self.header.seq_num, self.header.last_seq_num, self.header.client_id,
            self.order_id
        )

    @classmethod
    def unpack(cls, data: bytes) -> "OrderClosed":
        fields = struct.unpack(cls.FORMAT, data[:cls.SIZE])
        header = OeResponseHeader(*fields[:6])
        return cls(header, fields[6])


@dataclass
class ErrorMessage:
    FORMAT: ClassVar[str] = OeResponseHeader.FORMAT + "BH32s"
    SIZE:   ClassVar[int] = struct.calcsize(FORMAT)

    header:                OeResponseHeader
    error_code:            int
    error_message_length: int
    error_message:         bytes   # max 32 bytes

    def pack(self) -> bytes:
        return struct.pack(
            self.FORMAT,
            self.header.length, self.header.msg_type, self.header.version,
            self.header.seq_num, self.header.last_seq_num, self.header.client_id,
            self.error_code, self.error_message_length,
            self.error_message.ljust(32, b'\x00')[:32]
        )

    @classmethod
    def unpack(cls, data: bytes) -> "ErrorMessage":
        fields = struct.unpack(cls.FORMAT, data[:cls.SIZE])
        header = OeResponseHeader(*fields[:6])
        return cls(header, *fields[6:])

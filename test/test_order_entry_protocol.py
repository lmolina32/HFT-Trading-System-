#!/usr/bin/env python3
"""Pack/unpack round-trip tests for the TCP order-entry protocol."""

import unittest

import _path_setup  # noqa: F401

from src.order_entry_protocol import (
    DeleteOrder,
    ErrorMessage,
    FillFlags,
    Login,
    LoginResponse,
    LoginStatus,
    ModifyOrder,
    MsgType,
    NewOrder,
    OE_PROTOCOL_VERSION,
    OeRequestHeader,
    OeResponseHeader,
    OrderAck,
    OrderClosed,
    OrderFill,
    OrderFlags,
    OrderReject,
    RejectReason,
    Side,
)


def req_header(msg_type, length, seq_num=1, client_id=2, session_id=0):
    return OeRequestHeader(
        length=length, msg_type=int(msg_type), version=OE_PROTOCOL_VERSION,
        seq_num=seq_num, client_id=client_id, session_id=session_id,
    )


def resp_header(msg_type, length, seq_num=1, last_seq=0, client_id=2):
    return OeResponseHeader(
        length=length, msg_type=int(msg_type), version=OE_PROTOCOL_VERSION,
        seq_num=seq_num, last_seq_num=last_seq, client_id=client_id,
    )


class TestHeaderRoundTrip(unittest.TestCase):
    def test_request_header(self):
        h = OeRequestHeader(length=10, msg_type=1, version=OE_PROTOCOL_VERSION,
                            seq_num=99, client_id=2, session_id=12345)
        decoded = OeRequestHeader.unpack(h.pack())
        self.assertEqual(decoded, h)

    def test_response_header(self):
        h = OeResponseHeader(length=12, msg_type=101, version=OE_PROTOCOL_VERSION,
                             seq_num=99, last_seq_num=98, client_id=2)
        decoded = OeResponseHeader.unpack(h.pack())
        self.assertEqual(decoded, h)


class TestRequestMessages(unittest.TestCase):
    def test_login_roundtrip(self):
        msg = Login(
            header=req_header(MsgType.LOGIN, Login.SIZE),
            username=b"team2",
            password=b"hunter2",
        )
        decoded = Login.unpack(msg.pack())
        self.assertEqual(decoded.header.msg_type, int(MsgType.LOGIN))
        # ljust to the wire width
        self.assertEqual(decoded.username, b"team2".ljust(16, b"\x00"))
        self.assertEqual(decoded.password, b"hunter2".ljust(16, b"\x00"))

    def test_login_truncates_oversize_credentials(self):
        msg = Login(
            header=req_header(MsgType.LOGIN, Login.SIZE),
            username=b"a" * 32,
            password=b"b" * 32,
        )
        decoded = Login.unpack(msg.pack())
        self.assertEqual(decoded.username, b"a" * 16)
        self.assertEqual(decoded.password, b"b" * 16)

    def test_new_order_roundtrip(self):
        msg = NewOrder(
            header=req_header(MsgType.NEW_ORDER, NewOrder.SIZE),
            order_id=42, symbol=1, side=int(Side.BUY),
            quantity=10, price=1234, flags=int(OrderFlags.IOC),
        )
        decoded = NewOrder.unpack(msg.pack())
        self.assertEqual(decoded.order_id, 42)
        self.assertEqual(decoded.side, int(Side.BUY))
        self.assertEqual(decoded.flags, int(OrderFlags.IOC))
        self.assertEqual(decoded.price, 1234)

    def test_delete_order_roundtrip(self):
        msg = DeleteOrder(
            header=req_header(MsgType.DELETE_ORDER, DeleteOrder.SIZE),
            order_id=99,
        )
        self.assertEqual(DeleteOrder.unpack(msg.pack()).order_id, 99)

    def test_modify_order_roundtrip(self):
        msg = ModifyOrder(
            header=req_header(MsgType.MODIFY_ORDER, ModifyOrder.SIZE),
            order_id=100, side=int(Side.SELL), quantity=7, price=555,
        )
        decoded = ModifyOrder.unpack(msg.pack())
        self.assertEqual(decoded.order_id, 100)
        self.assertEqual(decoded.side, int(Side.SELL))
        self.assertEqual(decoded.quantity, 7)
        self.assertEqual(decoded.price, 555)


class TestResponseMessages(unittest.TestCase):
    def test_login_response_roundtrip(self):
        msg = LoginResponse(
            header=resp_header(MsgType.LOGIN_RESPONSE, LoginResponse.SIZE),
            session_id=987654321, status=int(LoginStatus.SUCCESS),
        )
        decoded = LoginResponse.unpack(msg.pack())
        self.assertEqual(decoded.session_id, 987654321)
        self.assertEqual(decoded.status, int(LoginStatus.SUCCESS))

    def test_order_ack_roundtrip(self):
        msg = OrderAck(
            header=resp_header(MsgType.ACK, OrderAck.SIZE),
            order_id=1, exch_order_id=2, quantity=3, price=4,
        )
        decoded = OrderAck.unpack(msg.pack())
        self.assertEqual((decoded.order_id, decoded.exch_order_id,
                          decoded.quantity, decoded.price), (1, 2, 3, 4))

    def test_order_reject_roundtrip(self):
        msg = OrderReject(
            header=resp_header(MsgType.REJECT, OrderReject.SIZE),
            order_id=7, reject_reason=int(RejectReason.RISK_REJECT),
        )
        decoded = OrderReject.unpack(msg.pack())
        self.assertEqual(decoded.order_id, 7)
        self.assertEqual(decoded.reject_reason, int(RejectReason.RISK_REJECT))

    def test_order_fill_roundtrip(self):
        msg = OrderFill(
            header=resp_header(MsgType.FILL, OrderFill.SIZE),
            order_id=99, quantity=5, price=1000, flags=int(FillFlags.CLOSED),
        )
        decoded = OrderFill.unpack(msg.pack())
        self.assertEqual(decoded.quantity, 5)
        self.assertEqual(decoded.flags, int(FillFlags.CLOSED))

    def test_order_closed_roundtrip(self):
        msg = OrderClosed(
            header=resp_header(MsgType.CLOSE, OrderClosed.SIZE),
            order_id=55,
        )
        self.assertEqual(OrderClosed.unpack(msg.pack()).order_id, 55)

    def test_error_message_roundtrip(self):
        text = b"too bad"
        msg = ErrorMessage(
            header=resp_header(MsgType.ERROR, ErrorMessage.SIZE),
            error_code=42, error_message_length=len(text), error_message=text,
        )
        decoded = ErrorMessage.unpack(msg.pack())
        self.assertEqual(decoded.error_code, 42)
        self.assertEqual(decoded.error_message[:len(text)], text)


class TestEnumIntegrity(unittest.TestCase):
    def test_msgtype_distinct(self):
        values = [int(x) for x in MsgType]
        self.assertEqual(len(values), len(set(values)))

    def test_side_distinct(self):
        self.assertNotEqual(int(Side.BUY), int(Side.SELL))


if __name__ == "__main__":
    unittest.main()

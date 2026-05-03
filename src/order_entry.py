#!/usr/bin/env python3

from __future__ import annotations

import logging
import socket
import struct
import time
from typing import Optional, List, Tuple

from .order_book import OrderBookManager
from .order_entry_protocol import (
    OE_PROTOCOL_VERSION,
    MsgType,
    RejectReason,
    LoginStatus,
    OrderFlags,
    FillFlags,
    Side,
    OeRequestHeader,
    OeResponseHeader,
    Login,
    LoginResponse,
    NewOrder,
    DeleteOrder,
    ModifyOrder,
    OrderAck,
    OrderReject,
    OrderFill,
    OrderClosed,
    ErrorMessage,
    OeResponse,
    OeConfig,
)
from .safety import PositionTracker, ExposureTracker, PnLTracker, RiskTracker

log: logging.Logger = logging.getLogger("order_entry")
log.propagate = False
log.info("This goes to order_entry.log (and maybe app.log)")


RESP_HDR_SIZE = OeResponseHeader.SIZE


class OrderEntryClient:
    """
    OrderEntryClient to place orders to NDFEX

    Attributes:
        user_name: username for the exchange
        passowrd:  password associated with account
        clientId:  specified Id for client
        sessionID: Identifier given by NDFEX when client logs in
        seqNum:    Class sequence number for sending out orders
        respSeq:   Last Sequence number seen from the Exchange
        host:      Host of NDFEX
        port:      Port of NDFEX
        PositionTracker:  Used to track the current position in BUYs and SELLs
        openOrders: Map of OrderIds to given orders (symbol, side, quantity)
        exposureTracker:  Keep track of exposure on open orders
        riskTracker:      Keep track of risk tracking
        pnlTracker:       keep track of PNL for all open orders
        order_manager:    Manager of orderbook from live data
        pnlMinVal:        lowest PNL value allowed
        positionLimit: maximum position limit allowed
        socket:           socket to connect to NDFEX
    """

    __slots__ = (
        "username",
        "password",
        "client_id",
        "session_id",
        "seq_num",
        "resp_seq",
        "host",
        "port",
        "position_tracker",
        "open_orders",
        "exposure_tracker",
        "risk_tracker",
        "pnl_tracker",
        "order_manager",
        "pnl_min_val",
        "position_limit",
        "socket",
    )

    def __init__(
        self,
        order_manager: OrderBookManager,
        host: str = "192.168.13.100",
        port: int = 1234,
        username: bytes = b"team2",
        password: bytes = b"92vM31Pa",
        client_id: int = 2,
        pnl_floor: int = -20_000,
        position_cap: int = 10,
    ):
        self.username: bytes = username
        self.password: bytes = password
        self.client_id: int = client_id
        self.session_id: int = 0
        self.seq_num: int = 0
        self.resp_seq: int = 0
        self.host: str = host
        self.port: int = port

        # Tracking & Risk
        self.position_tracker: PositionTracker = PositionTracker()
        self.open_orders: dict[int, OeConfig] = {}
        self.exposure_tracker: ExposureTracker = ExposureTracker()
        self.risk_tracker: RiskTracker = RiskTracker()
        self.pnl_tracker: PnLTracker = PnLTracker()
        self.order_manager: OrderBookManager = order_manager
        self.pnl_min_val: int = pnl_floor
        self.position_limit: int = position_cap

        # TCP socket
        self.socket: Optional[socket.socket] = None
        self._connect()

    def _connect(self) -> None:
        """Establish TCP connection to exchange"""
        self._close()
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.socket.connect((self.host, self.port))
            log.info(f"Succesful connection to {self.host}:{self.port}")
        except Exception as e:
            log.error(f"Connection failed: {e}")
            self._close()
            raise

    def _close(self) -> None:
        """Gracefully shut down the TCP socket"""
        if self.socket is not None:
            try:
                self.socket.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            finally:
                self.socket.close()
                self.socket = None

    def login(self) -> LoginResponse:
        """
        Sends Log in request to NDFEX, if succesful returns the LoginResponse and initilizes session id

        Returns:
            LoginResponse recieved from NDFEX

        Raises:
            PermissionError: if LoginStatus does not equal SUCCESS
        """
        msg = Login(
            header=self._make_header(MsgType.LOGIN, Login.SIZE),
            username=self.username,
            password=self.password,
        )
        self._send_raw(msg.pack())
        log.info("SEND LOGIN  username=%s  seq=%d", self.username, self.seq_num)

        resp = self._parse_response(self._recv_message())
        if not isinstance(resp, LoginResponse):
            raise PermissionError(f"Expected LoginResponse: got {type(resp).__name__}")

        status = LoginStatus(resp.status)
        if status != LoginStatus.SUCCESS:
            log.error("login failed:  status=%s", status.name)
            raise PermissionError("couldnt login...")

        self.session_id = resp.session_id
        log.info("Login Success: session_id=%d", self.session_id)
        return resp

    def _parse_response(self, data: bytes) -> OeResponse:
        """
        Parse data packet recieved from NDFEX and unpack into appropriate struct

        Args:
            data: Raw bytes from TCP connection

        Returns:
            Unpacked struct that matches MsgType
        """
        hdr = OeResponseHeader.unpack(data)
        self._validate_response_header(hdr)
        self.resp_seq = hdr.seq_num
        msg_type = MsgType(hdr.msg_type)
        log.info("RECV %s  seq=%d", msg_type.name, hdr.seq_num)

        dispatch: dict[MsgType, type] = {
            MsgType.LOGIN_RESPONSE: LoginResponse,
            MsgType.ACK: OrderAck,
            MsgType.REJECT: OrderReject,
            MsgType.FILL: OrderFill,
            MsgType.CLOSE: OrderClosed,
            MsgType.ERROR: ErrorMessage,
        }
        cls = dispatch.get(msg_type)
        if cls is not None:
            return cls.unpack(data)
        return hdr

    def _make_header(self, msg_type: MsgType, length: int) -> OeRequestHeader:
        """Creates OeRequestHeader given specified msgType and length"""
        return OeRequestHeader(
            length=length,
            msg_type=int(msg_type),
            version=OE_PROTOCOL_VERSION,
            seq_num=self._next_seq(),
            client_id=self.client_id,
            session_id=self.session_id,
        )

    def _next_seq(self) -> int:
        """Update and return clients sequence counter"""
        self.seq_num += 1
        return self.seq_num

    def _send_raw(self, data: bytes) -> None:
        """Send Raw order structs over the wire"""
        assert self.socket is not None
        log.debug("SEND (%d bytes): %s", len(data), data.hex())
        self.socket.sendall(data)

    def _recv_exact(self, expected_size: int) -> bytes:
        """Listen over the wire until receives a packet of the expected size"""
        assert self.socket is not None
        buf = bytearray(expected_size)
        view = memoryview(buf)
        pos = 0
        while pos < expected_size:
            nbytes = self.socket.recv_into(view[pos:])
            if nbytes == 0:
                raise ConnectionError("Broken connection from NDFEX")
            pos += nbytes
        return bytes(buf)

    def _recv_message(self) -> bytes:
        """Read full length-prefixed message over the wire"""
        log.info("here beofre exact")
        hdr_bytes = self._recv_exact(RESP_HDR_SIZE)
        log.info("here after exact")
        totalLength = struct.unpack_from("<H", hdr_bytes, 0)[0]
        log.info("here length exact")
        remaining = totalLength - RESP_HDR_SIZE
        if remaining < 0:
            raise ValueError("Invalid sized read from malformed packet")
        if remaining == 0:
            return hdr_bytes

        log.info("here length exact")
        return hdr_bytes + self._recv_exact(remaining)

    def _send_and_recv(self, msg: bytes) -> List[OeResponse]:
        """
        Send a packed message to NDFEX, then collect all responses

        Args:
            msg: raw bytes to send to NDFEX

        Returns:
            return responses given back from NDFEX
        """
        assert self.socket is not None
        self._send_raw(msg)

        # Block waiting for the first (mandatory) response
        self.socket.setblocking(True)
        responses: List[OeResponse] = [self._parse_response(self._recv_message())]

        # If first response is a reject or error, no more messages are coming
        if isinstance(responses[0], (OrderReject, ErrorMessage)):
            return responses

        # Non-blocking drain for any additional messages (fills, closes, etc.)
        self.socket.setblocking(False)
        try:
            while True:
                try:
                    responses.append(self._parse_response(self._recv_message()))
                except (BlockingIOError, socket.error):
                    break
        finally:
            self.socket.setblocking(True)

        return responses

    def _process_responses(self, responses: List[OeResponse]) -> None:
        """Process exchange response: update position, PnL, and check limits"""
        for resp in responses:
            if isinstance(resp, OrderReject):
                reason = RejectReason(resp.reject_reason)
                log.error(
                    "order rejected  order_id=%d  reason=%s",
                    resp.order_id,
                    reason.name,
                )
                benign = {
                    RejectReason.UNKNOWN_ORDER_ID,
                    RejectReason.DUPLICATE_ORDER_ID,
                    RejectReason.INVALID_PRICE,
                    RejectReason.INVALID_QUANTITY,
                    RejectReason.INVALID_SIDE,
                    RejectReason.RISK_REJECT,
                }
                if reason not in benign:
                    ...
                if reason == RejectReason.UNKNOWN_ORDER_ID:
                    self.open_orders.pop(resp.order_id, None)
                else:
                    raise KeyError(
                        "ORDER REJECTED order_id=%d reason=%s",
                        resp.order_id,
                        reason.name,
                    )
            elif isinstance(resp, OrderFill):
                log.info(
                    "FILL order_id=%d qty=%d price=%d flags=%s",
                    resp.order_id,
                    resp.quantity,
                    resp.price,
                    FillFlags(resp.flags).name,
                )

                # for position tracking (symbol, buy qty, sellqty)
                order_info = self.open_orders.get(resp.order_id)
                if order_info is not None:
                    symbol, side, qty, prc, filled = order_info
                    new_filled = filled + resp.quantity
                    if side == Side.BUY:
                        self.position_tracker.update_position(symbol, resp.quantity, 0)
                        self.pnl_tracker.on_fill_buy(symbol, resp.quantity, resp.price)
                    else:
                        self.position_tracker.update_position(symbol, 0, resp.quantity)
                        self.pnl_tracker.on_fill_sell(symbol, resp.quantity, resp.price)

                    if FillFlags(resp.flags) == FillFlags.CLOSED:
                        self.open_orders.pop(resp.order_id, None)
                    else:
                        self.open_orders[resp.order_id] = (
                            symbol,
                            side,
                            qty,
                            prc,
                            new_filled,
                        )

                    self._check_limits(symbol)

            elif isinstance(resp, OrderAck):
                log.info(
                    "ACK order_id=%d exch_order_id=%d",
                    resp.order_id,
                    resp.exch_order_id,
                )
            elif isinstance(resp, OrderClosed):
                log.info("CLOSE order_id=%d", resp.order_id)
                # Remove only after exchange confirmation (atomicity)
                self.open_orders.pop(resp.order_id, None)
            elif isinstance(resp, ErrorMessage):
                log.error("ERROR code=%d msg=%s", resp.error_code, resp.error_message)

    def new_order(
        self,
        order_id: int,
        symbol: int,
        side: int,
        quantity: int,
        price: int,
        flags: int = OrderFlags.NONE,
    ) -> List[OeResponse]:
        """Submit a new order after passing risk checks"""
        if order_id in self.open_orders:
            log.error(
                "DUPLICATE order_id=%d already open - rejecting locally", order_id
            )
            return [
                OrderReject(
                    header=OeResponseHeader(
                        length=OrderReject.SIZE,
                        msg_type=int(MsgType.REJECT),
                        version=OE_PROTOCOL_VERSION,
                        seq_num=0,
                        last_seq_num=self.seq_num,
                        client_id=self.client_id,
                    ),
                    order_id=order_id,
                    reject_reason=RejectReason.DUPLICATE_ORDER_ID,
                )
            ]

        # pre-trade risk check
        valid, reason = self.risk_tracker.is_valid(
            symbol,
            side,
            quantity,
            price,
            self.open_orders,
            self.position_tracker,
            self.exposure_tracker,
            self.pnl_tracker,
            self.resp_seq,
        )

        if not valid:
            log.error(
                "order rejected by risk manager order_id=%d  reason=%s",
                order_id,
                reason,
            )
            return [
                OrderReject(
                    header=OeResponseHeader(
                        length=OrderReject.SIZE,
                        msg_type=MsgType.REJECT,
                        version=OE_PROTOCOL_VERSION,
                        seq_num=self._next_seq(),
                        last_seq_num=self.seq_num - 1,
                        client_id=self.client_id,
                    ),
                    order_id=order_id,
                    reject_reason=RejectReason.RISK_REJECT,
                )
            ]

        msg = NewOrder(
            header=self._make_header(MsgType.NEW_ORDER, NewOrder.SIZE),
            order_id=order_id,
            symbol=symbol,
            side=int(side),
            quantity=quantity,
            price=price,
            flags=int(flags),
        )
        log.info(
            "SEND NEW_ORDER  order_id=%d  symbol=%d  side=%s  qty=%d  price=%d  flags=%s",
            order_id,
            symbol,
            Side(side).name,
            quantity,
            price,
            OrderFlags(flags).name,
        )
        # adding dict to keep track of positions for positionTracker in safety.py. bc otherwise we dk the positions during fills
        self.open_orders[order_id] = (
            symbol,
            side,
            quantity,
            price,
            0,
        )  # orderId mapped to (symbol, side, quantity, filled)

        responses = self._send_and_recv(msg.pack())
        self._process_responses(responses)
        return responses

    def delete_order(self, order_id: int) -> List[OeResponse]:
        """Cancel an existing order by order_id"""
        msg = DeleteOrder(
            header=self._make_header(MsgType.DELETE_ORDER, DeleteOrder.SIZE),
            order_id=order_id,
        )
        log.info("SEND DELETE_ORDER  order_id=%d", order_id)
        responses = self._send_and_recv(msg.pack())
        self._process_responses(responses)
        return responses

    def modify_order(
        self, order_id: int, side: int, quantity: int, price: int
    ) -> list[OeResponse]:
        """Modify an existing order's side, qty, and price"""

        if order_id not in self.open_orders:
            log.error("MODIFY for unknown local order_id=%d", order_id)
            return [
                OrderReject(
                    header=OeResponseHeader(
                        length=OrderReject.SIZE,
                        msg_type=int(MsgType.REJECT),
                        version=OE_PROTOCOL_VERSION,
                        seq_num=0,
                        last_seq_num=self.seq_num,
                        client_id=self.client_id,
                    ),
                    order_id=order_id,
                    reject_reason=RejectReason.UNKNOWN_ORDER_ID,
                )
            ]

        msg = ModifyOrder(
            header=self._make_header(MsgType.MODIFY_ORDER, ModifyOrder.SIZE),
            order_id=order_id,
            side=int(side),
            quantity=quantity,
            price=price,
        )
        log.info(
            "SEND MODIFY_ORDER  order_id=%d  side=%s  qty=%d  price=%d",
            order_id,
            Side(side).name,
            quantity,
            price,
        )
        responses = self._send_and_recv(msg.pack())
        self._process_responses(responses)

        if not responses:
            log.error("MODIFY oid=%d: no response received", order_id)
            return responses

        first = responses[0]
        # updating the map if modify is successful
        if isinstance(first, OrderAck) and order_id in self.open_orders:
            symbol, _, _, _, filled = self.open_orders[order_id]
            self.open_orders[order_id] = (symbol, side, quantity, price, filled)

        elif isinstance(first, OrderClosed):
            log.warning(
                "MODIFY oid=%d: received OrderClosed instead of OrderAck -> order ack partially filled beyond modify qty. Order is Now closed",
                order_id,
            )
            self.open_orders.pop(order_id, None)

        elif isinstance(first, OrderReject):
            reason = RejectReason(first.reject_reason)
            if reason == RejectReason.UNKNOWN_ORDER_ID:
                log.warning(
                    "MODIFY oid=%d: UNKNOWN ORDER ID -> order was fully filled before the modify reached the exchange, clean up open orders"
                )
                self.open_orders.pop(order_id, None)
            else:
                log.error("MODIFY oid=%d rejected: reason = %s", order_id, reason.name)
        return responses

    def immediate_or_cancel(
        self, order_id: int, symbol: int, side: int, quantity: int, price: int
    ) -> list[OeResponse]:
        """Submit an IOC order"""
        return self.new_order(
            order_id=order_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            flags=OrderFlags.IOC,
        )

    def _validate_response_header(self, hdr: OeResponseHeader) -> None:
        """Validate version, sequence monotonicity, and client_id on every response"""
        if hdr.version != OE_PROTOCOL_VERSION:
            raise ValueError(
                f"Response version mismatch: got={hdr.version} expected={OE_PROTOCOL_VERSION}"
            )
        if hdr.client_id != self.client_id:
            raise ValueError(
                f"Response client_id mismatch: got={hdr.client_id} expected={self.client_id}"
            )
        if self.resp_seq != 0 and hdr.seq_num <= self.resp_seq:
            raise ValueError(
                f"Response seq_num not monotonic: got={hdr.seq_num} last={self.resp_seq}"
            )

    def get_mid_price(self, symbol: int) -> int:
        """Reutrn current mid price form the order book, 0 if unavailable"""
        book = self.order_manager.books.get(symbol)
        if book is None:
            return 0
        best_bid: Tuple[int, int] = book.get_best_bid()
        best_ask: Tuple[int, int] = book.get_best_ask()
        if best_bid and best_ask:
            return (best_bid[0] + best_ask[0]) // 2
        elif best_bid:
            return best_bid[0]
        elif best_ask:
            return best_ask[0]
        return 0

    def get_pnl(self, symbol: int) -> float:
        """Compute current PnL for symbol"""
        position = self.position_tracker.get_position(symbol)
        mid_price = self.get_mid_price(symbol)
        return self.pnl_tracker.get_pnl()

    def cancel_all_orders(self) -> None:
        """Cancel every locally tracked open order"""
        log.info("Canceling all open orders")
        for order_id in list(self.open_orders.keys()):
            try:
                log.info(
                    f"Attempting to delete order_id={order_id} {self.open_orders[order_id]}"
                )
                self.delete_order(order_id)
                log.info("Deleted order_id=%d", order_id)
            except Exception as e:
                log.error("Failed to cancelt oid=%d: %s", order_id, e)

    def _check_limits(self, symbol: int) -> None:
        position = self.position_tracker.get_position(symbol)
        total_pnl = self.pnl_tracker.get_pnl()  # total across all symbols

        if total_pnl < self.pnl_min_val:
            log.error(
                "KILL SWITCH: total PnL %.2f below floor %.2f — cancelling all",
                total_pnl,
                self.pnl_min_val,
            )
            self.cancel_all_orders()
            # Don't SystemExit — let the strategy's own kill switch handle graceful stop
        if abs(position) > self.position_limit:
            log.error(
                "KILL SWITCH: sym=%d position=%d exceeds limit=%d — cancelling all",
                symbol,
                position,
                self.position_limit,
            )
            self.cancel_all_orders()

    def reconnect(self) -> None:
        """Re-establish TCP connection preserving position/PnL state. open_orders cleared."""
        log.warning("RECONNECT: connection lost — attempting reconnect")
        self.open_orders.clear()  # exchange dropped these; don't know state
        self.seq_num = 0
        self.resp_seq = 0
        self.session_id = 0
        for attempt in range(5):
            try:
                self._connect()
                self.login()
                log.info("RECONNECT: success on attempt %d", attempt + 1)
                return
            except Exception as exc:
                wait = 2**attempt
                log.error(
                    "RECONNECT attempt %d failed: %s — waiting %ds",
                    attempt + 1,
                    exc,
                    wait,
                )
                time.sleep(wait)
        raise ConnectionError("RECONNECT: failed after 5 attempts — giving up")

    def shutdown(self) -> None:
        """Cancel all orders and close the connection."""
        if self.socket is not None:
            try:
                self.cancel_all_orders()
            except Exception as exc:
                log.error("Error during shutdown cancel: %s", exc)
            self._close()

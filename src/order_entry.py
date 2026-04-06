#!/usr/bin/env python3

from __future__ import annotations

import logging
import socket
import struct
from typing import Optional, Dict, List, Tuple

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
)
from .safety import PositionTracker, ExposureTracker, PnLTracker, RiskTracker


# logging.basicConfig(
#     level=logging.DEBUG,
#     format="%(asctime)s  %(levelname)-8s  %(message)s",
#     handlers=[
#         logging.StreamHandler(),
#         logging.FileHandler("order_entry.log"),
#     ],
# )

log: logging.Logger = logging.getLogger("order_entry")


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
        pnl_floor: int = -10_000,
        position_cap: int = 100,
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
        self.open_orders: dict[int, tuple[int, int, int]] = {}
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
        hdr_bytes = self._recv_exact(RESP_HDR_SIZE)
        totalLength = struct.unpack_from("<H", hdr_bytes, 0)[0]
        remaining = totalLength - RESP_HDR_SIZE
        if remaining < 0:
            raise ValueError("Invalid sized read from malformed packet")
        if remaining == 0:
            return hdr_bytes
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
                    symbol, side, _ = order_info
                    if side == Side.BUY:
                        self.position_tracker.update_position(symbol, resp.quantity, 0)
                        self.pnl_tracker.on_fill_buy(symbol, resp.quantity, resp.price)
                    else:
                        self.position_tracker.update_position(symbol, 0, resp.quantity)
                        self.pnl_tracker.on_fill_sell(symbol, resp.quantity, resp.price)

                    if FillFlags(resp.flags) == FillFlags.CLOSED:
                        self.open_orders.pop(resp.order_id, None)

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
        valid, reason = self.risk_tracker.is_valid(
            symbol,
            side,
            quantity,
            price,
            self.open_orders,
            self.position_tracker,
            self.exposure_tracker,
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
        # TODO: check if this is done during _log_resposnse after get ACk or now
        self.open_orders[order_id] = (
            symbol,
            side,
            quantity,
        )  # orderId mapped to (symbol, side, quantity)

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

        # updating the map if modify is successful
        if (
            responses
            and isinstance(responses[0], OrderAck)
            and order_id in self.open_orders
        ):
            symbol, _, _ = self.open_orders[order_id]
            self.open_orders[order_id] = (
                symbol,
                side,
                quantity,
            )
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

    def get_pnl(self, symbol: int) -> float:
        """Compute current PnL for symbol"""
        position = self.position_tracker.get_position(symbol)
        mid_price = self.get_mid_price(symbol)
        return self.pnl_tracker.get_pnl(symbol, position, mid_price)

    def cancel_all_orders(self) -> None:
        """Cancel every locally tracked open order"""
        for order_id in list(self.open_orders.keys()):
            try:
                self.delete_order(order_id)
            except Exception as e:
                log.error("Failed to cancelt oid=%d: %s", order_id, e)

    def _check_limits(self, symbol: int) -> None:
        position = self.position_tracker.get_position(symbol)
        pnl = self.get_pnl(symbol)

        if pnl < self.pnl_min_val:
            log.warning(f"PnL for symbol {symbol} is below threshold: {pnl}")
            self.cancel_all_orders()
            raise SystemExit(f"PnL limit breached for symbol {symbol}. Exiting...")
        if abs(position) > self.position_limit:
            log.warning(f"Position for symbol {symbol} is above limit: {position}")
            self.cancel_all_orders()
            raise SystemExit(f"Position limit breached for symbol {symbol}. Exiting...")

    def shutdown(self) -> None:
        """Cancel all orders and close the connection."""
        if self.socket is not None:
            try:
                self.cancel_all_orders()
            except Exception as exc:
                log.error("Error during shutdown cancel: %s", exc)
            self._close()

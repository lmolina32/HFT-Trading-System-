#!/usr/bin/env python3


import logging
import socket
import struct
from order_book import OrderBookManager
from order_entry_protocol import (
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
)
from safety import PositionTracker, ExposureTracker, PnLTracker, RiskTracker
from typing import Optional, TypeAlias


logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("order_entry.log"),
    ],
)
log = logging.getLogger(__name__)


RESP_HDR_SIZE = OeResponseHeader.SIZE
order_structs: TypeAlias = (
    LoginResponse
    | OrderAck
    | OrderReject
    | OrderFill
    | OrderClosed
    | ErrorMessage
    | OeResponseHeader
)


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

    def __init__(
        self,
        order_manager: OrderBookManager,
        host: str = "192.168.13.100",
        port: int = 1234,
    ):
        self.username: bytes = b"team2"
        self.password: bytes = b"92vM31Pa"
        self.clientId: int = 2
        self.sessionId: int = 0
        self.seqNum: int = 0
        self.respSeq: int = 0
        self.host: str = host
        self.port: int = port
        self.positionTracker: PositionTracker = PositionTracker()
        self.openOrders: dict[int, tuple[int, int, int]] = {}
        self.exposureTracker: ExposureTracker = ExposureTracker()
        self.riskTracker: RiskTracker = RiskTracker()
        self.pnlTracker: PnLTracker = PnLTracker()
        self.order_manager: OrderBookManager = order_manager
        self.pnlMinVal: int = -10000
        self.positionLimit: int = 100
        self.socket: Optional[socket.socket] = None
        self._create_socket()

    def log_in(self) -> LoginResponse:
        """
        Sends Log in request to NDFEX, if succesful returns the LoginResponse and initilizes session id

        Returns:
            LoginResponse recieved from NDFEX

        Raises:
            PermissionError: if LoginStatus does not equal SUCCESS
        """
        msg = Login(
            header=self.makingRequestHeader(MsgType.LOGIN, Login.SIZE),
            username=self.username,
            password=self.password,
        )
        self.send(msg.pack())
        log.info("SEND LOGIN  username=%s  seq=%d", self.username, self.seqNum)

        resp = self.parse_response(self.receiveResponse())
        status = LoginStatus(resp.status)
        if status != LoginStatus.SUCCESS:
            self.handle_log_in_error(status)
            raise PermissionError("couldnt login...")
        self.sessionId = resp.session_id
        log.info("Login Success: session_id=%d", self.sessionId)
        return resp

    def parse_response(self, data: bytes) -> order_structs:
        """
        Parse data packet recieved from NDFEX and unpack into appropriate struct

        Args:
            data: Raw bytes from TCP connection

        Returns:
            Unpacked struct that matches MsgType
        """
        hdr = OeResponseHeader.unpack(data)
        self.respSeq = hdr.seq_num
        msgType = MsgType(hdr.msg_type)
        log.info("RECV %s  seq=%d", msgType.name, hdr.seq_num)

        if msgType == MsgType.LOGIN_RESPONSE:
            return LoginResponse.unpack(data)
        elif msgType == MsgType.ACK:
            return OrderAck.unpack(data)
        elif msgType == MsgType.REJECT:
            return OrderReject.unpack(data)
        elif msgType == MsgType.FILL:
            return OrderFill.unpack(data)
        elif msgType == MsgType.CLOSE:
            return OrderClosed.unpack(data)
        elif msgType == MsgType.ERROR:
            return ErrorMessage.unpack(data)
        else:
            return hdr

    def makingRequestHeader(self, msgType: MsgType, length: int) -> OeRequestHeader:
        """Creates OeRequestHeader given specified msgType and length"""
        return OeRequestHeader(
            length=length,
            msg_type=int(msgType),
            version=OE_PROTOCOL_VERSION,
            seq_num=self.nxtSeq(),
            client_id=self.clientId,
            session_id=self.sessionId,
        )

    def send(self, data: bytes) -> None:
        """Send Raw order structs over the wire"""
        log.debug("SEND (%d bytes): %s", len(data), data.hex())
        self.socket.sendall(data)

    def nxtSeq(self) -> int:
        """Update and return clients sequence counter"""
        self.seqNum += 1
        return self.seqNum

    def _recv_exact(self, expected_size: int) -> bytes:
        """Listen over the wire until receives a packet of the expected size"""
        buf = b""
        while len(buf) < expected_size:
            chunk = self.socket.recv(expected_size - len(buf))
            if not chunk:
                raise ConnectionError("Broken connection from NDFEX")
            buf += chunk
        return buf

    def receiveResponse(self) -> bytes:
        """Read full length-prefixed message over the wire"""
        buffer = self._recv_exact(RESP_HDR_SIZE)
        totalLength = struct.unpack_from("<H", buffer, 0)[0]
        remaining = totalLength - RESP_HDR_SIZE

        if remaining < 0:
            raise ValueError("Invalid sized read from malformed packet")

        fullMsg = buffer + (self._recv_exact(remaining) if remaining else b"")
        log.debug("RECV (%d bytes): %s", len(fullMsg), fullMsg.hex())
        return fullMsg

    def sendAndRecv(self, msg: bytes) -> list[order_structs]:
        """
        Send a packed message to NDFEX, then collect all responses

        Args:
            msg: raw bytes to send to NDFEX

        Returns:
            return responses given back from NDFEX
        """
        self.send(msg)

        # Block waiting for the first (mandatory) response
        self.socket.setblocking(True)
        responses = [self.parse_response(self.receiveResponse())]

        # If first response is a reject or error, no more messages are coming
        if isinstance(responses[0], (OrderReject, ErrorMessage)):
            return responses

        # Non-blocking drain for any additional messages (fills, closes, etc.)
        self.socket.setblocking(False)
        try:
            while True:
                try:
                    responses.append(self.parse_response(self.receiveResponse()))
                except (BlockingIOError, socket.error):
                    break
        finally:
            self.socket.setblocking(True)

        return responses

    def handle_order_error(self, resp):
        reason = RejectReason(resp.reject_reason)
        log.error(
            "order rejected </3:  order_id = %d  reason = %s",
            resp.order_id,
            reason.name,
        )

    def handle_log_in_error(self, status):
        log.error("login failed </3:  status=%s", status.name)

    def _log_responses(self, responses):
        for resp in responses:
            if isinstance(resp, OrderReject):
                self.handle_order_error(resp)
            elif isinstance(resp, OrderFill):
                log.info(
                    "FILL order_id=%d qty=%d price=%d flags=%s",
                    resp.order_id,
                    resp.quantity,
                    resp.price,
                    FillFlags(resp.flags).name,
                )

                # for position tracking (symbol, buy qty, sellqty)
                order = self.openOrders.get(resp.order_id)
                if order:
                    symbol, side, qty = order
                    if side == Side.BUY:
                        self.positionTracker.updatePosition(
                            symbol, resp.quantity, 0
                        )  # position tracking. (resp.quantity and not actual quantity in the case that it is a partial fill)
                        self.pnlTracker.whenFillBuy(
                            symbol, resp.quantity, resp.price
                        )  # pnl tracking
                    else:
                        self.positionTracker.updatePosition(
                            symbol, 0, resp.quantity
                        )  # position
                        self.pnlTracker.whenFillSell(
                            symbol, resp.quantity, resp.price
                        )  # pnl

                    if FillFlags(resp.flags) == FillFlags.CLOSED:
                        self.openOrders.pop(
                            resp.order_id, None
                        )  # remove order from openOrders dict when fully filled

                    self.check(symbol)  # the check

            elif isinstance(resp, OrderAck):
                log.info(
                    "ACK order_id=%d exch_order_id=%d",
                    resp.order_id,
                    resp.exch_order_id,
                )
            elif isinstance(resp, OrderClosed):
                log.info("CLOSE order_id=%d", resp.order_id)
                self.openOrders.pop(
                    resp.order_id, None
                )  # remove order from openOrders dict when deleted
                ## adding this here for atomicity; removing only once exchange confirms that it is gone. otherwise in cancel order fnctn it u might have issues i think
            elif isinstance(resp, ErrorMessage):
                log.error("ERROR code=%d msg=%s", resp.error_code, resp.error_message)

    def new_order(self, orderId, symbol, side, quantity, price, flags=OrderFlags.NONE):
        valid, reason = self.riskTracker.isValid(
            symbol,
            side,
            quantity,
            price,
            self.openOrders,
            self.positionTracker,
            self.exposureTracker,
            self.respSeq,
        )

        if not valid:
            log.error(
                "order rejected by risk manager </3 nooo rip:  order_id = %d  reason = %s",
                orderId,
                reason,
            )
            return [
                OrderReject(
                    header=self.makingRequestHeader(MsgType.REJECT, OrderReject.SIZE),
                    order_id=orderId,
                    reject_reason=RejectReason.RISK_REJECT,
                )
            ]

        msg = NewOrder(
            header=self.makingRequestHeader(MsgType.NEW_ORDER, NewOrder.SIZE),
            order_id=orderId,
            symbol=symbol,
            side=int(side),
            quantity=quantity,
            price=price,
            flags=int(flags),
        )
        log.info(
            "SEND NEW_ORDER  order_id=%d  symbol=%d  side=%s  qty=%d  price=%d  flags=%s",
            orderId,
            symbol,
            Side(side).name,
            quantity,
            price,
            OrderFlags(flags).name,
        )
        # adding dict to keep track of positions for positionTracker in safety.py. bc otherwise we dk the positions during fills
        self.openOrders[orderId] = (
            symbol,
            side,
            quantity,
        )  # orderId mapped to (symbol, side, quantity)

        responses = self.sendAndRecv(msg.pack())
        self._log_responses(responses)
        return responses

    def delete_order(self, orderId):
        msg = DeleteOrder(
            header=self.makingRequestHeader(MsgType.DELETE_ORDER, DeleteOrder.SIZE),
            order_id=orderId,
        )
        log.info("SEND DELETE_ORDER  order_id=%d", orderId)
        responses = self.sendAndRecv(msg.pack())
        self._log_responses(responses)

        return responses

    def modify_order(self, orderId, side, quantity, price):
        msg = ModifyOrder(
            header=self.makingRequestHeader(MsgType.MODIFY_ORDER, ModifyOrder.SIZE),
            order_id=orderId,
            side=int(side),
            quantity=quantity,
            price=price,
        )
        log.info(
            "SEND MODIFY_ORDER  order_id=%d  side=%s  qty=%d  price=%d",
            orderId,
            Side(side).name,
            quantity,
            price,
        )
        responses = self.sendAndRecv(msg.pack())
        self._log_responses(responses)

        # updating the map if modify is successful (ie if we get an ack and not a reject)
        if (
            isinstance(responses[0], OrderAck)
            and responses[0].order_id in self.openOrders
        ):
            symbol, _, _ = self.openOrders.get(orderId)
            self.openOrders[orderId] = (
                symbol,
                side,
                quantity,
            )  # update order in openOrders dict when modified successfully
        return responses

    def immediate_or_cancel(self, orderId, symbol, side, quantity, price):
        return self.new_order(
            orderId=orderId,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            flags=OrderFlags.IOC,
        )

    # adding for pnl
    def getCurrentMarket(self, symbol):
        book = self.order_manager.books.get(symbol)
        if book:
            best_bid = book.get_best_bid()
            best_ask = book.get_best_ask()
            if best_bid and best_ask:
                return (best_bid[0] + best_ask[0]) // 2  # mid price
            elif best_bid:
                return best_bid[0]
            elif best_ask:
                return best_ask[0]
        return 0  # if dne yet

    def getPnL(self, symbol):
        position = self.positionTracker.symbolPosition.get(symbol, 0)
        currentMarketPrice = self.getCurrentMarket(symbol)
        return self.pnlTracker.getPnL(symbol, position, currentMarketPrice)

    def cancelAllOrders(self):  # he talked ab diff methods for this in class ??
        for order in list(self.openOrders.keys()):
            self.delete_order(order)

    def check(self, symbol):
        position = self.positionTracker.symbolPosition.get(symbol, 0)
        pnl = self.getPnL(symbol)

        if pnl is not None and pnl < self.pnlMinVal:
            log.warning(f"PnL for symbol {symbol} is below threshold: {pnl}")
            self.cancelAllOrders()
            raise SystemExit(f"PnL limit breached for symbol {symbol}. Exiting...")
        if position is not None and abs(position) > self.positionLimit:
            log.warning(f"Position for symbol {symbol} is above limit: {position}")
            self.cancelAllOrders()
            raise SystemExit(f"Position limit breached for symbol {symbol}. Exiting...")

    def _create_socket(self) -> None:
        self._close_socket()
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        try:
            self.socket.connect((self.host, self.port))
            log.info(f"Succesful connection to {self.host}:{self.port}")
        except Exception as e:
            log.info(f"{e}")
            self._close_socket()

    def _close_socket(self) -> None:
        if self.socket is not None:
            self.cancelAllOrders()
            try:
                self.socket.shutdown(self.socket.SHUT_RDWR)
            except Exception:
                pass
            finally:
                self.socket.close()
                self.socket = None


"""
def main():
    client = OrderEntryClient()
    client.log_in()

    while True:


        try:
            line = input("> ").strip()
        except EOFError:
            break
        if not line:
            continue

        parts = line.split()
        cmd = parts[0].lower()

        try:
            if cmd == "buy":
                _, oid, sym, qty, price = parts
                client.new_order(int(oid), int(sym), Side.BUY, int(qty), int(price))
            elif cmd == "sell":
                _, oid, sym, qty, price = parts
                client.new_order(int(oid), int(sym), Side.SELL, int(qty), int(price))
            elif cmd == "del":
                _, oid = parts
                client.delete_order(int(oid))
            elif cmd == "mod":
                _, oid, side, qty, price = parts
                s = Side.BUY if side.lower() == "buy" else Side.SELL
                client.modify_order(int(oid), s, int(qty), int(price))
            elif cmd == "ioc":
                _, oid, sym, side, qty, price = parts
                s = Side.BUY if side.lower() == "buy" else Side.SELL
                client.immediate_or_cancel(int(oid), int(sym), s, int(qty), int(price))
            elif cmd == "quit":
                break
            else:
                print(f"unknown command: {cmd}")
        except (ValueError, TypeError) as e:
            print(f"bad input: {e}")


if __name__ == "__main__":
    main()

"""

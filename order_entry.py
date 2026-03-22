#!/usr/bin/env python3


import logging
import socket
import struct
from order_entry_protocol import (
    OE_PROTOCOL_VERSION, MsgType, RejectReason, LoginStatus, OrderFlags, FillFlags, Side,
    OeRequestHeader, OeResponseHeader, Login, LoginResponse, NewOrder, DeleteOrder,
    ModifyOrder, OrderAck, OrderReject, OrderFill, OrderClosed, ErrorMessage,
)

from safety import positionTracker, exposureTracker, pnlTracker, riskTracker, cancelAllOrders


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


class OrderEntryClient:
    def __init__(self, order_manager=None):
        self.username = b"team2"
        self.password = b"92vM31Pa"
        self.clientId = 2

        self.sessionId = 0  # exchange assigns this when u login
        self.seqNum = 0     # outbound sequence num
        self.respSeq = 0    # last exchange seq number seen
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.connect(("192.168.13.100", 1234))
        log.info("Connected to 192.168.13.100:1234")

        self.positionTracker = positionTracker() # added during hw3, for position tracking
        self.openOrders = {}

        # adding to synchronize it all in main.py
        self.pnlTracker = pnlTracker() # for pnl tracking
        self.order_manager = order_manager

        self.pnlMinVal = -10000 
        self.positionLimit = 100 # change these as needed ^^ same w the error checking in safety.py

    def log_in(self):
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
        log.info("LOGIN SUCCESS !! :)  session_id=%d", self.sessionId)
        return resp

    def parse_response(self, data):
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

    def makingRequestHeader(self, msgType, lengthh):
        return OeRequestHeader(
            length=lengthh,
            msg_type=int(msgType),
            version=OE_PROTOCOL_VERSION,
            seq_num=self.nxtSeq(),
            client_id=self.clientId,
            session_id=self.sessionId,
        )

    def send(self, data):
        log.debug("SEND (%d bytes): %s", len(data), data.hex())
        self.socket.sendall(data)

    def nxtSeq(self):
        self.seqNum += 1
        return self.seqNum

    def receiveResponse(self):
        """Read one length-prefixed message."""
        def recv_exact(n):
            buf = b""
            while len(buf) < n:
                chunk = self.socket.recv(n - len(buf))
                if not chunk:
                    raise ConnectionError("no more connection!!")
                buf += chunk
            return buf

        buffer = recv_exact(RESP_HDR_SIZE)
        totalLength = struct.unpack_from("<H", buffer, 0)[0]
        remaining = totalLength - RESP_HDR_SIZE

        if remaining < 0:
            raise ValueError("wack message length")

        fullMsg = buffer + (recv_exact(remaining) if remaining else b"")
        log.debug("RECV (%d bytes): %s", len(fullMsg), fullMsg.hex())
        return fullMsg

    def sendAndRecv(self, msg):
        """Send a packed message then collect all responses."""
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
        log.error("order rejected </3:  order_id = %d  reason = %s", resp.order_id, reason.name)

    def handle_log_in_error(self, status):
        log.error("login failed </3:  status=%s", status.name)

    def _log_responses(self, responses):
        for resp in responses:
            if isinstance(resp, OrderReject):
                self.handle_order_error(resp)
            elif isinstance(resp, OrderFill):
                log.info("FILL order_id=%d qty=%d price=%d flags=%s",
                         resp.order_id, resp.quantity, resp.price, FillFlags(resp.flags).name)
                
                # for position tracking (symbol, buy qty, sellqty)
                order =  self.openOrders.get(resp.order_id)
                if order:
                    symbol, side, qty = order
                    if side == Side.BUY:
                        self.positionTracker.updatePosition(symbol, resp.quantity, 0) # position tracking. (resp.quantity and not actual quantity in the case that it is a partial fill)
                        self.pnlTracker.whenFillBuy(symbol, resp.quantity, resp.price) # pnl tracking
                    else:
                        self.positionTracker.updatePosition(symbol, 0, resp.quantity) # position
                        self.pnlTracker.whenFillSell(symbol, resp.quantity, resp.price) # pnl

                    if FillFlags(resp.flags) == FillFlags.CLOSED:
                        self.openOrders.pop(resp.order_id, None) # remove order from openOrders dict when fully filled

                    self.check(symbol) # the check

            elif isinstance(resp, OrderAck):
                log.info("ACK order_id=%d exch_order_id=%d", resp.order_id, resp.exch_order_id)
            elif isinstance(resp, OrderClosed):
                log.info("CLOSE order_id=%d", resp.order_id)
                self.openOrders.pop(resp.order_id, None) # remove order from openOrders dict when deleted
                ## adding this here for atomicity; removing only once exchange confirms that it is gone. otherwise in cancel order fnctn it u might have issues i think
            elif isinstance(resp, ErrorMessage):
                log.error("ERROR code=%d msg=%s", resp.error_code, resp.error_message)

    def new_order(self, orderId, symbol, side, quantity, price, flags=OrderFlags.NONE):
        valid, reason = riskTracker.isValid(orderId, symbol, side, quantity, price, self.openOrders, self.positionTracker, self.exposureTracker, self.respSeq)
        if not valid:
            log.error("order rejected by risk manager </3 nooo rip:  order_id = %d  reason = %s", orderId, reason)
            return [OrderReject(
                header=self.makingRequestHeader(MsgType.REJECT, OrderReject.SIZE),
                order_id=orderId,
                reject_reason=RejectReason.RISK_REJECT,
            )]

        
        msg = NewOrder(
            header=self.makingRequestHeader(MsgType.NEW_ORDER, NewOrder.SIZE),
            order_id=orderId,
            symbol=symbol,
            side=int(side),
            quantity=quantity,
            price=price,
            flags=int(flags),
        )
        log.info("SEND NEW_ORDER  order_id=%d  symbol=%d  side=%s  qty=%d  price=%d  flags=%s",
                 orderId, symbol, Side(side).name, quantity, price, OrderFlags(flags).name)
        # adding dict to keep track of positions for positionTracker in safety.py. bc otherwise we dk the positions during fills
        self.openOrders[orderId] = (symbol, side, quantity) # orderId mapped to (symbol, side, quantity)

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
        log.info("SEND MODIFY_ORDER  order_id=%d  side=%s  qty=%d  price=%d",
                 orderId, Side(side).name, quantity, price)
        responses = self.sendAndRecv(msg.pack())
        self._log_responses(responses)

        # updating the map if modify is successful (ie if we get an ack and not a reject)
        if isinstance(responses[0], OrderAck) and responses[0].order_id in self.openOrders:
            symbol, _, _ = self.openOrders.get(orderId)
            self.openOrders[orderId] = (symbol, side, quantity) # update order in openOrders dict when modified successfully
        return responses

    def immediate_or_cancel(self, orderId, symbol, side, quantity, price):
        return self.new_order(
            orderId=orderId, symbol=symbol, side=side,
            quantity=quantity, price=price, flags=OrderFlags.IOC,
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
        return 0 # if dne yet

    def getPnL(self, symbol):
        position = self.positionTracker.symbolPosition.get(symbol, 0)
        currentMarketPrice = self.getCurrentMarket(symbol)
        return self.pnlTracker.getPnL(symbol, position, currentMarketPrice)

    def cancelAllOrders(self):
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


'''
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

'''
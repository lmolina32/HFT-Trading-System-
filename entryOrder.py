#!/usr/bin/env python3


import logging
import socket
import struct
import sys
from order_entry_protocol import (
    OE_PROTOCOL_VERSION, MsgType, RejectReason, LoginStatus, OrderFlags, FillFlags, Side, OeRequestHeader, OeResponseHeader, Login, LoginResponse, NewOrder, DeleteOrder, ModifyOrder, OrderAck, OrderReject, OrderFill, OrderClosed, ErrorMessage,
)

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
    def __init__(self):
        self.username = b"team2"
        self.password = b"92vM31Pa"
        self.clientId = 2

        self.sessionId = 0 # exchange assigns this when u login
        self.seqNum = 0 # outbound sequence num
        self.respSeq = 0 # this is the last exchange seq number seen
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.connect(("192.168.13.100", 1234))
        log.info("Connected to 192.168.13.100:1234")

    def log_in(self):
        msg = Login(
            header = self.makingRequestHeader(MsgType.LOGIN, Login.SIZE),
            username = self.username,
            password = self.password
        )
        self.send(msg.pack())
        log.info("SEND LOGIN  username=%s  seq=%d", self.username, self.seqNum)

        rawResp = self.receiveResponse()
        resp = self.parse_response(rawResp)

        status = LoginStatus(resp.status)
        if status != LoginStatus.SUCCESS:
            self.handle_log_in_error(status)
            raise PermissionError("couldnt login...")
        self.sessionId = resp.session_id
        log.info("LOGIN SUCCESS  session_id=%d", self.sessionId)
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
            length = lengthh,
            msg_type = int(msgType),
            version = OE_PROTOCOL_VERSION,
            seq_num = self.nxtSeq(),
            client_id = self.clientId,
            session_id = self.sessionId
        )
    def send(self, data):
        log.debug("SEND (%d bytes): %s", len(data), data.hex())
        self.socket.sendall(data)


    def nxtSeq(self):
        self.seqNum += 1
        return self.seqNum

    def recv_response(self, n):
        buffer = b""

        while len(buffer) < n:
            packetChunk = self.socket.recv(n - len(buffer))
            if not packetChunk:
                raise ConnectionError("no more connection!!")
            buffer += packetChunk
        return buffer

    def receiveResponse(self):
        buffer = self.recv_response(RESP_HDR_SIZE)
        totalLength = struct.unpack_from("<H", buffer, 0)[0] # come back and reunderstand syntax here
        remaining = totalLength - RESP_HDR_SIZE

        if remaining < 0:
            raise ValueError("wack message length")

        rawBody = self.recv_response(remaining) if remaining else b"" # get what is left
        fullMsg = buffer + rawBody
        log.debug("RECV (%d bytes): %s", len(fullMsg), fullMsg.hex())
        return fullMsg


    def sendAndRecv(self):
        responses = []

        # Block waiting for the FIRST (mandatory) response
        self.socket.setblocking(True)
        raw = self.receiveResponse()
        resp = self.parse_response(raw)
        responses.append(resp)

        # Now non-blocking drain for any additional messages (fills, etc.)
        self.socket.setblocking(False)
        try:
            while True:
                try:
                    raw = self.receiveResponse()
                    resp = self.parse_response(raw)
                    responses.append(resp)
                except (BlockingIOError, socket.error):
                    break
        finally:
            self.socket.setblocking(True)

        return responses[-1] if responses else None




    def handle_order_error(self, resp):
        reason = RejectReason(resp.reject_reason)
        log.error("ORDER REJECTED  order_id=%d  reason=%s", resp.order_id, reason.name)

    def handle_log_in_error(self, status):
        log.error("LOGIN FAILED  status=%s", status.name)

    def new_order(self, orderId, symbol, side, quantity, price, flags=OrderFlags.NONE):
        msg = NewOrder(
            header   = self.makingRequestHeader(MsgType.NEW_ORDER, NewOrder.SIZE),
            order_id = orderId,
            symbol   = symbol,
            side     = int(side),
            quantity = quantity,
            price    = price,
            flags    = int(flags),
        )
        self.send(msg.pack())
        log.info("SEND NEW_ORDER  order_id=%d  symbol=%d  side=%s  qty=%d  price=%d  flags=%s",
                 orderId, symbol, Side(side).name, quantity, price, OrderFlags(flags).name)
        return self.sendAndRecv()

    def send_order(self, orderId, symbol, side, quantity, price, flags: OrderFlags = OrderFlags.NONE):
        return self.new_order(orderId, symbol, side, quantity, price, flags)


    def delete_order(self, orderId):
        msg = DeleteOrder(
            header = self.makingRequestHeader(MsgType.DELETE_ORDER, DeleteOrder.SIZE),
            order_id = orderId
        )
        self.send(msg.pack())
        log.info("SEND DELETE_ORDER  order_id=%d", orderId)
        return self.sendAndRecv()

    def modify_order(self, orderId, side, quantity, price):
        msg = ModifyOrder(
            header = self.makingRequestHeader(MsgType.MODIFY_ORDER, ModifyOrder.SIZE),
            order_id = orderId,
            side = int(side),
            quantity = quantity,
            price = price,
        )
        self.send(msg.pack())
        log.info("SEND MODIFY_ORDER  order_id=%d  side=%s  qty=%d  price=%d",
                 orderId, Side(side).name, quantity, price)
        return self.sendAndRecv()

    def immediate_or_cancel(self, orderId, symbol, side, quantity, price):
        return self.new_order(orderId = orderId, symbol = symbol, side = side, quantity = quantity, price = price, flags = OrderFlags.IOC)


def main():

    client = OrderEntryClient()
    client.log_in()

    orderId = 1  # hardcoded

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
#!/usr/bin/env python3

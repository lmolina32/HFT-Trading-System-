#!/usr/bin/env python3

import math
import time
from order_entry_protocol import Side


class positionTracker:
    def __init__(self):
        self.symbolPosition = {}

    def updatePosition(self, symbol, buy, sell):
        self.symbolPosition[symbol] = self.symbolPosition.get(symbol, 0) + buy - sell


class exposureTracker:
    def buyExposure(self, symbol, openOrders, position):
        outstandingBuys = 0
        for orderId, (sym, side, qty) in openOrders.items():
            if sym == symbol and side == Side.BUY:
                outstandingBuys += qty
        return outstandingBuys + position

    def sellExposure(self, symbol, openOrders, position):
        outstandingSells = 0
        for orderId, (sym, side, qty) in openOrders.items():
            if sym == symbol and side == Side.SELL:
                outstandingSells += qty
        return outstandingSells + position


class pnlTracker:
    def __init__(self):
        self.totalSells = {}
        self.avgSellPrice = {}
        self.totalBuys = {}
        self.avgBuyPrice = {}

    def whenFillBuy(self, symbol, quantity, price):
        totalCost = self.avgBuyPrice.get(symbol, 0) * self.totalBuys.get(symbol, 0)
        totalCost += quantity * price
        self.totalBuys[symbol] = self.totalBuys.get(symbol, 0) + quantity
        self.avgBuyPrice[symbol] = totalCost / self.totalBuys[symbol]

    def whenFillSell(self, symbol, quantity, price):
        totalRevenue = self.avgSellPrice.get(symbol, 0) * self.totalSells.get(symbol, 0)
        totalRevenue += quantity * price
        self.totalSells[symbol] = self.totalSells.get(symbol, 0) + quantity
        self.avgSellPrice[symbol] = totalRevenue / self.totalSells[symbol]
    
    def getPnL(self, symbol, position, currentMarketPrice):
        buyCost = self.avgBuyPrice.get(symbol, 0) * self.totalBuys.get(symbol, 0)
        sellRevenue = self.avgSellPrice.get(symbol, 0) * self.totalSells.get(symbol, 0)
        return sellRevenue - buyCost + (currentMarketPrice * position) # this is to make it tick to market?


class riskTracker:
    def __init__(self):
        self.maxQtyOrder = 1000
        self.maxQtySide = 500
        self.maxExposure = 1000
        self.maxOrdersPerSecond = 10
        self.maxPerSequence = 1000
        self.maxUnackedOrders = 5
        self.positionLimit = 1000
        # anything else you can think of?

        # states for rate limiting ??
        self.ordersThisSecond = 0
        self.lastSecondTime = None
        self.ordersThisSeqNum = 0
        self.lastSeqNum = None

    def isValid(self, symbol, side, quantity, price, openOrders, positionTracker, exposureTracker, currentSeqNum):

        if quantity > self.maxQtyOrder:
            return False, f"Order quantity {quantity} exceeds maximum allowed {self.maxQtyOrder}"

        if quantity > self.maxQtySide:
            return False, f"Order quantity {quantity} exceeds maximum allowed per side {self.maxQtySide}"

        if side == Side.BUY:
            exposure = exposureTracker.buyExposure(symbol, openOrders, positionTracker.symbolPosition.get(symbol, 0))
        else:
            exposure = exposureTracker.sellExposure(symbol, openOrders, positionTracker.symbolPosition.get(symbol, 0))
        if exposure + quantity > self.maxExposure:
            return False, f"Order would exceed maximum exposure of {self.maxExposure} for symbol {symbol}"

        if price <= 0: # is this invalid price? anything else?
            return False, "Order price cannot be negative"

        if abs(positionTracker.symbolPosition.get(symbol, 0)) >= self.positionLimit:
            return False, f"Order would exceed position limit of {self.positionLimit} for symbol {symbol}"


        rn = time.time()
        if self.lastSecondTime is None or rn - self.lastSecondTime >= 1:
            self.ordersThisSecond = 0 # reset counter if a second has passed
            self.lastSecondTime = rn # update last 'tracked' second to rn
        self.ordersThisSecond += 1
        if self.ordersThisSecond > self.maxOrdersPerSecond:
            return False, f"exceeded maximum orders per second {self.maxOrdersPerSecond}"


        if currentSeqNum != self.lastSeqNum:
            self.ordersThisSeqNum = 0 # reset counter if it is a new sequence number
            self.lastSeqNum = currentSeqNum # update last sequence number to this current one
        self.ordersThisSeqNum += 1
        if self.ordersThisSeqNum > self.maxPerSequence:
            return False, f"Order quantity {quantity} exceeds maximum per sequence {self.maxPerSequence}"

        if len(openOrders) >= self.maxUnackedOrders:
            return False, f"Number of unacknowledged orders {len(openOrders)} exceeds maximum allowed {self.maxUnackedOrders}"

        return True, None





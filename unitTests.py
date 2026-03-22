#!/usr/bin/env python3

import time
from order_entry_protocol import Side
from safety import positionTracker, exposureTracker, pnlTracker, riskTracker


def run_test(name, condition, detail=""):
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}" + (f": {detail}" if detail else ""))


def test_position_tracker():
    print("\n--- positionTracker ---")
    pt = positionTracker()

    run_test("initial position is zero", pt.symbolPosition.get(1, 0) == 0)

    pt.updatePosition(1, 10, 0)
    run_test("buy increases position", pt.symbolPosition[1] == 10)

    pt2 = positionTracker()
    pt2.updatePosition(1, 0, 5)
    run_test("sell decreases position", pt2.symbolPosition[1] == -5)

    pt3 = positionTracker()
    pt3.updatePosition(1, 10, 0)
    pt3.updatePosition(1, 0, 4)
    run_test("buy then sell", pt3.symbolPosition[1] == 6)

    pt4 = positionTracker()
    pt4.updatePosition(1, 5, 0)
    pt4.updatePosition(1, 5, 0)
    run_test("partial fills accumulate", pt4.symbolPosition[1] == 10)

    pt5 = positionTracker()
    pt5.updatePosition(1, 10, 0)
    pt5.updatePosition(2, 0, 5)
    run_test("multiple symbols are independent",
             pt5.symbolPosition[1] == 10 and pt5.symbolPosition[2] == -5)

    pt6 = positionTracker()
    pt6.updatePosition(1, 10, 0)
    pt6.updatePosition(1, 0, 10)
    run_test("flat position after buy and sell", pt6.symbolPosition[1] == 0)


def test_exposure_tracker():
    print("\n--- exposureTracker ---")
    et = exposureTracker()

    run_test("buy exposure with no orders or position", et.buyExposure(1, {}, 0) == 0)
    run_test("buy exposure with position only", et.buyExposure(1, {}, 10) == 10)

    openOrders = {101: (1, Side.BUY, 20)}
    run_test("buy exposure with open buy orders", et.buyExposure(1, openOrders, 0) == 20)
    run_test("buy exposure position plus orders", et.buyExposure(1, openOrders, 10) == 30)

    run_test("sell exposure with no orders", et.sellExposure(1, {}, 0) == 0)

    openSell = {101: (1, Side.SELL, 15)}
    run_test("sell exposure with open sell orders", et.sellExposure(1, openSell, 0) == 15)
    run_test("sell orders dont affect buy exposure", et.buyExposure(1, openSell, 0) == 0)

    wrongSymbol = {101: (2, Side.BUY, 50)}
    run_test("different symbol is ignored", et.buyExposure(1, wrongSymbol, 0) == 0)


def test_pnl_tracker():
    print("\n--- pnlTracker ---")
    pt = pnlTracker()

    run_test("initial pnl is zero", pt.getPnL(1, 0, 100) == 0)

    pt.whenFillBuy(1, 10, 100)
    run_test("buy fill updates avg price", abs(pt.avgBuyPrice[1] - 100) < 0.001)
    run_test("buy fill updates total", pt.totalBuys[1] == 10)

    pt2 = pnlTracker()
    pt2.whenFillSell(1, 10, 110)
    run_test("sell fill updates avg price", abs(pt2.avgSellPrice[1] - 110) < 0.001)
    run_test("sell fill updates total", pt2.totalSells[1] == 10)

    pt3 = pnlTracker()
    pt3.whenFillBuy(1, 10, 100)
    pt3.whenFillBuy(1, 10, 120)
    run_test("weighted avg buy price", abs(pt3.avgBuyPrice[1] - 110) < 0.001)

    pt4 = pnlTracker()
    pt4.whenFillSell(1, 10, 100)
    pt4.whenFillSell(1, 10, 120)
    run_test("weighted avg sell price", abs(pt4.avgSellPrice[1] - 110) < 0.001)

    pt5 = pnlTracker()
    pt5.whenFillBuy(1, 10, 100)
    pt5.whenFillSell(1, 10, 110)
    run_test("pnl profit when sell > buy", abs(pt5.getPnL(1, 0, 0) - 100) < 0.001)

    pt6 = pnlTracker()
    pt6.whenFillBuy(1, 10, 100)
    # bought 10 @ 100, position=10, market=105 -> pnl = -1000 + 1050 = 50
    run_test("mark to market long position", abs(pt6.getPnL(1, 10, 105) - 50) < 0.001)

    pt7 = pnlTracker()
    pt7.whenFillSell(1, 10, 100)
    # sold 10 @ 100, position=-10, market=90 -> pnl = 1000 + (-10*90) = 100
    run_test("mark to market short position", abs(pt7.getPnL(1, -10, 90) - 100) < 0.001)


def test_risk_tracker():
    print("\n--- riskTracker ---")

    def make():
        rt = riskTracker()
        pt = positionTracker()
        et = exposureTracker()
        return rt, pt, et

    def check(rt, pt, et, openOrders={}, symbol=1, side=Side.BUY, quantity=10, price=100, seqNum=1):
        return rt.isValid(symbol, side, quantity, price, openOrders, pt, et, seqNum)

    # a) max qty per order
    rt, pt, et = make()
    ok, _ = check(rt, pt, et, quantity=rt.maxQtyOrder + 1)
    run_test("a) exceeds max qty per order is rejected", not ok)

    rt2, pt2, et2 = make()
    ok2, _ = check(rt2, pt2, et2, quantity=rt2.maxQtySide)  # use maxQtySide since it's the lower limit
    run_test("a) at max qty per order is accepted", ok2)

    # b) max qty per side
    rt, pt, et = make()
    ok, _ = check(rt, pt, et, quantity=rt.maxQtySide + 1)
    run_test("b) exceeds max qty per side is rejected", not ok)

    # c) max exposure
    rt, pt, et = make()
    pt.symbolPosition[1] = rt.maxExposure
    ok, _ = check(rt, pt, et, quantity=1)
    run_test("c) exceeds max exposure is rejected", not ok)

    rt2, pt2, et2 = make()
    openOrders = {101: (1, Side.BUY, rt2.maxExposure)}
    ok2, _ = check(rt2, pt2, et2, openOrders=openOrders, quantity=1)
    run_test("c) open orders push over exposure limit", not ok2)

    # d) invalid price
    rt, pt, et = make()
    ok, _ = check(rt, pt, et, price=0)
    run_test("d) zero price is rejected", not ok)
    rt2, pt2, et2 = make()
    ok2, _ = check(rt2, pt2, et2, price=-1)
    run_test("d) negative price is rejected", not ok2)
    rt3, pt3, et3 = make()
    ok3, _ = check(rt3, pt3, et3, price=1)
    run_test("d) valid price is accepted", ok3)

    # e) position limit
    rt, pt, et = make()
    pt.symbolPosition[1] = rt.positionLimit
    ok, _ = check(rt, pt, et, quantity=1)
    run_test("e) at position limit is rejected", not ok)
    rt2, pt2, et2 = make()
    pt2.symbolPosition[1] = rt2.positionLimit - 1
    ok2, _ = check(rt2, pt2, et2, quantity=1)
    run_test("e) below position limit is accepted", ok2)

    # f) orders per second
    rt, pt, et = make()
    for _ in range(rt.maxOrdersPerSecond):
        check(rt, pt, et)
    ok, _ = check(rt, pt, et)
    run_test("f) exceeds orders per second is rejected", not ok)
    rt.lastSecondTime = time.time() - 2  # force reset
    ok2, _ = check(rt, pt, et)
    run_test("f) counter resets after 1 second", ok2)

    # g) orders per seq num
    rt, pt, et = make()
    for _ in range(rt.maxPerSequence):
        check(rt, pt, et, seqNum=1)
    ok, _ = check(rt, pt, et, seqNum=1)
    run_test("g) exceeds orders per seq num is rejected", not ok)
    rt.lastSecondTime = time.time() - 2  # reset rate limiter too so it doesn't interfere
    ok2, _ = check(rt, pt, et, seqNum=2)
    run_test("g) new seq num resets counter", ok2)

    # h) unacked orders
    rt, pt, et = make()
    openOrders = {i: (1, Side.BUY, 1) for i in range(rt.maxUnackedOrders)}
    ok, _ = check(rt, pt, et, openOrders=openOrders)
    run_test("h) too many unacked orders is rejected", not ok)

    # all checks pass
    rt, pt, et = make()
    ok, reason = check(rt, pt, et)
    run_test("valid order passes all checks", ok and reason is None)


def test_shutdown_checks():
    print("\n--- shutdown / cancel all ---")
    from unittest.mock import MagicMock
    from order_entry import OrderEntryClient

    def make_client():
        client = MagicMock()
        client.positionTracker = positionTracker()
        client.pnlTracker = pnlTracker()
        client.pnlMinVal = -10000
        client.positionLimit = 100
        client.openOrders = {}
        client.order_manager = None
        client.getPnL = lambda symbol: OrderEntryClient.getPnL(client, symbol)
        client.getCurrentMarket = lambda symbol: 0
        client.check = lambda symbol: OrderEntryClient.check(client, symbol)
        return client

    # pnl breach - bought high, sold low, flat position so mark to market = 0
    client = make_client()
    client.pnlTracker.whenFillBuy(1, 100, 200)   # bought 100 @ 200 = cost 20000
    client.pnlTracker.whenFillSell(1, 100, 1)    # sold 100 @ 1 = revenue 100 -> loss of 19900
    client.positionTracker.symbolPosition[1] = 0  # flat position so mark to market adds nothing
    raised = False
    try:
        client.check(1)
    except SystemExit:
        raised = True
    run_test("pnl below minimum raises SystemExit", raised)
    run_test("cancel all called on pnl breach", client.cancelAllOrders.called)

    # position breach
    client2 = make_client()
    client2.positionTracker.symbolPosition[1] = 101
    raised = False
    try:
        client2.check(1)
    except SystemExit:
        raised = True
    run_test("position above limit raises SystemExit", raised)
    run_test("cancel all called on position breach", client2.cancelAllOrders.called)

    # normal state
    client3 = make_client()
    client3.positionTracker.symbolPosition[1] = 10
    client3.pnlTracker.whenFillBuy(1, 10, 100)
    client3.pnlTracker.whenFillSell(1, 10, 110)
    raised = False
    try:
        client3.check(1)
    except SystemExit:
        raised = True
    run_test("normal state does not raise SystemExit", not raised)


def main():
    print("=" * 50)
    print("Running unit tests")
    print("=" * 50)
    test_position_tracker()
    test_exposure_tracker()
    test_pnl_tracker()
    test_risk_tracker()
    test_shutdown_checks()
    print("\n" + "=" * 50)
    print("Done")
    print("=" * 50)


if __name__ == "__main__":
    main()
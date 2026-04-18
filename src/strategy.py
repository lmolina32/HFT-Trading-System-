#!/usr/bin/env python3



# mean reversion for ETFs

def microprice_calc(orderbook):
    # mean reversion
    best_bid, bid_qty = orderbook.book.get_best_bid()
    best_ask, ask_qty = orderbook.book.get_best_ask()
    return ((best_bid * ask_qty) (best_ask * bid_qty) / (bid_qty + ask_qty) )# double check this equation. i got it from gemini.

def main():
        

# spoofing check


# sending spoofing


# market maker; try to keep internal bookeeping of queues for orders we have placed. if too far back in line, cancel.
# IMPORTANT we dont get spoofed so we dont cancel an order we r in good standing for.
# signals that trigger this are important
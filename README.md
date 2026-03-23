# HFT class project

## Usage
```bash
./multicast.py 239.0.0.1 12345 239.0.0.2 12345 <network interface> | ./parser.py
```

```
./order_entry.py
....
> buy/sell     order_id        gold/blue (gold = 1, blue = 2)      quantity price

EXAMPLE:
....
> buy 1 1 5 500
First order (aka order_id of 1), buy 5 qts of gold for 500
```

## General Flow ?
- multicast.py -> subscribes to multicast groups, receives UDP packets, then prints all these packets as hex

- parser.py -> takes these outputted hex lines ^^, converts to bytes, and reassembles packets using the header length (in order to know when one msg ends n the other begins). it builds a typed message object (in `parse_message`) and then routes it !

- orderbook.py -> logic for constructing the order book

- order_entry.py -> logic for actually trying to login + start sending orders to the exchange


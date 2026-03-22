# HFT class project

## Usage
```bash
./multicast.py 239.0.0.1 12345 239.0.0.2 12345 <network interface> | ./parser.py
```




## General Flow ?
- multicast.py -> subscribes to multicast groups, receives UDP packets, then prints all these packets as hex

- parser.py -> takes these outputted hex lines ^^, converts to bytes, and reassembles packets using the header length (in order to know when one msg ends n the other begins). it builds a typed message object (in `parse_message`) and then routes it !

- orderbook.py -> logic for constructing the order book

- order_entry.py -> logic for actually trying to login + start sending orders to the exchange


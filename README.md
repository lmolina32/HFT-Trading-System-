# HFT class project

## Usage
```bash
./multicast.py 239.0.0.1 12345 239.0.0.2 12345 <network interface> | ./parser.py
onload taskset -c 7 python3 ./multicast.py 239.0.0.1 12345 239.0.0.2 12345 192.168.13.17 | python3 ./parser.py 
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



```
./order_entry.py
....
> buy/sell     order_id        gold/blue (gold = 1, blue = 2)      quantity price

EXAMPLE:
....
> buy 1 1 5 500
First order (aka order_id of 1), buy 5 qts of gold for 500
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


- how do you know when you get filled? 
- should we stop running the client if one of the regect reasons happen (invalid_price, qty, side)
no
- on order closed do we have to update our PNL

- in his notes it says -position + total outstanding in the exposure tracker
- get PNL why you add the position + current market price -> getPNL()
- for exposure would we add subtract based on side??? -> isvalid()
- is open orders only unacked orders? is there another dicionatry that has valid open orders??? -> is_valid()
- ask about PNL in office hours 
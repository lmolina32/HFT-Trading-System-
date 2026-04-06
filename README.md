# HFT class project

## Usage (run in base directory)
```bash
onload taskset -c 6 python3 -m src.main <ifconfig addresses> 

Commands:
    buy  <oid> <sym> <qty> <price>
    sell <oid> <sym> <qty> <price>
    del  <oid>
    mod  <oid> <side> <qty> <price>
    ioc  <oid> <sym> <side> <qty> <price>
    pnl  <sym>
    pos  <sym>
    cancel
    quit
```
Note: symbol 1 -> gold, 2 -> blue

## Project Structure

```
bminor/
├── src/
│   ├── main.py                 # main entry point for market data and order entry
│   ├── market_data_struct.py   # order book protocols 
│   ├── multicast.py            # multicast listener for market data 
│   ├── order_book.py           # classes to create and manage order book 
│   ├── order_entry.py          # class to create and manage order entries 
│   ├── parser.py               # functions to parse market data 
│   ├── safety.py               # risk system to ensure all trades are valid 
│   └── strategy/               # trading strategy 
└── test/               # Test cases organized by phase
```
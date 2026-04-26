# HFT class project

## Usage (run in base directory)
```bash
taskset -c 5 onload env EF_SPIN_USEC=-1 EF_MAX_PACKETS=65536 EF_RXQ_SIZE=4096 EF_UDP_RCVBUF=8388608 python3 -m src.main 192.168.13.17

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
└── test/                       # Test cases organized by phase
```
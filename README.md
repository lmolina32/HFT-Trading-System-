# HFT Class Project — Team 2

A market-making and arbitrage trading system for the NDFEX exchange simulator.
Consumes a multicast market-data feed, maintains per-symbol order books, and
sends orders over TCP through pre-trade risk checks.

## Usage

Run from the repository root:

```bash
taskset -c 5 onload env EF_SPIN_USEC=-1 EF_MAX_PACKETS=65536 \
  EF_RXQ_SIZE=4096 EF_UDP_RCVBUF=8388608 \
  python3 -m src.main 192.168.13.17
```


### Interactive CLI commands

While the engine is running, manual orders can be entered alongside the
automated strategy:

| Command | Arguments | Description |
| --- | --- | --- |
| `buy`    | `<oid> <sym> <qty> <price>`        | Submit a buy order |
| `sell`   | `<oid> <sym> <qty> <price>`        | Submit a sell order |
| `ioc`    | `<oid> <sym> <side> <qty> <price>` | Submit an immediate-or-cancel order |
| `mod`    | `<oid> <side> <qty> <price>`       | Modify an existing order |
| `del`    | `<oid>`                            | Cancel a specific order |
| `cancel` |                                    | Cancel every open order |
| `pos`    | `<sym>`                            | Print current position |
| `pnl`    | `<sym>`                            | Print current PnL |
| `all`    |                                    | Print all open orders |
| `quit`   |                                    | Exit |

Symbols: `1` = GOLD, `2` = BLUE, `3`–`12` = dorm names, `13` = UNDY (ETF).

## Project structure

```
team2/
├── src/
│   ├── main.py                  # Entry point: feed handler + CLI + strategy
│   ├── multicast.py             # UDP multicast socket setup
│   ├── market_data_struct.py    # Binary message definitions for the market-data feed
│   ├── parser.py                # Dispatches raw packets to message classes
│   ├── order_book.py            # OrderBook, OrderBookManager, snapshot resync logic
│   ├── order_entry_protocol.py  # Binary message definitions for order entry (TCP)
│   ├── order_entry.py           # OrderEntryClient: login, send/recv, response handling
│   ├── safety.py                # Position / exposure / PnL / pre-trade risk trackers
│   ├── strategy.py              # Market-making strategy with spoof detection
│   └── etf_arb.py               # Create/redeem arbitrage against the ETF basket
└── test/
    ├── _path_setup.py                   # Shared sys.path / logging setup
    ├── md_packets.py                    # Helpers for building raw MD packets
    ├── test_orderbook.py                # OrderBook (heap, levels, modify/trade)
    ├── test_orderbook_manager.py        # OrderBookManager + dispatch_live_message
    ├── test_sequence_tracker.py         # SequenceTracker gap/duplicate handling
    ├── test_snapshot_sync.py            # Snapshot resync state machine
    ├── test_safety.py                   # Position / exposure / PnL / risk
    ├── test_market_data_struct.py       # Binary MD message parsing
    ├── test_order_entry_protocol.py     # Order-entry pack/unpack round-trips
    ├── test_parser.py                   # parse_message dispatch table
    └── test_strategy.py                 # Tick rounding + SpoofDetector
```

## Tests

Run the full suite from the repo root:

```bash
python3 -m unittest discover -s test
```

Or a single module:

```bash
python3 -m unittest discover -s test -p test_safety.py
```

`src/main.py`, `src/multicast.py`, `src/order_entry.py`, and `src/etf_arb.py`
are I/O-bound (sockets, HTTP) and are exercised by running the trader against
the exchange rather than by unit tests.

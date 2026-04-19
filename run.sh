#!/bin/sh

rm -f trade_engine.log
rm -f order_entry.log
onload taskset -c 6 python3 -m src.main 192.168.13.17

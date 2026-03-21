#!/bin/bash

# Configuration
export WEIBO_UID="1644724561"
# Note: Cookies expire, so this might need updating eventually.
export WEIBO_COOKIE="SUB=_2A25EsLtzDeRhGeBM6lIV8CbPzz6IHXVnz7K7rDV6PUJbktANLVjDkW1NRQVR60GQoXwZq4oLyLdqdtSRxnW80DfJ;"
export WEIBO_DAYS="3"

# Start Server
echo "Starting Server..."
cd backend
python3 main.py

#!/bin/bash

# Configuration
export WEIBO_UID="1644724561"
# Note: Cookies expire, so this might need updating eventually.
export WEIBO_COOKIE="SUB=_2A25E4JSTDeRhGeBM6lIV8CbPzz6IHXVnn6hbrDV6PUJbktANLVLMkW1NRQVR63VpA4BcaZFjpY6tpU02xYuoFn_j"
export WEIBO_DAYS="3"

# Start Server
echo "Starting Server..."
cd backend
python3 main.py

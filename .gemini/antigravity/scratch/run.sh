#!/bin/bash

# Configuration
export WEIBO_UID="1644724561"
# Note: Cookies expire, so this might need updating eventually.
export WEIBO_COOKIE="SUB=_2A25EgS2rDeRhGeBM6lIV8CbPzz6IHXVn_y9jrDV6PUJbktANLWXckW1NRQVR6xLifTttHr9Rf_wUjxBhRyz0Xf19"
export WEIBO_DAYS="3"

# Start Server
echo "Starting Server..."
cd backend
python3 main.py

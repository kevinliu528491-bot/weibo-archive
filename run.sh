#!/bin/bash

# Configuration
export WEIBO_UID="1644724561"
# Note: Cookies expire, so this might need updating eventually.
export WEIBO_COOKIE="SUB=_2A25HtaN2DeRhGeBM6lIV8CbPzz6IHXVkyrq-rDV6PUJbktANLRHlkW1NRQVR63F9Xc8s5CX_YCORd_wTLbkizVY4"
export WEIBO_DAYS="3"

# Start Server
echo "Starting Server..."
cd backend
python3 main.py

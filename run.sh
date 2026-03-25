#!/bin/bash

# Configuration
export WEIBO_UID="1644724561"
# Note: Cookies expire, so this might need updating eventually.
export WEIBO_COOKIE="SUB=_2A25Ex1r_DeRhGeBM6lIV8CbPzz6IHXVnvdI3rDV6PUJbktANLWuhkW1NRQVR632fmRWoTr5G5FMiUncD7aD8xV_y"
export WEIBO_DAYS="3"

# Start Server
echo "Starting Server..."
cd backend
python3 main.py

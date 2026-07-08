#!/bin/bash
# Railway start script - disable SSL verify, start health server, then bot
export PYTHONHTTPSVERIFY=0
python railway.py

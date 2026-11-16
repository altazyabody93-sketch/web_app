#!/bin/bash
gunicorn web:app --bind 0.0.0.0:$PORT --workers 2 &
sleep 3
python wep.py &
wait
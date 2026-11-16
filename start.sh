#!/bin/bash

# 1. تشغيل الموقع (Flask) في الخلفية
gunicorn web:app --bind 0.0.0.0:$PORT --workers 2 &
sleep 3

# 2. تشغيل البوت (Telegram) في الخلفية
python bot.py &

# 3. إبقاء السيرفر الرئيسي شغال
wait

# ══════════════════════════════════════════════════════════════
# 🌟 NEM BOT v7 - بوت بيع الأرقام الاحترافي
# 📌 الإصدار: 7.0
# 📌 التقنية: pyTelegramBotAPI (fork with colors) + telethon
# 📌 الميزة: ألوان حقيقية (style=) + قائمة 2×2 + تخصيص كامل
# ══════════════════════════════════════════════════════════════

# ═══════════ AUTO INSTALLER ═══════════
import os
import sys
import subprocess


def _install(pkg, import_name=None, upgrade=False):
    if import_name is None:
        import_name = pkg
    try:
        __import__(import_name)
        print(f"✅ {pkg}")
        return True
    except ImportError:
        print(f"📦 تثبيت: {pkg}...")
        try:
            cmd = [sys.executable, '-m', 'pip', 'install', pkg, '--quiet']
            if upgrade:
                cmd.append('--upgrade')
            subprocess.check_call(cmd)
            print(f"✅ تم تثبيت {pkg}")
            return True
        except Exception as e:
            print(f"❌ فشل تثبيت {pkg}: {e}")
            return False


REQUIRED = [
    ('pyTelegramBotAPI>=4.14.0', 'telebot'),
    ('telethon', 'telethon'),
]

print("═" * 60)
print("📦 جاري تجهيز المكتبات...")
print("═" * 60)
for pkg, name in REQUIRED:
    _install(pkg, name, upgrade=True)
print("═" * 60)
print("✅ جاهز!")
print("═" * 60)


# ═══════════ IMPORTS ═══════════
import asyncio
import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from telethon import events
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, FloodWaitError
from telethon.sessions import StringSession

import telebot
from telebot.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    LabeledPrice,
)

# ═══════════ FLASK FOR WEB SERVICE ═══════════
from flask import Flask, jsonify


# ══════════════════════════════════════════════════════════════
# ⚙️ CONFIG
# ══════════════════════════════════════════════════════════════

API_ID = 22651991
API_HASH = 'ecad214ecff6a5cd90fc141d4e32f597'
BOT_TOKEN = "8852374292:AAEz_yB7bdJUyu4WdZtGiIJonaTRuR0T7sI"
REG_ID = 22651991
REG_HASH = 'ecad214ecff6a5cd90fc141d4e32f597'
PAY_TOKEN = ""

BOT_NAME = "بوت الأرقام الاحترافي"
ADMIN_ID = 7602226699

ACC_FILE = 'registered_accounts.json'
NUM_FILE = 'numbers_for_sale.json'
USER_FILE = 'user_data.json'
CONF_FILE = 'bot_settings.json'
STATS_FILE = 'stats.json'
LOG_FILE = 'activity.log'

bot = telebot.TeleBot(BOT_TOKEN)

# Thread للـ telethon
telethon_loop = asyncio.new_event_loop()


def _start_telethon_loop():
    asyncio.set_event_loop(telethon_loop)
    telethon_loop.run_forever()


threading.Thread(target=_start_telethon_loop, daemon=True).start()

client = TelegramClient(StringSession(), API_ID, API_HASH, loop=telethon_loop)


# ══════════════════════════════════════════════════════════════
# 💾 STORAGE
# ══════════════════════════════════════════════════════════════

u_clients = {}
code_reqs = {}
res_timers = {}
u_sessions = {}
avail_nums = {}
syyad_users = {}
add_states = {}
user_states = {}


# ══════════════════════════════════════════════════════════════
# ⚙️ الإعدادات الافتراضية
# ══════════════════════════════════════════════════════════════

syyad_conf = {
    'admin_ids': [str(7325566792)],
    'dailyGiftPoints': 10,
    'referralPoints': 5,
    'chargeRates': [],
    'reservationTimeoutMinutes': 60,
    'publish_channel_id': None,
    'notify_channel_id': None,
    'main_channel_url': None,
    'activation_channels': [],
    'currency_name': 'دولار',
    'currency_symbol': '$',
    'main_buttons_colors': {},
    'custom_main_rows': [],
    'welcome_message': None,
    'developer_username': 'MO_5_H',
}


# ══════════════════════════════════════════════════════════════
# 🎨 نظام الألوان الحقيقية
# ══════════════════════════════════════════════════════════════

# الألوان المدعومة في Telegram Bot API 7.0+
AVAILABLE_COLORS = {
    'primary': {'name': 'أزرق', 'emoji': '🔵'},
    'success': {'name': 'أخضر', 'emoji': '🟢'},
    'danger':  {'name': 'أحمر', 'emoji': '🔴'},
}

# الألوان الافتراضية للقائمة الرئيسية
DEFAULT_MAIN_COLORS = {
    'buy':     'success',   # 🛒 شراء — أخضر
    'charge':  'primary',   # 💳 شحن — أزرق
    'profile': 'primary',   # 👤 حسابي — أزرق
    'gift':    'success',   # 🎁 هدية — أخضر
    'ref':     'primary',   # 🔗 إحالة — أزرق
    'help':    'danger',    # 🆘 مساعدة — أحمر
    'channel': 'primary',   # 📢 قناة — أزرق
    'admin':   'danger',    # 👑 أدمن — أحمر
}


def ensure_colors_conf():
    """تأكد من وجود إعدادات الألوان"""
    if 'main_buttons_colors' not in syyad_conf or not syyad_conf['main_buttons_colors']:
        syyad_conf['main_buttons_colors'] = DEFAULT_MAIN_COLORS.copy()
    else:
        for key, val in DEFAULT_MAIN_COLORS.items():
            syyad_conf['main_buttons_colors'].setdefault(key, val)
    syyad_conf.setdefault('custom_main_rows', [])
    syyad_conf.setdefault('developer_username', 'MO_5_H')


def get_color(key):
    """الحصول على لون زر محدد"""
    colors = syyad_conf.get('main_buttons_colors', DEFAULT_MAIN_COLORS)
    return colors.get(key, 'primary')


def is_valid_color(color):
    return color in AVAILABLE_COLORS


# ══════════════════════════════════════════════════════════════
# 🎨 BUTTONS — ألوان حقيقية
# ══════════════════════════════════════════════════════════════

# كشف دعم style تلقائيًا
def _check_style_support():
    try:
        InlineKeyboardButton(text="test", callback_data="t", style="primary")
        return True
    except TypeError:
        return False
    except Exception:
        return True


USE_STYLE = _check_style_support()

if USE_STYLE:
    print("🎨 الألوان الحقيقية مدعومة ✅")
else:
    print("⚠️ نسختك لا تدعم style — سيتم استخدام أيقونات")
print()


class Btn:
    """
    أزرار احترافية تدعم الألوان الحقيقية.
    
    - إذا كانت نسختك تدعم style → ألوان حقيقية
    - إذا لا → أيقونات ملونة بجانب النص
    """
    
    @staticmethod
    def _make(text, data=None, url=None, color='primary'):
        kwargs = {}
        
        if USE_STYLE:
            kwargs['style'] = color
            display_text = text  # بدون أيقونة
        else:
            # fallback: أيقونة ملونة
            emoji = AVAILABLE_COLORS.get(color, {}).get('emoji', '')
            display_text = f"{emoji} {text}" if emoji else text
        
        if url:
            # أزرار الروابط — style مدعوم الآن
            return InlineKeyboardButton(text=display_text, url=url, **kwargs)
        
        return InlineKeyboardButton(
            text=display_text,
            callback_data=data if data else 'noop',
            **kwargs
        )
    
    # ───── اختصارات ─────
    @staticmethod
    def p(text, data):
        """🔵 primary (أزرق)"""
        return Btn._make(text, data=data, color='primary')
    
    @staticmethod
    def s(text, data):
        """🟢 success (أخضر)"""
        return Btn._make(text, data=data, color='success')
    
    @staticmethod
    def d(text, data):
        """🔴 danger (أحمر)"""
        return Btn._make(text, data=data, color='danger')
    
    @staticmethod
    def c(text, data, color='primary'):
        """زر بلون مخصص"""
        return Btn._make(text, data=data, color=color)
    
    @staticmethod
    def u(text, url, color='primary'):
        """زر رابط بلون"""
        return Btn._make(text, url=url, color=color)
    
    @staticmethod
    def cu(text, url, color='primary'):
        """زر رابط بلون مخصص (اختصار)"""
        return Btn._make(text, url=url, color=color)


# ══════════════════════════════════════════════════════════════
# 💬 HELPERS
# ══════════════════════════════════════════════════════════════

def now() -> datetime:
    return datetime.utcnow()


def hide_phone(phone):
    if not phone or len(phone) < 8:
        return phone
    return f"{phone[:4]}{'*' * (len(phone) - 7)}{phone[-3:]}"


def format_time_remaining(seconds):
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def log(text, level='info'):
    try:
        emoji = {'info': 'ℹ️', 'error': '❌', 'success': '✅', 'warn': '⚠️'}.get(level, 'ℹ️')
        ts = now().strftime('%Y-%m-%d %H:%M:%S')
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f"[{ts}] {emoji} {text}\n")
        print(f"{emoji} {text}")
    except Exception:
        pass


def is_valid_phone(p):
    if not p:
        return False
    p = p.strip()
    return p.startswith('+') and p[1:].isdigit() and 8 <= len(p) <= 16


def is_valid_uid(u):
    return str(u).strip().isdigit()


def is_valid_amount(a, min_val=1):
    try:
        return int(a) >= min_val
    except (ValueError, TypeError):
        return False


Path(LOG_FILE).touch(exist_ok=True)


# ══════════════════════════════════════════════════════════════
# ✅ EDIT / SEND HELPERS
# ══════════════════════════════════════════════════════════════

def edit_or_send_message(chat_id, message_id, text, kb=None):
    try:
        bot.edit_message_text(
            text,
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=kb,
            parse_mode='html'
        )
    except Exception:
        try:
            bot.send_message(chat_id, text, reply_markup=kb, parse_mode='html')
        except Exception as e:
            log(f"edit_or_send: {e}", 'error')


def answer_callback(call_id, text=None, alert=False):
    try:
        bot.answer_callback_query(
            callback_query_id=call_id,
            text=text,
            show_alert=alert
        )
    except Exception:
        pass


def screen_edit(chat_id, message_id, text, kb=None):
    edit_or_send_message(chat_id, message_id, text, kb)
    
# ══════════════════════════════════════════════════════════════
# 💾 DATABASE (JSON Files)
# ══════════════════════════════════════════════════════════════

def load(path, default=None):
    """تحميل ملف JSON"""
    if default is None:
        default = {}
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            log(f"load {path}: {e}", 'error')
            return default
    return default


def save(path, data):
    """حفظ ملف JSON (atomic)"""
    try:
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as e:
        log(f"save {path}: {e}", 'error')


def load_all():
    """تحميل كل البيانات"""
    global u_sessions, avail_nums, syyad_users, syyad_conf
    
    u_sessions = load(ACC_FILE, {})
    avail_nums = load(NUM_FILE, {})
    syyad_users = load(USER_FILE, {})
    
    loaded = load(CONF_FILE, {})
    syyad_conf.update(loaded)
    
    # تأكد من الأدمن الرئيسي
    if not syyad_conf.get('admin_ids') or not isinstance(syyad_conf['admin_ids'], list):
        syyad_conf['admin_ids'] = [str(ADMIN_ID)]
    if str(ADMIN_ID) not in syyad_conf['admin_ids']:
        syyad_conf['admin_ids'].append(str(ADMIN_ID))
    
    # الإعدادات الافتراضية
    defaults = {
        'main_channel_url': None,
        'currency_name': 'دولار',
        'currency_symbol': '$',
        'notify_channel_id': None,
        'publish_channel_id': None,
        'chargeRates': [],
        'activation_channels': [],
        'dailyGiftPoints': 10,
        'referralPoints': 5,
        'reservationTimeoutMinutes': 60,
    }
    for k, v in defaults.items():
        syyad_conf.setdefault(k, v)
    
    ensure_colors_conf()
    
    # ترحيل: تصفير price_stars
    migrated = 0
    for phone, details in avail_nums.items():
        if details.get('price_stars', 0) > 0:
            details['price_stars'] = 0
            migrated += 1
    if migrated:
        save(NUM_FILE, avail_nums)
        log(f"🔄 تم ترحيل {migrated} رقم", 'info')
    
    log(
        f"✅ التحميل: {len(syyad_users)} مستخدم | "
        f"{len(avail_nums)} رقم | {len(u_sessions)} جلسة",
        'success'
    )


def save_all():
    """حفظ كل البيانات"""
    save(ACC_FILE, u_sessions)
    save(NUM_FILE, avail_nums)
    save(CONF_FILE, syyad_conf)
    save(USER_FILE, syyad_users)


# ══════════════════════════════════════════════════════════════
# 👤 USERS
# ══════════════════════════════════════════════════════════════

def get_user(uid):
    """الحصول على مستخدم أو إنشاء جديد"""
    uid = str(uid)
    if uid not in syyad_users:
        syyad_users[uid] = {}
    u = syyad_users[uid]
    u.setdefault('points', 0)
    u.setdefault('stars', 0)
    u.setdefault('lastDailyGiftClaim', None)
    u.setdefault('referred_by', None)
    u.setdefault('total_spent', 0)
    u.setdefault('total_orders', 0)
    u.setdefault('registered_at', now().isoformat())
    u.setdefault('username', None)
    u.setdefault('first_name', None)
    return u


def update_user_info(uid, username=None, first_name=None):
    """تحديث معلومات المستخدم"""
    u = get_user(uid)
    if username:
        u['username'] = username
    if first_name:
        u['first_name'] = first_name
    save(USER_FILE, syyad_users)


def is_admin(uid):
    """هل المستخدم أدمن؟"""
    return str(uid) in syyad_conf.get('admin_ids', [])


def add_points(uid, amount):
    """إضافة رصيد"""
    u = get_user(uid)
    u['points'] = u.get('points', 0) + amount
    save(USER_FILE, syyad_users)
    return u['points']


def remove_points(uid, amount):
    """خصم رصيد"""
    u = get_user(uid)
    if u.get('points', 0) < amount:
        return False
    u['points'] -= amount
    save(USER_FILE, syyad_users)
    return True


def add_stars(uid, amount):
    """إضافة نجوم"""
    u = get_user(uid)
    u['stars'] = u.get('stars', 0) + amount
    save(USER_FILE, syyad_users)
    return u['stars']


# ══════════════════════════════════════════════════════════════
# 📱 NUMBERS
# ══════════════════════════════════════════════════════════════

def get_number(phone):
    """الحصول على رقم"""
    return avail_nums.get(phone)


def add_number(phone, details):
    """إضافة رقم جديد"""
    avail_nums[phone] = details
    save(NUM_FILE, avail_nums)


def remove_number(phone):
    """حذف رقم"""
    if phone in avail_nums:
        del avail_nums[phone]
        save(NUM_FILE, avail_nums)
        return True
    return False


def get_available_numbers():
    """الأرقام المتاحة"""
    return {p: d for p, d in avail_nums.items() if d.get('status') == 'available'}


def get_sold_numbers():
    """الأرقام المباعة"""
    return {p: d for p, d in avail_nums.items() if d.get('status') == 'sold'}


def get_booked_numbers():
    """الأرقام المحجوزة"""
    return {p: d for p, d in avail_nums.items() if d.get('status') == 'booked'}


def count_numbers():
    """إحصائيات الأرقام"""
    return {
        'total': len(avail_nums),
        'available': len(get_available_numbers()),
        'sold': len(get_sold_numbers()),
        'booked': len(get_booked_numbers()),
    }


def get_countries():
    """قائمة الدول المتاحة"""
    countries = set()
    for d in avail_nums.values():
        if d.get('status') in ['available', 'booked']:
            c = d.get('country')
            if c:
                countries.add(c)
    return sorted(countries)


def get_numbers_in_country(country, uid=None):
    """الأرقام في دولة معينة"""
    result = {}
    for p, d in avail_nums.items():
        if d.get('country') != country:
            continue
        status = d.get('status')
        if status == 'available':
            result[p] = d
        elif status == 'booked':
            if uid and str(d.get('booked_by')) == str(uid):
                result[p] = d
    return result


# ══════════════════════════════════════════════════════════════
# 🎁 GIFT + STATS
# ══════════════════════════════════════════════════════════════

GIFT_COOLDOWN = 86400  # 24 ساعة


def can_claim_gift(uid):
    """هل يمكن استلام الهدية؟"""
    u = get_user(uid)
    last = u.get('lastDailyGiftClaim')
    if not last:
        return True, 0
    elapsed = time.time() - last
    if elapsed >= GIFT_COOLDOWN:
        return True, 0
    return False, GIFT_COOLDOWN - elapsed


def claim_gift(uid):
    """استلام الهدية اليومية"""
    can, _ = can_claim_gift(uid)
    if not can:
        return False, 0
    amount = syyad_conf.get('dailyGiftPoints', 10)
    if amount <= 0:
        return False, 0
    add_points(uid, amount)
    u = get_user(uid)
    u['lastDailyGiftClaim'] = time.time()
    save(USER_FILE, syyad_users)
    return True, amount


def load_stats():
    """تحميل الإحصائيات"""
    return load(STATS_FILE, {
        'total_sales': 0,
        'total_revenue_points': 0,
        'total_revenue_stars': 0,
    })


def update_stats(key, amount=1):
    """تحديث الإحصائيات"""
    s = load_stats()
    s[key] = s.get(key, 0) + amount
    save(STATS_FILE, s)
    
# ══════════════════════════════════════════════════════════════
# ⌨️ KEYBOARDS - USER
# ══════════════════════════════════════════════════════════════

def kb_back(target="user_main", label="‹ رجوع"):
    """زر رجوع بسيط"""
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(Btn.d(label, target))
    return kb


def kb_cancel():
    """زر إلغاء"""
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(Btn.d("❌ إلغاء", "cancel"))
    return kb


def kb_user_main(uid=None):
    """
    🌟 القائمة الرئيسية (v7)
    
    التصميم:
    ┌─────────────────────────────┐
    │  🛒 شراء رقم (منفصل — أخضر)   │
    ├──────────────┬──────────────┤
    │ 💳 شحن       │ 👤 حسابي     │
    ├──────────────┼──────────────┤
    │ 🎁 هدية      │ 🔗 إحالة     │
    ├──────────────┼──────────────┤
    │ 🆘 مساعدة    │ ⚙️ المزيد    │
    ├─────────────────────────────┤
    │  📢 قناة الطلبات (منفصل)     │
    ├─────────────────────────────┤
    │  👑 لوحة التحكم (أدمن)       │
    └─────────────────────────────┘
    """
    kb = InlineKeyboardMarkup(row_width=2)
    
    # 🛒 شراء رقم — منفصل بارز
    kb.row(Btn.c("🛒 شراء رقم", "user_buy", get_color('buy')))
    
    # صفوف 1×1
    kb.row(
        Btn.c("💳 شحن رصيدي", "user_charge", get_color('charge')),
        Btn.c("👤 حسابي", "user_profile", get_color('profile')),
    )
    kb.row(
        Btn.c("🎁 هدية يومية", "user_gift", get_color('gift')),
        Btn.c("🔗 إحالة", "user_ref", get_color('ref')),
    )
    kb.row(
        Btn.c("🆘 مساعدة", "user_help", get_color('help')),
        Btn.c("⚙️ المزيد", "user_more", 'primary'),
    )
    
    # صفوف مخصصة من لوحة التحكم
    custom_rows = syyad_conf.get('custom_main_rows', [])
    for row in custom_rows:
        if not row.get('enabled', True):
            continue
        buttons = []
        for b in row.get('buttons', []):
            label = b.get('label', 'زر')
            color = b.get('color', 'primary')
            if b.get('url'):
                buttons.append(Btn.cu(label, b['url'], color))
            elif b.get('callback'):
                buttons.append(Btn.c(label, b['callback'], color))
        if buttons:
            kb.row(*buttons[:2])
    
    # 📢 قناة الطلبات — منفصل
    channel_url = syyad_conf.get('main_channel_url')
    if channel_url:
        kb.row(Btn.u("📢 قناة الطلبات", channel_url, get_color('channel')))
    
    # 👑 لوحة التحكم للأدمن فقط
    if uid and is_admin(uid):
        kb.row(Btn.c("👑 لوحة التحكم", "adm_main", get_color('admin')))
    
    return kb


def kb_user_profile():
    """قائمة حسابي"""
    kb = InlineKeyboardMarkup(row_width=2)
    kb.row(
        Btn.s("💳 شحن رصيدي", "user_charge"),
        Btn.p("🔗 رابط الإحالة", "user_ref"),
    )
    kb.row(
        Btn.p("📊 إحصائياتي", "user_my_stats"),
        Btn.p("📜 طلباتي", "user_my_orders"),
    )
    kb.row(Btn.d("‹ رجوع", "user_main"))
    return kb


def kb_user_charge():
    """قائمة الشحن"""
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(Btn.s("⭐ شحن بالنجوم", "user_charge_stars"))
    kb.add(Btn.s("🎁 الهدية اليومية", "user_gift"))
    kb.add(Btn.p("🔗 رابط الإحالة", "user_ref"))
    kb.add(Btn.d("‹ رجوع", "user_main"))
    return kb


def kb_user_charge_rates(rates):
    """باقات الشحن بالنجوم"""
    kb = InlineKeyboardMarkup(row_width=1)
    sym = syyad_conf.get('currency_symbol', '$')
    if not rates:
        kb.add(Btn.p("📭 لا توجد باقات حالياً", "noop"))
    else:
        for idx, rate in enumerate(rates):
            points = rate.get('points', 0)
            stars = rate.get('stars', 0)
            kb.add(Btn.s(f"💵 {sym}{points} = ⭐ {stars}", f"charge_stars:{idx}"))
    kb.add(Btn.d("‹ رجوع", "user_charge"))
    return kb


def kb_user_countries(countries):
    """قائمة الدول"""
    kb = InlineKeyboardMarkup(row_width=2)
    if not countries:
        kb.add(Btn.p("📭 لا توجد دول", "noop"))
    else:
        buttons = [Btn.p(f"🌍 {c}", f"country:{c}") for c in countries]
        kb.add(*buttons)
    kb.add(Btn.d("‹ رجوع", "user_main"))
    return kb


def kb_user_numbers(numbers, uid):
    """قائمة الأرقام — بالدولار فقط"""
    kb = InlineKeyboardMarkup(row_width=1)
    sym = syyad_conf.get('currency_symbol', '$')
    
    # أولاً: المحجوزة للمستخدم
    for phone, details in numbers.items():
        if details.get('status') == 'booked' and str(details.get('booked_by')) == str(uid):
            expiry = details.get('expiry_time', 0)
            rem = max(0, int(expiry - time.time()))
            kb.add(Btn.s(f"🔔 {hide_phone(phone)} ({format_time_remaining(rem)})", f"view_num:{phone}"))
    
    # ثانياً: الأرقام المتاحة
    for phone, details in numbers.items():
        if details.get('status') == 'available':
            pts = details.get('price_points', 0)
            label = f"📱 {hide_phone(phone)} — {sym}{pts}"
            kb.add(Btn.p(label, f"view_num:{phone}"))
    
    kb.add(Btn.d("‹ رجوع للدول", "user_buy"))
    return kb


def kb_user_more():
    """قائمة المزيد — كل الأزرار شغّالة"""
    kb = InlineKeyboardMarkup(row_width=2)
    kb.row(
        Btn.p("📊 إحصائياتي", "user_my_stats"),
        Btn.p("📜 طلباتي", "user_my_orders"),
    )
    kb.row(
        Btn.p("👤 حسابي", "user_profile"),
        Btn.s("🎁 الهدية", "user_gift"),
    )
    kb.row(
        Btn.p("📞 تواصل معنا", "user_contact"),
        Btn.p("📢 القنوات", "user_channels"),
    )
    kb.row(Btn.d("‹ رجوع", "user_main"))
    return kb


# ══════════════════════════════════════════════════════════════
# 🎨 SCREENS - USER (MAIN)
# ══════════════════════════════════════════════════════════════

def screen_user_main(chat_id, message_id=None, user=None, uid=None):
    """الشاشة الرئيسية الفاخرة"""
    if not uid:
        uid = str(user.id) if user else str(chat_id)
    
    u = get_user(uid)
    first_name = u.get('first_name') or (user.first_name if user else "—")
    username = u.get('username') or (user.username if user else None)
    
    points = u.get('points', 0)
    stars = u.get('stars', 0)
    orders = u.get('total_orders', 0)
    sym = syyad_conf.get('currency_symbol', '$')
    
    text = (
        "╔══════════════════════════════╗\n"
        "║   🌟 <b>مرحباً بك في</b>         ║\n"
        "║   💎 <b>بوت الأرقام الاحترافي</b>  ║\n"
        "╚══════════════════════════════╝\n"
        "\n"
        f"👋 أهلاً <b>{first_name}</b>\n"
        f"🆔 آيديك: <code>{uid}</code>\n"
    )
    if username:
        text += f"📛 يوزرك: @{username}\n"
    
    text += (
        "\n"
        "┌──────────────────────────────┐\n"
        f"│  💵 <b>الرصيد:</b> <code>{sym}{points}</code>\n"
        f"│  ⭐ <b>النجوم:</b> <code>{stars}</code>\n"
        f"│  📦 <b>الطلبات:</b> <code>{orders}</code>\n"
        "└──────────────────────────────┘\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "✨ <i>اختر الخدمة التي تريدها</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    
    kb = kb_user_main(uid=uid)
    
    if message_id:
        screen_edit(chat_id, message_id, text, kb)
    else:
        bot.send_message(chat_id, text, reply_markup=kb, parse_mode='html')


def screen_user_profile(chat_id, message_id, uid):
    """شاشة حسابي"""
    u = get_user(uid)
    sym = syyad_conf.get('currency_symbol', '$')
    
    text = (
        "╔══════════════════════════════╗\n"
        "║      👤 <b>بطاقتك الشخصية</b>      ║\n"
        "╚══════════════════════════════╝\n"
        "\n"
        "┌──────────────────────────────┐\n"
        f"│  🆔 <b>الآيدي:</b> <code>{uid}</code>\n"
        "├──────────────────────────────┤\n"
        f"│  💵 <b>الرصيد:</b> <code>{sym}{u.get('points', 0)}</code>\n"
        f"│  ⭐ <b>النجوم:</b> <code>{u.get('stars', 0)}</code>\n"
        "├──────────────────────────────┤\n"
        f"│  📦 <b>الطلبات:</b> <code>{u.get('total_orders', 0)}</code>\n"
        f"│  💰 <b>المشتريات:</b> <code>{sym}{u.get('total_spent', 0)}</code>\n"
        "└──────────────────────────────┘\n"
    )
    edit_or_send_message(chat_id, message_id, text, kb_user_profile())


def screen_user_charge(chat_id, message_id, uid):
    """شاشة الشحن"""
    u = get_user(uid)
    sym = syyad_conf.get('currency_symbol', '$')
    
    text = (
        "╔══════════════════════════════╗\n"
        "║      💳 <b>شحن رصيدي</b>          ║\n"
        "╚══════════════════════════════╝\n"
        "\n"
        "┌──────────────────────────────┐\n"
        f"│  💵 <b>رصيدك:</b> <code>{sym}{u.get('points', 0)}</code>\n"
        f"│  ⭐ <b>نجومك:</b> <code>{u.get('stars', 0)}</code>\n"
        "└──────────────────────────────┘\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "✨ <i>اختر طريقة الشحن</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    edit_or_send_message(chat_id, message_id, text, kb_user_charge())


def screen_user_charge_stars(chat_id, message_id):
    """شاشة باقات الشحن بالنجوم"""
    rates = syyad_conf.get('chargeRates', [])
    sym = syyad_conf.get('currency_symbol', '$')
    
    if not rates:
        text = (
            "❌ <b>لا توجد باقات شحن حالياً</b>\n\n"
            "💡 <i>حاول لاحقاً أو راسل الإدارة</i>"
        )
        edit_or_send_message(chat_id, message_id, text, kb_back("user_charge"))
        return
    
    text = (
        "╔══════════════════════════════╗\n"
        "║   ⭐ <b>شحن رصيدي بالنجوم</b>     ║\n"
        "╚══════════════════════════════╝\n"
        "\n"
        "💎 <b>اختر الباقة المناسبة:</b>\n"
        "\n"
    )
    for idx, rate in enumerate(rates, 1):
        points = rate.get('points', 0)
        stars = rate.get('stars', 0)
        text += f"  {idx}. 💵 <b>{sym}{points}</b> = ⭐ <b>{stars}</b> نجمة\n"
    
    text += (
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 <i>النجوم تُشحن رصيدك فقط</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    edit_or_send_message(chat_id, message_id, text, kb_user_charge_rates(rates))


def screen_user_gift(chat_id, message_id, uid, call_id=None):
    """الهدية اليومية"""
    can, remaining = can_claim_gift(uid)
    if not can:
        if call_id:
            answer_callback(
                call_id,
                f"⏳ الهدية متاحة بعد: {format_time_remaining(remaining)}",
                alert=True
            )
        return
    
    success, amount = claim_gift(uid)
    sym = syyad_conf.get('currency_symbol', '$')
    
    if success:
        text = (
            "╔══════════════════════════════╗\n"
            "║   🎉 <b>مبروك!</b>                ║\n"
            "╚══════════════════════════════╝\n"
            "\n"
            "┌──────────────────────────────┐\n"
            f"│  🎁 <b>حصلت على:</b> <code>{sym}{amount}</code>\n"
            "└──────────────────────────────┘\n"
            "\n"
            "💡 <i>تعال غدًا لمزيد!</i>"
        )
        edit_or_send_message(chat_id, message_id, text, kb_back("user_main"))
        if call_id:
            answer_callback(call_id, "🎉 مبروك!", alert=False)
    else:
        if call_id:
            answer_callback(call_id, "❌ فشل استلام الهدية", alert=True)


def screen_user_ref(chat_id, message_id, uid):
    """رابط الإحالة"""
    try:
        bot_info = bot.get_me()
        bot_username = bot_info.username
    except Exception:
        bot_username = "Bot"
    
    ref_link = f"https://t.me/{bot_username}?start=ref_{uid}"
    reward = syyad_conf.get('referralPoints', 5)
    sym = syyad_conf.get('currency_symbol', '$')
    
    text = (
        "╔══════════════════════════════╗\n"
        "║      🔗 <b>رابط الإحالة</b>        ║\n"
        "╚══════════════════════════════╝\n"
        "\n"
        "┌──────────────────────────────┐\n"
        f"│  💰 <b>المكافأة:</b> <code>{sym}{reward}</code>\n"
        "│  لكل صديق يسجل عبرك\n"
        "└──────────────────────────────┘\n"
        "\n"
        "📋 <b>رابطك:</b>\n"
        f"<code>{ref_link}</code>\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 <i>شارك رابطك واكسب!</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(Btn.u(
        "📤 مشاركة الرابط",
        f"https://t.me/share/url?url={ref_link}",
        'primary'
    ))
    kb.add(Btn.d("‹ رجوع", "user_charge"))
    
    edit_or_send_message(chat_id, message_id, text, kb)


def screen_user_help(chat_id, message_id):
    """المساعدة — مع زر المطور"""
    dev_user = syyad_conf.get('developer_username', 'MO_5_H')
    
    text = (
        "╔══════════════════════════════╗\n"
        "║      🆘 <b>المساعدة</b>           ║\n"
        "╚══════════════════════════════╝\n"
        "\n"
        "📌 <b>الأوامر المتاحة:</b>\n"
        "\n"
        "  🔹 /start — القائمة الرئيسية\n"
        "  🔹 /id — معلوماتك\n"
        "  🔹 /help — المساعدة\n"
        "\n"
        "💡 <b>كيف أشتري رقم؟</b>\n"
        "  1️⃣ اضغط \"🛒 شراء رقم\"\n"
        "  2️⃣ اختر الدولة\n"
        "  3️⃣ اختر الرقم\n"
        "  4️⃣ ادفع من رصيدك\n"
        "\n"
        "💡 <b>كيف أشحن رصيدي؟</b>\n"
        "  • بالنجوم ⭐ من \"💳 شحن رصيدي\"\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📞 <i>للتواصل مع المطور اضغط الزر أدناه</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(Btn.u("👨‍💻 المطور", f"https://t.me/{dev_user}", 'primary'))
    kb.add(Btn.d("‹ رجوع", "user_main"))
    
    edit_or_send_message(chat_id, message_id, text, kb)


def screen_user_more(chat_id, message_id):
    """شاشة المزيد"""
    text = (
        "╔══════════════════════════════╗\n"
        "║      ⚙️ <b>المزيد</b>              ║\n"
        "╚══════════════════════════════╝\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "✨ <i>اختر من الخيارات</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    edit_or_send_message(chat_id, message_id, text, kb_user_more())


# ══════════════════════════════════════════════════════════════
# 🎨 SCREENS - USER (MORE — الشاشات الجديدة)
# ══════════════════════════════════════════════════════════════

def screen_user_my_stats(chat_id, message_id, uid):
    """شاشة إحصائياتي"""
    u = get_user(uid)
    sym = syyad_conf.get('currency_symbol', '$')
    
    text = (
        "╔══════════════════════════════╗\n"
        "║   📊 <b>إحصائياتي</b>            ║\n"
        "╚══════════════════════════════╝\n"
        "\n"
        "┌──────────────────────────────┐\n"
        f"│  💵 <b>الرصيد الحالي:</b>\n"
        f"│  <code>{sym}{u.get('points', 0)}</code>\n"
        "├──────────────────────────────┤\n"
        f"│  ⭐ <b>النجوم:</b> <code>{u.get('stars', 0)}</code>\n"
        f"│  📦 <b>الطلبات:</b> <code>{u.get('total_orders', 0)}</code>\n"
        f"│  💰 <b>إجمالي الشراء:</b> <code>{sym}{u.get('total_spent', 0)}</code>\n"
        "└──────────────────────────────┘\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📈 <i>استمر في استخدام البوت!</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(Btn.s("🛒 شراء رقم", "user_buy"))
    kb.add(Btn.d("‹ رجوع", "user_more"))
    edit_or_send_message(chat_id, message_id, text, kb)


def screen_user_my_orders(chat_id, message_id, uid):
    """شاشة طلباتي"""
    my_orders = []
    for phone, details in avail_nums.items():
        if str(details.get('buyer_id')) == str(uid) and details.get('status') == 'sold':
            my_orders.append((phone, details))
    
    my_orders = sorted(my_orders, key=lambda x: x[1].get('sold_at', ''), reverse=True)
    sym = syyad_conf.get('currency_symbol', '$')
    
    if not my_orders:
        text = (
            "╔══════════════════════════════╗\n"
            "║   📜 <b>طلباتي</b>               ║\n"
            "╚══════════════════════════════╝\n"
            "\n"
            "📭 <b>لا توجد طلبات سابقة</b>\n"
            "\n"
            "💡 <i>ابدأ بشراء رقم!</i>"
        )
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(Btn.s("🛒 شراء رقم", "user_buy"))
        kb.add(Btn.d("‹ رجوع", "user_more"))
        edit_or_send_message(chat_id, message_id, text, kb)
        return
    
    text = (
        "╔══════════════════════════════╗\n"
        "║   📜 <b>طلباتي</b>               ║\n"
        "╚══════════════════════════════╝\n"
        "\n"
        f"📦 <b>عدد الطلبات:</b> <code>{len(my_orders)}</code>\n"
        "\n"
    )
    
    for i, (phone, details) in enumerate(my_orders[:10], 1):
        date = details.get('sold_at', '')
        if date:
            date = date[:10]
        text += (
            f"<b>{i}.</b> 📱 <code>{hide_phone(phone)}</code>\n"
            f"   🌍 {details.get('country', '—')} | 💵 {sym}{details.get('price_points', 0)}\n"
            f"   📅 {date}\n\n"
        )
    
    if len(my_orders) > 10:
        text += f"\n<i>... و {len(my_orders) - 10} طلب آخر</i>"
    
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(Btn.s("🛒 شراء رقم جديد", "user_buy"))
    kb.add(Btn.d("‹ رجوع", "user_more"))
    edit_or_send_message(chat_id, message_id, text, kb)


def screen_user_contact(chat_id, message_id):
    """شاشة تواصل معنا"""
    dev_user = syyad_conf.get('developer_username', 'MO_5_H')
    
    text = (
        "╔══════════════════════════════╗\n"
        "║   📞 <b>تواصل معنا</b>            ║\n"
        "╚══════════════════════════════╝\n"
        "\n"
        "💬 <b>للتواصل والدعم:</b>\n"
        "\n"
        f"  👨‍💻 <b>المطور:</b> @{dev_user}\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⏰ <i>الرد خلال 24 ساعة</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(Btn.u("💬 مراسلة المطور", f"https://t.me/{dev_user}", 'success'))
    kb.add(Btn.d("‹ رجوع", "user_more"))
    edit_or_send_message(chat_id, message_id, text, kb)


def screen_user_channels(chat_id, message_id):
    """شاشة القنوات"""
    main_ch = syyad_conf.get('main_channel_url')
    
    text = (
        "╔══════════════════════════════╗\n"
        "║   📢 <b>قنواتنا</b>              ║\n"
        "╚══════════════════════════════╝\n"
        "\n"
        "تابع قنواتنا للعروض الجديدة:\n"
        "\n"
    )
    
    kb = InlineKeyboardMarkup(row_width=1)
    
    if main_ch:
        text += "📢 <b>قناة الطلبات:</b>\n"
        kb.add(Btn.u("📢 قناة الطلبات", main_ch, 'primary'))
    else:
        text += "📭 <i>لا توجد قنوات حالياً</i>\n"
    
    kb.add(Btn.d("‹ رجوع", "user_more"))
    edit_or_send_message(chat_id, message_id, text, kb)


# ══════════════════════════════════════════════════════════════
# 🌍 SCREENS - BUY / NUMBERS
# ══════════════════════════════════════════════════════════════

def screen_user_countries(chat_id, msg_id):
    """شاشة اختيار الدولة"""
    countries = get_countries()
    if not countries:
        text = (
            "╔══════════════════════════════╗\n"
            "║   ❌ <b>لا توجد أرقام حالياً</b>   ║\n"
            "╚══════════════════════════════╝\n"
            "\n"
            "💡 <i>حاول لاحقاً أو راسل الإدارة</i>"
        )
        edit_or_send_message(chat_id, msg_id, text, kb_back("user_main"))
        return
    
    text = (
        "╔══════════════════════════════╗\n"
        "║      🌍 <b>اختر الدولة</b>         ║\n"
        "╚══════════════════════════════╝\n"
        "\n"
        f"📊 <b>الدول المتاحة:</b> <code>{len(countries)}</code>\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "👇 <i>اضغط على الدولة لعرض الأرقام</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    edit_or_send_message(chat_id, msg_id, text, kb_user_countries(countries))


def screen_user_numbers(chat_id, msg_id, country, uid):
    """شاشة عرض الأرقام في دولة"""
    numbers = get_numbers_in_country(country, uid)
    if not numbers:
        text = (
            "╔══════════════════════════════╗\n"
            f"║   ❌ <b>لا توجد أرقام في {country}</b>\n"
            "╚══════════════════════════════╝\n"
            "\n"
            "💡 <i>جرّب دولة أخرى</i>"
        )
        edit_or_send_message(chat_id, msg_id, text, kb_back("user_buy"))
        return
    
    available = sum(1 for d in numbers.values() if d.get('status') == 'available')
    booked = sum(1 for d in numbers.values() if d.get('status') == 'booked')
    
    text = (
        "╔══════════════════════════════╗\n"
        f"║      📱 <b>{country}</b>\n"
        "╚══════════════════════════════╝\n"
        "\n"
        "┌──────────────────────────────┐\n"
        f"│  🟢 <b>متاحة:</b> <code>{available}</code>\n"
    )
    if booked > 0:
        text += f"│  🟡 <b>محجوزة (لك):</b> <code>{booked}</code>\n"
    text += "└──────────────────────────────┘\n"
    
    text += (
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "👇 <i>اختر رقم للعرض والشراء</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    
    edit_or_send_message(chat_id, msg_id, text, kb_user_numbers(numbers, uid))


def screen_user_view_number(chat_id, msg_id, phone, uid):
    """بطاقة الرقم — بالدولار فقط"""
    details = get_number(phone)
    if not details:
        edit_or_send_message(chat_id, msg_id, "❌ <b>الرقم غير موجود</b>", kb_back("user_buy"))
        return
    
    status = details.get('status')
    
    if status == 'booked' and str(details.get('booked_by')) != str(uid):
        edit_or_send_message(chat_id, msg_id, "🔒 <b>الرقم محجوز لمستخدم آخر</b>", kb_back("user_buy"))
        return
    if status == 'sold':
        edit_or_send_message(chat_id, msg_id, "❌ <b>الرقم مباع</b>", kb_back("user_buy"))
        return
    
    pts = details.get('price_points', 0)
    country = details.get('country', '—')
    sym = syyad_conf.get('currency_symbol', '$')
    u = get_user(uid)
    balance = u.get('points', 0)
    can_afford = balance >= pts
    
    text = (
        "╔══════════════════════════════╗\n"
        "║      📱 <b>بطاقة الرقم</b>        ║\n"
        "╚══════════════════════════════╝\n"
        "\n"
        "┌──────────────────────────────┐\n"
        f"│  📞 <b>الرقم:</b>\n"
        f"│  <code>{hide_phone(phone)}</code>\n"
        "├──────────────────────────────┤\n"
        f"│  🌍 <b>الدولة:</b> {country}\n"
        f"│  📊 <b>الحالة:</b> 🟢 متاح\n"
        "└──────────────────────────────┘\n"
        "\n"
        "┌──────────────────────────────┐\n"
        f"│  💰 <b>السعر:</b> <code>{sym}{pts}</code>\n"
        f"│  {'✅' if can_afford else '❌'} <b>رصيدك:</b> <code>{sym}{balance}</code>\n"
        "└──────────────────────────────┘\n"
    )
    
    if not can_afford:
        text += (
            "\n"
            "⚠️ <b>رصيدك غير كافٍ</b>\n"
            f"💡 تحتاج: <code>{sym}{pts - balance}</code> إضافية\n"
        )
    else:
        text += "\n✅ <i>يمكنك الشراء الآن</i>\n"
    
    kb = InlineKeyboardMarkup(row_width=1)
    if status == 'available':
        if can_afford:
            kb.add(Btn.s(f"✅ شراء بـ {sym}{pts}", f"pay_pts:{phone}"))
        else:
            kb.add(Btn.s("💳 شحن الرصيد", "user_charge"))
        kb.add(Btn.p("🛒 أرقام أخرى", "user_buy"))
    elif status == 'booked' and str(details.get('booked_by')) == str(uid):
        kb.add(Btn.d("❌ إلغاء الحجز", f"cancel_book:{phone}"))
    kb.add(Btn.d("‹ رجوع", "user_buy"))
    
    edit_or_send_message(chat_id, msg_id, text, kb)


def screen_user_payment(chat_id, msg_id, phone, uid):
    """شاشة تأكيد الدفع"""
    details = get_number(phone)
    if not details:
        edit_or_send_message(chat_id, msg_id, "❌ الرقم غير موجود", kb_back("user_buy"))
        return
    
    if details.get('status') != 'available':
        edit_or_send_message(chat_id, msg_id, "❌ الرقم غير متاح", kb_back("user_buy"))
        return
    
    pts_price = details.get('price_points', 0)
    if pts_price <= 0:
        edit_or_send_message(
            chat_id, msg_id,
            "❌ <b>السعر غير محدد</b>\n\n💡 راسل الإدارة",
            kb_back(f"view_num:{phone}")
        )
        return
    
    u = get_user(uid)
    balance = u.get('points', 0)
    sym = syyad_conf.get('currency_symbol', '$')
    can_afford = balance >= pts_price
    
    text = (
        "╔══════════════════════════════╗\n"
        "║    💳 <b>تأكيد الدفع</b>          ║\n"
        "╚══════════════════════════════╝\n"
        "\n"
        "┌──────────────────────────────┐\n"
        f"│  📱 <b>الرقم:</b>\n"
        f"│  <code>{hide_phone(phone)}</code>\n"
        "├──────────────────────────────┤\n"
        f"│  🌍 <b>الدولة:</b> {details.get('country', '—')}\n"
        "└──────────────────────────────┘\n"
        "\n"
        "┌──────────────────────────────┐\n"
        f"│  💰 <b>السعر:</b> <code>{sym}{pts_price}</code>\n"
        f"│  {'✅' if can_afford else '❌'} <b>رصيدك:</b> <code>{sym}{balance}</code>\n"
        "└──────────────────────────────┘\n"
    )
    
    if not can_afford:
        text += (
            "\n"
            "⚠️ <b>رصيدك غير كافٍ</b>\n"
            f"💡 تحتاج شحن: <code>{sym}{pts_price - balance}</code>\n"
        )
    
    kb = InlineKeyboardMarkup(row_width=1)
    if can_afford:
        kb.add(Btn.s(f"✅ دفع {sym}{pts_price}", f"pay_pts:{phone}"))
    else:
        kb.add(Btn.s("💳 شحن الرصيد", "user_charge"))
    kb.add(Btn.d("‹ رجوع", f"view_num:{phone}"))
    
    edit_or_send_message(chat_id, msg_id, text, kb)
    
# ══════════════════════════════════════════════════════════════
# 💳 PAYMENT EXECUTION
# ══════════════════════════════════════════════════════════════

def execute_payment_points(chat_id, msg_id, phone, uid):
    """تنفيذ الشراء بالرصيد"""
    details = get_number(phone)
    if not details:
        edit_or_send_message(chat_id, msg_id, "❌ الرقم غير موجود", kb_back("user_buy"))
        return
    
    if details.get('status') != 'available':
        edit_or_send_message(chat_id, msg_id, "❌ الرقم غير متاح", kb_back("user_buy"))
        return
    
    pts_price = details.get('price_points', 0)
    if pts_price <= 0:
        edit_or_send_message(chat_id, msg_id, "❌ السعر غير محدد", kb_back(f"view_num:{phone}"))
        return
    
    u = get_user(uid)
    if u.get('points', 0) < pts_price:
        sym = syyad_conf.get('currency_symbol', '$')
        edit_or_send_message(
            chat_id, msg_id,
            f"❌ <b>رصيدك غير كافٍ</b>\n\n"
            f"تحتاج: <code>{sym}{pts_price}</code>\n"
            f"عندك: <code>{sym}{u.get('points', 0)}</code>",
            InlineKeyboardMarkup(inline_keyboard=[
                [Btn.s("💳 شحن رصيدي", "user_charge")],
                [Btn.d("‹ رجوع", f"view_num:{phone}")],
            ])
        )
        return
    
    # ───── خصم الرصيد ─────
    u['points'] -= pts_price
    u['total_spent'] = u.get('total_spent', 0) + pts_price
    u['total_orders'] = u.get('total_orders', 0) + 1
    
    # ───── تحديث حالة الرقم ─────
    avail_nums[phone].update({
        'status': 'sold',
        'buyer_id': uid,
        'sold_at': now().isoformat(),
    })
    
    # ───── إلغاء أي مؤقت حجز ─────
    if phone in res_timers:
        try:
            res_timers[phone].cancel()
        except Exception:
            pass
        del res_timers[phone]
    
    # ───── تسجيل الكود ─────
    code_reqs[phone] = int(chat_id)
    
    # ═══════ إشعار قناة السجل — جديد ═══════
    notify_sale_channel(phone, uid, pts_price)
    
    # حفظ البيانات
    save_all()
    
    # ───── إرسال التسليم ─────
    send_delivery_message(chat_id, phone, uid)
    notify_admin_purchase(phone, uid, pts_price)
    update_stats('total_sales', 1)
    update_stats('total_revenue_points', pts_price)


# ══════════════════════════════════════════════════════════════
# 📦 DELIVERY MESSAGE
# ══════════════════════════════════════════════════════════════

def send_delivery_message(chat_id, phone, uid):
    """رسالة تسليم فاخرة"""
    details = get_number(phone)
    if not details:
        return
    
    two_fa = u_sessions.get(phone, {}).get('two_factor_password', None)
    has_2fa = two_fa and two_fa != 'لا يوجد'
    sym = syyad_conf.get('currency_symbol', '$')
    
    # ═══════════ الرسالة الرئيسية ═══════════
    text = (
        "╔══════════════════════════════╗\n"
        "║   🎉 <b>تم الشراء بنجاح</b>      ║\n"
        "╚══════════════════════════════╝\n"
        "\n"
        "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
        "┃   📱 <b>بيانات الرقم</b>\n"
        "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n"
        "\n"
        f"  🔹 <b>الرقم:</b>\n"
        f"     <code>{phone}</code>\n"
        "\n"
        f"  🔹 <b>الدولة:</b>\n"
        f"     {details.get('country', '—')}\n"
        "\n"
        f"  🔹 <b>السعر:</b>\n"
        f"     <code>{sym}{details.get('price_points', 0)}</code>\n"
    )
    
    if has_2fa:
        text += (
            "\n"
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            "┃   🔐 <b>كلمة المرور (2FA)</b>\n"
            "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n"
            "\n"
            f"  <blockquote><code>{two_fa}</code></blockquote>\n"
            "\n"
            "  ⚠️ <i>احتفظ بها للدخول لاحقًا</i>\n"
        )
    
    text += (
        "\n"
        "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
        "┃   📌 <b>خطوات الدخول</b>\n"
        "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n"
        "\n"
        "<blockquote>"
        "<b>1️⃣</b> افتح تطبيق تيليجرام\n"
        "\n"
        "<b>2️⃣</b> اضغط على <u>تسجيل الدخول برقم الهاتف</u>\n"
        "\n"
        f"<b>3️⃣</b> أدخل الرقم:\n"
        f"    <code>{phone}</code>\n"
        "\n"
        "<b>4️⃣</b> اضغط على زر <u>🔑 طلب كود الدخول</u> بالأسفل\n"
        "\n"
        "<b>5️⃣</b> انتظر وصول الكود هنا\n"
        "\n"
        "<b>6️⃣</b> أدخل الكود في التطبيق</blockquote>\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "\n"
        "  ⏳ <b>سيصلك الكود هنا تلقائيًا</b>\n"
        "\n"
        "  ⚠️ <u><b>لا تشارك الرقم مع أحد</b></u>\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    
    # ═══════════ الأزرار ═══════════
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(Btn.s("🔑 طلب كود الدخول", f"request_code:{phone}"))
    kb.row(
        Btn.p("👤 حسابي", "user_profile"),
        Btn.p("🛒 شراء آخر", "user_buy"),
    )
    kb.row(Btn.d("‹ القائمة الرئيسية", "user_main"))
    
    try:
        bot.send_message(chat_id, text, reply_markup=kb, parse_mode='html')
    except Exception as e:
        log(f"send_delivery: {e}", 'error')

# ══════════════════════════════════════════════════════════════
# 📢 إشعار قناة السجل (سجل الشراء)
# ══════════════════════════════════════════════════════════════

def notify_sale_channel(phone, buyer_uid, price):
    """إشعار احترافي لعملية شراء — رسالة صغيرة"""
    channel = syyad_conf.get('notify_channel_id')
    if not channel:
        log("notify_sale: قناة الإشعارات غير محددة", 'warn')
        return
    
    try:
        buyer = get_user(buyer_uid)
        buyer_name = buyer.get('first_name') or 'مستخدم'
        buyer_username = buyer.get('username')
        details = get_number(phone) or {}
        country = details.get('country', '—')
        sale_time = now().strftime('%H:%M')
        sale_date = now().strftime('%m/%d')
        sym = syyad_conf.get('currency_symbol', '$')
        
        # رقم العملية (آخر 4 من الوقت)
        order_id = now().strftime('%H%M%S')[-4:]
        
        # يوزر المشتري
        if buyer_username:
            user_tag = f"@{buyer_username}"
        else:
            user_tag = f"<code>{buyer_uid}</code>"
        
        # ───── الرقم المخفي ─────
        hidden_number = hide_phone(phone)
        
        text = (
            "╭━━━━━━━━━━━━━━╮\n"
            "   🛒 <b>شراء جديد</b>\n"
            "╰━━━━━━━━━━━━━━╯\n"
            "\n"
            f"👤 <b>{buyer_name}</b>\n"
            f"🔗 {user_tag}\n"
            "─────────────────\n"
            f"📱 <code>{hidden_number}</code>\n"
            "─────────────────\n"
            f"🌍 {country}\n"
            f"💵 <b>سعر:</b> {sym}{price}\n"
            "─────────────────\n"
            f"🕐 {sale_time}  📅 {sale_date}\n"
            f"🔖 <code>#{order_id}</code>"
        )
        
        # ═══════ زر أسفل الرسالة ═══════
        kb = InlineKeyboardMarkup(row_width=1)
        
        # الحصول على يوزر البوت
        try:
            bot_username = bot.get_me().username
        except Exception:
            bot_username = None
        
        if bot_username:
            kb.add(Btn.u(
                "🚀 بوت الأرقام",
                f"https://t.me/{bot_username}",
                'success'
            ))
        
        bot.send_message(
            channel,
            text,
            parse_mode='html',
            reply_markup=kb
        )
        log(f"✅ إشعار: {buyer_name} | #{order_id}", 'success')
        
    except Exception as e:
        log(f"❌ notify_sale: {e}", 'error')

# ══════════════════════════════════════════════════════════════
# 🔄 RESERVATIONS (نظام الحجز)
# ══════════════════════════════════════════════════════════════

async def cancel_reservation(phone, notify=True):
    """إلغاء حجز رقم"""
    if phone not in avail_nums:
        return
    details = avail_nums[phone]
    if details.get('status') != 'booked':
        return
    
    booked_by = details.get('booked_by')
    
    if phone in res_timers:
        try:
            res_timers[phone].cancel()
        except Exception:
            pass
        del res_timers[phone]
    
    avail_nums[phone].update({
        'status': 'available',
        'booked_by': None,
        'booking_time': None,
        'expiry_time': None,
        'deposit_paid_stars': None,
    })
    save_all()
    
    if notify and booked_by:
        try:
            bot.send_message(
                int(booked_by),
                f"⏰ <b>انتهى حجز الرقم</b>\n\n"
                f"📱 <code>{hide_phone(phone)}</code>\n\n"
                f"💡 الرقم متاح الآن للآخرين",
                parse_mode='html'
            )
        except Exception:
            pass


async def run_reservation_timer(phone, uid, expiry):
    """مؤقت الحجز"""
    rem = expiry - time.time()
    if rem <= 0:
        await cancel_reservation(phone, notify=False)
        return
    
    task = asyncio.create_task(asyncio.sleep(rem))
    res_timers[phone] = task
    try:
        await task
        await cancel_reservation(phone, notify=True)
    except asyncio.CancelledError:
        pass
    finally:
        if phone in res_timers:
            del res_timers[phone]


async def init_reservations():
    """تهيئة المؤقتات عند بدء البوت"""
    for phone, details in list(avail_nums.items()):
        if details.get('status') != 'booked':
            continue
        expiry = details.get('expiry_time')
        if not expiry:
            continue
        if expiry > time.time():
            asyncio.create_task(
                run_reservation_timer(phone, details.get('booked_by'), expiry)
            )
        else:
            await cancel_reservation(phone, notify=False)


# ══════════════════════════════════════════════════════════════
# 💳 CHARGE STARS (شحن الرصيد بالنجوم — مسموح)
# ══════════════════════════════════════════════════════════════

def execute_charge_stars(chat_id, uid, idx):
    """شحن الرصيد بالنجوم — هذا فقط للشحن"""
    rates = syyad_conf.get('chargeRates', [])
    if idx < 0 or idx >= len(rates):
        return
    rate = rates[idx]
    points = rate.get('points', 0)
    stars = rate.get('stars', 0)
    if points <= 0 or stars <= 0:
        return
    
    sym = syyad_conf.get('currency_symbol', '$')
    prices = [LabeledPrice(label=f"شحن {sym}{points}", amount=stars)]
    
    try:
        bot.send_invoice(
            chat_id=chat_id,
            title=f"💵 شحن {sym}{points}",
            description=f"شحن رصيد بقيمة {sym}{points} مقابل {stars} نجمة.",
            provider_token="",
            currency="XTR",
            prices=prices,
            start_parameter=f"charge_{points}",
            invoice_payload=f"charge_stars:{points}:{stars}"
        )
    except Exception as e:
        log(f"send_invoice: {e}", 'error')
        bot.send_message(chat_id, "❌ فشل إعداد الفاتورة", parse_mode='html')


# ══════════════════════════════════════════════════════════════
# 🎯 USER CALLBACKS
# ══════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda c: c.data == 'noop')
def cb_noop(call):
    answer_callback(call.id)


@bot.callback_query_handler(func=lambda c: c.data == 'cancel')
def cb_cancel(call):
    """إلغاء أي عملية"""
    uid = str(call.from_user.id)
    answer_callback(call.id, "تم الإلغاء")
    if uid in add_states:
        del add_states[uid]
    if uid in user_states:
        del user_states[uid]
    if is_admin(uid):
        screen_admin_main(call.message.chat.id, call.message.message_id)
    else:
        screen_user_main(call.message.chat.id, call.message.message_id, uid=uid)


@bot.callback_query_handler(func=lambda c: c.data == 'check_subscription')
def cb_check_sub(call):
    answer_callback(call.id, "✅ تم التحقق")
    screen_user_main(
        call.message.chat.id,
        call.message.message_id,
        user=call.from_user,
        uid=str(call.from_user.id)
    )


@bot.callback_query_handler(
    func=lambda c: (
        c.data.startswith('user_') or
        c.data.startswith('country:') or
        c.data.startswith('view_num:') or
        c.data.startswith('pay_') or
        c.data.startswith('charge_') or
        c.data.startswith('cancel_book')
    )
)
def cb_user_router(call):
    """موجّه أزرار المستخدم"""
    uid = str(call.from_user.id)
    data = call.data
    chat_id = call.message.chat.id
    msg_id = call.message.message_id
    
    # ═══════ القائمة الرئيسية ═══════
    if data == 'user_main':
        answer_callback(call.id)
        screen_user_main(chat_id, msg_id, uid=uid)
    
    elif data == 'user_profile':
        answer_callback(call.id)
        screen_user_profile(chat_id, msg_id, uid)
    
    elif data == 'user_charge':
        answer_callback(call.id)
        screen_user_charge(chat_id, msg_id, uid)
    
    elif data == 'user_charge_stars':
        answer_callback(call.id)
        screen_user_charge_stars(chat_id, msg_id)
    
    elif data == 'user_gift':
        screen_user_gift(chat_id, msg_id, uid, call.id)
    
    elif data == 'user_ref':
        answer_callback(call.id)
        screen_user_ref(chat_id, msg_id, uid)
    
    elif data == 'user_help':
        answer_callback(call.id)
        screen_user_help(chat_id, msg_id)
    
    elif data == 'user_more':
        answer_callback(call.id)
        screen_user_more(chat_id, msg_id)
    
    # ═══════ المزيد ═══════
    elif data == 'user_my_stats':
        answer_callback(call.id)
        screen_user_my_stats(chat_id, msg_id, uid)
    
    elif data == 'user_my_orders':
        answer_callback(call.id)
        screen_user_my_orders(chat_id, msg_id, uid)
    
    elif data == 'user_contact':
        answer_callback(call.id)
        screen_user_contact(chat_id, msg_id)
    
    elif data == 'user_channels':
        answer_callback(call.id)
        screen_user_channels(chat_id, msg_id)
    
    # ═══════ الشراء ═══════
    elif data == 'user_buy':
        answer_callback(call.id)
        screen_user_countries(chat_id, msg_id)
    
    elif data.startswith('country:'):
        country = data.split(':', 1)[1]
        answer_callback(call.id)
        screen_user_numbers(chat_id, msg_id, country, uid)
    
    elif data.startswith('view_num:'):
        phone = data.split(':', 1)[1]
        answer_callback(call.id)
        screen_user_view_number(chat_id, msg_id, phone, uid)
    
    elif data.startswith('pay_menu:'):
        phone = data.split(':', 1)[1]
        answer_callback(call.id)
        screen_user_payment(chat_id, msg_id, phone, uid)
    
    elif data.startswith('pay_pts:'):
        phone = data.split(':', 1)[1]
        answer_callback(call.id, "⏳ جاري الدفع...")
        execute_payment_points(chat_id, msg_id, phone, uid)
    
    # ═══════ الشحن بالنجوم ═══════
    elif data.startswith('charge_stars:'):
        idx = int(data.split(':', 1)[1])
        answer_callback(call.id, "💳 إعداد الفاتورة...")
        execute_charge_stars(chat_id, uid, idx)
    
    # ═══════ إلغاء الحجز ═══════
    elif data.startswith('cancel_book:'):
        phone = data.split(':', 1)[1]
        answer_callback(call.id, "❌ تم إلغاء الحجز")
        asyncio.run_coroutine_threadsafe(cancel_reservation(phone), telethon_loop)
        details = get_number(phone)
        if details:
            country = details.get('country')
            if country:
                time.sleep(0.5)
                screen_user_numbers(chat_id, msg_id, country, uid)
    
    else:
        answer_callback(call.id, "❓")


# ══════════════════════════════════════════════════════════════
# ✅ PAYMENT HANDLERS
# ══════════════════════════════════════════════════════════════

@bot.pre_checkout_query_handler(func=lambda q: True)
def on_pre_checkout(pre_q):
    """قبول الدفع المسبق"""
    try:
        bot.answer_pre_checkout_query(pre_q.id, ok=True)
    except Exception:
        pass


@bot.message_handler(content_types=['successful_payment'])
def on_payment(paid):
    """معالجة الدفع الناجح (شحن الرصيد بالنجوم)"""
    try:
        uid = str(paid.chat.id)
        payload = paid.successful_payment.invoice_payload
        
        if payload.startswith("charge_stars:"):
            parts = payload.split(':')
            pts = int(parts[1])
            stars = int(parts[2])
            
            add_points(uid, pts)
            add_stars(uid, stars)
            user = get_user(uid)
            new_balance = user.get('points', 0)
            sym = syyad_conf.get('currency_symbol', '$')
            
            bot.send_message(
                uid,
                f"✅ <b>تم الشحن بنجاح</b>\n\n"
                f"💵 <b>+{sym}{pts}</b>\n"
                f"⭐ <b>{stars}</b> نجمة\n"
                f"\n"
                f"💰 <b>رصيدك الآن:</b> <code>{sym}{new_balance}</code>",
                parse_mode='html',
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [Btn.s("🛒 شراء رقم", "user_buy")],
                    [Btn.d("‹ القائمة الرئيسية", "user_main")],
                ])
            )
            
            # إشعار الأدمن
            try:
                admin = str(syyad_conf['admin_ids'][0])
                bot.send_message(
                    int(admin),
                    f"⭐ <b>شحن بالنجوم</b>\n\n"
                    f"👤 <code>{uid}</code>\n"
                    f"💵 <code>{sym}{pts}</code>\n"
                    f"⭐ <code>{stars}</code>",
                    parse_mode='html'
                )
            except Exception:
                pass
            
            update_stats('total_revenue_stars', stars)
    
    except Exception as e:
        log(f"on_payment: {e}", 'error')


# ══════════════════════════════════════════════════════════════
# 🎯 COMMANDS
# ══════════════════════════════════════════════════════════════

@bot.message_handler(commands=['start'])
def cmd_start(message):
    """أمر البدء"""
    try:
        uid = str(message.from_user.id)
        text = message.text or ''
        
        # ───── معالجة الإحالة ─────
        ref_id = None
        if 'ref_' in text:
            try:
                ref_id = text.split('ref_')[1].split()[0].strip()
            except Exception:
                pass
        
        update_user_info(
            uid,
            username=message.from_user.username,
            first_name=message.from_user.first_name
        )
        
        # معالجة الإحالة
        if ref_id and ref_id != uid:
            u = get_user(uid)
            if not u.get('referred_by'):
                u['referred_by'] = ref_id
                reward = syyad_conf.get('referralPoints', 5)
                if reward > 0:
                    add_points(ref_id, reward)
                    save(USER_FILE, syyad_users)
                    try:
                        bot.send_message(
                            int(ref_id),
                            f"🎉 <b>صديق جديد سجل عبر رابطك!</b>\n\n"
                            f"💵 <b>+{syyad_conf.get('currency_symbol', '$')}{reward}</b>",
                            parse_mode='html'
                        )
                    except Exception:
                        pass
        
        # ───── عرض القائمة ─────
        if is_admin(uid):
            screen_admin_main(message.chat.id)
        else:
            screen_user_main(message.chat.id, user=message.from_user, uid=uid)
    
    except Exception as e:
        log(f"start: {e}", 'error')


@bot.message_handler(commands=['id'])
def cmd_id(message):
    """عرض الآيدي"""
    bot.reply_to(
        message,
        f"🆔 <code>{message.from_user.id}</code>",
        parse_mode='html'
    )


@bot.message_handler(commands=['help'])
def cmd_help(message):
    """المساعدة"""
    uid = str(message.from_user.id)
    if is_admin(uid):
        bot.reply_to(
            message,
            "🆘 <b>الأوامر المتاحة:</b>\n\n"
            "/start — القائمة الرئيسية\n"
            "/admin — لوحة التحكم\n"
            "/id — معلوماتك\n"
            "/help — المساعدة",
            parse_mode='html'
        )
    else:
        bot.reply_to(
            message,
            "🆘 <b>الأوامر المتاحة:</b>\n\n"
            "/start — القائمة الرئيسية\n"
            "/id — معلوماتك\n"
            "/help — المساعدة",
            parse_mode='html'
        )


@bot.message_handler(commands=['admin'])
def cmd_admin(message):
    """لوحة التحكم — للأدمن فقط"""
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ ليس لديك صلاحية")
        return
    screen_admin_main(message.chat.id)
    
# ══════════════════════════════════════════════════════════════
# 👑 KEYBOARDS - ADMIN
# ══════════════════════════════════════════════════════════════

def kb_admin_back(target="adm_main"):
    """زر رجوع للأدمن"""
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(Btn.d("‹ رجوع", target))
    return kb


def kb_admin_main():
    """القائمة الرئيسية للأدمن"""
    kb = InlineKeyboardMarkup(row_width=2)
    kb.row(
        Btn.p("📱 الأرقام", "adm_nums"),
        Btn.p("💰 المبيعات", "adm_sales"),
    )
    kb.row(
        Btn.p("📊 الإحصائيات", "adm_stats"),
        Btn.p("👥 الأدمنية", "adm_admins"),
    )
    kb.row(
        Btn.p("⚙️ الإعدادات", "adm_settings"),
        Btn.p("🎨 التخصيص", "adm_custom"),
    )
    kb.row(
        Btn.p("📢 البث", "adm_broadcast"),
        Btn.p("📋 السجل", "adm_logs"),
    )
    kb.row(
        Btn.s("🎁 الشحن اليدوي", "adm_charge"),
        Btn.p("🔍 بحث مستخدم", "adm_users_search"),
    )
    kb.row(Btn.d("‹ القائمة الرئيسية", "user_main"))
    return kb


def kb_admin_numbers():
    """قائمة إدارة الأرقام"""
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(Btn.s("➕ إضافة رقم جديد", "adm_add_num"))
    kb.row(
        Btn.p("📋 كل الأرقام", "adm_list_nums"),
        Btn.p("🟢 المتاحة", "adm_avail_nums"),
    )
    kb.row(
        Btn.p("🟡 المحجوزة", "adm_booked_nums"),
        Btn.p("🔴 المباعة", "adm_sold_nums"),
    )
    kb.add(Btn.d("🗑️ حذف رقم", "adm_del_num"))
    kb.add(Btn.d("‹ رجوع", "adm_main"))
    return kb


def kb_admin_number_view(phone):
    """أزرار عرض رقم في الأدمن"""
    kb = InlineKeyboardMarkup(row_width=1)
    details = get_number(phone)
    if details and details.get('status') == 'available':
        kb.add(Btn.s("💰 تغيير السعر", f"adm_edit_price:{phone}"))
    kb.add(Btn.d("🗑️ حذف الرقم", f"adm_del_confirm:{phone}"))
    kb.add(Btn.p("‹ رجوع", "adm_nums"))
    return kb


def kb_admin_delete_numbers():
    """قائمة حذف الأرقام"""
    kb = InlineKeyboardMarkup(row_width=1)
    for phone in list(avail_nums.keys())[:30]:
        kb.add(Btn.d(f"❌ {hide_phone(phone)}", f"adm_del_confirm:{phone}"))
    kb.add(Btn.p("‹ رجوع", "adm_nums"))
    return kb


def kb_admin_confirm_delete(phone):
    """تأكيد الحذف"""
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(Btn.d("✅ نعم، احذف", f"adm_del_exec:{phone}"))
    kb.add(Btn.p("❌ إلغاء", "adm_nums"))
    return kb


def kb_admin_admins():
    """قائمة الأدمنية"""
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(Btn.s("➕ رفع أدمن", "adm_add_admin"))
    kb.add(Btn.d("➖ تنزيل أدمن", "adm_remove_admin"))
    kb.add(Btn.p("📋 عرض القائمة", "adm_list_admins"))
    kb.add(Btn.d("‹ رجوع", "adm_main"))
    return kb


def kb_admin_settings():
    """قائمة الإعدادات"""
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(Btn.s("💵 باقات شحن الدولار", "adm_set_rates"))
    kb.add(Btn.p("🎁 رصيد الهدية اليومية", "adm_set_gift"))
    kb.add(Btn.p("🔗 نقاط الإحالة", "adm_set_ref"))
    kb.add(Btn.p("💱 تعديل اسم العملة", "adm_set_currency"))
    kb.add(Btn.p("👨‍💻 يوزر المطور", "adm_set_developer"))
    kb.add(Btn.p("📢 قناة النشر", "adm_set_channel"))
    kb.add(Btn.p("🔔 قناة الإشعارات", "adm_set_notify_channel"))
    kb.add(Btn.p("📣 رابط قناة الطلبات", "adm_set_main_channel"))
    kb.add(Btn.p("📺 قنوات التفعيل", "adm_set_activation"))
    kb.add(Btn.d("‹ رجوع", "adm_main"))
    return kb


def kb_admin_rates(rates):
    """باقات الشحن"""
    kb = InlineKeyboardMarkup(row_width=1)
    sym = syyad_conf.get('currency_symbol', '$')
    if not rates:
        kb.add(Btn.p("📭 لا توجد باقات", "noop"))
    else:
        for idx, r in enumerate(rates):
            points = r.get('points', 0)
            stars = r.get('stars', 0)
            kb.add(Btn.d(f"🗑️ حذف {sym}{points} = ⭐{stars}", f"adm_del_rate:{idx}"))
    kb.add(Btn.s("➕ إضافة باقة جديدة", "adm_add_rate"))
    kb.add(Btn.d("‹ رجوع", "adm_settings"))
    return kb


def kb_admin_activation(channels):
    """قنوات التفعيل"""
    kb = InlineKeyboardMarkup(row_width=1)
    if not channels:
        kb.add(Btn.p("📭 لا توجد قنوات", "noop"))
    else:
        for idx, ch in enumerate(channels):
            kb.add(Btn.d(f"🗑️ حذف {ch}", f"adm_del_channel:{idx}"))
    kb.add(Btn.s("➕ إضافة قناة", "adm_add_channel"))
    kb.add(Btn.d("‹ رجوع", "adm_settings"))
    return kb


def kb_admin_sales():
    """قائمة المبيعات"""
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(Btn.p("📋 آخر المبيعات", "adm_recent_sales"))
    kb.add(Btn.p("📊 إحصائيات المبيعات", "adm_sales_stats"))
    kb.add(Btn.d("‹ رجوع", "adm_main"))
    return kb


def kb_admin_charge():
    """الشحن اليدوي"""
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(Btn.s("💵 إضافة رصيد", "adm_add_pts"))
    kb.add(Btn.s("⭐ إضافة نجوم", "adm_add_stars"))
    kb.add(Btn.p("💵 خصم رصيد", "adm_remove_pts"))
    kb.add(Btn.d("‹ رجوع", "adm_main"))
    return kb


# ══════════════════════════════════════════════════════════════
# 🎨 KEYBOARDS - ADMIN CUSTOMIZATION
# ══════════════════════════════════════════════════════════════

def kb_admin_custom():
    """قائمة التخصيص"""
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(Btn.s("🎨 تغيير ألوان الأزرار", "adm_custom_colors"))
    kb.add(Btn.p("➕ إضافة صف جديد", "adm_custom_add_row"))
    kb.add(Btn.p("📋 عرض الصفوف", "adm_custom_list"))
    kb.add(Btn.d("🗑️ حذف صف", "adm_custom_del"))
    kb.add(Btn.d("‹ رجوع", "adm_main"))
    return kb


def kb_admin_colors():
    """أزرار تخصيص الألوان"""
    kb = InlineKeyboardMarkup(row_width=1)
    items = [
        ('buy', '🛒 شراء رقم'),
        ('charge', '💳 شحن رصيدي'),
        ('profile', '👤 حسابي'),
        ('gift', '🎁 هدية يومية'),
        ('ref', '🔗 إحالة'),
        ('help', '🆘 مساعدة'),
        ('channel', '📢 قناة الطلبات'),
        ('admin', '👑 لوحة التحكم'),
    ]
    for key, label in items:
        kb.add(Btn.p(f"{label}", f"adm_color_edit:{key}"))
    kb.add(Btn.d("‹ رجوع", "adm_custom"))
    return kb


def kb_admin_color_choices(color_key):
    """اختيار اللون"""
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(Btn.p("🔵 أزرق", f"adm_color_set:{color_key}:primary"))
    kb.add(Btn.s("🟢 أخضر", f"adm_color_set:{color_key}:success"))
    kb.add(Btn.d("🔴 أحمر", f"adm_color_set:{color_key}:danger"))
    kb.add(Btn.d("‹ رجوع", "adm_custom_colors"))
    return kb


# ══════════════════════════════════════════════════════════════
# 🎨 SCREENS - ADMIN (MAIN)
# ══════════════════════════════════════════════════════════════

def screen_admin_main(chat_id, message_id=None):
    """القائمة الرئيسية للأدمن"""
    text = (
        "╔══════════════════════════════╗\n"
        "║   👑 <b>لوحة تحكم الأدمن</b>       ║\n"
        "╚══════════════════════════════╝\n"
        "\n"
        "🔥 <b>أهلاً بك يا ملك</b>\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ <i>اختر القسم المناسب</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    if message_id:
        edit_or_send_message(chat_id, message_id, text, kb_admin_main())
    else:
        bot.send_message(chat_id, text, reply_markup=kb_admin_main(), parse_mode='html')


def screen_admin_numbers(chat_id, message_id):
    """إدارة الأرقام"""
    nums = count_numbers()
    text = (
        "╔══════════════════════════════╗\n"
        "║      📱 <b>إدارة الأرقام</b>       ║\n"
        "╚══════════════════════════════╝\n"
        "\n"
        "┌──────────────────────────────┐\n"
        f"│  🟢 <b>متاحة:</b> <code>{nums['available']}</code>\n"
        f"│  🟡 <b>محجوزة:</b> <code>{nums['booked']}</code>\n"
        f"│  🔴 <b>مباعة:</b> <code>{nums['sold']}</code>\n"
        f"│  📦 <b>المجموع:</b> <code>{nums['total']}</code>\n"
        "└──────────────────────────────┘\n"
        "\n"
        "⚡ اختر إجراء:"
    )
    edit_or_send_message(chat_id, message_id, text, kb_admin_numbers())


def screen_admin_list_numbers(chat_id, msg_id, page=0, per_page=15):
    """كل الأرقام مع pagination"""
    if not avail_nums:
        edit_or_send_message(chat_id, msg_id, "📭 <b>لا توجد أرقام</b>", kb_admin_back("adm_nums"))
        return
    all_numbers = list(avail_nums.items())
    total = len(all_numbers)
    total_pages = max((total + per_page - 1) // per_page, 1)
    start = page * per_page
    page_numbers = all_numbers[start:start + per_page]
    sym = syyad_conf.get('currency_symbol', '$')

    text = (
        "╭──────────────────────────╮\n"
        "  📋 <b>كل الأرقام</b>\n"
        "╰──────────────────────────╯\n\n"
        f"📊 <b>العدد:</b> <code>{total}</code>\n"
        f"📄 <b>الصفحة:</b> <code>{page + 1}/{total_pages}</code>\n\n"
    )
    kb = InlineKeyboardMarkup(row_width=1)
    for phone, details in page_numbers:
        status = details.get('status', 'available')
        emoji = {'available': '🟢', 'booked': '🟡', 'sold': '🔴'}.get(status, '⚪')
        pts = details.get('price_points', 0)
        text += f"{emoji} <code>{hide_phone(phone)}</code> • {sym}{pts}\n"
        kb.add(Btn.p(f"{emoji} {hide_phone(phone)} — {sym}{pts}", f"adm_view_num:{phone}"))
    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(Btn.p("‹", f"adm_list_page:{page - 1}"))
        nav.append(Btn.p(f"{page + 1}/{total_pages}", "noop"))
        if page + 1 < total_pages:
            nav.append(Btn.p("›", f"adm_list_page:{page + 1}"))
        kb.add(*nav)
    kb.add(Btn.d("‹ رجوع", "adm_nums"))
    edit_or_send_message(chat_id, msg_id, text, kb)


def screen_admin_filter_numbers(chat_id, msg_id, status, page=0, per_page=15):
    """فلترة الأرقام (متاحة/محجوزة/مباعة)"""
    if status == 'available':
        filtered = get_available_numbers()
        title = "🟢 المتاحة"
    elif status == 'booked':
        filtered = get_booked_numbers()
        title = "🟡 المحجوزة"
    elif status == 'sold':
        filtered = get_sold_numbers()
        title = "🔴 المباعة"
    else:
        return
    if not filtered:
        edit_or_send_message(chat_id, msg_id, f"{title}\n\n📭 لا توجد أرقام", kb_admin_back("adm_nums"))
        return
    all_items = list(filtered.items())
    total = len(all_items)
    total_pages = max((total + per_page - 1) // per_page, 1)
    page_items = all_items[page * per_page:page * per_page + per_page]
    sym = syyad_conf.get('currency_symbol', '$')

    text = (
        "╭──────────────────────────╮\n"
        f"  {title}\n"
        "╰──────────────────────────╯\n\n"
        f"📊 العدد: <code>{total}</code>\n"
        f"📄 الصفحة: <code>{page + 1}/{total_pages}</code>\n\n"
    )
    kb = InlineKeyboardMarkup(row_width=1)
    for phone, details in page_items:
        pts = details.get('price_points', 0)
        text += f"📱 <code>{hide_phone(phone)}</code> • {sym}{pts}\n"
        kb.add(Btn.p(f"📱 {hide_phone(phone)} — {sym}{pts}", f"adm_view_num:{phone}"))
    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(Btn.p("‹", f"adm_filter_page:{status}:{page - 1}"))
        nav.append(Btn.p(f"{page + 1}/{total_pages}", "noop"))
        if page + 1 < total_pages:
            nav.append(Btn.p("›", f"adm_filter_page:{status}:{page + 1}"))
        kb.add(*nav)
    kb.add(Btn.d("‹ رجوع", "adm_nums"))
    edit_or_send_message(chat_id, msg_id, text, kb)


def screen_admin_view_number(chat_id, msg_id, phone):
    """عرض تفاصيل رقم"""
    details = get_number(phone)
    if not details:
        edit_or_send_message(chat_id, msg_id, "❌ غير موجود", kb_admin_back("adm_nums"))
        return
    status = details.get('status', 'available')
    status_map = {'available': '🟢 متاح', 'booked': '🟡 محجوز', 'sold': '🔴 مباع'}
    sym = syyad_conf.get('currency_symbol', '$')
    text = (
        "╭──────────────────────────╮\n"
        "  📱 <b>تفاصيل الرقم</b>\n"
        "╰──────────────────────────╯\n\n"
        f"📞 <b>الرقم:</b> <code>{phone}</code>\n"
        f"🌍 <b>الدولة:</b> {details.get('country', '—')}\n"
        f"💵 <b>السعر:</b> <code>{sym}{details.get('price_points', 0)}</code>\n"
        f"📊 <b>الحالة:</b> {status_map.get(status, status)}\n"
    )
    edit_or_send_message(chat_id, msg_id, text, kb_admin_number_view(phone))


def screen_admin_delete_menu(chat_id, msg_id):
    """قائمة حذف رقم"""
    if not avail_nums:
        edit_or_send_message(chat_id, msg_id, "📭 لا توجد أرقام", kb_admin_back("adm_nums"))
        return
    edit_or_send_message(chat_id, msg_id, "🗑️ <b>حذف رقم</b>\n\nاختر:", kb_admin_delete_numbers())


def screen_admin_confirm_delete(chat_id, msg_id, phone):
    """تأكيد الحذف"""
    details = get_number(phone)
    if not details:
        return
    text = (
        f"⚠️ <b>تأكيد الحذف</b>\n\n"
        f"📱 <code>{phone}</code>\n"
        f"🌍 {details.get('country', '—')}\n\n"
        f"❓ هل أنت متأكد؟"
    )
    edit_or_send_message(chat_id, msg_id, text, kb_admin_confirm_delete(phone))


def execute_delete_number(chat_id, msg_id, phone):
    """تنفيذ الحذف"""
    if phone in u_clients:
        try:
            asyncio.run_coroutine_threadsafe(u_clients[phone].disconnect(), telethon_loop)
        except Exception:
            pass
        del u_clients[phone]
    if phone in res_timers:
        try:
            res_timers[phone].cancel()
        except Exception:
            pass
        del res_timers[phone]
    if phone in u_sessions:
        del u_sessions[phone]
    remove_number(phone)
    save_all()
    screen_admin_numbers(chat_id, msg_id)

def screen_admin_admins_menu(chat_id, msg_id):
    """قائمة إدارة الأدمنية — مع أزرار الإضافة"""
    admins = syyad_conf.get('admin_ids', [])
    text = (
        "╭──────────────────────────╮\n"
        "  👥 <b>إدارة الأدمنية</b>\n"
        "╰──────────────────────────╯\n\n"
        f"📊 <b>العدد:</b> <code>{len(admins)}</code>\n\n"
    )
    for i, adm in enumerate(admins, 1):
        text += f"{i}. <code>{adm}</code>\n"
    
    text += "\n⚡ اختر إجراء:"
    
    edit_or_send_message(chat_id, msg_id, text, kb_admin_admins())

def screen_admin_list_admins(chat_id, msg_id):
    """قائمة الأدمنية"""
    admins = syyad_conf.get('admin_ids', [])
    text = "📋 <b>قائمة الأدمنية</b>\n\n"
    for i, adm in enumerate(admins, 1):
        text += f"{i}. <code>{adm}</code>\n"
    edit_or_send_message(chat_id, msg_id, text, kb_admin_back("adm_admins"))


def screen_admin_settings(chat_id, msg_id):
    """الإعدادات"""
    cfg = syyad_conf
    sym = cfg.get('currency_symbol', '$')
    text = (
        "⚙️ <b>الإعدادات</b>\n\n"
        f"💵 <b>العملة:</b> {cfg.get('currency_name', 'دولار')} ({sym})\n"
        f"🎁 <b>الهدية:</b> <code>{sym}{cfg.get('dailyGiftPoints', 0)}</code>\n"
        f"🔗 <b>الإحالة:</b> <code>{sym}{cfg.get('referralPoints', 0)}</code>\n"
        f"💳 <b>الباقات:</b> <code>{len(cfg.get('chargeRates', []))}</code>\n"
        f"👨‍💻 <b>المطور:</b> @{cfg.get('developer_username', 'MO_5_H')}\n"
    )
    edit_or_send_message(chat_id, msg_id, text, kb_admin_settings())


def screen_admin_rates(chat_id, msg_id):
    """باقات الشحن"""
    rates = syyad_conf.get('chargeRates', [])
    sym = syyad_conf.get('currency_symbol', '$')
    text = "💵 <b>باقات شحن الدولار</b>\n\n"
    if rates:
        for idx, r in enumerate(rates, 1):
            text += f"{idx}. 💵 <b>{sym}{r.get('points', 0)}</b> = ⭐ <b>{r.get('stars', 0)}</b>\n"
    else:
        text += "📭 لا توجد باقات\n"
    edit_or_send_message(chat_id, msg_id, text, kb_admin_rates(rates))


def screen_admin_activation(chat_id, msg_id):
    """قنوات التفعيل"""
    channels = syyad_conf.get('activation_channels', [])
    text = "📺 <b>قنوات التفعيل</b>\n\n"
    if channels:
        for idx, ch in enumerate(channels, 1):
            text += f"{idx}. 📢 <code>{ch}</code>\n"
    else:
        text += "📭 لا توجد قنوات\n"
    edit_or_send_message(chat_id, msg_id, text, kb_admin_activation(channels))


def screen_admin_sales(chat_id, message_id):
    """المبيعات"""
    sold = get_sold_numbers()
    total = sum(d.get('price_points', 0) for d in sold.values())
    sym = syyad_conf.get('currency_symbol', '$')
    text = (
        "💰 <b>المبيعات</b>\n\n"
        f"📊 <b>الأرقام المباعة:</b> <code>{len(sold)}</code>\n"
        f"💵 <b>الإيرادات:</b> <code>{sym}{total}</code>"
    )
    edit_or_send_message(chat_id, message_id, text, kb_admin_sales())


def screen_admin_recent_sales(chat_id, msg_id):
    """آخر المبيعات"""
    sold = get_sold_numbers()
    if not sold:
        edit_or_send_message(chat_id, msg_id, "📭 لا توجد مبيعات", kb_admin_back("adm_sales"))
        return
    sorted_sales = sorted(sold.items(), key=lambda x: x[1].get('sold_at', ''), reverse=True)[:10]
    sym = syyad_conf.get('currency_symbol', '$')
    text = "📋 <b>آخر المبيعات</b>\n\n"
    for phone, details in sorted_sales:
        text += (
            f"📱 <code>{hide_phone(phone)}</code>\n"
            f"   💵 {sym}{details.get('price_points', 0)}\n"
            f"   👤 <code>{details.get('buyer_id', '—')}</code>\n"
        )
    edit_or_send_message(chat_id, msg_id, text, kb_admin_back("adm_sales"))


def screen_admin_sales_stats(chat_id, msg_id):
    """إحصائيات المبيعات"""
    sold = get_sold_numbers()
    total = sum(d.get('price_points', 0) for d in sold.values())
    sym = syyad_conf.get('currency_symbol', '$')
    text = (
        "📊 <b>إحصائيات المبيعات</b>\n\n"
        f"📦 <b>الطلبات:</b> <code>{len(sold)}</code>\n"
        f"💵 <b>الإيرادات:</b> <code>{sym}{total}</code>"
    )
    edit_or_send_message(chat_id, msg_id, text, kb_admin_back("adm_sales"))


def screen_admin_stats(chat_id, msg_id):
    """إحصائيات عامة"""
    nums = count_numbers()
    total_users = len(syyad_users)
    sold = get_sold_numbers()
    total_pts = sum(d.get('price_points', 0) for d in sold.values())
    sym = syyad_conf.get('currency_symbol', '$')
    text = (
        "📊 <b>إحصائيات</b>\n\n"
        f"👥 المستخدمون: <code>{total_users}</code>\n"
        f"📱 الأرقام: <code>{nums['total']}</code>\n"
        f"🟢 متاحة: <code>{nums['available']}</code>\n"
        f"🟡 محجوزة: <code>{nums['booked']}</code>\n"
        f"🔴 مباعة: <code>{nums['sold']}</code>\n"
        f"💵 الإيرادات: <code>{sym}{total_pts}</code>"
    )
    edit_or_send_message(chat_id, msg_id, text, kb_admin_back("adm_stats"))


def screen_admin_logs(chat_id, msg_id, limit=25):
    """السجل"""
    if not os.path.exists(LOG_FILE):
        edit_or_send_message(chat_id, msg_id, "📭 لا يوجد سجل", kb_admin_back("adm_main"))
        return
    from collections import deque
    with open(LOG_FILE, 'r', encoding='utf-8') as f:
        lines = list(deque(f, maxlen=limit))
    text = f"📋 <b>آخر {limit} عملية</b>\n\n"
    for line in lines:
        text += f"<code>{line.strip()[:80]}</code>\n"
    if len(text) > 4000:
        text = text[:3900] + "\n<i>...</i>"
    edit_or_send_message(chat_id, msg_id, text, kb_admin_back("adm_main"))


def screen_admin_charge(chat_id, message_id):
    """الشحن اليدوي"""
    text = "💰 <b>الشحن اليدوي</b>\n\n⚡ اختر نوع الشحن:"
    edit_or_send_message(chat_id, message_id, text, kb_admin_charge())


# ══════════════════════════════════════════════════════════════
# 🎨 SCREENS - ADMIN CUSTOMIZATION
# ══════════════════════════════════════════════════════════════

def screen_admin_custom(chat_id, msg_id):
    """التخصيص"""
    colors = syyad_conf.get('main_buttons_colors', DEFAULT_MAIN_COLORS)
    rows = syyad_conf.get('custom_main_rows', [])
    text = (
        "╔══════════════════════════════╗\n"
        "║   🎨 <b>تخصيص القائمة</b>        ║\n"
        "╚══════════════════════════════╝\n"
        "\n"
        "┌──────────────────────────────┐\n"
        "│  🎨 <b>ألوان الأزرار:</b>\n"
        f"│  🛒 شراء: <code>{colors.get('buy')}</code>\n"
        f"│  💳 شحن: <code>{colors.get('charge')}</code>\n"
        f"│  👤 حسابي: <code>{colors.get('profile')}</code>\n"
        f"│  🎁 هدية: <code>{colors.get('gift')}</code>\n"
        "└──────────────────────────────┘\n"
        "\n"
        f"➕ <b>الصفوف المخصصة:</b> <code>{len(rows)}</code>\n"
        "\n"
        "⚡ اختر إجراء:"
    )
    edit_or_send_message(chat_id, msg_id, text, kb_admin_custom())


def screen_admin_colors(chat_id, msg_id):
    """ألوان الأزرار"""
    colors = syyad_conf.get('main_buttons_colors', DEFAULT_MAIN_COLORS)
    text = (
        "🎨 <b>ألوان الأزرار الرئيسية</b>\n\n"
        "الألوان المتاحة:\n"
        "🔵 primary | 🟢 success | 🔴 danger\n\n"
        "┌──────────────────────────────┐\n"
        f"│  🛒 شراء: <code>{colors.get('buy', 'success')}</code>\n"
        f"│  💳 شحن: <code>{colors.get('charge', 'primary')}</code>\n"
        f"│  👤 حسابي: <code>{colors.get('profile', 'primary')}</code>\n"
        f"│  🎁 هدية: <code>{colors.get('gift', 'success')}</code>\n"
        f"│  🔗 إحالة: <code>{colors.get('ref', 'primary')}</code>\n"
        f"│  🆘 مساعدة: <code>{colors.get('help', 'danger')}</code>\n"
        f"│  📢 قناة: <code>{colors.get('channel', 'primary')}</code>\n"
        f"│  👑 أدمن: <code>{colors.get('admin', 'danger')}</code>\n"
        "└──────────────────────────────┘\n\n"
        "👇 اضغط على الزر لتغيير لونه:"
    )
    edit_or_send_message(chat_id, msg_id, text, kb_admin_colors())


def screen_admin_color_choices(chat_id, msg_id, color_key):
    """اختيار لون محدد"""
    labels = {
        'buy': '🛒 شراء رقم',
        'charge': '💳 شحن رصيدي',
        'profile': '👤 حسابي',
        'gift': '🎁 هدية يومية',
        'ref': '🔗 إحالة',
        'help': '🆘 مساعدة',
        'channel': '📢 قناة الطلبات',
        'admin': '👑 لوحة التحكم',
    }
    label = labels.get(color_key, color_key)
    colors = syyad_conf.get('main_buttons_colors', DEFAULT_MAIN_COLORS)
    current = colors.get(color_key, 'primary')
    
    text = (
        f"🎨 <b>تغيير لون: {label}</b>\n\n"
        f"اللون الحالي: <code>{current}</code>\n\n"
        "اختر اللون الجديد:"
    )
    edit_or_send_message(chat_id, msg_id, text, kb_admin_color_choices(color_key))


def screen_admin_custom_list(chat_id, msg_id):
    """الصفوف المخصصة"""
    rows = syyad_conf.get('custom_main_rows', [])
    text = "📋 <b>الصفوف المخصصة</b>\n\n"
    if not rows:
        text += "📭 لا توجد صفوف مخصصة\n"
    else:
        for i, row in enumerate(rows, 1):
            status = "✅" if row.get('enabled', True) else "❌"
            text += f"{i}. {status} <b>{row.get('name', 'صف')}</b>\n"
            for b in row.get('buttons', []):
                text += f"   • {b.get('label')} [{b.get('color', 'primary')}]\n"
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(Btn.d("‹ رجوع", "adm_custom"))
    edit_or_send_message(chat_id, msg_id, text, kb)


# ══════════════════════════════════════════════════════════════
# 🔧 ADMIN - START FLOWS
# ══════════════════════════════════════════════════════════════

def start_set_gift(chat_id, msg_id):
    current = syyad_conf.get('dailyGiftPoints', 0)
    sym = syyad_conf.get('currency_symbol', '$')
    add_states[str(chat_id)] = {'step': 'set_gift'}
    text = f"🎁 <b>رصيد الهدية اليومية</b>\n\n💵 الحالي: <code>{sym}{current}</code>\n\n📝 أرسل الرصيد الجديد:"
    edit_or_send_message(chat_id, msg_id, text, kb_cancel())


def start_set_ref(chat_id, msg_id):
    current = syyad_conf.get('referralPoints', 0)
    sym = syyad_conf.get('currency_symbol', '$')
    add_states[str(chat_id)] = {'step': 'set_ref'}
    text = f"🔗 <b>مكافأة الإحالة</b>\n\n💵 الحالي: <code>{sym}{current}</code>\n\n📝 أرسل المكافأة الجديدة:"
    edit_or_send_message(chat_id, msg_id, text, kb_cancel())


def start_set_currency(chat_id, msg_id):
    current_name = syyad_conf.get('currency_name', 'دولار')
    current_sym = syyad_conf.get('currency_symbol', '$')
    add_states[str(chat_id)] = {'step': 'set_currency_name'}
    text = f"💱 <b>تعديل العملة</b>\n\n💵 الحالي: {current_name} ({current_sym})\n\n📝 أرسل اسم العملة الجديد:"
    edit_or_send_message(chat_id, msg_id, text, kb_cancel())


def start_set_developer(chat_id, msg_id):
    current = syyad_conf.get('developer_username', 'MO_5_H')
    add_states[str(chat_id)] = {'step': 'set_developer'}
    text = f"👨‍💻 <b>يوزر المطور</b>\n\n👤 الحالي: @{current}\n\n📝 أرسل اليوزر بدون @:"
    edit_or_send_message(chat_id, msg_id, text, kb_cancel())


def start_set_channel(chat_id, msg_id):
    current = syyad_conf.get('publish_channel_id') or "غير محدد"
    add_states[str(chat_id)] = {'step': 'set_channel'}
    text = f"📢 <b>قناة النشر</b>\n\n📺 الحالية: <code>{current}</code>\n\n📝 أرسل معرف القناة أو <code>حذف</code>:"
    edit_or_send_message(chat_id, msg_id, text, kb_cancel())


def start_set_notify_channel(chat_id, msg_id):
    current = syyad_conf.get('notify_channel_id') or "غير محدد"
    add_states[str(chat_id)] = {'step': 'set_notify_channel'}
    text = f"🔔 <b>قناة الإشعارات</b>\n\n📺 الحالية: <code>{current}</code>\n\n📝 أرسل معرف القناة أو <code>حذف</code>:"
    edit_or_send_message(chat_id, msg_id, text, kb_cancel())


def start_set_main_channel(chat_id, msg_id):
    current = syyad_conf.get('main_channel_url') or "غير محدد"
    add_states[str(chat_id)] = {'step': 'set_main_channel'}
    text = f"📣 <b>رابط قناة الطلبات</b>\n\n🔗 الحالي: <code>{current}</code>\n\n📝 أرسل الرابط أو <code>حذف</code>:"
    edit_or_send_message(chat_id, msg_id, text, kb_cancel())


def start_add_channel(chat_id, msg_id):
    add_states[str(chat_id)] = {'step': 'add_channel'}
    text = "➕ <b>إضافة قناة تفعيل</b>\n\n📝 أرسل معرف القناة:"
    edit_or_send_message(chat_id, msg_id, text, kb_cancel())


def start_add_rate(chat_id, msg_id):
    add_states[str(chat_id)] = {'step': 'rate_points'}
    text = "➕ <b>باقة شحن جديدة</b>\n\n📝 الخطوة 1/2: أرسل مبلغ الدولار:"
    edit_or_send_message(chat_id, msg_id, text, kb_cancel())


def start_add_admin(chat_id, msg_id):
    add_states[str(chat_id)] = {'step': 'add_admin'}
    text = "➕ <b>إضافة أدمن</b>\n\n📝 أرسل آيدي المستخدم:"
    edit_or_send_message(chat_id, msg_id, text, kb_cancel())


def start_remove_admin(chat_id, msg_id):
    add_states[str(chat_id)] = {'step': 'remove_admin'}
    text = "➖ <b>إزالة أدمن</b>\n\n📝 أرسل آيدي المستخدم:"
    edit_or_send_message(chat_id, msg_id, text, kb_cancel())


def start_add_points(chat_id, msg_id):
    add_states[str(chat_id)] = {'step': 'add_pts_uid'}
    text = "💵 <b>إضافة رصيد</b>\n\n📝 الخطوة 1/2: أرسل آيدي المستخدم:"
    edit_or_send_message(chat_id, msg_id, text, kb_cancel())


def start_remove_points(chat_id, msg_id):
    add_states[str(chat_id)] = {'step': 'remove_pts_uid'}
    text = "💵 <b>خصم رصيد</b>\n\n📝 الخطوة 1/2: أرسل آيدي المستخدم:"
    edit_or_send_message(chat_id, msg_id, text, kb_cancel())


def start_add_stars(chat_id, msg_id):
    add_states[str(chat_id)] = {'step': 'add_stars_uid'}
    text = "⭐ <b>إضافة نجوم</b>\n\n📝 الخطوة 1/2: أرسل آيدي المستخدم:"
    edit_or_send_message(chat_id, msg_id, text, kb_cancel())


def start_broadcast(chat_id, msg_id):
    add_states[str(chat_id)] = {'step': 'broadcast'}
    total = len(syyad_users)
    text = f"📢 <b>بث جماعي</b>\n\n👥 المستخدمون: <code>{total}</code>\n\n📝 أرسل الرسالة:"
    edit_or_send_message(chat_id, msg_id, text, kb_cancel())


def start_add_number(chat_id, msg_id):
    add_states[str(chat_id)] = {'step': 'phone'}
    text = (
        "➕ <b>إضافة رقم جديد</b>\n\n"
        "📝 الخطوة 1/4: أرسل الرقم بالصيغة الدولية:\n"
        "مثال: <code>+967777123456</code>"
    )
    edit_or_send_message(chat_id, msg_id, text, kb_cancel())


def start_edit_price(chat_id, msg_id, phone):
    details = get_number(phone)
    if not details:
        return
    pts = details.get('price_points', 0)
    sym = syyad_conf.get('currency_symbol', '$')
    add_states[str(chat_id)] = {'step': 'edit_price', 'edit_phone': phone}
    text = f"✏️ <b>تعديل السعر</b>\n\n📱 <code>{phone}</code>\n💵 الحالي: <code>{sym}{pts}</code>\n\n📝 أرسل السعر الجديد:"
    edit_or_send_message(chat_id, msg_id, text, kb_cancel())


def start_search_user(chat_id, msg_id):
    add_states[str(chat_id)] = {'step': 'search_user'}
    text = "🔍 <b>بحث عن مستخدم</b>\n\n📝 أرسل آيدي أو @username أو اسم:"
    edit_or_send_message(chat_id, msg_id, text, kb_cancel())


def start_custom_add_row(chat_id, msg_id):
    add_states[str(chat_id)] = {'step': 'custom_row_name'}
    text = "➕ <b>إضافة صف جديد للقائمة</b>\n\n📝 الخطوة 1/3: أرسل اسم الصف:"
    edit_or_send_message(chat_id, msg_id, text, kb_cancel())


def execute_delete_rate(chat_id, msg_id, idx):
    rates = syyad_conf.get('chargeRates', [])
    if 0 <= idx < len(rates):
        rates.pop(idx)
        save_all()
    screen_admin_rates(chat_id, msg_id)


def execute_delete_channel(chat_id, msg_id, idx):
    channels = syyad_conf.get('activation_channels', [])
    if 0 <= idx < len(channels):
        channels.pop(idx)
        save_all()
    screen_admin_activation(chat_id, msg_id)


def execute_delete_custom_row(chat_id, msg_id, idx):
    rows = syyad_conf.get('custom_main_rows', [])
    if 0 <= idx < len(rows):
        rows.pop(idx)
        save_all()
    screen_admin_custom(chat_id, msg_id)


# ══════════════════════════════════════════════════════════════
# 🎯 ADMIN CALLBACKS
# ══════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda c: c.data.startswith('adm_'))
def cb_admin_router(call):
    """موجّه أزرار الأدمن"""
    uid = str(call.from_user.id)
    data = call.data
    chat_id = call.message.chat.id
    msg_id = call.message.message_id

    if not is_admin(uid):
        answer_callback(call.id, "⛔ ليس لديك صلاحية", alert=True)
        return

    # ═══════ القائمة الرئيسية ═══════
    if data == 'adm_main':
        answer_callback(call.id); screen_admin_main(chat_id, msg_id)
    elif data == 'adm_nums':
        answer_callback(call.id); screen_admin_numbers(chat_id, msg_id)
    elif data == 'adm_add_num':
        answer_callback(call.id); start_add_number(chat_id, msg_id)
    elif data == 'adm_list_nums':
        answer_callback(call.id); screen_admin_list_numbers(chat_id, msg_id)
    elif data == 'adm_avail_nums':
        answer_callback(call.id); screen_admin_filter_numbers(chat_id, msg_id, 'available')
    elif data == 'adm_sold_nums':
        answer_callback(call.id); screen_admin_filter_numbers(chat_id, msg_id, 'sold')
    elif data == 'adm_booked_nums':
        answer_callback(call.id); screen_admin_filter_numbers(chat_id, msg_id, 'booked')
    elif data == 'adm_del_num':
        answer_callback(call.id); screen_admin_delete_menu(chat_id, msg_id)
    elif data.startswith('adm_del_confirm:'):
        phone = data.split(':', 1)[1]; answer_callback(call.id); screen_admin_confirm_delete(chat_id, msg_id, phone)
    elif data.startswith('adm_del_exec:'):
        phone = data.split(':', 1)[1]; answer_callback(call.id, "✅"); execute_delete_number(chat_id, msg_id, phone)
    elif data.startswith('adm_view_num:'):
        phone = data.split(':', 1)[1]; answer_callback(call.id); screen_admin_view_number(chat_id, msg_id, phone)
    elif data.startswith('adm_edit_price:'):
        phone = data.split(':', 1)[1]; answer_callback(call.id); start_edit_price(chat_id, msg_id, phone)
    elif data.startswith('adm_list_page:'):
        page = int(data.split(':', 1)[1]); answer_callback(call.id); screen_admin_list_numbers(chat_id, msg_id, page=page)
    elif data.startswith('adm_filter_page:'):
        parts = data.split(':')
        status = parts[1]; page = int(parts[2])
        answer_callback(call.id); screen_admin_filter_numbers(chat_id, msg_id, status, page=page)
    
    # ═══════ المبيعات والإحصائيات ═══════
    elif data == 'adm_sales':
        answer_callback(call.id); screen_admin_sales(chat_id, msg_id)
    elif data == 'adm_recent_sales':
        answer_callback(call.id); screen_admin_recent_sales(chat_id, msg_id)
    elif data == 'adm_sales_stats':
        answer_callback(call.id); screen_admin_sales_stats(chat_id, msg_id)
    elif data == 'adm_stats':
        answer_callback(call.id); screen_admin_stats(chat_id, msg_id)
    
    # ═══════ الأدمنية ═══════
    elif data == 'adm_admins':
        answer_callback(call.id); screen_admin_admins_menu(chat_id, msg_id)
    elif data == 'adm_add_admin':
        answer_callback(call.id); start_add_admin(chat_id, msg_id)
    elif data == 'adm_remove_admin':
        answer_callback(call.id); start_remove_admin(chat_id, msg_id)
    elif data == 'adm_list_admins':
        answer_callback(call.id); screen_admin_list_admins(chat_id, msg_id)
    
    # ═══════ الإعدادات ═══════
    elif data == 'adm_settings':
        answer_callback(call.id); screen_admin_settings(chat_id, msg_id)
    elif data == 'adm_set_gift':
        answer_callback(call.id); start_set_gift(chat_id, msg_id)
    elif data == 'adm_set_ref':
        answer_callback(call.id); start_set_ref(chat_id, msg_id)
    elif data == 'adm_set_currency':
        answer_callback(call.id); start_set_currency(chat_id, msg_id)
    elif data == 'adm_set_developer':
        answer_callback(call.id); start_set_developer(chat_id, msg_id)
    elif data == 'adm_set_channel':
        answer_callback(call.id); start_set_channel(chat_id, msg_id)
    elif data == 'adm_set_notify_channel':
        answer_callback(call.id); start_set_notify_channel(chat_id, msg_id)
    elif data == 'adm_set_main_channel':
        answer_callback(call.id); start_set_main_channel(chat_id, msg_id)
    elif data == 'adm_set_activation':
        answer_callback(call.id); screen_admin_activation(chat_id, msg_id)
    elif data == 'adm_add_channel':
        answer_callback(call.id); start_add_channel(chat_id, msg_id)
    elif data.startswith('adm_del_channel:'):
        idx = int(data.split(':', 1)[1]); answer_callback(call.id, "✅"); execute_delete_channel(chat_id, msg_id, idx)
    
    # ═══════ الباقات ═══════
    elif data == 'adm_set_rates':
        answer_callback(call.id); screen_admin_rates(chat_id, msg_id)
    elif data == 'adm_add_rate':
        answer_callback(call.id); start_add_rate(chat_id, msg_id)
    elif data.startswith('adm_del_rate:'):
        idx = int(data.split(':', 1)[1]); answer_callback(call.id, "✅"); execute_delete_rate(chat_id, msg_id, idx)
    
    # ═══════ الشحن اليدوي ═══════
    elif data == 'adm_charge':
        answer_callback(call.id); screen_admin_charge(chat_id, msg_id)
    elif data == 'adm_add_pts':
        answer_callback(call.id); start_add_points(chat_id, msg_id)
    elif data == 'adm_remove_pts':
        answer_callback(call.id); start_remove_points(chat_id, msg_id)
    elif data == 'adm_add_stars':
        answer_callback(call.id); start_add_stars(chat_id, msg_id)
    
    # ═══════ البث والسجل ═══════
    elif data == 'adm_broadcast':
        answer_callback(call.id); start_broadcast(chat_id, msg_id)
    elif data == 'adm_logs':
        answer_callback(call.id); screen_admin_logs(chat_id, msg_id)
    elif data == 'adm_users_search':
        answer_callback(call.id); start_search_user(chat_id, msg_id)
    
    # ═══════ التخصيص ═══════
    elif data == 'adm_custom':
        answer_callback(call.id); screen_admin_custom(chat_id, msg_id)
    elif data == 'adm_custom_colors':
        answer_callback(call.id); screen_admin_colors(chat_id, msg_id)
    elif data.startswith('adm_color_edit:'):
        key = data.split(':', 1)[1]; answer_callback(call.id); screen_admin_color_choices(chat_id, msg_id, key)
    elif data.startswith('adm_color_set:'):
        parts = data.split(':')
        key = parts[1]; color = parts[2]
        if is_valid_color(color):
            colors = syyad_conf.setdefault('main_buttons_colors', DEFAULT_MAIN_COLORS.copy())
            colors[key] = color
            save_all()
            answer_callback(call.id, f"✅ تم تغيير اللون إلى {color}")
            screen_admin_colors(chat_id, msg_id)
        else:
            answer_callback(call.id, "❌ لون غير صالح", alert=True)
    elif data == 'adm_custom_add_row':
        answer_callback(call.id); start_custom_add_row(chat_id, msg_id)
    elif data == 'adm_custom_list':
        answer_callback(call.id); screen_admin_custom_list(chat_id, msg_id)
    elif data == 'adm_custom_del':
        rows = syyad_conf.get('custom_main_rows', [])
        if not rows:
            answer_callback(call.id, "📭 لا توجد صفوف", alert=True)
            return
        kb = InlineKeyboardMarkup(row_width=1)
        for i, row in enumerate(rows):
            kb.add(Btn.d(f"🗑️ {row.get('name', f'صف {i+1}')}", f"adm_del_row:{i}"))
        kb.add(Btn.d("‹ رجوع", "adm_custom"))
        answer_callback(call.id)
        edit_or_send_message(chat_id, msg_id, "🗑️ <b>حذف صف</b>\n\nاختر:", kb)
    elif data.startswith('adm_del_row:'):
        idx = int(data.split(':', 1)[1]); answer_callback(call.id, "✅"); execute_delete_custom_row(chat_id, msg_id, idx)
    
    else:
        answer_callback(call.id, "❓")


# ══════════════════════════════════════════════════════════════
# 📨 ADMIN MESSAGE HANDLER
# ══════════════════════════════════════════════════════════════

@bot.message_handler(
    func=lambda m: str(m.from_user.id) in add_states,
    content_types=['text']
)
def handle_admin_message(message):
    """معالج رسائل الأدمن (بعد بدء أي عملية)"""
    try:
        uid = str(message.from_user.id)
        chat_id = message.chat.id

        if message.text and message.text.startswith('/'):
            return
        if not is_admin(uid):
            return
        if uid not in add_states:
            return

        state = add_states[uid]
        step = state.get('step')
        text = (message.text or '').strip()

        # ═══════ إضافة رقم ═══════
        if step == 'phone':
            if not is_valid_phone(text):
                bot.send_message(chat_id, "❌ رقم غير صالح. مثال: <code>+967777123456</code>", parse_mode='html', reply_markup=kb_cancel())
                return
            state['phone'] = text
            state['step'] = 'code_wait'
            bot.send_message(chat_id, f"✅ الرقم: <code>{text}</code>\n\n⏳ جاري إرسال الكود...", parse_mode='html')
            asyncio.run_coroutine_threadsafe(send_code_to_number(chat_id, text, uid), telethon_loop)
            return

        if step == 'code_wait':
            if not text.isdigit() or len(text) < 4:
                bot.send_message(chat_id, "❌ كود غير صالح.", parse_mode='html', reply_markup=kb_cancel())
                return
            asyncio.run_coroutine_threadsafe(verify_code(chat_id, text, uid), telethon_loop)
            return

        if step == '2fa':
            asyncio.run_coroutine_threadsafe(verify_2fa(chat_id, text, uid), telethon_loop)
            return

        if step == 'price_points':
            if not text.isdigit():
                bot.send_message(chat_id, "❌ أرسل رقم صحيح:", parse_mode='html', reply_markup=kb_cancel())
                return
            state['price_points'] = int(text)
            state['step'] = 'country'
            bot.send_message(
                chat_id,
                f"✅ السعر: <code>${text}</code>\n\n📝 الخطوة 4/4: أرسل اسم الدولة:",
                parse_mode='html',
                reply_markup=kb_cancel()
            )
            return

        if step == 'country':
            if len(text) < 2:
                bot.send_message(chat_id, "❌ اسم قصير", parse_mode='html', reply_markup=kb_cancel())
                return
            state['country'] = text
            state['step'] = 'done'
            asyncio.run_coroutine_threadsafe(finish_add_number(chat_id, state, uid), telethon_loop)
            return

        if step == 'edit_price':
            if not text.isdigit():
                bot.send_message(chat_id, "❌ رقم صحيح:", parse_mode='html', reply_markup=kb_cancel())
                return
            phone = state.get('edit_phone')
            if not phone or phone not in avail_nums:
                bot.send_message(chat_id, "❌ الرقم غير موجود")
                del add_states[uid]
                return
            avail_nums[phone]['price_points'] = int(text)
            save_all()
            bot.send_message(chat_id, f"✅ تم تحديث السعر إلى <code>${text}</code>", parse_mode='html', reply_markup=kb_admin_back("adm_nums"))
            del add_states[uid]
            return

        # ═══════ الأدمنية ═══════
        if step == 'add_admin':
            if not is_valid_uid(text):
                bot.send_message(chat_id, "❌ آيدي غير صالح", reply_markup=kb_cancel())
                return
            if text in syyad_conf['admin_ids']:
                bot.send_message(chat_id, "⚠️ أدمن مسبقاً", reply_markup=kb_admin_back("adm_admins"))
                del add_states[uid]
                return
            syyad_conf['admin_ids'].append(text)
            save_all()
            bot.send_message(chat_id, f"✅ تم رفع الأدمن: <code>{text}</code>", parse_mode='html', reply_markup=kb_admin_back("adm_admins"))
            del add_states[uid]
            return

        if step == 'remove_admin':
            if not is_valid_uid(text):
                bot.send_message(chat_id, "❌ آيدي غير صالح", reply_markup=kb_cancel())
                return
            if text not in syyad_conf['admin_ids']:
                bot.send_message(chat_id, "⚠️ ليس أدمن", reply_markup=kb_admin_back("adm_admins"))
                del add_states[uid]
                return
            if text == uid:
                bot.send_message(chat_id, "❌ لا يمكنك إزالة نفسك", reply_markup=kb_admin_back("adm_admins"))
                del add_states[uid]
                return
            syyad_conf['admin_ids'].remove(text)
            save_all()
            bot.send_message(chat_id, f"✅ تم إزالة الأدمن: <code>{text}</code>", parse_mode='html', reply_markup=kb_admin_back("adm_admins"))
            del add_states[uid]
            return

        # ═══════ الرصيد ═══════
        if step == 'add_pts_uid':
            if not is_valid_uid(text):
                bot.send_message(chat_id, "❌ آيدي غير صالح", reply_markup=kb_cancel())
                return
            state['target_uid'] = text
            state['step'] = 'add_pts_amount'
            bot.send_message(chat_id, f"✅ الآيدي: <code>{text}</code>\n\n📝 الخطوة 2/2: أرسل المبلغ:", parse_mode='html', reply_markup=kb_cancel())
            return

        if step == 'add_pts_amount':
            if not is_valid_amount(text, 1):
                bot.send_message(chat_id, "❌ مبلغ غير صالح", reply_markup=kb_cancel())
                return
            amount = int(text)
            target = state['target_uid']
            add_points(target, amount)
            sym = syyad_conf.get('currency_symbol', '$')
            bot.send_message(chat_id, f"✅ تم إضافة <code>{sym}{amount}</code> للمستخدم <code>{target}</code>", parse_mode='html', reply_markup=kb_admin_back("adm_charge"))
            try:
                bot.send_message(int(target), f"🎉 تم إضافة رصيد: <code>+{sym}{amount}</code>", parse_mode='html')
            except Exception:
                pass
            del add_states[uid]
            return

        if step == 'remove_pts_uid':
            if not is_valid_uid(text):
                bot.send_message(chat_id, "❌ آيدي غير صالح", reply_markup=kb_cancel())
                return
            state['target_uid'] = text
            state['step'] = 'remove_pts_amount'
            bot.send_message(chat_id, f"✅ الآيدي: <code>{text}</code>\n\n📝 الخطوة 2/2: أرسل المبلغ للخصم:", parse_mode='html', reply_markup=kb_cancel())
            return

        if step == 'remove_pts_amount':
            if not is_valid_amount(text, 1):
                bot.send_message(chat_id, "❌ مبلغ غير صالح", reply_markup=kb_cancel())
                return
            amount = int(text)
            target = state['target_uid']
            if not remove_points(target, amount):
                bot.send_message(chat_id, "❌ الرصيد غير كافٍ", reply_markup=kb_admin_back("adm_charge"))
                del add_states[uid]
                return
            sym = syyad_conf.get('currency_symbol', '$')
            bot.send_message(chat_id, f"✅ تم خصم <code>{sym}{amount}</code>", parse_mode='html', reply_markup=kb_admin_back("adm_charge"))
            del add_states[uid]
            return

        if step == 'add_stars_uid':
            if not is_valid_uid(text):
                bot.send_message(chat_id, "❌ آيدي غير صالح", reply_markup=kb_cancel())
                return
            state['target_uid'] = text
            state['step'] = 'add_stars_amount'
            bot.send_message(chat_id, f"✅ الآيدي: <code>{text}</code>\n\n📝 الخطوة 2/2: أرسل عدد النجوم:", parse_mode='html', reply_markup=kb_cancel())
            return

        if step == 'add_stars_amount':
            if not is_valid_amount(text, 1):
                bot.send_message(chat_id, "❌ رقم غير صالح", reply_markup=kb_cancel())
                return
            amount = int(text)
            target = state['target_uid']
            add_stars(target, amount)
            bot.send_message(chat_id, f"✅ تم إضافة <code>{amount}</code> نجمة", parse_mode='html', reply_markup=kb_admin_back("adm_charge"))
            del add_states[uid]
            return

        # ═══════ الإعدادات ═══════
        if step == 'set_gift':
            if not is_valid_amount(text, 0):
                bot.send_message(chat_id, "❌ رقم غير صالح", reply_markup=kb_cancel())
                return
            syyad_conf['dailyGiftPoints'] = int(text)
            save_all()
            bot.send_message(chat_id, f"✅ تم التحديث: <code>${text}</code>", parse_mode='html', reply_markup=kb_admin_back("adm_settings"))
            del add_states[uid]
            return

        if step == 'set_ref':
            if not is_valid_amount(text, 0):
                bot.send_message(chat_id, "❌ رقم غير صالح", reply_markup=kb_cancel())
                return
            syyad_conf['referralPoints'] = int(text)
            save_all()
            bot.send_message(chat_id, f"✅ تم التحديث: <code>${text}</code>", parse_mode='html', reply_markup=kb_admin_back("adm_settings"))
            del add_states[uid]
            return

        if step == 'set_currency_name':
            if len(text) < 2:
                bot.send_message(chat_id, "❌ اسم قصير", reply_markup=kb_cancel())
                return
            syyad_conf['currency_name'] = text
            state['step'] = 'set_currency_symbol'
            save_all()
            bot.send_message(chat_id, f"✅ اسم العملة: {text}\n\n📝 الخطوة 2/2: أرسل رمز العملة:", parse_mode='html', reply_markup=kb_cancel())
            return

        if step == 'set_currency_symbol':
            if len(text) < 1 or len(text) > 5:
                bot.send_message(chat_id, "❌ رمز غير صالح", reply_markup=kb_cancel())
                return
            syyad_conf['currency_symbol'] = text
            save_all()
            bot.send_message(chat_id, f"✅ العملة: {syyad_conf['currency_name']} ({text})", parse_mode='html', reply_markup=kb_admin_back("adm_settings"))
            del add_states[uid]
            return

        if step == 'set_developer':
            username = text.lstrip('@').strip()
            if len(username) < 3:
                bot.send_message(chat_id, "❌ يوزر قصير", reply_markup=kb_cancel())
                return
            syyad_conf['developer_username'] = username
            save_all()
            bot.send_message(chat_id, f"✅ يوزر المطور: @{username}", parse_mode='html', reply_markup=kb_admin_back("adm_settings"))
            del add_states[uid]
            return

        if step == 'set_channel':
            if text.lower() in ['حذف', 'delete', 'مسح', '']:
                syyad_conf['publish_channel_id'] = None
                msg = "🗑️ تم الإلغاء"
            else:
                syyad_conf['publish_channel_id'] = text
                msg = f"✅ تم التحديث: <code>{text}</code>"
            save_all()
            bot.send_message(chat_id, msg, parse_mode='html', reply_markup=kb_admin_back("adm_settings"))
            del add_states[uid]
            return

        if step == 'set_notify_channel':
            if text.lower() in ['حذف', 'delete', 'مسح', '']:
                syyad_conf['notify_channel_id'] = None
                msg = "🗑️ تم الإلغاء"
            else:
                syyad_conf['notify_channel_id'] = text
                msg = f"✅ تم التحديث: <code>{text}</code>"
            save_all()
            bot.send_message(chat_id, msg, parse_mode='html', reply_markup=kb_admin_back("adm_settings"))
            del add_states[uid]
            return

        if step == 'set_main_channel':
            if text.lower() in ['حذف', 'delete', 'مسح', '']:
                syyad_conf['main_channel_url'] = None
                msg = "🗑️ تم الإلغاء"
            else:
                url = text
                if url.startswith('@'):
                    url = f"https://t.me/{url[1:]}"
                elif not url.startswith('http'):
                    url = f"https://t.me/{url}"
                syyad_conf['main_channel_url'] = url
                msg = f"✅ تم التحديث: <code>{url}</code>"
            save_all()
            bot.send_message(chat_id, msg, parse_mode='html', reply_markup=kb_admin_back("adm_settings"))
            del add_states[uid]
            return

        # ═══════ الباقات ═══════
        if step == 'rate_points':
            if not is_valid_amount(text, 1):
                bot.send_message(chat_id, "❌ رقم غير صالح", reply_markup=kb_cancel())
                return
            state['rate_points'] = int(text)
            state['step'] = 'rate_stars'
            bot.send_message(chat_id, f"✅ الدولار: <code>${text}</code>\n\n📝 الخطوة 2/2: أرسل عدد النجوم:", parse_mode='html', reply_markup=kb_cancel())
            return

        if step == 'rate_stars':
            if not is_valid_amount(text, 1):
                bot.send_message(chat_id, "❌ رقم غير صالح", reply_markup=kb_cancel())
                return
            rate = {'points': state['rate_points'], 'stars': int(text)}
            syyad_conf.setdefault('chargeRates', []).append(rate)
            save_all()
            bot.send_message(chat_id, f"✅ تمت الإضافة: <code>${rate['points']}</code> = ⭐ <code>{rate['stars']}</code>", parse_mode='html', reply_markup=kb_admin_back("adm_settings"))
            del add_states[uid]
            return

        # ═══════ القنوات ═══════
        if step == 'add_channel':
            if len(text) < 3:
                bot.send_message(chat_id, "❌ معرف قصير", reply_markup=kb_cancel())
                return
            channels = syyad_conf.setdefault('activation_channels', [])
            if text in channels:
                bot.send_message(chat_id, "⚠️ موجودة مسبقاً", reply_markup=kb_cancel())
                return
            channels.append(text)
            save_all()
            bot.send_message(chat_id, f"✅ تمت الإضافة: <code>{text}</code>", parse_mode='html', reply_markup=kb_admin_back("adm_settings"))
            del add_states[uid]
            return

        # ═══════ البث ═══════
        if step == 'broadcast':
            del add_states[uid]
            execute_broadcast(chat_id, text)
            return

        # ═══════ البحث ═══════
        if step == 'search_user':
            del add_states[uid]
            execute_search_user(chat_id, message.message_id, text)
            return

        # ═══════ الصفوف المخصصة ═══════
        if step == 'custom_row_name':
            if len(text) < 2:
                bot.send_message(chat_id, "❌ اسم قصير", reply_markup=kb_cancel())
                return
            state['custom_row_name'] = text
            state['step'] = 'custom_row_btn_label'
            bot.send_message(chat_id, "📝 الخطوة 2/3: أرسل نص الزر:", reply_markup=kb_cancel())
            return

        if step == 'custom_row_btn_label':
            if len(text) < 1:
                bot.send_message(chat_id, "❌ نص قصير", reply_markup=kb_cancel())
                return
            state['custom_btn_label'] = text
            state['step'] = 'custom_row_btn_url'
            bot.send_message(
                chat_id,
                "🔗 الخطوة 3/3: أرسل الرابط (أو <code>skip</code> لو زر عادي):",
                parse_mode='html',
                reply_markup=kb_cancel()
            )
            return

        if step == 'custom_row_btn_url':
            is_url = text.lower() != 'skip'
            row = {
                'name': state.get('custom_row_name', 'صف مخصص'),
                'enabled': True,
                'buttons': [{
                    'label': state.get('custom_btn_label', 'زر'),
                    'url': text if is_url else None,
                    'callback': None if is_url else 'noop',
                    'color': 'primary',
                }]
            }
            syyad_conf.setdefault('custom_main_rows', []).append(row)
            save_all()
            bot.send_message(chat_id, "✅ تمت إضافة الصف", reply_markup=kb_admin_back("adm_custom"))
            del add_states[uid]
            return

    except Exception as e:
        log(f"admin_message: {e}", 'error')
        if str(message.from_user.id) in add_states:
            del add_states[str(message.from_user.id)]

# ══════════════════════════════════════════════════════════════
# 📨 SEARCH + BROADCAST
# ══════════════════════════════════════════════════════════════

def execute_search_user(chat_id, msg_id, query):
    """بحث عن مستخدم"""
    query = query.strip()
    results = []
    for uid, u in syyad_users.items():
        match = False
        if uid == query:
            match = True
        if not match:
            username = u.get('username', '')
            if username and query.lstrip('@').lower() == username.lower():
                match = True
        if not match:
            first_name = u.get('first_name', '')
            if first_name and query.lower() in first_name.lower():
                match = True
        if match:
            results.append((uid, u))
        if len(results) >= 10:
            break

    if not results:
        edit_or_send_message(chat_id, msg_id, f"🔍 لا نتائج لـ <code>{query}</code>", kb_admin_back("adm_main"))
        return

    text = f"🔍 <b>نتائج البحث</b>\n\n"
    for uid, u in results:
        text += f"👤 {u.get('first_name', '—')} | <code>{uid}</code> | 💵 ${u.get('points', 0)}\n"
    edit_or_send_message(chat_id, msg_id, text, kb_admin_back("adm_main"))


def execute_broadcast(chat_id, message):
    """بث جماعي"""
    total = len(syyad_users)
    sent = 0
    failed = 0
    status_msg = bot.send_message(chat_id, f"⏳ جاري البث... ({total})", parse_mode='html')
    for user_id in list(syyad_users.keys()):
        try:
            bot.send_message(int(user_id), f"📢 <b>رسالة من الإدارة</b>\n\n{message}", parse_mode='html')
            sent += 1
        except Exception:
            failed += 1
        if sent % 20 == 0:
            time.sleep(1)
    try:
        bot.edit_message_text(
            f"✅ تم البث\n\nنجح: {sent}\nفشل: {failed}",
            chat_id=chat_id,
            message_id=status_msg.message_id,
            reply_markup=kb_admin_back("adm_main")
        )
    except Exception:
        pass
        
# ══════════════════════════════════════════════════════════════
# 📨 ASYNC FUNCTIONS (Telethon)
# ══════════════════════════════════════════════════════════════

async def send_code_to_number(chat_id, phone, uid):
    """إرسال كود التحقق لرقم جديد (لإضافته للبيع)"""
    try:
        new_client = TelegramClient(
            StringSession(),
            REG_ID,
            REG_HASH,
            loop=telethon_loop
        )
        await new_client.connect()
        code_info = await new_client.send_code_request(phone)
        add_states[uid]['client'] = new_client
        add_states[uid]['code_info'] = code_info
        bot.send_message(
            chat_id,
            f"📨 تم إرسال الكود\n\n"
            f"📱 <code>{phone}</code>\n\n"
            f"✍️ أرسل الكود هنا:",
            parse_mode='html',
            reply_markup=kb_cancel()
        )
    except FloodWaitError as e:
        bot.send_message(
            chat_id,
            f"⏳ انتظر {e.seconds} ثانية قبل المحاولة مجددًا",
            parse_mode='html',
            reply_markup=kb_cancel()
        )
        if uid in add_states:
            del add_states[uid]
    except Exception as e:
        log(f"send_code: {e}", 'error')
        bot.send_message(
            chat_id,
            f"❌ فشل:\n<code>{str(e)[:100]}</code>",
            parse_mode='html',
            reply_markup=kb_cancel()
        )
        if uid in add_states:
            del add_states[uid]


async def verify_code(chat_id, code, uid):
    """التحقق من كود الدخول"""
    state = add_states.get(uid)
    if not state or 'client' not in state:
        return
    phone = state['phone']
    client_ = state['client']
    code_info = state['code_info']
    try:
        await client_.sign_in(
            phone=phone,
            code=code,
            phone_code_hash=code_info.phone_code_hash
        )
        await finish_signin(chat_id, state, uid)
    except SessionPasswordNeededError:
        state['step'] = '2fa'
        bot.send_message(
            chat_id,
            "🔐 <b>الحساب محمي بكلمة مرور</b>\n\n"
            "📝 أرسل كلمة المرور (2FA):",
            parse_mode='html',
            reply_markup=kb_cancel()
        )
    except Exception as e:
        log(f"sign_in: {e}", 'error')
        bot.send_message(
            chat_id,
            f"❌ فشل:\n<code>{str(e)[:100]}</code>",
            parse_mode='html',
            reply_markup=kb_cancel()
        )
        if uid in add_states:
            del add_states[uid]


async def verify_2fa(chat_id, password, uid):
    """التحقق من كلمة المرور الثنائية"""
    state = add_states.get(uid)
    if not state or 'client' not in state:
        return
    client_ = state['client']
    try:
        await client_.sign_in(password=password)
        state['two_fa'] = password
        await finish_signin(chat_id, state, uid)
    except Exception as e:
        bot.send_message(
            chat_id,
            f"❌ خطأ:\n<code>{str(e)[:100]}</code>",
            parse_mode='html',
            reply_markup=kb_cancel()
        )


async def finish_signin(chat_id, state, uid):
    """حفظ الجلسة بعد نجاح تسجيل الدخول"""
    client_ = state['client']
    phone = state['phone']
    try:
        sess_str = client_.session.save()
        u_sessions[phone] = {
            'api_id': REG_ID,
            'api_hash': REG_HASH,
            'session_str': sess_str,
            'two_factor_password': state.get('two_fa', 'لا يوجد'),
        }
        try:
            await client_.disconnect()
        except Exception:
            pass
        # تشغيل الجلسة
        asyncio.run_coroutine_threadsafe(
            init_acc(phone, REG_ID, REG_HASH, sess_str),
            telethon_loop
        )
        save_all()
        # الانتقال لخطوة السعر
        state['step'] = 'price_points'
        bot.send_message(
            chat_id,
            f"✅ <b>تم تسجيل الدخول بنجاح</b>\n\n"
            f"📱 <code>{phone}</code>\n\n"
            f"📝 الخطوة 3/4: أرسل السعر بالدولار:",
            parse_mode='html',
            reply_markup=kb_cancel()
        )
    except Exception as e:
        log(f"finish_signin: {e}", 'error')
        bot.send_message(
            chat_id,
            f"❌ خطأ: {str(e)[:100]}",
            reply_markup=kb_cancel()
        )
        if uid in add_states:
            del add_states[uid]


async def finish_add_number(chat_id, state, uid):
    """إنهاء إضافة رقم جديد"""
    phone = state['phone']
    details = {
        'price_points': state.get('price_points', 0),
        'price_stars': 0,  # ← لا نجوم للشراء
        'country': state.get('country', 'غير محدد'),
        'status': 'available',
        'added_by': uid,
        'buyer_id': None,
        'booked_by': None,
        'booking_time': None,
        'expiry_time': None,
        'deposit_paid_stars': None,
        'publish_message_id': None,
        'added_at': now().isoformat(),
    }
    add_number(phone, details)
    save_all()
    # نشر في القناة إن وُجدت
    try:
        asyncio.run_coroutine_threadsafe(publish_number(phone), telethon_loop)
    except Exception:
        pass
    sym = syyad_conf.get('currency_symbol', '$')
    bot.send_message(
        chat_id,
        f"✅ <b>تمت الإضافة بنجاح</b>\n\n"
        f"📱 <code>{phone}</code>\n"
        f"🌍 {details['country']}\n"
        f"💵 <code>{sym}{details['price_points']}</code>",
        parse_mode='html',
        reply_markup=kb_admin_back("adm_nums")
    )
    if uid in add_states:
        del add_states[uid]


# ══════════════════════════════════════════════════════════════
# 🔄 INIT ACCOUNTS (تشغيل الجلسات)
# ══════════════════════════════════════════════════════════════

async def init_acc(phone, api_id, api_hash, sess_str):
    """تشغيل جلسة حساب واحد"""
    if phone in u_clients:
        try:
            if await u_clients[phone].is_connected():
                return
        except Exception:
            pass
    
    try:
        u_client = TelegramClient(
            StringSession(sess_str),
            api_id,
            api_hash,
            loop=telethon_loop
        )

        @u_client.on(events.NewMessage(incoming=True, chats=777000))
        async def proc_code_msg(event):
            """التقاط كود تيليجرام من رسائل 777000"""
            try:
                text = event.message.text or ''
                # البحث عن الكود
                m = re.search(r'Login code[:\s]+(\d+)', text)
                if not m:
                    m = re.search(r'\b(\d{5,6})\b', text)
                if not m:
                    return
                code = m.group(1)
                buyer_id = code_reqs.get(phone)
                if not buyer_id:
                    return
                # إرسال الكود للمشتري — اقتباس + رموز
                try:
                    code_text = (
                        "╔══════════════════════╗\n"
                        "║   🔑 <b>كود الدخول</b>       ║\n"
                        "╚══════════════════════╝\n"
                        "\n"
                        f"📱 <code>{phone}</code>\n"
                        "\n"
                        "━━━━━━━━━━━━━━━━━━━━━━\n"
                        "\n"
                        "<blockquote>"
                        "🎯 <b>الكود الخاص بك</b>\n"
                        "\n"
                        f"<code>{code}</code>"
                        "</blockquote>\n"
                        "\n"
                        "━━━━━━━━━━━━━━━━━━━━━━\n"
                        "\n"
                        "⏱️ <i>صالح لمدة قصيرة</i>\n"
                        "🔒 <i>لا تشاركه مع أحد</i>"
                    )
                    
                    await bot.send_message(
                        int(buyer_id),
                        code_text,
                        parse_mode='html'
                    )
                except Exception:
                    pass
                if phone in code_reqs:
                    del code_reqs[phone]
                raise events.StopPropagation
            except events.StopPropagation:
                raise
            except Exception as e:
                log(f"proc_code: {e}", 'error')

        await u_client.connect()
        if not await u_client.is_user_authorized():
            log(f"not auth: {phone}", 'error')
            return
        u_clients[phone] = u_client
        log(f"init_acc: {phone}", 'success')
    except Exception as e:
        log(f"init_acc {phone}: {e}", 'error')
        if phone in u_clients:
            del u_clients[phone]


async def run_accs():
    """تشغيل كل الجلسات"""
    if not u_sessions:
        return
    log(f"🔄 تشغيل {len(u_sessions)} جلسة...", 'info')
    for phone, details in list(u_sessions.items()):
        api_id = details.get('api_id')
        api_hash = details.get('api_hash')
        sess_str = details.get('session_str')
        if not (api_id and api_hash and sess_str):
            continue
        try:
            asyncio.create_task(init_acc(phone, api_id, api_hash, sess_str))
            log(f"✅ بدء: {phone}", 'success')
        except Exception as e:
            log(f"❌ فشل بدء {phone}: {e}", 'error')
        await asyncio.sleep(2)  # تفادي rate limits


# ══════════════════════════════════════════════════════════════
# 📢 PUBLISHING (نشر الأرقام في القناة)
# ══════════════════════════════════════════════════════════════

async def publish_number(phone):
    """نشر رقم جديد في قناة النشر"""
    channel = syyad_conf.get('publish_channel_id')
    if not channel:
        return
    details = get_number(phone)
    if not details:
        return
    pts = details.get('price_points', 0)
    country = details.get('country', '—')
    sym = syyad_conf.get('currency_symbol', '$')
    text = (
        f"🌟 <b>رقم جديد</b>\n\n"
        f"📱 <code>{hide_phone(phone)}</code>\n"
        f"🌍 {country}\n"
        f"💵 {sym}{pts}\n"
    )
    try:
        sent = bot.send_message(channel, text, parse_mode='html')
        avail_nums[phone]['publish_message_id'] = sent.message_id
        save_all()
    except Exception as e:
        log(f"publish: {e}", 'error')


# ══════════════════════════════════════════════════════════════
# 🌐 FLASK APP — للـ Web Service
# ══════════════════════════════════════════════════════════════

flask_app = Flask(__name__)


@flask_app.route('/')
@flask_app.route('/health')
def health_check():
    """نقطة فحص الحالة — UptimeRobot يزورها"""
    return jsonify({
        "status": "ok",
        "bot": "running",
        "users": len(syyad_users),
        "numbers": len(avail_nums),
        "sessions": len(u_sessions),
    })


@flask_app.route('/stats')
def stats_endpoint():
    """إحصائيات"""
    return jsonify({
        "total_users": len(syyad_users),
        "total_numbers": len(avail_nums),
        "available": len(get_available_numbers()),
        "sold": len(get_sold_numbers()),
    })


# ══════════════════════════════════════════════════════════════
# 🚀 POLLING + HEALTH SERVER
# ══════════════════════════════════════════════════════════════

def run_bot_polling():
    """حلقة polling للبوت"""
    while True:
        try:
            bot.polling(none_stop=True, interval=1, timeout=20)
        except Exception as e:
            log(f"polling: {e}", 'error')
            time.sleep(5)


from http.server import HTTPServer, BaseHTTPRequestHandler


class HealthHandler(BaseHTTPRequestHandler):
    """Health check server"""
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'Bot is running')

    def log_message(self, *args):
        pass


def start_health_server():
    """تشغيل Health Server (للنشر على السحابة)"""
    port = int(os.environ.get('PORT', 10000))
    try:
        server = HTTPServer(('0.0.0.0', port), HealthHandler)
        log(f"✅ Health on port {port}", 'success')
        server.serve_forever()
    except Exception as e:
        log(f"health: {e}", 'error')


# ══════════════════════════════════════════════════════════════
# 🎬 MAIN — التشغيل الرئيسي (Render-Ready)
# ══════════════════════════════════════════════════════════════

def main():
    """الدالة الرئيسية لتشغيل البوت"""
    print()
    print("═" * 60)
    print("🌟 NEM BOT v7 - بوت بيع الأرقام الاحترافي")
    print("═" * 60)
    print()

    # ───── التحقق من التوكن ─────
    if not BOT_TOKEN or ':' not in BOT_TOKEN:
        print("❌ BOT_TOKEN غير صحيح!")
        return

    # ───── تحميل البيانات ─────
    try:
        load_all()
    except Exception as e:
        print(f"❌ فشل التحميل: {e}")
        return

    print(f"✅ تم تحميل البيانات")
    print(f"   👥 المستخدمون: {len(syyad_users)}")
    print(f"   📱 الأرقام: {len(avail_nums)}")
    print(f"   💼 الجلسات: {len(u_sessions)}")
    print(f"   💵 العملة: {syyad_conf.get('currency_name', 'دولار')} ({syyad_conf.get('currency_symbol', '$')})")
    print(f"   🎨 الألوان الحقيقية: {'✅ مدعومة' if USE_STYLE else '❌ غير مدعومة'}")
    print()

    # ───── الاتصال بتيليجرام ─────
    print("🚀 جاري الاتصال بـ تيليجرام...")
    try:
        future = asyncio.run_coroutine_threadsafe(
            client.connect(),
            telethon_loop
        )
        future.result(timeout=30)
        print("✅ تم الاتصال!")
    except Exception as e:
        print(f"❌ فشل الاتصال: {e}")
        return
    print()

    # ───── تشغيل الجلسات ─────
    if u_sessions:
        print(f"🔄 جاري تشغيل {len(u_sessions)} جلسة...")
        asyncio.run_coroutine_threadsafe(run_accs(), telethon_loop)
        print("✅ تم بدء الجلسات")
        print()

    # ───── تهيئة الحجوزات ─────
    try:
        asyncio.run_coroutine_threadsafe(init_reservations(), telethon_loop)
    except Exception:
        pass

    # ══════════════════════════════════════════════════════════════
    # 🚀 تشغيل Flask للـ Web Service على Render
    # ══════════════════════════════════════════════════════════════
    
    # تشغيل polling في thread منفصل
    poll_thread = threading.Thread(target=run_bot_polling, daemon=True)
    poll_thread.start()
    print("✅ البوت يعمل الآن")
    print()

    # تشغيل Flask على المنفذ المطلوب
    port = int(os.environ.get('PORT', 10000))
    print(f"🌐 Flask على منفذ {port}")
    print("═" * 60)
    print("👑 البوت يعمل — لا تغلق النافذة")
    print("═" * 60)
    print()

    try:
        flask_app.run(
            host='0.0.0.0',
            port=port,
            debug=False,
            use_reloader=False,
            threaded=True
        )
    except KeyboardInterrupt:
        print("\n👋 تم الإيقاف")
        save_all()
    except Exception as e:
        log(f"flask run: {e}", 'error')
        print(f"❌ Flask error: {e}")


# ══════════════════════════════════════════════════════════════
# 🚀 نقطة الدخول
# ══════════════════════════════════════════════════════════════

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n👋")
        try:
            save_all()
        except Exception:
            pass
    except Exception as e:
        log(f"main error: {e}", 'error')
        print(f"❌ خطأ: {e}")
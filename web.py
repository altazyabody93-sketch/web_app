# ============================================================
# MATARI STORE - web.py (نسخة كاملة نهائية)
# ============================================================
import os, sqlite3, secrets, re, imaplib, email, random, threading, time
from datetime import datetime
from functools import wraps
from urllib.parse import urlencode
from markupsafe import Markup
from flask import (Flask, request, redirect, url_for, session, flash,
                   g, abort, get_flashed_messages, jsonify, Response)
from werkzeug.security import generate_password_hash, check_password_hash

# ---------- المسارات والإعدادات (مرتبطة بمجلد الملف، آمنة على Render) ----------
import logging
from logging.handlers import RotatingFileHandler
from werkzeug.exceptions import HTTPException

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# على Render ممكن تحط قاعدة البيانات على Disk دائم عبر MATARI_DB_PATH (مثال: /var/data/matari.db)
DB_PATH = os.environ.get("MATARI_DB_PATH") or os.path.join(BASE_DIR, "matari.db")
# المنفذ: Render يحدد PORT تلقائياً، وكود التشغيل المحلي يستخدم 5000
PORT = int(os.environ.get("PORT", 5000))
# كلمة سر الأدمن الافتراضية - يفضل تغييرها من متغيرات البيئة
ADMIN_DEFAULT_PASSWORD = os.environ.get("MATARI_ADMIN_PASSWORD", "733723953")

# ---------- نظام التسجيل (Logging): يطبع في stdout (يظهر في Logs على Render) ويكتب app.log ----------
LOG_PATH = os.path.join(BASE_DIR, "app.log")
log = logging.getLogger("matari")
log.setLevel(logging.INFO)
if not log.handlers:
    _fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    _sh = logging.StreamHandler()
    _sh.setFormatter(_fmt)
    log.addHandler(_sh)
    try:
        _fh = RotatingFileHandler(LOG_PATH, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        _fh.setFormatter(_fmt)
        log.addHandler(_fh)
    except Exception:
        pass  # لو الملف غير قابل للكتابة نكتفي بـ stdout

def _load_secret():
    """مفتاح الجلسات: من متغير البيئة MATARI_SECRET (الموصى به).
    تم حذف المفتاح الثابت القديم لأنه كان ظاهراً في الكود (ثغرة أمنية)."""
    env_secret = os.environ.get("MATARI_SECRET")
    if env_secret:
        return env_secret
    key_file = os.path.join(BASE_DIR, ".secret_key")
    try:
        if os.path.exists(key_file):
            with open(key_file, "r", encoding="utf-8") as f:
                return f.read().strip()
        k = secrets.token_hex(32)
        with open(key_file, "w", encoding="utf-8") as f:
            f.write(k)
        return k
    except Exception as e:
        log.warning("تعذر حفظ مفتاح الجلسات: %s", e)
        return secrets.token_hex(32)

SECRET = _load_secret()

app = Flask(__name__, static_folder=os.path.join(BASE_DIR, "static"), static_url_path="/static")
app.secret_key = SECRET
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["PERMANENT_SESSION_LIFETIME"] = 2592000  # 30 days

@app.errorhandler(Exception)
def _handle_unexpected_error(e):
    """أي خطأ غير متوقع يتسجل في الـ Logs ويرجع صفحة بديلة بدل 502/انهيار."""
    if isinstance(e, HTTPException):
        return e  # 404 و 403 ... تبقى كما هي
    log.exception("Unhandled error: %s", e)
    return ("<div dir='rtl' style='font-family:sans-serif;padding:40px;text-align:center'>"
            "<h2>حدث خطأ مؤقت</h2><p>حاول مرة أخرى بعد قليل.</p>"
            "<a href='/'>الرجوع للرئيسية</a></div>"), 500

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, timeout=30)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        try:
            g.db.execute("PRAGMA journal_mode = WAL")
        except sqlite3.OperationalError as e:
            log.warning("WAL غير متاح: %s", e)
    return g.db

@app.teardown_appcontext
def close_db(exc=None):
    d = g.pop("db", None)
    if d: d.close()


# ============================================================
# SVG ICONS
# ============================================================
ICONS = {
    "home": '<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>',
    "cart": '<circle cx="9" cy="21" r="1"/><circle cx="20" cy="21" r="1"/><path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6"/>',
    "user": '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
    "users": '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "phone": '<rect x="5" y="2" width="14" height="20" rx="2" ry="2"/><line x1="12" y1="18" x2="12.01" y2="18"/>',
    "check": '<path d="M20 6L9 17l-5-5"/>',
    "x": '<circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>',
    "warning": '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
    "refresh": '<polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>',
    "key": '<path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/>',
    "gift": '<polyline points="20 12 20 22 4 22 4 12"/><rect x="2" y="7" width="20" height="5"/><line x1="12" y1="22" x2="12" y2="7"/><path d="M12 7H7.5a2.5 2.5 0 0 1 0-5C11 2 12 7 12 7z"/><path d="M12 7h4.5a2.5 2.5 0 0 0 0-5C13 2 12 7 12 7z"/>',
    "ticket": '<path d="M2 9a3 3 0 0 1 0 6v2a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-2a3 3 0 0 1 0-6V7a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2z"/>',
    "arrow-left": '<line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/>',
    "arrow-right": '<line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/>',
    "lock": '<rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    "star": '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>',
    "chart": '<line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
    "send": '<line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>',
    "telegram": '<path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4 20-7z"/>',
    "whatsapp": '<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>',
    "copy": '<rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    "upload": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>',
    "check-circle": '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>',
    "download": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
    "list": '<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/>',
    "trash": '<polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
    "edit": '<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>',
    "eye": '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>',
    "wallet": '<path d="M21 12V7H5a2 2 0 0 1 0-4h14v4"/><path d="M3 5v14a2 2 0 0 0 2 2h16v-5"/><path d="M18 12a2 2 0 0 0 0 4h4v-4z"/>',
    "credit-card": '<rect x="1" y="4" width="22" height="16" rx="2" ry="2"/><line x1="1" y1="10" x2="23" y2="10"/>',
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
    "logout": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2"/>',
    "dollar": '<line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>',
    "globe": '<circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    "message": '<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>',
    "search": '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
    "file": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/>',
}



def detect_country(phone):
    """يحدد الدولة من رقم الهاتف (بناءً على رمز الدولة)"""
    if not phone:
        return None
    # نزيل + والمسافات والشرطات
    clean = str(phone).replace("+", "").replace(" ", "").replace("-", "")
    if not clean or not clean.isdigit():
        return None
    
    # نبحث في buy_prices عن الدولة التي يطابق رمزها بداية الرقم
    prices = db().execute("SELECT country, code FROM buy_prices WHERE code IS NOT NULL AND code != ''").fetchall()
    # نرتب حسب طول الرمز (الأطول أولاً لتفادي 1 (أمريكا) بدل 1xx)
    sorted_prices = sorted(prices, key=lambda x: len(str(x["code"])), reverse=True)
    
    for p in sorted_prices:
        code = str(p["code"])
        if code and clean.startswith(code):
            return p["country"]
    
    return None


def ico(name, size=18):
    body = ICONS.get(name, "")
    if not body:
        return ""
    return ('<svg width="' + str(size) + '" height="' + str(size) + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:inline-block;vertical-align:middle;flex-shrink:0">' + body + '</svg>')

def _gen_captcha_code():
    import random
    return "".join(random.choices("0123456789", k=4))


SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  user_id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  email TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  recovery_key TEXT UNIQUE,
  custom_id TEXT UNIQUE,
  balance REAL DEFAULT 0.0,
  is_admin INTEGER DEFAULT 0,
  is_banned INTEGER DEFAULT 0,
  referred_by INTEGER,
  referral_earnings REAL DEFAULT 0.0,
  captcha_passed INTEGER DEFAULT 0,
  last_bonus TEXT,
  total_spent REAL DEFAULT 0,
  bad_coupons INTEGER DEFAULT 0,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS numbers(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  platform TEXT NOT NULL,
  country TEXT NOT NULL,
  phone TEXT NOT NULL,
  price REAL NOT NULL,
  status TEXT DEFAULT 'available',
  buyer_id INTEGER,
  sold_at TEXT,
  last_code TEXT,
  paid_price REAL,
  session_string TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS deposits(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  method TEXT NOT NULL,
  amount_usd REAL NOT NULL,
  status TEXT DEFAULT 'pending',
  trans_id TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  processed_at TEXT
);
CREATE TABLE IF NOT EXISTS vouchers(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT UNIQUE NOT NULL,
  amount REAL NOT NULL,
  is_used INTEGER DEFAULT 0,
  used_by INTEGER,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS coupons(
  code TEXT PRIMARY KEY,
  percent REAL NOT NULL,
  max_uses INTEGER DEFAULT 1,
  used_count INTEGER DEFAULT 0,
  expires_at TEXT
);
CREATE TABLE IF NOT EXISTS coupon_uses(
  code TEXT, user_id INTEGER, used_at TEXT,
  PRIMARY KEY(code, user_id)
);
CREATE TABLE IF NOT EXISTS tickets(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  subject TEXT NOT NULL,
  message TEXT,
  status TEXT DEFAULT 'open',
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS ticket_messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticket_id INTEGER NOT NULL,
  sender TEXT NOT NULL,
  text TEXT NOT NULL,
  is_read INTEGER DEFAULT 0,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS audit_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER,
  action TEXT NOT NULL,
  details TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS transfers(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  from_id INTEGER, to_id INTEGER, amount REAL, fee REAL,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS preorders(
  user_id INTEGER, country TEXT, created_at TEXT,
  PRIMARY KEY(user_id, country)
);
CREATE TABLE IF NOT EXISTS ratings(
  number_id INTEGER PRIMARY KEY,
  user_id INTEGER, stars INTEGER, created_at TEXT
);
CREATE TABLE IF NOT EXISTS temp_sessions(
  phone TEXT PRIMARY KEY,
  session_str TEXT,
  code_hash TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS announcements(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  text TEXT NOT NULL,
  level TEXT DEFAULT 'info',
  is_active INTEGER DEFAULT 1,
  text_color TEXT DEFAULT '#e8e8f5',
  font_size TEXT DEFAULT '15px',
  icon TEXT DEFAULT 'bell',
  btn_text TEXT DEFAULT '',
  btn_url TEXT DEFAULT '',
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS site_icons(
  name TEXT PRIMARY KEY,
  filename TEXT NOT NULL,
  uploaded_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS pending_balance(
  user_id INTEGER, amount REAL, number_id INTEGER, created_at TEXT
);
CREATE TABLE IF NOT EXISTS buy_prices(
  country TEXT PRIMARY KEY,
  code TEXT DEFAULT '',
  price REAL NOT NULL,
  flag TEXT DEFAULT '',
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_nums_status ON numbers(status);
CREATE INDEX IF NOT EXISTS idx_nums_platform ON numbers(platform);
CREATE INDEX IF NOT EXISTS idx_nums_buyer ON numbers(buyer_id);
CREATE INDEX IF NOT EXISTS idx_dep_user ON deposits(user_id);
CREATE INDEX IF NOT EXISTS idx_dep_status ON deposits(status);
CREATE TABLE IF NOT EXISTS static_pages_overrides(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  route TEXT UNIQUE NOT NULL,
  custom_html TEXT,
  is_active INTEGER DEFAULT 1,
  updated_by INTEGER,
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS dashboard_blocks(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  block_type TEXT NOT NULL DEFAULT 'text',
  reference_id INTEGER,
  content TEXT,
  column_pos TEXT DEFAULT 'full',
  sort_order INTEGER DEFAULT 0,
  is_active INTEGER DEFAULT 1,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS custom_pages(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  slug TEXT UNIQUE NOT NULL,
  title TEXT NOT NULL,
  content_html TEXT NOT NULL,
  meta_description TEXT,
  is_active INTEGER DEFAULT 1,
  created_by INTEGER,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS custom_links(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  url TEXT NOT NULL,
  icon_name TEXT DEFAULT 'link',
  color TEXT DEFAULT '#6366f1',
  position TEXT DEFAULT 'dashboard',
  target_users TEXT DEFAULT 'all',
  is_active INTEGER DEFAULT 1,
  sort_order INTEGER DEFAULT 0,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS dev_history(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  version TEXT UNIQUE NOT NULL,
  title TEXT NOT NULL,
  description TEXT,
  change_type TEXT DEFAULT 'update',
  files_changed TEXT,
  db_changes TEXT,
  backup_path TEXT,
  created_by INTEGER,
  created_at TEXT DEFAULT (datetime('now'))
);
"""

DEFAULT_SETTINGS = {
    "SITE_NAME": "MATARI STORE", "SUPPORT_USER": "@MO_5_H",
    "PROFILE_ID": "", "PROFILE_NAME": "MATARI STORE", "PROFILE_BIO": "مرحباً بك في متجري، يمكنك التحويل على الآيدي أدناه.",
    "MIN_DEPOSIT_USD": "0.10", "REFERRAL_REWARD": "0.001", "CURRENCY": "USD",
    "EMAIL_ADDRESS": "", "EMAIL_PASSWORD": "",
    "IMAP_HOST": "imap.gmail.com", "IMAP_FOLDERS": "INBOX",
    "TG_API_ID": "22651991", "TG_API_HASH": "ecad214ecff6a5cd90fc141d4e32f597",
    "BINANCE_API_KEY": "OwzBspNyOTGHJDyc4dWs4IOUsWeI2545xRVbP6zlwREaFeyBiKGwrfcribztTvg2",
    "BINANCE_API_SECRET": "myHSYz8sN0ptu0w7OGiuSo7LIT93OJNGQJClK1TySLFRU6wZNA8FOJNGj52HPAxT",
    "BINANCE_PAY_ID": "914222418",
    "JEEB_ACCOUNT": "1596606", "JEEB_RATE_YE": "540", "JEEB_RATE_SA": "3.75",
    "ONECASH_ACCOUNT": "148175861", "ONECASH_RATE_YE": "540", "ONECASH_RATE_SA": "3.75",
    "TRANSFER_FEE": "0.05",
    "DAILY_BONUS": "0.01",
    "REFERRAL_ENABLED": "1",
    "DAILY_BONUS_ENABLED": "1",
    "BACKUP_BOT_TOKEN": "7331163937:AAFwmM45N8hAhFOPnM26QXAWaK-SCqvPgqc",
    "BACKUP_CHAT_ID": "7325566792",
}

# الدول الافتراضية لأسعار الشراء (تُزرع تلقائياً لو الجدول فاضي)
DEFAULT_BUY_PRICES = [
    # (country, code, price, flag)
    ("اليمن", "967", 0.50, "🇾🇪"),
    ("السعودية", "966", 1.00, "🇸🇦"),
    ("مصر", "20", 0.30, "🇪🇬"),
    ("أمريكا", "1", 1.50, "🇺🇸"),
    ("الإمارات", "971", 1.20, "🇦🇪"),
    ("العراق", "964", 0.60, "🇮🇶"),
    ("الأردن", "962", 0.80, "🇯🇴"),
    ("سوريا", "963", 0.40, "🇸🇾"),
    ("لبنان", "961", 0.70, "🇱🇧"),
    ("المغرب", "212", 0.65, "🇲🇦"),
    ("الجزائر", "213", 0.55, "🇩🇿"),
    ("تونس", "216", 0.60, "🇹🇳"),
    ("ليبيا", "218", 0.55, "🇱🇾"),
    ("السودان", "249", 0.45, "🇸🇩"),
    ("عُمان", "968", 1.10, "🇴🇲"),
    ("الكويت", "965", 1.20, "🇰🇼"),
    ("قطر", "974", 1.20, "🇶🇦"),
    ("البحرين", "973", 1.10, "🇧🇭"),
    ("فلسطين", "970", 0.70, "🇵🇸"),
    ("تركيا", "90", 0.90, "🇹🇷"),
    ("بريطانيا", "44", 1.80, "🇬🇧"),
    ("ألمانيا", "49", 1.70, "🇩🇪"),
    ("فرنسا", "33", 1.70, "🇫🇷"),
    ("إسبانيا", "34", 1.60, "🇪🇸"),
    ("إيطاليا", "39", 1.60, "🇮🇹"),
    ("هولندا", "31", 1.60, "🇳🇱"),
    ("بلجيكا", "32", 1.60, "🇧🇪"),
    ("السويد", "46", 1.70, "🇸🇪"),
    ("النرويج", "47", 1.80, "🇳🇴"),
    ("الدنمارك", "45", 1.70, "🇩🇰"),
    ("فنلندا", "358", 1.70, "🇫🇮"),
    ("سويسرا", "41", 2.00, "🇨🇭"),
    ("النمسا", "43", 1.80, "🇦🇹"),
    ("بولندا", "48", 1.50, "🇵🇱"),
    ("أوكرانيا", "380", 1.20, "🇺🇦"),
    ("اليونان", "30", 1.50, "🇬🇷"),
    ("البرتغال", "351", 1.50, "🇵🇹"),
    ("أيرلندا", "353", 1.60, "🇮🇪"),
    ("روسيا", "7", 1.20, "🇷🇺"),
    ("الهند", "91", 0.50, "🇮🇳"),
    ("باكستان", "92", 0.40, "🇵🇰"),
    ("بنغلاديش", "880", 0.40, "🇧🇩"),
    ("إندونيسيا", "62", 0.55, "🇮🇩"),
    ("ماليزيا", "60", 0.70, "🇲🇾"),
    ("الفلبين", "63", 0.55, "🇵🇭"),
    ("الصين", "86", 0.80, "🇨🇳"),
    ("اليابان", "81", 1.50, "🇯🇵"),
    ("كوريا الجنوبية", "82", 1.40, "🇰🇷"),
    ("تايلاند", "66", 0.70, "🇹🇭"),
    ("فيتنام", "84", 0.60, "🇻🇳"),
    ("سنغافورة", "65", 1.50, "🇸🇬"),
    ("أستراليا", "61", 1.90, "🇦🇺"),
    ("كندا", "1", 1.80, "🇨🇦"),
    ("البرازيل", "55", 1.20, "🇧🇷"),
    ("المكسيك", "52", 1.10, "🇲🇽"),
    ("الأرجنتين", "54", 1.00, "🇦🇷"),
    ("جنوب أفريقيا", "27", 0.90, "🇿🇦"),
    ("نيجيريا", "234", 0.60, "🇳🇬"),
    ("كينيا", "254", 0.60, "🇰🇪"),
    ("إثيوبيا", "251", 0.50, "🇪🇹"),
]

def seed_buy_prices():
    """يزرع الدول الافتراضية في جدول buy_prices لو مش موجودة"""
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        # تأكد من وجود الجدول
        try:
            con.execute("SELECT 1 FROM buy_prices LIMIT 1")
        except sqlite3.OperationalError:
            # الجدول مش موجود، اخرج
            con.close()
            return
        count = con.execute("SELECT COUNT(*) c FROM buy_prices").fetchone()["c"]
        if count == 0:
            # الجدول فاضي — نزرع كل الدول الافتراضية
            for country, code, price, flag in DEFAULT_BUY_PRICES:
                con.execute(
                    "INSERT INTO buy_prices(country, code, price, flag) VALUES(?,?,?,?)",
                    (country, code, price, flag)
                )
            con.commit()
            print(f"[seed] planted {len(DEFAULT_BUY_PRICES)} countries in buy_prices")
        else:
            # الجدول فيه بيانات — نضيف الناقص فقط
            existing = {r["country"] for r in con.execute("SELECT country FROM buy_prices").fetchall()}
            added = 0
            for country, code, price, flag in DEFAULT_BUY_PRICES:
                if country not in existing:
                    con.execute(
                        "INSERT INTO buy_prices(country, code, price, flag) VALUES(?,?,?,?)",
                        (country, code, price, flag)
                    )
                    added += 1
            if added > 0:
                con.commit()
                print(f"[seed] added {added} missing countries to buy_prices")
    except Exception as e:
        print(f"[seed] error: {e}")
    finally:
        con.close()

def init_db():
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.executescript(SCHEMA)
    # ترحيل: عمود is_read في رسائل التذاكر (للقواعد القديمة)
    _tm_cols = [r[1] for r in con.execute("PRAGMA table_info(ticket_messages)")]
    if "is_read" not in _tm_cols:
        con.execute("ALTER TABLE ticket_messages ADD COLUMN is_read INTEGER DEFAULT 0")
    # إضافة أعمدة الإشعارات تلقائياً (لو الجدول موجود من نسخة قديمة)
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(announcements)")]
        if "text_color" not in cols:
            con.execute("ALTER TABLE announcements ADD COLUMN text_color TEXT DEFAULT '#e8e8f5'")
        if "font_size" not in cols:
            con.execute("ALTER TABLE announcements ADD COLUMN font_size TEXT DEFAULT '15px'")
        if "icon" not in cols:
            con.execute("ALTER TABLE announcements ADD COLUMN icon TEXT DEFAULT 'bell'")
        con.commit()
        print("[migration] announcements columns ensured")
    except sqlite3.OperationalError:
        pass
    # ترحيلات: أعمدة مستخدمة في الكود ومش موجودة في تعريف الجداول
    for table, col, decl in [("users", "avatar", "TEXT"), ("numbers", "is_premium", "INTEGER DEFAULT 0")]:
        cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
        if col not in cols:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
    con.execute("CREATE TABLE IF NOT EXISTS pending_sellers (number_id INTEGER, user_id INTEGER, created_at TEXT)")
    # Migration: أضف عمود code لو مش موجود (للقواعد القديمة)
    try:
        con.execute("ALTER TABLE buy_prices ADD COLUMN code TEXT DEFAULT ''")
        print("[migration] added code column to buy_prices")
    except sqlite3.OperationalError:
        pass  # موجود مسبقاً

    for k, v in DEFAULT_SETTINGS.items():
        con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
    # إنشاء الأدمن الافتراضي لو مش موجود (باسورد 733723953)
    if not con.execute("SELECT 1 FROM users WHERE is_admin=1 LIMIT 1").fetchone():
        con.execute(
            "INSERT INTO users(username,email,password_hash,recovery_key,is_admin,captcha_passed) VALUES(?,?,?,?,1,1)",
            ("admin", "admin@matari.local", generate_password_hash(ADMIN_DEFAULT_PASSWORD),
             "AT-" + secrets.token_hex(6).upper()))
    con.commit(); con.close()

# ============================================================
# SETTINGS
# ============================================================
def get_setting(k, d=None):
    r = db().execute("SELECT value FROM settings WHERE key=?", (k,)).fetchone()
    return r["value"] if r else d

def set_setting(k, v):
    db().execute("INSERT INTO settings(key,value) VALUES(?,?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, str(v)))
    db().commit()

def get_fee():
    """ترجع رسوم التحويل الحالية من الداتابيز (بتقراها كل مرة)"""
    try:
        return float(get_setting("TRANSFER_FEE", "0.05"))
    except (ValueError, TypeError):
        return 0.05

def all_settings():
    return {r["key"]: r["value"] for r in db().execute("SELECT key,value FROM settings")}

def audit(action, details=""):
    db().execute("INSERT INTO audit_log(user_id,action,details) VALUES(?,?,?)",
                 (session.get("user_id"), action, details[:500]))
    db().commit()

# ============================================================
# USERS
# ============================================================
def current_user():
    uid = session.get("user_id")
    if not uid: return None
    return db().execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()

def get_user(uid):
    return db().execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()

def get_user_by_ident(ident):
    return db().execute("SELECT * FROM users WHERE email=? OR username=?",
                        (ident.lower(), ident)).fetchone()

def create_user(username, email, password, referred_by=None):
    try:
        rk = "AT-" + secrets.token_hex(6).upper()
        custom_id = _generate_custom_id()
        cur = db().execute(
            "INSERT INTO users(username,email,password_hash,recovery_key,referred_by,custom_id) VALUES(?,?,?,?,?,?)",
            (username, email.lower(), generate_password_hash(password), rk, referred_by, custom_id))
        db().commit()
        return cur.lastrowid, rk, custom_id
    except sqlite3.IntegrityError:
        return None, None, None

def verify_password(user_row, password):
    return check_password_hash(user_row["password_hash"], password)



def _generate_custom_id():
    """يولّد آيدي عشوائي من 8 أرقام (لا يتكرر)"""
    import random
    for _ in range(100):
        new_id = str(random.randint(10000000, 99999999))
        existing = db().execute("SELECT 1 FROM users WHERE custom_id=?", (new_id,)).fetchone()
        if not existing:
            return new_id
    # في حالة فشل 100 مرة (احتمال ضئيل جداً)
    return str(random.randint(10000000, 99999999))


def is_banned(u): return bool(u and u["is_banned"])
def is_admin(u):  return bool(u and u["is_admin"])

# ============================================================
# DECORATORS
# ============================================================
def login_required(f):
    @wraps(f)
    def w(*a, **kw):
        if not session.get("user_id"):
            return redirect(url_for("login", next=request.path))
        u = current_user()
        # إصلاح: جلسة معلّقة (المستخدم محذوف من DB أو الجلسة قديمة)
        if not u:
            session.clear()
            flash("انتهت جلستك. سجّل الدخول من جديد.", "error")
            return redirect(url_for("login", next=request.path))
        if is_banned(u):
            session.clear(); flash("حسابك محظور.", "error")
            return redirect(url_for("login"))
        return f(*a, **kw)
    return w

def admin_required(f):
    @wraps(f)
    def w(*a, **kw):
        u = current_user()
        if not u or not u["is_admin"]:
            flash("غير مصرح بالدخول. سجل دخول بحساب الأدمن.", "error")
            return redirect(url_for("login", next=request.path))
        return f(*a, **kw)
    return w

def captcha_required(f):
    @wraps(f)
    def w(*a, **kw):
        if get_setting("CAPTCHA_ENABLED", "1") != "1":
            return f(*a, **kw)
        u = current_user()
        if not u: return f(*a, **kw)
        try:
            if u["captcha_passed"]: return f(*a, **kw)
        except (KeyError, IndexError):
            return f(*a, **kw)
        return redirect(url_for("captcha_verify", next=request.path))
    return w

# ============================================================
# HELPERS: Numbers / Buy / Coupons / VIP
# ============================================================
def list_available_numbers(platform=None, country=None, q=None,
                           sort="new", limit=20, offset=0):
    where, params = ["status='available'"], []
    if platform: 
        # إصلاح جذري: مطابقة ذكية لأي شكل للمنصة (whatsapp / WhatsApp / Telegram)
        p_low = str(platform).lower()
        if p_low in ('whatsapp', 'wa'):
            where.append("LOWER(platform) LIKE '%whatsapp%'")
        elif p_low in ('telegram', 'tg', 'telegram (session)'):
            where.append("LOWER(platform) LIKE '%telegram%'")
        else:
            where.append("LOWER(platform)=?")
            params.append(p_low)
    if country:  where.append("country=?");  params.append(country)
    if q:        where.append("(phone LIKE ? OR country LIKE ?)"); params += [f"%{q}%", f"%{q}%"]
    order_map = {
        "new": "country ASC, id DESC",
        "old": "country ASC, id ASC",
        "cheap": "country ASC, price ASC",
        "expensive": "country ASC, price DESC",
        "country": "country ASC, id DESC",
    }
    order = order_map.get(sort, "country ASC, id DESC")
    return db().execute(
        f"SELECT * FROM numbers WHERE {' AND '.join(where)} ORDER BY {order} LIMIT ? OFFSET ?",
        params + [limit, offset]).fetchall()

def count_available_numbers(platform=None, country=None, q=None):
    where, params = ["status='available'"], []
    if platform:
        p_low = str(platform).lower()
        if p_low in ('whatsapp', 'wa'):
            where.append("LOWER(platform) LIKE '%whatsapp%'")
        elif p_low in ('telegram', 'tg', 'telegram (session)'):
            where.append("LOWER(platform) LIKE '%telegram%'")
        else:
            where.append("LOWER(platform)=?")
            params.append(p_low)
    if country:  where.append("country=?");  params.append(country)
    if q:        where.append("(phone LIKE ? OR country LIKE ?)"); params += [f"%{q}%", f"%{q}%"]
    return db().execute(
        f"SELECT COUNT(*) c FROM numbers WHERE {' AND '.join(where)}", params
    ).fetchone()["c"]

def buy_number(user_id, number_id):
    con = db()
    try:
        con.execute("BEGIN")
        n = con.execute("SELECT * FROM numbers WHERE id=?", (number_id,)).fetchone()
        if not n: con.execute("ROLLBACK"); return False, "الرقم غير موجود."
        if n["status"] != "available":
            con.execute("ROLLBACK"); return False, "الرقم غير متاح."
        u = con.execute("SELECT balance FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not u or u["balance"] < n["price"]:
            con.execute("ROLLBACK"); return False, "رصيدك غير كافٍ."
        upd = con.execute(
            "UPDATE users SET balance=balance-? WHERE user_id=? AND balance>=?",
            (n["price"], user_id, n["price"])).rowcount
        if upd != 1: con.execute("ROLLBACK"); return False, "فشل الخصم."
        con.execute(
            "UPDATE numbers SET status='sold',buyer_id=?,sold_at=datetime('now') WHERE id=?",
            (user_id, number_id))
        con.commit()
        audit("buy_number", f"nid={number_id} price={n['price']}")
        return True, "تم الشراء."
    except Exception:
        try: con.execute("ROLLBACK")
        except: pass
        return False, "خطأ."

def redeem_voucher(user_id, code):
    con = db()
    try:
        con.execute("BEGIN")
        v = con.execute("SELECT * FROM vouchers WHERE code=? AND is_used=0", (code,)).fetchone()
        if not v: con.execute("ROLLBACK"); return False, "الكود غير صالح."
        con.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (v["amount"], user_id))
        con.execute("UPDATE vouchers SET is_used=1, used_by=? WHERE id=?", (user_id, v["id"]))
        con.commit()
        audit("redeem_voucher", f"code={code} amt={v['amount']}")
        return True, f"تم شحن ${v['amount']:.2f}."
    except Exception:
        try: con.execute("ROLLBACK")
        except: pass
        return False, "خطأ."

def approve_deposit(deposit_id, admin_id=None):
    con = db()
    try:
        con.execute("BEGIN")
        d = con.execute("SELECT * FROM deposits WHERE id=?", (deposit_id,)).fetchone()
        if not d: con.execute("ROLLBACK"); return False, "غير موجود."
        if d["status"] != "pending": con.execute("ROLLBACK"); return False, "ليست معلقة."
        con.execute("UPDATE users SET balance=balance+? WHERE user_id=?",
                    (d["amount_usd"], d["user_id"]))
        con.execute("UPDATE deposits SET status='approved',processed_at=datetime('now') WHERE id=?",
                    (deposit_id,))
        con.commit()
        make_safe_backup() # نسخ احتياطي عند الموافقة على الشحن
        audit("approve_deposit", f"did={deposit_id} amt={d['amount_usd']}")
        return True, "تمت الموافقة."
    except Exception:
        try: con.execute("ROLLBACK")
        except: pass
        return False, "خطأ."

def reject_deposit(deposit_id, admin_id=None):
    try:
        db().execute("UPDATE deposits SET status='rejected',processed_at=datetime('now') "
                     "WHERE id=? AND status='pending'", (deposit_id,))
        db().commit()
        audit("reject_deposit", f"did={deposit_id}")
        return True, "تم الرفض."
    except Exception:
        return False, "خطأ."

def stats():
    return {
        "users":   db().execute("SELECT COUNT(*) c FROM users").fetchone()["c"],
        "numbers": db().execute("SELECT COUNT(*) c FROM numbers").fetchone()["c"],
        "sold":    db().execute("SELECT COUNT(*) c FROM numbers WHERE status='sold'").fetchone()["c"],
        "pending": db().execute("SELECT COUNT(*) c FROM deposits WHERE status='pending'").fetchone()["c"],
        "tickets": db().execute("SELECT COUNT(*) c FROM tickets WHERE status='open'").fetchone()["c"],
        "revenue": db().execute("SELECT COALESCE(SUM(COALESCE(paid_price, price)),0) s FROM numbers WHERE status='sold'").fetchone()["s"],
    }

# ============================================================
# VIP / Coupons / Referral
# ============================================================
def _get_vip_info(spent):
    tiers_raw = get_setting("VIP_TIERS", "5:3,20:5,50:10")
    tiers = []
    for part in tiers_raw.split(","):
        try:
            need, disc = part.strip().split(":")
            tiers.append((float(need), float(disc)))
        except: continue
    pct, level = 0.0, 0
    for i, (need, disc) in enumerate(sorted(tiers), 1):
        if spent >= need: pct, level = disc, i
    return pct, level

def _calc_price(uid, base, coupon_pct=0.0):
    u = get_user(uid)
    spent = 0
    if u:
        try: spent = u["total_spent"] or 0
        except: spent = 0
    vip_pct, _ = _get_vip_info(spent)
    total = min(vip_pct + coupon_pct, 90)
    return round(max(base * (1 - total/100), 0.001), 4), vip_pct

def _coupon_check(code, uid):
    c = db().execute("SELECT * FROM coupons WHERE code=?", (code,)).fetchone()
    if not c: return None, "كوبون غير صحيح"
    if c["expires_at"] and c["expires_at"] < datetime.now().strftime("%Y-%m-%d %H:%M:%S"):
        return None, "انتهت صلاحية الكوبون"
    if c["max_uses"] and c["used_count"] >= c["max_uses"]:
        return None, "استُنفد الكوبون"
    used = db().execute("SELECT 1 FROM coupon_uses WHERE code=? AND user_id=?", (code, uid)).fetchone()
    if used: return None, "استخدمت هذا الكوبون سابقاً"
    return float(c["percent"]), None

def _consume_coupon(code, uid):
    pct, err = _coupon_check(code, uid)
    if pct is None: return None
    try:
        db().execute("UPDATE coupons SET used_count=used_count+1 WHERE code=?", (code,))
        db().execute("INSERT INTO coupon_uses(code,user_id,used_at) VALUES(?,?,?)",
                     (code, uid, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        db().commit()
        return pct
    except Exception:
        return None

def _release_coupon(code, uid):
    try:
        db().execute("UPDATE coupons SET used_count=MAX(used_count-1,0) WHERE code=?", (code,))
        db().execute("DELETE FROM coupon_uses WHERE code=? AND user_id=?", (code, uid))
        db().commit()
    except: pass

def _credit_referral(uid):
    u = get_user(uid)
    if not u or not u["referred_by"]: return
    existing = db().execute(
        "SELECT 1 FROM audit_log WHERE user_id=? AND action='referral_credited' LIMIT 1",
        (uid,)).fetchone()
    if existing: return
    reward = float(get_setting("REFERRAL_REWARD", "0.001"))
    try:
        db().execute("BEGIN")
        db().execute("UPDATE users SET balance=balance+?, referral_earnings=referral_earnings+? "
                     "WHERE user_id=?", (reward, reward, u["referred_by"]))
        db().execute("INSERT INTO audit_log(user_id,action,details) VALUES(?,?,?)",
                     (uid, "referral_credited", f"referrer={u['referred_by']}"))
        db().commit()
    except Exception:
        try: db().execute("ROLLBACK")
        except: pass



def esc(s):
    """تنقية النص من أكواد HTML الخطرة"""
    if s is None:
        return ""
    import html
    return html.escape(str(s))

def _site_icon_url(name):
    """يرجع رابط الأيقونة المرفوعة إن كانت محفوظة والملف موجود فعلاً، وإلا None."""
    try:
        row = db().execute("SELECT filename FROM site_icons WHERE name=?", (name,)).fetchone()
    except Exception:
        return None
    if not row or not row["filename"]:
        return None
    if not os.path.exists(os.path.join(BASE_DIR, "static", "icons", row["filename"])):
        return None
    return "/static/icons/" + row["filename"]
def site_icon(name, size=28, fallback=""):
    """يرجع <img> للأيقونة المرفوعة إن وجدت، أو fallback (SVG) إن لم توجد.
    يدعم: PNG, JPG, SVG, WEBP, GIF (متحرك), MP4, WEBM"""
    # الأيقونات الافتراضية المدمجة في الكود
    DEFAULT_ICONS = {
        "whatsapp": '<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="#25D366"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/></svg>',
        "telegram": '<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="#0088cc"><path d="M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0zm5.562 8.161c-.18 1.897-.962 6.502-1.359 8.627-.168.9-.5 1.201-.82 1.23-.697.064-1.226-.461-1.901-.903-1.056-.692-1.653-1.123-2.678-1.798-1.185-.781-.417-1.21.258-1.911.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635.099-.002.321.023.465.14a.506.506 0 01.171.325c.016.093.036.306.02.472z"/></svg>',
        "whatsapp_btn": '<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="#25D366"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/></svg>',
        "telegram_btn": '<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="#0088cc"><path d="M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0zm5.562 8.161c-.18 1.897-.962 6.502-1.359 8.627-.168.9-.5 1.201-.82 1.23-.697.064-1.226-.461-1.901-.903-1.056-.692-1.653-1.123-2.678-1.798-1.185-.781-.417-1.21.258-1.911.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635.099-.002.321.023.465.14a.506.506 0 01.171.325c.016.093.036.306.02.472z"/></svg>',
    }
    
    row = db().execute("SELECT filename FROM site_icons WHERE name=?", (name,)).fetchone()
    if row and row["filename"] and os.path.exists(os.path.join(BASE_DIR, "static", "icons", row["filename"])):
        fn = row["filename"]
        ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else ""
        # فيديو → نعرضه بـ <video>
        if ext in ("mp4", "webm", "m4v", "mov"):
            return (f'<video autoplay loop muted playsinline '
                    f'style="width:{size}px;height:{size}px;object-fit:contain;'
                    f'display:inline-block;vertical-align:middle;flex-shrink:0">'
                    f'<source src="/static/icons/{fn}" type="video/{ext}">'
                    f'</video>')
        # صورة أو GIF → نعرضها بـ <img>
        return (f'<img src="/static/icons/{fn}" '
                f'style="width:{size}px;height:{size}px;object-fit:contain;'
                f'display:inline-block;vertical-align:middle;flex-shrink:0" alt="{name}">')
    
    # لو مفيش حاجة في الداتابيز، نرجع الأيقونة الافتراضية المدمجة أو الـ fallback
    if name in DEFAULT_ICONS:
        return DEFAULT_ICONS[name].replace("{size}", str(size))
    
    return fallback

def save_site_icon(name, file_storage):
    """يحفظ ملف الصورة في static/icons ويسجله في قاعدة البيانات."""
    import os as _os
    from werkzeug.utils import secure_filename
    name = (name or "").strip().lower()
    if not name or not file_storage or not file_storage.filename:
        return False, "اسم الأيقونة أو الملف مفقود"
    ext = _os.path.splitext(file_storage.filename)[1].lower()
    # كل الصيغ المدعومة
    if ext not in (".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif", ".webm", ".mp4", ".m4v", ".mov", ".avi", ".mkv"):
        return False, "صيغة غير مدعومة (صور أو فيديو)"
    safe_name = secure_filename(name) or name
    filename = f"{safe_name}{ext}"
    target = _os.path.join(BASE_DIR, "static", "icons", filename)
    try:
        _os.makedirs(_os.path.dirname(target), exist_ok=True)
        file_storage.save(target)
        
        # لو الملف فيديو → نحوله لـ MP4 متوافق مع كل المتصفحات
        if ext in (".webm", ".mp4", ".m4v", ".mov", ".avi", ".mkv", ".3gp"):
            converted_path, conv_err = convert_video_for_web(target)
            if conv_err is None and os.path.exists(converted_path):
                print(f"[ICON] تم تحويل الفيديو: {converted_path}")
                filename = os.path.basename(converted_path)
            else:
                print(f"[ICON] فشل التحويل: {conv_err}")
        
        db().execute("INSERT INTO site_icons(name, filename) VALUES(?, ?) "
                     "ON CONFLICT(name) DO UPDATE SET filename=excluded.filename, uploaded_at=datetime('now')",
                     (name, filename))
        db().commit()
        return True, f"تم رفع {filename}"
    except Exception as e:
        return False, f"خطأ: {e}"

def convert_video_for_web(file_path):
    """يحول أي فيديو لصيغة MP4 (H.264) متوافقة مع كل المتصفحات"""
    import subprocess, os, shutil
    if not os.path.exists(file_path):
        return file_path, "الملف غير موجود"
    ext = os.path.splitext(file_path)[1].lower()
    if ext not in (".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".3gp"):
        return file_path, "ليس فيديو"
    out_path = os.path.splitext(file_path)[0] + "_web.mp4"
    try:
        cmd = [
            "ffmpeg", "-i", file_path,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            "-y", out_path
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=120)
        if result.returncode == 0 and os.path.exists(out_path):
            # استبدل الملف الأصلي بالجديد
            if os.path.basename(file_path) != os.path.basename(out_path):
                os.remove(file_path)
                final_path = file_path.replace(ext, ".mp4")
                shutil.move(out_path, final_path)
                return final_path, None
            return out_path, None
        else:
            return file_path, "فشل التحويل: " + result.stderr.decode()[:200]
    except Exception as e:
        return file_path, str(e)

def delete_site_icon(name):
    import os as _os
    row = db().execute("SELECT filename FROM site_icons WHERE name=?", (name,)).fetchone()
    if row and row["filename"]:
        try:
            _os.remove(_os.path.join(BASE_DIR, "static", "icons", row["filename"]))
        except Exception:
            pass
    db().execute("DELETE FROM site_icons WHERE name=?", (name,))
    db().commit()
    return True

# ============================================================
# OTP FETCH (IMAP)
# ============================================================
def _extract_otp(text):
    if not text: return None
    for pat in [r"(?<!\d)(\d{3})[-\s]?(\d{3})(?!\d)", r"(?<!\d)(\d{4,8})(?!\d)"]:
        m = re.search(pat, text)
        if m:
            code = "".join(m.groups())
            if 4 <= len(code) <= 8: return code
    return None




def _tg_request_code(phone):
    try:
        from telethon.sync import TelegramClient
        from telethon.sessions import StringSession
    except ImportError:
        return None, None, "telethon غير مثبتة"
    import asyncio
    api_id = int(get_setting("TG_API_ID", "22651991"))
    api_hash = get_setting("TG_API_HASH", "").strip()
    if not api_hash:
        return None, None, "API Hash غير مهيأ"
    if not re.match(r'^\+[1-9]\d{6,14}$', phone):
        return None, None, "رقم غير صالح"
    async def run():
        client = TelegramClient(StringSession(), api_id, api_hash)
        await client.connect()
        try:
            sent = await client.send_code_request(phone)
            return client.session.save(), sent.phone_code_hash, None
        finally:
            await client.disconnect()
    try:
        return asyncio.run(asyncio.wait_for(run(), 60))
    except Exception as e:
        return None, None, "خطأ: " + str(e)[:100]

def _tg_verify_code(phone, code, session_str, code_hash):
    try:
        from telethon.sync import TelegramClient
        from telethon.sessions import StringSession
    except ImportError:
        return None, "error", "telethon غير مثبتة"
    import asyncio
    api_id = int(get_setting("TG_API_ID", "22651991"))
    api_hash = get_setting("TG_API_HASH", "").strip()
    async def run():
        client = TelegramClient(StringSession(session_str), api_id, api_hash)
        await client.connect()
        try:
            try:
                await client.sign_in(phone=phone, code=code, phone_code_hash=code_hash)
            except Exception as e:
                if type(e).__name__ == "SessionPasswordNeededError":
                    return None, "2fa", None
                raise
            if not await client.is_user_authorized():
                return None, "error", "لم يكتمل"
            return client.session.save(), "ok", None
        finally:
            await client.disconnect()
    try:
        return asyncio.run(asyncio.wait_for(run(), 60))
    except Exception as e:
        return None, "error", "خطأ: " + str(e)[:100]

def _tg_verify_password(session_str, password):
    try:
        from telethon.sync import TelegramClient
        from telethon.sessions import StringSession
    except ImportError:
        return None, "telethon غير مثبتة"
    import asyncio
    api_id = int(get_setting("TG_API_ID", "22651991"))
    api_hash = get_setting("TG_API_HASH", "").strip()
    async def run():
        client = TelegramClient(StringSession(session_str), api_id, api_hash)
        await client.connect()
        try:
            await client.sign_in(password=password)
            if not await client.is_user_authorized():
                return None, "لم يكتمل"
            return client.session.save(), None
        finally:
            await client.disconnect()
    try:
        return asyncio.run(asyncio.wait_for(run(), 60))
    except Exception as e:
        return None, "خطأ: " + str(e)[:100]


def binance_auto_verify(order_id, expected_amount):
    import hmac, hashlib, time, requests
    from urllib.parse import urlencode
    api_key = get_setting("BINANCE_API_KEY", "")
    api_secret = get_setting("BINANCE_API_SECRET", "")
    if not api_key or not api_secret:
        return False, "مفاتيح Binance غير مهيأة في الإعدادات."
    
    params = {"timestamp": int(time.time() * 1000), "recvWindow": 5000, "limit": 100}
    qs = urlencode(params)
    sig = hmac.new(api_secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
    url = "https://api.binance.com/sapi/v1/pay/transactions?" + qs + "&signature=" + sig
    headers = {"X-MBX-APIKEY": api_key}
    
    try:
        res = requests.get(url, headers=headers, timeout=20).json()
        if not res.get("success"):
            return False, "خطأ في الاتصال بـ Binance: " + str(res.get("message", ""))
        
        for tx in res.get("data", []):
            if str(tx.get("orderId", "")) == str(order_id):
                amount = float(tx.get("amount", 0))
                if amount >= float(expected_amount):
                    return True, "تم التحقق بنجاح!"
                else:
                    return False, f"المبلغ المرسل ({amount}$) أقل من المطلوب ({expected_amount}$)."
        return False, "لم يتم العثور على Order ID. تأكد من نسخه بشكل صحيح."
    except Exception as e:
        return False, "خطأ تقني: " + str(e)[:80]


def _tg_fetch_code(session_str, since_ts=0, phone=None):
    """يقرأ آخر كود من رسائل تيليجرام (مثل البوت الأصلي - بدون طلب كود جديد)"""
    if not session_str:
        return None, "لا جلسة."
    try:
        from telethon.sync import TelegramClient
        from telethon.sessions import StringSession
        api_id = int(get_setting("TG_API_ID", "22651991"))
        api_hash = get_setting("TG_API_HASH", "").strip()
        if not api_hash:
            return None, "API Hash غير مهيأ."
        
        import asyncio
        import re as _re
        
        async def run():
            client = TelegramClient(StringSession(session_str), api_id, api_hash)
            await client.connect()
            try:
                if not await client.is_user_authorized():
                    return None, "الجلسة غير مفعلة"
                
                # نقرأ آخر 10 رسائل من 777000
                async for msg in client.iter_messages(777000, limit=10):
                    if msg.text:
                        # نبحث عن أي كود 5-6 أرقام
                        m = _re.search(r"\b(\d{5,6})\b", msg.text)
                        if m:
                            code = m.group(1)
                            # نتجاهل الرسائل القديمة (قبل وقت الشراء)
                            if since_ts > 0:
                                try:
                                    msg_ts = msg.date.timestamp()
                                    if msg_ts < since_ts - 60:
                                        continue
                                except Exception:
                                    pass
                            return code, None
                
                return None, "لا يوجد كود جديد في الرسائل الأخيرة."
            finally:
                await client.disconnect()
        return asyncio.run(asyncio.wait_for(run(), 30))
    except ImportError:
        return None, "مكتبة telethon غير مثبتة."
    except Exception as e:
        return None, "خطأ: " + str(e)[:100]

def fetch_otp_telethon(session_string):
    if not session_string: return None, "لا جلسة."
    try:
        from telethon.sync import TelegramClient
        from telethon.sessions import StringSession
        api_id = int(get_setting("TG_API_ID", "22651991"))
        api_hash = get_setting("TG_API_HASH", "").strip()
        if not api_hash: return None, "API Hash غير مهيأ."
        with TelegramClient(StringSession(session_string), api_id, api_hash) as client:
            for msg in client.iter_messages(777000, limit=10):
                if msg.text:
                    code = _extract_otp(msg.text)
                    if code: return code, None
        return None, "لا كود."
    except ImportError:
        return None, "telethon غير مثبتة."
    except Exception as e:
        return None, f"خطأ: {e}"



# ============================================================
# CSS
# ============================================================
CSS = """

/* ==== حركات الأيقونات ==== */
@keyframes bell-ring {
    0%, 100% { transform: rotate(0); }
    10%, 30%, 50%, 70%, 90% { transform: rotate(-8deg); }
    20%, 40%, 60%, 80% { transform: rotate(8deg); }
}
@keyframes cart-pulse {
    0% { transform: scale(1); }
    50% { transform: scale(1.15); }
    100% { transform: scale(1); }
}
@keyframes clock-tick-live {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
}
@keyframes search-shake {
    0%, 100% { transform: translateX(0); }
    25% { transform: translateX(-3px); }
    75% { transform: translateX(3px); }
}
@keyframes refresh-spin {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
}

/* تطبيق الحركات على الأيقونات المهمة */
.admin-tile:hover .admin-tile-icon svg,
.admin-stat:hover svg {
    animation: cart-pulse 1s ease-in-out infinite;
}
.live-timer svg, .clock-hand {
    animation: clock-tick-live 2s linear infinite;
}
.search-bar:focus-within svg {
    animation: search-shake 0.4s ease-in-out infinite;
    color: var(--primary2);
}
.bottom-nav a.active svg {
    animation: cart-pulse 2s ease-in-out infinite;
}
#otpBtn:hover #otpBtnIcon svg {
    animation: refresh-spin 1s linear infinite;
}
#copyBtn:hover svg,
.btn:hover svg {
    animation: cart-pulse 0.6s ease-in-out;
}

/* ==== إخفاء خلفية GIF السوداء تلقائياً (تحتاج خلفية غامقة) ==== */
img[src$=".gif"], img[src$=".GIF"] {
    mix-blend-mode: screen !important;
    filter: contrast(1.15) brightness(1.1);
}
/* قاعدة مخصصة لصور الأفاتار GIF */
img[src*="/avatars/"][src$=".gif"],
img[src*="/avatars/"][src$=".GIF"] {
    mix-blend-mode: screen !important;
    filter: contrast(1.15) brightness(1.1);
    background: transparent !important;
}
/* قاعدة قوية للوجو في الـ Navbar */
.nav img[src$=".gif"], .nav img[src$=".GIF"],
.brand img[src$=".gif"], .brand img[src$=".GIF"] {
    mix-blend-mode: screen !important;
    filter: contrast(1.2) brightness(1.1) !important;
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    border-radius: 0 !important;
}
/* قاعدة قوية للوجو في الكارت */
.login-logo img[src$=".gif"], .login-logo img[src$=".GIF"],
.register-logo img[src$=".gif"], .register-logo img[src$=".GIF"] {
    mix-blend-mode: screen !important;
    filter: contrast(1.2) brightness(1.1) !important;
}
/* ما نطبقهاش على صور البروفايل لو عايزينها تفضل زي ما هي */
.uc-avatar img[src$=".gif"], .uc-avatar img[src$=".GIF"],
.avatar img[src$=".gif"], .avatar img[src$=".GIF"] {
    mix-blend-mode: normal !important;
    filter: none !important;
}
:root{--bg:#0f0f1a;--bg2:#15152a;--card:#1a1a30;--card2:#232340;--border:#2d2d4a;--text:#e8e8f5;--muted:#8888aa;--primary:#6366f1;--primary2:#818cf8;--success:#10b981;--danger:#ef4444;--warn:#f59e0b;--gradient:linear-gradient(135deg,#6366f1,#8b5cf6,#06b6d4);--radius:16px;--shadow:none;--font:'Cairo','Inter',-apple-system,sans-serif}
[data-theme="light"]{--bg:#f8fafc;--bg2:#f1f5f9;--card:#ffffff;--card2:#f8fafc;--border:#e2e8f0;--text:#0f172a;--muted:#64748b;--shadow:0 8px 32px rgba(0,0,0,.08)}
*{margin:0;padding:0;box-sizing:border-box;font-family:var(--font);-webkit-tap-highlight-color:transparent;}
html{scroll-behavior:smooth;-webkit-overflow-scrolling:touch;}
body{overscroll-behavior-y:none;}
/* تسريع الرسوميات لسلاسة 120Hz */
.num-card, .card, .btn, .bottom-nav a, .nav, .admin-tile {
    will-change: transform, opacity;
    transform: translateZ(0);
    -webkit-backface-visibility: hidden;
    backface-visibility: hidden;
}
/* تقليل استهلاك الحركات الخلفية */
@media (prefers-reduced-motion: no-preference) {
    .fade-in, .num-card { animation-duration: 0.3s !important; }
}
body{background:var(--bg);color:var(--text);min-height:100vh;line-height:1.6;transition:background .3s,color .3s;overflow-x:hidden}
a{color:inherit;text-decoration:none}
button{font-family:inherit;cursor:pointer}
svg{display:block}
code{font-family:monospace;background:var(--card2);padding:2px 8px;border-radius:6px;font-size:.9em;color:var(--primary2)}
.nav{position:sticky;top:0;z-index:100;background:rgba(15,15,26,.85);backdrop-filter:blur(20px);border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;padding:14px 28px;gap:20px;flex-wrap:wrap}
[data-theme="light"] .nav{background:rgba(248,250,252,.85)}
.brand{display:flex;align-items:center;gap:10px;font-weight:800;font-size:18px}
.brand-text{background:var(--gradient);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.nav-links{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.nav-links a,.nav-links button{color:var(--muted);font-size:14px;font-weight:500;padding:8px 14px;border-radius:10px;border:none;background:transparent;transition:all .2s;display:flex;align-items:center;gap:6px}
.nav-links a:hover,.nav-links button:hover{color:var(--text);background:var(--card)}
.btn-accent{background:var(--gradient)!important;color:#fff!important;padding:8px 18px!important;font-weight:600!important;box-shadow:0 4px 16px rgba(99,102,241,.35)}
.container{max-width:1200px;margin:0 auto;padding:32px 24px;width:100%}
.hero{text-align:center;padding:80px 20px 60px}
.hero h1{font-size:clamp(32px,6vw,58px);font-weight:900;letter-spacing:-1.5px;background:var(--gradient);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;margin-bottom:20px;line-height:1.1}
.hero p{color:var(--muted);font-size:18px;max-width:600px;margin:0 auto 32px;line-height:1.7}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;padding:12px 24px;border-radius:12px;border:none;font-weight:700;font-size:15px;background:var(--gradient);color:#fff;transition:all .2s;cursor:pointer;box-shadow:0 4px 16px rgba(99,102,241,.3)}
.btn:hover{transform:translateY(-2px)}
.btn-sm{padding:8px 16px;font-size:13px}
.btn-ghost{background:var(--card);color:var(--text);border:1px solid var(--border);box-shadow:none}
.card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:24px;transition:all .3s;box-shadow:none !important;}
.form-card{max-width:440px;margin:60px auto;background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:40px;box-shadow:var(--shadow)}
.form-card h2{font-size:26px;margin-bottom:8px;font-weight:900}
.form-card .sub{color:var(--muted);font-size:14px;margin-bottom:28px}
.field{margin-bottom:18px}
.field label{display:block;font-size:13px;font-weight:600;margin-bottom:8px;color:var(--muted)}
.field input,.field select,.field textarea{width:100%;padding:13px 16px;background:var(--bg2);color:var(--text);border:1.5px solid var(--border);border-radius:12px;font-size:14px;font-family:inherit}
.field input:focus,.field select:focus,.field textarea:focus{outline:none;border-color:var(--primary);box-shadow:0 0 0 4px rgba(99,102,241,.15)}
.form-btn{width:100%;padding:14px;border:none;border-radius:12px;font-weight:700;font-size:15px;background:var(--gradient);color:#fff;margin-top:8px;cursor:pointer;box-shadow:0 4px 16px rgba(99,102,241,.3)}
.flash{padding:14px 18px;border-radius:12px;font-size:14px;font-weight:500;margin-bottom:20px}
.flash.success{background:rgba(16,185,129,.12);color:var(--success);border:1px solid rgba(16,185,129,.3)}
.flash.error{background:rgba(239,68,68,.12);color:var(--danger);border:1px solid rgba(239,68,68,.3)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:20px}
.num-card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:20px;transition:all .3s;cursor:pointer}
.num-card:hover{border-color:var(--primary);transform:translateY(-3px);box-shadow:var(--shadow)}
.num-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px}
@keyframes clock-tick { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
.clock-hand { transform-origin: 12px 12px; animation: clock-tick 2s linear infinite; }
.badge{padding:5px 12px;border-radius:8px;font-size:11px;font-weight:800;letter-spacing:.5px}
.badge.whatsapp{background:rgba(37,211,102,.15);color:#25d366}
.badge.telegram{background:rgba(6,182,212,.15);color:#06b6d4}
.badge.available{background:rgba(16,185,129,.15);color:var(--success)}
.badge.sold,.badge.rejected,.badge.banned{background:rgba(239,68,68,.15);color:var(--danger)}
.badge.pending{background:rgba(245,158,11,.15);color:var(--warn)}
.badge.approved{background:rgba(16,185,129,.15);color:var(--success)}
.num-country{color:var(--muted);font-size:13px;margin-bottom:8px}
.num-phone{font-family:monospace;font-size:15px;margin-bottom:14px;direction:ltr;text-align:left;color:var(--text)}
.num-price{font-size:26px;font-weight:900;background:var(--gradient);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;direction:ltr;text-align:left}
.section-title{font-size:24px;font-weight:900;margin-bottom:24px}
.section-sub{color:var(--muted);font-size:14px;font-weight:400;margin-right:8px}
.dash-hello{font-size:32px;font-weight:900;margin-bottom:8px}
.dash-balance{font-size:40px;font-weight:900;background:var(--gradient);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;margin-bottom:24px;direction:ltr}
.dash-actions{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:40px}
.table-wrap{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);overflow:auto}
.table{width:100%;border-collapse:collapse}
.table th,.table td{padding:14px 16px;text-align:right;border-bottom:1px solid var(--border);font-size:14px;white-space:nowrap}
.table th{background:var(--card2);color:var(--muted);font-weight:700;font-size:12px;text-transform:uppercase;letter-spacing:.5px}
.table tr:hover td{background:var(--card2)}
.table tr:last-child td{border-bottom:none}
.empty{padding:60px 20px;text-align:center;color:var(--muted);background:var(--card);border:1px dashed var(--border);border-radius:var(--radius)}

@media(max-width:640px){.nav{padding:12px 16px;gap:12px}.nav-links a,.nav-links button{padding:6px 10px;font-size:13px}.container{padding:24px 16px}.hero{padding:60px 16px 40px}.form-card{margin:32px 16px;padding:28px}.dash-hello{font-size:24px}.dash-balance{font-size:32px}}
@keyframes fadeInUp{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:translateY(0)}}
@keyframes pulse{0%{transform:scale(1)}50%{transform:scale(1.15)}100%{transform:scale(1)}}
.fade-in{animation:fadeInUp .5s ease}
.num-card,.card{}




/* تصميم الفلاتر المنسدلة الحديثة */
.filters-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
    margin-bottom: 20px;
}
.filter-box {
    position: relative;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    overflow: hidden;
}
.filter-box.full-width {
    grid-column: 1 / -1;
}
.filter-box select {
    width: 100%;
    padding: 14px 40px 14px 16px;
    background: transparent;
    border: none;
    color: var(--text);
    font-family: inherit;
    font-size: 14px;
    font-weight: 600;
    appearance: none;
    -webkit-appearance: none;
    cursor: pointer;
    outline: none;
}
.filter-box select:focus {
    background: rgba(99,102,241,.05);
}
.filter-box::after {
    content: '';
    position: absolute;
    left: 16px;
    top: 50%;
    transform: translateY(-50%);
    width: 10px;
    height: 10px;
    border-right: 2px solid var(--muted);
    border-bottom: 2px solid var(--muted);
    transform: translateY(-70%) rotate(45deg);
    pointer-events: none;
}
.search-bar {
    display: flex; align-items: center; gap: 10px; padding: 0 16px;
    background: var(--card); border: 1px solid var(--border); border-radius: 12px; margin-bottom: 12px;
}
.search-bar input { flex: 1; padding: 14px 0; background: transparent; border: none; color: var(--text); font-family: inherit; font-size: 14px; outline: none; }
.search-bar svg { width: 18px; height: 18px; stroke: var(--muted); fill: none; stroke-width: 2; }
/* مساحة فارغة أسفل الصفحة عشان الشريط ما يغطي المحتوى */
@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
@keyframes spin-icon { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
.spinning { animation: spin-icon 1s linear infinite; display: inline-block !important; }
@keyframes slideDown { from { opacity: 0; transform: translateY(-20px); } to { opacity: 1; transform: translateY(0); } }
@keyframes slideUp { from { opacity: 1; transform: translateY(0); } to { opacity: 0; transform: translateY(-20px); } }
body { padding-bottom: 76px; }

/* قائمة الحساب المنسدلة */
.account-menu {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    overflow: hidden;
    margin-bottom: 24px;
}
.account-menu a, .account-menu button {
    display: flex;
    align-items: center;
    gap: 12px;
    width: 100%;
    padding: 16px 20px;
    border-bottom: 1px solid var(--border);
    color: var(--text);
    font-weight: 600;
    font-size: 14px;
    background: transparent;
    border-left: none;
    border-right: none;
    border-top: none;
    text-align: right;
    cursor: pointer;
}
.account-menu a:last-child, .account-menu button:last-child { border-bottom: none; }
.account-menu a:active, .account-menu button:active { background: var(--bg2); }
/* تم إزالة الستايل القديم لأيقونات account-menu ليظهر كل SVG بلونه وحجمه */
html, body {
    touch-action: pan-x pan-y;
    -webkit-user-select: none;
    user-select: none;
    -webkit-touch-callout: none;
}
.copyable, code, input, textarea {
    -webkit-user-select: text !important;
    user-select: text !important;
    -webkit-touch-callout: default !important;
}
.copy-btn-inline {
    background: rgba(99,102,241,.15);
    border: 1px solid rgba(99,102,241,.3);
    color: #818cf8;
    padding: 6px 10px;
    border-radius: 8px;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-family: inherit;
    font-size: 12px;
    font-weight: 700;
    transition: all .2s;
    margin-right: 8px;
}
.copy-btn-inline:active { transform: scale(.92); }
.copy-btn-inline svg { width: 14px; height: 14px; stroke: currentColor; fill: none; stroke-width: 2; }


[data-theme="light"] 




body { padding-bottom: 75px; }

.bottom-nav {
    position: fixed;
    bottom: 0; left: 0; right: 0;
    height: 65px;
    background: rgba(15,15,26,.98);
    border-top: 1px solid var(--border);
    display: flex;
    align-items: center;
    justify-content: space-around;
    z-index: 9999;
    padding-bottom: env(safe-area-inset-bottom);
}
[data-theme="light"] .bottom-nav { background: rgba(255,255,255,.98); }

.bottom-nav a {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 4px;
    color: var(--muted);
    font-size: 10.5px;
    font-weight: 700;
    text-decoration: none;
    height: 100%;
    padding: 0;
    margin: 0;
    transition: all .2s;
}

/* تأثير التوهج واللون المميز للزر المختار */
.bottom-nav a.active { 
    color: var(--primary2); 
}
.bottom-nav a.active svg {
    filter: drop-shadow(0 0 8px rgba(99,102,241,.6));
    transform: translateY(-2px);
}

.bottom-nav a svg {
    width: 24px;
    height: 24px;
    display: block;
    flex-shrink: 0;
    transition: transform .2s;
}

body { padding-bottom: 75px; }


.app-footer svg {
    width: 16px;
    height: 16px;
    stroke: var(--primary2);
    fill: none;
    stroke-width: 2;
}






/* تصميم الحقوق كبطاقة صغيرة */
.app-footer {
    display: flex;
    justify-content: center;
    padding: 30px 20px 90px 20px;
}
.footer-badge {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    background: var(--card);
    border: 1px solid var(--border);
    padding: 8px 16px;
    border-radius: 30px;
    font-size: 11px;
    font-weight: 700;
    color: var(--muted);
    box-shadow: 0 4px 12px rgba(0,0,0,0.1);
}
.footer-badge svg {
    width: 14px;
    height: 14px;
    stroke: var(--primary2);
    fill: none;
    stroke-width: 2.5;
}
.footer-badge span {
    color: var(--text);
    opacity: 0.8;
}

.btn svg {
    display: inline-block;
    vertical-align: middle;
}
.btn-sm svg {
    width: 16px;
    height: 16px;
}

.num-phone svg {
    color: var(--primary2);
    opacity: 0.8;
    vertical-align: middle;
}

/* ===== Admin Grid ===== */
.admin-stats-row {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 10px;
    margin-bottom: 24px;
}
.admin-stat {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 16px 8px;
    text-align: center;
}
.admin-stat-num {
    font-size: 24px;
    font-weight: 900;
    margin-bottom: 4px;
}
.admin-stat-label {
    font-size: 11px;
    color: var(--muted);
    font-weight: 600;
}
.admin-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 12px;
}
.admin-tile {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 10px;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 22px 12px;
    text-decoration: none;
    color: var(--text);
    transition: all 0.25s;
}
.admin-tile:active {
    background: var(--bg2);
}
.admin-tile:hover {
    border-color: var(--primary);
}
.admin-tile-icon {
    width: 42px;
    height: 42px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(99,102,241,.08);
    border-radius: 12px;
}
.admin-tile-icon svg {
    width: 24px;
    height: 24px;
}
.admin-tile-label {
    font-size: 13px;
    font-weight: 700;
    text-align: center;
}


.buy-price-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 12px;
    display: flex;
    align-items: center;
    gap: 10px;
    transition: all 0.2s;
}
.buy-price-card:hover {
    border-color: var(--primary);
    transform: translateY(-1px);
}
.buy-price-flag {
    font-size: 24px;
    flex-shrink: 0;
}
.buy-price-name {
    flex: 1;
    font-weight: 800;
    font-size: 14px;
    color: var(--text);
}
.buy-price-value {
    font-size: 16px;
    font-weight: 900;
    color: var(--success);
    direction: ltr;
    flex-shrink: 0;
}
.buy-price-delete {
    background: var(--danger);
    color: #fff;
    padding: 6px 12px;
    border-radius: 8px;
    border: none;
    font-size: 12px;
    font-weight: 700;
    cursor: pointer;
    flex-shrink: 0;
}

@media(max-width: 400px) {
    .admin-stats-row {
        grid-template-columns: repeat(2, 1fr);
    }
}
"""

JS = """


// إخفاء رسائل التنبيه تلقائياً بعد 5 ثواني
document.addEventListener('DOMContentLoaded', function() {
    setTimeout(function() {
        document.querySelectorAll('.toast-message').forEach(function(el) {
            el.style.animation = 'slideUp 0.4s ease forwards';
            setTimeout(function() { el.style.display = 'none'; }, 400);
        });
    }, 5000);
});

function toggleAdminBtn(e) {
    e.preventDefault();
    var btn = document.getElementById('adminBtn');
    if (!btn) return;
    if (btn.style.display === 'none' || btn.style.display === '') {
        btn.style.display = 'inline-flex';
        btn.style.alignItems = 'center';
    } else {
        btn.style.display = 'none';
    }
}

function toggleTheme(){
    var cur = document.documentElement.getAttribute('data-theme') || 'dark';
    var nxt = cur === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', nxt);
    try { localStorage.setItem('theme', nxt); } catch(e) {}
    var icon = document.getElementById('themeIcon');
    if (icon) {
        if (nxt === 'dark') {
            icon.innerHTML = '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>';
        } else {
            icon.innerHTML = '<circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>';
        }
    }
}
var AC = null;
function beep(f,d,v){
    f = f || 650; d = d || 0.04; v = v || 0.03;
    try {
        if (!AC) AC = new (window.AudioContext || window.webkitAudioContext)();
        var o = AC.createOscillator(), g = AC.createGain();
        o.frequency.value = f; o.type = 'sine'; g.gain.value = v;
        o.connect(g); g.connect(AC.destination);
        o.start(); g.gain.exponentialRampToValueAtTime(0.0001, AC.currentTime + d); o.stop(AC.currentTime + d);
    } catch(e) {}
}
document.addEventListener('DOMContentLoaded', function(){
    var cur = document.documentElement.getAttribute('data-theme');
    var icon = document.getElementById('themeIcon');
    if (icon && cur === 'dark') {
        icon.innerHTML = '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>';
    }
    document.querySelectorAll('button,.btn,a').forEach(function(el){
        el.addEventListener('click', function(){ beep(); });
    });
});

function openTimeModal(endTs, leftSec) {
    // إزالة أي مودال قديم
    var oldModal = document.getElementById('timeModal');
    if (oldModal) oldModal.remove();
    
    var days = 0, hours = 0, mins = 0, isExpired = false;
    if (endTs === 0 || leftSec <= 0) {
        isExpired = true;
    } else {
        days = Math.floor(leftSec / 86400);
        hours = Math.floor((leftSec % 86400) / 3600);
        mins = Math.floor((leftSec % 3600) / 60);
    }
    
    var timeDisplay = "";
    if (isExpired) {
        timeDisplay = '<div style="font-size:24px; font-weight:900; color:#ef4444; text-align:center;">انتهت الصلاحية</div><div style="font-size:13px; color:var(--muted); text-align:center; margin-top:8px;">لا يمكنك سحب الكود من هذا الرقم بعد الآن.</div>';
    } else {
        var parts = [];
        if (days > 0) parts.push('<div style="text-align:center;"><div style="font-size:28px; font-weight:900; color:var(--primary2);">' + days + '</div><div style="font-size:11px; color:var(--muted);">يوم</div></div>');
        if (hours > 0) parts.push('<div style="text-align:center;"><div style="font-size:28px; font-weight:900; color:var(--warn);">' + hours + '</div><div style="font-size:11px; color:var(--muted);">ساعة</div></div>');
        parts.push('<div style="text-align:center;"><div style="font-size:28px; font-weight:900; color:var(--success);">' + mins + '</div><div style="font-size:11px; color:var(--muted);">دقيقة</div></div>');
        
        timeDisplay = '<div style="display:flex; justify-content:center; gap:16px; margin-bottom:16px;">' + parts.join('') + '</div>' +
            '<div style="font-size:13px; color:var(--text); text-align:center; line-height:1.7; background:rgba(99,102,241,0.08); border:1px solid rgba(99,102,241,0.2); border-radius:12px; padding:12px;">' +
            'يمكنك سحب الكود من هذا الرقم خلال هذه الفترة.<br>بعد انتهاء الوقت، لن تتمكن من سحب الكود مرة أخرى لأسباب أمنية.' +
            '</div>';
    }
    
    var modalHtml = '<div id="timeModal" style="position:fixed; inset:0; background:rgba(0,0,0,0.75); backdrop-filter:blur(5px); z-index:99999; display:flex; align-items:center; justify-content:center; padding:20px; animation:fadeIn 0.3s ease;">' +
        '<div style="background:linear-gradient(145deg, var(--card), var(--card2)); border:1px solid var(--border); border-radius:24px; max-width:380px; width:100%; padding:24px; text-align:center; position:relative; box-shadow:0 20px 60px rgba(0,0,0,0.6);">' +
        '<button onclick="document.getElementById(&#39;timeModal&#39;).remove()" style="position:absolute; top:12px; left:12px; background:rgba(255,255,255,0.05); border:none; color:var(--muted); width:32px; height:32px; border-radius:50%; cursor:pointer; font-size:18px;">&times;</button>' +
        '<div style="width:80px; height:80px; margin:0 auto 16px; background:rgba(245,158,11,0.15); border-radius:50%; display:flex; align-items:center; justify-content:center; border:2px solid #f59e0b;">' +
        '<svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>' +
        '</div>' +
        '<h2 style="font-size:20px; font-weight:900; margin-bottom:16px; color:var(--text);">الوقت المتبقي لسحب الكود</h2>' +
        timeDisplay +
        '</div></div>';
    
    var div = document.createElement('div');
    div.innerHTML = modalHtml;
    document.body.appendChild(div.firstChild);
}

// COPY_FINAL_V2
// نسخ يعمل على HTTP وHTTPS وChrome Android وFirefox
function copyFeedback(btn) {
    if (!btn) return;
    if (btn.__copyOrig === undefined) { btn.__copyOrig = btn.innerHTML; }
    if (btn.__copyTimer) { clearTimeout(btn.__copyTimer); }
    btn.innerHTML = '<svg viewBox="0 0 24 24" style="width:14px;height:14px;stroke:#10b981;fill:none;stroke-width:3;vertical-align:middle"><path d="M20 6L9 17l-5-5"/></svg>';
    btn.style.color = '#10b981';
    btn.__copyTimer = setTimeout(function() {
        btn.innerHTML = btn.__copyOrig;
        btn.__copyOrig = undefined;
        btn.style.color = '';
        btn.__copyTimer = null;
    }, 1500);
}
function copyWithExec(txt) {
    var ta = document.createElement('textarea');
    ta.value = txt;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.top = '0';
    ta.style.left = '0';
    ta.style.width = '1px';
    ta.style.height = '1px';
    ta.style.opacity = '0';
    ta.style.fontSize = '16px';
    document.body.appendChild(ta);
    var ok = false;
    try {
        ta.focus();
        ta.removeAttribute('readonly');
        ta.select();
        ta.setSelectionRange(0, txt.length);
        ok = document.execCommand('copy');
    } catch (e) {
        ok = false;
    }
    document.body.removeChild(ta);
    return ok;
}
function copyText(txt, btn) {
    txt = (txt === undefined || txt === null) ? '' : String(txt);
    if (copyWithExec(txt)) { copyFeedback(btn); return; }
    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(txt).then(function() {
            copyFeedback(btn);
        }).catch(function() {
            prompt('انسخ النص يدوياً (Ctrl+C):', txt);
        });
        return;
    }
    prompt('انسخ النص يدوياً (Ctrl+C):', txt);
}

function autoFilter(sel) {
    var form = sel.closest('form');
    if (form) form.submit();
}
function fetchOTP(nid){
    var b = document.getElementById('otpBtn');
    var t = document.getElementById('otpBtnText');
    var r = document.getElementById('otpResult');
    var icon = document.getElementById('otpBtnIcon');
    if (!b) return;
    b.disabled = true;
    if (t) t.textContent = 'جاري السحب...';
    if (r) r.innerHTML = '';
    
    // تشغيل حركة الدوران
    if (icon) icon.classList.add('spinning');
    if (icon && icon.querySelector('svg')) {
        icon.querySelector('svg').classList.add('spinning');
    }
    
    fetch('/fetch-otp/' + nid, {method: 'POST'})
        .then(function(x){ return x.json(); })
        .then(function(d){
            b.disabled = false;
            if (t) t.textContent = 'سحب الكود الآن';
            
            // إيقاف حركة الدوران
            if (icon) icon.classList.remove('spinning');
            if (icon && icon.querySelector('svg')) {
                icon.querySelector('svg').classList.remove('spinning');
            }
            
            if (d.ok) {
                if (r) r.innerHTML = '<div style="color:var(--success);font-weight:700">الكود: <code style="font-size:18px">' + d.code + '</code></div>';
                setTimeout(function(){ location.reload(); }, 1500);
            } else {
                if (r) r.innerHTML = '<div style="color:var(--danger)">' + (d.error || 'فشل') + '</div>';
            }
        })
        .catch(function(e){
            b.disabled = false;
            if (t) t.textContent = 'سحب الكود الآن';
            if (icon) icon.classList.remove('spinning');
            if (icon && icon.querySelector('svg')) {
                icon.querySelector('svg').classList.remove('spinning');
            }
            if (r) r.innerHTML = '<div style="color:var(--danger)">خطأ</div>';
        });
}

// ============================================================
// مؤشر FPS (يعرض الإطارات في الثانية في أي مكان)
// ============================================================
(function() {
    // نتأكد إن المؤشر مش موجود
    if (document.getElementById('fpsMeter')) return;
    
    // نضيف الستايل
    var style = document.createElement('style');
    style.textContent = '' +
        '#fpsMeter { position: fixed; top: 10px; left: 50%; transform: translateX(-50%); z-index: 99998; font-family: monospace; font-size: 10px; font-weight: 900; padding: 3px 10px; border-radius: 10px; backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px); display: flex; align-items: center; gap: 3px; cursor: pointer; transition: all 0.3s; border: 1px solid; user-select: none; box-shadow: 0 2px 10px rgba(0,0,0,0.3); }' +
        '#fpsMeter.good { background: rgba(16,185,129,0.2); color: #10b981; border-color: rgba(16,185,129,0.5); }' +
        '#fpsMeter.medium { background: rgba(245,158,11,0.2); color: #f59e0b; border-color: rgba(245,158,11,0.5); }' +
        '#fpsMeter.bad { background: rgba(239,68,68,0.2); color: #ef4444; border-color: rgba(239,68,68,0.5); }' +
        '#fpsMeter.hidden { display: none; }';
    document.head.appendChild(style);
    
    // نضيف المؤشر
    var fpsEl = document.createElement('div');
    fpsEl.id = 'fpsMeter';
    fpsEl.className = 'good';
    fpsEl.title = 'اضغط لإخفاء المؤشر (اضغط مطولاً لإظهاره تاني)';
    fpsEl.innerHTML = '<span style="font-size:9px; opacity:0.7;">FPS</span> <span id="fpsValue">60</span>';
    document.body.appendChild(fpsEl);
    
    // دالة قياس FPS
    var frames = 0;
    var lastTime = performance.now();
    var fpsValue = document.getElementById('fpsValue');
    var fpsMeter = document.getElementById('fpsMeter');
    
    function updateFPS() {
        var now = performance.now();
        var delta = now - lastTime;
        frames++;
        
        if (delta >= 1000) {
            var fps = Math.round((frames * 1000) / delta);
            if (fpsValue) fpsValue.textContent = fps;
            
            // تغيير اللون حسب الأداء
            fpsMeter.classList.remove('good', 'medium', 'bad');
            if (fps >= 55) {
                fpsMeter.classList.add('good');
            } else if (fps >= 30) {
                fpsMeter.classList.add('medium');
            } else {
                fpsMeter.classList.add('bad');
            }
            
            frames = 0;
            lastTime = now;
        }
        
        requestAnimationFrame(updateFPS);
    }
    
    requestAnimationFrame(updateFPS);
    
    // إخفاء/إظهار المؤشر بالضغط
    var hideTimer = null;
    fpsMeter.addEventListener('click', function() {
        fpsMeter.classList.add('hidden');
        // نضيف زر صغير لإظهاره تاني (في نفس المكان)
        var restoreBtn = document.createElement('div');
        restoreBtn.id = 'fpsRestore';
        restoreBtn.style.cssText = 'position:fixed;top:140px;left:12px;z-index:99997;width:8px;height:8px;background:rgba(16,185,129,0.5);border-radius:50%;cursor:pointer;';
        restoreBtn.title = 'إظهار مؤشر FPS';
        restoreBtn.onclick = function() {
            fpsMeter.classList.remove('hidden');
            restoreBtn.remove();
        };
        document.body.appendChild(restoreBtn);
    });
})();

// ============================================================
// زر التحديث العائم (يظهر في كل الصفحات)
// ============================================================
(function() {
    // نتأكد إن الزر مش موجود
    if (document.getElementById('globalRefreshBtn')) return;
    
    // نضيف الستايل
    var style = document.createElement('style');
    style.textContent = '@keyframes spin-refresh-btn { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }' +
        '.refresh-float-btn-force { position: fixed; bottom: 140px; left: 20px; width: 46px; height: 46px; border-radius: 50%; background: rgba(99,102,241,0.15); backdrop-filter: blur(12px); border: 1.5px solid rgba(99,102,241,0.4); color: #6366f1; display: flex; align-items: center; justify-content: center; z-index: 9998; cursor: pointer; transition: all 0.2s; }' +
        '.refresh-float-btn-force:active { transform: scale(0.9); }' +
        '.refresh-float-btn-force svg { width: 22px; height: 22px; }' +
        '.refresh-float-btn-force.spinning svg { animation: spin-refresh-btn 0.8s linear infinite; }';
    document.head.appendChild(style);
    
    // نضيف الزر
    var btn = document.createElement('button');
    btn.id = 'globalRefreshBtn';
    btn.className = 'refresh-float-btn-force';
    btn.title = 'تحديث الصفحة';
    btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>';
    btn.onclick = function() {
        btn.classList.add('spinning');
        setTimeout(function() { window.location.reload(); }, 300);
    };
    document.body.appendChild(btn);
})();

// ============================================================
// تحديث مؤشر FPS (الموجود في النافبار)
// ============================================================
(function() {
    var fpsValue = document.getElementById('fpsValue');
    var fpsMeter = document.getElementById('fpsMeter');
    if (!fpsValue || !fpsMeter) return;
    
    var frames = 0;
    var lastTime = performance.now();
    
    function updateFPS() {
        var now = performance.now();
        var delta = now - lastTime;
        frames++;
        
        if (delta >= 1000) {
            var fps = Math.round((frames * 1000) / delta);
            fpsValue.textContent = fps;
            
            // تغيير اللون حسب الأداء
            if (fps >= 55) {
                fpsMeter.style.background = 'rgba(16,185,129,0.15)';
                fpsMeter.style.color = '#10b981';
                fpsMeter.style.borderColor = 'rgba(16,185,129,0.4)';
            } else if (fps >= 30) {
                fpsMeter.style.background = 'rgba(245,158,11,0.15)';
                fpsMeter.style.color = '#f59e0b';
                fpsMeter.style.borderColor = 'rgba(245,158,11,0.4)';
            } else {
                fpsMeter.style.background = 'rgba(239,68,68,0.15)';
                fpsMeter.style.color = '#ef4444';
                fpsMeter.style.borderColor = 'rgba(239,68,68,0.4)';
            }
            
            frames = 0;
            lastTime = now;
        }
        
        requestAnimationFrame(updateFPS);
    }
    
    requestAnimationFrame(updateFPS);
})();

"""


def _svg(name, size=20):
    icons = {
        "home": '<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>',
        "user": '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
        "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
        "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2"/>',
        "logout": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>',
    }
    return f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{icons.get(name,"")}</svg>'

def _nav(u):
    _logo_url = _site_icon_url("site_logo")
    if _logo_url:
        logo = '<img src="' + _logo_url + '" style="width:40px;height:40px;border-radius:50%;object-fit:cover;border:2px solid rgba(99,102,241,0.5);box-shadow:0 2px 8px rgba(99,102,241,0.3);flex-shrink:0">'
    else:
        logo = '<svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="url(#g1)" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><defs><linearGradient id="g1" x1="0" x2="1" y1="0" y2="1"><stop offset="0" stop-color="#6366f1"/><stop offset=".5" stop-color="#8b5cf6"/><stop offset="1" stop-color="#06b6d4"/></linearGradient></defs><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>'
    
    # زر الإدارة - يظهر فقط للأدمن
    admin_btn = ""
    if is_admin(u):
        admin_btn = (
            '<a href="/admin" id="adminBtn" title="لوحة الإدارة" '
            'style="background:rgba(16,185,129,0.15);border:1px solid rgba(16,185,129,0.5);'
            'color:#10b981;cursor:pointer;padding:8px;border-radius:50%;'
            'display:flex;align-items:center;justify-content:center;'
            'transition:all 0.3s;width:40px;height:40px;text-decoration:none">'
            '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
            'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
            '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>'
            '<polyline points="9 12 11 14 15 10"/>'
            '</svg></a>'
        )
    
    return (
        '<header class="nav" style="justify-content:space-between">'
        '<a class="brand" href="/" onclick="toggleAdminBtn(event)" style="display:flex;align-items:center;gap:10px;cursor:pointer">'
        + logo +
        '<span class="brand-text">MATARI STORE</span>'
        '<div id="fpsMeter" style="display: inline-flex; align-items: center; gap: 3px; font-family: monospace; font-size: 9px; font-weight: 900; padding: 2px 6px; border-radius: 6px; background: rgba(16,185,129,0.1); color: #10b981; border: 1px solid rgba(16,185,129,0.3); margin-right: 6px; user-select: none;"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg> <span id="fpsValue">60</span></div>'
        '</a>'
        '<div style="display:flex;align-items:center;gap:8px">'
        + _pb_navbar_html(u) + admin_btn +
        '<button onclick="toggleTheme()" id="themeToggle" style="background:rgba(99,102,241,0.15);border:1px solid rgba(99,102,241,0.4);color:var(--primary2);cursor:pointer;padding:8px;border-radius:50%;display:flex;align-items:center;justify-content:center;transition:all 0.3s;width:40px;height:40px">'
        '<svg id="themeIcon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>'
        '</button>'
        '</div>'
        '</header>'
    )


def _bottom_nav(u, active=""):
    def cls(x): return ' class="active"' if x == active else ''
    svg_style = 'width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"'
    
    # جلب عدد الأرقام الجديدة اللي المستخدم ما شافهاش
    unread_count = 0
    support_unread = 0
    if u:
        try:
            unread_count = db().execute("SELECT COUNT(*) as c FROM numbers WHERE buyer_id=? AND seen_by_buyer=0", (u["user_id"],)).fetchone()["c"]
        except Exception:
            unread_count = 0
        try:
            support_unread = db().execute("""
                SELECT COUNT(*) as c FROM ticket_messages tm
                JOIN tickets t ON t.id = tm.ticket_id
                WHERE t.user_id = ? AND tm.sender = 'admin' AND tm.is_read = 0
            """, (u["user_id"],)).fetchone()["c"]
        except Exception:
            support_unread = 0

    badge_html = ""
    if unread_count > 0:
        badge_html = f'<span style="position:absolute; top:4px; right:25%; background:#ef4444; color:#fff; font-size:10px; font-weight:900; min-width:16px; height:16px; border-radius:10px; display:flex; align-items:center; justify-content:center; padding:0 4px; box-shadow:0 0 10px rgba(239,68,68,0.6); animation:pulse 1.5s infinite;">{unread_count}</span>'
    
    support_badge = ""
    if support_unread > 0:
        support_badge = f'<span style="position:absolute; top:4px; right:25%; background:#ef4444; color:#fff; font-size:10px; font-weight:900; min-width:16px; height:16px; border-radius:10px; display:flex; align-items:center; justify-content:center; padding:0 4px; box-shadow:0 0 10px rgba(239,68,68,0.6); animation:pulse 1.5s infinite;">{support_unread}</span>'

    return f'''
    <nav class="bottom-nav">
      <a href="/"{cls("home")}>
        <svg {svg_style}><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>
        <span>الرئيسية</span>
      </a>
      <a href="/store"{cls("store")}>
        <svg {svg_style}><path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/><line x1="3" y1="6" x2="21" y2="6"/><path d="M16 10a4 4 0 0 1-8 0"/></svg>
        <span>المتجر</span>
      </a>
      <a href="/dashboard"{cls("dashboard")} style="position:relative; { 'color: #ef4444 !important;' if unread_count > 0 and active != 'dashboard' else '' }">
        <svg {svg_style} { 'style="filter: drop-shadow(0 0 6px rgba(239,68,68,0.8));"' if unread_count > 0 and active != 'dashboard' else '' }><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
        {badge_html}
        <span>حسابي</span>
      </a>
      <a href="/support"{cls("support")} style="position:relative;">
        <svg {svg_style}><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>
        {support_badge}
        <span>الدعم</span>
      </a>
    </nav>'''



 











def get_refresh_btn():
    """زر تحديث عائم شفاف"""
    return '''
    <style>
    @keyframes spin-refresh { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
    .refresh-float-btn {
        position: fixed; bottom: 140px; left: 20px;
        width: 46px; height: 46px; border-radius: 50%;
        background: rgba(99,102,241,0.15);
        backdrop-filter: blur(12px);
        border: 1.5px solid rgba(99,102,241,0.4);
        color: #6366f1;
        display: flex; align-items: center; justify-content: center;
        z-index: 9998; cursor: pointer;
        transition: all 0.2s;
    }
    .refresh-float-btn:active { transform: scale(0.9); }
    .refresh-float-btn:hover { background: rgba(99,102,241,0.25); }
    .refresh-float-btn svg { width: 22px; height: 22px; }
    .refresh-float-btn.spinning svg { animation: spin-refresh 0.8s linear infinite; }
    </style>
    <button class="refresh-float-btn" id="refreshBtn" onclick="manualRefresh()" title="تحديث الصفحة">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="23 4 23 10 17 10"/>
            <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
        </svg>
    </button>
    <script>
    function manualRefresh() {
        var btn = document.getElementById('refreshBtn');
        if (btn) btn.classList.add('spinning');
        setTimeout(function() { window.location.reload(); }, 300);
    }
    </script>
    '''


def _render_notif_text(text, btn_text="", btn_url=""):
    """يحول الأكواد إلى HTML ويعالج أزرار الدفع (بدون Regex)."""
    if not text:
        return ""
    t = str(text)
    t = t.replace("[b]", "<b>").replace("[/b]", "</b>")
    t = t.replace("[u]", "<u>").replace("[/u]", "</u>")
    t = t.replace("[big]", "<span style='font-size:20px;'>").replace("[/big]", "</span>")
    t = t.replace("[red]", "<span style='color:#ef4444;font-weight:700;'>").replace("[/red]", "</span>")
    t = t.replace("[green]", "<span style='color:#10b981;font-weight:700;'>").replace("[/green]", "</span>")
    t = t.replace("[gold]", "<span style='color:#fbbf24;font-weight:700;'>").replace("[/gold]", "</span>")
    t = t.replace("[blue]", "<span style='color:#818cf8;font-weight:700;'>").replace("[/blue]", "</span>")
    t = t.replace("[cyan]", "<span style='color:#06b6d4;font-weight:700;'>").replace("[/cyan]", "</span>")
    if btn_text and btn_url:
        t = t.replace('href="#"', 'href="' + btn_url + '"')
        t = t.replace('>تواصل معنا الآن<', '>' + btn_text + '<')
        t = t.replace('>اشحن الآن<', '>' + btn_text + '<')
        t = t.replace('>تصفح المتجر<', '>' + btn_text + '<')
        t = t.replace('>احصل على العرض الآن<', '>' + btn_text + '<')
    return t


def get_notif_btn():
    try:
        all_notifs = db().execute("SELECT * FROM announcements ORDER BY id DESC").fetchall()
        if not all_notifs:
            return ""
        cards_html = ""
        for n in all_notifs:
            if n["level"] == "success":
                c = "#10b981"
                icon_path = '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>'
            elif n["level"] == "error":
                c = "#ef4444"
                icon_path = '<circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>'
            else:
                c = "#6366f1"
                icon_path = '<path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/>'
            date_str = n["created_at"][:10] if n["created_at"] else ""
            text_color = n["text_color"] if "text_color" in n.keys() and n["text_color"] else "#e8e8f5"
            font_size = n["font_size"] if "font_size" in n.keys() and n["font_size"] else "14px"
            btn_t = n["btn_text"] if "btn_text" in n.keys() and n["btn_text"] else ""
            btn_u = n["btn_url"] if "btn_url" in n.keys() and n["btn_url"] else ""
            text_html = _render_notif_text(n["text"], btn_t, btn_u)
            cards_html += '<div style="background:linear-gradient(145deg, var(--card) 0%, var(--card2) 100%); border:1px solid var(--border); border-radius:16px; padding:16px; margin-bottom:12px; border-right:4px solid ' + c + ';">'
            cards_html += '<div style="display:flex; align-items:center; gap:10px; margin-bottom:8px;">'
            cards_html += '<div style="width:30px; height:30px; border-radius:50%; background:' + c + '22; color:' + c + '; display:flex; align-items:center; justify-content:center;">'
            cards_html += '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">' + icon_path + '</svg>'
            cards_html += '</div>'
            cards_html += '<div style="font-size:12px; font-weight:800; color:' + c + ';">إشعار الإدارة</div>'
            cards_html += '<div style="font-size:10px; color:var(--muted); margin-right:auto;">' + date_str + '</div>'
            cards_html += '</div>'
            cards_html += '<div style="font-size:' + font_size + '; color:' + text_color + '; line-height:1.8;">' + text_html + '</div>'
            cards_html += '</div>'
        latest_id = all_notifs[0]["id"]
        latest_id_str = str(latest_id)
        notifs_count = str(len(all_notifs))
        html = ""
        html += "<style>"
        html += "@keyframes notifPulse { 0%, 100% { transform: scale(1); box-shadow: 0 0 0 0 rgba(99,102,241,0.4); } 50% { transform: scale(1.05); box-shadow: 0 0 0 12px rgba(99,102,241,0); } }"
        html += "@keyframes slideDownSheet { from { transform: translateY(-100%); opacity: 0; } to { transform: translateY(0); opacity: 1; } }"
        html += ".notif-btn-float { position: fixed; bottom: 85px; left: 20px; width: 42px; height: 42px; border-radius: 50%; background: rgba(99,102,241,0.15); backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px); border: 1.5px solid rgba(99,102,241,0.4); color: #818cf8; display: flex; align-items: center; justify-content: center; z-index: 9998; cursor: pointer; box-shadow: 0 4px 12px rgba(0,0,0,0.3); }"
        html += ".notif-btn-float svg { width: 18px; height: 18px; }"
        html += ".notif-btn-float:active { transform: scale(0.92); }"
        html += ".notif-dot { position: absolute; top: -2px; right: -2px; width: 16px; height: 16px; background: #ef4444; border-radius: 50%; border: 3px solid var(--bg); display: none; }"
        html += ".notif-modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.7); backdrop-filter: blur(5px); z-index: 9999; display: none; align-items: flex-start; justify-content: center; }"
        html += ".notif-modal-overlay.active { display: flex; }"
        html += ".notif-sheet { background: linear-gradient(180deg, rgba(30,30,60,0.98), rgba(15,15,30,0.98)); border: 1px solid rgba(99,102,241,0.3); border-bottom-left-radius: 28px; border-bottom-right-radius: 28px; padding: 20px 16px 30px 16px; max-width: 500px; width: 100%; max-height: 85vh; display: flex; flex-direction: column; animation: slideDownSheet 0.4s cubic-bezier(0.4,0,0.2,1); box-shadow: 0 10px 40px rgba(0,0,0,0.5); }"
        html += ".notif-sheet-handle { width: 40px; height: 4px; background: rgba(255,255,255,0.2); border-radius: 2px; margin: 0 auto 16px auto; }"
        html += "</style>"
        html += '<div class="notif-btn-float" id="floatingNotifBtn" onclick="if(!window.draggedNotif) document.getElementById(\'notifOverlay\').classList.add(\'active\'); localStorage.setItem(\'seen_nid\', \'' + latest_id_str + '\'); document.getElementById(\'notifDot\').style.display=\'none\';">'
        html += '<div class="notif-dot" id="notifDot"></div>'
        html += '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>'
        html += '</div>'
        html += '<div class="notif-modal-overlay" id="notifOverlay" onclick="if(event.target===this) this.classList.remove(\'active\')">'
        html += '<div class="notif-sheet">'
        html += '<div class="notif-sheet-handle"></div>'
        html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">'
        html += '<h3 style="font-size:18px;font-weight:900;color:#fff;margin:0;display:flex;align-items:center;gap:8px;">'
        html += '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#818cf8" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>'
        html += 'الإشعارات (' + notifs_count + ')'
        html += '</h3>'
        html += '<button onclick="document.getElementById(\'notifOverlay\').classList.remove(\'active\')" style="background:rgba(255,255,255,0.1);border:none;color:#fff;width:32px;height:32px;border-radius:50%;cursor:pointer;font-size:16px;display:flex;align-items:center;justify-content:center;">×</button>'
        html += '</div>'
        html += '<div style="overflow-y:auto;flex:1;">' + cards_html + '</div>'
        html += '</div></div>'
        html += '<script>if(localStorage.getItem(\'seen_nid\') != \'' + latest_id_str + '\') { document.getElementById(\'notifDot\').style.display = \'block\'; }</script>'
        return html
    except Exception as e:
        print("[NOTIF] error: " + str(e))
        return ""
def inject_globals():
    return {}
@app.route("/daily-bonus", methods=["POST"])
@login_required
def daily_bonus():
    u = current_user()
    today = datetime.now().strftime("%Y-%m-%d")
    
    # التأكد إن المستخدم ما استلمش النهاردة
    last_bonus = u["last_bonus"] if "last_bonus" in u.keys() else None
    if last_bonus == today:
        flash("استلمت مكافأة اليوم بالفعل. عد غداً!", "error")
        return redirect(url_for("dashboard"))
    
    # التحقق من أن المكافأة اليومية مفعلة
    if get_setting("DAILY_BONUS_ENABLED", "1") != "1":
        flash("المكافأة اليومية متوقفة حالياً. حاول لاحقاً.", "error")
        return redirect(url_for("dashboard"))
    
    # قراءة قيمة المكافأة من الإعدادات
    try:
        amount = float(get_setting("DAILY_BONUS", "0.01"))
    except ValueError:
        amount = 0.01
    
    # تحديث الرصيد وتاريخ الاستلام
    try:
        cur = db().execute("UPDATE users SET balance=balance+?, last_bonus=? WHERE user_id=? AND (last_bonus IS NULL OR last_bonus != ?)",
                           (amount, today, u["user_id"], today))
        if cur.rowcount == 0:
            flash("حدث خطأ: يبدو أنك استلمت المكافأة بالفعل اليوم.", "error")
            return redirect(url_for("dashboard"))
        db().commit()
        flash(f"تمت إضافة ${amount:.3f} إلى رصيدك!", "success")
    except Exception as e:
        flash(f"حدث خطأ غير متوقع: {str(e)[:50]}", "error")
    
    return redirect(url_for("dashboard"))

# ---- VIP ----
@app.route("/vip")
@login_required
def vip_page():
    _ovr = _static_override("/vip")
    if _ovr is not None:
        return _ovr
    u = current_user()
    try: spent = u["total_spent"] or 0
    except: spent = 0
    pct, level = _get_vip_info(spent)
    tiers_raw = get_setting("VIP_TIERS", "5:3,20:5,50:10")
    tiers = []
    for part in tiers_raw.split(","):
        try:
            need, disc = part.strip().split(":")
            tiers.append((float(need), float(disc)))
        except: pass
    tiers.sort()

    tiers_html = ""
    for i, (need, disc) in enumerate(tiers, 1):
        achieved = spent >= need
        color = "var(--success)" if achieved else "var(--muted)"
        mark = ico("check", 14) if achieved else ico("clock", 14)
        tiers_html += f'''<div class="card" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;{'opacity:.5' if not achieved else ''}">
          <div><div style="font-weight:800;color:{color}">VIP{i}</div>
          <div style="font-size:13px;color:var(--muted)">عند ${need:.2f}</div></div>
          <div style="text-align:left"><div style="font-size:24px;font-weight:900;color:{color}">-{disc:g}%</div>
          <div style="font-size:11px;color:var(--muted)">{mark}</div></div></div>'''

    body = f'''
    <div class="container" style="max-width:700px">
      <div class="section-title">مستويات VIP</div>
      <div class="card" style="margin-bottom:20px;text-align:center">
        <div style="color:var(--muted);font-size:13px;margin-bottom:8px">مستواك</div>
        <div style="font-size:36px;font-weight:900;background:var(--gradient);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text">VIP{level}</div>
        <div style="font-size:14px;color:var(--muted);margin-top:8px">خصم {pct:g}% · إجمالي: ${spent:.2f}</div>
      </div>
      {tiers_html}
    </div>'''
    return page("vip", body=body)

# [تابع في الرسالة 3]


# ---- Transfer ----
@app.route("/transfer", methods=["GET", "POST"])
@login_required
def transfer():
    _ovr = _static_override("/transfer")
    if _ovr is not None:
        return _ovr
    u = current_user()
    if request.method == "POST":
        try:
            to_id = int(request.form.get("to_id", "0"))
            amt = float(request.form.get("amount", "0"))
        except ValueError:
            flash("بيانات غير صالحة.", "error"); return redirect(url_for("transfer"))
        
        # قراءة الرسوم من الداتابيز (دائماً)
        fee = get_fee()
        
        # التحقق من أن المبلغ أكبر من صفر
        if amt <= 0:
            flash("أدخل مبلغ صالح.", "error"); return redirect(url_for("transfer"))
        
        # التحقق من أن المبلغ أكبر من الرسوم
        if amt <= fee:
            flash(f"المبلغ (${amt:.2f}) يجب أن يكون أكبر من رسوم التحويل (${fee:.2f}).", "error")
            return redirect(url_for("transfer"))
        
        # التحقق من أن المستخدم لا يحول لنفسه
        if to_id == u["user_id"]:
            flash("لا يمكن التحويل لنفسك.", "error"); return redirect(url_for("transfer"))
        
        # البحث عن المستلم بـ custom_id
        target = db().execute("SELECT * FROM users WHERE custom_id=?", (str(to_id),)).fetchone()
        if not target:
            flash("المستخدم غير موجود. تأكد من الآيدي المخصص (8 أرقام).", "error")
            return redirect(url_for("transfer"))
        
        target_uid = target["user_id"]
        if target_uid == u["user_id"]:
            flash("لا يمكن التحويل لنفسك.", "error"); return redirect(url_for("transfer"))
        
        if target["is_banned"]:
            flash("المستخدم محظور.", "error"); return redirect(url_for("transfer"))
        
        # التحقق من الرصيد الكافي (المبلغ + الرسوم)
        total_needed = round(amt + fee, 4)
        if u["balance"] < total_needed:
            flash(f"رصيدك غير كافٍ. تحتاج ${total_needed:.2f} (المبلغ + الرسوم). رصيدك الحالي: ${u['balance']:.2f}", "error")
            return redirect(url_for("transfer"))
        
        net = round(amt - fee, 4)  # الصافي للمستلم
        
        con = db()
        try:
            con.execute("BEGIN")
            # خصم المبلغ + الرسوم من الراسل
            upd = con.execute(
                "UPDATE users SET balance=balance-? WHERE user_id=? AND balance>=?",
                (total_needed, u["user_id"], total_needed)).rowcount
            if upd != 1:
                con.execute("ROLLBACK"); flash("رصيدك غير كافٍ.", "error")
                return redirect(url_for("transfer"))
            
            # إضافة الصافي للمستلم
            con.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (net, target_uid))
            
            # تسجيل التحويل
            con.execute("INSERT INTO transfers(from_id,to_id,amount,fee) VALUES(?,?,?,?)",
                        (u["user_id"], target_uid, amt, fee))
            con.commit()
            make_safe_backup() # نسخ احتياطي عند التحويل
            audit("transfer_out", f"to={to_id} amt={amt} fee={fee}")
            flash(f"تم تحويل ${net:.2f} إلى {target['username']}. (تم خصم ${fee:.2f} رسوم)", "success")
            return redirect(url_for("dashboard"))
        except Exception as e:
            try: con.execute("ROLLBACK")
            except: pass
            flash(f"خطأ: {str(e)[:50]}", "error"); return redirect(url_for("transfer"))
    return page("transfer")

# ---- Reveal number (paid) ----
@app.route("/reveal/<int:nid>", methods=["POST"])
@login_required
def reveal_number(nid):
    u = current_user()
    n = db().execute("SELECT * FROM numbers WHERE id=?", (nid,)).fetchone()
    if not n or n["status"] != "available":
        flash("غير متاح.", "error"); return redirect(url_for("store"))
    cost = float(get_setting("REVEAL_COST", "0.10"))
    existing = session.get("revealed_" + str(nid))
    if existing:
        flash("الرقم مكشوف بالفعل.", "success"); return redirect(url_for("buy", nid=nid))
    con = db()
    try:
        con.execute("BEGIN")
        upd = con.execute(
            "UPDATE users SET balance=balance-? WHERE user_id=? AND balance>=?",
            (cost, u["user_id"], cost)).rowcount
        if upd != 1:
            con.execute("ROLLBACK"); flash(f"تحتاج ${cost:.2f} للكشف.", "error")
            return redirect(url_for("buy", nid=nid))
        con.commit()
        session["revealed_" + str(nid)] = True
        audit("reveal_number", f"nid={nid} cost={cost}")
        flash(f"تم خصم ${cost:.2f} وكشف الرقم.", "success")
    except Exception:
        try: con.execute("ROLLBACK")
        except: pass
        flash("خطأ.", "error")
    return redirect(url_for("buy", nid=nid))

# ---- Pre-order ----
@app.route("/preorder", methods=["POST"])
@login_required
def preorder():
    u = current_user()
    country = request.form.get("country", "").strip()
    if not country:
        flash("حدد دولة.", "error"); return redirect(url_for("store"))
    try:
        db().execute("INSERT OR IGNORE INTO preorders(user_id,country,created_at) VALUES(?,?,datetime('now'))",
                     (u["user_id"], country))
        db().commit()
        flash(f"سنخبرك عند توفر أرقام {country}.", "success")
    except: flash("خطأ.", "error")
    return redirect(url_for("store"))

# ---- Rating ----
@app.route("/rate/<int:nid>", methods=["POST"])
@login_required
def rate_number(nid):
    u = current_user()
    n = db().execute("SELECT * FROM numbers WHERE id=? AND buyer_id=?", (nid, u["user_id"])).fetchone()
    if not n: abort(404)
    try: stars = int(request.form.get("stars", "0"))
    except: stars = 0
    if not (1 <= stars <= 5):
        flash("تقييم غير صالح.", "error"); return redirect(url_for("my_number", nid=nid))
    try:
        db().execute("INSERT OR REPLACE INTO ratings(number_id,user_id,stars,created_at) VALUES(?,?,?,datetime('now'))",
                     (nid, u["user_id"], stars))
        db().commit()
        flash(f"شكراً لتقييمك {ico("star", 14) * stars}", "success")
    except: flash("خطأ.", "error")
    return redirect(url_for("my_number", nid=nid))

# ---- CSV Export ----
@app.route("/admin/export/users.csv")
@admin_required
def admin_export_users():
    import csv, io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["user_id","username","email","balance","total_spent","referred_by","captcha_passed","is_banned","created_at"])
    for r in db().execute("SELECT * FROM users ORDER BY user_id"):
        w.writerow([r["user_id"], r["username"], r["email"], r["balance"],
                    (r["total_spent"] or 0 if "total_spent" in r.keys() else 0), (r["referred_by"] or "" if "referred_by" in r.keys() else ""), (r["captcha_passed"] if "captcha_passed" in r.keys() else 0),
                    r["is_banned"], r["created_at"]])
    resp = Response(buf.getvalue(), mimetype="text/csv")
    resp.headers["Content-Disposition"] = 'attachment; filename="users.csv"'
    return resp

@app.route("/admin/export/numbers.csv")
@admin_required
def admin_export_numbers():
    import csv, io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id","platform","country","phone","price","status","buyer_id","sold_at"])
    for r in db().execute("SELECT * FROM numbers ORDER BY id"):
        w.writerow([r["id"], r["platform"], r["country"], r["phone"], r["price"],
                    r["status"], r["buyer_id"] or "", r["sold_at"] or ""])
    resp = Response(buf.getvalue(), mimetype="text/csv")
    resp.headers["Content-Disposition"] = 'attachment; filename="numbers.csv"'
    return resp

# ---- Audit Log UI ----
@app.route("/admin/audit")
@admin_required
def admin_audit():
    logs = db().execute(
        "SELECT a.*, u.username FROM audit_log a "
        "LEFT JOIN users u ON u.user_id=a.user_id "
        "ORDER BY a.id DESC LIMIT 500"
    ).fetchall()
    return page("admin_audit", logs=logs)

# ---- Announcement ----
@app.route("/admin/announcement", methods=["POST"])
@admin_required
def admin_announcement():
    text = request.form.get("text", "").strip()
    level = request.form.get("level", "info")
    if level not in ("info", "success", "error"): level = "info"
    set_setting("ANNOUNCEMENT", text)
    set_setting("ANNOUNCEMENT_LEVEL", level)
    flash("تم تحديث الإعلان.", "success")
    return redirect(url_for("admin_settings"))

# ============================================================
# ADMIN ROUTES
# ============================================================

@app.route("/admin/payments")
@admin_required
def admin_payments():
    from datetime import datetime, timedelta
    rows = db().execute("""
        SELECT pb.*, u.username, u.user_id as uid, n.phone, n.country, n.status as nstatus
        FROM pending_balance pb
        LEFT JOIN users u ON u.user_id = pb.user_id
        LEFT JOIN numbers n ON n.id = pb.number_id
        ORDER BY pb.created_at DESC
    """).fetchall()
    
    now = datetime.now()
    items = []
    for r in rows:
        try:
            created = datetime.strptime(r["created_at"], "%Y-%m-%d %H:%M:%S")
            elapsed = (now - created).total_seconds() / 3600
            remaining = max(0, 24 - elapsed)
        except Exception:
            remaining = 24
        items.append({
            "id": r["number_id"],
            "user_id": r["user_id"],
            "username": r["username"] or f"#{r['user_id']}",
            "phone": r["phone"] or "-",
            "country": r["country"] or "-",
            "amount": float(r["amount"] or 0),
            "created_at": r["created_at"],
            "remaining": remaining,
        })
    
    total = sum(i["amount"] for i in items)
    ready_count = sum(1 for i in items if i["remaining"] <= 0)
    
    return page("admin_payments", items=items, total=total, ready_count=ready_count)


@app.route("/admin/payments/pay/<int:nid>", methods=["POST"])
@admin_required
def admin_pay_seller(nid):
    row = db().execute("SELECT * FROM pending_balance WHERE number_id=?", (nid,)).fetchone()
    if not row:
        flash("لا يوجد سجل دفع لهذا الرقم.", "error")
        return redirect(url_for("admin_payments"))
    amount = float(row["amount"] or 0)
    if amount > 0:
        db().execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amount, row["user_id"]))
    db().execute("DELETE FROM pending_balance WHERE number_id=?", (nid,))
    db().commit()
    flash(f"تم الدفع ${amount:.2f} للمستخدم #{row['user_id']}.", "success")
    return redirect(url_for("admin_payments"))


@app.route("/admin/payments/pay_all", methods=["POST"])
@admin_required
def admin_pay_all_ready():
    from datetime import datetime, timedelta
    cutoff = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    rows = db().execute("SELECT * FROM pending_balance WHERE created_at <= ?", (cutoff,)).fetchall()
    paid = 0
    for r in rows:
        amount = float(r["amount"] or 0)
        if amount > 0:
            db().execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amount, r["user_id"]))
            paid += 1
        db().execute("DELETE FROM pending_balance WHERE number_id=?", (r["number_id"],))
    db().commit()
    flash(f"تم دفع {paid} مبلغ معلق (مرّ عليه 24 ساعة).", "success")
    return redirect(url_for("admin_payments"))



@app.route("/")
def index():
    nums = db().execute("SELECT * FROM numbers WHERE status='available' ORDER BY id DESC LIMIT 3").fetchall()
    return page("index", numbers=nums, active="home")




@app.route("/about")
def about_page():
    _ovr = _static_override("/about")
    if _ovr is not None:
        return _ovr
    items = [
        ("home", "الرئيسية", "الصفحة الرئيسية التي تعرض أحدث الأرقام المتاحة وأهم الميزات.", "#6366f1"),
        ("store", "المتجر", "تصفح جميع الأرقام المتاحة للبيع مقسمة حسب المنصة (واتساب/تيليجرام) والدولة.", "#818cf8"),
        ("cart", "الشراء", "اختر الرقم الذي تريده واضغط شراء ليتم خصم السعر من رصيدك فوراً.", "#10b981"),
        ("user", "حسابي", "لوحة التحكم الخاصة بك حيث ترى رصيدك وأرقامك المشتراة وإحصائياتك.", "#06b6d4"),
        ("wallet", "شحن الرصيد", "أضف رصيد لحسابك باستخدام فودافون كاش، جيب، ون كاش، بينانس، أو كود شحن.", "#f59e0b"),
        ("send", "تحويل رصيد", "أرسل رصيد لأي صديق باستخدام الآيدي الخاص به داخل الموقع.", "#8b5cf6"),
        ("star", "مستويات VIP", "كلما اشتريت أكثر، ترتفع رتبتك وتحصل على خصومات حصرية تلقائية.", "#f97316"),
        ("users", "الإحالات", "شارك رابطك مع أصدقائك واربح مكافأة مالية عند شراء أول رقم.", "#ec4899"),
        ("phone", "أرقامي", "جميع الأرقام التي اشتريتها موجودة هنا، مع إمكانية سحب الكود في أي وقت.", "#14b8a6"),
        ("key", "سحب الكود", "اضغط على الرقم لتدخل صفحته وتضغط زر سحب الكود ليظهر لك فوراً.", "#ef4444"),
        ("shield", "الحماية", "نضمن لك حماية أرقامك وعدم استرجاعها من قبل البائع الأصلي.", "#84cc16"),
        ("ticket", "الدعم الفني", "إذا واجهت أي مشكلة، افتح تذكرة جديدة وسيرد عليك فريق الدعم.", "#a855f7"),
        ("gift", "المكافأة اليومية", "احصل على مكافأة مجانية كل 24 ساعة بمجرد الضغط على زر الاستلام.", "#eab308"),
        ("message", "الإشعارات", "ستصلك إشعارات فورية عند وصول الكود أو عند إتمام أي عملية بنجاح.", "#3b82f6"),
        ("search", "البحث", "استخدم مربع البحث للعثور على رقم أو دولة معينة بسرعة.", "#6b7280"),
        ("lock", "الأمان", "جميع بياناتك مشفرة ومحمية بأعلى معايير الأمان في الموقع.", "#059669"),
    ]
    
    cards = ""
    for i, (icon_name, title, desc, color) in enumerate(items, 1):
        cards += f"""<div style="background: linear-gradient(145deg, var(--card), var(--card2)); border: 1px solid var(--border); border-radius: 16px; padding: 16px; margin-bottom: 12px; display: flex; align-items: flex-start; gap: 14px; border-right: 4px solid {color}; transition: all 0.3s;">
          <div style="width: 44px; height: 44px; border-radius: 12px; background: {color}15; display: flex; align-items: center; justify-content: center; flex-shrink: 0; border: 1px solid {color}30;">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{ICONS.get(icon_name, '<circle cx="12" cy="12" r="10"/>')}</svg>
          </div>
          <div style="flex: 1;">
            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px;">
              <span style="background: {color}20; color: {color}; font-size: 10px; font-weight: 900; padding: 2px 8px; border-radius: 20px;">{i:02d}</span>
              <div style="font-weight: 800; font-size: 15px; color: var(--text);">{title}</div>
            </div>
            <div style="font-size: 13px; color: var(--muted); line-height: 1.6;">{desc}</div>
          </div>
        </div>
        """
    
    body = f"""
    <div class="container" style="max-width: 700px; padding-top: 20px;">
      <div style="text-align: center; margin-bottom: 24px;">
        <div style="font-size: 24px; font-weight: 900; color: var(--text); margin-bottom: 6px;">دليل استخدام الموقع</div>
        <div style="font-size: 13px; color: var(--muted);">كل ما تحتاج معرفته عن أقسام MATARI STORE</div>
      </div>
    </div>
    {cards}
    """
    return page("about_page", body=body, active="")


@app.route("/logout")
def logout():
    session.clear()
    flash("تم تسجيل الخروج.", "success")
    return redirect(url_for("index"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        ident = request.form.get("ident","").strip(); pw = request.form.get("password","")
        u = get_user_by_ident(ident)
        if not u or not check_password_hash(u["password_hash"], pw):
            flash("بيانات الدخول خاطئة.", "error"); return redirect(url_for("login"))
        if is_banned(u):
            flash("حسابك محظور.", "error"); return redirect(url_for("login"))
        remember = request.form.get("remember") == "1"
        session.clear()
        session["user_id"] = u["user_id"]
        # الجلسة دايماً permanent (30 يوم) — بيحفظ الحساب
        session.permanent = True
        if remember:
            session["remember_me"] = True
        return redirect(request.args.get("next") or url_for("dashboard"))
    return page("login")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","")
        password2 = request.form.get("password2","")
        if not (username and password):
            flash("كل الحقول مطلوبة.", "error"); return redirect(url_for("register"))
        if len(password) < 6:
            flash("كلمة المرور 6 أحرف على الأقل.", "error"); return redirect(url_for("register"))
        if password != password2:
            flash("كلمتا المرور غير متطابقتين.", "error"); return redirect(url_for("register"))
        email = username.lower() + "@matari.local"
        
        # قراءة كود الإحالة من الرابط
        ref_code = request.args.get("ref", "").strip()
        referred_by = None
        if ref_code:
            referrer = db().execute("SELECT user_id FROM users WHERE username=?", (ref_code,)).fetchone()
            if referrer:
                referred_by = referrer["user_id"]
                print(f"[REFERRAL] New user {username} referred by {ref_code} (ID: {referred_by})")
            else:
                print(f"[REFERRAL] Referrer {ref_code} not found")
        
        uid, rk, custom_id = create_user(username, email, password, referred_by)
        if uid:
            make_safe_backup() # نسخ احتياطي عند تسجيل مستخدم
            make_safe_backup() # نسخ احتياطي عند تسجيل مستخدم
            # إضافة المكافأة لصاحب الإحالة (بمجرد التسجيل) - فقط لو النظام مفعل
            if referred_by and get_setting("REFERRAL_ENABLED", "1") == "1":
                try:
                    reward = float(get_setting("REFERRAL_REWARD", "0.001"))
                    db().execute("UPDATE users SET balance=balance+?, referral_earnings=referral_earnings+? WHERE user_id=?",
                                 (reward, reward, referred_by))
                    db().commit()
                    print(f"[REFERRAL] Credited {reward} to user ID {referred_by}")
                except Exception as e:
                    print(f"[REFERRAL] Credit error: {e}")
            
            # تسجيل دخول تلقائي بعد إنشاء الحساب
            session.clear()
            session["user_id"] = uid
            session.permanent = True
            flash(f"أهلاً بيك! آيديك: {custom_id}", "success")
            return redirect(url_for("dashboard"))
        else:
            flash("اسم المستخدم مستخدم.", "error"); return redirect(url_for("register"))
    return page("register")


@app.route("/buy/<int:nid>", methods=["GET", "POST"])
@login_required
def buy(nid):
    u = current_user()
    n = db().execute("SELECT * FROM numbers WHERE id=?", (nid,)).fetchone()
    if not n:
        flash("هذا الرقم غير موجود. جرب رقماً آخر.", "error")
        return redirect(url_for("store"))
    if n["status"] != "available":
        flash("هذا الرقم تم بيعه بالفعل. جرب رقماً آخر من المتجر.", "error")
        return redirect(url_for("store"))
    
    coupon_code = request.args.get("coupon", "").strip().upper()
    applied_coupon = None
    discount_pct = 0.0
    final_price = float(n["price"])
    
    if coupon_code:
        pct, err = _coupon_check(coupon_code, u["user_id"])
        if pct is not None:
            applied_coupon = coupon_code
            discount_pct = pct
            final_price = round(float(n["price"]) * (1 - pct/100), 2)
        else:
            flash(err or "كوبون غير صالح", "error")

    if request.method == "POST":
        if u["balance"] < final_price:
            flash(f"رصيدك غير كافٍ. تحتاج ${final_price:.2f}", "error"); return redirect(url_for("buy", nid=nid, coupon=coupon_code))
        con = db(); con.execute("BEGIN")
        cur = con.execute("SELECT status,price FROM numbers WHERE id=?", (nid,)).fetchone()
        if cur["status"] != "available":
            con.execute("ROLLBACK"); flash("تم بيعه مسبقاً.", "error"); return redirect(url_for("store"))
        
        # تحديث الرصيد بالسعر المخصوم
        upd = con.execute("UPDATE users SET balance=balance-? WHERE user_id=? AND balance>=?",
                          (final_price, u["user_id"], final_price)).rowcount
        if upd != 1:
            con.execute("ROLLBACK"); flash("رصيدك غير كافٍ.", "error"); return redirect(url_for("buy", nid=nid, coupon=coupon_code))
            
        con.execute("UPDATE numbers SET status='sold',buyer_id=?,sold_at=datetime('now'),seen_by_buyer=0, paid_price=? WHERE id=?",
                    (u["user_id"], final_price, nid))
        
        # خصم الكوبون من الجدول (تسجيل الاستخدام)
        if applied_coupon:
            _consume_coupon(applied_coupon, u["user_id"])
            
        con.commit()
        make_safe_backup() # نسخ احتياطي عند الشراء
        
        # إضافة مكافأة الإحالة لصاحب الرابط (بعد أول شراء فقط)
        if get_setting("REFERRAL_ENABLED", "1") == "1":
            try:
                _credit_referral(u["user_id"])
            except Exception as e:
                print(f"[REFERRAL] Credit error after purchase: {e}")
        
        flash(f"تم الشراء بنجاح! جاري البحث عن الكود تلقائياً... (تم خصم ${n['price'] - final_price:.2f} بكوبون)", "success")
        
        # تشغيل البحث التلقائي عن الكود في الخلفية
        threading.Thread(
            target=auto_fetch_otp,
            args=(u["user_id"], nid, 300, 5),
            daemon=True
        ).start()
        
        return redirect(url_for("dashboard"))
    return page("buy", number=n, final_price=final_price, coupon_code=coupon_code, discount_pct=discount_pct)


@app.route("/my/numbers")
@login_required
def my_numbers_list():
    u = current_user()
    nums = db().execute("SELECT * FROM numbers WHERE buyer_id=? ORDER BY sold_at DESC", (u["user_id"],)).fetchall()
    # تصفير الإشعارات هنا (لما المستخدم يفتح صفحة أرقامي)
    db().execute("UPDATE numbers SET seen_by_buyer=1 WHERE buyer_id=? AND seen_by_buyer=0", (u["user_id"],))
    db().commit()
    return page("my_numbers", my_numbers=nums)


@app.route("/deposit", methods=["GET", "POST"])
@app.route("/deposit/<method>", methods=["GET", "POST"])
@login_required
def deposit(method=None):
    if method is None:
        _ovr = _static_override("/deposit")
        if _ovr is not None:
            return _ovr
    u = current_user()
    if request.method == "POST":
        method_form = request.form.get("method", "").strip()
        if method_form == "voucher":
            code = request.form.get("code", "").strip().upper()
            if not code:
                flash("أدخل كود الشحن.", "error"); return redirect(url_for("deposit"))
            v = db().execute("SELECT * FROM vouchers WHERE code=? AND is_used=0", (code,)).fetchone()
            if not v:
                flash("الكود غير صالح.", "error"); return redirect(url_for("deposit", method="voucher"))
            con = db()
            con.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (v["amount"], u["user_id"]))
            con.execute("UPDATE vouchers SET is_used=1, used_by=? WHERE id=?", (u["user_id"], v["id"]))
            con.commit()
            flash(f"تم شحن ${v['amount']:.2f}.", "success")
            return redirect(url_for("dashboard"))
        elif method_form in ("jeeb", "onecash", "binance"):
            try: amt = float(request.form.get("amount", "0"))
            except ValueError: amt = 0
            if amt < 0.1:
                flash("الحد الأدنى $0.10.", "error"); return redirect(url_for("deposit", method=method_form))
            db().execute("INSERT INTO deposits(user_id,method,amount_usd,status) VALUES(?,?,?,'pending')",
                         (u["user_id"], method_form, amt))
            db().commit()
            flash("تم إرسال الطلب.", "success")
            return redirect(url_for("dashboard"))
    return page("deposit", method=method)


@app.route("/referral")
@login_required
def referral():
    _ovr = _static_override("/referral")
    if _ovr is not None:
        return _ovr
    u = current_user()
    cnt = db().execute("SELECT COUNT(*) c FROM users WHERE referred_by=?", (u["user_id"],)).fetchone()["c"]
    return page("referral", referral_count=cnt)

@app.route("/my/delete/<int:nid>", methods=["POST"])
@login_required
def my_delete_number(nid):
    u = current_user()
    db().execute("DELETE FROM numbers WHERE id=? AND buyer_id=?", (nid, u["user_id"]))
    db().commit()
    flash("تم حذف الرقم من قائمتك.", "success")
    return redirect(url_for("my_numbers_list"))



# ============================================================
# مراقبة الأكواد
# ============================================================
def log_code(user_id, number_id, phone, code, platform):
    try:
        db().execute("INSERT INTO code_logs(user_id, number_id, phone, code, platform, created_at) VALUES(?,?,?,?,?,datetime('now'))",
            (user_id, number_id, phone, code, platform))
        db().commit()
    except Exception as e:
        print("[CODE-LOG] error: " + str(e))


@app.route("/admin/code-monitor")
@admin_required
def admin_code_monitor():
    try:
        db().execute("""CREATE TABLE IF NOT EXISTS code_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            number_id INTEGER,
            phone TEXT,
            code TEXT,
            platform TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )""")
        db().commit()
    except Exception as e:
        print("[code-monitor] error: " + str(e))
    
    logs = db().execute("""SELECT cl.*, u.username
        FROM code_logs cl
        LEFT JOIN users u ON u.user_id = cl.user_id
        ORDER BY cl.id DESC LIMIT 200""").fetchall()
    
    total_today = db().execute("SELECT COUNT(*) c FROM code_logs WHERE date(created_at) = date('now')").fetchone()["c"]
    total_all = db().execute("SELECT COUNT(*) c FROM code_logs").fetchone()["c"]
    
    cards_html = ""
    for lg in logs:
        platform_lower = str(lg["platform"] or "").lower()
        if "telegram" in platform_lower:
            plt_icon = site_icon("telegram", 16, ico("telegram", 16))
            plt_color = "#06b6d4"
            plt_label = "تيليجرام"
        else:
            plt_icon = site_icon("whatsapp", 16, ico("whatsapp", 16))
            plt_color = "#25d366"
            plt_label = "واتساب"
        
        try:
            ts = lg["created_at"] or ""
            time_only = ts[11:16] if len(ts) > 16 else ""
            date_only = ts[:10] if len(ts) >= 10 else ""
        except:
            time_only = ""
            date_only = ""
        
        username = esc(lg["username"] or ("مستخدم #" + str(lg["user_id"] or "?")))
        phone = esc(lg["phone"] or "-")
        code_val = esc(lg["code"] or "-")
        
        cards_html += (
            '<div style="background:linear-gradient(145deg,var(--card),var(--card2));border:1px solid var(--border);border-right:4px solid ' + plt_color + ';border-radius:14px;padding:14px;margin-bottom:10px;">'
            '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">'
            '<div style="display:inline-flex;align-items:center;gap:6px;padding:3px 10px;font-size:10px;font-weight:800;background:' + plt_color + '15;color:' + plt_color + ';border-radius:20px;border:1px solid ' + plt_color + '30;">'
            + plt_icon + ' ' + plt_label + '</div>'
            '<div style="font-size:11px;color:var(--muted);">' + date_only + ' · ' + time_only + '</div>'
            '</div>'
            '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">'
            '<div style="flex:1;">'
            '<div style="font-size:13px;color:var(--text);font-weight:800;margin-bottom:2px;">' + username + '</div>'
            '<div style="font-size:11px;color:var(--muted);font-family:monospace;direction:ltr;text-align:left;">' + phone + '</div>'
            '</div>'
            '<div style="text-align:left;">'
            '<div style="font-size:10px;color:var(--muted);margin-bottom:2px;">الكود</div>'
            '<div style="font-family:monospace;font-size:18px;font-weight:900;color:var(--success);letter-spacing:2px;direction:ltr;">' + code_val + '</div>'
            '</div></div>'
            '<button onclick="copyText(\'' + code_val + '\', this)" class="btn btn-sm" style="width:100%;padding:8px;font-size:12px;background:rgba(16,185,129,0.15);border:1px solid rgba(16,185,129,0.3);color:var(--success);font-weight:700;display:flex;align-items:center;justify-content:center;gap:6px;">'
            + ico("copy", 14) + ' نسخ الكود</button>'
            '</div>'
        )
    
    if not cards_html:
        cards_html = '<div class="empty" style="padding:40px;text-align:center;color:var(--muted);">لا توجد أكواد مستلمة بعد</div>'
    
    body = (
        '<div class="container" style="max-width:700px;">'
        '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;">'
        '<div class="section-title" style="margin:0;">مراقبة الأكواد</div>'
        '<a href="/admin" class="btn btn-ghost btn-sm">' + ico("arrow-left", 14) + ' رجوع</a>'
        '</div>'
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:20px;">'
        '<div class="card" style="text-align:center;padding:16px;">'
        '<div style="font-size:13px;color:var(--muted);margin-bottom:4px;">اليوم</div>'
        '<div style="font-size:28px;font-weight:900;color:var(--primary2);">' + str(total_today) + '</div>'
        '</div>'
        '<div class="card" style="text-align:center;padding:16px;">'
        '<div style="font-size:13px;color:var(--muted);margin-bottom:4px;">الإجمالي</div>'
        '<div style="font-size:28px;font-weight:900;color:var(--success);">' + str(total_all) + '</div>'
        '</div></div>'
        + cards_html +
        '</div>'
    )
    return page("admin_code_monitor", body=body)


@app.route("/admin/code-monitor/clear", methods=["POST"])
@admin_required
def admin_code_monitor_clear():
    try:
        db().execute("DELETE FROM code_logs")
        db().commit()
        flash("تم مسح كل السجلات.", "success")
    except Exception as e:
        flash("خطأ: " + str(e), "error")
    return redirect(url_for("admin_code_monitor"))


@app.route("/dashboard")
@login_required
def dashboard():
    u = current_user()
    nums = db().execute("SELECT * FROM numbers WHERE buyer_id=? ORDER BY sold_at DESC", (u["user_id"],)).fetchall()
    deps = db().execute("SELECT * FROM deposits WHERE user_id=? ORDER BY id DESC LIMIT 10", (u["user_id"],)).fetchall()
    return page("dashboard", my_numbers=nums, my_deposits=deps, active="dashboard")

@app.route("/support", methods=["GET", "POST"])
@login_required
def support():
    _ovr = _static_override("/support")
    if _ovr is not None:
        return _ovr
    u = current_user()
    # نبحث عن تذكرة مفتوحة للمستخدم، أو نعمل واحدة
    t = db().execute("SELECT * FROM tickets WHERE user_id=? AND status='open' ORDER BY id DESC LIMIT 1", (u["user_id"],)).fetchone()
    if not t:
        cur = db().execute("INSERT INTO tickets(user_id,subject,message,status) VALUES(?,?,?,'open')",
                           (u["user_id"], "محادثة دعم", ""))
        db().commit()
        tid = cur.lastrowid
        t = db().execute("SELECT * FROM tickets WHERE id=?", (tid,)).fetchone()
    else:
        tid = t["id"]
    
    # لو الرسالة الأصلية لسه مش في ticket_messages، نضيفها
    cnt = db().execute("SELECT COUNT(*) c FROM ticket_messages WHERE ticket_id=?", (tid,)).fetchone()["c"]
    if cnt == 0 and t["message"]:
        db().execute("INSERT INTO ticket_messages(ticket_id, sender, text, created_at) VALUES(?,?,?,?)",
                     (tid, "user", t["message"], t["created_at"]))
        db().commit()
    
    # إرسال رسالة
    if request.method == "POST":
        text = request.form.get("text", "").strip()
        if text:
            db().execute("INSERT INTO ticket_messages(ticket_id, sender, text) VALUES(?,?,?)",
                         (tid, "user", text))
            db().commit()
        return redirect(url_for("support"))
    
    # نعلّم رسائل الإدارة كمقروءة (لأن المستخدم فتح الشات)
    db().execute("UPDATE ticket_messages SET is_read=1 WHERE ticket_id=? AND sender='admin' AND is_read=0", (tid,))
    db().commit()
    
    # جلب الرسائل
    msgs = db().execute("SELECT * FROM ticket_messages WHERE ticket_id=? ORDER BY id ASC", (tid,)).fetchall()
    
    msgs_html = ""
    for m in msgs:
        is_user = m["sender"] == "user"
        align = "flex-end" if is_user else "flex-start"
        bg = "linear-gradient(135deg, #6366f1, #8b5cf6)" if is_user else "var(--card2)"
        txt_color = "#fff" if is_user else "var(--text)"
        radius = "18px 18px 4px 18px" if is_user else "18px 18px 18px 4px"
        label = "أنت" if is_user else "الدعم"
        ta = "left" if is_user else "right"
        
        # علامة الصح
        read_mark = ""
        if is_user:
            is_read = m["is_read"] if "is_read" in m.keys() else 0
            if is_read:
                # علامتين صح زرقاء
                read_mark = '<span style="display:inline-flex; margin-right:6px; color:#60a5fa;" title="تم القراءة"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="18 6 7 17 2 12"/><polyline points="22 6 11 17 8 14"/></svg></span>'
            else:
                # علامة صح واحدة رمادية
                read_mark = '<span style="display:inline-flex; margin-right:6px; color:rgba(255,255,255,0.6);" title="تم الإرسال"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg></span>'
        
        avatar_small = '<div style="width:22px; height:22px; border-radius:50%; overflow:hidden; flex-shrink:0; display:flex; align-items:center; justify-content:center; mix-blend-mode: screen;">' + site_icon("site_logo", 22, '') + '</div>'
        msgs_html += (
            '<div style="display:flex; justify-content:' + align + '; margin-bottom:12px; padding:0 8px;">'
            '<div style="max-width:80%;">'
            '<div style="display:flex; justify-content:' + ('flex-start' if not is_user else 'flex-end') + '; align-items:center; gap:6px; margin-bottom:4px;">'
            + (avatar_small if not is_user else '') +
            '<div style="font-size:10px; color:var(--muted); text-align:' + ta + ';">' + label + ' · ' + m["created_at"][11:16] + '</div>'
            '</div>'
            '<div style="background:' + bg + '; color:' + txt_color + '; padding:12px 16px; border-radius:' + radius + '; font-size:14px; line-height:1.5; box-shadow:0 2px 8px rgba(0,0,0,0.2); word-wrap:break-word; display:flex; align-items:center; justify-content:space-between; gap:8px;">'
            '<span>' + esc(m["text"]) + '</span>' + read_mark +
            '</div>'
            '</div></div>'
        )
    
    if not msgs_html:
        msgs_html = '<div style="text-align:center;padding:40px;color:var(--muted);">لا توجد رسائل بعد. ابدأ المحادثة.</div>'
    
    body = '<div class="container" style="max-width:600px; padding-bottom:20px;">'
    body += '<div style="display:flex; align-items:center; gap:12px; padding:14px 16px; background:var(--card); border:1px solid var(--border); border-radius:16px; margin-bottom:16px;">'
    body += '<div style="width:48px; height:48px; border-radius:50%; overflow:hidden; flex-shrink:0; display:flex; align-items:center; justify-content:center; mix-blend-mode: screen;">' + site_icon("site_logo", 48, '') + '</div>'
    body += '<div style="flex:1;"><div style="font-weight:900; font-size:15px;">الدعم الفني</div>'
    body += '<div style="font-size:11px; color:#10b981; display:flex; align-items:center; gap:4px;">'
    body += '<span style="width:6px; height:6px; background:#10b981; border-radius:50%; display:inline-block; animation:pulse 1.5s infinite;"></span>'
    body += ' متصل الآن</div></div>'
    body += '</div>'
    body += '<div style="background:var(--bg2); border-radius:16px; padding:16px 0; margin-bottom:16px; min-height:350px; max-height:500px; overflow-y:auto;">' + msgs_html + '</div>'
    body += '<form method="POST" style="display:flex; gap:8px;">'
    body += '<input name="text" placeholder="اكتب رسالتك..." required style="flex:1; padding:14px 18px; background:var(--card); color:var(--text); border:1px solid var(--border); border-radius:24px; font-family:inherit; font-size:14px; outline:none;">'
    body += '<button type="submit" class="btn" style="padding:0 20px; border-radius:24px;">' + ico("send", 16) + '</button>'
    body += '</form>'
    body += '</div>'
    body += '<script>var cb = document.querySelector(\'[style*="max-height:500px"]\'); if (cb) cb.scrollTop = cb.scrollHeight;</script>'
    
    return page("support_chat", body=body, active="support")



@app.route("/support/ticket/<int:tid>")
@login_required
def support_ticket_redirect(tid):
    u = current_user()
    t = db().execute("SELECT id FROM tickets WHERE id=? AND user_id=?", (tid, u["user_id"])).fetchone()
    if not t:
        flash("التذكرة غير موجودة.", "error")
    return redirect(url_for("support"))

@app.route("/support/history")
@login_required
def support_history():
    u = current_user()
    ts = db().execute("SELECT * FROM tickets WHERE user_id=? ORDER BY id DESC", (u["user_id"],)).fetchall()
    
    tickets_html = ""
    for t in ts:
        st_badge = "approved" if t["status"] == "closed" else "pending"
        st_text = "مغلقة" if t["status"] == "closed" else "مفتوحة"
        try:
            last_msg = db().execute("SELECT text FROM ticket_messages WHERE ticket_id=? ORDER BY id DESC LIMIT 1", (t["id"],)).fetchone()
            preview = (last_msg["text"][:60] + "...") if (last_msg and len(last_msg["text"]) > 60) else (last_msg["text"] if last_msg else (t["message"] or ""))
        except Exception:
            preview = t["message"] or ""
        tickets_html += (
            '<a href="/support/ticket/' + str(t["id"]) + '" style="display:flex; align-items:center; gap:12px; padding:16px; background:var(--card); border:1px solid var(--border); border-radius:14px; margin-bottom:10px; text-decoration:none; color:inherit;">'
            '<div style="width:44px; height:44px; border-radius:12px; background:linear-gradient(135deg, rgba(99,102,241,0.2), rgba(6,182,212,0.2)); display:flex; align-items:center; justify-content:center; flex-shrink:0;">' + ico("message", 22) + '</div>'
            '<div style="flex:1; min-width:0;"><div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px; gap:8px;">'
            '<div style="font-weight:800; font-size:14px;">#' + str(t["id"]) + ' · ' + esc(t["subject"]) + '</div>'
            '<span class="badge ' + st_badge + '" style="font-size:10px; flex-shrink:0;">' + st_text + '</span></div>'
            '<div style="font-size:12px; color:var(--muted); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">' + esc(preview) + '</div>'
            '</div></a>'
        )
    if not tickets_html:
        tickets_html = '<div class="empty" style="text-align:center;padding:40px;color:var(--muted);">لا تذاكر بعد</div>'
    
    body = '<div class="container" style="max-width:600px;">'
    body += '<div style="display:flex; align-items:center; gap:10px; margin-bottom:20px;">'
    body += '<a href="/support" class="btn btn-ghost btn-sm">' + ico("arrow-left", 14) + ' رجوع للشات</a>'
    body += '</div>'
    body += '<div class="section-title">سجل التذاكر</div>'
    body += tickets_html
    body += '</div>'
    return page("support_history", body=body, active="support")


@app.route("/store")
def store():
    _ovr = _static_override("/store")
    if _ovr is not None:
        return _ovr
    platform = request.args.get("platform", "").strip()
    # توحيد اسم تيليجرام (يدعم telegram أو Telegram (Session))
    if platform.lower() == "telegram":
        platform = "Telegram (Session)"
    country  = request.args.get("country", "").strip()
    q        = request.args.get("q", "").strip()
    sort     = request.args.get("sort", "new")
    try: pn = max(1, int(request.args.get("p", "1") or 1))
    except ValueError: pn = 1
    per = 12
    # إصلاح: البحث بغض النظر عن حالة الأحرف (Case-Insensitive) للمنصة
    p_filter = platform.lower() if platform else None
    nums = list_available_numbers(p_filter, country or None, q or None, sort, per, (pn-1)*per)
    total = count_available_numbers(p_filter, country or None, q or None)
    total_pages = max(1, (total + per - 1) // per)
    platforms = [r["platform"] for r in db().execute("SELECT DISTINCT platform FROM numbers WHERE status='available'")]
    countries = [r["country"] for r in db().execute("SELECT DISTINCT country FROM numbers WHERE status='available'")]
    return page("store", active="store", numbers=nums, platforms=platforms, countries=countries,
                cur_platform=platform, cur_country=country, cur_q=q, cur_sort=sort,
                page_n=pn, total_pages=total_pages, total=total)


@app.route("/deposit/binance_verify", methods=["POST"])
@login_required
def deposit_binance_verify():
    u = current_user()
    try:
        amt = float(request.form.get("amount", "0"))
        order_id = request.form.get("order_id", "").strip()
    except:
        flash("بيانات غير صالحة", "error"); return redirect(url_for("deposit", method="binance"))
    
    if amt < 0.1:
        flash("الحد الأدنى $0.10", "error"); return redirect(url_for("deposit", method="binance"))
    if not order_id:
        flash("رقم العملية (Order ID) مطلوب.", "error"); return redirect(url_for("deposit", method="binance"))
    
    # التحقق التلقائي
    ok, msg = binance_auto_verify(order_id, amt)
    
    if ok:
        # إضافة الرصيد تلقائياً
        db().execute("INSERT INTO deposits(user_id,method,amount_usd,status,trans_id) VALUES(?,?,?,'approved',?)",
                     (u["user_id"], "binance", amt, order_id))
        db().execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amt, u["user_id"]))
        db().commit()
        flash("تم تأكيد الدفع وإضافة الرصيد تلقائياً!", "success")
        return redirect(url_for("dashboard"))
    else:
        # إذا فشل التحقق، نرسل طلب للإدارة للمراجعة
        db().execute("INSERT INTO deposits(user_id,method,amount_usd,status,trans_id) VALUES(?,?,?,'pending',?)",
                     (u["user_id"], "binance", amt, order_id))
        db().commit()
        flash("لم يتم التحقق التلقائي: " + msg + " - تم إرسال طلبك للإدارة.", "error")
        return redirect(url_for("dashboard"))


import shutil, zipfile
from datetime import datetime as _dt

_BACKUP_PROGRESS_BLOCK = r'''<div id="bkOverlay" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.55);z-index:9999;align-items:center;justify-content:center;padding:20px;">
  <div style="width:100%;max-width:360px;background:var(--card);border:1px solid var(--border);border-radius:16px;padding:20px;box-shadow:0 10px 40px rgba(0,0,0,0.5);">
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;">
      <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="#818cf8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
      <div style="font-weight:800;color:var(--text);font-size:15px;">جاري تحميل النسخة الاحتياطية</div>
    </div>
    <div style="height:10px;background:var(--bg2);border-radius:999px;overflow:hidden;border:1px solid var(--border);">
      <div id="bkBar" style="height:100%;width:0%;background:linear-gradient(90deg,#6366f1,#06b6d4);border-radius:999px;transition:width 0.2s ease;"></div>
    </div>
    <div style="display:flex;justify-content:space-between;margin-top:10px;font-size:12px;color:var(--muted);direction:ltr;">
      <span id="bkPct">0%</span><span id="bkSize">0.00 MB</span>
    </div>
  </div>
</div>
<script>
(function() {
  function mb(bytes) { return (bytes / 1048576).toFixed(2) + ' MB'; }
  function showBk(show) {
    var o = document.getElementById('bkOverlay');
    if (o) o.style.display = show ? 'flex' : 'none';
  }
  function setBk(loaded, total) {
    var bar = document.getElementById('bkBar');
    var pct = document.getElementById('bkPct');
    var sz = document.getElementById('bkSize');
    if (!bar) return;
    if (total > 0) {
      var p = Math.min(100, Math.round(loaded * 100 / total));
      bar.style.width = p + '%';
      pct.textContent = p + '%';
      sz.textContent = mb(loaded) + ' / ' + mb(total);
    } else {
      bar.style.width = '100%';
      pct.textContent = '';
      sz.textContent = mb(loaded);
    }
  }
  function downloadBackup(url) {
    showBk(true);
    setBk(0, 0);
    fetch(url, { credentials: 'same-origin' }).then(function(r) {
      if (!r.ok || !r.body) { throw new Error('HTTP ' + r.status); }
      var total = parseInt(r.headers.get('Content-Length') || '0', 10);
      var reader = r.body.getReader();
      var chunks = [];
      var loaded = 0;
      function pump() {
        return reader.read().then(function(res) {
          if (res.done) return;
          chunks.push(res.value);
          loaded += res.value.length;
          setBk(loaded, total);
          return pump();
        });
      }
      return pump().then(function() {
        return new Blob(chunks, { type: 'application/zip' });
      });
    }).then(function(blob) {
      var a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'matari_backup.zip';
      document.body.appendChild(a);
      a.click();
      setTimeout(function() { URL.revokeObjectURL(a.href); a.remove(); }, 3000);
      setBk(1, 1);
      setTimeout(function() { showBk(false); }, 600);
    }).catch(function(e) {
      showBk(false);
      console.log('فشل تحميل النسخة الاحتياطية', e);
      prompt('تعذر التحميل المباشر. افتح الرابط في المتصفح:', location.origin + url);
    });
  }
  document.querySelectorAll('a[href="/admin/backup/download"]').forEach(function(a) {
    a.addEventListener('click', function(ev) {
      ev.preventDefault();
      downloadBackup(a.getAttribute('href'));
    });
  });
})();
</script>'''

@app.route("/admin/backup/download")
@admin_required
def admin_backup_download():
    try:
        import os, zipfile
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"backup_matari_{ts}.zip"
        
        with zipfile.ZipFile(backup_filename, "w", zipfile.ZIP_DEFLATED) as zf:
            # إضافة قاعدة البيانات
            if os.path.exists(DB_PATH):
                zf.write(DB_PATH, "matari.db")
            # إضافة ملف web.py
            if os.path.exists(os.path.join(BASE_DIR, "web.py")):
                zf.write(os.path.join(BASE_DIR, "web.py"), "web.py")
            # إضافة مجلد static لو موجود
            static_dir = os.path.join(BASE_DIR, "static")
            if os.path.exists(static_dir):
                for root, dirs, files in os.walk(static_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        zf.write(file_path, os.path.relpath(file_path, BASE_DIR))
        
        from flask import send_file
        return send_file(backup_filename, as_attachment=True, download_name=backup_filename)
    except Exception as e:
        flash(f"فشل إنشاء النسخة الاحتياطية: {str(e)}", "error")
        return redirect(url_for("admin_settings"))

@app.route("/admin/backup/restore", methods=["GET", "POST"])
@admin_required
def admin_backup_restore():
    if request.method == "POST":
        if "backup_file" not in request.files:
            flash("لم يتم رفع ملف.", "error")
            return redirect(url_for("admin_backup_restore"))
        file = request.files["backup_file"]
        if file.filename == "":
            flash("لم يتم اختيار ملف.", "error")
            return redirect(url_for("admin_backup_restore"))
        
        if not file.filename.endswith(".zip"):
            flash("الرجاء رفع ملف ZIP فقط.", "error")
            return redirect(url_for("admin_backup_restore"))
        
        try:
            import os, zipfile, shutil
            from datetime import datetime
            
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            temp_zip = "temp_restore_" + ts + ".zip"
            file.save(temp_zip)
            
            # فك الـ ZIP في مجلد مؤقت
            temp_dir = "temp_restore_" + ts
            os.makedirs(temp_dir, exist_ok=True)
            with zipfile.ZipFile(temp_zip, "r") as zf:
                zf.extractall(temp_dir)
            os.remove(temp_zip)
            
            # البحث عن matari.db في الملف
            db_source = None
            for root, dirs, files in os.walk(temp_dir):
                for fname in files:
                    if fname == "matari.db":
                        db_source = os.path.join(root, fname)
                        break
                if db_source:
                    break
            
            if not db_source:
                # مفيش داتابيز في الملف، نستخرج باقي الملفات (static، web.py)
                for root, dirs, files in os.walk(temp_dir):
                    for fname in files:
                        src = os.path.join(root, fname)
                        rel_path = os.path.relpath(src, temp_dir)
                        if rel_path.startswith("static/") or rel_path == "web.py":
                            dst_dir = os.path.dirname(rel_path)
                            if dst_dir:
                                os.makedirs(dst_dir, exist_ok=True)
                            shutil.copy2(src, rel_path)
                shutil.rmtree(temp_dir, ignore_errors=True)
                flash("تمت استعادة الملفات (بدون داتابيز). الداتابيز الحالية لم تتأثر.", "success")
                return redirect(url_for("admin_settings"))
            
            # نسخة أمان من الداتابيز الحالية
            if os.path.exists(DB_PATH):
                shutil.copy(DB_PATH, "pre_restore_" + ts + ".db")
            
            # نسخ الداتابيز الجديدة
            shutil.copy(db_source, DB_PATH)
            print("[RESTORE] Database copied from backup.")
            
            # ⚠️ الأهم: إصلاح تلقائي بعد الاستعادة
            try:
                auto_fix_db()
                print("[RESTORE] auto_fix_db applied after restore.")
            except Exception as e:
                print("[RESTORE] auto_fix error: " + str(e))
            
            # استعادة باقي الملفات (static، web.py) لو موجودة
            for root, dirs, files in os.walk(temp_dir):
                for fname in files:
                    src = os.path.join(root, fname)
                    rel_path = os.path.relpath(src, temp_dir)
                    if rel_path.startswith("static/"):
                        dst_dir = os.path.dirname(rel_path)
                        if dst_dir:
                            os.makedirs(dst_dir, exist_ok=True)
                        shutil.copy2(src, rel_path)
            
            # مسح المجلد المؤقت
            shutil.rmtree(temp_dir, ignore_errors=True)
            
            flash("تمت استعادة البيانات بنجاح + إصلاح الداتابيز تلقائياً! السيرفر هيعيد التشغيل خلال ثانيتين...", "success")
            
            # إعادة تشغيل السيرفر
            import threading, sys
            def restart():
                import time
                time.sleep(2)
                if not os.environ.get("RENDER"):  # على Render يعيد المنصة تشغيل الخدمة بنفسها
                    os.execl(sys.executable, sys.executable, os.path.join(BASE_DIR, "web.py"))
            threading.Thread(target=restart, daemon=True).start()
            
            return redirect(url_for("admin_settings"))
            
        except Exception as e:
            flash("فشل الاستعادة: " + str(e), "error")
            return redirect(url_for("admin_backup_restore"))

    body = f'''<div class="container" style="max-width:600px">
        <div class="section-title">استعادة نسخة احتياطية</div>
        <a href="/admin" class="btn btn-ghost btn-sm" style="margin-bottom:20px">رجوع</a>
        <div class="card" style="border-color:var(--warning);">
            <div style="background:rgba(245,158,11,0.1); padding:16px; border-radius:12px; margin-bottom:20px; color:var(--warn); font-size:14px; line-height:1.6;">
                <b>⚠️ تحذير:</b><br>
                الاستعادة ستستبدل الداتابيز الحالية بداتابيز الملف المرفوع. سيتم إصلاح الأعمدة الناقصة تلقائياً بعد الاستعادة.
            </div>
            <form method="POST" enctype="multipart/form-data" id="restoreForm" onsubmit="return handleRestore(event)">
                <div class="field">
                    <label>ملف النسخة الاحتياطية (ZIP)</label>
                    <input type="file" name="backup_file" id="backupFileInput" accept=".zip" required style="padding:12px; background:var(--bg2); color:var(--text); border:1px solid var(--border); border-radius:10px; width:100%;">
                </div>
                <button class="form-btn" id="restoreBtn" style="background:var(--danger);">استعادة النسخة الآن</button>
            </form>
            
            <div id="restoreProgressBox" style="display:none; margin-top:20px;">
                <div style="display:flex; justify-content:space-between; margin-bottom:8px; font-size:13px; color:var(--text);">
                    <span>جاري رفع الملف...</span>
                    <span id="restorePct">0%</span>
                </div>
                <div style="height:12px; background:var(--bg2); border-radius:999px; overflow:hidden; border:1px solid var(--border);">
                    <div id="restoreBar" style="height:100%; width:0%; background:linear-gradient(90deg, #6366f1, #06b6d4); border-radius:999px; transition:width 0.2s;"></div>
                </div>
                <div style="margin-top:8px; font-size:12px; color:var(--muted); text-align:center;">
                    <span id="restoreSize">0.00 MB</span> / <span id="restoreTotal">0.00 MB</span>
                </div>
            </div>
        </div>
    </div>'''
    body += '''
    <script>
    function handleRestore(e) {
        e.preventDefault();
        var fileInput = document.getElementById("backupFileInput");
        if (!fileInput.files.length) { alert("اختر ملف"); return false; }
        var file = fileInput.files[0];
        if (!confirm("هل أنت متأكد؟ سيتم استبدال البيانات!")) return false;
        document.getElementById("restoreProgressBox").style.display = "block";
        document.getElementById("restoreTotal").textContent = (file.size / 1048576).toFixed(2) + " MB";
        document.getElementById("restoreBtn").disabled = true;
        document.getElementById("restoreBtn").textContent = "جاري الرفع...";
        var formData = new FormData();
        formData.append("backup_file", file);
        var xhr = new XMLHttpRequest();
        xhr.open("POST", "/admin/backup/restore", true);
        xhr.upload.onprogress = function(ev) {
            if (ev.lengthComputable) {
                var pct = Math.round((ev.loaded / ev.total) * 100);
                document.getElementById("restorePct").textContent = pct + "%";
                document.getElementById("restoreBar").style.width = pct + "%";
                document.getElementById("restoreSize").textContent = (ev.loaded / 1048576).toFixed(2) + " MB";
            }
        };
        xhr.onload = function() {
            if (xhr.status === 200) {
                document.getElementById("restoreBar").style.width = "100%";
                document.getElementById("restorePct").textContent = "100%";
                setTimeout(function() { window.location.href = "/admin/settings"; }, 1500);
            } else {
                alert("فشل الرفع");
                document.getElementById("restoreBtn").disabled = false;
                document.getElementById("restoreBtn").textContent = "استعادة النسخة الآن";
            }
        };
        xhr.send(formData);
        return false;
    }
    </script>
    '''
    return page("admin_backup_restore", body=body)


@app.route("/admin/notifications", methods=["GET", "POST"])
@admin_required
def admin_notifications():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            text = request.form.get("text", "").strip()
            level = request.form.get("level", "info")
            t_color = request.form.get("text_color", "#e8e8f5")
            f_size = request.form.get("font_size", "15px")
            icon = request.form.get("icon", "bell")
            if text:
                btn_url = request.form.get("btn_url", "").strip()
                btn_text = request.form.get("btn_text", "").strip()
                db().execute("UPDATE announcements SET is_active=0")
                db().execute("INSERT INTO announcements(text, level, text_color, font_size, icon, btn_text, btn_url, is_active) VALUES(?,?,?,?,?,?,?,1)", 
                             (text, level, t_color, f_size, icon, btn_text, btn_url))
                db().commit()
                flash("تم نشر الإشعار!", "success")
        elif action in ("delete", "delete_all"):
            db().execute("DELETE FROM announcements")
            db().commit()
            flash("تم مسح الكل.", "success")
        return redirect(url_for("admin_notifications"))

    history = db().execute("SELECT * FROM announcements ORDER BY id DESC").fetchall()
    hist_html = ""
    for h in history:
        c = "#6366f1" if h["level"] == "info" else ("#10b981" if h["level"] == "success" else "#ef4444")
        hist_html += '<div style="padding:12px;background:var(--bg2);border-radius:10px;margin-bottom:8px;border-right:4px solid ' + c + ';">'
        hist_html += '<div style="font-size:14px;">' + str(h["text"]) + '</div>'
        hist_html += '<div style="font-size:10px;color:var(--muted);">' + str(h["created_at"])[:10] + '</div>'
        hist_html += '</div>'
    if not hist_html:
        hist_html = '<div style="color:var(--muted);text-align:center;">لا يوجد إشعارات سابقة</div>'

    body = '<div class="container" style="max-width:600px">'
    body += '<div class="section-title">إدارة الإشعارات</div>'
    body += '<a href="/admin" class="btn btn-ghost btn-sm" style="margin-bottom:20px">رجوع</a>'
    
    body += '<div class="card" style="margin-bottom:24px; background:linear-gradient(145deg, var(--card), var(--card2));">'
    body += '<form method="POST" id="notifForm">'
    body += '<input type="hidden" name="action" value="add">'
    body += '<input type="hidden" name="text_color" value="#e8e8f5">'
    body += '<input type="hidden" name="font_size" value="15px">'
    
    body += '<div class="field">'
    body += '<label style="font-weight:800; color:var(--primary2); margin-bottom:10px; display:block;">محرر الإشعار (حدد النص، ثم اضغط الزر)</label>'
    
    # أدوات التنسيق
    body += '<div style="display:flex; flex-wrap:wrap; gap:6px; margin-bottom:10px; background:rgba(0,0,0,0.2); padding:8px; border-radius:12px; border:1px solid var(--border);">'
    
    # أزرار التنسيق النصي
    body += '<button type="button" onclick="insertCode(\'[b]\', \'[/b]\')" title="عريض" style="width:36px; height:36px; border-radius:8px; background:var(--bg2); border:1px solid var(--border); color:var(--text); cursor:pointer; font-weight:900; font-size:14px;">B</button>'
    body += '<button type="button" onclick="insertCode(\'[u]\', \'[/u]\')" title="تسطير" style="width:36px; height:36px; border-radius:8px; background:var(--bg2); border:1px solid var(--border); color:var(--text); cursor:pointer; text-decoration:underline; font-size:14px;">U</button>'
    body += '<button type="button" onclick="insertCode(\'[big]\', \'[/big]\')" title="تكبير" style="width:36px; height:36px; border-radius:8px; background:var(--bg2); border:1px solid var(--border); color:var(--text); cursor:pointer; font-size:18px;">A+</button>'
    
    # أزرار الألوان
    colors = [
        ("[red]", "[/red]", "#ef4444", "أحمر"),
        ("[green]", "[/green]", "#10b981", "أخضر"),
        ("[gold]", "[/gold]", "#fbbf24", "أصفر"),
        ("[blue]", "[/blue]", "#818cf8", "بنفسجي"),
        ("[cyan]", "[/cyan]", "#06b6d4", "سماوي")
    ]
    for code_open, code_close, c_hex, c_name in colors:
        body += '<button type="button" onclick="insertCode(\'' + code_open + '\', \'' + code_close + '\')" title="' + c_name + '" style="width:32px; height:32px; border-radius:50%; background:' + c_hex + '; border:2px solid var(--border); cursor:pointer;"></button>'
    
    # أزرار الأيقونات المدمجة (وسط النص)
    body += '<button type="button" onclick="insertText(\'[icon-heart]\')" title="قلب" style="width:36px; height:36px; border-radius:8px; background:var(--bg2); border:1px solid var(--border); color:#ef4444; cursor:pointer; display:flex; align-items:center; justify-content:center;"><svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/></svg></button>'
    body += '<button type="button" onclick="insertText(\'[icon-star]\')" title="نجمة" style="width:36px; height:36px; border-radius:8px; background:var(--bg2); border:1px solid var(--border); color:#fbbf24; cursor:pointer; display:flex; align-items:center; justify-content:center;"><svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg></button>'
    body += '<button type="button" onclick="insertText(\'[icon-bell]\')" title="جرس" style="width:36px; height:36px; border-radius:8px; background:var(--bg2); border:1px solid var(--border); color:#818cf8; cursor:pointer; display:flex; align-items:center; justify-content:center;"><svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg></button>'
    body += '<button type="button" onclick="insertText(\'[icon-fire]\')" title="نار" style="width:36px; height:36px; border-radius:8px; background:var(--bg2); border:1px solid var(--border); color:#f97316; cursor:pointer; display:flex; align-items:center; justify-content:center;"><svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"/></svg></button>'
    
    body += '</div>'
    
    body += '<textarea name="text" id="notifText" rows="6" required placeholder="اكتب إشعارك هنا..." style="width:100%; padding:14px; background:var(--bg2); color:var(--text); border:1.5px solid var(--border); border-radius:12px; font-family:inherit; font-size:15px; resize:vertical;"></textarea>'
    body += '</div>'
    
    # خانات الرابط ونص الزر
    body += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px;">'
    body += '<div class="field" style="margin:0;">'
    body += '<label style="font-size:11px;font-weight:700;color:var(--muted);margin-bottom:4px;display:block;">نص الزر (اختياري)</label>'
    body += '<input name="btn_text" placeholder="تسوق الآن" style="width:100%;padding:10px;background:var(--bg2);color:var(--text);border:1px solid var(--border);border-radius:8px;font-family:inherit;font-size:13px;">'
    body += '</div>'
    body += '<div class="field" style="margin:0;">'
    body += '<label style="font-size:11px;font-weight:700;color:var(--muted);margin-bottom:4px;display:block;">رابط الزر (اختياري)</label>'
    body += '<input name="btn_url" placeholder="/store" style="width:100%;padding:10px;background:var(--bg2);color:var(--text);border:1px solid var(--border);border-radius:8px;font-family:monospace;font-size:13px;direction:ltr;">'
    body += '</div>'
    body += '</div>'
    
    # لون التمييز (بدون قسم الأيقونات القديم)
    body += '<div class="field">'
    body += '<label style="font-size:12px; font-weight:700; color:var(--muted); margin-bottom:6px; display:block;">لون التمييز (للإشعار نفسه)</label>'
    body += '<select name="level" style="width:100%; height:40px; background:var(--bg2); color:var(--text); border:1px solid var(--border); border-radius:8px; padding:0 10px; font-family:inherit;">'
    body += '<option value="info">بنفسجي (معلومة)</option>'
    body += '<option value="success">أخضر (نجاح)</option>'
    body += '<option value="error">أحمر (خطأ)</option>'
    body += '</select></div>'
    
    # معاينة مباشرة
    body += '<div class="field">'
    body += '<label style="font-size:12px; font-weight:700; color:var(--muted); margin-bottom:6px; display:block;">معاينة مباشرة (شكل الإشعار النهائي)</label>'
    body += '<div id="previewBox" style="background:linear-gradient(145deg, var(--card), var(--card2)); padding:16px; border-radius:12px; border:1px solid var(--border); min-height:60px; color:#e8e8f5; font-size:14px; line-height:1.8; border-right:4px solid #6366f1;">'
    body += '<div style="font-size:12px; font-weight:800; color:#6366f1; margin-bottom:6px;">إشعار الإدارة</div>'
    body += '<div id="previewContent" style="color:#e8e8f5;">اكتب النص فوق عشان تشوف المعاينة...</div>'
    body += '</div></div>'
    
    # القوالب الجاهزة (أزرار صغيرة)
    body += '<div class="field">'
    body += '<label style="font-size:12px; font-weight:700; color:var(--muted); margin-bottom:8px; display:block;">قوالب جاهزة (اضغط للتحميل)</label>'
    body += '<div style="display:flex; flex-wrap:wrap; gap:6px;">'
    body += '<button type="button" onclick="loadTemplate(WA_TPL)" style="padding:8px 14px;background:rgba(37,211,102,0.15);border:1px solid #25D366;border-radius:8px;color:#25D366;cursor:pointer;font-weight:700;font-size:12px;">واتساب</button>'
    body += '<button type="button" onclick="loadTemplate(TG_TPL)" style="padding:8px 14px;background:rgba(6,182,212,0.15);border:1px solid #06b6d4;border-radius:8px;color:#06b6d4;cursor:pointer;font-weight:700;font-size:12px;">تيليجرام</button>'
    body += '<button type="button" onclick="loadTemplate(LIM_TPL)" style="padding:8px 14px;background:rgba(239,68,68,0.15);border:1px solid #ef4444;border-radius:8px;color:#ef4444;cursor:pointer;font-weight:700;font-size:12px;">عرض محدود</button>'
    body += '<button type="button" onclick="loadTemplate(WEL_TPL)" style="padding:8px 14px;background:rgba(129,140,248,0.15);border:1px solid #818cf8;border-radius:8px;color:#818cf8;cursor:pointer;font-weight:700;font-size:12px;">ترحيبي</button>'
    body += '<button type="button" onclick="loadTemplate(DEP_TPL)" style="padding:8px 14px;background:rgba(251,191,36,0.15);border:1px solid #fbbf24;border-radius:8px;color:#fbbf24;cursor:pointer;font-weight:700;font-size:12px;">شحن رصيد</button>'
    body += '<button type="button" onclick="loadTemplate(MNT_TPL)" style="padding:8px 14px;background:rgba(239,68,68,0.15);border:1px solid #ef4444;border-radius:8px;color:#ef4444;cursor:pointer;font-weight:700;font-size:12px;">صيانة</button>'
    body += '</div></div>'

    body += '<button type="submit" class="form-btn" style="padding:14px; font-size:15px; margin-top:10px;">نشر الإشعار الآن</button>'
    body += '</form></div>'
    
    body += '<div class="card">'
    body += '<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">'
    body += '<h3 style="font-size:16px; margin:0;">الإشعارات السابقة (' + str(len(history)) + ')</h3>'
    body += '<form method="POST" style="margin:0;"><input type="hidden" name="action" value="delete_all"><button class="btn btn-sm" style="background:var(--danger); padding:6px 12px; font-size:11px;">مسح الكل</button></form>'
    body += '</div>'
    body += hist_html
    body += '</div></div>'
    
    body += """
    <script>
    function insertCode(openCode, closeCode) {
        var ta = document.getElementById('notifText');
        var start = ta.selectionStart;
        var end = ta.selectionEnd;
        var text = ta.value;
        if (start === end) {
            ta.value = text.substring(0, start) + openCode + 'النص' + closeCode + text.substring(end);
            ta.focus();
            ta.setSelectionRange(start + openCode.length, start + openCode.length + 4);
        } else {
            var selected = text.substring(start, end);
            ta.value = text.substring(0, start) + openCode + selected + closeCode + text.substring(end);
            ta.focus();
            ta.setSelectionRange(start + openCode.length, start + openCode.length + selected.length);
        }
    }
    function insertText(txt) {
        var ta = document.getElementById('notifText');
        var start = ta.selectionStart;
        ta.value = ta.value.substring(0, start) + txt + ta.value.substring(ta.selectionEnd);
        ta.focus();
        ta.setSelectionRange(start + txt.length, start + txt.length);
        updatePreview();
    }
    
    function renderBBCode(text) {
        if (!text) return '';
        var t = text;
        t = t.replace(/\[b\]/g, '<b>').replace(/\[\/b\]/g, '</b>');
        t = t.replace(/\[u\]/g, '<u>').replace(/\[\/u\]/g, '</u>');
        t = t.replace(/\[big\]/g, "<span style='font-size:20px;'>").replace(/\[\/big\]/g, '</span>');
        t = t.replace(/\[red\]/g, "<span style='color:#ef4444;font-weight:700;'>").replace(/\[\/red\]/g, '</span>');
        t = t.replace(/\[green\]/g, "<span style='color:#10b981;font-weight:700;'>").replace(/\[\/green\]/g, '</span>');
        t = t.replace(/\[gold\]/g, "<span style='color:#fbbf24;font-weight:700;'>").replace(/\[\/gold\]/g, '</span>');
        t = t.replace(/\[blue\]/g, "<span style='color:#818cf8;font-weight:700;'>").replace(/\[\/blue\]/g, '</span>');
        t = t.replace(/\[cyan\]/g, "<span style='color:#06b6d4;font-weight:700;'>").replace(/\[\/cyan\]/g, '</span>');
        t = t.replace(/\[icon-whatsapp\]/g, "<svg width='18' height='18' viewBox='0 0 24 24' fill='#25D366' style='display:inline-block;vertical-align:middle;margin:0 4px;'><path d='M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z'/></svg>");
        return t;
    }
    
    function updatePreview() {
        var ta = document.getElementById('notifText');
        var preview = document.getElementById('previewContent');
        if (preview) {
            var txt = ta.value.trim();
            if (!txt) {
                preview.innerHTML = 'اكتب النص فوق عشان تشوف المعاينة...';
            } else {
                preview.innerHTML = renderBBCode(txt);
            }
        }
    }
    
    function loadTemplate(html) {
        var ta = document.getElementById('notifText');
        ta.value = html;
        updatePreview();
        ta.focus();
    }
    function loadTemplate(html) {
        var ta = document.getElementById('notifText');
        ta.value = html;
        updatePreview();
        ta.focus();
    }
    
    var WA_TPL = '<div style="display:flex;align-items:center;justify-content:center;gap:8px;margin-bottom:8px;"><svg width="22" height="22" viewBox="0 0 24 24" fill="#25D366"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/></svg><b style="color:#10b981;font-size:18px;">عرض واتساب خاص</b></div><hr style="border:none;border-top:1px dashed #6366f1;margin:6px 0;"><div style="display:flex;justify-content:space-between;padding:4px 0;"><span style="color:#fbbf24;font-weight:800;">🇾🇪 اليمن</span><span style="color:#06b6d4;">1.50$</span></div><div style="display:flex;justify-content:space-between;padding:4px 0;"><span style="color:#fbbf24;font-weight:800;">🇪🇬 مصر</span><span style="color:#06b6d4;">2.00$</span></div><div style="display:flex;justify-content:space-between;padding:4px 0;"><span style="color:#fbbf24;font-weight:800;">🇸🇦 السعودية</span><span style="color:#06b6d4;">3.00$</span></div><hr style="border:none;border-top:1px dashed #6366f1;margin:6px 0;"><div style="text-align:center;margin-top:8px;"><a href="#" style="display:inline-block;padding:8px 20px;background:linear-gradient(135deg,#10b981,#059669);color:#fff;font-weight:900;font-size:13px;border-radius:20px;text-decoration:none;box-shadow:0 4px 12px rgba(16,185,129,0.4);">تواصل معنا الآن</a></div>';
    var TG_TPL = '<div style="display:flex;align-items:center;justify-content:center;gap:8px;margin-bottom:8px;"><svg width="22" height="22" viewBox="0 0 24 24" fill="#0088cc"><path d="M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0zm5.562 8.161c-.18 1.897-.962 6.502-1.359 8.627-.168.9-.5 1.201-.82 1.23-.697.064-1.226-.461-1.901-.903-1.056-.692-1.653-1.123-2.678-1.798-1.185-.781-.417-1.21.258-1.911.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635.099-.002.321.023.465.14a.506.506 0 01.171.325c.016.093.036.306.02.472z"/></svg><b style="color:#06b6d4;font-size:18px;">عرض تيليجرام خاص</b></div><hr style="border:none;border-top:1px dashed #06b6d4;margin:6px 0;"><div style="display:flex;justify-content:space-between;padding:4px 0;"><span style="color:#fbbf24;font-weight:800;">🇾🇪 اليمن</span><span style="color:#06b6d4;">2.00$</span></div><div style="display:flex;justify-content:space-between;padding:4px 0;"><span style="color:#fbbf24;font-weight:800;">🇮🇶 العراق</span><span style="color:#06b6d4;">2.50$</span></div><div style="display:flex;justify-content:space-between;padding:4px 0;"><span style="color:#fbbf24;font-weight:800;">🇹🇷 تركيا</span><span style="color:#06b6d4;">3.50$</span></div><hr style="border:none;border-top:1px dashed #06b6d4;margin:6px 0;"><div style="text-align:center;margin-top:8px;"><a href="#" style="display:inline-block;padding:8px 20px;background:linear-gradient(135deg,#06b6d4,#3b82f6);color:#fff;font-weight:900;font-size:13px;border-radius:20px;text-decoration:none;box-shadow:0 4px 12px rgba(6,182,212,0.4);">تواصل معنا الآن</a></div>';
    var LIM_TPL = '<div style="text-align:center;margin-bottom:8px;"><svg width="24" height="24" viewBox="0 0 24 24" fill="#ef4444"><path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"/></svg><b style="color:#ef4444;font-size:18px;">عرض محدود!</b></div><div style="text-align:center;margin-bottom:8px;color:#e8e8f5;font-size:14px;line-height:1.6;">خصم <b style="color:#fbbf24;font-size:20px;">20%</b> على جميع الأرقام<br>لفترة محدودة جداً</div><hr style="border:none;border-top:1px dashed #ef4444;margin:6px 0;"><div style="text-align:center;margin-top:8px;"><a href="#" style="display:inline-block;padding:10px 24px;background:linear-gradient(135deg,#ef4444,#b91c1c);color:#fff;font-weight:900;font-size:14px;border-radius:20px;text-decoration:none;box-shadow:0 4px 12px rgba(239,68,68,0.4);">احصل على العرض الآن</a></div>';
    var WEL_TPL = '<div style="text-align:center;margin-bottom:8px;"><b style="color:#818cf8;font-size:20px;">مرحباً بك في متجر مطري</b></div><div style="text-align:center;margin-bottom:8px;color:#e8e8f5;font-size:13px;line-height:1.7;">نقدم لك أفضل الأرقام الموثوقة<br>مع تسليم فوري وسحب أكواد تلقائي</div><hr style="border:none;border-top:1px dashed #818cf8;margin:6px 0;"><div style="text-align:center;margin-top:8px;"><a href="#" style="display:inline-block;padding:10px 24px;background:linear-gradient(135deg,#818cf8,#6366f1);color:#fff;font-weight:900;font-size:13px;border-radius:20px;text-decoration:none;box-shadow:0 4px 12px rgba(129,140,248,0.4);">تصفح المتجر</a></div>';
    var DEP_TPL = '<div style="display:flex;align-items:center;justify-content:center;gap:8px;margin-bottom:8px;"><svg width="22" height="22" viewBox="0 0 24 24" fill="#fbbf24"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg><b style="color:#fbbf24;font-size:18px;">اشحن رصيدك الآن</b></div><div style="text-align:center;margin-bottom:8px;color:#e8e8f5;font-size:13px;">طرق دفع متعددة: بينانس، جيب، ون كاش، فودافون كاش</div><hr style="border:none;border-top:1px dashed #fbbf24;margin:6px 0;"><div style="text-align:center;margin-top:8px;"><a href="#" style="display:inline-block;padding:10px 24px;background:linear-gradient(135deg,#fbbf24,#f59e0b);color:#000;font-weight:900;font-size:13px;border-radius:20px;text-decoration:none;box-shadow:0 4px 12px rgba(251,191,36,0.4);">اشحن الآن</a></div>';
    var MNT_TPL = '<div style="text-align:center;margin-bottom:8px;"><svg width="24" height="24" viewBox="0 0 24 24" fill="#ef4444"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg><b style="color:#ef4444;font-size:18px;">صيانة مؤقتة</b></div><div style="text-align:center;margin-bottom:8px;color:#e8e8f5;font-size:13px;line-height:1.7;">نعتذر عن إيقاف المتجر مؤقتاً<br>لأعمال الصيانة والتحديث<br>سنعود قريباً بإذن الله</div>';
    
    document.getElementById('notifText').addEventListener('input', updatePreview);
    </script>
    """
    
    return page("admin_notifications", body=body)


@app.route("/admin/manual-deposit", methods=["GET", "POST"])
@admin_required
def admin_manual_deposit():
    if request.method == "POST":
        ident = request.form.get("ident", "").strip()
        try:
            amt = float(request.form.get("amount", "0"))
        except ValueError:
            amt = 0
        if not ident or amt <= 0:
            flash("تأكد من إدخال الآيدي والمبلغ بشكل صحيح.", "error")
            return redirect(url_for("admin_manual_deposit"))
        user = db().execute("SELECT * FROM users WHERE username=? OR custom_id=? OR CAST(user_id AS TEXT)=?", (ident, ident, ident)).fetchone()
        if not user:
            flash("المستخدم غير موجود.", "error")
            return redirect(url_for("admin_manual_deposit"))
        db().execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amt, user["user_id"]))
        db().execute("INSERT INTO deposits(user_id, method, amount_usd, status, trans_id, created_at, processed_at) VALUES(?,?,?,?,?,datetime('now'),datetime('now'))",
                     (user["user_id"], "manual_admin", amt, "approved", "إضافة يدوية بواسطة الإدارة"))
        db().commit()
        audit("manual_deposit", f"uid={user['user_id']} amt={amt}")
        flash(f"تم شحن ${amt:.2f} لحساب {user['username']} بنجاح!", "success")
        return redirect(url_for("admin_home"))

    body = f'''
    <div class="container" style="max-width:600px">
      <div class="section-title">شحن حسابي (يدوي)</div>
      <a href="/admin" class="btn btn-ghost btn-sm" style="margin-bottom:20px">{ico("arrow-left", 14)} رجوع</a>
      <div class="card" style="border-color:rgba(16,185,129,0.4);">
        <p style="color:var(--muted);font-size:14px;margin-bottom:20px;line-height:1.6;">اكتب اسم المستخدم أو الآيدي، وأضف المبلغ لرصيده فوراً (سيتم تسجيل العملية في سجل الشحنات).</p>
        <form method="POST">
          <div class="field"><label>اسم المستخدم أو الآيدي</label><input name="ident" placeholder="مثال: admin أو 12345678" required></div>
          <div class="field"><label>المبلغ بالدولار</label><input name="amount" type="number" step="0.01" min="0.01" placeholder="مثال: 5.00" required></div>
          <button class="form-btn" style="background:var(--gradient);font-size:16px;padding:14px;">{ico("dollar", 20)} شحن الرصيد الآن</button>
        </form>
      </div>
    </div>'''
    return page("admin_manual_deposit", body=body)


@app.route("/admin")
@admin_required
def admin_home():
    # حساب الإشعارات
    try:
        unread_messages = db().execute("""
            SELECT COUNT(*) c FROM ticket_messages tm
            JOIN tickets t ON t.id = tm.ticket_id
            WHERE tm.sender = 'user' AND tm.is_read = 0
        """).fetchone()["c"]
    except Exception:
        unread_messages = 0
    try:
        pending_deposits = db().execute("SELECT COUNT(*) c FROM deposits WHERE status='pending'").fetchone()["c"]
    except Exception:
        pending_deposits = 0
    try:
        pending_numbers = db().execute("SELECT COUNT(*) c FROM numbers WHERE status='pending'").fetchone()["c"]
    except Exception:
        pending_numbers = 0
    
    return page("admin_home", stats=stats(), 
                unread_messages=unread_messages,
                pending_deposits=pending_deposits,
                pending_numbers=pending_numbers)


@app.route("/admin/deposit/<int:did>/delete", methods=["POST"])
@admin_required
def admin_deposit_delete(did):
    db().execute("DELETE FROM deposits WHERE id=?", (did,))
    db().commit()
    flash("تم حذف الشحنة.", "success")
    return redirect(url_for("admin_deposits"))

@app.route("/admin/deposits/clear", methods=["POST"])
@admin_required
def admin_deposits_clear():
    # بيحذف الشحنات المقبولة والمرفوضة فقط، ويسيب المعلقة
    db().execute("DELETE FROM deposits WHERE status IN ('approved', 'rejected')")
    db().commit()
    flash("تم مسح كل الدفعات القديمة (المقبولة والمرفوضة).", "success")
    return redirect(url_for("admin_deposits"))


@app.route("/admin/deposits")
@admin_required
def admin_deposits():
    deps = db().execute("SELECT d.*, u.username FROM deposits d JOIN users u ON u.user_id=d.user_id ORDER BY d.id DESC LIMIT 200").fetchall()
    return page("admin_deposits", deposits=deps)

@app.route("/admin/deposit/<int:did>/<action>", methods=["POST"])
@admin_required
def admin_deposit_action(did, action):
    ok, msg = (approve_deposit(did) if action == "approve" else reject_deposit(did))
    flash(msg, "success" if ok else "error")
    return redirect(url_for("admin_deposits"))

@app.route("/admin/settings", methods=["GET", "POST"])
@admin_required
def admin_settings():
    if request.method == "POST":
        for k in DEFAULT_SETTINGS.keys():
            if k in request.form:
                val = request.form[k].strip()
                if val and set(val) == {chr(8226)}:
                    continue  # نجوم = حقل سري لم يُغيَّر
                # لا تمسح القيم الحساسة إذا تُركت فارغة
                if val == "" and k in ("EMAIL_ADDRESS", "EMAIL_PASSWORD", "BINANCE_API_KEY", "BINANCE_API_SECRET", "TG_API_HASH"):
                    continue
                set_setting(k, val)
        
        # حفظ حالة نظام الإحالات (checkbox - لو مش موجود يبقى 0)
        set_setting("REFERRAL_ENABLED", "1" if request.form.get("REFERRAL_ENABLED") == "1" else "0")
        # حفظ حالة المكافأة اليومية (checkbox - لو مش موجود يبقى 0)
        set_setting("DAILY_BONUS_ENABLED", "1" if request.form.get("DAILY_BONUS_ENABLED") == "1" else "0")
        flash("تم حفظ الإعدادات بنجاح.", "success")
        return redirect(url_for("admin_settings"))
    return page("admin_settings", s=all_settings())





@app.route("/admin/user/<int:uid>/credentials")
@admin_required
def admin_user_credentials(uid):
    user_data = db().execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
    if not user_data:
        flash("المستخدم غير موجود", "error")
        return redirect(url_for("admin_users"))
    body = (
        '<div class="container" style="max-width:500px; padding-top:20px;">'
        '<div class="section-title" style="text-align:center;margin-bottom:20px;">بيانات الدخول</div>'
        '<div class="card" style="padding:20px;">'
        '<div style="background:var(--bg2);border:1px solid var(--border);border-radius:12px;padding:16px;margin-bottom:16px;">'
        '<div style="font-size:12px;color:var(--muted);margin-bottom:6px;">اسم المستخدم</div>'
        '<div style="display:flex;align-items:center;gap:10px;">'
        '<span style="font-family:monospace;font-size:18px;color:var(--text);flex:1;">' + esc(user_data["username"]) + '</span>'
        '<button onclick="copyText(\'' + esc(user_data["username"]) + '\', this)" class="btn btn-sm" style="padding:8px 12px;background:var(--primary2);color:#fff;font-size:12px;">نسخ</button>'
        '</div></div>'
        '<div style="background:var(--bg2);border:1px solid var(--border);border-radius:12px;padding:16px;margin-bottom:16px;">'
        '<div style="font-size:12px;color:var(--muted);margin-bottom:6px;">آيدي التحويل</div>'
        '<div style="display:flex;align-items:center;gap:10px;">'
        '<span style="font-family:monospace;font-size:18px;color:var(--primary2);flex:1;">' + str(user_data["custom_id"] or user_data["user_id"]) + '</span>'
        '<button onclick="copyText(\'' + str(user_data["custom_id"] or user_data["user_id"]) + '\', this)" class="btn btn-sm" style="padding:8px 12px;background:var(--primary2);color:#fff;font-size:12px;">نسخ</button>'
        '</div></div>'
        '<div style="background:var(--bg2);border:1px solid var(--border);border-radius:12px;padding:16px;margin-bottom:24px;">'
        '<div style="font-size:12px;color:var(--muted);margin-bottom:10px;">كلمة المرور</div>'
        '<form method="POST" action="/admin/user/' + str(uid) + '/reset_pass">'
        '<button type="submit" class="btn" style="width:100%;padding:12px;background:var(--warn);color:#fff;font-size:14px;" onclick="return confirm(\'توليد باسورد جديدة؟\');">توليد كلمة مرور جديدة</button>'
        '</form></div>'
        '<a href="/admin/users" class="btn btn-ghost" style="width:100%;padding:12px;">رجوع</a>'
        '</div></div>'
    )
    return page("admin_creds", body=body)

@app.route("/admin/user/<int:uid>/reset_pass", methods=["POST"])
@admin_required
def admin_user_reset_pass(uid):
    from werkzeug.security import generate_password_hash
    import secrets, string
    new_pass = ''.join(secrets.choice(string.ascii_letters + string.digits) for i in range(10))
    db().execute("UPDATE users SET password_hash=? WHERE user_id=?", (generate_password_hash(new_pass), uid))
    db().commit()
    flash("تم توليد كلمة المرور: " + new_pass, "success")
    return redirect(url_for("admin_user_credentials", uid=uid))

@app.route("/admin/user/<int:uid>/delete", methods=["POST"])
@admin_required
def admin_user_delete(uid):
    if uid == session.get("user_id"):
        flash("لا يمكنك حذف حسابك!", "error")
        return redirect(url_for("admin_users"))
    try:
        db().execute("DELETE FROM users WHERE user_id=?", (uid,))
        db().execute("UPDATE numbers SET status='available', buyer_id=NULL, sold_at=NULL WHERE buyer_id=?", (uid,))
        db().execute("DELETE FROM tickets WHERE user_id=?", (uid,))
        db().execute("DELETE FROM pending_balance WHERE user_id=?", (uid,))
        db().commit()
        flash("تم حذف المستخدم وإرجاع أرقامه.", "success")
    except Exception as e:
        flash("خطأ: " + str(e), "error")
    return redirect(url_for("admin_users"))

@app.route("/admin/users")
@admin_required
def admin_users():
    users = db().execute("SELECT * FROM users ORDER BY user_id DESC LIMIT 200").fetchall()
    return page("admin_users", users=users)

@app.route("/admin/user/<int:uid>/action", methods=["POST"])
@admin_required
def admin_user_action(uid):
    action = request.form.get("action", "")
    mapping = {
        "ban": "UPDATE users SET is_banned=1 WHERE user_id=?",
        "unban": "UPDATE users SET is_banned=0 WHERE user_id=?",
        "make_admin": "UPDATE users SET is_admin=1 WHERE user_id=?",
        "reset_captcha": "UPDATE users SET captcha_passed=0 WHERE user_id=?",
    }
    sql = mapping.get(action)
    if sql:
        db().execute(sql, (uid,)); db().commit()
        flash("تم.", "success")
    return redirect(url_for("admin_users"))

@app.route("/admin/user/<int:uid>/balance", methods=["POST"])
@admin_required
def admin_user_balance(uid):
    try: amt = float(request.form.get("amount", "0"))
    except ValueError: amt = 0
    db().execute("UPDATE users SET balance=MAX(balance+?,0) WHERE user_id=?", (amt, uid))
    db().commit()
    u = get_user(uid)
    flash(f"رصيد جديد: ${u['balance']:.2f}", "success")
    return redirect(url_for("admin_users"))

@app.route("/admin/numbers", methods=["GET", "POST"])
@admin_required
def admin_numbers():
    if request.method == "POST":
        action = request.form.get("action", "")
        if action == "add":
            try:
                platform = request.form["platform"].strip()
                phone = request.form["phone"].strip()
                price = float(request.form["price"])
                
                # نحدد الدولة تلقائياً من الرقم
                detected_country, detected_flag = detect_country_from_phone(phone)
                if not detected_country:
                    flash("لم نتمكن من تحديد الدولة من الرقم. تأكد من رمز الدولة (+967...)", "error")
                    return redirect(url_for("admin_numbers"))
                
                # التحقق: نمنع التكرار فقط لو الرقم متاح للبيع حالياً
                existing_avail = db().execute("SELECT 1 FROM numbers WHERE phone=? AND platform=? AND status='available'", (phone, platform)).fetchone()
                if existing_avail:
                    flash("هذا الرقم معروض للبيع بالفعل. لا يمكن إضافته مرتين.", "error")
                    return redirect(url_for("admin_numbers"))
                
                is_premium = 1 if request.form.get("is_premium") == "on" else 0
                db().execute("INSERT INTO numbers(platform,country,phone,price,is_premium) VALUES(?,?,?,?,?)",
                             (platform, detected_country, phone, price, is_premium))
                db().commit()
                flash(f"تمت الإضافة! الدولة: {detected_country} {detected_flag or ''}", "success")
            except Exception as e:
                flash(f"خطأ: {e}", "error")
        elif action == "edit":
            try:
                nid = request.form["id"]
                price = float(request.form["price"])
                platform = request.form["platform"]
                is_prem = 1 if request.form.get("is_premium") == "1" else 0
                db().execute("UPDATE numbers SET price=?, platform=?, is_premium=? WHERE id=? AND status='available'", (price, platform, is_prem, nid))
                db().commit()
                flash("تم تعديل الرقم بنجاح.", "success")
            except Exception as e:
                flash("خطأ في التعديل: " + str(e), "error")
        elif action == "delete":
            db().execute("DELETE FROM numbers WHERE id=? AND status='available'", (request.form["id"],))
            db().commit(); flash("تم الحذف.", "success")
        elif action == "restore":
            db().execute("UPDATE numbers SET status='available', buyer_id=NULL, sold_at=NULL WHERE id=?",
                         (request.form["id"],))
            db().commit(); flash("تم الإرجاع.", "success")
        return redirect(url_for("admin_numbers"))
    nums = db().execute("SELECT * FROM numbers ORDER BY id DESC LIMIT 300").fetchall()
    return page("admin_numbers", numbers=nums)

@app.route("/admin/vouchers", methods=["GET", "POST"])
@admin_required
def admin_vouchers():
    if request.method == "POST":
        try:
            amt = float(request.form.get("amount", "0"))
            count = int(request.form.get("count", "1"))
            if amt > 0 and 1 <= count <= 100:
                codes = []
                for _ in range(count):
                    for _try in range(5):
                        code = "MT-" + "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(10))
                        try:
                            db().execute("INSERT INTO vouchers(code,amount) VALUES(?,?)", (code, amt))
                            db().commit(); codes.append(code); break
                        except sqlite3.IntegrityError: continue
                flash(f"تم توليد {len(codes)} كود بقيمة ${amt:.2f}", "success")
        except Exception as e: flash(f"خطأ: {e}", "error")
        return redirect(url_for("admin_vouchers"))
    vs = db().execute("SELECT * FROM vouchers ORDER BY id DESC LIMIT 300").fetchall()
    return page("admin_vouchers", vouchers=vs)

@app.route("/admin/coupons", methods=["GET", "POST"])
@admin_required
def admin_coupons():
    if request.method == "POST":
        code = request.form.get("code", "").strip().upper()
        try: pct = float(request.form.get("percent", "0"))
        except: pct = 0
        try: mx = int(request.form.get("max_uses", "0"))
        except: mx = 0
        days = 0
        try: days = int(request.form.get("days", "0"))
        except: pass
        if not code or not (0 < pct <= 90):
            flash("كود غير صالح أو نسبة خارج النطاق.", "error")
            return redirect(url_for("admin_coupons"))
        expires = None
        if days > 0:
            from datetime import timedelta
            expires = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        try:
            db().execute("INSERT INTO coupons(code,percent,max_uses,expires_at) VALUES(?,?,?,?)",
                         (code, pct, mx, expires))
            db().commit(); flash(f"تم إنشاء كوبون {code} ({pct:g}%)", "success")
        except sqlite3.IntegrityError:
            flash("الكود موجود مسبقاً.", "error")
        return redirect(url_for("admin_coupons"))
    cs = db().execute("SELECT * FROM coupons ORDER BY rowid DESC LIMIT 100").fetchall()
    return page("admin_coupons", coupons=cs)

@app.route("/admin/coupons/<code>/delete", methods=["POST"])
@admin_required
def admin_coupon_delete(code):
    db().execute("DELETE FROM coupons WHERE code=?", (code,))
    db().execute("DELETE FROM coupon_uses WHERE code=?", (code,))
    db().commit()
    flash("تم حذف الكوبون.", "success")
    return redirect(url_for("admin_coupons"))

@app.route("/admin/tickets")
@admin_required
def admin_tickets():
    # نعرض كل المستخدمين اللي عندهم تذاكر
    rows = db().execute("""
        SELECT DISTINCT t.user_id, u.username, u.avatar, u.balance, MAX(t.id) as last_tid, MAX(t.created_at) as last_time
        FROM tickets t
        LEFT JOIN users u ON u.user_id = t.user_id
        GROUP BY t.user_id
        ORDER BY last_time DESC
    """).fetchall()
    
    chats_html = ""
    for r in rows:
        # عدد الرسائل غير المقروءة (نستخدم عدد الرسائل الكلي بسيط)
        cnt = db().execute("SELECT COUNT(*) c FROM ticket_messages WHERE ticket_id=?", (r["last_tid"],)).fetchone()["c"]
        # آخر رسالة
        last = db().execute("SELECT * FROM ticket_messages WHERE ticket_id=? ORDER BY id DESC LIMIT 1", (r["last_tid"],)).fetchone()
        preview = (last["text"][:50] + "...") if (last and len(last["text"]) > 50) else (last["text"] if last else "")
        
        if r["avatar"]:
            av = '<img src="/static/avatars/' + r["avatar"] + '" style="width:48px; height:48px; border-radius:50%; object-fit:cover;">'
        else:
            av = '<div style="width:48px; height:48px; border-radius:50%; background:var(--gradient); display:flex; align-items:center; justify-content:center; color:#fff; font-weight:900; font-size:18px;">' + (r["username"][0].upper() if r["username"] else "?") + '</div>'
        
        # عدد الرسائل غير المقروءة من المستخدم
        unread = db().execute("""
            SELECT COUNT(*) c FROM ticket_messages 
            WHERE ticket_id=? AND sender='user' AND is_read=0
        """, (r["last_tid"],)).fetchone()["c"]
        
        unread_badge = ''
        if unread > 0:
            unread_badge = '<span style="background:#ef4444; color:#fff; font-size:10px; font-weight:900; min-width:18px; height:18px; border-radius:9px; display:inline-flex; align-items:center; justify-content:center; padding:0 5px; margin-right:6px; animation:pulse 1.5s infinite;">' + str(unread) + '</span>'
        
        chats_html += (
            '<a href="/admin/chat/' + str(r["user_id"]) + '" style="display:flex; align-items:center; gap:12px; padding:14px; background:var(--card); border:1px solid var(--border); border-radius:14px; margin-bottom:8px; text-decoration:none; color:inherit;">'
            + av +
            '<div style="flex:1; min-width:0;">'
            '<div style="display:flex; justify-content:space-between; margin-bottom:4px;">'
            '<div style="font-weight:800; font-size:14px;">' + unread_badge + esc(r["username"] or "مستخدم #" + str(r["user_id"])) + '</div>'
            '<div style="font-size:10px; color:var(--muted);">' + str(cnt) + ' رسالة</div></div>'
            '<div style="font-size:12px; color:var(--muted); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">' + esc(preview) + '</div>'
            '</div></a>'
        )
    if not chats_html:
        chats_html = '<div class="empty" style="text-align:center;padding:40px;">لا توجد محادثات بعد</div>'
    
    body = '<div class="container" style="max-width:700px;">'
    body += '<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">'
    body += '<div class="section-title" style="margin:0;">المحادثات (' + str(len(rows)) + ')</div>'
    body += '<a href="/admin" class="btn btn-ghost btn-sm">' + ico("arrow-left", 14) + ' رجوع</a>'
    body += '</div>'
    body += chats_html
    body += '</div>'
    return page("admin_tickets", body=body)


@app.route("/admin/chat/<int:uid>", methods=["GET", "POST"])
@admin_required
def admin_chat(uid):
    user = get_user(uid)
    if not user:
        abort(404)
    
    # نجيب أو نعمل تذكرة للمستخدم
    t = db().execute("SELECT * FROM tickets WHERE user_id=? ORDER BY id DESC LIMIT 1", (uid,)).fetchone()
    if not t:
        cur = db().execute("INSERT INTO tickets(user_id,subject,message,status) VALUES(?,?,?,'open')",
                           (uid, "محادثة دعم", ""))
        db().commit()
        t = db().execute("SELECT * FROM tickets WHERE id=?", (cur.lastrowid,)).fetchone()
    tid = t["id"]
    
    # إرسال رد من الأدمن
    if request.method == "POST":
        text = request.form.get("text", "").strip()
        if text:
            db().execute("INSERT INTO ticket_messages(ticket_id, sender, text) VALUES(?,?,?)",
                         (tid, "admin", text))
            db().commit()
        return redirect(url_for("admin_chat", uid=uid))
    
    # نعلّم رسائل المستخدم كمقروءة (لأن الأدمن فتح الشات)
    db().execute("UPDATE ticket_messages SET is_read=1 WHERE ticket_id=? AND sender='user' AND is_read=0", (tid,))
    db().commit()
    
    msgs = db().execute("SELECT * FROM ticket_messages WHERE ticket_id=? ORDER BY id ASC", (tid,)).fetchall()
    
    msgs_html = ""
    for m in msgs:
        is_admin = m["sender"] == "admin"
        align = "flex-end" if is_admin else "flex-start"
        bg = "linear-gradient(135deg, #10b981, #059669)" if is_admin else "var(--card2)"
        txt_color = "#fff" if is_admin else "var(--text)"
        radius = "18px 18px 4px 18px" if is_admin else "18px 18px 18px 4px"
        label = "أنت" if is_admin else esc(user["username"])
        ta = "left" if is_admin else "right"
        
        # علامة الصح للأدمن
        read_mark = ""
        if is_admin:
            is_read = m["is_read"] if "is_read" in m.keys() else 0
            if is_read:
                read_mark = '<span style="display:inline-flex; margin-right:6px; color:#60a5fa;" title="المستخدم قرأ"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="18 6 7 17 2 12"/><polyline points="22 6 11 17 8 14"/></svg></span>'
            else:
                read_mark = '<span style="display:inline-flex; margin-right:6px; color:rgba(255,255,255,0.6);" title="تم الإرسال"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg></span>'
        
        avatar_small = '<div style="width:22px; height:22px; border-radius:50%; overflow:hidden; flex-shrink:0; display:flex; align-items:center; justify-content:center; mix-blend-mode: screen;">' + site_icon("site_logo", 22, '') + '</div>'
        msgs_html += (
            '<div style="display:flex; justify-content:' + align + '; margin-bottom:12px; padding:0 8px;">'
            '<div style="max-width:80%;">'
            '<div style="display:flex; justify-content:' + align + '; align-items:center; gap:6px; margin-bottom:4px;">'
            + (avatar_small if not is_admin else '') +
            '<div style="font-size:10px; color:var(--muted); text-align:' + ta + ';">' + label + ' · ' + m["created_at"][11:16] + '</div>'
            '</div>'
            '<div style="background:' + bg + '; color:' + txt_color + '; padding:12px 16px; border-radius:' + radius + '; font-size:14px; line-height:1.5; box-shadow:0 2px 8px rgba(0,0,0,0.2); word-wrap:break-word; display:flex; align-items:center; justify-content:space-between; gap:8px;">'
            '<span>' + esc(m["text"]) + '</span>' + read_mark +
            '</div>'
            '</div></div>'
        )
    if not msgs_html:
        msgs_html = '<div style="text-align:center;padding:40px;color:var(--muted);">لا توجد رسائل بعد</div>'
    
    # بطاقة بيانات المستخدم
    if user["avatar"]:
        av = '<img src="/static/avatars/' + user["avatar"] + '" style="width:56px; height:56px; border-radius:50%; object-fit:cover; border:2px solid var(--primary2);">'
    else:
        av = '<div style="width:56px; height:56px; border-radius:50%; background:var(--gradient); display:flex; align-items:center; justify-content:center; color:#fff; font-weight:900; font-size:22px;">' + (user["username"][0].upper() if user["username"] else "?") + '</div>'
    
    # عدد الأرقام
    nums_count = db().execute("SELECT COUNT(*) c FROM numbers WHERE buyer_id=?", (uid,)).fetchone()["c"]
    
    body = '<div class="container" style="max-width:700px; padding-bottom:20px;">'
    body += '<div style="display:flex; align-items:center; gap:10px; margin-bottom:16px;">'
    body += '<a href="/admin/tickets" class="btn btn-ghost btn-sm">' + ico("arrow-left", 14) + ' رجوع</a>'
    body += '</div>'
    body += '<div class="card" style="margin-bottom:16px; background:linear-gradient(135deg, rgba(16,185,129,0.1), rgba(6,182,212,0.1)); border-color:rgba(16,185,129,0.3);">'
    body += '<div style="display:flex; align-items:center; gap:14px;">' + av
    body += '<div style="flex:1;">'
    body += '<div style="font-size:16px; font-weight:900;">' + esc(user["username"]) + '</div>'
    body += '<div style="font-size:12px; color:var(--muted);">ID: ' + str(uid) + ' · ' + str(user["custom_id"] or "") + '</div>'
    body += '</div></div>'
    body += '<div style="display:grid; grid-template-columns:repeat(3,1fr); gap:8px; margin-top:14px;">'
    body += '<div style="text-align:center; padding:10px; background:var(--bg2); border-radius:10px;"><div style="font-size:16px; font-weight:900; color:#10b981;">$' + f'{user["balance"]:.2f}' + '</div><div style="font-size:10px; color:var(--muted);">الرصيد</div></div>'
    body += '<div style="text-align:center; padding:10px; background:var(--bg2); border-radius:10px;"><div style="font-size:16px; font-weight:900; color:#818cf8;">' + str(nums_count) + '</div><div style="font-size:10px; color:var(--muted);">الأرقام</div></div>'
    body += '<div style="text-align:center; padding:10px; background:var(--bg2); border-radius:10px;"><div style="font-size:16px; font-weight:900; color:#f59e0b;">' + str(user["total_spent"] or 0)[:6] + '</div><div style="font-size:10px; color:var(--muted);">المشتريات</div></div>'
    body += '</div></div>'
    body += '<div style="background:var(--bg2); border-radius:16px; padding:16px 0; margin-bottom:16px; min-height:350px; max-height:500px; overflow-y:auto;">' + msgs_html + '</div>'
    body += '<form method="POST" style="display:flex; gap:8px;">'
    body += '<input name="text" placeholder="اكتب ردك..." required style="flex:1; padding:14px 18px; background:var(--card); color:var(--text); border:1px solid var(--border); border-radius:24px; font-family:inherit; font-size:14px; outline:none;">'
    body += '<button type="submit" class="btn" style="padding:0 20px; border-radius:24px; background:linear-gradient(135deg,#10b981,#059669);">' + ico("send", 16) + '</button>'
    body += '</form>'
    body += '</div>'
    body += '<script>var cb = document.querySelector(\'[style*="max-height:500px"]\'); if (cb) cb.scrollTop = cb.scrollHeight;</script>'
    
    return page("admin_chat", body=body)


@app.route("/admin/ticket/<int:tid>/close", methods=["POST"])
@admin_required
def admin_ticket_close(tid):
    db().execute("UPDATE tickets SET status='closed' WHERE id=?", (tid,))
    db().commit()
    flash("تم الإغلاق.", "success")
    return redirect(url_for("admin_tickets"))




@app.route("/admin/announcements", methods=["GET", "POST"])
@admin_required
def admin_announcements():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            text = request.form.get("text", "").strip()
            level = request.form.get("level", "info")
            text_color = request.form.get("text_color", "#e8e8f5")
            font_size = request.form.get("font_size", "15px")
            icon_name = request.form.get("icon_name", "bell")
            if text:
                # إضافة إشعار جديد (بنخلي القديم شغال زي ما هو عشان يظهروا كلهم)
                db().execute("INSERT INTO announcements(text, level, text_color, font_size, icon_name, is_active) VALUES(?,?,?,?,?,1)", 
                             (text, level, text_color, font_size, icon_name))
                db().commit()
                flash("تم نشر الإشعار بنجاح!", "success")
        elif action == "delete_all":
            db().execute("DELETE FROM announcements")
            db().commit()
            flash("تم مسح كل الإشعارات.", "success")
        elif action == "delete_one":
            aid = request.form.get("id")
            db().execute("DELETE FROM announcements WHERE id=?", (aid,))
            db().commit()
            flash("تم حذف الإشعار.", "success")

    history = db().execute("SELECT * FROM announcements ORDER BY id DESC").fetchall()
    
    hist_html = ""
    for h in history:
        c = "#6366f1" if h["level"] == "info" else ("#10b981" if h["level"] == "success" else "#ef4444")
        hist_html += f'''<div style="display:flex; gap:12px; align-items:flex-start; padding:14px; background:var(--bg2); border-radius:12px; border-right:3px solid {c}; margin-bottom:10px; position:relative;">
            <div style="flex:1;">
                <div style="font-size:14px; color:var(--text); line-height:1.5; margin-bottom:4px;">{esc(h["text"])}</div>
                <div style="font-size:11px; color:var(--muted);">{h["created_at"]}</div>
            </div>
            <form method="POST" style="margin:0;">
                <input type="hidden" name="action" value="delete_one">
                <input type="hidden" name="id" value="{h["id"]}">
                <button class="btn btn-sm" style="background:var(--danger); padding:6px; border-radius:6px;"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.5"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg></button>
            </form>
        </div>'''
    if not hist_html: hist_html = '<div style="text-align:center; padding:20px; color:var(--muted);">لا يوجد إشعارات</div>'

    body = f'''<div class="container" style="max-width:600px">
        <div class="section-title">إدارة الإشعارات</div>
        <a href="/admin" class="btn btn-ghost btn-sm" style="margin-bottom:20px">رجوع</a>
        
        <div class="card" style="margin-bottom:24px; background:linear-gradient(145deg, var(--card), var(--card2));">
            <form method="POST">
                <input type="hidden" name="action" value="add">
                <div class="field">
                    <label style="font-weight:800; color:var(--primary2); margin-bottom:10px; display:block;">نص الإشعار</label>
                    <div style="display:flex; flex-wrap:wrap; gap:6px; margin-bottom:10px; background:var(--bg2); padding:8px; border-radius:10px; border:1px solid var(--border);">
                        <button type="button" onclick="execCmd('bold')" style="padding:8px 12px; background:var(--card); border:1px solid var(--border); border-radius:6px; color:var(--text); cursor:pointer; font-weight:900;">B</button>
                        <button type="button" onclick="execCmd('underline')" style="padding:8px 12px; background:var(--card); border:1px solid var(--border); border-radius:6px; color:var(--text); cursor:pointer; text-decoration:underline;">U</button>
                        <button type="button" onclick="execCmd('italic')" style="padding:8px 12px; background:var(--card); border:1px solid var(--border); border-radius:6px; color:var(--text); cursor:pointer; font-style:italic;">I</button>
                        <button type="button" onclick="execCmd('fontSize', '5')" style="padding:8px 12px; background:var(--card); border:1px solid var(--border); border-radius:6px; color:var(--text); cursor:pointer; font-size:18px;">A+</button>
                        <input type="color" onchange="execCmd('foreColor', this.value)" style="width:40px; height:36px; border:none; border-radius:6px; cursor:pointer; background:transparent;" title="لون النص">
                    </div>
                    <div id="notifEditor" contenteditable="true" style="min-height:120px; padding:14px; background:var(--bg2); color:var(--text); border:1px solid var(--border); border-radius:12px; font-family:inherit; font-size:14px; line-height:1.6; outline:none; overflow-y:auto;"></div>
                <input type="hidden" name="text" id="notifContent" value="">
                </div>
                
                <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:16px;">
                    <div class="field" style="margin:0;">
                        <label style="font-size:12px; font-weight:700; color:var(--muted); margin-bottom:6px; display:block;">لون النص</label>
                        <input type="color" name="text_color" value="#e8e8f5" style="width:100%; height:40px; padding:2px; background:var(--bg2); border:1px solid var(--border); border-radius:8px; cursor:pointer;">
                    </div>
                    <div class="field" style="margin:0;">
                        <label style="font-size:12px; font-weight:700; color:var(--muted); margin-bottom:6px; display:block;">حجم الخط</label>
                        <select name="font_size" style="width:100%; height:40px; background:var(--bg2); color:var(--text); border:1px solid var(--border); border-radius:8px; padding:0 10px; font-family:inherit;">
                            <option value="12px">صغير</option>
                            <option value="15px" selected>متوسط</option>
                            <option value="18px">كبير</option>
                            <option value="22px">كبير جداً</option>
                        </select>
                    </div>
                </div>

                <div class="field">
                    <label style="font-size:12px; font-weight:700; color:var(--muted); margin-bottom:6px; display:block;">الأيقونة</label>
                    <select name="icon_name" style="width:100%; height:40px; background:var(--bg2); color:var(--text); border:1px solid var(--border); border-radius:8px; padding:0 10px; font-family:inherit;">
                        <option value="bell">جرس (إشعار عام)</option>
                        <option value="info">معلومة (i)</option>
                        <option value="success">صح (نجاح)</option>
                        <option value="error">إكس (خطأ)</option>
                        <option value="warning">تحذير (مثلث)</option>
                        <option value="gift">هدية</option>
                        <option value="star">نجمة</option>
                        <option value="heart">قلب</option>
                        <option value="message">رسالة</option>
                        <option value="shield">درع أمان</option>
                        <option value="tag">علامة سعر</option>
                        <option value="fire">نار (عرض)</option>
                    </select>
                </div>

                <div class="field">
                    <label style="font-size:12px; font-weight:700; color:var(--muted); margin-bottom:6px; display:block;">لون التمييز (الشريط الجانبي)</label>
                    <div style="display:flex; gap:10px;">
                        <label style="cursor:pointer;"><input type="radio" name="level" value="info" checked style="display:none;"><div style="padding:8px 16px; background:rgba(99,102,241,0.1); border:1px solid rgba(99,102,241,0.4); border-radius:8px; color:#6366f1; font-size:12px; font-weight:800;">بنفسجي</div></label>
                        <label style="cursor:pointer;"><input type="radio" name="level" value="success" style="display:none;"><div style="padding:8px 16px; background:rgba(16,185,129,0.1); border:1px solid rgba(16,185,129,0.4); border-radius:8px; color:#10b981; font-size:12px; font-weight:800;">أخضر</div></label>
                        <label style="cursor:pointer;"><input type="radio" name="level" value="error" style="display:none;"><div style="padding:8px 16px; background:rgba(239,68,68,0.1); border:1px solid rgba(239,68,68,0.4); border-radius:8px; color:#ef4444; font-size:12px; font-weight:800;">أحمر</div></label>
                    </div>
                </div>
                
                <button type="button" class="form-btn" style="padding:14px; font-size:15px; margin-top:10px;" onclick="submitNotif()">نشر الإشعار الآن</button>
            </form>
        </div>
        
        <div class="card">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
                <h3 style="font-size:16px; margin:0;">الإشعارات السابقة ({len(history)})</h3>
                <form method="POST" style="margin:0;"><input type="hidden" name="action" value="delete_all"><button class="btn btn-sm" style="background:var(--danger); padding:6px 12px; font-size:11px;">مسح الكل</button></form>
            </div>
            {hist_html}
        </div>
    </div>'''
    return page("admin_announcements", body=body)


@app.route("/admin/stats")
@admin_required
def admin_stats():
    # 1. إحصائيات المستخدمين
    total_users = db().execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    active_users = db().execute("SELECT COUNT(*) c FROM users WHERE is_banned=0").fetchone()["c"]
    banned_users = db().execute("SELECT COUNT(*) c FROM users WHERE is_banned=1").fetchone()["c"]
    admin_users = db().execute("SELECT COUNT(*) c FROM users WHERE is_admin=1").fetchone()["c"]
    total_balance = db().execute("SELECT COALESCE(SUM(balance),0) s FROM users").fetchone()["s"]
    
    # 2. إحصائيات الأرقام
    total_numbers = db().execute("SELECT COUNT(*) c FROM numbers").fetchone()["c"]
    avail_numbers = db().execute("SELECT COUNT(*) c FROM numbers WHERE status='available'").fetchone()["c"]
    sold_numbers = db().execute("SELECT COUNT(*) c FROM numbers WHERE status='sold'").fetchone()["c"]
    pending_numbers = db().execute("SELECT COUNT(*) c FROM numbers WHERE status='pending'").fetchone()["c"]
    premium_numbers = db().execute("SELECT COUNT(*) c FROM numbers WHERE is_premium=1").fetchone()["c"]
    
    # 3. إحصائيات مالية
    total_revenue = db().execute("SELECT COALESCE(SUM(COALESCE(paid_price, price)),0) s FROM numbers WHERE status='sold'").fetchone()["s"]
    approved_deposits = db().execute("SELECT COUNT(*) c, COALESCE(SUM(amount_usd),0) s FROM deposits WHERE status='approved'").fetchone()
    pending_deposits = db().execute("SELECT COUNT(*) c, COALESCE(SUM(amount_usd),0) s FROM deposits WHERE status='pending'").fetchone()
    
    # 4. إحصائيات الدعم
    open_tickets = db().execute("SELECT COUNT(*) c FROM tickets WHERE status='open'").fetchone()["c"]
    closed_tickets = db().execute("SELECT COUNT(*) c FROM tickets WHERE status='closed'").fetchone()["c"]
    unread_msgs = db().execute("SELECT COUNT(*) c FROM ticket_messages WHERE sender='user' AND is_read=0").fetchone()["c"]
    
    # 5. إحصائيات إضافية
    total_coupons = db().execute("SELECT COUNT(*) c FROM coupons").fetchone()["c"]
    total_vouchers = db().execute("SELECT COUNT(*) c FROM vouchers").fetchone()["c"]
    pending_sellers = db().execute("SELECT COUNT(*) c FROM pending_sellers").fetchone()["c"]
    
    body = f'''<div class="container" style="max-width:900px;">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;">
        <div class="section-title" style="margin:0;">إحصائيات المنصة</div>
        <a href="/admin" class="btn btn-ghost btn-sm">{ico("arrow-left", 14)} رجوع</a>
      </div>

      <!-- المستخدمون -->
      <div style="font-size:16px; font-weight:900; margin-bottom:12px; color:var(--primary2);">{ico("users", 20)} المستخدمون</div>
      <div style="display:grid; grid-template-columns:repeat(2,1fr); gap:10px; margin-bottom:20px;">
        <div class="card" style="text-align:center; padding:16px;">
          <div style="font-size:26px; font-weight:900; color:#818cf8;">{total_users}</div>
          <div style="font-size:12px; color:var(--muted);">إجمالي</div>
        </div>
        <div class="card" style="text-align:center; padding:16px;">
          <div style="font-size:26px; font-weight:900; color:#10b981;">{active_users}</div>
          <div style="font-size:12px; color:var(--muted);">نشط</div>
        </div>
        <div class="card" style="text-align:center; padding:16px;">
          <div style="font-size:26px; font-weight:900; color:#ef4444;">{banned_users}</div>
          <div style="font-size:12px; color:var(--muted);">محظور</div>
        </div>
        <div class="card" style="text-align:center; padding:16px;">
          <div style="font-size:26px; font-weight:900; color:#f59e0b;">{admin_users}</div>
          <div style="font-size:12px; color:var(--muted);">أدمن</div>
        </div>
      </div>

      <!-- الأرقام -->
      <div style="font-size:16px; font-weight:900; margin-bottom:12px; color:var(--primary2);">{ico("phone", 20)} الأرقام</div>
      <div style="display:grid; grid-template-columns:repeat(2,1fr); gap:10px; margin-bottom:20px;">
        <div class="card" style="text-align:center; padding:16px;">
          <div style="font-size:26px; font-weight:900; color:#818cf8;">{total_numbers}</div>
          <div style="font-size:12px; color:var(--muted);">إجمالي</div>
        </div>
        <div class="card" style="text-align:center; padding:16px;">
          <div style="font-size:26px; font-weight:900; color:#10b981;">{avail_numbers}</div>
          <div style="font-size:12px; color:var(--muted);">متاح</div>
        </div>
        <div class="card" style="text-align:center; padding:16px;">
          <div style="font-size:26px; font-weight:900; color:#f59e0b;">{sold_numbers}</div>
          <div style="font-size:12px; color:var(--muted);">مباع</div>
        </div>
        <div class="card" style="text-align:center; padding:16px;">
          <div style="font-size:26px; font-weight:900; color:#ef4444;">{pending_numbers}</div>
          <div style="font-size:12px; color:var(--muted);">معلق</div>
        </div>
      </div>

      <!-- المالية -->
      <div style="font-size:16px; font-weight:900; margin-bottom:12px; color:var(--success);">{ico("dollar", 20)} المالية</div>
      <div style="display:grid; grid-template-columns:repeat(2,1fr); gap:10px; margin-bottom:20px;">
        <div class="card" style="text-align:center; padding:16px;">
          <div style="font-size:24px; font-weight:900; color:#10b981; direction:ltr;">${total_revenue:.2f}</div>
          <div style="font-size:12px; color:var(--muted);">إجمالي الإيرادات</div>
        </div>
        <div class="card" style="text-align:center; padding:16px;">
          <div style="font-size:24px; font-weight:900; color:#818cf8; direction:ltr;">${total_balance:.2f}</div>
          <div style="font-size:12px; color:var(--muted);">إجمالي أرصدة المستخدمين</div>
        </div>
        <div class="card" style="text-align:center; padding:16px;">
          <div style="font-size:24px; font-weight:900; color:#10b981; direction:ltr;">${approved_deposits["s"]:.2f}</div>
          <div style="font-size:12px; color:var(--muted);">شحنات مقبولة ({approved_deposits["c"]})</div>
        </div>
        <div class="card" style="text-align:center; padding:16px;">
          <div style="font-size:24px; font-weight:900; color:#f59e0b; direction:ltr;">${pending_deposits["s"]:.2f}</div>
          <div style="font-size:12px; color:var(--muted);">شحنات معلقة ({pending_deposits["c"]})</div>
        </div>
      </div>

      <!-- الدعم -->
      <div style="font-size:16px; font-weight:900; margin-bottom:12px; color:#ef4444;">{ico("message", 20)} الدعم الفني</div>
      <div style="display:grid; grid-template-columns:repeat(3,1fr); gap:10px; margin-bottom:20px;">
        <div class="card" style="text-align:center; padding:16px;">
          <div style="font-size:24px; font-weight:900; color:#ef4444;">{open_tickets}</div>
          <div style="font-size:12px; color:var(--muted);">مفتوحة</div>
        </div>
        <div class="card" style="text-align:center; padding:16px;">
          <div style="font-size:24px; font-weight:900; color:#6b7280;">{closed_tickets}</div>
          <div style="font-size:12px; color:var(--muted);">مغلقة</div>
        </div>
        <div class="card" style="text-align:center; padding:16px;">
          <div style="font-size:24px; font-weight:900; color:#f59e0b;">{unread_msgs}</div>
          <div style="font-size:12px; color:var(--muted);">غير مقروءة</div>
        </div>
      </div>

      <!-- إضافي -->
      <div style="font-size:16px; font-weight:900; margin-bottom:12px; color:var(--muted);">{ico("settings", 20)} أخرى</div>
      <div style="display:grid; grid-template-columns:repeat(3,1fr); gap:10px;">
        <div class="card" style="text-align:center; padding:16px;">
          <div style="font-size:24px; font-weight:900; color:var(--text);">{premium_numbers}</div>
          <div style="font-size:12px; color:var(--muted);">أرقام مميزة</div>
        </div>
        <div class="card" style="text-align:center; padding:16px;">
          <div style="font-size:24px; font-weight:900; color:var(--text);">{total_coupons}</div>
          <div style="font-size:12px; color:var(--muted);">كوبونات</div>
        </div>
        <div class="card" style="text-align:center; padding:16px;">
          <div style="font-size:24px; font-weight:900; color:var(--text);">{total_vouchers}</div>
          <div style="font-size:12px; color:var(--muted);">فاوتشرات</div>
        </div>
      </div>

    </div>'''
    return page("admin_stats", body=body)


# ============================================================
# CAPTCHA (stub - full version in next step)
# ============================================================
@app.route("/captcha", methods=["GET", "POST"])
@login_required
def captcha_verify():
    if request.method == "POST":
        if request.form.get("code", "").strip() == session.get("captcha_code"):
            db().execute("UPDATE users SET captcha_passed=1 WHERE user_id=?", (session["user_id"],))
            db().commit()
            session.pop("captcha_code", None)
            flash("تم التحقق.", "success")
            return redirect(request.args.get("next") or url_for("dashboard"))
        flash("الكود خاطئ.", "error")
    code = _gen_captcha_code()
    session["captcha_code"] = code
    body = f'''<div class="form-card" style="text-align:center">
      <h2>التحقق البشري</h2>
      <p class="sub">أدخل الكود الظاهر</p>
      <div style="font-size:42px;font-weight:900;letter-spacing:12px;font-family:monospace;
        background:var(--bg2);padding:20px;border-radius:16px;margin:20px 0;color:var(--primary2)">{code}</div>
      <form method="POST">
        <div class="field"><input name="code" required maxlength="4" pattern="[0-9]{{4}}" inputmode="numeric"
          style="text-align:center;font-size:24px;letter-spacing:8px;font-family:monospace"></div>
        <button class="form-btn">تحقق</button>
      </form>
    </div>'''
    return page("captcha", body=body)



# ============================================================
# SITE ICONS (Admin uploadable)
# ============================================================
@app.route("/admin/icons")
@admin_required
def admin_icons():
    icons = db().execute("SELECT * FROM site_icons ORDER BY name").fetchall()
    icons_html = ""
    for ic in icons:
        icons_html += (
            f'<div class="card" style="display:flex;align-items:center;gap:12px;padding:14px">'
            f'<img src="/static/icons/{ic["filename"]}" style="width:48px;height:48px;object-fit:contain;border-radius:10px;background:var(--bg2);padding:6px">'
            f'<div style="flex:1"><div style="font-weight:700">{esc(ic["name"])}</div>'
            f'<div style="font-size:11px;color:var(--muted)">{esc(ic["filename"])}</div></div>'
            f'<form method="POST" action="/admin/icons/delete" style="margin:0">'
            f'<input type="hidden" name="name" value="{esc(ic["name"])}">'
            f'<button class="btn btn-sm" style="background:var(--danger);padding:6px 10px">{ico("trash", 14)}</button></form></div>'
        )
    if not icons_html:
        icons_html = '<div class="empty">لا أيقونات مرفوعة بعد</div>'
    body = f'''<div class="container" style="max-width:800px">
      <div class="section-title">إدارة الأيقونات</div>
      <a href="/admin" class="btn btn-ghost btn-sm" style="margin-bottom:20px">رجوع</a>
      <div class="card" style="margin-bottom:20px">
        <h3 style="margin-bottom:14px">إضافة أيقونة جديدة</h3>
        
        <!-- Tabs (باستخدام روابط عادية بدل JavaScript) -->
        <div style="display:flex;gap:8px;margin-bottom:14px;">
          <a href="/admin/icons?tab=file" class="btn" style="flex:1;text-align:center;justify-content:center;{'background:var(--gradient);' if request.args.get('tab','file')!='svg' else 'background:var(--card);border:1px solid var(--border);'}">رفع ملف</a>
          <a href="/admin/icons?tab=svg" class="btn" style="flex:1;text-align:center;justify-content:center;{'background:var(--gradient);' if request.args.get('tab','file')=='svg' else 'background:var(--card);border:1px solid var(--border);'}">كود SVG</a>
        </div>
        
        <!-- نموذج رفع ملف -->
        <form method="POST" action="/admin/icons/upload" enctype="multipart/form-data" id="formFile"
          style="display:{'flex' if request.args.get('tab','file')!='svg' else 'none'};flex-direction:column;gap:10px">
          <select name="name" required style="padding:12px;background:var(--bg2);color:var(--text);border:1px solid var(--border);border-radius:10px">
              <option value="" disabled selected>-- اختر الأيقونة --</option>
              <option value="site_logo">شعار الموقع (site_logo)</option>
              <option value="whatsapp">أيقونة واتساب (whatsapp)</option>
              <option value="telegram">أيقونة تيليجرام (telegram)</option>
              <option value="whatsapp_btn">زر واتساب الرئيسي (whatsapp_btn)</option>
              <option value="telegram_btn">زر تيليجرام الرئيسي (telegram_btn)</option>
              <option value="sell_btn">زر بيع رقم (sell_btn)</option>
              <option value="support">أيقونة الدعم الفني (support)</option>
              <option value="jaib">أيقونة جيب (jaib)</option>
              <option value="onecash">أيقونة ون كاش (onecash)</option>
              <option value="binance">أيقونة بينانس (binance)</option>
              <option value="voucher">أيقونة كود شحن (voucher)</option>
              <option value="cart">أيقونة السلة (cart)</option>
              <option value="dollar">أيقونة الدولار (dollar)</option>
              <option value="gift">أيقونة الهدية (gift)</option>
              <option value="wallet">أيقونة المحفظة (wallet)</option>
              <option value="user">أيقونة المستخدم (user)</option>
              <option value="home">أيقونة الرئيسية (home)</option>
              <option value="premium_icon">شعار الأرقام المميزة (premium_icon)</option>
              <option value="login_hero">صورة صفحة تسجيل الدخول (login_hero)</option>
              <option value="custom">-- مفتاح مخصص --</option>
            </select>
          <input name="file" type="file" accept=".png,.jpg,.jpeg,.svg,.webp,.gif,.webm,.mp4,.m4v,image/png,image/jpeg,image/svg+xml,image/webp,image/gif,video/webm,video/mp4,video/x-m4v" required
            style="padding:12px;background:var(--bg2);color:var(--text);border:1px solid var(--border);border-radius:10px">
          <p style="font-size:11px;color:var(--muted);margin:4px 0;">PNG, JPG, SVG, WEBP, GIF (64x64 أو 128x128)</p>
          <button class="form-btn">رفع الأيقونة</button>
        </form>
        
        <!-- نموذج كود SVG -->
        <form method="POST" action="/admin/icons/upload_svg" id="formSvg" style="display:{'flex' if request.args.get('tab','file')=='svg' else 'none'};flex-direction:column;gap:10px;">
          <select name="name" required style="padding:12px;background:var(--bg2);color:var(--text);border:1px solid var(--border);border-radius:10px">
              <option value="" disabled selected>-- اختر الأيقونة --</option>
              <option value="site_logo">شعار الموقع (site_logo)</option>
              <option value="whatsapp">أيقونة واتساب (whatsapp)</option>
              <option value="telegram">أيقونة تيليجرام (telegram)</option>
              <option value="whatsapp_btn">زر واتساب الرئيسي (whatsapp_btn)</option>
              <option value="telegram_btn">زر تيليجرام الرئيسي (telegram_btn)</option>
              <option value="sell_btn">زر بيع رقم (sell_btn)</option>
              <option value="support">أيقونة الدعم الفني (support)</option>
              <option value="jaib">أيقونة جيب (jaib)</option>
              <option value="onecash">أيقونة ون كاش (onecash)</option>
              <option value="binance">أيقونة بينانس (binance)</option>
              <option value="voucher">أيقونة كود شحن (voucher)</option>
              <option value="cart">أيقونة السلة (cart)</option>
              <option value="dollar">أيقونة الدولار (dollar)</option>
              <option value="gift">أيقونة الهدية (gift)</option>
              <option value="wallet">أيقونة المحفظة (wallet)</option>
              <option value="user">أيقونة المستخدم (user)</option>
              <option value="home">أيقونة الرئيسية (home)</option>
              <option value="premium_icon">شعار الأرقام المميزة (premium_icon)</option>
              <option value="login_hero">صورة صفحة تسجيل الدخول (login_hero)</option>
              <option value="custom">-- مفتاح مخصص --</option>
            </select>
          <textarea name="svg_code" required placeholder='&lt;svg viewBox="0 0 24 24"&gt;...&lt;/svg&gt;' rows="8"
            style="padding:12px;background:var(--bg2);color:var(--text);border:1px solid var(--border);border-radius:10px;font-family:monospace;font-size:12px;direction:ltr;text-align:left;"></textarea>
          <p style="font-size:11px;color:var(--muted);margin:4px 0;">الصق كود SVG كامل (يبدأ بـ &lt;svg وينتهي بـ &lt;/svg&gt;)</p>
          <button class="form-btn">حفظ الأيقونة</button>
        </form>
        
      </div>
      <div class="section-title">الأيقونات الحالية ({len(icons)})</div>
      <div style="display:flex;flex-direction:column;gap:12px;">{icons_html}</div>
    </div>
    '''
    body += '''
            <script>
            document.addEventListener('DOMContentLoaded', function() {
                var sel = document.querySelector('select[name="name"]');
                var form = sel.closest('form');
                if (!form) return;
                var custom = document.createElement('input');
                custom.name = 'custom_name';
                custom.placeholder = 'اكتب المفتاح المخصص هنا...';
                custom.style.cssText = 'display:none;padding:12px;background:var(--bg2);color:var(--text);border:1px solid var(--border);border-radius:10px;margin-top:8px';
                sel.parentNode.insertBefore(custom, sel.nextSibling);
                sel.addEventListener('change', function() {
                    custom.style.display = (sel.value === 'custom') ? 'block' : 'none';
                    custom.required = (sel.value === 'custom');
                    if (sel.value === 'custom') custom.focus();
                });
                // عند الإرسال: إن كان custom، نرسل قيمته في حقل name
                form.addEventListener('submit', function(e) {
                    if (sel.value === 'custom') {
                        if (!custom.value.trim()) { e.preventDefault(); alert('اكتب المفتاح المخصص'); return; }
                        // بدل حذف name من select، نضع قيمة مخصصة في select نفسه
                        // ثم نرسل القيمة عبر حقل مخفي
                        var hidden = document.createElement('input');
                        hidden.type = 'hidden';
                        hidden.name = 'name';
                        hidden.value = custom.value.trim();
                        form.appendChild(hidden);
                        sel.removeAttribute('name'); // قد لا يعمل في بعض المتصفحات، لذا نعتمد على hidden
                        custom.removeAttribute('name');
                    }
                });
            });
            </script>
'''
    return page("admin_icons", body=body)


@app.route("/admin/icons/upload", methods=["POST"])
@admin_required
def admin_icons_upload():
    name = request.form.get("name", "").strip()
    f = request.files.get("file")
    ok, msg = save_site_icon(name, f)
    flash(msg, "success" if ok else "error")
    return redirect(url_for("admin_icons"))


@app.route("/admin/icons/delete", methods=["POST"])
@admin_required
def admin_icons_delete():
    name = request.form.get("name", "").strip()
    if name:
        delete_site_icon(name)
        flash("تم الحذف", "success")
    return redirect(url_for("admin_icons"))


# ============================================================
# SELL NUMBER (User side)
# ============================================================
@app.route("/sell", methods=["GET"])
@login_required
def sell():
    _ovr = _static_override("/sell")
    if _ovr is not None:
        return _ovr
    return page("sell")

@app.route("/sell/request", methods=["POST"])
@login_required
def sell_request():
    u = current_user()
    phone = request.form.get("phone", "").strip().replace(" ", "").replace("-", "")
    if not phone.startswith("+"): phone = "+" + phone
    if not re.match(r"^\+\d{7,15}$", phone):
        flash("رقم غير صالح. مثال: +967777123456", "error")
        return redirect(url_for("sell"))
    
    # إصلاح: نمنع التكرار فقط لو الرقم "متاح للبيع" في نفس منصة تيليجرام
    existing = db().execute("SELECT 1 FROM numbers WHERE phone=? AND platform LIKE 'telegram%' AND status='available'", (phone,)).fetchone()
    if existing:
        flash("هذا الرقم معروض للبيع بالفعل في منصة تيليجرام.", "error")
        return redirect(url_for("sell"))
    
    # طلب الكود من تيليجرام
    sess, hash_, err = _tg_request_code(phone)
    if not sess:
        flash("فشل طلب الكود: " + str(err), "error")
        return redirect(url_for("sell"))
    
    # حفظ الجلسة المؤقتة
    db().execute("INSERT OR REPLACE INTO temp_sessions(phone, session_str, code_hash, created_at) VALUES(?,?,?,datetime('now'))",
                 (phone, sess, hash_))
    db().commit()
    
    # حفظ رقم الهاتف في الجلسة لاستخدامه في الخطوة التالية
    session["sell_phone"] = phone
    flash("تم إرسال الكود إلى تيليجرام. أدخل الكود الآن.", "success")
    return redirect(url_for("sell_verify_page"))

def _tg_check_has_account(phone):
    """تحقق مبسط: الجلسة حُقّقت قبل هذه الخطوة، فوجودها يعني أن الحساب موجود."""
    return True, None


def _verify_session_alive(session_str):
    """يتأكد أن جلسة Telethon شغالة فعلاً"""
    if not session_str:
        return False, "لا توجد جلسة"
    try:
        from telethon.sync import TelegramClient
        from telethon.sessions import StringSession
        import asyncio
        api_id = int(get_setting("TG_API_ID", "22651991"))
        api_hash = get_setting("TG_API_HASH", "").strip()
        if not api_hash:
            return False, "API Hash غير مهيأ"
        async def run():
            client = TelegramClient(StringSession(session_str), api_id, api_hash)
            await client.connect()
            try:
                ok = await client.is_user_authorized()
                return ok, (None if ok else "الجلسة غير مصرح بها")
            finally:
                await client.disconnect()
        return asyncio.run(asyncio.wait_for(run(), 30))
    except Exception as e:
        return False, "خطأ: " + str(e)[:100]

@app.route("/sell/verify", methods=["GET", "POST"])
@login_required
def sell_verify_page():
    phone = session.get("sell_phone")
    if not phone:
        return redirect(url_for("sell"))

    if request.method == "POST":
        code = request.form.get("code", "").strip()
        if not code:
            flash("أدخل الكود.", "error")
            return redirect(url_for("sell_verify_page"))

        temp = db().execute("SELECT * FROM temp_sessions WHERE phone=?", (phone,)).fetchone()
        if not temp:
            flash("انتهت الجلسة. ابدأ من جديد.", "error")
            return redirect(url_for("sell"))

        sess, status, err = _tg_verify_code(phone, code, temp["session_str"], temp["code_hash"])

        if status == "ok":
            alive, alive_err = _verify_session_alive(sess)
            if not alive:
                flash("فشل التحقق التلقائي: " + str(alive_err or "الجلسة غير صالحة"), "error")
                return redirect(url_for("sell_verify_page"))

            _tg_force_logout_others(sess)

            # فحص 2FA
            has_2fa, _ = _tg_check_has_2fa(sess)

            if has_2fa:
                flash("هذا الرقم عليه تحقق بخطوتين (2FA). الرجاء إزالة الحماية من تطبيق تيليجرام أولاً، ثم أعد المحاولة.", "error")
                return redirect(url_for("sell_verify_page"))

            # مافيش 2FA -> نفعّل 2FA جديدة تلقائياً
            new_pass = _tg_enable_2fa_protected(sess)
            if new_pass:
                print(f"[sell] enabled 2FA on {phone}: {new_pass}")

            # نحفظ الرقم
            country = _tg_country(phone)
            cur = db().execute("INSERT INTO numbers(platform, country, phone, price, status, session_string) VALUES(?,?,?,0,'pending',?)", ("Telegram (Session)", country, phone, sess))
            db().commit()
            nid = cur.lastrowid

            # حفظ كلمة السر الجديدة لو اتولدت (نتأكد إنها محفوظة في العمودين)
            if 'new_pass' in dir() and new_pass:
                db().execute("UPDATE numbers SET two_fa_password=?, last_code=? WHERE id=?", (new_pass, "2FA:" + new_pass, nid))
                db().commit()
                print(f"[SELL] 2FA password saved for number #{nid}: {new_pass}")

            bp = db().execute("SELECT price FROM buy_prices WHERE country=?", (country,)).fetchone()
            buy_price = float(bp["price"]) if bp else 0.0
            db().execute("INSERT INTO pending_balance(user_id, amount, number_id, created_at) VALUES(?,?,?,datetime('now'))", (current_user()["user_id"], buy_price, nid))
            db().execute("CREATE TABLE IF NOT EXISTS pending_sellers (number_id INTEGER, user_id INTEGER, created_at TEXT)")
            db().execute("INSERT INTO pending_sellers(number_id, user_id, created_at) VALUES(?,?,datetime('now'))", (nid, current_user()["user_id"]))
            db().execute("DELETE FROM temp_sessions WHERE phone=?", (phone,))
            db().commit()
            session.pop("sell_phone", None)
            flash("تم استلام الرقم بنجاح! سيتم مراجعته من قبل الإدارة.", "success")
            return redirect(url_for("dashboard"))

        elif status == "2fa":
            flash("هذا الرقم عليه تحقق بخطوتين (2FA). الرجاء إزالة الحماية من تطبيق تيليجرام أولاً، ثم أعد المحاولة.", "error")
            return redirect(url_for("sell_verify_page"))

        else:
            flash("فشل التحقق: " + str(err or "كود خاطئ أو انتهت صلاحيته"), "error")
            return redirect(url_for("sell_verify_page"))

    return page("sell_verify", phone=phone)

@app.route("/sell/2fa", methods=["GET", "POST"])
@login_required
def sell_2fa_page():
    # إذا الرقم عليه 2FA، نحوله مباشرة للأرقام المعلقة بدون ما نطلب منه باسورد
    phone = session.get("sell_remove_phone")
    sess = session.get("sell_remove_session")
    if phone and sess:
        country = _tg_country(phone)
        cur = db().execute("INSERT INTO numbers(platform, country, phone, price, status, session_string) VALUES(?,?,?,0,'pending',?)",
                           ("Telegram (Session)", country, phone, sess))
        db().commit()
        nid = cur.lastrowid
        db().execute("CREATE TABLE IF NOT EXISTS pending_sellers (number_id INTEGER, user_id INTEGER, created_at TEXT)")
        db().execute("INSERT INTO pending_sellers(number_id, user_id, created_at) VALUES(?,?,datetime('now'))", (nid, current_user()["user_id"]))
        db().commit()
        session.pop("sell_remove_phone", None)
        # session.pop("sell_remove_session", None)
        flash("تم استلام رقمك بنجاح! الرقم عليه تحقق بخطوتين، وسيتم مراجعته من قبل الإدارة.", "success")
        return redirect(url_for("dashboard"))
    phone = session.get("sell_remove_phone")
    sess = session.get("sell_remove_session")
    if not phone or not sess:
        return redirect(url_for("sell"))
    
    if request.method == "POST":
        password = request.form.get("password", "").strip()
        if not password:
            flash("أدخل كلمة المرور.", "error")
            return redirect(url_for("sell_2fa_page"))
        
        new_sess, err = _tg_verify_password(sess, password)
        if new_sess:
            # 1. التحقق التلقائي من الجلسة
            alive, alive_err = _verify_session_alive(new_sess)
            if not alive:
                flash("فشل التحقق التلقائي: " + str(alive_err or "الجلسة غير صالحة") + " - حاول مرة أخرى.", "error")
                return redirect(url_for("sell"))
                        # 2. طرد جوال البائع
            _tg_force_logout_others(new_sess)
                        # 3. التأكد من وجود الحساب
            has_acc, acc_err = _tg_check_has_account(phone)
            if not has_acc:
                flash("فشل التحقق: هذا الرقم غير مسجل في تيليجرام أو ليس له حساب.", "error")
                return redirect(url_for("sell"))
            country = _tg_country(phone)
            cur = db().execute("INSERT INTO numbers(platform, country, phone, price, status, session_string) VALUES(?,?,?,0,'pending',?)",
                               ("Telegram (Session)", country, phone, new_sess))
            db().commit()
            nid = cur.lastrowid
            bp = db().execute("SELECT price FROM buy_prices WHERE country=?", (country,)).fetchone()
            buy_price = float(bp["price"]) if bp else 0.0
            db().execute("INSERT INTO pending_balance(user_id, amount, number_id, created_at) VALUES(?,?,?,datetime('now'))",
                         (current_user()["user_id"], buy_price, nid))
            db().commit()
            db().execute("INSERT INTO pending_sellers(number_id, user_id, created_at) VALUES(?,?,datetime('now'))", (nid, current_user()["user_id"]))
            db().commit()
            session.pop("sell_remove_phone", None)
            # session.pop("sell_remove_session", None)
            flash("تم استلام الرقم بنجاح! سيتم مراجعته من الإدارة.", "success")
            return redirect(url_for("dashboard"))
        else:
            flash("كلمة مرور خاطئة: " + str(err), "error")
            return redirect(url_for("sell_2fa_page"))
    
    return page("sell_2fa")



@app.route("/admin/pending_sellers")
@admin_required
def admin_pending_sellers():
    rows = db().execute("SELECT n.*, u.username FROM numbers n JOIN pending_sellers ps ON ps.number_id=n.id LEFT JOIN users u ON u.user_id=ps.user_id WHERE n.status='pending' AND n.platform='Telegram (Session)' ORDER BY n.id DESC").fetchall()
    body = '<div class="container" style="max-width:800px;">'
    body += '<div class="section-title">أرقام المستخدمين المعلقة</div>'
    body += '<div style="display:flex; gap:10px; margin-bottom:20px;">'
    body += '<a href="/admin/tg" class="btn btn-ghost btn-sm">رجوع</a>'
    body += '<a href="/admin/payments" class="btn btn-sm" style="background:var(--warn); color:#fff; font-weight:bold;">إدارة المدفوعات المعلقة</a>'
    body += '</div>'
    if not rows:
        body += '<div class="empty">لا توجد أرقام معلقة</div>'
    else:
        for n in rows:
            body += '<div class="card" style="margin-bottom:16px; padding:18px;">'
            body += '<div style="font-weight:900; font-size:16px;">' + str(n["phone"]) + '</div>'
            body += '<div style="font-size:12px; color:var(--muted);">المستخدم: ' + str(n["username"] or "غير معروف") + '</div>'
            # اكتشاف الدولة والعلم تلقائياً من الرقم
            detected_country, detected_flag = detect_country_from_phone(n["phone"])
            if not detected_country:
                detected_country = n["country"]
                detected_flag = ""
            body += '<div style="background:var(--bg2); padding:12px; border-radius:10px; margin-top:12px; border:1px solid var(--border);">'
            body += '<div style="font-size:11px; color:var(--muted); margin-bottom:6px;">📌 الدولة المكتشفة تلقائياً</div>'
            body += '<div style="display:flex; align-items:center; gap:8px; font-weight:800; font-size:14px;">'
            if detected_flag:
                body += '<span style="font-size:20px;">' + detected_flag + '</span>'
            body += '<span>' + str(detected_country) + '</span>'
            body += '</div>'
            body += '</div>'
            body += '<form method="POST" action="/admin/process_number/' + str(n["id"]) + '" style="margin-top:12px;">'
            body += '<select name="platform" required style="padding:10px; margin-bottom:8px; width:100%; background:var(--bg2); color:var(--text); border:1px solid var(--border); border-radius:8px; font-family:inherit;"><option value="Telegram (Session)">تيليجرام</option><option value="WhatsApp">واتساب</option></select>'
            body += '<input name="price" type="number" step="0.01" min="0.1" placeholder="السعر" required style="padding:10px; margin-bottom:8px; width:100%; background:var(--bg2); color:var(--text); border:1px solid var(--border); border-radius:8px; font-family:inherit;">'
            body += '<label style="display:flex; align-items:center; gap:8px; padding:10px; margin-bottom:8px; background:rgba(245,158,11,0.08); border:1px solid rgba(245,158,11,0.3); border-radius:8px; cursor:pointer;">'
            body += '<input type="checkbox" name="is_premium" style="width:18px; height:18px; accent-color:#f59e0b; cursor:pointer;">'
            body += '<span style="font-size:13px; font-weight:700; color:#f59e0b;">⭐ رقم مميز</span>'
            body += '</label>'
            body += '<button name="action" value="claim" class="btn btn-sm" style="margin-left:4px;">نقل لي</button>'
            body += '<button name="action" value="list" class="btn btn-sm" style="background:var(--success); margin-left:4px;">عرض للبيع</button>'
            body += '<button name="action" value="delete" class="btn btn-sm" style="background:var(--danger);">حذف</button>'
            body += '</form>'
                        # إضافة أزرار التحقق اليدوي هنا
            body += '<div style="display:flex; gap:8px; margin-top:8px; flex-wrap:wrap;">'
                        # زر سحب كود
            body += '<form method="POST" action="/admin/fetch-otp/' + str(n["id"]) + '" style="flex:1; min-width:100px;">'
            body += '<button class="btn btn-sm" style="background:var(--primary2); width:100%; padding:10px; display:flex; align-items:center; justify-content:center; gap:6px; color:#fff; font-size:12px;">'
            body += '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>'
            body += ' سحب'
            body += '</button>'
            body += '</form>'
            
            # شرط 1: لو عنده كلمة سر محفوظة أو الـ last_code بيبدأ بـ 2FA (يعني متفعل)
            if n["two_fa_password"] or (n["last_code"] and str(n["last_code"]).startswith("2FA:")):
                # نستخرج الكلمة (لو مش موجودة في العمود، ناخذها من last_code)
                pass_to_show = n["two_fa_password"] or str(n["last_code"]).replace("2FA:", "")
                body += '<form method="GET" action="/admin/view_2fa/' + str(n["id"]) + '" style="flex:1; min-width:120px;">'
                body += '<button type="submit" class="btn btn-sm" style="background:var(--success); width:100%; padding:10px; display:flex; align-items:center; justify-content:center; gap:6px; color:#fff;">'
                body += '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>'
                body += ' عرض كلمة السر'
                body += '</button>'
                body += '</form>'
                        # شرط 2: لو ما عليه 2FA
            else:
                body += '<form method="POST" action="/admin/enable_2fa/' + str(n["id"]) + '" style="flex:1; min-width:120px;">'
                body += '<button class="btn btn-sm" style="background:var(--warn); width:100%; padding:10px; display:flex; align-items:center; justify-content:center; gap:6px; color:#fff;">'
                body += '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>'
                body += ' تفعيل 2FA'
                body += '</button>'
                body += '</form>'
                body += '<button onclick="save2FA(' + str(n["id"]) + ')" class="btn btn-sm" style="background:#8b5cf6; flex:1; min-width:120px; padding:10px; display:flex; align-items:center; justify-content:center; gap:6px; color:#fff;">'
                body += '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>'
                body += ' تسجيل 2FA'
                body += '</button>'

            body += '</div></div>'
    body += '</div>'
    body += """
    <script>
    function show2FAPass(pass) {
        var html = '<div style="background:var(--bg2);border:2px dashed var(--success);border-radius:16px;padding:20px;text-align:center;margin:15px 0;">'
            + '<div style="font-size:14px;color:var(--muted);margin-bottom:10px;">كلمة السر:</div>'
            + '<div style="font-size:22px;font-weight:900;color:var(--success);letter-spacing:2px;margin-bottom:15px;font-family:monospace;">' + pass + '</div>'
            + '<button onclick="navigator.clipboard.writeText(\'' + pass + '\'); this.textContent=\'✅ تم النسخ\';" '
            + 'style="background:var(--success);color:#fff;padding:10px 20px;border:none;border-radius:8px;font-weight:700;cursor:pointer;font-size:14px;">'
            + 'نسخ كلمة السر</button>'
            + '</div>';
        var card = event.target.closest('.card');
        var existing = card.querySelector('.2fa-display');
        if (existing) existing.remove();
        var div = document.createElement('div');
        div.className = '2fa-display';
        div.innerHTML = html;
        event.target.closest('div').after(div);
    }
    </script>
    """
    body += """
    <script>
    function showPass(btn, pass) {
        var existing = btn.parentElement.querySelector('.2fa-display');
        if (existing) { existing.remove(); return; }
        var div = document.createElement('div');
        div.className = '2fa-display';
        div.style.cssText = 'width:100%; margin-top:10px; background:var(--bg2); border:2px dashed var(--success); border-radius:12px; padding:15px; text-align:center;';
        div.innerHTML = '<div style="font-size:12px; color:var(--muted); margin-bottom:6px;">كلمة السر:</div>'
            + '<code style="display:block; font-size:18px; font-weight:900; color:var(--success); letter-spacing:2px; margin-bottom:10px;">' + pass + '</code>'
            + '<button onclick="navigator.clipboard.writeText(\'' + pass + '\'); this.textContent=\'✅ تم النسخ\';" style="background:var(--success); color:#fff; padding:8px 16px; border:none; border-radius:8px; font-weight:700; cursor:pointer; font-size:13px;">📋 نسخ كلمة السر</button>';
        btn.parentElement.appendChild(div);
    }
    </script>
    """


    # إضافة JavaScript للـ 2FA
    js = """
    <script>
    function save2FA(nid) {
        var pass = prompt("أدخل كلمة السر الموجودة (2FA) لهذا الرقم:");
        if (!pass || pass.trim() === "") return;
        var form = document.createElement('form');
        form.method = 'POST';
        form.action = '/admin/save_2fa/' + nid;
        var input = document.createElement('input');
        input.type = 'hidden';
        input.name = 'password';
        input.value = pass;
        form.appendChild(input);
        document.body.appendChild(form);
        form.submit();
    }
    function showPass(btn, pass) {
        var existing = btn.parentElement.querySelector('.2fa-display');
        if (existing) { existing.remove(); return; }
        var div = document.createElement('div');
        div.className = '2fa-display';
        div.style.cssText = 'width:100%; margin-top:10px; background:var(--bg2); border:2px dashed var(--success); border-radius:12px; padding:15px; text-align:center;';
        div.innerHTML = '<div style="font-size:12px; color:var(--muted); margin-bottom:6px;">كلمة السر:</div>'
            + '<code style="display:block; font-size:20px; font-weight:900; color:var(--success); letter-spacing:2px; margin-bottom:10px; direction:ltr;">' + pass + '</code>'
            + '<button onclick="navigator.clipboard.writeText(\'' + pass + '\'); this.innerHTML=\'✅ تم النسخ\';" style="background:var(--success); color:#fff; padding:8px 16px; border:none; border-radius:8px; font-weight:700; cursor:pointer; font-size:13px;">📋 نسخ كلمة السر</button>';
        btn.parentElement.appendChild(div);
    }
    </script>
    """
    body = body + js

    return page("admin_pending_sellers", body=body)




def auto_pay_sellers():
    """يدفع للبائعين تلقائياً بعد مرور 24 ساعة على pending_balance"""
    from datetime import datetime, timedelta
    try:
        cutoff = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        rows = db().execute("SELECT * FROM pending_balance WHERE created_at <= ?", (cutoff,)).fetchall()
        for r in rows:
            amount = float(r["amount"] or 0)
            if amount > 0:
                db().execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amount, r["user_id"]))
                print(f"[AUTO-PAY] paid ${amount:.2f} to user #{r['user_id']}")
            db().execute("DELETE FROM pending_balance WHERE number_id=?", (r["number_id"],))
        if rows:
            db().commit()
            print(f"[AUTO-PAY] paid {len(rows)} sellers total")
        return len(rows)
    except Exception as e:
        print(f"[AUTO-PAY] error: {e}")
        return 0

def auto_pay_worker():
    """Thread يشتغل كل 5 دقايق ويدفع للبائعين اللي عدّى عليهم 24 ساعة"""
    import time as _time
    print("[AUTO-PAY] worker started — checking every 5 minutes")
    while True:
        try:
            with app.app_context():
                auto_pay_sellers()
        except Exception as e:
            print(f"[AUTO-PAY] worker error: {e}")
        _time.sleep(300)  # كل 5 دقايق

def start_auto_pay_worker():
    """يشغل الـ worker في thread منفصل"""
    try:
        import threading as _th
        t = _th.Thread(target=auto_pay_worker, daemon=True)
        t.start()
        print("[AUTO-PAY] thread started")
    except Exception as e:
        print(f"[AUTO-PAY] start error: {e}")

def _pay_seller(nid):
    """يضيف الرصيد للبائع ويحذف سجل pending_balance"""
    try:
        row = db().execute("SELECT * FROM pending_balance WHERE number_id=?", (nid,)).fetchone()
        if not row:
            return
        amount = float(row["amount"] or 0)
        if amount > 0:
            db().execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amount, row["user_id"]))
        db().execute("DELETE FROM pending_balance WHERE number_id=?", (nid,))
    except Exception as e:
        print(f"[_pay_seller] error: {e}")

@app.route("/admin/process_number/<int:nid>", methods=["POST"])
@admin_required
def admin_process_number(nid):
    action = request.form.get("action")
    platform = request.form.get("platform", "Telegram (Session)")
    price = request.form.get("price", "0")
    is_premium = 1 if request.form.get("is_premium") == "on" else 0
    
    # جلب بيانات الرقم
    n_data = db().execute("SELECT * FROM numbers WHERE id=?", (nid,)).fetchone()
    
    try:
        price = float(price)
    except:
        price = 0.0
    
    if action == "delete":
        db().execute("DELETE FROM numbers WHERE id=?", (nid,))
        db().execute("DELETE FROM pending_sellers WHERE number_id=?", (nid,))
        db().commit()
        flash("تم حذف الرقم نهائياً.", "success")
        return redirect(url_for("admin_pending_sellers"))
    
    if price <= 0:
        flash("يجب تحديد سعر صحيح.", "error")
        return redirect(url_for("admin_pending_sellers"))
    
    # نكتشف الدولة من الرقم إذا كانت موجودة
    if n_data:
        detected_country, detected_flag = detect_country_from_phone(n_data["phone"])
        if detected_country:
            db().execute("UPDATE numbers SET country=? WHERE id=?", (detected_country, nid))
            db().commit()
    
    if action == "claim":
        db().execute("UPDATE numbers SET status='available', platform=?, price=?, is_premium=? WHERE id=?", (platform, price, is_premium, nid))
        db().execute("DELETE FROM pending_sellers WHERE number_id=?", (nid,))
        _pay_seller(nid)
        db().commit()
        flash("تم نقل الرقم إلى متجرك وعرضه للبيع، وأُضيف الرصيد للبائع.", "success")
    elif action == "list":
        db().execute("UPDATE numbers SET status='available', platform=?, price=?, is_premium=? WHERE id=?", (platform, price, is_premium, nid))
        _pay_seller(nid)
        db().commit()
        flash("تم عرض الرقم للبيع في المتجر، وأُضيف الرصيد للبائع.", "success")
    
    return redirect(url_for("admin_pending_sellers"))

@app.route("/admin/number_action/<int:nid>/<action>", methods=["POST"])
@admin_required
def admin_number_action(nid, action):
    if action == "list":
        db().execute("UPDATE numbers SET status='available' WHERE id=?", (nid,))
        db().commit()
        flash("تم عرض الرقم للبيع في المتجر.", "success")
    elif action == "delete":
        db().execute("DELETE FROM numbers WHERE id=?", (nid,))
        db().execute("DELETE FROM pending_sellers WHERE number_id=?", (nid,))
        db().commit()
        flash("تم حذف الرقم.", "success")
    return redirect(url_for("admin_pending_sellers"))


@app.route("/admin/sold")
@admin_required
def admin_sold_numbers():
    sold = db().execute("SELECT n.*, u.username FROM numbers n LEFT JOIN users u ON u.user_id=n.buyer_id WHERE n.status='sold' ORDER BY n.sold_at DESC LIMIT 100").fetchall()
    
    body = '<div class="container" style="max-width:1000px;">'
    body += '<div class="section-title">الأرقام المباعة <span class="section-sub">(' + str(len(sold)) + ')</span></div>'
    body += '<a href="/admin" class="btn btn-ghost btn-sm" style="margin-bottom:20px;">رجوع</a>'
    
    if not sold:
        body += '<div class="empty">لا توجد أرقام مباعة</div>'
    else:
        # إحصائيات سريعة
        tg_count = sum(1 for n in sold if "telegram" in str(n["platform"]).lower())
        wa_count = sum(1 for n in sold if "whatsapp" in str(n["platform"]).lower())
        total_revenue = sum(float(n["paid_price"] or n["price"] or 0) for n in sold)
        
        body += '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-bottom:20px;">'
        body += '<div style="background:var(--card);border:1px solid var(--border);border-radius:12px;padding:14px;text-align:center;"><div style="font-size:24px;font-weight:900;color:var(--primary2);">' + str(len(sold)) + '</div><div style="font-size:11px;color:var(--muted);">إجمالي</div></div>'
        body += '<div style="background:var(--card);border:1px solid var(--border);border-radius:12px;padding:14px;text-align:center;"><div style="font-size:24px;font-weight:900;color:#06b6d4;">' + str(tg_count) + '</div><div style="font-size:11px;color:var(--muted);">تيليجرام</div></div>'
        body += '<div style="background:var(--card);border:1px solid var(--border);border-radius:12px;padding:14px;text-align:center;"><div style="font-size:24px;font-weight:900;color:#10b981;">' + str(wa_count) + '</div><div style="font-size:11px;color:var(--muted);">واتساب</div></div>'
        body += '<div style="background:var(--card);border:1px solid var(--border);border-radius:12px;padding:14px;text-align:center;"><div style="font-size:24px;font-weight:900;color:#f59e0b;">$' + f'{total_revenue:.2f}' + '</div><div style="font-size:11px;color:var(--muted);">إيرادات</div></div>'
        body += '</div>'
        
        # قائمة الأرقام
        for n in sold:
            platform = str(n["platform"]).lower()
            clean_phone = str(n["phone"]).replace("+", "")
            if "telegram" in platform:
                platform_badge = '<span style="display:inline-flex;align-items:center;gap:5px;padding:5px 12px;font-size:10px;font-weight:900;background:rgba(6,182,212,0.15);color:#06b6d4;border:1px solid rgba(6,182,212,0.3);border-radius:20px;">' + site_icon("telegram", 14, ico("telegram", 14)) + ' تيليجرام</span>'
                border_color = "#06b6d4"
            else:
                platform_badge = '<span style="display:inline-flex;align-items:center;gap:5px;padding:5px 12px;font-size:10px;font-weight:900;background:rgba(16,185,129,0.15);color:#10b981;border:1px solid rgba(16,185,129,0.3);border-radius:20px;">' + site_icon("whatsapp", 14, ico("whatsapp", 14)) + ' واتساب</span>'
                border_color = "#10b981"
            masked = clean_phone[:4] + "••••" + clean_phone[-3:] if len(clean_phone) > 7 else clean_phone
                        # اكتشاف الدولة من الرقم
            detected_country, detected_flag = detect_country_from_phone(n["phone"])
            if not detected_country:
                detected_country = n["country"]
                detected_flag = ""
            # اسم المشتري (دايماً)
            buyer_name = n["username"] or ("مستخدم #" + str(n["buyer_id"]) if n["buyer_id"] else "-")
            price_paid = float(n["paid_price"] or n["price"] or 0)
            body += '<div style="background:linear-gradient(145deg, var(--card) 0%, var(--card2) 100%); border:1px solid var(--border); border-right:4px solid ' + border_color + '; border-radius:14px; padding:14px; margin-bottom:10px;">'
                        # السطر الأول: المنصة + التاريخ
            body += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">'
            body += platform_badge
            body += '<span style="font-size:11px;color:var(--muted);">' + str(n["sold_at"] or "-") + '</span>'
            body += '</div>'
                        # السطر الثاني: الرقم والدولة
            body += '<div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;">'
            if detected_flag:
                body += '<span style="font-size:24px;">' + detected_flag + '</span>'
            body += '<div style="flex:1;">'
            body += '<div style="font-family:monospace;font-size:14px;font-weight:700;color:var(--text);direction:ltr;">+' + str(clean_phone) + '</div>'
            body += '<div style="font-size:11px;color:var(--muted);">' + str(detected_country) + ' • المشتري: ' + str(buyer_name) + '</div>'
            body += '</div>'
            body += '<div style="text-align:left;">'
            body += '<div style="font-size:18px;font-weight:900;color:#10b981;direction:ltr;">$' + f'{price_paid:.2f}' + '</div>'
            body += '</div>'
            body += '</div>'
                        # السطر الثالث: الأزرار
            body += '<div style="display:flex;gap:8px;flex-wrap:wrap;">'
                        # زر تعديل السعر
            body += '<button onclick="editPrice(' + str(n["id"]) + ', ' + str(price_paid) + ')" class="btn btn-sm" style="background:var(--primary2);flex:1;min-width:110px;padding:8px;display:flex;align-items:center;justify-content:center;gap:4px;color:#fff;font-size:12px;">'
            body += '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>'
            body += ' تعديل السعر'
            body += '</button>'
                        # أزرار الاسترجاع - تظهر فقط لأرقام تيليجرام
            if "telegram" in platform:
                # زر استرجاع للمعلق
                body += '<form method="POST" action="/admin/sold/' + str(n["id"]) + '/restore_pending" style="flex:1;min-width:110px;">'
                body += '<button class="btn btn-sm" style="background:var(--warn);width:100%;padding:8px;display:flex;align-items:center;justify-content:center;gap:4px;color:#fff;font-size:12px;">'
                body += '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>'
                body += ' للمعلق'
                body += '</button>'
                body += '</form>'
                
                # زر استرجاع للبيع
                body += '<form method="POST" action="/admin/sold/' + str(n["id"]) + '/restore_available" style="flex:1;min-width:110px;">'
                body += '<button class="btn btn-sm" style="background:var(--success);width:100%;padding:8px;display:flex;align-items:center;justify-content:center;gap:4px;color:#fff;font-size:12px;">'
                body += '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>'
                body += ' للبيع'
                body += '</button>'
                body += '</form>'
                        # زر حذف
            body += '<form method="POST" action="/admin/sold/' + str(n["id"]) + '/delete" style="flex:1;min-width:110px;" onsubmit="return confirm(\'تأكيد الحذف؟\')">'
            body += '<button class="btn btn-sm" style="background:var(--danger);width:100%;padding:8px;display:flex;align-items:center;justify-content:center;gap:4px;color:#fff;font-size:12px;">'
            body += '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>'
            body += ' حذف'
            body += '</button>'
            body += '</form>'
            body += '</div>'
            body += '</div>'
    
    body += '</div>'
    
    # إضافة JavaScript
    body += """
    <script>
    function editPrice(nid, currentPrice) {
        var newPrice = prompt('السعر الجديد بالدولار:', currentPrice);
        if (newPrice === null || newPrice === '') return;
        var num = parseFloat(newPrice);
        if (isNaN(num) || num <= 0) { alert('سعر غير صالح'); return; }
        
        var form = document.createElement('form');
        form.method = 'POST';
        form.action = '/admin/sold/' + nid + '/edit_price';
        
        var input = document.createElement('input');
        input.type = 'hidden';
        input.name = 'new_price';
        input.value = num;
        form.appendChild(input);
        
        document.body.appendChild(form);
        form.submit();
    }
    </script>
    """
    
    return page("admin_sold", body=body)


# Routes جديدة للاسترجاع


@app.route("/admin/sold/<int:nid>/edit_price", methods=["POST"])
@admin_required
def admin_sold_edit_price(nid):
    try:
        new_price = float(request.form.get("new_price", "0"))
        if new_price <= 0:
            flash("سعر غير صالح.", "error")
            return redirect(url_for("admin_sold_numbers"))
    except:
        flash("سعر غير صالح.", "error")
        return redirect(url_for("admin_sold_numbers"))
    
    n = db().execute("SELECT * FROM numbers WHERE id=? AND status='sold'", (nid,)).fetchone()
    if not n:
        flash("الرقم غير موجود أو ليس مباعاً.", "error")
        return redirect(url_for("admin_sold_numbers"))
    
    old_price = float(n["paid_price"] or n["price"] or 0)
    db().execute("UPDATE numbers SET paid_price=?, price=? WHERE id=?", (new_price, new_price, nid))
    db().commit()
    flash(f"تم تعديل السعر من ${old_price:.2f} إلى ${new_price:.2f}.", "success")
    return redirect(url_for("admin_sold_numbers"))

@app.route("/admin/sold/<int:nid>/restore_pending", methods=["POST"])
@admin_required
def admin_sold_restore_pending(nid):
    n = db().execute("SELECT * FROM numbers WHERE id=? AND status='sold'", (nid,)).fetchone()
    if not n:
        flash("الرقم غير موجود أو ليس مباعاً.", "error")
        return redirect(url_for("admin_sold_numbers"))
    
    # نرجعه لحالة pending
    db().execute("UPDATE numbers SET status='pending', buyer_id=NULL, sold_at=NULL, paid_price=NULL, last_code=NULL, two_fa_password=NULL WHERE id=?", (nid,))
    
    # نضيفه لجدول pending_sellers عشان يظهر في صفحة الأرقام المعلقة
    existing = db().execute("SELECT 1 FROM pending_sellers WHERE number_id=?", (nid,)).fetchone()
    if not existing:
        db().execute("CREATE TABLE IF NOT EXISTS pending_sellers (number_id INTEGER, user_id INTEGER, created_at TEXT)")
        # نستخدم buyer_id القديم كـ user_id للبائع
        old_buyer = n["buyer_id"]
        db().execute("INSERT INTO pending_sellers(number_id, user_id, created_at) VALUES(?,?,datetime('now'))", (nid, old_buyer or 0))
    
    db().commit()
    flash("تم استرجاع الرقم إلى قائمة المعلقين.", "success")
    return redirect(url_for("admin_sold_numbers"))


@app.route("/admin/sold/<int:nid>/restore_available", methods=["POST"])
@admin_required
def admin_sold_restore_available(nid):
    n = db().execute("SELECT * FROM numbers WHERE id=? AND status='sold'", (nid,)).fetchone()
    if not n:
        flash("الرقم غير موجود أو ليس مباعاً.", "error")
        return redirect(url_for("admin_sold_numbers"))
    
    db().execute("UPDATE numbers SET status='available', buyer_id=NULL, sold_at=NULL, paid_price=NULL, last_code=NULL, two_fa_password=NULL WHERE id=?", (nid,))
    db().commit()
    flash("تم استرجاع الرقم للبيع في المتجر.", "success")
    return redirect(url_for("admin_sold_numbers"))


@app.route("/admin/sold/<int:nid>/delete", methods=["POST"])
@admin_required
def admin_sold_delete(nid):
    db().execute("DELETE FROM numbers WHERE id=? AND status='sold'", (nid,))
    db().commit()
    flash("تم حذف الرقم نهائياً.", "success")
    return redirect(url_for("admin_sold_numbers"))



@login_required
@app.route("/my/number/<int:nid>")
def my_number(nid):
    u = current_user()
    n = db().execute("SELECT * FROM numbers WHERE id=? AND buyer_id=?", (nid, u["user_id"])).fetchone()
    if not n: abort(404)
    
    # تصفير إشعار هذا الرقم لما المستخدم يفتحه
    db().execute("UPDATE numbers SET seen_by_buyer=1 WHERE id=?", (nid,))
    db().commit()
    
    # نرجع نجيب البيانات بعد التحديث
    n = db().execute("SELECT * FROM numbers WHERE id=? AND buyer_id=?", (nid, u["user_id"])).fetchone()
    
    # حساب الأيام (3 أيام = 72 ساعة)
    from datetime import datetime
    is_expired = False
    if n["sold_at"]:
        try:
            sold_date = datetime.strptime(n["sold_at"], "%Y-%m-%d %H:%M:%S")
            days_passed = (datetime.now() - sold_date).days
            if days_passed >= 3:
                is_expired = True
        except Exception:
            pass

    return page("my_number", number=n, is_expired=is_expired)



# ============================================================
# TELEGRAM MANAGER
# ============================================================


def _tg_country(phone):
    if not phone:
        return "دول أخرى"
    digits = phone.lstrip("+")
    # قراءة الدول من DEFAULT_BUY_PRICES الموجود في الكود
    try:
        # نرتب حسب طول الكود تنازلياً (الأطول أولاً)
        sorted_prices = sorted(DEFAULT_BUY_PRICES, key=lambda x: len(str(x[1])), reverse=True)
        for country, code, price, flag in sorted_prices:
            if code and digits.startswith(str(code)):
                return country
    except Exception:
        pass
    return "دول أخرى"

def tg_request_code(phone):
    """يطلب كود من تيليجرام ويرجع (session_str, code_hash, error)"""
    try:
        from telethon.sync import TelegramClient
        from telethon.sessions import StringSession
    except ImportError:
        return None, None, "مكتبة telethon غير مثبتة"
    
    api_id = int(get_setting("TG_API_ID", "22651991"))
    api_hash = get_setting("TG_API_HASH", "").strip()
    if not api_hash:
        return None, None, "API Hash غير مهيأ"
    # التحقق من صيغة الرقم
    if not re.match(r'^\+[1-9]\d{6,14}$', phone):
        return None, None, "رقم الهاتف غير صالح، تأكد من إضافته بالصيغة الدولية (+967...)"
    try:
        import asyncio
        async def run():
            client = TelegramClient(StringSession(), api_id, api_hash)
            await client.connect()
            try:
                sent = await client.send_code_request(phone)
                return client.session.save(), sent.phone_code_hash, None
            finally:
                await client.disconnect()
        return asyncio.run(asyncio.wait_for(run(), 60))
    except Exception as e:
        err_text = str(e)
        if "PHONE_NUMBER_INVALID" in err_text or "invalid" in err_text.lower():
            return None, None, "رقم الهاتف غير صالح أو غير مسجل في تيليجرام"
        if "FLOOD_WAIT" in err_text:
            import re as _re
            m = _re.search(r'\d+', err_text)
            wait = m.group(0) if m else "قليل"
            return None, None, f"تيليجرام يطلب الانتظار {wait} ثانية قبل المحاولة مجدداً"
        if "API_ID_INVALID" in err_text or "API_HASH" in err_text:
            return None, None, "مفاتيح API الخاصة بتيليجرام غير صالحة، جرب مفاتيح جديدة"
        return None, None, f"خطأ من تيليجرام: {err_text[:100]}"

def tg_verify_code(phone, code, session_str, code_hash):
    """يؤكد الكود ويرجع (final_session, status, error)"""
    try:
        from telethon.sync import TelegramClient
        from telethon.sessions import StringSession
    except ImportError:
        return None, "error", "telethon غير مثبتة"
    api_id = int(get_setting("TG_API_ID", "22651991"))
    api_hash = get_setting("TG_API_HASH", "").strip()
    try:
        import asyncio
        async def run():
            client = TelegramClient(StringSession(session_str), api_id, api_hash)
            await client.connect()
            try:
                try:
                    await client.sign_in(phone=phone, code=code, phone_code_hash=code_hash)
                except Exception as e:
                    if type(e).__name__ == "SessionPasswordNeededError":
                        return None, "2fa", None
                    raise
                if not await client.is_user_authorized():
                    return None, "error", "لم يكتمل"
                return client.session.save(), "ok", None
            finally:
                await client.disconnect()
        return asyncio.run(asyncio.wait_for(run(), 60))
    except Exception as e:
        return None, "error", f"خطأ: {str(e)[:100]}"

def tg_verify_password(session_str, password):
    try:
        from telethon.sync import TelegramClient
        from telethon.sessions import StringSession
    except ImportError:
        return None, "telethon غير مثبتة"
    api_id = int(get_setting("TG_API_ID", "22651991"))
    api_hash = get_setting("TG_API_HASH", "").strip()
    try:
        import asyncio
        async def run():
            client = TelegramClient(StringSession(session_str), api_id, api_hash)
            await client.connect()
            try:
                await client.sign_in(password=password)
                if not await client.is_user_authorized():
                    return None, "لم يكتمل"
                return client.session.save(), None
            finally:
                await client.disconnect()
        return asyncio.run(asyncio.wait_for(run(), 60))
    except Exception as e:
        return None, f"خطأ: {str(e)[:100]}"


# ============================================================
# ROUTES: Telegram Manager
# ============================================================
@app.route("/admin/tg")
@admin_required
def admin_tg():
    tg_nums = db().execute("SELECT * FROM numbers WHERE platform LIKE 'telegram%' ORDER BY id DESC LIMIT 100").fetchall()
    return page("admin_tg", tg_nums=tg_nums)

@app.route("/admin/tg/add", methods=["POST"])
@admin_required
def admin_tg_add():
    phone = request.form.get("phone", "").strip().replace(" ", "").replace("-", "")
    if not phone.startswith("+"): phone = "+" + phone
    if not re.match(r"^\+\d{7,15}$", phone):
        flash("رقم غير صالح. مثال: +967777123456", "error")
        return redirect(url_for("admin_tg"))
    # إصلاح: الفحص يتم فقط ضمن نفس المنصة (تيليجرام) عشان نسمح بنفس الرقم في الواتساب
    existing = db().execute(
        "SELECT 1 FROM numbers WHERE phone=? AND platform LIKE 'telegram%' AND status IN ('available','pending') LIMIT 1",
        (phone,)
    ).fetchone()
    if existing:
        flash("الرقم موجود حالياً في منصة تيليجرام (معروض أو قيد التأكيد)", "error")
        return redirect(url_for("admin_tg"))
    country = _tg_country(phone)
    cur = db().execute("INSERT INTO numbers(platform,country,phone,price,status) VALUES(?,?,?,0,'pending')",
                       ("telegram", country, phone))
    db().commit()
    flash(f"تم إضافة {phone} - {country}. اطلب الكود الآن.", "success")
    return redirect(url_for("admin_tg"))

@app.route("/admin/tg/<int:nid>/request-code", methods=["POST"])
@admin_required
def admin_tg_request_code(nid):
    n = db().execute("SELECT * FROM numbers WHERE id=? AND platform LIKE 'telegram%'", (nid,)).fetchone()
    if not n:
        return jsonify({"ok": False, "error": "رقم غير موجود"})
    sess, hash_, err = tg_request_code(n["phone"])
    if sess:
        db().execute("INSERT OR REPLACE INTO temp_sessions(phone,session_str,code_hash,created_at) VALUES(?,?,?,datetime('now'))",
                     (n["phone"], sess, hash_))
        db().commit()
        return jsonify({"ok": True, "msg": f"تم إرسال الكود إلى تيليجرام {n['phone']}. الآن أكّد الكود."})
    else:
        return jsonify({"ok": False, "error": f"فشل: {err}"})

@app.route("/admin/tg/<int:nid>/verify", methods=["POST"])
@admin_required
def admin_tg_verify(nid):
    n = db().execute("SELECT * FROM numbers WHERE id=? AND platform LIKE 'telegram%'", (nid,)).fetchone()
    if not n:
        return jsonify({"ok": False, "error": "رقم غير موجود"})
    code = request.form.get("code", "").strip()
    if not code:
        return jsonify({"ok": False, "error": "الكود مطلوب"})
    temp = db().execute("SELECT * FROM temp_sessions WHERE phone=?", (n["phone"],)).fetchone()
    if not temp:
        return jsonify({"ok": False, "error": "اطلب الكود أولاً"})
    session, status, err = tg_verify_code(n["phone"], code, temp["session_str"], temp["code_hash"])
    if status == "ok":
        platform = request.form.get("platform", "Telegram (Session)").strip()
        if platform not in ("WhatsApp", "Telegram (Session)"):
            platform = "Telegram (Session)"
        try:
            price = float(request.form.get("price", "1.00"))
            if price <= 0:
                raise ValueError
        except ValueError:
            price = 1.00
        is_premium = 1 if request.form.get("is_premium") == "on" else 0
        db().execute("UPDATE numbers SET session_string=?, status='available', platform=?, price=?, is_premium=? WHERE id=?",
                     (session, platform, price, is_premium, nid))
        db().execute("DELETE FROM temp_sessions WHERE phone=?", (n["phone"],))
        db().commit()
        return jsonify({"ok": True, "session": session[:20] + "..."})
    if status == "2fa":
        return jsonify({"ok": False, "need_2fa": True, "session": temp["session_str"], "error": "يتطلب كلمة سر 2FA"})
    return jsonify({"ok": False, "error": err or "فشل"})

@app.route("/admin/tg/<int:nid>/2fa", methods=["POST"])
@admin_required
def admin_tg_2fa(nid):
    n = db().execute("SELECT * FROM numbers WHERE id=? AND platform LIKE 'telegram%'", (nid,)).fetchone()
    if not n:
        return jsonify({"ok": False, "error": "رقم غير موجود"})
    pw = request.form.get("password", "").strip()
    temp = db().execute("SELECT * FROM temp_sessions WHERE phone=?", (n["phone"],)).fetchone()
    if not temp:
        return jsonify({"ok": False, "error": "اطلب الكود أولاً"})
    session, err = tg_verify_password(temp["session_str"], pw)
    if session:
        db().execute("UPDATE numbers SET session_string=?, status='available' WHERE id=?", (session, nid))
        db().execute("DELETE FROM temp_sessions WHERE phone=?", (n["phone"],))
        db().commit()
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": err or "فشل"})

@app.route("/admin/tg/<int:nid>/price", methods=["POST"])
@admin_required
def admin_tg_price(nid):
    try:
        price = float(request.form.get("price", "0"))
        if price <= 0:
            flash("السعر يجب أن يكون أكبر من 0", "error")
            return redirect(url_for("admin_tg"))
        db().execute("UPDATE numbers SET price=?, status='available' WHERE id=? AND platform LIKE 'telegram%'", (price, nid))
        db().commit()
        flash(f"تم تحديد السعر: ${price:.2f}", "success")
    except:
        flash("سعر غير صالح", "error")
    return redirect(url_for("admin_tg"))

@app.route("/admin/tg/<int:nid>/platform", methods=["POST"])
@admin_required
def admin_tg_platform(nid):
    """تغيير منصة الرقم (واتساب/تيليجرام)"""
    platform = request.form.get("platform", "").strip()
    if platform not in ("WhatsApp", "Telegram (Session)"):
        flash("منصة غير صالحة", "error")
        return redirect(url_for("admin_tg"))
    db().execute("UPDATE numbers SET platform=? WHERE id=?", (platform, nid))
    db().commit()
    flash(f"تم تغيير المنصة إلى {platform}", "success")
    return redirect(url_for("admin_tg"))


@app.route("/admin/tg/<int:nid>/delete", methods=["POST"])
@admin_required
def admin_tg_delete(nid):
    db().execute("DELETE FROM numbers WHERE id=? AND platform LIKE 'telegram%'", (nid,))
    db().commit()
    flash("تم الحذف", "success")
    return redirect(url_for("admin_tg"))



def binance_verify(order_id, expected_amount):
    api_key = get_setting("BINANCE_API_KEY", "").strip()
    api_secret = get_setting("BINANCE_API_SECRET", "").strip()
    if not api_key or not api_secret:
        return False, "مفاتيح Binance غير مهيأة"
    try:
        import hmac, hashlib, time, requests
        from urllib.parse import urlencode
        params = {"timestamp": int(time.time() * 1000), "recvWindow": 5000, "limit": 100}
        qs = urlencode(params)
        sig = hmac.new(api_secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
        url = "https://api.binance.com/sapi/v1/pay/transactions?" + qs + "&signature=" + sig
        headers = {"X-MBX-APIKEY": api_key}
        res = requests.get(url, headers=headers, timeout=20).json()
        if not res.get("success"):
            return False, "خطأ Binance: " + str(res.get("message", ""))
        for tx in res.get("data", []):
            if str(tx.get("orderId", "")) == str(order_id):
                amount = float(tx.get("amount", 0))
                if amount >= float(expected_amount):
                    return True, "تم التحقق"
                return False, "المبلغ " + str(amount) + "$ أقل من " + str(expected_amount) + "$"
        return False, "لم يتم العثور على Order ID"
    except Exception as e:
        return False, "خطأ: " + str(e)[:80]



@app.route("/deposit/binance", methods=["POST"])
@login_required
def deposit_binance():
    u = current_user()
    try:
        amt = float(request.form.get("amount", "0"))
        order_id = request.form.get("order_id", "").strip()
    except:
        flash("بيانات غير صالحة", "error"); return redirect(url_for("deposit"))
    if amt < 0.1:
        flash("الحد الأدنى $0.10", "error"); return redirect(url_for("deposit"))
    if not order_id:
        flash("Order ID مطلوب", "error"); return redirect(url_for("deposit"))
    ok, msg = binance_verify(order_id, amt)
    if ok:
        db().execute("INSERT INTO deposits(user_id,method,amount_usd,status,trans_id) VALUES(?,?,?,'approved',?)",
                     (u["user_id"], "binance", amt, order_id))
        db().execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amt, u["user_id"]))
        db().commit()
        flash(f" تم شحن $" + f"{amt:.2f}" + " تلقائياً!", "success")
    else:
        db().execute("INSERT INTO deposits(user_id,method,amount_usd,status,trans_id) VALUES(?,?,?,'pending',?)",
                     (u["user_id"], "binance", amt, order_id))
        db().commit()
        flash(f"{ico("warning", 14)} " + msg + " - أُرسل للإدارة", "error")
    return redirect(url_for("dashboard"))



@app.route("/fetch-otp/<int:nid>", methods=["POST"])
@login_required
def fetch_otp_route(nid):
    u = current_user()
    n = db().execute("SELECT * FROM numbers WHERE id=? AND buyer_id=?", (nid, u["user_id"])).fetchone()
    if not n:
        return jsonify({"ok": False, "error": "غير مصرح"}), 403
    
    # الكود القديم المخزن
    old_code = n["last_code"] if n["last_code"] else None
    
    # حفظ وقت الطلب الحالي
    import time as _time
    req_time = _time.time()
    db().execute("UPDATE numbers SET request_time=? WHERE id=?", (req_time, nid))
    db().commit()

    platform = (n["platform"] or "").lower()
    
    if platform == "telegram" or "telegram" in platform.lower():
        try: sess = n["session_string"]
        except: sess = None
        sold_ts = 0
        if n["sold_at"]:
            try:
                from datetime import datetime
                sold_ts = datetime.strptime(n["sold_at"], "%Y-%m-%d %H:%M:%S").timestamp()
            except Exception:
                pass
        # نجيب الكود من بعد وقت الطلب (عشان نتجنب القديم)
        code, err = _tg_fetch_code(sess, req_time)
    else:
        code, err = fetch_otp_imap()
    
    if code:
        # نتأكد إن الكود الجديد مختلف عن القديم
        if old_code and code == old_code:
            return jsonify({"ok": False, "error": "لم يصل كود جديد بعد. جرب بعد لحظات."})
        
        db().execute("UPDATE numbers SET last_code=? WHERE id=?", (code, nid))
        db().commit()
        try:
            log_code(u["user_id"], nid, n["phone"], code, n["platform"])
        except Exception as e:
            print("[CODE-LOG] error: " + str(e))
        return jsonify({"ok": True, "code": code})
    
    return jsonify({"ok": False, "error": err or "لا كود"})



def fetch_otp_imap(phone_filter=None, since_ts=0):
    """سحب آخر كود واتساب وصل في الإيميل (مع فلترة بالتاريخ)"""
    addr = get_setting("WA_EMAIL_ADDRESS", "").strip() or get_setting("EMAIL_ADDRESS", "").strip()
    pwd  = get_setting("WA_EMAIL_PASSWORD", "").strip() or get_setting("EMAIL_PASSWORD", "").strip()
    host = get_setting("IMAP_HOST", "imap.gmail.com").strip()

    if not (addr and pwd):
        return None, "الإيميل غير مهيأ في الإعدادات"

    try:
        import email as _email
        from email.utils import parsedate_to_datetime
        import time as _time

        M = imaplib.IMAP4_SSL(host, timeout=15)
        M.login(addr, pwd)
        M.select("INBOX", readonly=True)

        # نبحث عن رسائل واتساب
        _, data = M.search(None, 'TEXT', '"whatsapp"')
        ids = data[0].split()

        if not ids:
            M.logout()
            return None, "لا توجد رسائل واتساب"

        # نأخذ آخر 10 رسائل ونفحصها من الأحدث للأقدم
        for mid in reversed(ids[-10:]):
            try:
                _, md = M.fetch(mid, "(RFC822)")
                if not md or not md[0] or not isinstance(md[0], tuple):
                    continue

                msg = _email.message_from_bytes(md[0][1])

                # فلترة بالتاريخ: نتجاهل الرسائل القديمة (قبل الشراء)
                if since_ts > 0:
                    try:
                        msg_date_str = msg.get("Date", "")
                        if msg_date_str:
                            msg_ts = parsedate_to_datetime(msg_date_str).timestamp()
                            # نتجاهل الرسائل اللي قبل وقت الشراء بـ 60 ثانية كهامش أمان
                            if msg_ts < (since_ts - 60):
                                continue
                    except Exception:
                        pass  # لو فشل تحليل التاريخ، نكمل ونفحص

                # استخراج النص من الرسالة
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            try:
                                body += part.get_payload(decode=True).decode(errors="ignore")
                            except Exception:
                                pass
                else:
                    try:
                        payload = msg.get_payload(decode=True)
                        if payload:
                            body = payload.decode(errors="ignore")
                    except Exception:
                        pass

                if not body:
                    continue

                # البحث عن كود 6 أرقام (مثل: 123-456 أو 123456)
                m = re.search(r"(?<!\d)(\d{3})[-\s]?(\d{3})(?!\d)", body)
                if m:
                    M.logout()
                    return m.group(1) + m.group(2), None

                # البحث عن كود 4-8 أرقام (احتياطي)
                m = re.search(r"(?<!\d)(\d{4,8})(?!\d)", body)
                if m:
                    M.logout()
                    return m.group(1), None

            except Exception as e:
                print(f"[IMAP-FETCH] error on msg {mid}: {e}")
                continue

        M.logout()
        return None, "لا يوجد كود جديد في آخر الرسائل"

    except Exception as e:
        return None, "خطأ: " + str(e)[:80]


@app.route("/admin/tg/<int:nid>/list", methods=["POST"])
@admin_required
def admin_tg_list(nid):
    # يحول الرقم لـ متاح للبيع في المتجر
    n = db().execute("SELECT * FROM numbers WHERE id=? AND platform LIKE 'telegram%'", (nid,)).fetchone()
    if n:
        sess = n["session_string"] if "session_string" in n.keys() else None
        price = n["price"] if "price" in n.keys() else 0
        if sess and price and price > 0:
            db().execute("UPDATE numbers SET status='available' WHERE id=?", (nid,))
            db().commit()
            flash("تم عرض الرقم للبيع في المتجر", "success")
        else:
            flash("لازم يكون فيه جلسة وسعر قبل العرض", "error")
    return redirect(url_for("admin_tg"))

@app.route("/admin/tg/<int:nid>/unlist", methods=["POST"])
@admin_required
def admin_tg_unlist(nid):
    # يسحب الرقم من المتجر (يرجعه pending)
    db().execute("UPDATE numbers SET status='pending' WHERE id=? AND platform LIKE 'telegram%'", (nid,))
    db().commit()
    flash("تم سحب الرقم من المتجر", "success")
    return redirect(url_for("admin_tg"))



def mask_phone(phone):
    """يخفي وسط الرقم ويحط أيقونة قفل صغيرة (SVG)"""
    if not phone: return ""
    clean = str(phone).replace(" ", "").replace("-", "")
    if len(clean) < 7: return clean
    
    prefix = clean[:4]
    suffix = clean[-3:]
    
    lock_svg = (
        '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" '
        'style="display:inline-block; vertical-align:middle; margin:0 4px; opacity:0.85; color:var(--primary2);">'
        '<rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>'
        '<path d="M7 11V7a5 5 0 0 1 10 0v4"/>'
        '</svg>'
    )
    
    return prefix + lock_svg + suffix


def auto_fetch_otp(user_id, number_id, max_seconds=300, interval=5):
    """دالة خلفية تبحث عن الكود تلقائياً بعد الشراء (مع فلترة بالتاريخ)"""
    start_time = time.time()
    attempt = 0
    
    # نحسب وقت البداية (sold_at) لفلترة الرسائل القديمة
    since_ts = 0
    try:
        with app.app_context():
            n0 = db().execute("SELECT sold_at FROM numbers WHERE id=?", (number_id,)).fetchone()
            if n0 and n0["sold_at"]:
                from datetime import datetime as _dt
                since_ts = _dt.strptime(n0["sold_at"], "%Y-%m-%d %H:%M:%S").timestamp()
    except Exception:
        pass
    
    # نحفظ وقت الشراء الأصلي عشان ما ناخذ كود قديم
    initial_code = None
    try:
        with app.app_context():
            r0 = db().execute("SELECT last_code FROM numbers WHERE id=?", (number_id,)).fetchone()
            if r0 and r0["last_code"]:
                initial_code = r0["last_code"]
    except Exception:
        pass
    
    while time.time() - start_time < max_seconds:
        time.sleep(interval)
        attempt += 1
        
        try:
            with app.app_context():
                row = db().execute("SELECT * FROM numbers WHERE id=? AND buyer_id=?", 
                                    (number_id, user_id)).fetchone()
                if not row:
                    print(f"[AUTO-OTP #{number_id}] Number not found or not owned")
                    return
                
                # إذا كان الكود الحالي مختلف عن الكود الأولي = كود جديد وصل، توقف
                current = row["last_code"] if row["last_code"] else None
                if current and current != initial_code:
                    print(f"[AUTO-OTP #{number_id}] New code arrived: {current}")
                    return
                
                # نحاول سحب الكود
                platform = (row["platform"] or "").lower()
                code = None
                
                if "telegram" in platform:
                    session = row["session_string"]
                    if session:
                        code, _ = _tg_fetch_code(session, since_ts, phone=row["phone"])
                else:
                    code, _ = fetch_otp_imap(since_ts=since_ts)
                
                if code and code != initial_code:
                    db().execute("UPDATE numbers SET last_code=? WHERE id=?", (code, number_id))
                    db().commit()
                    print(f"[AUTO-OTP #{number_id}] Found new code: {code} (attempt {attempt})")
                    return
                
                print(f"[AUTO-OTP #{number_id}] Attempt {attempt}: no new code yet")
        except Exception as e:
            print(f"[AUTO-OTP #{number_id}] Error: {e}")
    
    print(f"[AUTO-OTP #{number_id}] Gave up after {attempt} attempts")




def get_country_flag(phone):
    """يرجع اسم الدولة والعلم من رقم الهاتف (بالبحث في قاعدة البيانات)"""
    if not phone:
        return "", ""
    clean = str(phone).replace("+", "").replace(" ", "").replace("-", "")
    if not clean or not clean.isdigit():
        return "", ""
    
    try:
        rows = db().execute("SELECT country, code, flag FROM buy_prices WHERE code IS NOT NULL AND code != ''").fetchall()
        # نرتب حسب طول الكود تنازلياً
        sorted_rows = sorted(rows, key=lambda x: len(str(x["code"])), reverse=True)
        for r in sorted_rows:
            code = str(r["code"])
            if clean.startswith(code):
                return r["country"], r["flag"]
    except Exception:
        pass
    return "", ""


def get_live_events():
    events = []
    try:
        sales = db().execute("""
            SELECT u.username, n.country FROM numbers n 
            JOIN users u ON u.user_id = n.buyer_id 
            WHERE n.status='sold' AND n.sold_at IS NOT NULL
            ORDER BY n.sold_at DESC LIMIT 5
        """).fetchall()
        for s in sales:
            events.append({"type": "buy", "user": str(s['username']), "text": "رقم " + str(s['country'])})
        
        deposits = db().execute("""
            SELECT u.username, d.amount_usd FROM deposits d 
            JOIN users u ON u.user_id = d.user_id 
            WHERE d.status='approved' AND d.processed_at IS NOT NULL
            ORDER BY d.processed_at DESC LIMIT 5
        """).fetchall()
        for d in deposits:
            events.append({"type": "deposit", "user": str(d['username']), "text": "$" + "{:.2f}".format(d['amount_usd'])})
    except Exception as e:
        print("[LIVE-EVENTS] " + str(e))
    
    if not events:
        events = [{"type": "info", "user": "متجر مطري", "text": "تسليم فوري وأرقام موثوقة 100%"}]
    return events

def page(name, active="", **ctx):
    u = current_user()
    ticker_code = ""  # تعريف آمن لتجنب UnboundLocalError
    # تحويل الرسائل إلى Toasts أنيقة
    flash_messages = get_flashed_messages(with_categories=True)
    fh = ""
    for c, m in flash_messages:
        icon = "check-circle" if c == "success" else ("warning" if c == "error" else "info")
        color = "#10b981" if c == "success" else ("#ef4444" if c == "error" else "#6366f1")
        bg = "rgba(16,185,129,0.1)" if c == "success" else ("rgba(239,68,68,0.1)" if c == "error" else "rgba(99,102,241,0.1)")
        border = "rgba(16,185,129,0.3)" if c == "success" else ("rgba(239,68,68,0.3)" if c == "error" else "rgba(99,102,241,0.3)")
        fh += f'''<div class="toast-message" style="display:flex;align-items:center;gap:12px;background:{bg};border:1px solid {border};padding:14px 18px;border-radius:14px;margin-bottom:10px;color:{color};font-weight:600;font-size:14px;animation: slideDown 0.4s ease; position: relative; backdrop-filter: blur(10px);"><div style="flex-shrink:0;">{ico(icon, 20)}</div><div style="flex:1; line-height:1.5;">{m}</div><button onclick="this.parentElement.style.display='none'" style="background:none;border:none;color:{color};cursor:pointer;opacity:0.6;padding:0;display:flex;">{ico("x", 18)}</button></div>'''

    ticker_template = """<div id="liveTicker" style="position:fixed;top:75px;left:50%;transform:translateX(-50%) translateY(-30px);z-index:99999;display:flex;align-items:center;justify-content:center;padding:12px 24px;background:rgba(20,20,40,0.85);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);border:1.5px solid rgba(251,191,36,0.4);border-radius:50px;box-shadow:0 10px 40px rgba(0,0,0,0.6), 0 0 30px rgba(251,191,36,0.15);opacity:0;transition:all 0.5s cubic-bezier(0.4,0,0.2,1);max-width:92vw;overflow:hidden;">
    <div id="tickerInner" style="display:flex;align-items:center;gap:10px;font-size:13px;font-weight:800;color:#fff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
        <svg id="tickerIcon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#fbbf24" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;"><path d="M3 11l18-5v12L3 14v-3z"/><path d="M11.6 16.8a3 3 0 1 1-5.8-1.6"/></svg>
        <span id="tickerMsg" style="color:#e8e8f5;"></span>
    </div>
</div>
<script>
(function() {
    var ticker = document.getElementById('liveTicker');
    if (!ticker) return;
    
    // ميزة 20 عملية يومياً
    var today = new Date().toDateString();
    var storedDate = localStorage.getItem('tickerDate');
    var viewCount = parseInt(localStorage.getItem('tickerViewCount') || '0');
    if (storedDate !== today) { viewCount = 0; localStorage.setItem('tickerDate', today); }
    if (viewCount >= 20) { ticker.remove(); return; }
    viewCount++;
    localStorage.setItem('tickerViewCount', viewCount.toString());

    var events = __EVENTS_JSON__;
    var msg = document.getElementById('tickerMsg');
    var icon = document.getElementById('tickerIcon');
    var inner = document.getElementById('tickerInner');
    
    // دالة تحويل البيانات لنص وألوان
    function renderEvent(ev) {
        var bg, border, iconColor, label;
        if (ev.type === 'buy') {
            bg = 'rgba(16,185,129,0.15)';
            border = 'rgba(16,185,129,0.4)';
            iconColor = '#10b981';
            label = 'قام <b style="color:#fbbf24;">' + ev.user + '</b> بشراء ' + ev.text + ' بنجاح';
            icon.innerHTML = '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>';
        } else if (ev.type === 'deposit') {
            bg = 'rgba(99,102,241,0.15)';
            border = 'rgba(99,102,241,0.4)';
            iconColor = '#818cf8';
            label = 'تم شحن <b style="color:#fbbf24;">' + ev.text + '</b> لحساب <b style="color:#fbbf24;">' + ev.user + '</b>';
            icon.innerHTML = '<line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>';
        } else {
            bg = 'rgba(251,191,36,0.15)';
            border = 'rgba(251,191,36,0.4)';
            iconColor = '#fbbf24';
            label = '<b>' + ev.user + '</b>: ' + ev.text;
            icon.innerHTML = '<path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2z"/>';
        }
        ticker.style.background = 'linear-gradient(135deg, rgba(20,20,40,0.95), ' + bg + ')';
        ticker.style.borderColor = border;
        icon.style.stroke = iconColor;
        msg.innerHTML = label;
    }
    
    renderEvent(events[0]);
    setTimeout(function() { ticker.style.transform = 'translateX(-50%) translateY(0)'; ticker.style.opacity = '1'; }, 100);
    
    var idx = 0;
    var swap = setInterval(function() {
        idx = (idx + 1) % events.length;
        msg.style.opacity = '0';
        setTimeout(function() {
            renderEvent(events[idx]);
            msg.style.opacity = '1';
        }, 300);
    }, 3500);
    
    setTimeout(function() {
        clearInterval(swap);
        ticker.style.transform = 'translateX(-50%) translateY(-30px)';
        ticker.style.opacity = '0';
    }, 20000);
})();
</script>"""
    body = ""
    
    # لو الصفحة جاية بـ body جاهز، نستخدمه على طول
    if ctx.get("body"):
        if getattr(_CAPTURE, "on", False):
            return ctx["body"]
        return f'''<!DOCTYPE html>
<html lang="ar" dir="rtl" data-theme="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
  <title>{get_setting("SITE_NAME", "MATARI STORE")} · MATARI STORE</title>
  <script>(function(){{var t=localStorage.getItem('theme')||'dark';document.documentElement.setAttribute('data-theme',t);}})();</script>
  <link rel="manifest" href="/manifest.json">
  <link rel="icon" href="/icon.svg" type="image/svg+xml">
  <meta name="theme-color" content="#6366f1">
  <link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800;900&family=Tajawal:wght@700;800;900&display=swap" rel="stylesheet">
  <style>{CSS}</style>
  <style>{SMOOTH_CSS}{DASH_CSS_EXTRA}</style>
</head>
<body>
{ticker_code}
{_nav(u)}
{_bottom_nav(u, active)}
<div class="container" style="padding-top:16px;padding-bottom:0">{fh}</div>
{Markup(ctx["body"])}
<div style="text-align:center; padding: 30px 0 20px 0; width: 100%;">
  <div style="display:inline-flex; align-items:center; gap:8px; background:var(--card); border:1px solid var(--border); padding:10px 18px; border-radius:30px; font-size:12px; font-weight:700; color:var(--muted); box-shadow:0 4px 12px rgba(0,0,0,0.2);">
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--primary2)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
    <span>MATARI STORE © 2026</span>
  </div>
</div>
{get_notif_btn()}
{get_refresh_btn()}
<script>{JS}</script>
<script>{SMOOTH_JS}</script>
<script>
(function() {{
    // إصلاح: إيقاف التحديث التلقائي لتحسين سلاسة الموقع (120Hz Smooth)
    var autoRefreshPages = [];
    var currentPage = '{name}';
    
    if (autoRefreshPages.indexOf(currentPage) === -1) return;
    
    var refreshTimer = null;
    var lastInteraction = Date.now();
    
    function resetInteraction() {{
        lastInteraction = Date.now();
    }}
    
    window.addEventListener('scroll', resetInteraction, {{passive: true}});
    document.addEventListener('click', resetInteraction);
    document.addEventListener('keydown', resetInteraction);
    document.addEventListener('touchstart', resetInteraction, {{passive: true}});
    
    // مؤشر التحديث
    var indicator = document.createElement('div');
    indicator.id = 'globalRefreshIndicator';
    indicator.style.cssText = 'display:none;position:fixed;bottom:80px;left:50%;transform:translateX(-50%);background:var(--card);border:1px solid var(--border);padding:10px 20px;border-radius:30px;box-shadow:0 4px 12px rgba(0,0,0,0.3);z-index:99999;align-items:center;gap:8px;font-size:13px;color:var(--primary2);font-weight:700;';
    indicator.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" style="animation:spin 1s linear infinite;"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg><span>جاري التحديث...</span>';
    document.body.appendChild(indicator);
    
    refreshTimer = setInterval(function() {{
        // لو المستخدم تفاعل خلال 15 ثانية، منعملش تحديث
        if (Date.now() - lastInteraction < 15000) return;
        
        // نتحقق إن مفيش modal مفتوح
        var openModal = document.querySelector('[style*="display:flex"][style*="position:fixed"]');
        if (openModal && openModal.id !== 'globalRefreshIndicator') return;
        
        indicator.style.display = 'flex';
        setTimeout(function() {{ window.location.reload(); }}, 500);
    }}, 5000);
}})();
</script>
</body>
</html>'''

    def _nc(n, show_buy=False):
        b = f'<a href="/buy/{n["id"]}" class="btn btn-sm" style="margin-top:12px;width:100%">شراء</a>' if show_buy else ''
        return f'''<div class="num-card">
          <div class="num-head"><span class="badge {n["platform"]}">{("واتساب" if "whatsapp" in str(n["platform"]).lower() else "تيليجرام" if "telegram" in str(n["platform"]).lower() else n["platform"])}</span><span class="badge available">متاح</span></div>
          <div class="num-country">{n["country"]}</div>
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:14px;direction:ltr">
          <div class="num-phone" style="margin:0;flex:1;color:var(--muted);font-family:monospace">{mask_phone(n["phone"])}</div>
          
        </div>
          <div class="num-price">${n["price"]:.2f}</div>{b}
        </div>'''

    if name == "index":
        cards = ""
        for n in ctx.get("numbers", []):
            masked = mask_phone(n["phone"])
            _plat_lower = str(n["platform"]).lower()
            is_whatsapp = "whatsapp" in _plat_lower
            platform_color = "var(--success)" if is_whatsapp else "var(--primary2)"
            _pl = "whatsapp" if is_whatsapp else "telegram"
            platform_icon = site_icon(_pl, 16, ico(_pl, 16))
            cards += f'''
            <div class="card" style="display:flex; align-items:center; justify-content:space-between; padding:16px; margin-bottom:12px; background:linear-gradient(145deg, var(--card), var(--card2)); border-left:4px solid {platform_color};">
                <div style="display:flex; align-items:center; gap:14px;">
                    <div style="width:44px; height:44px; border-radius:12px; background:rgba(255,255,255,0.05); display:flex; align-items:center; justify-content:center; color:{platform_color};">
                        {platform_icon}
                    </div>
                    <div>
                        <div style="font-weight:800; font-size:15px; margin-bottom:4px; color:var(--text);">{n["country"]}</div>
                        <div style="font-family:monospace; font-size:13px; color:var(--muted); direction:ltr; text-align:left;">{masked}</div>
                    </div>
                </div>
                <div style="text-align:left;">
                    <div style="font-size:18px; font-weight:900; color:var(--primary2); direction:ltr; margin-bottom:4px;">${n["price"]:.2f}</div>
                    <a href="/buy/{n["id"]}" class="btn btn-sm" style="padding:8px 16px; font-size:12px; display:inline-flex; align-items:center; gap:6px; border-radius:10px;">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="21" r="1"/><circle cx="20" cy="21" r="1"/><path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6"/></svg>
                        توجه للشراء
                      </a>
                </div>
            </div>'''
        
        if not cards:
            cards = '<div class="empty">لا توجد أرقام متاحة حالياً، تابعنا قريباً!</div>'

        body = f'''
        <div class="hero" style="padding: 50px 16px 30px; text-align: center; position:relative; overflow:hidden;">
            <div style="position:absolute; top:-50px; left:-50px; width:150px; height:150px; background:var(--primary); filter:blur(100px); opacity:0.3; border-radius:50%;"></div>
            <div style="position:absolute; bottom:-50px; right:-50px; width:150px; height:150px; background:var(--primary2); filter:blur(100px); opacity:0.3; border-radius:50%;"></div>
                        <h1 style="font-size: clamp(32px, 8vw, 48px); line-height:1.2; margin-bottom: 20px; font-weight: 900; position:relative; z-index:1;">
              <span style="background:var(--gradient); -webkit-background-clip:text; -webkit-text-fill-color:transparent; display:inline-block; animation: float 3s ease-in-out infinite;">أرقام موثوقة.</span><br>
              <span style="color:var(--text); display:inline-block; animation: float 3s ease-in-out infinite 0.5s;">تسليم فوري.</span>
            </h1>
            <div style="max-width: 450px; margin: 0 auto 30px; position:relative; z-index:1;">
              <p style="color: var(--muted); font-size: 15px; line-height: 1.8; text-align: center; font-weight: 500; font-family: 'Inter', -apple-system, sans-serif;">
                احصل على رقم
                <span style="background: var(--gradient); -webkit-background-clip: text; -webkit-text-fill-color: transparent; font-weight: 900; font-size: 17px;">واتساب</span>
                أو
                <span style="background: linear-gradient(135deg, #06b6d4, #3b82f6); -webkit-background-clip: text; -webkit-text-fill-color: transparent; font-weight: 900; font-size: 17px;">تيليجرام</span>
                جاهز للتفعيل،
                <br>
                مع سحب تلقائي لأكواد
                <span style="color: var(--primary2); font-weight: 800; font-family: monospace;">OTP</span>
                في ثوانٍ.
              </p>
            </div>
            <div style="display: flex; flex-direction: column; gap: 10px; max-width: 450px; margin: 0 auto; position:relative; z-index:1; text-align: right;">
              
              <a href="/about" style="display: flex; align-items: center; gap: 12px; background: linear-gradient(135deg, rgba(99,102,241,0.15), rgba(6,182,212,0.15)); padding: 14px 16px; border-radius: 14px; border: 1px solid rgba(99,102,241,0.3); text-decoration: none; transition: all 0.3s; box-shadow: 0 4px 15px rgba(99,102,241,0.15);">
                <div style="width: 40px; height: 40px; background: var(--gradient); border-radius: 12px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; box-shadow: 0 4px 10px rgba(99,102,241,0.3);">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
                </div>
                <div style="flex: 1;">
                  <div style="font-size: 14px; color: var(--text); font-weight: 800; margin-bottom: 2px;">دليل استخدام الموقع</div>
                  <div style="font-size: 11px; color: var(--muted);">تعرف على كل أقسام المتجر وكيفية استخدامها</div>
                </div>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--primary2)" stroke-width="2.5"><polyline points="15 18 9 12 15 6"/></svg>
              </a>

              <div style="display: flex; align-items: center; gap: 10px; background: rgba(16,185,129,0.08); padding: 12px 16px; border-radius: 12px; border: 1px solid rgba(16,185,129,0.2);">
                <div style="width: 32px; height: 32px; background: rgba(16,185,129,0.15); border-radius: 8px; display: flex; align-items: center; justify-content: center; flex-shrink: 0;">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                </div>
                <div style="font-size: 13px; color: var(--text); font-weight: 600;">تسليم فوري وسحب تلقائي لأكواد OTP (بدون انتظار).</div>
              </div>

              <div style="display: flex; align-items: center; gap: 10px; background: rgba(245,158,11,0.08); padding: 12px 16px; border-radius: 12px; border: 1px solid rgba(245,158,11,0.2);">
                <div style="width: 32px; height: 32px; background: rgba(245,158,11,0.15); border-radius: 8px; display: flex; align-items: center; justify-content: center; flex-shrink: 0;">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
                </div>
                <div style="font-size: 13px; color: var(--text); font-weight: 600;">حماية كاملة وأرقام موثوقة 100% مع ضمان العمل.</div>
              </div>

            </div>
        </div>
        
        <div class="container" style="padding-top: 10px; max-width:700px;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 20px;">
                <div class="section-title" style="margin:0;">أحدث الأرقام</div>
                <a href="/store" style="color:var(--primary2); font-size:13px; font-weight:700; display:flex; align-items:center; gap:4px;">
                    عرض الكل {ico("arrow-right", 14)}
                </a>
            </div>
            <div style="display:flex; flex-direction:column;">
                {cards}
            </div>
        </div>
        
        <style>
        @keyframes float {{
            0% {{ transform: translateY(0px); }}
            50% {{ transform: translateY(-8px); }}
            100% {{ transform: translateY(0px); }}
        }}
        .card:hover {{
            transform: translateY(-2px);
            box-shadow: 0 8px 24px rgba(0,0,0,0.3);
            border-color: var(--primary2);
        }}
        </style>
        '''

    elif name == "store":
        platform = ctx["cur_platform"]
        country = ctx["cur_country"]
        q_val = ctx["cur_q"]
        sort = ctx["cur_sort"]
        
        # جلب كل الأرقام المتاحة مقسمة حسب الدولة
        where_parts = ["status='available'"]
        params = []
        if platform:
            where_parts.append("platform=?")
            params.append(platform)
        if q_val:
            where_parts.append("(phone LIKE ? OR country LIKE ?)")
            params.extend([f"%{q_val}%", f"%{q_val}%"])
        
        all_nums = db().execute(
            f"SELECT * FROM numbers WHERE {' AND '.join(where_parts)} ORDER BY country ASC, id DESC",
            params
        ).fetchall()
        
        # تجميع الأرقام حسب الدولة
        countries_dict = {}
        for n in all_nums:
            c = n["country"]
            if c not in countries_dict:
                countries_dict[c] = []
            countries_dict[c].append(n)

        # الأزرار الثلاثة العلوية
        # الأيقونات الديناميكية (تتغير من لوحة الإدارة)
        wa_icon = site_icon("whatsapp_btn", 24, '<svg width="24" height="24" viewBox="0 0 24 24" fill="#25D366"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/></svg>')
        tg_icon = site_icon("telegram_btn", 24, '<svg width="24" height="24" viewBox="0 0 24 24" fill="#0088cc"><path d="M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0zm5.562 8.161c-.18 1.897-.962 6.502-1.359 8.627-.168.9-.5 1.201-.82 1.23-.697.064-1.226-.461-1.901-.903-1.056-.692-1.653-1.123-2.678-1.798-1.185-.781-.417-1.21.258-1.911.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635.099-.002.321.023.465.14a.506.506 0 01.171.325c.016.093.036.306.02.472z"/></svg>')
        sell_icon = site_icon("sell_btn", 24, ico("dollar", 24))

        # الصف الأول: واتساب + تيليجرام
        wa_active = "background: linear-gradient(135deg, rgba(37,211,102,0.25), rgba(37,211,102,0.1)); border: 2px solid #25D366; box-shadow: 0 0 25px rgba(37,211,102,0.4); color: #25d366; transform: translateY(-2px);" if platform == "whatsapp" else "background: var(--card); border: 1px solid var(--border); color: var(--text);"
        tg_active = "background: linear-gradient(135deg, rgba(6,182,212,0.25), rgba(6,182,212,0.1)); border: 2px solid #06b6d4; box-shadow: 0 0 25px rgba(6,182,212,0.4); color: #06b6d4; transform: translateY(-2px);" if platform == "Telegram (Session)" else "background: var(--card); border: 1px solid var(--border); color: var(--text);"
        
        row1 = f'''<div style="display:flex; gap:12px; margin-bottom:16px;">
            <a href="/store?platform=whatsapp" style="flex:1; display:flex; align-items:center; justify-content:center; gap:8px; padding:16px 10px; font-size:15px; font-weight:900; border-radius:16px; {wa_active} transition: all 0.3s;">{wa_icon} <span>واتساب</span></a>
            <a href="/store?platform=Telegram (Session)" style="flex:1; display:flex; align-items:center; justify-content:center; gap:8px; padding:16px 10px; font-size:15px; font-weight:900; border-radius:16px; {tg_active} transition: all 0.3s;">{tg_icon} <span>تيليجرام</span></a>
        </div>'''
        
        # الصف الثاني: بيع رقم
        row2 = f'''<div style="display:flex; margin-bottom:24px;">
            <a href="/sell" onmousedown="this.style.transform='scale(0.93)'; this.style.boxShadow='0 0 25px rgba(99,102,241,0.7)';" onmouseup="this.style.transform='scale(1)'; this.style.boxShadow='0 4px 20px rgba(99,102,241,0.15)';" ontouchstart="this.style.transform='scale(0.93)'; this.style.boxShadow='0 0 25px rgba(99,102,241,0.7)';" ontouchend="this.style.transform='scale(1)'; this.style.boxShadow='0 4px 20px rgba(99,102,241,0.15)';" style="flex:1; display:flex; align-items:center; justify-content:center; gap:10px; padding:16px; font-size:15px; font-weight:900; background:rgba(99,102,241,0.1); backdrop-filter:blur(12px); -webkit-backdrop-filter:blur(12px); border:2px solid rgba(99,102,241,0.5); color:#818cf8; border-radius:50px; box-shadow:0 4px 20px rgba(99,102,241,0.15); text-decoration:none; transition:all 0.2s;">
<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<path d="M2.5 12.5 V21.5"/>
<path d="M5.5 13 H10.5 A2 2 0 0 1 10.5 17 H8"/>
<path d="M5.5 21 H12.5 A2 2 0 0 0 13.62 20.66 L19.9 16.4 A1.75 1.75 0 0 0 18 13.5 L12.5 16.5"/>
<path d="M20 4.5 A5 2.5 0 1 1 10 4.5 A5 2.5 0 1 1 20 4.5 Z"/>
<path d="M10 4.5 V8 A5 2.5 0 0 0 20 8 V4.5"/>
</svg>
<span>بيع رقم</span></a>

        </div>'''


        # بناء الكروت (كل دولة كارت منفصل، تحته)
        # إصلاح: الاعتماد على الأرقام المجلوبة من الـ route مباشرة (ctx)
        all_nums_for_display = ctx.get("numbers", [])
        
        countries_dict = {}
        for n in all_nums_for_display:
            c = n["country"]
            if c not in countries_dict:
                countries_dict[c] = []
            countries_dict[c].append(n)
        
        if not countries_dict:
            carousel_html = '<div class="card" style="text-align:center;padding:20px;background:linear-gradient(145deg, var(--card) 0%, var(--card2) 100%);border:1px solid var(--border);border-radius:20px;margin-top:20px;"><div class="empty-search-pulse" style="display:inline-flex;align-items:center;justify-content:center;width:60px;height:60px;background:rgba(99,102,241,0.1);border-radius:50%;margin-bottom:10px;color:var(--primary2);"><svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg></div><div style="font-size:15px;font-weight:900;color:var(--text);margin-bottom:4px;">لا توجد أرقام متاحة</div><div style="font-size:11px;color:var(--muted);">سيتم تحديث المتجر قريباً إن شاء الله</div></div><style>@keyframes empty-pulse { 0%, 100% { transform: scale(1); opacity: 1; } 50% { transform: scale(1.08); opacity: 0.7; } } .empty-search-pulse { animation: empty-pulse 2s ease-in-out infinite; }</style>'
        else:
            country_cards = []
            for c_idx, (c_name, nums) in enumerate(countries_dict.items()):
                flag_row = db().execute("SELECT flag FROM buy_prices WHERE country=?", (c_name,)).fetchone()
                flag = flag_row["flag"] if flag_row and flag_row["flag"] else "🌍"
                
                # بناء شرائح الأرقام (slides) لكل رقم في الدولة
                slides_inner = ""
                for n in nums:
                    is_prem = bool(n["is_premium"] if "is_premium" in n.keys() else 0)
                    premium_border = "2px solid #f59e0b" if is_prem else "1px solid rgba(99,102,241,0.25)"
                    premium_shadow = "0 0 20px rgba(245,158,11,0.4)" if is_prem else "none"
                    masked = mask_phone(n["phone"])
                    _plt = "telegram" if "telegram" in str(n["platform"]).lower() else "whatsapp"
                    plt_icon_inner = site_icon(_plt, 16, ico(_plt, 16))
                    platform_label = "واتساب" if "whatsapp" in str(n["platform"]).lower() else "تيليجرام"
                    
                    slides_inner += (
                        '<div class="num-slide" style="min-width:100%; scroll-snap-align:center; padding:0 2px;">'
                        '<div style="position:relative; background:' + ('linear-gradient(145deg, rgba(6,182,212,0.15), rgba(6,182,212,0.03))' if 'telegram' in str(n["platform"]).lower() else 'linear-gradient(145deg, rgba(37,211,102,0.15), rgba(37,211,102,0.03))') + '; border:1px solid ' + ('rgba(6,182,212,0.4)' if 'telegram' in str(n["platform"]).lower() else 'rgba(37,211,102,0.4)') + '; border-radius:12px; padding:10px 12px; margin-bottom:8px;">'

                        '<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">'
                        f'<span style="display:inline-flex; align-items:center; gap:4px; padding:3px 10px; font-size:10px; font-weight:800; background:linear-gradient(135deg, rgba(99,102,241,0.2), rgba(6,182,212,0.2)); color:#a5b4fc; border-radius:20px; border:1px solid rgba(99,102,241,0.3);">{plt_icon_inner} {platform_label}</span>'
                        '<div style="display:flex; align-items:center; gap:6px;">'
                        + ('<div style="width:38px; height:38px; flex-shrink:0; display:flex; align-items:center; justify-content:center; position:relative;">'
                           '<svg viewBox="0 0 100 100" style="width:100%; height:100%; filter: drop-shadow(0 2px 5px rgba(0,0,0,0.6)) drop-shadow(0 0 8px rgba(245,158,11,0.3));">'
                           '<defs>'
                           '<linearGradient id="goldSeal' + str(n["id"]) + '" x1="0%" y1="0%" x2="100%" y2="100%">'
                           '<stop offset="0%" stop-color="#fbbf24"/>'
                           '<stop offset="50%" stop-color="#f59e0b"/>'
                           '<stop offset="100%" stop-color="#b45309"/>'
                           '</linearGradient>'
                           '<radialGradient id="sealHighlight' + str(n["id"]) + '" cx="30%" cy="30%" r="50%">'
                           '<stop offset="0%" stop-color="#fde68a" stop-opacity="0.6"/>'
                           '<stop offset="100%" stop-color="#fbbf24" stop-opacity="0"/>'
                           '</radialGradient>'
                           '</defs>'
                           # قاعدة الختم الدائرية
                           '<circle cx="50" cy="50" r="46" fill="url(#goldSeal' + str(n["id"]) + ')"/>'
                           '<circle cx="50" cy="50" r="46" fill="url(#sealHighlight' + str(n["id"]) + ')"/>'
                           # حلقة خارجية مزدوجة (زي ختم رسمي)
                           '<circle cx="50" cy="50" r="42" fill="none" stroke="#fff" stroke-width="1.5" opacity="0.7"/>'
                           '<circle cx="50" cy="50" r="37" fill="none" stroke="#fff" stroke-width="0.8" opacity="0.5"/>'
                           # نجوم صغيرة في الأعلى (زي أختام المدارس)
                           '<path d="M50 8 L52 14 L58 14 L53 18 L55 24 L50 20 L45 24 L47 18 L42 14 L48 14 Z" fill="#fff" opacity="0.9"/>'
                           # حرف M كبير كلاسيكي (بخط Serif)
                           '<text x="50" y="55" font-family="Georgia, Times New Roman, serif" font-size="36" font-weight="900" font-style="italic" fill="#fff" text-anchor="middle" style="filter: drop-shadow(0 1px 2px rgba(0,0,0,0.4))">M</text>'
                           # خط فاصل
                           '<line x1="28" y1="64" x2="72" y2="64" stroke="#fff" stroke-width="1.2" opacity="0.7"/>'
                           # كلمة مميز بخط صغير تحتها
                           '<text x="50" y="78" font-family="Cairo, sans-serif" font-size="11" font-weight="900" fill="#fff" text-anchor="middle" letter-spacing="1.5">مميز</text>'
                           '</svg>'
                           '</div>' if is_prem else '') +
                        '<span style="padding:3px 10px; font-size:9px; font-weight:900; background:rgba(16,185,129,0.15); color:#10b981; border-radius:20px; border:1px solid rgba(16,185,129,0.3);">● متاح</span>'
                        '</div>'

                        '</div>'
                        '<div style="display:flex; align-items:center; justify-content:center; gap:6px; margin-bottom:6px; background:linear-gradient(135deg, rgba(0,0,0,0.3), rgba(0,0,0,0.2)); padding:8px; border-radius:10px; direction:ltr; border:1px solid rgba(99,102,241,0.15);">'
                        '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#6366f1" stroke-width="2"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/></svg>'
                        f'<div style="font-family:monospace; font-size:13px; color:#a5b4fc; font-weight:700; letter-spacing:0.5px;">{masked}</div>'
                        '</div>'
                        '<div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:6px; padding:6px 10px; background:rgba(16,185,129,0.08); border-radius:10px; border:1px solid rgba(16,185,129,0.2);">'
                        '<div style="font-size:11px; color:#6b7280; font-weight:600;">السعر</div>'
                        f'<div style="font-weight:900; font-size:16px; color:#10b981; direction:ltr; text-shadow:0 0 12px rgba(16,185,129,0.4);">${n["price"]:.2f}</div>'
                        '</div>'
                        f'<a href="/buy/{n["id"]}" style="display:flex; align-items:center; justify-content:center; gap:6px; padding:8px; font-size:12px; font-weight:800; color:#fff; background:linear-gradient(135deg, #6366f1 0%, #8b5cf6 50%, #06b6d4 100%); border-radius:10px; text-decoration:none; box-shadow:0 3px 12px rgba(99,102,241,0.4);">'
                        '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="9" cy="21" r="1"/><circle cx="20" cy="21" r="1"/><path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6"/></svg>'
                        'شراء الآن</a></div></div>'
                    )
                
                carousel_id = f"carousel_{c_idx}"
                counter_id = f"counter_{c_idx}"
                total_nums = len(nums)
                
                country_cards.append(
                    '<div style="background:linear-gradient(145deg, #1e1e35 0%, #15152a 100%); border:1px solid rgba(99,102,241,0.3); border-radius:20px; padding:12px; box-shadow:0 8px 32px rgba(99,102,241,0.15); margin-bottom:16px;">'
                    '<div style="display:flex; align-items:center; gap:10px; margin-bottom:10px; padding-bottom:8px; border-bottom:1px solid rgba(99,102,241,0.2);">'
                    f'<div style="width:44px; height:44px; display:flex; align-items:center; justify-content:center; background:linear-gradient(135deg, rgba(99,102,241,0.2), rgba(6,182,212,0.2)); border-radius:12px; border:2px solid rgba(99,102,241,0.4); font-size:24px; flex-shrink:0;">{flag}</div>'
                    '<div style="flex:1;">'
                    f'<div style="font-weight:900; font-size:16px; color:#e8e8f5;">{c_name}</div>'
                    f'<div style="font-size:12px; color:var(--muted);">{total_nums} رقم متاح</div>'
                    '</div></div>'
                    f'<div id="{carousel_id}" class="num-carousel" style="display:flex; overflow-x:auto; scroll-snap-type:x mandatory; scrollbar-width:none; -webkit-overflow-scrolling:touch; scroll-behavior:smooth; gap:0; overscroll-behavior-x:contain; scroll-padding:0;">'
                    + slides_inner +
                    '</div>'
                    '<div style="display:flex; justify-content:center; align-items:center; gap:12px; margin-top:12px;">'
                    f'<button type="button" onclick="numPrev(\'{carousel_id}\')" class="carousel-arrow" style="background:rgba(99,102,241,0.15);color:#818cf8;border:1px solid rgba(99,102,241,0.4);padding:8px 14px;border-radius:12px;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;width:44px;height:40px;">'
                    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>'
                    '</button>'
                    f'<div id="{counter_id}" style="font-size:14px;font-weight:900;color:#fff;background:rgba(99,102,241,0.2);border:1px solid rgba(99,102,241,0.4);padding:8px 18px;border-radius:12px;min-width:70px;text-align:center;">1 / {total_nums}</div>'
                    f'<button type="button" onclick="numNext(\'{carousel_id}\')" class="carousel-arrow" style="background:rgba(99,102,241,0.15);color:#818cf8;border:1px solid rgba(99,102,241,0.4);padding:8px 14px;border-radius:12px;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;width:44px;height:40px;">'
                    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>'
                    '</button>'
                    '</div>'
                    '</div>'
                )
                carousel_html = "".join(country_cards)
            carousel_html += (
                '<style>'
'.num-carousel::-webkit-scrollbar{display:none}'
'.num-carousel{-ms-overflow-style:none;}'
'.num-slide{transition:transform 0.3s ease;}'
'@keyframes slideIn{from{opacity:0.6;transform:scale(0.96);}to{opacity:1;transform:scale(1);}}'
'.num-slide > div{animation:slideIn 0.4s ease; border-radius:14px;}'
'</style>'
                '<script>'
                'window.numNext = function(id){var c=document.getElementById(id);if(!c)return;var w=c.offsetWidth;c.scrollBy({left:w,behavior:"smooth"});};'
                'window.numPrev = function(id){var c=document.getElementById(id);if(!c)return;var w=c.offsetWidth;c.scrollBy({left:-w,behavior:"smooth"});};'
                '(function(){'
                'var carousels=document.querySelectorAll(".num-carousel");'
                'carousels.forEach(function(c){'
                'var counterId="counter_"+c.id.replace("carousel_","");'
                'var counter=document.getElementById(counterId);'
                'var slides=c.querySelectorAll(".num-slide");var total=slides.length;'
                'function u(){var w=c.offsetWidth;var i=Math.round(c.scrollLeft/w)+1;if(i<1)i=1;if(i>total)i=total;if(counter)counter.textContent=i+" / "+total;}'
                'c.addEventListener("scroll",u,{passive:true});'
                'setTimeout(u,100);'
                '});'
                '})();'
                '</script>'
            )
        
        # ترقيم الصفحات
        pag = ""
        if ctx["total_pages"] > 1:
            parts = []
            for i in range(1, ctx["total_pages"] + 1):
                qs = urlencode({**{k: v for k, v in request.args.items() if k != "p"}, "p": i})
                if i == ctx["page_n"]:
                    parts.append(f'<span style="background:var(--gradient);color:#fff;padding:8px 14px;border-radius:8px;font-weight:700">{i}</span>')
                else:
                    parts.append(f'<a href="/store?{qs}" style="background:var(--card);border:1px solid var(--border);padding:8px 14px;border-radius:8px;color:var(--text)">{i}</a>')
            pag = f'<div style="display:flex;gap:6px;justify-content:center;margin-top:32px;flex-wrap:wrap">{"".join(parts)}</div>'

        # بناء شريط فلاتر الدول
        body = f'''<div class="container" style="padding-top:16px">
          <div class="section-title" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
            المتجر <span class="section-sub">({ctx["total"]} رقم متاح)</span>
          </div>
          


          {row1}
          {row2}


          <form method="GET" action="/store">
            <div class="search-bar" style="border-radius:16px; border:1.5px solid var(--border); background:var(--card);">
              <div style="color:var(--primary2); margin-right:6px;">{ico("search", 22)}</div>
              <input type="text" name="q" value="{q_val}" placeholder="ابحث عن رقم أو دولة..." style="font-size:15px; padding:16px 0;">
            </div>
          </form>
          

          <div style="margin-top:16px">{carousel_html}</div>
          {pag}
        </div>'''


    elif name == "buy":
        n = ctx["number"]
        final_price = ctx.get("final_price", n["price"])
        coupon_code = ctx.get("coupon_code", "")
        discount_pct = ctx.get("discount_pct", 0)
        
        # جلب علم الدولة من الداتابيز
        flag_row = db().execute("SELECT flag FROM buy_prices WHERE country=?", (n["country"],)).fetchone()
        country_flag = flag_row["flag"] if flag_row and flag_row["flag"] else "🌍"
        
        # جلب أيقونة المنصة (SVG)
        plt_lower = str(n["platform"]).lower()
        plt_icon_name = "whatsapp" if "whatsapp" in plt_lower else "telegram"
        plt_icon = site_icon(plt_icon_name, 20, ico(plt_icon_name, 20))
        plt_label = "واتساب" if "whatsapp" in plt_lower else "تيليجرام"
        plt_color = "#25d366" if "whatsapp" in plt_lower else "#06b6d4"

        coupon_html = f'''
        <div style="margin-bottom:14px;">
            <form method="GET" action="/buy/{n["id"]}" style="display:flex; gap:6px; background:var(--bg2); padding:4px; border-radius:10px; border:1px solid var(--border);">
                <input type="text" name="coupon" value="{coupon_code}" placeholder="كود الخصم" style="flex:1; padding:8px 12px; background:transparent; color:var(--text); border:none; outline:none; font-family:monospace; text-transform:uppercase; font-size:13px;">
                <button type="submit" class="btn btn-sm" style="padding:6px 14px; border-radius:8px;">تطبيق</button>
            </form>
            {f'<div style="color:var(--success); font-size:11px; margin-top:6px; font-weight:bold; display:flex; align-items:center; gap:4px;">{ico("check-circle", 12)} تم تطبيق خصم {discount_pct}% بنجاح!</div>' if discount_pct > 0 else ''}
        </div>
        '''
        
        body = f'''<div class="container" style="max-width:480px; padding-top:10px;"><div class="card" style="padding:16px;">
          
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
            <span style="display:inline-flex; align-items:center; gap:4px; background:rgba(255,255,255,0.05); border:1px solid {plt_color}40; color:{plt_color}; padding:3px 8px; border-radius:6px; font-weight:800; font-size:11px;">
              {plt_icon} {plt_label}
            </span>
            <span class="badge available" style="font-size:9px; padding:3px 6px;">متاح</span>
          </div>

          <div style="display:flex; align-items:center; gap:6px; margin-bottom:8px;">
            <span style="font-size:20px;">{country_flag}</span>
            <h2 style="font-size:16px; margin:0; font-weight:900;">{n["country"]}</h2>
          </div>
          
          <div style="font-family:monospace; font-size:16px; direction:ltr; text-align:left; color:var(--muted); margin-bottom:12px; background:rgba(0,0,0,0.2); padding:12px 14px; border-radius:10px; border:1px solid var(--border); display:flex; align-items:center; justify-content:space-between; gap:8px;">
            <span style="display:inline-flex; align-items:center;">{mask_phone(n["phone"])}</span>
            <span style="font-size:11px; color:#ef4444; font-weight:800; background:rgba(239,68,68,0.08); padding:4px 10px; border-radius:8px; display:inline-flex; align-items:center; gap:4px; border: 1px solid rgba(239,68,68,0.2);"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg> يُكشف بعد الشراء</span>
          </div>

          {coupon_html}

          <div style="background:rgba(0,0,0,0.15); border:1px solid var(--border); border-radius:10px; padding:10px; margin-bottom:12px;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px; font-size:12px; color:var(--muted);">
              <span>السعر الأصلي</span>
              <span style="text-decoration:{'line-through' if discount_pct > 0 else 'none'};">${n["price"]:.2f}</span>
            </div>
            <div style="display:flex; justify-content:space-between; align-items:center; border-top:1px dashed var(--border); padding-top:6px; margin-top:6px;">
              <span style="font-weight:800; font-size:13px;">الإجمالي المطلوب</span>
              <strong style="font-size:20px; color:var(--success);">${final_price:.2f}</strong>
            </div>
          </div>

          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; padding:8px 12px; background:rgba(99,102,241,0.08); border:1px solid rgba(99,102,241,0.2); border-radius:10px;">
            <span style="color:var(--primary2); font-size:12px; font-weight:700; display:flex; align-items:center; gap:6px;">
              {ico("wallet", 16)} رصيدك الحالي
            </span>
            <strong style="font-size:15px; color:var(--text);">${u["balance"]:.2f}</strong>
          </div>

          {fh}
          
          <form method="POST"><button class="form-btn" style="padding:12px; font-size:14px;">تأكيد الشراء</button></form>
          
          <a href="/store" class="btn btn-ghost" style="width:100%; margin-top:8px; padding:8px; display:flex; align-items:center; justify-content:center; gap:6px; font-size:12px;">
            {ico("arrow-left", 12)} رجوع للمتجر
          </a>
        </div></div>'''



    elif name == "my_number":
        n = ctx["number"]
        last_code = n["last_code"] if "last_code" in n.keys() and n["last_code"] else None
        code_html = esc(last_code) if last_code else "••••••"
        
        # تحديد حالة الكود
        if last_code:
            status_text = "الكود جاهز"
            status_color = "var(--success)"
            status_bg = "rgba(16,185,129,0.15)"
            status_border = "rgba(16,185,129,0.4)"
        else:
            status_text = "في الانتظار"
            status_color = "var(--warn)"
            status_bg = "rgba(245,158,11,0.15)"
            status_border = "rgba(245,158,11,0.4)"

        phone_clean = str(n["phone"]).replace("+", "")
        detected_country_2, detected_flag_2 = get_country_flag(n["phone"])
        flag_display_2 = f'<span style="font-size:24px;">{detected_flag_2}</span>' if detected_flag_2 else '🌍'
        country_display = detected_country_2 if detected_country_2 else n["country"]

        # زر النسخ (يظهر فقط لو في كود)
        copy_code_btn = ""
        if last_code:
            copy_code_btn = f'''<button onclick="copyText('{esc(last_code)}', this)" class="btn" style="width:100%;margin-bottom:12px;display:flex;align-items:center;justify-content:center;gap:8px;padding:14px;background:var(--success);color:#fff;box-shadow:0 4px 12px rgba(16,185,129,0.2);border-radius:12px;font-weight:800;font-size:15px;">{ico("copy", 18)} نسخ الكود الآن</button>'''

        if ctx.get('is_expired'):
            body = f'''
            <div class="container" style="max-width:600px; padding-top:40px; text-align:center;">
              <div class="card" style="border: 1px solid rgba(239,68,68,0.3); padding: 40px 20px;">
                <div style="width: 80px; height: 80px; margin: 0 auto 20px; background: rgba(239,68,68,0.1); border: 2px solid var(--danger); border-radius: 50%; display: flex; align-items: center; justify-content: center;">
                  <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="var(--danger)" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
                </div>
                <h2 style="font-size: 24px; font-weight: 900; margin-bottom: 10px;">انتهت صلاحية الطلب</h2>
                <p style="color: var(--muted); font-size: 14px; line-height: 1.8; margin-bottom: 30px;">مر أكثر من 3 أيام على شراء هذا الرقم. لا يمكن طلب الكود بعد الآن.</p>
                <a href="/my/numbers" class="btn" style="background: var(--danger); color: #fff; width: 100%; padding: 14px;">العودة لأرقامي</a>
              </div>
            </div>
            '''
        else:
            body = f'''<div class="container" style="max-width:600px">
              <div class="card" style="padding: 24px;">
                
                <!-- الهيدر -->
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;">
                  <span style="display:inline-flex;align-items:center;gap:8px;background:rgba(99,102,241,0.1);border:1px solid rgba(99,102,241,0.3);padding:6px 14px;border-radius:20px;font-weight:800;font-size:13px;color:var(--primary2);">
                    {site_icon("whatsapp", 18, ico("whatsapp", 18)) if "whatsapp" in str(n["platform"]).lower() else site_icon("telegram", 18, ico("telegram", 18))}
                    {"واتساب" if "whatsapp" in str(n["platform"]).lower() else "تيليجرام"}
                  </span>
                  <span class="badge sold" style="padding:6px 14px;">مشترى</span>
                </div>

                <!-- الدولة -->
                <div style="display:flex; align-items:center; justify-content:center; gap:10px; background:var(--bg2); border:1px solid var(--border); padding:12px; border-radius:14px; margin-bottom:20px;">
                  <span style="font-size:24px;">{flag_display_2}</span>
                  <span style="font-weight:900; font-size:16px;">{esc(country_display)}</span>
                </div>

                <!-- رقم الهاتف -->
                <div style="display:flex;align-items:center;gap:12px;background:var(--bg2);padding:14px 16px;border-radius:12px;margin-bottom:20px;border:1px solid var(--border);">
                  <div style="flex:1;">
                    <div style="font-size:11px; color:var(--muted); margin-bottom:2px;">رقم الهاتف</div>
                    <div style="font-family:monospace; font-size:17px; direction:ltr; color:var(--text); font-weight:900; letter-spacing: 0.5px;">+{esc(phone_clean)}</div>
                  </div>
                  <button onclick="copyText('{esc(phone_clean)}', this)" class="btn btn-sm" style="padding:8px 14px; background:var(--gradient); color:#fff; font-size:13px; font-weight:700;">
                    {ico("copy", 14)} نسخ
                  </button>
                </div>

                <!-- الكود الحالي -->
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
                  <span style="font-size:15px; font-weight:800; display:flex; align-items:center; gap:6px;">
                    {ico("key", 18)} الكود الحالي
                  </span>
                  <span style="font-size:11px; color:{status_color}; font-weight:800; background:{status_bg}; border:1px solid {status_border}; padding:4px 12px; border-radius:20px;">{status_text}</span>
                </div>
                
                {f'''<div style="min-height:80px; display:flex; align-items:center; justify-content:center; border-radius:14px; font-size:38px; font-weight:900; letter-spacing:12px; margin-bottom:12px; background:rgba(37,211,102,0.05); border:2px dashed rgba(37,211,102,0.4); color:#25d366; font-family:monospace; text-shadow: 0 0 20px rgba(37,211,102,0.4);">
                  {code_html}
                </div>''' if "whatsapp" in str(n["platform"]).lower() else f'''<div style="min-height:80px; display:flex; align-items:center; justify-content:center; border-radius:14px; font-size:38px; font-weight:900; letter-spacing:12px; margin-bottom:12px; background:rgba(6,182,212,0.05); border:2px dashed rgba(6,182,212,0.4); color:#06b6d4; font-family:monospace; text-shadow: 0 0 20px rgba(6,182,212,0.4);">
                  {code_html}
                </div>'''}
                
                <div id="otpResult" style="text-align:center; font-size:13px; margin-bottom:12px; min-height:18px"></div>

                <!-- الأزرار -->
                {copy_code_btn}
                
                <button onclick="fetchOTP({n["id"]})" id="otpBtn" class="btn" style="width:100%; display:flex; align-items:center; justify-content:center; gap:10px; padding:14px; margin-bottom:12px; background:var(--gradient); color:#fff; border-radius:12px; font-weight:800; font-size:15px;">
                  <span id="otpBtnIcon" style="display:flex;">{ico("refresh", 18)}</span>
                  <span id="otpBtnText">سحب الكود الآن</span>
                </button>

                <a href="/dashboard" class="btn btn-ghost" style="width:100%; display:flex; align-items:center; justify-content:center; gap:8px;">
                  {ico("arrow-left", 14)} رجوع للحساب
                </a>
              </div>
            </div>'''

    elif name == "my_numbers":
        nums = ctx.get("my_numbers", [])
        cards = ""
        for n in nums:
            nid = n["id"]
            is_new = (n["seen_by_buyer"] if "seen_by_buyer" in n.keys() else 1) == 0
            platform_lower = str(n["platform"]).lower()
            if "telegram" in platform_lower or "session" in platform_lower:
                border_color = "#06b6d4"
                badge_text = site_icon("telegram", 14, ico("telegram", 14)) + " تيليجرام"
                badge_class = "telegram"
            else:
                border_color = "#25d366"
                badge_text = site_icon("whatsapp", 14, ico("whatsapp", 14)) + " واتساب"
                badge_class = "whatsapp"

            new_badge = ""
            if is_new:
                new_badge = '<span style="background:#ef4444;color:#fff;font-size:9px;font-weight:900;padding:3px 8px;border-radius:20px;animation:pulse 1.5s infinite;">جديد</span>'
            
            if bool(n["is_premium"] if "is_premium" in n.keys() else 0):
                _default_prem = '<svg viewBox="0 0 100 100" style="width:100%;height:100%;filter:drop-shadow(0 2px 5px rgba(0,0,0,.6))"><defs><linearGradient id="gs' + str(nid) + '" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fbbf24"/><stop offset=".5" stop-color="#f59e0b"/><stop offset="1" stop-color="#b45309"/></linearGradient></defs><circle cx="50" cy="50" r="46" fill="url(#gs' + str(nid) + ')"/><circle cx="50" cy="50" r="42" fill="none" stroke="#fff" stroke-width="1.5" opacity=".7"/><text x="50" y="52" font-family="Georgia,serif" font-size="32" font-weight="900" font-style="italic" fill="#fff" text-anchor="middle">M</text><text x="50" y="78" font-family="Cairo,sans-serif" font-size="14" font-weight="900" fill="#fff" text-anchor="middle">مميز</text></svg>'
                _prem_img = site_icon("premium_icon", 22, _default_prem)
                new_badge += '<div style="width:22px;height:22px;display:inline-flex;align-items:center;justify-content:center;vertical-align:middle;margin-right:2px;">' + _prem_img + '</div>'

            # لون خلفية خفيف حسب المنصة
            if "telegram" in platform_lower or "session" in platform_lower:
                bg_style = "background: linear-gradient(145deg, rgba(6,182,212,0.08), rgba(6,182,212,0.02));"
            else:
                bg_style = "background: linear-gradient(145deg, rgba(37,211,102,0.08), rgba(37,211,102,0.02));"
            
            border_style = f'border: 1px solid rgba(255,255,255,0.08); border-right: 4px solid {border_color}; {bg_style} box-shadow: none;' if is_new else f'border: 1px solid rgba(255,255,255,0.08); border-right: 4px solid {border_color}; {bg_style} opacity: 0.85; box-shadow: none;'
            
            # حساب الوقت المتبقي
            import time as _time
            from datetime import datetime as _dt
            time_btn = ""
            # تأكد أن المتغير موجود دائماً حتى لو مفيش تاريخ
            if n["sold_at"]:
                try:
                    sold_ts = int(_dt.strptime(n["sold_at"], "%Y-%m-%d %H:%M:%S").timestamp())
                    end_ts = sold_ts + 259200
                    left_sec = end_ts - _time.time()
                    # حساب الوقت المتبقي للعرض جوه الزر
                    days = int(left_sec // 86400)
                    hours = int((left_sec % 86400) // 3600)
                    minutes = int((left_sec % 3600) // 60)
                    
                    time_str = ""
                    if days > 0:
                        time_str += str(days) + " ي "
                    if hours > 0:
                        time_str += str(hours) + " س "
                    time_str += str(minutes) + " د"
                    
                    if left_sec > 0:
                        time_btn = '<button type="button" onclick="event.stopPropagation(); openTimeModal(' + str(end_ts) + ', ' + str(left_sec) + ')" style="background:rgba(245,158,11,0.1); border:1px solid rgba(245,158,11,0.3); color:#f59e0b; padding:5px 10px; border-radius:8px; font-size:11px; font-weight:800; display:inline-flex; align-items:center; gap:4px; cursor:pointer; transition:all 0.2s; direction:rtl;"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><polyline class="clock-hand" points="12 6 12 12 16 14"/></svg> ' + time_str + '</button>'
                    else:
                        time_btn = '<button type="button" onclick="event.stopPropagation(); openTimeModal(0, 0)" style="background:rgba(239,68,68,0.15); border:1px solid rgba(239,68,68,0.4); color:#ef4444; padding:6px 12px; border-radius:10px; font-size:12px; font-weight:800; display:inline-flex; align-items:center; gap:6px; cursor:pointer; transition:all 0.2s;"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg> انتهت</button>'
                except: pass

            detected_country, detected_flag = get_country_flag(n["phone"])
            if not detected_country:
                detected_country = n["country"]
                detected_flag = ""
            
            flag_display = f'<span style="font-size:18px;">{detected_flag}</span> ' if detected_flag else ''

            cards += '<div class="num-card" onclick="location.href=\'/my/number/' + str(nid) + '\'" style="' + border_style + '">'
            cards += '<div class="num-head" style="display:flex; justify-content:space-between; align-items:center; width:100%; margin-bottom:12px; gap:6px; border-bottom: 1px solid rgba(255,255,255,0.05); padding-bottom:12px;">'
            cards += '<div style="display:flex; align-items:center; gap:6px; background:rgba(0,0,0,0.2); padding:4px 8px 4px 4px; border-radius:12px; border:1px solid rgba(255,255,255,0.05);">'
            cards += '<span class="badge ' + badge_class + '" style="display:inline-flex; align-items:center; gap:4px; padding:4px 8px; font-size:11px; border-radius:8px;">' + badge_text + '</span>'
            cards += new_badge + '</div>'
            cards += time_btn + '</div>'
            cards += '<div style="display:flex; align-items:center; gap:10px; margin-bottom:12px;">'
            cards += '<div style="width:44px; height:44px; display:flex; align-items:center; justify-content:center; background:rgba(99,102,241,0.1); border-radius:12px; border:2px solid rgba(99,102,241,0.3); font-size:24px; flex-shrink:0;">' + (flag_display if flag_display else '🌍') + '</div>'
            cards += '<div style="flex:1;"><div style="font-size:11px; color:var(--muted); margin-bottom:2px;">الدولة</div><div style="font-weight:900; font-size:16px; color:var(--text);">' + str(detected_country) + '</div></div></div>'
            cards += '<div style="background:rgba(0,0,0,0.25); border:1px solid rgba(99,102,241,0.2); border-radius:12px; padding:14px; margin-bottom:16px; display:flex; align-items:center; justify-content:center; gap:8px; direction:ltr;">'
            cards += '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#6366f1" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="2" width="14" height="20" rx="2" ry="2"/><line x1="12" y1="18" x2="12.01" y2="18"/></svg>'
            cards += '<div style="font-family:monospace; font-size:16px; color:#a5b4fc; font-weight:800; letter-spacing:0.5px;">' + str(n['phone']) + '</div></div>'
            cards += '<div style="margin-top:16px; display:flex; gap:8px;">'
            cards += '<a href="/my/number/' + str(nid) + '" onclick="event.stopPropagation();" class="btn" style="flex:1; display:flex; align-items:center; justify-content:center; gap:8px; padding:12px; font-size:14px; font-weight:800; background:linear-gradient(135deg, #6366f1, #8b5cf6); color:#fff; border-radius:12px; text-decoration:none; box-shadow:0 4px 12px rgba(99,102,241,0.3);"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg> طلب كود</a>'
            cards += '<form method="POST" action="/my/delete/' + str(nid) + '" style="margin:0;" onsubmit="event.stopPropagation(); return confirm(\'هل أنت متأكد من حذف هذا الرقم من قائمتك؟\');"><button type="submit" class="btn" style="padding:12px; background:rgba(239,68,68,0.15); color:var(--danger); border:1px solid rgba(239,68,68,0.3); border-radius:12px; display:flex; align-items:center; justify-content:center;"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg></button></form>'
            cards += '</div></div>'

        if not cards:
            cards = '<div class="empty">لا أرقام</div>'
        body = f'<div class="container"><div class="section-title">كل أرقامي <span class="section-sub">({len(nums)})</span></div><div class="grid">{cards}</div></div>'

    elif name == "sell":
        body = f'''<div class="container" style="max-width:500px; padding-top:20px;">
          
          <div style="text-align:center; margin-bottom:24px;">
            <div style="width:80px; height:80px; margin:0 auto 16px; background:linear-gradient(135deg, rgba(6,182,212,0.15), rgba(99,102,241,0.15)); border:2px solid #06b6d4; border-radius:50%; display:flex; align-items:center; justify-content:center; box-shadow:0 0 30px rgba(6,182,212,0.3);">
              {site_icon("telegram", 44, ico("telegram", 44))}
            </div>
            <div class="section-title" style="margin-bottom:8px;">بيع رقم تيليجرام</div>
            <p style="color:var(--muted); font-size:13px; line-height:1.7; padding:0 16px;">
              قم ببيع رقمك للبوت وسنقوم بربطه فوراً. سيتم تسجيل الخروج من جهازك تلقائياً لحماية حسابك.
            </p>
          </div>

          <div class="card" style="padding:24px;">
            <form method="POST" action="/sell/request">
              
              <div class="field">
                <label style="display:flex; align-items:center; gap:6px; font-size:13px; font-weight:700;">
                  {ico("phone", 16)} رقم الهاتف (بالصيغة الدولية)
                </label>
                <div style="position:relative;">
                  <div style="position:absolute; right:14px; top:50%; transform:translateY(-50%); color:var(--muted);">
                    {ico("telegram", 18)}
                  </div>
                  <input name="phone" placeholder="+967777123456" required style="direction:ltr; text-align:left; padding:14px 44px 14px 16px; font-size:16px; letter-spacing:1px; width:100%; background:var(--bg2); color:var(--text); border:1.5px solid var(--border); border-radius:12px; font-family:monospace;">
                </div>
              </div>

              <div style="background:rgba(245,158,11,0.08); border:1px solid rgba(245,158,11,0.3); border-radius:12px; padding:12px; margin-bottom:18px; display:flex; align-items:flex-start; gap:10px;">
                <div style="color:#f59e0b; flex-shrink:0; margin-top:2px;">{ico("shield", 20)}</div>
                <div style="font-size:12px; color:var(--text); line-height:1.6;">
                  <b>ملاحظة أمنية:</b> بمجرد طلب الكود، سيتم تسجيل الخروج من حسابك على جهازك الشخصي لضمان عدم استرجاع الرقم.
                </div>
              </div>

              <button class="form-btn" style="padding:16px; font-size:16px; display:flex; align-items:center; justify-content:center; gap:10px; box-shadow:0 4px 20px rgba(99,102,241,0.4);">
                {ico("send", 20)} طلب كود التحقق
              </button>
            </form>

            <div style="display:flex; align-items:center; gap:12px; margin:20px 0;">
              <div style="flex:1; height:1px; background:var(--border);"></div>
              <div style="font-size:12px; color:var(--muted); font-weight:700;">أو</div>
              <div style="flex:1; height:1px; background:var(--border);"></div>
            </div>

            <a href="/sell/prices" class="btn btn-ghost" style="width:100%; display:flex; align-items:center; justify-content:center; gap:8px; padding:14px; font-size:14px;">
              {ico("chart", 18)} عرض أسعار الشراء لكل دولة
            </a>
          </div>
        </div>'''

    elif name == "sell_verify":
        phone = ctx.get("phone", "")
        body = f'''<div class="container" style="max-width:500px; padding-top:20px;">
          
          <div style="text-align:center; margin-bottom:24px;">
            <div style="width:80px; height:80px; margin:0 auto 16px; background:linear-gradient(135deg, rgba(16,185,129,0.15), rgba(6,182,212,0.15)); border:2px solid #10b981; border-radius:50%; display:flex; align-items:center; justify-content:center; box-shadow:0 0 30px rgba(16,185,129,0.3);">
              {ico("key", 40)}
            </div>
            <div class="section-title" style="margin-bottom:8px;">تأكيد الكود</div>
            <p style="color:var(--muted); font-size:13px; line-height:1.7;">تم إرسال كود التحقق إلى رقمك، يرجى إدخاله بالأسفل.</p>
          </div>

          <div class="card" style="padding:24px; text-align:center;">
            
            <div style="display:inline-flex; align-items:center; gap:8px; background:rgba(99,102,241,0.1); border:1px solid rgba(99,102,241,0.3); padding:8px 16px; border-radius:12px; margin-bottom:24px;">
              <span style="font-size:13px; color:var(--muted);">الرقم:</span>
              <strong style="color:var(--primary2); direction:ltr; font-size:16px; font-family:monospace;">{phone}</strong>
            </div>

            <form method="POST" action="/sell/verify">
              <div class="field">
                <input name="code" placeholder="• • • • •" required style="text-align:center; letter-spacing:12px; font-size:28px; padding:16px; background:var(--bg2); color:var(--text); border:2px solid var(--border); border-radius:14px; font-family:monospace; width:100%; font-weight:900; direction:ltr;">
              </div>

              <div style="background:rgba(6,182,212,0.08); border:1px solid rgba(6,182,212,0.3); border-radius:12px; padding:12px; margin-bottom:20px; display:flex; align-items:flex-start; gap:10px; text-align:right;">
                <div style="color:#06b6d4; flex-shrink:0; margin-top:2px;">{ico("message", 20)}</div>
                <div style="font-size:12px; color:var(--text); line-height:1.6;">
                  إذا لم يصلك الكود، تأكد من فتح تطبيق <b>تيليجرام</b> على جهازك، ستجد رسالة تحتوي على الكود.
                </div>
              </div>

              <button class="form-btn" style="padding:16px; font-size:16px; display:flex; align-items:center; justify-content:center; gap:10px; box-shadow:0 4px 20px rgba(16,185,129,0.4); background:linear-gradient(135deg, #10b981, #059669);">
                {ico("check-circle", 20)} تأكيد الرقم
              </button>
            </form>

            <div style="margin-top:20px;">
              <a href="/sell" style="color:var(--muted); font-size:13px; text-decoration:none; display:inline-flex; align-items:center; gap:6px;">
                {ico("arrow-left", 14)} العودة وتغيير الرقم
              </a>
            </div>
          </div>
        </div>'''

    elif name == "sell_2fa":
        body = f'''<div class="container" style="max-width:600px">
          <div class="section-title">التحقق بخطوتين</div>
          <div class="card" style="text-align:center; padding:30px;">
            <p style="color:var(--muted); margin-bottom:20px;">
              هذا الحساب محمي بكلمة مرور (2FA).<br>أدخل كلمة المرور لإكمال عملية البيع.
            </p>
            <form method="POST" action="/sell/2fa">
              <div class="field"><label>كلمة مرور التحقق</label>
                <input name="password" type="password" required>
              </div>
              <button class="form-btn">{ico("lock", 18)} تأكيد البيع</button>
            </form>
          </div>
        </div>'''

    elif name == "deposit":
        method = ctx.get("method")
        
        # ============================================================
        # صفحة قائمة طرق الشحن (الرئيسية)
        # ============================================================
        if not method:
            methods = [
                ("voucher",  "شحن بكود فاوتشر",   "أدخل الكود واستلم الرصيد فوراً",         "#8b5cf6", "ticket"),
                ("jeeb",     "جيب",                "محفظة إلكترونية يمنية",                  "#dc2626", "wallet"),
                ("onecash",  "ون كاش",             "محفظة إلكترونية يمنية",                  "#ea580c", "credit-card"),
                ("binance",  "Binance Pay",        "دفع بالعملات الرقمية USDT",              "#f59e0b", "dollar"),
            ]
            
            cards = ""
            for key, title, desc, accent_color, fb_icon in methods:
                # لون الخلفية لكل صندوق (مع استثناء: جيب = أبيض)
                if key == "jeeb":
                    box_bg = "#ffffff"
                else:
                    box_bg = accent_color
                
                # اسم الأيقونة المرفوعة (jaib بدل jeeb)
                icon_name_map = {
                    "voucher": "voucher",
                    "jeeb": "jaib",
                    "onecash": "onecash",
                    "binance": "binance"
                }
                real_icon_name = icon_name_map.get(key, key)
                fallback_svg = ico(fb_icon, 30)
                icon_html = site_icon(real_icon_name, 34, fallback_svg)
                
                cards += (
                    f'<a href="/deposit/{key}" '
                    f'style="display:flex;align-items:center;gap:14px;padding:14px;'
                    f'background:var(--card);border:1px solid var(--border);'
                    f'border-right:4px solid {accent_color};border-radius:14px;'
                    f'text-decoration:none;color:var(--text);margin-bottom:10px;">'
                    f'<div style="width:56px;height:56px;display:flex;align-items:center;justify-content:center;'
                    f'background:{box_bg};border-radius:14px;flex-shrink:0;padding:6px;'
                    f'box-shadow: 0 4px 12px {box_bg}40;">'
                    f'<div style="display:flex;align-items:center;justify-content:center;width:100%;height:100%;">'
                    f'{icon_html}</div></div>'
                    f'<div style="flex:1; min-width:0;">'
                    f'<div style="font-size:14px;font-weight:800;color:var(--text);margin-bottom:2px;">{title}</div>'
                    f'<div style="font-size:11px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{desc}</div>'
                    f'</div>'
                    f'<div style="color:{accent_color};flex-shrink:0;">{ico("arrow-left", 18)}</div>'
                    f'</a>'
                )
            
            body = f'''<div class="container" style="max-width:600px; padding-top:20px;">
                <div style="text-align:center; margin-bottom:24px;">
                    <div class="section-title" style="margin-bottom:8px;">شحن الرصيد</div>
                    <div style="font-size:13px; color:var(--muted);">اختر طريقة الشحن المناسبة لك</div>
                </div>
                
                <div style="background:linear-gradient(135deg, rgba(16,185,129,0.1), rgba(6,182,212,0.05)); border:1px solid rgba(16,185,129,0.3); border-radius:16px; padding:16px; margin-bottom:24px; display:flex; justify-content:space-between; align-items:center;">
                    <div>
                        <div style="font-size:12px; color:var(--muted); margin-bottom:4px;">رصيدك الحالي</div>
                        <div style="font-size:24px; font-weight:900; color:#10b981; direction:ltr;">${u["balance"]:.2f}</div>
                    </div>
                    <div style="text-align:left;">
                        <div style="font-size:11px; color:var(--muted); margin-bottom:4px;">العملة</div>
                        <div style="font-size:13px; font-weight:800; color:var(--text);">USDT</div>
                    </div>
                </div>
                
                <div style="display:flex; flex-direction:column;">
                    {cards}
                </div>
            </div>'''
            return page("deposit_menu", body=body)
        
        # ============================================================
        # الصفحات الفرعية (جيب، ون كاش، بينانس، فاوتشر) - التصميم الجميل
        # ============================================================
        else:
            back_btn = (
                f'<a href="/deposit" class="btn btn-ghost btn-sm" '
                f'style="display:inline-flex;align-items:center;gap:6px;margin-bottom:16px">'
                f'{ico("arrow-left", 14)} رجوع</a>'
            )
            
            colors_map = {
                "voucher": "#8b5cf6",
                "jeeb": "#ffffff",  # جيب أبيض
                "onecash": "#ea580c",
                "binance": "#f59e0b"
            }
            icon_names_map = {
                "voucher": "voucher",
                "jeeb": "jaib",
                "onecash": "onecash",
                "binance": "binance"
            }
            titles_map = {
                "voucher": "شحن بكود فاوتشر",
                "jeeb": "جيب",
                "onecash": "ون كاش",
                "binance": "Binance Pay"
            }
            
            method_color = colors_map.get(method, "#8b5cf6")
            method_icon_name = icon_names_map.get(method, method)
            method_title = titles_map.get(method, method)
            icon_html = site_icon(method_icon_name, 34, ico("wallet", 34))
            
            # لون الأيقونة (لو الخلفية بيضاء، نستخدم لون بنفسجي للأيقونة)
            icon_border_style = f'border:1px solid #ddd;' if method == 'jeeb' else ''
            
            header = (
                f'<div style="display:flex;align-items:center;gap:12px;margin-bottom:20px">'
                f'<div style="width:56px;height:56px;display:flex;align-items:center;justify-content:center;'
                f'background:{method_color};border-radius:14px;padding:6px;{icon_border_style}">{icon_html}</div>'
                f'<h2 style="font-size:22px;font-weight:900;margin:0">{method_title}</h2>'
                f'</div>'
            )
            
            if method == "voucher":
                support_user = get_setting("SUPPORT_USER", "@MO_5_H")
                content = f'''
                  <div class="card" style="padding:24px;">
                    
                    <div style="background:rgba(245,158,11,0.08); border:1px solid rgba(245,158,11,0.3); border-radius:14px; padding:16px; margin-bottom:20px;">
                      <div style="display:flex; gap:12px; align-items:flex-start; margin-bottom:12px;">
                        <div style="color:#f59e0b; flex-shrink:0; margin-top:2px;">{ico("info", 22)}</div>
                        <div style="font-size:13px; color:var(--text); line-height:1.7;">
                          <b style="color:#f59e0b;">ملاحظة هامة:</b><br>
                          إذا لم تكن طريقة الدفع متاحة في بلدك، أو لم تتمكن من الحصول على كود شحن، يمكنك التواصل مع فريق الدعم مباشرة لشراء كود شحن بأي طريقة دفع أخرى تناسبك.
                        </div>
                      </div>
                      <a href="/support" style="display:flex; align-items:center; justify-content:center; gap:8px; width:100%; padding:12px; background:linear-gradient(135deg, #f59e0b, #ea580c); color:#fff; border-radius:10px; font-weight:800; font-size:14px; text-decoration:none; box-shadow:0 4px 12px rgba(245,158,11,0.3);">
                        {ico("message", 18)} تواصل مع الدعم الآن
                      </a>
                    </div>

                    <p style="color:var(--muted);font-size:13px;margin-bottom:14px">أدخل كود الشحن الذي حصلت عليه، وسيضاف رصيده إلى حسابك فوراً.</p>
                    <form method="POST">
                      <input type="hidden" name="method" value="voucher">
                      <div class="field"><label>كود الشحن</label>
                        <input name="code" placeholder="MT-XXXXXXXX" required style="font-family:monospace;text-align:center;text-transform:uppercase">
                      </div>
                      <button class="form-btn">تفعيل الكود</button>
                    </form>
                  </div>'''
            
            elif method in ("jeeb", "onecash"):
                acc_key = "JEEB_ACCOUNT" if method == "jeeb" else "ONECASH_ACCOUNT"
                rate_ye = "JEEB_RATE_YE" if method == "jeeb" else "ONECASH_RATE_YE"
                rate_sa = "JEEB_RATE_SA" if method == "jeeb" else "ONECASH_RATE_SA"
                acc = get_setting(acc_key, "")
                r_ye = get_setting(rate_ye, "540")
                r_sa = get_setting(rate_sa, "3.75")
                content = f'''
                  <div class="card" style="padding:20px; margin-bottom:16px;">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
                        <span style="font-size:14px; font-weight:700; color:var(--text);">1. رقم الحساب</span>
                        {ico("wallet", 20)}
                    </div>
                    <div style="display:flex; align-items:center; gap:10px; background:var(--bg2); padding:16px; border-radius:12px; border:1px dashed var(--border);">
                      <span style="font-family:monospace; font-size:20px; direction:ltr; flex:1; color:var(--primary2); font-weight:900; letter-spacing:1px;">{acc}</span>
                      <button onclick="copyText('{acc}', this)" class="btn btn-sm" style="padding:8px 14px; background:rgba(99,102,241,0.1); color:var(--primary2); border:1px solid rgba(99,102,241,0.3); font-weight:700; border-radius:8px;">{ico("copy", 14)} نسخ</button>
                    </div>
                  </div>

                  <div class="card" style="padding:20px; margin-bottom:16px;">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
                        <span style="font-size:14px; font-weight:700; color:var(--text);">2. أسعار الصرف</span>
                        {ico("chart", 20)}
                    </div>
                    <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px;">
                        <div style="background:rgba(16,185,129,0.05); border:1px solid rgba(16,185,129,0.2); border-radius:10px; padding:12px; text-align:center;">
                            <div style="font-size:11px; color:var(--muted); margin-bottom:4px;">اليمن</div>
                            <div style="font-size:13px; font-weight:900; color:#10b981; direction:ltr;">1$ = {r_ye}</div>
                        </div>
                        <div style="background:rgba(16,185,129,0.05); border:1px solid rgba(16,185,129,0.2); border-radius:10px; padding:12px; text-align:center;">
                            <div style="font-size:11px; color:var(--muted); margin-bottom:4px;">السعودية</div>
                            <div style="font-size:13px; font-weight:900; color:#10b981; direction:ltr;">1$ = {r_sa}</div>
                        </div>
                    </div>
                  </div>

                  <div class="card" style="padding:20px;">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
                        <span style="font-size:14px; font-weight:700; color:var(--text);">3. المبلغ المطلوب</span>
                        {ico("dollar", 20)}
                    </div>
                    <form method="POST">
                      <input type="hidden" name="method" value="{method}">
                      <div style="margin-bottom:16px;">
                        <input name="amount" type="number" step="0.01" min="0.10" placeholder="مثال: 5.00" required style="width:100%; padding:16px; background:var(--bg2); color:var(--text); border:2px solid var(--border); border-radius:12px; font-size:18px; font-weight:700; direction:ltr; transition:border-color 0.2s;">
                      </div>
                      <button class="form-btn" style="padding:16px; font-size:16px; border-radius:12px;">{ico("send", 18)} إرسال طلب الشحن</button>
                    </form>
                  </div>'''
            
            elif method == "binance":
                pay_id = get_setting("BINANCE_PAY_ID", "")
                content = f'''
                  <div class="card" style="padding:20px; margin-bottom:16px;">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
                        <span style="font-size:14px; font-weight:700; color:var(--text);">1. أرسل المبلغ إلى:</span>
                        <span style="display:flex; align-items:center; gap:6px; color:#f59e0b; font-weight:800; font-size:11px; background:rgba(245,158,11,0.1); padding:4px 10px; border-radius:8px;">
                          {site_icon("binance", 14, ico("dollar", 14))} Pay ID
                        </span>
                    </div>
                    <div style="display:flex; align-items:center; gap:10px; background:var(--bg2); padding:16px; border-radius:12px; border:2px dashed var(--warn);">
                      <span style="font-family:monospace; font-size:20px; direction:ltr; flex:1; color:#f59e0b; font-weight:900; letter-spacing:1px;">{pay_id}</span>
                      <button onclick="copyText('{pay_id}', this)" class="btn btn-sm" style="padding:8px 14px; background:rgba(245,158,11,0.15); color:#f59e0b; border:1px solid rgba(245,158,11,0.4); font-weight:700; border-radius:8px;">{ico("copy", 14)} نسخ</button>
                    </div>
                  </div>

                  <div class="card" style="padding:20px;">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
                        <span style="font-size:14px; font-weight:700; color:var(--text);">2. تأكيد الدفع</span>
                        {ico("shield", 20)}
                    </div>
                    <div style="background:rgba(99,102,241,0.05); border:1px solid rgba(99,102,241,0.2); border-radius:10px; padding:12px; margin-bottom:16px; font-size:12px; color:var(--muted); line-height:1.7;">
                        بعد إتمام التحويل، انسخ <b style="color:var(--text);">Order ID</b> من تطبيق Binance، وأدخله هنا مع المبلغ الذي أرسلته.
                    </div>
                    <form method="POST" action="/deposit/binance_verify">
                      <div style="margin-bottom:14px;">
                        <label style="display:block; font-size:12px; font-weight:700; margin-bottom:6px; color:var(--muted);">المبلغ بالدولار</label>
                        <input name="amount" type="number" step="0.01" min="0.10" placeholder="5.00" required style="width:100%; padding:14px; background:var(--bg2); color:var(--text); border:1.5px solid var(--border); border-radius:10px; font-size:16px; font-weight:700; direction:ltr;">
                      </div>
                      <div style="margin-bottom:20px;">
                        <label style="display:block; font-size:12px; font-weight:700; margin-bottom:6px; color:var(--muted);">Order ID (رقم العملية)</label>
                        <input name="order_id" type="text" placeholder="123456789" required style="width:100%; padding:14px; background:var(--bg2); color:var(--text); border:1.5px solid var(--border); border-radius:10px; font-size:14px; direction:ltr; text-align:left; font-family:monospace;">
                      </div>
                      <button class="form-btn" style="padding:16px; font-size:16px; background:linear-gradient(135deg, #f59e0b, #ea580c); box-shadow:0 4px 15px rgba(245,158,11,0.3);">{ico("check", 20)} تأكيد الدفع تلقائياً</button>
                    </form>
                  </div>'''
            else:
                content = f'<div class="card">طريقة غير معروفة</div>'
            
            body = f'''<div class="container" style="max-width:600px">
              {back_btn}
              {header}
              {content}
            </div>'''
            return page("deposit_sub", body=body, method=method)



    elif name == "deposit_menu":
        body = ctx.get("body", "")
    
    elif name == "deposit_sub":
        body = ctx.get("body", "")

    elif name == "register":
        import os as _os
        # نتحقق من وجود صورة الـ Hero
        hero_url = _site_icon_url("login_hero")
        
        hero_style = f"background-image: url('{hero_url}');" if hero_url else "background: linear-gradient(135deg, #0a1428, #0f1e3d);"
        
        body = f'''
        <style>
          .register-page {{
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            background: #0a1428;
            padding: 0;
            margin: 0;
          }}
          .register-hero {{
            position: relative;
            width: 100%;
            height: auto;
            min-height: 240px;
            max-height: 400px;
            {hero_style}
            background-size: cover;
            background-position: center top;
            background-repeat: no-repeat;
            border-radius: 0 0 30px 30px;
            margin: 0;
            padding: 0;
            box-shadow: none;
            background-color: #0a1428;
            border: none;
          }}
          
          .register-main {{
            flex: 1;
            padding: 0 16px 30px;
            margin-top: -10px;
            position: relative;
            z-index: 2;
          }}
          .register-card {{
            background: linear-gradient(180deg, #0f1f3d 0%, #0a1428 100%);
            border: 2px solid #1e90ff;
            border-radius: 30px;
            padding: 32px 24px 30px;
            box-shadow: 0 0 15px rgba(30, 144, 255, 0.15);
            position: relative;
            overflow: hidden;
            width: 100%;
          }}
          .register-card::before {{
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 3px;
            background: linear-gradient(90deg, transparent, #1e90ff, transparent);
            box-shadow: 0 0 20px #1e90ff;
          }}
          .register-logo-wrap {{
            display: flex;
            justify-content: center;
            margin-bottom: 20px;
          }}
          .register-logo {{
            width: 80px;
            height: 80px;
            border-radius: 50%;
            background: linear-gradient(135deg, #1e90ff, #00d4ff);
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 0 15px rgba(30, 144, 255, 0.3);
            position: relative;
            overflow: hidden;
          }}
          .register-logo img {{
            width: 100%;
            height: 100%;
            object-fit: cover;
            border-radius: 50%;
          }}
          .register-logo svg {{
            filter: drop-shadow(0 2px 8px rgba(0,0,0,0.3));
          }}
          .register-title {{
            text-align: center;
            font-size: 24px;
            font-weight: 900;
            margin-bottom: 6px;
            color: #fff;
            letter-spacing: 1px;
          }}
          .register-sub {{
            text-align: center;
            font-size: 13px;
            color: #6b8ab8;
            margin-bottom: 24px;
            font-weight: 500;
          }}
          .register-field {{
            position: relative;
            margin-bottom: 14px;
          }}
          .register-field svg {{
            position: absolute;
            right: 18px;
            top: 50%;
            transform: translateY(-50%);
            color: #00d4ff;
            pointer-events: none;
          }}
          .register-field input {{
            width: 100%;
            padding: 16px 50px 16px 65px;
            background: rgba(10, 20, 40, 0.8);
            color: #fff;
            border: 1.5px solid rgba(30, 144, 255, 0.35);
            border-radius: 14px;
            font-size: 15px;
            font-family: inherit;
            transition: all 0.3s;
          }}
          .register-field input:focus {{
            outline: none;
            border-color: #00d4ff;
            background: rgba(10, 20, 40, 0.95);
            box-shadow: 0 0 0 2px rgba(30, 144, 255, 0.1);
          }}
          .register-field input::placeholder {{
            color: #5a7a9e;
          }}
          .password-toggle {{
            position: absolute;
            left: 16px;
            top: 50%;
            margin-top: -12px;
            background: transparent;
            border: none;
            cursor: pointer;
            color: #00d4ff;
            padding: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            opacity: 0.8;
            transition: opacity 0.2s;
            z-index: 10;
            width: 24px;
            height: 24px;
            line-height: 1;
          }}
          .password-toggle:hover {{
            opacity: 1;
          }}
          .password-toggle:active {{
          }}
          .register-btn {{
            width: 100%;
            padding: 16px;
            background: linear-gradient(135deg, #1e90ff, #00d4ff);
            color: #fff;
            border: none;
            border-radius: 14px;
            font-size: 16px;
            font-weight: 900;
            cursor: pointer;
            margin-top: 16px;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
            transition: all 0.3s;
            box-shadow: 0 4px 12px rgba(30, 144, 255, 0.3);
          }}
          .register-btn:hover {{
            transform: translateY(-2px);
            box-shadow: 0 12px 32px rgba(0, 212, 255, 0.7);
          }}
          .register-footer {{
            text-align: center;
            color: #6b8ab8;
            font-size: 13px;
            margin-top: 20px;
            padding-top: 16px;
            border-top: 1px solid rgba(30, 144, 255, 0.2);
          }}
          .register-footer a {{
            color: #00d4ff;
            font-weight: 800;
            text-decoration: none;
          }}
        </style>
        
        <div class="register-page">
          <div class="register-hero"></div>
          <div class="register-main">
            <div class="register-card">
              <div class="register-logo-wrap">
                <div class="register-logo" style="background: transparent; border: none; box-shadow: none; overflow: visible; position: relative;">
                  <div style="mix-blend-mode: screen; filter: contrast(1.2) brightness(1.1); display: inline-block;">
                    {site_icon("site_logo", 150, '<svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>')}
                  </div>
                  
                </div>
              </div>
              <div class="register-title">إنشاء حساب</div>
              <div class="register-sub">انضم إلى MATARI STORE</div>
              {fh}
              {f'<div style="background:rgba(239,68,68,0.1); border:1px solid rgba(239,68,68,0.3); border-radius:10px; padding:10px 14px; margin-bottom:14px; font-size:11px; color:#ef4444; font-weight:700;">{ico("warning", 14)} نظام الإحالات متوقف حالياً، لن يحصل صاحب الرابط على مكافأة عند تسجيلك.</div>' if request.args.get("ref") and get_setting("REFERRAL_ENABLED", "1") != "1" else ''}
              <form method="POST">
                <div class="register-field">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
                  <input name="username" placeholder="اسم المستخدم" required minlength="3" autocomplete="username">
                </div>
                <div class="register-field">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
                  <input name="password" type="password" placeholder="كلمة المرور" id="reg_pw1" required minlength="6" autocomplete="new-password">
                  <button type="button" class="password-toggle" onclick="togglePass('reg_pw1', this)">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                  </button>
                </div>
                <div class="register-field">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><polyline points="9 12 11 14 15 10"/></svg>
                  <input name="password2" type="password" placeholder="تأكيد كلمة المرور" id="reg_pw2" required minlength="6" autocomplete="new-password">
                  <button type="button" class="password-toggle" onclick="togglePass('reg_pw2', this)">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                  </button>
                </div>
                <input type="hidden" name="ref" value="{request.args.get('ref', '')}">
                <div style="display:flex; align-items:center; justify-content: flex-start; margin: 8px 0 20px 0; padding: 0 4px;">
                  <label style="display: flex; align-items: center; gap: 10px; cursor: pointer; user-select: none;">
                    <div style="position: relative; width: 36px; height: 20px; background: rgba(0, 212, 255, 0.2); border-radius: 10px; border: 1px solid rgba(0, 212, 255, 0.4); transition: all 0.3s;">
                      <input type="checkbox" name="remember" value="1" style="opacity: 0; position: absolute; width: 100%; height: 100%; cursor: pointer; z-index: 2; margin: 0;" onchange="this.nextElementSibling.style.transform = this.checked ? 'translateX(-16px)' : 'translateX(0)'; this.nextElementSibling.style.background = this.checked ? '#00d4ff' : '#1e3a5f';">
                      <div style="position: absolute; top: 2px; right: 2px; width: 14px; height: 14px; background: #fff; border-radius: 50%; transition: all 0.3s; transform: translateX(0);"></div>
                    </div>
                    <span style="font-size: 13px; color: #6b8ab8; font-weight: 600;">حفظ حسابي (تسجيل دائم)</span>
                  </label>
                </div>
                <button class="register-btn" type="submit">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/><line x1="20" y1="8" x2="20" y2="14"/><line x1="23" y1="11" x2="17" y2="11"/></svg>
                  إنشاء الحساب
                </button>
              </form>
              <div class="register-footer">
                عندك حساب؟ <a href="/login">سجّل دخول</a>
              </div>
            </div>
          </div>
        </div>
        <script>
        function togglePass(id, btn) {{
          var input = document.getElementById(id);
          var svg = btn.querySelector('svg');
          if (input.type === 'password') {{
            input.type = 'text';
            svg.innerHTML = '<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/>';
          }} else {{
            input.type = 'password';
            svg.innerHTML = '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>';
          }}
        }}
        </script>
        '''


    elif name == "login":
        import os as _os
        # نتحقق من وجود صورة الـ Hero
        hero_url = _site_icon_url("login_hero")
        
        hero_style = f"background-image: url('{hero_url}');" if hero_url else "background: linear-gradient(135deg, #0a1428, #0f1e3d);"
        
        body = f'''
        <style>
          .login-page {{
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            background: #0a1428;
            padding: 0;
            margin: 0;
          }}
          .login-hero {{
            position: relative;
            width: 100%;
            height: auto;
            min-height: 240px;
            max-height: 400px;
            {hero_style}
            background-size: cover;
            background-position: center top;
            background-repeat: no-repeat;
            border-radius: 0 0 30px 30px;
            margin: 0;
            padding: 0;
            box-shadow: none;
            background-color: #0a1428;
            border: none;
          }}
          
          .login-main {{
            flex: 1;
            padding: 0 16px 30px;
            margin-top: -10px;
            position: relative;
            z-index: 2;
          }}
          .login-card {{
            background: linear-gradient(180deg, #0f1f3d 0%, #0a1428 100%);
            border: 2px solid #1e90ff;
            border-radius: 30px;
            padding: 40px 24px 30px;
            box-shadow: 0 0 15px rgba(30, 144, 255, 0.15);
            position: relative;
            overflow: hidden;
            width: 100%;
            max-width: 100%;
            transition: box-shadow 0.4s ease, transform 0.4s ease;
          }}

          .login-card::before {{
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 3px;
            background: linear-gradient(90deg, transparent, #1e90ff, transparent);
            box-shadow: 0 0 20px #1e90ff;
          }}
          .login-logo-wrap {{
            display: flex;
            justify-content: center;
            margin-bottom: 24px;
            position: relative;
          }}
          .login-logo {{
            width: 80px;
            height: 80px;
            border-radius: 50%;
            background: linear-gradient(135deg, #1e90ff, #00d4ff);
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 0 15px rgba(30, 144, 255, 0.3);
            position: relative;
            overflow: hidden;
          }}
          .login-logo img {{
            width: 100%;
            height: 100%;
            object-fit: cover;
            border-radius: 50%;
          }}
          .login-logo svg {{
            filter: drop-shadow(0 2px 8px rgba(0,0,0,0.3));
          }}
          /* removed animation for performance */
          .login-brand-title {{
            text-align: center;
            font-size: 26px;
            font-weight: 900;
            margin-bottom: 6px;
            letter-spacing: 2px;
            color: #ffffff;
          }}
          .login-brand-title .brand-accent {{
            color: #00d4ff;
          }}
          .login-brand-sub {{
            text-align: center;
            font-size: 13px;
            color: #6b8ab8;
            margin-bottom: 30px;
            font-weight: 500;
          }}
          .login-field {{
            position: relative;
            margin-bottom: 14px;
          }}
          .login-field svg {{
            position: absolute;
            right: 18px;
            top: 50%;
            transform: translateY(-50%);
            color: #00d4ff;
            pointer-events: none;
          }}
          .login-field input {{
            width: 100%;
            padding: 16px 50px 16px 65px;
            background: rgba(10, 20, 40, 0.8);
            color: #fff;
            border: 1.5px solid rgba(30, 144, 255, 0.35);
            border-radius: 14px;
            font-size: 15px;
            font-family: inherit;
            transition: all 0.3s;
          }}
          .login-field input:focus {{
            outline: none;
            border-color: #00d4ff;
            background: rgba(10, 20, 40, 0.95);
            box-shadow: 0 0 0 2px rgba(30, 144, 255, 0.1);
          }}
          .login-field input::placeholder {{
            color: #7a9ac0;
            opacity: 1;
          }}
          .login-field .password-toggle {{
            position: absolute;
            left: 14px;
            top: 50%;
            margin-top: -15px;
            background: transparent;
            border: none;
            cursor: pointer;
            color: #00d4ff;
            padding: 6px;
            display: flex;
            align-items: center;
            justify-content: center;
            opacity: 0.8;
            transition: opacity 0.2s;
            z-index: 10;
            width: 30px;
            height: 30px;
            line-height: 1;
          }}
          .login-field .password-toggle:hover {{
            opacity: 1;
          }}
          .login-field .password-toggle:active {{
          }}
          .login-btn {{
            width: 100%;
            padding: 16px;
            background: linear-gradient(135deg, #1e90ff, #00d4ff);
            color: #fff;
            border: none;
            border-radius: 14px;
            font-size: 16px;
            font-weight: 900;
            cursor: pointer;
            margin-top: 16px;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
            transition: all 0.3s;
            box-shadow: 0 4px 12px rgba(30, 144, 255, 0.3);
            letter-spacing: 1px;
          }}
          .login-btn:hover {{
            transform: translateY(-2px);
            box-shadow: 0 12px 32px rgba(0, 212, 255, 0.7);
          }}
          .login-divider {{
            display: flex;
            align-items: center;
            gap: 12px;
            margin: 24px 0 16px;
            color: #5a7a9e;
            font-size: 11px;
            font-weight: 700;
          }}
          .login-divider::before,
          .login-divider::after {{
            content: '';
            flex: 1;
            height: 1px;
            background: linear-gradient(to right, transparent, rgba(30, 144, 255, 0.5), transparent);
          }}
          .login-register-btn {{
            width: 100%;
            padding: 14px;
            background: transparent;
            color: #00d4ff;
            border: 1.5px solid rgba(30, 144, 255, 0.5);
            border-radius: 14px;
            font-size: 14px;
            font-weight: 800;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            transition: all 0.3s;
            text-decoration: none;
          }}
          .login-register-btn:hover {{
            background: rgba(30, 144, 255, 0.1);
            border-color: #00d4ff;
            box-shadow: 0 4px 16px rgba(30, 144, 255, 0.3);
          }}
          .login-brand-foot {{
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 6px;
            color: #5a7a9e;
            font-size: 11px;
            font-weight: 600;
            margin-top: 24px;
            padding-top: 20px;
            border-top: 1px solid rgba(30, 144, 255, 0.2);
          }}
        </style>
        
        <div class="login-page">
          <div class="login-hero"></div>
          
          <div class="login-main">
            <div class="login-card">
              <div class="login-logo-wrap">
                <div class="login-logo" style="background: transparent; border: none; box-shadow: none; overflow: visible; position: relative;">
                  <div style="mix-blend-mode: screen; filter: contrast(1.2) brightness(1.1); display: inline-block;">
                    {site_icon("site_logo", 150, '<svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>')}
                  </div>
                  
                </div>
              </div>
              
              <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
                <a href="/" style="display:flex; align-items:center; gap:6px; color:#6b8ab8; font-size:13px; text-decoration:none;">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>
                  الرئيسية
                </a>
                <span style="font-size:11px; color:#3a5a7e;">MATARI STORE</span>
              </div>
              <div class="login-brand-title">MATARI <span class="brand-accent">STORE</span></div>
              <div class="login-brand-sub">سجّل دخولك إلى حسابك</div>
              
              {fh}
              
              <form method="POST">
                <div class="login-field">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>
                  <input name="ident" placeholder="اسم المستخدم أو الإيميل" required autofocus>
                </div>
                <div class="login-field">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
                  <input name="password" type="password" placeholder="كلمة المرور" id="login_pw" required>
                  <button type="button" class="password-toggle" onclick="toggleLoginPass('login_pw', this)">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                  </button>
                </div>
                <div style="display:flex; align-items:center; justify-content: flex-start; margin: 8px 0 20px 0; padding: 0 4px;">
                  <label style="display: flex; align-items: center; gap: 10px; cursor: pointer; user-select: none;">
                    <div style="position: relative; width: 36px; height: 20px; background: rgba(0, 212, 255, 0.2); border-radius: 10px; border: 1px solid rgba(0, 212, 255, 0.4); transition: all 0.3s;">
                      <input type="checkbox" name="remember" value="1" style="opacity: 0; position: absolute; width: 100%; height: 100%; cursor: pointer; z-index: 2; margin: 0;" onchange="this.nextElementSibling.style.transform = this.checked ? 'translateX(-16px)' : 'translateX(0)'; this.nextElementSibling.style.background = this.checked ? '#00d4ff' : '#1e3a5f';">
                      <div style="position: absolute; top: 2px; right: 2px; width: 14px; height: 14px; background: #fff; border-radius: 50%; transition: all 0.3s; transform: translateX(0);"></div>
                    </div>
                    <span style="font-size: 13px; color: #6b8ab8; font-weight: 600;">حفظ حسابي (تسجيل دائم)</span>
                  </label>
                </div>
                <button class="login-btn" type="submit">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>
                  تسجيل الدخول
                </button>
              </form>
              
              <div class="login-divider"><span style="font-size: 14px; font-weight: 800; letter-spacing: 2px; color: #6b8ab8;">أو</span></div>
              <a href="/register" class="login-register-btn">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/><line x1="20" y1="8" x2="20" y2="14"/><line x1="23" y1="11" x2="17" y2="11"/></svg>
                إنشاء حساب جديد
              </a>
              
              <div class="login-brand-foot">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
                MATARI STORE © 2026
              </div>
            </div>
          </div>
        </div>
        <script>
        function toggleLoginPass(id, btn) {{
          var input = document.getElementById(id);
          var svg = btn.querySelector('svg');
          if (input.type === 'password') {{
            input.type = 'text';
            svg.innerHTML = '<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/>';
          }} else {{
            input.type = 'password';
            svg.innerHTML = '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>';
          }}
        }}
        </script>
        '''


    elif name == "sell_remove_2fa":
        phone = ctx.get("phone", "")
        body = f'''
        <div class="container" style="max-width:600px">
          <div class="section-title">فك التحقق بخطوتين</div>
          <div class="card" style="text-align:center; padding:30px;">
            <div style="width:80px; height:80px; margin:0 auto 20px; background:linear-gradient(135deg, rgba(245,158,11,0.15), rgba(239,68,68,0.15)); border-radius:50%; display:flex; align-items:center; justify-content:center; border:2px solid #f59e0b; box-shadow:0 0 25px rgba(245,158,11,0.3);">
              <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/><circle cx="12" cy="16" r="1.5" fill="#f59e0b"/></svg>
            </div>
            <h2 style="font-size:22px; margin-bottom:8px; font-weight:900;">الرقم عليه حماية</h2>
            <p style="color:var(--muted); margin-bottom:20px; line-height:1.7;">الرقم <strong style="color:var(--primary2);">{phone}</strong> عليه تحقق بخطوتين.<br>أدخل كلمة السر الحالية عشان نفك الحماية ونكمل البيع.</p>
            <form method="POST">
              <div class="field"><label>كلمة السر الحالية (2FA)</label>
                <input name="password" type="password" required style="text-align:center;">
              </div>
              <button class="form-btn">فك الحماية وإكمال البيع</button>
            </form>
            <a href="/sell" class="btn btn-ghost" style="width:100%; margin-top:12px;">إلغاء</a>
          </div>
        </div>
        '''
        # (هذا الكود داخل page، لازم يكون body = بدل return page)

    elif name == "dashboard":
        nums = ctx.get("my_numbers", [])
        unread_count_dash = 0
        try:
            unread_count_dash = db().execute("SELECT COUNT(*) as c FROM numbers WHERE buyer_id=? AND seen_by_buyer=0", (u["user_id"],)).fetchone()["c"]
        except Exception:
            pass
        deps = ctx.get("my_deposits", [])
        
        try:
            pending_count = db().execute("""
                SELECT COUNT(*) c FROM pending_balance pb
                INNER JOIN numbers n ON n.id = pb.number_id
                WHERE pb.user_id = ? AND n.phone IS NOT NULL AND n.phone != ''
            """, (u["user_id"],)).fetchone()["c"]
        except Exception:
            pending_count = 0
        
        try:
            pending_count = db().execute("""
                SELECT COUNT(*) c FROM pending_balance pb
                INNER JOIN numbers n ON n.id = pb.number_id
                WHERE pb.user_id = ? AND n.phone IS NOT NULL AND n.phone != ''
            """, (u["user_id"],)).fetchone()["c"]
        except:
            pending_count = 0
        
        # حساب عدد الأرقام المعلقة للمستخدم
        try:
            pending_count = db().execute("""
                SELECT COUNT(*) c FROM pending_balance pb
                INNER JOIN numbers n ON n.id = pb.number_id
                WHERE pb.user_id = ? AND n.phone IS NOT NULL AND n.phone != ''
            """, (u["user_id"],)).fetchone()["c"]
        except:
            pending_count = 0
        nh_parts = []
        time_btn = ""
        new_badge = ""
        _prem_img = ""
        for n in nums:
            is_new = (n["seen_by_buyer"] if "seen_by_buyer" in n.keys() else 1) == 0
            platform_lower = str(n["platform"]).lower()
            if "telegram" in platform_lower or "session" in platform_lower:
                border_color = "#06b6d4"
                badge_text = site_icon("telegram", 14, ico("telegram", 14)) + " تيليجرام"
                badge_class = "telegram"
            elif "whatsapp" in platform_lower:
                border_color = "#25d366"
                badge_text = site_icon("whatsapp", 14, ico("whatsapp", 14)) + " واتساب"
                badge_class = "whatsapp"
            else:
                border_color = "var(--primary2)"
                badge_text = str(n["platform"])
                badge_class = "whatsapp"
                new_badge = ""
            if is_new:
                new_badge = '<span style="background:#ef4444;color:#fff;font-size:9px;font-weight:900;padding:3px 8px;border-radius:20px;animation:pulse 1.5s infinite;">جديد</span>'
                        # إضافة بادج "مميز" لو الرقم مميز
            is_prem = bool(n["is_premium"] if "is_premium" in n.keys() else 0)

            new_badge = ""
            if is_new:
                new_badge = '<span style="background:#ef4444;color:#fff;font-size:9px;font-weight:900;padding:3px 8px;border-radius:20px;animation:pulse 1.5s infinite;">جديد</span>'
                
            if bool(n["is_premium"] if "is_premium" in n.keys() else 0):
                _default_prem = '<svg viewBox="0 0 100 100" style="width:100%;height:100%;filter:drop-shadow(0 2px 5px rgba(0,0,0,.6))"><defs><linearGradient id="gs' + str(n["id"]) + '" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fbbf24"/><stop offset=".5" stop-color="#f59e0b"/><stop offset="1" stop-color="#b45309"/></linearGradient></defs><circle cx="50" cy="50" r="46" fill="url(#gs' + str(n["id"]) + ')"/><circle cx="50" cy="50" r="42" fill="none" stroke="#fff" stroke-width="1.5" opacity=".7"/><text x="50" y="52" font-family="Georgia,serif" font-size="32" font-weight="900" font-style="italic" fill="#fff" text-anchor="middle">M</text><text x="50" y="78" font-family="Cairo,sans-serif" font-size="14" font-weight="900" fill="#fff" text-anchor="middle">مميز</text></svg>'
                _prem_img = site_icon("premium_icon", 22, _default_prem)
                new_badge += '<div style="width:22px;height:22px;display:inline-flex;align-items:center;justify-content:center;vertical-align:middle;margin-right:4px;">' + _prem_img + '</div>'
            border_style = f'border-right:4px solid {border_color};' if is_new else f'border-right:4px solid {border_color};opacity:0.7;'
            import time as _time
            from datetime import datetime as _dt
            time_left_html = ""
            if n["sold_at"]:
                try:
                    sold_ts = _dt.strptime(n["sold_at"], "%Y-%m-%d %H:%M:%S").timestamp()
                    left_sec = int((sold_ts + 259200) - _time.time())
                    if left_sec > 0:
                        time_left_html = '<div class="live-timer" data-end="' + str(int(sold_ts + 259200)) + '" style="display:flex;align-items:center;justify-content:center;gap:6px;background:rgba(245,158,11,0.1);border:1px solid rgba(245,158,11,0.3);color:#f59e0b;padding:6px;border-radius:8px;font-size:11px;font-weight:800;margin-bottom:12px;"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg> الوقت المتبقي: <span class="timer-val">جاري الحساب...</span></div>'
                    else:
                        time_left_html = '<div style="display:flex;align-items:center;justify-content:center;gap:6px;background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.3);color:#ef4444;padding:6px;border-radius:8px;font-size:11px;font-weight:800;margin-bottom:12px;">انتهت الصلاحية</div>'
                except: pass

            nh_parts.append(f'''<div class="num-card" onclick="location.href='/my/number/{n['id']}'" style="{border_style}">
              <div class="num-head" style="display:flex; justify-content:space-between; align-items:center; width:100%; margin-bottom: 12px; gap: 6px; border-bottom: 1px solid rgba(255,255,255,0.05); padding-bottom: 12px;">
                <div style="display:flex; align-items:center; gap:6px; background:rgba(0,0,0,0.2); padding:4px 8px 4px 4px; border-radius:12px; border:1px solid rgba(255,255,255,0.05);">
                    <span class="badge {badge_class}" style="display:inline-flex; align-items:center; gap:4px; padding:4px 8px; font-size:11px; border-radius:8px;">{badge_text}</span>
                    {new_badge}
                </div>
                {time_btn}
              </div>
              <div class="num-country" style="margin-top:12px;">{n['country']}</div>
              <div class="num-phone">{n['phone']}</div>
              <div style="margin-top:14px;">
                <a href="/my/number/{n['id']}" onclick="event.stopPropagation();" class="btn btn-sm" style="width:100%; display:flex; align-items:center; justify-content:center; gap:6px; padding:10px; font-size:13px; font-weight:800; background:linear-gradient(135deg, rgba(99,102,241,0.15), rgba(6,182,212,0.15)); color:var(--primary2); border:1px solid rgba(99,102,241,0.4); border-radius:10px; text-decoration:none;">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>
                  طلب كود
                </a>
              </div>
            </div>''')
        
        nh = "".join(nh_parts) or '<div class="empty">لم تشترِ بعد</div>'
        
        dh = "".join(f'''<tr><td>#{d["id"]}</td><td>{d["method"]}</td><td style="direction:ltr;text-align:left">${d["amount_usd"]:.2f}</td><td><span class="badge {d["status"]}">{d["status"]}</span></td><td>{d["created_at"]}</td></tr>''' for d in deps) or '<tr><td colspan="5" style="text-align:center;color:var(--muted)">لا شحنات</td></tr>'

        today = datetime.now().strftime("%Y-%m-%d")
        can_bonus = True
        try: can_bonus = (u["last_bonus"] != today)
        except: pass
        bonus_btn = f""
        if can_bonus:
            bonus_btn = f'<form method="POST" action="/daily-bonus" style="margin:0"><button class="btn" style="width:100%">{ico("gift", 14)} استلام المكافأة اليومية</button></form>'

        # بناء HTML للزرار "أرقامي قيد المراجعة" (خارج الـ f-string)
        # الزرار يظهر دايماً (العداد يظهر بس لو في أرقام معلقة)
        badge_html = ''
        if pending_count > 0:
            badge_html = (
                '<span style="position:absolute; top:-8px; right:-8px; background:#ef4444; color:#fff; '
                'font-size:11px; font-weight:900; min-width:22px; height:22px; border-radius:11px; '
                'display:flex; align-items:center; justify-content:center; padding:0 5px; '
                'box-shadow:0 0 12px rgba(239,68,68,0.7); border:2px solid var(--card);">' + str(pending_count) + '</span>'
            )
        
        pending_btn_html = (
            '<a href="/my/pending-sales" style="display:flex; align-items:center; justify-content:center; gap:10px; '
            'padding:16px; margin-bottom:24px; '
            'background:linear-gradient(135deg, rgba(245,158,11,0.15), rgba(239,68,68,0.15)); '
            'border:1px solid rgba(245,158,11,0.4); border-radius:14px; '
            'color:#f59e0b; font-weight:800; font-size:14px; text-decoration:none; position:relative;">'
            '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">'
            '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>'
            '<span>أرقامي قيد المراجعة</span>'
            + badge_html +
            '</a>'
        )
        
        body = f'''
        <div class="container">

          <!-- البروفايل -->
          <div style="text-align:center; margin-bottom:20px; padding:20px 16px; background:linear-gradient(145deg, var(--card) 0%, var(--card2) 100%); border-radius:20px; border:1px solid var(--border); position:relative; overflow:hidden;">
            <div style="position:absolute; top:-40px; right:-40px; width:120px; height:120px; background:radial-gradient(circle, rgba(99,102,241,0.25), transparent 70%); border-radius:50%; pointer-events:none;"></div>
                        <div style="width:90px; height:90px; margin:0 auto 14px; background:var(--bg2); border:3px solid var(--primary2); border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:36px; font-weight:900; color:var(--primary2); box-shadow:0 0 25px rgba(99,102,241,0.4); overflow:hidden; position:relative; z-index:1;">
              {f'<img src="/static/avatars/{u["avatar"]}" style="width:100%; height:100%; object-fit:cover;">' if u["avatar"] else (u["username"][0].upper() if u["username"] else "?")}
            </div>
                        <div style="display:flex; align-items:center; justify-content:center; gap:10px; margin-bottom:6px; position:relative; z-index:1;">
              <div style="font-size:20px; font-weight:900;">{u["username"]}</div>
              <a href="/profile/edit" class="btn btn-sm btn-ghost" style="padding:4px 10px; font-size:11px;">
                {ico("edit", 12)} تعديل
              </a>
            </div>
                        <div style="display:inline-flex; align-items:center; gap:8px; background:rgba(99,102,241,0.1); border:1px solid rgba(99,102,241,0.3); padding:6px 14px; border-radius:12px; position:relative; z-index:1;">
              <span style="font-size:11px; color:var(--muted); font-weight:700;">الآيدي:</span>
              <code style="font-family:monospace; font-size:14px; color:var(--primary2); font-weight:900; letter-spacing:1px; direction:ltr;">{u["custom_id"] or u["user_id"]}</code>
              <button onclick="copyText('{u["custom_id"] or u["user_id"]}', this)" class="copy-btn-inline" style="padding:4px 8px; font-size:11px;">{ico("copy", 12)}</button>
            </div>
          </div>
          
          <!-- الرصيد -->
          <div style="position:relative; text-align:center; margin-bottom:24px; padding:32px 16px 24px; background:linear-gradient(135deg, rgba(99,102,241,0.08), rgba(6,182,212,0.08)); border:1px solid rgba(99,102,241,0.2); border-radius:16px; overflow:hidden;">
            <div style="position:absolute; top:0; left:0; display:inline-flex; border-radius:0 0 12px 0; padding:6px 12px 8px 10px; align-items:center; gap:6px; background:linear-gradient(135deg, rgba(38,161,123,0.25), rgba(28,126,90,0.15)); backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px); border:1px solid rgba(38,161,123,0.5); border-top:none; border-left:none; color:#34d399; font-size:10px; font-weight:900; letter-spacing:0.5px; box-shadow:0 2px 8px rgba(38,161,123,0.15), inset 0 1px 0 rgba(255,255,255,0.1);">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M8 7h8M12 7v10M8 12h8"/></svg>
                USDT
            </div>
            <div style="display:flex; align-items:center; justify-content:center; gap:8px; font-size:14px; color:var(--muted); margin-bottom:18px; font-weight:700;">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#818cf8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="filter: drop-shadow(0 0 4px rgba(129,140,248,0.3));">
                    <path d="M21 12V7H5a2 2 0 0 1 0-4h14v4"/><path d="M3 5v14a2 2 0 0 0 2 2h16v-5"/><path d="M18 12a2 2 0 0 0 0 4h4v-4z"/>
                </svg>
                إجمالي رصيدي
            </div>
            <div style="display:flex; align-items:center; justify-content:center; margin-bottom:28px;">
                <span style="font-family:'Tajawal', sans-serif; font-size:clamp(28px, 6.5vw, 36px); font-weight:900; background:linear-gradient(135deg, #818cf8, #06b6d4); -webkit-background-clip:text; -webkit-text-fill-color:transparent; background-clip:text; line-height:1; letter-spacing:-0.5px; direction:ltr;">
                    {u["balance"]:.2f}
                </span>
            </div>
            <div style="display:flex; gap:10px; justify-content:center;">
                <a href="/deposit" class="btn btn-sm" style="flex:1; display:flex; align-items:center; justify-content:center; gap:6px; padding:10px; font-size:12px; background:rgba(99,102,241,0.1); border:1px solid rgba(99,102,241,0.3); color:#818cf8;">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><rect x="2" y="5" width="20" height="14" rx="2"/><line x1="2" y1="10" x2="22" y2="10"/></svg>
                    شحن
                </a>
                <a href="/transfer" class="btn btn-sm" style="flex:1; display:flex; align-items:center; justify-content:center; gap:6px; padding:10px; font-size:12px; background:rgba(16,185,129,0.1); border:1px solid rgba(16,185,129,0.3); color:#10b981;">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M17 1l4 4-4 4"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><path d="M7 23l-4-4 4-4"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/></svg>
                    تحويل
                </a>
            </div>
        </div>
          


          <!-- القائمة الرئيسية -->
          <div class="account-menu">
                        
            <a href="/vip" style="display:flex;align-items:center;justify-content:space-between;padding:16px 20px;">
              <div style="display:flex;align-items:center;gap:14px;">
                <div style="width:40px;height:40px;border-radius:12px;background:rgba(245,158,11,0.15);display:flex;align-items:center;justify-content:center;border:1px solid rgba(245,158,11,0.3);">
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
                </div>
                <div>
                  <div style="font-weight:800;font-size:14px;color:var(--text);">مستويات VIP</div>
                  <div style="font-size:11px;color:var(--muted);">خصومات حصرية</div>
                </div>
              </div>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--muted)" stroke-width="2.5"><polyline points="15 18 9 12 15 6"/></svg>
            </a>
                        <a href="/referral" style="display:flex;align-items:center;justify-content:space-between;padding:16px 20px;">
              <div style="display:flex;align-items:center;gap:14px;">
                <div style="width:40px;height:40px;border-radius:12px;background:rgba(139,92,246,0.15);display:flex;align-items:center;justify-content:center;border:1px solid rgba(139,92,246,0.3);">
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#8b5cf6" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
                </div>
                <div>
                  <div style="font-weight:800;font-size:14px;color:var(--text);">الإحالات</div>
                  <div style="font-size:11px;color:var(--muted);">اربح من دعوة أصدقائك</div>
                </div>
              </div>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--muted)" stroke-width="2.5"><polyline points="15 18 9 12 15 6"/></svg>
            </a>
                        
                        
            
                        <a href="/logout" style="display:flex;align-items:center;justify-content:space-between;padding:16px 20px;">
              <div style="display:flex;align-items:center;gap:14px;">
                <div style="width:40px;height:40px;border-radius:12px;background:rgba(239,68,68,0.15);display:flex;align-items:center;justify-content:center;border:1px solid rgba(239,68,68,0.3);">
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
                </div>
                <div>
                  <div style="font-weight:800;font-size:14px;color:var(--danger);">تسجيل الخروج</div>
                  <div style="font-size:11px;color:var(--muted);">إنهاء الجلسة</div>
                </div>
              </div>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--danger)" stroke-width="2.5"><polyline points="15 18 9 12 15 6"/></svg>
            </a>
          </div>

          <!-- bonus removed -->



          <div style="margin-bottom:24px">{bonus_btn}</div>



          <!-- الروابط السريعة -->
          <div class="section-title">روابط سريعة</div>
          <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:24px;">
            <a href="/my/numbers" style="position:relative; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:6px; padding:14px 8px; background:linear-gradient(135deg, rgba(16,185,129,0.15), rgba(6,182,212,0.15)); border:1px solid rgba(16,185,129,0.3); border-radius:14px; color:#10b981; font-weight:800; font-size:12px; text-decoration:none; text-align:center;">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><rect x="5" y="2" width="14" height="20" rx="2" ry="2"/><line x1="12" y1="18" x2="12.01" y2="18"/></svg>
              عرض أرقامي
              {f'<span style="position:absolute; top:8px; right:20%; background:#ef4444; color:#fff; font-size:10px; font-weight:900; min-width:18px; height:18px; border-radius:9px; display:flex; align-items:center; justify-content:center; padding:0 5px; box-shadow:0 0 10px rgba(239,68,68,0.8); animation:pulse 1.5s infinite;">{unread_count_dash}</span>' if unread_count_dash > 0 else ''}
            </a>
            <a href="/store" style="display:flex; flex-direction:column; align-items:center; justify-content:center; gap:6px; padding:14px 8px; background:linear-gradient(135deg, rgba(99,102,241,0.15), rgba(6,182,212,0.15)); border:1px solid rgba(99,102,241,0.3); border-radius:14px; color:var(--primary2); font-weight:800; font-size:12px; text-decoration:none; text-align:center;">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/><line x1="3" y1="6" x2="21" y2="6"/><path d="M16 10a4 4 0 0 1-8 0"/></svg>
              تصفح المتجر
            </a>
          </div>


          

          
          

          
          {pending_btn_html}

          <!-- الإحصائيات (مميزة مع SVG) -->
          <div class="section-title" style="text-align:center;">إحصائياتي</div>
          <div style="display:grid; grid-template-columns:repeat(2, 1fr); gap:12px; margin-bottom:24px;">

            <!-- أرقامي -->
            <div style="background:linear-gradient(145deg, var(--card), var(--card2)); border:1px solid rgba(99,102,241,0.25); border-radius:16px; padding:16px 14px; text-align:center; position:relative; overflow:hidden; box-shadow:0 4px 15px rgba(99,102,241,0.1);">
              <div style="width:40px;height:40px;background:rgba(99,102,241,0.15);border-radius:12px;display:flex;align-items:center;justify-content:center;margin:0 auto 10px;">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#818cf8" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="2" width="14" height="20" rx="2" ry="2"/><line x1="12" y1="18" x2="12.01" y2="18"/></svg>
              </div>
              <div style="font-size:28px; font-weight:900; color:#818cf8; line-height:1;">{len(nums)}</div>
              <div style="font-size:12px; color:var(--muted); margin-top:6px;">أرقامي</div>
            </div>

            <!-- إجمالي المشتريات -->
            <div style="background:linear-gradient(145deg, var(--card), var(--card2)); border:1px solid rgba(16,185,129,0.25); border-radius:16px; padding:16px 14px; text-align:center; position:relative; overflow:hidden; box-shadow:0 4px 15px rgba(16,185,129,0.1);">
              <div style="width:40px;height:40px;background:rgba(16,185,129,0.15);border-radius:12px;display:flex;align-items:center;justify-content:center;margin:0 auto 10px;">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
              </div>
              <div style="font-size:22px; font-weight:900; color:#10b981; line-height:1;">{u["total_spent"] or 0:.2f} <span style="font-size:12px; color:#26a17b;">USDT</span></div>
              <div style="font-size:12px; color:var(--muted); margin-top:6px;">إجمالي المشتريات</div>
            </div>

            <!-- أرباح الإحالات -->
            <div style="background:linear-gradient(145deg, var(--card), var(--card2)); border:1px solid rgba(139,92,246,0.25); border-radius:16px; padding:16px 14px; text-align:center; position:relative; overflow:hidden; box-shadow:0 4px 15px rgba(139,92,246,0.1);">
              <div style="width:40px;height:40px;background:rgba(139,92,246,0.15);border-radius:12px;display:flex;align-items:center;justify-content:center;margin:0 auto 10px;">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#8b5cf6" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
              </div>
              <div style="font-size:22px; font-weight:900; color:#8b5cf6; line-height:1;">{("0" if u["referral_earnings"] == 0 else "{:g}".format(round(u["referral_earnings"], 4)))} <span style="font-size:12px; color:#26a17b;">USDT</span></div>
              <div style="font-size:12px; color:var(--muted); margin-top:6px;">أرباح الإحالات</div>
            </div>

            <!-- الرصيد الحالي -->
            <div style="background:linear-gradient(145deg, var(--card), var(--card2)); border:1px solid rgba(245,158,11,0.25); border-radius:16px; padding:16px 14px; text-align:center; position:relative; overflow:hidden; box-shadow:0 4px 15px rgba(245,158,11,0.1);">
              <div style="width:40px;height:40px;background:rgba(245,158,11,0.15);border-radius:12px;display:flex;align-items:center;justify-content:center;margin:0 auto 10px;">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12V7H5a2 2 0 0 1 0-4h14v4"/><path d="M3 5v14a2 2 0 0 0 2 2h16v-5"/><path d="M18 12a2 2 0 0 0 0 4h4v-4z"/></svg>
              </div>
              <div style="font-size:22px; font-weight:900; color:#f59e0b; line-height:1;">${u["balance"]:.2f}</div>
              <div style="font-size:12px; color:var(--muted); margin-top:6px;">إجمالي رصيدي</div>
            </div>

          </div>

        </div>'''


    elif name == "referral":
        cnt = ctx["referral_count"]
        ref_url = f"{request.host_url.rstrip('/')}/register?ref={u['username']}"
        reward = float(get_setting("REFERRAL_REWARD", "0.001"))
        
        # استخدام input مخفي للنسخ عشان نتجنب مشاكل الرابط
        body = f'''
        <div class="container" style="max-width:700px">
          <div class="section-title">نظام الإحالات</div>
          
          {f'<div style="background:rgba(239,68,68,0.1); border:1px solid rgba(239,68,68,0.3); border-radius:12px; padding:14px; margin-bottom:20px; display:flex; align-items:center; gap:10px; color:#ef4444; font-weight:700; font-size:13px;">{ico("warning", 20)} نظام الإحالات متوقف مؤقتاً. لن يتم إضافة مكافآت للمستخدمين الجدد حالياً.</div>' if get_setting("REFERRAL_ENABLED", "1") != "1" else ''}
          
          <div class="card" style="margin-bottom:20px; text-align:center;">
            <div style="width:60px; height:60px; margin:0 auto 16px; background:linear-gradient(135deg, rgba(99,102,241,0.15), rgba(6,182,212,0.15)); border:2px solid var(--primary2); border-radius:50%; display:flex; align-items:center; justify-content:center; color:var(--primary2);">
              {ico("users", 28)}
            </div>
            <div style="font-size:16px; font-weight:800; margin-bottom:8px;">اربح من دعوة أصدقائك</div>
            <div style="font-size:13px; color:var(--muted); margin-bottom:16px;">شارك رابط الإحالة الخاص بك، واربح <b style="color:var(--success);">${reward:.2f}</b> عند شراء أول رقم.</div>
            
            <div style="display:flex; flex-direction:column; gap:8px;">
              <input type="text" id="refUrlInput" value="{ref_url}" readonly style="width:100%; padding:14px; background:var(--bg2); color:var(--primary2); border:1px solid var(--border); border-radius:12px; font-family:monospace; font-size:13px; direction:ltr; text-align:center;">
              <button onclick="copyRefUrl()" class="btn" style="padding:14px; background:var(--gradient); color:#fff; border-radius:12px; font-weight:800; font-size:14px; display:flex; align-items:center; justify-content:center; gap:8px;">
                {ico("copy", 18)} نسخ رابط الإحالة
              </button>
            </div>
          </div>

          <div style="display:grid; grid-template-columns:repeat(2, 1fr); gap:12px; margin-bottom:20px;">
            <div class="card" style="text-align:center; padding:20px;">
              <div style="font-size:36px;font-weight:900;background:var(--gradient);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text">{cnt}</div>
              <div style="color:var(--muted);font-size:13px;margin-top:4px;">مُحالون</div>
            </div>
            <div class="card" style="text-align:center; padding:20px;">
              <div style="font-size:36px;font-weight:900;color:var(--success);direction:ltr">${u["referral_earnings"]:.2f}</div>
              <div style="color:var(--muted);font-size:13px;margin-top:4px;">مكافآت</div>
            </div>
          </div>

          <div class="card" style="background:rgba(99,102,241,0.05); border-color:rgba(99,102,241,0.2);">
            <div style="font-size:14px; font-weight:800; margin-bottom:8px; color:var(--primary2);">{ico("info", 18)} كيف يعمل النظام؟</div>
            <ol style="margin:0; padding-right:20px; font-size:13px; color:var(--muted); line-height:1.8;">
              <li>اضغط على زر "نسخ رابط الإحالة" بالأعلى.</li>
              <li>شارك الرابط مع أصدقائك على وسائل التواصل الاجتماعي.</li>
              <li>عند تسجيل أي صديق من خلال الرابط وشراءه أول رقم، ستضاف لك مكافأة <b style="color:var(--success);">${reward:.2f}</b> تلقائياً إلى رصيدك.</li>
            </ol>
          </div>
        </div>
        
        <script>
        function copyRefUrl() {{
            var input = document.getElementById('refUrlInput');
            input.select();
            input.setSelectionRange(0, 99999);
            try {{
                navigator.clipboard.writeText(input.value).then(function() {{
                    alert('تم نسخ رابط الإحالة بنجاح!');
                }}).catch(function() {{
                    document.execCommand('copy');
                    alert('تم نسخ رابط الإحالة بنجاح!');
                }});
            }} catch(e) {{
                document.execCommand('copy');
                alert('تم نسخ رابط الإحالة بنجاح!');
            }}
        }}
        </script>'''

    elif name == "transfer":
        fee = get_fee()
        body = (
            '<div class="container" style="max-width:500px; padding-top:20px;">'
            '<div style="text-align:center; margin-bottom:20px;">'
            '<div style="width:60px; height:60px; margin:0 auto 12px; background:linear-gradient(135deg, rgba(16,185,129,0.15), rgba(6,182,212,0.15)); border:2px solid #10b981; border-radius:50%; display:flex; align-items:center; justify-content:center; color:#10b981;">'
            + ico("send", 28) +
            '</div>'
            '<div class="section-title" style="margin-bottom:4px;">تحويل رصيد</div>'
            '<div style="font-size:12px; color:var(--muted);">رسوم التحويل: <b style="color:var(--warn);">' + '${:.2f}'.format(fee) + '</b> لكل عملية</div>'
            '</div>'
            '<div class="card" style="padding:20px;">'
            '<form method="POST" style="display:flex;flex-direction:column;gap:14px">'
            # آيدي المستلم
            '<div class="field">'
            '<label style="display:flex; align-items:center; gap:6px; font-size:12px; font-weight:700; margin-bottom:6px; color:var(--muted);">'
            + ico("user", 16) + ' آيدي المستلم'
            '</label>'
            '<input name="to_id" type="number" required placeholder="12345678" style="width:100%; padding:14px; background:var(--bg2); color:var(--text); border:1.5px solid var(--border); border-radius:10px; font-size:16px; text-align:center; direction:ltr;">'
            '</div>'
            # المبلغ
            '<div class="field">'
            '<label style="display:flex; align-items:center; gap:6px; font-size:12px; font-weight:700; margin-bottom:6px; color:var(--muted);">'
            + ico("dollar", 16) + ' المبلغ ($)'
            '</label>'
            '<input name="amount" type="number" step="0.01" min="' + str(fee + 0.01) + '" required placeholder="5.00" style="width:100%; padding:14px; background:var(--bg2); color:var(--text); border:1.5px solid var(--border); border-radius:10px; font-size:16px; text-align:center; direction:ltr;">'
            '</div>'
            # الرصيد
            '<div style="background:rgba(99,102,241,0.05); border:1px solid rgba(99,102,241,0.2); border-radius:10px; padding:12px; font-size:12px; color:var(--muted);">'
            '<div style="display:flex; justify-content:space-between; align-items:center;">'
            + ico("wallet", 14) + ' <span>رصيدك الحالي:</span> <b style="color:var(--text); direction:ltr;">' + '${:.2f}'.format(u["balance"]) + '</b>'
            '</div>'
            '</div>'
            # زر التحويل
            '<button type="submit" class="form-btn" style="padding:16px; font-size:16px; display:flex; align-items:center; justify-content:center; gap:8px;">'
            + ico("send", 20) + ' تحويل الآن'
            '</button>'
            '</form>'
            # الآيدي الخاص بك
            '<div style="margin-top:20px; padding-top:16px; border-top:1px solid var(--border); text-align:center;">'
            '<div style="font-size:11px; color:var(--muted); margin-bottom:8px; display:flex; align-items:center; justify-content:center; gap:6px;">'
            + ico("user", 14) + ' آيديك (شاركه ليصلك رصيد)'
            '</div>'
            '<div style="display:flex; align-items:center; justify-content:center; gap:8px; background:var(--bg2); padding:10px; border-radius:10px;">'
            '<code style="font-size:16px; color:var(--primary2); font-weight:900; direction:ltr;">' + str(u["custom_id"] or u["user_id"]) + '</code>'
            '<button onclick="copyText(\'' + str(u["custom_id"] or u["user_id"]) + '\', this)" class="copy-btn-inline" style="padding:4px 8px; font-size:11px; display:flex; align-items:center; gap:4px;">'
            + ico("copy", 14) + ' نسخ'
            '</button>'
            '</div>'
            '</div>'
            '</div>'
            '</div>'
        )
        return page("transfer", body=body)

    elif name == "admin_audit":
        logs = ctx["logs"]
        rows = ""
        for l in logs:
            rows += f'<tr><td>#{l["id"]}</td><td>{l["username"] or "—"}</td><td><code>{l["action"]}</code></td><td style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{l["details"] or ""}</td><td style="font-size:11px">{l["created_at"]}</td></tr>'
        body = f'''
        <div class="container"><div class="section-title">سجل النشاط <span class="section-sub">({len(logs)})</span></div>
          <a href="/admin" class="btn btn-ghost btn-sm" style="margin-bottom:20px">{ico("arrow-left", 14)} رجوع</a>
          <div class="table-wrap"><table class="table"><tr><th>#</th><th>المستخدم</th><th>الإجراء</th><th>التفاصيل</th><th>التاريخ</th></tr>{rows or '<tr><td colspan="5" style="text-align:center;color:var(--muted)">لا سجلات</td></tr>'}</table></div>
        </div>'''

    elif name == "admin_home":
        s = ctx["stats"]
        pending_deposits = ctx.get("pending_deposits", 0)
        unread_messages = ctx.get("unread_messages", 0)
        pending_numbers = ctx.get("pending_numbers", 0)
        
        # دالة مساعدة لصنع زر بأيقونة
        def tile(href, label, svg_icon, color="var(--primary)", badge_count=0):
            badge_html = ""
            if badge_count > 0:
                badge_html = f'<span style="position:absolute; top:8px; left:8px; background:#3b82f6; color:#fff; font-size:10px; font-weight:900; min-width:20px; height:20px; border-radius:10px; display:flex; align-items:center; justify-content:center; padding:0 5px; box-shadow:0 0 12px rgba(59,130,246,0.7); animation:pulse 1.5s infinite; border:2px solid var(--card);">{badge_count}</span>'
            return f'''<a href="{href}" class="admin-tile" style="position:relative;">
              {badge_html}
              <div class="admin-tile-icon" style="color:{color}">{svg_icon}</div>
              <div class="admin-tile-label">{label}</div>
            </a>'''
        
        # أيقونات SVG
        svg_wallet = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12V7H5a2 2 0 0 1 0-4h14v4"/><path d="M3 5v14a2 2 0 0 0 2 2h16v-5"/><path d="M18 12a2 2 0 0 0 0 4h4v-4z"/></svg>'
        svg_users = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>'
        svg_phone = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="2" width="14" height="20" rx="2" ry="2"/><line x1="12" y1="18" x2="12.01" y2="18"/></svg>'
        svg_telegram = site_icon("telegram", 24, ico("telegram", 24))
        svg_voucher = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 5l-1.41 1.41L18.17 11H2v2h16.17l-4.58 4.59L15 19l7-7-7-7z"/></svg>'
        svg_ticket = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 9a3 3 0 0 1 0 6v2a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-2a3 3 0 0 1 0-6V7a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2z"/></svg>'
        svg_stats = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>'
        svg_audit = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>'
        svg_settings = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>'
        svg_csv = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>'
        
        body = f'''<div class="container">
          <div class="section-title" style="text-align:center;margin-bottom:24px;display:flex;align-items:center;justify-content:center;gap:12px;">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="url(#adminGearGrad)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <defs><linearGradient id="adminGearGrad" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#6366f1"/><stop offset="1" stop-color="#06b6d4"/></linearGradient></defs>
              <circle cx="12" cy="12" r="3"/>
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
            </svg>
            لوحة الإدارة
          </div>
          
          <div style="display:grid; grid-template-columns:repeat(2, 1fr); gap:12px; margin-bottom:24px;">
            <!-- كارت المستخدمين -->
            <div style="background:linear-gradient(145deg, var(--card) 0%, var(--card2) 100%); border:1px solid rgba(129,140,248,0.3); border-radius:16px; padding:16px; position:relative; overflow:hidden; box-shadow:0 4px 15px rgba(99,102,241,0.1);">
              <div style="position:absolute; top:-10px; right:-10px; width:60px; height:60px; background:radial-gradient(circle, rgba(129,140,248,0.2), transparent 70%); border-radius:50%;"></div>
              <div style="display:flex; align-items:center; gap:10px; margin-bottom:10px; position:relative; z-index:1;">
                <div style="width:32px; height:32px; border-radius:10px; background:rgba(129,140,248,0.15); display:flex; align-items:center; justify-content:center; border:1px solid rgba(129,140,248,0.3);">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#818cf8" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
                </div>
                <div style="font-size:12px; font-weight:800; color:var(--muted);">المستخدمون</div>
              </div>
              <div style="font-size:26px; font-weight:900; color:#818cf8; line-height:1; position:relative; z-index:1;">{s["users"]}</div>
            </div>

            <!-- كارت الأرقام -->
            <div style="background:linear-gradient(145deg, var(--card) 0%, var(--card2) 100%); border:1px solid rgba(6,182,212,0.3); border-radius:16px; padding:16px; position:relative; overflow:hidden; box-shadow:0 4px 15px rgba(6,182,212,0.1);">
              <div style="position:absolute; top:-10px; right:-10px; width:60px; height:60px; background:radial-gradient(circle, rgba(6,182,212,0.2), transparent 70%); border-radius:50%;"></div>
              <div style="display:flex; align-items:center; gap:10px; margin-bottom:10px; position:relative; z-index:1;">
                <div style="width:32px; height:32px; border-radius:10px; background:rgba(6,182,212,0.15); display:flex; align-items:center; justify-content:center; border:1px solid rgba(6,182,212,0.3);">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#06b6d4" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="2" width="14" height="20" rx="2" ry="2"/><line x1="12" y1="18" x2="12.01" y2="18"/></svg>
                </div>
                <div style="font-size:12px; font-weight:800; color:var(--muted);">الأرقام</div>
              </div>
              <div style="font-size:26px; font-weight:900; color:#06b6d4; line-height:1; position:relative; z-index:1;">{s["numbers"]}</div>
            </div>

            <!-- كارت المبيوعة -->
            <div style="background:linear-gradient(145deg, var(--card) 0%, var(--card2) 100%); border:1px solid rgba(16,185,129,0.3); border-radius:16px; padding:16px; position:relative; overflow:hidden; box-shadow:0 4px 15px rgba(16,185,129,0.1);">
              <div style="position:absolute; top:-10px; right:-10px; width:60px; height:60px; background:radial-gradient(circle, rgba(16,185,129,0.2), transparent 70%); border-radius:50%;"></div>
              <div style="display:flex; align-items:center; gap:10px; margin-bottom:10px; position:relative; z-index:1;">
                <div style="width:32px; height:32px; border-radius:10px; background:rgba(16,185,129,0.15); display:flex; align-items:center; justify-content:center; border:1px solid rgba(16,185,129,0.3);">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
                </div>
                <div style="font-size:12px; font-weight:800; color:var(--muted);">مبيوعة</div>
              </div>
              <div style="font-size:26px; font-weight:900; color:#10b981; line-height:1; position:relative; z-index:1;">{s["sold"]}</div>
            </div>

            <!-- كارت المعلقة -->
            <div style="background:linear-gradient(145deg, var(--card) 0%, var(--card2) 100%); border:1px solid rgba(245,158,11,0.3); border-radius:16px; padding:16px; position:relative; overflow:hidden; box-shadow:0 4px 15px rgba(245,158,11,0.1);">
              <div style="position:absolute; top:-10px; right:-10px; width:60px; height:60px; background:radial-gradient(circle, rgba(245,158,11,0.2), transparent 70%); border-radius:50%;"></div>
              <div style="display:flex; align-items:center; gap:10px; margin-bottom:10px; position:relative; z-index:1;">
                <div style="width:32px; height:32px; border-radius:10px; background:rgba(245,158,11,0.15); display:flex; align-items:center; justify-content:center; border:1px solid rgba(245,158,11,0.3);">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                </div>
                <div style="font-size:12px; font-weight:800; color:var(--muted);">معلقة</div>
              </div>
              <div style="font-size:26px; font-weight:900; color:#f59e0b; line-height:1; position:relative; z-index:1;">{s["pending"]}</div>
            </div>
          </div>
          
          <div class="admin-grid">
            {tile("/admin/code-monitor", "مراقبة الأكواد", '<svg viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>', "var(--danger)")}
            {tile("/admin/deposits", "الشحنات", '<svg viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="1" y="4" width="22" height="16" rx="2" ry="2"/><line x1="1" y1="10" x2="23" y2="10"/></svg>', "var(--warn)", pending_deposits)}
            {tile("/admin/users", "المستخدمون", '<svg viewBox="0 0 24 24" fill="none" stroke="#818cf8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>', "var(--primary2)")}
            {tile("/admin/numbers", "الأرقام", '<svg viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="2" width="14" height="20" rx="2" ry="2"/><line x1="12" y1="18" x2="12.01" y2="18"/></svg>', "var(--success)")}
            {tile("/admin/tg", "تيليجرام", site_icon("telegram", 24, ico("telegram", 24)), "var(--primary2)")}
            {tile("/admin/vouchers", "أكواد الشحن", '<svg viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 12 20 22 4 22 4 12"/><rect x="2" y="7" width="20" height="5"/><line x1="12" y1="22" x2="12" y2="7"/><path d="M12 7H7.5a2.5 2.5 0 0 1 0-5C11 2 12 7 12 7z"/><path d="M12 7h4.5a2.5 2.5 0 0 0 0-5C13 2 12 7 12 7z"/></svg>', "var(--success)")}
            {tile("/admin/coupons", "الكوبونات", '<svg viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 9a3 3 0 0 1 0 6v2a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-2a3 3 0 0 1 0-6V7a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2z"/></svg>', "var(--warn)")}
            {tile("/admin/tickets", "التذاكر", '<svg viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>', "var(--danger)", unread_messages)}
            {tile("/admin/stats", "الإحصائيات", '<svg viewBox="0 0 24 24" fill="none" stroke="#818cf8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>', "var(--primary2)")}
            {tile("/admin/audit", "سجل النشاط", '<svg viewBox="0 0 24 24" fill="none" stroke="#8888aa" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>', "var(--muted)")}
            {tile("/admin/backup/auto_download", "نسخة احتياطية", '<svg viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>', "var(--success)")}
            {tile("/admin/backup/restore", "استعادة نسخة", '<svg viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>', "var(--danger)")}
            {tile("/admin/notifications", "الإشعارات", '<svg viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>', "var(--warn)")}
            {tile("/admin/settings", "الإعدادات", '<svg viewBox="0 0 24 24" fill="none" stroke="#818cf8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>', "var(--primary2)")}
                        
            {tile("/admin/icons", "الأيقونات", '<svg viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>', "var(--success)")}
            {tile("/admin/buy-prices", "أسعار الشراء", '<svg viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>', "var(--success)")}
            {tile("/admin/pending_sellers", "أرقام المستخدمين", '<svg viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>', "var(--warn)", pending_numbers)}
            {tile("/admin/sold", "الأرقام المباعة", '<svg viewBox="0 0 24 24" fill="none" stroke="#818cf8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>', "var(--primary2)")}
            {tile("/admin/database", "إدارة قاعدة البيانات", '<svg viewBox="0 0 24 24" fill="none" stroke="#818cf8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>', "var(--primary)")}
            {tile("/admin/pages", "الصفحات المخصصة", ico("file", 24), "var(--primary)")}
            {tile("/admin/links", "الأزرار والروابط", ico("list", 24), "var(--primary2)")}
            {tile("/admin/dev-history", "تاريخ التطوير", ico("refresh", 24), "var(--success)")}
            {tile("/admin/static-pages", "الصفحات الثابتة", ico("globe", 24), "var(--primary)")}
            {tile("/admin/dashboard-blocks", "بلوكات لوحة المستخدم", ico("settings", 24), "var(--primary2)")}
          </div>
        </div>'''
        body += _BACKUP_PROGRESS_BLOCK

    elif name == "admin_deposits":
        deps = ctx["deposits"]
        cards_html = ""
        for d in deps:
            if d["status"] == "approved":
                st_color = "var(--success)"
                st_bg = "rgba(16,185,129,0.15)"
                st_txt = "مقبول"
            elif d["status"] == "rejected":
                st_color = "var(--danger)"
                st_bg = "rgba(239,68,68,0.15)"
                st_txt = "مرفوض"
            else:
                st_color = "var(--warn)"
                st_bg = "rgba(245,158,11,0.15)"
                st_txt = "معلق"

            actions = ""
            if d["status"] == "pending":
                actions = f'''
                <div style="display:flex;gap:8px;margin-top:14px;">
                    <form method="POST" action="/admin/deposit/{d["id"]}/approve" style="flex:1;margin:0">
                        <button class="btn" style="background:var(--success);width:100%;padding:10px;border-radius:10px;font-weight:800;color:#fff;display:flex;align-items:center;justify-content:center;gap:6px;">
                            {ico("check", 16)} قبول
                        </button>
                    </form>
                    <form method="POST" action="/admin/deposit/{d["id"]}/reject" style="flex:1;margin:0">
                        <button class="btn" style="background:var(--danger);width:100%;padding:10px;border-radius:10px;font-weight:800;color:#fff;display:flex;align-items:center;justify-content:center;gap:6px;">
                            {ico("x", 16)} رفض
                        </button>
                    </form>
                </div>'''

            cards_html += f'''
            <div style="background:linear-gradient(145deg, var(--card) 0%, var(--card2) 100%); border:1px solid var(--border); border-right:4px solid {st_color}; border-radius:16px; padding:16px; margin-bottom:12px; box-shadow:0 4px 12px rgba(0,0,0,0.2);">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
                    <div style="font-weight:900;font-size:15px;color:var(--text);display:flex;align-items:center;gap:8px;">
                        {ico("user", 16)} {esc(d["username"])}
                    </div>
                    <div style="background:{st_bg}; color:{st_color}; border:1px solid {st_color}; padding:4px 12px; border-radius:20px; font-size:11px; font-weight:900;">
                        {st_txt}
                    </div>
                </div>
                <div style="background:var(--bg2); border:1px solid var(--border); border-radius:12px; padding:12px; display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
                    <div style="font-size:12px; color:var(--muted);">المبلغ المطلوب</div>
                    <div style="font-size:22px; font-weight:900; color:var(--primary2); direction:ltr;">${d["amount_usd"]:.2f}</div>
                </div>
                <div style="display:flex; flex-direction:column; gap:6px; font-size:12px; color:var(--muted); background:rgba(0,0,0,0.1); padding:10px; border-radius:10px;">
                    <div style="display:flex;justify-content:space-between;"><span>الطريقة:</span><span style="font-weight:700;color:var(--text);">{esc(d["method"])}</span></div>
                    <div style="display:flex;justify-content:space-between;"><span>رقم العملية:</span><span style="font-family:monospace;color:var(--text);direction:ltr;">{esc(d["trans_id"]) if d["trans_id"] else "—"}</span></div>
                    <div style="display:flex;justify-content:space-between;"><span>التاريخ:</span><span style="color:var(--text);">{d["created_at"][:16]}</span></div>
                </div>
                <div style="display:flex; gap:8px; margin-top:14px;">
                    <div style="flex:1;">{actions}</div>
                    <form method="POST" action="/admin/deposit/{d["id"]}/delete" style="margin:0;" onsubmit="return confirm('حذف هذه الشحنة نهائياً؟');">
                        <button class="btn" style="background:rgba(239,68,68,0.15); border:1px solid rgba(239,68,68,0.3); color:var(--danger); height:100%; padding:10px; border-radius:10px; display:flex; align-items:center; justify-content:center;">
                            {ico("trash", 16)}
                        </button>
                    </form>
                </div>
            </div>'''

        if not cards_html:
            cards_html = '<div class="empty">لا شحنات حالياً</div>'

        body = f'''
        <div class="container" style="max-width:700px">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px; flex-wrap:wrap; gap:10px;">
                <div class="section-title" style="margin:0;">الشحنات <span class="section-sub">({len(deps)})</span></div>
                <div style="display:flex; gap:8px;">
                    <form method="POST" action="/admin/deposits/clear" style="margin:0;" onsubmit="return confirm('هل أنت متأكد من مسح كل الشحنات (المقبولة والمرفوضة)؟ المعلقة مش هتتمسح.');">
                        <button class="btn btn-sm" style="background:var(--danger); color:#fff; display:flex; align-items:center; gap:6px; padding:8px 12px;">
                            {ico("trash", 14)} مسح القديمة
                        </button>
                    </form>
                    <a href="/admin" class="btn btn-ghost btn-sm">{ico("arrow-left", 14)} رجوع</a>
                </div>
            </div>
            {cards_html}
        </div>'''

    elif name == "admin_settings":
        s = ctx["s"]
        
        parts = []
        parts.append('<div class="container" style="max-width:800px;">')
        parts.append('<div class="section-title">إعدادات النظام المتقدمة</div>')
        parts.append('<a href="/admin" class="btn btn-ghost btn-sm" style="margin-bottom:20px">رجوع للوحة التحكم</a>')
        parts.append('<form method="POST">')
        
        # دالة مساعدة لإنشاء الحقول
        def make_field(key, label, desc, is_secret=False, dir_ltr=True):
            real_val = s.get(key, "")
            display_val = "••••••••" if (is_secret and real_val) else real_val
            dir_style = "direction:ltr; text-align:left;" if dir_ltr else ""
                        # لو الحقل سري، نضيف زر العين
            eye_btn = ""
            if is_secret and real_val:
                eye_btn = (
                    '<button type="button" onclick="toggleEye(this)" data-real="' + str(real_val) + '" '
                    'style="position:absolute; left:10px; top:50%; transform:translateY(-50%); '
                    'background:transparent; border:none; cursor:pointer; color:var(--muted); padding:4px;">'
                    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
                    '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>'
                    '<circle cx="12" cy="12" r="3"/>'
                    '</svg>'
                    '</button>'
                )

            return (
                '<div style="margin-bottom:16px; background:var(--bg2); padding:14px; border-radius:12px; border:1px solid var(--border);">'
                '<div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:8px;">'
                '<div>'
                '<div style="font-size:14px; font-weight:800; color:var(--text); margin-bottom:2px;">' + label + '</div>'
                '<div style="font-size:11px; color:var(--muted);">' + desc + '</div>'
                '</div>'
                '<span style="font-size:10px; font-family:monospace; color:var(--primary2); background:rgba(99,102,241,0.1); padding:2px 6px; border-radius:4px;">' + key + '</span>'
                '</div>'
                '<div style="position:relative;">'
                '<input name="' + key + '" type="' + ("password" if is_secret else "text") + '" value="' + str(display_val) + '" '
                'style="width:100%; padding:10px' + (' 36px' if is_secret else '') + '; background:var(--card); color:var(--text); '
                'border:1px solid var(--border); border-radius:8px; font-family:monospace; ' + dir_style + '">'
                + eye_btn +
                '</div>'
                '</div>'
            )

        # قسم البريد
        parts.append('<div class="card" style="margin-bottom:20px;">')
        parts.append('<div style="font-size:18px; font-weight:900; color:var(--primary2); margin-bottom:16px; display:flex; align-items:center; gap:8px;">' + ico("message", 22) + ' إعدادات البريد الإلكتروني</div>')
        parts.append(make_field("EMAIL_ADDRESS", "البريد الإلكتروني (Gmail)", "الإيميل الذي تستقبل عليه أكواد الواتساب."))
        parts.append(make_field("EMAIL_PASSWORD", "كلمة مرور التطبيق (App Password)", "ليس كلمة مرور جوجل العادية.", is_secret=True))
        parts.append(make_field("IMAP_HOST", "خادم IMAP", "افتراضياً: imap.gmail.com"))
        parts.append('<button type="button" onclick="testConnection(\'/admin/test_email\', this, \'emailResult\')" class="btn" style="background:var(--success); color:#fff; margin-top:8px;">' + ico("check-circle", 16) + ' فحص اتصال الإيميل</button>')
        parts.append('<div id="emailResult" style="margin-top:10px; font-size:13px; font-weight:bold;"></div>')
        parts.append('</div>')

        # قسم الدفع
        parts.append('<div class="card" style="margin-bottom:20px;">')
        parts.append('<div style="font-size:18px; font-weight:900; color:var(--primary2); margin-bottom:16px; display:flex; align-items:center; gap:8px;">' + ico("credit-card", 22) + ' إعدادات الدفع (Binance)</div>')
        parts.append(make_field("BINANCE_API_KEY", "Binance API Key", "مفتاح API الخاص بحساب Binance."))
        parts.append(make_field("BINANCE_API_SECRET", "Binance API Secret", "المفتاح السري لـ Binance.", is_secret=True))
        parts.append(make_field("BINANCE_PAY_ID", "Binance Pay ID", "رقم الـ Pay ID الخاص بك."))
        parts.append('<button type="button" onclick="testConnection(\'/admin/test_binance\', this, \'binanceResult\')" class="btn" style="background:var(--success); color:#fff; margin-top:8px;">' + ico("check-circle", 16) + ' فحص اتصال Binance</button>')
        parts.append('<div id="binanceResult" style="margin-top:10px; font-size:13px; font-weight:bold;"></div>')
        parts.append('</div>')

        # قسم الدفع اليدوي
        parts.append('<div class="card" style="margin-bottom:20px;">')
        parts.append('<div style="font-size:18px; font-weight:900; color:var(--primary2); margin-bottom:16px; display:flex; align-items:center; gap:8px;">' + ico("wallet", 22) + ' إعدادات الدفع اليدوي (جيب / ون كاش)</div>')
        parts.append(make_field("JEEB_ACCOUNT", "رقم حساب جيب", "رقم الحساب الذي يستلم عليه التحويلات."))
        parts.append(make_field("ONECASH_ACCOUNT", "رقم حساب ون كاش", "رقم الحساب الذي يستلم عليه التحويلات."))
        parts.append(make_field("JEEB_RATE_YE", "سعر صرف جيب (اليمن)", "كم ريال يمني يعادل 1 دولار."))
        parts.append(make_field("JEEB_RATE_SA", "سعر صرف جيب (السعودية)", "كم ريال سعودي يعادل 1 دولار."))
        parts.append(make_field("ONECASH_RATE_YE", "سعر صرف ون كاش (اليمن)", "كم ريال يمني يعادل 1 دولار."))
        parts.append(make_field("ONECASH_RATE_SA", "سعر صرف ون كاش (السعودية)", "كم ريال سعودي يعادل 1 دولار."))
        parts.append('</div>')

        # قسم تيليجرام
        parts.append('<div class="card" style="margin-bottom:20px;">')
        parts.append('<div style="font-size:18px; font-weight:900; color:var(--primary2); margin-bottom:16px; display:flex; align-items:center; gap:8px;">' + ico("telegram", 22) + ' إعدادات تيليجرام</div>')
        parts.append(make_field("TG_API_ID", "Telegram API ID", "معرف التطبيق من my.telegram.org"))
        parts.append(make_field("TG_API_HASH", "Telegram API Hash", "الهاش السري من my.telegram.org", is_secret=True))
        parts.append('</div>')

        # قسم عام
        parts.append('<div class="card" style="margin-bottom:20px;">')
        parts.append('<div style="font-size:18px; font-weight:900; color:var(--primary2); margin-bottom:16px; display:flex; align-items:center; gap:8px;">' + ico("settings", 22) + ' الإعدادات العامة</div>')
        parts.append(make_field("SITE_NAME", "اسم الموقع", "الاسم الذي يظهر في الأعلى."))
        parts.append(make_field("SUPPORT_USER", "يوزر الدعم الفني", "مثال: @MO_5_H"))
        parts.append(make_field("MIN_DEPOSIT_USD", "الحد الأدنى للإيداع", "بالدولار، مثال: 0.10"))
        # حقل مكافأة الإحالة
        parts.append(make_field("REFERRAL_REWARD", "مكافأة الإحالة", "بالدولار، مثال: 0.001"))
        
        # زر تبديل تفعيل/إيقاف نظام الإحالات (Checkbox عادي)
        ref_enabled = s.get("REFERRAL_ENABLED", "1") == "1"
        toggle_html = f'''
        <div style="margin-bottom:16px; background:var(--bg2); padding:14px; border-radius:12px; border:1px solid var(--border);">
            <label style="display:flex; align-items:center; gap:12px; cursor:pointer;">
                <input type="checkbox" name="REFERRAL_ENABLED" value="1" {'checked' if ref_enabled else ''} style="width:20px; height:20px; accent-color:#10b981; cursor:pointer;">
                <div>
                    <div style="font-size:14px; font-weight:800; color:var(--text); margin-bottom:2px;">تفعيل نظام الإحالات</div>
                    <div style="font-size:11px; color:var(--muted);">عند الإيقاف، لن تُضاف مكافآت للمستخدمين الجدد</div>
                </div>
            </label>
        </div>
        '''
        parts.append(toggle_html)
        
        # زر تبديل تفعيل/إيقاف المكافأة اليومية
        bonus_enabled = s.get("DAILY_BONUS_ENABLED", "1") == "1"
        bonus_toggle_html = f'''
        <div style="margin-bottom:16px; background:var(--bg2); padding:14px; border-radius:12px; border:1px solid var(--border);">
            <label style="display:flex; align-items:center; gap:12px; cursor:pointer;">
                <input type="checkbox" name="DAILY_BONUS_ENABLED" value="1" {'checked' if bonus_enabled else ''} style="width:20px; height:20px; accent-color:#f59e0b; cursor:pointer;">
                <div>
                    <div style="font-size:14px; font-weight:800; color:var(--text); margin-bottom:2px;">تفعيل المكافأة اليومية</div>
                    <div style="font-size:11px; color:var(--muted);">عند الإيقاف، لن يستطيع المستخدمون الحصول على المكافأة</div>
                </div>
            </label>
        </div>
        '''
        parts.append(bonus_toggle_html)
        parts.append(make_field("DAILY_BONUS", "المكافأة اليومية", "بالدولار."))
        parts.append(make_field("TRANSFER_FEE", "رسوم التحويل", "بالدولار."))
        parts.append('</div>')

        parts.append('<button type="submit" class="form-btn" style="padding:16px; font-size:16px;">' + ico("check", 20) + ' حفظ جميع الإعدادات</button>')
        parts.append('</form>')
        parts.append('</div>')
        
        # كود JavaScript للفحص
        parts.append('<script>')
        parts.append('function testConnection(url, btn, resultId) {')
        parts.append('  var originalHtml = btn.innerHTML;')
        parts.append('  btn.innerHTML = "جاري الفحص...";')
        parts.append('  btn.disabled = true;')
        parts.append('  var res = document.getElementById(resultId);')
        parts.append('  res.innerHTML = "جاري فحص الاتصال...";')
        parts.append('  fetch(url).then(function(r){ return r.json(); }).then(function(d){')
        parts.append('    btn.innerHTML = originalHtml;')
        parts.append('    btn.disabled = false;')
        parts.append('    if(d.ok) { res.innerHTML = "<span style=\"color:var(--success)\">✓ " + d.msg + "</span>"; }')
        parts.append('    else { res.innerHTML = "<span style=\"color:var(--danger)\">✗ " + d.error + "</span>"; }')
        parts.append('  }).catch(function(e){')
        parts.append('    btn.innerHTML = originalHtml;')
        parts.append('    btn.disabled = false;')
        parts.append('    res.innerHTML = "<span style=\"color:var(--danger)\">خطأ في الاتصال</span>";')
        parts.append('  });')
        parts.append('}')
        parts.append('</script>')
        
        # إضافة كود JavaScript للفحص مباشرة في الـ body
        parts.append("""
<script>
function testConnection(url, btn, resultId) {{
    var originalHtml = btn.innerHTML;
    btn.innerHTML = "جاري الفحص...";
    btn.disabled = true;
    var res = document.getElementById(resultId);
    if (res) res.innerHTML = "جاري فحص الاتصال...";
    fetch(url)
        .then(function(r){{ return r.json(); }})
        .then(function(d){{
            btn.innerHTML = originalHtml;
            btn.disabled = false;
            if (res) {{
                if (d.ok) {{
                    res.innerHTML = "<span style='color:var(--success);font-weight:bold'>✓ " + d.msg + "</span>";
                }} else {{
                    res.innerHTML = "<span style='color:var(--danger);font-weight:bold'>✗ " + d.error + "</span>";
                }}
            }}
        }})
        .catch(function(e){{
            btn.innerHTML = originalHtml;
            btn.disabled = false;
            if (res) res.innerHTML = "<span style='color:var(--danger)'>خطأ في الاتصال: " + e.message + "</span>";
        }});
}}
</script>
""")
        parts.append('''
        <script>
        function toggleEye(btn) {{
            var input = btn.previousElementSibling;
            if (!input) return;
            var realVal = btn.getAttribute('data-real');
            if (input.type === 'password') {{
                input.type = 'text';
                input.value = realVal;
                btn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--danger)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>';
            }} else {{
                input.type = 'password';
                input.value = '••••••••';
                btn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>';
            }}
        }}
        </script>
        ''')
        body = "".join(parts)


    elif name == "admin_settings":
        s = ctx["s"]
        fields = ""
        for k in DEFAULT_SETTINGS.keys():
            v = str(s.get(k, ""))
            fields += '<div class="field"><label>' + k + '</label><input name="' + k + '" value="' + v + '"></div>'
        body = (
            '<div class="container" style="max-width:800px">'
            '<div class="section-title">الإعدادات</div>'
            '<a href="/admin" class="btn btn-ghost btn-sm" style="margin-bottom:20px">رجوع</a>'
            '<p style="color:var(--muted);margin-bottom:20px;font-size:14px">كل القيم تُحفظ فوراً.</p>'
            '<form method="POST" class="card">' + fields + '<button class="form-btn" style="margin-top:16px">حفظ الكل</button></form>'
            '</div>'
        )

    elif name == "admin_users":
        us = ctx["users"]
        cards_html = ""
        for x in us:
            cap_status = ico("check", 14) if (x["captcha_passed"] if "captcha_passed" in x.keys() else 0) else ico("clock", 14)
            is_adm = "<span style='background:var(--warn);color:#000;padding:2px 8px;border-radius:6px;font-size:10px;font-weight:900'>أدمن</span>" if x["is_admin"] else ""
            is_banned = x["is_banned"]
            status_badge = "<span style='background:rgba(239,68,68,0.15);color:var(--danger);padding:4px 10px;border-radius:8px;font-size:11px;font-weight:800'>محظور</span>" if is_banned else "<span style='background:rgba(16,185,129,0.15);color:var(--success);padding:4px 10px;border-radius:8px;font-size:11px;font-weight:800'>نشط</span>"
            uid_val = x["user_id"]
            uname = esc(x["username"])
            cid = esc(x["custom_id"] or x["user_id"])
            cards_html += (
                '<div style="background:var(--card);border:1px solid var(--border);border-radius:16px;margin-bottom:16px;overflow:hidden;">'
                '<div style="padding:16px;border-bottom:1px solid var(--border);background:rgba(255,255,255,0.02);">'
                '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">'
                '<div style="font-size:16px;font-weight:900;color:var(--text);display:flex;align-items:center;gap:6px;">' + uname + ' ' + is_adm + '</div>'
                + status_badge +
                '</div>'
                '<div style="font-size:12px;color:var(--muted);font-family:monospace;direction:ltr;text-align:left;margin-bottom:6px;">' + esc(x["email"]) + '</div>'
                '<div style="display:flex;justify-content:space-between;align-items:center;margin-top:10px;">'
                '<div style="display:flex;align-items:center;gap:6px;font-size:11px;color:var(--muted);">'
                '<span>الآيدي: <span style="background:rgba(99,102,241,0.15);color:var(--primary2);padding:2px 8px;border-radius:6px;font-family:monospace;font-weight:900;letter-spacing:1px;">' + cid + '</span></span>'
                '<button onclick="copyText(\'' + cid + '\', this)" class="copy-btn-inline" style="padding:3px 6px;font-size:10px;border-radius:6px;background:transparent;border:1px solid var(--border);color:var(--text);cursor:pointer;display:flex;align-items:center;">'
                '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>'
                '</button>'
                '</div>'
                '<div style="font-size:11px;color:var(--muted);">كابتشا: ' + cap_status + '</div>'
                '</div>'
                '</div>'
                '<div style="padding:16px;">'
                '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;background:var(--bg2);padding:12px;border-radius:12px;border:1px solid var(--border);">'
                '<div style="font-size:12px;color:var(--muted);font-weight:700;">الرصيد الحالي</div>'
                '<div style="font-size:20px;font-weight:900;color:var(--success);direction:ltr;">$' + f'{x["balance"]:.2f}' + '</div>'
                '</div>'
                '<div style="display:flex;gap:8px;flex-wrap:wrap;">'
                '<form method="POST" action="/admin/user/' + str(uid_val) + '/balance" style="display:flex;gap:6px;flex:1;min-width:140px;margin:0;">'
                '<input name="amount" type="number" step="0.01" placeholder="+/- مبلغ" style="flex:1;padding:10px;background:var(--bg2);color:var(--text);border:1px solid var(--border);border-radius:8px;font-size:12px;text-align:center;width:100%;">'
                '<button class="btn" style="padding:8px 12px;font-size:12px;background:var(--primary2);">تعديل</button>'
                '</form>'
                '<form method="POST" action="/admin/user/' + str(uid_val) + '/action" style="margin:0;">'
                '<button name="action" value="' + ('unban' if is_banned else 'ban') + '" class="btn" style="padding:10px 16px;font-size:12px;background:' + ('var(--success)' if is_banned else 'var(--danger)') + ';height:100%;">' + ('إلغاء الحظر' if is_banned else 'حظر') + '</button>'
                '</form>'
                '<a href="/admin/user/' + str(uid_val) + '/credentials" class="btn" style="padding:10px 16px;font-size:12px;background:rgba(99,102,241,0.15);border:1px solid rgba(99,102,241,0.3);color:var(--primary2);height:100%;display:flex;align-items:center;justify-content:center;">'
                + ico("key", 16) +
                '</a>'
                '<form method="POST" action="/admin/user/' + str(uid_val) + '/delete" style="margin:0;" onsubmit="return confirm(\'حذف المستخدم نهائياً؟\');">'
                '<button class="btn" style="padding:10px 16px;font-size:12px;background:rgba(239,68,68,0.15);border:1px solid rgba(239,68,68,0.3);color:var(--danger);height:100%;display:flex;align-items:center;justify-content:center;">'
                + ico("trash", 16) +
                '</button>'
                '</form>'
                '</div>'
                '</div>'
                '</div>'
            )
        body = (
            '<div class="container" style="max-width:700px;">'
            '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;">'
            '<div class="section-title" style="margin:0;">المستخدمون <span class="section-sub">(' + str(len(us)) + ')</span></div>'
            '<a href="/admin" class="btn btn-ghost btn-sm">' + ico("arrow-left", 14) + ' رجوع</a>'
            '</div>'
            + (cards_html if cards_html else '<div class="empty">لا يوجد مستخدمين</div>') +
            '</div>'
        )
    elif name == "admin_numbers":
        nums = ctx["numbers"]
        rows = ""
        for n in nums:
            if n["status"] == "available":
                act = f'<button type="button" onclick="editNumber({n["id"]}, \'{n["platform"]}\', {n["price"]}, {1 if ("is_premium" in n.keys() and n["is_premium"]) else 0})" class="btn btn-sm" style="background:var(--primary2);padding:6px 10px;font-size:11px;margin-left:4px">تعديل</button>'
                act += f'<form method="POST" style="display:inline"><input type="hidden" name="action" value="delete"><input type="hidden" name="id" value="{n["id"]}"><button class="btn btn-sm" style="background:var(--danger);padding:6px 10px;font-size:11px">حذف</button></form>'
            elif n["status"] == "sold":
                act = f'<form method="POST" action="/admin/sold/{n["id"]}/delete" style="display:inline" onsubmit="return confirm(\'تأكيد حذف الرقم المباع نهائياً؟\')"><button class="btn btn-sm" style="background:var(--danger);padding:6px 10px;font-size:11px">حذف</button></form>'
            else:
                act = "-"
            rows += f'<tr><td>#{n["id"]}</td><td><span class="badge {n["platform"]}">{n["platform"]}</span></td><td>{n["country"]}</td><td style="font-family:monospace;direction:ltr">{n["phone"]}</td><td style="direction:ltr;text-align:left">${n["price"]:.2f}</td><td><span class="badge {n["status"]}">{n["status"]}</span></td><td>{act}</td></tr>'
        body = f'''
        <div class="container"><div class="section-title">الأرقام <span class="section-sub">({len(nums)})</span></div>
          <a href="/admin" class="btn btn-ghost btn-sm" style="margin-bottom:20px">{ico("arrow-left", 14)} رجوع</a>
          <div class="card" style="margin-bottom:24px"><h3 style="font-size:16px;margin-bottom:14px">إضافة رقم</h3>
            <form method="POST" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px">
              <input type="hidden" name="action" value="add">
              <select name="platform" required style="padding:10px;background:var(--bg2);color:var(--text);border:1px solid var(--border);border-radius:8px;font-family:inherit;appearance:none;-webkit-appearance:none;cursor:pointer;">
                <option value="" disabled selected>-- اختر المنصة --</option>
                <option value="WhatsApp">واتساب (WhatsApp)</option>
                <option value="Telegram (Session)">تيليجرام (Telegram Session)</option>
              </select>
              <input name="phone" placeholder="+967777123456 (سيكتشف الدولة تلقائياً)" required style="padding:10px;background:var(--bg2);color:var(--text);border:1px solid var(--border);border-radius:8px;direction:ltr">
              <input name="price" type="number" step="0.01" placeholder="السعر" required style="padding:10px;background:var(--bg2);color:var(--text);border:1px solid var(--border);border-radius:8px">
              <label style="display:flex; align-items:center; gap:8px; padding:10px 14px; background:rgba(245,158,11,0.08); border:1px solid rgba(245,158,11,0.3); border-radius:8px; cursor:pointer;">
                <input type="checkbox" name="is_premium" style="width:18px; height:18px; accent-color:#f59e0b; cursor:pointer;">
                <span style="font-size:13px; font-weight:700; color:#f59e0b;">⭐ رقم مميز</span>
              </label>
              <button class="btn">إضافة</button>
            </form>
            <p style="color:var(--muted);font-size:12px;margin-top:8px;">💡 سيتم اكتشاف الدولة والعلم تلقائياً من كود الرقم.</p>
          </div>
          <script>
          function editNumber(nid, platform, price, isPremium) {{
              var newPrice = prompt('السعر الجديد بالدولار ($):', price);
              if (newPrice === null) return;
              var newPlat = prompt('المنصة (اكتب WhatsApp أو Telegram (Session)):', platform);
              if (newPlat === null) return;
              var isPrem = confirm('هل تريد جعله رقماً مميزاً؟ (OK = نعم، Cancel = لا)');
              
              var form = document.createElement('form');
              form.method = 'POST';
              form.innerHTML = '<input type="hidden" name="action" value="edit">' +
                               '<input type="hidden" name="id" value="' + nid + '">' +
                               '<input type="hidden" name="price" value="' + newPrice + '">' +
                               '<input type="hidden" name="platform" value="' + newPlat + '">' +
                               '<input type="hidden" name="is_premium" value="' + (isPrem ? '1' : '0') + '">';
              document.body.appendChild(form);
              form.submit();
          }}
          </script>
          <div class="table-wrap"><table class="table"><tr><th>#</th><th>المنصة</th><th>الدولة</th><th>الرقم</th><th>السعر</th><th>الحالة</th><th></th></tr>{rows or '<tr><td colspan="7" style="text-align:center;color:var(--muted)">لا أرقام</td></tr>'}</table></div>
        </div>'''

    elif name == "admin_vouchers":
        vs = ctx["vouchers"]
        rows = "".join(f'<tr><td>#{v["id"]}</td><td><code>{v["code"]}</code></td><td style="direction:ltr;text-align:left">${v["amount"]:.2f}</td><td>{"مستخدم" if v["is_used"] else "متاح"}</td><td style="font-size:12px;color:var(--muted)">{v["created_at"]}</td></tr>' for v in vs)
        body = f'''
        <div class="container"><div class="section-title">أكواد الشحن <span class="section-sub">({len(vs)})</span></div>
          <a href="/admin" class="btn btn-ghost btn-sm" style="margin-bottom:20px">{ico("arrow-left", 14)} رجوع</a>
          <div class="card" style="margin-bottom:24px"><h3 style="font-size:16px;margin-bottom:14px">توليد أكواد</h3>
            <form method="POST" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px">
              <input name="amount" type="number" step="0.01" min="0.01" placeholder="القيمة $" required style="padding:10px;background:var(--bg2);color:var(--text);border:1px solid var(--border);border-radius:8px">
              <input name="count" type="number" min="1" max="100" value="1" required style="padding:10px;background:var(--bg2);color:var(--text);border:1px solid var(--border);border-radius:8px">
              <button class="btn">توليد</button>
            </form>
          </div>
          <div class="table-wrap"><table class="table"><tr><th>#</th><th>الكود</th><th>القيمة</th><th>الحالة</th><th>التاريخ</th></tr>{rows or '<tr><td colspan="5" style="text-align:center;color:var(--muted)">لا أكواد</td></tr>'}</table></div>
        </div>'''

    elif name == "admin_coupons":
        cs = ctx["coupons"]
        rows = ""
        for c in cs:
            rows += f'''<tr>
              <td>
                <div style="display:flex; align-items:center; gap:6px;">
                  <code>{c["code"]}</code>
                  <button onclick="copyText('{c["code"]}', this)" class="copy-btn-inline" style="padding:4px 8px; font-size:11px;">
                    {ico("copy", 12)}
                  </button>
                </div>
              </td>
              <td>{c["percent"]:g}%</td>
              <td>{c["used_count"]}/{c["max_uses"] or "∞"}</td>
              <td style="font-size:11px">{c["expires_at"] or "دائم"}</td>
              <td><form method="POST" action="/admin/coupons/{c["code"]}/delete" style="display:inline"><button class="btn btn-sm" style="background:var(--danger);padding:6px 10px;font-size:11px">حذف</button></form></td>
            </tr>'''
        body = f'''
        <div class="container"><div class="section-title">الكوبونات <span class="section-sub">({len(cs)})</span></div>
          <a href="/admin" class="btn btn-ghost btn-sm" style="margin-bottom:20px">{ico("arrow-left", 14)} رجوع</a>
          <div class="card" style="margin-bottom:24px"><h3 style="font-size:16px;margin-bottom:14px">إنشاء كوبون</h3>
            <form method="POST" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px">
              <input name="code" placeholder="الكود (SUMMER20)" required style="padding:10px;background:var(--bg2);color:var(--text);border:1px solid var(--border);border-radius:8px;text-transform:uppercase;font-family:monospace">
              <input name="percent" type="number" step="1" min="1" max="90" placeholder="خصم % (1-90)" required style="padding:10px;background:var(--bg2);color:var(--text);border:1px solid var(--border);border-radius:8px">
              <input name="max_uses" type="number" min="0" value="0" placeholder="أقصى استخدامات (0=∞)" style="padding:10px;background:var(--bg2);color:var(--text);border:1px solid var(--border);border-radius:8px">
              <input name="days" type="number" min="0" value="0" placeholder="أيام الصلاحية (0=∞)" style="padding:10px;background:var(--bg2);color:var(--text);border:1px solid var(--border);border-radius:8px">
              <button class="btn">إنشاء</button>
            </form>
          </div>
          <div class="table-wrap"><table class="table"><tr><th>الكود</th><th>الخصم</th><th>استُخدم</th><th>الانتهاء</th><th></th></tr>{rows or '<tr><td colspan="5" style="text-align:center;color:var(--muted)">لا كوبونات</td></tr>'}</table></div>
        </div>'''


    elif name == "admin_stats":
        s = ctx["s"]
        body = f'''<div class="container">
          <div class="section-title">إحصائيات</div>
          <a href="/admin" class="btn btn-ghost btn-sm" style="margin-bottom:20px">{ico("arrow-left", 14)} رجوع</a>
          <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(160px,1fr))">
            <div class="card" style="text-align:center"><div style="font-size:32px;font-weight:900;color:var(--primary2)">{s["users"]}</div><div style="color:var(--muted);font-size:13px">مستخدمون</div></div>
            <div class="card" style="text-align:center"><div style="font-size:32px;font-weight:900;color:var(--primary2)">{s["numbers"]}</div><div style="color:var(--muted);font-size:13px">أرقام</div></div>
            <div class="card" style="text-align:center"><div style="font-size:32px;font-weight:900;color:var(--primary2)">{s["sold"]}</div><div style="color:var(--muted);font-size:13px">مبيوعة</div></div>
            <div class="card" style="text-align:center"><div style="font-size:32px;font-weight:900;color:var(--warn)">{s["pending"]}</div><div style="color:var(--muted);font-size:13px">شحنات معلقة</div></div>
            <div class="card" style="text-align:center"><div style="font-size:32px;font-weight:900;color:var(--warn)">{s["tickets"]}</div><div style="color:var(--muted);font-size:13px">تذاكر مفتوحة</div></div>
            <div class="card" style="text-align:center"><div style="font-size:32px;font-weight:900;color:var(--success)">${s["revenue"]:.2f}</div><div style="color:var(--muted);font-size:13px">إيرادات</div></div>
          </div>
        </div>'''

    elif name == "admin_tg":
        tg_nums = ctx.get("tg_nums", [])
        rows_parts = []
        for n in tg_nums:
            status_badge = "pending" if n["status"] == "pending" else ("available" if n["status"] == "available" else "sold")
            _sess_val = n["session_string"] if "session_string" in n.keys() else None
            has_session = ico("check", 14) if _sess_val else ico("x", 14)
            price = n["price"] or 0
            nid = n["id"]
            actions = ""
            # أزرار حسب الحالة
            actions = ''
            has_sess = bool(n["session_string"] if "session_string" in n.keys() else None)
            if n["status"] == "pending":
                if not has_sess:
                    actions = '<button type="button" class="btn btn-sm" style="display:inline-flex;align-items:center;gap:4px;padding:6px 10px;font-size:11px" onclick="window.requestCode(window.event, ' + str(nid) + ')"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg> كود</button> <button type="button" class="btn btn-sm" style="display:inline-flex;align-items:center;gap:4px;padding:6px 10px;font-size:11px" onclick="window.showVerify(' + str(nid) + ')"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg> تأكيد</button>'
                else:
                    actions = '<button class="btn btn-sm" style="display:inline-flex;align-items:center;gap:4px;padding:6px 10px;font-size:11px" onclick="showPrice(' + str(nid) + ')"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg> سعر</button>'
                    actions += ' <button class="btn btn-sm" style="background:var(--primary2);display:inline-flex;align-items:center;gap:4px;padding:6px 10px;font-size:11px" onclick="changePlatform(' + str(nid) + ')"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 1l4 4-4 4"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><path d="M7 23l-4-4 4-4"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/></svg> منصة</button>'
                    if price > 0:
                        actions += ' <form method="POST" action="/admin/tg/' + str(nid) + '/list" style="display:inline"><button class="btn btn-sm" style="background:var(--success);display:inline-flex;align-items:center;gap:4px;padding:6px 10px;font-size:11px"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><polyline points="19 12 12 19 5 12"/></svg> عرض</button></form>'
            elif n["status"] == "available":
                actions = '<form method="POST" action="/admin/tg/' + str(nid) + '/unlist" style="display:inline"><button class="btn btn-sm" style="background:var(--warn);display:inline-flex;align-items:center;gap:4px;padding:6px 10px;font-size:11px"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/></svg> سحب</button></form>'
            elif n["status"] == "sold":
                actions = '<span style="color:var(--danger);font-size:11px">مباع</span>'
                actions += ' <form method="POST" action="/admin/tg/' + str(nid) + '/delete" style="display:inline" onsubmit="return confirm(\'حذف؟\')"><button class="btn btn-sm" style="background:var(--danger);display:inline-flex;align-items:center;gap:4px;padding:6px 10px;font-size:11px"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg></button></form>' 
        
            rows_parts.append('<tr><td>#' + str(nid) + '</td><td>' + str(n["phone"]) + '</td><td>' + str(n["country"]) + '</td><td>' + has_session + '</td><td>$' + f'{price:.2f}' + '</td><td><span class="badge ' + status_badge + '">' + n["status"] + '</span></td><td>' + actions + '</td></tr>')
        rows = "".join(rows_parts) or '<tr><td colspan="7" style="text-align:center;color:var(--muted)">لا أرقام</td></tr>'

        tg_js = """
<script>
window.requestCode = function(evt, nid) {
    var btn = evt && evt.currentTarget ? evt.currentTarget : (evt && evt.target ? evt.target : null);
    console.log('[requestCode] called for nid=' + nid);
    if (!confirm('طلب كود من تيليجرام للرقم #' + nid + '؟')) return;
    if (!btn) btn = document.querySelector('button[data-nid="' + nid + '"]');
    var originalHtml = btn ? btn.innerHTML : 'كود';
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span style="font-size:11px;">جاري...</span>';
    }
    
    fetch('/admin/tg/' + nid + '/request-code', {
        method: 'POST',
        headers: {'Accept': 'application/json'},
        credentials: 'same-origin'
    })
    .then(r => r.json())
    .then(d => {
        if (d.ok) {
            alert(d.msg || 'تم إرسال الكود');
            location.reload();
        } else {
            if (btn) { btn.disabled = false; btn.innerHTML = originalHtml; }
            alert('فشل: ' + (d.error || 'خطأ غير معروف'));
        }
    })
    .catch(e => {
        if (btn) { btn.disabled = false; btn.innerHTML = originalHtml; }
        alert('خطأ: ' + e.message);
    });
};
window.showVerify = function(nid) {
    document.getElementById('verifyArea').innerHTML = '<div class="card" style="margin-bottom:20px;border-color:var(--primary)"><h3>تأكيد الكود للرقم #' + nid + '</h3><input id="codeInput_' + nid + '" placeholder="أدخل الكود" style="width:100%;padding:12px;margin:12px 0;background:var(--bg2);color:var(--text);border:1px solid var(--border);border-radius:10px;font-family:monospace;text-align:center;font-size:18px;letter-spacing:4px"><div style="display:flex;gap:8px;margin-bottom:12px;"><select id="platInput_' + nid + '" style="flex:1;padding:10px;background:var(--bg2);color:var(--text);border:1px solid var(--border);border-radius:10px;"><option value="Telegram (Session)" selected>Telegram (Session)</option><option value="WhatsApp">WhatsApp</option></select><input id="priceInput_' + nid + '" type="number" step="0.01" min="0.01" value="1.00" style="flex:1;padding:10px;background:var(--bg2);color:var(--text);border:1px solid var(--border);border-radius:10px;direction:ltr;"></div><label style="display:flex;align-items:center;gap:8px;padding:10px;margin-bottom:12px;background:rgba(245,158,11,0.08);border:1px solid rgba(245,158,11,0.3);border-radius:8px;cursor:pointer;"><input type="checkbox" id="isPremium_' + nid + '" style="width:18px;height:18px;accent-color:#f59e0b;cursor:pointer;"><span style="font-size:13px;font-weight:700;color:#f59e0b;">⭐ رقم مميز</span></label><button class="btn" onclick="verifyCode(' + nid + ')">تأكيد</button><div id="verifyResult_' + nid + '" style="margin-top:12px"></div></div>';
}
function verifyCode(nid) {
    var code = document.getElementById('codeInput_' + nid).value;
    fetch('/admin/tg/' + nid + '/verify', {
        method: 'POST',
        headers: {'Content-Type': 'application/x-www-form-urlencoded'},
        body: 'code=' + encodeURIComponent(code) + '&platform=' + encodeURIComponent(document.getElementById('platInput_' + nid).value) + '&price=' + encodeURIComponent(document.getElementById('priceInput_' + nid).value) + '&is_premium=' + (document.getElementById('isPremium_' + nid).checked ? 'on' : 'off')
    }).then(r => r.json()).then(d => {
        var res = document.getElementById('verifyResult_' + nid);
        if (d.ok) {
            res.innerHTML = '<div style="color:var(--success)"> تم التأكيد!</div>';
            setTimeout(() => location.reload(), 1500);
        } else if (d.need_2fa) {
            res.innerHTML = '<div style="color:var(--warn); display:flex; align-items:center; gap:6px;"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg> يتطلب 2FA</div><input id="pwInput_' + nid + '" type="password" placeholder="كلمة سر 2FA" style="width:100%;padding:12px;margin:12px 0;background:var(--bg2);color:var(--text);border:1px solid var(--border);border-radius:10px"><button class="btn" onclick="verify2FA(' + nid + ')">تأكيد 2FA</button>';
        } else {
            res.innerHTML = '<div style="color:var(--danger)">❌ ' + (d.error || 'فشل') + '</div>';
        }
    });
}
function verify2FA(nid) {
    var pw = document.getElementById('pwInput_' + nid).value;
    fetch('/admin/tg/' + nid + '/2fa', {
        method: 'POST',
        headers: {'Content-Type': 'application/x-www-form-urlencoded'},
        body: 'password=' + encodeURIComponent(pw)
    }).then(r => r.json()).then(d => {
        if (d.ok) {
            document.getElementById('verifyResult_' + nid).innerHTML = '<div style="color:var(--success)"> تم!</div>';
            setTimeout(() => location.reload(), 1500);
        } else {
            document.getElementById('verifyResult_' + nid).innerHTML = '<div style="color:var(--danger)">❌ ' + (d.error || 'فشل') + '</div>';
        }
    });
}

// ربط الأزرار بعد تحميل الصفحة
document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('[id^="btnCode_"]').forEach(function(btn) {
        var nid = btn.id.replace('btnCode_', '');
        btn.addEventListener('click', function(e) {
            e.preventDefault();
            window.requestCode({currentTarget: btn}, nid);
        });
    });
    document.querySelectorAll('[id^="btnVerify_"]').forEach(function(btn) {
        var nid = btn.id.replace('btnVerify_', '');
        btn.addEventListener('click', function(e) {
            e.preventDefault();
            window.showVerify(nid);
        });
    });
});
function showPrice(nid) {
    var price = prompt('أدخل السعر بالدولار:', '1.00');
    if (!price) return;
    fetch('/admin/tg/' + nid + '/price', {
        method: 'POST',
        headers: {'Content-Type': 'application/x-www-form-urlencoded'},
        body: 'price=' + encodeURIComponent(price)
    }).then(() => location.reload());
}

function changePlatform(nid) {
    var p = prompt('اختر المنصة:\\n1 = WhatsApp\\n2 = Telegram (Session)', '2');
    if (!p) return;
    var platform = (p === '1') ? 'WhatsApp' : 'Telegram (Session)';
    fetch('/admin/tg/' + nid + '/platform', {
        method: 'POST',
        headers: {'Content-Type': 'application/x-www-form-urlencoded'},
        body: 'platform=' + encodeURIComponent(platform)
    }).then(() => location.reload());
}

// ربط الأزرار بعد تحميل الصفحة
(function() {
    function bindButtons() {
        document.querySelectorAll('[id^="btnCode_"]').forEach(function(btn) {
            if (btn.dataset.bound) return;
            btn.dataset.bound = '1';
            var nid = btn.id.replace('btnCode_', '');
            btn.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                window.requestCode({currentTarget: btn}, nid);
            });
        });
        document.querySelectorAll('[id^="btnVerify_"]').forEach(function(btn) {
            if (btn.dataset.bound) return;
            btn.dataset.bound = '1';
            var nid = btn.id.replace('btnVerify_', '');
            btn.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                window.showVerify(nid);
            });
        });
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bindButtons);
    } else {
        bindButtons();
    }
})();
</script>
"""

        # نضع الـ JavaScript أولاً (قبل الجدول) عشان الدوال تكون معرّفة
        body = tg_js
        body += '<div class="container"><div class="section-title"> إدارة أرقام تيليجرام</div>'
        body += '<a href="/admin" class="btn btn-ghost btn-sm" style="margin-bottom:16px">' + ico("arrow-left", 14) + ' رجوع</a>'
        body += '<div class="card" style="margin-bottom:20px"><h3 style="font-size:16px;margin-bottom:12px">إضافة رقم جديد</h3><form method="POST" action="/admin/tg/add" style="display:flex;gap:10px;flex-wrap:wrap"><input name="phone" placeholder="+967777123456" required style="flex:1;min-width:200px;padding:12px;background:var(--bg2);color:var(--text);border:1px solid var(--border);border-radius:10px;direction:ltr"><button class="btn">إضافة</button></form></div>'
        body += '<div id="verifyArea"></div>'
        body += '<div class="table-wrap"><table class="table" style="font-size:13px"><tr><th>#</th><th>الرقم</th><th>الدولة</th><th>جلسة</th><th>السعر</th><th>الحالة</th><th>إجراءات</th></tr>' + rows + '</table></div></div>'

    elif name == "admin_payments":
        items = ctx["items"]
        total = ctx["total"]
        ready = ctx["ready_count"]
        
        rows_html = ""
        for i in items:
            color = "var(--success)" if i["remaining"] <= 0 else "var(--warn)"
            time_text = "جاهز للدفع" if i["remaining"] <= 0 else f"{int(i['remaining'])} ساعة متبقية"
            rows_html += f"""
            <div style="background:var(--card);border:1px solid var(--border);border-radius:12px;padding:14px;margin-bottom:10px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px">
              <div style="flex:1;min-width:200px">
                <div style="font-weight:800;margin-bottom:4px">{esc(i['username'])} <code style="font-size:11px;color:var(--muted)">#{i['user_id']}</code></div>
                <div style="font-family:monospace;font-size:13px;color:var(--primary2);direction:ltr">{esc(i['phone'])} · {esc(i['country'])}</div>
                <div style="font-size:11px;color:{color};margin-top:4px">{time_text}</div>
              </div>
              <div style="text-align:left">
                <div style="font-size:20px;font-weight:900;color:var(--success);direction:ltr;margin-bottom:6px">${i['amount']:.2f}</div>
                <form method="POST" action="/admin/payments/pay/{i['id']}" style="margin:0">
                  <button class="btn btn-sm" style="background:var(--success);padding:6px 14px;font-size:12px">{ico("check", 12)} ادفع الآن</button>
                </form>
              </div>
            </div>"""
        
        if not rows_html:
            rows_html = '<div class="empty">لا مدفوعات معلقة حالياً</div>'
        
        body = f"""
        <div class="container" style="max-width:800px">
          <div class="section-title">المدفوعات المعلقة</div>
          <a href="/admin" class="btn btn-ghost btn-sm" style="margin-bottom:20px">{ico("arrow-left", 14)} رجوع</a>
          
          <div class="grid" style="grid-template-columns:1fr 1fr;margin-bottom:20px">
            <div class="card" style="text-align:center">
              <div style="font-size:13px;color:var(--muted);margin-bottom:6px">إجمالي المعلق</div>
              <div style="font-size:28px;font-weight:900;color:var(--warn);direction:ltr">${total:.2f}</div>
            </div>
            <div class="card" style="text-align:center">
              <div style="font-size:13px;color:var(--muted);margin-bottom:6px">جاهز للدفع (24 ساعة)</div>
              <div style="font-size:28px;font-weight:900;color:var(--success)">{ready}</div>
            </div>
          </div>
          
          {'<form method="POST" action="/admin/payments/pay_all" style="margin-bottom:20px"><button class="btn" style="width:100%">' + ico("check-circle", 16) + ' دفع الكل (الجاهز)</button></form>' if ready > 0 else ''}
          
          <div class="section-title" style="font-size:18px">السجلات ({len(items)})</div>
          {rows_html}
        </div>"""
        return page("admin_payments_body", body=body)
    
    elif name == "admin_payments_body":
        body = ctx.get("body", "")

    elif name == "admin_icons":
        body = ctx.get("body", "")

    elif name == "vip":
        body = ctx.get("body", "<div class='container'>VIP</div>")

    elif name == "admin_view_2fa":
        body = ctx.get("body", "")

    elif name == "admin_pending_sellers":
        body = ctx.get("body", "<div class='container'><div class='empty'>لا توجد أرقام</div></div>")

    elif name == "admin_sold":
        body = ctx.get("body", "<div class='container'><div class='empty'>لا توجد أرقام مباعة</div></div>")

    elif name == "profile":
        body = ctx.get("body", "")

    elif name == "profile_edit":
        body = ctx.get("body", "")

    elif name == "sell_prices":
        body = ctx.get("body", "")

    elif name == "admin_buy_prices":
        body = ctx.get("body", "")

    elif name == "about_page":
        body = ctx.get("body", "")

    elif name == "my_pending_sales":
        body = ctx.get("body", "<div class='container'><div class='empty'>لا توجد أرقام</div></div>")

    elif name == "error":
        body = f'''
        <div class="container" style="text-align:center;padding:100px 20px">
          <div style="font-size:120px;font-weight:900;background:var(--gradient);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;line-height:1">{ctx.get("code")}</div>
          <p style="color:var(--muted);font-size:18px;margin:20px 0 32px">{ctx.get("msg")}</p>
          <a href="/" class="btn">العودة للرئيسية</a>
        </div>'''

    ann_text = get_setting("ANNOUNCEMENT", "").strip()
    ann_level = get_setting("ANNOUNCEMENT_LEVEL", "info")
    announcement_html = ""
    if ann_text:
        announcement_html = f'<div class="container" style="padding-top:16px;padding-bottom:0"><div class="flash {ann_level}">{ann_text}</div></div>'

    # عرض الشريط فقط في الصفحة الرئيسية
    if name == "index":
        events_list = get_live_events()
        import json as _json
        ticker_code = ticker_template.replace("__EVENTS_JSON__", _json.dumps(events_list, ensure_ascii=False))
    else:
        ticker_code = ""
    
    # توليد الشريط للصفحة الرئيسية فقط
    if name == "index":
        try:
            events_list = get_live_events()
            import json as _json
            ticker_template = '''<div id="liveTicker" style="position:fixed;top:75px;left:50%;transform:translateX(-50%) translateY(-30px);z-index:99999;display:flex;align-items:center;justify-content:center;padding:12px 24px;background:rgba(20,20,40,0.85);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);border:1.5px solid rgba(251,191,36,0.4);border-radius:50px;box-shadow:0 10px 40px rgba(0,0,0,0.6), 0 0 30px rgba(251,191,36,0.15);opacity:0;transition:all 0.5s cubic-bezier(0.4,0,0.2,1);max-width:92vw;overflow:hidden;">
    <div id="tickerInner" style="display:flex;align-items:center;gap:10px;font-size:13px;font-weight:800;color:#fff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
        <svg id="tickerIcon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#fbbf24" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;"><path d="M3 11l18-5v12L3 14v-3z"/><path d="M11.6 16.8a3 3 0 1 1-5.8-1.6"/></svg>
        <span id="tickerMsg" style="color:#e8e8f5;"></span>
    </div>
</div>
<script>
(function() {
    var ticker = document.getElementById('liveTicker');
    if (!ticker) return;
    var today = new Date().toDateString();
    var storedDate = localStorage.getItem('tickerDate');
    var viewCount = parseInt(localStorage.getItem('tickerViewCount') || '0');
    if (storedDate !== today) { viewCount = 0; localStorage.setItem('tickerDate', today); }
    if (viewCount >= 20) { ticker.remove(); return; }
    viewCount++;
    localStorage.setItem('tickerViewCount', viewCount.toString());
    var events = __EVENTS_JSON__;
    var msg = document.getElementById('tickerMsg');
    var icon = document.getElementById('tickerIcon');
    function renderEvent(ev) {
        var bg, border, iconColor, label;
        if (ev.type === 'buy') {
            bg = 'rgba(16,185,129,0.15)'; border = 'rgba(16,185,129,0.4)'; iconColor = '#10b981';
            label = 'قام <b style="color:#fbbf24;">' + ev.user + '</b> بشراء ' + ev.text + ' بنجاح';
            icon.innerHTML = '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>';
        } else if (ev.type === 'deposit') {
            bg = 'rgba(99,102,241,0.15)'; border = 'rgba(99,102,241,0.4)'; iconColor = '#818cf8';
            label = 'تم شحن <b style="color:#fbbf24;">' + ev.text + '</b> لحساب <b style="color:#fbbf24;">' + ev.user + '</b>';
            icon.innerHTML = '<line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>';
        } else {
            bg = 'rgba(251,191,36,0.15)'; border = 'rgba(251,191,36,0.4)'; iconColor = '#fbbf24';
            label = '<b>' + ev.user + '</b>: ' + ev.text;
            icon.innerHTML = '<path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2z"/>';
        }
        ticker.style.background = 'linear-gradient(135deg, rgba(20,20,40,0.95), ' + bg + ')';
        ticker.style.borderColor = border;
        icon.style.stroke = iconColor;
        msg.innerHTML = label;
    }
    renderEvent(events[0]);
    setTimeout(function() { ticker.style.transform = 'translateX(-50%) translateY(0)'; ticker.style.opacity = '1'; }, 100);
    var idx = 0;
    var swap = setInterval(function() {
        idx = (idx + 1) % events.length;
        msg.style.opacity = '0';
        setTimeout(function() { renderEvent(events[idx]); msg.style.opacity = '1'; }, 300);
    }, 3500);
    setTimeout(function() {
        clearInterval(swap);
        ticker.style.transform = 'translateX(-50%) translateY(-30px)';
        ticker.style.opacity = '0';
    }, 20000);
})();
</script>'''
            ticker_code = ticker_template.replace("__EVENTS_JSON__", _json.dumps(events_list, ensure_ascii=False))
        except Exception as e:
            print(f"[TICKER] خطأ: {e}")
            ticker_code = ""

    if getattr(_CAPTURE, "on", False):
        return body
    return f'''<!DOCTYPE html>
<html lang="ar" dir="rtl" data-theme="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
  <meta name="mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <title>{get_setting("SITE_NAME", "MATARI STORE")} · MATARI STORE</title>
  <script>(function(){{var t=localStorage.getItem('theme')||'dark';document.documentElement.setAttribute('data-theme',t);}})();</script>
  <link rel="manifest" href="/manifest.json">
  <link rel="icon" href="/icon.svg" type="image/svg+xml">
  <meta name="theme-color" content="#6366f1">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800;900&family=Tajawal:wght@700;800;900&display=swap" rel="stylesheet">
  <style>{CSS}</style>
  <style>{SMOOTH_CSS}{DASH_CSS_EXTRA}</style>
</head>
<body>
{ticker_code}
{_nav(u)}
{_bottom_nav(u, active)}
{announcement_html}
<div class="container" style="padding-top:16px;padding-bottom:0">{fh}</div>
{body}{_pb_dashboard_block(u) if name == "dashboard" else ""}

<div style="text-align:center; padding: 30px 0 20px 0; width: 100%;">
  <div style="display:inline-flex; align-items:center; gap:8px; background:var(--card); border:1px solid var(--border); padding:10px 18px; border-radius:30px; font-size:12px; font-weight:700; color:var(--muted); box-shadow:0 4px 12px rgba(0,0,0,0.2);">
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--primary2)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
    <span>MATARI STORE © 2026</span>
  </div>
</div>
{get_notif_btn()}
<script>{JS}</script>
<script>{SMOOTH_JS}</script>
</body>
</html>'''

# ============================================================
# PWA
# ============================================================
@app.route("/manifest.json")
def manifest():
    return jsonify({
        "name": "MATARI STORE", "short_name": "MATARI",
        "start_url": "/", "display": "standalone",
        "background_color": "#0f0f1a", "theme_color": "#6366f1",
        "lang": "ar", "dir": "rtl",
        "icons": [{"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml"}]
    })

@app.route("/icon.svg")
def icon():
    svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 192 192"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#6366f1"/><stop offset=".5" stop-color="#8b5cf6"/><stop offset="1" stop-color="#06b6d4"/></linearGradient></defs><rect width="192" height="192" rx="42" fill="url(#g)"/><path d="M48 76 L96 40 L144 76 L144 148 L48 148 Z" fill="none" stroke="#ff" stroke-width="8" stroke-linejoin="round"/><rect x="78" y="104" width="36" height="44" fill="#ff" rx="4"/></svg>'''
    return Response(svg, mimetype="image/svg+xml")

# ============================================================
# التهيئة (بدون تشغيل تلقائي)
# ============================================================

# ============================================================
# إصلاح تلقائي شامل للداتابيز (يشتغل مع كل تشغيل)
# ============================================================
def auto_fix_db():
    """يتأكد من وجود كل الأعمدة والجداول اللي الكود محتاجها"""
    con = sqlite3.connect(DB_PATH, timeout=30)
    try:
        # قائمة بكل الجداول والأعمدة المطلوبة
        needed_columns = [
            # (اسم الجدول، اسم العمود، تعريف العمود)
            # جدول users
            ("users", "avatar", "TEXT"),
            ("users", "captcha_passed", "INTEGER DEFAULT 0"),
            ("users", "last_bonus", "TEXT"),
            ("users", "total_spent", "REAL DEFAULT 0"),
            ("users", "bad_coupons", "INTEGER DEFAULT 0"),
            ("users", "referral_earnings", "REAL DEFAULT 0.0"),
            ("users", "custom_id", "TEXT"),
            # جدول numbers
            ("numbers", "seen_by_buyer", "INTEGER DEFAULT 0"),
            ("numbers", "request_time", "TEXT"),
            ("numbers", "two_fa_password", "TEXT"),
            ("numbers", "is_premium", "INTEGER DEFAULT 0"),
            ("numbers", "paid_price", "REAL"),
            ("numbers", "session_string", "TEXT"),
            ("numbers", "last_code", "TEXT"),
            # جدول ticket_messages
            ("ticket_messages", "is_read", "INTEGER DEFAULT 0"),
            # جدول announcements
            ("announcements", "text_color", "TEXT DEFAULT '#e8e8f5'"),
            ("announcements", "font_size", "TEXT DEFAULT '15px'"),
            ("announcements", "icon", "TEXT DEFAULT 'bell'"),
            ("announcements", "icon_name", "TEXT DEFAULT 'bell'"),
            ("announcements", "is_active", "INTEGER DEFAULT 1"),
            # جدول buy_prices
            ("buy_prices", "code", "TEXT DEFAULT ''"),
            ("buy_prices", "flag", "TEXT DEFAULT ''"),
        ]
        
        added = 0
        for table, col, decl in needed_columns:
            try:
                # نتأكد إن الجدول موجود
                cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
                if not cols:
                    # الجدول مش موجود، نتخطاه
                    continue
                if col not in cols:
                    con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
                    added += 1
                    print(f"[AUTO-FIX] added {table}.{col}")
            except sqlite3.OperationalError as e:
                print(f"[AUTO-FIX] error on {table}.{col}: {e}")
        
        # إنشاء جداول ناقصة
        con.execute("CREATE TABLE IF NOT EXISTS pending_sellers (number_id INTEGER, user_id INTEGER, created_at TEXT)")
        con.execute("CREATE TABLE IF NOT EXISTS pending_balance (user_id INTEGER, amount REAL, number_id INTEGER, created_at TEXT)")
        
        # التأكد من الأعمدة الناقصة في جدول settings
        try:
            cols = [r[1] for r in con.execute("PRAGMA table_info(settings)")]
            if not cols:
                con.execute("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT)")
        except:
            pass
        
        # إضافة قيم افتراضية للإعدادات لو مش موجودة
        default_settings = {
            "WHEEL_ENABLED": "1",
            "WHEEL_PRIZES": "0.01,0.05,0.10,0.02,0.00,0.05,0.01,0.20",
            "WHEEL_MAX_SPINS": "1",
            "WHEEL_MAX_PRIZE": "0.20",
            "REWARD_MODE": "daily",
            "DAILY_BONUS_ENABLED": "1",
            "REFERRAL_ENABLED": "1",
        }
        for k, v in default_settings.items():
            try:
                con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
            except:
                pass
        
        con.commit()
        if added > 0:
            print(f"[AUTO-FIX] Fixed {added} columns successfully.")
        else:
            print("[AUTO-FIX] Database is up to date.")
    except Exception as e:
        print(f"[AUTO-FIX] Fatal error: {e}")
    finally:
        con.close()


def run_migrations():
    """ترحيلات آمنة - بتتنفذ في كل تشغيل."""
    auto_fix_db()
    con = sqlite3.connect(DB_PATH, timeout=30)
    try:
        needed = [
            ("announcements", "text_color", "TEXT DEFAULT '#e8e8f5'"),
            ("announcements", "font_size", "TEXT DEFAULT '15px'"),
            ("announcements", "icon", "TEXT DEFAULT 'bell'"),
            ("announcements", "icon_name", "TEXT DEFAULT 'bell'"),
            ("buy_prices", "code", "TEXT DEFAULT ''"),
            ("users", "avatar", "TEXT"),
            ("numbers", "is_premium", "INTEGER DEFAULT 0"),
        ]
        for table, col, decl in needed:
            try:
                cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
                if col not in cols:
                    con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
                    print(f"[migration] added {table}.{col}")
            except sqlite3.OperationalError as e:
                print(f"[migration] skip {table}.{col}: {e}")
        con.execute("CREATE TABLE IF NOT EXISTS pending_sellers (number_id INTEGER, user_id INTEGER, created_at TEXT)")
        con.commit()
        print("[migration] done")
    finally:
        con.close()


# (التهيئة الآن تتم في bootstrap_database() أسفل الملف)


# ============================================================
# التشغيل التلقائي
# ============================================================
# ============================================================
# ADMIN TEST ROUTES (Email + Binance)
# ============================================================
@app.route("/admin/test_email")
@admin_required
def admin_test_email():
    addr = get_setting("EMAIL_ADDRESS", "").strip()
    pwd = get_setting("EMAIL_PASSWORD", "").strip()
    host = get_setting("IMAP_HOST", "imap.gmail.com").strip()
    if not addr or not pwd:
        return jsonify({"ok": False, "error": "الإيميل أو كلمة المرور غير محفوظة."})
    try:
        import imaplib
        M = imaplib.IMAP4_SSL(host, timeout=15)
        M.login(addr, pwd)
        M.logout()
        return jsonify({"ok": True, "msg": "تم الاتصال بالإيميل بنجاح!"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:100]})


@app.route("/admin/test_binance")
@admin_required
def admin_test_binance():
    api_key = get_setting("BINANCE_API_KEY", "").strip()
    api_secret = get_setting("BINANCE_API_SECRET", "").strip()
    if not api_key or not api_secret:
        return jsonify({"ok": False, "error": "مفاتيح Binance غير محفوظة."})
    try:
        import hmac, hashlib, time, requests
        from urllib.parse import urlencode
        params = {"timestamp": int(time.time() * 1000), "recvWindow": 5000}
        qs = urlencode(params)
        sig = hmac.new(api_secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
        url = "https://api.binance.com/api/v3/account?" + qs + "&signature=" + sig
        res = requests.get(url, headers={"X-MBX-APIKEY": api_key}, timeout=15).json()
        if res.get("accountType"):
            return jsonify({"ok": True, "msg": "تم الاتصال بنجاح! الحساب: " + str(res["accountType"])})
        return jsonify({"ok": False, "error": str(res.get("msg", "مفاتيح غير صالحة"))})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:100]})


@app.route("/check-otp/<int:nid>", methods=["POST"])
@login_required
def check_otp(nid):
    u = current_user()
    n = db().execute("SELECT * FROM numbers WHERE id=? AND buyer_id=?", (nid, u["user_id"])).fetchone()
    if not n:
        return jsonify({"ok": False, "error": "غير مصرح"})
    
    # إذا كان الكود موجوداً، أرجعه
    if n["last_code"]:
        return jsonify({"ok": True, "code": n["last_code"]})
    
    # إذا لم يكن موجوداً، حاول سحبه الآن
    platform = (n["platform"] or "").lower()
    code = None
    err = None
    
    try:
        if "telegram" in platform:
            session = n["session_string"]
            if session:
                code, err = _tg_fetch_code(session, 0, phone=n["phone"])
        else:
            # نمرر sold_at كـ since_ts لفلترة الرسائل القديمة
            _st = 0
            if n["sold_at"]:
                try:
                    from datetime import datetime as _dt
                    _st = _dt.strptime(n["sold_at"], "%Y-%m-%d %H:%M:%S").timestamp()
                except Exception:
                    pass
            code, err = fetch_otp_imap(since_ts=_st)
    except Exception as e:
        err = str(e)[:100]
    
    if code:
        db().execute("UPDATE numbers SET last_code=? WHERE id=?", (code, nid))
        db().commit()
        return jsonify({"ok": True, "code": code})
    
    return jsonify({"ok": False, "error": err or "لا كود بعد"})


@app.route("/profile")
def profile_page():
    u = current_user()
    profile_id = get_setting("PROFILE_ID", "")
    profile_name = get_setting("PROFILE_NAME", "MATARI STORE")
    profile_bio = get_setting("PROFILE_BIO", "مرحباً بك في متجري")
    body = (
        '<div class="container" style="max-width:600px">'
        '<div class="section-title" style="text-align:center">' + esc(profile_name) + '</div>'
        '<div class="card" style="text-align:center; padding:30px">'
        '<div style="width:80px; height:80px; margin:0 auto 20px; background:var(--gradient); border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:36px; color:#fff">'
        + ico("user", 48) + '</div>'
        '<div style="font-size:15px; color:var(--muted); margin-bottom:20px">' + esc(profile_bio) + '</div>'
        '<div style="background:var(--bg2); border-radius:12px; padding:16px; margin-bottom:16px">'
        '<div style="font-size:12px; color:var(--muted); margin-bottom:6px">آيدي التحويل</div>'
        '<div style="display:flex; align-items:center; gap:10px; justify-content:center">'
        '<code style="font-size:18px; color:var(--primary2)">' + esc(profile_id) + '</code>'
        '<button onclick="copyText(\'' + esc(profile_id) + '\', this)" class="btn btn-sm" style="padding:6px 12px">' + ico("copy", 14) + ' نسخ</button>'
        '</div></div>'
        '<a href="/transfer" class="btn" style="width:100%; margin-bottom:10px; display:flex; align-items:center; justify-content:center; gap:8px">' + ico("send", 16) + ' تحويل رصيد</a>'
        '<a href="/deposit" class="btn btn-ghost" style="width:100%; display:flex; align-items:center; justify-content:center; gap:8px">' + ico("wallet", 16) + ' شحن الرصيد</a>'
        '</div></div>'
    )
    return page("profile", body=body, profile_id=profile_id, profile_name=profile_name)

def _tg_force_logout_others(*args, **kwargs):
    """(معطّلة) طرد أجهزة البائع من حسابه لمنع استرجاعه، غير مفعّلة."""
    return None


def _tg_check_has_2fa(session_str):
    """يتحقق إذا كان الرقم عليه تحقق بخطوتين (2FA). يرجع (bool, err)"""
    if not session_str:
        return False, "لا توجد جلسة"
    try:
        from telethon.sync import TelegramClient
        from telethon.sessions import StringSession
        from telethon.tl.functions.account import GetPasswordRequest
        import asyncio

        api_id = int(get_setting("TG_API_ID", "22651991"))
        api_hash = get_setting("TG_API_HASH", "").strip()
        if not api_hash:
            return False, "API Hash غير مهيأ"

        async def run():
            client = TelegramClient(StringSession(session_str), api_id, api_hash)
            await client.connect()
            try:
                if not await client.is_user_authorized():
                    return False, "الجلسة غير مصرح بها"
                pwd_info = await client(GetPasswordRequest())
                return bool(pwd_info.has_password), None
            finally:
                await client.disconnect()

        return asyncio.run(asyncio.wait_for(run(), 30))
    except Exception as e:
        return False, "خطأ: " + str(e)[:100]


def _tg_remove_2fa(session_str, current_password):
    """يشيل 2FA باستخدام edit_2fa (متوافق مع Telethon 1.45.0).
    يرجع (new_session_str, None) عند النجاح، أو (None, error) عند الفشل."""
    if not session_str or not current_password:
        return None, "بيانات ناقصة"
    try:
        from telethon.sync import TelegramClient
        from telethon.sessions import StringSession
        import asyncio

        api_id = int(get_setting("TG_API_ID", "22651991"))
        api_hash = get_setting("TG_API_HASH", "").strip()
        if not api_hash:
            return None, "API Hash غير مهيأ"

        async def run():
            client = TelegramClient(StringSession(session_str), api_id, api_hash)
            await client.connect()
            try:
                if not await client.is_user_authorized():
                    return None, "الجلسة غير مصرح بها"
                # edit_2fa هو الطريق الرسمي في Telethon 1.45.0
                # تمرير new_password=None يعني إزالة 2FA
                ok = await client.edit_2fa(
                    current_password=current_password,
                    new_password=None,
                )
                if not ok:
                    return None, "فشل إزالة 2FA (edit_2fa رجع False)"
                return client.session.save(), None
            except Exception as e:
                msg = str(e)
                if "PASSWORD_HASH_INVALID" in msg:
                    return None, "كلمة السر خاطئة."
                if "SessionPasswordNeededError" in type(e).__name__:
                    return None, "كلمة السر خاطئة أو غير مطلوبة."
                return None, "خطأ: " + msg[:150]
            finally:
                await client.disconnect()

        return asyncio.run(asyncio.wait_for(run(), 60))
    except Exception as e:
        return None, "خطأ: " + str(e)[:100]


def _tg_enable_2fa_protected(*args, **kwargs):
    """(معطّلة) تعيين كلمة سر 2FA على الحساب، معطّلة لمنع قفل حسابات البيع."""
    return None


@app.route("/admin/fetch-otp/<int:nid>", methods=["POST"])
@admin_required
def admin_fetch_otp(nid):
    n = db().execute("SELECT * FROM numbers WHERE id=?", (nid,)).fetchone()
    if not n or not n["session_string"]:
        flash("الرقم غير موجود أو لا توجد جلسة محفوظة.", "error")
        return redirect(url_for("admin_pending_sellers"))
    
    code, err = _tg_fetch_code(n["session_string"])
    if code:
        db().execute("UPDATE numbers SET last_code=? WHERE id=?", (code, nid))
        db().commit()
        flash(f"تم سحب الكود بنجاح: {code}", "success")
    else:
        flash(f"فشل سحب الكود: {err}", "error")
    return redirect(url_for("admin_pending_sellers"))



@app.route("/admin/save_2fa/<int:nid>", methods=["POST"])
@admin_required
def admin_save_2fa(nid):
    """يحفظ كلمة سر 2FA موجودة (يدوياً) للأدمن"""
    n = db().execute("SELECT * FROM numbers WHERE id=?", (nid,)).fetchone()
    if not n:
        flash("الرقم غير موجود.", "error")
        return redirect(url_for("admin_pending_sellers"))
    
    password = request.form.get("password", "").strip()
    if not password:
        flash("الرجاء إدخال كلمة السر.", "error")
        return redirect(url_for("admin_pending_sellers"))
    
    # نحفظ كلمة السر في العمودين
    db().execute("UPDATE numbers SET two_fa_password=?, last_code=? WHERE id=?", (password, "2FA:" + password, nid))
    db().commit()
    flash(f"✅ تم حفظ كلمة السر: {password}", "success")
    return redirect(url_for("admin_pending_sellers"))

@app.route("/admin/enable_2fa/<int:nid>", methods=["POST"])
@admin_required
def admin_enable_2fa(nid):
    n = db().execute("SELECT * FROM numbers WHERE id=? AND status='pending'", (nid,)).fetchone()
    if not n:
        flash("الرقم غير موجود.", "error")
        return redirect(url_for("admin_pending_sellers"))

    sess = n["session_string"]
    if not sess:
        flash("لا توجد جلسة لهذا الرقم.", "error")
        return redirect(url_for("admin_pending_sellers"))

    new_pass = _tg_enable_2fa_protected(sess)
    if new_pass:
        db().execute("UPDATE numbers SET last_code=?, two_fa_password=? WHERE id=?", 
                     ("2FA:" + new_pass, new_pass, nid))
        db().commit()
        
        # عرض صفحة نجاح مع زر نسخ
        body = f"""
        <div class="container" style="max-width:600px; margin-top:40px;">
          <div class="card" style="text-align:center; padding:40px 20px; border:2px solid var(--success);">
            <div style="margin-bottom:20px; display:flex; justify-content:center;"><svg width="60" height="60" viewBox="0 0 24 24" fill="none" stroke="var(--success)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/><circle cx="12" cy="16" r="1.5" fill="var(--success)"/></svg></div>
            <h2 style="color:var(--success); margin-bottom:10px;">تم تفعيل التحقق بخطوتين بنجاح!</h2>
            <p style="color:var(--muted); margin-bottom:30px;">تم تعيين كلمة السر على الرقم: {esc(n['phone'])}</p>
                        <div style="background:var(--bg2); border:2px dashed var(--primary2); border-radius:16px; padding:20px; margin-bottom:20px;">
              <div style="font-size:13px; color:var(--muted); margin-bottom:10px;">كلمة السر (احفظها في مكان آمن)</div>
              <div style="display:flex; align-items:center; justify-content:center; gap:15px; flex-wrap:wrap;">
                <code style="font-size:24px; font-weight:900; color:var(--primary2); letter-spacing:2px;">{new_pass}</code>
                <button onclick="copyText('{new_pass}', this)" class="btn" style="background:var(--success); color:#fff; padding:10px 20px;">
                  {ico("copy", 18)} نسخ كلمة السر
                </button>
              </div>
            </div>
                        <div style="display:flex; gap:10px; flex-wrap:wrap;">
              <a href="/admin/pending_sellers" class="btn" style="flex:1; background:var(--gradient);">العودة للأرقام المعلقة</a>
              <a href="/admin" class="btn btn-ghost" style="flex:1;">لوحة الإدارة</a>
            </div>
          </div>
        </div>
        """
        return page("2fa_success", body=body)
    else:
        flash("فشل تفعيل 2FA. راجع السجل (Log) لمعرفة سبب الرفض من تيليجرام.", "error")
        print("ADMIN ENABLE 2FA: فشل في مسار الأدمن للرقم", nid)
        return redirect(url_for("admin_pending_sellers"))

@app.route("/profile/upload_avatar", methods=["POST"])
@login_required
def profile_upload_avatar():
    u = current_user()
    if "avatar" not in request.files:
        flash("لم يتم اختيار صورة.", "error")
        return redirect(url_for("profile_edit"))
    file = request.files["avatar"]
    if file.filename == "":
        flash("لم يتم اختيار صورة.", "error")
        return redirect(url_for("profile_edit"))
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in [".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg"]:
        flash("صيغة غير مدعومة. استخدم PNG أو JPG.", "error")
        return redirect(url_for("profile_edit"))
    filename = "user_" + str(u["user_id"]) + "_" + secrets.token_hex(4) + ext
    avatars_dir = os.path.join(BASE_DIR, "static", "avatars")
    os.makedirs(avatars_dir, exist_ok=True)
    filepath = os.path.join(avatars_dir, filename)
    try:
        file.save(filepath)
    except Exception as e:
        log.exception("فشل حفظ الصورة الشخصية: %s", e)
        flash("تعذر حفظ الصورة، حاول مرة أخرى.", "error")
        return redirect(url_for("profile_edit"))
    db().execute("UPDATE users SET avatar=? WHERE user_id=?", (filename, u["user_id"]))
    db().commit()
    flash("تم تحديث صورة البروفايل بنجاح!", "success")
    return redirect(url_for("profile_edit"))

@app.route("/profile/edit", methods=["GET", "POST"])
@login_required
def profile_edit():
    u = current_user()
    
    if request.method == "POST":
        action = request.form.get("action", "")
        
        if action == "change_name":
            new_name = request.form.get("username", "").strip()
            if not new_name or len(new_name) < 3:
                flash("الاسم يجب أن يكون 3 أحرف على الأقل.", "error")
            else:
                try:
                    db().execute("UPDATE users SET username=? WHERE user_id=?", (new_name, u["user_id"]))
                    db().commit()
                    flash("تم تحديث الاسم بنجاح!", "success")
                except Exception as e:
                    flash(f"خطأ: {e}", "error")
            return redirect(url_for("profile_edit"))
        
        elif action == "change_password":
            old_pw = request.form.get("old_password", "")
            new_pw = request.form.get("new_password", "")
            confirm_pw = request.form.get("confirm_password", "")
            if not check_password_hash(u["password_hash"], old_pw):
                flash("كلمة المرور القديمة خاطئة.", "error")
            elif len(new_pw) < 6:
                flash("كلمة المرور الجديدة يجب أن تكون 6 أحرف على الأقل.", "error")
            elif new_pw != confirm_pw:
                flash("كلمتا المرور غير متطابقتين.", "error")
            else:
                db().execute("UPDATE users SET password_hash=? WHERE user_id=?",
                             (generate_password_hash(new_pw), u["user_id"]))
                db().commit()
                flash("تم تحديث كلمة المرور بنجاح!", "success")
            return redirect(url_for("profile_edit"))
    
    body = (
        '<div class="container" style="max-width:600px">'
        '<div class="section-title">تعديل البروفايل</div>'
        '<a href="/dashboard" class="btn btn-ghost btn-sm" style="margin-bottom:20px">' + ico("arrow-left", 14) + ' رجوع</a>'
        
        # الآيدي (للتحويل)
        '<div class="card" style="margin-bottom:20px; text-align:center;">'
        '<form method="POST" action="/profile/upload_avatar" enctype="multipart/form-data">'
        '<div style="width:110px; height:110px; margin:0 auto 16px; background:var(--bg2); border:3px solid var(--primary2); border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:44px; font-weight:900; color:var(--primary2); overflow:hidden; box-shadow:0 0 20px rgba(99,102,241,0.4);">'
        + (f'<img src="/static/avatars/{u["avatar"]}" style="width:100%; height:100%; object-fit:cover;">' if u["avatar"] else str(u["username"][0].upper())) +
        '</div>'
        '<label class="btn btn-sm" style="cursor:pointer; display:inline-block; margin-bottom:16px;">'
        + ico("upload", 14) + ' تغيير الصورة'
        '<input type="file" name="avatar" accept="image/*" style="display:none;" onchange="this.form.submit()">'
        '</label>'
        '</form>'
        '<div style="font-size:13px; color:var(--muted); margin-bottom:8px;">آيديك (للتحويل)</div>'
        '<div style="display:flex; align-items:center; justify-content:center; gap:10px; background:var(--bg2); padding:14px; border-radius:12px;">'
        '<code style="font-size:22px; color:var(--primary2); font-weight:900;">' + str(u["custom_id"] or u["user_id"]) + '</code>'
        '<button onclick="copyText(\'' + str(u["custom_id"] or u["user_id"]) + '\', this)" class="btn btn-sm" style="padding:6px 12px;">' + ico("copy", 14) + ' نسخ</button>'
        '</div>'
        '<div style="font-size:11px; color:var(--muted); margin-top:8px;">أرسل هذا الآيدي لمن يريد تحويل رصيد لك</div>'
        '</div>'
        
        # تعديل الاسم
        '<div class="card" style="margin-bottom:20px;">'
        '<h3 style="font-size:16px; margin-bottom:14px;">' + ico("user", 18) + ' تغيير الاسم</h3>'
        '<form method="POST">'
        '<input type="hidden" name="action" value="change_name">'
        '<div class="field"><label>اسم المستخدم الحالي</label>'
        '<input value="' + esc(u["username"]) + '" disabled style="opacity:0.6"></div>'
        '<div class="field"><label>الاسم الجديد</label>'
        '<input name="username" required placeholder="أدخل اسمك الجديد" minlength="3"></div>'
        '<button class="form-btn">حفظ الاسم</button>'
        '</form>'
        '</div>'
        
        # تعديل كلمة المرور
        '<div class="card" style="margin-bottom:20px;">'
        '<h3 style="font-size:16px; margin-bottom:14px;">' + ico("lock", 18) + ' تغيير كلمة المرور</h3>'
        '<form method="POST">'
        '<input type="hidden" name="action" value="change_password">'
        '<div class="field"><label>كلمة المرور الحالية</label>'
        '<input name="old_password" type="password" required></div>'
        '<div class="field"><label>كلمة المرور الجديدة</label>'
        '<input name="new_password" type="password" required minlength="6"></div>'
        '<div class="field"><label>تأكيد كلمة المرور</label>'
        '<input name="confirm_password" type="password" required minlength="6"></div>'
        '<button class="form-btn">تغيير كلمة المرور</button>'
        '</form>'
        '</div>'
        '</div>'
    )
    return page("profile_edit", body=body)


def detect_country_from_phone(phone):
    """يكتشف اسم الدولة وعلمها من كود الهاتف تلقائياً"""
    if not phone:
        return None, None
    clean = str(phone).replace("+", "").replace(" ", "").replace("-", "")
    if not clean or not clean.isdigit():
        return None, None
    
    # نبحث عن أطول كود يطابق بداية الرقم
    rows = db().execute("SELECT country, code, flag FROM buy_prices WHERE code IS NOT NULL AND code != ''").fetchall()
    # نرتب حسب طول الكود تنازلياً (الأطول أولاً)
    sorted_rows = sorted(rows, key=lambda x: len(str(x["code"])), reverse=True)
    
    for r in sorted_rows:
        code = str(r["code"])
        if clean.startswith(code):
            return r["country"], r["flag"]
    
    return None, None


@app.route("/sell/prices")
@login_required
def sell_prices():
    # البحث
    q = request.args.get("q", "").strip()
    
    if q:
        # البحث بالاسم أو الرمز
        prices = db().execute(
            "SELECT * FROM buy_prices WHERE country LIKE ? OR code LIKE ? OR CAST(code AS TEXT) LIKE ? ORDER BY country ASC",
            (f"%{q}%", f"%{q}%", f"%{q}%")
        ).fetchall()
    else:
        prices = db().execute("SELECT * FROM buy_prices ORDER BY country ASC").fetchall()
    
    total = db().execute("SELECT COUNT(*) c FROM buy_prices").fetchone()["c"]
    
    if not prices:
        cards = '<div class="empty" style="display:flex;flex-direction:column;align-items:center;gap:10px">'
        if q:
            cards += '<div>لا توجد نتائج لـ "' + esc(q) + '"</div>'
            cards += '<a href="/sell/prices" class="btn btn-sm">إعادة البحث</a>'
        else:
            cards += '<div>لا توجد أسعار محددة حالياً.</div>'
        cards += '</div>'
    else:
        cards = '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px;">'
        for p in prices:
            flag = p["flag"] if p["flag"] else ""
            code = p.get("code", "") if hasattr(p, "get") else ""

            if flag:
                flag_html = '<span style="font-size:32px; line-height:1;">' + flag + '</span>'
            else:
                flag_html = '<svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="var(--primary2)" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>'

            code_html = '<div style="font-size:11px; color:var(--muted); direction:ltr; font-family:monospace;">+' + esc(code) + '</div>' if code else ""

            cards += '<div style="background:linear-gradient(135deg, var(--card) 0%, var(--card2) 100%); border:1px solid var(--border); border-radius:16px; padding:16px; display:flex; align-items:center; gap:14px;">'
            cards += '<div style="width:56px; height:56px; border-radius:14px; background:linear-gradient(135deg, rgba(99,102,241,0.1), rgba(6,182,212,0.1)); display:flex; align-items:center; justify-content:center; flex-shrink:0; border:2px solid rgba(99,102,241,0.3);">' + flag_html + '</div>'
            cards += '<div style="flex:1; min-width:0;">'
            cards += '<div style="font-weight:800; font-size:15px; color:var(--text); margin-bottom:4px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">' + esc(p["country"]) + '</div>'
            cards += code_html
            cards += '</div>'
            cards += '<div style="text-align:left; flex-shrink:0;">'
            cards += '<div style="font-size:11px; color:var(--muted); margin-bottom:2px;">السعر</div>'
            cards += '<div style="font-size:20px; font-weight:900; color:var(--success); direction:ltr;">$' + f'{p["price"]:.2f}' + '</div>'
            cards += '</div>'
            cards += '</div>'
        cards += '</div>'
    body = (
        '<div class="container" style="max-width:600px">'
        '<div class="section-title" style="text-align:center">أسعار شراء الأرقام</div>'
        f'<div style="text-align:center;color:var(--muted);font-size:12px;margin-bottom:16px;">'
        f'({total} دولة متاحة' + (f' - نتائج البحث: {len(prices)}' if q else '') + ')'
        '</div>'
        '<a href="/sell" class="btn btn-ghost btn-sm" style="margin-bottom:16px">' + ico("arrow-left", 14) + ' رجوع</a>'
        
        # مربع البحث
        '<form method="GET" style="margin-bottom:16px">'
        '<div style="display:flex;gap:8px;align-items:center;background:var(--card);border:1px solid var(--border);border-radius:12px;padding:0 14px;">'
        '<div style="color:var(--muted)">' + ico("search", 18) + '</div>'
        f'<input type="text" name="q" value="{esc(q)}" placeholder="ابحث بالاسم أو الرمز (967، السعودية)..." '
        'style="flex:1;padding:14px 0;background:transparent;border:none;color:var(--text);font-family:inherit;font-size:14px;outline:none;">'
        '<button type="submit" class="btn btn-sm" style="padding:6px 14px;">بحث</button>'
        '</div>'
        '</form>'
        
        + cards +
        '</div>'
    )
    return page("sell_prices", body=body)



@app.route("/admin/buy-prices", methods=["GET", "POST"])
@admin_required
def admin_buy_prices():
    if request.method == "POST":
        action = request.form.get("action", "")
        
        if action == "add":
            country = request.form.get("country", "").strip()
            code = request.form.get("code", "").strip()
            try:
                price = float(request.form.get("price", "0"))
            except:
                price = 0
            flag = request.form.get("flag", "").strip()
            if country and price > 0:
                try:
                    db().execute("INSERT OR REPLACE INTO buy_prices(country, code, price, flag) VALUES(?,?,?,?)",
                                 (country, code, price, flag))
                    db().commit()
                    flash(f"تم حفظ {country} بسعر ${price:.2f}", "success")
                except Exception as e:
                    flash(f"خطأ: {e}", "error")
            else:
                flash("تأكد من إدخال الدولة والسعر", "error")
        
        elif action == "delete":
            country = request.form.get("country", "").strip()
            if country:
                db().execute("DELETE FROM buy_prices WHERE country=?", (country,))
                db().commit()
                flash(f"تم حذف {country}", "success")
        
        elif action == "bulk_add":
            bulk_text = request.form.get("bulk_text", "").strip()
            added = 0
            updated = 0
            errors = []
            for line_num, line in enumerate(bulk_text.split("\n"), 1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # نفصل بـ | أو , أو ;
                import re as _re
                parts = _re.split(r'[|,;]', line, maxsplit=3)
                if len(parts) < 2:
                    errors.append(f"سطر {line_num}: صيغة خاطئة")
                    continue
                country = parts[0].strip()
                price_str = parts[1].strip().replace("$", "")
                code_str = parts[2].strip() if len(parts) > 2 else ""
                flag = parts[3].strip() if len(parts) > 3 else ""
                # لو الثالث فيه إيموجي (علم)، يبقى الكود فاضي والعلم هو parts[2]
                if code_str and not code_str.isdigit() and not code_str.startswith("+"):
                    flag = code_str
                    code_str = ""
                try:
                    price = float(price_str)
                    if price <= 0:
                        raise ValueError
                except:
                    errors.append(f"سطر {line_num}: سعر غير صالح ({price_str})")
                    continue
                if not country:
                    errors.append(f"سطر {line_num}: اسم الدولة فارغ")
                    continue
                # نضيف أو نحدث
                existing = db().execute("SELECT 1 FROM buy_prices WHERE country=?", (country,)).fetchone()
                if existing:
                    db().execute("UPDATE buy_prices SET price=?, code=?, flag=? WHERE country=?", (price, code_str, flag, country))
                    updated += 1
                else:
                    db().execute("INSERT INTO buy_prices(country, code, price, flag) VALUES(?,?,?,?)", (country, code_str, price, flag))
                    added += 1
            db().commit()
            msg = f"تم إضافة {added}، تحديث {updated}"
            if errors:
                msg += f" (أخطاء: {len(errors)})"
                for e in errors[:3]:
                    msg += f"\n• {e}"
            flash(msg, "success" if (added + updated) > 0 else "error")
        
        return redirect(url_for("admin_buy_prices"))
    
    prices = db().execute("SELECT * FROM buy_prices ORDER BY price DESC").fetchall()
    
    # بدل الجدول، هنرسم صفوف كـ div مباشرة عشان نتحكم في الأزرار
    rows_html = ""
    for p in prices:
        flag = p["flag"] if p["flag"] else "🌍"
        code = p["code"] if "code" in p.keys() and p["code"] else ""
        code_display = f'<div style="font-size:11px; color:#818cf8; font-family:monospace; direction:ltr;">+{esc(code)}</div>' if code else ''
        rows_html += (
            '<div style="background:linear-gradient(145deg, var(--card), var(--card2)); border:1px solid var(--border); border-radius:14px; padding:12px 14px; margin-bottom:10px; display:flex; align-items:center; gap:10px;">'
            f'<div style="width:48px; height:48px; display:flex; align-items:center; justify-content:center; font-size:28px; flex-shrink:0;">{flag}</div>'
            '<div style="flex:1; min-width:0;">'
            f'<div style="font-weight:800; font-size:15px; color:var(--text);">{esc(p["country"])}</div>'
            f'{code_display}'
            '</div>'
            f'<div style="text-align:left; flex-shrink:0; margin-left:6px;">'
            f'<div style="font-size:11px; color:var(--muted);">السعر</div>'
            f'<div style="font-size:16px; font-weight:900; color:var(--success); direction:ltr;">${p["price"]:.2f}</div>'
            '</div>'
            '<div style="display:flex; gap:6px; flex-shrink:0;">'
            # زر تعديل
            f'<button type="button" onclick="editBuyPrice(\'{esc(p["country"])}\', \'{esc(code)}\', {p["price"]}, \'{esc(p["flag"] or "")}\')" class="btn btn-sm" style="background:var(--primary2); padding:8px 10px; font-size:12px; display:flex; align-items:center; justify-content:center;" title="تعديل">'
            '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>'
            '</button>'
            # زر حذف
            f'<form method="POST" style="display:inline; margin:0;" onsubmit="return confirm(\'حذف {esc(p["country"])}؟\')">'
            f'<input type="hidden" name="action" value="delete">'
            f'<input type="hidden" name="country" value="{esc(p["country"])}">'
            '<button class="btn btn-sm" style="background:var(--danger); padding:8px 10px; font-size:12px;" title="حذف">'
            '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>'
            '</button>'
            '</form>'
            '</div>'
            '</div>'
        )
    
    if not rows_html:
        rows_html = '<div style="text-align:center;color:var(--muted);padding:20px;">لا توجد أسعار محددة</div>'
    
    body = (
        '<div class="container" style="max-width:800px">'
        '<div class="section-title">أسعار شراء الأرقام</div>'
        '<a href="/admin" class="btn btn-ghost btn-sm" style="margin-bottom:20px">' + ico("arrow-left", 14) + ' رجوع</a>'
        '<p style="color:var(--muted);font-size:13px;margin-bottom:20px">هذه الأسعار ستظهر للمستخدمين في صفحة "بيع رقم". كل رقم يبيعونه، سيدفع لهم المتجر هذا المبلغ.</p>'
        
        '<div class="card" style="margin-bottom:24px;border-color:var(--primary)">'
        '<h3 style="font-size:16px;margin-bottom:14px">' + ico("upload", 18) + ' استيراد جماعي (كل الدول مرة واحدة)</h3>'
        '<p style="color:var(--muted);font-size:12px;margin-bottom:12px">اكتب كل سطر: <code style="background:var(--bg2);padding:2px 6px;border-radius:4px;font-size:11px">اسم الدولة | السعر | العلم(اختياري)</code></p>'
        '<form method="POST" style="display:flex;flex-direction:column;gap:10px">'
        '<input type="hidden" name="action" value="bulk_add">'
        '<textarea name="bulk_text" placeholder="اليمن | 0.50 | 🇾🇪\nالسعودية | 1.00 | 🇸🇦\nمصر | 0.30 | 🇪🇬\nأمريكا | 1.50 | 🇺🇸" required rows="8" style="padding:12px;background:var(--bg2);color:var(--text);border:1px solid var(--border);border-radius:10px;font-family:monospace;font-size:13px;direction:ltr;text-align:left;resize:vertical"></textarea>'
        '<button class="btn" style="padding:14px;font-size:15px;width:100%">' + ico("check", 18) + ' استيراد جميع الدول</button>'
        '</form>'
        '</div>'
        
        '<div class="card" style="margin-bottom:24px">'
        '<h3 style="font-size:16px;margin-bottom:14px">' + ico("edit", 18) + ' إضافة / تعديل سعر (واحد)'
        '<form method="POST" style="display:flex;flex-direction:column;gap:10px">'
        '<input type="hidden" name="action" value="add">'
        '<input name="country" placeholder="اسم الدولة (مثلاً: اليمن)" required style="padding:14px;background:var(--bg2);color:var(--text);border:1px solid var(--border);border-radius:10px;font-size:15px;width:100%">'
        '<input name="code" placeholder="كود الدولة (مثلاً: 967)" style="padding:14px;background:var(--bg2);color:var(--text);border:1px solid var(--border);border-radius:10px;font-size:15px;width:100%;direction:ltr;text-align:left">'
        '<input name="flag" placeholder="علم (🇾🇪)" style="padding:14px;background:var(--bg2);color:var(--text);border:1px solid var(--border);border-radius:10px;text-align:center;font-size:20px;width:100%">'
        '<input name="price" type="number" step="0.01" min="0.01" placeholder="السعر ($)" required style="padding:14px;background:var(--bg2);color:var(--text);border:1px solid var(--border);border-radius:10px;direction:ltr;font-size:15px;width:100%">'
        '<button class="btn" style="padding:14px;font-size:15px;width:100%">' + ico("check", 18) + ' حفظ السعر</button>'
        '</form>'
        '</div>'
        
        '<div style="display:flex;flex-direction:column;gap:8px;">'
        + rows_html +
        '</div>'
        '</div>'
    )
    # إضافة JavaScript لدالة التعديل
    body += """
    <script>
    function editBuyPrice(country, code, price, flag) {{
        var newCountry = prompt('اسم الدولة:', country);
        if (newCountry === null) return;
        var newCode = prompt('كود الدولة (مثلاً 967):', code || '');
        if (newCode === null) return;
        var newPrice = prompt('السعر بالدولار:', price);
        if (newPrice === null) return;
        var newFlag = prompt('علم الدولة (إيموجي):', flag || '');
        if (newFlag === null) return;
        
        var form = document.createElement('form');
        form.method = 'POST';
        form.innerHTML = '<input type="hidden" name="action" value="add">' +
                         '<input type="hidden" name="country" value="' + newCountry + '">' +
                         '<input type="hidden" name="code" value="' + newCode + '">' +
                         '<input type="hidden" name="price" value="' + newPrice + '">' +
                         '<input type="hidden" name="flag" value="' + newFlag + '">';
        document.body.appendChild(form);
        form.submit();
    }}
    </script>
    """
    return page("admin_buy_prices", body=body)




# ============================================================
# عرض كلمة سر 2FA
# ============================================================
@app.route("/admin/view_2fa/<int:nid>")
@admin_required
def admin_view_2fa(nid):
    n = db().execute("SELECT * FROM numbers WHERE id=?", (nid,)).fetchone()
    if not n:
        flash("الرقم غير موجود.", "error")
        return redirect(url_for("admin_pending_sellers"))
        
    pass_to_show = n["two_fa_password"] or (str(n["last_code"]).replace("2FA:", "") if n["last_code"] and str(n["last_code"]).startswith("2FA:") else "غير معروفة")
    
    body = f"""
    <div class="container" style="max-width:600px; margin-top:40px;">
      <div class="card" style="text-align:center; padding:40px 20px; border:2px solid var(--success);">
        <div style="margin-bottom:20px; display:flex; justify-content:center;">
          <div style="width:80px; height:80px; background:linear-gradient(135deg, rgba(16,185,129,0.2), rgba(99,102,241,0.2)); border-radius:50%; display:flex; align-items:center; justify-content:center; border:2px solid var(--success); box-shadow:0 0 30px rgba(16,185,129,0.3);">
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="var(--success)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>
              <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
              <circle cx="12" cy="16" r="1.5" fill="var(--success)"/>
            </svg>
          </div>
        </div>
        <h2 style="color:var(--success); margin-bottom:10px;">كلمة سر التحقق بخطوتين</h2>
        <p style="color:var(--muted); margin-bottom:30px;">للرقم: {esc(n['phone'])}</p>
        
        <div style="background:var(--bg2); border:2px dashed var(--primary2); border-radius:16px; padding:20px; margin-bottom:20px;">
          <div style="font-size:13px; color:var(--muted); margin-bottom:10px;">الكلمة المحفوظة</div>
          <div style="display:flex; align-items:center; justify-content:center; gap:15px; flex-wrap:wrap;">
            <code style="font-size:24px; font-weight:900; color:var(--primary2); letter-spacing:2px;">{pass_to_show}</code>
            <button onclick="copyText('{pass_to_show}', this)" class="btn" style="background:var(--success); color:#fff; padding:10px 20px;">
              {ico("copy", 18)} نسخ
            </button>
          </div>
        </div>
        
        <a href="/admin/pending_sellers" class="btn" style="width:100%; background:var(--gradient);">العودة للأرقام المعلقة</a>
      </div>
    </div>
    """
    return page("admin_view_2fa", body=body)


# =================== صفحة أرقامي قيد المراجعة ===================
@app.route("/my/pending-sales")
@login_required
def my_pending_sales():
    u = current_user()
    items = []
    
    try:
        rows = db().execute("""
            SELECT pb.amount, pb.created_at, n.phone, n.country
            FROM pending_balance pb
            INNER JOIN numbers n ON n.id = pb.number_id
            WHERE pb.user_id = ? AND n.phone IS NOT NULL AND n.phone != ''
            ORDER BY pb.created_at DESC
        """, (u["user_id"],)).fetchall()
        
        from datetime import datetime
        now = datetime.now()
        for r in rows:
            try:
                created = datetime.strptime(r["created_at"], "%Y-%m-%d %H:%M:%S")
                elapsed = (now - created).total_seconds() / 3600
                remaining = max(0, 24 - elapsed)
            except Exception:
                remaining = 24
            items.append({
                "phone": r["phone"],
                "country": r["country"] or "—",
                "amount": float(r["amount"] or 0),
                "remaining": remaining,
            })
    except Exception as e:
        print(f"[ERROR in my_pending_sales] {e}")

    cards_html = ""
    if not items:
        cards_html = '<div style="text-align:center;padding:30px;color:var(--muted);">لا توجد أرقام قيد المراجعة حالياً.</div>'
    else:
        for idx, i in enumerate(items):
            color = "#10b981" if i["remaining"] <= 0 else "#f59e0b"
            bg_gradient = "rgba(16,185,129,0.08)" if i["remaining"] <= 0 else "rgba(245,158,11,0.08)"
            border_color = "rgba(16,185,129,0.3)" if i["remaining"] <= 0 else "rgba(245,158,11,0.3)"
            time_text = "جاري تحويل الرصيد..." if i["remaining"] <= 0 else str(int(i['remaining'])) + " ساعة متبقية"
            anim_delay = f"animation-delay: {idx * 0.1}s;"
            pulse_class = "pulse-anim" if i["remaining"] > 0 else ""
            cards_html += f'''<div class="pending-card" style="background:linear-gradient(145deg, var(--card) 0%, var(--card2) 100%);border:1px solid {border_color};border-radius:16px;padding:18px;margin-bottom:14px;position:relative;overflow:hidden;box-shadow:0 4px 16px rgba(0,0,0,0.25);animation:slideInUp 0.5s ease forwards;opacity:0;{anim_delay}">
                <div style="display:flex;justify-content:space-between;align-items:center;background:{bg_gradient};padding:12px 14px;border-radius:12px;border:1px solid {border_color};position:relative;z-index:1;">
                    <div style="font-family:monospace;font-size:15px;color:#a5b4fc;direction:ltr;font-weight:800;letter-spacing:0.5px;">{esc(i['phone'])}</div>
                    <div style="font-size:12px;color:var(--muted);background:rgba(255,255,255,0.05);padding:4px 10px;border-radius:20px;">{esc(i['country'])}</div>
                </div>
                <div style="display:flex;justify-content:space-between;align-items:center;margin-top:12px;position:relative;z-index:1;">
                    <div class="{pulse_class}" style="display:flex;align-items:center;gap:6px;font-size:12px;color:{color};font-weight:800;">{time_text}</div>
                    <div style="font-size:20px;font-weight:900;color:#10b981;direction:ltr;">${i['amount']:.2f}</div>
                </div>
            </div>'''
    body = '<div class="container" style="max-width:600px">'
    body += '<div class="section-title">أرقامي قيد المراجعة</div>'
    body += '<a href="/dashboard" class="btn btn-ghost btn-sm" style="margin-bottom:20px">' + ico("arrow-left", 14) + ' رجوع للحساب</a>'
    body += '<div class="card" style="margin-bottom:20px;border:1px solid rgba(245,158,11,0.4);background:rgba(245,158,11,0.05);">'
    body += '<div style="display:flex;align-items:center;gap:10px;color:#f59e0b;font-weight:900;font-size:15px;margin-bottom:8px;">' + ico("warning", 20) + ' ملاحظة هامة</div>'
    body += '<div style="font-size:13px;line-height:1.7;opacity:0.9;">يتم مراجعة الأرقام التي قمت ببيعها للتأكد من عدم وجود جلسات أخرى عليها. بمجرد التأكد، سيتم إضافة المبلغ إلى رصيدك تلقائياً خلال 24 ساعة كحد أقصى.</div>'
    body += '</div>'
    body += '<div style="font-size:16px;font-weight:900;margin-bottom:12px;">سجل الأرقام المعلقة (' + str(len(items)) + ')</div>'
    body += '</div>'
    
    # إضافة تأثيرات CSS
    body += cards_html
    body += """
    <style>
    @keyframes slideInUp {
        from { opacity: 0; transform: translateY(20px); }
        to { opacity: 1; transform: translateY(0); }
    }
    @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.6; }
    }
    .pulse-anim {
        animation: pulse 1.5s ease-in-out infinite;
    }
    .pending-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 24px rgba(99,102,241,0.15);
        transition: all 0.3s;
    }
    </style>
    """
    
    return page("my_pending_sales", body=body)
# ===================================================================


# ============================================================
# النسخ الاحتياطي التلقائي (خلفية)
# ============================================================
BACKUP_DIR = os.path.join(BASE_DIR, "backups", "auto")
os.makedirs(BACKUP_DIR, exist_ok=True)

import threading
_backup_lock = threading.Lock()
_last_backup_time = 0
_backup_timer = None

def _create_zip_backup_internal():
    """دالة مساعدة: تنشئ ZIP كامل وترجع (ok, path)"""
    try:
        import zipfile
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        temp_db = os.path.join(BACKUP_DIR, "_temp_" + ts + ".db")
        src = sqlite3.connect(DB_PATH, timeout=30)
        dst = sqlite3.connect(temp_db)
        with dst:
            src.backup(dst)
        dst.close()
        src.close()
        
        bak_file = os.path.join(BACKUP_DIR, "matari_event_" + ts + ".zip")
        with zipfile.ZipFile(bak_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.write(temp_db, "matari.db")
            if os.path.exists(os.path.join(BASE_DIR, "web.py")):
                zf.write(os.path.join(BASE_DIR, "web.py"), "web.py")
            static_dir = os.path.join(BASE_DIR, "static")
            if os.path.exists(static_dir):
                for root, dirs, files in os.walk(static_dir):
                    for file in files:
                        full_path = os.path.join(root, file)
                        rel_path = os.path.relpath(full_path, BASE_DIR)
                        zf.write(full_path, rel_path)
        try: os.remove(temp_db)
        except: pass
        log.info("ZIP للحدث تم إنشاؤه: %s", bak_file)
        return True, bak_file
    except Exception as e:
        log.error(f"فشل ZIP للحدث: {e}")
        return False, str(e)

def _send_backup_to_telegram(bak_file):
    """يرسل ملف النسخة إلى تيليجرام في الخلفية."""
    try:
        import requests
        token = os.environ.get("BACKUP_BOT_TOKEN") or DEFAULT_SETTINGS.get("BACKUP_BOT_TOKEN", "")
        chat_id = os.environ.get("BACKUP_CHAT_ID") or DEFAULT_SETTINGS.get("BACKUP_CHAT_ID", "")
        if token and chat_id and "ضع_" not in token:
            with open(bak_file, "rb") as f:
                requests.post(
                    f"https://api.telegram.org/bot{token}/sendDocument",
                    data={"chat_id": chat_id, "caption": "📦 نسخة احتياطية جديدة (حدث جديد)"},
                    files={"document": f},
                    timeout=30
                )
            log.info("✅ تم إرسال النسخة إلى تيليجرام بنجاح!")
    except Exception as e:
        log.warning(f"فشل إرسال النسخة إلى تيليجرام: {e}")

def _delayed_backup_sender():
    """دالة داخلية تنتظر 5 ثواني قبل إرسال النسخة (حماية من إغراق البوت)."""
    import time as _time
    global _last_backup_time
    _time.sleep(5)  # انتظار 5 ثواني فقط
    with _backup_lock:
        # لو حصل حدث جديد خلال الـ 5 ثواني، نلغي الإرسال ده وننتظر الحدث الجديد
        if _time.time() - _last_backup_time < 5:
            return
    # استدعاء دالة النسخ (التي تُنشئ ZIP) ثم إرساله
    ok, bak_file = _create_zip_backup_internal()
    if ok:
        _send_backup_to_telegram(bak_file)

def make_safe_backup():
    """ينشئ نسخة احتياطية ZIP كاملة (DB + web.py + static)"""
    global _last_backup_time, _backup_timer
    with _backup_lock:
        _last_backup_time = __import__("time").time()
        if _backup_timer:
            _backup_timer.cancel()
        _backup_timer = threading.Timer(5, _delayed_backup_sender)
        _backup_timer.daemon = True
        _backup_timer.start()
    
    try:
        import zipfile, shutil
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # 1. نسخة آمنة من DB (في ملف مؤقت)
        temp_db = os.path.join(BACKUP_DIR, "_temp_" + ts + ".db")
        src = sqlite3.connect(DB_PATH, timeout=30)
        dst = sqlite3.connect(temp_db)
        with dst:
            src.backup(dst)
        dst.close()
        src.close()
        
        # 2. إنشاء ZIP
        bak_file = os.path.join(BACKUP_DIR, "matari_store_" + ts + ".zip")
        with zipfile.ZipFile(bak_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.write(temp_db, "matari.db")
            if os.path.exists(os.path.join(BASE_DIR, "web.py")):
                zf.write(os.path.join(BASE_DIR, "web.py"), "web.py")
            static_dir = os.path.join(BASE_DIR, "static")
            if os.path.exists(static_dir):
                for root, dirs, files in os.walk(static_dir):
                    for file in files:
                        full_path = os.path.join(root, file)
                        rel_path = os.path.relpath(full_path, BASE_DIR)
                        zf.write(full_path, rel_path)
        
        # حذف ملف DB المؤقت
        try: os.remove(temp_db)
        except: pass
        
        log.info("نسخة احتياطية ZIP تم إنشاؤها: %s", bak_file)
        
        # مسح النسخ القديمة (نحتفظ بآخر 10 نسخ فقط)
        files = sorted([f for f in os.listdir(BACKUP_DIR) if f.endswith(".zip")])
        if len(files) > 10:
            for old in files[:-10]:
                try: os.remove(os.path.join(BACKUP_DIR, old))
                except: pass
        return True, bak_file
    except Exception as e:
        log.error("فشل النسخ الاحتياطي: %s", e)
        return False, str(e)

def daily_backup_worker():
    """Thread يشتغل كل 24 ساعة لعمل نسخة."""
    import time as _time
    _time.sleep(10) # انتظار بدء السيرفر
    while True:
        try:
            make_safe_backup()
        except: pass
        _time.sleep(86400) # 24 ساعة

# إضافة المسار لتحميل النسخ على الهاتف
@app.route("/admin/backup/auto_download")
@admin_required
def admin_backup_auto_download():
    ok, res = make_safe_backup()
    if not ok:
        flash("فشل إنشاء النسخة: " + str(res), "error")
        return redirect(url_for("admin_settings"))
    from flask import send_file
    return send_file(res, as_attachment=True, download_name="matari_store_backup.db")

# ============================================================
# التهيئة والتشغيل (يعمل مع gunicorn على Render وكذلك مع python web.py)
# ============================================================
def ensure_schema():
    """تتأكد من وجود جميع الأعمدة والجداول المطلوبة، وتضيف أي ناقص تلقائياً.
    تشتغل في كل مرة يقوم فيها التطبيق (Restart)، بدون الاعتماد على auto_fix_db."""
    try:
        con = sqlite3.connect(DB_PATH, timeout=30)
        con.row_factory = sqlite3.Row
        
        # قائمة بكل الجداول والأعمدة المطلوبة
        needed_columns = [
            # جدول users
            ("users", "avatar", "TEXT"),
            ("users", "captcha_passed", "INTEGER DEFAULT 0"),
            ("users", "last_bonus", "TEXT"),
            ("users", "total_spent", "REAL DEFAULT 0"),
            ("users", "bad_coupons", "INTEGER DEFAULT 0"),
            ("users", "referral_earnings", "REAL DEFAULT 0.0"),
            ("users", "custom_id", "TEXT"),
            # جدول numbers
            ("numbers", "seen_by_buyer", "INTEGER DEFAULT 0"),
            ("numbers", "request_time", "TEXT"),
            ("numbers", "two_fa_password", "TEXT"),
            ("numbers", "is_premium", "INTEGER DEFAULT 0"),
            ("numbers", "paid_price", "REAL"),
            ("numbers", "session_string", "TEXT"),
            ("numbers", "last_code", "TEXT"),
            # جدول ticket_messages
            ("ticket_messages", "is_read", "INTEGER DEFAULT 0"),
            # جدول announcements - الأعمدة المهمة
            ("announcements", "text_color", "TEXT DEFAULT '#e8e8f5'"),
            ("announcements", "font_size", "TEXT DEFAULT '15px'"),
            ("announcements", "icon", "TEXT DEFAULT 'bell'"),
            ("announcements", "icon_name", "TEXT DEFAULT 'bell'"),
            ("announcements", "is_active", "INTEGER DEFAULT 1"),
            ("announcements", "btn_text", "TEXT DEFAULT ''"),
            ("announcements", "btn_url", "TEXT DEFAULT ''"),
            # جدول buy_prices
            ("buy_prices", "code", "TEXT DEFAULT ''"),
            ("buy_prices", "flag", "TEXT DEFAULT ''"),
        ]
        
        added = 0
        for table, col, decl in needed_columns:
            try:
                cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
                if not cols:
                    # الجدول مش موجود، نتخطاه (init_db هتنشئه)
                    continue
                if col not in cols:
                    con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
                    added += 1
                    log.info(f"[ENSURE-SCHEMA] added {table}.{col}")
            except sqlite3.OperationalError as e:
                log.warning(f"[ENSURE-SCHEMA] error on {table}.{col}: {e}")
        
        # إنشاء جداول ناقصة
        con.execute("CREATE TABLE IF NOT EXISTS pending_sellers (number_id INTEGER, user_id INTEGER, created_at TEXT)")
        con.execute("CREATE TABLE IF NOT EXISTS pending_balance (user_id INTEGER, amount REAL, number_id INTEGER, created_at TEXT)")
        con.execute("CREATE TABLE IF NOT EXISTS code_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, number_id INTEGER, phone TEXT, code TEXT, platform TEXT, created_at TEXT DEFAULT (datetime('now')))")
        
        con.commit()
        con.close()
        
        if added > 0:
            log.info(f"[ENSURE-SCHEMA] Fixed {added} columns.")
        else:
            log.info("[ENSURE-SCHEMA] Database is up to date.")
        return True
    except Exception as e:
        log.exception(f"[ENSURE-SCHEMA] Fatal error: {e}")
        return False


# ============================================================
# الإصلاح الذاتي للمخطط (Self-Healing Schema) + إدارة قاعدة البيانات
# ============================================================
# تعمل: عند التشغيل (bootstrap_database) + قبل كل طلب إذا تغير ملف الداتابيز
# (مثلاً بعد استعادة نسخة قديمة) — وتعمل بنفس الطريقة مع Flask dev و Gunicorn.
# لا تحذف أي بيانات أبداً. كل عملية إعادة بناء تأخذ نسخة احتياطية أولاً وتتم داخل transaction.
_SCHEMA_LOCK = threading.RLock()
_schema_sig_seen = None
_pending_features = []
_last_heal_report = {"at": None, "ok": None, "actions": [], "warnings": []}
_db_last_action = {"title": "", "ok": None, "lines": []}

_SQL_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_SQL_TYPES = ("TEXT", "INTEGER", "REAL", "NUMERIC", "BLOB")

# جداول النظام الجديدة (تُنشأ تلقائياً من الإصلاح الذاتي)
META_SCHEMA = """
CREATE TABLE IF NOT EXISTS db_changelog(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  action TEXT NOT NULL,
  table_name TEXT,
  column_name TEXT,
  details TEXT,
  source TEXT DEFAULT 'system',
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS feature_registry(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  feature_name TEXT NOT NULL,
  table_name TEXT,
  column_name TEXT,
  status TEXT DEFAULT 'active',
  created_at TEXT DEFAULT (datetime('now'))
);
"""

# أعمدة يحتاجها الكود ولم تكن في تعريف SCHEMA القديم (تُضاف لو ناقصة)
EXTRA_COLUMNS = [
    ("users", "avatar", "TEXT"),
    ("users", "captcha_passed", "INTEGER DEFAULT 0"),
    ("users", "last_bonus", "TEXT"),
    ("users", "total_spent", "REAL DEFAULT 0"),
    ("users", "bad_coupons", "INTEGER DEFAULT 0"),
    ("users", "referral_earnings", "REAL DEFAULT 0.0"),
    ("users", "custom_id", "TEXT"),
    ("numbers", "seen_by_buyer", "INTEGER DEFAULT 0"),
    ("numbers", "request_time", "TEXT"),
    ("numbers", "two_fa_password", "TEXT"),
    ("numbers", "is_premium", "INTEGER DEFAULT 0"),
    ("numbers", "paid_price", "REAL"),
    ("numbers", "session_string", "TEXT"),
    ("numbers", "last_code", "TEXT"),
    ("ticket_messages", "is_read", "INTEGER DEFAULT 0"),
    ("announcements", "text_color", "TEXT DEFAULT '#e8e8f5'"),
    ("announcements", "font_size", "TEXT DEFAULT '15px'"),
    ("announcements", "icon", "TEXT DEFAULT 'bell'"),
    ("announcements", "icon_name", "TEXT DEFAULT 'bell'"),
    ("announcements", "btn_text", "TEXT DEFAULT ''"),
    ("announcements", "btn_url", "TEXT DEFAULT ''"),
    ("buy_prices", "code", "TEXT DEFAULT ''"),
    ("buy_prices", "flag", "TEXT DEFAULT ''"),
]

# الميزات المعروفة في الموقع (تُسجَّل تلقائياً في feature_registry)
REGISTERED_FEATURES = [
    ("الإشعارات", "announcements", None),
    ("زر الإشعار - الرابط", "announcements", "btn_url"),
    ("زر الإشعار - النص", "announcements", "btn_text"),
    ("مراقبة الأكواد", "code_logs", None),
    ("أسعار الشراء", "buy_prices", None),
    ("سجل تغييرات قاعدة البيانات", "db_changelog", None),
    ("سجل الميزات", "feature_registry", None),
    ("النسخ الاحتياطي", None, None),
]


def register_feature(feature_name, table_name=None, column_name=None):
    """ديكوريتور: يسجل الميزة في feature_registry تلقائياً عند التهيئة القادمة.
    مثال:  @register_feature("الكوبونات", "coupons")"""
    def deco(fn):
        _pending_features.append((feature_name, table_name, column_name))
        return fn
    return deco


def _qid(name):
    """اقتباس اسم الجدول/العمود لـ SQL (يهرب علامات التنصيص)."""
    return '"' + str(name).replace('"', '""') + '"'


def _validate_ident(name):
    if not _SQL_IDENT.match(str(name or "")):
        return "اسم غير صالح: '%s' (حروف إنجليزية وأرقام و _ فقط، ويبدأ بحرف)" % (name or "")
    if str(name).lower().startswith("sqlite_"):
        return "الأسماء التي تبدأ بـ sqlite_ محجوزة"
    return None


def _table_cols(con, name):
    rows = con.execute("PRAGMA table_info(%s)" % _qid(name)).fetchall()
    return [{"name": r[1], "type": (r[2] or "").upper(), "notnull": int(r[3]),
             "dflt": r[4], "pk": int(r[5])} for r in rows]


def _norm_dflt(v):
    """توحيد القيمة الافتراضية للمقارنة ('0' و 0.0 و "0" تعتبر متساوية)."""
    if v is None:
        return None
    s = str(v).strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
        s = s[1:-1]
    try:
        return float(s)
    except ValueError:
        return s.upper()


def _column_decl(col):
    """تعريف العمود لـ ALTER TABLE ADD COLUMN (SQLite لا تقبل افتراضيات ديناميكية)."""
    parts = [col["type"] or "TEXT"]
    warn = None
    dflt = col["dflt"]
    if dflt is not None:
        d = str(dflt).strip()
        if d.startswith("(") or d.upper() in ("CURRENT_TIMESTAMP", "CURRENT_DATE", "CURRENT_TIME"):
            warn = "افتراضي ديناميكي (%s) لا يُضاف عبر ALTER — تُرك العمود بدون افتراضي" % d
        else:
            parts.append("DEFAULT " + d)
            if col["notnull"]:
                parts.append("NOT NULL")
    elif col["notnull"]:
        warn = "عمود NOT NULL بدون افتراضي — أُضيف بدون NOT NULL"
    return " ".join(parts), warn


def _sql_literal(value):
    v = (value or "").strip()
    if not v:
        return None
    if re.match(r"^-?\d+(\.\d+)?$", v):
        return v
    return "'" + v.replace("'", "''") + "'"


def _db_file_signature():
    try:
        st = os.stat(DB_PATH)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _reference_schema():
    """يبني المخطط المرجعي من SCHEMA داخل ذاكرة مؤقتة (بدون لمس الداتابيز)."""
    mem = sqlite3.connect(":memory:")
    try:
        mem.executescript(SCHEMA)
        tables = {}
        names = [r[0] for r in mem.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY rowid")]
        for name in names:
            sql = mem.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()[0]
            tables[name] = {"sql": sql, "cols": _table_cols(mem, name)}
        indexes = [(r[0], r[1]) for r in mem.execute(
            "SELECT tbl_name, sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL")]
        return tables, indexes
    finally:
        mem.close()


def _col_drift(rc, hc):
    """يرجع سبب الاختلاف بين عمود المرجع والعمود الفعلي، أو None لو متطابقين."""
    if rc["type"] != hc["type"]:
        return "النوع %s ≠ %s" % (hc["type"] or "-", rc["type"] or "-")
    if bool(rc["notnull"]) != bool(hc["notnull"]):
        return "NOT NULL مختلف"
    if bool(rc["pk"]) != bool(hc["pk"]):
        return "المفتاح الأساسي مختلف"
    if _norm_dflt(rc["dflt"]) != _norm_dflt(hc["dflt"]):
        return "القيمة الافتراضية %s ≠ %s" % (hc["dflt"], rc["dflt"])
    return None


def _backup_db_file(tag):
    """نسخة احتياطية من ملف الداتابيز قبل أي إعادة بناء."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(BACKUP_DIR, "pre_%s_%s.db" % (tag, ts))
    src = sqlite3.connect(DB_PATH, timeout=30)
    dst = sqlite3.connect(path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    _prune_files(BACKUP_DIR, "pre_", ".db", keep=10)
    return path


def _prune_files(folder, prefix, suffix, keep):
    try:
        files = sorted(f for f in os.listdir(folder) if f.startswith(prefix) and f.endswith(suffix))
        for old in files[:-keep] if keep else files:
            try:
                os.remove(os.path.join(folder, old))
            except OSError:
                pass
    except OSError:
        pass


def _changelog(con, action, table=None, column=None, details="", source="system"):
    try:
        con.execute("INSERT INTO db_changelog(action, table_name, column_name, details, source) "
                    "VALUES(?,?,?,?,?)", (action, table, column, str(details)[:500], source))
    except sqlite3.OperationalError as e:
        log.warning("[SELF-HEAL] تعذر كتابة سجل التغييرات: %s", e)


def _heal_record(con, report, action, table, column, details):
    msg = "%s: %s%s — %s" % (action, table, ("." + column) if column else "", details)
    report["actions"].append(msg)
    log.info("[SELF-HEAL] %s", msg)
    _changelog(con, action, table, column, details, source="self_heal")


def _heal_warn(report, msg):
    report["warnings"].append(msg)
    log.warning("[SELF-HEAL] %s", msg)


def _rebuild_table(con, tname, ref, ref_indexes, report):
    """يعيد بناء جدول بالتعريف المرجعي مع نقل كل البيانات. داخل transaction: أي خطأ = تراجع كامل."""
    tmp = "_heal_old_" + tname
    old_cols = _table_cols(con, tname)
    old_names = {c["name"] for c in old_cols}
    old_idx = [(r[0], r[1]) for r in con.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL",
        (tname,)).fetchall()]
    ref_idx_sql = [sql for tbl, sql in ref_indexes if tbl == tname]

    con.commit()
    con.execute("PRAGMA legacy_alter_table=ON")   # حتى لا تتغير مراجع المفاتيح في الجداول الأخرى
    try:
        con.execute("BEGIN IMMEDIATE")
        for iname, _sql in old_idx:
            con.execute("DROP INDEX IF EXISTS %s" % _qid(iname))
        con.execute("ALTER TABLE %s RENAME TO %s" % (_qid(tname), _qid(tmp)))
        con.execute(ref["sql"])
        new_names = [c["name"] for c in _table_cols(con, tname)]
        for oc in old_cols:
            if oc["name"] not in new_names:
                decl, warn = _column_decl(oc)
                con.execute("ALTER TABLE %s ADD COLUMN %s %s" % (_qid(tname), _qid(oc["name"]), decl))
                new_names.append(oc["name"])
                if warn:
                    _heal_warn(report, "%s.%s: %s" % (tname, oc["name"], warn))
        common = [n for n in new_names if n in old_names]
        cl = ", ".join(_qid(n) for n in common)
        con.execute("INSERT INTO %s (%s) SELECT %s FROM %s" % (_qid(tname), cl, cl, _qid(tmp)))
        con.execute("DROP TABLE %s" % _qid(tmp))
        for _name, sql in old_idx:
            try:
                con.execute(sql)
            except sqlite3.OperationalError:
                pass
        for sql in ref_idx_sql:
            try:
                con.execute(sql)
            except sqlite3.OperationalError:
                pass
        con.commit()
        _heal_record(con, report, "rebuild_table", tname, None,
                     "أُعيد بناء الجدول بالتعريف الحديث وانتقلت بياناته كاملة (%d عموداً)" % len(common))
        return True
    except Exception as e:
        try:
            con.rollback()
        except Exception:
            pass
        _heal_warn(report, "فشلت إعادة بناء %s وتم التراجع بدون أي تغيير: %s" % (tname, e))
        return False
    finally:
        con.execute("PRAGMA legacy_alter_table=OFF")


def _flush_features(con):
    items = list(REGISTERED_FEATURES) + list(_pending_features)
    for fname, tname, cname in items:
        exists = con.execute(
            "SELECT 1 FROM feature_registry WHERE feature_name=? AND IFNULL(table_name,'')=IFNULL(?,'') "
            "AND IFNULL(column_name,'')=IFNULL(?,'')", (fname, tname, cname)).fetchone()
        if not exists:
            con.execute("INSERT INTO feature_registry(feature_name, table_name, column_name, status) "
                        "VALUES(?,?,?,'active')", (fname, tname, cname))
            log.info("[FEATURE] سُجلت ميزة جديدة: %s (%s.%s)", fname, tname, cname)


def self_heal_schema(force_rebuild=False):
    """الإصلاح الذاتي: يقارن SCHEMA بالداتابيز الفعلية ويضيف الجداول والأعمدة الناقصة
    ويعيد بناء ما اختلف نوعه أو افتراضيه. آمن للتكرار، ولا يحذف أي بيانات.
    force_rebuild=True يعيد بناء كل جداول SCHEMA مع الاحتفاظ بالبيانات (زر إعادة البناء)."""
    global _schema_sig_seen, _last_heal_report
    report = {"at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "ok": True,
              "actions": [], "warnings": []}
    with _SCHEMA_LOCK:
        con = None
        try:
            os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
            tables, ref_indexes = _reference_schema()
            con = sqlite3.connect(DB_PATH, timeout=30)
            con.execute("PRAGMA foreign_keys=OFF")
            con.executescript(META_SCHEMA)           # db_changelog و feature_registry
            con.commit()

            existing = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

            # 1) الجداول الناقصة
            for tname, ref in tables.items():
                if tname not in existing:
                    con.execute(ref["sql"].replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1))
                    _heal_record(con, report, "create_table", tname, None, "جدول ناقص — تم إنشاؤه")
                    existing.add(tname)
            con.commit()

            # 2) الأعمدة الناقصة من المرجع + الأعمدة الإضافية المعروفة
            for tname, ref in tables.items():
                have = {c["name"] for c in _table_cols(con, tname)}
                for rc in ref["cols"]:
                    if rc["name"] in have or rc["pk"]:
                        continue
                    decl, warn = _column_decl(rc)
                    con.execute("ALTER TABLE %s ADD COLUMN %s %s" % (_qid(tname), _qid(rc["name"]), decl))
                    _heal_record(con, report, "add_column", tname, rc["name"], "عمود ناقص — أُضيف (%s)" % decl)
                    if warn:
                        _heal_warn(report, "%s.%s: %s" % (tname, rc["name"], warn))
            for tname, cname, decl in EXTRA_COLUMNS:
                if tname not in existing:
                    continue
                if cname not in {c["name"] for c in _table_cols(con, tname)}:
                    con.execute("ALTER TABLE %s ADD COLUMN %s %s" % (_qid(tname), _qid(cname), decl))
                    _heal_record(con, report, "add_column", tname, cname, "عمود ناقص — أُضيف (%s)" % decl)
            con.commit()

            # 3) الاختلافات في النوع / الافتراضي / NOT NULL → إعادة بناء آمنة
            plan = []
            for tname, ref in tables.items():
                if force_rebuild:
                    plan.append((tname, "إعادة بناء يدوية"))
                    continue
                have = {c["name"]: c for c in _table_cols(con, tname)}
                for rc in ref["cols"]:
                    hc = have.get(rc["name"])
                    if hc is None:
                        if rc["pk"]:
                            plan.append((tname, "المفتاح الأساسي %s مفقود" % rc["name"]))
                            break
                        continue
                    reason = _col_drift(rc, hc)
                    if reason:
                        plan.append((tname, "%s: %s" % (rc["name"], reason)))
                        break

            if plan:
                backup = _backup_db_file("heal")
                _heal_record(con, report, "backup", "*", None, "نسخة احتياطية قبل إعادة البناء: " + os.path.basename(backup))
                seen = set()
                for tname, reason in plan:
                    if tname in seen:
                        continue
                    seen.add(tname)
                    _heal_record(con, report, "drift", tname, None, reason)
                    _rebuild_table(con, tname, tables[tname], ref_indexes, report)

            # 4) الأعمدة الإضافية المعروفة (بعد إعادة البناء) + الميزات
            _flush_features(con)
            con.commit()
            if not report["actions"]:
                log.info("[SELF-HEAL] قاعدة البيانات محدثة ولا تحتاج أي إصلاح.")
        except Exception as e:
            report["ok"] = False
            _heal_warn(report, "خطأ فادح في الإصلاح الذاتي: %s" % e)
            log.exception("[SELF-HEAL] fatal")
            try:
                if con:
                    con.rollback()
            except Exception:
                pass
        finally:
            if con:
                try:
                    con.close()
                except Exception:
                    pass
            _schema_sig_seen = _db_file_signature()
            _last_heal_report = report
    return report


@app.before_request
def _self_heal_before_request():
    """يتحقق قبل كل طلب: لو تغير ملف الداتابيز (استعادة نسخة مثلاً) يُعاد الإصلاح الذاتي."""
    global _schema_sig_seen
    sig = _db_file_signature()
    if sig is None or sig == _schema_sig_seen:
        return None
    try:
        self_heal_schema()
    except Exception:
        log.exception("[SELF-HEAL] before_request")
    return None


# ----------------- النسخ اللقطية (Snapshot) -----------------
def create_snapshot_zip():
    """ZIP يحتوي: قاعدة البيانات كاملة + web.py + مجلد static + ملف MANIFEST."""
    import zipfile
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    tmp_db = os.path.join(BACKUP_DIR, "_snap_tmp_%s.db" % ts)
    src = sqlite3.connect(DB_PATH, timeout=30)
    dst = sqlite3.connect(tmp_db)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    path = os.path.join(BACKUP_DIR, "snapshot_%s.zip" % ts)
    try:
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(tmp_db, "matari.db")
            wp = os.path.join(BASE_DIR, "web.py")
            if os.path.exists(wp):
                zf.write(wp, "web.py")
            static_dir = os.path.join(BASE_DIR, "static")
            if os.path.isdir(static_dir):
                for root, _dirs, files in os.walk(static_dir):
                    for f in files:
                        full = os.path.join(root, f)
                        zf.write(full, os.path.relpath(full, BASE_DIR))
            zf.writestr("MANIFEST.txt", "created_at=%s\nsource_db=%s\n" % (ts, DB_PATH))
    finally:
        try:
            os.remove(tmp_db)
        except OSError:
            pass
    _prune_files(BACKUP_DIR, "snapshot_", ".zip", keep=20)
    log.info("[SNAPSHOT] أُنشئت نسخة الأمان: %s", path)
    return path


def _backup_bot_creds():
    """يقرأ توكن وآيدي النسخ الاحتياطي (يُستدعى داخل طلب، لأن get_setting يحتاج سياق Flask)."""
    token = os.environ.get("BACKUP_BOT_TOKEN") or get_setting("BACKUP_BOT_TOKEN", "") or DEFAULT_SETTINGS.get("BACKUP_BOT_TOKEN", "")
    chat_id = os.environ.get("BACKUP_CHAT_ID") or get_setting("BACKUP_CHAT_ID", "") or DEFAULT_SETTINGS.get("BACKUP_CHAT_ID", "")
    return token, chat_id


def send_snapshot_to_telegram(path, token, chat_id):
    """يرسل ملف النسخة إلى تيليجرام عبر BACKUP_BOT_TOKEN و BACKUP_CHAT_ID."""
    try:
        import requests
        if not token or not chat_id or "ضع_" in token:
            return False, "BACKUP_BOT_TOKEN أو BACKUP_CHAT_ID غير مهيأ"
        if os.path.getsize(path) > 49 * 1024 * 1024:
            return False, "حجم الملف أكبر من حد تيليجرام (50MB)"
        with open(path, "rb") as f:
            r = requests.post(
                "https://api.telegram.org/bot%s/sendDocument" % token,
                data={"chat_id": chat_id, "caption": "🛡 نسخة أمان MATARI — " + os.path.basename(path)},
                files={"document": f}, timeout=180)
        ok = r.ok and bool(r.json().get("ok"))
        log.info("[SNAPSHOT] إرسال تيليجرام: %s", "نجح" if ok else "فشل")
        return ok, ("تم الإرسال إلى تيليجرام" if ok else "رفض تيليجرام الإرسال")
    except Exception as e:
        log.warning("[SNAPSHOT] فشل الإرسال: %s", e)
        return False, str(e)


# ----------------- معلومات الداتابيز للعرض -----------------
def _db_table_overview():
    con = sqlite3.connect(DB_PATH, timeout=30)
    try:
        names = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        out = []
        for n in names:
            try:
                cols = _table_cols(con, n)
                cnt = con.execute("SELECT COUNT(*) FROM %s" % _qid(n)).fetchone()[0]
            except sqlite3.Error:
                cols, cnt = [], "?"
            out.append({"name": n, "rows": cnt, "cols": cols})
        return out
    finally:
        con.close()


def _db_changelog_rows(limit=50):
    con = sqlite3.connect(DB_PATH, timeout=30)
    try:
        rows = con.execute("SELECT created_at, action, table_name, column_name, details, source "
                           "FROM db_changelog ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return rows
    except sqlite3.Error:
        return []
    finally:
        con.close()


def _set_db_action(ok, title, lines):
    global _db_last_action
    _db_last_action = {"title": title, "ok": ok, "lines": [str(x) for x in lines][:80]}


def _db_add_column_safe(table, col, ctype, default):
    con = sqlite3.connect(DB_PATH, timeout=30)
    try:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
            raise ValueError("الجدول غير موجود")
        if col in {c["name"] for c in _table_cols(con, table)}:
            raise ValueError("العمود موجود بالفعل")
        decl = ctype
        lit = _sql_literal(default)
        if lit is not None:
            decl += " DEFAULT " + lit
        con.execute("ALTER TABLE %s ADD COLUMN %s %s" % (_qid(table), _qid(col), decl))
        _changelog(con, "add_column", table, col, "يدوياً من لوحة الإدارة: " + decl, source="admin")
        con.commit()
        return decl
    finally:
        con.close()


def _db_add_table_safe(name, specs):
    con = sqlite3.connect(DB_PATH, timeout=30)
    try:
        if con.execute("SELECT 1 FROM sqlite_master WHERE name=?", (name,)).fetchone():
            raise ValueError("الاسم مستخدم بالفعل")
        parts = ["id INTEGER PRIMARY KEY AUTOINCREMENT"]
        for cname, ctype, dflt in specs:
            parts.append("%s %s%s" % (_qid(cname), ctype, (" DEFAULT " + dflt) if dflt else ""))
        parts.append("created_at TEXT DEFAULT (datetime('now'))")
        con.execute("CREATE TABLE %s (%s)" % (_qid(name), ", ".join(parts)))
        _changelog(con, "create_table", name, None, "يدوياً: " + ", ".join(s[0] for s in specs), source="admin")
        con.commit()
    finally:
        con.close()


_db_table_re = re.compile(
    r"^([A-Za-z_][A-Za-z0-9_]{0,63})\s+(TEXT|INTEGER|REAL|NUMERIC|BLOB)"
    r"(?:\s+DEFAULT\s+(-?\d+(?:\.\d+)?|'[^']*'))?$", re.IGNORECASE)


def _db_manager_css():
    return """<style>
.dbm-wrap{max-width:1100px;margin:0 auto;padding:0 12px 40px}
.dbm-hero{background:linear-gradient(135deg,rgba(99,102,241,.28),rgba(16,185,129,.18));border:1px solid var(--border);border-radius:20px;padding:22px;margin-bottom:18px;backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);box-shadow:0 8px 30px rgba(0,0,0,.25)}
.dbm-title{font-size:22px;font-weight:900;margin:0 0 6px}
.dbm-sub{color:var(--muted);font-size:13px;line-height:1.7}
.dbm-section{background:linear-gradient(145deg,var(--card),var(--card2));border:1px solid var(--border);border-radius:18px;padding:18px;margin-bottom:18px;backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px)}
.dbm-h{font-size:16px;font-weight:900;margin:0 0 12px;color:var(--text)}
.dbm-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:18px}
.dbm-stat{background:linear-gradient(145deg,var(--card),var(--card2));border:1px solid var(--border);border-radius:16px;padding:14px}
.dbm-stat b{display:block;font-size:24px;font-weight:900;background:linear-gradient(90deg,#818cf8,#10b981);-webkit-background-clip:text;background-clip:text;color:transparent}
.dbm-stat span{font-size:12px;color:var(--muted)}
.dbm-actions{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin-bottom:18px}
.dbm-actions form,.dbm-actions a{margin:0}
.dbm-btn{width:100%;padding:12px;border-radius:12px;border:1px solid var(--border);background:linear-gradient(135deg,rgba(99,102,241,.25),rgba(99,102,241,.08));color:var(--text);font-weight:800;cursor:pointer;text-decoration:none;display:flex;align-items:center;justify-content:center;gap:6px;font-size:14px}
.dbm-btn.green{background:linear-gradient(135deg,rgba(16,185,129,.3),rgba(16,185,129,.08))}
.dbm-btn.red{background:linear-gradient(135deg,rgba(239,68,68,.3),rgba(239,68,68,.08))}
.dbm-btn.amber{background:linear-gradient(135deg,rgba(245,158,11,.3),rgba(245,158,11,.08))}
.dbm-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:14px}
.dbm-card{background:rgba(255,255,255,.03);border:1px solid var(--border);border-radius:16px;padding:14px;backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px)}
.dbm-card h4{margin:0 0 6px;font-size:15px;font-weight:900;color:#a5b4fc;direction:ltr;text-align:left;word-break:break-all}
.dbm-meta{font-size:12px;color:var(--muted);margin-bottom:8px}
.dbm-cols{width:100%;border-collapse:collapse;font-size:12px}
.dbm-cols td,.dbm-cols th{padding:5px 4px;border-bottom:1px solid var(--border);text-align:right;vertical-align:top;word-break:break-all}
.dbm-cols th{color:var(--muted);font-weight:700}
.dbm-tag{display:inline-block;padding:1px 6px;border-radius:8px;background:rgba(16,185,129,.15);color:#10b981;font-size:10px;font-weight:800}
.dbm-form{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;align-items:end}
.dbm-form label{font-size:12px;color:var(--muted);font-weight:700;display:block;margin-bottom:4px}
.dbm-form input,.dbm-form select,.dbm-form textarea{width:100%;background:var(--bg2);color:var(--text);border:1px solid var(--border);border-radius:10px;padding:10px;font-size:14px;box-sizing:border-box;font-family:inherit}
.dbm-form textarea{min-height:90px;direction:ltr;font-family:monospace}
.dbm-log{max-height:420px;overflow:auto}
.dbm-log-row{padding:9px 10px;border-radius:10px;background:var(--bg2);margin-bottom:6px;border-right:3px solid #6366f1;font-size:12px;line-height:1.6;word-break:break-word}
.dbm-note{font-size:12px;color:var(--muted);margin-top:8px;line-height:1.7}
.dbm-result{border-radius:16px;padding:14px;margin-bottom:18px;border:1px solid var(--border)}
.dbm-result.ok{background:rgba(16,185,129,.1);border-color:rgba(16,185,129,.35)}
.dbm-result.bad{background:rgba(239,68,68,.1);border-color:rgba(239,68,68,.35)}
.dbm-result ul{margin:8px 0 0;padding-right:18px;font-size:13px;line-height:1.8}
@media (max-width:600px){.dbm-title{font-size:18px}.dbm-section{padding:14px}.dbm-form{grid-template-columns:1fr}}
</style>"""


def _render_db_manager(tables, changelog, action, heal):
    total_rows = 0
    for t in tables:
        if isinstance(t["rows"], int):
            total_rows += t["rows"]
    last_heal = heal.get("at") or "لم يُنفذ بعد"
    h = []
    h.append('<div class="dbm-wrap">')
    h.append('<div class="dbm-hero"><div class="dbm-title"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:inline-block;vertical-align:middle;margin-left:8px;"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg> إدارة قاعدة البيانات</div>'
             '<div class="dbm-sub">فحص وإصلاح وإضافة جداول وأعمدة ونسخ احتياطية، بدون حذف أي بيانات. '
             'كل تغيير يُسجَّل في سجل التغييرات.</div></div>')

    if action.get("title"):
        cls = "ok" if action.get("ok") else "bad"
        items = "".join("<li>%s</li>" % esc(x) for x in action.get("lines", []))
        h.append('<div class="dbm-result %s"><b>%s %s</b><ul>%s</ul></div>' % (
            cls, "نجح" if action.get("ok") else "تحذير", esc(action["title"]), items))

    h.append('<div class="dbm-stats">')
    h.append('<div class="dbm-stat"><b>%d</b><span>عدد الجداول</span></div>' % len(tables))
    h.append('<div class="dbm-stat"><b>%s</b><span>إجمالي الصفوف</span></div>' % total_rows)
    h.append('<div class="dbm-stat"><b>%d</b><span>سجل التغييرات</span></div>' % len(changelog))
    h.append('<div class="dbm-stat"><b style="font-size:13px">%s</b><span>آخر إصلاح تلقائي</span></div>' % esc(last_heal))
    h.append('</div>')

    h.append('<div class="dbm-section"><div class="dbm-h"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:inline-block;vertical-align:middle;margin-left:8px;"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg> الإجراءات</div><div class="dbm-actions">')
    h.append('<form method="POST" action="/admin/database/heal"><button class="dbm-btn green" type="submit"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:inline-block;vertical-align:middle;margin-left:6px;"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg> إصلاح تلقائي</button></form>')
    h.append('<form method="POST" action="/admin/database/rebuild" onsubmit="return confirm(\'سيُعاد بناء كل الجداول مع الاحتفاظ بالبيانات، وتُؤخذ نسخة احتياطية أولاً. متابعة؟\')"><button class="dbm-btn amber" type="submit"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:inline-block;vertical-align:middle;margin-left:6px;"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg> إعادة بناء الجداول</button></form>')
    h.append('<form method="POST" action="/admin/database/integrity"><button class="dbm-btn" type="submit"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:inline-block;vertical-align:middle;margin-left:6px;"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg> فحص سلامة الداتابيز</button></form>')
    h.append('<form method="POST" action="/admin/database/backup"><button class="dbm-btn" type="submit"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:inline-block;vertical-align:middle;margin-left:6px;"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg> نسخة احتياطية الآن</button></form>')
    h.append('<form method="POST" action="/admin/database/snapshot"><button class="dbm-btn green" type="submit"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:inline-block;vertical-align:middle;margin-left:6px;"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg> حفظ نسخة أمان (+ تيليجرام)</button></form>')
    h.append('<a class="dbm-btn red" href="/admin/backup/restore"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:inline-block;vertical-align:middle;margin-left:6px;"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg> استعادة نسخة</a>')
    h.append('<a class="dbm-btn" href="/admin"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:inline-block;vertical-align:middle;margin-left:6px;"><line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/></svg> رجوع للوحة</a>')
    h.append('</div><div class="dbm-note">زر الاستعادة يفتح صفحة الاستعادة الموجودة. بعد أي استعادة يعمل الإصلاح الذاتي تلقائياً عند أول طلب.</div></div>')

    h.append('<div class="dbm-section"><div class="dbm-h"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:inline-block;vertical-align:middle;margin-left:6px;"><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1" ry="1"/></svg> الجداول والأعمدة</div><div class="dbm-grid">')
    for t in tables:
        rows_html = ""
        for c in t["cols"]:
            tags = ' <span class="dbm-tag">PK</span>' if c["pk"] else ""
            dflt = "" if c["dflt"] is None else str(c["dflt"])
            rows_html += "<tr><td>%s%s</td><td>%s</td><td>%s</td></tr>" % (
                esc(c["name"]), tags, esc(c["type"] or "-"), esc(dflt) or "—")
        h.append('<div class="dbm-card"><h4>%s</h4><div class="dbm-meta"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:inline-block;vertical-align:middle;margin-left:4px;"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg> %s صف · %d عمود</div>'
                 '<table class="dbm-cols"><tr><th>العمود</th><th>النوع</th><th>افتراضي</th></tr>%s</table></div>'
                 % (esc(t["name"]), esc(t["rows"]), len(t["cols"]), rows_html))
    h.append('</div></div>')

    h.append('<div class="dbm-section"><div class="dbm-h"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:inline-block;vertical-align:middle;margin-left:8px;"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="16"/><line x1="8" y1="12" x2="16" y2="12"/></svg> إضافة عمود جديد</div>'
             '<form method="POST" action="/admin/database/add_column" class="dbm-form">'
             '<div><label>الجدول</label><select name="table" required>')
    for t in tables:
        h.append('<option value="%s">%s</option>' % (esc(t["name"]), esc(t["name"])))
    h.append('</select></div>'
             '<div><label>اسم العمود</label><input name="column" required placeholder="new_column"></div>'
             '<div><label>النوع</label><select name="ctype">'
             '<option>TEXT</option><option>INTEGER</option><option>REAL</option><option>NUMERIC</option><option>BLOB</option>'
             '</select></div>'
             '<div><label>القيمة الافتراضية (اختياري)</label><input name="default" placeholder="مثال: 0 أو active"></div>'
             '<div><button class="dbm-btn green" type="submit">إضافة العمود</button></div>'
             '</form></div>')

    h.append('<div class="dbm-section"><div class="dbm-h"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:inline-block;vertical-align:middle;margin-left:8px;"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="12" y1="18" x2="12" y2="12"/><line x1="9" y1="15" x2="15" y2="15"/></svg> إضافة جدول جديد</div>'
             '<form method="POST" action="/admin/database/add_table" class="dbm-form" style="grid-template-columns:1fr">'
             '<div><label>اسم الجدول</label><input name="name" required placeholder="my_table"></div>'
             '<div><label>الأعمدة (سطر لكل عمود)، الصيغة: اسم النوع [DEFAULT قيمة]</label>'
             '<textarea name="columns" placeholder="title TEXT DEFAULT &#39;&#39;&#10;amount REAL DEFAULT 0"></textarea></div>'
             '<div><button class="dbm-btn green" type="submit">إنشاء الجدول</button></div>'
             '<div class="dbm-note">يُضاف تلقائياً عمود id (مفتاح أساسي) وعمود created_at. الجدول لا يُحذف من هنا.</div>'
             '</form></div>')

    h.append('<div class="dbm-section"><div class="dbm-h"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:inline-block;vertical-align:middle;margin-left:8px;"><path d="M4 2v20l4-4 4 4 4-4 4 4V2z"/><line x1="8" y1="7" x2="16" y2="7"/><line x1="8" y1="11" x2="16" y2="11"/><line x1="8" y1="15" x2="13" y2="15"/></svg> سجل التغييرات (آخر 50)</div><div class="dbm-log">')
    if not changelog:
        h.append('<div class="dbm-note">لا توجد تغييرات مسجلة بعد.</div>')
    for row in changelog:
        created, act, tname, cname, details, source = row
        target = (tname or "") + (("." + cname) if cname else "")
        h.append('<div class="dbm-log-row"><b>%s</b> · %s · <span style="color:var(--muted)">%s</span><br>%s<br>'
                 '<span style="color:var(--muted)">%s · %s</span></div>' % (
                     esc(act), esc(target or "—"), esc(source or ""), esc(details or ""),
                     esc(created or ""), esc(source or "")))
    h.append('</div></div>')
    h.append('</div>')
    return _db_manager_css() + "".join(h)


# ----------------- المسارات -----------------
@app.route("/admin/database")
@admin_required
@register_feature("إدارة قاعدة البيانات", "db_changelog")
def admin_database():
    try:
        tables = _db_table_overview()
    except Exception as e:
        log.exception("admin_database overview")
        tables = []
        _set_db_action(False, "تعذر قراءة الداتابيز", [str(e)])
    body = _render_db_manager(tables, _db_changelog_rows(50), _db_last_action, _last_heal_report)
    return page("admin_database", body=body)


@app.route("/admin/database/heal", methods=["POST"])
@admin_required
def admin_database_heal():
    rep = self_heal_schema()
    lines = list(rep["actions"]) + ["⚠️ " + w for w in rep["warnings"]]
    if not lines:
        lines = ["قاعدة البيانات سليمة ومحدثة ولا تحتاج أي إصلاح."]
    _set_db_action(rep["ok"] and not rep["warnings"], "نتيجة الإصلاح التلقائي", lines)
    return redirect(url_for("admin_database"))


@app.route("/admin/database/rebuild", methods=["POST"])
@admin_required
def admin_database_rebuild():
    rep = self_heal_schema(force_rebuild=True)
    lines = list(rep["actions"]) + ["⚠️ " + w for w in rep["warnings"]]
    _set_db_action(rep["ok"] and not rep["warnings"], "نتيجة إعادة بناء الجداول", lines or ["لا شيء للتنفيذ"])
    return redirect(url_for("admin_database"))


@app.route("/admin/database/integrity", methods=["POST"])
@admin_required
def admin_database_integrity():
    con = sqlite3.connect(DB_PATH, timeout=30)
    try:
        res = [r[0] for r in con.execute("PRAGMA integrity_check").fetchall()]
        fk = con.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        con.close()
    ok = res == ["ok"]
    lines = ["integrity_check: " + ("ok " if ok else "; ".join(res[:20]))]
    lines.append("foreign_key_check: " + ("لا توجد مشاكل " if not fk else "%d مشكلة" % len(fk)))
    _set_db_action(ok and not fk, "نتيجة فحص السلامة", lines)
    return redirect(url_for("admin_database"))


@app.route("/admin/database/backup", methods=["POST"])
@admin_required
def admin_database_backup():
    ok, res = make_safe_backup()
    _set_db_action(ok, "نسخة احتياطية", [("تم إنشاء: " + os.path.basename(res)) if ok else ("فشل: " + str(res))])
    return redirect(url_for("admin_database"))


@app.route("/admin/database/snapshot", methods=["POST"])
@admin_required
def admin_database_snapshot():
    try:
        path = create_snapshot_zip()
    except Exception as e:
        log.exception("snapshot")
        _set_db_action(False, "نسخة الأمان", ["فشل إنشاء النسخة: %s" % e])
        return redirect(url_for("admin_database"))
    token, chat_id = _backup_bot_creds()
    threading.Thread(target=send_snapshot_to_telegram, args=(path, token, chat_id), daemon=True).start()
    _set_db_action(True, "نسخة الأمان", [
        "تم حفظ النسخة محلياً: backups/auto/" + os.path.basename(path),
        "جاري الإرسال إلى تيليجرام في الخلفية (تحقق من السجل إن لم تصل)."])
    return redirect(url_for("admin_database"))


@app.route("/admin/database/add_column", methods=["POST"])
@admin_required
def admin_database_add_column():
    table = request.form.get("table", "").strip()
    col = request.form.get("column", "").strip()
    ctype = request.form.get("ctype", "TEXT").strip().upper()
    default = request.form.get("default", "")
    err = _validate_ident(table) or _validate_ident(col)
    if not err and ctype not in _SQL_TYPES:
        err = "نوع غير مدعوم"
    if err:
        _set_db_action(False, "إضافة عمود", [err])
        return redirect(url_for("admin_database"))
    try:
        decl = _db_add_column_safe(table, col, ctype, default)
        _set_db_action(True, "إضافة عمود", ["أُضيف %s.%s (%s) " % (table, col, decl)])
    except Exception as e:
        _set_db_action(False, "إضافة عمود", [str(e)])
    return redirect(url_for("admin_database"))


@app.route("/admin/database/add_table", methods=["POST"])
@admin_required
def admin_database_add_table():
    name = request.form.get("name", "").strip()
    spec = request.form.get("columns", "")
    err = _validate_ident(name)
    specs, seen = [], set(["id", "created_at"])
    if not err:
        for raw in spec.splitlines():
            line = raw.strip()
            if not line:
                continue
            m = _db_table_re.match(line)
            if not m:
                err = "سطر غير صالح: " + line
                break
            cname, ctype, dflt = m.group(1), m.group(2).upper(), m.group(3)
            e2 = _validate_ident(cname)
            if e2 or cname.lower() in seen:
                err = e2 or ("عمود مكرر: " + cname)
                break
            seen.add(cname.lower())
            specs.append((cname, ctype, dflt))
        if not err and not specs:
            err = "أضف عموداً واحداً على الأقل"
    if err:
        _set_db_action(False, "إنشاء جدول", [err])
        return redirect(url_for("admin_database"))
    try:
        _db_add_table_safe(name, specs)
        _set_db_action(True, "إنشاء جدول", ["أُنشئ الجدول %s بـ %d عمود " % (name, len(specs))])
    except Exception as e:
        _set_db_action(False, "إنشاء جدول", [str(e)])
    return redirect(url_for("admin_database"))


# ============================================================

# ============================================================
# Page & Link Builder + Dev History + تحسين السلاسة (Smooth Navigation)
# ============================================================
import html as _html_mod
from html.parser import HTMLParser as _PBHTMLParser

PB_POSITIONS = ("block", "navbar", "links_page")
PB_TARGETS = ("all", "admin", "user")
PB_MAX_HTML = 200000
DEV_TYPES = {
    "feature": ("ميزة جديدة", "#10b981"),
    "fix": ("إصلاح", "#ef4444"),
    "update": ("تحديث", "#3b82f6"),
    "hotfix": ("إصلاح عاجل", "#a855f7"),
}

# ---------- تنظيف HTML (قائمة سماح، بدون مكتبات خارجية) ----------
_PB_ALLOWED_TAGS = {"p", "br", "b", "strong", "i", "em", "u", "ul", "ol", "li",
                    "h1", "h2", "h3", "h4", "blockquote", "a", "img", "span",
                    "div", "hr", "code", "pre", "small"}
_PB_VOID_TAGS = {"br", "hr", "img"}
_PB_DROP_TAGS = {"script", "style", "iframe", "object", "embed", "noscript", "template",
                 "svg", "math", "form", "input", "button", "select", "textarea",
                 "link", "meta", "base", "frame", "frameset", "applet", "audio", "video"}
_PB_ATTRS = {
    "a": ("href", "title"),
    "img": ("src", "alt", "width", "height"),
    "span": ("style",), "div": ("style",), "p": ("style",),
    "h1": ("style",), "h2": ("style",), "h3": ("style",), "h4": ("style",),
    "li": ("style",), "b": ("style",), "strong": ("style",),
}
_PB_STYLE_DECL = re.compile(
    r"^(color|background-color|text-align|font-size|font-weight|font-style|text-decoration)"
    r"\s*:\s*(#[0-9a-fA-F]{3,8}|[a-zA-Z-]+|-?\d+(\.\d+)?(px|em|rem|%)?)$")
_PB_COLOR = re.compile(r"^#[0-9a-fA-F]{3,8}$")


def _pb_clean_style(value):
    keep = []
    for decl in (value or "").split(";"):
        decl = decl.strip()
        if decl and _PB_STYLE_DECL.match(decl):
            keep.append(decl)
    return "; ".join(keep)


def _pb_safe_url(value):
    """يقبل روابط http/https والمسارات النسبية (/...) و #... فقط. يرفض javascript: و data: وغيرها."""
    raw = (value or "").strip()
    if not raw or len(raw) > 2000:
        return None
    compact = re.sub(r"[\x00-\x20\x7f]", "", raw).lower()
    if compact.startswith(("http://", "https://")):
        return raw
    if raw.startswith("/") and not compact.startswith("//") and "\\" not in raw:
        return raw
    if raw.startswith("#"):
        return raw
    return None


class _PBSanitizer(_PBHTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.drop = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in _PB_DROP_TAGS:
            if tag not in _PB_VOID_TAGS:
                self.drop += 1
            return
        if self.drop or tag not in _PB_ALLOWED_TAGS:
            return
        parts = []
        allowed = _PB_ATTRS.get(tag, ())
        for key, val in attrs:
            key = (key or "").lower()
            val = val or ""
            if key not in allowed:
                continue
            if key == "href":
                url = _pb_safe_url(val)
                if url is None:
                    continue
                parts.append(' href="%s"' % _html_mod.escape(url, quote=True))
                if url.lower().startswith("http"):
                    parts.append(' target="_blank" rel="noopener noreferrer"')
            elif key == "src":
                url = _pb_safe_url(val)
                if url is None or not (url.startswith("http") or url.startswith("/static/")):
                    continue
                parts.append(' src="%s"' % _html_mod.escape(url, quote=True))
            elif key == "style":
                style = _pb_clean_style(val)
                if style:
                    parts.append(' style="%s"' % _html_mod.escape(style, quote=True))
            elif key in ("width", "height"):
                if re.match(r"^\d{1,4}$", val):
                    parts.append(' %s="%s"' % (key, val))
            elif key in ("alt", "title"):
                parts.append(' %s="%s"' % (key, _html_mod.escape(val, quote=True)))
        self.out.append("<%s%s>" % (tag, "".join(parts)))

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in _PB_DROP_TAGS:
            if tag not in _PB_VOID_TAGS and self.drop:
                self.drop -= 1
            return
        if self.drop or tag not in _PB_ALLOWED_TAGS or tag in _PB_VOID_TAGS:
            return
        self.out.append("</%s>" % tag)

    def handle_data(self, data):
        if not self.drop:
            self.out.append(_html_mod.escape(data, quote=False))


def sanitize_html(raw):
    """ينظف HTML من script/iframe/on*/javascript: ويعيد HTML آمناً فقط."""
    parser = _PBSanitizer()
    parser.feed(str(raw or "")[:PB_MAX_HTML])
    parser.close()
    return "".join(parser.out)


def slugify(text):
    s = re.sub(r"[^a-z0-9-]+", "-", (text or "").strip().lower())
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:80] or ("page-" + secrets.token_hex(3))


def _pb_color(value):
    value = (value or "").strip()
    return value if _PB_COLOR.match(value) else "#6366f1"


# ---------- قراءة الروابط حسب المكان والجمهور ----------
def _pb_visible(u, position):
    rows = db().execute("SELECT * FROM custom_links WHERE position=? AND is_active=1 "
                        "ORDER BY sort_order ASC, id ASC", (position,)).fetchall()
    admin = is_admin(u)
    logged = bool(u)
    out = []
    for r in rows:
        t = r["target_users"] or "all"
        if t == "all" or (t == "admin" and admin) or (t == "user" and logged and not admin):
            out.append(r)
    return out


def _pb_icon(name, size=18):
    return ico(name, size) or ico("globe", size)


def _pb_link_card(r):
    href = _pb_safe_url(r["url"]) or "#"
    return ('<a class="pb-card" href="%s" style="--pb-c:%s">'
            '<span class="pb-ico">%s</span><span class="pb-title">%s</span></a>') % (
        esc(href), _pb_color(r["color"]), _pb_icon(r["icon_name"], 22), esc(r["title"]))


def _pb_navbar_html(u):
    links = _pb_visible(u, "navbar")
    if not links:
        return ""
    items = ""
    for r in links:
        href = _pb_safe_url(r["url"]) or "#"
        items += ('<a class="pb-nav" href="%s" title="%s">%s<span>%s</span></a>') % (
            esc(href), esc(r["title"]), _pb_icon(r["icon_name"], 16), esc(r["title"]))
    return '<div class="pb-nav-wrap">' + items + '</div>'


# ---------- سجل التطوير: إنشاء نسخة + تسجيل ----------
def _dev_next_version():
    prefix = datetime.now().strftime("v%Y.%m.%d.")
    n = db().execute("SELECT COUNT(*) c FROM dev_history WHERE version LIKE ?",
                     (prefix + "%",)).fetchone()["c"] + 1
    while db().execute("SELECT 1 FROM dev_history WHERE version=?", (prefix + "%02d" % n,)).fetchone():
        n += 1
    return prefix + "%02d" % n


def _dev_prune(keep=50):
    import shutil
    rows = db().execute("SELECT id, version FROM dev_history ORDER BY id DESC").fetchall()
    for r in rows[keep:]:
        shutil.rmtree(os.path.join(BASE_DIR, "backups", "versions", r["version"]), ignore_errors=True)
        db().execute("DELETE FROM dev_history WHERE id=?", (r["id"],))
    db().commit()


def log_dev_change(title, description="", change_type="update", files_changed=None,
                   db_changes=None, created_by=None):
    """ينشئ نسخة كاملة (matari.db + web.py + static) في ZIP، ويسجلها في dev_history،
    ويرسلها إلى تيليجرام في الخلفية، ويحتفظ بآخر 50 نسخة فقط."""
    import zipfile
    import json
    if change_type not in DEV_TYPES:
        change_type = "update"
    if created_by is None:
        try:
            created_by = session.get("user_id")
        except RuntimeError:
            created_by = None
    version = _dev_next_version()
    vdir = os.path.join(BASE_DIR, "backups", "versions", version)
    os.makedirs(vdir, exist_ok=True)
    tmp_db = os.path.join(vdir, "matari.db")
    src = sqlite3.connect(DB_PATH, timeout=30)
    dst = sqlite3.connect(tmp_db)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    zip_path = os.path.join(vdir, version + ".zip")
    files = []
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(tmp_db, "matari.db")
        files.append("matari.db")
        wp = os.path.join(BASE_DIR, "web.py")
        if os.path.exists(wp):
            zf.write(wp, "web.py")
            files.append("web.py")
        static_dir = os.path.join(BASE_DIR, "static")
        if os.path.isdir(static_dir):
            for root, _dirs, fnames in os.walk(static_dir):
                for fn in fnames:
                    full = os.path.join(root, fn)
                    rel = os.path.relpath(full, BASE_DIR).replace(os.sep, "/")
                    zf.write(full, rel)
                    files.append(rel)
        zf.writestr("MANIFEST.json", json.dumps({
            "version": version, "title": title, "type": change_type,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "files": len(files)},
            ensure_ascii=False, indent=2))
    try:
        os.remove(tmp_db)
    except OSError:
        pass
    db().execute("INSERT INTO dev_history(version, title, description, change_type, files_changed, "
                 "db_changes, backup_path, created_by) VALUES(?,?,?,?,?,?,?,?)",
                 (version, title[:160], (description or "")[:2000], change_type,
                  json.dumps(files_changed or files, ensure_ascii=False)[:4000],
                  (db_changes or "")[:500], zip_path, created_by))
    db().commit()
    _dev_prune(50)
    try:
        threading.Thread(target=_send_backup_to_telegram, args=(zip_path,), daemon=True).start()
    except Exception as e:
        log.warning("[DEV] telegram thread: %s", e)
    log.info("[DEV] سُجلت النسخة %s: %s", version, title)
    return version


def _pb_validate_slug_free(slug, pid):
    return db().execute("SELECT id FROM custom_pages WHERE slug=? AND id IS NOT ?",
                        (slug, pid)).fetchone() is None


# ---------- الصفحات المخصصة: عرض عام ----------
@app.route("/p/<slug>")
def custom_page_view(slug):
    row = db().execute("SELECT * FROM custom_pages WHERE slug=? AND is_active=1", (slug,)).fetchone()
    if not row:
        abort(404)
    body = ('<div class="container" style="max-width:820px"><div class="card pb-article">'
            '<h1 class="pb-h1">' + esc(row["title"]) + '</h1>' +
            sanitize_html_public(row["content_html"]) + '</div></div>')
    return page("custom_page", body=body)


@app.route("/links")
def links_page():
    u = current_user()
    links = _pb_visible(u, "links_page")
    grid = "".join(_pb_link_card(r) for r in links) or (
        '<div class="card" style="text-align:center;color:var(--muted)">لا توجد روابط حالياً.</div>')
    body = ('<div class="container" style="max-width:900px"><div class="section-title">الروابط</div>'
            '<div class="pb-grid">' + grid + '</div></div>')
    return page("links_page", body=body)


# ---------- إدارة الصفحات (أدمن) ----------
_PB_INPUT = ('width:100%;background:var(--bg2);color:var(--text);border:1px solid var(--border);'
             'border-radius:12px;padding:12px;font-size:14px;box-sizing:border-box;font-family:inherit')


def _pb_page_form(row=None):
    title = esc(row["title"]) if row else ""
    slug = esc(row["slug"]) if row else ""
    meta = esc(row["meta_description"]) if row and row["meta_description"] else ""
    checked = " checked" if (row is None or row["is_active"]) else ""
    seed = esc(row["content_html"]) if row else ""
    action = ("/admin/pages/%d/edit" % row["id"]) if row else "/admin/pages/new"
    return f'''
<div class="container" style="max-width:900px">
  <div class="section-title">{"تعديل صفحة" if row else "صفحة جديدة"}</div>
  <a href="/admin/pages" class="btn btn-ghost btn-sm" style="margin-bottom:16px">رجوع للصفحات</a>
  <form method="POST" action="{action}" id="pbPageForm" class="card" style="padding:18px">
    <div style="margin-bottom:12px"><label class="pb-label">العنوان</label>
      <input name="title" required value="{title}" style="{_PB_INPUT}" oninput="pbAutoSlug(this.value)"></div>
    <div style="margin-bottom:12px"><label class="pb-label">الرابط (slug) - يظهر كـ /p/الرابط</label>
      <input name="slug" id="pbSlug" dir="ltr" value="{slug}" placeholder="new-feature" style="{_PB_INPUT}"></div>
    <div style="margin-bottom:12px"><label class="pb-label">وصف قصير (اختياري)</label>
      <input name="meta_description" value="{meta}" style="{_PB_INPUT}"></div>
    <div style="margin-bottom:12px"><label class="pb-label">المحتوى</label>
      <div class="pb-toolbar">
        <button type="button" class="pb-tb" onclick="pbCmd('bold')" title="عريض">{ico("edit", 16)}<b>B</b></button>
        <button type="button" class="pb-tb" onclick="pbCmd('italic')" title="مائل"><i>I</i></button>
        <button type="button" class="pb-tb" onclick="pbCmd('underline')" title="تسطير"><u>U</u></button>
        <button type="button" class="pb-tb" onclick="pbLink()" title="رابط">{ico("globe", 16)}</button>
        <button type="button" class="pb-tb" onclick="pbImage()" title="صورة">{ico("file", 16)}</button>
        <button type="button" class="pb-tb" onclick="pbToggleHtml()" title="عرض HTML">{ico("list", 16)}</button>
        <button type="button" class="pb-tb" onclick="pbPreview()" title="معاينة">{ico("eye", 16)}</button>
      </div>
      <div id="pbEditor" class="pb-editor" contenteditable="true"></div>
      <textarea id="pbHtml" class="pb-html" dir="ltr" spellcheck="false" style="display:none"></textarea>
      <textarea id="pbSeed" hidden>{seed}</textarea>
      <input type="hidden" name="content_html" id="pbContent">
    </div>
    <label class="pb-check"><input type="checkbox" name="is_active"{checked}> الصفحة نشطة (ظاهرة للزوار)</label>
    <div style="display:flex;gap:10px;margin-top:16px;flex-wrap:wrap">
      <button class="btn" type="submit" onclick="pbSync()">حفظ</button>
      <a class="btn btn-ghost" href="/admin/pages">إلغاء</a>
    </div>
  </form>
</div>
<div id="pbModal" class="pb-modal" onclick="if(event.target===this)pbCloseModal()">
  <div class="pb-modal-box">
    <div class="pb-row"><b>معاينة</b><button type="button" class="btn btn-sm btn-ghost" onclick="pbCloseModal()">إغلاق</button></div>
    <iframe id="pbFrame" sandbox="" referrerpolicy="no-referrer" style="width:100%;height:70vh;border:0;border-radius:12px;background:#0b0b1a"></iframe>
  </div>
</div>
<script>
(function(){{
  var ed=document.getElementById('pbEditor'), seed=document.getElementById('pbSeed');
  ed.innerHTML=seed.value;
}})();
function pbAutoSlug(t){{
  var s=document.getElementById('pbSlug'); if(s.value) return;
  s.value=(t||'').toLowerCase().replace(/[^a-z0-9-]+/g,'-').replace(/-+/g,'-').replace(/^-|-$/g,'');
}}
function pbCmd(c){{ document.getElementById('pbEditor').focus(); document.execCommand(c,false,null); }}
function pbLink(){{ var u=prompt('الرابط (http أو /مسار)'); if(u) {{ document.getElementById('pbEditor').focus(); document.execCommand('createLink',false,u); }} }}
function pbImage(){{ var u=prompt('رابط الصورة (http أو /static/...)'); if(u) {{ document.getElementById('pbEditor').focus(); document.execCommand('insertImage',false,u); }} }}
function pbToggleHtml(){{
  var ed=document.getElementById('pbEditor'), h=document.getElementById('pbHtml');
  if(h.style.display==='none'){{ h.value=ed.innerHTML; h.style.display='block'; ed.style.display='none'; }}
  else {{ ed.innerHTML=h.value; h.style.display='none'; ed.style.display='block'; }}
}}
function pbSync(){{
  var h=document.getElementById('pbHtml');
  var v=(h.style.display==='block')? h.value : document.getElementById('pbEditor').innerHTML;
  document.getElementById('pbContent').value=v;
}}
function pbPreview(){{
  pbSync();
  var fd=new FormData(document.getElementById('pbPageForm'));
  fetch('/admin/pages/preview',{{method:'POST',body:fd,credentials:'same-origin'}})
    .then(function(r){{return r.text();}})
    .then(function(t){{ document.getElementById('pbFrame').srcdoc=t; document.getElementById('pbModal').style.display='flex'; }});
}}
function pbCloseModal(){{ document.getElementById('pbModal').style.display='none'; }}
</script>'''


@app.route("/admin/pages")
@admin_required
def admin_pages_list():
    rows = db().execute("SELECT * FROM custom_pages ORDER BY id DESC").fetchall()
    cards = ""
    for r in rows:
        ok = bool(r["is_active"])
        cards += ('<div class="card pb-admin-card">'
                  '<div class="pb-row"><b>' + esc(r["title"]) + '</b>'
                  '<span class="pb-status ' + ("ok" if ok else "off") + '">' + ("نشطة" if ok else "معطلة") + '</span></div>'
                  '<div class="pb-meta" dir="ltr">/p/' + esc(r["slug"]) + '</div>'
                  '<div class="pb-meta">تاريخ الإنشاء: ' + esc(r["created_at"]) + '</div>'
                  '<div class="pb-actions">'
                  '<a class="btn btn-sm btn-ghost" href="/p/' + esc(r["slug"]) + '" target="_blank" rel="noopener">معاينة</a>'
                  '<a class="btn btn-sm" href="/admin/pages/' + str(r["id"]) + '/edit">تعديل</a>'
                  '<form method="POST" action="/admin/pages/' + str(r["id"]) + '/delete" '
                  'onsubmit="return confirm(\'حذف هذه الصفحة؟\')">'
                  '<button class="btn btn-sm pb-danger" type="submit">حذف</button></form>'
                  '</div></div>')
    if not rows:
        cards = '<div class="card" style="text-align:center;color:var(--muted)">لا توجد صفحات بعد.</div>'
    body = ('<div class="container" style="max-width:900px">'
            '<div class="section-title">الصفحات المخصصة</div>'
            '<div class="pb-top"><a href="/admin" class="btn btn-ghost btn-sm">رجوع</a>'
            '<a href="/admin/pages/new" class="btn btn-sm">صفحة جديدة</a>'
            '<a href="/admin/links" class="btn btn-ghost btn-sm">الأزرار والروابط</a></div>'
            '<div class="pb-list">' + cards + '</div></div>')
    return page("admin_pages", body=body)


def _pb_save_page(pid):
    title = (request.form.get("title") or "").strip()[:160]
    slug = slugify((request.form.get("slug") or "").strip() or title)
    meta = (request.form.get("meta_description") or "").strip()[:300]
    content = request.form.get("content_html") or ""
    active = 1 if request.form.get("is_active") == "on" else 0
    back = "/admin/pages/new" if pid is None else "/admin/pages/%d/edit" % pid
    if not title:
        flash("العنوان مطلوب.", "error")
        return redirect(back)
    if not content.strip():
        flash("المحتوى فارغ بعد التنظيف الأمني.", "error")
        return redirect(back)
    if not _pb_validate_slug_free(slug, pid):
        flash("هذا الرابط (slug) مستخدم بالفعل، اختر غيره.", "error")
        return redirect(back)
    if pid is None:
        db().execute("INSERT INTO custom_pages(slug, title, content_html, meta_description, is_active, "
                     "created_by, updated_at) VALUES(?,?,?,?,?,?,datetime('now'))",
                     (slug, title, content, meta, active, session.get("user_id")))
        action, ctype = "إنشاء صفحة", "feature"
    else:
        db().execute("UPDATE custom_pages SET slug=?, title=?, content_html=?, meta_description=?, "
                     "is_active=?, updated_at=datetime('now') WHERE id=?",
                     (slug, title, content, meta, active, pid))
        action, ctype = "تعديل صفحة", "update"
    db().commit()
    log_dev_change("%s: %s" % (action, title),
                   "الرابط: /p/%s - الحالة: %s" % (slug, "نشطة" if active else "معطلة"),
                   change_type=ctype, db_changes="custom_pages")
    flash("تم الحفظ بنجاح.", "success")
    return redirect(url_for("admin_pages_list"))


@app.route("/admin/pages/new", methods=["GET", "POST"])
@admin_required
@register_feature("الصفحات المخصصة", "custom_pages")
def admin_page_new():
    if request.method == "POST":
        return _pb_save_page(None)
    return page("admin_page_form", body=_pb_page_form(None))


@app.route("/admin/pages/<int:pid>/edit", methods=["GET", "POST"])
@admin_required
def admin_page_edit(pid):
    row = db().execute("SELECT * FROM custom_pages WHERE id=?", (pid,)).fetchone()
    if not row:
        abort(404)
    if request.method == "POST":
        return _pb_save_page(pid)
    return page("admin_page_form", body=_pb_page_form(row))


@app.route("/admin/pages/<int:pid>/delete", methods=["POST"])
@admin_required
def admin_page_delete(pid):
    row = db().execute("SELECT * FROM custom_pages WHERE id=?", (pid,)).fetchone()
    if not row:
        abort(404)
    db().execute("DELETE FROM custom_pages WHERE id=?", (pid,))
    db().commit()
    log_dev_change("حذف صفحة: " + row["title"], "الرابط كان: /p/" + row["slug"],
                   change_type="update", db_changes="custom_pages")
    flash("تم حذف الصفحة.", "success")
    return redirect(url_for("admin_pages_list"))


@app.route("/admin/pages/preview", methods=["POST"])
@admin_required
def admin_page_preview():
    body = request.form.get("content_html") or ""
    title = esc(request.form.get("title") or "")
    doc = ('<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="utf-8">'
           '<link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;700;900&display=swap" rel="stylesheet">'
           '<style>body{font-family:Cairo,sans-serif;background:#0b0b1a;color:#e8e8f5;margin:0;padding:18px;line-height:1.8}'
           'a{color:#818cf8}img{max-width:100%;height:auto;border-radius:12px}h1,h2,h3{color:#fff}</style>'
           '</head><body><h1>' + title + '</h1>' + body + '</body></html>')
    resp = Response(doc, mimetype="text/html")
    resp.headers["Content-Security-Policy"] = ("default-src 'none'; img-src https: data: /static/; "
                                               "style-src 'unsafe-inline' https://fonts.googleapis.com; "
                                               "font-src https://fonts.gstatic.com")
    return resp


# ---------- إدارة الأزرار (أدمن) ----------
def _pb_link_form(row=None):
    pages = db().execute("SELECT slug, title FROM custom_pages ORDER BY id DESC").fetchall()
    opts = '<option value="">- اختر صفحة -</option>' + "".join(
        '<option value="/p/%s">%s</option>' % (esc(p["slug"]), esc(p["title"])) for p in pages)
    icon_opts = "".join('<option value="%s"%s>%s</option>' % (
        k, " selected" if row and row["icon_name"] == k else "", k) for k in ICONS.keys())
    pos_opts = "".join('<option value="%s"%s>%s</option>' % (
        p, " selected" if row and row["position"] == p else "", lbl) for p, lbl in (
        ("block", "لوحة المستخدم - بلوك مخصص"), ("navbar", "الشريط العلوي"), ("links_page", "صفحة الروابط")))
    tgt_opts = "".join('<option value="%s"%s>%s</option>' % (
        t, " selected" if row and row["target_users"] == t else "", lbl) for t, lbl in (
        ("all", "الجميع"), ("user", "المستخدمون فقط"), ("admin", "الأدمن فقط")))
    action = ("/admin/links/%d/edit" % row["id"]) if row else "/admin/links/new"
    v = lambda k, d="": esc(row[k]) if row and row[k] is not None else d  # noqa: E731
    active = " checked" if (row is None or row["is_active"]) else ""
    return f'''
<div class="container" style="max-width:700px">
  <div class="section-title">{"تعديل زر" if row else "زر جديد"}</div>
  <a href="/admin/links" class="btn btn-ghost btn-sm" style="margin-bottom:16px">رجوع للأزرار</a>
  <form method="POST" action="{action}" class="card" style="padding:18px">
    <div style="margin-bottom:12px"><label class="pb-label">العنوان</label>
      <input name="title" required value="{v("title")}" style="{_PB_INPUT}"></div>
    <div style="margin-bottom:12px"><label class="pb-label">ربط بصفحة مخصصة (اختياري)</label>
      <select style="{_PB_INPUT}" onchange="if(this.value)document.getElementById('pbUrl').value=this.value">{opts}</select></div>
    <div style="margin-bottom:12px"><label class="pb-label">الرابط</label>
      <input id="pbUrl" name="url" dir="ltr" required value="{v("url")}" placeholder="/store أو https://..." style="{_PB_INPUT}"></div>
    <div class="pb-grid2">
      <div><label class="pb-label">الأيقونة</label><select name="icon_name" style="{_PB_INPUT}">{icon_opts}</select></div>
      <div><label class="pb-label">اللون</label><input type="color" name="color" value="{v("color", "#6366f1")}" style="{_PB_INPUT};height:46px;padding:6px"></div>
      <div><label class="pb-label">المكان</label><select name="position" style="{_PB_INPUT}">{pos_opts}</select></div>
      <div><label class="pb-label">يظهر لـ</label><select name="target_users" style="{_PB_INPUT}">{tgt_opts}</select></div>
      <div><label class="pb-label">الترتيب</label><input type="number" name="sort_order" value="{v("sort_order", "0")}" style="{_PB_INPUT}"></div>
    </div>
    <label class="pb-check" style="margin-top:14px"><input type="checkbox" name="is_active"{active}> الزر نشط</label>
    <div style="display:flex;gap:10px;margin-top:16px"><button class="btn" type="submit">حفظ</button>
      <a class="btn btn-ghost" href="/admin/links">إلغاء</a></div>
  </form>
</div>'''


@app.route("/admin/links")
@admin_required
def admin_links_list():
    rows = db().execute("SELECT * FROM custom_links ORDER BY position, sort_order, id").fetchall()
    cards = ""
    for r in rows:
        ok = bool(r["is_active"])
        cards += ('<div class="card pb-admin-card">'
                  '<div class="pb-row"><span class="pb-link-title">' + _pb_icon(r["icon_name"], 18) +
                  '<b>' + esc(r["title"]) + '</b></span>'
                  '<span class="pb-status ' + ("ok" if ok else "off") + '">' + ("نشط" if ok else "معطل") + '</span></div>'
                  '<div class="pb-meta" dir="ltr">' + esc(r["url"]) + '</div>'
                  '<div class="pb-meta">المكان: ' + esc(r["position"]) + ' · الجمهور: ' + esc(r["target_users"]) +
                  ' · الترتيب: ' + str(r["sort_order"]) + '</div>'
                  '<div class="pb-actions">'
                  '<a class="btn btn-sm" href="/admin/links/' + str(r["id"]) + '/edit">تعديل</a>'
                  '<form method="POST" action="/admin/links/' + str(r["id"]) + '/delete" '
                  'onsubmit="return confirm(\'حذف هذا الزر؟\')">'
                  '<button class="btn btn-sm pb-danger" type="submit">حذف</button></form></div></div>')
    if not rows:
        cards = '<div class="card" style="text-align:center;color:var(--muted)">لا توجد أزرار بعد.</div>'
    body = ('<div class="container" style="max-width:900px">'
            '<div class="section-title">الأزرار والروابط</div>'
            '<div class="pb-top"><a href="/admin" class="btn btn-ghost btn-sm">رجوع</a>'
            '<a href="/admin/links/new" class="btn btn-sm">زر جديد</a>'
            '<a href="/admin/pages" class="btn btn-ghost btn-sm">الصفحات</a></div>'
            '<div class="pb-list">' + cards + '</div></div>')
    return page("admin_links", body=body)


def _pb_save_link(lid):
    title = (request.form.get("title") or "").strip()[:120]
    url_raw = (request.form.get("url") or "").strip()
    # أي مخطط آخر غير http/https (مثل javascript: أو data:) يُرفض صراحة
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:", url_raw) and not url_raw.lower().startswith(("http://", "https://")):
        url_raw = "!invalid"
    elif url_raw and not url_raw.startswith(("/", "http", "#")):
        url_raw = "/" + url_raw.lstrip("/")
    url = _pb_safe_url(url_raw)
    icon = request.form.get("icon_name", "link")
    if icon not in ICONS:
        icon = "globe"
    color = _pb_color(request.form.get("color"))
    position = request.form.get("position", "dashboard")
    if position not in PB_POSITIONS:
        position = "dashboard"
    target = request.form.get("target_users", "all")
    if target not in PB_TARGETS:
        target = "all"
    try:
        sort_order = int(request.form.get("sort_order", "0") or 0)
    except ValueError:
        sort_order = 0
    active = 1 if request.form.get("is_active") == "on" else 0
    back = "/admin/links/new" if lid is None else "/admin/links/%d/edit" % lid
    if not title or not url:
        flash("العنوان والرابط مطلوبان (رابط صحيح: /مسار أو https://...).", "error")
        return redirect(back)
    if lid is None:
        db().execute("INSERT INTO custom_links(title, url, icon_name, color, position, target_users, "
                     "is_active, sort_order) VALUES(?,?,?,?,?,?,?,?)",
                     (title, url, icon, color, position, target, active, sort_order))
        action, ctype = "إضافة زر", "feature"
    else:
        db().execute("UPDATE custom_links SET title=?, url=?, icon_name=?, color=?, position=?, "
                     "target_users=?, is_active=?, sort_order=? WHERE id=?",
                     (title, url, icon, color, position, target, active, sort_order, lid))
        action, ctype = "تعديل زر", "update"
    db().commit()
    _lid = lid if lid is not None else db().execute("SELECT last_insert_rowid()").fetchone()[0]
    _pb_sync_block(_lid, position, active, sort_order)
    log_dev_change("%s: %s" % (action, title), "المكان: %s - الجمهور: %s - الرابط: %s" % (
        position, target, url), change_type=ctype, db_changes="custom_links")
    flash("تم حفظ الزر.", "success")
    return redirect(url_for("admin_links_list"))


@app.route("/admin/links/new", methods=["GET", "POST"])
@admin_required
@register_feature("الأزرار والروابط", "custom_links")
def admin_link_new():
    if request.method == "POST":
        return _pb_save_link(None)
    return page("admin_link_form", body=_pb_link_form(None))


@app.route("/admin/links/<int:lid>/edit", methods=["GET", "POST"])
@admin_required
def admin_link_edit(lid):
    row = db().execute("SELECT * FROM custom_links WHERE id=?", (lid,)).fetchone()
    if not row:
        abort(404)
    if request.method == "POST":
        return _pb_save_link(lid)
    return page("admin_link_form", body=_pb_link_form(row))


@app.route("/admin/links/<int:lid>/delete", methods=["POST"])
@admin_required
def admin_link_delete(lid):
    row = db().execute("SELECT * FROM custom_links WHERE id=?", (lid,)).fetchone()
    if not row:
        abort(404)
    db().execute("DELETE FROM custom_links WHERE id=?", (lid,))
    db().commit()
    log_dev_change("حذف زر: " + row["title"], "كان الرابط: " + row["url"], change_type="update",
                   db_changes="custom_links")
    flash("تم حذف الزر.", "success")
    return redirect(url_for("admin_links_list"))


# ---------- تاريخ التطوير (أدمن) ----------
@app.route("/admin/dev-history")
@admin_required
@register_feature("تاريخ التطوير", "dev_history")
def admin_dev_history():
    t = request.args.get("type", "").strip()
    q = request.args.get("q", "").strip()
    sql = "SELECT * FROM dev_history WHERE 1=1"
    params = []
    if t in DEV_TYPES:
        sql += " AND change_type=?"
        params.append(t)
    if q:
        sql += " AND (title LIKE ? OR description LIKE ? OR version LIKE ?)"
        params += ["%" + q + "%"] * 3
    sql += " ORDER BY id DESC LIMIT 200"
    rows = db().execute(sql, params).fetchall()
    type_opts = '<option value="">كل الأنواع</option>' + "".join(
        '<option value="%s"%s>%s</option>' % (k, " selected" if k == t else "", lbl)
        for k, (lbl, _c) in DEV_TYPES.items())
    items = ""
    for r in rows:
        lbl, color = DEV_TYPES.get(r["change_type"], DEV_TYPES["update"])
        exists = bool(r["backup_path"]) and os.path.exists(r["backup_path"])
        dl = ('<a class="btn btn-sm btn-ghost" href="/admin/dev-history/%d/download">تحميل</a>' % r["id"]
              if exists else '<span class="pb-meta">النسخة غير متوفرة</span>')
        rs = ('<form method="POST" action="/admin/dev-history/%d/restore" '
              'onsubmit="return pbConfirmRestore(this)" style="margin:0">'
              '<input type="hidden" name="confirm" value="yes">'
              '<button class="btn btn-sm" type="submit">استعادة هذه النسخة</button></form>' % r["id"]
              if exists else "")
        items += ('<div class="dh-item"><span class="dh-dot" style="background:%s"></span>'
                  '<div class="card dh-card">'
                  '<div class="pb-row"><span class="dh-ver" dir="ltr">%s</span>'
                  '<span class="dh-type" style="color:%s;border-color:%s">%s</span></div>'
                  '<div class="dh-title">%s</div>'
                  '<div class="dh-desc">%s</div>'
                  '<div class="pb-meta">%s%s</div>'
                  '<div class="pb-actions">%s%s</div></div></div>') % (
            color, esc(r["version"]), color, color, esc(lbl), esc(r["title"]),
            esc(r["description"] or ""), esc(r["created_at"]),
            (" · " + esc(r["db_changes"])) if r["db_changes"] else "", dl, rs)
    if not rows:
        items = '<div class="card" style="text-align:center;color:var(--muted)">لا توجد نسخ مسجلة.</div>'
    body = ('<div class="container" style="max-width:820px">'
            '<div class="section-title">تاريخ التطوير</div>'
            '<div class="pb-top"><a href="/admin" class="btn btn-ghost btn-sm">رجوع</a>'
            '<a href="/admin/dev-history/new" class="btn btn-sm">تسجيل نسخة جديدة</a></div>'
            '<form method="GET" class="card pb-filter">'
            '<input name="q" value="' + esc(q) + '" placeholder="بحث بالعنوان أو الوصف أو الإصدار" style="' + _PB_INPUT + '">'
            '<select name="type" style="' + _PB_INPUT + '">' + type_opts + '</select>'
            '<button class="btn btn-sm" type="submit">بحث</button></form>'
            '<div class="dh-timeline">' + items + '</div></div>')
    return page("admin_dev_history", body=body)


@app.route("/admin/dev-history/new", methods=["GET", "POST"])
@admin_required
def admin_dev_new():
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()[:160]
        desc = (request.form.get("description") or "").strip()[:2000]
        ctype = request.form.get("change_type", "update")
        if not title:
            flash("العنوان مطلوب.", "error")
            return redirect(url_for("admin_dev_new"))
        ver = log_dev_change(title, desc, change_type=ctype)
        flash("تم تسجيل النسخة " + ver + ".", "success")
        return redirect(url_for("admin_dev_history"))
    type_opts = "".join('<option value="%s">%s</option>' % (k, lbl) for k, (lbl, _c) in DEV_TYPES.items())
    body = ('<div class="container" style="max-width:640px"><div class="section-title">تسجيل نسخة جديدة</div>'
            '<a href="/admin/dev-history" class="btn btn-ghost btn-sm" style="margin-bottom:16px">رجوع</a>'
            '<form method="POST" class="card" style="padding:18px">'
            '<div style="margin-bottom:12px"><label class="pb-label">العنوان</label>'
            '<input name="title" required style="' + _PB_INPUT + '"></div>'
            '<div style="margin-bottom:12px"><label class="pb-label">الوصف</label>'
            '<textarea name="description" rows="5" style="' + _PB_INPUT + '"></textarea></div>'
            '<div style="margin-bottom:12px"><label class="pb-label">النوع</label>'
            '<select name="change_type" style="' + _PB_INPUT + '">' + type_opts + '</select></div>'
            '<button class="btn" type="submit">حفظ وتسجيل</button></form></div>')
    return page("admin_dev_new", body=body)


@app.route("/admin/dev-history/<int:hid>/download")
@admin_required
def admin_dev_download(hid):
    row = db().execute("SELECT * FROM dev_history WHERE id=?", (hid,)).fetchone()
    if not row or not row["backup_path"] or not os.path.exists(row["backup_path"]):
        abort(404)
    from flask import send_file
    return send_file(row["backup_path"], as_attachment=True,
                     download_name=os.path.basename(row["backup_path"]))


@app.route("/admin/dev-history/<int:hid>/restore", methods=["POST"])
@admin_required
def admin_dev_restore(hid):
    import zipfile
    import shutil
    import sys
    import tempfile
    if request.form.get("confirm") != "yes":
        flash("لم يتم التأكيد، لم تُستعد أي نسخة.", "error")
        return redirect(url_for("admin_dev_history"))
    row = db().execute("SELECT * FROM dev_history WHERE id=?", (hid,)).fetchone()
    if not row or not row["backup_path"] or not os.path.exists(row["backup_path"]):
        abort(404)
    zip_path = row["backup_path"]
    # نسخة أمان من الوضع الحالي قبل أي شيء
    ok_safe, safe_path = _create_zip_backup_internal()
    if not ok_safe:
        flash("فشلت نسخة الأمان قبل الاستعادة، أُلغيت العملية: " + str(safe_path), "error")
        return redirect(url_for("admin_dev_history"))
    tmp = tempfile.mkdtemp(dir=BACKUP_DIR)
    restored_web = False
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            for n in names:
                if n.startswith("/") or ".." in n.replace("\\", "/").split("/"):
                    raise ValueError("مسار غير آمن داخل النسخة: " + n)
            zf.extract("matari.db", tmp)
            if "web.py" in names:
                zf.extract("web.py", tmp)
                restored_web = True
            static_files = [n for n in names if n.startswith("static/") and not n.endswith("/")]
            for n in static_files:
                zf.extract(n, tmp)
        # 1) قاعدة البيانات عبر Backup API (آمن أثناء التشغيل)
        src = sqlite3.connect(os.path.join(tmp, "matari.db"))
        dst = sqlite3.connect(DB_PATH, timeout=30)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        # 2) الملفات الثابتة
        for n in static_files:
            target = os.path.join(BASE_DIR, n)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(os.path.join(tmp, n), target)
        # 3) web.py
        if restored_web:
            shutil.copy2(os.path.join(tmp, "web.py"), os.path.join(BASE_DIR, "web.py"))
    except Exception as e:
        log.exception("[DEV] restore failed")
        flash("فشلت الاستعادة: " + str(e) + ". نسخة الأمان محفوظة: " + os.path.basename(safe_path), "error")
        return redirect(url_for("admin_dev_history"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    # 4) إصلاح المخطط بعد الاستعادة
    try:
        auto_fix_db()
        self_heal_schema()
    except Exception:
        log.exception("[DEV] post-restore heal")
    try:
        audit("dev_restore", "version=%s safe=%s" % (row["version"], os.path.basename(safe_path)))
        log_dev_change("استعادة النسخة " + row["version"], "تمت الاستعادة من النسخة " + row["version"],
                       change_type="hotfix", db_changes="restore")
    except Exception:
        log.exception("[DEV] log after restore")
    if restored_web and not os.environ.get("RENDER"):
        def _restart():
            time.sleep(2)
            os.execl(sys.executable, sys.executable, os.path.join(BASE_DIR, "web.py"))
        threading.Thread(target=_restart, daemon=True).start()
        flash("تمت الاستعادة، وجاري إعادة تشغيل السيرفر.", "success")
    elif restored_web:
        flash("تمت الاستعادة. أعد تشغيل الخدمة من لوحة Render لتفعيل web.py.", "success")
    else:
        flash("تمت استعادة قاعدة البيانات والملفات الثابتة.", "success")
    return redirect(url_for("admin_dev_history"))


# ---------- تحسين السلاسة (CSS + JS) ----------
SMOOTH_CSS = """
@view-transition { navigation: auto; }
::view-transition-old(root), ::view-transition-new(root) {
  animation-duration: .22s; animation-timing-function: cubic-bezier(.2,.7,.2,1);
}
@keyframes mtPageIn { from { opacity: 0; transform: translate3d(0,8px,0); } to { opacity: 1; transform: translate3d(0,0,0); } }
body.mt-ready .container { animation: mtPageIn .28s cubic-bezier(.2,.7,.2,1) both; }
html { -webkit-tap-highlight-color: transparent; scroll-behavior: smooth; }
a, button, .btn { -webkit-tap-highlight-color: transparent; }
img { content-visibility: auto; }
.pb-grid { display:grid; grid-template-columns: repeat(auto-fill, minmax(150px,1fr)); gap:12px; }
.pb-grid2 { display:grid; grid-template-columns: repeat(auto-fit, minmax(180px,1fr)); gap:12px; }
.pb-card { display:flex; flex-direction:column; align-items:center; gap:10px; padding:18px 12px;
  border-radius:18px; text-decoration:none; color:var(--text); text-align:center;
  background: linear-gradient(145deg, var(--card), var(--card2)); border:1px solid var(--border);
  border-top:3px solid var(--pb-c, #6366f1); box-shadow:0 6px 18px rgba(0,0,0,.2);
  transform: translate3d(0,0,0); transition: transform .2s ease, box-shadow .2s ease; }
.pb-card:hover, .pb-card:focus-visible { transform: translate3d(0,-3px,0); box-shadow:0 12px 26px rgba(0,0,0,.3); }
.pb-card:active { transform: translate3d(0,0,0) scale(.98); }
.pb-ico { width:44px; height:44px; border-radius:14px; display:flex; align-items:center; justify-content:center;
  background: color-mix(in srgb, var(--pb-c, #6366f1) 18%, transparent); color: var(--pb-c, #6366f1); }
.pb-title { font-weight:800; font-size:14px; }
.pb-nav-wrap { display:flex; align-items:center; gap:6px; }
.pb-nav { display:inline-flex; align-items:center; gap:6px; padding:7px 10px; border-radius:12px; text-decoration:none;
  color:var(--text); background:var(--card); border:1px solid var(--border); font-size:12px; font-weight:700;
  transition: transform .15s ease, background .15s ease; }
.pb-nav:hover { transform: translate3d(0,-1px,0); }
@media (max-width:600px) { .pb-nav span { display:none; } }
.pb-top { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:14px; }
.pb-list { display:grid; gap:12px; }
.pb-admin-card { padding:14px; }
.pb-row { display:flex; align-items:center; justify-content:space-between; gap:10px; flex-wrap:wrap; }
.pb-meta { font-size:12px; color:var(--muted); margin-top:6px; word-break:break-all; }
.pb-actions { display:flex; gap:8px; flex-wrap:wrap; margin-top:12px; align-items:center; }
.pb-status { font-size:11px; font-weight:800; padding:3px 10px; border-radius:20px; }
.pb-status.ok { background:rgba(16,185,129,.15); color:#10b981; }
.pb-status.off { background:rgba(239,68,68,.15); color:#ef4444; }
.pb-danger { background:rgba(239,68,68,.15); color:#ef4444; border:1px solid rgba(239,68,68,.35); }
.pb-label { font-size:12px; color:var(--muted); font-weight:800; display:block; margin-bottom:6px; }
.pb-check { display:flex; align-items:center; gap:8px; font-size:14px; font-weight:700; }
.pb-filter { display:grid; grid-template-columns: 1fr 200px auto; gap:10px; padding:14px; margin-bottom:16px; }
@media (max-width:640px) { .pb-filter { grid-template-columns:1fr; } }
.pb-toolbar { display:flex; flex-wrap:wrap; gap:6px; margin-bottom:8px; }
.pb-tb { min-width:38px; height:36px; padding:0 10px; border-radius:10px; cursor:pointer; background:var(--bg2);
  color:var(--text); border:1px solid var(--border); display:inline-flex; align-items:center; justify-content:center; gap:4px; font-family:inherit; }
.pb-tb:hover { background:var(--card2); }
.pb-editor { min-height:260px; background:var(--bg2); border:1px solid var(--border); border-radius:12px; padding:14px;
  outline:none; line-height:1.9; overflow:auto; }
.pb-html { width:100%; min-height:260px; background:var(--bg2); color:var(--text); border:1px solid var(--border);
  border-radius:12px; padding:12px; font-family:monospace; box-sizing:border-box; }
.pb-modal { display:none; position:fixed; inset:0; z-index:99990; background:rgba(0,0,0,.6); align-items:center;
  justify-content:center; padding:14px; backdrop-filter: blur(6px); -webkit-backdrop-filter: blur(6px); }
.pb-modal-box { width:min(900px,100%); background:var(--card); border:1px solid var(--border); border-radius:18px; padding:14px; }
.pb-article { padding:22px; line-height:1.9; }
.pb-h1 { font-size:24px; font-weight:900; margin:0 0 14px; }
.pb-article img { max-width:100%; height:auto; border-radius:12px; }
.dh-timeline { position:relative; padding-right:22px; }
.dh-timeline::before { content:""; position:absolute; right:7px; top:6px; bottom:6px; width:2px; background:var(--border); }
.dh-item { position:relative; margin-bottom:14px; }
.dh-dot { position:absolute; right:-22px; top:20px; width:14px; height:14px; border-radius:50%; box-shadow:0 0 0 4px var(--bg); }
.dh-card { padding:14px; }
.dh-ver { font-family:monospace; font-weight:900; font-size:13px; color:var(--primary2); }
.dh-type { font-size:11px; font-weight:800; padding:3px 10px; border-radius:20px; border:1px solid; }
.dh-title { font-weight:900; font-size:15px; margin-top:8px; }
.dh-desc { font-size:13px; color:var(--muted); line-height:1.8; margin-top:4px; white-space:pre-wrap; }
@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  body.mt-ready .container, .pb-card, .pb-nav, ::view-transition-old(root), ::view-transition-new(root) {
    animation: none !important; transition: none !important; }
}
"""

SMOOTH_JS = """
(function(){
  document.body && document.body.classList.add('mt-ready');
  var seen = {};
  var SKIP = /\\/logout|\\/admin|\\/buy\\/|\\/deposit|\\/my\\/delete|\\/transfer|\\/p\\/[^\\/]*\\/edit/;
  function internal(a){
    if(!a || !a.href) return false;
    try { var u = new URL(a.href); } catch(e){ return false; }
    if(u.origin !== location.origin || a.target || a.hasAttribute('download')) return false;
    if(u.pathname === location.pathname) return false;
    if(SKIP.test(u.pathname)) return false;
    return true;
  }
  function prefetch(a){
    if(!internal(a) || seen[a.href]) return;
    seen[a.href] = 1;
    var l = document.createElement('link');
    l.rel = 'prefetch'; l.href = a.href; l.as = 'document';
    document.head.appendChild(l);
  }
  function near(e){ return e.target && e.target.closest ? e.target.closest('a') : null; }
  document.addEventListener('pointerover', function(e){ prefetch(near(e)); }, {passive:true});
  document.addEventListener('touchstart', function(e){ prefetch(near(e)); }, {passive:true});
  window.pbConfirmRestore = function(f){
    return confirm('سيتم استبدال البيانات والملفات الحالية بهذه النسخة. نسخة أمان من الوضع الحالي ستُؤخذ أولاً. متابعة؟');
  };
})();
"""


# ============================================================
# تطوير: تنظيف عام للزوار + الصفحات الثابتة + بلوكات لوحة المستخدم
# ============================================================
STATIC_PAGES = [
    ("/about", "عن المتجر"), ("/referral", "الإحالات"), ("/vip", "VIP"),
    ("/transfer", "التحويل"), ("/sell", "بيع الأرقام"), ("/store", "المتجر"),
    ("/deposit", "الشحن"), ("/support", "الدعم الفني"),
]
DASH_BLOCK_TYPES = (("link", "زر"), ("text", "نص"), ("banner", "بانر"), ("html", "HTML مخصص"))
DASH_COLUMNS = (("full", "عرض كامل"), ("left", "العمود الأيسر"), ("right", "العمود الأيمن"))

_PB_PUBLIC_TAGS = _PB_ALLOWED_TAGS | {
    "section", "article", "header", "footer", "nav", "main", "aside", "table", "thead",
    "tbody", "tfoot", "tr", "td", "th", "figure", "figcaption", "sup", "sub", "mark",
    "time", "abbr", "center"}
_PB_PUBLIC_ATTRS = {"href", "src", "title", "alt", "width", "height", "class", "id",
                    "style", "colspan", "rowspan"}
_PB_CSS_BAD = re.compile(
    r"expression\s*\(|javascript\s*:|vbscript\s*:|@import|behavior\s*:|-moz-binding|"
    r"url\s*\(\s*['\"]?\s*(javascript|data|vbscript)\s*:", re.IGNORECASE)


class _PBPublicSanitizer(_PBHTMLParser):
    """تنظيف للزوار: يسمح بالتنسيق (style و class و <style>) ويمنع السكربتات والأحداث والروابط الخطرة."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.drop = 0
        self.in_style = False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "style":
            if not self.drop:
                self.in_style = True
                self.out.append("<style>")
            return
        if tag in _PB_DROP_TAGS:
            if tag not in _PB_VOID_TAGS:
                self.drop += 1
            return
        if self.drop or tag not in _PB_PUBLIC_TAGS:
            return
        parts = []
        for key, val in attrs:
            key = (key or "").lower()
            val = val or ""
            if key not in _PB_PUBLIC_ATTRS or key.startswith("on"):
                continue
            if key in ("href", "src"):
                url = _pb_safe_url(val)
                if url is None or (key == "src" and not (url.startswith("http") or url.startswith("/"))):
                    continue
                parts.append(' %s="%s"' % (key, _html_mod.escape(url, quote=True)))
                if key == "href" and url.lower().startswith("http"):
                    parts.append(' target="_blank" rel="noopener noreferrer"')
            elif key == "style":
                if _PB_CSS_BAD.search(val):
                    continue
                parts.append(' style="%s"' % _html_mod.escape(val, quote=True))
            else:
                parts.append(' %s="%s"' % (key, _html_mod.escape(val, quote=True)))
        self.out.append("<%s%s>" % (tag, "".join(parts)))

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "style":
            if self.in_style:
                self.in_style = False
                self.out.append("</style>")
            return
        if tag in _PB_DROP_TAGS:
            if tag not in _PB_VOID_TAGS and self.drop:
                self.drop -= 1
            return
        if self.drop or tag not in _PB_PUBLIC_TAGS or tag in _PB_VOID_TAGS:
            return
        self.out.append("</%s>" % tag)

    def handle_data(self, data):
        if self.drop:
            return
        if self.in_style:
            css = re.sub(r"@import[^;]*;?", "", data, flags=re.IGNORECASE)
            css = _PB_CSS_BAD.sub("", css)
            self.out.append(css.replace("</", "<\\/"))
            return
        self.out.append(_html_mod.escape(data, quote=False))


def sanitize_html_public(raw):
    parser = _PBPublicSanitizer()
    parser.feed(str(raw or "")[:PB_MAX_HTML * 2])
    parser.close()
    return "".join(parser.out)


_CAPTURE = threading.local()

# الصفحات الثابتة ومعرّف دالة العرض الخاصة بكل صفحة
STATIC_PAGE_ENDPOINTS = {
    "/about": "about_page", "/referral": "referral", "/vip": "vip_page",
    "/transfer": "transfer", "/sell": "sell", "/store": "store",
    "/deposit": "deposit", "/support": "support",
}

# نسخ الـ HTML الأصلي للصفحات الثابتة التي محتواها ثابت (لا يتغير حسب المستخدم).
# تُملأ من الكود الفعلي للصفحة. الصفحات غير الموجودة هنا تُلتقط تلقائياً من الكود الحالي.
STATIC_PAGE_DEFAULTS = {
    # نسخة الأصل من الكود (صفحة ثابتة المحتوى، لا تعتمد على بيانات المستخدم)
    "/about": '\n    <div class="container" style="max-width: 700px; padding-top: 20px;">\n      <div style="text-align: center; margin-bottom: 24px;">\n        <div style="font-size: 24px; font-weight: 900; color: var(--text); margin-bottom: 6px;">دليل استخدام الموقع</div>\n        <div style="font-size: 13px; color: var(--muted);">كل ما تحتاج معرفته عن أقسام MATARI STORE</div>\n      </div>\n    </div>\n    <div style="background: linear-gradient(145deg, var(--card), var(--card2)); border: 1px solid var(--border); border-radius: 16px; padding: 16px; margin-bottom: 12px; display: flex; align-items: flex-start; gap: 14px; border-right: 4px solid #6366f1; transition: all 0.3s;">\n          <div style="width: 44px; height: 44px; border-radius: 12px; background: #6366f115; display: flex; align-items: center; justify-content: center; flex-shrink: 0; border: 1px solid #6366f130;">\n            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#6366f1" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>\n          </div>\n          <div style="flex: 1;">\n            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px;">\n              <span style="background: #6366f120; color: #6366f1; font-size: 10px; font-weight: 900; padding: 2px 8px; border-radius: 20px;">01</span>\n              <div style="font-weight: 800; font-size: 15px; color: var(--text);">الرئيسية</div>\n            </div>\n            <div style="font-size: 13px; color: var(--muted); line-height: 1.6;">الصفحة الرئيسية التي تعرض أحدث الأرقام المتاحة وأهم الميزات.</div>\n          </div>\n        </div>\n        <div style="background: linear-gradient(145deg, var(--card), var(--card2)); border: 1px solid var(--border); border-radius: 16px; padding: 16px; margin-bottom: 12px; display: flex; align-items: flex-start; gap: 14px; border-right: 4px solid #818cf8; transition: all 0.3s;">\n          <div style="width: 44px; height: 44px; border-radius: 12px; background: #818cf815; display: flex; align-items: center; justify-content: center; flex-shrink: 0; border: 1px solid #818cf830;">\n            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#818cf8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/></svg>\n          </div>\n          <div style="flex: 1;">\n            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px;">\n              <span style="background: #818cf820; color: #818cf8; font-size: 10px; font-weight: 900; padding: 2px 8px; border-radius: 20px;">02</span>\n              <div style="font-weight: 800; font-size: 15px; color: var(--text);">المتجر</div>\n            </div>\n            <div style="font-size: 13px; color: var(--muted); line-height: 1.6;">تصفح جميع الأرقام المتاحة للبيع مقسمة حسب المنصة (واتساب/تيليجرام) والدولة.</div>\n          </div>\n        </div>\n        <div style="background: linear-gradient(145deg, var(--card), var(--card2)); border: 1px solid var(--border); border-radius: 16px; padding: 16px; margin-bottom: 12px; display: flex; align-items: flex-start; gap: 14px; border-right: 4px solid #10b981; transition: all 0.3s;">\n          <div style="width: 44px; height: 44px; border-radius: 12px; background: #10b98115; display: flex; align-items: center; justify-content: center; flex-shrink: 0; border: 1px solid #10b98130;">\n            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="21" r="1"/><circle cx="20" cy="21" r="1"/><path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6"/></svg>\n          </div>\n          <div style="flex: 1;">\n            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px;">\n              <span style="background: #10b98120; color: #10b981; font-size: 10px; font-weight: 900; padding: 2px 8px; border-radius: 20px;">03</span>\n              <div style="font-weight: 800; font-size: 15px; color: var(--text);">الشراء</div>\n            </div>\n            <div style="font-size: 13px; color: var(--muted); line-height: 1.6;">اختر الرقم الذي تريده واضغط شراء ليتم خصم السعر من رصيدك فوراً.</div>\n          </div>\n        </div>\n        <div style="background: linear-gradient(145deg, var(--card), var(--card2)); border: 1px solid var(--border); border-radius: 16px; padding: 16px; margin-bottom: 12px; display: flex; align-items: flex-start; gap: 14px; border-right: 4px solid #06b6d4; transition: all 0.3s;">\n          <div style="width: 44px; height: 44px; border-radius: 12px; background: #06b6d415; display: flex; align-items: center; justify-content: center; flex-shrink: 0; border: 1px solid #06b6d430;">\n            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#06b6d4" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>\n          </div>\n          <div style="flex: 1;">\n            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px;">\n              <span style="background: #06b6d420; color: #06b6d4; font-size: 10px; font-weight: 900; padding: 2px 8px; border-radius: 20px;">04</span>\n              <div style="font-weight: 800; font-size: 15px; color: var(--text);">حسابي</div>\n            </div>\n            <div style="font-size: 13px; color: var(--muted); line-height: 1.6;">لوحة التحكم الخاصة بك حيث ترى رصيدك وأرقامك المشتراة وإحصائياتك.</div>\n          </div>\n        </div>\n        <div style="background: linear-gradient(145deg, var(--card), var(--card2)); border: 1px solid var(--border); border-radius: 16px; padding: 16px; margin-bottom: 12px; display: flex; align-items: flex-start; gap: 14px; border-right: 4px solid #f59e0b; transition: all 0.3s;">\n          <div style="width: 44px; height: 44px; border-radius: 12px; background: #f59e0b15; display: flex; align-items: center; justify-content: center; flex-shrink: 0; border: 1px solid #f59e0b30;">\n            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12V7H5a2 2 0 0 1 0-4h14v4"/><path d="M3 5v14a2 2 0 0 0 2 2h16v-5"/><path d="M18 12a2 2 0 0 0 0 4h4v-4z"/></svg>\n          </div>\n          <div style="flex: 1;">\n            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px;">\n              <span style="background: #f59e0b20; color: #f59e0b; font-size: 10px; font-weight: 900; padding: 2px 8px; border-radius: 20px;">05</span>\n              <div style="font-weight: 800; font-size: 15px; color: var(--text);">شحن الرصيد</div>\n            </div>\n            <div style="font-size: 13px; color: var(--muted); line-height: 1.6;">أضف رصيد لحسابك باستخدام فودافون كاش، جيب، ون كاش، بينانس، أو كود شحن.</div>\n          </div>\n        </div>\n        <div style="background: linear-gradient(145deg, var(--card), var(--card2)); border: 1px solid var(--border); border-radius: 16px; padding: 16px; margin-bottom: 12px; display: flex; align-items: flex-start; gap: 14px; border-right: 4px solid #8b5cf6; transition: all 0.3s;">\n          <div style="width: 44px; height: 44px; border-radius: 12px; background: #8b5cf615; display: flex; align-items: center; justify-content: center; flex-shrink: 0; border: 1px solid #8b5cf630;">\n            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#8b5cf6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>\n          </div>\n          <div style="flex: 1;">\n            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px;">\n              <span style="background: #8b5cf620; color: #8b5cf6; font-size: 10px; font-weight: 900; padding: 2px 8px; border-radius: 20px;">06</span>\n              <div style="font-weight: 800; font-size: 15px; color: var(--text);">تحويل رصيد</div>\n            </div>\n            <div style="font-size: 13px; color: var(--muted); line-height: 1.6;">أرسل رصيد لأي صديق باستخدام الآيدي الخاص به داخل الموقع.</div>\n          </div>\n        </div>\n        <div style="background: linear-gradient(145deg, var(--card), var(--card2)); border: 1px solid var(--border); border-radius: 16px; padding: 16px; margin-bottom: 12px; display: flex; align-items: flex-start; gap: 14px; border-right: 4px solid #f97316; transition: all 0.3s;">\n          <div style="width: 44px; height: 44px; border-radius: 12px; background: #f9731615; display: flex; align-items: center; justify-content: center; flex-shrink: 0; border: 1px solid #f9731630;">\n            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#f97316" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>\n          </div>\n          <div style="flex: 1;">\n            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px;">\n              <span style="background: #f9731620; color: #f97316; font-size: 10px; font-weight: 900; padding: 2px 8px; border-radius: 20px;">07</span>\n              <div style="font-weight: 800; font-size: 15px; color: var(--text);">مستويات VIP</div>\n            </div>\n            <div style="font-size: 13px; color: var(--muted); line-height: 1.6;">كلما اشتريت أكثر، ترتفع رتبتك وتحصل على خصومات حصرية تلقائية.</div>\n          </div>\n        </div>\n        <div style="background: linear-gradient(145deg, var(--card), var(--card2)); border: 1px solid var(--border); border-radius: 16px; padding: 16px; margin-bottom: 12px; display: flex; align-items: flex-start; gap: 14px; border-right: 4px solid #ec4899; transition: all 0.3s;">\n          <div style="width: 44px; height: 44px; border-radius: 12px; background: #ec489915; display: flex; align-items: center; justify-content: center; flex-shrink: 0; border: 1px solid #ec489930;">\n            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#ec4899" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>\n          </div>\n          <div style="flex: 1;">\n            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px;">\n              <span style="background: #ec489920; color: #ec4899; font-size: 10px; font-weight: 900; padding: 2px 8px; border-radius: 20px;">08</span>\n              <div style="font-weight: 800; font-size: 15px; color: var(--text);">الإحالات</div>\n            </div>\n            <div style="font-size: 13px; color: var(--muted); line-height: 1.6;">شارك رابطك مع أصدقائك واربح مكافأة مالية عند شراء أول رقم.</div>\n          </div>\n        </div>\n        <div style="background: linear-gradient(145deg, var(--card), var(--card2)); border: 1px solid var(--border); border-radius: 16px; padding: 16px; margin-bottom: 12px; display: flex; align-items: flex-start; gap: 14px; border-right: 4px solid #14b8a6; transition: all 0.3s;">\n          <div style="width: 44px; height: 44px; border-radius: 12px; background: #14b8a615; display: flex; align-items: center; justify-content: center; flex-shrink: 0; border: 1px solid #14b8a630;">\n            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#14b8a6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="2" width="14" height="20" rx="2" ry="2"/><line x1="12" y1="18" x2="12.01" y2="18"/></svg>\n          </div>\n          <div style="flex: 1;">\n            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px;">\n              <span style="background: #14b8a620; color: #14b8a6; font-size: 10px; font-weight: 900; padding: 2px 8px; border-radius: 20px;">09</span>\n              <div style="font-weight: 800; font-size: 15px; color: var(--text);">أرقامي</div>\n            </div>\n            <div style="font-size: 13px; color: var(--muted); line-height: 1.6;">جميع الأرقام التي اشتريتها موجودة هنا، مع إمكانية سحب الكود في أي وقت.</div>\n          </div>\n        </div>\n        <div style="background: linear-gradient(145deg, var(--card), var(--card2)); border: 1px solid var(--border); border-radius: 16px; padding: 16px; margin-bottom: 12px; display: flex; align-items: flex-start; gap: 14px; border-right: 4px solid #ef4444; transition: all 0.3s;">\n          <div style="width: 44px; height: 44px; border-radius: 12px; background: #ef444415; display: flex; align-items: center; justify-content: center; flex-shrink: 0; border: 1px solid #ef444430;">\n            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg>\n          </div>\n          <div style="flex: 1;">\n            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px;">\n              <span style="background: #ef444420; color: #ef4444; font-size: 10px; font-weight: 900; padding: 2px 8px; border-radius: 20px;">10</span>\n              <div style="font-weight: 800; font-size: 15px; color: var(--text);">سحب الكود</div>\n            </div>\n            <div style="font-size: 13px; color: var(--muted); line-height: 1.6;">اضغط على الرقم لتدخل صفحته وتضغط زر سحب الكود ليظهر لك فوراً.</div>\n          </div>\n        </div>\n        <div style="background: linear-gradient(145deg, var(--card), var(--card2)); border: 1px solid var(--border); border-radius: 16px; padding: 16px; margin-bottom: 12px; display: flex; align-items: flex-start; gap: 14px; border-right: 4px solid #84cc16; transition: all 0.3s;">\n          <div style="width: 44px; height: 44px; border-radius: 12px; background: #84cc1615; display: flex; align-items: center; justify-content: center; flex-shrink: 0; border: 1px solid #84cc1630;">\n            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#84cc16" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>\n          </div>\n          <div style="flex: 1;">\n            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px;">\n              <span style="background: #84cc1620; color: #84cc16; font-size: 10px; font-weight: 900; padding: 2px 8px; border-radius: 20px;">11</span>\n              <div style="font-weight: 800; font-size: 15px; color: var(--text);">الحماية</div>\n            </div>\n            <div style="font-size: 13px; color: var(--muted); line-height: 1.6;">نضمن لك حماية أرقامك وعدم استرجاعها من قبل البائع الأصلي.</div>\n          </div>\n        </div>\n        <div style="background: linear-gradient(145deg, var(--card), var(--card2)); border: 1px solid var(--border); border-radius: 16px; padding: 16px; margin-bottom: 12px; display: flex; align-items: flex-start; gap: 14px; border-right: 4px solid #a855f7; transition: all 0.3s;">\n          <div style="width: 44px; height: 44px; border-radius: 12px; background: #a855f715; display: flex; align-items: center; justify-content: center; flex-shrink: 0; border: 1px solid #a855f730;">\n            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#a855f7" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 9a3 3 0 0 1 0 6v2a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-2a3 3 0 0 1 0-6V7a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2z"/></svg>\n          </div>\n          <div style="flex: 1;">\n            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px;">\n              <span style="background: #a855f720; color: #a855f7; font-size: 10px; font-weight: 900; padding: 2px 8px; border-radius: 20px;">12</span>\n              <div style="font-weight: 800; font-size: 15px; color: var(--text);">الدعم الفني</div>\n            </div>\n            <div style="font-size: 13px; color: var(--muted); line-height: 1.6;">إذا واجهت أي مشكلة، افتح تذكرة جديدة وسيرد عليك فريق الدعم.</div>\n          </div>\n        </div>\n        <div style="background: linear-gradient(145deg, var(--card), var(--card2)); border: 1px solid var(--border); border-radius: 16px; padding: 16px; margin-bottom: 12px; display: flex; align-items: flex-start; gap: 14px; border-right: 4px solid #eab308; transition: all 0.3s;">\n          <div style="width: 44px; height: 44px; border-radius: 12px; background: #eab30815; display: flex; align-items: center; justify-content: center; flex-shrink: 0; border: 1px solid #eab30830;">\n            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#eab308" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 12 20 22 4 22 4 12"/><rect x="2" y="7" width="20" height="5"/><line x1="12" y1="22" x2="12" y2="7"/><path d="M12 7H7.5a2.5 2.5 0 0 1 0-5C11 2 12 7 12 7z"/><path d="M12 7h4.5a2.5 2.5 0 0 0 0-5C13 2 12 7 12 7z"/></svg>\n          </div>\n          <div style="flex: 1;">\n            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px;">\n              <span style="background: #eab30820; color: #eab308; font-size: 10px; font-weight: 900; padding: 2px 8px; border-radius: 20px;">13</span>\n              <div style="font-weight: 800; font-size: 15px; color: var(--text);">المكافأة اليومية</div>\n            </div>\n            <div style="font-size: 13px; color: var(--muted); line-height: 1.6;">احصل على مكافأة مجانية كل 24 ساعة بمجرد الضغط على زر الاستلام.</div>\n          </div>\n        </div>\n        <div style="background: linear-gradient(145deg, var(--card), var(--card2)); border: 1px solid var(--border); border-radius: 16px; padding: 16px; margin-bottom: 12px; display: flex; align-items: flex-start; gap: 14px; border-right: 4px solid #3b82f6; transition: all 0.3s;">\n          <div style="width: 44px; height: 44px; border-radius: 12px; background: #3b82f615; display: flex; align-items: center; justify-content: center; flex-shrink: 0; border: 1px solid #3b82f630;">\n            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>\n          </div>\n          <div style="flex: 1;">\n            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px;">\n              <span style="background: #3b82f620; color: #3b82f6; font-size: 10px; font-weight: 900; padding: 2px 8px; border-radius: 20px;">14</span>\n              <div style="font-weight: 800; font-size: 15px; color: var(--text);">الإشعارات</div>\n            </div>\n            <div style="font-size: 13px; color: var(--muted); line-height: 1.6;">ستصلك إشعارات فورية عند وصول الكود أو عند إتمام أي عملية بنجاح.</div>\n          </div>\n        </div>\n        <div style="background: linear-gradient(145deg, var(--card), var(--card2)); border: 1px solid var(--border); border-radius: 16px; padding: 16px; margin-bottom: 12px; display: flex; align-items: flex-start; gap: 14px; border-right: 4px solid #6b7280; transition: all 0.3s;">\n          <div style="width: 44px; height: 44px; border-radius: 12px; background: #6b728015; display: flex; align-items: center; justify-content: center; flex-shrink: 0; border: 1px solid #6b728030;">\n            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#6b7280" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>\n          </div>\n          <div style="flex: 1;">\n            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px;">\n              <span style="background: #6b728020; color: #6b7280; font-size: 10px; font-weight: 900; padding: 2px 8px; border-radius: 20px;">15</span>\n              <div style="font-weight: 800; font-size: 15px; color: var(--text);">البحث</div>\n            </div>\n            <div style="font-size: 13px; color: var(--muted); line-height: 1.6;">استخدم مربع البحث للعثور على رقم أو دولة معينة بسرعة.</div>\n          </div>\n        </div>\n        <div style="background: linear-gradient(145deg, var(--card), var(--card2)); border: 1px solid var(--border); border-radius: 16px; padding: 16px; margin-bottom: 12px; display: flex; align-items: flex-start; gap: 14px; border-right: 4px solid #059669; transition: all 0.3s;">\n          <div style="width: 44px; height: 44px; border-radius: 12px; background: #05966915; display: flex; align-items: center; justify-content: center; flex-shrink: 0; border: 1px solid #05966930;">\n            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#059669" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>\n          </div>\n          <div style="flex: 1;">\n            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px;">\n              <span style="background: #05966920; color: #059669; font-size: 10px; font-weight: 900; padding: 2px 8px; border-radius: 20px;">16</span>\n              <div style="font-weight: 800; font-size: 15px; color: var(--text);">الأمان</div>\n            </div>\n            <div style="font-size: 13px; color: var(--muted); line-height: 1.6;">جميع بياناتك مشفرة ومحمية بأعلى معايير الأمان في الموقع.</div>\n          </div>\n        </div>\n        \n    ',
}


def _capture_static_body(route):
    """يشغّل دالة عرض الصفحة الأصلية (بدون التخصيص) ويرجع جزء الـ body فقط."""
    endpoint = STATIC_PAGE_ENDPOINTS.get(route)
    if not endpoint or route == "/support":  # /support تنشئ تذكرة عند فتحها، لذلك لا نلتقطها
        return ""
    fn = app.view_functions.get(endpoint)
    if fn is None:
        return ""
    _CAPTURE.on = True
    _CAPTURE.skip = True
    try:
        rv = fn()
    except Exception:
        log.exception("[STATIC] تعذر التقاط الصفحة %s", route)
        return ""
    finally:
        _CAPTURE.on = False
        _CAPTURE.skip = False
    return rv if isinstance(rv, str) else ""


def _static_default(route):
    """الأصل الذي يظهر في مربع التعديل: القاموس أولاً، ثم الالتقاط من الكود الحالي."""
    if route in STATIC_PAGE_DEFAULTS:
        return STATIC_PAGE_DEFAULTS[route]
    return _capture_static_body(route)


def _static_override(route):
    """يرجع صفحة التخصيص إن وُجدت (للطلبات GET فقط)، وإلا None."""
    if request.method != "GET" or getattr(_CAPTURE, "skip", False):
        return None
    try:
        row = db().execute("SELECT custom_html FROM static_pages_overrides WHERE route=? AND is_active=1",
                           (route,)).fetchone()
    except sqlite3.Error:
        return None
    if not row:
        return None
    return page("static_override", body=sanitize_html_public(row["custom_html"]))


# ---------- معاينة الصفحة المخصصة للأدمن ----------
@app.route("/p/preview/<slug>")
@admin_required
def preview_custom_page(slug):
    row = db().execute("SELECT * FROM custom_pages WHERE slug=?", (slug,)).fetchone()
    if not row:
        abort(404)
    banner = ('<div class="card" style="margin-bottom:12px;border:1px solid rgba(245,158,11,.4);'
              'background:rgba(245,158,11,.08);display:flex;justify-content:space-between;align-items:center;'
              'gap:10px;flex-wrap:wrap"><b style="color:#f59e0b">وضع المعاينة - غير محفوظ للزوار</b>'
              '<a class="btn btn-sm btn-ghost" href="/admin/pages/' + str(row["id"]) + '/edit">رجوع للتعديل</a></div>')
    body = ('<div class="container" style="max-width:820px">' + banner +
            '<div class="card pb-article"><h1 class="pb-h1">' + esc(row["title"]) + '</h1>' +
            sanitize_html_public(row["content_html"]) + '</div></div>')
    return page("custom_page_preview", body=body)


# ---------- الصفحات الثابتة: قائمة وتعديل ----------
def _sp_get(idx):
    if idx < 0 or idx >= len(STATIC_PAGES):
        abort(404)
    return STATIC_PAGES[idx]


@app.route("/admin/static-pages")
@admin_required
def admin_static_pages():
    ov = {r["route"]: r for r in db().execute("SELECT * FROM static_pages_overrides").fetchall()}
    cards = ""
    for i, (route, label) in enumerate(STATIC_PAGES):
        r = ov.get(route)
        custom = bool(r and r["is_active"])
        reset = ('<form method="POST" action="/admin/static-pages/%d/reset" '
                 'onsubmit="return confirm(\'إعادة الصفحة للنسخة الأصلية؟\')">'
                 '<button class="btn btn-sm pb-danger" type="submit">مسح التخصيص</button></form>' % i) if custom else ""
        cards += ('<div class="card pb-admin-card"><div class="pb-row"><b>' + esc(label) + '</b>'
                  '<span class="pb-status ' + ("ok" if custom else "off") + '">' +
                  ("مخصصة" if custom else "الأصلية") + '</span></div>'
                  '<div class="pb-meta" dir="ltr">' + esc(route) + '</div>'
                  '<div class="pb-actions">'
                  '<a class="btn btn-sm btn-ghost" href="' + esc(route) + '" target="_blank" rel="noopener">معاينة الموقع</a>'
                  '<a class="btn btn-sm" href="/admin/static-pages/' + str(i) + '/edit">تعديل</a>' + reset +
                  '</div></div>')
    body = ('<div class="container" style="max-width:900px"><div class="section-title">الصفحات الثابتة</div>'
            '<div class="pb-top"><a href="/admin" class="btn btn-ghost btn-sm">رجوع</a></div>'
            '<div class="card" style="margin-bottom:12px;font-size:13px;color:var(--muted);line-height:1.8">'
            'يمكنك استبدال محتوى أي صفحة من الموقع بتصميمك الخاص. التخصيص يحل محل الصفحة الأصلية مؤقتاً، '
            'وزر "مسح التخصيص" يعيدها كما كانت.</div>'
            '<div class="pb-list">' + cards + '</div></div>')
    return page("admin_static_pages", body=body)


@app.route("/admin/static-pages/<int:idx>/edit", methods=["GET", "POST"])
@admin_required
def admin_static_edit(idx):
    route, label = _sp_get(idx)
    back = "/admin/static-pages/%d/edit" % idx
    if request.method == "POST":
        raw = request.form.get("custom_html", "")
        if not raw.strip():
            flash("المحتوى فارغ. استخدم مسح التخصيص للعودة للصفحة الأصلية.", "error")
            return redirect(back)
        if len(raw) > 300000:
            flash("المحتوى كبير جداً (الحد 300 ألف حرف).", "error")
            return redirect(back)
        db().execute("INSERT INTO static_pages_overrides(route, custom_html, is_active, updated_by, updated_at) "
                     "VALUES(?,?,1,?,datetime('now')) ON CONFLICT(route) DO UPDATE SET "
                     "custom_html=excluded.custom_html, is_active=1, updated_by=excluded.updated_by, "
                     "updated_at=excluded.updated_at", (route, raw, session.get("user_id")))
        db().commit()
        log_dev_change("تعديل صفحة ثابتة: " + label, "المسار: " + route, change_type="update",
                       db_changes="static_pages_overrides")
        flash("تم حفظ التخصيص.", "success")
        return redirect(url_for("admin_static_pages"))
    r = db().execute("SELECT custom_html FROM static_pages_overrides WHERE route=?", (route,)).fetchone()
    seed = esc(r["custom_html"]) if r else esc(_static_default(route))
    body = ('<div class="container" style="max-width:900px"><div class="section-title">تعديل: ' + esc(label) + '</div>'
            '<a href="/admin/static-pages" class="btn btn-ghost btn-sm" style="margin-bottom:16px">رجوع</a>'
            '<form method="POST" action="' + back + '" class="card" style="padding:18px">'
            '<label class="pb-label">محتوى HTML للصفحة (يُعرض داخل الموقع)</label>'
            '<textarea id="spHtml" name="custom_html" rows="22" dir="ltr" spellcheck="false" '
            'style="width:100%;min-height:420px;font-family:monospace;text-align:left;background:#0f0f1a;'
            'color:#e8e8f5;border:1px solid #2d2d4a;border-radius:8px;padding:12px;box-sizing:border-box">' + seed + '</textarea>'
            '<div style="display:flex;gap:10px;margin-top:14px;flex-wrap:wrap">'
            '<button class="btn" type="submit">حفظ</button>'
            '<button class="btn btn-ghost" type="button" onclick="spPreview()">معاينة مباشرة</button>'
            '<a class="btn btn-ghost" href="/admin/static-pages">إلغاء</a></div></form></div>'
            '<div id="spModal" class="pb-modal" onclick="if(event.target===this)this.style.display=\'none\'">'
            '<div class="pb-modal-box"><div class="pb-row"><b>معاينة</b>'
            '<button type="button" class="btn btn-sm btn-ghost" onclick="document.getElementById(\'spModal\').style.display=\'none\'">إغلاق</button></div>'
            '<iframe id="spFrame" sandbox="" referrerpolicy="no-referrer" style="width:100%;height:70vh;border:0;'
            'border-radius:12px;background:#0b0b1a"></iframe></div></div>'
            '<script>function spPreview(){'
            'var fd=new FormData();fd.append("title","' + label.replace('"', '\\"') + '");'
            'fd.append("content_html",document.getElementById("spHtml").value);'
            'fetch("/admin/pages/preview",{method:"POST",body:fd,credentials:"same-origin"})'
            '.then(function(r){return r.text();}).then(function(t){'
            'document.getElementById("spFrame").srcdoc=t;document.getElementById("spModal").style.display="flex";});}'
            '</script>')
    return page("admin_static_edit", body=body)


@app.route("/admin/static-pages/<int:idx>/reset", methods=["POST"])
@admin_required
def admin_static_reset(idx):
    route, label = _sp_get(idx)
    db().execute("DELETE FROM static_pages_overrides WHERE route=?", (route,))
    db().commit()
    log_dev_change("مسح تخصيص صفحة: " + label, "المسار: " + route, change_type="update",
                   db_changes="static_pages_overrides")
    flash("تمت إعادة الصفحة للنسخة الأصلية.", "success")
    return redirect(url_for("admin_static_pages"))


# ---------- بلوكات لوحة المستخدم ----------
def _pb_link_visible(u, r):
    if not r or not r["is_active"]:
        return False
    t = r["target_users"] or "all"
    admin = is_admin(u)
    return t == "all" or (t == "admin" and admin) or (t == "user" and bool(u) and not admin)


def _pb_render_block(b, u):
    btype = b["block_type"]
    if btype == "link":
        r = db().execute("SELECT * FROM custom_links WHERE id=?", (b["reference_id"],)).fetchone()
        return _pb_link_card(r) if _pb_link_visible(u, r) else ""
    if btype == "text":
        return '<div class="card pb-text">' + esc(b["content"] or "").replace("\n", "<br>") + '</div>'
    if btype == "banner":
        return '<div class="pb-banner">' + esc(b["content"] or "") + '</div>'
    if btype == "html":
        return '<div class="card pb-text">' + sanitize_html_public(b["content"] or "") + '</div>'
    return ""


def _pb_dashboard_block(u):
    rows = db().execute("SELECT * FROM dashboard_blocks WHERE is_active=1 "
                        "ORDER BY sort_order ASC, id ASC").fetchall()
    items = []
    for b in rows:
        piece = _pb_render_block(b, u)
        if not piece:
            continue
        cls = {"left": "pb-b-left", "right": "pb-b-right"}.get(b["column_pos"], "pb-b-full")
        items.append('<div class="pb-b ' + cls + '">' + piece + '</div>')
    if not items:
        return ""
    return ('<div class="container" style="margin-top:8px"><div class="pb-blocks">' +
            "".join(items) + '</div></div>')


def _pb_sync_block(lid, position, active, sort_order):
    row = db().execute("SELECT id FROM dashboard_blocks WHERE block_type='link' AND reference_id=?",
                       (lid,)).fetchone()
    if position == "block":
        if row:
            db().execute("UPDATE dashboard_blocks SET is_active=?, sort_order=? WHERE id=?",
                         (active, sort_order, row["id"]))
        else:
            db().execute("INSERT INTO dashboard_blocks(block_type, reference_id, column_pos, sort_order, "
                         "is_active) VALUES('link', ?, 'full', ?, ?)", (lid, sort_order, active))
    elif row:
        db().execute("UPDATE dashboard_blocks SET is_active=0 WHERE id=?", (row["id"],))
    db().commit()


def _pb_migrate_dashboard_links():
    """يحوّل الأزرار القديمة position='dashboard' إلى بلوكات (مرة واحدة، آمن للتكرار)."""
    rows = db().execute("SELECT id FROM custom_links WHERE position='dashboard'").fetchall()
    for r in rows:
        db().execute("UPDATE custom_links SET position='block' WHERE id=?", (r["id"],))
        _pb_sync_block(r["id"], "block", 1, 0)
    if rows:
        log.info("[BLOCKS] نُقلت %d أزرار قديمة إلى بلوكات لوحة المستخدم", len(rows))


def _db_block_form(row=None):
    links = db().execute("SELECT id, title FROM custom_links ORDER BY id DESC").fetchall()
    link_opts = '<option value="">- اختر زراً -</option>' + "".join(
        '<option value="%d"%s>%s</option>' % (l["id"], " selected" if row and row["reference_id"] == l["id"] else "",
                                             esc(l["title"])) for l in links)
    type_opts = "".join('<option value="%s"%s>%s</option>' % (k, " selected" if row and row["block_type"] == k else "", lbl)
                        for k, lbl in DASH_BLOCK_TYPES)
    col_opts = "".join('<option value="%s"%s>%s</option>' % (k, " selected" if row and row["column_pos"] == k else "", lbl)
                       for k, lbl in DASH_COLUMNS)
    content = esc(row["content"] or "") if row else ""
    sort = row["sort_order"] if row else 0
    active = " checked" if (row is None or row["is_active"]) else ""
    action = ("/admin/dashboard-blocks/%d/edit" % row["id"]) if row else "/admin/dashboard-blocks/new"
    return ('<div class="container" style="max-width:700px"><div class="section-title">' +
            ("تعديل بلوك" if row else "بلوك جديد") + '</div>'
            '<a href="/admin/dashboard-blocks" class="btn btn-ghost btn-sm" style="margin-bottom:16px">رجوع</a>'
            '<form method="POST" action="' + action + '" class="card" style="padding:18px">'
            '<div class="pb-grid2"><div><label class="pb-label">نوع البلوك</label>'
            '<select name="block_type" style="' + _PB_INPUT + '">' + type_opts + '</select></div>'
            '<div><label class="pb-label">العمود</label><select name="column_pos" style="' + _PB_INPUT + '">' + col_opts + '</select></div>'
            '<div><label class="pb-label">الترتيب داخل العمود</label>'
            '<input type="number" name="sort_order" value="' + str(sort) + '" style="' + _PB_INPUT + '"></div></div>'
            '<div style="margin-top:12px"><label class="pb-label">الزر (للنوع زر فقط)</label>'
            '<select name="reference_id" style="' + _PB_INPUT + '">' + link_opts + '</select></div>'
            '<div style="margin-top:12px"><label class="pb-label">المحتوى (نص / بانر / HTML)</label>'
            '<textarea name="content" rows="8" dir="auto" style="' + _PB_INPUT + ';min-height:160px;font-family:inherit">' + content + '</textarea>'
            '<div class="pb-meta">للنوع HTML يُنظف تلقائياً من السكربتات والأحداث قبل العرض.</div></div>'
            '<label class="pb-check" style="margin-top:14px"><input type="checkbox" name="is_active"' + active + '> البلوك نشط</label>'
            '<div style="display:flex;gap:10px;margin-top:16px"><button class="btn" type="submit">حفظ</button>'
            '<a class="btn btn-ghost" href="/admin/dashboard-blocks">إلغاء</a></div></form></div>')


def _db_block_save(bid):
    btype = request.form.get("block_type", "text")
    if btype not in [k for k, _ in DASH_BLOCK_TYPES]:
        btype = "text"
    col = request.form.get("column_pos", "full")
    if col not in [k for k, _ in DASH_COLUMNS]:
        col = "full"
    try:
        sort = int(request.form.get("sort_order", "0") or 0)
    except ValueError:
        sort = 0
    ref = request.form.get("reference_id", "")
    ref_id = int(ref) if btype == "link" and ref.isdigit() else None
    content = (request.form.get("content") or "")[:PB_MAX_HTML]
    active = 1 if request.form.get("is_active") == "on" else 0
    back = "/admin/dashboard-blocks/new" if bid is None else "/admin/dashboard-blocks/%d/edit" % bid
    if btype == "link" and not ref_id:
        flash("اختر زراً لهذا البلوك.", "error")
        return redirect(back)
    if btype != "link" and not content.strip():
        flash("المحتوى فارغ.", "error")
        return redirect(back)
    if bid is None:
        db().execute("INSERT INTO dashboard_blocks(block_type, reference_id, content, column_pos, sort_order, "
                     "is_active) VALUES(?,?,?,?,?,?)", (btype, ref_id, content, col, sort, active))
        action = "إضافة بلوك"
    else:
        db().execute("UPDATE dashboard_blocks SET block_type=?, reference_id=?, content=?, column_pos=?, "
                     "sort_order=?, is_active=? WHERE id=?", (btype, ref_id, content, col, sort, active, bid))
        action = "تعديل بلوك"
    db().commit()
    log_dev_change("%s (%s)" % (action, dict(DASH_BLOCK_TYPES)[btype]),
                   "العمود: %s - الترتيب: %d - نشط: %s" % (col, sort, "نعم" if active else "لا"),
                   change_type="feature" if bid is None else "update", db_changes="dashboard_blocks")
    flash("تم حفظ البلوك.", "success")
    return redirect(url_for("admin_dashboard_blocks"))


@app.route("/admin/dashboard-blocks")
@admin_required
def admin_dashboard_blocks():
    rows = db().execute("SELECT * FROM dashboard_blocks ORDER BY column_pos, sort_order, id").fetchall()
    cards = ""
    type_lbl = dict(DASH_BLOCK_TYPES)
    col_lbl = dict(DASH_COLUMNS)
    for r in rows:
        ok = bool(r["is_active"])
        summary = ""
        if r["block_type"] == "link":
            lk = db().execute("SELECT title FROM custom_links WHERE id=?", (r["reference_id"],)).fetchone()
            summary = lk["title"] if lk else "زر محذوف"
        else:
            summary = (r["content"] or "")[:80]
        cards += ('<div class="card pb-admin-card"><div class="pb-row"><b>' + esc(type_lbl.get(r["block_type"], "")) +
                  ' - ' + esc(summary) + '</b><span class="pb-status ' + ("ok" if ok else "off") + '">' +
                  ("نشط" if ok else "معطل") + '</span></div>'
                  '<div class="pb-meta">العمود: ' + esc(col_lbl.get(r["column_pos"], "")) +
                  ' · الترتيب: ' + str(r["sort_order"]) + '</div>'
                  '<div class="pb-actions">'
                  '<form method="POST" action="/admin/dashboard-blocks/' + str(r["id"]) + '/move/up"><button class="btn btn-sm btn-ghost" type="submit">أعلى</button></form>'
                  '<form method="POST" action="/admin/dashboard-blocks/' + str(r["id"]) + '/move/down"><button class="btn btn-sm btn-ghost" type="submit">أسفل</button></form>'
                  '<a class="btn btn-sm" href="/admin/dashboard-blocks/' + str(r["id"]) + '/edit">تعديل</a>'
                  '<form method="POST" action="/admin/dashboard-blocks/' + str(r["id"]) + '/toggle"><button class="btn btn-sm btn-ghost" type="submit">' +
                  ("تعطيل" if ok else "تفعيل") + '</button></form>'
                  '<form method="POST" action="/admin/dashboard-blocks/' + str(r["id"]) + '/delete" '
                  'onsubmit="return confirm(\'حذف هذا البلوك؟\')"><button class="btn btn-sm pb-danger" type="submit">حذف</button></form>'
                  '</div></div>')
    if not rows:
        cards = '<div class="card" style="text-align:center;color:var(--muted)">لا توجد بلوكات بعد.</div>'
    body = ('<div class="container" style="max-width:960px"><div class="section-title">بلوكات لوحة المستخدم</div>'
            '<div class="pb-top"><a href="/admin" class="btn btn-ghost btn-sm">رجوع</a>'
            '<a href="/admin/dashboard-blocks/new" class="btn btn-sm">إضافة بلوك جديد</a></div>'
            '<div class="pb-list">' + cards + '</div>'
            '<div class="section-title" style="margin-top:20px">معاينة لوحة المستخدم</div>'
            '<div class="card" style="padding:8px"><iframe src="/dashboard" style="width:100%;height:520px;border:0;'
            'border-radius:12px;background:#0b0b1a" title="معاينة"></iframe></div></div>')
    return page("admin_dashboard_blocks", body=body)


@app.route("/admin/dashboard-blocks/new", methods=["GET", "POST"])
@admin_required
def admin_block_new():
    if request.method == "POST":
        return _db_block_save(None)
    return page("admin_block_form", body=_db_block_form(None))


@app.route("/admin/dashboard-blocks/<int:bid>/edit", methods=["GET", "POST"])
@admin_required
def admin_block_edit(bid):
    row = db().execute("SELECT * FROM dashboard_blocks WHERE id=?", (bid,)).fetchone()
    if not row:
        abort(404)
    if request.method == "POST":
        return _db_block_save(bid)
    return page("admin_block_form", body=_db_block_form(row))


@app.route("/admin/dashboard-blocks/<int:bid>/delete", methods=["POST"])
@admin_required
def admin_block_delete(bid):
    row = db().execute("SELECT * FROM dashboard_blocks WHERE id=?", (bid,)).fetchone()
    if not row:
        abort(404)
    db().execute("DELETE FROM dashboard_blocks WHERE id=?", (bid,))
    db().commit()
    log_dev_change("حذف بلوك لوحة المستخدم", "النوع: " + row["block_type"], change_type="update",
                   db_changes="dashboard_blocks")
    flash("تم حذف البلوك.", "success")
    return redirect(url_for("admin_dashboard_blocks"))


@app.route("/admin/dashboard-blocks/<int:bid>/toggle", methods=["POST"])
@admin_required
def admin_block_toggle(bid):
    row = db().execute("SELECT * FROM dashboard_blocks WHERE id=?", (bid,)).fetchone()
    if not row:
        abort(404)
    new_state = 0 if row["is_active"] else 1
    db().execute("UPDATE dashboard_blocks SET is_active=? WHERE id=?", (new_state, bid))
    db().commit()
    log_dev_change(("تفعيل" if new_state else "تعطيل") + " بلوك لوحة المستخدم", "النوع: " + row["block_type"],
                   change_type="update", db_changes="dashboard_blocks")
    return redirect(url_for("admin_dashboard_blocks"))


@app.route("/admin/dashboard-blocks/<int:bid>/move/<direction>", methods=["POST"])
@admin_required
def admin_block_move(bid, direction):
    if direction not in ("up", "down"):
        abort(404)
    row = db().execute("SELECT * FROM dashboard_blocks WHERE id=?", (bid,)).fetchone()
    if not row:
        abort(404)
    group = db().execute("SELECT id FROM dashboard_blocks WHERE column_pos=? "
                         "ORDER BY sort_order ASC, id ASC", (row["column_pos"],)).fetchall()
    ids = [g["id"] for g in group]
    i = ids.index(bid)
    j = i - 1 if direction == "up" else i + 1
    if 0 <= j < len(ids):
        ids[i], ids[j] = ids[j], ids[i]
        for n, item_id in enumerate(ids):
            db().execute("UPDATE dashboard_blocks SET sort_order=? WHERE id=?", (n, item_id))
        db().commit()
        log_dev_change("ترتيب بلوكات لوحة المستخدم", "نقل بلوك " + ("للأعلى" if direction == "up" else "للأسفل"),
                       change_type="update", db_changes="dashboard_blocks")
    return redirect(url_for("admin_dashboard_blocks"))


DASH_CSS_EXTRA = """
.pb-blocks { display:grid; grid-template-columns: 1fr; gap:12px; }
@media (min-width:720px) {
  .pb-blocks { grid-template-columns: 1fr 1fr; }
  .pb-b-full { grid-column: 1 / -1; }
}
.pb-text { line-height:1.9; }
.pb-banner { padding:18px; border-radius:18px; font-weight:800; text-align:center;
  background: linear-gradient(135deg, rgba(99,102,241,.35), rgba(16,185,129,.25)); border:1px solid var(--border); }
"""

def bootstrap_database():
    """تهيئة آمنة وقابلة للتكرار: تنشئ المجلدات والجداول والأعمدة الناقصة."""
    for d in ("static/icons", "static/avatars"):
        os.makedirs(os.path.join(BASE_DIR, d), exist_ok=True)
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)

    # init_db آمنة للتكرار (CREATE IF NOT EXISTS + INSERT OR IGNORE)
    # ملاحظة: لم نعد نفحص وجود الملف قبلها، لأن الاتصال بـ sqlite ينشئ ملفاً فارغاً
    try:
        init_db()
        log.info("قاعدة البيانات جاهزة: %s", DB_PATH)
    except Exception:
        log.exception("فشل init_db")
    
    # تأكد من الأعمدة المطلوبة (حتى لو auto_fix_db فشلت)
    try:
        ensure_schema()
    except Exception:
        log.exception("فشل ensure_schema")

    # الإصلاح الذاتي الشامل (يضيف الجداول/الأعمدة الناقصة ويعيد بناء ما اختلف)
    try:
        self_heal_schema()
    except Exception:
        log.exception("فشل self_heal_schema")

    try:
        with app.app_context():
            _pb_migrate_dashboard_links()
    except Exception:
        log.exception("فشل ترحيل بلوكات لوحة المستخدم")

    for name, fn in (("auto_fix_db", auto_fix_db),
                     ("seed_buy_prices", seed_buy_prices),
                     ("run_migrations", run_migrations)):
        try:
            fn()
        except Exception:
            log.exception("فشل %s", name)


try:
    bootstrap_database()
except Exception:
    log.exception("فشل تهيئة التطبيق")

# الدفع التلقائي للبائعين: يشتغل مرة واحدة فقط (استخدم worker واحد في Procfile)
if os.environ.get("MATARI_AUTOPAY", "1") == "1":
    try:
        start_auto_pay_worker()
    except Exception:
        log.exception("فشل تشغيل worker الدفع التلقائي")

    # تشغيل خلفية النسخ الاحتياطي اليومي
    import threading
    threading.Thread(target=daily_backup_worker, daemon=True).start()

if __name__ == "__main__":
    log.info("تشغيل السيرفر المحلي على المنفذ %s", PORT)
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)

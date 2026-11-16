# -*- coding: utf-8 -*-
# ============================================================
#  النسخة النهائية — فهرس الأقسام: 1 الإعدادات · 2 قاعدة البيانات · 3 المخطط · 4 المستخدمون · 5 المتجر · 6 الأكواد
#  7 الشحن/التحويل · 8 الدعم · 9 الإدارة · 10 القوالب والأزرار · 11+ المعالجات · المزامنة · التشغيل
# ============================================================
#  MATARI STORE — Telegram Bot (bot.py)
#  بوت تيليجرام متكامل ومتزامن بالكامل مع الموقع (web.py)
#  يقرأ ويكتب في نفس قاعدة البيانات matari.db — بدون تعديل أي سطر في web.py
# ============================================================
import os, re, sys, io, csv, time, html, math, shutil, hashlib, hmac, secrets, random
import sqlite3, logging, threading, traceback, asyncio, imaplib, email as _email
from contextlib import contextmanager
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from logging.handlers import RotatingFileHandler
from urllib.parse import urlencode

from werkzeug.security import generate_password_hash, check_password_hash

try:
    import requests
except ImportError:  # Binance فقط يحتاجها
    requests = None

import telebot
from telebot import types
from telebot.apihelper import ApiTelegramException

# ============================================================
#  1) الإعدادات (كلها من متغيرات البيئة أو من جدول settings — لا أسرار داخل الكود)
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# نفس منطق web.py تماماً لتحديد مسار قاعدة البيانات
DB_PATH = os.environ.get("MATARI_DB_PATH") or os.path.join(BASE_DIR, "matari.db")
BOT_LOG = os.path.join(BASE_DIR, "bot.log")

ENV_TOKEN = os.environ.get("BOT_TOKEN", "7798949296:AAENslF2-nCqfyIttMdRFQfVtALSxRZspY8").strip()
ENV_ADMINS = {int(x) for x in re.findall(r"\d+", os.environ.get("ADMIN_IDS", "7325566792"))}
PAGE = 6                       # عناصر كل صفحة
OTP_LIFETIME = 3 * 24 * 3600   # مدة السماح بطلب الكود بعد الشراء (3 أيام — نفس الموقع)
OTP_COOLDOWN = 10              # ثواني بين كل طلب كود وآخر (نفس الموقع)
AUTO_OTP_SECONDS = 300         # مدة البحث التلقائي عن الكود بعد الشراء
POLL_INTERVAL = 4              # فترة فحص أحداث الموقع (ثواني)
# الموقع يخصم (المبلغ + الرسوم) من المرسل ويضيف (المبلغ − الرسوم) للمستلم.
# True = نفس معادلة الموقع حرفياً (ليتطابق السجل). False = المستلم يستلم المبلغ كاملاً.
MIRROR_SITE_TRANSFER_MATH = True

logger = logging.getLogger("matari_bot")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _f = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    _sh = logging.StreamHandler(); _sh.setFormatter(_f); logger.addHandler(_sh)
    try:
        _fh = RotatingFileHandler(BOT_LOG, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        _fh.setFormatter(_f); logger.addHandler(_fh)
    except Exception:
        pass

# ============================================================
#  2) طبقة قاعدة البيانات (اتصال جديد لكل عملية = آمن مع الخيوط والموقع)
# ============================================================
@contextmanager
def conn():
    c = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None, check_same_thread=False)
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA busy_timeout=30000")
        yield c
    finally:
        c.close()

@contextmanager
def tx():
    """معاملة ذرّية: BEGIN IMMEDIATE ... COMMIT (أو ROLLBACK عند أي خطأ)."""
    with conn() as c:
        c.execute("BEGIN IMMEDIATE")
        try:
            yield c
            c.execute("COMMIT")
        except BaseException:
            try: c.execute("ROLLBACK")
            except Exception: pass
            raise

def rows(sql, p=()):
    with conn() as c:
        return c.execute(sql, p).fetchall()

def row(sql, p=()):
    with conn() as c:
        return c.execute(sql, p).fetchone()

def run(sql, p=()):
    with conn() as c:
        cur = c.execute(sql, p)
        return cur.lastrowid, cur.rowcount

def scalar(sql, p=(), d=0):
    r = row(sql, p)
    return r[0] if r and r[0] is not None else d

def now_s():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ---------------- الإعدادات (جدول settings المشترك مع الموقع) ----------------
def get_setting(k, d=None):
    r = row("SELECT value FROM settings WHERE key=?", (k,))
    return r["value"] if r and r["value"] is not None else d

def set_setting(k, v):
    run("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (k, str(v)))

def fsetting(k, d=0.0):
    try: return float(get_setting(k, d))
    except (TypeError, ValueError): return float(d)

def audit(uid, action, details=""):
    try:
        run("INSERT INTO audit_log(user_id,action,details) VALUES(?,?,?)", (uid, "bot:" + action, str(details)[:500]))
    except Exception:
        pass

# ============================================================
#  3) تجهيز قاعدة البيانات (إضافات فقط — لا حذف ولا تغيير لما يعتمد عليه الموقع)
# ============================================================
def _cols(c, table):
    return {r[1] for r in c.execute("PRAGMA table_info(%s)" % table)}

def ensure_schema():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with conn() as c:
        try: c.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError: pass
        # الجداول الأساسية — نفس تعريف الموقع (IF NOT EXISTS) لو شُغّل البوت قبل الموقع
        c.executescript("""
CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
  email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, recovery_key TEXT UNIQUE, custom_id TEXT UNIQUE,
  balance REAL DEFAULT 0.0, is_admin INTEGER DEFAULT 0, is_banned INTEGER DEFAULT 0, referred_by INTEGER,
  referral_earnings REAL DEFAULT 0.0, captcha_passed INTEGER DEFAULT 0, last_bonus TEXT, total_spent REAL DEFAULT 0,
  bad_coupons INTEGER DEFAULT 0, created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS numbers(id INTEGER PRIMARY KEY AUTOINCREMENT, platform TEXT NOT NULL, country TEXT NOT NULL,
  phone TEXT NOT NULL, price REAL NOT NULL, status TEXT DEFAULT 'available', buyer_id INTEGER, sold_at TEXT,
  last_code TEXT, paid_price REAL, session_string TEXT, created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS deposits(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, method TEXT NOT NULL,
  amount_usd REAL NOT NULL, status TEXT DEFAULT 'pending', trans_id TEXT, created_at TEXT DEFAULT (datetime('now')), processed_at TEXT);
CREATE TABLE IF NOT EXISTS vouchers(id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE NOT NULL, amount REAL NOT NULL,
  is_used INTEGER DEFAULT 0, used_by INTEGER, created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS coupons(code TEXT PRIMARY KEY, percent REAL NOT NULL, max_uses INTEGER DEFAULT 1,
  used_count INTEGER DEFAULT 0, expires_at TEXT);
CREATE TABLE IF NOT EXISTS coupon_uses(code TEXT, user_id INTEGER, used_at TEXT, PRIMARY KEY(code, user_id));
CREATE TABLE IF NOT EXISTS tickets(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, subject TEXT NOT NULL,
  message TEXT, status TEXT DEFAULT 'open', created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS ticket_messages(id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id INTEGER NOT NULL,
  sender TEXT NOT NULL, text TEXT NOT NULL, is_read INTEGER DEFAULT 0, created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS audit_log(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, action TEXT NOT NULL,
  details TEXT, created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS transfers(id INTEGER PRIMARY KEY AUTOINCREMENT, from_id INTEGER, to_id INTEGER, amount REAL,
  fee REAL, created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS announcements(id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL, level TEXT DEFAULT 'info',
  is_active INTEGER DEFAULT 1, text_color TEXT DEFAULT '#e8e8f5', font_size TEXT DEFAULT '15px', icon TEXT DEFAULT 'bell',
  btn_text TEXT DEFAULT '', btn_url TEXT DEFAULT '', created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS buy_prices(country TEXT PRIMARY KEY, code TEXT DEFAULT '', price REAL NOT NULL,
  flag TEXT DEFAULT '', created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS stamps(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, color TEXT DEFAULT '#f59e0b',
  shape TEXT DEFAULT 'seal', svg TEXT, created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS number_stamps(number_id INTEGER NOT NULL, stamp_id INTEGER NOT NULL, PRIMARY KEY(number_id, stamp_id));
CREATE TABLE IF NOT EXISTS code_logs(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, number_id INTEGER, phone TEXT,
  code TEXT, platform TEXT, created_at TEXT DEFAULT (datetime('now')));
-- جداول خاصة بالبوت فقط
CREATE TABLE IF NOT EXISTS bot_notified(kind TEXT NOT NULL, ref TEXT NOT NULL, PRIMARY KEY(kind, ref));
CREATE TABLE IF NOT EXISTS bot_receipts(deposit_id INTEGER PRIMARY KEY, file_id TEXT);
""")
        wanted = {
            "users": [("tg_id", "INTEGER"), ("tg_username", "TEXT"), ("tg_name", "TEXT"), ("avatar", "TEXT"),
                      ("captcha_passed", "INTEGER DEFAULT 0"), ("last_bonus", "TEXT"), ("total_spent", "REAL DEFAULT 0"),
                      ("referral_earnings", "REAL DEFAULT 0.0"), ("custom_id", "TEXT"), ("bad_coupons", "INTEGER DEFAULT 0")],
            "numbers": [("hidden_for_buyer", "INTEGER DEFAULT 0"), ("seen_by_buyer", "INTEGER DEFAULT 0"),
                        ("request_time", "TEXT"), ("is_premium", "INTEGER DEFAULT 0"), ("paid_price", "REAL"),
                        ("session_string", "TEXT"), ("last_code", "TEXT")],
            "ticket_messages": [("is_read", "INTEGER DEFAULT 0")],
            "announcements": [("icon_name", "TEXT DEFAULT 'bell'"), ("text_color", "TEXT DEFAULT '#e8e8f5'"),
                              ("font_size", "TEXT DEFAULT '15px'"), ("icon", "TEXT DEFAULT 'bell'"),
                              ("btn_text", "TEXT DEFAULT ''"), ("btn_url", "TEXT DEFAULT ''")],
            "buy_prices": [("code", "TEXT DEFAULT ''"), ("flag", "TEXT DEFAULT ''")],
        }
        for t, cl in wanted.items():
            have = _cols(c, t)
            for name, decl in cl:
                if name not in have:
                    c.execute("ALTER TABLE %s ADD COLUMN %s %s" % (t, name, decl))
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_tg ON users(tg_id) WHERE tg_id IS NOT NULL")
        c.execute("CREATE INDEX IF NOT EXISTS idx_nums_status ON numbers(status)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_nums_buyer ON numbers(buyer_id)")
        # إعدادات افتراضية خاصة بالبوت (لا تمس إعدادات الموقع)
        for k, v in {"BOT_AUTO_OTP": "1", "TRANSFER_FEE": "0.05", "MIN_DEPOSIT_USD": "0.10",
                     "DAILY_BONUS": "0.01", "DAILY_BONUS_ENABLED": "1", "SITE_NAME": "MATARI STORE",
                     "SUPPORT_USER": "@MO_5_H"}.items():
            c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))

# ============================================================
#  4) المستخدمون (ربط تيليجرام ↔ حسابات الموقع)
# ============================================================
def user_by_tg(tg_id):
    return row("SELECT * FROM users WHERE tg_id=?", (tg_id,))

def user_by_id(uid):
    return row("SELECT * FROM users WHERE user_id=?", (uid,))

def find_user(q):
    """بحث بـ: user_id / custom_id / tg_id / username / email"""
    q = (q or "").strip().lstrip("@")
    if not q: return None
    return row("SELECT * FROM users WHERE custom_id=? OR username=? OR lower(email)=? OR CAST(tg_id AS TEXT)=? "
               "OR CAST(user_id AS TEXT)=? LIMIT 1", (q, q, q.lower(), q, q))

def _gen_custom_id(c):
    for _ in range(100):
        cid = str(random.randint(10000000, 99999999))
        if not c.execute("SELECT 1 FROM users WHERE custom_id=?", (cid,)).fetchone():
            return cid
    return str(random.randint(10000000, 99999999))

def register_tg_user(tg_id, username=None, full_name=None, ref=None):
    """ينشئ حساباً جديداً (رصيد 0) أو يرجع الحساب المرتبط. الحساب صالح للدخول بالموقع بعد تعيين كلمة مرور."""
    u = user_by_tg(tg_id)
    if u:
        if (username or "") != (u["tg_username"] or "") or (full_name or "") != (u["tg_name"] or ""):
            run("UPDATE users SET tg_username=?, tg_name=? WHERE user_id=?", (username, full_name, u["user_id"]))
        return user_by_tg(tg_id), False
    with tx() as c:
        if c.execute("SELECT 1 FROM users WHERE tg_id=?", (tg_id,)).fetchone():
            return user_by_tg(tg_id), False
        referrer = None
        if ref:
            r = c.execute("SELECT user_id FROM users WHERE user_id=? OR custom_id=?", (str(ref), str(ref))).fetchone()
            if r: referrer = r["user_id"]
        uname = "tg_%d" % tg_id
        mail = "tg%d@telegram.local" % tg_id
        c.execute("INSERT INTO users(username,email,password_hash,recovery_key,custom_id,referred_by,captcha_passed,"
                  "tg_id,tg_username,tg_name) VALUES(?,?,?,?,?,?,1,?,?,?)",
                  (uname, mail, generate_password_hash(secrets.token_urlsafe(24)),
                   "AT-" + secrets.token_hex(6).upper(), _gen_custom_id(c), referrer, tg_id, username, full_name))
    audit(None, "register", "tg=%d" % tg_id)
    return user_by_tg(tg_id), True

def link_site_account(tg_id, ident, password):
    """يربط تيليجرام بحساب موجود في الموقع (بإيميل/يوزر + كلمة المرور). يدمج الحساب المؤقت إن وُجد."""
    ident = (ident or "").strip()
    target = row("SELECT * FROM users WHERE lower(email)=? OR username=? OR custom_id=?", (ident.lower(), ident, ident))
    if not target or not check_password_hash(target["password_hash"], password or ""):
        return False, "بيانات الدخول غير صحيحة."
    if target["is_banned"]:
        return False, "هذا الحساب محظور."
    if target["tg_id"] and int(target["tg_id"]) != int(tg_id):
        return False, "هذا الحساب مرتبط بحساب تيليجرام آخر."
    cur = user_by_tg(tg_id)
    if cur and cur["user_id"] == target["user_id"]:
        return True, "حسابك مرتبط بالفعل."
    with tx() as c:
        if cur:
            old = cur["user_id"]
            bal = c.execute("SELECT balance FROM users WHERE user_id=?", (old,)).fetchone()["balance"] or 0
            c.execute("UPDATE users SET tg_id=NULL WHERE user_id=?", (old,))
            c.execute("UPDATE users SET balance=balance+?, tg_id=?, tg_username=?, tg_name=? WHERE user_id=?",
                      (bal, tg_id, cur["tg_username"], cur["tg_name"], target["user_id"]))
            for t, col in (("numbers", "buyer_id"), ("deposits", "user_id"), ("tickets", "user_id"),
                           ("code_logs", "user_id")):
                c.execute("UPDATE %s SET %s=? WHERE %s=?" % (t, col, col), (target["user_id"], old))
            c.execute("UPDATE transfers SET from_id=? WHERE from_id=?", (target["user_id"], old))
            c.execute("UPDATE transfers SET to_id=? WHERE to_id=?", (target["user_id"], old))
            c.execute("UPDATE users SET referred_by=? WHERE referred_by=?", (target["user_id"], old))
            c.execute("DELETE FROM users WHERE user_id=?", (old,))
        else:
            c.execute("UPDATE users SET tg_id=? WHERE user_id=?", (tg_id, target["user_id"]))
    audit(target["user_id"], "link_account", "tg=%d" % tg_id)
    return True, "تم ربط حسابك بالموقع بنجاح."

def set_site_password(uid, new_password):
    if len(new_password or "") < 6:
        return False, "كلمة المرور قصيرة (6 أحرف على الأقل)."
    run("UPDATE users SET password_hash=? WHERE user_id=?", (generate_password_hash(new_password), uid))
    audit(uid, "set_password")
    return True, "تم تعيين كلمة المرور."

def admin_ids():
    ids = set(ENV_ADMINS)
    for x in re.findall(r"\d+", get_setting("BOT_ADMIN_IDS", "") or ""):
        ids.add(int(x))
    try:
        for r in rows("SELECT tg_id FROM users WHERE is_admin=1 AND tg_id IS NOT NULL"):
            ids.add(int(r["tg_id"]))
    except Exception:
        pass
    return ids

def is_admin_tg(tg_id):
    return int(tg_id) in admin_ids()

# ============================================================
#  5) المتجر: أرقام / شراء / كوبونات
# ============================================================
def plat_filter(pf):
    """pf: wa | tg  → شرط SQL مطابق لمنطق الموقع"""
    if pf == "wa": return "LOWER(platform) LIKE '%whatsapp%'"
    if pf == "tg": return "LOWER(platform) LIKE '%telegram%'"
    return "1=1"

def pf_of(platform):
    return "tg" if "telegram" in (platform or "").lower() else "wa"

def country_key(name):
    return hashlib.md5((name or "").encode("utf-8")).hexdigest()[:8]

def resolve_country(key):
    for r in rows("SELECT DISTINCT country FROM numbers"):
        if country_key(r["country"]) == key:
            return r["country"]
    return None

def flag_of(country):
    r = row("SELECT flag FROM buy_prices WHERE country=?", (country,))
    return (r["flag"] if r and r["flag"] else "🌍")

def detect_country(phone):
    clean = re.sub(r"[+\s\-]", "", str(phone or ""))
    if not clean.isdigit(): return None, None
    best = None
    for r in rows("SELECT country, code, flag FROM buy_prices WHERE code IS NOT NULL AND code!=''"):
        code = str(r["code"])
        if clean.startswith(code) and (best is None or len(code) > len(str(best["code"]))):
            best = r
    return (best["country"], best["flag"]) if best else (None, None)

def countries_for(pf):
    return rows("SELECT country, COUNT(*) c, MIN(price) mp FROM numbers WHERE status='available' AND %s "
                "GROUP BY country ORDER BY c DESC, country" % plat_filter(pf))

def numbers_for(pf, country, offset=0, limit=PAGE):
    return rows("SELECT * FROM numbers WHERE status='available' AND %s AND country=? ORDER BY is_premium DESC, id DESC "
                "LIMIT ? OFFSET ?" % plat_filter(pf), (country, limit, offset))

def count_numbers_for(pf, country):
    return scalar("SELECT COUNT(*) FROM numbers WHERE status='available' AND %s AND country=?" % plat_filter(pf), (country,))

def stamps_of(nid):
    return [r["name"] for r in rows("SELECT s.name FROM number_stamps ns JOIN stamps s ON s.id=ns.stamp_id "
                                    "WHERE ns.number_id=?", (nid,))]

def mask_phone(phone):
    p = str(phone or "")
    return p[:5] + "••••" + p[-2:] if len(p) > 8 else p

def coupon_check(code, uid):
    code = (code or "").strip().upper()
    c = row("SELECT * FROM coupons WHERE code=?", (code,))
    if not c: return None, "كوبون غير صحيح"
    if c["expires_at"] and c["expires_at"] < now_s(): return None, "انتهت صلاحية الكوبون"
    if c["max_uses"] and c["used_count"] >= c["max_uses"]: return None, "استُنفد الكوبون"
    if row("SELECT 1 FROM coupon_uses WHERE code=? AND user_id=?", (code, uid)): return None, "استخدمت هذا الكوبون سابقاً"
    return float(c["percent"]), None

def final_price(price, pct):
    return round(float(price) * (1 - pct / 100.0), 2) if pct else float(price)

def buy_number(uid, nid, coupon=None):
    """شراء ذرّي مطابق لمسار /buy في الموقع (خصم الرصيد + status=sold + paid_price + الكوبون + الإحالة)."""
    coupon = (coupon or "").strip().upper() or None
    try:
        with tx() as c:
            u = c.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
            if not u: return False, "الحساب غير موجود.", None
            if u["is_banned"]: return False, "حسابك محظور.", None
            n = c.execute("SELECT * FROM numbers WHERE id=?", (nid,)).fetchone()
            if not n: return False, "الرقم غير موجود.", None
            if n["status"] != "available": return False, "عذراً، تم بيع هذا الرقم للتو.", None
            pct = 0.0
            if coupon:
                cp = c.execute("SELECT * FROM coupons WHERE code=?", (coupon,)).fetchone()
                err = None
                if not cp: err = "كوبون غير صحيح"
                elif cp["expires_at"] and cp["expires_at"] < now_s(): err = "انتهت صلاحية الكوبون"
                elif cp["max_uses"] and cp["used_count"] >= cp["max_uses"]: err = "استُنفد الكوبون"
                elif c.execute("SELECT 1 FROM coupon_uses WHERE code=? AND user_id=?", (coupon, uid)).fetchone():
                    err = "استخدمت هذا الكوبون سابقاً"
                if err: return False, err, None
                pct = float(cp["percent"])
            price = final_price(n["price"], pct)
            if c.execute("UPDATE users SET balance=balance-? WHERE user_id=? AND balance>=?",
                         (price, uid, price)).rowcount != 1:
                return False, "رصيدك غير كافٍ. تحتاج $%.2f" % price, None
            c.execute("UPDATE numbers SET status='sold', buyer_id=?, sold_at=datetime('now'), seen_by_buyer=0, "
                      "paid_price=? WHERE id=?", (uid, price, nid))
            if coupon:
                c.execute("UPDATE coupons SET used_count=used_count+1 WHERE code=?", (coupon,))
                c.execute("INSERT INTO coupon_uses(code,user_id,used_at) VALUES(?,?,?)", (coupon, uid, now_s()))
            c.execute("INSERT OR IGNORE INTO bot_notified(kind,ref) VALUES('sale',?)", (str(nid),))
        # مكافأة الإحالة (أول شراء فقط — نفس _credit_referral في الموقع)
        if get_setting("REFERRAL_ENABLED", "1") == "1":
            try: credit_referral(uid)
            except Exception: logger.exception("referral")
        audit(uid, "buy_number", "nid=%s price=%s" % (nid, price))
        return True, "تمت عملية الشراء بنجاح.", row("SELECT * FROM numbers WHERE id=?", (nid,))
    except sqlite3.OperationalError as e:
        logger.warning("buy locked: %s", e)
        return False, "الخادم مشغول، حاول بعد ثوانٍ.", None

def credit_referral(uid):
    u = user_by_id(uid)
    if not u or not u["referred_by"]: return
    if row("SELECT 1 FROM audit_log WHERE user_id=? AND action='referral_credited' LIMIT 1", (uid,)): return
    reward = fsetting("REFERRAL_REWARD", 0.001)
    with tx() as c:
        c.execute("UPDATE users SET balance=balance+?, referral_earnings=referral_earnings+? WHERE user_id=?",
                  (reward, reward, u["referred_by"]))
        c.execute("INSERT INTO audit_log(user_id,action,details) VALUES(?,?,?)",
                  (uid, "referral_credited", "referrer=%s" % u["referred_by"]))
    ref = user_by_id(u["referred_by"])
    if ref and ref["tg_id"]:
        NOTIFY_QUEUE.append((int(ref["tg_id"]), "referral", reward))

NOTIFY_QUEUE = []   # (tg_id, kind, payload) — تُعالَج من خيط الإشعارات

def my_numbers(uid, offset=0, limit=PAGE):
    return rows("SELECT * FROM numbers WHERE buyer_id=? AND COALESCE(hidden_for_buyer,0)=0 ORDER BY sold_at DESC, id DESC "
                "LIMIT ? OFFSET ?", (uid, limit, offset))

def count_my_numbers(uid):
    return scalar("SELECT COUNT(*) FROM numbers WHERE buyer_id=? AND COALESCE(hidden_for_buyer,0)=0", (uid,))

def hide_number(uid, nid):
    run("UPDATE numbers SET hidden_for_buyer=1 WHERE id=? AND buyer_id=?", (nid, uid))

# ============================================================
#  6) سحب أكواد التفعيل (نفس منطق الموقع: IMAP للواتساب / Telethon لتيليجرام)
# ============================================================
def extract_otp(text):
    if not text: return None
    for pat in (r"(?<!\d)(\d{3})[-\s]?(\d{3})(?!\d)", r"(?<!\d)(\d{4,8})(?!\d)"):
        m = re.search(pat, text)
        if m:
            code = "".join(m.groups())
            if 4 <= len(code) <= 8: return code
    return None

def fetch_otp_imap(since_ts=0):
    addr = (get_setting("WA_EMAIL_ADDRESS", "") or "").strip() or (get_setting("EMAIL_ADDRESS", "") or "").strip()
    pwd = (get_setting("WA_EMAIL_PASSWORD", "") or "").strip() or (get_setting("EMAIL_PASSWORD", "") or "").strip()
    host = (get_setting("IMAP_HOST", "imap.gmail.com") or "imap.gmail.com").strip()
    if not (addr and pwd):
        return None, "الإيميل غير مهيأ في الإعدادات"
    M = None
    try:
        M = imaplib.IMAP4_SSL(host, timeout=15)
        M.login(addr, pwd)
        M.select("INBOX", readonly=True)
        _, data = M.search(None, "TEXT", '"whatsapp"')
        ids = data[0].split()
        if not ids: return None, "لا توجد رسائل واتساب"
        for mid in reversed(ids[-10:]):
            try:
                _, md = M.fetch(mid, "(RFC822)")
                if not md or not md[0] or not isinstance(md[0], tuple): continue
                msg = _email.message_from_bytes(md[0][1])
                if since_ts > 0:
                    try:
                        ds = msg.get("Date", "")
                        if ds and parsedate_to_datetime(ds).timestamp() < since_ts - 60: continue
                    except Exception:
                        pass
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            try: body += part.get_payload(decode=True).decode(errors="ignore")
                            except Exception: pass
                else:
                    pl = msg.get_payload(decode=True)
                    if pl: body = pl.decode(errors="ignore")
                code = extract_otp(body)
                if code: return code, None
            except Exception as e:
                logger.warning("imap msg: %s", e)
        return None, "لا يوجد كود جديد في آخر الرسائل"
    except Exception as e:
        return None, "خطأ: " + str(e)[:80]
    finally:
        try:
            if M: M.logout()
        except Exception:
            pass

def fetch_otp_telethon(session_str, since_ts=0):
    if not session_str: return None, "لا توجد جلسة لهذا الرقم."
    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
    except ImportError:
        return None, "مكتبة telethon غير مثبتة (pip install telethon)."
    api_id = int(get_setting("TG_API_ID", "0") or 0)
    api_hash = (get_setting("TG_API_HASH", "") or "").strip()
    if not (api_id and api_hash): return None, "TG API ID/Hash غير مهيأ."

    async def go():
        cl = TelegramClient(StringSession(session_str), api_id, api_hash)
        await cl.connect()
        try:
            if not await cl.is_user_authorized(): return None, "الجلسة غير مفعّلة."
            async for m in cl.iter_messages(777000, limit=10):
                if not m.text: continue
                mm = re.search(r"\b(\d{5,6})\b", m.text)
                if mm:
                    if since_ts > 0 and m.date.timestamp() < since_ts - 60: continue
                    return mm.group(1), None
            return None, "لا يوجد كود جديد في الرسائل الأخيرة."
        finally:
            await cl.disconnect()
    try:
        loop = asyncio.new_event_loop()
        try: return loop.run_until_complete(asyncio.wait_for(go(), 30))
        finally: loop.close()
    except Exception as e:
        return None, "خطأ: " + str(e)[:100]

def _sold_ts(n):
    try: return datetime.strptime(n["sold_at"], "%Y-%m-%d %H:%M:%S").timestamp()
    except Exception: return 0

def request_otp(uid, nid, force_since=None):
    """يرجع (code, error). يطبّق: ملكية الرقم، مهلة 3 أيام، فاصل 10 ثواني، منع إعادة تسليم كود لعميل آخر."""
    n = row("SELECT * FROM numbers WHERE id=? AND buyer_id=? AND COALESCE(hidden_for_buyer,0)=0", (nid, uid))
    if not n: return None, "غير مصرح."
    now = time.time(); sts = _sold_ts(n)
    if sts and now > sts + OTP_LIFETIME: return None, "انتهت مدة طلب الكود (3 أيام) لهذا الرقم."
    try: last = float(n["request_time"] or 0)
    except Exception: last = 0
    if now - last < OTP_COOLDOWN:
        return None, "انتظر %d ثانية قبل إعادة الطلب." % (OTP_COOLDOWN - int(now - last) + 1)
    run("UPDATE numbers SET request_time=? WHERE id=?", (str(now), nid))
    old = n["last_code"] or None
    since = force_since if force_since is not None else max(sts, now - 120)
    if "telegram" in (n["platform"] or "").lower():
        code, err = fetch_otp_telethon(n["session_string"], now if force_since is None else force_since)
    else:
        code, err = fetch_otp_imap(since_ts=since)
    if not code: return None, err or "لا يوجد كود."
    if row("SELECT 1 FROM code_logs WHERE code=? AND (number_id<>? OR user_id<>?) LIMIT 1", (code, nid, uid)):
        return None, "لم يصل كود جديد بعد. جرّب بعد لحظات."
    if old and code == old:
        return None, "لم يصل كود جديد بعد. جرّب بعد لحظات."
    run("UPDATE numbers SET last_code=? WHERE id=?", (code, nid))
    try:
        run("INSERT INTO code_logs(user_id,number_id,phone,code,platform,created_at) VALUES(?,?,?,?,?,datetime('now'))",
            (uid, nid, n["phone"], code, n["platform"]))
    except Exception:
        pass
    return code, None

# ============================================================
#  7) الشحن والإيداع والتحويل
# ============================================================
def redeem_voucher(uid, code):
    code = (code or "").strip().upper()
    if not code: return False, "أدخل الكود.", 0
    try:
        with tx() as c:
            v = c.execute("SELECT * FROM vouchers WHERE code=? AND is_used=0", (code,)).fetchone()
            if not v: return False, "الكود غير صالح أو مستخدم.", 0
            c.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (v["amount"], uid))
            c.execute("UPDATE vouchers SET is_used=1, used_by=? WHERE id=?", (uid, v["id"]))
            c.execute("INSERT OR IGNORE INTO bot_notified(kind,ref) VALUES('vch',?)", (str(v["id"]),))
        audit(uid, "redeem_voucher", "code=%s amt=%s" % (code, v["amount"]))
        return True, "تم الشحن.", float(v["amount"])
    except sqlite3.OperationalError:
        return False, "الخادم مشغول، أعد المحاولة.", 0

def create_deposit(uid, method, amount, trans_id=None, file_id=None):
    mn = fsetting("MIN_DEPOSIT_USD", 0.10)
    if amount < max(mn, 0.01): return None, "الحد الأدنى للشحن $%.2f" % mn
    if scalar("SELECT COUNT(*) FROM deposits WHERE user_id=? AND status='pending'", (uid,)) >= 3:
        return None, "لديك 3 طلبات معلّقة بالفعل. انتظر معالجتها."
    if trans_id and row("SELECT 1 FROM deposits WHERE trans_id=? AND status IN ('pending','approved') AND method=?",
                        (trans_id, method)):
        return None, "رقم العملية هذا مُستخدم مسبقاً."
    did, _ = run("INSERT INTO deposits(user_id,method,amount_usd,status,trans_id) VALUES(?,?,?,'pending',?)",
                 (uid, method, round(amount, 4), trans_id))
    run("INSERT OR IGNORE INTO bot_notified(kind,ref) VALUES('dep_new',?)", (str(did),))
    if file_id:
        run("INSERT OR REPLACE INTO bot_receipts(deposit_id,file_id) VALUES(?,?)", (did, file_id))
    audit(uid, "deposit_request", "id=%s %s $%s" % (did, method, amount))
    return did, None

def approve_deposit(did):
    try:
        with tx() as c:
            d = c.execute("SELECT * FROM deposits WHERE id=?", (did,)).fetchone()
            if not d: return False, "الطلب غير موجود.", None
            if d["status"] != "pending": return False, "الطلب ليس معلّقاً.", None
            c.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (d["amount_usd"], d["user_id"]))
            c.execute("UPDATE deposits SET status='approved', processed_at=datetime('now') WHERE id=?", (did,))
        audit(None, "approve_deposit", "id=%s amt=%s" % (did, d["amount_usd"]))
        return True, "تمت الموافقة.", d
    except sqlite3.OperationalError:
        return False, "الخادم مشغول.", None

def reject_deposit(did):
    d = row("SELECT * FROM deposits WHERE id=?", (did,))
    if not d or d["status"] != "pending": return False, "الطلب ليس معلّقاً.", None
    run("UPDATE deposits SET status='rejected', processed_at=datetime('now') WHERE id=? AND status='pending'", (did,))
    audit(None, "reject_deposit", "id=%s" % did)
    return True, "تم الرفض.", d

def transfer_balance(from_uid, to_custom_id, amount):
    """نفس منطق /transfer في الموقع."""
    fee = fsetting("TRANSFER_FEE", 0.05)
    try: amount = round(float(amount), 4)
    except (TypeError, ValueError): return False, "مبلغ غير صالح.", None
    if amount <= 0: return False, "أدخل مبلغاً صالحاً.", None
    if amount <= fee: return False, "المبلغ يجب أن يكون أكبر من رسوم التحويل ($%.2f)." % fee, None
    try:
        with tx() as c:
            me = c.execute("SELECT * FROM users WHERE user_id=?", (from_uid,)).fetchone()
            t = c.execute("SELECT * FROM users WHERE custom_id=? OR (CAST(user_id AS TEXT)=? AND custom_id IS NULL)",
                          (str(to_custom_id).strip(), str(to_custom_id).strip())).fetchone()
            if not t: return False, "المستخدم غير موجود. تأكد من الآيدي (8 أرقام).", None
            if t["user_id"] == from_uid: return False, "لا يمكن التحويل لنفسك.", None
            if t["is_banned"]: return False, "المستلم محظور.", None
            total = round(amount + fee, 4)
            if c.execute("UPDATE users SET balance=balance-? WHERE user_id=? AND balance>=?",
                         (total, from_uid, total)).rowcount != 1:
                return False, "رصيدك غير كافٍ. تحتاج $%.2f (المبلغ + الرسوم)." % total, None
            net = round(amount - fee, 4) if MIRROR_SITE_TRANSFER_MATH else amount
            c.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (net, t["user_id"]))
            c.execute("INSERT INTO transfers(from_id,to_id,amount,fee) VALUES(?,?,?,?)", (from_uid, t["user_id"], amount, fee))
        audit(from_uid, "transfer_out", "to=%s amt=%s fee=%s" % (to_custom_id, amount, fee))
        return True, "تم التحويل.", {"to": t, "amount": amount, "fee": fee, "net": net}
    except sqlite3.OperationalError:
        return False, "الخادم مشغول، أعد المحاولة.", None

def claim_bonus(uid):
    if get_setting("DAILY_BONUS_ENABLED", "1") != "1": return False, "المكافأة اليومية متوقفة حالياً.", 0
    today = datetime.now().strftime("%Y-%m-%d")
    amt = fsetting("DAILY_BONUS", 0.01)
    _, rc = run("UPDATE users SET balance=balance+?, last_bonus=? WHERE user_id=? AND (last_bonus IS NULL OR last_bonus!=?)",
                (amt, today, uid, today))
    if rc == 0: return False, "استلمت مكافأة اليوم بالفعل. عد غداً!", 0
    return True, "تمت إضافة المكافأة.", amt

# ---------------- Binance (تحقق تلقائي من دفعة Binance Pay — اختياري) ----------------
def _binance_signed(path, params=None):
    key = (get_setting("BINANCE_API_KEY", "") or "").strip()
    sec = (get_setting("BINANCE_API_SECRET", "") or "").strip()
    if not (key and sec): return None, "مفاتيح Binance غير مهيأة."
    if requests is None: return None, "مكتبة requests غير مثبتة."
    p = dict(params or {}); p["timestamp"] = int(time.time() * 1000); p["recvWindow"] = 10000
    qs = urlencode(p)
    sig = hmac.new(sec.encode(), qs.encode(), hashlib.sha256).hexdigest()
    try:
        r = requests.get("https://api.binance.com%s?%s&signature=%s" % (path, qs, sig),
                         headers={"X-MBX-APIKEY": key}, timeout=15)
        return r.json(), None
    except Exception as e:
        return None, "تعذر الاتصال: " + str(e)[:80]

def binance_check():
    if requests is None: return False, "مكتبة requests غير مثبتة."
    try:
        if requests.get("https://api.binance.com/api/v3/ping", timeout=10).status_code != 200:
            return False, "Binance لا يستجيب."
    except Exception as e:
        return False, "لا اتصال بـ Binance: " + str(e)[:60]
    data, err = _binance_signed("/api/v3/account")
    if err: return False, err
    if isinstance(data, dict) and data.get("code"):
        return False, "Binance: %s (%s)" % (data.get("msg", "")[:80], data.get("code"))
    return True, "الاتصال سليم ✓ — صلاحيات: %s" % ",".join(data.get("permissions", [])[:4])

def binance_auto_verify(order_id, expected):
    """يطابق رقم العملية مع سجل Binance Pay. أي فشل = يتحول الطلب للمراجعة اليدوية."""
    data, err = _binance_signed("/sapi/v1/pay/transactions", {"limit": 100})
    if err: return False, err
    if not isinstance(data, dict) or str(data.get("code")) not in ("000000", "0", "None"):
        return False, "تعذر قراءة سجل Binance Pay."
    for t in (data.get("data") or []):
        ids = {str(t.get("orderId", "")), str(t.get("transactionId", "")), str(t.get("prepayId", ""))}
        if str(order_id).strip() in ids:
            try: amt = float(t.get("amount", 0))
            except Exception: amt = 0
            if amt > 0 and (t.get("currency", "USDT") in ("USDT", "USDC", "BUSD", "FDUSD")) and amt + 0.01 >= expected:
                return True, "تم التحقق"
            return False, "المبلغ لا يطابق"
    return False, "لم يتم العثور على العملية"

# ============================================================
#  8) الدعم الفني (نفس جدولَي tickets / ticket_messages)
# ============================================================
def open_ticket(uid):
    t = row("SELECT * FROM tickets WHERE user_id=? AND status='open' ORDER BY id DESC LIMIT 1", (uid,))
    if t: return t
    tid, _ = run("INSERT INTO tickets(user_id,subject,message,status) VALUES(?,?,?,'open')", (uid, "محادثة دعم", ""))
    return row("SELECT * FROM tickets WHERE id=?", (tid,))

def add_ticket_msg(tid, sender, text):
    mid, _ = run("INSERT INTO ticket_messages(ticket_id,sender,text) VALUES(?,?,?)", (tid, sender, text[:3500]))
    return mid

def ticket_msgs(tid, limit=8):
    r = rows("SELECT * FROM ticket_messages WHERE ticket_id=? ORDER BY id DESC LIMIT ?", (tid, limit))
    return list(reversed(r))

# ============================================================
#  9) خدمات الإدارة
# ============================================================
def stats():
    one = lambda s, p=(): scalar(s, p)
    today = datetime.now().strftime("%Y-%m-%d")
    return {
        "users": one("SELECT COUNT(*) FROM users"),
        "tg_users": one("SELECT COUNT(*) FROM users WHERE tg_id IS NOT NULL"),
        "banned": one("SELECT COUNT(*) FROM users WHERE is_banned=1"),
        "numbers": one("SELECT COUNT(*) FROM numbers"),
        "available": one("SELECT COUNT(*) FROM numbers WHERE status='available'"),
        "sold": one("SELECT COUNT(*) FROM numbers WHERE status='sold'"),
        "sold_today": one("SELECT COUNT(*) FROM numbers WHERE status='sold' AND date(sold_at)=?", (today,)),
        "revenue": one("SELECT COALESCE(SUM(COALESCE(paid_price, price)),0) FROM numbers WHERE status='sold'"),
        "revenue_today": one("SELECT COALESCE(SUM(COALESCE(paid_price, price)),0) FROM numbers WHERE status='sold' "
                             "AND date(sold_at)=?", (today,)),
        "pending_dep": one("SELECT COUNT(*) FROM deposits WHERE status='pending'"),
        "deposited": one("SELECT COALESCE(SUM(amount_usd),0) FROM deposits WHERE status='approved'"),
        "open_tickets": one("SELECT COUNT(*) FROM tickets WHERE status='open'"),
        "balances": one("SELECT COALESCE(SUM(balance),0) FROM users"),
    }

def admin_add_number(platform, phone, price, premium=0):
    phone = phone.strip().replace(" ", "")
    if not re.match(r"^\+?\d{6,16}$", phone): return False, "رقم غير صالح."
    if not phone.startswith("+"): phone = "+" + phone
    country, flag = detect_country(phone)
    if not country: return False, "لم أتمكن من تحديد الدولة من رمز الرقم (أضف الدولة في أسعار الشراء بالموقع)."
    if row("SELECT 1 FROM numbers WHERE phone=? AND platform=? AND status='available'", (phone, platform)):
        return False, "الرقم معروض للبيع بالفعل."
    nid, _ = run("INSERT INTO numbers(platform,country,phone,price,is_premium) VALUES(?,?,?,?,?)",
                 (platform, country, phone, float(price), int(premium)))
    return True, "%s %s" % (flag or "", country)

def gen_vouchers(amount, count):
    codes = []
    for _ in range(count):
        for _t in range(5):
            code = "MT-" + "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(10))
            try:
                run("INSERT INTO vouchers(code,amount) VALUES(?,?)", (code, amount)); codes.append(code); break
            except sqlite3.IntegrityError:
                continue
    return codes

def add_coupon(code, pct, max_uses, days):
    code = code.strip().upper()
    if not code or not (0 < pct <= 90): return False, "كود غير صالح أو نسبة خارج النطاق (1-90)."
    exp = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S") if days > 0 else None
    try:
        run("INSERT INTO coupons(code,percent,max_uses,expires_at) VALUES(?,?,?,?)", (code, pct, max_uses, exp))
        return True, "تم إنشاء الكوبون."
    except sqlite3.IntegrityError:
        return False, "الكود موجود مسبقاً."

def adjust_balance(uid, amount):
    """amount موجب = إضافة، سالب = خصم (لا يسمح بالسالب)."""
    if amount < 0:
        _, rc = run("UPDATE users SET balance=balance+? WHERE user_id=? AND balance>=?", (amount, uid, -amount))
        return rc == 1
    _, rc = run("UPDATE users SET balance=balance+? WHERE user_id=?", (amount, uid))
    return rc == 1

def db_backup_bytes():
    """نسخة احتياطية متسقة عبر sqlite backup API."""
    tmp = os.path.join(BASE_DIR, ".bot_backup_%d.db" % int(time.time()))
    src = sqlite3.connect(DB_PATH, timeout=30)
    try:
        dst = sqlite3.connect(tmp)
        try: src.backup(dst)
        finally: dst.close()
    finally:
        src.close()
    try:
        with open(tmp, "rb") as f: return f.read()
    finally:
        try: os.remove(tmp)
        except Exception: pass

# مفاتيح الإعدادات القابلة للتعديل من البوت: (key, الوصف, سرّي؟)
SETTING_GROUPS = [
    ("tg", "🤖 Telegram API", [("TG_API_ID", "API ID", False), ("TG_API_HASH", "API Hash", True)]),
    ("mail", "📧 البريد (IMAP) لأكواد واتساب", [("EMAIL_ADDRESS", "الإيميل", False), ("EMAIL_PASSWORD", "كلمة مرور التطبيق", True),
                                              ("WA_EMAIL_ADDRESS", "إيميل واتساب (اختياري)", False),
                                              ("WA_EMAIL_PASSWORD", "باسورد إيميل واتساب", True),
                                              ("IMAP_HOST", "سيرفر IMAP", False)]),
    ("bn", "🟡 Binance", [("BINANCE_API_KEY", "API Key", True), ("BINANCE_API_SECRET", "API Secret", True),
                          ("BINANCE_PAY_ID", "Pay ID", False)]),
    ("pay", "💳 الدفع اليدوي وأسعار الصرف", [("JEEB_ACCOUNT", "حساب جيب", False), ("JEEB_RATE_YE", "جيب: ريال يمني/$", False),
                                          ("JEEB_RATE_SA", "جيب: ريال سعودي/$", False),
                                          ("ONECASH_ACCOUNT", "حساب ون كاش", False), ("ONECASH_RATE_YE", "ون كاش: يمني/$", False),
                                          ("ONECASH_RATE_SA", "ون كاش: سعودي/$", False)]),
    ("gen", "🏪 إعدادات المتجر", [("SITE_NAME", "اسم المتجر", False), ("SUPPORT_USER", "يوزر الدعم", False),
                                ("MIN_DEPOSIT_USD", "أقل مبلغ شحن $", False), ("TRANSFER_FEE", "رسوم التحويل $", False),
                                ("REFERRAL_REWARD", "مكافأة الإحالة $", False), ("DAILY_BONUS", "المكافأة اليومية $", False)]),
]
ALL_SETTING_KEYS = [(k, lbl, sec) for _g, _t, items in SETTING_GROUPS for (k, lbl, sec) in items]

def mask_secret(v):
    v = str(v or "")
    if not v: return "— غير مضبوط —"
    return v[:3] + "•" * 6 + v[-3:] if len(v) > 8 else "•" * len(v)

# ============================================================
#  10) إنشاء البوت + أدوات العرض + القوالب
# ============================================================
bot = telebot.TeleBot(ENV_TOKEN or "0:PLACEHOLDER", parse_mode="HTML", threaded=True, num_threads=10)

e = lambda s: html.escape(str(s if s is not None else ""))
LINE = "━━━━━━━━━━━━━━━━━━━━"
THIN = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"

def usd(x):
    try: x = float(x)
    except Exception: x = 0.0
    return ("$%.4f" % x) if (x != 0 and abs(x) < 0.01) else ("$%.2f" % x)

def site_name(): return get_setting("SITE_NAME", "MATARI STORE") or "MATARI STORE"
def plat_label(p): return "🔵 تيليجرام" if "telegram" in (p or "").lower() else "🟢 واتساب"

class BTN:
    """أنماط الأزرار المدعومة رسمياً في Telegram Bot API (حقل style)"""
    PRIMARY = "primary"   # أزرق  - للعمليات الرئيسية
    SUCCESS = "success"   # أخضر  - للتأكيد والنجاح
    DANGER = "danger"     # أحمر  - للحذف والإلغاء
    DEFAULT = None        # افتراضي

BTN_COLORS = os.environ.get("BTN_COLORS", "1") != "0"   # BTN_COLORS=0 لإيقاف الألوان

class _StyledButton(types.InlineKeyboardButton):
    """زر ملوّن: يضيف حقل style لطلب Bot API. العملاء القدامى يعرضونه بدون لون بلا أي مشكلة."""
    def __init__(self, *a, style=None, **k):
        super().__init__(*a, **k)
        self._style = style
    def to_dict(self):
        d = super().to_dict()
        if self._style: d["style"] = self._style
        return d

def _auto_style(text):
    t = text or ""
    if any(x in t for x in ("❌", "🗑", "🚫", "✖", "⛔", "🔨")): return BTN.DANGER
    if any(x in t for x in ("✅", "➕", "🎁", "🔑", "🛒")): return BTN.SUCCESS
    if any(x in t for x in ("🏠", "👑", "👤", "💰", "📦", "💸", "🎧", "⚙️", "🔗")): return BTN.PRIMARY
    return BTN.DEFAULT

def B(text, data=None, url=None, style=None):
    """زر Inline. style=BTN.SUCCESS/DANGER/PRIMARY لتحديد اللون يدوياً، وإلا يُحدَّد تلقائياً من رمز الزر."""
    st = (style or _auto_style(text)) if BTN_COLORS else None
    if st:
        try:
            return _StyledButton(text, url=url, style=st) if url else _StyledButton(text, callback_data=data, style=st)
        except Exception:
            pass
    if url: return types.InlineKeyboardButton(text, url=url)
    return types.InlineKeyboardButton(text, callback_data=data)

def K(*rws):
    kb = types.InlineKeyboardMarkup()
    for r in rws:
        if not r: continue
        kb.row(*r)
    return kb

def home_row(): return [B("🏠 القائمة الرئيسية", "m")]
def back_row(to, label="◀️ رجوع"): return [B(label, to), B("🏠", "m")]

def send(chat_id, text, kb=None, **kw):
    try:
        return bot.send_message(chat_id, text, reply_markup=kb, disable_web_page_preview=True, **kw)
    except ApiTelegramException as ex:
        logger.warning("send(%s): %s", chat_id, str(ex)[:120])
    except Exception:
        logger.exception("send")
    return None

def show(c, text, kb=None):
    """يعدّل رسالة الأزرار الحالية (تجربة سلسة) وإن تعذّر يرسل رسالة جديدة."""
    try:
        if getattr(c.message, "content_type", "text") == "photo":
            return bot.edit_message_caption(text[:1024], c.message.chat.id, c.message.message_id, reply_markup=kb)
        return bot.edit_message_text(text, c.message.chat.id, c.message.message_id,
                                     reply_markup=kb, disable_web_page_preview=True)
    except ApiTelegramException as ex:
        if "not modified" in str(ex): return None
        return send(c.message.chat.id, text, kb)
    except Exception:
        return send(c.message.chat.id, text, kb)

def toast(c, text="", alert=False):
    try: bot.answer_callback_query(c.id, text, show_alert=alert)
    except Exception: pass

def notify_admins(text, kb=None, photo=None):
    for aid in admin_ids():
        try:
            if photo: bot.send_photo(aid, photo, caption=text, reply_markup=kb)
            else: bot.send_message(aid, text, reply_markup=kb, disable_web_page_preview=True)
        except Exception as ex:
            logger.debug("notify admin %s: %s", aid, str(ex)[:80])

def paginate(total, page, per=PAGE):
    pages = max(1, math.ceil(total / per))
    page = max(0, min(page, pages - 1))
    return page, pages, page * per

def pager_row(prefix, page, pages):
    r = []
    if page > 0: r.append(B("⬅️ السابق", "%s:%d" % (prefix, page - 1)))
    r.append(B("• %d / %d •" % (page + 1, pages), "noop"))
    if page < pages - 1: r.append(B("التالي ➡️", "%s:%d" % (prefix, page + 1)))
    return r

# ---------------- القوالب (Templates) — زخرفة + ترتيب + ألوان ----------------
ORN = "✦━━━━━━━━━━━━━━━━━━✦"
SEP = "╞══════════════════╡"
LEVELS = ["⚪ مبتدئ", "🥉 برونزي", "🥈 فضي", "🥇 ذهبي", "💎 ماسي"]

def money(x):
    """💵 المبلغ مع مؤشر لوني: 🟢 رصيد جيد · 🟡 رصيد قليل · 🔴 صفر."""
    try: v = float(x)
    except Exception: v = 0.0
    dot = "🟢" if v >= 1 else ("🟡" if v > 0 else "🔴")
    return "%s <b>%s</b>" % (dot, usd(v))

def fld(icon, label, value):
    return "┃ %s %s ⟫ %s\n" % (icon, label, value)

def cid_tag(u):
    return "<code>%s</code>" % e(u["custom_id"] or u["user_id"])

def bar(pct, n=10):
    pct = max(0.0, min(100.0, pct)); f = int(round(pct / 100 * n))
    return "▰" * f + "▱" * (n - f) + " %d%%" % int(pct)

def vip_level(spent):
    tiers = []
    for part in (get_setting("VIP_TIERS", "5:3,20:5,50:10") or "").split(","):
        try:
            need, disc = part.strip().split(":"); tiers.append((float(need), float(disc)))
        except Exception:
            continue
    tiers.sort()
    lvl, prev = 0, 0.0
    for i, (need, _d) in enumerate(tiers, 1):
        if spent >= need: lvl, prev = i, need
    nxt = next((n for n, _d in tiers if spent < n), None)
    pct = 100.0 if nxt is None else ((spent - prev) / (nxt - prev) * 100 if nxt > prev else 0)
    return LEVELS[min(lvl, len(LEVELS) - 1)], pct, nxt

class T:
    @staticmethod
    def banner(title, icon="🏪"):
        return "%s\n  %s  <b>%s</b>\n%s\n" % (ORN, icon, e(title), ORN)

    @staticmethod
    def welcome(u, new=False):
        ann = row("SELECT text FROM announcements WHERE is_active=1 ORDER BY id DESC LIMIT 1")
        name = u["tg_name"] or u["username"]
        s = T.banner(site_name())
        s += ("🎉 <b>تم إنشاء حسابك بنجاح!</b>\n" if new else "👋 أهلاً بعودتك،") + " <b>%s</b>\n\n" % e(name)
        s += fld("💵", "الرصيد", money(u["balance"]))
        s += fld("🆔", "الآيدي", cid_tag(u))
        s += fld("📦", "أرقامي", "<b>%d</b>" % count_my_numbers(u["user_id"]))
        if str(u["username"]).startswith("tg_"):
            s += "\n🔐 <b>عندك حساب في الموقع؟</b> سجّل دخولك بنفس حسابك لتظهر أرصدتك ومشترياتك هنا.\n"
        if ann: s += "\n📢 <i>%s</i>\n" % e(ann["text"][:160])
        s += "\n%s\n✨ اختر من القائمة 👇" % THIN
        return s

    @staticmethod
    def wallet(u):
        dep = scalar("SELECT COALESCE(SUM(amount_usd),0) FROM deposits WHERE user_id=? AND status='approved'", (u["user_id"],))
        spent = scalar("SELECT COALESCE(SUM(COALESCE(paid_price,price)),0) FROM numbers WHERE buyer_id=? AND status='sold'", (u["user_id"],))
        pend = scalar("SELECT COUNT(*) FROM deposits WHERE user_id=? AND status='pending'", (u["user_id"],))
        s = T.banner("محفظتي", "💰")
        s += "\n💵 <b>الرصيد الحالي</b>\n   ⟫  %s\n\n%s\n" % (money(u["balance"]), SEP)
        s += fld("📥", "إجمالي الشحن", "<code>%s</code>" % usd(dep))
        s += fld("🛍", "إجمالي المشتريات", "<code>%s</code>" % usd(spent))
        s += fld("🆔", "آيدي التحويل", cid_tag(u))
        if pend: s += fld("⏳", "طلبات شحن معلّقة", "<b>%d</b>" % pend)
        return s

    @staticmethod
    def profile(u):
        uid = u["user_id"]
        dep = scalar("SELECT COALESCE(SUM(amount_usd),0) FROM deposits WHERE user_id=? AND status='approved'", (uid,))
        spent = scalar("SELECT COALESCE(SUM(COALESCE(paid_price,price)),0) FROM numbers WHERE buyer_id=? AND status='sold'", (uid,))
        cnt = scalar("SELECT COUNT(*) FROM numbers WHERE buyer_id=? AND status='sold'", (uid,))
        refs = scalar("SELECT COUNT(*) FROM users WHERE referred_by=?", (uid,))
        lvl, pct, nxt = vip_level(float(spent or 0))
        s = T.banner("حسابي", "👤")
        s += fld("🧾", "الاسم", "<b>%s</b>" % e(u["tg_name"] or u["username"]))
        s += fld("🆔", "الآيدي", cid_tag(u))
        if u["tg_username"]: s += fld("✈️", "تيليجرام", "@%s" % e(u["tg_username"]))
        s += fld("📅", "انضم", "<code>%s</code>" % e((u["created_at"] or "")[:10]))
        s += SEP + "\n"
        s += fld("💵", "الرصيد", money(u["balance"]))
        s += fld("📥", "إجمالي الشحن", "<code>%s</code>" % usd(dep))
        s += fld("🛍", "إجمالي المشتريات", "<code>%s</code>" % usd(spent))
        s += fld("📦", "الأرقام المشتراة", "<b>%d</b>" % cnt)
        s += fld("👥", "المدعوّون", "<b>%d</b>" % refs)
        s += SEP + "\n"
        s += fld("🏅", "المستوى", "<b>%s</b>" % lvl)
        s += "   <code>%s</code>\n" % bar(pct)
        s += ("   ⬆️ المستوى التالي عند مشتريات <b>%s</b>\n" % usd(nxt)) if nxt else "   🌟 وصلت لأعلى مستوى!\n"
        return s

    @staticmethod
    def number_card(n, bal=None, pct=0.0, coupon=None):
        price = final_price(n["price"], pct)
        s = T.banner("تفاصيل الرقم", "📱")
        s += fld("📡", "المنصة", plat_label(n["platform"]))
        s += fld("🌍", "الدولة", "%s <b>%s</b>" % (flag_of(n["country"]), e(n["country"])))
        s += fld("☎️", "الرقم", "<code>%s</code>" % e(mask_phone(n["phone"])))
        if n["is_premium"]: s += fld("💎", "النوع", "<b>رقم مميز</b>")
        st = stamps_of(n["id"])
        if st: s += fld("🏅", "الشارات", " • ".join(e(x) for x in st))
        s += SEP + "\n"
        if pct:
            s += fld("🏷", "السعر الأصلي", "<s>%s</s>" % usd(n["price"]))
            s += fld("🎟", "الكوبون", "<code>%s</code> (−%g%%)" % (e(coupon), pct))
        s += fld("💳", "السعر", "<b>%s</b>" % usd(price))
        if bal is not None:
            s += fld("💵", "رصيدك", money(bal))
            if bal < price: s += "┃ ⚠️ ينقصك <b>%s</b>\n" % usd(price - bal)
        return s

    @staticmethod
    def purchased(n, paid):
        s = T.banner("تمت عملية الشراء", "✅")
        s += fld("📡", "المنصة", plat_label(n["platform"]))
        s += fld("🌍", "الدولة", "%s <b>%s</b>" % (flag_of(n["country"]), e(n["country"])))
        s += fld("💳", "المدفوع", "<b>%s</b>" % usd(paid))
        s += SEP + "\n☎️ الرقم (اضغط للنسخ):\n<code>%s</code>\n" % e(n["phone"])
        s += "\n%s\n⏳ جاري البحث عن كود التفعيل تلقائياً… سيصلك هنا فور وصوله.\n🔑 أو اضغط «سحب الكود» بعد طلبه من التطبيق." % THIN
        return s

    @staticmethod
    def code_card(n, code):
        s = T.banner("كود التفعيل", "🔑")
        s += fld("📡", "المنصة", plat_label(n["platform"]))
        s += fld("☎️", "الرقم", "<code>%s</code>" % e(n["phone"]))
        s += "\n┏━━━━━━━━━━━━━━┓\n    🔐  <b><code>%s</code></b>\n┗━━━━━━━━━━━━━━┛\n" % e(code)
        s += "\n⚠️ لا تشارك الكود مع أي شخص."
        return s

    @staticmethod
    def my_number(n):
        s = T.banner("رقمي", "📦")
        s += fld("📡", "المنصة", plat_label(n["platform"]))
        s += fld("🌍", "الدولة", "%s <b>%s</b>" % (flag_of(n["country"]), e(n["country"])))
        s += fld("☎️", "الرقم", "<code>%s</code>" % e(n["phone"]))
        s += fld("💳", "دفعت", "<b>%s</b>" % usd(n["paid_price"] if n["paid_price"] is not None else n["price"]))
        s += fld("🕒", "الشراء", "<code>%s</code>" % e(n["sold_at"]))
        if n["last_code"]: s += SEP + "\n" + fld("🔑", "آخر كود", "<code>%s</code>" % e(n["last_code"]))
        return s

    @staticmethod
    def deposit_notice(d, u, extra=""):
        s = T.banner("طلب شحن جديد", "💳")
        s += fld("👤", "العميل", "%s (%s)" % (e(u["tg_name"] or u["username"]), cid_tag(u)))
        s += fld("🏦", "الطريقة", "<b>%s</b>" % e(d["method"]))
        s += fld("💵", "المبلغ", "<b>%s</b>" % usd(d["amount_usd"]))
        if d["trans_id"]: s += fld("🧾", "المرجع", "<code>%s</code>" % e(d["trans_id"]))
        s += fld("🆔", "طلب رقم", "<code>%d</code>" % d["id"])
        return s + extra

# ---------------- الحالات (State machine للنصوص) ----------------
STATE = {}
STATE_LOCK = threading.Lock()
COUPONS = {}   # (tg_id, nid) -> code

def set_state(tg, step, **data):
    with STATE_LOCK: STATE[tg] = {"step": step, "data": data, "ts": time.time()}

def get_state(tg):
    with STATE_LOCK:
        st = STATE.get(tg)
        if st and time.time() - st["ts"] > 1800:
            STATE.pop(tg, None); return None
        return st

def touch_state(tg):
    with STATE_LOCK:
        if tg in STATE: STATE[tg]["ts"] = time.time()

def clear_state(tg):
    with STATE_LOCK: STATE.pop(tg, None)

STEPS = {}
def step(name):
    def deco(fn): STEPS[name] = fn; return fn
    return deco

CB = {}
def cb(name, admin=False):
    def deco(fn): CB[name] = (fn, admin); return fn
    return deco

def del_msg(m):
    try: bot.delete_message(m.chat.id, m.message_id)
    except Exception: pass

def ask(chat_id, text, cancel_to="m"):
    return send(chat_id, text + "\n\n<i>للإلغاء اضغط الزر أدناه أو أرسل /cancel</i>", K([B("✖️ إلغاء", cancel_to)]))

# ---------------- هوية المستخدم + الحظر ----------------
def ctx_user(tg_user, ref=None):
    u, new = register_tg_user(tg_user.id, tg_user.username,
                              ((tg_user.first_name or "") + " " + (tg_user.last_name or "")).strip() or None, ref)
    return u, new

def banned_guard(chat_id, u):
    if u["is_banned"]:
        send(chat_id, "🚫 <b>حسابك محظور.</b>\nللاستفسار تواصل مع الدعم: %s" % e(get_setting("SUPPORT_USER", "")))
        return True
    return False

def main_kb(tg_id):
    rows_ = [
        [B("🛒 المتجر", "shop"), B("👤 حسابي", "prof")],
        [B("💰 محفظتي", "wal"), B("➕ شحن الرصيد", "dep")],
        [B("📦 أرقامي", "my:0"), B("💸 تحويل رصيد", "tr")],
        [B("💰 بيع رقم", "sell"), B("🎁 مكافأة يومية", "bonus")],
        [B("🎧 الدعم الفني", "sup"), B("👥 الإحالات", "ref")],
        [B("🔗 ربط حساب الموقع", "lnk"), B("🔐 بيانات الموقع", "acc")],
    ]
    me = user_by_tg(tg_id)
    if me and str(me["username"]).startswith("tg_"):      # حساب مؤقت بالبوت = غير مربوط بحساب الموقع
        rows_.insert(0, [B("🔐 تسجيل الدخول بحساب الموقع", "lnk", style=BTN.PRIMARY)])
    if is_admin_tg(tg_id): rows_.append([B("👑 لوحة المدير", "a")])
    return K(*rows_)

def go_home(chat_id, tg_user, c=None, new=False):
    u, _ = ctx_user(tg_user)
    if banned_guard(chat_id, u): return
    text, kb = T.welcome(u, new), main_kb(tg_user.id)
    if c: show(c, text, kb)
    else: send(chat_id, text, kb)

# ============================================================
#  11) الأوامر
# ============================================================
@bot.message_handler(commands=["start"])
def cmd_start(m):
    clear_state(m.from_user.id)
    parts = (m.text or "").split(maxsplit=1)
    ref = None
    if len(parts) > 1 and parts[1].startswith("ref_"): ref = parts[1][4:]
    u, new = ctx_user(m.from_user, ref)
    if banned_guard(m.chat.id, u): return
    send(m.chat.id, T.welcome(u, new), main_kb(m.from_user.id))
    if new:
        notify_admins("👤 <b>مستخدم جديد عبر البوت</b>\n%s  <code>%s</code>\n🆔 <code>%s</code>%s" % (
            e(u["tg_name"] or ""), e("@" + u["tg_username"] if u["tg_username"] else ""), e(u["custom_id"]),
            ("\n🔗 إحالة من: <code>%s</code>" % u["referred_by"]) if u["referred_by"] else ""))

@bot.message_handler(commands=["menu", "help"])
def cmd_menu(m):
    clear_state(m.from_user.id); go_home(m.chat.id, m.from_user)

@bot.message_handler(commands=["cancel"])
def cmd_cancel(m):
    clear_state(m.from_user.id)
    send(m.chat.id, "✅ تم الإلغاء.", K(home_row()))

@bot.message_handler(commands=["balance"])
def cmd_balance(m):
    u, _ = ctx_user(m.from_user)
    if banned_guard(m.chat.id, u): return
    send(m.chat.id, T.wallet(u), K([B("➕ شحن", "dep"), B("💸 تحويل", "tr")], home_row()))

@bot.message_handler(commands=["admin"])
def cmd_admin(m):
    if not is_admin_tg(m.from_user.id):
        return send(m.chat.id, "⛔ هذا الأمر للمدير فقط.")
    clear_state(m.from_user.id)
    send(m.chat.id, admin_home_text(), admin_home_kb())

# ============================================================
#  12) موزّع الأزرار المركزي
# ============================================================
@bot.callback_query_handler(func=lambda c: True)
def on_callback(c):
    try:
        parts = (c.data or "").split(":")
        name, args = parts[0], parts[1:]
        if name == "noop": return toast(c)
        hit = CB.get(name)
        if not hit: return toast(c, "الزر منتهي الصلاحية، افتح القائمة من جديد.")
        fn, need_admin = hit
        if need_admin and not is_admin_tg(c.from_user.id):
            return toast(c, "⛔ للمدير فقط.", True)
        u, _ = ctx_user(c.from_user)
        if u["is_banned"]:
            return toast(c, "🚫 حسابك محظور.", True)
        fn(c, u, args)
    except Exception:
        logger.error("callback %s failed:\n%s", c.data, traceback.format_exc())
        toast(c, "حدث خطأ غير متوقع، حاول مجدداً.", True)

@cb("m")
def cb_home(c, u, a):
    clear_state(c.from_user.id); toast(c)
    show(c, T.welcome(u), main_kb(c.from_user.id))

# ============================================================
#  13) المتجر
# ============================================================
@cb("shop")
def cb_shop(c, u, a):
    toast(c); clear_state(c.from_user.id)
    wa = scalar("SELECT COUNT(*) FROM numbers WHERE status='available' AND %s" % plat_filter("wa"))
    tg = scalar("SELECT COUNT(*) FROM numbers WHERE status='available' AND %s" % plat_filter("tg"))
    s = T.banner("المتجر", "🛒") + "اختر المنصة المطلوبة:\n\n🟢 واتساب  ‹ <b>%d</b> رقم متاح ›\n🔵 تيليجرام  ‹ <b>%d</b> رقم متاح ›\n" % (wa, tg)
    show(c, s, K([B("🟢 واتساب (%d)" % wa, "sh:wa:0"), B("🔵 تيليجرام (%d)" % tg, "sh:tg:0")], home_row()))

@cb("sh")
def cb_shop_countries(c, u, a):
    toast(c); pf, page = a[0], int(a[1])
    cs = countries_for(pf)
    page, pages, off = paginate(len(cs), page, 8)
    s = T.banner("اختر الدولة", "🌍") + "%s\n" % ("🟢 واتساب" if pf == "wa" else "🔵 تيليجرام")
    if not cs: s += "\n😔 لا توجد أرقام متاحة حالياً. عد لاحقاً."
    btns = [B("%s %s · %d · %s" % (flag_of(r["country"]), r["country"], r["c"], usd(r["mp"])),
              "nl:%s:%s:0" % (pf, country_key(r["country"]))) for r in cs[off:off + 8]]
    kb = [btns[i:i + 2] for i in range(0, len(btns), 2)]
    if pages > 1: kb.append(pager_row("sh:" + pf, page, pages))
    kb.append(back_row("shop"))
    show(c, s, K(*kb))

@cb("nl")
def cb_number_list(c, u, a):
    toast(c); pf, ck, page = a[0], a[1], int(a[2])
    country = resolve_country(ck)
    if not country: return show(c, "الدولة غير متاحة حالياً.", K(back_row("sh:%s:0" % pf)))
    total = count_numbers_for(pf, country)
    page, pages, off = paginate(total, page)
    s = T.banner("%s %s" % (flag_of(country), country), "📱") + "%s · <b>%d</b> رقم متاح\n" % (
        "🟢 واتساب" if pf == "wa" else "🔵 تيليجرام", total)
    kb = []
    for n in numbers_for(pf, country, off):
        kb.append([B("%s%s  ·  %s" % ("💎 " if n["is_premium"] else "", mask_phone(n["phone"]), usd(n["price"])), "nd:%d" % n["id"])])
    if pages > 1: kb.append(pager_row("nl:%s:%s" % (pf, ck), page, pages))
    kb.append(back_row("sh:%s:0" % pf))
    show(c, s, K(*kb))

def _number_screen(c, u, nid):
    n = row("SELECT * FROM numbers WHERE id=?", (nid,))
    if not n or n["status"] != "available":
        return show(c, "😔 عذراً، هذا الرقم لم يعد متاحاً.", K([B("🛒 المتجر", "shop")], home_row()))
    code = COUPONS.get((c.from_user.id, nid))
    pct = 0.0
    if code:
        p, err = coupon_check(code, u["user_id"])
        if p is None: COUPONS.pop((c.from_user.id, nid), None); code = None
        else: pct = p
    u = user_by_id(u["user_id"])
    price = final_price(n["price"], pct)
    kb = [[B("🛒 شراء الآن  ‹ %s ›" % usd(price), "nb:%d" % nid)],
          [B("🎟 لدي كوبون خصم", "nc:%d" % nid)],
          back_row("nl:%s:%s:0" % (pf_of(n["platform"]), country_key(n["country"])))]
    if u["balance"] < price:
        kb.insert(1, [B("➕ اشحن رصيدك (ينقصك %s)" % usd(price - u["balance"]), "dep")])
    show(c, T.number_card(n, u["balance"], pct, code), K(*kb))

@cb("nd")
def cb_number_detail(c, u, a):
    toast(c); _number_screen(c, u, int(a[0]))

@cb("nc")
def cb_coupon_ask(c, u, a):
    toast(c); set_state(c.from_user.id, "coupon", nid=int(a[0]))
    ask(c.message.chat.id, "🎟 أرسل <b>كود الكوبون</b> الآن:", "nd:%s" % a[0])

@step("coupon")
def step_coupon(m, st):
    nid = st["data"]["nid"]; clear_state(m.from_user.id)
    u, _ = ctx_user(m.from_user)
    code = (m.text or "").strip().upper()
    pct, err = coupon_check(code, u["user_id"])
    if pct is None:
        return send(m.chat.id, "❌ %s" % e(err), K([B("🔁 جرّب كوبون آخر", "nc:%d" % nid)], [B("◀️ رجوع للرقم", "nd:%d" % nid)]))
    COUPONS[(m.from_user.id, nid)] = code
    send(m.chat.id, "✅ تم تفعيل الكوبون <code>%s</code> — خصم <b>%g%%</b>" % (e(code), pct), K([B("➡️ متابعة", "nd:%d" % nid)]))

@cb("nb")
def cb_buy_confirm(c, u, a):
    toast(c); nid = int(a[0])
    n = row("SELECT * FROM numbers WHERE id=?", (nid,))
    if not n or n["status"] != "available":
        return show(c, "😔 الرقم لم يعد متاحاً.", K([B("🛒 المتجر", "shop")]))
    code = COUPONS.get((c.from_user.id, nid)); pct = 0.0
    if code:
        p, _e = coupon_check(code, u["user_id"]); pct = p or 0.0
    price = final_price(n["price"], pct)
    s = ("⚠️ <b>تأكيد الشراء</b>\n%s\n%s %s\n☎️ <code>%s</code>\n💳 سيتم خصم  <b>%s</b>  من رصيدك\n\n"
         "هل تريد المتابعة؟") % (LINE, flag_of(n["country"]), e(n["country"]), e(mask_phone(n["phone"])), usd(price))
    show(c, s, K([B("✅ نعم، اشترِ", "ny:%d" % nid, style=BTN.SUCCESS), B("❌ إلغاء", "nd:%d" % nid, style=BTN.DANGER)]))

@cb("ny")
def cb_buy_do(c, u, a):
    nid = int(a[0]); coupon = COUPONS.get((c.from_user.id, nid))
    ok, msg, n = buy_number(u["user_id"], nid, coupon)
    if not ok:
        toast(c, "❌ " + msg, True)
        return show(c, "❌ <b>تعذّر الشراء</b>\n%s" % e(msg),
                    K([B("➕ شحن الرصيد", "dep")], [B("🛒 المتجر", "shop")], home_row()))
    toast(c, "✅ تم الشراء")
    COUPONS.pop((c.from_user.id, nid), None)
    paid = n["paid_price"]
    show(c, T.purchased(n, paid), K([B("🔑 سحب الكود", "otp:%d" % nid)], [B("📦 أرقامي", "my:0"), B("🏠", "m")]))
    buyer = user_by_id(u["user_id"])
    notify_admins("🛍 <b>عملية شراء جديدة</b> (بوت)\n👤 %s  <code>%s</code>\n%s %s <code>%s</code>\n💳 %s  ·  💰 رصيده الآن %s" % (
        e(buyer["tg_name"] or buyer["username"]), e(buyer["custom_id"]), plat_label(n["platform"]),
        e(n["country"]), e(n["phone"]), usd(paid), usd(buyer["balance"])))
    if get_setting("BOT_AUTO_OTP", "1") == "1":
        threading.Thread(target=auto_otp_worker, args=(c.message.chat.id, u["user_id"], nid), daemon=True).start()

def auto_otp_worker(chat_id, uid, nid):
    """بحث تلقائي عن الكود بعد الشراء (مثل auto_fetch_otp في الموقع) — يُرسل الكود فور وصوله."""
    start = time.time(); since = start - 60
    time.sleep(8)
    while time.time() - start < AUTO_OTP_SECONDS:
        try:
            if get_setting("BOT_AUTO_OTP", "1") != "1": return
            n = row("SELECT * FROM numbers WHERE id=? AND buyer_id=? AND COALESCE(hidden_for_buyer,0)=0", (nid, uid))
            if not n: return
            code, err = request_otp(uid, nid, force_since=since)
            if code:
                send(chat_id, T.code_card(n, code), K([B("🔄 كود جديد", "otp:%d" % nid)], [B("📦 أرقامي", "my:0"), B("🏠", "m")]))
                return
        except Exception:
            logger.exception("auto_otp")
        time.sleep(OTP_COOLDOWN + 1)
    send(chat_id, "⌛ لم يصل كود تلقائياً بعد.\nاطلب الكود من التطبيق ثم اضغط «سحب الكود».",
         K([B("🔑 سحب الكود", "otp:%d" % nid)]))

@cb("otp")
def cb_otp(c, u, a):
    nid = int(a[0]); toast(c, "⏳ جاري البحث عن الكود…")
    n = row("SELECT * FROM numbers WHERE id=? AND buyer_id=?", (nid, u["user_id"]))
    code, err = request_otp(u["user_id"], nid)
    if code:
        send(c.message.chat.id, T.code_card(n, code), K([B("🔄 كود جديد", "otp:%d" % nid)], [B("📦 أرقامي", "my:0"), B("🏠", "m")]))
    else:
        toast(c, "⌛ " + (err or "لا يوجد كود"), True)

@cb("my")
def cb_my(c, u, a):
    toast(c); total = count_my_numbers(u["user_id"])
    page, pages, off = paginate(total, int(a[0]))
    s = T.banner("أرقامي", "📦") + "إجمالي أرقامك: <b>%d</b>\n" % total
    if not total: s += "\nلا توجد مشتريات بعد. ابدأ من المتجر 🛒"
    kb = []
    for n in my_numbers(u["user_id"], off):
        kb.append([B("%s %s · %s" % ("🔵" if "telegram" in (n["platform"] or "").lower() else "🟢", n["phone"], flag_of(n["country"])), "mn:%d" % n["id"])])
    if pages > 1: kb.append(pager_row("my", page, pages))
    kb.append([B("🛒 المتجر", "shop"), B("🏠", "m")])
    show(c, s, K(*kb))

@cb("mn")
def cb_my_number(c, u, a):
    toast(c); nid = int(a[0])
    n = row("SELECT * FROM numbers WHERE id=? AND buyer_id=?", (nid, u["user_id"]))
    if not n: return show(c, "الرقم غير موجود.", K([B("📦 أرقامي", "my:0")]))
    show(c, T.my_number(n), K([B("🔑 سحب الكود", "otp:%d" % nid)],
                              [B("🗑 إخفاء من قائمتي", "hid:%d" % nid)], back_row("my:0")))

@cb("hid")
def cb_hide(c, u, a):
    hide_number(u["user_id"], int(a[0])); toast(c, "🗑 تم الإخفاء")
    cb_my(c, u, ["0"])

# ============================================================
#  14) المحفظة / السجل / المكافأة / الإحالة
# ============================================================
@cb("wal")
def cb_wallet(c, u, a):
    toast(c)
    show(c, T.wallet(u), K([B("➕ شحن الرصيد", "dep"), B("💸 تحويل", "tr")], [B("📜 سجل العمليات", "hist")], home_row()))

@cb("hist")
def cb_history(c, u, a):
    toast(c); uid = u["user_id"]; ev = []
    for d in rows("SELECT * FROM deposits WHERE user_id=? ORDER BY id DESC LIMIT 8", (uid,)):
        ic = {"approved": "✅", "pending": "⏳", "rejected": "❌"}.get(d["status"], "•")
        ev.append((d["created_at"] or "", "%s شحن %s  %s" % (ic, e(d["method"]), usd(d["amount_usd"]))))
    for t in rows("SELECT * FROM transfers WHERE from_id=? OR to_id=? ORDER BY id DESC LIMIT 8", (uid, uid)):
        out = t["from_id"] == uid
        ev.append((t["created_at"] or "", "%s تحويل %s  %s" % ("📤" if out else "📥", "صادر" if out else "وارد", usd(t["amount"]))))
    for n in rows("SELECT * FROM numbers WHERE buyer_id=? AND status='sold' ORDER BY sold_at DESC LIMIT 8", (uid,)):
        ev.append((n["sold_at"] or "", "🛍 شراء %s  %s" % (e(n["country"]), usd(n["paid_price"] if n["paid_price"] is not None else n["price"]))))
    ev.sort(key=lambda x: x[0], reverse=True)
    s = T.banner("سجل العمليات", "📜")
    s += "\n".join("<code>%s</code>  %s" % (e(t[:16]), line) for t, line in ev[:12]) if ev else "لا توجد عمليات بعد."
    show(c, s, K(back_row("wal")))

@cb("bonus")
def cb_bonus(c, u, a):
    ok, msg, amt = claim_bonus(u["user_id"])
    toast(c, ("🎁 +%s" % usd(amt)) if ok else msg, not ok)
    if ok:
        u = user_by_id(u["user_id"])
        show(c, T.banner("المكافأة اليومية", "🎁") + "🎉 تمت إضافة <b>%s</b> إلى رصيدك!\n💰 رصيدك الآن: <code>%s</code>\n\nعد غداً لمكافأة جديدة ✨" % (usd(amt), usd(u["balance"])), K(home_row()))

@cb("ref")
def cb_referral(c, u, a):
    toast(c)
    uname = bot_username()
    cnt = scalar("SELECT COUNT(*) FROM users WHERE referred_by=?", (u["user_id"],))
    link = "https://t.me/%s?start=ref_%s" % (uname, u["user_id"])
    s = T.banner("نظام الإحالة", "👥")
    s += "ادعُ أصدقاءك واربح <b>%s</b> عن كل صديق يُجري أول عملية شراء!\n\n🔗 رابطك:\n<code>%s</code>\n\n👥 عدد المدعوّين:  <b>%d</b>\n💎 أرباحك:  <b>%s</b>" % (
        usd(fsetting("REFERRAL_REWARD", 0.001)), e(link), cnt, usd(u["referral_earnings"] or 0))
    show(c, s, K(home_row()))

# ============================================================
#  15) الشحن والإيداع
# ============================================================
PAY_METHODS = {"jeeb": ("جيب", "JEEB"), "onecash": ("ون كاش", "ONECASH"), "binance": ("Binance Pay", "BINANCE")}

@cb("dep")
def cb_deposit(c, u, a):
    toast(c); clear_state(c.from_user.id)
    s = T.banner("شحن الرصيد", "➕") + "اختر طريقة الشحن:\n\n🎟 <b>كود شحن</b> — فوري\n💳 <b>جيب / ون كاش</b> — تحويل يدوي بمراجعة سريعة\n🟡 <b>Binance Pay</b> — تحقق تلقائي أو مراجعة\n\n💵 أقل مبلغ: <b>%s</b>" % usd(fsetting("MIN_DEPOSIT_USD", 0.10))
    show(c, s, K([B("🎟 كود شحن", "dv")], [B("💳 جيب", "dp:jeeb"), B("💳 ون كاش", "dp:onecash")],
                 [B("🟡 Binance Pay", "dp:binance")], home_row()))

@cb("dv")
def cb_voucher(c, u, a):
    toast(c); set_state(c.from_user.id, "voucher")
    ask(c.message.chat.id, "🎟 أرسل <b>كود الشحن</b> الآن (مثال: <code>MT-XXXXXXXXXX</code>):", "dep")

@step("voucher")
def step_voucher(m, st):
    u, _ = ctx_user(m.from_user)
    ok, msg, amt = redeem_voucher(u["user_id"], m.text or "")
    if ok:
        clear_state(m.from_user.id); u = user_by_id(u["user_id"])
        send(m.chat.id, T.banner("تم الشحن", "✅") + "💵 أُضيف  <b>%s</b>\n💰 رصيدك الآن:  <code>%s</code>" % (usd(amt), usd(u["balance"])),
             K([B("🛒 تسوّق الآن", "shop"), B("🏠", "m")]))
        notify_admins("🎟 <b>شحن بكود</b>\n👤 %s <code>%s</code>\n💵 %s" % (e(u["tg_name"] or u["username"]), e(u["custom_id"]), usd(amt)))
    else:
        touch_state(m.from_user.id)
        send(m.chat.id, "❌ %s\nأرسل كوداً آخر أو اضغط إلغاء." % e(msg), K([B("✖️ إلغاء", "dep")]))

@cb("dp")
def cb_dep_method(c, u, a):
    toast(c); m_ = a[0]
    if m_ not in PAY_METHODS: return
    label, pre = PAY_METHODS[m_]
    acct = get_setting(pre + "_ACCOUNT" if m_ != "binance" else "BINANCE_PAY_ID", "") or "—"
    s = T.banner("الشحن عبر " + label, "💳")
    s += "📌 أرسل المبلغ إلى:\n<code>%s</code>\n" % e(acct)
    if m_ != "binance":
        s += "\n💱 أسعار الصرف:\n  🇾🇪 1$ = <b>%s</b> ريال يمني\n  🇸🇦 1$ = <b>%s</b> ريال سعودي\n" % (
            e(get_setting(pre + "_RATE_YE", "—")), e(get_setting(pre + "_RATE_SA", "—")))
    else:
        s += "\n💡 بعد الدفع أرسل <b>رقم العملية (Order ID)</b> وسنتحقق تلقائياً.\n"
    s += "\n%s\n✏️ الآن أرسل <b>المبلغ بالدولار</b> الذي حوّلته (مثال: <code>2.5</code>):" % THIN
    set_state(c.from_user.id, "dep_amount", method=m_)
    show(c, s, K([B("✖️ إلغاء", "dep")]))

@step("dep_amount")
def step_dep_amount(m, st):
    try: amt = float((m.text or "").replace(",", ".").replace("$", "").strip())
    except ValueError: return send(m.chat.id, "❌ أرسل رقماً صحيحاً مثل <code>2.5</code>")
    mn = fsetting("MIN_DEPOSIT_USD", 0.10)
    if amt < mn: return send(m.chat.id, "❌ أقل مبلغ للشحن %s" % usd(mn))
    meth = st["data"]["method"]; label, pre = PAY_METHODS[meth]
    extra = ""
    if meth != "binance":
        try:
            ye = amt * float(get_setting(pre + "_RATE_YE", 0)); sa = amt * float(get_setting(pre + "_RATE_SA", 0))
            extra = "\n💱 يعادل:  <b>%s</b> ريال يمني  |  <b>%s</b> ريال سعودي\n" % (format(round(ye), ","), format(round(sa, 2), ","))
        except Exception: pass
    set_state(m.from_user.id, "dep_ref", method=meth, amount=amt)
    send(m.chat.id, "💵 المبلغ:  <b>%s</b>%s\n\n🧾 الآن أرسل <b>رقم العملية / المرجع</b> أو <b>صورة الإيصال</b>:" % (usd(amt), extra),
         K([B("✖️ إلغاء", "dep")]))

@step("dep_ref")
def step_dep_ref(m, st):
    u, _ = ctx_user(m.from_user)
    meth, amt = st["data"]["method"], st["data"]["amount"]
    file_id = None; ref = None
    if m.content_type == "photo":
        file_id = m.photo[-1].file_id; ref = (m.caption or "").strip() or "إيصال-تيليجرام-%d" % int(time.time())
    elif m.content_type == "text":
        ref = (m.text or "").strip()
    if not ref: return send(m.chat.id, "❌ أرسل رقم العملية أو صورة الإيصال.")
    if meth == "binance" and file_id is None:
        ok, why = binance_auto_verify(ref, amt) if get_setting("BINANCE_API_KEY", "") else (False, "")
        did, err = create_deposit(u["user_id"], meth, amt, ref)
        if err: return send(m.chat.id, "❌ %s" % e(err), K([B("◀️ رجوع", "dep")]))
        clear_state(m.from_user.id)
        if ok:
            approve_deposit(did); BOT_MARK("dep_status", did); u2 = user_by_id(u["user_id"])
            send(m.chat.id, T.banner("تم التحقق تلقائياً", "✅") + "💵 أُضيف <b>%s</b> لرصيدك\n💰 رصيدك: <code>%s</code>" % (usd(amt), usd(u2["balance"])),
                 K([B("🛒 تسوّق", "shop"), B("🏠", "m")]))
            return notify_admins("🟡 <b>Binance — تأكيد تلقائي</b>\n👤 %s <code>%s</code>\n💵 %s  🧾 <code>%s</code>" % (e(u["tg_name"] or u["username"]), e(u["custom_id"]), usd(amt), e(ref)))
    else:
        did, err = create_deposit(u["user_id"], meth, amt, ref, file_id)
        if err: return send(m.chat.id, "❌ %s" % e(err), K([B("◀️ رجوع", "dep")]))
        clear_state(m.from_user.id)
    send(m.chat.id, T.banner("تم استلام طلبك", "⏳") + "🆔 رقم الطلب: <code>%d</code>\n💵 %s\nسيتم إشعارك فور المراجعة ✅" % (did, usd(amt)), K(home_row()))
    d = row("SELECT * FROM deposits WHERE id=?", (did,))
    notify_admins(T.deposit_notice(d, u), K([B("✅ موافقة", "a_da:%d" % did, style=BTN.SUCCESS), B("❌ رفض", "a_dr:%d" % did, style=BTN.DANGER)]), photo=file_id)


# ============================================================
#  بيع الرقم (مطابق لقسم البيع في الموقع): طلب الكود، التحقق، كلمة سر 2FA، ثم مراجعة الإدارة
# ============================================================
def sell_db_init():
    """ينشئ جداول البيع المؤقتة إذا ما كانت موجودة (نفس أسماء جداول الموقع)."""
    run("CREATE TABLE IF NOT EXISTS temp_sessions (phone TEXT PRIMARY KEY, session_str TEXT, code_hash TEXT, created_at TEXT)")
    run("CREATE TABLE IF NOT EXISTS pending_sellers (number_id INTEGER, user_id INTEGER, created_at TEXT)")


def sell_normalize_phone(text):
    """يحول النص لرقم دولي بصيغة +digits، أو يرجع None إذا كان غير صالح."""
    phone = re.sub(r"[\s\-]", "", text or "")
    if phone and not phone.startswith("+"):
        phone = "+" + phone
    return phone if re.fullmatch(r"\+\d{7,15}", phone) else None


def sell_duplicate(phone):
    """True إذا الرقم معروض للبيع بالفعل في تيليجرام."""
    return bool(row("SELECT 1 FROM numbers WHERE phone=? AND platform LIKE 'telegram%' AND status='available'", (phone,)))


def _has_telethon():
    try:
        import telethon  # noqa: F401
        return True
    except ImportError:
        return False


def _tg_sell_creds():
    api_id = int(get_setting("TG_API_ID", "22651991") or 22651991)
    api_hash = (get_setting("TG_API_HASH", "") or "").strip()
    return api_id, api_hash


def _tg_sell_run(coro, timeout=60):
    return asyncio.run(asyncio.wait_for(coro, timeout))


def tg_sell_request_code(phone):
    """يرسل كود تيليجرام للرقم. يرجع (session, code_hash, error)."""
    if not _has_telethon():
        return None, None, "مكتبة telethon غير مثبتة"
    api_id, api_hash = _tg_sell_creds()
    if not api_hash:
        return None, None, "API Hash غير مهيأ في الإعدادات"
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    async def run():
        client = TelegramClient(StringSession(), api_id, api_hash)
        await client.connect()
        try:
            sent = await client.send_code_request(phone)
            return client.session.save(), sent.phone_code_hash, None
        finally:
            await client.disconnect()
    try:
        return _tg_sell_run(run())
    except Exception as e:
        return None, None, "خطأ: %s" % str(e)[:100]


def tg_sell_verify_code(phone, code, session_str, code_hash):
    """يتحقق من الكود. يرجع (session, status, error) حيث status = ok أو 2fa."""
    if not _has_telethon():
        return None, "error", "مكتبة telethon غير مثبتة"
    api_id, api_hash = _tg_sell_creds()
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from telethon.errors import SessionPasswordNeededError

    async def run():
        client = TelegramClient(StringSession(session_str), api_id, api_hash)
        await client.connect()
        try:
            try:
                await client.sign_in(phone=phone, code=code, phone_code_hash=code_hash)
                return client.session.save(), "ok", None
            except SessionPasswordNeededError:
                return client.session.save(), "2fa", None
        finally:
            await client.disconnect()
    try:
        return _tg_sell_run(run())
    except Exception as e:
        return None, "error", "خطأ: %s" % str(e)[:100]


def tg_sell_verify_password(session_str, password):
    """يدخل كلمة سر 2FA للجلسة الجزئية. يرجع (session, error)."""
    api_id, api_hash = _tg_sell_creds()
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    async def run():
        client = TelegramClient(StringSession(session_str), api_id, api_hash)
        await client.connect()
        try:
            await client.sign_in(password=password)
            return client.session.save(), None
        finally:
            await client.disconnect()
    try:
        return _tg_sell_run(run())
    except Exception as e:
        return None, "كلمة السر غير صحيحة أو خطأ: %s" % str(e)[:80]


def tg_sell_check(session_str):
    """يتأكد أن الجلسة شغالة، ويرجع (ok, has_2fa, error)."""
    api_id, api_hash = _tg_sell_creds()
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from telethon.tl.functions.account import GetPasswordRequest

    async def run():
        client = TelegramClient(StringSession(session_str), api_id, api_hash)
        await client.connect()
        try:
            if not await client.is_user_authorized():
                return False, False, "الجلسة غير مصرح بها"
            pwd = await client(GetPasswordRequest())
            return True, bool(pwd.has_password), None
        finally:
            await client.disconnect()
    try:
        return _tg_sell_run(run(), 30)
    except Exception as e:
        return False, False, "خطأ: %s" % str(e)[:100]


def tg_sell_logout_others(session_str):
    """يطرد أي جهاز ثاني مربوط بالحساب (حتى ما يبقى الرقم مفتوح عند البائع)."""
    api_id, api_hash = _tg_sell_creds()
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from telethon.tl.functions.account import ResetAuthorizationRequest

    async def run():
        client = TelegramClient(StringSession(session_str), api_id, api_hash)
        await client.connect()
        try:
            await client(ResetAuthorizationRequest())
        finally:
            await client.disconnect()
    try:
        _tg_sell_run(run(), 30)
    except Exception:
        pass


def tg_sell_enable_2fa(session_str):
    """يفعّل حماية 2FA جديدة على الحساب، ويرجع كلمة السر الجديدة أو None."""
    api_id, api_hash = _tg_sell_creds()
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    new_pass = secrets.token_urlsafe(9)[:12]

    async def run():
        client = TelegramClient(StringSession(session_str), api_id, api_hash)
        await client.connect()
        try:
            await client.edit_2fa(new_password=new_pass, hint="")
            return new_pass
        finally:
            await client.disconnect()
    try:
        return _tg_sell_run(run(), 60)
    except Exception:
        return None


def sell_save_pending(uid, phone, session_str, two_fa_password=None):
    """يحفظ الرقم كطلب بيع معلق لمراجعة الإدارة، ويربطه بالبائع."""
    country = detect_country(phone)
    nid, _ = run("INSERT INTO numbers(platform, country, phone, price, status, session_string) "
                 "VALUES(?,?,?,0,'pending',?)", ("Telegram (Session)", country, phone, session_str))
    if two_fa_password:
        run("UPDATE numbers SET two_fa_password=?, last_code=? WHERE id=?",
            (two_fa_password, "2FA:" + two_fa_password, nid))
    run("INSERT INTO pending_sellers(number_id, user_id, created_at) VALUES(?,?,?)", (nid, uid, now_s()))
    return nid



# ---------- بيع الرقم: خطوات المستخدم ----------
@cb("sell")
def cb_sell(c, u, a):
    toast(c)
    if not get_setting("TG_API_HASH", ""):
        return show(c, T.banner("بيع رقم", "💰") + "⚠️ الخدمة غير مهيأة حالياً (API غير مضبوط). تواصل مع الدعم.",
                    K([B("🏠 القائمة", "m")]))
    set_state(c.from_user.id, "sell_phone")
    show(c, T.banner("بيع رقم", "💰") +
         "📱 أرسل <b>رقم تيليجرام</b> الذي تريد بيعه بالصيغة الدولية.\nمثال: <code>+967777123456</code>",
         K([B("✖️ إلغاء", "m")]))


@step("sell_phone")
def step_sell_phone(m, st):
    phone = sell_normalize_phone(m.text)
    if not phone:
        return send(m.chat.id, "❌ رقم غير صالح. مثال: <code>+967777123456</code>")
    if sell_duplicate(phone):
        clear_state(m.from_user.id)
        return send(m.chat.id, "❌ هذا الرقم معروض للبيع بالفعل.", main_kb(m.from_user.id))
    sess, code_hash, err = tg_sell_request_code(phone)
    if not sess:
        clear_state(m.from_user.id)
        return send(m.chat.id, "❌ فشل إرسال الكود: %s" % e(str(err)), main_kb(m.from_user.id))
    run("INSERT OR REPLACE INTO temp_sessions(phone, session_str, code_hash, created_at) VALUES(?,?,?,?)",
        (phone, sess, code_hash, now_s()))
    set_state(m.from_user.id, "sell_code", phone=phone)
    send(m.chat.id, "📨 تم إرسال الكود إلى تيليجرام على الرقم <code>%s</code>.\nأرسل الكود الآن:" % e(phone))


@step("sell_code")
def step_sell_code(m, st):
    phone = st["data"].get("phone")
    code = re.sub(r"\D", "", m.text or "")
    if not phone or not code:
        return send(m.chat.id, "❌ أرسل الكود (أرقام فقط).")
    temp = row("SELECT * FROM temp_sessions WHERE phone=?", (phone,))
    if not temp:
        clear_state(m.from_user.id)
        return send(m.chat.id, "❌ انتهت الجلسة، ابدأ من جديد من بيع رقم.", main_kb(m.from_user.id))
    sess, status, err = tg_sell_verify_code(phone, code, temp["session_str"], temp["code_hash"])
    if status == "error":
        return send(m.chat.id, "❌ %s" % e(str(err)))
    if status == "2fa":
        set_state(m.from_user.id, "sell_pw", phone=phone, sess=sess)
        return send(m.chat.id, "🔐 الرقم عليه تحقق بخطوتين. أرسل <b>كلمة سر التحقق</b>:")
    finish_sell(m, phone, sess, has_pw_check=True)


@step("sell_pw")
def step_sell_pw(m, st):
    phone = st["data"].get("phone")
    sess = st["data"].get("sess")
    new_sess, err = tg_sell_verify_password(sess, (m.text or "").strip())
    if not new_sess:
        return send(m.chat.id, "❌ %s" % e(str(err)))
    finish_sell(m, phone, new_sess, has_pw_check=False)


def finish_sell(m, phone, sess, has_pw_check):
    """المرحلة الأخيرة: تحقق الجلسة، طرد الأجهزة الأخرى، 2FA، ثم حفظ الطلب للمراجعة."""
    uid_tg = m.from_user.id
    clear_state(uid_tg)
    user = row("SELECT user_id FROM users WHERE telegram_id=?", (uid_tg,))
    if not user:
        return send(m.chat.id, "❌ سجّل دخولك أولاً.", main_kb(uid_tg))
    ok, has_2fa, err = tg_sell_check(sess)
    if not ok:
        return send(m.chat.id, "❌ فشل التحقق من الجلسة: %s" % e(str(err)), main_kb(uid_tg))
    tg_sell_logout_others(sess)
    if has_pw_check and has_2fa:
        return send(m.chat.id, "⚠️ هذا الرقم عليه تحقق بخطوتين. أزله من تيليجرام أولاً ثم أعد المحاولة.",
                    main_kb(uid_tg))
    new_pass = None
    if not has_2fa:
        new_pass = tg_sell_enable_2fa(sess)
    nid = sell_save_pending(user["user_id"], phone, sess, new_pass)
    run("DELETE FROM temp_sessions WHERE phone=?", (phone,))
    send(m.chat.id, "✅ <b>تم استلام رقمك</b>\n\nالرقم <code>%s</code> قيد المراجعة من الإدارة، وبيظهر في حسابك بعد الموافقة."
         % e(phone), main_kb(uid_tg))
    notify_admins("💰 <b>طلب بيع رقم جديد</b>\n📱 <code>%s</code>\n🆔 رقم الطلب: %s" % (e(phone), nid))


# ============================================================
#  16) تحويل الرصيد
# ============================================================
@cb("tr")
def cb_transfer(c, u, a):
    toast(c); fee = fsetting("TRANSFER_FEE", 0.05)
    set_state(c.from_user.id, "tr_id")
    show(c, T.banner("تحويل رصيد", "💸") + "💰 رصيدك: <code>%s</code>\n💳 رسوم التحويل: <b>%s</b>\n\n🆔 أرسل <b>آيدي المستلم</b> (8 أرقام):" % (usd(u["balance"]), usd(fee)),
         K([B("✖️ إلغاء", "m")]))

@step("tr_id")
def step_tr_id(m, st):
    cid = re.sub(r"\D", "", m.text or "")
    t = row("SELECT * FROM users WHERE custom_id=?", (cid,)) if cid else None
    u, _ = ctx_user(m.from_user)
    if not t: return send(m.chat.id, "❌ لم أجد مستخدماً بهذا الآيدي. أعد المحاولة.")
    if t["user_id"] == u["user_id"]: return send(m.chat.id, "❌ لا يمكن التحويل لنفسك.")
    if t["is_banned"]: return send(m.chat.id, "❌ هذا المستخدم محظور.")
    set_state(m.from_user.id, "tr_amt", cid=cid)
    send(m.chat.id, "✅ المستلم: <b>%s</b> (<code>%s</code>)\n\n💵 أرسل <b>المبلغ بالدولار</b>:" % (e(t["tg_name"] or t["username"]), cid), K([B("✖️ إلغاء", "m")]))

@step("tr_amt")
def step_tr_amt(m, st):
    try: amt = round(float((m.text or "").replace(",", ".").replace("$", "")), 4)
    except ValueError: return send(m.chat.id, "❌ أرسل مبلغاً صحيحاً.")
    fee = fsetting("TRANSFER_FEE", 0.05)
    if amt <= fee: return send(m.chat.id, "❌ المبلغ يجب أن يكون أكبر من الرسوم (%s)." % usd(fee))
    cid = st["data"]["cid"]; t = row("SELECT * FROM users WHERE custom_id=?", (cid,))
    net = round(amt - fee, 4) if MIRROR_SITE_TRANSFER_MATH else amt
    set_state(m.from_user.id, "tr_confirm", cid=cid, amt=amt)
    send(m.chat.id, "⚠️ <b>تأكيد التحويل</b>\n%s\n👤 إلى: <b>%s</b> (<code>%s</code>)\n💵 المبلغ: <b>%s</b>\n💳 الرسوم: <b>%s</b>\n📥 يصل للمستلم: <b>%s</b>\n💸 يُخصم منك: <b>%s</b>" % (
        LINE, e(t["tg_name"] or t["username"]), cid, usd(amt), usd(fee), usd(net), usd(amt + fee)),
         K([B("✅ تأكيد", "trok", style=BTN.SUCCESS), B("❌ إلغاء", "m", style=BTN.DANGER)]))

@cb("trok")
def cb_transfer_ok(c, u, a):
    st = get_state(c.from_user.id)
    if not st or st["step"] != "tr_confirm": return toast(c, "انتهت العملية، ابدأ من جديد.", True)
    cid, amt = st["data"]["cid"], st["data"]["amt"]; clear_state(c.from_user.id)
    ok, msg, info = transfer_balance(u["user_id"], cid, amt)
    if not ok:
        toast(c, "❌ " + msg, True); return show(c, "❌ <b>فشل التحويل</b>\n%s" % e(msg), K(home_row()))
    toast(c, "✅ تم التحويل"); u = user_by_id(u["user_id"])
    show(c, T.banner("تم التحويل", "✅") + "📤 أُرسل  <b>%s</b>  إلى  <code>%s</code>\n💳 الرسوم: %s\n💰 رصيدك الآن: <code>%s</code>" % (usd(info["net"]), e(cid), usd(info["fee"]), usd(u["balance"])), K(home_row()))
    t = info["to"]
    if t["tg_id"]:
        send(int(t["tg_id"]), T.banner("وصلك تحويل", "📥") + "💵 استلمت  <b>%s</b>\n👤 من: <code>%s</code>" % (usd(info["net"]), e(u["custom_id"])), K(home_row()))

# ============================================================
#  17) الدعم الفني
# ============================================================
@cb("sup")
def cb_support(c, u, a):
    toast(c); t = open_ticket(u["user_id"])
    msgs = ticket_msgs(t["id"], 6)
    s = T.banner("الدعم الفني", "🎧") + "🎫 تذكرتك رقم <code>%d</code>\n%s\n" % (t["id"], THIN)
    for x in msgs:
        s += "%s %s\n" % ("🧑" if x["sender"] == "user" else "🛡", e(x["text"][:300]))
    if not msgs: s += "اكتب مشكلتك وسيرد عليك الفريق قريباً 👇\n"
    s += "\n✍️ <b>أرسل رسالتك الآن</b> (يمكنك إرسال عدة رسائل)."
    set_state(c.from_user.id, "support", tid=t["id"])
    sup = get_setting("SUPPORT_USER", "")
    kb = [[B("✖️ إنهاء المحادثة", "m")]]
    if sup: kb.insert(0, [B("💬 تواصل مباشر " + sup, url="https://t.me/" + sup.lstrip("@"))])
    show(c, s, K(*kb))

@step("support")
def step_support(m, st):
    u, _ = ctx_user(m.from_user)
    text = (m.text or m.caption or "").strip()
    if not text: return send(m.chat.id, "أرسل رسالة نصية من فضلك.")
    t = open_ticket(u["user_id"])
    add_ticket_msg(t["id"], "user", text)
    set_state(m.from_user.id, "support", tid=t["id"])
    send(m.chat.id, "✅ وصلت رسالتك — سيتم الرد عليك هنا.", K([B("✖️ إنهاء المحادثة", "m")]))

# ============================================================
#  18) ربط حساب الموقع / بيانات الدخول
# ============================================================
@cb("lnk")
def cb_link(c, u, a):
    toast(c); set_state(c.from_user.id, "lnk_id")
    show(c, T.banner("ربط حساب الموقع", "🔗") + "اربط حسابك الحالي في الموقع ليظهر رصيدك ومشترياتك هنا.\n\n📧 أرسل <b>الإيميل أو اسم المستخدم</b> المسجّل بالموقع:",
         K([B("✖️ إلغاء", "m")]))

@step("lnk_id")
def step_lnk_id(m, st):
    set_state(m.from_user.id, "lnk_pw", ident=(m.text or "").strip())
    send(m.chat.id, "🔑 أرسل <b>كلمة المرور</b> (ستُحذف رسالتك فوراً لحمايتك):", K([B("✖️ إلغاء", "m")]))

@step("lnk_pw")
def step_lnk_pw(m, st):
    ident = st["data"]["ident"]; pw = m.text or ""; del_msg(m); clear_state(m.from_user.id)
    ok, msg = link_site_account(m.from_user.id, ident, pw)
    if ok:
        u = user_by_tg(m.from_user.id)
        send(m.chat.id, "✅ <b>%s</b>\n💰 رصيدك: <code>%s</code>  |  🆔 <code>%s</code>" % (e(msg), usd(u["balance"]), e(u["custom_id"])), K(home_row()))
    else:
        send(m.chat.id, "❌ %s" % e(msg), K([B("🔁 حاول مجدداً", "lnk"), B("🏠", "m")]))


# ============================================================
#  مستويات VIP (نفس منطق صفحة /vip في الموقع)
# ============================================================
def vip_tiers():
    """يقرأ مستويات VIP من الإعدادات، كل مستوى: (المطلوب بالدولار، نسبة الخصم)."""
    raw = get_setting("VIP_TIERS", "5:3,20:5,50:10") or ""
    tiers = []
    for part in raw.split(","):
        try:
            need, disc = part.strip().split(":")
            tiers.append((float(need), float(disc)))
        except Exception:
            pass
    return sorted(tiers)


def vip_status(total_spent):
    """يرجع (رقم المستوى الحالي، نسبة الخصم الحالية) حسب إجمالي المشتريات."""
    level, pct = 0, 0.0
    for i, (need, disc) in enumerate(vip_tiers(), 1):
        if (total_spent or 0) >= need:
            level, pct = i, disc
    return level, pct


@cb("vip")
def cb_vip(c, u, a):
    """شاشة مستويات VIP: كل مستوى ومطلوبه ونسبة خصمه، ومستواك الحالي."""
    toast(c)
    spent = float(u["total_spent"] or 0) if "total_spent" in u.keys() else 0.0
    level, pct = vip_status(spent)
    lines = []
    for i, (need, disc) in enumerate(vip_tiers(), 1):
        mark = "✅" if spent >= need else "🔒"
        lines.append("%s <b>VIP%d</b>  عند %s  ←  خصم <b>%g%%</b>" % (mark, i, usd(need), disc))
    body = T.banner("مستويات VIP", "⭐") + "💰 إجمالي مشترياتك: <b>%s</b>\n" % usd(spent)
    body += "🏅 مستواك الحالي: <b>%s</b>\n\n" % (("VIP%d" % level) if level else "بدون مستوى")
    body += "\n".join(lines) or "لا توجد مستويات مضبوطة."
    show(c, body, K([B("🔙 حسابي", "acc")], home_row()))


# ============================================================
#  المبيعات المعلقة (مطابقة لصفحة /my/pending-sales في الموقع)
# ============================================================
def pending_sales_of(uid):
    """يرجع قائمة مبيعات الرقم المعلقة للمستخدم مع الساعات المتبقية (الحد 24 ساعة)."""
    try:
        rows = rows("SELECT pb.amount, pb.created_at, n.phone, n.country FROM pending_balance pb "
                     "INNER JOIN numbers n ON n.id = pb.number_id "
                     "WHERE pb.user_id=? AND n.phone IS NOT NULL AND n.phone != '' "
                     "ORDER BY pb.created_at DESC", (uid,))
    except Exception:
        return []
    out = []
    now = datetime.now()
    for r in rows:
        try:
            created = datetime.strptime(r["created_at"], "%Y-%m-%d %H:%M:%S")
            left = max(0.0, 24 - (now - created).total_seconds() / 3600)
        except Exception:
            left = 24.0
        out.append({"phone": r["phone"], "country": r["country"], "amount": float(r["amount"] or 0),
                    "hours_left": left})
    return out


@cb("psales")
def cb_pending_sales(c, u, a):
    """شاشة مبيعات الأرقام المعلقة وقيمة كل مبيعة والوقت المتبقي للصرف."""
    toast(c)
    items = pending_sales_of(u["user_id"])
    if not items:
        return show(c, T.banner("مبيعاتي المعلقة", "⏳") + "لا توجد مبيعات معلقة حالياً.",
                    K([B("🔙 حسابي", "acc")], home_row()))
    lines = []
    for it in items[:15]:
        lines.append("📱 <code>%s</code> · %s · <b>%s</b> · متبقي %.0f ساعة" % (
            e(it["phone"]), e(it["country"] or ""), usd(it["amount"]), it["hours_left"]))
    show(c, T.banner("مبيعاتي المعلقة", "⏳") + "\n".join(lines),
         K([B("🔙 حسابي", "acc")], home_row()))


@cb("prof")
def cb_profile(c, u, a):
    toast(c); clear_state(c.from_user.id)
    show(c, T.profile(user_by_id(u["user_id"])),
         K([B("➕ شحن", "dep"), B("💸 تحويل", "tr")], [B("📜 سجل العمليات", "hist"), B("🔐 بيانات الموقع", "acc")], home_row()))

@cb("acc")
def cb_account(c, u, a):
    toast(c)
    s = T.banner("بيانات حسابك", "🔐")
    s += "👤 اسم المستخدم:  <code>%s</code>\n📧 الإيميل:  <code>%s</code>\n🆔 الآيدي:  <code>%s</code>\n🗝 مفتاح الاسترداد:  <code>%s</code>\n" % (
        e(u["username"]), e(u["email"]), e(u["custom_id"]), e(u["recovery_key"]))
    s += "\n💡 لتسجيل الدخول للموقع بنفس الحساب عيّن كلمة مرور:"
    show(c, s, K([B("🔑 تعيين / تغيير كلمة المرور", "pw")],
                 [B("⭐ مستويات VIP", "vip"), B("⏳ مبيعاتي المعلقة", "psales")], home_row()))

@cb("pw")
def cb_pw(c, u, a):
    toast(c); set_state(c.from_user.id, "setpw")
    show(c, "🔑 أرسل <b>كلمة المرور الجديدة</b> (6 أحرف فأكثر).\nستُحذف رسالتك فوراً.", K([B("✖️ إلغاء", "acc")]))

@step("setpw")
def step_setpw(m, st):
    pw = m.text or ""; del_msg(m)
    u, _ = ctx_user(m.from_user)
    ok, msg = set_site_password(u["user_id"], pw)
    if ok: clear_state(m.from_user.id)
    send(m.chat.id, ("✅ " if ok else "❌ ") + e(msg) + ("\nسجّل الدخول بالموقع بـ: <code>%s</code>" % e(u["username"]) if ok else ""), K(home_row()))

# ============================================================
#  19) لوحة المدير داخل البوت
# ============================================================
def admin_home_text():
    s = stats()
    return (T.banner("لوحة المدير", "👑") +
            "👥 المستخدمون: <b>%d</b>   📦 المتاح: <b>%d</b>\n🛍 المباع: <b>%d</b>   💰 الأرباح: <b>%s</b>\n"
            "⏳ شحن معلّق: <b>%d</b>   🎫 تذاكر مفتوحة: <b>%d</b>\n%s\n✨ اختر القسم:" % (
                s["users"], s["available"], s["sold"], usd(s["revenue"]), s["pending_dep"], s["open_tickets"], THIN))

def admin_home_kb():
    s = stats()
    return K(
        [B("📊 الإحصائيات", "a_st"), B("👥 المستخدمون", "a_usr")],
        [B("➕ إضافة أرقام", "a_num"), B("🗂 المخزون", "a_inv:available:0")],
        [B("💳 طلبات الشحن (%d)" % s["pending_dep"], "a_dep:0"), B("🎫 التذاكر (%d)" % s["open_tickets"], "a_tk:0")],
        [B("🎟 أكواد الشحن", "a_vch"), B("🏷 الكوبونات", "a_cpn")],
        [B("📢 الإعلانات", "a_ann"), B("🏅 الشارات", "a_stp")],
        [B("⚙️ إعدادات API", "a_set"), B("🛠 الأدوات", "a_tools")],
        [B("📣 بث رسالة", "a_bc"), B("💾 نسخة احتياطية", "a_bak")],
        home_row())

@cb("a", admin=True)
def cb_admin(c, u, a):
    toast(c); clear_state(c.from_user.id)
    show(c, admin_home_text(), admin_home_kb())

ADM_BACK = [B("👑 لوحة المدير", "a")]

@cb("a_st", admin=True)
def cb_stats(c, u, a):
    toast(c); s = stats()
    t = T.banner("إحصائيات المتجر", "📊")
    t += ("👥 المستخدمون: <b>%d</b>  (عبر البوت: %d)\n🚫 المحظورون: <b>%d</b>\n%s\n"
          "📦 إجمالي الأرقام: <b>%d</b>\n🟢 المتاحة: <b>%d</b>\n🛍 المباعة: <b>%d</b>\n%s\n"
          "📅 مبيعات اليوم: <b>%d</b>  (%s)\n💰 إجمالي الأرباح: <b>%s</b>\n📥 إجمالي الشحن: <b>%s</b>\n"
          "🏦 أرصدة المستخدمين: <b>%s</b>\n%s\n⏳ شحن معلّق: <b>%d</b>\n🎫 تذاكر مفتوحة: <b>%d</b>") % (
        s["users"], s["tg_users"], s["banned"], THIN, s["numbers"], s["available"], s["sold"], THIN,
        s["sold_today"], usd(s["revenue_today"]), usd(s["revenue"]), usd(s["deposited"]), usd(s["balances"]), THIN,
        s["pending_dep"], s["open_tickets"])
    show(c, t, K([B("🔄 تحديث", "a_st")], ADM_BACK))

# ---------------- إضافة الأرقام ----------------
@cb("a_num", admin=True)
def cb_add_menu(c, u, a):
    toast(c); clear_state(c.from_user.id)
    show(c, T.banner("إضافة أرقام", "➕") + "اختر المنصة، ثم أرسل الأرقام <b>سطر لكل رقم</b>:\n<code>+967771234567 0.50</code>\n<code>+966501234567 0.80 vip</code>\n\n"
         "• الدولة تُكتشف تلقائياً من الرمز\n• أضف <code>vip</code> لجعل الرقم مميزاً 💎\n• يمكنك إرسال عدة أسطر دفعة واحدة",
         K([B("🟢 واتساب", "a_add:WhatsApp"), B("🔵 تيليجرام", "a_add:Telegram")], ADM_BACK))

@cb("a_add", admin=True)
def cb_add_ask(c, u, a):
    toast(c); set_state(c.from_user.id, "a_add", platform=a[0])
    ask(c.message.chat.id, "📥 أرسل أرقام <b>%s</b> الآن (<code>الرقم السعر [vip]</code> في كل سطر):" % ("واتساب" if a[0] == "WhatsApp" else "تيليجرام"), "a_num")

@step("a_add")
def step_add_numbers(m, st):
    if not is_admin_tg(m.from_user.id): return
    ok_n, errs = 0, []
    for ln in (m.text or "").splitlines():
        p = ln.split()
        if not p: continue
        if len(p) < 2: errs.append("%s ← السعر مفقود" % ln[:25]); continue
        try: price = float(p[1].replace(",", "."))
        except ValueError: errs.append("%s ← سعر غير صالح" % ln[:25]); continue
        if price <= 0: errs.append("%s ← السعر يجب أن يكون > 0" % ln[:25]); continue
        ok, msg = admin_add_number(st["data"]["platform"], p[0], price, 1 if len(p) > 2 and p[2].lower() in ("vip", "premium", "مميز") else 0)
        if ok: ok_n += 1
        else: errs.append("%s ← %s" % (p[0], msg))
    touch_state(m.from_user.id)
    s = "✅ تمت إضافة <b>%d</b> رقم للمتجر (يظهر فوراً في الموقع)." % ok_n
    if errs: s += "\n\n⚠️ تعذّر:\n" + "\n".join("• " + e(x) for x in errs[:15])
    send(m.chat.id, s + "\n\nأرسل أرقاماً أخرى أو اضغط رجوع.", K([B("◀️ رجوع", "a_num")], ADM_BACK))

# ---------------- المخزون ----------------
@cb("a_inv", admin=True)
def cb_inventory(c, u, a):
    toast(c); stt, page = a[0], int(a[1])
    total = scalar("SELECT COUNT(*) FROM numbers WHERE status=?", (stt,))
    page, pages, off = paginate(total, page)
    names = {"available": "🟢 المتاحة", "sold": "🛍 المباعة", "pending": "⏳ المعلّقة"}
    s = T.banner("المخزون", "🗂") + "%s — <b>%d</b> رقم\n" % (names.get(stt, stt), total)
    kb = [[B("🟢 متاحة", "a_inv:available:0"), B("🛍 مباعة", "a_inv:sold:0"), B("⏳ معلّقة", "a_inv:pending:0")]]
    for n in rows("SELECT * FROM numbers WHERE status=? ORDER BY id DESC LIMIT ? OFFSET ?", (stt, PAGE, off)):
        kb.append([B("#%d  %s %s · %s" % (n["id"], "🔵" if "telegram" in (n["platform"] or "").lower() else "🟢", n["phone"], usd(n["price"])), "a_ni:%d" % n["id"])])
    if pages > 1: kb.append(pager_row("a_inv:" + stt, page, pages))
    kb.append(ADM_BACK)
    show(c, s, K(*kb))

@cb("a_ni", admin=True)
def cb_num_admin(c, u, a):
    toast(c); nid = int(a[0]); n = row("SELECT * FROM numbers WHERE id=?", (nid,))
    if not n: return show(c, "الرقم غير موجود.", K(ADM_BACK))
    s = T.banner("رقم #%d" % nid, "📱") + "%s  %s %s\n☎️ <code>%s</code>\n💳 السعر: <b>%s</b>   الحالة: <b>%s</b>\n" % (
        plat_label(n["platform"]), flag_of(n["country"]), e(n["country"]), e(n["phone"]), usd(n["price"]), e(n["status"]))
    if n["is_premium"]: s += "💎 مميز\n"
    st = stamps_of(nid)
    if st: s += "🏅 " + " • ".join(e(x) for x in st) + "\n"
    if n["buyer_id"]:
        b = user_by_id(n["buyer_id"])
        s += "👤 المشتري: <code>%s</code>  ·  🕒 %s\n💵 دفع: %s\n" % (e(b["custom_id"] if b else n["buyer_id"]), e(n["sold_at"]), usd(n["paid_price"] or n["price"]))
        if n["last_code"]: s += "🔑 آخر كود: <code>%s</code>\n" % e(n["last_code"])
    kb = []
    if n["status"] == "available":
        kb.append([B("💲 تعديل السعر", "a_np:%d" % nid), B("🗑 حذف", "a_nd:%d" % nid)])
    else:
        kb.append([B("↩️ إرجاع للمتجر", "a_nr:%d" % nid)])
    kb.append([B("🏅 الشارات", "a_ns:%d" % nid), B("💎 مميز/عادي", "a_nv:%d" % nid)])
    kb.append([B("◀️ المخزون", "a_inv:%s:0" % n["status"])])
    show(c, s, K(*kb))

@cb("a_nd", admin=True)
def cb_num_delete(c, u, a):
    run("DELETE FROM numbers WHERE id=? AND status='available'", (int(a[0]),)); toast(c, "🗑 تم الحذف")
    cb_inventory(c, u, ["available", "0"])

@cb("a_nr", admin=True)
def cb_num_restore(c, u, a):
    run("UPDATE numbers SET status='available', buyer_id=NULL, sold_at=NULL WHERE id=?", (int(a[0]),)); toast(c, "↩️ أُرجع للمتجر")
    cb_num_admin(c, u, a)

@cb("a_nv", admin=True)
def cb_num_vip(c, u, a):
    run("UPDATE numbers SET is_premium=1-COALESCE(is_premium,0) WHERE id=?", (int(a[0]),)); toast(c, "تم")
    cb_num_admin(c, u, a)

@cb("a_np", admin=True)
def cb_num_price(c, u, a):
    toast(c); set_state(c.from_user.id, "a_price", nid=int(a[0]))
    ask(c.message.chat.id, "💲 أرسل <b>السعر الجديد</b> بالدولار:", "a_ni:%s" % a[0])

@step("a_price")
def step_price(m, st):
    try: p = float((m.text or "").replace(",", "."))
    except ValueError: return send(m.chat.id, "❌ أرسل رقماً صحيحاً.")
    if p <= 0: return send(m.chat.id, "❌ السعر يجب أن يكون أكبر من صفر.")
    run("UPDATE numbers SET price=? WHERE id=? AND status='available'", (p, st["data"]["nid"])); clear_state(m.from_user.id)
    send(m.chat.id, "✅ تم تحديث السعر إلى <b>%s</b>" % usd(p), K([B("◀️ الرقم", "a_ni:%d" % st["data"]["nid"])], ADM_BACK))

# ---------------- شارات الأرقام ----------------
@cb("a_ns", admin=True)
def cb_num_stamps(c, u, a):
    toast(c); nid = int(a[0]); have = {r["stamp_id"] for r in rows("SELECT stamp_id FROM number_stamps WHERE number_id=?", (nid,))}
    kb = [[B(("✅ " if s["id"] in have else "▫️ ") + s["name"], "a_nst:%d:%d" % (nid, s["id"]))] for s in rows("SELECT * FROM stamps ORDER BY id")]
    kb.append([B("◀️ رجوع", "a_ni:%d" % nid)])
    show(c, T.banner("شارات الرقم #%d" % nid, "🏅") + "اضغط لإضافة/إزالة الشارة:", K(*kb))

@cb("a_nst", admin=True)
def cb_num_stamp_toggle(c, u, a):
    nid, sid = int(a[0]), int(a[1])
    if row("SELECT 1 FROM number_stamps WHERE number_id=? AND stamp_id=?", (nid, sid)):
        run("DELETE FROM number_stamps WHERE number_id=? AND stamp_id=?", (nid, sid))
    else:
        run("INSERT OR IGNORE INTO number_stamps(number_id,stamp_id) VALUES(?,?)", (nid, sid))
    cb_num_stamps(c, u, [str(nid)])

# ---------------- أكواد الشحن ----------------
@cb("a_vch", admin=True)
def cb_vouchers(c, u, a):
    toast(c); clear_state(c.from_user.id)
    free = scalar("SELECT COUNT(*) FROM vouchers WHERE is_used=0"); used = scalar("SELECT COUNT(*) FROM vouchers WHERE is_used=1")
    show(c, T.banner("أكواد الشحن", "🎟") + "🟢 غير مستخدمة: <b>%d</b>\n⚫ مستخدمة: <b>%d</b>" % (free, used),
         K([B("➕ توليد أكواد", "a_vg")], [B("📋 آخر الأكواد غير المستخدمة", "a_vl")], ADM_BACK))

@cb("a_vg", admin=True)
def cb_voucher_gen(c, u, a):
    toast(c); set_state(c.from_user.id, "a_vgen")
    ask(c.message.chat.id, "🎟 أرسل <b>القيمة</b> و<b>العدد</b> (حتى 100) في رسالة واحدة:\n<code>5 10</code>  ← عشرة أكواد بقيمة $5", "a_vch")

@step("a_vgen")
def step_vgen(m, st):
    try:
        amt_s, cnt_s = (m.text or "").replace(",", ".").split()[:2]; amt, cnt = float(amt_s), int(cnt_s)
        assert amt > 0 and 1 <= cnt <= 100
    except Exception:
        return send(m.chat.id, "❌ الصيغة: <code>القيمة العدد</code> مثل <code>5 10</code>")
    codes = gen_vouchers(amt, cnt); clear_state(m.from_user.id)
    audit(None, "gen_vouchers", "%d x %s" % (len(codes), amt))
    body = "\n".join(codes)
    if len(codes) <= 30:
        send(m.chat.id, T.banner("أكواد جاهزة", "✅") + "💵 قيمة الكود: <b>%s</b> × %d\n\n<code>%s</code>" % (usd(amt), len(codes), e(body)), K([B("➕ توليد المزيد", "a_vg")], ADM_BACK))
    else:
        bio = io.BytesIO(body.encode()); bio.name = "vouchers_%s_x%d.txt" % (amt, len(codes))
        bot.send_document(m.chat.id, bio, caption="✅ %d كود بقيمة %s" % (len(codes), usd(amt)))
        send(m.chat.id, "تم إرسال الأكواد كملف.", K(ADM_BACK))

@cb("a_vl", admin=True)
def cb_voucher_list(c, u, a):
    toast(c); rs = rows("SELECT * FROM vouchers WHERE is_used=0 ORDER BY id DESC LIMIT 20")
    s = T.banner("أكواد غير مستخدمة", "📋") + ("\n".join("<code>%s</code>  ‹ %s ›" % (e(r["code"]), usd(r["amount"])) for r in rs) or "لا توجد.")
    show(c, s, K([B("◀️ رجوع", "a_vch")], ADM_BACK))

# ---------------- الكوبونات ----------------
@cb("a_cpn", admin=True)
def cb_coupons(c, u, a):
    toast(c); clear_state(c.from_user.id)
    cs = rows("SELECT * FROM coupons ORDER BY rowid DESC LIMIT 15")
    s = T.banner("كوبونات الخصم", "🏷")
    kb = []
    for x in cs:
        exp = (x["expires_at"] or "بلا انتهاء")[:10]
        s += "• <code>%s</code>  −%g%%  ·  %d/%s  ·  %s\n" % (e(x["code"]), x["percent"], x["used_count"], x["max_uses"] or "∞", e(exp))
        kb.append([B("🗑 حذف " + x["code"], "a_cpd:" + x["code"])])
    if not cs: s += "لا توجد كوبونات."
    kb.insert(0, [B("➕ كوبون جديد", "a_cpa")]); kb.append(ADM_BACK)
    show(c, s, K(*kb))

@cb("a_cpa", admin=True)
def cb_coupon_add(c, u, a):
    toast(c); set_state(c.from_user.id, "a_cpn")
    ask(c.message.chat.id, "🏷 أرسل: <code>الكود النسبة الحد_الأقصى_للاستخدام الأيام</code>\nمثال: <code>RAMADAN 20 100 30</code>\n(الأيام 0 = بلا انتهاء)", "a_cpn")

@step("a_cpn")
def step_coupon_add(m, st):
    try:
        p = (m.text or "").split(); code, pct = p[0], float(p[1].replace(",", ".")); mx = int(p[2]) if len(p) > 2 else 1; days = int(p[3]) if len(p) > 3 else 0
    except Exception:
        return send(m.chat.id, "❌ الصيغة: <code>CODE 20 100 30</code>")
    ok, msg = add_coupon(code, pct, mx, days)
    if ok: clear_state(m.from_user.id)
    send(m.chat.id, ("✅ " if ok else "❌ ") + e(msg), K([B("🏷 الكوبونات", "a_cpn")], ADM_BACK))

@cb("a_cpd", admin=True)
def cb_coupon_del(c, u, a):
    run("DELETE FROM coupons WHERE code=?", (a[0],)); run("DELETE FROM coupon_uses WHERE code=?", (a[0],)); toast(c, "🗑 حُذف")
    cb_coupons(c, u, [])

# ---------------- طلبات الشحن ----------------
@cb("a_dep", admin=True)
def cb_deposits(c, u, a):
    toast(c); total = scalar("SELECT COUNT(*) FROM deposits WHERE status='pending'")
    page, pages, off = paginate(total, int(a[0]))
    s = T.banner("طلبات الشحن المعلّقة", "💳") + "عدد الطلبات: <b>%d</b>\n" % total
    kb = []
    for d in rows("SELECT d.*, u.username, u.custom_id FROM deposits d LEFT JOIN users u ON u.user_id=d.user_id WHERE d.status='pending' ORDER BY d.id LIMIT ? OFFSET ?", (PAGE, off)):
        kb.append([B("#%d  %s · %s · %s" % (d["id"], d["custom_id"] or d["username"], d["method"], usd(d["amount_usd"])), "a_dv:%d" % d["id"])])
    if not total: s += "\n✨ لا توجد طلبات معلّقة."
    if pages > 1: kb.append(pager_row("a_dep", page, pages))
    kb.append(ADM_BACK); show(c, s, K(*kb))

@cb("a_dv", admin=True)
def cb_deposit_view(c, u, a):
    toast(c); did = int(a[0]); d = row("SELECT * FROM deposits WHERE id=?", (did,))
    if not d: return show(c, "الطلب غير موجود.", K(ADM_BACK))
    usr = user_by_id(d["user_id"]); fid = row("SELECT file_id FROM bot_receipts WHERE deposit_id=?", (did,))
    kb = []
    if d["status"] == "pending": kb.append([B("✅ موافقة", "a_da:%d" % did, style=BTN.SUCCESS), B("❌ رفض", "a_dr:%d" % did, style=BTN.DANGER)])
    if fid: kb.append([B("🖼 عرض الإيصال", "a_dimg:%d" % did)])
    kb.append([B("◀️ الطلبات", "a_dep:0")])
    show(c, T.deposit_notice(d, usr, "📌 الحالة: <b>%s</b>" % e(d["status"])), K(*kb))

@cb("a_dimg", admin=True)
def cb_deposit_img(c, u, a):
    toast(c); r = row("SELECT file_id FROM bot_receipts WHERE deposit_id=?", (int(a[0]),))
    if r:
        try: bot.send_photo(c.message.chat.id, r["file_id"], caption="🧾 إيصال الطلب #%s" % a[0])
        except Exception: pass

def _finish_deposit(c, did, approve):
    ok, msg, d = (approve_deposit if approve else reject_deposit)(did)
    if not ok: return toast(c, "⚠️ " + msg, True)
    toast(c, "✅ تمت الموافقة" if approve else "❌ تم الرفض")
    usr = user_by_id(d["user_id"])
    BOT_MARK("dep_status", did)
    if usr and usr["tg_id"]:
        if approve:
            send(int(usr["tg_id"]), T.banner("تم شحن رصيدك", "✅") + "💵 أُضيف  <b>%s</b>\n💰 رصيدك الآن: <code>%s</code>\n🆔 طلب #%d" % (usd(d["amount_usd"]), usd(usr["balance"]), did), K([B("🛒 تسوّق الآن", "shop")]))
        else:
            send(int(usr["tg_id"]), T.banner("تم رفض طلب الشحن", "❌") + "🆔 طلب #%d بقيمة %s\nللاستفسار: %s" % (did, usd(d["amount_usd"]), e(get_setting("SUPPORT_USER", ""))), K(home_row()))
    show(c, T.deposit_notice(d, usr, "\n%s <b>%s بواسطة %s</b>" % ("✅" if approve else "❌", "تمت الموافقة" if approve else "تم الرفض", e(c.from_user.first_name))), K([B("💳 الطلبات", "a_dep:0")], ADM_BACK))

@cb("a_da", admin=True)
def cb_dep_approve(c, u, a): _finish_deposit(c, int(a[0]), True)

@cb("a_dr", admin=True)
def cb_dep_reject(c, u, a): _finish_deposit(c, int(a[0]), False)

# ---------------- المستخدمون ----------------
@cb("a_usr", admin=True)
def cb_users(c, u, a):
    toast(c); clear_state(c.from_user.id)
    show(c, T.banner("إدارة المستخدمين", "👥") + "ابحث بـ: الآيدي / اليوزر / الإيميل / آيدي تيليجرام",
         K([B("🔍 بحث عن مستخدم", "a_us")], [B("🔨 حظر", "a_ban:1"), B("♻️ فك الحظر", "a_ban:0")],
           [B("🆕 آخر المسجلين", "a_ul:0"), B("🚫 المحظورون", "a_ubl:0")], ADM_BACK))

@cb("a_us", admin=True)
def cb_user_search(c, u, a):
    toast(c); set_state(c.from_user.id, "a_usearch")
    ask(c.message.chat.id, "🔍 أرسل <b>الآيدي / اليوزر / الإيميل / آيدي تيليجرام</b>:", "a_usr")

def user_card(x):
    nums = scalar("SELECT COUNT(*) FROM numbers WHERE buyer_id=? AND status='sold'", (x["user_id"],))
    dep = scalar("SELECT COALESCE(SUM(amount_usd),0) FROM deposits WHERE user_id=? AND status='approved'", (x["user_id"],))
    s = T.banner("مستخدم", "👤")
    s += "🧾 الاسم: <b>%s</b>\n🆔 الآيدي: <code>%s</code>   🔢 ID: <code>%s</code>\n" % (e(x["tg_name"] or x["username"]), e(x["custom_id"]), x["user_id"])
    s += "✈️ تيليجرام: %s\n📧 %s\n%s\n" % (("<code>%s</code> %s" % (x["tg_id"], e("@" + x["tg_username"] if x["tg_username"] else ""))) if x["tg_id"] else "غير مرتبط", e(x["email"]), THIN)
    s += "💰 الرصيد: <b>%s</b>\n📥 شحن: %s   📦 مشتريات: %d\n🕒 انضم: %s\n" % (usd(x["balance"]), usd(dep), nums, e((x["created_at"] or "")[:16]))
    s += "%s %s" % ("🚫" if x["is_banned"] else "🟢", "<b>محظور</b>" if x["is_banned"] else "نشط")
    if x["is_admin"]: s += "  ·  👑 مدير"
    return s

def user_kb(x):
    uid = x["user_id"]
    return K([B("♻️ فك الحظر" if x["is_banned"] else "🚫 حظر", ("a_uu:%d" if x["is_banned"] else "a_ub:%d") % uid)],
             [B("➕ إضافة رصيد", "a_ubal:%d:add" % uid), B("➖ خصم رصيد", "a_ubal:%d:sub" % uid)],
             [B("✉️ إرسال رسالة", "a_um:%d" % uid)], [B("◀️ المستخدمون", "a_usr")])

@step("a_usearch")
def step_user_search(m, st):
    x = find_user(m.text or "")
    if not x: return send(m.chat.id, "❌ لم أجد مستخدماً. أعد المحاولة أو اضغط إلغاء.", K([B("✖️ إلغاء", "a_usr")]))
    clear_state(m.from_user.id); send(m.chat.id, user_card(x), user_kb(x))

@cb("a_uv", admin=True)
def cb_user_view(c, u, a):
    toast(c); x = user_by_id(int(a[0]))
    if x: show(c, user_card(x), user_kb(x))

def _set_ban(c, uid, val):
    x = user_by_id(uid)
    if not x: return toast(c, "غير موجود", True)
    if x["is_admin"] and val: return toast(c, "لا يمكن حظر مدير.", True)
    run("UPDATE users SET is_banned=? WHERE user_id=?", (val, uid)); audit(None, "ban" if val else "unban", "uid=%s" % uid)
    toast(c, "🚫 تم الحظر" if val else "♻️ تم فك الحظر")
    if x["tg_id"]:
        send(int(x["tg_id"]), "🚫 <b>تم حظر حسابك.</b>" if val else "✅ <b>تم فك الحظر عن حسابك.</b> أرسل /start")
    cb_user_view(c, None, [str(uid)])

@cb("a_ub", admin=True)
def cb_ban(c, u, a): _set_ban(c, int(a[0]), 1)

@cb("a_uu", admin=True)
def cb_unban(c, u, a): _set_ban(c, int(a[0]), 0)

@cb("a_ban", admin=True)
def cb_ban_ask(c, u, a):
    toast(c); set_state(c.from_user.id, "a_banq", val=int(a[0]))
    ask(c.message.chat.id, "%s أرسل <b>آيدي/يوزر/إيميل</b> المستخدم:" % ("🔨 للحظر" if a[0] == "1" else "♻️ لفك الحظر"), "a_usr")

@step("a_banq")
def step_ban(m, st):
    x = find_user(m.text or ""); val = st["data"]["val"]
    if not x: return send(m.chat.id, "❌ لم أجد المستخدم.")
    if x["is_admin"] and val: return send(m.chat.id, "❌ لا يمكن حظر مدير.")
    run("UPDATE users SET is_banned=? WHERE user_id=?", (val, x["user_id"])); clear_state(m.from_user.id)
    if x["tg_id"]: send(int(x["tg_id"]), "🚫 <b>تم حظر حسابك.</b>" if val else "✅ <b>تم فك الحظر عن حسابك.</b>")
    send(m.chat.id, "%s <b>%s</b> (<code>%s</code>)" % ("🚫 تم حظر" if val else "♻️ تم فك الحظر عن", e(x["username"]), e(x["custom_id"])), K([B("👥 المستخدمون", "a_usr")]))

@cb("a_ubal", admin=True)
def cb_user_bal(c, u, a):
    toast(c); set_state(c.from_user.id, "a_bal", uid=int(a[0]), mode=a[1])
    ask(c.message.chat.id, "💵 أرسل <b>المبلغ</b> بالدولار %s:" % ("للإضافة" if a[1] == "add" else "للخصم"), "a_uv:%s" % a[0])

@step("a_bal")
def step_balance(m, st):
    try: amt = float((m.text or "").replace(",", ".")); assert amt > 0
    except Exception: return send(m.chat.id, "❌ أرسل مبلغاً صحيحاً.")
    uid, mode = st["data"]["uid"], st["data"]["mode"]; clear_state(m.from_user.id)
    ok = adjust_balance(uid, amt if mode == "add" else -amt)
    x = user_by_id(uid)
    if not ok: return send(m.chat.id, "❌ الرصيد غير كافٍ للخصم.", K([B("◀️ رجوع", "a_uv:%d" % uid)]))
    audit(None, "admin_balance", "uid=%s %s%s by=%s" % (uid, "+" if mode == "add" else "-", amt, m.from_user.id))
    if x["tg_id"]:
        send(int(x["tg_id"]), ("💰 تمت إضافة <b>%s</b> إلى رصيدك من الإدارة." if mode == "add" else "💳 تم خصم <b>%s</b> من رصيدك من الإدارة.") % usd(amt) + "\nرصيدك: <code>%s</code>" % usd(x["balance"]))
    send(m.chat.id, "✅ تم. رصيده الآن <b>%s</b>" % usd(x["balance"]), K([B("◀️ المستخدم", "a_uv:%d" % uid)]))

@cb("a_um", admin=True)
def cb_user_msg(c, u, a):
    toast(c); set_state(c.from_user.id, "a_umsg", uid=int(a[0]))
    ask(c.message.chat.id, "✉️ أرسل نص الرسالة للمستخدم:", "a_uv:%s" % a[0])

@step("a_umsg")
def step_user_msg(m, st):
    x = user_by_id(st["data"]["uid"]); clear_state(m.from_user.id)
    if not x or not x["tg_id"]: return send(m.chat.id, "❌ المستخدم غير مرتبط بتيليجرام.")
    r = send(int(x["tg_id"]), T.banner("رسالة من الإدارة", "📨") + e(m.text or ""), K(home_row()))
    send(m.chat.id, "✅ تم الإرسال." if r else "❌ تعذّر الإرسال (ربما حظر البوت).", K([B("◀️ المستخدم", "a_uv:%d" % x["user_id"])]))

def _user_list(c, title, where, prefix, page):
    total = scalar("SELECT COUNT(*) FROM users WHERE " + where); page, pages, off = paginate(total, page)
    kb = [[B("%s · %s · %s" % (x["tg_name"] or x["username"], x["custom_id"], usd(x["balance"])), "a_uv:%d" % x["user_id"])]
          for x in rows("SELECT * FROM users WHERE %s ORDER BY user_id DESC LIMIT ? OFFSET ?" % where, (PAGE, off))]
    if pages > 1: kb.append(pager_row(prefix, page, pages))
    kb.append([B("◀️ رجوع", "a_usr")]); show(c, T.banner(title, "👥") + "العدد: <b>%d</b>" % total, K(*kb))

@cb("a_ul", admin=True)
def cb_user_list(c, u, a): toast(c); _user_list(c, "آخر المسجلين", "1=1", "a_ul", int(a[0]))

@cb("a_ubl", admin=True)
def cb_banned_list(c, u, a): toast(c); _user_list(c, "المحظورون", "is_banned=1", "a_ubl", int(a[0]))

# ---------------- التذاكر ----------------
@cb("a_tk", admin=True)
def cb_tickets(c, u, a):
    toast(c); total = scalar("SELECT COUNT(*) FROM tickets WHERE status='open'"); page, pages, off = paginate(total, int(a[0]))
    s = T.banner("تذاكر الدعم", "🎫") + "المفتوحة: <b>%d</b>\n" % total; kb = []
    for t in rows("SELECT t.*, u.username, u.custom_id, (SELECT text FROM ticket_messages WHERE ticket_id=t.id ORDER BY id DESC LIMIT 1) last, "
                  "(SELECT COUNT(*) FROM ticket_messages WHERE ticket_id=t.id AND sender='user' AND is_read=0) unread FROM tickets t "
                  "LEFT JOIN users u ON u.user_id=t.user_id WHERE t.status='open' ORDER BY t.id DESC LIMIT ? OFFSET ?", (PAGE, off)):
        kb.append([B("%s#%d · %s · %s" % ("🔴 " if t["unread"] else "", t["id"], t["custom_id"] or t["username"], (t["last"] or "—")[:18]), "a_tv:%d" % t["id"])])
    if not total: s += "\n✨ لا توجد تذاكر مفتوحة."
    if pages > 1: kb.append(pager_row("a_tk", page, pages))
    kb.append(ADM_BACK); show(c, s, K(*kb))

@cb("a_tv", admin=True)
def cb_ticket_view(c, u, a):
    toast(c); tid = int(a[0]); t = row("SELECT * FROM tickets WHERE id=?", (tid,))
    if not t: return show(c, "التذكرة غير موجودة.", K(ADM_BACK))
    usr = user_by_id(t["user_id"]); run("UPDATE ticket_messages SET is_read=1 WHERE ticket_id=? AND sender='user'", (tid,))
    s = T.banner("تذكرة #%d" % tid, "🎫") + "👤 %s (<code>%s</code>)  ·  %s\n%s\n" % (e(usr["tg_name"] or usr["username"]), e(usr["custom_id"]), "🟢 مفتوحة" if t["status"] == "open" else "⚫ مغلقة", THIN)
    for x in ticket_msgs(tid, 10): s += "%s %s\n" % ("🧑" if x["sender"] == "user" else "🛡", e(x["text"][:400]))
    kb = [[B("✍️ رد", "a_tr:%d" % tid)]]
    kb.append([B("🔒 إغلاق التذكرة", "a_tc:%d" % tid)] if t["status"] == "open" else [B("🔓 إعادة فتح", "a_to:%d" % tid)])
    kb.append([B("◀️ التذاكر", "a_tk:0")]); show(c, s, K(*kb))

@cb("a_tr", admin=True)
def cb_ticket_reply(c, u, a):
    toast(c); set_state(c.from_user.id, "a_treply", tid=int(a[0]))
    ask(c.message.chat.id, "✍️ أرسل <b>ردك</b> على التذكرة #%s:" % a[0], "a_tv:%s" % a[0])

@step("a_treply")
def step_ticket_reply(m, st):
    tid = st["data"]["tid"]; t = row("SELECT * FROM tickets WHERE id=?", (tid,)); text = (m.text or "").strip()
    if not t or not text: return send(m.chat.id, "❌ أرسل نصاً.")
    mid = add_ticket_msg(tid, "admin", text); BOT_MARK("tadm", mid); clear_state(m.from_user.id)
    usr = user_by_id(t["user_id"])
    if usr and usr["tg_id"]:
        send(int(usr["tg_id"]), T.banner("رد من الدعم", "🛡") + e(text) + "\n\n<i>للرد: افتح «الدعم الفني» من القائمة.</i>", K([B("🎧 الدعم الفني", "sup")]))
    send(m.chat.id, "✅ تم إرسال الرد.", K([B("◀️ التذكرة", "a_tv:%d" % tid), B("🎫 التذاكر", "a_tk:0")]))

@cb("a_tc", admin=True)
def cb_ticket_close(c, u, a):
    run("UPDATE tickets SET status='closed' WHERE id=?", (int(a[0]),)); toast(c, "🔒 أُغلقت")
    t = row("SELECT user_id FROM tickets WHERE id=?", (int(a[0]),)); usr = user_by_id(t["user_id"]) if t else None
    if usr and usr["tg_id"]: send(int(usr["tg_id"]), "🔒 تم إغلاق تذكرتك #%s. شكراً لتواصلك ✨" % a[0])
    cb_tickets(c, u, ["0"])

@cb("a_to", admin=True)
def cb_ticket_open(c, u, a):
    run("UPDATE tickets SET status='open' WHERE id=?", (int(a[0]),)); cb_ticket_view(c, u, a)

# ---------------- الإعلانات ----------------
@cb("a_ann", admin=True)
def cb_announcements(c, u, a):
    toast(c); clear_state(c.from_user.id); rs = rows("SELECT * FROM announcements ORDER BY id DESC LIMIT 10")
    s = T.banner("الإعلانات", "📢") + ("\n".join("%s <b>#%d</b> %s" % ("🟢" if r["is_active"] else "⚫", r["id"], e(r["text"][:60])) for r in rs) or "لا توجد إعلانات.")
    kb = [[B("➕ إعلان جديد", "a_ana")]]
    for r in rs: kb.append([B(("⏸ إيقاف #%d" if r["is_active"] else "▶️ تفعيل #%d") % r["id"], "a_ant:%d" % r["id"]), B("🗑 #%d" % r["id"], "a_and:%d" % r["id"])])
    kb.append(ADM_BACK); show(c, s, K(*kb))

@cb("a_ant", admin=True)
def cb_ann_toggle(c, u, a):
    run("UPDATE announcements SET is_active=1-is_active WHERE id=?", (int(a[0]),)); toast(c, "تم"); cb_announcements(c, u, [])

@cb("a_and", admin=True)
def cb_ann_delete(c, u, a):
    run("DELETE FROM announcements WHERE id=?", (int(a[0]),)); toast(c, "🗑 حُذف"); cb_announcements(c, u, [])

@cb("a_ana", admin=True)
def cb_ann_add(c, u, a):
    toast(c); set_state(c.from_user.id, "a_anntext"); ask(c.message.chat.id, "📢 أرسل <b>نص الإعلان</b> (يظهر بالموقع وفي البوت):", "a_ann")

@step("a_anntext")
def step_ann_text(m, st):
    set_state(m.from_user.id, "a_annlevel", text=(m.text or "").strip()[:500])
    send(m.chat.id, "🎨 اختر <b>نوع الإعلان</b>:", K([B("ℹ️ معلومة", "a_anl:info"), B("✅ نجاح", "a_anl:success")], [B("⚠️ تحذير", "a_anl:warning"), B("🚨 خطر", "a_anl:danger")]))

@cb("a_anl", admin=True)
def cb_ann_level(c, u, a):
    st = get_state(c.from_user.id)
    if not st or st["step"] != "a_annlevel": return toast(c, "انتهت العملية.", True)
    run("INSERT INTO announcements(text,level,is_active,icon,icon_name) VALUES(?,?,1,'bell','bell')", (st["data"]["text"], a[0])); clear_state(c.from_user.id)
    toast(c, "✅ تم النشر"); cb_announcements(c, u, [])

# ---------------- الشارات ----------------
@cb("a_stp", admin=True)
def cb_stamps(c, u, a):
    toast(c); clear_state(c.from_user.id)
    rs = rows("SELECT s.*, (SELECT COUNT(*) FROM number_stamps WHERE stamp_id=s.id) cnt FROM stamps s ORDER BY id")
    s = T.banner("الشارات (Stamps)", "🏅") + ("\n".join("🏅 <b>%s</b>  <code>%s</code>  %s  ·  %d رقم" % (e(r["name"]), e(r["color"]), e(r["shape"]), r["cnt"]) for r in rs) or "لا توجد شارات.")
    kb = [[B("➕ شارة جديدة", "a_sta")]] + [[B("🗑 حذف " + r["name"], "a_std:%d" % r["id"])] for r in rs] + [ADM_BACK]
    show(c, s, K(*kb))

@cb("a_sta", admin=True)
def cb_stamp_add(c, u, a):
    toast(c); set_state(c.from_user.id, "a_stamp")
    ask(c.message.chat.id, "🏅 أرسل: <code>الاسم اللون الشكل</code>\nمثال: <code>موثوق #10b981 shield</code>\nالأشكال: seal · star · shield · crown · ribbon", "a_stp")

@step("a_stamp")
def step_stamp(m, st):
    p = (m.text or "").split()
    if not p: return send(m.chat.id, "❌ أرسل الاسم أولاً.")
    color = next((x for x in p[1:] if re.match(r"^#[0-9a-fA-F]{6}$", x)), "#f59e0b")
    shape = next((x for x in p[1:] if x in ("seal", "star", "shield", "crown", "ribbon")), "seal")
    name = " ".join(x for x in p if x != color and x != shape)[:30]
    try:
        run("INSERT INTO stamps(name,color,shape) VALUES(?,?,?)", (name, color, shape)); clear_state(m.from_user.id)
        send(m.chat.id, "✅ تمت إضافة الشارة <b>%s</b>" % e(name), K([B("🏅 الشارات", "a_stp")]))
    except sqlite3.IntegrityError:
        send(m.chat.id, "❌ الشارة موجودة مسبقاً.")

@cb("a_std", admin=True)
def cb_stamp_del(c, u, a):
    run("DELETE FROM number_stamps WHERE stamp_id=?", (int(a[0]),)); run("DELETE FROM stamps WHERE id=?", (int(a[0]),)); toast(c, "🗑 حُذفت")
    cb_stamps(c, u, [])

# ---------------- إعدادات API ----------------
@cb("a_set", admin=True)
def cb_settings(c, u, a):
    toast(c); clear_state(c.from_user.id)
    kb = [[B(t, "a_sg:%d" % i)] for i, (_g, t, _it) in enumerate(SETTING_GROUPS)]
    kb.append([B("👑 مدراء إضافيون (IDs)", "a_sadm")]); kb.append(ADM_BACK)
    show(c, T.banner("إعدادات API والمتجر", "⚙️") + "كل تعديل يُحفظ <b>فوراً</b> في قاعدة البيانات ويسري على الموقع والبوت معاً.", K(*kb))

@cb("a_sg", admin=True)
def cb_setting_group(c, u, a):
    toast(c); gi = int(a[0]); _g, title, items = SETTING_GROUPS[gi]
    s = T.banner(title, "⚙️"); kb = []
    for k, lbl, sec in items:
        val = get_setting(k, "")
        s += "• <b>%s</b>\n  <code>%s</code>\n" % (e(lbl), e(mask_secret(val) if sec else (val or "— غير مضبوط —")))
        kb.append([B("✏️ " + lbl, "a_sk:%d" % ALL_SETTING_KEYS.index((k, lbl, sec)))])
    kb.append([B("◀️ رجوع", "a_set")]); show(c, s, K(*kb))

@cb("a_sk", admin=True)
def cb_setting_edit(c, u, a):
    toast(c); k, lbl, sec = ALL_SETTING_KEYS[int(a[0])]; set_state(c.from_user.id, "a_setval", key=k, sec=sec, lbl=lbl)
    ask(c.message.chat.id, "✏️ أرسل القيمة الجديدة لـ <b>%s</b>%s\n(أرسل <code>-</code> لمسح القيمة)" % (e(lbl), "\n🔒 ستُحذف رسالتك فوراً." if sec else ""), "a_set")

@step("a_setval")
def step_setval(m, st):
    k, sec, lbl = st["data"]["key"], st["data"]["sec"], st["data"]["lbl"]; v = (m.text or "").strip()
    if sec: del_msg(m)
    v = "" if v == "-" else v
    if k in ("TG_API_ID",) and v and not v.isdigit(): return send(m.chat.id, "❌ API ID أرقام فقط.")
    if k.endswith(("_RATE_YE", "_RATE_SA", "MIN_DEPOSIT_USD", "TRANSFER_FEE", "REFERRAL_REWARD", "DAILY_BONUS")) and v:
        try: float(v)
        except ValueError: return send(m.chat.id, "❌ أرسل رقماً.")
    set_setting(k, v); clear_state(m.from_user.id); audit(m.from_user.id, "set_setting", k)
    send(m.chat.id, "✅ تم تحديث <b>%s</b>\n<code>%s</code>" % (e(lbl), e(mask_secret(v) if sec else (v or "— فارغ —"))), K([B("⚙️ الإعدادات", "a_set")], ADM_BACK))

@cb("a_sadm", admin=True)
def cb_extra_admins(c, u, a):
    toast(c); cur = get_setting("BOT_ADMIN_IDS", "") or "—"; set_state(c.from_user.id, "a_admins")
    ask(c.message.chat.id, "👑 المدراء الحاليون (بالبيئة + الموقع + هنا):\n<code>%s</code>\n\nأرسل قائمة جديدة لآيدي تيليجرام مفصولة بمسافة (أو <code>-</code> للمسح).\n<i>مدراء الموقع المرتبطون بالبوت يُضافون تلقائياً.</i>" % e(", ".join(map(str, sorted(admin_ids()))) + "\n(مخصص: " + cur + ")"), "a_set")

@step("a_admins")
def step_admins(m, st):
    v = (m.text or "").strip(); ids = " ".join(re.findall(r"\d+", v)) if v != "-" else ""
    set_setting("BOT_ADMIN_IDS", ids)
    clear_state(m.from_user.id); send(m.chat.id, "✅ تم الحفظ.", K([B("⚙️ الإعدادات", "a_set")]))

# ---------------- الأدوات الخارجية ----------------
@cb("a_tools", admin=True)
def cb_tools(c, u, a):
    toast(c); auto = get_setting("BOT_AUTO_OTP", "1") == "1"
    kb = [[B("%s سحب الأكواد تلقائياً: %s" % ("🟢" if auto else "🔴", "يعمل" if auto else "متوقف"), "a_tl:otp")],
          [B("🟡 فحص Binance", "a_tl:bn"), B("📧 فحص البريد IMAP", "a_tl:imap")],
          [B("🤖 فحص Telegram API", "a_tl:tg"), B("🩺 حالة النظام", "a_tl:health")],
          [B("📄 آخر السجلات", "a_tl:log"), B("🔄 إعادة تشغيل البوت", "a_tl:rs")], ADM_BACK]
    show(c, T.banner("الأدوات الخارجية", "🛠") + "تحكّم كامل بالأدوات من داخل البوت.", K(*kb))

def _check_imap():
    addr = (get_setting("WA_EMAIL_ADDRESS", "") or "").strip() or (get_setting("EMAIL_ADDRESS", "") or "").strip()
    pwd = (get_setting("WA_EMAIL_PASSWORD", "") or "").strip() or (get_setting("EMAIL_PASSWORD", "") or "").strip()
    host = (get_setting("IMAP_HOST", "imap.gmail.com") or "").strip()
    if not (addr and pwd): return False, "الإيميل/كلمة المرور غير مضبوطين."
    try:
        M = imaplib.IMAP4_SSL(host, timeout=15); M.login(addr, pwd); st, d = M.select("INBOX", readonly=True); M.logout()
        return True, "تسجيل الدخول ناجح ✓  (%s) — الرسائل في INBOX: %s" % (host, (d[0] or b"?").decode())
    except Exception as ex:
        return False, "فشل: " + str(ex)[:120]

def _check_tg():
    aid, ah = (get_setting("TG_API_ID", "") or "").strip(), (get_setting("TG_API_HASH", "") or "").strip()
    if not (aid.isdigit() and re.match(r"^[0-9a-fA-F]{32}$", ah)): return False, "API ID/Hash غير صالحين (الهاش 32 خانة hex)."
    try: from telethon import TelegramClient; from telethon.sessions import StringSession
    except ImportError: return False, "مكتبة telethon غير مثبتة: pip install telethon"
    async def go():
        cl = TelegramClient(StringSession(), int(aid), ah); await cl.connect(); ok = cl.is_connected(); await cl.disconnect(); return ok
    try:
        loop = asyncio.new_event_loop()
        try: ok = loop.run_until_complete(asyncio.wait_for(go(), 25))
        finally: loop.close()
        return (True, "الاتصال بسيرفرات تيليجرام ناجح ✓ (الصيغة صحيحة)") if ok else (False, "تعذر الاتصال.")
    except Exception as ex: return False, "فشل: " + str(ex)[:120]

@cb("a_tl", admin=True)
def cb_tool_action(c, u, a):
    act = a[0]
    if act == "otp":
        set_setting("BOT_AUTO_OTP", "0" if get_setting("BOT_AUTO_OTP", "1") == "1" else "1"); toast(c, "تم"); return cb_tools(c, u, [])
    if act == "rs":
        toast(c); return show(c, "🔄 <b>إعادة تشغيل البوت؟</b>\nسيتوقف لثوانٍ ثم يعود.", K([B("✅ نعم، أعد التشغيل", "a_tl:rsok"), B("❌ لا", "a_tools")]))
    if act == "rsok":
        toast(c, "🔄 جاري إعادة التشغيل…"); show(c, "🔄 <b>جاري إعادة تشغيل البوت…</b>")
        threading.Thread(target=restart_bot, daemon=True).start(); return
    if act == "log":
        toast(c)
        try:
            with open(BOT_LOG, "r", encoding="utf-8", errors="ignore") as f: tail = "".join(f.readlines()[-35:])
        except Exception: tail = "لا يوجد سجل."
        return show(c, T.banner("آخر السجلات", "📄") + "<pre>%s</pre>" % e(tail[-3200:]), K([B("🔄 تحديث", "a_tl:log")], [B("◀️ الأدوات", "a_tools")]))
    if act == "health":
        toast(c); sz = os.path.getsize(DB_PATH) / 1048576 if os.path.exists(DB_PATH) else 0
        imap_ok = bool((get_setting("EMAIL_ADDRESS", "") or get_setting("WA_EMAIL_ADDRESS", "")) and (get_setting("EMAIL_PASSWORD", "") or get_setting("WA_EMAIL_PASSWORD", "")))
        try: import telethon; tl = telethon.__version__
        except Exception: tl = "غير مثبتة"
        s = T.banner("حالة النظام", "🩺") + "🗄 قاعدة البيانات: <code>%s</code> (%.2f MB)\n🧵 خيوط نشطة: %d\n🤖 سحب الأكواد التلقائي: %s\n📧 إعداد البريد: %s\n🔑 Binance: %s\n✈️ telethon: <code>%s</code>\n🔁 فحص أحداث الموقع: كل %d ثانية\n🕒 %s" % (
            e(os.path.basename(DB_PATH)), sz, threading.active_count(), "🟢" if get_setting("BOT_AUTO_OTP", "1") == "1" else "🔴", "✅" if imap_ok else "❌ غير مضبوط",
            "✅" if get_setting("BINANCE_API_KEY", "") else "❌ غير مضبوط", tl, POLL_INTERVAL, now_s())
        return show(c, s, K([B("🔄 تحديث", "a_tl:health")], [B("◀️ الأدوات", "a_tools")]))
    toast(c, "⏳ جاري الفحص…")
    ok, msg = {"bn": binance_check, "imap": _check_imap, "tg": _check_tg}[act]()
    title = {"bn": "فحص Binance", "imap": "فحص البريد", "tg": "فحص Telegram API"}[act]
    show(c, T.banner(title, "✅" if ok else "❌") + e(msg), K([B("🔁 إعادة الفحص", "a_tl:" + act)], [B("◀️ الأدوات", "a_tools")]))

def restart_bot():
    time.sleep(1.5)
    logger.info("restart requested by admin")
    try: bot.stop_polling()
    except Exception: pass
    os.execv(sys.executable, [sys.executable] + sys.argv)

# ---------------- بث رسالة ----------------
@cb("a_bc", admin=True)
def cb_broadcast(c, u, a):
    toast(c); set_state(c.from_user.id, "a_bc")
    ask(c.message.chat.id, "📣 أرسل <b>نص البث</b> لجميع مستخدمي البوت (%d مستخدم).\nيدعم HTML: <code>&lt;b&gt;غامق&lt;/b&gt;</code>" % scalar("SELECT COUNT(*) FROM users WHERE tg_id IS NOT NULL AND is_banned=0"), "a")

@step("a_bc")
def step_bc(m, st):
    text = m.text or m.caption or ""
    if not text.strip(): return send(m.chat.id, "❌ أرسل نصاً.")
    set_state(m.from_user.id, "a_bcc", text=text)
    send(m.chat.id, "📣 <b>معاينة البث:</b>\n%s\n%s\n%s\n\nهل تؤكد الإرسال؟" % (LINE, text, LINE), K([B("✅ إرسال الآن", "a_bcok"), B("❌ إلغاء", "a")]))

@cb("a_bcok", admin=True)
def cb_broadcast_go(c, u, a):
    st = get_state(c.from_user.id)
    if not st or st["step"] != "a_bcc": return toast(c, "انتهت العملية.", True)
    text = st["data"]["text"]; clear_state(c.from_user.id); toast(c, "🚀 بدأ البث")
    show(c, "🚀 <b>جاري البث…</b> سيصلك التقرير عند الانتهاء."); chat = c.message.chat.id
    def work():
        ok = fail = 0
        for r in rows("SELECT tg_id FROM users WHERE tg_id IS NOT NULL AND is_banned=0"):
            try: bot.send_message(int(r["tg_id"]), T.banner(site_name(), "📣") + text, disable_web_page_preview=True); ok += 1
            except ApiTelegramException as ex:
                fail += 1
                if ex.error_code == 429:
                    time.sleep(int(getattr(ex, "result_json", {}).get("parameters", {}).get("retry_after", 3)))
            except Exception: fail += 1
            time.sleep(0.06)
        send(chat, "📣 <b>اكتمل البث</b>\n✅ نجح: %d\n❌ فشل: %d" % (ok, fail), K(ADM_BACK))
    threading.Thread(target=work, daemon=True).start()

# ---------------- نسخة احتياطية ----------------
@cb("a_bak", admin=True)
def cb_backup(c, u, a):
    toast(c, "⏳ جاري إنشاء النسخة…")
    try:
        data = db_backup_bytes(); bio = io.BytesIO(data); bio.name = "matari_backup_%s.db" % datetime.now().strftime("%Y%m%d_%H%M")
        bot.send_document(c.message.chat.id, bio, caption="💾 نسخة احتياطية متسقة من matari.db\n📦 %.2f MB" % (len(data) / 1048576))
    except Exception as ex:
        send(c.message.chat.id, "❌ فشل النسخ: %s" % e(str(ex)[:150]))

# ============================================================
#  20) موجّه الرسائل النصية (الحالات)
# ============================================================
@bot.message_handler(content_types=["text", "photo", "document"], func=lambda m: m.chat.type == "private")
def on_message(m):
    tg = m.from_user.id
    try:
        st = get_state(tg)
        if st:
            fn = STEPS.get(st["step"])
            if fn:
                if st["step"].startswith("a_") and not is_admin_tg(tg):
                    clear_state(tg); return
                u, _ = ctx_user(m.from_user)
                if banned_guard(m.chat.id, u): return
                return fn(m, st)
        go_home(m.chat.id, m.from_user)
    except Exception:
        logger.error("message handler failed:\n%s", traceback.format_exc())
        send(m.chat.id, "⚠️ حدث خطأ غير متوقع، حاول مجدداً.", K(home_row()))

_BOT_UN = {}
def bot_username():
    if "u" not in _BOT_UN: _BOT_UN["u"] = bot.get_me().username
    return _BOT_UN["u"]

# ============================================================
#  21) مزامنة أحداث الموقع → تيليجرام (إشعارات فورية للمدير والمستخدمين)
# ============================================================
def mark(kind, ref):
    try: run("INSERT OR IGNORE INTO bot_notified(kind,ref) VALUES(?,?)", (kind, str(ref)))
    except Exception: pass

BOT_MARK = mark

def _baseline():
    """أول تشغيل: نعتبر كل ما هو موجود سابقاً مُشعَراً به حتى لا نغرق المدير بالإشعارات القديمة."""
    if get_setting("BOT_SYNC_BASELINE"): return
    with tx() as c:
        c.execute("INSERT OR IGNORE INTO bot_notified SELECT 'sale', CAST(id AS TEXT) FROM numbers WHERE status='sold'")
        c.execute("INSERT OR IGNORE INTO bot_notified SELECT 'dep_new', CAST(id AS TEXT) FROM deposits")
        c.execute("INSERT OR IGNORE INTO bot_notified SELECT 'dep_status', CAST(id AS TEXT) FROM deposits WHERE status!='pending'")
        c.execute("INSERT OR IGNORE INTO bot_notified SELECT 'tmsg', CAST(id AS TEXT) FROM ticket_messages WHERE sender='user'")
        c.execute("INSERT OR IGNORE INTO bot_notified SELECT 'tadm', CAST(id AS TEXT) FROM ticket_messages WHERE sender!='user'")
        c.execute("INSERT OR IGNORE INTO bot_notified SELECT 'user', CAST(user_id AS TEXT) FROM users")
        c.execute("INSERT OR IGNORE INTO bot_notified SELECT 'vch', CAST(id AS TEXT) FROM vouchers WHERE is_used=1")
    set_setting("BOT_SYNC_BASELINE", now_s())

def poll_once():
    # 1) مبيعات (من الموقع أو أي مصدر آخر)
    for n in rows("SELECT n.*, u.username, u.custom_id, u.tg_name FROM numbers n LEFT JOIN users u ON u.user_id=n.buyer_id "
                  "LEFT JOIN bot_notified b ON b.kind='sale' AND b.ref=CAST(n.id AS TEXT) WHERE n.status='sold' AND b.ref IS NULL "
                  "ORDER BY n.id LIMIT 30"):
        mark("sale", n["id"])
        notify_admins("🛍 <b>عملية شراء جديدة</b> (الموقع)\n👤 %s  <code>%s</code>\n%s %s <code>%s</code>\n💳 %s" % (
            e(n["tg_name"] or n["username"] or n["buyer_id"]), e(n["custom_id"] or ""), plat_label(n["platform"]), e(n["country"]),
            e(n["phone"]), usd(n["paid_price"] if n["paid_price"] is not None else n["price"])))
    # 2) طلبات/عمليات شحن جديدة
    for d in rows("SELECT d.* FROM deposits d LEFT JOIN bot_notified b ON b.kind='dep_new' AND b.ref=CAST(d.id AS TEXT) "
                  "WHERE b.ref IS NULL ORDER BY d.id LIMIT 30"):
        mark("dep_new", d["id"]); usr = user_by_id(d["user_id"])
        if not usr: continue
        if d["status"] == "pending":
            notify_admins(T.deposit_notice(d, usr, "🌐 <i>من الموقع</i>"), K([B("✅ موافقة", "a_da:%d" % d["id"]), B("❌ رفض", "a_dr:%d" % d["id"])]))
        else:
            notify_admins("💳 <b>شحن جديد</b> (الموقع)\n👤 %s <code>%s</code>\n🏦 %s  ·  %s" % (e(usr["username"]), e(usr["custom_id"]), e(d["method"]), usd(d["amount_usd"])))
    # 3) تغيّر حالة الشحن (موافقة/رفض من لوحة الموقع) → إشعار المستخدم
    for d in rows("SELECT d.* FROM deposits d LEFT JOIN bot_notified b ON b.kind='dep_status' AND b.ref=CAST(d.id AS TEXT) "
                  "WHERE d.status IN ('approved','rejected') AND b.ref IS NULL ORDER BY d.id LIMIT 30"):
        mark("dep_status", d["id"]); usr = user_by_id(d["user_id"])
        if usr and usr["tg_id"]:
            if d["status"] == "approved":
                send(int(usr["tg_id"]), T.banner("تم شحن رصيدك", "✅") + "💵 أُضيف  <b>%s</b>\n💰 رصيدك الآن: <code>%s</code>" % (usd(d["amount_usd"]), usd(usr["balance"])), K([B("🛒 تسوّق الآن", "shop")]))
            else:
                send(int(usr["tg_id"]), T.banner("تم رفض طلب الشحن", "❌") + "🆔 طلب #%d بقيمة %s\nللاستفسار: %s" % (d["id"], usd(d["amount_usd"]), e(get_setting("SUPPORT_USER", ""))))
    # 4) شحن بالأكواد من الموقع
    for v in rows("SELECT v.* FROM vouchers v LEFT JOIN bot_notified b ON b.kind='vch' AND b.ref=CAST(v.id AS TEXT) "
                  "WHERE v.is_used=1 AND b.ref IS NULL ORDER BY v.id LIMIT 30"):
        mark("vch", v["id"]); usr = user_by_id(v["used_by"]) if v["used_by"] else None
        notify_admins("🎟 <b>شحن بكود</b> (الموقع)\n👤 %s <code>%s</code>\n💵 %s" % (e(usr["username"] if usr else "?"), e(usr["custom_id"] if usr else ""), usd(v["amount"])))
        if usr and usr["tg_id"]:
            send(int(usr["tg_id"]), T.banner("تم الشحن", "✅") + "💵 أُضيف  <b>%s</b>\n💰 رصيدك: <code>%s</code>" % (usd(v["amount"]), usd(usr["balance"])))
    # 5) رسائل التذاكر: المستخدم → المدير
    for mm in rows("SELECT m.*, t.user_id FROM ticket_messages m JOIN tickets t ON t.id=m.ticket_id "
                   "LEFT JOIN bot_notified b ON b.kind='tmsg' AND b.ref=CAST(m.id AS TEXT) WHERE m.sender='user' AND b.ref IS NULL ORDER BY m.id LIMIT 30"):
        mark("tmsg", mm["id"]); usr = user_by_id(mm["user_id"])
        first = scalar("SELECT COUNT(*) FROM ticket_messages WHERE ticket_id=? AND id<?", (mm["ticket_id"], mm["id"])) == 0
        notify_admins("%s <b>%s</b> #%d\n👤 %s <code>%s</code>\n💬 %s" % ("🎫" if first else "💬", "تذكرة دعم جديدة" if first else "رسالة دعم جديدة", mm["ticket_id"],
                      e(usr["tg_name"] or usr["username"]) if usr else "?", e(usr["custom_id"]) if usr else "", e(mm["text"][:500])),
                      K([B("✍️ رد", "a_tr:%d" % mm["ticket_id"]), B("📖 فتح", "a_tv:%d" % mm["ticket_id"])]))
    # 6) ردود الإدارة (من لوحة الموقع) → المستخدم
    for mm in rows("SELECT m.*, t.user_id FROM ticket_messages m JOIN tickets t ON t.id=m.ticket_id "
                   "LEFT JOIN bot_notified b ON b.kind='tadm' AND b.ref=CAST(m.id AS TEXT) WHERE m.sender!='user' AND b.ref IS NULL ORDER BY m.id LIMIT 30"):
        mark("tadm", mm["id"]); usr = user_by_id(mm["user_id"])
        if usr and usr["tg_id"]:
            send(int(usr["tg_id"]), T.banner("رد من الدعم", "🛡") + e(mm["text"]) + "\n\n<i>للرد: افتح «الدعم الفني» من القائمة.</i>", K([B("🎧 الدعم الفني", "sup")]))
    # 7) مستخدمون جدد من الموقع
    for x in rows("SELECT u.* FROM users u LEFT JOIN bot_notified b ON b.kind='user' AND b.ref=CAST(u.user_id AS TEXT) WHERE b.ref IS NULL LIMIT 30"):
        mark("user", x["user_id"])
        if not x["tg_id"]:
            notify_admins("👤 <b>مستخدم جديد</b> (الموقع)\n%s  ·  <code>%s</code>" % (e(x["username"]), e(x["email"])))
    # 8) طابور إشعارات داخلية (إحالات…)
    while NOTIFY_QUEUE:
        tg, kind, payload = NOTIFY_QUEUE.pop(0)
        if kind == "referral":
            send(tg, "🎉 <b>مكافأة إحالة!</b>\nأضيف  <b>%s</b>  لرصيدك لأن أحد مدعوّيك أتمّ أول عملية شراء." % usd(payload))

POLLER = {"last_ok": 0, "errors": 0}

def poller_loop():
    try: _baseline()
    except Exception: logger.exception("baseline")
    while True:
        try:
            poll_once(); POLLER["last_ok"] = time.time()
        except Exception:
            POLLER["errors"] += 1; logger.error("poller error:\n%s", traceback.format_exc())
        time.sleep(POLL_INTERVAL)

# ============================================================
#  22) التشغيل
# ============================================================
def _single_instance(background=False):
    try:
        import fcntl, tempfile
        fh = open(os.path.join(tempfile.gettempdir(), "matari_bot.lock"), "w")
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fh
    except ImportError:
        return True
    except OSError:
        msg = "البوت يعمل بالفعل في عملية أخرى."
        logger.info(msg)
        if background: raise SystemExit(0)
        print("⚠️ " + msg + " أوقفه أولاً (pkill -f bot.py)."); sys.exit(1)

def _start_health_server():
    """اختياري لـ Render (Web Service): BOT_HEALTH_SERVER=1 يفتح منفذ PORT لفحص الصحة. لا تفعّله لو web.py يعمل في نفس الخدمة."""
    if os.environ.get("BOT_HEALTH_SERVER", "0") != "1": return
    from http.server import BaseHTTPRequestHandler, HTTPServer
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.send_header("Content-Type", "text/plain; charset=utf-8"); self.end_headers()
            self.wfile.write(b"matari bot OK")
        def log_message(self, *a): pass
    srv = HTTPServer(("0.0.0.0", int(os.environ.get("PORT", "10000"))), H)
    threading.Thread(target=srv.serve_forever, daemon=True, name="health").start()
    logger.info("health server on port %s", os.environ.get("PORT", "10000"))

def main(background=False):
    lock = _start_lock = _single_instance(background)
    if not background: _start_health_server()
    ensure_schema()
    token = ENV_TOKEN or (get_setting("BOT_TOKEN", "") or "").strip()
    if not token:
        # أول تشغيل: يطلب التوكن ويحفظه في قاعدة البيانات، بدون أوامر خارجية
        if background or not sys.stdin.isatty():
            logger.error("BOT_TOKEN غير مضبوط (متغير البيئة أو الإعدادات). البوت متوقف.")
            print("❌ لم يتم ضبط BOT_TOKEN (متغير البيئة أو الإعدادات). البوت متوقف.")
            sys.exit(1)
        token = input("🔑 أدخل توكن البوت من BotFather: ").strip()
        if not token:
            print("❌ التوكن مطلوب."); sys.exit(1)
        set_setting("BOT_TOKEN", token)
    bot.token = token
    if not admin_ids():
        # أول تشغيل: يطلب آيدي المدير ويحفظه
        raw = input("👑 أدخل آيدي تيليجرام الخاص بك (المدير): ").strip() if sys.stdin.isatty() else ""
        ids = re.findall(r"\d+", raw)
        if ids:
            set_setting("BOT_ADMIN_IDS", ",".join(ids))
        else:
            print("⚠️ لم يتم إدخال آيدي المدير، لن تقدر تستخدم لوحة الإدارة.")
    try:
        me = bot.get_me(); logger.info("Bot @%s started | DB=%s | admins=%s", me.username, DB_PATH, sorted(admin_ids()))
    except Exception as ex:
        logger.error("فشل الاتصال بتيليجرام (تحقق من التوكن/الإنترنت): %s", ex)
        print("❌ فشل الاتصال بتيليجرام (تحقق من التوكن/الإنترنت):", ex); sys.exit(1)
    try:
        sell_db_init()
    except Exception as ex:
        logger.warning("sell schema: %s", ex)
    try: bot.delete_webhook()
    except Exception: pass
    try:
        bot.set_my_commands([types.BotCommand("start", "ابدأ / القائمة الرئيسية"), types.BotCommand("menu", "القائمة الرئيسية"),
                             types.BotCommand("balance", "رصيدي"), types.BotCommand("admin", "لوحة المدير"),
                             types.BotCommand("cancel", "إلغاء العملية الحالية")])
    except Exception: pass
    threading.Thread(target=poller_loop, daemon=True, name="site-sync").start()
    notify_admins("✅ <b>البوت يعمل الآن</b> — متزامن مع الموقع.\n🗄 <code>%s</code>\n🕒 %s" % (e(os.path.basename(DB_PATH)), now_s()),
                  K([B("👑 لوحة المدير", "a")]))
    while True:
        try:
            bot.infinity_polling(timeout=30, long_polling_timeout=30, skip_pending=True, allowed_updates=["message", "callback_query"])
        except KeyboardInterrupt:
            break
        except Exception:
            logger.error("polling crashed, retry in 5s:\n%s", traceback.format_exc()); time.sleep(5)

def start_in_background():
    """يُستدعى من web.py: يشغّل البوت في خيط خلفي داخل نفس عملية الموقع،
    فيستخدمان نفس ملف matari.db بالضبط (مزامنة كاملة بلا أي إعداد إضافي)."""
    def run():
        try:
            main(background=True)
        except SystemExit:
            pass
        except Exception:
            logger.error("bot thread crashed:\n%s", traceback.format_exc())
    t = threading.Thread(target=run, daemon=True, name="telegram-bot")
    t.start()
    return t

if __name__ == "__main__":
    main()

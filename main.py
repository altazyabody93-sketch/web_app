# ============================
# IMPORTS
# ============================
from __future__ import annotations

import asyncio
import csv
import json
import logging
import os
import random
import re
import shutil
import smtplib
import sqlite3
import time
import uuid
from contextlib import closing
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, BotCommand,
    FSInputFile,
)


# ============================
# CONFIG
# ============================
BOT_TOKEN = "8247238031:AAGIIHhPYAuJCxdRzNWVdchYE5U7leGbmrA"
ADMIN_IDS = {7325566792}
SUPER_ADMIN_IDS = {7602226699}

DATABASE_PATH = os.environ.get("DATABASE_PATH", "matary.db")
LOG_LEVEL = "INFO"
BOT_NAME = "المطري دعم"
RATE_LIMIT_SECONDS = 1
BACKUP_DIR = "backups"

if not BOT_TOKEN or ":" not in BOT_TOKEN:
    raise SystemExit("❌ ضع BOT_TOKEN")
if not ADMIN_IDS or 0 in ADMIN_IDS:
    raise SystemExit("❌ ضع ADMIN_IDS")

Path(BACKUP_DIR).mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logging.getLogger("aiogram").setLevel(logging.WARNING)
log = logging.getLogger("matary")


# ============================
# EMAIL
# ============================
SENDER_EMAILS = [
    {"email": "altazyabody93@gmail.com",   "password": "xxxx xxxx xxxx xxxx"},
    {"email": "altazyabody9999@gmail.com", "password": "xxxx xxxx xxxx xxxx"},
    {"email": "altazyabody733@gmail.com",  "password": "xxxx xxxx xxxx xxxx"},
]

WHATSAPP_EMAILS = [
    "1979975992710010@support.whatsapp.com",
    "support@whatsapp.com",
    "support@support.whatsapp.com",
    "android@support.whatsapp.com",
    "ios@support.whatsapp.com",
    "web@support.whatsapp.com",
]


# ============================
# CONSTANTS / ENUMS
# ============================
class RStatus(str, Enum):
    NEW = "NEW"
    PREPARING = "PREPARING"
    SENT = "SENT"
    WAITING_REPLY = "WAITING_REPLY"
    REPLY_RECEIVED = "REPLY_RECEIVED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


STATUS_AR = {
    RStatus.NEW: "🆕 جديد",
    RStatus.PREPARING: "⏳ قيد التجهيز",
    RStatus.SENT: "📤 تم الإرسال",
    RStatus.WAITING_REPLY: "⏰ بانتظار الرد",
    RStatus.REPLY_RECEIVED: "📨 وصل الرد",
    RStatus.RESOLVED: "✅ تم الحل",
    RStatus.CLOSED: "🔒 مغلق",
    RStatus.FAILED: "❌ فشل",
    RStatus.CANCELLED: "✕ ملغي",
}

PHONE_RE = re.compile(r"^\+\d{8,15}$")
CODE_RE = re.compile(r"^MTR-\d{6}$")

# اقتباسات عشوائية
REPLY_QUOTES = [
    "✨ وصلنا الرد، ونحن نهتم بك 💙",
    "🎯 خطوة بخطوة، ونحن معك",
    "💎 لا تقلق، الأمر تحت السيطرة",
    "🚀 وصل رد جديد، تابعنا",
    "🌟 نحن معك حتى النهاية",
    "🔥 كل ثانية نقترب من الحل",
    "💚 اطمئن، فريقنا يعمل الآن",
    "🎉 أخبار جيدة قادمة",
]

WELCOME_ANIMATIONS = [
    "🌟",
    "✨",
    "💫",
    "⭐",
    "🌠",
    "🎇",
    "🌈",
    "💎",
]


def now() -> datetime:
    return datetime.utcnow()


def fmt_dt(dt) -> str:
    if not dt:
        return "—"
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except ValueError:
            return dt
    return dt.strftime("%Y-%m-%d %H:%M")


def divider() -> str:
    return "━━━━━━━━━━━━━━━━"


def mask_phone(s: str) -> str:
    if not s or len(s) < 7:
        return s
    return f"{s[:4]}*******{s[-3:]}"


def is_valid_phone(s: str) -> bool:
    return bool(s and PHONE_RE.match(s.strip().replace(" ", "").replace("-", "")))


def norm_phone(s: str) -> str:
    return s.strip().replace(" ", "").replace("-", "")


def random_quote() -> str:
    return random.choice(REPLY_QUOTES)


def random_emoji() -> str:
    return random.choice(WELCOME_ANIMATIONS)


# ============================
# DATABASE
# ============================
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER UNIQUE NOT NULL,
    username TEXT,
    first_name TEXT,
    created_at TEXT NOT NULL,
    last_activity TEXT NOT NULL,
    requests_count INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS request_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    description TEXT,
    template TEXT NOT NULL,
    enabled INTEGER DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL,
    phone TEXT NOT NULL,
    request_type_id INTEGER NOT NULL,
    request_type_name TEXT NOT NULL,
    message TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'NEW',
    external_message_id TEXT,
    external_thread_id TEXT,
    correlation_id TEXT,
    reply_text TEXT,
    admin_note TEXT,
    retry_count INTEGER DEFAULT 0,
    last_attempt TEXT,
    next_attempt TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(request_type_id) REFERENCES request_types(id)
);
CREATE INDEX IF NOT EXISTS ix_req_status ON requests(status, created_at);
CREATE INDEX IF NOT EXISTS ix_req_corr ON requests(correlation_id);
CREATE TABLE IF NOT EXISTS message_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type_id INTEGER NOT NULL,
    body TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(type_id) REFERENCES request_types(id)
);
CREATE TABLE IF NOT EXISTS request_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL,
    event TEXT NOT NULL,
    details TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(request_id) REFERENCES requests(id)
);
CREATE TABLE IF NOT EXISTS admins (
    telegram_id INTEGER PRIMARY KEY,
    role TEXT NOT NULL DEFAULT 'ADMIN',
    added_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id INTEGER,
    action TEXT NOT NULL,
    target TEXT,
    details TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS buttons_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    button_key TEXT UNIQUE NOT NULL,
    label TEXT NOT NULL,
    position INTEGER DEFAULT 0,
    enabled INTEGER DEFAULT 1
);
"""

DEFAULT_TYPES = [
    ("حظر حساب", "طلب مراجعة لحساب محظور",
     "مرحبًا،\nأرغب في طلب مراجعة للحساب المرتبط بالرقم:\n{phone}\n\n"
     "رقم الطلب: {request_id}\n\nيرجى مراجعة الحالة وفق الإجراءات الرسمية.", 10),
    ("حظر مؤقت", "طلب مراجعة لحظر مؤقت",
     "مرحبًا،\nأرغب في طلب مراجعة لحظر مؤقت على الحساب:\n{phone}\n\n"
     "رقم الطلب: {request_id}", 20),
    ("مشكلة تسجيل", "مشكلة في تسجيل الدخول",
     "مرحبًا،\nأواجه مشكلة في تسجيل الدخول للحساب:\n{phone}\n\n"
     "رقم الطلب: {request_id}", 30),
    ("طلب مراجعة", "طلب مراجعة عام",
     "مرحبًا،\nأرغب في طلب مراجعة:\n{phone}\n\n"
     "رقم الطلب: {request_id}", 40),
    ("مشكلة أخرى", "مشكلة أخرى",
     "مرحبًا،\nلدي مشكلة بخصوص الحساب:\n{phone}\n\n"
     "رقم الطلب: {request_id}", 50),
]

DEFAULT_SETTINGS = {
    "AUTO_SEND": "1",
    "AUTO_REPLY": "1",
    "MAINTENANCE": "0",
    "LOGGING": "1",
    "RETRY_ENABLED": "1",
    "MAX_RETRIES": "3",
    "RATE_LIMIT": str(RATE_LIMIT_SECONDS),
    "CONNECTOR_MODE": "not_configured",
    "welcome_message": "🌟 أهلاً وسهلاً بك في <b>المطري دعم</b> 🌟",
    "show_admin_button": "1",
}

DEFAULT_RESPONSE_KEYWORDS = {
    "resolved_keywords": ["resolved", "unbanned", "تم الحل", "تمت المراجعة"],
    "pending_keywords": ["pending", "review", "قيد المراجعة", "بانتظار"],
    "rejected_keywords": ["rejected", "denied", "مرفوض", "رفض"],
}

DEFAULT_BUTTONS = [
    ("new_request", "📩 طلب جديد", 10),
    ("my_requests", "📋 طلباتي", 20),
    ("help", "🆘 المساعدة", 30),
    ("admin_panel", "⚙️ لوحة التحكم", 40),
]


def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def db_init() -> None:
    with closing(db_connect()) as conn:
        conn.executescript(SCHEMA)
        cur = conn.execute("SELECT COUNT(*) AS c FROM request_types")
        if cur.fetchone()["c"] == 0:
            for name, desc, tmpl, pos in DEFAULT_TYPES:
                conn.execute(
                    "INSERT INTO request_types(name, description, template, enabled, created_at) "
                    "VALUES (?,?,?,1,?)",
                    (name, desc, tmpl, now().isoformat()),
                )
                tid = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
                conn.execute(
                    "INSERT INTO message_templates(type_id, body, updated_at) VALUES (?,?,?)",
                    (tid, tmpl, now().isoformat()),
                )
        for k, v in DEFAULT_SETTINGS.items():
            conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES (?,?)", (k, v))
        conn.execute(
            "INSERT OR IGNORE INTO settings(key,value) VALUES (?,?)",
            ("response_keywords", json.dumps(DEFAULT_RESPONSE_KEYWORDS, ensure_ascii=False)),
        )
        for a in ADMIN_IDS:
            conn.execute(
                "INSERT OR IGNORE INTO admins(telegram_id, role, added_at) VALUES (?,?,?)",
                (a, "ADMIN", now().isoformat()),
            )
        for a in SUPER_ADMIN_IDS:
            conn.execute(
                "INSERT OR REPLACE INTO admins(telegram_id, role, added_at) VALUES (?,?,?)",
                (a, "SUPER_ADMIN", now().isoformat()),
            )
        for key, label, pos in DEFAULT_BUTTONS:
            conn.execute(
                "INSERT OR IGNORE INTO buttons_config(button_key, label, position) VALUES (?,?,?)",
                (key, label, pos),
            )
        conn.commit()


try:
    db_init()
except Exception as _e:
    print(f"DB init warning: {_e}")


def db_exec(query: str, params: tuple = ()) -> None:
    with closing(db_connect()) as conn:
        conn.execute(query, params)
        conn.commit()


def db_one(query: str, params: tuple = ()) -> Optional[sqlite3.Row]:
    with closing(db_connect()) as conn:
        cur = conn.execute(query, params)
        return cur.fetchone()


def db_all(query: str, params: tuple = ()) -> list[sqlite3.Row]:
    with closing(db_connect()) as conn:
        cur = conn.execute(query, params)
        return cur.fetchall()


def get_setting(key: str, default: str = "") -> str:
    row = db_one("SELECT value FROM settings WHERE key=?", (key,))
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    db_exec(
        "INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def log_event(actor_id: Optional[int], action: str, target: str | None = None,
              details: str | None = None) -> None:
    if get_setting("LOGGING", "1") != "1":
        return
    db_exec(
        "INSERT INTO logs(actor_id, action, target, details, created_at) VALUES (?,?,?,?,?)",
        (actor_id, action, target, details, now().isoformat()),
    )


def upsert_user(tg_user) -> sqlite3.Row:
    ts = now().isoformat()
    row = db_one("SELECT * FROM users WHERE telegram_id=?", (tg_user.id,))
    if row:
        db_exec(
            "UPDATE users SET username=?, first_name=?, last_activity=? WHERE telegram_id=?",
            (tg_user.username, tg_user.first_name, ts, tg_user.id),
        )
    else:
        db_exec(
            "INSERT INTO users(telegram_id, username, first_name, created_at, last_activity) "
            "VALUES (?,?,?,?,?)",
            (tg_user.id, tg_user.username, tg_user.first_name, ts, ts),
        )
    return db_one("SELECT * FROM users WHERE telegram_id=?", (tg_user.id,))
    
# ============================
# KEYBOARDS
# ============================
def get_buttons_config() -> list:
    """يرجع الأزرار مرتبة من قاعدة البيانات"""
    return db_all(
        "SELECT button_key, label, position, enabled FROM buttons_config "
        "WHERE enabled=1 ORDER BY position ASC, id ASC"
    )


def main_menu_kb() -> InlineKeyboardMarkup:
    """القائمة الرئيسية (Inline)"""
    rows = db_all("SELECT id, name FROM request_types WHERE enabled=1 ORDER BY id")
    kb = [[InlineKeyboardButton(text=f"📩 {r['name']}", callback_data=f"rt:{r['id']}")] for r in rows]
    kb.append([
        InlineKeyboardButton(text="📋 طلباتي", callback_data="my:0"),
        InlineKeyboardButton(text="🆘 المساعدة", callback_data="help"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def reply_menu_kb(is_admin_user: bool = False) -> ReplyKeyboardMarkup:
    """القائمة السفلية (Reply) — فيها زر لوحة التحكم"""
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📩 طلب جديد")],
            [KeyboardButton(text="📋 طلباتي"), KeyboardButton(text="🆘 المساعدة")],
        ],
        resize_keyboard=True,
    )
    if is_admin_user:
        kb.keyboard.append([KeyboardButton(text="⚙️ لوحة التحكم")])
    return kb


def admin_reply_kb() -> ReplyKeyboardMarkup:
    """قائمة الأدمن السفلية"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 الطلبات"), KeyboardButton(text="📊 الإحصائيات")],
            [KeyboardButton(text="👤 المستخدمون"), KeyboardButton(text="⚙️ الإعدادات")],
            [KeyboardButton(text="🎨 تخصيص الأزرار"), KeyboardButton(text="📝 القوالب")],
            [KeyboardButton(text="🔙 رجوع للقائمة الرئيسية")],
        ],
        resize_keyboard=True,
    )


def back_kb(target: str = "menu:main", label: str = "‹ رجوع") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=label, callback_data=target)]])


def admin_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 الطلبات", callback_data="adm:reqs:NEW:0"),
         InlineKeyboardButton(text="🗂 أنواع المشاكل", callback_data="adm:types")],
        [InlineKeyboardButton(text="📝 القوالب", callback_data="adm:templates"),
         InlineKeyboardButton(text="📊 الإحصائيات", callback_data="adm:stats")],
        [InlineKeyboardButton(text="👤 المستخدمون", callback_data="adm:users"),
         InlineKeyboardButton(text="📜 السجل", callback_data="adm:logs")],
        [InlineKeyboardButton(text="🎨 تخصيص الأزرار", callback_data="adm:buttons_config")],
        [InlineKeyboardButton(text="⚙ الإعدادات", callback_data="adm:settings"),
         InlineKeyboardButton(text="🗄 Backup", callback_data="adm:backup")],
        [InlineKeyboardButton(text="📤 تصدير CSV", callback_data="adm:export_csv")],
    ])


def status_filter_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🆕 جديدة", callback_data="adm:reqs:NEW:0"),
         InlineKeyboardButton(text="📤 مرسلة", callback_data="adm:reqs:SENT:0")],
        [InlineKeyboardButton(text="⏰ بانتظار الرد", callback_data="adm:reqs:WAITING_REPLY:0"),
         InlineKeyboardButton(text="📨 وصل رد", callback_data="adm:reqs:REPLY_RECEIVED:0")],
        [InlineKeyboardButton(text="✅ مكتملة", callback_data="adm:reqs:RESOLVED:0"),
         InlineKeyboardButton(text="❌ فاشلة", callback_data="adm:reqs:FAILED:0")],
        [InlineKeyboardButton(text="‹ رجوع", callback_data="adm:panel")],
    ])


def request_admin_kb(req_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 تغيير الحالة", callback_data=f"adm:chst:{req_id}")],
        [InlineKeyboardButton(text="📨 محاكاة رد وارد", callback_data=f"adm:simreply:{req_id}")],
        [InlineKeyboardButton(text="🔁 إعادة إرسال", callback_data=f"adm:resend:{req_id}")],
        [InlineKeyboardButton(text="📝 ملاحظة", callback_data=f"adm:note:{req_id}")],
        [InlineKeyboardButton(text="✉ رسالة للمستخدم", callback_data=f"adm:msg:{req_id}")],
        [InlineKeyboardButton(text="‹ رجوع", callback_data="adm:reqs:NEW:0")],
    ])


# ============================
# EMAIL SENDER
# ============================
def send_support_email(subject: str, body: str) -> dict:
    """يبعت الإيميلات للستة عناوين، من إيميل عشوائي"""
    sender = random.choice(SENDER_EMAILS)
    results = {"sent": 0, "failed": 0}

    for to_email in WHATSAPP_EMAILS:
        try:
            msg = MIMEMultipart()
            msg['From'] = sender['email']
            msg['To'] = to_email
            msg['Subject'] = subject
            msg.attach(MIMEText(body, 'plain', 'utf-8'))

            with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=20) as server:
                server.login(sender['email'], sender['password'].replace(' ', ''))
                server.send_message(msg)

            results["sent"] += 1
            log.info(f"✅ {sender['email']} → {to_email}")
            time.sleep(1)
        except Exception as e:
            results["failed"] += 1
            log.error(f"❌ {to_email}: {e}")

    return results


# ============================
# FSM STATES
# ============================
class Flow(StatesGroup):
    phone = State()
    confirm = State()


class AdminFlow(StatesGroup):
    add_type_name = State()
    add_type_desc = State()
    add_type_template = State()
    edit_type_name = State()
    edit_type_template = State()
    edit_template = State()
    search_user = State()
    req_note = State()
    req_msg = State()
    sim_reply = State()
    edit_button_label = State()
    edit_button_position = State()
    edit_welcome = State()


# ============================
# BOT / DISPATCHER
# ============================
bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()
dp.include_router(router)


async def notify_admins(text: str) -> None:
    for a in (ADMIN_IDS | SUPER_ADMIN_IDS):
        try:
            await bot.send_message(a, text)
        except TelegramAPIError:
            pass


async def edit_or_send(cb: CallbackQuery, text: str, kb: InlineKeyboardMarkup | None = None) -> None:
    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest:
        await cb.message.answer(text, reply_markup=kb)


# ============================
# USER HANDLERS
# ============================
@router.message(CommandStart())
async def cmd_start(m: Message, state: FSMContext):
    await state.clear()
    upsert_user(m.from_user)
    is_admin_user = is_admin(m.from_user.id)

    if get_setting("MAINTENANCE", "0") == "1" and not is_admin_user:
        await m.answer("🛠 البوت في وضع الصيانة حالياً.")
        return

    emoji = random_emoji()
    welcome = get_setting("welcome_message", "🌟 أهلاً وسهلاً بك 🌟")
    text = (
        f"{divider()}\n"
        f"{emoji} <b>{BOT_NAME}</b> {emoji}\n"
        f"{divider()}\n\n"
        f"{welcome}\n\n"
        f"👋 مرحباً <b>{m.from_user.first_name}</b>\n\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"✨ اختر الخدمة التي تريدها 👇\n"
        f"━━━━━━━━━━━━━━━━"
    )

    await m.answer(text, reply_markup=reply_menu_kb(is_admin_user))
    await m.answer(
        "⚠️ تنويه: هذا النظام يساعدك على تجهيز طلب مراجعة رسمي ومتابعته. "
        "لا يقوم بإزالة حظر واتساب ولا بتجاوز سياساتها.",
        reply_markup=main_menu_kb(),
    )


@router.message(Command("id"))
async def cmd_id(m: Message):
    await m.answer(
        f"🆔 <b>معلوماتك:</b>\n\n"
        f"👤 الاسم: {m.from_user.first_name}\n"
        f"🆔 الآيدي: <code>{m.from_user.id}</code>\n"
        f"👤 اليوزر: @{m.from_user.username or 'لا يوجد'}"
    )


@router.message(Command("cancel"))
async def cmd_cancel(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(
        "✕ تم إلغاء العملية الحالية.",
        reply_markup=reply_menu_kb(is_admin(m.from_user.id)),
    )


@router.message(F.text == "📩 طلب جديد")
async def btn_new_request(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(
        f"{divider()}\n📝 <b>طلب دعم جديد</b>\n{divider()}\n\n"
        "اختر نوع المشكلة:",
        reply_markup=main_menu_kb(),
    )


@router.message(F.text == "📋 طلباتي")
async def btn_my_requests(m: Message):
    user = upsert_user(m.from_user)
    total = db_one("SELECT COUNT(*) AS c FROM requests WHERE user_id=?", (user["id"],))["c"]
    rows = db_all(
        "SELECT code, request_type_name, status, created_at FROM requests "
        "WHERE user_id=? ORDER BY created_at DESC LIMIT 5",
        (user["id"],),
    )
    if not rows:
        await m.answer("📭 لا توجد طلبات بعد.")
        return
    lines = [f"{divider()}\n🗂 <b>طلباتي</b> ({total})\n{divider()}\n"]
    for r in rows:
        lines.append(
            f"• <code>{r['code']}</code>\n"
            f"  {r['request_type_name']}\n"
            f"  {status_ar(r['status'])} — {fmt_dt(r['created_at'])}"
        )
    await m.answer("\n".join(lines), reply_markup=back_kb())


@router.message(F.text == "🆘 المساعدة")
async def btn_help(m: Message):
    await m.answer(
        f"ℹ️ <b>المساعدة</b>\n\n"
        f"• اختر نوع المشكلة من القائمة\n"
        f"• أرسل رقم هاتفك بالصيغة الدولية\n"
        f"• سيتابع النظام طلبك تلقائيًا\n\n"
        f"⚠️ لا يقوم البوت بفك حظر واتساب.",
        reply_markup=back_kb(),
    )


@router.callback_query(F.data == "menu:main")
async def cb_main(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    upsert_user(cb.from_user)
    is_admin_user = is_admin(cb.from_user.id)
    emoji = random_emoji()
    text = (
        f"{divider()}\n"
        f"{emoji} <b>{BOT_NAME}</b> {emoji}\n"
        f"{divider()}\n\n"
        f"✨ اختر الخدمة 👇"
    )
    await edit_or_send(cb, text, main_menu_kb())
    await cb.answer()


@router.callback_query(F.data == "help")
async def cb_help(cb: CallbackQuery):
    text = (
        f"ℹ️ <b>المساعدة</b>\n\n"
        f"• اختر نوع المشكلة من القائمة\n"
        f"• أرسل رقم هاتفك بالصيغة الدولية\n"
        f"• سيتابع النظام طلبك تلقائيًا\n\n"
        f"⚠️ لا يقوم البوت بفك حظر واتساب."
    )
    await edit_or_send(cb, text, back_kb())
    await cb.answer()


@router.callback_query(F.data == "noop")
async def cb_noop(cb: CallbackQuery):
    await cb.answer()


# ============================
# REQUEST SYSTEM (User)
# ============================
@router.callback_query(F.data.startswith("rt:"))
async def cb_choose_type(cb: CallbackQuery, state: FSMContext):
    type_id = int(cb.data.split(":")[1])
    row = db_one("SELECT * FROM request_types WHERE id=? AND enabled=1", (type_id,))
    if not row:
        await cb.answer("النوع غير متوفر", show_alert=True)
        return
    await state.update_data(type_id=type_id, type_name=row["name"])
    await state.set_state(Flow.phone)
    await edit_or_send(
        cb,
        f"✓ النوع: <b>{row['name']}</b>\n\n"
        "أرسل رقم الهاتف بالصيغة الدولية، مثال:\n<code>+967XXXXXXXXX</code>",
        back_kb("menu:main"),
    )
    await cb.answer()


@router.message(Flow.phone)
async def on_phone(m: Message, state: FSMContext):
    raw = m.text or ""
    if not is_valid_phone(raw):
        await m.answer(
            "⚠ صيغة الرقم غير صحيحة.\n"
            "أرسل الرقم بصيغة دولية مثل:\n<code>+967XXXXXXXXX</code>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ إلغاء", callback_data="req:cancel")]
            ])
        )
        return
    phone = norm_phone(raw)
    data = await state.get_data()
    type_id = data.get("type_id")
    user = upsert_user(m.from_user)
    req_type = db_one("SELECT * FROM request_types WHERE id=?", (type_id,))
    if not req_type:
        await m.answer("⚠ النوع لم يعد متوفراً. ابدأ من جديد بـ /start")
        await state.clear()
        return

    cnt = db_one("SELECT COUNT(*) AS c FROM requests")["c"]
    code = f"MTR-{cnt + 1:06d}"
    correlation_id = str(uuid.uuid4())
    ts = now().isoformat()

    message = build_request_message(
        req_type, phone=phone, request_id=code,
        user_id=m.from_user.id, username=m.from_user.username or "",
        first_name=m.from_user.first_name or "",
    )

    db_exec(
        "INSERT INTO requests(code, user_id, phone, request_type_id, request_type_name, "
        "message, status, correlation_id, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (code, user["id"], phone, req_type["id"], req_type["name"],
         message, RStatus.NEW.value, correlation_id, ts, ts),
    )
    db_exec("UPDATE users SET requests_count = requests_count + 1 WHERE id=?", (user["id"],))
    log_event(m.from_user.id, "REQUEST_CREATED", code, f"type={req_type['name']}")

    await state.clear()

    await m.answer(
        f"⏳ <b>جاري معالجة الطلب...</b>\n\n"
        f"📋 رقم الطلب: <code>{code}</code>\n"
        f"{divider()}",
    )

    if get_setting("AUTO_SEND", "1") == "1":
        await try_send_request(code, notify_user_chat_id=m.chat.id, silent=False)

    await notify_admins(
        f"🆕 <b>طلب جديد</b>\n"
        f"الرقم: <code>{code}</code>\n"
        f"من: {m.from_user.full_name} (<code>{m.from_user.id}</code>)\n"
        f"النوع: {req_type['name']}\n"
        f"الهاتف: <code>{mask_phone(phone)}</code>"
    )


@router.callback_query(F.data == "req:cancel")
async def cb_req_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await edit_or_send(cb, "✕ تم إلغاء الطلب.", main_menu_kb())
    await cb.answer()


async def try_send_request(code: str, notify_user_chat_id: int | None = None,
                           silent: bool = False) -> None:
    row = db_one("SELECT * FROM requests WHERE code=?", (code,))
    if not row:
        return
    db_exec(
        "UPDATE requests SET status=?, updated_at=?, last_attempt=? WHERE id=?",
        (RStatus.PREPARING.value, now().isoformat(), now().isoformat(), row["id"]),
    )

    try:
        subject = f"طلب مراجعة - {row['code']}"
        body = (
            f"السلام عليكم،\n\n"
            f"أرغب في تقديم طلب مراجعة لحسابي.\n\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📋 رقم الطلب: {row['code']}\n"
            f"📱 رقم الهاتف: {row['phone']}\n"
            f"🏷️ نوع المشكلة: {row['request_type_name']}\n"
            f"📅 التاريخ: {row['created_at']}\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"📝 التفاصيل:\n{row['message']}\n\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"مع الشكر،\n"
            f"فريق المطري دعم"
        )
        result = send_support_email(subject, body)
        sent_count = result["sent"]
    except Exception as e:
        log.error(f"Email error: {e}")
        sent_count = 0

    if sent_count > 0:
        db_exec(
            "UPDATE requests SET status=?, external_message_id=?, "
            "correlation_id=?, updated_at=? WHERE id=?",
            (RStatus.WAITING_REPLY.value, f"email-{row['correlation_id'][:8]}",
             row["correlation_id"], now().isoformat(), row["id"]),
        )
        log_event(None, "REQUEST_SENT", code, f"emails={sent_count}/6")

        if notify_user_chat_id and not silent:
            await bot.send_message(
                notify_user_chat_id,
                f"{divider()}\n"
                f"✅ <b>تم إرسال طلبك بنجاح</b>\n"
                f"{divider()}\n\n"
                f"📋 رقم الطلب: <code>{code}</code>\n"
                f"📊 الحالة: {status_ar(RStatus.WAITING_REPLY.value)}\n\n"
                f"📧 تم إرسال طلبك إلى {sent_count} قناة دعم\n\n"
                f"{random_quote()}\n\n"
                f"{divider()}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📋 طلباتي", callback_data="my:0")],
                    [InlineKeyboardButton(text="‹ القائمة الرئيسية", callback_data="menu:main")],
                ]),
            )
    else:
        db_exec(
            "UPDATE requests SET status=?, updated_at=? WHERE id=?",
            (RStatus.FAILED.value, now().isoformat(), row["id"]),
        )
        log_event(None, "REQUEST_SEND_FAILED", code, "no emails sent")
        if notify_user_chat_id:
            await bot.send_message(
                notify_user_chat_id,
                f"⚠ <b>تعذر إرسال الطلب</b>\n\n"
                f"📋 رقم الطلب: <code>{code}</code>\n"
                f"يرجى التواصل مع الدعم لاحقاً.",
                reply_markup=back_kb(),
            )
            
# ============================
# MY REQUESTS
# ============================
@router.callback_query(F.data.startswith("my:"))
async def cb_my(cb: CallbackQuery):
    page = int(cb.data.split(":")[1])
    per_page = 5
    user = upsert_user(cb.from_user)
    total = db_one("SELECT COUNT(*) AS c FROM requests WHERE user_id=?", (user["id"],))["c"]
    rows = db_all(
        "SELECT code, request_type_name, status, created_at FROM requests "
        "WHERE user_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (user["id"], per_page, page * per_page),
    )
    if not rows:
        await edit_or_send(cb, "📭 لا توجد طلبات بعد.", back_kb())
        await cb.answer()
        return
    total_pages = max((total + per_page - 1) // per_page, 1)
    lines = [f"{divider()}\n🗂 <b>طلباتي</b> ({total})\n{divider()}\n"]
    for r in rows:
        lines.append(
            f"• <code>{r['code']}</code> — {r['request_type_name']}\n"
            f"  الحالة: {status_ar(r['status'])} — {fmt_dt(r['created_at'])}"
        )
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="‹", callback_data=f"my:{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
    if page + 1 < total_pages:
        nav.append(InlineKeyboardButton(text="›", callback_data=f"my:{page+1}"))
    kb = InlineKeyboardMarkup(inline_keyboard=[
        nav,
        [InlineKeyboardButton(text="‹ القائمة الرئيسية", callback_data="menu:main")],
    ])
    await edit_or_send(cb, "\n".join(lines), kb)
    await cb.answer()


# ============================
# ADMIN PANEL
# ============================
@router.message(Command("admin"))
async def cmd_admin(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        await m.answer("⛔ ليس لديك صلاحية.")
        return
    await state.clear()
    log_event(m.from_user.id, "ADMIN_LOGIN")
    await m.answer(
        f"{divider()}\n⚙️ <b>لوحة تحكم المطري</b>\n{divider()}",
        reply_markup=admin_reply_kb(),
    )
    await m.answer("اختر من الأزرار أو من القائمة 👇", reply_markup=admin_panel_kb())


@router.message(F.text == "⚙️ لوحة التحكم")
async def btn_admin_panel(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        await m.answer("⛔ ليس لديك صلاحية.")
        return
    await state.clear()
    await m.answer(
        f"{divider()}\n⚙️ <b>لوحة تحكم المطري</b>\n{divider()}",
        reply_markup=admin_reply_kb(),
    )
    await m.answer("اختر من الأزرار أو من القائمة 👇", reply_markup=admin_panel_kb())


@router.message(F.text == "🔙 رجوع للقائمة الرئيسية")
async def btn_back_main(m: Message, state: FSMContext):
    await state.clear()
    await cmd_start(m, state)


@router.callback_query(F.data == "adm:panel")
async def cb_adm_panel(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    await state.clear()
    await edit_or_send(
        cb,
        f"{divider()}\n⚙️ <b>لوحة تحكم المطري</b>\n{divider()}",
        admin_panel_kb(),
    )
    await cb.answer()


# ---------- Requests ----------
@router.callback_query(F.data.startswith("adm:reqs:"))
async def cb_adm_reqs(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    _, _, status, page_s = cb.data.split(":")
    page = int(page_s)
    per_page = 5
    total = db_one("SELECT COUNT(*) AS c FROM requests WHERE status=?", (status,))["c"]
    rows = db_all(
        "SELECT id, code, request_type_name, created_at FROM requests "
        "WHERE status=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (status, per_page, page * per_page),
    )
    if not rows:
        await edit_or_send(cb, f"لا توجد طلبات بحالة {status_ar(status)}.", back_kb("adm:panel"))
        await cb.answer()
        return
    total_pages = max((total + per_page - 1) // per_page, 1)
    lines = [f"{divider()}\n📋 <b>{status_ar(status)}</b> ({total})\n{divider()}\n"]
    for r in rows:
        lines.append(f"• <code>{r['code']}</code> — {r['request_type_name']} — {fmt_dt(r['created_at'])}")
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="‹", callback_data=f"adm:reqs:{status}:{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
    if page + 1 < total_pages:
        nav.append(InlineKeyboardButton(text="›", callback_data=f"adm:reqs:{status}:{page+1}"))
    rows_open = [[InlineKeyboardButton(text=f"فتح {r['code']}", callback_data=f"adm:open:{r['code']}")]
                 for r in rows]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        nav,
        *rows_open,
        [InlineKeyboardButton(text="🔎 تصفية بالحالة", callback_data="adm:filter"),
         InlineKeyboardButton(text="‹ رجوع", callback_data="adm:panel")],
    ])
    await edit_or_send(cb, "\n".join(lines), kb)
    await cb.answer()


@router.message(F.text == "📋 الطلبات")
async def btn_admin_requests(m: Message):
    if not is_admin(m.from_user.id):
        return
    await m.answer("اختر الحالة:", reply_markup=status_filter_kb())


@router.callback_query(F.data == "adm:filter")
async def cb_adm_filter(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    await edit_or_send(cb, "اختر الحالة:", status_filter_kb())
    await cb.answer()


@router.callback_query(F.data.startswith("adm:open:"))
async def cb_adm_open(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    code = cb.data.split(":", 2)[2]
    r = db_one(
        "SELECT r.*, u.telegram_id AS tg_id, u.first_name AS fname, u.username AS uname "
        "FROM requests r JOIN users u ON u.id=r.user_id WHERE r.code=?",
        (code,),
    )
    if not r:
        await cb.answer("غير موجود", show_alert=True)
        return
    text = (
        f"{divider()}\n<b>{r['code']}</b>\n{divider()}\n\n"
        f"المستخدم: {r['fname'] or '—'} (@{r['uname'] or '—'})\n"
        f"Telegram ID: <code>{r['tg_id']}</code>\n"
        f"الهاتف: <code>{r['phone']}</code>\n"
        f"النوع: {r['request_type_name']}\n"
        f"الحالة: {status_ar(r['status'])}\n"
        f"الإنشاء: {fmt_dt(r['created_at'])}\n"
        f"آخر تحديث: {fmt_dt(r['updated_at'])}\n"
        f"Correlation ID: <code>{r['correlation_id'] or '—'}</code>\n\n"
        f"<b>الرسالة:</b>\n{r['message']}\n\n"
        f"<b>الرد:</b>\n{r['reply_text'] or '—'}\n\n"
        f"<b>ملاحظة:</b>\n{r['admin_note'] or '—'}"
    )
    await edit_or_send(cb, text, request_admin_kb(r["id"]))
    await cb.answer()


@router.callback_query(F.data.startswith("adm:chst:"))
async def cb_adm_chst(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    req_id = int(cb.data.split(":")[2])
    rows = [[InlineKeyboardButton(text=status_ar(s.value), callback_data=f"adm:setst:{req_id}:{s.value}")]
            for s in RStatus]
    rows.append([InlineKeyboardButton(text="‹ رجوع", callback_data="adm:panel")])
    await edit_or_send(cb, "اختر الحالة الجديدة:", InlineKeyboardMarkup(inline_keyboard=rows))
    await cb.answer()


@router.callback_query(F.data.startswith("adm:setst:"))
async def cb_adm_setst(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    _, _, req_id, st = cb.data.split(":")
    req_id = int(req_id)
    r = db_one("SELECT * FROM requests WHERE id=?", (req_id,))
    if not r:
        await cb.answer("غير موجود", show_alert=True)
        return
    db_exec("UPDATE requests SET status=?, updated_at=? WHERE id=?",
            (st, now().isoformat(), req_id))
    log_event(cb.from_user.id, "STATUS_CHANGE", r["code"], f"{r['status']} -> {st}")
    await cb.answer("تم التحديث")

    u = db_one("SELECT telegram_id FROM users WHERE id=?", (r["user_id"],))
    if u and get_setting("AUTO_REPLY", "1") == "1":
        try:
            await bot.send_message(
                u["telegram_id"],
                f"{divider()}\n"
                f"📢 <b>تحديث على طلبك</b>\n"
                f"{divider()}\n\n"
                f"📋 رقم الطلب: <code>{r['code']}</code>\n"
                f"📊 الحالة الجديدة: {status_ar(st)}\n\n"
                f"{random_quote()}",
            )
        except TelegramAPIError:
            pass

    cb.data = f"adm:open:{r['code']}"
    await cb_adm_open(cb)


@router.callback_query(F.data.startswith("adm:resend:"))
async def cb_adm_resend(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    req_id = int(cb.data.split(":")[2])
    r = db_one("SELECT * FROM requests WHERE id=?", (req_id,))
    if not r:
        await cb.answer("غير موجود", show_alert=True)
        return
    await edit_or_send(
        cb,
        f"هل تريد إعادة إرسال الطلب <code>{r['code']}</code>؟",
        InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✓ تأكيد", callback_data=f"adm:resend_go:{req_id}")],
            [InlineKeyboardButton(text="✕ إلغاء", callback_data=f"adm:open:{r['code']}")],
        ]),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("adm:resend_go:"))
async def cb_adm_resend_go(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    req_id = int(cb.data.split(":")[2])
    r = db_one("SELECT * FROM requests WHERE id=?", (req_id,))
    if not r:
        await cb.answer("غير موجود", show_alert=True)
        return
    log_event(cb.from_user.id, "RESEND", r["code"])
    await cb.answer("⏳ جاري الإرسال...")
    await try_send_request(r["code"], notify_user_chat_id=None)
    cb.data = f"adm:open:{r['code']}"
    await cb_adm_open(cb)


@router.callback_query(F.data.startswith("adm:note:"))
async def cb_adm_note(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    req_id = int(cb.data.split(":")[2])
    await state.update_data(req_id=req_id)
    await state.set_state(AdminFlow.req_note)
    await edit_or_send(cb, "📝 أرسل الملاحظة:", back_kb(f"adm:open_id:{req_id}"))
    await cb.answer()


@router.callback_query(F.data.startswith("adm:open_id:"))
async def cb_adm_open_id(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    req_id = int(cb.data.split(":")[2])
    r = db_one("SELECT code FROM requests WHERE id=?", (req_id,))
    if not r:
        await cb.answer("غير موجود", show_alert=True)
        return
    cb.data = f"adm:open:{r['code']}"
    await cb_adm_open(cb)


@router.message(AdminFlow.req_note)
async def on_adm_note(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return
    data = await state.get_data()
    req_id = data.get("req_id")
    r = db_one("SELECT code FROM requests WHERE id=?", (req_id,))
    if not r:
        await m.answer("غير موجود")
        await state.clear()
        return
    db_exec("UPDATE requests SET admin_note=?, updated_at=? WHERE id=?",
            (m.text or "", now().isoformat(), req_id))
    log_event(m.from_user.id, "ADD_NOTE", r["code"])
    await m.answer("✓ تمت إضافة الملاحظة.", reply_markup=admin_panel_kb())
    await state.clear()


@router.callback_query(F.data.startswith("adm:msg:"))
async def cb_adm_msg(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    req_id = int(cb.data.split(":")[2])
    await state.update_data(req_id=req_id)
    await state.set_state(AdminFlow.req_msg)
    await edit_or_send(cb, "✉ أرسل نص الرسالة للمستخدم:", back_kb(f"adm:open_id:{req_id}"))
    await cb.answer()


@router.message(AdminFlow.req_msg)
async def on_adm_msg(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return
    data = await state.get_data()
    req_id = data.get("req_id")
    r = db_one(
        "SELECT r.code, u.telegram_id AS tg_id FROM requests r "
        "JOIN users u ON u.id=r.user_id WHERE r.id=?",
        (req_id,),
    )
    if not r:
        await m.answer("غير موجود")
        await state.clear()
        return
    try:
        await bot.send_message(
            r["tg_id"],
            f"✉ <b>رسالة من الدعم</b>\n\n"
            f"بخصوص الطلب: <code>{r['code']}</code>\n\n{m.text}",
        )
        log_event(m.from_user.id, "SEND_USER_MSG", r["code"], "ok")
        await m.answer("✓ تم الإرسال.", reply_markup=admin_panel_kb())
    except TelegramAPIError:
        await m.answer("⚠ فشل الإرسال.")
    await state.clear()


# ---------- محاكاة رد وارد ----------
@router.callback_query(F.data.startswith("adm:simreply:"))
async def cb_adm_simreply(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    req_id = int(cb.data.split(":")[2])
    await state.update_data(req_id=req_id)
    await state.set_state(AdminFlow.sim_reply)
    await edit_or_send(
        cb,
        "📨 اكتب نص الرد الوارد:",
        back_kb(f"adm:open_id:{req_id}"),
    )
    await cb.answer()


@router.message(AdminFlow.sim_reply)
async def on_sim_reply(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return
    data = await state.get_data()
    req_id = data.get("req_id")
    r = db_one("SELECT * FROM requests WHERE id=?", (req_id,))
    if not r:
        await m.answer("غير موجود")
        await state.clear()
        return
    await handle_incoming_reply({
        "correlation_id": r["correlation_id"],
        "external_message_id": r["external_message_id"],
        "external_thread_id": r["external_thread_id"],
        "text": m.text or "",
    })
    await m.answer("✓ تمت معالجة الرد.", reply_markup=admin_panel_kb())
    await state.clear()


# ============================
# 🎨 تخصيص الأزرار
# ============================
@router.message(F.text == "🎨 تخصيص الأزرار")
async def btn_customize_buttons(m: Message):
    if not is_admin(m.from_user.id):
        return
    await show_buttons_editor(m)


@router.callback_query(F.data == "adm:buttons_config")
async def cb_buttons_config(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    await show_buttons_editor(cb.message)


async def show_buttons_editor(target: Message):
    buttons = db_all("SELECT id, button_key, label, position, enabled FROM buttons_config ORDER BY position")
    lines = [f"{divider()}\n🎨 <b>تخصيص الأزرار</b>\n{divider()}\n\n"]
    kb_rows = []
    for b in buttons:
        st = "✅" if b["enabled"] else "⛔"
        lines.append(f"{st} <b>{b['label']}</b>\n   ترتيب: {b['position']}\n")
        kb_rows.append([
            InlineKeyboardButton(text=f"✏️ {b['label']}", callback_data=f"adm:btn_edit:{b['id']}"),
            InlineKeyboardButton(text="✅/⛔", callback_data=f"adm:btn_toggle:{b['id']}"),
            InlineKeyboardButton(text="⬆️", callback_data=f"adm:btn_up:{b['id']}"),
            InlineKeyboardButton(text="⬇️", callback_data=f"adm:btn_down:{b['id']}"),
        ])
    kb_rows.append([InlineKeyboardButton(text="‹ رجوع", callback_data="adm:panel")])
    await target.answer(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
    )


@router.callback_query(F.data.startswith("adm:btn_edit:"))
async def cb_btn_edit(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    btn_id = int(cb.data.split(":")[2])
    await state.update_data(btn_id=btn_id)
    await state.set_state(AdminFlow.edit_button_label)
    await edit_or_send(cb, "✏️ أرسل النص الجديد للزر:", back_kb("adm:buttons_config"))
    await cb.answer()


@router.message(AdminFlow.edit_button_label)
async def on_edit_button_label(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return
    data = await state.get_data()
    btn_id = data.get("btn_id")
    new_label = (m.text or "").strip()
    if not new_label:
        await m.answer("نص فارغ")
        return
    db_exec("UPDATE buttons_config SET label=? WHERE id=?", (new_label, btn_id))
    log_event(m.from_user.id, "EDIT_BUTTON", str(btn_id))
    await m.answer("✅ تم تحديث الزر.", reply_markup=admin_panel_kb())
    await state.clear()


@router.callback_query(F.data.startswith("adm:btn_toggle:"))
async def cb_btn_toggle(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    btn_id = int(cb.data.split(":")[2])
    db_exec("UPDATE buttons_config SET enabled = 1 - enabled WHERE id=?", (btn_id,))
    await cb.answer("تم التبديل")
    await show_buttons_editor(cb.message)


@router.callback_query(F.data.startswith("adm:btn_up:"))
async def cb_btn_up(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    btn_id = int(cb.data.split(":")[2])
    r = db_one("SELECT position FROM buttons_config WHERE id=?", (btn_id,))
    if r:
        db_exec("UPDATE buttons_config SET position=? WHERE id=?", (r["position"] - 5, btn_id))
    await cb.answer("⬆️")
    await show_buttons_editor(cb.message)


@router.callback_query(F.data.startswith("adm:btn_down:"))
async def cb_btn_down(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    btn_id = int(cb.data.split(":")[2])
    r = db_one("SELECT position FROM buttons_config WHERE id=?", (btn_id,))
    if r:
        db_exec("UPDATE buttons_config SET position=? WHERE id=?", (r["position"] + 5, btn_id))
    await cb.answer("⬇️")
    await show_buttons_editor(cb.message)


# ============================
# أنواع المشاكل + القوالب (مختصر)
# ============================
@router.message(F.text == "📝 القوالب")
async def btn_templates(m: Message):
    if not is_admin(m.from_user.id):
        return
    rows = db_all("SELECT id, name, template FROM request_types ORDER BY id")
    kb_rows = [[InlineKeyboardButton(text=f"📝 {r['name']}", callback_data=f"adm:tpl:{r['id']}")]
               for r in rows]
    kb_rows.append([InlineKeyboardButton(text="‹ رجوع", callback_data="adm:panel")])
    await m.answer("📝 <b>القوالب</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))


@router.callback_query(F.data.startswith("adm:tpl:"))
async def cb_adm_tpl(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    tid = int(cb.data.split(":")[2])
    r = db_one("SELECT * FROM request_types WHERE id=?", (tid,))
    t = db_one("SELECT body FROM message_templates WHERE type_id=? ORDER BY id DESC LIMIT 1", (tid,))
    body = t["body"] if t else r["template"]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✎ تعديل القالب", callback_data=f"adm:tpl_edit:{tid}")],
        [InlineKeyboardButton(text="‹ رجوع", callback_data="adm:templates")],
    ])
    await edit_or_send(cb, f"<b>{r['name']}</b>\n\n<pre>{body}</pre>", kb)
    await cb.answer()


@router.callback_query(F.data == "adm:templates")
async def cb_adm_templates(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    rows = db_all("SELECT id, name FROM request_types ORDER BY id")
    kb_rows = [[InlineKeyboardButton(text=f"📝 {r['name']}", callback_data=f"adm:tpl:{r['id']}")]
               for r in rows]
    kb_rows.append([InlineKeyboardButton(text="‹ رجوع", callback_data="adm:panel")])
    await edit_or_send(cb, "📝 <b>القوالب</b>", InlineKeyboardMarkup(inline_keyboard=kb_rows))
    await cb.answer()


@router.callback_query(F.data.startswith("adm:tpl_edit:"))
async def cb_adm_tpl_edit(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    tid = int(cb.data.split(":")[2])
    await state.update_data(tid=tid)
    await state.set_state(AdminFlow.edit_template)
    await edit_or_send(cb, "✍ أرسل القالب الجديد:", back_kb("adm:templates"))
    await cb.answer()


@router.message(AdminFlow.edit_template)
async def on_edit_template(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return
    data = await state.get_data()
    tid = data.get("tid")
    body = (m.text or "").strip()
    if len(body) < 5:
        await m.answer("⚠ قصير")
        return
    db_exec("UPDATE request_types SET template=? WHERE id=?", (body, tid))
    db_exec("UPDATE message_templates SET body=?, updated_at=? WHERE type_id=?",
            (body, now().isoformat(), tid))
    log_event(m.from_user.id, "EDIT_TEMPLATE", str(tid))
    await m.answer("✅ تم التحديث.", reply_markup=admin_panel_kb())
    await state.clear()


# ============================
# أنواع المشاكل
# ============================
@router.callback_query(F.data == "adm:types")
async def cb_adm_types(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    rows = db_all("SELECT id, name, description, enabled FROM request_types ORDER BY id")
    lines = [f"{divider()}\n🗂 <b>أنواع المشاكل</b>\n{divider()}\n"]
    kb_rows = []
    for r in rows:
        st = "✅" if r["enabled"] else "⛔"
        lines.append(f"{st} [{r['id']}] {r['name']}")
        kb_rows.append([
            InlineKeyboardButton(text=f"✎ {r['name']}", callback_data=f"adm:tedit:{r['id']}"),
            InlineKeyboardButton(text="✅/⛔", callback_data=f"adm:ttoggle:{r['id']}"),
            InlineKeyboardButton(text="🗑", callback_data=f"adm:tdel:{r['id']}"),
        ])
    kb_rows.append([InlineKeyboardButton(text="➕ إضافة نوع", callback_data="adm:tadd")])
    kb_rows.append([InlineKeyboardButton(text="‹ رجوع", callback_data="adm:panel")])
    await edit_or_send(cb, "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=kb_rows))
    await cb.answer()


@router.callback_query(F.data.startswith("adm:ttoggle:"))
async def cb_adm_ttoggle(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    tid = int(cb.data.split(":")[2])
    db_exec("UPDATE request_types SET enabled = 1 - enabled WHERE id=?", (tid,))
    await cb.answer("تم التبديل")
    cb.data = "adm:types"
    await cb_adm_types(cb)


@router.callback_query(F.data.startswith("adm:tdel:"))
async def cb_adm_tdel(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    tid = int(cb.data.split(":")[2])
    db_exec("DELETE FROM request_types WHERE id=?", (tid,))
    await cb.answer("تم الحذف")
    cb.data = "adm:types"
    await cb_adm_types(cb)


@router.callback_query(F.data == "adm:tadd")
async def cb_adm_tadd(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    await state.set_state(AdminFlow.add_type_name)
    await edit_or_send(cb, "➕ أرسل اسم النوع:", back_kb("adm:types"))
    await cb.answer()


@router.message(AdminFlow.add_type_name)
async def on_add_type_name(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return
    name = (m.text or "").strip()
    if len(name) < 2:
        await m.answer("⚠ اسم قصير")
        return
    await state.update_data(tname=name)
    await state.set_state(AdminFlow.add_type_desc)
    await m.answer("✍ أرسل وصفًا مختصرًا:")


@router.message(AdminFlow.add_type_desc)
async def on_add_type_desc(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return
    await state.update_data(tdesc=(m.text or "").strip())
    await state.set_state(AdminFlow.add_type_template)
    await m.answer(
        "✍ أرسل قالب الرسالة.\n\n"
        "المتغيرات: {phone} {request_id} {user_id} {username} {first_name} {request_type} {created_at}"
    )


@router.message(AdminFlow.add_type_template)
async def on_add_type_template(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return
    tpl = (m.text or "").strip()
    if len(tpl) < 5:
        await m.answer("⚠ القالب قصير")
        return
    data = await state.get_data()
    ts = now().isoformat()
    db_exec(
        "INSERT INTO request_types(name, description, template, enabled, created_at) VALUES (?,?,?,1,?)",
        (data["tname"], data.get("tdesc", ""), tpl, ts),
    )
    tid = db_one("SELECT id FROM request_types WHERE name=?", (data["tname"],))["id"]
    db_exec("INSERT INTO message_templates(type_id, body, updated_at) VALUES (?,?,?)", (tid, tpl, ts))
    await m.answer("✅ تمت الإضافة.", reply_markup=admin_panel_kb())
    await state.clear()


@router.callback_query(F.data.startswith("adm:tedit:"))
async def cb_adm_tedit(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    tid = int(cb.data.split(":")[2])
    await state.update_data(tid=tid)
    await state.set_state(AdminFlow.edit_type_name)
    r = db_one("SELECT name FROM request_types WHERE id=?", (tid,))
    await edit_or_send(cb, f"✎ الاسم الحالي: <b>{r['name'] if r else '?'}</b>\n\nأرسل الاسم الجديد:",
                       back_kb("adm:types"))
    await cb.answer()


@router.message(AdminFlow.edit_type_name)
async def on_edit_type_name(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return
    data = await state.get_data()
    tid = data.get("tid")
    new_name = (m.text or "").strip()
    if len(new_name) < 2:
        await m.answer("⚠ اسم قصير")
        return
    db_exec("UPDATE request_types SET name=? WHERE id=?", (new_name, tid))
    await m.answer("✅ تم التحديث.", reply_markup=admin_panel_kb())
    await state.clear()


# ============================
# المستخدمون
# ============================
@router.message(F.text == "👤 المستخدمون")
async def btn_users(m: Message):
    if not is_admin(m.from_user.id):
        return
    await show_users(m)


@router.callback_query(F.data == "adm:users")
async def cb_adm_users(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    await show_users(cb.message)
    await cb.answer()


async def show_users(target: Message):
    total = db_one("SELECT COUNT(*) AS c FROM users")["c"]
    rows = db_all(
        "SELECT telegram_id, username, first_name, requests_count, last_activity "
        "FROM users ORDER BY last_activity DESC LIMIT 10"
    )
    lines = [f"{divider()}\n👤 <b>المستخدمون</b> ({total})\n{divider()}\n"]
    for u in rows:
        lines.append(
            f"• {u['first_name'] or '—'} @{u['username'] or '—'} <code>{u['telegram_id']}</code>\n"
            f"  الطلبات: {u['requests_count']}"
        )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔎 بحث", callback_data="adm:usearch")],
        [InlineKeyboardButton(text="‹ رجوع", callback_data="adm:panel")],
    ])
    await target.answer("\n".join(lines), reply_markup=kb)


@router.callback_query(F.data == "adm:usearch")
async def cb_adm_usearch(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    await state.set_state(AdminFlow.search_user)
    await edit_or_send(cb, "🔎 أرسل: ID / Username / كود MTR / رقم هاتف", back_kb("adm:users"))
    await cb.answer()


@router.message(AdminFlow.search_user)
async def on_search_user(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return
    q = (m.text or "").strip()
    results = []
    if CODE_RE.match(q.upper()):
        r = db_one(
            "SELECT r.code, r.phone, r.status, r.request_type_name, u.telegram_id, u.first_name "
            "FROM requests r JOIN users u ON u.id=r.user_id WHERE r.code=?",
            (q.upper(),),
        )
        if r:
            results.append(f"📋 {r['code']} | {r['request_type_name']} | {status_ar(r['status'])}\n"
                           f"👤 {r['first_name'] or '—'} <code>{r['telegram_id']}</code>\n"
                           f"📱 {r['phone']}")
    else:
        like = f"%{q.lstrip('@')}%"
        rows = db_all(
            "SELECT telegram_id, username, first_name, requests_count FROM users "
            "WHERE CAST(telegram_id AS TEXT)=? OR username LIKE ? OR first_name LIKE ? LIMIT 15",
            (q, like, like),
        )
        for u in rows:
            results.append(f"• {u['first_name'] or '—'} @{u['username'] or '—'} <code>{u['telegram_id']}</code>")
    text = "🔎 <b>النتائج</b>\n\n" + ("\n\n".join(results) if results else "لا نتائج.")
    await m.answer(text, reply_markup=back_kb("adm:users"))
    await state.clear()


# ============================
# الإحصائيات
# ============================
@router.message(F.text == "📊 الإحصائيات")
async def btn_stats(m: Message):
    if not is_admin(m.from_user.id):
        return
    await m.answer(build_stats_text(), reply_markup=admin_panel_kb())


@router.callback_query(F.data == "adm:stats")
async def cb_adm_stats(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    await edit_or_send(cb, build_stats_text(), back_kb("adm:panel"))
    await cb.answer()


def build_stats_text() -> str:
    total_users = db_one("SELECT COUNT(*) AS c FROM users")["c"]
    total_reqs = db_one("SELECT COUNT(*) AS c FROM requests")["c"]
    counts = {}
    for s in RStatus:
        counts[s.value] = db_one("SELECT COUNT(*) AS c FROM requests WHERE status=?", (s.value,))["c"]

    lines = [
        f"{divider()}", "📊 <b>الإحصائيات</b>", f"{divider()}", "",
        f"👥 المستخدمون: <b>{total_users}</b>",
        f"📋 إجمالي الطلبات: <b>{total_reqs}</b>", "",
        "— حسب الحالة —",
    ]
    for s in RStatus:
        lines.append(f"• {status_ar(s.value)}: {counts[s.value]}")

    if total_reqs:
        lines.append("")
        lines.append("— توزيع —")
        for s in RStatus:
            c = counts[s.value]
            bar = "█" * int(round((c / total_reqs) * 20))
            lines.append(f"{status_ar(s.value):<20} | {bar} {c}")
    return "\n".join(lines)


# ============================
# السجل
# ============================
@router.callback_query(F.data == "adm:logs")
async def cb_adm_logs(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    rows = db_all(
        "SELECT actor_id, action, target, details, created_at FROM logs ORDER BY created_at DESC LIMIT 30"
    )
    lines = [f"{divider()}\n📜 <b>آخر العمليات</b>\n{divider()}\n"]
    for r in rows:
        lines.append(
            f"• {fmt_dt(r['created_at'])}\n"
            f"  {r['action']} | actor=<code>{r['actor_id']}</code> | target={r['target'] or '—'}"
        )
    if not rows:
        lines.append("لا يوجد سجل.")
    await edit_or_send(cb, "\n".join(lines), back_kb("adm:panel"))
    await cb.answer()


# ============================
# الإعدادات
# ============================
@router.message(F.text == "⚙️ الإعدادات")
async def btn_settings(m: Message):
    if not is_admin(m.from_user.id):
        return
    await show_settings(m)


@router.callback_query(F.data == "adm:settings")
async def cb_adm_settings(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    await show_settings(cb.message)
    await cb.answer()


async def show_settings(target: Message):
    keys = ["AUTO_SEND", "AUTO_REPLY", "MAINTENANCE", "LOGGING", "RETRY_ENABLED", "show_admin_button"]
    labels = {
        "AUTO_SEND": "الإرسال التلقائي",
        "AUTO_REPLY": "الرد التلقائي",
        "MAINTENANCE": "وضع الصيانة",
        "LOGGING": "تسجيل العمليات",
        "RETRY_ENABLED": "إعادة المحاولة",
        "show_admin_button": "زر لوحة التحكم في القائمة السفلية",
    }
    kb_rows = []
    lines = [f"{divider()}\n⚙ <b>الإعدادات</b>\n{divider()}\n"]
    for k in keys:
        v = get_setting(k, "0")
        lines.append(f"• {labels[k]}: {'✅' if v == '1' else '⛔'}")
        kb_rows.append([InlineKeyboardButton(text=f"تبديل {labels[k]}", callback_data=f"adm:set:{k}")])

    kb_rows.append([InlineKeyboardButton(text="✏️ تعديل رسالة الترحيب", callback_data="adm:edit_welcome")])
    kb_rows.append([InlineKeyboardButton(text="‹ رجوع", callback_data="adm:panel")])
    await target.answer("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))


@router.callback_query(F.data.startswith("adm:set:"))
async def cb_adm_set(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    k = cb.data.split(":")[2]
    v = get_setting(k, "0")
    set_setting(k, "0" if v == "1" else "1")
    await cb.answer("تم التبديل")
    cb.data = "adm:settings"
    await cb_adm_settings(cb)


@router.callback_query(F.data == "adm:edit_welcome")
async def cb_edit_welcome(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    await state.set_state(AdminFlow.edit_welcome)
    current = get_setting("welcome_message", "")
    await edit_or_send(cb, f"✏️ رسالة الترحيب الحالية:\n\n<code>{current}</code>\n\nأرسل النص الجديد:",
                       back_kb("adm:settings"))
    await cb.answer()


@router.message(AdminFlow.edit_welcome)
async def on_edit_welcome(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return
    new_text = (m.text or "").strip()
    if not new_text:
        await m.answer("فارغ")
        return
    set_setting("welcome_message", new_text)
    await m.answer("✅ تم التحديث.", reply_markup=admin_panel_kb())
    await state.clear()


# ============================
# Backup / Export
# ============================
@router.callback_query(F.data == "adm:backup")
async def cb_adm_backup(cb: CallbackQuery):
    if not is_super(cb.from_user.id):
        await cb.answer("⛔ للسوبر أدمن فقط", show_alert=True)
        return
    try:
        ts = now().strftime("%Y%m%d_%H%M%S")
        dst = Path(BACKUP_DIR) / f"matary_backup_{ts}.db"
        with closing(db_connect()) as conn:
            conn.execute("PRAGMA wal_checkpoint(FULL)")
            conn.commit()
        shutil.copy2(DATABASE_PATH, dst)
        await cb.message.answer_document(FSInputFile(str(dst)), caption=f"🗄 Backup {ts}")
        await cb.answer("تم")
    except Exception as e:
        log.exception("backup failed: %s", e)
        await cb.answer("فشل النسخ", show_alert=True)


@router.callback_query(F.data == "adm:export_csv")
async def cb_adm_export_csv(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    try:
        ts = now().strftime("%Y%m%d_%H%M%S")
        dst = Path(BACKUP_DIR) / f"requests_{ts}.csv"
        rows = db_all("SELECT code, phone, request_type_name, status, created_at FROM requests")
        with dst.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["code", "phone", "type", "status", "created_at"])
            for r in rows:
                w.writerow([r["code"], r["phone"], r["request_type_name"], r["status"], r["created_at"]])
        await cb.message.answer_document(FSInputFile(str(dst)), caption=f"📤 CSV {ts}")
        await cb.answer("تم")
    except Exception as e:
        log.exception("export failed: %s", e)
        await cb.answer("فشل", show_alert=True)
        
# ============================
# BACKGROUND WORKER
# ============================
async def background_worker() -> None:
    """يتابع الطلبات التي بانتظار الرد"""
    while True:
        try:
            if get_setting("RETRY_ENABLED", "1") == "1":
                max_retries = int(get_setting("MAX_RETRIES", "3") or 3)
                rows = db_all(
                    "SELECT * FROM requests WHERE status=? AND retry_count < ? LIMIT 20",
                    (RStatus.WAITING_REPLY.value, max_retries),
                )
                for r in rows:
                    res = await CONNECTOR.check_status(r)
                    if not res.get("ok"):
                        continue
                    db_exec(
                        "UPDATE requests SET last_attempt=?, next_attempt=?, updated_at=? WHERE id=?",
                        (now().isoformat(),
                         (now() + timedelta(minutes=5)).isoformat(),
                         now().isoformat(),
                         r["id"]),
                    )
        except Exception as e:
            log.exception("worker error: %s", e)
        await asyncio.sleep(60)


# ============================
# ERROR HANDLER
# ============================
@dp.errors()
async def on_error(event: Any):
    log.exception("Unhandled error: %s", event)
    try:
        if isinstance(event.update, Message):
            await event.update.answer("⚠ حدث خطأ غير متوقع.")
        elif isinstance(event.update, CallbackQuery):
            await event.update.answer("⚠ حدث خطأ.", show_alert=True)
    except Exception:
        pass


# ============================
# MIDDLEWARES
# ============================
@dp.message.middleware()
async def mw_maintenance(handler, event: Message, data):
    if isinstance(event, Message) and event.from_user and not is_admin(event.from_user.id):
        if get_setting("MAINTENANCE", "0") == "1":
            if not (event.text or "").startswith("/start"):
                await event.answer("🛠 البوت في وضع الصيانة حالياً.")
                return
    return await handler(event, data)


@dp.callback_query.middleware()
async def mw_rate(handler, event: CallbackQuery, data):
    if event.from_user and throttled(event.from_user.id):
        await event.answer("⏳ الرجاء التمهل قليلاً")
        return
    return await handler(event, data)


# ============================
# MAIN
# ============================
async def on_startup() -> None:
    db_init()

    # ✅ تسجيل الأوامر الظاهرة في تيليجرام
    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="🏠 بدء البوت"),
            BotCommand(command="id", description="🆔 عرض آيديك"),
            BotCommand(command="admin", description="⚙️ لوحة التحكم"),
            BotCommand(command="cancel", description="✕ إلغاء"),
        ])
        log.info("✅ تم تسجيل الأوامر")
    except Exception as e:
        log.warning(f"⚠️ فشل تسجيل الأوامر: {e}")

    me = await bot.get_me()
    log.info("Bot started as @%s", me.username)

    for a in (ADMIN_IDS | SUPER_ADMIN_IDS):
        try:
            await bot.send_message(a, f"✅ تم تشغيل <b>{BOT_NAME}</b>.")
        except TelegramAPIError:
            pass

    asyncio.create_task(background_worker())


async def main() -> None:
    await on_startup()
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


# ============================
# HTTP Health Server (لـ Render)
# ============================
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is running")

    def log_message(self, format, *args):
        pass


def start_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"✅ Health server on port {port}")
    server.serve_forever()


threading.Thread(target=start_health_server, daemon=True).start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot stopped.")
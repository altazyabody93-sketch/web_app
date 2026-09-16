# ============================
# IMPORTS
# ============================
from __future__ import annotations

import asyncio
import csv
import json
import logging
import os
import re
import shutil
import sqlite3
import time
import uuid
from contextlib import closing
from datetime import datetime, timedelta
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
    FSInputFile,
)


# ============================
# CONFIG  ← عدّل هذا القسم فقط
# ============================
BOT_TOKEN = "8247238031:AAEaziSWKRn0diQeJnZ_aVMYUz4M_iWjXG0"                    # ← ضع توكن البوت هنا
ADMIN_IDS = {7325566792}                   # ← ضع Telegram ID الخاص بك
SUPER_ADMIN_IDS = {7602226699}             # ← ضع نفس ID (أو أعلى صلاحية)

# إعدادات ثابتة (لا تحتاج تعديل)
DATABASE_PATH = os.environ.get("DATABASE_PATH", "matary.db")
LOG_LEVEL = "INFO"
BOT_NAME = "المطري دعم"
RATE_LIMIT_SECONDS = 1
BACKUP_DIR = "backups"

# تحقق
if not BOT_TOKEN or ":" not in BOT_TOKEN:
    raise SystemExit("❌ ضع BOT_TOKEN داخل main.py في قسم CONFIG")
if not ADMIN_IDS or 0 in ADMIN_IDS:
    raise SystemExit("❌ ضع Telegram ID في ADMIN_IDS داخل main.py")

Path(BACKUP_DIR).mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logging.getLogger("aiogram").setLevel(logging.WARNING)
log = logging.getLogger("matary")


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
}

DEFAULT_RESPONSE_KEYWORDS = {
    "resolved_keywords": ["resolved", "unbanned", "تم الحل", "تمت المراجعة"],
    "pending_keywords": ["pending", "review", "قيد المراجعة", "بانتظار"],
    "rejected_keywords": ["rejected", "denied", "مرفوض", "رفض"],
}


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
        conn.commit()


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
# HELPERS
# ============================
_last_call: dict[int, float] = {}


def throttled(user_id: int) -> bool:
    t = time.time()
    last = _last_call.get(user_id, 0)
    if t - last < RATE_LIMIT_SECONDS:
        return True
    _last_call[user_id] = t
    return False


def render_template(text: str, **vars: Any) -> str:
    safe = {k: ("" if v is None else str(v)) for k, v in vars.items()}
    try:
        return text.format(**safe)
    except Exception:
        out = text
        for k, v in safe.items():
            out = out.replace("{" + k + "}", v)
        return out


def status_ar(s: str) -> str:
    try:
        return STATUS_AR[RStatus(s)]
    except Exception:
        return s


def get_admin_role(tg_id: int) -> Optional[str]:
    if tg_id in SUPER_ADMIN_IDS:
        return "SUPER_ADMIN"
    if tg_id in ADMIN_IDS:
        return "ADMIN"
    row = db_one("SELECT role FROM admins WHERE telegram_id=?", (tg_id,))
    return row["role"] if row else None


def is_admin(tg_id: int) -> bool:
    return get_admin_role(tg_id) is not None


def is_super(tg_id: int) -> bool:
    return get_admin_role(tg_id) == "SUPER_ADMIN"


# ============================
# TEMPLATE SYSTEM
# ============================
def build_request_message(req_type: sqlite3.Row, *, phone: str, request_id: str,
                          user_id: int, username: str, first_name: str) -> str:
    body = req_type["template"]
    tmpl = db_one("SELECT body FROM message_templates WHERE type_id=? ORDER BY id DESC LIMIT 1",
                  (req_type["id"],))
    if tmpl:
        body = tmpl["body"]
    return render_template(
        body,
        phone=phone,
        request_id=request_id,
        user_id=user_id,
        username=username or "",
        first_name=first_name or "",
        request_type=req_type["name"],
        created_at=now().strftime("%Y-%m-%d %H:%M"),
    )


# ============================
# CONNECTOR (Official Adapter)
# ============================
class OfficialSupportConnector:
    """
    Adapter جاهز للربط بقناة دعم رسمية ومصرّح بها.

    - في الوضع الافتراضي (not_configured): لا يفعل شيئًا ويعيد NOT_CONFIGURED.
    - يمكن ربطه بـ WhatsApp Business Cloud API الرسمي من Meta، أو أي API رسمي آخر.
    - ⚠️ لا يستخدم أي طريقة غير رسمية، ولا أي WhatsApp Web automation.
    """

    MODE_NOT_CONFIGURED = "not_configured"
    MODE_MANUAL = "manual"
    MODE_API = "api"

    def __init__(self) -> None:
        self.mode = get_setting("CONNECTOR_MODE", self.MODE_NOT_CONFIGURED)

    def refresh(self) -> None:
        self.mode = get_setting("CONNECTOR_MODE", self.MODE_NOT_CONFIGURED)

    async def send_request(self, request_row: sqlite3.Row, message: str) -> dict:
        self.refresh()
        correlation_id = request_row["correlation_id"] or str(uuid.uuid4())

        if self.mode == self.MODE_NOT_CONFIGURED:
            return {
                "ok": False,
                "status": "NOT_CONFIGURED",
                "external_message_id": None,
                "external_thread_id": None,
                "correlation_id": correlation_id,
                "error": "قناة الدعم غير مهيأة",
            }

        if self.mode == self.MODE_MANUAL:
            return {
                "ok": True,
                "status": "SENT",
                "external_message_id": f"manual-{correlation_id[:8]}",
                "external_thread_id": None,
                "correlation_id": correlation_id,
                "error": None,
            }

        if self.mode == self.MODE_API:
            # TODO: اربط هنا بـ API الرسمي
            return {
                "ok": False,
                "status": "NOT_CONFIGURED",
                "external_message_id": None,
                "external_thread_id": None,
                "correlation_id": correlation_id,
                "error": "API الرسمي غير مربوط بعد",
            }

        return {
            "ok": False,
            "status": "NOT_CONFIGURED",
            "external_message_id": None,
            "external_thread_id": None,
            "correlation_id": correlation_id,
            "error": f"وضع غير معروف: {self.mode}",
        }

    async def check_status(self, request_row: sqlite3.Row) -> dict:
        self.refresh()
        if self.mode == self.MODE_NOT_CONFIGURED:
            return {"ok": False, "status": "NOT_CONFIGURED"}
        return {"ok": True, "status": "WAITING_REPLY"}

    async def process_incoming_response(self, payload: dict) -> dict:
        corr = payload.get("correlation_id")
        ext_msg = payload.get("external_message_id")
        ext_thread = payload.get("external_thread_id")
        text = payload.get("text") or ""

        row = None
        if corr:
            row = db_one("SELECT * FROM requests WHERE correlation_id=?", (corr,))
        if not row and ext_msg:
            row = db_one("SELECT * FROM requests WHERE external_message_id=?", (ext_msg,))
        if not row and ext_thread:
            row = db_one("SELECT * FROM requests WHERE external_thread_id=?", (ext_thread,))

        if not row:
            return {"ok": False, "request_code": None, "reply_text": None,
                    "error": "لا يوجد طلب مطابق"}

        db_exec(
            "UPDATE requests SET reply_text=?, status=?, updated_at=? WHERE id=?",
            (text, RStatus.REPLY_RECEIVED.value, now().isoformat(), row["id"]),
        )
        db_exec(
            "INSERT INTO request_events(request_id, event, details, created_at) VALUES (?,?,?,?)",
            (row["id"], "REPLY_RECEIVED", text[:500], now().isoformat()),
        )
        return {"ok": True, "request_code": row["code"], "reply_text": text, "error": None}


CONNECTOR = OfficialSupportConnector()


# ============================
# RESPONSE PROCESSOR
# ============================
def analyze_reply(text: str) -> Optional[str]:
    if not text:
        return None
    raw = get_setting("response_keywords", "{}")
    try:
        kws = json.loads(raw)
    except Exception:
        kws = DEFAULT_RESPONSE_KEYWORDS

    low = text.lower()
    if any(k.lower() in low for k in kws.get("resolved_keywords", [])):
        return RStatus.RESOLVED.value
    if any(k.lower() in low for k in kws.get("rejected_keywords", [])):
        return RStatus.CLOSED.value
    if any(k.lower() in low for k in kws.get("pending_keywords", [])):
        return RStatus.WAITING_REPLY.value
    return None


async def handle_incoming_reply(payload: dict) -> None:
    res = await CONNECTOR.process_incoming_response(payload)
    if not res["ok"]:
        log.warning("incoming reply not matched: %s", res.get("error"))
        return
    code = res["request_code"]
    text = res["reply_text"] or ""

    suggested = analyze_reply(text)
    if suggested:
        db_exec("UPDATE requests SET status=?, updated_at=? WHERE code=?",
                (suggested, now().isoformat(), code))
        log_event(None, "STATUS_CHANGE", code, f"REPLY -> {suggested}")

    row = db_one(
        "SELECT r.*, u.telegram_id AS tg_id FROM requests r JOIN users u ON u.id=r.user_id WHERE r.code=?",
        (code,),
    )
    if row and get_setting("AUTO_REPLY", "1") == "1":
        user_msg = (
            f"{divider()}\n<b>تحديث طلبك</b>\n{divider()}\n\n"
            f"رقم الطلب: <code>{row['code']}</code>\n"
            f"الرقم: <code>{mask_phone(row['phone'])}</code>\n"
            f"الحالة: {status_ar(row['status'])}\n\n"
            f"رد الجهة:\n{text or '—'}"
        )
        try:
            await bot.send_message(row["tg_id"], user_msg,
                                   reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                       [InlineKeyboardButton(text="📋 طلباتي", callback_data="my:0")],
                                       [InlineKeyboardButton(text="‹ القائمة الرئيسية", callback_data="menu:main")],
                                   ]))
        except TelegramAPIError as e:
            log.warning("notify user failed: %s", e)

    await notify_admins(
        f"📨 <b>وصل رد جديد</b>\nالطلب: <code>{code}</code>\nالنص:\n{text[:400]}"
    )


# ============================
# KEYBOARDS
# ============================
def main_menu_kb() -> InlineKeyboardMarkup:
    rows = db_all("SELECT id, name FROM request_types WHERE enabled=1 ORDER BY id")
    kb = [[InlineKeyboardButton(text=f"📩 {r['name']}", callback_data=f"rt:{r['id']}")] for r in rows]
    kb.append([InlineKeyboardButton(text="📋 طلباتي", callback_data="my:0"),
               InlineKeyboardButton(text="🆘 المساعدة", callback_data="help")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


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
# FSM STATES
# ============================
class Flow(StatesGroup):
    phone = State()


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
    if get_setting("MAINTENANCE", "0") == "1" and not is_admin(m.from_user.id):
        await m.answer("🛠 البوت في وضع الصيانة حالياً.")
        return
    text = f"{divider()}\n<b>{BOT_NAME}</b>\n{divider()}\n\nاختر نوع المشكلة:"
    await m.answer(text, reply_markup=main_menu_kb())
    await m.answer(
        "⚠️ تنويه: هذا النظام يساعدك على تجهيز طلب مراجعة رسمي ومتابعته. "
        "لا يقوم بإزالة حظر واتساب ولا بتجاوز سياساتها."
    )


@router.callback_query(F.data == "menu:main")
async def cb_main(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    upsert_user(cb.from_user)
    text = f"{divider()}\n<b>{BOT_NAME}</b>\n{divider()}\n\nاختر نوع المشكلة:"
    await edit_or_send(cb, text, main_menu_kb())
    await cb.answer()


@router.callback_query(F.data == "help")
async def cb_help(cb: CallbackQuery):
    text = (
        "ℹ️ <b>المساعدة</b>\n\n"
        "• اختر نوع المشكلة من القائمة\n"
        "• أرسل رقم هاتفك بالصيغة الدولية\n"
        "• سيتابع النظام طلبك تلقائيًا\n\n"
        "⚠️ لا يقوم البوت بفك حظر واتساب."
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
        await m.answer("⚠ صيغة الرقم غير صحيحة، أرسل الرقم بصيغة دولية.\n"
                       "مثال: <code>+967XXXXXXXXX</code>")
        return
    phone = norm_phone(raw)
    data = await state.get_data()
    type_id = data.get("type_id")
    user = upsert_user(m.from_user)
    req_type = db_one("SELECT * FROM request_types WHERE id=?", (type_id,))
    if not req_type:
        await m.answer("⚠ النوع لم يعد متوفرًا. ابدأ من جديد بـ /start")
        await state.clear()
        return

    # رقم طلب جديد
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

    # إشعار مبدئي
    await m.answer(
        f"⏳ جاري معالجة الطلب...\n\nرقم الطلب: <code>{code}</code>",
    )

    # إرسال تلقائي حسب الإعداد
    if get_setting("AUTO_SEND", "1") == "1":
        await try_send_request(code, notify_user_chat_id=m.chat.id, silent=False)
    else:
        await m.answer(
            f"✓ تم إنشاء الطلب <code>{code}</code>\n"
            "بانتظار مراجعة الأدمن للإرسال.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📋 طلباتي", callback_data="my:0")],
                [InlineKeyboardButton(text="‹ القائمة الرئيسية", callback_data="menu:main")],
            ]),
        )

    await notify_admins(
        f"🆕 <b>طلب جديد</b>\n"
        f"الرقم: <code>{code}</code>\n"
        f"من: {m.from_user.full_name} (<code>{m.from_user.id}</code>)\n"
        f"النوع: {req_type['name']}\n"
        f"الهاتف: <code>{mask_phone(phone)}</code>"
    )


async def try_send_request(code: str, notify_user_chat_id: int | None = None,
                           silent: bool = False) -> None:
    row = db_one("SELECT * FROM requests WHERE code=?", (code,))
    if not row:
        return
    db_exec("UPDATE requests SET status=?, updated_at=?, last_attempt=? WHERE id=?",
            (RStatus.PREPARING.value, now().isoformat(), now().isoformat(), row["id"]))

    result = await CONNECTOR.send_request(row, row["message"])

    if result["ok"]:
        db_exec(
            "UPDATE requests SET status=?, external_message_id=?, external_thread_id=?, "
            "correlation_id=?, updated_at=? WHERE id=?",
            (RStatus.WAITING_REPLY.value, result["external_message_id"],
             result["external_thread_id"], result["correlation_id"],
             now().isoformat(), row["id"]),
        )
        log_event(None, "REQUEST_SENT", code, result["status"])
        db_exec(
            "INSERT INTO request_events(request_id, event, details, created_at) VALUES (?,?,?,?)",
            (row["id"], "SENT", result["status"], now().isoformat()),
        )
        if notify_user_chat_id and not silent:
            await bot.send_message(
                notify_user_chat_id,
                f"✓ <b>تم إرسال الطلب</b>\n\n"
                f"رقم الطلب: <code>{code}</code>\n"
                f"الحالة: {status_ar(RStatus.WAITING_REPLY.value)}\n\n"
                "سنوافيك بالرد فور وصوله.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📋 طلباتي", callback_data="my:0")],
                    [InlineKeyboardButton(text="‹ القائمة الرئيسية", callback_data="menu:main")],
                ]),
            )
    else:
        db_exec("UPDATE requests SET status=?, updated_at=? WHERE id=?",
                (RStatus.FAILED.value, now().isoformat(), row["id"]))
        log_event(None, "REQUEST_SEND_FAILED", code, result.get("error") or "")
        if notify_user_chat_id:
            msg = (
                "⚠ تعذر إرسال الطلب عبر قناة الدعم الرسمية."
                if result["status"] != "NOT_CONFIGURED"
                else "⚠ قناة الدعم غير مهيأة."
            )
            await bot.send_message(
                notify_user_chat_id,
                f"{msg}\n\nرقم الطلب: <code>{code}</code>",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📋 طلباتي", callback_data="my:0")],
                    [InlineKeyboardButton(text="‹ القائمة الرئيسية", callback_data="menu:main")],
                ]),
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
        await edit_or_send(cb, "لا توجد طلبات بعد.", back_kb())
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
        f"{divider()}\n<b>لوحة تحكم المطري</b>\n{divider()}",
        reply_markup=admin_panel_kb(),
    )


@router.callback_query(F.data == "adm:panel")
async def cb_adm_panel(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    await state.clear()
    await edit_or_send(cb, f"{divider()}\n<b>لوحة تحكم المطري</b>\n{divider()}", admin_panel_kb())
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
        f"Correlation ID: <code>{r['correlation_id'] or '—'}</code>\n"
        f"External Message: <code>{r['external_message_id'] or '—'}</code>\n\n"
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

    # إشعار المستخدم إذا الرد متاح
    u = db_one("SELECT telegram_id FROM users WHERE id=?", (r["user_id"],))
    if u and get_setting("AUTO_REPLY", "1") == "1":
        try:
            await bot.send_message(
                u["telegram_id"],
                f"{divider()}\n<b>تحديث طلبك</b>\n{divider()}\n\n"
                f"رقم الطلب: <code>{r['code']}</code>\n"
                f"الحالة الجديدة: {status_ar(st)}",
            )
        except TelegramAPIError:
            pass

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
    await cb.answer("جاري الإرسال...")
    await try_send_request(r["code"], notify_user_chat_id=None)
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
    await m.answer("✓ تمت إضافة الملاحظة.", reply_markup=back_kb("adm:panel"))
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
            f"✉ <b>رسالة من الدعم</b>\n\nبخصوص الطلب: <code>{r['code']}</code>\n\n{m.text}",
        )
        log_event(m.from_user.id, "SEND_USER_MSG", r["code"], "ok")
        await m.answer("✓ تم الإرسال.")
    except TelegramAPIError:
        await m.answer("⚠ فشل الإرسال.")
    await state.clear()


# ---------- محاكاة رد وارد (للاختبار) ----------
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
        "📨 اكتب نص الرد الوارد (سيُربط بالطلب عبر correlation_id):",
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
    await m.answer("✓ تمت معالجة الرد.")
    await state.clear()


# ---------- أنواع المشاكل ----------
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
        lines.append(f"{st} [{r['id']}] {r['name']} — {r['description'] or ''}")
        kb_rows.append([
            InlineKeyboardButton(text=f"✎ {r['name']}", callback_data=f"adm:tedit:{r['id']}"),
            InlineKeyboardButton(text="✅/⛔", callback_data=f"adm:ttoggle:{r['id']}"),
            InlineKeyboardButton(text="🗑", callback_data=f"adm:tdel:{r['id']}"),
        ])
    kb_rows.append([InlineKeyboardButton(text="➕ إضافة نوع", callback_data="adm:tadd")])
    kb_rows.append([InlineKeyboardButton(text="‹ رجوع", callback_data="adm:panel")])
    await edit_or_send(cb, "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=kb_rows))
    await cb.answer()


@router.callback_query(F.data == "adm:tadd")
async def cb_adm_tadd(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    await state.set_state(AdminFlow.add_type_name)
    await edit_or_send(cb, "➕ أرسل اسم النوع (مثال: حظر حساب):", back_kb("adm:types"))
    await cb.answer()


@router.message(AdminFlow.add_type_name)
async def on_add_type_name(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return
    name = (m.text or "").strip()
    if len(name) < 2:
        await m.answer("⚠ اسم قصير")
        return
    if db_one("SELECT id FROM request_types WHERE name=?", (name,)):
        await m.answer("⚠ الاسم مستخدم مسبقًا")
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
        "المتغيرات المتاحة:\n"
        "<code>{phone}</code> <code>{request_id}</code> <code>{user_id}</code> "
        "<code>{username}</code> <code>{first_name}</code> <code>{request_type}</code> "
        "<code>{created_at}</code>"
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
        "INSERT INTO request_types(name, description, template, enabled, created_at) "
        "VALUES (?,?,?,1,?)",
        (data["tname"], data.get("tdesc", ""), tpl, ts),
    )
    tid = db_one("SELECT id FROM request_types WHERE name=?", (data["tname"],))["id"]
    db_exec("INSERT INTO message_templates(type_id, body, updated_at) VALUES (?,?,?)",
            (tid, tpl, ts))
    log_event(m.from_user.id, "ADD_TYPE", data["tname"])
    await m.answer("✓ تمت الإضافة.", reply_markup=back_kb("adm:types"))
    await state.clear()


@router.callback_query(F.data.startswith("adm:ttoggle:"))
async def cb_adm_ttoggle(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    tid = int(cb.data.split(":")[2])
    db_exec("UPDATE request_types SET enabled = 1 - enabled WHERE id=?", (tid,))
    log_event(cb.from_user.id, "TOGGLE_TYPE", str(tid))
    await cb.answer("تم التبديل")
    await cb_adm_types(cb)


@router.callback_query(F.data.startswith("adm:tdel:"))
async def cb_adm_tdel(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    tid = int(cb.data.split(":")[2])
    db_exec("DELETE FROM request_types WHERE id=?", (tid,))
    log_event(cb.from_user.id, "DELETE_TYPE", str(tid))
    await cb.answer("تم الحذف")
    await cb_adm_types(cb)


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
    log_event(m.from_user.id, "EDIT_TYPE", str(tid))
    await m.answer("✓ تم التحديث.", reply_markup=back_kb("adm:types"))
    await state.clear()


# ---------- قوالب الرسائل ----------
@router.callback_query(F.data == "adm:templates")
async def cb_adm_templates(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    rows = db_all("SELECT id, name, template FROM request_types ORDER BY id")
    kb_rows = [[InlineKeyboardButton(text=f"📝 {r['name']}", callback_data=f"adm:tpl:{r['id']}")]
               for r in rows]
    kb_rows.append([InlineKeyboardButton(text="‹ رجوع", callback_data="adm:panel")])
    await edit_or_send(cb, "📝 <b>القوالب</b>\nاختر نوع الطلب:",
                       InlineKeyboardMarkup(inline_keyboard=kb_rows))
    await cb.answer()


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
    await edit_or_send(cb, f"<b>{r['name']}</b>\n\n<pre>{body}</pre>\n\n"
                           "المتغيرات: {phone} {request_id} {user_id} {username} "
                           "{first_name} {request_type} {created_at}", kb)
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
    await m.answer("✓ تم التحديث.", reply_markup=back_kb("adm:templates"))
    await state.clear()


# ---------- المستخدمون ----------
@router.callback_query(F.data == "adm:users")
async def cb_adm_users(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    total = db_one("SELECT COUNT(*) AS c FROM users")["c"]
    rows = db_all(
        "SELECT telegram_id, username, first_name, requests_count, last_activity "
        "FROM users ORDER BY last_activity DESC LIMIT 10"
    )
    lines = [f"{divider()}\n👤 <b>المستخدمون</b> (الإجمالي: {total})\n{divider()}\n"]
    for u in rows:
        lines.append(
            f"• {u['first_name'] or '—'} @{u['username'] or '—'} <code>{u['telegram_id']}</code>\n"
            f"  الطلبات: {u['requests_count']} | آخر نشاط: {fmt_dt(u['last_activity'])}"
        )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔎 بحث", callback_data="adm:usearch")],
        [InlineKeyboardButton(text="‹ رجوع", callback_data="adm:panel")],
    ])
    await edit_or_send(cb, "\n".join(lines), kb)
    await cb.answer()


@router.callback_query(F.data == "adm:usearch")
async def cb_adm_usearch(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    await state.set_state(AdminFlow.search_user)
    await edit_or_send(cb, "🔎 أرسل: Telegram ID / Username / كود طلب MTR-XXXXXX / رقم هاتف",
                       back_kb("adm:users"))
    await cb.answer()


@router.message(AdminFlow.search_user)
async def on_search_user(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return
    q = (m.text or "").strip()
    results = []
    if CODE_RE.match(q.upper()):
        r = db_one(
            "SELECT r.code, r.phone, r.status, r.request_type_name, u.telegram_id, u.first_name, u.username "
            "FROM requests r JOIN users u ON u.id=r.user_id WHERE r.code=?",
            (q.upper(),),
        )
        if r:
            results.append(
                f"📋 {r['code']} | {r['request_type_name']} | {status_ar(r['status'])}\n"
                f"👤 {r['first_name'] or '—'} @{r['username'] or '—'} <code>{r['telegram_id']}</code>\n"
                f"📱 {r['phone']}"
            )
    else:
        like = f"%{q.lstrip('@')}%"
        rows = db_all(
            "SELECT telegram_id, username, first_name, requests_count, last_activity "
            "FROM users WHERE CAST(telegram_id AS TEXT)=? OR username LIKE ? OR first_name LIKE ? LIMIT 15",
            (q, like, like),
        )
        for u in rows:
            results.append(
                f"• {u['first_name'] or '—'} @{u['username'] or '—'} <code>{u['telegram_id']}</code>\n"
                f"  الطلبات: {u['requests_count']} | آخر نشاط: {fmt_dt(u['last_activity'])}"
            )
    text = "🔎 <b>نتائج البحث</b>\n\n" + ("\n\n".join(results) if results else "لا نتائج.")
    await m.answer(text, reply_markup=back_kb("adm:users"))
    await state.clear()


# ---------- إحصائيات ----------
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
    day_ago = (now() - timedelta(days=1)).isoformat()
    week_ago = (now() - timedelta(days=7)).isoformat()
    month_ago = (now() - timedelta(days=30)).isoformat()
    today = db_one("SELECT COUNT(*) AS c FROM requests WHERE created_at>=?", (day_ago,))["c"]
    week = db_one("SELECT COUNT(*) AS c FROM requests WHERE created_at>=?", (week_ago,))["c"]
    month = db_one("SELECT COUNT(*) AS c FROM requests WHERE created_at>=?", (month_ago,))["c"]
    counts = {}
    for s in RStatus:
        counts[s.value] = db_one("SELECT COUNT(*) AS c FROM requests WHERE status=?", (s.value,))["c"]

    lines = [
        f"{divider()}", "📊 <b>الإحصائيات</b>", f"{divider()}", "",
        f"👥 المستخدمون: <b>{total_users}</b>",
        f"📋 إجمالي الطلبات: <b>{total_reqs}</b>",
        f"🗓 اليوم: {today} | الأسبوع: {week} | الشهر: {month}", "",
        "— حسب الحالة —",
    ]
    for s in RStatus:
        lines.append(f"• {status_ar(s.value)}: {counts[s.value]}")

    if total_reqs:
        lines.append("")
        lines.append("— توزيع الحالات —")
        for s in RStatus:
            c = counts[s.value]
            bar = "█" * int(round((c / total_reqs) * 20))
            lines.append(f"{status_ar(s.value):<20} | {bar} {c}")
    return "\n".join(lines)


# ---------- السجل ----------
@router.callback_query(F.data == "adm:logs")
async def cb_adm_logs(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    rows = db_all(
        "SELECT actor_id, action, target, details, created_at FROM logs "
        "ORDER BY created_at DESC LIMIT 30"
    )
    lines = [f"{divider()}\n📜 <b>آخر العمليات</b>\n{divider()}\n"]
    for r in rows:
        lines.append(
            f"• {fmt_dt(r['created_at'])}\n"
            f"  {r['action']} | actor=<code>{r['actor_id']}</code> | target={r['target'] or '—'}\n"
            f"  {r['details'] or ''}"
        )
    if not rows:
        lines.append("لا يوجد سجل.")
    await edit_or_send(cb, "\n".join(lines), back_kb("adm:panel"))
    await cb.answer()


# ---------- إعدادات ----------
@router.callback_query(F.data == "adm:settings")
async def cb_adm_settings(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    keys = ["AUTO_SEND", "AUTO_REPLY", "MAINTENANCE", "LOGGING", "RETRY_ENABLED"]
    labels = {
        "AUTO_SEND": "الإرسال التلقائي",
        "AUTO_REPLY": "الرد التلقائي",
        "MAINTENANCE": "وضع الصيانة",
        "LOGGING": "تسجيل العمليات",
        "RETRY_ENABLED": "إعادة المحاولة",
    }
    kb_rows = []
    lines = [f"{divider()}\n⚙ <b>الإعدادات</b>\n{divider()}\n"]
    for k in keys:
        v = get_setting(k, "0")
        lines.append(f"• {labels[k]}: {'✅ مفعّل' if v == '1' else '⛔ معطّل'}")
        kb_rows.append([InlineKeyboardButton(text=f"تبديل {labels[k]}", callback_data=f"adm:set:{k}")])

    conn_mode = get_setting("CONNECTOR_MODE", "not_configured")
    lines.append(f"\n🔌 وضع Connector: <b>{conn_mode}</b>")
    kb_rows.append([
        InlineKeyboardButton(text="not_configured", callback_data="adm:cmode:not_configured"),
        InlineKeyboardButton(text="manual", callback_data="adm:cmode:manual"),
        InlineKeyboardButton(text="api", callback_data="adm:cmode:api"),
    ])
    kb_rows.append([InlineKeyboardButton(text="‹ رجوع", callback_data="adm:panel")])
    await edit_or_send(cb, "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=kb_rows))
    await cb.answer()


@router.callback_query(F.data.startswith("adm:set:"))
async def cb_adm_set(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    k = cb.data.split(":")[2]
    v = get_setting(k, "0")
    set_setting(k, "0" if v == "1" else "1")
    log_event(cb.from_user.id, "SETTING_TOGGLE", k)
    await cb.answer("تم التبديل")
    await cb_adm_settings(cb)


@router.callback_query(F.data.startswith("adm:cmode:"))
async def cb_adm_cmode(cb: CallbackQuery):
    if not is_super(cb.from_user.id):
        await cb.answer("⛔ للسوبر أدمن فقط", show_alert=True)
        return
    mode = cb.data.split(":")[2]
    if mode not in ("not_configured", "manual", "api"):
        await cb.answer("وضع غير صالح", show_alert=True)
        return
    set_setting("CONNECTOR_MODE", mode)
    CONNECTOR.refresh()
    log_event(cb.from_user.id, "SET_CONNECTOR_MODE", mode)
    await cb.answer(f"تم الضبط: {mode}")
    await cb_adm_settings(cb)


# ---------- Backup / Export ----------
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
        log_event(cb.from_user.id, "BACKUP", dst.name)
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
    """يتابع الطلبات التي بانتظار الرد، ويحاول استرجاع الردود إن أمكن."""
    while True:
        try:
            if get_setting("RETRY_ENABLED", "1") == "1":
                max_retries = int(get_setting("MAX_RETRIES", "3") or 3)
                rows = db_all(
                    "SELECT * FROM requests WHERE status=? AND retry_count < ? LIMIT 20",
                    (RStatus.WAITING_REPLY.value, max_retries),
                )
                for r in rows:
                    # في الوضع الحقيقي: نتحقق من القناة الرسمية هنا
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
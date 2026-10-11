# ============================================================
# موقع أرقام OTP - نظيف
# الجزء 1: الاستيرادات + البيانات + الدوال
# ============================================================
import os, json, random, string, time
import sqlite3
from flask import Flask, render_template_string, request, redirect, url_for, jsonify, session, make_response
from functools import wraps
try:
    from ticket_templates import TICKET_CHAT_HTML, TICKETS_ADMIN_HTML
except ImportError:
    TICKET_CHAT_HTML = "<html><body>Ticket templates غير موجود</body></html>"
    TICKETS_ADMIN_HTML = "<html><body>Tickets admin غير موجود</body></html>"


# ═══════════════════════════════════════════
# PUSH NOTIFICATIONS
# ═══════════════════════════════════════════
_PUSH_READY = False
try:
    from pywebpush import webpush, WebPushException
    import base64 as _b64_push
    from cryptography.hazmat.primitives.asymmetric import ec as _ec_push
    from cryptography.hazmat.primitives import serialization as _ser_push
    _PUSH_READY = True
except Exception as _e:
    print("[PUSH] pywebpush غير مثبت:", _e)

VAPID_FILE = os.path.join(_PERSIST_DIR, "vapid.json")
_SUBS_FILE = os.path.join(_PERSIST_DIR, "push_subs.json")
_PUSH_LOCK = __import__("threading").Lock()

def _gen_vapid():
    """يولّد مفاتيح VAPID جديدة"""
    private_key = _ec_push.generate_private_key(_ec_push.SECP256R1())
    private_pem = private_key.private_bytes(
        encoding=_ser_push.Encoding.PEM,
        format=_ser_push.PrivateFormat.PKCS8,
        encryption_algorithm=_ser_push.NoEncryption()
    ).decode()
    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(
        encoding=_ser_push.Encoding.PEM,
        format=_ser_push.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    # استخرج المفتاح العمومي بالصيغة اللي يفهمها المتصفح (base64url)
    raw = public_key.public_bytes(
        encoding=_ser_push.Encoding.X962,
        format=_ser_push.PublicFormat.UncompressedPoint
    )
    public_b64 = _b64_push.urlsafe_b64encode(raw).rstrip(b"=").decode()
    return {"private_key": private_pem, "public_key": public_b64}

def _load_vapid():
    if os.path.exists(VAPID_FILE):
        try:
            with open(VAPID_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
                if d.get("private_key") and d.get("public_key"):
                    return d
        except Exception:
            pass
    if not _PUSH_READY:
        return {}
    d = _gen_vapid()
    try:
        with open(VAPID_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("[PUSH] save vapid error:", e)
    return d

_vapid = _load_vapid()

def _load_subs():
    if os.path.exists(_SUBS_FILE):
        try:
            with open(_SUBS_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
                if isinstance(d, list):
                    return d
        except Exception:
            pass
    return []

def _save_subs(subs):
    with _PUSH_LOCK:
        try:
            with open(_SUBS_FILE, "w", encoding="utf-8") as f:
                json.dump(subs, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print("[PUSH] save subs error:", e)

def _sub_key(sub):
    """مفتاح فريد للاشتراك"""
    ep = sub.get("endpoint", "")
    if len(ep) > 100:
        return ep[:100]
    return ep

def _add_sub(sub):
    subs = _load_subs()
    key = _sub_key(sub)
    for s in subs:
        if _sub_key(s) == key:
            return False
    subs.append(sub)
    _save_subs(subs)
    return True

def _remove_sub(endpoint):
    subs = _load_subs()
    new_subs = [s for s in subs if s.get("endpoint") != endpoint]
    if len(new_subs) != len(subs):
        _save_subs(new_subs)
        return True
    return False


# _platformIconsV1
import os as _os_pi

_PLATFORM_ICONS_DIR = os.path.join(_PERSIST_DIR, "static", "platform_icons")
try:
    _os_pi.makedirs(_PLATFORM_ICONS_DIR, exist_ok=True)
except Exception:
    pass

# خريطة الماركات (من تيليجرام) إلى أيقونات المنصات
BRAND_TO_PLATFORM = {
    "WA": "واتساب",
    "WB": "واتساب",
    "WS": "واتساب",
    "TG": "تيليجرام",
    "IM": "تيليجرام",
    "FB": "فيسبوك",
    "IG": "انستقرام",
    "TW": "تويتر",
    "X":  "تويتر",
    "GG": "جوجل",
    "AP": "آبل",
    "TT": "تيك توك",
    "DC": "ديسكورد",
    "SC": "سناب",
}

# ماركات غير معروفة → أخرى
BRAND_DEFAULT = "أخرى"

def _ensure_platform_icon_pngs():
    """يولّد أيقونات PNG لكل منصة من SVG (مرة واحدة)"""
    # flag — نتخطى لو فحصنا قبل
    import os as _os_flag
    flag = _os_flag.path.join(_os_flag.path.expanduser("~"), ".cairosvg_skip")
    if _os_flag.path.exists(flag):
        return
    try:
        import cairosvg
    except (ImportError, Exception) as _e:
        print("[PUSH-ICON] cairosvg غير متاح — تخطي")
        try:
            with open(flag, "w") as _f:
                _f.write("skip")
        except Exception:
            pass
        return
    _os_pi.makedirs(_PLATFORM_ICONS_DIR, exist_ok=True)
    for platform_name, svg in PLATFORM_ICONS.items():
        # استخدم اسم ملف آمن
        safe = "p_" + "".join(c for c in platform_name if c.isalnum() or c == "_") + ".png"
        out_path = _os_pi.path.join(_PLATFORM_ICONS_DIR, safe)
        # لو موجود حديث — تخطى
        if _os_pi.path.exists(out_path):
            continue
        try:
            cairosvg.svg2png(
                bytestring=svg.encode("utf-8"),
                write_to=out_path,
                output_width=192,
                output_height=192
            )
        except Exception as e:
            print(f"[PUSH-ICON] خطأ في {platform_name}: {e}")
    print("[PUSH-ICON] تم توليد أيقونات المنصات")

def _get_platform_icon_url(platform_name):
    """يرجع رابط الأيقونة PNG للمنصة"""
    if not platform_name:
        return ""
    safe = "p_" + "".join(c for c in platform_name if c.isalnum() or c == "_") + ".png"
    path = _os_pi.path.join(_PLATFORM_ICONS_DIR, safe)
    if _os_pi.path.exists(path):
        return "/" + _PLATFORM_ICONS_DIR + "/" + safe
    return ""

# _staticSvgIcon
def _get_static_icon_png():
    """يحوّل static/push_icon.svg إلى PNG ويحفظه في uploads/"""
    import os as _os_s
    svg_path = _os_s.path.join(_os_s.path.dirname(_os_s.path.abspath(__file__)), "static", "push_icon.svg")
    if not _os_s.path.exists(svg_path):
        return ""
    out_name = "push_icon_static.png"
    out_path = _os_s.path.join(UPLOAD_FOLDER, out_name)
    # لو موجود وحديث، استخدمه
    try:
        if _os_s.path.exists(out_path):
            svg_mtime = _os_s.path.getmtime(svg_path)
            png_mtime = _os_s.path.getmtime(out_path)
            if png_mtime >= svg_mtime:
                return "/uploads/" + out_name
    except Exception:
        pass
    # حوّل
    try:
        import cairosvg
        with open(svg_path, "r", encoding="utf-8") as _f:
            svg_text = _f.read()
        cairosvg.svg2png(
            bytestring=svg_text.encode("utf-8"),
            write_to=out_path,
            output_width=192,
            output_height=192
        )
        return "/uploads/" + out_name
    except Exception as e:
        print("[PUSH-STATIC-ICON] فشل التحويل:", e)
        return ""

# _pushCustomV1
def _svg_to_png(svg_text, out_path, size=192):
    """يحول SVG إلى PNG"""
    try:
        import cairosvg
        cairosvg.svg2png(
            bytestring=svg_text.encode("utf-8"),
            write_to=out_path,
            output_width=size,
            output_height=size
        )
        return True
    except Exception as e:
        print("[PUSH-SVG] cairosvg failed:", e)
        return False


def send_push_to_all(title, body, url="/", icon_svg="", icon_url="", tag="", target_endpoint="", icon_file=""):
    """يرسل إشعار Push لكل المشتركين أو لمشترك واحد"""
    if not _PUSH_READY:
        return 0

    subs = _load_subs()
    if not subs:
        return 0

    if target_endpoint:
        subs = [s for s in subs if s.get("endpoint") == target_endpoint]
        if not subs:
            return 0

    import os as _os_pf
    home = _os_pf.path.expanduser("~")
    pem_path = _os_pf.path.join(home, ".vapid_tmp.pem")
    try:
        with open(pem_path, "w") as _pf:
            _pf.write(_vapid.get("private_key", ""))
    except Exception as _e:
        print("[PUSH] فشل كتابة المفتاح المؤقت:", _e)
        return 0

    icon_path_final = ""
    try:
        if icon_file and _os_pf.path.exists(icon_file):
            if icon_file.lower().endswith(".svg"):
                png_out = _os_pf.path.join(home, ".push_icon_custom.png")
                with open(icon_file, "r", encoding="utf-8") as _f:
                    svg_text = _f.read()
                if _svg_to_png(svg_text, png_out):
                    icon_path_final = "/uploads/.push_icon_custom.png"
                    import shutil
                    shutil.copy(png_out, _os_pf.path.join(UPLOAD_FOLDER, ".push_icon_custom.png"))
            else:
                dst = _os_pf.path.join(UPLOAD_FOLDER, ".push_icon_custom.png")
                shutil.copy(icon_file, dst)
                icon_path_final = "/uploads/.push_icon_custom.png"
        elif icon_svg:
            png_out = _os_pf.path.join(home, ".push_icon_custom.png")
            if _svg_to_png(icon_svg, png_out):
                dst = _os_pf.path.join(UPLOAD_FOLDER, ".push_icon_custom.png")
                shutil.copy(png_out, dst)
                icon_path_final = "/uploads/.push_icon_custom.png"
        elif icon_url:
            icon_path_final = icon_url
    except Exception as _e:
        print("[PUSH-ICON] error:", _e)

    sent = 0
    dead = []
    for sub in subs:
        try:
            # _payloadFixV2
            # الأيقونة: من المخصصة أو SVG الثابت
            final_icon = icon_path_final
            if not final_icon:
                try:
                    final_icon = _get_static_icon_png()
                except Exception:
                    final_icon = ""

            # اسم الموقع في مقدمة العنوان
            site_name_local = "المطري OTP"
            try:
                _s = load_settings()
                site_name_local = _s.get("site_name", "المطري OTP")
            except Exception:
                pass

            full_title = title
            if site_name_local and title:
                full_title = title + " — " + site_name_local

            payload = {
                "title": full_title,
                "body": body,
                "url": url or "/",
                "badge": "/icon-192.png"
            }
            if final_icon:
                payload["icon"] = final_icon
            if tag:
                payload["tag"] = tag

            webpush(
                subscription_info=sub,
                data=json.dumps(payload, ensure_ascii=False),
                vapid_private_key=pem_path,
                vapid_claims={"sub": "mailto:admin@otp.local"}
            )
            sent += 1
        except WebPushException as e:
            status = getattr(e.response, "status_code", 0) if e.response else 0
            print("[PUSH] WebPushException: status=" + str(status))
            if status in (404, 410):
                dead.append(sub)
        except Exception as _ex:
            print("[PUSH] Exception: " + type(_ex).__name__ + ": " + str(_ex))

    if dead:
        subs2 = _load_subs()
        for d in dead:
            subs2 = [s for s in subs2 if s.get("endpoint") != d.get("endpoint")]
        _save_subs(subs2)
        print("[PUSH] حذف " + str(len(dead)) + " اشتراك ميت")

    print("[PUSH] أُرسل " + str(sent) + " / " + str(len(subs)))
    return sent


app = Flask(__name__)

ADMIN_PASSWORD = "admin2025"  # ← غيّرها من هنا

# ═══════════════════════════════════════════
# نظام المستخدمين
# ═══════════════════════════════════════════
import hashlib as _hashlib

def _hash_pw(pw):
    return _hashlib.sha256(("otp_salt_" + str(pw)).encode()).hexdigest()


def _gen_recovery_key():
    """يولّد مفتاح استيراد بصيغة AT-XXXX-XXXX-XXXX"""
    import secrets as _sec
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    def blk():
        return "".join(_sec.choice(chars) for _ in range(4))
    return "AT-" + blk() + "-" + blk() + "-" + blk()


def _get_recovery_key(username):
    """يرجع مفتاح الاستيراد لمستخدم — يولد لو مو موجود"""
    try:
        conn = _db()
        c = conn.cursor()
        row = c.execute("SELECT recovery_key FROM users WHERE username=?", (username.strip().lower(),)).fetchone()
        if row and row["recovery_key"]:
            conn.close()
            return row["recovery_key"]
        # ولّد جديد
        key = _gen_recovery_key()
        c.execute("UPDATE users SET recovery_key=? WHERE username=?", (key, username.strip().lower()))
        conn.commit()
        conn.close()
        return key
    except Exception as e:
        print("_get_recovery_key err:", e)
        return ""

# ═══════════════════════════════════════════
# SQLite — قاعدة البيانات
# ═══════════════════════════════════════════
# ═══ قاعدة بيانات دائمة ═══
# على Render: نستخدم /data (Persistent Disk)
# على Termux: نستخدم ~/.otp_persist
if os.environ.get("RENDER"):
    _PERSIST_DIR = "/data"
    if not os.path.exists(_PERSIST_DIR):
        _PERSIST_DIR = os.path.expanduser("~")
else:
    _PERSIST_DIR = os.path.join(os.path.expanduser("~"), ".otp_persist")
try:
    os.makedirs(_PERSIST_DIR, exist_ok=True)
except Exception:
    _PERSIST_DIR = os.path.expanduser("~")
DB_FILE = os.path.join(_PERSIST_DIR, "data.db")
print("[DB] ملف البيانات: " + DB_FILE)

def _db():
    """اتصال بقاعدة البيانات"""
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

def db_init():
    """إنشاء الجداول لو مو موجودة"""
    conn = _db()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            created REAL DEFAULT 0,
            avatar TEXT DEFAULT '',
            last_login REAL DEFAULT 0,
            visits INTEGER DEFAULT 0
        )
    """)
    # أضف عمود password_plain لو ما كان
    try:
        c.execute("ALTER TABLE users ADD COLUMN password_plain TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    # recovery_key — مفتاح استيراد الحساب
    try:
        c.execute("ALTER TABLE users ADD COLUMN recovery_key TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    c.execute("CREATE INDEX IF NOT EXISTS idx_users_created ON users(created DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_users_last_login ON users(last_login DESC)")

    # جدول المسابقات
    c.execute("""
        CREATE TABLE IF NOT EXISTS contests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            kind TEXT DEFAULT 'event',
            prize TEXT DEFAULT '',
            icon TEXT DEFAULT '',
            image TEXT DEFAULT '',
            starts_at REAL DEFAULT 0,
            ends_at REAL DEFAULT 0,
            status TEXT DEFAULT 'active',
            pinned INTEGER DEFAULT 0,
            votes TEXT DEFAULT '[]',
            voters TEXT DEFAULT '[]',
            created REAL DEFAULT 0,
            updated REAL DEFAULT 0
        )
    """)
    try:
        c.execute("ALTER TABLE contests ADD COLUMN answer TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE contests ADD COLUMN participants TEXT DEFAULT '[]'")
    except sqlite3.OperationalError:
        pass
    c.execute("CREATE INDEX IF NOT EXISTS idx_contests_pinned ON contests(pinned DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_contests_status ON contests(status)")

    # جدول الإعلانات
    c.execute("""
        CREATE TABLE IF NOT EXISTS ads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            body TEXT DEFAULT '',
            images TEXT DEFAULT '[]',
            contact_url TEXT DEFAULT '',
            contact_label TEXT DEFAULT 'تواصل',
            starts_at REAL DEFAULT 0,
            ends_at REAL DEFAULT 0,
            status TEXT DEFAULT 'active',
            pinned INTEGER DEFAULT 0,
            custom_buttons TEXT DEFAULT '[]',
            info_html TEXT DEFAULT '',
            created REAL DEFAULT 0,
            updated REAL DEFAULT 0
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_ads_pinned ON ads(pinned DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_ads_status ON ads(status)")
    # custom_buttons — للتثبيتات الموجودة
    try:
        c.execute("ALTER TABLE ads ADD COLUMN custom_buttons TEXT DEFAULT '[]'")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE ads ADD COLUMN info_html TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass

    # ═══════════════════════════════════════
    # SOCIAL — شبكة اجتماعية
    # ═══════════════════════════════════════
    c.execute("""
        CREATE TABLE IF NOT EXISTS social_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            author TEXT NOT NULL,
            kind TEXT DEFAULT 'text',
            body TEXT DEFAULT '',
            media TEXT DEFAULT '[]',
            attach TEXT DEFAULT '',
            attach_name TEXT DEFAULT '',
            pinned INTEGER DEFAULT 0,
            status TEXT DEFAULT 'active',
            created REAL DEFAULT 0,
            updated REAL DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS social_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            author TEXT NOT NULL,
            body TEXT DEFAULT '',
            parent_id INTEGER DEFAULT 0,
            created REAL DEFAULT 0,
            FOREIGN KEY (post_id) REFERENCES social_posts(id) ON DELETE CASCADE
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS social_reactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            author TEXT NOT NULL,
            kind TEXT DEFAULT 'like',
            created REAL DEFAULT 0,
            UNIQUE(post_id, author)
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_sp_created ON social_posts(created DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sp_pinned ON social_posts(pinned DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sc_post ON social_comments(post_id)")
    # parent_id — للردود
    try:
        c.execute("ALTER TABLE social_comments ADD COLUMN parent_id INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    c.execute("CREATE INDEX IF NOT EXISTS idx_sr_post ON social_reactions(post_id)")

    conn.commit()
    conn.close()

def load_users():
    """يرجع كل المستخدمين من DB"""
    try:
        conn = _db()
        rows = conn.execute("SELECT * FROM users").fetchall()
        conn.close()
        users = {}
        for r in rows:
            keys = r.keys()
            users[r["username"]] = {
                "username": r["display_name"],
                "password": r["password_hash"],
                "password_plain": (r["password_plain"] or "") if "password_plain" in keys else "",
                "created": r["created"],
                "avatar": r["avatar"],
                "last_login": r["last_login"],
                "visits": r["visits"]
            }
        return users
    except Exception as e:
        print("DB load_users error:", e)
        return {}

def save_users(users):
    """يحفظ المستخدمين (يستخدمه الكود القديم)"""
    try:
        conn = _db()
        c = conn.cursor()
        for key, u in users.items():
            c.execute("""
                INSERT OR REPLACE INTO users
                (username, display_name, password_hash, password_plain, created, avatar, last_login, visits)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                key,
                u.get("username", key),
                u.get("password", ""),
                u.get("password_plain", ""),
                u.get("created", time.time()),
                u.get("avatar", ""),
                u.get("last_login", 0),
                u.get("visits", 0)
            ))
        conn.commit()
        conn.close()
    except Exception as e:
        print("DB save_users error:", e)

def _backup_users_db():
    """نسخة احتياطية من قاعدة البيانات — تلقائياً"""
    try:
        import shutil as _sh
        import time as _t
        # نسخ إلى مجلد النسخ
        backup_dir = os.path.join(_PERSIST_DIR, "backups")
        os.makedirs(backup_dir, exist_ok=True)
        # نسخة يومية
        day = _t.strftime("%Y-%m-%d")
        daily = os.path.join(backup_dir, "data_" + day + ".db")
        if not os.path.exists(daily):
            _sh.copy2(DB_FILE, daily)
        # نسخة ساعية (آخر 24)
        hour = _t.strftime("%Y-%m-%d_%H")
        hourly = os.path.join(backup_dir, "data_" + hour + ".db")
        _sh.copy2(DB_FILE, hourly)
        # احذف النسخ الأقدم من 7 أيام
        try:
            now = _t.time()
            for fn in os.listdir(backup_dir):
                fp = os.path.join(backup_dir, fn)
                if os.path.isfile(fp) and (now - os.path.getmtime(fp)) > 7 * 86400:
                    os.remove(fp)
        except Exception:
            pass
    except Exception as e:
        print("[BACKUP] err:", e)


def db_update_user(username, **fields):
    """يحدّث حقول معينة لمستخدم"""
    if not fields:
        return False
    try:
        allowed = {"display_name", "password_hash", "avatar", "last_login", "visits"}
        sets = []
        vals = []
        for k, v in fields.items():
            if k in allowed:
                sets.append(k + " = ?")
                vals.append(v)
        if not sets:
            return False
        vals.append(username.strip().lower())
        conn = _db()
        conn.execute("UPDATE users SET " + ", ".join(sets) + " WHERE username = ?", vals)
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print("DB update error:", e)
        return False

def db_delete_user(username):
    """يحذف مستخدم من DB"""
    try:
        conn = _db()
        conn.execute("DELETE FROM users WHERE username = ?", (username.strip().lower(),))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print("DB delete error:", e)
        return False

def find_user(username):
    users = load_users()
    key = username.strip().lower()
    if key in users:
        return key, users[key]
    return None, None

def create_user(username, password):
    username = username.strip()
    if not username or not password:
        return False, "الاسم وكلمة السر مطلوبة"
    if len(username) < 3:
        return False, "الاسم قصير جداً (3 أحرف على الأقل)"
    if len(password) < 4:
        return False, "كلمة السر قصيرة (4 أحرف على الأقل)"
    key = username.lower()
    users = load_users()
    if key in users:
        return False, "الاسم مستخدم مسبقاً"
    # ولّد مفتاح استيراد فريد
    import secrets as _sec
    key_new = _gen_recovery_key()
    # تأكد أنه ما يتكرر
    try:
        conn = _db()
        for _try in range(20):
            exists = conn.execute("SELECT 1 FROM users WHERE recovery_key=?", (key_new,)).fetchone()
            if not exists:
                break
            key_new = _gen_recovery_key()
        conn.close()
    except Exception:
        pass
    users[key] = {
        "username": username,
        "password": _hash_pw(password),
        "password_plain": password,
        "created": time.time(),
        "avatar": "",
        "visits": 0,
        "last_login": time.time()
    }
    save_users(users)
    # احفظ المفتاح
    try:
        conn = _db()
        conn.execute("UPDATE users SET recovery_key=? WHERE username=?", (key_new, key))
        conn.commit()
        conn.close()
    except Exception as e:
        print("save recovery_key err:", e)
    print(f"[RECOVERY] مستخدم جديد: {username} → مفتاح: {key_new}")
    _backup_users_db()
    return True, "تم التسجيل بنجاح"

def user_required(f):
    from functools import wraps as _wraps
    @_wraps(f)
    def deco(*args, **kwargs):
        if not session.get("user_logged"):
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return deco

# ═══ ضغط البيانات ═══
try:
    from flask_compress import Compress
    Compress(app)
    print('✅ ضغط gzip مفعّل')
except ImportError:
    print('⚠️ flask_compress غير مثبت — تثبيت: pip install flask-compress')

@app.before_request
def _global_gate():
    """قفل شامل: أي مسار إلا المسموح → لازم تسجيل دخول"""
    # المسارات المسموحة بدون تسجيل
    allowed_prefixes = [
        "/login", "/logout", "/forgot", "/import", "/admin", "/static", "/uploads",
        "/manifest.json", "/sw.js", "/icon-192.png", "/icon-512.png",
        "/favicon.ico", "/api/import-account", "/api/my-recovery-key", "/api/tree", "/api/bot-version", "/api/check-otp",
        "/api/tree", "/api/check-otp", "/api/set-platform", "/api/codes/list",
        "/api/notice", "/api/maintenance", "/api/version", "/api/bot-version",
        "/api/push/public-key", "/api/push/subscribe", "/api/push/unsubscribe",
        "/api/telegram/status", "/api/support/unread", "/api/track"
    ]
    allowed_exact = ["/"]
    path = request.path
    # الأدمن يعدي
    if session.get("admin_logged"):
        return None
    # المستخدم المسجل يعدي
    if session.get("user_logged"):
        return None
    # المسموحات
    for pref in allowed_prefixes:
        if path.startswith(pref):
            return None
    # الرئيسية تروح لـ login
    if path == "/":
        return redirect(url_for("login_page"))
    # أي مسار ثاني → يرجع للدخول
    return redirect(url_for("login_page"))


@app.route("/login", methods=["GET", "POST"])
def login_page():
    err = ""
    mode = request.args.get("mode", "login").strip()
    if mode not in ("login", "register"):
        mode = "login"
    if request.method == "POST":
        action = request.form.get("action", "login")
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if action == "register":
            password_confirm = request.form.get("password_confirm", "")
            if password != password_confirm:
                err = "كلمتا السر غير متطابقتين"
                mode = "register"
                return render_template_string(LOGIN_HTML, err=err, mode=mode)
            ok, msg = create_user(username, password)
            if ok:
                # رفع الصورة لو موجودة
                avatar_url = ""
                avatar_file = request.files.get("avatar")
                print("[REGISTER] avatar_file:", avatar_file, "filename:", avatar_file.filename if avatar_file else None)
                if avatar_file and avatar_file.filename:
                    from werkzeug.utils import secure_filename
                    fn = secure_filename(avatar_file.filename)
                    ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else ""
                    if ext in ["jpg", "jpeg", "png", "gif", "webp"]:
                        try:
                            os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                            new_name = "av_user_" + str(int(time.time())) + "_" + fn
                            avatar_file.save(os.path.join(UPLOAD_FOLDER, new_name))
                            users = load_users()
                            key = username.lower()
                            if key in users:
                                users[key]["avatar"] = "/uploads/" + new_name
                                save_users(users)
                                avatar_url = "/uploads/" + new_name
                                print("[REGISTER] saved avatar:", avatar_url)
                        except Exception as e:
                            print("register avatar err:", e)
                session["user_logged"] = True
                session["user_name"] = username
                session.permanent = True
                # 🔄 حدّث الصورة في session
                users = load_users()
                k = username.lower()
                if k in users and users[k].get("avatar"):
                    session["user_avatar"] = users[k]["avatar"]
                return redirect(url_for("index"))
            err = msg
            mode = "register"
        else:
            key, u = find_user(username)
            if u and u.get("password") == _hash_pw(password):
                session["user_logged"] = True
                session["user_name"] = u.get("username", username)
                session["user_avatar"] = u.get("avatar", "")
                session.permanent = True
                db_update_user(key, last_login=time.time())
                return redirect(url_for("index"))
            err = "اسم أو كلمة سر غلط"
    return render_template_string(LOGIN_HTML, err=err, mode=mode)

@app.route("/forgot", methods=["GET", "POST"])
def forgot_password():
    """صفحة نسيت كلمة السر"""
    err = ""
    success = ""
    new_pw = ""
    if request.method == "POST":
        action = request.form.get("action", "reset")
        if action == "reset":
            username = request.form.get("username", "").strip()
            key, u = find_user(username)
            if not u:
                err = "اسم المستخدم غير موجود"
            else:
                # نولّد كلمة سر جديدة
                import secrets as _sec
                new_pw = _sec.token_urlsafe(6)[:8]
                users = load_users()
                users[key]["password"] = _hash_pw(new_pw)
                users[key]["password_plain"] = new_pw
                save_users(users)
                success = "تم إنشاء كلمة سر جديدة"
                print("🔑 كلمة سر جديدة:", username, "→", new_pw)
    return render_template_string(FORGOT_HTML, err=err, success=success, new_pw=new_pw)


@app.route("/logout")
def user_logout():
    session.pop("user_logged", None)
    session.pop("user_name", None)
    return redirect(url_for("login_page"))

LOGIN_HTML = r"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<meta name="theme-color" content="#7b2ff7">
<title>تسجيل الدخول — المطري OTP</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;font-family:-apple-system,'Segoe UI',Tahoma,sans-serif;-webkit-tap-highlight-color:transparent}
html,body{height:100%;overflow:hidden}
body{background:#0a0a18;color:#fff;display:flex;align-items:center;justify-content:center;padding:20px;position:relative;min-height:100vh}

/* خلفية ناعمة */
.bg{position:fixed;inset:0;z-index:0;pointer-events:none;overflow:hidden}
.bg::before{content:"";position:absolute;width:500px;height:500px;background:radial-gradient(circle,rgba(123,47,247,.35),transparent 70%);top:-150px;right:-100px;border-radius:50%;filter:blur(40px)}
.bg::after{content:"";position:absolute;width:450px;height:450px;background:radial-gradient(circle,rgba(0,212,255,.25),transparent 70%);bottom:-120px;left:-100px;border-radius:50%;filter:blur(40px)}

.wrap{position:relative;z-index:2;width:100%;max-width:380px}

/* بطاقة */
.card{background:linear-gradient(160deg,#161628,#0f0f1e);border:1px solid rgba(123,47,247,.2);border-radius:28px;padding:36px 28px 28px;box-shadow:0 20px 60px rgba(0,0,0,.5),0 0 0 1px rgba(255,255,255,.03) inset}

/* أيقونة رأس دائرية */
.avatar-ring{width:88px;height:88px;margin:0 auto 18px;border-radius:50%;background:radial-gradient(circle at 30% 30%,#7b2ff7,#0a0a18);display:flex;align-items:center;justify-content:center;position:relative;box-shadow:0 8px 30px rgba(123,47,247,.4)}
.avatar-ring::before{content:"";position:absolute;inset:-3px;border-radius:50%;background:linear-gradient(135deg,#7b2ff7,#00d4ff);z-index:-1;opacity:0.6}
.avatar-ring svg{width:44px;height:44px;fill:#fff}

/* عنوان */
.title{text-align:center;font-size:28px;font-weight:900;letter-spacing:.5px;margin-bottom:26px;background:linear-gradient(135deg,#fff,#a8d8ff);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}

/* حقل */
.field{margin-bottom:16px}
.field label{display:block;font-size:13px;color:#a8a8bd;margin-bottom:8px;font-weight:600}
.field-in{position:relative}
.field-in .lead{position:absolute;right:16px;top:50%;transform:translateY(-50%);width:20px;height:20px;fill:#6e6e8a;pointer-events:none;transition:fill .2s}
.field-in input{width:100%;padding:15px 48px 15px 48px;border:1.5px solid rgba(123,47,247,.15);border-radius:14px;background:rgba(0,0,0,.4);color:#fff;font-size:15px;outline:none;font-family:inherit;transition:all .2s}
.field-in input:focus{border-color:#7b2ff7;background:rgba(123,47,247,.06);box-shadow:0 0 0 4px rgba(123,47,247,.12)}
.field-in input:focus ~ .lead{fill:#00d4ff}
.eye{position:absolute;left:12px;top:50%;transform:translateY(-50%);width:34px;height:34px;border:none;background:transparent;cursor:pointer;display:flex;align-items:center;justify-content:center;border-radius:50%}
.eye svg{width:18px;height:18px;fill:#6e6e8a}
.eye:active{background:rgba(255,255,255,.06)}

/* نسيت كلمة السر */
.forgot{display:block;text-align:left;font-size:12px;color:#7b8cff;text-decoration:none;margin:-6px 0 20px;font-weight:600}
.forgot:hover{color:#00d4ff}

/* زر */
.btn{width:100%;padding:16px;border:none;border-radius:14px;background:linear-gradient(135deg,#7b2ff7,#00d4ff);color:#fff;font-weight:800;font-size:16px;cursor:pointer;font-family:inherit;box-shadow:0 10px 30px rgba(123,47,247,.4);transition:transform .15s,box-shadow .15s;letter-spacing:.5px}
.btn:active{transform:scale(.98);box-shadow:0 6px 20px rgba(123,47,247,.3)}

/* تنبيه خطأ */
.err{background:rgba(233,69,96,.15);border:1px solid rgba(233,69,96,.4);color:#ff8aa3;padding:12px;border-radius:12px;font-size:13px;text-align:center;margin-bottom:16px;font-weight:600}

/* تبديل الوضع */
.switch-line{text-align:center;margin-top:20px;font-size:13px;color:#8e8eab}
.switch-line button{background:none;border:none;color:#00d4ff;font-weight:800;cursor:pointer;font-size:13px;font-family:inherit;padding:4px 6px;border-radius:6px}
.switch-line button:hover{background:rgba(0,212,255,.08)}

/* شعار صغير أسفل */
.forgot-link{display:block;text-align:center;margin-top:12px;font-size:13px;color:#00d4ff;text-decoration:none;font-weight:700;padding:8px;border-radius:10px;transition:background .2s}
.forgot-link:hover,.forgot-link:active{background:rgba(0,212,255,.08)}
.logo-foot{text-align:center;margin-top:22px;font-size:11px;color:#5a5a72;letter-spacing:1px;display:flex;align-items:center;justify-content:center;gap:6px}
.logo-foot svg{width:14px;height:14px;fill:#7b2ff7}

.hidden{display:none}

/* ═══ تصغير عند التسجيل (حتى يرجع داخل الشاشة) ═══ */
#formRegister .field{margin-bottom:11px}
#formRegister .field label{font-size:12px;margin-bottom:6px}
#formRegister .field-in input{padding:12px 44px 12px 44px;font-size:14px}
#formRegister .btn{padding:13px;font-size:15px}
#formRegister .card{padding-top:28px;padding-bottom:22px}
#formRegister ~ .switch-line{margin-top:14px}
.card:has(#formRegister:not(.hidden)) .avatar-ring{width:72px;height:72px;margin-bottom:12px}
.card:has(#formRegister:not(.hidden)) .avatar-ring svg{width:36px;height:36px}
.card:has(#formRegister:not(.hidden)) .avatar-cam-badge{width:26px;height:26px}
.card:has(#formRegister:not(.hidden)) .avatar-cam-badge svg{width:13px;height:13px}
.card:has(#formRegister:not(.hidden)) .title{font-size:24px;margin-bottom:18px}

/* رفع صورة في التسجيل */
.avatar-upload-field{margin-bottom:18px}
.avatar-pick{display:block;cursor:pointer}
.avatar-preview{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;padding:24px 16px;border:2px dashed rgba(123,47,247,.5);border-radius:18px;background:rgba(123,47,247,.06);transition:all .25s;min-height:150px;cursor:pointer;position:relative;overflow:hidden}
.avatar-preview::before{content:"";position:absolute;inset:0;background:radial-gradient(circle at center,rgba(123,47,247,.15),transparent 70%);opacity:0;transition:opacity .3s}
.avatar-preview:hover::before{opacity:1}
.avatar-preview:active{background:rgba(123,47,247,.12);border-color:#7b2ff7}
.avatar-preview svg{width:44px;height:44px;fill:#7b2ff7;opacity:.7}
.avatar-pick-label{font-size:12px;color:#8e8eab;font-weight:600}
.avatar-preview img{width:90px;height:90px;border-radius:50%;object-fit:cover;border:3px solid #7b2ff7;box-shadow:0 6px 20px rgba(123,47,247,.5)}
.avatar-preview.has-img{border-style:solid;border-color:#7b2ff7;background:rgba(123,47,247,.08)}
.avatar-preview.has-img .avatar-pick-label{color:#7b2ff7}
.avatar-ring{cursor:pointer;transition:transform .2s}
.avatar-ring:active{transform:scale(.95)}
.avatar-cam-badge{position:absolute;bottom:-2px;left:-2px;width:30px;height:30px;border-radius:50%;background:linear-gradient(135deg,#7b2ff7,#00d4ff);display:flex;align-items:center;justify-content:center;box-shadow:0 4px 14px rgba(123,47,247,.6);border:2.5px solid #0a0a18;z-index:5}
.avatar-cam-badge svg{width:16px;height:16px;fill:#fff}

/* شريط علوي */
.top-bar{position:fixed;top:16px;left:0;right:0;padding:0 20px;display:flex;align-items:center;justify-content:space-between;z-index:10;max-width:460px;margin:0 auto}
.mini-logo{display:flex;align-items:center;gap:8px;padding:8px 14px;background:rgba(22,22,40,.6);backdrop-filter:blur(12px);border:1px solid rgba(123,47,247,.2);border-radius:14px}
.mini-name{font-size:13px;font-weight:800;background:linear-gradient(135deg,#00d4ff,#7b2ff7);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;letter-spacing:.3px}
.lang-btn{padding:9px 16px;background:rgba(22,22,40,.6);backdrop-filter:blur(12px);border:1px solid rgba(123,47,247,.25);border-radius:14px;color:#00d4ff;font-weight:800;font-size:13px;cursor:pointer;font-family:inherit;letter-spacing:1px;transition:all .2s}
.lang-btn:active{transform:scale(.95);background:rgba(0,212,255,.12)}

/* إنجليزي */
body[dir="ltr"] .top-bar{flex-direction:row-reverse}
body[dir="ltr"] .forgot{text-align:right}
</style>
</head>
<body>

<div class="bg"></div>

<!-- شريط علوي: شعار صغير يمين + زر لغة يسار -->
<div class="top-bar">
<div class="mini-logo">
<svg viewBox="0 0 24 24" width="20" height="20">
<defs>
<linearGradient id="miniG" x1="0%" y1="0%" x2="100%" y2="100%">
<stop offset="0%" stop-color="#00d4ff"/>
<stop offset="100%" stop-color="#7b2ff7"/>
</linearGradient>
</defs>
<path d="M12 2L3 6.5v6.5c0 5.3 3.9 9.7 9 11 5.1-1.3 9-5.7 9-11V6.5L12 2z" fill="none" stroke="url(#miniG)" stroke-width="1.6" stroke-linejoin="round"/>
<circle cx="12" cy="10" r="1.6" fill="#00d4ff"/>
<path d="M9.5 13.5 L10.5 15.5 L14.5 15.5 L15.5 13.5" stroke="#7b2ff7" stroke-width="1.3" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
<span class="mini-name">المطري OTP</span>
</div>
<button class="lang-btn" onclick="toggleLangPage()" id="langBtn">EN</button>
</div>

<div class="wrap">
<div class="card">

<!-- أيقونة رأس -->
<label class="avatar-ring" for="regAvatarTop" id="avatarTopLabel" style="cursor:pointer;position:relative">
<svg viewBox="0 0 24 24" id="avatarTopSvg"><path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/></svg>
<img id="avatarTopImg" style="display:none;width:100%;height:100%;object-fit:cover;border-radius:50%" alt="">
<div class="avatar-cam-badge">
<svg viewBox="0 0 24 24"><path d="M12 15.2a3.2 3.2 0 100-6.4 3.2 3.2 0 000 6.4zM9 2L7.17 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2h-3.17L15 2H9zm3 15c-2.76 0-5-2.24-5-5s2.24-5 5-5 5 2.24 5 5-2.24 5-5 5z"/></svg>
</div>
</label>
<!-- input رفع الصورة — ينقل داخل formRegister -->


<div class="title" id="pageTitle">تسجيل الدخول</div>

{% if err %}
<div class="err">{{ err }}</div>
{% endif %}

<!-- نموذج الدخول -->
<form method="POST" id="formLogin" class="{% if mode == 'register' %}hidden{% endif %}">
<input type="hidden" name="action" value="login">
<div class="field">
<label data-i18n="label_user">اسم المستخدم</label>
<div class="field-in">
<input type="text" name="username" placeholder="ادخل اسمك" required autocomplete="username">
<svg class="lead" viewBox="0 0 24 24"><path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/></svg>
</div>
</div>
<div class="field">
<label data-i18n="label_pw">كلمة السر</label>
<div class="field-in">
<input type="password" name="password" id="pwLogin" placeholder="••••••••" required autocomplete="current-password">
<svg class="lead" viewBox="0 0 24 24"><path d="M18 8h-1V6c0-2.76-2.24-5-5-5S7 3.24 7 6v2H6c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V10c0-1.1-.9-2-2-2zm-6 9c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2zm3.1-9H8.9V6c0-1.71 1.39-3.1 3.1-3.1 1.71 0 3.1 1.39 3.1 3.1v2z"/></svg>
<button type="button" class="eye" onclick="togglePw('pwLogin', this)">
<svg viewBox="0 0 24 24"><path d="M12 4.5C7 4.5 2.73 7.61 1 12c1.73 4.39 6 7.5 11 7.5s9.27-3.11 11-7.5c-1.73-4.39-6-7.5-11-7.5zM12 17c-2.76 0-5-2.24-5-5s2.24-5 5-5 5 2.24 5 5-2.24 5-5 5zm0-8c-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3-1.34-3-3-3z"/></svg>
</button>
</div>
</div>
<button type="submit" class="btn" data-i18n="btn_login">تسجيل الدخول</button>
</form>

<!-- نموذج التسجيل -->
<form method="POST" id="formRegister" class="{% if mode != 'register' %}hidden{% endif %}" enctype="multipart/form-data">
<input type="hidden" name="action" value="register">
<input type="file" id="regAvatarTop" name="avatar" accept="image/*" onchange="previewRegAvatar(event)" style="display:none">

<div class="field">
<label data-i18n="label_user">اسم المستخدم</label>
<div class="field-in">
<input type="text" name="username" placeholder="اختر اسم مستخدم" required minlength="3" autocomplete="username">
<svg class="lead" viewBox="0 0 24 24"><path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/></svg>
</div>
</div>
<div class="field">
<label data-i18n="label_pw">كلمة السر</label>
<div class="field-in">
<input type="password" name="password" id="pwReg" placeholder="اختر كلمة سر قوية" required minlength="4" autocomplete="new-password">
<svg class="lead" viewBox="0 0 24 24"><path d="M18 8h-1V6c0-2.76-2.24-5-5-5S7 3.24 7 6v2H6c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V10c0-1.1-.9-2-2-2zm-6 9c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2zm3.1-9H8.9V6c0-1.71 1.39-3.1 3.1-3.1 1.71 0 3.1 1.39 3.1 3.1v2z"/></svg>
<button type="button" class="eye" onclick="togglePw('pwReg', this)">
<svg viewBox="0 0 24 24"><path d="M12 4.5C7 4.5 2.73 7.61 1 12c1.73 4.39 6 7.5 11 7.5s9.27-3.11 11-7.5c-1.73-4.39-6-7.5-11-7.5zM12 17c-2.76 0-5-2.24-5-5s2.24-5 5-5 5 2.24 5 5-2.24 5-5 5zm0-8c-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3-1.34-3-3-3z"/></svg>
</button>
</div>
</div>
<div class="field">
<label data-i18n="label_pw_confirm">تأكيد كلمة السر</label>
<div class="field-in">
<input type="password" name="password_confirm" id="pwRegConfirm" placeholder="أعد كتابة كلمة السر" required minlength="4" autocomplete="new-password">
<svg class="lead" viewBox="0 0 24 24"><path d="M18 8h-1V6c0-2.76-2.24-5-5-5S7 3.24 7 6v2H6c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V10c0-1.1-.9-2-2-2zm-6 9c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2zm3.1-9H8.9V6c0-1.71 1.39-3.1 3.1-3.1 1.71 0 3.1 1.39 3.1 3.1v2z"/></svg>
<button type="button" class="eye" onclick="togglePw('pwRegConfirm', this)">
<svg viewBox="0 0 24 24"><path d="M12 4.5C7 4.5 2.73 7.61 1 12c1.73 4.39 6 7.5 11 7.5s9.27-3.11 11-7.5c-1.73-4.39-6-7.5-11-7.5zM12 17c-2.76 0-5-2.24-5-5s2.24-5 5-5 5 2.24 5 5-2.24 5-5 5zm0-8c-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3-1.34-3-3-3z"/></svg>
</button>
</div>
</div>
<button type="submit" class="btn" data-i18n="btn_register">إنشاء الحساب</button>
</form>

<div class="switch-line">
<span id="switchText">ما عندك حساب؟</span>
<button type="button" id="switchBtn" onclick="toggleMode()" style="background:none;border:none;color:#00d4ff;font-weight:800;cursor:pointer;padding:4px 8px;border-radius:6px;font-family:inherit;font-size:13px">إنشاء حساب</button>
</div>
<input type="hidden" id="modeHidden" value="{% if mode == 'register' %}register{% else %}login{% endif %}">

<a href="/forgot" class="forgot-link" id="forgotLink">نسيت كلمة السر؟</a>
<a href="/import" class="forgot-link" id="importLink" style="color:#00d4a5;margin-top:4px">استيراد حساب موجود</a>

<div class="logo-foot">
<svg viewBox="0 0 24 24"><path d="M12 2L2 7v7c0 5 4 9 10 10 6-1 10-5 10-10V7z"/></svg>
المطري OTP
</div>

</div>
</div>

<script>
function toggleMode(){
    var fl = document.getElementById('formLogin');
    var fr = document.getElementById('formRegister');
    if(_mode === 'login'){
        _mode = 'register';
        fl.classList.add('hidden');
        fr.classList.remove('hidden');
        try { history.replaceState(null, '', '/login?mode=register'); } catch(e){}
    } else {
        _mode = 'login';
        fl.classList.remove('hidden');
        fr.classList.add('hidden');
        try { history.replaceState(null, '', '/login'); } catch(e){}
    }
    applyLoginLang();
}

// ═══ التحقق من تطابق كلمتي السر قبل الإرسال ═══
(function(){
    var form = document.getElementById('formRegister');
    if(!form) return;
    form.addEventListener('submit', function(e){
        var pw = document.getElementById('pwReg');
        var pwc = document.getElementById('pwRegConfirm');
        if(pwd || !pwc) return;
        if(pw.value !== pwc.value){
            e.preventDefault();
            var tr = _TRANS[_lang] || _TRANS['ar'];
            alert(tr.err_pw_mismatch || 'كلمتا السر غير متطابقتين');
            pwc.focus();
            return false;
        }
    });
})();
// ═══════════════════════════════════════════
// تغيير اللغة
// ═══════════════════════════════════════════
var _lang = localStorage.getItem('login_lang') || 'ar';

var _TRANS = {
    ar: {
        title_login: 'تسجيل الدخول',
        title_register: 'إنشاء حساب',
        label_user: 'اسم المستخدم',
        label_pw: 'كلمة السر',
        label_pw_confirm: 'تأكيد كلمة السر',
        label_avatar: 'الصورة الشخصية (اختياري)',
        ph_user_login: 'ادخل اسمك',
        ph_user_reg: 'اختر اسم مستخدم',
        ph_pw_login: '••••••••',
        ph_pw_reg: 'اختر كلمة سر قوية',
        ph_pw_confirm: 'أعد كتابة كلمة السر',
        btn_login: 'تسجيل الدخول',
        btn_register: 'إنشاء الحساب',
        switch_no_acc: 'ما عندك حساب؟',
        switch_has_acc: 'عندك حساب؟',
        switch_btn_reg: 'إنشاء حساب',
        switch_btn_login: 'تسجيل دخول',
        err_pw_mismatch: 'كلمتا السر غير متطابقتين',
        forgot_pw: 'نسيت كلمة السر؟',
        import_acc: 'استيراد حساب موجود',
        logo_name: 'المطري OTP',
        lang_label: 'EN'
    },
    en: {
        title_login: 'Login',
        title_register: 'Create Account',
        label_user: 'Username',
        label_pw: 'Password',
        label_pw_confirm: 'Confirm Password',
        label_avatar: 'Profile Picture (optional)',
        ph_user_login: 'Enter your username',
        ph_user_reg: 'Choose a username',
        ph_pw_login: '••••••••',
        ph_pw_reg: 'Choose a strong password',
        ph_pw_confirm: 'Re-enter password',
        btn_login: 'Sign In',
        btn_register: 'Create Account',
        switch_no_acc: "Don't have an account?",
        switch_has_acc: 'Have an account?',
        switch_btn_reg: 'Sign Up',
        switch_btn_login: 'Sign In',
        err_pw_mismatch: 'Passwords do not match',
        forgot_pw: 'Forgot password?',
        import_acc: 'Import existing account',
        logo_name: 'AlMatari OTP',
        lang_label: 'AR'
    }
};

var _mode = '{{ mode }}';

function toggleLangPage(){
    _lang = _lang === 'ar' ? 'en' : 'ar';
    try { localStorage.setItem('login_lang', _lang); } catch(e){}
    applyLoginLang();
}

function applyLoginLang(){
    var tr = _TRANS[_lang];
    if(!tr) return;
    // الاتجاه
    document.documentElement.lang = _lang;
    document.documentElement.dir = _lang === 'ar' ? 'rtl' : 'ltr';
    document.body.dir = _lang === 'ar' ? 'rtl' : 'ltr';
    // العنوان الرئيسي
    var pt = document.getElementById('pageTitle');
    if(pt) pt.textContent = _mode === 'login' ? tr.title_login : tr.title_register;
    // نصوص التبديل
    var sb = document.getElementById('switchBtn');
    var st = document.getElementById('switchText');
    if(sb && st){
        if(_mode === 'login'){
            st.textContent = tr.switch_no_acc;
            sb.textContent = tr.switch_btn_reg;
        } else {
            st.textContent = tr.switch_has_acc;
            sb.textContent = tr.switch_btn_login;
        }
    }
    // زر اللغة
    var lb = document.getElementById('langBtn');
    if(lb) lb.textContent = tr.lang_label;
    // اسم الشعار (شريط علوي + تذييل)
    var mn = document.querySelector('.mini-name');
    if(mn) mn.textContent = tr.logo_name;
    var lf = document.querySelector('.logo-foot');
    if(lf && lf.lastChild && lf.lastChild.nodeType === 3){
        lf.lastChild.textContent = ' ' + tr.logo_name;
    }
    // data-i18n
    document.querySelectorAll('[data-i18n]').forEach(function(el){
        var key = el.dataset.i18n;
        if(tr[key]) el.textContent = tr[key];
    });
    // placeholder حقول الدخول
    var loginUser = document.querySelector('#formLogin input[name="username"]');
    var loginPw = document.querySelector('#formLogin input[name="password"]');
    if(loginUser) loginUser.placeholder = tr.ph_user_login;
    if(loginPw) loginPw.placeholder = tr.ph_pw_login;
    // placeholder حقول التسجيل
    var regUser = document.querySelector('#formRegister input[name="username"]');
    var regPw = document.querySelector('#formRegister input[name="password"]');
    var regPwC = document.getElementById('pwRegConfirm');
    if(regUser) regUser.placeholder = tr.ph_user_reg;
    if(regPw) regPw.placeholder = tr.ph_pw_reg;
    if(regPwC) regPwC.placeholder = tr.ph_pw_confirm;
    // روابط أسفل النموذج
    var fl = document.getElementById('forgotLink');
    if(fl) fl.textContent = tr.forgot_pw;
    var il = document.getElementById('importLink');
    if(il) il.textContent = tr.import_acc;
}

// نطبق اللغة عند التحميل
document.addEventListener('DOMContentLoaded', function(){
    // اقرأ الوضع من الحقل المخفي (mode من السيرفر)
    var mh = document.getElementById('modeHidden');
    if(mh && mh.value === 'register'){
        _mode = 'register';
        var fl = document.getElementById('formLogin');
        var fr = document.getElementById('formRegister');
        if(fl) fl.classList.add('hidden');
        if(fr) fr.classList.remove('hidden');
    }
    // اقرأ اللغة المحفوظة وطبّقها
    try {
        var saved = localStorage.getItem('login_lang');
        if(saved === 'en' || saved === 'ar') _lang = saved;
    } catch(e){}
    applyLoginLang();
});

// معاينة صورة التسجيل — تظهر في الرأس
function previewRegAvatar(event){
    var file = event.target.files[0];
    if(!file) return;
    var url = URL.createObjectURL(file);
    var img = document.getElementById('avatarTopImg');
    var svg = document.getElementById('avatarTopSvg');
    if(img){
        img.src = url;
        img.style.display = 'block';
        img.style.width = '100%';
        img.style.height = '100%';
        img.style.objectFit = 'cover';
        img.style.borderRadius = '50%';
    }
    if(svg){ svg.style.display = 'none'; }
}

function togglePw(inputId, btn){
    var inp = document.getElementById(inputId);
    if(!inp) return;
    if(inp.type === 'password'){
        inp.type = 'text';
        btn.innerHTML = '<svg viewBox="0 0 24 24"><path d="M12 7c2.76 0 5 2.24 5 5 0 .65-.13 1.26-.36 1.83l2.92 2.92c1.51-1.26 2.7-2.89 3.43-4.75-1.73-4.39-6-7.5-11-7.5-1.4 0-2.74.25-3.98.7l2.16 2.16C10.74 7.13 11.35 7 12 7zM2 4.27l2.28 2.28.46.46C3.08 8.3 1.78 10.02 1 12c1.73 4.39 6 7.5 11 7.5 1.55 0 3.03-.3 4.38-.84l.42.42L19.73 22 21 20.73 3.27 3 2 4.27zM7.53 9.8l1.55 1.55c-.05.21-.08.43-.08.65 0 1.66 1.34 3 3 3 .22 0 .44-.03.65-.08l1.55 1.55c-.67.33-1.41.53-2.2.53-2.76 0-5-2.24-5-5 0-.79.2-1.53.53-2.2zm4.31-.78l3.15 3.15.02-.16c0-1.66-1.34-3-3-3l-.17.01z"/></svg>';
    } else {
        inp.type = 'password';
        btn.innerHTML = '<svg viewBox="0 0 24 24"><path d="M12 4.5C7 4.5 2.73 7.61 1 12c1.73 4.39 6 7.5 11 7.5s9.27-3.11 11-7.5c-1.73-4.39-6-7.5-11-7.5zM12 17c-2.76 0-5-2.24-5-5s2.24-5 5-5 5 2.24 5 5-2.24 5-5 5zm0-8c-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3-1.34-3-3-3z"/></svg>';
    }
}
</script>

</body>
</html>"""

FORGOT_HTML = r"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<meta name="theme-color" content="#7b2ff7">
<title>نسيت كلمة السر</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;font-family:-apple-system,'Segoe UI',Tahoma,sans-serif;-webkit-tap-highlight-color:transparent}
html,body{height:100%;overflow:hidden}
body{background:#0a0a18;color:#fff;display:flex;align-items:center;justify-content:center;padding:20px;position:relative;min-height:100vh}
.bg{position:fixed;inset:0;z-index:0;pointer-events:none;overflow:hidden}
.bg::before{content:"";position:absolute;width:500px;height:500px;background:radial-gradient(circle,rgba(123,47,247,.35),transparent 70%);top:-150px;right:-100px;border-radius:50%;filter:blur(40px)}
.bg::after{content:"";position:absolute;width:450px;height:450px;background:radial-gradient(circle,rgba(0,212,255,.25),transparent 70%);bottom:-120px;left:-100px;border-radius:50%;filter:blur(40px)}
.wrap{position:relative;z-index:2;width:100%;max-width:400px}
.card{background:linear-gradient(160deg,#161628,#0f0f1e);border:1px solid rgba(123,47,247,.2);border-radius:28px;padding:32px 26px;box-shadow:0 20px 60px rgba(0,0,0,.5)}
.icon-box{width:80px;height:80px;margin:0 auto 18px;border-radius:50%;background:linear-gradient(135deg,#7b2ff7,#00d4ff);display:flex;align-items:center;justify-content:center;box-shadow:0 8px 30px rgba(123,47,247,.5)}
.icon-box svg{width:40px;height:40px;fill:#fff}
.title{text-align:center;font-size:22px;font-weight:900;margin-bottom:10px;background:linear-gradient(135deg,#fff,#a8d8ff);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.subtitle{text-align:center;font-size:12px;color:#8e8eab;margin-bottom:24px;line-height:1.6}
.field{margin-bottom:16px}
.field label{display:block;font-size:13px;color:#a8a8bd;margin-bottom:8px;font-weight:600}
.field-in{position:relative}
.field-in svg{position:absolute;right:16px;top:50%;transform:translateY(-50%);width:20px;height:20px;fill:#6e6e8a;pointer-events:none}
.field-in input{width:100%;padding:15px 48px 15px 16px;border:1.5px solid rgba(123,47,247,.15);border-radius:14px;background:rgba(0,0,0,.4);color:#fff;font-size:15px;outline:none;font-family:inherit}
.field-in input:focus{border-color:#7b2ff7;background:rgba(123,47,247,.06);box-shadow:0 0 0 4px rgba(123,47,247,.12)}
.btn{width:100%;padding:16px;border:none;border-radius:14px;background:linear-gradient(135deg,#7b2ff7,#00d4ff);color:#fff;font-weight:800;font-size:16px;cursor:pointer;font-family:inherit;box-shadow:0 10px 30px rgba(123,47,247,.4);margin-top:6px;letter-spacing:.5px}
.btn:active{transform:scale(.98)}
.err{background:rgba(233,69,96,.15);border:1px solid rgba(233,69,96,.4);color:#ff8aa3;padding:12px;border-radius:12px;font-size:13px;text-align:center;margin-bottom:16px;font-weight:600}
.ok{background:rgba(0,184,148,.15);border:1px solid rgba(0,184,148,.4);color:#6fe3c1;padding:12px;border-radius:12px;font-size:13px;text-align:center;margin-bottom:16px;font-weight:600}
.pw-box{background:linear-gradient(135deg,#0c1e3e,#1e3a8a);border:2px dashed rgba(0,212,255,.5);border-radius:16px;padding:20px;text-align:center;margin:16px 0}
.pw-label{font-size:11px;color:#8ee4ff;margin-bottom:8px;letter-spacing:1px}
.pw-value{font-size:24px;font-weight:900;color:#fff;letter-spacing:3px;font-family:monospace;direction:ltr;user-select:all}
.pw-hint{font-size:11px;color:#8e8eab;margin-top:10px;line-height:1.5}
.back-link{display:block;text-align:center;margin-top:18px;font-size:13px;color:#00d4ff;text-decoration:none;font-weight:700;padding:10px;border-radius:10px}
.back-link:hover,.back-link:active{background:rgba(0,212,255,.08)}
</style>
</head>
<body>

<div class="bg"></div>

<div class="wrap">
<div class="card">

<div class="icon-box">
<svg viewBox="0 0 24 24"><path d="M18 8h-1V6c0-2.76-2.24-5-5-5S7 3.24 7 6v2H6c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V10c0-1.1-.9-2-2-2zm-6 9c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2zm3.1-9H8.9V6c0-1.71 1.39-3.1 3.1-3.1 1.71 0 3.1 1.39 3.1 3.1v2z"/></svg>
</div>

<div class="title">نسيت كلمة السر؟</div>
<div class="subtitle">اكتب اسم المستخدم وسنولّد لك كلمة سر جديدة</div>

{% if err %}
<div class="err">{{ err }}</div>
{% endif %}

{% if success %}
<div class="ok">{{ success }}</div>
<div class="pw-box">
<div class="pw-label"><svg viewBox="0 0 24 24" style="width:14px;height:14px;fill:#8ee4ff;vertical-align:middle;margin-left:4px"><path d="M12.65 10C11.83 7.67 9.61 6 7 6c-3.31 0-6 2.69-6 6s2.69 6 6 6c2.61 0 4.83-1.67 5.65-4H17v4h4v-4h2v-4H12.65zM7 14c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2z"/></svg> كلمة السر الجديدة</div>
<div class="pw-value">{{ new_pw }}</div>
<div class="pw-hint">انسخها الآن واحفظها في مكان آمن<br>لن تظهر مرة أخرى</div>
</div>
{% else %}
<form method="POST">
<input type="hidden" name="action" value="reset">
<div class="field">
<label>اسم المستخدم</label>
<div class="field-in">
<input type="text" name="username" placeholder="ادخل اسمك" required autocomplete="username" autofocus>
<svg viewBox="0 0 24 24"><path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/></svg>
</div>
</div>
<button type="submit" class="btn">إعادة تعيين كلمة السر</button>
</form>
{% endif %}

<a href="/login" class="back-link">← رجوع لتسجيل الدخول</a>

</div>
</div>

</body>
</html>"""

import datetime as _datetime_module
app.permanent_session_lifetime = _datetime_module.timedelta(days=7)

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated

LOGIN_FILE = os.path.join(_PERSIST_DIR, "login_attempts.json")

def _load_attempts():
    if os.path.exists(LOGIN_FILE):
        try:
            with open(LOGIN_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}

def _save_attempts(d):
    with open(LOGIN_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    ip = request.remote_addr or "unknown"
    attempts = _load_attempts()
    now = time.time()

    # تحقق من الحظر
    if ip in attempts:
        data = attempts[ip]
        if data.get("blocked_until", 0) > now:
            wait = int((data["blocked_until"] - now) / 60) + 1
            return f"""<body style="background:#0a0a12;display:flex;justify-content:center;align-items:center;height:100vh;font-family:sans-serif;flex-direction:column;gap:20px;color:#fff">
            <h2 style="color:#e94560">🔒 محظور مؤقتاً</h2>
            <p style="color:#8e8e93">حاول مرة ثانية بعد {wait} دقيقة</p>
            </body>"""
        # انتهى الحظر، احذف السجل
        if now > data.get("blocked_until", 0):
            del attempts[ip]
            _save_attempts(attempts)

    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            # نجح → احذف المحاولات
            if ip in attempts:
                del attempts[ip]
                _save_attempts(attempts)
            session["admin_logged"] = True
            return redirect(url_for("admin_panel"))

        # فشل → سجّل المحاولة
        if ip not in attempts:
            attempts[ip] = {"count": 0, "blocked_until": 0, "last": now}
        attempts[ip]["count"] = attempts[ip].get("count", 0) + 1
        attempts[ip]["last"] = now
        count = attempts[ip]["count"]

        # 5 محاولات → حظر 15 دقيقة
        if count >= 5:
            attempts[ip]["blocked_until"] = now + (15 * 60)
            attempts[ip]["count"] = 0
            _save_attempts(attempts)
            return f"""<body style="background:#0a0a12;display:flex;justify-content:center;align-items:center;height:100vh;font-family:sans-serif;flex-direction:column;gap:20px;color:#fff">
            <h2 style="color:#e94560">تم الحظر</h2>
            <p style="color:#8e8e93">5 محاولات خاطئة — محظور 15 دقيقة</p>
            </body>"""

        _save_attempts(attempts)
        remaining = 5 - count
        return f"""<body style="background:#0a0a12;display:flex;justify-content:center;align-items:center;height:100vh;font-family:sans-serif;flex-direction:column;gap:20px;color:#fff">
        <h2 style="color:#e94560">كلمة السر غلط</h2>
        <p style="color:#ffcb6b">باقي {remaining} محاولات</p>
        <a href="/admin/login" style="color:#0ea5e9;text-decoration:none;padding:12px 30px;background:#1e3a8a;border-radius:10px">حاول مرة ثانية</a>
        </body>"""
    return """<body style="background:linear-gradient(135deg,#0a0a12,#1a1a2e);display:flex;justify-content:center;align-items:center;height:100vh;font-family:sans-serif;margin:0">
    <form method="POST" style="background:#16161f;padding:40px;border-radius:20px;text-align:center;border:1px solid #2a2a35;box-shadow:0 10px 40px rgba(0,0,0,0.5)">
    <div style="font-size:48px;margin-bottom:20px"></div>
    <h2 style="color:#0ea5e9;margin-bottom:30px;font-weight:700">لوحة الأدمن</h2>
    <input type="password" name="password" placeholder="كلمة السر" style="padding:16px;border-radius:12px;border:1px solid #2a2a35;background:#0a0a12;color:#fff;width:260px;text-align:center;font-size:16px;outline:none">
    <br><br>
    <button style="padding:16px 60px;background:linear-gradient(135deg,#1e3a8a,#0ea5e9);color:#fff;border:none;border-radius:12px;font-weight:bold;cursor:pointer;font-size:15px;width:100%">دخول</button>
    </form></body>"""

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged", None)
    return redirect(url_for("admin_login"))

@app.template_filter('timestamp')
def timestamp_filter(ts):
    from datetime import datetime
    try:
        return datetime.fromtimestamp(float(ts)).strftime('%H:%M')
    except:
        return ''

app.secret_key = "otp-secret-2025"

NUMBERS_FILE = os.path.join(_PERSIST_DIR, "numbers.txt")
SETTINGS_FILE = os.path.join(_PERSIST_DIR, "settings.json")
TICKETS_FILE = os.path.join(_PERSIST_DIR, "tickets.json")
UPLOAD_FOLDER = os.path.join(_PERSIST_DIR, "uploads")
import os as _os
_os.makedirs(UPLOAD_FOLDER, exist_ok=True)

DEFAULT_SETTINGS = {
    "maint_icon": "engineer",
    "maint_color": "gold",
    "site_name": "أرقام OTP",
    "site_name_en": "OTP Numbers",
    "support_url": "https://wa.me/967xxxxxxxxx",
    "primary_color": "#1e3a8a",
    "secondary_color": "#0ea5e9",
    "telegram_token": "",
    "telegram_chat_id": "",
    "notice_title": "",
    "notice_body": "",
    "notice_type": "info",
    "notice_expire": "",
    "notice_id": "",
    "maintenance_on": False,
    "maintenance_title": "الموقع تحت الصيانة",
    "maintenance_body": "نعتذر عن الإزعاج، سنعود قريباً بعد انتهاء التحديث"
}

# ============================================================
# 190 دولة + أعلام SVG
# ============================================================
COUNTRIES = {
    "+93": {"ar": "أفغانستان", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="1" height="2" fill="#000"/><rect x="1" width="1" height="2" fill="#D32011"/><rect x="2" width="1" height="2" fill="#007A36"/></svg>'},
    "+355": {"ar": "ألبانيا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="2" fill="#E41E20"/></svg>'},
    "+213": {"ar": "الجزائر", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="1.5" height="2" fill="#006233"/><rect x="1.5" width="1.5" height="2" fill="#fff"/><circle cx="1.5" cy="1" r="0.4" fill="#D21034"/><circle cx="1.65" cy="1" r="0.35" fill="#fff"/></svg>'},
    "+376": {"ar": "أندورا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="1" height="2" fill="#10069F"/><rect x="1" width="1" height="2" fill="#FEDD00"/><rect x="2" width="1" height="2" fill="#D50032"/></svg>'},
    "+244": {"ar": "أنغولا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="1" fill="#CE1126"/><rect y="1" width="3" height="1" fill="#000"/></svg>'},
    "+54": {"ar": "الأرجنتين", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="0.67" fill="#74ACDF"/><rect y="0.67" width="3" height="0.67" fill="#fff"/><rect y="1.33" width="3" height="0.67" fill="#74ACDF"/></svg>'},
    "+374": {"ar": "أرمينيا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="0.67" fill="#D90012"/><rect y="0.67" width="3" height="0.67" fill="#0033A0"/><rect y="1.33" width="3" height="0.67" fill="#F2A800"/></svg>'},
    "+61": {"ar": "أستراليا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="2" fill="#00247D"/><path d="M0,0 L1.5,1 M1.5,0 L0,1" stroke="#fff" stroke-width="0.1"/></svg>'},
    "+43": {"ar": "النمسا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="0.67" fill="#ED2939"/><rect y="0.67" width="3" height="0.67" fill="#fff"/><rect y="1.33" width="3" height="0.67" fill="#ED2939"/></svg>'},
    "+994": {"ar": "أذربيجان", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="0.67" fill="#0092BC"/><rect y="0.67" width="3" height="0.67" fill="#E4002B"/><rect y="1.33" width="3" height="0.67" fill="#00AE65"/></svg>'},
    "+973": {"ar": "البحرين", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="2" fill="#CE1126"/><path d="M0,0 L0.7,0.13 L0.5,0.25 L0.7,0.38 L0.5,0.5 L0.7,0.63 L0.5,0.75 L0.7,0.88 L0.5,1 L0.7,1.13 L0.5,1.25 L0.7,1.38 L0.5,1.5 L0.7,1.63 L0.5,1.75 L0.7,1.88 L0.5,2 L0,2 Z" fill="#fff"/></svg>'},
    "+880": {"ar": "بنغلاديش", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="2" fill="#006A4E"/><circle cx="1.2" cy="1" r="0.5" fill="#F42A41"/></svg>'},
    "+375": {"ar": "بيلاروسيا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="2" fill="#C8313E"/><rect y="0.67" width="3" height="0.66" fill="#4AA657"/><rect width="0.8" height="2" fill="#fff"/></svg>'},
    "+32": {"ar": "بلجيكا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="1" height="2" fill="#000"/><rect x="1" width="1" height="2" fill="#FDDA24"/><rect x="2" width="1" height="2" fill="#EF3340"/></svg>'},
    "+591": {"ar": "بوليفيا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="0.67" fill="#D52B1E"/><rect y="0.67" width="3" height="0.67" fill="#F9E300"/><rect y="1.33" width="3" height="0.67" fill="#007934"/></svg>'},
    "+387": {"ar": "البوسنة", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="2" fill="#002F6C"/><path d="M0,0 L3,0 L0,2 Z" fill="#FECB00"/></svg>'},
    "+55": {"ar": "البرازيل", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="2" fill="#009C3B"/><path d="M1.5,0.2 L2.7,1 L1.5,1.8 L0.3,1 Z" fill="#FFDF00"/><circle cx="1.5" cy="1" r="0.4" fill="#002776"/></svg>'},
    "+673": {"ar": "بروناي", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="2" fill="#F7E017"/></svg>'},
    "+359": {"ar": "بلغاريا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="0.67" fill="#fff"/><rect y="0.67" width="3" height="0.67" fill="#00966E"/><rect y="1.33" width="3" height="0.67" fill="#D62612"/></svg>'},
    "+855": {"ar": "كمبوديا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="0.5" fill="#032EA1"/><rect y="0.5" width="3" height="1" fill="#E00025"/><rect y="1.5" width="3" height="0.5" fill="#032EA1"/></svg>'},
    "+237": {"ar": "الكاميرون", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="1" height="2" fill="#007A5E"/><rect x="1" width="1" height="2" fill="#CE1126"/><rect x="2" width="1" height="2" fill="#FCD116"/></svg>'},
    "+1": {"ar": "كندا/أمريكا", "flag": '<svg viewBox="0 0 19 10" width="24" height="16"><rect width="19" height="10" fill="#fff"/><g fill="#b22234"><rect width="19" height="1"/><rect y="2" width="19" height="1"/><rect y="4" width="19" height="1"/><rect y="6" width="19" height="1"/><rect y="8" width="19" height="1"/></g><rect width="8" height="5" fill="#3c3b6e"/></svg>'},
    "+56": {"ar": "تشيلي", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="1" fill="#fff"/><rect y="1" width="3" height="1" fill="#D52B1E"/><rect width="1" height="1" fill="#0039A6"/></svg>'},
    "+86": {"ar": "الصين", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="2" fill="#DE2910"/><path d="M0.5,0.3 L0.6,0.55 L0.85,0.55 L0.65,0.7 L0.72,0.95 L0.5,0.8 L0.28,0.95 L0.35,0.7 L0.15,0.55 L0.4,0.55 Z" fill="#FFDE00"/></svg>'},
    "+57": {"ar": "كولومبيا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="1" fill="#FCD116"/><rect y="1" width="3" height="0.5" fill="#003893"/><rect y="1.5" width="3" height="0.5" fill="#CE1126"/></svg>'},
    "+506": {"ar": "كوستاريكا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="0.34" fill="#002B7F"/><rect y="0.34" width="3" height="0.34" fill="#fff"/><rect y="0.68" width="3" height="0.64" fill="#CE1126"/><rect y="1.32" width="3" height="0.34" fill="#fff"/><rect y="1.66" width="3" height="0.34" fill="#002B7F"/></svg>'},
    "+385": {"ar": "كرواتيا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="0.67" fill="#FF0000"/><rect y="0.67" width="3" height="0.67" fill="#fff"/><rect y="1.33" width="3" height="0.67" fill="#171796"/></svg>'},
    "+53": {"ar": "كوبا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="2" fill="#002A8F"/><g fill="#fff"><rect y="0.4" width="3" height="0.4"/><rect y="1.2" width="3" height="0.4"/></g><path d="M0,0 L1,1 L0,2 Z" fill="#CF142B"/></svg>'},
    "+357": {"ar": "قبرص", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="2" fill="#fff"/></svg>'},
    "+420": {"ar": "التشيك", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="1" fill="#fff"/><rect y="1" width="3" height="1" fill="#D7141A"/><path d="M0,0 L1.5,1 L0,2 Z" fill="#11457E"/></svg>'},
    "+45": {"ar": "الدنمارك", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="2" fill="#C60C30"/><rect x="0.9" width="0.3" height="2" fill="#fff"/><rect y="0.85" width="3" height="0.3" fill="#fff"/></svg>'},
    "+20": {"ar": "مصر", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="2" fill="#fff"/><rect width="3" height="0.67" fill="#CE1126"/><rect y="1.33" width="3" height="0.67" fill="#000"/></svg>'},
    "+372": {"ar": "إستونيا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="0.67" fill="#0072CE"/><rect y="0.67" width="3" height="0.67" fill="#000"/><rect y="1.33" width="3" height="0.67" fill="#fff"/></svg>'},
    "+251": {"ar": "إثيوبيا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="0.67" fill="#078930"/><rect y="0.67" width="3" height="0.67" fill="#FCDD09"/><rect y="1.33" width="3" height="0.67" fill="#DA121A"/><circle cx="1.5" cy="1" r="0.3" fill="#0F47AF"/></svg>'},
    "+358": {"ar": "فنلندا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="2" fill="#fff"/><rect x="0.9" width="0.4" height="2" fill="#003580"/><rect y="0.8" width="3" height="0.4" fill="#003580"/></svg>'},
    "+33": {"ar": "فرنسا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="1" height="2" fill="#002395"/><rect x="1" width="1" height="2" fill="#fff"/><rect x="2" width="1" height="2" fill="#ED2939"/></svg>'},
    "+995": {"ar": "جورجيا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="2" fill="#fff"/><rect x="1.3" width="0.4" height="2" fill="#FF0000"/><rect y="0.8" width="3" height="0.4" fill="#FF0000"/></svg>'},
    "+49": {"ar": "ألمانيا", "flag": '<svg viewBox="0 0 5 3" width="24" height="16"><rect width="5" height="1" fill="#000"/><rect y="1" width="5" height="1" fill="#D00"/><rect y="2" width="5" height="1" fill="#FFCE00"/></svg>'},
    "+30": {"ar": "اليونان", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="2" fill="#fff"/><g fill="#0D5EAF"><rect width="3" height="0.22"/><rect y="0.44" width="3" height="0.22"/><rect y="0.88" width="3" height="0.22"/><rect y="1.33" width="3" height="0.22"/><rect y="1.77" width="3" height="0.22"/></g><rect width="1.1" height="1.1" fill="#0D5EAF"/><path d="M0.55,0 V1.1 M0,0.55 H1.1" stroke="#fff" stroke-width="0.22"/></svg>'},
    "+36": {"ar": "هنغاريا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="0.67" fill="#CE2939"/><rect y="0.67" width="3" height="0.67" fill="#fff"/><rect y="1.33" width="3" height="0.67" fill="#477050"/></svg>'},
    "+354": {"ar": "آيسلندا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="2" fill="#02529C"/><rect x="0.8" width="0.4" height="2" fill="#fff"/><rect y="0.8" width="3" height="0.4" fill="#fff"/><rect x="0.9" width="0.2" height="2" fill="#DC1E35"/><rect y="0.9" width="3" height="0.2" fill="#DC1E35"/></svg>'},
    "+91": {"ar": "الهند", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="0.67" fill="#FF9933"/><rect y="0.67" width="3" height="0.67" fill="#fff"/><rect y="1.33" width="3" height="0.67" fill="#138808"/></svg>'},
    "+62": {"ar": "إندونيسيا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="1" fill="#FF0000"/><rect y="1" width="3" height="1" fill="#fff"/></svg>'},
    "+98": {"ar": "إيران", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="0.67" fill="#239F40"/><rect y="0.67" width="3" height="0.67" fill="#fff"/><rect y="1.33" width="3" height="0.67" fill="#DA0000"/></svg>'},
    "+964": {"ar": "العراق", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="0.67" fill="#CE1126"/><rect y="0.67" width="3" height="0.67" fill="#fff"/><rect y="1.33" width="3" height="0.67" fill="#000"/></svg>'},
    "+353": {"ar": "أيرلندا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="1" height="2" fill="#169B62"/><rect x="1" width="1" height="2" fill="#fff"/><rect x="2" width="1" height="2" fill="#FF883E"/></svg>'},
    "+39": {"ar": "إيطاليا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="1" height="2" fill="#009246"/><rect x="1" width="1" height="2" fill="#fff"/><rect x="2" width="1" height="2" fill="#CE2B37"/></svg>'},
    "+81": {"ar": "اليابان", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="2" fill="#fff"/><circle cx="1.5" cy="1" r="0.5" fill="#BC002D"/></svg>'},
    "+962": {"ar": "الأردن", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="2" fill="#fff"/><rect width="3" height="0.67" fill="#000"/><rect y="1.33" width="3" height="0.67" fill="#007A3D"/><path d="M0,0 L1,1 L0,2 Z" fill="#CE1126"/></svg>'},
    "+7": {"ar": "روسيا", "flag": '<svg viewBox="0 0 9 6" width="24" height="16"><rect width="9" height="2" fill="#fff"/><rect y="2" width="9" height="2" fill="#0039a6"/><rect y="4" width="9" height="2" fill="#d52b1e"/></svg>'},
    "+254": {"ar": "كينيا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="0.67" fill="#000"/><rect y="0.67" width="3" height="0.67" fill="#fff"/><rect y="1.33" width="3" height="0.67" fill="#006600"/><rect x="1.3" width="0.4" height="2" fill="#BB0000"/></svg>'},
    "+965": {"ar": "الكويت", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="0.67" fill="#007A3D"/><rect y="0.67" width="3" height="0.67" fill="#fff"/><rect y="1.33" width="3" height="0.67" fill="#CE1126"/><rect width="0.6" height="2" fill="#000"/></svg>'},
    "+856": {"ar": "لاوس", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="0.5" fill="#CE1126"/><rect y="0.5" width="3" height="1" fill="#002868"/><rect y="1.5" width="3" height="0.5" fill="#CE1126"/><circle cx="1.5" cy="1" r="0.25" fill="#fff"/></svg>'},
    "+371": {"ar": "لاتفيا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="2" fill="#9E3039"/><rect y="0.8" width="3" height="0.4" fill="#fff"/></svg>'},
    "+961": {"ar": "لبنان", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="2" fill="#fff"/><rect width="3" height="0.5" fill="#ED1C24"/><rect y="1.5" width="3" height="0.5" fill="#ED1C24"/></svg>'},
    "+218": {"ar": "ليبيا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="2" fill="#239E46"/><rect y="0.5" width="3" height="1" fill="#000"/><rect y="1.5" width="3" height="0.5" fill="#fff"/></svg>'},
    "+370": {"ar": "ليتوانيا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="0.67" fill="#FDB913"/><rect y="0.67" width="3" height="0.67" fill="#006A44"/><rect y="1.33" width="3" height="0.67" fill="#C1272D"/></svg>'},
    "+352": {"ar": "لوكسمبورغ", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="0.67" fill="#EF3340"/><rect y="0.67" width="3" height="0.67" fill="#fff"/><rect y="1.33" width="3" height="0.67" fill="#00A3E0"/></svg>'},
    "+60": {"ar": "ماليزيا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="2" fill="#CC0001"/><g fill="#fff"><rect width="3" height="0.14"/><rect y="0.29" width="3" height="0.14"/><rect y="0.57" width="3" height="0.14"/><rect y="0.86" width="3" height="0.14"/><rect y="1.14" width="3" height="0.14"/><rect y="1.43" width="3" height="0.14"/><rect y="1.71" width="3" height="0.14"/></g><rect width="1.5" height="1" fill="#010066"/></svg>'},
    "+960": {"ar": "المالديف", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="2" fill="#D21034"/><rect x="0.6" y="0.6" width="1.8" height="0.8" fill="#007E3A"/></svg>'},
    "+356": {"ar": "مالطا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="1.5" height="2" fill="#fff"/><rect x="1.5" width="1.5" height="2" fill="#CF142B"/></svg>'},
    "+52": {"ar": "المكسيك", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="1" height="2" fill="#006847"/><rect x="1" width="1" height="2" fill="#fff"/><rect x="2" width="1" height="2" fill="#CE1126"/></svg>'},
    "+373": {"ar": "مولدوفا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="1" height="2" fill="#003DA5"/><rect x="1" width="1" height="2" fill="#FFD100"/><rect x="2" width="1" height="2" fill="#C8102E"/></svg>'},
    "+377": {"ar": "موناكو", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="1" fill="#CE1126"/><rect y="1" width="3" height="1" fill="#fff"/></svg>'},
    "+976": {"ar": "منغوليا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="1" height="2" fill="#C4272F"/><rect x="1" width="1" height="2" fill="#015197"/><rect x="2" width="1" height="2" fill="#C4272F"/></svg>'},
    "+212": {"ar": "المغرب", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="2" fill="#C1272D"/></svg>'},
    "+95": {"ar": "ميانمار", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="0.67" fill="#FECB00"/><rect y="0.67" width="3" height="0.67" fill="#34B233"/><rect y="1.33" width="3" height="0.67" fill="#EA2839"/></svg>'},
    "+977": {"ar": "نيبال", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><path d="M0.5,0 L1.8,1 L0.8,1 L1.8,2 L0.5,2 Z" fill="#DC143C"/></svg>'},
    "+31": {"ar": "هولندا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="0.67" fill="#AE1C28"/><rect y="0.67" width="3" height="0.67" fill="#fff"/><rect y="1.33" width="3" height="0.67" fill="#21468B"/></svg>'},
    "+64": {"ar": "نيوزيلندا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="2" fill="#00247D"/><path d="M0,0 L1.5,1 M1.5,0 L0,1" stroke="#fff" stroke-width="0.1"/></svg>'},
    "+234": {"ar": "نيجيريا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="1" height="2" fill="#008751"/><rect x="1" width="1" height="2" fill="#fff"/><rect x="2" width="1" height="2" fill="#008751"/></svg>'},
    "+47": {"ar": "النرويج", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="2" fill="#BA0C2F"/><rect x="0.8" width="0.5" height="2" fill="#fff"/><rect y="0.75" width="3" height="0.5" fill="#fff"/><rect x="0.9" width="0.3" height="2" fill="#00205B"/><rect y="0.85" width="3" height="0.3" fill="#00205B"/></svg>'},
    "+968": {"ar": "عُمان", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="0.67" fill="#fff"/><rect y="0.67" width="3" height="0.67" fill="#f00"/><rect y="1.33" width="3" height="0.67" fill="#008000"/><rect width="0.75" height="2" fill="#f00"/></svg>'},
    "+92": {"ar": "باكستان", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="2" fill="#01411C"/><rect width="0.75" height="2" fill="#fff"/></svg>'},
    "+970": {"ar": "فلسطين", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="0.67" fill="#000"/><rect y="0.67" width="3" height="0.67" fill="#fff"/><rect y="1.33" width="3" height="0.67" fill="#007A3D"/><path d="M0,0 L0.9,1 L0,2 Z" fill="#CE1126"/></svg>'},
    "+51": {"ar": "بيرو", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="1" height="2" fill="#D91023"/><rect x="1" width="1" height="2" fill="#fff"/><rect x="2" width="1" height="2" fill="#D91023"/></svg>'},
    "+63": {"ar": "الفلبين", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="1" fill="#0038A8"/><rect y="1" width="3" height="1" fill="#CE1126"/><path d="M0,0 L0.9,1 L0,2 Z" fill="#fff"/></svg>'},
    "+48": {"ar": "بولندا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="1" fill="#fff"/><rect y="1" width="3" height="1" fill="#DC143C"/></svg>'},
    "+351": {"ar": "البرتغال", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="2" fill="#DA291C"/><rect width="1.2" height="2" fill="#046A38"/><circle cx="1.2" cy="1" r="0.35" fill="#FFD700"/></svg>'},
    "+974": {"ar": "قطر", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="2" fill="#8A1538"/><path d="M0.6,0 L1.1,0.1 L0.7,0.2 L1.1,0.3 L0.7,0.4 L1.1,0.5 L0.7,0.6 L1.1,0.7 L0.7,0.8 L1.1,0.9 L0.7,1 L1.1,1.1 L0.7,1.2 L1.1,1.3 L0.7,1.4 L1.1,1.5 L0.7,1.6 L1.1,1.7 L0.7,1.8 L1.1,1.9 L0.7,2 L0.6,2 Z" fill="#fff"/></svg>'},
    "+40": {"ar": "رومانيا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="1" height="2" fill="#002B7F"/><rect x="1" width="1" height="2" fill="#FCD116"/><rect x="2" width="1" height="2" fill="#CE1126"/></svg>'},
    "+966": {"ar": "السعودية", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="2" fill="#165d31"/></svg>'},
    "+381": {"ar": "صربيا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="0.67" fill="#C6363C"/><rect y="0.67" width="3" height="0.67" fill="#0C4076"/><rect y="1.33" width="3" height="0.67" fill="#fff"/></svg>'},
    "+65": {"ar": "سنغافورة", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="1" fill="#ED2939"/><rect y="1" width="3" height="1" fill="#fff"/><circle cx="0.5" cy="0.5" r="0.3" fill="#fff"/><circle cx="0.6" cy="0.5" r="0.25" fill="#ED2939"/></svg>'},
    "+421": {"ar": "سلوفاكيا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="0.67" fill="#fff"/><rect y="0.67" width="3" height="0.67" fill="#0B4EA2"/><rect y="1.33" width="3" height="0.67" fill="#EE1C25"/></svg>'},
    "+386": {"ar": "سلوفينيا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="0.67" fill="#fff"/><rect y="0.67" width="3" height="0.67" fill="#005DA4"/><rect y="1.33" width="3" height="0.67" fill="#ED1C24"/></svg>'},
    "+27": {"ar": "جنوب أفريقيا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="2" fill="#007A4D"/><path d="M0,0 L1.2,1 L0,2 Z" fill="#FFB612"/><path d="M0,0 L0.9,1 L0,2 Z" fill="#000"/></svg>'},
    "+82": {"ar": "كوريا الجنوبية", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="2" fill="#fff"/><circle cx="1.5" cy="1" r="0.4" fill="#CD2E3A"/><path d="M1.5,0.6 A0.4,0.4 0 0,1 1.5,1.4 A0.2,0.2 0 0,1 1.5,1 A0.2,0.2 0 0,0 1.5,0.6 Z" fill="#0047A0"/></svg>'},
    "+34": {"ar": "إسبانيا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="2" fill="#AA151B"/><rect y="0.5" width="3" height="1" fill="#F1BF00"/></svg>'},
    "+94": {"ar": "سريلانكا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="2" fill="#FF7900"/><rect width="0.4" height="2" fill="#00534E"/><rect x="0.4" width="0.4" height="2" fill="#FF7900"/><rect x="0.8" width="2.2" height="2" fill="#8D153A"/><rect x="0.8" y="0.3" width="2.2" height="1.4" fill="#FFB700"/></svg>'},
    "+249": {"ar": "السودان", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="0.67" fill="#D21034"/><rect y="0.67" width="3" height="0.67" fill="#fff"/><rect y="1.33" width="3" height="0.67" fill="#000"/><path d="M0,0 L0.8,1 L0,2 Z" fill="#007229"/></svg>'},
    "+46": {"ar": "السويد", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="2" fill="#006AA7"/><rect x="0.9" width="0.4" height="2" fill="#FECC00"/><rect y="0.8" width="3" height="0.4" fill="#FECC00"/></svg>'},
    "+41": {"ar": "سويسرا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="2" fill="#DA291C"/><rect x="1.3" y="0.5" width="0.4" height="1" fill="#fff"/><rect x="1" y="0.8" width="1" height="0.4" fill="#fff"/></svg>'},
    "+963": {"ar": "سوريا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="0.67" fill="#CE1126"/><rect y="0.67" width="3" height="0.67" fill="#fff"/><rect y="1.33" width="3" height="0.67" fill="#000"/></svg>'},
    "+886": {"ar": "تايوان", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="2" fill="#FE0000"/><rect width="1.5" height="1" fill="#000095"/></svg>'},
    "+992": {"ar": "طاجيكستان", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="0.5" fill="#CC0000"/><rect y="0.5" width="3" height="0.7" fill="#fff"/><rect y="1.2" width="3" height="0.8" fill="#006600"/></svg>'},
    "+255": {"ar": "تنزانيا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="2" fill="#1EB53A"/><path d="M0,0 L3,0 L0,2 Z" fill="#00A3DD"/><path d="M0,2 L3,0 L3,0.3 L0.3,2 Z" fill="#000"/><path d="M0,1.7 L2.7,0 L3,0 L0,2 Z" fill="#FCD116"/></svg>'},
    "+66": {"ar": "تايلاند", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="2" fill="#A51931"/><rect y="0.33" width="3" height="1.34" fill="#F4F5F8"/><rect y="0.67" width="3" height="0.66" fill="#2D2A4A"/></svg>'},
    "+216": {"ar": "تونس", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="2" fill="#E70013"/><circle cx="1.5" cy="1" r="0.5" fill="#fff"/><circle cx="1.6" cy="1" r="0.4" fill="#E70013"/></svg>'},
    "+90": {"ar": "تركيا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="2" fill="#E30A17"/><circle cx="1.2" cy="1" r="0.5" fill="#fff"/><circle cx="1.35" cy="1" r="0.4" fill="#E30A17"/></svg>'},
    "+380": {"ar": "أوكرانيا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="1" fill="#0057B7"/><rect y="1" width="3" height="1" fill="#FFDD00"/></svg>'},
    "+971": {"ar": "الإمارات", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="2" fill="#fff"/><rect width="3" height="0.67" fill="#00732f"/><rect y="1.33" width="3" height="0.67" fill="#000"/><rect width="0.75" height="2" fill="#f00"/></svg>'},
    "+44": {"ar": "بريطانيا", "flag": '<svg viewBox="0 0 60 30" width="24" height="16"><rect width="60" height="30" fill="#012169"/><path d="M0,0 L60,30 M60,0 L0,30" stroke="#fff" stroke-width="6"/><path d="M30,0 V30 M0,15 H60" stroke="#fff" stroke-width="10"/><path d="M30,0 V30 M0,15 H60" stroke="#C8102E" stroke-width="6"/></svg>'},
    "+1": {"ar": "أمريكا", "flag": '<svg viewBox="0 0 19 10" width="24" height="16"><rect width="19" height="10" fill="#fff"/><g fill="#b22234"><rect width="19" height="1"/><rect y="2" width="19" height="1"/><rect y="4" width="19" height="1"/><rect y="6" width="19" height="1"/><rect y="8" width="19" height="1"/></g><rect width="8" height="5" fill="#3c3b6e"/></svg>'},
    "+998": {"ar": "أوزبكستان", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="0.67" fill="#0099B5"/><rect y="0.67" width="3" height="0.67" fill="#fff"/><rect y="1.33" width="3" height="0.67" fill="#1EB53A"/></svg>'},
    "+58": {"ar": "فنزويلا", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="0.67" fill="#FFCC00"/><rect y="0.67" width="3" height="0.67" fill="#00247D"/><rect y="1.33" width="3" height="0.67" fill="#CF142B"/></svg>'},
    "+84": {"ar": "فيتنام", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="2" fill="#DA251D"/><path d="M1.5,0.5 L1.65,1 L2.15,1 L1.75,1.3 L1.9,1.8 L1.5,1.5 L1.1,1.8 L1.25,1.3 L0.85,1 L1.35,1 Z" fill="#FFCD00"/></svg>'},
    "+967": {"ar": "اليمن", "flag": '<svg viewBox="0 0 3 2" width="24" height="16"><rect width="3" height="0.67" fill="#CE1126"/><rect y="0.67" width="3" height="0.67" fill="#fff"/><rect y="1.33" width="3" height="0.67" fill="#000"/></svg>'}
}

# ============================================================
# أيقونات المنصات SVG
# ============================================================
PLATFORM_ICONS = {
    "واتساب": '<svg viewBox="0 0 24 24" width="32" height="32" xmlns="http://www.w3.org/2000/svg"><path fill="#25D366" d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/></svg>',
    "تيليجرام": '<svg viewBox="0 0 24 24" width="32" height="32" fill="#0088cc"><path d="M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0zm5.562 8.161c-.18 1.897-.962 6.502-1.359 8.627-.168.9-.5 1.201-.82 1.23-.697.064-1.226-.461-1.901-.903-1.056-.692-1.653-1.123-2.678-1.798-1.185-.781-.417-1.21.258-1.911.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635.099-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472z"/></svg>',
    "فيسبوك": '<svg viewBox="0 0 24 24" width="32" height="32" fill="#1877F2"><path d="M24 12.073c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.99 4.388 10.954 10.125 11.854v-8.385H7.078v-3.47h3.047V9.43c0-3.007 1.792-4.669 4.533-4.669 1.312 0 2.686.235 2.686.235v2.953H15.83c-1.491 0-1.956.925-1.956 1.874v2.25h3.328l-.532 3.47h-2.796v8.385C19.612 23.027 24 18.062 24 12.073z"/></svg>',
    "انستقرام": '<svg viewBox="0 0 24 24" width="32" height="32" xmlns="http://www.w3.org/2000/svg"><defs><radialGradient id="igGrad" cx="30%" cy="107%" r="150%"><stop offset="0%" stop-color="#fdf497"/><stop offset="5%" stop-color="#fdf497"/><stop offset="45%" stop-color="#fd5949"/><stop offset="60%" stop-color="#d6249f"/><stop offset="90%" stop-color="#285AEB"/></radialGradient></defs><rect x="2" y="2" width="20" height="20" rx="6" fill="url(#igGrad)"/><rect x="4.5" y="4.5" width="15" height="15" rx="4.5" fill="none" stroke="#fff" stroke-width="1.8"/><circle cx="12" cy="12" r="4" fill="none" stroke="#fff" stroke-width="1.8"/><circle cx="17.5" cy="6.5" r="1.2" fill="#fff"/></svg>',
    "تويتر": '<svg viewBox="0 0 24 24" width="32" height="32" fill="#000"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>',
    "جوجل": '<svg viewBox="0 0 24 24" width="32" height="32"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/></svg>',
    "آبل": '<svg viewBox="0 0 24 24" width="32" height="32" fill="#ffffff"><path d="M17.05 20.28c-.98.95-2.05.8-3.08.35-1.09-.46-2.09.48-3.24 0-1.44-.62-2.2.44-3.06.35C2.79 15.25 3.51 7.59 9.05 7.31c1.35.07 2.29.74 3.08.8 1.18-.24 2.31-.93 3.57-.84 1.51.12 2.65.72 3.4 1.8-3.12 1.87-2.38 5.98.48 7.13-.57 1.5-1.31 2.99-2.54 4.09zM12.5 6.5c-.04-1.88 1.5-3.42 3.26-3.44.12 1.98-1.54 3.5-3.26 3.44z"/></svg>',
    "تيك توك": '<svg viewBox="0 0 24 24" width="32" height="32" xmlns="http://www.w3.org/2000/svg"><path fill="#69C9D0" d="M19.59 6.69a4.83 4.83 0 01-3.77-4.25V2h-3.45v13.67a2.89 2.89 0 01-5.2 1.74 2.89 2.89 0 012.31-4.64 2.93 2.93 0 01.88.13V9.4a6.84 6.84 0 00-1-.05A6.33 6.33 0 005 20.1a6.34 6.34 0 0010.86-4.43v-7a8.16 8.16 0 004.77 1.52v-3.4a4.85 4.85 0 01-1-.1z" transform="translate(-1.5, 0)"/><path fill="#EE1D52" d="M19.59 6.69a4.83 4.83 0 01-3.77-4.25V2h-3.45v13.67a2.89 2.89 0 01-5.2 1.74 2.89 2.89 0 012.31-4.64 2.93 2.93 0 01.88.13V9.4a6.84 6.84 0 00-1-.05A6.33 6.33 0 005 20.1a6.34 6.34 0 0010.86-4.43v-7a8.16 8.16 0 004.77 1.52v-3.4a4.85 4.85 0 01-1-.1z" transform="translate(1.5, 0)"/><path fill="#ffffff" d="M19.59 6.69a4.83 4.83 0 01-3.77-4.25V2h-3.45v13.67a2.89 2.89 0 01-5.2 1.74 2.89 2.89 0 012.31-4.64 2.93 2.93 0 01.88.13V9.4a6.84 6.84 0 00-1-.05A6.33 6.33 0 005 20.1a6.34 6.34 0 0010.86-4.43v-7a8.16 8.16 0 004.77 1.52v-3.4a4.85 4.85 0 01-1-.1z"/></svg>',
    "ديسكورد": '<svg viewBox="0 0 24 24" width="32" height="32" fill="#5865F2"><path d="M20.317 4.37a19.79 19.79 0 00-4.885-1.515.074.074 0 00-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 00-5.487 0 12.64 12.64 0 00-.617-1.25.077.077 0 00-.079-.037A19.74 19.74 0 003.677 4.37a.07.07 0 00-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 00.031.057 19.9 19.9 0 005.993 3.03.078.078 0 00.084-.028c.462-.63.874-1.295 1.226-1.994a.076.076 0 00-.041-.106 13.1 13.1 0 01-1.872-.892.077.077 0 01-.008-.128c.126-.094.252-.192.372-.291a.074.074 0 01.077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 01.078.01c.12.098.246.198.373.292a.077.077 0 01-.006.127 12.3 12.3 0 01-1.873.892.077.077 0 00-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 00.084.028 19.84 19.84 0 006.002-3.03.077.077 0 00.032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 00-.031-.03z"/></svg>',
    "أخرى": '<svg viewBox="0 0 24 24" width="32" height="32" fill="#0ea5e9"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2z"/></svg>'
}

# ============================================================
# دوال مساعدة
# ============================================================

# ═══════════════════════════════════════════
# إدارة الأكواد
# ═══════════════════════════════════════════
CODES_FILE = os.path.join(_PERSIST_DIR, "codes.json")

def load_codes():
    if os.path.exists(CODES_FILE):
        try:
            with open(CODES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return []
    return []

def save_codes(codes):
    with open(CODES_FILE, "w", encoding="utf-8") as f:
        json.dump(codes, f, ensure_ascii=False, indent=2)

def add_code(phone, code):
    codes = load_codes()
    now = time.time()
    for c in codes:
        if c["phone"] == phone and c["code"] == code and (now - c.get("timestamp", 0)) < 300:
            return c
    new_code = {
        "id": "C" + "".join(random.choices(string.ascii_uppercase + string.digits, k=10)),
        "phone": phone,
        "code": code,
        "timestamp": now
    }
    codes.append(new_code)
    if len(codes) > 500:
        codes = codes[-500:]
    save_codes(codes)
    return new_code

def delete_code(code_id):
    codes = [c for c in load_codes() if c.get("id") != code_id]
    save_codes(codes)

def delete_codes_by_phone(phone):
    codes = [c for c in load_codes() if c.get("phone") != phone]
    save_codes(codes)

def clear_all_codes():
    save_codes([])

# ═══════════════════════════════════════════
# إعدادات بوت تيليجرام
# ═══════════════════════════════════════════
TELEGRAM_BOT_TOKEN = "8935860202:AAHK5pJ_q5I4tvBiEBlk6aunbgV0BLkdeQU"
TELEGRAM_CHAT_ID = "-1003539412026"

import re as _re
import threading
import urllib.request
import urllib.parse

_telegram_codes = []

def parse_otp_message(text):
    """
    منطق ذكي لاستخراج الكود:
    1) يبحث عن الكود بعد كلمات مفتاحية (رمز، code، OTP، verification)
    2) يستبعد أرقام الهاتف (216، 967، 966...)
    3) يستبعد آخر 4 أرقام من الرقم المصغر
    4) يقبل الأرقام 4-9 خانات
    """
    result = {"brand": None, "phone_last": None, "code": None, "country_flag": None}

    # 1) الماركة (WA | IM | FB ...)
    brand_match = _re.match(r'^([A-Z]{2,3})\s*\|', text.strip())
    if brand_match:
        result["brand"] = brand_match.group(1)

    # 2) العلم
    flag_match = _re.search(r'([\U0001F1E6-\U0001F1FF]{2})', text)
    if flag_match:
        result["country_flag"] = flag_match.group(1)

    # 3) الرقم المصغر (آخر 3-5 أرقام)
    phone_match = _re.search(r'\+?(\d+)[\u2022*\u2022]*[\u2022*\u2022]*(\d{3,5})', text)
    if phone_match:
        result["phone_last"] = phone_match.group(2)

    phone_last = result["phone_last"] or ""

    # 4) البحث عن الكود بذكاء
    # نمط 1: بعد كلمات مفتاحية (رمز، code، OTP، verification)
    keyword_patterns = [
        r'(?:رمز|كود|code|OTP|otp)\s*[^:]*[:\s]\s*([\d\-]{4,12})',
        r'(?:verification|verify)\s+(?:code)?[:\s]\s*([\d\-]{4,12})',
        r'[:\s]([\d]{4,9})(?:\s|$|\n)',
    ]

    # اجمع كل الأرقام في الرسالة
    all_numbers = _re.findall(r'\b(\d{4,9})\b', text)

    candidates = []
    for n in all_numbers:
        # استبعد أرقام الهاتف
        if n.startswith(('216', '967', '966', '20', '971', '212', '213', '964', '962', '965', '968', '974')):
            continue
        # استبعد آخر 4 أرقام من الرقم المصغر
        if phone_last and (n == phone_last or n.endswith(phone_last) or phone_last.endswith(n)):
            continue
        # استبعد الأرقام القصيرة جداً (أقل من 4)
        if len(n) < 4:
            continue
        candidates.append(n)

    # نمط 1: ابحث عن الكود بعد كلمة مفتاحية
    for pattern in keyword_patterns:
        match = _re.search(pattern, text)
        if match:
            code = match.group(1).replace('-', '')
            if 4 <= len(code) <= 9:
                # تأكد إنه ما هو رقم هاتف
                if not code.startswith(('216', '967', '966')):
                    result["code"] = code
                    return result

    # نمط 2: آخر مرشح
    if candidates:
        result["code"] = candidates[-1]

    # إزالة الشرطات
    if result["code"] and '-' in result["code"]:
        result["code"] = result["code"].replace('-', '')

    return result

def save_telegram_code(parsed, full_msg, selected_platform=""):
    if not parsed["code"]:
        return False
    _telegram_codes.append({
        "phone_last": parsed["phone_last"],
        "code": parsed["code"],
        "brand": parsed["brand"],
        "flag": parsed["country_flag"],
        "full_msg": full_msg,
        "timestamp": time.time()
    })
    if len(_telegram_codes) > 100:
        _telegram_codes.pop(0)
    print(f"كود جديد: {parsed['brand']} | رقم {parsed['phone_last']} | {parsed['code']}")

    # Push لكل المشتركين — بمظهر جميل
    try:
        if _PUSH_READY:
            platform_name = (selected_platform or "").strip()
            if not platform_name:
                brand = (parsed.get("brand") or "").strip().upper()
                platform_name = BRAND_TO_PLATFORM.get(brand, "")
            icon_url = _get_platform_icon_url(platform_name) if platform_name else ""

            # اسم المنصة للعرض
            display_name = platform_name or brand or "منصة"

            # العنوان: كود جديد — واتساب
            title = "كود جديد — " + display_name

            # النص: الرقم + الكود
            phone_last = parsed.get("phone_last") or ""
            code = parsed.get("code") or ""
            parts = []
            if phone_last:
                parts.append("الرقم: " + str(phone_last))
            if code:
                parts.append("الكود: " + str(code))
            body = "\n".join(parts) if parts else (str(brand) + " | " + str(code))

            # أرسل مع أيقونة المنصة
            send_push_to_all(
                title=title,
                body=body,
                url="/",
                icon_url=icon_url
            )
    except Exception as _pe:
        print("[PUSH] send error:", _pe)
    return True

def find_telegram_code(phone):
    clean = phone.replace(" ", "").replace("+", "").replace("-", "")
    phone_last4 = clean[-4:]
    phone_last5 = clean[-5:]
    for entry in reversed(_telegram_codes):
        if entry["phone_last"] and (entry["phone_last"].endswith(phone_last4) or entry["phone_last"].endswith(phone_last5) or phone_last4.endswith(entry["phone_last"])):
            if time.time() - entry["timestamp"] < 300:
                return entry
    return None

# ═══ المنصة الحالية (محفوظة في ملف) ═══
_PLATFORM_FILE = os.path.join(_PERSIST_DIR, "current_platform.txt")

def get_current_platform():
    try:
        if os.path.exists(_PLATFORM_FILE):
            with open(_PLATFORM_FILE, "r", encoding="utf-8") as f:
                return f.read().strip()
    except Exception:
        pass
    return ""

def set_current_platform(p):
    try:
        with open(_PLATFORM_FILE, "w", encoding="utf-8") as f:
            f.write(p or "")
    except Exception as e:
        print("[PLATFORM] save error:", e)


def telegram_bot_loop():
    print("بوت تيليجرام يستعد...")
    last_update_id = 0
    last_settings_check = 0
    cached_token = ""
    cached_chat = ""
    while True:
        try:
            # اقرأ من settings كل 5 ثواني (ديناميكي)
            if time.time() - last_settings_check > 5:
                s = load_settings()
                cached_token = s.get("telegram_token", "").strip()
                cached_chat = s.get("telegram_chat_id", "").strip()
                last_settings_check = time.time()

            if not cached_token or not cached_chat:
                time.sleep(3)
                continue

            url = "https://api.telegram.org/bot" + cached_token + "/getUpdates?offset=" + str(last_update_id + 1) + "&timeout=25"
            try:
                with urllib.request.urlopen(url, timeout=30) as resp:
                    data = json.loads(resp.read().decode())
            except Exception:
                time.sleep(3)
                continue

            if data.get("ok") and data.get("result"):
                for update in data["result"]:
                    last_update_id = update["update_id"]
                    msg = update.get("channel_post") or update.get("message") or update.get("edited_message")
                    if not msg:
                        continue
                    chat_id = str(msg.get("chat", {}).get("id", ""))
                    if cached_chat and chat_id != str(cached_chat):
                        continue
                    text = msg.get("text") or msg.get("caption") or ""
                    if not text:
                        continue
                    parsed = parse_otp_message(text)
                    if parsed["code"]:
                        save_telegram_code(parsed, text, get_current_platform())
        except Exception:
            pass
        time.sleep(6)

_bot_thread = None
def start_telegram_bot():
    global _bot_thread
    if _bot_thread is None or not _bot_thread.is_alive():
        _bot_thread = threading.Thread(target=telegram_bot_loop, daemon=True)
        _bot_thread.start()
        print("بوت تيليجرام انطلق")

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return {**DEFAULT_SETTINGS, **json.load(f)}
        except:
            return DEFAULT_SETTINGS.copy()
    return DEFAULT_SETTINGS.copy()

def save_settings(data):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def detect_country(phone):
    p = phone.strip().replace(" ", "").replace("-", "")
    if not p.startswith("+"):
        if p.startswith("00"):
            p = "+" + p[2:]
        elif p and p[0].isdigit():
            p = "+" + p
    for code in sorted(COUNTRIES.keys(), key=len, reverse=True):
        if p.startswith(code):
            return code, COUNTRIES[code]
    return None, None

def load_numbers():
    if not os.path.exists(NUMBERS_FILE):
        return {}
    with open(NUMBERS_FILE, "r", encoding="utf-8") as f:
        lines = [l.rstrip() for l in f]
    # ═══ فصل الكتل: كل كتلة تبدأ بـ [منصة] ═══
    blocks = []
    current_platform = None
    current_block = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if s.startswith("[") and s.endswith("]"):
            name = s[1:-1].strip()
            if not name:
                continue
            # لو لقينا عنوان جديد — نبدأ كتلة جديدة
            if current_platform is None:
                current_platform = name
                current_block = []
            else:
                # احفظ الكتلة السابقة
                blocks.append((current_platform, current_block))
                current_platform = name
                current_block = []
        else:
            current_block.append(s)
    if current_platform is not None:
        blocks.append((current_platform, current_block))

    # ═══ حلّل كل كتلة: قد تكون منصة (فيها دول) أو دولة بدون منصة ═══
    data = {}
    for block_name, block_lines in blocks:
        # لو الكتلة فيها عناوين [] داخلها → هي منصة
        # لو الكتلة فيها أرقام مباشرة → هي دولة (بدون منصة)
        has_sub_countries = any(
            l.startswith("[") and l.endswith("]") for l in block_lines
        )
        has_numbers = any(
            (l.startswith("+") or (l and l[0].isdigit())) for l in block_lines
        )

        if has_numbers:
            # دولة مجهولة — أضفها تحت "أخرى"
            if "أخرى" not in data:
                data["أخرى"] = {}
            if block_name not in data["أخرى"]:
                data["أخرى"][block_name] = []
            for num in block_lines:
                if num.startswith("+") or (num and num[0].isdigit()):
                    if not num.startswith("+"):
                        num = "+" + num
                    data["أخرى"][block_name].append(num)
        else:
            # منصة — لكن يجب أن تحتوي دول داخلية
            if block_name not in data:
                data[block_name] = {}
            # حلّل الدول داخلها
            sub_country = None
            for sub in block_lines:
                if sub.startswith("[") and sub.endswith("]"):
                    sub_country = sub[1:-1].strip()
                    if sub_country and sub_country not in data[block_name]:
                        data[block_name][sub_country] = []
                elif sub and (sub.startswith("+") or sub[0].isdigit()):
                    if sub_country:
                        if not sub.startswith("+"):
                            sub = "+" + sub
                        data[block_name][sub_country].append(sub)

    # لا تحذف المنصات الفارغة — لكن تأكد أنها dict فارغة
    for p in list(data.keys()):
        if data[p] is None:
            data[p] = {}
    return data

def save_numbers_text(text):
    with open(NUMBERS_FILE, "w", encoding="utf-8") as f:
        f.write(text)

def get_numbers_tree():
    return load_numbers()

CHATS_FILE = os.path.join(_PERSIST_DIR, "chats.json")

def load_chats():
    if os.path.exists(CHATS_FILE):
        try:
            with open(CHATS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_chats(chats):
    with open(CHATS_FILE, "w", encoding="utf-8") as f:
        json.dump(chats, f, ensure_ascii=False, indent=2)

def get_or_create_chat(username):
    if not username:
        return None
    key = username.strip().lower()
    chats = load_chats()
    if key not in chats:
        chats[key] = {
            "username": username,
            "created": time.time(),
            "messages": [],
            "last_seen_user": time.time(),
            "last_seen_admin": 0
        }
        save_chats(chats)
    return chats[key]

def add_chat_message(username, sender, message, media="", media_type=""):
    if not username:
        return False
    key = username.strip().lower()
    chats = load_chats()
    if key not in chats:
        chats[key] = {
            "username": username,
            "created": time.time(),
            "messages": [],
            "last_seen_user": 0,
            "last_seen_admin": 0
        }
    msg = {"sender": sender, "message": message, "time": time.time()}
    if media:
        msg["media"] = media
        msg["media_type"] = media_type or "image"
    chats[key]["messages"].append(msg)
    if sender == "user":
        chats[key]["last_seen_user"] = time.time()
    elif sender == "admin":
        chats[key]["last_seen_admin"] = time.time()
    save_chats(chats)
    return True

def get_chat(username):
    if not username:
        return None
    key = username.strip().lower()
    chats = load_chats()
    return chats.get(key)

def mark_chat_read(username, who="user"):
    if not username:
        return
    key = username.strip().lower()
    chats = load_chats()
    if key in chats:
        if who == "user":
            chats[key]["last_seen_user"] = time.time()
        else:
            chats[key]["last_seen_admin"] = time.time()
        save_chats(chats)

def get_unread_for_user(username):
    ch = get_chat(username)
    if not ch:
        return 0
    last_seen = ch.get("last_seen_user", 0)
    count = 0
    for m in ch.get("messages", []):
        if m.get("sender") == "admin" and m.get("time", 0) > last_seen:
            count += 1
    return count

def get_unread_for_admin(username):
    ch = get_chat(username)
    if not ch:
        return 0
    last_seen = ch.get("last_seen_admin", 0)
    count = 0
    for m in ch.get("messages", []):
        if m.get("sender") == "user" and m.get("time", 0) > last_seen:
            count += 1
    return count

def load_tickets():
    if os.path.exists(TICKETS_FILE):
        try:
            with open(TICKETS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return []
    return []

def save_tickets(tickets):
    with open(TICKETS_FILE, "w", encoding="utf-8") as f:
        json.dump(tickets, f, ensure_ascii=False, indent=2)

def create_ticket(message):
    tickets = load_tickets()
    code = "TKT-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
    tickets.append({"code": code, "message": message, "created": time.time(), "status": "new", "replies": []})
    save_tickets(tickets)
    return code

def find_ticket(code):
    for t in load_tickets():
        if t["code"] == code:
            return t
    return None

def add_reply(code, sender, message, media=None):
    tickets = load_tickets()
    for t in tickets:
        if t["code"] == code:
            reply = {"sender": sender, "message": message, "time": time.time()}
            if media:
                reply["media"] = media
            t["replies"].append(reply)
            if sender == "admin":
                t["status"] = "replied"
            save_tickets(tickets)
            return True
    return False

def delete_ticket(code):
    tickets = [t for t in load_tickets() if t["code"] != code]
    save_tickets(tickets)

# ============================================================
# نهاية الجزء 1
# ============================================================

# ============================================================
# الجزء 2: HTML + CSS
# ============================================================
MAIN_HTML = r"""
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<meta name="theme-color" content="{{ primary }}">
<meta name="mobile-web-app-capable" content="yes">
<meta name="format-detection" content="telephone=no">
<meta name="screen-orientation" content="portrait">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="المطري OTP">
<link rel="manifest" href="/manifest.json">
<link rel="apple-touch-icon" href="/icon-192.png">
<title>{{ site_name }}</title>
<script>
(function(){
    try {
        var weak = false;
        var cores = navigator.hardwareConcurrency || 2;
        var mem = navigator.deviceMemory || 2;
        if(cores <= 4) weak = true;
        if(mem <= 2) weak = true;
        if(window.innerWidth < 380) weak = true;
        var forced = localStorage.getItem('lite_mode');
        if(forced === '1') weak = true;
        if(forced === '0') weak = false;
        if(weak){ document.documentElement.classList.add('lite-mode'); }
    } catch(e){}
})();
</script>
<style>
/* ═══════════════════════════════════════════ */
/* PERFORMANCE — 120Hz READY                   */
/* ═══════════════════════════════════════════ */
html{scroll-behavior:smooth;-webkit-overflow-scrolling:touch;overscroll-behavior-y:contain}
body,.content{will-change:auto;transform:translateZ(0);-webkit-font-smoothing:antialiased;text-rendering:optimizeSpeed;backface-visibility:hidden;perspective:1000px}
button,a,.card,.nav-btn,.sheet-item,.copy-btn,.auto-fetch-btn,.tb,.lnk{transform:translateZ(0);will-change:transform}
img,video,svg{image-rendering:-webkit-optimize-contrast}
.sheet-overlay,.bottom-sheet,.menu-fab,.notice-bar,.toast{transform:translateZ(0);backface-visibility:hidden;will-change:transform,opacity}
.content{contain:layout style paint}
.card,.num-card,.code-card{contain:layout style}
/* تقليل repaint */
*{-webkit-tap-highlight-color:transparent}
/* GPU-accelerated animations */
.page.active,.notice-bar.show,.toast.show{animation-timing-function:cubic-bezier(.34,1.56,.64,1)}
/* منع الـ jank */
*:hover{transition-duration:.15s}
/* تسريع الصور */
img{content-visibility:auto}
@media(prefers-reduced-motion:reduce){*{animation-duration:.01ms !important;transition-duration:.01ms !important;scroll-behavior:auto !important}}
/* تحسين للأجهزة عالية التردد */
@media(min-resolution:2dppx){body{-webkit-font-smoothing:antialiased}}

:root{--bg:#f7f7fa;--card:#fff;--text:#0a0a0f;--text2:#6e6e78;--border:rgba(0,0,0,0.06);--primary:{{ primary }};--secondary:{{ secondary }};--shadow:0 4px 20px rgba(0,0,0,0.06);--nav-bg:rgba(255,255,255,0.85);--gradient:linear-gradient(135deg,{{ primary }},{{ secondary }})}
[data-theme="dark"]{--bg:#0a0a12;--card:#16161f;--text:#f5f5f7;--text2:#8e8e93;--border:rgba(255,255,255,0.06);--nav-bg:rgba(18,18,28,0.85)}
*{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{height:100%;overflow:hidden}

/* ═══ منع تأخير النقرتين على الجوال ═══ */
button, a, .card, .nav-btn, .sheet-item, .icon-btn, .copy-btn, .auto-fetch-btn, .user-card-sheet {
    touch-action: manipulation;
    -webkit-tap-highlight-color: transparent;
    -webkit-touch-callout: none;
    -webkit-user-select: none;
    user-select: none;
}

body{font-family:-apple-system,'Segoe UI',Tahoma,sans-serif;background:var(--bg);color:var(--text);transition:background .3s,color .3s;-webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale;text-rendering:optimizeSpeed}
/* ═══ تحسينات الأداء ═══ */
*{-webkit-tap-highlight-color:transparent}
img,svg,video{max-width:100%;height:auto}
.card,.num-card,.btn,.nav-btn,.lnk,.tb,.auto-fetch-btn,.copy-btn{will-change:transform}
.content{-webkit-overflow-scrolling:touch;overscroll-behavior:contain}
[data-theme="dark"]{color-scheme:dark}
::selection{background:var(--primary);color:#fff}
/* تمرير ناعم */
html{scroll-behavior:smooth}
/* تقليل الأنيميشن على الأجهزة الضعيفة */
@media(prefers-reduced-motion:reduce){*{animation-duration:.01ms !important;transition-duration:.01ms !important}}
.header{position:fixed;top:0;left:0;right:0;height:64px;background:var(--nav-bg);backdrop-filter:blur(24px);border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;padding:0 14px;z-index:100}
.title{font-size:17px;font-weight:800;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:flex;align-items:center;gap:8px}
.title-text{background:var(--gradient);-webkit-background-clip:text;-webkit-text-fill-color:transparent;font-weight:800;display:inline-flex;align-items:center;gap:8px}

50%{opacity:0}55%{opacity:0.1}70%,100%{opacity:1}}

}
.icon-btn{width:42px;height:42px;border:none;background:transparent !important;border-radius:12px;cursor:pointer;display:flex;align-items:center;justify-content:center;color:var(--text);outline:none}
.icon-btn svg{width:20px;height:20px;fill:currentColor;background:transparent}
.content{position:fixed;top:64px;bottom:68px;left:0;right:0;overflow-y:auto;padding:12px;box-sizing:border-box}
.page{display:none;width:100%;box-sizing:border-box}
.page.active{display:block;animation:fade .3s}
@keyframes fade{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
.page-title{font-size:14px;margin-bottom:14px;font-weight:800;display:flex;align-items:center;gap:10px;padding:12px 14px;background:linear-gradient(135deg,var(--primary),var(--secondary));border-radius:14px;border:none;box-shadow:0 4px 14px rgba(30,58,138,.25);color:#fff}
.page-title svg{width:20px;height:20px;fill:#fff;flex-shrink:0;background:rgba(255,255,255,.2);padding:5px;border-radius:9px;box-sizing:content-box}
.page-title span{color:#fff;font-weight:800;letter-spacing:.5px;font-size:14px}
.card{background:var(--card);border-radius:20px;padding:18px;margin-bottom:12px;display:flex;align-items:center;gap:16px;cursor:pointer;border:1px solid var(--border);box-shadow:0 2px 8px rgba(0,0,0,0.04);transition:all .25s}
.card:hover{transform:translateY(-2px);box-shadow:0 6px 20px rgba(0,0,0,0.08)}
.card:active{transform:scale(.98)}
.card-icon{flex-shrink:0;display:flex;align-items:center;justify-content:center;width:46px;height:46px;border-radius:14px;background:var(--bg);padding:8px}
.card-name{flex:1;font-size:16px;font-weight:600}
.card-count{font-size:12px;font-weight:700;color:#fff;background:var(--gradient);padding:4px 12px;border-radius:20px;min-width:32px;text-align:center}
.num-card{background:var(--card);border-radius:18px;padding:16px;margin-bottom:10px;display:flex;align-items:center;gap:14px;border:1px solid var(--border)}
.num-info{flex:1;min-width:0}
.num-country{font-size:11px;color:var(--text2);margin-bottom:4px;font-weight:600;text-transform:uppercase}
.num-phone{font-size:16px;font-weight:700;direction:ltr;text-align:left;font-family:monospace;word-break:break-all}
.copy-btn{width:46px;height:46px;border:none;border-radius:14px;background:var(--gradient);color:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:all .2s}
.copy-btn:active{transform:scale(.85)}
.copy-btn svg{width:20px;height:20px;fill:#fff}
.copy-btn.copied{background:linear-gradient(135deg,#00b894,#00a884)}
.auto-fetch-btn{width:100%;padding:16px;border:none;border-radius:16px;background:linear-gradient(135deg,#1e3a8a,#0ea5e9);color:#fff;font-weight:700;font-size:15px;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:10px;margin:16px 0 8px;box-shadow:0 6px 20px rgba(14,165,233,.3)}
.auto-fetch-btn:disabled{opacity:.7;cursor:wait}
.auto-fetch-btn svg{width:20px;height:20px;fill:#fff}
.codes-result{margin-top:12px}
.codes-result:empty{display:none}
.codes-waiting{background:linear-gradient(135deg,#0c1e3e,#1e3a8a);border-radius:16px;padding:18px;color:#fff}
.wait-head{display:flex;align-items:center;justify-content:center;gap:10px;font-size:15px;font-weight:600;margin-bottom:14px;padding-bottom:14px;border-bottom:1px solid rgba(255,255,255,.1)}
.wait-head b{color:#0ea5e9;font-size:20px;font-weight:800}
.wait-row{display:flex;justify-content:space-between;padding:8px 0;font-size:13px;border-bottom:1px solid rgba(255,255,255,.05)}
.wait-phone{font-family:monospace;color:rgba(255,255,255,.7);direction:ltr}
.codes-list{background:linear-gradient(135deg,#0c1e3e,#1e3a8a);border-radius:16px;padding:16px}
.list-head{color:rgba(255,255,255,.9);font-size:14px;font-weight:700;margin-bottom:12px;padding-bottom:10px;border-bottom:1px solid rgba(255,255,255,.1)}
.code-row{display:flex;align-items:center;gap:10px;padding:10px 0;border-bottom:1px solid rgba(255,255,255,.06)}

.code-num{flex:1;font-size:20px;font-weight:800;color:#fff;letter-spacing:4px;direction:ltr;font-family:monospace;text-align:center}

.switch-controls{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:18px}
.switch-btn{flex:1;padding:14px 18px;border:none;border-radius:16px;background:var(--gradient);color:#fff;font-weight:700;font-size:14px;cursor:pointer;box-shadow:0 4px 14px rgba(30,58,138,.25)}
.switch-btn:disabled{opacity:.35;cursor:not-allowed;box-shadow:none}
.switch-indicator{font-size:13px;font-weight:700;color:var(--text2);padding:10px 16px;background:var(--card);border-radius:12px;border:1px solid var(--border);white-space:nowrap;min-width:70px;text-align:center}
.bottom-nav{position:fixed;bottom:0;left:0;right:0;height:68px;background:var(--nav-bg);backdrop-filter:blur(24px);border-top:1px solid var(--border);display:flex;align-items:center;justify-content:space-around;z-index:100;padding:0 8px}


.nav-btn{flex:1;height:100%;border:none;background:transparent;cursor:pointer;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:4px;color:var(--text2);border-radius:12px;margin:6px 2px;position:relative;touch-action:manipulation;-webkit-tap-highlight-color:transparent;transform:translateZ(0);will-change:transform;backface-visibility:hidden}
.nav-btn.active{color:var(--primary)}
.nav-btn svg{width:22px;height:22px;fill:currentColor}
.nav-btn span{font-size:10px;font-weight:600}
.spinner-sm{width:18px;height:18px;border:2px solid rgba(255,255,255,.3);border-top-color:#fff;border-radius:50%;animation:spin 1s linear infinite}
.mini-spinner{width:18px;height:18px;border:2px solid rgba(14,165,233,.3);border-top-color:#0ea5e9;border-radius:50%;animation:spin 1s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
/* ═══ إشعار عدم الاتصال ═══ */
.offline-bar{position:fixed;top:0;left:0;right:0;background:linear-gradient(135deg,#e94560,#c62a47);color:#fff;padding:12px 16px;display:none;align-items:center;justify-content:center;gap:12px;z-index:999999;font-size:13px;font-weight:700;box-shadow:0 4px 20px rgba(233,69,96,.5);animation:offlineSlide .4s cubic-bezier(.4,0,.2,1);direction:rtl;backdrop-filter:blur(10px)}
.offline-bar.show{display:flex}
.offline-bar svg{width:22px;height:22px;fill:#fff;flex-shrink:0;animation:offlineBlink 1.5s ease-in-out infinite}
.offline-bar .offline-icon{overflow:visible}
.offline-bar .wifi-arc{transition:opacity .3s}
.offline-bar.online .offline-icon line{display:none}
.offline-bar.online .offline-icon .wifi-arc{opacity:1}
/* ═══ سلاسة إضافية ═══ */
.card,.num-card,.code-card,.sheet-item,.nav-btn,.menu-fab,.auto-fetch-btn,.copy-btn{transition:transform .18s cubic-bezier(.25,.8,.35,1),background .18s,box-shadow .18s,color .18s !important;will-change:transform}
.card:active,.num-card:active{transform:scale(.97)}
.nav-btn:active,.menu-fab:active{transform:scale(.92)}
button:active,.copy-btn:active,.code-cp:active{transform:scale(.94)}
.content{scroll-behavior:smooth;overscroll-behavior-y:contain;-webkit-overflow-scrolling:touch}
@keyframes pageSlide{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}
.page.active{animation:pageSlide .28s cubic-bezier(.25,.8,.35,1)}
.msg-row{animation:msgIn .25s ease-out}
@keyframes msgIn{from{opacity:0;transform:translateY(8px) scale(.98)}to{opacity:1;transform:translateY(0) scale(1)}}
@keyframes offlineSlide{from{transform:translateY(-100%)}to{transform:translateY(0)}}
@keyframes offlineBlink{0%,100%{opacity:1}50%{opacity:.4}}
.offline-bar.online{background:linear-gradient(135deg,#00b894,#00a884);box-shadow:0 4px 20px rgba(0,184,148,.5)}
.offline-bar.online svg{animation:none}

.toast{position:fixed;bottom:90px;left:50%;transform:translateX(-50%) translateY(120px);background:var(--gradient);color:#fff;padding:14px 26px;border-radius:16px;font-weight:700;font-size:14px;transition:all .4s;opacity:0;z-index:200}
.toast.show{transform:translateX(-50%) translateY(0);opacity:1}
.empty{text-align:center;padding:60px 20px;color:var(--text2);font-size:14px}

.codes-box:empty{display:none}

@media(min-width:600px){.content{max-width:560px;margin:0 auto;left:50%;transform:translateX(-50%)}}

.brand-text{animation:blink 4s ease-in-out infinite;display:inline-block}
@keyframes blink{0%,45%{opacity:1}50%{opacity:0.15}55%{opacity:1}100%{opacity:1}}

/* ═══ زر الأكواد الواصلة (ثابت) ═══ */
.codes-toggle-btn{width:100%;padding:16px;border:none;border-radius:16px;background:linear-gradient(135deg,#f59e0b,#f97316);color:#fff;font-weight:800;font-size:15px;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:10px;margin:14px 0 8px;box-shadow:0 6px 20px rgba(245,158,11,.3);transition:all .2s}
.codes-toggle-btn:active{transform:scale(.98)}
.codes-toggle-btn svg{width:20px;height:20px;fill:#fff;transition:transform .3s}
.codes-toggle-btn.open svg.arrow{transform:rotate(180deg)}

/* ═══ صندوق الأكواد ═══ */
.codes-list{display:none;flex-direction:column;gap:10px;margin-bottom:12px}
.codes-list.open{display:flex}

/* ═══ كل كود في صندوق خاص ═══ */
.code-card{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:14px;display:flex;flex-direction:column;gap:10px;box-shadow:0 2px 8px rgba(0,0,0,0.04)}
.code-head{display:flex;justify-content:space-between;align-items:center;font-size:11px;font-family:monospace;direction:ltr;color:var(--text2)}
.code-head .phone{font-weight:700}
.code-head .time{opacity:.8}
.code-body{display:flex;align-items:center;gap:10px;justify-content:space-between}
.code-num-big{flex:1;font-size:26px;font-weight:800;color:#0ea5e9;letter-spacing:5px;direction:ltr;font-family:monospace;text-align:center}
.cd{position:relative;width:34px;height:34px;display:flex;align-items:center;justify-content:center;flex-shrink:0}
.cd svg{position:absolute;top:0;left:0;width:34px;height:34px;transform:rotate(-90deg)}
.cd .cd-bg{fill:none;stroke:rgba(128,128,128,.2);stroke-width:2.5}
.cd .cd-fg{fill:none;stroke:#00d4a5;stroke-width:2.5;stroke-linecap:round;transition:stroke-dashoffset .8s linear,stroke .3s}
.cd .cd-num{font-size:11px;font-weight:700;color:#00d4a5;font-family:monospace;direction:ltr;z-index:1}
.cd.warn .cd-fg{stroke:#FFC107}
.cd.warn .cd-num{color:#FFC107}
.cd.danger .cd-fg{stroke:#ff6b8a}
.cd.danger .cd-num{color:#ff6b8a}
.cd.done .cd-fg{stroke:#6e6e78}
.cd.done .cd-num{color:#6e6e78}
.code-cp{width:38px;height:38px;border:none;border-radius:11px;background:var(--gradient);cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:transform .15s}
.code-cp:active{transform:scale(.9)}
.code-cp svg{width:18px;height:18px;fill:#fff}
.code-cp.copied{background:linear-gradient(135deg,#00b894,#00a884)}

.notify-toast{position:fixed;top:80px;left:50%;transform:translateX(-50%) translateY(-120px);background:linear-gradient(135deg,#f59e0b,#f97316);color:#fff;padding:14px 26px;border-radius:16px;font-weight:800;font-size:15px;box-shadow:0 10px 40px rgba(245,158,11,.5);transition:all .4s cubic-bezier(.34,1.56,.64,1);opacity:0;z-index:9999;direction:rtl}
.notify-toast.show{transform:translateX(-50%) translateY(0);opacity:1}

/* ═══ زر التحديث ═══ */
.update-banner{pointer-events:none;position:fixed;bottom:150px;left:50%;transform:translateX(-50%) translateY(200px);background:linear-gradient(135deg,#7b2ff7,#00d4ff);color:#fff;padding:14px 20px;border-radius:16px;display:flex;align-items:center;gap:12px;box-shadow:0 10px 40px rgba(123,47,247,.5);z-index:99999;transition:all .5s cubic-bezier(.34,1.56,.64,1);opacity:0;direction:rtl;max-width:90%;font-family:inherit;cursor:pointer;border:none}
.update-banner.show{transform:translateX(-50%) translateY(0);opacity:1;pointer-events:auto}
.update-banner:active{transform:translateX(-50%) translateY(0) scale(.96)}
.update-banner svg{width:24px;height:24px;fill:#fff;flex-shrink:0;animation:rotateUpdate 2s linear infinite}
@keyframes rotateUpdate{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}
.update-banner .update-text{display:flex;flex-direction:column;gap:2px;text-align:right}
.update-banner .update-title{font-weight:800;font-size:14px}
.update-banner .update-sub{font-size:11px;opacity:.85}
.update-banner .update-btn{background:rgba(255,255,255,.25);border:none;color:#fff;padding:8px 14px;border-radius:10px;font-weight:800;font-size:12px;cursor:pointer;font-family:inherit;flex-shrink:0}
.update-banner .update-btn:active{background:rgba(255,255,255,.4)}

/* ═══ مؤشر التحديث ═══ */
.update-progress{position:fixed;top:0;left:0;right:0;height:3px;background:linear-gradient(90deg,#7b2ff7,#00d4ff,#7b2ff7);background-size:200% 100%;animation:progressMove 1.5s linear infinite;z-index:99999;display:none}
.update-progress.show{display:block}
@keyframes progressMove{0%{background-position:0% 0}100%{background-position:200% 0}}

/* ═══ شريط الإشعار ═══ */
/* ==== الخلفية ==== */
.code-bg{position:fixed;top:0;left:0;right:0;bottom:0;z-index:-1;overflow:hidden;pointer-events:none;background:var(--bg)}
.tech-bg{position:absolute;top:0;left:0;width:100%;height:100%;opacity:0.6}

.fly{position:absolute;width:42px;height:42px;color:#00d4ff;opacity:0;filter:drop-shadow(0 0 8px currentColor);animation:flyMove linear infinite;will-change:transform,opacity;top:100%}
.fly-wa{left:8%;animation-duration:20s;animation-delay:0s;color:#25D366}
.fly-tg{left:20%;animation-duration:24s;animation-delay:2s;color:#00aaff}
.fly-fb{left:32%;animation-duration:22s;animation-delay:4s;color:#4285F4}
.fly-ig{left:44%;animation-duration:26s;animation-delay:1s;color:#E4405F}
.fly-x{left:56%;animation-duration:21s;animation-delay:3s;color:#ffffff}
.fly-gg{left:68%;animation-duration:23s;animation-delay:5s;color:#34A853}
.fly-ap{left:80%;animation-duration:27s;animation-delay:6s;color:#ffffff}
.fly-tt{left:12%;animation-duration:19s;animation-delay:7s;color:#EE1D52}
.fly-dc{left:38%;animation-duration:25s;animation-delay:8s;color:#5865F2}
.fly-code{left:52%;animation-duration:22s;animation-delay:9s;color:#00d4ff}
.fly-cloud{left:64%;animation-duration:24s;animation-delay:10s;color:#7b2ff7}
.fly-db{left:76%;animation-duration:26s;animation-delay:11s;color:#00b894}
.fly-lock{left:28%;animation-duration:20s;animation-delay:12s;color:#ffcb6b}
.fly-bolt{left:60%;animation-duration:18s;animation-delay:13s;color:#f39c12}
.fly-shield{left:90%;animation-duration:23s;animation-delay:14s;color:#00d4a5}

@keyframes flyMove{
  0%{transform:translateY(0) rotate(-10deg) scale(1);opacity:0}
  8%{opacity:0.45}
  50%{transform:translateY(-50vh) rotate(10deg) scale(1.1);opacity:0.55}
  92%{opacity:0.45}
  100%{transform:translateY(-105vh) rotate(-10deg) scale(1);opacity:0}
}

.moving-name{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:80%;max-width:400px;pointer-events:none;animation:namePulse 5s ease-in-out infinite}
.moving-name svg{width:100%;height:auto}
@keyframes namePulse{
  0%,100%{transform:translate(-50%,-50%) scale(1);opacity:0.6}
  50%{transform:translate(-50%,-50%) scale(1.05);opacity:1}
}

[data-theme="light"] .code-bg{background:linear-gradient(135deg,#f0f4ff,#f7f7fa)}
[data-theme="light"] .fly{opacity:0.35}
[data-theme="light"] .fly-x,[data-theme="light"] .fly-ap{color:#333}

.notice-bar{position:fixed;top:64px;left:0;right:0;max-width:560px;margin:0 auto;background:linear-gradient(135deg,#0ea5e9,#1e3a8a);color:#fff;padding:12px 16px;display:none;align-items:center;gap:10px;z-index:99;font-size:13px;font-weight:600;box-shadow:0 4px 16px rgba(0,0,0,.15);animation:slideDown .4s cubic-bezier(.4,0,.2,1)}
.notice-bar.show{display:flex}
.notice-bar.warning{background:linear-gradient(135deg,#f59e0b,#f97316)}
.notice-bar.success{background:linear-gradient(135deg,#10b981,#059669)}
.notice-bar.danger{background:linear-gradient(135deg,#e94560,#c62a47)}
.notice-bar .n-icon{width:22px;height:22px;flex-shrink:0;display:flex;align-items:center;justify-content:center}
.notice-bar .n-icon svg{width:22px;height:22px;fill:#fff}
.notice-bar .n-text{flex:1;min-width:0}
.notice-bar .n-title{font-weight:800;margin-bottom:2px}
.notice-bar .n-body{font-size:12px;opacity:.9;line-height:1.4}
.notice-bar .n-close{background:rgba(255,255,255,.2);border:none;color:#fff;width:28px;height:28px;border-radius:50%;cursor:pointer;font-size:16px;font-weight:800;display:flex;align-items:center;justify-content:center;flex-shrink:0}
.notice-bar .n-close:active{background:rgba(255,255,255,.4)}
@keyframes slideDown{from{transform:translateY(-100%);opacity:0}to{transform:translateY(0);opacity:1}}

/* ═══ زر ☰ جديد — لا يتدخل مع أي شي ═══ */
.menu-fab{position:fixed;bottom:80px;left:16px;width:52px;height:52px;border-radius:50%;background:linear-gradient(135deg,var(--primary),var(--secondary));border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;box-shadow:0 6px 20px rgba(30,58,138,.4);z-index:99;transition:transform .2s,box-shadow .2s}
.menu-fab:active{transform:scale(.9)}
.menu-fab svg{width:26px;height:26px;fill:#fff}

/* ═══ Bottom Sheet ═══ */
/* ═══ Drawer جانبي ═══ */
.hdr-menu{width:44px;height:44px;border:none;background:transparent;display:flex;align-items:center;justify-content:center;cursor:pointer;border-radius:14px;padding:0;transition:background .2s;-webkit-tap-highlight-color:transparent}
.hdr-menu:hover{background:rgba(123,47,247,.14)}
.hdr-menu svg{width:28px;height:28px;display:block}
.sheet-overlay{display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:transparent;z-index:98}
.sheet-overlay.show{display:block}
.bottom-sheet{display:none;position:fixed;top:0;bottom:0;left:0;right:auto;width:290px;max-width:82vw;box-sizing:border-box;margin:0;padding:72px 0 84px;max-height:none;overflow-y:auto;-webkit-overflow-scrolling:touch;z-index:99;border-radius:0 24px 24px 0;background:rgba(10,10,26,.82);-webkit-backdrop-filter:blur(26px) saturate(150%);backdrop-filter:blur(26px) saturate(150%);border-right:1px solid rgba(123,47,247,.35);box-shadow:8px 0 40px rgba(0,0,0,.4);transform:none;transition:none;will-change:auto;contain:none;--text:#f2f2f7;--text2:#a4a4bd;--border:rgba(255,255,255,.1);--bg:rgba(255,255,255,.08);--primary:#00d4ff}
.bottom-sheet.open{display:block}
html[dir=ltr] .bottom-sheet{left:auto;right:0;border-radius:24px 0 0 24px;border-right:none;border-left:1px solid rgba(123,47,247,.35);box-shadow:-8px 0 40px rgba(0,0,0,.4)}
.bottom-sheet .sheet-handle{display:none}
.bottom-sheet .sheet-item:hover{background:rgba(123,47,247,.2)}
.sheet-handle{width:42px;height:4px;background:var(--border);border-radius:2px;margin:10px auto 6px;opacity:.5}
.sheet-title{padding:6px 18px 10px;font-size:13px;font-weight:800;color:var(--text);border-bottom:1px solid var(--border);display:flex;align-items:center;gap:8px}
.sheet-title svg{width:18px;height:18px;fill:var(--primary)}
.sheet-list{padding:6px 0 12px}
.sheet-item{display:flex;align-items:center;gap:12px;padding:11px 18px;color:var(--text);text-decoration:none;font-size:14px;font-weight:600;cursor:pointer;border:none;background:transparent;width:100%;text-align:right;font-family:inherit;transition:background .2s}
.sheet-item:active{background:rgba(128,128,128,.08)}
.sheet-item svg{width:22px;height:22px;fill:var(--primary);flex-shrink:0;background:transparent;padding:0;border-radius:0}
.sheet-item .lbl{flex:1}
.sheet-item .arrow{width:16px;height:16px;fill:var(--text2);opacity:.5;background:transparent;padding:0;border-radius:0}
.sheet-version{display:flex;align-items:center;justify-content:center;gap:6px;margin:14px auto 6px;font-size:11px;color:#00d4ff;padding:7px 14px;background:linear-gradient(135deg,rgba(0,212,255,.1),rgba(123,47,247,.1));border:1px solid rgba(0,212,255,.3);border-radius:20px;font-weight:700;letter-spacing:.3px;width:fit-content;max-width:90%}
.sheet-version svg{width:14px;height:14px;fill:#00d4ff;flex-shrink:0}

/* بطاقة المستخدم داخل القائمة */
.user-card-sheet{display:flex;align-items:center;gap:12px;padding:14px 16px;margin:10px 12px 8px;border-radius:16px;background:linear-gradient(135deg,rgba(123,47,247,.22),rgba(0,212,255,.15));border:1px solid rgba(123,47,247,.4);box-shadow:0 4px 20px rgba(123,47,247,.2),inset 0 1px 0 rgba(255,255,255,.06);transition:all .25s;text-decoration:none;cursor:pointer;-webkit-user-select:none;user-select:none;-webkit-touch-callout:none;overflow:hidden;box-sizing:border-box;position:relative}
.user-card-sheet::before{content:"";position:absolute;top:0;left:-100%;width:100%;height:100%;background:linear-gradient(90deg,transparent,rgba(255,255,255,.15),transparent);transition:left .6s;pointer-events:none}
.user-card-sheet:active{transform:scale(.98);box-shadow:0 2px 12px rgba(123,47,247,.25)}
.user-card-sheet:active::before{left:100%}
.uc-avatar{width:44px;height:44px;border-radius:50%;background:linear-gradient(135deg,#7b2ff7,#00d4ff);display:flex;align-items:center;justify-content:center;color:#fff;font-weight:900;font-size:22px;flex-shrink:0;overflow:hidden;position:relative;box-shadow:0 4px 14px rgba(123,47,247,.4);border:2.5px solid rgba(255,255,255,.1)}
.uc-avatar img{width:100%;height:100%;object-fit:cover}
.uc-initial{line-height:1}
.uc-online{position:absolute;bottom:-1px;right:-1px;width:14px;height:14px;background:#00d4a5;border:2.5px solid var(--card);border-radius:50%;box-shadow:0 0 8px #00d4a5}
.uc-info{flex:1;min-width:0}
.uc-name{font-size:14px;font-weight:800;color:var(--text);margin-bottom:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.uc-sub{font-size:11px;color:var(--text2);display:flex;align-items:center;gap:4px}
.uc-sub::before{content:none}
.uc-arrow{width:16px;height:16px;fill:var(--primary);opacity:0.9;flex-shrink:0;animation:ucArrow 1.5s ease-in-out infinite}
@keyframes ucArrow{0%,100%{transform:translateX(0)}50%{transform:translateX(-4px)}}
.uc-badge{display:inline-block;font-size:9px;font-weight:900;letter-spacing:.5px;padding:2px 7px;border-radius:6px;background:linear-gradient(135deg,#f59e0b,#f97316);color:#fff;margin-right:4px;vertical-align:middle;box-shadow:0 2px 6px rgba(245,158,11,.5)}

/* فاصل قبل بطاقة المستخدم */
.sheet-item.contact-support{border-bottom:1px solid var(--border);padding-bottom:16px}

/* ═══ شاشة الصيانة — مهندسين ═══ */
.maint-overlay{position:fixed;top:0;left:0;right:0;bottom:0;background:linear-gradient(160deg,#0a0a12,#12121e,#0a0a12);z-index:99999;display:none;align-items:center;justify-content:center;padding:24px;text-align:center;color:#fff;overflow-y:auto}
.maint-overlay.show{display:flex}
.maint-bg{position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:0}
.maint-card{max-width:460px;width:100%;position:relative;z-index:1}

.eng-hero{width:200px;height:200px;margin:0 auto 24px;filter:drop-shadow(0 0 30px rgba(245,158,11,.3))}
.eng-hero svg{width:100%;height:100%;display:block}

.maint-spinner{width:48px;height:48px;border:4px solid rgba(245,158,11,.15);border-top-color:#fbbf24;border-radius:50%;animation:maintSpin 1s linear infinite;margin:0 auto 22px}
@keyframes maintSpin{to{transform:rotate(360deg)}}

.maint-title{font-size:28px;font-weight:900;margin-bottom:14px;background:linear-gradient(135deg,#fbbf24,#f59e0b);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;letter-spacing:.5px}
.maint-body{font-size:15px;color:#b8b8c4;line-height:1.8;margin-bottom:26px}

.maint-progress{width:240px;height:4px;background:rgba(245,158,11,.15);border-radius:2px;margin:0 auto 22px;overflow:hidden}
.maint-progress-bar{height:100%;width:40%;background:linear-gradient(90deg,#fbbf24,#f59e0b,#fbbf24);background-size:200% 100%;animation:engProgress 1.8s ease-in-out infinite;border-radius:2px}
@keyframes engProgress{
0%{margin-left:-40%}
100%{margin-left:100%}
}

.maint-hint{font-size:12px;color:#6e6e78;padding-top:22px;border-top:1px solid rgba(255,255,255,.06)}

/* أيقونة الترس في وسط القائمة للمهندسين */
.eng-mini-icon{display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px}
.eng-mini-icon svg{width:100%;height:100%}

50%{transform:scale(1.3)}}

/* ═══ اللوحة السرية ═══ */
.secret-overlay{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.6);opacity:0;pointer-events:none;transition:opacity .3s;z-index:50000}
.secret-overlay.show{opacity:1;pointer-events:auto}
.secret-panel{position:fixed;top:50%;left:50%;transform:translate(-50%,-50%) scale(.9);background:var(--card);border:1px solid var(--border);border-radius:20px;padding:22px;width:90%;max-width:380px;z-index:50001;opacity:0;pointer-events:none;transition:all .3s cubic-bezier(.34,1.56,.64,1);direction:rtl;box-shadow:0 20px 60px rgba(0,0,0,.5)}
.secret-panel.show{opacity:1;pointer-events:auto;transform:translate(-50%,-50%) scale(1)}
.secret-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:18px;padding-bottom:14px;border-bottom:1px solid var(--border)}
.secret-title{font-size:16px;font-weight:800;color:var(--text);display:flex;align-items:center;gap:8px}
.secret-title svg{width:20px;height:20px;fill:#7b2ff7}
.secret-close{background:transparent;border:none;color:var(--text2);font-size:22px;cursor:pointer;width:32px;height:32px;border-radius:8px;display:flex;align-items:center;justify-content:center}
.secret-close:active{background:rgba(128,128,128,.15)}
.secret-status{padding:12px;border-radius:12px;margin-bottom:14px;text-align:center;font-size:13px;font-weight:700}
.secret-status.on{background:rgba(233,69,96,.15);color:#e94560;border:1px solid rgba(233,69,96,.3)}
.secret-status.off{background:rgba(0,184,148,.15);color:#00d4a5;border:1px solid rgba(0,184,148,.3)}
.secret-btn{width:100%;padding:14px;border:none;border-radius:12px;color:#fff;font-weight:800;font-size:14px;cursor:pointer;font-family:inherit;display:flex;align-items:center;justify-content:center;gap:8px;margin-bottom:10px;transition:transform .15s}
.secret-btn:active{transform:scale(.97)}
.secret-btn.danger{background:linear-gradient(135deg,#e94560,#c62a47)}
.secret-btn.success{background:linear-gradient(135deg,#00b894,#00a884)}
.secret-btn.primary{background:linear-gradient(135deg,#7b2ff7,#00d4ff)}
.secret-textarea{width:100%;padding:12px;border:1px solid var(--border);border-radius:12px;background:var(--bg);color:var(--text);font-size:13px;font-family:inherit;resize:vertical;min-height:70px;outline:none;margin-bottom:10px}
.secret-textarea:focus{border-color:#7b2ff7}
.secret-hint{text-align:center;font-size:11px;color:var(--text2);margin-top:10px;opacity:.6}

/* ═══ زر تخطي الصيانة (سري) ═══ */
.maint-skip{display:none;margin-top:24px;padding:12px 24px;background:rgba(123,47,247,.15);border:1px dashed rgba(123,47,247,.5);border-radius:12px;color:#7b2ff7;font-weight:800;font-size:14px;cursor:pointer;font-family:inherit;text-align:center;transition:all .2s}
.maint-skip.show{display:inline-flex;align-items:center;gap:8px}
.maint-skip:active{transform:scale(.97);background:rgba(123,47,247,.25)}
.maint-skip svg{width:18px;height:18px;fill:#7b2ff7}

/* ═══ شريط المطور (بعد التخطي) ═══ */
.dev-bar{position:fixed;bottom:80px;right:16px;background:linear-gradient(135deg,#7b2ff7,#00d4ff);color:#fff;padding:10px 16px;border-radius:30px;font-size:12px;font-weight:800;box-shadow:0 6px 24px rgba(123,47,247,.4);z-index:9998;display:none;align-items:center;gap:8px;cursor:pointer;font-family:inherit;border:none;direction:rtl}
.dev-bar.show{display:flex}
.dev-bar svg{width:16px;height:16px;fill:#fff}
.dev-bar:active{transform:scale(.95)}

/* ═══ شريط المطور — قائمة سريعة ═══ */
.dev-menu{position:fixed;bottom:130px;right:16px;background:var(--card);border:1px solid var(--border);border-radius:16px;padding:8px;box-shadow:0 10px 40px rgba(0,0,0,.3);z-index:9999;display:none;flex-direction:column;gap:4px;min-width:180px;direction:rtl}
.dev-menu.show{display:flex}
.dev-item{padding:12px 16px;background:transparent;border:none;color:var(--text);font-size:13px;font-weight:600;cursor:pointer;font-family:inherit;text-align:right;border-radius:10px;display:flex;align-items:center;gap:10px;transition:background .2s}
.dev-item:active{background:rgba(128,128,128,.1)}
.dev-item svg{width:18px;height:18px;fill:var(--primary);flex-shrink:0}

/* ═══ اللوحة السرية ═══ */
.secret-overlay{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.6);opacity:0;pointer-events:none;transition:opacity .3s;z-index:50000}
.secret-overlay.show{opacity:1;pointer-events:auto}
.secret-panel{position:fixed;top:50%;left:50%;transform:translate(-50%,-50%) scale(.9);background:var(--card);border:1px solid var(--border);border-radius:20px;padding:22px;width:90%;max-width:380px;z-index:50001;opacity:0;pointer-events:none;transition:all .3s cubic-bezier(.34,1.56,.64,1);direction:rtl;box-shadow:0 20px 60px rgba(0,0,0,.5)}
.secret-panel.show{opacity:1;pointer-events:auto;transform:translate(-50%,-50%) scale(1)}
.secret-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:18px;padding-bottom:14px;border-bottom:1px solid var(--border)}
.secret-title{font-size:16px;font-weight:800;color:var(--text);display:flex;align-items:center;gap:8px}
.secret-title svg{width:20px;height:20px;fill:#7b2ff7}
.secret-close{background:transparent;border:none;color:var(--text2);font-size:22px;cursor:pointer;width:32px;height:32px;border-radius:8px;display:flex;align-items:center;justify-content:center}
.secret-close:active{background:rgba(128,128,128,.15)}
.secret-status{padding:12px;border-radius:12px;margin-bottom:14px;text-align:center;font-size:13px;font-weight:700}
.secret-status.on{background:rgba(233,69,96,.15);color:#e94560;border:1px solid rgba(233,69,96,.3)}
.secret-status.off{background:rgba(0,184,148,.15);color:#00d4a5;border:1px solid rgba(0,184,148,.3)}
.secret-btn{width:100%;padding:14px;border:none;border-radius:12px;color:#fff;font-weight:800;font-size:14px;cursor:pointer;font-family:inherit;display:flex;align-items:center;justify-content:center;gap:8px;margin-bottom:10px;transition:transform .15s}
.secret-btn:active{transform:scale(.97)}
.secret-btn.danger{background:linear-gradient(135deg,#e94560,#c62a47)}
.secret-btn.success{background:linear-gradient(135deg,#00b894,#00a884)}
.secret-btn.primary{background:linear-gradient(135deg,#7b2ff7,#00d4ff)}
.secret-textarea{width:100%;padding:12px;border:1px solid var(--border);border-radius:12px;background:var(--bg);color:var(--text);font-size:13px;font-family:inherit;resize:vertical;min-height:70px;outline:none;margin-bottom:10px}
.secret-textarea:focus{border-color:#7b2ff7}
.secret-hint{text-align:center;font-size:11px;color:var(--text2);margin-top:10px;opacity:.6}

/* ═══ إشعار "انقر مرة ثانية" — نسخة صغيرة أنيقة ═══ */
.tap-hint{position:fixed;top:72px;left:50%;transform:translateX(-50%) translateY(-60px);background:linear-gradient(135deg,#1e3a8a,#0ea5e9);color:#fff;padding:8px 14px;border-radius:30px;display:flex;align-items:center;gap:8px;box-shadow:0 4px 20px rgba(14,165,233,.4);z-index:999999;transition:all .3s cubic-bezier(.34,1.56,.64,1);opacity:0;direction:rtl;font-family:inherit;pointer-events:none;font-size:12px;max-width:85vw}
.tap-hint.show{transform:translateX(-50%) translateY(0);opacity:1}
.tap-hint svg{width:22px;height:22px;flex-shrink:0;filter:drop-shadow(0 0 4px rgba(255,255,255,.3))}
.tap-hint .hint-text{display:flex;align-items:center;gap:6px;text-align:right;white-space:nowrap}
.tap-hint .hint-title{font-weight:700;font-size:12px}
.tap-hint .hint-sub{font-size:11px;opacity:.85}
@keyframes tapPulse{0%,100%{transform:scale(1)}50%{transform:scale(1.1)}}
.tap-hint svg .pulse{animation:tapPulse 1s ease-in-out infinite;transform-origin:center}

/* ==== خلفية مبرمجين ==== */
.code-bg{position:fixed;top:0;left:0;right:0;bottom:0;z-index:-1;overflow:hidden;pointer-events:none;background:var(--bg)}
.code-lines{position:absolute;top:0;left:0;width:100%;height:100%;opacity:0.9}
.ca1{animation:ca1 25s linear infinite}
.ca2{animation:ca2 30s linear infinite}
.ca3{animation:ca3 35s linear infinite}
@keyframes ca1{0%{transform:translateX(-100px);opacity:0}10%{opacity:0.15}50%{opacity:0.2}90%{opacity:0.15}100%{transform:translateX(100px);opacity:0}}
@keyframes ca2{0%{transform:translateX(100px);opacity:0}10%{opacity:0.12}50%{opacity:0.18}90%{opacity:0.12}100%{transform:translateX(-100px);opacity:0}}
@keyframes ca3{0%{transform:translateX(-80px);opacity:0}10%{opacity:0.1}50%{opacity:0.15}90%{opacity:0.1}100%{transform:translateX(80px);opacity:0}}
.la1{animation:la1 8s ease-in-out infinite}
.la2{animation:la2 10s ease-in-out infinite}
.la3{animation:la3 12s ease-in-out infinite}
@keyframes la1{0%,100%{transform:translateX(0);opacity:0.3}50%{transform:translateX(200px);opacity:0.8}}
@keyframes la2{0%,100%{transform:translateX(0);opacity:0.4}50%{transform:translateX(-250px);opacity:0.9}}
@keyframes la3{0%,100%{transform:translateX(0);opacity:0.3}50%{transform:translateX(300px);opacity:0.7}}
.float-symbols{position:absolute;top:0;left:0;right:0;bottom:0;overflow:hidden}
.fs{position:absolute;font-family:monospace;font-weight:900;opacity:0.12;text-shadow:0 0 20px currentColor;animation:floatUp linear infinite;bottom:-50px}


@keyframes floatUp{0%{bottom:-50px;opacity:0;transform:translateY(0) rotate(0deg)}10%{opacity:0.15}90%{opacity:0.15}100%{bottom:110%;opacity:0;transform:translateY(-30px) rotate(360deg)}}
.fpl-1{left:8%;width:50px;height:50px;animation-duration:22s;animation-delay:0.9s}
.fpl-2{left:25%;width:60px;height:60px;animation-duration:26s;animation-delay:1.8s}
.fpl-3{left:42%;width:55px;height:55px;animation-duration:20s;animation-delay:2.7s}
.fpl-4{left:58%;width:65px;height:65px;animation-duration:24s;animation-delay:3.6s}
.fpl-5{left:72%;width:52px;height:52px;animation-duration:19s;animation-delay:4.5s}
.fpl-6{left:88%;width:58px;height:58px;animation-duration:25s;animation-delay:5.4s}
.fpl-7{left:15%;width:62px;height:62px;animation-duration:21s;animation-delay:6.3s}
.fpl-8{left:35%;width:56px;height:56px;animation-duration:23s;animation-delay:7.2s}
.fpl-9{left:52%;width:54px;height:54px;animation-duration:27s;animation-delay:8.1s}
.fpl-10{left:82%;width:48px;height:48px;animation-duration:18s;animation-delay:9.0s}
.matrix{position:absolute;top:0;left:0;right:0;bottom:0;overflow:hidden;display:flex;justify-content:space-around}
.mtx{font-family:monospace;font-size:14px;font-weight:900;color:#00d4ff;opacity:0;letter-spacing:14px;text-shadow:0 0 8px #00d4ff;animation:matrixFall linear infinite;writing-mode:vertical-rl}
.mtx:nth-child(1){animation-duration:8s}
.mtx:nth-child(2){animation-duration:10s;animation-delay:1.5s}
.mtx:nth-child(3){animation-duration:9s;animation-delay:3s}
.mtx:nth-child(4){animation-duration:11s;animation-delay:0.8s}
.mtx:nth-child(5){animation-duration:7s;animation-delay:2.2s}
.mtx:nth-child(6){animation-duration:12s;animation-delay:4s}
@keyframes matrixFall{0%{transform:translateY(-100%);opacity:0}5%{opacity:0.35}95%{opacity:0.35}100%{transform:translateY(100vh);opacity:0}}
.code-icon{position:absolute;bottom:10%;right:5%;width:200px;height:200px;opacity:0.5;animation:pulseIcon 6s ease-in-out infinite}
@keyframes pulseIcon{0%,100%{transform:scale(1) rotate(0deg);opacity:0.3}50%{transform:scale(1.1) rotate(5deg);opacity:0.5}}
[data-theme="light"] .code-bg{background:linear-gradient(135deg,#f0f4ff,#f7f7fa)}
[data-theme="light"] .fs{opacity:0.08}
[data-theme="light"] .mtx{color:#7b2ff7;text-shadow:0 0 8px #7b2ff7}


/* زر استكشف العائم */
.explore-wrap{position:fixed;bottom:78px;left:16px;z-index:99;display:flex;flex-direction:column;align-items:center;gap:4px;text-decoration:none}
.explore-fab{width:48px;height:48px;border-radius:50%;background:linear-gradient(135deg,#7b2ff7,#00d4ff);border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;box-shadow:0 6px 18px rgba(123,47,247,.45);transition:all .25s}
.explore-wrap:active .explore-fab{transform:scale(.9)}
.explore-fab svg{width:22px;height:22px;fill:#fff}
.explore-lbl{font-size:10px;font-weight:700;color:#00d4ff;letter-spacing:.3px;background:rgba(10,10,20,.7);padding:2px 8px;border-radius:8px;border:1px solid rgba(0,212,255,.2)}


/* ألوان الصيانة */
.maint-overlay[data-color="gold"] .maint-title{background:linear-gradient(135deg,#fbbf24,#f59e0b);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.maint-overlay[data-color="purple"] .maint-title{background:linear-gradient(135deg,#c8a2ff,#7b2ff7);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.maint-overlay[data-color="cyan"] .maint-title{background:linear-gradient(135deg,#a8d8ff,#00d4ff);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.maint-overlay[data-color="green"] .maint-title{background:linear-gradient(135deg,#6fe3c1,#00d4a5);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.maint-overlay[data-color="gold"] .maint-spinner{border-color:rgba(245,158,11,.15);border-top-color:#fbbf24}
.maint-overlay[data-color="purple"] .maint-spinner{border-color:rgba(123,47,247,.15);border-top-color:#c8a2ff}
.maint-overlay[data-color="cyan"] .maint-spinner{border-color:rgba(0,212,255,.15);border-top-color:#00d4ff}
.maint-overlay[data-color="green"] .maint-spinner{border-color:rgba(0,212,165,.15);border-top-color:#00d4a5}
.maint-overlay[data-color="gold"] .maint-progress-bar{background:linear-gradient(90deg,#fbbf24,#f59e0b,#fbbf24);background-size:200% 100%}
.maint-overlay[data-color="purple"] .maint-progress-bar{background:linear-gradient(90deg,#c8a2ff,#7b2ff7,#c8a2ff);background-size:200% 100%}
.maint-overlay[data-color="cyan"] .maint-progress-bar{background:linear-gradient(90deg,#00d4ff,#0099cc,#00d4ff);background-size:200% 100%}
.maint-overlay[data-color="green"] .maint-progress-bar{background:linear-gradient(90deg,#00d4a5,#00b894,#00d4a5);background-size:200% 100%}

/* ═══ LITE MODE — الصفحة الرئيسية ═══ */
html.lite-mode * {
    animation-duration: .001s !important;
    transition-duration: .05s !important;
}
html.lite-mode .code-bg,
html.lite-mode .fly,
html.lite-mode .matrix,
html.lite-mode .moving-name,
html.lite-mode .fs,
html.lite-mode .mtx {
    display: none !important;
}
html.lite-mode .bottom-nav,
html.lite-mode .header {
    backdrop-filter: none !important;
    -webkit-backdrop-filter: none !important;
}
html.lite-mode .card,
html.lite-mode .num-card,
html.lite-mode .btn,
html.lite-mode .nav-btn {
    box-shadow: none !important;
}
html.lite-mode .page-title {
    background: var(--primary) !important;
}
html.lite-mode .offline-bar {
    backdrop-filter: none !important;
    -webkit-backdrop-filter: none !important;
}
</style>
</head>
<body>
<!-- إشعار عدم الاتصال -->
<div class="offline-bar" id="offlineBar">
<svg viewBox="0 0 24 24" class="offline-icon">
<!-- wifi مقطوع -->
<path class="wifi-arc" d="M12 3C7.5 3 3.5 4.6 0.5 7.2L2 9C4.5 6.8 8 5.4 12 5.4S19.5 6.8 22 9L23.5 7.2C20.5 4.6 16.5 3 12 3Z" opacity="0.35"/>
<path class="wifi-arc" d="M12 8C9 8 6.3 9 4.2 10.7L5.7 12.5C7.4 11.1 9.6 10.3 12 10.3S16.6 11.1 18.3 12.5L19.8 10.7C17.7 9 15 8 12 8Z" opacity="0.5"/>
<circle cx="12" cy="16" r="2" fill="#fff"/>
<line x1="4" y1="20" x2="20" y2="4" stroke="#fff" stroke-width="2.2" stroke-linecap="round"/>
</svg>
<span id="offlineText">لا يوجد اتصال بالإنترنت — تعمل من الكاش</span>
</div>

<!-- شاشة الصيانة -->
<div class="maint-overlay" id="maintOverlay" data-icon="{{ maint_icon }}" data-color="{{ maint_color }}">

<!-- خلفية هندسية متحركة -->
<svg class="maint-bg" viewBox="0 0 400 800" preserveAspectRatio="xMidYMid slice" xmlns="http://www.w3.org/2000/svg">
<defs>
<linearGradient id="mBg1" x1="0%" y1="0%" x2="100%" y2="100%">
<stop offset="0%" stop-color="#f59e0b" stop-opacity="0.08"/>
<stop offset="100%" stop-color="#e67e22" stop-opacity="0.02"/>
</linearGradient>
<pattern id="mGrid" width="40" height="40" patternUnits="userSpaceOnUse">
<path d="M 40 0 L 0 0 0 40" fill="none" stroke="#f59e0b" stroke-width="0.3" opacity="0.15"/>
</pattern>
</defs>
<rect width="400" height="800" fill="url(#mGrid)"/>
<!-- خطوط هندسية طايرة -->
<g stroke="#f59e0b" stroke-width="0.6" fill="none" opacity="0.25">
<circle cx="80" cy="120" r="30" stroke-dasharray="4 3">
<animate attributeName="r" values="30;38;30" dur="6s" repeatCount="indefinite"/>
</circle>
<circle cx="320" cy="650" r="45" stroke-dasharray="5 4">
<animate attributeName="r" values="45;55;45" dur="8s" repeatCount="indefinite"/>
</circle>
<rect x="280" y="180" width="50" height="50" stroke-dasharray="4 3" transform="rotate(45 305 205)">
<animate attributeName="opacity" values="0.15;0.5;0.15" dur="5s" repeatCount="indefinite"/>
</rect>
<line x1="20" y1="400" x2="120" y2="500">
<animate attributeName="opacity" values="0.1;0.4;0.1" dur="4s" repeatCount="indefinite"/>
</line>
<line x1="300" y1="300" x2="380" y2="200">
<animate attributeName="opacity" values="0.1;0.4;0.1" dur="5s" repeatCount="indefinite"/>
</line>
</g>
</svg>

<div class="maint-card">

<!-- الأيقونة الرئيسية -->
<div class="eng-hero">
<svg viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg">
<defs>
<linearGradient id="eGold" x1="0%" y1="0%" x2="100%" y2="100%">
<stop offset="0%" stop-color="#fbbf24"/>
<stop offset="100%" stop-color="#f59e0b"/>
</linearGradient>
<linearGradient id="eGoldDark" x1="0%" y1="0%" x2="100%" y2="100%">
<stop offset="0%" stop-color="#d97706"/>
<stop offset="100%" stop-color="#92400e"/>
</linearGradient>
<filter id="eGlow">
<feGaussianBlur stdDeviation="3" result="blur"/>
<feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
</filter>
</defs>

<!-- دائرة الخلفية -->
<circle cx="100" cy="100" r="85" fill="none" stroke="url(#eGold)" stroke-width="1.5" opacity="0.3" stroke-dasharray="3 4">
<animateTransform attributeName="transform" type="rotate" from="0 100 100" to="360 100 100" dur="30s" repeatCount="indefinite"/>
</circle>
<circle cx="100" cy="100" r="75" fill="none" stroke="url(#eGold)" stroke-width="0.8" opacity="0.2"/>

<!-- ترس كبير -->
<g filter="url(#eGlow)">
<g>
<animateTransform attributeName="transform" type="rotate" from="0 100 90" to="360 100 90" dur="20s" repeatCount="indefinite"/>
<circle cx="100" cy="90" r="42" fill="none" stroke="url(#eGold)" stroke-width="3"/>
<circle cx="100" cy="90" r="24" fill="none" stroke="url(#eGold)" stroke-width="2.5"/>
<g fill="url(#eGold)">
<rect x="96" y="42" width="8" height="14" rx="2"/>
<rect x="96" y="124" width="8" height="14" rx="2"/>
<rect x="42" y="86" width="14" height="8" rx="2"/>
<rect x="144" y="86" width="14" height="8" rx="2"/>
<rect x="55" y="55" width="8" height="12" rx="2" transform="rotate(-45 59 61)"/>
<rect x="137" y="55" width="8" height="12" rx="2" transform="rotate(45 141 61)"/>
<rect x="55" y="113" width="8" height="12" rx="2" transform="rotate(45 59 119)"/>
<rect x="137" y="113" width="8" height="12" rx="2" transform="rotate(-45 141 119)"/>
</g>
</g>
</g>

<!-- مسطرة -->
<g>
<animateTransform attributeName="transform" type="rotate" from="-12 100 90" to="8 100 90" dur="4s" repeatCount="indefinite" values="-12 100 90;8 100 90;-12 100 90"/>
<rect x="55" y="140" width="90" height="16" rx="3" fill="url(#eGoldDark)" stroke="url(#eGold)" stroke-width="1.5"/>
<!-- علامات المسطرة -->
<g stroke="url(#eGold)" stroke-width="1.2">
<line x1="65" y1="142" x2="65" y2="148"/>
<line x1="75" y1="142" x2="75" y2="146"/>
<line x1="85" y1="142" x2="85" y2="148"/>
<line x1="95" y1="142" x2="95" y2="146"/>
<line x1="105" y1="142" x2="105" y2="148"/>
<line x1="115" y1="142" x2="115" y2="146"/>
<line x1="125" y1="142" x2="125" y2="148"/>
<line x1="135" y1="142" x2="135" y2="146"/>
</g>
</g>

<!-- قلم رصاص مائل -->
<g transform="translate(160 60) rotate(-30)">
<rect x="0" y="0" width="10" height="60" fill="url(#eGoldDark)" stroke="url(#eGold)" stroke-width="1"/>
<path d="M 0 60 L 5 75 L 10 60 Z" fill="#fbbf24"/>
<rect x="0" y="0" width="10" height="12" fill="#dc2626"/>
<rect x="0" y="12" width="10" height="6" fill="#cbd5e1"/>
</g>

<!-- فرجار -->
<g transform="translate(35 50) rotate(20)" opacity="0.85">
<line x1="10" y1="0" x2="0" y2="55" stroke="url(#eGold)" stroke-width="2.5" stroke-linecap="round"/>
<line x1="10" y1="0" x2="20" y2="55" stroke="url(#eGold)" stroke-width="2.5" stroke-linecap="round"/>
<circle cx="10" cy="0" r="4" fill="url(#eGoldDark)" stroke="url(#eGold)" stroke-width="1"/>
<circle cx="0" cy="55" r="3" fill="url(#eGold)"/>
<circle cx="20" cy="55" r="3" fill="url(#eGold)"/>
</g>

<!-- نقاط لمعان -->
<circle cx="40" cy="40" r="2" fill="#fbbf24">
<animate attributeName="opacity" values="0.2;1;0.2" dur="2s" repeatCount="indefinite"/>
</circle>
<circle cx="165" cy="35" r="1.5" fill="#fbbf24">
<animate attributeName="opacity" values="0.2;1;0.2" dur="2.5s" repeatCount="indefinite"/>
</circle>
<circle cx="30" cy="160" r="2" fill="#fbbf24">
<animate attributeName="opacity" values="0.2;1;0.2" dur="3s" repeatCount="indefinite"/>
</circle>
</svg>
</div>

<!-- السبنر -->
<div class="maint-spinner"></div>

<!-- العنوان -->
<div class="maint-title" id="maintTitle">{{ maint_title|default("الموقع تحت الصيانة") }}</div>
<div class="maint-body" id="maintBody">{{ maint_body|default("نعتذر عن الإزعاج، سنعود قريباً")|safe }}</div>

<!-- شريط التقدم -->
<div class="maint-progress">
<div class="maint-progress-bar"></div>
</div>

<!-- التذييل -->
<div class="maint-hint">شكراً لصبركم</div>

</div>
</div>

<div class="header">
<div class="title">
<button id="backBtn" onclick="goBack()" style="display:none;width:42px;height:42px;border:none;background:transparent;cursor:pointer;align-items:center;justify-content:center;border-radius:12px;transition:background .2s" onmouseover="this.style.background='rgba(255,255,255,0.1)'" onmouseout="this.style.background='transparent'">
<svg viewBox="0 0 24 24" style="width:24px;height:24px;fill:var(--text)">
<path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z"/>
</svg>
</button>
<span class="title-text" id="headerTitle" style="display:flex;align-items:center;gap:10px;font-size:18px">
<svg viewBox="0 0 80 60" width="72" height="54" style="flex-shrink:0;overflow:visible">
<defs>
<linearGradient id="skin" x1="0%" y1="0%" x2="0%" y2="100%">
<stop offset="0%" stop-color="#F5C9A0"/>
<stop offset="100%" stop-color="#E0A87C"/>
</linearGradient>
<linearGradient id="shirt" x1="0%" y1="0%" x2="100%" y2="100%">
<stop offset="0%" stop-color="#1e3a8a"/>
<stop offset="100%" stop-color="#0ea5e9"/>
</linearGradient>
<linearGradient id="phone" x1="0%" y1="0%" x2="100%" y2="100%">
<stop offset="0%" stop-color="#0a0a12"/>
<stop offset="100%" stop-color="#1e293b"/>
</linearGradient>
<linearGradient id="screen" x1="0%" y1="0%" x2="100%" y2="100%">
<stop offset="0%" stop-color="#0ea5e9"/>
<stop offset="100%" stop-color="#7b2ff7"/>
</linearGradient>
<linearGradient id="hair" x1="0%" y1="0%" x2="0%" y2="100%">
<stop offset="0%" stop-color="#2a1810"/>
<stop offset="100%" stop-color="#4a2c1a"/>
</linearGradient>
<filter id="shadow">
<feGaussianBlur stdDeviation="0.4"/>
</filter>
</defs>

<!-- ظل أرضي -->
<ellipse cx="30" cy="57" rx="16" ry="2" fill="#000" opacity="0.25"/>

<!-- جسم/قميص -->
<path d="M 12 56 Q 12 36 30 36 Q 48 36 48 56 Z" fill="url(#shirt)">
<animate attributeName="d" values="M 12 56 Q 12 36 30 36 Q 48 36 48 56 Z;M 12 55 Q 12 35 30 35 Q 48 35 48 55 Z;M 12 56 Q 12 36 30 36 Q 48 36 48 56 Z" dur="2.5s" repeatCount="indefinite"/>
</path>

<!-- رقبة -->
<rect x="26" y="30" width="8" height="8" fill="url(#skin)"/>

<!-- رأس -->
<ellipse cx="30" cy="22" rx="10" ry="11" fill="url(#skin)">
<animate attributeName="cy" values="22;21;22" dur="2.5s" repeatCount="indefinite"/>
</ellipse>

<!-- شعر -->
<path d="M 20 18 Q 22 8 30 8 Q 38 8 40 18 Q 38 12 30 12 Q 22 12 20 18 Z" fill="url(#hair)">
<animate attributeName="d" values="M 20 18 Q 22 8 30 8 Q 38 8 40 18 Q 38 12 30 12 Q 22 12 20 18 Z;M 20 17 Q 22 7 30 7 Q 38 7 40 17 Q 38 11 30 11 Q 22 11 20 17 Z;M 20 18 Q 22 8 30 8 Q 38 8 40 18 Q 38 12 30 12 Q 22 12 20 18 Z" dur="2.5s" repeatCount="indefinite"/>
</path>
<path d="M 20 18 Q 18 14 20 12 Q 22 14 22 18 Z" fill="url(#hair)"/>
<path d="M 40 18 Q 42 14 40 12 Q 38 14 38 18 Z" fill="url(#hair)"/>

<!-- عيون -->
<circle cx="26" cy="21" r="1.2" fill="#1a1a1a">
<animate attributeName="r" values="1.2;1.2;0.2;1.2" dur="4s" repeatCount="indefinite"/>
</circle>
<circle cx="34" cy="21" r="1.2" fill="#1a1a1a">
<animate attributeName="r" values="1.2;1.2;0.2;1.2" dur="4s" repeatCount="indefinite"/>
</circle>
<circle cx="26.3" cy="20.7" r="0.4" fill="#fff"/>
<circle cx="34.3" cy="20.7" r="0.4" fill="#fff"/>

<!-- فم مبتسم -->
<path d="M 27 26 Q 30 28 33 26" stroke="#8B4513" stroke-width="0.9" fill="none" stroke-linecap="round"/>

<!-- ذراع يمسك الهاتف -->
<path d="M 42 42 Q 50 40 54 36" stroke="url(#shirt)" stroke-width="4" stroke-linecap="round" fill="none">
<animate attributeName="d" values="M 42 42 Q 50 40 54 36;M 42 41 Q 50 39 54 35;M 42 42 Q 50 40 54 36" dur="2.5s" repeatCount="indefinite"/>
</path>

<!-- يد -->
<ellipse cx="55" cy="35" rx="3" ry="2.5" fill="url(#skin)"/>

<!-- الهاتف الذكي -->
<g>
<animate attributeName="transform" type="translate" values="0,0; 0,-1; 0,0" dur="2.5s" repeatCount="indefinite"/>
<rect x="51" y="22" width="14" height="24" rx="2.5" fill="url(#phone)" stroke="#334155" stroke-width="0.6"/>
<rect x="52.2" y="23.5" width="11.6" height="19" rx="1.5" fill="url(#screen)"/>
<!-- خطوط داخل الشاشة (محاكاة تطبيق) -->
<rect x="53.5" y="25" width="9" height="1.5" rx="0.5" fill="#ffffff" opacity="0.4"/>
<rect x="53.5" y="27.5" width="7" height="1.5" rx="0.5" fill="#ffffff" opacity="0.3"/>
<rect x="53.5" y="30" width="9" height="1.5" rx="0.5" fill="#ffffff" opacity="0.3"/>

<!-- كلمة OTP تظهر حرف حرف -->
<text x="58" y="38" font-size="4.5" font-weight="900" fill="#ffffff" text-anchor="middle" font-family="monospace">
<animate attributeName="opacity" values="1" dur="1s"/>
</text>
<!-- O -->
<text x="54.5" y="38" font-size="4.5" font-weight="900" fill="#00d4a5" font-family="monospace">O
<animate attributeName="opacity" values="0;1;1;1;0" dur="3s" repeatCount="indefinite" begin="0s"/>
</text>
<!-- T -->
<text x="58" y="38" font-size="4.5" font-weight="900" fill="#00d4a5" font-family="monospace">T
<animate attributeName="opacity" values="0;0;1;1;0" dur="3s" repeatCount="indefinite" begin="0s"/>
</text>
<!-- P -->
<text x="61.5" y="38" font-size="4.5" font-weight="900" fill="#00d4a5" font-family="monospace">P
<animate attributeName="opacity" values="0;0;0;1;0" dur="3s" repeatCount="indefinite" begin="0s"/>
</text>
</g>

<!-- وميض الشاشة -->
<rect x="51" y="22" width="14" height="24" rx="2.5" fill="#00d4ff" opacity="0">
<animate attributeName="opacity" values="0;0.15;0" dur="2s" repeatCount="indefinite"/>
</rect>

<!-- إشارات wifi/otp تخرج من الهاتف -->
<circle cx="68" cy="20" r="1.5" fill="#00d4ff">
<animate attributeName="opacity" values="0;1;0" dur="1.8s" repeatCount="indefinite"/>
<animate attributeName="cy" values="22;14;6" dur="1.8s" repeatCount="indefinite"/>
<animate attributeName="cx" values="66;68;70" dur="1.8s" repeatCount="indefinite"/>
</circle>
<circle cx="70" cy="22" r="1.2" fill="#7b2ff7">
<animate attributeName="opacity" values="0;1;0" dur="1.8s" repeatCount="indefinite" begin="0.6s"/>
<animate attributeName="cy" values="24;16;8" dur="1.8s" repeatCount="indefinite" begin="0.6s"/>
<animate attributeName="cx" values="68;71;74" dur="1.8s" repeatCount="indefinite" begin="0.6s"/>
</circle>
<circle cx="72" cy="24" r="1" fill="#00d4a5">
<animate attributeName="opacity" values="0;1;0" dur="1.8s" repeatCount="indefinite" begin="1.2s"/>
<animate attributeName="cy" values="26;18;10" dur="1.8s" repeatCount="indefinite" begin="1.2s"/>
<animate attributeName="cx" values="70;73;76" dur="1.8s" repeatCount="indefinite" begin="1.2s"/>
</circle>
</svg>
<span class="brand-text" style="font-weight:800;background:var(--gradient);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text">المطري OTP</span>
</span>
</div>
<div class="hdr-actions">
<button type="button" class="hdr-menu" id="hdrMenu" onclick="toggleSheet()" aria-label="القائمة">
<svg viewBox="0 0 24 24" fill="none" stroke="url(#hdrMenuGrad)" stroke-width="2.4" stroke-linecap="round"><defs><linearGradient id="hdrMenuGrad" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#7b2ff7"/><stop offset="1" stop-color="#00d4ff"/></linearGradient></defs><path d="M4 7h16M4 12h16M4 17h16"/></svg>
</button>
</div>
</div>

<div class="content">
<div class="page active" id="page-platforms">
<div class="page-title">
<svg viewBox="0 0 24 24"><path d="M4 6h16v2H4zm0 5h16v2H4zm0 5h16v2H4z"/></svg>
<span id="ttl_platforms">اختر المنصة</span>
</div>
<div id="platformsList"></div>
</div>
<div class="page" id="page-countries">
<div class="page-title">
<svg viewBox="0 0 24 24"><path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z"/></svg>
<span id="ttl_countries">اختر الدولة</span>
</div>
<div id="countriesList"></div>
</div>
<div class="page" id="page-numbers">
<div class="page-title">
<svg viewBox="0 0 24 24"><path d="M6.62 10.79c1.44 2.83 3.76 5.14 6.59 6.59l2.2-2.2c.27-.27.67-.36 1.02-.24 1.12.37 2.33.57 3.57.57.55 0 1 .45 1 1V20c0 .55-.45 1-1 1-9.39 0-17-7.61-17-17 0-.55.45-1 1-1h3.5c.55 0 1 .45 1 1 0 1.25.2 2.45.57 3.57.11.35.03.74-.25 1.02l-2.2 2.2z"/></svg>
<span id="ttl_numbers">الأرقام</span>
</div>
<div id="numbersList"></div>
</div>

</div>

<a href="/explore" class="explore-wrap" aria-label="استكشف">
<div class="explore-fab">
<svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm2.19 12.19L6 18l3.81-8.19L18 6l-3.81 8.19zM12 11c-.55 0-1 .45-1 1s.45 1 1 1 1-.45 1-1-.45-1-1-1z"/></svg>
</div>
<span class="explore-lbl" id="exploreLbl">استكشف</span>
</a>

<div class="bottom-nav">
<button class="nav-btn active" id="nav_home" onclick="navTo('platforms')"><svg viewBox="0 0 24 24"><path d="M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z"/></svg><span id="nav_home_txt">الرئيسية</span></button>
<button class="nav-btn" id="nav_support" onclick="openMySupport()"><span style="position:relative;display:inline-flex;align-items:center;justify-content:center"><svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/></svg><span id="supportBadge" style="display:none;position:absolute;top:-6px;right:-8px;background:#e94560;color:#fff;font-size:9px;font-weight:800;min-width:16px;height:16px;border-radius:8px;padding:0 4px;align-items:center;justify-content:center;box-shadow:0 2px 6px rgba(233,69,96,.7);border:1.5px solid var(--card);line-height:1">0</span></span><span id="nav_support_txt">الدعم</span></button>
<button class="nav-btn" onclick="toggleTheme()"><svg viewBox="0 0 24 24" id="darkIcon"><path d="M12 3a9 9 0 109 9c0-.46-.04-.92-.1-1.36a5.389 5.389 0 01-4.4 2.26 5.403 5.403 0 01-3.14-9.8c-.44-.06-.9-.1-1.36-.1z"/></svg><span id="nav_dark_txt">ليلي</span></button>
<button class="nav-btn" onclick="toggleLang()"><svg viewBox="0 0 24 24"><path d="M12.87 15.07l-2.54-2.51.03-.03A17.52 17.52 0 0014.07 6H17V4h-7V2H8v2H1v2h11.17C11.5 7.92 10.44 9.75 9 11.35 8.07 10.32 7.3 9.19 6.69 8h-2c.73 1.63 1.73 3.17 2.98 4.56l-5.09 5.02L4 19l5-5 3.11 3.11.76-2.04z"/></svg><span id="nav_lang_txt">EN</span></button>
</div>

<!-- ==== خلفية مبرمجين ==== -->
<div class="code-bg" aria-hidden="true">
  <!-- شبكة SVG خفيفة -->
  <svg class="tech-bg" viewBox="0 0 100 100" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
    <defs>
      <pattern id="gridPattern" width="10" height="10" patternUnits="userSpaceOnUse">
        <path d="M 10 0 L 0 0 0 10" fill="none" stroke="rgba(0,212,255,0.05)" stroke-width="0.15"/>
      </pattern>
    </defs>
    <rect width="100" height="100" fill="url(#gridPattern)"/>
  </svg>

  <!-- منصات outline أحادية اللون -->
  <svg class="fly fly-wa" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 01-.9 3.8 8.5 8.5 0 01-7.6 4.7 8.38 8.38 0 01-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 01-.9-3.8 8.5 8.5 0 014.7-7.6 8.38 8.38 0 013.8-.9h.5a8.48 8.48 0 018 8v.5z"/></svg>

  <svg class="fly fly-tg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4 20-7z"/></svg>

  <svg class="fly fly-fb" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M18 2h-3a5 5 0 00-5 5v3H7v4h3v8h4v-8h3l1-4h-4V7a1 1 0 011-1h3z"/></svg>

  <svg class="fly fly-ig" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="20" rx="5" ry="5"/><path d="M16 11.37A4 4 0 1112.63 8 4 4 0 0116 11.37z"/><line x1="17.5" y1="6.5" x2="17.51" y2="6.5"/></svg>

  <svg class="fly fly-x" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4l16 16M20 4L4 20"/></svg>

  <svg class="fly fly-gg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 8v8M8 12h8"/></svg>

  <svg class="fly fly-ap" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2C8 6 8 12 12 18c4-6 4-12 0-16z"/></svg>

  <svg class="fly fly-tt" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18a4 4 0 104-4V2c1 3 4 5 7 5"/></svg>

  <svg class="fly fly-dc" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="12" r="1"/><circle cx="15" cy="12" r="1"/><path d="M7 7c3-1 7-1 10 0 2 3 3 7 2 11-3 1-7 1-10 0-1-4 0-8-2-11z"/></svg>

  <svg class="fly fly-code" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>

  <svg class="fly fly-cloud" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M18 10h-1.26A8 8 0 109 20h9a5 5 0 000-10z"/></svg>

  <svg class="fly fly-db" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v6c0 1.66 4 3 9 3s9-1.34 9-3V5"/><path d="M3 11v6c0 1.66 4 3 9 3s9-1.34 9-3v-6"/></svg>

  <svg class="fly fly-lock" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0110 0v4"/></svg>

  <svg class="fly fly-bolt" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>

  <svg class="fly fly-shield" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>

  <!-- الاسم في المنتصف -->
  <div class="moving-name">
    <svg viewBox="0 0 400 100" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <linearGradient id="mvGrad" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stop-color="#00d4ff"/>
          <stop offset="50%" stop-color="#7b2ff7"/>
          <stop offset="100%" stop-color="#00d4ff"/>
        </linearGradient>
      </defs>
      <text x="200" y="62" font-family="monospace, sans-serif" font-size="46" font-weight="900" fill="none" stroke="url(#mvGrad)" stroke-width="1.2" text-anchor="middle" opacity="0.5">{{ background_name }}</text>
      <text x="200" y="62" font-family="monospace, sans-serif" font-size="46" font-weight="900" fill="url(#mvGrad)" text-anchor="middle" opacity="0.15">{{ background_name }}</text>
    </svg>
  </div>
</div>

<div class="notice-bar" id="noticeBar">
<span class="n-icon" id="nIcon"></span>
<div class="n-text">
<div class="n-title" id="nTitle"></div>
<div class="n-body" id="nBody"></div>
</div>
<button class="n-close" onclick="closeNotice()">×</button>
</div>

<div class="toast" id="toast">تم النسخ!</div>

<!-- مؤشر التحديث -->
<div class="update-progress" id="updateProgress"></div>

<!-- زر التحديث (يظهر فقط عند وجود تحديث معلق) -->
<button class="update-banner" id="updateBanner" onclick="applyUpdate()" style="display:none">
<svg viewBox="0 0 24 24"><path d="M17.65 6.35A7.958 7.958 0 0012 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0112 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/></svg>
<div class="update-text">
<div class="update-title">🔄 تحديث جديد متوفر</div>
<div class="update-sub">اضغط للتحديث الآن</div>
</div>
<div class="update-btn">تحديث</div>
</button>

<!-- شريط المطور -->
<button class="dev-bar" id="devBar" onclick="toggleDevMenu()">
<svg viewBox="0 0 24 24"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg>
وضع المطور
</button>

<div class="dev-menu" id="devMenu">
<button class="dev-item" onclick="previewMaintenance()">
<svg viewBox="0 0 24 24"><path d="M12 4.5C7 4.5 2.73 7.61 1 12c1.73 4.39 6 7.5 11 7.5s9.27-3.11 11-7.5c-1.73-4.39-6-7.5-11-7.5zM12 17c-2.76 0-5-2.24-5-5s2.24-5 5-5 5 2.24 5 5-2.24 5-5 5zm0-8c-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3-1.34-3-3-3z"/></svg>
معاينة شاشة الصيانة
</button>
<button class="dev-item" onclick="openSecretPanel()">
<svg viewBox="0 0 24 24"><path d="M18 8h-1V6c0-2.76-2.24-5-5-5S7 3.24 7 6v2H6c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V10c0-1.1-.9-2-2-2z"/></svg>
لوحة الصيانة
</button>
<button class="dev-item" onclick="stopSkipping()">
<svg viewBox="0 0 24 24"><path d="M17 7l-1.41 1.41L18.17 11H8v2h10.17l-2.58 2.58L17 17l5-5zM4 5h8V3H4c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h8v-2H4V5z"/></svg>
الخروج من التخطي
</button>
</div>

<!-- ═══ Bottom Sheet ═══ -->
<div class="sheet-overlay" id="sheetOverlay" onclick="closeSheet()"></div>
<div class="bottom-sheet" id="bottomSheet">
<div class="sheet-handle"></div>


<div style="height:14px"></div>
<div class="sheet-list">
{% if user_name %}
<a href="/profile" class="user-card-sheet" style="text-decoration:none">
<div class="uc-avatar">
{% if user_avatar %}
<img src="{{ user_avatar }}" alt="{{ user_name }}">
{% else %}
<span class="uc-initial">{{ (user_name or 'U')[0]|upper }}</span>
{% endif %}
<div class="uc-online"></div>
</div>
<div class="uc-info">
<div class="uc-name">{{ user_name or 'مستخدم' }} <span class="uc-badge">PRO</span></div>
<div class="uc-sub">اضغط لعرض ملفك الشخصي</div>
</div>
<svg class="uc-arrow" viewBox="0 0 24 24"><path d="M10 6L8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z"/></svg>
</a>
{% endif %}
<button class="sheet-item" onclick="installPWA()">
<svg viewBox="0 0 24 24"><path d="M17 1.01L7 1c-1.1 0-2 .9-2 2v18c0 1.1.9 2 2 2h10c1.1 0 2-.9 2-2V3c0-1.1-.9-1.99-2-1.99zM17 19H7V5h10v14zm-4-4V9h-2v6H8.5l3.5 3.5L15.5 15H13z"/></svg>
<span class="lbl" id="sht_install">ثبّت التطبيق</span>
<svg class="arrow" viewBox="0 0 24 24"><path d="M10 6L8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z"/></svg>
</button>
<button class="sheet-item" onclick="shareSite()">
<svg viewBox="0 0 24 24"><path d="M18 16.08c-.76 0-1.44.3-1.96.77L8.91 12.7c.05-.23.09-.46.09-.7s-.04-.47-.09-.7l7.05-4.11c.54.5 1.25.81 2.04.81 1.66 0 3-1.34 3-3s-1.34-3-3-3-3 1.34-3 3c0 .24.04.47.09.7L8.04 9.81C7.5 9.31 6.79 9 6 9c-1.66 0-3 1.34-3 3s1.34 3 3 3c.79 0 1.5-.31 2.04-.81l7.12 4.16c-.05.21-.08.43-.08.65 0 1.61 1.31 2.92 2.92 2.92s2.92-1.31 2.92-2.92-1.31-2.92-2.92-2.92z"/></svg>
<span class="lbl" id="sht_share">شارك الموقع</span>
<svg class="arrow" viewBox="0 0 24 24"><path d="M10 6L8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z"/></svg>
</button>
<button class="sheet-item" onclick="openHistory()">
<svg viewBox="0 0 24 24"><path d="M13 3c-4.97 0-9 4.03-9 9H1l3.89 3.89.07.14L9 12H6c0-3.87 3.13-7 7-7s7 3.13 7 7-3.13 7-7 7c-1.93 0-3.68-.79-4.94-2.06l-1.42 1.42C8.27 19.99 10.51 21 13 21c4.97 0 9-4.03 9-9s-4.03-9-9-9zm-1 5v5l4.28 2.54.72-1.21-3.5-2.08V8H12z"/></svg>
<span class="lbl" id="sht_history">سجل الأكواد</span>
<svg class="arrow" viewBox="0 0 24 24"><path d="M10 6L8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z"/></svg>
</button>

<button class="sheet-item" onclick="if(window.toggleLiteMode) window.toggleLiteMode()">
<svg viewBox="0 0 24 24" style="fill:#fbbf24"><path d="M13 3h-2v10h2V3zm4.83 2.17l-1.42 1.42C17.99 7.86 19 9.81 19 12c0 3.87-3.13 7-7 7s-7-3.13-7-7c0-2.19 1.01-4.14 2.59-5.42L6.17 5.17C4.23 6.82 3 9.26 3 12c0 4.97 4.03 9 9 9s9-4.03 9-9c0-2.74-1.23-5.18-3.17-6.83z"/></svg>
<span class="lbl" id="sht_lite">الأداء العالي</span>
<svg class="arrow" viewBox="0 0 24 24"><path d="M10 6L8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z"/></svg>
</button>

<button class="sheet-item" onclick="if(window.toggleSound) window.toggleSound()">
<svg viewBox="0 0 24 24" fill="none" stroke="#00d4a5" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 5L6 9H2v6h4l5 4V5z"/><path d="M15.54 8.46a5 5 0 010 7.07"/><path d="M19.07 4.93a10 10 0 010 14.14"/></svg>
<span class="lbl" id="sht_sound">تشغيل/إيقاف الأصوات</span>
<svg class="arrow" viewBox="0 0 24 24"><path d="M10 6L8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z"/></svg>
</button>
<button class="sheet-item" onclick="openAbout()">
<svg viewBox="0 0 24 24"><path d="M11 7h2v2h-2zm0 4h2v6h-2zm1-9C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8z"/></svg>
<span class="lbl" id="sht_about">عن الموقع</span>
<svg class="arrow" viewBox="0 0 24 24"><path d="M10 6L8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z"/></svg>
</button>
<button class="sheet-item" onclick="contactSupport()">
<svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm-2 12H6v-2h12v2zm0-3H6V9h12v2zm0-3H6V6h12v2z"/></svg>
<span class="lbl" id="sht_contact">تواصل معنا</span>
<svg class="arrow" viewBox="0 0 24 24"><path d="M10 6L8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z"/></svg>
</button>
{% if user_name %}
<a class="sheet-item sheet-logout" href="/logout" style="text-decoration:none;border-top:1px solid var(--border)">
<svg viewBox="0 0 24 24" style="fill:#e94560"><path d="M17 7l-1.41 1.41L18.17 11H8v2h10.17l-2.58 2.58L17 17l5-5zM4 5h8V3H4c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h8v-2H4V5z"/></svg>
<span class="lbl" style="color:#e94560">خروج</span>
<svg class="arrow" viewBox="0 0 24 24"><path d="M10 6L8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z"/></svg>
</a>
{% endif %}
</div>
<div class="sheet-version">
<svg viewBox="0 0 24 24"><path d="M12 2L3 7v5c0 5 4 9 9 10 5-1 9-5 9-10V7l-9-5zm-1 14l-4-4 1.41-1.41L11 13.17l5.59-5.59L18 9l-7 7z"/></svg>
<span>{{ site_name }} — الإصدار 1.0</span>
</div>
</div>

<script>
var TREE = {{ tree|safe }};
const COUNTRY_DATA = {{ countries_json|safe }};
const PLATFORM_ICONS = {{ icons|safe }};
const SETTINGS = {{ settings_json|safe }};

const PLATFORM_NAMES_EN = {
    "واتساب": "WhatsApp",
    "واتساب بزنس": "WhatsApp Business",
    "تيليجرام": "Telegram",
    "فيسبوك": "Facebook",
    "انستقرام": "Instagram",
    "تويتر": "Twitter",
    "جوجل": "Google",
    "آبل": "Apple",
    "أبل آي دي": "Apple ID",
    "تيك توك": "TikTok",
    "ديسكورد": "Discord",
    "سناب": "Snapchat",
    "سناب شات": "Snapchat",
    "أخرى": "Other"
};

function platformName(ar_name){
    if(currentLang === 'en' && PLATFORM_NAMES_EN[ar_name]){
        return PLATFORM_NAMES_EN[ar_name];
    }
    return ar_name;
}

const COUNTRY_NAMES_EN = {
    "مصر": "Egypt", "السعودية": "Saudi Arabia", "اليمن": "Yemen",
    "الإمارات": "UAE", "تونس": "Tunisia", "روسيا": "Russia",
    "أمريكا": "USA", "كندا/أمريكا": "USA/Canada", "بريطانيا": "UK",
    "ألمانيا": "Germany", "فرنسا": "France", "تركيا": "Turkey",
    "العراق": "Iraq", "سوريا": "Syria", "الأردن": "Jordan",
    "لبنان": "Lebanon", "فلسطين": "Palestine", "الكويت": "Kuwait",
    "قطر": "Qatar", "البحرين": "Bahrain", "عُمان": "Oman",
    "المغرب": "Morocco", "الجزائر": "Algeria", "ليبيا": "Libya",
    "السودان": "Sudan", "الصومال": "Somalia", "موريتانيا": "Mauritania",
    "الهند": "India", "باكستان": "Pakistan", "بنغلاديش": "Bangladesh",
    "إندونيسيا": "Indonesia", "ماليزيا": "Malaysia", "الفلبين": "Philippines",
    "الصين": "China", "اليابان": "Japan", "كوريا الجنوبية": "South Korea",
    "تايلاند": "Thailand", "فيتنام": "Vietnam", "سنغافورة": "Singapore",
    "أستراليا": "Australia", "كندا": "Canada", "البرازيل": "Brazil",
    "المكسيك": "Mexico", "الأرجنتين": "Argentina", "إسبانيا": "Spain",
    "إيطاليا": "Italy", "هولندا": "Netherlands", "بلجيكا": "Belgium",
    "السويد": "Sweden", "النرويج": "Norway", "الدنمارك": "Denmark",
    "بولندا": "Poland", "أوكرانيا": "Ukraine", "اليونان": "Greece",
    "البرتغال": "Portugal", "سويسرا": "Switzerland", "النمسا": "Austria",
    "أيرلندا": "Ireland", "فنلندا": "Finland", "أفغانستان": "Afghanistan",
    "إيران": "Iran", "أرمينيا": "Armenia", "أذربيجان": "Azerbaijan",
    "كازاخستان": "Kazakhstan", "أوزبكستان": "Uzbekistan", "جورجيا": "Georgia"
};

function countryName(ar_name){
    if(currentLang === 'en' && COUNTRY_NAMES_EN[ar_name]){
        return COUNTRY_NAMES_EN[ar_name];
    }
    return ar_name;
}

let currentLang = localStorage.getItem('lang') || 'ar';
let currentTheme = localStorage.getItem('theme') || 'light';
let currentPlatform = null;
let currentCountry = null;
let numberPage = 0;
const NUMBERS_PER_PAGE = 3;

const T = {
    ar: {home:'الرئيسية', support:'الدعم', dark:'ليلي', lang:'EN', choose_platform:'اختر المنصة', choose_country:'اختر الدولة', numbers:'الأرقام', choose_platform_title:'اختر المنصة', choose_country_title:'اختر الدولة', numbers_title:'الأرقام', switch_numbers:'تبديل الرقمين', codes_toggle:'الأكواد الواصلة', fetch_otp:'تحديث OTP', copying:'جاري الجلب...', sheet_title:'خيارات إضافية', sht_install:'ثبّت التطبيق', sht_share:'شارك الموقع', sht_fav:'المفضلة', sht_history:'سجل الأكواد', sht_cache:'مسح الكاش والتحديث', sht_about:'عن الموقع', sht_contact:'تواصل معنا', no_data:'لا توجد بيانات', no_countries:'لا توجد دول', no_numbers:'لا توجد أرقام', fetch_code:'جلب كود تلقائي', fetching:'جاري الجلب...', waiting:'في انتظار الأكواد...', received:'وصلت الأكواد:', sec:'ث', back:'رجوع', switch:'تبديل', copied:'تم النسخ!'},
    en: {home:'Home', support:'Support', dark:'Dark', lang:'AR', choose_platform:'Choose Platform', choose_country:'Choose Country', numbers:'Numbers', choose_platform_title:'Choose Platform', choose_country_title:'Choose Country', numbers_title:'Numbers', switch_numbers:'Switch Numbers', codes_toggle:'Received Codes', fetch_otp:'Refresh OTP', copying:'Fetching...', sheet_title:'Extra Options', sht_install:'Install App', sht_share:'Share Site', sht_fav:'Favorites', sht_history:'Codes History', sht_cache:'Clear Cache & Refresh', sht_about:'About', sht_contact:'Contact Us', no_data:'No data', no_countries:'No countries', no_numbers:'No numbers', fetch_code:'Fetch Codes', fetching:'Fetching...', waiting:'Waiting for codes...', received:'Codes received:', sec:'s', back:'Back', switch:'Switch', copied:'Copied!'}
};
function t(k){ return T[currentLang][k] || k; }

// أصوات النقر الناعمة
(function(){
    var ac = null, on = localStorage.getItem('snd_on') !== '0';
    function init(){
        if(!ac){ try { ac = new (window.AudioContext || window.webkitAudioContext)(); } catch(e){} }
        if(ac && ac.state === 'suspended') ac.resume();
    }
    function play(freq, dur, vol){
        if(!on) return;
        init(); if(!ac) return;
        try {
            var o = ac.createOscillator();
            var g = ac.createGain();
            // موجة جيبية + موجة تربيعية خفيفة = دفء
            o.type = 'sine';
            o.frequency.value = freq;
            // فِلتر لتنعيم الصوت
            var filter = ac.createBiquadFilter();
            filter.type = 'lowpass';
            filter.frequency.value = 2000;
            g.gain.setValueAtTime(0, ac.currentTime);
            g.gain.linearRampToValueAtTime(vol, ac.currentTime + 0.02);
            g.gain.exponentialRampToValueAtTime(0.0001, ac.currentTime + dur);
            o.connect(filter); filter.connect(g); g.connect(ac.destination);
            o.start(); o.stop(ac.currentTime + dur);
        } catch(e){}
    }
    window._sTap = function(){ play(587, 0.12, 0.04); };
    window._sClick = function(){ play(784, 0.09, 0.035); };
    window._sSuccess = function(){ play(659, 0.15, 0.04); setTimeout(function(){ play(988, 0.2, 0.035); }, 90); };
    window._sNav = function(){ play(523, 0.1, 0.035); };
    window._sWarn = function(){ play(440, 0.15, 0.04); };

    document.addEventListener('click', function(e){
        var el = e.target.closest ? e.target.closest('.nav-btn,.card,.copy-btn,.code-cp,.auto-fetch-btn,.sheet-item,.btn,.tb,.lnk,.icon-btn,.menu-fab,.send,.del,.cdel') : null;
        if(!el || el.disabled) return;
        if(el.classList.contains('copy-btn') || el.classList.contains('code-cp')) window._sSuccess();
        else if(el.classList.contains('nav-btn') || el.classList.contains('tb')) window._sNav();
        else if(el.classList.contains('card') || el.classList.contains('sheet-item') || el.classList.contains('lnk')) window._sTap();
        else if(el.classList.contains('del') || el.classList.contains('cdel') || el.classList.contains('btn-red')) window._sWarn();
        else window._sClick();
    }, true);

    // تهيئة أول لمسة
    document.addEventListener('touchstart', function once(){ init(); document.removeEventListener('touchstart', once); }, {passive:true, once:true});

    window.toggleSound = function(){
        on = !on;
        localStorage.setItem('snd_on', on ? '1' : '0');
        if(on) window._sClick();
        if(typeof showToast === 'function') showToast(on ? 'مفعلة' : 'مكتومة');
        return on;
    };
})();

function applyTheme(){
    document.documentElement.setAttribute('data-theme', currentTheme);
    // زر الليلي — لو موجود
    var themeIcon = document.getElementById('darkIcon');
    if(themeIcon){
        themeIcon.innerHTML = currentTheme === 'dark'
            ? '<path d="M12 7c-2.76 0-5 2.24-5 5s2.24 5 5 5 5-2.24 5-5-2.24-5-5-5zM2 13h2c.55 0 1-.45 1-1s-.45-1-1-1H2c-.55 0-1 .45-1 1s.45 1 1 1zm18 0h2c.55 0 1-.45 1-1s-.45-1-1-1h-2c-.55 0-1 .45-1 1s.45 1 1 1z"/>'
            : '<path d="M12 3a9 9 0 109 9c0-.46-.04-.92-.1-1.36a5.389 5.389 0 01-4.4 2.26 5.403 5.403 0 01-3.14-9.8c-.44-.06-.9-.1-1.36-.1z"/>';
    }
}
function toggleTheme(){
    currentTheme = currentTheme === 'light' ? 'dark' : 'light';
    try { localStorage.setItem('theme', currentTheme); } catch(err){}
    applyTheme();
    var txt = document.getElementById('nav_dark_txt');
    if(txt) txt.textContent = currentTheme === 'dark' ? 'نهاري' : 'ليلي';
}
function toggleLang(){
    currentLang = currentLang === 'ar' ? 'en' : 'ar';
    try { localStorage.setItem('lang', currentLang); } catch(err){}
    document.documentElement.lang = currentLang;
    document.documentElement.dir = currentLang === 'ar' ? 'rtl' : 'ltr';
    var nh = document.getElementById('nav_home_txt');
    var ns = document.getElementById('nav_support_txt');
    var nd = document.getElementById('nav_dark_txt');
    var nl = document.getElementById('nav_lang_txt');
    if(nh) nh.textContent = t('home');
    if(ns) ns.textContent = t('support');
    if(nd) nd.textContent = currentTheme === 'dark' ? (currentLang === 'ar' ? 'نهاري' : 'Light') : t('dark');
    if(nl) nl.textContent = t('lang');
    // ترجمة القائمة الجانبية
    var sht = {
        sheet_title_txt: 'sheet_title',
        sht_install: 'sht_install',
        sht_share: 'sht_share',
        sht_profile: 'sht_profile',
        sht_history: 'sht_history',
        sht_cache: 'sht_cache',
        sht_about: 'sht_about',
        sht_contact: 'sht_contact'
    };
    for(var id in sht){
        var el = document.getElementById(id);
        if(el) el.textContent = t(sht[id]);
    }
    // ترجمة زر استكشف
    var el = document.getElementById('exploreLbl');
    if(el) el.textContent = currentLang === 'ar' ? 'استكشف' : 'Explore';
    // ترجمة العناوين
    var ttl1 = document.getElementById('ttl_platforms');
    var ttl2 = document.getElementById('ttl_countries');
    var ttl3 = document.getElementById('ttl_numbers');
    if(ttl1) ttl1.textContent = t('choose_platform_title');
    if(ttl2) ttl2.textContent = t('choose_country_title');
    if(ttl3) ttl3.textContent = t('numbers_title');
    renderCurrent();
}

function showPage(name){
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.getElementById('page-' + name).classList.add('active');
    document.querySelector('.content').scrollTop = 0;
}

function navTo(name){
    if(name === 'support'){
        window.location.href = '/support';
        return;
    }
    currentPlatform = null;
    currentCountry = null;
    numberPage = 0;
    document.getElementById('backBtn').style.display = 'none';
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    document.getElementById('nav_home').classList.add('active');
    renderPlatforms();
}

async function _refreshTree(){
    try {
        var r = await fetch('/api/tree?t=' + Date.now(), {cache: 'no-store'});
        if(r.ok){
            var d = await r.json();
            if(d && typeof d === 'object'){
                TREE = d;
            }
        }
    } catch(e){}
}

function renderPlatforms(){
    // حدّث TREE في الخلفية — بدون انتظار
    _refreshTree();
    const list = document.getElementById('platformsList');
    const platforms = Object.keys(TREE);
    if(platforms.length === 0){ list.innerHTML = '<div class="empty">' + t('no_data') + '</div>'; showPage('platforms'); return; }
    let html = '<div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;width:100%">';
    html += platforms.map(p => {
        const icon = PLATFORM_ICONS[p] || PLATFORM_ICONS['أخرى'];
        const count = Object.keys(TREE[p]).length;
        const displayName = platformName(p);
        return '<div class="card" style="padding:12px;gap:8px;margin:0;min-width:0;position:relative" onclick="selectPlatform(\'' + p.replace(/'/g, "\'") + '\')">' +
            '<div class="card-count" style="position:absolute;top:6px;left:6px;margin:0;font-size:10px;padding:2px 7px;min-width:auto;background:var(--gradient)">' + count + '</div>' +
            '<div class="card-icon" style="width:40px;height:40px;background:transparent;padding:0;flex-shrink:0">' + icon + '</div>' +
            '<div class="card-name" style="font-size:13px;font-weight:600;white-space:nowrap;overflow:visible">' + displayName + '</div>' +
        '</div>';
    }).join('');
    html += '</div>';
    list.innerHTML = html;
    showPage('platforms');
}

function selectPlatform(name){
    currentPlatform = name;
    currentCountry = null;
    numberPage = 0;
    // ═══ نرسل المنصة للسيرفر ═══
    try {
        fetch('/api/set-platform', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({platform: name})
        }).catch(function(){});
    } catch(e) {}
    document.getElementById('backBtn').style.display = 'flex';
    renderCountries();
}

function renderCountries(){
    const list = document.getElementById('countriesList');
    if(!TREE[currentPlatform]){
        currentPlatform = null;
        renderPlatforms();
        return;
    }
    const countries = Object.keys(TREE[currentPlatform]);
    if(countries.length === 0){ list.innerHTML = '<div class="empty">' + t('no_countries') + '</div>'; showPage('countries'); return; }
    list.innerHTML = countries.map(c => {
        const nums = TREE[currentPlatform][c];
        const flag = getFlag(c);
        const displayName = countryName(c);
        return '<div class="card" onclick="selectCountry(\'' + c.replace(/'/g, "\'") + '\')">' +
            '<div class="card-icon">' + flag + '</div>' +
            '<div class="card-name">' + displayName + '</div>' +
            '<div class="card-count">' + nums.length + '</div>' +
        '</div>';
    }).join('');
    showPage('countries');
}

function selectCountry(name){
    currentCountry = name;
    numberPage = 0;
    // استرجع الأكواد من localStorage
    const saved = localStorage.getItem('savedCodes_' + currentPlatform + '_' + currentCountry);
    if(saved){
        try { savedCodes = JSON.parse(saved); } catch(e){ savedCodes = []; }
    } else {
        savedCodes = [];
    }
    // زامن مع السيرفر فوراً (لو الأدمن حذف شي)
    fetch('/api/codes/list').then(r => r.json()).then(serverCodes => {
        const serverPhones = new Set(serverCodes.map(c => c.phone));
        const filtered = savedCodes.filter(c => serverPhones.has(c.phone));
        if(filtered.length !== savedCodes.length){
            savedCodes = filtered;
            localStorage.setItem('savedCodes_' + currentPlatform + '_' + currentCountry, JSON.stringify(savedCodes));
        }
        renderNumbers();
    }).catch(() => renderNumbers());
}

function getFlag(country){
    const nums = TREE[currentPlatform][country];
    if(!nums || nums.length === 0) return PLATFORM_ICONS['أخرى'];
    const first = nums[0].replace(/\s/g, '');
    for(const code in COUNTRY_DATA){
        if(first.startsWith(code)) return COUNTRY_DATA[code].flag;
    }
    return PLATFORM_ICONS['أخرى'];
}

let currentNumbers = [];
let savedCodes = [];

function renderNumbers(){
    const list = document.getElementById('numbersList');
    if(!TREE[currentPlatform]){
        currentPlatform = null; currentCountry = null;
        renderPlatforms();
        return;
    }
    if(!TREE[currentPlatform][currentCountry]){
        currentCountry = null;
        renderCountries();
        return;
    }
    const nums = TREE[currentPlatform][currentCountry];
    if(nums.length === 0){ list.innerHTML = '<div class="empty">' + t('no_numbers') + '</div>'; showPage('numbers'); return; }

    // اختر رقمين حسب عدد الصفحة
    const start = (numberPage * 2) % nums.length;
    currentNumbers = [];
    for(let i = 0; i < 2; i++){
        currentNumbers.push(nums[(start + i) % nums.length]);
    }

    const flag = getFlag(currentCountry);

    // ═══ الرقمين فوق ═══
    let html = currentNumbers.map(n =>
        '<div class="num-card">' +
            '<div class="card-icon">' + flag + '</div>' +
            '<div class="num-info">' +
                '<div class="num-country">' + countryName(currentCountry) + '</div>' +
                '<div class="num-phone">' + n + '</div>' +
            '</div>' +
            '<button class="copy-btn" onclick="copyNumber(this, \'' + n + '\')">' +
                '<svg viewBox="0 0 24 24"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg>' +
            '</button>' +
        '</div>'
    ).join('');

    // ═══ زر تبديل الرقمين ═══
    html += '<button class="auto-fetch-btn" onclick="switchNumbers()" id="switchBtn" style="margin:14px 0 8px">' +
        '<svg viewBox="0 0 24 24" fill="#fff"><path d="M17 1l4 4-4 4V6H3V4h14V1zM7 23l-4-4 4-4v3h14v2H7v3z"/></svg>' +
        ' <span>' + t('switch_numbers') + '</span>' +
    '</button>';

    // ═══ زر الأكواد الواصلة ═══
    html += '<button class="codes-toggle-btn" id="codesToggle" onclick="toggleCodes()">' +
        '<svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/></svg>' +
        ' <span id="codesBtnTxt">' + t('codes_toggle') + '</span> (' + savedCodes.length + ')' +
        '<svg class="arrow" viewBox="0 0 24 24"><path d="M7 10l5 5 5-5z"/></svg>' +
    '</button>';

    // ═══ صندوق الأكواد ═══
    html += '<div class="codes-list" id="codesList">';
    if(savedCodes.length > 0){
        html += savedCodes.map((item, idx) =>
            '<div class="code-card">' +
                '<div class="code-head">' +
                    '<span class="phone">' + item.phone + '</span>' +
                    '<span class="time">' + (item.time || '--:--') + '</span>' +
                '</div>' +
                '<div class="code-body">' +
                    '<div class="cd" data-start="' + (item.timestamp || Date.now()) + '">' +
                        '<svg viewBox="0 0 34 34"><circle class="cd-bg" cx="17" cy="17" r="14"/><circle class="cd-fg" cx="17" cy="17" r="14" stroke-dasharray="87.96" stroke-dashoffset="0"/></svg>' +
                        '<span class="cd-num">60</span>' +
                    '</div>' +
                    '<span class="code-num-big">' + item.code + '</span>' +
                    '<button class="code-cp" onclick="copyNumber(this, \'' + item.code + '\')">' +
                        '<svg viewBox="0 0 24 24"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg>' +
                    '</button>' +
                '</div>' +
            '</div>'
        ).join('');
        html += '<button class="auto-fetch-btn" onclick="copyAllCodes()" style="margin:0;background:linear-gradient(135deg,#00b894,#00a884);box-shadow:0 6px 20px rgba(0,184,148,.3)">' +
            '<svg viewBox="0 0 24 24" fill="#fff"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg>' +
            ' نسخ كل الأكواد (' + savedCodes.length + ')' +
        '</button>';
    }
    html += '</div>';

    // ═══ زر تحديث OTP ═══
    html += '<button class="auto-fetch-btn" onclick="fetchOTP()" id="otpBtn" style="margin:14px 0 8px">' +
        '<svg viewBox="0 0 24 24" fill="#fff"><path d="M17.65 6.35A7.958 7.958 0 0012 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0112 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/></svg>' +
        ' <span id="otpBtnTxt">' + t('fetch_otp') + '</span>' +
    '</button>';

    list.innerHTML = html;
    showPage('numbers');
}

function switchNumbers(){
    const nums = TREE[currentPlatform][currentCountry];
    numberPage = (numberPage + 1) % Math.ceil(nums.length / 2);
    renderNumbers();
}

async function fetchOTP(){
    const btn = document.getElementById('otpBtn');
    btn.disabled = true;
    btn.innerHTML = '<div class="spinner-sm"></div> ' + t('copying');

    for(let i = 0; i < currentNumbers.length; i++){
        const phone = currentNumbers[i];
        try {
            const r = await fetch('/api/check-otp/' + encodeURIComponent(phone), {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({platform: currentPlatform || ''})
            });
            const d = await r.json();
            if(d.code){
                // احفظ في السيرفر
                fetch('/api/codes/save', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({phone: phone, code: d.code})
                }).catch(function(){});
                // شوف إذا الكود موجود مسبقاً
                const exists = savedCodes.find(c => c.phone === phone && c.code === d.code);
                if(!exists){
                    const now = new Date();
                    const timeStr = now.getHours().toString().padStart(2,'0') + ':' + now.getMinutes().toString().padStart(2,'0');
                    savedCodes.push({phone: phone, code: d.code, time: timeStr, timestamp: Date.now()});
                }
            }
        } catch(e) {}
        // انتظر شوي بين كل رقم
        await new Promise(r => setTimeout(r, 800));
    }

    btn.disabled = false;
    btn.innerHTML = '<svg viewBox="0 0 24 24" fill="#fff"><path d="M17.65 6.35A7.958 7.958 0 0012 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0112 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/></svg> ' + t('fetch_otp');

    // احفظ في localStorage (مربوط بالمنصة + الدولة)
    localStorage.setItem('savedCodes_' + currentPlatform + '_' + currentCountry, JSON.stringify(savedCodes));

    renderNumbers();
}

function nextNumbers(){ numberPage++; renderNumbers(); }
function prevNumbers(){ if(numberPage > 0) numberPage--; renderNumbers(); }

function goBack(){
    if(currentCountry){ currentCountry = null; renderCountries(); }
    else if(currentPlatform){ currentPlatform = null; document.getElementById('backBtn').style.display = 'none'; renderPlatforms(); }
}

function copyAllCodes(){
    if(savedCodes.length === 0) return;
    const text = savedCodes.map(c => c.phone + ' → ' + c.code).join('\n');
    navigator.clipboard.writeText(text).then(() => {
        const toast = document.getElementById('toast');
        toast.textContent = 'تم نسخ ' + savedCodes.length + ' أكواد!';
        toast.classList.add('show');
        setTimeout(() => toast.classList.remove('show'), 1500);
    });
}

function copyNumber(btn, text){
    function done(){
        btn.classList.add('copied');
        btn.innerHTML = '<svg viewBox="0 0 24 24"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>';
        const toast = document.getElementById('toast');
        toast.textContent = t('copied');
        toast.classList.add('show');
        setTimeout(() => toast.classList.remove('show'), 1500);
        setTimeout(() => { btn.classList.remove('copied'); btn.innerHTML = '<svg viewBox="0 0 24 24"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg>'; }, 1500);
    }
    if(navigator.clipboard && navigator.clipboard.writeText){
        navigator.clipboard.writeText(text).then(done).catch(done);
    } else { done(); }
}

function renderCurrent(){
    if(currentCountry) renderNumbers();
    else if(currentPlatform) renderCountries();
    else renderPlatforms();
}


// ═══ مزامنة الأكواد مع السيرفر ═══
async function syncCodesWithServer(){
    if(!currentPlatform || !currentCountry) return;
    try {
        const r = await fetch('/api/codes/list');
        const serverCodes = await r.json();
        // فلترة أكواد الدولة الحالية
        const nums = TREE[currentPlatform] && TREE[currentPlatform][currentCountry] ? TREE[currentPlatform][currentCountry] : [];
        const serverPhones = new Set(serverCodes.map(c => c.phone));
        // احتفظ بس الأكواد الموجودة في السيرفر
        const filtered = savedCodes.filter(c => serverPhones.has(c.phone));
        // لو تغير شي → احفظ
        if(filtered.length !== savedCodes.length){
            savedCodes = filtered;
            localStorage.setItem('savedCodes_' + currentPlatform + '_' + currentCountry, JSON.stringify(savedCodes));
            renderNumbers();
        }
    } catch(e){}
}
// اشتغل كل 30 ثانية (أخف)
setInterval(syncCodesWithServer, 30000);


// ═══ فتح الدعم — بنقرة واحدة ═══
function openSupport(e){
    if(navigator.vibrate) navigator.vibrate(20);
    window.location.href = '/support';
}

function openMySupport(){
    window.location.href = '/support';
}

// ═══ فتح/قفل صندوق الأكواد ═══
function toggleCodes(){
    var btn = document.getElementById('codesToggle');
    var list = document.getElementById('codesList');
    if(!btn || !list) return;
    btn.classList.toggle('open');
    list.classList.toggle('open');
}

// ═══ العدّاد الدائري ═══
var CIRC = 2 * Math.PI * 14; // 87.96
function tickTimers(){
    document.querySelectorAll('.cd[data-start]').forEach(function(el){
        var start = parseInt(el.dataset.start);
        var diff = Math.floor((Date.now() - start) / 1000);
        var left = Math.max(0, 60 - diff);
        var num = el.querySelector('.cd-num');
        var fg = el.querySelector('.cd-fg');
        if(!num || !fg) return;
        fg.style.strokeDashoffset = CIRC * (1 - left / 60);
        num.textContent = left > 0 ? left : '✓';
        el.classList.remove('warn','danger','done');
        if(left === 0) el.classList.add('done');
        else if(left <= 15) el.classList.add('danger');
        else if(left <= 30) el.classList.add('warn');
    });
}
tickTimers();
setInterval(tickTimers, 1000);

// ═══ إشعارات وصول كود جديد ═══
let _lastTelegramCount = 0;
let _audioCtx = null;

function playNotifySound(){
    try {
        if(!_audioCtx) _audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        // صوت جميل — نغمة مزدوجة
        const now = _audioCtx.currentTime;
        const osc1 = _audioCtx.createOscillator();
        const osc2 = _audioCtx.createOscillator();
        const gain = _audioCtx.createGain();
        osc1.connect(gain);
        osc2.connect(gain);
        gain.connect(_audioCtx.destination);
        osc1.frequency.value = 880;
        osc2.frequency.value = 1320;
        osc1.type = 'sine';
        osc2.type = 'sine';
        gain.gain.setValueAtTime(0, now);
        gain.gain.linearRampToValueAtTime(0.2, now + 0.05);
        gain.gain.linearRampToValueAtTime(0.15, now + 0.15);
        gain.gain.linearRampToValueAtTime(0, now + 0.4);
        osc1.start(now);
        osc2.start(now);
        osc1.stop(now + 0.4);
        osc2.stop(now + 0.4);
    } catch(e){}
}

function vibrateDevice(){
    try {
        if(navigator.vibrate) navigator.vibrate([100, 50, 100]);
    } catch(e){}
}

function showNotification(text){
    try {
        if(!("Notification" in window)) return;
        if(Notification.permission === "granted"){
            new Notification("كود جديد وصل!", {
                body: text,
                icon: "/icon-192.png",
                badge: "/icon-192.png",
                vibrate: [100, 50, 100]
            });
        }
    } catch(e){}
}

function showToast(text){
    let toast = document.getElementById('notifyToast');
    if(!toast){
        toast = document.createElement('div');
        toast.id = 'notifyToast';
        toast.className = 'notify-toast';
        document.body.appendChild(toast);
    }
    toast.textContent = text;
    toast.classList.add('show');
    setTimeout(() => toast.classList.remove('show'), 3000);
}

async function checkNewTelegramCodes(){
    try {
        const r = await fetch('/api/telegram/status');
        const d = await r.json();
        const count = d.codes_count || 0;

        if(_lastTelegramCount > 0 && count > _lastTelegramCount){
            // كود جديد وصل!
            const diff = count - _lastTelegramCount;
            const recent = d.recent_codes && d.recent_codes.length > 0 ? d.recent_codes[d.recent_codes.length - 1] : null;
            const text = recent ? (recent.brand + " | " + (recent.phone_last || '') + " | " + recent.code) : "كود جديد";
            playNotifySound();
            vibrateDevice();
            showToast("" + diff + " كود جديد وصل!");
            showNotification(text);
            // حدّث الأكواد إذا كنا في صفحة الأرقام
            if(currentCountry){
                setTimeout(() => fetchOTP(), 500);
            }
        }
        _lastTelegramCount = count;
    } catch(e){}
}

// اشتغل كل 5 ثواني — أبطأ على الأجهزة الضعيفة
(function(){
    var lite = document.documentElement.classList.contains('lite-mode');
    setInterval(checkNewTelegramCodes, lite ? 20000 : 6000);
})();

// اطلب إذن الإشعارات
// ═══ الإشعار الداخلي ═══
var _lastNoticeId = "";

async function checkNotice(){
    try {
        var r = await fetch('/api/notice');
        var d = await r.json();
        if(!d.active){
            var bar = document.getElementById('noticeBar');
            if(bar) bar.classList.remove('show');
            return;
        }
        // ✅ الأدمن يشوف الإشعار دايماً — بدون cache
        var isAdmin = SETTINGS && SETTINGS.is_admin;
        if(!isAdmin){
            // تحقق إذا المستخدم شاف الإشعار
            var seen = localStorage.getItem('notice_seen_' + d.id);
            if(seen) return;
        }
        // اعرض الإشعار
        var bar = document.getElementById('noticeBar');
        var icon = document.getElementById('nIcon');
        var title = document.getElementById('nTitle');
        var body = document.getElementById('nBody');
        if(!bar) return;
        bar.classList.remove('warning', 'success', 'danger');
        var type = d.type || 'info';
        // أيقونات SVG
        var SVG_INFO = '<svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/></svg>';
        var SVG_WARN = '<svg viewBox="0 0 24 24"><path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/></svg>';
        var SVG_OK = '<svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg>';
        var SVG_ERR = '<svg viewBox="0 0 24 24"><path d="M12 2C6.47 2 2 6.47 2 12s4.47 10 10 10 10-4.47 10-10S17.53 2 12 2zm5 13.59L15.59 17 12 13.41 8.41 17 7 15.59 10.59 12 7 8.41 8.41 7 12 10.59 15.59 7 17 8.41 13.41 12 17 15.59z"/></svg>';
        if(type === 'warning'){ bar.classList.add('warning'); icon.innerHTML = SVG_WARN; }
        else if(type === 'success'){ bar.classList.add('success'); icon.innerHTML = SVG_OK; }
        else if(type === 'danger'){ bar.classList.add('danger'); icon.innerHTML = SVG_ERR; }
        else { icon.innerHTML = SVG_INFO; }
        title.textContent = d.title || '';
        body.textContent = d.body || '';
        bar.classList.add('show');
        _lastNoticeId = d.id;
    } catch(e){}
}

function closeNotice(){
    var bar = document.getElementById('noticeBar');
    if(bar) bar.classList.remove('show');
    if(_lastNoticeId){
        try { localStorage.setItem('notice_seen_' + _lastNoticeId, '1'); } catch(e){}
    }
}

// شغّل عند الفتح + كل دقيقة
setInterval(checkNotice, 30000);

if("Notification" in window && Notification.permission === "default"){
    Notification.requestPermission();
}

// ═══ الضغط على الدائرة 5 مرات (للمطور) ═══
var _spinnerClicks = 0;
var _spinnerTimer = null;

function initSecretTap(){
    var spinner = document.getElementById('spinnerTap');
    var logo = document.querySelector('.title-text');

    // الدائرة (شاشة الصيانة)
    if(spinner){
        spinner.style.cursor = 'pointer';
        spinner.style.userSelect = 'none';
        spinner.style.webkitTapHighlightColor = 'transparent';
        spinner.addEventListener('click', function(e){
            e.stopPropagation();
            _spinnerClicks++;
            if(_spinnerTimer) clearTimeout(_spinnerTimer);
            _spinnerTimer = setTimeout(function(){
                _spinnerClicks = 0;
            }, 1500);
            if(_spinnerClicks >= 5){
                _spinnerClicks = 0;
                if(_spinnerTimer) clearTimeout(_spinnerTimer);
                // اهتزاز + تخطي
                if(navigator.vibrate) navigator.vibrate(80);
                // تخطى الصيانة
                try { localStorage.setItem('otp_dev_skip', '1'); } catch(e){}
                var overlay = document.getElementById('maintOverlay');
                if(overlay) overlay.classList.remove('show');
                document.body.style.overflow = '';
                // شريط المطور
                var bar = document.getElementById('devBar');
                if(bar) bar.classList.add('show');
                if(typeof showToast === 'function') showToast('تم تخطي الصيانة');
            }
        });
    }

    // الشعار (في الصفحة العادية)
    if(logo){
        logo.style.userSelect = 'none';
        logo.style.webkitTapHighlightColor = 'transparent';
        logo.addEventListener('click', function(e){
            _spinnerClicks++;
            if(_spinnerTimer) clearTimeout(_spinnerTimer);
            _spinnerTimer = setTimeout(function(){
                _spinnerClicks = 0;
            }, 1500);
            if(_spinnerClicks >= 5){
                _spinnerClicks = 0;
                if(_spinnerTimer) clearTimeout(_spinnerTimer);
                openSecret();
            }
        });
    }
}

async function openSecret(){
    var overlay = document.getElementById('secretOverlay');
    var panel = document.getElementById('secretPanel');
    if(!overlay || !panel) return;
    overlay.classList.add('show');
    panel.classList.add('show');
    // حدّث الحالة
    try {
        var r = await fetch('/api/maintenance?t=' + Date.now());
        var d = await r.json();
        updateSecretUI(d);
    } catch(e){}
}

function closeSecret(){
    var overlay = document.getElementById('secretOverlay');
    var panel = document.getElementById('secretPanel');
    if(overlay) overlay.classList.remove('show');
    if(panel) panel.classList.remove('show');
}

function updateSecretUI(d){
    var status = document.getElementById('secretStatus');
    var btn = document.getElementById('secretToggle');
    var msg = document.getElementById('secretMsg');
    if(!status || !btn) return;
    if(d.on){
        status.className = 'secret-status on';
        status.textContent = 'الصيانة مُفعَّلة — الموقع مجمّد';
        btn.className = 'secret-btn success';
        btn.innerHTML = 'رفع الصيانة';
        btn.dataset.action = 'off';
    } else {
        status.className = 'secret-status off';
        status.textContent = 'الموقع يعمل طبيعي';
        btn.className = 'secret-btn danger';
        btn.innerHTML = 'تفعيل الصيانة';
        btn.dataset.action = 'on';
    }
    if(msg && d.title) msg.value = d.body || '';
}

async function toggleMaintenance(){
    var btn = document.getElementById('secretToggle');
    var msg = document.getElementById('secretMsg');
    var action = btn.dataset.action || 'on';
    btn.disabled = true;
    var oldText = btn.innerHTML;
    btn.innerHTML = 'جاري...';
    try {
        if(action === 'on'){
            var fd = new FormData();
            fd.append('maintenance_msg', msg ? msg.value : '');
            var r = await fetch('/admin/maintenance/on', {method: 'POST', body: fd});
        } else {
            var r = await fetch('/admin/maintenance/off');
        }
        if(r.ok || r.redirected){
            var r2 = await fetch('/api/maintenance?t=' + Date.now());
            var d = await r2.json();
            updateSecretUI(d);
        }
    } catch(e){
        alert('خطأ: ' + e.message);
    }
    btn.disabled = false;
}

function openAdminPanel(){
    closeSecret();
    window.open('/admin', '_blank');
}


// ═══ تخطي الصيانة ═══
var SKIP_KEY = 'otp_dev_skip';

function isSkipping(){
    try { return localStorage.getItem(SKIP_KEY) === '1'; } catch(e){ return false; }
}

function skipMaintenance(){
    try { localStorage.setItem(SKIP_KEY, '1'); } catch(e){}
    var overlay = document.getElementById('maintOverlay');
    if(overlay) overlay.classList.remove('show');
    document.body.style.overflow = '';
    showDevBar();
}

function stopSkipping(){
    try { localStorage.removeItem(SKIP_KEY); } catch(e){}
    var bar = document.getElementById('devBar');
    var menu = document.getElementById('devMenu');
    if(bar) bar.classList.remove('show');
    if(menu) menu.classList.remove('show');
    // أعد تحميل عشان يرجع للصيانة
    location.reload();
}

function showDevBar(){
    var bar = document.getElementById('devBar');
    if(bar) bar.classList.add('show');
}

function toggleDevMenu(){
    var menu = document.getElementById('devMenu');
    if(menu) menu.classList.toggle('show');
}

function previewMaintenance(){
    var menu = document.getElementById('devMenu');
    if(menu) menu.classList.remove('show');
    var overlay = document.getElementById('maintOverlay');
    if(overlay){
        overlay.classList.add('show');
        document.body.style.overflow = 'hidden';
        // أضف زر خروج من المعاينة
        var skipBtn = document.getElementById('skipBtn');
        if(skipBtn) skipBtn.classList.add('show');
    }
}

function openSecretPanel(){
    var menu = document.getElementById('devMenu');
    if(menu) menu.classList.remove('show');
    var overlay = document.getElementById('secretOverlay');
    var panel = document.getElementById('secretPanel');
    if(overlay) overlay.classList.add('show');
    if(panel) panel.classList.add('show');
    // حدّث الحالة
    fetch('/api/maintenance?t=' + Date.now()).then(function(r){ return r.json(); }).then(function(d){
        updateSecretUI(d);
    }).catch(function(){});
}

// ═══ الصيانة — شاشة تجميد ═══
var _maintInterval = null;

async function checkMaintenance(){
    // لو المطور متخطي → شغّل شريط المطور بدل الصيانة
    if(isSkipping()){
        showDevBar();
        return;
    }
    // لو إنت أدمن → تخطى الصيانة
    if(SETTINGS && SETTINGS.is_admin){
        return;
    }
    try {
        var r = await fetch('/api/maintenance?t=' + Date.now());
        var d = await r.json();
        var overlay = document.getElementById('maintOverlay');
        if(!overlay) return;
        // ✅ حدّث العنوان والنص من API
        if(d.title){
            var tt = document.getElementById('maintTitle');
            if(tt) tt.textContent = d.title;
        }
        if(d.body){
            var bb = document.getElementById('maintBody');
            if(bb) bb.textContent = d.body;
        }
        // ✅ حدّث الأيقونة واللون
        if(d.icon) overlay.dataset.icon = d.icon;
        if(d.color) overlay.dataset.color = d.color;
        if(d.on){
            var t = document.getElementById('maintTitle');
            var b = document.getElementById('maintBody');
            if(t) t.textContent = d.title || 'الموقع تحت الصيانة';
            if(b) b.textContent = d.body || 'نعتذر عن الإزعاج';
            // حدّث الأيقونة واللون
            var ov = document.getElementById('maintOverlay');
            if(ov){
                if(d.icon) ov.dataset.icon = d.icon;
                if(d.color) ov.dataset.color = d.color;
            }
            if(!overlay.classList.contains('show')){
                overlay.classList.add('show');
                document.body.style.overflow = 'hidden';
            }
        } else {
            // ✅ لما الصيانة تُرفع → إعادة تحميل فوري
            if(overlay.classList.contains('show')){
                overlay.classList.remove('show');
                document.body.style.overflow = '';
                setTimeout(function(){
                    location.reload();
                }, 500);
            }
        }
    } catch(e){}
}

// اشتغل كل 10 ثواني
setInterval(checkMaintenance, 5000);

// ═══ Bottom Sheet ═══
function openSheet(){
    var sheet = document.getElementById('bottomSheet');
    var overlay = document.getElementById('sheetOverlay');
    if(sheet) sheet.classList.add('open');
    if(overlay) overlay.classList.add('show');
}
function closeSheet(){
    var sheet = document.getElementById('bottomSheet');
    var overlay = document.getElementById('sheetOverlay');
    if(sheet) sheet.classList.remove('open');
    if(overlay) overlay.classList.remove('show');
}


function toggleSheet(){
    var sh = document.getElementById('bottomSheet');
    if(sh && sh.classList.contains('open')) closeSheet(); else openSheet();
}

// ═══ مسح الكاش + إعادة تحميل ═══
async function clearAllCache(){
    closeSheet();
    showToast('جاري المسح...');

    try {
        if('caches' in window){
            var names = await caches.keys();
            await Promise.all(names.map(function(n){ return caches.delete(n); }));
            console.log('✅ تم حذف الكاش:', names);
        }

        if('serviceWorker' in navigator){
            var regs = await navigator.serviceWorker.getRegistrations();
            await Promise.all(regs.map(function(r){ return r.unregister(); }));
            console.log('✅ تم إلغاء SW');
        }

        var theme = localStorage.getItem('theme');
        var lang = localStorage.getItem('lang');
        localStorage.clear();
        if(theme) localStorage.setItem('theme', theme);
        if(lang) localStorage.setItem('lang', lang);
        console.log('✅ تم مسح localStorage');

        showToast('تم! جاري التحديث...');

        setTimeout(function(){
            window.location.reload(true);
        }, 1000);

    } catch(e){
        console.error('خطأ في المسح:', e);
        showToast('خطأ: ' + e.message);
        setTimeout(function(){
            window.location.reload(true);
        }, 1500);
    }
}

// ═══ 📱 ثبّت التطبيق — PWA ═══
var _deferredPrompt = null;

// ═══ تسجيل Service Worker محسّن ═══
if('serviceWorker' in navigator){
    window.addEventListener('load', function(){
        navigator.serviceWorker.register('/sw.js', {scope: '/'}).then(function(reg){
            console.log('✅ SW registered:', reg.scope);

            // تحقق من التحديثات كل 30 دقيقة
            setInterval(function(){
                reg.update().catch(function(){});
            }, 30 * 60 * 1000);

            // تحقق فوراً
            reg.update().catch(function(){});

            // لما يصل تحديث جديد
            reg.addEventListener('updatefound', function(){
                var newWorker = reg.installing;
                if(!newWorker) return;
                newWorker.addEventListener('statechange', function(){
                    if(newWorker.state === 'installed' && navigator.serviceWorker.controller){
                        console.log('🎉 تحديث جديد متوفر!');
                        // بلغ SW الجديد يشتغل
                        newWorker.postMessage({type: 'SKIP_WAITING'});
                    }
                });
            });
        }).catch(function(err){
            console.log('❌ SW error:', err);
        });
    });

    // لما SW جديد ياخذ السيطرة
    var refreshing = false;
    navigator.serviceWorker.addEventListener('controllerchange', function(){
        if(refreshing) return;
        refreshing = true;
        console.log('🔄 إعادة تحميل للنسخة الجديدة');
        window.location.reload();
    });

    // ═══ تحديث تلقائي كل 30 ثانية ═══
    setInterval(function(){
        navigator.serviceWorker.getRegistration().then(function(reg){
            if(reg) reg.update();
        });
    }, 30000);
}

window.addEventListener('beforeinstallprompt', function(e){
    e.preventDefault();
    _deferredPrompt = e;
    console.log('install prompt ready');
});

function installPWA(){
    closeSheet();
    if(_deferredPrompt){
        _deferredPrompt.prompt();
        _deferredPrompt.userChoice.then(function(choice){
            if(choice.outcome === 'accepted'){
                showToast('تم التثبيت!');
            } else {
                showToast('تم إلغاء التثبيت');
            }
            _deferredPrompt = null;
        });
    } else if(window.matchMedia('(display-mode: standalone)').matches){
        showToast('التطبيق مثبّت مسبقاً!');
    } else {
        showToast('اضغط قائمة المتصفح ثم "إضافة إلى الشاشة الرئيسية"');
    }
}

// ═══ 📤 شارك الموقع ═══
function shareSite(){
    closeSheet();
    var url = window.location.origin;
    var text = 'موقع أرقام OTP — استقبل أكواد التحقق بسهولة!';
    if(navigator.share){
        navigator.share({title: 'أرقام OTP', text: text, url: url}).catch(function(){});
    } else if(navigator.clipboard){
        navigator.clipboard.writeText(url).then(function(){
            showToast('تم نسخ الرابط!');
        }).catch(function(){
            showToast('الرابط: ' + url);
        });
    } else {
        showToast('الرابط: ' + url);
    }
}

// ═══ ⭐ المفضلة ═══
function openFavorites(){
    closeSheet();
    showToast('المفضلة — قريباً!');
}

// ═══ 📜 سجل الأكواد ═══
function openHistory(){
    closeSheet();
    var total = 0;
    try {
        for(var i = 0; i < localStorage.length; i++){
            var key = localStorage.key(i);
            if(key && key.indexOf('savedCodes_') === 0){
                var arr = JSON.parse(localStorage.getItem(key) || '[]');
                total += arr.length;
            }
        }
    } catch(e){}
    showToast('لديك ' + total + ' كود في السجل');
}

// ═══ ℹ️ عن الموقع ═══

function openAbout(){
    closeSheet();
    var msg = '📱 أرقام OTP\n\n' +
              'موقع لاستقبال أكواد التحقق\n' +
              'من قنوات تيليجرام تلقائياً\n\n' +
              'الإصدار: 1.0\n' +
              'صُنع بـ ❤️';
    alert(msg);
}

// ═══ 📞 تواصل ═══
function contactSupport(){
    closeSheet();
    window.location.href = '/support';
}


// ═══ بدء التشغيل — مرة واحدة فقط ═══


// ═══ بدء التشغيل — مرة واحدة فقط ═══

// ═══ ✨ مميزات SVG ═══
(function(){
  var ar = function(){ return currentLang === 'ar'; };
  var st = document.createElement('style');
  st.textContent = '.srch-wrap{position:relative;margin-bottom:12px}'
    + '.srch-wrap svg{position:absolute;right:14px;top:50%;transform:translateY(-50%);width:18px;height:18px;fill:var(--text2);pointer-events:none}'
    + '.srch-in{width:100%;padding:12px 44px 12px 16px;border-radius:14px;border:1px solid var(--border);background:var(--card);color:var(--text);font-size:16px;outline:none;font-family:inherit}'
    + '.upd-line{font-size:12px;color:var(--text2);text-align:center;margin-bottom:10px;display:flex;align-items:center;justify-content:center;gap:6px}'
    + '.upd-line svg{width:14px;height:14px;fill:var(--text2)}';
  document.head.appendChild(st);

  var SVG_SEARCH = '<svg viewBox="0 0 24 24"><path d="M15.5 14h-.79l-.28-.27C15.41 12.59 16 11.11 16 9.5 16 5.91 13.09 3 9.5 3S3 5.91 3 9.5 5.91 16 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/></svg>';
  var SVG_CLOCK = '<svg viewBox="0 0 24 24"><path d="M11.99 2C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2zM12 20c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8zm.5-13H11v6l5.25 3.15.75-1.23-4.5-2.67z"/></svg>';

  // 📳 اهتزاز
  document.addEventListener('click', function(e){
    var el = e.target.closest ? e.target.closest('.nav-btn,.card,.copy-btn,.code-cp,.auto-fetch-btn') : null;
    if(!el || !navigator.vibrate) return;
    try { navigator.vibrate(el.classList.contains('copy-btn') || el.classList.contains('code-cp') ? 25 : 10); } catch(x){}
  }, {capture:true, passive:true});

  // 🔍 البحث
  function addSearch(listId){
    var list = document.getElementById(listId);
    if(!list || !list.querySelector('.card')) return;
    var old = list.querySelector('.srch-wrap'); if(old) old.remove();
    var w = document.createElement('div'); w.className = 'srch-wrap';
    w.innerHTML = SVG_SEARCH + '<input class="srch-in" type="search" autocomplete="off" placeholder="' + (ar() ? 'ابحث...' : 'Search...') + '">';
    list.insertBefore(w, list.firstChild);
    var inp = w.querySelector('input');
    inp.addEventListener('input', function(){
      var q = inp.value.trim().toLowerCase();
      list.querySelectorAll('.card').forEach(function(c){
        var n = (c.querySelector('.card-name') || {}).textContent || '';
        c.style.display = (!q || n.toLowerCase().indexOf(q) > -1) ? '' : 'none';
      });
    });
  }

  // 📊 تتبع
  function uid(){
    var u = null; try { u = localStorage.getItem('otp_uid'); } catch(e){}
    if(!u){ u = Math.random().toString(36).slice(2) + Date.now().toString(36); try { localStorage.setItem('otp_uid', u); } catch(e){} }
    return u;
  }
  function track(ev, p, c){
    try { fetch('/api/track', {method: 'POST', headers: {'Content-Type': 'application/json'}, keepalive: true,
      body: JSON.stringify({uid: uid(), ev: ev, platform: p || '', country: c || ''})}).catch(function(){}); } catch(e){}
  }
  setTimeout(function(){ track('visit'); }, 800);

  // 🕒 آخر تحديث
  var lastFetch = 0;
  function ago(ts){
    var s = Math.floor((Date.now() - ts) / 1000);
    if(s < 10) return ar() ? 'الآن' : 'just now';
    if(s < 60) return ar() ? 'منذ ' + s + ' ث' : s + 's ago';
    var m = Math.floor(s / 60); if(m < 60) return ar() ? 'منذ ' + m + ' د' : m + 'm ago';
    var h = Math.floor(m / 60); return ar() ? 'منذ ' + h + ' س' : h + 'h ago';
  }
  function refreshUpd(){
    var d = document.getElementById('updLine'); if(!d) return;
    var last = 0; savedCodes.forEach(function(c){ if(c.timestamp > last) last = c.timestamp; });
    d.innerHTML = SVG_CLOCK + '<span>' + (last ? (ar() ? 'آخر كود: ' : 'Last code: ') + ago(last) : (ar() ? 'لا توجد أكواد بعد' : 'No codes yet'))
      + (lastFetch ? (ar() ? ' · آخر فحص: ' : ' · Checked: ') + ago(lastFetch) : '') + '</span>';
    document.querySelectorAll('#codesList .code-card').forEach(function(card, i){
      var it = savedCodes[i], t = card.querySelector('.time');
      if(it && it.timestamp && t) t.textContent = (it.time || '--:--') + ' · ' + ago(it.timestamp);
    });
  }
  setInterval(refreshUpd, 60000);

  // ربط
  var _rp = renderPlatforms;
  renderPlatforms = function(){ _rp(); addSearch('platformsList'); };
  var _rc = renderCountries;
  renderCountries = function(){ _rc(); addSearch('countriesList'); };
  var _rn = renderNumbers;
  renderNumbers = function(){
    _rn();
    var list = document.getElementById('numbersList'); if(!list) return;
    var old = document.getElementById('updLine'); if(old) old.remove();
    var d = document.createElement('div'); d.className = 'upd-line'; d.id = 'updLine';
    list.insertBefore(d, list.firstChild); refreshUpd();
  };
  var _fo = fetchOTP;
  fetchOTP = async function(){ await _fo(); lastFetch = Date.now(); refreshUpd(); };
  var _sp = selectPlatform;
  selectPlatform = function(n){ track('platform', n); return _sp(n); };
  var _sc = selectCountry;
  selectCountry = function(n){ track('country', currentPlatform, n); return _sc(n); };
})();

// ═══ PERFORMANCE 120Hz ═══
(function(){
    // تفعيل GPU acceleration
    document.documentElement.style.setProperty('will-change', 'auto');

    // passive touch listeners = سلاسة عالية
    ['touchstart','touchmove','touchend','scroll','wheel'].forEach(function(ev){
        document.addEventListener(ev, function(){}, {passive: true, capture: true});
    });

    // تقليل عمل الـ observers
    if('requestIdleCallback' in window){
        requestIdleCallback(function(){ console.log('Idle: optimizing'); });
    }

    // منع القفزة عند اللمس
    document.body.style.webkitTouchCallout = 'none';
    document.body.style.webkitUserSelect = 'none';

    // تسريع الأحداث على الأجهزة 120Hz
    var lastTap = 0;
    document.addEventListener('touchstart', function(e){
        var now = Date.now();
        if(now - lastTap < 300){
            e.preventDefault(); // منع zoom المزدوج
        }
        lastTap = now;
    }, {passive: false});
})();

// ═══ مراقب الاتصال بالإنترنت ═══
(function(){
    var bar = null, txt = null;
    var wasOffline = false;
    function show(text, isOnline){
        if(!bar){ bar = document.getElementById('offlineBar'); txt = document.getElementById('offlineText'); }
        if(!bar) return;
        txt.textContent = text;
        var icon = bar.querySelector('.offline-icon');
        if(isOnline){
            bar.classList.add('online');
            bar.classList.add('show');
            // أيقونة wifi كاملة (بدون خط مقطوع)
            if(icon){
                icon.innerHTML = '<path d="M12 3C7.5 3 3.5 4.6 0.5 7.2L2 9C4.5 6.8 8 5.4 12 5.4S19.5 6.8 22 9L23.5 7.2C20.5 4.6 16.5 3 12 3Z" opacity="0.4"/><path d="M12 8C9 8 6.3 9 4.2 10.7L5.7 12.5C7.4 11.1 9.6 10.3 12 10.3S16.6 11.1 18.3 12.5L19.8 10.7C17.7 9 15 8 12 8Z" opacity="0.6"/><path d="M12 13C10.3 13 8.7 13.6 7.5 14.5L9 16.3C9.8 15.7 10.9 15.3 12 15.3S14.2 15.7 15 16.3L16.5 14.5C15.3 13.6 13.7 13 12 13Z" opacity="0.8"/><circle cx="12" cy="18.5" r="2"/>';
            }
            setTimeout(function(){ bar.classList.remove('show'); }, 2500);
        } else {
            bar.classList.remove('online');
            bar.classList.add('show');
            // أيقونة wifi مقطوعة (مع خط)
            if(icon){
                icon.innerHTML = '<path d="M12 3C7.5 3 3.5 4.6 0.5 7.2L2 9C4.5 6.8 8 5.4 12 5.4S19.5 6.8 22 9L23.5 7.2C20.5 4.6 16.5 3 12 3Z" opacity="0.3"/><path d="M12 8C9 8 6.3 9 4.2 10.7L5.7 12.5C7.4 11.1 9.6 10.3 12 10.3S16.6 11.1 18.3 12.5L19.8 10.7C17.7 9 15 8 12 8Z" opacity="0.45"/><circle cx="12" cy="16" r="2" fill="#fff"/><line x1="4" y1="20" x2="20" y2="4" stroke="#fff" stroke-width="2.2" stroke-linecap="round"/>';
            }
        }
    }
    function check(){
        if(!navigator.onLine){
            wasOffline = true;
            show('لا يوجد اتصال بالإنترنت — تعمل من الكاش', false);
        } else {
            if(wasOffline){
                wasOffline = false;
                show('عاد الاتصال بالإنترنت', true);
            } else {
                if(bar) bar.classList.remove('show');
            }
        }
    }
    window.addEventListener('online', check);
    window.addEventListener('offline', check);
    setTimeout(check, 500);
    setInterval(check, 3000);
})();

document.addEventListener('DOMContentLoaded', function(){
    applyTheme();
    // تطبيق اللغة عند البدء
    if(currentLang === 'en'){
        document.documentElement.lang = 'en';
        document.documentElement.dir = 'ltr';
        var ttl1 = document.getElementById('ttl_platforms');
        var ttl2 = document.getElementById('ttl_countries');
        var ttl3 = document.getElementById('ttl_numbers');
        if(ttl1) ttl1.textContent = 'Choose Platform';
        if(ttl2) ttl2.textContent = 'Choose Country';
        if(ttl3) ttl3.textContent = 'Numbers';
    }
    renderPlatforms();
    setTimeout(initSecretTap, 300);
    setTimeout(checkNotice, 500);
    setTimeout(checkMaintenance, 100);
    setTimeout(checkNewTelegramCodes, 2000);
    setTimeout(function(){ if(typeof checkBotHash === 'function') checkBotHash(); }, 3000);
    // فحص الردود الجديدة من الدعم
    function checkSupportBadge(){
        fetch('/api/chat/unread').then(function(r){return r.json()}).then(function(d){
            var b = document.getElementById('supportBadge');
            if(!b) return;
            if(d.unread && d.count > 0){
                b.textContent = d.count > 9 ? '9+' : String(d.count);
                b.style.display = 'inline-flex';
                // اهتزاز بسيط لأول مرة
                if(!b.dataset.seen){
                    b.dataset.seen = '1';
                    if(navigator.vibrate) try{navigator.vibrate(30)}catch(e){}
                }
            } else {
                b.style.display = 'none';
                delete b.dataset.seen;
            }
        }).catch(function(){});
    }
    setTimeout(checkSupportBadge, 2500);
    setInterval(checkSupportBadge, 15000);

    // ═══ مراقبة نسخة الموقع (لتحديث الثيمات فوراً) ═══
    var _lastVersion = null;
    function checkVersion(){
        fetch('/api/version?t=' + Date.now(), {cache: 'no-store'})
            .then(function(r){ return r.json(); })
            .then(function(d){
                if(_lastVersion === null){
                    _lastVersion = d.version;
                    return;
                }
                if(d.version !== _lastVersion){
                    _lastVersion = d.version;
                    console.log('🎨 تحديث الإعدادات — إعادة تحميل');
                    if(navigator.serviceWorker && navigator.serviceWorker.controller){
                        navigator.serviceWorker.getRegistration().then(function(reg){
                            if(reg){
                                reg.unregister().then(function(){
                                    location.reload(true);
                                });
                            } else {
                                location.reload(true);
                            }
                        });
                    } else {
                        location.reload(true);
                    }
                }
            })
            .catch(function(){});
    }
    // افحص أول مرة بعد 3 ثواني ثم كل 10 ثواني
    setTimeout(checkVersion, 3000);
    setInterval(checkVersion, 10000);

    // فحص نسخة bot.py — إعادة تحميل فورية عند أي تعديل
    var _botVer = null;
    function checkBotVersion(){
        fetch('/api/bot-version?t=' + Date.now(), {cache: 'no-store'})
            .then(function(r){ return r.json(); })
            .then(function(d){
                if(_botVer === null){
                    _botVer = d.v;
                    return;
                }
                if(d.v !== _botVer){
                    console.log('تحديث جديد — إعادة تحميل...');
                    // امسح الكاش والـ SW
                    if('caches' in window){
                        caches.keys().then(function(names){
                            return Promise.all(names.map(function(n){ return caches.delete(n); }));
                        }).then(function(){
                            if('serviceWorker' in navigator){
                                return navigator.serviceWorker.getRegistrations();
                            }
                        }).then(function(regs){
                            if(regs){
                                return Promise.all(regs.map(function(r){ return r.unregister(); }));
                            }
                        }).then(function(){
                            window.location.reload(true);
                        }).catch(function(){
                            window.location.reload(true);
                        });
                    } else {
                        window.location.reload(true);
                    }
                }
            })
            .catch(function(){});
    }
    setTimeout(checkBotVersion, 4000);
    setInterval(checkBotVersion, 8000);
});

</script>

<!-- ═══ SVG مخصص (يظهر فقط إذا مُفعّل) ═══ -->
<script>
(function(){
    var customSvg = {{ settings_json|safe }}.background_custom_svg || "";
    var bgStyle = {{ settings_json|safe }}.background_style || "code";
    var bgOn = {{ settings_json|safe }}.background_on;

    if(!bgOn) return;

    // لو النوع "custom" → نخفي الخلفية الافتراضية ونعرض SVG
    if(bgStyle === "custom" && customSvg){
        // إخفاء كل عناصر الخلفية الافتراضية
        var bg = document.querySelector(".code-bg");
        if(bg){
            // احفظ SVG فقط
            bg.innerHTML = '<div style="position:absolute;top:0;left:0;right:0;bottom:0;display:flex;align-items:center;justify-content:center;opacity:0.6">' + customSvg + '</div>';
        }
    } else if(bgStyle === "off"){
        var bg2 = document.querySelector(".code-bg");
        if(bg2) bg2.style.display = "none";
    }
})();
</script>
<script>
// ═══════════════════════════════════════════
// PUSH NOTIFICATIONS — كود التسجيل في المتصفح
// ═══════════════════════════════════════════
window.__pushInit = true;
(function(){
    function urlBase64ToUint8Array(base64String){
        var padding = "=".repeat((4 - base64String.length % 4) % 4);
        var base64 = (base64String + padding).replace(/\-/g, "+").replace(/_/g, "/");
        var rawData = atob(base64);
        var outputArray = new Uint8Array(rawData.length);
        for(var i = 0; i < rawData.length; ++i){
            outputArray[i] = rawData.charCodeAt(i);
        }
        return outputArray;
    }

    async function registerPush(){
        if(!("serviceWorker" in navigator) || !("PushManager" in window)){
            console.log("[PUSH] المتصفح ما يدعم Push");
            return;
        }
        if(!("Notification" in window)){
            console.log("[PUSH] Notification غير مدعوم");
            return;
        }

        // اطلب إذن
        var perm = Notification.permission;
        if(perm === "default"){
            try {
                perm = await Notification.requestPermission();
            } catch(e){
                console.log("[PUSH] طلب الإذن فشل:", e);
                return;
            }
        }
        if(perm !== "granted"){
            console.log("[PUSH] المستخدم رفض الإشعارات");
            return;
        }

        try {
            // 1) اجلب المفتاح العمومي
            var r = await fetch("/api/push/public-key");
            var d = await r.json();
            if(!d.public_key){
                console.log("[PUSH] لا يوجد public key");
                return;
            }
            var appKey = urlBase64ToUint8Array(d.public_key);

            // 2) جيب SW
            var reg = await navigator.serviceWorker.ready;

            // 3) تحقق لو مسجل مسبقاً
            var existing = await reg.pushManager.getSubscription();
            if(existing){
                // تأكد إنه مسجل في السيرفر
                await fetch("/api/push/subscribe", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({subscription: existing.toJSON()})
                }).catch(function(){});
                console.log("[PUSH] مسجل مسبقاً");
                return;
            }

            // 4) سجل اشتراك جديد
            var sub = await reg.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: appKey
            });

            // 5) أرسل للسيرفر
            await fetch("/api/push/subscribe", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({subscription: sub.toJSON()})
            });

            console.log("[PUSH] تم التسجيل بنجاح");
        } catch(e){
            console.log("[PUSH] خطأ:", e);
        }
    }

    // شغّل بعد 3 ثواني من التحميل
    if(document.readyState === "complete"){
        setTimeout(registerPush, 3000);
    } else {
        window.addEventListener("load", function(){
            setTimeout(registerPush, 3000);
        });
    }
})();

// ═══ PUSH — Admin Panel ═══
function pushRefresh(){
    var b = document.getElementById("pushStatus");
    if(!b) return;
    b.innerHTML = "جاري التحميل...";
    // FIX: mark auto run
    window._pushAutoRun = true;
    fetch("/api/push/stats").then(function(r){ return r.json(); }).then(function(d){
        var h = "";
        if(!d.ready){
            h = "<b style='color:#ff6b8a'>pywebpush غير مثبت</b><br><br>ثبت بـ:<br><code style='direction:ltr;display:inline-block;margin-top:6px'>pip install pywebpush</code>";
        } else {
            h = "<b style='color:#00d4a5'>النظام شغال</b><br>";
            h += "عدد المشتركين: <b style='color:#00d4ff'>" + d.subs + "</b><br>";
            h += "VAPID: <b style='color:#00d4a5'>" + (d.has_vapid ? "موجود" : "ناقص") + "</b>";
        }
        b.innerHTML = h;
    }).catch(function(e){
        b.innerHTML = "<b style='color:#ff6b8a'>خطأ: " + e.message + "</b>";
    });
}

function pushSendTest(){
    var b = document.getElementById("pushTestResult");
    if(!b) return;
    b.style.display = "block";
    b.style.color = "#ffcb6b";
    b.textContent = "جاري الإرسال...";
    fetch("/api/push/test").then(function(r){ return r.json(); }).then(function(d){
        if(d.ok){
            b.style.color = "#00d4a5";
            b.textContent = "تم إرسال " + d.sent + " إشعار (من " + d.total + " مشترك)";
        } else {
            b.style.color = "#ff6b8a";
            b.textContent = "فشل: " + (d.error || "");
        }
    }).catch(function(e){
        b.style.color = "#ff6b8a";
        b.textContent = "خطأ: " + e.message;
    });
}

// ═══ PUSH FIX v2 ═══
window._pushFixed_v2 = true;
// شغّل pushRefresh عند أي نقرة على زر Push (بدون استبدال showTab)
document.addEventListener("click", function(e){
    var t = e.target.closest ? e.target.closest(".tb") : null;
    if(!t) return;
    if(t.textContent.indexOf("Push") > -1 || t.innerHTML.indexOf("Push") > -1){
        setTimeout(function(){
            if(typeof pushRefresh === "function") pushRefresh();
        }, 200);
    }
}, false);

</script>

<script>
// ═══════════════════════════════════════════
// AUTO SYNC — تحديث تلقائي ذكي لكل الصفحات
// ═══════════════════════════════════════════
(function(){
    var isVisible = true;
    document.addEventListener('visibilitychange', function(){
        isVisible = !document.hidden;
    });

    // ═══ الإشعارات — تظهر فوراً ═══
    async function syncNotice(){
        if(!isVisible) return;
        try {
            var r = await fetch('/api/notice?t=' + Date.now());
            var d = await r.json();
            var bar = document.getElementById('noticeBar');
            if(!bar) return;
            if(!d.active){
                bar.classList.remove('show');
                return;
            }
            // لو نفس الإشعار → لا تعيد
            if(_lastNoticeId === d.id && bar.classList.contains('show')) return;
            // اعرض الإشعار
            var icon = document.getElementById('nIcon');
            var title = document.getElementById('nTitle');
            var body = document.getElementById('nBody');
            bar.classList.remove('warning','success','danger');
            var t = d.type || 'info';
            var SVG_INFO = '<svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/></svg>';
            var SVG_WARN = '<svg viewBox="0 0 24 24"><path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/></svg>';
            var SVG_OK = '<svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg>';
            var SVG_ERR = '<svg viewBox="0 0 24 24"><path d="M12 2C6.47 2 2 6.47 2 12s4.47 10 10 10 10-4.47 10-10S17.53 2 12 2zm5 13.59L15.59 17 12 13.41 8.41 17 7 15.59 10.59 12 7 8.41 8.41 7 12 10.59 15.59 7 17 8.41 13.41 12 17 15.59z"/></svg>';
            if(t === 'warning'){ bar.classList.add('warning'); icon.innerHTML = SVG_WARN; }
            else if(t === 'success'){ bar.classList.add('success'); icon.innerHTML = SVG_OK; }
            else if(t === 'danger'){ bar.classList.add('danger'); icon.innerHTML = SVG_ERR; }
            else { icon.innerHTML = SVG_INFO; }
            title.textContent = d.title || '';
            body.textContent = d.body || '';
            bar.classList.add('show');
            _lastNoticeId = d.id;
        } catch(e){}
    }

    // ═══ تحديث أكواد OTP الجديدة (الصفحة الرئيسية) ═══
    async function syncCodes(){
        if(!isVisible) return;
        // فقط في صفحة الأرقام
        var pageNumbers = document.getElementById('page-numbers');
        if(!pageNumbers || !pageNumbers.classList.contains('active')) return;
        // فقط لو فيه أرقام معروضة
        if(!currentNumbers || currentNumbers.length === 0) return;
        // ما تحدّث لو المستخدم يكتب
        var active = document.activeElement;
        if(active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA')) return;
        // فحص الأكواد الجديدة
        for(var i = 0; i < currentNumbers.length; i++){
            var phone = currentNumbers[i];
            try {
                var r = await fetch('/api/check-otp/' + encodeURIComponent(phone), {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({platform: currentPlatform || ''})
                });
                var d = await r.json();
                if(d.code){
                    var exists = savedCodes.find(function(c){ return c.phone === phone && c.code === d.code; });
                    if(!exists){
                        var now = new Date();
                        var timeStr = ('0' + now.getHours()).slice(-2) + ':' + ('0' + now.getMinutes()).slice(-2);
                        savedCodes.push({phone: phone, code: d.code, time: timeStr, timestamp: Date.now()});
                        // احفظ في localStorage
                        localStorage.setItem('savedCodes_' + currentPlatform + '_' + currentCountry, JSON.stringify(savedCodes));
                        // شغّل صوت واهتزاز
                        if(typeof playNotifySound === 'function') playNotifySound();
                        if(typeof vibrateDevice === 'function') vibrateDevice();
                        if(typeof showToast === 'function') showToast('وصل كود جديد!');
                        // حدّث الواجهة
                        if(typeof renderNumbers === 'function') renderNumbers();
                    }
                }
            } catch(e){}
        }
    }

    // ═══ تحديث الإحصائيات (الأدمن) ═══
    async function syncAdminStats(){
        if(!isVisible) return;
        if(!window.location.pathname.startsWith('/admin')) return;
        // تحديث حالة البوت فقط
        try {
            var r = await fetch('/admin/telegram/status');
            var d = await r.json();
            var el = document.getElementById('tgStatus');
            if(el && el.offsetParent !== null){
                var h = '';
                h += d.running ? "<b style='color:#00d4a5'>البوت شغال</b><br>" : "<b style='color:#ff6b8a'>البوت متوقف</b><br>";
                h += d.has_token ? "التوكن محفوظ<br>" : "التوكن ناقص<br>";
                h += d.has_chat_id ? "Chat ID محفوظ<br>" : "Chat ID ناقص<br>";
                h += "عدد الأكواد: <b>" + d.codes_count + "</b>";
                el.innerHTML = h;
            }
        } catch(e){}
    }

    // ═══ تحديث الرسائل (الدعم) ═══
    async function syncChat(){
        if(!isVisible) return;
        if(window.location.pathname.indexOf('/support') === -1) return;
        // ما تحدّث لو المستخدم يكتب
        var inp = document.getElementById('msgInput');
        if(inp && inp.value.trim().length > 0) return;
        var active = document.activeElement;
        if(active === inp) return;
        try {
            var r = await fetch('/api/chat/messages');
            var d = await r.json();
            var list = document.getElementById('messagesList');
            if(!list) return;
            var current = list.querySelectorAll('.msg-row').length;
            if(d.count && d.count !== current){
                // فيه رسائل جديدة
                location.reload();
            }
        } catch(e){}
    }

    // ═══ تحديث إشعار الدعم ═══
    async function syncSupportBadge(){
        if(!isVisible) return;
        try {
            var r = await fetch('/api/chat/unread');
            var d = await r.json();
            var b = document.getElementById('supportBadge');
            if(!b) return;
            if(d.unread && d.count > 0){
                b.textContent = d.count > 9 ? '9+' : String(d.count);
                b.style.display = 'inline-flex';
            } else {
                b.style.display = 'none';
            }
        } catch(e){}
    }

    // ═══ الموزّع — يحدّث حسب الصفحة الحالية ═══
    async function autoSync(){
        if(!isVisible) return;
        if(!navigator.onLine) return;
        // الإشعارات — دايماً
        await syncNotice();
        // الرئيسية — الأكواد
        await syncCodes();
        // أدمن
        await syncAdminStats();
        // دعم
        await syncChat();
        await syncSupportBadge();
    }

    // شغّل أول مرة بعد 5 ثواني، ثم حسب سرعة الجهاز
    var lite = document.documentElement.classList.contains('lite-mode');
    setTimeout(autoSync, lite ? 10000 : 5000);
    setInterval(autoSync, lite ? 60000 : 20000);

    // شغّل عند رجوع المستخدم للصفحة
    document.addEventListener('visibilitychange', function(){
        if(!document.hidden){
            setTimeout(autoSync, 1000);
            // حدّث الشجرة عند الرجوع للموقع
            try {
                if(typeof _refreshTree === 'function'){
                    _refreshTree().then(function(){
                        if(typeof currentCountry !== 'undefined' && currentCountry){
                            renderNumbers();
                        } else if(typeof currentPlatform !== 'undefined' && currentPlatform){
                            renderCountries();
                        } else if(typeof renderPlatforms === 'function'){
                            renderPlatforms();
                        }
                    }).catch(function(){});
                }
            } catch(e){}
        }
    });

    console.log('✅ Auto Sync مفعّل — كل 20 ثانية');
})();

// ═══ تبديل الأداء العالي ═══
window.toggleLiteMode = function(){
    var current = document.documentElement.classList.contains('lite-mode');
    var next = !current;
    if(next){
        document.documentElement.classList.add('lite-mode');
        localStorage.setItem('lite_mode', '1');
    } else {
        document.documentElement.classList.remove('lite-mode');
        localStorage.setItem('lite_mode', '0');
    }
    if(window._sClick) window._sClick();
    if(typeof showToast === 'function'){
        showToast(next ? 'الوضع العالي مُفعَّل' : 'الوضع العادي');
    }
    // أعد تحميل الصفحة لتطبيق التغييرات
    setTimeout(function(){ location.reload(); }, 800);
};
</script>

<script>
// ═══ LIVE UPDATE SYSTEM — كل الصفحات ═══
(function(){
    window.__liveUpdate = true;

    // ═══ قراءة رقم نسخة bot.py من السيرفر ═══
    var _lastVer = null;
    function checkVersion(){
        fetch('/api/bot-version?t=' + Date.now(), {cache: 'no-store'})
            .then(function(r){ return r.json(); })
            .then(function(d){
                if(_lastVer === null){
                    _lastVer = d.v;
                    return;
                }
                if(d.v !== _lastVer){
                    _lastVer = d.v;
                    // امسح cache الـ API
                    if('caches' in window){
                        caches.keys().then(function(names){
                            return Promise.all(names.map(function(n){ return caches.delete(n); }));
                        }).then(function(){
                            window.location.reload(true);
                        }).catch(function(){
                            window.location.reload(true);
                        });
                    } else {
                        window.location.reload(true);
                    }
                }
            })
            .catch(function(){});
    }
    setTimeout(checkVersion, 3000);
    setInterval(checkVersion, 6000);

    // ═══ تحديث الشجرة (المنصات/الدول) ═══
    var _treeSig = null;
    var _treeBusy = false;
    function pollTree(){
        if(document.hidden) return;
        if(_treeBusy) return;
        if(typeof TREE === 'undefined') return;
        _treeBusy = true;
        fetch('/api/tree?t=' + Date.now(), {cache: 'no-store'})
            .then(function(r){ return r.ok ? r.json() : null; })
            .then(function(d){
                _treeBusy = false;
                if(!d || typeof d !== 'object') return;
                var sig = JSON.stringify(d);
                if(_treeSig === null){ _treeSig = sig; return; }
                if(sig === _treeSig) return;
                _treeSig = sig;
                TREE = d;
                try {
                    var pageNum = document.getElementById('page-numbers');
                    var pageCtry = document.getElementById('page-countries');
                    var pagePlat = document.getElementById('page-platforms');
                    if(pageNum && pageNum.classList.contains('active') && currentCountry){
                        if(TREE[currentPlatform] && TREE[currentPlatform][currentCountry]) renderNumbers();
                        else { currentCountry = null; if(TREE[currentPlatform]) renderCountries(); else { currentPlatform = null; renderPlatforms(); } }
                    } else if(pageCtry && pageCtry.classList.contains('active') && currentPlatform){
                        if(TREE[currentPlatform]) renderCountries();
                        else { currentPlatform = null; renderPlatforms(); }
                    } else if(pagePlat && pagePlat.classList.contains('active')){
                        renderPlatforms();
                    }
                } catch(e){}
            })
            .catch(function(){ _treeBusy = false; });
    }
    setTimeout(pollTree, 3000);
    setInterval(pollTree, 4000);

    // ═══ تحديث الإشعارات ═══
    var _lastNoticeId = null;
    function pollNotice(){
        if(document.hidden) return;
        fetch('/api/notice?t=' + Date.now(), {cache: 'no-store'})
            .then(function(r){ return r.json(); })
            .then(function(d){
                if(!d.active) return;
                if(_lastNoticeId === null){ _lastNoticeId = d.id; return; }
                if(d.id === _lastNoticeId) return;
                _lastNoticeId = d.id;
                var bar = document.getElementById('noticeBar');
                if(!bar) return;
                var icon = document.getElementById('nIcon');
                var title = document.getElementById('nTitle');
                var body = document.getElementById('nBody');
                bar.classList.remove('warning','success','danger');
                var t = d.type || 'info';
                var SVG_INFO = '<svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/></svg>';
                var SVG_WARN = '<svg viewBox="0 0 24 24"><path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/></svg>';
                var SVG_OK = '<svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg>';
                var SVG_ERR = '<svg viewBox="0 0 24 24"><path d="M12 2C6.47 2 2 6.47 2 12s4.47 10 10 10 10-4.47 10-10S17.53 2 12 2zm5 13.59L15.59 17 12 13.41 8.41 17 7 15.59 10.59 12 7 8.41 8.41 7 12 10.59 15.59 7 17 8.41 13.41 12 17 15.59z"/></svg>';
                if(t === 'warning'){ bar.classList.add('warning'); if(icon) icon.innerHTML = SVG_WARN; }
                else if(t === 'success'){ bar.classList.add('success'); if(icon) icon.innerHTML = SVG_OK; }
                else if(t === 'danger'){ bar.classList.add('danger'); if(icon) icon.innerHTML = SVG_ERR; }
                else { if(icon) icon.innerHTML = SVG_INFO; }
                if(title) title.textContent = d.title || '';
                if(body) body.textContent = d.body || '';
                bar.classList.add('show');
            })
            .catch(function(){});
    }
    setTimeout(pollNotice, 4000);
    setInterval(pollNotice, 6000);

    // ═══ تحديث صورة وبيانات المستخدم ═══
    var _lastUserSig = null;
    function pollUser(){
        if(document.hidden) return;
        var slot = document.getElementById('userCardSlot');
        if(!slot) return;
        fetch('/api/me?t=' + Date.now(), {cache: 'no-store'})
            .then(function(r){ return r.ok ? r.json() : null; })
            .then(function(d){
                if(!d || !d.ok) return;
                var sig = d.username + '|' + d.avatar;
                if(_lastUserSig === null){ _lastUserSig = sig; return; }
                if(sig === _lastUserSig) return;
                _lastUserSig = sig;
                var initial = (d.display_name || d.username || 'U')[0].toUpperCase();
                var avatarHtml = d.avatar
                    ? '<img src="' + d.avatar + '?t=' + Date.now() + '" alt="">'
                    : '<span class="uc-initial">' + initial + '</span>';
                slot.innerHTML =
                    '<div class="uc-avatar">' + avatarHtml + '<div class="uc-online"></div></div>' +
                    '<div class="uc-info">' +
                        '<div class="uc-name">' + (d.display_name || d.username) + ' <span class="uc-badge">PRO</span></div>' +
                        '<div class="uc-sub">اضغط لعرض ملفك الشخصي</div>' +
                    '</div>' +
                    '<svg class="uc-arrow" viewBox="0 0 24 24"><path d="M10 6L8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z"/></svg>';
            })
            .catch(function(){});
    }
    setTimeout(pollUser, 2000);
    setInterval(pollUser, 4000);

    console.log('Live update system ready');
})();
</script>

</body>
</html>
"""

# ============================================================
# الجزء 3: JavaScript + Routes + Admin
# ============================================================
USER_PROFILE_HTML = r"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<meta name="theme-color" content="#7b2ff7">
<title>ملفي الشخصي</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;font-family:-apple-system,'Segoe UI',Tahoma,sans-serif;-webkit-tap-highlight-color:transparent}
body{background:#07070d;color:#e8e8f0;min-height:100vh;padding:0 0 30px;direction:rtl}
.hdr{position:sticky;top:0;z-index:100;background:linear-gradient(135deg,#0c0c18,#12122a);border-bottom:1px solid rgba(123,47,247,.25);padding:16px 18px;display:flex;align-items:center;gap:14px;box-shadow:0 4px 24px rgba(0,0,0,.4)}
.hdr .titles{flex:1;min-width:0}
.hdr h1{font-size:19px;font-weight:900;background:linear-gradient(135deg,#7b2ff7,#00d4ff);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.hdr .sub{font-size:11px;color:#6e6e8a;margin-top:3px;display:flex;align-items:center;gap:5px}
.hdr .sub .dot{width:6px;height:6px;border-radius:50%;background:#00d4a5;box-shadow:0 0 8px #00d4a5}
.hdr .back{padding:9px 14px;background:rgba(0,212,255,.12);border:1px solid rgba(0,212,255,.35);color:#00d4ff;border-radius:11px;font-size:12px;font-weight:700;text-decoration:none;display:flex;align-items:center;gap:6px}
.hdr .back svg{width:14px;height:14px;fill:currentColor}

.wrap{padding:18px}
.avatar-block{text-align:center;margin-bottom:22px}
.avatar-big{width:110px;height:110px;border-radius:50%;background:linear-gradient(135deg,#7b2ff7,#00d4ff);margin:0 auto 14px;display:flex;align-items:center;justify-content:center;font-size:48px;font-weight:900;color:#fff;overflow:hidden;box-shadow:0 12px 40px rgba(123,47,247,.45);border:4px solid rgba(255,255,255,.1);position:relative}
.avatar-big img{width:100%;height:100%;object-fit:cover}
.avatar-edit{display:inline-block;padding:8px 16px;background:rgba(0,212,255,.12);border:1px solid rgba(0,212,255,.3);color:#00d4ff;border-radius:10px;font-size:12px;font-weight:700;cursor:pointer;margin-top:6px}
.uname-big{font-size:22px;font-weight:900;color:#e8e8f0;margin-bottom:6px}
.usub{font-size:12px;color:#6e6e8a}

.card{background:linear-gradient(160deg,#10101e,#0a0a14);border:1px solid rgba(123,47,247,.2);border-radius:18px;padding:18px;margin-bottom:14px}
.card h2{font-size:14px;color:#00d4ff;margin-bottom:14px;font-weight:800;display:flex;align-items:center;gap:8px}
.card h2 svg{width:18px;height:18px;fill:#00d4ff}

label{display:block;font-size:12px;color:#8e8eab;margin:12px 0 6px;font-weight:600}
label:first-of-type{margin-top:0}
input,textarea{width:100%;padding:13px 14px;border:1px solid rgba(123,47,247,.25);border-radius:12px;background:rgba(0,0,0,.4);color:#e8e8f0;font-size:14px;outline:none;font-family:inherit}
input:focus,textarea:focus{border-color:#00d4ff}

.btn{width:100%;padding:14px 20px;border:none;border-radius:13px;color:#fff;cursor:pointer;font-weight:800;font-size:14px;font-family:inherit;margin-top:14px;background:linear-gradient(135deg,#7b2ff7,#00d4ff);box-shadow:0 6px 20px rgba(123,47,247,.4)}
.btn-green{background:linear-gradient(135deg,#00b894,#00a884)}
.btn-orange{background:linear-gradient(135deg,#f39c12,#e67e22)}
.btn-red{background:linear-gradient(135deg,#e94560,#c62a47)}
.btn:active{transform:scale(.97)}

.msg{padding:12px 14px;border-radius:12px;font-size:13px;text-align:center;font-weight:700;margin-bottom:14px}
.msg.ok{background:rgba(0,184,148,.15);border:1px solid rgba(0,184,148,.35);color:#6fe3c1}
.msg.err{background:rgba(233,69,96,.15);border:1px solid rgba(233,69,96,.4);color:#ff8aa3}

.info-row{display:flex;justify-content:space-between;padding:10px 0;border-bottom:1px solid rgba(255,255,255,.05);font-size:13px}
.info-row:last-child{border:none}
.info-row span{color:#6e6e8a}
.info-row b{color:#e8e8f0;font-weight:700}

.logout-btn{display:flex;align-items:center;justify-content:center;gap:8px;text-decoration:none;background:rgba(233,69,96,.12);border:1px solid rgba(233,69,96,.3);color:#ff6b8a;padding:14px;border-radius:13px;font-weight:800;margin-top:8px}
.logout-btn svg{width:18px;height:18px;fill:currentColor}

.file-drop{display:block;padding:24px 16px;border:2px dashed rgba(123,47,247,.5);border-radius:14px;background:rgba(123,47,247,.06);text-align:center;color:#c8c8d8;font-size:13px;cursor:pointer;margin-top:8px}
.file-drop:active{background:rgba(123,47,247,.15)}
.file-drop input{display:none}
</style>
</head>
<body>

<div class="hdr">
<svg class="logo" width="46" height="46" viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg">
<defs>
<linearGradient id="pg1" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#7b2ff7"/><stop offset="100%" stop-color="#00d4ff"/></linearGradient>
</defs>
<circle cx="24" cy="24" r="20" fill="none" stroke="url(#pg1)" stroke-width="1.5" opacity="0.4"/>
<circle cx="24" cy="18" r="6" fill="url(#pg1)"/>
<path d="M12 38 Q 24 30 36 38" stroke="url(#pg1)" stroke-width="2.5" fill="none" stroke-linecap="round"/>
</svg>
<div class="titles">
<h1>ملفي الشخصي</h1>
<div class="sub"><span class="dot"></span> حسابك في المطري OTP</div>
</div>
<a href="/" class="back">
<svg viewBox="0 0 24 24"><path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z"/></svg>
الرئيسية
</a>
</div>

<div class="wrap">

{% if msg %}<div class="msg ok">{{ msg }}</div>{% endif %}
{% if err %}<div class="msg err">{{ err }}</div>{% endif %}

<div class="avatar-block">
<div class="avatar-big">
{% if u.avatar %}
<img src="{{ u.avatar }}" alt="{{ u.username }}">
{% else %}
{{ (u.username or 'U')[0]|upper }}
{% endif %}
</div>
<div class="uname-big">{{ u.username or 'مستخدم' }}</div>
<div class="usub">عضو في المطري OTP</div>
</div>

<div class="card">
<h2>
<svg viewBox="0 0 24 24"><path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/></svg>
معلومات الحساب
</h2>
<form method="POST">
<input type="hidden" name="action" value="update_name">
<label>اسم العرض</label>
<input type="text" name="display_name" value="{{ u.username or '' }}" minlength="3" required>
<button type="submit" class="btn btn-green">تحديث الاسم</button>
</form>
</div>

<div class="card">
<h2>
<svg viewBox="0 0 24 24"><path d="M21 19V5c0-1.1-.9-2-2-2H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2zM8.5 13.5l2.5 3.01L14.5 12l4.5 6H5l3.5-4.5z"/></svg>
الصورة الشخصية
</h2>
<form method="POST" action="/profile/upload-avatar" enctype="multipart/form-data">
<label class="file-drop" for="avatarFile">
<svg viewBox="0 0 24 24" style="width:36px;height:36px;fill:#00d4ff;display:block;margin:0 auto 8px"><path d="M9 16h6v-6h4l-7-7-7 7h4zm-4 2h14v2H5z"/></svg>
<span id="fileName">اضغط لاختيار صورة</span>
<input type="file" id="avatarFile" name="file" accept="image/*" onchange="document.getElementById('fileName').textContent=this.files[0]?this.files[0].name:'اضغط لاختيار صورة'">
</label>
<button type="submit" class="btn">رفع الصورة</button>
</form>
</div>

<div class="card">
<h2>
<svg viewBox="0 0 24 24"><path d="M18 8h-1V6c0-2.76-2.24-5-5-5S7 3.24 7 6v2H6c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V10c0-1.1-.9-2-2-2zm-6 9c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2zm3.1-9H8.9V6c0-1.71 1.39-3.1 3.1-3.1 1.71 0 3.1 1.39 3.1 3.1v2z"/></svg>
تغيير كلمة السر
</h2>
<form method="POST">
<input type="hidden" name="action" value="update_pw">
<label>كلمة السر الحالية</label>
<input type="password" name="old_password" required>
<label>كلمة السر الجديدة</label>
<input type="password" name="new_password" required minlength="4">
<button type="submit" class="btn btn-orange">تغيير كلمة السر</button>
</form>
</div>

<div class="card">
<h2>
<svg viewBox="0 0 24 24"><path d="M12.65 10C11.83 7.67 9.61 6 7 6c-3.31 0-6 2.69-6 6s2.69 6 6 6c2.61 0 4.83-1.67 5.65-4H17v4h4v-4h2v-4H12.65zM7 14c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2z"/></svg>
مفتاح الاستيراد
</h2>
<div style="font-size:12px;color:#8e8eab;line-height:1.7;margin-bottom:12px">
هذا المفتاح يسمح لك باستيراد حسابك على أي رابط للموقع.<br>
احفظه في مكان آمن — لا تشاركه مع أحد.
</div>
<div id="recoveryKeyBox" style="background:linear-gradient(135deg,#0c1e3e,#1e3a8a);border:2px dashed rgba(0,212,255,.5);border-radius:14px;padding:16px;text-align:center;margin-bottom:12px">
<div id="recoveryKeyVal" style="font-size:18px;font-weight:900;color:#fff;letter-spacing:3px;font-family:monospace;direction:ltr;user-select:all;word-break:break-all">— — — —</div>
</div>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
<button type="button" onclick="revealKey()" id="revealBtn" class="btn" style="margin-top:0;background:linear-gradient(135deg,#7b2ff7,#00d4ff)">
<svg viewBox="0 0 24 24" style="width:16px;height:16px;fill:#fff;vertical-align:middle;margin-left:4px"><path d="M12 4.5C7 4.5 2.73 7.61 1 12c1.73 4.39 6 7.5 11 7.5s9.27-3.11 11-7.5c-1.73-4.39-6-7.5-11-7.5zM12 17c-2.76 0-5-2.24-5-5s2.24-5 5-5 5 2.24 5 5-2.24 5-5 5zm0-8c-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3-1.34-3-3-3z"/></svg>
إظهار
</button>
<button type="button" onclick="copyKey()" id="copyBtn" class="btn btn-green" style="margin-top:0" disabled>
<svg viewBox="0 0 24 24" style="width:16px;height:16px;fill:#fff;vertical-align:middle;margin-left:4px"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg>
نسخ
</button>
</div>
<div style="font-size:11px;color:#6e6e8a;text-align:center;margin-top:10px;line-height:1.6">
في أي رابط آخر للموقع — اضغط "استيراد حساب" والصق المفتاح
</div>
</div>

<div class="card">
<h2>
<svg viewBox="0 0 24 24"><path d="M11 7h2v2h-2zm0 4h2v6h-2zm1-9C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2z"/></svg>
معلومات سريعة
</h2>
<div class="info-row"><span>تاريخ الانضمام</span><b>{{ u.created|timestamp }}</b></div>
<div class="info-row"><span>آخر دخول</span><b>{{ u.last_login|timestamp }}</b></div>
</div>

<a href="/logout" class="logout-btn">
<svg viewBox="0 0 24 24"><path d="M17 7l-1.41 1.41L18.17 11H8v2h10.17l-2.58 2.58L17 17l5-5zM4 5h8V3H4c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h8v-2H4V5z"/></svg>
تسجيل الخروج
</a>

</div>
<script>
var _recoveryKey = '';
function revealKey(){
    var btn = document.getElementById('revealBtn');
    btn.disabled = true;
    btn.innerHTML = 'جاري...';
    fetch('/api/my-recovery-key', {credentials:'same-origin'})
        .then(function(r){ return r.json(); })
        .then(function(d){
            if(d.ok){
                _recoveryKey = d.key;
                document.getElementById('recoveryKeyVal').textContent = d.key;
                document.getElementById('copyBtn').disabled = false;
                btn.innerHTML = '✅ ظاهر';
            } else {
                alert('فشل: ' + (d.error || ''));
                btn.disabled = false;
                btn.innerHTML = 'إظهار';
            }
        })
        .catch(function(e){
            alert('خطأ: ' + e.message);
            btn.disabled = false;
            btn.innerHTML = 'إظهار';
        });
}
function copyKey(){
    if(!_recoveryKey) return;
    if(navigator.clipboard && navigator.clipboard.writeText){
        navigator.clipboard.writeText(_recoveryKey).then(function(){
            var btn = document.getElementById('copyBtn');
            var old = btn.innerHTML;
            btn.innerHTML = '✅ تم';
            setTimeout(function(){ btn.innerHTML = old; }, 1500);
        });
    } else {
        alert('المفتاح: ' + _recoveryKey);
    }
}
</script>

</body>
</html>"""


CHAT_HTML = r"""
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<title>الدعم الفني</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;font-family:-apple-system,'Segoe UI',Tahoma,sans-serif}
html,body{height:100%;overflow:hidden}
body{background:#0a0a0f;color:#f5f5f7}

.chat-header{position:fixed;top:0;left:0;right:0;height:64px;background:#14141f;border-bottom:1px solid #2a2a35;display:flex;align-items:center;padding:0 12px;gap:10px;z-index:100}
.chat-header .back{width:42px;height:42px;border:none;background:transparent;cursor:pointer;display:flex;align-items:center;justify-content:center;border-radius:50%;flex-shrink:0}
.chat-header .back svg{width:24px;height:24px;fill:#0ea5e9}
.chat-header .avatar{width:44px;height:44px;border-radius:50%;background:linear-gradient(135deg,#1e3a8a,#0ea5e9);display:flex;align-items:center;justify-content:center;flex-shrink:0;position:relative;overflow:hidden;color:#fff;font-weight:900;font-size:18px}
.chat-header .avatar img{width:100%;height:100%;object-fit:cover}
.chat-header .avatar svg{width:100%;height:100%;display:block}
.chat-header .avatar .online{position:absolute;bottom:0;right:0;width:12px;height:12px;border-radius:50%;background:#00b894;border:2px solid #14141f;z-index:5}
.admin-avatar{background:transparent !important;box-shadow:0 4px 12px rgba(0,212,255,.35)}

/* اسم الرسالة تحت كل رسالة */
.bubble .msg-sender{display:flex;align-items:center;gap:6px;margin-bottom:6px;font-size:11px;font-weight:700}
.bubble .msg-sender .sender-av{width:20px;height:20px;border-radius:50%;overflow:hidden;flex-shrink:0;background:linear-gradient(135deg,#1e3a8a,#0ea5e9);display:flex;align-items:center;justify-content:center}
.bubble .msg-sender .sender-av svg{width:100%;height:100%}
.bubble .msg-sender .sender-av img{width:100%;height:100%;object-fit:cover}
.msg-row.admin .bubble .msg-sender{color:rgba(255,255,255,.85)}
.msg-row.user .bubble .msg-sender{color:rgba(255,255,255,.85)}
.chat-header .info{flex:1;min-width:0}
.chat-header .info .name{font-size:15px;font-weight:700}
.chat-header .info .status{font-size:11px;color:#00b894;margin-top:2px}

.chat-body{position:fixed;top:64px;bottom:70px;left:0;right:0;overflow-y:auto;padding:16px;background:#0a0a0f}

.welcome{background:#14141f;border:1px solid #2a2a35;border-radius:16px;padding:16px;text-align:center;margin-bottom:16px;font-size:13px;color:#8e8e93;line-height:1.8}
.welcome svg{width:32px;height:32px;fill:#0ea5e9;margin-bottom:8px;display:block;margin-left:auto;margin-right:auto}
.welcome b{color:#f5f5f7;font-size:14px;display:block;margin-bottom:4px}

.msg-row{display:flex;margin-bottom:10px;width:100%}
.msg-row.user{justify-content:flex-start}
.msg-row.admin{justify-content:flex-end}
.bubble{max-width:75%;padding:10px 14px;border-radius:16px;font-size:14px;line-height:1.5;word-wrap:break-word}
.msg-row.user .bubble{background:#1e3a8a;color:#fff;border-bottom-left-radius:4px}
.msg-row.admin .bubble{background:#0088cc;color:#fff;border-bottom-right-radius:4px}
.bubble img,.bubble video{max-width:200px;border-radius:12px;margin-top:6px;display:block}
.bubble .meta{display:flex;align-items:center;gap:4px;justify-content:flex-end;margin-top:4px;font-size:10px;opacity:0.7;direction:ltr}
.bubble .meta svg{width:14px;height:14px;fill:currentColor}

.chat-input{position:fixed;bottom:0;left:0;right:0;height:70px;background:#14141f;border-top:1px solid #2a2a35;display:flex;align-items:center;padding:0 8px;gap:6px;z-index:100}
.chat-input input[type="text"]{flex:1;padding:12px 16px;border:1px solid #2a2a35;border-radius:24px;background:#0a0a0f;color:#f5f5f7;font-size:15px;outline:none;font-family:inherit;min-width:0}
.chat-input input[type="text"]::placeholder{color:#8e8e93}
.chat-input .icon-btn{width:44px;height:44px;border-radius:50%;background:transparent;border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0}
.chat-input .icon-btn svg{width:24px;height:24px;fill:#8e8e93}
.chat-input .emoji-btn svg{fill:#FFC107}
.chat-input .send{width:48px;height:48px;border-radius:50%;background:linear-gradient(135deg,#1e3a8a,#0ea5e9);border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0}
.chat-input .send svg{width:24px;height:24px;fill:#fff}

.emoji-panel{position:fixed;bottom:70px;left:0;right:0;background:#14141f;border-top:1px solid #2a2a35;padding:10px;display:none;grid-template-columns:repeat(10,1fr);gap:4px;z-index:99;max-height:200px;overflow-y:auto}
.emoji-panel.show{display:grid}
.emoji-panel button{background:transparent;border:none;font-size:24px;cursor:pointer;padding:6px;border-radius:8px}

.preview-box{position:fixed;bottom:70px;left:0;right:0;background:#14141f;border-top:1px solid #2a2a35;padding:12px;display:none;z-index:99;text-align:center}
.preview-box.show{display:block}
.preview-box img,.preview-box video{max-height:150px;border-radius:10px;display:block;margin:0 auto 8px}
.preview-box .actions{display:flex;gap:8px;justify-content:center}
.preview-box button{padding:8px 16px;border:none;border-radius:10px;cursor:pointer;font-size:13px;font-weight:600}
.preview-box .send-btn{background:linear-gradient(135deg,#1e3a8a,#0ea5e9);color:#fff}
.preview-box .cancel-btn{background:#2a2a35;color:#f5f5f7}

.empty-chat{text-align:center;padding:60px 20px;color:#6e6e8a;font-size:13px}
.empty-chat svg{width:64px;height:64px;fill:#2a2a35;display:block;margin:0 auto 14px}
</style>
</head>
<body>

<div class="chat-header">
<button class="back" onclick="window.location.href='/'">
<svg viewBox="0 0 24 24"><path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z"/></svg>
</button>
<!-- شعار SVG للدعم -->
<div class="avatar admin-avatar">
<svg viewBox="0 0 40 40" xmlns="http://www.w3.org/2000/svg">
<defs>
<linearGradient id="adminG" x1="0%" y1="0%" x2="100%" y2="100%">
<stop offset="0%" stop-color="#00d4ff"/>
<stop offset="100%" stop-color="#7b2ff7"/>
</linearGradient>
<radialGradient id="adminGlow" cx="50%" cy="50%" r="50%">
<stop offset="0%" stop-color="#ffffff" stop-opacity="0.4"/>
<stop offset="100%" stop-color="#ffffff" stop-opacity="0"/>
</radialGradient>
</defs>
<circle cx="20" cy="20" r="19" fill="url(#adminG)"/>
<circle cx="20" cy="20" r="19" fill="url(#adminGlow)"/>
<!-- رأس الدعم -->
<circle cx="20" cy="15" r="5.5" fill="#ffffff"/>
<path d="M8 34 Q 20 24 32 34 Z" fill="#ffffff"/>
<!-- سماعة الدعم (شارة) -->
<circle cx="31" cy="30" r="7" fill="#00d4a5" stroke="#14141f" stroke-width="2"/>
<path d="M28 30 Q 31 33 34 30" stroke="#ffffff" stroke-width="1.5" fill="none" stroke-linecap="round"/>
<circle cx="28" cy="29" r="1" fill="#ffffff"/>
<circle cx="34" cy="29" r="1" fill="#ffffff"/>
</svg>
<div class="online"></div>
</div>
<div class="info">
<div class="name">الدعم الفني</div>
<div class="status">● متصل الآن</div>
</div>
</div>

<div class="chat-body" id="chatBody">

{% if not chat or not chat.messages %}
<div class="welcome">
<svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/></svg>
<b>أهلاً {{ username }}</b>
هذي محادثتك مع الدعم الفني<br>اكتب رسالتك وسنرد عليك بأسرع وقت
</div>
{% endif %}

<div id="messagesList">
{% for m in chat.messages %}
<div class="msg-row {{ m.sender }}">
<div class="bubble">
<!-- اسم المرسل + صورته -->
<div class="msg-sender">
<div class="sender-av">
{% if m.sender == 'admin' %}
<svg viewBox="0 0 40 40" xmlns="http://www.w3.org/2000/svg">
<circle cx="20" cy="20" r="20" fill="#0088cc"/>
<circle cx="20" cy="15" r="5" fill="#fff"/>
<path d="M9 33 Q 20 24 31 33 Z" fill="#fff"/>
</svg>
{% else %}
{% if user.avatar %}
<img src="{{ user.avatar }}" alt="{{ username }}">
{% else %}
<span style="color:#fff;font-weight:900;font-size:11px">{{ (username or 'U')[0]|upper }}</span>
{% endif %}
{% endif %}
</div>
<span>{% if m.sender == 'admin' %}الدعم الفني{% else %}{{ username }}{% endif %}</span>
</div>
{% if m.media %}
  {% if m.media_type == 'video' %}
  <video src="/uploads/{{ m.media }}" controls></video>
  {% else %}
  <img src="/uploads/{{ m.media }}" alt="صورة">
  {% endif %}
{% else %}
  {{ m.message }}
{% endif %}
<div class="meta">
<span>{{ m.time|timestamp }}</span>
{% if m.sender == 'user' %}
{% if chat.last_seen_admin and chat.last_seen_admin >= m.time %}
<svg viewBox="0 0 24 24" style="fill:#00d4ff;width:18px;height:18px"><path d="M18 7l-1.41-1.41-6.34 6.34 1.41 1.41L18 7zm4.24-1.41L11.66 16.17 7.48 12l-1.41 1.41L11.66 19l12-12-1.42-1.41zM.41 13.41L6 19l1.41-1.41L1.83 12 .41 13.41z"/></svg>
{% else %}
<svg viewBox="0 0 24 24" style="fill:currentColor;width:14px;height:14px"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>
{% endif %}
{% endif %}
</div>
</div>
</div>
{% endfor %}
</div>

</div>

<form method="POST" action="/support/reply" class="chat-input" id="chatForm">
<button type="button" class="icon-btn emoji-btn" onclick="toggleEmoji(event)">
<svg viewBox="0 0 24 24"><path d="M11.99 2C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2zM12 20c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8zm3.5-9c.83 0 1.5-.67 1.5-1.5S16.33 8 15.5 8 14 8.67 14 9.5s.67 1.5 1.5 1.5zm-7 0c.83 0 1.5-.67 1.5-1.5S9.33 8 8.5 8 7 8.67 7 9.5 7.67 11 8.5 11zm3.5 6.5c2.33 0 4.31-1.46 5.11-3.5H6.89c.8 2.04 2.78 3.5 5.11 3.5z"/></svg>
</button>
<button type="button" class="icon-btn attach" onclick="document.getElementById('fileInput').click()">
<svg viewBox="0 0 24 24"><path d="M16.5 6v11.5c0 2.21-1.79 4-4 4s-4-1.79-4-4V5c0-1.38 1.12-2.5 2.5-2.5s2.5 1.12 2.5 2.5v10.5c0 .55-.45 1-1 1s-1-.45-1-1V6H10v9.5c0 1.38 1.12 2.5 2.5 2.5s2.5-1.12 2.5-2.5V5c0-2.21-1.79-4-4-4S7 2.79 7 5v12.5c0 3.04 2.46 5.5 5.5 5.5s5.5-2.46 5.5-5.5V6h-1.5z"/></svg>
</button>
<input type="file" id="fileInput" accept="image/*,video/*" style="display:none" onchange="previewFile(event)">
<input type="text" name="message" id="msgInput" placeholder="اكتب رسالتك..." autocomplete="off">
<button type="submit" class="send">
<svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
</button>
</form>

<div class="emoji-panel" id="emojiPanel"></div>
<div class="preview-box" id="previewBox">
<div id="previewContent"></div>
<div class="actions">
<button class="send-btn" onclick="sendFile()">إرسال</button>
<button class="cancel-btn" onclick="cancelFile()">إلغاء</button>
</div>
</div>

<script>
const EMOJIS = ["😀","😂","😍","🥰","😎","🤔","😢","😡","👍","👎","❤️","🔥","✨","💯","🙏","🤝"];
const emojiPanel = document.getElementById('emojiPanel');
emojiPanel.innerHTML = EMOJIS.map(function(e){ return '<button type="button" onclick="addEmoji(\'' + e + '\')">' + e + '</button>'; }).join('');

function toggleEmoji(e){
    e.preventDefault();
    emojiPanel.classList.toggle('show');
    document.getElementById('previewBox').classList.remove('show');
}
function addEmoji(e){
    const inp = document.getElementById('msgInput');
    inp.value += e;
    inp.focus();
}

let currentFile = null;
function previewFile(event){
    const file = event.target.files[0];
    if(!file) return;
    currentFile = file;
    const box = document.getElementById('previewBox');
    const content = document.getElementById('previewContent');
    const url = URL.createObjectURL(file);
    if(file.type.startsWith('image/')){
        content.innerHTML = '<img src="' + url + '">';
    } else if(file.type.startsWith('video/')){
        content.innerHTML = '<video src="' + url + '" controls></video>';
    }
    box.classList.add('show');
    emojiPanel.classList.remove('show');
}
function cancelFile(){
    currentFile = null;
    document.getElementById('fileInput').value = '';
    document.getElementById('previewBox').classList.remove('show');
}
async function sendFile(){
    if(!currentFile) return;
    const formData = new FormData();
    formData.append('file', currentFile);
    try {
        const res = await fetch('/support/upload-chat', { method: 'POST', body: formData });
        if(res.ok){
            cancelFile();
            location.reload();
        } else {
            alert('فشل الرفع');
        }
    } catch(e){
        alert('خطأ: ' + e.message);
    }
}

// تحديث تلقائي — رسائل جديدة تظهر بدون reload
let lastTime = Math.floor(Date.now() / 1000);
let lastCount = 0;
let _chatBusy = false;

function _chatScrollBottom(){
    var b = document.getElementById('chatBody');
    if(b) b.scrollTop = b.scrollHeight;
}

function _chatEscape(t){
    var d = document.createElement('div');
    d.textContent = t || '';
    return d.innerHTML;
}

function _chatAddMessage(m){
    var list = document.getElementById('messagesList');
    if(!list) return;
    var isMine = (m.sender === 'user');
    var who = isMine ? 'أنت' : 'الدعم الفني';
    var mediaHtml = '';
    if(m.media){
        if(m.media_type === 'video'){
            mediaHtml = '<video src="/uploads/' + _chatEscape(m.media) + '" controls></video>';
        } else {
            mediaHtml = '<img src="/uploads/' + _chatEscape(m.media) + '" alt="صورة">';
        }
    }
    var bodyText = m.media ? mediaHtml : _chatEscape(m.message);
    var t = new Date((m.time || 0) * 1000);
    var hh = ('0' + t.getHours()).slice(-2);
    var mm = ('0' + t.getMinutes()).slice(-2);
    var timeStr = hh + ':' + mm;
    var row = document.createElement('div');
    row.className = 'msg-row ' + (isMine ? 'user' : 'admin');
    row.innerHTML =
        '<div class="bubble">' +
        '<div class="msg-sender"><span>' + who + '</span></div>' +
        bodyText +
        '<div class="meta"><span>' + timeStr + '</span></div>' +
        '</div>';
    // احذف رسالة "لا يوجد" لو موجودة
    var empty = list.querySelector('.empty-chat');
    if(empty) empty.remove();
    list.appendChild(row);
    _chatScrollBottom();
    // اهتزاز وصوت
    if(!isMine){
        if(navigator.vibrate) try { navigator.vibrate([80, 40, 80]); } catch(e){}
        try {
            if(!window._chatAudio) window._chatAudio = new (window.AudioContext || window.webkitAudioContext)();
            var ac = window._chatAudio;
            var o = ac.createOscillator();
            var g = ac.createGain();
            o.frequency.value = 880;
            o.type = 'sine';
            g.gain.setValueAtTime(0, ac.currentTime);
            g.gain.linearRampToValueAtTime(0.15, ac.currentTime + 0.05);
            g.gain.linearRampToValueAtTime(0, ac.currentTime + 0.3);
            o.connect(g); g.connect(ac.destination);
            o.start(); o.stop(ac.currentTime + 0.3);
        } catch(e){}
    }
}

function _chatPoll(){
    if(document.hidden) return;
    if(_chatBusy) return;
    _chatBusy = true;
    fetch('/api/chat/since/' + lastTime + '?t=' + Date.now(), {cache: 'no-store'})
        .then(function(r){ return r.ok ? r.json() : null; })
        .then(function(d){
            _chatBusy = false;
            if(!d) return;
            if(d.messages && d.messages.length > 0){
                d.messages.forEach(function(m){
                    _chatAddMessage(m);
                    if(m.time && m.time > lastTime){
                        lastTime = Math.floor(m.time);
                    }
                });
            }
        })
        .catch(function(){ _chatBusy = false; });
}
setTimeout(_chatPoll, 2000);
setInterval(_chatPoll, 2500);

// تحديث تلقائي للـ count
setInterval(() => {
    fetch('/api/chat/messages')
        .then(r => r.json())
        .then(d => {
            if(lastCount > 0 && d.count > lastCount){
                // الرسائل تُضاف من _chatPoll
            }
            lastCount = d.count;
        })
        .catch(() => {});
}, 15000);

document.addEventListener('DOMContentLoaded', () => {
    const body = document.getElementById('chatBody');
    if(body) body.scrollTop = body.scrollHeight;
    fetch('/api/chat/messages')
        .then(r => r.json())
        .then(d => { lastCount = d.count; })
        .catch(() => {});
    // علّم كمقروء بعد ثانيتين (بعد ما يشوف الرسائل)
    setTimeout(function(){
        fetch('/api/chat/mark-read', {method:'POST'}).catch(function(){});
    }, 2000);
});
</script>
</body>
</html>
"""


SUPPORT_HTML = r"""
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<title>الدعم</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;font-family:-apple-system,'Segoe UI',Tahoma,sans-serif}
html,body{height:100%;overflow:hidden}
body{background:#0a0a0f;color:#f5f5f7}

.chat-header{position:fixed;top:0;left:0;right:0;height:64px;background:#14141f;border-bottom:1px solid #2a2a35;display:flex;align-items:center;padding:0 12px;gap:10px;z-index:100}
.chat-header .back{width:42px;height:42px;border:none;background:transparent;cursor:pointer;display:flex;align-items:center;justify-content:center;border-radius:50%;flex-shrink:0}
.chat-header .back svg{width:24px;height:24px;fill:#0ea5e9}
.chat-header .avatar{width:44px;height:44px;border-radius:50%;background:linear-gradient(135deg,#1e3a8a,#0ea5e9);display:flex;align-items:center;justify-content:center;flex-shrink:0;position:relative}
.chat-header .avatar svg{width:26px;height:26px;fill:#fff}
.chat-header .avatar .online{position:absolute;bottom:0;right:0;width:12px;height:12px;border-radius:50%;background:#00b894;border:2px solid #14141f}
.chat-header .info{flex:1;min-width:0}
.chat-header .info .name{font-size:15px;font-weight:700}
.chat-header .info .status{font-size:11px;color:#00b894;margin-top:2px}

.chat-body{position:fixed;top:64px;bottom:70px;left:0;right:0;overflow-y:auto;padding:16px;background:#0a0a0f}

.ticket-code-box{background:linear-gradient(135deg,#0c1e3e,#1e3a8a);border-radius:16px;padding:14px;text-align:center;margin-bottom:16px;display:flex;align-items:center;justify-content:center;gap:10px}
.ticket-code-box svg{width:20px;height:20px;fill:#fff}
.ticket-code-box .code{font-size:16px;font-weight:800;letter-spacing:2px;font-family:monospace;direction:ltr;color:#fff}
.ticket-code-box .copy{background:rgba(255,255,255,.2);border:none;color:#fff;padding:6px 12px;border-radius:8px;font-size:12px;cursor:pointer}
.welcome{background:#14141f;border:1px solid #2a2a35;border-radius:16px;padding:16px;text-align:center;margin-bottom:16px;font-size:13px;color:#8e8e93;line-height:1.8}
.welcome svg{width:32px;height:32px;fill:#0ea5e9;margin-bottom:8px;display:block;margin-left:auto;margin-right:auto}
.welcome b{color:#f5f5f7;font-size:14px;display:block;margin-bottom:4px}

.msg-row{display:flex;margin-bottom:10px;width:100%}
.msg-row.user{justify-content:flex-start}
.msg-row.admin{justify-content:flex-end}
.bubble{max-width:75%;padding:10px 14px;border-radius:16px;font-size:14px;line-height:1.5;word-wrap:break-word}
.msg-row.user .bubble{background:#1e3a8a;color:#fff;border-bottom-left-radius:4px}
.msg-row.admin .bubble{background:#0088cc;color:#fff;border-bottom-right-radius:4px}
.bubble img,.bubble video{max-width:200px;border-radius:12px;margin-top:6px;display:block}
.bubble .meta{display:flex;align-items:center;gap:4px;justify-content:flex-end;margin-top:4px;font-size:10px;opacity:0.7;direction:ltr}
.bubble .meta svg{width:14px;height:14px;fill:currentColor}

.chat-input{position:fixed;bottom:0;left:0;right:0;height:70px;background:#14141f;border-top:1px solid #2a2a35;display:flex;align-items:center;padding:0 8px;gap:6px;z-index:100}
.chat-input input[type="text"]{flex:1;padding:12px 16px;border:1px solid #2a2a35;border-radius:24px;background:#0a0a0f;color:#f5f5f7;font-size:15px;outline:none;font-family:inherit;min-width:0}
.chat-input input[type="text"]::placeholder{color:#8e8e93}
.chat-input .icon-btn{width:44px;height:44px;border-radius:50%;background:transparent;border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0}
.chat-input .icon-btn svg{width:24px;height:24px;fill:#8e8e93}
.chat-input .emoji-btn svg{fill:#FFC107}
.chat-input .send{width:48px;height:48px;border-radius:50%;background:linear-gradient(135deg,#1e3a8a,#0ea5e9);border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0}
.chat-input .send svg{width:24px;height:24px;fill:#fff}

.emoji-panel{position:fixed;bottom:70px;left:0;right:0;background:#14141f;border-top:1px solid #2a2a35;padding:10px;display:none;grid-template-columns:repeat(10,1fr);gap:4px;z-index:99;max-height:200px;overflow-y:auto}
.emoji-panel.show{display:grid}
.emoji-panel button{background:transparent;border:none;font-size:24px;cursor:pointer;padding:6px;border-radius:8px}

.preview-box{position:fixed;bottom:70px;left:0;right:0;background:#14141f;border-top:1px solid #2a2a35;padding:12px;display:none;z-index:99;text-align:center}
.preview-box.show{display:block}
.preview-box img,.preview-box video{max-height:150px;border-radius:10px;display:block;margin:0 auto 8px}
.preview-box .actions{display:flex;gap:8px;justify-content:center}
.preview-box button{padding:8px 16px;border:none;border-radius:10px;cursor:pointer;font-size:13px;font-weight:600}
.preview-box .send-btn{background:linear-gradient(135deg,#1e3a8a,#0ea5e9);color:#fff}
.preview-box .cancel-btn{background:#2a2a35;color:#f5f5f7}
</style>
</head>
<body>

<div class="chat-header">
<button class="back" onclick="window.location.href='/'">
<svg viewBox="0 0 24 24"><path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z"/></svg>
</button>
<div class="avatar">
<svg viewBox="0 0 24 24"><path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/></svg>
<div class="online"></div>
</div>
<div class="info">
<div class="name">الدعم الفني</div>
<div class="status">متصل الآن</div>
</div>
</div>

<div class="chat-body" id="chatBody">
<div class="ticket-code-box">
<svg viewBox="0 0 24 24"><path d="M20 8h-2.81c-.45-.78-1.07-1.45-1.82-1.96L17 4.41 15.59 3l-2.17 2.17C12.96 5.06 12.49 5 12 5s-.96.06-1.41.17L8.41 3 7 4.41l1.62 1.63C7.88 6.55 7.26 7.22 6.81 8H4v2h2.09c-.05.33-.09.66-.09 1v1H4v2h2v1c0 .34.04.67.09 1H4v2h2.81c1.04 1.79 2.97 3 5.19 3s4.15-1.21 5.19-3H20v-2h-2.09c.05-.33.09-.66.09-1v-1h2v-2h-2v-1c0-.34-.04-.67-.09-1H20V8z"/></svg>
<span class="code">{{ ticket.code }}</span>
<button class="copy" onclick="copyCode('{{ ticket.code }}')">نسخ</button>
</div>

<div class="welcome">
<svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/></svg>
<b>أهلاً بك في الدعم الفني</b>
أرسل رسالتك وسنرد عليك فوراً
</div>

<div id="messagesList">
{% if ticket.message %}
<div class="msg-row user">
<div class="bubble">
{{ ticket.message }}
<div class="meta">
<span>{{ ticket.created|timestamp }}</span>
<svg viewBox="0 0 24 24"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>
</div>
</div>
</div>
{% endif %}
{% for r in ticket.replies %}
<div class="msg-row {{ r.sender }}">
<div class="bubble">
{% if r.media %}
  {% if r.media_type == 'video' %}
  <video src="/uploads/{{ r.media }}" controls></video>
  {% else %}
  <img src="/uploads/{{ r.media }}" alt="صورة">
  {% endif %}
{% elif r.message and r.message.startswith('[IMAGE]:') %}
  <img src="/uploads/{{ r.message[8:] }}" alt="صورة">
{% elif r.message and r.message.startswith('[VIDEO]:') %}
  <video src="/uploads/{{ r.message[8:] }}" controls></video>
{% else %}
  {{ r.message }}
{% endif %}
<div class="meta">
<span>{{ r.time|timestamp }}</span>
{% if r.sender == 'user' %}
<svg viewBox="0 0 24 24"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>
{% endif %}
</div>
</div>
</div>
{% endfor %}
</div>

</div>

<form method="POST" action="/support/reply" class="chat-input" id="chatForm">
<input type="hidden" name="code" value="{{ ticket.code }}">
<button type="button" class="icon-btn emoji-btn" onclick="toggleEmoji(event)">
<svg viewBox="0 0 24 24"><path d="M11.99 2C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2zM12 20c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8zm3.5-9c.83 0 1.5-.67 1.5-1.5S16.33 8 15.5 8 14 8.67 14 9.5s.67 1.5 1.5 1.5zm-7 0c.83 0 1.5-.67 1.5-1.5S9.33 8 8.5 8 7 8.67 7 9.5 7.67 11 8.5 11zm3.5 6.5c2.33 0 4.31-1.46 5.11-3.5H6.89c.8 2.04 2.78 3.5 5.11 3.5z"/></svg>
</button>
<button type="button" class="icon-btn attach" onclick="document.getElementById('fileInput').click()">
<svg viewBox="0 0 24 24"><path d="M16.5 6v11.5c0 2.21-1.79 4-4 4s-4-1.79-4-4V5c0-1.38 1.12-2.5 2.5-2.5s2.5 1.12 2.5 2.5v10.5c0 .55-.45 1-1 1s-1-.45-1-1V6H10v9.5c0 1.38 1.12 2.5 2.5 2.5s2.5-1.12 2.5-2.5V5c0-2.21-1.79-4-4-4S7 2.79 7 5v12.5c0 3.04 2.46 5.5 5.5 5.5s5.5-2.46 5.5-5.5V6h-1.5z"/></svg>
</button>
<input type="file" id="fileInput" accept="image/*,video/*" style="display:none" onchange="previewFile(event)">
<input type="text" name="message" id="msgInput" placeholder="اكتب رسالتك..." autocomplete="off">
<button type="submit" class="send">
<svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
</button>
</form>

<div class="emoji-panel" id="emojiPanel"></div>
<div class="preview-box" id="previewBox">
<div id="previewContent"></div>
<div class="actions">
<button class="send-btn" onclick="sendFile()">إرسال</button>
<button class="cancel-btn" onclick="cancelFile()">إلغاء</button>
</div>
</div>

<script>
const TICKET_CODE = "{{ ticket.code }}";

const EMOJIS = ["😀","😂","😍","🥰","😎","🤔","😢","😡","👍","👎","❤️","🔥","","✨","","💯","🙏","","","🤝"];
const emojiPanel = document.getElementById('emojiPanel');
emojiPanel.innerHTML = EMOJIS.map(e => '<button type="button" onclick="addEmoji(\'' + e + '\')">' + e + '</button>').join('');

function toggleEmoji(e){
    e.preventDefault();
    emojiPanel.classList.toggle('show');
    document.getElementById('previewBox').classList.remove('show');
}
function addEmoji(e){
    const inp = document.getElementById('msgInput');
    inp.value += e;
    inp.focus();
}

let currentFile = null;
function previewFile(event){
    const file = event.target.files[0];
    if(!file) return;
    currentFile = file;
    const box = document.getElementById('previewBox');
    const content = document.getElementById('previewContent');
    const url = URL.createObjectURL(file);
    if(file.type.startsWith('image/')){
        content.innerHTML = '<img src="' + url + '">';
    } else if(file.type.startsWith('video/')){
        content.innerHTML = '<video src="' + url + '" controls></video>';
    }
    box.classList.add('show');
    emojiPanel.classList.remove('show');
}
function cancelFile(){
    currentFile = null;
    document.getElementById('fileInput').value = '';
    document.getElementById('previewBox').classList.remove('show');
}
async function sendFile(){
    if(!currentFile) return;
    const formData = new FormData();
    formData.append('file', currentFile);
    formData.append('code', TICKET_CODE);
    try {
        const res = await fetch('/support/upload', { method: 'POST', body: formData });
        if(res.ok){
            cancelFile();
            location.reload();
        } else {
            alert('فشل الرفع');
        }
    } catch(e){
        alert('خطأ: ' + e.message);
    }
}

// ═══════ إشعار صوتي ═══════
let lastCount = 0;
let audioCtx = null;
function playSound(){
    try {
        if(!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        const osc = audioCtx.createOscillator();
        const gain = audioCtx.createGain();
        osc.connect(gain);
        gain.connect(audioCtx.destination);
        osc.frequency.value = 900;
        gain.gain.value = 0.15;
        osc.start();
        osc.stop(audioCtx.currentTime + 0.2);
    } catch(e) { console.log('audio err', e); }
}

setInterval(() => {
    fetch('/api/ticket/' + TICKET_CODE)
        .then(r => r.json())
        .then(d => {
            if(lastCount > 0 && d.replies_count > lastCount){
                playSound();
                location.reload();
            }
            lastCount = d.replies_count;
        })
        .catch(() => {});
}, 5000);

document.addEventListener('DOMContentLoaded', () => {
    const body = document.getElementById('chatBody');
    if(body) body.scrollTop = body.scrollHeight;
    // احسب العدد الأولي
    fetch('/api/ticket/' + TICKET_CODE)
        .then(r => r.json())
        .then(d => { lastCount = d.replies_count; })
        .catch(() => {});
});

try { localStorage.setItem('my_ticket', TICKET_CODE); } catch(e){}
document.cookie = "last_ticket=" + TICKET_CODE + "; path=/; max-age=2592000";
// علّم كمقروء لما يفتح الصفحة
fetch('/api/support/mark-read/' + TICKET_CODE, {method:'POST'}).catch(function(){});
// يحدد الردود كمقروءة بعد ما المستخدم يشوفها (تختفي النقطة)
function markSeen(){
    if(document.visibilityState !== 'visible') return;
    fetch('/api/support/mark-read/' + encodeURIComponent(TICKET_CODE), {method: 'POST', keepalive: true}).catch(function(){});
}
setTimeout(markSeen, 1500);
document.addEventListener('visibilitychange', function(){ if(document.visibilityState === 'visible') setTimeout(markSeen, 500); });

function copyCode(code){
    navigator.clipboard.writeText(code).then(()=>{
        event.target.textContent='تم';
        setTimeout(()=>{event.target.textContent='نسخ';},1000);
    });
}
</script>
</body>
</html>
"""


IMPORT_HTML = r"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<title>استيراد حساب</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;font-family:-apple-system,'Segoe UI',Tahoma,sans-serif;-webkit-tap-highlight-color:transparent}
html,body{min-height:100vh}
body{background:#0a0a18;color:#fff;display:flex;align-items:center;justify-content:center;padding:20px;position:relative;min-height:100vh;direction:rtl}
.bg{position:fixed;inset:0;z-index:0;pointer-events:none;overflow:hidden}
.bg::before{content:"";position:absolute;width:500px;height:500px;background:radial-gradient(circle,rgba(123,47,247,.35),transparent 70%);top:-150px;right:-100px;border-radius:50%;filter:blur(40px)}
.bg::after{content:"";position:absolute;width:450px;height:450px;background:radial-gradient(circle,rgba(0,212,255,.25),transparent 70%);bottom:-120px;left:-100px;border-radius:50%;filter:blur(40px)}
.wrap{position:relative;z-index:2;width:100%;max-width:420px}
.card{background:linear-gradient(160deg,#161628,#0f0f1e);border:1px solid rgba(123,47,247,.2);border-radius:28px;padding:32px 26px;box-shadow:0 20px 60px rgba(0,0,0,.5)}
.icon-box{width:80px;height:80px;margin:0 auto 18px;border-radius:50%;background:linear-gradient(135deg,#7b2ff7,#00d4ff);display:flex;align-items:center;justify-content:center;box-shadow:0 8px 30px rgba(123,47,247,.5)}
.icon-box svg{width:40px;height:40px;fill:#fff}
.title{text-align:center;font-size:22px;font-weight:900;margin-bottom:10px;background:linear-gradient(135deg,#fff,#a8d8ff);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.subtitle{text-align:center;font-size:12px;color:#8e8eab;margin-bottom:24px;line-height:1.6}
.field{margin-bottom:16px}
.field label{display:block;font-size:13px;color:#a8a8bd;margin-bottom:8px;font-weight:600}
.field input{width:100%;padding:15px 16px;border:1.5px solid rgba(123,47,247,.15);border-radius:14px;background:rgba(0,0,0,.4);color:#fff;font-size:15px;outline:none;font-family:monospace;direction:ltr;text-align:center;letter-spacing:2px}
.field input:focus{border-color:#7b2ff7;background:rgba(123,47,247,.06);box-shadow:0 0 0 4px rgba(123,47,247,.12)}
.btn{width:100%;padding:16px;border:none;border-radius:14px;background:linear-gradient(135deg,#7b2ff7,#00d4ff);color:#fff;font-weight:800;font-size:16px;cursor:pointer;font-family:inherit;box-shadow:0 10px 30px rgba(123,47,247,.4);margin-top:6px;letter-spacing:.5px}
.btn:active{transform:scale(.98)}
.btn:disabled{opacity:.6;cursor:wait}
.err{background:rgba(233,69,96,.15);border:1px solid rgba(233,69,96,.4);color:#ff8aa3;padding:12px;border-radius:12px;font-size:13px;text-align:center;margin-bottom:16px;font-weight:600}
.ok{background:rgba(0,184,148,.15);border:1px solid rgba(0,184,148,.4);color:#6fe3c1;padding:12px;border-radius:12px;font-size:13px;text-align:center;margin-bottom:16px;font-weight:600}
.hint{font-size:11px;color:#6e6e8a;text-align:center;margin-top:14px;line-height:1.7}
.back-link{display:block;text-align:center;margin-top:18px;font-size:13px;color:#00d4ff;text-decoration:none;font-weight:700;padding:10px;border-radius:10px}
.back-link:hover,.back-link:active{background:rgba(0,212,255,.08)}
</style>
</head>
<body>

<div class="bg"></div>

<div class="wrap">
<div class="card">

<div class="icon-box">
<svg viewBox="0 0 24 24"><path d="M12.65 10C11.83 7.67 9.61 6 7 6c-3.31 0-6 2.69-6 6s2.69 6 6 6c2.61 0 4.83-1.67 5.65-4H17v4h4v-4h2v-4H12.65zM7 14c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2z"/></svg>
</div>

<div class="title">استيراد حساب</div>
<div class="subtitle">الصق مفتاح الاستيراد الخاص بك<br>لنقل حسابك إلى هذا الموقع</div>

{% if err %}
<div class="err">{{ err }}</div>
{% endif %}

{% if success %}
<div class="ok">{{ success }}</div>
<div style="text-align:center;padding:16px;font-size:13px;color:#c8c8d8;line-height:1.7">
سيتم تحويلك للصفحة الرئيسية خلال لحظات...
</div>
<script>setTimeout(function(){ window.location.href = '/'; }, 1800);</script>
{% else %}
<form method="POST" id="importForm" onsubmit="return doImport(event)">
<div class="field">
<label>مفتاح الاستيراد</label>
<input type="text" name="key" id="keyInput" placeholder="AT-XXXX-XXXX-XXXX" maxlength="20" autocomplete="off" autocapitalize="characters" spellcheck="false" required autofocus>
</div>
<button type="submit" class="btn" id="importBtn">
<svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:#fff;vertical-align:middle;margin-left:6px"><path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/></svg>
استيراد الحساب
</button>
</form>
<div class="hint">هذا المفتاح يعطيك وصولاً لحسابك من أي رابط<br>لا تشاركه مع أحد</div>
{% endif %}

<a href="/login" class="back-link">← رجوع لتسجيل الدخول</a>

</div>
</div>

<script>
function doImport(e){
    e.preventDefault();
    var key = document.getElementById('keyInput').value.trim().toUpperCase();
    if(!key){ alert('الصق المفتاح'); return false; }
    var btn = document.getElementById('importBtn');
    btn.disabled = true;
    btn.innerHTML = 'جاري التحقق...';
    fetch('/api/import-account', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        credentials: 'same-origin',
        body: JSON.stringify({key: key})
    })
    .then(function(r){ return r.json(); })
    .then(function(d){
        if(d.ok){
            btn.innerHTML = '✅ تم — جاري التحويل...';
            setTimeout(function(){ window.location.href = '/'; }, 800);
        } else {
            alert('❌ ' + (d.error || 'فشل'));
            btn.disabled = false;
            btn.innerHTML = 'استيراد الحساب';
        }
    })
    .catch(function(err){
        alert('خطأ: ' + err.message);
        btn.disabled = false;
        btn.innerHTML = 'استيراد الحساب';
    });
    return false;
}
document.getElementById('keyInput').addEventListener('input', function(e){
    var v = e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, '');
    // نمط: AT-XXXX-XXXX-XXXX
    var out = '';
    if(v.startsWith('AT')){ out = 'AT'; v = v.slice(2); } else { out = ''; }
    var rest = v;
    if(out === 'AT'){ out += '-'; }
    var parts = rest.match(/.{1,4}/g) || [];
    out += parts.join('-');
    e.target.value = out.slice(0, 17);
});
</script>

</body>
</html>"""


@app.route("/import", methods=["GET", "POST"])
def import_account_page():
    """صفحة استيراد الحساب بمفتاح الاستيراد"""
    err = ""
    success = ""
    if request.method == "POST":
        key = request.form.get("key", "").strip().upper()
        if not key:
            err = "الصق مفتاح الاستيراد"
        else:
            # ابحث عن المستخدم بالمفتاح
            try:
                conn = _db()
                row = conn.execute("SELECT * FROM users WHERE recovery_key=?", (key,)).fetchone()
                conn.close()
                if not row:
                    err = "المفتاح غير صحيح"
                else:
                    # سجّل الدخول
                    session["user_logged"] = True
                    session["user_name"] = row["display_name"]
                    session.permanent = True
                    session["user_avatar"] = row["avatar"] or ""
                    session.modified = True
                    # حدّث آخر دخول
                    try:
                        conn = _db()
                        conn.execute("UPDATE users SET last_login=? WHERE username=?", (time.time(), row["username"]))
                        conn.commit()
                        conn.close()
                    except Exception:
                        pass
                    success = "تم استيراد حسابك بنجاح"
                    print(f"[IMPORT] مستخدم استرجع حسابه: {row['display_name']}")
            except Exception as e:
                err = f"خطأ: {e}"
    return render_template_string(IMPORT_HTML, err=err, success=success)


@app.route("/api/import-account", methods=["POST"])
def api_import_account():
    """API لاستيراد الحساب — للاستدعاء من JS"""
    data = request.get_json(silent=True) or {}
    key = (data.get("key") or "").strip().upper()
    if not key:
        return jsonify({"ok": False, "error": "المفتاح مطلوب"})
    try:
        conn = _db()
        row = conn.execute("SELECT * FROM users WHERE recovery_key=?", (key,)).fetchone()
        conn.close()
        if not row:
            return jsonify({"ok": False, "error": "المفتاح غير صحيح"})
        session["user_logged"] = True
        session["user_name"] = row["display_name"]
        session.permanent = True
        session["user_avatar"] = row["avatar"] or ""
        session.modified = True
        try:
            conn = _db()
            conn.execute("UPDATE users SET last_login=? WHERE username=?", (time.time(), row["username"]))
            conn.commit()
            conn.close()
        except Exception:
            pass
        print(f"[IMPORT] مستخدم استرجع حسابه: {row['display_name']}")
        return jsonify({"ok": True, "username": row["display_name"]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/my-recovery-key")
def api_my_recovery_key():
    """يرجع مفتاح استيراد المستخدم الحالي"""
    if not session.get("user_logged"):
        return jsonify({"ok": False, "error": "login"}), 401
    username = session.get("user_name", "")
    if not username:
        return jsonify({"ok": False, "error": "no user"}), 401
    key = _get_recovery_key(username)
    if not key:
        return jsonify({"ok": False, "error": "failed"})
    return jsonify({"ok": True, "key": key})


ADMIN_HTML = r"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<title>لوحة الأدمن</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;font-family:-apple-system,'Segoe UI',Tahoma,sans-serif;-webkit-tap-highlight-color:transparent}
body{background:#07070d;color:#e8e8f0;min-height:100vh;padding:0 0 30px;direction:rtl;overflow-x:hidden}
.hdr{position:sticky;top:0;z-index:100;background:linear-gradient(135deg,#0c0c18,#12122a);border-bottom:1px solid rgba(123,47,247,.25);padding:16px 18px;display:flex;align-items:center;gap:14px;box-shadow:0 4px 24px rgba(0,0,0,.4)}
.hdr .logo{width:46px;height:46px;flex-shrink:0}
.hdr .titles{flex:1;min-width:0}
.hdr h1{font-size:19px;font-weight:900;background:linear-gradient(135deg,#7b2ff7,#00d4ff);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;letter-spacing:.5px}
.hdr .sub{font-size:11px;color:#6e6e8a;margin-top:3px;display:flex;align-items:center;gap:5px}
.hdr .sub .dot{width:6px;height:6px;border-radius:50%;background:#00d4a5;box-shadow:0 0 8px #00d4a5}
.hdr .logout{padding:9px 14px;background:rgba(233,69,96,.12);border:1px solid rgba(233,69,96,.35);color:#ff6b8a;border-radius:11px;font-size:12px;font-weight:700;text-decoration:none;display:flex;align-items:center;gap:6px}
.hdr .logout svg{width:14px;height:14px;fill:currentColor}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;padding:18px}
.stat{background:linear-gradient(160deg,#10101e,#0a0a14);border:1px solid rgba(123,47,247,.2);border-radius:18px;padding:14px 8px;text-align:center}
.stat b{font-size:22px;font-weight:900;display:block;margin-bottom:2px;background:linear-gradient(135deg,#00d4ff,#7b2ff7);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.stat span{font-size:10px;color:#6e6e8a}
.stat.ok b{background:linear-gradient(135deg,#00d4a5,#00b894);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.links{display:flex;gap:8px;padding:0 18px 12px;overflow-x:auto;overflow-y:hidden;scrollbar-width:none;-webkit-overflow-scrolling:touch;touch-action:pan-x}
.links::-webkit-scrollbar{display:none}
.lnk{padding:10px 14px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:12px;color:#8e8eab;font-size:12px;font-weight:700;white-space:nowrap;font-family:inherit;display:flex;align-items:center;gap:7px;flex-shrink:0;text-decoration:none;transition:all .2s;touch-action:manipulation;-webkit-tap-highlight-color:transparent;pointer-events:auto;position:relative;z-index:1}
.lnk:active{transform:scale(.96);background:rgba(0,212,255,.1)}
.tabs{display:flex;gap:8px;padding:0 18px 12px;overflow-x:auto;overflow-y:hidden;scrollbar-width:none;-webkit-overflow-scrolling:touch;touch-action:pan-x}
.tabs::-webkit-scrollbar{display:none}
.tb{padding:9px 14px;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.12);border-radius:12px;color:#c8c8d8;font-size:12px;font-weight:700;cursor:pointer;white-space:nowrap;font-family:inherit;display:flex;align-items:center;gap:6px;flex-shrink:0;touch-action:manipulation;-webkit-tap-highlight-color:transparent;pointer-events:auto}
.tb svg{width:16px;height:16px;fill:currentColor;flex-shrink:0}
.tb.active{background:linear-gradient(135deg,#7b2ff7,#00d4ff) !important;color:#fff !important;border-color:transparent !important;box-shadow:0 4px 18px rgba(123,47,247,.5) !important;font-weight:900 !important;transform:translateY(-1px)}
@keyframes hintBlink{0%,100%{opacity:0.3;transform:translateX(0)}50%{opacity:1;transform:translateX(-5px)}}
.tb:active{transform:scale(.94);background:linear-gradient(135deg,#7b2ff7,#00d4ff) !important;color:#fff !important}
.body{padding:0 18px 20px}
.pane{display:none}
.pane.active{display:block}
.card{background:#0f0f1c;border:1px solid rgba(123,47,247,.18);border-radius:20px;padding:18px;margin-bottom:14px}
.card h2{font-size:14px;color:#00d4ff;margin-bottom:14px;font-weight:800}
label{display:block;font-size:12px;color:#8e8eab;margin:12px 0 6px;font-weight:600}
label:first-of-type{margin-top:0}
input,textarea,select{width:100%;padding:12px 14px;border:1px solid rgba(255,255,255,.08);border-radius:12px;background:rgba(0,0,0,.35);color:#e8e8f0;font-size:14px;outline:none;font-family:inherit}
input:focus,textarea:focus,select:focus{border-color:#7b2ff7}
.btn{padding:14px 20px;border:none;border-radius:13px;color:#fff;cursor:pointer;font-weight:800;font-size:14px;display:inline-block;width:100%;margin-top:14px;text-align:center;text-decoration:none;font-family:inherit}
.btn-grad{background:linear-gradient(135deg,#7b2ff7,#00d4ff)}
.btn-green{background:linear-gradient(135deg,#00b894,#00a884)}
.btn-red{background:linear-gradient(135deg,#e94560,#c62a47)}
.btn-orange{background:linear-gradient(135deg,#f39c12,#e67e22)}
.file-drop{padding:22px;border:2px dashed rgba(123,47,247,.5);border-radius:14px;background:rgba(123,47,247,.06);color:#c8c8d8;text-align:center;font-size:13px;display:block;cursor:pointer;font-family:inherit}
.file-drop input{display:none}
.info-box{padding:12px 14px;border-radius:12px;background:rgba(0,212,255,.08);border:1px solid rgba(0,212,255,.25);font-size:12px;color:#8ee4ff;margin-top:10px;line-height:1.7}
.info-box.ok{background:rgba(0,184,148,.08);border-color:rgba(0,184,148,.25);color:#6fe3c1}
.info-box.err{background:rgba(233,69,96,.08);border-color:rgba(233,69,96,.3);color:#ff8aa3}
.info-box.warn{background:rgba(243,156,18,.08);border-color:rgba(243,156,18,.25);color:#ffcb6b}
.prow{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:12px 14px;background:rgba(0,0,0,.28);border:1px solid rgba(255,255,255,.05);border-radius:13px;margin-bottom:8px}
.prow .pn{font-weight:700;font-size:14px;flex:1}
.prow .cnt{font-size:11px;color:#00d4ff;background:rgba(0,212,255,.14);padding:4px 11px;border-radius:20px;font-weight:800}
.prow .del{width:34px;height:34px;background:rgba(233,69,96,.18);color:#ff6b8a;border-radius:9px;text-decoration:none;display:flex;align-items:center;justify-content:center;font-size:16px;flex-shrink:0}
.prow .pn{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.pl-name{font-weight:800;font-size:14px;color:#e8e8f0}
.countries-list{background:rgba(0,0,0,.2);border-radius:13px;padding:4px 8px;margin:-4px 0 10px;border:1px solid rgba(255,255,255,.04)}
.crow{display:flex;align-items:center;gap:10px;padding:8px 6px;border-bottom:1px solid rgba(255,255,255,.04)}
.crow:last-child{border-bottom:none}
.cname{flex:1;font-size:13px;color:#c8c8d8;font-weight:600}
.cnum{font-size:10px;color:#00d4ff;background:rgba(0,212,255,.12);padding:3px 9px;border-radius:20px;font-weight:700}
.cdel{width:28px;height:28px;background:rgba(233,69,96,.15);color:#ff6b8a;border-radius:8px;text-decoration:none;display:flex;align-items:center;justify-content:center;font-size:14px;flex-shrink:0}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:6px}
</style>
</head>
<body>

<div class="hdr">
<svg class="logo" viewBox="0 0 48 48">
<defs>
<linearGradient id="gA" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#7b2ff7"/><stop offset="100%" stop-color="#00d4ff"/></linearGradient>
<linearGradient id="gB" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#00d4ff"/><stop offset="100%" stop-color="#00b894"/></linearGradient>
</defs>
<rect x="6" y="4" width="36" height="40" rx="9" fill="url(#gA)" opacity="0.15"/>
<rect x="6" y="4" width="36" height="40" rx="9" fill="none" stroke="url(#gA)" stroke-width="1.8"/>
<rect x="14" y="14" width="20" height="3" rx="1.5" fill="url(#gB)"/>
<rect x="14" y="22" width="20" height="3" rx="1.5" fill="url(#gB)" opacity="0.7"/>
<rect x="14" y="30" width="20" height="3" rx="1.5" fill="url(#gB)" opacity="0.5"/>
<circle cx="38" cy="10" r="5" fill="#00d4a5"/>
<path d="M36 10 L37.5 11.5 L40 8.5" stroke="#fff" stroke-width="1.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
<div class="titles">
<h1>لوحة الأدمن</h1>
<div class="sub"><span class="dot"></span> متصل · الإصدار 1.0</div>
</div>
<a href="/admin/logout" class="logout">
<svg viewBox="0 0 24 24"><path d="M17 7l-1.41 1.41L18.17 11H8v2h10.17l-2.58 2.58L17 17l5-5zM4 5h8V3H4c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h8v-2H4V5z"/></svg>
خروج
</a>
</div>

<div class="stats">
<div class="stat"><b>{{ stats.platforms }}</b><span>منصات</span></div>
<div class="stat"><b>{{ stats.countries }}</b><span>دول</span></div>
<div class="stat"><b>{{ stats.numbers }}</b><span>أرقام</span></div>
<div class="stat ok"><b>OK</b><span>الحالة</span></div>
</div>

<div class="links">
<a href="/" class="lnk">
<svg viewBox="0 0 24 24" width="20" height="20" style="fill:#00d4ff;flex-shrink:0"><path d="M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z"/></svg>
<span>الموقع</span>
</a>
<a href="/admin/tickets" class="lnk">
<svg viewBox="0 0 24 24" width="20" height="20" style="fill:#00d4ff;flex-shrink:0"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm-2 12H6v-2h12v2zm0-3H6V9h12v2zm0-3H6V6h12v2z"/></svg>
<span>التذاكر</span>
</a>
<a href="/admin/codes" class="lnk">
<svg viewBox="0 0 24 24" width="20" height="20" style="fill:#00d4ff;flex-shrink:0"><path d="M20 8h-2.81c-.45-.78-1.07-1.45-1.82-1.96L17 4.41 15.59 3l-2.17 2.17C12.96 5.06 12.49 5 12 5s-.96.06-1.41.17L8.41 3 7 4.41l1.62 1.63C7.88 6.55 7.26 7.22 6.81 8H4v2h2.09c-.05.33-.09.66-.09 1v1H4v2h2v1c0 .34.04.67.09 1H4v2h2.81c1.04 1.79 2.97 3 5.19 3s4.15-1.21 5.19-3H20v-2h-2.09c.05-.33.09-.66.09-1v-1h2v-2h-2v-1c0-.34-.04-.67-.09-1H20V8zM12 16c-2.21 0-4-1.79-4-4s1.79-4 4-4 4 1.79 4 4-1.79 4-4 4zm0-6c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2z"/></svg>
<span>الأكواد</span>
</a>
<a href="/admin/stats" class="lnk">
<svg viewBox="0 0 24 24" width="20" height="20" style="fill:#00d4ff;flex-shrink:0"><path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zM9 17H7v-7h2v7zm4 0h-2V7h2v10zm4 0h-2v-4h2v4z"/></svg>
<span>الإحصائيات</span>
</a>
<a href="/admin/users" class="lnk">
<svg viewBox="0 0 24 24" width="20" height="20" style="fill:#00d4ff;flex-shrink:0"><path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z"/></svg>
<span>المستخدمون</span>
</a>
</div>
</div>

<div class="tabs">
<button class="tb active" onclick="showTab('add',event)">
<svg viewBox="0 0 24 24"><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/></svg>
<span>إضافة</span>
</button>
<button class="tb" onclick="showTab('manage',event)">
<svg viewBox="0 0 24 24"><path d="M3 17v2h6v-2H3zM3 5v2h10V5H3zm10 16v-2h8v-2h-8v-2h-2v6h2zM7 9v2H3v2h4v2h2V9H7zm14 4v-2H11v2h10zm-6-4h2V7h4V5h-4V3h-2v6z"/></svg>
<span>إدارة</span>
</button>
<button class="tb" onclick="showTab('settings',event)">
<svg viewBox="0 0 24 24"><path d="M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.09.63-.09.94s.02.64.07.94l-2.03 1.58c-.18.14-.23.41-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z"/></svg>
<span>إعدادات</span>
</button>
<button class="tb" onclick="showTab('telegram',event)">
<svg viewBox="0 0 24 24"><path d="M9.78 18.65l.28-4.23 7.68-6.92c.34-.31-.07-.46-.52-.19L7.74 13.3 3.64 12c-.88-.25-.89-.86.2-1.3l15.97-6.16c.73-.33 1.43.18 1.15 1.3l-2.72 12.81c-.19.91-.74 1.13-1.5.71L12.6 16.3l-1.99 1.93c-.23.23-.42.42-.83.42z"/></svg>
<span>تيليجرام</span>
</button>
<button class="tb" onclick="window.location.href='/admin/contests'">
<svg viewBox="0 0 24 24"><path d="M19 5h-2V3H7v2H5c-1.1 0-2 .9-2 2v1c0 2.55 1.92 4.63 4.39 4.94.63 1.5 1.98 2.63 3.61 2.96V19H7v2h10v-2h-4v-3.1c1.63-.33 2.98-1.46 3.61-2.96C19.08 12.63 21 10.55 21 8V7c0-1.1-.9-2-2-2z"/></svg>
<span>مسابقات</span>
</button>
<button class="tb" onclick="showTab('notice',event)">
<svg viewBox="0 0 24 24"><path d="M12 22c1.1 0 2-.9 2-2h-4c0 1.1.9 2 2 2zm6-6v-5c0-3.07-1.64-5.64-4.5-6.32V4c0-.83-.67-1.5-1.5-1.5s-1.5.67-1.5 1.5v.68C7.63 5.36 6 7.92 6 11v5l-2 2v1h16v-1l-2-2z"/></svg>
<span>إشعارات</span>
</button>
<button class="tb" onclick="showTab('maint',event)">
<svg viewBox="0 0 24 24"><path d="M22.7 19l-9.1-9.1c.9-2.3.4-5-1.5-6.9-2-2-5-2.4-7.4-1.3L9 6 6 9 1.6 4.7C.4 7.1.9 10.1 2.9 12.1c1.9 1.9 4.6 2.4 6.9 1.5l9.1 9.1c.4.4 1 .4 1.4 0l2.3-2.3c.5-.4.5-1.1.1-1.4z"/></svg>
<span>صيانة</span>
</button>

<button class="tb" onclick="showTab('preview',event)">
<svg viewBox="0 0 24 24"><path d="M12 4.5C7 4.5 2.73 7.61 1 12c1.73 4.39 6 7.5 11 7.5s9.27-3.11 11-7.5c-1.73-4.39-6-7.5-11-7.5zM12 17c-2.76 0-5-2.24-5-5s2.24-5 5-5 5 2.24 5 5-2.24 5-5 5zm0-8c-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3-1.34-3-3-3z"/></svg>
<span>معاينة</span>
</button>
<button class="tb" onclick="showTab('push',event)">
<svg viewBox="0 0 24 24"><path d="M12 22c1.1 0 2-.9 2-2h-4c0 1.1.9 2 2 2zm6-6v-5c0-3.07-1.64-5.64-4.5-6.32V4c0-.83-.67-1.5-1.5-1.5s-1.5.67-1.5 1.5v.68C7.63 5.36 6 7.92 6 11v5l-2 2v1h16v-1l-2-2z"/></svg>
<span>Push</span>
</button>
<button class="tb" onclick="showTab('chart',event)">
<svg viewBox="0 0 24 24"><path d="M9 17H7v-7h2v7zm4 0h-2V7h2v10zm4 0h-2v-4h2v4zm2 2H5V5h14v14zm0-16H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2z"/></svg>
<span>رسم بياني</span>
</button>
<button class="tb" onclick="showTab('background',event)">
<svg viewBox="0 0 24 24"><path d="M21 3H3c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h18c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm0 16H3V5h18v14zM5 15l3.5-4.5 2.5 3.01L14.5 9l4.5 6H5z"/></svg>
<span>الخلفية</span>
</button>
</div>

<div class="body">
<div class="pane active" id="pane-add">
<form method="POST" action="/admin/upload-file" enctype="multipart/form-data">
<div class="card"><h2>اختر المنصة</h2>
<select name="platform" required><option value="">-- اختر --</option>{% for p in platforms_list %}<option value="{{ p }}">{{ p }}</option>{% endfor %}</select></div>
<div class="card"><h2>ارفع ملف الأرقام</h2>
<label class="file-drop"><span id="fn">اضغط لاختيار ملف txt (اختياري)</span><input type="file" name="file" accept=".txt" onchange="document.getElementById('fn').textContent=this.files[0]?this.files[0].name:'اضغط لاختيار ملف txt (اختياري)'"></label>
<div class="info-box">كل رقم في سطر منفصل</div>
<button type="submit" class="btn btn-grad"><svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:#fff;vertical-align:middle;margin-left:6px"><path d="M5 20h14v-2H5v2zM19 9h-4V3H9v6H5l7 7 7-7z"/></svg> رفع وحفظ</button>
</div></form></div>

<div class="pane" id="pane-manage">
<div class="card"><h2>المنصات المضافة</h2>
{% if tree %}{% for platform, countries in tree.items() %}
<div class="prow">
  <div class="pn">
    <span class="pl-name">{{ platform }}</span>
    <span class="cnt">{{ countries|length }} دولة</span>
  </div>
  <a href="/admin/delete-platform/{{ platform }}" class="del" onclick="return confirm('حذف منصة {{ platform }} كاملة؟')" title="حذف المنصة">×</a>
</div>
{% if countries %}
<div class="countries-list">
  {% for country, nums in countries.items() %}
  <div class="crow">
    <span class="cname">{{ country }}</span>
    <span class="cnum">{{ nums|length }} رقم</span>
    <a href="/admin/delete-country/{{ platform }}/{{ country }}" class="cdel" onclick="return confirm('حذف دولة {{ country }} من {{ platform }}؟')">×</a>
  </div>
  {% endfor %}
</div>
{% endif %}
{% endfor %}{% else %}<div class="info-box">لا توجد منصات</div>{% endif %}
</div>
<div class="card"><h2>منطقة الخطر</h2>
<div class="info-box err">حذف كل الأرقام لا يمكن الرجوع عنه</div>
<a href="/admin/clear-numbers" class="btn btn-red" onclick="return confirm('مسح؟')"><svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:#fff;vertical-align:middle;margin-left:6px"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg> مسح كل الأرقام</a>
</div></div>

<div class="pane" id="pane-settings">
<form method="POST" action="/admin/save-settings">
<div class="card"><h2>معلومات الموقع</h2>
<label>الاسم بالعربية</label><input name="site_name" value="{{ s.site_name }}">
<label>الاسم بالإنجليزية</label><input name="site_name_en" value="{{ s.site_name_en }}"></div>
<div class="card"><h2>رابط الدعم</h2>
<label>الرابط</label><input name="support_url" value="{{ s.support_url }}"></div>
<div class="card"><h2>الألوان</h2>
<div class="grid2">
<div><label>الأساسي</label><input name="primary_color" type="color" value="{{ s.primary_color }}" style="height:50px"></div>
<div><label>الثانوي</label><input name="secondary_color" type="color" value="{{ s.secondary_color }}" style="height:50px"></div>
</div></div>
<button type="submit" class="btn btn-green"><svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:#fff;vertical-align:middle;margin-left:6px"><path d="M17 3H5c-1.11 0-2 .9-2 2v14c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V7l-4-4zm-5 16c-1.66 0-3-1.34-3-3s1.34-3 3-3 3 1.34 3 3-1.34 3-3 3zm3-10H5V5h10v4z"/></svg> حفظ الإعدادات</button>
</form></div>

<div class="pane" id="pane-telegram">
<div class="card"><h2>إعدادات البوت</h2>
<form method="POST" action="/admin/telegram/save">
<label>التوكن</label><input type="text" name="telegram_token" value="{{ s.telegram_token or '' }}" dir="ltr" style="font-family:monospace">
<label>Chat ID</label><input type="text" name="telegram_chat_id" value="{{ s.telegram_chat_id or '' }}" dir="ltr" style="font-family:monospace">
<button type="submit" class="btn btn-green"><svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:#fff;vertical-align:middle;margin-left:6px"><path d="M17 3H5c-1.11 0-2 .9-2 2v14c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V7l-4-4zm-5 16c-1.66 0-3-1.34-3-3s1.34-3 3-3 3 1.34 3 3-1.34 3-3 3zm3-10H5V5h10v4z"/></svg> حفظ</button>
</form></div>
<div class="card"><h2>اختبار الاتصال</h2>
<div class="grid2">
<button type="button" onclick="tgTest()" class="btn btn-green" style="margin-top:0"><svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:#fff;vertical-align:middle;margin-left:4px"><path d="M15.5 14h-.79l-.28-.27C15.41 12.59 16 11.11 16 9.5 16 5.91 13.09 3 9.5 3S3 5.91 3 9.5 5.91 16 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/></svg> اختبار</button>
<button type="button" onclick="tgSendTest()" class="btn btn-orange" style="margin-top:0"><svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:#fff;vertical-align:middle;margin-left:4px"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg> إرسال</button>
</div>
<div id="tgResult" style="margin-top:14px;padding:14px;border-radius:10px;background:rgba(0,0,0,.3);font-size:12px;display:none;direction:ltr;font-family:monospace;white-space:pre-line"></div></div>
<div class="card"><h2>حالة البوت</h2>
<div id="tgStatus" style="padding:14px;border-radius:10px;background:rgba(0,0,0,.3);font-size:13px;line-height:2">جاري التحميل...</div>
<button type="button" onclick="tgRefresh()" class="btn btn-grad"><svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:#fff;vertical-align:middle;margin-left:6px"><path d="M17.65 6.35A7.958 7.958 0 0012 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0112 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/></svg> تحديث</button></div>
<div class="card"><h2>حذف أكواد البوت</h2>
<a href="/admin/telegram/clear-codes" class="btn btn-red" onclick="return confirm('حذف؟')"><svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:#fff;vertical-align:middle;margin-left:6px"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg> حذف الأكواد</a></div>
</div>

<div class="pane" id="pane-notice">
<div class="card"><h2>إرسال إشعار</h2>
<form method="POST" action="/admin/notice/save">
<label>العنوان</label><input type="text" name="notice_title" value="{{ s.notice_title or '' }}" required>
<label>النص</label><textarea name="notice_body" rows="3" style="resize:vertical">{{ s.notice_body or '' }}</textarea>
<label>النوع</label><select name="notice_type">
<option value="info" {% if s.notice_type == 'info' %}selected{% endif %}>معلومات</option>
<option value="warning" {% if s.notice_type == 'warning' %}selected{% endif %}>تحذير</option>
<option value="success" {% if s.notice_type == 'success' %}selected{% endif %}>نجاح</option>
<option value="danger" {% if s.notice_type == 'danger' %}selected{% endif %}>خطأ</option>
</select>
<label>تاريخ الانتهاء</label><input type="date" name="notice_expire" value="{{ s.notice_expire or '' }}">
<button type="submit" class="btn btn-grad"><svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:#fff;vertical-align:middle;margin-left:6px"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg> إرسال</button>
</form></div>
<div class="card"><h2>حذف الإشعار الحالي</h2>
<a href="/admin/notice/delete" class="btn btn-red" onclick="return confirm('حذف؟')"><svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:#fff;vertical-align:middle;margin-left:6px"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg> حذف الإشعار</a></div>

<div class="card"><h2>وضع الصيانة</h2>
<div class="info-box err">تنبيه: عند التشغيل، الموقع يتجمد بالكامل.</div>
<form method="POST" action="/admin/maintenance/save">
<label>عنوان الصيانة</label><input type="text" name="maintenance_title" value="{{ s.maintenance_title or 'الموقع تحت الصيانة' }}">
<label>نص الصيانة</label><textarea name="maintenance_body" rows="3" style="resize:vertical">{{ s.maintenance_body or '' }}</textarea>
<label style="margin-top:16px;display:flex;align-items:center;gap:8px;cursor:pointer">
<input type="checkbox" name="maintenance_on" {% if s.maintenance_on %}checked{% endif %} style="width:auto;margin:0">
<b style="color:#e94560;font-size:14px">تفعيل الصيانة</b></label>
<button type="submit" class="btn btn-red"><svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:#fff;vertical-align:middle;margin-left:6px"><path d="M17 3H5c-1.11 0-2 .9-2 2v14c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V7l-4-4zm-5 16c-1.66 0-3-1.34-3-3s1.34-3 3-3 3 1.34 3 3-1.34 3-3 3zm3-10H5V5h10v4z"/></svg> حفظ</button>
</form></div>
<div class="card"><h2>الحالة الحالية</h2>
{% if s.maintenance_on %}
<div class="info-box err" style="text-align:center"><b>الموقع تحت الصيانة</b></div>
<a href="/admin/maintenance/off" class="btn btn-green" onclick="return confirm('رفع؟')"><svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:#fff;vertical-align:middle;margin-left:6px"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg> رفع الصيانة</a>
{% else %}
<div class="info-box ok" style="text-align:center"><b>الموقع يعمل</b></div>
{% endif %}
</div></div>

<!-- ═══ تبويب Push ═══ -->
<div class="pane" id="pane-push">
<div class="card">
<h2>
<svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:#00d4ff;vertical-align:middle;margin-left:6px"><path d="M12 22c1.1 0 2-.9 2-2h-4c0 1.1.9 2 2 2zm6-6v-5c0-3.07-1.64-5.64-4.5-6.32V4c0-.83-.67-1.5-1.5-1.5s-1.5.67-1.5 1.5v.68C7.63 5.36 6 7.92 6 11v5l-2 2v1h16v-1l-2-2z"/></svg>
حالة الإشعارات
</h2>
<div id="pushStatus" class="info-box" style="text-align:center">جاري التحميل...</div>
<button type="button" onclick="pushRefresh()" class="btn btn-grad" style="margin-top:14px">
<svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:#fff;vertical-align:middle;margin-left:6px"><path d="M17.65 6.35A7.958 7.958 0 0012 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0112 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/></svg>
تحديث
</button>
</div>

<div class="card">
<h2>
<svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:#00d4a5;vertical-align:middle;margin-left:6px"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
إرسال إشعار تجريبي
</h2>
<div class="info-box">يرسل لكل المشتركين الحاليين. لو ما وصلك، تأكد إنك فتحت الموقع وسمحت بالإشعارات.</div>
<button type="button" onclick="pushSendTest()" class="btn btn-green" style="margin-top:14px">
<svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:#fff;vertical-align:middle;margin-left:6px"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
إرسال اختبار
</button>
<div id="pushTestResult" style="margin-top:14px;padding:14px;border-radius:10px;background:rgba(0,0,0,.3);font-size:13px;display:none"></div>
</div>

<div class="card">
<h2>
<svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:#7b2ff7;vertical-align:middle;margin-left:6px"><path d="M20 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 4l-8 5-8-5V6l8 5 8-5v2z"/></svg>
إرسال إشعار مخصص
</h2>
<div class="info-box">اكتب ما تريد إرساله. يمكنك إضافة أيقونة SVG مخصصة.</div>

<label>العنوان</label>
<input type="text" id="cpTitle" placeholder="عنوان الإشعار" maxlength="100">

<label>النص</label>
<textarea id="cpBody" rows="3" placeholder="نص الإشعار..." style="resize:vertical" maxlength="300"></textarea>

<label>الرابط عند النقر (اختياري)</label>
<input type="text" id="cpUrl" placeholder="/" value="/">

<label>Tag — لمنع التكرار (اختياري)</label>
<input type="text" id="cpTag" placeholder="مثال: news" maxlength="50">

<label>اختر أيقونة جاهزة</label>
<div id="iconGallery" style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:12px;direction:ltr"></div>

<label>أو الصق كود SVG مخصص (اختياري)</label>
<textarea id="cpSvg" rows="4" placeholder="&lt;svg viewBox=&quot;0 0 24 24&quot;&gt;...&lt;/svg&gt;" style="resize:vertical;font-family:monospace;font-size:11px;direction:ltr;text-align:left"></textarea>

<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:8px">
<button type="button" onclick="cpPreviewSvg()" class="btn btn-orange" style="margin-top:0;font-size:13px;padding:10px">معاينة SVG</button>
<button type="button" onclick="cpClearSvg()" class="btn btn-red" style="margin-top:0;font-size:13px;padding:10px">مسح SVG</button>
</div>

<div id="cpSvgPreview" style="display:none;text-align:center;margin-top:12px;padding:10px;background:rgba(0,0,0,.3);border-radius:10px">
<img id="cpSvgImg" style="max-width:96px;max-height:96px;border-radius:8px" alt="">
</div>

<div id="cpResult" style="margin-top:14px;padding:14px;border-radius:10px;background:rgba(0,0,0,.3);font-size:13px;display:none"></div>

<button type="button" onclick="cpSend()" class="btn btn-grad" id="cpSendBtn" style="margin-top:14px">
<svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:#fff;vertical-align:middle;margin-left:6px"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
إرسال الآن
</button>
</div>

<div class="card">
<h2>
<svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:#ffcb6b;vertical-align:middle;margin-left:6px"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>
معلومات
</h2>
<div class="info-box">
- الإشعار يوصل حتى لو الموقع مسكر<br>
- يشتغل تلقائياً عند وصول كود جديد من تيليجرام<br>
- المستخدم لازم يفتح الموقع مرة وحدة ويسمح بالإشعارات<br>
- ما يشتغل إلا على HTTPS أو localhost
</div>
</div>
</div>

<!-- ═══ تبويب المعاينة ═══ -->
<div class="pane" id="pane-maint">
<style>
@keyframes mt-spin{from{transform:rotate(0)}to{transform:rotate(360deg)}}
@keyframes mt-spinr{from{transform:rotate(360deg)}to{transform:rotate(0)}}
@keyframes mt-glow{0%,100%{filter:drop-shadow(0 0 10px rgba(0,212,255,.5))}50%{filter:drop-shadow(0 0 25px rgba(123,47,247,.8))}}
@keyframes mt-pulse{0%,100%{opacity:.5}50%{opacity:1}}
.mh{background:linear-gradient(135deg,rgba(123,47,247,.15),rgba(0,212,255,.1));border:1px solid rgba(123,47,247,.3);border-radius:22px;padding:24px;text-align:center;margin-bottom:18px}
.mh-icon{width:120px;height:120px;margin:0 auto 14px}
.mh-icon svg{width:100%;height:100%;animation:mt-glow 2s ease-in-out infinite}
.mg1{transform-origin:60px 60px;animation:mt-spin 8s linear infinite}
.mg2{transform-origin:60px 60px;animation:mt-spinr 6s linear infinite}
.mw{transform-origin:60px 60px;animation:mt-pulse 2s ease-in-out infinite}
.mh-title{font-size:17px;font-weight:900;margin-bottom:6px}
.mh-title.on{color:#ff6b8a}
.mh-title.off{color:#00d4a5}
.mh-sub{font-size:12px;color:#8e8eab}
.mh-badge{display:inline-block;padding:6px 16px;border-radius:20px;font-size:11px;font-weight:900;margin-top:12px;letter-spacing:.4px}
.mh-badge.on{background:rgba(233,69,96,.15);border:1px solid rgba(233,69,96,.4);color:#ff6b8a}
.mh-badge.off{background:rgba(0,212,165,.15);border:1px solid rgba(0,212,165,.4);color:#00d4a5}
</style>

<div class="mh">
<div class="mh-icon">
<svg viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg">
<defs>
<linearGradient id="mgA" x1="0%" y1="0%" x2="100%" y2="100%">
<stop offset="0%" stop-color="#7b2ff7"/>
<stop offset="100%" stop-color="#00d4ff"/>
</linearGradient>
<linearGradient id="mgB" x1="0%" y1="0%" x2="100%" y2="100%">
<stop offset="0%" stop-color="#00d4ff"/>
<stop offset="100%" stop-color="#00b894"/>
</linearGradient>
</defs>
<g class="mg1">
<circle cx="60" cy="60" r="32" fill="none" stroke="url(#mgA)" stroke-width="3.5"/>
<circle cx="60" cy="60" r="16" fill="none" stroke="url(#mgA)" stroke-width="2.5"/>
<g fill="url(#mgA)">
<rect x="55" y="22" width="10" height="12" rx="2"/>
<rect x="55" y="86" width="10" height="12" rx="2"/>
<rect x="22" y="55" width="12" height="10" rx="2"/>
<rect x="86" y="55" width="12" height="10" rx="2"/>
<rect x="33" y="33" width="10" height="10" rx="2" transform="rotate(-45 38 38)"/>
<rect x="77" y="33" width="10" height="10" rx="2" transform="rotate(45 82 38)"/>
<rect x="33" y="77" width="10" height="10" rx="2" transform="rotate(45 38 82)"/>
<rect x="77" y="77" width="10" height="10" rx="2" transform="rotate(-45 82 82)"/>
</g>
</g>
<g class="mg2">
<circle cx="60" cy="60" r="22" fill="none" stroke="url(#mgB)" stroke-width="2" opacity="0.55"/>
<g fill="url(#mgB)" opacity="0.65">
<rect x="58" y="36" width="4" height="8" rx="1"/>
<rect x="58" y="76" width="4" height="8" rx="1"/>
<rect x="36" y="58" width="8" height="4" rx="1"/>
<rect x="76" y="58" width="8" height="4" rx="1"/>
</g>
</g>
<g class="mw">
<path d="M 60 60 L 50 50 L 53 47 L 63 57 L 67 53 L 57 43 L 60 40 L 70 50
         C 73 47 73 42 70 39 C 67 36 62 36 59 39
         L 40 20 L 37 23 L 56 42
         C 59 45 62 45 65 42
         L 68 45 L 63 50
         C 66 53 69 56 72 53 L 75 56 Z"
      fill="url(#mgA)" stroke="#00d4ff" stroke-width="0.8" stroke-linejoin="round"/>
</g>
<circle cx="28" cy="28" r="2" fill="#00d4ff">
<animate attributeName="opacity" values="0.3;1;0.3" dur="2s" repeatCount="indefinite"/>
</circle>
<circle cx="92" cy="92" r="2" fill="#7b2ff7">
<animate attributeName="opacity" values="0.3;1;0.3" dur="2.5s" repeatCount="indefinite"/>
</circle>
</svg>
</div>
{% if s.maintenance_on %}
<div class="mh-title on">الموقع تحت الصيانة</div>
<div class="mh-sub">الزوار لا يستطيعون الوصول للموقع حالياً</div>
<div class="mh-badge on">الصيانة مُفعَّلة</div>
{% else %}
<div class="mh-title off">الموقع يعمل بشكل طبيعي</div>
<div class="mh-sub">كل الزوار يستطيعون الوصول للموقع</div>
<div class="mh-badge off">الموقع يعمل</div>
{% endif %}
</div>

<form method="POST" action="/admin/maintenance/save">
<div class="card">
<h2><svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:#00d4ff;vertical-align:middle;margin-left:6px"><path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.39-.39-1.02-.39-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/></svg> تفاصيل الصيانة</h2>
<label>عنوان الصيانة</label>
<input type="text" name="maintenance_title" value="{{ s.maintenance_title or 'الموقع تحت الصيانة' }}" maxlength="100">
<label>نص الصيانة</label>
<textarea name="maintenance_body" rows="3" style="resize:vertical" maxlength="500">{{ s.maintenance_body or '' }}</textarea>

<label>الأيقونة</label>
<div style="display:grid;grid-template-columns:repeat(5,1fr);gap:6px;margin-top:6px">
<label style="cursor:pointer;position:relative"><input type="radio" name="maint_icon" value="engineer" {% if s.maint_icon == 'engineer' or not s.maint_icon %}checked{% endif %} style="position:absolute;opacity:0"><div class="iopt" style="padding:10px 4px;border:2px solid rgba(255,255,255,.1);border-radius:10px;text-align:center;background:rgba(0,0,0,.3);font-size:10px;color:#8e8eab"><div style="font-size:22px;margin-bottom:2px">🏗️</div>مهندس</div></label>
<label style="cursor:pointer;position:relative"><input type="radio" name="maint_icon" value="coder" {% if s.maint_icon == 'coder' %}checked{% endif %} style="position:absolute;opacity:0"><div class="iopt" style="padding:10px 4px;border:2px solid rgba(255,255,255,.1);border-radius:10px;text-align:center;background:rgba(0,0,0,.3);font-size:10px;color:#8e8eab"><div style="font-size:22px;margin-bottom:2px">💻</div>مبرمج</div></label>
<label style="cursor:pointer;position:relative"><input type="radio" name="maint_icon" value="robot" {% if s.maint_icon == 'robot' %}checked{% endif %} style="position:absolute;opacity:0"><div class="iopt" style="padding:10px 4px;border:2px solid rgba(255,255,255,.1);border-radius:10px;text-align:center;background:rgba(0,0,0,.3);font-size:10px;color:#8e8eab"><div style="font-size:22px;margin-bottom:2px">🤖</div>روبوت</div></label>
<label style="cursor:pointer;position:relative"><input type="radio" name="maint_icon" value="gear" {% if s.maint_icon == 'gear' %}checked{% endif %} style="position:absolute;opacity:0"><div class="iopt" style="padding:10px 4px;border:2px solid rgba(255,255,255,.1);border-radius:10px;text-align:center;background:rgba(0,0,0,.3);font-size:10px;color:#8e8eab"><div style="font-size:22px;margin-bottom:2px">⚙️</div>ترس</div></label>
<label style="cursor:pointer;position:relative"><input type="radio" name="maint_icon" value="sad" {% if s.maint_icon == 'sad' %}checked{% endif %} style="position:absolute;opacity:0"><div class="iopt" style="padding:10px 4px;border:2px solid rgba(255,255,255,.1);border-radius:10px;text-align:center;background:rgba(0,0,0,.3);font-size:10px;color:#8e8eab"><div style="font-size:22px;margin-bottom:2px">😔</div>حزين</div></label>
</div>

<label>اللون</label>
<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:6px">
<label style="cursor:pointer;position:relative"><input type="radio" name="maint_color" value="gold" {% if s.maint_color == 'gold' or not s.maint_color %}checked{% endif %} style="position:absolute;opacity:0"><div class="copt" style="height:40px;border-radius:10px;background:linear-gradient(135deg,#fbbf24,#f59e0b);border:3px solid transparent"></div></label>
<label style="cursor:pointer;position:relative"><input type="radio" name="maint_color" value="purple" {% if s.maint_color == 'purple' %}checked{% endif %} style="position:absolute;opacity:0"><div class="copt" style="height:40px;border-radius:10px;background:linear-gradient(135deg,#c8a2ff,#7b2ff7);border:3px solid transparent"></div></label>
<label style="cursor:pointer;position:relative"><input type="radio" name="maint_color" value="cyan" {% if s.maint_color == 'cyan' %}checked{% endif %} style="position:absolute;opacity:0"><div class="copt" style="height:40px;border-radius:10px;background:linear-gradient(135deg,#00d4ff,#0099cc);border:3px solid transparent"></div></label>
<label style="cursor:pointer;position:relative"><input type="radio" name="maint_color" value="green" {% if s.maint_color == 'green' %}checked{% endif %} style="position:absolute;opacity:0"><div class="copt" style="height:40px;border-radius:10px;background:linear-gradient(135deg,#00d4a5,#00b894);border:3px solid transparent"></div></label>
</div>

<style>
.iopt,.copt{transition:all .2s}
label input:checked + .iopt{border-color:#7b2ff7 !important;box-shadow:0 0 20px rgba(123,47,247,.4);background:rgba(123,47,247,.15) !important}
label input:checked + .copt{border-color:#fff !important;box-shadow:0 0 20px rgba(255,255,255,.3);transform:scale(1.05)}
</style>
</div>

<div class="card" style="padding:14px 18px">
<label style="display:flex;align-items:center;gap:12px;cursor:pointer;margin:0;padding:12px;background:rgba(233,69,96,.08);border:1.5px solid rgba(233,69,96,.3);border-radius:14px">
<input type="checkbox" name="maintenance_on" {% if s.maintenance_on %}checked{% endif %} style="width:auto;margin:0;transform:scale(1.4)">
<div style="flex:1">
<b style="color:#e94560;font-size:14px;display:block">تفعيل الصيانة</b>
<span style="font-size:11px;color:#8e8eab">سيتم تجميد الموقع بالكامل للزوار</span>
</div>
</label>
<button type="submit" class="btn btn-red" style="margin-top:14px">
<svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:#fff;vertical-align:middle;margin-left:6px"><path d="M17 3H5c-1.11 0-2 .9-2 2v14c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V7l-4-4z"/></svg>
حفظ
</button>
</div>
</form>

{% if s.maintenance_on %}
<div class="card" style="padding:14px">
<a href="/admin/maintenance/off" class="btn btn-green" style="margin-top:0" onclick="return confirm('رفع الصيانة؟')">
<svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:#fff;vertical-align:middle;margin-left:6px"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>
رفع الصيانة الآن
</a>
</div>
{% endif %}

</div>

<div class="pane" id="pane-preview">
<div class="card"><h2>معاينة الموقع</h2>
<div class="info-box">هنا يظهر الموقع الفعلي داخل إطار. اضغط "فتح كامل" لتصفح من نافذة جديدة.</div>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:14px">
<a href="/" target="_blank" class="btn btn-grad" style="margin-top:0"><svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:#fff;vertical-align:middle;margin-left:6px"><path d="M19 19H5V5h7V3H5c-1.11 0-2 .9-2 2v14c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2v-7h-2v7zM14 3v2h3.59l-9.83 9.83 1.41 1.41L19 6.41V10h2V3h-7z"/></svg> فتح كامل</a>
<button class="btn btn-orange" onclick="refreshPreview()" style="margin-top:0"><svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:#fff;vertical-align:middle;margin-left:6px"><path d="M17.65 6.35A7.958 7.958 0 0012 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0112 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/></svg> تحديث</button>
</div>
<div style="margin-top:14px;border:2px solid rgba(0,212,255,.3);border-radius:14px;overflow:hidden;background:#000">
<iframe id="previewFrame" src="/" style="width:100%;height:500px;border:none;display:block"></iframe>
</div>
</div>
</div>

<!-- ═══ تبويب الرسم البياني ═══ -->
<div class="pane" id="pane-chart">
<div class="card"><h2>آخر 7 أيام — الزيارات</h2>
{% if chart_data %}
<svg viewBox="0 0 400 200" style="width:100%;height:auto;background:rgba(0,0,0,.2);border-radius:12px;padding:10px" preserveAspectRatio="none">
<defs>
<linearGradient id="chartGrad" x1="0%" y1="0%" x2="0%" y2="100%">
<stop offset="0%" stop-color="#00d4ff" stop-opacity="0.7"/>
<stop offset="100%" stop-color="#7b2ff7" stop-opacity="0.05"/>
</linearGradient>
</defs>
<!-- خطوط الشبكة -->
<line x1="20" y1="40" x2="380" y2="40" stroke="rgba(255,255,255,.06)" stroke-width="1"/>
<line x1="20" y1="80" x2="380" y2="80" stroke="rgba(255,255,255,.06)" stroke-width="1"/>
<line x1="20" y1="120" x2="380" y2="120" stroke="rgba(255,255,255,.06)" stroke-width="1"/>
<line x1="20" y1="160" x2="380" y2="160" stroke="rgba(255,255,255,.06)" stroke-width="1"/>
<!-- المنطقة الملونة -->
<path d="{{ chart_area }}" fill="url(#chartGrad)"/>
<!-- الخط -->
<path d="{{ chart_path }}" fill="none" stroke="#00d4ff" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>
<!-- النقاط -->
{% for p in chart_points %}
<circle cx="{{ p.x }}" cy="{{ p.y }}" r="4" fill="#00d4ff" stroke="#fff" stroke-width="1.5">
<title>{{ p.value }} زيارة</title>
</circle>
{% endfor %}
</svg>
<div style="display:flex;justify-content:space-between;margin-top:10px;font-size:10px;color:#8e8eab;direction:ltr;padding:0 8px">
{% for d in chart_data %}<span>{{ d.label }}</span>{% endfor %}
</div>
{% else %}
<div style="padding:40px;text-align:center;color:#8e8eab;font-size:13px">لا توجد بيانات</div>
{% endif %}
</div>
<div class="card"><h2>ملخص</h2>
<div class="grid2">
<div class="info-box ok" style="text-align:center;margin-top:0"><b id="chartTotal" style="font-size:20px">0</b><br><span style="font-size:11px">إجمالي الزيارات</span></div>
<div class="info-box" style="text-align:center;margin-top:0"><b id="chartToday" style="font-size:20px">0</b><br><span style="font-size:11px">زيارات اليوم</span></div>
</div>
</div>
</div>

<!-- ═══ تبويب الخلفية ═══ -->
<div class="pane" id="pane-background">
<div class="card">
<h2>
<svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:#00d4ff;vertical-align:middle;margin-left:6px"><path d="M21 3H3c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h18c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm0 16H3V5h18v14zM5 15l3.5-4.5 2.5 3.01L14.5 9l4.5 6H5z"/></svg>
إعدادات الخلفية
</h2>

<div class="info-box">تتحكم بالخلفية المتحركة للموقع — تشغيل/إيقاف + اختيار النوع + الاسم.</div>

<form method="POST" action="/admin/background/save">

<label style="display:flex;align-items:center;gap:10px;cursor:pointer;background:rgba(0,212,255,.08);padding:14px;border-radius:12px;margin-top:14px">
<input type="checkbox" name="background_on" {% if s.background_on %}checked{% endif %} style="width:auto;margin:0;transform:scale(1.5)">
<b style="color:#00d4ff;font-size:14px">✨ تشغيل الخلفية</b>
</label>

<label>نوع الخلفية</label>
<select name="background_style" style="font-family:inherit">
<option value="code" {% if s.background_style == 'code' %}selected{% endif %}>💻 مبرمجين (أكواد)</option>
<option value="platforms" {% if s.background_style == 'platforms' %}selected{% endif %}>📱 منصات طايرة</option>
<option value="custom" {% if s.background_style == 'custom' %}selected{% endif %}>🎨 SVG مخصص فقط</option>
<option value="off" {% if s.background_style == 'off' %}selected{% endif %}>بدون خلفية</option>
</select>

<label>الاسم في المنتصف</label>
<input type="text" name="background_name" value="{{ s.background_name or 'المطري OTP' }}" placeholder="المطري OTP" maxlength="30">

<label>كود SVG مخصص (اختياري)</label>
<textarea name="background_custom_svg" rows="6" style="font-family:monospace;font-size:12px;direction:ltr;text-align:left;resize:vertical;min-height:120px" placeholder="<svg viewBox=&quot;0 0 24 24&quot;>...</svg>">{{ s.background_custom_svg or '' }}</textarea>
<div class="info-box">الصق كود SVG هنا — سيظهر في خلفية الموقع. اتركه فاضي للخلفية الافتراضية.</div>

<button type="submit" class="btn btn-green">
<svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:#fff;vertical-align:middle;margin-left:6px"><path d="M17 3H5c-1.11 0-2 .9-2 2v14c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V7l-4-4zm-5 16c-1.66 0-3-1.34-3-3s1.34-3 3-3 3 1.34 3 3-1.34 3-3 3zm3-10H5V5h10v4z"/></svg>
حفظ
</button>
</form>
</div>

<div class="card">
<h2>
<svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:#ffcb6b;vertical-align:middle;margin-left:6px"><path d="M12 4.5C7 4.5 2.73 7.61 1 12c1.73 4.39 6 7.5 11 7.5s9.27-3.11 11-7.5c-1.73-4.39-6-7.5-11-7.5zM12 17c-2.76 0-5-2.24-5-5s2.24-5 5-5 5 2.24 5 5-2.24 5-5 5zm0-8c-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3-1.34-3-3-3z"/></svg>
معاينة
</h2>
<a href="/" target="_blank" class="btn btn-grad">
<svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:#fff;vertical-align:middle;margin-left:6px"><path d="M19 19H5V5h7V3H5c-1.11 0-2 .9-2 2v14c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2v-7h-2v7zM14 3v2h3.59l-9.83 9.83 1.41 1.41L19 6.41V10h2V3h-7z"/></svg>
فتح الموقع
</a>
</div>
</div>

</div>

<script>
function showTab(n,e){
  document.querySelectorAll(".tb").forEach(function(t){t.classList.remove("active")});
  document.querySelectorAll(".pane").forEach(function(t){t.classList.remove("active")});
  e.target.classList.add("active");
  var pane = document.getElementById("pane-"+n);
  if(pane) pane.classList.add("active");
  if(n==="telegram") tgRefresh();
  if(n==="chart"){ setTimeout(loadChart, 100); setTimeout(loadChart, 500); }
  if(n==="preview" && typeof refreshPreview === "function") setTimeout(refreshPreview, 200);
}
function tgTest(){
  var b=document.getElementById("tgResult");
  b.style.display="block";b.style.color="#00d4ff";b.textContent="جاري الاختبار...";
  fetch("/admin/telegram/test").then(function(r){return r.json()}).then(function(d){
    if(d.ok){b.style.color="#00d4a5";b.textContent="نجح: "+(d.title||"")}
    else{b.style.color="#ff6b8a";b.textContent="فشل: "+(d.error||"")}
  }).catch(function(e){b.style.color="#ff6b8a";b.textContent="خطأ: "+e.message});
}
function tgSendTest(){
  var b=document.getElementById("tgResult");
  b.style.display="block";b.style.color="#FFC107";b.textContent="جاري الإرسال...";
  fetch("/admin/telegram/send-test").then(function(r){return r.json()}).then(function(d){
    if(d.ok){b.style.color="#00d4a5";b.textContent="تم الإرسال"}
    else{b.style.color="#ff6b8a";b.textContent="فشل: "+(d.error||"")}
  }).catch(function(e){b.style.color="#ff6b8a";b.textContent="خطأ: "+e.message});
}
function tgRefresh(){
  var b=document.getElementById("tgStatus");if(!b)return;
  b.innerHTML="جاري التحديث...";
  fetch("/admin/telegram/status").then(function(r){return r.json()}).then(function(d){
    var h="";
    h+=d.running?"<b style='color:#00d4a5'>البوت شغال</b><br>":"<b style='color:#ff6b8a'>البوت متوقف</b><br>";
    h+=d.has_token?"التوكن محفوظ<br>":"التوكن ناقص<br>";
    h+=d.has_chat_id?"Chat ID محفوظ<br>":"Chat ID ناقص<br>";
    h+="عدد الأكواد: <b>"+d.codes_count+"</b>";
    b.innerHTML=h;
  }).catch(function(e){b.innerHTML="خطأ: "+e.message});
}

// ═══ ADMIN PUSH v4 ═══
window._adminPushFixed = true;
(function(){
    function pushRefresh(){
        var b = document.getElementById("pushStatus");
        if(!b) return;
        b.innerHTML = "جاري التحميل...";
        fetch("/api/push/stats")
            .then(function(r){ return r.json(); })
            .then(function(d){
                var h = "";
                if(!d.ready){
                    h = "<b style=\'color:#ff6b8a\'>pywebpush غير مثبت</b><br><br>ثبت بـ:<br><code style=\'direction:ltr;display:inline-block;margin-top:6px\'>pip install pywebpush</code>";
                } else {
                    h = "<b style=\'color:#00d4a5\'>النظام شغال</b><br>";
                    h += "عدد المشتركين: <b style=\'color:#00d4ff\'>" + d.subs + "</b><br>";
                    h += "VAPID: <b style=\'color:#00d4a5\'>" + (d.has_vapid ? "موجود" : "ناقص") + "</b>";
                }
                b.innerHTML = h;
            })
            .catch(function(e){
                b.innerHTML = "<b style=\'color:#ff6b8a\'>خطأ: " + e.message + "</b>";
            });
    }

    function pushSendTest(){
        var b = document.getElementById("pushTestResult");
        if(!b) return;
        b.style.display = "block";
        b.style.color = "#ffcb6b";
        b.textContent = "جاري الإرسال...";
        fetch("/api/push/test")
            .then(function(r){ return r.json(); })
            .then(function(d){
                if(d.ok){
                    b.style.color = "#00d4a5";
                    b.textContent = "تم إرسال " + d.sent + " إشعار (من " + d.total + " مشترك)";
                } else {
                    b.style.color = "#ff6b8a";
                    b.textContent = "فشل: " + (d.error || "");
                }
            })
            .catch(function(e){
                b.style.color = "#ff6b8a";
                b.textContent = "خطأ: " + e.message;
            });
    }

    // اربط الأزرار عند التحميل
    function bindButtons(){
        // زر تحديث
        var btns = document.querySelectorAll("button");
        for(var i = 0; i < btns.length; i++){
            var b = btns[i];
            var oc = b.getAttribute("onclick") || "";
            if(oc.indexOf("pushRefresh") > -1){
                b.removeAttribute("onclick");
                b.addEventListener("click", function(e){
                    e.preventDefault();
                    pushRefresh();
                });
            }
            if(oc.indexOf("pushSendTest") > -1){
                b.removeAttribute("onclick");
                b.addEventListener("click", function(e){
                    e.preventDefault();
                    pushSendTest();
                });
            }
        }
        // شغّل pushRefresh عند فتح tab Push
        var tabs = document.querySelectorAll(".tb");
        for(var j = 0; j < tabs.length; j++){
            var t = tabs[j];
            if(t.textContent.indexOf("Push") > -1 || t.innerHTML.indexOf("Push") > -1){
                t.addEventListener("click", function(){
                    setTimeout(pushRefresh, 300);
                });
            }
        }
        // لو التبويب مفتوح حالياً → شغّله
        setTimeout(function(){
            var pane = document.getElementById("pane-push");
            if(pane && pane.classList.contains("active")){
                pushRefresh();
            }
        }, 500);
    }

    if(document.readyState === "loading"){
        document.addEventListener("DOMContentLoaded", bindButtons);
    } else {
        bindButtons();
    }
})();


// ═══ PUSH CUSTOM v1 ═══
window._pushCustomUI = true;

function cpPreviewSvg(){
    var svg = document.getElementById("cpSvg").value.trim();
    var box = document.getElementById("cpSvgPreview");
    var img = document.getElementById("cpSvgImg");
    if(!svg){
        box.style.display = "none";
        return;
    }
    fetch("/api/push/preview-svg", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({svg: svg})
    })
    .then(function(r){ return r.json(); })
    .then(function(d){
        if(d.ok){
            img.src = d.data_url;
            box.style.display = "block";
        } else {
            alert("فشل المعاينة: " + (d.error || ""));
        }
    })
    .catch(function(e){
        alert("خطأ: " + e.message);
    });
}

function cpClearSvg(){
    document.getElementById("cpSvg").value = "";
    document.getElementById("cpSvgPreview").style.display = "none";
}

function cpSend(){
    var title = document.getElementById("cpTitle").value.trim();
    var body = document.getElementById("cpBody").value.trim();
    var url = document.getElementById("cpUrl").value.trim();
    var tag = document.getElementById("cpTag").value.trim();
    var svg = document.getElementById("cpSvg").value.trim();

    if(!title && !body){
        alert("اكتب عنوان أو نص على الأقل");
        return;
    }

    var b = document.getElementById("cpResult");
    var btn = document.getElementById("cpSendBtn");
    b.style.display = "block";
    b.style.color = "#ffcb6b";
    b.textContent = "جاري الإرسال...";
    btn.disabled = true;

    fetch("/api/push/send-custom", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
            title: title,
            body: body,
            url: url || "/",
            tag: tag,
            icon_svg: svg
        })
    })
    .then(function(r){ return r.json(); })
    .then(function(d){
        if(d.ok){
            b.style.color = "#00d4a5";
            b.textContent = "تم إرسال " + d.sent + " إشعار (من " + d.total + " مشترك)";
        } else {
            b.style.color = "#ff6b8a";
            b.textContent = "فشل: " + (d.error || "");
        }
        btn.disabled = false;
    })
    .catch(function(e){
        b.style.color = "#ff6b8a";
        b.textContent = "خطأ: " + e.message;
        btn.disabled = false;
    });
}


// ═══ ICON GALLERY v1 ═══
window._iconGalleryV1 = true;

// ═══ الأيقونات الجاهزة (SVG) ═══
var ICONS = [
    {
        id: "otp",
        label: "OTP",
        svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 192 192"><defs><linearGradient id="og1" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#7b2ff7"/><stop offset="100%" stop-color="#00d4ff"/></linearGradient></defs><rect width="192" height="192" rx="48" fill="url(#og1)"/><rect x="48" y="56" width="96" height="80" rx="12" fill="#fff"/><path d="M48 68 L96 100 L144 68" stroke="#7b2ff7" stroke-width="6" fill="none" stroke-linecap="round" stroke-linejoin="round"/><text x="96" y="124" font-family="Arial" font-size="26" font-weight="900" fill="#7b2ff7" text-anchor="middle">OTP</text></svg>'
    },
    {
        id: "msg",
        label: "رسالة",
        svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 192 192"><defs><linearGradient id="og2" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#00b894"/><stop offset="100%" stop-color="#00d4ff"/></linearGradient></defs><rect width="192" height="192" rx="48" fill="url(#og2)"/><path d="M40 60 Q40 44 56 44 L136 44 Q152 44 152 60 L152 120 Q152 136 136 136 L88 136 L56 160 L56 136 Q40 136 40 120 Z" fill="#fff"/><circle cx="72" cy="90" r="8" fill="#00b894"/><circle cx="96" cy="90" r="8" fill="#00b894"/><circle cx="120" cy="90" r="8" fill="#00b894"/></svg>'
    },
    {
        id: "lock",
        label: "قفل",
        svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 192 192"><defs><linearGradient id="og3" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#e94560"/><stop offset="100%" stop-color="#f39c12"/></linearGradient></defs><rect width="192" height="192" rx="48" fill="url(#og3)"/><path d="M64 84 L64 64 Q64 40 96 40 Q128 40 128 64 L128 84" stroke="#fff" stroke-width="12" fill="none" stroke-linecap="round"/><rect x="52" y="84" width="88" height="72" rx="10" fill="#fff"/><circle cx="96" cy="118" r="8" fill="#e94560"/><rect x="92" y="118" width="8" height="22" fill="#e94560" rx="2"/></svg>'
    },
    {
        id: "bell",
        label: "جرس",
        svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 192 192"><defs><linearGradient id="og4" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#f39c12"/><stop offset="100%" stop-color="#feca57"/></linearGradient></defs><rect width="192" height="192" rx="48" fill="url(#og4)"/><path d="M96 40 Q60 40 60 84 L60 120 L48 132 L144 132 L132 120 L132 84 Q132 40 96 40 Z" fill="#fff"/><circle cx="96" cy="144" r="12" fill="#fff"/><circle cx="130" cy="60" r="10" fill="#e94560"/></svg>'
    },
    {
        id: "shield",
        label: "حماية",
        svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 192 192"><defs><linearGradient id="og5" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#0ea5e9"/><stop offset="100%" stop-color="#00d4a5"/></linearGradient></defs><rect width="192" height="192" rx="48" fill="url(#og5)"/><path d="M96 36 L48 56 L48 104 Q48 144 96 164 Q144 144 144 104 L144 56 Z" fill="#fff"/><path d="M76 100 L92 116 L120 84" stroke="#0ea5e9" stroke-width="12" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>'
    },
    {
        id: "check",
        label: "صح",
        svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 192 192"><defs><linearGradient id="og6" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#00b894"/><stop offset="100%" stop-color="#00d4a5"/></linearGradient></defs><rect width="192" height="192" rx="48" fill="url(#og6)"/><circle cx="96" cy="96" r="56" fill="#fff"/><path d="M68 96 L88 116 L124 76" stroke="#00b894" stroke-width="14" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>'
    },
    {
        id: "phone",
        label: "هاتف",
        svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 192 192"><defs><linearGradient id="og7" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#7b2ff7"/><stop offset="100%" stop-color="#e94560"/></linearGradient></defs><rect width="192" height="192" rx="48" fill="url(#og7)"/><rect x="60" y="32" width="72" height="128" rx="12" fill="#fff"/><rect x="68" y="44" width="56" height="100" rx="6" fill="#7b2ff7"/><circle cx="96" cy="152" r="5" fill="#7b2ff7"/><text x="96" y="104" font-family="Arial" font-size="40" font-weight="900" fill="#fff" text-anchor="middle">123</text></svg>'
    },
    {
        id: "star",
        label: "نجمة",
        svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 192 192"><defs><linearGradient id="og8" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#7b2ff7"/><stop offset="100%" stop-color="#00d4ff"/></linearGradient></defs><rect width="192" height="192" rx="48" fill="url(#og8)"/><path d="M96 40 L112 84 L160 84 L122 112 L136 156 L96 128 L56 156 L70 112 L32 84 L80 84 Z" fill="#fff"/></svg>'
    },
    {
        id: "whatsapp",
        label: "واتساب",
        svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 192 192"><rect width="192" height="192" rx="48" fill="#25D366"/><path fill="#fff" d="M96 40 Q64 40 44 60 Q24 80 24 108 Q24 124 34 138 L24 168 L56 158 Q72 166 96 166 Q136 166 156 138 Q176 110 168 80 Q160 52 128 42 Q112 38 96 40 Z M96 156 Q76 156 64 150 L56 146 L38 152 L44 136 L40 128 Q32 116 32 108 Q32 86 48 70 Q64 54 96 54 Q120 54 140 68 Q156 82 156 104 Q156 128 140 142 Q124 156 96 156 Z"/><path fill="#fff" d="M78 82 Q70 80 68 88 Q66 98 78 114 Q88 126 100 130 Q112 132 116 124 Q118 116 110 114 Q102 110 102 118 Q90 112 82 100 Q90 98 88 90 Q86 84 78 82 Z"/></svg>'
    },
    {
        id: "telegram",
        label: "تيليجرام",
        svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 192 192"><rect width="192" height="192" rx="48" fill="#0088cc"/><path fill="#fff" d="M148 56 L44 96 L76 108 L88 144 L104 116 L136 136 Z M136 136 L88 108 L144 68 Z"/></svg>'
    },
    {
        id: "fire",
        label: "شعلة",
        svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 192 192"><defs><linearGradient id="og11" x1="0%" y1="0%" x2="0%" y2="100%"><stop offset="0%" stop-color="#feca57"/><stop offset="100%" stop-color="#e94560"/></linearGradient></defs><rect width="192" height="192" rx="48" fill="url(#og11)"/><path d="M96 32 Q72 60 72 88 Q72 104 60 120 Q56 128 60 140 Q68 160 96 160 Q124 160 132 140 Q136 128 132 120 Q120 104 120 88 Q120 60 96 32 Z M96 148 Q84 148 78 138 Q74 130 82 120 Q90 112 92 100 Q94 90 96 84 Q98 90 100 100 Q102 112 110 120 Q118 130 114 138 Q108 148 96 148 Z" fill="#fff"/></svg>'
    },
    {
        id: "alert",
        label: "تنبيه",
        svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 192 192"><defs><linearGradient id="og12" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#e94560"/><stop offset="100%" stop-color="#c62a47"/></linearGradient></defs><rect width="192" height="192" rx="48" fill="url(#og12)"/><path d="M96 40 L168 160 L24 160 Z" fill="#fff"/><rect x="88" y="80" width="16" height="44" rx="4" fill="#e94560"/><circle cx="96" cy="140" r="8" fill="#e94560"/></svg>'
    }
];

// ═══ بناء المعرض ═══
function buildIconGallery(){
    var g = document.getElementById("iconGallery");
    if(!g) return;
    g.innerHTML = "";
    ICONS.forEach(function(ic){
        var btn = document.createElement("button");
        btn.type = "button";
        btn.title = ic.label;
        btn.style.cssText = "padding:4px;border:2px solid rgba(123,47,247,.2);border-radius:12px;background:rgba(0,0,0,.3);cursor:pointer;transition:all .2s;aspect-ratio:1;display:flex;align-items:center;justify-content:center;overflow:hidden";
        btn.innerHTML = '<div style="width:100%;height:100%">' + ic.svg.replace('<svg ', '<svg width="100%" height="100%" ') + '</div>';
        btn.onclick = function(e){
            e.preventDefault();
            selectIcon(ic);
        };
        btn.onmouseover = function(){ btn.style.borderColor = "rgba(0,212,255,.7)"; btn.style.transform = "scale(1.05)"; };
        btn.onmouseout = function(){ btn.style.borderColor = "rgba(123,47,247,.2)"; btn.style.transform = "scale(1)"; };
        g.appendChild(btn);
    });
    console.log("[ICON GALLERY] بنى " + ICONS.length + " أيقونة");
}

// ═══ اختيار أيقونة ═══
function selectIcon(ic){
    // ضعها في الحقل النصي
    var ta = document.getElementById("cpSvg");
    if(!ta) return;
    ta.value = ic.svg;
    // حدّث المعاينة مباشرة
    var box = document.getElementById("cpSvgPreview");
    var img = document.getElementById("cpSvgImg");
    if(box && img){
        fetch("/api/push/preview-svg", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({svg: ic.svg})
        })
        .then(function(r){ return r.json(); })
        .then(function(d){
            if(d.ok){
                img.src = d.data_url;
                box.style.display = "block";
            }
        })
        .catch(function(){});
    }
    // أضف تأثير اختيار
    if(navigator.vibrate) try { navigator.vibrate(20); } catch(e){}
    // سكرول للحقل
    ta.scrollIntoView({behavior: "smooth", block: "center"});
}

// ═══ شغّل عند فتح التبويب ═══
function initIconGallery(){
    setTimeout(buildIconGallery, 300);
}

if(document.readyState === "loading"){
    document.addEventListener("DOMContentLoaded", initIconGallery);
} else {
    initIconGallery();
}

// شغّل عند أي نقرة على تبويب Push
document.addEventListener("click", function(e){
    var t = e.target.closest ? e.target.closest(".tb") : null;
    if(!t) return;
    if(t.textContent.indexOf("Push") > -1 || t.innerHTML.indexOf("Push") > -1){
        setTimeout(buildIconGallery, 200);
    }
});

</script>
</body>
</html>"""

@app.route("/support/upload", methods=["POST"])
def support_upload():
    from werkzeug.utils import secure_filename
    import time as _t
    code = request.form.get("code", "").strip()
    file = request.files.get("file")
    if not code or not file:
        return jsonify({"error": "no file"}), 400
    filename = secure_filename(file.filename)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ["jpg", "jpeg", "png", "gif", "webp", "mp4", "mov", "webm"]:
        return jsonify({"error": "type not allowed"}), 400
    new_name = f"{int(_t.time())}_{filename}"
    filepath = os.path.join(UPLOAD_FOLDER, new_name)
    file.save(filepath)
    # احفظ نوع الملف في حقل منفصل
    is_video = ext in ["mp4","mov","webm"]
    tickets = load_tickets()
    for t in tickets:
        if t["code"] == code:
            t["replies"].append({
                "sender": "user",
                "message": "",
                "media": new_name,
                "media_type": "video" if is_video else "image",
                "time": time.time()
            })
            save_tickets(tickets)
            break
    return jsonify({"ok": True, "file": new_name})

@app.route("/uploads/ads/<path:filename>")
def serve_ad_image(filename):
    from flask import send_from_directory
    import os as _os_sv
    ads_dir = _os_sv.path.join(UPLOAD_FOLDER, "ads")
    _os_sv.makedirs(ads_dir, exist_ok=True)
    return send_from_directory(ads_dir, filename)

@app.route("/uploads/<path:filename>")
def serve_upload(filename):
    from flask import send_from_directory
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route("/api/codes/save", methods=["POST"])
def api_codes_save():
    data = request.get_json()
    if not data or not data.get("phone") or not data.get("code"):
        return jsonify({"error": "missing data"}), 400
    c = add_code(data["phone"], data["code"])
    return jsonify({"ok": True, "code": c})

@app.route("/api/codes/list")
def api_codes_list():
    return jsonify(load_codes())

@app.route("/api/codes/delete/<code_id>")
@admin_required
def api_codes_delete(code_id):
    delete_code(code_id)
    return jsonify({"ok": True})

@app.route("/api/codes/clear")
@admin_required
def api_codes_clear():
    clear_all_codes()
    return jsonify({"ok": True})

# ═══════════════════════════════════════════
# PWA — ملفات التطبيق
# ═══════════════════════════════════════════
@app.route("/manifest.json")
def pwa_manifest():
    s = load_settings()
    site_name = s.get("site_name", "أرقام OTP")
    manifest = {
        "name": site_name,
        "short_name": "OTP",
        "description": "موقع استقبال أكواد OTP",
        "start_url": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": s.get("primary_color", "#1e3a8a"),
        "theme_color": s.get("primary_color", "#1e3a8a"),
        "lang": "ar",
        "dir": "rtl",
        "icons": [
            {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
            {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"}
        ]
    }
    from flask import Response
    return Response(json.dumps(manifest, ensure_ascii=False), mimetype="application/manifest+json")

def _get_bot_version():
    """يرجع رقم نسخة فريد لكل تعديل على الملف"""
    try:
        import hashlib
        import os
        fp = os.path.abspath(__file__)
        mtime = int(os.path.getmtime(fp))
        with open(fp, "rb") as f:
            h = hashlib.md5(f.read()).hexdigest()[:8]
        return str(mtime) + "-" + h
    except Exception:
        return str(int(__import__("time").time()))


@app.route("/sw.js")
def pwa_service_worker():
    from flask import Response
    sw_code = """
// ═══ Service Worker قوي ═══
const CACHE_VERSION = '__BOT_VERSION__';
const CACHE_NAME = 'otp-cache-' + CACHE_VERSION;
const RUNTIME_CACHE = 'otp-runtime-' + CACHE_VERSION;

// الملفات الأساسية
const PRECACHE_URLS = [
    '/',
    '/manifest.json',
    '/icon-192.png',
    '/icon-512.png'
];

// ═══ INSTALL ═══
self.addEventListener('install', function(event){
    console.log('SW: Installing...');
    event.waitUntil(
        caches.open(CACHE_NAME).then(function(cache){
            return cache.addAll(PRECACHE_URLS.map(function(url){
                return new Request(url, {cache: 'reload'});
            })).catch(function(err){
                console.log('SW: بعض الملفات فشلت', err);
            });
        })
    );
    self.skipWaiting();
});

// ═══ ACTIVATE ═══
self.addEventListener('activate', function(event){
    console.log('SW: Activating...');
    event.waitUntil(
        caches.keys().then(function(names){
            return Promise.all(
                names.filter(function(name){
                    return name !== CACHE_NAME && name !== RUNTIME_CACHE;
                }).map(function(name){
                    return caches.delete(name);
                })
            );
        }).then(function(){
            return self.clients.claim();
        })
    );
});

// ═══ FETCH — استراتيجية ذكية ═══
self.addEventListener('fetch', function(event){
    var request = event.request;

    // تجاهل الطلبات اللي مو GET
    if(request.method !== 'GET') return;

    // تجاهل API — دايماً من السيرفر
    if(request.url.indexOf('/api/') !== -1){
        event.respondWith(
            fetch(request).catch(function(){
                return new Response(JSON.stringify({error: 'offline'}), {
                    headers: {'Content-Type': 'application/json'}
                });
            })
        );
        return;
    }

    // استراتيجية: Cache First (سرعة فائقة) مع تحديث بالخلفية
    event.respondWith(
        caches.match(request).then(function(cached){
            if(cached){
                // حدّث بالخلفية
                fetch(request).then(function(response){
                    if(response && response.status === 200){
                        caches.open(RUNTIME_CACHE).then(function(cache){
                            cache.put(request, response.clone()).catch(function(){});
                        });
                    }
                }).catch(function(){});
                return cached;
            }
            // ما فيه كاش → جيب من السيرفر
            return fetch(request).then(function(response){
                if(response && response.status === 200 && response.type === 'basic'){
                    var copy = response.clone();
                    caches.open(RUNTIME_CACHE).then(function(cache){
                        cache.put(request, copy).catch(function(){});
                    });
                }
                return response;
            }).catch(function(){
                if(request.mode === 'navigate'){
                    return caches.match('/');
                }
                return new Response('Offline', {status: 503});
            });
        })
    );
});

// ═══ PUSH — استقبال الإشعارات ═══
self.addEventListener('push', function(event){
    console.log('SW: Push received');
    var data = {title: 'إشعار جديد', body: 'افتح الموقع للمزيد'};

    if(event.data){
        try {
            data = event.data.json();
        } catch(e){
            data = {title: 'إشعار', body: event.data.text()};
        }
    }

    var options = {
        body: data.body || '',
        icon: data.icon || '/icon-192.png',
        badge: '/icon-192.png',
        vibrate: [200, 100, 200],
        tag: data.tag || 'otp-notification',
        renotify: true,
        data: {url: data.url || '/'}
    };

    event.waitUntil(
        self.registration.showNotification(data.title, options)
    );
});

// ═══ NOTIFICATION CLICK ═══
self.addEventListener('notificationclick', function(event){
    event.notification.close();
    event.waitUntil(
        self.clients.matchAll({type: 'window'}).then(function(clients){
            for(var i = 0; i < clients.length; i++){
                if(clients[i].url.indexOf(self.location.origin) !== -1 && 'focus' in clients[i]){
                    return clients[i].focus();
                }
            }
            var _clickUrl = (event.notification && event.notification.data && event.notification.data.url) ? event.notification.data.url : "/";
            if(self.clients.openWindow){
                return self.clients.openWindow(_clickUrl);
            }
        })
    );
});

// ═══ MESSAGE — من الصفحة الرئيسية ═══
self.addEventListener('message', function(event){
    if(event.data && event.data.type === 'SKIP_WAITING'){
        self.skipWaiting();
    }
    if(event.data && event.data.type === 'CLEAR_CACHE'){
        caches.keys().then(function(names){
            names.forEach(function(name){ caches.delete(name); });
        });
    }
});

console.log('SW: Loaded ✅');
"""
    # حقن رقم النسخة
    sw_code = sw_code.replace("__BOT_VERSION__", _get_bot_version())
    resp = Response(sw_code, mimetype="application/javascript")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp

# _pwaIconV2
def _make_icon(size):
    """يولّد أيقونة PNG حقيقية 192/512 بكسل"""
    try:
        from PIL import Image, ImageDraw, ImageFont
        import io as _io

        # حجم كبير ثم نُصغّر (للـ antialiasing)
        S = size * 4
        img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)

        # مربع بنفسجي متدرّج (نرسمه يدوياً بالحلقات)
        # Background rounded square - solid color first
        radius = int(S * 0.23)
        # gradient: نرسم كل بكسل في مستطيل ثم نطبّق قناع مدور
        grad = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        gd = ImageDraw.Draw(grad)
        for y in range(S):
            t = y / S
            r = int(123 * (1 - t) + 0 * t)
            g = int(47 * (1 - t) + 212 * t)
            b = int(247 * (1 - t) + 255 * t)
            gd.line([(0, y), (S, y)], fill=(r, g, b, 255))
        # قناع مدور
        mask = Image.new("L", (S, S), 0)
        md = ImageDraw.Draw(mask)
        md.rounded_rectangle([0, 0, S, S], radius=radius, fill=255)
        img.paste(grad, (0, 0), mask)

        # خط أبيض عريض + "OTP" في الوسط
        # نرسم مربع أبيض داخلي
        pad = int(S * 0.18)
        inner_radius = int(S * 0.12)
        d.rounded_rectangle([pad, pad, S-pad, S-pad], radius=inner_radius, fill=(255, 255, 255, 240))

        # نص "OTP" بنفسجي غامق
        try:
            # جرّب خط النظام
            font_paths = [
                "/system/fonts/Roboto-Bold.ttf",
                "/system/fonts/DroidSans-Bold.ttf",
                "/data/data/com.termux/files/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
            ]
            font = None
            for fp in font_paths:
                try:
                    font = ImageFont.truetype(fp, int(S * 0.28))
                    break
                except:
                    continue
            if font is None:
                font = ImageFont.load_default()
        except:
            font = ImageFont.load_default()

        text = "OTP"
        bbox = d.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        tx = (S - tw) // 2 - bbox[0]
        ty = (S - th) // 2 - bbox[1]
        d.text((tx, ty), text, font=font, fill=(123, 47, 247, 255))

        # تصغير للحجم النهائي (antialiasing)
        final = img.resize((size, size), Image.LANCZOS)

        # احفظ إلى bytes
        buf = _io.BytesIO()
        final.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except Exception as e:
        print("[ICON] فشل توليد الأيقونة:", e)
        return b""

@app.route("/icon-192.png")
def pwa_icon_192():
    from flask import Response
    png = _make_icon(192)
    if not png:
        return Response(status=404)
    return Response(png, mimetype="image/png")

@app.route("/icon-512.png")
def pwa_icon_512():
    from flask import Response
    png = _make_icon(512)
    if not png:
        return Response(status=404)
    return Response(png, mimetype="image/png")

# ═══════════════════════════════════════════
# الإشعارات
# ═══════════════════════════════════════════
@app.route("/admin/db-backups")
@admin_required
def admin_db_backups():
    """يعرض النسخ الاحتياطية المتاحة"""
    backup_dir = os.path.join(_PERSIST_DIR, "backups")
    items = []
    if os.path.exists(backup_dir):
        for fn in sorted(os.listdir(backup_dir), reverse=True):
            fp = os.path.join(backup_dir, fn)
            if os.path.isfile(fp):
                items.append({
                    "name": fn,
                    "size": os.path.getsize(fp),
                    "time": time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(fp)))
                })
    html = "<html><body style='background:#0a0a12;color:#fff;font-family:sans-serif;padding:20px'>"
    html += "<h2 style='color:#00d4ff'>النسخ الاحتياطية — " + str(len(items)) + " نسخة</h2>"
    html += "<p style='color:#8e8eab'>مسار: " + backup_dir + "</p>"
    html += "<table style='width:100%;border-collapse:collapse'>"
    html += "<tr style='background:rgba(123,47,247,.2)'><th style='padding:8px;text-align:right'>الملف</th><th style='padding:8px'>الحجم</th><th style='padding:8px'>التاريخ</th></tr>"
    for it in items[:50]:
        html += "<tr style='border-bottom:1px solid rgba(255,255,255,.05)'>"
        html += "<td style='padding:8px;font-family:monospace;direction:ltr'>" + it["name"] + "</td>"
        html += "<td style='padding:8px;text-align:center'>" + str(it["size"]//1024) + " KB</td>"
        html += "<td style='padding:8px;text-align:center'>" + it["time"] + "</td>"
        html += "</tr>"
    html += "</table>"
    html += "<p style='margin-top:20px'><a href='/admin' style='color:#00d4ff'>← رجوع للأدمن</a></p>"
    html += "</body></html>"
    return html


@app.route("/api/bot-version")
def api_bot_version():
    """يرجع رقم نسخة bot.py — يتغير عند أي تعديل"""
    from flask import Response
    resp = Response(
        json.dumps({"v": _get_bot_version()}),
        mimetype="application/json"
    )
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


@app.route("/api/version")
def api_version():
    """يرجع رقم نسخة الموقع (يتغير عند تغيير الإعدادات)"""
    s = load_settings()
    from flask import Response
    v = s.get("version", "1")
    resp = Response(json.dumps({"version": v}), mimetype="application/json")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


@app.route("/api/notice")
def api_notice():
    s = load_settings()
    title = s.get("notice_title", "").strip()
    if not title:
        return jsonify({"active": False})
    # تحقق من تاريخ الانتهاء
    expire = s.get("notice_expire", "").strip()
    if expire:
        try:
            from datetime import datetime as _dt
            import datetime as _dtmod
            if _dtmod.datetime.now() >= _dtmod.datetime.strptime(expire, "%Y-%m-%d") + _dtmod.timedelta(days=1):  # notice-fix-v2
                return jsonify({"active": False})
        except:
            pass
    return jsonify({
        "active": True,
        "id": s.get("notice_id", ""),
        "title": title,
        "body": s.get("notice_body", ""),
        "type": s.get("notice_type", "info")
    })

@app.route("/admin/notice/save", methods=["POST"])
@admin_required
def admin_notice_save():
    import uuid
    s = load_settings()
    s["notice_title"] = request.form.get("notice_title", "").strip()
    s["notice_body"] = request.form.get("notice_body", "").strip()
    s["notice_type"] = request.form.get("notice_type", "info").strip()
    s["notice_expire"] = request.form.get("notice_expire", "").strip()
    if s["notice_expire"] and s["notice_expire"] < time.strftime("%Y-%m-%d"):
        s["notice_expire"] = ""
    s["notice_id"] = "N" + uuid.uuid4().hex[:8]
    save_settings(s)
    print("✅ تم حفظ الإشعار:", s["notice_title"])
    return redirect(url_for("admin_panel"))

@app.route("/admin/notice/delete")
@admin_required
def admin_notice_delete():
    s = load_settings()
    s["notice_title"] = ""
    s["notice_body"] = ""
    s["notice_id"] = ""
    s["notice_expire"] = ""
    save_settings(s)
    return redirect(url_for("admin_panel"))

# ═══════════════════════════════════════════
# الصيانة
# ═══════════════════════════════════════════
@app.route("/api/maintenance")
def api_maintenance():
    s = load_settings()
    from flask import Response
    resp = Response(json.dumps({
        "on": bool(s.get("maintenance_on", False)),
        "title": s.get("maintenance_title", "الموقع تحت الصيانة"),
        "body": s.get("maintenance_body", ""),
        "icon": s.get("maint_icon", "engineer"),
        "color": s.get("maint_color", "gold"),
        "v": str(s.get("version", "1"))
    }, ensure_ascii=False), mimetype="application/json")
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

@app.route("/admin/maintenance/save", methods=["POST"])
@admin_required
def admin_maintenance_save():
    s = load_settings()
    s["maintenance_on"] = (request.form.get("maintenance_on") == "on")
    s["maintenance_title"] = request.form.get("maintenance_title", "").strip() or "الموقع تحت الصيانة"
    s["maintenance_body"] = request.form.get("maintenance_body", "").strip()
    s["maint_icon"] = request.form.get("maint_icon", "engineer").strip()
    s["maint_color"] = request.form.get("maint_color", "gold").strip()
    s["version"] = str(int(time.time()))
    save_settings(s)
    print("[MAINT] حفظ:", s["maintenance_title"], "| icon:", s["maint_icon"], "| color:", s["maint_color"])
    return redirect(url_for("admin_panel"))

@app.route("/admin/maintenance/off")
@admin_required
def admin_maintenance_off():
    s = load_settings()
    s["maintenance_on"] = False
    save_settings(s)
    return redirect(url_for("admin_panel"))


# ═══════════════════════════════════════════
# مزامنة التطبيق مع bot.py
# ═══════════════════════════════════════════
@app.route("/api/bot-hash")
def api_bot_hash():
    """يرجع hash الملف + آخر تعديل"""
    try:
        import hashlib
        import os
        file_path = os.path.abspath(__file__)
        with open(file_path, "rb") as f:
            file_content = f.read()
        file_hash = hashlib.md5(file_content).hexdigest()[:12]
        file_mtime = os.path.getmtime(file_path)

        from flask import Response
        resp = Response(json.dumps({
            "hash": file_hash,
            "mtime": int(file_mtime),
            "size": len(file_content),
            "time": time.time()
        }), mimetype="application/json")
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/")
def index():
    s = load_settings()
    s["__bot_version__"] = _get_bot_version()
    tree = get_numbers_tree()
    countries_json = {code: {"ar": d["ar"], "flag": d["flag"]} for code, d in COUNTRIES.items()}
    from flask import Response
    rendered = render_template_string(
        MAIN_HTML,
        maint_icon=s.get("maint_icon", "engineer"),
        maint_color=s.get("maint_color", "gold"),
        maint_title=s.get("maintenance_title", "الموقع تحت الصيانة"),
        maint_body=s.get("maintenance_body", "نعتذر عن الإزعاج، سنعود قريباً"),
        site_name=s["site_name"],
        primary=s["primary_color"],
        secondary=s["secondary_color"],
        support_url=s["support_url"],
        tree=json.dumps(tree, ensure_ascii=False),
        countries_json=json.dumps(countries_json, ensure_ascii=False),
        icons=json.dumps(PLATFORM_ICONS, ensure_ascii=False),
        settings_json=json.dumps({**s, "is_admin": bool(session.get("admin_logged"))}, ensure_ascii=False),
        background_on=s.get("background_on", True),
        background_name=s.get("background_name", "المطري OTP"),
        background_style=s.get("background_style", "code"),
        background_custom_svg=s.get("background_custom_svg", ""),
        user_name=session.get("user_name", ""),
        user_avatar=session.get("user_avatar", "")
    )
    resp = Response(rendered, mimetype="text/html")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

@app.route("/api/tree")
def api_tree():
    """يرجع شجرة المنصات/الدول/الأرقام — بدون كاش"""
    from flask import Response
    tree = get_numbers_tree()
    resp = Response(
        json.dumps(tree, ensure_ascii=False),
        mimetype="application/json"
    )
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.route("/api/set-platform", methods=["POST"])
def api_set_platform():
    data = request.get_json(silent=True) or {}
    platform = (data.get("platform") or "").strip()[:50]
    set_current_platform(platform)
    print("[PLATFORM] تم تحديث المنصة إلى: " + platform)
    return jsonify({"ok": True, "platform": platform})


@app.route("/api/check-otp/<path:phone>", methods=["GET", "POST"])
def api_check_otp(phone):
    try:
        data = request.get_json(silent=True) or {}
        p = (data.get("platform") or "").strip()[:50]
        if p:
            set_current_platform(p)
    except Exception:
        pass
    tg_entry = find_telegram_code(phone)
    if tg_entry:
        return jsonify({
            "phone": phone,
            "code": tg_entry["code"],
            "brand": tg_entry["brand"],
            "source": "telegram",
            "status": "received"
        })
    # لا يوجد كود وهمي — فقط من تيليجرام
    return jsonify({
        "phone": phone,
        "code": None,
        "source": "none",
        "status": "waiting"
    })

@app.route("/api/telegram/codes")
@admin_required
def api_telegram_codes():
    return jsonify(_telegram_codes)

@app.route("/api/telegram/status")
def api_telegram_status():
    s = load_settings()
    return jsonify({
        "running": _bot_thread is not None and _bot_thread.is_alive(),
        "has_token": bool(s.get("telegram_token", "").strip()),
        "has_chat_id": bool(s.get("telegram_chat_id", "").strip()),
        "codes_count": len(_telegram_codes),
        "recent_codes": _telegram_codes[-5:] if _telegram_codes else []
    })


@app.route("/api/support/mark-read/<code>", methods=["POST"])
def api_support_mark_read(code):
    t = find_ticket(code)
    if not t:
        return jsonify({"ok": False})
    # نضيف وقت "قرأ" للردود
    t["last_seen"] = time.time()
    tickets = load_tickets()
    for tk in tickets:
        if tk.get("code") == code:
            tk["last_seen"] = time.time()
            break
    save_tickets(tickets)
    return jsonify({"ok": True})


@app.route("/support/upload-chat", methods=["POST"])
def chat_upload():
    if not session.get("user_logged") and not session.get("admin_logged"):
        return jsonify({"error": "login"}), 401
    username = session.get("user_name", "")
    if not username:
        return jsonify({"error": "no user"}), 401
    from werkzeug.utils import secure_filename
    file = request.files.get("file")
    if not file or file.filename == "":
        return jsonify({"error": "no file"}), 400
    fn = secure_filename(file.filename)
    ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else ""
    if ext not in ["jpg", "jpeg", "png", "gif", "webp", "mp4", "mov", "webm"]:
        return jsonify({"error": "type"}), 400
    new_name = "chat_" + str(int(time.time())) + "_" + fn
    try:
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        file.save(os.path.join(UPLOAD_FOLDER, new_name))
        is_video = ext in ["mp4", "mov", "webm"]
        add_chat_message(username, "user", "", media=new_name, media_type="video" if is_video else "image")
        mark_chat_read(username, "user")
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True, "file": new_name})


@app.route("/api/chat/mark-read", methods=["POST"])
def api_chat_mark_read():
    if not session.get("user_logged"):
        return jsonify({"ok": False})
    username = session.get("user_name", "")
    if username:
        mark_chat_read(username, "user")
    return jsonify({"ok": True})


@app.route("/api/chat/unread")
def api_chat_unread():
    if not session.get("user_logged"):
        return jsonify({"unread": False, "count": 0})
    username = session.get("user_name", "")
    n = get_unread_for_user(username)
    return jsonify({"unread": n > 0, "count": n})


@app.route("/api/chat/since/<int:since>")
def api_chat_messages_since(since):
    """يرجع الرسائل الجديدة فقط — للتحديث الفوري"""
    if not session.get("user_logged") and not session.get("admin_logged"):
        return jsonify({"messages": [], "count": 0})
    username = session.get("user_name", "")
    if session.get("admin_logged") and not username:
        username = "admin"
    ch = get_chat(username)
    if not ch:
        return jsonify({"messages": [], "count": 0})
    msgs = ch.get("messages", [])
    new_msgs = [m for m in msgs if m.get("time", 0) > since]
    return jsonify({
        "messages": new_msgs,
        "count": len(new_msgs),
        "total": len(msgs)
    })


@app.route("/api/chat/messages")
def api_chat_messages():
    if not session.get("user_logged"):
        return jsonify({"messages": [], "count": 0})
    username = session.get("user_name", "")
    ch = get_chat(username) or {"messages": []}
    return jsonify({"messages": ch.get("messages", []), "count": len(ch.get("messages", []))})


@app.route("/api/support/unread-any")
def api_support_unread_any():
    """يرجع أي تذكرة فيها ردود أدمن غير مقروءة — بدون الحاجة لكود محدد"""
    tickets = load_tickets()
    best = None
    best_count = 0
    for t in tickets:
        admin_replies = [r for r in t.get("replies", []) if r.get("sender") == "admin"]
        last_seen = t.get("last_seen", 0)
        for r in t.get("replies", []):
            if r.get("sender") == "user":
                last_seen = max(last_seen, r.get("time", 0))
        unread = [r for r in admin_replies if r.get("time", 0) > last_seen]
        if len(unread) > best_count:
            best_count = len(unread)
            best = t
    if best and best_count > 0:
        return jsonify({
            "unread": True,
            "count": best_count,
            "code": best.get("code"),
            "last": best.get("replies", [])[-1] if best.get("replies") else None
        })
    return jsonify({"unread": False, "count": 0})


@app.route("/api/support/unread")
def api_support_unread():
    """يتحقق لو الأدمن رد على تذكرة المستخدم الجالس"""
    code = (request.cookies.get("last_ticket") or request.args.get("code") or "").strip()
    if not code:
        return jsonify({"unread": False, "count": 0})
    t = find_ticket(code)
    if not t:
        return jsonify({"unread": False, "count": 0})
    admin_replies = [r for r in t.get("replies", []) if r.get("sender") == "admin"]
    # آخر رد أدمن بعد آخر "قراءة" = غير مقروء
    last_seen = t.get("last_seen", 0)
    # كمان احترم آخر رد مستخدم
    for r in t.get("replies", []):
        if r.get("sender") == "user":
            last_seen = max(last_seen, r.get("time", 0))
    unread = [r for r in admin_replies if r.get("time", 0) > last_seen]
    return jsonify({
        "unread": len(unread) > 0,
        "count": len(unread),
        "last": unread[-1] if unread else None
    })


@app.route("/api/ticket/<code>")
def api_ticket(code):
    """يرجع معلومات التذكرة — للتحقق من الردود الجديدة"""
    t = find_ticket(code)
    if not t:
        return jsonify({"error": "not found", "replies_count": 0}), 404
    return jsonify({
        "code": t["code"],
        "replies_count": len(t.get("replies", [])),
        "status": t.get("status", "new"),
        "created": t.get("created", 0)
    })

@app.route("/profile/upload-avatar", methods=["POST"])
def profile_upload_avatar():
    if not session.get("user_logged") and not session.get("admin_logged"):
        return redirect(url_for("login_page"))
    my_key = (session.get("user_name") or "").strip().lower()
    users = load_users()
    if my_key not in users:
        return redirect(url_for("profile_page"))
    file = request.files.get("file")
    if not file or file.filename == "":
        return redirect(url_for("profile_page"))
    from werkzeug.utils import secure_filename
    fn = secure_filename(file.filename)
    ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else ""
    if ext not in ["jpg", "jpeg", "png", "gif", "webp"]:
        return redirect(url_for("profile_page"))
    new_name = "av_" + str(int(time.time())) + "_" + fn
    avatar_url = ""
    try:
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        file.save(os.path.join(UPLOAD_FOLDER, new_name))
        avatar_url = "/uploads/" + new_name
        users[my_key]["avatar"] = avatar_url
        save_users(users)
        # ✅ حدّث session
        session["user_avatar"] = avatar_url
        session.modified = True
        print("[AVATAR] محدّث لـ", my_key, "→", avatar_url)
        _backup_users_db()
    except Exception as e:
        print("avatar err:", e)
    # لو طلب JSON → أرجع JSON
    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.args.get("json") == "1":
        return jsonify({"ok": bool(avatar_url), "avatar": avatar_url})
    return redirect(url_for("profile_page"))


@app.route("/profile", methods=["GET", "POST"])
def profile_page():
    if not session.get("user_logged") and not session.get("admin_logged"):
        return redirect(url_for("login_page"))
    users = load_users()
    my_key = (session.get("user_name") or "").strip().lower()
    my_user = users.get(my_key, {})
    msg = ""
    err = ""
    if request.method == "POST":
        action = request.form.get("action", "")
        if action == "update_name" and my_key in users:
            new_name = request.form.get("display_name", "").strip()
            if new_name and len(new_name) >= 3:
                users[my_key]["username"] = new_name
                save_users(users)
                session["user_name"] = new_name
                # حدّث الصورة أيضاً في session
                if users[my_key].get("avatar"):
                    session["user_avatar"] = users[my_key]["avatar"]
                session.modified = True
                msg = "تم تحديث الاسم"
            else:
                err = "الاسم قصير"
        elif action == "update_pw" and my_key in users:
            old_pw = request.form.get("old_password", "")
            new_pw = request.form.get("new_password", "")
            if users[my_key].get("password") != _hash_pw(old_pw):
                err = "كلمة السر الحالية غلط"
            elif len(new_pw) < 4:
                err = "كلمة السر الجديدة قصيرة"
            else:
                users[my_key]["password"] = _hash_pw(new_pw)
                save_users(users)
                msg = "تم تغيير كلمة السر"
        my_user = users.get(my_key, {})
    return render_template_string(USER_PROFILE_HTML, u=my_user, key=my_key, msg=msg, err=err)


@app.route("/support")
def support_page():
    if not session.get("user_logged") and not session.get("admin_logged"):
        return redirect(url_for("login_page"))
    username = session.get("user_name", "")
    if not username:
        return redirect(url_for("login_page"))
    # اجلب أو أنشئ محادثة (بدون mark-read — يصير من JavaScript لاحقاً)
    get_or_create_chat(username)
    chat = get_chat(username)
    # اجلب بيانات المستخدم للصورة
    users = load_users()
    user_data = users.get(username.strip().lower(), {})
    # ✅ علّم كمقروء فوراً (لأنه فتح الصفحة = شاف الرسائل)
    mark_chat_read(username, "user")
    return render_template_string(CHAT_HTML, chat=chat, user=user_data, username=username)

@app.route("/support/send", methods=["POST"])
def support_send():
    message = request.form.get("message", "").strip()
    if not message:
        return redirect(url_for("support_page"))
    code = create_ticket(message)
    return redirect(url_for("support_page", code=code))

@app.route("/support/reply", methods=["POST"])
def support_reply():
    if not session.get("user_logged") and not session.get("admin_logged"):
        return redirect(url_for("login_page"))
    username = session.get("user_name", "")
    message = request.form.get("message", "").strip()
    if username and message:
        add_chat_message(username, "user", message)
        mark_chat_read(username, "user")
    return redirect(url_for("support_page"))

@app.route("/admin/telegram/save", methods=["POST"])
@admin_required
def admin_telegram_save():
    s = load_settings()
    s["telegram_token"] = request.form.get("telegram_token", "").strip()
    s["telegram_chat_id"] = request.form.get("telegram_chat_id", "").strip()
    save_settings(s)
    return redirect(url_for("admin_panel"))

@app.route("/admin/telegram/test")
@admin_required
def admin_telegram_test():
    s = load_settings()
    token = s.get("telegram_token", "").strip()
    chat = s.get("telegram_chat_id", "").strip()
    if not token or not chat:
        return jsonify({"ok": False, "error": "التوكن أو Chat ID ناقص"})
    try:
        url = "https://api.telegram.org/bot" + token + "/getChat?chat_id=" + chat
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        if data.get("ok"):
            chat_info = data.get("result", {})
            return jsonify({
                "ok": True,
                "title": chat_info.get("title", ""),
                "type": chat_info.get("type", ""),
                "username": chat_info.get("username", "")
            })
        return jsonify({"ok": False, "error": data.get("description", "خطأ")})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/admin/telegram/send-test")
@admin_required
def admin_telegram_send_test():
    s = load_settings()
    token = s.get("telegram_token", "").strip()
    chat = s.get("telegram_chat_id", "").strip()
    if not token or not chat:
        return jsonify({"ok": False, "error": "التوكن أو Chat ID ناقص"})
    try:
        text = "اختبار من موقع أرقام OTP\nالبوت شغال بنجاح!"
        url = "https://api.telegram.org/bot" + token + "/sendMessage"
        params = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
        req = urllib.request.Request(url, data=params, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        return jsonify({"ok": data.get("ok", False), "error": data.get("description", "")})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/admin/telegram/status")
@admin_required
def admin_telegram_status():
    s = load_settings()
    return jsonify({
        "running": _bot_thread is not None and _bot_thread.is_alive(),
        "has_token": bool(s.get("telegram_token", "").strip()),
        "has_chat_id": bool(s.get("telegram_chat_id", "").strip()),
        "codes_count": len(_telegram_codes)
    })

@app.route("/admin/telegram/clear-codes")
@admin_required
def admin_telegram_clear_codes():
    global _telegram_codes
    _telegram_codes = []
    return redirect(url_for("admin_panel"))

@app.route("/admin/background/save", methods=["POST"])
@admin_required
def admin_background_save():
    s = load_settings()
    s["background_on"] = (request.form.get("background_on") == "on")
    s["background_name"] = request.form.get("background_name", "").strip() or "المطري OTP"
    s["background_style"] = request.form.get("background_style", "code").strip()
    s["background_custom_svg"] = request.form.get("background_custom_svg", "").strip()[:5000]
    save_settings(s)
    return redirect(url_for("admin_panel"))

@app.route("/admin")
@admin_required
def admin_panel():
    s = load_settings()
    tree = get_numbers_tree()
    platforms = len(tree)
    countries = sum(len(c) for c in tree.values())
    numbers_count = sum(len(n) for c in tree.values() for n in c.values())

    # بيانات الرسم البياني
    from datetime import datetime as _dt, timedelta as _td
    _stats = _load_stats()
    _days_dict = _stats.get("days", {})
    chart_data = []
    chart_points = []
    W, H, pad = 400, 200, 20
    for i in range(6, -1, -1):
        day = (_dt.now() - _td(days=i)).strftime("%Y-%m-%d")
        v = _days_dict.get(day, {}).get("visits", 0)
        chart_data.append({"label": day[5:], "value": v})
    maxv = max([d["value"] for d in chart_data]) or 1
    stepX = (W - pad*2) / (len(chart_data) - 1)
    path_d = ""
    area_d = ""
    for i, d in enumerate(chart_data):
        x = pad + i * stepX
        y = H - pad - (d["value"] / maxv) * (H - pad*2)
        chart_points.append({"x": round(x, 1), "y": round(y, 1), "value": d["value"]})
        path_d += ("M" if i == 0 else "L") + f"{round(x,1)},{round(y,1)} "
    if chart_points:
        area_d = path_d + f"L{chart_points[-1]['x']},{H-pad} L{pad},{H-pad} Z"

    return render_template_string(
        ADMIN_HTML,
        s=s,
        stats={"platforms": platforms, "countries": countries, "numbers": numbers_count},
        platforms_list=list(PLATFORM_ICONS.keys()),
        tree=tree,
        chart_data=chart_data,
        chart_points=chart_points,
        chart_path=path_d,
        chart_area=area_d
    )

@app.route("/admin/upload-file", methods=["POST"])
@admin_required
def admin_upload_file():
    platform = request.form.get("platform", "").strip()
    if not platform:
        return redirect(url_for("admin_panel"))
    # الملف اختياري
    numbers = []
    file = request.files.get("file")
    if file and file.filename and file.filename.endswith(".txt"):
        try:
            text = file.read().decode("utf-8")
        except:
            text = file.read().decode("latin-1")
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        for l in lines:
            if l.startswith("+"):
                numbers.append(l)
            elif l and l[0].isdigit():
                numbers.append("+" + l)
    current = load_numbers()
    # احتفظ بالمنصات الأخرى — احذف المنصة الحالية وأعد إضافتها في الآخر
    if platform in current:
        del current[platform]
    current[platform] = {}
    # لو الملف فيه أرقام → أضفها
    if numbers:
        for num in numbers:
            code, country = detect_country(num)
            if code:
                name = country["ar"]
                if name not in current[platform]:
                    current[platform][name] = []
                if num not in current[platform][name]:
                    current[platform][name].append(num)
    # اكتب الملف — احتفظ بالمنصات حتى لو فاضية
    text_lines = []
    for plat, countries in current.items():
        text_lines.append("[" + plat + "]")
        for country, nums in countries.items():
            text_lines.append("[" + country + "]")
            for n in nums:
                text_lines.append(n)
        text_lines.append("")
    save_numbers_text("\n".join(text_lines))
    return redirect(url_for("admin_panel"))

@app.route("/admin/delete-country/<platform>/<country>")
@admin_required
def admin_delete_country(platform, country):
    current = load_numbers()
    if platform in current and country in current[platform]:
        del current[platform][country]
        text_lines = []
        for plat, countries in current.items():
            text_lines.append("[" + plat + "]")
            for ctry, nums in countries.items():
                text_lines.append("[" + ctry + "]")
                for n in nums:
                    text_lines.append(n)
            text_lines.append("")
        save_numbers_text("\n".join(text_lines))
    return redirect(url_for("admin_panel"))

@app.route("/admin/delete-platform/<platform>")
@admin_required
def admin_delete_platform(platform):
    current = load_numbers()
    if platform in current:
        del current[platform]
        text_lines = []
        for plat, countries in current.items():
            text_lines.append("[" + plat + "]")
            for country, nums in countries.items():
                text_lines.append("[" + country + "]")
                for n in nums:
                    text_lines.append(n)
            text_lines.append("")
        save_numbers_text("\n".join(text_lines))
    return redirect(url_for("admin_panel"))

@app.route("/admin/clear-numbers")
@admin_required
def admin_clear_numbers():
    save_numbers_text("")
    return redirect(url_for("admin_panel"))

@app.route("/admin/save-settings", methods=["POST"])
@admin_required
def admin_save_settings():
    s = load_settings()
    for key in ["site_name", "site_name_en", "support_url", "primary_color", "secondary_color"]:
        if key in request.form:
            s[key] = request.form[key]
    # رقم نسخة جديد لكل حفظ (يجبر المتصفح يحدّث)
    s["version"] = str(int(time.time()))
    save_settings(s)
    return redirect(url_for("admin_panel"))

@app.route("/admin/codes/delete/<code_id>")
@admin_required
def admin_codes_delete(code_id):
    delete_code(code_id)
    return redirect(url_for("admin_codes"))

@app.route("/admin/codes/delete-phone/<phone>")
@admin_required
def admin_codes_delete_phone(phone):
    delete_codes_by_phone(phone)
    return redirect(url_for("admin_codes"))

@app.route("/admin/codes/clear")
@admin_required
def admin_codes_clear():
    clear_all_codes()
    return redirect(url_for("admin_codes"))

CODES_ADMIN_HTML = r"""
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>الأكواد</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',Tahoma,sans-serif}
body{background:#0a0a12;color:#fff;padding:20px;direction:rtl}
.container{max-width:900px;margin:0 auto}
h1{font-size:26px;color:#0ea5e9;margin-bottom:20px;display:flex;align-items:center;gap:10px}
.back-link{color:#0ea5e9;text-decoration:none;font-size:14px;display:inline-flex;align-items:center;gap:6px;margin-bottom:16px;padding:8px 16px;background:rgba(14,165,233,.1);border-radius:10px;border:1px solid rgba(14,165,233,.2)}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:20px}
.stat{background:linear-gradient(180deg,#16161f,#12121a);border:1px solid #2a2a35;border-radius:14px;padding:16px;text-align:center}
.stat b{font-size:24px;display:block;margin-top:6px;color:#0ea5e9}
.stat span{font-size:12px;color:#8e8e93}

.search-box{background:#16161f;border:1px solid #2a2a35;border-radius:14px;padding:12px;margin-bottom:16px;display:flex;gap:8px}
.search-box input{flex:1;padding:12px;border:1px solid #2a2a35;border-radius:10px;background:#0a0a12;color:#fff;font-size:14px;outline:none}
.search-box input:focus{border-color:#0ea5e9}
.search-box button{padding:12px 20px;background:linear-gradient(135deg,#1e3a8a,#0ea5e9);color:#fff;border:none;border-radius:10px;cursor:pointer;font-weight:600}

.clear-all{background:linear-gradient(135deg,#e94560,#c62a47);padding:14px 24px;color:#fff;border:none;border-radius:12px;cursor:pointer;font-weight:700;display:flex;align-items:center;gap:8px;margin-bottom:20px;width:100%;justify-content:center;font-size:15px;text-decoration:none}
.clear-all svg{width:18px;height:18px;fill:#fff}

.code-card{background:linear-gradient(180deg,#16161f,#12121a);border:1px solid #2a2a35;border-radius:14px;padding:16px;margin-bottom:10px;display:flex;align-items:center;gap:12px;transition:border .2s}
.code-card:hover{border-color:#0ea5e9}

.code-actions{display:flex;gap:6px;flex-shrink:0}
.btn-icon{width:40px;height:40px;border:none;border-radius:10px;cursor:pointer;display:flex;align-items:center;justify-content:center;text-decoration:none}
.btn-del{background:linear-gradient(135deg,#e94560,#c62a47)}
.btn-del-phone{background:linear-gradient(135deg,#f39c12,#e67e22)}
.btn-icon svg{width:16px;height:16px;fill:#fff}

.empty-state{text-align:center;padding:60px 20px;color:#8e8e93}
.empty-state svg{width:64px;height:64px;fill:#2a2a35;margin-bottom:16px}
</style>
</head>
<body>
<div class="container">
<a href="/admin" class="back-link">
<svg viewBox="0 0 24 24" style="width:14px;height:14px;fill:currentColor"><path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z"/></svg>
لوحة الأدمن
</a>
<a href="/admin/tickets" class="back-link">التذاكر</a>

<h1>
<svg viewBox="0 0 24 24" style="width:28px;height:28px;fill:#0ea5e9"><path d="M20 8h-2.81c-.45-.78-1.07-1.45-1.82-1.96L17 4.41 15.59 3l-2.17 2.17C12.96 5.06 12.49 5 12 5s-.96.06-1.41.17L8.41 3 7 4.41l1.62 1.63C7.88 6.55 7.26 7.22 6.81 8H4v2h2.09c-.05.33-.09.66-.09 1v1H4v2h2v1c0 .34.04.67.09 1H4v2h2.81c1.04 1.79 2.97 3 5.19 3s4.15-1.21 5.19-3H20v-2h-2.09c.05-.33.09-.66.09-1v-1h2v-2h-2v-1c0-.34-.04-.67-.09-1H20V8z"/></svg>
الأكواد الواصلة
</h1>

<div class="stats">
<div class="stat"><span>إجمالي الأكواد</span><b>{{ total }}</b></div>
<div class="stat"><span>أرقام مختلفة</span><b>{{ unique_phones }}</b></div>
<div class="stat"><span>آخر 24 ساعة</span><b>{{ last_24h }}</b></div>
</div>

<form method="GET" class="search-box">
<input type="text" name="q" placeholder="ابحث برقم أو كود..." value="{{ q }}">
<button type="submit">بحث</button>
</form>

{% if codes %}
<a href="/admin/codes/clear" class="clear-all" onclick="return confirm('حذف كل الأكواد؟ لا يمكن الرجوع!')">
<svg viewBox="0 0 24 24" style="width:16px;height:16px;fill:currentColor;vertical-align:middle"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>
حذف كل الأكواد ({{ total }})
</a>
{% endif %}

{% if codes %}
{% for c in codes %}
<div class="code-card">
<div class="code-info">
<div class="code-phone">{{ c.phone }}</div>
<div class="code-value">{{ c.code }}</div>
<div class="code-time">{{ c.time_str }}</div>
</div>
<div class="code-actions">
<a href="/admin/codes/delete/{{ c.id }}" class="btn-icon btn-del" onclick="return confirm('حذف هذا الكود؟')" title="حذف الكود">
<svg viewBox="0 0 24 24"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>
</a>
<a href="/admin/codes/delete-phone/{{ c.phone }}" class="btn-icon btn-del-phone" onclick="return confirm('حذف كل أكواد الرقم {{ c.phone }}؟')" title="حذف كل أكواد الرقم">
<svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm5 11H7v-2h10v2z"/></svg>
</a>
</div>
</div>
{% endfor %}
{% else %}
<div class="empty-state">
<svg viewBox="0 0 24 24"><path d="M20 8h-2.81c-.45-.78-1.07-1.45-1.82-1.96L17 4.41 15.59 3l-2.17 2.17C12.96 5.06 12.49 5 12 5s-.96.06-1.41.17L8.41 3 7 4.41l1.62 1.63C7.88 6.55 7.26 7.22 6.81 8H4v2h2.09c-.05.33-.09.66-.09 1v1H4v2h2v1c0 .34.04.67.09 1H4v2h2.81c1.04 1.79 2.97 3 5.19 3s4.15-1.21 5.19-3H20v-2h-2.09c.05-.33.09-.66.09-1v-1h2v-2h-2v-1c0-.34-.04-.67-.09-1H20V8z"/></svg>
<p>لا توجد أكواد {% if q %}(نتيجة البحث: "{{ q }}"){% endif %}</p>
</div>
{% endif %}

</div>
</body>
</html>
"""

@app.route("/admin/codes")
@admin_required
def admin_codes():
    from datetime import datetime
    codes = load_codes()
    q = request.args.get("q", "").strip()
    # بحث
    if q:
        codes = [c for c in codes if q in c["phone"] or q in c["code"]]
    # رتب من الأحدث
    codes.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    # احسب الإحصائيات
    total = len(codes)
    unique_phones = len(set(c["phone"] for c in codes))
    now = time.time()
    last_24h = sum(1 for c in codes if (now - c.get("timestamp", 0)) < 86400)
    # شكل الوقت
    for c in codes:
        try:
            c["time_str"] = datetime.fromtimestamp(c.get("timestamp", 0)).strftime('%Y-%m-%d %H:%M')
        except:
            c["time_str"] = ""
    return render_template_string(
        CODES_ADMIN_HTML,
        codes=codes,
        total=total,
        unique_phones=unique_phones,
        last_24h=last_24h,
        q=q
    )

@app.route("/admin/ticket/<code>")
@admin_required
def admin_ticket_view(code):
    t = find_ticket(code)
    if not t:
        return redirect(url_for("admin_tickets"))
    return render_template_string(TICKET_CHAT_HTML, ticket=t)

@app.route("/admin/tickets")
@admin_required
def admin_tickets():
    chats = load_chats()
    users = load_users()
    items = []
    total_unread = 0
    for key, ch in chats.items():
        msgs = ch.get("messages", [])
        if not msgs:
            continue
        last = msgs[-1]
        last_seen = ch.get("last_seen_admin", 0)
        unread = sum(1 for m in msgs if m.get("sender") == "user" and m.get("time", 0) > last_seen)
        total_unread += unread
        u = users.get(key, {})
        items.append({
            "key": key,
            "username": ch.get("username", key),
            "avatar": u.get("avatar", ""),
            "last_message": last.get("message", "") or "[صورة]",
            "last_sender": last.get("sender", ""),
            "last_time": last.get("time", 0),
            "unread": unread,
            "total": len(msgs)
        })
    items.sort(key=lambda x: x.get("last_time", 0), reverse=True)
    return render_template_string(CHATS_ADMIN_HTML, chats=items, total=len(items), total_unread=total_unread)


@app.route("/admin/chat/<username>")
@admin_required
def admin_chat_view(username):
    ch = get_chat(username)
    if not ch:
        return redirect(url_for("admin_tickets"))
    users = load_users()
    u = users.get(username.strip().lower(), {})
    mark_chat_read(username, "admin")
    return render_template_string(ADMIN_CHAT_HTML, chat=ch, user=u, username=ch.get("username", username))


@app.route("/admin/chat/<username>/reply", methods=["POST"])
@admin_required
def admin_chat_reply(username):
    message = request.form.get("message", "").strip()
    if message:
        add_chat_message(username, "admin", message)
        mark_chat_read(username, "admin")
    return redirect(url_for("admin_chat_view", username=username))


@app.route("/admin/chat/<username>/delete")
@admin_required
def admin_chat_delete(username):
    chats = load_chats()
    key = username.strip().lower()
    if key in chats:
        del chats[key]
        save_chats(chats)
    return redirect(url_for("admin_tickets"))

@app.route("/admin/tickets/reply", methods=["POST"])
@admin_required
def admin_tickets_reply():
    code = request.form.get("code", "").strip()
    message = request.form.get("message", "").strip()
    if code and message:
        add_reply(code, "admin", message)
    return redirect(url_for("admin_tickets"))

@app.route("/admin/tickets/delete/<code>")
@admin_required
def admin_tickets_delete(code):
    delete_ticket(code)
    return redirect(url_for("admin_tickets"))


# ═══ 📊 إحصائيات الزوار (SVG) ═══
import threading
STATS_FILE = os.path.join(_PERSIST_DIR, "stats.json")
_stats_lock = threading.Lock()

def _load_stats():
    try:
        with open(STATS_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
            if isinstance(d, dict):
                return d
    except Exception:
        pass
    return {"visits": 0, "days": {}, "platforms": {}, "countries": {}}

def _detect_device(ua):
    """يحدد نوع الجهاز والنظام والمتصفح والموديل من User-Agent"""
    ua_l = ua.lower()
    # النظام
    if "android" in ua_l: os_name = "Android"
    elif "iphone" in ua_l or "ipad" in ua_l or "ipod" in ua_l: os_name = "iOS"
    elif "windows" in ua_l: os_name = "Windows"
    elif "mac os" in ua_l or "macintosh" in ua_l: os_name = "macOS"
    elif "linux" in ua_l: os_name = "Linux"
    else: os_name = "أخرى"
    # نوع الجهاز
    if "mobile" in ua_l or "android" in ua_l or "iphone" in ua_l: device = "جوال"
    elif "ipad" in ua_l or "tablet" in ua_l: device = "تابلت"
    else: device = "كمبيوتر"
    # المتصفح
    if "chrome" in ua_l and "edg" not in ua_l and "opr" not in ua_l: browser = "Chrome"
    elif "firefox" in ua_l: browser = "Firefox"
    elif "safari" in ua_l and "chrome" not in ua_l: browser = "Safari"
    elif "edg" in ua_l: browser = "Edge"
    elif "opr" in ua_l or "opera" in ua_l: browser = "Opera"
    else: browser = "أخرى"

    # ═══ كشف الماركة والموديل ═══
    model = "غير معروف"
    # iPhone
    import re as _re2
    iphone_match = _re2.search(r'iPhone(?:\s*OS\s*[\d_]+)?', ua)
    if iphone_match:
        model = "iPhone"
    # iPad
    elif "ipad" in ua_l:
        model = "iPad"
    # Android - نستخرج الموديل
    elif "android" in ua_l:
        # النمط: Android X.X; BRAND MODEL Build
        m = _re2.search(r'Android[^;]*;\s*([^;)]+?)(?:\s+Build|\s*\))', ua)
        if m:
            model = m.group(1).strip()
            # تنظيف
            model = _re2.sub(r'\s+', ' ', model)
            # تصحيح أسماء ماركات شائعة
            model_l = model.lower()
            if model_l.startswith("sm-"): model = "Samsung " + model
            elif model_l.startswith("redmi"): model = "Xiaomi " + model
            elif model_l.startswith("mi "): model = "Xiaomi " + model
            elif model_l.startswith("m20") or model_l.startswith("m21"): model = "Samsung " + model
            elif model_l.startswith("huawei"): pass
            elif model_l.startswith("vivo"): pass
            elif model_l.startswith("oppo"): pass
        else:
            model = "Android"
    # Windows
    elif "windows" in ua_l:
        model = "Windows PC"
    # Mac
    elif "macintosh" in ua_l or "mac os" in ua_l:
        model = "Mac"
    # Linux
    elif "linux" in ua_l:
        model = "Linux PC"

    return device, os_name, browser, model

@app.route("/api/track", methods=["POST"])
def api_track():
    data = request.get_json(silent=True) or {}
    ev = str(data.get("ev", ""))[:20]
    uid = str(data.get("uid", ""))[:40]
    p = str(data.get("platform", ""))[:60]
    c = str(data.get("country", ""))[:60]
    ua = request.headers.get("User-Agent", "")[:300]
    with _stats_lock:
        d = _load_stats()
        day = time.strftime("%Y-%m-%d")
        dd = d["days"].setdefault(day, {"visits": 0, "uids": []})
        if ev == "visit":
            d["visits"] = d.get("visits", 0) + 1
            dd["visits"] = dd.get("visits", 0) + 1
            if uid and uid not in dd["uids"] and len(dd["uids"]) < 5000:
                dd["uids"].append(uid)
            # تتبع الأجهزة — مخفف للأداء
            try:
                device, os_name, browser, model = _detect_device(ua)
                dv = d.setdefault("devices", {})
                dv[device] = dv.get(device, 0) + 1
            except:
                pass
        elif ev == "platform" and p:
            pm = d.setdefault("platforms", {})
            pm[p] = pm.get(p, 0) + 1
        elif ev == "country" and p and c:
            k = p + " / " + c
            cm = d.setdefault("countries", {})
            cm[k] = cm.get(k, 0) + 1
        for k in sorted(d["days"].keys())[:-60]:
            del d["days"][k]
        try:
            with open(STATS_FILE, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False)
        except Exception:
            pass
    return jsonify({"ok": True})

CHATS_ADMIN_HTML = r"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<title>المحادثات</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;font-family:-apple-system,'Segoe UI',Tahoma,sans-serif;-webkit-tap-highlight-color:transparent}
body{background:#07070d;color:#e8e8f0;min-height:100vh;padding:0 0 30px;direction:rtl}
.hdr{position:sticky;top:0;z-index:100;background:linear-gradient(135deg,#0c0c18,#12122a);border-bottom:1px solid rgba(123,47,247,.25);padding:16px 18px;display:flex;align-items:center;gap:14px;box-shadow:0 4px 24px rgba(0,0,0,.4)}
.hdr .titles{flex:1;min-width:0}
.hdr h1{font-size:19px;font-weight:900;background:linear-gradient(135deg,#7b2ff7,#00d4ff);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.hdr .sub{font-size:11px;color:#6e6e8a;margin-top:3px;display:flex;align-items:center;gap:5px}
.hdr .sub .dot{width:6px;height:6px;border-radius:50%;background:#00d4a5;box-shadow:0 0 8px #00d4a5}
.hdr .back{padding:9px 14px;background:rgba(0,212,255,.12);border:1px solid rgba(0,212,255,.35);color:#00d4ff;border-radius:11px;font-size:12px;font-weight:700;text-decoration:none;display:flex;align-items:center;gap:6px}
.hdr .back svg{width:14px;height:14px;fill:currentColor}

.stats{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;padding:18px}
.stat{background:linear-gradient(160deg,#10101e,#0a0a14);border:1px solid rgba(123,47,247,.2);border-radius:18px;padding:16px 12px;text-align:center}
.stat b{font-size:26px;font-weight:900;display:block;margin-bottom:2px;background:linear-gradient(135deg,#00d4ff,#7b2ff7);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.stat.red b{background:linear-gradient(135deg,#e94560,#c62a47);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.stat span{font-size:11px;color:#6e6e8a}

.list{padding:0 18px}
.chat-card{background:linear-gradient(160deg,#10101e,#0a0a14);border:1px solid rgba(123,47,247,.18);border-radius:16px;padding:14px;margin-bottom:10px;display:flex;align-items:center;gap:12px;text-decoration:none;color:inherit;position:relative}
.chat-card.unread{border-color:rgba(233,69,96,.5);background:linear-gradient(160deg,#1a0e18,#100a12)}
.avatar{width:52px;height:52px;border-radius:50%;background:linear-gradient(135deg,#7b2ff7,#00d4ff);display:flex;align-items:center;justify-content:center;font-size:22px;font-weight:900;color:#fff;flex-shrink:0;overflow:hidden;position:relative}
.avatar img{width:100%;height:100%;object-fit:cover}
.avatar .badge{position:absolute;top:-2px;right:-2px;background:#e94560;color:#fff;font-size:10px;font-weight:800;min-width:20px;height:20px;border-radius:10px;padding:0 5px;display:flex;align-items:center;justify-content:center;border:2px solid #0a0a14}
.info{flex:1;min-width:0}
.uname{font-size:15px;font-weight:800;color:#e8e8f0;margin-bottom:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ulast{font-size:12px;color:#8e8eab;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:flex;gap:6px;align-items:center}
.ulast .who{color:#00d4ff;font-weight:700}
.ulast .who.admin{color:#7b2ff7}
.utime{font-size:10px;color:#6e6e8a;margin-top:4px}

.empty{text-align:center;padding:60px 20px;color:#6e6e8a;font-size:14px}
.empty svg{width:64px;height:64px;fill:#2a2a35;margin-bottom:16px;display:block;margin-left:auto;margin-right:auto}
</style>
</head>
<body>

<div class="hdr">
<svg width="46" height="46" viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg">
<defs><linearGradient id="cg1" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#7b2ff7"/><stop offset="100%" stop-color="#00d4ff"/></linearGradient></defs>
<path d="M8 8h32v22H18l-6 6V8z" fill="none" stroke="url(#cg1)" stroke-width="2" stroke-linejoin="round"/>
<circle cx="18" cy="18" r="2" fill="#00d4ff"/>
<circle cx="24" cy="18" r="2" fill="#00d4ff"/>
<circle cx="30" cy="18" r="2" fill="#00d4ff"/>
</svg>
<div class="titles">
<h1>المحادثات</h1>
<div class="sub"><span class="dot"></span> {{ total }} محادثة · {{ total_unread }} غير مقروءة</div>
</div>
<a href="/admin" class="back">
<svg viewBox="0 0 24 24"><path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z"/></svg>
الأدمن
</a>
</div>

<div class="stats">
<div class="stat"><b>{{ total }}</b><span>إجمالي المحادثات</span></div>
<div class="stat red"><b>{{ total_unread }}</b><span>رسائل غير مقروءة</span></div>
</div>

<div class="list">
{% if chats %}
{% for c in chats %}
<a href="/admin/chat/{{ c.key }}" class="chat-card {% if c.unread > 0 %}unread{% endif %}">
<div class="avatar">
{% if c.avatar %}
<img src="{{ c.avatar }}" alt="{{ c.username }}">
{% else %}
{{ c.username[0]|upper }}
{% endif %}
{% if c.unread > 0 %}
<div class="badge">{{ c.unread if c.unread < 10 else '9+' }}</div>
{% endif %}
</div>
<div class="info">
<div class="uname">{{ c.username }}</div>
<div class="ulast">
<span class="who {% if c.last_sender == 'admin' %}admin{% endif %}">
{% if c.last_sender == 'admin' %}أنت:{% else %}{{ c.username }}:{% endif %}
</span>
<span>{{ c.last_message }}</span>
</div>
<div class="utime">{{ c.last_time|timestamp }}</div>
</div>
</a>
{% endfor %}
{% else %}
<div class="empty">
<svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/></svg>
لا توجد محادثات بعد
</div>
{% endif %}
</div>

</body>
</html>"""


ADMIN_CHAT_HTML = r"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<title>محادثة {{ username }}</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;font-family:-apple-system,'Segoe UI',Tahoma,sans-serif}
html,body{height:100%;overflow:hidden}
body{background:#0a0a0f;color:#f5f5f7}
.chat-header{position:fixed;top:0;left:0;right:0;height:64px;background:#14141f;border-bottom:1px solid #2a2a35;display:flex;align-items:center;padding:0 12px;gap:10px;z-index:100}
.chat-header .back{width:42px;height:42px;border:none;background:transparent;cursor:pointer;display:flex;align-items:center;justify-content:center;border-radius:50%;flex-shrink:0;text-decoration:none}
.chat-header .back svg{width:24px;height:24px;fill:#0ea5e9}
.chat-header .avatar{width:44px;height:44px;border-radius:50%;background:linear-gradient(135deg,#7b2ff7,#00d4ff);display:flex;align-items:center;justify-content:center;flex-shrink:0;overflow:hidden;color:#fff;font-weight:900;font-size:18px}
.chat-header .avatar img{width:100%;height:100%;object-fit:cover}
.chat-header .info{flex:1;min-width:0}
.chat-header .info .name{font-size:15px;font-weight:700}
.chat-header .info .status{font-size:11px;color:#00b894;margin-top:2px}
.chat-header .del{width:40px;height:40px;background:rgba(233,69,96,.15);border:none;border-radius:10px;cursor:pointer;display:flex;align-items:center;justify-content:center;text-decoration:none;flex-shrink:0}
.chat-header .del svg{width:18px;height:18px;fill:#ff6b8a}
.chat-body{position:fixed;top:64px;bottom:70px;left:0;right:0;overflow-y:auto;padding:16px;background:#0a0a0f}
.msg-row{display:flex;margin-bottom:10px;width:100%}
.msg-row.user{justify-content:flex-start}
.msg-row.admin{justify-content:flex-end}
.bubble{max-width:75%;padding:10px 14px;border-radius:16px;font-size:14px;line-height:1.5;word-wrap:break-word}
.msg-row.user .bubble{background:#1e3a8a;color:#fff;border-bottom-left-radius:4px}
.msg-row.admin .bubble{background:#0088cc;color:#fff;border-bottom-right-radius:4px}
.bubble img,.bubble video{max-width:200px;border-radius:12px;margin-top:6px;display:block}
.bubble .meta{display:flex;align-items:center;gap:4px;justify-content:flex-end;margin-top:4px;font-size:10px;opacity:0.7;direction:ltr}
.bubble .meta svg{width:14px;height:14px;fill:currentColor}
.chat-input{position:fixed;bottom:0;left:0;right:0;height:70px;background:#14141f;border-top:1px solid #2a2a35;display:flex;align-items:center;padding:0 8px;gap:6px;z-index:100}
.chat-input input[type="text"]{flex:1;padding:12px 16px;border:1px solid #2a2a35;border-radius:24px;background:#0a0a0f;color:#f5f5f7;font-size:15px;outline:none;font-family:inherit;min-width:0}
.chat-input .send{width:48px;height:48px;border-radius:50%;background:linear-gradient(135deg,#1e3a8a,#0ea5e9);border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0}
.chat-input .send svg{width:24px;height:24px;fill:#fff}
.empty-chat{text-align:center;padding:60px 20px;color:#6e6e8a;font-size:13px}
</style>
</head>
<body>

<div class="chat-header">
<a href="/admin/tickets" class="back">
<svg viewBox="0 0 24 24"><path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z"/></svg>
</a>
<div class="avatar">
{% if user.avatar %}
<img src="{{ user.avatar }}" alt="{{ username }}">
{% else %}
{{ (username or 'U')[0]|upper }}
{% endif %}
</div>
<div class="info">
<div class="name">{{ username }}</div>
<div class="status">متصل الآن</div>
</div>
<a href="/admin/chat/{{ username|lower }}/delete" class="del" onclick="return confirm('حذف المحادثة كاملة؟')">
<svg viewBox="0 0 24 24"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>
</a>
</div>

<div class="chat-body" id="chatBody">
{% if not chat.messages %}
<div class="empty-chat">لا توجد رسائل بعد</div>
{% endif %}
{% for m in chat.messages %}
<div class="msg-row {{ m.sender }}">
<div class="bubble">
{% if m.media %}
  {% if m.media_type == 'video' %}
  <video src="/uploads/{{ m.media }}" controls></video>
  {% else %}
  <img src="/uploads/{{ m.media }}" alt="صورة">
  {% endif %}
{% else %}
  {{ m.message }}
{% endif %}
<div class="meta">
<span>{{ m.time|timestamp }}</span>
{% if m.sender == 'admin' %}
{% if chat.last_seen_user and chat.last_seen_user >= m.time %}
<svg viewBox="0 0 24 24" style="fill:#00d4ff;width:18px;height:18px"><path d="M18 7l-1.41-1.41-6.34 6.34 1.41 1.41L18 7zm4.24-1.41L11.66 16.17 7.48 12l-1.41 1.41L11.66 19l12-12-1.42-1.41zM.41 13.41L6 19l1.41-1.41L1.83 12 .41 13.41z"/></svg>
{% else %}
<svg viewBox="0 0 24 24" style="fill:currentColor;width:14px;height:14px"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>
{% endif %}
{% endif %}
</div>
</div>
</div>
{% endfor %}
</div>

<form method="POST" action="/admin/chat/{{ username|lower }}/reply" class="chat-input">
<input type="text" name="message" placeholder="اكتب ردك..." autocomplete="off" required>
<button type="submit" class="send">
<svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
</button>
</form>

<script>
document.addEventListener('DOMContentLoaded', function(){
    var body = document.getElementById('chatBody');
    if(body) body.scrollTop = body.scrollHeight;
});

// ═══ تحديث فوري لمحادثة الأدمن ═══
(function(){
    var lastTime = Math.floor(Date.now() / 1000);
    var busy = false;
    function esc(t){ var d = document.createElement('div'); d.textContent = t || ''; return d.innerHTML; }
    function addMsg(m){
        var list = document.getElementById('chatBody');
        if(!list) return;
        var isMine = (m.sender === 'admin');
        var mediaHtml = '';
        if(m.media){
            mediaHtml = m.media_type === 'video'
                ? '<video src="/uploads/' + esc(m.media) + '" controls></video>'
                : '<img src="/uploads/' + esc(m.media) + '" alt="">';
        }
        var bodyText = m.media ? mediaHtml : esc(m.message);
        var t = new Date((m.time || 0) * 1000);
        var hh = ('0' + t.getHours()).slice(-2);
        var mm = ('0' + t.getMinutes()).slice(-2);
        var row = document.createElement('div');
        row.className = 'msg-row ' + (isMine ? 'admin' : 'user');
        row.innerHTML = '<div class="bubble">' + bodyText +
            '<div class="meta"><span>' + hh + ':' + mm + '</span></div></div>';
        var empty = list.querySelector('.empty-chat');
        if(empty) empty.remove();
        list.appendChild(row);
        list.scrollTop = list.scrollHeight;
        if(!isMine && navigator.vibrate) try { navigator.vibrate([80,40,80]); } catch(e){}
    }
    function poll(){
        if(document.hidden || busy) return;
        busy = true;
        fetch('/api/chat/since/' + lastTime + '?t=' + Date.now(), {cache: 'no-store'})
            .then(function(r){ return r.ok ? r.json() : null; })
            .then(function(d){
                busy = false;
                if(!d || !d.messages) return;
                d.messages.forEach(function(m){
                    addMsg(m);
                    if(m.time && m.time > lastTime) lastTime = Math.floor(m.time);
                });
            })
            .catch(function(){ busy = false; });
    }
    setTimeout(poll, 2000);
    setInterval(poll, 2500);
})();
</script>
</body>
</html>"""


USERS_ADMIN_HTML = r"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<title>المستخدمون</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;font-family:-apple-system,'Segoe UI',Tahoma,sans-serif;-webkit-tap-highlight-color:transparent}
body{background:#07070d;color:#e8e8f0;min-height:100vh;padding:0 0 30px;direction:rtl}
.hdr{position:sticky;top:0;z-index:100;background:linear-gradient(135deg,#0c0c18,#12122a);border-bottom:1px solid rgba(123,47,247,.25);padding:16px 18px;display:flex;align-items:center;gap:14px;box-shadow:0 4px 24px rgba(0,0,0,.4)}
.hdr .logo{width:46px;height:46px;flex-shrink:0}
.hdr .titles{flex:1;min-width:0}
.hdr h1{font-size:19px;font-weight:900;background:linear-gradient(135deg,#7b2ff7,#00d4ff);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.hdr .sub{font-size:11px;color:#6e6e8a;margin-top:3px;display:flex;align-items:center;gap:5px}
.hdr .sub .dot{width:6px;height:6px;border-radius:50%;background:#00d4a5;box-shadow:0 0 8px #00d4a5}
.hdr .back{padding:9px 14px;background:rgba(0,212,255,.12);border:1px solid rgba(0,212,255,.35);color:#00d4ff;border-radius:11px;font-size:12px;font-weight:700;text-decoration:none;display:flex;align-items:center;gap:6px}
.hdr .back svg{width:14px;height:14px;fill:currentColor}

.stats{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;padding:18px}
.stat{background:linear-gradient(160deg,#10101e,#0a0a14);border:1px solid rgba(123,47,247,.2);border-radius:18px;padding:16px 12px;text-align:center}
.stat b{font-size:26px;font-weight:900;display:block;margin-bottom:2px;background:linear-gradient(135deg,#00d4ff,#7b2ff7);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.stat span{font-size:11px;color:#6e6e8a}

.list{padding:0 18px}
.user-card{background:linear-gradient(160deg,#10101e,#0a0a14);border:1px solid rgba(123,47,247,.18);border-radius:16px;padding:14px;margin-bottom:10px;display:flex;align-items:center;gap:12px}
.avatar{width:48px;height:48px;border-radius:50%;background:linear-gradient(135deg,#7b2ff7,#00d4ff);display:flex;align-items:center;justify-content:center;font-size:20px;font-weight:900;color:#fff;flex-shrink:0;overflow:hidden}
.avatar img{width:100%;height:100%;object-fit:cover}
.info{flex:1;min-width:0}
.uname{font-size:15px;font-weight:800;color:#e8e8f0;margin-bottom:4px;word-break:break-all}
.umeta{font-size:11px;color:#6e6e8a;line-height:1.6}
.umeta b{color:#00d4ff}
.upw{display:flex;align-items:center;gap:6px;margin-top:8px;padding:8px 10px;background:rgba(0,212,255,.06);border:1px solid rgba(0,212,255,.2);border-radius:10px;font-size:11px;flex-wrap:wrap}
.upw-lbl{color:#00d4ff;font-weight:700}
.upw-val{flex:1;font-family:monospace;direction:ltr;color:#fff;font-size:12px;word-break:break-all;user-select:all;min-width:80px}
.upw-copy{background:rgba(0,212,255,.15);border:1px solid rgba(0,212,255,.3);color:#00d4ff;padding:4px 10px;border-radius:8px;font-size:10px;cursor:pointer;font-family:inherit;font-weight:700}
.upw-copy:active{background:rgba(0,212,255,.3)}
.upw-box{margin-top:8px;display:flex;flex-direction:column;gap:6px}
.upw-toggle{background:rgba(0,212,255,.1);border:1px solid rgba(0,212,255,.25);color:#00d4ff;padding:6px 12px;border-radius:8px;font-size:11px;font-weight:700;cursor:pointer;font-family:inherit;display:flex;align-items:center;gap:6px;width:fit-content}
.upw-toggle:active{background:rgba(0,212,255,.2)}
.upw-hidden{display:flex;align-items:center;gap:8px;background:rgba(123,47,247,.1);border:1px solid rgba(123,47,247,.3);padding:8px 12px;border-radius:10px}
.upw-val{font-family:monospace;direction:ltr;color:#fff;font-size:13px;font-weight:700;flex:1;word-break:break-all;user-select:all}
.upw-copy{background:rgba(123,47,247,.2);border:1px solid rgba(123,47,247,.4);color:#c8a2ff;padding:4px 10px;border-radius:7px;font-size:10px;font-weight:700;cursor:pointer;font-family:inherit}
.upw-copy:active{background:rgba(123,47,247,.4)}
.upw-box{margin-top:8px;display:flex;flex-direction:column;gap:6px}
.upw-toggle{background:rgba(0,212,255,.1);border:1px solid rgba(0,212,255,.25);color:#00d4ff;padding:6px 12px;border-radius:8px;font-size:11px;font-weight:700;cursor:pointer;font-family:inherit;display:flex;align-items:center;gap:6px;width:fit-content}
.upw-toggle:active{background:rgba(0,212,255,.2)}
.upw-hidden{display:flex;align-items:center;gap:8px;background:rgba(123,47,247,.1);border:1px solid rgba(123,47,247,.3);padding:8px 12px;border-radius:10px}
.upw-val{font-family:monospace;direction:ltr;color:#fff;font-size:13px;font-weight:700;flex:1;word-break:break-all;user-select:all}
.upw-copy{background:rgba(123,47,247,.2);border:1px solid rgba(123,47,247,.4);color:#c8a2ff;padding:4px 10px;border-radius:7px;font-size:10px;font-weight:700;cursor:pointer;font-family:inherit}
.upw-copy:active{background:rgba(123,47,247,.4)}
.del-btn{width:40px;height:40px;background:rgba(233,69,96,.15);border:1px solid rgba(233,69,96,.3);color:#ff6b8a;border-radius:11px;text-decoration:none;display:flex;align-items:center;justify-content:center;flex-shrink:0}
.del-btn svg{width:18px;height:18px;fill:currentColor}

.empty{text-align:center;padding:60px 20px;color:#6e6e8a;font-size:14px}
.empty svg{width:64px;height:64px;fill:#2a2a35;margin-bottom:16px;display:block;margin-left:auto;margin-right:auto}

.search{padding:0 18px 14px}
.search input{width:100%;padding:13px 16px;border:1px solid rgba(123,47,247,.25);border-radius:14px;background:rgba(0,0,0,.4);color:#fff;font-size:14px;outline:none;font-family:inherit}
.search input:focus{border-color:#00d4ff}
</style>
</head>
<body>

<div class="hdr">
<svg class="logo" viewBox="0 0 48 48">
<defs>
<linearGradient id="gA" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#7b2ff7"/><stop offset="100%" stop-color="#00d4ff"/></linearGradient>
<linearGradient id="gB" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#00d4ff"/><stop offset="100%" stop-color="#00b894"/></linearGradient>
</defs>
<circle cx="24" cy="24" r="20" fill="none" stroke="url(#gA)" stroke-width="1.5" opacity="0.4"/>
<circle cx="18" cy="19" r="4" fill="url(#gB)"/>
<circle cx="30" cy="19" r="4" fill="url(#gB)"/>
<path d="M10 36 Q 24 44 38 36" stroke="url(#gA)" stroke-width="2.5" fill="none" stroke-linecap="round"/>
</svg>
<div class="titles">
<h1>المستخدمون المسجلون</h1>
<div class="sub"><span class="dot"></span> إجمالي: {{ total }} مستخدم</div>
</div>
<a href="/admin" class="back">
<svg viewBox="0 0 24 24"><path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z"/></svg>
الأدمن
</a>
</div>

<div class="stats">
<div class="stat"><b>{{ total }}</b><span>إجمالي المستخدمين</span></div>
<div class="stat"><b>{{ total }}</b><span>حسابات نشطة</span></div>
</div>

<div class="search">
<input type="text" id="searchBox" placeholder="ابحث عن مستخدم..." oninput="filterUsers(this.value)">
</div>

<div class="list" id="usersList">
{% if users %}
{% for u in users %}
<div class="user-card" data-name="{{ u.username|lower }}">
<div class="avatar">
{% if u.avatar %}
<img src="{{ u.avatar }}" alt="{{ u.username }}">
{% else %}
{{ u.username[0]|upper }}
{% endif %}
</div>
<div class="info">
<div class="uname">{{ u.username }}</div>
<div class="umeta">
انضم: <b>{{ u.created|timestamp }}</b> · آخر دخول: <b>{{ u.last_login|timestamp }}</b>
</div>
{% if u.password_plain %}
<div class="upw">
<span class="upw-lbl"><svg viewBox="0 0 24 24" style="width:14px;height:14px;fill:#f59e0b;vertical-align:middle;margin-left:4px"><path d="M12.65 10C11.83 7.67 9.61 6 7 6c-3.31 0-6 2.69-6 6s2.69 6 6 6c2.61 0 4.83-1.67 5.65-4H17v4h4v-4h2v-4H12.65zM7 14c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2z"/></svg> كلمة السر:</span>
<code class="upw-val">{{ u.password_plain }}</code>
<button class="upw-copy" onclick="copyPw(this, '{{ u.password_plain }}')">نسخ</button>
</div>
{% endif %}
</div>
<a href="/admin/users/delete/{{ u.key }}" class="del-btn" onclick="return confirm('حذف المستخدم {{ u.username }}؟')">
<svg viewBox="0 0 24 24"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>
</a>
</div>
{% endfor %}
{% else %}
<div class="empty">
<svg viewBox="0 0 24 24"><path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z"/></svg>
لا يوجد مستخدمون مسجلون بعد
</div>
{% endif %}
</div>

<script>
function togglePw(btn){
    var box = btn.parentElement.querySelector('.upw-hidden');
    if(box.style.display === 'none'){
        box.style.display = 'flex';
        btn.querySelector('span').textContent = 'إخفاء';
    } else {
        box.style.display = 'none';
        btn.querySelector('span').textContent = 'كلمة السر';
    }
}
function copyPw(btn, pw){
    navigator.clipboard.writeText(pw).then(function(){
        var old = btn.textContent;
        btn.textContent = '✓';
        setTimeout(function(){ btn.textContent = old; }, 1200);
    }).catch(function(){});
}
function filterUsers(q){
    q = q.trim().toLowerCase();
    document.querySelectorAll('.user-card').forEach(function(c){
        var n = c.dataset.name || '';
        c.style.display = (!q || n.indexOf(q) > -1) ? '' : 'none';
    });
}
</script>
</body>
</html>"""


STATS_HTML = r"""<!DOCTYPE html>
<html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>الإحصائيات</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;font-family:-apple-system,'Segoe UI',Tahoma,sans-serif}
body{background:#0a0a0f;color:#f5f5f7;padding:16px;max-width:560px;margin:0 auto}
h1{font-size:20px;margin:8px 0 16px;display:flex;align-items:center;gap:10px}
h1 svg{width:24px;height:24px;fill:#0ea5e9}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:16px}
.box{background:#16161f;border:1px solid #2a2a35;border-radius:16px;padding:14px;text-align:center}
.box b{display:block;font-size:26px;margin-bottom:4px}
.box span{font-size:12px;color:#8e8e93}
h2{font-size:14px;color:#8e8e93;margin:16px 0 8px;display:flex;align-items:center;gap:8px}
h2 svg{width:16px;height:16px;fill:#8e8e93}
.row{display:flex;justify-content:space-between;background:#16161f;border:1px solid #2a2a35;border-radius:12px;padding:10px 14px;margin-bottom:6px;font-size:14px}
a{color:#0ea5e9;text-decoration:none;display:inline-flex;align-items:center;gap:6px}
a svg{width:16px;height:16px;fill:currentColor}
</style></head><body>
<a href="/admin"><svg viewBox="0 0 24 24"><path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z"/></svg> الأدمن</a>
<h1><svg viewBox="0 0 24 24"><path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zM9 17H7v-7h2v7zm4 0h-2V7h2v10zm4 0h-2v-4h2v4z"/></svg> إحصائيات الموقع</h1>
<div class="grid">
<div class="box"><b>{{ total }}</b><span>إجمالي الزيارات</span></div>
<div class="box"><b>{{ today }}</b><span>زيارات اليوم</span></div>
<div class="box"><b>{{ today_u }}</b><span>زوار اليوم (فريدون)</span></div>
<div class="box"><b>{{ week_u }}</b><span>زوار آخر 7 أيام</span></div>
</div>
<h2><svg viewBox="0 0 24 24"><path d="M16 6l2.29 2.29-4.88 4.88-4-4L2 16.59 3.41 18l6-6 4 4 6.3-6.29L22 12V6z"/></svg> أكثر المنصات استخداماً</h2>
{% for n, v in top_p %}<div class="row"><span>{{ n }}</span><b>{{ v }}</b></div>{% else %}<div class="row">لا توجد بيانات</div>{% endfor %}
<h2><svg viewBox="0 0 24 24"><path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z"/></svg> أكثر الدول استخداماً</h2>
{% for n, v in top_c %}<div class="row"><span>{{ n }}</span><b>{{ v }}</b></div>{% else %}<div class="row">لا توجد بيانات</div>{% endfor %}
<h2><svg viewBox="0 0 24 24"><path d="M17 1.01L7 1c-1.1 0-2 .9-2 2v18c0 1.1.9 2 2 2h10c1.1 0 2-.9 2-2V3c0-1.1-.9-1.99-2-1.99zM17 19H7V5h10v14z"/></svg> نوع الأجهزة</h2>
{% for n, v in top_d %}<div class="row"><span>{{ n }}</span><b>{{ v }}</b></div>{% else %}<div class="row">لا توجد بيانات</div>{% endfor %}

<h2><svg viewBox="0 0 24 24"><path d="M20 18c1.1 0 1.99-.9 1.99-2L22 6c0-1.1-.9-2-2-2H4c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2H0v2h24v-2h-4zM4 6h16v10H4V6z"/></svg> أنظمة التشغيل</h2>
{% for n, v in top_os %}<div class="row"><span>{{ n }}</span><b>{{ v }}</b></div>{% else %}<div class="row">لا توجد بيانات</div>{% endfor %}

<h2><svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z"/></svg> المتصفحات</h2>
{% for n, v in top_br %}<div class="row"><span>{{ n }}</span><b>{{ v }}</b></div>{% else %}<div class="row">لا توجد بيانات</div>{% endfor %}

<h2><svg viewBox="0 0 24 24"><path d="M17 1.01L7 1c-1.1 0-2 .9-2 2v18c0 1.1.9 2 2 2h10c1.1 0 2-.9 2-2V3c0-1.1-.9-1.99-2-1.99zM17 19H7V5h10v14zm-8-3h6v2H9v-2z"/></svg> أجهزة المستخدمين</h2>
{% for n, v in top_m %}<div class="row"><span>{{ n }}</span><b>{{ v }}</b></div>{% else %}<div class="row">لا توجد بيانات</div>{% endfor %}

<h2><svg viewBox="0 0 24 24"><path d="M11.99 2C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2zM12 20c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8zm.5-13H11v6l5.25 3.15.75-1.23-4.5-2.67z"/></svg> آخر 7 أيام</h2>
{% for d, v, u in rows %}<div class="row"><span>{{ d }}</span><span>{{ v }} زيارة · {{ u }} زائر</span></div>{% endfor %}

</body></html>"""

@app.route("/admin/api/chart-data")
@admin_required
def admin_chart_data():
    d = _load_stats()
    days_dict = d.get("days", {})
    # آخر 7 أيام
    from datetime import datetime, timedelta
    out_days = []
    for i in range(6, -1, -1):
        day = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        v = days_dict.get(day, {}).get("visits", 0)
        out_days.append({"label": day[5:], "value": v})
    today = days_dict.get(datetime.now().strftime("%Y-%m-%d"), {}).get("visits", 0)
    return jsonify({"days": out_days, "total": d.get("visits", 0), "today": today})

@app.route("/admin/users")
@admin_required
def admin_users():
    users = load_users()
    # رتب حسب تاريخ الإنشاء
    users_list = []
    for key, u in users.items():
        users_list.append({
            "key": key,
            "username": u.get("username", key),
            "created": u.get("created", 0),
            "last_login": u.get("last_login", 0),
            "visits": u.get("visits", 0),
            "avatar": u.get("avatar", ""),
            "password_plain": u.get("password_plain", "")
        })
    users_list.sort(key=lambda x: x.get("created", 0), reverse=True)
    return render_template_string(USERS_ADMIN_HTML, users=users_list, total=len(users_list))


@app.route("/admin/users/delete/<key>")
@admin_required
def admin_users_delete(key):
    db_delete_user(key)
    return redirect(url_for("admin_users"))


@app.route("/admin/stats")
@admin_required
def admin_stats():
    d = _load_stats()
    days = d.get("days", {})
    t = days.get(time.strftime("%Y-%m-%d"), {"visits": 0, "uids": []})
    last7 = sorted(days.keys())[-7:]
    uniq = set()
    for k in last7:
        uniq.update(days[k].get("uids", []))
    top = lambda m: sorted(m.items(), key=lambda x: -x[1])[:10]
    rows = [(k, days[k].get("visits", 0), len(days[k].get("uids", []))) for k in reversed(last7)]
    return render_template_string(STATS_HTML, total=d.get("visits", 0), today=t.get("visits", 0),
        today_u=len(t.get("uids", [])), week_u=len(uniq), top_p=top(d.get("platforms", {})),
        top_c=top(d.get("countries", {})), rows=rows,
        top_d=top(d.get("devices", {})),
        top_os=top(d.get("os", {})),
        top_br=top(d.get("browsers", {})),
        top_m=top(d.get("models", {})))


# ---- Push Notifications ----

import subprocess as _subprocess
import re as _re_tunnel
import threading as _th_tunnel

_public_url = {"url": ""}

def start_cloudflare_tunnel(port=5000):
    """يشغل cloudflared tunnel ويعرض الرابط"""
    def _run():
        try:
            proc = _subprocess.Popen(
                ["cloudflared", "tunnel", "--url", "http://127.0.0.1:" + str(port),
                 "--protocol", "http2", "--no-autoupdate"],
                stdout=_subprocess.PIPE,
                stderr=_subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            url_found = False
            for line in iter(proc.stdout.readline, ""):
                # ابحث عن الرابط
                m = _re_tunnel.search(r'https://[a-z0-9\-]+\.trycloudflare\.com', line)
                if m and not url_found:
                    url = m.group(0)
                    _public_url["url"] = url
                    url_found = True
                    # اطبع الرابط بلون مميز
                    print("")
                    print("\033[38;5;48m\033[1m  ╔══════════════════════════════════════════════════╗\033[0m")
                    print("\033[38;5;48m\033[1m  ║  🌐  الرابط العام (استخدمه من أي جوال):           ║\033[0m")
                    print("\033[38;5;48m\033[1m  ╚══════════════════════════════════════════════════╝\033[0m")
                    print("")
                    print("\033[38;5;51m\033[1m     " + url + "\033[0m")
                    print("")
                    print("\033[38;5;220m     🔓  لوحة الأدمن: " + url + "/admin\033[0m")
                    print("\033[38;5;213m     🔑  كلمة السر: admin2025\033[0m")
                    print("")
                    print("\033[38;5;245m     ⚠️  الرابط يتغير في كل تشغيل — انسخه الآن\033[0m")
                    print("")
        except FileNotFoundError:
            print("\033[38;5;203m⚠️  cloudflared غير مثبت — التثبيت: pkg install cloudflared\033[0m")
        except Exception as e:
            print("\033[38;5;203m⚠️  خطأ tunnel: " + str(e) + "\033[0m")

    import threading as _th
    t = _th.Thread(target=_run, daemon=True)
    t.start()
    return t


# speed-boost: ضغط gzip + كاش القوالب + كاش الصور + تصغير الصور الشخصية
import gzip as _gzip
import threading as _sb_thr
from functools import lru_cache as _lru
_orig_from_string = app.jinja_env.from_string
@_lru(maxsize=64)
def _tpl_cached(src):
    return _orig_from_string(src)
def _from_string_cached(source, *a, **k):
    if a or k or not isinstance(source, str):
        return _orig_from_string(source, *a, **k)
    return _tpl_cached(source)
app.jinja_env.from_string = _from_string_cached

_SB_LOCK = _sb_thr.Lock()
_SB_WARNED = [False]
def _shrink_avatar(path, max_side=512, min_bytes=120 * 1024):
    try:
        if os.path.getsize(path) < min_bytes:
            return
        try:
            from PIL import Image, ImageOps
        except ImportError:
            if not _SB_WARNED[0]:
                _SB_WARNED[0] = True
                print("speed-boost: لتصغير الصور ثبّت: pkg install python-pillow")
            return
        with _SB_LOCK:
            if os.path.getsize(path) < min_bytes:
                return
            ext = path.rsplit(".", 1)[-1].lower()
            if ext == "gif":
                return
            im = Image.open(path)
            im = ImageOps.exif_transpose(im)
            im.thumbnail((max_side, max_side))
            tmp = path + ".tmp"
            if ext in ("jpg", "jpeg"):
                im.convert("RGB").save(tmp, "JPEG", quality=82, optimize=True)
            elif ext == "png":
                im.save(tmp, "PNG", optimize=True)
            else:
                im.save(tmp, "WEBP", quality=82)
            os.replace(tmp, path)
    except Exception as e:
        print("speed-boost avatar:", e)

@app.before_request
def _sb_avatar_before():
    p = request.path
    if p.startswith("/uploads/av_"):
        fn = p[len("/uploads/"):]
        if "/" not in fn and ".." not in fn:
            _shrink_avatar(os.path.join(UPLOAD_FOLDER, fn))

@app.after_request
def _slow_net_boost(resp):
    # ضغط HTML تلقائي
    try:
        if resp.status_code == 200 and request.method == "GET":
            ct = (resp.headers.get("Content-Type") or "").lower()
            # ضغط HTML
            if ct.startswith("text/html"):
                if "Content-Encoding" not in resp.headers:
                    accept_enc = request.headers.get("Accept-Encoding", "").lower()
                    if "gzip" in accept_enc:
                        data = resp.get_data()
                        if len(data) > 500:
                            import gzip as _gz
                            resp.set_data(_gz.compress(data, 6))
                            resp.headers["Content-Encoding"] = "gzip"
                            resp.headers["Vary"] = "Accept-Encoding"
                            try:
                                resp.headers["Content-Length"] = str(len(resp.get_data()))
                            except Exception:
                                pass
            # cache أقوى للملفات الثابتة
            p = request.path
            if p.startswith("/static/") or p.startswith("/uploads/"):
                if "Cache-Control" not in resp.headers:
                    resp.headers["Cache-Control"] = "public, max-age=604800, immutable"
    except Exception as e:
        pass
    return resp


@app.after_request
def _no_cache_admin(resp):
    try:
        if request.path.startswith("/admin") or request.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            resp.headers["Pragma"] = "no-cache"
            resp.headers["Expires"] = "0"
    except Exception:
        pass
    return resp

_SB_COMPRESSIBLE = ("text/", "application/json", "application/javascript", "image/svg+xml", "application/manifest+json")
@app.after_request
def _sb_after(resp):
    try:
        p = request.path
        if resp.status_code == 200 and request.method == "GET":
            if p.startswith("/uploads/"):
                resp.headers["Cache-Control"] = "public, max-age=2592000"
            elif p in ("/icon-192.png", "/icon-512.png", "/manifest.json"):
                resp.headers["Cache-Control"] = "public, max-age=86400"
        ct = (resp.headers.get("Content-Type") or "").lower()
        if (resp.status_code == 200 and not resp.direct_passthrough
                and "Content-Encoding" not in resp.headers
                and "gzip" in request.headers.get("Accept-Encoding", "").lower()
                and ct.startswith(_SB_COMPRESSIBLE)):
            data = resp.get_data()
            if len(data) > 1024:
                resp.set_data(_gzip.compress(data, 5))
                resp.headers["Content-Encoding"] = "gzip"
                resp.headers["Vary"] = "Accept-Encoding"
                resp.headers["Content-Length"] = str(len(resp.get_data()))
    except Exception as e:
        print("speed-boost:", e)
    return resp


# ═══════════════════════════════════════════
# PUSH ROUTES
# ═══════════════════════════════════════════
@app.route("/api/push/public-key")
def api_push_public_key():
    return jsonify({"public_key": _vapid.get("public_key", "")})

@app.route("/api/push/subscribe", methods=["POST"])
def api_push_subscribe():
    data = request.get_json(silent=True) or {}
    sub = data.get("subscription")
    if not sub or not sub.get("endpoint"):
        return jsonify({"ok": False, "error": "no sub"}), 400
    added = _add_sub(sub)
    return jsonify({"ok": True, "new": added})

@app.route("/api/push/unsubscribe", methods=["POST"])
def api_push_unsubscribe():
    data = request.get_json(silent=True) or {}
    ep = data.get("endpoint", "")
    if not ep:
        return jsonify({"ok": False, "error": "no ep"}), 400
    _remove_sub(ep)
    return jsonify({"ok": True})

@app.route("/api/push/test")
@admin_required
def api_push_test():
    n = send_push_to_all("اختبار من الموقع", "الإشعارات شغالة!", "/")
    return jsonify({"ok": True, "sent": n, "total": len(_load_subs())})

@app.route("/api/push/stats")
@admin_required
def api_push_stats():
    return jsonify({
        "ready": _PUSH_READY,
        "subs": len(_load_subs()),
        "has_vapid": bool(_vapid.get("public_key"))
    })

# ═══════════════════════════════════════════


# ═══════════════════════════════════════════
# PUSH — إرسال مخصص
# ═══════════════════════════════════════════
@app.route("/api/push/subs-list")
@admin_required
def api_push_subs_list():
    subs = _load_subs()
    out = []
    for i, s in enumerate(subs):
        ep = s.get("endpoint", "")
        out.append({
            "index": i,
            "endpoint": ep,
            "endpoint_short": (ep[:50] + "...") if len(ep) > 50 else ep
        })
    return jsonify({"subs": out, "count": len(out)})


@app.route("/api/push/send-custom", methods=["POST"])
@admin_required
def api_push_send_custom():
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()[:100]
    body = (data.get("body") or "").strip()[:300]
    url = (data.get("url") or "/").strip()[:500]
    icon_svg = (data.get("icon_svg") or "").strip()[:20000]
    icon_url = (data.get("icon_url") or "").strip()[:500]
    tag = (data.get("tag") or "").strip()[:50]
    target = (data.get("target_endpoint") or "").strip()

    if not title and not body:
        return jsonify({"ok": False, "error": "لازم عنوان أو نص"}), 400

    n = send_push_to_all(
        title=title or "إشعار جديد",
        body=body or "",
        url=url or "/",
        icon_svg=icon_svg,
        icon_url=icon_url,
        tag=tag,
        target_endpoint=target
    )

    return jsonify({"ok": True, "sent": n, "total": len(_load_subs())})


@app.route("/api/push/preview-svg", methods=["POST"])
@admin_required
def api_push_preview_svg():
    data = request.get_json(silent=True) or {}
    svg = (data.get("svg") or "").strip()
    if not svg:
        return jsonify({"ok": False, "error": "no svg"}), 400
    try:
        import cairosvg
        import base64
        png_bytes = cairosvg.svg2png(
            bytestring=svg.encode("utf-8"),
            output_width=96,
            output_height=96
        )
        b64 = base64.b64encode(png_bytes).decode()
        return jsonify({"ok": True, "data_url": "data:image/png;base64," + b64})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


# ═══════════════════════════════════════════


@app.route("/explore")
def explore_page():
    if not session.get("user_logged") and not session.get("admin_logged"):
        return redirect(url_for("login_page"))
    s = load_settings()
    users = load_users()
    codes = load_codes()
    try:
        contests = contests_list(only_active=True)
    except Exception:
        contests = []
    username = (session.get("user_name") or "").strip()
    if not username and session.get("admin_logged"):
        username = "admin"
    u = users.get(username.lower(), {})
    user_avatar = u.get("avatar", "")
    # اجمع كل مشاركات المستخدم
    user_voters = []
    try:
        all_c = contests_list(only_active=False)
        uname_low = username.lower()
        for c in all_c:
            try:
                voters = json.loads(c.get("voters") or "[]")
            except:
                voters = []
            if uname_low in voters:
                user_voters.append(c)
    except:
        pass
    try:
        ads = ads_list(only_active=True)
    except Exception:
        ads = []
    # جلب المنشورات الاجتماعية + ربط المستخدمين
    social_posts = []
    try:
        posts_raw = social_post_list(only_active=True, limit=50)
        me_low = (username or "").strip().lower()
        if not me_low and session.get("admin_logged"):
            me_low = "admin"
        for p in posts_raw:
            u_author = users.get((p.get("author") or "").lower(), {})
            try:
                reacts = social_reactions_summary(p["id"])
            except:
                reacts = {"like":0,"love":0,"haha":0,"wow":0,"sad":0,"angry":0}
            my_react = None
            try:
                if me_low:
                    my_react = social_user_reaction(p["id"], me_low)
            except:
                pass
            p["author_display"] = u_author.get("username", p.get("author", ""))
            p["author_avatar"] = u_author.get("avatar", "")
            p["reactions"] = reacts
            p["my_reaction"] = my_react
            # احسب إجمالي الإعجابات
            try:
                p["likes_count"] = sum(reacts.values())
            except:
                p["likes_count"] = 0
            social_posts.append(p)
    except Exception as _se:
        print("[SOCIAL] err:", _se)
    return render_template_string(
        EXPLORE_HTML,
        site_name=s.get("site_name", "المطري OTP"),
        users_count=len(users),
        codes_count=len(codes),
        contests=contests,
        ads=ads,
        social_posts=social_posts,
        now=time.time(),
        user_name=username,
        user_avatar=user_avatar,
        user_voters=user_voters
    )


@app.route("/explore/vote/<int:cid>/<int:idx>", methods=["POST"])
def explore_vote(cid, idx):
    if not session.get("user_logged") and not session.get("admin_logged"):
        return jsonify({"ok": False, "error": "login"}), 401
    user_key = (session.get("user_name") or session.get("admin_logged") and "admin" or "").strip().lower()
    if not user_key:
        return jsonify({"ok": False, "error": "no user"}), 401
    ok, msg = contests_vote(cid, user_key, idx)
    return jsonify({"ok": ok, "msg": msg})


EXPLORE_HTML = r"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<meta name="theme-color" content="#7b2ff7">
<title>استكشف</title>
<script>
// كشف الجهاز الضعيف — يشتغل قبل تحميل CSS
(function(){
    try {
        var weak = false;
        var cores = navigator.hardwareConcurrency || 2;
        var mem = navigator.deviceMemory || 2;
        var w = window.innerWidth;
        var ua = navigator.userAgent.toLowerCase();
        // جهاز ضعيف
        if(cores <= 4) weak = true;
        if(mem <= 2) weak = true;
        if(w < 380) weak = true;
        // احترام اختيار المستخدم اليدوي
        var forced = localStorage.getItem('lite_mode');
        if(forced === '1') weak = true;
        if(forced === '0') weak = false;
        // طبق
        if(weak){
            document.documentElement.classList.add('lite-mode');
        }
    } catch(e){}
})();
</script>
<style>
*{margin:0;padding:0;box-sizing:border-box;font-family:-apple-system,'Segoe UI',Tahoma,sans-serif;-webkit-tap-highlight-color:transparent}
body{background:#07070d;color:#e8e8f0;min-height:100vh;padding:0 0 46px;direction:rtl}

.hdr{position:sticky;top:0;z-index:100;background:linear-gradient(135deg,#0c0c18,#12122a);border-bottom:1px solid rgba(123,47,247,.25);padding:14px 16px;display:flex;align-items:center;gap:12px;box-shadow:0 4px 24px rgba(0,0,0,.4)}
.hdr .back{width:40px;height:40px;border:none;background:rgba(0,212,255,.12);border:1px solid rgba(0,212,255,.3);border-radius:12px;cursor:pointer;display:flex;align-items:center;justify-content:center;text-decoration:none;flex-shrink:0}
.hdr .back svg{width:22px;height:22px;fill:#00d4ff}
.hdr h1{font-size:18px;font-weight:900;background:linear-gradient(135deg,#fff,#a8d8ff);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;flex:1}

.tabs{display:flex;gap:6px;padding:14px 16px 4px;overflow-x:auto;scrollbar-width:none;-webkit-overflow-scrolling:touch}
.tabs::-webkit-scrollbar{display:none}
.tab{flex:1;padding:12px 10px;min-width:80px;border-radius:14px;border:1.5px solid rgba(123,47,247,.2);background:rgba(255,255,255,.03);color:#8e8eab;font-size:13px;font-weight:800;cursor:pointer;font-family:inherit;white-space:nowrap;transition:all .25s;display:flex;align-items:center;justify-content:center;gap:8px}
.tab svg{width:18px;height:18px;fill:currentColor}
.tab.active{background:linear-gradient(135deg,#00d4ff,#0099cc);border-color:transparent;color:#fff;box-shadow:0 6px 20px rgba(0,212,255,.4);transform:translateY(-1px)}
.tab:active{transform:scale(.96)}

.wrap{padding:16px 16px 60px}

.pane{display:none;animation:fadeIn .3s}
.pane.active{display:block}
@keyframes fadeIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}

/* ── معلومات التطبيق ── */
.hero{text-align:center;padding:24px 16px 20px;background:linear-gradient(160deg,rgba(123,47,247,.15),rgba(0,212,255,.1));border:1px solid rgba(123,47,247,.25);border-radius:22px;margin-bottom:14px;position:relative;overflow:hidden}
.hero::before{content:"";position:absolute;top:-50%;left:-50%;width:200%;height:200%;background:radial-gradient(circle,rgba(0,212,255,.1),transparent 60%);animation:heroGlow 4s ease-in-out infinite}
@keyframes heroGlow{0%,100%{opacity:.3}50%{opacity:.7}}
.hero-icon{width:80px;height:80px;margin:0 auto 12px;border-radius:50%;background:linear-gradient(135deg,#7b2ff7,#00d4ff);display:flex;align-items:center;justify-content:center;box-shadow:0 8px 30px rgba(123,47,247,.5);position:relative;z-index:1}
.hero-icon svg{width:44px;height:44px;fill:#fff}
.hero-name{font-size:22px;font-weight:900;background:linear-gradient(135deg,#fff,#a8d8ff);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;margin-bottom:8px;position:relative;z-index:1}
.hero-welcome{font-size:14px;color:#00d4ff;font-weight:700;position:relative;z-index:1}

.count-box{background:linear-gradient(160deg,rgba(243,156,18,.12),rgba(245,158,11,.06));border:1.5px solid rgba(243,156,18,.35);border-radius:20px;padding:18px;margin-bottom:14px}
.count-head{display:flex;align-items:center;gap:8px;font-size:13px;font-weight:800;color:#f59e0b;margin-bottom:12px}
.count-head svg{width:18px;height:18px;fill:#f59e0b}
.count-time{font-size:34px;font-weight:900;text-align:center;color:#fff;font-family:monospace;letter-spacing:2px;direction:ltr;text-shadow:0 0 20px rgba(245,158,11,.5)}

.info-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.info-item{background:linear-gradient(160deg,#10101e,#0a0a14);border:1px solid rgba(123,47,247,.18);border-radius:16px;padding:14px;text-align:center}
.info-item svg{width:24px;height:24px;fill:#00d4ff;margin-bottom:8px}
.info-item b{display:block;font-size:18px;font-weight:900;color:#fff;margin-bottom:2px}
.info-item span{font-size:11px;color:#6e6e8a}

/* ── بطاقات عامة ── */
.card{background:linear-gradient(160deg,#10101e,#0a0a14);border:1px solid rgba(123,47,247,.18);border-radius:18px;padding:16px;margin-bottom:12px;display:flex;gap:14px;align-items:flex-start}
.card-ico{width:44px;height:44px;border-radius:12px;background:linear-gradient(135deg,#7b2ff7,#00d4ff);display:flex;align-items:center;justify-content:center;flex-shrink:0}
.card-ico svg{width:22px;height:22px;fill:#fff}
.card-ico.gold{background:linear-gradient(135deg,#f59e0b,#fbbf24)}
.card-ico.red{background:linear-gradient(135deg,#e94560,#c62a47)}
.card-body{flex:1;min-width:0}
.card-title{font-size:14px;font-weight:800;color:#fff;margin-bottom:4px}
.card-desc{font-size:12px;color:#8e8eab;line-height:1.6}
.card-time{font-size:10px;color:#6e6e8a;margin-top:6px;font-family:monospace}

.empty{text-align:center;padding:50px 20px;color:#6e6e8a}
.empty svg{width:64px;height:64px;fill:#2a2a35;margin-bottom:14px;display:block;margin-left:auto;margin-right:auto}
.empty-t{font-size:15px;font-weight:800;color:#4a4a5e;margin-bottom:6px}
.empty-d{font-size:12px}


/* ── الشريط المتحرك ── */
.ticker{position:fixed;bottom:0px;left:0;right:0;height:42px;background:linear-gradient(135deg,#0c0c18,#12122a);border-top:1px solid rgba(123,47,247,.35);border-bottom:1px solid rgba(123,47,247,.35);display:flex;align-items:center;overflow:hidden;z-index:98;box-shadow:0 -4px 20px rgba(0,0,0,.5)}
.ticker-icon{width:42px;height:42px;background:linear-gradient(135deg,#7b2ff7,#00d4ff);display:flex;align-items:center;justify-content:center;flex-shrink:0;box-shadow:4px 0 12px rgba(0,0,0,.3)}
.ticker-icon svg{width:20px;height:20px;fill:#fff;animation:tickerStar 2s ease-in-out infinite}
@keyframes tickerStar{0%,100%{transform:scale(1) rotate(0)}50%{transform:scale(1.15) rotate(15deg)}}
.ticker-track{flex:1;overflow:hidden;position:relative;height:100%}
.ticker-content{display:inline-flex;align-items:center;height:100%;white-space:nowrap;animation:tickerMove 25s linear infinite;padding-right:100%}
@keyframes tickerMove{0%{transform:translateX(0)}100%{transform:translateX(50%)}}
.ticker-content span{color:#e8e8f0;font-size:13px;font-weight:700;letter-spacing:.3px;padding:0 12px}
.ticker-content .dot{color:#00d4ff;font-size:10px;padding:0 4px}

/* ── بطاقات المسابقات ── */
.contest-card{background:linear-gradient(160deg,#10101e,#0a0a14);border:1px solid rgba(123,47,247,.18);border-radius:20px;padding:16px;margin-bottom:14px;position:relative;overflow:hidden}
.contest-card.pinned{border-color:rgba(251,191,36,.5);background:linear-gradient(160deg,rgba(251,191,36,.06),rgba(251,191,36,.02))}
.pin-badge{position:absolute;top:0;left:0;background:linear-gradient(135deg,#fbbf24,#f59e0b);color:#fff;font-size:10px;font-weight:900;padding:4px 12px;border-bottom-right-radius:14px;letter-spacing:.3px}
.contest-head{display:flex;align-items:center;gap:12px;margin-bottom:12px;margin-top:6px}
.contest-ico{width:52px;height:52px;border-radius:16px;background:linear-gradient(135deg,#7b2ff7,#00d4ff);display:flex;align-items:center;justify-content:center;font-size:26px;flex-shrink:0;box-shadow:0 6px 18px rgba(123,47,247,.3)}
.contest-card.pinned .contest-ico{background:linear-gradient(135deg,#fbbf24,#f59e0b)}
.contest-info{flex:1;min-width:0}
.contest-title{font-size:16px;font-weight:900;color:#fff;margin-bottom:6px;word-break:break-word}
.contest-kind{display:inline-block;font-size:10px;font-weight:800;padding:3px 10px;border-radius:10px;letter-spacing:.2px}
.contest-kind.vote{background:rgba(123,47,247,.2);color:#c8a2ff}
.contest-kind.q{background:rgba(0,212,255,.15);color:#00d4ff}
.contest-kind.event{background:rgba(0,212,165,.15);color:#00d4a5}
.contest-desc{font-size:13px;color:#c8c8d8;line-height:1.7;margin-bottom:12px;padding:12px;background:rgba(0,0,0,.25);border-radius:12px;border-right:3px solid #00d4ff}
.contest-prize{display:flex;align-items:center;gap:8px;background:linear-gradient(135deg,rgba(0,212,165,.1),rgba(0,184,148,.05));border:1px solid rgba(0,212,165,.3);border-radius:12px;padding:10px 14px;margin-bottom:12px;font-size:13px;font-weight:800;color:#00d4a5}
.contest-prize svg{width:18px;height:18px;fill:#00d4a5;flex-shrink:0}
.contest-count{display:flex;align-items:center;justify-content:center;gap:8px;background:rgba(243,156,18,.08);border:1px solid rgba(243,156,18,.25);border-radius:12px;padding:10px;font-size:13px;font-weight:800;color:#f59e0b;font-family:monospace;direction:ltr;letter-spacing:1px}
.contest-count svg{width:16px;height:16px;fill:#f59e0b}
.count-txt{font-size:15px;font-weight:900}

.vote-box{display:flex;flex-direction:column;gap:8px;margin-top:8px}
.vote-opt{position:relative;padding:12px 14px;border:1.5px solid rgba(123,47,247,.25);background:rgba(255,255,255,.02);border-radius:12px;cursor:pointer;font-family:inherit;display:flex;align-items:center;justify-content:space-between;color:#e8e8f0;font-size:13px;font-weight:700;overflow:hidden;transition:all .2s}
.vote-opt:active{transform:scale(.98)}
.vote-fill{position:absolute;top:0;right:0;bottom:0;background:linear-gradient(90deg,rgba(123,47,247,.35),rgba(0,212,255,.35));transition:width .4s;z-index:0}
.vote-text{position:relative;z-index:1;text-align:right;flex:1}
.vote-pct{position:relative;z-index:1;font-weight:900;color:#00d4ff;font-family:monospace;direction:ltr}

/* ═══ شريط المستخدم في الهيدر ═══ */
.user-mini{display:flex;align-items:center;gap:8px;padding:4px 10px 4px 4px;background:linear-gradient(135deg,rgba(123,47,247,.15),rgba(0,212,255,.1));border:1px solid rgba(123,47,247,.3);border-radius:24px;cursor:pointer;flex-shrink:0;transition:all .2s;max-width:130px}
.user-mini:active{transform:scale(.96)}
.user-mini-av{width:32px;height:32px;border-radius:50%;background:linear-gradient(135deg,#7b2ff7,#00d4ff);display:flex;align-items:center;justify-content:center;color:#fff;font-weight:900;font-size:14px;flex-shrink:0;overflow:hidden}
.user-mini-av img{width:100%;height:100%;object-fit:cover}
.user-mini-info{flex:1;min-width:0;display:none}
.user-mini-name{font-size:11px;font-weight:800;color:#e8e8f0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.user-mini-sub{font-size:9px;color:#6e6e8a}
@media(min-width:420px){.user-mini-info{display:block}}

/* ═══ مشاركاتي ═══ */
.mine-header{background:linear-gradient(135deg,rgba(0,212,165,.1),rgba(0,184,148,.05));border:1px solid rgba(0,212,165,.3);border-radius:16px;padding:14px;margin-bottom:14px;text-align:center}
.mine-count{display:flex;align-items:center;justify-content:center;gap:10px;font-size:14px;color:#00d4a5;font-weight:700}
.mine-count svg{width:22px;height:22px;fill:#00d4a5}
.mine-count b{color:#fff;font-weight:900;font-size:18px}

.mine-card{background:linear-gradient(160deg,#10101e,#0a0a14);border:1px solid rgba(123,47,247,.18);border-radius:16px;padding:14px;margin-bottom:10px;display:flex;align-items:center;gap:12px;position:relative}
.mine-ico{width:48px;height:48px;border-radius:14px;background:linear-gradient(135deg,#7b2ff7,#00d4ff);display:flex;align-items:center;justify-content:center;font-size:22px;flex-shrink:0}
.mine-info{flex:1;min-width:0}
.mine-title{font-size:14px;font-weight:800;color:#fff;margin-bottom:6px;word-break:break-word}
.mine-meta{display:flex;flex-wrap:wrap;gap:5px}
.mine-tag{font-size:9px;font-weight:800;padding:2px 8px;border-radius:8px;letter-spacing:.2px}
.mine-tag.vote{background:rgba(123,47,247,.2);color:#c8a2ff}
.mine-tag.q{background:rgba(0,212,255,.15);color:#00d4ff}
.mine-tag.ev{background:rgba(0,212,165,.15);color:#00d4a5}
.mine-tag.active{background:rgba(0,212,165,.15);color:#00d4a5}
.mine-tag.paused{background:rgba(255,107,138,.15);color:#ff6b8a}
.mine-tag.prize{background:rgba(251,191,36,.15);color:#fbbf24}
.mine-check{width:36px;height:36px;border-radius:50%;background:linear-gradient(135deg,#00d4a5,#00b894);display:flex;align-items:center;justify-content:center;flex-shrink:0;box-shadow:0 4px 12px rgba(0,212,165,.4)}
.mine-check svg{width:20px;height:20px;fill:#fff}

/* ── بطاقات الإعلانات ── */
.ad-card{background:linear-gradient(160deg,#10101e,#0a0a14);border:1px solid rgba(123,47,247,.18);border-radius:20px;margin-bottom:16px;overflow:hidden;position:relative}
.ad-card.pinned{border-color:rgba(251,191,36,.5);box-shadow:0 0 30px rgba(251,191,36,.15)}
.ad-pin{position:absolute;top:10px;left:10px;z-index:5;display:flex;align-items:center;gap:4px;background:linear-gradient(135deg,#fbbf24,#f59e0b);color:#fff;font-size:10px;font-weight:900;padding:4px 10px;border-radius:10px;box-shadow:0 4px 12px rgba(245,158,11,.5);letter-spacing:.3px}
.ad-pin svg{width:12px;height:12px;fill:#fff}

/* السلايدر */
.slider{position:relative;width:100%;aspect-ratio:16/9;overflow:hidden;background:#000;user-select:none;touch-action:pan-y;direction:ltr}
.slider-track{display:flex;height:100%;transition:transform .35s cubic-bezier(.25,.8,.35,1);will-change:transform}
.slide{flex:0 0 100%;height:100%;display:flex;align-items:center;justify-content:center}
.slide img{width:100%;height:100%;object-fit:cover;display:block;pointer-events:none;-webkit-user-drag:none}

.nav-btn{position:absolute;top:50%;transform:translateY(-50%);width:36px;height:36px;border-radius:50%;background:rgba(0,0,0,.55);backdrop-filter:blur(8px);border:1px solid rgba(255,255,255,.2);color:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center;z-index:3;transition:all .2s}
.nav-btn:active{transform:translateY(-50%) scale(.9)}
.nav-btn svg{width:22px;height:22px;fill:#fff}
.nav-btn.prev{left:8px}
.nav-btn.next{right:8px}

.dots{position:absolute;bottom:10px;left:50%;transform:translateX(-50%);display:flex;gap:6px;z-index:3;background:rgba(0,0,0,.45);padding:6px 10px;border-radius:20px;backdrop-filter:blur(6px)}
.dot{width:8px;height:8px;border-radius:50%;background:rgba(255,255,255,.4);cursor:pointer;transition:all .25s}
.dot.active{background:#00d4ff;width:20px;border-radius:4px;box-shadow:0 0 10px #00d4ff}

.ad-body{padding:14px 16px 16px}
.ad-title{font-size:16px;font-weight:900;color:#fff;margin-bottom:8px;word-break:break-word}
.ad-text{font-size:13px;color:#c8c8d8;line-height:1.7;margin-bottom:12px;white-space:pre-line}
.ad-btn{display:flex;align-items:center;justify-content:center;gap:8px;padding:13px;border-radius:13px;background:linear-gradient(135deg,#25D366,#128C7E);color:#fff;font-weight:800;font-size:14px;text-decoration:none;box-shadow:0 6px 20px rgba(37,211,102,.35);transition:transform .2s}
.ad-btn:active{transform:scale(.97)}
.ad-btn svg{width:20px;height:20px;fill:#fff}

/* SOCIAL FEED */
.social-feed{display:flex;flex-direction:column;gap:14px}
.s-post{background:linear-gradient(160deg,#10101e,#0a0a14);border:1px solid rgba(123,47,247,.18);border-radius:20px;padding:16px;position:relative}
.s-post.pinned{border-color:rgba(251,191,36,.5);box-shadow:0 0 30px rgba(251,191,36,.15)}
.s-pin{position:absolute;top:-8px;right:14px;background:linear-gradient(135deg,#fbbf24,#f59e0b);color:#fff;font-size:10px;font-weight:900;padding:3px 10px;border-radius:10px;box-shadow:0 4px 12px rgba(245,158,11,.4)}
.s-head{display:flex;align-items:center;gap:12px;margin-bottom:12px}
.s-av{width:44px;height:44px;border-radius:50%;background:linear-gradient(135deg,#7b2ff7,#00d4ff);display:flex;align-items:center;justify-content:center;color:#fff;font-weight:900;font-size:18px;overflow:hidden;flex-shrink:0}
.s-av img{width:100%;height:100%;object-fit:cover}
.s-info{flex:1;min-width:0}
.s-name{font-size:14px;font-weight:800;color:#fff;margin-bottom:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.s-time{font-size:11px;color:#6e6e8a}
.s-body{font-size:14px;line-height:1.7;color:#e8e8f0;white-space:pre-line;margin-bottom:12px;word-break:break-word}
.s-media{display:grid;gap:6px;margin-bottom:12px}
.s-media.grid-2{grid-template-columns:1fr 1fr}
.s-media.grid-1{grid-template-columns:1fr}
.s-media img,.s-media video{width:100%;border-radius:12px;display:block;max-height:260px;object-fit:cover;background:#000;cursor:pointer}
.s-media.grid-2 img,.s-media.grid-2 video{max-height:150px}
.s-media.grid-1 img,.s-media.grid-1 video{max-height:260px}
.s-attach{display:flex;align-items:center;gap:10px;padding:12px;background:linear-gradient(135deg,rgba(0,212,255,.08),rgba(123,47,247,.08));border:1px solid rgba(0,212,255,.25);border-radius:12px;margin-bottom:12px;text-decoration:none;color:#00d4ff;font-size:13px;font-weight:700}
.s-attach svg{width:20px;height:20px;fill:#00d4ff;flex-shrink:0}
.s-stats{display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid rgba(255,255,255,.08);margin-bottom:8px;font-size:12px;color:#8e8eab}
.s-stats-likes{display:flex;align-items:center;gap:2px}
.s-stats-likes span{display:inline-flex;align-items:center;justify-content:center;width:20px;height:20px;background:rgba(0,0,0,.4);border-radius:50%;font-size:12px;margin-left:-4px;border:1.5px solid #0a0a14}
.s-stats-likes b{color:#00d4ff;margin-right:6px}
.s-actions{display:flex;gap:6px;padding:6px 0}
.s-btn{flex:1;padding:10px;border:none;background:transparent;color:#8e8eab;font-size:13px;font-weight:700;font-family:inherit;cursor:pointer;border-radius:10px;display:flex;align-items:center;justify-content:center;gap:6px;transition:all .2s;position:relative}
.s-btn:hover{background:rgba(255,255,255,.04);color:#e8e8f0}
.s-btn.active{color:#00d4ff;background:rgba(0,212,255,.08)}
.s-btn svg{width:18px;height:18px;fill:currentColor}
.s-btn.my-react{color:#e94560}
.s-btn .my-emoji{font-size:16px;position:absolute;top:-8px;right:8px;filter:drop-shadow(0 2px 4px rgba(0,0,0,.5))}

.s-react-pop{position:absolute;bottom:100%;left:0;background:#1a1a26;border:1px solid rgba(123,47,247,.3);border-radius:30px;padding:6px 8px;display:none;gap:4px;box-shadow:0 10px 30px rgba(0,0,0,.5);z-index:20;margin-bottom:4px}
.s-react-pop.show{display:flex}
.s-react-pop button{background:transparent;border:none;font-size:24px;cursor:pointer;padding:4px 6px;border-radius:50%;transition:transform .2s}
.s-react-pop button:hover{transform:scale(1.3);background:rgba(255,255,255,.1)}

.s-comments{margin-top:12px;padding-top:12px;border-top:1px solid rgba(255,255,255,.08);display:none}
.s-comments.show{display:block}
.s-comment{display:flex;gap:10px;margin-bottom:10px}
.s-comment .s-av{width:36px;height:36px;font-size:14px}
.s-comment-body{flex:1;background:rgba(0,0,0,.3);border-radius:14px;padding:8px 12px;min-width:0}
.s-comment-name{font-size:12px;font-weight:800;color:#00d4ff;margin-bottom:4px}
.s-comment-text{font-size:13px;color:#e8e8f0;line-height:1.5;word-break:break-word}
.s-comment-time{font-size:10px;color:#6e6e8a;margin-top:4px}

.s-comment-form{display:flex;gap:8px;margin-top:8px}
.s-comment-form input{flex:1;padding:10px 14px;border:1px solid rgba(123,47,247,.25);border-radius:20px;background:rgba(0,0,0,.4);color:#e8e8f0;font-size:13px;outline:none;font-family:inherit;min-width:0}
.s-comment-form input:focus{border-color:#7b2ff7}
.s-comment-form button{padding:10px 16px;border:none;border-radius:20px;background:linear-gradient(135deg,#7b2ff7,#00d4ff);color:#fff;font-weight:700;cursor:pointer;font-size:13px;font-family:inherit;flex-shrink:0}
.s-comment-form button:active{transform:scale(.95)}

/* ═══ تعليقات شجرية — ردود ═══ */
.s-comment-wrap{margin-bottom:10px}
.s-comment-wrap:last-child{margin-bottom:0}
.s-comment-replies{margin-top:8px;margin-right:26px;padding-right:12px;border-right:2px solid rgba(123,47,247,.25)}
.s-comment-replies .s-comment{margin-bottom:8px}
.s-comment-replies .s-comment:last-child{margin-bottom:0}
.s-comment-reply-btn{background:transparent;border:none;color:#8e8eab;font-size:11px;font-weight:700;cursor:pointer;padding:4px 8px;border-radius:6px;font-family:inherit;display:inline-flex;align-items:center;gap:4px}
.s-comment-reply-btn:hover{color:#00d4ff;background:rgba(0,212,255,.08)}
.s-comment-reply-btn:active{transform:scale(.95)}
.s-comment-reply-btn svg{width:12px;height:12px;fill:currentColor}
.s-reply-form{margin-top:8px;margin-right:26px;display:none;gap:6px}
.s-reply-form.show{display:flex}
.s-reply-form input{flex:1;padding:8px 12px;border:1px solid rgba(123,47,247,.3);border-radius:18px;background:rgba(0,0,0,.4);color:#e8e8f0;font-size:12px;outline:none;font-family:inherit;min-width:0}
.s-reply-form input:focus{border-color:#00d4ff}
.s-reply-form button{padding:8px 14px;border:none;border-radius:18px;background:linear-gradient(135deg,#7b2ff7,#00d4ff);color:#fff;font-weight:700;cursor:pointer;font-size:12px;font-family:inherit;flex-shrink:0}
.s-reply-form button:active{transform:scale(.95)}

/* ═══ أزرار الإعلانات المخصصة ═══ */
.ad-custom-btns{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
.ad-cbtn{flex:1;min-width:120px;padding:12px 16px;border:none;border-radius:12px;color:#fff;font-weight:800;font-size:13px;cursor:pointer;font-family:inherit;display:inline-flex;align-items:center;justify-content:center;gap:8px;text-decoration:none;box-shadow:0 4px 14px rgba(0,0,0,.25);transition:transform .15s,box-shadow .15s;text-align:center}
.ad-cbtn:active{transform:scale(.96);box-shadow:0 2px 8px rgba(0,0,0,.25)}
.ad-cbtn svg{width:18px;height:18px;fill:currentColor;flex-shrink:0}

/* ═══ شريط معلومات الإعلان ═══ */
.ad-info-box{margin-top:12px;padding:12px 14px;background:linear-gradient(135deg,rgba(123,47,247,.08),rgba(0,212,255,.06));border:1px solid rgba(123,47,247,.25);border-radius:12px;font-size:13px;line-height:1.7;color:#e8e8f0;word-break:break-word;position:relative}

.ad-info-box b,.ad-info-box strong{color:#fff;font-weight:900}
.ad-info-box i,.ad-info-box em{font-style:italic;color:#c8a2ff}
.ad-info-box u{text-decoration:underline;text-decoration-color:#00d4ff;text-decoration-thickness:1.5px;text-underline-offset:2px;padding-bottom:1px}

/* ═══ LITE MODE — للأجهزة الضعيفة ═══ */
html.lite-mode * {
    animation: none !important;
    transition: none !important;
}
html.lite-mode .ticker,
html.lite-mode .ticker-icon svg,
html.lite-mode .s-pin,
html.lite-mode .ad-pin,
html.lite-mode .pin-badge {
    animation: none !important;
}
html.lite-mode .ticker-content {
    animation-duration: 40s !important;
}
html.lite-mode .ticker-icon svg {
    animation: none !important;
}
html.lite-mode .slider-track {
    transition: transform .2s linear !important;
}
html.lite-mode .s-media img,
html.lite-mode .s-media video {
    max-height: 220px;
}
html.lite-mode .num-card,
html.lite-mode .card {
    box-shadow: none;
}
html.lite-mode .ad-cbtn,
html.lite-mode .ad-btn,
html.lite-mode .ad-info-box {
    box-shadow: none;
}
/* إخفاء الزخارف الخفيفة */
html.lite-mode .s-react-pop {
    transition: none;
}
</style>
</head>
<body>

<div class="hdr">
<a href="/" class="back">
<svg viewBox="0 0 24 24"><path d="M15.41 7.41L14 6l-6 6 6 6 1.41-1.41L10.83 12z"/></svg>
</a>
<h1>استكشف</h1>
{% if user_name %}
<div class="user-mini" onclick="window.location.href='/profile'">
<div class="user-mini-av">
{% if user_avatar %}
<img src="{{ user_avatar }}" alt="{{ user_name }}">
{% else %}
<span>{{ user_name[0]|upper }}</span>
{% endif %}
</div>
<div class="user-mini-info">
<div class="user-mini-name">{{ user_name }}</div>
<div class="user-mini-sub">اضغط للملف</div>
</div>
</div>
{% endif %}
</div>

<div class="tabs">
<button class="tab active" onclick="switchTab(event,'ads')">
<svg viewBox="0 0 24 24"><path d="M18 11v2h4v-2h-4zm-2 6.61c.96.71 2.21 1.65 3.2 2.39.4-.53.8-1.07 1.2-1.6-.99-.74-2.24-1.68-3.2-2.4-.4.54-.8 1.08-1.2 1.61zM20.4 5.6c-.4-.53-.8-1.07-1.2-1.6-.99.74-2.24 1.68-3.2 2.4.4.53.8 1.07 1.2 1.6.96-.72 2.21-1.65 3.2-2.4zM4 9c-1.1 0-2 .9-2 2v2c0 1.1.9 2 2 2h1v4h2v-4h1l5 3V6L8 9H4z"/></svg>
الإعلانات
</button>
<button class="tab" onclick="switchTab(event,'contests')">
<svg viewBox="0 0 24 24"><path d="M19 5h-2V3H7v2H5c-1.1 0-2 .9-2 2v1c0 2.55 1.92 4.63 4.39 4.94.63 1.5 1.98 2.63 3.61 2.96V19H7v2h10v-2h-4v-3.1c1.63-.33 2.98-1.46 3.61-2.96C19.08 12.63 21 10.55 21 8V7c0-1.1-.9-2-2-2zM5 8V7h2v3.82C5.84 10.4 5 9.3 5 8zm14 0c0 1.3-.84 2.4-2 2.82V7h2v1z"/></svg>
مسابقات
</button>
<button class="tab" onclick="switchTab(event,'mine')">
<svg viewBox="0 0 24 24"><path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/></svg>
مشاركاتي
</button>
<button class="tab" onclick="switchTab(event,'social')">
<svg viewBox="0 0 24 24"><path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z"/></svg>
اجتماعي
</button>
</div>

<div class="wrap">

<div class="pane active" id="pane-ads">
{% if ads and ads|length > 0 %}
{% for a in ads %}
<div class="ad-card {% if a.pinned %}pinned{% endif %}" data-ad-id="{{ a.id }}">
{% if a.pinned %}<div class="ad-pin"><svg viewBox="0 0 24 24"><path d="M16 12V4h1V2H7v2h1v8l-2 2v2h5.2v6h1.6v-6H18v-2l-2-2z"/></svg> مثبت</div>{% endif %}

{% if a.images and a.images|length > 0 %}
<div class="slider" data-idx="0" data-count="{{ a.images|length }}">
<div class="slider-track">
{% for img in a.images %}
<div class="slide"><img src="/uploads/{{ img }}" alt="{{ a.title }}" loading="lazy"></div>
{% endfor %}
</div>
{% if a.images|length > 1 %}
<button type="button" class="nav-btn prev" onclick="slidePrev(this)">
<svg viewBox="0 0 24 24"><path d="M15.41 7.41L14 6l-6 6 6 6 1.41-1.41L10.83 12z"/></svg>
</button>
<button type="button" class="nav-btn next" onclick="slideNext(this)">
<svg viewBox="0 0 24 24"><path d="M10 6L8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z"/></svg>
</button>
<div class="dots">
{% for img in a.images %}
<div class="dot {% if loop.index0 == 0 %}active{% endif %}" onclick="slideTo(this, {{ loop.index0 }})"></div>
{% endfor %}
</div>
{% endif %}
</div>
{% endif %}

<div class="ad-body">
<div class="ad-title">{{ a.title }}</div>
{% if a.body %}<div class="ad-text">{{ a.body }}</div>{% endif %}
{% if a.contact_url %}
<a href="{{ a.contact_url }}" target="_blank" class="ad-btn">
<svg viewBox="0 0 24 24"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347z"/></svg>
{{ a.contact_label or 'تواصل' }}
</a>
{% endif %}

{% if a.info_html and a.info_html|length > 0 %}
<div class="ad-info-box">{{ a.info_html|safe }}</div>
{% endif %}

{% if a.custom_buttons and a.custom_buttons|length > 0 %}
<div class="ad-custom-btns">
{% for b in a.custom_buttons %}
{% if b.mode == 'html' and b.html %}
<button type="button" class="ad-cbtn" style="background:{{ b.color or '#00d4ff' }}" data-html="{{ b.html|e }}" onclick="exploreAdHtml(this)">
{% if b.icon_svg %}{{ b.icon_svg|safe }}{% endif %}
<span>{{ b.label or 'عرض' }}</span>
</button>
{% else %}
<a href="{{ b.url or '#' }}" {% if b.url and (b.url.startswith('http://') or b.url.startswith('https://')) %}target="_blank" rel="noopener"{% endif %} class="ad-cbtn" style="background:{{ b.color or '#25D366' }}">
{% if b.icon_svg %}{{ b.icon_svg|safe }}{% endif %}
<span>{{ b.label or 'زر' }}</span>
</a>
{% endif %}
{% endfor %}
</div>
{% endif %}
</div>
</div>
{% endfor %}
{% else %}
<div class="empty">
<svg viewBox="0 0 24 24"><path d="M18 11v2h4v-2h-4zm-2 6.61c.96.71 2.21 1.65 3.2 2.39.4-.53.8-1.07 1.2-1.6-.99-.74-2.24-1.68-3.2-2.4-.4.54-.8 1.08-1.2 1.61zM20.4 5.6c-.4-.53-.8-1.07-1.2-1.6-.99.74-2.24 1.68-3.2 2.4.4.53.8 1.07 1.2 1.6.96-.72 2.21-1.65 3.2-2.4zM4 9c-1.1 0-2 .9-2 2v2c0 1.1.9 2 2 2h1v4h2v-4h1l5 3V6L8 9H4z"/></svg>
<div class="empty-t">لا توجد إعلانات حالياً</div>
<div class="empty-d">تابعنا قريباً</div>
</div>
{% endif %}
</div>

<div class="pane" id="pane-mine">
{% if user_voters and user_voters|length > 0 %}
<div class="mine-header">
<div class="mine-count">
<svg viewBox="0 0 24 24"><path d="M19 5h-2V3H7v2H5c-1.1 0-2 .9-2 2v1c0 2.55 1.92 4.63 4.39 4.94.63 1.5 1.98 2.63 3.61 2.96V19H7v2h10v-2h-4v-3.1c1.63-.33 2.98-1.46 3.61-2.96C19.08 12.63 21 10.55 21 8V7c0-1.1-.9-2-2-2z"/></svg>
<span>عدد مشاركاتك: <b>{{ user_voters|length }}</b></span>
</div>
</div>
{% for c in user_voters %}
<div class="mine-card">
<div class="mine-ico">{% if c.icon and c.icon not in ['🏆',''] %}{{ c.icon }}{% else %}<svg viewBox="0 0 24 24" style="width:24px;height:24px;fill:#fff"><path d="M19 5h-2V3H7v2H5c-1.1 0-2 .9-2 2v1c0 2.55 1.92 4.63 4.39 4.94.63 1.5 1.98 2.63 3.61 2.96V19H7v2h10v-2h-4v-3.1c1.63-.33 2.98-1.46 3.61-2.96C19.08 12.63 21 10.55 21 8V7c0-1.1-.9-2-2-2z"/></svg>{% endif %}</div>
<div class="mine-info">
<div class="mine-title">{{ c.title }}</div>
<div class="mine-meta">
{% if c.kind == 'vote' %}<span class="mine-tag vote">تصويت</span>
{% elif c.kind == 'question' %}<span class="mine-tag q">سؤال</span>
{% else %}<span class="mine-tag ev">حدث</span>{% endif %}
{% if c.status == 'paused' %}<span class="mine-tag paused">موقوفة</span>
{% else %}<span class="mine-tag active">نشطة</span>{% endif %}
{% if c.prize %}<span class="mine-tag prize">{{ c.prize }}</span>{% endif %}
</div>
</div>
<div class="mine-check">
<svg viewBox="0 0 24 24"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>
</div>
</div>
{% endfor %}
{% else %}
<div class="empty">
<svg viewBox="0 0 24 24"><path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/></svg>
<div class="empty-t">ما شاركت في أي مسابقة بعد</div>
<div class="empty-d">افتح تبويب "مسابقات" وجرّب حظك</div>
</div>
{% endif %}
</div>

<div class="pane" id="pane-social">
{% if social_posts and social_posts|length > 0 %}
<div class="social-feed">
{% for p in social_posts %}
<div class="s-post {% if p.pinned %}pinned{% endif %}" data-pid="{{ p.id }}">
{% if p.pinned %}<div class="s-pin">مثبت</div>{% endif %}
<div class="s-head">
<div class="s-av">
{% if p.author_avatar %}<img src="{{ p.author_avatar }}" alt="">{% else %}{{ (p.author_display or p.author or 'U')[0]|upper }}{% endif %}
</div>
<div class="s-info">
<div class="s-name">{{ p.author_display or p.author }}</div>
<div class="s-time">{{ p.created|timestamp }}</div>
</div>
</div>
{% if p.body %}<div class="s-body">{{ p.body }}</div>{% endif %}
{% if p.media and p.media|length > 0 %}
<div class="s-media {% if p.media|length == 1 %}grid-1{% else %}grid-2{% endif %}">
{% for m in p.media %}
{% if m.type == 'video' %}
<video src="/uploads/{{ m.src }}" controls preload="metadata"></video>
{% else %}
<img src="/uploads/{{ m.src }}" alt="" loading="lazy">
{% endif %}
{% endfor %}
</div>
{% endif %}
{% if p.attach %}
<a href="/uploads/{{ p.attach }}" class="s-attach" download>
<svg viewBox="0 0 24 24"><path d="M14 2H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V8l-6-6zm4 18H6V4h7v5h5v11z"/></svg>
<span>{{ p.attach_name or 'ملف مرفق' }}</span>
</a>
{% endif %}
<div class="s-stats">
<div class="s-stats-likes">
{% if p.likes_count and p.likes_count > 0 %}
<b>{{ p.likes_count }}</b>
{% endif %}
</div>
<div>{{ p.comments_count or 0 }} تعليق</div>
</div>
<div class="s-actions" style="position:relative">
<button class="s-btn {% if p.my_reaction %}active{% endif %}" onclick="toggleReactions({{ p.id }}, event)" id="likeBtn_{{ p.id }}">
<svg viewBox="0 0 24 24"><path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/></svg>
إعجاب
{% if p.my_reaction %}<span class="my-emoji" id="myEmoji_{{ p.id }}">{{ {'like':'👍','love':'❤️','haha':'😂','wow':'😮','sad':'😢','angry':'😡'}.get(p.my_reaction, '👍') }}</span>{% endif %}
</button>
<div class="s-react-pop" id="reactPop_{{ p.id }}">
<button onclick="sendReaction({{ p.id }}, 'like')">👍</button>
<button onclick="sendReaction({{ p.id }}, 'love')">❤️</button>
<button onclick="sendReaction({{ p.id }}, 'haha')">😂</button>
<button onclick="sendReaction({{ p.id }}, 'wow')">😮</button>
<button onclick="sendReaction({{ p.id }}, 'sad')">😢</button>
<button onclick="sendReaction({{ p.id }}, 'angry')">😡</button>
</div>
<button class="s-btn" onclick="toggleComments({{ p.id }})" id="comBtn_{{ p.id }}">
<svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/></svg>
تعليق
</button>
</div>
<div class="s-comments" id="comments_{{ p.id }}">
<div id="commentsList_{{ p.id }}"></div>
<div class="s-comment-form">
<input type="text" placeholder="اكتب تعليقك..." id="commentInput_{{ p.id }}" maxlength="500" onkeydown="if(event.key==='Enter'){event.preventDefault();sendComment({{ p.id }});}">
<button onclick="sendComment({{ p.id }})">إرسال</button>
</div>
</div>
</div>
{% endfor %}
</div>
{% else %}
<div class="empty" style="text-align:center;padding:60px 20px;color:#6e6e8a">
<svg viewBox="0 0 24 24" style="width:64px;height:64px;fill:#2a2a35"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/></svg>
<div style="font-size:15px;font-weight:800;color:#4a4a5e;margin-top:14px">لا توجد منشورات بعد</div>
<div style="font-size:12px;margin-top:6px">ترقبوا الجديد قريباً</div>
</div>
{% endif %}
</div>

<div class="pane" id="pane-contests">
{% if contests %}
{% for c in contests %}
<div class="contest-card {% if c.pinned %}pinned{% endif %}">
{% if c.pinned %}<div class="pin-badge"><svg viewBox="0 0 24 24" style="width:1em;height:1em;fill:currentColor;vertical-align:middle;margin-left:4px"><path d="M16 12V4h1V2H7v2h1v8l-2 2v2h5.2v6h1.6v-6H18v-2l-2-2z"/></svg> مثبتة</div>{% endif %}
<div class="contest-head">
<div class="contest-ico">{% if c.icon and c.icon not in ['🏆',''] %}{{ c.icon }}{% else %}<svg viewBox="0 0 24 24" style="width:26px;height:26px;fill:#fff"><path d="M19 5h-2V3H7v2H5c-1.1 0-2 .9-2 2v1c0 2.55 1.92 4.63 4.39 4.94.63 1.5 1.98 2.63 3.61 2.96V19H7v2h10v-2h-4v-3.1c1.63-.33 2.98-1.46 3.61-2.96C19.08 12.63 21 10.55 21 8V7c0-1.1-.9-2-2-2zM5 8V7h2v3.82C5.84 10.4 5 9.3 5 8zm14 0c0 1.3-.84 2.4-2 2.82V7h2v1z"/></svg>{% endif %}</div>
<div class="contest-info">
<div class="contest-title">{{ c.title }}</div>
{% if c.kind == 'vote' %}<span class="contest-kind vote"><svg viewBox="0 0 24 24" style="width:1em;height:1em;fill:currentColor;vertical-align:middle"><path d="M18 13h-.68l-2 2h1.91L19 17H5l1.78-2h2.05l-2-2H6l-3 3v4c0 1.1.89 2 1.99 2H19c1.1 0 2-.9 2-2v-4l-3-3zm-1-5.05l-4.95 4.95-3.54-3.54 4.95-4.95L17 7.95zm-4.24-5.66L6.39 8.66c-.39.39-.39 1.02 0 1.41l4.95 4.95c.39.39 1.02.39 1.41 0l6.36-6.36c.39-.39.39-1.02 0-1.41L14.16 2.3c-.38-.4-1.01-.4-1.4-.01z"/></svg> تصويت</span>
{% elif c.kind == 'question' %}<span class="contest-kind q"><svg viewBox="0 0 24 24" style="width:1em;height:1em;fill:currentColor;vertical-align:middle"><path d="M11 18h2v-2h-2v2zm1-16C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8zm0-14c-2.21 0-4 1.79-4 4h2c0-1.1.9-2 2-2s2 .9 2 2c0 2-3 1.75-3 5h2c0-2.25 3-2.5 3-5 0-2.21-1.79-4-4-4z"/></svg> سؤال</span>
{% else %}<span class="contest-kind event"><svg viewBox="0 0 24 24" style="width:1em;height:1em;fill:currentColor;vertical-align:middle"><path d="M19 3h-1V1h-2v2H8V1H6v2H5c-1.11 0-1.99.9-1.99 2L3 19c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm0 16H5V8h14v11zM7 10h5v5H7z"/></svg> حدث</span>{% endif %}
</div>
</div>

{% if c.description %}
<div class="contest-desc">{{ c.description }}</div>
{% endif %}

{% if c.prize %}
<div class="contest-prize">
<svg viewBox="0 0 24 24"><path d="M20 6h-2.18c.11-.31.18-.65.18-1a2.996 2.996 0 00-5.5-1.65l-.5.67-.5-.68C10.96 2.54 10.05 2 9 2 7.34 2 6 3.34 6 5c0 .35.07.69.18 1H4c-1.11 0-1.99.89-1.99 2L2 19c0 1.11.89 2 2 2h16c1.11 0 2-.89 2-2V8c0-1.11-.89-2-2-2zM15 4c.55 0 1 .45 1 1s-.45 1-1 1-1-.45-1-1 .45-1 1-1zM9 4c.55 0 1 .45 1 1s-.45 1-1 1-1-.45-1-1 .45-1 1-1zm11 15H4v-2h16v2zm0-5H4V8h5.08L7 10.83 8.62 12 11 8.76l1-1.36 1 1.36L15.38 12 17 10.83 14.92 8H20v6z"/></svg>
<span>{{ c.prize }}</span>
</div>
{% endif %}

{% if c.kind == 'vote' %}
{% set vd = c.votes|from_json %}
{% if vd is mapping and vd.labels %}
{% set labels = vd.labels %}
{% set counts = vd.counts %}
{% set total_votes = counts|sum %}
<div class="vote-box">
{% for label in labels %}
{% set pct = ((counts[loop.index0] / total_votes * 100) if total_votes else 0)|round(0) %}
<button type="button" class="vote-opt" onclick="doVote({{ c.id }}, {{ loop.index0 }}, this)">
<div class="vote-fill" style="width:{{ pct }}%"></div>
<span class="vote-text">{{ label }}</span>
<span class="vote-pct">{{ pct }}%</span>
</button>
{% endfor %}
</div>
{% endif %}
{% endif %}

{% if c.ends_at and c.ends_at > now %}
<div class="contest-count" data-end="{{ c.ends_at|int }}">
<svg viewBox="0 0 24 24"><path d="M11.99 2C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2zM12 20c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8zm.5-13H11v6l5.25 3.15.75-1.23-4.5-2.67z"/></svg>
<span class="count-txt">--:--:--</span>
</div>
{% endif %}
</div>
{% endfor %}
{% else %}
<div class="empty">
<svg viewBox="0 0 24 24"><path d="M19 5h-2V3H7v2H5c-1.1 0-2 .9-2 2v1c0 2.55 1.92 4.63 4.39 4.94.63 1.5 1.98 2.63 3.61 2.96V19H7v2h10v-2h-4v-3.1c1.63-.33 2.98-1.46 3.61-2.96C19.08 12.63 21 10.55 21 8V7c0-1.1-.9-2-2-2z"/></svg>
<div class="empty-t">لا توجد مسابقات حالياً</div>
<div class="empty-d">ترقبوا قريباً</div>
</div>
{% endif %}
</div>

</div>

<script>
function switchTab(e, name){
    document.querySelectorAll('.tab').forEach(function(t){ t.classList.remove('active'); });
    document.querySelectorAll('.pane').forEach(function(p){ p.classList.remove('active'); });
    e.currentTarget.classList.add('active');
    var pane = document.getElementById('pane-' + name);
    if(pane) pane.classList.add('active');
}

// عداد تنازلي بسيط
(function(){
    var sec = 30 * 60;
    var el = document.getElementById('countdown');
    if(!el) return;
    setInterval(function(){
        sec--;
        if(sec < 0) sec = 30 * 60;
        var m = Math.floor(sec / 60);
        var s = sec % 60;
        el.textContent = (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
    }, 1000);
})();

// ═══ تصويت ═══
function doVote(cid, idx, btn){
    if(btn.disabled) return;
    btn.disabled = true;
    fetch('/explore/vote/' + cid + '/' + idx, {method:'POST'})
        .then(function(r){ return r.json(); })
        .then(function(d){
            if(d.ok){
                location.reload();
            } else {
                btn.disabled = false;
                alert(d.msg || 'فشل التصويت');
            }
        })
        .catch(function(e){
            btn.disabled = false;
            alert('خطأ: ' + e.message);
        });
}


// ═══════════════════════════════════════════
// SOCIAL — تفاعلات وتعليقات
// ═══════════════════════════════════════════
var REACTION_EMOJI_MAP = {"like":"👍","love":"❤️","haha":"😂","wow":"😮","sad":"😢","angry":"😡"};

function esc(t){
    var d = document.createElement('div');
    d.textContent = t || '';
    return d.innerHTML;
}

function agoS(ts){
    var s = Math.floor(Date.now()/1000 - ts);
    if(s < 60) return 'الآن';
    if(s < 3600) return 'منذ ' + Math.floor(s/60) + ' د';
    if(s < 86400) return 'منذ ' + Math.floor(s/3600) + ' س';
    if(s < 604800) return 'منذ ' + Math.floor(s/86400) + ' ي';
    return '';
}

function toggleReactions(pid, e){
    e.preventDefault();
    e.stopPropagation();
    var pop = document.getElementById('reactPop_' + pid);
    if(!pop) return;
    var isOpen = pop.classList.contains('show');
    document.querySelectorAll('.s-react-pop').forEach(function(p){ p.classList.remove('show'); });
    if(!isOpen){
        pop.classList.add('show');
        clearTimeout(pop._tm);
        pop._tm = setTimeout(function(){ pop.classList.remove('show'); }, 4000);
    }
}

async function sendReaction(pid, kind){
    document.querySelectorAll('.s-react-pop').forEach(function(p){ p.classList.remove('show'); });
    try {
        var r = await fetch('/api/social/react/' + pid, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({kind: kind})
        });
        if(!r.ok){ alert('فشل: ' + r.status); return; }
        var d = await r.json();
        if(!d.ok){ alert(d.error || 'فشل'); return; }

        // حدّث الزر
        var btn = document.getElementById('likeBtn_' + pid);
        if(btn){
            var oldEmoji = btn.querySelector('.my-emoji');
            if(oldEmoji) oldEmoji.remove();
            if(d.action === 'removed'){
                btn.classList.remove('active');
            } else {
                btn.classList.add('active');
                var span = document.createElement('span');
                span.className = 'my-emoji';
                span.textContent = REACTION_EMOJI_MAP[d.kind] || '👍';
                btn.appendChild(span);
            }
        }

        // حدّث عدد الإعجابات
        var post = document.querySelector('[data-pid="' + pid + '"]');
        if(post){
            var statsLikes = post.querySelector('.s-stats-likes');
            var total = 0;
            if(d.reactions){
                Object.values(d.reactions).forEach(function(v){ total += v; });
            }
            if(statsLikes){
                var b = statsLikes.querySelector('b');
                if(total > 0){
                    if(b) b.textContent = total;
                    else statsLikes.insertAdjacentHTML('afterbegin', '<b>' + total + '</b>');
                } else {
                    if(b) b.remove();
                }
            }
        }
    } catch(e){
        alert('خطأ: ' + e.message);
    }
}

function renderCommentTree(c, postId){
    var av = c.author_avatar
        ? '<img src="' + esc(c.author_avatar) + '" alt="">'
        : esc((c.author_display || c.author || 'U')[0].toUpperCase());
    var repliesHtml = '';
    if(c.replies && c.replies.length > 0){
        repliesHtml = '<div class="s-comment-replies">' +
            c.replies.map(function(r){ return renderCommentTree(r, postId); }).join('') +
            '</div>';
    }
    return '<div class="s-comment-wrap" data-cid="' + c.id + '">' +
        '<div class="s-comment">' +
            '<div class="s-av">' + av + '</div>' +
            '<div class="s-comment-body">' +
                '<div class="s-comment-name">' + esc(c.author_display || c.author) + '</div>' +
                '<div class="s-comment-text">' + esc(c.body) + '</div>' +
                '<div style="display:flex;align-items:center;gap:6px;margin-top:4px">' +
                    '<div class="s-comment-time">' + agoS(c.created) + '</div>' +
                    '<button type="button" class="s-comment-reply-btn" onclick="toggleReplyForm(' + c.id + ', ' + postId + ')">' +
                        '<svg viewBox="0 0 24 24"><path d="M10 9V5l-7 7 7 7v-4.1c5 0 8.5 1.6 11 5.1-1-5-4-10-11-11z"/></svg>' +
                        'رد' +
                    '</button>' +
                '</div>' +
            '</div>' +
        '</div>' +
        repliesHtml +
        '<div class="s-reply-form" id="reply-form-' + c.id + '">' +
            '<input type="text" id="reply-input-' + c.id + '" placeholder="اكتب ردك على ' + esc(c.author_display || c.author) + '..." maxlength="500">' +
            '<button type="button" onclick="sendReply(' + c.id + ', ' + postId + ')">إرسال</button>' +
        '</div>' +
    '</div>';
}

async function toggleComments(pid){
    var div = document.getElementById('comments_' + pid);
    if(!div) return;
    if(div.classList.contains('show')){
        div.classList.remove('show');
        return;
    }
    div.classList.add('show');
    await loadComments(pid);
}

async function loadComments(pid){
    var list = document.getElementById('commentsList_' + pid);
    if(!list) return;
    list.innerHTML = '<div style="text-align:center;padding:12px;color:#6e6e8a;font-size:12px">جاري التحميل...</div>';
    try {
        var r = await fetch('/api/social/comments/' + pid, {credentials:'same-origin'});
        if(!r.ok){ list.innerHTML = '<div style="text-align:center;padding:12px;color:#ff6b8a;font-size:12px">فشل: ' + r.status + '</div>'; return; }
        var d = await r.json();
        if(d.ok){
            if(!d.comments || d.comments.length === 0){
                list.innerHTML = '<div style="text-align:center;padding:12px;color:#6e6e8a;font-size:12px">لا توجد تعليقات — كن أول من يعلّق</div>';
            } else {
                list.innerHTML = d.comments.map(function(c){ return renderCommentTree(c, pid); }).join('');
            }
        } else {
            list.innerHTML = '<div style="text-align:center;padding:12px;color:#ff6b8a;font-size:12px">' + esc(d.error || 'فشل') + '</div>';
        }
    } catch(e){
        list.innerHTML = '<div style="text-align:center;padding:12px;color:#ff6b8a;font-size:12px">خطأ: ' + esc(e.message) + '</div>';
    }
}

function toggleReplyForm(cid, pid){
    var f = document.getElementById('reply-form-' + cid);
    if(!f) return;
    // اقفل باقي النماذج المفتوحة
    document.querySelectorAll('.s-reply-form.show').forEach(function(el){
        if(el.id !== 'reply-form-' + cid) el.classList.remove('show');
    });
    f.classList.toggle('show');
    if(f.classList.contains('show')){
        var inp = document.getElementById('reply-input-' + cid);
        if(inp) setTimeout(function(){ inp.focus(); }, 100);
    }
}

async function sendReply(parentId, pid){
    var inp = document.getElementById('reply-input-' + parentId);
    if(!inp) return;
    var body = inp.value.trim();
    if(!body) return;
    inp.disabled = true;
    try {
        var r = await fetch('/api/social/comment/' + pid, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({body: body, parent_id: parentId})
        });
        if(!r.ok){ alert('فشل: ' + r.status); inp.disabled = false; return; }
        var d = await r.json();
        if(d.ok){
            inp.value = '';
            var f = document.getElementById('reply-form-' + parentId);
            if(f) f.classList.remove('show');
            // أعد تحميل التعليقات
            await loadComments(pid);
        } else {
            alert('فشل: ' + (d.error || ''));
        }
    } catch(e){
        alert('خطأ: ' + e.message);
    }
    inp.disabled = false;
}

async function sendComment(pid){
    var inp = document.getElementById('commentInput_' + pid);
    if(!inp) return;
    var body = inp.value.trim();
    if(!body) return;
    inp.value = '';
    inp.disabled = true;
    try {
        var r = await fetch('/api/social/comment/' + pid, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({body: body, parent_id: 0})
        });
        if(!r.ok){ alert('فشل: ' + r.status); inp.disabled = false; return; }
        var d = await r.json();
        if(d.ok && d.comment){
            var list = document.getElementById('commentsList_' + pid);
            if(list){
                var c = d.comment;
                var av = c.author_avatar
                    ? '<img src="' + esc(c.author_avatar) + '" alt="">'
                    : esc((c.author_display || c.author || 'U')[0].toUpperCase());
                var html = '<div class="s-comment">' +
                    '<div class="s-av">' + av + '</div>' +
                    '<div class="s-comment-body">' +
                    '<div class="s-comment-name">' + esc(c.author_display || c.author) + '</div>' +
                    '<div class="s-comment-text">' + esc(c.body) + '</div>' +
                    '<div class="s-comment-time">الآن</div>' +
                    '</div></div>';
                // شيل "لا توجد تعليقات"
                if(list.querySelector('div[style*="لا توجد"]')){
                    list.innerHTML = html;
                } else {
                    list.insertAdjacentHTML('beforeend', html);
                }
            }
            // حدّث عدّاد التعليقات
            var post = document.querySelector('[data-pid="' + pid + '"]');
            if(post){
                var stats = post.querySelector('.s-stats');
                if(stats){
                    var divs = stats.querySelectorAll('div');
                    if(divs.length > 1){
                        var txt = divs[1].textContent;
                        var n = parseInt(txt) || 0;
                        divs[1].textContent = (n + 1) + ' تعليق';
                    }
                }
            }
        } else {
            alert(d.error || 'فشل');
        }
    } catch(e){
        alert('خطأ: ' + e.message);
    }
    inp.disabled = false;
    inp.focus();
}

// اقفل popups لما تنقر برا
document.addEventListener('click', function(e){
    if(!e.target.closest || (!e.target.closest('.s-react-pop') && !e.target.closest('#likeBtn_'))){
        document.querySelectorAll('.s-react-pop').forEach(function(p){ p.classList.remove('show'); });
    }
});

// ═══ عداد تنازلي ═══
function tickCounters(){
    document.querySelectorAll('.contest-count[data-end]').forEach(function(el){
        var end = parseInt(el.dataset.end) * 1000;
        var now = Date.now();
        var diff = Math.floor((end - now) / 1000);
        var txt = el.querySelector('.count-txt');
        if(!txt) return;
        if(diff <= 0){ txt.textContent = 'انتهت'; return; }
        var d = Math.floor(diff / 86400);
        var h = Math.floor((diff % 86400) / 3600);
        var m = Math.floor((diff % 3600) / 60);
        var s = diff % 60;
        if(d > 0){
            txt.textContent = d + 'يوم ' + h + ':' + (m<10?'0':'')+m + ':' + (s<10?'0':'')+s;
        } else {
            txt.textContent = (h<10?'0':'')+h + ':' + (m<10?'0':'')+m + ':' + (s<10?'0':'')+s;
        }
    });
}
tickCounters();
setInterval(tickCounters, 1000);

// ═══ سلايدر الإعلانات ═══
function slideUpdate(slider){
    var idx = parseInt(slider.dataset.idx) || 0;
    var count = parseInt(slider.dataset.count) || 1;
    if(idx < 0) idx = count - 1;
    if(idx >= count) idx = 0;
    slider.dataset.idx = idx;
    var track = slider.querySelector('.slider-track');
    if(track) track.style.transform = 'translateX(' + (-idx * 100) + '%)';
    slider.querySelectorAll('.dot').forEach(function(d, i){
        d.classList.toggle('active', i === idx);
    });
}

function slideNext(btn){
    var slider = btn.closest('.slider');
    if(!slider) return;
    var idx = parseInt(slider.dataset.idx) || 0;
    slider.dataset.idx = idx + 1;
    slideUpdate(slider);
}

function slidePrev(btn){
    var slider = btn.closest('.slider');
    if(!slider) return;
    var idx = parseInt(slider.dataset.idx) || 0;
    slider.dataset.idx = idx - 1;
    slideUpdate(slider);
}

function slideTo(dot, idx){
    var slider = dot.closest('.slider');
    if(!slider) return;
    slider.dataset.idx = idx;
    slideUpdate(slider);
}

// سحب بالإصبع
document.querySelectorAll('.slider').forEach(function(slider){
    var startX = 0, startY = 0, moved = false, locked = false;
    slider.addEventListener('touchstart', function(e){
        startX = e.touches[0].clientX;
        startY = e.touches[0].clientY;
        moved = false; locked = false;
    }, {passive:true});
    slider.addEventListener('touchmove', function(e){
        if(locked) return;
        var dx = e.touches[0].clientX - startX;
        var dy = e.touches[0].clientY - startY;
        if(Math.abs(dy) > Math.abs(dx) && Math.abs(dy) > 15){
            locked = true;
            return;
        }
        if(Math.abs(dx) > 15) moved = true;
    }, {passive:true});
    slider.addEventListener('touchend', function(e){
        if(!moved || locked) return;
        var dx = e.changedTouches[0].clientX - startX;
        if(dx < -50){ slideNext(slider.querySelector('.next') || slider); }
        else if(dx > 50){ slidePrev(slider.querySelector('.prev') || slider); }
    }, {passive:true});
});

// تشغيل أولي
document.querySelectorAll('.slider').forEach(slideUpdate);

// تخطي تلقائي كل 5 ثواني (فقط إذا الإعلان في الشاشة)
setInterval(function(){
    if(document.hidden) return;
    document.querySelectorAll('.slider').forEach(function(slider){
        var rect = slider.getBoundingClientRect();
        if(rect.top < window.innerHeight && rect.bottom > 0){
            var idx = parseInt(slider.dataset.idx) || 0;
            slider.dataset.idx = idx + 1;
            slideUpdate(slider);
        }
    });
}, 5000);
</script>

<div class="ticker">
<div class="ticker-icon">
<svg viewBox="0 0 24 24"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg>
</div>
<div class="ticker-track">
<div class="ticker-content">
<span>أهلاً بك في تطبيق المطري OTP</span>
<span class="dot">◆</span>
<span>ترقبوا الجديد قريباً</span>
<span class="dot">◆</span>
<span>أهلاً بك في تطبيق المطري OTP</span>
<span class="dot">◆</span>
<span>ترقبوا الجديد قريباً</span>
<span class="dot">◆</span>
</div>
</div>
</div>


<style>
.exp-preview-overlay{
    position:fixed;top:0;left:0;right:0;bottom:0;
    background:rgba(0,0,0,.96);
    z-index:9999999;display:none;flex-direction:column;
}
.exp-preview-overlay.show{display:flex}
.exp-preview-topbar{
    display:flex;align-items:center;
    padding:10px 12px;
    background:linear-gradient(135deg,#0c0c18,#12122a);
    border-bottom:1px solid rgba(123,47,247,.35);
    flex-shrink:0;
    justify-content:flex-end;
}
.exp-preview-topbar .exp-pv-close{
    width:44px;height:44px;border-radius:50%;border:none;
    background:linear-gradient(135deg,#e94560,#c62a47);
    color:#fff;cursor:pointer;display:flex;
    align-items:center;justify-content:center;flex-shrink:0;
    box-shadow:0 4px 14px rgba(233,69,96,.5);
}
.exp-preview-topbar .exp-pv-close:active{transform:scale(.9)}
.exp-preview-topbar .exp-pv-close svg{width:20px;height:20px;fill:#fff}
.exp-preview-frame{
    flex:1;width:100%;border:none;background:#fff;
}
</style>
<div class="exp-preview-overlay" id="expPreviewOverlay">
    <div class="exp-preview-topbar">
        <button type="button" class="exp-pv-close" onclick="expClosePreview()" title="إغلاق">
            <svg viewBox="0 0 24 24"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>
        </button>
    </div>
    <iframe class="exp-preview-frame" id="expPreviewFrame" style="display:block;background:#fff;border:none;flex:1;width:100%"></iframe>
</div>

<script>
function exploreAdHtml(btn){
    var html = btn.dataset.html || '';
    if(!html){alert('لا يوجد محتوى'); return;}
    var overlay = document.getElementById('expPreviewOverlay');
    var iframe = document.getElementById('expPreviewFrame');
    if(!overlay || !iframe){alert('نافذة العرض غير موجودة'); return;}
    // ضع HTML في iframe عبر srcdoc
    iframe.srcdoc = html;
    overlay.classList.add('show');
    document.body.style.overflow = 'hidden';
}
function expClosePreview(){
    var overlay = document.getElementById('expPreviewOverlay');
    var iframe = document.getElementById('expPreviewFrame');
    if(overlay) overlay.classList.remove('show');
    if(iframe) iframe.srcdoc = '';
    document.body.style.overflow = '';
}
document.addEventListener('keydown', function(e){
    if(e.key === 'Escape'){
        var overlay = document.getElementById('expPreviewOverlay');
        if(overlay && overlay.classList.contains('show')) expClosePreview();
    }
});
</script>
</body>
</html>"""


# ═══════════════════════════════════════════
# المسابقات — Contests
# ═══════════════════════════════════════════
def contests_list(only_active=False):
    """يرجع كل المسابقات — المثبتة أولاً"""
    try:
        conn = _db()
        if only_active:
            rows = conn.execute(
                "SELECT * FROM contests WHERE status='active' ORDER BY pinned DESC, created DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM contests ORDER BY pinned DESC, created DESC"
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        print("contests_list err:", e)
        return []


def contests_get(cid):
    try:
        conn = _db()
        row = conn.execute("SELECT * FROM contests WHERE id=?", (cid,)).fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as e:
        print("contests_get err:", e)
        return None


def contests_add(title, description="", kind="event", prize="", icon="", image="",
                 starts_at=0, ends_at=0, votes=None, answer=""):
    try:
        conn = _db()
        c = conn.cursor()
        # حوّل الخيارات النصية إلى مصفوفة أرقام
        votes_data = []
        labels_data = []
        if votes and isinstance(votes, list):
            for v in votes:
                votes_data.append(0)
                labels_data.append(str(v))
        # نخزّن النصوص في votes أيضاً — بس كـ JSON منفصل
        full_votes = {"labels": labels_data, "counts": votes_data}
        c.execute("""
            INSERT INTO contests (title, description, kind, prize, icon, image,
                                  starts_at, ends_at, status, pinned, votes, voters,
                                  answer, participants, created, updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', 0, ?, '[]', ?, '[]', ?, ?)
        """, (
            title, description, kind, prize, icon, image,
            starts_at, ends_at,
            json.dumps(full_votes, ensure_ascii=False),
            answer,
            time.time(), time.time()
        ))
        cid = c.lastrowid
        conn.commit()
        conn.close()
        return cid
    except Exception as e:
        print("contests_add err:", e)
        return None


def contests_update(cid, **fields):
    allowed = {"title","description","kind","prize","icon","image",
               "starts_at","ends_at","status","pinned","votes","answer","participants"}
    sets = []
    vals = []
    for k, v in fields.items():
        if k in allowed:
            if k == "votes" and isinstance(v, list):
                v = json.dumps(v, ensure_ascii=False)
            sets.append(k + "=?")
            vals.append(v)
    if not sets:
        return False
    sets.append("updated=?")
    vals.append(time.time())
    vals.append(cid)
    try:
        conn = _db()
        conn.execute("UPDATE contests SET " + ", ".join(sets) + " WHERE id=?", vals)
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print("contests_update err:", e)
        return False


def contests_toggle_pin(cid):
    """يبدّل حالة التثبيت"""
    c = contests_get(cid)
    if not c:
        return False
    new_val = 0 if c.get("pinned") else 1
    return contests_update(cid, pinned=new_val)


def contests_toggle_status(cid):
    """يبدّل بين active / paused"""
    c = contests_get(cid)
    if not c:
        return False
    new_val = "paused" if c.get("status") == "active" else "active"
    return contests_update(cid, status=new_val)


def contests_delete(cid):
    try:
        conn = _db()
        conn.execute("DELETE FROM contests WHERE id=?", (cid,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print("contests_delete err:", e)
        return False


def contests_vote(cid, user_key, choice_idx):
    """يصوّت مستخدم على خيار"""
    c = contests_get(cid)
    if not c:
        return False, "المسابقة غير موجودة"
    try:
        voters = json.loads(c.get("voters") or "[]")
    except:
        voters = []
    if user_key in voters:
        return False, "صوّت مسبقاً"
    votes = {}
    try:
        votes = json.loads(c.get("votes") or "{}")
    except:
        votes = {}
    # دعم الشكل القديم (قائمة)
    if isinstance(votes, list):
        labels = [str(v) for v in votes]
        counts = [0] * len(votes)
        votes = {"labels": labels, "counts": counts}
    if not isinstance(votes, dict):
        votes = {"labels": [], "counts": []}
    labels = votes.get("labels", [])
    counts = votes.get("counts", [])
    if choice_idx < 0 or choice_idx >= len(counts):
        return False, "خيار غير صحيح"
    counts[choice_idx] = (counts[choice_idx] or 0) + 1
    votes["counts"] = counts
    voters.append(user_key)
    try:
        conn = _db()
        conn.execute("UPDATE contests SET votes=?, voters=?, updated=? WHERE id=?",
                     (json.dumps(votes, ensure_ascii=False),
                      json.dumps(voters, ensure_ascii=False),
                      time.time(), cid))
        conn.commit()
        conn.close()
        return True, "تم التصويت"
    except Exception as e:
        return False, str(e)


# ═══════════════════════════════════════════
# ADMIN — المسابقات
# ═══════════════════════════════════════════
@app.route("/admin/contests")
@admin_required
def admin_contests():
    contests = contests_list()
    try:
        ads = ads_list()
    except Exception:
        ads = []
    try:
        social_posts = social_post_list(only_active=False, limit=100)
    except Exception:
        social_posts = []
    return render_template_string(
        CONTESTS_ADMIN_HTML,
        contests=contests,
        ads=ads,
        social_posts=social_posts,
        total=len(contests),
        pinned=sum(1 for c in contests if c.get("pinned")),
        active=sum(1 for c in contests if c.get("status") == "active"),
        paused=sum(1 for c in contests if c.get("status") == "paused"),
        ads_total=len(ads),
        ads_pinned=sum(1 for a in ads if a.get("pinned")),
        ads_active=sum(1 for a in ads if a.get("status") == "active"),
        ads_paused=sum(1 for a in ads if a.get("status") == "paused"),
        social_total=len(social_posts),
        social_pinned=sum(1 for p in social_posts if p.get("pinned")),
        social_active=sum(1 for p in social_posts if p.get("status") == "active"),
        social_paused=sum(1 for p in social_posts if p.get("status") == "paused")
    )


@app.route("/admin/contests/add", methods=["POST"])
@admin_required
def admin_contests_add():
    title = request.form.get("title", "").strip()
    if not title:
        return redirect(url_for("admin_contests"))
    desc = request.form.get("description", "").strip()
    kind = request.form.get("kind", "event").strip()
    prize = request.form.get("prize", "").strip()
    icon = request.form.get("icon", "").strip() or "🏆"
    image = request.form.get("image", "").strip()
    ends_at = 0
    ends_str = request.form.get("ends_at", "").strip()
    if ends_str:
        try:
            from datetime import datetime as _dt
            ends_at = _dt.strptime(ends_str, "%Y-%m-%dT%H:%M").timestamp()
        except:
            pass
    # خيارات التصويت
    votes = []
    if kind == "vote":
        for i in range(1, 5):
            v = request.form.get("vote_" + str(i), "").strip()
            if v:
                votes.append(v)
        if not votes:
            votes = []
    answer = request.form.get("answer", "").strip()
    contests_add(title, desc, kind, prize, icon, image, 0, ends_at, votes if votes else None, answer)
    return redirect(url_for("admin_contests"))


@app.route("/admin/contests/edit/<int:cid>", methods=["POST"])
@admin_required
def admin_contests_edit(cid):
    title = request.form.get("title", "").strip()
    if not title:
        return redirect(url_for("admin_contests"))
    desc = request.form.get("description", "").strip()
    kind = request.form.get("kind", "event").strip()
    prize = request.form.get("prize", "").strip()
    icon = request.form.get("icon", "").strip() or "🏆"
    ends_at = 0
    ends_str = request.form.get("ends_at", "").strip()
    if ends_str:
        try:
            from datetime import datetime as _dt
            ends_at = _dt.strptime(ends_str, "%Y-%m-%dT%H:%M").timestamp()
        except:
            pass
    answer = request.form.get("answer", "").strip()
    contests_update(cid, title=title, description=desc, kind=kind, prize=prize,
                    icon=icon, ends_at=ends_at, answer=answer)
    return redirect(url_for("admin_contests"))


@app.route("/admin/contests/toggle-pin/<int:cid>")
@admin_required
def admin_contests_toggle_pin(cid):
    contests_toggle_pin(cid)
    return redirect(url_for("admin_contests"))


@app.route("/admin/contests/toggle-status/<int:cid>")
@admin_required
def admin_contests_toggle_status(cid):
    contests_toggle_status(cid)
    return redirect(url_for("admin_contests"))


@app.route("/admin/contests/delete/<int:cid>")
@admin_required
def admin_contests_delete(cid):
    contests_delete(cid)
    return redirect(url_for("admin_contests"))


CONTESTS_ADMIN_HTML = r"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>المسابقات</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;font-family:-apple-system,'Segoe UI',Tahoma,sans-serif;-webkit-tap-highlight-color:transparent}
body{background:#07070d;color:#e8e8f0;min-height:100vh;padding:0 0 40px;direction:rtl}
.hdr{position:sticky;top:0;z-index:100;background:linear-gradient(135deg,#0c0c18,#12122a);border-bottom:1px solid rgba(123,47,247,.25);padding:16px 18px;display:flex;align-items:center;gap:14px;box-shadow:0 4px 24px rgba(0,0,0,.4)}
.hdr .back{padding:10px 14px;background:rgba(0,212,255,.12);border:1px solid rgba(0,212,255,.3);color:#00d4ff;border-radius:12px;font-size:12px;font-weight:700;text-decoration:none;display:flex;align-items:center;gap:6px;flex-shrink:0}
.hdr .back svg{width:14px;height:14px;fill:currentColor}
.hdr h1{font-size:19px;font-weight:900;background:linear-gradient(135deg,#7b2ff7,#00d4ff);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;flex:1}

.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;padding:14px 18px}
.stat{background:linear-gradient(160deg,#10101e,#0a0a14);border:1px solid rgba(123,47,247,.2);border-radius:14px;padding:12px 8px;text-align:center}
.stat b{font-size:20px;font-weight:900;display:block;margin-bottom:2px;color:#00d4ff}
.stat.gold b{color:#fbbf24}
.stat.green b{color:#00d4a5}
.stat.red b{color:#ff6b8a}
.stat span{font-size:10px;color:#6e6e8a}

.wrap{padding:0 18px}

.add-box{background:linear-gradient(160deg,#10101e,#0a0a14);border:1px solid rgba(123,47,247,.2);border-radius:18px;padding:18px;margin-bottom:18px}
.add-box h2{font-size:14px;color:#00d4ff;margin-bottom:14px;font-weight:800;display:flex;align-items:center;gap:8px}
.add-box h2 svg{width:18px;height:18px;fill:#00d4ff}

label{display:block;font-size:12px;color:#8e8eab;margin:12px 0 6px;font-weight:600}
label:first-of-type{margin-top:0}
input,textarea,select{width:100%;padding:12px 14px;border:1px solid rgba(255,255,255,.08);border-radius:12px;background:rgba(0,0,0,.35);color:#e8e8f0;font-size:14px;outline:none;font-family:inherit}
input:focus,textarea:focus,select:focus{border-color:#7b2ff7}

.kinds{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:8px}
.kind-btn{padding:12px 8px;border:1.5px solid rgba(123,47,247,.2);background:rgba(255,255,255,.02);border-radius:12px;color:#8e8eab;font-size:12px;font-weight:700;cursor:pointer;font-family:inherit;text-align:center;display:flex;flex-direction:column;align-items:center;gap:6px;transition:all .2s}
.kind-btn svg{width:22px;height:22px;fill:currentColor}
.kind-btn.active{background:linear-gradient(135deg,#7b2ff7,#00d4ff);border-color:transparent;color:#fff;box-shadow:0 4px 14px rgba(123,47,247,.35)}

.type-block{margin-top:14px;padding:14px;background:rgba(0,212,255,.05);border:1.5px dashed rgba(0,212,255,.25);border-radius:14px}
.type-block label{color:#00d4ff;margin-top:0;margin-bottom:10px;font-weight:800}
.type-block input{margin-bottom:8px}
.type-block input:last-child{margin-bottom:0}

.btn{width:100%;padding:14px;border:none;border-radius:13px;color:#fff;cursor:pointer;font-weight:800;font-size:14px;font-family:inherit;margin-top:14px}
.btn-grad{background:linear-gradient(135deg,#7b2ff7,#00d4ff);box-shadow:0 6px 20px rgba(123,47,247,.4)}
.btn:active{transform:scale(.97)}

.list{display:flex;flex-direction:column;gap:12px}
.c-card{background:linear-gradient(160deg,#10101e,#0a0a14);border:1px solid rgba(123,47,247,.18);border-radius:18px;padding:16px;position:relative}
.c-card.pinned{border-color:rgba(251,191,36,.5);background:linear-gradient(160deg,rgba(251,191,36,.06),rgba(251,191,36,.02))}
.c-card.paused{opacity:.55;filter:grayscale(.6)}
.c-head{display:flex;align-items:flex-start;gap:12px;margin-bottom:12px}
.c-ico{width:48px;height:48px;border-radius:14px;background:linear-gradient(135deg,#7b2ff7,#00d4ff);display:flex;align-items:center;justify-content:center;font-size:24px;flex-shrink:0}
.c-card.pinned .c-ico{background:linear-gradient(135deg,#fbbf24,#f59e0b)}
.c-card.paused .c-ico{background:linear-gradient(135deg,#6e6e8a,#4a4a5e)}
.c-info{flex:1;min-width:0}
.c-title{font-size:15px;font-weight:800;color:#fff;margin-bottom:4px;word-break:break-word}
.c-desc{font-size:12px;color:#8e8eab;line-height:1.5;margin-bottom:6px}
.c-meta{display:flex;flex-wrap:wrap;gap:6px;font-size:10px}
.c-tag{padding:3px 9px;border-radius:8px;font-weight:700;background:rgba(0,212,255,.12);color:#00d4ff}
.c-tag.pin{background:rgba(251,191,36,.15);color:#fbbf24}
.c-tag.pause{background:rgba(255,107,138,.15);color:#ff6b8a}
.c-tag.kind{background:rgba(123,47,247,.15);color:#c8a2ff}
.c-tag.prize{background:rgba(0,212,165,.15);color:#00d4a5}

.c-actions{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:10px}
.c-act{padding:10px 6px;border:none;border-radius:10px;cursor:pointer;font-size:11px;font-weight:700;font-family:inherit;display:flex;flex-direction:column;align-items:center;gap:4px;text-decoration:none;color:#fff;transition:all .2s}
.c-act svg{width:16px;height:16px;fill:currentColor}
.c-act:active{transform:scale(.95)}
.c-act.pin-on{background:rgba(251,191,36,.2);color:#fbbf24;border:1px solid rgba(251,191,36,.4)}
.c-act.pin-off{background:rgba(123,47,247,.15);color:#c8a2ff;border:1px solid rgba(123,47,247,.3)}
.c-act.pause{background:rgba(255,107,138,.15);color:#ff6b8a;border:1px solid rgba(255,107,138,.3)}
.c-act.resume{background:rgba(0,212,165,.15);color:#00d4a5;border:1px solid rgba(0,212,165,.3)}
.c-act.edit{background:rgba(0,212,255,.15);color:#00d4ff;border:1px solid rgba(0,212,255,.3)}
.c-act.del{background:rgba(233,69,96,.15);color:#ff6b8a;border:1px solid rgba(233,69,96,.3)}

.empty{text-align:center;padding:50px 20px;color:#6e6e8a}
.empty svg{width:64px;height:64px;fill:#2a2a35;margin-bottom:14px;display:block;margin-left:auto;margin-right:auto}

/* تبويبات الصفحة */
.page-tabs{display:flex;gap:8px;padding:14px 18px 4px;margin-bottom:4px}
.page-tab{flex:1;padding:12px 16px;border-radius:14px;border:1.5px solid rgba(123,47,247,.2);background:rgba(255,255,255,.03);color:#8e8eab;font-size:13px;font-weight:800;cursor:pointer;font-family:inherit;display:flex;align-items:center;justify-content:center;gap:8px;transition:all .25s}
.page-tab svg{width:18px;height:18px;fill:currentColor}
.page-tab.active{background:linear-gradient(135deg,#7b2ff7,#00d4ff);border-color:transparent;color:#fff;box-shadow:0 6px 20px rgba(123,47,247,.4);transform:translateY(-1px)}
.page-tab:active{transform:scale(.96)}
.tab-pane{display:none}
.tab-pane.active{display:block}

/* بطاقات الإعلانات */
.a-card{background:linear-gradient(160deg,#10101e,#0a0a14);border:1px solid rgba(123,47,247,.18);border-radius:18px;padding:16px;position:relative;margin-bottom:12px}
.a-card.pinned{border-color:rgba(251,191,36,.5);background:linear-gradient(160deg,rgba(251,191,36,.06),rgba(251,191,36,.02))}
.a-card.paused{opacity:.55;filter:grayscale(.6)}
.a-head{display:flex;align-items:flex-start;gap:12px;margin-bottom:12px}
.a-ico{width:48px;height:48px;border-radius:14px;background:linear-gradient(135deg,#7b2ff7,#00d4ff);display:flex;align-items:center;justify-content:center;font-size:24px;flex-shrink:0;overflow:hidden}
.a-ico img{width:100%;height:100%;object-fit:cover}
.a-card.pinned .a-ico{background:linear-gradient(135deg,#fbbf24,#f59e0b)}
.a-info{flex:1;min-width:0}
.a-title{font-size:15px;font-weight:800;color:#fff;margin-bottom:4px;word-break:break-word}
.a-body{font-size:12px;color:#8e8eab;line-height:1.5;margin-bottom:6px}
.a-meta{display:flex;flex-wrap:wrap;gap:6px;font-size:10px}
.a-tag{padding:3px 9px;border-radius:8px;font-weight:700;background:rgba(0,212,255,.12);color:#00d4ff}
.a-tag.pin{background:rgba(251,191,36,.15);color:#fbbf24}
.a-tag.pause{background:rgba(255,107,138,.15);color:#ff6b8a}
.a-tag.img{background:rgba(0,212,165,.15);color:#00d4a5}

.a-thumbs{display:flex;gap:6px;margin:10px 0;overflow-x:auto;scrollbar-width:none;padding-bottom:4px}
.a-thumbs::-webkit-scrollbar{display:none}
.a-thumb{width:60px;height:60px;border-radius:10px;flex-shrink:0;position:relative;overflow:hidden;background:rgba(0,0,0,.3);border:1px solid rgba(123,47,247,.2)}
.a-thumb img{width:100%;height:100%;object-fit:cover}
.a-thumb .rm{position:absolute;top:2px;right:2px;width:20px;height:20px;background:rgba(233,69,96,.9);color:#fff;border:none;border-radius:50%;cursor:pointer;font-size:12px;font-weight:900;line-height:1;padding:0;display:flex;align-items:center;justify-content:center;text-decoration:none}

.a-actions{display:grid;grid-template-columns:repeat(5,1fr);gap:6px;margin-top:10px}
.a-act{padding:10px 4px;border:none;border-radius:10px;cursor:pointer;font-size:10px;font-weight:700;font-family:inherit;display:flex;flex-direction:column;align-items:center;gap:4px;text-decoration:none;color:#fff;transition:all .2s}
.a-act svg{width:16px;height:16px;fill:currentColor}
.a-act:active{transform:scale(.95)}
.a-act.pin-on{background:rgba(251,191,36,.2);color:#fbbf24;border:1px solid rgba(251,191,36,.4)}
.a-act.pin-off{background:rgba(123,47,247,.15);color:#c8a2ff;border:1px solid rgba(123,47,247,.3)}
.a-act.pause{background:rgba(255,107,138,.15);color:#ff6b8a;border:1px solid rgba(255,107,138,.3)}
.a-act.resume{background:rgba(0,212,165,.15);color:#00d4a5;border:1px solid rgba(0,212,165,.3)}
.a-act.up{background:rgba(0,212,255,.15);color:#00d4ff;border:1px solid rgba(0,212,255,.3)}
.a-act.edit{background:rgba(0,212,255,.15);color:#00d4ff;border:1px solid rgba(0,212,255,.3)}
.a-act.del{background:rgba(233,69,96,.15);color:#ff6b8a;border:1px solid rgba(233,69,96,.3)}

.upload-zone{padding:20px;border:2px dashed rgba(0,212,255,.4);border-radius:14px;background:rgba(0,212,255,.05);text-align:center;cursor:pointer;display:block}
.upload-zone svg{width:36px;height:36px;fill:#00d4ff;margin-bottom:8px;display:block;margin-left:auto;margin-right:auto}
.upload-zone p{font-size:13px;color:#c8c8d8;font-weight:600;margin:0}
.upload-zone small{font-size:11px;color:#6e6e8a;display:block;margin-top:4px}
.upload-zone input{display:none}

/* قيود الصور في قوائم الأدمن */
.a-thumb{width:56px !important;height:56px !important}
.c-ico img{max-width:100%;max-height:100%;object-fit:cover}

/* ═══ محرر الأزرار المخصصة ═══ */
.btns-editor{margin-top:14px;padding:14px;background:rgba(0,212,255,.05);border:1.5px dashed rgba(0,212,255,.3);border-radius:14px}
.btns-editor h3{font-size:13px;color:#00d4ff;margin-bottom:10px;font-weight:800;display:flex;align-items:center;gap:6px}
.btn-item{background:rgba(0,0,0,.35);border:1px solid rgba(123,47,247,.25);border-radius:12px;padding:12px;margin-bottom:10px;position:relative}
.btn-item-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;padding-bottom:8px;border-bottom:1px solid rgba(255,255,255,.06)}
.btn-item-num{font-size:11px;color:#8e8eab;font-weight:700}
.btn-item-remove{background:rgba(255,107,138,.15);border:1px solid rgba(255,107,138,.3);color:#ff6b8a;width:28px;height:28px;border-radius:8px;cursor:pointer;font-size:14px;font-weight:900;padding:0;line-height:1}
.btn-item label{font-size:11px;color:#8e8eab;margin:8px 0 4px;display:block;font-weight:600}
.btn-item input[type=text]{width:100%;padding:9px 12px;font-size:13px;border-radius:10px}
.btn-item input[type=color]{width:100%;height:38px;padding:2px;border-radius:10px;cursor:pointer}
.btn-icon-grid{display:grid;grid-template-columns:repeat(6,1fr);gap:4px;margin-top:6px}
.btn-icon-opt{padding:6px 2px;border:1.5px solid rgba(255,255,255,.1);border-radius:9px;background:rgba(0,0,0,.3);cursor:pointer;display:flex;align-items:center;justify-content:center;aspect-ratio:1}
.btn-icon-opt svg{width:100%;height:100%;fill:#8e8eab}
.btn-icon-opt.active{border-color:#00d4ff;background:rgba(0,212,255,.15)}
.btn-icon-opt.active svg{fill:#00d4ff}
.btn-icon-opt:active{transform:scale(.92)}
.btn-icon-custom{margin-top:6px;font-size:11px;font-family:monospace;direction:ltr;text-align:left;resize:vertical;min-height:50px;width:100%;padding:8px;background:rgba(0,0,0,.4);border:1px solid rgba(255,255,255,.1);border-radius:9px;color:#e8e8f0}
.btn-add-btn{width:100%;padding:12px;border:1.5px dashed rgba(0,212,255,.5);border-radius:12px;background:rgba(0,212,255,.05);color:#00d4ff;font-weight:800;font-size:13px;cursor:pointer;font-family:inherit;display:flex;align-items:center;justify-content:center;gap:6px;transition:all .2s}
.btn-add-btn:hover{background:rgba(0,212,255,.12)}
.btn-add-btn:active{transform:scale(.97)}
.btn-preview-bar{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px;padding:10px;background:rgba(0,0,0,.3);border-radius:10px;min-height:44px;align-items:center;justify-content:center}
.btn-preview-bar:empty::before{content:"معاينة الأزرار ستظهر هنا";color:#4a4a5e;font-size:11px}
.btn-preview-pill{padding:8px 14px;border-radius:10px;color:#fff;font-weight:700;font-size:12px;display:inline-flex;align-items:center;gap:6px}
.btn-preview-pill svg{width:16px;height:16px;fill:currentColor}

/* ═══ محرر شريط المعلومات ═══ */
.info-editor{margin-top:14px;padding:14px;background:rgba(123,47,247,.05);border:1.5px dashed rgba(123,47,247,.3);border-radius:14px}
.info-editor h3{font-size:13px;color:#c8a2ff;margin-bottom:10px;font-weight:800;display:flex;align-items:center;gap:6px}
.info-editor h3 svg{width:16px;height:16px;fill:#c8a2ff}
.info-toolbar{display:flex;flex-wrap:wrap;gap:4px;background:rgba(0,0,0,.4);padding:6px;border-radius:10px;margin-bottom:8px;border:1px solid rgba(255,255,255,.08)}
.info-tb-btn{width:34px;height:34px;border:none;background:rgba(255,255,255,.05);border-radius:8px;cursor:pointer;color:#e8e8f0;font-weight:900;font-size:14px;display:flex;align-items:center;justify-content:center;font-family:inherit;transition:all .15s;padding:0}
.info-tb-btn:hover{background:rgba(123,47,247,.25);color:#c8a2ff}
.info-tb-btn:active{transform:scale(.92)}
.info-tb-btn.bold{font-weight:900}
.info-tb-btn.italic{font-style:italic;font-family:Georgia,serif}
.info-tb-btn.underline{text-decoration:underline}
.info-tb-btn.color{background:linear-gradient(135deg,#7b2ff7,#00d4ff);color:#fff}
.info-tb-sep{width:1px;background:rgba(255,255,255,.1);margin:4px 2px}
.info-color-picker{display:flex;flex-wrap:wrap;gap:4px;margin-bottom:8px;display:none}
.info-color-picker.show{display:flex}
.info-color-opt{width:28px;height:28px;border-radius:50%;border:2px solid rgba(255,255,255,.2);cursor:pointer;padding:0}
.info-color-opt:active{transform:scale(.9)}
.info-editor-textarea{width:100%;min-height:80px;padding:10px 12px;font-size:13px;font-family:inherit;background:rgba(0,0,0,.4);border:1px solid rgba(255,255,255,.1);border-radius:10px;color:#e8e8f0;resize:vertical;outline:none;line-height:1.6}
.info-editor-textarea:focus{border-color:#7b2ff7}
.info-preview{margin-top:8px;padding:10px 12px;background:rgba(0,0,0,.35);border:1px solid rgba(0,212,255,.2);border-radius:10px;min-height:44px;font-size:13px;line-height:1.7;color:#e8e8f0;word-break:break-word}
.info-preview:empty::before{content:"معاينة الشريط ستظهر هنا";color:#4a4a5e;font-size:11px}
</style>
</head>
<body>

<div class="hdr">
<a href="/admin" class="back">
<svg viewBox="0 0 24 24"><path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z"/></svg>
الأدمن
</a>
<h1>المسابقات</h1>
</div>

<div class="page-tabs">
<button type="button" class="page-tab active" id="tabBtnContests" onclick="switchPageTab('contests')">
<svg viewBox="0 0 24 24"><path d="M19 5h-2V3H7v2H5c-1.1 0-2 .9-2 2v1c0 2.55 1.92 4.63 4.39 4.94.63 1.5 1.98 2.63 3.61 2.96V19H7v2h10v-2h-4v-3.1c1.63-.33 2.98-1.46 3.61-2.96C19.08 12.63 21 10.55 21 8V7c0-1.1-.9-2-2-2zM5 8V7h2v3.82C5.84 10.4 5 9.3 5 8zm14 0c0 1.3-.84 2.4-2 2.82V7h2v1z"/></svg>
المسابقات
</button>
<button type="button" class="page-tab" id="tabBtnAds" onclick="switchPageTab('ads')">
<svg viewBox="0 0 24 24"><path d="M18 11v2h4v-2h-4zm-2 6.61c.96.71 2.21 1.65 3.2 2.39.4-.53.8-1.07 1.2-1.6-.99-.74-2.24-1.68-3.2-2.4-.4.54-.8 1.08-1.2 1.61zM20.4 5.6c-.4-.53-.8-1.07-1.2-1.6-.99.74-2.24 1.68-3.2 2.4.4.53.8 1.07 1.2 1.6.96-.72 2.21-1.65 3.2-2.4zM4 9c-1.1 0-2 .9-2 2v2c0 1.1.9 2 2 2h1v4h2v-4h1l5 3V6L8 9H4z"/></svg>
الإعلانات
</button>
<button type="button" class="page-tab" id="tabBtnSocial" onclick="switchPageTab('social')">
<svg viewBox="0 0 24 24"><path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z"/></svg>
اجتماعي
</button>
</div>

<div id="paneTabContests" class="tab-pane active">
<div class="stats">
<div class="stat"><b>{{ total }}</b><span>الكل</span></div>
<div class="stat gold"><b>{{ pinned }}</b><span>مثبتة</span></div>
<div class="stat green"><b>{{ active }}</b><span>نشطة</span></div>
<div class="stat red"><b>{{ paused }}</b><span>موقوفة</span></div>
</div>

<div class="wrap">

<div class="add-box">
<h2>
<svg viewBox="0 0 24 24"><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/></svg>
إضافة مسابقة جديدة
</h2>

<form method="POST" action="/admin/contests/add">
<label>نوع المسابقة</label>
<div class="kinds">
<button type="button" class="kind-btn active" onclick="pickKind(this,'event')" data-kind="event">
<svg viewBox="0 0 24 24"><path d="M19 3h-1V1h-2v2H8V1H6v2H5c-1.11 0-1.99.9-1.99 2L3 19c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm0 16H5V8h14v11z"/></svg>
حدث
</button>
<button type="button" class="kind-btn" onclick="pickKind(this,'vote')" data-kind="vote">
<svg viewBox="0 0 24 24"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>
تصويت
</button>
<button type="button" class="kind-btn" onclick="pickKind(this,'question')" data-kind="question">
<svg viewBox="0 0 24 24"><path d="M11 18h2v-2h-2v2zm1-16C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8zm0-14c-2.21 0-4 1.79-4 4h2c0-1.1.9-2 2-2s2 .9 2 2c0 2-3 1.75-3 5h2c0-2.25 3-2.5 3-5 0-2.21-1.79-4-4-4z"/></svg>
سؤال
</button>
</div>
<input type="hidden" name="kind" id="kindInput" value="event">

<label>عنوان المسابقة</label>
<input type="text" name="title" placeholder="مثال: مسابقة الأسبوع" maxlength="100">

<label>الوصف</label>
<textarea name="description" rows="3" placeholder="تفاصيل المسابقة..." style="resize:vertical" maxlength="500"></textarea>

<label>الجائزة</label>
<input type="text" name="prize" placeholder="مثال: 500 ريال / حساب PRO" maxlength="100">

<label>أيقونة (إيموجي)</label>
<input type="text" name="icon" placeholder="🏆" maxlength="4" value="🏆">

<label>تاريخ الانتهاء</label>
<input type="datetime-local" name="ends_at">

<!-- خيارات نوع تصويت -->
<div class="type-block" id="voteOpts" style="display:none">
<label>خيارات التصويت</label>
<input type="text" name="vote_1" placeholder="الخيار 1">
<input type="text" name="vote_2" placeholder="الخيار 2">
<input type="text" name="vote_3" placeholder="الخيار 3">
<input type="text" name="vote_4" placeholder="الخيار 4">
</div>

<!-- خيارات نوع سؤال -->
<div class="type-block" id="answerOpts" style="display:none">
<label>الجواب الصحيح</label>
<input type="text" name="answer" placeholder="اكتب الجواب هنا">
</div>

<button type="submit" class="btn btn-grad">
<svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:#fff;vertical-align:middle;margin-left:6px"><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/></svg>
إضافة المسابقة
</button>
</form>
</div>

<h2 style="font-size:14px;color:#8e8eab;margin-bottom:12px;font-weight:800">المسابقات الحالية ({{ total }})</h2>

<div class="list">
{% if contests %}
{% for c in contests %}
<div class="c-card {% if c.pinned %}pinned{% endif %} {% if c.status == 'paused' %}paused{% endif %}">
<div class="c-head">
<div class="c-ico">{% if c.icon and c.icon not in ['🏆',''] %}{{ c.icon }}{% else %}<svg viewBox="0 0 24 24" style="width:26px;height:26px;fill:#fff"><path d="M19 5h-2V3H7v2H5c-1.1 0-2 .9-2 2v1c0 2.55 1.92 4.63 4.39 4.94.63 1.5 1.98 2.63 3.61 2.96V19H7v2h10v-2h-4v-3.1c1.63-.33 2.98-1.46 3.61-2.96C19.08 12.63 21 10.55 21 8V7c0-1.1-.9-2-2-2zM5 8V7h2v3.82C5.84 10.4 5 9.3 5 8zm14 0c0 1.3-.84 2.4-2 2.82V7h2v1z"/></svg>{% endif %}</div>
<div class="c-info">
<div class="c-title">{{ c.title }}</div>
{% if c.description %}<div class="c-desc">{{ c.description }}</div>{% endif %}
<div class="c-meta">
{% if c.pinned %}<span class="c-tag pin"><svg viewBox="0 0 24 24" style="width:1em;height:1em;fill:currentColor;vertical-align:middle"><path d="M16 12V4h1V2H7v2h1v8l-2 2v2h5.2v6h1.6v-6H18v-2l-2-2z"/></svg> مثبتة</span>{% endif %}
{% if c.status == 'paused' %}<span class="c-tag pause"><svg viewBox="0 0 24 24" style="width:1em;height:1em;fill:currentColor;vertical-align:middle"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg> موقوفة</span>{% else %}<span class="c-tag">نشطة</span>{% endif %}
<span class="c-tag kind">{% if c.kind == 'vote' %}<svg viewBox="0 0 24 24" style="width:1em;height:1em;fill:currentColor;vertical-align:middle"><path d="M18 13h-.68l-2 2h1.91L19 17H5l1.78-2h2.05l-2-2H6l-3 3v4c0 1.1.89 2 1.99 2H19c1.1 0 2-.9 2-2v-4l-3-3zm-1-5.05l-4.95 4.95-3.54-3.54 4.95-4.95L17 7.95zm-4.24-5.66L6.39 8.66c-.39.39-.39 1.02 0 1.41l4.95 4.95c.39.39 1.02.39 1.41 0l6.36-6.36c.39-.39.39-1.02 0-1.41L14.16 2.3c-.38-.4-1.01-.4-1.4-.01z"/></svg> تصويت{% elif c.kind == 'question' %}<svg viewBox="0 0 24 24" style="width:1em;height:1em;fill:currentColor;vertical-align:middle"><path d="M11 18h2v-2h-2v2zm1-16C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8zm0-14c-2.21 0-4 1.79-4 4h2c0-1.1.9-2 2-2s2 .9 2 2c0 2-3 1.75-3 5h2c0-2.25 3-2.5 3-5 0-2.21-1.79-4-4-4z"/></svg> سؤال{% else %}<svg viewBox="0 0 24 24" style="width:1em;height:1em;fill:currentColor;vertical-align:middle"><path d="M19 3h-1V1h-2v2H8V1H6v2H5c-1.11 0-1.99.9-1.99 2L3 19c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm0 16H5V8h14v11zM7 10h5v5H7z"/></svg> حدث{% endif %}</span>
{% if c.prize %}<span class="c-tag prize"><svg viewBox="0 0 24 24" style="width:1em;height:1em;fill:currentColor;vertical-align:middle"><path d="M20 6h-2.18c.11-.31.18-.65.18-1a2.996 2.996 0 00-5.5-1.65l-.5.67-.5-.68C10.96 2.54 10.05 2 9 2 7.34 2 6 3.34 6 5c0 .35.07.69.18 1H4c-1.11 0-1.99.89-1.99 2L2 19c0 1.11.89 2 2 2h16c1.11 0 2-.89 2-2V8c0-1.11-.89-2-2-2zm-5-2c.55 0 1 .45 1 1s-.45 1-1 1-1-.45-1-1 .45-1 1-1zM9 4c.55 0 1 .45 1 1s-.45 1-1 1-1-.45-1-1 .45-1 1-1zm11 15H4v-2h16v2zm0-5H4V8h5.08L7 10.83 8.62 12 11 8.76l1-1.36 1 1.36L15.38 12 17 10.83 14.92 8H20v6z"/></svg> {{ c.prize }}</span>{% endif %}
</div>
</div>
</div>

<div class="c-actions" style="grid-template-columns:repeat(5,1fr)">
<button type="button" class="c-act" style="background:rgba(0,212,165,.15);color:#00d4a5;border:1px solid rgba(0,212,165,.3)" onclick="showVoters({{ c.id }})" title="المصوتون">
<svg viewBox="0 0 24 24"><path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z"/></svg>
المصوتون
</button>
<a href="/admin/contests/toggle-pin/{{ c.id }}" class="c-act {% if c.pinned %}pin-on{% else %}pin-off{% endif %}" title="تثبيت">
<svg viewBox="0 0 24 24"><path d="M16 12V4h1V2H7v2h1v8l-2 2v2h5.2v6h1.6v-6H18v-2l-2-2z"/></svg>
{% if c.pinned %}إلغاء{% else %}تثبيت{% endif %}
</a>
<a href="/admin/contests/toggle-status/{{ c.id }}" class="c-act {% if c.status == 'paused' %}resume{% else %}pause{% endif %}" title="إيقاف/تشغيل">
{% if c.status == 'paused' %}
<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
تشغيل
{% else %}
<svg viewBox="0 0 24 24"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>
إيقاف
{% endif %}
</a>
<button type="button" class="c-act edit" data-id="{{ c.id }}" data-title="{{ c.title|e }}" data-desc="{{ c.description|e }}" data-kind="{{ c.kind }}" data-prize="{{ c.prize|e }}" data-icon="{{ c.icon|e }}" onclick="editContest2(this)">
<svg viewBox="0 0 24 24"><path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.39-.39-1.02-.39-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/></svg>
تعديل
</button>
<a href="/admin/contests/delete/{{ c.id }}" class="c-act del" onclick="return confirm('حذف {{ c.title }}؟')">
<svg viewBox="0 0 24 24"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>
حذف
</a>
</div>
</div>
{% endfor %}
{% else %}
<div class="empty">
<svg viewBox="0 0 24 24"><path d="M19 5h-2V3H7v2H5c-1.1 0-2 .9-2 2v1c0 2.55 1.92 4.63 4.39 4.94.63 1.5 1.98 2.63 3.61 2.96V19H7v2h10v-2h-4v-3.1c1.63-.33 2.98-1.46 3.61-2.96C19.08 12.63 21 10.55 21 8V7c0-1.1-.9-2-2-2z"/></svg>
لا توجد مسابقات بعد — أضف واحدة من الأعلى
</div>
{% endif %}
</div>

</div>

<div id="editModal" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.8);z-index:9999;align-items:center;justify-content:center;padding:20px">
<div style="background:#10101e;border:1px solid rgba(123,47,247,.3);border-radius:18px;padding:20px;max-width:480px;width:100%;max-height:90vh;overflow-y:auto">
<h3 style="color:#00d4ff;margin-bottom:14px;font-size:15px">تعديل المسابقة</h3>
<form method="POST" id="editForm">
<label>العنوان</label><input type="text" name="title" id="eTitle">
<label>الوصف</label><textarea name="description" id="eDesc" rows="3" style="resize:vertical"></textarea>
<label>الجائزة</label><input type="text" name="prize" id="ePrize">
<label>الأيقونة</label><input type="text" name="icon" id="eIcon" maxlength="4">
<label>النوع</label>
<select name="kind" id="eKind">
<option value="event">حدث</option>
<option value="vote">تصويت</option>
<option value="question">سؤال</option>
</select>
<label>تاريخ الانتهاء</label><input type="datetime-local" name="ends_at" id="eEnds">
<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:14px">
<button type="submit" class="btn btn-grad" style="margin-top:0">حفظ</button>
<button type="button" class="btn" style="margin-top:0;background:rgba(255,107,138,.15);color:#ff6b8a" onclick="closeEdit()">إلغاء</button>
</div>
</form>
</div>
</div>

<script>
function pickKind(btn, kind){
    document.querySelectorAll('.kind-btn').forEach(function(b){ b.classList.remove('active'); });
    btn.classList.add('active');
    document.getElementById('kindInput').value = kind;
    var voteBox = document.getElementById('voteOpts');
    var answerBox = document.getElementById('answerOpts');
    voteBox.style.display = 'none';
    answerBox.style.display = 'none';
    if(kind === 'vote') voteBox.style.display = 'block';
    else if(kind === 'question') answerBox.style.display = 'block';
}
document.addEventListener('DOMContentLoaded', function(){
    pickKind(document.querySelector('.kind-btn.active'), 'event');
});

function editContest2(btn){
    var d = btn.dataset;
    document.getElementById('eTitle').value = d.title || '';
    document.getElementById('eDesc').value = d.desc || '';
    document.getElementById('eKind').value = d.kind || 'event';
    document.getElementById('ePrize').value = d.prize || '';
    document.getElementById('eIcon').value = d.icon || '';
    document.getElementById('editForm').action = '/admin/contests/edit/' + d.id;
    document.getElementById('editModal').style.display = 'flex';
}

// دالة قديمة — للتوافق
function editContest(id, title, desc, kind, prize, icon){
    document.getElementById('eTitle').value = title;
    document.getElementById('eDesc').value = desc;
    document.getElementById('eKind').value = kind;
    document.getElementById('ePrize').value = prize;
    document.getElementById('eIcon').value = icon;
    document.getElementById('editForm').action = '/admin/contests/edit/' + id;
    document.getElementById('editModal').style.display = 'flex';
}

function closeEdit(){
    document.getElementById('editModal').style.display = 'none';
}
</script>


<div id="votersModal" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.85);z-index:99999;align-items:center;justify-content:center;padding:16px">
<div style="background:#10101e;border:1px solid rgba(0,212,165,.35);border-radius:20px;padding:20px;max-width:520px;width:100%;max-height:85vh;overflow-y:auto">
<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;padding-bottom:12px;border-bottom:1px solid rgba(255,255,255,.08)">
<h3 style="color:#00d4a5;font-size:16px;font-weight:900;margin:0;display:flex;align-items:center;gap:8px">
<svg viewBox="0 0 24 24" style="width:20px;height:20px;fill:#00d4a5"><path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z"/></svg>
المصوتون
</h3>
<button type="button" onclick="closeVoters()" style="background:rgba(255,107,138,.15);border:1px solid rgba(255,107,138,.3);color:#ff6b8a;width:32px;height:32px;border-radius:10px;cursor:pointer;font-size:18px;font-weight:900">×</button>
</div>
<div id="votersTitle" style="font-size:14px;color:#e8e8f0;font-weight:800;margin-bottom:12px"></div>
<div id="votersStats" style="display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-bottom:16px"></div>
<div id="votersList"></div>
</div>
</div>

<script>
function showVoters(cid){
    var modal = document.getElementById('votersModal');
    var title = document.getElementById('votersTitle');
    var list = document.getElementById('votersList');
    var stats = document.getElementById('votersStats');
    modal.style.display = 'flex';
    title.textContent = 'جاري التحميل...';
    list.innerHTML = '';
    stats.innerHTML = '';
    fetch('/api/contest-voters/' + cid)
        .then(function(r){ return r.json(); })
        .then(function(d){
            if(!d.ok){
                title.textContent = 'خطأ: ' + (d.error || '');
                return;
            }
            title.textContent = d.title || '';
            var total = d.total || 0;
            var totalVotes = (d.counts || []).reduce(function(a,b){ return a + (b||0); }, 0);
            stats.innerHTML =
                '<div style="background:rgba(0,212,165,.1);border:1px solid rgba(0,212,165,.3);border-radius:12px;padding:12px;text-align:center">' +
                '<b style="display:block;font-size:22px;color:#00d4a5;font-weight:900">' + total + '</b>' +
                '<span style="font-size:11px;color:#6e6e8a">عدد المصوتين</span></div>' +
                '<div style="background:rgba(0,212,255,.1);border:1px solid rgba(0,212,255,.3);border-radius:12px;padding:12px;text-align:center">' +
                '<b style="display:block;font-size:22px;color:#00d4ff;font-weight:900">' + totalVotes + '</b>' +
                '<span style="font-size:11px;color:#6e6e8a">إجمالي الأصوات</span></div>';
            if(!d.voters || d.voters.length === 0){
                list.innerHTML = '<div style="text-align:center;padding:30px;color:#6e6e8a;font-size:13px">لا يوجد مصوتون بعد</div>';
                return;
            }
            list.innerHTML = d.voters.map(function(v, i){
                var av = v.avatar ? '<img src="' + v.avatar + '" style="width:100%;height:100%;object-fit:cover;border-radius:50%">' : '<span style="color:#fff;font-weight:900;font-size:14px">' + (v.display || v.username || 'U')[0].toUpperCase() + '</span>';
                return '<div style="display:flex;align-items:center;gap:12px;padding:10px;background:rgba(0,0,0,.25);border:1px solid rgba(255,255,255,.05);border-radius:12px;margin-bottom:6px">' +
                    '<div style="width:40px;height:40px;border-radius:50%;background:linear-gradient(135deg,#7b2ff7,#00d4ff);display:flex;align-items:center;justify-content:center;flex-shrink:0;overflow:hidden">' + av + '</div>' +
                    '<div style="flex:1;min-width:0">' +
                    '<div style="font-size:13px;font-weight:800;color:#e8e8f0">' + (v.display || v.username) + '</div>' +
                    '<div style="font-size:10px;color:#6e6e8a;font-family:monospace;direction:ltr">@' + (v.username || '') + '</div>' +
                    '</div>' +
                    '<span style="background:rgba(123,47,247,.15);color:#c8a2ff;font-size:10px;font-weight:800;padding:3px 10px;border-radius:10px">#' + (i+1) + '</span>' +
                    '</div>';
            }).join('');
        })
        .catch(function(e){
            title.textContent = 'خطأ: ' + e.message;
        });
}
function closeVoters(){
    document.getElementById('votersModal').style.display = 'none';
}
</script>

</div><!-- /paneTabContests -->

<div id="paneTabSocial" class="tab-pane">

<div class="stats">
<div class="stat"><b>{{ social_total }}</b><span>الكل</span></div>
<div class="stat gold"><b>{{ social_pinned }}</b><span>مثبتة</span></div>
<div class="stat green"><b>{{ social_active }}</b><span>نشطة</span></div>
<div class="stat red"><b>{{ social_paused }}</b><span>موقوفة</span></div>
</div>

<div class="wrap">

<div class="add-box">
<h2>
<svg viewBox="0 0 24 24"><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/></svg>
منشور جديد
</h2>

<form method="POST" action="/admin/social/add" enctype="multipart/form-data">
<label>النص</label>
<textarea name="body" rows="3" placeholder="اكتب نص المنشور..." style="resize:vertical" maxlength="2000"></textarea>

<label>الصور / الفيديو / الملفات</label>
<label class="upload-zone">
<svg viewBox="0 0 24 24"><path d="M9 16h6v-6h4l-7-7-7 7h4zm-4 2h14v2H5z"/></svg>
<p>اضغط لاختيار الملفات</p>
<small>صور: jpg, png, gif, webp | فيديو: mp4, mov, webm | ملفات: pdf, zip, doc...</small>
<input type="file" name="files" accept="image/*,video/*,.pdf,.zip,.rar,.doc,.docx,.xls,.xlsx,.txt,.ppt,.pptx,.apk" multiple onchange="document.getElementById('socialFname').textContent=this.files.length+' ملف مختار'">
</label>
<div id="socialFname" style="font-size:12px;color:#00d4a5;margin-top:8px;text-align:center;font-weight:700"></div>

<button type="submit" class="btn btn-grad">
<svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:#fff;vertical-align:middle;margin-left:6px"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
نشر
</button>
</form>
</div>

<h2 style="font-size:14px;color:#8e8eab;margin-bottom:12px;font-weight:800">المنشورات ({{ social_total }})</h2>

<div class="list">
{% if social_posts %}
{% for p in social_posts %}
<div class="c-card {% if p.pinned %}pinned{% endif %} {% if p.status == 'paused' %}paused{% endif %}">
<div class="c-head">
<div class="c-ico">
{% if p.media and p.media|length > 0 and p.media[0].type == 'image' %}
<img src="/uploads/{{ p.media[0].src }}" alt="">
{% elif p.media and p.media|length > 0 and p.media[0].type == 'video' %}
<svg viewBox="0 0 24 24" style="width:24px;height:24px;fill:#fff"><path d="M17 10.5V7c0-.55-.45-1-1-1H4c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h12c.55 0 1-.45 1-1v-3.5l4 4v-11l-4 4z"/></svg>
{% elif p.attach %}
<svg viewBox="0 0 24 24" style="width:24px;height:24px;fill:#fff"><path d="M14 2H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V8l-6-6zm4 18H6V4h7v5h5v11z"/></svg>
{% else %}
<svg viewBox="0 0 24 24" style="width:24px;height:24px;fill:#fff"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/></svg>
{% endif %}
</div>
<div class="c-info">
<div class="c-title">{{ p.author }}</div>
<div class="c-desc">{{ p.body[:100] }}{% if p.body|length > 100 %}...{% endif %}</div>
<div class="c-meta">
{% if p.pinned %}<span class="c-tag pin">مثبت</span>{% endif %}
{% if p.status == 'paused' %}<span class="c-tag pause">موقوف</span>{% else %}<span class="c-tag">نشط</span>{% endif %}
<span class="c-tag kind">{{ p.kind }}</span>
<span class="c-tag">💬 {{ p.comments_count }}</span>
<span class="c-tag">❤️ {{ p.likes_count }}</span>
<span class="c-tag prize">{{ p.created|timestamp }}</span>
</div>
</div>
</div>

<div class="c-actions" style="grid-template-columns:repeat(5,1fr)">
<a href="/admin/social/view/{{ p.id }}" class="c-act edit">
<svg viewBox="0 0 24 24"><path d="M12 4.5C7 4.5 2.73 7.61 1 12c1.73 4.39 6 7.5 11 7.5s9.27-3.11 11-7.5c-1.73-4.39-6-7.5-11-7.5zM12 17c-2.76 0-5-2.24-5-5s2.24-5 5-5 5 2.24 5 5-2.24 5-5 5zm0-8c-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3-1.34-3-3-3z"/></svg>
معاينة
</a>
<a href="/admin/social/toggle-pin/{{ p.id }}" class="c-act {% if p.pinned %}pin-on{% else %}pin-off{% endif %}">
<svg viewBox="0 0 24 24"><path d="M16 12V4h1V2H7v2h1v8l-2 2v2h5.2v6h1.6v-6H18v-2l-2-2z"/></svg>
{% if p.pinned %}إلغاء{% else %}تثبيت{% endif %}
</a>
<a href="/admin/social/toggle-status/{{ p.id }}" class="c-act {% if p.status == 'paused' %}resume{% else %}pause{% endif %}">
{% if p.status == 'paused' %}<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>تشغيل{% else %}<svg viewBox="0 0 24 24"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>إيقاف{% endif %}
</a>
<button type="button" class="c-act edit" onclick="editSocial({{ p.id }}, '{{ p.body|e }}')">
<svg viewBox="0 0 24 24"><path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.39-.39-1.02-.39-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/></svg>
تعديل
</button>
<a href="/admin/social/delete/{{ p.id }}" class="c-act del" onclick="return confirm('حذف المنشور وكل تعليقاته؟')">
<svg viewBox="0 0 24 24"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>
حذف
</a>
</div>
</div>
{% endfor %}
{% else %}
<div class="empty">
<svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/></svg>
لا توجد منشورات بعد
</div>
{% endif %}
</div>

</div>

<!-- modal تعديل منشور -->
<div id="socialEditModal" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.85);z-index:99999;align-items:center;justify-content:center;padding:16px">
<div style="background:#10101e;border:1px solid rgba(123,47,247,.3);border-radius:18px;padding:20px;max-width:480px;width:100%">
<h3 style="color:#00d4ff;margin-bottom:14px;font-size:15px">تعديل المنشور</h3>
<form id="socialEditForm" method="POST">
<label>النص</label>
<textarea name="body" id="seBody" rows="5" style="resize:vertical" maxlength="2000"></textarea>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:14px">
<button type="submit" class="btn btn-grad" style="margin-top:0">حفظ</button>
<button type="button" class="btn" style="margin-top:0;background:rgba(255,107,138,.15);color:#ff6b8a" onclick="document.getElementById('socialEditModal').style.display='none'">إلغاء</button>
</div>
</form>
</div>
</div>

<script>
function editSocial(pid, body){
    document.getElementById('seBody').value = body || '';
    document.getElementById('socialEditForm').action = '/admin/social/edit/' + pid;
    document.getElementById('socialEditModal').style.display = 'flex';
}
</script>

</div>

<div id="paneTabAds" class="tab-pane">
<div class="stats">
<div class="stat"><b>{{ ads_total }}</b><span>الكل</span></div>
<div class="stat gold"><b>{{ ads_pinned }}</b><span>مثبتة</span></div>
<div class="stat green"><b>{{ ads_active }}</b><span>نشطة</span></div>
<div class="stat red"><b>{{ ads_paused }}</b><span>موقوفة</span></div>
</div>

<div class="wrap">

<div class="add-box">
<h2>
<svg viewBox="0 0 24 24"><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/></svg>
إضافة إعلان جديد
</h2>

<form method="POST" action="/admin/ads/add" enctype="multipart/form-data" id="adsAddForm">
<label>عنوان الإعلان (اختياري)</label>
<input type="text" name="title" placeholder="عنوان الإعلان (اختياري)" maxlength="100">

<label>الوصف / النص</label>
<textarea name="body" rows="3" placeholder="تفاصيل الإعلان..." style="resize:vertical" maxlength="1000"></textarea>

<label>رابط التواصل (اختياري)</label>
<input type="text" name="contact_url" placeholder="https://wa.me/967..." dir="ltr">

<label>نص زر التواصل</label>
<input type="text" name="contact_label" placeholder="تواصل" maxlength="20" value="تواصل">

<label>تاريخ الانتهاء (اختياري)</label>
<input type="datetime-local" name="ends_at">

<div class="info-editor">
<h3>
<svg viewBox="0 0 24 24"><path d="M11 7h2v2h-2zm0 4h2v6h-2zm1-9C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2z"/></svg>
شريط معلومات (اختياري)
</h3>
<div class="info-toolbar">
<button type="button" class="info-tb-btn bold" onclick="infoCmd('bold')" title="عريض (Ctrl+B)">B</button>
<button type="button" class="info-tb-btn italic" onclick="infoCmd('italic')" title="مائل (Ctrl+I)">I</button>
<button type="button" class="info-tb-btn underline" onclick="infoCmd('underline')" title="تسطير (Ctrl+U)">U</button>
<div class="info-tb-sep"></div>
<button type="button" class="info-tb-btn color" onclick="infoToggleColors()" title="لون النص">A</button>
<button type="button" class="info-tb-btn" onclick="infoCopy()" title="نسخ">
<svg viewBox="0 0 24 24" style="width:14px;height:14px;fill:currentColor"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg>
</button>
</div>
<div class="info-color-picker" id="infoColors">
<button type="button" class="info-color-opt" style="background:#e8e8f0" onclick="infoColor('#e8e8f0')" title="افتراضي"></button>
<button type="button" class="info-color-opt" style="background:#00d4ff" onclick="infoColor('#00d4ff')" title="سماوي"></button>
<button type="button" class="info-color-opt" style="background:#7b2ff7" onclick="infoColor('#7b2ff7')" title="بنفسجي"></button>
<button type="button" class="info-color-opt" style="background:#00d4a5" onclick="infoColor('#00d4a5')" title="أخضر"></button>
<button type="button" class="info-color-opt" style="background:#fbbf24" onclick="infoColor('#fbbf24')" title="ذهبي"></button>
<button type="button" class="info-color-opt" style="background:#ff6b8a" onclick="infoColor('#ff6b8a')" title="وردي"></button>
<button type="button" class="info-color-opt" style="background:#25D366" onclick="infoColor('#25D366')" title="واتساب"></button>
<button type="button" class="info-color-opt" style="background:#0088cc" onclick="infoColor('#0088cc')" title="تيليجرام"></button>
</div>
<textarea class="info-editor-textarea" id="infoHtmlInput" name="info_html" placeholder="معلومات تظهر أسفل الإعلان... حدّد النص وأضف تنسيق" oninput="infoUpdatePreview()"></textarea>
<div class="info-preview" id="infoPreviewBox"></div>
</div>

<div class="btns-editor">
<h3>
<svg viewBox="0 0 24 24" style="width:16px;height:16px;fill:#00d4ff"><path d="M17 3H7c-1.1 0-2 .9-2 2v16l7-3 7 3V5c0-1.1-.9-2-2-2z"/></svg>
أزرار مخصصة (اختياري)
</h3>
<div id="btnsList"></div>
<button type="button" class="btn-add-btn" onclick="addButtonField()">
<svg viewBox="0 0 24 24" style="width:16px;height:16px;fill:currentColor"><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/></svg>
إضافة زر جديد
</button>
<div class="btn-preview-bar" id="btnPreview"></div>
</div>

<input type="hidden" name="custom_buttons_json" id="customButtonsJson" value="[]">

<button type="button" class="btn btn-grad" onclick="document.getElementById('adsAddForm').submit();">
<svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:#fff;vertical-align:middle;margin-left:6px"><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/></svg>
إضافة الإعلان
</button>
</form>
<div style="font-size:11px;color:#6e6e8a;text-align:center;margin-top:10px">
بعد الإضافة → ارفع الصور من قائمة الإعلانات تحت
</div>
</div>

<h2 style="font-size:14px;color:#8e8eab;margin-bottom:12px;font-weight:800">الإعلانات الحالية ({{ ads_total }})</h2>

<div class="list">
{% if ads %}
{% for a in ads %}
<div class="a-card {% if a.pinned %}pinned{% endif %} {% if a.status == 'paused' %}paused{% endif %}">
<div class="a-head">
<div class="a-ico">
{% if a.images and a.images|length > 0 %}
<img src="/uploads/{{ a.images[0] }}" alt="{{ a.title }}">
{% else %}
<svg viewBox="0 0 24 24" style="width:24px;height:24px;fill:#fff"><path d="M21 3H3c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h18c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm0 16H3V5h18v14zM5 15l3.5-4.5 2.5 3.01L14.5 9l4.5 6H5z"/></svg>
{% endif %}
</div>
<div class="a-info">
<div class="a-title">{{ a.title }}</div>
{% if a.body %}<div class="a-body">{{ a.body[:120] }}{% if a.body|length > 120 %}...{% endif %}</div>{% endif %}
<div class="a-meta">
{% if a.pinned %}<span class="a-tag pin">مثبتة</span>{% endif %}
{% if a.status == 'paused' %}<span class="a-tag pause">موقوفة</span>{% else %}<span class="a-tag">نشطة</span>{% endif %}
<span class="a-tag img">{{ a.images|length }} صورة</span>
</div>
</div>
</div>

{% if a.images and a.images|length > 0 %}
<div class="a-thumbs">
{% for img in a.images %}
<div class="a-thumb">
<img src="/uploads/{{ img }}" alt="">
<a href="/admin/ads/delete-image/{{ a.id }}/{{ img|replace('ads/', '') }}" class="rm" onclick="return confirm('حذف الصورة؟')">×</a>
</div>
{% endfor %}
</div>
{% endif %}

<div class="a-actions">
<button type="button" class="a-act up" onclick="openUpload({{ a.id }})" title="رفع صور">
<svg viewBox="0 0 24 24"><path d="M9 16h6v-6h4l-7-7-7 7h4zm-4 2h14v2H5z"/></svg>
رفع
</button>
<a href="/admin/ads/toggle-pin/{{ a.id }}" class="a-act {% if a.pinned %}pin-on{% else %}pin-off{% endif %}">
<svg viewBox="0 0 24 24"><path d="M16 12V4h1V2H7v2h1v8l-2 2v2h5.2v6h1.6v-6H18v-2l-2-2z"/></svg>
{% if a.pinned %}إلغاء{% else %}تثبيت{% endif %}
</a>
<a href="/admin/ads/toggle-status/{{ a.id }}" class="a-act {% if a.status == 'paused' %}resume{% else %}pause{% endif %}">
{% if a.status == 'paused' %}<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>تشغيل{% else %}<svg viewBox="0 0 24 24"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>إيقاف{% endif %}
</a>
<button type="button" class="a-act edit" data-id="{{ a.id }}" data-title="{{ a.title|e }}" data-body="{{ a.body|e }}" data-url="{{ a.contact_url|e }}" data-label="{{ a.contact_label|e }}" data-buttons="{{ a.custom_buttons|tojson|e }}" data-info="{{ a.info_html|e }}" onclick="openAdEdit2(this)">
<svg viewBox="0 0 24 24"><path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.39-.39-1.02-.39-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/></svg>
تعديل
</button>
<a href="/admin/ads/delete/{{ a.id }}" class="a-act del" onclick="return confirm('حذف {{ a.title }}؟')">
<svg viewBox="0 0 24 24"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>
حذف
</a>
</div>
</div>
{% endfor %}
{% else %}
<div class="empty">
<svg viewBox="0 0 24 24"><path d="M18 11v2h4v-2h-4zm-2 6.61c.96.71 2.21 1.65 3.2 2.39.4-.53.8-1.07 1.2-1.6-.99-.74-2.24-1.68-3.2-2.4-.4.54-.8 1.08-1.2 1.61zM20.4 5.6c-.4-.53-.8-1.07-1.2-1.6-.99.74-2.24 1.68-3.2 2.4.4.53.8 1.07 1.2 1.6.96-.72 2.21-1.65 3.2-2.4zM4 9c-1.1 0-2 .9-2 2v2c0 1.1.9 2 2 2h1v4h2v-4h1l5 3V6L8 9H4z"/></svg>
لا توجد إعلانات بعد — أضف واحد من الأعلى
</div>
{% endif %}
</div>

</div>
</div><!-- /paneTabAds -->

<!-- modal الرفع -->
<div id="adUploadModal" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.85);z-index:99999;align-items:center;justify-content:center;padding:16px">
<div style="background:#10101e;border:1px solid rgba(123,47,247,.3);border-radius:18px;padding:20px;max-width:480px;width:100%">
<h3 style="color:#00d4ff;margin-bottom:14px;font-size:15px">رفع صور الإعلان</h3>
<form id="adUploadForm" method="POST" enctype="multipart/form-data">
<label class="upload-zone">
<svg viewBox="0 0 24 24"><path d="M9 16h6v-6h4l-7-7-7 7h4zm-4 2h14v2H5z"/></svg>
<p>اضغط لاختيار الصور</p>
<small>يمكنك اختيار عدة صور (حتى 10)</small>
<input type="file" name="images" accept="image/*" multiple onchange="document.getElementById('adFname').textContent=this.files.length+' صورة مختارة'">
</label>
<div id="adFname" style="font-size:12px;color:#00d4a5;margin-top:10px;text-align:center"></div>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:14px">
<button type="submit" class="btn btn-grad" style="margin-top:0">رفع</button>
<button type="button" class="btn" style="margin-top:0;background:rgba(255,107,138,.15);color:#ff6b8a" onclick="document.getElementById('adUploadModal').style.display='none'">إلغاء</button>
</div>
</form>
</div>
</div>

<!-- modal التعديل -->
<div id="adEditModal" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.85);z-index:99999;align-items:center;justify-content:center;padding:16px">
<div style="background:#10101e;border:1px solid rgba(123,47,247,.3);border-radius:18px;padding:20px;max-width:480px;width:100%;max-height:85vh;overflow-y:auto">
<h3 style="color:#00d4ff;margin-bottom:14px;font-size:15px">تعديل الإعلان</h3>
<form id="adEditForm" method="POST">
<label>العنوان</label>
<input type="text" name="title" id="aeTitle">
<label>الوصف</label>
<textarea name="body" id="aeBody" rows="4" style="resize:vertical"></textarea>
<label>رابط التواصل</label>
<input type="text" name="contact_url" id="aeUrl" dir="ltr">
<label>نص الزر</label>
<input type="text" name="contact_label" id="aeLabel" maxlength="20">

<div class="info-editor">
<h3>
<svg viewBox="0 0 24 24"><path d="M11 7h2v2h-2zm0 4h2v6h-2zm1-9C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2z"/></svg>
شريط معلومات
</h3>
<div class="info-toolbar">
<button type="button" class="info-tb-btn bold" onclick="infoCmd('bold')" title="عريض">B</button>
<button type="button" class="info-tb-btn italic" onclick="infoCmd('italic')" title="مائل">I</button>
<button type="button" class="info-tb-btn underline" onclick="infoCmd('underline')" title="تسطير">U</button>
<div class="info-tb-sep"></div>
<button type="button" class="info-tb-btn color" onclick="infoToggleColors()" title="لون">A</button>
<button type="button" class="info-tb-btn" onclick="infoCopy()" title="نسخ">
<svg viewBox="0 0 24 24" style="width:14px;height:14px;fill:currentColor"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg>
</button>
</div>
<div class="info-color-picker" id="infoColorsEdit">
<button type="button" class="info-color-opt" style="background:#e8e8f0" onclick="infoColor('#e8e8f0')" title="افتراضي"></button>
<button type="button" class="info-color-opt" style="background:#00d4ff" onclick="infoColor('#00d4ff')" title="سماوي"></button>
<button type="button" class="info-color-opt" style="background:#7b2ff7" onclick="infoColor('#7b2ff7')" title="بنفسجي"></button>
<button type="button" class="info-color-opt" style="background:#00d4a5" onclick="infoColor('#00d4a5')" title="أخضر"></button>
<button type="button" class="info-color-opt" style="background:#fbbf24" onclick="infoColor('#fbbf24')" title="ذهبي"></button>
<button type="button" class="info-color-opt" style="background:#ff6b8a" onclick="infoColor('#ff6b8a')" title="وردي"></button>
<button type="button" class="info-color-opt" style="background:#25D366" onclick="infoColor('#25D366')" title="واتساب"></button>
<button type="button" class="info-color-opt" style="background:#0088cc" onclick="infoColor('#0088cc')" title="تيليجرام"></button>
</div>
<textarea class="info-editor-textarea" id="infoHtmlInputEdit" name="info_html" placeholder="معلومات تظهر أسفل الإعلان..." oninput="infoUpdatePreviewEdit()"></textarea>
<div class="info-preview" id="infoPreviewBoxEdit"></div>
</div>

<div class="btns-editor">
<h3>
<svg viewBox="0 0 24 24" style="width:16px;height:16px;fill:#00d4ff"><path d="M17 3H7c-1.1 0-2 .9-2 2v16l7-3 7 3V5c0-1.1-.9-2-2-2z"/></svg>
أزرار مخصصة
</h3>
<div id="btnsListEdit"></div>
<button type="button" class="btn-add-btn" onclick="addButtonFieldEdit()">
<svg viewBox="0 0 24 24" style="width:16px;height:16px;fill:currentColor"><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/></svg>
إضافة زر جديد
</button>
<div class="btn-preview-bar" id="btnPreviewEdit"></div>
</div>

<input type="hidden" name="custom_buttons_json" id="customButtonsJsonEdit" value="[]">

<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:14px">
<button type="submit" class="btn btn-grad" style="margin-top:0">حفظ</button>
<button type="button" class="btn" style="margin-top:0;background:rgba(255,107,138,.15);color:#ff6b8a" onclick="document.getElementById('adEditModal').style.display='none'">إلغاء</button>
</div>
</form>
</div>
</div>

<script>
function switchPageTab(name){
    document.querySelectorAll('.page-tab').forEach(function(b){ b.classList.remove('active'); });
    document.querySelectorAll('.tab-pane').forEach(function(p){ p.classList.remove('active'); });
    if(name === 'ads'){
        document.getElementById('tabBtnAds').classList.add('active');
        document.getElementById('paneTabAds').classList.add('active');
        try { localStorage.setItem('contests_tab', 'ads'); } catch(e){}
    } else if(name === 'social'){
        document.getElementById('tabBtnSocial').classList.add('active');
        document.getElementById('paneTabSocial').classList.add('active');
        try { localStorage.setItem('contests_tab', 'social'); } catch(e){}
    } else {
        document.getElementById('tabBtnContests').classList.add('active');
        document.getElementById('paneTabContests').classList.add('active');
        try { localStorage.setItem('contests_tab', 'contests'); } catch(e){}
    }
}

document.addEventListener('DOMContentLoaded', function(){
    try {
        var saved = localStorage.getItem('contests_tab');
        if(saved === 'ads') switchPageTab('ads');
        else if(saved === 'social') switchPageTab('social');
    } catch(e){}
});

function openUpload(aid){
    document.getElementById('adUploadForm').action = '/admin/ads/upload-images/' + aid;
    document.getElementById('adUploadModal').style.display = 'flex';
    document.getElementById('adFname').textContent = '';
}

function openAdEdit2(btn){
    var d = btn.dataset;
    document.getElementById('aeTitle').value = d.title || '';
    document.getElementById('aeBody').value = d.body || '';
    document.getElementById('aeUrl').value = d.url || '';
    document.getElementById('aeLabel').value = d.label || 'تواصل';
    document.getElementById('adEditForm').action = '/admin/ads/edit/' + d.id;
    // ═══ الأزرار المخصصة ═══
    var btnsArr = [];
    try {
        if(d.buttons){
            btnsArr = JSON.parse(d.buttons);
        }
    } catch(e){ btnsArr = []; }
    fillButtonsEditorEdit(btnsArr);
    // ═══ info_html ═══
    var infoTa = document.getElementById('infoHtmlInputEdit');
    if(infoTa) infoTa.value = d.info || '';
    infoUpdatePreviewEdit();
    document.getElementById('adEditModal').style.display = 'flex';
}

function openAdEdit(aid, title, body, url, label){
    document.getElementById('aeTitle').value = title || '';
    document.getElementById('aeBody').value = body || '';
    document.getElementById('aeUrl').value = url || '';
    document.getElementById('aeLabel').value = label || 'تواصل';
    document.getElementById('adEditForm').action = '/admin/ads/edit/' + aid;
    document.getElementById('adEditModal').style.display = 'flex';
}

// ═══ مكتبة أيقونات SVG ═══
var BTN_ICONS = {
    "link": {name:"رابط", svg:'<svg viewBox="0 0 24 24"><path d="M3.9 12c0-1.71 1.39-3.1 3.1-3.1h4V7H7c-2.76 0-5 2.24-5 5s2.24 5 5 5h4v-1.9H7c-1.71 0-3.1-1.39-3.1-3.1zM8 13h8v-2H8v2zm9-6h-4v1.9h4c1.71 0 3.1 1.39 3.1 3.1s-1.39 3.1-3.1 3.1h-4V17h4c2.76 0 5-2.24 5-5s-2.24-5-5-5z"/></svg>'},
    "whatsapp": {name:"واتساب", svg:'<svg viewBox="0 0 24 24"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/></svg>'},
    "telegram": {name:"تيليجرام", svg:'<svg viewBox="0 0 24 24"><path d="M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0zm5.562 8.161c-.18 1.897-.962 6.502-1.359 8.627-.168.9-.5 1.201-.82 1.23-.697.064-1.226-.461-1.901-.903-1.056-.692-1.653-1.123-2.678-1.798-1.185-.781-.417-1.21.258-1.911.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635.099-.002.321.023.465.14a.506.506 0 01.171.325c.016.093.036.306.02.472z"/></svg>'},
    "phone": {name:"هاتف", svg:'<svg viewBox="0 0 24 24"><path d="M6.62 10.79c1.44 2.83 3.76 5.14 6.59 6.59l2.2-2.2c.27-.27.67-.36 1.02-.24 1.12.37 2.33.57 3.57.57.55 0 1 .45 1 1V20c0 .55-.45 1-1 1-9.39 0-17-7.61-17-17 0-.55.45-1 1-1h3.5c.55 0 1 .45 1 1 0 1.25.2 2.45.57 3.57.11.35.03.74-.25 1.02l-2.2 2.2z"/></svg>'},
    "download": {name:"تحميل", svg:'<svg viewBox="0 0 24 24"><path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/></svg>'},
    "cart": {name:"متجر", svg:'<svg viewBox="0 0 24 24"><path d="M7 18c-1.1 0-1.99.9-1.99 2S5.9 22 7 22s2-.9 2-2-.9-2-2-2zM1 2v2h2l3.6 7.59-1.35 2.45c-.16.28-.25.61-.25.96 0 1.1.9 2 2 2h12v-2H7.42c-.14 0-.25-.11-.25-.25l.03-.12.9-1.63h7.45c.75 0 1.41-.41 1.75-1.03l3.58-6.49c.08-.14.12-.31.12-.48 0-.55-.45-1-1-1H5.21l-.94-2H1zm16 16c-1.1 0-1.99.9-1.99 2s.89 2 1.99 2 2-.9 2-2-.9-2-2-2z"/></svg>'},
    "star": {name:"مميز", svg:'<svg viewBox="0 0 24 24"><path d="M12 17.27L18.18 21l-1.64-7.03L22 9.24l-7.19-.61L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21z"/></svg>'},
    "gift": {name:"هدية", svg:'<svg viewBox="0 0 24 24"><path d="M20 6h-2.18c.11-.31.18-.65.18-1a2.996 2.996 0 00-5.5-1.65l-.5.67-.5-.68C10.96 2.54 10.05 2 9 2 7.34 2 6 3.34 6 5c0 .35.07.69.18 1H4c-1.11 0-1.99.89-1.99 2L2 19c0 1.11.89 2 2 2h16c1.11 0 2-.89 2-2V8c0-1.11-.89-2-2-2zm-5-2c.55 0 1 .45 1 1s-.45 1-1 1-1-.45-1-1 .45-1 1-1zM9 4c.55 0 1 .45 1 1s-.45 1-1 1-1-.45-1-1 .45-1 1-1zm11 15H4v-2h16v2zm0-5H4V8h5.08L7 10.83 8.62 12 11 8.76l1-1.36 1 1.36L15.38 12 17 10.83 14.92 8H20v6z"/></svg>'},
    "info": {name:"معلومة", svg:'<svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/></svg>'},
    "play": {name:"تشغيل", svg:'<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>'},
    "fire": {name:"شعبي", svg:'<svg viewBox="0 0 24 24"><path d="M12 2C9 7 6 8 6 13a6 6 0 1012 0c0-5-3-6-6-11zm0 18c-2.21 0-4-1.79-4-4 0-2 1-3 2-4 0 2 1 3 2 3s2-1 2-3c1 1 2 2 2 4 0 2.21-1.79 4-4 4z"/></svg>'},
    "check": {name:"صح", svg:'<svg viewBox="0 0 24 24"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>'},
    "map": {name:"موقع", svg:'<svg viewBox="0 0 24 24"><path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z"/></svg>'},
    "users": {name:"مجموعة", svg:'<svg viewBox="0 0 24 24"><path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z"/></svg>'}
};

var _btnCounter = 0;

function renderIconGrid(container, btnId){
    var html = '';
    for(var k in BTN_ICONS){
        var ic = BTN_ICONS[k];
        html += '<div class="btn-icon-opt" data-icon="' + k + '" onclick="pickIcon(this, ' + btnId + ')" title="' + ic.name + '">' + ic.svg + '</div>';
    }
    container.innerHTML = html;
}

function addButtonField(data){
    data = data || {};
    var id = ++_btnCounter;
    var list = document.getElementById("btnsList");
    var div = document.createElement("div");
    div.className = "btn-item";
    div.dataset.btnId = id;
    div.innerHTML =
        '<div class="btn-item-head">' +
            '<span class="btn-item-num">زر #<span class="btn-num-lbl">' + id + '</span></span>' +
            '<button type="button" class="btn-item-remove" onclick="removeButtonField(this)">×</button>' +
        '</div>' +
        '<label>النص الظاهر</label>' +
        '<input type="text" class="bi-label" placeholder="مثال: افتح الموقع" maxlength="50" value="' + (data.label || '').replace(/"/g, '&quot;') + '">' +
        '<label>الرابط (URL / tel: / mailto: / #)</label>' +
        '<input type="text" class="bi-url" placeholder="https://..." dir="ltr" value="' + (data.url || '').replace(/"/g, '&quot;') + '">' +
        '<label>اللون</label>' +
        '<input type="color" class="bi-color" value="' + (data.color || '#25D366') + '">' +
        '<label>نوع الزر</label>' +
        '<div class="bi-mode-group" style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-bottom:8px">' +
            '<label style="cursor:pointer;padding:8px;border:1.5px solid rgba(123,47,247,.25);border-radius:10px;text-align:center;background:rgba(0,0,0,.3);font-size:11px;margin:0">' +
                '<input type="radio" name="bi-mode-' + id + '" value="normal" ' + ((data.mode || 'normal') === 'normal' ? 'checked' : '') + ' style="width:auto;margin:0 4px 0 0;vertical-align:middle">' +
                '<span style="vertical-align:middle">عادي</span>' +
            '</label>' +
            '<label style="cursor:pointer;padding:8px;border:1.5px solid rgba(123,47,247,.25);border-radius:10px;text-align:center;background:rgba(0,0,0,.3);font-size:11px;margin:0">' +
                '<input type="radio" name="bi-mode-' + id + '" value="preview" ' + ((data.mode || '') === 'preview' ? 'checked' : '') + ' style="width:auto;margin:0 4px 0 0;vertical-align:middle">' +
                '<span style="vertical-align:middle">معاينة</span>' +
            '</label>' +
            '<label style="cursor:pointer;padding:8px;border:1.5px solid rgba(123,47,247,.25);border-radius:10px;text-align:center;background:rgba(0,0,0,.3);font-size:11px;margin:0">' +
                '<input type="radio" name="bi-mode-' + id + '" value="html" ' + ((data.mode || '') === 'html' ? 'checked' : '') + ' style="width:auto;margin:0 4px 0 0;vertical-align:middle">' +
                '<span style="vertical-align:middle">HTML</span>' +
            '</label>' +
        '</div>' +
        '<div class="bi-html-block" style="display:none;background:rgba(0,212,255,.05);border:1.5px dashed rgba(0,212,255,.3);border-radius:10px;padding:10px;margin-bottom:8px">' +
            '<label style="color:#00d4ff;font-weight:800;font-size:12px">كود HTML (يظهر داخل النافذة)</label>' +
            '<textarea class="bi-html" placeholder="&lt;html&gt;...&lt;/html&gt;" style="width:100%;min-height:80px;padding:8px;font-family:monospace;font-size:11px;direction:ltr;text-align:left;background:rgba(0,0,0,.4);border:1px solid rgba(255,255,255,.1);border-radius:8px;color:#e8e8f0;resize:vertical;outline:none">' + (data.html || '').replace(/</g, '&lt;').replace(/>/g, '&gt;') + '</textarea>' +
        '</div>' +
        '<label>اختر أيقونة</label>' +
        '<div class="btn-icon-grid" id="iconGrid_' + id + '"></div>' +
        '<label>أو الصق كود SVG مخصص (اختياري)</label>' +
        '<textarea class="btn-icon-custom bi-svg" placeholder="&lt;svg viewBox=&quot;0 0 24 24&quot;&gt;...&lt;/svg&gt;">' + (data.icon_svg ? data.icon_svg.replace(/</g, '&lt;').replace(/>/g, '&gt;') : '') + '</textarea>';
    list.appendChild(div);
    renderIconGrid(document.getElementById("iconGrid_" + id), id);
    // event listeners live
    div.querySelectorAll(".bi-label, .bi-url, .bi-color, .bi-svg, .bi-html").forEach(function(el){
        el.addEventListener("input", updateButtonsJson);
        el.addEventListener("change", updateButtonsJson);
    });
    // إظهار/إخفاء HTML block
    div.querySelectorAll('input[type="radio"]').forEach(function(r){
        r.addEventListener("change", function(){
            var htmlBlock = div.querySelector(".bi-html-block");
            if(r.value === "html" && r.checked){
                htmlBlock.style.display = "block";
            } else if(r.checked){
                htmlBlock.style.display = "none";
            }
        });
    });
    // حالة أولية
    var modeEl = div.querySelector('input[type="radio"]:checked');
    if(modeEl && modeEl.value === "html"){
        div.querySelector(".bi-html-block").style.display = "block";
    }
    updateButtonsJson();
}

function removeButtonField(btn){
    var item = btn.closest(".btn-item");
    if(item) item.remove();
    updateButtonsJson();
}

function pickIcon(el, btnId){
    var item = document.querySelector('[data-btn-id="' + btnId + '"]');
    if(!item) return;
    item.querySelectorAll(".btn-icon-opt").forEach(function(o){ o.classList.remove("active"); });
    el.classList.add("active");
    var key = el.dataset.icon;
    var svg = BTN_ICONS[key] ? BTN_ICONS[key].svg : "";
    var ta = item.querySelector(".bi-svg");
    if(ta) ta.value = svg;
    updateButtonsJson();
}

function collectButtons(){
    var out = [];
    document.querySelectorAll("#btnsList .btn-item").forEach(function(item){
        var label = (item.querySelector(".bi-label").value || "").trim();
        var url = (item.querySelector(".bi-url").value || "").trim();
        var color = (item.querySelector(".bi-color").value || "#25D366").trim();
        var svg = (item.querySelector(".bi-svg").value || "").trim();
        var modeEl = item.querySelector('input[type="radio"]:checked');
        var mode = modeEl ? modeEl.value : "normal";
        var html = "";
        var htmlTa = item.querySelector(".bi-html");
        if(htmlTa) html = htmlTa.value || "";
        if(!label && !url && !html) return;
        out.push({label: label, url: url, color: color, icon_svg: svg, mode: mode, html: html});
    });
    return out;
}

function updateButtonsJson(){
    var btns = collectButtons();
    var hidden = document.getElementById("customButtonsJson");
    if(hidden) hidden.value = JSON.stringify(btns);
    var prev = document.getElementById("btnPreview");
    if(prev){
        prev.innerHTML = btns.map(function(b){
            var icon = b.icon_svg || "";
            return '<span class="btn-preview-pill" style="background:' + b.color + '">' + icon + (b.label || "زر") + '</span>';
        }).join("");
    }
}

// ═══ تعبئة المحرر عند التعديل ═══
function fillButtonsEditor(jsonStr){
    var list = document.getElementById("btnsList");
    if(!list) return;
    list.innerHTML = "";
    _btnCounter = 0;
    var arr = [];
    try { arr = JSON.parse(jsonStr || "[]"); } catch(e){ arr = []; }
    if(!Array.isArray(arr)) arr = [];
    arr.forEach(function(b){ addButtonField(b); });
    updateButtonsJson();
}

// ═══ محرر الأزرار — نموذج التعديل ═══
var _btnCounterEdit = 0;

function renderIconGridEdit(container, btnId){
    var html = '';
    for(var k in BTN_ICONS){
        var ic = BTN_ICONS[k];
        html += '<div class="btn-icon-opt" data-icon="' + k + '" onclick="pickIconEdit(this, ' + btnId + ')" title="' + ic.name + '">' + ic.svg + '</div>';
    }
    container.innerHTML = html;
}

function addButtonFieldEdit(data){
    data = data || {};
    var id = ++_btnCounterEdit;
    var list = document.getElementById("btnsListEdit");
    if(!list) return;
    var div = document.createElement("div");
    div.className = "btn-item";
    div.dataset.btnId = id;
    div.innerHTML =
        '<div class="btn-item-head">' +
            '<span class="btn-item-num">زر #<span class="btn-num-lbl">' + id + '</span></span>' +
            '<button type="button" class="btn-item-remove" onclick="removeButtonFieldEdit(this)">×</button>' +
        '</div>' +
        '<label>النص الظاهر</label>' +
        '<input type="text" class="bi-label" placeholder="مثال: افتح الموقع" maxlength="50" value="' + (data.label || '').replace(/"/g, '&quot;') + '">' +
        '<label>الرابط</label>' +
        '<input type="text" class="bi-url" placeholder="https://..." dir="ltr" value="' + (data.url || '').replace(/"/g, '&quot;') + '">' +
        '<label>اللون</label>' +
        '<input type="color" class="bi-color" value="' + (data.color || '#25D366') + '">' +
        '<label>نوع الزر</label>' +
        '<div class="bi-mode-group" style="display:flex;gap:8px;margin-bottom:8px">' +
            '<label style="flex:1;cursor:pointer;padding:10px;border:1.5px solid rgba(123,47,247,.25);border-radius:10px;text-align:center;background:rgba(0,0,0,.3);font-size:12px;margin:0">' +
                '<input type="radio" name="bi-mode-edit-' + id + '" value="normal" ' + ((data.mode || 'normal') === 'normal' ? 'checked' : '') + ' style="width:auto;margin:0 6px 0 0;vertical-align:middle">' +
                '<span style="vertical-align:middle">عادي</span>' +
            '</label>' +
            '<label style="flex:1;cursor:pointer;padding:10px;border:1.5px solid rgba(123,47,247,.25);border-radius:10px;text-align:center;background:rgba(0,0,0,.3);font-size:12px;margin:0">' +
                '<input type="radio" name="bi-mode-edit-' + id + '" value="preview" ' + ((data.mode || '') === 'preview' ? 'checked' : '') + ' style="width:auto;margin:0 6px 0 0;vertical-align:middle">' +
                '<span style="vertical-align:middle">معاينة</span>' +
            '</label>' +
        '</div>' +
        '<label>اختر أيقونة</label>' +
        '<div class="btn-icon-grid" id="iconGridEdit_' + id + '"></div>' +
        '<label>أو الصق كود SVG مخصص</label>' +
        '<textarea class="btn-icon-custom bi-svg" placeholder="&lt;svg viewBox=&quot;0 0 24 24&quot;&gt;...&lt;/svg&gt;">' + (data.icon_svg ? data.icon_svg.replace(/</g, '&lt;').replace(/>/g, '&gt;') : '') + '</textarea>';
    list.appendChild(div);
    renderIconGridEdit(document.getElementById("iconGridEdit_" + id), id);
    div.querySelectorAll(".bi-label, .bi-url, .bi-color, .bi-svg").forEach(function(el){
        el.addEventListener("input", updateButtonsJsonEdit);
        el.addEventListener("change", updateButtonsJsonEdit);
    });
    updateButtonsJsonEdit();
}

function removeButtonFieldEdit(btn){
    var item = btn.closest(".btn-item");
    if(item) item.remove();
    updateButtonsJsonEdit();
}

function pickIconEdit(el, btnId){
    var item = document.querySelector('#btnsListEdit [data-btn-id="' + btnId + '"]');
    if(!item) return;
    item.querySelectorAll(".btn-icon-opt").forEach(function(o){ o.classList.remove("active"); });
    el.classList.add("active");
    var key = el.dataset.icon;
    var svg = BTN_ICONS[key] ? BTN_ICONS[key].svg : "";
    var ta = item.querySelector(".bi-svg");
    if(ta) ta.value = svg;
    updateButtonsJsonEdit();
}

function collectButtonsEdit(){
    var out = [];
    document.querySelectorAll("#btnsListEdit .btn-item").forEach(function(item){
        var label = (item.querySelector(".bi-label").value || "").trim();
        var url = (item.querySelector(".bi-url").value || "").trim();
        var color = (item.querySelector(".bi-color").value || "#25D366").trim();
        var svg = (item.querySelector(".bi-svg").value || "").trim();
        var modeEl = item.querySelector('input[type="radio"]:checked');
        var mode = modeEl ? modeEl.value : "normal";
        if(!label && !url) return;
        out.push({label: label, url: url, color: color, icon_svg: svg, mode: mode});
    });
    return out;
}

function updateButtonsJsonEdit(){
    var btns = collectButtonsEdit();
    var hidden = document.getElementById("customButtonsJsonEdit");
    if(hidden) hidden.value = JSON.stringify(btns);
    var prev = document.getElementById("btnPreviewEdit");
    if(prev){
        prev.innerHTML = btns.map(function(b){
            var icon = b.icon_svg || "";
            return '<span class="btn-preview-pill" style="background:' + b.color + '">' + icon + (b.label || "زر") + '</span>';
        }).join("");
    }
}

function fillButtonsEditorEdit(btnsArr){
    var list = document.getElementById("btnsListEdit");
    if(!list) return;
    list.innerHTML = "";
    _btnCounterEdit = 0;
    if(!Array.isArray(btnsArr)) btnsArr = [];
    btnsArr.forEach(function(b){ addButtonFieldEdit(b); });
    updateButtonsJsonEdit();
}

// ═══ محرر شريط المعلومات ═══
function infoGetActiveTextarea(){
    // يشتغل مع أي textarea مرئي
    var editModal = document.getElementById('adEditModal');
    if(editModal && editModal.style.display === 'flex'){
        return document.getElementById('infoHtmlInputEdit');
    }
    return document.getElementById('infoHtmlInput');
}

function infoCmd(cmd){
    var ta = infoGetActiveTextarea();
    if(!ta) return;
    var start = ta.selectionStart;
    var end = ta.selectionEnd;
    var text = ta.value;
    var selected = text.substring(start, end);
    var openTag, closeTag;
    if(cmd === 'bold'){ openTag = '<b>'; closeTag = '</b>'; }
    else if(cmd === 'italic'){ openTag = '<i>'; closeTag = '</i>'; }
    else if(cmd === 'underline'){ openTag = '<u>'; closeTag = '</u>'; }
    else return;
    var newText;
    if(selected){
        newText = text.substring(0, start) + openTag + selected + closeTag + text.substring(end);
    } else {
        newText = text.substring(0, start) + openTag + closeTag + text.substring(end);
    }
    ta.value = newText;
    // ضع المؤشر بين الوسمين
    if(!selected){
        ta.selectionStart = ta.selectionEnd = start + openTag.length;
    }
    ta.focus();
    infoUpdatePreview();
    infoUpdatePreviewEdit();
}

function infoToggleColors(){
    var c1 = document.getElementById('infoColors');
    var c2 = document.getElementById('infoColorsEdit');
    if(c1) c1.classList.toggle('show');
    if(c2) c2.classList.toggle('show');
}

function infoColor(color){
    var ta = infoGetActiveTextarea();
    if(!ta) return;
    var start = ta.selectionStart;
    var end = ta.selectionEnd;
    var text = ta.value;
    var selected = text.substring(start, end) || 'نص';
    var openTag = '<span style="color:' + color + '">';
    var closeTag = '</span>';
    var newText = text.substring(0, start) + openTag + selected + closeTag + text.substring(end);
    ta.value = newText;
    ta.focus();
    infoUpdatePreview();
    infoUpdatePreviewEdit();
    // اقفل لوحة الألوان
    var c1 = document.getElementById('infoColors');
    var c2 = document.getElementById('infoColorsEdit');
    if(c1) c1.classList.remove('show');
    if(c2) c2.classList.remove('show');
}

function infoCopy(){
    var ta = infoGetActiveTextarea();
    if(!ta) return;
    if(navigator.clipboard && navigator.clipboard.writeText){
        navigator.clipboard.writeText(ta.value).then(function(){
            // تأكيد
            var btn = event && event.target;
            if(btn){
                var old = btn.innerHTML;
                btn.innerHTML = '✓';
                setTimeout(function(){ btn.innerHTML = old; }, 1200);
            }
        });
    }
}

function infoUpdatePreview(){
    var ta = document.getElementById('infoHtmlInput');
    var box = document.getElementById('infoPreviewBox');
    if(ta && box) box.innerHTML = ta.value;
}

function infoUpdatePreviewEdit(){
    var ta = document.getElementById('infoHtmlInputEdit');
    var box = document.getElementById('infoPreviewBoxEdit');
    if(ta && box) box.innerHTML = ta.value;
}

// اربط Ctrl+B/I/U
document.addEventListener('keydown', function(e){
    if((e.ctrlKey || e.metaKey) && !e.shiftKey){
        if(e.key === 'b'){ e.preventDefault(); infoCmd('bold'); }
        if(e.key === 'i'){ e.preventDefault(); infoCmd('italic'); }
        if(e.key === 'u'){ e.preventDefault(); infoCmd('underline'); }
    }
});
</script>

</body>
</html>"""


@app.template_filter('tojson')
def _tojson_filter(v):
    try:
        return json.dumps(v, ensure_ascii=False)
    except Exception:
        return "[]"


@app.template_filter('from_json')
def _from_json_filter(s):
    try:
        return json.loads(s) if s else []
    except Exception:
        return []


# ═══════════════════════════════════════════
# MY CONTESTS — مشاركات المستخدم
# ═══════════════════════════════════════════
@app.route("/api/me")
def api_me():
    """يرجع بيانات المستخدم الحالي"""
    if not session.get("user_logged") and not session.get("admin_logged"):
        return jsonify({"ok": False, "error": "login"}), 401
    username = session.get("user_name", "")
    is_admin = bool(session.get("admin_logged"))
    if is_admin and not username:
        username = "admin"
    users = load_users()
    u = users.get(username.strip().lower(), {})
    return jsonify({
        "ok": True,
        "username": username,
        "avatar": u.get("avatar", ""),
        "is_admin": is_admin
    })


@app.route("/api/my-contests")
def api_my_contests():
    """يرجع المسابقات اللي شارك/صوّت فيها المستخدم"""
    if not session.get("user_logged") and not session.get("admin_logged"):
        return jsonify({"ok": False, "error": "login"}), 401
    username = (session.get("user_name") or "").strip().lower()
    is_admin = bool(session.get("admin_logged"))
    if is_admin and not username:
        username = "admin"
    if not username:
        return jsonify({"ok": False, "error": "no user"}), 401
    try:
        all_contests = contests_list(only_active=False)
        mine = []
        for c in all_contests:
            try:
                voters = json.loads(c.get("voters") or "[]")
            except:
                voters = []
            if username in voters:
                mine.append({
                    "id": c.get("id"),
                    "title": c.get("title"),
                    "kind": c.get("kind"),
                    "icon": c.get("icon"),
                    "prize": c.get("prize"),
                    "status": c.get("status"),
                    "created": c.get("created")
                })
        return jsonify({"ok": True, "contests": mine, "count": len(mine)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/contest-voters/<int:cid>")
@admin_required
def api_contest_voters(cid):
    """يرجع من صوّت على المسابقة"""
    c = contests_get(cid)
    if not c:
        return jsonify({"ok": False, "error": "not found"}), 404
    try:
        voters = json.loads(c.get("voters") or "[]")
    except:
        voters = []
    try:
        votes = json.loads(c.get("votes") or "{}")
    except:
        votes = {}
    if isinstance(votes, list):
        votes = {"labels": votes, "counts": []}
    labels = votes.get("labels", []) if isinstance(votes, dict) else []
    counts = votes.get("counts", []) if isinstance(votes, dict) else []
    users = load_users()
    # اربط كل مصوّت باسمه الكامل
    result = []
    for v in voters:
        u = users.get(v.lower(), {})
        result.append({
            "username": v,
            "display": u.get("username", v),
            "avatar": u.get("avatar", "")
        })
    return jsonify({
        "ok": True,
        "title": c.get("title"),
        "voters": result,
        "total": len(result),
        "labels": labels,
        "counts": counts
    })


# ═══════════════════════════════════════════
# الإعلانات — Ads
# ═══════════════════════════════════════════
def ads_list(only_active=False):
    """يرجع كل الإعلانات — المثبتة أولاً"""
    try:
        conn = _db()
        if only_active:
            now = time.time()
            rows = conn.execute(
                "SELECT * FROM ads WHERE status='active' ORDER BY pinned DESC, created DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM ads ORDER BY pinned DESC, created DESC"
            ).fetchall()
        conn.close()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["images"] = json.loads(d.get("images") or "[]")
            except:
                d["images"] = []
            try:
                d["custom_buttons"] = json.loads(d.get("custom_buttons") or "[]")
            except:
                d["custom_buttons"] = []
            result.append(d)
        return result
    except Exception as e:
        print("ads_list err:", e)
        return []


def ads_get(aid):
    try:
        conn = _db()
        row = conn.execute("SELECT * FROM ads WHERE id=?", (aid,)).fetchone()
        conn.close()
        if not row:
            return None
        d = dict(row)
        try:
            d["images"] = json.loads(d.get("images") or "[]")
        except:
            d["images"] = []
        try:
            d["custom_buttons"] = json.loads(d.get("custom_buttons") or "[]")
        except:
            d["custom_buttons"] = []
        return d
    except Exception as e:
        print("ads_get err:", e)
        return None


def ads_add(title, body="", images=None, contact_url="", contact_label="تواصل",
            starts_at=0, ends_at=0, custom_buttons=None, info_html=""):
    try:
        conn = _db()
        c = conn.cursor()
        c.execute("""
            INSERT INTO ads (title, body, images, contact_url, contact_label,
                             starts_at, ends_at, status, pinned, custom_buttons,
                             info_html, created, updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'active', 0, ?, ?, ?, ?)
        """, (
            title, body,
            json.dumps(images or [], ensure_ascii=False),
            contact_url, contact_label,
            starts_at, ends_at,
            json.dumps(custom_buttons or [], ensure_ascii=False),
            info_html or "",
            time.time(), time.time()
        ))
        aid = c.lastrowid
        conn.commit()
        conn.close()
        return aid
    except Exception as e:
        print("ads_add err:", e)
        return None


def ads_update(aid, **fields):
    allowed = {"title","body","images","contact_url","contact_label",
               "starts_at","ends_at","status","pinned","custom_buttons","info_html"}
    sets = []
    vals = []
    for k, v in fields.items():
        if k in allowed:
            if k == "images" and isinstance(v, list):
                v = json.dumps(v, ensure_ascii=False)
            if k == "custom_buttons" and isinstance(v, list):
                v = json.dumps(v, ensure_ascii=False)
            sets.append(k + "=?")
            vals.append(v)
    if not sets:
        return False
    sets.append("updated=?")
    vals.append(time.time())
    vals.append(aid)
    try:
        conn = _db()
        conn.execute("UPDATE ads SET " + ", ".join(sets) + " WHERE id=?", vals)
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print("ads_update err:", e)
        return False


def ads_toggle_pin(aid):
    a = ads_get(aid)
    if not a:
        return False
    return ads_update(aid, pinned=0 if a.get("pinned") else 1)


def ads_toggle_status(aid):
    a = ads_get(aid)
    if not a:
        return False
    return ads_update(aid, status="paused" if a.get("status") == "active" else "active")


def ads_delete(aid):
    try:
        # احذف الصور
        a = ads_get(aid)
        if a and a.get("images"):
            for img in a["images"]:
                try:
                    p = os.path.join(UPLOAD_FOLDER, "ads", os.path.basename(img))
                    if os.path.exists(p):
                        os.remove(p)
                except:
                    pass
        conn = _db()
        conn.execute("DELETE FROM ads WHERE id=?", (aid,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print("ads_delete err:", e)
        return False


def ads_add_images(aid, new_images):
    """يضيف صور لـ إعلان — منع التكرار حسب محتوى الملف (SHA1) وليس الاسم"""
    import hashlib as _hl
    a = ads_get(aid)
    if not a:
        return False
    imgs = a.get("images") or []
    def _h(rel):
        try:
            with open(os.path.join(UPLOAD_FOLDER, rel), "rb") as fh:
                return _hl.sha1(fh.read()).hexdigest()
        except Exception:
            return None
    seen = set()
    for img in imgs:
        h = _h(img)
        if h:
            seen.add(h)
    for new_img in new_images:
        if new_img in imgs:
            continue
        h = _h(new_img)
        if h and h in seen:
            try:
                p = os.path.join(UPLOAD_FOLDER, new_img)
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass
            continue
        imgs.append(new_img)
        if h:
            seen.add(h)
    return ads_update(aid, images=imgs[:10])


def ads_remove_image(aid, img_name):
    """يحذف صورة من إعلان"""
    a = ads_get(aid)
    if not a:
        return False
    imgs = a.get("images") or []
    imgs = [i for i in imgs if os.path.basename(i) != img_name]
    # احذف الملف
    try:
        p = os.path.join(UPLOAD_FOLDER, "ads", img_name)
        if os.path.exists(p):
            os.remove(p)
    except:
        pass
    return ads_update(aid, images=imgs)


@app.route("/admin/ads/upload-images/<int:aid>", methods=["POST"])
@admin_required
def admin_ads_upload_images(aid):
    from werkzeug.utils import secure_filename
    files = request.files.getlist("images")
    if not files:
        return jsonify({"ok": False, "error": "no files"}), 400
    a = ads_get(aid)
    if not a:
        return jsonify({"ok": False, "error": "not found"}), 404
    saved = []
    allowed = ["jpg", "jpeg", "png", "gif", "webp"]
    for f in files:
        if not f or not f.filename:
            continue
        fn = secure_filename(f.filename)
        ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else ""
        if ext not in allowed:
            continue
        new_name = "ad_" + str(int(time.time() * 1000)) + "_" + fn
        try:
            os.makedirs(os.path.join(UPLOAD_FOLDER, "ads"), exist_ok=True)
            filepath = os.path.join(UPLOAD_FOLDER, "ads", new_name)
            f.save(filepath)
            # ضغط الصورة
            try:
                from PIL import Image, ImageOps
                im = Image.open(filepath)
                im = ImageOps.exif_transpose(im)
                im.thumbnail((1200, 1200))
                if ext in ("jpg", "jpeg"):
                    im.convert("RGB").save(filepath, "JPEG", quality=82, optimize=True)
                elif ext == "png":
                    im.save(filepath, "PNG", optimize=True)
                else:
                    im.save(filepath, "WEBP", quality=82)
            except Exception as e:
                print("[ADS] compress err:", e)
            saved.append("ads/" + new_name)
        except Exception as e:
            print("[ADS] save err:", e)
    if saved:
        ads_add_images(aid, saved)
    print(f"[ADS] رُفعت {len(saved)} صورة للإعلان #{aid}")
    return jsonify({"ok": True, "saved": saved, "total": len(saved)})


@app.route("/admin/ads/remove-image/<int:aid>/<img_name>")
@admin_required
def admin_ads_remove_image(aid, img_name):
    ads_remove_image(aid, img_name)
    return redirect(url_for("admin_contests") + "#ads")


# ═══════════════════════════════════════════
# ADMIN — الإعلانات
# ═══════════════════════════════════════════


# ═══ Admin Ads (مضغوطة داخل /admin/contests) ═══
@app.route("/admin/ads/delete/<int:aid>")
@admin_required
def admin_ads_delete(aid):
    ads_delete(aid)
    return redirect(url_for("admin_contests") + "#ads")


@app.route("/admin/ads/edit/<int:aid>", methods=["POST"])
@admin_required
def admin_ads_edit(aid):
    title = request.form.get("title", "").strip()
    if not title:
        return redirect(url_for("admin_contests") + "#ads")
    body = request.form.get("body", "").strip()
    contact_url = request.form.get("contact_url", "").strip()
    contact_label = request.form.get("contact_label", "تواصل").strip() or "تواصل"
    info_html = request.form.get("info_html", "").strip()[:10000]
    ends_at = 0
    ends_str = request.form.get("ends_at", "").strip()
    if ends_str:
        try:
            from datetime import datetime as _dt
            ends_at = _dt.strptime(ends_str, "%Y-%m-%dT%H:%M").timestamp()
        except:
            pass

    # ═══ اقرأ الأزرار ═══
    custom_buttons = None
    btns_json = request.form.get("custom_buttons_json", "").strip()
    if btns_json:
        try:
            parsed = json.loads(btns_json)
            if isinstance(parsed, list):
                custom_buttons = []
                for b in parsed[:10]:
                    if not isinstance(b, dict):
                        continue
                    label = (b.get("label") or "").strip()[:50]
                    url = (b.get("url") or "").strip()[:500]
                    icon_svg = (b.get("icon_svg") or "").strip()[:20000]
                    color = (b.get("color") or "#25D366").strip()[:20]
                    if not label and not url:
                        continue
                    mode = (b.get("mode") or "normal").strip()
                    if mode not in ("normal", "preview", "html"):
                        mode = "normal"
                    html_content = (b.get("html") or "").strip()[:50000]
                    custom_buttons.append({
                        "label": label,
                        "url": url,
                        "icon_svg": icon_svg,
                        "color": color,
                        "mode": mode,
                        "html": html_content
                    })
        except Exception as e:
            print("[ADS] edit btns json err:", e)

    fields = dict(title=title, body=body, contact_url=contact_url,
                  contact_label=contact_label, ends_at=ends_at,
                  info_html=info_html)
    if custom_buttons is not None:
        fields["custom_buttons"] = custom_buttons
    ads_update(aid, **fields)
    return redirect(url_for("admin_contests") + "#ads")


@app.route("/admin/ads/toggle-pin/<int:aid>")
@admin_required
def admin_ads_toggle_pin(aid):
    ads_toggle_pin(aid)
    return redirect(url_for("admin_contests") + "#ads")


@app.route("/admin/ads/toggle-status/<int:aid>")
@admin_required
def admin_ads_toggle_status(aid):
    ads_toggle_status(aid)
    return redirect(url_for("admin_contests") + "#ads")


@app.route("/admin/ads/add", methods=["POST"])
@admin_required
def admin_ads_add():
    from werkzeug.utils import secure_filename
    from datetime import datetime as _dtnow
    print("[ADS-ADD] === استقبال طلب ===")
    print("[ADS-ADD] title:", repr(request.form.get("title", ""))[:100])
    print("[ADS-ADD] body:", repr(request.form.get("body", ""))[:100])
    print("[ADS-ADD] info_html:", repr(request.form.get("info_html", ""))[:100])
    print("[ADS-ADD] custom_buttons_json:", repr(request.form.get("custom_buttons_json", ""))[:200])
    title = request.form.get("title", "").strip()
    # العنوان اختياري — لو فاضي نخليه فاضي

    # ═══ اقرأ الحقول الإضافية ═══
    body = request.form.get("body", "").strip()
    contact_url = request.form.get("contact_url", "").strip()
    contact_label = request.form.get("contact_label", "تواصل").strip() or "تواصل"
    info_html = request.form.get("info_html", "").strip()[:10000]
    ends_at = 0
    ends_str = request.form.get("ends_at", "").strip()
    if ends_str:
        try:
            from datetime import datetime as _dt
            ends_at = _dt.strptime(ends_str, "%Y-%m-%dT%H:%M").timestamp()
        except Exception:
            pass

    # ═══ اقرأ الأزرار المخصصة من Form ═══
    custom_buttons = []
    btns_json = request.form.get("custom_buttons_json", "").strip()
    if btns_json:
        try:
            parsed = json.loads(btns_json)
            if isinstance(parsed, list):
                for b in parsed[:10]:  # حد أقصى 10 أزرار
                    if not isinstance(b, dict):
                        continue
                    label = (b.get("label") or "").strip()[:50]
                    url = (b.get("url") or "").strip()[:500]
                    icon_svg = (b.get("icon_svg") or "").strip()[:20000]
                    color = (b.get("color") or "#25D366").strip()[:20]
                    if not label and not url:
                        continue
                    mode = (b.get("mode") or "normal").strip()
                    if mode not in ("normal", "preview", "html"):
                        mode = "normal"
                    html_content = (b.get("html") or "").strip()[:50000]
                    custom_buttons.append({
                        "label": label,
                        "url": url,
                        "icon_svg": icon_svg,
                        "color": color,
                        "mode": mode,
                        "html": html_content
                    })
        except Exception as e:
            print("[ADS] btns json err:", e)

    # أنشئ الإعلان أول
    aid = ads_add(title, body, [], contact_url, contact_label, 0, ends_at, custom_buttons, info_html)
    if not aid:
        return redirect(url_for("admin_contests") + "#ads")

    # ارفع الصور
    files = request.files.getlist("images")
    saved = []
    allowed = ["jpg", "jpeg", "png", "gif", "webp"]
    for f in files:
        if not f or not f.filename:
            continue
        fn = secure_filename(f.filename)
        ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else ""
        if ext not in allowed:
            continue
        new_name = "ad_" + str(int(time.time() * 1000)) + "_" + fn
        try:
            os.makedirs(os.path.join(UPLOAD_FOLDER, "ads"), exist_ok=True)
            filepath = os.path.join(UPLOAD_FOLDER, "ads", new_name)
            f.save(filepath)
            # ضغط الصورة
            try:
                from PIL import Image, ImageOps
                im = Image.open(filepath)
                im = ImageOps.exif_transpose(im)
                im.thumbnail((1200, 1200))
                if ext in ("jpg", "jpeg"):
                    im.convert("RGB").save(filepath, "JPEG", quality=82, optimize=True)
                elif ext == "png":
                    im.save(filepath, "PNG", optimize=True)
                else:
                    im.save(filepath, "WEBP", quality=82)
            except Exception as e:
                print("[ADS] compress err:", e)
            saved.append("ads/" + new_name)
        except Exception as e:
            print("[ADS] save err:", e)

    if saved:
        ads_add_images(aid, saved)

    print(f"[ADS] أُضيف إعلان #{aid}: {title} — {len(saved)} صورة")
    return redirect(url_for("admin_contests") + "#ads")


@app.route("/admin/ads/delete-image/<int:aid>/<path:img_name>")
@admin_required
def admin_ads_delete_image(aid, img_name):
    """حذف صورة من إعلان — يدعم المسارات الفرعية"""
    import os as _os_del
    a = ads_get(aid)
    if not a:
        return redirect(url_for("admin_contests") + "#ads")
    imgs = a.get("images") or []
    # طابق أي صورة تحتوي على اسم الملف
    new_imgs = []
    deleted = False
    for img in imgs:
        # img عادة "ads/ad_xxx.jpg"
        base = _os_del.path.basename(img)
        if base == img_name or img == img_name or base == _os_del.path.basename(img_name):
            # احذف الملف
            try:
                p = _os_del.path.join(UPLOAD_FOLDER, "ads", base)
                if _os_del.path.exists(p):
                    _os_del.remove(p)
                    print(f"[ADS] حذف ملف: {p}")
            except Exception as e:
                print(f"[ADS] خطأ حذف: {e}")
            deleted = True
        else:
            new_imgs.append(img)
    if deleted:
        ads_update(aid, images=new_imgs)
    return redirect(url_for("admin_contests") + "#ads")


# ═══════════════════════════════════════════
# SOCIAL — دوال الشبكة الاجتماعية
# ═══════════════════════════════════════════
def social_post_add(author, kind="text", body="", media=None, attach="", attach_name=""):
    """إضافة منشور اجتماعي"""
    try:
        conn = _db()
        c = conn.cursor()
        c.execute("""
            INSERT INTO social_posts (author, kind, body, media, attach, attach_name, pinned, status, created, updated)
            VALUES (?, ?, ?, ?, ?, ?, 0, 'active', ?, ?)
        """, (
            author, kind, body,
            json.dumps(media or [], ensure_ascii=False),
            attach, attach_name,
            time.time(), time.time()
        ))
        pid = c.lastrowid
        conn.commit()
        conn.close()
        print(f"[SOCIAL] منشور جديد #{pid} بواسطة {author}")
        return pid
    except Exception as e:
        print("social_post_add err:", e)
        return None


def social_post_get(pid):
    try:
        conn = _db()
        row = conn.execute("SELECT * FROM social_posts WHERE id=?", (pid,)).fetchone()
        conn.close()
        if not row:
            return None
        d = dict(row)
        try:
            d["media"] = json.loads(d.get("media") or "[]")
        except:
            d["media"] = []
        return d
    except Exception as e:
        print("social_post_get err:", e)
        return None


def social_post_list(only_active=True, limit=50):
    """قائمة المنشورات — مع عدّاد التعليقات والإعجابات"""
    try:
        conn = _db()
        if only_active:
            rows = conn.execute(
                "SELECT * FROM social_posts WHERE status='active' ORDER BY pinned DESC, created DESC LIMIT ?",
                (limit,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM social_posts ORDER BY pinned DESC, created DESC LIMIT ?",
                (limit,)
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["media"] = json.loads(d.get("media") or "[]")
            except:
                d["media"] = []
            # عدد التعليقات
            cc = conn.execute("SELECT COUNT(*) as n FROM social_comments WHERE post_id=?", (d["id"],)).fetchone()
            d["comments_count"] = cc["n"] if cc else 0
            # عدد الإعجابات
            rc = conn.execute("SELECT COUNT(*) as n FROM social_reactions WHERE post_id=?", (d["id"],)).fetchone()
            d["likes_count"] = rc["n"] if rc else 0
            result.append(d)
        conn.close()
        return result
    except Exception as e:
        print("social_post_list err:", e)
        return []


def social_post_update(pid, **fields):
    allowed = {"body", "kind", "media", "attach", "attach_name", "status", "pinned", "author"}
    sets = []
    vals = []
    for k, v in fields.items():
        if k in allowed:
            if k == "media" and isinstance(v, list):
                v = json.dumps(v, ensure_ascii=False)
            sets.append(k + "=?")
            vals.append(v)
    if not sets:
        return False
    sets.append("updated=?")
    vals.append(time.time())
    vals.append(pid)
    try:
        conn = _db()
        conn.execute("UPDATE social_posts SET " + ", ".join(sets) + " WHERE id=?", vals)
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print("social_post_update err:", e)
        return False


def social_post_toggle_pin(pid):
    p = social_post_get(pid)
    if not p:
        return False
    return social_post_update(pid, pinned=0 if p.get("pinned") else 1)


def social_post_toggle_status(pid):
    p = social_post_get(pid)
    if not p:
        return False
    return social_post_update(pid, status="paused" if p.get("status") == "active" else "active")


def social_post_delete(pid):
    try:
        conn = _db()
        # احذف الصور
        p = social_post_get(pid)
        if p and p.get("media"):
            for img in p["media"]:
                try:
                    basename = os.path.basename(img)
                    path = os.path.join(UPLOAD_FOLDER, "social", basename)
                    if os.path.exists(path):
                        os.remove(path)
                except:
                    pass
        # احذف الملف المرفق
        if p and p.get("attach"):
            try:
                basename = os.path.basename(p["attach"])
                path = os.path.join(UPLOAD_FOLDER, "social", basename)
                if os.path.exists(path):
                    os.remove(path)
            except:
                pass
        # احذف التعليقات والإعجابات
        conn.execute("DELETE FROM social_comments WHERE post_id=?", (pid,))
        conn.execute("DELETE FROM social_reactions WHERE post_id=?", (pid,))
        conn.execute("DELETE FROM social_posts WHERE id=?", (pid,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print("social_post_delete err:", e)
        return False


# ═══ التعليقات ═══
def social_comment_add(post_id, author, body, parent_id=0):
    """يضيف تعليق — parent_id=0 يعني تعليق رئيسي، غير 0 يعني رد"""
    if not body or not body.strip():
        return None
    try:
        parent_id = int(parent_id or 0)
    except (ValueError, TypeError):
        parent_id = 0
    try:
        conn = _db()
        c = conn.cursor()
        # لو parent_id غير صفر — تحقق أنه موجود وينتمي لنفس المنشور
        if parent_id > 0:
            row = c.execute(
                "SELECT id FROM social_comments WHERE id=? AND post_id=?",
                (parent_id, post_id)
            ).fetchone()
            if not row:
                parent_id = 0
        c.execute("""
            INSERT INTO social_comments (post_id, author, body, parent_id, created)
            VALUES (?, ?, ?, ?, ?)
        """, (post_id, author, body.strip()[:1000], parent_id, time.time()))
        cid = c.lastrowid
        conn.commit()
        conn.close()
        return cid
    except Exception as e:
        print("social_comment_add err:", e)
        return None


def social_comments_list(post_id, limit=200):
    """يرجع التعليقات كشجرة — الرئيسية أولاً، ثم الردود تحتها"""
    try:
        conn = _db()
        rows = conn.execute(
            "SELECT * FROM social_comments WHERE post_id=? ORDER BY created ASC LIMIT ?",
            (post_id, limit)
        ).fetchall()
        conn.close()
        all_comments = [dict(r) for r in rows]
        # افصل الرئيسية والردود
        by_parent = {}
        roots = []
        for cm in all_comments:
            pid = cm.get("parent_id") or 0
            if pid == 0:
                cm["replies"] = []
                roots.append(cm)
            else:
                by_parent.setdefault(pid, []).append(cm)
        # اربط الردود بأهلها
        for root in roots:
            root["replies"] = by_parent.get(root["id"], [])
        # أي رد بدون أب موجود (حالة نادرة) → ارفعه لرئيسي
        orphan_ids = set(by_parent.keys()) - set(r["id"] for r in roots)
        for oid in orphan_ids:
            for cm in by_parent.get(oid, []):
                cm["replies"] = []
                roots.append(cm)
        return roots
    except Exception as e:
        print("social_comments_list err:", e)
        return []


def social_comment_delete(cid):
    try:
        conn = _db()
        conn.execute("DELETE FROM social_comments WHERE id=?", (cid,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print("social_comment_delete err:", e)
        return False


# ═══ التفاعلات (إعجابات) ═══
REACTIONS = ["like", "love", "haha", "wow", "sad", "angry"]
REACTION_EMOJI = {
    "like": "👍",
    "love": "❤️",
    "haha": "😂",
    "wow": "😮",
    "sad": "😢",
    "angry": "😡"
}


def social_react(post_id, author, kind="like"):
    """يضيف/يغيّر تفاعل"""
    if kind not in REACTIONS:
        kind = "like"
    try:
        conn = _db()
        c = conn.cursor()
        # تحقق إذا موجود
        existing = c.execute(
            "SELECT id, kind FROM social_reactions WHERE post_id=? AND author=?",
            (post_id, author)
        ).fetchone()
        if existing:
            if existing["kind"] == kind:
                # نفس التفاعل → احذفه (إلغاء)
                c.execute("DELETE FROM social_reactions WHERE id=?", (existing["id"],))
                conn.commit()
                conn.close()
                return {"ok": True, "action": "removed", "kind": kind}
            else:
                # غيّر التفاعل
                c.execute("UPDATE social_reactions SET kind=?, created=? WHERE id=?",
                          (kind, time.time(), existing["id"]))
                conn.commit()
                conn.close()
                return {"ok": True, "action": "changed", "kind": kind}
        else:
            c.execute("""
                INSERT INTO social_reactions (post_id, author, kind, created)
                VALUES (?, ?, ?, ?)
            """, (post_id, author, kind, time.time()))
            conn.commit()
            conn.close()
            return {"ok": True, "action": "added", "kind": kind}
    except Exception as e:
        print("social_react err:", e)
        return {"ok": False, "error": str(e)}


def social_reactions_summary(post_id):
    """ملخص الإعجابات لكل منشور"""
    try:
        conn = _db()
        rows = conn.execute(
            "SELECT kind, COUNT(*) as n FROM social_reactions WHERE post_id=? GROUP BY kind",
            (post_id,)
        ).fetchall()
        conn.close()
        result = {k: 0 for k in REACTIONS}
        for r in rows:
            result[r["kind"]] = r["n"]
        return result
    except Exception as e:
        print("social_reactions_summary err:", e)
        return {k: 0 for k in REACTIONS}


def social_reactions_list(post_id, limit=50):
    """قائمة المصوّتين (للأدمن)"""
    try:
        conn = _db()
        rows = conn.execute(
            "SELECT * FROM social_reactions WHERE post_id=? ORDER BY created DESC LIMIT ?",
            (post_id, limit)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        return []


def social_user_reaction(post_id, author):
    """يرجع تفاعل المستخدم على منشور"""
    try:
        conn = _db()
        row = conn.execute(
            "SELECT kind FROM social_reactions WHERE post_id=? AND author=?",
            (post_id, author)
        ).fetchone()
        conn.close()
        return row["kind"] if row else None
    except:
        return None


# ═══════════════════════════════════════════
# ADMIN — SOCIAL (الشبكة الاجتماعية)
# ═══════════════════════════════════════════
@app.route("/admin/social/upload/<int:post_id>", methods=["POST"])
@admin_required
def admin_social_upload(post_id):
    """يرفع ملفات لمنشور اجتماعي"""
    from werkzeug.utils import secure_filename
    files = request.files.getlist("files")
    if not files:
        return jsonify({"ok": False, "error": "no files"}), 400

    p = social_post_get(post_id)
    if not p:
        return jsonify({"ok": False, "error": "not found"}), 404

    saved_media = []
    saved_attach = ""
    saved_attach_name = ""

    allowed_media = ["jpg", "jpeg", "png", "gif", "webp", "mp4", "mov", "webm"]
    allowed_attach = ["pdf", "zip", "rar", "doc", "docx", "xls", "xlsx", "txt", "ppt", "pptx", "apk"]

    for f in files:
        if not f or not f.filename:
            continue
        fn = secure_filename(f.filename)
        ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else ""

        # ملف مرفق
        if ext in allowed_attach and not saved_attach:
            new_name = "soc_att_" + str(int(time.time() * 1000)) + "_" + fn
            try:
                os.makedirs(os.path.join(UPLOAD_FOLDER, "social"), exist_ok=True)
                fp = os.path.join(UPLOAD_FOLDER, "social", new_name)
                f.save(fp)
                saved_attach = "social/" + new_name
                saved_attach_name = f.filename
                print(f"[SOCIAL] مرفق: {new_name}")
            except Exception as e:
                print("social attach save err:", e)
            continue

        # وسائط (صور / فيديو)
        if ext in allowed_media:
            is_video = ext in ["mp4", "mov", "webm"]
            # لو فيديو → احفظه مباشرة
            if is_video:
                new_name = "soc_" + str(int(time.time() * 1000)) + "_" + fn
                try:
                    os.makedirs(os.path.join(UPLOAD_FOLDER, "social"), exist_ok=True)
                    fp = os.path.join(UPLOAD_FOLDER, "social", new_name)
                    f.save(fp)
                    saved_media.append({"type": "video", "src": "social/" + new_name})
                    print(f"[SOCIAL] فيديو: {new_name}")
                except Exception as e:
                    print("social video save err:", e)
            else:
                # صورة → ضغط
                new_name = "soc_" + str(int(time.time() * 1000)) + "_" + fn
                try:
                    os.makedirs(os.path.join(UPLOAD_FOLDER, "social"), exist_ok=True)
                    fp = os.path.join(UPLOAD_FOLDER, "social", new_name)
                    f.save(fp)
                    # ضغط
                    try:
                        from PIL import Image, ImageOps
                        im = Image.open(fp)
                        im = ImageOps.exif_transpose(im)
                        im.thumbnail((1400, 1400))
                        if ext in ("jpg", "jpeg"):
                            im.convert("RGB").save(fp, "JPEG", quality=85, optimize=True)
                        elif ext == "png":
                            im.save(fp, "PNG", optimize=True)
                        else:
                            im.save(fp, "WEBP", quality=85)
                    except Exception as e:
                        print("social img compress err:", e)
                    saved_media.append({"type": "image", "src": "social/" + new_name})
                    print(f"[SOCIAL] صورة: {new_name}")
                except Exception as e:
                    print("social image save err:", e)

    # حدّث المنشور
    current_media = p.get("media") or []
    current_media.extend(saved_media)
    fields = {"media": current_media}
    if saved_attach:
        fields["attach"] = saved_attach
        fields["attach_name"] = saved_attach_name
    social_post_update(post_id, **fields)

    return jsonify({"ok": True, "media": saved_media, "attach": saved_attach})


@app.route("/admin/social/remove/<int:post_id>/<path:idx>")
@admin_required
def admin_social_remove(post_id, idx):
    """يحذف وسيط منشور"""
    import os as _os2
    p = social_post_get(post_id)
    if not p:
        return redirect(url_for("admin_contests") + "#social")
    media = p.get("media") or []
    try:
        i = int(idx)
        if 0 <= i < len(media):
            item = media[i]
            src = item.get("src", "") if isinstance(item, dict) else item
            # احذف الملف
            try:
                base = _os2.path.basename(src)
                fp = _os2.path.join(UPLOAD_FOLDER, "social", base)
                if _os2.path.exists(fp):
                    _os2.remove(fp)
            except:
                pass
            media.pop(i)
            social_post_update(post_id, media=media)
    except Exception as e:
        print("social remove err:", e)
    return redirect(url_for("admin_contests") + "#social")


@app.route("/admin/social/remove-attach/<int:post_id>")
@admin_required
def admin_social_remove_attach(post_id):
    import os as _os2
    p = social_post_get(post_id)
    if not p:
        return redirect(url_for("admin_contests") + "#social")
    att = p.get("attach", "")
    if att:
        try:
            base = _os2.path.basename(att)
            fp = _os2.path.join(UPLOAD_FOLDER, "social", base)
            if _os2.path.exists(fp):
                _os2.remove(fp)
        except:
            pass
    social_post_update(post_id, attach="", attach_name="")
    return redirect(url_for("admin_contests") + "#social")


@app.route("/admin/social/add", methods=["POST"])
@admin_required
def admin_social_add():
    """إضافة منشور — نص + وسائط + مرفق"""
    from werkzeug.utils import secure_filename
    from datetime import datetime as _dt

    body = request.form.get("body", "").strip()
    title = request.form.get("title", "").strip()

    # ابحث عن وسائط ومرفقات
    files = request.files.getlist("files") if "files" in request.files else []

    # اسم المؤلف
    author = (session.get("user_name") or "admin").strip()
    if author.lower() == "admin":
        author = session.get("admin_name", "الأدمن")

    # لو ما فيه نص ولا ملفات → ارفض
    if not body and not files:
        return redirect(url_for("admin_contests") + "#social")

    # أنشئ المنشور أول (نص فقط)
    media_list = []
    attach = ""
    attach_name = ""

    # احفظ الملفات
    allowed_media = ["jpg", "jpeg", "png", "gif", "webp", "mp4", "mov", "webm"]
    allowed_attach = ["pdf", "zip", "rar", "doc", "docx", "xls", "xlsx", "txt", "ppt", "pptx", "apk"]

    for f in files:
        if not f or not f.filename:
            continue
        fn = secure_filename(f.filename)
        ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else ""

        if ext in allowed_attach and not attach:
            new_name = "soc_att_" + str(int(time.time() * 1000)) + "_" + fn
            try:
                os.makedirs(os.path.join(UPLOAD_FOLDER, "social"), exist_ok=True)
                fp = os.path.join(UPLOAD_FOLDER, "social", new_name)
                f.save(fp)
                attach = "social/" + new_name
                attach_name = f.filename
            except Exception as e:
                print("attach err:", e)
            continue

        if ext in allowed_media:
            is_video = ext in ["mp4", "mov", "webm"]
            new_name = "soc_" + str(int(time.time() * 1000)) + "_" + fn
            try:
                os.makedirs(os.path.join(UPLOAD_FOLDER, "social"), exist_ok=True)
                fp = os.path.join(UPLOAD_FOLDER, "social", new_name)
                f.save(fp)
                if not is_video:
                    try:
                        from PIL import Image, ImageOps
                        im = Image.open(fp)
                        im = ImageOps.exif_transpose(im)
                        im.thumbnail((1400, 1400))
                        if ext in ("jpg", "jpeg"):
                            im.convert("RGB").save(fp, "JPEG", quality=85, optimize=True)
                        elif ext == "png":
                            im.save(fp, "PNG", optimize=True)
                    except:
                        pass
                media_list.append({
                    "type": "video" if is_video else "image",
                    "src": "social/" + new_name
                })
            except Exception as e:
                print("media err:", e)

    # النوع
    kind = "text"
    if media_list:
        has_video = any(m["type"] == "video" for m in media_list)
        kind = "video" if has_video else "image"

    pid = social_post_add(author, kind, body, media_list, attach, attach_name)
    if pid:
        print(f"[SOCIAL] منشور #{pid}: {body[:40]}... — {len(media_list)} وسائط")
    return redirect(url_for("admin_contests") + "#social")


@app.route("/admin/social/edit/<int:pid>", methods=["POST"])
@admin_required
def admin_social_edit(pid):
    body = request.form.get("body", "").strip()
    social_post_update(pid, body=body)
    return redirect(url_for("admin_contests") + "#social")


@app.route("/admin/social/toggle-pin/<int:pid>")
@admin_required
def admin_social_toggle_pin(pid):
    social_post_toggle_pin(pid)
    return redirect(url_for("admin_contests") + "#social")


@app.route("/admin/social/toggle-status/<int:pid>")
@admin_required
def admin_social_toggle_status(pid):
    social_post_toggle_status(pid)
    return redirect(url_for("admin_contests") + "#social")


@app.route("/admin/social/delete/<int:pid>")
@admin_required
def admin_social_delete(pid):
    social_post_delete(pid)
    return redirect(url_for("admin_contests") + "#social")


@app.route("/admin/social/view/<int:pid>")
@admin_required
def admin_social_view(pid):
    """معاينة منشور + تعليقاته"""
    p = social_post_get(pid)
    if not p:
        return redirect(url_for("admin_contests") + "#social")
    comments = social_comments_list(pid, limit=200)
    reactions = social_reactions_summary(pid)
    users = load_users()
    # اربط التعليقات بالمستخدمين
    for c in comments:
        u = users.get(c["author"].lower(), {})
        c["avatar"] = u.get("avatar", "")
        c["display"] = u.get("username", c["author"])
    return render_template_string(
        SOCIAL_POST_ADMIN_HTML,
        post=p, comments=comments, reactions=reactions,
        reaction_emoji=REACTION_EMOJI
    )


@app.route("/admin/social/comment-delete/<int:cid>")
@admin_required
def admin_social_comment_delete(cid):
    social_comment_delete(cid)
    return redirect(request.referrer or url_for("admin_contests") + "#social")


# ═══════════════════════════════════════════
# EXPLORE — API للاجتماعي
# ═══════════════════════════════════════════
@app.route("/api/social/posts")
def api_social_posts():
    """جلب المنشورات للمستخدمين"""
    if not session.get("user_logged") and not session.get("admin_logged"):
        return jsonify({"ok": False}), 401
    posts = social_post_list(only_active=True, limit=50)
    users = load_users()
    me = (session.get("user_name") or "").strip().lower()
    if not me and session.get("admin_logged"):
        me = "admin"
    out = []
    for p in posts:
        u = users.get(p["author"].lower(), {})
        # تفاعل المستخدم
        my_react = social_user_reaction(p["id"], me) if me else None
        reactions = social_reactions_summary(p["id"])
        out.append({
            "id": p["id"],
            "author": p["author"],
            "author_display": u.get("username", p["author"]),
            "author_avatar": u.get("avatar", ""),
            "kind": p.get("kind", "text"),
            "body": p.get("body", ""),
            "media": p.get("media", []),
            "attach": p.get("attach", ""),
            "attach_name": p.get("attach_name", ""),
            "pinned": bool(p.get("pinned")),
            "created": p.get("created", 0),
            "comments_count": p.get("comments_count", 0),
            "likes_count": p.get("likes_count", 0),
            "reactions": reactions,
            "my_reaction": my_react
        })
    return jsonify({"ok": True, "posts": out, "count": len(out)})


@app.route("/api/social/comments/<int:pid>")
def api_social_comments(pid):
    if not session.get("user_logged") and not session.get("admin_logged"):
        return jsonify({"ok": False}), 401
    comments = social_comments_list(pid, limit=200)
    users = load_users()

    def _pack(c):
        u = users.get(c["author"].lower(), {})
        out = {
            "id": c["id"],
            "author": c["author"],
            "author_display": u.get("username", c["author"]),
            "author_avatar": u.get("avatar", ""),
            "body": c.get("body", ""),
            "parent_id": c.get("parent_id") or 0,
            "created": c.get("created", 0),
            "replies": []
        }
        for r in c.get("replies", []):
            ru = users.get(r["author"].lower(), {})
            out["replies"].append({
                "id": r["id"],
                "author": r["author"],
                "author_display": ru.get("username", r["author"]),
                "author_avatar": ru.get("avatar", ""),
                "body": r.get("body", ""),
                "parent_id": r.get("parent_id") or 0,
                "created": r.get("created", 0)
            })
        return out

    out = [_pack(c) for c in comments]
    total = sum(1 + len(c["replies"]) for c in out)
    return jsonify({"ok": True, "comments": out, "count": total})


@app.route("/api/social/comment/<int:pid>", methods=["POST"])
def api_social_comment_add(pid):
    if not session.get("user_logged") and not session.get("admin_logged"):
        return jsonify({"ok": False, "error": "login"}), 401
    author = (session.get("user_name") or "").strip()
    if not author and session.get("admin_logged"):
        author = "admin"
    if not author:
        return jsonify({"ok": False, "error": "no user"}), 401
    data = request.get_json(silent=True) or {}
    body = (data.get("body") or "").strip()
    parent_id = data.get("parent_id", 0)
    if not body:
        return jsonify({"ok": False, "error": "empty"}), 400
    cid = social_comment_add(pid, author, body, parent_id)
    if not cid:
        return jsonify({"ok": False, "error": "failed"}), 500
    users = load_users()
    u = users.get(author.lower(), {})
    # احسب parent_id الفعلي بعد التحقق (قد يكون صُفّر)
    real_parent = 0
    try:
        conn = _db()
        row = conn.execute(
            "SELECT parent_id FROM social_comments WHERE id=?", (cid,)
        ).fetchone()
        if row:
            real_parent = row["parent_id"] or 0
        conn.close()
    except Exception:
        pass
    return jsonify({
        "ok": True,
        "comment": {
            "id": cid,
            "author": author,
            "author_display": u.get("username", author),
            "author_avatar": u.get("avatar", ""),
            "body": body,
            "parent_id": real_parent,
            "created": time.time()
        }
    })


@app.route("/api/social/react/<int:pid>", methods=["POST"])
def api_social_react(pid):
    if not session.get("user_logged") and not session.get("admin_logged"):
        return jsonify({"ok": False, "error": "login"}), 401
    author = (session.get("user_name") or "").strip()
    if not author and session.get("admin_logged"):
        author = "admin"
    if not author:
        return jsonify({"ok": False}), 401
    data = request.get_json(silent=True) or {}
    kind = (data.get("kind") or "like").strip()
    result = social_react(pid, author, kind)
    if result.get("ok"):
        # جيب الملخص الجديد
        summary = social_reactions_summary(pid)
        result["reactions"] = summary
        result["total"] = sum(summary.values())
    return jsonify(result)


@app.route("/uploads/social/<path:filename>")
def serve_social_file(filename):
    from flask import send_from_directory
    return send_from_directory(os.path.join(UPLOAD_FOLDER, "social"), filename)


if __name__ == "__main__":
    # ═══ رسالة التشغيل المميزة (ملونة) ═══
    # ألوان ANSI
    R = "\033[0m"        # reset
    B = "\033[1m"        # bold
    DIM = "\033[2m"      # dim

    # ألوان
    PURPLE = "\033[38;5;141m"    # بنفسجي
    CYAN = "\033[38;5;51m"       # سماوي
    GREEN = "\033[38;5;48m"      # أخضر
    YELLOW = "\033[38;5;220m"    # أصفر
    RED = "\033[38;5;203m"       # أحمر
    GRAY = "\033[38;5;245m"      # رمادي
    WHITE = "\033[38;5;255m"     # أبيض
    ORANGE = "\033[38;5;215m"    # برتقالي
    PINK = "\033[38;5;213m"      # وردي
    BG_PURPLE = "\033[48;5;54m"  # خلفية بنفسجية
    BG_DARK = "\033[48;5;17m"    # خلفية داكنة

    print("")
    print(PURPLE + "╔══════════════════════════════════════════════════════╗" + R)
    print(PURPLE + "║" + BG_PURPLE + "                                                      " + R + PURPLE + "║" + R)
    print(PURPLE + "║" + BG_PURPLE + "  " + CYAN + B + "  ██████╗ ████████╗██████╗  " + R + BG_PURPLE + "                        " + R + PURPLE + "║" + R)
    print(PURPLE + "║" + BG_PURPLE + "  " + CYAN + B + " ██╔═══██╗╚══██╔══╝██╔══██╗ " + R + BG_PURPLE + "                        " + R + PURPLE + "║" + R)
    print(PURPLE + "║" + BG_PURPLE + "  " + CYAN + B + " ██║   ██║   ██║   ██████╔╝ " + R + BG_PURPLE + "                        " + R + PURPLE + "║" + R)
    print(PURPLE + "║" + BG_PURPLE + "  " + CYAN + B + " ██║   ██║   ██║   ██╔═══╝  " + R + BG_PURPLE + "                        " + R + PURPLE + "║" + R)
    print(PURPLE + "║" + BG_PURPLE + "  " + CYAN + B + " ╚██████╔╝   ██║   ██║      " + R + BG_PURPLE + "                        " + R + PURPLE + "║" + R)
    print(PURPLE + "║" + BG_PURPLE + "  " + CYAN + B + "  ╚═════╝    ╚═╝   ╚═╝      " + R + BG_PURPLE + "                        " + R + PURPLE + "║" + R)
    print(PURPLE + "║" + BG_PURPLE + "                                                      " + R + PURPLE + "║" + R)
    print(PURPLE + "║" + BG_PURPLE + "        " + YELLOW + B + "🚀  موقع أرقام OTP" + R + BG_PURPLE + "                           " + R + PURPLE + "║" + R)
    print(PURPLE + "║" + BG_PURPLE + "        " + GREEN + B + "⚡  الإصدار 1.0" + R + BG_PURPLE + "                             " + R + PURPLE + "║" + R)
    print(PURPLE + "║" + BG_PURPLE + "                                                      " + R + PURPLE + "║" + R)
    print(PURPLE + "╚══════════════════════════════════════════════════════╝" + R)
    print("")
    print(GREEN + B + "  🎯  جاري تشغيل الموقع..." + R)
    print("")
    print(GRAY + "  ┌───────────────────────────────────────────────┐" + R)
    print(GRAY + "  │" + R + "                                               " + GRAY + "│" + R)
    print(GRAY + "  │" + R + "   " + CYAN + "📍  الرابط المحلي:" + R + "                          " + GRAY + "│" + R)
    print(GRAY + "  │" + R + "       " + WHITE + B + "http://127.0.0.1:5000" + R + "                   " + GRAY + "│" + R)
    print(GRAY + "  │" + R + "                                               " + GRAY + "│" + R)
    print(GRAY + "  │" + R + "   " + YELLOW + "🔓  لوحة الأدمن:" + R + "                            " + GRAY + "│" + R)
    print(GRAY + "  │" + R + "       " + WHITE + B + "http://127.0.0.1:5000/admin" + R + "             " + GRAY + "│" + R)
    print(GRAY + "  │" + R + "                                               " + GRAY + "│" + R)
    print(GRAY + "  │" + R + "   " + RED + "🔑  كلمة السر: " + PINK + B + "admin2025" + R + "                    " + GRAY + "│" + R)
    print(GRAY + "  │" + R + "                                               " + GRAY + "│" + R)
    print(GRAY + "  └───────────────────────────────────────────────┘" + R)
    print("")
    print(ORANGE + "  💡  للحصول على الرابط الخارجي، استخدم: " + GREEN + B + "./start.sh" + R)
    print("")
    print(PURPLE + "  ═══════════════════════════════════════════════════════" + R)
    print(RED + "  ⚠️   للخروج: اضغط " + YELLOW + B + "Ctrl+C" + R)
    print(PURPLE + "  ═══════════════════════════════════════════════════════" + R)
    print("")

    db_init()  # إنشاء/تحديث جداول قاعدة البيانات
    _ensure_platform_icon_pngs()
    print('✅ قاعدة البيانات جاهزة')
    start_telegram_bot()

    # ═══ كشف البيئة ═══
    import os as _os_env
    IS_RENDER = bool(_os_env.environ.get("RENDER"))
    PORT = int(_os_env.environ.get("PORT", 5000))

    if IS_RENDER:
        print("🌐 يعمل على Render")
        print("   PORT = " + str(PORT))
    else:
        print("📱 يعمل على Termux")
        # نشغل tunnel بعد ما يبدأ السيرفر
        import threading as _th_main
        def _delay_tunnel():
            import time as _t
            _t.sleep(3)
            start_cloudflare_tunnel(5000)
        _th_main.Thread(target=_delay_tunnel, daemon=True).start()

    # ═══ تشغيل السيرفر ═══
    app.run(
        debug=False,
        host='0.0.0.0',
        port=PORT,
        threaded=True,
        use_reloader=False,
        processes=1
    )

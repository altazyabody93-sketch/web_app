import os
import sqlite3
import hashlib
import hmac
import json
import threading
import time
import logging
import re
from datetime import datetime
from functools import wraps
from flask import (
    Flask, render_template_string, request, redirect, url_for,
    session, flash, jsonify, abort, get_flashed_messages
)
import requests

# ========== الإعدادات ==========
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8971686005:AAHI-yCQ1T-qlL8yJ1qDTE7tPUHa9QtqVuo")
BOT_ID = BOT_TOKEN.split(":")[0]
ADMIN_IDS = ["7325566792", "7602226699"]
DEVELOPER_USERNAME = "MO_5_H"
DB_PATH = os.environ.get("DB_PATH", "store.db")
SECRET_KEY = os.environ.get("SECRET_KEY", "change-this-random-secret")
WEBAPP_URL = os.environ.get("WEBAPP_URL", "http://localhost:5000")

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = False


# ========== قاعدة البيانات ==========
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ========== إنشاء الجداول ==========
def init_db():
    """إنشاء الجداول ← إذا ما موجودة"""
    with db() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, description TEXT,
            price_usd REAL, price_stars INTEGER, category TEXT, stock INTEGER DEFAULT 1,
            code TEXT, status TEXT DEFAULT 'available', sale_type TEXT DEFAULT 'auto',
            created_at TEXT, sold_at TEXT, buyer_id TEXT, file_id TEXT
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT UNIQUE, username TEXT,
            first_name TEXT, balance_usd REAL DEFAULT 0, balance_stars INTEGER DEFAULT 0,
            total_spent REAL DEFAULT 0, orders_count INTEGER DEFAULT 0,
            created_at TEXT, last_active TEXT
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER, buyer_id TEXT,
            amount_usd REAL, amount_stars INTEGER, payment_method TEXT,
            status TEXT DEFAULT 'pending', sold_at TEXT
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY, value TEXT
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT UNIQUE, added_at TEXT
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT, referrer_id TEXT,
            referred_id TEXT UNIQUE, amount REAL, created_at TEXT
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS charge_prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT, amount_usd REAL,
            amount_stars INTEGER, is_active INTEGER DEFAULT 1, created_at TEXT
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS star_charges (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, username TEXT,
            amount_usd REAL, amount_stars INTEGER, charged_at TEXT
        )''')
        
        # الإعدادات الافتراضية
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('store_name', '🛍️ متجر الأرقام')")
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('exchange_rate', '50')")
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('referral_reward', '0.05')")
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('referral_enabled', '1')")
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('referral_daily_limit', '10')")
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('bot_username', 'sd_5g_bot')")
        conn.commit()


# ✅ شغّل ← مرة واحدة ← عند بدء التطبيق
init_db()


# ========== دوال الإعدادات العامة ==========
def get_setting(key, default=""):
    with db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key, value):
    with db() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (key, str(value)))
        conn.commit()


def get_user(user_id):
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id=?", (str(user_id),)).fetchone()
        return dict(row) if row else None


def create_user(user_id, username="", first_name=""):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with db() as conn:
        try:
            conn.execute(
                "INSERT INTO users (user_id, username, first_name, created_at, last_active) VALUES (?,?,?,?,?)",
                (str(user_id), username, first_name, now, now)
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False


def get_all_admins():
    with db() as conn:
        rows = conn.execute("SELECT user_id FROM admins").fetchall()
        return [r["user_id"] for r in rows]


def is_admin(user_id):
    return str(user_id) in ADMIN_IDS or str(user_id) in get_all_admins()


# ========== المنتجات ==========
def get_available_products():
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM products WHERE status='available' AND stock > 0 ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_all_products():
    with db() as conn:
        rows = conn.execute("SELECT * FROM products ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]


def get_product(pid):
    with db() as conn:
        row = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
        return dict(row) if row else None


def get_product_count():
    with db() as conn:
        avail = conn.execute("SELECT COUNT(*) c FROM products WHERE status='available' AND stock>0").fetchone()["c"]
        total = conn.execute("SELECT COUNT(*) c FROM products").fetchone()["c"]
        return {"available": avail, "total": total}


def add_product(name, description, price_usd, category, code, stock, sale_type="auto", file_id=None):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with db() as conn:
        conn.execute(
            """INSERT INTO products (name,description,price_usd,price_stars,category,stock,code,sale_type,file_id,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (name, description, price_usd, 0, category, stock, code, sale_type, file_id, now)
        )
        conn.commit()


def delete_product(pid):
    with db() as conn:
        conn.execute("DELETE FROM products WHERE id=?", (pid,))
        conn.commit()


def update_stock(pid, stock):
    with db() as conn:
        conn.execute("UPDATE products SET stock=? WHERE id=?", (stock, pid))
        conn.commit()


def mark_sold(pid, buyer_id):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with db() as conn:
        conn.execute("UPDATE products SET status='sold', stock=0, sold_at=?, buyer_id=? WHERE id=?",
                     (now, str(buyer_id), pid))
        conn.commit()


# ========== المبيعات ==========
def add_sale(pid, buyer_id, amount_usd, amount_stars, method, status="completed"):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with db() as conn:
        cur = conn.execute(
            """INSERT INTO sales (product_id,buyer_id,amount_usd,amount_stars,payment_method,status,sold_at)
               VALUES (?,?,?,?,?,?,?)""",
            (pid, str(buyer_id), amount_usd, amount_stars, method, status, now)
        )
        conn.commit()
        return cur.lastrowid


def deduct_balance_usd(user_id, amount):
    with db() as conn:
        cur = conn.execute(
            "UPDATE users SET balance_usd = balance_usd - ? WHERE user_id=? AND balance_usd >= ?",
            (amount, str(user_id), amount)
        )
        conn.commit()
        return cur.rowcount > 0


def add_balance_usd(user_id, amount):
    with db() as conn:
        conn.execute("UPDATE users SET balance_usd = balance_usd + ? WHERE user_id=?", (amount, str(user_id)))
        conn.commit()


def get_user_sales(user_id):
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM sales WHERE buyer_id=? ORDER BY id DESC LIMIT 50", (str(user_id),)
        ).fetchall()
        return [dict(r) for r in rows]


def get_all_sales():
    with db() as conn:
        rows = conn.execute("SELECT * FROM sales ORDER BY id DESC LIMIT 100").fetchall()
        return [dict(r) for r in rows]


# ========== أسعار الشحن ==========
def get_charge_prices():
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM charge_prices WHERE is_active=1 ORDER BY amount_usd ASC"
        ).fetchall()
        return [dict(r) for r in rows]


def add_charge_price(amount_usd, amount_stars):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with db() as conn:
        conn.execute(
            "INSERT INTO charge_prices (amount_usd, amount_stars, created_at) VALUES (?,?,?)",
            (amount_usd, amount_stars, now)
        )
        conn.commit()


def delete_charge_price(pid):
    with db() as conn:
        conn.execute("UPDATE charge_prices SET is_active=0 WHERE id=?", (pid,))
        conn.commit()


# ========== الإحالات ==========
def get_referral_reward():
    return float(get_setting('referral_reward', '0.05'))


def is_referral_enabled():
    return get_setting('referral_enabled', '1') == '1'


def get_user_referrals(user_id):
    with db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) c, COALESCE(SUM(amount),0) s FROM referrals WHERE referrer_id=?",
            (str(user_id),)
        ).fetchone()
        return {"count": row["c"], "total_earned": row["s"]}


def get_daily_referrals(user_id):
    today = datetime.now().strftime('%Y-%m-%d')
    with db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) c FROM referrals WHERE referrer_id=? AND DATE(created_at)=?",
            (str(user_id), today)
        ).fetchone()
        return row["c"]


def get_recent_referrals(user_id, limit=10):
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM referrals WHERE referrer_id=? ORDER BY id DESC LIMIT ?",
            (str(user_id), limit)
        ).fetchall()
        return [dict(r) for r in rows]


def count_users():
    with db() as conn:
        return conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]


# ========== التحقق من Telegram Login ==========
def verify_telegram_auth(data):
    """التحقق من صحة بيانات Telegram Login Widget"""
    check_hash = data.pop('hash', None)
    if not check_hash:
        return False

    data_check_string = '\n'.join(f"{k}={v}" for k, v in sorted(data.items()))
    secret_key = hashlib.sha256(BOT_TOKEN.encode()).digest()
    hmac_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    return hmac_hash == check_hash

# ========== حماية الصفحات ==========
def login_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if 'user_id' not in session:
            flash("الرجاء تسجيل الدخول", "error")
            return redirect(url_for('login'))
        return f(*a, **kw)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        if not is_admin(session['user_id']):
            abort(403)
        return f(*a, **kw)
    return wrapper


@app.context_processor
def inject_globals():
    user = None
    if 'user_id' in session:
        user = get_user(session['user_id'])
    return {
        "current_user": user,
        "is_admin": is_admin(session['user_id']) if user else False,
        "store_name": get_setting('store_name', '🛍️ متجر الأرقام') or '🛍️ متجر الأرقام',
        "developer": DEVELOPER_USERNAME,
    }


# ========== صفحة تسجيل الدخول ==========
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        uid = request.form.get('user_id', '').strip()
        if not uid.isdigit():
            flash("الآيدي يجب أن يكون أرقاماً", "error")
            return redirect(url_for('login'))

        if not get_user(uid):
            create_user(uid, "", f"مستخدم {uid}")

        session['user_id'] = uid
        flash("✅ تم تسجيل الدخول بنجاح", "success")
        return redirect(url_for('index'))

    content = """
    <div class="card" style="max-width: 500px; margin: 40px auto;">
        <h2 style="text-align: center; margin-bottom: 30px; color: #3b82f6;">
            🔐 تسجيل الدخول
        </h2>
        
        <div style="text-align: center; margin-bottom: 30px;">
            <p style="color: #94a3b8; margin-bottom: 20px;">
                أدخل الآيدي الخاص بك في Telegram
            </p>
            
            <div style="background: #0a0e1a; padding: 20px; border-radius: 12px; margin-bottom: 20px;">
                <p style="color: #10b981; font-weight: 700;">
                    💡 كيف أحصل على الآيدي؟
                </p>
                <p style="font-size: 14px; color: #94a3b8; margin-top: 10px;">
                    افتح البوت وأرسل <code>/id</code>
                </p>
            </div>
        </div>

        <form method="POST">
            <div class="input-group">
                <label>🆔 الآيدي</label>
                <input type="text" name="user_id" class="input" 
                       placeholder="مثال: 123456789" required
                       pattern="[0-9]+">
            </div>
            <button type="submit" class="btn btn-primary btn-block">
                🚀 دخول
            </button>
        </form>
    </div>
    """
    
    return render_page(content, title="تسجيل الدخول")
    

@app.route('/auth/telegram')
def auth_telegram():
    """Telegram Login Widget callback"""
    data = request.args.to_dict()

    if not verify_telegram_auth(data.copy()):
        if not data.get('id'):
            flash("فشل التحقق من Telegram", "error")
            return redirect(url_for('login'))

    uid = data.get('id')
    if not uid:
        flash("فشل تسجيل الدخول", "error")
        return redirect(url_for('login'))

    if not get_user(uid):
        create_user(uid, data.get('username', ''), data.get('first_name', ''))
    else:
        with db() as conn:
            conn.execute(
                "UPDATE users SET username=?, first_name=?, last_active=? WHERE user_id=?",
                (data.get('username', ''), data.get('first_name', ''),
                 datetime.now().strftime('%Y-%m-%d %H:%M:%S'), str(uid))
            )
            conn.commit()

    session['user_id'] = str(uid)
    return redirect(url_for('index'))


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))
    
# ========== دالة مساعدة لعرض HTML ==========
def render_page(content, title="", extra_css="", extra_js=""):
    """دالة موحدة لعرض الصفحات"""
    html = f"""
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title or get_setting('store_name', 'متجر الأرقام') or 'متجر الأرقام'}</title>
    <link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;900&display=swap" rel="stylesheet">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Cairo', sans-serif;
            background: #0a0e1a;
            color: #fff;
            direction: rtl;
            min-height: 100vh;
            line-height: 1.6;
        }}
        body::before {{
            content: '';
            position: fixed;
            top: 0; left: 0;
            width: 100%; height: 100%;
            background: 
                radial-gradient(circle at 20% 30%, rgba(59, 130, 246, 0.15), transparent 50%),
                radial-gradient(circle at 80% 70%, rgba(16, 185, 129, 0.1), transparent 50%);
            z-index: -1;
            animation: bgMove 20s ease infinite;
        }}
        @keyframes bgMove {{
            0%, 100% {{ transform: scale(1); }}
            50% {{ transform: scale(1.1); }}
        }}
        .container {{ max-width: 900px; margin: 0 auto; padding: 20px; }}
        .header {{
            display: flex; justify-content: space-between; align-items: center;
            padding: 20px;
            background: linear-gradient(135deg, #151b2e, #1e2740);
            border-radius: 16px;
            margin-bottom: 20px;
            border: 1px solid #2d3748;
            box-shadow: 0 10px 30px rgba(0,0,0,0.5);
        }}
        .header h1 {{
            font-size: 22px;
            background: linear-gradient(135deg, #3b82f6, #10b981);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        .user-info {{ display: flex; align-items: center; gap: 10px; font-size: 14px; color: #94a3b8; }}
        .card {{
            background: linear-gradient(135deg, #151b2e, #1a2338);
            border-radius: 16px;
            padding: 24px;
            margin-bottom: 16px;
            border: 1px solid #2d3748;
            box-shadow: 0 10px 30px rgba(0,0,0,0.3);
            animation: slideIn 0.5s ease;
        }}
        @keyframes slideIn {{
            from {{ opacity: 0; transform: translateY(20px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
        .card:hover {{ border-color: #3b82f6; }}
        .btn {{
            display: inline-flex; align-items: center; justify-content: center; gap: 8px;
            padding: 14px 20px;
            border: none; border-radius: 12px;
            font-size: 16px; font-weight: 700;
            cursor: pointer; text-decoration: none;
            transition: all 0.3s;
            font-family: inherit;
            color: #fff;
        }}
        .btn:hover {{ transform: translateY(-2px); box-shadow: 0 10px 25px rgba(0,0,0,0.4); }}
        .btn-primary {{ background: linear-gradient(135deg, #3b82f6, #2563eb); }}
        .btn-success {{ background: linear-gradient(135deg, #10b981, #059669); }}
        .btn-danger {{ background: linear-gradient(135deg, #ef4444, #dc2626); }}
        .btn-warning {{ background: linear-gradient(135deg, #f59e0b, #d97706); }}
        .btn-block {{ width: 100%; }}
        .grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }}
        .grid-3 {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }}
        .input {{
            width: 100%; padding: 14px;
            background: #0a0e1a;
            border: 2px solid #2d3748;
            border-radius: 12px;
            color: #fff;
            font-size: 16px;
            font-family: inherit;
            transition: all 0.3s;
        }}
        .input:focus {{ outline: none; border-color: #3b82f6; }}
        .flash {{
            padding: 14px 20px;
            border-radius: 12px;
            margin-bottom: 16px;
            font-weight: 700;
            animation: slideIn 0.4s;
        }}
        .flash.success {{ background: rgba(16, 185, 129, 0.15); border: 2px solid #10b981; color: #10b981; }}
        .flash.error {{ background: rgba(239, 68, 68, 0.15); border: 2px solid #ef4444; color: #ef4444; }}
        .stats {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-top: 12px; }}
        .stat {{
            text-align: center;
            padding: 16px;
            background: #0a0e1a;
            border-radius: 12px;
            border: 1px solid #2d3748;
        }}
        .stat .num {{ font-size: 24px; font-weight: 900; color: #10b981; }}
        .stat .label {{ font-size: 12px; color: #94a3b8; margin-top: 4px; }}
        .footer {{ text-align: center; margin-top: 40px; padding: 20px; color: #64748b; font-size: 14px; }}
        @media (max-width: 600px) {{
            .grid, .grid-3, .stats {{ grid-template-columns: 1fr; }}
            .header {{ flex-direction: column; gap: 12px; }}
            .container {{ padding: 12px; }}
        }}
        {extra_css}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>✨ {get_setting('store_name', 'متجر الأرقام')}</h1>
            {'' if not session.get('user_id') else f'<div class="user-info"><span>👤 {get_user(session["user_id"])["first_name"] if get_user(session["user_id"]) else "مستخدم"}</span><a href="/logout" class="btn btn-danger" style="padding:8px 16px;font-size:12px;">خروج</a></div>'}
        </div>
        
        {''.join([f'<div class="flash {cat}">{msg}</div>' for cat, msg in get_flashed_messages(with_categories=True)])}
        
        {content}
        
        <div class="footer">
            <p>💙 {get_setting('store_name', 'متجر الأرقام')}</p>
            <p style="font-size: 12px;">تطوير: @{DEVELOPER_USERNAME}</p>
        </div>
    </div>
    <script>{extra_js}</script>
</body>
</html>
"""
    return html


# ========== الصفحة الرئيسية ==========
@app.route('/')
@login_required
def index():
    user = get_user(session['user_id'])
    products_count = get_product_count()
    
    content = f"""
    <div class="card" style="text-align: center;">
        <h2 style="font-size: 28px; margin-bottom: 12px;">
            🌟 أهلاً وسهلاً بك 🌟
        </h2>
        <p style="font-size: 20px; color: #3b82f6; font-weight: 700;">
            {user['first_name']}
        </p>
        <p style="color: #94a3b8; margin-top: 8px;">
            نورت المتجر 💙
        </p>
    </div>

    <div class="card">
        <h3 style="margin-bottom: 16px;">📊 إحصائيات سريعة</h3>
        <div class="stats">
            <div class="stat">
                <div class="num">{products_count['available']}</div>
                <div class="label">منتج متوفر</div>
            </div>
            <div class="stat">
                <div class="num">{user['balance_usd']:.2f}$</div>
                <div class="label">رصيدك</div>
            </div>
            <div class="stat">
                <div class="num">{user['orders_count']}</div>
                <div class="label">طلباتك</div>
            </div>
        </div>
    </div>

    <div class="card">
        <h3 style="margin-bottom: 16px;">🔹 القائمة الرئيسية</h3>
        <div class="grid">
            <a href="/products" class="btn btn-primary">🛍️ المنتجات</a>
            <a href="/balance" class="btn btn-success">💰 رصيدي</a>
            <a href="/charge" class="btn btn-danger">💳 شحن الرصيد</a>
            <a href="/orders" class="btn btn-primary">📋 طلباتي</a>
            <a href="/share" class="btn btn-success">🎁 شارك واربح</a>
            <a href="/help" class="btn btn-danger">❓ مساعدة</a>
        </div>
    </div>
    """
    
    if is_admin(session['user_id']):
        content += """
        <div class="card" style="border-color: #f59e0b;">
            <h3 style="margin-bottom: 16px; color: #f59e0b;">⚙️ لوحة التحكم</h3>
            <a href="/admin" class="btn btn-warning btn-block">🔧 فتح لوحة التحكم</a>
        </div>
        """
    
    return render_page(content, title="الصفحة الرئيسية")


# ========== صفحة المنتجات ==========
@app.route('/products')
@login_required
def products():
    items = get_available_products()
    
    if not items:
        content = """
        <div class="card" style="text-align: center;">
            <p style="font-size: 60px;">📭</p>
            <p style="color: #94a3b8;">لا توجد منتجات متاحة حالياً</p>
            <a href="/" class="btn btn-primary" style="margin-top: 20px;">🔙 رجوع</a>
        </div>
        """
        return render_page(content, title="المنتجات")
    
    products_html = ""
    for p in items:
        if p['sale_type'] == 'manual':
            availability = "♾️ عند طلب"
            avail_color = "#f59e0b"
        else:
            availability = f"✅ متوفر ({p['stock']})"
            avail_color = "#10b981"
        
        products_html += f"""
        <div class="card">
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;">
                <div style="flex: 1;">
                    <h3 style="color: #3b82f6; margin-bottom: 8px;">📦 {p['name']}</h3>
                    <p style="color: #94a3b8; font-size: 14px;">{p['description'][:100]}</p>
                    <p style="color: {avail_color}; font-weight: 700; margin-top: 8px;">{availability}</p>
                </div>
                <div style="text-align: center;">
                    <div style="font-size: 28px; font-weight: 900; color: #10b981;">{p['price_usd']}$</div>
                    <a href="/product/{p['id']}" class="btn btn-primary" style="margin-top: 8px;">🛒 شراء</a>
                </div>
            </div>
        </div>
        """
    
    content = f"""
    <div class="card">
        <h2 style="margin-bottom: 16px;">🛍️ المنتجات المتوفرة</h2>
        <p style="color: #94a3b8;">عدد المنتجات: {len(items)}</p>
    </div>
    {products_html}
    <a href="/" class="btn btn-danger btn-block">🔙 رجوع</a>
    """
    
    return render_page(content, title="المنتجات")


# ========== تفاصيل المنتج ==========
@app.route('/product/<int:pid>')
@login_required
def product_detail(pid):
    p = get_product(pid)
    if not p or p['status'] != 'available' or p['stock'] <= 0:
        flash("❌ المنتج غير متوفر", "error")
        return redirect(url_for('products'))
    
    user = get_user(session['user_id'])
    
    content = f"""
    <div class="card">
        <h2 style="color: #3b82f6; margin-bottom: 16px;">📦 {p['name']}</h2>
        <p style="color: #94a3b8; margin-bottom: 16px;">{p['description']}</p>
        
        <div style="background: #0a0e1a; padding: 16px; border-radius: 12px; margin-bottom: 16px;">
            <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                <span style="color: #94a3b8;">💰 السعر:</span>
                <span style="color: #10b981; font-weight: 700; font-size: 20px;">{p['price_usd']}$</span>
            </div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                <span style="color: #94a3b8;">📊 المتوفر:</span>
                <span style="color: #3b82f6; font-weight: 700;">{p['stock']}</span>
            </div>
            <div style="display: flex; justify-content: space-between;">
                <span style="color: #94a3b8;">💵 رصيدك:</span>
                <span style="color: {'#10b981' if user['balance_usd'] >= p['price_usd'] else '#ef4444'}; font-weight: 700;">{user['balance_usd']:.2f}$</span>
            </div>
        </div>
        
        <form method="POST" action="/buy/{p['id']}">
            <button type="submit" class="btn btn-success btn-block" {'disabled' if user['balance_usd'] < p['price_usd'] else ''}>
                💳 شراء الآن
            </button>
        </form>
        
        <a href="/products" class="btn btn-danger btn-block" style="margin-top: 12px;">🔙 رجوع</a>
    </div>
    """
    
    return render_page(content, title=p['name'])
    
    
# ========== الشراء ==========
@app.route('/buy/<int:pid>', methods=['POST'])
@login_required
def buy(pid):
    p = get_product(pid)
    if not p or p['status'] != 'available' or p['stock'] <= 0:
        flash("❌ المنتج غير متوفر", "error")
        return redirect(url_for('products'))

    uid = session['user_id']
    user = get_user(uid)
    
    if user['balance_usd'] < p['price_usd']:
        flash(f"❌ رصيدك غير كافٍ. رصيدك: {user['balance_usd']:.2f}$", "error")
        return redirect(url_for('product_detail', pid=pid))

    if not deduct_balance_usd(uid, p['price_usd']):
        flash("❌ فشل الخصم", "error")
        return redirect(url_for('product_detail', pid=pid))

    method = "دولار"
    
    if p['sale_type'] == 'manual':
        add_sale(pid, uid, p['price_usd'], 0, method, status="pending")
        notify_admins_manual_sale(p, uid, user)
        flash("⏳ تم إرسال طلبك للمراجعة، سيتم التسليم قريباً", "success")
        return redirect(url_for('orders'))

    new_stock = p['stock'] - 1
    if new_stock <= 0:
        mark_sold(pid, uid)
    else:
        update_stock(pid, new_stock)

    add_sale(pid, uid, p['price_usd'], 0, method, status="completed")

    with db() as conn:
        conn.execute(
            "UPDATE users SET orders_count = orders_count + 1, total_spent = total_spent + ? WHERE user_id=?",
            (p['price_usd'], uid)
        )
        conn.commit()

    notify_buyer_and_channel(p, uid, user)
    
    content = f"""
    <div class="card" style="text-align: center; border-color: #10b981;">
        <p style="font-size: 80px; margin-bottom: 16px;">✅</p>
        <h2 style="color: #10b981; margin-bottom: 16px;">تم الشراء بنجاح!</h2>
        
        <div style="background: #0a0e1a; padding: 20px; border-radius: 12px; margin: 20px 0;">
            <p style="color: #94a3b8; margin-bottom: 8px;">📦 المنتج:</p>
            <p style="font-size: 20px; font-weight: 700; margin-bottom: 16px;">{p['name']}</p>
            
            <p style="color: #94a3b8; margin-bottom: 8px;">🔑 الكود:</p>
            <div style="background: #151b2e; padding: 16px; border-radius: 8px; margin-bottom: 16px;">
                <code style="color: #10b981; font-size: 18px; font-weight: 700; word-break: break-all;">{p['code']}</code>
            </div>
            
            <p style="color: #94a3b8; margin-bottom: 8px;">💰 السعر:</p>
            <p style="font-size: 20px; font-weight: 700; color: #10b981;">{p['price_usd']}$</p>
        </div>
        
        <p style="color: #94a3b8; font-size: 14px;">
            📢 تم إرسال نسخة من الطلب للقناة
        </p>
        
        <div class="grid" style="margin-top: 20px;">
            <a href="/products" class="btn btn-primary">🛍️ منتجات أخرى</a>
            <a href="/" class="btn btn-success">🏠 الرئيسية</a>
        </div>
    </div>
    """
    
    return render_page(content, title="تم الشراء")


def notify_admins_manual_sale(product, buyer_id, buyer):
    msg = (
        f"🤝 <b>طلب بيع يدوي جديد (من الموقع)!</b>\n\n"
        f"📦 <b>المنتج:</b> {product['name']}\n"
        f"👤 <b>المشتري:</b> {buyer.get('first_name') or buyer_id}\n"
        f"🆔 <b>المعرف:</b> {buyer_id}\n"
        f"💰 <b>السعر:</b> {product['price_usd']}$\n\n"
        f"افتح البوت للتأكيد."
    )
    for admin_id in ADMIN_IDS:
        try:
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": admin_id, "text": msg, "parse_mode": "HTML"},
                timeout=5
            )
        except:
            pass


def notify_buyer_and_channel(product, buyer_id, buyer):
    text = (
        f"✅ <b>تم الشراء بنجاح من الموقع!</b>\n\n"
        f"📦 <b>المنتج:</b> {product['name']}\n"
        f"🔑 <b>الكود:</b> <code>{product['code']}</code>\n"
        f"💰 <b>السعر:</b> {product['price_usd']}$\n"
    )
    
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": buyer_id, "text": text, "parse_mode": "HTML"},
            timeout=5
        )
    except:
        pass

    if product.get('file_id'):
        try:
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument",
                json={
                    "chat_id": buyer_id,
                    "document": product['file_id'],
                    "caption": f"📎 ملف المنتج: {product['name']}"
                },
                timeout=5
            )
        except:
            pass


# ========== الرصيد ==========
@app.route('/balance')
@login_required
def balance():
    user = get_user(session['user_id'])
    
    content = f"""
    <div class="card" style="text-align: center; border-color: #10b981;">
        <p style="font-size: 60px;">💰</p>
        <h2 style="color: #10b981;">رصيدك الحالي</h2>
        <p style="font-size: 48px; font-weight: 900; color: #10b981; margin: 20px 0;">
            {user['balance_usd']:.2f}$
        </p>
    </div>
    
    <div class="card">
        <h3 style="margin-bottom: 16px;">📊 إحصائياتك</h3>
        <div class="stats">
            <div class="stat">
                <div class="num">{user['orders_count']}</div>
                <div class="label">عدد الطلبات</div>
            </div>
            <div class="stat">
                <div class="num">{user['total_spent']:.2f}$</div>
                <div class="label">إجمالي المشتريات</div>
            </div>
            <div class="stat">
                <div class="num">{user['balance_stars']}</div>
                <div class="label">نجومك</div>
            </div>
        </div>
    </div>
    
    <div class="grid">
        <a href="/charge" class="btn btn-success">💳 شحن الرصيد</a>
        <a href="/" class="btn btn-primary">🏠 الرئيسية</a>
    </div>
    """
    
    return render_page(content, title="رصيدي")


# ========== الشحن ==========
@app.route('/charge')
@login_required
def charge():
    prices = get_charge_prices()
    rate = int(get_setting('exchange_rate', '50'))
    bot_username = get_setting('bot_username', 'sd_5g_bot')
    
    if not prices:
        content = """
        <div class="card" style="text-align: center;">
            <p style="font-size: 60px;">❌</p>
            <p style="color: #94a3b8;">لا توجد أسعار شحن متاحة</p>
            <a href="/" class="btn btn-primary" style="margin-top: 20px;">🔙 رجوع</a>
        </div>
        """
        return render_page(content, title="شحن الرصيد")
    
    prices_html = ""
    for p in prices:
        prices_html += f"""
        <a href="https://t.me/{bot_username}" target="_blank" class="btn btn-success btn-block" style="margin-bottom: 12px;">
            💵 {p['amount_usd']}$ = ⭐ {p['amount_stars']}
        </a>
        """
    
    content = f"""
    <div class="card" style="text-align: center;">
        <p style="font-size: 60px;">💳</p>
        <h2 style="color: #3b82f6;">شحن الرصيد</h2>
        <p style="color: #94a3b8; margin-top: 12px;">
            💱 سعر الصرف: 1$ = {rate} ⭐
        </p>
    </div>
    
    <div class="card">
        <h3 style="margin-bottom: 16px;">اختر المبلغ:</h3>
        {prices_html}
        
        <div style="background: #0a0e1a; padding: 16px; border-radius: 12px; margin-top: 16px;">
            <p style="color: #f59e0b; font-weight: 700;">💡 ملاحظة:</p>
            <p style="color: #94a3b8; font-size: 14px; margin-top: 8px;">
                سيتم تحويلك إلى البوت لإتمام عملية الدفع بالنجوم.
            </p>
        </div>
    </div>
    
    <a href="/" class="btn btn-danger btn-block">🔙 رجوع</a>
    """
    
    return render_page(content, title="شحن الرصيد")


# ========== الطلبات ==========
@app.route('/orders')
@login_required
def orders():
    items = get_user_sales(session['user_id'])
    
    if not items:
        content = """
        <div class="card" style="text-align: center;">
            <p style="font-size: 60px;">📭</p>
            <p style="color: #94a3b8;">لا توجد طلبات سابقة</p>
            <a href="/products" class="btn btn-primary" style="margin-top: 20px;">🛍️ تسوق الآن</a>
        </div>
        """
        return render_page(content, title="طلباتي")
    
    orders_html = ""
    for s in items:
        if s['status'] == 'completed':
            status = "✅ مكتمل"
            color = "#10b981"
        elif s['status'] == 'pending':
            status = "⏳ قيد المراجعة"
            color = "#f59e0b"
        else:
            status = "❌ مرفوض"
            color = "#ef4444"
        
        orders_html += f"""
        <div class="card">
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
                <div>
                    <p style="font-size: 14px; color: #94a3b8;">🆔 #{s['id']}</p>
                    <p style="font-size: 20px; font-weight: 700; color: #10b981; margin: 4px 0;">
                        {s['amount_usd']}$
                    </p>
                    <p style="font-size: 12px; color: #64748b;">🕒 {s['sold_at']}</p>
                </div>
                <div style="text-align: center;">
                    <span style="color: {color}; font-weight: 700;">{status}</span>
                    <p style="font-size: 12px; color: #64748b; margin-top: 4px;">💳 {s['payment_method']}</p>
                </div>
            </div>
        </div>
        """
    
    content = f"""
    <div class="card">
        <h2>📋 طلباتي</h2>
        <p style="color: #94a3b8;">عدد الطلبات: {len(items)}</p>
    </div>
    {orders_html}
    <a href="/" class="btn btn-primary btn-block">🔙 رجوع</a>
    """
    
    return render_page(content, title="طلباتي")
    
# ========== شارك واربح ==========
@app.route('/share')
@login_required
def share():
    uid = session['user_id']
    if not is_referral_enabled():
        flash("❌ الميزة معطلة حالياً", "error")
        return redirect(url_for('index'))

    stats = get_user_referrals(uid)
    daily = get_daily_referrals(uid)
    daily_limit = int(get_setting('referral_daily_limit', '10'))
    reward = get_referral_reward()
    bot_username = get_setting('bot_username', 'sd_5g_bot')
    recent = get_recent_referrals(uid)
    ref_link = f"https://t.me/{bot_username}?start=ref_{uid}"

    recent_html = ""
    if recent:
        for r in recent:
            recent_html += f"""
            <div style="background: #0a0e1a; padding: 12px; border-radius: 8px; margin-bottom: 8px;">
                <p style="color: #94a3b8; font-size: 12px;">🆔 {r['referred_id']}</p>
                <p style="color: #10b981; font-weight: 700;">💰 {r['amount']:.2f}$</p>
                <p style="color: #64748b; font-size: 11px;">🕒 {r['created_at']}</p>
            </div>
            """
    else:
        recent_html = '<p style="color: #94a3b8; text-align: center;">لا توجد إحالات بعد</p>'

    content = f"""
    <div class="card" style="text-align: center; border-color: #10b981;">
        <p style="font-size: 60px;">🎁</p>
        <h2 style="color: #10b981;">شارك واربح</h2>
        <p style="color: #94a3b8; margin-top: 12px;">
            اكسب <b style="color: #10b981;">{reward:.2f}$</b> عن كل صديق ينضم
        </p>
    </div>

    <div class="card">
        <h3 style="margin-bottom: 16px;">📊 إحصائياتك</h3>
        <div class="stats">
            <div class="stat">
                <div class="num">{stats['count']}</div>
                <div class="label">إحالاتك</div>
            </div>
            <div class="stat">
                <div class="num">{stats['total_earned']:.2f}$</div>
                <div class="label">إجمالي الأرباح</div>
            </div>
            <div class="stat">
                <div class="num">{daily}/{daily_limit}</div>
                <div class="label">إحالات اليوم</div>
            </div>
        </div>
    </div>

    <div class="card">
        <h3 style="margin-bottom: 12px;">🔗 رابطك الخاص</h3>
        <div style="background: #0a0e1a; padding: 16px; border-radius: 12px; margin-bottom: 12px;">
            <code style="color: #3b82f6; font-size: 14px; word-break: break-all;">
                {ref_link}
            </code>
        </div>
        
        <button onclick="copyLink()" class="btn btn-success btn-block">
            📋 نسخ الرابط
        </button>
        
        <a href="https://t.me/share/url?url={ref_link}&text=انضم إلى {get_setting('store_name', 'المتجر')}" 
           target="_blank" 
           class="btn btn-primary btn-block" 
           style="margin-top: 12px;">
            📤 مشاركة
        </a>
    </div>

    <div class="card">
        <h3 style="margin-bottom: 16px;">📋 آخر الإحالات</h3>
        {recent_html}
    </div>

    <a href="/" class="btn btn-danger btn-block">🔙 رجوع</a>

    <script>
        function copyLink() {{
            const link = "{ref_link}";
            navigator.clipboard.writeText(link).then(() => {{
                alert("✅ تم نسخ الرابط بنجاح!");
            }});
        }}
    </script>
    """

    return render_page(content, title="شارك واربح")


# ========== المساعدة ==========
@app.route('/help')
@login_required
def help_page():
    content = f"""
    <div class="card" style="text-align: center;">
        <p style="font-size: 60px;">❓</p>
        <h2 style="color: #3b82f6;">المساعدة</h2>
    </div>

    <div class="card">
        <h3 style="margin-bottom: 16px;">📖 الأوامر المتاحة</h3>
        <div style="background: #0a0e1a; padding: 16px; border-radius: 12px;">
            <p style="margin-bottom: 8px;"><code style="color: #10b981;">/start</code> - القائمة الرئيسية</p>
            <p style="margin-bottom: 8px;"><code style="color: #10b981;">/id</code> - عرض آيديك</p>
            <p><code style="color: #10b981;">/help</code> - المساعدة</p>
        </div>
    </div>

    <div class="card">
        <h3 style="margin-bottom: 16px;">💡 كيف يعمل الموقع؟</h3>
        <ol style="color: #94a3b8; line-height: 2; padding-right: 20px;">
            <li>سجّل الدخول بآيديك</li>
            <li>تصفّح المنتجات</li>
            <li>اشتر بالدولار من رصيدك</li>
            <li>استلم الكود/الملف فوراً</li>
        </ol>
    </div>

    <div class="card">
        <h3 style="margin-bottom: 16px;">📞 تواصل معنا</h3>
        <div class="grid">
            <a href="https://t.me/{DEVELOPER_USERNAME}" target="_blank" class="btn btn-primary">
                👨‍💻 المطور
            </a>
            <a href="https://t.me/E_E_72" target="_blank" class="btn btn-danger">
                👑 الأدمن
            </a>
        </div>
    </div>

    <a href="/" class="btn btn-danger btn-block">🔙 رجوع</a>
    """

    return render_page(content, title="المساعدة")
    
# ========== لوحة تحكم الأدمن ==========
@app.route('/admin')
@admin_required
def admin_dashboard():
    products_count = get_product_count()
    users_count = count_users()
    rate = get_setting('exchange_rate', '50')
    
    with db() as conn:
        sales_count = conn.execute("SELECT COUNT(*) c FROM sales").fetchone()["c"]
        sales_sum = conn.execute("SELECT COALESCE(SUM(amount_usd),0) s FROM sales WHERE status='completed'").fetchone()["s"]
        ref_count = conn.execute("SELECT COUNT(*) c FROM referrals").fetchone()["c"]
    
    content = f"""
    <div class="card" style="border-color: #f59e0b;">
        <h2 style="color: #f59e0b;">⚙️ لوحة التحكم</h2>
        <p style="color: #94a3b8;">مرحباً {get_user(session['user_id'])['first_name']}</p>
    </div>

    <div class="card">
        <h3 style="margin-bottom: 16px;">📊 الإحصائيات السريعة</h3>
        <div class="stats">
            <div class="stat">
                <div class="num">{products_count['available']}</div>
                <div class="label">منتج متوفر</div>
            </div>
            <div class="stat">
                <div class="num">{users_count}</div>
                <div class="label">مستخدم</div>
            </div>
            <div class="stat">
                <div class="num">{sales_count}</div>
                <div class="label">عملية بيع</div>
            </div>
            <div class="stat">
                <div class="num">{sales_sum:.2f}$</div>
                <div class="label">إجمالي المبيعات</div>
            </div>
            <div class="stat">
                <div class="num">{ref_count}</div>
                <div class="label">إحالة</div>
            </div>
            <div class="stat">
                <div class="num">{rate}</div>
                <div class="label">سعر الصرف</div>
            </div>
        </div>
    </div>

    <div class="card">
        <h3 style="margin-bottom: 16px;">🔧 الإجراءات</h3>
        <div class="grid">
            <a href="/admin/products" class="btn btn-primary">📦 المنتجات</a>
            <a href="/admin/users" class="btn btn-success">👥 المستخدمين</a>
            <a href="/admin/sales" class="btn btn-primary">📋 المبيعات</a>
            <a href="/admin/charge_prices" class="btn btn-success">💲 أسعار الشحن</a>
            <a href="/admin/settings" class="btn btn-warning">⚙️ الإعدادات</a>
            <a href="/admin/stats" class="btn btn-danger">📊 إحصائيات كاملة</a>
        </div>
    </div>

    <a href="/" class="btn btn-danger btn-block">🔙 رجوع</a>
    """
    
    return render_page(content, title="لوحة التحكم")


# ========== إدارة المنتجات ==========
@app.route('/admin/products')
@admin_required
def admin_products():
    products = get_all_products()
    
    products_html = ""
    for p in products:
        sale_type = "🤝 يدوي" if p['sale_type'] == 'manual' else "⚡ تلقائي"
        status = "✅ متوفر" if p['status'] == 'available' else "❌ منفذ"
        
        products_html += f"""
        <div class="card">
            <div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 8px;">
                <div style="flex: 1; min-width: 200px;">
                    <p style="font-weight: 700; color: #3b82f6;">🆔 {p['id']} - {p['name']}</p>
                    <p style="color: #94a3b8; font-size: 12px;">{p['description'][:60]}</p>
                    <p style="color: #10b981; font-weight: 700;">💰 {p['price_usd']}$</p>
                    <p style="color: #94a3b8; font-size: 12px;">📦 {p['stock']} | {sale_type} | {status}</p>
                </div>
                <form method="POST" action="/admin/products/delete/{p['id']}" 
                      onsubmit="return confirm('هل أنت متأكد من الحذف؟')">
                    <button type="submit" class="btn btn-danger" style="padding: 10px 14px; font-size: 12px;">
                        🗑️ حذف
                    </button>
                </form>
            </div>
        </div>
        """
    
    content = f"""
    <div class="card">
        <h2>📦 إدارة المنتجات</h2>
    </div>

    <div class="card" style="border-color: #10b981;">
        <h3 style="margin-bottom: 16px;">➕ إضافة منتج جديد</h3>
        <form method="POST" action="/admin/products/add">
            <div class="input-group">
                <label>📦 الاسم</label>
                <input type="text" name="name" class="input" required>
            </div>
            
            <div class="input-group">
                <label>📝 الوصف</label>
                <textarea name="description" class="input" rows="2"></textarea>
            </div>
            
            <div class="grid">
                <div class="input-group">
                    <label>💰 السعر بالدولار</label>
                    <input type="number" step="0.01" name="price_usd" class="input" required>
                </div>
                <div class="input-group">
                    <label>📊 المخزون</label>
                    <input type="number" name="stock" class="input" value="1" required>
                </div>
            </div>
            
            <div class="grid">
                <div class="input-group">
                    <label>🏷️ التصنيف</label>
                    <input type="text" name="category" class="input" value="عام">
                </div>
                <div class="input-group">
                    <label>⚡ نوع البيع</label>
                    <select name="sale_type" class="input">
                        <option value="auto">⚡ تلقائي</option>
                        <option value="manual">🤝 يدوي</option>
                    </select>
                </div>
            </div>
            
            <div class="input-group">
                <label>🔑 الكود</label>
                <input type="text" name="code" class="input">
            </div>
            
            <div class="input-group">
                <label>📎 file_id (اختياري)</label>
                <input type="text" name="file_id" class="input" placeholder="أرسل الملف للبوت أولاً واحصل على file_id">
            </div>
            
            <button type="submit" class="btn btn-success btn-block">
                ➕ إضافة المنتج
            </button>
        </form>
    </div>

    <div class="card">
        <h3 style="margin-bottom: 16px;">📋 المنتجات الحالية ({len(products)})</h3>
    </div>

    {products_html}
    
    <a href="/admin" class="btn btn-danger btn-block">🔙 رجوع</a>
    """
    
    return render_page(content, title="إدارة المنتجات")


@app.route('/admin/products/add', methods=['POST'])
@admin_required
def admin_add_product():
    try:
        add_product(
            name=request.form.get('name', '').strip(),
            description=request.form.get('description', '').strip(),
            price_usd=float(request.form.get('price_usd', 0)),
            category=request.form.get('category', 'عام').strip(),
            code=request.form.get('code', '').strip(),
            stock=int(request.form.get('stock', 1)),
            sale_type=request.form.get('sale_type', 'auto'),
            file_id=request.form.get('file_id') or None
        )
        flash("✅ تمت إضافة المنتج", "success")
    except Exception as e:
        flash(f"❌ خطأ: {e}", "error")
    return redirect(url_for('admin_products'))


@app.route('/admin/products/delete/<int:pid>', methods=['POST'])
@admin_required
def admin_delete_product(pid):
    delete_product(pid)
    flash("✅ تم حذف المنتج", "success")
    return redirect(url_for('admin_products'))


# ========== إدارة المستخدمين ==========
@app.route('/admin/users')
@admin_required
def admin_users():
    with db() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY id DESC LIMIT 200").fetchall()
        users = [dict(r) for r in rows]
    
    users_html = ""
    for u in users:
        users_html += f"""
        <div class="card">
            <p style="font-weight: 700; color: #3b82f6;">🆔 {u['user_id']}</p>
            <p style="color: #94a3b8; font-size: 12px;">
                👤 {u['first_name'] or u['username'] or 'مستخدم'}
            </p>
            <p style="color: #10b981; font-weight: 700;">💰 {u['balance_usd']:.2f}$</p>
            <p style="color: #94a3b8; font-size: 12px;">📦 {u['orders_count']} طلب</p>
        </div>
        """
    
    content = f"""
    <div class="card">
        <h2>👥 إدارة المستخدمين</h2>
        <p style="color: #94a3b8;">العدد: {len(users)}</p>
    </div>

    <div class="card" style="border-color: #10b981;">
        <h3 style="margin-bottom: 16px;">💰 شحن رصيد مستخدم</h3>
        <form method="POST" action="/admin/users/charge">
            <div class="input-group">
                <label>🆔 آيدي المستخدم</label>
                <input type="text" name="user_id" class="input" required>
            </div>
            
            <div class="input-group">
                <label>💵 المبلغ بالدولار</label>
                <input type="number" step="0.01" name="amount" class="input" required>
            </div>
            
            <button type="submit" class="btn btn-success btn-block">
                💰 شحن
            </button>
        </form>
    </div>

    {users_html}
    
    <a href="/admin" class="btn btn-danger btn-block">🔙 رجوع</a>
    """
    
    return render_page(content, title="إدارة المستخدمين")


@app.route('/admin/users/charge', methods=['POST'])
@admin_required
def admin_charge_user():
    uid = request.form.get('user_id', '').strip()
    try:
        amount = float(request.form.get('amount', 0))
    except:
        amount = 0

    if not uid or amount <= 0:
        flash("❌ بيانات غير صحيحة", "error")
        return redirect(url_for('admin_users'))

    if not get_user(uid):
        flash("❌ المستخدم غير موجود", "error")
        return redirect(url_for('admin_users'))

    add_balance_usd(uid, amount)
    flash(f"✅ تم إضافة {amount}$ للمستخدم {uid}", "success")
    return redirect(url_for('admin_users'))
    
# ========== المبيعات ==========
@app.route('/admin/sales')
@admin_required
def admin_sales():
    sales = get_all_sales()
    
    sales_html = ""
    for s in sales:
        if s['status'] == 'completed':
            status = "✅ مكتمل"
            color = "#10b981"
        elif s['status'] == 'pending':
            status = "⏳ قيد المراجعة"
            color = "#f59e0b"
        else:
            status = "❌ مرفوض"
            color = "#ef4444"
        
        sales_html += f"""
        <div class="card">
            <div style="display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
                <div>
                    <p style="font-weight: 700; color: #3b82f6;">🆔 #{s['id']}</p>
                    <p style="color: #94a3b8; font-size: 12px;">👤 {s['buyer_id']}</p>
                    <p style="color: #10b981; font-weight: 700;">💰 {s['amount_usd']}$</p>
                    <p style="color: #64748b; font-size: 11px;">🕒 {s['sold_at']}</p>
                </div>
                <div style="text-align: center;">
                    <span style="color: {color}; font-weight: 700;">{status}</span>
                    <p style="color: #64748b; font-size: 11px;">💳 {s['payment_method']}</p>
                </div>
            </div>
        </div>
        """
    
    if not sales:
        sales_html = '<div class="card" style="text-align: center;"><p style="color: #94a3b8;">لا توجد مبيعات</p></div>'
    
    content = f"""
    <div class="card">
        <h2>📋 المبيعات</h2>
        <p style="color: #94a3b8;">آخر {len(sales)} عملية</p>
    </div>
    {sales_html}
    <a href="/admin" class="btn btn-danger btn-block">🔙 رجوع</a>
    """
    
    return render_page(content, title="المبيعات")


# ========== أسعار الشحن ==========
@app.route('/admin/charge_prices')
@admin_required
def admin_charge_prices():
    prices = get_charge_prices()
    
    prices_html = ""
    for p in prices:
        prices_html += f"""
        <div class="card">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <p style="font-weight: 700; color: #10b981;">💵 {p['amount_usd']}$ = ⭐ {p['amount_stars']}</p>
                    <p style="color: #64748b; font-size: 12px;">🆔 {p['id']}</p>
                </div>
                <form method="POST" action="/admin/charge_prices/delete/{p['id']}" 
                      onsubmit="return confirm('حذف السعر؟')">
                    <button type="submit" class="btn btn-danger" style="padding: 10px 14px; font-size: 12px;">
                        🗑️ حذف
                    </button>
                </form>
            </div>
        </div>
        """
    
    if not prices:
        prices_html = '<div class="card" style="text-align: center;"><p style="color: #94a3b8;">لا توجد أسعار</p></div>'
    
    content = f"""
    <div class="card">
        <h2>💲 أسعار الشحن</h2>
        <p style="color: #94a3b8;">عدد الأسعار: {len(prices)}</p>
    </div>

    <div class="card" style="border-color: #10b981;">
        <h3 style="margin-bottom: 16px;">➕ إضافة سعر جديد</h3>
        <form method="POST" action="/admin/charge_prices/add">
            <div class="grid">
                <div class="input-group">
                    <label>💵 المبلغ بالدولار</label>
                    <input type="number" step="0.01" name="amount_usd" class="input" required>
                </div>
                <div class="input-group">
                    <label>⭐ عدد النجوم</label>
                    <input type="number" name="amount_stars" class="input" required>
                </div>
            </div>
            <button type="submit" class="btn btn-success btn-block">➕ إضافة</button>
        </form>
    </div>

    {prices_html}
    <a href="/admin" class="btn btn-danger btn-block">🔙 رجوع</a>
    """
    
    return render_page(content, title="أسعار الشحن")


@app.route('/admin/charge_prices/add', methods=['POST'])
@admin_required
def admin_add_charge_price():
    try:
        amount_usd = float(request.form.get('amount_usd', 0))
        amount_stars = int(request.form.get('amount_stars', 0))
        if amount_usd > 0 and amount_stars > 0:
            add_charge_price(amount_usd, amount_stars)
            flash("✅ تمت الإضافة", "success")
        else:
            flash("❌ بيانات غير صحيحة", "error")
    except:
        flash("❌ بيانات غير صحيحة", "error")
    return redirect(url_for('admin_charge_prices'))


@app.route('/admin/charge_prices/delete/<int:pid>', methods=['POST'])
@admin_required
def admin_delete_charge_price(pid):
    delete_charge_price(pid)
    flash("✅ تم الحذف", "success")
    return redirect(url_for('admin_charge_prices'))


# ========== الإعدادات ==========
@app.route('/admin/settings', methods=['GET', 'POST'])
@admin_required
def admin_settings():
    if request.method == 'POST':
        for key in ['store_name', 'exchange_rate', 'referral_reward',
                    'referral_daily_limit', 'referral_enabled', 'bot_username']:
            val = request.form.get(key)
            if val is not None:
                set_setting(key, val)
        flash("✅ تم حفظ الإعدادات", "success")
        return redirect(url_for('admin_settings'))

    settings = {
        'store_name': get_setting('store_name', '🛍️ متجر الأرقام'),
        'exchange_rate': get_setting('exchange_rate', '50'),
        'referral_reward': get_setting('referral_reward', '0.05'),
        'referral_daily_limit': get_setting('referral_daily_limit', '10'),
        'referral_enabled': get_setting('referral_enabled', '1'),
        'bot_username': get_setting('bot_username', 'YourBot'),
    }
    
    content = f"""
    <div class="card">
        <h2>⚙️ الإعدادات</h2>
    </div>

    <form method="POST">
        <div class="card">
            <h3 style="margin-bottom: 16px;">🏪 إعدادات المتجر</h3>
            
            <div class="input-group">
                <label>🏪 اسم المتجر</label>
                <input type="text" name="store_name" class="input" value="{settings['store_name']}">
            </div>
            
            <div class="input-group">
                <label>🤖 يوزر البوت (بدون @)</label>
                <input type="text" name="bot_username" class="input" value="{settings['bot_username']}">
            </div>
            
            <div class="input-group">
                <label>💱 سعر الصرف (كم نجمة = 1$)</label>
                <input type="number" name="exchange_rate" class="input" value="{settings['exchange_rate']}">
            </div>
        </div>

        <div class="card">
            <h3 style="margin-bottom: 16px;">🎁 إعدادات الإحالات</h3>
            
            <div class="input-group">
                <label>💰 مكافأة الإحالة (بالدولار)</label>
                <input type="number" step="0.01" name="referral_reward" class="input" value="{settings['referral_reward']}">
            </div>
            
            <div class="input-group">
                <label>📅 الحد اليومي للإحالات</label>
                <input type="number" name="referral_daily_limit" class="input" value="{settings['referral_daily_limit']}">
            </div>
            
            <div class="input-group">
                <label>🔘 حالة الميزة</label>
                <select name="referral_enabled" class="input">
                    <option value="1" {'selected' if settings['referral_enabled'] == '1' else ''}>✅ مفعلة</option>
                    <option value="0" {'selected' if settings['referral_enabled'] == '0' else ''}>❌ معطلة</option>
                </select>
            </div>
        </div>

        <button type="submit" class="btn btn-success btn-block">💾 حفظ الإعدادات</button>
    </form>

    <a href="/admin" class="btn btn-danger btn-block" style="margin-top: 12px;">🔙 رجوع</a>
    """
    
    return render_page(content, title="الإعدادات")


# ========== الإحصائيات الكاملة ==========
@app.route('/admin/stats')
@admin_required
def admin_stats():
    with db() as conn:
        total_sales = conn.execute("SELECT COUNT(*) c, COALESCE(SUM(amount_usd),0) s FROM sales WHERE status='completed'").fetchone()
        total_referrals = conn.execute("SELECT COUNT(*) c, COALESCE(SUM(amount),0) s FROM referrals").fetchone()
        total_stars = conn.execute("SELECT COUNT(*) c, COALESCE(SUM(amount_stars),0) s FROM star_charges").fetchone()
        total_users = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        total_products = conn.execute("SELECT COUNT(*) c FROM products").fetchone()["c"]
        available_products = conn.execute("SELECT COUNT(*) c FROM products WHERE status='available' AND stock>0").fetchone()["c"]
    
    content = f"""
    <div class="card">
        <h2>📊 الإحصائيات الكاملة</h2>
    </div>

    <div class="card">
        <h3 style="margin-bottom: 16px;">💰 المبيعات</h3>
        <div class="stats">
            <div class="stat">
                <div class="num">{total_sales['c']}</div>
                <div class="label">عملية بيع</div>
            </div>
            <div class="stat">
                <div class="num">{total_sales['s']:.2f}$</div>
                <div class="label">إجمالي المبيعات</div>
            </div>
        </div>
    </div>

    <div class="card">
        <h3 style="margin-bottom: 16px;">👥 المستخدمين</h3>
        <div class="stats">
            <div class="stat">
                <div class="num">{total_users}</div>
                <div class="label">مستخدم</div>
            </div>
        </div>
    </div>

    <div class="card">
        <h3 style="margin-bottom: 16px;">📦 المنتجات</h3>
        <div class="stats">
            <div class="stat">
                <div class="num">{available_products}</div>
                <div class="label">متوفر</div>
            </div>
            <div class="stat">
                <div class="num">{total_products}</div>
                <div class="label">إجمالي</div>
            </div>
        </div>
    </div>

    <div class="card">
        <h3 style="margin-bottom: 16px;">🎁 الإحالات</h3>
        <div class="stats">
            <div class="stat">
                <div class="num">{total_referrals['c']}</div>
                <div class="label">إحالة</div>
            </div>
            <div class="stat">
                <div class="num">{total_referrals['s']:.2f}$</div>
                <div class="label">إجمالي المدفوع</div>
            </div>
        </div>
    </div>

    <div class="card">
        <h3 style="margin-bottom: 16px;">⭐ شحن النجوم</h3>
        <div class="stats">
            <div class="stat">
                <div class="num">{total_stars['c']}</div>
                <div class="label">عملية شحن</div>
            </div>
            <div class="stat">
                <div class="num">{total_stars['s']}</div>
                <div class="label">إجمالي النجوم</div>
            </div>
        </div>
    </div>

    <a href="/admin" class="btn btn-danger btn-block">🔙 رجوع</a>
    """
    
    return render_page(content, title="الإحصائيات")


# ========== API ==========
@app.route('/api/me')
def api_me():
    if 'user_id' not in session:
        return jsonify({"ok": False}), 401
    user = get_user(session['user_id'])
    return jsonify({"ok": True, "user": user})
    
# =========================================================
# ========== تشغيل البوت في Thread =========================
# =========================================================

def run_telegram_bot():
    """تشغيل بوت Telegram في Thread منفصل"""
    try:
        import telebot
        from telebot import types
        from telebot.types import BotCommand, ReplyKeyboardMarkup, KeyboardButton
        
        bot = telebot.TeleBot(BOT_TOKEN)
        user_data = {}
        
        # ========== دوال البوت ==========
        def bot_get_setting(key, default=""):
            return get_setting(key, default)
        
        def bot_get_user(user_id):
            return get_user(str(user_id))
        
        def bot_create_user(user_id, username="", first_name=""):
            return create_user(str(user_id), username, first_name)
        
        def bot_get_all_admins():
            return get_all_admins()
        
        def bot_is_admin(user_id):
            return str(user_id) in ADMIN_IDS or str(user_id) in get_all_admins()
        
        # ========== أوامر ==========
        @bot.message_handler(commands=['start', 'menu'])
        def start_cmd(message):
            user_id = str(message.from_user.id)
            is_admin_user = bot_is_admin(user_id)
            
            if not bot_get_user(user_id):
                bot_create_user(user_id, message.from_user.username or "", message.from_user.first_name or "")
            
            store_name = bot_get_setting('store_name', '🛍️ متجر الأرقام')
            user = bot_get_user(user_id)
            
            text = f"""
🌟 <b>أهلاً وسهلاً بك</b> 🌟

<blockquote>✨ <b>{store_name}</b> ✨</blockquote>

👋 مرحباً <b>{message.from_user.first_name}</b>!

💰 <b>رصيدك:</b> <code>{user['balance_usd']:.2f}$</code>
📦 <b>المنتجات:</b> <code>{get_product_count()['available']}</code>

🔹 <b>اختر من القائمة:</b>
"""
            
            reply_markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
            reply_markup.add(
                KeyboardButton("💰 رصيدي"),
                KeyboardButton("📋 طلباتي")
            )
            reply_markup.add(
                KeyboardButton("💳 شحن رصيد"),
                KeyboardButton("❓ مساعدة")
            )
            reply_markup.add(
                KeyboardButton("🔄 تشغيل البوت"),
                KeyboardButton("🌐 الموقع")
            )
            
            bot.reply_to(message, text, parse_mode="HTML", reply_markup=reply_markup)
            
            # القائمة العلوية
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("🛍️ المنتجات", callback_data="show_products", style="primary"),
                types.InlineKeyboardButton("💰 رصيدي", callback_data="my_balance", style="success"),
            )
            markup.add(
                types.InlineKeyboardButton("💳 شحن الرصيد", callback_data="charge_balance", style="danger"),
                types.InlineKeyboardButton("📋 طلباتي", callback_data="my_orders", style="primary"),
            )
            markup.add(
                types.InlineKeyboardButton("🌐 فتح الموقع", url=WEBAPP_URL, style="success"),
            )
            
            if is_admin_user:
                markup.add(types.InlineKeyboardButton("⚙️ لوحة التحكم", callback_data="admin_panel", style="danger"))
            
            bot.send_message(
                message.chat.id,
                "<u><b>🔹 الـــقـــائـــمـــة الـــرئـــيـــســـيـــة 🔹</b></u>",
                parse_mode="HTML",
                reply_markup=markup
            )
        
        @bot.message_handler(commands=['id'])
        def send_id(message):
            bot.reply_to(
                message,
                f"🆔 <b>معلوماتك:</b>\n\n"
                f"👤 <b>الاسم:</b> {message.from_user.first_name}\n"
                f"🆔 <b>الآيدي:</b> <code>{message.from_user.id}</code>\n"
                f"🌐 <b>يوزر:</b> @{message.from_user.username or 'لا يوجد'}",
                parse_mode="HTML"
            )
        
        @bot.message_handler(commands=['help'])
        def send_help(message):
            bot.reply_to(
                message,
                f"❓ <b>المساعدة</b>\n\n"
                f"🔹 /start - القائمة الرئيسية\n"
                f"🔹 /id - عرض آيديك\n"
                f"🔹 /help - المساعدة\n\n"
                f"🌐 <b>الموقع:</b> {WEBAPP_URL}\n"
                f"👨‍💻 <b>المطور:</b> @{DEVELOPER_USERNAME}",
                parse_mode="HTML"
            )
        
        # ========== المعالجات ==========
        @bot.message_handler(func=lambda m: m.text == "💰 رصيدي")
        def btn_balance(message):
            user = bot_get_user(str(message.from_user.id))
            if not user:
                bot.reply_to(message, "❌ حدث خطأ")
                return
            bot.reply_to(
                message,
                f"💰 <b>رصيدك:</b> <code>{user['balance_usd']:.2f}$</code>\n"
                f"📦 <b>طلباتك:</b> {user['orders_count']}",
                parse_mode="HTML"
            )
        
        @bot.message_handler(func=lambda m: m.text == "📋 طلباتي")
        def btn_orders(message):
            sales = get_user_sales(str(message.from_user.id))
            if not sales:
                bot.reply_to(message, "📭 لا توجد طلبات")
                return
            text = "📋 <b>طلباتك:</b>\n\n"
            for s in sales[:5]:
                status = "✅" if s['status'] == 'completed' else "⏳" if s['status'] == 'pending' else "❌"
                text += f"{status} #{s['id']} - {s['amount_usd']}$\n"
            bot.reply_to(message, text, parse_mode="HTML")
        
        @bot.message_handler(func=lambda m: m.text == "❓ مساعدة")
        def btn_help(message):
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton("🌐 فتح الموقع", url=WEBAPP_URL, style="success"),
                types.InlineKeyboardButton("👨‍💻 المطور", url=f"https://t.me/{DEVELOPER_USERNAME}", style="primary"),
                types.InlineKeyboardButton("👑 الأدمن", url="https://t.me/E_E_72", style="danger")
            )
            bot.reply_to(
                message,
                f"❓ <b>المساعدة</b>\n\n"
                f"🌐 <b>الموقع:</b> {WEBAPP_URL}\n\n"
                f"👇 <b>للتواصل:</b>",
                parse_mode="HTML",
                reply_markup=markup
            )
        
        @bot.message_handler(func=lambda m: m.text == "🔄 تشغيل البوت")
        def btn_restart(message):
            start_cmd(message)
        
        @bot.message_handler(func=lambda m: m.text == "🌐 الموقع")
        def btn_website(message):
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton("🌐 فتح الموقع", url=WEBAPP_URL, style="success")
            )
            bot.reply_to(
                message,
                f"🌐 <b>الموقع الرسمي</b>\n\n"
                f"اضغط الزر لفتح الموقع:",
                parse_mode="HTML",
                reply_markup=markup
            )
        
        # ========== تسجيل الأوامر ==========
        try:
            bot.set_my_commands([
                BotCommand("start", "🏠 بدء البوت"),
                BotCommand("id", "🆔 عرض آيديك"),
                BotCommand("help", "❓ المساعدة"),
            ])
            print("✅ تم تسجيل الأوامر")
        except Exception as e:
            print(f"⚠️ خطأ في تسجيل الأوامر: {e}")
        
        # ========== تشغيل ==========
        print("🤖 بدء تشغيل بوت Telegram...")
        bot.infinity_polling(timeout=10, long_polling_timeout=5)
        
    except Exception as e:
        print(f"❌ خطأ في البوت: {e}")
        import traceback
        traceback.print_exc()


# ========== التشغيل الرئيسي ==========
if __name__ == "__main__":
    # ✅ تأكد من قاعدة البيانات قبل أي شي
    init_db()
    print(f"✅ قاعدة البيانات جاهزة: {DB_PATH}")
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
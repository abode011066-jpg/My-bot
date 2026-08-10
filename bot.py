import logging
import sqlite3
import re
import random
import os
import threading
import json
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    WebAppInfo,
)
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ConversationHandler,
)

# ------------------ خادم فحوصات الصحة وخدمات العجلة API ------------------
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_path = urllib.parse.urlparse(self.path)
        path = parsed_path.path
        
        # API لجلب بيانات العجلة للمستخدم
        if path.startswith("/api/user/"):
            try:
                user_id = int(path.split("/")[-1])
                conn = sqlite3.connect("wayxbet_vip_pro.db")
                c = conn.cursor()
                c.execute("SELECT spins, balance FROM users WHERE user_id = ?", (user_id,))
                res = c.fetchone()
                conn.close()
                if res:
                    response = json.dumps({"success": True, "spins": res[0], "balance": res[1]}).encode('utf-8')
                else:
                    response = json.dumps({"success": False, "spins": 0, "balance": 0}).encode('utf-8')
            except Exception as e:
                response = json.dumps({"success": False, "error": str(e)}).encode('utf-8')
            
            self.send_response(200)
            self.send_header("Content-type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(response)
            return

        if os.path.exists("index.html"):
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            with open("index.html", "rb") as f:
                self.wfile.write(f.read())
        else:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot Service is Running Alive")

    def do_POST(self):
        # API لدوران العجلة وحساب الأرباح
        if self.path == "/api/spin":
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data.decode('utf-8'))
                user_id = int(data.get("user_id"))

                conn = sqlite3.connect("wayxbet_vip_pro.db")
                c = conn.cursor()
                c.execute("SELECT spins, balance FROM users WHERE user_id = ?", (user_id,))
                res = c.fetchone()

                if not res or res[0] <= 0:
                    conn.close()
                    response = json.dumps({"success": False, "message": "لا توجد لديك لفات متاحة!"}).encode('utf-8')
                else:
                    prizes = [
                        {"label": "0", "sub": "حظ أوفر", "val": 0},
                        {"label": "500", "sub": "ليرة", "val": 5},
                        {"label": "1000", "sub": "ليرة", "val": 10},
                        {"label": "2500", "sub": "ليرة", "val": 25},
                        {"label": "5000", "sub": "ليرة", "val": 50},
                        {"label": "10000", "sub": "ليرة", "val": 100},
                        {"label": "50000", "sub": "ليرة", "val": 500},
                        {"label": "100000", "sub": "ليرة", "val": 1000}
                    ]
                    
                    prob_keys = ["wheel_prob_0", "wheel_prob_5", "wheel_prob_10", "wheel_prob_25", "wheel_prob_50", "wheel_prob_100", "wheel_prob_1000", "wheel_prob_10000"]
                    weights = []
                    for k in prob_keys[:8]:
                        c.execute("SELECT value FROM settings WHERE key = ?", (k,))
                        r = c.fetchone()
                        weights.append(float(r[0]) if r and r[0] else 1.0)

                    chosen_idx = random.choices(range(len(prizes)), weights=weights, k=1)[0]
                    win_prize = prizes[chosen_idx]

                    c.execute("UPDATE users SET spins = spins - 1, balance = balance + ? WHERE user_id = ?", (win_prize["val"], user_id))
                    conn.commit()

                    c.execute("SELECT spins, balance FROM users WHERE user_id = ?", (user_id,))
                    updated_res = c.fetchone()
                    conn.close()

                    response = json.dumps({
                        "success": True,
                        "prize_index": chosen_idx,
                        "prize": win_prize,
                        "new_balance": updated_res[1],
                        "remaining_spins": updated_res[0]
                    }).encode('utf-8')

            except Exception as e:
                response = json.dumps({"success": False, "message": str(e)}).encode('utf-8')

            self.send_response(200)
            self.send_header("Content-type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(response)
            return

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):
        return

def run_health_check_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=run_health_check_server, daemon=True).start()

# ----------------- الإعدادات العامة -----------------
TOKEN = "8812713556:AAGv3bCjQnGgwSGxiqoX8ipuVTvlNTTiLdk"
ADMIN_IDS = [8984953082]
ADMIN_ID = ADMIN_IDS[0]
CHANNEL_BOT = "@cashinsher"
CHANNEL_PROG = "@lerafree"
SITE_URL = "https://wayxbet10.com"
FB_PAGE_URL = "https://www.facebook.com/share/1EEroBvKf1/"
SERVER_WHEEL_URL = "https://my-bot-a8sy.onrender.com"

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ----------------- حالات المحادثة (Conversation States) -----------------
(
    GET_CONTACT, ACC_NAME, ACC_PASS, 
    DEPOSIT_METHOD, DEPOSIT_TX, DEPOSIT_AMT, 
    WITHDRAW_METHOD, WITHDRAW_ACC, WITHDRAW_AMT, WITHDRAW_SPEED, WITHDRAW_CONFIRM,
    SITE_DEP_AMT, SITE_WIT_AMT, 
    GIFT_INPUT, SUPPORT_INPUT, 
    ADMIN_NAME_INPUT, ADMIN_BROADCAST_MSG, ADMIN_PRIV_ID, ADMIN_PRIV_MSG,
    ADMIN_GIFT_CODE, ADMIN_GIFT_AMT, ADMIN_NEW_ADMIN_ID, 
    ADMIN_BAL_ID, ADMIN_BAL_AMT, ADMIN_BAL_TYPE,
    ADMIN_BAN_ID, ADMIN_UNBAN_ID, ADMIN_VIEW_USER_ID, ADMIN_SETTING_VAL,
    ADMIN_WHEEL_PROB_VAL, ADMIN_TICKET_REPLY,
    ADMIN_SPINS_ID, ADMIN_SPINS_COUNT
) = range(33)

# ----------------- قاعدة البيانات الشاملة -----------------
def init_db():
    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        full_name TEXT,
        phone TEXT,
        balance REAL DEFAULT 0,
        spins INTEGER DEFAULT 0,
        wayxbet_account TEXT,
        wayxbet_pass TEXT,
        referred_by INTEGER,
        active_refs INTEGER DEFAULT 0,
        active_ops INTEGER DEFAULT 0,
        is_sub INTEGER DEFAULT 0,
        banned INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        type TEXT,
        method TEXT,
        amount REAL,
        tx_id TEXT,
        account_num TEXT,
        speed TEXT,
        fee REAL DEFAULT 0,
        net_amount REAL DEFAULT 0,
        info TEXT,
        status TEXT DEFAULT 'pending',
        admin_name TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS gift_codes (
        code TEXT PRIMARY KEY,
        amount REAL,
        used_count INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS gift_uses (
        code TEXT,
        user_id INTEGER,
        used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (code, user_id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS support_tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        message TEXT,
        photo_id TEXT,
        status TEXT DEFAULT 'open',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS admins (
        admin_id INTEGER PRIMARY KEY,
        admin_name TEXT
    )""")
    
    defaults = {
        "syriatel_num": "0998682581",
        "sham_num": "d96338dabdb4da50e049526fa93b3353",
        "welcome_bonus": "1000",
        "welcome_bonus_active": "1",
        "deposit_bonus": "0",
        "deposit_bonus_active": "0",
        "ref_spin_active": "1",
        "currency_ratio": "100",
        "min_withdraw": "10000",
        "min_deposit": "5000",
        "min_site_withdraw": "10000",
        "min_site_deposit": "5000",
        "maintenance_mode": "0",
        "current_competition": "🏆 مسابقة الأسبوع: أكثر 3 أعضاء يحققون إحالات نشطة يحصلون على كود هدية !",
        "wheel_prob_0": "40.0",
        "wheel_prob_5": "25.0",
        "wheel_prob_10": "15.0",
        "wheel_prob_15": "10.0",
        "wheel_prob_25": "5.0",
        "wheel_prob_50": "3.0",
        "wheel_prob_100": "1.5",
        "wheel_prob_1000": "0.4",
        "wheel_prob_10000": "0.1"
    }
    for k, v in defaults.items():
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
        
    for adm in ADMIN_IDS:
        c.execute("INSERT OR IGNORE INTO admins (admin_id, admin_name) VALUES (?, ?)", (adm, "المدير العام"))
    conn.commit()
    conn.close()

init_db()

# ----------------- دوال المساعدة -----------------
def get_setting(key):
    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = ?", (key,))
    res = c.fetchone()
    conn.close()
    return res[0] if res else ""

def set_setting(key, value):
    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def is_admin(user_id):
    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("SELECT admin_id FROM admins WHERE admin_id = ?", (user_id,))
    res = c.fetchone()
    conn.close()
    return res is not None

def is_banned(user_id):
    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("SELECT banned FROM users WHERE user_id = ?", (user_id,))
    res = c.fetchone()
    conn.close()
    return res and res[0] == 1

def format_currency(amount):
    ratio = float(get_setting("currency_ratio") or 100)
    old_lira = float(amount)
    new_lira = old_lira / ratio
    return f"{old_lira:,.0f} ليرة قديمة ({new_lira:,.2f} ليرة جديدة)"

async def check_subscription(user_id, context):
    try:
        for ch in [CHANNEL_BOT, CHANNEL_PROG]:
            member = await context.bot.get_chat_member(chat_id=ch, user_id=user_id)
            if member.status in ['left', 'kicked']:
                return False
        return True
    except:
        return False

# ----------------- الواجهات والأزرار -----------------
def main_menu_keyboard(user_id, wayx_account):
    acc_text = f"حسابك: {wayx_account}" if wayx_account else "WayxBet (إنشاء حساب)"
    kb = [
        [InlineKeyboardButton(f"🎮 {acc_text}", callback_data="wayx_acc_menu")],
        [InlineKeyboardButton("💵 سحب رصيد", callback_data="withdraw_menu"), 
         InlineKeyboardButton("💳 شحن رصيد", callback_data="deposit_menu")],
        [InlineKeyboardButton("🔄 شحن من البوت للموقع", callback_data="site_dep_menu"), 
         InlineKeyboardButton("🔄 سحب من الموقع للبوت", callback_data="site_wit_menu")],
        [InlineKeyboardButton("👥 إحالاتي", callback_data="refs_menu"), 
         InlineKeyboardButton("🎡 عجلة الحظ", web_app=WebAppInfo(url=SERVER_WHEEL_URL))],
        [InlineKeyboardButton("🎁 كود هدية", callback_data="gift_menu"), 
         InlineKeyboardButton("🏆 المسابقات الحالية", callback_data="comps_menu")],
        [InlineKeyboardButton("🌐 صفحتنا على الفيسبوك", url=FB_PAGE_URL)],
        [InlineKeyboardButton("👨‍💻 قناة المبرمج", url=f"https://t.me/{CHANNEL_PROG[1:]}"), 
         InlineKeyboardButton("🎧 تواصل مع الدعم", callback_data="support_menu")]
    ]
    if is_admin(user_id):
        kb.append([InlineKeyboardButton("🛠 لوحة الإدارة الشاملة", callback_data="admin_panel")])
    return InlineKeyboardMarkup(kb)

# ----------------- نظام الدخول والتحقق -----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ عذراً، حسابك محظور من استخدام البوت.")
        return ConversationHandler.END

    if get_setting("maintenance_mode") == "1" and not is_admin(user.id):
        await update.message.reply_text("🛠 **البوت حالياً في وضع الصيانة.**\nيرجى الانتظار لحين الانتهاء من الصيانة وتحديث الخدمات.")
        return ConversationHandler.END

    args = context.args
    ref_id = int(args[0]) if args and args[0].isdigit() and int(args[0]) != user.id else None

    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("SELECT is_sub, phone FROM users WHERE user_id = ?", (user.id,))
    db_user = c.fetchone()

    if not db_user:
        c.execute("INSERT OR IGNORE INTO users (user_id, username, full_name, referred_by) VALUES (?, ?, ?, ?)",
                  (user.id, user.username, user.full_name, ref_id))
        conn.commit()
        
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"👤 **دخول مستخدم جديد للبوت:**\nالاسم: {user.full_name}\nالايدي: `{user.id}`",
                parse_mode="Markdown"
            )
        except:
            pass

    conn.close()

    if not await check_subscription(user.id, context):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("قناة البوت 📢", url=f"https://t.me/{cashinsher[1:]}")],
            [InlineKeyboardButton("قناة المبرمج 👨‍💻", url=f"https://t.me/{lerafree[1:]}")],
            [InlineKeyboardButton("✅ تحقق من الاشتراك", callback_data="verify_subscription")]
        ])
        await update.message.reply_text(
            f"❌ عذراً عزيزي، يجب عليك الاشتراك في قنوات البوت الإجبارية أولاً:\n1️⃣ {CHANNEL_BOT}\n2️⃣ {CHANNEL_PROG}\n\nبعد الاشتراك، اضغط على زر التحقق أدناه:",
            reply_markup=kb
        )
        return ConversationHandler.END

    return await show_home_screen(update.message, user.id, context)

async def verify_subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    user = query.from_user

    if not await check_subscription(user_id, context):
        await query.answer("❌ لم تقم بالاشتراك في كافة القنوات المطلوبة بعد!", show_alert=True)
        return

    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("SELECT is_sub, referred_by, phone FROM users WHERE user_id = ?", (user_id,))
    db_user = c.fetchone()

    if db_user and db_user[0] == 0:
        c.execute("UPDATE users SET is_sub = 1 WHERE user_id = ?", (user_id,))
        conn.commit()

    conn.close()
    await query.message.delete()

    if db_user and not db_user[2]:
        kb = ReplyKeyboardMarkup([[KeyboardButton("📱 مشاركة رقم الهاتف السوري", request_contact=True)]], resize_keyboard=True, one_time_keyboard=True)
        await query.message.reply_text("✅ تم التحقق من الاشتراك بنجاح!\n📱 يرجى مشاركة رقم هاتفك السوري لتفعيل حسابك واستلام البونص:", reply_markup=kb)
        return GET_CONTACT

    await show_home_screen(query.message, user_id, context)

async def contact_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not update.message.contact or update.message.contact.user_id != user.id:
        await update.message.reply_text("⚠️ يرجى استخدام الزر المخصص لمشاركة رقم هاتفك حصراً!")
        return GET_CONTACT

    phone = update.message.contact.phone_number.strip()
    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    
    # التحقق من أن المستخدم لم يشارك رقمه مسبقاً، لجلب referred_by وأمان احتساب الإحالة بعد مشاركة الرقم
    c.execute("SELECT phone, referred_by FROM users WHERE user_id = ?", (user.id,))
    row = c.fetchone()
    old_phone = row[0] if row else None
    ref_id = row[1] if row else None

    bonus_active = get_setting("welcome_bonus_active") == "1"
    welcome_bonus = float(get_setting("welcome_bonus") or 0) if bonus_active else 0
    
    c.execute("UPDATE users SET phone = ?, balance = balance + ? WHERE user_id = ?", (phone, welcome_bonus, user.id))
    
    # احتساب الإحالة الآمنة بعد مشاركة رقم الهاتف السوري وفحص تفعيل نظام الإحالة والمحيل
    if not old_phone and ref_id and get_setting("ref_spin_active") == "1":
        c.execute("SELECT user_id, full_name FROM users WHERE user_id = ?", (ref_id,))
        ref_user_row = c.fetchone()
        if ref_user_row:
            c.execute("UPDATE users SET spins = spins + 1, active_refs = active_refs + 1 WHERE user_id = ?", (ref_id,))
            try:
                c.execute("SELECT active_refs FROM users WHERE user_id = ?", (ref_id,))
                current_refs = c.fetchone()[0]
                # إشعار للمُحيل
                await context.bot.send_message(
                    chat_id=ref_id,
                    text=f"🔔 **إحالة ناجحة جديدة!**\n"
                         f"👤 العضو الجديد: {user.full_name}\n"
                         f"📱 تم مشاركة وتأكيد رقم الهاتف السوري بنجاح.\n"
                         f"🎁 تم منحك لفة عجلة مجانية!\n"
                         f"📊 إجمالي إحالاتك النشطة: `{current_refs}`",
                    parse_mode="Markdown"
                )
                # إشعار لوحة الإدارة (من أحال من)
                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=f"👥 **إشعار إحالة ناجحة ومؤكدة برقم الهاتف:**\n"
                         f"▪️ المُحيل (ID): `{ref_id}`\n"
                         f"▪️ العضو المحال (ID): `{user.id}` ({user.full_name})\n"
                         f"▪️ رقم الهاتف: `{phone}`",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Error in ref notification: {e}")

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ تم تأكيد رقم هاتفك بنجاح!\n🎁 تم إضافة بونص ترحيبي بقيمة: {format_currency(welcome_bonus)}",
        reply_markup=ReplyKeyboardRemove()
    )
    return await show_home_screen(update.message, user.id, context)

async def show_home_screen(message_obj, user_id, context):
    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("SELECT balance, wayxbet_account, full_name FROM users WHERE user_id = ?", (user_id,))
    res = c.fetchone()
    conn.close()

    if not res:
        return

    balance, wayx_acc, full_name = res[0], res[1], res[2]
    text = (
        f"أهلاً وسهلاً بك {full_name} في بوت\n"
        f"**ROZ WAYXBET** 🌹🚀\n\n"
        f"💰 **رصيدك:** {format_currency(balance)}\n"
        f"🆔 **ايدي حسابك:** `{user_id}`\n"
        f"🌐 **رابط الموقع:** {SITE_URL}"
    )

    await message_obj.reply_text(text, reply_markup=main_menu_keyboard(user_id, wayx_acc), parse_mode="Markdown")
    return ConversationHandler.END

async def back_home_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.delete()
    await show_home_screen(query.message, query.from_user.id, context)

# ----------------- 1. قسم حساب WayxBet (تخزين الحساب وكلمة المرور) -----------------
async def wayxbet_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("SELECT wayxbet_account, wayxbet_pass FROM users WHERE user_id = ?", (user.id,))
    res = c.fetchone()
    conn.close()

    if res and res[0]:
        acc_user = res[0]
        acc_pass = res[1] if res[1] else "غير مسجل"
        await query.edit_message_text(
            f"✅ **حسابك المسجل في الموقع:**\n\n"
            f"👤 **اسم الحساب:** `{acc_user}`\n"
            f"🔑 **كلمة المرور:** `{acc_pass}`\n\n"
            f"(اضغط على النص لنسخه)",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]])
        )
        return ConversationHandler.END

    await query.edit_message_text(
        "📌 **شروط إنشاء الحساب:**\n"
        "- أن يبدأ اسم الحساب بحرف كبير (Capital).\n"
        "- أن ينتهي بـ `@123`.\n"
        "مثال: `Roz133@`\n\n"
        "أدخل اسم المستخدم المطلوب:",
        parse_mode="Markdown"
    )
    return ACC_NAME

async def receive_acc_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    context.user_data['req_acc_name'] = name
    await update.message.reply_text("🔑 ممتاز. الآن أدخل كلمة المرور الخاصة بالحساب:")
    return ACC_PASS

async def receive_acc_pass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    password = update.message.text.strip()
    acc_name = context.user_data.get('req_acc_name')

    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("SELECT phone FROM users WHERE user_id = ?", (user.id,))
    row = c.fetchone()
    phone = row[0] if row else "غير متوفر"

    c.execute("INSERT INTO requests (user_id, type, amount, info) VALUES (?, ?, ?, ?)",
              (user.id, 'account', 0, f"يوزر: {acc_name} | باسورد: {password} | هاتف: {phone}"))
    req_id = c.lastrowid
    conn.commit()
    conn.close()

    Kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ موافقة", callback_data=f"adm_app_acc_{req_id}_{user.id}_{acc_name}"),
         InlineKeyboardButton("❌ رفض", callback_data=f"adm_rej_acc_{req_id}_{user.id}")]
    ])
    
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📥 **طلب إنشاء حساب جديد (#{req_id})**\n\n"
             f"👤 المستخدم: {user.full_name}\n"
             f"🆔 الايدي: `{user.id}`\n"
             f"📱 الهاتف: `{phone}`\n"
             f"🏷 اسم الحساب: `{acc_name}`\n"
             f"🔑 كلمة المرور: `{password}`",
        parse_mode="Markdown",
        reply_markup=Kb
    )

    await update.message.reply_text("⏳ تم وصول طلبك للإدارة، انتظر قليلاً ليتم مراجعته وتفعيله.")
    return ConversationHandler.END

# ----------------- 2. نظام السحب -----------------
async def withdraw_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("SELECT wayxbet_account FROM users WHERE user_id = ?", (query.from_user.id,))
    res = c.fetchone()
    conn.close()

    if not res or not res[0]:
        await query.edit_message_text(
            "❌ يجب عليك إنشاء حساب WayxBet وتفعيله أولاً لتتمكن من السحب!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]])
        )
        return ConversationHandler.END

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("سيريتل كاش", callback_data="wit_meth_syriatel"),
         InlineKeyboardButton("شام كاش", callback_data="wit_meth_sham")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]
    ])
    await query.edit_message_text("💳 اختر طريقة السحب:", reply_markup=kb)
    return WITHDRAW_METHOD

async def withdraw_method_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    method = "سيريتل كاش" if "syriatel" in query.data else "شام كاش"
    context.user_data['wit_method'] = method

    await query.edit_message_text(f"📌 أدخل رقم الحساب/المحفظة ({method}) المراد السحب إليها:")
    return WITHDRAW_ACC

async def withdraw_acc_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['wit_acc'] = update.message.text.strip()
    min_w = float(get_setting("min_withdraw") or 10000)
    await update.message.reply_text(f"💵 أدخل المبلغ المراد سحبه (الحد الأدنى {format_currency(min_w)}):")
    return WITHDRAW_AMT

async def withdraw_amt_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ يرجى إدخال رقم صحيح:")
        return WITHDRAW_AMT

    min_w = float(get_setting("min_withdraw") or 10000)
    if amount < min_w:
        await update.message.reply_text(f"❌ المبلغ أقل من الحد الأدنى للسحب ({format_currency(min_w)}). أعد الإدخال:")
        return WITHDRAW_AMT

    context.user_data['wit_amt'] = amount
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ طلب سريع (عمولة 5%)", callback_data="wit_speed_fast")],
        [InlineKeyboardButton("🐢 طلب بطيء (عمولة 0%)", callback_data="wit_speed_slow")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="back_home")]
    ])
    await update.message.reply_text("⚡ اختر نوع الطلب:", reply_markup=kb)
    return WITHDRAW_SPEED

async def withdraw_speed_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    speed_type = query.data.split("_")[2]
    fee_pct = 5.0 if speed_type == "fast" else 0.0
    amount = context.user_data['wit_amt']
    fee = amount * (fee_pct / 100)
    net_amount = amount - fee

    context.user_data['wit_fee'] = fee
    context.user_data['wit_net'] = net_amount
    context.user_data['wit_speed_str'] = "سريع (5%)" if speed_type == "fast" else "بطيء (0%)"

    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("SELECT wayxbet_account, balance FROM users WHERE user_id = ?", (user.id,))
    res = c.fetchone()
    conn.close()

    wayx_acc, balance = res[0] if res else ("", 0)

    if balance < amount:
        await query.edit_message_text("❌ رصيدك غير كافي لإتمام هذا السحب!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]]))
        return ConversationHandler.END

    summary = (
        f"📋 **تفاصيل طلب السحب:**\n"
        f"🏷 حساب الموقع: `{wayx_acc}`\n"
        f"💳 الطريقة: {context.user_data['wit_method']}\n"
        f"🔢 رقم المحفظة: `{context.user_data['wit_acc']}`\n"
        f"💰 المبلغ المطلوب: {format_currency(amount)}\n"
        f"⚡ نوع الطلب: {context.user_data['wit_speed_str']}\n"
        f"📉 العمولة: {format_currency(fee)}\n"
        f"💵 الصافي المستلم: {format_currency(net_amount)}\n\n"
        f"هل تريد تأكيد الطلب؟"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تأكيد السحب", callback_data="wit_confirm"),
         InlineKeyboardButton("❌ إلغاء", callback_data="back_home")]
    ])
    await query.edit_message_text(summary, parse_mode="Markdown", reply_markup=kb)
    return WITHDRAW_CONFIRM

async def withdraw_confirmed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    amount = context.user_data['wit_amt']
    net_amount = context.user_data['wit_net']
    fee = context.user_data['wit_fee']
    method = context.user_data['wit_method']
    acc_num = context.user_data['wit_acc']
    speed = context.user_data['wit_speed_str']

    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("SELECT wayxbet_account, balance FROM users WHERE user_id = ?", (user.id,))
    res = c.fetchone()
    wayx_acc, balance = res[0], res[1]

    if balance < amount:
        await query.edit_message_text("❌ رصيدك غير كافي!")
        conn.close()
        return ConversationHandler.END

    c.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user.id))
    c.execute("""INSERT INTO requests (user_id, type, method, amount, account_num, speed, fee, net_amount, info)
                 VALUES (?, 'withdraw', ?, ?, ?, ?, ?, ?, ?)""",
              (user.id, method, amount, acc_num, speed, fee, net_amount, f"حساب: {wayx_acc}"))
    req_id = c.lastrowid
    conn.commit()
    conn.close()

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ موافقة", callback_data=f"adm_app_wit_{req_id}_{user.id}_{amount}"),
         InlineKeyboardButton("❌ رفض", callback_data=f"adm_rej_wit_{req_id}_{user.id}_{amount}")]
    ])

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📤 **طلب سحب رصيد جديدة (#{req_id})**\n\n"
             f"👤 العضو: {user.full_name}\n"
             f"🆔 الايدي: `{user.id}`\n"
             f"🏷 حساب الموقع: `{wayx_acc}`\n"
             f"💳 الطريقة: {method}\n"
             f"🔢 الرقم: `{acc_num}`\n"
             f"💰 المبلغ: {format_currency(amount)}\n"
             f"⚡ نوع الطلب: {speed}\n"
             f"💵 المستلم الصافي: {format_currency(net_amount)}",
        parse_mode="Markdown",
        reply_markup=kb
    )

    await query.edit_message_text("⏳ تم إرسال طلب السحب للادارة بنجاح، انتظر قيد المراجعة.")
    return ConversationHandler.END

# ----------------- 3. نظام الشحن -----------------
async def deposit_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("SELECT wayxbet_account FROM users WHERE user_id = ?", (query.from_user.id,))
    res = c.fetchone()
    conn.close()

    if not res or not res[0]:
        await query.edit_message_text(
            "❌ يجب عليك إنشاء حساب WayxBet وتفعيله أولاً لتتمكن من الشحن!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]])
        )
        return ConversationHandler.END

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("سيريتل كاش", callback_data="dep_meth_syriatel"),
         InlineKeyboardButton("شام كاش", callback_data="dep_meth_sham")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]
    ])
    await query.edit_message_text("💳 اختر طريقة الشحن:", reply_markup=kb)
    return DEPOSIT_METHOD

async def deposit_method_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if "syriatel" in query.data:
        method = "سيريتل كاش"
        acc_info = get_setting("syriatel_num")
    else:
        method = "شام كاش"
        acc_info = get_setting("sham_num")

    context.user_data['dep_method'] = method
    await query.edit_message_text(
        f"📥 **شحن عبر {method}:**\n\n"
        f"يرجى التحويل إلى الحساب التالي:\n`{acc_info}`\n\n"
        f"بعد التحويل، أرسل **رقم العملية (رقم الإشعار)** هنا:",
        parse_mode="Markdown"
    )
    return DEPOSIT_TX

async def deposit_tx_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['dep_tx'] = update.message.text.strip()
    min_d = float(get_setting("min_deposit") or 5000)
    await update.message.reply_text(f"💰 أدخل المبلغ الذي قمت بتحويله (الحد الأدنى {format_currency(min_d)}):")
    return DEPOSIT_AMT

async def deposit_amt_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ يرجى إدخال رقم صحيح:")
        return DEPOSIT_AMT

    min_d = float(get_setting("min_deposit") or 5000)
    if amount < min_d:
        await update.message.reply_text(f"❌ المبلغ أقل من الحد الأدنى للشحن ({format_currency(min_d)}). أعد الإدخال:")
        return DEPOSIT_AMT

    user = update.effective_user
    method = context.user_data['dep_method']
    tx_id = context.user_data['dep_tx']

    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("SELECT wayxbet_account FROM users WHERE user_id = ?", (user.id,))
    row = c.fetchone()
    wayx_acc = row[0] if row else ""

    c.execute("""INSERT INTO requests (user_id, type, method, amount, tx_id, info)
                 VALUES (?, 'deposit', ?, ?, ?, ?)""",
              (user.id, method, amount, tx_id, f"حساب: {wayx_acc}"))
    req_id = c.lastrowid
    conn.commit()
    conn.close()

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ موافقة", callback_data=f"adm_app_dep_{req_id}_{user.id}_{amount}"),
         InlineKeyboardButton("❌ رفض", callback_data=f"adm_rej_dep_{req_id}_{user.id}")]
    ])

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📥 **طلب شحن رصيد جديد (#{req_id})**\n\n"
             f"👤 العضو: {user.full_name}\n"
             f"🆔 الايدي: `{user.id}`\n"
             f"🏷 حساب الموقع: `{wayx_acc}`\n"
             f"💳 الطريقة: {method}\n"
             f"📑 رقم العملية: `{tx_id}`\n"
             f"💰 المبلغ: {format_currency(amount)}",
        parse_mode="Markdown",
        reply_markup=kb
    )

    await update.message.reply_text("✅ تم استلام طلبك وهو الآن قيد المراجعة لدى الإدارة.")
    return ConversationHandler.END

# ----------------- 4. شحن وسحب الموقع المباشر -----------------
async def site_dep_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("SELECT wayxbet_account, balance FROM users WHERE user_id = ?", (query.from_user.id,))
    res = c.fetchone()
    conn.close()

    if not res or not res[0]:
        await query.edit_message_text("❌ يجب إنشاء حساب WayxBet أولاً!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]]))
        return ConversationHandler.END

    min_sd = float(get_setting("min_site_deposit") or 5000)
    await query.edit_message_text(f"🔄 **شحن من البوت إلى حسابك بالموقع:**\n\nرصيدك الحالي بالبوت: {format_currency(res[1])}\nأدخل المبلغ المراد تحويله للموقع (الحد الأدنى {format_currency(min_sd)}):")
    return SITE_DEP_AMT

async def site_dep_amt_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ أدخل رقم صحيح:")
        return SITE_DEP_AMT

    user = update.effective_user
    min_sd = float(get_setting("min_site_deposit") or 5000)
    if amount < min_sd:
        await update.message.reply_text(f"❌ الحد الأدنى لشحن الموقع هو {format_currency(min_sd)}:")
        return SITE_DEP_AMT

    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("SELECT wayxbet_account, balance FROM users WHERE user_id = ?", (user.id,))
    res = c.fetchone()
    wayx_acc, balance = res[0], res[1]

    if balance < amount:
        await update.message.reply_text("❌ رصيدك في البوت غير كافي!")
        conn.close()
        return ConversationHandler.END

    c.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user.id))
    c.execute("INSERT INTO requests (user_id, type, amount, info) VALUES (?, 'site_deposit', ?, ?)",
              (user.id, amount, f"حساب الموقع: {wayx_acc}"))
    req_id = c.lastrowid
    conn.commit()
    conn.close()

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ موافقة", callback_data=f"adm_app_sitedep_{req_id}_{user.id}_{amount}"),
         InlineKeyboardButton("❌ رفض", callback_data=f"adm_rej_sitedep_{req_id}_{user.id}_{amount}")]
    ])

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"🔄 **طلب شحن من البوت إلى الموقع (#{req_id})**\n\n"
             f"👤 العضو: {user.full_name}\n"
             f"🆔 الايدي: `{user.id}`\n"
             f"🏷 حساب الموقع: `{wayx_acc}`\n"
             f"💰 المبلغ المطلوب: {format_currency(amount)}",
        parse_mode="Markdown",
        reply_markup=kb
    )
    await update.message.reply_text("⏳ تم إرسال طلب الشحن إلى حسابك بالموقع للإدارة.")
    return ConversationHandler.END

async def site_wit_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("SELECT wayxbet_account FROM users WHERE user_id = ?", (query.from_user.id,))
    res = c.fetchone()
    conn.close()

    if not res or not res[0]:
        await query.edit_message_text("❌ يجب إنشاء حساب WayxBet أولاً!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]]))
        return ConversationHandler.END

    min_sw = float(get_setting("min_site_withdraw") or 10000)
    await query.edit_message_text(f"🔄 **سحب من حسابك بالموقع إلى البوت:**\n\nأدخل المبلغ المراد سحبـه من حساب الموقع إلى البوت (الحد الأدنى {format_currency(min_sw)}):")
    return SITE_WIT_AMT

async def site_wit_amt_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ أدخل رقم صحيح:")
        return SITE_WIT_AMT

    user = update.effective_user
    min_sw = float(get_setting("min_site_withdraw") or 10000)
    if amount < min_sw:
        await update.message.reply_text(f"❌ الحد الأدنى للسحب من الموقع هو {format_currency(min_sw)}:")
        return SITE_WIT_AMT

    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("SELECT wayxbet_account FROM users WHERE user_id = ?", (user.id,))
    wayx_acc = c.fetchone()[0]

    c.execute("INSERT INTO requests (user_id, type, amount, info) VALUES (?, 'site_withdraw', ?, ?)",
              (user.id, amount, f"حساب الموقع: {wayx_acc}"))
    req_id = c.lastrowid
    conn.commit()
    conn.close()

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ موافقة", callback_data=f"adm_app_sitewit_{req_id}_{user.id}_{amount}"),
         InlineKeyboardButton("❌ رفض", callback_data=f"adm_rej_sitewit_{req_id}_{user.id}")]
    ])

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"🔄 **طلب سحب من الموقع إلى البوت (#{req_id})**\n\n"
             f"👤 العضو: {user.full_name}\n"
             f"🆔 الايدي: `{user.id}`\n"
             f"🏷 حساب الموقع: `{wayx_acc}`\n"
             f"💰 المبلغ: {format_currency(amount)}",
        parse_mode="Markdown",
        reply_markup=kb
    )

    await update.message.reply_text("⏳ تم رفع طلب السحب من الموقع للادارة، يرجى الانتظار.")
    return ConversationHandler.END

# ----------------- 5. الإحالات والدعم والهدية -----------------
async def refs_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    bot_info = await context.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user_id}"

    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("SELECT spins, active_refs, active_ops FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()

    spins, active_refs, active_ops = row[0] if row else (0, 0, 0)

    text = (
        f"👥 **نظام الإحالات الخاص بك:**\n\n"
        f"🔗 رابط الإحالة:\n`{ref_link}`\n\n"
        f"🎡 عدد لفات العجلة المتاحة: `{spins}`\n"
        f"📊 عداد الإحالات الناجحة: `{active_refs}`\n"
        f"💰 عمولة الإحالات (5% عند كل 5 عمليات شحن نشطة): `{active_ops}` عملية\n\n"
        f"🎁 تحصل على لفة مجانية في عجلة الحظ مقابل كل شخص ينضم عبر رابطك ويشارك رقمه السوري بنجاح!"
    )

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]])
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)

async def gift_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🎁 **أدخل كود الهدية الخاص بك هنا:**")
    return GIFT_INPUT

async def gift_input_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()
    user = update.effective_user

    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("SELECT amount FROM gift_codes WHERE code = ?", (code,))
    gift = c.fetchone()

    if not gift:
        await update.message.reply_text("❌ كود الهدية هذا غير صحيح أو غير موجود.")
        conn.close()
        return ConversationHandler.END

    c.execute("SELECT * FROM gift_uses WHERE code = ? AND user_id = ?", (code, user.id))
    if c.fetchone():
        await update.message.reply_text("⚠️ لقد قمت باستخدام هذا الكود سابقاً!")
        conn.close()
        return ConversationHandler.END

    amount = gift[0]
    c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user.id))
    c.execute("INSERT INTO gift_uses (code, user_id) VALUES (?, ?)", (code, user.id))
    c.execute("UPDATE gift_codes SET used_count = used_count + 1 WHERE code = ?", (code,))
    conn.commit()
    conn.close()

    await update.message.reply_text(f"🎉 مبروك! تم استخدام كود الهدية بنجاح وإضافة {format_currency(amount)} إلى رصيدك.")

    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🎁 **إشعار استخدام كود هدية:**\nالمستخدم: {user.full_name} (`{user.id}`)\nالكود: `{code}`\nالقيمة: {format_currency(amount)}",
            parse_mode="Markdown"
        )
    except:
        pass

    return ConversationHandler.END

async def support_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🎧 **قسم الدعم الفني:**\n\nأرسل رسالتك الآن (يمكنك إرسال نص أو صورة مع نص):")
    return SUPPORT_INPUT

async def support_input_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg_text = update.message.text or update.message.caption or "بدون نص"
    photo_id = update.message.photo[-1].file_id if update.message.photo else None

    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("INSERT INTO support_tickets (user_id, message, photo_id) VALUES (?, ?, ?)",
              (user.id, msg_text, photo_id))
    ticket_id = c.lastrowid
    conn.commit()
    conn.close()

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 رد على التذكرة", callback_data=f"adm_reply_ticket_{ticket_id}_{user.id}")]
    ])

    admin_msg = f"📩 **تذكرة دعم جديدة (#{ticket_id}):**\n\n👤 المستخدم: {user.full_name}\n🆔 الايدي: `{user.id}`\n📝 الرسالة: {msg_text}"
    if photo_id:
        await context.bot.send_photo(chat_id=ADMIN_ID, photo=photo_id, caption=admin_msg, parse_mode="Markdown", reply_markup=kb)
    else:
        await context.bot.send_message(chat_id=ADMIN_ID, text=admin_msg, parse_mode="Markdown", reply_markup=kb)

    await update.message.reply_text("✅ تم إرسال رسالتك لفريق الدعم الفني، وسيصلك الرد هنا مباشرة.")
    return ConversationHandler.END

async def comps_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    comp_text = get_setting("current_competition") or "🏆 لا توجد مسابقات نشطة حالياً."
    await query.edit_message_text(f"🏆 **المسابقات الحالية:**\n\n{comp_text}", parse_mode="Markdown",
                                  reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]]))

# ----------------- 6. لوحة الإدارة الشاملة المكتملة -----------------
async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("❌ ليست لديك صلاحيات الإدارة!", show_alert=True)
        return

    await query.answer()
    maint_status = "تفعيل وضع الصيانة 🛠" if get_setting("maintenance_mode") == "0" else "إلغاء وضع الصيانة 🟢"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(maint_status, callback_data="toggle_setting_maintenance_mode")],
        [InlineKeyboardButton("⚙️ إعدادات البونصات والحدود", callback_data="adm_settings_menu")],
        [InlineKeyboardButton("🎡 خوارزمية نسب ربح العجلة", callback_data="adm_wheel_menu")],
        [InlineKeyboardButton("💳 تغيير حسابات الشحن (سيريتل/شام)", callback_data="adm_accounts_menu")],
        [InlineKeyboardButton("📜 سجلات الطلبات الكاملة", callback_data="adm_logs_menu")],
        [InlineKeyboardButton("👥 إدارة اللاعبين والمستخدمين", callback_data="adm_users_menu")],
        [InlineKeyboardButton("🎁 إنشاء كود هدية", callback_data="adm_create_gift"),
         InlineKeyboardButton("➕ إضافة أدمن جديد", callback_data="adm_add_admin")],
        [InlineKeyboardButton("📢 إرسال رسالة جماعية", callback_data="adm_broadcast"),
         InlineKeyboardButton("✉️ إرسال رسالة خاصة", callback_data="adm_private_msg")],
        [InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="back_home")]
    ])
    await query.edit_message_text("🛠 **لوحة الإدارة الشاملة والتحكم الكامل بالبوت:**", reply_markup=kb)

# --- موافقات ورفض الطلبات وتخزين يوزر وباسورد العميل ---
async def admin_request_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data.split("_")
    action = data[1]
    req_type = data[2]
    req_id = int(data[3])
    target_user_id = int(data[4])

    context.user_data['pending_action'] = {
        'action': action,
        'type': req_type,
        'req_id': req_id,
        'user_id': target_user_id,
        'extra_val': data[5] if len(data) > 5 else None
    }

    await query.answer()
    await query.message.reply_text("👤 **إجراء أمني:** يرجى كتابة اسمك (اسم الأدمن) لإتمام العملية وتوثيقها:")
    return ADMIN_NAME_INPUT

async def admin_name_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_name = update.message.text.strip()
    action_data = context.user_data.get('pending_action')
    if not action_data:
        await update.message.reply_text("❌ حدث خطأ ببيانات الطلب!")
        return ConversationHandler.END

    act = action_data['action']
    req_type = action_data['type']
    req_id = action_data['req_id']
    target_user_id = action_data['user_id']
    extra_val = action_data['extra_val']

    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()

    if act == "app":
        c.execute("UPDATE requests SET status = 'approved', admin_name = ? WHERE id = ?", (admin_name, req_id))
        if req_type == "acc":
            c.execute("SELECT info FROM requests WHERE id = ?", (req_id,))
            req_info = c.fetchone()
            pass_val = ""
            if req_info and req_info[0]:
                try:
                    pass_val = req_info[0].split("| باسورد: ")[1].split(" |")[0].strip()
                except:
                    pass_val = ""
            c.execute("UPDATE users SET wayxbet_account = ?, wayxbet_pass = ? WHERE user_id = ?", (extra_val, pass_val, target_user_id))
            await context.bot.send_message(
                target_user_id, 
                f"✅ تمت الموافقة على إنشاء حسابك بواسطة الأدمن ({admin_name})!\n\n"
                f"👤 **اسم الحساب:** `{extra_val}`\n"
                f"🔑 **كلمة المرور:** `{pass_val}`\n\n"
                f"يمكنك الشحن والاستفادة من الخدمات الآن.",
                parse_mode="Markdown"
            )
        elif req_type == "wit":
            await context.bot.send_message(target_user_id, f"✅ تم تنفيذ طلب السحب الخاص بك بنجاح بواسطة الأدمن ({admin_name}).")
        elif req_type == "dep":
            amt = float(extra_val)
            dep_bonus_active = get_setting("deposit_bonus_active") == "1"
            dep_bonus_pct = float(get_setting("deposit_bonus") or 0) if dep_bonus_active else 0
            final_amt = amt + (amt * (dep_bonus_pct / 100))
            c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (final_amt, target_user_id))
            await context.bot.send_message(target_user_id, f"✅ تمت الموافقة على طلب الشحن بقيمة {format_currency(amt)} وإضافتها لرصيدك بواسطة الأدمن ({admin_name}).")
        elif req_type == "sitedep":
            amt = float(extra_val)
            await context.bot.send_message(target_user_id, f"✅ تم شحن مبلغ {format_currency(amt)} إلى حسابك في الموقع بنجاح بواسطة الأدمن ({admin_name}).")
        elif req_type == "sitewit":
            amt = float(extra_val)
            c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amt, target_user_id))
            await context.bot.send_message(target_user_id, f"✅ تمت الموافقة على سحب {format_currency(amt)} من الموقع وإضافتها لرصيدك بالبوت بواسطة الأدمن ({admin_name}).")

        await update.message.reply_text(f"✅ تم تأكيد الموافقة على الطلب (#{req_id}) باسم الأدمن: {admin_name}")

    else:
        c.execute("UPDATE requests SET status = 'rejected', admin_name = ? WHERE id = ?", (admin_name, req_id))
        if req_type == "wit" or req_type == "sitedep":
            amt = float(extra_val)
            c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amt, target_user_id))
        
        await context.bot.send_message(target_user_id, f"❌ تم رفض طلبك من قبل الإدارة ({admin_name}).")
        await update.message.reply_text(f"❌ تم رفض الطلب (#{req_id}) باسم الأدمن: {admin_name}")

    conn.commit()
    conn.close()
    return ConversationHandler.END

# --- خوارزمية العجلة ---
async def adm_wheel_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    numbers = [0, 5, 10, 15, 25, 50, 100, 1000, 10000]
    kb = []
    for num in numbers:
        prob = get_setting(f"wheel_prob_{num}") or "0"
        kb.append([InlineKeyboardButton(f"الرقم {num} - الاحتمال الحالي: {prob}%", callback_data=f"set_wheel_prob_{num}")])
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")])

    await query.edit_message_text("🎡 **تعديل خوارزمية ونسب ربح العجلة:**\n\nاختر الرقم لتعديل نسبة احتماله:", reply_markup=InlineKeyboardMarkup(kb))

async def adm_set_wheel_prob_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    num = query.data.split("_")[3]
    context.user_data['edit_wheel_num'] = num
    await query.edit_message_text(f"🎯 أدخل النسبة المئوية الجديدة لفوز الرقم **{num}** (مثال: 15.5):")
    return ADMIN_WHEEL_PROB_VAL

async def adm_wheel_prob_val_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    num = context.user_data.get('edit_wheel_num')
    try:
        float_val = float(val)
        set_setting(f"wheel_prob_{num}", str(float_val))
        await update.message.reply_text(f"✅ تم تعديل نسبة احتمال الرقم {num} إلى {float_val}% بنجاح!")
    except:
        await update.message.reply_text("❌ قيمة غير صحيحة، أعد الإدخال.")
    return ConversationHandler.END

# --- إعدادات البونص والحدود والصيانة وتفعيل/إلغاء أرباح الإحالات ---
async def adm_settings_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    wb_active = "مفعل ✅" if get_setting("welcome_bonus_active") == "1" else "معطل ❌"
    db_active = "مفعل ✅" if get_setting("deposit_bonus_active") == "1" else "معطل ❌"
    ref_active = "مفعل ✅" if get_setting("ref_spin_active") == "1" else "معطل ❌"
    maint_active = "مفعل 🛠" if get_setting("maintenance_mode") == "1" else "معطل 🟢"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"وضع الصيانة ({maint_active})", callback_data="toggle_setting_maintenance_mode")],
        [InlineKeyboardButton(f"نظام أرباح الإحالات ({ref_active})", callback_data="toggle_setting_ref_spin_active")],
        [InlineKeyboardButton(f"البونص الترحيبي ({wb_active})", callback_data="toggle_setting_welcome_bonus_active"),
         InlineKeyboardButton("قيمة البونص الترحيبي", callback_data="set_setting_welcome_bonus")],
        [InlineKeyboardButton(f"بونص الشحن ({db_active})", callback_data="toggle_setting_deposit_bonus_active"),
         InlineKeyboardButton("نسبة بونص الشحن %", callback_data="set_setting_deposit_bonus")],
        [InlineKeyboardButton("الحد الأدنى للشحن (بوت)", callback_data="set_setting_min_deposit"),
         InlineKeyboardButton("الحد الأدنى للسحب (بوت)", callback_data="set_setting_min_withdraw")],
        [InlineKeyboardButton("الحد الأدنى للشحن (موقع)", callback_data="set_setting_min_site_deposit"),
         InlineKeyboardButton("الحد الأدنى للسحب (موقع)", callback_data="set_setting_min_site_withdraw")],
        [InlineKeyboardButton("تغيير نسبة العملة (القديمة/الجديدة)", callback_data="set_setting_currency_ratio")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]
    ])
    await query.edit_message_text("⚙️ **إعدادات البونصات والحدود والأرباح والصيانة:**", reply_markup=kb)

async def toggle_setting_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    key = query.data.replace("toggle_setting_", "")
    curr = get_setting(key)
    new_val = "0" if curr == "1" else "1"
    set_setting(key, new_val)
    await query.answer("✅ تم تغيير الحالة بنجاح!")
    
    if key == "maintenance_mode":
        return await admin_panel_callback(update, context)
    return await adm_settings_menu_callback(update, context)

async def set_setting_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = query.data.replace("set_setting_", "")
    context.user_data['setting_key_to_edit'] = key
    await query.edit_message_text(f"📝 أدخل القيمة الجديدة لـ (`{key}`):", parse_mode="Markdown")
    return ADMIN_SETTING_VAL

async def set_setting_val_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    key = context.user_data.get('setting_key_to_edit')
    set_setting(key, val)
    await update.message.reply_text(f"✅ تم حفظ القيمة الجديدة لـ `{key}` بنجاح!", parse_mode="Markdown")
    return ConversationHandler.END

async def adm_accounts_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    syr = get_setting("syriatel_num")
    sham = get_setting("sham_num")

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"تعديل سيريتل كاش ({syr})", callback_data="set_setting_syriatel_num")],
        [InlineKeyboardButton(f"تعديل شام كاش ({sham[:10]}...)", callback_data="set_setting_sham_num")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]
    ])
    await query.edit_message_text("💳 **تعديل حسابات الشحن:**", reply_markup=kb)

# --- إدارة اللاعبين والمستخدمين وحظرهم والتعديل عليهم (مع إضافة منح لفات مجانية للاعب) ---
async def adm_users_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    conn.close()

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 عرض تفاصيل لاعب محدد", callback_data="adm_view_user_start")],
        [InlineKeyboardButton("🎡 منح لفات مجانية للاعب", callback_data="adm_grant_spins_start")],
        [InlineKeyboardButton("➕ إضافة رصيد للاعب", callback_data="adm_add_bal_start"),
         InlineKeyboardButton("➖ خصم رصيد من لاعب", callback_data="adm_ded_bal_start")],
        [InlineKeyboardButton("🚫 حظر مستخدم", callback_data="adm_ban_start"),
         InlineKeyboardButton("✅ إلغاء حظر مستخدم", callback_data="adm_unban_start")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]
    ])
    await query.edit_message_text(f"👥 **إدارة المستخدمين:**\n\nإجمالي مستخدمين البوت: `{total_users}` مستخدم.", parse_mode="Markdown", reply_markup=kb)

async def adm_view_user_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🔍 أدخل ايدي (ID) اللاعب لرؤية تفاصيله الكاملة:")
    return ADMIN_VIEW_USER_ID

async def adm_view_user_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id_str = update.message.text.strip()
    if not user_id_str.isdigit():
        await update.message.reply_text("❌ أدخل ايدي صحيح.")
        return ConversationHandler.END

    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("SELECT full_name, phone, balance, spins, active_refs, wayxbet_account, wayxbet_pass, banned, created_at FROM users WHERE user_id = ?", (int(user_id_str),))
    u = c.fetchone()
    conn.close()

    if not u:
        await update.message.reply_text("❌ لم يتم العثور على هذا المستخدم في البوت.")
        return ConversationHandler.END

    status = "محظور 🚫" if u[7] == 1 else "نشط ✅"
    text = (
        f"👤 **تفاصيل اللاعب (#{user_id_str}):**\n\n"
        f"▪️ الاسم: {u[0]}\n"
        f"▪️ الرقم: `{u[1]}`\n"
        f"▪️ الرصيد الحالي: {format_currency(u[2])}\n"
        f"▪️ لفات العجلة: `{u[3]}`\n"
        f"▪️ عداد الإحالات: `{u[4]}`\n"
        f"▪️ حساب الموقع: `{u[5] or 'غير مسجل'}`\n"
        f"▪️ كلمة المرور: `{u[6] or 'غير مسجل'}`\n"
        f"▪️ الحالة: {status}\n"
        f"▪️ تاريخ الانضمام: {u[8]}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")
    return ConversationHandler.END

# --- وظيفة منح لفات مجانية للاعب من لوحة الإدارة ---
async def adm_grant_spins_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🎡 أدخل ايدي (ID) اللاعب المراد منح لفات عجلة مجانية له:")
    return ADMIN_SPINS_ID

async def adm_grant_spins_id_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text_id = update.message.text.strip()
    if not text_id.isdigit():
        await update.message.reply_text("❌ ايدي غير صحيح، أعد الإدخال:")
        return ADMIN_SPINS_ID
    context.user_data['grant_spins_user_id'] = int(text_id)
    await update.message.reply_text("🔢 أدخل عدد لفات العجلة المجانية المراد إضافتها للاعب:")
    return ADMIN_SPINS_COUNT

async def adm_grant_spins_count_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text_count = update.message.text.strip()
    if not text_count.isdigit():
        await update.message.reply_text("❌ عدد غير صحيح، أعد إدخال الرقم:")
        return ADMIN_SPINS_COUNT
    
    count = int(text_count)
    target_id = context.user_data.get('grant_spins_user_id')

    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("UPDATE users SET spins = spins + ? WHERE user_id = ?", (count, target_id))
    c.execute("SELECT spins FROM users WHERE user_id = ?", (target_id,))
    res = c.fetchone()
    conn.commit()
    conn.close()

    if not res:
        await update.message.reply_text("❌ لم يتم العثور على المستخدم!")
        return ConversationHandler.END

    new_total = res[0]
    await update.message.reply_text(f"✅ تم إضافة `{count}` لفة عجلة مجانية بنجاح للاعب `{target_id}`!\n🎡 إجمالي لفاته الآن: `{new_total}`", parse_mode="Markdown")
    
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=f"🎁 **هدية من الإدارة:**\nتم منحك `{count}` لفة عجلة مجانية! إجمالي لفاتك الآن: `{new_total}` 🎡",
            parse_mode="Markdown"
        )
    except:
        pass

    return ConversationHandler.END

async def adm_bal_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    b_type = "add" if "add" in query.data else "ded"
    context.user_data['bal_type'] = b_type
    await query.edit_message_text(f"💰 أدخل ايدي (ID) اللاعب المراد {'إضافة' if b_type == 'add' else 'خصم'} رصيد له:")
    return ADMIN_BAL_ID

async def adm_bal_id_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['target_bal_id'] = int(update.message.text.strip())
    b_type = context.user_data['bal_type']
    await update.message.reply_text(f"💵 أدخل المبلغ المراد {'إضافته' if b_type == 'add' else 'خصمه'}:")
    return ADMIN_BAL_AMT

async def adm_bal_amt_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amt = float(update.message.text.strip())
    target_id = context.user_data['target_bal_id']
    b_type = context.user_data['bal_type']

    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    if b_type == "add":
        c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amt, target_id))
        msg = f"🎉 تم إضافة {format_currency(amt)} إلى رصيدك بواسطة الإدارة."
    else:
        c.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amt, target_id))
        msg = f"📉 تم خصم {format_currency(amt)} من رصيدك بواسطة الإدارة."
    
    conn.commit()
    conn.close()

    await update.message.reply_text("✅ تم تعديل الرصيد بنجاح!")
    try:
        await context.bot.send_message(target_id, msg)
    except:
        pass
    return ConversationHandler.END

async def adm_ban_unban_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    is_ban = "ban" in query.data and "unban" not in query.data
    context.user_data['is_ban_op'] = is_ban
    await query.edit_message_text(f"🚫 أدخل ايدي (ID) المستخدم المراد {'حظره' if is_ban else 'إلغاء حظره'}:")
    return ADMIN_BAN_ID if is_ban else ADMIN_UNBAN_ID

async def adm_ban_id_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target_id = int(update.message.text.strip())
    is_ban = context.user_data['is_ban_op']

    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("UPDATE users SET banned = ? WHERE user_id = ?", (1 if is_ban else 0, target_id))
    conn.commit()
    conn.close()

    await update.message.reply_text(f"✅ تم {'حظر' if is_ban else 'إلغاء حظر'} المستخدم بنجاح.")
    return ConversationHandler.END

# --- سجلات الطلبات التفصيلية ---
async def adm_logs_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📜 سجلات الشحن", callback_data="adm_view_logs_deposit"),
         InlineKeyboardButton("📜 سجلات السحب", callback_data="adm_view_logs_withdraw")],
        [InlineKeyboardButton("📜 سجلات شحن الموقع", callback_data="adm_view_logs_site_deposit"),
         InlineKeyboardButton("📜 سجلات سحب الموقع", callback_data="adm_view_logs_site_withdraw")],
        [InlineKeyboardButton("📜 سجلات إنشاء الحسابات", callback_data="adm_view_logs_account")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]
    ])
    await query.edit_message_text("📜 **عرض سجلات الطلبات حسب النوع:**", reply_markup=kb)

async def adm_view_logs_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    log_type = query.data.replace("adm_view_logs_", "")

    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("SELECT id, user_id, amount, status, admin_name, created_at FROM requests WHERE type = ? ORDER BY id DESC LIMIT 10", (log_type,))
    logs = c.fetchall()
    conn.close()

    if not logs:
        await query.edit_message_text("📭 لا توجد سجلات حالية لهذا القسم.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_logs_menu")]]))
        return

    text = f"📜 **أحدث 10 طلبات ({log_type}):**\n\n"
    for l in logs:
        text += f"▪️ طلب #{l[0]} | ايدي: `{l[1]}` | مبلغ: {l[2]} | الحالة: {l[3]} | الأدمن: {l[4] or 'لا يوجد'} | التاريخ: {l[5]}\n---\n"

    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_logs_menu")]]))

# --- كود الهدية والأدمنز والرسائل الجماعية والخاصة ---
async def adm_create_gift_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🎁 أدخل اسم كود الهدية الجديد (مثال: VIP100):")
    return ADMIN_GIFT_CODE

async def gift_code_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_gift_code'] = update.message.text.strip()
    await update.message.reply_text("💰 أدخل القيمة المالية لهذا الكود:")
    return ADMIN_GIFT_AMT

async def gift_amt_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amt = float(update.message.text.strip())
    code = context.user_data['new_gift_code']

    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO gift_codes (code, amount) VALUES (?, ?)", (code, amt))
    conn.commit()
    conn.close()

    await update.message.reply_text(f"✅ تم إنشاء كود الهدية `{code}` بقيمة {format_currency(amt)} بنجاح!", parse_mode="Markdown")
    return ConversationHandler.END

async def adm_add_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("➕ أدخل ايدي (ID) الشخص المراد إضافته كأدمن:")
    return ADMIN_NEW_ADMIN_ID

async def adm_add_admin_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_admin_id = int(update.message.text.strip())
    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO admins (admin_id, admin_name) VALUES (?, ?)", (new_admin_id, "أدمن فرعي"))
    conn.commit()
    conn.close()

    await update.message.reply_text(f"✅ تم منح صلاحيات الأدمن للشخص صاحب الايدي `{new_admin_id}` بنجاح!", parse_mode="Markdown")
    return ConversationHandler.END

async def adm_broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("📢 أدخل النص المراد إرساله كإذاعة جماعية لجميع المستخدمين:")
    return ADMIN_BROADCAST_MSG

async def adm_broadcast_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    users = c.fetchall()
    conn.close()

    success, fail = 0, 0
    for u in users:
        try:
            await context.bot.send_message(u[0], f"📢 **إشعار من الإدارة:**\n\n{text}", parse_mode="Markdown")
            success += 1
        except:
            fail += 1

    await update.message.reply_text(f"✅ تم إنهاء الإذاعة بنجاح!\n📊 النماذج المستلمة: {success} | الفاشلة: {fail}")
    return ConversationHandler.END

async def adm_private_msg_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("✉️ أدخل ايدي (ID) المستخدم المراد مراسلته بشكل خاص:")
    return ADMIN_PRIV_ID

async def adm_priv_id_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['target_priv_id'] = int(update.message.text.strip())
    await update.message.reply_text("✉️ أدخل النص المراد إرساله له:")
    return ADMIN_PRIV_MSG

async def adm_priv_msg_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    target_id = context.user_data['target_priv_id']

    try:
        await context.bot.send_message(target_id, f"📩 **رسالة خاصة من الإدارة:**\n\n{text}", parse_mode="Markdown")
        await update.message.reply_text("✅ تم إرسال الرسالة الخاصة بنجاح!")
    except Exception as e:
        await update.message.reply_text(f"❌ تعذر إرسال الرسالة: {e}")
    return ConversationHandler.END

async def adm_reply_ticket_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split("_")
    context.user_data['reply_ticket_id'] = int(data[3])
    context.user_data['reply_user_id'] = int(data[4])
    await query.message.reply_text("💬 اكتب ردك الآن لإرساله إلى المستخدم مباشرة:")
    return ADMIN_TICKET_REPLY

async def adm_reply_ticket_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_text = update.message.text.strip()
    target_user_id = context.user_data['reply_user_id']
    ticket_id = context.user_data['reply_ticket_id']

    try:
        await context.bot.send_message(target_user_id, f"🎧 **رد الدعم الفني على تذكرتك (#{ticket_id}):**\n\n{reply_text}")
        await update.message.reply_text("✅ تم إرسال الرد للعميل بنجاح.")
    except Exception as e:
        await update.message.reply_text(f"❌ فشل إرسال الرد: {e}")
    return ConversationHandler.END

# ----------------- تشغيل البوت -----------------
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # Handlers
    acc_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(wayxbet_menu_callback, pattern="^wayx_acc_menu$")],
        states={
            ACC_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_acc_name)],
            ACC_PASS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_acc_pass)],
        },
        fallbacks=[CallbackQueryHandler(back_home_callback, pattern="^back_home$")]
    )

    wit_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(withdraw_menu_callback, pattern="^withdraw_menu$")],
        states={
            WITHDRAW_METHOD: [CallbackQueryHandler(withdraw_method_chosen, pattern="^wit_meth_")],
            WITHDRAW_ACC: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_acc_received)],
            WITHDRAW_AMT: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_amt_received)],
            WITHDRAW_SPEED: [CallbackQueryHandler(withdraw_speed_chosen, pattern="^wit_speed_")],
            WITHDRAW_CONFIRM: [CallbackQueryHandler(withdraw_confirmed, pattern="^wit_confirm$")],
        },
        fallbacks=[CallbackQueryHandler(back_home_callback, pattern="^back_home$")]
    )

    dep_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(deposit_menu_callback, pattern="^deposit_menu$")],
        states={
            DEPOSIT_METHOD: [CallbackQueryHandler(deposit_method_chosen, pattern="^dep_meth_")],
            DEPOSIT_TX: [MessageHandler(filters.TEXT & ~filters.COMMAND, deposit_tx_received)],
            DEPOSIT_AMT: [MessageHandler(filters.TEXT & ~filters.COMMAND, deposit_amt_received)],
        },
        fallbacks=[CallbackQueryHandler(back_home_callback, pattern="^back_home$")]
    )

    site_dep_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(site_dep_menu_callback, pattern="^site_dep_menu$")],
        states={
            SITE_DEP_AMT: [MessageHandler(filters.TEXT & ~filters.COMMAND, site_dep_amt_received)],
        },
        fallbacks=[CallbackQueryHandler(back_home_callback, pattern="^back_home$")]
    )

    site_wit_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(site_wit_menu_callback, pattern="^site_wit_menu$")],
        states={
            SITE_WIT_AMT: [MessageHandler(filters.TEXT & ~filters.COMMAND, site_wit_amt_received)],
        },
        fallbacks=[CallbackQueryHandler(back_home_callback, pattern="^back_home$")]
    )

    gift_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(gift_menu_callback, pattern="^gift_menu$")],
        states={
            GIFT_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, gift_input_received)],
        },
        fallbacks=[CallbackQueryHandler(back_home_callback, pattern="^back_home$")]
    )

    support_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(support_menu_callback, pattern="^support_menu$")],
        states={
            SUPPORT_INPUT: [MessageHandler((filters.TEXT | filters.PHOTO) & ~filters.COMMAND, support_input_received)],
        },
        fallbacks=[CallbackQueryHandler(back_home_callback, pattern="^back_home$")]
    )

    admin_req_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_request_action_callback, pattern="^adm_(app|rej)_")],
        states={
            ADMIN_NAME_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_name_received)],
        },
        fallbacks=[]
    )

    admin_wheel_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(adm_set_wheel_prob_callback, pattern="^set_wheel_prob_")],
        states={
            ADMIN_WHEEL_PROB_VAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_wheel_prob_val_received)],
        },
        fallbacks=[]
    )

    admin_setting_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(set_setting_start_callback, pattern="^set_setting_")],
        states={
            ADMIN_SETTING_VAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_setting_val_received)],
        },
        fallbacks=[]
    )

    admin_gift_create_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(adm_create_gift_callback, pattern="^adm_create_gift$")],
        states={
            ADMIN_GIFT_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, gift_code_received)],
            ADMIN_GIFT_AMT: [MessageHandler(filters.TEXT & ~filters.COMMAND, gift_amt_received)],
        },
        fallbacks=[]
    )

    admin_add_admin_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(adm_add_admin_callback, pattern="^adm_add_admin$")],
        states={
            ADMIN_NEW_ADMIN_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_add_admin_received)],
        },
        fallbacks=[]
    )

    admin_broadcast_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(adm_broadcast_callback, pattern="^adm_broadcast$")],
        states={
            ADMIN_BROADCAST_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_broadcast_received)],
        },
        fallbacks=[]
    )

    admin_priv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(adm_private_msg_callback, pattern="^adm_private_msg$")],
        states={
            ADMIN_PRIV_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_priv_id_received)],
            ADMIN_PRIV_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_priv_msg_received)],
        },
        fallbacks=[]
    )

    admin_user_view_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(adm_view_user_start_callback, pattern="^adm_view_user_start$")],
        states={
            ADMIN_VIEW_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_view_user_received)],
        },
        fallbacks=[]
    )

    admin_grant_spins_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(adm_grant_spins_start_callback, pattern="^adm_grant_spins_start$")],
        states={
            ADMIN_SPINS_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_grant_spins_id_received)],
            ADMIN_SPINS_COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_grant_spins_count_received)],
        },
        fallbacks=[]
    )

    admin_bal_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(adm_bal_start_callback, pattern="^adm_(add|ded)_bal_start$")],
        states={
            ADMIN_BAL_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_bal_id_received)],
            ADMIN_BAL_AMT: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_bal_amt_received)],
        },
        fallbacks=[]
    )

    admin_ban_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(adm_ban_unban_start_callback, pattern="^adm_(ban|unban)_start$")],
        states={
            ADMIN_BAN_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_ban_id_received)],
            ADMIN_UNBAN_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_ban_id_received)],
        },
        fallbacks=[]
    )

    admin_reply_ticket_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(adm_reply_ticket_callback, pattern="^adm_reply_ticket_")],
        states={
            ADMIN_TICKET_REPLY: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_reply_ticket_received)],
        },
        fallbacks=[]
    )

    # Adding Commands and Callbacks
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(verify_subscription_callback, pattern="^verify_subscription$"))
    app.add_handler(MessageHandler(filters.CONTACT, contact_handler))
    app.add_handler(CallbackQueryHandler(back_home_callback, pattern="^back_home$"))
    app.add_handler(CallbackQueryHandler(refs_menu_callback, pattern="^refs_menu$"))
    app.add_handler(CallbackQueryHandler(comps_menu_callback, pattern="^comps_menu$"))

    # Admin Panel Submenus
    app.add_handler(CallbackQueryHandler(admin_panel_callback, pattern="^admin_panel$"))
    app.add_handler(CallbackQueryHandler(adm_wheel_menu_callback, pattern="^adm_wheel_menu$"))
    app.add_handler(CallbackQueryHandler(adm_settings_menu_callback, pattern="^adm_settings_menu$"))
    app.add_handler(CallbackQueryHandler(adm_accounts_menu_callback, pattern="^adm_accounts_menu$"))
    app.add_handler(CallbackQueryHandler(adm_users_menu_callback, pattern="^adm_users_menu$"))
    app.add_handler(CallbackQueryHandler(adm_logs_menu_callback, pattern="^adm_logs_menu$"))
    app.add_handler(CallbackQueryHandler(adm_view_logs_callback, pattern="^adm_view_logs_"))
    app.add_handler(CallbackQueryHandler(toggle_setting_callback, pattern="^toggle_setting_"))

    # Add Conversations
    app.add_handler(acc_handler)
    app.add_handler(dep_handler)
    app.add_handler(wit_handler)
    app.add_handler(site_dep_handler)
    app.add_handler(site_wit_handler)
    app.add_handler(gift_handler)
    app.add_handler(support_handler)
    app.add_handler(admin_req_handler)
    app.add_handler(admin_wheel_handler)
    app.add_handler(admin_setting_handler)
    app.add_handler(admin_gift_create_handler)
    app.add_handler(admin_add_admin_handler)
    app.add_handler(admin_broadcast_handler)
    app.add_handler(admin_priv_handler)
    app.add_handler(admin_user_view_handler)
    app.add_handler(admin_grant_spins_handler)
    app.add_handler(admin_bal_handler)
    app.add_handler(admin_ban_handler)
    app.add_handler(admin_reply_ticket_handler)

    print("🤖 تم تشغيل البوت المكتمل بكافة الإصلاحات والإضافات بنجاح...")
    app.run_polling()

if __name__ == "__main__":
    main()

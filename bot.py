import os
import sys
import logging
import math
import random
import time
import asyncio
import sqlite3
import threading
from flask import Flask, render_template_string, request, jsonify

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    WebAppInfo
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

# ----------------------------------------------------
# 1. إعداد التسجيل والمحيط (Logging & Environment)
# ----------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://your-domain.com/slot")
ADMIN_IDS = [int(i) for i in os.getenv("ADMIN_IDS", "123456789").split(",") if i.strip()]

# ----------------------------------------------------
# 2. خادم Flask للحفاظ على عمل البوت (Keep-Alive) واستضافة اللعبة
# ----------------------------------------------------
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "Bot Server is Alive and Running!"

@flask_app.route("/slot")
def slot_game():
    html_code = """
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
        <title>Slot Game</title>
        <script src="https://telegram.org/js/telegram-web-app.js"></script>
        <style>
            body {
                background-color: #121212;
                color: #ffffff;
                font-family: Arial, sans-serif;
                text-align: center;
                margin: 0;
                padding: 20px;
            }
            .container {
                max-width: 400px;
                margin: 0 auto;
            }
            .slot-machine {
                background: #1e1e1e;
                border: 3px solid #f39c12;
                border-radius: 15px;
                padding: 20px;
                margin-top: 20px;
            }
            .reels {
                display: flex;
                justify-content: space-around;
                font-size: 3rem;
                background: #000;
                padding: 10px;
                border-radius: 10px;
            }
            button {
                background-color: #f39c12;
                border: none;
                color: white;
                padding: 15px 32px;
                font-size: 1.2rem;
                margin-top: 20px;
                border-radius: 8px;
                cursor: pointer;
                width: 100%;
            }
            button:disabled {
                background-color: #555;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h2>🎰 لعبة السلوت 🎰</h2>
            <div class="slot-machine">
                <div class="reels">
                    <span id="reel1">❓</span>
                    <span id="reel2">❓</span>
                    <span id="reel3">❓</span>
                </div>
            </div>
            <button id="spinBtn" onclick="spin()">دوران 🎯</button>
            <p id="result"></p>
        </div>

        <script>
            const tg = window.Telegram.WebApp;
            tg.expand();

            async function spin() {
                const btn = document.getElementById("spinBtn");
                btn.disabled = true;
                document.getElementById("result").innerText = "جاري الدوران...";

                try {
                    const response = await fetch('/api/spin', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ initData: tg.initData })
                    });
                    const data = await response.json();

                    if (data.success) {
                        document.getElementById("reel1").innerText = data.symbols[0];
                        document.getElementById("reel2").innerText = data.symbols[1];
                        document.getElementById("reel3").innerText = data.symbols[2];
                        document.getElementById("result").innerText = data.message;
                    } else {
                        document.getElementById("result").innerText = data.error || "حدث خطأ ما";
                    }
                } catch (e) {
                    document.getElementById("result").innerText = "فشل الاتصال بالسيرفر";
                } finally {
                    btn.disabled = false;
                }
            }
        </script>
    </body>
    </html>
    """
    return render_template_string(html_code)

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)

def keep_alive():
    t = threading.Thread(target=run_flask)
    t.daemon = True
    t.start()

# ----------------------------------------------------
# 3. إدارة قاعدة البيانات (SQLite Database)
# ----------------------------------------------------
DB_FILE = "bot_database.db"

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        full_name TEXT,
        phone TEXT,
        balance REAL DEFAULT 0.0,
        referrals_count INTEGER DEFAULT 0,
        referred_by INTEGER,
        games_played INTEGER DEFAULT 0,
        is_banned INTEGER DEFAULT 0,
        step TEXT DEFAULT 'main'
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS admins (
        user_id INTEGER PRIMARY KEY
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS channels (
        channel_id TEXT PRIMARY KEY,
        channel_title TEXT,
        invite_link TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS deposits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        method TEXT,
        amount REAL,
        tx_id TEXT,
        photo_file_id TEXT,
        status TEXT DEFAULT 'pending'
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS withdrawals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        method TEXT,
        amount REAL,
        account_code TEXT,
        status TEXT DEFAULT 'pending'
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS gifts (
        code TEXT PRIMARY KEY,
        amount REAL,
        max_uses INTEGER,
        used_count INTEGER DEFAULT 0
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        action TEXT,
        amount REAL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS deposit_methods (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        method_name TEXT,
        account_details TEXT
    )
    """)

    # القيم الافتراضية للإعدادات
    default_settings = {
        "min_deposit": "100",
        "min_withdraw": "200",
        "referral_reward": "50",
        "welcome_bonus": "0",
        "maintenance_mode": "0",
        "global_win_mode": "auto",
        "win_rate": "30",
        "bonus_win_rate": "40",
        "bonus_cap_1": "200",
        "bonus_cap_2": "500",
        "bonus_cap_3": "1000",
        "chance_loss": "50",
        "chance_normal": "30",
        "chance_medium": "12",
        "chance_high": "6",
        "chance_huge": "2"
    }

    for k, v in default_settings.items():
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

    for admin_id in ADMIN_IDS:
        c.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (admin_id,))

    conn.commit()
    conn.close()

# ----------------------------------------------------
# 4. وظائف مساعدة وإعادة استخدام الواجهات
# ----------------------------------------------------
def is_maintenance_active():
    conn = get_db()
    res = conn.execute("SELECT value FROM settings WHERE key='maintenance_mode'").fetchone()
    conn.close()
    return res and res["value"] == "1"

async def check_user_channels_subscription(bot, user_id):
    conn = get_db()
    channels = conn.execute("SELECT * FROM channels").fetchall()
    conn.close()

    unsubscribed = []
    for ch in channels:
        try:
            member = await bot.get_chat_member(chat_id=ch["channel_id"], user_id=user_id)
            if member.status in ["left", "kicked"]:
                unsubscribed.append(ch)
        except Exception:
            unsubscribed.append(ch)

    return len(unsubscribed) == 0, unsubscribed

def build_sub_keyboard(unsubscribed_channels):
    kb = []
    for ch in unsubscribed_channels:
        kb.append([InlineKeyboardButton(text=f"📢 {ch['channel_title']}", url=ch["invite_link"])])
    kb.append([InlineKeyboardButton(text="✅ تحقق من الاشتراك", callback_data="check_subscription_status")])
    return InlineKeyboardMarkup(kb)

def build_main_keyboard(user_id, is_admin=False):
    kb = [
        [InlineKeyboardButton("🎰 بدء اللعب (فتح اللعبة)", web_app=WebAppInfo(url=WEBAPP_URL))],
        [InlineKeyboardButton("👤 حسابي", callback_data="btn_account"), InlineKeyboardButton("💳 شحن رصيد", callback_data="btn_deposit")],
        [InlineKeyboardButton("💸 سحب أرباح", callback_data="btn_withdraw"), InlineKeyboardButton("🔗 رابط الإحالة", callback_data="btn_referral")],
        [InlineKeyboardButton("🎁 كود هدية", callback_data="btn_gift"), InlineKeyboardButton("📜 سجل العمليات", callback_data="btn_logs")],
        [InlineKeyboardButton("💬 الدعم الفني", callback_data="btn_support"), InlineKeyboardButton("🤖 شراء البوت", callback_data="btn_buy_bot")]
    ]
    if is_admin:
        kb.append([InlineKeyboardButton("⚙️ لوحة التحكم الإدارية", callback_data="open_admin_panel")])
    return InlineKeyboardMarkup(kb)

def cancel_keyboard(callback_target="back_to_main"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء والعودة", callback_data=callback_target)]])

def admin_panel_keyboard():
    maint = "🔴 إيقاف الصيانة" if is_maintenance_active() else "🟢 تفعيل الصيانة"
    kb = [
        [InlineKeyboardButton("🎛️ خوارزمية الربح والمكافآت", callback_data="adm_algo_menu")],
        [InlineKeyboardButton("⚡ التحكم بالنمط المباشر", callback_data="adm_global_mode_menu")],
        [InlineKeyboardButton("💳 طرق وحسابات الشحن", callback_data="adm_dep_methods"), InlineKeyboardButton("📥 طلبات الشحن معلقة", callback_data="adm_deposits")],
        [InlineKeyboardButton("💸 طلبات السحب معلقة", callback_data="adm_withdraws"), InlineKeyboardButton("📊 الإحصائيات العامّة", callback_data="adm_stats")],
        [InlineKeyboardButton("➕ إضافة رصيد", callback_data="adm_add_bal"), InlineKeyboardButton("➖ خصم رصيد", callback_data="adm_sub_bal")],
        [InlineKeyboardButton("👤 الاستعلام عن مستخدم", callback_data="adm_user_info"), InlineKeyboardButton("🚀 تعزيز حساب (Boost)", callback_data="adm_user_boost")],
        [InlineKeyboardButton("🚫 حظر مستخدم", callback_data="adm_ban"), InlineKeyboardButton("🔓 فك حظر", callback_data="adm_unban")],
        [InlineKeyboardButton("🎁 إنشاء كود هدية", callback_data="adm_make_gift"), InlineKeyboardButton("📢 إدارة قنوات الاشتراك", callback_data="adm_channels_menu")],
        [InlineKeyboardButton("📢 إذاعة نصية", callback_data="adm_bc_txt"), InlineKeyboardButton("📸 إذاعة صوَرية", callback_data="adm_bc_img")],
        [InlineKeyboardButton("✉️ رسالة خاصة لمستخدم", callback_data="adm_pm_txt"), InlineKeyboardButton("📜 السجلات العامة", callback_data="adm_all_logs")],
        [InlineKeyboardButton("➕ إضافة أدمن", callback_data="adm_add_admin"), InlineKeyboardButton("➖ إزالة أدمن", callback_data="adm_del_admin")],
        [InlineKeyboardButton("⚙️ ضبط حد أدنى شحن", callback_data="adm_set_min_dep"), InlineKeyboardButton("⚙️ ضبط حد أدنى سحب", callback_data="adm_set_min_w")],
        [InlineKeyboardButton("⚙️ ضبط مكافأة إحالة", callback_data="adm_set_ref"), InlineKeyboardButton("⚙️ ضبط بونص ترحيبي", callback_data="adm_set_welcome")],
        [InlineKeyboardButton(f"{maint}", callback_data="adm_toggle_maint")],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(kb)

def algo_panel_keyboard():
    kb = [
        [InlineKeyboardButton("🎯 نسبة الربح العامة", callback_data="adm_set_win_rate"), InlineKeyboardButton("🎁 نسبة ربح المكافأة", callback_data="adm_set_bonus_win_rate")],
        [InlineKeyboardButton("🏺 سقف 1 جرة", callback_data="adm_set_bonus_cap_1"), InlineKeyboardButton("🏺🏺 سقف 2 جرة", callback_data="adm_set_bonus_cap_2")],
        [InlineKeyboardButton("🏺🏺🏺 سقف 3 جرات", callback_data="adm_set_bonus_cap_3")],
        [InlineKeyboardButton("📉 نسبة الخسارة", callback_data="adm_set_ch_loss"), InlineKeyboardButton("🥉 نسبة الربح العادي", callback_data="adm_set_ch_normal")],
        [InlineKeyboardButton("🥈 نسبة الربح المتوسط", callback_data="adm_set_ch_medium"), InlineKeyboardButton("🥇 نسبة الربح العالي", callback_data="adm_set_ch_high")],
        [InlineKeyboardButton("👑 نسبة الربح الضخم", callback_data="adm_set_ch_huge")],
        [InlineKeyboardButton("🔙 رجوع للإدارة", callback_data="open_admin_panel")]
    ]
    return InlineKeyboardMarkup(kb)

def global_mode_keyboard():
    kb = [
        [InlineKeyboardButton("🔄 تلقائي (حسب نسب الخوارزمية)", callback_data="set_gmode_auto")],
        [InlineKeyboardButton("❌ قفل خاسر دائماً (Loss Mode)", callback_data="set_gmode_loss")],
        [InlineKeyboardButton("🥉 قفل ربح عادي (حتى 5x)", callback_data="set_gmode_normal")],
        [InlineKeyboardButton("🥈 قفل ربح متوسط (حتى 10x)", callback_data="set_gmode_medium")],
        [InlineKeyboardButton("🥇 قفل ربح عالي (حتى 20x)", callback_data="set_gmode_high")],
        [InlineKeyboardButton("👑 قفل ربح ضخم (حتى 50x)", callback_data="set_gmode_huge")],
        [InlineKeyboardButton("🔙 رجوع لخوارزمية الربح", callback_data="adm_algo_menu")]
    ]
    return InlineKeyboardMarkup(kb)

async def send_main_dashboard(chat_id, user_id, full_name, is_admin, context):
    msg = (
        f"👋 **أهلاً بك يا {full_name} في بوت اللعب والأرباح!**\n\n"
        f"🎮 يمكنك استخدام القائمة أدناه لإدارة حسابك وشحن رصيدك أو البدء باللعب مباشرة المباشر عبر زر اللعبة."
    )
    await context.bot.send_message(
        chat_id=chat_id,
        text=msg,
        parse_mode="Markdown",
        reply_markup=build_main_keyboard(user_id, is_admin)
    )

# ----------------------------------------------------
# 5. معالجة أوامر البوت والتفاعل المباشر
# ----------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id

    conn = get_db()

    # فحص وضع الصيانة
    is_maint = conn.execute("SELECT value FROM settings WHERE key='maintenance_mode'").fetchone()["value"] == "1"
    is_admin = conn.execute("SELECT user_id FROM admins WHERE user_id = ?", (user.id,)).fetchone() is not None

    if is_maint and not is_admin:
        conn.close()
        await update.message.reply_text("🚧 **البوت حالياً في حالة صيانة وتحديثات. يرجى المحاولة لاحقاً!**", parse_mode="Markdown")
        return

    # تسجيل المستخدم إذا كان جديداً
    u = conn.execute("SELECT * FROM users WHERE user_id = ?", (user.id,)).fetchone()

    referred_by = None
    if context.args and len(context.args) > 0:
        try:
            ref_id = int(context.args[0])
            if ref_id != user.id:
                referred_by = ref_id
        except ValueError:
            pass

    if not u:
        welcome_bonus = float(conn.execute("SELECT value FROM settings WHERE key='welcome_bonus'").fetchone()["value"])
        conn.execute(
            "INSERT INTO users (user_id, full_name, balance, referred_by) VALUES (?, ?, ?, ?)",
            (user.id, user.full_name, welcome_bonus, referred_by)
        )
        conn.commit()

        # معالجة مكافأة الدعوة
        if referred_by:
            ref_reward = float(conn.execute("SELECT value FROM settings WHERE key='referral_reward'").fetchone()["value"])
            conn.execute("UPDATE users SET balance = balance + ?, referrals_count = referrals_count + 1 WHERE user_id = ?", (ref_reward, referred_by))
            conn.execute("INSERT INTO logs (user_id, action, amount) VALUES (?, ?, ?)", (referred_by, f"مكافأة إحالة للمستخدم {user.id}", ref_reward))
            conn.commit()
            try:
                await context.bot.send_message(referred_by, f"🎉 **انضم مستخدم جديد عبر رابطك!** تم إيداع `{ref_reward}` NSP لحسابك.", parse_mode="Markdown")
            except Exception:
                pass

    u = conn.execute("SELECT * FROM users WHERE user_id = ?", (user.id,)).fetchone()

    if u["is_banned"]:
        conn.close()
        await update.message.reply_text("🚫 **حسابك معطل ومحظر من استخدام البوت.**", parse_mode="Markdown")
        return

    # التحقق من ربط رقم الهاتف
    if not u["phone"]:
        conn.close()
        kb = ReplyKeyboardMarkup(
            [[KeyboardButton("📱 مشاركة رقم الهاتف", request_contact=True)]],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        await update.message.reply_text(
            "⚠️ **أهلاً بك! لتفعيل حسابك البدء باستخدام البوت، يرجى مشاركة رقم هاتفك عبر الزر أدناه:**",
            reply_markup=kb
        )
        return

    # التحقق من الاشتراك القسري بالقنوات
    is_sub, unsubscribed = await check_user_channels_subscription(context.bot, user.id)
    if not is_sub:
        conn.close()
        await update.message.reply_text(
            "⚠️ **يجب عليك الاشتراك في قنوات البوت التالية للاستمرار:**",
            reply_markup=build_sub_keyboard(unsubscribed)
        )
        return

    conn.close()
    await send_main_dashboard(chat_id, user.id, user.full_name, is_admin, context)

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = get_db()
    is_admin = conn.execute("SELECT user_id FROM admins WHERE user_id = ?", (user.id,)).fetchone() is not None
    conn.close()

    if is_admin:
        await update.message.reply_text("⚙️ **لوحة التحكم الإدارية الشاملة:**", parse_mode="Markdown", reply_markup=admin_panel_keyboard())
    else:
        await update.message.reply_text("❌ ليس لديك صلاحية للوصول لوظائف الأدمن.")

async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    contact = update.message.contact

    if contact.user_id != user.id:
        await update.message.reply_text("❌ يرجى مشاركة رقم الهاتف الخاص بحسابك فقط!")
        return

    conn = get_db()
    conn.execute("UPDATE users SET phone = ? WHERE user_id = ?", (contact.phone_number, user.id))
    conn.commit()

    is_admin = conn.execute("SELECT user_id FROM admins WHERE user_id = ?", (user.id,)).fetchone() is not None
    conn.close()

    await update.message.reply_text("✅ تم ربط رقم الهاتف بنجاح!", reply_markup=ReplyKeyboardRemove())
    await send_main_dashboard(update.effective_chat.id, user.id, user.full_name, is_admin, context)

# ----------------------------------------------------
# 6. معالجة الرسائل النصية الموجهة حسب الخطوات (Steps)
# ----------------------------------------------------
async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()

    conn = get_db()
    u = conn.execute("SELECT * FROM users WHERE user_id = ?", (user.id,)).fetchone()
    is_admin = conn.execute("SELECT user_id FROM admins WHERE user_id = ?", (user.id,)).fetchone() is not None

    if not u or u["is_banned"]:
        conn.close()
        return

    step = u["step"]

    # --- خطوات المستخدم العادي ---
    if step == "deposit_step_amount":
        try:
            amt = float(text)
            min_dep = float(conn.execute("SELECT value FROM settings WHERE key='min_deposit'").fetchone()["value"])
            if amt < min_dep:
                await update.message.reply_text(f"⚠️ **المبلغ أقل من الحد الأدنى للشحن ({min_dep} NSP). يرجى إدخال مبلغ أكبر:**", parse_mode="Markdown")
                conn.close()
                return

            context.user_data["dep_amount"] = amt
            conn.execute("UPDATE users SET step = 'deposit_step_tx' WHERE user_id = ?", (user.id,))
            conn.commit()
            conn.close()

            await update.message.reply_text(
                "🔢 **يرجى إرسال رقم العملية / الإشعار الآن (أو أرسل صورة الإشعار):**",
                reply_markup=cancel_keyboard("btn_deposit")
            )
            return
        except ValueError:
            conn.close()
            await update.message.reply_text("⚠️ يرجى إدخال مبلغ صحيح بالأرقام فقط!")
            return

    elif step == "deposit_step_tx":
        method = context.user_data.get("dep_method", "غير محدد")
        amt = context.user_data.get("dep_amount", 0.0)

        conn.execute(
            "INSERT INTO deposits (user_id, method, amount, tx_id) VALUES (?, ?, ?, ?)",
            (user.id, method, amt, text)
        )
        conn.execute("UPDATE users SET step = 'main' WHERE user_id = ?", (user.id,))
        conn.commit()
        conn.close()

        await update.message.reply_text("✅ **تم رفع طلب الشحن بنجاح! سينظر الإشراف في طلبك في أقرب وقت.**", parse_mode="Markdown")
        return

    elif step == "withdraw_step_code":
        context.user_data["withdraw_code"] = text
        conn.execute("UPDATE users SET step = 'withdraw_step_amount' WHERE user_id = ?", (user.id,))
        conn.commit()
        conn.close()
        await update.message.reply_text("✍️ **أدخل المبلغ المراد سحبه (NSP):**", reply_markup=cancel_keyboard("btn_withdraw"))
        return

    elif step == "withdraw_step_amount":
        try:
            amt = float(text)
            min_w = float(conn.execute("SELECT value FROM settings WHERE key='min_withdraw'").fetchone()["value"])
            
            if amt < min_w:
                await update.message.reply_text(f"⚠️ **المبلغ أقل من الحد الأدنى للسحب ({min_w} NSP).**", parse_mode="Markdown")
                conn.close()
                return

            if amt > u["balance"]:
                await update.message.reply_text("⚠️ **رصيدك الحالي غير كافٍ لإتمام هذه العملية!**", parse_mode="Markdown")
                conn.close()
                return

            method = context.user_data.get("withdraw_method", "غير محدد")
            code = context.user_data.get("withdraw_code", "")

            conn.execute("UPDATE users SET balance = balance - ?, step = 'main' WHERE user_id = ?", (amt, user.id))
            conn.execute(
                "INSERT INTO withdrawals (user_id, method, amount, account_code) VALUES (?, ?, ?, ?)",
                (user.id, method, amt, code)
            )
            conn.execute("INSERT INTO logs (user_id, action, amount) VALUES (?, ?, ?)", (user.id, f"طلب سحب ({method})", amt))
            conn.commit()
            conn.close()

            await update.message.reply_text("✅ **تم تقديم طلب السحب بنجاح وخصم المبلغ من رصيدك المتاح.**", parse_mode="Markdown")
            return
        except ValueError:
            conn.close()
            await update.message.reply_text("⚠️ يرجى إدخال مبلغ صحيح!")
            return

    elif step == "input_gift_code":
        g = conn.execute("SELECT * FROM gifts WHERE code = ?", (text,)).fetchone()
        if not g:
            conn.close()
            await update.message.reply_text("❌ **كود الهدية غير صحيح أو غير موجود!**", parse_mode="Markdown")
            return

        if g["used_count"] >= g["max_uses"]:
            conn.close()
            await update.message.reply_text("⚠️ **عذراً، هذا الكود استنفذ كامل مرات الاستخدام المتاحة!**", parse_mode="Markdown")
            return

        conn.execute("UPDATE gifts SET used_count = used_count + 1 WHERE code = ?", (text,))
        conn.execute("UPDATE users SET balance = balance + ?, step = 'main' WHERE user_id = ?", (g["amount"], user.id))
        conn.execute("INSERT INTO logs (user_id, action, amount) VALUES (?, ?, ?)", (user.id, f"استخدام كود هدية ({text})", g["amount"]))
        conn.commit()
        conn.close()

        await update.message.reply_text(f"🎉 **مبروك! تم شحن `{g['amount']}` NSP لرصيدك بنجاح.**", parse_mode="Markdown")
        return

    elif step == "input_support_msg":
        conn.execute("UPDATE users SET step = 'main' WHERE user_id = ?", (user.id,))
        conn.commit()
        conn.close()

        for admin_id in ADMIN_IDS:
            try:
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("💬 رد على الرسالة", callback_data=f"adm_rep_supp_{user.id}")]])
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"💬 **رسالة دعم جديدة:**\n👤 **المرسل:** {user.full_name} (`{user.id}`)\n\n📝 **النص:**\n{text}",
                    parse_mode="Markdown",
                    reply_markup=kb
                )
            except Exception:
                pass

        await update.message.reply_text("✅ **وصلت رسالتك لفريق الدعم، سيتم الرد عليك في أقرب وقت ممكن.**", parse_mode="Markdown")
        return

    # --- خطوات لوحة الأدمن ---
    if is_admin:
        if step == "adm_input_add_dep_name":
            context.user_data["new_dep_name"] = text
            conn.execute("UPDATE users SET step = 'adm_input_add_dep_acc' WHERE user_id = ?", (user.id,))
            conn.commit()
            conn.close()
            await update.message.reply_text("✍️ **أدخل الآن تفاصيل الحساب / الرقم للتحويل إليها:**", reply_markup=cancel_keyboard("adm_dep_methods"))
            return

        elif step == "adm_input_add_dep_acc":
            m_name = context.user_data.get("new_dep_name", "غير محدد")
            conn.execute("INSERT INTO deposit_methods (method_name, account_details) VALUES (?, ?)", (m_name, text))
            conn.execute("UPDATE users SET step = 'main' WHERE user_id = ?", (user.id,))
            conn.commit()
            conn.close()
            await update.message.reply_text("✅ تم إضافة طريقة الشحن الجديدة بنجاح!")
            return

        elif step == "adm_input_set_min_dep":
            try:
                val = str(float(text))
                conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('min_deposit', ?)", (val,))
                conn.execute("UPDATE users SET step = 'main' WHERE user_id = ?", (user.id,))
                conn.commit()
                conn.close()
                await update.message.reply_text(f"✅ تم تعديل الحد الأدنى للشحن إلى: `{val}` NSP", parse_mode="Markdown")
                return
            except ValueError:
                conn.close()
                await update.message.reply_text("⚠️ يرجى إدخال قيمة رقمية صحيحة!")
                return

        elif step == "adm_input_support_reply":
            target_id = context.user_data.get("support_target_id")
            conn.execute("UPDATE users SET step = 'main' WHERE user_id = ?", (user.id,))
            conn.commit()
            conn.close()

            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text=f"💬 **رد الدعم الفني:**\n\n{text}",
                    parse_mode="Markdown"
                )
                await update.message.reply_text(f"✅ تم إرسال الرد للمستخدم `{target_id}` بنجاح.", parse_mode="Markdown")
            except Exception as e:
                await update.message.reply_text(f"❌ فشل إرسال الرد للمستخدم: {e}")
            return

        elif step.startswith("adm_set_"):
            setting_key = step.replace("adm_set_", "")
            try:
                val = str(float(text))
                conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (setting_key, val))
                conn.execute("UPDATE users SET step = 'main' WHERE user_id = ?", (user.id,))
                conn.commit()
                conn.close()
                await update.message.reply_text(f"✅ تم تعديل الإعداد `{setting_key}` إلى `{val}` بنجاح.", parse_mode="Markdown")
                return
            except ValueError:
                conn.close()
                await update.message.reply_text("⚠️ أدخل قيمة رقمية صحيحة!")
                return

        elif step == "adm_input_add_admin":
            try:
                aid = int(text)
                conn.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (aid,))
                conn.execute("UPDATE users SET step = 'main' WHERE user_id = ?", (user.id,))
                conn.commit()
                conn.close()
                await update.message.reply_text(f"✅ تم إضافة المستخدم `{aid}` كأدمن.", parse_mode="Markdown")
                return
            except ValueError:
                conn.close()
                await update.message.reply_text("⚠️ أدخل ID رقمي صحيح!")
                return

        elif step == "adm_input_del_admin":
            try:
                aid = int(text)
                conn.execute("DELETE FROM admins WHERE user_id = ?", (aid,))
                conn.execute("UPDATE users SET step = 'main' WHERE user_id = ?", (user.id,))
                conn.commit()
                conn.close()
                await update.message.reply_text(f"✅ تم إزالة المستخدم `{aid}` من الإدارة.", parse_mode="Markdown")
                return
            except ValueError:
                conn.close()
                await update.message.reply_text("⚠️ أدخل ID رقمي صحيح!")
                return

        elif step == "adm_input_add_ch_id":
            context.user_data["new_ch_id"] = text
            conn.execute("UPDATE users SET step = 'adm_input_add_ch_title' WHERE user_id = ?", (user.id,))
            conn.commit()
            conn.close()
            await update.message.reply_text("✍️ **أدخل اسم/عنوان القناة الظاهر للمستخدمين:**")
            return

        elif step == "adm_input_add_ch_title":
            context.user_data["new_ch_title"] = text
            conn.execute("UPDATE users SET step = 'adm_input_add_ch_link' WHERE user_id = ?", (user.id,))
            conn.commit()
            conn.close()
            await update.message.reply_text("✍️ **أدخل رابط الدعوة الخاص بالقناة:**")
            return

        elif step == "adm_input_add_ch_link":
            ch_id = context.user_data.get("new_ch_id")
            ch_title = context.user_data.get("new_ch_title")
            conn.execute("INSERT OR REPLACE INTO channels (channel_id, channel_title, invite_link) VALUES (?, ?, ?)", (ch_id, ch_title, text))
            conn.execute("UPDATE users SET step = 'main' WHERE user_id = ?", (user.id,))
            conn.commit()
            conn.close()
            await update.message.reply_text("✅ تم إضافة القناة لقائمة الاشتراك الإجباري بنجاح!")
            return

        elif step == "adm_input_add_bal":
            parts = text.split()
            if len(parts) == 2:
                try:
                    tid, amt = int(parts[0]), float(parts[1])
                    conn.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amt, tid))
                    conn.execute("INSERT INTO logs (user_id, action, amount) VALUES (?, ?, ?)", (tid, "إضافة رصيد بواسطة الأدمن", amt))
                    conn.execute("UPDATE users SET step = 'main' WHERE user_id = ?", (user.id,))
                    conn.commit()
                    conn.close()
                    await update.message.reply_text(f"✅ تم إضافة `{amt}` NSP لرصيد المستخدم `{tid}`.", parse_mode="Markdown")
                    try:
                        await context.bot.send_message(tid, f"🎁 تم إضافة `{amt}` NSP لحسابك بواسطة الإدارة!")
                    except Exception:
                        pass
                    return
                except ValueError:
                    pass
            conn.close()
            await update.message.reply_text("⚠️ الصيغة خاطئة! استخدم: `ID المبلغ`", parse_mode="Markdown")
            return

        elif step == "adm_input_sub_bal":
            parts = text.split()
            if len(parts) == 2:
                try:
                    tid, amt = int(parts[0]), float(parts[1])
                    conn.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amt, tid))
                    conn.execute("INSERT INTO logs (user_id, action, amount) VALUES (?, ?, ?)", (tid, "خصم رصيد بواسطة الأدمن", amt))
                    conn.execute("UPDATE users SET step = 'main' WHERE user_id = ?", (user.id,))
                    conn.commit()
                    conn.close()
                    await update.message.reply_text(f"✅ تم خصم `{amt}` NSP من رصيد المستخدم `{tid}`.", parse_mode="Markdown")
                    return
                except ValueError:
                    pass
            conn.close()
            await update.message.reply_text("⚠️ الصيغة خاطئة! استخدم: `ID المبلغ`", parse_mode="Markdown")
            return

        elif step == "adm_input_make_gift":
            parts = text.split()
            if len(parts) == 3:
                try:
                    code, amt, uses = parts[0], float(parts[1]), int(parts[2])
                    conn.execute("INSERT OR REPLACE INTO gifts (code, amount, max_uses) VALUES (?, ?, ?)", (code, amt, uses))
                    conn.execute("UPDATE users SET step = 'main' WHERE user_id = ?", (user.id,))
                    conn.commit()
                    conn.close()
                    await update.message.reply_text(f"✅ تم إنشاء كود الهدية `{code}` بقيمة `{amt}` ولعدد `{uses}` استخدامات.", parse_mode="Markdown")
                    return
                except ValueError:
                    pass
            conn.close()
            await update.message.reply_text("⚠️ الصيغة خاطئة! استخدم: `الكود المبلغ عدد_المرات`", parse_mode="Markdown")
            return

        elif step == "adm_input_set_ref":
            try:
                val = str(float(text))
                conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('referral_reward', ?)", (val,))
                conn.execute("UPDATE users SET step = 'main' WHERE user_id = ?", (user.id,))
                conn.commit()
                conn.close()
                await update.message.reply_text(f"✅ تم تعديل مكافأة الإحالة إلى: `{val}` NSP", parse_mode="Markdown")
                return
            except ValueError:
                conn.close()
                await update.message.reply_text("⚠️ أدخل قيمة رقمية صحيحة!")
                return

        elif step == "adm_input_set_min_w":
            try:
                val = str(float(text))
                conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('min_withdraw', ?)", (val,))
                conn.execute("UPDATE users SET step = 'main' WHERE user_id = ?", (user.id,))
                conn.commit()
                conn.close()
                await update.message.reply_text(f"✅ تم تعديل الحد الأدنى للسحب إلى: `{val}` NSP", parse_mode="Markdown")
                return
            except ValueError:
                conn.close()
                await update.message.reply_text("⚠️ أدخل قيمة رقمية صحيحة!")
                return

        elif step == "adm_input_set_welcome":
            try:
                val = str(float(text))
                conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('welcome_bonus', ?)", (val,))
                conn.execute("UPDATE users SET step = 'main' WHERE user_id = ?", (user.id,))
                conn.commit()
                conn.close()
                await update.message.reply_text(f"✅ تم تعديل البونص الترحيبي إلى: `{val}` NSP", parse_mode="Markdown")
                return
            except ValueError:
                conn.close()
                await update.message.reply_text("⚠️ أدخل قيمة رقمية صحيحة!")
                return

        elif step == "adm_input_user_info":
            try:
                tid = int(text)
                usr = conn.execute("SELECT * FROM users WHERE user_id = ?", (tid,)).fetchone()
                conn.close()
                if not usr:
                    await update.message.reply_text("❌ لم يتم العثور على هذا المستخدم.")
                    return
                msg = (
                    f"👤 **معلومات المستخدم (`{usr['user_id']}`):**\n\n"
                    f"• **الاسم:** {usr['full_name']}\n"
                    f"• **الهاتف:** `{usr['phone'] or 'غير مرتبط'}`\n"
                    f"• **الرصيد:** `{usr['balance']:,.2f}` NSP\n"
                    f"• **الإحالات:** `{usr['referrals_count']}`\n"
                    f"• **عدد المرات:** `{usr['games_played']}`\n"
                    f"• **محظور؟:** `{'نعم' if usr['is_banned'] else 'لا'}`"
                )
                await update.message.reply_text(msg, parse_mode="Markdown")
                return
            except ValueError:
                conn.close()
                await update.message.reply_text("⚠️ أدخل ID رقمي صحيح!")
                return

        elif step == "adm_input_ban":
            try:
                tid = int(text)
                conn.execute("UPDATE users SET is_banned = 1, step = 'main' WHERE user_id = ?", (tid,))
                conn.commit()
                conn.close()
                await update.message.reply_text(f"✅ تم حظر المستخدم `{tid}`.", parse_mode="Markdown")
                return
            except ValueError:
                conn.close()
                await update.message.reply_text("⚠️ أدخل ID رقمي صحيح!")
                return

        elif step == "adm_input_unban":
            try:
                tid = int(text)
                conn.execute("UPDATE users SET is_banned = 0, step = 'main' WHERE user_id = ?", (tid,))
                conn.commit()
                conn.close()
                await update.message.reply_text(f"✅ تم فك حظر المستخدم `{tid}`.", parse_mode="Markdown")
                return
            except ValueError:
                conn.close()
                await update.message.reply_text("⚠️ أدخل ID رقمي صحيح!")
                return

        elif step == "adm_input_bc_txt":
            users = conn.execute("SELECT user_id FROM users WHERE is_banned = 0").fetchall()
            conn.execute("UPDATE users SET step = 'main' WHERE user_id = ?", (user.id,))
            conn.commit()
            conn.close()

            succ, fail = 0, 0
            for u_row in users:
                try:
                    await context.bot.send_message(u_row["user_id"], text, parse_mode="Markdown")
                    succ += 1
                except Exception:
                    fail += 1

            await update.message.reply_text(f"📢 **إنهاء الإذاعة النصية:**\n✅ 성공: `{succ}`\n❌ فشل: `{fail}`", parse_mode="Markdown")
            return

        elif step == "adm_input_pm_txt":
            parts = text.split(" ", 1)
            if len(parts) == 2:
                try:
                    tid, pmsg = int(parts[0]), parts[1]
                    conn.execute("UPDATE users SET step = 'main' WHERE user_id = ?", (user.id,))
                    conn.commit()
                    conn.close()
                    await context.bot.send_message(tid, f"📩 **رسالة خاصة من الإدارة:**\n\n{pmsg}", parse_mode="Markdown")
                    await update.message.reply_text(f"✅ تم إرسال الرسالة للمستخدم `{tid}`.", parse_mode="Markdown")
                    return
                except Exception as e:
                    await update.message.reply_text(f"❌ فشل إرسال الرسالة: {e}")
                    return
            conn.close()
            await update.message.reply_text("⚠️ الصيغة خاطئة! استخدم: `ID النص`", parse_mode="Markdown")
            return

    conn.close()

async def handle_photo_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = get_db()
    u = conn.execute("SELECT * FROM users WHERE user_id = ?", (user.id,)).fetchone()
    is_admin = conn.execute("SELECT user_id FROM admins WHERE user_id = ?", (user.id,)).fetchone() is not None

    if not u or u["is_banned"]:
        conn.close()
        return

    step = u["step"]

    if step == "deposit_step_tx":
        photo_id = update.message.photo[-1].file_id
        caption = update.message.caption or "صورة إشعار"
        method = context.user_data.get("dep_method", "غير محدد")
        amt = context.user_data.get("dep_amount", 0.0)

        conn.execute(
            "INSERT INTO deposits (user_id, method, amount, tx_id, photo_file_id) VALUES (?, ?, ?, ?, ?)",
            (user.id, method, amt, caption, photo_id)
        )
        conn.execute("UPDATE users SET step = 'main' WHERE user_id = ?", (user.id,))
        conn.commit()
        conn.close()

        await update.message.reply_text("✅ **تم رفع صورة الإشعار وطلب الشحن بنجاح!**", parse_mode="Markdown")
        return

    if is_admin and step == "adm_input_bc_img":
        photo_id = update.message.photo[-1].file_id
        caption = update.message.caption or ""
        users = conn.execute("SELECT user_id FROM users WHERE is_banned = 0").fetchall()
        conn.execute("UPDATE users SET step = 'main' WHERE user_id = ?", (user.id,))
        conn.commit()
        conn.close()

        succ, fail = 0, 0
        for u_row in users:
            try:
                await context.bot.send_photo(chat_id=u_row["user_id"], photo=photo_id, caption=caption, parse_mode="Markdown")
                succ += 1
            except Exception:
                fail += 1

        await update.message.reply_text(f"📸 **إنهاء الإذاعة الصورية:**\n✅ 성공: `{succ}`\n❌ فشل: `{fail}`", parse_mode="Markdown")
        return

    conn.close()

# ----------------------------------------------------
# 7. معالجة النقرات (Callback Queries)
# ----------------------------------------------------
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    data = query.data

    if data == "check_subscription_status":
        is_sub, unsubscribed = await check_user_channels_subscription(context.bot, user.id)
        if is_sub:
            await query.message.delete()
            await query.message.reply_text("✅ شكرًا لاشتراكك!")
            conn = get_db()
            is_admin = conn.execute("SELECT user_id FROM admins WHERE user_id = ?", (user.id,)).fetchone() is not None
            conn.close()
            await send_main_dashboard(query.message.chat_id, user.id, user.full_name, is_admin, context)
        else:
            await query.message.edit_text(
                "⚠️ **يرجى الاشتراك بالقنوات أولاً:**",
                reply_markup=build_sub_keyboard(unsubscribed),
                parse_mode="Markdown"
            )
        return

    conn = get_db()
    
    # إعادة ضبط أي خطوة مؤقتة للمستخدم عند الرجوع
    conn.execute("UPDATE users SET step = 'main' WHERE user_id = ?", (user.id,))
    conn.commit()

    u = conn.execute("SELECT * FROM users WHERE user_id = ?", (user.id,)).fetchone()
    is_admin = conn.execute("SELECT user_id FROM admins WHERE user_id = ?", (user.id,)).fetchone() is not None

    if not u or u["is_banned"]:
        conn.close()
        return

    if data == "back_to_main":
        conn.close()
        await send_main_dashboard(query.message.chat_id, user.id, user.full_name, is_admin, context)
        return

    if data == "btn_account":
        msg = (
            f"👤 **بيانات حسابك الشخصي:**\n"
            f"✨ ─────────────────── ✨\n"
            f"✏️ **الاسم:** {u['full_name']}\n"
            f"🆔 **ID:** `{u['user_id']}`\n"
            f"📱 **الهاتف:** `{u['phone'] or 'غير مرتبط'}`\n"
            f"💰 **الرصيد:** `{u['balance']:,.2f}` NSP\n"
            f"👥 **الإحالات:** `{u['referrals_count']}`\n"
            f"🎮 **الضربات:** `{u['games_played']}`\n"
            f"✨ ─────────────────── ✨"
        )
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="back_to_main")]])
        await query.message.edit_text(msg, parse_mode="Markdown", reply_markup=kb)
        conn.close()
        return

    if data == "btn_deposit":
        min_dep = conn.execute("SELECT value FROM settings WHERE key='min_deposit'").fetchone()["value"]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📱 سيريتل كاش", callback_data="dep_meth_Syriatel Cash")],
            [InlineKeyboardButton("📱 إم تي إن كاش", callback_data="dep_meth_MTN Cash")],
            [InlineKeyboardButton("💳 شام كاش", callback_data="dep_meth_Bank Cham Cash")],
            [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="back_to_main")]
        ])
        await query.message.edit_text(
            f"💳 **قسم شحن الرصيد:**\n\n"
            f"💰 **الحد الأدنى للشحن:** `{min_dep}` NSP\n\n"
            f"اختر طريقة الشحن المناسبة لك:",
            parse_mode="Markdown",
            reply_markup=kb
        )
        conn.close()
        return

    if data.startswith("dep_meth_"):
        method_name = data.replace("dep_meth_", "")
        acc = conn.execute("SELECT * FROM deposit_methods WHERE method_name LIKE ?", (f"%{method_name}%",)).fetchone()
        
        if not acc:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="btn_deposit")]])
            await query.message.edit_text(f"⏳ **طريقة الشحن عن طريق ({method_name}) غير متوفرة حالياً (قريباً!).**", reply_markup=kb)
            conn.close()
            return

        context.user_data["dep_method"] = acc["method_name"]
        min_dep = conn.execute("SELECT value FROM settings WHERE key='min_deposit'").fetchone()["value"]
        
        conn.execute("UPDATE users SET step = 'deposit_step_amount' WHERE user_id = ?", (user.id,))
        conn.commit()
        conn.close()

        msg = (
            f"💳 **شحن عبر {acc['method_name']}**\n\n"
            f"📌 **يرجى التحويل إلى الحساب التالي:**\n"
            f"`{acc['account_details']}`\n\n"
            f"✍️ **أدخل المبلغ المراد شحنه (NSP):**\n"
            f"⚠️ **الحد الأدنى للشحن:** `{min_dep}` NSP"
        )
        await query.message.edit_text(msg, parse_mode="Markdown", reply_markup=cancel_keyboard("btn_deposit"))
        return

    if data == "btn_withdraw":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📱 سيريتل كاش", callback_data="w_meth_Syriatel Cash")],
            [InlineKeyboardButton("📱 إم تي إن كاش", callback_data="w_meth_MTN Cash")],
            [InlineKeyboardButton("💳 شام كاش", callback_data="w_meth_Bank Cham Cash")],
            [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="back_to_main")]
        ])
        min_w = conn.execute("SELECT value FROM settings WHERE key='min_withdraw'").fetchone()["value"]
        await query.message.edit_text(
            f"💸 **قسم سحب الأرباح:**\n\n"
            f"💰 **رصيدك:** `{u['balance']:,.2f}` NSP\n"
            f"⚠️ **الحد الأدنى:** `{min_w}` NSP\n\n"
            f"اختر وسيلة السحب:",
            parse_mode="Markdown",
            reply_markup=kb
        )
        conn.close()
        return

    if data.startswith("w_meth_"):
        method = data.replace("w_meth_", "")
        context.user_data["withdraw_method"] = method
        conn.execute("UPDATE users SET step = 'withdraw_step_code' WHERE user_id = ?", (user.id,))
        conn.commit()
        conn.close()
        await query.message.edit_text(f"✍️ **الطريقة:** {method}\n\nأدخل رقم الحساب أو المحفظة المراد التحويل إليها:", reply_markup=cancel_keyboard("btn_withdraw"))
        return

    if data == "btn_referral":
        ref_reward = conn.execute("SELECT value FROM settings WHERE key='referral_reward'").fetchone()["value"]
        bot_info = await context.bot.get_me()
        ref_link = f"https://t.me/{bot_info.username}?start={user.id}"
        
        msg = (
            f"🔗 **نظام الإحالة:**\n"
            f"✨ ─────────────────── ✨\n"
            f"احصل على `{ref_reward}` NSP عن كل صديق يسجل عبر رابطك!\n\n"
            f"👥 **عدد إحالاتك:** `{u['referrals_count']}`\n"
            f"🔗 **رابط الدعوة الخاص بك:**\n`{ref_link}`\n"
            f"✨ ─────────────────── ✨"
        )
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="back_to_main")]])
        await query.message.edit_text(msg, parse_mode="Markdown", reply_markup=kb)
        conn.close()
        return

    if data == "btn_gift":
        conn.execute("UPDATE users SET step = 'input_gift_code' WHERE user_id = ?", (user.id,))
        conn.commit()
        conn.close()
        await query.message.edit_text("🎁 **أدخل كود الهدية الخاص بك:**", reply_markup=cancel_keyboard("back_to_main"))
        return

    if data == "btn_logs":
        logs = conn.execute("SELECT action, amount, timestamp FROM logs WHERE user_id = ? ORDER BY id DESC LIMIT 10", (user.id,)).fetchall()
        conn.close()
        
        if not logs:
            txt = "📜 لا توجد سجلات حالياً."
        else:
            txt = "📜 **آخر 10 عمليات خاصة بحسابك:**\n\n"
            for lg in logs:
                txt += f"• `{lg['timestamp']}` | {lg['action']} | `{lg['amount']}` NSP\n"
                
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="back_to_main")]])
        await query.message.edit_text(txt, parse_mode="Markdown", reply_markup=kb)
        return

    if data == "btn_support":
        conn.execute("UPDATE users SET step = 'input_support_msg' WHERE user_id = ?", (user.id,))
        conn.commit()
        conn.close()
        await query.message.edit_text("💬 **اكتب رسالتك وستصل لفريق الدعم الفني فوراً:**", reply_markup=cancel_keyboard("back_to_main"))
        return

    if data == "btn_buy_bot":
        conn.close()
        msg = (
            "🤖 **لشراء بوتك الخاص وتجهيز سيرفرك تواصل مع المبرمج:**\n\n"
            "📢 **قناة المبرمج الرسمية:** @lerafree"
        )
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="back_to_main")]])
        await query.message.edit_text(msg, parse_mode="Markdown", reply_markup=kb)
        return

    # ----------------------------------------------------
    # لوحة المشرفين
    # ----------------------------------------------------
    if is_admin:
        if data == "open_admin_panel":
            conn.close()
            await query.message.edit_text("⚙️ **لوحة التحكم الإدارية الشاملة:**", parse_mode="Markdown", reply_markup=admin_panel_keyboard())
            return

        if data == "adm_toggle_maint":
            current = is_maintenance_active()
            new_val = "0" if current else "1"
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('maintenance_mode', ?)", (new_val,))
            conn.commit()
            conn.close()
            await query.message.edit_text("⚙️ **لوحة التحكم الإدارية الشاملة:**", parse_mode="Markdown", reply_markup=admin_panel_keyboard())
            return

        if data == "adm_algo_menu":
            settings = dict(conn.execute("SELECT key, value FROM settings").fetchall())
            conn.close()

            mode_map = {
                "auto": "🔄 تلقائي (حسب نسب الاحتمالات)",
                "loss": "❌ قفل خاسر دائماً (Loss Mode)",
                "normal": "🥉 قفل ربح عادي (حتى 5x)",
                "medium": "🥈 قفل ربح متوسط (حتى 10x)",
                "high": "🥇 قفل ربح عالي (حتى 20x)",
                "huge": "👑 قفل ربح ضخم (حتى 50x)"
            }
            current_mode = mode_map.get(settings.get('global_win_mode', 'auto'), "🔄 تلقائي")

            msg = (
                "🎛️ **لوحة تحكم خوارزميات الربح والمكافآت المحدثة:**\n\n"
                f"⚡ **النمط المباشر المفعّل:** `{current_mode}`\n"
                f"-----------------------------------\n"
                f"🎯 نسبة الربح العامة: `{settings.get('win_rate', 30)}%`\n"
                f"🎁 نسبة ربح شراء المكافأة: `{settings.get('bonus_win_rate', 40)}%`\n"
                f"🏺 سقف 1 جرة (فئة 3): `{settings.get('bonus_cap_1', 200)}` NSP\n"
                f"🏺🏺 سقف 2 جرة (فئة 3): `{settings.get('bonus_cap_2', 500)}` NSP\n"
                f"🏺🏺🏺 سقف 3 جرات (فئة 3): `{settings.get('bonus_cap_3', 1000)}` NSP\n"
                f"-----------------------------------\n"
                f"📉 نسبة الخسارة: `{settings.get('chance_loss', 50)}%`\n"
                f"🥉 نسبة الربح العادي (حتى 5x): `{settings.get('chance_normal', 30)}%`\n"
                f"🥈 نسبة الربح المتوسط (حتى 10x): `{settings.get('chance_medium', 12)}%`\n"
                f"🥇 نسبة الربح العالي (حتى 20x): `{settings.get('chance_high', 6)}%`\n"
                f"👑 نسبة الربح الضخم (حتى 50x): `{settings.get('chance_huge', 2)}%`\n\n"
                "اختر الخيار المراد تعديله من الأزرار أدناه:"
            )
            await query.message.edit_text(msg, parse_mode="Markdown", reply_markup=algo_panel_keyboard())
            return

        if data == "adm_global_mode_menu":
            conn.close()
            await query.message.edit_text(
                "⚡ **التحكم المباشر بنمط السيرفر:**\n\n"
                "يمكنك قفل جميع أدوار السيرفر فورياً على نمط ربح أو خسارة محدد، أو تركه يعمل تلقائياً حسب نسب الخوارزمية.",
                parse_mode="Markdown",
                reply_markup=global_mode_keyboard()
            )
            return

        if data.startswith("set_gmode_"):
            new_mode = data.replace("set_gmode_", "")
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('global_win_mode', ?)", (new_mode,))
            conn.commit()
            conn.close()

            names = {
                "auto": "تلقائي (حسب نسب الخوارزمية)",
                "loss": "خسارة دائمة",
                "normal": "ربح عادي (حتى 5x)",
                "medium": "ربح متوسط (حتى 10x)",
                "high": "ربح عالي (حتى 20x)",
                "huge": "ربح ضخم (حتى 50x)"
            }
            await query.message.edit_text(
                f"✅ تم تغيير النمط المباشر للعب بنجاح إلى: **{names.get(new_mode, new_mode)}**",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع لخوارزمية الربح", callback_data="adm_algo_menu")]])
            )
            return

        if data == "adm_dep_methods":
            dep_accs = conn.execute("SELECT * FROM deposit_methods").fetchall()
            kb = [[InlineKeyboardButton("➕ إضافة حساب شحن جديد", callback_data="adm_add_dep_acc")]]
            for acc in dep_accs:
                kb.append([InlineKeyboardButton(f"❌ حذف: {acc['method_name']}", callback_data=f"adm_del_dep_{acc['id']}")])
            kb.append([InlineKeyboardButton("🔙 رجوع للإدارة", callback_data="open_admin_panel")])
            
            await query.message.edit_text("💳 **إدارة حسابات الشحن:**", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
            conn.close()
            return

        if data == "adm_add_dep_acc":
            conn.execute("UPDATE users SET step = 'adm_input_add_dep_name' WHERE user_id = ?", (user.id,))
            conn.commit()
            conn.close()
            await query.message.edit_text("✍️ **أدخل اسم طريقة الشحن (مثال: سيريتل كاش):**", reply_markup=cancel_keyboard("adm_dep_methods"))
            return

        if data.startswith("adm_del_dep_"):
            dep_id = int(data.replace("adm_del_dep_", ""))
            conn.execute("DELETE FROM deposit_methods WHERE id = ?", (dep_id,))
            conn.commit()
            conn.close()
            await query.message.edit_text("✅ تم حذف حساب الشحن.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_dep_methods")]]))
            return

        if data == "adm_set_min_dep":
            conn.execute("UPDATE users SET step = 'adm_input_set_min_dep' WHERE user_id = ?", (user.id,))
            conn.commit()
            conn.close()
            await query.message.edit_text("✍️ **أدخل الحد الأدنى المسموح به للشحن (NSP):**", reply_markup=cancel_keyboard("open_admin_panel"))
            return

        if data == "adm_deposits":
            pending = conn.execute("SELECT * FROM deposits WHERE status = 'pending' ORDER BY id DESC LIMIT 10").fetchall()
            conn.close()
            
            if not pending:
                await query.message.edit_text("📥 لا توجد طلبات شحن معلقة حالياً.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="open_admin_panel")]]))
                return

            for dep in pending:
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ موافقة وتعبئة", callback_data=f"app_dep_{dep['id']}"), InlineKeyboardButton("❌ رفض الطلب", callback_data=f"rej_dep_{dep['id']}")]
                ])
                txt = (
                    f"📥 **طلب شحن (# {dep['id']}):**\n"
                    f"🆔 **ID العميل:** `{dep['user_id']}`\n"
                    f"💳 **الطريقة:** {dep['method']}\n"
                    f"🔢 **رقم العملية/الإشعار:** `{dep['tx_id']}`\n"
                    f"💰 **المبلغ:** `{dep['amount']}` NSP"
                )
                if dep["photo_file_id"]:
                    try:
                        await context.bot.send_photo(chat_id=user.id, photo=dep["photo_file_id"], caption=txt, parse_mode="Markdown", reply_markup=kb)
                    except Exception:
                        await context.bot.send_message(chat_id=user.id, text=txt, parse_mode="Markdown", reply_markup=kb)
                else:
                    await context.bot.send_message(chat_id=user.id, text=txt, parse_mode="Markdown", reply_markup=kb)
            return

        if data.startswith("app_dep_"):
            dep_id = int(data.replace("app_dep_", ""))
            dep = conn.execute("SELECT * FROM deposits WHERE id = ?", (dep_id,)).fetchone()
            if dep and dep["status"] == "pending":
                conn.execute("UPDATE deposits SET status = 'approved' WHERE id = ?", (dep_id,))
                conn.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (dep["amount"], dep["user_id"]))
                conn.execute("INSERT INTO logs (user_id, action, amount) VALUES (?, ?, ?)", (dep["user_id"], f"شحن رصيد ({dep['method']})", dep["amount"]))
                conn.commit()
                await query.message.edit_text(f"✅ تم الموافقة على طلب الشحن #{dep_id} وتعبئة `{dep['amount']}` NSP לרصيد العميل.")
                try: 
                    await context.bot.send_message(dep["user_id"], f"🎉 تم الموافقة على طلب الشحن وإضافة `{dep['amount']}` NSP لرصيدك!")
                except Exception: 
                    pass
            conn.close()
            return

        if data.startswith("rej_dep_"):
            dep_id = int(data.replace("rej_dep_", ""))
            dep = conn.execute("SELECT * FROM deposits WHERE id = ?", (dep_id,)).fetchone()
            if dep and dep["status"] == "pending":
                conn.execute("UPDATE deposits SET status = 'rejected' WHERE id = ?", (dep_id,))
                conn.commit()
                await query.message.edit_text(f"❌ تم رفض طلب الشحن #{dep_id}.")
                try: 
                    await context.bot.send_message(dep["user_id"], f"❌ تم رفض طلب الشحن الخاص بك.")
                except Exception: 
                    pass
            conn.close()
            return

        if data.startswith("adm_rep_supp_"):
            target_id = data.replace("adm_rep_supp_", "")
            context.user_data["support_target_id"] = target_id
            conn.execute("UPDATE users SET step = 'adm_input_support_reply' WHERE user_id = ?", (user.id,))
            conn.commit()
            conn.close()
            await query.message.edit_text(f"✍️ **أدخل نص الرد على العميل (`{target_id}`):**", reply_markup=cancel_keyboard("open_admin_panel"))
            return

        algo_steps = [
            "adm_set_win_rate", "adm_set_bonus_win_rate", 
            "adm_set_bonus_cap_1", "adm_set_bonus_cap_2", "adm_set_bonus_cap_3",
            "adm_set_ch_loss", "adm_set_ch_normal", "adm_set_ch_medium", "adm_set_ch_high", "adm_set_ch_huge"
        ]
        if data in algo_steps:
            conn.execute("UPDATE users SET step = ? WHERE user_id = ?", (data, user.id))
            conn.commit()
            conn.close()
            
            prompts = {
                "adm_set_win_rate": "✍️ أرسل نسبة الربح العامة الجديدة (0 إلى 100):",
                "adm_set_bonus_win_rate": "✍️ أرسل نسبة الربح الجديدة عند شراء المكافأة (0 إلى 100):",
                "adm_set_bonus_cap_1": "✍️ أرسل سقف الأرباح الجديد لشراء 1 جرة (لفئة 3 NSP):",
                "adm_set_bonus_cap_2": "✍️ أرسل سقف الأرباح الجديد لشراء 2 جرة (لفئة 3 NSP):",
                "adm_set_bonus_cap_3": "✍️ أرسل سقف الأرباح الجديد لشراء 3 جرات (لفئة 3 NSP):",
                "adm_set_ch_loss": "✍️ أرسل نسبة الخسارة العامة الجديدة (0 إلى 100):",
                "adm_set_ch_normal": "✍️ أرسل نسبة الربح العادي الجديدة (0 إلى 100):",
                "adm_set_ch_medium": "✍️ أرسل نسبة الربح المتوسط الجديدة (0 إلى 100):",
                "adm_set_ch_high": "✍️ أرسل نسبة الربح العالي الجديدة (0 إلى 100):",
                "adm_set_ch_huge": "✍️ أرسل نسبة الربح الضخم الجديدة (0 إلى 100):"
            }
            await query.message.edit_text(prompts[data], reply_markup=cancel_keyboard("adm_algo_menu"))
            return

        if data == "adm_add_admin":
            conn.execute("UPDATE users SET step = 'adm_input_add_admin' WHERE user_id = ?", (user.id,))
            conn.commit()
            conn.close()
            await query.message.edit_text("✍️ **أدخل ID المستخدم لترقيته كأدمن:**", reply_markup=cancel_keyboard("open_admin_panel"))
            return
            
        if data == "adm_del_admin":
            conn.execute("UPDATE users SET step = 'adm_input_del_admin' WHERE user_id = ?", (user.id,))
            conn.commit()
            conn.close()
            await query.message.edit_text("✍️ **أدخل ID الأدمن لإزالته من الإدارة:**", reply_markup=cancel_keyboard("open_admin_panel"))
            return

        if data == "adm_channels_menu":
            channels = conn.execute("SELECT * FROM channels").fetchall()
            kb = [[InlineKeyboardButton("➕ إضافة قناة", callback_data="adm_add_channel")]]
            for ch in channels:
                kb.append([InlineKeyboardButton(f"❌ حذف: {ch['channel_title']}", callback_data=f"adm_del_ch_{ch['channel_id']}")])
            kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="open_admin_panel")])
            
            await query.message.edit_text("📢 **إدارة القنوات:**", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
            conn.close()
            return

        if data == "adm_add_channel":
            conn.execute("UPDATE users SET step = 'adm_input_add_ch_id' WHERE user_id = ?", (user.id,))
            conn.commit()
            conn.close()
            await query.message.edit_text("✍️ **أدخل معرّف القناة ID:**", reply_markup=cancel_keyboard("adm_channels_menu"))
            return

        if data.startswith("adm_del_ch_"):
            ch_id = data.replace("adm_del_ch_", "")
            conn.execute("DELETE FROM channels WHERE channel_id = ?", (ch_id,))
            conn.commit()
            conn.close()
            await query.message.edit_text("✅ تم الحذف.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_channels_menu")]]))
            return

        if data == "adm_add_bal":
            conn.execute("UPDATE users SET step = 'adm_input_add_bal' WHERE user_id = ?", (user.id,))
            conn.commit()
            conn.close()
            await query.message.edit_text("✍️ **أدخل ID ثم مسافة ثم المبلغ للإضافة:**", reply_markup=cancel_keyboard("open_admin_panel"))
            return

        if data == "adm_sub_bal":
            conn.execute("UPDATE users SET step = 'adm_input_sub_bal' WHERE user_id = ?", (user.id,))
            conn.commit()
            conn.close()
            await query.message.edit_text("✍️ **أدخل ID ثم مسافة ثم المبلغ للخصم:**", reply_markup=cancel_keyboard("open_admin_panel"))
            return

        if data == "adm_make_gift":
            conn.execute("UPDATE users SET step = 'adm_input_make_gift' WHERE user_id = ?", (user.id,))
            conn.commit()
            conn.close()
            await query.message.edit_text("✍️ **أدخل: الكود المبلغ عدد_المرات**", reply_markup=cancel_keyboard("open_admin_panel"))
            return

        if data == "adm_set_ref":
            conn.execute("UPDATE users SET step = 'adm_input_set_ref' WHERE user_id = ?", (user.id,))
            conn.commit()
            conn.close()
            await query.message.edit_text("✍️ **أدخل قيمة مكافأة الإحالة الجديدة:**", reply_markup=cancel_keyboard("open_admin_panel"))
            return

        if data == "adm_set_min_w":
            conn.execute("UPDATE users SET step = 'adm_input_set_min_w' WHERE user_id = ?", (user.id,))
            conn.commit()
            conn.close()
            await query.message.edit_text("✍️ **أدخل الحد الأدنى للسحب:**", reply_markup=cancel_keyboard("open_admin_panel"))
            return

        if data == "adm_set_welcome":
            conn.execute("UPDATE users SET step = 'adm_input_set_welcome' WHERE user_id = ?", (user.id,))
            conn.commit()
            conn.close()
            await query.message.edit_text("✍️ **أدخل البونص الترحيبي:**", reply_markup=cancel_keyboard("open_admin_panel"))
            return

        if data == "adm_user_info":
            conn.execute("UPDATE users SET step = 'adm_input_user_info' WHERE user_id = ?", (user.id,))
            conn.commit()
            conn.close()
            await query.message.edit_text("✍️ **أدخل ID المستخدم للبحث:**", reply_markup=cancel_keyboard("open_admin_panel"))
            return

        if data == "adm_ban":
            conn.execute("UPDATE users SET step = 'adm_input_ban' WHERE user_id = ?", (user.id,))
            conn.commit()
            conn.close()
            await query.message.edit_text("✍️ **أدخل ID للحظر:**", reply_markup=cancel_keyboard("open_admin_panel"))
            return

        if data == "adm_unban":
            conn.execute("UPDATE users SET step = 'adm_input_unban' WHERE user_id = ?", (user.id,))
            conn.commit()
            conn.close()
            await query.message.edit_text("✍️ **أدخل ID لفك الحظر:**", reply_markup=cancel_keyboard("open_admin_panel"))
            return

        if data == "adm_bc_txt":
            conn.execute("UPDATE users SET step = 'adm_input_bc_txt' WHERE user_id = ?", (user.id,))
            conn.commit()
            conn.close()
            await query.message.edit_text("✍️ **أدخل نص الإذاعة:**", reply_markup=cancel_keyboard("open_admin_panel"))
            return

        if data == "adm_bc_img":
            conn.execute("UPDATE users SET step = 'adm_input_bc_img' WHERE user_id = ?", (user.id,))
            conn.commit()
            conn.close()
            await query.message.edit_text("📸 **أرسل الصورة مع النص للإذاعة:**", reply_markup=cancel_keyboard("open_admin_panel"))
            return

        if data == "adm_pm_txt":
            conn.execute("UPDATE users SET step = 'adm_input_pm_txt' WHERE user_id = ?", (user.id,))
            conn.commit()
            conn.close()
            await query.message.edit_text("✍️ **أدخل ID ثم مسافة ثم النص:**", reply_markup=cancel_keyboard("open_admin_panel"))
            return

        if data == "adm_all_logs":
            logs = conn.execute("SELECT user_id, action, amount, timestamp FROM logs ORDER BY id DESC LIMIT 15").fetchall()
            conn.close()
            if not logs:
                txt = "📜 لا توجد سجلات عامة حتى الآن."
            else:
                txt = "📜 **آخر 15 عملية على مستوى البوت:**\n\n"
                for lg in logs:
                    txt += f"• `{lg['timestamp']}` | `{lg['user_id']}` | {lg['action']} | `{lg['amount']}` NSP\n"
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للإدارة", callback_data="open_admin_panel")]])
            await query.message.edit_text(txt, parse_mode="Markdown", reply_markup=kb)
            return

        if data == "adm_stats":
            u_count = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
            w_sum = conn.execute("SELECT SUM(amount) as s FROM withdrawals WHERE status = 'approved'").fetchone()["s"] or 0.0
            p_sum = conn.execute("SELECT SUM(balance) as s FROM users").fetchone()["s"] or 0.0
            
            msg = (
                f"📊 **الإحصائيات الشاملة:**\n"
                f"✨ ─────────────────── ✨\n"
                f"👥 **إجمالي المستخدمين:** `{u_count}`\n"
                f"💰 **إجمالي الأرصدة الحالية:** `{p_sum:,.2f}` NSP\n"
                f"💸 **إجمالي السحوبات المقبولة:** `{w_sum:,.2f}` NSP\n"
                f"✨ ─────────────────── ✨"
            )
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للإدارة", callback_data="open_admin_panel")]])
            await query.message.edit_text(msg, parse_mode="Markdown", reply_markup=kb)
            conn.close()
            return

        if data == "adm_withdraws":
            pending = conn.execute("SELECT * FROM withdrawals WHERE status = 'pending' ORDER BY id DESC LIMIT 10").fetchall()
            conn.close()
            
            if not pending:
                await query.message.edit_text("📥 لا توجد طلبات سحب معلقة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للإدارة", callback_data="open_admin_panel")]]))
                return

            for w in pending:
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ موافقة ودفع", callback_data=f"app_w_{w['id']}"), InlineKeyboardButton("❌ رفض وإعادة", callback_data=f"rej_w_{w['id']}")]
                ])
                await context.bot.send_message(
                    chat_id=user.id,
                    text=f"📥 **طلب سحب (# {w['id']}):**\n🆔 **ID:** `{w['user_id']}`\n💳 **الطريقة:** {w['method']}\n🔢 **الكود:** `{w['account_code']}`\n💰 **المبلغ:** `{w['amount']}` NSP",
                    parse_mode="Markdown",
                    reply_markup=kb
                )
            return

        if data.startswith("app_w_"):
            wid = int(data.replace("app_w_", ""))
            w = conn.execute("SELECT * FROM withdrawals WHERE id = ?", (wid,)).fetchone()
            if w and w["status"] == "pending":
                conn.execute("UPDATE withdrawals SET status = 'approved' WHERE id = ?", (wid,))
                conn.commit()
                await query.message.edit_text(f"✅ تم الموافقة على الطلب #{wid}.")
                try: 
                    await context.bot.send_message(w["user_id"], f"✅ تم الموافقة على سحب `{w['amount']}` NSP!")
                except Exception: 
                    pass
            conn.close()
            return

        if data.startswith("rej_w_"):
            wid = int(data.replace("rej_w_", ""))
            w = conn.execute("SELECT * FROM withdrawals WHERE id = ?", (wid,)).fetchone()
            if w and w["status"] == "pending":
                conn.execute("UPDATE withdrawals SET status = 'rejected' WHERE id = ?", (wid,))
                conn.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (w["amount"], w["user_id"]))
                conn.commit()
                await query.message.edit_text(f"❌ تم رفض الطلب #{wid} وإعادة الرصيد.")
                try: 
                    await context.bot.send_message(w["user_id"], f"❌ تم رفض طلب السحب وإعادة `{w['amount']}` NSP لحسابك.")
                except Exception: 
                    pass
            conn.close()
            return

    conn.close()

# ----------------------------------------------------
# 8. تشغيل التطبيق (Application Builder & Polling)
# ----------------------------------------------------
def main():
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("❌ لم يتم العثور على BOT_TOKEN صحيح في متغيرات البيئة!")
        return

    # تهيئة قاعدة البيانات عند بدء التشغيل
    init_db()

    # تشغيل سيرفر Keep-Alive الخاص بـ Render
    keep_alive()

    # بناء تطبيق البوت
    app = Application.builder().token(BOT_TOKEN).build()

    # تسجيل الأوامر الرئيسية
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("admin", admin_command))
    
    # تسجيل معالجات أنواع الرسائل
    app.add_handler(MessageHandler(filters.CONTACT, handle_contact))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo_messages))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_messages))
    
    # تسجيل معالج الأزرار الشفافية (Inline Callback Query)
    app.add_handler(CallbackQueryHandler(handle_callback))

    logger.info("Bot & Keep-Alive Engine starting successfully...")
    app.run_polling()

if __name__ == "__main__":
    main()

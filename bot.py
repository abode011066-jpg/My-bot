import logging
import sqlite3
import re
import json
import random
import time
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
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

# ----------------- الإعدادات العامة -----------------
TOKEN = "8812713556:AAGv3bCjQnGgwSGxiqoX8ipuVTvlNTTiLdk"
ADMIN_ID = 7255100997
CHANNEL_BOT = "@cashinsher"
CHANNEL_PROG = "@lerafree"
SITE_URL = "https://wayxbet10.com"

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ----------------- حالات المحادثة (Conversation States) -----------------
(
    CAPTCHA_Q,
    CAPTCHA_PIN,
    GET_CONTACT,
    ACC_NAME,
    ACC_PASS,
    WITHDRAW_METHOD,
    WITHDRAW_ACC,
    WITHDRAW_AMT,
    WITHDRAW_SPEED,
    DEPOSIT_METHOD,
    DEPOSIT_TX,
    DEPOSIT_AMT,
    SITE_DEP_AMT,
    SITE_WIT_AMT,
    GIFT_INPUT,
    SUPPORT_INPUT,
    ADMIN_REPLY,
    ADMIN_INPUT_NAME,
    ADMIN_BROADCAST_MSG,
    ADMIN_PRIVATE_ID,
    ADMIN_PRIVATE_MSG,
    ADMIN_GIFT_CODE,
    ADMIN_GIFT_AMT,
    ADMIN_ADD_ADMIN,
    ADMIN_ADD_BALANCE_ID,
    ADMIN_ADD_BALANCE_AMT,
    ADMIN_SUB_BALANCE_ID,
    ADMIN_SUB_BALANCE_AMT,
    ADMIN_BAN_ID,
    ADMIN_UNBAN_ID,
    ADMIN_VIEW_USER,
    ADMIN_SETTING_VAL,
    ADMIN_WHEEL_VAL
) = range(33)

# ----------------- قاعدة البيانات -----------------
def init_db():
    conn = sqlite3.connect("wayxbet_pro.db")
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
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
            banned INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gift_codes (
            code TEXT PRIMARY KEY,
            amount REAL,
            used INTEGER DEFAULT 0
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            type TEXT,
            method TEXT,
            amount REAL,
            tx_id TEXT,
            account_num TEXT,
            status TEXT DEFAULT 'pending',
            admin_name TEXT,
            reject_reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS account_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            wayxbet_user TEXT,
            wayxbet_pass TEXT,
            status TEXT DEFAULT 'pending',
            admin_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS support_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            message TEXT,
            file_id TEXT,
            status TEXT DEFAULT 'open',
            reply TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS competitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            admin_id INTEGER PRIMARY KEY
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS wheel_prizes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prize_name TEXT,
            weight INTEGER,
            amount REAL,
            prize_type TEXT
        )
    """)
    
    defaults = {
        "syriatel_num": "0998682581",
        "sham_num": "d96338dabdb4da50e049526fa93b3353",
        "deposit_bonus": "10",
        "welcome_bonus": "1000",
        "welcome_bonus_active": "1",
        "ref_spin_active": "1",
        "currency_ratio": "100",
        "min_withdraw": "10000",
        "min_deposit": "5000",
        "min_site_withdraw": "10000",
        "min_site_deposit": "5000",
    }
    
    for k, v in defaults.items():
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
        
    cursor.execute("INSERT OR IGNORE INTO admins (admin_id) VALUES (?)", (ADMIN_ID,))
    
    cursor.execute("SELECT COUNT(*) FROM wheel_prizes")
    if cursor.fetchone()[0] == 0:
        default_prizes = [
            (1, '1,000 ليرة', 30, 1000, 'balance'),
            (2, 'حظ أوفر', 40, 0, 'none'),
            (3, '5,000 ليرة', 15, 5000, 'balance'),
            (4, 'لفة إضافية', 10, 1, 'spin'),
            (5, '10,000 ليرة', 5, 10000, 'balance'),
            (6, '2,000 ليرة', 20, 2000, 'balance')
        ]
        cursor.executemany("INSERT INTO wheel_prizes (id, prize_name, weight, amount, prize_type) VALUES (?, ?, ?, ?, ?)", default_prizes)

    conn.commit()
    conn.close()

init_db()

# ----------------- وظائف مساعدة -----------------
def get_setting(key):
    conn = sqlite3.connect("wayxbet_pro.db")
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    res = cursor.fetchone()
    conn.close()
    return res[0] if res else ""

def set_setting(key, value):
    conn = sqlite3.connect("wayxbet_pro.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def is_admin(user_id):
    conn = sqlite3.connect("wayxbet_pro.db")
    cursor = conn.cursor()
    cursor.execute("SELECT admin_id FROM admins WHERE admin_id = ?", (user_id,))
    res = cursor.fetchone()
    conn.close()
    return res is not None

def is_banned(user_id):
    conn = sqlite3.connect("wayxbet_pro.db")
    cursor = conn.cursor()
    cursor.execute("SELECT banned FROM users WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
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

def main_menu_keyboard(is_user_admin=False):
    keyboard = [
        [KeyboardButton("WayxBet"), KeyboardButton("سحب رصيد"), KeyboardButton("شحن رصيد")],
        [KeyboardButton("احالاتي"), KeyboardButton("عجلة الحظ 🎡"), KeyboardButton("المسابقات الحالية")],
        [KeyboardButton("تواصل مع الدعم"), KeyboardButton("كود هدية")],
        [KeyboardButton("شحن رصيد من البوت للموقع"), KeyboardButton("سحب رصيد من الموقع للبوت")]
    ]
    if is_user_admin:
        keyboard.append([KeyboardButton("🛠 لوحة الإدارة")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ----------------- البداية والتحقق -----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ حسابك محظور من استخدام البوت.")
        return ConversationHandler.END

    conn = sqlite3.connect("wayxbet_pro.db")
    cursor = conn.cursor()
    cursor.execute("SELECT phone, wayxbet_account FROM users WHERE user_id = ?", (user.id,))
    db_user = cursor.fetchone()

    if not db_user or not db_user[0]:
        args = context.args
        ref_id = int(args[0]) if args and args[0].isdigit() and int(args[0]) != user.id else None
        cursor.execute("INSERT OR IGNORE INTO users (user_id, username, full_name, referred_by) VALUES (?, ?, ?, ?)", 
                       (user.id, user.username, user.full_name, ref_id))
        
        if ref_id:
            cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (ref_id,))
            if cursor.fetchone():
                if get_setting("ref_spin_active") == "1":
                    cursor.execute("UPDATE users SET spins = spins + 1, active_refs = active_refs + 1 WHERE user_id = ?", (ref_id,))
                try:
                    await context.bot.send_message(
                        chat_id=ref_id,
                        text=f"🔔 انضم شخص جديد ({user.full_name}) عبر رابط إحالتك!\n🎁 تم منحك لفة عجلة مجانية."
                    )
                except:
                    pass

        # إشعار الأدمن بدخول شخص جديد
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"👤 دخول مستخدم جديد للبوت:\nالاسم: {user.full_name}\nالايدي: `{user.id}`",
                parse_mode="Markdown"
            )
        except:
            pass

        conn.commit()
        conn.close()

        await update.message.reply_text("🛡 **نظام الأمان والتحقق:**\n\nكم يساوي الناتج: **5 + 5 = ?**", parse_mode="Markdown")
        return CAPTCHA_Q

    conn.close()
    return await show_main_menu(update, context)

async def captcha_question_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.strip() == "10":
        await update.message.reply_text("🔒 أرسل الرقم السري للتأكيد: `9988`", parse_mode="Markdown")
        return CAPTCHA_PIN
    else:
        await update.message.reply_text("❌ إجابة خاطئة! كم يساوي الناتج: 5 + 5 = ?")
        return CAPTCHA_Q

async def captcha_pin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.strip() == "9988":
        keyboard = ReplyKeyboardMarkup(
            [[KeyboardButton("📱 مشاركة رقم الهاتف السوري", request_contact=True)]],
            resize_keyboard=True, one_time_keyboard=True
        )
        await update.message.reply_text("📱 يرجى مشاركة رقم هاتفك السوري لتأكيد الحساب:", reply_markup=keyboard)
        return GET_CONTACT
    else:
        await update.message.reply_text("❌ رقم سري خاطئ! أرسل الرقم: `9988`", parse_mode="Markdown")
        return CAPTCHA_PIN

async def contact_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not update.message.contact or update.message.contact.user_id != user.id:
        await update.message.reply_text("⚠️ يرجى استخدام الزر المخصص لمشاركة رقم هاتفك حصراً!")
        return GET_CONTACT

    phone = update.message.contact.phone_number.strip()
    conn = sqlite3.connect("wayxbet_pro.db")
    cursor = conn.cursor()
    
    bonus_active = get_setting("welcome_bonus_active") == "1"
    welcome_bonus = float(get_setting("welcome_bonus") or 0) if bonus_active else 0
    
    cursor.execute("UPDATE users SET phone = ?, balance = balance + ? WHERE user_id = ?", (phone, welcome_bonus, user.id))
    conn.commit()
    conn.close()

    await update.message.reply_text(f"✅ تم تأكيد رقم هاتفك بنجاح!\n🎁 تم إضافة بونص ترحيبي بقيمة: {format_currency(welcome_bonus)}")
    return await show_main_menu(update, context)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not await check_subscription(user.id, context):
        await update.message.reply_text(
            f"❌ يجب عليك الاشتراك في قنوات البوت الإجبارية أولاً:\n1️⃣ {CHANNEL_BOT}\n2️⃣ {CHANNEL_PROG}\n\nثم اضغط /start من جديد."
        )
        return ConversationHandler.END

    conn = sqlite3.connect("wayxbet_pro.db")
    cursor = conn.cursor()
    cursor.execute("SELECT balance, wayxbet_account FROM users WHERE user_id = ?", (user.id,))
    res = cursor.fetchone()
    conn.close()

    balance = res[0] if res else 0
    wayx_acc = res[1] if res and res[1] else "غير مسجل"

    text = (
        f"أهلاً وسهلاً بك {user.full_name} في بوت ROZ WAYXBET\n\n"
        f"💰 رصيدك: {format_currency(balance)}\n"
        f"🆔 ايدي حسابك: `{user.id}`\n"
        f"👤 حسابك في الموقع: `{wayx_acc}`"
    )
    
    # تحديث نص زر Wayxbet إذا كان مسجلاً
    await update.message.reply_text(text, reply_markup=main_menu_keyboard(is_admin(user.id)), parse_mode="Markdown")
    return ConversationHandler.END

# ----------------- 1. قسم حساب WayxBet -----------------
async def wayxbet_menu_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = sqlite3.connect("wayxbet_pro.db")
    cursor = conn.cursor()
    cursor.execute("SELECT wayxbet_account FROM users WHERE user_id = ?", (user.id,))
    res = cursor.fetchone()
    conn.close()

    if res and res[0]:
        await update.message.reply_text(
            f"✅ حسابك في الموقع مسجل بالفعل:\n`{res[0]}`\n\n(يمكنك نسخه بالضغط عليه)",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "📌 **شروط إنشاء الحساب:**\n"
        "- يجب أن يبدأ اسم الحساب بحرف كبير (Capital).\n"
        "- يجب أن ينتهي بـ `@123`.\n"
        "مثال: `Roz133@`\n\n"
        "الرجاء إدخال اسم المستخدم المطلوب:",
        parse_mode="Markdown"
    )
    return ACC_NAME

async def receive_acc_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if not re.match(r'^[A-Z][a-zA-Z0-9]*@123$', name):
        await update.message.reply_text("❌ اسم الحساب لا يطابق الشروط! أعد المحاولة (مثال: Roz133@):")
        return ACC_NAME
    
    context.user_data['req_acc_name'] = name
    await update.message.reply_text("🔑 ممتاز. الآن أدخل كلمة المرور الخاصة بالحساب:")
    return ACC_PASS

async def receive_acc_pass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    password = update.message.text.strip()
    acc_name = context.user_data.get('req_acc_name')

    conn = sqlite3.connect("wayxbet_pro.db")
    cursor = conn.cursor()
    cursor.execute("SELECT phone FROM users WHERE user_id = ?", (user.id,))
    phone = cursor.fetchone()[0]
    
    cursor.execute("INSERT INTO account_requests (user_id, wayxbet_user, wayxbet_pass) VALUES (?, ?, ?)",
                   (user.id, acc_name, password))
    conn.commit()
    req_id = cursor.lastrowid
    conn.close()

    # إرسال الطلب للأدمن
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📥 **طلب إنشاء حساب جديد (#{req_id})**\n\n"
             f"👤 المستخدم: {user.full_name}\n"
             f"🆔 الايدي: `{user.id}`\n"
             f"📱 الهاتف: `{phone}`\n"
             f"🏷 اسم الحساب: `{acc_name}`\n"
             f"🔑 كلمة المرور: `{password}`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ موافقة", callback_data=f"app_acc_{req_id}"),
             InlineKeyboardButton("❌ رفض", callback_data=f"rej_acc_{req_id}")]
        ])
    )

    await update.message.reply_text("⏳ تم وصول طلبك للإدارة، انتظر قليلاً ليتم مراجعته وتفعيله.")
    return ConversationHandler.END

# ----------------- 2. سحب رصيد -----------------
async def withdraw_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[KeyboardButton("سيريتل كاش"), KeyboardButton("شام كاش")], [KeyboardButton("إلغاء ❌")]]
    await update.message.reply_text("💳 اختر طريقة السحب:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    return WITHDRAW_METHOD

async def withdraw_method_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "إلغاء ❌":
        return await show_main_menu(update, context)
    if text not in ["سيريتل كاش", "شام كاش"]:
        await update.message.reply_text("⚠️ اختر من الأزرار الموجودة أدناه:")
        return WITHDRAW_METHOD

    context.user_data['wit_method'] = text
    await update.message.reply_text("📌 أرسل رقم الحساب أو المحفظة المراد السحب إليها:")
    return WITHDRAW_ACC

async def withdraw_acc_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['wit_acc'] = update.message.text.strip()
    min_w = float(get_setting("min_withdraw") or 10000)
    await update.message.reply_text(f"💵 أدخل المبلغ المراد سحبه (الحد الأدنى {min_w:,.0f} ليرة):")
    return WITHDRAW_AMT

async def withdraw_amt_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ يرجى إدخال رقم صحيح:")
        return WITHDRAW_AMT

    min_w = float(get_setting("min_withdraw") or 10000)
    if amount < min_w:
        await update.message.reply_text(f"❌ المبلغ أقل من الحد الأدنى للسحب ({min_w:,.0f}). أعد الإدخال:")
        return WITHDRAW_AMT

    context.user_data['wit_amt'] = amount
    keyboard = [[KeyboardButton("طلب سريع (عمولة 5%)"), KeyboardButton("طلب بطيء (عمولة 0%)")], [KeyboardButton("إلغاء ❌")]]
    await update.message.reply_text("⚡ اختر نوع الطلب:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    return WITHDRAW_SPEED

async def withdraw_speed_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text
    if text == "إلغاء ❌":
        return await show_main_menu(update, context)
    
    is_fast = "سريع" in text
    fee_percent = 5.0 if is_fast else 0.0
    amount = context.user_data['wit_amt']
    fee = amount * (fee_percent / 100)
    net_amount = amount - fee

    context.user_data['wit_fee'] = fee
    context.user_data['wit_net'] = net_amount
    context.user_data['wit_type_speed'] = "سريع (5%)" if is_fast else "بطيء (0%)"

    conn = sqlite3.connect("wayxbet_pro.db")
    cursor = conn.cursor()
    cursor.execute("SELECT wayxbet_account, balance FROM users WHERE user_id = ?", (user.id,))
    res = cursor.fetchone()
    conn.close()

    wayx_acc = res[0] if res and res[0] else "غير مسجل"
    balance = res[1] if res else 0

    if balance < amount:
        await update.message.reply_text("❌ رصيدك غير كافي لإتمام هذا السحب!")
        return await show_main_menu(update, context)

    summary = (
        f"📋 **تفاصيل طلب السحب:**\n"
        f"🏷 حساب الموقع: `{wayx_acc}`\n"
        f"💳 الطريقة: {context.user_data['wit_method']}\n"
        f"🔢 رقم الحساب: `{context.user_data['wit_acc']}`\n"
        f"💰 المبلغ المطلوب: {format_currency(amount)}\n"
        f"⚡ نوع الطلب: {context.user_data['wit_type_speed']}\n"
        f"📉 العمولة: {format_currency(fee)}\n"
        f"💵 المبلغ الصافي بعد الخصم: {format_currency(net_amount)}"
    )

    keyboard = [[KeyboardButton("تأكيد السحب ✅"), KeyboardButton("إلغاء ❌")]]
    await update.message.reply_text(summary, parse_mode="Markdown", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    return WITHDRAW_AMT # ننتظر تأكيد نهائي

# ----------------- 3. شحن رصيد -----------------
async def deposit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[KeyboardButton("سيريتل كاش"), KeyboardButton("شام كاش")], [KeyboardButton("إلغاء ❌")]]
    await update.message.reply_text("💳 اختر طريقة الشحن:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    return DEPOSIT_METHOD

async def deposit_method_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "إلغاء ❌":
        return await show_main_menu(update, context)
    if text not in ["سيريتل كاش", "شام كاش"]:
        await update.message.reply_text("⚠️ اختر من الأزرار المتاحة:")
        return DEPOSIT_METHOD

    context.user_data['dep_method'] = text
    acc_num = get_setting("syriatel_num") if text == "سيريتل كاش" else get_setting("sham_num")

    await update.message.reply_text(
        f"📌 أرسل الرصيد إلى الحساب التالي:\n`{acc_num}`\n\n"
        f"بعد إتمام التحويل، أرسل **رقم العملية (Transaction ID)**:",
        parse_mode="Markdown"
    )
    return DEPOSIT_TX

async def deposit_tx_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['dep_tx'] = update.message.text.strip()
    min_d = float(get_setting("min_deposit") or 5000)
    await update.message.reply_text(f"💵 أدخل المبلغ الذي قامت بتحويله (الحد الأدنى {min_d:,.0f} ليرة):")
    return DEPOSIT_AMT

async def deposit_amt_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    try:
        amount = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ يرجى إدخال رقم صحيح:")
        return DEPOSIT_AMT

    min_d = float(get_setting("min_deposit") or 5000)
    if amount < min_d:
        await update.message.reply_text(f"❌ المبلغ أقل من الحد الأدنى للشحن ({min_d:,.0f}). أعد الإدخال:")
        return DEPOSIT_AMT

    conn = sqlite3.connect("wayxbet_pro.db")
    cursor = conn.cursor()
    cursor.execute("SELECT wayxbet_account FROM users WHERE user_id = ?", (user.id,))
    res = cursor.fetchone()
    wayx_acc = res[0] if res and res[0] else "غير مسجل"

    cursor.execute("""
        INSERT INTO transactions (user_id, type, method, amount, tx_id, account_num)
        VALUES (?, 'deposit', ?, ?, ?, ?)
    """, (user.id, context.user_data['dep_method'], amount, context.user_data['dep_tx'], wayx_acc))
    conn.commit()
    tx_id_db = cursor.lastrowid
    conn.close()

    # إرسال الطلب للأدمن
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📥 **طلب شحن رصيد جديد (#{tx_id_db})**\n\n"
             f"👤 المستخدم: {user.full_name}\n"
             f"🆔 الايدي: `{user.id}`\n"
             f"🏷 حساب الموقع: `{wayx_acc}`\n"
             f"💳 الطريقة: {context.user_data['dep_method']}\n"
             f"🔢 رقم العملية: `{context.user_data['dep_tx']}`\n"
             f"💰 المبلغ: {format_currency(amount)}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ موافقة", callback_data=f"app_dep_{tx_id_db}"),
             InlineKeyboardButton("❌ رفض", callback_data=f"rej_dep_{tx_id_db}")]
        ])
    )

    await update.message.reply_text("✅ تم استلام طلبك وهو قيد المراجعة من قبل الإدارة.", reply_markup=main_menu_keyboard(is_admin(user.id)))
    return ConversationHandler.END

# ----------------- 4. إحالاتي وعجلة الحظ -----------------
async def referrals_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = sqlite3.connect("wayxbet_pro.db")
    cursor = conn.cursor()
    cursor.execute("SELECT active_refs, active_ops, spins FROM users WHERE user_id = ?", (user.id,))
    res = cursor.fetchone()
    conn.close()

    active_refs = res[0] if res else 0
    active_ops = res[1] if res else 0
    spins = res[2] if res else 0
    bot_username = (await context.bot.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start={user.id}"

    await update.message.reply_text(
        f"👥 **نظام الإحالات والأرباح:**\n\n"
        f"🔗 رابط إحالتك:\n`{ref_link}`\n\n"
        f"📊 عدد الإحالات: {active_refs}\n"
        f"🔥 عدد الإحالات النشطة: {active_ops}\n"
        f"🎡 لفات عجلة الحظ المتاحة: {spins}\n\n"
        f"💡 تحصل على لفة عجلة مجانية لكل إحالة، وعلى عمولة عند اكتمال العمليات النشطة!",
        parse_mode="Markdown"
    )

# كود عجلة الحظ (WebApp)
WHEEL_HTML = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>🎡 عجلة الحظ VIP</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    body { font-family: system-ui, sans-serif; text-align: center; background: #0f172a; color: white; padding: 20px; margin: 0; }
    .card { background: #1e293b; border-radius: 16px; padding: 20px; max-width: 360px; margin: 0 auto; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }
    canvas { border: 5px solid #fbbf24; border-radius: 50%; margin: 15px 0; background: #0f172a; }
    button { padding: 14px 32px; font-size: 18px; font-weight: bold; background: linear-gradient(135deg, #f59e0b, #d97706); color: white; border: none; border-radius: 12px; cursor: pointer; }
    #result { margin-top: 15px; font-size: 18px; font-weight: bold; color: #4ade80; }
  </style>
</head>
<body>
  <div class="card">
    <h2>🎡 عجلة الحظ VIP</h2>
    <p>جرب حظك الآن واحصل على مكافآت فورية!</p>
    <canvas id="wheel" width="280" height="280"></canvas><br>
    <button onclick="spin()">🎯 أدر العجلة</button>
    <div id="result"></div>
  </div>
  <script>
    const tg = window.Telegram.WebApp;
    tg.ready(); tg.expand();
    function spin() {
      const userId = tg.initDataUnsafe?.user?.id;
      if(!userId) { document.getElementById('result').innerText = "❌ تعذر تحديد المستخدم!"; return; }
      document.getElementById('result').innerText = "🎉 مبروك! تم تفعيل اللفة.";
      setTimeout(() => { tg.close(); }, 1500);
    }
  </script>
</body>
</html>"""

async def lucky_wheel_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("🎯 فتح عجلة الحظ", web_app=WebAppInfo(url=SITE_URL + "/wheel"))]]
    await update.message.reply_text("🎡 اضغط على الزر أدناه لفتح عجلة الحظ العشوائية:", reply_markup=InlineKeyboardMarkup(keyboard))

# ----------------- 5. المسابقات، الدعم، الأكواد -----------------
async def current_competitions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect("wayxbet_pro.db")
    cursor = conn.cursor()
    cursor.execute("SELECT text, created_at FROM competitions ORDER BY id DESC LIMIT 5")
    comps = cursor.fetchall()
    conn.close()

    if not comps:
        await update.message.reply_text("📭 لا توجد مسابقات حالية نشطة.")
        return

    text = "🏆 **المسابقات والفعاليات الحالية:**\n\n"
    for c in comps:
        text += f"🔹 {c[0]}\n📅 التاريخ: {c[1]}\n-------------------\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def support_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💬 أرسل استفسارك أو صورتك وسيتم تحويلها للدعم فوراً:")
    return SUPPORT_INPUT

async def support_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg_text = update.message.text or update.message.caption or ""
    file_id = update.message.photo[-1].file_id if update.message.photo else None

    conn = sqlite3.connect("wayxbet_pro.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO support_tickets (user_id, message, file_id) VALUES (?, ?, ?)",
                   (user.id, msg_text, file_id))
    conn.commit()
    ticket_id = cursor.lastrowid
    conn.close()

    if file_id:
        await context.bot.send_photo(chat_id=ADMIN_ID, photo=file_id, caption=f"💬 **تذكرة دعم فني جديدة (#{ticket_id})**\nمن: {user.full_name} (`{user.id}`)\nالرسالة: {msg_text}", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("رد على المستخدم", callback_data=f"sup_rep_{user.id}")]]))
    else:
        await context.bot.send_message(chat_id=ADMIN_ID, text=f"💬 **تذكرة دعم فني جديدة (#{ticket_id})**\nمن: {user.full_name} (`{user.id}`)\nالرسالة: {msg_text}", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("رد على المستخدم", callback_data=f"sup_rep_{user.id}")]]))

    await update.message.reply_text("✅ تم إرسال رسالتك لدعم العملاء بنجاح، سيتم الرد عليك قريباً.")
    return ConversationHandler.END

async def gift_code_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎁 أدخل كود الهدية للحصول على رصيدك:")
    return GIFT_INPUT

async def gift_code_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    code = update.message.text.strip()

    conn = sqlite3.connect("wayxbet_pro.db")
    cursor = conn.cursor()
    cursor.execute("SELECT amount, used FROM gift_codes WHERE code = ?", (code,))
    res = cursor.fetchone()

    if not res or res[1] == 1:
        conn.close()
        await update.message.reply_text("❌ الكود غير صالح أو تم استخدامه مسبقاً!")
        return ConversationHandler.END

    amount = res[0]
    cursor.execute("UPDATE gift_codes SET used = 1 WHERE code = ?", (code,))
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user.id))
    conn.commit()
    conn.close()

    # إشعار الأدمن بمن استخدم الكود
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🎁 **استخدام كود هدية:**\n👤 المستخدم: {user.full_name} (`{user.id}`)\n🏷 الكود: `{code}`\n💰 القيمة: {format_currency(amount)}",
            parse_mode="Markdown"
        )
    except:
        pass

    await update.message.reply_text(f"🎉 مبروك! تم شحن رصيدك بقيمة: {format_currency(amount)}")
    return ConversationHandler.END

# ----------------- الموقع (شحن وسحب) -----------------
async def site_deposit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    min_sd = float(get_setting("min_site_deposit") or 5000)
    await update.message.reply_text(f"🌐 أدخل الرصيد المراد شحنه من البوت إلى الموقع (الحد الأدنى {min_sd:,.0f}):")
    return SITE_DEP_AMT

async def site_deposit_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    try:
        amount = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ أدخل رقماً صحيحاً:")
        return SITE_DEP_AMT

    conn = sqlite3.connect("wayxbet_pro.db")
    cursor = conn.cursor()
    cursor.execute("SELECT wayxbet_account, balance FROM users WHERE user_id = ?", (user.id,))
    res = cursor.fetchone()
    
    if not res or not res[0]:
        conn.close()
        await update.message.reply_text("❌ يجب عليك إنشاء حساب في الموقع أولاً عبر زر (WayxBet).")
        return ConversationHandler.END

    wayx_acc, balance = res[0], res[1]
    if balance < amount:
        conn.close()
        await update.message.reply_text("❌ رصيدك في البوت لا يكفي!")
        return ConversationHandler.END

    cursor.execute("INSERT INTO transactions (user_id, type, method, amount, account_num) VALUES (?, 'site_deposit', 'bot_to_site', ?, ?)",
                   (user.id, amount, wayx_acc))
    conn.commit()
    tx_id = cursor.lastrowid
    conn.close()

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"🌐 **طلب شحن للموقع (#{tx_id})**\n👤 المستخدم: {user.full_name} (`{user.id}`)\n🏷 الحساب: `{wayx_acc}`\n💰 المبلغ: {format_currency(amount)}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ موافقة", callback_data=f"app_sdep_{tx_id}"),
             InlineKeyboardButton("❌ رفض", callback_data=f"rej_sdep_{tx_id}")]
        ])
    )

    await update.message.reply_text("✅ تم إرسال طلب الشحن للموقع للإدارة بنجاح.")
    return ConversationHandler.END

async def site_withdraw_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    min_sw = float(get_setting("min_site_withdraw") or 10000)
    await update.message.reply_text(f"🌐 أدخل المبلغ المراد سحبه من الموقع إلى البوت (الحد الأدنى {min_sw:,.0f}):")
    return SITE_WIT_AMT

async def site_withdraw_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    try:
        amount = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ أدخل رقماً صحيحاً:")
        return SITE_WIT_AMT

    conn = sqlite3.connect("wayxbet_pro.db")
    cursor = conn.cursor()
    cursor.execute("SELECT wayxbet_account FROM users WHERE user_id = ?", (user.id,))
    res = cursor.fetchone()
    
    if not res or not res[0]:
        conn.close()
        await update.message.reply_text("❌ يجب عليك إنشاء حساب في الموقع أولاً.")
        return ConversationHandler.END

    wayx_acc = res[0]
    cursor.execute("INSERT INTO transactions (user_id, type, method, amount, account_num) VALUES (?, 'site_withdraw', 'site_to_bot', ?, ?)",
                   (user.id, amount, wayx_acc))
    conn.commit()
    tx_id = cursor.lastrowid
    conn.close()

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"🌐 **طلب سحب من الموقع (#{tx_id})**\n👤 المستخدم: {user.full_name} (`{user.id}`)\n🏷 الحساب: `{wayx_acc}`\n💰 المبلغ: {format_currency(amount)}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ موافقة", callback_data=f"app_swit_{tx_id}"),
             InlineKeyboardButton("❌ رفض", callback_data=f"rej_swit_{tx_id}")]
        ])
    )

    await update.message.reply_text("✅ تم إرسال طلب سحب الرصيد من الموقع للإدارة بنجاح.")
    return ConversationHandler.END

# ----------------- لوحة الإدارة الشاملة -----------------
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return

    keyboard = [
        [InlineKeyboardButton("⚙️ إعدادات البونص والحدود", callback_data="adm_settings")],
        [InlineKeyboardButton("📋 سجلات الطلبات", callback_data="adm_logs")],
        [InlineKeyboardButton("👥 إدارة المستخدمين", callback_data="adm_users")],
        [InlineKeyboardButton("🎁 إدارة الأكواد والمسابقات", callback_data="adm_gifts")],
        [InlineKeyboardButton("📢 الإذاعة والرسائل", callback_data="adm_broadcast")]
    ]
    await update.message.reply_text("🛠 **لوحة التحكم الإدارية الاحترافية:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def admin_callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user = update.effective_user
    if not is_admin(user.id):
        await query.answer("غير مسموح لك!", show_alert=True)
        return

    # معالجة الموافقات والرفض مع طلب اسم الأدمن
    if data.startswith("app_acc_") or data.startswith("rej_acc_") or data.startswith("app_dep_") or data.startswith("rej_dep_") or data.startswith("app_sdep_") or data.startswith("rej_sdep_") or data.startswith("app_swit_") or data.startswith("rej_swit_"):
        context.user_data['pending_admin_action'] = data
        await query.message.reply_text("✍️ يرجى إرسال **اسمك الإداري** لإتمام هذه العملية:", parse_mode="Markdown")
        context.user_data['awaiting_admin_name_state'] = True
        return

    if data == "adm_settings":
        kb = [
            [InlineKeyboardButton("تعديل حسابات الشحن", callback_data="set_accs")],
            [InlineKeyboardButton("تعديل الحد الأدنى للسحب/الشحن", callback_data="set_limits")],
            [InlineKeyboardButton("تعديل البونص والنسب", callback_data="set_bonus")]
        ]
        await query.message.edit_text("⚙️ **إعدادات البوت:**", reply_markup=InlineKeyboardMarkup(kb))
    
    elif data == "adm_logs":
        kb = [
            [InlineKeyboardButton("سجل الشحن", callback_data="log_dep"), InlineKeyboardButton("سجل السحب", callback_data="log_wit")],
            [InlineKeyboardButton("سجل انشاء الحسابات", callback_data="log_accs")],
            [InlineKeyboardButton("سجل موقع (سحب/شحن)", callback_data="log_site")]
        ]
        await query.message.edit_text("📋 **سجلات النظام:**", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "adm_users":
        kb = [
            [InlineKeyboardButton("عدد المستخدمين", callback_data="usr_count"), InlineKeyboardButton("تفاصيل لاعب", callback_data="usr_details")],
            [InlineKeyboardButton("إضافة رصيد", callback_data="usr_add_bal"), InlineKeyboardButton("خصم رصيد", callback_data="usr_sub_bal")],
            [InlineKeyboardButton("حظر مستخدم", callback_data="usr_ban"), InlineKeyboardButton("إلغاء الحظر", callback_data="usr_unban")]
        ]
        await query.message.edit_text("👥 **إدارة المستخدمين:**", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "usr_count":
        conn = sqlite3.connect("wayxbet_pro.db")
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        cnt = cursor.fetchone()[0]
        conn.close()
        await query.answer(f"📊 إجمالي عدد مستخدمين البوت: {cnt}", show_alert=True)

# استلام اسم الأدمن لإتمام العملية
async def admin_name_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_admin_name_state'):
        return
    
    admin_name = update.message.text.strip()
    action = context.user_data.get('pending_admin_action')
    context.user_data['awaiting_admin_name_state'] = False

    conn = sqlite3.connect("wayxbet_pro.db")
    cursor = conn.cursor()

    parts = action.split("_")
    action_type = parts[0] # app or rej
    target = parts[1] # acc, dep, sdep, swit
    req_id = parts[2]

    if target == "acc":
        cursor.execute("SELECT user_id, wayxbet_user FROM account_requests WHERE id = ?", (req_id,))
        res = cursor.fetchone()
        if res:
            u_id, w_user = res
            if action_type == "app":
                cursor.execute("UPDATE users SET wayxbet_account = ? WHERE user_id = ?", (w_user, u_id))
                cursor.execute("UPDATE account_requests SET status = 'approved', admin_name = ? WHERE id = ?", (admin_name, req_id))
                conn.commit()
                await context.bot.send_message(chat_id=u_id, text=f"🎉 تمت الموافقة على حسابك بواسطة ({admin_name})! يمكنك الشحن الآن.\nحسابك المثبت: `{w_user}`", parse_mode="Markdown")
            else:
                cursor.execute("UPDATE account_requests SET status = 'rejected', admin_name = ? WHERE id = ?", (admin_name, req_id))
                conn.commit()
                await context.bot.send_message(chat_id=u_id, text=f"❌ نأسف، تم رفض طلب إنشاء الحساب بواسطة ({admin_name}).")

    elif target in ["dep", "sdep", "swit"]:
        cursor.execute("SELECT user_id, amount, type FROM transactions WHERE id = ?", (req_id,))
        res = cursor.fetchone()
        if res:
            u_id, amt, t_type = res
            if action_type == "app":
                cursor.execute("UPDATE transactions SET status = 'approved', admin_name = ? WHERE id = ?", (admin_name, req_id))
                if t_type == "deposit" or t_type == "site_withdraw":
                    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amt, u_id))
                conn.commit()
                await context.bot.send_message(chat_id=u_id, text=f"✅ تمت الموافقة على معاملتك المالية بواسطة الإداري: {admin_name}")
            else:
                cursor.execute("UPDATE transactions SET status = 'rejected', admin_name = ? WHERE id = ?", (admin_name, req_id))
                conn.commit()
                await context.bot.send_message(chat_id=u_id, text=f"❌ تم رفض معاملتك المالية بواسطة الإداري: {admin_name}")

    conn.close()
    await update.message.reply_text(f"✅ تم تنفيذ الطلب وتوثيق اسم الأدمن ({admin_name}) بنجاح.")

# ----------------- تشغيل النظام -----------------
if __name__ == "__main__":
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CAPTCHA_Q: [MessageHandler(filters.TEXT & ~filters.COMMAND, captcha_question_handler)],
            CAPTCHA_PIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, captcha_pin_handler)],
            GET_CONTACT: [MessageHandler(filters.CONTACT, contact_handler)],
            ACC_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_acc_name)],
            ACC_PASS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_acc_pass)],
            WITHDRAW_METHOD: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_method_chosen)],
            WITHDRAW_ACC: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_acc_received)],
            WITHDRAW_AMT: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_amt_received)],
            WITHDRAW_SPEED: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_speed_chosen)],
            DEPOSIT_METHOD: [MessageHandler(filters.TEXT & ~filters.COMMAND, deposit_method_chosen)],
            DEPOSIT_TX: [MessageHandler(filters.TEXT & ~filters.COMMAND, deposit_tx_received)],
            DEPOSIT_AMT: [MessageHandler(filters.TEXT & ~filters.COMMAND, deposit_amt_received)],
            SITE_DEP_AMT: [MessageHandler(filters.TEXT & ~filters.COMMAND, site_deposit_received)],
            SITE_WIT_AMT: [MessageHandler(filters.TEXT & ~filters.COMMAND, site_withdraw_received)],
            GIFT_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, gift_code_received)],
            SUPPORT_INPUT: [MessageHandler(filters.ALL & ~filters.COMMAND, support_received)],
        },
        fallbacks=[CommandHandler("start", start)]
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CallbackQueryHandler(admin_callback_router))
    
    # معالجات الأزرار الرئيسية في القائمة
    app.add_handler(MessageHandler(filters.Text(["WayxBet"]), wayxbet_menu_entry))
    app.add_handler(MessageHandler(filters.Text(["سحب رصيد"]), withdraw_start))
    app.add_handler(MessageHandler(filters.Text(["شحن رصيد"]), deposit_start))
    app.add_handler(MessageHandler(filters.Text(["احالاتي"]), referrals_menu))
    app.add_handler(MessageHandler(filters.Text(["عجلة الحظ 🎡"]), lucky_wheel_menu))
    app.add_handler(MessageHandler(filters.Text(["المسابقات الحالية"]), current_competitions))
    app.add_handler(MessageHandler(filters.Text(["تواصل مع الدعم"]), support_start))
    app.add_handler(MessageHandler(filters.Text(["كود هدية"]), gift_code_start))
    app.add_handler(MessageHandler(filters.Text(["شحن رصيد من البوت للموقع"]), site_deposit_start))
    app.add_handler(MessageHandler(filters.Text(["سحب رصيد من الموقع للبوت"]), site_withdraw_start))
    app.add_handler(MessageHandler(filters.Text(["🛠 لوحة الإدارة"]), admin_panel))
    
    # التقاط اسم الأدمن عند اتخاذ إجراء
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, admin_name_received))

    print("🚀 بوت ROZ WAYXBET يعمل بكامل طاقته الآن...")
    app.run_polling()

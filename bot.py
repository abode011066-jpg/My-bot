import logging
import sqlite3
import re
import json
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

# ----------------- الإعدادات العامة -----------------
TOKEN = "ضع_توكن_البوت_هنا"
ADMIN_ID = 7255100997
CHANNEL_BOT = "@cashinsher"
CHANNEL_PROG = "@lerafree"
WHEEL_URL = "https://wayxbet10.com/wheel" # رابط ملفات العجلة على الويب

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ----------------- حالات المحادثة الكاملة (Conversation States) -----------------
(
    GET_CONTACT, ACC_NAME, ACC_PASS, 
    WITHDRAW_METHOD, WITHDRAW_ACC, WITHDRAW_AMT, WITHDRAW_SPEED, 
    DEPOSIT_METHOD, DEPOSIT_TX, DEPOSIT_AMT, 
    SITE_DEP_AMT, SITE_WITH_AMT, 
    GIFT_INPUT, SUPPORT_INPUT, ADMIN_REPLY, 
    ADMIN_NAME_CONFIRM, ADMIN_BROADCAST, ADMIN_PRIVATE_ID, ADMIN_PRIVATE_MSG,
    ADMIN_GIFT_CODE, ADMIN_GIFT_AMT, ADMIN_ADD_ADMIN, ADMIN_BALANCE_ID, ADMIN_BALANCE_AMT,
    ADMIN_BAN_ID, ADMIN_UNBAN_ID, ADMIN_VIEW_USER, ADMIN_SETTING_KEY, ADMIN_SETTING_VAL
) = range(29)

# ----------------- قاعدة البيانات الشاملة -----------------
def init_db():
    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    
    # جدول المستخدمين
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
    
    # جدول الإعدادات
    c.execute("""CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )""")
    
    # جدول الطلبات (سحب، شحن، حساب، موقع)
    c.execute("""CREATE TABLE IF NOT EXISTS requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        type TEXT,
        method TEXT,
        amount REAL,
        tx_id TEXT,
        account_num TEXT,
        speed TEXT,
        status TEXT DEFAULT 'pending',
        admin_name TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    
    # جدول أكواد الهدايا
    c.execute("""CREATE TABLE IF NOT EXISTS gift_codes (
        code TEXT PRIMARY KEY,
        amount REAL,
        used INTEGER DEFAULT 0,
        used_by INTEGER
    )""")

    # جدول التذاكر والدعم الفني
    c.execute("""CREATE TABLE IF NOT EXISTS support_tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        message TEXT,
        file_id TEXT,
        status TEXT DEFAULT 'open',
        reply TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    # جدول المسابقات الحالية
    c.execute("""CREATE TABLE IF NOT EXISTS competitions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        text TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    # جدول الأدمنز
    c.execute("""CREATE TABLE IF NOT EXISTS admins (
        admin_id INTEGER PRIMARY KEY
    )""")
    
    # القيم الافتراضية للإعدادات
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
        "wheel_prize_1": "30",
        "wheel_prize_2": "40",
        "wheel_prize_3": "30"
    }
    for k, v in defaults.items():
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
        
    c.execute("INSERT OR IGNORE INTO admins (admin_id) VALUES (?)", (ADMIN_ID,))
    conn.commit()
    conn.close()

init_db()

# ----------------- دوال المساعدة (Helpers) -----------------
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

# ----------------- واجهة الأزرار الشفافة الرئيسية -----------------
def main_menu_keyboard(user_id, wayx_account):
    acc_text = f"حسابك: {wayx_account}" if wayx_account else "WayxBet (إنشاء حساب)"
    kb = [
        [InlineKeyboardButton(f"🎮 {acc_text}", callback_data="wayx_acc_menu")],
        [InlineKeyboardButton("💵 سحب رصيد", callback_data="withdraw_menu"), 
         InlineKeyboardButton("💳 شحن رصيد", callback_data="deposit_menu")],
        [InlineKeyboardButton("👥 إحالاتي", callback_data="refs_menu"), 
         InlineKeyboardButton("🎡 عجلة الحظ", web_app=WebAppInfo(url=WHEEL_URL))],
        [InlineKeyboardButton("🔄 شحن من البوت للموقع", callback_data="site_dep_menu"), 
         InlineKeyboardButton("🔄 سحب من الموقع للبوت", callback_data="site_wit_menu")],
        [InlineKeyboardButton("🎁 كود هدية", callback_data="gift_menu"), 
         InlineKeyboardButton("🏆 المسابقات الحالية", callback_data="comps_menu")],
        [InlineKeyboardButton("👨‍💻 قناة المبرمج", url=f"https://t.me/{CHANNEL_PROG[1:]}"), 
         InlineKeyboardButton("🎧 تواصل مع الدعم", callback_data="support_menu")]
    ]
    if is_admin(user_id):
        kb.append([InlineKeyboardButton("🛠 لوحة الإدارة (الوحش)", callback_data="admin_panel")])
    return InlineKeyboardMarkup(kb)

# ----------------- نظام البدء والاشتراك الإجباري -----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ عذراً، حسابك محظور من استخدام البوت.")
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
        
        # إشعار الأدمن بدخول مستخدم جديد
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
            [InlineKeyboardButton("قناة البوت 📢", url=f"https://t.me/{CHANNEL_BOT[1:]}")],
            [InlineKeyboardButton("قناة المبرمج 👨‍💻", url=f"https://t.me/{CHANNEL_PROG[1:]}")],
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
        ref_id = db_user[1]
        
        # منح مكافأة الإحالة (لفة عجلة) إذا كانت مفعلة
        if ref_id and get_setting("ref_spin_active") == "1":
            c.execute("UPDATE users SET spins = spins + 1, active_refs = active_refs + 1 WHERE user_id = ?", (ref_id,))
            try:
                await context.bot.send_message(
                    chat_id=ref_id,
                    text=f"🔔 انضم شخص جديد ({user.full_name}) عبر رابط إحالتك!\n🎁 تم منحك لفة عجلة مجانية."
                )
                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=f"👥 **إحالة جديدة:**\nالمُحيل: `{ref_id}`\nالعضو الجديد: `{user_id}` ({user.full_name})",
                    parse_mode="Markdown"
                )
            except:
                pass
        conn.commit()

    conn.close()
    await query.message.delete()

    if db_user and not db_user[2]: # لم يرسل رقمه بعد
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
    
    bonus_active = get_setting("welcome_bonus_active") == "1"
    welcome_bonus = float(get_setting("welcome_bonus") or 0) if bonus_active else 0
    
    c.execute("UPDATE users SET phone = ?, balance = balance + ? WHERE user_id = ?", (phone, welcome_bonus, user.id))
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
        f"**ROZ WAYXBET** 🚀\n\n"
        f"💰 رصيدك: {format_currency(balance)}\n"
        f"🆔 ايدي حسابك: `{user_id}`"
    )

    await message_obj.reply_text(text, reply_markup=main_menu_keyboard(user_id, wayx_acc), parse_mode="Markdown")
    return ConversationHandler.END
# ----------------- 1. قسم حساب WayxBet -----------------
async def wayxbet_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("SELECT wayxbet_account FROM users WHERE user_id = ?", (user.id,))
    res = c.fetchone()
    conn.close()

    if res and res[0]:
        await query.edit_message_text(
            f"✅ حسابك في الموقع مسجل بالفعل:\n`{res[0]}`\n\n(يمكنك نسخه بالضغط عليه)",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]])
        )
        return ConversationHandler.END

    await query.edit_message_text(
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

    # إرسال الطلب للأدمن
    kb = InlineKeyboardMarkup([
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
        reply_markup=kb
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

async def withdraw_method_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    method = "سيريتل كاش" if "syriatel" in query.data else "شام كاش"
    context.user_data['wit_method'] = method

    await query.edit_message_text(f"📌 أرسل رقم الحساب أو المحفظة ({method}) المراد السحب إليها:")
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
        await update.message.reply_text(f"❌ المبلغ أقل من الحد الأدنى للسحب ({min_w:,.0f} ليرة). أعد الإدخال:")
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

    speed_type = query.data.split("_")[2] # fast or slow
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

    wayx_acc = res[0] if res else ""
    balance = res[1] if res else 0

    if balance < amount:
        await query.edit_message_text("❌ رصيدك غير كافي لإتمام هذا السحب!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]]))
        return ConversationHandler.END

    summary = (
        f"📋 **تفاصيل طلب السحب:**\n"
        f"🏷 حساب الموقع: `{wayx_acc}`\n"
        f"💳 الطريقة: {context.user_data['wit_method']}\n"
        f"🔢 رقم الحساب: `{context.user_data['wit_acc']}`\n"
        f"💰 المبلغ المطلوب: {format_currency(amount)}\n"
        f"⚡ نوع الطلب: {context.user_data['wit_speed_str']}\n"
        f"📉 العمولة: {format_currency(fee)}\n"
        f"💵 المبلغ الصافي بعد الخصم: {format_currency(net_amount)}"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تأكيد السحب", callback_data="wit_confirm_final")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="back_home")]
    ])
    await query.edit_message_text(summary, parse_mode="Markdown", reply_markup=kb)
    return WITHDRAW_SPEED

async def withdraw_confirm_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    amount = context.user_data['wit_amt']
    method = context.user_data['wit_method']
    acc = context.user_data['wit_acc']
    speed = context.user_data['wit_speed_str']
    net = context.user_data['wit_net']

    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("SELECT wayxbet_account, balance FROM users WHERE user_id = ?", (user.id,))
    res = c.fetchone()
    if not res or res[1] < amount:
        conn.close()
        await query.edit_message_text("❌ حدث خطأ أو الرصيد غير كافٍ.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]]))
        return ConversationHandler.END

    wayx_acc = res[0]

    c.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user.id))
    
    info = f"حساب Wayx: {wayx_acc} | الطريقة: {method} | الرقم: {acc} | الصافي: {net} | النوع: {speed}"
    c.execute("INSERT INTO requests (user_id, type, amount, info) VALUES (?, ?, ?, ?)",
              (user.id, 'withdraw', amount, info))
    req_id = c.lastrowid
    conn.commit()
    conn.close()

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ موافقة", callback_data=f"adm_app_wit_{req_id}_{user.id}_{amount}"),
         InlineKeyboardButton("❌ رفض", callback_data=f"adm_rej_wit_{req_id}_{user.id}_{amount}")]
    ])
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📤 **طلب سحب جديد (#{req_id})**\n\n"
             f"👤 الايدي: `{user.id}`\n"
             f"🏷 حساب الموقع: `{wayx_acc}`\n"
             f"💳 الطريقة: {method}\n"
             f"🔢 الرقم: `{acc}`\n"
             f"💰 المبلغ: {format_currency(amount)}\n"
             f"💵 الصافي: {format_currency(net)}\n"
             f"⚡ النوع: {speed}",
        parse_mode="Markdown",
        reply_markup=kb
    )

    await query.edit_message_text(
        "✅ تم إرسال طلب السحب بنجاح وهو قيد المراجعة من الإدارة.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="back_home")]])
    )
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
            "❌ يجب إنشاء حساب WayxBet أولاً لتتمكن من شحن الرصيد!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]])
        )
        return ConversationHandler.END

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("سيريتل كاش", callback_data="dep_meth_syriatel"),
         InlineKeyboardButton("شام كاش", callback_data="dep_meth_sham")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]
    ])
    await query.edit_message_text("💳 اختر طريقة الشحن:", reply_markup=kb)

async def deposit_method_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    is_sham = "sham" in query.data
    method = "شام كاش" if is_sham else "سيريتل كاش"
    context.user_data['dep_method'] = method

    target_acc = get_setting("sham_num") if is_sham else get_setting("syriatel_num")

    text = (
        f"💳 **شحن رصيد عبر {method}**\n\n"
        f"قم بتحويل المبلغ المطلوبة إلى الحساب التالي:\n"
        f"`{target_acc}`\n\n"
        f"ثم أرسل **رقم العملية** أو تفاصيل التحويل هنا:"
    )
    await query.edit_message_text(text, parse_mode="Markdown")
    return DEPOSIT_TX

async def deposit_tx_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['dep_tx'] = update.message.text.strip()
    min_d = float(get_setting("min_deposit") or 5000)
    await update.message.reply_text(f"💵 أدخل المبلغ الذي قمت بتحويله (الحد الأدنى {min_d:,.0f} ليرة):")
    return DEPOSIT_AMT

async def deposit_amt_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    try:
        amount = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ يرجى إدخال رقم صحيح للمبلغ:")
        return DEPOSIT_AMT

    min_d = float(get_setting("min_deposit") or 5000)
    if amount < min_d:
        await update.message.reply_text(f"❌ المبلغ أقل من الحد الأدنى للشحن ({min_d:,.0f} ليرة). أعد الإدخال:")
        return DEPOSIT_AMT

    method = context.user_data['dep_method']
    tx_id = context.user_data['dep_tx']

    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("SELECT wayxbet_account FROM users WHERE user_id = ?", (user.id,))
    res = c.fetchone()
    conn.close()
    wayx_acc = res[0] if res else ""

    info = f"حساب Wayx: {wayx_acc} | الطريقة: {method} | رقم العملية: {tx_id}"
    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("INSERT INTO requests (user_id, type, amount, info) VALUES (?, ?, ?, ?)",
              (user.id, 'deposit', amount, info))
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
             f"👤 الايدي: `{user.id}`\n"
             f"🏷 حساب الموقع: `{wayx_acc}`\n"
             f"💳 الطريقة: {method}\n"
             f"🔢 رقم العملية: `{tx_id}`\n"
             f"💰 المبلغ: {format_currency(amount)}",
        parse_mode="Markdown",
        reply_markup=kb
    )

    await update.message.reply_text(
        "✅ تم استلام طلبك قيد المراجعة من الإدارة.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="back_home")]])
    )
    return ConversationHandler.END


# ----------------- 4. الشحن والسحب من وإلى الموقع -----------------
async def site_dep_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("SELECT wayxbet_account FROM users WHERE user_id = ?", (query.from_user.id,))
    res = c.fetchone()
    conn.close()

    if not res or not res[0]:
        await query.edit_message_text(
            "❌ يجب إنشاء حساب WayxBet أولاً!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]])
        )
        return ConversationHandler.END

    min_sd = float(get_setting("min_site_deposit") or 5000)
    await query.edit_message_text(f"🔄 أدخل المبلغ المراد شحنه من البوت إلى الموقع (الحد الأدنى {min_sd:,.0f}):")
    return SITE_DEP_AMT

async def site_dep_amt_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    try:
        amount = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ أدخل مبلغاً صحيحاً:")
        return SITE_DEP_AMT

    min_sd = float(get_setting("min_site_deposit") or 5000)
    if amount < min_sd:
        await update.message.reply_text(f"❌ المبلغ أقل من الحد الأدنى ({min_sd:,.0f}). أعد الإدخال:")
        return SITE_DEP_AMT

    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("SELECT balance, wayxbet_account FROM users WHERE user_id = ?", (user.id,))
    res = c.fetchone()
    if not res or res[0] < amount:
        conn.close()
        await update.message.reply_text("❌ رصيدك في البوت غير كافي!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]]))
        return ConversationHandler.END

    balance, wayx_acc = res[0], res[1]
    c.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user.id))

    c.execute("INSERT INTO requests (user_id, type, amount, info) VALUES (?, ?, ?, ?)",
              (user.id, 'site_deposit', amount, f"شحن للموقع لحساب: {wayx_acc}"))
    req_id = c.lastrowid
    conn.commit()
    conn.close()

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ موافقة", callback_data=f"adm_app_sitedep_{req_id}_{user.id}_{amount}"),
         InlineKeyboardButton("❌ رفض", callback_data=f"adm_rej_sitedep_{req_id}_{user.id}_{amount}")]
    ])
    await context.bot.send_message(
        ADMIN_ID,
        f"📥 **طلب شحن للموقع (#{req_id})**\nحساب الموقع: `{wayx_acc}`\nالمبلغ: {format_currency(amount)}\nالايدي: `{user.id}`",
        parse_mode="Markdown", reply_markup=kb
    )

    await update.message.reply_text("⏳ تم إرسال طلب الشحن للموقع للإدارة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="back_home")]]))
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
    await query.edit_message_text(f"🔄 أدخل المبلغ المراد سحبه من الموقع للبوت (الحد الأدنى {min_sw:,.0f}):")
    return SITE_WITH_AMT

async def site_wit_amt_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    try:
        amount = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ أدخل مبلغاً صحيحاً:")
        return SITE_WITH_AMT

    min_sw = float(get_setting("min_site_withdraw") or 10000)
    if amount < min_sw:
        await update.message.reply_text(f"❌ المبلغ أقل من الحد الأدنى ({min_sw:,.0f}). أعد الإدخال:")
        return SITE_WITH_AMT

    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("SELECT wayxbet_account FROM users WHERE user_id = ?", (user.id,))
    res = c.fetchone()
    wayx_acc = res[0] if res else ""
    conn.close()

    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("INSERT INTO requests (user_id, type, amount, info) VALUES (?, ?, ?, ?)",
              (user.id, 'site_withdraw', amount, f"سحب من الموقع لحساب: {wayx_acc}"))
    req_id = c.lastrowid
    conn.commit()
    conn.close()

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ موافقة", callback_data=f"adm_app_sitewit_{req_id}_{user.id}_{amount}"),
         InlineKeyboardButton("❌ رفض", callback_data=f"adm_rej_sitewit_{req_id}_{user.id}")]
    ])
    await context.bot.send_message(
        ADMIN_ID,
        f"📥 **طلب سحب من الموقع (#{req_id})**\nحساب الموقع: `{wayx_acc}`\nالمبلغ: {format_currency(amount)}\nالايدي: `{user.id}`",
        parse_mode="Markdown", reply_markup=kb
    )

    await update.message.reply_text("⏳ تم إرسال طلب سحب الرصيد من الموقع للإدارة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="back_home")]]))
    return ConversationHandler.END
# ----------------- 1. نظام إحالاتي -----------------
async def refs_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("SELECT active_refs, active_ops, spins FROM users WHERE user_id = ?", (user.id,))
    res = c.fetchone()
    conn.close()

    active_refs = res[0] if res else 0
    active_ops = res[1] if res else 0
    spins = res[2] if res else 0

    bot_user = (await context.bot.get_me()).username
    ref_link = f"https://t.me/{bot_user}?start={user.id}"

    text = (
        f"👥 **نظام الإحالات الخاص بك:**\n\n"
        f"🔗 رابط الإحالة الخاص بك:\n`{ref_link}`\n\n"
        f"📊 عدد الإحالات الكلية/النشطة: {active_refs}\n"
        f"⚙️ عدد العمليات النشطة (لشحن عمولة 5%): {active_ops}\n"
        f"🎡 عدد لفات العجلة المتاحة: {spins}\n\n"
        f"💡 شارك الرابط مع أصدقائك واكسب لفات مجانية لكل إحالة ناجحة!"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]])
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)


# ----------------- 2. نظام أكواد الهدايا -----------------
async def gift_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🎁 أدخل كود الهدية الخاص بك هنا:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]])
    )
    return GIFT_INPUT

async def gift_input_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    code = update.message.text.strip()

    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("SELECT amount, used FROM gift_codes WHERE code = ?", (code,))
    res = c.fetchone()

    if not res:
        conn.close()
        await update.message.reply_text(
            "❌ كود الهدية غير صالح أو غير موجود.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="back_home")]])
        )
        return ConversationHandler.END

    amount, used = res[0], res[1]
    if used == 1:
        conn.close()
        await update.message.reply_text(
            "❌ تم استخدام هذا الكود مسبقاً!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="back_home")]])
        )
        return ConversationHandler.END

    c.execute("UPDATE gift_codes SET used = 1, used_by = ? WHERE code = ?", (user.id, code))
    c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user.id))
    conn.commit()
    conn.close()

    # إشعار الأدمن بمن استخدم الهدية
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🎁 **استخدام كود هدية:**\n"
                 f"👤 المستخدم: {user.full_name} (`{user.id}`)\n"
                 f"🏷 الكود: `{code}`\n"
                 f"💰 المبلغ المضاف: {format_currency(amount)}",
            parse_mode="Markdown"
        )
    except:
        pass

    await update.message.reply_text(
        f"✅ مبروك! تم شحن الكود بنجاح وإضافة {format_currency(amount)} إلى رصيدك.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="back_home")]])
    )
    return ConversationHandler.END


# ----------------- 3. نظام تواصل مع الدعم -----------------
async def support_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🎧 أرسل رسالتك النصية أو صورتك للدعم الفني، وسيقوم الأدمن بالرد عليك فوراً:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]])
    )
    return SUPPORT_INPUT

async def support_msg_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text or update.message.caption or "بدون نص"
    file_id = None
    if update.message.photo:
        file_id = update.message.photo[-1].file_id

    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("INSERT INTO support_tickets (user_id, message, file_id) VALUES (?, ?, ?)",
              (user.id, text, file_id))
    ticket_id = c.lastrowid
    conn.commit()
    conn.close()

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✍️ الرد على المستخدم", callback_data=f"adm_reply_{ticket_id}_{user.id}")]])
    
    if file_id:
        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=file_id,
            caption=f"🎧 **رسالة دعم جديدة (#{ticket_id})**\n"
                    f"👤 من: {user.full_name} (`{user.id}`)\n"
                    f"💬 النص: {text}",
            parse_mode="Markdown",
            reply_markup=kb
        )
    else:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🎧 **رسالة دعم جديدة (#{ticket_id})**\n"
                 f"👤 من: {user.full_name} (`{user.id}`)\n"
                 f"💬 النص: {text}",
            parse_mode="Markdown",
            reply_markup=kb
        )

    await update.message.reply_text(
        "✅ تم إرسال رسالتك إلى الدعم الفني بنجاح وسيتم الرد عليك قريباً.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="back_home")]])
    )
    return ConversationHandler.END


# ----------------- 4. نظام المسابقات الحالية -----------------
async def comps_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("SELECT id, text, created_at FROM competitions ORDER BY id DESC LIMIT 5")
    comps = c.fetchall()
    conn.close()

    if not comps:
        text = "🏆 لا توجد مسابقات حالية مضافة في الوقت الحالي."
    else:
        text = "🏆 **المسابقات الحالية:**\n\n"
        for comp in comps:
            text += f"🔹 **مسابقة #{comp[0]}**\n{comp[1]}\n⏳ التاريخ: {comp[2]}\n\n-------------------\n"

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]])
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)


# ----------------- 5. زر الرجوع للقائمة الرئيسية -----------------
async def back_home_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
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
        f"**ROZ WAYXBET** 🚀\n\n"
        f"💰 رصيدك: {format_currency(balance)}\n"
        f"🆔 ايدي حسابك: `{user_id}`"
    )
    await query.edit_message_text(text, reply_markup=main_menu_keyboard(user_id, wayx_acc), parse_mode="Markdown")
# ----------------- 1. لوحة الإدارة الرئيسية -----------------
async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("❌ لست مديراً للبوت!", show_alert=True)
        return

    kb = [
        [InlineKeyboardButton("⚙️ إعدادات البونص والحدود", callback_data="adm_settings_menu")],
        [InlineKeyboardButton("💳 تغيير حسابات الشحن", callback_data="adm_wallets_menu")],
        [InlineKeyboardButton("🎁 إنشاء كود هدية", callback_data="adm_create_gift"),
         InlineKeyboardButton("➕ إضافة أدمن", callback_data="adm_add_admin_start")],
        [InlineKeyboardButton("📊 سجلات الطلبات (سحب/شحن)", callback_data="adm_logs_menu"),
         InlineKeyboardButton("👥 تفاصيل وحسابات اللاعبين", callback_data="adm_users_menu")],
        [InlineKeyboardButton("💰 إضافة/خصم رصيد", callback_data="adm_balance_menu"),
         InlineKeyboardButton("🚫 حظر/فك حظر مستخدم", callback_data="adm_ban_menu")],
        [InlineKeyboardButton("📢 إذاعة عامة", callback_data="adm_broadcast_start"),
         InlineKeyboardButton("✉️ رسالة خاصة لمستخدم", callback_data="adm_private_start")],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="back_home")]
    ]
    await query.edit_message_text("🛠 **لوحة التحكم الإدارية (الوحش):**\nاختر القسم المطلوب:", reply_markup=InlineKeyboardMarkup(kb))

# ----------------- إعدادات الإدارة -----------------
async def adm_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    kb = [
        [InlineKeyboardButton(f"البونص الترحيبي: {get_setting('welcome_bonus')} ({'مفعل' if get_setting('welcome_bonus_active')=='1' else 'متوقف'})", callback_data="adm_set_welcome")],
        [InlineKeyboardButton(f"بونص الشحن: {get_setting('deposit_bonus')}% ({'مفعل' if get_setting('deposit_bonus_active')=='1' else 'متوقف'})", callback_data="adm_set_deposit_bonus")],
        [InlineKeyboardButton(f"الحد الأدنى للسحب: {get_setting('min_withdraw')}", callback_data="adm_set_min_wit")],
        [InlineKeyboardButton(f"الحد الأدنى للشحن: {get_setting('min_deposit')}", callback_data="adm_set_min_dep")],
        [InlineKeyboardButton(f"الحد الأدنى لسحب الموقع: {get_setting('min_site_withdraw')}", callback_data="adm_set_min_sitewit")],
        [InlineKeyboardButton(f"الحد الأدنى لشحن الموقع: {get_setting('min_site_deposit')}", callback_data="adm_set_min_sitedep")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]
    ]
    await query.edit_message_text("⚙️ **إعدادات النظام والحدود:**\nاضغط على الإعداد لتعديله:", reply_markup=InlineKeyboardMarkup(kb))

async def adm_setting_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    key_map = {
        "adm_set_welcome": "welcome_bonus",
        "adm_set_deposit_bonus": "deposit_bonus",
        "adm_set_min_wit": "min_withdraw",
        "adm_set_min_dep": "min_deposit",
        "adm_set_min_sitewit": "min_site_withdraw",
        "adm_set_min_sitedep": "min_site_deposit"
    }
    key = key_map.get(data)
    context.user_data['editing_setting'] = key
    await query.edit_message_text(f"✏️ أدخل القيمة الجديدة للإعداد (`{key}`):", parse_mode="Markdown")
    return ADMIN_SETTING_VAL

async def adm_setting_val_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = context.user_data.get('editing_setting')
    val = update.message.text.strip()
    set_setting(key, val)
    await update.message.reply_text(f"✅ تم تحديث `{key}` إلى `{val}` بنجاح.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 لوحة الإدارة", callback_data="admin_panel")]]))
    return ConversationHandler.END

async def adm_wallets_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    kb = [
        [InlineKeyboardButton(f"سيريتل كاش: {get_setting('syriatel_num')}", callback_data="adm_set_syriatel")],
        [InlineKeyboardButton(f"شام كاش: {get_setting('sham_num')}", callback_data="adm_set_sham")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]
    ]
    await query.edit_message_text("💳 **تعديل حسابات الشحن:**", reply_markup=InlineKeyboardMarkup(kb))

# ----------------- أكواد الهدايا والأدمنز وإدارة الرصيد -----------------
async def adm_create_gift_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.edit_message_text("🎁 أدخل كود الهدية الجديد (مثال: `ROZ2026`):", parse_mode="Markdown")
    return ADMIN_GIFT_CODE

async def adm_gift_code_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_gift_code'] = update.message.text.strip()
    await update.message.reply_text("💵 أدخل مبلغ الهدية (القيمة بالليرات القديمة):")
    return ADMIN_GIFT_AMT

async def adm_gift_amt_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = context.user_data.get('new_gift_code')
    try:
        amount = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ أدخل رقماً صحيحاً للمبلغ:")
        return ADMIN_GIFT_AMT

    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO gift_codes (code, amount, used) VALUES (?, ?, 0)", (code, amount))
    conn.commit()
    conn.close()

    await update.message.reply_text(f"✅ تم إنشاء كود الهدية `{code}` بقيمة {format_currency(amount)} بنجاح.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 لوحة الإدارة", callback_data="admin_panel")]]), parse_mode="Markdown")
    return ConversationHandler.END

async def adm_add_admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.edit_message_text("➕ أدخل الايدي (User ID) الخاص بالمستخدم المراد إضافته كأدمن:")
    return ADMIN_ADD_ADMIN

async def adm_add_admin_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        new_admin_id = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ ايدي غير صحيح:")
        return ADMIN_ADD_ADMIN

    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO admins (admin_id) VALUES (?)", (new_admin_id,))
    conn.commit()
    conn.close()

    await update.message.reply_text(f"✅ تم تعيين المستخدم `{new_admin_id}` كأدمن جديد بنجاح.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 لوحة الإدارة", callback_data="admin_panel")]]), parse_mode="Markdown")
    return ConversationHandler.END

# إدارة الرصيد (إضافة / خصم)
async def adm_balance_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.edit_message_text("💰 أدخل ايدي المستخدم المراد تعديل رصيده:")
    return ADMIN_BALANCE_ID

async def adm_balance_id_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        target_id = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ ايدي غير صحيح:")
        return ADMIN_BALANCE_ID

    context.user_data['target_balance_id'] = target_id
    kb = [
        [InlineKeyboardButton("➕ إضافة رصيد", callback_data="bal_op_add"),
         InlineKeyboardButton("➖ خصم رصيد", callback_data="bal_op_sub")]
    ]
    await update.message.reply_text("اختر عملية التعديل:", reply_markup=InlineKeyboardMarkup(kb))
    return ADMIN_BALANCE_AMT

async def adm_balance_op_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['bal_op'] = query.data
    await query.edit_message_text("💵 أدخل المبلغ المراد إضافته أو خصمه:")
    return ADMIN_BALANCE_AMT

async def adm_balance_amt_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target_id = context.user_data.get('target_balance_id')
    op = context.user_data.get('bal_op', 'bal_op_add')
    try:
        amount = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ أدخل رقماً صحيحاً:")
        return ADMIN_BALANCE_AMT

    mult = 1 if op == "bal_op_add" else -1
    final_amt = amount * mult

    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (final_amt, target_id))
    conn.commit()
    conn.close()

    await update.message.reply_text(f"✅ تم تعديل رصيد المستخدم `{target_id}` بنجاح بمقدار {format_currency(final_amt)}.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 لوحة الإدارة", callback_data="admin_panel")]]), parse_mode="Markdown")
    return ConversationHandler.END

# الحظر والفك
async def adm_ban_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.edit_message_text("🚫 أدخل ايدي المستخدم المراد حظره:")
    return ADMIN_BAN_ID

async def adm_ban_id_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        uid = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ ايدي غير صحيح:")
        return ADMIN_BAN_ID

    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("UPDATE users SET banned = 1 WHERE user_id = ?", (uid,))
    conn.commit()
    conn.close()

    await update.message.reply_text(f"✅ تم حظر المستخدم `{uid}` بنجاح.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 لوحة الإدارة", callback_data="admin_panel")]]), parse_mode="Markdown")
    return ConversationHandler.END

# ----------------- السجلات واللاعبين والإذاعة -----------------
async def adm_logs_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("SELECT id, type, amount, status, created_at FROM requests ORDER BY id DESC LIMIT 10")
    reqs = c.fetchall()
    conn.close()

    text = "📊 **آخر 10 طلبات في النظام:**\n\n"
    for r in reqs:
        text += f"🆔 #{r[0]} | نوع: {r[1]} | مبلغ: {r[2]} | الحالة: {r[3]} | ⏳ {r[4]}\n-------------------\n"

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 لوحة الإدارة", callback_data="admin_panel")]])
    await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

async def adm_users_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    c.execute("SELECT user_id, full_name, balance, wayxbet_account FROM users ORDER BY created_at DESC LIMIT 5")
    users = c.fetchall()
    conn.close()

    text = f"👥 **إجمالي مستخدمي البوت:** {total_users}\n\n**آخر 5 لاعبين مسجلين:**\n"
    for u in users:
        text += f"👤 {u[1]} (`{u[0]}`)\n💰 رصيد: {u[2]} | حساب: `{u[3]}`\n-------------------\n"

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 لوحة الإدارة", callback_data="admin_panel")]])
    await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

async def adm_broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.edit_message_text("📢 أرسل الرسالة الجماعية (نص أو صورة) ليتم إرسالها لكافة المستخدمين:")
    return ADMIN_BROADCAST

async def adm_broadcast_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or update.message.caption or ""
    photo = update.message.photo[-1].file_id if update.message.photo else None

    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE banned = 0")
    users = c.fetchall()
    conn.close()

    count = 0
    for u in users:
        try:
            if photo:
                await context.bot.send_photo(chat_id=u[0], photo=photo, caption=text)
            else:
                await context.bot.send_message(chat_id=u[0], text=text)
            count += 1
        except:
            pass

    await update.message.reply_text(f"✅ تم إرسال الإذاعة بنجاح إلى {count} مستخدم.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 لوحة الإدارة", callback_data="admin_panel")]]))
    return ConversationHandler.END

async def adm_private_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.edit_message_text("✉️ أدخل ايدي المستخدم المراد مراسلته:")
    return ADMIN_PRIVATE_ID

async def adm_private_id_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        uid = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ ايدي غير صحيح:")
        return ADMIN_PRIVATE_ID

    context.user_data['priv_user_id'] = uid
    await update.message.reply_text("✍️ الآن أرسل الرسالة التي تريد إرسالها لهذا المستخدم:")
    return ADMIN_PRIVATE_MSG

async def adm_private_msg_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = context.user_data.get('priv_user_id')
    text = update.message.text or ""
    try:
        await context.bot.send_message(chat_id=uid, text=f"📥 **رسالة من الإدارة:**\n\n{text}", parse_mode="Markdown")
        await update.message.reply_text("✅ تم إرسال الرسالة الخاصة بنجاح.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 لوحة الإدارة", callback_data="admin_panel")]]))
    except Exception as e:
        await update.message.reply_text(f"❌ فشل الإرسال: {e}")
    return ConversationHandler.END


# ----------------- 2. نظام الموافقات والرفض للطلبات وتذاكر الدعم -----------------
async def admin_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    if not is_admin(user.id):
        await query.answer("❌ غير مسموح لك!", show_alert=True)
        return

    data = query.data
    # مثال: adm_app_acc_1_12345_Roz133@ أو adm_rej_acc_1_12345
    parts = data.split("_")
    action = parts[1] # app أو rej
    req_type = parts[2] # acc, wit, dep, sitedep, sitewit
    req_id = parts[3]
    target_user_id = int(parts[4])

    conn = sqlite3.connect("wayxbet_vip_pro.db")
    c = conn.cursor()
    c.execute("UPDATE requests SET status = ? WHERE id = ?", ("approved" if action=="app" else "rejected", req_id))

    if req_type == "acc" and action == "app":
        acc_name = parts[5]
        c.execute("UPDATE users SET wayxbet_account = ? WHERE user_id = ?", (acc_name, target_user_id))
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text=f"✅ تمت الموافقة على طلب إنشاء حسابك!\n🏷 اسم حسابك: `{acc_name}` (يمكنك نسخه)\nيمكنك الشحن واللعب الآن.",
                parse_mode="Markdown"
            )
        except:
            pass

    elif req_type == "dep" and action == "app":
        amount = float(parts[5])
        c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, target_user_id))
        try:
            await context.bot.send_message(chat_id=target_user_id, text=f"✅ تمت الموافقة على طلب شحن رصيدك بقيمة {format_currency(amount)}.")
        except:
            pass

    elif req_type == "wit" and action == "app":
        amount = float(parts[5])
        try:
            await context.bot.send_message(chat_id=target_user_id, text=f"✅ تمت الموافقة على طلب سحب رصيدك بقيمة {format_currency(amount)}.")
        except:
            pass

    elif action == "rej":
        try:
            await context.bot.send_message(chat_id=target_user_id, text="❌ عذراً، تم رفض طلبك من قبل الإدارة.")
        except:
            pass

    conn.commit()
    conn.close()

    await query.edit_message_text(f"{query.message.text}\n\n✅ **تمت العملية بواسطة الأدمن:** {user.full_name}")

async def admin_reply_ticket_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    parts = query.data.split("_")
    context.user_data['ticket_id'] = parts[2]
    context.user_data['ticket_user_id'] = int(parts[3])
    await query.message.reply_text("✍️ أرسل الرد الموجه للمستخدم:")
    return ADMIN_REPLY

async def admin_reply_ticket_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = context.user_data.get('ticket_user_id')
    reply_text = update.message.text.strip()
    try:
        await context.bot.send_message(chat_id=uid, text=f"🎧 **رد الدعم الفني:**\n\n{reply_text}", parse_mode="Markdown")
        await update.message.reply_text("✅ تم إرسال الرد للمستخدم بنجاح.")
    except Exception as e:
        await update.message.reply_text(f"❌ فشل إرسال الرد: {e}")
    return ConversationHandler.END


# ----------------- 3. التشغيل الرئيسي (Main) -----------------
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # محادثة المحادثات الشاملة (ConversationHandler)
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CallbackQueryHandler(verify_subscription_callback, pattern="^verify_subscription$"),
            CallbackQueryHandler(wayxbet_menu_callback, pattern="^wayx_acc_menu$"),
            CallbackQueryHandler(withdraw_menu_callback, pattern="^withdraw_menu$"),
            CallbackQueryHandler(withdraw_method_chosen, pattern="^wit_meth_"),
            CallbackQueryHandler(deposit_menu_callback, pattern="^deposit_menu$"),
            CallbackQueryHandler(deposit_method_chosen, pattern="^dep_meth_"),
            CallbackQueryHandler(site_dep_menu_callback, pattern="^site_dep_menu$"),
            CallbackQueryHandler(site_wit_menu_callback, pattern="^site_wit_menu$"),
            CallbackQueryHandler(refs_menu_callback, pattern="^refs_menu$"),
            CallbackQueryHandler(gift_menu_callback, pattern="^gift_menu$"),
            CallbackQueryHandler(support_menu_callback, pattern="^support_menu$"),
            CallbackQueryHandler(comps_menu_callback, pattern="^comps_menu$"),
            CallbackQueryHandler(back_home_callback, pattern="^back_home$"),
            CallbackQueryHandler(admin_panel_callback, pattern="^admin_panel$"),
            CallbackQueryHandler(adm_settings_menu, pattern="^adm_settings_menu$"),
            CallbackQueryHandler(adm_setting_click, pattern="^adm_set_"),
            CallbackQueryHandler(adm_wallets_menu, pattern="^adm_wallets_menu$"),
            CallbackQueryHandler(adm_create_gift_start, pattern="^adm_create_gift$"),
            CallbackQueryHandler(adm_add_admin_start, pattern="^adm_add_admin_start$"),
            CallbackQueryHandler(adm_logs_menu, pattern="^adm_logs_menu$"),
            CallbackQueryHandler(adm_users_menu, pattern="^adm_users_menu$"),
            CallbackQueryHandler(adm_balance_menu, pattern="^adm_balance_menu$"),
            CallbackQueryHandler(adm_ban_menu, pattern="^adm_ban_menu$"),
            CallbackQueryHandler(adm_broadcast_start, pattern="^adm_broadcast_start$"),
            CallbackQueryHandler(adm_private_start, pattern="^adm_private_start$"),
            CallbackQueryHandler(admin_action_callback, pattern="^adm_"),
            CallbackQueryHandler(admin_reply_ticket_start, pattern="^adm_reply_"),
        ],
        states={
            GET_CONTACT: [MessageHandler(filters.CONTACT, contact_handler)],
            ACC_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_acc_name)],
            ACC_PASS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_acc_pass)],
            WITHDRAW_ACC: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_acc_received)],
            WITHDRAW_AMT: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_amt_received)],
            WITHDRAW_SPEED: [CallbackQueryHandler(withdraw_speed_chosen, pattern="^wit_speed_")],
            DEPOSIT_TX: [MessageHandler(filters.TEXT & ~filters.COMMAND, deposit_tx_received)],
            DEPOSIT_AMT: [MessageHandler(filters.TEXT & ~filters.COMMAND, deposit_amt_received)],
            SITE_DEP_AMT: [MessageHandler(filters.TEXT & ~filters.COMMAND, site_dep_amt_received)],
            SITE_WITH_AMT: [MessageHandler(filters.TEXT & ~filters.COMMAND, site_wit_amt_received)],
            GIFT_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, gift_input_received)],
            SUPPORT_INPUT: [MessageHandler(filters.ALL & ~filters.COMMAND, support_msg_received)],
            ADMIN_REPLY: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_reply_ticket_received)],
            ADMIN_BROADCAST: [MessageHandler(filters.ALL & ~filters.COMMAND, adm_broadcast_received)],
            ADMIN_PRIVATE_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_private_id_received)],
            ADMIN_PRIVATE_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_private_msg_received)],
            ADMIN_GIFT_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_gift_code_received)],
            ADMIN_GIFT_AMT: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_gift_amt_received)],
            ADMIN_ADD_ADMIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_add_admin_received)],
            ADMIN_BALANCE_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_balance_id_received)],
            ADMIN_BALANCE_AMT: [
                CallbackQueryHandler(adm_balance_op_chosen, pattern="^bal_op_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, adm_balance_amt_received)
            ],
            ADMIN_BAN_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_ban_id_received)],
            ADMIN_SETTING_VAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_setting_val_received)],
        },
        fallbacks=[CommandHandler("start", start)]
    )

    app.add_handler(conv_handler)
    
    # معالجات احتياطية سريعة للأزرار الثابتة خارج المحادثة
    app.add_handler(CallbackQueryHandler(withdraw_confirm_final, pattern="^wit_confirm_final$"))
    app.add_handler(CallbackQueryHandler(admin_action_callback, pattern="^adm_"))

    logger.info("🚀 بوت ROZ WAYXBET يعمل بكامل طاقته واحترافيته...")
    app.run_polling()

if __name__ == "__main__":
    main()

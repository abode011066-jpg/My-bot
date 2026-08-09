import logging
import sqlite3
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
    ConversationHandler,
)

# ----------------- خادم الويب الوهمي لـ Render -----------------
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write("Roz Wayxbet Bot is active and running!".encode("utf-8"))

def run_dummy_server():
    server_address = ("", 8080)
    httpd = HTTPServer(server_address, DummyHandler)
    httpd.serve_forever()

threading.Thread(target=run_dummy_server, daemon=True).start()
# -------------------------------------------------------------

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = "8812713556:AAGv3bCjQnGgwSGxiqoX8ipuVTvlNTTiLdk"  # ضع توكن البوت هنا
ADMIN_ID = 7255100997
CHANNEL_PROGRAMMER = "@lerafree"
CHANNEL_BOT = "@cashinsher"

# حالات المحادثة
(
    GET_CAPTCHA,
    GET_CONTACT,
    CREATE_ACCOUNT_NAME,
    CREATE_ACCOUNT_PASS,
    DEPOSIT_SYRIATEL_AMOUNT,
    DEPOSIT_SYRIATEL_TX,
    DEPOSIT_SHAM_AMOUNT,
    DEPOSIT_SHAM_TX,
    WITHDRAW_AMOUNT,
    WITHDRAW_ACC,
    GIFT_CODE_INPUT,
    SUPPORT_MESSAGE,
    ADMIN_BROADCAST,
    ADMIN_SEND_PRIVATE,
    ADMIN_ADD_GIFT,
    ADMIN_SET_BONUS,
    ADMIN_SET_REF_BONUS,
    ADMIN_SET_ACCOUNTS,
    ADMIN_WHEEL_ODDS,
    ADMIN_REJECT_REASON,
    ADMIN_REPLY_SUPPORT
) = range(21)

def init_db():
    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            phone TEXT,
            username TEXT,
            balance REAL DEFAULT 0,
            spins INTEGER DEFAULT 0,
            referred_by INTEGER,
            active_refs INTEGER DEFAULT 0,
            created_account TEXT
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
            amount REAL
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
            reject_reason TEXT
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            admin_id INTEGER PRIMARY KEY
        )
    """)
    
    defaults = {
        "syriatel_num": "0998682581",
        "sham_num": "d96338dabdb4da50e049526fa93b3353",
        "deposit_bonus": "10",
        "ref_bonus_percent": "5",
        "fast_withdraw_fee": "5",
        "slow_withdraw_fee": "0",
        "maintenance": "0",
        "offers_text": "لا توجد عروض حالياً.",
        "competitions_text": "لا توجد مسابقات حالياً.",
        "wheel_odds": "default"
    }
    
    for k, v in defaults.items():
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
        
    cursor.execute("INSERT OR IGNORE INTO admins (admin_id) VALUES (?)", (ADMIN_ID,))
    conn.commit()
    conn.close()

init_db()

def get_setting(key):
    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    res = cursor.fetchone()
    conn.close()
    return res[0] if res else ""

def set_setting(key, value):
    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def is_admin(user_id):
    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT admin_id FROM admins WHERE admin_id = ?", (user_id,))
    res = cursor.fetchone()
    conn.close()
    return res is not None

async def check_subscription(user_id, context: ContextTypes.DEFAULT_TYPE):
    try:
        m1 = await context.bot.get_chat_member(chat_id=CHANNEL_PROGRAMMER, user_id=user_id)
        m2 = await context.bot.get_chat_member(chat_id=CHANNEL_BOT, user_id=user_id)
        if m1.status in ['left', 'kicked'] or m2.status in ['left', 'kicked']:
            return False
        return True
    except Exception:
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user.id,))
    user_data = cursor.fetchone()
    
    if get_setting("maintenance") == "1" and not is_admin(user.id):
        await update.message.reply_text("🛠 البوت متوقف حالياً للصيانة. يرجى العودة لاحقاً.")
        conn.close()
        return ConversationHandler.END

    if not user_data:
        args = context.args
        if args and args[0].isdigit():
            ref_id = int(args[0])
            if ref_id != user.id:
                cursor.execute("INSERT OR IGNORE INTO users (user_id, referred_by) VALUES (?, ?)", (user.id, ref_id))
                # إشعار لمن أحال شخصاً
                try:
                    await context.bot.send_message(chat_id=ref_id, text=f"🔔 قام المستخدم {user.full_name} بالدخول عبر رابط إحالتك!")
                except:
                    pass
        
        cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user.id,))
        conn.commit()
        conn.close()
        
        await update.message.reply_text("🛡 للتاكد أنك لست روبوت، كم الناتج:\n5 + 3 = ?")
        return GET_CAPTCHA
    
    conn.close()
    return await show_main_menu(update, context)

async def receive_captcha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.strip() == "8":
        await update.message.reply_text(
            "رائع! يرجى مشاركة رقم هاتفك للتاكيد عبر الزر أدناه:",
            reply_markup=InlineKeyboardMarkup([[{"text": "📱 مشاركة رقم الهاتف", "request_contact": True}]])
        )
        return GET_CONTACT
    else:
        await update.message.reply_text("❌ إجابة خاطئة. كم الناتج:\n5 + 3 = ?")
        return GET_CAPTCHA

async def receive_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.message.contact:
        conn = sqlite3.connect("wayxbet.db")
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET phone = ? WHERE user_id = ?", (update.message.contact.phone_number, user.id))
        conn.commit()
        conn.close()
        
    if not await check_subscription(user.id, context):
        keyboard = [
            [InlineKeyboardButton("قناة المبرمج", url=f"https://t.me/{CHANNEL_PROGRAMMER[1:]}")],
            [InlineKeyboardButton("قناة البوت", url=f"https://t.me/{CHANNEL_BOT[1:]}")],
            [InlineKeyboardButton("✅ تحقق من الاشتراك", callback_data="check_sub")]
        ]
        await update.message.reply_text(
            f"⚠️ يجب عليك الاشتراك في قنوات البوت أولاً:\n1. {CHANNEL_PROGRAMMER}\n2. {CHANNEL_BOT}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return ConversationHandler.END
    
    return await show_main_menu(update, context)

async def check_sub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if await check_subscription(query.from_user.id, context):
        await query.message.delete()
        await show_main_menu_callback(query, context)
    else:
        await query.answer("❌ لم تقم بالاشتراك في كافة القنوات بعد!", show_alert=True)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT created_account FROM users WHERE user_id = ?", (user.id,))
    res = cursor.fetchone()
    conn.close()
    
    acc_text = res[0] if res and res[0] else "طلب إنشاء حساب"
    
    keyboard = [
        [InlineKeyboardButton(f"Wayxbet: {acc_text}", callback_data="wayxbet_menu")],
        [InlineKeyboardButton("💰 شحن رصيد", callback_data="deposit"), InlineKeyboardButton("💸 سحب رصيد", callback_data="withdraw")],
        [InlineKeyboardButton("🔗 رابط إحالاتي", callback_data="referrals"), InlineKeyboardButton("🎁 كود هدية", callback_data="gift_code")],
        [InlineKeyboardButton("🎡 عجلة الحظ", web_app=WebAppInfo(url="https://example.com/wheel"))], # ضع رابط صفحة الويب الخاص بالعجلة هنا
        [InlineKeyboardButton("📢 العروض الحالية", callback_data="offers"), InlineKeyboardButton("🏆 المسابقات", callback_data="competitions")],
        [InlineKeyboardButton("📞 مراسلة الدعم", callback_data="support")]
    ]
    if is_admin(user.id):
        keyboard.append([InlineKeyboardButton("⚙️ لوحة الإدارة", callback_data="admin_panel")])
        
    text = f"🔴 **Roz Wayxbet**\n\nأهلاً بك عزيزي المستخدم.\nقناة المبرمج: {CHANNEL_PROGRAMMER}"
    if update.message:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return ConversationHandler.END

async def show_main_menu_callback(query, context):
    user = query.from_user
    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT created_account FROM users WHERE user_id = ?", (user.id,))
    res = cursor.fetchone()
    conn.close()
    
    acc_text = res[0] if res and res[0] else "طلب إنشاء حساب"
    keyboard = [
        [InlineKeyboardButton(f"Wayxbet: {acc_text}", callback_data="wayxbet_menu")],
        [InlineKeyboardButton("💰 شحن رصيد", callback_data="deposit"), InlineKeyboardButton("💸 سحب رصيد", callback_data="withdraw")],
        [InlineKeyboardButton("🔗 رابط إحالاتي", callback_data="referrals"), InlineKeyboardButton("🎁 كود هدية", callback_data="gift_code")],
        [InlineKeyboardButton("🎡 عجلة الحظ", web_app=WebAppInfo(url="https://example.com/wheel"))],
        [InlineKeyboardButton("📢 العروض الحالية", callback_data="offers"), InlineKeyboardButton("🏆 المسابقات", callback_data="competitions")],
        [InlineKeyboardButton("📞 مراسلة الدعم", callback_data="support")]
    ]
    if is_admin(user.id):
        keyboard.append([InlineKeyboardButton("⚙️ لوحة الإدارة", callback_data="admin_panel")])
    text = f"🔴 **Roz Wayxbet**\n\nأهلاً بك عزيزي المستخدم.\nقناة المبرمج: {CHANNEL_PROGRAMMER}"
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def wayxbet_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()
    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT created_account FROM users WHERE user_id = ?", (user.id,))
    res = cursor.fetchone()
    conn.close()
    
    if res and res[0]:
        await query.message.edit_text(
            f"👤 حسابك المنشأ:\n`{res[0]}`\n(يمكنك نسخه)",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]]),
            parse_mode="Markdown"
        )
    else:
        await query.message.edit_text(
            "📝 أخل اسم مستخدم يدوي بحيث ينتهي بـ `@123`\nمثال: `rozah@123`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]]),
            parse_mode="Markdown"
        )
        return CREATE_ACCOUNT_NAME

async def receive_account_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.endswith("@123"):
        await update.message.reply_text("❌ اسم غير صالح. يجب أن ينتهي بـ `@123`. حاول مجدداً:")
        return CREATE_ACCOUNT_NAME
    context.user_data['temp_acc_name'] = text
    await update.message.reply_text("🔑 الآن أدخل كلمة المرور الخاصة بالحساب:")
    return CREATE_ACCOUNT_PASS

async def receive_account_pass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text.strip()
    user = update.effective_user
    acc_name = context.user_data.get('temp_acc_name')
    
    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT phone FROM users WHERE user_id = ?", (user.id,))
    phone = cursor.fetchone()[0]
    conn.close()
    
    admin_kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ موافقة وتفعيل", callback_data=f"approve_acc_{user.id}_{acc_name}"),
            InlineKeyboardButton("❌ إلغاء", callback_data=f"reject_acc_{user.id}")
        ]
    ])
    
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📥 **طلب إنشاء حساب جديد:**\n👤 المستخدم: {user.full_name}\n🆔 الآيدي: `{user.id}`\n📱 الهاتف: `{phone}`\n🏷 الاسم: `{acc_name}`\n🔑 الباسورد: `{password}`",
        reply_markup=admin_kb,
        parse_mode="Markdown"
    )
    await update.message.reply_text("⏳ تم إرسال طلب إنشاء الحساب بنجاح، انتظر المراجعة.")
    return await show_main_menu(update, context)

async def deposit_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bonus = get_setting("deposit_bonus")
    bonus_text = f"\n🎁 يوجد بونص بنسبة {bonus}% على عمليات الشحن!" if bonus and int(bonus) > 0 else ""
    keyboard = [
        [InlineKeyboardButton(" سيريتل كاش", callback_data="dep_syriatel"), InlineKeyboardButton(" شام كاش", callback_data="dep_sham")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]
    ]
    await query.message.edit_text(f"💰 اختر طريقة الشحن:{bonus_text}", reply_markup=InlineKeyboardMarkup(keyboard))

async def dep_syriatel_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['dep_method'] = "سيريتل كاش"
    await query.message.edit_text(" أرسل المبلغ الذي تريد شحنه:")
    return DEPOSIT_SYRIATEL_AMOUNT

async def dep_syriatel_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['dep_amount'] = update.message.text.strip()
    num = get_setting("syriatel_num")
    await update.message.reply_text(f"📱 أرسل المبلغ إلى حساب سيريتل كاش:\n`{num}`\n\nثم أرسل **رقم العملية**:")
    return DEPOSIT_SYRIATEL_TX

async def dep_syriatel_tx(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tx_id = update.message.text.strip()
    user = update.effective_user
    amount = context.user_data.get('dep_amount')
    method = context.user_data.get('dep_method')
    
    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT phone, created_account FROM users WHERE user_id = ?", (user.id,))
    res = cursor.fetchone()
    phone, acc_name = res[0], res[1] or "غير منشأ"
    
    cursor.execute("INSERT INTO transactions (user_id, type, method, amount, tx_id, status) VALUES (?, 'deposit', ?, ?, ?, 'pending')",
                   (user.id, method, float(amount), tx_id))
    tx_db_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    admin_kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ موافقة", callback_data=f"app_dep_{tx_db_id}"),
            InlineKeyboardButton("❌ رفض", callback_data=f"rej_dep_{tx_db_id}")
        ]
    ])
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📥 **طلب شحن جديد:**\n🏷 الحساب: `{acc_name}`\n🆔 الآيدي: `{user.id}`\n📱 الهاتف: `{phone}`\n💳 الطريقة: {method}\n💵 المبلغ: {amount}\n🔢 رقم العملية: `{tx_id}`",
        reply_markup=admin_kb,
        parse_mode="Markdown"
    )
    await update.message.reply_text("✅ تم تقديم طلب الشحن يرجى الانتظار.")
    return await show_main_menu(update, context)

async def dep_sham_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['dep_method'] = "شام كاش"
    await query.message.edit_text(" أرسل المبلغ الذي تريد شحنه:")
    return DEPOSIT_SHAM_AMOUNT

async def dep_sham_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['dep_amount'] = update.message.text.strip()
    num = get_setting("sham_num")
    await update.message.reply_text(f" اشحن على حساب شام كاش التالي:\n`{num}`\n\nثم أرسل **رقم العملية**:")
    return DEPOSIT_SHAM_TX

async def dep_sham_tx(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tx_id = update.message.text.strip()
    user = update.effective_user
    amount = context.user_data.get('dep_amount')
    method = context.user_data.get('dep_method')
    
    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT phone, created_account FROM users WHERE user_id = ?", (user.id,))
    res = cursor.fetchone()
    phone, acc_name = res[0], res[1] or "غير منشأ"
    
    cursor.execute("INSERT INTO transactions (user_id, type, method, amount, tx_id, status) VALUES (?, 'deposit', ?, ?, ?, 'pending')",
                   (user.id, method, float(amount), tx_id))
    tx_db_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    admin_kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ موافقة", callback_data=f"app_dep_{tx_db_id}"),
            InlineKeyboardButton("❌ رفض", callback_data=f"rej_dep_{tx_db_id}")
        ]
    ])
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📥 **طلب شحن جديد:**\n🏷 الحساب: `{acc_name}`\n🆔 الآيدي: `{user.id}`\n📱 الهاتف: `{phone}`\n💳 الطريقة: {method}\n💵 المبلغ: {amount}\n🔢 رقم العملية: `{tx_id}`",
        reply_markup=admin_kb,
        parse_mode="Markdown"
    )
    await update.message.reply_text("✅ تم تقديم الطلب يرجى الانتظار.")
    return await show_main_menu(update, context)

async def withdraw_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    fast_fee = get_setting("fast_withdraw_fee")
    slow_fee = get_setting("slow_withdraw_fee")
    keyboard = [
        [InlineKeyboardButton(f"⚡ طلب سريع (عمولة {fast_fee}%)", callback_data="wd_speed_fast")],
        [InlineKeyboardButton(f"🐢 طلب بطيء (عمولة {slow_fee}%)", callback_data="wd_speed_slow")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]
    ]
    await query.message.edit_text("💸 اختر سرعة السحب:", reply_markup=InlineKeyboardMarkup(keyboard))

async def withdraw_speed_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['wd_speed'] = "سريع" if "fast" in query.data else "بطيء"
    keyboard = [
        [InlineKeyboardButton(" سيريتل كاش", callback_data="wd_meth_syriatel"), InlineKeyboardButton(" شام كاش", callback_data="wd_meth_sham")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]
    ]
    await query.message.edit_text("💳 اختر طريقة السحب:", reply_markup=InlineKeyboardMarkup(keyboard))

async def withdraw_method_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['wd_method'] = "سيريتل كاش" if "syriatel" in query.data else "شام كاش"
    await query.message.edit_text("💵 أرسل المبلغ المراد سحبه:")
    return WITHDRAW_AMOUNT

async def withdraw_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['wd_amount'] = update.message.text.strip()
    await update.message.reply_text("🔢 أرسل رقم الحساب أو الهاتف المراد السحب إليه:")
    return WITHDRAW_ACC

async def withdraw_acc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    acc_num = update.message.text.strip()
    user = update.effective_user
    speed = context.user_data.get('wd_speed')
    method = context.user_data.get('wd_method')
    amount = context.user_data.get('wd_amount')
    
    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT phone, created_account, balance FROM users WHERE user_id = ?", (user.id,))
    res = cursor.fetchone()
    phone, acc_name, balance = res[0], res[1] or "غير منشأ", res[2]
    
    try:
        req_amount = float(amount)
    except:
        req_amount = 0
        
    if balance < req_amount:
        conn.close()
        await update.message.reply_text("❌ رصيدك غير كافي لإتمام عملية السحب.")
        return await show_main_menu(update, context)
        
    cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (req_amount, user.id))
    cursor.execute("INSERT INTO transactions (user_id, type, method, amount, account_num, status) VALUES (?, 'withdraw', ?, ?, ?, 'pending')",
                   (user.id, f"{method} ({speed})", req_amount, acc_num))
    tx_db_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    admin_kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ موافقة", callback_data=f"app_wd_{tx_db_id}"),
            InlineKeyboardButton("❌ رفض", callback_data=f"rej_wd_{tx_db_id}")
        ]
    ])
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📤 **طلب سحب جديد:**\n🏷 الحساب: `{acc_name}`\n🆔 الآيدي: `{user.id}`\n📱 الهاتف: `{phone}`\n⚡ السرعة: {speed}\n💳 الطريقة: {method}\n💵 المبلغ: {req_amount}\n🔢 رقم الحساب: `{acc_num}`",
        reply_markup=admin_kb,
        parse_mode="Markdown"
    )
    await update.message.reply_text("✅ تم تقديم طلب السحب بنجاح، انتظر المراجعة.")
    return await show_main_menu(update, context)

async def referrals_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT active_refs FROM users WHERE user_id = ?", (user.id,))
    res = cursor.fetchone()
    conn.close()
    active_refs = res[0] if res else 0
    ref_bonus = get_setting("ref_bonus_percent")
    
    bot_info = await context.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user.id}"
    
    text = f"🔗 **نظام الإحالات:**\n\nقم بمشاركة رابطك مع أصدقائك واكسب نسبة {ref_bonus}% عند شحنهم!\n\n👥 عدد إحالاتك النشطة: {active_refs}\n\n🔗 رابطك الخاص:\n`{ref_link}`"
    keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]]
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def gift_code_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text(
        "🎁 أرسل كود الهدية لشحنه في حسابك:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]])
    )
    return GIFT_CODE_INPUT

async def gift_code_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()
    user = update.effective_user
    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT amount FROM gift_codes WHERE code = ?", (code,))
    res = cursor.fetchone()
    if not res:
        conn.close()
        await update.message.reply_text("❌ الكود غير صالح أو تم استخدامه مسبقاً.")
        return await show_main_menu(update, context)
    
    amount = res[0]
    cursor.execute("DELETE FROM gift_codes WHERE code = ?", (code,))
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user.id))
    conn.commit()
    conn.close()
    
    await update.message.reply_text(f"🎉 مبروك! تم إضافة {amount} إلى رصيدك بنجاح.")
    return await show_main_menu(update, context)

async def offers_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = get_setting("offers_text")
    await query.message.edit_text(
        f"📢 **العروض الحالية:**\n\n{text}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]])
    )

async def competitions_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = get_setting("competitions_text")
    await query.message.edit_text(
        f"🏆 **المسابقات:**\n\n{text}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]])
    )

async def support_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text(
        "📞 أرسل رسالتك أو مشكلتك وسيتم تحويلها إلى الدعم الفني:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]])
    )
    return SUPPORT_MESSAGE

async def support_message_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text
    user = update.effective_user
    admin_kb = InlineKeyboardMarkup([[InlineKeyboardButton(" رد على المستخدم", callback_data=f"support_reply_{user.id}")]])
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📞 **رسالة دعم جديدة من:** {user.full_name} (`{user.id}`)\n\n{msg}",
        reply_markup=admin_kb
    )
    await update.message.reply_text("✅ تم إرسال رسالتك إلى الدعم الفني بنجاح.")
    return await show_main_menu(update, context)

async def back_home_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await show_main_menu_callback(query, context)
    return ConversationHandler.END

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()
    if not is_admin(user.id):
        return
    keyboard = [
        [InlineKeyboardButton("📢 إذاعة عامة", callback_data="adm_broadcast"), InlineKeyboardButton("✉️ رسالة لشخص", callback_data="adm_send_priv")],
        [InlineKeyboardButton("🎁 إضافة كود هدية", callback_data="adm_add_gift"), InlineKeyboardButton("⚙️ تعديل الأرقام", callback_data="adm_set_nums")],
        [InlineKeyboardButton("💯 تعديل البونص", callback_data="adm_set_bonus"), InlineKeyboardButton("🛠 الصيانة", callback_data="adm_maint")],
        [InlineKeyboardButton("🔙 رجوع للقائمة", callback_data="back_home")]
    ]
    await query.message.edit_text("⚙️ **لوحة التحكم الخاصة بالأدمن:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def admin_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    if not is_admin(user.id):
        await query.answer("لست مسجلاً كأدمن!", show_alert=True)
        return
    data = query.data
    await query.answer()
    
    if data.startswith("approve_acc_"):
        parts = data.split("_")
        target_id = parts[2]
        acc_name = "_".join(parts[3:])
        conn = sqlite3.connect("wayxbet.db")
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET created_account = ? WHERE user_id = ?", (acc_name, target_id))
        conn.commit()
        conn.close()
        
        # تحقق من الإحالة وإعطاء البونص إن وجد
        conn = sqlite3.connect("wayxbet.db")
        cursor = conn.cursor()
        cursor.execute("SELECT referred_by FROM users WHERE user_id = ?", (target_id,))
        ref_res = cursor.fetchone()
        conn.close()
        if ref_res and ref_res[0]:
            ref_id = ref_res[0]
            conn = sqlite3.connect("wayxbet.db")
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET active_refs = active_refs + 1 WHERE user_id = ?", (ref_id,))
            conn.commit()
            conn.close()
            try:
                await context.bot.send_message(chat_id=ref_id, text="🎉 مبروك! أحد الأشخاص الذين دعيتهم أكمل إنشاء حسابه وتم احتساب إحالتك.")
            except:
                pass

        await query.message.edit_text(query.message.text + "\n\n✅ تم الموافقة وتفعيل الحساب.")
        try:
            await context.bot.send_message(chat_id=target_id, text=f"🎉 تم تفعيل حسابك بنجاح!\nاسم الحساب: `{acc_name}`", parse_mode="Markdown")
        except:
            pass

    elif data.startswith("reject_acc_"):
        target_id = data.split("_")[2]
        await query.message.edit_text(query.message.text + "\n\n❌ تم إلغاء الطلب.")
        try:
            await context.bot.send_message(chat_id=target_id, text="❌ معذرة، تم رفض طلب إنشاء الحساب الخاص بك. تأكد من البيانات وحاول مجدداً.")
        except:
            pass

    elif data.startswith("app_dep_"):
        tx_id = data.split("_")[2]
        conn = sqlite3.connect("wayxbet.db")
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, amount FROM transactions WHERE id = ?", (tx_id,))
        tx = cursor.fetchone()
        if tx:
            u_id, amt = tx[0], tx[1]
            bonus = float(get_setting("deposit_bonus") or 0)
            final_amt = amt + (amt * bonus / 100)
            cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (final_amt, u_id))
            cursor.execute("UPDATE transactions SET status = 'approved' WHERE id = ?", (tx_id,))
            conn.commit()
            conn.close()
            await query.message.edit_text(query.message.text + "\n\n✅ تم الموافقة على الشحن وإضافة الرصيد للمستخدم.")
            try:
                await context.bot.send_message(chat_id=u_id, text=f"✅ تم الموافقة على عملية الشحن وإضافة مبلغ {final_amt} إلى رصيدك!")
            except:
                pass
        else:
            conn.close()

    elif data.startswith("rej_dep_"):
        tx_id = data.split("_")[2]
        conn = sqlite3.connect("wayxbet.db")
        cursor = conn.cursor()
        cursor.execute("UPDATE transactions SET status = 'rejected' WHERE id = ?", (tx_id,))
        cursor.execute("SELECT user_id FROM transactions WHERE id = ?", (tx_id,))
        tx = cursor.fetchone()
        conn.commit()
        conn.close()
        await query.message.edit_text(query.message.text + "\n\n❌ تم رفض الشحن.")
        if tx:
            try:
                await context.bot.send_message(chat_id=tx[0], text="❌ تم رفض طلب الشحن الخاص بك من قبل الإدارة.")
            except:
                pass

    elif data.startswith("app_wd_"):
        tx_id = data.split("_")[2]
        conn = sqlite3.connect("wayxbet.db")
        cursor = conn.cursor()
        cursor.execute("UPDATE transactions SET status = 'approved' WHERE id = ?", (tx_id,))
        cursor.execute("SELECT user_id, amount FROM transactions WHERE id = ?", (tx_id,))
        tx = cursor.fetchone()
        conn.commit()
        conn.close()
        await query.message.edit_text(query.message.text + "\n\n✅ تم الموافقة على السحب.")
        if tx:
            try:
                await context.bot.send_message(chat_id=tx[0], text=f"✅ تم تنفيذ وإرسال مبلغ السحب ({tx[1]}) بنجاح!")
            except:
                pass

    elif data.startswith("rej_wd_"):
        tx_id = data.split("_")[2]
        conn = sqlite3.connect("wayxbet.db")
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, amount FROM transactions WHERE id = ?", (tx_id,))
        tx = cursor.fetchone()
        if tx:
            u_id, amt = tx[0], tx[1]
            cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amt, u_id))
            cursor.execute("UPDATE transactions SET status = 'rejected' WHERE id = ?", (tx_id,))
            conn.commit()
        conn.close()
        await query.message.edit_text(query.message.text + "\n\n❌ تم رفض السحب وإرجاع المبلغ للرصيد.")
        if tx:
            try:
                await context.bot.send_message(chat_id=tx[0], text="❌ تم رفض طلب السحب وإرجاع المبلغ إلى رصيدك.")
            except:
                pass

    elif data == "adm_maint":
        curr = get_setting("maintenance")
        new_val = "0" if curr == "1" else "1"
        set_setting("maintenance", new_val)
        await query.answer(f"تم تغيير وضع الصيانة إلى: {new_val}", show_alert=True)
        await admin_panel(update, context)

    elif data == "adm_add_gift":
        await query.message.edit_text("🎁 أرسل كود الهدية والقيمة بالشكل التالي:\n`الكود المبلغ`\nمثال: `GIFT100 50`", parse_mode="Markdown")
        return ADMIN_ADD_GIFT

    elif data == "adm_set_nums":
        await query.message.edit_text("📱 أرسل رقم سيريتل والشام بالشكل التالي:\n`syriatel:رقم`\nأو قم بتعديله من قاعدة البيانات مباشرة.", parse_mode="Markdown")

    elif data == "adm_broadcast":
        await query.message.edit_text("📢 أرسل الرسالة التي تريد إذاعتها لجميع المستخدمين:")
        return ADMIN_BROADCAST

    elif data == "adm_send_priv":
        await query.message.edit_text("✉️ أرسل الآيدي والرسالة بالشكل التالي:\n`USER_ID الرسالة`", parse_mode="Markdown")
        return ADMIN_SEND_PRIVATE

    elif data.startswith("support_reply_"):
        target_id = data.split("_")[2]
        context.user_data['support_target'] = target_id
        await query.message.reply_text("✉️ أرسل الرد للمستخدم:")
        return ADMIN_REPLY_SUPPORT

async def admin_add_gift_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parts = update.message.text.strip().split()
    if len(parts) < 2:
        await update.message.reply_text("❌ صيغة خاطئة. حاول مجدداً بالشكل: `الكود المبلغ`")
        return ADMIN_ADD_GIFT
    code, amt = parts[0], float(parts[1])
    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO gift_codes (code, amount) VALUES (?, ?)", (code, amt))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅ تم إضافة كود الهدية `{code}` بقيمة `{amt}` بنجاح.", parse_mode="Markdown")
    return await show_main_menu(update, context)

async def admin_broadcast_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text
    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    conn.close()
    
    count = 0
    for u in users:
        try:
            await context.bot.send_message(chat_id=u[0], text=msg)
            count += 1
        except:
            pass
    await update.message.reply_text(f"📢 تمت الإذاعة بنجاح إلى {count} مستخدم.")
    return await show_main_menu(update, context)

async def admin_send_private_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    parts = text.split(" ", 1)
    if len(parts) < 2:
        await update.message.reply_text("❌ صيغة خاطئة. اتبع: `USER_ID الرسالة`")
        return ADMIN_SEND_PRIVATE
    target_id, msg = parts[0], parts[1]
    try:
        await context.bot.send_message(chat_id=int(target_id), text=f"📩 رسالة من الإدارة:\n\n{msg}")
        await update.message.reply_text("✅ تم إرسال الرسالة بنجاح.")
    except Exception as e:
        await update.message.reply_text(f"❌ فشل الإرسال: {e}")
    return await show_main_menu(update, context)

async def admin_reply_support_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text
    target_id = context.user_data.get('support_target')
    try:
        await context.bot.send_message(chat_id=int(target_id), text=f"📞 رد الدعم الفني:\n\n{msg}")
        await update.message.reply_text("✅ تم إرسال الرد للمستخدم بنجاح.")
    except Exception as e:
        await update.message.reply_text(f"❌ فشل إرسال الرد: {e}")
    return await show_main_menu(update, context)

def main():
    app = Application.builder().token(TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            GET_CAPTCHA: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_captcha)],
            GET_CONTACT: [MessageHandler(filters.CONTACT, receive_contact)],
            CREATE_ACCOUNT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_account_name)],
            CREATE_ACCOUNT_PASS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_account_pass)],
            DEPOSIT_SYRIATEL_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, dep_syriatel_amount)],
            DEPOSIT_SYRIATEL_TX: [MessageHandler(filters.TEXT & ~filters.COMMAND, dep_syriatel_tx)],
            DEPOSIT_SHAM_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, dep_sham_amount)],
            DEPOSIT_SHAM_TX: [MessageHandler(filters.TEXT & ~filters.COMMAND, dep_sham_tx)],
            WITHDRAW_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_amount)],
            WITHDRAW_ACC: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_acc)],
            GIFT_CODE_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, gift_code_receive)],
            SUPPORT_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, support_message_receive)],
            ADMIN_BROADCAST: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_broadcast_receive)],
            ADMIN_SEND_PRIVATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_send_private_receive)],
            ADMIN_ADD_GIFT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_gift_receive)],
            ADMIN_REPLY_SUPPORT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_reply_support_receive)],
        },
        fallbacks=[CommandHandler("start", start)]
    )
    
    app.add_handler(conv_handler)
    
    # المعالجات متوافقة تماماً مع الإصدار v20
    app.add_handler(CallbackQueryHandler(check_sub_callback, pattern="^check_sub$"))
    app.add_handler(CallbackQueryHandler(wayxbet_menu_handler, pattern="^wayxbet_menu$"))
    app.add_handler(CallbackQueryHandler(deposit_menu, pattern="^deposit$"))
    app.add_handler(CallbackQueryHandler(dep_syriatel_start, pattern="^dep_syriatel$"))
    app.add_handler(CallbackQueryHandler(dep_sham_start, pattern="^dep_sham$"))
    app.add_handler(CallbackQueryHandler(withdraw_menu, pattern="^withdraw$"))
    app.add_handler(CallbackQueryHandler(withdraw_speed_choice, pattern="^wd_speed_"))
    app.add_handler(CallbackQueryHandler(withdraw_method_choice, pattern="^wd_meth_"))
    app.add_handler(CallbackQueryHandler(referrals_menu, pattern="^referrals$"))
    app.add_handler(CallbackQueryHandler(gift_code_start, pattern="^gift_code$"))
    app.add_handler(CallbackQueryHandler(offers_menu, pattern="^offers$"))
    app.add_handler(CallbackQueryHandler(competitions_menu, pattern="^competitions$"))
    app.add_handler(CallbackQueryHandler(support_start, pattern="^support$"))
    app.add_handler(CallbackQueryHandler(back_home_callback, pattern="^back_home$"))
    app.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin_panel$"))
    app.add_handler(CallbackQueryHandler(admin_callbacks))
    
    logger.info("Bot is starting...")
    app.run_polling()

if __name__ == "__main__":
    main()

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

TOKEN = "YOUR_BOT_TOKEN_HERE"  # ضع توكن البوت هنا
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

async def withdraw_amount_recv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['wd_amount'] = update.message.text.strip()
    await update.message.reply_text("📱 أرسل رقم الحساب أو الكود الذي ستستلم عليه رصيدك:")
    return WITHDRAW_ACC

async def withdraw_acc_recv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    acc_num = update.message.text.strip()
    user = update.effective_user
    speed = context.user_data.get('wd_speed')
    method = context.user_data.get('wd_method')
    amount = context.user_data.get('wd_amount')
    
    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT phone, created_account FROM users WHERE user_id = ?", (user.id,))
    res = cursor.fetchone()
    phone, acc_name = res[0], res[1] or "غير منشأ"
    
    cursor.execute("INSERT INTO transactions (user_id, type, method, amount, account_num, status) VALUES (?, 'withdraw', ?, ?, ?, 'pending')",
                   (user.id, f"{method} ({speed})", float(amount), acc_num))
    tx_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    admin_kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ موافقة", callback_data=f"app_wd_{tx_id}"),
            InlineKeyboardButton("❌ رفض", callback_data=f"rej_wd_{tx_id}")
        ]
    ])
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📤 **طلب سحب جديد:**\n🏷 الحساب: `{acc_name}`\n🆔 الآيدي: `{user.id}`\n📱 الهاتف: `{phone}`\n⚡ السرعة: {speed}\n💳 الطريقة: {method}\n💵 المبلغ: {amount}\n🔢 حساب الاستلام: `{acc_num}`",
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
    cursor.execute("SELECT COUNT(*) FROM users WHERE referred_by = ?", (user.id,))
    total_refs = cursor.fetchone()[0]
    cursor.execute("SELECT active_refs FROM users WHERE user_id = ?", (user.id,))
    active_refs = cursor.fetchone()[0]
    conn.close()
    
    bot_user = (await context.bot.get_me()).username
    ref_link = f"https://t.me/{bot_user}?start={user.id}"
    ref_percent = get_setting("ref_bonus_percent")
    
    text = (
        f"🔗 **نظام الإحالة الاحترافي**\n\nرابطك:\n`{ref_link}`\n\n"
        f"👥 المدعوون: {total_refs}\n🔥 النشطون: {active_refs}\n"
        f"🎁 تحصل على لفة مجانية لكل صديق، ونسبة ربح {ref_percent}% عند 3 إحالات نشطة."
    )
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]]), parse_mode="Markdown")

async def gift_code_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("🎁 أرسل كود الهدية هنا:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]]))
    return GIFT_CODE_INPUT

async def receive_gift_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()
    user = update.effective_user
    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT amount FROM gift_codes WHERE code = ?", (code,))
    res = cursor.fetchone()
    if res:
        amount = res[0]
        cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user.id))
        cursor.execute("DELETE FROM gift_codes WHERE code = ?", (code,))
        conn.commit()
        
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🎁 **استخدام كود هدية:**\n👤 المستخدم: {user.full_name}\n🆔 الآيدي: `{user.id}`\n🏷 الكود: `{code}`\n💰 القيمة: {amount}"
        )
        await update.message.reply_text(f"🎉 مبروك! تمت إضافة {amount} لرصيدك.")
    else:
        await update.message.reply_text("❌ الكود غير صالح أو مستخدم.")
    conn.close()
    return await show_main_menu(update, context)

async def support_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("📞 أرسل رسالتك أو صورتك للدعم الفني:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]]))
    return SUPPORT_MESSAGE

async def receive_support_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    forward_kb = InlineKeyboardMarkup([[InlineKeyboardButton("💬 رد على المستخدم", callback_data=f"reply_sup_{user.id}")]])
    await context.bot.forward_message(chat_id=ADMIN_ID, from_chat_id=user.id, message_id=update.message.message_id)
    await context.bot.send_message(chat_id=ADMIN_ID, text=f"📞 رسالة دعم من: `{user.id}`", reply_markup=forward_kb, parse_mode="Markdown")
    await update.message.reply_text("✅ تم إرسال رسالتك للدعم بنجاح.")
    return await show_main_menu(update, context)

async def offers_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text(f"📢 **العروض الحالية:**\n\n{get_setting('offers_text')}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]]), parse_mode="Markdown")

async def competitions_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text(f"🏆 **المسابقات:**\n\n{get_setting('competitions_text')}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]]), parse_mode="Markdown")

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("غير مسموح!", show_alert=True)
        return
        
    keyboard = [
        [InlineKeyboardButton("➕ إنشاء كود هدية", callback_data="adm_add_gift"), InlineKeyboardButton("👥 عدد اللاعبين", callback_data="adm_count_users")],
        [InlineKeyboardButton("👤 تفاصيل لاعب", callback_data="adm_player_info"), InlineKeyboardButton("💰 أرصدة اللاعبين", callback_data="adm_players_bal")],
        [InlineKeyboardButton("💸 سجل طلبات السحب", callback_data="adm_wd_logs"), InlineKeyboardButton("📥 تلقي رسائل الدعم", callback_data="adm_support")],
        [InlineKeyboardButton("✉️ إرسال رسالة خاصة", callback_data="adm_send_priv"), InlineKeyboardButton("📢 إرسال رسالة جماعية", callback_data="adm_broadcast")],
        [InlineKeyboardButton("🎡 خوارزمية العجلة", callback_data="adm_wheel"), InlineKeyboardButton("🎁 تغيير بونص الشحن", callback_data="adm_dep_bonus")],
        [InlineKeyboardButton("🔗 تغيير بونص الإحالة", callback_data="adm_ref_bonus"), InlineKeyboardButton("💳 تغيير حسابات الشحن", callback_data="adm_accs")],
        [InlineKeyboardButton("💾 حسابات اللاعبين", callback_data="adm_saved_accs"), InlineKeyboardButton("📥 طلبات إنشاء حساب", callback_data="adm_acc_reqs")],
        [InlineKeyboardButton("📊 سجل إنشاء الحسابات", callback_data="adm_acc_logs"), InlineKeyboardButton("💰 طلبات الشحن", callback_data="adm_dep_reqs")],
        [InlineKeyboardButton("📈 سجل طلبات الشحن", callback_data="adm_dep_logs"), InlineKeyboardButton("➕ إضافة أدمن", callback_data="adm_add_admin")],
        [InlineKeyboardButton("🛠 وضع صيانة", callback_data="adm_maintenance_on"), InlineKeyboardButton("✅ تفعيل البوت", callback_data="adm_maintenance_off")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]
    ]
    await query.message.edit_text("⚙️ **لوحة التحكم الإدارية الآلية:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def admin_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    if not is_admin(user.id):
        return
    data = query.data
    
    if data == "back_home":
        await show_main_menu_callback(query, context)
    elif data == "adm_count_users":
        conn = sqlite3.connect("wayxbet.db")
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        cnt = cursor.fetchone()[0]
        conn.close()
        await query.answer(f"عدد اللاعبين: {cnt}", show_alert=True)
    elif data == "adm_maintenance_on":
        set_setting("maintenance", "1")
        await query.answer("🛠 تم تفعيل الصيانة.", show_alert=True)
    elif data == "adm_maintenance_off":
        set_setting("maintenance", "0")
        await query.answer("✅ تم إلغاء الصيانة.", show_alert=True)
    elif data == "adm_players_bal":
        conn = sqlite3.connect("wayxbet.db")
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, balance FROM users LIMIT 20")
        rows = cursor.fetchall()
        conn.close()
        text = "💰 **أرصدة اللاعبين:**\n" + "\n".join([f"ID: `{r[0]}` - الرصيد: {r[1]}" for r in rows])
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]]), parse_mode="Markdown")
    elif data == "adm_saved_accs":
        conn = sqlite3.connect("wayxbet.db")
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, created_account FROM users WHERE created_account IS NOT NULL")
        rows = cursor.fetchall()
        conn.close()
        text = "💾 **حسابات اللاعبين المحفوظة:**\n" + "\n".join([f"ID: `{r[0]}` - الحساب: `{r[1]}`" for r in rows]) if rows else "لا توجد حسابات بعد."
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]]), parse_mode="Markdown")
    elif data == "adm_wd_logs":
        conn = sqlite3.connect("wayxbet.db")
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, method, amount, status, admin_name FROM transactions WHERE type LIKE '%withdraw%' LIMIT 15")
        rows = cursor.fetchall()
        conn.close()
        text = "💸 **سجل طلبات السحب:**\n" + "\n".join([f"ID: {r[0]} | {r[1]} | مبلغ: {r[2]} | الحالة: {r[3]} | الآدمن: {r[4]}" for r in rows]) if rows else "لا توجد سجلات."
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]]), parse_mode="Markdown")
    elif data == "adm_dep_logs":
        conn = sqlite3.connect("wayxbet.db")
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, method, amount, status, admin_name FROM transactions WHERE type='deposit' LIMIT 15")
        rows = cursor.fetchall()
        conn.close()
        text = "📈 **سجل طلبات الشحن:**\n" + "\n".join([f"ID: {r[0]} | {r[1]} | مبلغ: {r[2]} | الحالة: {r[3]} | الآدمن: {r[4]}" for r in rows]) if rows else "لا توجد سجلات."
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]]), parse_mode="Markdown")
    
    # تفاعلات الموافقات والرفض التلقائية للآدمن
    elif data.startswith("approve_acc_"):
        parts = data.split("_")
        target_user = parts[2]
        acc_name = parts[3]
        conn = sqlite3.connect("wayxbet.db")
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET created_account = ? WHERE user_id = ?", (acc_name, target_user))
        conn.commit()
        conn.close()
        await context.bot.send_message(chat_id=int(target_user), text=f"🎉 تم إنشاء حسابك بنجاح:\n`{acc_name}`", parse_mode="Markdown")
        await query.message.edit_text(query.message.text + f"\n\n✅ **تمت الموافقة وتفعيل الحساب بواسطة الآدمن:** {user.first_name}")
    
    elif data.startswith("reject_acc_"):
        target_user = data.split("_")[2]
        await context.bot.send_message(chat_id=int(target_user), text="❌ اسم مستخدم غير صالح أو مرفوض، أعد إنشاء الحساب.")
        await query.message.edit_text(query.message.text + f"\n\n❌ **تم الإلغاء بواسطة الآدمن:** {user.first_name}")

    elif data.startswith("app_dep_"):
        tx_id = data.split("_")[2]
        conn = sqlite3.connect("wayxbet.db")
        cursor = conn.cursor()
        cursor.execute("UPDATE transactions SET status = 'approved', admin_name = ? WHERE id = ?", (user.first_name, tx_id))
        conn.commit()
        conn.close()
        await query.message.edit_text(query.message.text + f"\n\n✅ تمت الموافقة بواسطة الآدمن: {user.first_name}")

    elif data.startswith("rej_dep_"):
        tx_id = data.split("_")[2]
        conn = sqlite3.connect("wayxbet.db")
        cursor = conn.cursor()
        cursor.execute("UPDATE transactions SET status = 'rejected', admin_name = ? WHERE id = ?", (user.first_name, tx_id))
        conn.commit()
        conn.close()
        await query.message.edit_text(query.message.text + f"\n\n❌ تم الرفض بواسطة الآدمن: {user.first_name}")

    elif data.startswith("app_wd_"):
        tx_id = data.split("_")[2]
        conn = sqlite3.connect("wayxbet.db")
        cursor = conn.cursor()
        cursor.execute("UPDATE transactions SET status = 'approved', admin_name = ? WHERE id = ?", (user.first_name, tx_id))
        conn.commit()
        conn.close()
        await query.message.edit_text(query.message.text + f"\n\n✅ تمت الموافقة بواسطة الآدمن: {user.first_name}")

    elif data.startswith("rej_wd_"):
        tx_id = data.split("_")[2]
        conn = sqlite3.connect("wayxbet.db")
        cursor = conn.cursor()
        cursor.execute("UPDATE transactions SET status = 'rejected', admin_name = ? WHERE id = ?", (user.first_name, tx_id))
        conn.commit()
        conn.close()
        await query.message.edit_text(query.message.text + f"\n\n❌ تم الرفض بواسطة الآدمن: {user.first_name}")

def main():
    application = Application.builder().token(TOKEN).build()

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
            WITHDRAW_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_amount_recv)],
            WITHDRAW_ACC: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_acc_recv)],
            GIFT_CODE_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_gift_code)],
            SUPPORT_MESSAGE: [MessageHandler(filters.ALL & ~filters.COMMAND, receive_support_message)],
        },
        fallbacks=[CommandHandler("start", start)],
    )

    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(check_sub_callback, pattern="^check_sub$"))
    application.add_handler(CallbackQueryHandler(wayxbet_menu_handler, pattern="^wayxbet_menu$"))
    application.add_handler(CallbackQueryHandler(deposit_menu, pattern="^deposit$"))
    application.add_handler(CallbackQueryHandler(dep_syriatel_start, pattern="^dep_syriatel$"))
    application.add_handler(CallbackQueryHandler(dep_sham_start, pattern="^dep_sham$"))
    application.add_handler(CallbackQueryHandler(withdraw_menu, pattern="^withdraw$"))
    application.add_handler(CallbackQueryHandler(withdraw_speed_choice, pattern="^wd_speed_"))
    application.add_handler(CallbackQueryHandler(withdraw_method_choice, pattern="^wd_meth_"))
    application.add_handler(CallbackQueryHandler(referrals_menu, pattern="^referrals$"))
    application.add_handler(CallbackQueryHandler(gift_code_menu, pattern="^gift_code$"))
    application.add_handler(CallbackQueryHandler(support_menu, pattern="^support$"))
    application.add_handler(CallbackQueryHandler, pattern="^offers$") # type: ignore
    application.add_handler(CallbackQueryHandler(offers_menu, pattern="^offers$"))
    application.add_handler(CallbackQueryHandler(competitions_menu, pattern="^competitions$"))
    application.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin_panel$"))
    application.add_handler(CallbackQueryHandler(admin_callbacks))
    application.add_handler(CallbackQueryHandler(show_main_menu_callback, pattern="^back_home$"))

    print("Roz Wayxbet Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    main()

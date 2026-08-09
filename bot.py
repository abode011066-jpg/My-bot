import logging
import sqlite3
import threading
import re
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
        self.wfile.write("Roz Wayxbet VIP Bot is active and running!".encode("utf-8"))

def run_dummy_server():
    try:
        server_address = ("", 8080)
        httpd = HTTPServer(server_address, DummyHandler)
        httpd.serve_forever()
    except Exception as e:
        print(f"Dummy server error: {e}")

threading.Thread(target=run_dummy_server, daemon=True).start()
# -------------------------------------------------------------

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = "8812713556:AAGv3bCjQnGgwSGxiqoX8ipuVTvlNTTiLdk"  # توكن البوت الخاص بك
ADMIN_ID = 7255100997
CHANNEL_PROGRAMMER = "@lerafree"
SITE_URL = "https://wayxbet10.com"

# حالات المحادثة (Conversation States)
(
    GET_CAPTCHA_QUESTION,
    GET_CAPTCHA_PIN,
    GET_CONTACT,
    CREATE_ACCOUNT_NAME,
    CREATE_ACCOUNT_PASS,
    DEPOSIT_AMOUNT,
    DEPOSIT_TX,
    BOT_TO_SITE_AMOUNT,
    WITHDRAW_AMOUNT,
    WITHDRAW_ACC,
    GIFT_CODE_INPUT,
    SUPPORT_MESSAGE,
    ADMIN_BROADCAST,
    ADMIN_SEND_PRIVATE_ID,
    ADMIN_SEND_PRIVATE_MSG,
    ADMIN_ADD_GIFT_CODE,
    ADMIN_ADD_GIFT_AMT,
    ADMIN_SET_SETTING_VAL,
    ADMIN_ACTION_NAME,
    ADMIN_REJECT_REASON,
    ADMIN_REPLY_SUPPORT,
    ADMIN_ADD_CHANNEL,
    ADMIN_BAN_USER,
    ADMIN_VIEW_USER_DETAILS,
    ADMIN_ADD_ADMIN_ID,
) = range(25)

# ----------------- إعداد قاعدة البيانات -----------------
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
            wayxbet_user TEXT,
            wayxbet_pass TEXT,
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
            status TEXT DEFAULT 'open',
            reply TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS forced_channels (
            channel_username TEXT PRIMARY KEY
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
        "min_deposit": "5000",
        "min_withdraw": "10000",
        "welcome_bonus": "1000",
        "welcome_bonus_active": "1",
        "currency_ratio": "100" # 100 ليرة قديمة = 1 ليرة جديدة
    }
    
    for k, v in defaults.items():
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
        
    cursor.execute("INSERT OR IGNORE INTO admins (admin_id) VALUES (?)", (ADMIN_ID,))
    cursor.execute("INSERT OR IGNORE INTO forced_channels (channel_username) VALUES (?)", ("@cashinsher",))
    
    conn.commit()
    conn.close()

init_db()

# ----------------- دوان معالجة قاعدة البيانات -----------------
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

def is_banned(user_id):
    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT banned FROM users WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    conn.close()
    return res and res[0] == 1

def format_currency(amount):
    ratio = float(get_setting("currency_ratio") or 100)
    old_lira = float(amount)
    new_lira = old_lira / ratio
    return f"{old_lira:,.0f} ليرة قديمة | {new_lira:,.2f} ليرة جديدة"

async def check_subscription(user_id, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT channel_username FROM forced_channels")
    channels = [row[0] for row in cursor.fetchall()]
    conn.close()

    try:
        m_prog = await context.bot.get_chat_member(chat_id=CHANNEL_PROGRAMMER, user_id=user_id)
        if m_prog.status in ['left', 'kicked']:
            return False
    except:
        return False

    for ch in channels:
        try:
            m = await context.bot.get_chat_member(chat_id=ch, user_id=user_id)
            if m.status in ['left', 'kicked']:
                return False
        except:
            return False
    return True

# ----------------- نظام التسجيل والتحقق الفائق -----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if is_banned(user.id):
        await update.message.reply_text("❌ حسابك محظور من استخدام البوت.")
        return ConversationHandler.END

    if get_setting("maintenance") == "1" and not is_admin(user.id):
        await update.message.reply_text("🛠 البوت متوقف حالياً للصيانة الفنية. يرجى العودة لاحقاً.")
        return ConversationHandler.END

    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT phone FROM users WHERE user_id = ?", (user.id,))
    user_data = cursor.fetchone()
    
    if not user_data:
        args = context.args
        ref_id = int(args[0]) if args and args[0].isdigit() and int(args[0]) != user.id else None
        cursor.execute("INSERT OR IGNORE INTO users (user_id, username, referred_by) VALUES (?, ?, ?)", (user.id, user.username, ref_id))
        
        # منح بونص الإحالة
        if ref_id:
            try:
                ref_percent = float(get_setting("ref_bonus_percent") or 5)
                await context.bot.send_message(
                    chat_id=ref_id,
                    text=f"🔔 قام المستخدم ({user.full_name}) بالدخول عبر رابط إحالتك!\nستحصل على نسبة {ref_percent}% من عملياته."
                )
            except:
                pass

        conn.commit()
        conn.close()
        
        await update.message.reply_text("🛡 **نظام الأمان والتحقق الأول:**\n\nالرجاء إجابة السؤال الرياضي:\nكم يساوي الناتج: **7 + 4 = ?**")
        return GET_CAPTCHA_QUESTION
    
    conn.close()
    return await check_and_show_main_menu(update, context)

async def receive_captcha_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.strip() == "11":
        await update.message.reply_text("🔒 **اختبار الرقم السري الأمني:**\n\nيرجى كتابة الرقم السري التالي للتأكيد: `7788`", parse_mode="Markdown")
        return GET_CAPTCHA_PIN
    else:
        await update.message.reply_text("❌ إجابة خاطئة! كم يساوي الناتج: 7 + 4 = ?")
        return GET_CAPTCHA_QUESTION

async def receive_captcha_pin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.strip() == "7788":
        await update.message.reply_text(
            "📱 أهلاً بك! يرجى مشاركة رقم هاتفك لتأكيد الهوية عبر الضغط على الزر أدناه:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📱 مشاركة رقم الهاتف", request_contact=True)]])
        )
        return GET_CONTACT
    else:
        await update.message.reply_text("❌ رقم سري خاطئ! يرجى إدخال الرقم: `7788`", parse_mode="Markdown")
        return GET_CAPTCHA_PIN

async def receive_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.message.contact:
        conn = sqlite3.connect("wayxbet.db")
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET phone = ? WHERE user_id = ?", (update.message.contact.phone_number, user.id))
        
        # تطبيق البونص الترحيبي عند إتمام التسجيل
        if get_setting("welcome_bonus_active") == "1":
            w_bonus = float(get_setting("welcome_bonus") or 0)
            if w_bonus > 0:
                cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (w_bonus, user.id))
                await update.message.reply_text(f"🎁 **مبروك!** حصلت على بونص ترحيبي بمبلغ: {format_currency(w_bonus)}")
                
        conn.commit()
        conn.close()

    return await check_and_show_main_menu(update, context)

async def check_and_show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user if update.message else update.callback_query.from_user
    
    if not await check_subscription(user.id, context):
        conn = sqlite3.connect("wayxbet.db")
        cursor = conn.cursor()
        cursor.execute("SELECT channel_username FROM forced_channels")
        channels = [row[0] for row in cursor.fetchall()]
        conn.close()

        keyboard = [[InlineKeyboardButton("📢 قناة المبرمج", url=f"https://t.me/{CHANNEL_PROGRAMMER[1:]}")]]
        for idx, ch in enumerate(channels, 1):
            keyboard.append([InlineKeyboardButton(f"📢 قناة إجبارية #{idx}", url=f"https://t.me/{ch[1:]}")])
        keyboard.append([InlineKeyboardButton("✅ تم التحقق من الاشتراك", callback_data="check_sub")])

        msg = "⚠️ **عليك الاشتراك في القنوات التالية أولاً لاستخدام البوت:**\n"
        if update.message:
            await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.callback_query.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
        return ConversationHandler.END

    return await show_main_menu(update, context)

async def check_sub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if await check_subscription(query.from_user.id, context):
        await show_main_menu_callback(query, context)
    else:
        await query.answer("❌ لم تقم بالاشتراك في كافة القنوات الإجبارية بعد!", show_alert=True)

# ----------------- القائمة الرئيسية الاحترافية -----------------
async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    return await render_main_menu(user, update.message.reply_text)

async def show_main_menu_callback(query, context):
    user = query.from_user
    return await render_main_menu(user, query.message.edit_text)

async def render_main_menu(user, send_func):
    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT wayxbet_user, balance FROM users WHERE user_id = ?", (user.id,))
    res = cursor.fetchone()
    conn.close()

    acc_text = f"حسابي ({res[0]})" if res and res[0] else "إنشاء حساب Wayxbet"
    balance = res[1] if res else 0

    keyboard = [
        [InlineKeyboardButton(f"👤 Wayxbet: {acc_text}", callback_data="wayxbet_menu")],
        [InlineKeyboardButton("💰 شحن رصيد", callback_data="deposit"), InlineKeyboardButton("💸 سحب رصيد", callback_data="withdraw")],
        [InlineKeyboardButton("🔄 شحن الموقع من محفظة البوت", callback_data="bot_to_site_deposit")],
        [InlineKeyboardButton("🔗 رابط إحالاتي", callback_data="referrals"), InlineKeyboardButton("🎁 كود هدية", callback_data="gift_code")],
        [InlineKeyboardButton("🎡 عجلة الحظ VIP", web_app=WebAppInfo(url="https://wayxbet10.com/wheel"))],
        [InlineKeyboardButton("🌐 الذهاب إلى الموقع", url=SITE_URL), InlineKeyboardButton("👨‍💻 قناة المبرمج", url=f"https://t.me/{CHANNEL_PROGRAMMER[1:]}")],
        [InlineKeyboardButton("📞 مراسلة الدعم الفني", callback_data="support")]
    ]

    if is_admin(user.id):
        keyboard.append([InlineKeyboardButton("⚙️ لوحة الإدارة (VIP)", callback_data="admin_panel")])

    text = f"🔥 **مرحباً بك في بوت Wayxbet VIP الرسمي**\n\n" \
           f"💵 **رصيد محفظتك:** {format_currency(balance)}\n" \
           f"🌐 **الموقع الرسمي:** {SITE_URL}\n" \
           f"👨‍💻 **قناة المبرمج:** {CHANNEL_PROGRAMMER}"

    await send_func(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return ConversationHandler.END

# ----------------- قسم حساب Wayxbet -----------------
async def wayxbet_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()
    
    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT wayxbet_user, wayxbet_pass FROM users WHERE user_id = ?", (user.id,))
    res = cursor.fetchone()
    conn.close()

    if res and res[0]:
        await query.message.edit_text(
            f"👤 **تفاصيل حسابك في Wayxbet:**\n\n"
            f"🏷 **اسم المستخدم:** `{res[0]}`\n"
            f"🔑 **كلمة المرور:** `{res[1]}`\n\n"
            f"ملاحظة: اضغط على النص لنسخه.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]]),
            parse_mode="Markdown"
        )
        return ConversationHandler.END
    else:
        await query.message.edit_text(
            "📝 **طلب إنشاء حساب جديد على Wayxbet:**\n\n"
            "يرجى إدخال اسم المستخدم المطلوب بالشروط التالية:\n"
            "1️⃣ يبدأ بحرف كبير (Upper case).\n"
            "2️⃣ ينتهي بـ `123@`\n\n"
            "📌 **مثال صالح:** `Rozah123@`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]]),
            parse_mode="Markdown"
        )
        return CREATE_ACCOUNT_NAME

async def receive_account_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    
    # التحقق: حرف أول كبير وينتهي بـ 123@
    if not (text and text[0].isupper() and text.endswith("123@")):
        await update.message.reply_text(
            "❌ **اسم مستخدم غير صالح!**\n"
            "يجب أن يبدأ بحرف كبير وينتهي بـ `123@` (مثال: `Rozah123@`).\nحاول مرة أخرى:"
        )
        return CREATE_ACCOUNT_NAME

    context.user_data['temp_acc_name'] = text
    await update.message.reply_text("🔑 **الآن أدخل كلمة المرور الحساب المطلوبة:**")
    return CREATE_ACCOUNT_PASS

async def receive_account_pass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text.strip()
    user = update.effective_user
    acc_name = context.user_data.get('temp_acc_name')

    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT phone FROM users WHERE user_id = ?", (user.id,))
    phone = cursor.fetchone()[0]
    
    cursor.execute("INSERT INTO account_requests (user_id, wayxbet_user, wayxbet_pass) VALUES (?, ?, ?)", (user.id, acc_name, password))
    req_id = cursor.lastrowid
    conn.commit()
    conn.close()

    admin_kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ موافقة وتفعيل", callback_data=f"app_acc_{req_id}"),
            InlineKeyboardButton("❌ رفض الطلب", callback_data=f"rej_acc_{req_id}")
        ]
    ])

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📥 **طلب إنشاء حساب جديد:**\n\n"
             f"👤 العميل: {user.full_name}\n"
             f"🆔 الآيدي: `{user.id}`\n"
             f"📱 الهاتف: `{phone}`\n"
             f"🏷 الاسم المطلوب: `{acc_name}`\n"
             f"🔑كلمة المرور: `{password}`",
        reply_markup=admin_kb,
        parse_mode="Markdown"
    )

    await update.message.reply_text("✅ تم إرسال طلب إنشاء الحساب بنجاح للإدارة، سيتم إشعارك فور الموافقة.")
    return await show_main_menu(update, context)

# ----------------- شحن الموقع من محفظة البوت -----------------
async def bot_to_site_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT wayxbet_user, balance FROM users WHERE user_id = ?", (user.id,))
    res = cursor.fetchone()
    conn.close()

    if not res or not res[0]:
        await query.message.edit_text(
            "❌ يجب عليك إنشاء حساب Wayxbet أولاً قبل الشحن للموقع!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]])
        )
        return ConversationHandler.END

    min_dep = float(get_setting("min_deposit") or 5000)
    await query.message.edit_text(
        f"🔄 **شحن حساب الموقع من محفظة البوت:**\n\n"
        f"👤 حسابك في الموقع: `{res[0]}`\n"
        f"💵 رصيدك في البوت: {format_currency(res[1])}\n"
        f"🔻 الحد الأدنى للشحن: {format_currency(min_dep)}\n\n"
        f"أدخل المبلغ الذي ترغب بتحويله للموقع:",
        parse_mode="Markdown"
    )
    return BOT_TO_SITE_AMOUNT

async def receive_bot_to_site_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    try:
        amount = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ يرجى إدخال رقم صحيح للمبلغ.")
        return BOT_TO_SITE_AMOUNT

    min_dep = float(get_setting("min_deposit") or 5000)
    if amount < min_dep:
        await update.message.reply_text(f"❌ المبلغ أقل من الحد الأدنى للشحن وهو: {format_currency(min_dep)}")
        return BOT_TO_SITE_AMOUNT

    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT wayxbet_user, phone, balance FROM users WHERE user_id = ?", (user.id,))
    res = cursor.fetchone()

    if res[2] < amount:
        await update.message.reply_text("❌ رصيدك في البوت غير كافٍ لإتمام العملية!")
        conn.close()
        return ConversationHandler.END

    cursor.execute("INSERT INTO transactions (user_id, type, method, amount, status) VALUES (?, 'bot_to_site', 'محفظة البوت', ?, 'pending')", (user.id, amount))
    tx_id = cursor.lastrowid
    conn.commit()
    conn.close()

    admin_kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ موافقة الشحن", callback_data=f"app_tx_{tx_id}"),
            InlineKeyboardButton("❌ رفض", callback_data=f"rej_tx_{tx_id}")
        ]
    ])

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📥 **طلب شحن للموقع من محفظة البوت:**\n\n"
             f"🏷 حساب الموقع Wayxbet: `{res[0]}`\n"
             f"🆔 الآيدي: `{user.id}`\n"
             f"📱 الهاتف: `{res[1]}`\n"
             f"💳 طريقة الشحن: محفظة البوت\n"
             f"💵 المبلغ: {format_currency(amount)}",
        reply_markup=admin_kb,
        parse_mode="Markdown"
    )

    await update.message.reply_text("✅ تم تقديم طلب شحن الموقع من محفظتك بنجاح، انتظر موافقة الأدمن.")
    return await show_main_menu(update, context)

# ----------------- الشحن الخارجي والسحب -----------------
async def deposit_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bonus = get_setting("deposit_bonus")
    bonus_text = f"\n🎁 **بونص شحن مفعل:** {bonus}%" if bonus and float(bonus) > 0 else ""

    keyboard = [
        [InlineKeyboardButton("💳 سيريتل كاش", callback_data="dep_syriatel"), InlineKeyboardButton("💳 شام كاش", callback_data="dep_sham")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]
    ]
    await query.message.edit_text(f"💰 **اختر طريقة الشحن إلى محفظة البوت:**{bonus_text}", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def dep_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    method = "سيريتل كاش" if "syriatel" in query.data else "شام كاش"
    context.user_data['dep_method'] = method

    acc_num = get_setting("syriatel_num") if method == "سيريتل كاش" else get_setting("sham_num")
    min_dep = float(get_setting("min_deposit") or 5000)

    await query.message.edit_text(
        f"💳 **الشحن عبر {method}:**\n\n"
        f"📌 الرقم/العنوان للتحويل: `{acc_num}`\n"
        f"🔻 الحد الأدنى للشحن: {format_currency(min_dep)}\n\n"
        f"أدخل المبلغ الذي قمت بتحويله:",
        parse_mode="Markdown"
    )
    return DEPOSIT_AMOUNT

async def receive_dep_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ أدخل رقم صحيح للمبلغ.")
        return DEPOSIT_AMOUNT

    min_dep = float(get_setting("min_deposit") or 5000)
    if amount < min_dep:
        await update.message.reply_text(f"❌ المبلغ أصغر من الحد الأدنى ({format_currency(min_dep)}).")
        return DEPOSIT_AMOUNT

    context.user_data['dep_amount'] = amount
    await update.message.reply_text("🔢 الآن يرجى إرسال **رقم العملية** للتأكيد:")
    return DEPOSIT_TX

async def receive_dep_tx(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tx_id_str = update.message.text.strip()
    user = update.effective_user
    amount = context.user_data.get('dep_amount')
    method = context.user_data.get('dep_method')

    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT phone, wayxbet_user FROM users WHERE user_id = ?", (user.id,))
    res = cursor.fetchone()
    phone, way_acc = res[0], res[1] or "غير منشأ"

    cursor.execute("INSERT INTO transactions (user_id, type, method, amount, tx_id, status) VALUES (?, 'deposit', ?, ?, ?, 'pending')",
                   (user.id, method, amount, tx_id_str))
    tx_db_id = cursor.lastrowid
    conn.commit()
    conn.close()

    admin_kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ موافقة", callback_data=f"app_tx_{tx_db_id}"),
            InlineKeyboardButton("❌ رفض", callback_data=f"rej_tx_{tx_db_id}")
        ]
    ])

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📥 **طلب شحن خارجي جديد:**\n\n"
             f"🏷 حساب Wayxbet المخزن: `{way_acc}`\n"
             f"🆔 الآيدي: `{user.id}`\n"
             f"📱 الهاتف: `{phone}`\n"
             f"💳 الطريقة: {method}\n"
             f"🔢 رقم العملية: `{tx_id_str}`\n"
             f"💵 المبلغ: {format_currency(amount)}",
        reply_markup=admin_kb,
        parse_mode="Markdown"
    )

    await update.message.reply_text("✅ تم تقديم طلب الشحن الإدارة تتراجع وسوف تصلك رسالة عند التأكيد.")
    return await show_main_menu(update, context)

# ----------------- نظام السحب -----------------
async def withdraw_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    fast_fee = get_setting("fast_withdraw_fee")
    slow_fee = get_setting("slow_withdraw_fee")

    keyboard = [
        [InlineKeyboardButton(f"⚡ سحب سريع (عمولة {fast_fee}%)", callback_data="wd_speed_fast")],
        [InlineKeyboardButton(f"🐢 سحب بطيء (عمولة {slow_fee}%)", callback_data="wd_speed_slow")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]
    ]
    await query.message.edit_text("💸 **اختر نوع سرعة السحب:**", reply_markup=InlineKeyboardMarkup(keyboard))

async def withdraw_speed_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['wd_speed'] = "سريع" if "fast" in query.data else "بطيء"

    keyboard = [
        [InlineKeyboardButton("💳 سيريتل كاش", callback_data="wd_m_syriatel"), InlineKeyboardButton("💳 شام كاش", callback_data="wd_m_sham")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]
    ]
    await query.message.edit_text("💳 **اختر طريقة استلام المبلغ:**", reply_markup=InlineKeyboardMarkup(keyboard))

async def withdraw_method_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['wd_method'] = "سيريتل كاش" if "syriatel" in query.data else "شام كاش"
    min_wd = float(get_setting("min_withdraw") or 10000)

    await query.message.edit_text(
        f"💵 **أدخل المبلغ المراد سحبه:**\n"
        f"🔻 الحد الأدنى للسحب: {format_currency(min_wd)}",
        parse_mode="Markdown"
    )
    return WITHDRAW_AMOUNT

async def receive_withdraw_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ أدخل مبلغ صحيح.")
        return WITHDRAW_AMOUNT

    min_wd = float(get_setting("min_withdraw") or 10000)
    if amount < min_wd:
        await update.message.reply_text(f"❌ المبلغ أقل من الحد الأدنى للسحب وهو: {format_currency(min_wd)}")
        return WITHDRAW_AMOUNT

    user = update.effective_user
    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user.id,))
    bal = cursor.fetchone()[0]
    conn.close()

    if bal < amount:
        await update.message.reply_text("❌ رصيدك الحالي لا يكفي لإتمام عملية السحب.")
        return WITHDRAW_AMOUNT

    context.user_data['wd_amount'] = amount
    await update.message.reply_text("📱 **أدخل رقم الحساب/المحفظة لاستلام الرصيد عليه:**")
    return WITHDRAW_ACC

async def receive_withdraw_acc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    acc_num = update.message.text.strip()
    user = update.effective_user
    amount = context.user_data.get('wd_amount')
    method = context.user_data.get('wd_method')
    speed = context.user_data.get('wd_speed')

    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT phone, wayxbet_user FROM users WHERE user_id = ?", (user.id,))
    res = cursor.fetchone()
    phone, way_acc = res[0], res[1] or "غير منشأ"

    cursor.execute("INSERT INTO transactions (user_id, type, method, amount, account_num, status) VALUES (?, 'withdraw', ?, ?, ?, 'pending')",
                   (user.id, f"{method} ({speed})", amount, acc_num))
    tx_id = cursor.lastrowid
    conn.commit()
    conn.close()

    admin_kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ موافقة السحب", callback_data=f"app_tx_{tx_id}"),
            InlineKeyboardButton("❌ رفض", callback_data=f"rej_tx_{tx_id}")
        ]
    ])

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📤 **طلب سحب جديد ({speed}):**\n\n"
             f"🏷 حساب Wayxbet: `{way_acc}`\n"
             f"🆔 الآيدي: `{user.id}`\n"
             f"📱 الهاتف: `{phone}`\n"
             f"💳 طريقة السحب: {method}\n"
             f"📲 حساب المستلم: `{acc_num}`\n"
             f"💵 المبلغ: {format_currency(amount)}",
        reply_markup=admin_kb,
        parse_mode="Markdown"
    )

    await update.message.reply_text("✅ تم إرسال طلب السحب للإدارة وسيتم المعالجة قريباً.")
    return await show_main_menu(update, context)

# ----------------- الأكواد والدعم والإحالات -----------------
async def referrals_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    ref_link = f"https://t.me/{context.bot.username}?start={user.id}"
    ref_percent = get_setting("ref_bonus_percent")

    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users WHERE referred_by = ?", (user.id,))
    count = cursor.fetchone()[0]
    conn.close()

    await query.message.edit_text(
        f"🔗 **نظام الإحالات الـ VIP:**\n\n"
        f"👥 عدد الأشخاص الذين دعيتهم: `{count}`\n"
        f"🎁 نسبة ربحك من عملياتهم: `{ref_percent}%`\n\n"
        f"🔗 **رابط إحالتك الخاص:**\n`{ref_link}`",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]]),
        parse_mode="Markdown"
    )

async def gift_code_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("🎁 **أدخل كود الهدية الخاص بك هنا:**")
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
        cursor.execute("DELETE FROM gift_codes WHERE code = ?", (code,))
        cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user.id))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"🎉 **تهانينا!** تم استخدام الكود ونقل {format_currency(amount)} لرصيدك.")
    else:
        conn.close()
        await update.message.reply_text("❌ الكود غير صحيح أو تم استخدامه سابقاً.")

    return await show_main_menu(update, context)

async def support_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("📞 **أرسل رسالتك وسوف يتواصل معك الدعم الفني فوراً:**")
    return SUPPORT_MESSAGE

async def receive_support_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.message.text.strip()

    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO support_tickets (user_id, message) VALUES (?, ?)", (user.id, msg))
    t_id = cursor.lastrowid
    conn.commit()
    conn.close()

    admin_kb = InlineKeyboardMarkup([[InlineKeyboardButton("💬 رد على الرسالة", callback_data=f"reply_sup_{t_id}")]])
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📩 **رسالة دعم جديدة (Ticket #{t_id}):**\n\n"
             f"👤 من: {user.full_name} (`{user.id}`)\n"
             f"💬 النص: {msg}",
        reply_markup=admin_kb,
        parse_mode="Markdown"
    )

    await update.message.reply_text("✅ تم إرسال رسالتك للادارة، انتظر الرد.")
    return await show_main_menu(update, context)

# ----------------- لوحة الإدارة الاحترافية (VIP Admin Panel) -----------------
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return

    m_status = "مفعل 🔴" if get_setting("maintenance") == "1" else "معطل 🟢"
    w_status = "مفعل 🟢" if get_setting("welcome_bonus_active") == "1" else "معطل 🔴"

    keyboard = [
        [InlineKeyboardButton("➕ إضافة أدمن جديد", callback_data="adm_add_admin"), InlineKeyboardButton("📢 إضافة قناة إجبارية", callback_data="adm_add_channel")],
        [InlineKeyboardButton("🎁 إنشاء كود هدية", callback_data="adm_add_gift")],
        [InlineKeyboardButton("👥 إدارة المستخدمين والتفاصيل", callback_data="adm_users_manage")],
        [InlineKeyboardButton("📜 سجل طلبات الحسابات", callback_data="adm_log_acc"), InlineKeyboardButton("📜 سجل العمليات (شحن/سحب)", callback_data="adm_log_tx")],
        [InlineKeyboardButton(f"🛠 الصيانة: {m_status}", callback_data="adm_toggle_maint"), InlineKeyboardButton(f"🎁 البونص الترحيبي: {w_status}", callback_data="adm_toggle_welc")],
        [InlineKeyboardButton("⚙️ تعديل الإعدادات والحدود", callback_data="adm_settings")],
        [InlineKeyboardButton("📢 إرسال إذاعة جماعية", callback_data="adm_broadcast"), InlineKeyboardButton("✉️ إرسال رسالة خاصة", callback_data="adm_send_private")],
        [InlineKeyboardButton("🔙 الصفحة الرئيسية", callback_data="back_home")]
    ]

    await query.message.edit_text("⚙️ **لوحة التحكم والإدارة الفائقة VIP:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def admin_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("تعديل حساب سيريتل كاش", callback_data="set_syriatel_num"), InlineKeyboardButton("تعديل حساب شام كاش", callback_data="set_sham_num")],
        [InlineKeyboardButton("تعديل بونص الشحن (%)", callback_data="set_deposit_bonus"), InlineKeyboardButton("تعديل نسبة الإحالة (%)", callback_data="set_ref_bonus_percent")],
        [InlineKeyboardButton("تعديل حد أدنى للشحن", callback_data="set_min_deposit"), InlineKeyboardButton("تعديل حد أدنى للسحب", callback_data="set_min_withdraw")],
        [InlineKeyboardButton("عمولة السحب البطئ (%)", callback_data="set_slow_withdraw_fee"), InlineKeyboardButton("عمولة السحب السريع (%)", callback_data="set_fast_withdraw_fee")],
        [InlineKeyboardButton("تعديل مبلغ البونص الترحيبي", callback_data="set_welcome_bonus")],
        [InlineKeyboardButton("🔙 لوحة الإدارة", callback_data="admin_panel")]
    ]
    await query.message.edit_text("⚙️ **إعدادات الحدود والعمولات والحسابات:**", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_set_setting_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    setting_key = query.data.replace("set_", "")
    context.user_data['edit_setting_key'] = setting_key
    await query.message.edit_text(f"📝 أدخل القيمة الجديدة لـ `{setting_key}`:", parse_mode="Markdown")
    return ADMIN_SET_SETTING_VAL

async def admin_receive_setting_val(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    key = context.user_data.get('edit_setting_key')
    set_setting(key, val)
    await update.message.reply_text(f"✅ تم تحديث `{key}` إلى: `{val}` بنجاح!", parse_mode="Markdown")
    return await show_main_menu(update, context)

# ----------------- معالجة الموافقات بطلب اسم الأدمن للتوثيق -----------------
async def admin_approve_request_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    context.user_data['pending_action_data'] = data
    await query.message.reply_text("✍️ **يرجى كتابة اسمك (كأدمن) لتسجيل الموافقة باسمك في السجل:**")
    return ADMIN_ACTION_NAME

async def admin_execute_approved_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_name = update.message.text.strip()
    data = context.user_data.get('pending_action_data')

    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()

    if data.startswith("app_acc_"):
        req_id = int(data.replace("app_acc_", ""))
        cursor.execute("SELECT user_id, wayxbet_user, wayxbet_pass FROM account_requests WHERE id = ?", (req_id,))
        req = cursor.fetchone()

        if req:
            u_id, w_user, w_pass = req
            cursor.execute("UPDATE account_requests SET status = 'approved', admin_name = ? WHERE id = ?", (admin_name, req_id))
            cursor.execute("UPDATE users SET wayxbet_user = ?, wayxbet_pass = ? WHERE user_id = ?", (w_user, w_pass, u_id))

            try:
                await context.bot.send_message(
                    chat_id=u_id,
                    text=f"🎉 **تمت الموافقة على إنشاء حسابك على موقع Wayxbet!**\n\n"
                         f"🏷 **اسم المستخدم:** `{w_user}`\n"
                         f"🔑 **كلمة المرور:** `{w_pass}`\n"
                         f"الموافق: {admin_name}",
                    parse_mode="Markdown"
                )
            except:
                pass
            await update.message.reply_text(f"✅ تمت الموافقة وتوثيق العملية باسم الأدمن: {admin_name}")

    elif data.startswith("app_tx_"):
        tx_id = int(data.replace("app_tx_", ""))
        cursor.execute("SELECT user_id, type, amount FROM transactions WHERE id = ?", (tx_id,))
        tx = cursor.fetchone()

        if tx:
            u_id, tx_type, amount = tx
            cursor.execute("UPDATE transactions SET status = 'approved', admin_name = ? WHERE id = ?", (admin_name, tx_id))

            if tx_type == 'deposit':
                bonus_pct = float(get_setting("deposit_bonus") or 0)
                bonus_amount = (amount * bonus_pct) / 100
                total_added = amount + bonus_amount

                cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (total_added, u_id))

                msg = f"✅ **تمت الموافقة على شحن حسابك بمبلغ {format_currency(amount)}.**\n"
                if bonus_amount > 0:
                    msg += f"🎁 تمت إضافة بونص شحن ({bonus_pct}%): {format_currency(bonus_amount)}\n"
                    msg += f"💵 إجمالي الرصيد المضاف: {format_currency(total_added)}"

                try:
                    await context.bot.send_message(chat_id=u_id, text=msg, parse_mode="Markdown")
                except:
                    pass

            elif tx_type == 'bot_to_site':
                cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, u_id))
                try:
                    await context.bot.send_message(chat_id=u_id, text=f"✅ **تم شحن حسابك على الموقع بمبلغ {format_currency(amount)} من محفظتك.**", parse_mode="Markdown")
                except:
                    pass

            elif tx_type == 'withdraw':
                cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, u_id))
                try:
                    await context.bot.send_message(chat_id=u_id, text=f"✅ **تمت الموافقة على طلب سحب المبلغ: {format_currency(amount)}.**", parse_mode="Markdown")
                except:
                    pass

            await update.message.reply_text(f"✅ تم تنفيذ العملية وتوثيقها باسم الأدمن: {admin_name}")

    conn.commit()
    conn.close()
    return await show_main_menu(update, context)

# ----------------- الإذاعة والمستخدمين والحظر -----------------
async def admin_add_gift_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("🎁 أدخل كود الهدية الجديد (مثال: `VIP2026`):", parse_mode="Markdown")
    return ADMIN_ADD_GIFT_CODE

async def admin_receive_gift_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_gift_code'] = update.message.text.strip()
    await update.message.reply_text("💵 أدخل القيمة المالية للكود:")
    return ADMIN_ADD_GIFT_AMT

async def admin_receive_gift_amt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amt = float(update.message.text.strip())
        code = context.user_data.get('new_gift_code')
        conn = sqlite3.connect("wayxbet.db")
        cursor = conn.cursor()
        cursor.execute("INSERT INTO gift_codes (code, amount) VALUES (?, ?)", (code, amt))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ تم إنشاء كود الهدية `{code}` بقيمة {format_currency(amt)} بنجاح!", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ: {e}")
    return await show_main_menu(update, context)

async def admin_add_admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("➕ أرسل آيدي (User ID) الأدمن الجديد:")
    return ADMIN_ADD_ADMIN_ID

async def admin_receive_admin_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        new_adm = int(update.message.text.strip())
        conn = sqlite3.connect("wayxbet.db")
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO admins (admin_id) VALUES (?)", (new_adm,))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ تم منح صلاحيات الأدمن للآيدي: `{new_adm}` بنجاح!", parse_mode="Markdown")
    except:
        await update.message.reply_text("❌ أدخل آيدي صحيح الرقم.")
    return await show_main_menu(update, context)

async def admin_add_channel_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("📢 أدخل معرف القناة الإجبارية الجديدة (مثال: `@channel_user`):")
    return ADMIN_ADD_CHANNEL

async def admin_receive_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ch = update.message.text.strip()
    if not ch.startswith("@"):
        ch = "@" + ch
    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO forced_channels (channel_username) VALUES (?)", (ch,))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅ تم إضافة القناة الإجبارية `{ch}` بنجاح!", parse_mode="Markdown")
    return await show_main_menu(update, context)

async def admin_broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("📢 أدخل نص الرسالة الجماعية التي تريد إرسالها لجميع الأعضاء:")
    return ADMIN_BROADCAST

async def admin_receive_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    conn.close()

    count = 0
    for u in users:
        try:
            await context.bot.send_message(chat_id=u[0], text=f"📢 **إشعار جماعي من الإدارة:**\n\n{text}", parse_mode="Markdown")
            count += 1
        except:
            pass

    await update.message.reply_text(f"✅ تم إرسال الإذاعة بنجاح إلى {count} مستخدم.")
    return await show_main_menu(update, context)

async def admin_toggle_maint(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    curr = get_setting("maintenance")
    new_v = "0" if curr == "1" else "1"
    set_setting("maintenance", new_v)
    await query.answer("تم تغيير حالة الصيانة بنجاح!", show_alert=True)
    return await admin_panel(update, context)

async def admin_toggle_welc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    curr = get_setting("welcome_bonus_active")
    new_v = "0" if curr == "1" else "1"
    set_setting("welcome_bonus_active", new_v)
    await query.answer("تم تغيير حالة البونص الترحيبي!", show_alert=True)
    return await admin_panel(update, context)

# ----------------- إلغاء العودة والبدء -----------------
async def back_home_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    return await show_main_menu_callback(query, context)

# ----------------- بناء وتطبيق معالجات البوت -----------------
def main():
    app = Application.builder().token(TOKEN).build()

    # معالج المحادثات العام الشامل
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CallbackQueryHandler(wayxbet_menu_handler, pattern="^wayxbet_menu$"),
            CallbackQueryHandler(deposit_menu, pattern="^deposit$"),
            CallbackQueryHandler(dep_start, pattern="^dep_"),
            CallbackQueryHandler(withdraw_menu, pattern="^withdraw$"),
            CallbackQueryHandler(withdraw_speed_choice, pattern="^wd_speed_"),
            CallbackQueryHandler(withdraw_method_choice, pattern="^wd_m_"),
            CallbackQueryHandler(bot_to_site_start, pattern="^bot_to_site_deposit$"),
            CallbackQueryHandler(gift_code_start, pattern="^gift_code$"),
            CallbackQueryHandler(support_start, pattern="^support$"),
            CallbackQueryHandler(admin_set_setting_start, pattern="^set_"),
            CallbackQueryHandler(admin_add_gift_start, pattern="^adm_add_gift$"),
            CallbackQueryHandler(admin_add_admin_start, pattern="^adm_add_admin$"),
            CallbackQueryHandler(admin_add_channel_start, pattern="^adm_add_channel$"),
            CallbackQueryHandler(admin_broadcast_start, pattern="^adm_broadcast$"),
        ],
        states={
            GET_CAPTCHA_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_captcha_question)],
            GET_CAPTCHA_PIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_captcha_pin)],
            GET_CONTACT: [MessageHandler(filters.CONTACT | filters.TEXT, receive_contact)],
            CREATE_ACCOUNT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_account_name)],
            CREATE_ACCOUNT_PASS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_account_pass)],
            DEPOSIT_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_dep_amount)],
            DEPOSIT_TX: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_dep_tx)],
            BOT_TO_SITE_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_bot_to_site_amount)],
            WITHDRAW_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_withdraw_amount)],
            WITHDRAW_ACC: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_withdraw_acc)],
            GIFT_CODE_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_gift_code)],
            SUPPORT_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_support_message)],
            ADMIN_SET_SETTING_VAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_receive_setting_val)],
            ADMIN_ACTION_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_execute_approved_action)],
            ADMIN_ADD_GIFT_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_receive_gift_code)],
            ADMIN_ADD_GIFT_AMT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_receive_gift_amt)],
            ADMIN_ADD_ADMIN_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_receive_admin_id)],
            ADMIN_ADD_CHANNEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_receive_channel)],
            ADMIN_BROADCAST: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_receive_broadcast)],
        },
        fallbacks=[
            CommandHandler("start", start),
            CallbackQueryHandler(back_home_callback, pattern="^back_home$")
        ],
        allow_reentry=True
    )

    app.add_handler(conv_handler)
    
    # معالجات الأزرار المباشرة
    app.add_handler(CallbackQueryHandler(check_sub_callback, pattern="^check_sub$"))
    app.add_handler(CallbackQueryHandler(referrals_menu, pattern="^referrals$"))
    app.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin_panel$"))
    app.add_handler(CallbackQueryHandler(admin_settings_menu, pattern="^adm_settings$"))
    app.add_handler(CallbackQueryHandler(admin_toggle_maint, pattern="^adm_toggle_maint$"))
    app.add_handler(CallbackQueryHandler(admin_toggle_welc, pattern="^adm_toggle_welc$"))
    app.add_handler(CallbackQueryHandler(back_home_callback, pattern="^back_home$"))
    app.add_handler(CallbackQueryHandler(admin_approve_request_prompt, pattern="^(app_acc_|app_tx_)"))

    print("Roz Wayxbet VIP Bot started successfully...")
    app.run_polling()

if __name__ == "__main__":
    main()

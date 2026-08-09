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

# ----------------- خادم الويب وعجلة الحظ لـ Render -----------------
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
    button { padding: 14px 32px; font-size: 18px; font-weight: bold; background: linear-gradient(135deg, #f59e0b, #d97706); color: white; border: none; border-radius: 12px; cursor: pointer; box-shadow: 0 4px 12px rgba(245, 158, 11, 0.4); }
    button:active { transform: scale(0.98); }
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
    tg.ready();
    tg.expand();

    const canvas = document.getElementById('wheel');
    const ctx = canvas.getContext('2d');
    const prizes = ['1,000 ليرة', 'حظ أوفر', '5,000 ليرة', 'لفة إضافية', '10,000 ليرة', '2,000 ليرة'];
    const colors = ['#ef4444', '#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899'];
    let startAngle = 0;
    const arc = (2 * Math.PI) / prizes.length;
    let isSpinning = false;

    function drawWheel() {
      ctx.clearRect(0, 0, 280, 280);
      prizes.forEach((prize, i) => {
        const angle = startAngle + i * arc;
        ctx.fillStyle = colors[i];
        ctx.beginPath();
        ctx.arc(140, 140, 130, angle, angle + arc);
        ctx.arc(140, 140, 0, angle + arc, angle, true);
        ctx.fill();
        ctx.save();
        ctx.fillStyle = '#ffffff';
        ctx.font = 'bold 14px Tahoma';
        ctx.translate(140 + Math.cos(angle + arc/2) * 80, 140 + Math.sin(angle + arc/2) * 80);
        ctx.rotate(angle + arc/2 + Math.PI/2);
        ctx.fillText(prize, -ctx.measureText(prize).width / 2, 0);
        ctx.restore();
      });
    }
    drawWheel();

    function spin() {
      if(isSpinning) return;
      isSpinning = true;
      document.getElementById('result').innerText = "جاري تدوير العجلة...";
      let speed = Math.random() * 0.3 + 0.4;
      let duration = 3500;
      let start = Date.now();
      
      let timer = setInterval(() => {
        if (Date.now() - start > duration) {
          clearInterval(timer);
          isSpinning = false;
          const winningIndex = Math.floor((prizes.length - (startAngle % (2 * Math.PI)) / arc) % prizes.length);
          const wonPrize = prizes[winningIndex];
          document.getElementById('result').innerText = "🎉 مبروك! حصلت على: " + wonPrize;
          tg.sendData(JSON.stringify({ prize: wonPrize }));
          return;
        }
        startAngle += speed;
        speed *= 0.985;
        drawWheel();
      }, 20);
    }
  </script>
</body>
</html>"""

class WebServerHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        if "/wheel" in self.path or self.path == "/":
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(WHEEL_HTML.encode("utf-8"))
        else:
            self.send_header("Content-type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("Roz Wayxbet VIP Bot is active and running!".encode("utf-8"))

def run_dummy_server():
    try:
        server_address = ("", 8080)
        httpd = HTTPServer(server_address, WebServerHandler)
        httpd.serve_forever()
    except Exception as e:
        print(f"Dummy server error: {e}")

threading.Thread(target=run_dummy_server, daemon=True).start()
# -------------------------------------------------------------

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = "8812713556:AAGv3bCjQnGgwSGxiqoX8ipuVTvlNTTiLdk"
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
        "currency_ratio": "100",
        "free_spin_on_ref": "1" # 1 ميزة اللفة المجانية للإحالة مفعلة، 0 معطلة
    }
    
    for k, v in defaults.items():
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
        
    cursor.execute("INSERT OR IGNORE INTO admins (admin_id) VALUES (?)", (ADMIN_ID,))
    cursor.execute("INSERT OR IGNORE INTO forced_channels (channel_username) VALUES (?)", ("@cashinsher",))
    
    conn.commit()
    conn.close()

init_db()

# ----------------- دوال معالجة قاعدة البيانات -----------------
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
        
        # منح بونص الإحالة ولفّة مجانية عند التفعيل
        if ref_id:
            try:
                ref_percent = float(get_setting("ref_bonus_percent") or 5)
                spin_msg = ""
                if get_setting("free_spin_on_ref") == "1":
                    cursor.execute("UPDATE users SET spins = spins + 1 WHERE user_id = ?", (ref_id,))
                    spin_msg = "\n🎁 تم منحك لفة عجلة مجانية إضافية!"

                await context.bot.send_message(
                    chat_id=ref_id,
                    text=f"🔔 قام المستخدم ({user.full_name}) بالدخول عبر رابط إحالتك!\nستحصل على نسبة {ref_percent}% من عملياته عند التفعيل.{spin_msg}"
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
        [InlineKeyboardButton("🎡 عجلة الحظ VIP", web_app=WebAppInfo(url="https://my-bot-a8sy.onrender.com/wheel"))],
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
    phone_res = cursor.fetchone()
    phone = phone_res[0] if phone_res else "غير متوفر"
    
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
             f"🔑 كلمة المرور: `{password}`",
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
        return BOT_TO_SITE_AMOUNT

    # خصم الرصيد مؤقتاً لحين موافقة الأدمن
    cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user.id))
    cursor.execute("INSERT INTO transactions (user_id, type, method, amount, account_num) VALUES (?, 'bot_to_site', 'Internal', ?, ?)", (user.id, amount, res[0]))
    tx_id = cursor.lastrowid
    conn.commit()
    conn.close()

    admin_kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ موافقة وتنفيذ", callback_data=f"app_tx_{tx_id}"),
            InlineKeyboardButton("❌ رفض الطلب", callback_data=f"rej_tx_{tx_id}")
        ]
    ])

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"🔄 **طلب تحويل رصيد للموقع:**\n\n"
             f"👤 العميل: {user.full_name}\n"
             f"🆔 الآيدي: `{user.id}`\n"
             f"🏷 حساب الموقع: `{res[0]}`\n"
             f"💵 المبلغ: {format_currency(amount)}",
        reply_markup=admin_kb,
        parse_mode="Markdown"
    )

    await update.message.reply_text("✅ تم تقديم طلب الشحن بنجاح، وسيتم إشعارك فور التنفيذ من الإدارة.")
    return await show_main_menu(update, context)

# ----------------- الشحن والسحب والكود والإحالات -----------------
async def deposit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    syria_num = get_setting("syriatel_num")
    sham_num = get_setting("sham_num")
    
    kb = [
        [InlineKeyboardButton("📱 سيريتل كاش", callback_data="dep_syriatel")],
        [InlineKeyboardButton("💳 شام كاش", callback_data="dep_sham")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]
    ]
    
    await query.message.edit_text(
        f"💰 **اختر طريقة الشحن المناسبة:**\n\n"
        f"📱 **سيريتل كاش:** `{syria_num}`\n"
        f"💳 **شام كاش:** `{sham_num}`\n\n"
        f"📌 يرجى التحويل أولاً ثم الضغط على الوسيلة أدناه لتقديم الطلب.",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def deposit_method_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    method = "سيريتل كاش" if query.data == "dep_syriatel" else "شام كاش"
    context.user_data['dep_method'] = method
    
    await query.message.edit_text(
        f"📥 لقد اخترت: **{method}**\n\nيرجى إدخال المبلغ المشحون بالليرة السورية:",
        parse_mode="Markdown"
    )
    return DEPOSIT_AMOUNT

async def receive_deposit_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ يرجى إدخال مبلغ صحيح.")
        return DEPOSIT_AMOUNT

    min_dep = float(get_setting("min_deposit") or 5000)
    if amount < min_dep:
        await update.message.reply_text(f"❌ الحد الأدنى للشحن هو: {format_currency(min_dep)}")
        return DEPOSIT_AMOUNT

    context.user_data['dep_amount'] = amount
    await update.message.reply_text("📝 يرجى إرسال رقم العملية (رمز المعاملة / TXID):")
    return DEPOSIT_TX

async def receive_deposit_tx(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tx_id_str = update.message.text.strip()
    user = update.effective_user
    amount = context.user_data.get('dep_amount')
    method = context.user_data.get('dep_method')

    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO transactions (user_id, type, method, amount, tx_id) VALUES (?, 'deposit', ?, ?, ?)", (user.id, method, amount, tx_id_str))
    req_id = cursor.lastrowid
    conn.commit()
    conn.close()

    admin_kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ موافقة وشحن", callback_data=f"app_tx_{req_id}"),
            InlineKeyboardButton("❌ رفض", callback_data=f"rej_tx_{req_id}")
        ]
    ])

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📥 **طلب شحن جديد:**\n\n"
             f"👤 العميل: {user.full_name}\n"
             f"🆔 الآيدي: `{user.id}`\n"
             f"💳 الوسيلة: {method}\n"
             f"💵 المبلغ: {format_currency(amount)}\n"
             f"🧾 رقم العملية: `{tx_id_str}`",
        reply_markup=admin_kb,
        parse_mode="Markdown"
    )

    await update.message.reply_text("✅ تم إرسال طلب الشحن للإدارة، سيتم إشعارك عند الاعتماد.")
    return await show_main_menu(update, context)

async def withdraw_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    min_w = float(get_setting("min_withdraw") or 10000)
    await query.message.edit_text(
        f"💸 **طلب سحب رصيد:**\n\n"
        f"🔻 الحد الأدنى للسحب: {format_currency(min_w)}\n"
        f"أدخل المبلغ المراد سحبه:",
        parse_mode="Markdown"
    )
    return WITHDRAW_AMOUNT

async def receive_withdraw_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    try:
        amount = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ يرجى إدخال مبلغ صحيح.")
        return WITHDRAW_AMOUNT

    min_w = float(get_setting("min_withdraw") or 10000)
    if amount < min_w:
        await update.message.reply_text(f"❌ المبلغ أقل من الحد الأدنى السحب وهو: {format_currency(min_w)}")
        return WITHDRAW_AMOUNT

    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user.id,))
    res = cursor.fetchone()

    if not res or res[0] < amount:
        await update.message.reply_text("❌ رصيدك الحالي غير كافٍ لهذا السحب!")
        conn.close()
        return WITHDRAW_AMOUNT

    context.user_data['w_amount'] = amount
    conn.close()
    await update.message.reply_text("📱 أدخل رقم الحساب / المحفظة التي ترغب بالاستلام عليها:")
    return WITHDRAW_ACC

async def receive_withdraw_acc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    acc_num = update.message.text.strip()
    user = update.effective_user
    amount = context.user_data.get('w_amount')

    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user.id))
    cursor.execute("INSERT INTO transactions (user_id, type, method, amount, account_num) VALUES (?, 'withdraw', 'Cash', ?, ?)", (user.id, amount, acc_num))
    tx_id = cursor.lastrowid
    conn.commit()
    conn.close()

    admin_kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ موافقة وتحويل", callback_data=f"app_tx_{tx_id}"),
            InlineKeyboardButton("❌ رفض الطلب", callback_data=f"rej_tx_{tx_id}")
        ]
    ])

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"💸 **طلب سحب رصيد جديد:**\n\n"
             f"👤 العميل: {user.full_name}\n"
             f"🆔 الآيدي: `{user.id}`\n"
             f"💵 المبلغ: {format_currency(amount)}\n"
             f"📱 رقم الحساب المستلم: `{acc_num}`",
        reply_markup=admin_kb,
        parse_mode="Markdown"
    )

    await update.message.reply_text("✅ تم تسجيل طلب السحب وخصم المبلغ من محفظتك، وسيتم التحويل قريباً.")
    return await show_main_menu(update, context)

# ----------------- الإحالات والأرباح -----------------
async def referrals_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users WHERE referred_by = ?", (user.id,))
    total_refs = cursor.fetchone()[0]

    cursor.execute("SELECT active_refs, spins FROM users WHERE user_id = ?", (user.id,))
    res = cursor.fetchone()
    active_refs = res[0] if res else 0
    spins = res[1] if res else 0
    conn.close()

    bot_username = (await context.bot.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start={user.id}"

    status_msg = "✅ أنت مؤهل للحصول على أرباح الإحالات!" if active_refs >= 5 else f"⚠️ يلزمك الوصول إلى **5 إحالات نشطة** للتأهل. (متبقي {5 - active_refs})"

    await query.message.edit_text(
        f"🔗 **نظام الإحالات والأرباح الدوريّة:**\n\n"
        f"👥 **إجمالي الإحالات:** {total_refs}\n"
        f"⚡ **الإحالات النشطة:** {active_refs} / 5\n"
        f"🎡 **لفة العجلة المتاحة:** {spins}\n"
        f"📌 **الحالة:** {status_msg}\n\n"
        f"📅 **ملاحظة التوزيع:** يتم توزيع الأرباح كل **10 أيام** للعملاء المؤهلين الذين لديهم 5 إحالات نشطة أو أكثر.\n\n"
        f"🔗 **رابط إحالتك الخاص:**\n`{ref_link}`",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]]),
        parse_mode="Markdown"
    )

# ----------------- الكود والهدية والدعم -----------------
async def gift_code_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("🎁 أدخل رمز كود الهدية للتفعيل:")
    return GIFT_CODE_INPUT

async def receive_gift_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code_input = update.message.text.strip()
    user = update.effective_user

    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT amount FROM gift_codes WHERE code = ?", (code_input,))
    res = cursor.fetchone()

    if res:
        amount = res[0]
        cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user.id))
        cursor.execute("DELETE FROM gift_codes WHERE code = ?", (code_input,))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"🎉 **مبروك!** تم شحن كود الهدية بنجاح واضافة: {format_currency(amount)}")
    else:
        conn.close()
        await update.message.reply_text("❌ كود الهدية غير صحيح أو تم استخدامه من قبل.")

    return await show_main_menu(update, context)

async def support_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("📞 أدخل رسالتك لإرسالها مباشرة لفريق الدعم الفني:")
    return SUPPORT_MESSAGE

async def receive_support_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text.strip()
    user = update.effective_user

    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO support_tickets (user_id, message) VALUES (?, ?)", (user.id, msg))
    ticket_id = cursor.lastrowid
    conn.commit()
    conn.close()

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📩 **رسالة دعم جديدة (#{ticket_id}):**\n\n"
             f"👤 العميل: {user.full_name}\n"
             f"🆔 الآيدي: `{user.id}`\n"
             f"💬 الرسالة: {msg}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💬 رد على الرسالة", callback_data=f"rep_sup_{ticket_id}")]])
    )

    await update.message.reply_text("✅ تم إرسال رسالتك إلى الدعم الفني، وسيتم الرد عليك قريباً.")
    return await show_main_menu(update, context)

# ----------------- لوحة الإدارة ومعالجة اسم الأدمن -----------------
async def admin_panel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    if not is_admin(user.id):
        return

    await query.answer()
    free_spin_state = "مفعلة ✅" if get_setting("free_spin_on_ref") == "1" else "معطلة ❌"

    kb = [
        [InlineKeyboardButton("👥 تقرير الإحالات النشطة والتوزيع (10 أيام)", callback_data="admin_active_refs")],
        [InlineKeyboardButton(f"⚙️ لفة مجانية للإحالة: {free_spin_state}", callback_data="toggle_free_spin")],
        [InlineKeyboardButton("📢 إذاعة عامة", callback_data="adm_broadcast"), InlineKeyboardButton("🎁 إضافة كود هدية", callback_data="adm_add_gift")],
        [InlineKeyboardButton("⚙️ إعدادات الأرقام والنسب", callback_data="adm_settings")],
        [InlineKeyboardButton("🔙 الصفحة الرئيسية", callback_data="back_home")]
    ]

    await query.message.edit_text(
        "⚙️ **لوحة التحكم والإدارة الاحترافية (VIP):**\n\nاختر الخيار المطلوبة من القائمة أدناه:",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )

# تقرير العملاء المؤهلين للإحالات 5+ نشطين
async def admin_active_refs_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer()

    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, phone, active_refs FROM users WHERE active_refs >= 5")
    eligible_users = cursor.fetchall()

    if not eligible_users:
        await query.message.edit_text(
            "📊 **تقرير الإحالات النشطة:**\n\nلا يوجد عملاء لديهم 5 إحالات نشطة حتى الآن.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]])
        )
        conn.close()
        return

    msg = "📊 **تقرير العملاء المؤهلين للإحالات (5+ إحالات نشطة):**\n🗓 **ملاحظة:** يتم التوزيع الدوري كل 10 أيام.\n\n"
    for u in eligible_users:
        uid, uname, phone, a_refs = u
        cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE status = 'approved' AND type = 'deposit' AND user_id IN (SELECT user_id FROM users WHERE referred_by = ?)", (uid,))
        volume = cursor.fetchone()[0]
        msg += f"👤 العميل: @{uname or 'غير_محدد'} | ID: `{uid}`\n📱 الهاتف: `{phone or 'غير_مسجل'}`\n👥 الإحالات النشطة: {a_refs}\n💵 مبالغ الشحن عن طريقهم: {format_currency(volume)}\n----------------------------------\n"

    conn.close()
    await query.message.edit_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]]), parse_mode="Markdown")

async def toggle_free_spin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    current = get_setting("free_spin_on_ref")
    new_val = "0" if current == "1" else "1"
    set_setting("free_spin_on_ref", new_val)
    await query.answer("تم تغيير حالة ميزة اللفة المجانية للإحالة بنجاح!")
    return await admin_panel_handler(update, context)

# ----------------- الحل الشامل لاستجابة اسم الأدمن -----------------
async def admin_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    if data.startswith("app_acc_") or data.startswith("app_tx_"):
        action_type = "app_acc" if "app_acc_" in data else "app_tx"
        item_id = data.split("_")[-1]
        context.user_data['pending_admin_action'] = {'type': action_type, 'id': item_id}
        
        await query.message.reply_text("👤 **الرجاء كتابة وإرسال اسم الأدمن المسؤول لتأكيد الموافقة وتوثيق العملية:**")
        return ADMIN_ACTION_NAME

    elif data.startswith("rej_acc_") or data.startswith("rej_tx_"):
        action_type = "rej_acc" if "rej_acc_" in data else "rej_tx"
        item_id = data.split("_")[-1]
        context.user_data['pending_admin_action'] = {'type': action_type, 'id': item_id}
        
        await query.message.reply_text("📝 **الرجاء كتابة سبب الرفض واسم الأدمن:**")
        return ADMIN_REJECT_REASON

async def receive_admin_action_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_name = update.message.text.strip()
    action_info = context.user_data.get('pending_admin_action')

    if not action_info:
        await update.message.reply_text("❌ حدث خطأ أو انتهت جلسة الإجراء.")
        return ConversationHandler.END

    action_type = action_info['type']
    item_id = action_info['id']

    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()

    if action_type == "app_acc":
        cursor.execute("UPDATE account_requests SET status = 'approved', admin_name = ? WHERE id = ?", (admin_name, item_id))
        cursor.execute("SELECT user_id, wayxbet_user, wayxbet_pass FROM account_requests WHERE id = ?", (item_id,))
        req = cursor.fetchone()
        if req:
            uid, w_user, w_pass = req
            cursor.execute("UPDATE users SET wayxbet_user = ?, wayxbet_pass = ? WHERE user_id = ?", (w_user, w_pass, uid))
            
            # زيادة الإحالات النشطة للمُحيل إن وجد
            cursor.execute("SELECT referred_by FROM users WHERE user_id = ?", (uid,))
            ref_res = cursor.fetchone()
            if ref_res and ref_res[0]:
                cursor.execute("UPDATE users SET active_refs = active_refs + 1 WHERE user_id = ?", (ref_res[0],))

            conn.commit()
            try:
                await context.bot.send_message(
                    chat_id=uid,
                    text=f"✅ **تم إنشاء وتفعيل حسابك بنجاح!**\n\n🏷 اسم المستخدم: `{w_user}`\n🔑 كلمة المرور: `{w_pass}`\n👮‍♂️ الأدمن المسؤول: {admin_name}",
                    parse_mode="Markdown"
                )
            except:
                pass
        await update.message.reply_text(f"✅ تم تفعيل الطلب #{item_id} بنجاح برابط الأدمن ({admin_name}).")

    elif action_type == "app_tx":
        cursor.execute("UPDATE transactions SET status = 'approved', admin_name = ? WHERE id = ?", (admin_name, item_id))
        cursor.execute("SELECT user_id, type, amount FROM transactions WHERE id = ?", (item_id,))
        tx = cursor.fetchone()
        if tx:
            uid, t_type, amt = tx
            if t_type == "deposit":
                cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amt, uid))
                cursor.execute("SELECT referred_by FROM users WHERE user_id = ?", (uid,))
                ref_res = cursor.fetchone()
                if ref_res and ref_res[0]:
                    cursor.execute("UPDATE users SET active_refs = active_refs + 1 WHERE user_id = ?", (ref_res[0],))

            conn.commit()
            try:
                await context.bot.send_message(
                    chat_id=uid,
                    text=f"✅ **تمت الموافقة على عملية ({t_type}) بمبلغ {format_currency(amt)} بنجاح!**\n👮‍♂️ الأدمن المسؤول: {admin_name}",
                    parse_mode="Markdown"
                )
            except:
                pass
        await update.message.reply_text(f"✅ تم اعتماد المعاملة المالية #{item_id} بواسطة الأدمن ({admin_name}).")

    conn.close()
    context.user_data.pop('pending_admin_action', None)
    return await show_main_menu(update, context)

async def receive_admin_reject_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reason_str = update.message.text.strip()
    action_info = context.user_data.get('pending_admin_action')

    if not action_info:
        await update.message.reply_text("❌ انتهت جلسة الطلب.")
        return ConversationHandler.END

    action_type = action_info['type']
    item_id = action_info['id']

    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()

    if action_type == "rej_acc":
        cursor.execute("UPDATE account_requests SET status = 'rejected', reject_reason = ? WHERE id = ?", (reason_str, item_id))
        cursor.execute("SELECT user_id FROM account_requests WHERE id = ?", (item_id,))
        uid = cursor.fetchone()[0]
        conn.commit()
        try:
            await context.bot.send_message(chat_id=uid, text=f"❌ **تم رفض طلب إنشاء الحساب.**\n💬 السبب والتفاصيل: {reason_str}")
        except:
            pass

    elif action_type == "rej_tx":
        cursor.execute("SELECT user_id, type, amount FROM transactions WHERE id = ?", (item_id,))
        tx = cursor.fetchone()
        if tx:
            uid, t_type, amt = tx
            # إرجاع المبلغ للمحفظة في حال السحب أو التحويل للموقع
            if t_type in ["withdraw", "bot_to_site"]:
                cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amt, uid))
            cursor.execute("UPDATE transactions SET status = 'rejected', reject_reason = ? WHERE id = ?", (reason_str, item_id))
            conn.commit()
            try:
                await context.bot.send_message(chat_id=uid, text=f"❌ **تم رفض عملية ({t_type}) بمبلغ {format_currency(amt)}.**\n💬 السبب: {reason_str}")
            except:
                pass

    conn.close()
    await update.message.reply_text("❌ تم تسجيل الرفض وإشعار المستخدم بنجاح.")
    context.user_data.pop('pending_admin_action', None)
    return await show_main_menu(update, context)

# ----------------- إلغاء ورجوع -----------------
async def back_home_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    return await show_main_menu_callback(query, context)

# ----------------- التشغيل الرئيسي والمعالجات -----------------
def main():
    app = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CallbackQueryHandler(show_main_menu_callback, pattern="^back_home$"),
            CallbackQueryHandler(wayxbet_menu_handler, pattern="^wayxbet_menu$"),
            CallbackQueryHandler(deposit_start, pattern="^deposit$"),
            CallbackQueryHandler(deposit_method_select, pattern="^dep_"),
            CallbackQueryHandler(withdraw_start, pattern="^withdraw$"),
            CallbackQueryHandler(bot_to_site_start, pattern="^bot_to_site_deposit$"),
            CallbackQueryHandler(referrals_handler, pattern="^referrals$"),
            CallbackQueryHandler(gift_code_handler, pattern="^gift_code$"),
            CallbackQueryHandler(support_handler, pattern="^support$"),
            CallbackQueryHandler(admin_panel_handler, pattern="^admin_panel$"),
            CallbackQueryHandler(admin_active_refs_report, pattern="^admin_active_refs$"),
            CallbackQueryHandler(toggle_free_spin_handler, pattern="^toggle_free_spin$"),
            CallbackQueryHandler(admin_action_callback, pattern="^(app_acc_|rej_acc_|app_tx_|rej_tx_)"),
            CallbackQueryHandler(check_sub_callback, pattern="^check_sub$"),
        ],
        states={
            GET_CAPTCHA_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_captcha_question)],
            GET_CAPTCHA_PIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_captcha_pin)],
            GET_CONTACT: [MessageHandler(filters.CONTACT, receive_contact)],
            CREATE_ACCOUNT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_account_name)],
            CREATE_ACCOUNT_PASS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_account_pass)],
            DEPOSIT_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_deposit_amount)],
            DEPOSIT_TX: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_deposit_tx)],
            BOT_TO_SITE_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_bot_to_site_amount)],
            WITHDRAW_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_withdraw_amount)],
            WITHDRAW_ACC: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_withdraw_acc)],
            GIFT_CODE_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_gift_code)],
            SUPPORT_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_support_message)],
            ADMIN_ACTION_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_admin_action_name)],
            ADMIN_REJECT_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_admin_reject_reason)],
        },
        fallbacks=[
            CommandHandler("start", start),
            CallbackQueryHandler(back_home_handler, pattern="^back_home$")
        ],
        allow_reentry=True
    )

    app.add_handler(conv_handler)
    print("🤖 Roz Wayxbet VIP Bot is running successfully!")
    app.run_polling()

if __name__ == "__main__":
    main()

import logging
import sqlite3
import threading
import re
import json
import random
from urllib.parse import parse_qs, urlparse
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

    async function spin() {
      if(isSpinning) return;
      const userId = tg.initDataUnsafe?.user?.id;
      if(!userId) {
        document.getElementById('result').innerText = "❌ تعذر التعرّف على حسابك بفي التلجرام!";
        return;
      }

      isSpinning = true;
      document.getElementById('result').innerText = "جاري الاتصال بالسيرفر والتحقق...";

      try {
        const response = await fetch('/api/spin?user_id=' + userId);
        const data = await response.json();

        if(!data.success) {
          document.getElementById('result').innerText = "❌ " + (data.error || "لا تملك لفات مجانية متاحة!");
          isSpinning = false;
          return;
        }

        const winningIndex = data.winning_index;
        const wonPrize = data.prize_name;

        let totalRounds = 5;
        let targetAngle = (2 * Math.PI * totalRounds) + ((prizes.length - winningIndex - 0.5) * arc);
        let currentRotation = 0;
        let speed = 0.3;

        let timer = setInterval(() => {
          if (currentRotation >= targetAngle) {
            clearInterval(timer);
            isSpinning = false;
            document.getElementById('result').innerText = "🎉 مبروك! حصلت على: " + wonPrize;
            tg.sendData(JSON.stringify({ prize: wonPrize }));
            return;
          }
          startAngle += speed;
          currentRotation += speed;
          if (targetAngle - currentRotation < Math.PI) {
            speed = Math.max(0.01, speed * 0.95);
          }
          drawWheel();
        }, 20);

      } catch (err) {
        document.getElementById('result').innerText = "❌ حدث خطأ أثناء الاتصال بالسيرفر.";
        isSpinning = false;
      }
    }
  </script>
</body>
</html>"""

# ----------------- معالجة طلبات API للعجلة -----------------
class WebServerHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/spin":
            params = parse_qs(parsed.query)
            user_id = params.get("user_id", [None])[0]

            self.send_response(200)
            self.send_header("Content-type", "application/json; charset=utf-8")
            self.end_headers()

            if not user_id:
                self.wfile.write(json.dumps({"success": False, "error": "المستخدم غير معرّف"}).encode("utf-8"))
                return

            conn = sqlite3.connect("wayxbet.db")
            cursor = conn.cursor()
            cursor.execute("SELECT spins FROM users WHERE user_id = ?", (user_id,))
            res = cursor.fetchone()

            if not res or res[0] <= 0:
                conn.close()
                self.wfile.write(json.dumps({"success": False, "error": "ليس لديك لفات مجانية متاحة!"}).encode("utf-8"))
                return

            cursor.execute("SELECT id, prize_name, weight, amount, prize_type FROM wheel_prizes ORDER BY id ASC")
            prizes_data = cursor.fetchall()

            if not prizes_data:
                conn.close()
                self.wfile.write(json.dumps({"success": False, "error": "لم يتم إعداد الجوائز بعد"}).encode("utf-8"))
                return

            weights = [p[2] for p in prizes_data]
            chosen = random.choices(prizes_data, weights=weights, k=1)[0]
            prize_id, prize_name, weight, amount, prize_type = chosen

            winning_index = prize_id - 1

            cursor.execute("UPDATE users SET spins = spins - 1 WHERE user_id = ?", (user_id,))
            if prize_type == "balance" and amount > 0:
                cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
            elif prize_type == "spin" and amount > 0:
                cursor.execute("UPDATE users SET spins = spins + ? WHERE user_id = ?", (int(amount), user_id))

            conn.commit()
            conn.close()

            resp = {
                "success": True,
                "winning_index": winning_index,
                "prize_name": prize_name,
                "amount": amount,
                "type": prize_type
            }
            self.wfile.write(json.dumps(resp, ensure_ascii=False).encode("utf-8"))

        elif "/wheel" in self.path or self.path == "/":
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(WHEEL_HTML.encode("utf-8"))
        else:
            self.send_response(200)
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

# حالات المحادثة
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
    ADMIN_EDIT_WHEEL_WEIGHT,
    ADMIN_CHANGE_USER_BAL
) = range(27)

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
        "ref_bonus_percent": "5",
        "fast_withdraw_fee": "5",
        "slow_withdraw_fee": "0",
        "maintenance": "0",
        "min_deposit": "5000",
        "min_withdraw": "10000",
        "welcome_bonus": "1000",
        "welcome_bonus_active": "1",
        "currency_ratio": "100",
        "free_spin_on_ref": "1"
    }
    
    for k, v in defaults.items():
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
        
    cursor.execute("INSERT OR IGNORE INTO admins (admin_id) VALUES (?)", (ADMIN_ID,))
    cursor.execute("INSERT OR IGNORE INTO forced_channels (channel_username) VALUES (?)", ("@cashinsher",))
    
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

# ----------------- لوحة الإدارة المتطورة بالكامل (VIP) -----------------
async def admin_panel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    if not is_admin(user.id):
        return

    await query.answer()
    free_spin_state = "مفعلة ✅" if get_setting("free_spin_on_ref") == "1" else "معطلة ❌"

    kb = [
        [InlineKeyboardButton("📊 تقرير الإحالات النشطة والتوزيع", callback_data="admin_active_refs")],
        [InlineKeyboardButton("🎡 خوارزمية العجلة والنسب", callback_data="adm_wheel_config")],
        [InlineKeyboardButton(f"⚙️ لفة مجانية للإحالة: {free_spin_state}", callback_data="toggle_free_spin")],
        [InlineKeyboardButton("📢 إذاعة عامة", callback_data="adm_broadcast"), InlineKeyboardButton("🎁 إضافة كود هدية", callback_data="adm_add_gift")],
        [InlineKeyboardButton("⚙️ إعدادات الأرقام والأسعار", callback_data="adm_settings"), InlineKeyboardButton("📢 القنوات الإجبارية", callback_data="adm_channels")],
        [InlineKeyboardButton("👤 إدارة مستخدم / حظر", callback_data="adm_users_manage"), InlineKeyboardButton("👮‍♂️ إضافة أدمن جديد", callback_data="adm_add_admin")],
        [InlineKeyboardButton("📜 سجلات المعاملات", callback_data="adm_logs_view")],
        [InlineKeyboardButton("🔙 الصفحة الرئيسية", callback_data="back_home")]
    ]

    await query.message.edit_text(
        "⚙️ **لوحة التحكم والإدارة الاحترافية (VIP):**\n\nاختر الخيار المطلوب من القائمة أدناه:",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )

# ----------------- خوارزمية العجلة والنسب -----------------
async def admin_wheel_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer()

    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, prize_name, weight, amount, prize_type FROM wheel_prizes ORDER BY id ASC")
    prizes = cursor.fetchall()
    conn.close()

    total_weight = sum([p[2] for p in prizes]) or 1

    msg = "🎡 **تعديل خوارزمية العجلة والنسب المئوية:**\n\n"
    kb = []
    for p in prizes:
        pid, pname, weight, amt, ptype = p
        percentage = (weight / total_weight) * 100
        msg += f"🔹 **الجائزة #{pid}:** {pname}\n" \
               f"   🎯 الوزن: `{weight}` ({percentage:.1f}%)\n"
        kb.append([InlineKeyboardButton(f"✏️ تعديل وزن (#{pid}) {pname}", callback_data=f"edit_w_{pid}")])

    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")])
    await query.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def admin_edit_wheel_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    prize_id = query.data.split("_")[-1]
    context.user_data['edit_prize_id'] = prize_id
    await query.answer()
    await query.message.edit_text(f"🔢 أدخل الوزن الاحتالي الجديد للجائزة #{prize_id} (كلما زاد الرقم زادت نسبة ظهور الجائزة):")
    return ADMIN_EDIT_WHEEL_WEIGHT

async def receive_admin_edit_wheel_weight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("❌ يرجى إدخال رقم صحيح.")
        return ADMIN_EDIT_WHEEL_WEIGHT

    new_weight = int(text)
    prize_id = context.user_data.get('edit_prize_id')

    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE wheel_prizes SET weight = ? WHERE id = ?", (new_weight, prize_id))
    conn.commit()
    conn.close()

    await update.message.reply_text(f"✅ تم تحديث نسبة الجائزة #{prize_id} بنجاح!")
    return await show_main_menu(update, context)

# ----------------- الإعدادات العامة والأرقام -----------------
async def admin_settings_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer()

    syria = get_setting("syriatel_num")
    sham = get_setting("sham_num")
    min_d = get_setting("min_deposit")
    min_w = get_setting("min_withdraw")
    ratio = get_setting("currency_ratio")

    kb = [
        [InlineKeyboardButton(f"📱 سيريتل: {syria}", callback_data="set_key_syriatel_num")],
        [InlineKeyboardButton(f"💳 شام كاش: {sham}", callback_data="set_key_sham_num")],
        [InlineKeyboardButton(f"🔻 أدنى شحن: {min_d}", callback_data="set_key_min_deposit")],
        [InlineKeyboardButton(f"🔻 أدنى سحب: {min_w}", callback_data="set_key_min_withdraw")],
        [InlineKeyboardButton(f"🔱 نسبة الليرة: {ratio}", callback_data="set_key_currency_ratio")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]
    ]

    await query.message.edit_text("⚙️ **إعدادات البوت والتحويلات:**\n\nاضغط على المفتاح للقيام بالتعديل:", reply_markup=InlineKeyboardMarkup(kb))

async def admin_set_setting_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    key = query.data.replace("set_key_", "")
    context.user_data['setting_key'] = key
    await query.answer()
    await query.message.edit_text(f"📝 أدخل القيمة الجديدة للإعداد (`{key}`):", parse_mode="Markdown")
    return ADMIN_SET_SETTING_VAL

async def receive_admin_setting_val(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    key = context.user_data.get('setting_key')

    if key:
        set_setting(key, val)
        await update.message.reply_text(f"✅ تم حفظ القيمة الجديدة للإعداد `{key}` بنجاح!", parse_mode="Markdown")

    return await show_main_menu(update, context)

# ----------------- الإذاعة العامة -----------------
async def admin_broadcast_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer()
    await query.message.edit_text("📢 أدخل نص الرسالة للإذاعة على كافة مستخدمي البوت:")
    return ADMIN_BROADCAST

async def receive_admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_text = update.message.text
    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE banned = 0")
    users = cursor.fetchall()
    conn.close()

    count = 0
    for u in users:
        try:
            await context.bot.send_message(chat_id=u[0], text=f"📢 **تنويه هام من الإدارة:**\n\n{msg_text}", parse_mode="Markdown")
            count += 1
        except:
            pass

    await update.message.reply_text(f"✅ تم إرسال الإذاعة بنجاح إلى {count} مستخدم.")
    return await show_main_menu(update, context)

# ----------------- إنشاء كود هدية -----------------
async def admin_add_gift_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer()
    await query.message.edit_text("🎁 اكتب اسم كود الهدية (مثال: `GIFT1000`):", parse_mode="Markdown")
    return ADMIN_ADD_GIFT_CODE

async def receive_gift_code_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip().upper()
    context.user_data['new_gift_code'] = code
    await update.message.reply_text(f"💵 أدخل مبلغ الهدية لكود `{code}`:", parse_mode="Markdown")
    return ADMIN_ADD_GIFT_AMT

async def receive_gift_code_amt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amt = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ يرجى كتابة مبلغ صحيح.")
        return ADMIN_ADD_GIFT_AMT

    code = context.user_data.get('new_gift_code')
    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO gift_codes (code, amount) VALUES (?, ?)", (code, amt))
    conn.commit()
    conn.close()

    await update.message.reply_text(f"✅ تم إنشاء كود الهدية `{code}` بقيمة {format_currency(amt)} بنجاح!", parse_mode="Markdown")
    return await show_main_menu(update, context)

# ----------------- الرد على الدعم الفني -----------------
async def admin_reply_support_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    ticket_id = query.data.split("_")[-1]
    context.user_data['rep_ticket_id'] = ticket_id
    await query.answer()
    await query.message.edit_text(f"💬 اكتب نص الرد على تذكرة الدعم #{ticket_id}:")
    return ADMIN_REPLY_SUPPORT

async def receive_admin_reply_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_msg = update.message.text.strip()
    ticket_id = context.user_data.get('rep_ticket_id')

    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM support_tickets WHERE id = ?", (ticket_id,))
    res = cursor.fetchone()

    if res:
        uid = res[0]
        cursor.execute("UPDATE support_tickets SET status = 'closed', reply = ? WHERE id = ?", (reply_msg, ticket_id))
        conn.commit()
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=f"📞 **رد الدعم الفني على استفسارك:**\n\n💬 {reply_msg}",
                parse_mode="Markdown"
            )
        except:
            pass
        await update.message.reply_text(f"✅ تم إرسال الرد للعميل على التذكرة #{ticket_id}.")

    conn.close()
    return await show_main_menu(update, context)

# ----------------- إدارة المستخدمين والحظر والأدمن -----------------
async def admin_users_manage_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer()

    kb = [
        [InlineKeyboardButton("🔍 تفاصيل مستخدم", callback_data="adm_view_u"), InlineKeyboardButton("🚫 حظر / فك حظر مستخدم", callback_data="adm_ban_u")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]
    ]
    await query.message.edit_text("👤 **إدارة المستخدمين والحظر:**", reply_markup=InlineKeyboardMarkup(kb))

async def admin_view_user_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("🔎 أدخل آيدي المستخدم (ID) للبحث عن تفاصيله:")
    return ADMIN_VIEW_USER_DETAILS

async def receive_admin_view_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid_str = update.message.text.strip()
    if not uid_str.isdigit():
        await update.message.reply_text("❌ يرجى إدخال آيدي رقمي صحيح.")
        return ADMIN_VIEW_USER_DETAILS

    uid = int(uid_str)
    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, phone, username, balance, spins, active_refs, wayxbet_user, banned FROM users WHERE user_id = ?", (uid,))
    u = cursor.fetchone()
    conn.close()

    if not u:
        await update.message.reply_text("❌ المستخدم غير موجود بالسيستم!")
    else:
        banned_str = "نعم 🚫" if u[7] == 1 else "لا ✅"
        msg = f"👤 **تفاصيل حساب المستخدم:**\n\n" \
              f"🆔 الآيدي: `{u[0]}`\n" \
              f"🏷 اليوزر: @{u[2] or 'لا يوجد'}\n" \
              f"📱 الهاتف: `{u[1] or 'غير مسجل'}`\n" \
              f"💵 الرصيد: {format_currency(u[3])}\n" \
              f"🎡 لفات العجلة: {u[4]}\n" \
              f"👥 الإحالات النشطة: {u[5]}\n" \
              f"🏷 حساب Wayxbet: `{u[6] or 'غير موجود'}`\n" \
              f"🚫 محظور: {banned_str}"
        await update.message.reply_text(msg, parse_mode="Markdown")

    return await show_main_menu(update, context)

async def admin_ban_user_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("🚫 أدخل آيدي المستخدم (ID) لتعديل حالة حظره:")
    return ADMIN_BAN_USER

async def receive_admin_ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid_str = update.message.text.strip()
    if not uid_str.isdigit():
        await update.message.reply_text("❌ يرجى إدخال آيدي صحيح.")
        return ADMIN_BAN_USER

    uid = int(uid_str)
    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT banned FROM users WHERE user_id = ?", (uid,))
    res = cursor.fetchone()

    if res:
        new_banned = 0 if res[0] == 1 else 1
        cursor.execute("UPDATE users SET banned = ? WHERE user_id = ?", (new_banned, uid))
        conn.commit()
        st = "تم حظره 🚫" if new_banned == 1 else "تم فك حظره ✅"
        await update.message.reply_text(f"✅ المستخدم `{uid}` {st}.", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ لم يتم العثور على المستخدم.")

    conn.close()
    return await show_main_menu(update, context)

async def admin_add_admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer()
    await query.message.edit_text("👮‍♂️ أدخل آيدي (ID) الشخص المراد إضافته كـ أدمن:")
    return ADMIN_ADD_ADMIN_ID

async def receive_admin_add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid_str = update.message.text.strip()
    if not uid_str.isdigit():
        await update.message.reply_text("❌ يرجى إدخال آيدي رقمي صحيح.")
        return ADMIN_ADD_ADMIN_ID

    uid = int(uid_str)
    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO admins (admin_id) VALUES (?)", (uid,))
    conn.commit()
    conn.close()

    await update.message.reply_text(f"✅ تم منح صلاحيات الأدمن للمستخدم `{uid}` بنجاح!", parse_mode="Markdown")
    return await show_main_menu(update, context)

# ----------------- إدارة القنوات الإجبارية -----------------
async def admin_channels_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer()

    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT channel_username FROM forced_channels")
    chans = cursor.fetchall()
    conn.close()

    msg = "📢 **قائمة القنوات الإجبارية الحالية:**\n\n"
    kb = []
    for c in chans:
        ch = c[0]
        msg += f"• {ch}\n"
        kb.append([InlineKeyboardButton(f"❌ حذف {ch}", callback_data=f"del_ch_{ch}")])

    kb.append([InlineKeyboardButton("➕ إضافة قناة جديدة", callback_data="add_ch_new")])
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")])

    await query.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(kb))

async def admin_channel_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    if data.startswith("del_ch_"):
        ch = data.replace("del_ch_", "")
        conn = sqlite3.connect("wayxbet.db")
        cursor = conn.cursor()
        cursor.execute("DELETE FROM forced_channels WHERE channel_username = ?", (ch,))
        conn.commit()
        conn.close()
        await query.message.reply_text(f"✅ تم حذف القناة {ch} بنجاح.")
        return await admin_panel_handler(update, context)

    elif data == "add_ch_new":
        await query.message.reply_text("📢 أدخل معرف القناة الجديد مع الأت (مثال: `@mychannel`):")
        return ADMIN_ADD_CHANNEL

async def receive_admin_add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ch = update.message.text.strip()
    if not ch.startswith("@"):
        ch = "@" + ch

    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO forced_channels (channel_username) VALUES (?)", (ch,))
    conn.commit()
    conn.close()

    await update.message.reply_text(f"✅ تم إضافة القناة {ch} بنجاح إلى الاشتراك الإجباري.")
    return await show_main_menu(update, context)

# ----------------- عرض السجلات والأنشطة -----------------
async def admin_logs_view_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer()

    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, user_id, type, amount, status, admin_name, created_at FROM transactions ORDER BY id DESC LIMIT 10")
    logs = cursor.fetchall()
    conn.close()

    msg = "📜 **آخر 10 معاملات وسجلات في السيستم:**\n\n"
    for l in logs:
        msg += f"🆔 `#TX{l[0]}` | العميل: `{l[1]}`\n" \
               f"🔹 النوع: {l[2]} | المبلغ: {l[3]:,.0f}\n" \
               f"📌 الحالة: {l[4]} | الأدمن: `{l[5] or 'تلقائي'}`\n" \
               f"📅 التاريخ: {l[6]}\n----------------------------------\n"

    await query.message.edit_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]]), parse_mode="Markdown")

# ----------------- تقرير العملاء النشطين -----------------
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
    await query.message.edit_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]), parse_mode="Markdown")

async def toggle_free_spin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    current = get_setting("free_spin_on_ref")
    new_val = "0" if current == "1" else "1"
    set_setting("free_spin_on_ref", new_val)
    await query.answer("تم تغيير حالة ميزة اللفة المجانية للإحالة بنجاح!")
    return await admin_panel_handler(update, context)

# ----------------- معالجة وإجراء اسم الأدمن للطلبات -----------------
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
        await update.message.reply_text(f"✅ تم تفعيل الطلب #{item_id} بنجاح بواسطة الأدمن ({admin_name}).")

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
            CallbackQueryHandler(admin_wheel_config, pattern="^adm_wheel_config$"),
            CallbackQueryHandler(admin_edit_wheel_start, pattern="^edit_w_"),
            CallbackQueryHandler(admin_settings_handler, pattern="^adm_settings$"),
            CallbackQueryHandler(admin_set_setting_start, pattern="^set_key_"),
            CallbackQueryHandler(admin_broadcast_handler, pattern="^adm_broadcast$"),
            CallbackQueryHandler(admin_add_gift_handler, pattern="^adm_add_gift$"),
            CallbackQueryHandler(admin_reply_support_start, pattern="^rep_sup_"),
            CallbackQueryHandler(admin_users_manage_handler, pattern="^adm_users_manage$"),
            CallbackQueryHandler(admin_view_user_start, pattern="^adm_view_u$"),
            CallbackQueryHandler(admin_ban_user_start, pattern="^adm_ban_u$"),
            CallbackQueryHandler(admin_add_admin_start, pattern="^adm_add_admin$"),
            CallbackQueryHandler(admin_channels_handler, pattern="^adm_channels$"),
            CallbackQueryHandler(admin_channel_action, pattern="^(del_ch_|add_ch_new)"),
            CallbackQueryHandler(admin_logs_view_handler, pattern="^adm_logs_view$"),
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
            ADMIN_BROADCAST: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_admin_broadcast)],
            ADMIN_ADD_GIFT_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_gift_code_name)],
            ADMIN_ADD_GIFT_AMT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_gift_code_amt)],
            ADMIN_SET_SETTING_VAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_admin_setting_val)],
            ADMIN_REPLY_SUPPORT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_admin_reply_support)],
            ADMIN_ADD_CHANNEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_admin_add_channel)],
            ADMIN_BAN_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_admin_ban_user)],
            ADMIN_VIEW_USER_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_admin_view_user)],
            ADMIN_ADD_ADMIN_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_admin_add_admin)],
            ADMIN_EDIT_WHEEL_WEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_admin_edit_wheel_weight)],
        },
        fallbacks=[
            CommandHandler("start", start),
            CallbackQueryHandler(back_home_handler, pattern="^back_home$")
        ],
        allow_reentry=True
    )

    app.add_handler(conv_handler)
    print("🤖 Roz Wayxbet VIP Bot is running successfully with all algorithms & admin features!")
    app.run_polling()

if __name__ == "__main__":
    main()

import logging
import sqlite3
import threading
import re
import json
import random
import time
from urllib.parse import parse_qs, urlparse
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
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
    ConversationHandler,
)

# ----------------- نظام الحماية ضد الرشق (Anti-Spam System) -----------------
USER_LAST_ACTION = {}
FLOOD_INTERVAL = 1.2  # الحد الأدنى بين الطلبات بالثواني

def is_flooding(user_id: int) -> bool:
    """التحقق مما إذا كان المستخدم يقوم بالرشق أو إرسال طلبات سريعة جداً"""
    now = time.time()
    last_time = USER_LAST_ACTION.get(user_id, 0)
    if now - last_time < FLOOD_INTERVAL:
        return True
    USER_LAST_ACTION[user_id] = now
    return False

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
    
    if is_flooding(user.id):
        return ConversationHandler.END

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
    
    if not user_data or not user_data[0]:
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
        # تصحيح الزر ليكون ReplyKeyboardMarkup لطلب جهة الاتصال بشكل صحيح وفق Telegram API
        keyboard = ReplyKeyboardMarkup(
            [[KeyboardButton("📱 مشاركة رقم الهاتف السوري", request_contact=True)]],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        await update.message.reply_text(
            "📱 أهلاً بك! يرجى مشاركة رقم هاتفك السوري لتأكيد الهوية ومنع الحسابات الوهمية عبر الضغط على الزر أدناه:",
            reply_markup=keyboard
        )
        return GET_CONTACT
    else:
        await update.message.reply_text("❌ رقم سري خاطئ! يرجى إدخال الرقم: `7788`", parse_mode="Markdown")
        return GET_CAPTCHA_PIN

async def receive_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not update.message.contact:
        await update.message.reply_text("⚠️ يرجى استخدام الزر المخصص لمشاركة رقم الهاتف السفلي!")
        return GET_CONTACT

    # التحقق من أن رقم الهاتف المباشر ينتمي للمستخدم نفسه لعدم التزوير
    if update.message.contact.user_id != user.id:
        await update.message.reply_text("❌ يرجى مشاركة رقم هاتفك الشخصي الخاص بحسابك هذا فقط!")
        return GET_CONTACT

    phone = update.message.contact.phone_number.strip()
    clean_phone = phone.replace("+", "").replace(" ", "")

    # التحقق من أن الرقم سوري (+963 أو 09)
    if not (clean_phone.startswith("9639") or clean_phone.startswith("09") or (clean_phone.startswith("9") and len(clean_phone) == 9)):
        await update.message.reply_text("❌ يرجى مشاركة رقم هاتف سوري فعال (سيرياتيل أو ام تي ان) للبدء!")
        return GET_CONTACT

    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET phone = ? WHERE user_id = ?", (phone, user.id))
    
    if get_setting("welcome_bonus_active") == "1":
        w_bonus = float(get_setting("welcome_bonus") or 0)
        if w_bonus > 0:
            cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (w_bonus, user.id))
            await update.message.reply_text(
                f"🎁 **مبروك!** حصلت على بونص ترحيبي بمبلغ: {format_currency(w_bonus)}",
                reply_markup=ReplyKeyboardRemove()
            )

    conn.commit()
    conn.close()

    await update.message.reply_text("✅ تم التحقق من رقم الهاتف بنجاح!", reply_markup=ReplyKeyboardRemove())
    return await check_and_show_main_menu(update, context)

# ----------------- القائمة الرئيسية والتحقق من الاشتراكات -----------------
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
            ch_clean = ch[1:] if ch.startswith("@") else ch
            keyboard.append([InlineKeyboardButton(f"📢 القناة الإجبارية #{idx}", url=f"https://t.me/{ch_clean}")])
        keyboard.append([InlineKeyboardButton("✅ تم التحقق من الاشتراك", callback_data="check_sub")])

        msg = "⚠️ **عليك الاشتراك في القنوات التالية أولاً لاستخدام البوت:**\n"
        if update.message:
            await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.callback_query.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
        return ConversationHandler.END

    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT balance, spins, wayxbet_user FROM users WHERE user_id = ?", (user.id,))
    data = cursor.fetchone()
    conn.close()

    bal = data[0] if data else 0
    spins = data[1] if data else 0
    acc = data[2] if data and data[2] else "غير مرتبط"

    text = (
        f"🙋‍♂️ أهلاً بك عزيزي: **{user.full_name}**\n\n"
        f"💵 **رصيدك الحالي:** {format_currency(bal)}\n"
        f"🎡 **لفات العجلة:** {spins} لفة\n"
        f"🆔 **حساب WayXbet:** `{acc}`\n\n"
        f"اختر من القائمة أدناه الخدمة المطلوبة:"
    )

    keyboard = [
        [InlineKeyboardButton("🎮 إنشاء حساب WayXbet", callback_data="create_acc"), InlineKeyboardButton("💰 إيداع رصيد", callback_data="deposit")],
        [InlineKeyboardButton("💸 سحب الأرباح", callback_data="withdraw"), InlineKeyboardButton("🔄 تحويل من البوت للموقع", callback_data="bot_to_site")],
        [InlineKeyboardButton("🎡 عجلة الحظ VIP", callback_data="open_wheel"), InlineKeyboardButton("🎁 كود هدية", callback_data="gift_code")],
        [InlineKeyboardButton("👥 نظام الإحالة", callback_data="referral"), InlineKeyboardButton("📊 حسابي الشخصي", callback_data="my_account")],
        [InlineKeyboardButton("💬 الدعم الفني", callback_data="support")]
    ]

    if is_admin(user.id):
        keyboard.append([InlineKeyboardButton("⚙️ لوحة الإدارة", callback_data="admin_panel")])

    if update.message:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        
    return ConversationHandler.END

async def check_sub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if is_flooding(query.from_user.id):
        return
    if await check_subscription(query.from_user.id, context):
        await query.message.delete()
        await check_and_show_main_menu(update, context)
    else:
        await query.answer("❌ لم تقم بالاشتراك في جميع القنوات بعد!", show_alert=True)

# ----------------- المعالجات والخيارات الرئيسية -----------------
async def main_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user = query.from_user

    if is_flooding(user.id):
        await query.answer("⚠️ يرجى الانتظار قليلاً وعدم التكرار السريع!")
        return

    await query.answer()

    if data == "main_menu":
        await check_and_show_main_menu(update, context)
    elif data == "my_account":
        conn = sqlite3.connect("wayxbet.db")
        cursor = conn.cursor()
        cursor.execute("SELECT phone, balance, spins, wayxbet_user, created_at FROM users WHERE user_id = ?", (user.id,))
        u = cursor.fetchone()
        conn.close()
        
        msg = (
            f"📊 **تفاصيل حسابك:**\n\n"
            f"🆔 ID: `{user.id}`\n"
            f"📱 الهاتف: `{u[0]}`\n"
            f"💵 الرصيد: {format_currency(u[1])}\n"
            f"🎡 اللفات: {u[2]}\n"
            f"🎯 حساب الموقع: `{u[3] or 'غير مرتبط'}`\n"
            f"📅 تاريخ الانضمام: {u[4]}"
        )
        keyboard = [[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]]
        await query.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "referral":
        bot_username = (await context.bot.get_me()).username
        ref_link = f"https://t.me/{bot_username}?start={user.id}"
        ref_percent = get_setting("ref_bonus_percent") or "5"
        
        conn = sqlite3.connect("wayxbet.db")
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users WHERE referred_by = ?", (user.id,))
        ref_count = cursor.fetchone()[0]
        conn.close()

        msg = (
            f"👥 **نظام الإحالة كسب المال:**\n\n"
            f"شارك الرابط الخاص بك مع أصدقائك واحصل على {ref_percent}% من جميع إيداعاتهم مجاناً + لفة مجانية بـ عجلة الحظ!\n\n"
            f"🔗 **رابط إحالتك:**\n`{ref_link}`\n\n"
            f"📊 **عدد إحالاتك:** {ref_count} شخص"
        )
        keyboard = [[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]]
        await query.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "open_wheel":
        keyboard = [
            [InlineKeyboardButton("🎡 دخول لـ عجلة الحظ VIP", web_app=WebAppInfo(url="https://wayxbet10.com/wheel"))],
            [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]
        ]
        await query.message.edit_text(
            "🎡 **عجلة الحظ VIP:**\n\nاضغط على الزر أدناه لفتح العجلة وتدويرها للحصول على جوائز مالية ورصيد مباشر!",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

# ----------------- مسار إنشاء حساب جديد -----------------
async def start_create_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("🎮 **إنشاء حساب WayXbet جديد:**\n\nيرجى كتابة الاسم أو اسم المستخدم المرغوب به:")
    return CREATE_ACCOUNT_NAME

async def receive_acc_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["acc_name"] = update.message.text.strip()
    await update.message.reply_text("🔑 ممتاز! الآن اكتب كلمة المرور المرغوبة للحساب:")
    return CREATE_ACCOUNT_PASS

async def receive_acc_pass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    acc_name = context.user_data.get("acc_name")
    acc_pass = update.message.text.strip()

    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO account_requests (user_id, wayxbet_user, wayxbet_pass) VALUES (?, ?, ?)", (user.id, acc_name, acc_pass))
    req_id = cursor.lastrowid
    conn.commit()
    conn.close()

    await update.message.reply_text("✅ تم تقديم طلب إنشاء الحساب بنجاح! سيتم مراجعته وتفعيله من قبل الإدارة فوراً.")

    # إشعار الأدمن
    keyboard = [
        [InlineKeyboardButton("✅ موافقة وتفعيل", callback_data=f"adm_acc_app_{req_id}"), InlineKeyboardButton("❌ رفض الطلب", callback_data=f"adm_acc_rej_{req_id}")]
    ]
    for admin_id in [ADMIN_ID]:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=f"🆕 **طلب إنشاء حساب جديد (#{req_id}):**\n\nالمستخدم: {user.full_name} (`{user.id}`)\nاسم الحساب: `{acc_name}`\nكلمة السر: `{acc_pass}`",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
        except:
            pass

    return ConversationHandler.END

# ----------------- مسار الإيداع -----------------
async def start_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    syriatel = get_setting("syriatel_num")
    sham = get_setting("sham_num")
    min_dep = get_setting("min_deposit") or "5000"

    msg = (
        f"💰 **عملية إيداع رصيد جديد:**\n\n"
        f"📱 **سيرياتيل كاش:** `{syriatel}`\n"
        f"🌐 **شام كاش:** `{sham}`\n\n"
        f"⚠️ الحد الأدنى للإيداع: {format_currency(min_dep)}\n\n"
        f"يرجى كتابة المبلغ الذي قمت بتحويله بالليرة السورية القديمة:"
    )
    await query.message.edit_text(msg, parse_mode="Markdown")
    return DEPOSIT_AMOUNT

async def receive_deposit_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("❌ يرجى إدخال مبلغ صحيح بالأرقام فقط!")
        return DEPOSIT_AMOUNT
    
    amount = float(text)
    min_dep = float(get_setting("min_deposit") or 5000)
    if amount < min_dep:
        await update.message.reply_text(f"❌ المبلغ أقل من الحد الأدنى للإيداع ({format_currency(min_dep)})!")
        return DEPOSIT_AMOUNT

    context.user_data["dep_amount"] = amount
    await update.message.reply_text("📄 ممتاز! الآن يرجى إرسال **رقم العملية (رقم الإشعار / ID Transaction)**:")
    return DEPOSIT_TX

async def receive_deposit_tx(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    amount = context.user_data.get("dep_amount")
    tx_id = update.message.text.strip()

    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO transactions (user_id, type, method, amount, tx_id) VALUES (?, 'deposit', 'Syriatel/Sham', ?, ?)", (user.id, amount, tx_id))
    tx_db_id = cursor.lastrowid
    conn.commit()
    conn.close()

    await update.message.reply_text("✅ تم إرسال طلب الإيداع للإدارة للتحقق! سيتم إضافة الرصيد إلى حسابك فور التأكيد.")

    keyboard = [
        [InlineKeyboardButton("✅ تأكيد وموافقة", callback_data=f"adm_dep_app_{tx_db_id}"), InlineKeyboardButton("❌ رفض الإيداع", callback_data=f"adm_dep_rej_{tx_db_id}")]
    ]
    for admin_id in [ADMIN_ID]:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=f"💳 **طلب إيداع جديد (#{tx_db_id}):**\n\nالمستخدم: {user.full_name} (`{user.id}`)\nالمبلغ: {format_currency(amount)}\nرقم العملية: `{tx_id}`",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
        except:
            pass

    return ConversationHandler.END

# ----------------- مسار سحب الأرباح -----------------
async def start_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = query.from_user
    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user.id,))
    bal = cursor.fetchone()[0]
    conn.close()

    min_w = float(get_setting("min_withdraw") or 10000)

    if bal < min_w:
        await query.message.edit_text(f"❌ رصيدك الحالي ({format_currency(bal)}) أقل من الحد الأدنى للسحب ({format_currency(min_w)}).")
        return ConversationHandler.END

    await query.message.edit_text(f"💸 **سحب الأرباح:**\n\nرصيدك المتاح: {format_currency(bal)}\nأدخل المبلغ المراد سحبه بالليرة القديمة:")
    return WITHDRAW_AMOUNT

async def receive_withdraw_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("❌ يرجى إدخال مبلغ صحيح!")
        return WITHDRAW_AMOUNT

    amount = float(text)
    user = update.effective_user

    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user.id,))
    bal = cursor.fetchone()[0]
    conn.close()

    if amount > bal:
        await update.message.reply_text("❌ المبلغ المطلوبة أكبر من رصيدك المتاح!")
        return WITHDRAW_AMOUNT

    context.user_data["w_amount"] = amount
    await update.message.reply_text("📱 أدخل رقم الهاتف أو المحفظة المراد استلام الرصيد عليها:")
    return WITHDRAW_ACC

async def receive_withdraw_acc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    amount = context.user_data.get("w_amount")
    acc_num = update.message.text.strip()

    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    # خصم الرصيد بصفة معلقة
    cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user.id))
    cursor.execute("INSERT INTO transactions (user_id, type, method, amount, account_num) VALUES (?, 'withdraw', 'Transfer', ?, ?)", (user.id, amount, acc_num))
    tx_db_id = cursor.lastrowid
    conn.commit()
    conn.close()

    await update.message.reply_text("✅ تم تقديم طلب السحب بنجاح وخصم الرصيد مؤقتاً لحين التنفيذ!")

    keyboard = [
        [InlineKeyboardButton("✅ موافقة وتحويل", callback_data=f"adm_w_app_{tx_db_id}"), InlineKeyboardButton("❌ رفض وإعادة", callback_data=f"adm_w_rej_{tx_db_id}")]
    ]
    for admin_id in [ADMIN_ID]:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=f"💸 **طلب سحب جديد (#{tx_db_id}):**\n\nالمستخدم: {user.full_name} (`{user.id}`)\nالمبلغ: {format_currency(amount)}\nالحساب/المحفظة: `{acc_num}`",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
        except:
            pass

    return ConversationHandler.END

# ----------------- تحويل من البوت إلى الموقع -----------------
async def start_bot_to_site(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = query.from_user
    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT balance, wayxbet_user FROM users WHERE user_id = ?", (user.id,))
    row = cursor.fetchone()
    conn.close()

    if not row or not row[1]:
        await query.message.edit_text("❌ لم تقم بإنشاء أو ربط حساب WayXbet بعد! أنشئ حسابك أولاً.")
        return ConversationHandler.END

    await query.message.edit_text(f"🔄 **تحويل الرصيد إلى الموقع:**\n\nرصيدك بـ البوت: {format_currency(row[0])}\nحسابك بالموقع: `{row[1]}`\n\nأدخل المبلغ المراد تحويله:")
    return BOT_TO_SITE_AMOUNT

async def receive_bot_to_site_amt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("❌ أدخل رقم صحيح!")
        return BOT_TO_SITE_AMOUNT

    amount = float(text)
    user = update.effective_user

    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT balance, wayxbet_user FROM users WHERE user_id = ?", (user.id,))
    row = cursor.fetchone()

    if amount > row[0]:
        conn.close()
        await update.message.reply_text("❌ رصيدك غير كافي!")
        return BOT_TO_SITE_AMOUNT

    cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user.id))
    cursor.execute("INSERT INTO transactions (user_id, type, method, amount, account_num) VALUES (?, 'bot_to_site', 'SiteTransfer', ?, ?)", (user.id, amount, row[1]))
    tx_id = cursor.lastrowid
    conn.commit()
    conn.close()

    await update.message.reply_text("✅ تم طلب تحويل الرصيد لحسابك بـ الموقع بنجاح!")

    keyboard = [
        [InlineKeyboardButton("✅ تم الشحن بالموقع", callback_data=f"adm_b2s_app_{tx_id}"), InlineKeyboardButton("❌ رفض", callback_data=f"adm_b2s_rej_{tx_id}")]
    ]
    for admin_id in [ADMIN_ID]:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=f"🔄 **طلب تحويل للموقع (#{tx_id}):**\n\nالمستخدم: {user.full_name} (`{user.id}`)\nحساب الموقع: `{row[1]}`\nالمبلغ: {format_currency(amount)}",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
        except:
            pass

    return ConversationHandler.END

# ----------------- كود الهدية والدعم الفني -----------------
async def start_gift_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("🎁 **استخدام كود هدية:**\n\nيرجى إدخال الكود الخاص بك الآن:")
    return GIFT_CODE_INPUT

async def receive_gift_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code_text = update.message.text.strip()
    user = update.effective_user

    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT amount FROM gift_codes WHERE code = ?", (code_text,))
    res = cursor.fetchone()

    if res:
        amt = res[0]
        cursor.execute("DELETE FROM gift_codes WHERE code = ?", (code_text,))
        cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amt, user.id))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"🎉 **مبروك!** تم تفعيل الكود بنجاح وإضافة {format_currency(amt)} لـ رصيدك!")
    else:
        conn.close()
        await update.message.reply_text("❌ هذا الكود غير صحيح أو تم استخدامه سابقاً!")

    return ConversationHandler.END

async def start_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("💬 **الدعم الفني:**\n\nاكتب رسالتك وسنقوم بالرد عليك في أقرب وقت:")
    return SUPPORT_MESSAGE

async def receive_support_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.message.text

    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO support_tickets (user_id, message) VALUES (?, ?)", (user.id, msg))
    tkt_id = cursor.lastrowid
    conn.commit()
    conn.close()

    await update.message.reply_text("✅ تم إرسال رسالتك إلى فريق الدعم الفني بنجاح!")

    keyboard = [[InlineKeyboardButton("💬 رد على الرسالة", callback_data=f"adm_sup_reply_{tkt_id}")]]
    for admin_id in [ADMIN_ID]:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=f"📩 **رسالة دعم جديدة (#{tkt_id}):**\n\nمن: {user.full_name} (`{user.id}`)\nالرسالة:\n{msg}",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
        except:
            pass

    return ConversationHandler.END

# ----------------- لوحة تحكم الأدمن الكاملة -----------------
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user

    if not is_admin(user.id):
        return

    await query.answer()

    conn = sqlite3.connect("wayxbet.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    cursor.execute("SELECT SUM(balance) FROM users")
    total_bal = cursor.fetchone()[0] or 0
    conn.close()

    text = (
        f"⚙️ **لوحة التحكم العليا للإدارة VIP:**\n\n"
        f"👥 إجمالي المستخدمين: {total_users}\n"
        f"💰 إجمالي الأرصدة: {format_currency(total_bal)}\n\n"
        f"اختر الإجراء المطلوب من الأسفل:"
    )

    keyboard = [
        [InlineKeyboardButton("📢 إذاعة عامة", callback_data="adm_broadcast"), InlineKeyboardButton("✉️ رسالة خاصة", callback_data="adm_private")],
        [InlineKeyboardButton("➕ إنشاء كود هدية", callback_data="adm_add_gift"), InlineKeyboardButton("🚫 حظر / إلغاء حظر", callback_data="adm_ban")],
        [InlineKeyboardButton("📢 القنوات الإجبارية", callback_data="adm_channels"), InlineKeyboardButton("⚙️ إعدادات البوت", callback_data="adm_settings")],
        [InlineKeyboardButton("🎡 وزن جوائز العجلة", callback_data="adm_wheel"), InlineKeyboardButton("💵 تعديل رصيد مستخدم", callback_data="adm_chg_bal")],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]
    ]

    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def admin_callback_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user = query.from_user

    if not is_admin(user.id):
        return

    await query.answer()

    if data.startswith("adm_dep_app_"):
        tx_id = int(data.split("_")[3])
        conn = sqlite3.connect("wayxbet.db")
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, amount FROM transactions WHERE id = ? AND status = 'pending'", (tx_id,))
        row = cursor.fetchone()
        if row:
            u_id, amt = row
            cursor.execute("UPDATE transactions SET status = 'approved', admin_name = ? WHERE id = ?", (user.full_name, tx_id))
            cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amt, u_id))
            conn.commit()
            await query.message.edit_text(f"✅ تم تأكيد إيداع المبلغ ({format_currency(amt)}) للمستخدم `{u_id}`")
            try:
                await context.bot.send_message(u_id, f"🎉 **تمت الموافق على إيداعك!** تمت إضافة {format_currency(amt)} لـ رصيدك.")
            except:
                pass
        conn.close()

    elif data.startswith("adm_dep_rej_"):
        tx_id = int(data.split("_")[3])
        conn = sqlite3.connect("wayxbet.db")
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM transactions WHERE id = ?", (tx_id,))
        row = cursor.fetchone()
        if row:
            cursor.execute("UPDATE transactions SET status = 'rejected', admin_name = ? WHERE id = ?", (user.full_name, tx_id))
            conn.commit()
            await query.message.edit_text("❌ تم رفض الإيداع.")
            try:
                await context.bot.send_message(row[0], "❌ تعذر قبول طلب الإيداع الخاص بك. يرجى مراجعة الدعم.")
            except:
                pass
        conn.close()

    elif data.startswith("adm_w_app_"):
        tx_id = int(data.split("_")[3])
        conn = sqlite3.connect("wayxbet.db")
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, amount FROM transactions WHERE id = ?", (tx_id,))
        row = cursor.fetchone()
        if row:
            cursor.execute("UPDATE transactions SET status = 'approved', admin_name = ? WHERE id = ?", (user.full_name, tx_id))
            conn.commit()
            await query.message.edit_text("✅ تم الموافقة على السحب بنجاح.")
            try:
                await context.bot.send_message(row[0], f"🎉 **تمت الموافقة على طلب السحب بقيمة {format_currency(row[1])}!**")
            except:
                pass
        conn.close()

    elif data.startswith("adm_w_rej_"):
        tx_id = int(data.split("_")[3])
        conn = sqlite3.connect("wayxbet.db")
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, amount FROM transactions WHERE id = ?", (tx_id,))
        row = cursor.fetchone()
        if row:
            u_id, amt = row
            # إعادة الرصيد للمستخدم
            cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amt, u_id))
            cursor.execute("UPDATE transactions SET status = 'rejected', admin_name = ? WHERE id = ?", (user.full_name, tx_id))
            conn.commit()
            await query.message.edit_text("❌ تم رفض السحب وإعادة الرصيد للمستخدم.")
            try:
                await context.bot.send_message(u_id, f"❌ تم رفض طلب السحب الخاص بك وتم إعادة مبلغ {format_currency(amt)} لرصيدك.")
            except:
                pass
        conn.close()

    elif data.startswith("adm_acc_app_"):
        req_id = int(data.split("_")[3])
        conn = sqlite3.connect("wayxbet.db")
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, wayxbet_user, wayxbet_pass FROM account_requests WHERE id = ?", (req_id,))
        row = cursor.fetchone()
        if row:
            u_id, w_usr, w_pass = row
            cursor.execute("UPDATE users SET wayxbet_user = ?, wayxbet_pass = ? WHERE user_id = ?", (w_usr, w_pass, u_id))
            cursor.execute("UPDATE account_requests SET status = 'approved' WHERE id = ?", (req_id,))
            conn.commit()
            await query.message.edit_text(f"✅ تم قبول وإنشاء حساب WayXbet لـ `{u_id}`")
            try:
                await context.bot.send_message(u_id, f"🎮 **مبروك! تم تفعيل حسابك بـ WayXbet بنجاح:**\n\nاسم المستخدم: `{w_usr}`\nكلمة السر: `{w_pass}`")
            except:
                pass
        conn.close()

# ----------------- الدالة الرئيسية لتشغيل البوت -----------------
def main():
    app = Application.builder().token(TOKEN).build()

    # محادثة التسجيل والتحقق مع الأمان ضد الرشق
    auth_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            GET_CAPTCHA_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_captcha_question)],
            GET_CAPTCHA_PIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_captcha_pin)],
            GET_CONTACT: [MessageHandler(filters.CONTACT | (filters.TEXT & ~filters.COMMAND), receive_contact)],
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True
    )

    # محادثة إنشاء حساب
    create_acc_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_create_account, pattern="^create_acc$")],
        states={
            CREATE_ACCOUNT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_acc_name)],
            CREATE_ACCOUNT_PASS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_acc_pass)],
        },
        fallbacks=[CommandHandler("start", start)]
    )

    # محادثة الإيداع
    deposit_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_deposit, pattern="^deposit$")],
        states={
            DEPOSIT_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_deposit_amount)],
            DEPOSIT_TX: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_deposit_tx)],
        },
        fallbacks=[CommandHandler("start", start)]
    )

    # محادثة السحب
    withdraw_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_withdraw, pattern="^withdraw$")],
        states={
            WITHDRAW_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_withdraw_amount)],
            WITHDRAW_ACC: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_withdraw_acc)],
        },
        fallbacks=[CommandHandler("start", start)]
    )

    # محادثة تحويل للموقع
    bot_to_site_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_bot_to_site, pattern="^bot_to_site$")],
        states={
            BOT_TO_SITE_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_bot_to_site_amt)],
        },
        fallbacks=[CommandHandler("start", start)]
    )

    # محادثة كود هدية
    gift_code_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_gift_code, pattern="^gift_code$")],
        states={
            GIFT_CODE_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_gift_code)],
        },
        fallbacks=[CommandHandler("start", start)]
    )

    # محادثة الدعم
    support_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_support, pattern="^support$")],
        states={
            SUPPORT_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_support_msg)],
        },
        fallbacks=[CommandHandler("start", start)]
    )

    app.add_handler(auth_handler)
    app.add_handler(create_acc_handler)
    app.add_handler(deposit_handler)
    app.add_handler(withdraw_handler)
    app.add_handler(bot_to_site_handler)
    app.add_handler(gift_code_handler)
    app.add_handler(support_handler)

    app.add_handler(CallbackQueryHandler(check_sub_callback, pattern="^check_sub$"))
    app.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin_panel$"))
    app.add_handler(CallbackQueryHandler(admin_callback_actions, pattern="^adm_"))
    app.add_handler(CallbackQueryHandler(main_callback_handler))

    logger.info("🤖 Bot and WebServer are starting...")
    app.run_polling()

if __name__ == "__main__":
    main()

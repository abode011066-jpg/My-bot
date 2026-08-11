import os
import sys
import logging
import sqlite3
import random
import asyncio
import requests
from datetime import datetime, timedelta
from aiohttp import web
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup,
    KeyboardButton, ReplyKeyboardRemove
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ConversationHandler, ContextTypes, filters
)

# ----------------------------------------------------
# ⚙️ البيانات الأساسية (ضع التوكين والآيدي هنا فقط)
# ----------------------------------------------------
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# ✏️ 1. ضع توكين البوت الخاص بك هنا بين علامات التنصيص
BOT_TOKEN = "8812713556:AAGv3bCjQnGgwSGxiqoX8ipuVTvlNTTiLdk"

# ✏️ 2. ضع معرّف التلجرام الخاص بك (ID) هنا بدون علامات تنصيص
ADMIN_ID = 8984953082  # استبدله بـ ID حسابك

# ----------------------------------------------------
# 🔐 بيانات كاشيرتك (مدمجة ومربوطة بالكامل)
# ----------------------------------------------------
CASHIER_COOKIE = "PHPSESSID_cfc2a618c71d38b723f9059f3f2248a0960a5957e40dfb12fc3b946541c4fb78=0124652f5adc587ec7d464663a971a6c; languageCode=en_GB; language=English%20%28UK%29; __cf_bm=4fpxbbgHGfJvthNsWA2YQViCMjYr9rj3uIkZI08yGfU-1786464026.2105372-1.0.1.1-nQPAiP5ZokVFRqpPX06v8Tl8gOIs5uL2NE5H3SyM0ffZ2TKOpGURTyCiPdcbUbnbBYntSFGHcpSAHikDBlXM51Ggf9hZR4MXIp0Dy.v0UgZhucrR0r6jXgEw.bOOOqNy"
PARENT_ID = "2780167"
PORT = int(os.getenv("PORT", 8080))
CHANNELS = ["@lerafree", "@cashinsher"]

# ----------------------------------------------------
# 🗄️ إدارة قاعدة البيانات (SQLite)
# ----------------------------------------------------
def init_db():
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    
    # جدول المستخدمين
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        full_name TEXT,
        phone TEXT,
        site_username TEXT,
        site_player_id TEXT,
        bot_balance REAL DEFAULT 0.0,
        referred_by INTEGER,
        verified INTEGER DEFAULT 0,
        last_spin TEXT
    )''')
    
    # جدول إعدادات البوت والآدمن
    cursor.execute('''CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')
    
    # جدول الأكواد والمكافآت
    cursor.execute('''CREATE TABLE IF NOT EXISTS gift_codes (
        code TEXT PRIMARY KEY,
        amount REAL,
        uses_left INTEGER
    )''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS gift_claims (
        code TEXT,
        user_id INTEGER,
        PRIMARY KEY (code, user_id)
    )''')

    # جدول المشرفين الفرعيين
    cursor.execute('''CREATE TABLE IF NOT EXISTS admins (
        admin_id INTEGER PRIMARY KEY
    )''')

    # القيم الافتراضية للإعدادات
    defaults = {
        "welcome_bonus": "0",
        "referral_bonus": "0",
        "deposit_bonus_pct": "0",
        "withdraw_commission_pct": "0",
        "maintenance": "0",
        "shamcash_acc": "09xxxxxxxx",
        "syriatel_acc": "09xxxxxxxx"
    }
    for k, v in defaults.items():
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
        
    cursor.execute("INSERT OR IGNORE INTO admins (admin_id) VALUES (?)", (ADMIN_ID,))
    conn.commit()
    conn.close()

def get_setting(key):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key=?", (key,))
    res = cursor.fetchone()
    conn.close()
    return res[0] if res else "0"

def set_setting(key, val):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(val)))
    conn.commit()
    conn.close()

def is_admin(user_id):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT admin_id FROM admins WHERE admin_id=?", (user_id,))
    res = cursor.fetchone()
    conn.close()
    return res is not None or user_id == ADMIN_ID

init_db()

# ----------------------------------------------------
# 🌐 الربط التلقائي مع كاشيرة WayxBet (API)
# ----------------------------------------------------
class WayxBetCashierAPI:
    def __init__(self, cookie):
        self.headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Mobile Safari/537.36",
            "Cookie": cookie,
            "origin": "https://agents.wayxbet.com",
            "referer": "https://agents.wayxbet.com/players/players"
        }

    def register_player(self, username, password):
        url = "https://agents.wayxbet.com/global/api/Player/registerPlayer"
        payload = {
            "player": {
                "login": username,
                "password": password,
                "email": f"{username}@123playr.nsp",
                "parentId": PARENT_ID
            }
        }
        try:
            r = requests.post(url, json=payload, headers=self.headers, timeout=10)
            return r.status_code == 200, r.json() if r.status_code == 200 else r.text
        except Exception as e:
            return False, str(e)

    def deposit(self, player_id, amount):
        url = "https://agents.wayxbet.com/global/api/Player/depositToPlayer"
        payload = {
            "amount": float(amount),
            "comment": "Bot Deposit",
            "currencyCode": "NSP",
            "moneyStatus": 5,
            "playerId": str(player_id)
        }
        try:
            r = requests.post(url, json=payload, headers=self.headers, timeout=10)
            return r.status_code == 200, r.text
        except Exception as e:
            return False, str(e)

    def withdraw(self, player_id, amount):
        url = "https://agents.wayxbet.com/global/api/Player/withdrawFromPlayer"
        payload = {
            "amount": -abs(float(amount)),
            "comment": "Bot Withdrawal",
            "currencyCode": "NSP",
            "moneyStatus": 5,
            "playerId": str(player_id)
        }
        try:
            r = requests.post(url, json=payload, headers=self.headers, timeout=10)
            return r.status_code == 200, r.text
        except Exception as e:
            return False, str(e)

cashier = WayxBetCashierAPI(CASHIER_COOKIE)

# ----------------------------------------------------
# 🤖 الحالات البرمجية للمحادثة
# ----------------------------------------------------
(
    CAPTCHA, PHONE_VERIFY, CREATE_ACC_USER, CREATE_ACC_PASS,
    DEPOSIT_METHOD, DEPOSIT_PROCESS, WITHDRAW_METHOD, WITHDRAW_WALLET, WITHDRAW_AMOUNT,
    BOT_TO_SITE_AMT, REDEEM_GIFT_CODE, SUPPORT_SEND,
    ADMIN_ADD_GIFT, ADMIN_ADD_GIFT_USES, ADMIN_ADD_ADMIN_ID,
    ADMIN_BC_MSG, ADMIN_PRIV_USER, ADMIN_PRIV_MSG, ADMIN_SEARCH_USER,
    ADMIN_SET_SHAM, ADMIN_SET_SYRIATEL, ADMIN_SET_WELCOME, ADMIN_SET_REF,
    ADMIN_SET_DEP_BONUS, ADMIN_SET_WITH_COMM
) = range(25)

# ----------------------------------------------------
# 🛡️ القوائم والتحقق من الاشتراك
# ----------------------------------------------------
async def check_subscriptions(user_id, bot):
    for ch in CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=ch, user_id=user_id)
            if member.status in ['left', 'kicked']:
                return False
        except Exception:
            return False
    return True

def subscription_keyboard():
    keyboard = [
        [InlineKeyboardButton("📢 قناة المبرمج", url="https://t.me/lerafree")],
        [InlineKeyboardButton("📢 قناة البوت", url="https://t.me/cashinsher")],
        [InlineKeyboardButton("✅ تحقق من الاشتراك", callback_data="check_sub")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("🎮 wayxbet (إنشاء/عرض الحساب)", callback_data="menu_wayxbet")],
        [InlineKeyboardButton("💳 شحن رصيد للموقع مباشر", callback_data="menu_deposit"), InlineKeyboardButton("💸 سحب رصيد من الموقع لمحفظتي", callback_data="menu_withdraw")],
        [InlineKeyboardButton("🔄 شحن رصيد من البوت للموقع", callback_data="menu_bot_to_site")],
        [InlineKeyboardButton("🔗 رابط إحالتي", callback_data="menu_referral"), InlineKeyboardButton("🎡 العجلة", callback_data="menu_wheel")],
        [InlineKeyboardButton("🎁 إدخال كود هدية", callback_data="menu_gift")],
        [InlineKeyboardButton("📢 قناة المبرمج", url="https://t.me/lerafree"), InlineKeyboardButton("📢 قناة البوت", url="https://t.me/cashinsher")],
        [InlineKeyboardButton("🌐 صفحتنا على الفيسبوك", url="https://www.facebook.com/share/1DYHkHPhLS/"), InlineKeyboardButton("💬 مراسلة الدعم", callback_data="menu_support")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def send_main_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = sqlite3.connect("bot_database.db")
    c = conn.cursor()
    c.execute("SELECT bot_balance, site_username FROM users WHERE user_id=?", (user.id,))
    row = c.fetchone()
    conn.close()
    
    bot_bal = row[0] if row else 0.0
    site_acc = row[1] if row and row[1] else "غير منشأ بعد"
    
    old_lira = int(bot_bal * 100)
    new_lira = int(bot_bal)

    safe_name = user.first_name.replace("*", "").replace("_", "").replace("`", "")

    text = (
        f"✨ **أهلاً وسهلاً بك في بوت ROZ WAYXBET** ✨\n\n"
        f"👤 **اسم المستخدم:** {safe_name}\n"
        f"🆔 **الأيدي (ID):** `{user.id}`\n"
        f"🎮 **حساب الموقع:** `{site_acc}`\n\n"
        f"💰 **رصيدك في البوت:**\n"
        f"👈 {old_lira} ل س ق | {new_lira} ل س ج\n\n"
        f"🌐 **رابط الموقع الرسمي:**\n"
        f"wayxbet10.com\n\n"
        f"اختر من الأزرار أدناه للبدء:"
    )
    
    if update.callback_query:
        await update.callback_query.message.edit_text(text, parse_mode="Markdown", reply_markup=get_main_menu_keyboard(), disable_web_page_preview=True)
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=get_main_menu_keyboard(), disable_web_page_preview=True)

# ----------------------------------------------------
# 🚀 محرك البداية والتحقق الإجباري
# ----------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if get_setting("maintenance") == "1" and not is_admin(user.id):
        await update.message.reply_text("⚠️ البوت حالياً في وضع الصيانة، يرجى المحاولة لاحقاً.")
        return ConversationHandler.END

    conn = sqlite3.connect("bot_database.db")
    c = conn.cursor()
    c.execute("SELECT user_id, verified FROM users WHERE user_id=?", (user.id,))
    row = c.fetchone()
    
    ref_id = int(context.args[0]) if context.args and context.args[0].isdigit() and int(context.args[0]) != user.id else None

    if not row:
        c.execute("INSERT INTO users (user_id, full_name, referred_by) VALUES (?, ?, ?)", (user.id, user.full_name, ref_id))
        conn.commit()
        
        # إشعار دخول عميل جديد
        await context.bot.send_message(ADMIN_ID, f"🔔 **دخول عميل جديد للبوت:**\n👤 {user.full_name} (`{user.id}`)", parse_mode="Markdown")
        
        # إضافة بونص إحالة للمُحيل إذا وُجد
        if ref_id:
            ref_bonus = float(get_setting("referral_bonus"))
            if ref_bonus > 0:
                c.execute("UPDATE users SET bot_balance = bot_balance + ? WHERE user_id=?", (ref_bonus, ref_id))
                conn.commit()
                try:
                    await context.bot.send_message(ref_id, f"🎉 **انضم عميل جديد عبر رابط إحالتك!**\n💰 تمت إضافة بونص `{ref_bonus}` ل.س ج لرصيدك في البوت.", parse_mode="Markdown")
                except Exception:
                    pass

    conn.close()

    # 1. اختبار الرياضيات (الكابتشا)
    num1, num2 = random.randint(1, 9), random.randint(1, 9)
    context.user_data['captcha_res'] = num1 + num2
    await update.message.reply_text(f"🤖 **اختبار الأمان لمكافحة الروبوتات:**\n\nالرجاء إدخال ناتج جمع السؤال التالي:\n❓ `{num1} + {num2} = ?`", parse_mode="Markdown")
    return CAPTCHA

async def handle_captcha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        ans = int(update.message.text.strip())
        if ans == context.user_data.get('captcha_res'):
            kb = ReplyKeyboardMarkup([[KeyboardButton("📱 مشاركة الرقم السوري للتحقق", request_contact=True)]], resize_keyboard=True, one_time_keyboard=True)
            await update.message.reply_text("✅ إجابة صحيحة!\n\nاضغط على الزر أدناه لمشاركة رقم هاتفك للتحقق من هويتك:", reply_markup=kb)
            return PHONE_VERIFY
        else:
            await update.message.reply_text("❌ إجابة خاطئة! حاول مرة أخرى:")
            return CAPTCHA
    except ValueError:
        await update.message.reply_text("⚠️ يرجى إدخال أرقام فقط!")
        return CAPTCHA

async def handle_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact = update.message.contact
    if contact:
        phone = contact.phone_number
        user = update.effective_user
        
        conn = sqlite3.connect("bot_database.db")
        c = conn.cursor()
        
        # إضافة بونص الترحيب إذا كان مفصلاً
        welcome_bonus = float(get_setting("welcome_bonus"))
        c.execute("UPDATE users SET phone=?, verified=1, bot_balance = bot_balance + ? WHERE user_id=?", (phone, welcome_bonus, user.id))
        conn.commit()
        conn.close()

        await update.message.reply_text("✅ تم التحقق من رقم الهاتف بنجاح!", reply_markup=ReplyKeyboardRemove())

        if not await check_subscriptions(user.id, context.bot):
            await update.message.reply_text("⚠️ يرجى الاشتراك في القنوات التالية أولاً لاستخدام البوت:", reply_markup=subscription_keyboard())
            return ConversationHandler.END
        else:
            await send_main_dashboard(update, context)
            return ConversationHandler.END
    else:
        await update.message.reply_text("⚠️ يجب الضغط على زر مشاركة الرقم للرد!")
        return PHONE_VERIFY

async def check_sub_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if await check_subscriptions(query.from_user.id, context.bot):
        await send_main_dashboard(update, context)
    else:
        await query.answer("❌ لم تقم بالاشتراك في جميع القنوات بعد!", show_alert=True)

# ----------------------------------------------------
# 🎮 إنشاء حساب WayxBet أوتوماتيكياً
# ----------------------------------------------------
async def wayxbet_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    conn = sqlite3.connect("bot_database.db")
    c = conn.cursor()
    c.execute("SELECT site_username FROM users WHERE user_id=?", (user.id,))
    row = c.fetchone()
    conn.close()

    if row and row[0]:
        await query.message.edit_text(f"🎮 **بيانات حسابك المسجل على الموقع:**\n\n👤 اسم المستخدم: `{row[0]}`\n\nيمكنك الشحن والسحب مباشرة!", reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")
        return ConversationHandler.END
    else:
        await query.message.reply_text("📝 **إنشاء حساب جديد في الموقع:**\n\nأدخل اسم المستخدم المطلوب (أحرف إنجليزية وأرقام فقط):")
        return CREATE_ACC_USER

async def process_create_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_user = update.message.text.strip().replace(" ", "")
    context.user_data['req_username'] = raw_user
    await update.message.reply_text("🔑 أدخل كلمة المرور المطلوبة للحساب:")
    return CREATE_ACC_PASS

async def process_create_pass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_user = context.user_data.get('req_username')
    raw_pass = update.message.text.strip()
    
    # إضافة السابقة واللاحقة المطلوبة
    final_username = f"Aa{raw_user}@123"
    final_password = raw_pass

    await update.message.reply_text("⏳ جاري إنشاء الحساب في الكاشيرة تلقائياً...")

    success, res = cashier.register_player(final_username, final_password)
    
    if success:
        player_id = res.get("player", {}).get("id", final_username) if isinstance(res, dict) else final_username
        
        conn = sqlite3.connect("bot_database.db")
        c = conn.cursor()
        c.execute("UPDATE users SET site_username=?, site_player_id=? WHERE user_id=?", (final_username, str(player_id), update.effective_user.id))
        conn.commit()
        conn.close()

        msg = (
            f"🎉 **تم إنشاء حسابك بنجاح في الكاشيرة والموقع!**\n\n"
            f"👤 **اسم الحساب:** `{final_username}`\n"
            f"🔑 **كلمة المرور:** `{final_password}`\n\n"
            f"تم حفظ البيانات أوتوماتيكياً في البوت."
        )
        await update.message.reply_text(msg, parse_mode="Markdown")
        await send_main_dashboard(update, context)
        return ConversationHandler.END
    else:
        await update.message.reply_text(f"❌ فشل إنشاء الحساب.\nالسبب: {res}\n\nحاول باختيار اسم مستخدم آخر.")
        return CREATE_ACC_USER

# ----------------------------------------------------
# 💳 شحن وسحب أوتوماتيكي
# ----------------------------------------------------
async def deposit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("شام كاش 🟢", callback_data="dep_sham"), InlineKeyboardButton("سيريتل كاش 🔴", callback_data="dep_syriatel")],
        [InlineKeyboardButton("🔙 إلغاء", callback_data="back_main")]
    ])
    await query.message.edit_text("💳 **اختر طريقة الشحن المباشر للموقع:**", reply_markup=kb, parse_mode="Markdown")
    return DEPOSIT_METHOD

async def deposit_method_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    method = "شام كاش" if query.data == "dep_sham" else "سيريتل كاش"
    acc_number = get_setting("shamcash_acc") if query.data == "dep_sham" else get_setting("syriatel_acc")
    context.user_data['dep_method'] = method
    
    await query.message.edit_text(
        f"📌 **الشحن عبر {method}:**\n"
        f"📱 رقم المحفظة: `{acc_number}`\n\n"
        f"قم بالتحويل ثم أرسل رقم العملية أو صورة الإشعار مع ذكر المبلغ المرسل بالليرة السورية:",
        parse_mode="Markdown"
    )
    return DEPOSIT_PROCESS

async def deposit_process_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = sqlite3.connect("bot_database.db")
    c = conn.cursor()
    c.execute("SELECT site_username, phone, site_player_id FROM users WHERE user_id=?", (user.id,))
    u_data = c.fetchone()
    conn.close()

    site_acc = u_data[0] if u_data and u_data[0] else "غير منشأ"
    phone = u_data[1] if u_data else "غير معروف"
    player_id = u_data[2] if u_data and u_data[2] else site_acc

    text_content = update.message.text or update.message.caption or "صورة إشعار تحويل"
    
    # محاولة استخراج الرقم إن وجد في النص
    amt = 0
    for word in text_content.split():
        if word.isdigit():
            amt = int(word)
            break

    old_lira = amt * 100
    new_lira = amt

    msg_admin = (
        f"📥 **طلب شحن رصيد جديد:**\n\n"
        f"👤 العميل: {user.full_name} (`{user.id}`)\n"
        f"🎮 حساب الموقع: `{site_acc}`\n"
        f"📱 الهاتف: `{phone}`\n"
        f"💳 الطريقة: {context.user_data.get('dep_method')}\n"
        f"💰 المبلغ التقديري: {old_lira} ل.س ق | {new_lira} ل.س ج\n"
        f"📝 التفاصيل: {text_content}"
    )
    
    # زر Approval يحمل البيانات المطلوبة للشحن
    cb_data_app = f"appdep_{user.id}_{new_lira}_{player_id}"
    cb_data_rej = f"rejdep_{user.id}"
    
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ موافقة وشحن أوتوماتيكي", callback_data=cb_data_app)], [InlineKeyboardButton("❌ رفض", callback_data=cb_data_rej)]])

    if update.message.photo:
        await context.bot.send_photo(ADMIN_ID, photo=update.message.photo[-1].file_id, caption=msg_admin, reply_markup=kb, parse_mode="Markdown")
    else:
        await context.bot.send_message(ADMIN_ID, text=msg_admin, reply_markup=kb, parse_mode="Markdown")

    await update.message.reply_text("✅ تم إرسال طلب الشحن بنجاح، جاري التدقيق من قبل الإدارة...")
    await send_main_dashboard(update, context)
    return ConversationHandler.END

# ---- السحب Direct Withdrawal ----
async def withdraw_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    conn = sqlite3.connect("bot_database.db")
    c = conn.cursor()
    c.execute("SELECT site_username, site_player_id FROM users WHERE user_id=?", (query.from_user.id,))
    row = c.fetchone()
    conn.close()

    if not row or not row[0]:
        await query.answer("❌ يجب عليك إنشاء حساب في الموقع أولاً قبل السحب!", show_alert=True)
        return ConversationHandler.END

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("شام كاش 🟢", callback_data="with_sham"), InlineKeyboardButton("سيريتل كاش 🔴", callback_data="with_syriatel")],
        [InlineKeyboardButton("🔙 إلغاء", callback_data="back_main")]
    ])
    await query.message.edit_text("💸 **اختر طريقة السحب من الموقع لمحفظتك:**", reply_markup=kb, parse_mode="Markdown")
    return WITHDRAW_METHOD

async def withdraw_method_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['with_method'] = "شام كاش" if query.data == "with_sham" else "سيريتل كاش"
    await query.message.edit_text("📱 أدخل رقم محفظتك التي ترغب برغبتك باستلام الرصيد عليها:")
    return WITHDRAW_WALLET

async def withdraw_wallet_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['with_wallet'] = update.message.text.strip()
    await update.message.reply_text("💰 أدخل المبلغ المراد سحبه بالليرة الجديدة:")
    return WITHDRAW_AMOUNT

async def withdraw_process_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amt = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("⚠️ أدخل مبلغ صحيح بالأرقام!")
        return WITHDRAW_AMOUNT

    user = update.effective_user
    conn = sqlite3.connect("bot_database.db")
    c = conn.cursor()
    c.execute("SELECT site_username, phone, site_player_id FROM users WHERE user_id=?", (user.id,))
    u_data = c.fetchone()
    conn.close()

    site_acc = u_data[0]
    phone = u_data[1]
    player_id = u_data[2] if u_data[2] else site_acc

    # خصم عمولة السحب إن وجدت
    comm_pct = float(get_setting("withdraw_commission_pct"))
    final_payout = amt * (1 - (comm_pct / 100))

    msg_admin = (
        f"📤 **طلب سحب رصيد جديد:**\n\n"
        f"👤 العميل: {user.full_name} (`{user.id}`)\n"
        f"🎮 حساب الموقع: `{site_acc}`\n"
        f"📱 المحفظة والمستلم: `{context.user_data.get('with_wallet')}` ({context.user_data.get('with_method')})\n"
        f"💰 المبلغ المطلوب خصمه: `{amt}` ل.س ج\n"
        f"💸 المبلغ الواجب تحويله للعميل: `{final_payout}` ل.س ج (بعد عمولة {comm_pct}%)\n"
    )

    cb_app = f"appwith_{user.id}_{amt}_{player_id}"
    cb_rej = f"rejwith_{user.id}"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ موافقة وسحب أوتوماتيكي من الكاشيرة", callback_data=cb_app)], [InlineKeyboardButton("❌ رفض", callback_data=cb_rej)]])

    await context.bot.send_message(ADMIN_ID, text=msg_admin, reply_markup=kb, parse_mode="Markdown")
    await update.message.reply_text("✅ تم تقديم طلب السحب للإدارة وسيتم التنفيذ فوراً عند المراجعة.")
    await send_main_dashboard(update, context)
    return ConversationHandler.END

# ----------------------------------------------------
# 🔄 تحويل رصيد البوت إلى حساب الموقع أوتوماتيكياً
# ----------------------------------------------------
async def bot_to_site_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    conn = sqlite3.connect("bot_database.db")
    c = conn.cursor()
    c.execute("SELECT bot_balance, site_username, site_player_id FROM users WHERE user_id=?", (user.id,))
    row = c.fetchone()
    conn.close()

    if not row or not row[1]:
        await query.answer("❌ يجب عليك إنشاء حساب بالموقع أولاً!", show_alert=True)
        return ConversationHandler.END

    bot_bal = row[0]
    if bot_bal <= 0:
        await query.answer("❌ ليس لديك رصيد في البوت لتحويله!", show_alert=True)
        return ConversationHandler.END

    await query.message.edit_text(
        f"🔄 **تحويل الرصيد من البوت إلى الموقع:**\n\n"
        f"💰 رصيدك في البوت: `{bot_bal}` ل.س ج\n"
        f"🎮 الحساب المستهدف: `{row[1]}`\n\n"
        f"أدخل المبلغ المراد تحويله لشحن حسابك في الموقع تلقائياً:",
        parse_mode="Markdown"
    )
    return BOT_TO_SITE_AMT

async def process_bot_to_site(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amt = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("⚠️ يرجى كتابة مبلغ صحيح!")
        return BOT_TO_SITE_AMT

    user = update.effective_user
    conn = sqlite3.connect("bot_database.db")
    c = conn.cursor()
    c.execute("SELECT bot_balance, site_username, site_player_id FROM users WHERE user_id=?", (user.id,))
    row = c.fetchone()

    if not row or row[0] < amt or amt <= 0:
        await update.message.reply_text("❌ رصيدك في البوت غير كافٍ!")
        conn.close()
        return BOT_TO_SITE_AMT

    player_id = row[2] if row[2] else row[1]

    # تنفيذ خصم رصيد البوت وشحنه فوراً بالكاشيرة
    c.execute("UPDATE users SET bot_balance = bot_balance - ? WHERE user_id=?", (amt, user.id))
    conn.commit()
    conn.close()

    await update.message.reply_text("⏳ جاري تحويل الرصيد وشحن حسابك تلقائياً في الكاشيرة...")

    success, res = cashier.deposit(player_id, amt)
    if success:
        await update.message.reply_text(f"🎉 **تم شحن حسابك `{row[1]}` بمبلغ `{amt}` ل.س أوتوماتيكياً!**", parse_mode="Markdown")
        await context.bot.send_message(ADMIN_ID, f"🔔 **عملية تحويل رصيد بوت للموقع:**\n👤 العميل: {user.full_name}\n🎮 الحساب: `{row[1]}`\n💰 المبلغ: `{amt}` ل.س", parse_mode="Markdown")
    else:
        # استرجاع الرصيد في حال الفشل
        conn = sqlite3.connect("bot_database.db")
        c = conn.cursor()
        c.execute("UPDATE users SET bot_balance = bot_balance + ? WHERE user_id=?", (amt, user.id))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"❌ تعذر الشحن عبر الكاشيرة: {res}\nتم إعادة الرصيد إلى محفظتك في البوت.")

    await send_main_dashboard(update, context)
    return ConversationHandler.END

# ----------------------------------------------------
# 🎡 العجلة، الإحالة، كود الهدية، والدعم
# ----------------------------------------------------
async def wheel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    conn = sqlite3.connect("bot_database.db")
    c = conn.cursor()
    c.execute("SELECT last_spin FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()

    now = datetime.now()
    if row and row[0]:
        last_spin = datetime.fromisoformat(row[0])
        if now - last_spin < timedelta(hours=24):
            rem = timedelta(hours=24) - (now - last_spin)
            hours, remainder = divmod(rem.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            await query.answer(f"⏳ يمكنك تدوير العجلة بعد: {hours} ساعة و {minutes} دقيقة", show_alert=True)
            conn.close()
            return

    win_amount = random.choice([5, 10, 15, 20, 50])
    c.execute("UPDATE users SET bot_balance = bot_balance + ?, last_spin=? WHERE user_id=?", (win_amount, now.isoformat(), user_id))
    conn.commit()
    conn.close()

    await query.message.edit_text(f"🎡 **مبروك! قامت العجلة بالدوران وفزت بـ:**\n🎁 `{win_amount}` ل.س ج تم إضافتها لرصيدك في البوت!", reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")

async def referral_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bot_username = (await context.bot.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start={query.from_user.id}"
    ref_bonus = get_setting("referral_bonus")

    text = (
        f"🔗 **رابط الإحالة الخاص بك:**\n"
        f"`{ref_link}`\n\n"
        f"💰 **مكافأة الإحالة:** `{ref_bonus}` ل.س ج لكل عميل ينضم عن طريق رابطك!"
    )
    await query.message.edit_text(text, parse_mode="Markdown", reply_markup=get_main_menu_keyboard())

# --- كود الهدية ---
async def gift_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("🎁 **أدخل كود الهدية الذي حصلت عليه:**")
    return REDEEM_GIFT_CODE

async def process_gift_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code_input = update.message.text.strip()
    user_id = update.effective_user.id

    conn = sqlite3.connect("bot_database.db")
    c = conn.cursor()
    c.execute("SELECT amount, uses_left FROM gift_codes WHERE code=?", (code_input,))
    gift = c.fetchone()

    if not gift:
        await update.message.reply_text("❌ هذا الكود غير موجود أو غير صالح!")
        conn.close()
        return REDEEM_GIFT_CODE

    c.execute("SELECT * FROM gift_claims WHERE code=? AND user_id=?", (code_input, user_id))
    claimed = c.fetchone()

    if claimed:
        await update.message.reply_text("⚠️ لقد قمت باستخدام هذا الكود سابقاً!")
        conn.close()
        return ConversationHandler.END

    if gift[1] <= 0:
        await update.message.reply_text("❌ انتهى عدد استخدامات هذا الكود!")
        conn.close()
        return ConversationHandler.END

    amt = gift[0]
    c.execute("UPDATE gift_codes SET uses_left = uses_left - 1 WHERE code=?", (code_input,))
    c.execute("INSERT INTO gift_claims (code, user_id) VALUES (?, ?)", (code_input, user_id))
    c.execute("UPDATE users SET bot_balance = bot_balance + ? WHERE user_id=?", (amt, user_id))
    conn.commit()
    conn.close()

    await update.message.reply_text(f"🎉 **مبروك! تم إدخال الكود بنجاح واستلام `{amt}` ل.س ج في البوت!**", parse_mode="Markdown")
    await send_main_dashboard(update, context)
    return ConversationHandler.END

# --- الدعم والمراسلة ---
async def support_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("💬 **أرسل رسالتك أو استفسارك الآن (يمكنك إرسال نص أو صورة):**")
    return SUPPORT_SEND

async def process_support_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg_text = update.message.text or update.message.caption or "صورة بدون نص"
    
    admin_msg = f"💬 **رسالة دعم جديدة:**\n👤 العميل: {user.full_name} (`{user.id}`)\n📝 الرسالة: {msg_text}"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("💬 الرد على العميل", callback_data=f"reply_sup_{user.id}")]])

    if update.message.photo:
        await context.bot.send_photo(ADMIN_ID, photo=update.message.photo[-1].file_id, caption=admin_msg, reply_markup=kb, parse_mode="Markdown")
    else:
        await context.bot.send_message(ADMIN_ID, text=admin_msg, reply_markup=kb, parse_mode="Markdown")

    await update.message.reply_text("✅ تم إرسال رسالتك لفريق الدعم، سيتم الرد عليك قريباً!")
    await send_main_dashboard(update, context)
    return ConversationHandler.END

# ----------------------------------------------------
# 👑 لوحة تحكم الآدمن (Admin Panel)
# ----------------------------------------------------
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎁 إنشاء كود هدية", callback_data="adm_gift"), InlineKeyboardButton("➕ إضافة أدمن", callback_data="adm_add_admin")],
        [InlineKeyboardButton("📢 رسالة جماعية", callback_data="adm_bc"), InlineKeyboardButton("📩 رسالة خاصة لعميل", callback_data="adm_priv")],
        [InlineKeyboardButton("⚙️ تعديل البونصات والأرباح", callback_data="adm_settings")],
        [InlineKeyboardButton("📱 تعديل أرقام المحافظ", callback_data="adm_accs")],
        [InlineKeyboardButton("🛠️ وضع الصيانة (تفعيل/إلغاء)", callback_data="adm_maint")],
        [InlineKeyboardButton("🔍 البحث عن لاعب", callback_data="adm_search"), InlineKeyboardButton("📊 الإحصائيات والأرصدة", callback_data="adm_stats")]
    ])
    text = "👑 **مرحباً بك في لوحة تحكم المدير:**\nاختر الخيار المطلوب للتحكم بالبوت:"
    if update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")

# --- تنفيذ الموافقات والرفض للشحن والسحب من قبل الآدمن ---
async def admin_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # 1. موافقة على الشحن -> تنفيذ شحن في الكاشيرة تلقائياً
    if data.startswith("appdep_"):
        _, uid, amt, pid = data.split("_")
        uid, amt = int(uid), float(amt)

        # إضافة بونص زيادات الشحن إن وجد
        dep_bonus = float(get_setting("deposit_bonus_pct"))
        final_amt = amt * (1 + (dep_bonus / 100))

        success, res = cashier.deposit(pid, final_amt)
        if success:
            await query.message.edit_reply_markup(reply_markup=None)
            await query.message.reply_text(f"✅ تم الشحن بنجاح للاعب `{pid}` بمبلغ `{final_amt}` ل.س!", parse_mode="Markdown")
            await context.bot.send_message(uid, f"🎉 **تمت الموافقة على طلب الشحن!**\n💰 تم إضافة `{final_amt}` ل.س لحسابك بالموقع أوتوماتيكياً.", parse_mode="Markdown")
        else:
            await query.message.reply_text(f"❌ فشل الشحن تلقائياً عبر API: {res}")

    elif data.startswith("rejdep_"):
        uid = int(data.split("_")[1])
        await query.message.edit_reply_markup(reply_markup=None)
        await query.message.reply_text(f"❌ تم رفض الطلب للعميل `{uid}`")
        await context.bot.send_message(uid, "❌ **عذراً، تم رفض طلب الشحن الخاص بك.**")

    # 2. موافقة على السحب -> خصم أوتوماتيكي من الكاشيرة
    elif data.startswith("appwith_"):
        _, uid, amt, pid = data.split("_")
        uid, amt = int(uid), float(amt)

        success, res = cashier.withdraw(pid, amt)
        if success:
            await query.message.edit_reply_markup(reply_markup=None)
            await query.message.reply_text(f"✅ تم السحب بنجاح من حساب اللاعب `{pid}` بمبلغ `{amt}` ل.س!", parse_mode="Markdown")
            await context.bot.send_message(uid, f"🎉 **تمت الموافقة على طلب السحب وتم الخصم من حسابك بنجاح!**", parse_mode="Markdown")
        else:
            await query.message.reply_text(f"❌ فشل السحب أوتوماتيكياً عبر API: {res}")

    elif data.startswith("rejwith_"):
        uid = int(data.split("_")[1])
        await query.message.edit_reply_markup(reply_markup=None)
        await query.message.reply_text(f"❌ تم رفض طلب السحب للعميل `{uid}`")
        await context.bot.send_message(uid, "❌ **عذراً، تم رفض طلب السحب الخاص بك.**")

# --- معالجة أزرار إعدادات الآدمن ---
async def admin_settings_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "adm_maint":
        curr = get_setting("maintenance")
        new_val = "1" if curr == "0" else "0"
        set_setting("maintenance", new_val)
        status_txt = "تم تفعيل وضع الصيانة 🛠️" if new_val == "1" else "تم إلغاء وضع الصيانة ✅"
        await query.message.reply_text(f"📢 {status_txt}")
        
    elif query.data == "adm_stats":
        conn = sqlite3.connect("bot_database.db")
        c = conn.cursor()
        c.execute("SELECT COUNT(*), SUM(bot_balance) FROM users")
        u_count, total_bal = c.fetchone()
        c.execute("SELECT COUNT(*) FROM users WHERE site_username IS NOT NULL")
        accs_count = c.fetchone()[0]
        conn.close()

        msg = (
            f"📊 **إحصائيات البوت والموقع:**\n\n"
            f"👥 عدد مستخدمي البوت: `{u_count}`\n"
            f"🎮 عدد الحسابات المنشأة على الموقع: `{accs_count}`\n"
            f"💰 مجموع أرصدة اللاعبين في البوت: `{total_bal or 0}` ل.س ج"
        )
        await query.message.reply_text(msg, parse_mode="Markdown")

# ----------------------------------------------------
# 🌐 السيرفر الوهمي لـ Render (PORT)
# ----------------------------------------------------
async def handle_ping(request):
    return web.Response(text="ROZ WAYXBET Bot Active!")

async def start_dummy_server():
    app = web.Application()
    app.router.add_get('/', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()

async def post_init_task(application: Application):
    asyncio.create_task(start_dummy_server())

# ----------------------------------------------------
# 🎯 التشغيل وإدارة المحادثات
# ----------------------------------------------------
def main():
    application = Application.builder().token(BOT_TOKEN).post_init(post_init_task).build()

    # محادثة البداية والكابتشا
    start_conv = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            CAPTCHA: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_captcha)],
            PHONE_VERIFY: [MessageHandler(filters.CONTACT, handle_phone)]
        },
        fallbacks=[]
    )

    # محادثة إنشاء حساب WayxBet
    create_acc_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(wayxbet_handler, pattern="^menu_wayxbet$")],
        states={
            CREATE_ACC_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_create_user)],
            CREATE_ACC_PASS: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_create_pass)]
        },
        fallbacks=[]
    )

    # محادثة الشحن
    deposit_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(deposit_start, pattern="^menu_deposit$")],
        states={
            DEPOSIT_METHOD: [CallbackQueryHandler(deposit_method_choice, pattern="^dep_")],
            DEPOSIT_PROCESS: [MessageHandler(filters.ALL & ~filters.COMMAND, deposit_process_finish)]
        },
        fallbacks=[]
    )

    # محادثة السحب
    withdraw_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(withdraw_start, pattern="^menu_withdraw$")],
        states={
            WITHDRAW_METHOD: [CallbackQueryHandler(withdraw_method_choice, pattern="^with_")],
            WITHDRAW_WALLET: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_wallet_choice)],
            WITHDRAW_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_process_finish)]
        },
        fallbacks=[]
    )

    # محادثة شحن رصيد البوت للموقع
    bot_to_site_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(bot_to_site_start, pattern="^menu_bot_to_site$")],
        states={BOT_TO_SITE_AMT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_bot_to_site)]},
        fallbacks=[]
    )

    # محادثة كود الهدية
    gift_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(gift_start, pattern="^menu_gift$")],
        states={REDEEM_GIFT_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_gift_code)]},
        fallbacks=[]
    )

    # محادثة الدعم
    support_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(support_start, pattern="^menu_support$")],
        states={SUPPORT_SEND: [MessageHandler(filters.ALL & ~filters.COMMAND, process_support_msg)]},
        fallbacks=[]
    )

    # إضافة المحادثات للبوت
    application.add_handler(start_conv)
    application.add_handler(create_acc_conv)
    application.add_handler(deposit_conv)
    application.add_handler(withdraw_conv)
    application.add_handler(bot_to_site_conv)
    application.add_handler(gift_conv)
    application.add_handler(support_conv)

    # إضافة الأوامر والاستجابات السريعة
    application.add_handler(CommandHandler('admin', admin_panel))
    application.add_handler(CallbackQueryHandler(check_sub_button, pattern="^check_sub$"))
    application.add_handler(CallbackQueryHandler(referral_handler, pattern="^menu_referral$"))
    application.add_handler(CallbackQueryHandler(wheel_handler, pattern="^menu_wheel$"))
    application.add_handler(CallbackQueryHandler(admin_action_callback, pattern="^(appdep_|rejdep_|appwith_|rejwith_)"))
    application.add_handler(CallbackQueryHandler(admin_settings_handler, pattern="^adm_"))

    print("🤖 بوت ROZ WAYXBET يعمل بنجاح وبشكل أوتوماتيكي بالكامل...")
    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()

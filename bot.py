import os
import sqlite3
import logging
from datetime import datetime, timedelta
from collections import deque, defaultdict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)
from groq import Groq

# ==================== الإعدادات الأساسية ====================
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN", "7999371850:AAFzy0dsBUuWyZ1Md_Kgj2EMH-N090KbIM0")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
MAIN_ADMIN_ID = 8577656131

logging.basicConfig(level=logging.INFO)

# إعداد عميل Groq الذكي
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# ذاكرة مؤقتة لرسائل الكروبات والقصص التفاعلية
group_message_logs = defaultdict(lambda: deque(maxlen=10))
story_sessions = defaultdict(lambda: {"active": False, "lines": [], "users": []})

# حالات المحادثات المتعددة (Conversation Handler States)
(
    WAITING_CONFESSION_TEXT,
    WAITING_GRANT_GROUP_ID,
    WAITING_GRANT_DAYS,
    WAITING_ADD_ADMIN_ID,
    WAITING_GROUP_MSG_TARGET,
    WAITING_GROUP_MSG_TEXT,
    WAITING_FORCE_CHANNEL,
) = range(7)

# ==================== قاعدة البيانات (SQLite) ====================
def init_db():
    conn = sqlite3.connect("bot_system.db")
    cursor = conn.cursor()
    # جدول المجموعات المرخصة
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            group_id INTEGER PRIMARY KEY,
            group_title TEXT,
            expire_at TEXT
        )
    """)
    # جدول الاعترافات المجهولة
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS confessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            user_name TEXT,
            group_id INTEGER,
            group_title TEXT,
            text TEXT,
            created_at TEXT
        )
    """)
    # جدول الأدمنية الإضافيين
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY,
            added_at TEXT
        )
    """)
    # جدول الإعدادات العامة (قناة الاشتراك الإجباري وغيرها)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ==================== وظائف قاعدة البيانات والصلاحيات ====================
def is_admin(user_id: int) -> bool:
    if user_id == MAIN_ADMIN_ID:
        return True
    conn = sqlite3.connect("bot_system.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM admins WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row is not None

def add_admin_db(user_id: int):
    conn = sqlite3.connect("bot_system.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO admins (user_id, added_at) VALUES (?, ?)", 
                   (user_id, datetime.now().strftime("%Y-%m-%d %H:%M")))
    conn.commit()
    conn.close()

def get_all_admins():
    conn = sqlite3.connect("bot_system.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, added_at FROM admins")
    rows = cursor.fetchall()
    conn.close()
    return rows

def set_setting(key: str, value: str):
    conn = sqlite3.connect("bot_system.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def get_setting(key: str) -> str:
    conn = sqlite3.connect("bot_system.db")
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else ""

def is_group_active(group_id: int) -> bool:
    conn = sqlite3.connect("bot_system.db")
    cursor = conn.cursor()
    cursor.execute("SELECT expire_at FROM groups WHERE group_id = ?", (group_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        expire_date = datetime.fromisoformat(row[0])
        if expire_date > datetime.now():
            return True
    return False

def add_or_update_group(group_id: int, title: str, days: int):
    conn = sqlite3.connect("bot_system.db")
    cursor = conn.cursor()
    cursor.execute("SELECT expire_at FROM groups WHERE group_id = ?", (group_id,))
    row = cursor.fetchone()
    
    now = datetime.now()
    if row and datetime.fromisoformat(row[0]) > now:
        new_expire = datetime.fromisoformat(row[0]) + timedelta(days=days)
    else:
        new_expire = now + timedelta(days=days)
        
    cursor.execute("""
        INSERT OR REPLACE INTO groups (group_id, group_title, expire_at)
        VALUES (?, ?, ?)
    """, (group_id, title, new_expire.isoformat()))
    conn.commit()
    conn.close()
    return new_expire.strftime("%Y-%m-%d %H:%M")

def get_active_groups():
    conn = sqlite3.connect("bot_system.db")
    cursor = conn.cursor()
    cursor.execute("SELECT group_id, group_title, expire_at FROM groups")
    rows = cursor.fetchall()
    conn.close()
    active = []
    now = datetime.now()
    for gid, title, exp in rows:
        if datetime.fromisoformat(exp) > now:
            active.append((gid, title, exp))
    return active

def log_confession(user_id: int, user_name: str, group_id: int, group_title: str, text: str):
    conn = sqlite3.connect("bot_system.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO confessions (user_id, user_name, group_id, group_title, text, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, user_name, group_id, group_title, text, datetime.now().strftime("%Y-%m-%d %H:%M")))
    conn.commit()
    conn.close()

def get_confessions_log():
    conn = sqlite3.connect("bot_system.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, user_name, group_title, text, created_at FROM confessions ORDER BY id DESC LIMIT 15")
    rows = cursor.fetchall()
    conn.close()
    return rows

# ==================== التحقق من الاشتراك الإجباري ====================
async def check_force_sub(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    channel = get_setting("force_channel")
    if not channel:
        return True
    try:
        member = await context.bot.get_chat_member(chat_id=channel, user_id=user_id)
        if member.status in ["creator", "administrator", "member"]:
            return True
    except Exception:
        pass
    return False

# ==================== توليد الذكاء الاصطناعي باللهجة السورية (Groq) ====================
async def generate_syrian_ai(prompt: str) -> str:
    if not groq_client:
        return "لك يا خاي مفتاح الـ AI (Groq) مو متفعل، حاكي المطور!"
    
    system_instruction = (
        "أنت بوت تلجرام سوري مهضوم وساخر ومرح جداً. تحدث حصراً باللهجة السورية الشامية العفوية "
        "(استخدم كلمات مثل: يا زلمة، شو هالحكي، ولي على بعضي، شو هالقصة، العما بقلبك، لك يا خاي، هبيدات، الخ). "
        "اجعل الردود طريفة وقوية بدون إساءة حقيقية أو شتم."
    )
    
    try:
        completion = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=1024,
        )
        return completion.choices[0].message.content
    except Exception as e:
        logging.error(f"Groq AI Error: {e}")
        return "العما! صرلي مشكلة بالدماغ الاصطناعي، جرب بعد شوي يا زلمة!"

# ==================== الأوامر العامة والتحقق من الاشتراك ====================
UNAUTHORIZED_MSG = "⚠️ هذا البوت مدفوع وتحتاج تفعيله بالكروب.\nللاشتراك والتفعيل كلم المطور: @syabd0"

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    # فحص الاشتراك الإجباري
    if not await check_force_sub(user.id, context):
        channel = get_setting("force_channel")
        btn = InlineKeyboardMarkup([[InlineKeyboardButton("📢 اشترك بالقناة هنا", url=f"https://t.me/{channel.replace('@', '')}")]])
        await update.message.reply_text(f"⚠️ لاستخدام البوت يرجى الاشتراك بقناة البوت أولاً:\n{channel}", reply_markup=btn)
        return

    if chat.type == "private":
        keyboard = [
            [InlineKeyboardButton("🕵️ إرسال اعتراف مجهول", callback_data="start_confession")]
        ]
        if is_admin(user.id):
            keyboard.append([InlineKeyboardButton("⚙️ لوحة الإدارة", callback_data="admin_panel")])
            
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"أهلاً فيك يا {user.first_name} بـ بوت التسلاية والضحك السوري! 🇸🇾✨\n\n"
            "من هون فيك ترسل اعترافات مجهولة للكروبات المفعلة بدون ما حدا يعرفك!\n"
            "أما بالكروبات، البوت بيحكم بين الأعضاء بـ /قاضي وبيقصف جبهات بـ /قصف وبيعمل قصص تفاعلية بـ /قصة!",
            reply_markup=reply_markup
        )
    else:
        if not is_group_active(chat.id):
            await update.message.reply_text(UNAUTHORIZED_MSG)
        else:
            await update.message.reply_text("لك أهلاً بالشباب! البوت شغال ومفعل بهالكروب جاهز للتسلاية! 🎉")

# ==================== الميزة 1: قاضي الجروب والقصف ====================
async def track_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type in ["group", "supergroup"]:
        if update.message and update.message.text:
            user = update.effective_user.first_name
            text = update.message.text
            group_message_logs[update.effective_chat.id].append(f"{user}: {text}")

async def judge_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not is_group_active(chat_id):
        await update.message.reply_text(UNAUTHORIZED_MSG)
        return

    logs = list(group_message_logs[chat_id])
    if len(logs) < 2:
        await update.message.reply_text("لك حكولكم كلمتين بالكروب الأول لحتى أقدر احكم بيناتكم! ما في حكي لسه!")
        return

    chat_history = "\n".join(logs)
    prompt = f"اقرأ المحادثة الأخيرة بين أعضاء الجروب واحكم بيناتهم بأسلوب سوري ساخر ومضحك، حدد مين صاحب الهبدة الأكبر ومين وجهة نظره أهضم:\n{chat_history}"
    
    await update.message.reply_text("⚖️ عم اقرأ الهبدات والنعرات بالكروب... شوية وقت لإصدر الحكم!")
    verdict = await generate_syrian_ai(prompt)
    await update.message.reply_text(f"👨‍⚖️ **حكم قاضي الجروب:**\n\n{verdict}", parse_mode="Markdown")

async def roast_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not is_group_active(chat_id):
        await update.message.reply_text(UNAUTHORIZED_MSG)
        return

    target = ""
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user.first_name
    elif context.args:
        target = " ".join(context.args)
    else:
        await update.message.reply_text("ولك منشن حدن أو رد على رسالته لحتى نقصف جبهته! /قصف @username")
        return

    prompt = f"اعمل قصف جبهة سوري ساخر ومهضوم ومضحك بدون زعل للشخص هاد: ({target})"
    roast_text = await generate_syrian_ai(prompt)
    await update.message.reply_text(f"🔥 **قصف جبهة مباشر لـ {target}:**\n\n{roast_text}")

# ==================== الميزة 2: قصة الجروب المجنونة ====================
async def story_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not is_group_active(chat_id):
        await update.message.reply_text(UNAUTHORIZED_MSG)
        return

    session = story_sessions[chat_id]
    
    if not session["active"]:
        session["active"] = True
        session["lines"] = []
        session["users"] = []
        
        start_prompt = "اكتب بداية قصة مجنونة ومضحكة جداً بفقرة واحدة وبسطر واحد فقط باللهجة السورية لتبدأ بها لعبة الجروب."
        intro = await generate_syrian_ai(start_prompt)
        
        await update.message.reply_text(
            f"📖 **بدأت قصة الجروب المجنونة!** 🎭\n\n"
            f"البداية: {intro}\n\n"
            f"👇 المطلوب: 5 أعضاء يضيفوا أسطر للقصة! لتضيف سطر اكتب الأمر:\n`/سطر نص السطر تبعك`",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(f"القصة شغال حالياً! شاركنا سطر بأمر: `/سطر النص`\nوصلنا {len(session['lines'])}/5 أسطر.")

async def add_story_line(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not is_group_active(chat_id):
        return

    session = story_sessions[chat_id]
    if not session["active"]:
        await update.message.reply_text("ما في قصة شغال حالياً! اكتب `/قصة` لنبلش قصة جديدة!")
        return

    line_text = " ".join(context.args)
    if not line_text:
        await update.message.reply_text("اكتب السطر تبعك بعد الأمر! مثال:\n`/سطر وفجأة طلع بوجههم غوار الطوشة`")
        return

    user = update.effective_user.first_name
    session["lines"].append(f"{user}: {line_text}")
    count = len(session["lines"])

    if count < 5:
        await update.message.reply_text(f"✅ تسجل سطر {user}! صرنا ({count}/5) أسطر. مين كمان؟")
    else:
        await update.message.reply_text("🎬 كملوا הـ 5 أسطر! عم اجمع الهبدات لحتى الذكاء الاصطناعي يركبلكم النهاية الدرامية...")
        combined_lines = "\n".join(session["lines"])
        prompt = f"جمّع هالسطور الخمسة يلي كتبوها الشباب واعمل منها تكملة قصة درامية ومجنونة وساخرة جداً باللهجة السورية:\n{combined_lines}"
        
        final_story = await generate_syrian_ai(prompt)
        await update.message.reply_text(f"🔥 **النتيجة النهائية لقصة الجروب المجنونة:**\n\n{final_story}")
        session["active"] = False

# ==================== الميزة 3: الاعترافات المجهولة ====================
async def start_confession_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    active_groups = get_active_groups()
    if not active_groups:
        await query.edit_message_text("للأسف ما في ولا كروب مفعل حالياً لإرسال الاعترافات له!")
        return

    keyboard = []
    for gid, title, _ in active_groups:
        keyboard.append([InlineKeyboardButton(f"👥 {title}", callback_data=f"sendconf_{gid}")])

    await query.edit_message_text(
        "اختر الكروب يلي بدك ترسل إله الاعتراف المجهول:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def confession_group_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    group_id = int(query.data.split("_")[1])
    context.user_data["confess_group_id"] = group_id
    
    active_groups = dict((g[0], g[1]) for g in get_active_groups())
    context.user_data["confess_group_title"] = active_groups.get(group_id, "الكروب")

    await query.edit_message_text("✍️ اكتب هلق رسالة الاعتراف أو الخبر الطريف وارسله بهي المحادثة (سرّك ببير ومحدا بالكروب بيعرفك):")
    return WAITING_CONFESSION_TEXT

async def receive_confession_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text
    group_id = context.user_data.get("confess_group_id")
    group_title = context.user_data.get("confess_group_title")

    log_confession(user.id, user.first_name, group_id, group_title, text)

    try:
        confess_msg = f"🕵️ **اعتراف مجهول جديد وصل للكروب:**\n\n« {text} »"
        await context.bot.send_message(chat_id=group_id, text=confess_msg, parse_mode="Markdown")
        
        await context.bot.send_poll(
            chat_id=group_id,
            question="مين بتتوقعوا صاحب هالاعتراف المجهول؟ 🧐",
            options=["واحد من المشرفين 👮‍♂️", "عضو قديم ومختفي 👻", "أهضم واحد بالكروب 😂", "أنا شاك بشخص بس ما رح احكي 🤫"],
            is_anonymous=True
        )
        await update.message.reply_text("✅ تم إرسال اعترافك للكروب بنجاح وبسرية تامة بالكروب!")
    except Exception as e:
        await update.message.reply_text("❌ حدث خطأ أثناء إرسال الاعتراف، تأكد أن البوت موجود بالكروب وصلاحياته كاملة!")

    return ConversationHandler.END

# ==================== لوحة الإدارة الكاملة (Admin Panel) ====================
async def admin_panel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return

    text = "🛠 **لوحة إدارة البوت الكاملة (المدير/الأدمن):**\nاختر من الأزرار أدناه للتحكم الشامل:"
    keyboard = [
        [InlineKeyboardButton("➕ تفعيل كروب جديد", callback_data="admin_grant"), InlineKeyboardButton("📋 الكروبات المفعلة", callback_data="admin_list_groups")],
        [InlineKeyboardButton("📢 رسالة خاصة لكروب", callback_data="admin_msg_group_start"), InlineKeyboardButton("🚪 مغادرة كروب", callback_data="admin_leave_start")],
        [InlineKeyboardButton("👑 إدارة الأدمنية", callback_data="admin_manage_admins"), InlineKeyboardButton("📢 الاشتراك الإجباري", callback_data="admin_force_sub_start")],
        [InlineKeyboardButton("🕵️ سجل الاعترافات", callback_data="admin_confessions_log"), InlineKeyboardButton("📜 جميع الأوامر والدليل", callback_data="admin_help_guide")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

async def admin_buttons_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    if not is_admin(query.from_user.id):
        return

    if data == "admin_panel":
        await admin_panel_handler(update, context)

    elif data == "admin_list_groups":
        groups = get_active_groups()
        if not groups:
            msg = "لا يوجد كروبات مفعلة حالياً."
        else:
            msg = "📋 **سجل الكروبات المفعلة حالياً:**\n\n"
            for gid, title, exp in groups:
                msg += f"• **الاسم:** {title}\n  **ID:** `{gid}`\n  **ينتهي بـ:** {exp}\n\n"
        
        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "admin_confessions_log":
        logs = get_confessions_log()
        if not logs:
            msg = "لا يوجد اعترافات مسجلة بعد."
        else:
            msg = "🕵️ **سجل الاعترافات (يكشف المرسل للمدير فقط):**\n\n"
            for uid, uname, gtitle, text, dt in logs:
                msg += f"👤 **المرسل:** {uname} (`{uid}`)\n👥 **الكروب:** {gtitle}\n💬 **النص:** {text}\n🕒 **التاريخ:** {dt}\n--------------------\n"
        
        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "admin_help_guide":
        guide = (
            "📜 **دليل الشامل لجميع الميزات والأوامر:**\n\n"
            "1️⃣ **قاضي الجروب وقصف الجبهات:**\n"
            "• `/قاضي`: يقرأ أحدث 10 رسائل بالكروب ويصدر حكماً ساخراً بين الأعضاء.\n"
            "• `/قصف` أو `/قصف @username`: توليد قصف جبهة مباشر وسريع.\n\n"
            "2️⃣ **الاعترافات والرسائل المجهولة:**\n"
            "• يرسل العضو رسالة بالخاص للبوت، ويختار الكروب ليتم نشرها مجهولة المصدر مع استطلاع رأي.\n"
            "• يستطيع الأدمن معرفة هوية المرسل الحقيقية من زر 'سجل الاعترافات'.\n\n"
            "3️⃣ **قصة الجروب المجنونة:**\n"
            "• `/قصة`: لبدء القصة.\n"
            "• `/سطر [النص]`: إضافة سطر للقصة (عند اكتمال 5 أسطر يدمجها الذكاء الاصطناعي بنهاية درامية).\n\n"
            "4️⃣ **الترخيص والاشتراك:**\n"
            "• يتوقف البوت تلقائياً عن العمل في الكروب فور انتهاء مدة الأيام المحددة له."
        )
        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]]
        await query.edit_message_text(guide, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "admin_manage_admins":
        admins = get_all_admins()
        msg = f"👑 **إدارة الأدمنية:**\n\nالمدير الأساسي: `{MAIN_ADMIN_ID}`\n\n**الأدمنية الإضافيين:**\n"
        for uid, dt in admins:
            msg += f"• `{uid}` - أضيف بتاريخ: {dt}\n"
        
        keyboard = [
            [InlineKeyboardButton("➕ إضافة أدمن جديد", callback_data="admin_add_admin")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]
        ]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("admin_leave_grp_"):
        gid = int(data.split("_")[3])
        try:
            await context.bot.leave_chat(gid)
            await query.edit_message_text(f"✅ تم مغادرة الكروب `{gid}` بنجاح!")
        except Exception as e:
            await query.edit_message_text(f"❌ تعذر مغادرة الكروب: {e}")

# ==================== معالجات لوحة الإدارة المتفاعلة (Conversations) ====================
# 1. منح وتفعيل كروب
async def admin_grant_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("أرسل الآن الـ ID الخاص بالكروب (مثال: `-100123456789`):")
    return WAITING_GRANT_GROUP_ID

async def admin_receive_group_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        gid = int(update.message.text.strip())
        context.user_data["grant_gid"] = gid
        await update.message.reply_text("أدخل الآن عدد أيام التفعيل (مثال: `30`):")
        return WAITING_GRANT_DAYS
    except ValueError:
        await update.message.reply_text("❌ ID غير صالح، يرجى إرسال رقم صحيح.")
        return WAITING_GRANT_GROUP_ID

async def admin_receive_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        days = int(update.message.text.strip())
        gid = context.user_data.get("grant_gid")
        try:
            chat = await context.bot.get_chat(gid)
            title = chat.title
        except Exception:
            title = f"كروب {gid}"

        exp_date = add_or_update_group(gid, title, days)
        await update.message.reply_text(
            f"✅ **تمت عملية منح الكروب بنجاح!**\n\n• الكروب: {title}\n• ID: `{gid}`\n• ينتهي بتاريخ: {exp_date}",
            parse_mode="Markdown"
        )
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("❌ يرجى إدخال عدد أيام صحيح كـ رقم.")
        return WAITING_GRANT_DAYS

# 2. إضافة أدمن جديد
async def admin_add_admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("أرسل الآن الآيدي (ID) الخاص بالأدمن الجديد:")
    return WAITING_ADD_ADMIN_ID

async def admin_receive_admin_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        aid = int(update.message.text.strip())
        add_admin_db(aid)
        await update.message.reply_text(f"✅ تم إضافة المستخدم `{aid}` كـ أدمن جديد بنجاح بنسبة كامل الصلاحيات!")
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("❌ يرجى إدخال ID صحيح كـ رقم.")
        return WAITING_ADD_ADMIN_ID

# 3. مغادرة كروب
async def admin_leave_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    groups = get_active_groups()
    if not groups:
        await query.edit_message_text("لا يوجد كروبات مفعلة لمغادرتها.")
        return

    keyboard = []
    for gid, title, _ in groups:
        keyboard.append([InlineKeyboardButton(f"🚪 مغادرة: {title}", callback_data=f"admin_leave_grp_{gid}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")])

    await query.edit_message_text("اختر الكروب الذي تريد أن يغادره البوت:", reply_markup=InlineKeyboardMarkup(keyboard))

# 4. إرسال رسالة خاصة لكروب
async def admin_msg_group_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    groups = get_active_groups()
    if not groups:
        await query.edit_message_text("لا يوجد كروبات مفعلة لإرسال رسالة إليها.")
        return

    keyboard = []
    for gid, title, _ in groups:
        keyboard.append([InlineKeyboardButton(f"📢 {title}", callback_data=f"admin_select_msggrp_{gid}")])

    await query.edit_message_text("اختر الكروب الذي تريد إرسال رسالة خاصة له:", reply_markup=InlineKeyboardMarkup(keyboard))
    return WAITING_GROUP_MSG_TARGET

async def admin_msg_group_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    gid = int(query.data.split("_")[3])
    context.user_data["msg_target_gid"] = gid
    await query.edit_message_text("اكتب الآن الرسالة التي تريد إرسالها للكروب:")
    return WAITING_GROUP_MSG_TEXT

async def admin_receive_group_msg_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    gid = context.user_data.get("msg_target_gid")
    text = update.message.text
    try:
        await context.bot.send_message(chat_id=gid, text=f"📢 **رسالة من إدارات البوت:**\n\n{text}", parse_mode="Markdown")
        await update.message.reply_text("✅ تم إرسال الرسالة إلى الكروب بنجاح!")
    except Exception as e:
        await update.message.reply_text(f"❌ فشل إرسال الرسالة: {e}")
    return ConversationHandler.END

# 5. قناة الاشتراك الإجباري
async def admin_force_sub_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    curr = get_setting("force_channel") or "غير محددة"
    await query.edit_message_text(f"القناة الحالية: {curr}\n\nأرسل الآن معرّف القناة الجديدة (مثال: `@mychannel`):")
    return WAITING_FORCE_CHANNEL

async def admin_receive_force_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ch = update.message.text.strip()
    set_setting("force_channel", ch)
    await update.message.reply_text(f"✅ تم ضبط قناة الاشتراك الإجباري إلى: {ch}")
    return ConversationHandler.END

# ==================== التشغيل الرئيسي ====================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # محادثة تفعيل الكروبات
    grant_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_grant_start, pattern="^admin_grant$")],
        states={
            WAITING_GRANT_GROUP_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_receive_group_id)],
            WAITING_GRANT_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_receive_days)]
        },
        fallbacks=[]
    )

    # محادثة إضافة أدمن
    add_admin_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_add_admin_start, pattern="^admin_add_admin$")],
        states={
            WAITING_ADD_ADMIN_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_receive_admin_id)]
        },
        fallbacks=[]
    )

    # محادثة الاعترافات
    confess_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(confession_group_selected, pattern="^sendconf_")],
        states={
            WAITING_CONFESSION_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_confession_text)]
        },
        fallbacks=[]
    )

    # محادثة إرسال رسالة لكروب
    msg_group_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_msg_group_start, pattern="^admin_msg_group_start$")],
        states={
            WAITING_GROUP_MSG_TARGET: [CallbackQueryHandler(admin_msg_group_selected, pattern="^admin_select_msggrp_")],
            WAITING_GROUP_MSG_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_receive_group_msg_text)]
        },
        fallbacks=[]
    )

    # محادثة قناة الاشتراك الإجباري
    force_sub_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_force_sub_start, pattern="^admin_force_sub_start$")],
        states={
            WAITING_FORCE_CHANNEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_receive_force_channel)]
        },
        fallbacks=[]
    )

    # تسجيل الأوامر العامة
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("admin", admin_panel_handler))
    app.add_handler(CommandHandler("قاضي", judge_handler))
    app.add_handler(CommandHandler("قصف", roast_handler))
    app.add_handler(CommandHandler("قصة", story_handler))
    app.add_handler(CommandHandler("سطر", add_story_line))

    # تسجيل محادثات لوحة الإدارة والخدمات
    app.add_handler(grant_conv)
    app.add_handler(add_admin_conv)
    app.add_handler(confess_conv)
    app.add_handler(msg_group_conv)
    app.add_handler(force_sub_conv)

    app.add_handler(CallbackQueryHandler(start_confession_callback, pattern="^start_confession$"))
    app.add_handler(CallbackQueryHandler(admin_leave_start, pattern="^admin_leave_start$"))
    app.add_handler(CallbackQueryHandler(admin_buttons_callback, pattern="^admin_"))

    # تسجيل معالج تعقب الرسائل للكروبات
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, track_messages))

    print("🚀 البوت يعمل الآن بنجاح...")
    app.run_polling()

if __name__ == "__main__":
    main()

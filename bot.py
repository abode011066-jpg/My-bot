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
ADMIN_ID = 8577656131

logging.basicConfig(level=logging.INFO)

# إعداد عميل Groq الذكي
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# ذاكرة مؤقتة لرسائل الكروبات (لأجل ميزة القاضي) والقصص التفاعلية
group_message_logs = defaultdict(lambda: deque(maxlen=10))
story_sessions = defaultdict(lambda: {"active": False, "lines": [], "users": []})

# حالات المحادثات الخاصة بالاعترافات والترخيص
WAITING_CONFESSION_GROUP, WAITING_CONFESSION_TEXT, WAITING_GRANT_GROUP_ID, WAITING_GRANT_DAYS = range(4)

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
    # جدول الاعترافات المجهولة (لأجل لوحة الإدارة)
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
    conn.commit()
    conn.close()

init_db()

# ==================== وظائف مساعدة لقاعدة البيانات ====================
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

    if chat.type == "private":
        keyboard = [
            [InlineKeyboardButton("🕵️ إرسال اعتراف مجهول", callback_data="start_confession")]
        ]
        if user.id == ADMIN_ID:
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

# ==================== الميزة 3: الاعترافات المجهولة (مع لوحة التحكم) ====================
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
    if user_id != ADMIN_ID:
        return

    text = "🛠 **لوحة إدارة البوت الكاملة (المدير):**\nاختر من الأزرار أدناه للتحكم:"
    keyboard = [
        [InlineKeyboardButton("➕ تفعيل كروب جديد", callback_data="admin_grant")],
        [InlineKeyboardButton("📋 الكروبات المفعلة", callback_data="admin_list_groups")],
        [InlineKeyboardButton("🕵️ سجل الاعترافات المجهولة", callback_data="admin_confessions_log")],
        [InlineKeyboardButton("📖 دليل استخدام الميزات", callback_data="admin_help_guide")]
    ]
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def admin_buttons_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    if data == "admin_panel":
        await admin_panel_handler(update, context)

    elif data == "admin_list_groups":
        groups = get_active_groups()
        if not groups:
            msg = "لا يوجد كروبات مفعلة حالياً."
        else:
            msg = "📋 **الكروبات المفعلة حالياً:**\n\n"
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
            "📖 **دليل ميزات البوت وكيفية استخدامه:**\n\n"
            "1️⃣ **قاضي الجروب وقصف الجبهات:**\n"
            "• `/قاضي`: يقرأ آخر 10 رسائل ويصدر حكماً ساخراً بين الأعضاء.\n"
            "• `/قصف @username`: يولد قصف جبهة كوميدي للمستخدم.\n\n"
            "2️⃣ **الاعترافات المجهولة:**\n"
            "• يدخل العضو للبوت بالخاص، يضغط زر إرسال اعتراف، يختار الكروب ويكتب النص. يتم نشره بالكروب مجاناً وبشكل مجهول مع استطلاع رأي، بينما يظهر اسم المرسل للمدير في اللوحة.\n\n"
            "3️⃣ **قصة الجروب المجنونة:**\n"
            "• `/قصة`: يبدأ لعبة القصة التفاعلية.\n"
            "• `/سطر [النص]`: يضيف العضو سطراً للقصة، وبعد 5 مشاركات يدمجها الذكاء الاصطناعي بنهاية درامية."
        )
        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]]
        await query.edit_message_text(guide, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ==================== معالجة تفعيل الكروبات من الإدارة ====================
async def admin_grant_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("أرسل الآن الـ ID الخاص بالكروب (مثال: `-100123456789`):\n\n*(يمكنك الحصول على ID الكروب عبر توجيه أي رسالة منه للبوت)*")
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
            f"✅ **تمت العملية بنجاح!**\n\n"
            f"• الكروب: {title}\n"
            f"• ID: `{gid}`\n"
            f"• تاريخ الانتهاء: {exp_date}",
            parse_mode="Markdown"
        )
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("❌ يرجى إدخال عدد أيام صحيح كـ رقم.")
        return WAITING_GRANT_DAYS

# ==================== التشغيل الرئيسي ====================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    grant_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_grant_start, pattern="^admin_grant$")],
        states={
            WAITING_GRANT_GROUP_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_receive_group_id)],
            WAITING_GRANT_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_receive_days)]
        },
        fallbacks=[]
    )

    confess_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(confession_group_selected, pattern="^sendconf_")],
        states={
            WAITING_CONFESSION_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_confession_text)]
        },
        fallbacks=[]
    )

    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("admin", admin_panel_handler))
    app.add_handler(CommandHandler("قاضي", judge_handler))
    app.add_handler(CommandHandler("قصف", roast_handler))
    app.add_handler(CommandHandler("قصة", story_handler))
    app.add_handler(CommandHandler("سطر", add_story_line))

    app.add_handler(grant_conv)
    app.add_handler(confess_conv)
    app.add_handler(CallbackQueryHandler(start_confession_callback, pattern="^start_confession$"))
    app.add_handler(CallbackQueryHandler(admin_buttons_callback, pattern="^admin_"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, track_messages))

    print("🚀 البوت يعمل الآن بنجاح مع Groq...")
    app.run_polling()

if __name__ == "__main__":
    main()

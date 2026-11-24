import os
import csv
import time
import sqlite3
import threading
import random
import string

import telebot
from telebot import types

# =========================================================
# CONFIGURATION
# =========================================================
# Set BOT_TOKEN as an environment variable before starting.
BOT_TOKEN = "1780288571:wwwDHj5JBYtarcgsuR9ZyTV-tJ0VOEoCq_u"
ADMIN_ID = 1780285990
CHANNEL = "@zellenn"
NEGOTIATOR = "@monk888"
COOLDOWN = 30
MAX_PHOTOS = 10
DB = "bot.db"

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN is not set. Set the new token from @BotFather "
        "in the BOT_TOKEN environment variable."
    )

bot = telebot.TeleBot(BOT_TOKEN, threaded=True)
db_lock = threading.RLock()
db = sqlite3.connect(DB, check_same_thread=False)
db.row_factory = sqlite3.Row

# =========================================================
# DATABASE
# =========================================================
with db_lock:
    db.executescript("""
    CREATE TABLE IF NOT EXISTS payouts(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE,
        user_id INTEGER,
        chat_id INTEGER,
        username TEXT,
        target TEXT,
        ads_count INTEGER DEFAULT 0,
        reward TEXT,
        photos TEXT DEFAULT '',
        status TEXT DEFAULT 'new',
        hidden INTEGER DEFAULT 0,
        created INTEGER
    );

    CREATE TABLE IF NOT EXISTS questions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE,
        user_id INTEGER,
        chat_id INTEGER,
        username TEXT,
        text TEXT,
        answer TEXT DEFAULT '',
        status TEXT DEFAULT 'new',
        hidden INTEGER DEFAULT 0,
        created INTEGER
    );

    CREATE TABLE IF NOT EXISTS banned(
        user_id INTEGER PRIMARY KEY,
        ts INTEGER
    );

    CREATE TABLE IF NOT EXISTS settings(
        key TEXT PRIMARY KEY,
        value TEXT
    );
    """)
    db.commit()


def q(sql, args=(), one=False):
    with db_lock:
        cur = db.execute(sql, args)
        rows = cur.fetchall()
    return (rows[0] if rows else None) if one else rows


def x(sql, args=()):
    with db_lock:
        db.execute(sql, args)
        db.commit()


if not q("SELECT value FROM settings WHERE key='notify'", one=True):
    x("INSERT OR IGNORE INTO settings(key,value) VALUES('notify','1')")


# =========================================================
# CONSTANTS / HELPERS
# =========================================================
STATUS = {
    "new": "🆕 Новая",
    "in_work": "🔧 В работе",
    "paid": "✅ Выплачено",
    "rejected": "❌ Отклонена",
    "closed": "🔒 Закрыта",
}
QSTATUS = {
    "new": "🆕 Без ответа",
    "answered": "✅ Отвечен",
    "closed": "🔒 Закрыт",
}

states = {}
cooldown = {}


def is_admin(user_id):
    return user_id == ADMIN_ID


def is_banned(user_id):
    return q(
        "SELECT user_id FROM banned WHERE user_id=?",
        (user_id,),
        one=True
    ) is not None


def notify_on():
    row = q(
        "SELECT value FROM settings WHERE key='notify'",
        one=True
    )
    return bool(row and row["value"] == "1")


def gen_code(prefix="P"):
    chars = string.ascii_uppercase + string.digits
    table = "payouts" if prefix == "P" else "questions"
    for _ in range(100):
        code = f"{prefix}-" + "".join(
            random.choices(chars, k=4)
        )
        if not q(f"SELECT 1 FROM {table} WHERE code=?", (code,), one=True):
            return code
    return f"{prefix}-{int(time.time())}"


def calc_reward(ads):
    if ads <= 2:
        return "1 мишка 🧸"
    if ads <= 5:
        return "2 мишки 🧸🧸"
    if ads <= 10:
        return "5 мишек 🧸🧸🧸🧸🧸"
    if ads <= 20:
        return "1 NFT 🖼"
    return f"Договор с {NEGOTIATOR} 💬"


def fmt_payout(t):
    photos = t["photos"] or ""
    count = len([p for p in photos.split(",") if p])
    created = time.strftime(
        "%d.%m.%Y %H:%M",
        time.localtime(t["created"] or time.time())
    )
    return (
        f"💰 Заявка {t['code']}\n"
        f"Статус: {STATUS.get(t['status'], t['status'])}\n\n"
        f"👤 Пользователь: @{t['username'] or '—'}\n"
        f"🆔 ID: {t['user_id']}\n"
        f"📢 Аккаунт/канал для выплаты: {t['target']}\n"
        f"📊 Количество реклам: {t['ads_count']}\n"
        f"🎁 Награда: {t['reward']}\n"
        f"📸 Скриншотов: {count}\n\n"
        f"🕐 Создана: {created}"
    )


def fmt_user_payout(t):
    created = time.strftime(
        "%d.%m.%Y %H:%M",
        time.localtime(t["created"] or time.time())
    )
    return (
        f"💰 Заявка {t['code']}\n"
        f"Статус: {STATUS.get(t['status'], t['status'])}\n\n"
        f"📢 Аккаунт/канал: {t['target']}\n"
        f"📊 Реклам: {t['ads_count']}\n"
        f"🎁 Награда: {t['reward']}\n"
        f"🕐 Создана: {created}"
    )


def fmt_question(r):
    answer = f"\n\n✅ Ответ администрации:\n{r['answer']}" if r["answer"] else ""
    return (
        f"💬 Вопрос {r['code']}\n"
        f"Статус: {QSTATUS.get(r['status'], r['status'])}\n\n"
        f"👤 @{r['username'] or '—'} (ID: {r['user_id']})\n"
        f"📝 {r['text']}{answer}"
    )


# =========================================================
# KEYBOARDS
# =========================================================
def main_kb():
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton(
            "💰 Подать заявку на выплату",
            callback_data="p:new"
        ),
        types.InlineKeyboardButton(
            "💬 Задать вопрос",
            callback_data="q:new"
        ),
        types.InlineKeyboardButton(
            "📋 Мои заявки",
            callback_data="my:payouts"
        ),
        types.InlineKeyboardButton(
            "📨 Мои вопросы",
            callback_data="my:questions"
        )
    )
    return kb


def cancel_kb():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("❌ Отменить", callback_data="cancel"))
    return kb


def photos_done_kb():
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton(
            "✅ Отправить заявку",
            callback_data="photos_done"
        ),
        types.InlineKeyboardButton(
            "❌ Отменить",
            callback_data="cancel"
        )
    )
    return kb


def admin_menu_kb():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("📂 Открытые", callback_data="adm:open"),
        types.InlineKeyboardButton("🔒 Закрытые", callback_data="adm:closed")
    )
    kb.add(
        types.InlineKeyboardButton("📋 Все заявки", callback_data="adm:all"),
        types.InlineKeyboardButton("💬 Вопросы", callback_data="adm:questions")
    )
    kb.add(
        types.InlineKeyboardButton("📊 Статистика", callback_data="adm:stats"),
        types.InlineKeyboardButton("🚫 Баны", callback_data="adm:bans")
    )
    label = "🔔 Уведомления: ВКЛ" if notify_on() else "🔕 Уведомления: ВЫКЛ"
    kb.add(types.InlineKeyboardButton(label, callback_data="adm:notify"))
    kb.add(
        types.InlineKeyboardButton("📢 Рассылка", callback_data="adm:bc"),
        types.InlineKeyboardButton("📤 CSV", callback_data="adm:csv")
    )
    return kb


def payout_list_kb(rows, back="adm:menu"):
    kb = types.InlineKeyboardMarkup(row_width=1)
    for r in rows:
        label = (
            f"{r['code']} {STATUS.get(r['status'], '')} — "
            f"{r['reward'] or 'без награды'}"
        )
        kb.add(
            types.InlineKeyboardButton(
                label[:60],
                callback_data=f"pv:{r['code']}"
            )
        )
    kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data=back))
    return kb


def question_list_kb(rows):
    kb = types.InlineKeyboardMarkup(row_width=1)
    for r in rows:
        label = f"{r['code']} {QSTATUS.get(r['status'], '')} — @{r['username'] or '—'}"
        kb.add(
            types.InlineKeyboardButton(
                label[:60],
                callback_data=f"qv:{r['code']}"
            )
        )
    kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="adm:menu"))
    return kb


def payout_card_kb(code, is_closed=False):
    kb = types.InlineKeyboardMarkup(row_width=2)
    if is_closed:
        kb.add(
            types.InlineKeyboardButton(
                "🔓 Открыть заново",
                callback_data=f"rc:{code}"
            )
        )
    else:
        kb.add(
            types.InlineKeyboardButton(
                "✅ Принять",
                callback_data=f"pa:{code}"
            ),
            types.InlineKeyboardButton(
                "❌ Отклонить",
                callback_data=f"pd:{code}"
            )
        )
    kb.add(
        types.InlineKeyboardButton(
            "⬅️ Вернуться к списку",
            callback_data="adm:open"
        )
    )
    return kb


def user_payout_kb(code):
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton(
            "🔒 Закрыть заявку",
            callback_data=f"upc:{code}"
        ),
        types.InlineKeyboardButton(
            "👁 Убрать из списка",
            callback_data=f"uph:{code}"
        )
    )
    return kb


def question_card_kb(code):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("💬 Ответить", callback_data=f"qr:{code}"),
        types.InlineKeyboardButton("🔒 Закрыть", callback_data=f"qc:{code}")
    )
    kb.add(types.InlineKeyboardButton("⬅️ К списку", callback_data="adm:questions"))
    return kb


# =========================================================
# MESSAGE SENDING
# =========================================================
def send_admin_payout(chat_id, payout):
    """Send screenshots as an album, then send the action card."""
    photo_ids = [
        item for item in (payout["photos"] or "").split(",") if item
    ]

    if photo_ids:
        try:
            media = [
                types.InputMediaPhoto(file_id)
                for file_id in photo_ids[:MAX_PHOTOS]
            ]
            bot.send_media_group(chat_id, media)
        except Exception as exc:
            print("[PHOTO ALBUM ERROR]", exc)
            # Fallback: send photos individually if album sending fails.
            for file_id in photo_ids[:MAX_PHOTOS]:
                try:
                    bot.send_photo(chat_id, file_id)
                except Exception as photo_exc:
                    print("[PHOTO ERROR]", photo_exc)

    bot.send_message(
        chat_id,
        fmt_payout(payout),
        reply_markup=payout_card_kb(
            payout["code"],
            payout["status"] == "closed"
        )
    )


def safe_notify_user(chat_id, text):
    try:
        bot.send_message(chat_id, text)
        return True
    except Exception as exc:
        print("[USER NOTIFICATION ERROR]", exc)
        return False


# =========================================================
# COMMANDS
# =========================================================
@bot.message_handler(commands=["start"])
def h_start(message):
    uid = message.from_user.id

    if is_admin(uid):
        bot.send_message(
            message.chat.id,
            "👑 Админ-панель. Используй /menu.",
            reply_markup=admin_menu_kb()
        )
        return

    if is_banned(uid):
        bot.send_message(message.chat.id, "🚫 Доступ к боту ограничен.")
        return

    bot.send_message(
        message.chat.id,
        f"👋 Привет! Это бот заявок на выплаты за рекламу канала {CHANNEL}.\n\n"
        "🎁 Система наград:\n"
        "• 1–2 рекламы → 1 мишка 🧸\n"
        "• 3–5 реклам → 2 мишки 🧸🧸\n"
        "• 6–10 реклам → 5 мишек 🧸🧸🧸🧸🧸\n"
        "• 11–20 реклам → 1 NFT 🖼\n"
        f"• Более 20 реклам → обсуждение с {NEGOTIATOR}\n\n"
        f"📸 Максимум в одной заявке: {MAX_PHOTOS} скриншотов.\n\n"
        "Нажми «Подать заявку», укажи аккаунт и количество реклам, "
        "затем отправь скриншоты. После отправки заявка поступит "
        "администратору на проверку.",
        reply_markup=main_kb()
    )


@bot.message_handler(commands=["id"])
def h_id(message):
    bot.reply_to(message, f"Твой Telegram ID: {message.from_user.id}")


@bot.message_handler(commands=["menu"])
def h_menu(message):
    if not is_admin(message.from_user.id):
        return
    bot.send_message(
        message.chat.id,
        "🛠 Админ-панель:",
        reply_markup=admin_menu_kb()
    )


@bot.message_handler(commands=["cancel"])
def h_cancel(message):
    if message.from_user.id in states:
        states.pop(message.from_user.id, None)
        bot.send_message(
            message.chat.id,
            "❌ Действие отменено.",
            reply_markup=main_kb()
        )
    else:
        bot.send_message(message.chat.id, "Сейчас нечего отменять.")


@bot.message_handler(commands=["notify"])
def h_notify(message):
    if not is_admin(message.from_user.id):
        return

    parts = (message.text or "").split()
    if len(parts) < 2:
        current = "ВКЛ" if notify_on() else "ВЫКЛ"
        bot.send_message(
            message.chat.id,
            f"Уведомления сейчас: {current}\n"
            "/notify on — включить\n"
            "/notify off — выключить"
        )
        return

    value = parts[1].lower()
    if value not in ("on", "off"):
        bot.send_message(message.chat.id, "Использование: /notify on или /notify off")
        return

    new_value = "1" if value == "on" else "0"
    x(
        "INSERT INTO settings(key,value) VALUES('notify',?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (new_value,)
    )
    bot.send_message(
        message.chat.id,
        "🔔 Уведомления включены." if new_value == "1"
        else "🔕 Уведомления выключены.",
        reply_markup=admin_menu_kb()
    )


@bot.message_handler(commands=["status"])
def h_status(message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "Использование: /status P-ABCD")
        return

    code = parts[1].strip().upper()
    payout = q(
        "SELECT * FROM payouts WHERE code=? AND user_id=?",
        (code, message.from_user.id),
        one=True
    )
    if not payout:
        bot.reply_to(message, f"Заявка {code} не найдена.")
        return

    bot.send_message(
        message.chat.id,
        fmt_user_payout(payout),
        reply_markup=user_payout_kb(code)
    )


@bot.message_handler(commands=["ban"])
def h_ban(message):
    if not is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        bot.reply_to(message, "Использование: /ban TELEGRAM_ID")
        return
    uid = int(parts[1])
    x(
        "INSERT OR REPLACE INTO banned(user_id,ts) VALUES(?,?)",
        (uid, int(time.time()))
    )
    bot.reply_to(message, f"🚫 Пользователь {uid} заблокирован.")


@bot.message_handler(commands=["unban"])
def h_unban_command(message):
    if not is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        bot.reply_to(message, "Использование: /unban TELEGRAM_ID")
        return
    uid = int(parts[1])
    x("DELETE FROM banned WHERE user_id=?", (uid,))
    bot.reply_to(message, f"✅ Пользователь {uid} разблокирован.")


# =========================================================
# START NEW PAYOUT / QUESTION
# =========================================================
@bot.callback_query_handler(func=lambda c: c.data == "p:new")
def cb_new_payout(call):
    bot.answer_callback_query(call.id)
    uid = call.from_user.id

    if is_banned(uid):
        bot.send_message(call.message.chat.id, "🚫 Доступ к боту ограничен.")
        return

    now = int(time.time())
    if now - cooldown.get(uid, 0) < COOLDOWN:
        remaining = COOLDOWN - (now - cooldown.get(uid, 0))
        bot.send_message(
            call.message.chat.id,
            f"⏳ Подожди ещё {remaining} сек. перед новой заявкой."
        )
        return

    states[uid] = {
        "kind": "payout",
        "step": 0,
        "data": {"photos": []}
    }
    bot.send_message(
        call.message.chat.id,
        "1️⃣ Напиши @username аккаунта/канала, на который оформить выплату:",
        reply_markup=cancel_kb()
    )


@bot.callback_query_handler(func=lambda c: c.data == "q:new")
def cb_new_question(call):
    bot.answer_callback_query(call.id)
    uid = call.from_user.id

    if is_banned(uid):
        bot.send_message(call.message.chat.id, "🚫 Доступ к боту ограничен.")
        return

    states[uid] = {"kind": "question"}
    bot.send_message(
        call.message.chat.id,
        "💬 Напиши свой вопрос одним сообщением:",
        reply_markup=cancel_kb()
    )


@bot.callback_query_handler(func=lambda c: c.data == "cancel")
def cb_cancel(call):
    states.pop(call.from_user.id, None)
    bot.answer_callback_query(call.id, "Отменено")
    bot.send_message(
        call.message.chat.id,
        "Главное меню:",
        reply_markup=main_kb()
    )


# =========================================================
# PHOTO COLLECTION
# =========================================================
@bot.message_handler(content_types=["photo"])
def h_photo(message):
    uid = message.from_user.id
    state = states.get(uid)

    if not state or state.get("kind") != "payout" or state.get("step") != 2:
        bot.send_message(message.chat.id, "Сейчас фотографии не запрашиваются.")
        return

    photos = state["data"]["photos"]

    if len(photos) >= MAX_PHOTOS:
        bot.send_message(
            message.chat.id,
            f"Достигнут лимит — {MAX_PHOTOS} фотографий. "
            "Нажми «Отправить заявку».",
            reply_markup=photos_done_kb()
        )
        return

    photos.append(message.photo[-1].file_id)
    count = len(photos)

    bot.send_message(
        message.chat.id,
        f"📸 Фото {count}/{MAX_PHOTOS} принято.\n"
        "Можешь отправить ещё или нажать «Отправить заявку».",
        reply_markup=photos_done_kb()
    )


@bot.callback_query_handler(func=lambda c: c.data == "photos_done")
def cb_photos_done(call):
    uid = call.from_user.id
    state = states.get(uid)

    if not state or state.get("kind") != "payout" or state.get("step") != 2:
        bot.answer_callback_query(
            call.id,
            "Сейчас ты не заполняешь заявку.",
            show_alert=True
        )
        return

    if not state["data"]["photos"]:
        bot.answer_callback_query(
            call.id,
            "Сначала отправь хотя бы один скриншот.",
            show_alert=True
        )
        return

    bot.answer_callback_query(call.id, "Отправляю заявку...")
    finish_payout(call.message, state, call.from_user)


def finish_payout(message, state, user):
    uid = user.id
    data = state["data"]
    now = int(time.time())
    code = gen_code("P")
    photos = ",".join(data["photos"])

    x(
        "INSERT INTO payouts"
        "(code,user_id,chat_id,username,target,ads_count,reward,photos,created) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (
            code,
            uid,
            message.chat.id,
            user.username or "",
            data["target"],
            data["ads_count"],
            data["reward"],
            photos,
            now
        )
    )

    states.pop(uid, None)
    cooldown[uid] = now

    bot.send_message(
        message.chat.id,
        f"✅ Заявка {code} успешно отправлена на модерацию!\n\n"
        f"📢 Аккаунт/канал: {data['target']}\n"
        f"📊 Количество реклам: {data['ads_count']}\n"
        f"🎁 Предварительная награда: {data['reward']}\n"
        f"📸 Скриншотов: {len(data['photos'])}\n\n"
        "⏳ Администратор проверит заявку. Обычно это занимает "
        "до 24 часов.\n"
        "📩 Результат проверки придёт в этот чат.\n\n"
        f"Чтобы проверить статус позже, используй:\n/status {code}",
        reply_markup=main_kb()
    )

    if notify_on():
        payout = q(
            "SELECT * FROM payouts WHERE code=?",
            (code,),
            one=True
        )
        try:
            send_admin_payout(ADMIN_ID, payout)
        except Exception as exc:
            print("[ADMIN PAYOUT NOTIFICATION ERROR]", exc)


# =========================================================
# TEXT HANDLER: QUESTIONS, PAYOUT STEPS, ADMIN REPLIES/BC
# =========================================================
@bot.message_handler(content_types=["text"])
def h_all_text(message):
    uid = message.from_user.id
    text_value = (message.text or "").strip()

    if not text_value or text_value.startswith("/"):
        return

    # Admin text modes
    if is_admin(uid) and uid in states:
        state = states.get(uid, {})
        kind = state.get("kind")

        if kind == "reply_question":
            code = state["code"]
            states.pop(uid, None)
            row = q(
                "SELECT * FROM questions WHERE code=?",
                (code,),
                one=True
            )
            if not row:
                bot.reply_to(message, "❌ Вопрос не найден.")
                return

            delivered = safe_notify_user(
                row["chat_id"],
                f"💬 Ответ администрации на вопрос {code}:\n\n{text_value}"
            )
            if delivered:
                x(
                    "UPDATE questions SET answer=?,status='answered' WHERE code=?",
                    (text_value, code)
                )
                bot.reply_to(message, "✅ Ответ отправлен пользователю.")
            else:
                bot.reply_to(message, "⚠️ Не удалось отправить ответ пользователю.")
            return

        if kind == "bc":
            states.pop(uid, None)
            recipients = set()
            for row in q("SELECT DISTINCT chat_id FROM payouts"):
                recipients.add(row["chat_id"])
            for row in q("SELECT DISTINCT chat_id FROM questions"):
                recipients.add(row["chat_id"])

            sent = 0
            failed = 0
            for chat_id in recipients:
                try:
                    bot.send_message(chat_id, f"📢 Сообщение от администрации:\n\n{text_value}")
                    sent += 1
                    time.sleep(0.05)
                except Exception:
                    failed += 1

            bot.reply_to(
                message,
                f"📢 Рассылка завершена.\nДоставлено: {sent}\nНе доставлено: {failed}"
            )
            return

        states.pop(uid, None)
        bot.send_message(
            message.chat.id,
            "Режим ввода сброшен.",
            reply_markup=admin_menu_kb()
        )
        return

    # User flow
    if uid in states:
        state = states[uid]

        if state.get("kind") == "question":
            code = gen_code("Q")
            now = int(time.time())
            x(
                "INSERT INTO questions"
                "(code,user_id,chat_id,username,text,created) "
                "VALUES(?,?,?,?,?,?)",
                (
                    code,
                    uid,
                    message.chat.id,
                    message.from_user.username or "",
                    text_value,
                    now
                )
            )
            states.pop(uid, None)

            bot.send_message(
                message.chat.id,
                f"✅ Вопрос {code} отправлен администрации.\n"
                "Ответ придёт сюда же.",
                reply_markup=main_kb()
            )

            if notify_on():
                row = q(
                    "SELECT * FROM questions WHERE code=?",
                    (code,),
                    one=True
                )
                try:
                    bot.send_message(
                        ADMIN_ID,
                        fmt_question(row),
                        reply_markup=question_card_kb(code)
                    )
                except Exception as exc:
                    print("[QUESTION NOTIFICATION ERROR]", exc)
            return

        if state.get("kind") == "payout":
            step = state["step"]

            if step == 0:
                value = text_value.strip()
                if not value.startswith("@") or len(value) < 3:
                    bot.send_message(
                        message.chat.id,
                        "⚠️ Введи username в формате @username.",
                        reply_markup=cancel_kb()
                    )
                    return

                username = value.split()[0]
                if not all(ch.isalnum() or ch == "_" for ch in username[1:]):
                    bot.send_message(
                        message.chat.id,
                        "⚠️ В username допустимы только латинские буквы, "
                        "цифры и символ подчёркивания.",
                        reply_markup=cancel_kb()
                    )
                    return

                state["data"]["target"] = username
                state["step"] = 1
                bot.send_message(
                    message.chat.id,
                    "2️⃣ Сколько реклам ты разместил? Напиши целое число:",
                    reply_markup=cancel_kb()
                )
                return

            if step == 1:
                try:
                    ads = int(text_value)
                    if ads < 1 or ads > 100000:
                        raise ValueError
                except ValueError:
                    bot.send_message(
                        message.chat.id,
                        "⚠️ Введи целое число от 1 до 100000.",
                        reply_markup=cancel_kb()
                    )
                    return

                state["data"]["ads_count"] = ads
                state["data"]["reward"] = calc_reward(ads)
                state["step"] = 2

                bot.send_message(
                    message.chat.id,
                    f"🎁 Предварительная награда: {state['data']['reward']}\n\n"
                    f"3️⃣ Отправь скриншоты подтверждения (до {MAX_PHOTOS} шт.).\n"
                    "Можно отправлять по одному. Когда закончишь, "
                    "нажми «Отправить заявку».",
                    reply_markup=photos_done_kb()
                )
                return

    if is_banned(uid):
        bot.send_message(message.chat.id, "🚫 Доступ к боту ограничен.")
        return

    if is_admin(uid):
        bot.send_message(
            message.chat.id,
            "🛠 Админ-панель:",
            reply_markup=admin_menu_kb()
        )
    else:
        bot.send_message(
            message.chat.id,
            "Выбери действие:",
            reply_markup=main_kb()
        )


# =========================================================
# USER: MY PAYOUTS / QUESTIONS
# =========================================================
@bot.callback_query_handler(func=lambda c: c.data == "my:payouts")
def cb_my_payouts(call):
    bot.answer_callback_query(call.id)
    rows = q(
        "SELECT * FROM payouts "
        "WHERE user_id=? AND hidden=0 AND status!='closed' "
        "ORDER BY id DESC LIMIT 20",
        (call.from_user.id,)
    )
    if not rows:
        bot.send_message(call.message.chat.id, "📋 У тебя пока нет открытых заявок.")
        return

    kb = types.InlineKeyboardMarkup(row_width=1)
    for row in rows:
        kb.add(
            types.InlineKeyboardButton(
                f"{row['code']} — {STATUS.get(row['status'], row['status'])}",
                callback_data=f"upv:{row['code']}"
            )
        )
    kb.add(types.InlineKeyboardButton("⬅️ Главное меню", callback_data="home"))
    bot.send_message(
        call.message.chat.id,
        "📋 Твои заявки:",
        reply_markup=kb
    )


@bot.callback_query_handler(func=lambda c: c.data == "home")
def cb_home(call):
    bot.answer_callback_query(call.id)
    bot.send_message(
        call.message.chat.id,
        "Главное меню:",
        reply_markup=main_kb()
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("upv:"))
def cb_user_view_payout(call):
    code = call.data.split(":", 1)[1]
    payout = q(
        "SELECT * FROM payouts WHERE code=? AND user_id=?",
        (code, call.from_user.id),
        one=True
    )
    if not payout:
        bot.answer_callback_query(call.id, "Заявка не найдена.", show_alert=True)
        return

    if payout["status"] == "closed":
        bot.answer_callback_query(call.id, "Заявка закрыта.", show_alert=True)
        return

    bot.answer_callback_query(call.id)
    bot.send_message(
        call.message.chat.id,
        fmt_user_payout(payout),
        reply_markup=user_payout_kb(code)
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("upc:"))
def cb_user_close_payout(call):
    code = call.data.split(":", 1)[1]
    payout = q(
        "SELECT * FROM payouts WHERE code=? AND user_id=?",
        (code, call.from_user.id),
        one=True
    )
    if not payout:
        bot.answer_callback_query(call.id, "Заявка не найдена.", show_alert=True)
        return

    if payout["status"] in ("closed", "paid", "rejected"):
        bot.answer_callback_query(call.id, "Эту заявку нельзя закрыть.", show_alert=True)
        return

    x("UPDATE payouts SET status='closed' WHERE code=?", (code,))
    bot.answer_callback_query(call.id, "Заявка закрыта.")
    bot.send_message(
        call.message.chat.id,
        f"🔒 Заявка {code} закрыта."
    )
    try:
        bot.send_message(
            ADMIN_ID,
            f"🔒 Пользователь @{payout['username'] or '—'} закрыл заявку {code}."
        )
    except Exception as exc:
        print("[ADMIN CLOSE NOTICE ERROR]", exc)


@bot.callback_query_handler(func=lambda c: c.data.startswith("uph:"))
def cb_user_hide_payout(call):
    code = call.data.split(":", 1)[1]
    payout = q(
        "SELECT * FROM payouts WHERE code=? AND user_id=?",
        (code, call.from_user.id),
        one=True
    )
    if not payout:
        bot.answer_callback_query(call.id, "Заявка не найдена.", show_alert=True)
        return

    x(
        "UPDATE payouts SET hidden=1 WHERE code=? AND user_id=?",
        (code, call.from_user.id)
    )
    bot.answer_callback_query(call.id, "Убрано из списка.")
    bot.send_message(call.message.chat.id, f"👁 Заявка {code} убрана из списка.")


@bot.callback_query_handler(func=lambda c: c.data == "my:questions")
def cb_my_questions(call):
    bot.answer_callback_query(call.id)
    rows = q(
        "SELECT * FROM questions "
        "WHERE user_id=? AND hidden=0 "
        "ORDER BY id DESC LIMIT 20",
        (call.from_user.id,)
    )
    if not rows:
        bot.send_message(call.message.chat.id, "📨 У тебя пока нет вопросов.")
        return

    lines = [
        f"{row['code']} — {QSTATUS.get(row['status'], row['status'])}\n"
        f"{row['text'][:100]}"
        for row in rows
    ]
    bot.send_message(call.message.chat.id, "📨 Твои вопросы:\n\n" + "\n\n".join(lines))


# =========================================================
# ADMIN MENU
# =========================================================
@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:"))
def cb_admin_menu(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "Нет доступа.", show_alert=True)
        return

    bot.answer_callback_query(call.id)
    action = call.data.split(":", 1)[1]
    chat_id = call.message.chat.id

    if action == "menu":
        bot.send_message(chat_id, "🛠 Админ-панель:", reply_markup=admin_menu_kb())
        return

    if action == "open":
        rows = q(
            "SELECT * FROM payouts WHERE status NOT IN ('closed','paid','rejected') "
            "ORDER BY id DESC LIMIT 50"
        )
        if not rows:
            bot.send_message(chat_id, "📂 Открытых заявок нет.")
            return
        bot.send_message(
            chat_id,
            "📂 Открытые заявки:",
            reply_markup=payout_list_kb(rows, "adm:menu")
        )
        return

    if action == "closed":
        rows = q(
            "SELECT * FROM payouts WHERE status='closed' "
            "ORDER BY id DESC LIMIT 50"
        )
        if not rows:
            bot.send_message(chat_id, "🔒 Закрытых заявок нет.")
            return
        bot.send_message(
            chat_id,
            "🔒 Закрытые заявки:",
            reply_markup=payout_list_kb(rows, "adm:menu")
        )
        return

    if action == "all":
        rows = q("SELECT * FROM payouts ORDER BY id DESC LIMIT 50")
        if not rows:
            bot.send_message(chat_id, "Заявок пока нет.")
            return
        bot.send_message(
            chat_id,
            "📋 Последние заявки:",
            reply_markup=payout_list_kb(rows, "adm:menu")
        )
        return

    if action == "questions":
        rows = q("SELECT * FROM questions ORDER BY id DESC LIMIT 50")
        if not rows:
            bot.send_message(chat_id, "💬 Вопросов пока нет.")
            return
        bot.send_message(
            chat_id,
            "💬 Вопросы пользователей:",
            reply_markup=question_list_kb(rows)
        )
        return

    if action == "stats":
        total = q("SELECT COUNT(*) AS c FROM payouts", one=True)["c"]
        new = q("SELECT COUNT(*) AS c FROM payouts WHERE status='new'", one=True)["c"]
        paid = q("SELECT COUNT(*) AS c FROM payouts WHERE status='paid'", one=True)["c"]
        rejected = q("SELECT COUNT(*) AS c FROM payouts WHERE status='rejected'", one=True)["c"]
        closed = q("SELECT COUNT(*) AS c FROM payouts WHERE status='closed'", one=True)["c"]
        questions = q("SELECT COUNT(*) AS c FROM questions", one=True)["c"]

        bot.send_message(
            chat_id,
            "📊 Статистика\n\n"
            f"💰 Всего заявок: {total}\n"
            f"🆕 Новых: {new}\n"
            f"✅ Одобрено: {paid}\n"
            f"❌ Отклонено: {rejected}\n"
            f"🔒 Закрыто: {closed}\n"
            f"💬 Вопросов: {questions}"
        )
        return

    if action == "bans":
        rows = q("SELECT * FROM banned ORDER BY ts DESC LIMIT 50")
        if not rows:
            bot.send_message(chat_id, "🚫 Список блокировок пуст.")
            return
        kb = types.InlineKeyboardMarkup(row_width=1)
        for row in rows:
            kb.add(
                types.InlineKeyboardButton(
                    f"Разблокировать {row['user_id']}",
                    callback_data=f"ub:{row['user_id']}"
                )
            )
        kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="adm:menu"))
        bot.send_message(chat_id, "🚫 Заблокированные пользователи:", reply_markup=kb)
        return

    if action == "notify":
        new_value = "0" if notify_on() else "1"
        x(
            "INSERT INTO settings(key,value) VALUES('notify',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (new_value,)
        )
        bot.send_message(
            chat_id,
            "🔔 Уведомления включены." if new_value == "1"
            else "🔕 Уведомления выключены.",
            reply_markup=admin_menu_kb()
        )
        return

    if action == "bc":
        states[ADMIN_ID] = {"kind": "bc"}
        bot.send_message(
            chat_id,
            "📢 Отправь текст рассылки одним сообщением.\n"
            "Для отмены используй /cancel."
        )
        return

    if action == "csv":
        path = f"payouts_{int(time.time())}.csv"
        with open(path, "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)
            writer.writerow([
                "code", "user_id", "username", "target",
                "ads_count", "reward", "status", "created"
            ])
            for row in q("SELECT * FROM payouts ORDER BY id"):
                writer.writerow([
                    row["code"],
                    row["user_id"],
                    row["username"],
                    row["target"],
                    row["ads_count"],
                    row["reward"],
                    row["status"],
                    time.strftime(
                        "%Y-%m-%d %H:%M:%S",
                        time.localtime(row["created"] or 0)
                    )
                ])
        with open(path, "rb") as file:
            bot.send_document(chat_id, file, caption="📤 Экспорт заявок CSV")
        try:
            os.remove(path)
        except OSError:
            pass
        return


# =========================================================
# ADMIN: OPEN PAYOUT / APPROVE / REJECT / REOPEN / DELETE
# =========================================================
@bot.callback_query_handler(func=lambda c: c.data.startswith("pv:"))
def cb_open_payout(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "Нет доступа.", show_alert=True)
        return

    code = call.data.split(":", 1)[1]
    payout = q(
        "SELECT * FROM payouts WHERE code=?",
        (code,),
        one=True
    )
    if not payout:
        bot.answer_callback_query(call.id, "Заявка не найдена.", show_alert=True)
        return

    bot.answer_callback_query(call.id, "Открываю заявку...")
    send_admin_payout(call.message.chat.id, payout)


@bot.callback_query_handler(func=lambda c: c.data.startswith(("pa:", "pd:")))
def cb_payout_decision(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "Нет доступа.", show_alert=True)
        return

    action, code = call.data.split(":", 1)
    payout = q(
        "SELECT * FROM payouts WHERE code=?",
        (code,),
        one=True
    )

    if not payout:
        bot.answer_callback_query(call.id, "Заявка не найдена.", show_alert=True)
        return

    if payout["status"] == "closed":
        bot.answer_callback_query(call.id, "Заявка закрыта.", show_alert=True)
        return

    if payout["status"] in ("paid", "rejected"):
        bot.answer_callback_query(call.id, "Заявка уже обработана.", show_alert=True)
        return

    if action == "pa":
        x("UPDATE payouts SET status='paid' WHERE code=?", (code,))
        user_text = (
            f"🎉 Ваша заявка {code} на выплату за рекламу ТГК одобрена!\n\n"
            f"⭐️ На ваш аккаунт в Mechagram {payout['target']} "
            f"скоро будет зачислено: {payout['reward']}!\n\n"
            "Спасибо за контент и продвижение ТГК Zellen! ❤️"
        )
        admin_text = (
            f"✅ Заявка {code} принята.\n"
            f"👤 Пользователь: @{payout['username'] or '—'}\n"
            f"🎁 Награда: {payout['reward']}"
        )
    else:
        x("UPDATE payouts SET status='rejected' WHERE code=?", (code,))
        user_text = (
            f"❌ Ваша заявка {code} на выплату за рекламу ТГК "
            "была отклонена администрацией.\n\n"
            "Возможные причины:\n"
            "• Неполные или нечитаемые скриншоты.\n"
            "• Несоответствие количества реклам.\n"
            "• Недостоверные подтверждения.\n"
            "• Нарушение правил размещения рекламы.\n\n"
            "Если считаете, что произошла ошибка, "
            "обратитесь к администрации."
        )
        admin_text = f"❌ Заявка {code} отклонена."

    bot.answer_callback_query(call.id, "Решение сохранено.")
    if not safe_notify_user(payout["chat_id"], user_text):
        admin_text += "\n⚠️ Не удалось доставить сообщение пользователю."

    bot.send_message(
        call.message.chat.id,
        admin_text,
        reply_markup=admin_menu_kb()
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("rc:"))
def cb_reopen(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "Нет доступа.", show_alert=True)
        return

    code = call.data.split(":", 1)[1]
    payout = q(
        "SELECT * FROM payouts WHERE code=?",
        (code,),
        one=True
    )
    if not payout:
        bot.answer_callback_query(call.id, "Заявка не найдена.", show_alert=True)
        return

    if payout["status"] != "closed":
        bot.answer_callback_query(call.id, "Заявка не закрыта.", show_alert=True)
        return

    x(
        "UPDATE payouts SET status='new',hidden=0 WHERE code=?",
        (code,)
    )
    bot.answer_callback_query(call.id, "Заявка снова открыта.")
    bot.send_message(
        call.message.chat.id,
        f"🔓 Заявка {code} снова открыта и возвращена в новые."
    )
    safe_notify_user(
        payout["chat_id"],
        f"🔓 Ваша заявка {code} снова открыта и ожидает проверки."
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("td:"))
def cb_delete_payout(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "Нет доступа.", show_alert=True)
        return

    code = call.data.split(":", 1)[1]
    x("DELETE FROM payouts WHERE code=?", (code,))
    bot.answer_callback_query(call.id, "Заявка удалена.")
    bot.send_message(call.message.chat.id, f"🗑 Заявка {code} удалена из базы.")


# =========================================================
# ADMIN: QUESTIONS
# =========================================================
@bot.callback_query_handler(func=lambda c: c.data.startswith("qv:"))
def cb_open_question(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "Нет доступа.", show_alert=True)
        return

    code = call.data.split(":", 1)[1]
    row = q(
        "SELECT * FROM questions WHERE code=?",
        (code,),
        one=True
    )
    if not row:
        bot.answer_callback_query(call.id, "Вопрос не найден.", show_alert=True)
        return

    bot.answer_callback_query(call.id)
    bot.send_message(
        call.message.chat.id,
        fmt_question(row),
        reply_markup=question_card_kb(code)
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith(("qr:", "qc:")))
def cb_question_action(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "Нет доступа.", show_alert=True)
        return

    action, code = call.data.split(":", 1)
    row = q(
        "SELECT * FROM questions WHERE code=?",
        (code,),
        one=True
    )
    if not row:
        bot.answer_callback_query(call.id, "Вопрос не найден.", show_alert=True)
        return

    bot.answer_callback_query(call.id)

    if action == "qr":
        states[ADMIN_ID] = {
            "kind": "reply_question",
            "code": code
        }
        bot.send_message(
            call.message.chat.id,
            f"✍️ Напиши ответ на вопрос {code}.\nДля отмены: /cancel"
        )
        return

    if action == "qc":
        x("UPDATE questions SET status='closed' WHERE code=?", (code,))
        bot.send_message(
            call.message.chat.id,
            f"🔒 Вопрос {code} закрыт."
        )


@bot.callback_query_handler(func=lambda c: c.data.startswith("ub:"))
def cb_unban(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "Нет доступа.", show_alert=True)
        return

    try:
        uid = int(call.data.split(":", 1)[1])
    except ValueError:
        bot.answer_callback_query(call.id, "Некорректный ID.", show_alert=True)
        return

    x("DELETE FROM banned WHERE user_id=?", (uid,))
    bot.answer_callback_query(call.id, "Пользователь разблокирован.")
    bot.send_message(
        call.message.chat.id,
        f"✅ Пользователь {uid} разблокирован."
    )


# =========================================================
# START
# =========================================================
if __name__ == "__main__":
    print("Starting bot...")
    try:
        bot.remove_webhook()
    except Exception as exc:
        print("Webhook warning:", exc)

    while True:
        try:
            me = bot.get_me()
            print(f"✅ Bot started: @{me.username}")
            print(f"ADMIN_ID = {ADMIN_ID}")
            payout_count = q(
                "SELECT COUNT(*) AS c FROM payouts",
                one=True
            )["c"]
            question_count = q(
                "SELECT COUNT(*) AS c FROM questions",
                one=True
            )["c"]
            print(
                f"📊 Database: payouts={payout_count}, "
                f"questions={question_count}"
            )
            break
        except Exception as exc:
            print(f"⚠️ Telegram API unavailable: {exc}")
            time.sleep(10)

    while True:
        try:
            bot.infinity_polling(
                allowed_updates=["message", "callback_query"],
                timeout=30,
                long_polling_timeout=30
            )
        except Exception as exc:
            print(f"⚠️ Polling error: {exc}")
            time.sleep(10)

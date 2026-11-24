import os, csv, time, sqlite3, threading, random, string

# ====== Игнорируем системный прокси ======
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"
for _v in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
           "ALL_PROXY", "all_proxy"):
    os.environ.pop(_v, None)
import requests
_orig_request = requests.Session.request
def _no_proxy_request(self, *a, **kw):
    kw["proxies"] = {"http": None, "https": None}
    return _orig_request(self, *a, **kw)
requests.Session.request = _no_proxy_request
# =========================================

import telebot
from telebot import apihelper, types

# ============ КОНФИГ ============
BOT_TOKEN = "1780288571:wwwDHj5JBYtarcgsuR9ZyTV-tJ0VOEoCq_u"
BOT_API_BASE = "https://95-163-153-173.sslip.io"
ADMIN_ID = 1780285990
CHANNEL = "@zellenn"
NEGOTIATOR = "@monk888"
COOLDOWN = 30
MAX_PHOTOS = 10

apihelper.API_URL = BOT_API_BASE + "/bot{0}/{1}"
apihelper.FILE_URL = BOT_API_BASE + "/file/bot{0}/{1}"
bot = telebot.TeleBot(BOT_TOKEN, threaded=False)

# ============ БАЗА ============
DB = "bot.db"
_lock = threading.Lock()
_db = sqlite3.connect(DB, check_same_thread=False)
_db.row_factory = sqlite3.Row

# ---- q() и x() объявлены ДО любого использования ----
def q(sql, a=(), one=False):
    with _lock:
        r = _db.execute(sql, a).fetchall()
    return (r[0] if r else None) if one else r

def x(sql, a=()):
    with _lock:
        _db.execute(sql, a)
        _db.commit()
# ----------------------------------------------------

_db.executescript("""
CREATE TABLE IF NOT EXISTS payouts(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE, user_id INTEGER, chat_id INTEGER, username TEXT,
    target TEXT, ads_count INTEGER DEFAULT 0, reward TEXT,
    photos TEXT DEFAULT '', status TEXT DEFAULT 'new',
    hidden INTEGER DEFAULT 0, created INTEGER);
CREATE TABLE IF NOT EXISTS questions(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE, user_id INTEGER, chat_id INTEGER, username TEXT,
    text TEXT, answer TEXT DEFAULT '', status TEXT DEFAULT 'new',
    hidden INTEGER DEFAULT 0, created INTEGER);
CREATE TABLE IF NOT EXISTS banned(user_id INTEGER PRIMARY KEY, ts INTEGER);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
""")
_db.commit()

if not q("SELECT value FROM settings WHERE key='notify'", one=True):
    x("INSERT INTO settings(key,value) VALUES('notify','1')")

def gen_code():
    chars = string.ascii_uppercase + string.digits
    for _ in range(50):
        code = f"P-{''.join(random.choices(chars, k=4))}"
        if not q("SELECT 1 FROM payouts WHERE code=?", (code,), one=True):
            return code
    return f"P-{int(time.time())}"

def calc_reward(ads):
    if ads <= 2: return "1 мишка 🧸"
    elif ads <= 5: return "2 мишки 🧸🧸"
    elif ads <= 10: return "5 мишек 🧸🧸🧸🧸🧸"
    elif ads <= 20: return "1 NFT 🖼"
    else: return f"Договор с {NEGOTIATOR} 💬"

def notify_on():
    r = q("SELECT value FROM settings WHERE key='notify'", one=True)
    return r and r["value"] == "1"

STATUS = {"new":"🆕 Новая","in_work":"🔧 В работе","paid":"✅ Выплачено",
          "rejected":"❌ Отклонена","closed":"🔒 Закрыта"}
QSTATUS = {"new":"🆕 Без ответа","answered":"✅ Отвечен","closed":"🔒 Закрыт"}

states = {}
cooldown = {}

# ============ КЛАВИАТУРЫ ============
def main_kb():
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton("💰 Подать заявку на выплату", callback_data="p:new"))
    kb.add(types.InlineKeyboardButton("💬 Задать вопрос", callback_data="q:new"))
    kb.add(types.InlineKeyboardButton("📋 Мои заявки", callback_data="my:payouts"))
    kb.add(types.InlineKeyboardButton("📨 Мои вопросы", callback_data="my:questions"))
    return kb

def cancel_kb():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("❌ Отменить", callback_data="cancel"))
    return kb

def photos_done_kb():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("✅ Отправить заявку", callback_data="photos_done"))
    kb.add(types.InlineKeyboardButton("❌ Отменить", callback_data="cancel"))
    return kb

def admin_menu_kb():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(types.InlineKeyboardButton("📂 Открытые", callback_data="adm:open"),
           types.InlineKeyboardButton("🔒 Закрытые", callback_data="adm:closed"))
    kb.add(types.InlineKeyboardButton("📋 Все заявки", callback_data="adm:all"),
           types.InlineKeyboardButton("💬 Вопросы", callback_data="adm:questions"))
    kb.add(types.InlineKeyboardButton("📊 Статистика", callback_data="adm:stats"),
           types.InlineKeyboardButton("🚫 Баны", callback_data="adm:bans"))
    notify_label = "🔔 Уведомления: ВКЛ" if notify_on() else "🔕 Уведомления: ВЫКЛ"
    kb.add(types.InlineKeyboardButton(notify_label, callback_data="adm:notify"))
    kb.add(types.InlineKeyboardButton("📢 Рассылка", callback_data="adm:bc"),
           types.InlineKeyboardButton("📤 CSV", callback_data="adm:csv"))
    return kb

def payout_list_kb(rows):
    kb = types.InlineKeyboardMarkup(row_width=1)
    for r in rows:
        label = f"{r['code']} {STATUS.get(r['status'],'')} — {r['reward']}"
        kb.add(types.InlineKeyboardButton(label[:60], callback_data=f"pv:{r['code']}"))
    kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="adm:menu"))
    return kb

def closed_list_kb(rows):
    kb = types.InlineKeyboardMarkup(row_width=1)
    for r in rows:
        label = f"🔒 {r['code']} — {r['reward']}"
        kb.add(types.InlineKeyboardButton(label[:60], callback_data=f"rc:{r['code']}"))
    kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="adm:menu"))
    return kb

def profile_btn(username):
    uname = (username or "").lstrip("@").strip()
    if uname and all(c.isalnum() or c == "_" for c in uname):
        return types.InlineKeyboardButton(
            f"👤 Профиль @{uname}",
            url=f"https://t.me/{uname}"
        )
    return None

def payout_card_kb(code, username="", is_closed=False):
    kb = types.InlineKeyboardMarkup(row_width=2)
    if is_closed:
        kb.add(types.InlineKeyboardButton("🔓 Открыть заново", callback_data=f"rc:{code}"))
        kb.add(types.InlineKeyboardButton("🗑 Удалить", callback_data=f"td:{code}"))
        kb.add(types.InlineKeyboardButton("↩️ Вернуться обратно", callback_data="adm:closed"))
        return kb
    kb.add(types.InlineKeyboardButton("✅ Принять", callback_data=f"pa:{code}"),
           types.InlineKeyboardButton("❌ Отклонить", callback_data=f"pd:{code}"))
    kb.add(types.InlineKeyboardButton("↩️ Вернуться обратно", callback_data="adm:open"))
    return kb

def user_payout_kb(code):
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton("🔒 Закрыть заявку", callback_data=f"upc:{code}"))
    kb.add(types.InlineKeyboardButton("👁 Убрать из списка", callback_data=f"uph:{code}"))
    return kb

def user_my_list_kb(rows):
    kb = types.InlineKeyboardMarkup(row_width=1)
    for r in rows:
        label = f"{r['code']} {STATUS.get(r['status'],'')} — {r['reward']}"
        kb.add(types.InlineKeyboardButton(label[:60], callback_data=f"upv:{r['code']}"))
    return kb

def question_list_kb(rows):
    kb = types.InlineKeyboardMarkup(row_width=1)
    for r in rows:
        label = f"{r['code']} {QSTATUS.get(r['status'],'')} — @{r['username'] or '—'}"
        kb.add(types.InlineKeyboardButton(label[:60], callback_data=f"qv:{r['code']}"))
    kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="adm:menu"))
    return kb

def question_card_kb(code):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(types.InlineKeyboardButton("💬 Ответить", callback_data=f"qr:{code}"),
           types.InlineKeyboardButton("🔒 Закрыть", callback_data=f"qc:{code}"))
    kb.add(types.InlineKeyboardButton("⬅️ К списку", callback_data="adm:questions"))
    return kb

# ============ ФОРМАТ ============
def fmt_payout(t):
    photos = t["photos"] or ""
    count = len(photos.split(",")) if photos else 0
    return (f"💰 *Заявка {t['code']}*\n"
            f"Статус: {STATUS.get(t['status'], t['status'])}\n\n"
            f"👤 @{t['username'] or '—'} (`{t['user_id']}`)\n"
            f"📢 Канал: {t['target']}\n"
            f"📊 Реклам: {t['ads_count']}\n"
            f"🎁 Награда: {t['reward']}\n"
            f"📸 Скриншотов: {count}\n\n"
            f"🕐 {time.strftime('%d.%m %H:%M', time.localtime(t['created']))}")

def fmt_user_payout(t):
    return (f"💰 *Заявка {t['code']}*\n"
            f"Статус: {STATUS.get(t['status'], t['status'])}\n\n"
            f"📢 Канал: {t['target']}\n"
            f"📊 Реклам: {t['ads_count']}\n"
            f"🎁 Награда: {t['reward']}\n\n"
            f"🕐 {time.strftime('%d.%m %H:%M', time.localtime(t['created']))}")

def fmt_question(r):
    ans = f"\n\n✅ *Ответ:* {r['answer']}" if r["answer"] else ""
    return (f"💬 *Вопрос {r['code']}*\n"
            f"Статус: {QSTATUS.get(r['status'], r['status'])}\n\n"
            f"👤 @{r['username'] or '—'} (`{r['user_id']}`)\n\n"
            f"📝 {r['text']}{ans}\n\n"
            f"🕐 {time.strftime('%d.%m %H:%M', time.localtime(r['created']))}")

def is_banned(uid):
    return q("SELECT user_id FROM banned WHERE user_id=?", (uid,), one=True) is not None

# ============ КОМАНДЫ ============
@bot.message_handler(commands=["start"])
def h_start(m):
    if m.from_user.id == ADMIN_ID:
        return bot.send_message(m.chat.id, "👑 Админ. /menu — панель.",
                                reply_markup=admin_menu_kb())
    if is_banned(m.from_user.id):
        return bot.send_message(m.chat.id, "🚫 Забанен.")
    bot.send_message(m.chat.id,
        f"👋 Привет! Это бот выплат за рекламу канала {CHANNEL}.\n\n"
        "🎁 *Награды:*\n"
        "• 1–2 рекламы → 1 мишка 🧸\n"
        "• 2–5 → 2 мишки 🧸🧸\n"
        "• 5–10 → 5 мишек 🧸🧸🧸🧸🧸\n"
        "• 10–20 → 1 NFT 🖼\n"
        f"• больше 20 → договор с {NEGOTIATOR}\n\n"
        f"📸 Если скриншотов больше 10 — напиши в ЛС {NEGOTIATOR}\n\n"
        "Жми «Подать заявку» — укажи username, количество реклам и пришли скриншоты.",
        parse_mode="Markdown", reply_markup=main_kb())

@bot.message_handler(commands=["id"])
def h_id(m): bot.reply_to(m, f"`{m.from_user.id}`", parse_mode="Markdown")

@bot.message_handler(commands=["menu"])
def h_menu(m):
    if m.from_user.id != ADMIN_ID: return
    bot.send_message(m.chat.id, "🛠 Админ-меню:", reply_markup=admin_menu_kb())

@bot.message_handler(commands=["cancel"])
def h_cancel(m):
    if m.from_user.id in states:
        del states[m.from_user.id]
        return bot.send_message(m.chat.id, "Отменено.", reply_markup=main_kb())
    bot.send_message(m.chat.id, "Нечего отменять.")

@bot.message_handler(commands=["notify"])
def h_notify(m):
    if m.from_user.id != ADMIN_ID: return
    parts = (m.text or "").split()
    if len(parts) < 2:
        cur = "ВКЛ" if notify_on() else "ВЫКЛ"
        return bot.send_message(m.chat.id, f"Сейчас: {cur}\n`/notify on` или `/notify off`",
                                parse_mode="Markdown")
    val = parts[1].lower()
    if val == "on":
        x("UPDATE settings SET value='1' WHERE key='notify'")
        bot.send_message(m.chat.id, "🔔 Уведомления включены.")
    elif val == "off":
        x("UPDATE settings SET value='0' WHERE key='notify'")
        bot.send_message(m.chat.id, "🔕 Уведомления выключены.")
    else:
        bot.send_message(m.chat.id, "Использование: `/notify on` или `/notify off`",
                         parse_mode="Markdown")

@bot.message_handler(commands=["status"])
def h_status(m):
    parts = (m.text or "").split(maxsplit=1)
    if len(parts) < 2:
        return bot.send_message(m.chat.id, "Использование: `/status КОД`\nПример: `/status P-ABCD`",
                                parse_mode="Markdown")
    code = parts[1].strip().upper()
    t = q("SELECT * FROM payouts WHERE code=? AND user_id=?", (code, m.from_user.id), one=True)
    if not t:
        return bot.send_message(m.chat.id, f"Заявка `{code}` не найдена.", parse_mode="Markdown")
    bot.send_message(m.chat.id, fmt_user_payout(t), parse_mode="Markdown")

# ============ СТАРТ ЗАЯВКИ ============
@bot.callback_query_handler(func=lambda c: c.data == "p:new")
def cb_new_payout(c):
    bot.answer_callback_query(c.id)
    uid = c.from_user.id
    if is_banned(uid): return bot.send_message(c.message.chat.id, "🚫 Забанен.")
    if int(time.time()) - cooldown.get(uid, 0) < COOLDOWN:
        return bot.send_message(c.message.chat.id, "⏳ Подожди.")
    states[uid] = {"kind": "payout", "step": 0, "data": {"photos": []}}
    bot.send_message(c.message.chat.id,
        "1️⃣ Напиши свой `@username`, на который оформить выплату:",
        parse_mode="Markdown", reply_markup=cancel_kb())

@bot.callback_query_handler(func=lambda c: c.data == "q:new")
def cb_new_question(c):
    bot.answer_callback_query(c.id)
    uid = c.from_user.id
    if is_banned(uid): return bot.send_message(c.message.chat.id, "🚫 Забанен.")
    states[uid] = {"kind": "question"}
    bot.send_message(c.message.chat.id,
        "💬 Напиши свой вопрос:", reply_markup=cancel_kb())

@bot.callback_query_handler(func=lambda c: c.data == "cancel")
def cb_cancel(c):
    states.pop(c.from_user.id, None)
    bot.answer_callback_query(c.id, "Отменено")
    bot.send_message(c.message.chat.id, "Главное меню:", reply_markup=main_kb())

# ============ ФОТО ============
@bot.message_handler(content_types=["photo"])
def h_photo(m):
    uid = m.from_user.id
    st = states.get(uid)
    if not st or st.get("kind") != "payout" or st.get("step") != 2:
        return bot.send_message(m.chat.id, "Сейчас фото не нужно.")
    photo_id = m.photo[-1].file_id
    st["data"]["photos"].append(photo_id)
    count = len(st["data"]["photos"])
    if count > MAX_PHOTOS:
        return bot.send_message(m.chat.id,
            f"📸 У тебя уже больше {MAX_PHOTOS} скриншотов.\n\n"
            f"Такие объёмы разбираем вручную — напиши в ЛС {NEGOTIATOR}, "
            f"скинь все скрины туда, и мы всё оформим.",
            parse_mode="Markdown", reply_markup=photos_done_kb())
    if count == MAX_PHOTOS:
        return bot.send_message(m.chat.id,
            f"📸 Фото {count}/{MAX_PHOTOS} — достигнут лимит.\n"
            f"Нажми «Отправить заявку» или, если скринов больше, "
            f"напиши в ЛС {NEGOTIATOR}.",
            parse_mode="Markdown", reply_markup=photos_done_kb())
    bot.send_message(m.chat.id,
        f"📸 Фото {count}/{MAX_PHOTOS} принято.\n"
        f"Пришли ещё или нажми «Отправить заявку».",
        reply_markup=photos_done_kb())

@bot.callback_query_handler(func=lambda c: c.data == "photos_done")
def cb_photos_done(c):
    uid = c.from_user.id
    st = states.get(uid)
    if not st or st.get("kind") != "payout" or st.get("step") != 2:
        return bot.answer_callback_query(c.id, "Не в анкете", show_alert=True)
    if not st["data"]["photos"]:
        return bot.answer_callback_query(c.id, "Пришли хотя бы одно фото", show_alert=True)
    bot.answer_callback_query(c.id, "Отправляю...")
    finish_payout(c.message, st)

# ============ ЕДИНЫЙ ТЕКСТ ============
@bot.message_handler(content_types=["text"])
def h_all_text(m):
    uid = m.from_user.id
    txt = (m.text or "").strip()
    if txt.startswith("/"): return

    # --- АДМИН ---
    if uid == ADMIN_ID and ADMIN_ID in states:
        st = states.get(ADMIN_ID, {})
        kind = st.get("kind")
        if kind == "reply_payout":
            code = st["code"]; del states[ADMIN_ID]
            t = q("SELECT * FROM payouts WHERE code=?", (code,), one=True)
            if not t: return bot.reply_to(m, "❌ Заявка не найдена")
            try:
                bot.send_message(t["chat_id"], f"💬 Ответ по заявке {code}:\n\n{txt}")
                bot.reply_to(m, "✅ Отправлено")
            except Exception as e:
                bot.reply_to(m, f"❌ Ошибка: {e}")
            return
        if kind == "reply_question":
            code = st["code"]; del states[ADMIN_ID]
            r = q("SELECT * FROM questions WHERE code=?", (code,), one=True)
            if not r: return bot.reply_to(m, "❌ Вопрос не найден")
            try:
                bot.send_message(r["chat_id"], f"💬 Ответ на вопрос {code}:\n\n{txt}")
                x("UPDATE questions SET answer=?, status='answered' WHERE code=?", (txt, code))
                bot.reply_to(m, "✅ Отправлено")
            except Exception as e:
                bot.reply_to(m, f"❌ Ошибка: {e}")
            return
        if kind == "bc":
            del states[ADMIN_ID]
            uids = set()
            for r in q("SELECT DISTINCT chat_id FROM payouts"): uids.add(r["chat_id"])
            for r in q("SELECT DISTINCT chat_id FROM questions"): uids.add(r["chat_id"])
            ok = 0
            for cid in uids:
                try: bot.send_message(cid, f"📢 {txt}"); ok += 1; time.sleep(0.05)
                except Exception: pass
            return bot.reply_to(m, f"📢 {ok}/{len(uids)}")
        del states[ADMIN_ID]
        return bot.send_message(m.chat.id, "Режим сброшен.", reply_markup=admin_menu_kb())

    # --- ПОЛЬЗОВАТЕЛЬ ---
    if uid in states:
        st = states[uid]
        if st.get("kind") == "question":
            now = int(time.time()); code = f"Q-{''.join(random.choices(string.ascii_uppercase + string.digits, k=4))}"
            x("INSERT INTO questions(code,user_id,chat_id,username,text,created) VALUES(?,?,?,?,?,?)",
              (code, uid, m.chat.id, m.from_user.username or "", txt, now))
            del states[uid]
            bot.send_message(m.chat.id, f"✅ Вопрос {code} отправлен.", reply_markup=main_kb())
            r = q("SELECT * FROM questions WHERE code=?", (code,), one=True)
            try:
                if notify_on():
                    bot.send_message(ADMIN_ID, fmt_question(r), parse_mode="Markdown",
                                     reply_markup=question_card_kb(code))
            except Exception as e: print("[NOTIFY Q]", e)
            return
        if st.get("kind") == "payout":
            step = st["step"]
            if step == 0:
                if "@" not in txt:
                    return bot.send_message(m.chat.id, "⚠️ Нужен `@username`.", parse_mode="Markdown")
                target = "@" + txt.split("@", 1)[1].split()[0].strip()
                st["data"]["target"] = target
                st["step"] = 1
                return bot.send_message(m.chat.id,
                    "2️⃣ Сколько реклам ты сделал? Напиши число (например `7`):",
                    reply_markup=cancel_kb())
            if step == 1:
                try:
                    ads = int(txt.strip())
                    if ads < 0: raise ValueError
                except ValueError:
                    return bot.send_message(m.chat.id, "⚠️ Напиши число, например `7`.")
                st["data"]["ads_count"] = ads
                st["data"]["reward"] = calc_reward(ads)
                st["step"] = 2
                return bot.send_message(m.chat.id,
                    f"🎁 Твоя награда: *{st['data']['reward']}*\n\n"
                    f"3️⃣ Пришли скриншоты рекламы (до {MAX_PHOTOS} шт).\n"
                    f"Можно по одному. Когда закончишь — нажми «Отправить заявку».",
                    parse_mode="Markdown", reply_markup=photos_done_kb())

    if uid != ADMIN_ID:
        if is_banned(uid): return bot.send_message(m.chat.id, "🚫 Забанен.")
        return bot.send_message(m.chat.id, "Выбери действие:", reply_markup=main_kb())
    bot.send_message(m.chat.id, "Админ-меню:", reply_markup=admin_menu_kb())

def finish_payout(m, st):
    uid = m.from_user.id
    d = st["data"]
    now = int(time.time()); code = gen_code()
    photos = ",".join(d["photos"])
    x("INSERT INTO payouts(code,user_id,chat_id,username,target,ads_count,reward,photos,created) VALUES(?,?,?,?,?,?,?,?,?)",
      (code, uid, m.chat.id, m.from_user.username or "", d["target"],
       d["ads_count"], d["reward"], photos, now))
    del states[uid]; cooldown[uid] = now
    bot.send_message(m.chat.id,
        f"✅ Заявка #{code} отправлена!",
        reply_markup=main_kb())
    if notify_on():
        t = q("SELECT * FROM payouts WHERE code=?", (code,), one=True)
        try:
            if d["photos"]:
                bot.send_photo(ADMIN_ID, d["photos"][0], caption=fmt_payout(t),
                               parse_mode="Markdown", reply_markup=payout_card_kb(code, m.from_user.username))
                for extra in d["photos"][1:]:
                    bot.send_photo(ADMIN_ID, extra)
            else:
                bot.send_message(ADMIN_ID, fmt_payout(t), parse_mode="Markdown",
                                 reply_markup=payout_card_kb(code, m.from_user.username))
        except Exception as e:
            print("[NOTIFY P]", e)

# ============ МОИ ЗАЯВКИ ============
@bot.callback_query_handler(func=lambda c: c.data == "my:payouts")
def cb_my_payouts(c):
    bot.answer_callback_query(c.id)
    rows = q("SELECT * FROM payouts WHERE user_id=? AND hidden=0 AND status != 'closed' ORDER BY id DESC LIMIT 20",
             (c.from_user.id,))
    if not rows: return bot.send_message(c.message.chat.id, "Заявок нет.")
    bot.send_message(c.message.chat.id, "📋 Твои заявки:",
                     reply_markup=user_my_list_kb(rows))

@bot.callback_query_handler(func=lambda c: c.data.startswith("upv:"))
def cb_user_view_payout(c):
    code = c.data.split(":")[1]
    t = q("SELECT * FROM payouts WHERE code=? AND user_id=?", (code, c.from_user.id), one=True)
    if not t: return bot.answer_callback_query(c.id, "Не найдена", show_alert=True)
    if t["status"] == "closed":
        return bot.answer_callback_query(c.id, "🔒 Заявка закрыта", show_alert=True)
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, fmt_user_payout(t), parse_mode="Markdown",
                     reply_markup=user_payout_kb(code))

@bot.callback_query_handler(func=lambda c: c.data.startswith("upc:"))
def cb_user_close_payout(c):
    code = c.data.split(":")[1]
    t = q("SELECT * FROM payouts WHERE code=? AND user_id=?", (code, c.from_user.id), one=True)
    if not t: return bot.answer_callback_query(c.id, "Не найдена", show_alert=True)
    if t["status"] == "closed":
        return bot.answer_callback_query(c.id, "Уже закрыта", show_alert=True)
    x("UPDATE payouts SET status='closed' WHERE code=?", (code,))
    bot.answer_callback_query(c.id, "Закрыто")
    bot.send_message(c.message.chat.id, f"🔒 Заявка *{code}* закрыта.",
                     parse_mode="Markdown")
    try:
        bot.send_message(ADMIN_ID, f"🔒 @{t['username'] or '—'} закрыл заявку {code}")
    except Exception: pass

@bot.callback_query_handler(func=lambda c: c.data.startswith("uph:"))
def cb_user_hide_payout(c):
    code = c.data.split(":")[1]
    t = q("SELECT * FROM payouts WHERE code=? AND user_id=?", (code, c.from_user.id), one=True)
    if not t: return bot.answer_callback_query(c.id, "Не найдена", show_alert=True)
    x("UPDATE payouts SET hidden=1 WHERE code=?", (code,))
    bot.answer_callback_query(c.id, "Убрано")
    bot.send_message(c.message.chat.id, f"👁 Заявка {code} убрана.")

@bot.callback_query_handler(func=lambda c: c.data == "my:questions")
def cb_my_questions(c):
    bot.answer_callback_query(c.id)
    rows = q("SELECT * FROM questions WHERE user_id=? AND hidden=0 ORDER BY id DESC LIMIT 20",
             (c.from_user.id,))
    if not rows: return bot.send_message(c.message.chat.id, "Вопросов нет.")
    bot.send_message(c.message.chat.id, "📨 Твои вопросы:\n" + "\n".join(
        f"{r['code']} {QSTATUS.get(r['status'])} — {r['text'][:40]}" for r in rows))

# ============ АДМИН-МЕНЮ ============
@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:"))
def cb_admin_menu(c):
    if c.from_user.id != ADMIN_ID:
        return bot.answer_callback_query(c.id, "Нет доступа", show_alert=True)
    bot.answer_callback_query(c.id)
    k = c.data.split(":")[1]

    if k == "menu":
        return bot.send_message(c.message.chat.id, "🛠 Меню:", reply_markup=admin_menu_kb())
    if k == "open":
        rows = q("SELECT * FROM payouts WHERE status != 'closed' ORDER BY id DESC LIMIT 30")
        if not rows: return bot.send_message(c.message.chat.id, "Открытых нет.")
        return bot.send_message(c.message.chat.id, "📂 Открытые:",
                                reply_markup=payout_list_kb(rows))
    if k == "closed":
        rows = q("SELECT * FROM payouts WHERE status = 'closed' ORDER BY id DESC LIMIT 30")
        if not rows: return bot.send_message(c.message.chat.id, "Закрытых нет.")
        return bot.send_message(c.message.chat.id, "🔒 Закрытые:",
                                reply_markup=closed_list_kb(rows))
    if k == "all":
        rows = q("SELECT * FROM payouts ORDER BY id DESC LIMIT 30")
        if not rows: return bot.send_message(c.message.chat.id, "Заявок нет.")
        return bot.send_message(c.message.chat.id, "📋 Все заявки:",
                                reply_markup=payout_list_kb(rows))
    if k == "questions":
        rows = q("SELECT * FROM questions ORDER BY id DESC LIMIT 30")
        if not rows: return bot.send_message(c.message.chat.id, "Вопросов нет.")
        return bot.send_message(c.message.chat.id, "💬 Вопросы:",
                                reply_markup=question_list_kb(rows))
    if k == "stats":
        tot = q("SELECT COUNT(*) c FROM payouts", one=True)["c"]
        new = q("SELECT COUNT(*) c FROM payouts WHERE status='new'", one=True)["c"]
        paid = q("SELECT COUNT(*) c FROM payouts WHERE status='paid'", one=True)["c"]
        rej = q("SELECT COUNT(*) c FROM payouts WHERE status='rejected'", one=True)["c"]
        clo = q("SELECT COUNT(*) c FROM payouts WHERE status='closed'", one=True)["c"]
        qs = q("SELECT COUNT(*) c FROM questions", one=True)["c"]
        return bot.send_message(c.message.chat.id,
            f"📊 *Статистика*\n\n"
            f"💰 Заявки: {tot} (🆕 {new} | ✅ {paid} | ❌ {rej} | 🔒 {clo})\n"
            f"💬 Вопросы: {qs}", parse_mode="Markdown")
    if k == "bans":
        rows = q("SELECT * FROM banned")
        if not rows: return bot.send_message(c.message.chat.id, "Пусто.")
        kb = types.InlineKeyboardMarkup(row_width=1)
        for r in rows:
            kb.add(types.InlineKeyboardButton(f"Разбан {r['user_id']}",
                callback_data=f"ub:{r['user_id']}"))
        return bot.send_message(c.message.chat.id, "🚫 Баны:", reply_markup=kb)
    if k == "notify":
        new_val = "0" if notify_on() else "1"
        x("UPDATE settings SET value=? WHERE key='notify'", (new_val,))
        return bot.send_message(c.message.chat.id,
            "🔔 Уведомления включены." if new_val == "1" else "🔕 Уведомления выключены.",
            reply_markup=admin_menu_kb())
    if k == "bc":
        states[ADMIN_ID] = {"kind": "bc"}
        return bot.send_message(c.message.chat.id, "📢 Текст рассылки (или /cancel):")
    if k == "csv":
        path = f"payouts_{int(time.time())}.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["code","user","username","target","ads","reward","status","created"])
            for r in q("SELECT * FROM payouts ORDER BY id"):
                w.writerow([r["code"], r["user_id"], r["username"], r["target"],
                            r["ads_count"], r["reward"], r["status"],
                            time.strftime("%Y-%m-%d %H:%M", time.localtime(r["created"]))])
        with open(path, "rb") as f:
            bot.send_document(c.message.chat.id, f)

# ============ ОТКРЫТИЕ / ДЕЙСТВИЯ ============
@bot.callback_query_handler(func=lambda c: c.data.startswith("pv:"))
def cb_open_payout(c):
    if c.from_user.id != ADMIN_ID:
        return bot.answer_callback_query(c.id, "Нет доступа", show_alert=True)
    code = c.data.split(":")[1]
    t = q("SELECT * FROM payouts WHERE code=?", (code,), one=True)
    if not t: return bot.answer_callback_query(c.id, f"Заявка {code} не в базе", show_alert=True)
    is_closed = (t["status"] == "closed")
    bot.answer_callback_query(c.id, f"Заявка {code}")
    photos = t["photos"].split(",") if t["photos"] else []
    if photos:
        try:
            bot.send_photo(c.message.chat.id, photos[0], caption=fmt_payout(t),
                           parse_mode="Markdown",
                           reply_markup=payout_card_kb(code, t["username"], is_closed))
            for extra in photos[1:]:
                bot.send_photo(c.message.chat.id, extra)
            return
        except Exception: pass
    bot.send_message(c.message.chat.id, fmt_payout(t), parse_mode="Markdown",
                     reply_markup=payout_card_kb(code, t["username"], is_closed))

@bot.callback_query_handler(func=lambda c: c.data.startswith("rc:"))
def cb_reopen(c):
    if c.from_user.id != ADMIN_ID:
        return bot.answer_callback_query(c.id, "Нет доступа", show_alert=True)
    code = c.data.split(":")[1]
    t = q("SELECT * FROM payouts WHERE code=?", (code,), one=True)
    if not t: return bot.answer_callback_query(c.id, "Не найдена", show_alert=True)
    x("UPDATE payouts SET status='new', hidden=0 WHERE code=?", (code,))
    bot.answer_callback_query(c.id, "Открыта заново")
    bot.send_message(c.message.chat.id, f"🔓 Заявка {code} снова открыта (Новая).")
    try:
        bot.send_message(t["chat_id"], f"🔓 Твоя заявка {code} снова открыта.")
    except Exception: pass

@bot.callback_query_handler(func=lambda c: c.data[:2] in ("pa","pd") and ":" in c.data)
def cb_payout_decision(c):
    if c.from_user.id != ADMIN_ID:
        return bot.answer_callback_query(c.id, "Нет доступа", show_alert=True)
    act, code = c.data.split(":")
    t = q("SELECT * FROM payouts WHERE code=?", (code,), one=True)
    if not t: return bot.answer_callback_query(c.id, f"Заявка {code} не в базе", show_alert=True)
    if t["status"] == "closed":
        return bot.answer_callback_query(c.id, "🔒 Заявка закрыта", show_alert=True)
    bot.answer_callback_query(c.id)

    if act == "pa":
        x("UPDATE payouts SET status='paid' WHERE code=?", (code,))
        try:
            bot.send_message(t["chat_id"],
                f"🎉 Ваша заявка #{code} на выплату за рекламу ТГК одобрена!\n\n"
                f"⭐️ На ваш аккаунт в Mechagram {t['target']} скоро будет зачислено {t['reward']}!\n\n"
                f"Спасибо за контент и продвижение ТГК Zellen! ❤️",
                parse_mode="Markdown")
        except Exception: pass
        bot.send_message(c.message.chat.id, f"🎉 Заявка #{code} одобрена.")
    elif act == "pd":
        x("UPDATE payouts SET status='rejected' WHERE code=?", (code,))
        try:
            bot.send_message(t["chat_id"],
                f"❌ Ваша заявка #{code} на выплату за рекламу ТГК была отклонена администрацией.\n\n"
                f"Возможные причины: неполные скриншоты, фотошоп, несоответствие количества реклам.\n\n"
                f"Если считаешь, что произошла ошибка — напиши нам.",
                parse_mode="Markdown")
        except Exception: pass
        bot.send_message(c.message.chat.id, f"❌ Заявка #{code} отклонена.")

@bot.callback_query_handler(func=lambda c: c.data.startswith("td:"))
def cb_delete_payout(c):
    if c.from_user.id != ADMIN_ID:
        return bot.answer_callback_query(c.id, "Нет доступа", show_alert=True)
    code = c.data.split(":")[1]
    x("DELETE FROM payouts WHERE code=?", (code,))
    bot.answer_callback_query(c.id, "Удалено")
    bot.send_message(c.message.chat.id, f"🗑 Заявка {code} удалена.")

# ============ ВОПРОСЫ (админ) ============
@bot.callback_query_handler(func=lambda c: c.data.startswith("qv:"))
def cb_open_question(c):
    if c.from_user.id != ADMIN_ID:
        return bot.answer_callback_query(c.id, "Нет доступа", show_alert=True)
    code = c.data.split(":")[1]
    r = q("SELECT * FROM questions WHERE code=?", (code,), one=True)
    if not r: return bot.answer_callback_query(c.id, "Не найдено", show_alert=True)
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, fmt_question(r), parse_mode="Markdown",
                     reply_markup=question_card_kb(code))

@bot.callback_query_handler(func=lambda c: c.data[:2] in ("qr","qc") and ":" in c.data)
def cb_question_action(c):
    if c.from_user.id != ADMIN_ID:
        return bot.answer_callback_query(c.id, "Нет доступа", show_alert=True)
    act, code = c.data.split(":")
    r = q("SELECT * FROM questions WHERE code=?", (code,), one=True)
    if not r: return bot.answer_callback_query(c.id, "Не найдено", show_alert=True)
    bot.answer_callback_query(c.id)
    if act == "qr":
        states[ADMIN_ID] = {"kind": "reply_question", "code": code}
        return bot.send_message(c.message.chat.id, f"✍️ Ответ на {code} (или /cancel):")
    if act == "qc":
        x("UPDATE questions SET status='closed' WHERE code=?", (code,))
        return bot.send_message(c.message.chat.id, f"🔒 Вопрос {code} закрыт")

@bot.callback_query_handler(func=lambda c: c.data.startswith("ub:"))
def cb_unban(c):
    if c.from_user.id != ADMIN_ID: return
    uid = int(c.data.split(":")[1])
    x("DELETE FROM banned WHERE user_id=?", (uid,))
    bot.answer_callback_query(c.id, "Разбанен")
    try: bot.edit_message_text(f"✅ Разбан {uid}", c.message.chat.id, c.message.message_id)
    except Exception: pass

# ============ ЗАПУСК ============
if __name__ == "__main__":
    print("Снимаю webhook...")
    try: bot.delete_webhook(drop_pending_updates=False)
    except Exception as e: print("⚠️ webhook:", e)

    while True:
        try:
            me = bot.get_me()
            print(f"✅ Запуск @{me.username}")
            break
        except Exception as e:
            print(f"⏳ Сервер недоступен: {str(e)[:120]}")
            print("   Жду 15 сек...")
            time.sleep(15)

    print(f"ADMIN_ID = {ADMIN_ID}")
    cnt = q("SELECT COUNT(*) c FROM payouts", one=True)["c"]
    qcnt = q("SELECT COUNT(*) c FROM questions", one=True)["c"]
    print(f"📊 В базе: заявок={cnt}, вопросов={qcnt}")

    while True:
        try:
            bot.infinity_polling(allowed_updates=["message","callback_query"],
                                 timeout=30, long_polling_timeout=30)
        except Exception as e:
            print(f"⚠️ Polling упал: {e}")
            print("   Перезапуск через 10 сек...")
            time.sleep(10)

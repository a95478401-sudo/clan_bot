#!/usr/bin/env python3
"""
❥VP Clan Bot — Бот для заявок в клан по CS2
• Два администратора
• Планка набора — /setlimit
• Авто-подсчёт участников группы
• При отказе — опциональная причина
"""

import logging
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# ──────────────────────────────────────────────
#  НАСТРОЙКИ
# ──────────────────────────────────────────────
BOT_TOKEN  = "8617472901:AAFdqtDF4ermOn_eX0wESVmO5jwWdkry8fg"
GROUP_LINK = "https://t.me/+AC56M5JFGRllYmFi"

# Оба администратора
ADMIN_IDS: set[int] = {8054412009, 7628577301}
# ──────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Глобальное состояние ──
applications: dict[int, dict] = {}
app_counter   = 0
slot_limit    = 5
group_chat_id: int | None = None

# pending_reject хранит {admin_id: app_id} пока ждём текст причины
pending_reject: dict[int, int] = {}

# ── Состояния диалогов ──
(
    ASK_NAME,
    ASK_AGE,
    ASK_PRIME,
    ASK_HOURS,
    ASK_DAILY,
    ASK_NICK,
    ASK_CONFIRM,
    WAIT_LIMIT,
    WAIT_REJECT_REASON,
) = range(9)


# ────────────────────────────────────────────────────────────
#  ПРОВЕРКА ПРАВ
# ────────────────────────────────────────────────────────────

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# ────────────────────────────────────────────────────────────
#  ПОДСЧЁТ УЧАСТНИКОВ ГРУППЫ
# ────────────────────────────────────────────────────────────

async def get_real_member_count(bot) -> int | None:
    global group_chat_id
    if group_chat_id is None:
        return None
    try:
        count = await bot.get_chat_member_count(group_chat_id)
        return max(0, count - 1)   # -1 = сам бот
    except Exception as e:
        logger.warning(f"Не удалось получить кол-во участников: {e}")
        return None


async def get_slots_info(bot) -> tuple[int | None, int, int | None]:
    members = await get_real_member_count(bot)
    if members is None:
        return None, slot_limit, None
    free = max(0, slot_limit - members)
    return members, slot_limit, free


# ────────────────────────────────────────────────────────────
#  ХЕЛПЕРЫ
# ────────────────────────────────────────────────────────────

def application_text(data: dict, status: str = "") -> str:
    status_line = f"\n🔖 Статус: {status}" if status else ""
    return (
        f"📋 *ЗАЯВКА В КЛАН ❥VP* #{data['id']}{status_line}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Имя / Никнейм в Steam: *{data['name']}*\n"
        f"🎂 Возраст: *{data['age']} лет*\n"
        f"⭐ Прайм статус: *{data['prime']}*\n"
        f"⏱ Часов в CS2: *{data['hours']}*\n"
        f"🕐 Часов в день: *{data['daily']}*\n"
        f"🏷 Тег клана поставит: *{data['nick']}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 User ID: `{data['user_id']}`"
    )


def slots_line(members: int | None, limit: int, free: int | None) -> str:
    if free is None:
        return f"🔴 Планка набора: *{limit}* чел. (добавь бота в группу как админа)"
    filled = min(members, limit)
    bar_len = min(limit, 20)
    filled_bar = round(filled / limit * bar_len) if limit else 0
    bar = "█" * filled_bar + "░" * (bar_len - filled_bar)
    return (
        f"👥 В группе: *{members}* / {limit} чел.\n"
        f"`{bar}`\n"
        f"{'🟢' if free > 0 else '🔴'} Свободных мест: *{free}*"
    )


async def notify_all_admins(bot, text: str, reply_markup=None) -> None:
    """Отправляет сообщение всем администраторам."""
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=text,
                parse_mode="Markdown",
                reply_markup=reply_markup,
            )
        except Exception as e:
            logger.error(f"Не удалось написать админу {admin_id}: {e}")


# ────────────────────────────────────────────────────────────
#  ОТСЛЕЖИВАНИЕ group_chat_id
# ────────────────────────────────────────────────────────────

async def track_group(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    global group_chat_id
    if update.effective_chat and update.effective_chat.type in ("group", "supergroup"):
        if group_chat_id != update.effective_chat.id:
            group_chat_id = update.effective_chat.id
            logger.info(f"group_chat_id зафиксирован: {group_chat_id}")


# ────────────────────────────────────────────────────────────
#  /start
# ────────────────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    members, limit, free = await get_slots_info(ctx.bot)

    if free is not None and free <= 0:
        await update.message.reply_text(
            "😔 *Извините, у нас все места заполнены!*\n\n"
            f"В клане сейчас *{members}* из *{limit}* участников.\n\n"
            "Приходите в другой раз — мы периодически открываем новый набор! 🎮",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    slots_info = slots_line(members, limit, free)
    text = (
        "👋 Привет! Это бот для подачи заявки в клан *❥VP* (CS2)\n\n"
        "📌 *Требования:*\n"
        "• Возраст 12–16 лет\n"
        "• Прайм статус обязателен\n"
        "• Минимум 100 часов в CS2\n"
        "• Готов ставить тег и аву клана\n"
        "• Играть от 2 до 6 часов в день\n"
        "• Праки + веселье на разных серверах\n\n"
        f"{slots_info}\n\n"
        "Нажми кнопку ниже, чтобы подать заявку 👇"
    )
    kb = [[InlineKeyboardButton("📝 Подать заявку", callback_data="apply")]]
    await update.message.reply_text(
        text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb),
    )
    return ConversationHandler.END


async def apply_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    members, limit, free = await get_slots_info(ctx.bot)
    if free is not None and free <= 0:
        await update.callback_query.message.reply_text(
            "😔 *Места только что закончились!*\n\nПриходи в другой раз 🎮",
            parse_mode="Markdown",
        )
        return ConversationHandler.END
    await update.callback_query.message.reply_text(
        "✍️ Начинаем заполнение заявки!\n\n"
        "Шаг 1/6 — Напиши своё *имя* (или никнейм в Steam):",
        parse_mode="Markdown",
    )
    return ASK_NAME


# ────────────────────────────────────────────────────────────
#  ШАГИ АНКЕТЫ
# ────────────────────────────────────────────────────────────

async def ask_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["name"] = update.message.text.strip()
    await update.message.reply_text(
        "Шаг 2/6 — Сколько тебе *лет*? (нужно 12–16)", parse_mode="Markdown",
    )
    return ASK_AGE


async def ask_age(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.isdigit() or not (10 <= int(text) <= 99):
        await update.message.reply_text("⚠️ Введи возраст числом, например: 14")
        return ASK_AGE
    age = int(text)
    if not (12 <= age <= 16):
        await update.message.reply_text(
            f"😔 Возраст {age} лет не подходит (нужно 12–16 лет).\n"
            "Следи за обновлениями! /start"
        )
        return ConversationHandler.END
    ctx.user_data["age"] = text
    kb = [
        [InlineKeyboardButton("✅ Да, есть", callback_data="prime_yes")],
        [InlineKeyboardButton("❌ Нет",      callback_data="prime_no")],
    ]
    await update.message.reply_text(
        "Шаг 3/6 — Есть ли у тебя *Прайм статус* в CS2?",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb),
    )
    return ASK_PRIME


async def ask_prime(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    if update.callback_query.data == "prime_no":
        await update.callback_query.message.reply_text(
            "😔 Прайм статус обязателен.\nКупи его и возвращайся! /start"
        )
        return ConversationHandler.END
    ctx.user_data["prime"] = "Есть ✅"
    await update.callback_query.message.reply_text(
        "Шаг 4/6 — Сколько у тебя *часов* в CS2? (нужно минимум 100)",
        parse_mode="Markdown",
    )
    return ASK_HOURS


async def ask_hours(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("⚠️ Введи количество часов числом, например: 250")
        return ASK_HOURS
    hours = int(text)
    if hours < 100:
        await update.message.reply_text(
            f"😔 У тебя {hours} ч — нужно минимум 100.\n"
            "Наиграй ещё и возвращайся! /start"
        )
        return ConversationHandler.END
    ctx.user_data["hours"] = text
    await update.message.reply_text(
        "Шаг 5/6 — Сколько часов в день ты готов играть?", parse_mode="Markdown",
    )
    return ASK_DAILY


async def ask_daily(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.isdigit() or int(text) == 0:
        await update.message.reply_text("⚠️ Введи число часов, например: 3")
        return ASK_DAILY
    ctx.user_data["daily"] = text + " ч/день"
    kb = [
        [InlineKeyboardButton("✅ Да, поставлю", callback_data="nick_yes")],
        [InlineKeyboardButton("🤔 Подумаю",      callback_data="nick_maybe")],
    ]
    await update.message.reply_text(
        "Шаг 6/6 — Готов ли ты поставить *тег ❥VP* и аватарку клана?",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb),
    )
    return ASK_NICK


async def ask_nick(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    answer = "Да ✅" if update.callback_query.data == "nick_yes" else "Пока не уверен 🤔"
    ctx.user_data["nick"] = answer

    global app_counter
    app_counter += 1
    ctx.user_data["id"]      = app_counter
    ctx.user_data["user_id"] = update.callback_query.from_user.id

    preview = application_text(ctx.user_data)
    kb = [
        [InlineKeyboardButton("✅ Отправить", callback_data="confirm_yes")],
        [InlineKeyboardButton("❌ Отменить",  callback_data="confirm_no")],
    ]
    await update.callback_query.message.reply_text(
        f"📋 *Проверь свою заявку:*\n\n{preview}\n\nВсё верно?",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb),
    )
    return ASK_CONFIRM


async def confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    if update.callback_query.data == "confirm_no":
        await update.callback_query.message.reply_text("❌ Заявка отменена. /start")
        ctx.user_data.clear()
        return ConversationHandler.END

    members, limit, free = await get_slots_info(ctx.bot)
    if free is not None and free <= 0:
        await update.callback_query.message.reply_text(
            "😔 *Пока ты заполнял анкету — последнее место заняли!*\n\n"
            "Приходи в другой раз 🎮",
            parse_mode="Markdown",
        )
        ctx.user_data.clear()
        return ConversationHandler.END

    data = dict(ctx.user_data)
    applications[data["id"]] = data

    await update.callback_query.message.reply_text(
        "✅ *Заявка отправлена!*\n\nОжидай ответа от администратора 🎮",
        parse_mode="Markdown",
    )

    members, limit, free = await get_slots_info(ctx.bot)
    slots_info = slots_line(members, limit, free)
    kb = [[
        InlineKeyboardButton("✅ Принять",   callback_data=f"admin_accept_{data['id']}"),
        InlineKeyboardButton("❌ Отклонить", callback_data=f"admin_reject_{data['id']}"),
    ]]
    await notify_all_admins(
        ctx.bot,
        f"🔔 *НОВАЯ ЗАЯВКА!*\n\n"
        f"{application_text(data, status='⏳ Новая')}\n\n"
        f"📊 {slots_info}",
        reply_markup=InlineKeyboardMarkup(kb),
    )

    ctx.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    # Также сбрасываем pending_reject если был
    pending_reject.pop(update.effective_user.id, None)
    await update.message.reply_text(
        "❌ Отменено. /start — начать заново.",
        reply_markup=ReplyKeyboardRemove(),
    )
    ctx.user_data.clear()
    return ConversationHandler.END


# ────────────────────────────────────────────────────────────
#  РЕШЕНИЕ АДМИНА — ПРИНЯТЬ / ОТКЛОНИТЬ
# ────────────────────────────────────────────────────────────

async def admin_decision(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        await query.answer("⛔ Нет доступа", show_alert=True)
        return

    parts  = query.data.split("_")
    action = parts[1]
    app_id = int(parts[2])

    data = applications.get(app_id)
    if not data:
        await query.edit_message_text("⚠️ Заявка не найдена (уже обработана?).")
        return

    if action == "accept":
        # ── Принять ──
        user_id = data["user_id"]
        try:
            await ctx.bot.send_message(
                chat_id=user_id,
                text=(
                    "🎉 *Поздравляем! Твоя заявка в клан ❥VP одобрена!*\n\n"
                    "Добро пожаловать в команду 🔥\n\n"
                    f"👉 Вступай в нашу группу: {GROUP_LINK}"
                ),
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"Не удалось написать пользователю {user_id}: {e}")
            await query.message.reply_text(
                f"⚠️ Не удалось написать пользователю.\nUser ID: `{user_id}`",
                parse_mode="Markdown",
            )

        await query.edit_message_text(
            f"📋 *ЗАЯВКА ОБРАБОТАНА*\n\n"
            f"{application_text(data, status='✅ Принята')}",
            parse_mode="Markdown",
        )
        del applications[app_id]

    else:
        # ── Отклонить — спрашиваем причину ──
        pending_reject[query.from_user.id] = app_id
        kb = [[InlineKeyboardButton(
            "⏭ Без причины", callback_data=f"admin_noreason_{app_id}"
        )]]
        await query.edit_message_text(
            f"📋 *ЗАЯВКА #{app_id}*\n\n"
            f"{application_text(data)}\n\n"
            f"✍️ Напиши причину отказа (или нажми «Без причины»):",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb),
        )


async def admin_noreason(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Отклонить без указания причины."""
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        await query.answer("⛔ Нет доступа", show_alert=True)
        return

    app_id = int(query.data.split("_")[2])
    pending_reject.pop(query.from_user.id, None)
    await _do_reject(ctx.bot, query, app_id, reason=None)


async def admin_reject_reason(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Получаем текст причины от админа."""
    admin_id = update.effective_user.id
    if not is_admin(admin_id):
        return
    app_id = pending_reject.get(admin_id)
    if app_id is None:
        return   # не ждём причины — игнорируем

    reason = update.message.text.strip()
    pending_reject.pop(admin_id, None)
    await _do_reject(ctx.bot, update, app_id, reason=reason)


async def _do_reject(bot, source, app_id: int, reason: str | None) -> None:
    """Финальный отказ: уведомляем пользователя и обновляем сообщение у обоих админов."""
    data = applications.get(app_id)
    if not data:
        return

    user_id = data["user_id"]
    reason_line = f"\n\n📝 *Причина:* {reason}" if reason else ""

    try:
        await bot.send_message(
            chat_id=user_id,
            text=(
                "😔 *Твоя заявка в клан ❥VP была отклонена.*\n\n"
                "Не расстраивайся — продолжай играть и попробуй снова! 💪"
                f"{reason_line}"
            ),
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"Не удалось написать пользователю {user_id}: {e}")

    status_text = "❌ Отклонена" + (f" — {reason}" if reason else "")
    result_text = (
        f"📋 *ЗАЯВКА ОБРАБОТАНА*\n\n"
        f"{application_text(data, status=status_text)}"
    )

    # Обновляем у обоих админов
    if hasattr(source, "edit_message_text"):
        # callback_query
        try:
            await source.edit_message_text(result_text, parse_mode="Markdown")
        except Exception:
            pass
        # второму админу — новое сообщение
        for aid in ADMIN_IDS:
            if aid != source.from_user.id:
                try:
                    await bot.send_message(
                        chat_id=aid, text=result_text, parse_mode="Markdown"
                    )
                except Exception as e:
                    logger.error(f"Не удалось уведомить админа {aid}: {e}")
    else:
        # message (текст причины)
        try:
            await source.reply_text(result_text, parse_mode="Markdown")
        except Exception:
            pass
        for aid in ADMIN_IDS:
            if aid != source.from_user.id:
                try:
                    await bot.send_message(
                        chat_id=aid, text=result_text, parse_mode="Markdown"
                    )
                except Exception as e:
                    logger.error(f"Не удалось уведомить админа {aid}: {e}")

    del applications[app_id]


# ────────────────────────────────────────────────────────────
#  КОМАНДЫ ДЛЯ АДМИНОВ
# ────────────────────────────────────────────────────────────

async def cmd_setlimit(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Нет доступа.")
        return ConversationHandler.END
    await update.message.reply_text(
        f"🔢 Текущая планка набора: *{slot_limit}* чел.\n\n"
        "Введи новое максимальное количество участников:",
        parse_mode="Markdown",
    )
    return WAIT_LIMIT


async def receive_limit(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    global slot_limit
    text = update.message.text.strip()
    if not text.isdigit() or int(text) < 1:
        await update.message.reply_text("⚠️ Введи целое положительное число.")
        return WAIT_LIMIT
    slot_limit = int(text)
    members, limit, free = await get_slots_info(ctx.bot)
    slots_info = slots_line(members, limit, free)
    msg = f"✅ Планка набора обновлена до *{slot_limit}* чел.\n\n{slots_info}"
    # Уведомляем обоих админов
    for aid in ADMIN_IDS:
        if aid != update.effective_user.id:
            try:
                await ctx.bot.send_message(
                    chat_id=aid,
                    text=f"🔔 Планка набора изменена на *{slot_limit}* чел.\n\n{slots_info}",
                    parse_mode="Markdown",
                )
            except Exception:
                pass
    await update.message.reply_text(msg, parse_mode="Markdown")
    return ConversationHandler.END


async def cmd_slots(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    members, limit, free = await get_slots_info(ctx.bot)
    slots_info = slots_line(members, limit, free)
    if free is None:
        note = "\n\n⚠️ Добавь бота в группу как администратора."
    elif free <= 0:
        note = "\n\n🔴 *Набор закрыт* — все места заняты."
    else:
        note = "\n\n🟢 *Набор открыт* — подай заявку через /start"
    await update.message.reply_text(
        f"📊 *Статистика набора ❥VP*\n\n{slots_info}{note}",
        parse_mode="Markdown",
    )


async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(
        "🛠 *Команды администратора:*\n\n"
        "/setlimit — установить планку набора\n"
        "/slots — посмотреть статистику мест\n"
        "/admin — эта справка\n"
        "/cancel — отменить текущий ввод\n\n"
        "💡 *Как работает отказ с причиной:*\n"
        "Нажми «❌ Отклонить» → напиши причину текстом → бот отправит её кандидату.\n"
        "Или нажми «Без причины» — тогда причина не указывается.\n\n"
        "⚠️ Бот должен быть добавлен в группу как *администратор*!",
        parse_mode="Markdown",
    )


# ────────────────────────────────────────────────────────────
#  ЗАПУСК
# ────────────────────────────────────────────────────────────

def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    # Заявки
    apply_conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CallbackQueryHandler(apply_callback, pattern="^apply$"),
        ],
        states={
            ASK_NAME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_name)],
            ASK_AGE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_age)],
            ASK_PRIME:   [CallbackQueryHandler(ask_prime, pattern="^prime_")],
            ASK_HOURS:   [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_hours)],
            ASK_DAILY:   [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_daily)],
            ASK_NICK:    [CallbackQueryHandler(ask_nick, pattern="^nick_")],
            ASK_CONFIRM: [CallbackQueryHandler(confirm, pattern="^confirm_")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    # Установка планки
    setlimit_conv = ConversationHandler(
        entry_points=[CommandHandler("setlimit", cmd_setlimit)],
        states={
            WAIT_LIMIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_limit)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(apply_conv)
    app.add_handler(setlimit_conv)

    # Кнопки решений (принять/отклонить/без причины)
    app.add_handler(
        CallbackQueryHandler(admin_decision, pattern="^admin_(accept|reject)_\\d+$")
    )
    app.add_handler(
        CallbackQueryHandler(admin_noreason, pattern="^admin_noreason_\\d+$")
    )

    # Текст причины отказа от админа (в личке с ботом)
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
            admin_reject_reason,
        ),
        group=1,
    )

    app.add_handler(CommandHandler("slots", cmd_slots))
    app.add_handler(CommandHandler("admin", cmd_admin))

    # Запоминаем group_chat_id
    app.add_handler(
        MessageHandler(filters.ChatType.GROUPS, track_group), group=99
    )

    logger.info("❥VP Clan Bot запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

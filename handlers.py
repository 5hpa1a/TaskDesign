from datetime import datetime
import asyncio
import re
import html
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InputMediaPhoto
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramRetryAfter

import config
import database as db
from states import RegistrationState, TaskCreationState, TaskEditState
from keyboards import (
    get_main_menu_keyboard,
    get_reference_input_keyboard,
    get_task_confirmation_keyboard,
    get_task_take_keyboard,
    get_task_taken_placeholder,
    get_designer_task_control_keyboard,
    get_creator_confirmation_keyboard,
    get_user_task_item_keyboard,
)

router = Router()

DESIGNER_TITLES = ["дизайнер", "арт-директор", "head of design"]

# Хранилище ID сообщений последнего вызова «Мои задачи» заказчика
user_my_tasks_messages: dict[int, list[int]] = {}

# Хранилище ID сообщений вызова «Мои задачи в работе» дизайнера (включая заголовок)
user_designer_tasks_messages: dict[int, list[int]] = {}

# Хранилище сообщений ввода команд пользователя
user_last_command_message: dict[int, int] = {}

# Хранилище фоновых асинхронных уведомлений (удаляются при нажатии пользователем любой кнопки в боте)
pending_async_notices: dict[int, list[int]] = {}


def is_designer_position(position: str | None) -> bool:
    if not position:
        return False
    return any(title in position.lower() for title in DESIGNER_TITLES)


def parse_deadline(text: str) -> tuple[datetime | None, str]:
    now = datetime.now()
    clean_text = text.strip()
    formats = [
        "%d.%m.%Y %H:%M", "%d.%m.%Y %H", "%d.%m %H:%M",
        "%d-%m-%Y %H:%M", "%d/%m/%Y %H:%M", "%d.%m",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(clean_text, fmt)
            if dt.year == 1900:
                dt = dt.replace(year=now.year)
            return dt, clean_text
        except ValueError:
            continue

    match = re.search(r'(\d{1,2})[./\-](\d{1,2})(?:[./\-](\d{2,4}))?(?:\s+(\d{1,2}):(\d{2}))?', clean_text)
    if match:
        day, month, year, hour, minute = match.groups()
        yr = int(year) if year else now.year
        if yr < 100:
            yr += 2000
        hr = int(hour) if hour else 18
        mn = int(minute) if minute else 0
        try:
            return datetime(yr, int(month), int(day), hr, mn), clean_text
        except ValueError:
            pass

    return None, clean_text


def calculate_time_left(deadline_dt_str: str | None, raw_deadline: str) -> str:
    if not deadline_dt_str:
        dt, _ = parse_deadline(raw_deadline)
    else:
        try:
            dt = datetime.fromisoformat(deadline_dt_str)
        except ValueError:
            dt, _ = parse_deadline(raw_deadline)

    if not dt:
        return "Не указано"

    diff = dt - datetime.now()
    if diff.total_seconds() <= 0:
        return "⚠️ Дедлайн прошёл"

    days = diff.days
    hours = diff.seconds // 3600
    return f"{days} д. {hours} ч."


async def check_membership(bot: Bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(config.MAIN_CHAT_ID, user_id)
        return member.status not in ("left", "kicked")
    except Exception:
        return False


def build_user_link(name: str, username: str | None, user_id: int) -> str:
    safe_name = html.escape(name)
    if username:
        return f'<a href="https://t.me/{username}">{safe_name}</a>'
    return f'<a href="tg://user?id={user_id}">{safe_name}</a>'


def format_task_text(task_data: dict, creator_link: str) -> str:
    creator_position = html.escape(task_data.get("creator_position") or "Сотрудник")
    created_at = task_data.get("created_at") or datetime.now().strftime("%d.%m.%Y %H:%M")
    time_left = calculate_time_left(task_data.get("deadline_dt"), task_data.get("deadline", ""))

    ref_data = task_data.get("reference_data")
    ref_type = task_data.get("reference_type")
    photos = task_data.get("reference_photos", [])
    docs = task_data.get("reference_docs", [])

    parts = []
    if photos:
        parts.append(f"Фото: {len(photos)} шт.")
    if docs:
        parts.append(f"Файлы: {len(docs)} шт.")
    attachments_str = ", ".join(parts)

    if attachments_str:
        if ref_data:
            ref_text = f"Вложения ({attachments_str}) + описание/ссылки: {html.escape(ref_data)}"
        else:
            ref_text = f"Вложения ({attachments_str})"
    elif ref_type == "text" and ref_data:
        ref_text = html.escape(ref_data)
    else:
        ref_text = "Отсутствуют"

    escaped_description = html.escape(task_data.get('description', ''))

    return (
        f"📋 <b>Новая задача!</b>\n\n"
        f"👤 <b>Заказчик:</b> {creator_link} ({creator_position})\n"
        f"📅 <b>Дата постановки:</b> {created_at}\n\n"
        f"📌 <b>Тема:</b> {html.escape(task_data['theme'])}\n"
        f"📐 <b>Форматы:</b> {html.escape(task_data['formats'])}\n\n"
        f"📝 <b>ТЗ:</b>\n"
        f"<blockquote expandable>{escaped_description}</blockquote>\n\n"
        f"⏰ <b>Дедлайн:</b> {html.escape(task_data['deadline'])}\n"
        f"⏳ <b>До дедлайна осталось:</b> <code>{time_left}</code>\n\n"
        f"🔗 <b>Референсы:</b> {ref_text}\n\n"
    )


def format_user_card_text(t: dict) -> str:
    status_names = {
        "pending": "⏳ Ищет дизайнера (в чате)",
        "in_progress": "🛠 В работе у дизайнера",
        "awaiting_confirmation": "🧐 Ожидает вашего подтверждения"
    }
    designer_info = f" (Дизайнер: {html.escape(t['designer_name'])})" if t.get("designer_name") else ""
    time_left = calculate_time_left(t.get("deadline_dt"), t.get("deadline", ""))
    escaped_desc = html.escape(t.get("description", "—"))
    return (
        f"<b>Задача #{t['id']}: {html.escape(t['theme'])}</b>\n"
        f"<b>Статус:</b> {status_names.get(t['status'], t['status'])}{designer_info}\n"
        f"<b>Дедлайн:</b> {html.escape(t['deadline'])} (осталось: <code>{time_left}</code>)\n"
        f"<b>Форматы:</b> {html.escape(t['formats'])}\n"
        f"<b>ТЗ:</b>\n<blockquote expandable>{escaped_desc}</blockquote>\n"
    )


async def clear_user_pending_notices(bot: Bot, user_id: int):
    """Удаляет фоновые асинхронные уведомления, когда пользователь снова активен в боте."""
    if user_id in pending_async_notices:
        for mid in pending_async_notices[user_id]:
            try:
                await bot.delete_message(chat_id=user_id, message_id=mid)
            except Exception:
                pass
        pending_async_notices[user_id] = []


async def handle_user_command_cleanup(bot: Bot, chat_id: int, user_id: int, current_message_id: int):
    """Очищает предыдущую команду пользователя и фоновые уведомления."""
    await clear_user_pending_notices(bot, user_id)
    prev_msg_id = user_last_command_message.get(user_id)
    if prev_msg_id and prev_msg_id != current_message_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=prev_msg_id)
        except Exception:
            pass
    user_last_command_message[user_id] = current_message_id


async def delete_later(bot: Bot, chat_id: int, message_id: int, delay: int = 5):
    """Фоновое удаление сообщений через заданный интервал (5-10 сек)."""
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


async def delete_task_messages_from_group(bot: Bot, task_id: int):
    msg_ids = await db.get_task_messages_ids(task_id)
    for mid in msg_ids:
        try:
            await bot.delete_message(config.MAIN_CHAT_ID, mid)
            await asyncio.sleep(0.1)
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                await bot.delete_message(config.MAIN_CHAT_ID, mid)
            except Exception:
                pass
        except Exception:
            pass


async def post_task_to_chat(bot: Bot, task_payload: dict, task_id: int):
    creator_link = build_user_link(task_payload["creator_name"], task_payload.get("creator_username"), task_payload["creator_id"])
    task_card_text = format_task_text(task_payload, creator_link)

    photos = task_payload.get("reference_photos", [])
    docs = task_payload.get("reference_docs", [])
    all_ids = []

    if photos:
        if len(photos) > 1:
            media = [InputMediaPhoto(media=photos[0], caption=task_card_text)]
            for pid in photos[1:]:
                media.append(InputMediaPhoto(media=pid))
            sent_messages = await bot.send_media_group(chat_id=config.MAIN_CHAT_ID, media=media)
            all_ids.extend([m.message_id for m in sent_messages])
            
            for doc_id in docs:
                dm = await bot.send_document(chat_id=config.MAIN_CHAT_ID, document=doc_id)
                all_ids.append(dm.message_id)

            btn_msg = await bot.send_message(
                chat_id=config.MAIN_CHAT_ID,
                text=f"👆 Задача #{task_id}: нажмите кнопку ниже, чтобы взять в работу",
                reply_markup=get_task_take_keyboard(task_id)
            )
            all_ids.append(btn_msg.message_id)
            await db.update_task_group_messages(task_id, config.MAIN_CHAT_ID, all_ids)
            return
        else:
            sent_msg = await bot.send_photo(
                chat_id=config.MAIN_CHAT_ID,
                photo=photos[0],
                caption=task_card_text,
                reply_markup=get_task_take_keyboard(task_id)
            )
            all_ids.append(sent_msg.message_id)
            for doc_id in docs:
                dm = await bot.send_document(chat_id=config.MAIN_CHAT_ID, document=doc_id)
                all_ids.append(dm.message_id)
            await db.update_task_group_messages(task_id, config.MAIN_CHAT_ID, all_ids)
            return

    if docs:
        sent_msg = await bot.send_document(
            chat_id=config.MAIN_CHAT_ID,
            document=docs[0],
            caption=task_card_text,
            reply_markup=get_task_take_keyboard(task_id)
        )
        all_ids.append(sent_msg.message_id)
        for doc_id in docs[1:]:
            dm = await bot.send_document(chat_id=config.MAIN_CHAT_ID, document=doc_id)
            all_ids.append(dm.message_id)
        await db.update_task_group_messages(task_id, config.MAIN_CHAT_ID, all_ids)
        return

    sent_msg = await bot.send_message(
        chat_id=config.MAIN_CHAT_ID,
        text=task_card_text,
        reply_markup=get_task_take_keyboard(task_id),
        disable_web_page_preview=True
    )
    await db.update_task_group_messages(task_id, config.MAIN_CHAT_ID, [sent_msg.message_id])


async def track_msg(state: FSMContext, message_id: int):
    data = await state.get_data()
    cleanup = data.get("cleanup_messages", [])
    cleanup.append(message_id)
    await state.update_data(cleanup_messages=cleanup)


async def track_validation_msg(state: FSMContext, message_id: int):
    data = await state.get_data()
    val_msgs = data.get("validation_messages", [])
    val_msgs.append(message_id)
    await state.update_data(validation_messages=val_msgs)


async def clear_validation_msgs(bot: Bot, chat_id: int, state: FSMContext):
    data = await state.get_data()
    for mid in data.get("validation_messages", []):
        try:
            await bot.delete_message(chat_id=chat_id, message_id=mid)
        except Exception:
            pass
    await state.update_data(validation_messages=[])


async def cleanup_fsm_messages(bot: Bot, chat_id: int, state: FSMContext):
    data = await state.get_data()
    for mid in data.get("cleanup_messages", []):
        try:
            await bot.delete_message(chat_id=chat_id, message_id=mid)
        except Exception:
            pass
    for mid in data.get("validation_messages", []):
        try:
            await bot.delete_message(chat_id=chat_id, message_id=mid)
        except Exception:
            pass


# ========================================================
# Регистрация и меню
# ========================================================

@router.message(F.chat.type == "private", CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot):
    await handle_user_command_cleanup(bot, message.chat.id, message.from_user.id, message.message_id)

    if not await check_membership(bot, message.from_user.id):
        m = await message.answer("⛔ У вас нет доступа к боту. Вы должны состоять в рабочем чате.")
        asyncio.create_task(delete_later(bot, message.chat.id, m.message_id, 7))
        return

    user = await db.get_user(message.from_user.id)
    if not user:
        sent = await message.answer("👋 Добро пожаловать! Давайте познакомимся.\nВведите ваше <b>Имя и Фамилию</b>:")
        await state.update_data(cleanup_messages=[message.message_id, sent.message_id])
        await state.set_state(RegistrationState.waiting_for_full_name)
    else:
        is_admin_user = config.is_admin(message.from_user.id)
        is_designer_user = is_designer_position(user[2])
        await message.answer(
            f"С возвращением, {user[1]} ({user[2]})!",
            reply_markup=get_main_menu_keyboard(is_admin_user, is_designer_user)
        )


@router.message(RegistrationState.waiting_for_full_name)
async def process_name(message: Message, state: FSMContext, bot: Bot):
    await clear_validation_msgs(bot, message.chat.id, state)
    if not message.text or len(message.text.strip()) < 2:
        val = await message.answer("⚠️ Пожалуйста, введите корректное имя:")
        await track_validation_msg(state, message.message_id)
        await track_validation_msg(state, val.message_id)
        return

    await track_msg(state, message.message_id)
    await state.update_data(full_name=message.text.strip())
    sent = await message.answer(
        "Укажите вашу <b>должность</b> в организации:\n"
        "<i>(Если вы дизайнер, укажите: Дизайнер, Арт-директор или Head of Design)</i>"
    )
    await track_msg(state, sent.message_id)
    await state.set_state(RegistrationState.waiting_for_position)


@router.message(RegistrationState.waiting_for_position)
async def process_position(message: Message, state: FSMContext, bot: Bot):
    await clear_validation_msgs(bot, message.chat.id, state)
    if not message.text:
        val = await message.answer("⚠️ Пожалуйста, введите корректную должность:")
        await track_validation_msg(state, message.message_id)
        await track_validation_msg(state, val.message_id)
        return

    data = await state.get_data()
    position = message.text.strip()
    await db.create_user(
        user_id=message.from_user.id,
        full_name=data["full_name"],
        position=position,
        username=message.from_user.username
    )

    await track_msg(state, message.message_id)
    await cleanup_fsm_messages(bot, message.chat.id, state)
    await state.clear()
    
    is_admin_user = config.is_admin(message.from_user.id)
    is_designer_user = is_designer_position(position)
    sent = await message.answer(
        "✅ Регистрация завершена!",
        reply_markup=get_main_menu_keyboard(is_admin_user, is_designer_user)
    )
    asyncio.create_task(delete_later(bot, message.chat.id, sent.message_id, 7))


# ========================================================
# Просмотр и редактирование задач Заказчиком
# ========================================================

@router.message(F.chat.type == "private", F.text == "📋 Мои задачи")
async def show_my_tasks(message: Message, bot: Bot):
    await handle_user_command_cleanup(bot, message.chat.id, message.from_user.id, message.message_id)

    prev_messages = user_my_tasks_messages.get(message.from_user.id, [])
    for mid in prev_messages:
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=mid)
        except Exception:
            pass
    user_my_tasks_messages[message.from_user.id] = []

    tasks = await db.get_user_tasks(message.from_user.id)
    if not tasks:
        empty_msg = await message.answer("У вас нет активных задач в работе или ожидании.")
        asyncio.create_task(delete_later(bot, message.chat.id, empty_msg.message_id, 7))
        return

    new_list_ids = []
    header = await message.answer(f"📋 <b>Ваши активные задачи ({len(tasks)}):</b>")
    new_list_ids.append(header.message_id)

    for t in tasks:
        card = format_user_card_text(dict(t))
        card_msg = await message.answer(card, reply_markup=get_user_task_item_keyboard(t["id"]))
        new_list_ids.append(card_msg.message_id)

    user_my_tasks_messages[message.from_user.id] = new_list_ids


@router.callback_query(F.data.startswith("creator_cancel_"))
async def cancel_task_by_creator(callback: CallbackQuery, bot: Bot):
    await clear_user_pending_notices(bot, callback.from_user.id)
    task_id = int(callback.data.split("_")[2])
    task = await db.get_task(task_id)

    if not task or task["creator_id"] != callback.from_user.id:
        await callback.answer("⛔ Задача не найдена или чужая.", show_alert=True)
        return

    if task["status"] in ("completed", "canceled"):
        await callback.answer("Эта задача уже завершена или отменена.", show_alert=True)
        return

    await db.cancel_task_db(task_id)
    await delete_task_messages_from_group(bot, task_id)

    if task["designer_id"]:
        try:
            notice = await bot.send_message(
                chat_id=task["designer_id"],
                text=f"🚫 Заказчик отменил(-а) задачу #{task_id} («{html.escape(task['theme'])}»)."
            )
            pending_async_notices.setdefault(task["designer_id"], []).append(notice.message_id)
        except Exception:
            pass

    await callback.answer("Задача отменена!")
    await callback.message.edit_text(f"❌ <b>Задача #{task_id} («{html.escape(task['theme'])}») отменена.</b>")
    asyncio.create_task(delete_later(bot, callback.message.chat.id, callback.message.message_id, 5))


# Редактирование Дедлайна в "Моих задачах"
@router.callback_query(F.data.startswith("creator_edit_deadline_"))
async def start_edit_deadline(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await clear_user_pending_notices(bot, callback.from_user.id)
    task_id = int(callback.data.split("_")[3])
    task = await db.get_task(task_id)

    if not task or task["creator_id"] != callback.from_user.id:
        await callback.answer("⛔ Задача не найдена или чужая.", show_alert=True)
        return

    if task["status"] in ("completed", "canceled"):
        await callback.answer("Нельзя изменить дедлайн завершенной или отмененной задачи.", show_alert=True)
        return

    await state.set_state(TaskEditState.waiting_for_new_deadline)
    await state.update_data(editing_task_id=task_id, card_message_id=callback.message.message_id)

    await callback.answer()
    prompt = await callback.message.answer(
        f"📅 Введите новый дедлайн для задачи <b>#{task_id}</b> («{html.escape(task['theme'])}»):\n"
        f"<i>Текущий дедлайн: {html.escape(task['deadline'])}</i>\n\n"
        f"Пример: <code>15.11 18:00</code>"
    )
    await state.update_data(prompt_message_id=prompt.message_id)


@router.message(TaskEditState.waiting_for_new_deadline, F.text)
async def process_new_deadline(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    task_id = data.get("editing_task_id")
    card_message_id = data.get("card_message_id")
    prompt_message_id = data.get("prompt_message_id")

    if prompt_message_id:
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=prompt_message_id)
        except Exception:
            pass
    try:
        await message.delete()
    except Exception:
        pass

    if not task_id:
        await state.clear()
        return

    task = await db.get_task(task_id)
    if not task or task["creator_id"] != message.from_user.id:
        await state.clear()
        return

    dt, raw_deadline = parse_deadline(message.text)
    dt_str = dt.isoformat() if dt else None

    await db.update_task_deadline(task_id, raw_deadline, dt_str)
    await state.clear()

    task["deadline"] = raw_deadline
    task["deadline_dt"] = dt_str
    new_card_text = format_user_card_text(task)

    try:
        await bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=card_message_id,
            text=new_card_text,
            reply_markup=get_user_task_item_keyboard(task_id)
        )
    except Exception:
        pass

    confirm_msg = await message.answer(f"✅ Дедлайн задачи #{task_id} изменён на <b>{html.escape(raw_deadline)}</b>!")
    asyncio.create_task(delete_later(bot, message.chat.id, confirm_msg.message_id, 5))

    # Уведомление дизайнеру об изменении дедлайна
    if task["designer_id"]:
        try:
            notice = await bot.send_message(
                chat_id=task["designer_id"],
                text=(
                    f"⏰ <b>Заказчик обновил(-а) дедлайн по задаче #{task_id} («{html.escape(task['theme'])}»)!</b>\n"
                    f"⏳ <b>Новый дедлайн:</b> {html.escape(raw_deadline)}"
                )
            )
            pending_async_notices.setdefault(task["designer_id"], []).append(notice.message_id)
        except Exception:
            pass


# Редактирование ТЗ в "Моих задачах"
@router.callback_query(F.data.startswith("creator_edit_desc_"))
async def start_edit_description(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await clear_user_pending_notices(bot, callback.from_user.id)
    task_id = int(callback.data.split("_")[3])
    task = await db.get_task(task_id)

    if not task or task["creator_id"] != callback.from_user.id:
        await callback.answer("⛔ Задача не найдена или чужая.", show_alert=True)
        return

    if task["status"] in ("completed", "canceled"):
        await callback.answer("Нельзя изменить ТЗ завершенной или отмененной задачи.", show_alert=True)
        return

    await state.set_state(TaskEditState.waiting_for_new_description)
    await state.update_data(editing_task_id=task_id, card_message_id=callback.message.message_id)

    await callback.answer()
    prompt = await callback.message.answer(
        f"📝 Введите <b>новое развёрнутое ТЗ</b> для задачи <b>#{task_id}</b> («{html.escape(task['theme'])}»):"
    )
    await state.update_data(prompt_message_id=prompt.message_id)


@router.message(TaskEditState.waiting_for_new_description, F.text)
async def process_new_description(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    task_id = data.get("editing_task_id")
    card_message_id = data.get("card_message_id")
    prompt_message_id = data.get("prompt_message_id")

    if prompt_message_id:
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=prompt_message_id)
        except Exception:
            pass
    try:
        await message.delete()
    except Exception:
        pass

    if not task_id:
        await state.clear()
        return

    task = await db.get_task(task_id)
    if not task or task["creator_id"] != message.from_user.id:
        await state.clear()
        return

    new_desc = message.text.strip()
    await db.update_task_description(task_id, new_desc)
    await state.clear()

    task["description"] = new_desc
    new_card_text = format_user_card_text(task)

    try:
        await bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=card_message_id,
            text=new_card_text,
            reply_markup=get_user_task_item_keyboard(task_id)
        )
    except Exception:
        pass

    confirm_msg = await message.answer(f"✅ ТЗ для задачи #{task_id} успешно обновлено!")
    asyncio.create_task(delete_later(bot, message.chat.id, confirm_msg.message_id, 5))

    # Уведомление дизайнеру об изменении ТЗ
    if task["designer_id"]:
        try:
            notice = await bot.send_message(
                chat_id=task["designer_id"],
                text=(
                    f"📝 <b>Заказчик изменил(-а) ТЗ по задаче #{task_id} («{html.escape(task['theme'])}»)!</b>\n\n"
                    f"<b>Новое ТЗ:</b>\n"
                    f"<blockquote expandable>{html.escape(new_desc)}</blockquote>"
                )
            )
            pending_async_notices.setdefault(task["designer_id"], []).append(notice.message_id)
        except Exception:
            pass


# ========================================================
# Просмотр задач Дизайнером
# ========================================================

@router.message(F.chat.type == "private", F.text == "💼 Мои задачи в работе")
async def show_designer_tasks(message: Message, bot: Bot):
    await handle_user_command_cleanup(bot, message.chat.id, message.from_user.id, message.message_id)

    user = await db.get_user(message.from_user.id)
    if not user or not is_designer_position(user[2]):
        await message.answer("⛔ Эта функция доступна только дизайнерам.")
        return

    prev_messages = user_designer_tasks_messages.get(message.from_user.id, [])
    for mid in prev_messages:
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=mid)
        except Exception:
            pass
    user_designer_tasks_messages[message.from_user.id] = []

    tasks = await db.get_designer_tasks(message.from_user.id)
    if not tasks:
        empty_msg = await message.answer("У вас нет текущих задач в работе.")
        asyncio.create_task(delete_later(bot, message.chat.id, empty_msg.message_id, 7))
        return

    status_names = {
        "in_progress": "🛠 В процессе выполнения",
        "awaiting_confirmation": "⏳ На проверке у заказчика"
    }

    new_list_ids = []
    header = await message.answer(f"💼 <b>Ваши текущие задачи ({len(tasks)}):</b>")
    new_list_ids.append(header.message_id)

    for t in tasks:
        time_left = calculate_time_left(t["deadline_dt"], t["deadline"])
        card = (
            f"<b>Задача #{t['id']}: {html.escape(t['theme'])}</b>\n"
            f"<b>Заказчик:</b> {html.escape(t['creator_name'])}\n"
            f"<b>Дедлайн:</b> {html.escape(t['deadline'])} (осталось: <code>{time_left}</code>)\n"
            f"<b>Статус:</b> {status_names.get(t['status'], t['status'])}\n"
            f"<b>Форматы:</b> {html.escape(t['formats'])}\n"
        )
        if t["status"] == "in_progress":
            card_msg = await message.answer(card, reply_markup=get_designer_task_control_keyboard(t["id"]))
        else:
            card_msg = await message.answer(card)
        new_list_ids.append(card_msg.message_id)

    user_designer_tasks_messages[message.from_user.id] = new_list_ids


# ========================================================
# Создание задачи
# ========================================================

@router.message(F.chat.type == "private", F.text == "➕ Создать задачу")
async def start_task_creation(message: Message, state: FSMContext, bot: Bot):
    await handle_user_command_cleanup(bot, message.chat.id, message.from_user.id, message.message_id)

    if not await check_membership(bot, message.from_user.id):
        m = await message.answer("⛔ Вы не являетесь участником рабочего чата.")
        asyncio.create_task(delete_later(bot, message.chat.id, m.message_id, 7))
        return

    user = await db.get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала пройдите регистрацию. Отправьте /start")
        return

    await state.clear()
    sent = await message.answer("Введите <b>тему задачи</b> (краткое название):")
    await state.update_data(cleanup_messages=[message.message_id, sent.message_id])
    await state.set_state(TaskCreationState.waiting_for_theme)


@router.message(TaskCreationState.waiting_for_theme)
async def task_theme(message: Message, state: FSMContext, bot: Bot):
    await clear_validation_msgs(bot, message.chat.id, state)
    await track_msg(state, message.message_id)
    await state.update_data(theme=message.text)
    sent = await message.answer("Укажите <b>форматы дизайнов</b> (например: 1920x1080, TG-баннер):")
    await track_msg(state, sent.message_id)
    await state.set_state(TaskCreationState.waiting_for_formats)


@router.message(TaskCreationState.waiting_for_formats)
async def task_formats(message: Message, state: FSMContext, bot: Bot):
    await clear_validation_msgs(bot, message.chat.id, state)
    await track_msg(state, message.message_id)
    await state.update_data(formats=message.text)
    sent = await message.answer("Отправьте <b>полное и развернутое ТЗ</b>:")
    await track_msg(state, sent.message_id)
    await state.set_state(TaskCreationState.waiting_for_description)


@router.message(TaskCreationState.waiting_for_description)
async def task_description(message: Message, state: FSMContext, bot: Bot):
    await clear_validation_msgs(bot, message.chat.id, state)
    await track_msg(state, message.message_id)
    await state.update_data(description=message.text)
    sent = await message.answer("Укажите <b>дедлайн</b> (например: <code>15.11 18:00</code>):")
    await track_msg(state, sent.message_id)
    await state.set_state(TaskCreationState.waiting_for_deadline)


@router.message(TaskCreationState.waiting_for_deadline)
async def task_deadline(message: Message, state: FSMContext, bot: Bot):
    await clear_validation_msgs(bot, message.chat.id, state)
    await track_msg(state, message.message_id)
    dt, raw_text = parse_deadline(message.text)
    dt_str = dt.isoformat() if dt else None
    await state.update_data(deadline=raw_text, deadline_dt=dt_str, reference_photos=[], reference_docs=[])

    sent = await message.answer(
        "Прикрепите <b>референсы и файлы</b>:\n"
        "• Можно прикрепить до <b>5 файлов или фото</b> (по одному).\n"
        "• Можно отправить текстовые ссылки / ссылки на диск, Figma.\n"
        "• Когда закончите отправку файлов, нажмите <b>«Завершить прикрепление»</b>.",
        reply_markup=get_reference_input_keyboard(has_files=False)
    )
    await track_msg(state, sent.message_id)
    await state.set_state(TaskCreationState.waiting_for_references)


@router.message(TaskCreationState.waiting_for_references, F.photo)
async def task_references_photo(message: Message, state: FSMContext, bot: Bot, album: list[Message] | None = None):
    await clear_validation_msgs(bot, message.chat.id, state)
    messages = album if album else [message]
    for msg in messages:
        await track_msg(state, msg.message_id)

    data = await state.get_data()
    photos = data.get("reference_photos", [])
    docs = data.get("reference_docs", [])

    if (len(photos) + len(docs)) >= 5:
        val = await message.answer("⚠️ Уже загружено максимум (5 вложений). Нажмите кнопку «Завершить прикрепление файлов».")
        await track_validation_msg(state, val.message_id)
        return

    for msg in messages:
        if (len(photos) + len(docs)) >= 5:
            break
        if msg.photo:
            photos.append(msg.photo[-1].file_id)

    caption = data.get("reference_data")
    last_caption = next((m.caption.strip() for m in reversed(messages) if m.caption), None)
    if last_caption:
        caption = last_caption

    await state.update_data(reference_type="photo", reference_photos=photos, reference_data=caption)

    total = len(photos) + len(docs)
    sent = await message.answer(
        f"📸 Фото добавлено ({total} из 5 вложений). Отправьте ещё или завершите:",
        reply_markup=get_reference_input_keyboard(has_files=True)
    )
    await track_validation_msg(state, sent.message_id)


@router.message(TaskCreationState.waiting_for_references, F.document)
async def task_references_document(message: Message, state: FSMContext, bot: Bot, album: list[Message] | None = None):
    await clear_validation_msgs(bot, message.chat.id, state)
    messages = album if album else [message]
    for msg in messages:
        await track_msg(state, msg.message_id)

    data = await state.get_data()
    photos = data.get("reference_photos", [])
    docs = data.get("reference_docs", [])

    if (len(photos) + len(docs)) >= 5:
        val = await message.answer("⚠️ Уже загружено максимум (5 вложений). Нажмите кнопку «Завершить прикрепление файлов».")
        await track_validation_msg(state, val.message_id)
        return

    for msg in messages:
        if (len(photos) + len(docs)) >= 5:
            break
        if msg.document:
            docs.append(msg.document.file_id)

    caption = data.get("reference_data")
    last_caption = next((m.caption.strip() for m in reversed(messages) if m.caption), None)
    if last_caption:
        caption = last_caption

    await state.update_data(reference_type="document", reference_docs=docs, reference_data=caption)

    total = len(photos) + len(docs)
    sent = await message.answer(
        f"📄 Файл добавлен ({total} из 5 вложений). Отправьте ещё или завершите:",
        reply_markup=get_reference_input_keyboard(has_files=True)
    )
    await track_validation_msg(state, sent.message_id)


@router.message(TaskCreationState.waiting_for_references, F.text)
async def task_references_text(message: Message, state: FSMContext, bot: Bot):
    await clear_validation_msgs(bot, message.chat.id, state)
    await track_msg(state, message.message_id)
    data = await state.get_data()
    photos = data.get("reference_photos", [])
    docs = data.get("reference_docs", [])

    if photos or docs:
        await state.update_data(reference_data=message.text.strip())
    else:
        await state.update_data(
            reference_type="text",
            reference_photos=[],
            reference_docs=[],
            reference_data=message.text.strip()
        )
    await prompt_task_confirmation(message, state)


@router.callback_query(TaskCreationState.waiting_for_references, F.data == "finish_reference_files")
async def task_references_finish(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await clear_validation_msgs(bot, callback.message.chat.id, state)
    await callback.answer()
    await prompt_task_confirmation(callback.message, state)


@router.callback_query(TaskCreationState.waiting_for_references, F.data == "skip_reference")
async def task_references_skip(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await clear_validation_msgs(bot, callback.message.chat.id, state)
    await callback.answer()
    data = await state.get_data()
    if not data.get("reference_photos") and not data.get("reference_docs"):
        await state.update_data(reference_type="none", reference_photos=[], reference_docs=[], reference_data=None)
    await prompt_task_confirmation(callback.message, state)


async def prompt_task_confirmation(message: Message, state: FSMContext):
    data = await state.get_data()
    time_left = calculate_time_left(data.get("deadline_dt"), data.get("deadline", ""))

    photos = data.get("reference_photos", [])
    docs = data.get("reference_docs", [])
    ref_data = data.get("reference_data")
    
    parts = []
    if photos:
        parts.append(f"Фото: {len(photos)} шт.")
    if docs:
        parts.append(f"Файлы: {len(docs)} шт.")
    attachments_str = ", ".join(parts)

    if attachments_str:
        ref_display = f"{attachments_str}" + (f" + {html.escape(ref_data)}" if ref_data else "")
    elif ref_data:
        ref_display = html.escape(ref_data)
    else:
        ref_display = "Нет"

    escaped_description = html.escape(data.get('description', ''))

    text = (
        "🧐 <b>Проверьте правильность введенных данных:</b>\n\n"
        f"📌 <b>Тема:</b> {html.escape(data.get('theme', ''))}\n"
        f"📐 <b>Форматы:</b> {html.escape(data.get('formats', ''))}\n\n"
        f"📝 <b>ТЗ:</b>\n"
        f"<blockquote expandable>{escaped_description}</blockquote>\n\n"
        f"⏰ <b>Дедлайн:</b> {html.escape(data.get('deadline', ''))}\n"
        f"⏳ <b>До дедлайна:</b> {time_left}\n\n"
        f"🔗 <b>Референсы:</b> {ref_display}\n\n"
        "Всё верно?"
    )
    sent = await message.answer(text, reply_markup=get_task_confirmation_keyboard())
    await track_msg(state, sent.message_id)
    await state.set_state(TaskCreationState.waiting_for_confirmation)


# Редактирование ТЗ прямо на шаге подтверждения создания
@router.callback_query(TaskCreationState.waiting_for_confirmation, F.data == "confirm_edit_desc")
async def creation_edit_desc_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    sent = await callback.message.answer("📝 Введите <b>исправленное ТЗ</b>:")
    await track_msg(state, sent.message_id)
    await state.set_state(TaskCreationState.waiting_for_desc_edit)


@router.message(TaskCreationState.waiting_for_desc_edit, F.text)
async def creation_edit_desc_process(message: Message, state: FSMContext):
    await track_msg(state, message.message_id)
    await state.update_data(description=message.text.strip())
    await prompt_task_confirmation(message, state)


@router.callback_query(TaskCreationState.waiting_for_confirmation, F.data == "confirm_task_no")
async def cancel_task_creation(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await callback.answer("Создание задачи отменено.")
    await cleanup_fsm_messages(bot, callback.from_user.id, state)
    await state.clear()
    msg = await callback.message.answer("❌ Создание задачи отменено.")
    asyncio.create_task(delete_later(bot, callback.message.chat.id, msg.message_id, 5))


@router.callback_query(TaskCreationState.waiting_for_confirmation, F.data == "confirm_task_yes")
async def confirm_and_send_task(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await callback.answer()
    data = await state.get_data()
    user = await db.get_user(callback.from_user.id)

    creator_name = user[1] if user else callback.from_user.full_name
    creator_position = user[2] if user else "Сотрудник"

    task_payload = {
        "creator_id": callback.from_user.id,
        "creator_name": creator_name,
        "creator_username": callback.from_user.username,
        "creator_position": creator_position,
        "theme": data["theme"],
        "formats": data["formats"],
        "description": data["description"],
        "deadline": data["deadline"],
        "deadline_dt": data.get("deadline_dt"),
        "reference_type": data.get("reference_type"),
        "reference_photos": data.get("reference_photos", []),
        "reference_docs": data.get("reference_docs", []),
        "reference_data": data.get("reference_data"),
        "created_at": datetime.now().strftime("%d.%m.%Y %H:%M")
    }

    task_id = await db.create_task(task_payload)
    await cleanup_fsm_messages(bot, callback.from_user.id, state)
    await state.clear()

    await post_task_to_chat(bot, task_payload, task_id)
    confirm = await callback.message.answer(f"🚀 <b>Задача #{task_id} («{html.escape(task_payload['theme'])}») опубликована!</b>")
    asyncio.create_task(delete_later(bot, callback.message.chat.id, confirm.message_id, 7))


# ========================================================
# Взятие задачи в работу
# ========================================================

@router.callback_query(F.data.startswith("take_task_"))
async def take_task_handler(callback: CallbackQuery, bot: Bot):
    await clear_user_pending_notices(bot, callback.from_user.id)
    task_id = int(callback.data.split("_")[2])
    designer_id = callback.from_user.id

    designer_user = await db.get_user(designer_id)
    if not designer_user or not is_designer_position(designer_user[2]):
        await callback.answer(
            "⛔ Брать задачи могут только сотрудники с должностью «Дизайнер», «Арт-директор» или «Head of Design»!",
            show_alert=True
        )
        return

    designer_display_name = designer_user[1]
    designer_username = callback.from_user.username

    success = await db.assign_task_to_designer(task_id, designer_id, designer_display_name)
    if not success:
        await callback.answer("Увы, задачу уже взял(-а) другой дизайнер или она отменена!", show_alert=True)
        return

    await callback.answer("Вы взяли задачу в работу!")

    try:
        taken_label = f"@{designer_username}" if designer_username else designer_display_name
        await callback.message.edit_reply_markup(
            reply_markup=get_task_taken_placeholder(taken_label)
        )
    except Exception:
        pass

    task = await db.get_task(task_id)

    # 1. Отправляем карточку задачи дизайнеру в ЛС
    creator_link = build_user_link(task["creator_name"], task.get("creator_username"), task["creator_id"])
    task_info = format_task_text(task, creator_link)
    pm_text = (
        f"🎯 <b>Вы взяли задачу #{task_id}:</b>\n\n"
        f"{task_info}\n\n"
        "Когда закончите работу, нажмите «Выполнено». Если передумали — «Отказаться»."
    )

    try:
        await bot.send_message(
            chat_id=designer_id,
            text=pm_text,
            reply_markup=get_designer_task_control_keyboard(task_id),
            disable_web_page_preview=True
        )
    except Exception:
        pass

    # 2. Уведомление Заказчику с кликабельной гиперссылкой на дизайнера
    designer_link = build_user_link(designer_display_name, designer_username, designer_id)
    try:
        creator_notice = await bot.send_message(
            chat_id=task["creator_id"],
            text=(
                f"🎨 Вашу задачу <b>#{task_id}</b> («{html.escape(task['theme'])}») взял(-а) в работу дизайнер {designer_link}!"
            ),
            disable_web_page_preview=True
        )
        pending_async_notices.setdefault(task["creator_id"], []).append(creator_notice.message_id)
    except Exception:
        pass


# ========================================================
# Отказ, сдача и подтверждение
# ========================================================

@router.callback_query(F.data.startswith("designer_reject_"))
async def designer_reject_task(callback: CallbackQuery, bot: Bot):
    await clear_user_pending_notices(bot, callback.from_user.id)
    task_id = int(callback.data.split("_")[2])
    task = await db.get_task(task_id)

    if not task or task["designer_id"] != callback.from_user.id:
        await callback.answer("Задача не найдена или не принадлежит вам.", show_alert=True)
        return

    await db.free_task_from_designer(task_id)
    await callback.answer("Вы отказались от задачи.")

    await callback.message.edit_text(f"❌ Вы отказались от задачи #{task_id}.")
    asyncio.create_task(delete_later(bot, callback.message.chat.id, callback.message.message_id, 5))

    await delete_task_messages_from_group(bot, task_id)
    await post_task_to_chat(bot, task, task_id)


@router.callback_query(F.data.startswith("designer_done_"))
async def designer_done_task(callback: CallbackQuery, bot: Bot):
    await clear_user_pending_notices(bot, callback.from_user.id)
    task_id = int(callback.data.split("_")[2])
    task = await db.get_task(task_id)

    if not task or task["designer_id"] != callback.from_user.id:
        await callback.answer("Ошибка доступа.", show_alert=True)
        return

    await db.set_task_awaiting_confirmation(task_id)
    await callback.answer("Отправлено на подтверждение!")

    await callback.message.edit_text(f"⏳ Задача #{task_id} отправлена заказчику на проверку.")
    asyncio.create_task(delete_later(bot, callback.message.chat.id, callback.message.message_id, 5))

    designer_user = await db.get_user(callback.from_user.id)
    d_name = designer_user[1] if designer_user else callback.from_user.full_name

    text_to_creator = (
        f"🔔 Дизайнер <b>{html.escape(d_name)}</b> отметил(-а) выполнение задачи:\n"
        f"<b>Тема:</b> {html.escape(task['theme'])}\n\n"
        f"Пожалуйста, подтвердите приёмку или отправьте на доработку."
    )
    try:
        notice = await bot.send_message(
            chat_id=task["creator_id"],
            text=text_to_creator,
            reply_markup=get_creator_confirmation_keyboard(task_id)
        )
        pending_async_notices.setdefault(task["creator_id"], []).append(notice.message_id)
    except Exception:
        pass


@router.callback_query(F.data.startswith("creator_approve_"))
async def creator_approve_task(callback: CallbackQuery, bot: Bot):
    await clear_user_pending_notices(bot, callback.from_user.id)
    task_id = int(callback.data.split("_")[2])
    task = await db.get_task(task_id)

    if not task or task["creator_id"] != callback.from_user.id:
        await callback.answer("Ошибка доступа.", show_alert=True)
        return

    await db.complete_task_db(task_id)
    await callback.answer("Приёмка подтверждена!")

    await callback.message.edit_text(f"🎉 Задача #{task_id} («{html.escape(task['theme'])}») принята!")
    asyncio.create_task(delete_later(bot, callback.message.chat.id, callback.message.message_id, 5))

    await delete_task_messages_from_group(bot, task_id)

    if task["designer_id"]:
        try:
            notice = await bot.send_message(
                chat_id=task["designer_id"],
                text=f"🎉 Заказчик подтвердил(-а) выполнение задачи #{task_id} («{html.escape(task['theme'])}»)!"
            )
            pending_async_notices.setdefault(task["designer_id"], []).append(notice.message_id)
        except Exception:
            pass


@router.callback_query(F.data.startswith("creator_rework_"))
async def creator_rework_task(callback: CallbackQuery, bot: Bot):
    await clear_user_pending_notices(bot, callback.from_user.id)
    task_id = int(callback.data.split("_")[2])
    task = await db.get_task(task_id)

    if not task or task["creator_id"] != callback.from_user.id:
        await callback.answer("Ошибка доступа.", show_alert=True)
        return

    await db.rework_task_db(task_id)
    await callback.answer("Отправлено на доработку.")

    await callback.message.edit_text(f"🔄 Задача #{task_id} возвращена дизайнеру на доработку.")
    asyncio.create_task(delete_later(bot, callback.message.chat.id, callback.message.message_id, 5))

    if task["designer_id"]:
        try:
            notice = await bot.send_message(
                chat_id=task["designer_id"],
                text=f"⚠️ Заказчик вернул(-а) задачу #{task_id} («{html.escape(task['theme'])}») на доработку.",
                reply_markup=get_designer_task_control_keyboard(task_id)
            )
            pending_async_notices.setdefault(task["designer_id"], []).append(notice.message_id)
        except Exception:
            pass


# ========================================================
# Статистика
# ========================================================

@router.message(F.chat.type == "private", F.text == "📊 Статистика")
async def admin_stats_button(message: Message, bot: Bot):
    await handle_user_command_cleanup(bot, message.chat.id, message.from_user.id, message.message_id)

    if not config.is_admin(message.from_user.id):
        return

    now = datetime.now()
    start_of_current_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
    stats = await db.get_monthly_designer_stats(start_of_current_month)

    if not stats:
        msg = await message.answer(f"📈 За текущий месяц (с {now.strftime('01.%m.%Y')}) пока нет закрытых задач.")
        asyncio.create_task(delete_later(bot, message.chat.id, msg.message_id, 10))
        return

    msg_lines = [f"📊 <b>Статистика дизайнеров с 01.{now.strftime('%m.%Y')}:</b>\n"]
    for idx, row in enumerate(stats, start=1):
        d_name = html.escape(row["designer_name"] or "Аноним")
        count = row["done_count"]
        avg_time = html.escape(row["avg_time_str"])
        msg_lines.append(f"{idx}. <b>{d_name}</b>: {count} задач(и) | Среднее время: <code>{avg_time}</code>")

    await message.answer("\n".join(msg_lines))
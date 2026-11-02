from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    WebAppInfo
)
import config


def get_main_menu_keyboard(is_admin_user: bool = False, is_designer_user: bool = False) -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="➕ Создать задачу"), KeyboardButton(text="📋 Мои задачи")]
    ]

    if is_designer_user or is_admin_user:
        webapp_btn = KeyboardButton(
            text="📊 Таблица задач (Mini App)",
            web_app=WebAppInfo(url=config.WEBAPP_URL)
        )
        buttons.append([webapp_btn])

    if is_designer_user:
        buttons.append([KeyboardButton(text="💼 Мои задачи в работе")])

    if is_admin_user:
        buttons.append([KeyboardButton(text="📊 Статистика")])

    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def get_reference_input_keyboard(has_files: bool = False) -> InlineKeyboardMarkup:
    buttons = []
    if has_files:
        buttons.append([InlineKeyboardButton(text="✅ Завершить прикрепление файлов", callback_data="finish_reference_files")])
    buttons.append([InlineKeyboardButton(text="🚫 Референсов нет / Завершить", callback_data="skip_reference")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_task_confirmation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Всё верно, отправить", callback_data="confirm_task_yes")
            ],
            [
                InlineKeyboardButton(text="✏️ Изменить ТЗ", callback_data="confirm_edit_desc")
            ],
            [
                InlineKeyboardButton(text="❌ Отменить создание", callback_data="confirm_task_no")
            ]
        ]
    )


def get_task_take_keyboard(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💼 Взять в работу", callback_data=f"take_task_{task_id}")]
        ]
    )


def get_task_taken_placeholder(designer_name: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"Взял(-а): {designer_name}", callback_data="noop")]
        ]
    )


def get_designer_task_control_keyboard(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Выполнено", callback_data=f"designer_done_{task_id}"),
                InlineKeyboardButton(text="❌ Отказаться", callback_data=f"designer_reject_{task_id}")
            ]
        ]
    )


def get_creator_confirmation_keyboard(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить приёмку", callback_data=f"creator_approve_{task_id}"),
                InlineKeyboardButton(text="🔄 На доработку", callback_data=f"creator_rework_{task_id}")
            ]
        ]
    )


def get_user_task_item_keyboard(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📝 Изменить ТЗ", callback_data=f"creator_edit_desc_{task_id}"),
                InlineKeyboardButton(text="📅 Изменить дедлайн", callback_data=f"creator_edit_deadline_{task_id}")
            ],
            [
                InlineKeyboardButton(text="❌ Отменить эту задачу", callback_data=f"creator_cancel_{task_id}")
            ]
        ]
    )
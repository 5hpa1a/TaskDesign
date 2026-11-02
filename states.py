from aiogram.fsm.state import State, StatesGroup


class RegistrationState(StatesGroup):
    waiting_for_full_name = State()
    waiting_for_position = State()


class TaskCreationState(StatesGroup):
    waiting_for_theme = State()
    waiting_for_formats = State()
    waiting_for_description = State()
    waiting_for_deadline = State()
    waiting_for_references = State()
    waiting_for_confirmation = State()
    waiting_for_desc_edit = State()  # Редактирование ТЗ на этапе создания


class TaskEditState(StatesGroup):
    waiting_for_new_deadline = State()
    waiting_for_new_description = State()  # Редактирование ТЗ существующей задачи
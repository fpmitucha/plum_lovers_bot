from aiogram.fsm.state import State, StatesGroup


class AnonStates(StatesGroup):
    menu = State()
    waiting_target = State()
    dialog_message = State()
    admin_message = State()
    public_message = State()

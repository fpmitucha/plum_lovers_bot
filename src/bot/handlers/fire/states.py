from aiogram.fsm.state import State, StatesGroup


class FireStates(StatesGroup):
    waiting_dorm = State()
    waiting_description = State()

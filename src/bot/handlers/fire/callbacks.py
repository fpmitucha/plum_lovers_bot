from aiogram.filters.callback_data import CallbackData


class FireReviewCB(CallbackData, prefix="fire"):
    action: str
    incident_id: int

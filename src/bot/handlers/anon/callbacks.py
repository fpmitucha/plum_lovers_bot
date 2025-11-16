from aiogram.filters.callback_data import CallbackData


class MenuCB(CallbackData, prefix="anonmenu"):
    action: str


class DialogCB(CallbackData, prefix="anonchat"):
    action: str
    code: str


class PublicCB(CallbackData, prefix="anonpub"):
    action: str
    request_id: int


class PrefCB(CallbackData, prefix="anonpref"):
    mode: str


class ConsentCB(CallbackData, prefix="anoncons"):
    action: str
    request_id: int

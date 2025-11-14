from __future__ import annotations

from aiogram import Router

from . import admin_box, dialogs, menu, public

router = Router(name="anon")
router.include_router(menu.router)
router.include_router(dialogs.router)
router.include_router(admin_box.router)
router.include_router(public.router)

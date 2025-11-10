from __future__ import annotations

from aiogram import Router

from . import commands, review, stats

router = Router(name="fire")
router.include_router(commands.router)
router.include_router(review.router)
router.include_router(stats.router)

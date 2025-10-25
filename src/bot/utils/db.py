"""
Инициализация асинхронного движка и фабрики сессий SQLAlchemy.

Выделено в отдельный модуль для переиспользования в репозитории и при тестировании.
"""

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


def create_engine(database_url: str) -> AsyncEngine:
    """
    Создать асинхронный движок SQLAlchemy.

    :param database_url: строка подключения, напр. sqlite+aiosqlite:///./bot.db
    :return: экземпляр AsyncEngine.
    """
    return create_async_engine(database_url, future=True, echo=False)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """
    Создать фабрику асинхронных сессий.

    :param engine: асинхронный движок.
    :return: фабрика сессий.
    """
    return async_sessionmaker(bind=engine, expire_on_commit=False)

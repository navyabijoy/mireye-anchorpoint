from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text
from app.config import settings

db_url = settings.DATABASE_URL
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif db_url.startswith("postgresql://"):
    db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

connect_args = {}
if "sqlite" in db_url:
    connect_args["check_same_thread"] = False
    connect_args["timeout"] = 30  # Wait up to 30s for a lock before raising OperationalError

engine = create_async_engine(
    db_url,
    connect_args=connect_args,
    echo=False
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

class Base(DeclarativeBase):
    pass

async def set_wal_mode():
    """Enable WAL journal mode for SQLite to allow concurrent readers and writers."""
    if "sqlite" in db_url:
        async with engine.connect() as conn:
            await conn.execute(text("PRAGMA journal_mode=WAL;"))
            await conn.execute(text("PRAGMA synchronous=NORMAL;"))
            await conn.commit()

async def get_db():
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

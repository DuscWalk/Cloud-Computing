from functools import lru_cache

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


@lru_cache
def get_engine():
    url = get_settings().database_url
    options = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine_options = {} if url.startswith("sqlite") else {"isolation_level": "READ COMMITTED"}
    engine = create_engine(url, connect_args=options, pool_pre_ping=True, **engine_options)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def sqlite_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

    return engine


def get_db():
    with sessionmaker(bind=get_engine(), expire_on_commit=False)() as session:
        yield session

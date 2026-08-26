from contextvars import ContextVar

from sqlalchemy import create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.config import settings

is_sqlite = str(settings.DATABASE_URL).startswith("sqlite")
engine_options = {"pool_pre_ping": True, "echo": settings.DEBUG}
if is_sqlite:
    engine_options["connect_args"] = {"check_same_thread": False, "timeout": 30}
else:
    engine_options.update({"pool_size": 10, "max_overflow": 20, "pool_recycle": 1800})

engine = create_engine(settings.DATABASE_URL, **engine_options)

# Planner telemetry is scoped to the current request/build context.  Keeping
# the counter opt-in avoids per-query overhead for ordinary page reads.
_sql_query_counter: ContextVar[int | None] = ContextVar("planner_sql_query_counter", default=None)


def start_sql_query_measurement():
    """Start counting SQL statements for the current planner build."""
    return _sql_query_counter.set(0)


def finish_sql_query_measurement(token) -> int:
    """Return the current scoped query count and restore the previous context."""
    count = int(_sql_query_counter.get() or 0)
    _sql_query_counter.reset(token)
    return count


@event.listens_for(engine, "before_cursor_execute")
def _count_planner_queries(_connection, _cursor, _statement, _parameters, _context, _executemany):
    count = _sql_query_counter.get()
    if count is not None:
        _sql_query_counter.set(count + 1)
if is_sqlite:
    @event.listens_for(engine, "connect")
    def configure_sqlite(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=120000")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """Dependency for getting database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

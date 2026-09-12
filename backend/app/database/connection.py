from sqlite3 import Connection

from app.database.models import get_connection as _get_connection

__all__ = ["get_connection", "close"]


def get_connection(db_path=None) -> Connection:
    return _get_connection(db_path)


def close(conn: Connection) -> None:
    try:
        conn.close()
    except Exception:
        pass
import os
import sqlite3
from contextlib import contextmanager
from app.config import (
    DB_BACKEND, MYSQL_CONFIG, COORDINATOR_DB_PATH, BRANCHES
)

# Optional PyMySQL import
try:
    import pymysql
    import pymysql.cursors
    PYMYSQL_AVAILABLE = True
except ImportError:
    PYMYSQL_AVAILABLE = False


class RowDict(dict):
    """
    Dictionary subclass providing both key access ('balance') and numeric index access (row[0]),
    faithfully replicating sqlite3.Row for PyMySQL query results.
    """
    def __getitem__(self, item):
        if isinstance(item, int):
            return list(self.values())[item]
        return super().__getitem__(item)


class MySQLCursorWrapper:
    """
    Wraps PyMySQL DictCursor to provide seamless parameter conversion:
      - Automatically rewrites '?' to '%s'
      - Automatically rewrites 'INSERT OR REPLACE INTO' to 'REPLACE INTO'
      - Wraps results in RowDict for uniform sqlite3.Row compatibility
    """
    def __init__(self, raw_cursor):
        self._cur = raw_cursor

    def execute(self, sql: str, params=None):
        sql = sql.replace("INSERT OR REPLACE INTO", "REPLACE INTO")
        sql = sql.replace("?", "%s")
        if params is not None:
            return self._cur.execute(sql, params)
        return self._cur.execute(sql)

    def executescript(self, script: str):
        statements = [s.strip() for s in script.split(";") if s.strip()]
        for stmt in statements:
            self.execute(stmt)

    def fetchone(self):
        row = self._cur.fetchone()
        return RowDict(row) if row else None

    def fetchall(self):
        rows = self._cur.fetchall()
        return [RowDict(r) for r in rows] if rows else []

    def close(self):
        self._cur.close()

    def __iter__(self):
        for r in self._cur:
            yield RowDict(r)


class MySQLConnectionWrapper:
    """Wraps PyMySQL Connection to provide commit, rollback, cursor, and execute methods."""
    def __init__(self, raw_conn):
        self._conn = raw_conn

    def cursor(self):
        return MySQLCursorWrapper(self._conn.cursor(pymysql.cursors.DictCursor))

    def execute(self, sql: str, params=None):
        cur = self.cursor()
        cur.execute(sql, params)
        return cur

    def executescript(self, script: str):
        cur = self.cursor()
        cur.executescript(script)
        return cur

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.rollback()
        else:
            self.commit()
        self.close()


# =====================================================================
# Connection Factory
# =====================================================================

def get_mysql_connection(db_name: str) -> MySQLConnectionWrapper:
    """Creates a connection to a specific MySQL database."""
    if not PYMYSQL_AVAILABLE:
        raise ImportError("pymysql is required for MySQL backend. Run: pip install pymysql")

    raw_conn = pymysql.connect(
        host=MYSQL_CONFIG["host"],
        port=MYSQL_CONFIG["port"],
        user=MYSQL_CONFIG["user"],
        password=MYSQL_CONFIG["password"],
        database=db_name,
        autocommit=False,
        charset="utf8mb4"
    )
    return MySQLConnectionWrapper(raw_conn)


def get_sqlite_connection(db_path: str) -> sqlite3.Connection:
    """Creates a configured SQLite connection with dict-like row access and WAL mode."""
    conn = sqlite3.connect(db_path, check_same_thread=False, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    return conn


def get_coordinator_connection():
    """Returns a connection to Central Coordinator Node (MySQL or SQLite)."""
    if DB_BACKEND == "mysql":
        return get_mysql_connection(MYSQL_CONFIG["coordinator_db"])
    return get_sqlite_connection(str(COORDINATOR_DB_PATH))


def get_branch_connection(branch_id: str):
    """Returns a connection to a specific Branch Node (MySQL or SQLite)."""
    if branch_id not in BRANCHES:
        raise ValueError(f"Unknown branch_id: {branch_id}")

    if DB_BACKEND == "mysql":
        db_name = BRANCHES[branch_id].get("mysql_database", f"bank_branch_{branch_id.lower()}")
        return get_mysql_connection(db_name)

    return get_sqlite_connection(str(BRANCHES[branch_id]["db_path"]))


@contextmanager
def coordinator_db():
    conn = get_coordinator_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def branch_db(branch_id: str):
    conn = get_branch_connection(branch_id)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_all_branch_connections():
    return {b_id: get_branch_connection(b_id) for b_id in BRANCHES}

import sqlite3
from .config import SQLITE_DB_PATH


DEFAULT_DEVICE_MODE = "increment"
VALID_DEVICE_MODES = {"increment", "decrement"}


def connect():
    conn = sqlite3.connect(SQLITE_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_device_mode_column(cursor):
    cursor.execute("PRAGMA table_info(devices)")
    columns = {row[1] for row in cursor.fetchall()}
    if "mode" not in columns:
        cursor.execute(
            "ALTER TABLE devices ADD COLUMN mode TEXT NOT NULL DEFAULT 'increment'"
        )

def init_db() -> None:
    with connect() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS devices (
                pin TEXT PRIMARY KEY,
                current_count INTEGER NOT NULL DEFAULT 0,
                mode TEXT NOT NULL DEFAULT 'increment'
            )
            """
        )
        _ensure_device_mode_column(cursor)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_devices (
                user_id INTEGER NOT NULL,
                pin TEXT NOT NULL,
                UNIQUE(user_id, pin)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pin TEXT NOT NULL,
                change INTEGER NOT NULL,
                new_count INTEGER NOT NULL,
                ts INTEGER NOT NULL
            )
            """
        )
        conn.commit()


def apply_change(pin: str, change: int, ts: int):
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO devices(pin, current_count, mode) VALUES (?, 0, ?)",
            (pin, DEFAULT_DEVICE_MODE),
        )
        row = conn.execute(
            "SELECT current_count FROM devices WHERE pin = ?",
            (pin,),
        ).fetchone()
        current = int(row["current_count"]) if row else 0
        new_count = current + int(change)
        conn.execute(
            "UPDATE devices SET current_count = ? WHERE pin = ?",
            (new_count, pin),
        )
        conn.execute(
            "INSERT INTO logs(pin, change, new_count, ts) VALUES (?, ?, ?, ?)",
            (pin, int(change), new_count, ts),
        )
        conn.commit()
        return new_count


def get_current_count(pin: str):
    with connect() as conn:
        row = conn.execute(
            "SELECT current_count FROM devices WHERE pin = ?",
            (pin,),
        ).fetchone()
        if not row:
            return 0
        return int(row["current_count"])


def get_logs(pin: str, limit: int = 50):
    limit = max(1, min(500, int(limit)))
    with connect() as conn:
        rows = conn.execute(
            "SELECT pin, change, new_count, ts FROM logs WHERE pin = ? ORDER BY id DESC LIMIT ?",
            (pin, limit),
        ).fetchall()
        return [
            {"pin": r["pin"], "change": r["change"], "new_count": r["new_count"], "ts": r["ts"]}
            for r in rows
        ]


def create_user(username: str, password: str) -> int:
    with connect() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users(username, password) VALUES (?, ?)",
            (username, password),
        )
        conn.commit()
        return int(cursor.lastrowid)


def get_user_by_username(username: str):
    with connect() as conn:
        row = conn.execute(
            "SELECT id, username, password FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if not row:
            return None
        return {"id": row["id"], "username": row["username"], "password": row["password"]}


def link_pin_to_user(user_id: int, pin: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO devices(pin, current_count, mode) VALUES (?, 0, ?)",
            (pin, DEFAULT_DEVICE_MODE),
        )
        conn.execute(
            "INSERT OR IGNORE INTO user_devices(user_id, pin) VALUES (?, ?)",
            (user_id, pin),
        )
        conn.commit()


def unlink_pin_from_user(user_id: int, pin: str) -> bool:
    """Detach a pin from a user and clean up orphaned device data."""
    with connect() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM user_devices WHERE user_id = ? AND pin = ?",
            (user_id, pin),
        )
        deleted = cursor.rowcount > 0
        if not deleted:
            conn.commit()
            return False

        still_linked = cursor.execute(
            "SELECT 1 FROM user_devices WHERE pin = ? LIMIT 1",
            (pin,),
        ).fetchone()
        if not still_linked:
            cursor.execute("DELETE FROM devices WHERE pin = ?", (pin,))
            cursor.execute("DELETE FROM logs WHERE pin = ?", (pin,))

        conn.commit()
        return True


def list_user_pins(user_id: int):
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT d.pin, d.current_count, d.mode
            FROM devices d
            JOIN user_devices ud ON ud.pin = d.pin
            WHERE ud.user_id = ?
            ORDER BY d.pin
            """,
            (user_id,),
        ).fetchall()
        return [
            {
                "pin": r["pin"],
                "current_count": r["current_count"],
                "mode": r["mode"] or DEFAULT_DEVICE_MODE,
            }
            for r in rows
        ]


def is_pin_owned_by_user(user_id: int, pin: str) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM user_devices WHERE user_id = ? AND pin = ?",
            (user_id, pin),
        ).fetchone()
        return bool(row)


def get_device_mode(pin: str) -> str:
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO devices(pin, current_count, mode) VALUES (?, 0, ?)",
            (pin, DEFAULT_DEVICE_MODE),
        )
        row = conn.execute(
            "SELECT mode FROM devices WHERE pin = ?",
            (pin,),
        ).fetchone()
        mode = (row["mode"] if row else None) or DEFAULT_DEVICE_MODE
        if mode not in VALID_DEVICE_MODES:
            mode = DEFAULT_DEVICE_MODE
            conn.execute(
                "UPDATE devices SET mode = ? WHERE pin = ?",
                (mode, pin),
            )
        conn.commit()
        return mode


def set_device_mode(pin: str, mode: str) -> str:
    if not mode:
        raise ValueError("mode required")
    normalized = mode.strip().lower()
    if normalized not in VALID_DEVICE_MODES:
        raise ValueError("invalid mode")
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO devices(pin, current_count, mode) VALUES (?, 0, ?)",
            (pin, DEFAULT_DEVICE_MODE),
        )
        conn.execute(
            "UPDATE devices SET mode = ? WHERE pin = ?",
            (normalized, pin),
        )
        conn.commit()
        return normalized

import os
import sqlite3
from werkzeug.security import generate_password_hash
from cryptography.fernet import Fernet


# ------------------------------------------------------------------
# Paths — Render has an ephemeral FS. If /data exists (mounted disk),
# persist the DB + encryption key there so nothing gets wiped.
# ------------------------------------------------------------------
_DATA_DIR = "/data" if os.path.isdir("/data") and os.access("/data", os.W_OK) else "."

DB_PATH = os.getenv("DATABASE") or os.path.join(_DATA_DIR, "filewale.db")
KEY_PATH = os.path.join(_DATA_DIR, "_enc.key")


# ------------------------------------------------------------------
# Encryption helpers (Fernet — symmetric, at rest)
# ------------------------------------------------------------------
def _load_or_create_key() -> bytes:
    env_key = (os.getenv("ENC_KEY") or "").strip()
    if env_key:
        return env_key.encode()
    if os.path.exists(KEY_PATH):
        with open(KEY_PATH, "rb") as f:
            return f.read().strip()
    k = Fernet.generate_key()
    with open(KEY_PATH, "wb") as f:
        f.write(k)
    try:
        os.chmod(KEY_PATH, 0o600)
    except OSError:
        pass
    return k


_FERNET = None


def fernet() -> Fernet:
    global _FERNET
    if _FERNET is None:
        _FERNET = Fernet(_load_or_create_key())
    return _FERNET


def enc(plain: str) -> str:
    return fernet().encrypt(plain.encode()).decode()


def dec(cipher: str) -> str:
    return fernet().decrypt(cipher.encode()).decode()


# ------------------------------------------------------------------
# DB
# ------------------------------------------------------------------
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def init_db():
    c = get_db()
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT,
            password_hash TEXT NOT NULL,
            balance REAL NOT NULL DEFAULT 0,
            is_admin INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email_enc TEXT NOT NULL,
            password_enc TEXT NOT NULL,
            plan_name TEXT,
            plan_category TEXT NOT NULL DEFAULT 'silver',
            original_price REAL,
            original_currency TEXT DEFAULT 'USD',
            selling_price REAL NOT NULL,
            cost REAL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'LIVE',
            expiry_date TEXT,
            last_sync TEXT,
            notes TEXT,
            sold INTEGER NOT NULL DEFAULT 0,
            sold_to INTEGER,
            sold_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            amount REAL NOT NULL,
            balance_after REAL NOT NULL,
            reason TEXT,
            meta TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS deposits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            method TEXT NOT NULL,
            txn_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING',
            admin_note TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            verified_at TEXT,
            verified_by INTEGER
        );

        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            account_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_deposits_txn ON deposits(txn_id);
        CREATE INDEX IF NOT EXISTS idx_accounts_sold ON accounts(sold, status);
        CREATE INDEX IF NOT EXISTS idx_tx_user ON transactions(user_id, id DESC);

        INSERT OR IGNORE INTO settings (key, value) VALUES
            ('silver_banner_enabled', '1'),
            ('golden_banner_enabled', '1'),
            ('silver_banner_text', 'SILVER PLAN — Metallic Access, Half the Price.'),
            ('golden_banner_text', 'GOLDEN PLAN — Royal Tier. Premium Everything.'),
            ('site_title', 'FILEWALE PREMIUM');
        """
    )
    c.close()


def ensure_admin(username: str, password: str):
    """Idempotent — safe on every boot."""
    c = get_db()
    row = c.execute("SELECT id, is_admin FROM users WHERE username=?", (username,)).fetchone()
    if row:
        if not row["is_admin"]:
            c.execute("UPDATE users SET is_admin=1 WHERE id=?", (row["id"],))
    else:
        c.execute(
            "INSERT INTO users (username, password_hash, is_admin) VALUES (?,?,1)",
            (username, generate_password_hash(password)),
        )
    c.close()

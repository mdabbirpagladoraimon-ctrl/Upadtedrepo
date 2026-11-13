import sqlite3
import json
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash
from config import Config

def get_db_connection():
    conn = sqlite3.connect(Config.DATABASE_URL, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn

def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'user',
        wallet_balance REAL NOT NULL DEFAULT 0.0,
        total_deposits REAL NOT NULL DEFAULT 0.0,
        total_purchases REAL NOT NULL DEFAULT 0.0,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        identifier TEXT NOT NULL,
        encrypted_password TEXT NOT NULL,
        encrypted_access_token TEXT DEFAULT '',
        plan_category TEXT NOT NULL DEFAULT 'SILVER',
        category_override INTEGER NOT NULL DEFAULT 0,
        fw_plan_name TEXT NOT NULL DEFAULT 'Unknown Plan',
        original_price REAL NOT NULL DEFAULT 0.0,
        original_currency TEXT NOT NULL DEFAULT 'BDT',
        purchase_cost REAL NOT NULL DEFAULT 0.0,
        selling_price REAL NOT NULL DEFAULT 0.0,
        price_override INTEGER NOT NULL DEFAULT 0,
        discount_pct INTEGER NOT NULL DEFAULT 50,
        stock_status TEXT NOT NULL DEFAULT 'AVAILABLE',
        live_status TEXT NOT NULL DEFAULT 'CHECKING',
        sub_status TEXT DEFAULT 'UNKNOWN',
        start_date TEXT DEFAULT '',
        end_date TEXT DEFAULT '',
        remaining_days INTEGER DEFAULT 0,
        max_downloads INTEGER DEFAULT 0,
        max_bandwidth_gb REAL DEFAULT 0.0,
        max_devices INTEGER DEFAULT 0,
        daily_download_limit INTEGER DEFAULT 0,
        daily_bandwidth_limit_gb REAL DEFAULT 0.0,
        download_count INTEGER DEFAULT 0,
        bandwidth_used_gb REAL DEFAULT 0.0,
        fw_username TEXT DEFAULT '',
        fw_user_id TEXT DEFAULT '',
        fw_full_name TEXT DEFAULT '',
        fw_country TEXT DEFAULT '',
        fw_city TEXT DEFAULT '',
        fw_2fa INTEGER DEFAULT 0,
        fw_email_verified INTEGER DEFAULT 0,
        fw_mobile_verified INTEGER DEFAULT 0,
        fw_wallet_balance REAL DEFAULT 0.0,
        fw_wallet_currency TEXT DEFAULT 'BDT',
        admin_notes TEXT DEFAULT '',
        last_synced_at TEXT DEFAULT '',
        buyer_id INTEGER DEFAULT NULL,
        sold_at TEXT DEFAULT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(buyer_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS deposits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        amount REAL NOT NULL,
        payment_method TEXT NOT NULL,
        transaction_id TEXT UNIQUE NOT NULL,
        status TEXT NOT NULL DEFAULT 'PENDING',
        admin_note TEXT DEFAULT '',
        verified_by INTEGER DEFAULT NULL,
        created_at TEXT NOT NULL,
        verified_at TEXT DEFAULT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS purchases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        account_id INTEGER UNIQUE NOT NULL,
        plan_name TEXT NOT NULL,
        plan_category TEXT NOT NULL,
        original_price REAL NOT NULL,
        original_currency TEXT NOT NULL,
        paid_price REAL NOT NULL,
        purchased_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(account_id) REFERENCES accounts(id)
    );

    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        tx_type TEXT NOT NULL,
        amount REAL NOT NULL,
        balance_after REAL NOT NULL,
        reference TEXT DEFAULT '',
        description TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        actor_id INTEGER,
        actor_username TEXT,
        action TEXT NOT NULL,
        details TEXT DEFAULT '',
        ip_address TEXT DEFAULT '',
        created_at TEXT NOT NULL
    );
    """)

    # Seed initial Admin from environment variables
    admin_user = Config.ADMIN_USERNAME.strip()
    admin_pass = Config.ADMIN_PASSWORD
    cur.execute("SELECT id FROM users WHERE username = ?", (admin_user,))
    if not cur.fetchone():
        cur.execute("""
            INSERT INTO users (username, email, password_hash, role, wallet_balance, created_at)
            VALUES (?, ?, ?, 'admin', 0.0, ?)
        """, (
            admin_user,
            f"{admin_user.lower()}@filewalepremium.store",
            generate_password_hash(admin_pass),
            now_iso()
        ))

    # Seed default banners & site settings
    default_settings = {
        "site_title": "FILEWALE PREMIUM",
        "hero_subtitle": "PREMIUM ACCESS. HALF THE PRICE.",
        "bkash_number": Config.BKASH_NUMBER,
        "nagad_number": Config.NAGAD_NUMBER,
        "usd_to_bdt_rate": "120.0",
        "silver_banner_enabled": "1",
        "silver_banner_title": "SILVER ELITE TIER — 50% OFF OFFICIAL PRICE",
        "silver_banner_text": "High-speed verified FileWale Silver subscriptions with instant automated credential delivery.",
        "golden_banner_enabled": "1",
        "golden_banner_title": "ROYAL GOLDEN TIER — MAXIMUM BANDWIDTH AT 50% OFF",
        "golden_banner_text": "Unrestricted priority FileWale Golden plans with live status monitoring and full warranty."
    }
    for k, v in default_settings.items():
        cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

    conn.commit()
    conn.close()

def get_settings_dict() -> dict:
    conn = get_db_connection()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}

def log_audit(actor_id, actor_username: str, action: str, details: str = "", ip_address: str = ""):
    try:
        conn = get_db_connection()
        conn.execute("""
            INSERT INTO audit_logs (actor_id, actor_username, action, details, ip_address, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (actor_id, actor_username, action, details, ip_address, now_iso()))
        conn.commit()
        conn.close()
    except Exception:
        pass

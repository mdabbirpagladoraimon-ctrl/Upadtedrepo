import os
import base64
import hashlib
from dotenv import load_dotenv
from cryptography.fernet import Fernet

load_dotenv()

class Config:
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-fallback-secret-key-change-in-prod")
    DATABASE_URL = os.getenv("DATABASE_URL", "filewale_store.db")
    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "ZYELEO")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "@Saberps4")
    FILEWALE_BASE_URL = os.getenv("FILEWALE_BASE_URL", "https://filewale.com")
    FILEWALE_API_BASE = os.getenv("FILEWALE_API_BASE", "https://filewale.com/api/v1")
    BKASH_NUMBER = os.getenv("BKASH_NUMBER", "01739124825")
    NAGAD_NUMBER = os.getenv("NAGAD_NUMBER", "01739124825")
    SYNC_COOLDOWN_SECONDS = 120  # Rate-limit live API checks per account

    @staticmethod
    def get_fernet() -> Fernet:
        raw_key = os.getenv("FERNET_KEY", "")
        try:
            if raw_key and len(raw_key) == 44:
                return Fernet(raw_key.encode("utf-8"))
        except Exception:
            pass
        derived = base64.urlsafe_b64encode(
            hashlib.sha256(Config.SECRET_KEY.encode("utf-8")).digest()
        )
        return Fernet(derived)

fernet_cipher = Config.get_fernet()

def encrypt_secret(plain_text: str) -> str:
    if not plain_text:
        return ""
    return fernet_cipher.encrypt(plain_text.encode("utf-8")).decode("utf-8")

def decrypt_secret(cipher_text: str) -> str:
    if not cipher_text:
        return ""
    try:
        return fernet_cipher.decrypt(cipher_text.encode("utf-8")).decode("utf-8")
    except Exception:
        return "[DECRYPTION_ERROR]"

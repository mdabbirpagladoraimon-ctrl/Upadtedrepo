import requests
from datetime import datetime, timezone
from config import Config

class FileWaleAPIClient:
    """
    Authorized single-account FileWale API v1 client.
    Uses exact endpoints:
      - POST /api/v1/auth/login
      - GET  /api/v1/users/me
      - GET  /api/v1/wallet/me/balance
      - GET  /api/v1/subscriptions/my-subscription
    """
    def __init__(self, timeout: int = 12):
        self.base_url = Config.FILEWALE_API_BASE.rstrip("/")
        self.timeout = timeout
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "FileWalePremiumStore/2.0"
        }

    def _unwrap(self, payload: dict) -> dict:
        if not isinstance(payload, dict):
            return {}
        if "data" in payload and isinstance(payload["data"], dict):
            return payload["data"]
        return payload

    def login(self, identifier: str, password: str) -> dict:
        url = f"{self.base_url}/auth/login"
        try:
            resp = requests.post(
                url,
                json={"identifier": identifier, "password": password},
                headers=self.headers,
                timeout=self.timeout
            )
            body = resp.json() if resp.content else {}
            if resp.status_code in (200, 201):
                data = self._unwrap(body)
                access_token = data.get("accessToken") or body.get("accessToken")
                user_obj = data.get("user") or body.get("user") or {}
                if access_token:
                    return {
                        "ok": True,
                        "accessToken": access_token,
                        "user": user_obj
                    }
            err_msg = body.get("message") or body.get("error") or f"HTTP {resp.status_code}"
            return {"ok": False, "error": str(err_msg)}
        except requests.RequestException as exc:
            return {"ok": False, "error": f"Connection error: {str(exc)}"}
        except ValueError:
            return {"ok": False, "error": "Invalid JSON response from FileWale auth endpoint"}

    def get_profile(self, access_token: str) -> dict:
        url = f"{self.base_url}/users/me"
        headers = {**self.headers, "Authorization": f"Bearer {access_token}"}
        try:
            resp = requests.get(url, headers=headers, timeout=self.timeout)
            if resp.status_code == 401:
                return {"ok": False, "unauthorized": True, "error": "Token expired or unauthorized"}
            body = resp.json() if resp.content else {}
            if resp.status_code == 200:
                data = self._unwrap(body)
                user = data.get("user", data) if isinstance(data, dict) else {}
                return {
                    "ok": True,
                    "username": user.get("username", ""),
                    "id": str(user.get("id", user.get("_id", ""))),
                    "fullName": user.get("fullName", ""),
                    "country": user.get("country", ""),
                    "city": user.get("city", ""),
                    "isTwoFactorEnabled": bool(user.get("isTwoFactorEnabled", False)),
                    "emailVerified": bool(user.get("emailVerified", False)),
                    "mobileVerified": bool(user.get("mobileVerified", False)),
                    "createdAt": user.get("createdAt", "")
                }
            return {"ok": False, "error": f"Profile HTTP {resp.status_code}"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def get_wallet_balance(self, access_token: str) -> dict:
        url = f"{self.base_url}/wallet/me/balance"
        headers = {**self.headers, "Authorization": f"Bearer {access_token}"}
        try:
            resp = requests.get(url, headers=headers, timeout=self.timeout)
            if resp.status_code == 401:
                return {"ok": False, "unauthorized": True}
            body = resp.json() if resp.content else {}
            if resp.status_code == 200:
                data = self._unwrap(body)
                return {
                    "ok": True,
                    "balance": float(data.get("balance", 0.0) or 0.0),
                    "currency": str(data.get("currency", "BDT") or "BDT"),
                    "availableBalance": float(data.get("availableBalance", 0.0) or 0.0),
                    "lockedAmount": float(data.get("lockedAmount", 0.0) or 0.0),
                    "totalCredited": float(data.get("totalCredited", 0.0) or 0.0),
                    "totalDebited": float(data.get("totalDebited", 0.0) or 0.0),
                }
            return {"ok": False, "error": f"Wallet HTTP {resp.status_code}"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def get_subscription(self, access_token: str) -> dict:
        url = f"{self.base_url}/subscriptions/my-subscription"
        headers = {**self.headers, "Authorization": f"Bearer {access_token}"}
        try:
            resp = requests.get(url, headers=headers, timeout=self.timeout)
            if resp.status_code == 401:
                return {"ok": False, "unauthorized": True}
            body = resp.json() if resp.content else {}
            if resp.status_code == 200:
                data = self._unwrap(body)
                sub = data.get("subscription", data) if isinstance(data, dict) else {}
                if not sub or not isinstance(sub, dict):
                    return {"ok": True, "has_subscription": False}

                plan = sub.get("plan") if isinstance(sub.get("plan"), dict) else {}
                raw_price = plan.get("price")
                parsed_price = None
                if raw_price is not None and raw_price != "":
                    try:
                        parsed_price = float(raw_price)
                    except (ValueError, TypeError):
                        parsed_price = None

                end_date_str = str(sub.get("endDate", "") or "")
                remaining_days = calculate_remaining_days(end_date_str)
                sub_status = str(sub.get("status", "ACTIVE") or "ACTIVE").upper()

                return {
                    "ok": True,
                    "has_subscription": True,
                    "plan_name": str(plan.get("name") or sub.get("planName") or "Standard Plan"),
                    "plan_price": parsed_price,
                    "plan_currency": str(plan.get("currency") or sub.get("currency") or ""),
                    "maxDownloads": int(plan.get("maxDownloads", 0) or 0),
                    "maxBandwidthGB": float(plan.get("maxBandwidthGB", 0.0) or 0.0),
                    "maxDevices": int(plan.get("maxDevices", 0) or 0),
                    "dailyDownloadLimit": int(plan.get("dailyDownloadLimit", 0) or 0),
                    "dailyBandwidthLimitGB": float(plan.get("dailyBandwidthLimitGB", 0.0) or 0.0),
                    "status": sub_status,
                    "startDate": str(sub.get("startDate", "") or ""),
                    "endDate": end_date_str,
                    "remainingDays": remaining_days,
                    "downloadCount": int(sub.get("downloadCount", 0) or 0),
                    "bandwidthUsedGB": float(sub.get("bandwidthUsedGB", 0.0) or 0.0)
                }
            return {"ok": False, "error": f"Subscription HTTP {resp.status_code}"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def fetch_full_account_snapshot(self, identifier: str, password: str, existing_token: str = "") -> dict:
        token = existing_token
        profile = {}
        if token:
            prof_try = self.get_profile(token)
            if not prof_try.get("ok") and prof_try.get("unauthorized"):
                token = ""
            elif prof_try.get("ok"):
                profile = prof_try

        if not token:
            auth = self.login(identifier, password)
            if not auth.get("ok"):
                return {
                    "ok": False,
                    "live_status": "OFFLINE",
                    "error": auth.get("error", "Authentication failed")
                }
            token = auth["accessToken"]
            profile = self.get_profile(token)

        wallet = self.get_wallet_balance(token)
        sub = self.get_subscription(token)

        live_status = "LIVE"
        if sub.get("ok") and sub.get("has_subscription"):
            st = sub.get("status", "").upper()
            rem = sub.get("remainingDays", 0)
            if st in ("EXPIRED", "CANCELLED", "INACTIVE") or (sub.get("endDate") and rem <= 0):
                live_status = "EXPIRED"
        elif sub.get("ok") and not sub.get("has_subscription"):
            live_status = "EXPIRED"

        return {
            "ok": True,
            "accessToken": token,
            "live_status": live_status,
            "profile": profile if profile.get("ok") else {},
            "wallet": wallet if wallet.get("ok") else {},
            "subscription": sub if sub.get("ok") else {}
        }

def calculate_remaining_days(end_date_str: str) -> int:
    if not end_date_str:
        return 0
    try:
        cleaned = end_date_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = dt - datetime.now(timezone.utc)
        days = int(delta.total_seconds() // 86400)
        return max(0, days)
    except Exception:
        try:
            dt = datetime.strptime(end_date_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            delta = dt - datetime.now(timezone.utc)
            return max(0, int(delta.days))
        except Exception:
            return 0

def infer_plan_category(plan_name: str) -> str:
    if not plan_name:
        return "SILVER"
    upper = plan_name.upper()
    gold_keywords = ("GOLD", "GOLDEN", "PRO", "ULTIMATE", "ROYAL", "VIP", "PLATINUM", "MAX", "DIAMOND")
    for kw in gold_keywords:
        if kw in upper:
            return "GOLDEN"
    return "SILVER"

def calculate_half_price(original_price: float) -> float:
    return round(float(original_price) * 0.50, 2)

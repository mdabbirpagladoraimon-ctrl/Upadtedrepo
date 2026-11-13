import requests


class FileWaleError(Exception):
    pass


class FileWaleClient:
    def __init__(self, base_url: str, timeout: int = 20):
        self.base = base_url.rstrip("/")
        self.timeout = timeout

    def _req(self, method: str, path: str, token: str | None = None, **kwargs):
        headers = kwargs.pop("headers", {}) or {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        headers.setdefault("User-Agent", "FileWale-Store/2.0")
        headers.setdefault("Accept", "application/json")
        headers.setdefault("Content-Type", "application/json")
        try:
            r = requests.request(
                method,
                f"{self.base}{path}",
                headers=headers,
                timeout=self.timeout,
                **kwargs,
            )
        except requests.RequestException as e:
            raise FileWaleError(f"network: {e}") from e
        if r.status_code >= 400:
            raise FileWaleError(f"http {r.status_code}: {r.text[:200]}")
        try:
            return r.json()
        except ValueError as e:
            raise FileWaleError(f"non-json response: {r.text[:200]}") from e

    def login(self, identifier: str, password: str) -> dict:
        data = self._req(
            "POST",
            "/auth/login",
            json={"identifier": identifier, "password": password},
        )
        payload = data.get("data") or {}
        token = payload.get("accessToken") or payload.get("access_token")
        if not token:
            raise FileWaleError("no access token in login response")
        return {"token": token, "user": payload.get("user") or {}}

    def me(self, token: str) -> dict:
        return self._req("GET", "/users/me", token=token).get("data") or {}

    def wallet_balance(self, token: str) -> dict:
        return self._req("GET", "/wallet/me/balance", token=token).get("data") or {}

    def subscription(self, token: str) -> dict:
        return self._req(
            "GET", "/subscriptions/my-subscription", token=token
        ).get("data") or {}

    def snapshot(self, identifier: str, password: str) -> dict:
        """Login and pull profile + subscription in a single pass."""
        auth = self.login(identifier, password)
        token = auth["token"]
        try:
            user = self.me(token)
        except FileWaleError:
            user = auth["user"]
        try:
            sub = self.subscription(token)
        except FileWaleError:
            sub = {}
        return {"user": user, "subscription": sub, "token": token}


def categorize(plan_name: str) -> str:
    name = (plan_name or "").lower()
    if any(
        k in name
        for k in ("gold", "golden", "royal", "premium", "diamond", "platinum")
    ):
        return "gold"
    if any(k in name for k in ("silver", "basic", "starter", "standard")):
        return "silver"
    return "silver"

import os
import re
import json
import secrets
from datetime import datetime, timezone
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for, session, flash,
    jsonify, abort, send_from_directory,
)
from jinja2 import BaseLoader, TemplateNotFound
from werkzeug.security import generate_password_hash, check_password_hash

from config import Config
from models import init_db, get_db, ensure_admin, enc, dec
from api import FileWaleClient, FileWaleError, categorize


# ------------------------------------------------------------------
# Single-file template loader — reads `templates.html`
# ------------------------------------------------------------------
class SingleFileLoader(BaseLoader):
    def __init__(self, path: str):
        self.path = path
        self.cache = {}
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
        parts = re.split(r"\{#\s*TEMPLATE:\s*([\w\-\.]+)\s*#\}", raw)
        for i in range(1, len(parts), 2):
            self.cache[parts[i]] = parts[i + 1]

    def get_source(self, environment, template):
        if template not in self.cache:
            raise TemplateNotFound(template)
        return self.cache[template], self.path, lambda: True


app = Flask(__name__, static_folder=None)
app.config.from_object(Config)
app.jinja_loader = SingleFileLoader(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates.html")
)

init_db()
ensure_admin(Config.ADMIN_USERNAME, Config.ADMIN_PASSWORD)


# ------------------------------------------------------------------
# Static files from root
# ------------------------------------------------------------------
@app.route("/static.css")
def static_css():
    return send_from_directory(".", "static.css", mimetype="text/css")


@app.route("/static.js")
def static_js():
    return send_from_directory(".", "static.js", mimetype="application/javascript")


# ------------------------------------------------------------------
# CSRF
# ------------------------------------------------------------------
def csrf_token() -> str:
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(24)
    return session["_csrf"]


def require_csrf():
    token = session.get("_csrf")
    sent = request.form.get("_csrf") or request.headers.get("X-CSRF")
    if not token or not sent or not secrets.compare_digest(token, sent):
        abort(400, "CSRF token invalid")


app.jinja_env.globals["csrf_token"] = csrf_token


@app.context_processor
def inject_globals():
    user = None
    if session.get("uid"):
        c = get_db()
        user = c.execute(
            "SELECT id, username, balance, is_admin FROM users WHERE id=?",
            (session["uid"],),
        ).fetchone()
        c.close()
    settings = {}
    c = get_db()
    for row in c.execute("SELECT key, value FROM settings"):
        settings[row["key"]] = row["value"]
    c.close()
    return {
        "current_user": user,
        "is_admin": bool(session.get("admin")),
        "cfg": Config,
        "site": settings,
    }


def login_required(f):
    @wraps(f)
    def w(*a, **k):
        if not session.get("uid"):
            return redirect(url_for("login", next=request.path))
        return f(*a, **k)
    return w


def admin_required(f):
    @wraps(f)
    def w(*a, **k):
        if not session.get("admin"):
            return redirect(url_for("admin_login"))
        return f(*a, **k)
    return w


# ------------------------------------------------------------------
# Public
# ------------------------------------------------------------------
@app.route("/")
def home():
    c = get_db()
    stock = c.execute("SELECT COUNT(*) c FROM accounts WHERE sold=0").fetchone()["c"]
    c.close()
    return render_template("home.html", stock_count=stock)


@app.route("/store")
def store():
    return _render_store(None)


@app.route("/store/silver")
def silver():
    return _render_store("silver")


@app.route("/store/golden")
def golden():
    return _render_store("gold")


def _render_store(cat):
    c = get_db()
    q = "SELECT * FROM accounts WHERE sold=0"
    args = []
    if cat:
        q += " AND plan_category=?"
        args.append(cat)
    q += " ORDER BY plan_category DESC, created_at DESC"
    rows = c.execute(q, args).fetchall()
    c.close()
    items = []
    for r in rows:
        days_left = None
        if r["expiry_date"]:
            try:
                end = datetime.fromisoformat(str(r["expiry_date"]).replace("Z", "+00:00"))
                if end.tzinfo is None:
                    end = end.replace(tzinfo=timezone.utc)
                days_left = max(0, (end - datetime.now(timezone.utc)).days)
            except Exception:
                days_left = None
        items.append({
            "id": r["id"],
            "plan_name": r["plan_name"] or "FILEWALE PLAN",
            "plan_category": r["plan_category"],
            "original_price": r["original_price"],
            "original_currency": r["original_currency"],
            "selling_price": r["selling_price"],
            "status": r["status"],
            "days_left": days_left,
            "expiry_date": r["expiry_date"],
            "discount": 50,
        })
    return render_template("store.html", items=items, category=cat)


# ------------------------------------------------------------------
# Auth
# ------------------------------------------------------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        require_csrf()
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        email = (request.form.get("email") or "").strip() or None
        if not username or len(password) < 6:
            flash("username required, password >= 6 chars", "err")
            return redirect(url_for("register"))
        c = get_db()
        try:
            c.execute(
                "INSERT INTO users (username, email, password_hash) VALUES (?,?,?)",
                (username, email, generate_password_hash(password)),
            )
            row = c.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
        except Exception:
            c.close()
            flash("username taken", "err")
            return redirect(url_for("register"))
        c.close()
        session["uid"] = row["id"]
        session["uname"] = username
        return redirect(url_for("home"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        require_csrf()
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        c = get_db()
        row = c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        c.close()
        if not row or not check_password_hash(row["password_hash"], password):
            flash("invalid credentials", "err")
            return redirect(url_for("login"))
        session["uid"] = row["id"]
        session["uname"] = row["username"]
        if row["is_admin"]:
            session["admin"] = True
        return redirect(request.args.get("next") or url_for("home"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


# ------------------------------------------------------------------
# Wallet
# ------------------------------------------------------------------
@app.route("/wallet")
@login_required
def wallet():
    c = get_db()
    txns = c.execute(
        "SELECT * FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT 40",
        (session["uid"],),
    ).fetchall()
    deposits = c.execute(
        "SELECT * FROM deposits WHERE user_id=? ORDER BY id DESC LIMIT 20",
        (session["uid"],),
    ).fetchall()
    c.close()
    return render_template("wallet.html", txns=txns, deposits=deposits)


@app.route("/add-balance", methods=["GET", "POST"])
@login_required
def add_balance():
    if request.method == "POST":
        require_csrf()
        try:
            amount = float(request.form.get("amount") or 0)
        except ValueError:
            amount = 0
        method = (request.form.get("method") or "").lower()
        txn_id = (request.form.get("txn_id") or "").strip()
        if amount <= 0 or method not in ("bkash", "nagad") or len(txn_id) < 4:
            flash("invalid deposit data", "err")
            return redirect(url_for("add_balance"))
        c = get_db()
        try:
            c.execute(
                "INSERT INTO deposits (user_id, amount, method, txn_id) VALUES (?,?,?,?)",
                (session["uid"], amount, method, txn_id),
            )
        except Exception:
            c.close()
            flash("this transaction id is already submitted", "err")
            return redirect(url_for("add_balance"))
        c.close()
        flash("deposit submitted — pending admin verification", "ok")
        return redirect(url_for("wallet"))
    return render_template("add_balance.html")


@app.route("/purchases")
@login_required
def purchases():
    c = get_db()
    rows = c.execute(
        """SELECT p.*, a.plan_name, a.plan_category, a.email_enc, a.password_enc,
                  a.expiry_date FROM purchases p
           JOIN accounts a ON a.id=p.account_id
           WHERE p.user_id=? ORDER BY p.id DESC""",
        (session["uid"],),
    ).fetchall()
    c.close()
    out = []
    for r in rows:
        out.append({
            "id": r["id"],
            "plan_name": r["plan_name"],
            "plan_category": r["plan_category"],
            "amount": r["amount"],
            "email": dec(r["email_enc"]),
            "password": dec(r["password_enc"]),
            "expiry_date": r["expiry_date"],
            "created_at": r["created_at"],
        })
    return render_template("purchases.html", purchases=out)


@app.route("/transactions")
@login_required
def transactions():
    c = get_db()
    rows = c.execute(
        "SELECT * FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT 200",
        (session["uid"],),
    ).fetchall()
    c.close()
    return render_template("transactions.html", txns=rows)


@app.route("/profile")
@login_required
def profile():
    c = get_db()
    u = c.execute("SELECT * FROM users WHERE id=?", (session["uid"],)).fetchone()
    c.close()
    return render_template("profile.html", u=u)


# ------------------------------------------------------------------
# Purchase
# ------------------------------------------------------------------
@app.route("/buy/<int:acc_id>", methods=["POST"])
@login_required
def buy(acc_id):
    require_csrf()
    c = get_db()
    try:
        c.execute("BEGIN IMMEDIATE")
        acc = c.execute(
            "SELECT * FROM accounts WHERE id=? AND sold=0", (acc_id,)
        ).fetchone()
        if not acc:
            c.execute("ROLLBACK")
            flash("account no longer available", "err")
            return redirect(url_for("store"))
        user = c.execute(
            "SELECT * FROM users WHERE id=?", (session["uid"],)
        ).fetchone()
        if user["balance"] < acc["selling_price"]:
            c.execute("ROLLBACK")
            flash("insufficient balance — add balance first", "err")
            return redirect(url_for("wallet"))
        new_balance = round(user["balance"] - acc["selling_price"], 2)
        now = datetime.utcnow().isoformat(timespec="seconds")
        c.execute("UPDATE users SET balance=? WHERE id=?", (new_balance, user["id"]))
        c.execute(
            "UPDATE accounts SET sold=1, sold_to=?, sold_at=? WHERE id=?",
            (user["id"], now, acc["id"]),
        )
        c.execute(
            "INSERT INTO purchases (user_id, account_id, amount) VALUES (?,?,?)",
            (user["id"], acc["id"], acc["selling_price"]),
        )
        c.execute(
            "INSERT INTO transactions (user_id, type, amount, balance_after, reason) "
            "VALUES (?,?,?,?,?)",
            (user["id"], "purchase", -acc["selling_price"], new_balance,
             f"buy account #{acc['id']}"),
        )
        c.execute("COMMIT")
        flash("purchase successful — credentials revealed in My Purchases", "ok")
        return redirect(url_for("purchases"))
    except Exception as e:
        try:
            c.execute("ROLLBACK")
        except Exception:
            pass
        flash(f"purchase failed: {e}", "err")
        return redirect(url_for("store"))
    finally:
        c.close()


# ------------------------------------------------------------------
# Admin login
# ------------------------------------------------------------------
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        require_csrf()
        u = (request.form.get("username") or "").strip()
        p = request.form.get("password") or ""
        c = get_db()
        row = c.execute(
            "SELECT * FROM users WHERE username=? AND is_admin=1", (u,)
        ).fetchone()
        c.close()
        if row and check_password_hash(row["password_hash"], p):
            session["uid"] = row["id"]
            session["uname"] = row["username"]
            session["admin"] = True
            return redirect(url_for("admin_dashboard"))
        flash("invalid admin credentials", "err")
        return redirect(url_for("admin_login"))
    return render_template("admin_login.html")


# ------------------------------------------------------------------
# Admin
# ------------------------------------------------------------------
@app.route("/admin")
@admin_required
def admin_dashboard():
    c = get_db()
    stats = {
        "users":   c.execute("SELECT COUNT(*) c FROM users").fetchone()["c"],
        "stock":   c.execute("SELECT COUNT(*) c FROM accounts WHERE sold=0").fetchone()["c"],
        "sold":    c.execute("SELECT COUNT(*) c FROM accounts WHERE sold=1").fetchone()["c"],
        "pending": c.execute("SELECT COUNT(*) c FROM deposits WHERE status='PENDING'").fetchone()["c"],
        "revenue": c.execute("SELECT COALESCE(SUM(amount),0) s FROM purchases").fetchone()["s"],
    }
    c.close()
    return render_template("admin_dashboard.html", stats=stats)


@app.route("/admin/stock")
@admin_required
def admin_stock():
    c = get_db()
    rows = c.execute(
        "SELECT * FROM accounts ORDER BY sold ASC, id DESC"
    ).fetchall()
    c.close()
    return render_template("admin_stock.html", rows=rows)


@app.route("/admin/add-account", methods=["GET", "POST"])
@admin_required
def admin_add_account():
    if request.method == "POST":
        require_csrf()
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""
        manual_price = request.form.get("original_price")
        manual_price = float(manual_price) if manual_price else None
        manual_currency = (request.form.get("original_currency") or "USD").upper()
        manual_sell = request.form.get("selling_price")
        manual_sell = float(manual_sell) if manual_sell else None
        cost = request.form.get("cost")
        cost = float(cost) if cost else 0
        notes = (request.form.get("notes") or "").strip()
        category_override = (request.form.get("plan_category") or "auto").lower()

        plan_name = None
        original_price = manual_price
        original_currency = manual_currency
        plan_category = "silver"
        expiry_date = None
        status = "OFFLINE"

        client = FileWaleClient(Config.FILEWALE_API)
        try:
            snap = client.snapshot(email, password)
            sub = snap.get("subscription") or {}
            plan = sub.get("plan") or {}
            plan_name = plan.get("name") or None
            api_price = plan.get("price")
            api_currency = plan.get("currency")
            if api_price is not None:
                original_price = float(api_price)
            if api_currency:
                original_currency = str(api_currency).upper()
            if plan_name:
                plan_category = categorize(plan_name)
            end = sub.get("endDate")
            if end:
                expiry_date = end
                try:
                    end_dt = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
                    if end_dt.tzinfo is None:
                        end_dt = end_dt.replace(tzinfo=timezone.utc)
                    status = "LIVE" if end_dt > datetime.now(timezone.utc) else "EXPIRED"
                except Exception:
                    status = "LIVE"
            else:
                status = "LIVE"
        except FileWaleError as e:
            if not manual_price:
                flash(
                    f"api lookup failed ({e}) — enter original price manually",
                    "err",
                )
                return redirect(url_for("admin_add_account"))
            status = "OFFLINE"

        if category_override in ("silver", "gold"):
            plan_category = category_override

        if original_price is None:
            flash("no original price from API and none entered — cannot continue", "err")
            return redirect(url_for("admin_add_account"))

        selling_price = (
            manual_sell if manual_sell is not None else round(original_price * 0.5, 2)
        )

        c = get_db()
        c.execute(
            """INSERT INTO accounts
               (email_enc, password_enc, plan_name, plan_category, original_price,
                original_currency, selling_price, cost, status, expiry_date,
                last_sync, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                enc(email), enc(password), plan_name, plan_category, original_price,
                original_currency, selling_price, cost, status, expiry_date,
                datetime.utcnow().isoformat(timespec="seconds"), notes,
            ),
        )
        c.close()
        flash("account added to stock", "ok")
        return redirect(url_for("admin_stock"))
    return render_template("admin_add_account.html")


@app.route("/admin/edit-account/<int:acc_id>", methods=["GET", "POST"])
@admin_required
def admin_edit_account(acc_id):
    c = get_db()
    row = c.execute("SELECT * FROM accounts WHERE id=?", (acc_id,)).fetchone()
    if not row:
        c.close()
        abort(404)
    if request.method == "POST":
        require_csrf()
        selling = request.form.get("selling_price")
        category = request.form.get("plan_category")
        notes = request.form.get("notes")
        status = request.form.get("status")
        try:
            selling_f = float(selling) if selling else row["selling_price"]
        except ValueError:
            selling_f = row["selling_price"]
        c.execute(
            "UPDATE accounts SET selling_price=?, plan_category=?, notes=?, status=? "
            "WHERE id=?",
            (
                selling_f,
                category if category in ("silver", "gold") else row["plan_category"],
                notes if notes is not None else row["notes"],
                status or row["status"],
                acc_id,
            ),
        )
        c.close()
        flash("account updated", "ok")
        return redirect(url_for("admin_stock"))
    c.close()
    return render_template("admin_edit_account.html", row=row)


@app.route("/admin/delete-account/<int:acc_id>", methods=["POST"])
@admin_required
def admin_delete_account(acc_id):
    require_csrf()
    c = get_db()
    c.execute("DELETE FROM accounts WHERE id=? AND sold=0", (acc_id,))
    c.close()
    flash("account removed", "ok")
    return redirect(url_for("admin_stock"))


@app.route("/admin/sync/<int:acc_id>", methods=["POST"])
@admin_required
def admin_sync(acc_id):
    require_csrf()
    c = get_db()
    row = c.execute("SELECT * FROM accounts WHERE id=?", (acc_id,)).fetchone()
    c.close()
    if not row:
        abort(404)
    client = FileWaleClient(Config.FILEWALE_API)
    try:
        snap = client.snapshot(dec(row["email_enc"]), dec(row["password_enc"]))
        sub = snap.get("subscription") or {}
        plan = sub.get("plan") or {}
        end = sub.get("endDate")
        status = row["status"]
        if end:
            try:
                end_dt = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=timezone.utc)
                status = "LIVE" if end_dt > datetime.now(timezone.utc) else "EXPIRED"
            except Exception:
                status = "LIVE"
        else:
            status = "LIVE"
        c = get_db()
        c.execute(
            "UPDATE accounts SET status=?, last_sync=?, "
            "expiry_date=COALESCE(?, expiry_date), "
            "plan_name=COALESCE(?, plan_name) WHERE id=?",
            (
                status,
                datetime.utcnow().isoformat(timespec="seconds"),
                end,
                plan.get("name"),
                acc_id,
            ),
        )
        c.close()
        flash(f"synced — status {status}", "ok")
    except FileWaleError as e:
        c = get_db()
        c.execute("UPDATE accounts SET status='OFFLINE' WHERE id=?", (acc_id,))
        c.close()
        flash(f"sync failed: {e}", "err")
    return redirect(url_for("admin_stock"))


@app.route("/admin/users")
@admin_required
def admin_users():
    c = get_db()
    rows = c.execute("SELECT * FROM users ORDER BY id DESC").fetchall()
    c.close()
    return render_template("admin_users.html", rows=rows)


@app.route("/admin/wallet-op", methods=["POST"])
@admin_required
def admin_wallet_op():
    require_csrf()
    try:
        uid = int(request.form.get("user_id"))
        amount = float(request.form.get("amount"))
    except (ValueError, TypeError):
        flash("invalid amount/user", "err")
        return redirect(url_for("admin_users"))
    reason = (request.form.get("reason") or "manual adjust").strip()
    if amount == 0:
        flash("amount cannot be zero", "err")
        return redirect(url_for("admin_users"))
    c = get_db()
    try:
        c.execute("BEGIN IMMEDIATE")
        u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if not u:
            c.execute("ROLLBACK")
            flash("user not found", "err")
            return redirect(url_for("admin_users"))
        new_balance = round(u["balance"] + amount, 2)
        if new_balance < 0:
            c.execute("ROLLBACK")
            flash("balance cannot go negative", "err")
            return redirect(url_for("admin_users"))
        c.execute("UPDATE users SET balance=? WHERE id=?", (new_balance, uid))
        c.execute(
            "INSERT INTO transactions (user_id, type, amount, balance_after, reason) "
            "VALUES (?,?,?,?,?)",
            (uid,
             "admin_credit" if amount > 0 else "admin_debit",
             amount, new_balance, reason),
        )
        c.execute("COMMIT")
        flash("balance updated", "ok")
    except Exception as e:
        try:
            c.execute("ROLLBACK")
        except Exception:
            pass
        flash(f"failed: {e}", "err")
    finally:
        c.close()
    return redirect(url_for("admin_users"))


@app.route("/admin/deposits")
@admin_required
def admin_deposits():
    c = get_db()
    rows = c.execute(
        """SELECT d.*, u.username FROM deposits d
           JOIN users u ON u.id=d.user_id ORDER BY d.id DESC"""
    ).fetchall()
    c.close()
    return render_template("admin_deposits.html", rows=rows)


@app.route("/admin/deposits/<int:dep_id>/<action>", methods=["POST"])
@admin_required
def admin_deposit_action(dep_id, action):
    require_csrf()
    if action not in ("approve", "reject"):
        abort(400)
    note = (request.form.get("admin_note") or "").strip()
    c = get_db()
    try:
        c.execute("BEGIN IMMEDIATE")
        d = c.execute("SELECT * FROM deposits WHERE id=?", (dep_id,)).fetchone()
        if not d or d["status"] != "PENDING":
            c.execute("ROLLBACK")
            flash("deposit not pending", "err")
            return redirect(url_for("admin_deposits"))
        if action == "reject":
            c.execute(
                "UPDATE deposits SET status='REJECTED', admin_note=?, "
                "verified_at=datetime('now'), verified_by=? WHERE id=?",
                (note, session["uid"], dep_id),
            )
            c.execute("COMMIT")
            flash("deposit rejected", "ok")
            return redirect(url_for("admin_deposits"))
        u = c.execute("SELECT * FROM users WHERE id=?", (d["user_id"],)).fetchone()
        new_balance = round(u["balance"] + d["amount"], 2)
        c.execute("UPDATE users SET balance=? WHERE id=?", (new_balance, u["id"]))
        c.execute(
            "INSERT INTO transactions (user_id, type, amount, balance_after, reason) "
            "VALUES (?,?,?,?,?)",
            (u["id"], "deposit", d["amount"], new_balance,
             f"{d['method']} deposit #{d['id']}"),
        )
        c.execute(
            "UPDATE deposits SET status='APPROVED', admin_note=?, "
            "verified_at=datetime('now'), verified_by=? WHERE id=?",
            (note, session["uid"], dep_id),
        )
        c.execute("COMMIT")
        flash("deposit approved and credited", "ok")
    except Exception as e:
        try:
            c.execute("ROLLBACK")
        except Exception:
            pass
        flash(f"failed: {e}", "err")
    finally:
        c.close()
    return redirect(url_for("admin_deposits"))


@app.route("/admin/transactions")
@admin_required
def admin_transactions():
    c = get_db()
    rows = c.execute(
        """SELECT t.*, u.username FROM transactions t
           JOIN users u ON u.id=t.user_id ORDER BY t.id DESC LIMIT 300"""
    ).fetchall()
    c.close()
    return render_template("admin_transactions.html", rows=rows)


@app.route("/admin/banner", methods=["GET", "POST"])
@admin_required
def admin_banner():
    if request.method == "POST":
        require_csrf()
        c = get_db()
        for k in ("silver_banner_enabled", "golden_banner_enabled"):
            c.execute(
                "INSERT INTO settings (key, value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (k, "1" if request.form.get(k) else "0"),
            )
        for k in ("silver_banner_text", "golden_banner_text"):
            c.execute(
                "INSERT INTO settings (key, value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (k, (request.form.get(k) or "").strip()),
            )
        c.close()
        flash("banners updated", "ok")
        return redirect(url_for("admin_banner"))
    c = get_db()
    s = {row["key"]: row["value"] for row in c.execute("SELECT * FROM settings")}
    c.close()
    return render_template("admin_banner.html", s=s)


@app.route("/admin/settings", methods=["GET", "POST"])
@admin_required
def admin_settings():
    if request.method == "POST":
        require_csrf()
        c = get_db()
        c.execute(
            "INSERT INTO settings (key, value) VALUES ('site_title', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ((request.form.get("site_title") or "FILEWALE PREMIUM").strip(),),
        )
        c.close()
        flash("settings saved", "ok")
        return redirect(url_for("admin_settings"))
    c = get_db()
    s = {row["key"]: row["value"] for row in c.execute("SELECT * FROM settings")}
    c.close()
    return render_template("admin_settings.html", s=s)


@app.route("/admin/sold")
@admin_required
def admin_sold():
    c = get_db()
    rows = c.execute(
        """SELECT a.*, u.username AS buyer FROM accounts a
           LEFT JOIN users u ON u.id=a.sold_to
           WHERE a.sold=1 ORDER BY a.sold_at DESC"""
    ).fetchall()
    c.close()
    return render_template("admin_sold.html", rows=rows)


# ------------------------------------------------------------------
# Live stock JSON
# ------------------------------------------------------------------
@app.route("/api/live-stock")
def live_stock():
    c = get_db()
    total = c.execute(
        "SELECT COUNT(*) c FROM accounts WHERE sold=0"
    ).fetchone()["c"]
    live = c.execute(
        "SELECT COUNT(*) c FROM accounts WHERE sold=0 AND status='LIVE'"
    ).fetchone()["c"]
    c.close()
    return jsonify({"total": total, "live": live})


# ------------------------------------------------------------------
# Error handlers
# ------------------------------------------------------------------
@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(500)
def handle_error(e):
    code = getattr(e, "code", 500)
    return render_template("error.html", code=code, msg=str(e)), code


# ------------------------------------------------------------------
# Entrypoint
# ------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
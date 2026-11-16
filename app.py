import os
import json
import time
import cloudscraper
from flask import Flask, request, jsonify, render_template_string

app = Flask(__name__)
scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'ios', 'mobile': True})

HTML_UI = """
<!doctype html>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
    body { font-family: -apple-system, sans-serif; background: #121212; color: #e0e0e0; padding: 15px; }
    textarea { width: 100%; box-sizing: border-box; padding: 10px; margin-bottom: 10px; border-radius: 8px; border: 1px solid #333; background: #1e1e1e; color: #fff; font-size: 14px; font-family: monospace; }
    button { width: 100%; padding: 14px; background: #ff3b30; color: white; border: none; border-radius: 8px; font-size: 16px; font-weight: bold; margin-bottom: 20px;}
    pre { background: #000; padding: 15px; border-radius: 8px; overflow-x: auto; font-size: 14px; white-space: pre-wrap; }
</style>
<h2>Lucky Shot Exploit</h2>
<p style="font-size:14px; color:#aaa;">Жми кнопку. Если Cloudflare блокирует — увидим HTML в ответе.</p>

<button onclick="run()">PLAY LUCKY SHOT</button>
<pre id="out">Waiting...</pre>

<script>
async function run() {
    const btn = document.querySelector('button');
    const out = document.getElementById('out');
    btn.disabled = true; btn.textContent = "Sending...";
    out.textContent = "Sending request to api.gates-market.io...";
    
    const payload = {
      "game_id": 115350,
      "round_id": 115350,
      "grid_size": 5,
      "listing_kind": "NFT",
      "listing_id": 27741,
      "listing_price": "4.40",
      "chosen_cells": [
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0],
        [0, 0, 1, 0, 0],
        [0, 0, 1, 0, 0],
        [0, 0, 0, 0, 0]
      ],
      "amount_bet": 0.01
    };

    try {
        const r = await fetch('/api/lucky-shot', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ initData: localStorage.getItem('tgInitData'), payload: payload })
        });
        const data = await r.json();
        out.textContent = JSON.stringify(data, null, 2);
    } catch (e) {
        out.textContent = "Error: " + e.message;
    } finally { btn.disabled = false; btn.textContent = "PLAY LUCKY SHOT"; }
}
if (!localStorage.getItem('tgInitData')) {
    const raw = prompt("Вставь свой initData (один раз):");
    if (raw) localStorage.setItem('tgInitData', raw.trim());
}
</script>
"""

@app.route("/")
def ui():
    return render_template_string(HTML_UI)

@app.route("/api/lucky-shot", methods=["POST"])
def lucky_shot():
    body = request.get_json()
    init_data = body.get("initData")
    payload = body.get("payload")
    
    if not init_data: return jsonify({"error": "No initData"}), 400
    
    url = "https://api.gates-market.io/api/v1/games/lucky-shot/game"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Telegram-Init-Data": init_data,
        "Origin": "https://tg-app.gates-market.io",
        "Referer": "https://tg-app.gates-market.io/"
    }
    
    try:
        r = scraper.post(url, headers=headers, json=payload, timeout=20)
        # Пытаемся распарсить JSON, если не получается — отдаем сырой текст
        try:
            res_json = r.json()
        except:
            res_json = r.text[:300] 
            
        return jsonify({"status": r.status_code, "response": res_json})
    except Exception as e:
        return jsonify({"error": str(e)})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

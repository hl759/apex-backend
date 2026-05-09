from flask import Flask, jsonify
from flask_cors import CORS
import requests
from datetime import datetime
import os

app = Flask(__name__)
CORS(app)  # Permite chamadas do frontend

RAPIDAPI_KEY  = os.environ.get("RAPIDAPI_KEY", "348f64cc4bmsh83ca5a64d524287p1482b1jsn19e62eaf11f5")
RAPIDAPI_HOST = "apifootball3.p.rapidapi.com"
RAPIDAPI_BASE = "https://apifootball3.p.rapidapi.com"

HEADERS = {
    "x-rapidapi-key": RAPIDAPI_KEY,
    "x-rapidapi-host": RAPIDAPI_HOST
}

@app.route("/")
def index():
    return jsonify({"status": "APEX TRADE Backend online", "version": "1.0"})

@app.route("/fixtures/today")
def fixtures_today():
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        res = requests.get(
            f"{RAPIDAPI_BASE}/?action=get_events&from={today}&to={today}",
            headers=HEADERS,
            timeout=10
        )
        data = res.json()
        events = data if isinstance(data, list) else list(data.values())

        # Filtra e normaliza
        fixtures = []
        for e in events:
            status = e.get("match_status", "")
            if status in ["Finished", "FT", "AET", "PEN"]:
                continue
            fixtures.append({
                "id":       e.get("match_id", ""),
                "home":     e.get("match_hometeam_name", ""),
                "away":     e.get("match_awayteam_name", ""),
                "league":   e.get("league_name", ""),
                "country":  e.get("country_name", ""),
                "time":     e.get("match_time", ""),
                "date":     e.get("match_date", today),
                "status":   status,
                "score":    f"{e.get('match_hometeam_score','-')}-{e.get('match_awayteam_score','-')}",
                "elapsed":  e.get("match_elapsed", 0),
            })

        return jsonify({"success": True, "count": len(fixtures), "fixtures": fixtures[:20]})

    except Exception as ex:
        return jsonify({"success": False, "error": str(ex)}), 500

@app.route("/health")
def health():
    return jsonify({"ok": True, "time": datetime.now().isoformat()})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

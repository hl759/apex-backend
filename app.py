from flask import Flask, jsonify
from flask_cors import CORS
import requests
from datetime import datetime
import os

app = Flask(__name__)
CORS(app)

RAPIDAPI_KEY  = os.environ.get("RAPIDAPI_KEY", "348f64cc4bmsh83ca5a64d524287p1482b1jsn19e62eaf11f5")
RAPIDAPI_HOST = "apifootball3.p.rapidapi.com"
RAPIDAPI_BASE = "https://apifootball3.p.rapidapi.com"

HEADERS = {
    "x-rapidapi-key": RAPIDAPI_KEY,
    "x-rapidapi-host": RAPIDAPI_HOST
}

@app.route("/")
def index():
    return jsonify({"status": "APEX TRADE Backend online", "version": "1.1"})

@app.route("/health")
def health():
    return jsonify({"ok": True, "time": datetime.now().isoformat()})

@app.route("/debug")
def debug():
    """Retorna resposta bruta da API para diagnóstico"""
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        res = requests.get(
            f"{RAPIDAPI_BASE}/?action=get_events&from={today}&to={today}",
            headers=HEADERS,
            timeout=15
        )
        return jsonify({
            "status_code": res.status_code,
            "content_type": res.headers.get("content-type", ""),
            "raw_text": res.text[:2000],  # primeiros 2000 chars
        })
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500

@app.route("/fixtures/today")
def fixtures_today():
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        res = requests.get(
            f"{RAPIDAPI_BASE}/?action=get_events&from={today}&to={today}",
            headers=HEADERS,
            timeout=15
        )

        # Log status
        if res.status_code != 200:
            return jsonify({
                "success": False,
                "error": f"API retornou status {res.status_code}",
                "body": res.text[:500]
            }), 500

        # Tenta parsear JSON
        try:
            data = res.json()
        except Exception:
            return jsonify({
                "success": False,
                "error": "API não retornou JSON válido",
                "body": res.text[:500]
            }), 500

        # Normaliza estrutura — API pode retornar lista, dict ou dict de eventos
        fixtures_raw = []
        if isinstance(data, list):
            fixtures_raw = data
        elif isinstance(data, dict):
            # Pode ser {"error": "..."} ou {0: {...}, 1: {...}}
            if "error" in data:
                return jsonify({"success": False, "error": data["error"]}), 500
            fixtures_raw = list(data.values())

        # Filtra e normaliza cada evento
        fixtures = []
        for e in fixtures_raw:
            if not isinstance(e, dict):
                continue
            status = str(e.get("match_status", ""))
            if status in ["Finished", "FT", "AET", "PEN", "Cancelled", "Postponed"]:
                continue
            fixtures.append({
                "id":      str(e.get("match_id", "")),
                "home":    e.get("match_hometeam_name", ""),
                "away":    e.get("match_awayteam_name", ""),
                "league":  e.get("league_name", ""),
                "country": e.get("country_name", ""),
                "time":    e.get("match_time", ""),
                "date":    e.get("match_date", today),
                "status":  status,
                "score":   f"{e.get('match_hometeam_score','-')}-{e.get('match_awayteam_score','-')}",
                "elapsed": e.get("match_elapsed", 0),
            })

        return jsonify({
            "success": True,
            "count": len(fixtures),
            "fixtures": fixtures[:20]
        })

    except Exception as ex:
        return jsonify({"success": False, "error": str(ex)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

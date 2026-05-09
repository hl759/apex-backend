from flask import Flask, jsonify
from flask_cors import CORS
import requests
from datetime import datetime
import os

app = Flask(__name__)
CORS(app)

# Chave direta da api-sports.io (sem RapidAPI)
API_KEY  = os.environ.get("API_KEY", "98e06cbc3c531496be35529357044cfc")
API_BASE = "https://v3.football.api-sports.io"

HEADERS = {
    "x-apisports-key": API_KEY
}

@app.route("/")
def index():
    return jsonify({"status": "APEX TRADE Backend online", "version": "1.2"})

@app.route("/health")
def health():
    return jsonify({"ok": True, "time": datetime.now().isoformat()})

@app.route("/debug")
def debug():
    """Retorna resposta bruta para diagnóstico"""
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        res = requests.get(
            f"{API_BASE}/fixtures?date={today}&timezone=America/Sao_Paulo",
            headers=HEADERS,
            timeout=15
        )
        return jsonify({
            "status_code": res.status_code,
            "content_type": res.headers.get("content-type", ""),
            "raw": res.json() if res.status_code == 200 else res.text[:1000]
        })
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500

@app.route("/fixtures/today")
def fixtures_today():
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        res = requests.get(
            f"{API_BASE}/fixtures?date={today}&timezone=America/Sao_Paulo",
            headers=HEADERS,
            timeout=15
        )

        if res.status_code != 200:
            return jsonify({
                "success": False,
                "error": f"API retornou status {res.status_code}",
                "body": res.text[:500]
            }), 500

        data = res.json()

        # Verifica erros da API
        errors = data.get("errors", {})
        if errors:
            return jsonify({"success": False, "error": str(errors)}), 500

        response = data.get("response", [])
        if not response:
            return jsonify({"success": True, "count": 0, "fixtures": []})

        fixtures = []
        for f in response:
            status_short = f.get("fixture", {}).get("status", {}).get("short", "")
            # Filtra apenas jogos ativos ou a jogar
            if status_short in ["FT", "AET", "PEN", "CANC", "PST", "ABD", "AWD", "WO"]:
                continue

            fixture_date = f.get("fixture", {}).get("date", "")
            try:
                time_str = datetime.fromisoformat(fixture_date.replace("Z", "+00:00")).strftime("%H:%M")
            except Exception:
                time_str = ""

            home_score = f.get("goals", {}).get("home")
            away_score = f.get("goals", {}).get("away")
            score = f"{home_score}-{away_score}" if home_score is not None else "-"

            fixtures.append({
                "id":      str(f.get("fixture", {}).get("id", "")),
                "home":    f.get("teams", {}).get("home", {}).get("name", ""),
                "away":    f.get("teams", {}).get("away", {}).get("name", ""),
                "league":  f.get("league", {}).get("name", ""),
                "country": f.get("league", {}).get("country", ""),
                "time":    time_str,
                "status":  status_short,
                "score":   score,
                "elapsed": f.get("fixture", {}).get("status", {}).get("elapsed") or 0,
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

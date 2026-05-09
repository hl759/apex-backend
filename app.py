from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
from datetime import datetime
import os
import json

app = Flask(__name__)
CORS(app)

# api-sports.io
API_KEY  = os.environ.get("API_KEY", "98e06cbc3c531496be35529357044cfc")
API_BASE = "https://v3.football.api-sports.io"
API_HEADERS = {"x-apisports-key": API_KEY}

# Anthropic
ANTHROPIC_KEY  = os.environ.get("ANTHROPIC_KEY", "")
ANTHROPIC_BASE = "https://api.anthropic.com/v1/messages"

SYSTEM_PROMPT = """Você é APEX TRADE — uma inteligência artificial de elite especializada em trade esportivo de futebol, construída sobre a sabedoria coletiva dos 100 traders esportivos profissionais mais lucrativos do mundo.

MISSÃO: Identificar oportunidades de valor esperado positivo (EV+) com máxima precisão estatística.

REGRAS INEGOCIÁVEIS:
1. NUNCA prometer lucro garantido
2. SEMPRE informar o risco
3. NUNCA recomendar all-in
4. Priorizar consistência acima de lucro rápido

FORMATO — responda SEMPRE em JSON puro (sem markdown, sem backticks):

{
  "type": "analysis",
  "matches": [
    {
      "id": "id",
      "homeTeam": "Time Casa",
      "awayTeam": "Time Visitante",
      "league": "Liga",
      "country": "País",
      "time": "HH:MM",
      "status": "pre-live",
      "score": "-",
      "xgHome": 1.4,
      "xgAway": 1.0,
      "matchContext": "Contexto técnico",
      "opportunities": [
        {
          "market": "Over 2.5 Gols",
          "selection": "Over 2.5",
          "odds": 1.85,
          "probability": 65,
          "confidence": 78,
          "ev": 5.2,
          "stake": 3,
          "timing": "Pré-live",
          "cashout": "Momento ideal de saída",
          "riskLevel": "baixo",
          "rationale": "Explicação técnica detalhada",
          "keyStats": ["stat1", "stat2"],
          "suspiciousMovement": false,
          "consistencyScore": 76
        }
      ]
    }
  ],
  "dailySummary": "Resumo do dia",
  "marketAlert": null
}

Selecione TOP 5 jogos com maior EV+. Priorize qualidade."""


@app.route("/")
def index():
    return jsonify({"status": "APEX TRADE Backend online", "version": "2.0"})

@app.route("/health")
def health():
    return jsonify({"ok": True, "time": datetime.now().isoformat()})

@app.route("/fixtures/today")
def fixtures_today():
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        res = requests.get(
            f"{API_BASE}/fixtures?date={today}&timezone=America/Sao_Paulo",
            headers=API_HEADERS,
            timeout=15
        )
        if res.status_code != 200:
            return jsonify({"success": False, "error": f"API status {res.status_code}"}), 500

        data = res.json()
        errors = data.get("errors", {})
        if errors:
            return jsonify({"success": False, "error": str(errors)}), 500

        response = data.get("response", [])
        fixtures = []
        for f in response:
            status_short = f.get("fixture", {}).get("status", {}).get("short", "")
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

        return jsonify({"success": True, "count": len(fixtures), "fixtures": fixtures[:20]})

    except Exception as ex:
        return jsonify({"success": False, "error": str(ex)}), 500


@app.route("/analyze", methods=["POST"])
def analyze():
    """Recebe fixtures e retorna análise da IA — chamada server-side"""
    try:
        body = request.get_json()
        fixtures = body.get("fixtures", [])
        risk_mode = body.get("riskMode", "moderado")
        history = body.get("history", [])

        if not fixtures:
            return jsonify({"success": False, "error": "Nenhum fixture enviado"}), 400

        prompt = f"""Dados reais da API-Football — jogos de hoje {datetime.now().strftime('%d/%m/%Y')}:

{json.dumps(fixtures, ensure_ascii=False, indent=2)}

Como o melhor trader do mundo, selecione os TOP 5 jogos com maior EV+ potencial.
Para cada um gere oportunidades detalhadas com odds estimadas de mercado, gestão para perfil "{risk_mode}".
Responda APENAS com o JSON de análise."""

        messages = history + [{"role": "user", "content": prompt}]

        # Chama Anthropic server-side
        res = requests.post(
            ANTHROPIC_BASE,
            headers={
                "Content-Type": "application/json",
                "x-api-key": ANTHROPIC_KEY,
                "anthropic-version": "2023-06-01"
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 4000,
                "system": SYSTEM_PROMPT,
                "messages": messages
            },
            timeout=60
        )

        if res.status_code != 200:
            return jsonify({"success": False, "error": f"Anthropic error {res.status_code}: {res.text[:300]}"}), 500

        data = res.json()
        raw = "".join(b.get("text", "") for b in data.get("content", []))

        try:
            parsed = json.loads(raw.replace("```json", "").replace("```", "").strip())
        except Exception:
            parsed = {"type": "chat", "message": raw}

        return jsonify({"success": True, "result": parsed})

    except Exception as ex:
        return jsonify({"success": False, "error": str(ex)}), 500


@app.route("/chat", methods=["POST"])
def chat():
    """Chat livre com a IA"""
    try:
        body = request.get_json()
        message = body.get("message", "")
        risk_mode = body.get("riskMode", "moderado")
        history = body.get("history", [])

        if not message:
            return jsonify({"success": False, "error": "Mensagem vazia"}), 400

        messages = history + [{"role": "user", "content": f"{message}\n\n[Perfil: {risk_mode}]"}]

        res = requests.post(
            ANTHROPIC_BASE,
            headers={
                "Content-Type": "application/json",
                "x-api-key": ANTHROPIC_KEY,
                "anthropic-version": "2023-06-01"
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1000,
                "system": SYSTEM_PROMPT,
                "messages": messages
            },
            timeout=60
        )

        if res.status_code != 200:
            return jsonify({"success": False, "error": f"Anthropic error {res.status_code}"}), 500

        data = res.json()
        raw = "".join(b.get("text", "") for b in data.get("content", []))

        try:
            parsed = json.loads(raw.replace("```json", "").replace("```", "").strip())
        except Exception:
            parsed = {"type": "chat", "message": raw}

        return jsonify({"success": True, "result": parsed})

    except Exception as ex:
        return jsonify({"success": False, "error": str(ex)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

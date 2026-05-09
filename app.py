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

# Groq
GROQ_KEY  = os.environ.get("GROQ_KEY", "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")
GROQ_BASE = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"

SYSTEM_PROMPT = """Você é APEX TRADE — uma inteligência artificial de elite especializada em trade esportivo de futebol, construída sobre a sabedoria coletiva dos 100 traders esportivos profissionais mais lucrativos do mundo.

MISSÃO: Identificar oportunidades de valor esperado positivo (EV+) com máxima precisão estatística.

REGRAS INEGOCIÁVEIS:
1. NUNCA prometer lucro garantido
2. SEMPRE informar o risco
3. NUNCA recomendar all-in
4. Priorizar consistência acima de lucro rápido

FORMATO — responda SEMPRE em JSON puro (sem markdown, sem backticks, sem texto fora do JSON):

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

Para chat: {"type":"chat","message":"resposta detalhada"}

Selecione TOP 5 jogos com maior EV+. Priorize qualidade sobre quantidade."""


def call_groq(messages, max_tokens=4000):
    """Chama a API do Groq"""
    res = requests.post(
        GROQ_BASE,
        headers={
            "Authorization": f"Bearer {GROQ_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "model": GROQ_MODEL,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + messages,
            "max_tokens": max_tokens,
            "temperature": 0.7
        },
        timeout=60
    )
    if res.status_code != 200:
        raise Exception(f"Groq error {res.status_code}: {res.text[:300]}")
    data = res.json()
    return data["choices"][0]["message"]["content"]


def parse_ai_response(raw):
    """Tenta parsear JSON da resposta da IA"""
    try:
        clean = raw.replace("```json", "").replace("```", "").strip()
        # Pega só o JSON se tiver texto antes/depois
        start = clean.find("{")
        end = clean.rfind("}") + 1
        if start >= 0 and end > start:
            clean = clean[start:end]
        return json.loads(clean)
    except Exception:
        return {"type": "chat", "message": raw}


@app.route("/")
def index():
    return jsonify({"status": "APEX TRADE Backend online", "version": "3.0", "ai": "Groq/LLaMA-3.3-70b"})

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
    try:
        body = request.get_json()
        fixtures = body.get("fixtures", [])
        risk_mode = body.get("riskMode", "moderado")
        history = body.get("history", [])

        if not fixtures:
            return jsonify({"success": False, "error": "Nenhum fixture enviado"}), 400

        prompt = f"""Dados reais da API-Football — jogos de hoje {datetime.now().strftime('%d/%m/%Y')}:

{json.dumps(fixtures, ensure_ascii=False, indent=2)}

Analise como o melhor trader do mundo. Selecione os TOP 5 com maior EV+.
Gere oportunidades detalhadas com odds estimadas de mercado para perfil "{risk_mode}".
Responda APENAS com o JSON de análise."""

        messages = history[-4:] + [{"role": "user", "content": prompt}]
        raw = call_groq(messages, max_tokens=4000)
        parsed = parse_ai_response(raw)

        return jsonify({"success": True, "result": parsed})

    except Exception as ex:
        return jsonify({"success": False, "error": str(ex)}), 500


@app.route("/chat", methods=["POST"])
def chat():
    try:
        body = request.get_json()
        message = body.get("message", "")
        risk_mode = body.get("riskMode", "moderado")
        history = body.get("history", [])

        if not message:
            return jsonify({"success": False, "error": "Mensagem vazia"}), 400

        messages = history[-6:] + [{"role": "user", "content": f"{message}\n\n[Perfil: {risk_mode}]"}]
        raw = call_groq(messages, max_tokens=1000)
        parsed = parse_ai_response(raw)

        return jsonify({"success": True, "result": parsed})

    except Exception as ex:
        return jsonify({"success": False, "error": str(ex)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

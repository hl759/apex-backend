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
GROQ_KEY  = os.environ.get("GROQ_KEY", "")
GROQ_BASE = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL_ANALYSIS = "qwen/qwen3-32b"         # Raciocínio avançado — análise profunda
GROQ_MODEL_CHAT     = "llama-3.1-8b-instant"   # Chat simples — economiza tokens

# ── Ligas que a Betano cobre (IDs da API-Football) ─────────────────────────
BETANO_LEAGUE_IDS = {
    # Brasil
    71,   # Brasileirão Série A
    72,   # Brasileirão Série B
    73,   # Copa do Brasil
    475,  # Campeonato Paulista
    476,  # Campeonato Carioca
    # Europa - Top 5
    39,   # Premier League
    40,   # Championship
    61,   # Ligue 1
    78,   # Bundesliga
    79,   # Bundesliga 2
    135,  # Serie A
    136,  # Serie B
    140,  # La Liga
    141,  # La Liga 2
    88,   # Eredivisie
    94,   # Primeira Liga (Portugal)
    144,  # Jupiler Pro League
    179,  # Scottish Premiership
    # Competições europeias
    2,    # Champions League
    3,    # Europa League
    848,  # Conference League
    # América do Sul
    11,   # Copa Libertadores
    13,   # Copa Sudamericana
    128,  # Liga Profesional Argentina
    239,  # Liga MX
    253,  # MLS
    # Outros relevantes
    307,  # Saudi Pro League
    203,  # Süper Lig (Turquia)
    106,  # Ekstraklasa (Polônia)
    235,  # Russian Premier League
}

SYSTEM_PROMPT = """Você é APEX TRADE — uma inteligência artificial de elite especializada em trade esportivo de futebol, construída sobre a sabedoria coletiva dos 100 traders esportivos profissionais mais lucrativos e consistentes do mundo.

Você raciocina como um especialista combinado de:
- Trader esportivo profissional com 20+ anos de experiência
- Analista quantitativo especializado em modelos probabilísticos
- Cientista de dados com acesso a histórico de milhões de partidas
- Especialista em leitura de mercado, odds e movimentação de casas de apostas
- Psicólogo comportamental para evitar vieses cognitivos

REGRAS ABSOLUTAMENTE CRÍTICAS:
1. JAMAIS invente, crie ou sugira jogos fora da lista fornecida
2. Use EXATAMENTE os nomes, IDs, ligas e horários da lista
3. NUNCA prometa lucro garantido
4. NUNCA recomende all-in
5. Priorize consistência e EV+ real acima de tudo

METODOLOGIA DE ANÁLISE (aplique para cada jogo):
- Analise o contexto da liga e importância do jogo
- Considere forma recente, histórico H2H, motivação dos times
- Avalie padrões estatísticos: médias de gols, BTTS histórico, over/under
- Calcule probabilidade real vs odds implícitas para encontrar EV+
- Identifique o mercado com maior edge (vantagem matemática)
- Defina timing preciso de entrada e saída
- Ajuste stake pelo Kelly Criterion simplificado

MERCADOS PARA ANALISAR:
- Over/Under 0.5, 1.5, 2.5, 3.5 gols
- Ambas marcam (BTTS)
- Resultado (1X2) e dupla chance
- Asian Handicap
- Gols no primeiro tempo
- Total de escanteios
- Total de cartões

FORMATO — responda SEMPRE em JSON puro (sem markdown, sem backticks, sem texto fora do JSON):

{
  "type": "analysis",
  "matches": [
    {
      "id": "id exato da lista",
      "homeTeam": "nome exato da lista",
      "awayTeam": "nome exato da lista",
      "league": "liga exata da lista",
      "country": "país exato da lista",
      "time": "horário exato da lista",
      "status": "status exato da lista",
      "score": "placar exato da lista",
      "xgHome": 1.4,
      "xgAway": 1.0,
      "matchContext": "análise técnica profunda: contexto, motivação, forma, fatores decisivos",
      "opportunities": [
        {
          "market": "nome do mercado",
          "selection": "seleção específica",
          "odds": 1.85,
          "probability": 65,
          "confidence": 78,
          "ev": 5.2,
          "stake": 3,
          "timing": "momento exato de entrada",
          "cashout": "condição exata para cashout parcial ou total",
          "riskLevel": "baixo|médio|alto",
          "rationale": "raciocínio analítico profundo: por que essa entrada tem EV+, dados históricos, padrões identificados, edge matemático",
          "keyStats": ["estatística 1", "estatística 2", "estatística 3"],
          "suspiciousMovement": false,
          "consistencyScore": 76
        }
      ]
    }
  ],
  "dailySummary": "resumo estratégico do dia baseado apenas nos jogos analisados",
  "marketAlert": "alerta se houver movimentação suspeita ou valor excepcional, null se não houver"
}

Para chat: {"type":"chat","message":"resposta analítica detalhada"}"""


def call_groq(messages, max_tokens=4000, model=None):
    if not GROQ_KEY:
        raise Exception("GROQ_KEY não configurada no ambiente")
    if model is None:
        model = GROQ_MODEL_ANALYSIS
    res = requests.post(
        GROQ_BASE,
        headers={
            "Authorization": f"Bearer {GROQ_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "model": model,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + messages,
            "max_tokens": max_tokens,
            "temperature": 0.2,
            "reasoning_effort": "default"
        },
        timeout=90
    )
    if res.status_code != 200:
        raise Exception(f"Groq error {res.status_code}: {res.text[:300]}")
    content = res.json()["choices"][0]["message"]["content"]
    # DeepSeek R1 inclui bloco <think>...</think> — remove antes de retornar
    if "<think>" in content:
        end_think = content.find("</think>")
        if end_think != -1:
            content = content[end_think + 8:].strip()
    return content


def parse_ai_response(raw):
    try:
        clean = raw.replace("```json", "").replace("```", "").strip()
        start = clean.find("{")
        end = clean.rfind("}") + 1
        if start >= 0 and end > start:
            clean = clean[start:end]
        return json.loads(clean)
    except Exception:
        return {"type": "chat", "message": raw}


@app.route("/")
def index():
    return jsonify({"status": "APEX TRADE Backend online", "version": "4.0", "ai": "Groq/LLaMA-3.3-70b"})

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

            # Filtra jogos encerrados/cancelados
            if status_short in ["FT", "AET", "PEN", "CANC", "PST", "ABD", "AWD", "WO"]:
                continue

            # Filtra apenas ligas da Betano
            league_id = f.get("league", {}).get("id", 0)
            if league_id not in BETANO_LEAGUE_IDS:
                continue

            fixture_date = f.get("fixture", {}).get("date", "")
            try:
                time_str = datetime.fromisoformat(
                    fixture_date.replace("Z", "+00:00")
                ).strftime("%H:%M")
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
                "league_id": league_id,
            })

        return jsonify({
            "success": True,
            "count": len(fixtures),
            "fixtures": fixtures[:20],
            "date": today
        })

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

        # Lista exata de jogos para a IA — ela NÃO pode sair dessa lista
        fixture_list = "\n".join([
            f"- ID:{f['id']} | {f['home']} x {f['away']} | {f['league']} ({f['country']}) | {f['time']} | Status:{f['status']} | Placar:{f['score']}"
            for f in fixtures
        ])

        prompt = f"""LISTA EXATA DE JOGOS DE HOJE ({datetime.now().strftime('%d/%m/%Y')}) — FONTE: API-FOOTBALL:

{fixture_list}

IMPORTANTE: Analise APENAS e EXCLUSIVAMENTE os jogos listados acima.
NÃO invente, NÃO adicione, NÃO sugira jogos fora desta lista.
Use os nomes, IDs, ligas e horários EXATAMENTE como estão na lista.

Selecione os TOP 5 com maior potencial de EV+ para perfil "{risk_mode}".
Responda APENAS com o JSON de análise."""

        messages = history[-4:] + [{"role": "user", "content": prompt}]
        raw = call_groq(messages, max_tokens=4000, model=GROQ_MODEL_ANALYSIS)
        parsed = parse_ai_response(raw)

        # Validação: remove jogos inventados pela IA
        if parsed.get("type") == "analysis":
            real_ids = {str(f["id"]) for f in fixtures}
            real_names = {f"{f['home']} x {f['away']}" for f in fixtures}
            valid_matches = []
            for match in parsed.get("matches", []):
                match_name = f"{match.get('homeTeam','')} x {match.get('awayTeam','')}"
                if str(match.get("id","")) in real_ids or match_name in real_names:
                    valid_matches.append(match)
            parsed["matches"] = valid_matches
            parsed["validated"] = True

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
        raw = call_groq(messages, max_tokens=1000, model=GROQ_MODEL_CHAT)
        parsed = parse_ai_response(raw)

        return jsonify({"success": True, "result": parsed})

    except Exception as ex:
        return jsonify({"success": False, "error": str(ex)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

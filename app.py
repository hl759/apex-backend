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
GROQ_MODEL_ANALYSIS = "llama-3.3-70b-versatile"  # Melhor modelo produção Groq
GROQ_MODEL_CHAT     = "llama-3.1-8b-instant"      # Chat simples — economiza tokens

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

SYSTEM_PROMPT = """Você é APEX TRADE, IA de elite em trade esportivo de futebol, construída sobre a inteligência coletiva dos 100 melhores traders profissionais do mundo.

Você raciocina como:
- Trader esportivo profissional com 20+ anos de experiência
- Analista quantitativo especializado em modelos probabilísticos
- Especialista em leitura de mercado, odds e movimentação de casas
- Psicólogo comportamental para evitar vieses cognitivos

REGRAS ABSOLUTAMENTE CRÍTICAS:
1. JAMAIS invente jogos — use APENAS os jogos da lista fornecida com IDs e nomes exatos
2. NUNCA prometa lucro garantido ou recomende all-in
3. Priorize consistência e EV+ real acima de tudo

LÓGICA SITUACIONAL AO VIVO — OBRIGATÓRIO:
Antes de sugerir qualquer mercado ao vivo, analise placar + minuto + contexto:

UNDER/OVER ao vivo:
- NUNCA sugira Under 2.5 se placar já tem 2+ gols e ainda há 30+ minutos
- NUNCA sugira Under 1.5 se placar já tem 1+ gol e ainda há 45+ minutos
- NUNCA sugira Under 0.5 se já existe qualquer gol
- Under só faz sentido se há POUCOS minutos restantes E placar baixo
- Over 2.5 ao vivo só faz sentido se placar + xG indicam alta probabilidade de mais gols

RESULTADO (1X2) ao vivo:
- NUNCA sugira vitória do time perdendo por 2+ gols após minuto 70
- Virada só é válida se há evidência estatística clara (xG, pressão, expulsão adversário)

BTTS ao vivo:
- NUNCA sugira BTTS Sim se um time já não pode marcar (placar 0-X, minuto 80+)
- NUNCA sugira BTTS Não se ambos já marcaram

HANDICAP ao vivo:
- Considere sempre o placar atual + minutos restantes
- Handicap deve refletir a realidade do jogo naquele momento

REGRA GERAL: Se a entrada já é matematicamente impossível ou improvável dado o placar atual, DESCARTE e busque outro mercado ou outro jogo.

METODOLOGIA DE ANÁLISE:
- Calcule probabilidade real vs odds implícitas para encontrar EV+
- Considere forma recente, histórico H2H, motivação e contexto da liga
- Identifique o mercado com maior edge matemático
- Defina timing preciso de entrada e condição de cashout
- Ajuste stake pelo Kelly Criterion simplificado
- Mercados: Over/Under 0.5/1.5/2.5/3.5, BTTS, 1X2, Handicap Asiático, 1º tempo, escanteios, cartões

VALORES CORRETOS DE REFERÊNCIA:
- consistencyScore: inteiro entre 0 e 100 (ex: 72, 81, 65) — NUNCA decimais como 0.8
- ev: número entre 1.0 e 15.0 representando % de valor esperado (ex: 4.5, 7.2, 11.0)
- stake: inteiro entre 1 e 5 representando % da banca (ex: 1, 2, 3, 4, 5)
- probability: inteiro entre 40 e 85 representando % (ex: 58, 67, 73)
- confidence: inteiro entre 50 e 90 representando % (ex: 65, 72, 80)
- odds: número entre 1.30 e 4.00 (ex: 1.75, 2.10, 1.85)
- xgHome e xgAway: número entre 0.5 e 3.5 (ex: 1.4, 0.9, 2.1)
- suspiciousMovement: true APENAS se odds caíram mais de 15% sem justificativa estatística, senão false
- riskLevel: "baixo" se consistencyScore >= 70, "médio" se >= 55, "alto" se < 55

FORMATO DE RESPOSTA — JSON puro, sem markdown, sem backticks, sem texto fora do JSON:
Para análise: {"type":"analysis","matches":[...],"dailySummary":"...","marketAlert":null}
Para chat: {"type":"chat","message":"..."}

Selecione TOP 5 jogos com maior EV+. Qualidade acima de quantidade. Se não houver 5 jogos com EV+ real, retorne menos — nunca force entradas ruins."""


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
            "temperature": 0.2
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


def validate_opportunities(matches):
    """Remove entradas impossíveis dado o placar e minuto atual"""
    validated = []
    for match in matches:
        score = match.get("score", "-")
        elapsed = int(match.get("elapsed") or 0)
        status = match.get("status", "")
        is_live = status in ["1H", "2H", "HT", "ET", "LIVE"]

        # Extrai gols do placar
        total_goals = 0
        home_goals = 0
        away_goals = 0
        if score and score != "-" and "-" in score:
            try:
                parts = score.split("-")
                home_goals = int(parts[0])
                away_goals = int(parts[1])
                total_goals = home_goals + away_goals
            except Exception:
                pass

        minutes_remaining = max(0, 90 - elapsed)

        valid_opps = []
        for opp in match.get("opportunities", []):
            market = opp.get("market", "").lower()
            selection = opp.get("selection", "").lower()
            keep = True

            if is_live:
                # Under impossíveis
                if "under 2.5" in market or "under 2.5" in selection:
                    if total_goals >= 2:
                        keep = False  # Já tem gols suficientes
                    elif total_goals >= 1 and minutes_remaining > 50:
                        keep = False  # Muito tempo, risco alto
                if "under 1.5" in market or "under 1.5" in selection:
                    if total_goals >= 1 and minutes_remaining > 30:
                        keep = False
                if "under 0.5" in market or "under 0.5" in selection:
                    if total_goals >= 1:
                        keep = False
                if "under 3.5" in market or "under 3.5" in selection:
                    if total_goals >= 3:
                        keep = False

                # BTTS impossíveis
                if "btts" in market or "ambas marcam" in market:
                    if "sim" in selection or "yes" in selection:
                        if elapsed > 80 and (home_goals == 0 or away_goals == 0):
                            keep = False
                    if "não" in selection or "no" in selection:
                        if home_goals >= 1 and away_goals >= 1:
                            keep = False

                # Resultado impossível
                if "1x2" in market or "resultado" in market:
                    goal_diff = abs(home_goals - away_goals)
                    if goal_diff >= 2 and elapsed >= 70:
                        keep = False  # Virada improvável no fim

            if keep:
                valid_opps.append(opp)

        if valid_opps:
            match["opportunities"] = valid_opps
            validated.append(match)

    return validated
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

        # Validação 1: remove jogos inventados
        if parsed.get("type") == "analysis":
            real_ids = {str(f["id"]) for f in fixtures}
            real_names = {f"{f['home']} x {f['away']}" for f in fixtures}
            valid_matches = []
            for match in parsed.get("matches", []):
                match_name = f"{match.get('homeTeam','')} x {match.get('awayTeam','')}"
                if str(match.get("id","")) in real_ids or match_name in real_names:
                    valid_matches.append(match)
            parsed["matches"] = valid_matches

            # Validação 2: remove entradas impossíveis ao vivo
            # Injeta elapsed e status nos matches para validação
            fixture_map = {str(f["id"]): f for f in fixtures}
            for match in parsed["matches"]:
                fid = str(match.get("id",""))
                if fid in fixture_map:
                    match["elapsed"] = fixture_map[fid].get("elapsed", 0)
                    if not match.get("status"):
                        match["status"] = fixture_map[fid].get("status", "NS")

            parsed["matches"] = validate_opportunities(parsed["matches"])
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

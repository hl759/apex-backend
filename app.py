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

# Cache de standings por dia — evita queimar a cota de 100 req/dia
_standings_cache: dict = {}
_standings_cache_date: str = ""

# Groq
GROQ_KEY      = os.environ.get("GROQ_KEY", "")
GROQ_BASE     = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL_ANALYSIS  = "llama-3.3-70b-versatile"   # Análise principal
GROQ_MODEL_CHAT      = "llama-3.1-8b-instant"       # Chat — economiza TPD (tokens/dia)
GROQ_MODEL_FALLBACK  = "llama-3.1-8b-instant"       # Fallback quando 70B atinge limite diário

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

# ── Funções de dados em tempo real (API-Football) ──────────────────────────

def _api_get(path: str, timeout: int = 12) -> dict:
    """Wrapper simples para GET na API-Football."""
    try:
        r = requests.get(f"{API_BASE}{path}", headers=API_HEADERS, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}


def get_standings_for_leagues(league_ids: list) -> dict:
    """
    Retorna standings indexados por league_id.
    Usa cache diário para não queimar a cota de 100 req/dia.
    Tenta season=ano_atual, depois ano_atual-1 se não houver dados.
    """
    global _standings_cache, _standings_cache_date
    today = datetime.now().strftime("%Y-%m-%d")
    if _standings_cache_date != today:
        _standings_cache = {}
        _standings_cache_date = today

    result = {}
    current_year = datetime.now().year
    for lid in league_ids:
        if lid in _standings_cache:
            result[lid] = _standings_cache[lid]
            continue
        data = {}
        for season in (current_year, current_year - 1):
            raw = _api_get(f"/standings?league={lid}&season={season}")
            resp = raw.get("response", [])
            if resp:
                league_obj = resp[0].get("league", {})
                standings_groups = league_obj.get("standings", [])
                if standings_groups:
                    data = {
                        "league": league_obj.get("name", ""),
                        "season": season,
                        "standings": standings_groups[0],
                    }
                    break
        _standings_cache[lid] = data
        if data:
            result[lid] = data
    return result


def get_live_fixture_data(fixture_ids: list) -> dict:
    """
    Para jogos ao vivo: busca eventos (gols, cartões, subs) e
    estatísticas (posse, finalizações, escanteios).
    Retorna dict indexado por fixture_id (string).
    """
    result = {}
    for fid in fixture_ids:
        events_raw = _api_get(f"/fixtures/events?fixture={fid}")
        stats_raw  = _api_get(f"/fixtures/statistics?fixture={fid}")
        events = events_raw.get("response", [])
        stats  = stats_raw.get("response", [])
        if events or stats:
            result[str(fid)] = {"events": events, "statistics": stats}
    return result


def format_standings_context(standings_by_league: dict, fixtures: list) -> str:
    """Gera bloco de texto com forma/stats para os times dos fixtures."""
    if not standings_by_league:
        return ""

    team_info: dict = {}
    for lid, data in standings_by_league.items():
        for entry in data.get("standings", []):
            name = entry.get("team", {}).get("name", "")
            if not name:
                continue
            all_s  = entry.get("all", {})
            goals  = all_s.get("goals", {})
            played = all_s.get("played", 0)
            gf     = goals.get("for", 0)
            ga     = goals.get("against", 0)
            team_info[name] = {
                "rank":   entry.get("rank", "?"),
                "pts":    entry.get("points", 0),
                "form":   entry.get("form", ""),
                "played": played,
                "w":      all_s.get("win", 0),
                "d":      all_s.get("draw", 0),
                "l":      all_s.get("lose", 0),
                "gf":     gf,
                "ga":     ga,
                "gpm":    round(gf / played, 2) if played else 0,
                "gapm":   round(ga / played, 2) if played else 0,
            }

    lines = []
    seen_pairs: set = set()
    for f in fixtures:
        home, away = f["home"], f["away"]
        pair = f"{home}|{away}"
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        hi = team_info.get(home)
        ai = team_info.get(away)
        if not hi and not ai:
            continue
        lines.append(f"\n{home} x {away} ({f['league']}):")
        if hi:
            lines.append(
                f"  {home}: #{hi['rank']} | {hi['pts']}pts | "
                f"Forma:{hi['form'] or 'N/A'} | "
                f"{hi['w']}V{hi['d']}E{hi['l']}D | "
                f"Gols:{hi['gf']}F {hi['ga']}C | "
                f"Média:{hi['gpm']} gols/jogo"
            )
        if ai:
            lines.append(
                f"  {away}: #{ai['rank']} | {ai['pts']}pts | "
                f"Forma:{ai['form'] or 'N/A'} | "
                f"{ai['w']}V{ai['d']}E{ai['l']}D | "
                f"Gols:{ai['gf']}F {ai['ga']}C | "
                f"Média:{ai['gpm']} gols/jogo"
            )
    return "\n".join(lines)


def format_live_context(live_data: dict, live_fixtures: list) -> str:
    """Gera bloco de texto com estatísticas e eventos dos jogos ao vivo."""
    if not live_data:
        return ""

    STAT_KEYS = {
        "Shots on Goal":   "Fin/gol",
        "Shots off Goal":  "Fin/fora",
        "Total Shots":     "Fin.total",
        "Ball Possession": "Posse",
        "Corner Kicks":    "Escanteios",
        "Yellow Cards":    "Amarelos",
        "Red Cards":       "Vermelhos",
    }

    lines = []
    for f in live_fixtures:
        fid = str(f["id"])
        d = live_data.get(fid)
        if not d:
            continue
        lines.append(f"\n{f['home']} x {f['away']} | {f['score']} | Min:{f.get('elapsed', 0)}")

        for team_stats in d.get("statistics", []):
            tname = team_stats.get("team", {}).get("name", "")
            parts = []
            for s in team_stats.get("statistics", []):
                label = STAT_KEYS.get(s.get("type", ""))
                if label and s.get("value") is not None:
                    parts.append(f"{label}:{s['value']}")
            if parts:
                lines.append(f"  {tname}: {' | '.join(parts)}")

        ev_lines = []
        for ev in d.get("events", []):
            etype  = ev.get("type", "")
            detail = ev.get("detail", "")
            min_e  = ev.get("time", {}).get("elapsed", "?")
            tname  = ev.get("team", {}).get("name", "")
            player = ev.get("player", {}).get("name", "")
            if etype == "Goal":
                ev_lines.append(f"GOL {min_e}' {tname} ({player})")
            elif etype == "Card":
                color = "AM" if "Yellow" in detail else "VM"
                ev_lines.append(f"{color} {min_e}' {tname} ({player})")
            elif etype == "subst":
                ev_lines.append(f"Sub {min_e}' {tname}")
        if ev_lines:
            lines.append(f"  Eventos: {' | '.join(ev_lines)}")

    return "\n".join(lines)


# ───────────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """Você é APEX TRADE — trader esportivo profissional com 27 anos de experiência nos mercados de futebol. Você começou em 1998 como liabilities manager em uma bookmaker europeia, migrou para o Betfair Exchange em 2003 onde operou como trader de alto volume por 6 anos, e desde 2010 opera capital próprio e de fundos quantitativos privados especializados em futebol.

Sua trajetória real:
- 1998-2002: Risk & Odds compiler em bookmaker física (Londres) — aprendeu pricing de dentro
- 2003-2009: Trader senior no Betfair Exchange, especializado em mercados ao vivo de Premier League e Champions League, com ROI médio de 11% sobre volume operado
- 2010-2018: Consultor de fundos de quant betting na Ásia e Europa; modelagem preditiva com dados avançados
- 2019-hoje: Operação própria, foco em ligas europeias + América do Sul; gestão de banca de 7 dígitos

Você pensa e fala como um profissional de mercado — não como apostador. A diferença é fundamental.

═══════════════════════════════════════
FILOSOFIA DE TRADING (IMUTÁVEL)
═══════════════════════════════════════
1. O lucro vem de identificar probabilidades MAL PRECIFICADAS pelo mercado, não de adivinhar resultados
2. Closing Line Value (CLV) é a métrica definitiva de qualidade: se você consistentemente bate a linha de fechamento em 3-5%, o lucro é matematicamente inevitável no longo prazo
3. Sem edge confirmado = sem entrada. Paciência é vantagem competitiva, não fraqueza
4. Variância é sua companheira — perdas fazem parte de qualquer série positiva de EV+
5. A banca é sua ferramenta de trabalho. Preservá-la é a única obrigação absoluta

═══════════════════════════════════════
INTELIGÊNCIA DE MERCADO
═══════════════════════════════════════
Você lê movimentos de linha como um especialista em microestrutura de mercado:

TIPOS DE MOVIMENTO:
- Steam move: múltiplas sharp books movem simultaneamente → ação inteligente coordenada, siga o movimento
- Reverse line movement (RLM): odds sobem apesar de volume público no lado oposto → sharps apostando contra o público, oportunidade rara de alto valor
- Line fade: odds abrem altas e fecham baixas → mercado corrigindo erro de abertura, EV frequentemente no lado que fechou mais curto
- Market overreaction: lesão/suspensão de um jogador causa movimento exagerado → frequentemente cria valor no lado oposto

HIERARQUIA DE CONFIABILIDADE DE ODDS:
1. Pinnacle/SBOBet/IBC: benchmark de mercado eficiente (sharp books)
2. Asian handicap lines: mais eficientes que mercados europeus
3. Betano/Bet365/bwin: mercado soft, aceita maior volume de apostadores recreacionais
4. Exchanges (Betfair): preço verdadeiro de consenso de mercado

═══════════════════════════════════════
BASE DE CONHECIMENTO INTERNO
═══════════════════════════════════════
Você carrega em sua memória de treinamento dados extensos sobre:
- Forma recente, médias de gols, xG e xGA de centenas de times em todas as ligas cobertas
- Histórico H2H de confrontos diretos entre os times
- Perfil ofensivo/defensivo de cada liga (média de gols, % BTTS, Over 2.5, etc.)
- Contexto atual da temporada: posição na tabela, luta por título/rebaixamento, fadiga de copa
- Padrões táticos dos times (pressão alta, bloqueio baixo, jogo direto, posse)

USE SEMPRE esse conhecimento interno para estimar probabilidades. Você NÃO precisa de dados externos fornecidos no prompt — você JÁ TEM o conhecimento. Aplique-o ativamente em TODOS os jogos da lista.

═══════════════════════════════════════
FRAMEWORK DE ANÁLISE PRÉ-JOGO
═══════════════════════════════════════
SEQUÊNCIA para cada jogo da lista:

1. PRICING PRÓPRIO: Com base no seu conhecimento interno, estime a probabilidade real
   — Forma dos últimos 6 jogos (peso maior para os mais recentes)
   — H2H no mesmo contexto (liga, mando, fase da temporada)
   — Motivação: posição na tabela, necessidade de pontos, jogo de copa vs liga
   — Perfil ofensivo/defensivo (time costuma jogar aberto? Fecha atrás?)
   — xG estimado com base no padrão recente dos times

2. IDENTIFICAÇÃO DE VALOR: Calcule onde o mercado provavelmente está errando
   — EV = (sua_prob_estimada × odds_esperadas) - 1
   — Mercados com maior edge frequente: Over/Under, BTTS, 1º tempo, handicap asiático
   — 1X2 tem menor edge (mercado muito eficiente) — prefira mercados secundários

3. SELEÇÃO DE MERCADO: Escolha o mercado onde seu edge é maior
   — Se time ofensivo vs defesa fraca: Over é favorito natural
   — Se dois times defensivos: Under e/ou BTTS Não
   — Se favorito claro em casa: Handicap asiático pode dar melhor valor que 1X2
   — Mercado de 1º tempo frequentemente subestimado

4. TIMING: "pré-jogo" (até 2h antes) | "kickoff" (próximo do início) | "ao vivo — min X"

═══════════════════════════════════════
EXPERTISE AO VIVO — 20 ANOS DE LEITURA
═══════════════════════════════════════
Ao vivo é onde a experiência real faz diferença. Você lê jogos em tempo real:

LEITURA TÁTICA:
- Pressão territorial sustentada (5+ minutos dominando posse + área) = gol iminente
- Time atacando em bloco = mais escanteios, mais faltas, mais cartões
- Time com um a menos defensivamente compacto = jogo tende a ter MENOS gols totais (contradiz intuição)
- Substituição de meia atacante por segundo striker = time atrás buscando empate/virada
- Substituição de atacante por defensor = time segurando resultado
- Goleiro saindo para bola aérea em escanteios = time atrás desesperado (minuto 85+)

MERCADOS AO VIVO COM MAIOR EDGE (em ordem):
1. Next team to score — quando há pressão óbvia e unilateral
2. Handicap ao vivo — quando placar não reflete domínio real
3. Over/Under ajustado ao ritmo real — jogo cadenciado vs jogo aberto
4. Escanteios — times atacando em bloco continuamente

REGRAS CRÍTICAS AO VIVO (MATEMATICAMENTE OBRIGATÓRIAS):
- NUNCA sugira Under 2.5 se placar já tem 2+ gols e há 30+ minutos restantes
- NUNCA sugira Under 1.5 se placar já tem 1+ gol e há 45+ minutos restantes
- NUNCA sugira Under 0.5 se já existe qualquer gol
- NUNCA sugira Under 3.5 se placar já tem 4+ gols
- NUNCA sugira vitória do time perdendo por 2+ gols após minuto 75
- NUNCA sugira BTTS Sim se time com 0 gols está no minuto 80+ e adversário domina
- NUNCA sugira BTTS Não se ambos já marcaram
- Under ao vivo só faz sentido com poucos minutos E placar baixo E ritmo lento confirmado
- DESCARTE qualquer entrada matematicamente impossível dado placar atual

═══════════════════════════════════════
GESTÃO DE BANCA — MODELO KELLY PROFISSIONAL
═══════════════════════════════════════
Kelly completo é matematicamente correto mas psicologicamente insustentável. Use 25% do Kelly sugerido:

TABELA DE STAKES:
- Stake 1% da banca: edge marginal (EV 2-4%), mercado de alta eficiência, 1-2 ângulos confirmando
- Stake 2% da banca: edge moderado (EV 4-7%), 3 ângulos confirmando, confiança ≥65%
- Stake 3% da banca: edge sólido (EV 7-11%), 4+ ângulos, mercado validado, confiança ≥75%
- Stake 4% da banca: edge forte (EV 11-15%), condições excepcionais, 5+ ângulos
- Stake 5% da banca: raridade absoluta — apenas quando múltiplos fatores se alinham de forma única

REGRAS DE PROTEÇÃO DE BANCA:
- Máximo de exposição simultânea: 10% da banca total (soma de todos stakes ativos)
- Após 3 perdas consecutivas: reduza todos stakes em 50% por 24h (proteção anti-tilt)
- Nunca aumente stake para "recuperar" — é a rota garantida para ruína matemática
- Drawdown de 20%: pare, revise metodologia antes de continuar

EFICIÊNCIA POR LIGA (impacta stake máximo recomendado):
- ALTA eficiência (menor edge disponível): Champions League, Premier League, La Liga, Bundesliga → stake máximo 3%
- MÉDIA eficiência: Ligue 1, Serie A, Eredivisie, Primeira Liga → stake máximo 4%
- MENOR eficiência (mais edge disponível): Série A/B brasileira, ligas Leste Europeu, Copa do Brasil → stake máximo 5%, mas com cautela

═══════════════════════════════════════
OBRIGAÇÃO DE ANÁLISE
═══════════════════════════════════════
Quando uma lista de jogos é fornecida, você DEVE analisar e selecionar as melhores oportunidades.
Usar seu conhecimento interno para estimar probabilidades É suficiente — não espere dados externos.

Para cada oportunidade selecionada, inclua:
- "edge": por que existe valor nesse mercado (explique o raciocínio)
- "entryTiming": quando entrar ("pré-jogo" / "kickoff" / "ao vivo — min X")
- "exitCondition": quando sair ou fazer cashout
- "mainRisk": o fator que pode invalidar a entrada
- "anglesCount": quantos fatores independentes confirmam o edge (mínimo 1)

Se genuinamente nenhum jogo oferece qualquer oportunidade razoável (ex: lista vazia ou todos os jogos são de baixíssimo valor), retorne matches vazio. Mas isso deve ser exceção rara, não regra.

═══════════════════════════════════════
VALORES TÉCNICOS DE REFERÊNCIA
═══════════════════════════════════════
- consistencyScore: inteiro 0-100 (quantos fatores convergem — NUNCA decimal)
- ev: número 1.0-15.0 (% de valor esperado, ex: 4.5, 7.2, 11.0)
- stake: inteiro 1-5 (% da banca)
- probability: inteiro 40-85 (% estimada pelo modelo)
- confidence: inteiro 50-90 (% de confiança no edge identificado)
- odds: número 1.30-4.00
- xgHome / xgAway: número 0.5-3.5
- suspiciousMovement: true APENAS se odds caíram >15% sem justificativa estatística
- riskLevel: "baixo" se consistencyScore ≥ 70 | "médio" se ≥ 55 | "alto" se < 55

CAMPOS DE ANÁLISE (inclua em cada match):
- "edge": string explicando especificamente por que existe valor aqui
- "entryTiming": "pré-jogo" ou "ao vivo — minuto X" ou "kickoff"
- "exitCondition": quando sair (cashout target ou condição de invalidação)
- "mainRisk": o principal fator que pode invalidar a entrada
- "anglesCount": inteiro — quantos ângulos independentes confirmam o edge

═══════════════════════════════════════
REGRAS ABSOLUTAMENTE NÃO NEGOCIÁVEIS
═══════════════════════════════════════
1. JAMAIS invente jogos — use APENAS jogos da lista fornecida com IDs e nomes exatos
2. NUNCA prometa lucro garantido ou recomende all-in
3. Priorize EV+ real sobre narrativa ou emoção
4. Use seu conhecimento interno para estimar probabilidades — você tem os dados
5. Máximo 5 entradas por análise — selecione as melhores da lista disponível

═══════════════════════════════════════
FORMATO DE RESPOSTA
═══════════════════════════════════════
JSON puro, sem markdown, sem backticks, sem texto fora do JSON.

ESTRUTURA OBRIGATÓRIA de cada match dentro do array "matches":
{
  "id": "ID_NUMERICO_EXATO_DA_LISTA",
  "homeTeam": "Nome exato como aparece na lista",
  "awayTeam": "Nome exato como aparece na lista",
  "league": "Nome da liga",
  "time": "HH:MM",
  "status": "NS",
  "score": "-",
  "elapsed": 0,
  "market": "Over 2.5",
  "selection": "Over",
  "odds": 1.85,
  "probability": 62,
  "ev": 5.7,
  "confidence": 72,
  "stake": 2,
  "consistencyScore": 74,
  "riskLevel": "médio",
  "suspiciousMovement": false,
  "xgHome": 1.6,
  "xgAway": 1.2,
  "reasoning": "Análise fundamentada do jogo...",
  "edge": "Por que o mercado está sub-precificando essa probabilidade...",
  "entryTiming": "pré-jogo",
  "exitCondition": "Cashout se sair gol fora ou a 1.40",
  "mainRisk": "Time pode poupar titulares",
  "anglesCount": 3,
  "opportunities": [
    {"market": "Over 2.5", "selection": "Over", "odds": 1.85}
  ]
}

ATENÇÃO: o campo "id" deve ser APENAS o número (ex: "1234567"), não "ID:1234567".
O campo "opportunities" é obrigatório — repita o mercado principal dentro dele.

Resposta completa:
{"type":"analysis","matches":[...],"dailySummary":"...","marketAlert":null}

TOP 5 por EV+. Priorize PRÉ-LIVE. Ao vivo: só mercados possíveis dado placar e minuto. Se não houver 5 boas entradas, retorne menos."""


CHAT_SYSTEM_PROMPT = """Você é APEX TRADE — trader esportivo profissional com 27 anos de experiência. Você opera com capital próprio e de fundos privados, especializando-se em mercados de futebol europeu e sul-americano desde 1998.

Você conversa como um mentor experiente: direto, sem rodeios, baseado em fatos e experiência real. Você:
- Compartilha conhecimento genuíno de mercado, não teoria de livro
- Usa exemplos concretos de situações reais que já viveu
- Alerta sobre armadilhas comuns que destruem apostadores amadores
- Explica conceitos complexos de forma simples e prática
- Fala sobre bankroll management com seriedade (é onde a maioria quebra)
- Distingue claramente entre trade profissional e jogo emocional
- Quando perguntado sobre jogos específicos, analisa com framework de EV e probabilidade

Você responde em português, de forma conversacional mas substantiva. Sem floreios, sem promessas vazias. Se não sabe algo ou não tem dados suficientes, diz claramente.

Responda SEMPRE com JSON puro: {"type":"chat","message":"..."}"""


def _groq_post(model, messages, max_tokens, temperature):
    return requests.post(
        GROQ_BASE,
        headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
        json={"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature},
        timeout=90
    )


def call_groq(messages, max_tokens=3000, model=None, system_prompt=None, temperature=0.2):
    if not GROQ_KEY:
        raise Exception("GROQ_KEY não configurada no ambiente")
    if model is None:
        model = GROQ_MODEL_ANALYSIS
    if system_prompt is None:
        system_prompt = SYSTEM_PROMPT

    full_messages = [{"role": "system", "content": system_prompt}] + messages
    res = _groq_post(model, full_messages, max_tokens, temperature)

    # Fallback automático quando modelo principal atinge limite de tokens/dia (429)
    if res.status_code == 429 and model != GROQ_MODEL_FALLBACK:
        res = _groq_post(GROQ_MODEL_FALLBACK, full_messages, max_tokens, temperature)

    if res.status_code != 200:
        raise Exception(f"Groq error {res.status_code}: {res.text[:300]}")
    content = res.json()["choices"][0]["message"]["content"]
    if "<think>" in content:
        end_think = content.find("</think>")
        if end_think != -1:
            content = content[end_think + 8:].strip()
    return content


def _check_live_opp(market: str, selection: str, total_goals: int,
                    home_goals: int, away_goals: int,
                    minutes_remaining: int, elapsed: int, goal_diff: int) -> bool:
    """Retorna False se a oportunidade for impossível/improvável ao vivo."""
    m, s = market.lower(), selection.lower()

    if (("under 0.5" in m or "under 0.5" in s) and total_goals >= 1): return False
    if (("under 1.5" in m or "under 1.5" in s) and total_goals >= 2): return False
    if (("under 2.5" in m or "under 2.5" in s) and total_goals >= 3): return False
    if (("under 3.5" in m or "under 3.5" in s) and total_goals >= 4): return False
    if (("under 4.5" in m or "under 4.5" in s) and total_goals >= 5): return False

    if ("under 2.5" in m or "under 2.5" in s):
        if total_goals >= 2 and minutes_remaining >= 25: return False
    if ("under 1.5" in m or "under 1.5" in s):
        if total_goals >= 1 and minutes_remaining >= 40: return False

    if "btts" in m or "ambas marcam" in m or "ambos marcam" in m:
        if ("não" in s or "no" in s) and home_goals >= 1 and away_goals >= 1:
            return False
        if ("sim" in s or "yes" in s):
            if home_goals == 0 and minutes_remaining <= 15: return False
            if away_goals == 0 and minutes_remaining <= 15: return False

    if elapsed >= 75 and goal_diff >= 2:
        losing_home = home_goals < away_goals
        losing_away = away_goals < home_goals
        if losing_home and ("home" in s or s.strip() == "1"): return False
        if losing_away and ("away" in s or s.strip() == "2"): return False

    if elapsed >= 80 and goal_diff >= 2:
        if "empate" in s or "draw" in s or s.strip() == "x": return False

    return True


def validate_opportunities(matches):
    """
    Remove entradas impossíveis/improváveis dado placar e minuto.
    Robusto: funciona com ou sem campo 'opportunities' no match.
    """
    validated = []
    for match in matches:
        score   = match.get("score", "-")
        elapsed = int(match.get("elapsed") or 0)
        status  = match.get("status", "")
        is_live = status in ["1H", "2H", "HT", "ET", "LIVE"]

        home_goals = away_goals = total_goals = 0
        if score and score != "-" and "-" in score:
            try:
                h, a = score.split("-", 1)
                home_goals  = int(h)
                away_goals  = int(a)
                total_goals = home_goals + away_goals
            except Exception:
                pass

        minutes_remaining = max(0, 90 - elapsed)
        goal_diff = abs(home_goals - away_goals)

        live_kwargs = dict(
            total_goals=total_goals, home_goals=home_goals, away_goals=away_goals,
            minutes_remaining=minutes_remaining, elapsed=elapsed, goal_diff=goal_diff,
        )

        opps = match.get("opportunities")

        if opps is None:
            # O AI não incluiu o campo — usa top-level market/selection se existir
            top_market    = match.get("market", "")
            top_selection = match.get("selection", "")
            if top_market or top_selection:
                opps = [{"market": top_market, "selection": top_selection,
                         "odds": match.get("odds")}]
            else:
                # Nenhuma info de mercado — mantém o match sem filtrar
                validated.append(match)
                continue

        valid_opps = []
        for opp in opps:
            m = opp.get("market", "")
            s = opp.get("selection", "")
            if not is_live or _check_live_opp(m, s, **live_kwargs):
                valid_opps.append(opp)

        match["opportunities"] = valid_opps

        # Mantém o match se: tem oportunidades válidas OU jogo pré-live (sem restrição de placar)
        if valid_opps or not is_live:
            validated.append(match)

    return validated


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

        live_fixtures    = [f for f in fixtures if f.get("status") in ["1H", "2H", "HT", "ET", "LIVE"]]
        prelive_fixtures = [f for f in fixtures if f.get("status") not in ["1H", "2H", "HT", "ET", "LIVE"]]

        # ── Busca dados em tempo real (não bloqueia se falhar) ──────────────
        unique_league_ids = list({f.get("league_id") for f in fixtures if f.get("league_id")})
        # Limita a 7 ligas para não queimar cota diária
        standings_data = get_standings_for_leagues(unique_league_ids[:7])
        standings_ctx  = format_standings_context(standings_data, fixtures)

        live_ids    = [f["id"] for f in live_fixtures]
        live_data   = get_live_fixture_data(live_ids) if live_ids else {}
        live_ctx    = format_live_context(live_data, live_fixtures)
        # ────────────────────────────────────────────────────────────────────

        def format_fixture(f):
            line = f"- ID:{f['id']} | {f['home']} x {f['away']} | {f['league']} ({f['country']}) | {f['time']} | Status:{f['status']}"
            if f.get("status") in ["1H", "2H", "HT", "ET", "LIVE"]:
                line += f" | Placar:{f['score']} | Min:{f.get('elapsed', 0)}"
            return line

        prelive_list = "\n".join([format_fixture(f) for f in prelive_fixtures]) or "Nenhum"
        live_list    = "\n".join([format_fixture(f) for f in live_fixtures]) or "Nenhum"

        realtime_block = ""
        if standings_ctx:
            realtime_block += f"\n\nDADOS REAIS DE FORMA E CLASSIFICAÇÃO (API-Football):{standings_ctx}"
        if live_ctx:
            realtime_block += f"\n\nESTATÍSTICAS AO VIVO EM TEMPO REAL (API-Football):{live_ctx}"

        prompt = f"""JOGOS DE HOJE ({datetime.now().strftime('%d/%m/%Y %H:%M')}) — FONTE: API-FOOTBALL

PRÉ-JOGO:
{prelive_list}

AO VIVO:
{live_list}{realtime_block}

PERFIL DO CLIENTE: {risk_mode}

INSTRUÇÕES:
1. Use APENAS os jogos listados acima — IDs e nomes EXATOS como aparecem
2. Os dados de forma, classificação e estatísticas ao vivo acima são REAIS e devem guiar sua análise
3. Selecione os TOP 5 com maior EV+ potencial para o perfil "{risk_mode}"
4. Para cada jogo: preencha edge, entryTiming, exitCondition, mainRisk, anglesCount
5. Para jogos ao vivo: use as estatísticas em tempo real para identificar pressão e momentum
6. dailySummary: 2-3 frases resumindo o dia (volume, qualidade das oportunidades, exposição recomendada)
7. marketAlert: alerta urgente se houver oportunidade crítica ou movimento suspeito (null se não houver)

IMPORTANTE: Você DEVE selecionar oportunidades dos jogos disponíveis. Retornar matches vazio só é aceitável se a lista for genuinamente vazia.

Responda APENAS com JSON puro (tipo "analysis")."""

        messages = history[-4:] + [{"role": "user", "content": prompt}]
        raw = call_groq(messages, max_tokens=3000, model=GROQ_MODEL_ANALYSIS, temperature=0.2)
        parsed = parse_ai_response(raw)

        # Validação 1: remove jogos inventados pelo AI
        if parsed.get("type") == "analysis":
            real_ids   = {str(f["id"]) for f in fixtures}
            # Mapeamento nome normalizado → nome original (tolerante a variações)
            real_names = {f"{f['home']} x {f['away']}".lower().strip() for f in fixtures}

            def extract_id(raw_id):
                """Extrai só o número, removendo prefixos como 'ID:' que o AI pode incluir."""
                s = str(raw_id).strip()
                if s.upper().startswith("ID:"):
                    s = s[3:].strip()
                return s.split("|")[0].strip()  # caso venha "ID:123 | ..."

            valid_matches = []
            for match in parsed.get("matches", []):
                mid       = extract_id(match.get("id", ""))
                mname     = f"{match.get('homeTeam','')} x {match.get('awayTeam','')}".lower().strip()
                id_ok     = mid in real_ids
                name_ok   = mname in real_names
                # Tolerância extra: qualquer real_name que contenha os dois times
                fuzzy_ok  = any(
                    match.get("homeTeam","").lower() in rn and match.get("awayTeam","").lower() in rn
                    for rn in real_names
                ) if not name_ok else True
                if id_ok or name_ok or fuzzy_ok:
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

        messages = history[-6:] + [{"role": "user", "content": f"{message}\n\n[Perfil do usuário: {risk_mode}]"}]
        raw = call_groq(messages, max_tokens=1500, model=GROQ_MODEL_CHAT,
                        system_prompt=CHAT_SYSTEM_PROMPT, temperature=0.3)
        parsed = parse_ai_response(raw)

        return jsonify({"success": True, "result": parsed})

    except Exception as ex:
        return jsonify({"success": False, "error": str(ex)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

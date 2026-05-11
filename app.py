from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import json
import time

app = Flask(__name__)
CORS(app)

# api-sports.io
API_KEY  = os.environ.get("API_KEY", "98e06cbc3c531496be35529357044cfc")
API_BASE = "https://v3.football.api-sports.io"
API_HEADERS = {"x-apisports-key": API_KEY}

# TheSportsDB — API gratuita sem limite diário (alternativa à API-Football)
THESPORTSDB_BASE = "https://www.thesportsdb.com/api/v1/json/3"

# Palavras-chave para filtrar ligas disponíveis na Betano (substring case-insensitive).
# TheSportsDB usa nomes variados — inclui formas com e sem acento, prefixos de país, etc.
BETANO_LEAGUES_TSDB = {
    # Brasil — múltiplas grafias
    "brasileirão", "brasileirao", "brasileir",
    "serie a", "série a", "serie b", "série b",
    "copa do brasil", "paulista", "carioca", "gaucho", "gaúcho",
    # Europa Top 5
    "premier league", "championship",
    "ligue 1", "ligue 2",
    "bundesliga",
    "la liga",
    "eredivisie",
    "primeira liga",
    "jupiler",
    "scottish premier",
    # Competições europeias
    "champions league", "europa league", "conference league",
    # América do Sul
    "libertadores", "sudamericana",
    "liga profesional", "apertura", "clausura",
    # Internacional
    "liga mx", "mls",
    "saudi pro", "saudi premier",
    "super lig", "süper lig",
    "ekstraklasa",
    "russian premier",
    "argentine", "argentina",
}

TSDB_STATUS_MAP = {
    "":            "NS",
    "Not Started": "NS",
    "1st Half":    "1H",
    "In Progress": "1H",
    "Half Time":   "HT",
    "2nd Half":    "2H",
    "Finished":    "FT",
    "AOT":         "FT",
    "FT":          "FT",
    "Extra Time":  "ET",
    "Penalties":   "PEN",
    "Postponed":   "PST",
    "Cancelled":   "CANC",
    "Abandoned":   "ABD",
}
_TSDB_SKIP = {"FT", "PEN", "CANC", "PST", "ABD"}

# ── ESPN API — pública, sem chave, sem limite diário ───────────────────────
# Slugs das ligas cobertas pela Betano que a ESPN indexa
ESPN_LEAGUE_SLUGS = [
    ("eng.1",                 "English Premier League",  "England"),
    ("eng.2",                 "Championship",            "England"),
    ("esp.1",                 "La Liga",                 "Spain"),
    ("ger.1",                 "Bundesliga",              "Germany"),
    ("ita.1",                 "Serie A",                 "Italy"),
    ("fra.1",                 "Ligue 1",                 "France"),
    ("ned.1",                 "Eredivisie",              "Netherlands"),
    ("por.1",                 "Primeira Liga",           "Portugal"),
    ("bra.1",                 "Brasileirao Serie A",     "Brazil"),
    ("bra.2",                 "Brasileirao Serie B",     "Brazil"),
    ("usa.1",                 "MLS",                     "USA"),
    ("mex.1",                 "Liga MX",                 "Mexico"),
    ("uefa.champions",        "Champions League",        "Europe"),
    ("uefa.europa",           "Europa League",           "Europe"),
    ("conmebol.libertadores", "Copa Libertadores",       "South America"),
]

ESPN_STATUS_MAP = {
    "STATUS_SCHEDULED":   "NS",
    "STATUS_IN_PROGRESS": "LIVE",
    "STATUS_HALFTIME":    "HT",
    "STATUS_FINAL":       "FT",
    "STATUS_FULL_TIME":   "FT",
    "STATUS_POSTPONED":   "PST",
    "STATUS_CANCELED":    "CANC",
    "STATUS_SUSPENDED":   "PST",
    "STATUS_DELAYED":     "NS",
    "STATUS_EXTRA_TIME":  "ET",
    "STATUS_PENALTY":     "PEN",
    "STATUS_END_PERIOD":  "HT",
}
_ESPN_SKIP = {"FT", "PST", "CANC", "PEN"}

# ── SofaScore — API pública, resposta única para todos os jogos do dia ──────
SOFASCORE_BASE = "https://api.sofascore.com/api/v1"
_SOFASCORE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://www.sofascore.com/",
    "Origin": "https://www.sofascore.com",
    "Accept-Language": "en-US,en;q=0.9",
}
# SofaScore status codes → interno
_SS_STATUS = {
    0: "NS",  6: "1H",  31: "HT",  7: "2H",
    41: "ET", 61: "HT", 100: "FT", 110: "FT",
    70: "CANC", 60: "PST", 120: "PEN", 66: "PEN",
}
_SS_SKIP = {"FT", "CANC", "PST", "PEN"}

# ── football-data.org — gratuita, sem limite diário, aceita IPs de servidor ─
# Registro grátis em https://www.football-data.org/client/register
# Depois adicione FOOTBALL_DATA_KEY nas variáveis de ambiente do Render
FOOTBALL_DATA_KEY  = os.environ.get("FOOTBALL_DATA_KEY", "")
FOOTBALL_DATA_BASE = "https://api.football-data.org/v4"

_FD_STATUS = {
    "SCHEDULED": "NS", "TIMED": "NS",
    "IN_PLAY":   "1H",   # API não informa minuto na listagem
    "PAUSED":    "HT",
    "FINISHED":  "FT",  "POSTPONED": "PST",
    "CANCELLED": "CANC", "SUSPENDED": "PST",
}
_FD_SKIP = {"FT", "PST", "CANC"}

# Diagnóstico em tempo real — atualizado a cada chamada às APIs de fixtures
_api_diag: dict = {}

# ── Caches para proteger a cota de 100 req/dia da API-Football ─────────────
_standings_cache: dict = {}
_standings_cache_date: str = ""

# Cache de fixtures: evita req repetida quando usuário clica várias vezes
# TTL de 4 minutos — dados de fixture não mudam tão rápido
_fixtures_cache: dict = {"data": None, "ts": 0, "date": ""}
_FIXTURES_TTL = 600  # segundos (10 min) — preserva cota de 100 req/dia

# Groq
GROQ_KEY      = os.environ.get("GROQ_KEY", "")
GROQ_BASE     = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL_ANALYSIS  = "llama-3.3-70b-versatile"  # Principal: análise profunda
GROQ_MODEL_CHAT      = "llama-3.1-8b-instant"      # Chat: 6k TPM, 500k TPD
GROQ_MODEL_FALLBACK  = "llama-3.1-8b-instant"      # Fallback com prompt compacto

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
    Cache diário — cada liga só consome 1 req/dia.
    Limita novas requisições a 4 por chamada para proteger cota de 100 req/dia.
    """
    global _standings_cache, _standings_cache_date
    today = datetime.now().strftime("%Y-%m-%d")
    if _standings_cache_date != today:
        _standings_cache = {}
        _standings_cache_date = today

    result = {}
    current_year = datetime.now().year
    new_requests = 0  # máx 4 novas req por chamada
    for lid in league_ids:
        if lid in _standings_cache:
            result[lid] = _standings_cache[lid]
            continue
        if new_requests >= 4:  # protege cota diária
            break
        new_requests += 1
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


# Prompt compacto para o modelo fallback (8B, 6k TPM)
FALLBACK_SYSTEM_PROMPT = """Você é APEX TRADE, trader esportivo profissional com 27 anos de experiência. Analise os jogos fornecidos usando seu conhecimento de forma, H2H e contexto de cada liga.

REGRAS OBRIGATÓRIAS:
- Use APENAS os jogos da lista com IDs numéricos exatos (só o número, sem "ID:")
- Gere valores REAIS para cada campo — NÃO copie valores de exemplos
- Selecione TOP 5 com maior EV+ para o perfil solicitado
- Nunca invente jogos fora da lista

CAMPOS OBRIGATÓRIOS por jogo (gere valores reais baseados na sua análise):
- id: string com o número do ID exato da lista
- homeTeam / awayTeam: nomes exatos como na lista
- league, time, status, score, elapsed: copie da lista
- market: mercado escolhido (ex: "Over 2.5", "BTTS Sim", "Handicap -1.5")
- selection: seleção (ex: "Over", "Sim", "Casa -1.5")
- odds: odds estimadas entre 1.30 e 4.00 — CALCULE baseado na probabilidade
- probability: inteiro 40-85 — sua estimativa real de probabilidade
- ev: número 1.0-15.0 — calcule: (probability/100 * odds - 1) * 100
- confidence: inteiro 50-90 — sua confiança no edge
- stake: inteiro 1-5 — baseado no ev (ev<4→1, ev<7→2, ev<11→3, ev>=11→4)
- consistencyScore: inteiro 0-100 — quantos fatores confirmam o edge
- riskLevel: "baixo" se score>=70, "médio" se >=55, "alto" se <55
- suspiciousMovement: false na maioria dos casos, true só se odds caíram >15% sem motivo
- xgHome / xgAway: estimativa de xG entre 0.5 e 3.5
- reasoning: análise fundamentada em 1-2 frases
- edge: por que existe valor neste mercado
- entryTiming: "pré-jogo" ou "kickoff" ou "ao vivo — min X"
- exitCondition: quando sair
- mainRisk: principal risco
- anglesCount: inteiro 1-5
- opportunities: array com o mercado principal: [{"market":"...","selection":"...","odds":X.XX}]

Resposta: JSON puro sem markdown.
{"type":"analysis","matches":[...],"dailySummary":"2-3 frases sobre o dia","marketAlert":null}"""


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

    # Fallback: 429 (limite diário) ou 413 (request muito grande)
    # Usa prompt compacto + menos tokens para caber no 8B (6k TPM)
    if res.status_code in (429, 413) and model != GROQ_MODEL_FALLBACK:
        fallback_prompt = FALLBACK_SYSTEM_PROMPT if system_prompt == SYSTEM_PROMPT else system_prompt
        fallback_messages = [{"role": "system", "content": fallback_prompt}] + messages
        res = _groq_post(GROQ_MODEL_FALLBACK, fallback_messages, min(max_tokens, 2000), temperature)

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


def _num(val, default, lo, hi):
    """Converte val para float dentro de [lo, hi]; retorna default se inválido ou NaN."""
    try:
        v = float(val)
        if v != v:  # NaN check (NaN != NaN em IEEE 754)
            return default
        if lo <= v <= hi:
            return v
        return float(max(lo, min(hi, v)))
    except (TypeError, ValueError):
        return default


def sanitize_matches(matches):
    """
    Garante que todos os campos numéricos são válidos no nível raiz E dentro
    de opportunities — corrige NaN/None vindos do AI antes de chegar ao frontend.
    """
    sanitized = []
    for m in matches:
        try:
            odds        = _num(m.get("odds"),            1.85, 1.30, 4.00)
            probability = _num(m.get("probability"),     58,   40,   85)
            confidence  = _num(m.get("confidence"),      65,   50,   90)
            score_val   = _num(m.get("consistencyScore"),65,   0,    100)
            xg_home     = _num(m.get("xgHome"),          1.4,  0.5,  3.5)
            xg_away     = _num(m.get("xgAway"),          1.2,  0.5,  3.5)
            stake       = int(_num(m.get("stake"),        2,    1,    5))

            # EV: tenta usar o valor do AI; recalcula se ausente/inválido/NaN
            ev_raw = m.get("ev")
            try:
                ev = float(ev_raw)
                if ev != ev or not (1.0 <= ev <= 15.0):  # NaN ou fora do range
                    raise ValueError
            except (TypeError, ValueError):
                ev = round((probability / 100 * odds - 1) * 100, 1)
                ev = max(1.0, min(15.0, ev))

            risk = m.get("riskLevel", "")
            if risk not in ("baixo", "médio", "alto"):
                risk = "baixo" if score_val >= 70 else ("médio" if score_val >= 55 else "alto")

            m.update({
                "odds":              round(odds, 2),
                "probability":       int(probability),
                "confidence":        int(confidence),
                "consistencyScore":  int(score_val),
                "xgHome":            round(xg_home, 1),
                "xgAway":            round(xg_away, 1),
                "stake":             stake,
                "ev":                round(ev, 1),
                "riskLevel":         risk,
                "suspiciousMovement": bool(m.get("suspiciousMovement", False)),
            })

            # Sincroniza todos os campos numéricos dentro de opportunities[]
            # (o frontend pode ler de lá em vez do nível raiz)
            for opp in m.get("opportunities", []):
                opp["odds"]        = round(_num(opp.get("odds"), odds, 1.30, 4.00), 2)
                opp["probability"] = int(probability)
                opp["ev"]          = round(ev, 1)
                opp["stake"]       = stake
                opp["confidence"]  = int(confidence)
                opp["consistencyScore"] = int(score_val)

            sanitized.append(m)
        except Exception:
            # Se um match específico falhar na sanitização, mantém como está
            sanitized.append(m)

    return sanitized


@app.route("/")
def index():
    return jsonify({
        "status": "APEX TRADE Backend online",
        "version": "4.1",
        "ai": "Groq/LLaMA-3.3-70b",
        "football_data_key_set": bool(FOOTBALL_DATA_KEY),
        "football_data_key_preview": (FOOTBALL_DATA_KEY[:4] + "****") if FOOTBALL_DATA_KEY else None,
        "api_diag": _api_diag,
    })

@app.route("/health")
def health():
    return jsonify({
        "ok": True,
        "time": datetime.now().isoformat(),
        "football_data_key_set": bool(FOOTBALL_DATA_KEY),
        "api_diag": _api_diag,
    })

def _parse_fixtures(response):
    """Transforma resposta da API-Football em lista de fixtures filtrados."""
    fixtures = []
    for f in response:
        status_short = f.get("fixture", {}).get("status", {}).get("short", "")
        if status_short in ["FT", "AET", "PEN", "CANC", "PST", "ABD", "AWD", "WO"]:
            continue
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
            "id":       str(f.get("fixture", {}).get("id", "")),
            "home":     f.get("teams", {}).get("home", {}).get("name", ""),
            "away":     f.get("teams", {}).get("away", {}).get("name", ""),
            "league":   f.get("league", {}).get("name", ""),
            "country":  f.get("league", {}).get("country", ""),
            "time":     time_str,
            "status":   status_short,
            "score":    score,
            "elapsed":  f.get("fixture", {}).get("status", {}).get("elapsed") or 0,
            "league_id": league_id,
        })
    return fixtures[:20]


def get_fixtures_from_thesportsdb(date_str: str) -> list:
    """
    Busca fixtures na TheSportsDB (gratuita, sem limite diário, sem chave).
    Retorna lista no mesmo formato de _parse_fixtures().

    TheSportsDB atualiza status muito devagar — inferimos o status real
    comparando o horário de kickoff (UTC→BRT) com a hora atual.
    """
    try:
        url = f"{THESPORTSDB_BASE}/eventsday.php?d={date_str}&s=Soccer"
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            return []
        events = r.json().get("events") or []
    except Exception:
        return []

    now_brt   = datetime.utcnow() - timedelta(hours=3)
    today_brt = now_brt.strftime("%Y-%m-%d")

    betano = []
    others = []

    for ev in events:
        raw_status = ev.get("strStatus") or ""
        status = TSDB_STATUS_MAP.get(raw_status, "NS")
        if status in _TSDB_SKIP:
            continue

        # Converte horário UTC → BRT (UTC-3)
        raw_time = ev.get("strTime") or ""
        try:
            utc_dt   = datetime.strptime(f"{date_str} {raw_time[:5]}", "%Y-%m-%d %H:%M")
            time_str = (utc_dt - timedelta(hours=3)).strftime("%H:%M")
        except Exception:
            time_str = raw_time[:5] if raw_time else ""

        # Inferir status real pelo horário — TheSportsDB fica travado em "NS"
        elapsed = 0
        if status == "NS" and time_str:
            try:
                kickoff = datetime.strptime(f"{today_brt} {time_str}", "%Y-%m-%d %H:%M")
                mins    = (now_brt - kickoff).total_seconds() / 60
                if mins > 110:
                    continue          # Encerrado — descarta
                elif mins > 52:
                    status, elapsed = "2H", min(90, int(mins) - 15)
                elif mins > 47:
                    status, elapsed = "HT", 45
                elif mins > 2:
                    status, elapsed = "1H", min(45, int(mins))
                # else: ainda não começou → mantém NS
            except Exception:
                pass

        home_score = ev.get("intHomeScore")
        away_score = ev.get("intAwayScore")
        score = (f"{home_score}-{away_score}"
                 if home_score is not None and away_score is not None else "-")

        if not elapsed:
            try:
                elapsed = int(ev.get("strProgress") or 0)
            except (ValueError, TypeError):
                elapsed = 45 if status == "HT" else 0

        fixture = {
            "id":        f"tsdb_{ev.get('idEvent', '')}",
            "home":      ev.get("strHomeTeam", ""),
            "away":      ev.get("strAwayTeam", ""),
            "league":    ev.get("strLeague", ""),
            "country":   ev.get("strCountry", ""),
            "time":      time_str,
            "status":    status,
            "score":     score,
            "elapsed":   elapsed,
            "league_id": 0,
            "source":    "thesportsdb",
        }

        league_lower = (ev.get("strLeague") or "").lower()
        if any(kw in league_lower for kw in BETANO_LEAGUES_TSDB):
            betano.append(fixture)
        else:
            others.append(fixture)

    # Prefere ligas Betano; se o filtro não retornar nada, usa todos os jogos
    # disponíveis (melhor que retornar erro)
    result = betano if betano else others
    return result[:20]


def _parse_espn_event(ev: dict, league_name: str, country: str) -> dict | None:
    """Converte um evento ESPN no formato interno de fixture."""
    try:
        comp        = ev.get("competitions", [{}])[0]
        status_obj  = comp.get("status", {})
        status_name = status_obj.get("type", {}).get("name", "STATUS_SCHEDULED")
        status      = ESPN_STATUS_MAP.get(status_name, "NS")
        if status in _ESPN_SKIP:
            return None

        # Refina LIVE → 1H ou 2H pelo período
        elapsed = 0
        if status == "LIVE":
            period  = status_obj.get("period", 1)
            status  = "2H" if period >= 2 else "1H"
            clock   = status_obj.get("displayClock", "0:00")
            try:
                elapsed = int(clock.split(":")[0])
            except Exception:
                pass
        elif status == "HT":
            elapsed = 45

        # Times e placar
        home_team = away_team = ""
        home_score = away_score = None
        for ct in comp.get("competitors", []):
            name  = ct.get("team", {}).get("displayName", "")
            score = ct.get("score")
            if ct.get("homeAway") == "home":
                home_team, home_score = name, score
            else:
                away_team, away_score = name, score

        if not home_team or not away_team:
            return None

        score = (f"{home_score}-{away_score}"
                 if home_score is not None and away_score is not None else "-")

        # Horário UTC → BRT
        raw_date = ev.get("date", "")
        try:
            utc_dt   = datetime.strptime(raw_date[:16], "%Y-%m-%dT%H:%M")
            time_str = (utc_dt - timedelta(hours=3)).strftime("%H:%M")
        except Exception:
            time_str = ""

        # Nome da liga real (ESPN retorna no objeto leagues da resposta)
        real_league = ev.get("_league", league_name)

        return {
            "id":        f"espn_{ev.get('id', '')}",
            "home":      home_team,
            "away":      away_team,
            "league":    real_league,
            "country":   country,
            "time":      time_str,
            "status":    status,
            "score":     score,
            "elapsed":   elapsed,
            "league_id": 0,
            "source":    "espn",
        }
    except Exception:
        return None


_ESPN_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.espn.com",
    "Referer": "https://www.espn.com/",
}


def get_fixtures_from_espn(date_str: str) -> list:
    """
    Busca fixtures de hoje nas ligas Betano via ESPN API pública (sem chave, sem limite).
    Faz chamadas paralelas — tempo total ~3-5 s.
    User-Agent de browser é obrigatório para ESPN não bloquear o request.
    """
    espn_date = date_str.replace("-", "")  # YYYYMMDD

    def fetch_league(slug: str, league_name: str, country: str) -> list:
        try:
            url = (f"https://site.api.espn.com/apis/site/v2"
                   f"/sports/soccer/{slug}/scoreboard")
            r = requests.get(
                url,
                headers=_ESPN_HEADERS,
                params={"dates": espn_date, "limit": 50},
                timeout=8,
            )
            if r.status_code != 200:
                return []
            data = r.json()
            real_league = league_name
            if data.get("leagues"):
                real_league = data["leagues"][0].get("name", league_name)
            fixtures = []
            for ev in data.get("events", []):
                ev["_league"] = real_league
                parsed = _parse_espn_event(ev, real_league, country)
                if parsed:
                    fixtures.append(parsed)
            return fixtures
        except Exception:
            return []

    all_fixtures: list = []
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [
                pool.submit(fetch_league, slug, name, country)
                for slug, name, country in ESPN_LEAGUE_SLUGS
            ]
            # as_completed pode lançar TimeoutError — precisa estar no try externo
            for fut in as_completed(futures, timeout=18):
                try:
                    all_fixtures.extend(fut.result())
                except Exception:
                    pass
    except Exception:
        pass  # TimeoutError ou qualquer falha no pool

    all_fixtures.sort(key=lambda f: f.get("time", ""))
    return all_fixtures[:25]


def get_fixtures_from_sofascore(date_str: str) -> list:
    """
    Busca todos os jogos de futebol do dia na SofaScore (API pública, 1 chamada).
    Filtra pelas ligas da Betano; fallback para todos os jogos se filtro vazio.
    """
    try:
        url = f"{SOFASCORE_BASE}/sport/football/scheduled-events/{date_str}"
        r = requests.get(url, headers=_SOFASCORE_HEADERS, timeout=12)
        if r.status_code != 200:
            return []
        events = r.json().get("events") or []
    except Exception:
        return []

    betano = []
    others = []

    for ev in events:
        status_code = ev.get("status", {}).get("code", 0)
        status = _SS_STATUS.get(status_code, "NS")
        if status in _SS_SKIP:
            continue

        home_team = ev.get("homeTeam", {}).get("name", "")
        away_team = ev.get("awayTeam", {}).get("name", "")
        if not home_team or not away_team:
            continue

        # Horário: startTimestamp é UTC
        start_ts = ev.get("startTimestamp", 0)
        try:
            utc_dt   = datetime.utcfromtimestamp(start_ts)
            time_str = (utc_dt - timedelta(hours=3)).strftime("%H:%M")
        except Exception:
            time_str = ""

        # Placar
        hs = ev.get("homeScore", {}).get("current")
        as_ = ev.get("awayScore", {}).get("current")
        score = f"{hs}-{as_}" if hs is not None and as_ is not None else "-"

        # Minutos decorridos para jogos ao vivo
        elapsed = 0
        if status in ("1H", "2H", "ET"):
            period_ts = ev.get("time", {}).get("currentPeriodStartTimestamp", 0)
            if period_ts:
                mins = (time.time() - period_ts) / 60
                if status == "2H":
                    elapsed = min(90, 45 + int(mins))
                else:
                    elapsed = min(45, int(mins))
        elif status == "HT":
            elapsed = 45

        tournament  = ev.get("tournament", {})
        league_name = (tournament.get("uniqueTournament") or {}).get("name", "") \
                      or tournament.get("name", "")
        country     = ev.get("homeTeam", {}).get("country", {}).get("name", "")

        fixture = {
            "id":        f"ss_{ev.get('id', '')}",
            "home":      home_team,
            "away":      away_team,
            "league":    league_name,
            "country":   country,
            "time":      time_str,
            "status":    status,
            "score":     score,
            "elapsed":   elapsed,
            "league_id": 0,
            "source":    "sofascore",
        }

        if any(kw in league_name.lower() for kw in BETANO_LEAGUES_TSDB):
            betano.append(fixture)
        else:
            others.append(fixture)

    result = betano if betano else others
    result.sort(key=lambda f: f.get("time", ""))
    return result[:25]


def get_fixtures_from_football_data(date_str: str) -> list:
    """
    football-data.org — gratuita, sem limite diário, projetada para acesso
    de servidor. Requer FOOTBALL_DATA_KEY no ambiente.
    """
    if not FOOTBALL_DATA_KEY:
        _api_diag["football_data"] = {"ok": False, "error": "KEY_NOT_SET"}
        return []
    try:
        r = requests.get(
            f"{FOOTBALL_DATA_BASE}/matches",
            headers={"X-Auth-Token": FOOTBALL_DATA_KEY},
            params={"dateFrom": date_str, "dateTo": date_str},
            timeout=12,
        )
        diag = {"http": r.status_code, "ok": False}
        if r.status_code == 429:
            diag["error"] = "RATE_LIMITED_10rpm"
            _api_diag["football_data"] = diag
            return []
        if r.status_code != 200:
            diag["error"] = r.text[:300]
            _api_diag["football_data"] = diag
            return []
        body    = r.json()
        matches = body.get("matches", [])
        diag["ok"]          = True
        diag["total"]       = len(matches)
        diag["competitions"] = list({m.get("competition", {}).get("name","") for m in matches})
        _api_diag["football_data"] = diag
    except Exception as e:
        _api_diag["football_data"] = {"ok": False, "error": str(e)}
        return []

    fixtures = []
    for m in matches:
        status_str = m.get("status", "SCHEDULED")
        status     = _FD_STATUS.get(status_str, "NS")
        if status in _FD_SKIP:
            continue

        elapsed = 45 if status == "HT" else 0

        # Horário UTC → BRT
        utc_str = m.get("utcDate", "")
        try:
            utc_dt   = datetime.strptime(utc_str[:16], "%Y-%m-%dT%H:%M")
            time_str = (utc_dt - timedelta(hours=3)).strftime("%H:%M")
        except Exception:
            time_str = ""

        home = (m.get("homeTeam") or {}).get("name", "") or \
               (m.get("homeTeam") or {}).get("shortName", "")
        away = (m.get("awayTeam") or {}).get("name", "") or \
               (m.get("awayTeam") or {}).get("shortName", "")
        if not home or not away:
            continue

        ft   = (m.get("score") or {}).get("fullTime") or {}
        hs   = ft.get("home")
        as_  = ft.get("away")
        score = f"{hs}-{as_}" if hs is not None and as_ is not None else "-"

        comp        = m.get("competition") or {}
        league_name = comp.get("name", "")
        country     = (comp.get("area") or {}).get("name", "")

        fixtures.append({
            "id":        str(m.get("id", "")),
            "home":      home,
            "away":      away,
            "league":    league_name,
            "country":   country,
            "time":      time_str,
            "status":    status,
            "score":     score,
            "elapsed":   elapsed,
            "league_id": 0,
            "source":    "football-data",
        })

    fixtures.sort(key=lambda f: f.get("time", ""))
    return fixtures[:25]


def _filter_past_fixtures(fixtures: list) -> list:
    """
    Remove fixtures com status 'NS' cujo horário de kickoff já passou.
    TheSportsDB (e às vezes a API-Football) demora a atualizar o status,
    então jogos que já começaram ou terminaram podem aparecer como NS.
    Threshold: 30 minutos após o kickoff → assume que o jogo começou.
    """
    now_brt = datetime.utcnow() - timedelta(hours=3)
    today_brt = now_brt.strftime("%Y-%m-%d")
    result = []
    for f in fixtures:
        if f.get("status") != "NS":
            result.append(f)
            continue
        time_str = f.get("time", "")
        if not time_str:
            result.append(f)
            continue
        try:
            kickoff = datetime.strptime(f"{today_brt} {time_str}", "%Y-%m-%d %H:%M")
            if (now_brt - kickoff).total_seconds() > 30 * 60:
                continue  # kickoff passou há mais de 30 min — API com status desatualizado
        except Exception:
            pass
        result.append(f)
    return result


@app.route("/fixtures/today")
def fixtures_today():
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        now   = time.time()

        # Serve do cache se ainda válido
        c = _fixtures_cache
        if c["data"] is not None and c["date"] == today and (now - c["ts"]) < _FIXTURES_TTL:
            filtered = _filter_past_fixtures(c["data"])
            return jsonify({"success": True, "count": len(filtered),
                            "fixtures": filtered, "date": today, "cached": True})

        # ── Fonte principal: football-data.org (sem limite diário, funciona em servidores)
        if FOOTBALL_DATA_KEY:
            fd = get_fixtures_from_football_data(today)
            if fd:
                c["data"] = fd; c["ts"] = now; c["date"] = today
                return jsonify({"success": True, "count": len(fd),
                                "fixtures": fd, "date": today, "source": "football-data"})

        # ── Fonte secundária: API-Football (100 req/dia)
        res = requests.get(
            f"{API_BASE}/fixtures?date={today}&timezone=America/Sao_Paulo",
            headers=API_HEADERS, timeout=15
        )
        is_rate_limited = res.status_code == 429
        if res.status_code not in (200, 429):
            is_rate_limited = True  # trata erro como esgotamento
        if not is_rate_limited:
            data = res.json()
            if data.get("errors"):
                is_rate_limited = True

        if not is_rate_limited:
            fixtures = _filter_past_fixtures(_parse_fixtures(data.get("response", [])))
            c["data"] = fixtures; c["ts"] = now; c["date"] = today
            return jsonify({"success": True, "count": len(fixtures),
                            "fixtures": fixtures, "date": today})

        # ── Fallbacks quando API-Football está esgotada ─────────────────────
        # 1: football-data.org (mesmo sem key definida, tenta novamente caso haja race)
        fd = get_fixtures_from_football_data(today)
        if fd:
            c["data"] = fd; c["ts"] = now; c["date"] = today
            return jsonify({"success": True, "count": len(fd),
                            "fixtures": fd, "date": today, "source": "football-data"})

        # 2: SofaScore
        ss = get_fixtures_from_sofascore(today)
        if ss:
            c["data"] = ss; c["ts"] = now; c["date"] = today
            return jsonify({"success": True, "count": len(ss),
                            "fixtures": ss, "date": today, "source": "sofascore"})

        # 3: ESPN
        espn = get_fixtures_from_espn(today)
        if espn:
            c["data"] = espn; c["ts"] = now; c["date"] = today
            return jsonify({"success": True, "count": len(espn),
                            "fixtures": espn, "date": today, "source": "espn"})

        # 4: TheSportsDB
        tsdb = get_fixtures_from_thesportsdb(today)
        if tsdb:
            c["data"] = tsdb; c["ts"] = now; c["date"] = today
            return jsonify({"success": True, "count": len(tsdb),
                            "fixtures": tsdb, "date": today, "source": "thesportsdb"})

        # 5: cache antigo
        if c["data"] is not None:
            stale = _filter_past_fixtures(c["data"])
            return jsonify({"success": True, "count": len(stale),
                            "fixtures": stale, "date": c["date"], "cached": True,
                            "warning": "Usando dados em cache."})

        fd_diag = _api_diag.get("football_data", {})
        if not FOOTBALL_DATA_KEY:
            msg = "FOOTBALL_DATA_KEY nao detectada no ambiente do Render."
        elif fd_diag.get("http") and fd_diag["http"] != 200:
            msg = f"football-data.org retornou HTTP {fd_diag['http']}: {fd_diag.get('error','')}"
        elif fd_diag.get("ok") and fd_diag.get("total", 0) == 0:
            msg = "Nenhum jogo encontrado hoje nas ligas cobertas pelo plano gratuito."
        else:
            msg = f"Todas as fontes falharam. Diagnostico: {fd_diag}"
        return jsonify({"success": False, "error": msg, "diag": _api_diag}), 503

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
        # Standings e live stats desabilitados — a API-Football tem apenas 100 req/dia
        # e o budget precisa ser preservado para o /fixtures/today (1 req/4min).
        # O AI usa seu conhecimento interno para estimar forma e probabilidades.
        standings_ctx = ""
        live_ctx      = ""
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
            parsed["matches"] = sanitize_matches(parsed["matches"])
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


@app.route("/fixtures/debug")
def fixtures_debug():
    """Testa conectividade com cada fonte de fixtures e retorna diagnóstico."""
    today = datetime.now().strftime("%Y-%m-%d")
    results = {}

    # Testa football-data.org
    if FOOTBALL_DATA_KEY:
        try:
            r = requests.get(
                f"{FOOTBALL_DATA_BASE}/matches",
                headers={"X-Auth-Token": FOOTBALL_DATA_KEY},
                params={"dateFrom": today, "dateTo": today},
                timeout=10,
            )
            body = r.json() if r.status_code == 200 else {}
            results["football_data_org"] = {
                "http": r.status_code,
                "matches": len(body.get("matches") or []),
                "ok": r.status_code == 200,
            }
        except Exception as e:
            results["football_data_org"] = {"http": None, "matches": 0, "ok": False, "error": str(e)}
    else:
        results["football_data_org"] = {"ok": False, "error": "FOOTBALL_DATA_KEY não configurada"}

    # Testa SofaScore
    try:
        url = f"{SOFASCORE_BASE}/sport/football/scheduled-events/{today}"
        r = requests.get(url, headers=_SOFASCORE_HEADERS, timeout=10)
        body = r.json() if r.status_code == 200 else {}
        results["sofascore"] = {
            "http": r.status_code,
            "events": len(body.get("events") or []),
            "ok": r.status_code == 200,
        }
    except Exception as e:
        results["sofascore"] = {"http": None, "events": 0, "ok": False, "error": str(e)}

    # Testa ESPN (só eng.1 para diagnóstico rápido)
    try:
        url = "https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1/scoreboard"
        r = requests.get(url, headers=_ESPN_HEADERS,
                         params={"dates": today.replace("-", "")}, timeout=8)
        body = r.json() if r.status_code == 200 else {}
        results["espn_eng1"] = {
            "http": r.status_code,
            "events": len(body.get("events") or []),
            "ok": r.status_code == 200,
        }
    except Exception as e:
        results["espn_eng1"] = {"http": None, "events": 0, "ok": False, "error": str(e)}

    # Testa TheSportsDB
    try:
        url = f"{THESPORTSDB_BASE}/eventsday.php?d={today}&s=Soccer"
        r = requests.get(url, timeout=10)
        body = r.json() if r.status_code == 200 else {}
        results["thesportsdb"] = {
            "http": r.status_code,
            "events": len(body.get("events") or []),
            "ok": r.status_code == 200 and bool(body.get("events")),
        }
    except Exception as e:
        results["thesportsdb"] = {"http": None, "events": 0, "ok": False, "error": str(e)}

    # Testa API-Football
    try:
        r = requests.get(f"{API_BASE}/status", headers=API_HEADERS, timeout=8)
        body = r.json() if r.status_code == 200 else {}
        sub = body.get("response", {}).get("requests", {})
        results["api_football"] = {
            "http": r.status_code,
            "requests_used": sub.get("current", "?"),
            "requests_limit": sub.get("limit_day", "?"),
            "ok": r.status_code == 200,
        }
    except Exception as e:
        results["api_football"] = {"http": None, "ok": False, "error": str(e)}

    return jsonify({"date": today, "sources": results})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

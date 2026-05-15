from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
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
    "paranaense", "mineiro", "baiano", "pernambucano", "goiano",
    # Europa Top 5
    "premier league", "championship",
    "ligue 1", "ligue 2",
    "bundesliga",
    "la liga",
    "serie a", "serie b",
    "eredivisie",
    "primeira liga",
    "jupiler",
    "scottish premier",
    # Europa — outras ligas cobertas pela Betano
    "superliga", "danish superliga", "allsvenskan", "eliteserien",
    "super league", "swiss super",
    "austrian bundesliga", "austria",
    "greek super", "super league greece",
    "hnl", "croatian",
    "liga i", "romanian",
    "ukrainian premier", "premier liga ukraine",
    "first league", "czech",
    "super liga", "serbian",
    "ligat ha'al", "israeli premier",
    "ekstraklasa",
    "fortuna liga", "slovak",
    "veikkausliiga", "finnish",
    "premier league russia", "russian premier",
    "meistriliiga", "estonian",
    "a lyga", "lithuanian",
    "virsliga", "latvian",
    "nemzeti bajnokság", "hungarian",
    "premier league of belarus", "belarusian",
    "nations league",
    # Competições europeias
    "champions league", "europa league", "conference league",
    # América do Sul
    "libertadores", "sudamericana",
    "liga profesional", "apertura", "clausura",
    "primera división", "primera division",
    "liga pro", "ligapro", "ecuadorian",
    "descentralizado", "peruvian",
    "campeonato uruguayo", "uruguayan",
    "primera división de chile", "chilean",
    "venezuelan", "primera",
    "liga betplay", "colombian",
    # Internacional
    "liga mx", "mls",
    "saudi pro", "saudi premier",
    "super lig", "süper lig",
    "j1 league", "j-league", "japanese",
    "chinese super", "china super",
    "k league", "korean",
    "a-league", "australian",
    "qatar stars", "qsl",
    "uae pro", "arabian gulf",
    "egypt premier", "egyptian",
    "south african premier", "psl",
    "copa america", "world cup", "copa del rey",
    "fa cup", "dfb pokal", "coppa italia",
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
    ("arg.1",                 "Liga Profesional",        "Argentina"),
    ("col.1",                 "Liga Betplay",            "Colombia"),
    ("chi.1",                 "Primera División",        "Chile"),
    ("uru.1",                 "Primera División",        "Uruguay"),
    ("ecu.1",                 "LigaPro",                 "Ecuador"),
    ("per.1",                 "Primera División",        "Peru"),
    ("ven.1",                 "Primera División",        "Venezuela"),
    ("den.1",                 "Superliga",               "Denmark"),
    ("nor.1",                 "Eliteserien",             "Norway"),
    ("swe.1",                 "Allsvenskan",             "Sweden"),
    ("sui.1",                 "Super League",            "Switzerland"),
    ("aut.1",                 "Bundesliga",              "Austria"),
    ("gre.1",                 "Super League",            "Greece"),
    ("cro.1",                 "HNL",                     "Croatia"),
    ("rom.1",                 "Liga I",                  "Romania"),
    ("ukr.1",                 "Premier League",          "Ukraine"),
    ("cze.1",                 "First League",            "Czech Republic"),
    ("srb.1",                 "Super Liga",              "Serbia"),
    ("isr.1",                 "Premier League",          "Israel"),
    ("jpn.1",                 "J1 League",               "Japan"),
    ("chn.1",                 "Super League",            "China"),
    ("kor.1",                 "K League 1",              "South Korea"),
    ("aus.1",                 "A-League",                "Australia"),
    ("tur.1",                 "Süper Lig",               "Turkey"),
    ("pol.1",                 "Ekstraklasa",             "Poland"),
    ("rus.1",                 "Premier League",          "Russia"),
    ("sau.1",                 "Pro League",              "Saudi Arabia"),
    ("qat.1",                 "Stars League",            "Qatar"),
    ("egy.1",                 "Premier League",          "Egypt"),
    ("rsa.1",                 "Premier Soccer League",   "South Africa"),
    ("uae.1",                 "Pro League",              "UAE"),
    ("uefa.champions",        "Champions League",        "Europe"),
    ("uefa.europa",           "Europa League",           "Europe"),
    ("uefa.europa.conf",      "Conference League",       "Europe"),
    ("conmebol.libertadores", "Copa Libertadores",       "South America"),
    ("conmebol.sudamericana", "Copa Sudamericana",       "South America"),
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
# Todas as competições acessíveis no plano gratuito do football-data.org
_FD_COMPETITIONS = "PL,ELC,BL1,PD,SA,FL1,DED,PPL,CL,EC,BSA"

# Diagnóstico em tempo real — atualizado a cada chamada às APIs de fixtures
_api_diag: dict = {}

# ── Caches para proteger a cota de 100 req/dia da API-Football ─────────────
_standings_cache: dict = {}
_standings_cache_date: str = ""

# ── Cache em memória (perdido na hibernação do Render) ────────────────────────
_fixtures_cache: dict = {"data": None, "ts": 0, "date": ""}
_FIXTURES_TTL = 900  # 15 min — reduz chamadas dentro do mesmo ciclo ativo

# ── Cache em arquivo (sobrevive hibernações, perdido apenas no redeploy) ───────
_FILE_CACHE_DIR = Path("/tmp")

def _file_cache_path(date_str: str) -> Path:
    return _FILE_CACHE_DIR / f"apex_fixtures_{date_str}.json"

def _read_file_cache(date_str: str) -> list | None:
    """Lê fixtures do disco. Retorna None se expirado ou inválido."""
    try:
        p = _file_cache_path(date_str)
        if not p.exists():
            return None
        data = json.loads(p.read_text())
        if data.get("date") != date_str:
            return None
        fixtures = data.get("fixtures", [])
        if not fixtures:
            return None
        # Se houver jogos ao vivo, expirar após 5 min para atualizar placar
        has_live = any(f.get("status") in {"1H", "2H", "HT", "ET", "LIVE"} for f in fixtures)
        age = time.time() - data.get("saved_at", 0)
        if has_live and age > 300:
            return None
        return fixtures
    except Exception:
        return None

def _write_file_cache(date_str: str, fixtures: list) -> None:
    """Salva fixtures no disco para sobreviver hibernações."""
    try:
        _file_cache_path(date_str).write_text(json.dumps({
            "date":     date_str,
            "fixtures": fixtures,
            "saved_at": time.time(),
        }))
    except Exception:
        pass

# Groq
GROQ_KEY      = os.environ.get("GROQ_KEY", "")
GROQ_BASE     = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL_ANALYSIS  = "llama-3.3-70b-versatile"  # Principal: análise profunda
GROQ_MODEL_CHAT      = "llama-3.1-8b-instant"      # Chat: 6k TPM, 500k TPD
GROQ_MODEL_FALLBACK  = "llama-3.1-8b-instant"      # Fallback com prompt compacto

# ── Ligas que a Betano cobre (IDs da API-Football) ─────────────────────────
BETANO_LEAGUE_IDS = {
    # ── Brasil ────────────────────────────────────────────────────────────────
    71,   # Brasileirão Série A
    72,   # Brasileirão Série B
    73,   # Copa do Brasil
    475,  # Campeonato Paulista
    476,  # Campeonato Carioca
    477,  # Campeonato Gaúcho
    478,  # Campeonato Mineiro
    479,  # Campeonato Paranaense
    480,  # Campeonato Baiano
    481,  # Campeonato Pernambucano
    # ── Europa — Top 5 + Ligas importantes ───────────────────────────────────
    39,   # Premier League (Inglaterra)
    40,   # Championship (Inglaterra)
    45,   # FA Cup
    61,   # Ligue 1 (França)
    62,   # Ligue 2 (França)
    66,   # Coupe de France
    78,   # Bundesliga (Alemanha)
    79,   # 2. Bundesliga (Alemanha)
    81,   # DFB Pokal
    135,  # Serie A (Itália)
    136,  # Serie B (Itália)
    137,  # Coppa Italia
    140,  # La Liga (Espanha)
    141,  # La Liga 2 (Espanha)
    143,  # Copa del Rey
    88,   # Eredivisie (Holanda)
    89,   # Eerste Divisie (Holanda)
    94,   # Primeira Liga (Portugal)
    95,   # Segunda Liga (Portugal)
    144,  # Jupiler Pro League (Bélgica)
    179,  # Scottish Premiership (Escócia)
    # ── Europa — Outras ligas cobertas pela Betano ───────────────────────────
    119,  # Superliga (Dinamarca)
    120,  # 1st Division (Dinamarca)
    103,  # Eliteserien (Noruega)
    113,  # Allsvenskan (Suécia)
    114,  # Superettan (Suécia)
    207,  # Swiss Super League
    218,  # Austrian Bundesliga
    197,  # Greek Super League
    210,  # Croatian HNL
    283,  # Romanian Liga I
    333,  # Ukrainian Premier League
    345,  # Czech First League
    286,  # Serbian Super Liga
    384,  # Israeli Premier League
    106,  # Ekstraklasa (Polônia)
    235,  # Russian Premier League
    271,  # Slovak Super Liga
    244,  # Finnish Veikkausliiga
    372,  # Estonian Premium Liiga
    392,  # Lithuanian A Lyga
    115,  # Latvian Virsliga
    343,  # Hungarian Nemzeti Bajnokság
    116,  # Belarusian Premier League
    203,  # Süper Lig (Turquia)
    204,  # TFF First League (Turquia)
    # ── Competições europeias ─────────────────────────────────────────────────
    2,    # Champions League
    3,    # Europa League
    848,  # Conference League
    5,    # UEFA Nations League
    531,  # UEFA Super Cup
    4,    # Euro (Europeu)
    1,    # World Cup
    # ── Copas nacionais (Europa) ──────────────────────────────────────────────
    529,  # Super Cup Espanha
    547,  # Scottish FA Cup
    543,  # Belgian Cup
    # ── América do Sul ────────────────────────────────────────────────────────
    11,   # Copa Libertadores
    13,   # Copa Sudamericana
    128,  # Liga Profesional Argentina
    130,  # Copa Argentina
    131,  # Primera Nacional (Arg B)
    238,  # Liga Betplay (Colômbia)
    265,  # Primera B (Colômbia)
    240,  # Primera División Chile
    241,  # Primera B Chile
    278,  # Campeonato Uruguayo
    268,  # LigaPro (Equador)
    281,  # Liga 1 (Peru)
    295,  # Primera División Venezuela
    9,    # Copa América
    # ── América do Norte / Central ────────────────────────────────────────────
    239,  # Liga MX (México)
    262,  # Liga de Expansión MX
    253,  # MLS (EUA)
    254,  # USL Championship (EUA)
    # ── Ásia ─────────────────────────────────────────────────────────────────
    98,   # J1 League (Japão)
    99,   # J2 League (Japão)
    169,  # Chinese Super League
    292,  # K League 1 (Coreia do Sul)
    293,  # K League 2 (Coreia do Sul)
    29,   # Qatar Stars League
    435,  # UAE Pro League
    17,   # A-League (Austrália)
    # ── Oriente Médio / África ────────────────────────────────────────────────
    307,  # Saudi Pro League
    233,  # Egyptian Premier League
    288,  # South African Premier Division
    # ── Competições mundiais de clubes ────────────────────────────────────────
    15,   # FIFA Club World Cup
    26,   # CONCACAF Champions League
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
SYSTEM_PROMPT = """Você é APEX TRADE — sistema de inteligência de trading esportivo de nível institucional. Não é um apostador. É um operador de mercado quantitativo com leitura contextual humana de elite.

━━━ IDENTIDADE OPERACIONAL ━━━
Seu DNA combina simultaneamente:
• Trader profissional — 27 anos (bookmaker → Betfair Exchange → fundos quant privados)
• Analista tático — leitura de jogo em tempo real, padrões táticos, momentum
• Especialista em microestrutura de mercado — lê odds como linguagem, não como número
• Quant bayesiano — atualiza probabilidades dinamicamente conforme novas informações
• Psicólogo comportamental — detecta distorções emocionais no mercado

Você pensa como instituição, não como apostador recreacional. A diferença é absoluta.

━━━ ARQUITETURA COGNITIVA DE 5 CAMADAS ━━━
Para cada jogo, você processa SIMULTANEAMENTE estas 5 camadas antes de qualquer decisão:

CAMADA 1 — LEITURA ESTATÍSTICA
Analise: xG estimado, xGA, eficiência ofensiva/defensiva, médias de gols (casa/fora separadamente), BTTS histórico, Over/Under por contexto (liga, mando, fase da temporada). Identifique padrões de regressão à média. Detecte times com xG descolado do placar recente (superperformance/underperformance temporária).

CAMADA 2 — LEITURA TÁTICA
Analise: perfil tático de cada time (pressão alta vs bloco baixo vs posse). Encaixe tático do confronto — time de pressão vs time de contra-ataque cria dinâmica específica. Desgaste físico acumulado (copa + liga na mesma semana). Substituições que mudam postura. Times que alteram sistema em jogos decisivos. Momentum emocional pós-resultado anterior.

CAMADA 3 — LEITURA DE MERCADO
Analise: onde o mercado provavelmente está precificando mal. Identifique: mercados de alta eficiência (1X2 em jogos de alto perfil) vs mercados de baixa eficiência (Over/Under em ligas secundárias, BTTS em ligas obscuras, 1º tempo). Detecte se há valor real ou se o mercado já corrigiu. Avalie assimetria risco-retorno. Mercados secundários (escanteios, cartões, 1º tempo) frequentemente menos eficientes.

CAMADA 4 — CONTEXTO INVISÍVEL
Fatores que modelos tradicionais ignoram: Motivação real de cada time (necessidade de pontos, jogo "morto" para um lado). Impacto psicológico do confronto (clássico, rivalidade, histórico recente). Desgaste acumulado da temporada (times com 50+ jogos perdem intensidade mesmo com elenco completo). Padrão comportamental pós-trauma (time que perdeu clássico costuma reagir exageradamente). Pressão da torcida em casa vs vantagem do mando real. Jogos entre equipes que se conhecem profundamente (H2H táticos específicos).

CAMADA 5 — META-INTELIGÊNCIA (ANTI-VIÉS)
Antes de finalizar qualquer recomendação, questione ativamente:
• "Estou vendo edge real ou confirmação estatística de algo que o mercado já precificou?"
• "O mercado já sabe isso — quanto valor real resta?"
• "Esse edge é robusto a múltiplos cenários ou frágil demais?"
• "O risco invisível (lesão não divulgada, informação de última hora) é maior do que parece?"
• "Estou sendo arrastado pela narrativa ou pelos números?"
• "É melhor esperar e ter mais certeza, mesmo perdendo a entrada?"
• "Existe armadilha emocional criada pelo mercado aqui?"

━━━ PROTOCOLO ANTI-EDGE FALSO ━━━
Rejeite entradas quando detectar:
✗ Edge puramente estatístico sem confirmação tática/contextual
✗ Mercado que já reagiu completamente ao fator identificado
✗ Times com motivação assimétrica onde o lado mais forte tem menos a ganhar
✗ Jogos com resultado já matematicamente definido para um dos lados
✗ Estatísticas de forma recente distorcidas por adversários fracos/fortes demais
✗ Jogos onde contexto emocional supera lógica probabilística (derbies, rebaixamento emocional)
✗ Odds que parecem boas mas já refletem sharp action não visível ao público

━━━ DETECÇÃO DE ARMADILHAS DE MERCADO ━━━
O mercado cria armadilhas sistemáticas que destroem apostadores não sofisticados:
→ "Favorito óbvio": times favoritos em jogos considerados fáceis frequentemente têm odds sub-precificadas em handicap porque o público superestima a vitória fácil
→ "Reação exagerada": lesão de estrela cria movimento de odds 15-25% para o lado oposto, frequentemente exagerado — o lado lesionado pode ter valor
→ "Narrativa de momento": time em sequência de 5 vitórias recebe odds injustificadamente baixas — regressão à média é inevitável
→ "Jogo de cup trap": times fortes rotacionam em copas → handicap errado precificado para time titular
→ "Clássico emocional": odds em derbies frequentemente distorcidas pelo volume de apostas emocionais do público local

━━━ INTELIGÊNCIA AO VIVO ━━━
Ao vivo é onde experiência real cria alpha. Leia em tempo real:
• Pressão territorial sustentada (5+ min dominando posse + área) = gol estatisticamente iminente
• Time com 1 a menos defensivamente compacto = MENOS gols totais (contradiz intuição pública)
• Substituição de meia por segundo striker em time perdendo = busca de empate/virada
• Substituição de atacante por defensor = time segurando resultado — placar não muda
• Goleiro em escanteios min 85+ = time desesperado — gol contra provável (BTTS ou Over)

REGRAS MATEMÁTICAS ABSOLUTAS (inquebráveis):
— Under 0.5 → IMPOSSÍVEL se há ≥1 gol
— Under 1.5 → IMPOSSÍVEL se há ≥2 gols
— Under 2.5 → IMPOSSÍVEL se há ≥3 gols; IMPROVÁVEL se há 2 gols e >30min restantes
— Under 3.5 → IMPOSSÍVEL se há ≥4 gols
— BTTS Não → IMPOSSÍVEL se ambos já marcaram
— BTTS Sim → IMPROVÁVEL se time com 0 gols está no minuto ≥80 e adversário defende
— Vitória do time perdendo por 2+ → IMPROVÁVEL após minuto 75
— DESCARTE qualquer entrada matematicamente impossível dado placar atual

━━━ HIERARQUIA DE MERCADOS POR EFICIÊNCIA ━━━
Mais edge disponível → Menos edge disponível:
1º Tempo (menos líquido, mais exploração) > Handicap Asiático ligas secundárias > BTTS ligas menores > Over/Under ligas secundárias > Handicap europeu > Over/Under top 5 ligas > 1X2 qualquer liga

━━━ GESTÃO DE CAPITAL (KELLY FRACIONADO 25%) ━━━
• Stake 1%: EV 2-4%, 1-2 ângulos confirmando, mercado de alta eficiência
• Stake 2%: EV 4-7%, 3 ângulos, confiança ≥65%
• Stake 3%: EV 7-11%, 4+ ângulos, mercado validado, confiança ≥75%
• Stake 4%: EV 11-15%, condições excepcionais, 5+ ângulos
• Stake 5%: raridade absoluta — múltiplos fatores únicos alinhados
Exposição máxima simultânea: 10% da banca. Após 3 perdas seguidas: reduza 50% por 24h.

━━━ REGRAS ABSOLUTAS (INEGOCIÁVEIS) ━━━
1. Use APENAS jogos da lista com IDs e nomes EXATOS fornecidos
2. Nunca prometa lucro garantido ou all-in
3. Priorize EV real sobre narrativa emocional
4. Máximo 5 entradas por análise — priorize qualidade, mas SEMPRE analise os jogos fornecidos
5. NUNCA retorne matches vazio se há jogos na lista — se edge for marginal, use stake 1% e riskLevel "alto". Matches vazio = app inútil. Analise e ranqueie SEMPRE.

━━━ FORMATO DE RESPOSTA ━━━
JSON puro, sem markdown, sem texto fora do JSON.

Cada match dentro do array "matches":
{
  "id": "ID_NUMERICO_EXATO",
  "homeTeam": "Nome exato da lista",
  "awayTeam": "Nome exato da lista",
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
  "reasoning": "Análise multi-camada do jogo...",
  "edge": "Por que o mercado está mal-precificando essa probabilidade...",
  "entryTiming": "pré-jogo",
  "exitCondition": "Cashout se sair gol fora ou odds chegarem a 1.40",
  "mainRisk": "Fator principal de invalidação",
  "anglesCount": 3,
  "layerInsights": {
    "statistical": "Leitura estatística em 1 frase",
    "tactical": "Leitura tática em 1 frase",
    "market": "Leitura de mercado em 1 frase",
    "context": "Contexto invisível em 1 frase",
    "metaCheck": "Resultado da autocrítica — por que ainda entro apesar dos riscos"
  },
  "opportunities": [{"market": "Over 2.5", "selection": "Over", "odds": 1.85}]
}

VALORES TÉCNICOS:
- consistencyScore: inteiro 0-100 (NUNCA decimal)
- ev: número 1.0-15.0 (%)
- stake: inteiro 1-5
- probability: inteiro 40-85
- confidence: inteiro 50-90
- odds: número 1.30-4.00
- xgHome/xgAway: número 0.5-3.5
- suspiciousMovement: true APENAS se odds caíram >15% sem justificativa estatística
- riskLevel: "baixo" se score≥70 | "médio" se ≥55 | "alto" se <55

Resposta completa:
{"type":"analysis","matches":[...],"dailySummary":"2-3 frases contextuais sobre o dia de trading — volume, qualidade, exposição recomendada","marketAlert":null}

Priorize PRÉ-LIVE. Ao vivo: só mercados possíveis dado placar atual e minuto.
OBRIGATÓRIO: Se há jogos na lista, SEMPRE retorne análise. Edge marginal = stake 1% + riskLevel "alto". Nunca retorne matches vazio com jogos disponíveis."""


CHAT_SYSTEM_PROMPT = """Você é APEX TRADE — operador institucional de trading esportivo com 27 anos de experiência real. Opera capital próprio e de fundos privados em futebol europeu e sul-americano desde 1998.

Você conversa como mentor de trading de elite: direto, sem rodeios, baseado em experiência e probabilidade real.
• Compartilha conhecimento genuíno de mercado — não teoria de livro
• Alerta sobre armadilhas que destroem apostadores não sofisticados
• Distingue claramente entre trade profissional e jogo emocional
• Explica bankroll management com a seriedade que merece (onde 90% quebram)
• Quando analisa jogos específicos, usa framework de EV, CLV e probabilidade
• Admite incerteza com clareza — não força análise onde não tem dados suficientes
• Detecta perguntas emocionais disfarçadas de analíticas e responde à emoção, não à superfície

Responda em português, conversacional mas substantivo. Sem floreios, sem promessas. Se não tem dados suficientes, diz claramente.
Resposta SEMPRE com JSON puro: {"type":"chat","message":"..."}"""


FALLBACK_SYSTEM_PROMPT = """Você é APEX TRADE, operador institucional de trading esportivo. Use seu conhecimento profundo de futebol para analisar os jogos.

PROCESSO OBRIGATÓRIO para cada jogo:
1. Estime probabilidade real com base em forma, H2H e contexto da liga
2. Calcule EV = (prob/100 × odds_estimadas - 1) × 100
3. Selecione apenas onde EV > 3% e há contexto claro de valor
4. Rejeite jogos sem edge identificável — retornar menos é melhor que inventar edge

REGRAS:
- Use APENAS jogos da lista com IDs numéricos exatos (só o número)
- Gere valores REAIS baseados na análise — nunca copie exemplos
- Máximo 5 entradas. SEMPRE retorne análise se há jogos — edge marginal = stake 1% riskLevel alto

CAMPOS OBRIGATÓRIOS por jogo:
id, homeTeam, awayTeam, league, time, status, score, elapsed,
market, selection, odds(1.30-4.00), probability(40-85), ev(1.0-15.0),
confidence(50-90), stake(1-5), consistencyScore(0-100), riskLevel,
suspiciousMovement, xgHome, xgAway, reasoning, edge,
entryTiming, exitCondition, mainRisk, anglesCount,
opportunities:[{market, selection, odds}]

JSON puro: {"type":"analysis","matches":[...],"dailySummary":"...","marketAlert":null}"""

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
    """Transforma resposta da API-Football em lista de fixtures filtrados.
    O parâmetro timezone=America/Sao_Paulo garante que o date já vem em BRT.
    """
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
            dt       = datetime.fromisoformat(fixture_date.replace("Z", "+00:00"))
            time_str = dt.strftime("%H:%M")
            date_str = dt.strftime("%Y-%m-%d")
        except Exception:
            time_str = ""
            date_str = ""
        home_score = f.get("goals", {}).get("home")
        away_score = f.get("goals", {}).get("away")
        score = f"{home_score}-{away_score}" if home_score is not None else "-"
        fixtures.append({
            "id":        str(f.get("fixture", {}).get("id", "")),
            "home":      f.get("teams", {}).get("home", {}).get("name", ""),
            "away":      f.get("teams", {}).get("away", {}).get("name", ""),
            "league":    f.get("league", {}).get("name", ""),
            "country":   f.get("league", {}).get("country", ""),
            "time":      time_str,
            "date":      date_str,
            "status":    status_short,
            "score":     score,
            "elapsed":   f.get("fixture", {}).get("status", {}).get("elapsed") or 0,
            "league_id": league_id,
            "source":    "api-football",
        })
    return fixtures[:60]


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
            "date":      date_str,
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
    return result[:60]


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
            utc_dt    = datetime.strptime(raw_date[:16], "%Y-%m-%dT%H:%M")
            brt_evt   = utc_dt - timedelta(hours=3)
            time_str  = brt_evt.strftime("%H:%M")
            ev_date   = brt_evt.strftime("%Y-%m-%d")
        except Exception:
            time_str = ""
            ev_date  = ""

        # Nome da liga real (ESPN retorna no objeto leagues da resposta)
        real_league = ev.get("_league", league_name)

        return {
            "id":        f"espn_{ev.get('id', '')}",
            "home":      home_team,
            "away":      away_team,
            "league":    real_league,
            "country":   country,
            "time":      time_str,
            "date":      ev_date,
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
        with ThreadPoolExecutor(max_workers=12) as pool:
            futures = [
                pool.submit(fetch_league, slug, name, country)
                for slug, name, country in ESPN_LEAGUE_SLUGS
            ]
            # as_completed pode lançar TimeoutError — precisa estar no try externo
            for fut in as_completed(futures, timeout=22):
                try:
                    all_fixtures.extend(fut.result())
                except Exception:
                    pass
    except Exception:
        pass  # TimeoutError ou qualquer falha no pool

    all_fixtures.sort(key=lambda f: f.get("time", ""))
    return all_fixtures[:60]


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
            brt_ev   = utc_dt - timedelta(hours=3)
            time_str = brt_ev.strftime("%H:%M")
            ss_date  = brt_ev.strftime("%Y-%m-%d")
        except Exception:
            time_str = ""
            ss_date  = ""

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
            "date":      ss_date,
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
    return result[:60]


def _parse_fd_matches(matches: list) -> list:
    fixtures = []
    for m in matches:
        status_str = m.get("status", "SCHEDULED")
        status     = _FD_STATUS.get(status_str, "NS")
        if status in _FD_SKIP:
            continue

        elapsed = 45 if status == "HT" else 0

        utc_str = m.get("utcDate", "")
        try:
            utc_dt   = datetime.strptime(utc_str[:16], "%Y-%m-%dT%H:%M")
            brt_dt   = utc_dt - timedelta(hours=3)
            time_str = brt_dt.strftime("%H:%M")
            date_str = brt_dt.strftime("%Y-%m-%d")
        except Exception:
            time_str = ""
            date_str = ""

        home = (m.get("homeTeam") or {}).get("name", "") or \
               (m.get("homeTeam") or {}).get("shortName", "")
        away = (m.get("awayTeam") or {}).get("name", "") or \
               (m.get("awayTeam") or {}).get("shortName", "")
        if not home or not away:
            continue

        ft    = (m.get("score") or {}).get("fullTime") or {}
        hs    = ft.get("home")
        as_   = ft.get("away")
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
            "date":      date_str,
            "status":    status,
            "score":     score,
            "elapsed":   elapsed,
            "league_id": 0,
            "source":    "football-data",
        })
    fixtures.sort(key=lambda f: f.get("time", ""))
    return fixtures


def _fd_fetch_week(date_from: str, date_to: str, competitions: str | None = None) -> dict:
    """Chama /matches da football-data.org e retorna dict com 'raw', 'http', 'error'."""
    params: dict = {"dateFrom": date_from, "dateTo": date_to}
    if competitions:
        params["competitions"] = competitions
    r = requests.get(
        f"{FOOTBALL_DATA_BASE}/matches",
        headers={"X-Auth-Token": FOOTBALL_DATA_KEY},
        params=params,
        timeout=15,
    )
    if r.status_code != 200:
        return {"raw": [], "http": r.status_code, "error": r.text[:300]}
    body = r.json()
    return {"raw": body.get("matches", []), "http": 200}


def get_fixtures_from_football_data(date_str: str) -> list:
    """
    football-data.org — gratuita, sem limite diário, projetada para acesso
    de servidor. Requer FOOTBALL_DATA_KEY no ambiente.
    Busca a semana inteira em 1 chamada; fallback sem filtro de competições.
    """
    if not FOOTBALL_DATA_KEY:
        _api_diag["football_data"] = {"ok": False, "error": "KEY_NOT_SET"}
        return []

    base_dt  = datetime.strptime(date_str, "%Y-%m-%d")
    date_to  = (base_dt + timedelta(days=7)).strftime("%Y-%m-%d")

    def _pick_first_day(raw: list) -> list:
        """Agrupa por data BRT e retorna fixtures do primeiro dia com jogos."""
        by_date: dict = {}
        for m in raw:
            utc_str = m.get("utcDate", "")
            if utc_str:
                try:
                    brt_day = (datetime.strptime(utc_str[:16], "%Y-%m-%dT%H:%M")
                               - timedelta(hours=3)).strftime("%Y-%m-%d")
                except Exception:
                    brt_day = utc_str[:10]
                by_date.setdefault(brt_day, []).append(m)
        for offset in range(8):
            day = (base_dt + timedelta(days=offset)).strftime("%Y-%m-%d")
            fixtures = _parse_fd_matches(by_date.get(day, []))
            if fixtures:
                return fixtures
        return []

    diag: dict = {"date_from": date_str, "date_to": date_to, "ok": False}
    try:
        # Tentativa 1: com filtro de competições
        result = _fd_fetch_week(date_str, date_to, _FD_COMPETITIONS)
        diag["http"]      = result["http"]
        diag["with_comp"] = True
        if result["http"] == 429:
            diag["error"] = "RATE_LIMITED_10rpm"
            _api_diag["football_data"] = diag
            return []
        if result["http"] == 200:
            raw = result["raw"]
            diag["total_raw_comp"] = len(raw)
            fixtures = _pick_first_day(raw)
            if fixtures:
                diag["ok"] = True
                diag["total_parsed"] = len(fixtures)
                diag["competitions"] = list({m.get("competition", {}).get("name", "") for m in raw})
                _api_diag["football_data"] = diag
                return fixtures[:60]

        # Tentativa 2: sem filtro (retorna tudo acessível no plano)
        result2 = _fd_fetch_week(date_str, date_to, None)
        diag["http2"]      = result2["http"]
        diag["with_comp2"] = False
        if result2["http"] == 429:
            diag["error"] = "RATE_LIMITED_10rpm"
            _api_diag["football_data"] = diag
            return []
        if result2["http"] == 200:
            raw2 = result2["raw"]
            diag["total_raw_nocomp"] = len(raw2)
            fixtures2 = _pick_first_day(raw2)
            if fixtures2:
                diag["ok"] = True
                diag["total_parsed"] = len(fixtures2)
                diag["competitions"] = list({m.get("competition", {}).get("name", "") for m in raw2})
                _api_diag["football_data"] = diag
                return fixtures2[:60]

        # Nenhuma tentativa encontrou jogos
        diag["error"] = (
            result.get("error") or result2.get("error") or "NO_MATCHES_7_DAYS"
        )
        _api_diag["football_data"] = diag
        return []

    except Exception as e:
        _api_diag["football_data"] = {"ok": False, "error": str(e)}
        return []


def _filter_past_fixtures(fixtures: list) -> list:
    """
    Remove fixtures NS cujo kickoff já passou há mais de 30 min.
    Usa o campo 'date' do fixture (se disponível) para evitar confundir
    jogos de amanhã com jogos de hoje que já passaram.
    """
    now_brt   = datetime.utcnow() - timedelta(hours=3)
    today_brt = now_brt.strftime("%Y-%m-%d")
    result = []
    for f in fixtures:
        if f.get("status") not in ("NS", ""):
            result.append(f)
            continue
        time_str = f.get("time", "")
        if not time_str:
            result.append(f)
            continue
        fixture_date = f.get("date") or today_brt
        # Jogo de data futura: sempre manter
        if fixture_date > today_brt:
            result.append(f)
            continue
        try:
            kickoff = datetime.strptime(f"{fixture_date} {time_str}", "%Y-%m-%d %H:%M")
            if (now_brt - kickoff).total_seconds() > 30 * 60:
                continue  # kickoff passou há mais de 30 min com status desatualizado
        except Exception:
            pass
        result.append(f)
    return result


@app.route("/fixtures/today")
def fixtures_today():
    try:
        today = (datetime.utcnow() - timedelta(hours=3)).strftime("%Y-%m-%d")  # data BRT
        now   = time.time()
        c     = _fixtures_cache

        def _serve(fixtures: list, source: str, cached: bool = False) -> object:
            filtered = _filter_past_fixtures(fixtures)
            c["data"] = fixtures; c["ts"] = now; c["date"] = today
            resp = {"success": True, "count": len(filtered),
                    "fixtures": filtered, "date": today, "source": source}
            if cached:
                resp["cached"] = True
            return jsonify(resp)

        def _has_valid(fixtures: list) -> bool:
            """True se ainda há jogos válidos após filtro."""
            return bool(_filter_past_fixtures(fixtures))

        # ── 1. Cache em memória — só serve se ainda há jogos válidos ──────────
        if c["data"] is not None and c["date"] == today and (now - c["ts"]) < _FIXTURES_TTL:
            if _has_valid(c["data"]):
                return _serve(c["data"], "memory-cache", cached=True)
            # Jogos do cache já terminaram — invalida e busca dados frescos

        # ── 2. Cache em arquivo — só serve se ainda há jogos válidos ──────────
        file_fixtures = _read_file_cache(today)
        if file_fixtures and _has_valid(file_fixtures):
            return _serve(file_fixtures, "file-cache", cached=True)

        # ── 3. API-Football (primária — melhor cobertura, 100 req/dia) ─────────
        def _fetch_apifootball(date: str):
            try:
                r = requests.get(
                    f"{API_BASE}/fixtures",
                    headers=API_HEADERS,
                    params={"date": date, "timezone": "America/Sao_Paulo"},
                    timeout=15,
                )
                if r.status_code == 200 and not r.json().get("errors"):
                    return r.json().get("response", []), None
                return None, r.json().get("errors") or r.status_code
            except Exception as e:
                return None, str(e)

        raw_today, af_err = _fetch_apifootball(today)

        if raw_today is not None:
            fixtures_today_raw = _parse_fixtures(raw_today)
            filtered_today     = _filter_past_fixtures(fixtures_today_raw)
            _api_diag["api_football"] = {
                "ok": True, "http": 200,
                "total": len(raw_today), "parsed": len(fixtures_today_raw),
                "after_filter": len(filtered_today),
            }

            if filtered_today:
                # Há jogos hoje — servir normalmente
                _write_file_cache(today, fixtures_today_raw)
                return _serve(fixtures_today_raw, "api-football")

            # Hoje esvaziou (jogos terminaram) → buscar amanhã automaticamente
            tomorrow = (datetime.utcnow() - timedelta(hours=3) + timedelta(days=1)).strftime("%Y-%m-%d")
            raw_tmrw, _ = _fetch_apifootball(tomorrow)
            if raw_tmrw is not None:
                fixtures_tmrw = _parse_fixtures(raw_tmrw)
                if fixtures_tmrw:
                    _api_diag["api_football"]["tomorrow"] = {"total": len(raw_tmrw), "parsed": len(fixtures_tmrw)}
                    _write_file_cache(today, fixtures_tmrw)
                    return _serve(fixtures_tmrw, "api-football-tomorrow")

        # Registra falha da API-Football
        _api_diag["api_football"] = {"ok": False, "error": str(af_err)}

        # ── 4. football-data.org (backup — sem limite diário) ─────────────────
        if FOOTBALL_DATA_KEY:
            fd = get_fixtures_from_football_data(today)
            if fd and _has_valid(fd):
                _write_file_cache(today, fd)
                return _serve(fd, "football-data")

        # ── 5. Cache antigo (stale) ────────────────────────────────────────────
        if c["data"] is not None:
            return _serve(c["data"], "stale-cache", cached=True)

        # ── 6. Sem dados — retorna diagnóstico claro ───────────────────────────
        af_diag = _api_diag.get("api_football", {})
        fd_diag = _api_diag.get("football_data", {})
        if af_diag.get("ok") is False:
            err_detail = af_diag.get("error", "")
            if "429" in str(err_detail) or "rateLimit" in str(err_detail).lower():
                msg = ("Cota da API-Football atingida (100 req/dia). "
                       "Configure FOOTBALL_DATA_KEY no Render como backup, "
                       "ou aguarde meia-noite para resetar a cota.")
            else:
                msg = f"API-Football falhou: {err_detail}. Backup football-data.org: {fd_diag.get('error','sem key')}"
        else:
            msg = "Nenhuma fonte retornou jogos. Verifique /fixtures/debug."
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

        # Cap inteligente para controlar tokens no Groq: live têm prioridade total,
        # pré-jogo limitado a completar 25 slots. Preserva qualidade da análise
        # e evita estourar o limite de 6k TPM do free tier.
        _MAX_ANALYZE = 25
        live_fixtures    = [f for f in fixtures if f.get("status") in ["1H", "2H", "HT", "ET", "LIVE"]]
        prelive_fixtures = [f for f in fixtures if f.get("status") not in ["1H", "2H", "HT", "ET", "LIVE"]]
        prelive_fixtures.sort(key=lambda f: f.get("time", ""))
        prelive_cap      = max(0, _MAX_ANALYZE - len(live_fixtures))
        prelive_fixtures = prelive_fixtures[:prelive_cap]
        fixtures         = live_fixtures + prelive_fixtures

        # ── Busca dados em tempo real (não bloqueia se falhar) ──────────────
        unique_league_ids = list({f.get("league_id") for f in fixtures if f.get("league_id")})
        # Standings e live stats desabilitados — a API-Football tem apenas 100 req/dia
        # e o budget precisa ser preservado para o /fixtures/today (1 req/4min).
        # O AI usa seu conhecimento interno para estimar forma e probabilidades.
        standings_ctx = ""
        live_ctx      = ""
        # ────────────────────────────────────────────────────────────────────

        # Contexto temporal — dia da semana e hora afetam análise
        now_brt    = datetime.utcnow() - timedelta(hours=3)
        today_brt  = now_brt.strftime("%Y-%m-%d")
        weekday_pt = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
        day_label  = weekday_pt[now_brt.weekday()]
        time_label = now_brt.strftime("%H:%M")
        date_label = now_brt.strftime("%d/%m/%Y")

        def format_fixture(f):
            fixture_date = f.get("date", "")
            is_tomorrow  = fixture_date and fixture_date != today_brt
            date_tag     = " [AMANHÃ]" if is_tomorrow else ""
            line = (f"- ID:{f['id']} | {f['home']} x {f['away']} | "
                    f"{f['league']} ({f['country']}) | {f['time']}{date_tag} | Status:{f['status']}")
            if f.get("status") in ["1H", "2H", "HT", "ET", "LIVE"]:
                line += f" | Placar:{f['score']} | Min:{f.get('elapsed', 0)}"
            return line

        prelive_list = "\n".join([format_fixture(f) for f in prelive_fixtures]) or "Nenhum"
        live_list    = "\n".join([format_fixture(f) for f in live_fixtures]) or "Nenhum"

        has_live     = bool(live_fixtures)
        has_prelive  = bool(prelive_fixtures)
        total_games  = len(fixtures)

        prompt = f"""━━━ BRIEFING OPERACIONAL ━━━
Data: {day_label}, {date_label} | Hora BRT: {time_label}
Total de jogos disponíveis: {total_games} | Perfil do operador: {risk_mode.upper()}

━━━ JOGOS PRÉ-JOGO ({len(prelive_fixtures)}) ━━━
{prelive_list}

━━━ JOGOS AO VIVO ({len(live_fixtures)}) ━━━
{live_list}

━━━ PROTOCOLO DE ANÁLISE OBRIGATÓRIO ━━━
Para CADA jogo, processe internamente as 5 camadas cognitivas:

C1-ESTATÍSTICA: Use seu conhecimento de forma recente, xG, médias de gols, H2H desta liga neste contexto.
C2-TÁTICA: Qual o perfil tático de cada time? Como se encaixam? Há desgaste físico?
C3-MERCADO: Em que mercado específico o edge existe? O mercado já precificou ou há atraso?
C4-CONTEXTO: Qual a motivação real de cada time hoje? Há pressão psicológica invisível?
C5-META: Este edge é real ou estou sendo atraído por narrativa? O risco oculto justifica?

━━━ FILTROS ANTI-EDGE FALSO ━━━
REJEITE se: mercado já corrigiu | motivação assimétrica desfavorável | estatística sem suporte tático | odd aparentemente boa mas com armadilha contextual | jogo "morto" para um dos lados.

━━━ PRIORIDADES DE SELEÇÃO ━━━
1. Jogos ao vivo com pressão óbvia e unilateral identificada
2. Pré-jogo com edge confirmado em múltiplas camadas
3. Mercados de menor eficiência (1º tempo, handicap asiático, BTTS em ligas secundárias)
4. Máximo 5 entradas — MÍNIMO 1 entrada obrigatória se há jogos na lista

⚠️ REGRA CRÍTICA: SEMPRE retorne pelo menos 1 match analisado quando a lista não está vazia.
Se edge for fraco: stake=1, riskLevel="alto", confidence=50, ev=2.0 — mas ANALISE e RETORNE.
Retornar matches vazio com jogos disponíveis é falha operacional, não prudência.

━━━ CONTEXTO DO DIA ━━━
Dia: {day_label}. {"Segunda/terça: menos jogos de elite, mais edge em ligas secundárias." if now_brt.weekday() <= 1 else "Quarta/quinta: tipicamente CL/EL — mercados altamente eficientes, edge raro." if now_brt.weekday() <= 3 else "Final de semana: maior volume, mais ação sharp, seja criterioso."}
{"ATENÇÃO: Jogos marcados como [AMANHÃ] — analise como pré-jogo com mais tempo para mercado se mover." if any(f.get("date", "") != today_brt for f in fixtures) else ""}

━━━ INSTRUÇÃO FINAL ━━━
Use APENAS IDs e nomes EXATOS da lista acima.
Para ao vivo: aplique regras matemáticas absolutas de impossibilidade por placar.
dailySummary: contextualize o dia (quantidade, qualidade, exposição total recomendada).
marketAlert: alerta se detectar movimento suspeito ou oportunidade urgente (null caso contrário).

JSON puro, sem markdown. Tipo "analysis"."""

        messages = history[-4:] + [{"role": "user", "content": prompt}]
        raw = call_groq(messages, max_tokens=4000, model=GROQ_MODEL_ANALYSIS, temperature=0.25)
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

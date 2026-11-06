"""Rendimiento del clan: guerras, ligas, miembros y KPIs con la API pública de ClashKing (sin clave).

sync() guarda en clan.db todo lo que encuentra, así que el histórico crece aunque ClashKing lo pierda.
La lanza cada día el cron de Vercel, o la tarea de Windows (clan_sync.py) en el PC. El botón de recoger
la lanza al momento; en el PC, con el panel abierto, hay además una versión ligera cada 30 min.
Las consultas del panel sólo leen clan.db. Dónde está ese archivo lo decide almacen.py.

ClashKing no da la lista de miembros, así que hay dos modos:
- Con clave de la API oficial: lista exacta; altas y bajas automáticas aunque no jueguen guerras.
- Sin clave: se deduce de quién juega guerras; quien no juega no aparece.
La clave va por el proxy de RoyaleAPI (IP fija), así sirve desde cualquier sitio y no caduca si cambia
la IP. Se lee de COC_API_KEY o de clan.json.
"""
import hashlib
import hmac
import json
import os
import re
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import httpx

import almacen

ACCOUNTS = Path(__file__).parent.parent / "asistente" / "config.json"
API = os.environ.get("CLASHKING_API", "https://api.clashk.ing")
OFFICIAL = os.environ.get("COC_API_BASE", "https://cocproxy.royaleapi.dev/v1")
PROXY_IP = "45.79.218.79"     # la que hay que poner al crear la clave
HEADERS = {"User-Agent": "coc-asistente"}
TAG_RE = re.compile(r"^#[0289PYLQGRJCUV]{3,12}$")
GROUP_ID_RE = re.compile(r"^[a-z0-9]{1,16}$")
ROSTER_DAYS = 180     # quien jugó con el clan en estos días cuenta como miembro
LIGHT_S = 1800        # con el panel abierto, refresco ligero cada 30 min
MIN_ATTACKS = 3       # con menos ataques posibles se marca «Pocos datos»
DAILY_HOUR, DAILY_MINUTE = 11, 1

# Sistema de KPIs. Nota 0–100: lineal entre `floor` (0) y `target` (100). Si un KPI no se puede medir,
# su peso se reparte entre los demás en vez de penalizar.
KPIS = [
    {"id": "participacion", "name": "Participación", "unit": "%", "weight": 25, "floor": 50, "target": 100,
     "help": "Ataques usados de los disponibles"},
    {"id": "estrellas", "name": "Estrellas por ataque", "unit": "★", "weight": 25, "floor": 1, "target": 2.6,
     "help": "Media por ataque disponible: un ataque sin usar cuenta 0"},
    {"id": "triples", "name": "Triples", "unit": "%", "weight": 15, "floor": 10, "target": 70,
     "help": "Ataques de 3 estrellas sobre los usados"},
    {"id": "dano", "name": "Daño medio", "unit": "%", "weight": 10, "floor": 50, "target": 95,
     "help": "Destrucción media de sus ataques"},
    {"id": "exigencia", "name": "Contra TH igual o mayor", "unit": "★", "weight": 10, "floor": 1, "target": 2.4,
     "help": "Estrellas medias contra rivales de su TH o superior"},
    {"id": "defensa", "name": "Estrellas cedidas", "unit": "★", "weight": 10, "floor": 3, "target": 1.5,
     "help": "Media que le sacan por defensa (menos es mejor)"},
    {"id": "constancia", "name": "Guerras completas", "unit": "%", "weight": 5, "floor": 40, "target": 100,
     "help": "Guerras en las que usó todos sus ataques"},
]
LEVELS = [(85, "Élite", "elite"), (70, "Sólido", "solido"), (50, "Irregular", "irregular"), (0, "En riesgo", "riesgo")]

SCHEMA = """
CREATE TABLE IF NOT EXISTS players(tag TEXT PRIMARY KEY, name TEXT, th INT, roster INT DEFAULT 0, timers TEXT, timers_ts INT);
CREATE TABLE IF NOT EXISTS wars(end_ts INT, clan_tag TEXT, start_ts INT, kind TEXT, opponent TEXT, opponent_tag TEXT, size INT, per INT,
  stars INT, opp_stars INT, pct REAL, opp_pct REAL, result TEXT, PRIMARY KEY(end_ts, clan_tag));
CREATE TABLE IF NOT EXISTS plays(player TEXT, end_ts INT, clan_tag TEXT, clan_name TEXT, kind TEXT, per INT, size INT, opponent TEXT,
  th INT, pos INT, result TEXT, PRIMARY KEY(player, end_ts));
CREATE TABLE IF NOT EXISTS hits(player TEXT, end_ts INT, side TEXT, ord INT, stars INT, pct REAL, duration INT, fresh INT,
  enemy TEXT, enemy_th INT, enemy_pos INT, PRIMARY KEY(player, end_ts, side, ord));
CREATE TABLE IF NOT EXISTS seasons(clan_tag TEXT, season TEXT, league TEXT, state TEXT, rank INT, stars INT, destruction REAL, size INT,
  won INT, lost INT, tied INT, PRIMARY KEY(clan_tag, season));
CREATE TABLE IF NOT EXISTS player_seasons(player TEXT, season TEXT, clan_name TEXT, league TEXT, won INT, lost INT, tied INT, th INT,
  attacks INT, stars INT, PRIMARY KEY(player, season));
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS moves(ts INT, tag TEXT, name TEXT, kind TEXT);
CREATE INDEX IF NOT EXISTS plays_end ON plays(end_ts);
"""
_running = threading.Lock()


# ---------------- ajustes ----------------
settings = almacen.leer_ajustes
_save = almacen.guardar_ajustes


def clean_tag(tag):
    tag = str(tag or "").strip().upper().replace("O", "0")
    if tag and not tag.startswith("#"):
        tag = "#" + tag
    if not TAG_RE.match(tag):
        raise ValueError(f"Tag no válido: {tag or '(vacío)'}. Empieza por # y sale en el perfil del juego.")
    return tag


def enc(tag):
    return quote(tag, safe="")


def save_tag(tag):
    tag = clean_tag(tag)
    if not ((get(f"/v2/clan/{enc(tag)}/wars?limit=1") or {}).get("items")
            or (get(f"/v2/cwl/{enc(tag)}/seasons?limit=1") or {}).get("items")):
        raise ValueError(f"ClashKing no tiene guerras del clan {tag}. Revisa que sea el tag del clan, no el de tu perfil.")
    _save({**settings(), "clan_tag": tag})
    start_sync()


def api_key():
    return settings().get("api_key") or os.environ.get("COC_API_KEY")


def official(path, key=None):
    """API oficial de Supercell. Sus errores se explican para poder arreglarlos desde el panel."""
    try:
        r = httpx.get(OFFICIAL + path, headers={"Authorization": f"Bearer {key or api_key()}", **HEADERS}, timeout=30)
    except httpx.HTTPError as e:
        raise RuntimeError("Sin conexión con la API oficial.") from e
    if r.status_code == 200:
        return r.json()
    try:
        reason = r.json().get("reason", "")
    except ValueError:
        reason = ""
    if reason == "accessDenied.invalidIp":
        raise RuntimeError(f"La clave no admite esta conexión: al crearla, la IP debe ser {PROXY_IP}.")
    if r.status_code == 403:
        raise RuntimeError("Supercell rechaza la clave. Revisa que esté bien copiada y que siga activa.")
    if r.status_code == 503:
        raise RuntimeError("El juego está en mantenimiento; se reintenta en la próxima recogida.")
    raise RuntimeError(f"La API oficial respondió {r.status_code}.")


def save_key(key):
    key = str(key or "").strip()
    if len(key) < 40:
        raise ValueError("Eso no es una clave de desarrollador: el «Token de API» del juego no sirve. "
                         "Crea la clave en developer.clashofclans.com; es un texto largo que empieza por eyJ.")
    s = settings()
    if not s.get("clan_tag"):
        raise ValueError("Primero hace falta el tag del clan.")
    try:
        official(f"/clans/{enc(s['clan_tag'])}", key)
    except RuntimeError as e:
        raise ValueError(str(e)) from e
    _save({**s, "api_key": key})
    start_sync()


# ---------------- administración ----------------
# Sin configurar, entra admin/admin. Al cambiarla sólo se guarda un hash, nunca la contraseña.
def _hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000).hex()


def check_admin(user, password):
    cfg = settings().get("admin")
    if not cfg:
        return hmac.compare_digest(user.encode(), b"admin") and hmac.compare_digest(password.encode(), b"admin")
    return hmac.compare_digest(user.encode(), cfg["user"].encode()) and hmac.compare_digest(_hash(password, cfg["salt"]), cfg["hash"])


def set_admin(user, password):
    user, password = str(user or "").strip(), str(password or "")
    if not user or ":" in user:
        raise ValueError("Usuario no válido.")
    if len(password) < 8:
        raise ValueError("La contraseña necesita al menos 8 caracteres.")
    salt = os.urandom(16).hex()
    _save({**settings(), "admin": {"user": user, "salt": salt, "hash": _hash(password, salt)}})


def admin_info():
    c = db()
    try:
        cfg = settings().get("admin")
        return {**meta_info(c), "user": cfg["user"] if cfg else "admin", "default": not cfg, "log": meta_get(c, "sync_log", [])[:8],
                "members": c.execute("SELECT COUNT(*) n FROM players WHERE roster=1").fetchone()["n"]}
    finally:
        c.close()


# ---------------- API ----------------
def get(path):
    """JSON de la API; None si no existe (404). Otro fallo se explica en el panel."""
    try:
        r = httpx.get(API + path, headers=HEADERS, timeout=30)
    except httpx.HTTPError as e:
        raise RuntimeError("Sin conexión con ClashKing.") from e
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        raise RuntimeError(f"ClashKing respondió {r.status_code}.")
    return r.json()


def api_ts(s):
    """'20261104T120000.000Z' → epoch."""
    try:
        return int(datetime.strptime(s[:15], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc).timestamp())
    except (TypeError, ValueError):
        return 0


def norm_name(n):
    """I y l se confunden en el juego («TheRIvan11») y los nombres llevan adornos («ARDHIAMATEUR♤»)."""
    return re.sub(r"[^a-z0-9]", "", str(n or "").lower().replace("l", "i"))


def own_names():
    saved = settings().get("own_names")    # en la nube no está la configuración del asistente
    if saved is not None:
        return set(saved)
    try:
        acc = json.loads(ACCOUNTS.read_text(encoding="utf-8")).get("accounts", {})
    except (OSError, ValueError):
        return set()
    return {norm_name(a.get("village_name", n)) for n, a in acc.items()}


# ---------------- base de datos ----------------
def db():
    c = sqlite3.connect(almacen.ruta_db(), timeout=30)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c


def meta_get(c, k, default=None):
    r = c.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return json.loads(r["v"]) if r else default


def meta_set(c, k, v):
    c.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (k, json.dumps(v, ensure_ascii=False)))


def put(c, table, row):
    cols = ",".join(row)
    c.execute(f"INSERT OR REPLACE INTO {table}({cols}) VALUES({','.join('?' * len(row))})", tuple(row.values()))


def result_of(a, b):
    return "win" if a > b else "lose" if a < b else "tie"


# ---------------- recogida ----------------
def store_clan_war(c, w, tag, kind):
    """Guerra del clan completa: alineación, ataques y defensas (el rival trae los ataques a los nuestros)."""
    if w.get("state") != "warEnded":
        return []
    us, them = w.get("clan") or {}, w.get("opponent") or {}
    if them.get("tag") == tag:
        us, them = them, us
    if us.get("tag") != tag:
        return []
    end = api_ts(w.get("endTime"))
    per = w.get("attacksPerMember") or (1 if kind == "cwl" else 2)
    a = (us.get("stars", 0), us.get("destructionPercentage", 0))
    b = (them.get("stars", 0), them.get("destructionPercentage", 0))
    res = result_of(a, b)
    put(c, "wars", {"end_ts": end, "clan_tag": tag, "start_ts": api_ts(w.get("startTime")), "kind": kind, "opponent": them.get("name"),
                    "opponent_tag": them.get("tag"), "size": w.get("teamSize"), "per": per, "stars": a[0], "opp_stars": b[0],
                    "pct": round(a[1], 1), "opp_pct": round(b[1], 1), "result": res})
    enemies = {m["tag"]: m for m in them.get("members", [])}
    ours = {m["tag"]: m for m in us.get("members", [])}
    for m in us.get("members", []):
        put(c, "plays", {"player": m["tag"], "end_ts": end, "clan_tag": tag, "clan_name": us.get("name"), "kind": kind, "per": per,
                         "size": w.get("teamSize"), "opponent": them.get("name"), "th": m.get("townhallLevel"),
                         "pos": m.get("mapPosition"), "result": res})
        c.execute("INSERT INTO players(tag,name,th) VALUES(?,?,?) ON CONFLICT(tag) DO UPDATE SET name=excluded.name",
                  (m["tag"], m.get("name"), m.get("townhallLevel")))
        for x in m.get("attacks", []):
            e = enemies.get(x.get("defenderTag"), {})
            put(c, "hits", {"player": m["tag"], "end_ts": end, "side": "attack", "ord": x.get("order"), "stars": x.get("stars", 0),
                            "pct": x.get("destructionPercentage", 0), "duration": x.get("duration"), "fresh": None,
                            "enemy": e.get("name"), "enemy_th": e.get("townhallLevel"), "enemy_pos": e.get("mapPosition")})
    for e in them.get("members", []):
        for x in e.get("attacks", []):
            if x.get("defenderTag") in ours:
                put(c, "hits", {"player": x["defenderTag"], "end_ts": end, "side": "defense", "ord": x.get("order"), "stars": x.get("stars", 0),
                                "pct": x.get("destructionPercentage", 0), "duration": x.get("duration"), "fresh": None,
                                "enemy": e.get("name"), "enemy_th": e.get("townhallLevel"), "enemy_pos": e.get("mapPosition")})
    return list(ours)


def store_player_war(c, tag, w):
    """Historial del jugador: también guerras con otros clanes. Trae datos que la del clan no da (fresh)."""
    end = api_ts(w.get("endTime"))
    if not end or end > time.time() or w.get("type") == "friendly":      # las amistosas no cuentan
        return
    us, them, me = w.get("clan") or {}, w.get("opponent") or {}, w.get("player") or {}
    res = result_of((us.get("stars", 0), us.get("destructionPercentage", 0)), (them.get("stars", 0), them.get("destructionPercentage", 0)))
    put(c, "plays", {"player": tag, "end_ts": end, "clan_tag": us.get("tag"), "clan_name": us.get("name"),
                     "kind": "cwl" if w.get("type") == "cwl" else "war", "per": w.get("attacksPerMember") or 1, "size": w.get("teamSize"),
                     "opponent": them.get("name"), "th": me.get("townhallLevel"), "pos": me.get("mapPosition"), "result": res})
    for side, rows in (("attack", w.get("attacks") or []), ("defense", w.get("defenses") or [])):
        for x in rows:
            e = x.get("player") or {}
            put(c, "hits", {"player": tag, "end_ts": end, "side": side, "ord": x.get("order"), "stars": x.get("stars", 0),
                            "pct": x.get("destructionPercentage", 0), "duration": x.get("duration"), "fresh": x.get("fresh"),
                            "enemy": e.get("name"), "enemy_th": e.get("townhallLevel"), "enemy_pos": e.get("mapPosition")})


def store_seasons(c, tag, items):
    for s in items:
        r = s.get("rounds") or {}
        put(c, "seasons", {"clan_tag": tag, "season": s.get("season"), "league": (s.get("warLeague") or {}).get("name"), "state": s.get("state"),
                           "rank": s.get("rank"), "stars": s.get("stars"), "destruction": s.get("destruction"), "size": s.get("warSize"),
                           "won": r.get("won"), "lost": r.get("lost"), "tied": r.get("tied")})


def store_player_seasons(c, tag, items):
    for s in items:
        clan = s.get("clan") or {}
        w = clan.get("wars") or s.get("wars") or {}
        league = clan.get("warLeague") or s.get("warLeague") or {}
        atk = s.get("attacks") or []
        put(c, "player_seasons", {"player": tag, "season": s.get("season"), "clan_name": clan.get("name"), "league": league.get("name"),
                                  "won": w.get("won"), "lost": w.get("lost"), "tied": w.get("tied"), "th": s.get("townHallLevel"),
                                  "attacks": len(atk), "stars": sum(a.get("stars", 0) for a in atk)})


def fetch_player(tag, light):
    e = enc(tag)
    out = {"tag": tag, "timers": (get(f"/v2/player/{e}/timers") or {}).get("items", [])}
    if not light:
        out["wars"] = (get(f"/v2/player/{e}/war/stats?limit=500") or {}).get("items", [])
        out["seasons"] = (get(f"/v2/player/{e}/cwl/history?limit=24") or {}).get("items", [])
    return out


def rival_names(c, data, tag):
    """La API sólo da el tag del rival de una guerra en curso: su nombre sale de sus propias guerras."""
    known = meta_get(c, "rivals", {})
    rivals = {x for d in data for t in d.get("timers", []) for x in t.get("clans", [])} - {tag} - set(known)
    for r in rivals:
        try:
            wars = (get(f"/v2/clan/{enc(r)}/wars?limit=1") or {}).get("items", [])
        except RuntimeError:
            continue
        for w in wars:
            for side in (w.get("clan") or {}, w.get("opponent") or {}):
                if side.get("tag") == r:
                    known[r] = side.get("name")
    return known


def sync(light=False, source="panel"):
    """Recoge y guarda. Devuelve False si ya había otra en marcha."""
    if not _running.acquire(blocking=False):
        return False
    c = None
    try:
        s = settings()
        tag = s.get("clan_tag")
        if not tag:
            raise RuntimeError("Falta el tag del clan.")
        c = db()
        with c:
            meta_set(c, "syncing", {"ts": time.time(), "light": light})
        wars = [(k, w) for k, t in (("cwl", "cwl"), ("war", "random"))
                for w in (get(f"/v2/clan/{enc(tag)}/wars?limit=200&type={t}") or {}).get("items", [])]
        seasons = (get(f"/v2/cwl/{enc(tag)}/seasons?limit=24") or {}).get("items", [])
        listed, official_error = None, None
        if api_key():
            try:
                listed = official(f"/clans/{enc(tag)}").get("memberList")
            except RuntimeError as e:      # sin lista oficial la recogida sigue: no se pierden las guerras
                official_error = str(e)
        with c:
            for kind, w in wars:
                store_clan_war(c, w, tag, kind)
            store_seasons(c, tag, seasons)
            since = int(time.time()) - ROSTER_DAYS * 86400
            before = {r["tag"]: r["name"] for r in c.execute("SELECT tag, name FROM players WHERE roster=1")}
            had_official = meta_get(c, "official_ts")
            if listed:
                roster = [m["tag"] for m in listed]
                for m in listed:
                    c.execute("""INSERT INTO players(tag,name,th) VALUES(?,?,?)
                                 ON CONFLICT(tag) DO UPDATE SET name=excluded.name, th=COALESCE(excluded.th, th)""",
                              (m["tag"], m.get("name"), m.get("townHallLevel")))
                meta_set(c, "official_ts", int(time.time()))
            elif had_official:             # la oficial ha fallado: mejor la última lista buena que deducirla
                roster = list(before)
            else:
                roster = [r["player"] for r in c.execute("SELECT DISTINCT player FROM plays WHERE clan_tag=? AND end_ts>=?", (tag, since))]
            # la primera lista oficial sólo fija el punto de partida: no son altas de verdad
            if before and (had_official or not listed):
                names = {r["tag"]: r["name"] for r in c.execute("SELECT tag, name FROM players")}
                now_ = int(time.time())
                c.executemany("INSERT INTO moves VALUES(?,?,?,'join')", [(now_, t, names.get(t)) for t in roster if t not in before])
                if listed:
                    c.executemany("INSERT INTO moves VALUES(?,?,?,'leave')", [(now_, t, n) for t, n in before.items() if t not in roster])
            c.execute("UPDATE players SET roster=0")
            for t in roster:
                c.execute("INSERT INTO players(tag,roster) VALUES(?,1) ON CONFLICT(tag) DO UPDATE SET roster=1", (t,))

        def safe(t):
            try:
                return fetch_player(t, light)
            except RuntimeError as e:      # un jugador que falla no tira la recogida entera
                return {"tag": t, "error": str(e)}

        with ThreadPoolExecutor(3) as ex:
            data = list(ex.map(safe, roster))
        failed = [d["tag"] for d in data if "error" in d]
        if len(failed) == len(data) and data:
            raise RuntimeError(data[0]["error"])
        now = int(time.time())
        rivals = rival_names(c, data, tag)
        with c:
            meta_set(c, "rivals", rivals)
            for d in data:
                if "error" in d:
                    continue
                c.execute("UPDATE players SET timers=?, timers_ts=? WHERE tag=?", (json.dumps(d["timers"]), now, d["tag"]))
                for w in d.get("wars", []):
                    store_player_war(c, d["tag"], w)
                    me = w.get("player") or {}
                    c.execute("UPDATE players SET name=COALESCE(?,name) WHERE tag=?", (me.get("name"), d["tag"]))
                if d.get("wars"):
                    newest = max(d["wars"], key=lambda w: api_ts(w.get("endTime")))
                    c.execute("UPDATE players SET th=? WHERE tag=?", ((newest.get("player") or {}).get("townhallLevel"), d["tag"]))
                store_player_seasons(c, d["tag"], d.get("seasons", []))
            meta_set(c, "light_ts", now)
            if not light:
                meta_set(c, "full_ts", now)
            meta_set(c, "stamp", now)
            meta_set(c, "last_error", official_error or (f"{len(failed)} jugadores sin actualizar" if failed else None))
            log = meta_get(c, "sync_log", [])
            meta_set(c, "sync_log", ([{"ts": now, "source": source, "light": light, "players": len(roster), "failed": len(failed)}] + log)[:15])
        return True
    except Exception as e:             # también lo inesperado: si no, una recogida fallida no dejaría rastro
        if c is None:
            c = db()
        with c:
            meta_set(c, "last_error", str(e) if isinstance(e, RuntimeError) else f"Error al guardar los datos: {e}")
            meta_set(c, "fail_ts", int(time.time()))
        raise RuntimeError(str(e)) from e
    finally:
        if c is not None:
            with c:
                meta_set(c, "syncing", None)
            c.close()
            almacen.publicar_db()
        _running.release()


def start_sync(light=False, source="panel"):
    def run():
        try:
            sync(light, source)
        except RuntimeError:
            pass                 # queda en last_error y el panel lo enseña
    if almacen.EN_NUBE:
        run()                    # en la nube un hilo moriría con la petición
    else:
        threading.Thread(target=run, daemon=True).start()


def daily(retries=3, wait=300):
    """Para la tarea programada: reintenta si ClashKing falla. Devuelve 0 si todo fue bien."""
    for i in range(retries):
        try:
            sync(False, "diaria")
            return 0
        except RuntimeError as e:
            print(f"{datetime.now():%Y-%m-%d %H:%M} intento {i + 1}: {e}", flush=True)
            if i + 1 < retries:
                time.sleep(wait)
    return 1


# ---------------- KPIs ----------------
def latest_season_ts(c, tag):
    r = c.execute("SELECT MAX(season) s FROM seasons WHERE clan_tag=?", (tag,)).fetchone()
    try:
        return int(datetime.strptime(r["s"][:10], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
    except (TypeError, ValueError):
        return None


def load_plays(c, tag, kind="all", days=0, scope="clan", player=None):
    """Participaciones con sus ataques y defensas, de la más antigua a la más reciente."""
    where, args = ["1=1"], []
    if scope == "clan":
        where.append("p.clan_tag=?")
        args.append(tag)
    if days:
        where.append("p.end_ts>=?")
        args.append(int(time.time()) - days * 86400)
    if kind in ("war", "cwl"):
        where.append("p.kind=?")
        args.append(kind)
    elif kind == "cur":
        where += ["p.kind='cwl'", "p.end_ts>=?"]
        args.append(latest_season_ts(c, tag) or 0)
    if player:
        where.append("p.player=?")
        args.append(player)
    w = " AND ".join(where)
    plays = {}
    for r in c.execute(f"SELECT p.* FROM plays p WHERE {w} ORDER BY p.end_ts", args):
        plays[(r["player"], r["end_ts"])] = {**dict(r), "attacks": [], "defenses": []}
    for r in c.execute(f"SELECT h.* FROM hits h JOIN plays p ON p.player=h.player AND p.end_ts=h.end_ts WHERE {w} ORDER BY h.ord", args):
        p = plays.get((r["player"], r["end_ts"]))
        if p:
            p["attacks" if r["side"] == "attack" else "defenses"].append(dict(r))
    return list(plays.values())


def mean(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def kpi_values(plays):
    avail = sum(p["per"] for p in plays)
    atk = [a for p in plays for a in p["attacks"]]
    dfs = [d for p in plays for d in p["defenses"]]
    harder = [a["stars"] for p in plays for a in p["attacks"] if a["enemy_th"] and p["th"] and a["enemy_th"] >= p["th"]]
    stars = sum(a["stars"] for a in atk)
    return {"participacion": 100 * len(atk) / avail if avail else None,
            "estrellas": stars / avail if avail else None,
            "triples": 100 * sum(a["stars"] == 3 for a in atk) / len(atk) if atk else None,
            "dano": mean([a["pct"] for a in atk]),
            "exigencia": mean(harder),
            "defensa": mean([d["stars"] for d in dfs]),
            "constancia": 100 * sum(len(p["attacks"]) >= p["per"] for p in plays) / len(plays) if plays else None}


def kpi_scores(values):
    out, total, weight = {}, 0, 0
    for k in KPIS:
        v = values.get(k["id"])
        if v is None:
            out[k["id"]] = None
            continue
        s = max(0, min(100, 100 * (v - k["floor"]) / (k["target"] - k["floor"])))
        out[k["id"]] = round(s)
        total += s * k["weight"]
        weight += k["weight"]
    return out, round(total / weight) if weight else None


def level_of(index):
    if index is None:
        return {"id": "nada", "name": "Sin datos"}
    return next({"id": i, "name": n} for t, n, i in LEVELS if index >= t)


def trend(plays):
    """Forma: media de estrellas de los 5 últimos ataques frente a los 5 anteriores."""
    a = [x["stars"] for p in plays for x in p["attacks"]]
    if len(a) < 4:
        return None
    n = min(5, len(a) // 2)
    return round(mean(a[-n:]) - mean(a[-2 * n:-n]), 2)


def scorecard(plays):
    v = kpi_values(plays)
    scores, index = kpi_scores(v)
    atk = [a for p in plays for a in p["attacks"]]
    avail = sum(p["per"] for p in plays)
    return {"values": {k: (round(x, 2) if x is not None else None) for k, x in v.items()}, "scores": scores, "index": index,
            "level": level_of(index), "trend": trend(plays), "wars": len(plays), "avail": avail, "used": len(atk),
            "missed": avail - len(atk), "stars": sum(a["stars"] for a in atk), "few": avail < MIN_ATTACKS,
            "wins": sum(p["result"] == "win" for p in plays), "loses": sum(p["result"] == "lose" for p in plays)}


def live_wars(row, tag):
    if not row["timers"]:
        return []
    now = time.time()
    out = []
    for t in json.loads(row["timers"]):
        end = datetime.fromisoformat(t["expiresAt"].replace("Z", "+00:00")).timestamp()
        if end > now and tag in t.get("clans", []):
            rival = next((x for x in t["clans"] if x != tag), None)
            out.append({"type": t.get("type"), "ends": end, "rival": rival})
    return sorted(out, key=lambda x: x["ends"])


def members_state(c, tag):
    """Estado actual de cada miembro: en guerra, sin guerra o ya jugando en otro clan."""
    mine = own_names()
    official_list = meta_get(c, "official_ts")
    names = {**meta_get(c, "rivals", {}), **{r["opponent_tag"]: r["opponent"] for r in c.execute("SELECT opponent_tag, opponent FROM wars")}}
    out = {}
    for r in c.execute("SELECT * FROM players WHERE roster=1"):
        live = live_wars(r, tag)
        for w in live:
            w["rival_name"] = names.get(w["rival"])
        last = c.execute("SELECT end_ts, clan_tag, clan_name FROM plays WHERE player=? ORDER BY end_ts DESC LIMIT 1", (r["tag"],)).fetchone()
        # con lista oficial sabemos que sigue en el clan, aunque su última guerra fuese en otro
        state = "war" if live else "gone" if not official_list and last and last["clan_tag"] != tag else "idle"
        out[r["tag"]] = {"tag": r["tag"], "name": r["name"] or r["tag"], "th": r["th"], "mine": norm_name(r["name"]) in mine, "state": state,
                         "live": live, "last_war": last["end_ts"] if last else None, "last_clan": last["clan_name"] if last else None}
    return out


def live_rounds(members):
    """Guerras activas sin repetir. Una guerra dura 24 h: si acaba más tarde, sigue en preparación."""
    out = {}
    for m in members.values():
        for w in m["live"]:
            out[w["rival"]] = {**w, "phase": "prep" if w["ends"] - time.time() > 86400 else "battle"}
    return sorted(out.values(), key=lambda w: w["ends"])


# ---------------- jugadores: 1 jugador, N cuentas ----------------
# Un jugador es un grupo de cuentas guardado en clan.json; la cuenta que no está en ninguno es un jugador
# de una sola cuenta, así que un miembro nuevo aparece solo. Sus KPIs son la media de sus cuentas con
# guerras; una cuenta sin guerras no baja la media. Lo que se cuenta (ataques, estrellas) se suma.
def account_groups(c):
    saved = settings().get("groups")
    if saved is not None:
        return saved
    mine = own_names()     # hasta que se organice a mano, las cuentas del dueño ya van juntas
    tags = [r["tag"] for r in c.execute("SELECT tag, name FROM players WHERE roster=1") if norm_name(r["name"]) in mine]
    return [{"id": "yo", "name": "Mis cuentas", "accounts": tags}] if len(tags) > 1 else []


def save_groups(groups):
    if not isinstance(groups, list):
        raise ValueError("Lista de jugadores no válida.")
    c = db()
    try:
        names = {r["tag"]: r["name"] for r in c.execute("SELECT tag, name FROM players")}
        roster = {r["tag"] for r in c.execute("SELECT tag FROM players WHERE roster=1")}
        before = account_groups(c)
    finally:
        c.close()
    out, seen = [], set()
    for g in groups:
        accounts = [clean_tag(t) for t in g.get("accounts") or []]
        if seen & set(accounts) or len(set(accounts)) < len(accounts):
            raise ValueError("Una cuenta no puede estar en dos jugadores.")
        seen.update(accounts)
        gid = g.get("id") or uuid.uuid4().hex[:8]
        if not GROUP_ID_RE.match(str(gid)):
            raise ValueError("Jugador no válido.")
        name = str(g.get("name") or "").strip()[:30]
        out.append({"id": gid, "name": name or names.get(accounts[0] if accounts else None) or "Jugador", "accounts": accounts})
    for g in before:       # quien ha salido del clan no se ve en el panel: sigue en su jugador por si vuelve
        away = [t for t in g["accounts"] if t not in roster and t not in seen]
        if away:
            dest = next((o for o in out if o["id"] == g["id"]), None)
            if not dest:
                dest = {**g, "accounts": []}
                out.append(dest)
            dest["accounts"] += away
    _save({**settings(), "groups": [g for g in out if g["accounts"]]})


def mean_card(cards):
    """KPIs de un jugador a partir de los de sus cuentas."""
    played = [c for c in cards if c["wars"]]

    def avg(values, nd=2):
        m = mean(values)
        return round(m, nd) if m is not None else None
    index = avg([c["index"] for c in played], 0)
    index = int(index) if index is not None else None
    return {"values": {k["id"]: avg([c["values"][k["id"]] for c in played]) for k in KPIS},
            "scores": {k["id"]: avg([c["scores"][k["id"]] for c in played], 0) for k in KPIS}, "index": index, "level": level_of(index),
            "trend": avg([c["trend"] for c in played]), "few": all(c["few"] for c in cards),
            **{k: sum(c[k] for c in cards) for k in ("wars", "avail", "used", "missed", "stars", "wins", "loses")}}


def mean_record(records):
    return {**mean_card(records), **{k: sum(r[k] for r in records) for k in ("n", "won", "lost", "tied")}}


def owner_of(group, accounts):
    """Jugador con sus cuentas: cada cuenta conserva su nota y el jugador lleva la media."""
    ths = sorted({a["th"] for a in accounts if a.get("th")}, reverse=True)
    states = {a.get("state") for a in accounts}
    last = max(accounts, key=lambda a: a.get("last_war") or 0)
    return {"id": group["id"], "tag": group["id"], "name": group["name"], "grouped": True, "mine": any(a.get("mine") for a in accounts),
            "th": ths[0] if ths else None, "ths": ths, "state": "war" if "war" in states else "gone" if states == {"gone"} else "idle",
            "live": list({w["rival"]: w for a in accounts for w in a.get("live", [])}.values()), "last_war": last.get("last_war"), "last_clan": last.get("last_clan"),
            "accounts": [{k: v for k, v in a.items() if k != "ctx"} for a in accounts], **mean_card(accounts)}


def rank_key(p):
    return p["index"] is None, p["few"], -(p["index"] or 0), -p["stars"]


def build_owners(cards, groups):
    """Reparte las cuentas (tag → ficha) entre jugadores y marca en cada cuenta quién es su jugador."""
    owners, used = [], set()
    for g in groups:
        accounts = [cards[t] for t in g["accounts"] if t in cards]
        if accounts:
            used.update(a["tag"] for a in accounts)
            for a in accounts:
                a["owner"] = {"id": g["id"], "name": g["name"]}
            owners.append(owner_of(g, accounts))
    for t, a in cards.items():
        if t not in used:
            owners.append({**a, "id": t, "grouped": False, "ths": [a["th"]] if a.get("th") else [],
                           "accounts": [{k: v for k, v in a.items() if k != "ctx"}]})
    return sorted(owners, key=rank_key)


def owner_rows(c, groups, plays):
    """Jugadores con los KPIs de estas guerras; sólo cuentan las cuentas que las jugaron."""
    by = {}
    for p in plays:
        by.setdefault(p["player"], []).append(p)
    mine = own_names()
    info = {r["tag"]: r for r in c.execute("SELECT tag, name, th FROM players")}
    cards = {}
    for t, v in by.items():
        r = info.get(t)
        cards[t] = {"tag": t, "name": (r["name"] if r else None) or t, "th": r["th"] if r else None,
                    "mine": bool(r) and norm_name(r["name"]) in mine, **scorecard(v)}
    return build_owners(cards, groups)


def owner_names(groups):
    return {t: g["name"] for g in groups for t in g["accounts"]}


def owner_cards(c, clan_tag, group, kind, days, scope):
    """Un jugador con sus cuentas calculadas para estos filtros, y sus récords por tipo de guerra."""
    members = members_state(c, clan_tag)
    mine = own_names()
    cards, records = {}, []
    for t in group["accounts"]:
        r = c.execute("SELECT * FROM players WHERE tag=?", (t,)).fetchone()
        if r:
            base = members.get(t, {"tag": t, "name": r["name"] or t, "th": r["th"], "mine": norm_name(r["name"]) in mine, "state": "idle", "live": []})
            cards[t] = {**base, **scorecard(load_plays(c, clan_tag, kind, days, scope, t))}
            records.append({k: war_record(load_plays(c, clan_tag, k, days, "all", t)) for k in ("cwl", "war")})
    if not cards:
        raise ValueError("Jugador sin cuentas.")
    return build_owners(cards, [group])[0], records


# ---------------- vistas ----------------
def next_daily():
    if almacen.EN_NUBE:
        return None         # el cron de Vercel no fija el minuto: mejor no prometer una hora
    n = datetime.now().replace(hour=DAILY_HOUR, minute=DAILY_MINUTE, second=0, microsecond=0)
    return (n if n > datetime.now() else n + timedelta(days=1)).timestamp()


def meta_info(c):
    s = settings()
    syncing = meta_get(c, "syncing")
    return {"clan_tag": s.get("clan_tag"), "stamp": meta_get(c, "stamp"), "full_ts": meta_get(c, "full_ts"), "error": meta_get(c, "last_error"),
            "syncing": bool(syncing and time.time() - syncing["ts"] < 600), "next": next_daily(), "log": meta_get(c, "sync_log", [])[:5],
            "official": bool(meta_get(c, "official_ts")), "has_key": bool(api_key()), "proxy_ip": PROXY_IP, "cloud": almacen.EN_NUBE}


def maybe_light_sync(c):
    if not almacen.EN_NUBE and settings().get("clan_tag") and time.time() - (meta_get(c, "light_ts") or 0) > LIGHT_S and not _running.locked():
        start_sync(light=True, source="panel")


def clan_head(c, tag):
    w = c.execute("SELECT clan_name FROM plays WHERE clan_tag=? ORDER BY end_ts DESC LIMIT 1", (tag,)).fetchone()
    s = c.execute("SELECT * FROM seasons WHERE clan_tag=? ORDER BY season DESC LIMIT 1", (tag,)).fetchone()
    return {"tag": tag, "name": w["clan_name"] if w else tag, "season": dict(s) if s else None}


def status():
    c = db()
    try:
        maybe_light_sync(c)
        return meta_info(c)
    finally:
        c.close()


def overview(kind="all", days=0):
    c = db()
    try:
        out = {"meta": meta_info(c), "kpis": KPIS, "levels": [{"min": t, "name": n, "id": i} for t, n, i in LEVELS]}
        tag = out["meta"]["clan_tag"]
        if not tag:
            return out
        maybe_light_sync(c)
        plays = load_plays(c, tag, kind, days)
        by = {}
        for p in plays:
            by.setdefault(p["player"], []).append(p)
        cwl_by, war_by, recent, other = {}, {}, {}, {}
        for p in load_plays(c, tag, "all", days, "all"):
            if p["clan_tag"] == tag:
                (cwl_by if p["kind"] == "cwl" else war_by).setdefault(p["player"], []).append(p)
                recent.setdefault(p["player"], []).append(p)
            elif p["kind"] == "war":
                other.setdefault(p["player"], []).append(p)
        groups = account_groups(c)
        players = []
        for t, m in members_state(c, tag).items():
            ctx = {"cwl": scorecard(cwl_by.get(t, [])), "war": scorecard(war_by.get(t, [])), "other": scorecard(other.get(t, [])),
                   "other_clan": other[t][-1]["clan_name"] if t in other else None,
                   "recent": [{"ts": p["end_ts"], "kind": p["kind"], "opponent": p["opponent"], "result": p["result"], "per": p["per"],
                               "attacks": [{"stars": a["stars"], "pct": a["pct"], "enemy_th": a["enemy_th"]} for a in p["attacks"]]}
                              for p in reversed(recent.get(t, [])[-6:])]}
            players.append({**m, **scorecard(by.get(t, [])), "ctx": ctx})
        players.sort(key=rank_key)
        owners = build_owners({p["tag"]: p for p in players}, groups)
        full = {p["tag"]: p for p in players}
        for o in owners:
            if o["grouped"]:
                ctxs = [full[a["tag"]]["ctx"] for a in o["accounts"]]
                recent = [{**w, "account": a["name"]} for a, x in zip(o["accounts"], ctxs) for w in x["recent"]]
                o["ctx"] = {**{k: mean_card([x[k] for x in ctxs]) for k in ("cwl", "war", "other")},
                            "other_clan": next((x["other_clan"] for x in ctxs if x["other_clan"]), None),
                            "recent": sorted(recent, key=lambda w: -w["ts"])[:6]}
        wars = [dict(r) for r in c.execute("SELECT * FROM wars WHERE clan_tag=? ORDER BY end_ts", (tag,))]
        ends = {p["end_ts"] for p in plays}
        wars = [w for w in wars if w["end_ts"] in ends]
        all_cwl = load_plays(c, tag, "cwl", days)
        all_war = load_plays(c, tag, "war", days)
        cur = load_plays(c, tag, "cur", days)
        names = {p["tag"]: p for p in players}
        season_ts = latest_season_ts(c, tag) or 0
        season_rounds = [dict(r) for r in c.execute("SELECT * FROM wars WHERE clan_tag=? AND kind='cwl' AND end_ts>=? ORDER BY end_ts", (tag, season_ts))]
        last = c.execute("SELECT * FROM wars WHERE clan_tag=? ORDER BY end_ts DESC LIMIT 1", (tag,)).fetchone()
        missed = []
        if last:
            missed = [{"tag": p["player"], "name": names[p["player"]]["name"], "missed": p["per"] - len(p["attacks"])}
                      for p in load_plays(c, tag) if p["end_ts"] == last["end_ts"] and len(p["attacks"]) < p["per"] and p["player"] in names]
        return {**out, "clan": clan_head(c, tag), "players": players, "owners": owners, "groups": groups, "summary": scorecard(plays), "wars": wars,
                "wars_won": sum(w["result"] == "win" for w in wars), "split": {"cwl": war_record(all_cwl), "war": war_record(all_war), "cur": war_record(cur)},
                "last_war": dict(last) if last else None, "last_missed": missed, "season_rounds": season_rounds,
                "moves": [dict(r) for r in c.execute("SELECT * FROM moves WHERE ts>=? ORDER BY ts DESC", (int(time.time()) - 14 * 86400,))], "live": live_rounds(members_state(c, tag)),
                "others": sum(p["ctx"]["other"]["wars"] for p in players)}
    finally:
        c.close()


def war_record(plays):
    """Tarjeta de un conjunto de guerras: victorias contadas por guerra, no por jugador."""
    wars = {p["end_ts"]: p["result"] for p in plays}
    return {**scorecard(plays), "n": len(wars), "won": sum(r == "win" for r in wars.values()), "lost": sum(r == "lose" for r in wars.values()),
            "tied": sum(r == "tie" for r in wars.values())}


def wars_view(kind="all", days=0):
    c = db()
    try:
        out = {"meta": meta_info(c)}
        tag = out["meta"]["clan_tag"]
        if not tag:
            return out
        plays = load_plays(c, tag, kind, days)
        wars = {r["end_ts"]: {**dict(r), "lineup": []} for r in c.execute("SELECT * FROM wars WHERE clan_tag=?", (tag,))}
        names = {r["tag"]: r["name"] for r in c.execute("SELECT tag, name FROM players")}
        for p in plays:
            if p["end_ts"] in wars:
                wars[p["end_ts"]]["lineup"].append({
                    "tag": p["player"], "name": names.get(p["player"]) or p["player"], "th": p["th"], "pos": p["pos"], "per": p["per"],
                    "attacks": [{k: a[k] for k in ("stars", "pct", "enemy", "enemy_th", "enemy_pos", "duration")} for a in p["attacks"]],
                    "defenses": [{k: d[k] for k in ("stars", "pct", "enemy", "enemy_th")} for d in p["defenses"]]})
        rows = sorted((w for w in wars.values() if w["lineup"]), key=lambda w: w["end_ts"], reverse=True)
        for w in rows:
            w["lineup"].sort(key=lambda m: m["pos"] or 99)
        order = {}
        for p in plays:
            order[p["player"]] = order.get(p["player"], 0) + sum(a["stars"] for a in p["attacks"])
        heat = [{"tag": t, "name": names.get(t) or t} for t in sorted(order, key=order.get, reverse=True)]
        # guerras normales de los miembros con otros clanes: contexto, nunca mezclado con las del clan
        members = members_state(c, tag)
        groups = {}
        for p in load_plays(c, tag, "war", days, "all"):
            if p["clan_tag"] != tag and p["player"] in members:
                groups.setdefault(p["player"], []).append(p)
        others = [{"tag": t, "name": members[t]["name"], "th": members[t]["th"], "last_clan": v[-1]["clan_name"], "last_ts": v[-1]["end_ts"],
                   "clans": len({p["clan_tag"] for p in v}), **scorecard(v)} for t, v in groups.items()]
        others.sort(key=lambda o: (o["index"] is None, -(o["index"] or 0)))
        groups = account_groups(c)
        return {**out, "clan": clan_head(c, tag), "wars": rows, "heat": heat, "summary": war_record(plays), "others": others,
                "owners": owner_rows(c, groups, plays), "owner_names": owner_names(groups)}
    finally:
        c.close()


def leagues_view():
    c = db()
    try:
        out = {"meta": meta_info(c)}
        tag = out["meta"]["clan_tag"]
        if not tag:
            return out
        seasons = [dict(r) for r in c.execute("SELECT * FROM seasons WHERE clan_tag=? ORDER BY season", (tag,))]
        plays = load_plays(c, tag, "cwl")
        names = {r["tag"]: r["name"] for r in c.execute("SELECT tag, name FROM players")}
        rounds = {}
        for r in c.execute("SELECT * FROM wars WHERE clan_tag=? AND kind='cwl' ORDER BY end_ts", (tag,)):
            rounds.setdefault(month_of(r["end_ts"]), []).append(dict(r))
        for s in seasons:
            s["rounds_data"] = rounds.get(s["season"][:7], [])
            s["war_stars"] = sum(w["stars"] for w in s["rounds_data"])
        matrix = {}
        for p in plays:
            row = matrix.setdefault(p["player"], {"tag": p["player"], "name": names.get(p["player"]) or p["player"], "cells": {}})
            cell = row["cells"].setdefault(month_of(p["end_ts"]), {"stars": 0, "avail": 0, "used": 0})
            cell["avail"] += p["per"]
            cell["used"] += len(p["attacks"])
            cell["stars"] += sum(a["stars"] for a in p["attacks"])
        table = sorted(matrix.values(), key=lambda r: -sum(x["stars"] for x in r["cells"].values()))
        detail = wars_view("cwl")
        groups = account_groups(c)
        by_month = {}
        for p in plays:
            by_month.setdefault(month_of(p["end_ts"]), []).append(p)
        return {**out, "clan": clan_head(c, tag), "seasons": seasons, "matrix": table, "rounds": detail["wars"], "heat": detail["heat"],
                "owners": {m: owner_rows(c, groups, v) for m, v in by_month.items()}, "owner_names": detail["owner_names"],
                "live": live_rounds(members_state(c, tag))}
    finally:
        c.close()


def month_of(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m")


def player_view(tag, kind="all", days=0, scope="clan"):
    tag = clean_tag(tag)
    c = db()
    try:
        out = {"meta": meta_info(c), "kpis": KPIS}
        clan_tag = out["meta"]["clan_tag"]
        row = c.execute("SELECT * FROM players WHERE tag=?", (tag,)).fetchone()
        if not row:
            raise ValueError("Jugador desconocido.")
        plays = load_plays(c, clan_tag, kind, days, scope, tag)
        clan = scorecard(load_plays(c, clan_tag, kind, days))
        atk = [(p, a) for p in plays for a in p["attacks"]]
        dfs = [(p, d) for p in plays for d in p["defenses"]]
        roll, recent = [], []
        for p, a in atk:
            recent = (recent + [a["stars"]])[-5:]
            roll.append({"ts": p["end_ts"], "avg": round(mean(recent), 2)})
        timeline = [{"ts": p["end_ts"], "opponent": p["opponent"], "clan": p["clan_name"], "kind": p["kind"], "result": p["result"], "per": p["per"],
                     "pos": p["pos"], "th": p["th"], "size": p["size"],
                     "stars": sum(a["stars"] for a in p["attacks"]), "conceded": sum(d["stars"] for d in p["defenses"]),
                     "defenses": len(p["defenses"]), "attacks": [{k: a[k] for k in ("stars", "pct", "enemy", "enemy_th", "enemy_pos", "duration")} for a in p["attacks"]]}
                    for p in plays]
        dist = [sum(a["stars"] == n for _, a in atk) for n in range(4)]
        diff = {}
        for p, a in atk:
            if a["enemy_th"] and p["th"]:
                d = max(-3, min(3, a["enemy_th"] - p["th"]))
                diff.setdefault(d, []).append(a)
        by_diff = [{"diff": d, "n": len(v), "stars": round(mean([x["stars"] for x in v]), 2), "pct": round(mean([x["pct"] for x in v]))}
                   for d, v in sorted(diff.items())]
        timing = [0, 0, 0]
        for p, a in atk:
            total = (p["size"] or 0) * p["per"] * 2
            if total and a["ord"]:
                timing[min(2, 3 * (a["ord"] - 1) // total)] += 1
        dur = [{"ts": p["end_ts"], "s": a["duration"], "stars": a["stars"]} for p, a in atk if a["duration"]]
        th_seen = {}
        for p, d in dfs:
            if d["enemy_th"]:
                th_seen.setdefault(d["enemy_th"], []).append(d["stars"])
        seasons = [dict(r) for r in c.execute("SELECT * FROM player_seasons WHERE player=? ORDER BY season", (tag,))]
        state = members_state(c, clan_tag).get(tag, {"name": row["name"], "th": row["th"], "state": "idle", "live": []})
        history = {"wars": c.execute("SELECT COUNT(*) n FROM plays WHERE player=?", (tag,)).fetchone()["n"],
                   "clans": c.execute("SELECT COUNT(DISTINCT clan_tag) n FROM plays WHERE player=?", (tag,)).fetchone()["n"]}
        split = {"cwl": war_record(load_plays(c, clan_tag, "cwl", days, "all", tag)), "war": war_record(load_plays(c, clan_tag, "war", days, "all", tag))}
        group = next((g for g in account_groups(c) if tag in g["accounts"]), None)
        owner = owner_cards(c, clan_tag, group, kind, days, scope)[0] if group else None
        return {**out, "player": {**state, "tag": tag, "name": row["name"] or tag}, "owner": owner, "card": scorecard(plays), "clan_card": clan, "timeline": timeline, "split": split,
                "rolling": roll, "dist": dist, "by_diff": by_diff, "timing": timing, "durations": dur, "seasons": seasons, "history": history,
                "def_by_th": [{"th": t, "n": len(v), "stars": round(mean(v), 2)} for t, v in sorted(th_seen.items())]}
    finally:
        c.close()


def owner_view(gid, kind="all", days=0, scope="clan"):
    c = db()
    try:
        out = {"meta": meta_info(c), "kpis": KPIS}
        clan_tag = out["meta"]["clan_tag"]
        group = next((g for g in account_groups(c) if g["id"] == gid), None)
        if not group:
            raise ValueError("Jugador desconocido.")
        owner, records = owner_cards(c, clan_tag, group, kind, days, scope)
        tags = [a["tag"] for a in owner["accounts"]]
        marks = ",".join("?" * len(tags))
        history = {"wars": c.execute(f"SELECT COUNT(*) n FROM plays WHERE player IN ({marks})", tags).fetchone()["n"],
                   "clans": c.execute(f"SELECT COUNT(DISTINCT clan_tag) n FROM plays WHERE player IN ({marks})", tags).fetchone()["n"]}
        return {**out, "owner": owner, "clan_card": scorecard(load_plays(c, clan_tag, kind, days)), "history": history,
                "split": {k: mean_record([r[k] for r in records]) for k in ("cwl", "war")}}
    finally:
        c.close()

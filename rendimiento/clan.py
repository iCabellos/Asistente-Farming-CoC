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
import contextvars
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
import liga
import modelo
import prediccion

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
PAST_SHOWN = 14       # guerras pasadas que se enseñan con todo su detalle
VILLAGE_DAYS, HISTORY_DAYS = 3, 6     # cada cuánto se renueva lo que se sabe de un jugador de la liga
INTEL_SECONDS = 120   # tiempo máximo por recogida para renovarlo
PRED_SECONDS = 45     # tiempo máximo por recogida para predecir guerras pendientes; el resto, en la siguiente
LIVE_SECONDS = 45     # una guerra en juego se pide a la API como mucho una vez en este tiempo
DAILY_HOUR, DAILY_MINUTE = 11, 1
MAX_CLANS = 12        # cada clan gasta una recogida diaria de API y de almacén

# Sistema de KPIs. Nota 0–100: lineal entre `floor` (0) y `target` (100). Si un KPI no se puede medir,
# su peso se reparte entre los demás en vez de penalizar.
KPIS = [
    {"id": "dano_liga", "name": "% medio en liga", "unit": "%", "weight": 25, "floor": 60, "target": 100,
     "help": "Destrucción media de sus ataques de liga: la destrucción acumulada desempata la clasificación"},
    {"id": "estrellas", "name": "Estrellas por ataque", "unit": "★", "weight": 20, "floor": 1, "target": 2.6,
     "help": "Media por ataque disponible: un ataque sin usar cuenta 0"},
    {"id": "dano_efectivo", "name": "Daño efectivo", "unit": "%", "weight": 15, "floor": 50, "target": 95,
     "help": "Destrucción media por ataque disponible: un ataque sin usar cuenta 0 %"},
    {"id": "participacion", "name": "Participación", "unit": "%", "weight": 15, "floor": 50, "target": 100,
     "help": "Ataques usados de los disponibles"},
    {"id": "dano", "name": "Daño medio", "unit": "%", "weight": 5, "floor": 50, "target": 95,
     "help": "Destrucción media de los ataques que usó, en liga y normales"},
    {"id": "triples", "name": "Triples", "unit": "%", "weight": 5, "floor": 10, "target": 70,
     "help": "Ataques de 3 estrellas sobre los usados"},
    {"id": "exigencia", "name": "Contra TH igual o mayor", "unit": "★", "weight": 5, "floor": 1, "target": 2.4,
     "help": "Estrellas medias contra rivales de su TH o superior"},
    {"id": "defensa", "name": "Estrellas otorgadas al rival", "unit": "★", "weight": 5, "floor": 3, "target": 0,
     "help": "Estrellas que le sacan por guerra jugada; si nadie le ataca cuenta 0. Lo mejor es 0 y lo peor 3 por guerra"},
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
CREATE TABLE IF NOT EXISTS book(a TEXT, d TEXT, end_ts REAL, ord INT, a_th INT, d_th INT, a_pos INT, d_pos INT, size INT, cwl INT, stars INT, pct REAL, fresh INT, clan TEXT,
  PRIMARY KEY(a, d, end_ts, ord));
CREATE TABLE IF NOT EXISTS war_use(tag TEXT, end_ts REAL, cwl INT, per INT, used INT, PRIMARY KEY(tag, end_ts));
CREATE TABLE IF NOT EXISTS village(tag TEXT PRIMARY KEY, ts INT, data TEXT);
CREATE TABLE IF NOT EXISTS intel(tag TEXT PRIMARY KEY, ts INT);
CREATE TABLE IF NOT EXISTS battles(end_ts INT PRIMARY KEY, kind TEXT, state TEXT, rival TEXT, data TEXT, forecast TEXT, review TEXT);
"""
_locks = {}           # una recogida a la vez por clan; dos clanes distintos sí pueden ir a la par
_locks_guard = threading.Lock()


# ---------------- ajustes y clanes ----------------
# Los ajustes son uno solo; `settings()` los enseña ya mirando al clan de esta petición, así el resto del código no cambia.
_save = almacen.guardar_ajustes


def running():
    with _locks_guard:
        return _locks.setdefault(almacen.archivo(), threading.Lock())


def _raw():
    """Ajustes tal cual, recién leídos: lo que se vaya a escribir no debe partir de una copia vieja."""
    return almacen.leer_ajustes(fresco=True)


def clan_list(s=None):
    s = almacen.leer_ajustes() if s is None else s
    rows = s.get("clans")
    if rows is None:      # de cuando solo se podía seguir uno
        return [{"tag": s["clan_tag"], "file": almacen.PRIMERO, "name": s.get("clan_name")}] if s.get("clan_tag") else []
    return rows


def _active(s):
    rows, f = clan_list(s), almacen.archivo()
    return next((r for r in rows if r["file"] == f), rows[0] if rows else None)


def settings():
    s = almacen.leer_ajustes()
    e = _active(s)
    if not e:
        return {**s, "clan_tag": None}
    return {**s, "clan_tag": e["tag"], "groups": e["groups"] if "groups" in e else s.get("groups") if e["file"] == almacen.PRIMERO else None}


def use_clan(tag=None):
    """Elige el clan de esta petición. Sin tag, o con uno que ya no se sigue, el primero de la lista."""
    rows = clan_list()
    wanted = str(tag or "").strip().upper().lstrip("#")
    e = next((r for r in rows if r["tag"][1:] == wanted), rows[0] if rows else None)
    almacen.usar(e["file"] if e else None)
    return e


def _update_clan(tag, **fields):
    s = _raw()
    rows = [dict(r) for r in clan_list(s)]
    for r in rows:
        if r["tag"] == tag:
            r.update(fields)
    _save({**s, "clans": rows})


def add_clan(tag):
    """Añade un clan a la lista. La API oficial es quien sabe si existe: ClashKing solo conoce los clanes que sigue."""
    tag = clean_tag(tag)
    s = _raw()
    rows = [dict(r) for r in clan_list(s)]
    if any(r["tag"] == tag for r in rows):
        raise ValueError("Ese clan ya está en la lista.")
    if len(rows) >= MAX_CLANS:
        raise ValueError(f"Como mucho se pueden seguir {MAX_CLANS} clanes.")
    name = None
    if api_key():
        try:
            name = official(f"/clans/{enc(tag)}").get("name")
        except NotFound:
            raise ValueError(f"No existe ningún clan con el tag {tag}. Revisa que sea el del clan, no el de tu perfil.") from None
        except RuntimeError as e:
            raise ValueError(str(e)) from e
    elif not ((get(f"/v2/clan/{enc(tag)}/wars?limit=1") or {}).get("items") or (get(f"/v2/cwl/{enc(tag)}/seasons?limit=1") or {}).get("items")):
        raise ValueError(f"ClashKing no tiene guerras del clan {tag}. Revisa que sea el tag del clan, no el de tu perfil.")
    off = [dict(r) for r in s.get("clans_off") or []]
    back = next((r for r in off if r["tag"] == tag), None)    # si ya se siguió, recupera sus datos
    entry = {**(back or {"tag": tag, "file": tag[1:]}), "name": name or (back or {}).get("name") or tag}
    _save({**s, "clans": rows + [entry], "clans_off": [r for r in off if r["tag"] != tag]})
    return {"tag": tag, "name": entry["name"]}


def remove_clan(tag):
    """Deja de seguir un clan. Sus datos se conservan por si vuelve."""
    tag = clean_tag(tag)
    s = _raw()
    rows = [dict(r) for r in clan_list(s)]
    out = next((r for r in rows if r["tag"] == tag), None)
    if not out:
        raise ValueError("Ese clan no está en la lista.")
    if len(rows) == 1:
        raise ValueError("Tiene que quedar al menos un clan.")
    if out["file"] == almacen.PRIMERO and "groups" not in out and s.get("groups") is not None:
        out["groups"] = s["groups"]
    _save({**s, "clans": [r for r in rows if r["tag"] != tag], "clans_off": [*(s.get("clans_off") or []), out]})


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
    """Primer clan: al instalar aún no hay ninguno, así que se añade y se empieza a recoger."""
    info = add_clan(tag)
    use_clan(info["tag"])
    start_sync()


def api_key():
    return settings().get("api_key") or os.environ.get("COC_API_KEY")


class NotFound(RuntimeError):
    pass


# ---------------- avance de los cálculos ----------------
# Una recogida o un recálculo tardan: se publica por qué parte van y la web lo enseña a quien la tenga abierta,
# también si lo lanzó el cron. Cada fase ocupa un tramo de la barra según lo que suele tardar.
STAGES = {"recoger": (0, 12, "Recogiendo guerras del clan"), "jugadores": (12, 28, "Actualizando jugadores"), "grupo": (28, 34, "Bajando el grupo de liga"),
          "aldeas": (34, 50, "Revisando aldeas e historial"), "modelo": (50, 64, "Entrenando el modelo de ataques"), "plan": (64, 68, "Calculando el plan de ataque"),
          "sim": (68, 84, "Simulando la liga"), "rondas": (84, 90, "Repasando las rondas jugadas"), "batallas": (90, 97, "Comparando lo previsto con lo real"), "publicar": (97, 100, "Publicando los resultados")}
STALLED_S = 150           # sin noticias en este tiempo, el trabajo se dio por muerto (una función cortada no avisa)


class Progress:
    def __init__(self, source, quiet=False, first="recoger"):
        self.source, self.quiet, self.first, self.file = source, quiet, first, almacen.archivo()
        self.names = list(STAGES)
        self.names = self.names[self.names.index(first):]
        self.start = STAGES[first][0]
        self.stage, self.pct, self.last, self.t0 = None, 0, 0.0, int(time.time())
        self.gap = 2.5 if almacen.EN_NUBE else .4    # cada aviso en la nube gasta una operación del almacén
        self.lock = threading.Lock()

    def __call__(self, stage, frac=0.0, detail=None):
        if self.quiet or stage not in self.names:
            return
        with self.lock:
            a, b, _ = STAGES[stage]
            raw = a + (b - a) * max(0.0, min(1.0, frac))
            self.pct = max(self.pct, int(100 * (raw - self.start) / (100 - self.start)))    # la barra nunca retrocede
            changed, self.stage = stage != self.stage, stage
            if changed or time.time() - self.last >= self.gap:
                self.last = time.time()
                self._send(True, detail)

    def _send(self, active, detail=None, **extra):
        stage = self.stage or self.first
        almacen.guardar_progreso({"active": active, "pct": self.pct, "stage": stage, "label": STAGES[stage][2], "detail": detail, "source": self.source, "started": self.t0, "updated": int(time.time()),
                                  "step": self.names.index(stage) + 1, "steps": [STAGES[n][2] for n in self.names], **extra}, self.file)

    def finish(self, ok=True, error=None):
        if not self.quiet:
            self.pct = 100 if ok else self.pct
            self._send(False, ok=ok, error=error)


def progress_state():
    p = almacen.leer_progreso()
    if p.get("active") and time.time() - p.get("updated", 0) > STALLED_S:
        return {**p, "active": False, "ok": False, "error": "La última recogida se cortó antes de terminar."}
    return p


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
    if r.status_code == 403 and "private" in str(r.text).lower():
        raise RuntimeError("El clan tiene privado su registro de guerras: la API no da la guerra en curso.")
    if r.status_code == 403:
        raise RuntimeError("Supercell rechaza la clave. Revisa que esté bien copiada y que siga activa.")
    if r.status_code == 503:
        raise RuntimeError("El juego está en mantenimiento; se reintenta en la próxima recogida.")
    if r.status_code == 404:
        raise NotFound("La API oficial no lo encuentra.")
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
    _save({**_raw(), "api_key": key})
    start_sync()


# ---------------- administración ----------------
# Sin configurar, entra admin/admin. Al cambiarla sólo se guarda un hash, nunca la contraseña.
def _hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000).hex()


def check_admin(user, password):
    cfg = almacen.leer_ajustes(fresco=True).get("admin")    # nunca con una copia vieja: da igual qué instancia responda
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
    _save({**_raw(), "admin": {"user": user, "salt": salt, "hash": _hash(password, salt)}})


def admin_info():
    c = db()
    try:
        cfg = settings().get("admin")
        return {**meta_info(c), "user": cfg["user"] if cfg else "admin", "default": not cfg, "log": meta_get(c, "sync_log", [])[:8],
                "members": c.execute("SELECT COUNT(*) n FROM players WHERE roster=1").fetchone()["n"], "liga": _liga_admin(c)}
    finally:
        c.close()


def _liga_admin(c):
    tag = settings().get("clan_tag")
    view = meta_get(c, f"liga:{tag}") if tag else None
    return {"cfg": liga_cfg(tag), "zones": view["zones"], "roster": view["bench"]["roster"]} if view else None


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
    store_battle(c, w, tag, kind)
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


def store_battle(c, w, tag, kind):
    """Guarda la guerra entera, con nuestro clan a un lado: hace falta para comparar lo previsto con lo que pasó."""
    us, them = w.get("clan") or {}, w.get("opponent") or {}
    if them.get("tag") == tag:
        w = {**w, "clan": them, "opponent": us}
    elif us.get("tag") != tag:
        return
    end = api_ts(w.get("endTime"))
    if not end or w.get("state") not in ("preparation", "inWar", "warEnded"):
        return
    t = trim_war(w)
    old = c.execute("SELECT data FROM battles WHERE end_ts=?", (end,)).fetchone()
    if old:                              # ClashKing no sabe la ronda; la liga, sí
        prev = json.loads(old["data"])
        t["round"], t["tag"] = t.get("round") or prev.get("round"), t.get("tag") or prev.get("tag")
    c.execute("""INSERT INTO battles(end_ts, kind, state, rival, data) VALUES(?,?,?,?,?)
                 ON CONFLICT(end_ts) DO UPDATE SET kind=excluded.kind, state=excluded.state, rival=excluded.rival, data=excluded.data""",
              (end, kind, w["state"], (w.get("opponent") or {}).get("name"), json.dumps(t, ensure_ascii=False)))


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
    """Recoge y guarda el clan de esta petición. Devuelve False si ya había otra en marcha."""
    lock = running()
    if not lock.acquire(blocking=False):
        return False
    c = None
    done = False
    fail = None
    P = Progress(source, quiet=light)
    try:
        P("recoger")
        s = settings()
        tag = s.get("clan_tag")
        if not tag:
            raise RuntimeError("Falta el tag del clan.")
        c = db()
        with c:
            meta_set(c, "syncing", {"ts": time.time(), "light": light})
        wars = [(k, w) for k, t in (("cwl", "cwl"), ("war", "random"))
                for w in (get(f"/v2/clan/{enc(tag)}/wars?limit=200&type={t}") or {}).get("items", [])]
        P("recoger", .6)
        seasons = (get(f"/v2/cwl/{enc(tag)}/seasons?limit=24") or {}).get("items", [])
        listed, official_error, league = None, None, None
        if api_key():
            try:
                info = official(f"/clans/{enc(tag)}")
                listed, league = info.get("memberList"), (info.get("warLeague") or {}).get("name")
                if info.get("name") and info["name"] != _active(s).get("name"):
                    _update_clan(tag, name=info["name"])
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

        count = [0]

        def safe(t):
            try:
                return fetch_player(t, light)
            except RuntimeError as e:      # un jugador que falla no tira la recogida entera
                return {"tag": t, "error": str(e)}
            finally:
                count[0] += 1
                P("jugadores", count[0] / max(len(roster), 1), f"{count[0]} de {len(roster)}")

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
                if "wars" in d:              # su historial también entrena el modelo: así no se pide dos veces
                    store_history(c, d["tag"], *modelo.rows_from_history(d["tag"], d["wars"]), now)
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
        refresh_league(c, tag, league, P)
        refresh_battles(c, tag, P)
        done = True
        return True
    except Exception as e:             # también lo inesperado: si no, una recogida fallida no dejaría rastro
        fail = str(e)
        if c is None:
            c = db()
        with c:
            meta_set(c, "last_error", str(e) if isinstance(e, RuntimeError) else f"Error al guardar los datos: {e}")
            meta_set(c, "fail_ts", int(time.time()))
        raise RuntimeError(str(e)) from e
    finally:
        P("publicar")
        if c is not None:
            with c:
                meta_set(c, "syncing", None)
            c.close()
            almacen.publicar_db()
        P.finish(done, fail)
        lock.release()


def start_sync(light=False, source="panel"):
    def run():
        try:
            sync(light, source)
        except RuntimeError:
            pass                 # queda en last_error y el panel lo enseña
    if almacen.EN_NUBE:
        run()                    # en la nube un hilo moriría con la petición
    else:                        # el hilo nuevo debe seguir con el clan de esta petición
        threading.Thread(target=contextvars.copy_context().run, args=(run,), daemon=True).start()


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


# ---------------- escenarios de liga ----------------
# Cada recogida baja el grupo del clan seguido. Las guerras terminadas no cambian: se guardan y no se piden más.
# Lo que enseña la web se calcula aquí (liga.build) y se guarda, así abrirla no cuesta nada.
def liga_cfg(tag):
    return (settings().get("liga") or {}).get(tag) or {}


def trim_war(w):
    keep = ("tag", "round", "state", "teamSize", "attacksPerMember", "startTime", "endTime", "partial")
    def side(s):
        return {"tag": s["tag"], "name": s.get("name"), "stars": s.get("stars", 0), "destructionPercentage": s.get("destructionPercentage", 0), "attacks": s.get("attacks", 0),
                "members": [{"tag": m["tag"], "name": m.get("name"), "townhallLevel": m.get("townhallLevel"), "mapPosition": m.get("mapPosition"),
                             "attacks": [{k: a.get(k) for k in ("defenderTag", "stars", "destructionPercentage", "order")} for a in m.get("attacks") or []]}
                            for m in s.get("members") or []]}
    return {**{k: w.get(k) for k in keep}, "clan": side(w["clan"]), "opponent": side(w["opponent"])}


def fetch_league(c, tag, league, progress=None):
    """Liga normalizada, o None si el clan no está en ninguna ahora mismo."""
    on = progress or (lambda *a, **k: None)
    on("grupo")
    try:
        group = official(f"/clans/{enc(tag)}/currentwar/leaguegroup")
    except NotFound:
        return None
    if not group.get("clans") or group.get("state") == "notInWar":
        return None
    key = f"liga_wars:{tag}:{group.get('season')}"
    stored = meta_get(c, key, {})

    count = [0]

    def one(item):
        r, wt = item
        w = {**official(f"/clanwarleagues/wars/{quote(wt, safe='')}"), "round": r, "tag": wt}
        count[0] += 1
        on("grupo", count[0] / max(len(todo), 1), f"guerra {count[0]} de {len(todo)}")
        return w
    todo = [(i, wt) for i, r in enumerate(group.get("rounds") or [], 1) for wt in r.get("warTags") or [] if wt != "#0" and wt not in stored]
    with ThreadPoolExecutor(4) as ex:
        fresh = list(ex.map(one, todo))
    wars = list(stored.values()) + [trim_war(w) for w in fresh]
    meta_set(c, key, {w["tag"]: w for w in wars if w.get("state") == "warEnded"})
    with c:
        for w in wars:
            store_battle(c, w, tag, "cwl")
    return {**liga.normalize(group, wars, tag, league), "now": time.time()}


def store_history(c, tag, rows, usage, now):
    c.executemany("INSERT OR REPLACE INTO book VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  [(r["a"], r["d"], r["end"], r["ord"], r["a_th"], r["d_th"], r["a_pos"], r["d_pos"], r["size"], r["cwl"], r["stars"], r["pct"], r["fresh"], r["clan"]) for r in rows])
    c.executemany("INSERT OR REPLACE INTO war_use VALUES(?,?,?,?,?)", [(u["tag"], u["end"], u["cwl"], u["per"], u["used"]) for u in usage])
    c.execute("INSERT OR REPLACE INTO intel VALUES(?,?)", (tag, now))


def refresh_intel(c, tags, progress=None):
    """Aldeas e historial de los jugadores de una liga o una guerra, propios y rivales. Cambian despacio: se piden sólo si
    están viejos, primero los que más lo necesitan y con tiempo limitado; lo que no dé tiempo llega en la siguiente recogida."""
    now = int(time.time())
    last_v = {r["tag"]: r["ts"] for r in c.execute("SELECT tag, ts FROM village")}
    last_h = {r["tag"]: r["ts"] for r in c.execute("SELECT tag, ts FROM intel")}
    stop = time.time() + INTEL_SECONDS
    on = progress or (lambda *a, **k: None)
    count = [0]

    def tick():
        count[0] += 1
        total = len(old_v) + len(old_h)
        on("aldeas", count[0] / max(total, 1), f"{count[0]} de {total}")

    def village(t):
        if time.time() > stop:
            return None
        try:
            return t, modelo.village_summary(official(f"/players/{quote(t, safe='')}"))
        except RuntimeError:
            return None
        finally:
            tick()

    def history(t):
        if time.time() > stop:
            return None
        try:
            return (t, *modelo.rows_from_history(t, (get(f"/v2/player/{enc(t)}/war/stats?limit=500") or {}).get("items", [])))
        except RuntimeError:
            return None
        finally:
            tick()
    old_v = sorted((t for t in tags if now - last_v.get(t, 0) > VILLAGE_DAYS * 86400), key=lambda t: last_v.get(t, 0))
    old_h = sorted((t for t in tags if now - last_h.get(t, 0) > HISTORY_DAYS * 86400), key=lambda t: last_h.get(t, 0))
    on("aldeas")
    with ThreadPoolExecutor(6) as ex:
        villages = [x for x in ex.map(village, old_v) if x]
    with ThreadPoolExecutor(4) as ex:
        hist = [x for x in ex.map(history, old_h) if x]
    with c:
        c.executemany("INSERT OR REPLACE INTO village VALUES(?,?,?)", [(t, now, json.dumps(v, ensure_ascii=False)) for t, v in villages])
        for t, rows, usage in hist:
            store_history(c, t, rows, usage, now)
    return len(villages), len(hist)


def league_data(c):
    """Todo lo conocido para entrenar el modelo. La memoria de ataques sobrevive a los cambios de clan."""
    keys = ("a", "d", "end", "ord", "a_th", "d_th", "a_pos", "d_pos", "size", "cwl", "stars", "pct", "fresh", "clan")
    rows = [dict(zip(keys, r)) for r in c.execute("SELECT a,d,end_ts,ord,a_th,d_th,a_pos,d_pos,size,cwl,stars,pct,fresh,clan FROM book")]
    usage = [dict(zip(("tag", "end", "cwl", "per", "used"), r)) for r in c.execute("SELECT tag,end_ts,cwl,per,used FROM war_use")]
    villages = {r["tag"]: json.loads(r["data"]) for r in c.execute("SELECT tag, data FROM village")}
    saved = meta_get(c, "model_hp", {})
    fresh = bool(saved) and len(rows) < saved.get("rows", 0) * 1.05    # se vuelve a afinar cuando hay un 5 % más de ataques
    return {"rows": rows, "usage": usage, "villages": villages, "hp": saved.get("hp") if fresh else None}


def build_league(c, tag, L, progress=None):
    cfg = liga_cfg(tag)
    key = f"liga_hist:{tag}:{L['season']}"
    data = league_data(c)
    view = liga.build(L, cfg, meta_get(c, key, {}), data=data, progress=progress)
    meta_set(c, key, view.pop("hist"))
    view["ts"] = int(time.time())
    meta_set(c, f"liga:{tag}", view)
    info, saved = view["model"], meta_get(c, "model_hp", {})
    if not data["hp"] and info.get("hp"):
        saved = {**saved, "rows": info.get("rows", 0), "hp": info["hp"]}
    if info.get("calib") is not None:
        saved = {**saved, "sigma": info.get("war_sigma"), "calib": info["calib"]}
    meta_set(c, "model_hp", saved)
    return view


def refresh_league(c, tag, league, progress=None):
    """Nunca tumba la recogida: si la liga falla, sigue lo demás y la pestaña avisa de que no está al día."""
    if not api_key():
        return
    try:
        L = fetch_league(c, tag, league, progress)
        if L is not None:
            refresh_intel(c, [m["tag"] for x in L["clans"] for m in x["roster"]], progress)
        with c:
            meta_set(c, f"liga_off:{tag}", L is None)
            if L is not None:
                meta_set(c, f"liga_data:{tag}", L)
                build_league(c, tag, L, progress)
            meta_set(c, f"liga_error:{tag}", None)
    except Exception as e:      # noqa: BLE001 — también lo inesperado: la recogida de guerras ya está guardada
        with c:
            meta_set(c, f"liga_error:{tag}", str(e) if isinstance(e, RuntimeError) else f"No se pudo calcular la liga: {e}")


# ---------------- previsto y real ----------------
# La liga llega por fetch_league; la guerra normal, por la API oficial, porque ClashKing puede no seguir ese clan.
def fetch_current_war(c, tag):
    """Guerra normal en curso. Si ya terminó y sigue visible, además queda guardada como cualquier otra guerra."""
    try:
        w = official(f"/clans/{enc(tag)}/currentwar")
    except NotFound:
        return
    if w.get("state") in ("preparation", "inWar", "warEnded"):
        with c:
            if w["state"] == "warEnded":
                store_clan_war(c, w, tag, "war")
            else:
                store_battle(c, w, tag, "war")


def close_stale(c, tag):
    """Guerra que seguíamos y ya no aparece porque empezó otra entre dos recogidas: se cierra con lo último visto y el
    marcador final del registro del clan. Sus últimos ataques pueden faltar: queda marcada como parcial."""
    now = time.time()
    rows = c.execute("SELECT end_ts, kind, data FROM battles WHERE state IN ('preparation','inWar') AND end_ts<?", (now - 600,)).fetchall()
    if not rows:
        return
    try:
        log = (official(f"/clans/{enc(tag)}/warlog?limit=20") or {}).get("items", [])
    except RuntimeError:
        log = []
    with c:
        for r in rows:
            t = json.loads(r["data"])
            them = t["opponent"]["tag"] if t["clan"]["tag"] == tag else t["clan"]["tag"]
            x = next((w for w in log if (w.get("opponent") or {}).get("tag") == them), None)
            if x:
                for side, src in ((t["clan"], x.get("clan") or {}), (t["opponent"], x.get("opponent") or {})):
                    side.update({k: src[k] for k in ("stars", "destructionPercentage") if src.get(k) is not None})
            t.update(state="warEnded", partial=True)
            store_clan_war(c, t, tag, r["kind"])


def forecast_rows(c, tag):
    data = league_data(c)
    saved = meta_get(c, "model_hp", {})
    data.update(sigma=saved.get("sigma"), calib=saved.get("calib"))
    L = meta_get(c, f"liga_data:{tag}")
    if L:
        data["rows"] = modelo.merge(data["rows"], modelo.rows_from_league(L))
    return data, L


def refresh_forecasts(c, tag, on):
    """Predice las guerras que aún no lo están, de la más reciente a la más antigua, y cierra las que han terminado."""
    rows = c.execute("SELECT end_ts, kind, state, data, forecast, review FROM battles ORDER BY (state='warEnded'), end_ts DESC").fetchall()
    todo = [r for r in rows if not r["review"]]
    if not todo:
        return
    data, L = forecast_rows(c, tag)
    cfg = liga_cfg(tag)
    skip = ((set(liga.auto_inactive(L, tag)) if L else set()) - set(cfg.get("si") or ())) | set(cfg.get("no") or ())
    stop = time.time() + PRED_SECONDS
    for i, r in enumerate(todo):
        on("batallas", .9 * i / len(todo), f"guerra {i + 1} de {len(todo)}")
        war = prediccion.standard(json.loads(r["data"]), tag, r["kind"])
        if not war["a"]["members"] or not war["b"]["members"]:
            continue
        ended = r["state"] == "warEnded"
        snap = json.loads(r["forecast"]) if r["forecast"] else None
        if not snap or snap["sig"] != prediccion.signature(war):      # si cambió la alineación se repite: sigue usando solo lo anterior
            if time.time() > stop:
                continue
            snap = prediccion.forecast(war, tag, data, seed=f"{tag}|{r['end_ts']}", inactive=() if ended else skip)
        with c:
            if ended:        # ya no hace falta seguirla: solo se conserva lo que se dijo y cómo salió
                c.execute("UPDATE battles SET forecast=?, review=? WHERE end_ts=?", (json.dumps({"before": snap["before"]}), json.dumps(prediccion.finished(war, snap), ensure_ascii=False), r["end_ts"]))
            else:
                c.execute("UPDATE battles SET forecast=? WHERE end_ts=?", (json.dumps(snap), r["end_ts"]))


def active_battle(c):
    """La guerra que importa ahora: la que está en juego y, si no hay, la que esté en preparación."""
    now = time.time()
    return c.execute("SELECT * FROM battles WHERE state IN ('inWar','preparation') AND end_ts>=? ORDER BY (state!='inWar'), end_ts LIMIT 1", (now,)).fetchone()


def battle_now(c, tag, r, raw=None):
    t = raw or json.loads(r["data"])
    t["round"], t["tag"] = t.get("round") or json.loads(r["data"]).get("round"), t.get("tag") or json.loads(r["data"]).get("tag")
    return prediccion.battle_view(prediccion.standard(t, tag, r["kind"]), tag, json.loads(r["forecast"]) if r["forecast"] else None, time.time(), seed=f"{tag}|{r['end_ts']}")


def past_reviews(c):
    return [{**json.loads(r["review"]), "end_ts": r["end_ts"]} for r in c.execute("SELECT end_ts, review FROM battles WHERE review IS NOT NULL ORDER BY end_ts DESC")]


def refresh_battles(c, tag, progress=None):
    """Nunca tumba la recogida: lo ya guardado sigue valiendo aunque falle la guerra en curso."""
    if not api_key():
        return
    on = progress or (lambda *a, **k: None)
    on("batallas")
    error = None
    try:
        fetch_current_war(c, tag)
    except RuntimeError as e:
        error = str(e)
    try:
        close_stale(c, tag)
        r = active_battle(c)
        if r and r["kind"] == "war":      # los rivales de una guerra normal no estaban en ninguna liga: hay que conocerlos
            t = json.loads(r["data"])
            refresh_intel(c, [m["tag"] for s in (t["clan"], t["opponent"]) for m in s["members"]], lambda s, f=0, d=None: on("batallas", .3 * f, d))
        refresh_forecasts(c, tag, on)
        r = active_battle(c)
        with c:
            meta_set(c, "battle_now", battle_now(c, tag, r) if r else None)
            items = past_reviews(c)
            meta_set(c, "pred_sum", {k: prediccion.summary([x for x in items if x["kind"] == k]) for k in ("cwl", "war")})
            meta_set(c, "battle_error", error)
    except Exception as e:      # noqa: BLE001
        with c:
            meta_set(c, "battle_error", error or f"No se pudo calcular la previsión: {e}")


_live = {}                # última respuesta de la guerra en juego, por clan: la API se pide como mucho cada LIVE_SECONDS


def live_view():
    """La guerra en juego al minuto, con la previsión guardada. No entrena ni escribe nada: abrir la web no cuesta."""
    c = db()
    try:
        tag = settings().get("clan_tag")
        r = active_battle(c) if tag else None
        if not r:
            return {"battle": None}
        key = (almacen.archivo(), r["end_ts"])
        hit = _live.get(key)
        if hit and time.time() - hit[0] < LIVE_SECONDS:
            return hit[1]
        out = {"battle": None}
        if api_key():
            try:
                stored = json.loads(r["data"])
                raw = official(f"/clanwarleagues/wars/{quote(stored['tag'], safe='')}") if r["kind"] == "cwl" else official(f"/clans/{enc(tag)}/currentwar")
                if api_ts(raw.get("endTime")) == r["end_ts"]:
                    out = {"battle": battle_now(c, tag, r, trim_war(raw)), "live": True}
            except (RuntimeError, KeyError, TypeError) as e:
                out = {"battle": None, "error": str(e)}
        _live[key] = (time.time(), out)
        return out
    finally:
        c.close()


def save_liga_cfg(body):
    """Cupos de ascenso y descenso y cuentas que atacarán o no. Recalcula sin pedir nada a la API."""
    s = settings()
    tag = s.get("clan_tag")
    if not tag:
        raise ValueError("Primero hace falta el tag del clan.")
    c = db()
    try:
        L = meta_get(c, f"liga_data:{tag}")
        size = len(L["clans"]) if L else 8
        cfg = {}
        for k in ("promote", "demote"):
            v = body.get(k)
            if v is None or v == "":
                continue
            v = int(v)
            if not 0 <= v <= size // 2:
                raise ValueError(f"Los cupos van de 0 a {size // 2}.")
            cfg[k] = v
        known = {m["tag"] for x in (L["clans"] if L else []) if x["tag"] == tag for m in x["roster"]}
        for k in ("si", "no"):
            v = body.get(k) or []
            if not isinstance(v, list) or any(t not in known for t in v):
                raise ValueError("Hay una cuenta que no está inscrita en la liga.")
            cfg[k] = v
        if set(cfg.get("si", ())) & set(cfg.get("no", ())):
            raise ValueError("Una cuenta no puede atacar y no atacar a la vez.")
        raw = _raw()
        _save({**raw, "liga": {**(raw.get("liga") or {}), tag: cfg}})
        if L:
            P = Progress("admin", first="modelo")
            try:
                with c:
                    build_league(c, tag, L, P)
            except Exception as e:
                P.finish(False, str(e))
                raise
            P("publicar")
            c.close()
            almacen.publicar_db()
            P.finish()
            return
    finally:
        c.close()
    almacen.publicar_db()


def escenarios_view():
    c = db()
    try:
        out = {"meta": meta_info(c)}
        tag = out["meta"]["clan_tag"]
        if not tag:
            return out
        view = meta_get(c, f"liga:{tag}")
        roster = {m["tag"] for m in (view or {}).get("bench", {}).get("roster", [])}
        cards = {}
        for p in load_plays(c, tag, "all"):
            cards.setdefault(p["player"], []).append(p)
        members = members_state(c, tag)
        spare = [{"tag": t, "name": m["name"], "th": m["th"], "index": scorecard(cards[t])["index"] if t in cards else None}
                 for t, m in members.items() if t not in roster]
        spare.sort(key=lambda x: (-(x["th"] or 0), -(x["index"] or 0)))
        off = meta_get(c, f"liga_off:{tag}", False)
        battle = meta_get(c, "battle_now")
        if battle and battle["ends"] < time.time():      # la recogida la vio en juego, pero ya ha terminado
            battle = None
        # lo que manda es en qué está el clan ahora: una guerra normal, una liga o nada
        mode = "guerra" if battle and battle["kind"] == "war" else "liga" if view and not off else "nada"
        kind = "war" if mode == "guerra" else "cwl" if mode == "liga" else None
        past = past_reviews(c)
        summ = meta_get(c, "pred_sum") or {}
        if not kind:                                     # sin nada en juego, lo último que jugó
            kind = past[0]["kind"] if past else "cwl"
        return {**out, "clan": clan_head(c, tag), "liga": view, "off": off, "liga_error": meta_get(c, f"liga_error:{tag}"), "has_key": bool(api_key()), "cfg": liga_cfg(tag), "spare": spare, "progress": progress_state(),
                "mode": mode, "battle": battle, "battle_error": meta_get(c, "battle_error"), "past": [x for x in past if x["kind"] == kind][:PAST_SHOWN], "past_kind": kind, "summary": summ.get(kind)}
    finally:
        c.close()


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


def league_pcts(plays):
    return [a["pct"] for p in plays if p["kind"] == "cwl" for a in p["attacks"]]


def stars_given(p):
    """Estrellas que el rival saca a su aldea en una guerra: como en el juego, sólo cuenta el mejor ataque."""
    return max((d["stars"] for d in p["defenses"]), default=0)


def defense_plays(plays):
    """Guerras que cuentan para la defensa: las del clan siempre; las de otros clanes sólo si traen datos."""
    tag = settings().get("clan_tag")
    return [p for p in plays if p["clan_tag"] == tag or p["attacks"] or p["defenses"]]


def kpi_values(plays):
    avail = sum(p["per"] for p in plays)
    atk = [a for p in plays for a in p["attacks"]]
    guarded = defense_plays(plays)
    harder = [a["stars"] for p in plays for a in p["attacks"] if a["enemy_th"] and p["th"] and a["enemy_th"] >= p["th"]]
    stars = sum(a["stars"] for a in atk)
    return {"participacion": 100 * len(atk) / avail if avail else None,
            "estrellas": stars / avail if avail else None,
            "triples": 100 * sum(a["stars"] == 3 for a in atk) / len(atk) if atk else None,
            "dano_liga": mean(league_pcts(plays)),
            "dano_efectivo": sum(a["pct"] for a in atk) / avail if avail else None,
            "dano": mean([a["pct"] for a in atk]),
            "exigencia": mean(harder),
            "defensa": mean([stars_given(p) for p in guarded]),
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
    liga = league_pcts(plays)
    guarded = defense_plays(plays)
    return {"values": {k: (round(x, 2) if x is not None else None) for k, x in v.items()}, "scores": scores, "index": index,
            "level": level_of(index), "trend": trend(plays), "wars": len(plays), "avail": avail, "used": len(atk),
            "missed": avail - len(atk), "stars": sum(a["stars"] for a in atk), "few": avail < MIN_ATTACKS,
            "liga_total": round(sum(liga), 1), "liga_attacks": len(liga),
            "def_total": sum(stars_given(p) for p in guarded), "def_max": 3 * len(guarded),
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
    act, battle = active_battle(c), None
    if act:
        t = json.loads(act["data"])
        me, ot = (t["clan"], t["opponent"]) if t["clan"]["tag"] == tag else (t["opponent"], t["clan"])
        battle = ({m["tag"] for m in me.get("members") or []}, ot, "cwl" if act["kind"] == "cwl" else "random", act["end_ts"])
    for r in c.execute("SELECT * FROM players WHERE roster=1"):
        live = live_wars(r, tag)
        for w in live:
            w["rival_name"] = names.get(w["rival"])
        if battle and r["tag"] in battle[0]:      # ClashKing puede no seguir este clan: la guerra en curso también sale de la oficial
            if not any(w["rival"] == battle[1]["tag"] for w in live):
                live.append({"type": battle[2], "ends": battle[3], "rival": battle[1]["tag"], "rival_name": battle[1]["name"]})
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
    _update_clan(settings()["clan_tag"], groups=[g for g in out if g["accounts"]])


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
            **{k: sum(c[k] for c in cards) for k in ("wars", "avail", "used", "missed", "stars", "wins", "loses", "liga_total", "liga_attacks", "def_total", "def_max")}}


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
    return {"clan_tag": s.get("clan_tag"), "clans": [{"tag": r["tag"], "name": r.get("name") or r["tag"]} for r in clan_list(s)], "stamp": meta_get(c, "stamp"), "full_ts": meta_get(c, "full_ts"), "error": meta_get(c, "last_error"),
            "syncing": bool(syncing and time.time() - syncing["ts"] < 600), "next": next_daily(), "log": meta_get(c, "sync_log", [])[:5],
            "official": bool(meta_get(c, "official_ts")), "has_key": bool(api_key()), "proxy_ip": PROXY_IP, "cloud": almacen.EN_NUBE}


def maybe_light_sync(c):
    if not almacen.EN_NUBE and settings().get("clan_tag") and time.time() - (meta_get(c, "light_ts") or 0) > LIGHT_S and not running().locked():
        start_sync(light=True, source="panel")


def clan_head(c, tag):
    w = c.execute("SELECT clan_name FROM plays WHERE clan_tag=? ORDER BY end_ts DESC LIMIT 1", (tag,)).fetchone()
    s = c.execute("SELECT * FROM seasons WHERE clan_tag=? ORDER BY season DESC LIMIT 1", (tag,)).fetchone()
    known = next((r.get("name") for r in clan_list() if r["tag"] == tag), None)
    return {"tag": tag, "name": w["clan_name"] if w else known or tag, "season": dict(s) if s else None}


def status():
    c = db()
    try:
        maybe_light_sync(c)
        return {**meta_info(c), "progress": progress_state()}
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


def war_predictions(c):
    """Por guerra: lo previsto y el % de pleno de cada ataque, para enseñarlo junto al resultado."""
    return {x["end_ts"]: {"before": x["before"], "t": x["t"], "p": {r["o"]: r["p3"] for r in x["rows"]}} for x in past_reviews(c)}


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
                    "attacks": [{k: a[k] for k in ("ord", "stars", "pct", "enemy", "enemy_th", "enemy_pos", "duration")} for a in p["attacks"]],
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
                "owners": owner_rows(c, groups, plays), "owner_names": owner_names(groups), "pred": war_predictions(c), "battle": meta_get(c, "battle_now")}
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
            cell = row["cells"].setdefault(month_of(p["end_ts"]), {"stars": 0, "avail": 0, "used": 0, "pct": 0})
            cell["avail"] += p["per"]
            cell["used"] += len(p["attacks"])
            cell["stars"] += sum(a["stars"] for a in p["attacks"])
            cell["pct"] = round(cell["pct"] + sum(a["pct"] for a in p["attacks"]), 1)
        table = sorted(matrix.values(), key=lambda r: -sum(x["stars"] for x in r["cells"].values()))
        detail = wars_view("cwl")
        groups = account_groups(c)
        by_month = {}
        for p in plays:
            by_month.setdefault(month_of(p["end_ts"]), []).append(p)
        return {**out, "clan": clan_head(c, tag), "seasons": seasons, "matrix": table, "rounds": detail["wars"], "heat": detail["heat"],
                "owners": {m: owner_rows(c, groups, v) for m, v in by_month.items()}, "owner_names": detail["owner_names"],
                "live": live_rounds(members_state(c, tag)), "pred": detail["pred"], "battle": detail["battle"]}
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
                     "stars": sum(a["stars"] for a in p["attacks"]), "conceded": stars_given(p),
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

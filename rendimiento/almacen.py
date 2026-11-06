"""Dónde viven los datos del clan.

- En tu PC: clan.db y clan.json, junto a este archivo.
- En Vercel el disco se borra, así que ambos están en Vercel Blob (almacén privado). Cada función copia
  clan.db a /tmp y lo consulta como siempre; la recogida lo vuelve a subir entero al terminar.
  Con una recogida al día basta, y las consultas siguen siendo las mismas.
- Cada clan tiene su propia base (`usar`): así dos recogidas nunca se pisan al subir, y un clan no ve los datos de otro.
  El primero sigue en clan.db; los demás van en clan.db.<tag> en el PC y en clan/<tag>.db en el almacén.

Vercel reparte las peticiones entre varias instancias y el Blob tiene caché: head_blob siempre dice cuál es
la versión actual, pero get_blob puede devolver una anterior durante un rato tras escribir. Por eso aquí se
pregunta primero con head y se pide con get hasta recibir justo esa versión. El avance cambia cada pocos segundos
y no puede esperar a la caché: viaja también en el tipo del archivo, que head siempre da al día.
"""
import contextvars
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import quote, unquote

ROOT = Path(__file__).parent
EN_NUBE = bool(os.environ.get("VERCEL"))
SETTINGS = Path(os.environ.get("CLAN_SETTINGS", ROOT / "clan.json"))
DB = Path(os.environ.get("CLAN_DB", ROOT / "clan.db"))
PRIMERO = "clan"                 # archivo del clan que ya había antes de poder seguir varios
BLOB_AJUSTES = "clan/ajustes.json"
TTL_DB, TTL_AJUSTES = 180, 20    # cada consulta al almacén gasta cuota: los datos cambian poco
GET_INTENTOS, GET_ESPERA = 12, 0.5
ESCRITO_HACE = 30                # si la última escritura es de hace menos, la recogida puede seguir viva
_lock = threading.RLock()
_clan = contextvars.ContextVar("clan", default=None)     # cada petición lleva el suyo, aunque compartan instancia
_copias, _progresos = {}, {}
_ajustes = {"datos": None, "etag": None, "visto": 0.0, "forzado": 0.0}


def usar(archivo):
    """Fija el clan con el que trabaja esta petición."""
    _clan.set(archivo)


def archivo():
    return _clan.get() or PRIMERO


def _local(f):
    return DB if f == PRIMERO else Path(f"{DB}.{f}")


def _tmp(f):
    return Path(tempfile.gettempdir()) / f"{f}.db"


def _blob_db(f):
    return f"clan/{f}.db"


def _blob_progreso(f):
    return "clan/progreso.json" if f == PRIMERO else f"clan/progreso-{f}.json"


def _ruta_progreso(f):
    return Path(f"{_local(f)}.progreso")


def _copia(f):
    return _copias.setdefault(f, {"etag": None, "visto": 0.0})


def _progreso(f):
    return _progresos.setdefault(f, {"datos": None, "etag": None})


def _meta(pathname):
    """Lo que el almacén sabe ahora de un archivo: esto nunca viene de la caché. None si no existe."""
    from vercel.blob.sync import BlobNotFoundError, head_blob
    try:
        return head_blob(pathname)
    except BlobNotFoundError:
        return None


def _limpio(etag):
    return str(etag or "").removeprefix("W/").strip('"')


def _bajar(m):
    """Contenido de esa versión exacta; si la caché sigue dando otra, espera y reintenta."""
    from vercel.blob.sync import get_blob
    for intento in range(GET_INTENTOS):
        r = get_blob(m.pathname, access="private")
        if _limpio(r.metadata.etag) == _limpio(m.etag):
            return bytes(r.body)
        time.sleep(GET_ESPERA)
    raise RuntimeError("El almacén aún no sirve la última versión; reinténtalo en unos segundos.")


def _bajar_progreso(m):
    """Por si el tipo del archivo no trae el avance: vale esa versión o una posterior, nunca una anterior."""
    from vercel.blob.sync import get_blob
    escrito = m.uploaded_at.timestamp()
    for intento in range(3):
        d = json.loads(get_blob(m.pathname, access="private").body)
        if d.get("updated", 0) >= escrito - 15:
            return d
        time.sleep(.3)
    raise RuntimeError("Versión vieja del avance.")


def _tipo_con(p):
    return "application/json; d=" + quote(json.dumps(p, separators=(",", ":")), safe="")


def _tipo_datos(m):
    _, _, d = (getattr(m, "content_type", None) or "").partition("; d=")
    return json.loads(unquote(d)) if d else None


def guardar_progreso(p, f=None):
    """Avance de una recogida. Está aparte de la base de datos para que lo vea cualquier instancia, y si falla da igual:
    nunca debe parar el trabajo que está contando. Llega también desde hilos: `f` dice de qué clan es."""
    f = f or archivo()
    try:
        data = json.dumps(p, ensure_ascii=False).encode("utf-8")
        if EN_NUBE:
            try:
                etag = subir(_blob_progreso(f), data, _tipo_con(p))
            except Exception:   # noqa: BLE001 — sin metadatos se sigue leyendo del contenido
                etag = subir(_blob_progreso(f), data, "application/json")
            _progreso(f).update(datos=p, etag=etag)
        else:
            ruta = _ruta_progreso(f)
            tmp = ruta.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(ruta)
    except Exception:           # noqa: BLE001
        pass


def leer_progreso():
    f = archivo()
    x = _progreso(f)
    m = None
    try:
        if not EN_NUBE:
            ruta = _ruta_progreso(f)
            return json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else {}
        m = _meta(_blob_progreso(f))
        if not m:
            return {}
        d = _tipo_datos(m)
        if d is not None:
            x.update(datos=d, etag=m.etag)
            return d
        if m.etag != x["etag"]:
            x.update(datos=_bajar_progreso(m), etag=m.etag)
        return x["datos"] or {}
    except Exception:           # noqa: BLE001 — un fallo al leer no significa que haya terminado
        d = x["datos"] or {}
        if m and time.time() - m.uploaded_at.timestamp() < ESCRITO_HACE:     # hay una versión nueva que aún no se puede leer: lo que tenemos ya no vale
            return {**d, "updated": m.uploaded_at.timestamp()} if d.get("active") else {"active": True, "pct": 0, "stage": "recoger", "label": "Calculando", "detail": None, "source": None, "step": 1, "steps": d.get("steps") or [], "updated": m.uploaded_at.timestamp()}
        return d or {"unknown": True}


def refrescar_db():
    """Tras una recogida: la próxima consulta mira si hay datos nuevos sin esperar a que caduque la copia."""
    with _lock:
        x = _copia(archivo())
        if time.time() - x["visto"] > 1:
            x["visto"] = 0.0


def subir(pathname, data, content_type):
    from vercel.blob.sync import put_blob
    return put_blob(pathname, data, access="private", content_type=content_type, allow_overwrite=True, add_random_suffix=False).etag


def ruta_db():
    """Ruta de la base de datos, al día. Si no se sabe qué hay en el almacén y aún no hay copia, falla:
    seguir con una base vacía acabaría pisando el histórico en la siguiente recogida."""
    f = archivo()
    if not EN_NUBE:
        return _local(f)
    with _lock:
        x = _copia(f)
        if time.time() - x["visto"] > TTL_DB:
            try:
                m = _meta(_blob_db(f))
                if m and m.etag != x["etag"]:
                    tmp = _tmp(f).with_suffix(".nuevo")
                    tmp.write_bytes(_bajar(m))
                    tmp.replace(_tmp(f))
                    x["etag"] = m.etag
                x["visto"] = time.time()
            except Exception:
                if x["etag"] is None:
                    raise
    return _tmp(f)


def publicar_db():
    """Tras una recogida, sube la base entera. En el PC no hace nada."""
    if EN_NUBE:
        f = archivo()
        with _lock:
            x = _copia(f)
            x["etag"] = subir(_blob_db(f), _tmp(f).read_bytes(), "application/octet-stream")
            x["visto"] = time.time()


def leer_ajustes(fresco=False):
    """fresco=True comprueba el almacén ahora mismo; si falla lanza el error en vez de seguir con datos viejos."""
    if not EN_NUBE:
        try:
            return json.loads(SETTINGS.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
    with _lock:
        ahora = time.time()
        forzar = fresco and ahora - _ajustes["forzado"] >= 1     # un intento por segundo: no se gasta cuota por ráfagas
        if _ajustes["datos"] is None or forzar or ahora - _ajustes["visto"] > TTL_AJUSTES:
            try:
                m = _meta(BLOB_AJUSTES)
                etag = m.etag if m else None
                if _ajustes["datos"] is None or etag != _ajustes["etag"]:
                    _ajustes.update(datos=json.loads(_bajar(m)) if m else {}, etag=etag)
                _ajustes.update(visto=time.time(), forzado=time.time() if forzar else _ajustes["forzado"])
            except Exception:
                if fresco or _ajustes["datos"] is None:
                    raise
        return {"clan_tag": os.environ.get("CLAN_TAG"), **_ajustes["datos"]}    # el panel admin manda sobre la variable


def guardar_ajustes(s):
    if not EN_NUBE:
        tmp = SETTINGS.with_suffix(".tmp")
        tmp.write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(SETTINGS)
        return
    with _lock:
        etag = subir(BLOB_AJUSTES, json.dumps(s, ensure_ascii=False).encode("utf-8"), "application/json")
        _ajustes.update(datos=s, etag=etag, visto=time.time())

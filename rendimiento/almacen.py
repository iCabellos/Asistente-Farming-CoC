"""Dónde viven los datos del clan.

- En tu PC: clan.db y clan.json, junto a este archivo.
- En Vercel el disco se borra, así que ambos están en Vercel Blob (almacén privado). Cada función copia
  clan.db a /tmp y lo consulta como siempre; la recogida lo vuelve a subir entero al terminar.
  Con un solo clan y una recogida al día basta, y las consultas siguen siendo las mismas.
"""
import json
import os
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).parent
EN_NUBE = bool(os.environ.get("VERCEL"))
SETTINGS = Path(os.environ.get("CLAN_SETTINGS", ROOT / "clan.json"))
DB = Path(os.environ.get("CLAN_DB", ROOT / "clan.db"))
TMP_DB = Path(tempfile.gettempdir()) / "clan.db"
BLOB_DB, BLOB_AJUSTES = "clan/clan.db", "clan/ajustes.json"
TTL_DB, TTL_AJUSTES = 600, 120   # cada consulta al almacén gasta cuota: los datos sólo cambian una vez al día
_lock = threading.RLock()
_copia = {"etag": None, "visto": 0.0}
_ajustes = {"datos": None, "visto": 0.0}


def _etag(pathname):
    from vercel.blob.sync import BlobNotFoundError, head_blob
    try:
        return head_blob(pathname).etag
    except BlobNotFoundError:
        return None


def _bajar(pathname):
    from vercel.blob.sync import get_blob
    return bytes(get_blob(pathname, access="private").body)


def subir(pathname, data, content_type):
    from vercel.blob.sync import put_blob
    return put_blob(pathname, data, access="private", content_type=content_type, allow_overwrite=True, add_random_suffix=False).etag


def ruta_db():
    """Ruta de la base de datos, al día. Si no se sabe qué hay en el almacén y aún no hay copia, falla:
    seguir con una base vacía acabaría pisando el histórico en la siguiente recogida."""
    if not EN_NUBE:
        return DB
    with _lock:
        if time.time() - _copia["visto"] > TTL_DB:
            try:
                etag = _etag(BLOB_DB)
                if etag and etag != _copia["etag"]:
                    tmp = TMP_DB.with_suffix(".nuevo")
                    tmp.write_bytes(_bajar(BLOB_DB))
                    tmp.replace(TMP_DB)
                    _copia["etag"] = etag
                _copia["visto"] = time.time()
            except Exception:
                if _copia["etag"] is None:
                    raise
    return TMP_DB


def publicar_db():
    """Tras una recogida, sube la base entera. En el PC no hace nada."""
    if EN_NUBE:
        with _lock:
            _copia["etag"] = subir(BLOB_DB, TMP_DB.read_bytes(), "application/octet-stream")
            _copia["visto"] = time.time()


def leer_ajustes():
    if not EN_NUBE:
        try:
            return json.loads(SETTINGS.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
    with _lock:
        if _ajustes["datos"] is None or time.time() - _ajustes["visto"] > TTL_AJUSTES:
            _ajustes["datos"] = json.loads(_bajar(BLOB_AJUSTES)) if _etag(BLOB_AJUSTES) else {}
            _ajustes["visto"] = time.time()
        return {**_ajustes["datos"], "clan_tag": os.environ.get("CLAN_TAG")}


def guardar_ajustes(s):
    if not EN_NUBE:
        tmp = SETTINGS.with_suffix(".tmp")
        tmp.write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(SETTINGS)
        return
    limpio = {k: v for k, v in s.items() if k not in ("api_key", "clan_tag")}   # esos dos van en variables de entorno
    with _lock:
        subir(BLOB_AJUSTES, json.dumps(limpio, ensure_ascii=False).encode("utf-8"), "application/json")
        _ajustes.update(datos=limpio, visto=time.time())

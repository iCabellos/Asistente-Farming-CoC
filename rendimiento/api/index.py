"""API del panel. En Vercel es una sola función; en el PC la sirve local.py con el mismo código.

Leer es libre. En la nube, cambiar algo pide usuario y contraseña de administrador (de inicio admin/admin,
se cambia en el panel) y el cron pide CRON_SECRET; sin esa variable el cron se rechaza.
"""
import hmac
import json
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import almacen  # noqa: E402
import clan  # noqa: E402


def same(a, b):
    return bool(b) and hmac.compare_digest(a.encode(), b.encode())


class handler(BaseHTTPRequestHandler):
    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def route(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        return q.pop("ruta", None) or u.path.removeprefix("/api/"), q

    def is_admin(self):
        if not almacen.EN_NUBE:
            return True
        user, _, password = unquote(self.headers.get("X-Clave", "")).partition(":")
        return clan.check_admin(user, password)

    def cron(self, q):
        secret = os.environ.get("CRON_SECRET")
        if not secret or not same(self.headers.get("Authorization", ""), f"Bearer {secret}"):
            return self.send_json({"error": "No autorizado."}, 401)
        rows = clan.clan_list()
        if q.get("clan") or len(rows) < 2:
            code = clan.daily(retries=2, wait=20)
            return self.send_json({"ok": code == 0}, 200 if code == 0 else 500)   # el 500 deja la recogida fallida marcada en Vercel
        # varios clanes: cada uno se recoge en su propia ejecución, con sus 5 minutos, y uno lento no retrasa a los demás
        host = os.environ.get("VERCEL_PROJECT_PRODUCTION_URL") or self.headers.get("Host")

        def one(r):
            url = f"https://{host}/api/cron?clan={quote(r['tag'][1:])}"
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={"Authorization": f"Bearer {secret}", "User-Agent": "coc-rendimiento"}), timeout=295) as x:
                    return x.status == 200
            except OSError:
                return False
        with ThreadPoolExecutor(len(rows)) as ex:
            done = list(ex.map(one, rows))
        self.send_json({"ok": all(done), "clans": len(rows), "failed": done.count(False)}, 200 if all(done) else 500)

    def do_GET(self):
        path, q = self.route()
        try:
            clan.use_clan(q.get("clan"))
            if q.get("fresh"):
                almacen.leer_ajustes(fresco=True)      # el panel admin debe ver lo que acaba de guardar
                almacen.refrescar_db()                 # y quien vio acabar una recogida, sus datos nuevos
            args = (q.get("kind", "all"), int(q.get("days", 0)))
            if path == "status":
                return self.send_json(clan.status())
            if path == "progress":
                return self.send_json(clan.progress_state())
            if path == "overview":
                return self.send_json(clan.overview(*args))
            if path == "wars":
                return self.send_json(clan.wars_view(*args))
            if path == "leagues":
                return self.send_json(clan.leagues_view())
            if path == "escenarios":
                return self.send_json(clan.escenarios_view())
            if path == "vivo":
                return self.send_json(clan.live_view())
            if path == "player":
                return self.send_json(clan.player_view(q.get("tag"), *args, q.get("scope", "clan")))
            if path == "owner":
                return self.send_json(clan.owner_view(q.get("id"), *args, q.get("scope", "clan")))
            if path == "cron":
                return self.cron(q)
        except ValueError as e:
            return self.send_json({"error": str(e)}, 400)
        self.send_json({"error": "No existe."}, 404)

    def do_POST(self):
        path, q = self.route()
        if path not in ("login", "admin", "groups", "sync", "tag", "key", "password", "liga", "clans"):
            return self.send_json({"error": "No existe."}, 404)
        if not self.is_admin():
            return self.send_json({"error": "Usuario o contraseña incorrectos."}, 401)
        try:
            clan.use_clan(q.get("clan"))
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            if path == "admin":
                return self.send_json(clan.admin_info())
            if path == "groups":
                clan.save_groups(body.get("groups"))
            elif path == "sync":
                started = not clan.running().locked() and not clan.progress_state().get("active")   # puede ir en otra instancia
                if started:
                    clan.start_sync()
                return self.send_json({"started": started})
            elif path == "tag":
                clan.save_tag(body.get("clan_tag"))
            elif path == "clans":
                if body.get("action") == "remove":
                    clan.remove_clan(body.get("tag"))
                else:
                    return self.send_json(clan.add_clan(body.get("tag")))
            elif path == "key":
                clan.save_key(body.get("key"))
            elif path == "password":
                clan.set_admin(body.get("user"), body.get("password"))
            elif path == "liga":
                clan.save_liga_cfg(body)
            return self.send_json({"ok": True})
        except (ValueError, RuntimeError, AttributeError) as e:
            return self.send_json({"error": str(e)}, 400)

    def log_message(self, *_):
        pass

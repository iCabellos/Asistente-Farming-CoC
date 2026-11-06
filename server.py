"""Panel del asistente: vídeo del emulador, rutina, almacenes, botín y diario.  http://localhost:8000"""
import io
import json
import os
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import av

ROOT = Path(__file__).parent
RENDIMIENTO_URL = os.environ.get("COC_RENDIMIENTO_URL", "https://coc-rendimiento-clan.vercel.app")   # la web del clan
LOG = ROOT / "log.jsonl"
LOOT = ROOT / "loot.jsonl"   # botín conseguido por ataque
def _cfg():
    try:
        return json.loads((ROOT / "asistente" / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


ADB = _cfg().get("adb") or shutil.which("adb") or "adb"
SERIAL = _cfg().get("serial", "127.0.0.1:5555")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

frame_jpeg, frame_seq = None, 0


def video():
    """H.264 de screenrecord (se corta cada 3 min y se relanza) decodificado a JPEG."""
    global frame_jpeg, frame_seq
    while True:
        p = subprocess.Popen([ADB, "-s", SERIAL, "exec-out", "screenrecord", "--output-format=h264",
                              "--size", "1600x900", "--bit-rate", "8000000", "-"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
        codec = av.CodecContext.create("h264", "r")
        try:
            while data := p.stdout.read1(1 << 16):
                for pkt in codec.parse(data):
                    for fr in codec.decode(pkt):
                        buf = io.BytesIO()
                        fr.to_image().save(buf, "JPEG", quality=82)
                        frame_jpeg, frame_seq = buf.getvalue(), frame_seq + 1
        except Exception:
            pass
        finally:
            p.kill()
        time.sleep(0.5)


def read_log(after):
    if not LOG.exists():
        return []
    out = []
    for i, line in enumerate(LOG.read_text(encoding="utf-8").splitlines()):
        if i >= after and line.strip():
            try:
                out.append({"id": i + 1, **json.loads(line)})
            except json.JSONDecodeError:
                pass
    return out[-300:]


ASISTENTE_DIR = ROOT / "asistente"


CONFIG = ASISTENTE_DIR / "config.json"
TASKS = {"fill_storages": "Llenar almacenes", "farm": "Farmear", "builder_base": "Llenar aldea nocturna",
         "build": "Mejorar lo recomendado"}


def routine_info():
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    try:
        st = json.loads((ASISTENTE_DIR / "estado.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    storage = {n: {"capacity": a.get("capacity"), "builder_capacity": a.get("builder_capacity"),
                   "full_ratio": a.get("full_ratio", cfg.get("full_ratio", 0.9)),
                   "dark_full_ratio": a.get("dark_full_ratio", cfg.get("dark_full_ratio", 0.5)),
                   "builder_full_ratio": a.get("builder_full_ratio", a.get("full_ratio", 0.9))}
               for n, a in cfg.get("accounts", {}).items()}
    return {"routine": cfg.get("routine", []), "accounts": list(cfg.get("accounts", {})), "tasks": TASKS,
            "storage": storage,
            "labels": {n: a.get("label", n) for n, a in cfg.get("accounts", {}).items()},
            "state": st, "running": (ASISTENTE_DIR / "ENABLED").exists(), "now": time.time(),
            "paused_owner": _pause_until() > time.time()}


def _pause_until():
    try:
        return float((ASISTENTE_DIR / "PAUSA_DUENO").read_text())
    except (OSError, ValueError):
        return 0


def save_targets(targets):
    """{cuenta: {full_ratio, dark_full_ratio, builder_full_ratio}} en tanto por uno (0.3–1)."""
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    for acc, t in targets.items():
        if acc not in cfg["accounts"]:
            raise ValueError(f"cuenta desconocida: {acc}")
        for k in ("full_ratio", "dark_full_ratio", "builder_full_ratio"):
            if k in t:
                cfg["accounts"][acc][k] = round(max(0.3, min(1.0, float(t[k]))), 2)
    tmp = CONFIG.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(CONFIG)


def save_routine(routine):
    """Valida y guarda la rutina en config.json (el asistente la relee en cada paso)."""
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    clean = []
    for s in routine:
        acc, task = s.get("account"), s.get("task")
        if acc not in cfg["accounts"] or task not in TASKS:
            raise ValueError(f"paso no válido: {s}")
        step = {"account": acc, "task": task}
        if task in ("farm", "builder_base"):
            step["attacks"] = max(1, min(20, int(s.get("attacks") or (10 if task == "builder_base" else 6))))
        if s.get("enabled") is False:
            step["enabled"] = False
        clean.append(step)
    if not clean:
        raise ValueError("la rutina no puede quedar vacía")
    cfg["routine"] = clean
    tmp = CONFIG.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(CONFIG)
    return clean


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        u = urlparse(self.path)
        if u.path == "/routine":
            try:
                n = int(self.headers.get("Content-Length", 0))
                save_routine(json.loads(self.rfile.read(n) or b"[]"))
                return self.send_json(routine_info())
            except (ValueError, TypeError, json.JSONDecodeError) as e:
                return self.send_json({"error": str(e)}, 400)
        if u.path == "/targets":
            try:
                n = int(self.headers.get("Content-Length", 0))
                save_targets(json.loads(self.rfile.read(n) or b"{}"))
                return self.send_json(routine_info())
            except (ValueError, TypeError, json.JSONDecodeError) as e:
                return self.send_json({"error": str(e)}, 400)
        if u.path == "/asistente/skip_rest":
            (ASISTENTE_DIR / "SKIP_REST").touch()
            return self.send_json(routine_info())
        if u.path == "/asistente/start":
            (ASISTENTE_DIR / "STOP").unlink(missing_ok=True)
            (ASISTENTE_DIR / "ENABLED").touch()          # el vigilante lo arranca y lo mantiene vivo
        elif u.path == "/asistente/stop":
            (ASISTENTE_DIR / "ENABLED").unlink(missing_ok=True)
            (ASISTENTE_DIR / "STOP").touch()             # parada limpia entre acciones
        body = json.dumps({"running": (ASISTENTE_DIR / "ENABLED").exists()}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/":
            body = (ROOT / "index.html").read_bytes().replace(b"{{RENDIMIENTO_URL}}", RENDIMIENTO_URL.encode())
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif u.path == "/stream":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=f")
            self.end_headers()
            last = -1
            try:
                while True:
                    if frame_jpeg is not None and frame_seq != last:
                        last, f = frame_seq, frame_jpeg
                        self.wfile.write(b"--f\r\nContent-Type: image/jpeg\r\nContent-Length: " +
                                         str(len(f)).encode() + b"\r\n\r\n" + f + b"\r\n")
                    time.sleep(0.04)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
        elif u.path == "/frame.jpg":
            f = frame_jpeg
            if f is None:
                self.send_error(503)
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(f)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Seq", str(frame_seq))
            self.end_headers()
            self.wfile.write(f)
        elif u.path == "/routine":
            self.send_json(routine_info())
        elif u.path == "/asistente":
            body = json.dumps({"running": (ASISTENTE_DIR / "ENABLED").exists()}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        elif u.path == "/loot":
            rows = []
            if LOOT.exists():
                for line in LOOT.read_text(encoding="utf-8").splitlines():
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
            body = json.dumps(rows, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        elif u.path == "/log":
            after = int(parse_qs(u.query).get("after", ["0"])[0])
            body = json.dumps(read_log(after), ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)


if __name__ == "__main__":
    threading.Thread(target=video, daemon=True).start()
    print(f"Panel: http://localhost:{os.environ.get('COC_PORT', '8000')}/")
    port = int(os.environ.get("COC_PORT", "8000"))
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()

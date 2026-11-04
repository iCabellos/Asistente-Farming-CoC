"""Vigilante: mantiene vivos el emulador, Ollama, el visor (server.py) y el asistente. Sin ninguna ventana.

- Todo se lanza con pythonw.exe (sin consola): no aparece ninguna ventana que cerrar.
- Si el visor cae, lo relanza. Si el asistente está ACTIVADO (asistente/ENABLED) y cae, lo relanza.
- Si BlueStacks no está abierto, lo arranca (oculto). Si Ollama no responde, lo arranca.
- Si el LLM supera 9 GB de RAM, lo descarga (se recarga solo en la siguiente consulta).
- Si el asistente lleva 10 min sin escribir nada en su registro, lo considera colgado y lo reinicia.
Se arranca con  arrancar.bat.
"""
import json
import shutil
import subprocess
import time
from pathlib import Path

import httpx
import psutil

ROOT = Path(__file__).parent
ASIS = ROOT / "asistente"
PYW = str(ROOT / ".venv" / "Scripts" / "pythonw.exe")
try:
    _CFG = json.loads((ASIS / "config.json").read_text(encoding="utf-8"))
except (OSError, ValueError):
    _CFG = {}
OLLAMA = (_CFG.get("ollama_exe") or shutil.which("ollama")
          or str(Path.home() / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe"))
PLAYER = _CFG.get("bluestacks_player") or str(Path("C:/Program Files/BlueStacks_nxt/HD-Player.exe"))
INSTANCE = _CFG.get("bluestacks_instance", "Pie64")
MODEL = _CFG.get("model", "qwen2.5vl:7b")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DETACHED = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
STALL_SECONDS = 600


def log(kind, text):
    with open(ROOT / "log.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.time(), "kind": kind, "action": "", "text": text, "pts": None},
                           ensure_ascii=False) + "\n")


def procs(script):
    out = []
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            cmd = " ".join(p.info["cmdline"] or [])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if script in cmd and "vigilante" not in cmd:
            out.append(p)
    # el pythonw del venv es un lanzador que arranca el pythonw real como hijo: cuenta como uno solo
    pids = {p.pid for p in out}
    roots = []
    for p in out:
        try:
            if p.ppid() not in pids:
                roots.append(p)
        except psutil.NoSuchProcess:
            pass
    return roots


def launch(script, cwd, logfile):
    subprocess.Popen([PYW, "-u", script], cwd=cwd, creationflags=DETACHED,
                     stdout=open(logfile, "a", encoding="utf-8"), stderr=subprocess.STDOUT,
                     stdin=subprocess.DEVNULL)


def kill(ps):
    for p in ps:
        try:
            for c in p.children(recursive=True):
                c.kill()
            p.kill()
        except psutil.NoSuchProcess:
            pass


def by_name(name):
    return [p for p in psutil.process_iter(["name"]) if (p.info["name"] or "").lower() == name.lower()]


def ensure_emulator():
    if not by_name("HD-Player.exe") and Path(PLAYER).exists():
        subprocess.Popen([PLAYER, "--instance", INSTANCE], creationflags=DETACHED)
        log("warn", "Vigilante: BlueStacks no estaba abierto; lo arranco.")
        time.sleep(60)


def ensure_ollama():
    try:
        httpx.get("http://127.0.0.1:11434/api/tags", timeout=5)
    except httpx.HTTPError:
        subprocess.Popen([OLLAMA, "serve"], creationflags=DETACHED | NO_WINDOW,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log("warn", "Vigilante: Ollama no respondía; lo arranco.")
        time.sleep(5)


def llama_gb():
    return sum(p.memory_info().private for p in by_name("llama-server.exe")) / 2 ** 30


def main():
    log("think", "Vigilante en marcha.")
    while True:
        try:
            if not procs("server.py"):
                launch("server.py", ROOT, ROOT / "server.out")
                log("warn", "Vigilante: el visor estaba caído; relanzado.")
            if (ASIS / "ENABLED").exists():
                ensure_emulator()
                ensure_ollama()
                procesos = procs("asistente.py")
                out = ASIS / "asistente.out"
                stalled = procesos and out.exists() and time.time() - out.stat().st_mtime > STALL_SECONDS
                if stalled:
                    kill(procesos)
                    log("warn", "Vigilante: el asistente llevaba 10 min sin hacer nada; lo reinicio.")
                    procesos = []
                if len(procesos) > 1:
                    kill(procesos[1:])
                if not procesos:
                    (ASIS / "STOP").unlink(missing_ok=True)
                    launch("asistente.py", ASIS, out)
                    log("warn", "Vigilante: asistente lanzado.")
            else:
                kill(procs("asistente.py")) if (ASIS / "STOP").exists() and time.time() - (ASIS / "STOP").stat().st_mtime > 120 else None
            if llama_gb() > 9:
                httpx.post("http://127.0.0.1:11434/api/generate",
                           json={"model": MODEL, "keep_alive": 0}, timeout=30)
                log("warn", "Vigilante: el LLM ocupaba más de 9 GB; descargado para liberar memoria.")
        except Exception as e:
            log("warn", f"Vigilante: {e}")
        time.sleep(20)


if __name__ == "__main__":
    main()

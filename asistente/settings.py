"""Configuración del asistente: todo sale de config.json y lo que falte toma su valor por defecto.

Lo mínimo que hace falta escribir es el nombre de las cuentas:

    {"accounts": ["MiAldea", "MiSegundaAldea"]}

Con eso el asistente llena los almacenes de cada cuenta, en bucle. Todo lo demás (rutina, umbrales, tiempos,
emulador, modelo, funciones de tropas y hechizos…) es opcional: los valores por defecto están en DEFAULTS y
ACCOUNT_DEFAULTS, y cualquier clave de cuenta se puede poner una sola vez para todas en "account_defaults".
Las opciones generales también se pueden poner dentro de una cuenta para cambiarlas sólo en ella.

"advanced" cambia constantes internas (coordenadas, listas, tablas) sin tocar el código:
    "advanced": {"SPEED_BTN": [1840, 615], "vision.ALGO": 3}

Lo usan el asistente, el visor (server.py) y el vigilante, para que los tres entiendan lo mismo.
"""
import copy
import json
import os
from pathlib import Path

HERE = Path(__file__).parent
CONFIG = Path(os.environ.get("COC_CONFIG") or HERE / "config.json")

TASKS = {"fill_storages": "Llenar almacenes", "farm": "Farmear", "builder_base": "Llenar aldea nocturna",
         "build": "Mejorar lo recomendado", "walls": "Mejorar muros"}
LOOT_MODES = ("gold_and_elixir_or_dark", "gold_or_elixir")

DEFAULTS = {
    # --- conexión ---
    "adb": "adb",                                   # ruta a adb.exe; si no existe se busca en el PATH
    "serial": "127.0.0.1:5555",                     # dispositivo ADB del emulador
    "game_package": "com.supercell.clashofclans",
    "ollama": "http://127.0.0.1:11434",
    "model": "qwen2.5vl:7b",
    "model_keep_alive": "5m",
    # --- emulador y vigilante ---
    "bluestacks_player": "C:/Program Files/BlueStacks_nxt/HD-Player.exe",
    "bluestacks_instance": "Pie64",
    "emulator_args": None,                          # None = ["--instance", bluestacks_instance]
    "emulator_process": None,                       # None = el nombre del ejecutable de arriba
    "emulator_boot_seconds": 60,
    "ollama_exe": None,                             # None = se busca solo
    "model_max_ram_gb": 9,                          # por encima, el vigilante descarga el modelo
    "stall_minutes": 10,                            # sin escribir nada tanto tiempo = colgado: se reinicia
    # --- visor ---
    "panel_host": "127.0.0.1",
    "panel_port": 8000,
    "panel_video_size": "1600x900",
    "panel_video_bitrate": 8000000,
    "clan_site_url": "https://coc-rendimiento-clan.vercel.app",
    # --- rutina ---
    "rest_minutes_between_cycles": 2,
    "rest_minutes_when_full": 30,
    "owner_pause_minutes": 45,
    "donation_check_minutes": 4,
    "home_account": None,                           # None = la primera cuenta con "donor": true (o ninguna)
    "donate": True,                                 # donar lo que pidan en el clan
    "request_troops": True,                         # pedir tropas al castillo cuando es gratis
    # --- almacenes y botín ---
    "full_ratio": 0.9,
    "dark_full_ratio": 0.5,
    "min_loot_ratio": 0.035,                        # botín mínimo "auto" = esta parte de la capacidad
    "dry_attack_loot": 3000,                        # un ataque que suma menos que esto no ha sumado nada
    "dry_attacks_stop": 2,                          # tantos seguidos así = almacenes llenos
    # --- muros ---
    "walls_spend_ratio": 0.8,
    "walls_recheck_hours": 72,
    "walls_one_by_one": 10,
    "walls_busy_minutes": 15,                       # sin constructor libre: no se vuelve a mirar en este rato
    # --- batalla ---
    "hero_ability_seconds": 7,
    "stall_seconds": 15,
    "storages_model": True,
    "probe": False,
    # --- evento de tropa en masa ---
    "mass_event": False,
    "mass_cards": ["momma"],
    "mass_count": 25,
    "mass_stall_seconds": 30,
    "mass_walls_every": 20,
    # --- constantes internas ---
    "advanced": {},
}

ACCOUNT_DEFAULTS = {
    "max_searches": 25,
    "lightning_per_ad": 3,
    "min_loot": "auto",                             # o {"gold": N, "elixir": N, "dark": N, "mode": ...}
    "auto_build": False,
    "auto_build_until_th": 10,
}

# claves que el asistente escribe solo en cada cuenta (no son ajustes)
ACCOUNT_STATE = ("capacity", "builder_capacity", "walls_done", "walls_checked", "th_target")


def _accounts(value):
    """Las cuentas se pueden escribir como lista de nombres, lista de objetos con "name" o diccionario."""
    out = {}
    if isinstance(value, dict):
        for name, a in value.items():
            out[str(name)] = dict(a) if isinstance(a, dict) else {}
    elif isinstance(value, list):
        for a in value:
            if isinstance(a, str):
                out[a] = {}
            elif isinstance(a, dict) and a.get("name"):
                out[str(a["name"])] = {k: v for k, v in a.items() if k != "name"}
    return out


def canonical(raw):
    """El config tal cual está escrito, sólo con las cuentas en forma de diccionario (para poder guardar en él)."""
    raw = dict(raw) if isinstance(raw, dict) else {}
    raw["accounts"] = _accounts(raw.get("accounts"))
    return raw


def read_raw(path=None):
    return canonical(json.loads(Path(path or CONFIG).read_text(encoding="utf-8")))


def write_raw(raw, path=None):
    p = Path(path or CONFIG)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def _number(value, low, high, name, problems, default):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        problems.append(f"«{name}» debe ser un número entre {low} y {high} (pone {value!r}): uso {default}.")
        return default
    return value


def default_routine(accounts):
    """Sin rutina escrita: las tareas de cada cuenta ("tasks") o, si no dice nada, llenar almacenes."""
    steps = []
    for name, a in accounts.items():
        tasks = a.get("tasks")
        tasks = [tasks] if isinstance(tasks, str) else tasks if isinstance(tasks, list) else None
        if tasks is None:
            tasks = ["build", "fill_storages"] if a.get("auto_build") else ["fill_storages"]
        steps += [{"account": name, "task": t} for t in tasks]
    return steps


def normalize(raw):
    """(config completo, lista de problemas en cristiano). Nunca lanza: lo que esté mal se avisa y se sustituye
    por su valor por defecto, o se deja fuera si es un paso de la rutina imposible."""
    problems = []
    raw = canonical(raw)
    cfg = copy.deepcopy(DEFAULTS)
    cfg.update({k: v for k, v in raw.items() if k != "accounts"})

    for key in ("full_ratio", "dark_full_ratio", "walls_spend_ratio"):
        cfg[key] = _number(cfg[key], 0.05, 1, key, problems, DEFAULTS[key])
    for key in ("rest_minutes_between_cycles", "rest_minutes_when_full", "owner_pause_minutes",
                "donation_check_minutes"):
        cfg[key] = _number(cfg[key], 0, 24 * 60, key, problems, DEFAULTS[key])
    if not isinstance(cfg.get("advanced"), dict):
        problems.append("«advanced» debe ser un objeto {\"CONSTANTE\": valor}: lo ignoro.")
        cfg["advanced"] = {}

    shared = raw.get("account_defaults") if isinstance(raw.get("account_defaults"), dict) else {}
    accounts = {}
    for name, a in raw["accounts"].items():
        acc = {**copy.deepcopy(ACCOUNT_DEFAULTS), **copy.deepcopy(shared), **a}
        acc["village_name"] = str(acc.get("village_name") or name)
        acc["switch_label"] = str(acc.get("switch_label") or acc["village_name"])
        acc["label"] = str(acc.get("label") or name)
        acc["max_searches"] = int(_number(acc["max_searches"], 1, 500, f"{name}.max_searches", problems,
                                          ACCOUNT_DEFAULTS["max_searches"]))
        loot = acc.get("min_loot")
        if isinstance(loot, dict):
            if loot.get("mode") not in (None, *LOOT_MODES):
                problems.append(f"«{name}.min_loot.mode» debe ser {' o '.join(LOOT_MODES)} "
                                f"(pone {loot.get('mode')!r}): lo elijo yo.")
                acc["min_loot"] = {k: v for k, v in loot.items() if k != "mode"}
        elif loot not in (None, "auto"):
            problems.append(f"«{name}.min_loot» debe ser \"auto\" o {{\"gold\": N, \"elixir\": N, \"dark\": N}}: "
                            "uso \"auto\".")
            acc["min_loot"] = "auto"
        focus = acc.get("farm_focus")
        if focus is not None and not (isinstance(focus, list) and focus
                                      and all(k in ("gold", "elixir", "dark") for k in focus)):
            problems.append(f"«{name}.farm_focus» debe ser una lista con gold, elixir o dark: lo ignoro.")
            acc.pop("farm_focus")
        accounts[name] = acc
    cfg["accounts"] = accounts
    if not accounts:
        problems.append("No hay ninguna cuenta: escribe en config.json  \"accounts\": [\"NombreDeTuAldea\"].")

    routine = raw.get("routine")
    if not isinstance(routine, list) or not routine:
        if routine not in (None, []):
            problems.append("«routine» debe ser una lista de pasos: uso la rutina por defecto.")
        routine = default_routine(accounts)
    steps = []
    for i, s in enumerate(routine, 1):
        if isinstance(s, str) and ":" in s:                      # "Cuenta:tarea"
            acc, task = (p.strip() for p in s.rsplit(":", 1))
            s = {"account": acc, "task": task}
        if not isinstance(s, dict):
            problems.append(f"Paso {i} de la rutina ilegible ({s!r}): lo salto.")
            continue
        if s.get("account") not in accounts:
            problems.append(f"Paso {i} de la rutina: la cuenta «{s.get('account')}» no está en «accounts» "
                            f"(hay: {', '.join(accounts) or 'ninguna'}): lo salto.")
            continue
        if s.get("task") not in TASKS:
            problems.append(f"Paso {i} de la rutina: la tarea «{s.get('task')}» no existe "
                            f"(valen: {', '.join(TASKS)}): lo salto.")
            continue
        steps.append(s)
    cfg["routine"] = steps

    home = cfg.get("home_account")
    if home and home not in accounts:
        problems.append(f"«home_account» es «{home}», que no está en «accounts»: no vuelvo a ninguna cuenta "
                        "en los descansos.")
        home = None
    if not home and "home_account" not in raw:
        home = next((n for n, a in accounts.items() if a.get("donor")), None)
    cfg["home_account"] = home

    if not cfg.get("emulator_args"):
        cfg["emulator_args"] = ["--instance", str(cfg["bluestacks_instance"])]
    if not cfg.get("emulator_process"):
        cfg["emulator_process"] = Path(str(cfg["bluestacks_player"])).name
    return cfg, problems


def load(path=None):
    """(config completo, problemas). Si el fichero no existe o no es JSON válido, lo dice en los problemas."""
    p = Path(path or CONFIG)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except OSError:
        return normalize({})[0], [f"No existe {p.name}: copia config.example.json con ese nombre y pon tus cuentas."]
    except ValueError as e:
        return normalize({})[0], [f"{p.name} no es JSON válido ({e}): revisa comas y comillas."]
    return normalize(raw)


def option(cfg, key, default=None, account=None):
    """Valor de una opción: el de la cuenta si lo tiene, si no el general, si no `default`."""
    a = cfg.get("accounts", {}).get(account) if account else None
    if a and a.get(key) is not None:
        return a[key]
    v = cfg.get(key, default)
    return default if v is None else v


# ---------------- "advanced": constantes internas desde config.json ----------------
_ORIGINAL = {}


def _like(old, new):
    """Convierte lo que viene del JSON (listas, objetos) al tipo que tenía la constante."""
    if isinstance(old, tuple) and isinstance(new, list):
        inner = old[0] if old else None
        return tuple(_like(inner, v) if isinstance(inner, (tuple, list, dict, set)) else
                     (tuple(v) if isinstance(v, list) and isinstance(inner, tuple) else v) for v in new)
    if isinstance(old, (set, frozenset)) and isinstance(new, list):
        return type(old)(new)
    if isinstance(old, dict) and isinstance(new, dict):
        return {**old, **{k: _like(old[k], v) if k in old else v for k, v in new.items()}}
    if isinstance(old, list) and isinstance(new, list):
        inner = old[0] if old else None
        return [_like(inner, v) if isinstance(inner, (tuple, list, dict, set)) else v for v in new]
    return new


def apply_overrides(advanced, modules):
    """Pone las constantes de «advanced» en sus módulos (`modules`: {"asistente": módulo, "vision": módulo…}).
    "NOMBRE" es del asistente; "vision.NOMBRE" de vision.py. Devuelve los problemas encontrados. Lo que se
    quite de «advanced» vuelve a su valor original en la siguiente lectura."""
    problems = []
    for (mod, name), value in _ORIGINAL.items():
        if mod in modules:
            _set(modules[mod], name, copy.deepcopy(value))
    for key, value in (advanced or {}).items():
        mod, _, name = str(key).rpartition(".")
        mod = mod or "asistente"
        target = modules.get(mod)
        if target is None or not name.isupper() or not hasattr(target, name):
            problems.append(f"«advanced.{key}» no existe: es el nombre de una constante en mayúsculas "
                            f"(por ejemplo SPEED_BTN o vision.NOMBRE).")
            continue
        old = getattr(target, name)
        if (mod, name) not in _ORIGINAL:
            try:
                _ORIGINAL[(mod, name)] = copy.deepcopy(old)
            except Exception:
                problems.append(f"«advanced.{key}» no se puede cambiar desde config.json.")
                continue
        try:
            _set(target, name, _like(_ORIGINAL[(mod, name)], value))
        except Exception as e:
            problems.append(f"«advanced.{key}» no vale ({e}).")
    return problems


def _set(module, name, value):
    """Cambia la constante sin romper las referencias que ya la tengan (diccionarios y listas, en el sitio)."""
    old = getattr(module, name)
    if isinstance(old, dict) and isinstance(value, dict):
        old.clear()
        old.update(value)
    elif isinstance(old, list) and isinstance(value, list):
        old[:] = value
    else:
        setattr(module, name, value)

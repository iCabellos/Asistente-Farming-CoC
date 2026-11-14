"""Asistente de farmeo de Clash of Clans (BlueStacks + ADB). Lo arranca y vigila vigilante.py.

La rutina (qué cuenta y qué tarea, en bucle) está en config.json y se edita desde el visor
(http://localhost:8000). Tareas: llenar almacenes, llenar aldea nocturna, mejorar lo recomendado.
Entre batalla y batalla: dona lo que pidan en el clan y pide tropas si es gratis.
Normas: sólo batallas NORMALES, nunca gemas ni martillos, nunca guerra/competitiva; mejoras sólo en
las cuentas con "auto_build". Si el dueño entra en una cuenta desde otro dispositivo, el asistente se aparta.
"""
import colorsys
import io
import itertools
import json
import random
import re
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from device import Device, color, is_green, is_orange, is_red, is_yellow
from eyes import Eyes
try:
    import ocr as ocr_mod                     # comprobaciones por píxeles (precio en rojo…)
except Exception:
    ocr_mod = None
import math
import vision

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
HERE = Path(__file__).parent
LIVE = HERE.parent                      # coc-live: diario y botín que muestra el visor
CFG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
STOP = HERE / "STOP"

import shutil
_adb = CFG.get("adb") if CFG.get("adb") and Path(CFG["adb"]).exists() else (shutil.which("adb") or "adb")
dev = Device(_adb, CFG["serial"])
eyes = Eyes(CFG["ollama"], CFG["model"], CFG.get("model_keep_alive", "5m"))
blocked_until = {}                      # cuenta -> timestamp (el dueño está jugando)
current = None                          # cuenta abierta



# ---------------- diario (lo ve el visor web) ----------------
def log(kind, text, action="", pts=None):
    line = {"ts": time.time(), "kind": kind, "action": action, "text": text, "pts": pts}
    with open(LIVE / "log.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
    print(time.strftime("%H:%M:%S"), kind.upper(), text, flush=True)


def loot_log(account, enemy, stars, pct, gained):
    row = {"ts": time.time(), "account": account, "enemy": enemy, "stars": stars, "pct": pct,
           "gold": gained.get("gold") or 0, "elixir": gained.get("elixir") or 0, "dark": gained.get("dark") or 0,
           "note": "asistente"}
    with open(LIVE / "loot.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def tap(x, y, why, wait=0.8):
    dev.tap(x, y)
    log("act", why, "tap", [[int(x), int(y)]])
    time.sleep(wait)


def wait_for(cond, timeout, step=0.4):
    """Espera a que `cond()` sea cierto (como mucho `timeout` s) en vez de dormir un tiempo fijo."""
    t0 = time.time()
    while True:
        if cond():
            return True
        if time.time() - t0 > timeout:
            return False
        time.sleep(step)


def check_stop(redirect=True):
    """Punto seguro para atender órdenes del visor: parar (STOP) y, si `redirect`, saltar a un paso (IR_A).
    Con tropas ya desplegadas se llama con redirect=False: la batalla en curso se acaba antes de obedecer."""
    if STOP.exists():
        STOP.unlink()
        log("warn", "Parado por orden (fichero STOP).")
        sys.exit(0)
    if redirect:
        check_goto()


GOTO_FILE = HERE / "IR_A"               # orden del visor «haz este paso ya»: {"index", "account", "task"}


class Redirect(BaseException):
    """Orden de saltar a un paso de la rutina. Hereda de BaseException para que ningún `except Exception`
    intermedio se la trague: sube hasta main(), que empieza la vuelta en ese paso."""
    def __init__(self, index, step):
        super().__init__(index)
        self.index, self.step = index, step


def check_goto():
    if not GOTO_FILE.exists():
        return
    try:
        order = json.loads(GOTO_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        order = None
    GOTO_FILE.unlink(missing_ok=True)
    if not isinstance(order, dict):
        log("warn", "Orden del visor ilegible (IR_A): la ignoro.")
        return
    reload_config()
    routine, i = CFG["routine"], order.get("index")
    want = (order.get("account"), order.get("task"))
    if not (isinstance(i, int) and 0 <= i < len(routine) and (routine[i]["account"], routine[i]["task"]) == want):
        # la rutina cambió entre el clic y ahora: se busca el mismo paso por cuenta y tarea
        i = next((k for k, s in enumerate(routine) if (s["account"], s["task"]) == want), None)
    if i is None:
        log("warn", f"El visor pidió {want[0]} · {want[1]}, que ya no está en la rutina: lo ignoro.")
        return
    clear_pause()                        # lo manda el dueño: si había pausa por «está jugando», se acaba
    raise Redirect(i, routine[i])


# ---------------- pantallas ----------------
def upgrade_window(img):
    """Ventana «¿Mejorar tu X al nivel N?»: X roja arriba a la derecha y barra de título clara."""
    a, b = color(img, 1725, 85, 3), color(img, 1665, 85, 3)
    red = all(c[0] > 190 and c[1] < 90 and c[2] < 90 for c in (a, b))
    frame = [color(img, x, y, 3) for x, y in ((185, 300), (1745, 700))]      # marco gris oscuro de la ventana
    return red and all(max(c) < 110 and max(c) - min(c) < 25 for c in frame)


def _hsv(c):
    h, s, v = colorsys.rgb_to_hsv(*(x / 255 for x in c[:3]))
    return h * 360, s, v


def _red_any(c):
    """Rojo del botón Terminar/Rendirse, también con la neblina blanca de las nubes (por tono; QA)."""
    h, s, v = _hsv(c)
    return is_red(c) or ((h >= 345 or h <= 10) and s >= 0.3 and v >= 0.7)


def _orange_any(c):
    h, s, v = _hsv(c)
    return is_orange(c) or (15 <= h <= 45 and s >= 0.3 and v >= 0.8)


def home_button(img):
    """Botón amarillo de «Batalla» abajo a la izquierda (aldea). Se miran sus bordes además del centro: con
    algunos eventos el icono lleva llamas naranjas justo en el centro (10-nov)."""
    return any(is_yellow(color(img, x, y, 3)) for x, y in ((120, 1000), (60, 1000), (180, 1000), (60, 1040)))


def screen(img=None):
    img = img or dev.shot()
    if upgrade_window(img):
        return "upgrade", img
    # batalla primero: el botón rojo "Terminar batalla" (aldea principal y), en la nocturna, algo más arriba
    if _red_any(color(img, 60, 780, 3)) or _red_any(color(img, 60, 750, 3)):
        # botón naranja «Siguiente»: el precio cambia de sitio según su longitud (350 / 1700), se miran varios puntos
        orange = any(_orange_any(color(img, x, y, 3)) for x, y in ((1780, 820), (1640, 815), (1640, 725), (1880, 815)))
        return ("search" if orange else "battle"), img
    if is_green(color(img, 880, 945, 3)) and not home_button(img):
        return "result", img
    if home_button(img):
        return "home", img
    return "unknown", img


def in_builder(img=None):
    """Aldea nocturna: la 3ª barra de recursos es de gemas (icono verde claro) en vez de oscuro (negro)."""
    img = img or dev.shot()
    c = color(img, 1868, 205, 4)
    gem_third = c[1] > 200 and c[0] > 150
    # la aldea principal siempre tiene la barra del escudo (con su "+" blanco) debajo; la nocturna no
    shield_plus = min(color(img, 1617, 280, 4)) > 230
    return gem_third and not shield_plus


def main_village():
    """Asegura estar en la aldea PRINCIPAL (vuelve en barco si está en la nocturna)."""
    if not go_home():
        return False
    if in_builder():
        travel_boat(False)
        return go_home() and not in_builder()
    return True


OWNER = {"seen": False}
LAST_GAIN = {}
SAFE_WORDS = ("vale", "ok", "okay", "continuar", "cerrar", "mas tarde", "más tarde", "nunca", "seguir",
              "entendido", "aceptar", "volver", "cancelar")


def green_buttons(img, y_from=560, y_to=1000):
    """Botones verdes grandes en la mitad baja de la pantalla (Vale, Continuar…)."""
    px = img.load()
    found = []
    for y in range(y_from, y_to, 6):
        run = 0
        for x in range(640, 1400, 3):              # sólo la zona central (botones de diálogo)
            r, g, b = px[x, y]
            # verde exacto de los botones del juego (no la hierba): (129,198,54) ± tolerancia
            if abs(r - 129) < 35 and abs(g - 198) < 22 and abs(b - 54) < 40:
                run += 1
            else:
                if run >= 50:
                    found.append((x - run * 3 // 2, y))
                run = 0
    # un botón = varias franjas a la misma x; nos quedamos con el centro de cada grupo
    groups = []
    for x, y in found:
        for gr in groups:
            if abs(gr[0] - x) < 40 and abs(gr[-1][1] - y) <= 12:
                gr.append((x, y))
                break
        else:
            groups.append([x, (x, y)])
    out = []
    for gr in groups:
        pts = gr[1:]
        if len(pts) >= 4:
            out.append((sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)))
    return out


def button_text(img, x, y):
    crop = img.crop((int(x) - 190, int(y) - 55, int(x) + 190, int(y) + 55))
    d = eyes.ask(crop, '¿Qué texto pone en este botón? Responde {"text": "..."}. Si lleva un precio o una gema, '
                       'pon también el número.')
    return str(d.get("text", "")).strip().lower()


def red_close(img):
    """X roja de cerrar, por píxeles: cuadrado rojo intenso con aspa blanca cuyo CENTRO es blanco.
    Sólo se busca arriba a la derecha (donde están las X de paneles y avisos)."""
    px = img.load()
    red = lambda p: p[0] > 200 and p[1] < 70 and p[2] < 80
    for y in range(12, 330, 3):
        run = 0
        for x in range(1250, 1918, 2):
            if x < 1917 and red(px[x, y]):
                run += 1
                continue
            L = run * 2
            if 50 <= L <= 140:
                x1 = x - L
                for cy in range(max(5, y - L), y, 3):        # el aspa: centro blanco en la columna central
                    cx = x1 + L // 2
                    if min(px[cx, cy]) > 225 and red(px[x1 + 4, cy]) and red(px[x - 4, cy]):
                        return (cx, cy)
            run = 0
    return None


def chat_jump_visible(img):
    """Botón verde claro con flecha (abajo-izquierda del chat) para bajar a los mensajes nuevos."""
    c = color(img, 40, 900, 2)
    return c[1] > 200 and c[1] > c[2] + 60 and c[0] > 150   # verde claro (tolerante a cambios de tono)


def chat_open(img=None):
    img = img or dev.shot()
    return is_orange(color(img, 770, 450, 3)) and is_orange(color(img, 770, 520, 3))


def battle_menu_open(img=None):
    img = img or dev.shot()
    # franja naranja inferior del botón "Buscar batalla" (común a todas las versiones del menú)
    return all((lambda c: c[0] > 220 and 140 < c[1] < 200 and c[2] < 80)(color(img, x, 856, 3)) for x in (240, 400, 530))


def selection_bar(img):
    """¿Hay un edificio seleccionado? Su nombre sale en grande (texto amarillo con borde negro) en y≈715
    y debajo hay tarjetas beige. Se detecta por tarjetas beige claras en la franja y=760-930."""
    hits = 0
    for x in range(470, 1470, 20):
        for y in (790, 905):
            r, g, b = color(img, x, y, 2)
            if 190 < r < 240 and 170 < g < 215 and 120 < b < 175 and r - b > 40:
                hits += 1
    return hits >= 10


def deselect():
    """No se toca nada para deseleccionar (cualquier toque podría caer en un botón); basta con no tocar la barra."""
    go_home()


def system_dialog(img):
    """Diálogo gris oscuro de Android (desconexión). Devuelve 'inactividad', 'otro_dispositivo', 'otro' o None."""
    if not all(abs(c - 66) < 6 for p in ((1200, 560), (900, 640), (1300, 450)) for c in color(img, *p, 3)):
        return None
    d = eyes.ask(img.crop((552, 420, 1368, 660)), '¿Qué dice este aviso? Responde {"text": "..."}.')
    t = str(d.get("text", "")).lower()
    if "inactiv" in t:
        return "inactividad"
    if "dispositivo" in t or "device" in t:
        return "otro_dispositivo"
    return "otro"


def go_home(max_tries=10):
    """Lleva el juego a la aldea cerrando popups. Devuelve False si el dueño ha entrado."""
    last_close, waits = None, 0
    for _ in range(max_tries + 4):
        if paused():
            return False
        if "clashofclans" not in dev.foreground():
            dev.launch_game()
            time.sleep(15)
        kind, img = screen()
        if kind == "home":
            return True
        if kind == "result":
            tap(960, 925, "volver a casa", 6)
            continue
        if kind in ("search", "battle"):
            tap(137, 805, "terminar batalla", 1.5)
            dlg = dev.shot()
            for bx, by in green_buttons(dlg, 450, 950):
                if dialog_cancel(dlg, bx, by)[0] is not None:   # diálogo real: Cancelar | Okay
                    tap(bx, by, "confirmar terminar batalla", 5)
                    break
            continue
        if kind == "upgrade":                  # jamás tocar sus botones (el gris es el martillo)
            tap(1697, 83, "cerrar ventana de mejora (X)", 1.5)
            continue
        if builder_panel_open(img):
            tap(1887, 33, "cerrar panel de constructores", 1.2)
            continue
        sd = system_dialog(img)
        if sd == "otro_dispositivo":
            OWNER["seen"] = True                   # el dueño está jugando: NO recargar
            return False
        if sd in ("inactividad", "otro"):
            tap(680, 616, "volver a cargar (desconectado por inactividad)", 15)
            continue
        if is_orange(color(img, 770, 450, 3)) and is_orange(color(img, 770, 520, 3)):
            tap(787, 490, "cerrar chat del clan", 1.5)
            continue
        if is_orange(color(img, 1122, 450, 3)) and is_orange(color(img, 1122, 520, 3)):
            tap(1122, 490, "cerrar chat global", 1.5)
            continue
        # tras una batalla o un cambio de pantalla el juego pasa unos segundos por las nubes o una animación:
        # esperar antes de tocar nada. Antes se acababa pulsando ATRÁS y salía «¿Salir del juego?» (lo veía el
        # usuario, 10-nov) y además se gastaba una pregunta al modelo
        if finding_rivals(img):
            time.sleep(1)
            continue
        waits += 1
        if waits <= 3:
            time.sleep(1.2)
            continue
        what, close = eyes.screen_kind(img)
        if what == "aldea" and not upgrade_window(img) and not builder_panel_open(img):
            # el modelo ve la aldea aunque el botón de Batalla no tenga su amarillo de siempre (10-nov: con un
            # evento sale con llamas y no se reconocía → se pulsaba ATRÁS → «¿Quieres salir del juego?»)
            return True
        if what == "otro_dispositivo":
            # confirmación: ese aviso siempre trae un botón verde "Recargar"
            if any("recarg" in button_text(img, bx, by) or "reload" in button_text(img, bx, by)
                   for bx, by in green_buttons(img)):
                OWNER["seen"] = True
                return False
            what = "popup"
        if what == "cargando":
            time.sleep(5)
            continue
        # 1) botón verde con texto inofensivo (Vale, Continuar…); nunca si tiene precio
        pressed = False
        for bx, by in green_buttons(img):
            ox, oy = dialog_cancel(img, bx, by)
            if ox is not None:
                # diálogo de confirmación (p.ej. "¿Salir del juego?"): siempre Cancelar
                tap(ox, oy, "cancelar diálogo de confirmación", 1.5)
                pressed = True
                break
            text = button_text(img, bx, by)
            if any(w in text for w in SAFE_WORDS) and not any(ch.isdigit() for ch in text):
                tap(bx, by, f"pulsar «{text}»", 2)
                pressed = True
                break
        if pressed:
            continue
        # 2) X roja de cerrar, localizada por color (nunca por el LLM: podría pulsar Tienda u ofertas)
        xr = red_close(img)
        if xr and xr != last_close:
            tap(*xr, "cerrar ventana (X roja)", 1.5)
            last_close = xr
            continue
        # 3) tecla atrás, sólo como último recurso (si abre "¿Salir del juego?", la siguiente vuelta lo cancela)
        try:                                   # para ver qué pantalla era (la 1.ª no se pisa con la 2.ª)
            img.save(HERE / ("atras.png" if not (HERE / "atras.png").exists()
                             or time.time() - (HERE / "atras.png").stat().st_mtime > 60 else "atras2.png"))
        except Exception:
            pass
        log("think", f"Pantalla que no reconozco («{what}») y sin botón para cerrar: pulso ATRÁS (captura en atras.png).")
        dev.back(1.5)
        last_close = None
    return screen()[0] == "home"


def dialog_cancel(img, bx, by):
    """Diálogo de confirmación del juego: 'Cancelar' naranja centrado en x≈746 y el verde en x≈1167, misma fila."""
    if not (1050 < bx < 1290 and 600 < by < 900):
        return None, None
    c = color(img, 746, int(by), 6)
    if c[0] > 200 and 60 < c[1] < 160 and c[2] < 70:
        return 746, by
    return None, None


def cancel_left_of(img, bx, by, strict=False):
    """Botón naranja ('Cancelar') a la izquierda del verde, en la misma fila."""
    for x in range(int(bx) - 200, 300, -20):
        c = color(img, x, int(by), 4)
        if c[0] > 200 and 70 < c[1] < 170 and c[2] < 80:
            return x, by
    return (None, None) if strict else (746, 690)


def handle_not_home():
    """go_home() falló: si fue porque entró el dueño, bloquear la cuenta; si no, reiniciar el juego."""
    if OWNER["seen"]:
        OWNER["seen"] = False
        owner_detected()
    else:
        log("warn", "No consigo volver a la aldea; reinicio el juego.")
        dev.shell("am force-stop com.supercell.clashofclans")
        time.sleep(2)
        dev.launch_game()
        time.sleep(20)


PAUSE_FILE = HERE / "PAUSA_DUENO"
try:
    PAUSE = {"until": float(PAUSE_FILE.read_text())}
except (OSError, ValueError):
    PAUSE = {"until": 0}


def owner_detected():
    """El dueño juega en otro dispositivo. Al reabrir, el juego entra SIEMPRE en la última aldea (la suya)
    y le echaría: así que el asistente entero se para con el juego cerrado un buen rato."""
    mins = CFG.get("owner_pause_minutes", 45)
    PAUSE["until"] = time.time() + mins * 60
    blocked_until[current] = PAUSE["until"]          # igual que la pausa: si no, tras ella venía un descanso
    PAUSE_FILE.write_text(str(PAUSE["until"]))
    log("warn", f"El dueño está jugando en {current}: cierro el juego y paro el asistente {mins} min para no echarle.")
    dev.shell("am force-stop com.supercell.clashofclans")


def clear_pause():
    """Acaba la pausa por el dueño y desbloquea sus cuentas (las vuelve a usar el asistente)."""
    PAUSE["until"] = 0
    blocked_until.clear()
    PAUSE_FILE.unlink(missing_ok=True)


def paused():
    """¿Sigue la pausa por el dueño? Si el visor ha borrado PAUSA_DUENO («Saltar pausa»), se acaba ya."""
    if PAUSE["until"] > time.time() and not PAUSE_FILE.exists():
        clear_pause()
        log("think", "Pausa saltada desde el visor: vuelvo a la rutina.")
    return PAUSE["until"] > time.time()


def owner_pause():
    """Espera (sin abrir el juego) mientras dure la pausa por el dueño. Mira el visor cada 2 s."""
    if not paused():
        return
    set_state(phase="pause", pause_until=PAUSE["until"])
    beat = 0
    while paused():
        check_stop()
        if time.time() - beat >= 300:          # latido cada 5 min para que el vigilante no lo crea colgado
            beat = time.time()
            log("think", f"Pausa: el dueño está jugando. Quedan {int((PAUSE['until'] - beat) / 60)} min.")
        time.sleep(2)
    PAUSE_FILE.unlink(missing_ok=True)
    set_state(phase="run")
    log("think", "Fin de la pausa: vuelvo a abrir el juego.")


# ---------------- cuentas ----------------
def _norm(s):
    # la «l» minúscula y la «I» mayúscula se ven iguales en la fuente del juego: se igualan l/i
    return "".join(ch for ch in str(s).lower().replace("l", "i") if ch.isalnum())


def which_account(img=None):
    name = _norm(eyes.village_name(img or dev.shot()))
    for acc, a in CFG["accounts"].items():
        key = _norm(a["village_name"])
        if key and key in name:
            return acc
    return None


SID_LIST = (1440, 370, 1800, 1080)        # columna de los nombres en la lista de Supercell ID (panel derecho)


def _dark(img):
    return (np.asarray(img.convert("RGB")).astype(np.int16).max(axis=2) < 90).astype(np.float32)


def sid_list_open(img):
    """¿Está abierta la lista de Supercell ID? Panel derecho gris claro liso con la X blanca arriba."""
    a = np.asarray(img.convert("RGB")).astype(np.int16)
    strip = a[500:540, 1330:1900]
    return strip.min() > 225 and strip.max() - strip.min() < 30


def sid_card_y(img, acc):
    """y donde tocar la tarjeta de la cuenta en la lista de Supercell ID, por la plantilla de su nombre
    (tpl/sid_<cuenta>.png), o None. El modelo no la encontraba (10-nov): la lista pone «TheRlvan11», con ele,
    y se le pedía «TheRIvan11». Plantillas: 1,0 en su tarjeta y ≤0,51 en las demás."""
    p = HERE / "tpl" / f"sid_{acc}.png"
    if not p.exists():
        return None
    t = _dark(Image.open(p))
    r = cv2.matchTemplate(_dark(img.crop(SID_LIST)), t, cv2.TM_CCOEFF_NORMED)
    _, v, _, (_, y) = cv2.minMaxLoc(r)
    y += SID_LIST[1] + t.shape[0] // 2
    return y + 15 if v >= 0.85 and y + 15 < 1060 else None


def switch_to(acc):
    global current
    if not go_home():
        handle_not_home()
        return False
    if which_account() == acc:
        current = acc
        return True
    label = CFG["accounts"][acc]["switch_label"]
    log("think", f"Cambio a la cuenta {acc}.")
    pos = None
    for attempt in range(2):
        tap(100, 110, "abrir perfil", 2.5)
        # el perfil se abre en la última pestaña usada: sin pasar por «Ajustes», (1264,206) es otra cosa
        tap(1518, 90, "pestaña Ajustes", 1.5)
        tap(1264, 206, "cambiar de cuenta (Supercell ID)", 4)
        if sid_list_open(dev.shot()):
            break
        log("warn", "No se ha abierto la lista de Supercell ID; vuelvo a intentarlo.")
        go_home()
    else:
        return False
    for scroll in range(4):
        img = dev.shot()
        y = sid_card_y(img, acc)
        if y:
            pos = (1620, y)
            break
        if not (HERE / "tpl" / f"sid_{acc}.png").exists():      # cuenta sin plantilla: que la busque el modelo
            pos = eyes.find(img, f'la tarjeta de la cuenta "{label}" en la lista de Supercell ID (panel derecho)')
            if pos and pos[0] > 1330 and pos[1] < 1000:
                break
            pos = None
        dev.swipe(1620, 900, 1620, 560, 600, wait=1.5)
    if not pos:
        dev.shot().save(HERE / "sin_cuenta.png")
        log("warn", f"No encuentro la cuenta {label} en la lista (captura en sin_cuenta.png).")
        dev.back(1)
        go_home()
        return False
    tap(*pos, f"elegir cuenta {label}", 15)
    for _ in range(5):
        if go_home() and which_account() == acc:
            current = acc
            log("done", f"Ahora en {acc}.")
            return True
        time.sleep(4)
    return False


# ---------------- clan: donar y pedir ----------------
def donate_buttons(img):
    """Botones verdes "Donar" del chat (mismo verde que "Desafiar"), buscados por píxeles, sin LLM.
    Por fila se cuentan los píxeles verdes (el texto blanco "Donar" parte la franja, así que no se exige
    que sean seguidos); filas consecutivas con >= 90 px verdes forman un botón."""
    px = img.load()
    hits = []                                       # (y, xmin, xmax)
    for y in range(95, 955, 3):
        xs = []
        for x in range(40, 712, 2):
            r, g, b = px[x, y]
            # verde de botón (degradado de claro a oscuro): verde dominante y saturado
            if g > 160 and g > r + 15 and g > b + 60 and r > 80:
                xs.append(x)
        if len(xs) >= 40 and xs[-1] - xs[0] < 260:  # >= 90 px verdes en un tramo del ancho de un botón
            hits.append((y, xs[0], xs[-1]))
    buttons = []
    for y, x1, x2 in hits:
        if buttons and y - buttons[-1]["y2"] <= 18 and abs(buttons[-1]["x1"] - x1) < 30:
            buttons[-1]["y2"] = y
        else:
            buttons.append({"x1": x1, "x2": x2, "y1": y, "y2": y})
    return [((b["x1"] + b["x2"]) / 2, (b["y1"] + b["y2"]) / 2) for b in buttons if b["y2"] - b["y1"] >= 24]


DONATE_ROWS = (335, 510, 755)                      # 2 filas de tropas + 1 de hechizos
DONATE_COLS = tuple(range(842, 1740, 137))


def donation_gem_y(img):
    """Centro vertical del icono de gema (pestaña de la ventana de donación, x≈1633), o None.
    La ventana sale más arriba o más abajo según dónde estaba el botón Donar: todo se mide desde aquí."""
    px = img.load()
    ys = [y for y in range(10, 330, 2)
          if (lambda p: p[1] > 200 and 180 < p[0] < 240 and 100 < p[2] < 150)(px[1633, y])]
    if len(ys) < 8:
        return None
    return (ys[0] + ys[-1]) / 2


def donation_window_open(img):
    gy = donation_gem_y(img)
    if gy is None:
        return False
    c = color(img, 1255, int(gy + 90), 3)           # fondo gris claro de la ventana bajo la cabecera
    return min(c) > 200


def donation_rows(img):
    gy = donation_gem_y(img)
    return [int(gy + d) for d in (200, 375, 620)] if gy is not None else []


def card_colored(img, x, y):
    """En la ventana de donación el juego pone en gris lo que NO piden: a color = lo que hay que donar."""
    box = img.crop((x - 50, y - 60, x + 50, y + 40))
    return sum(1 for p in box.getdata() if max(p) - min(p) > 25) > 1500


def price_is_resource(img, x, y):
    """El icono del precio (abajo-derecha de la carta) es una gota rosa/negra, nunca una gema verde."""
    box = img.crop((x + 33, y + 47, x + 53, y + 67)).getdata()
    green = sum(1 for r, g, b in box if g > 150 and g > r + 40 and g > b + 30)
    pink = sum(1 for r, g, b in box if r > 190 and b > 170 and g < 140)
    dark = sum(1 for r, g, b in box if max(r, g, b) < 140 and b >= g and abs(r - b) < 45)
    return green < 20 and (pink + dark) >= 25     # gota rosa o negra (con brillos), nunca gema verde


def donate_once(x, y):
    """Abre la ventana de donación y dona todas las cartas a color hasta que se pongan grises."""
    tap(x, y, "abrir donación", 2)
    win = dev.shot()
    if chat_open(win) and donate_buttons(win) and abs(donate_buttons(win)[-1][1] - y) < 20 and             not card_colored(win, 842, 335) and not card_colored(win, 842, 755):
        return 0                                   # no se abrió ninguna ventana
    win.save(HERE / "ultima_donacion.png")
    if not donation_window_open(win):
        win.save(HERE / "donacion_fallida.png")     # para revisar qué había en pantalla
        log("think", "No se abre la ventana de donación (petición ya cubierta).")
        if not chat_open(win):
            dev.back(1.5)
        return 0
    done = 0
    for cy in donation_rows(win):
        for cx in DONATE_COLS:
            img = dev.shot()
            if not donation_window_open(img):     # petición cubierta: el juego cierra la ventana solo
                break
            if not card_colored(img, cx, cy):
                continue
            if not price_is_resource(img, cx, cy):
                log("warn", f"Carta {cx},{cy} con precio que no es elixir/oscuro: no la toco.")
                continue
            for _ in range(8):                     # hasta que la carta se ponga gris (petición cubierta)
                tap(cx, cy, "donar", 0.7)
                done += 1
                now = dev.shot()
                if not donation_window_open(now) or not card_colored(now, cx, cy):
                    break
    log("done" if done else "think", f"Donación: {done} toques a cartas pedidas.")
    if donation_window_open(dev.shot()):
        dev.back(1.5)
    if not chat_open():
        go_home()
        tap(100, 540, "reabrir chat del clan", 2)
    return done


def clan_duties():
    """Abre el chat del clan, dona TODO lo que pidan y pide tropas si es gratis."""
    if mass_on() and time.time() - MASS["clan"] < 600:
        return                                     # evento en masa: el clan, como mucho cada 10 min
    MASS["clan"] = time.time()
    if not go_home():
        return
    img = None
    for attempt in range(2):
        tap(100, 540, "abrir chat del clan", 1.5)
        for _ in range(4):                         # la animación del chat tarda a veces
            img = dev.shot()
            if chat_open(img):
                break
            if is_orange(color(img, 1122, 450, 3)) and is_orange(color(img, 1122, 520, 3)):
                tap(1122, 300, "pasar del chat global a la pestaña del clan", 2)
                continue
            time.sleep(1)
        if chat_open(img):
            break
    if not chat_open(img):
        log("warn", "El chat no se ha abierto; lo dejo para la próxima.")
        go_home()
        return
    if chat_jump_visible(img):
        tap(62, 920, "ir al final del chat", 1.5)
    donated = 0
    tried = {}
    for page in range(3):                          # final del chat y dos pantallas más arriba
        for _ in range(4):
            img = dev.shot()
            if not chat_open(img):
                break
            btns = donate_buttons(img)
            if not btns:
                break
            x, y = btns[-1]
            key = (round(x / 20), round(y / 20))
            tried[key] = tried.get(key, 0) + 1
            if tried[key] > 2:
                break                              # ya se donó lo que se podía a esta petición
            log("think", f"Petición de tropas en el clan (botón Donar en {int(x)},{int(y)}) → dono.")
            n = donate_once(x, y)
            donated += n
            if n == 0:
                break
        if page < 2:
            dev.swipe(370, 300, 370, 900, 500, wait=1.2)
    if donated:
        log("done", f"Donaciones hechas: {donated}.")
    img = dev.shot()
    if chat_jump_visible(img):
        tap(62, 920, "volver al final del chat", 1.5)
        img = dev.shot()
    # pedir es gratis si la burbuja del castillo no lleva el icono verde de gema (cuenta atrás de pago)
    bubble = img.crop((640, 978, 705, 1015))
    gem_px = sum(1 for p in bubble.getdata() if p[1] > 140 and p[0] < 130 and p[2] < 130 and p[1] - p[0] > 40)
    if gem_px < 15:
        tap(640, 1020, "pedir tropas al castillo", 2)
        dlg = dev.shot()
        dlg.save(HERE / "ultima_peticion.png")
        g, o = color(dlg, 1250, 790, 4), color(dlg, 680, 790, 4)     # Enviar (verde) y Cancelar (naranja), fuera del texto
        if g[1] > 150 and g[1] > g[0] + 40 and g[1] > g[2] + 60 and o[0] > 200 and o[2] < 90:
            # sin escribir mensaje (pedido por el usuario 13-nov: es perder tiempo); se envía tal cual
            tap(1175, 745, "enviar petición", 1.5)
            log("done", "Tropas del castillo pedidas.")
    if chat_open():
        tap(787, 490, "cerrar chat", 1.5)
    go_home()


# ---------------- batalla normal ----------------
def good_target(loot, rule, full=()):
    g, e, d = (loot.get(k) or 0 for k in ("gold", "elixir", "dark"))
    if full:
        # lo que ya está lleno no cuenta: basta con que lo que aún falta merezca la pena
        need = [k for k in ("gold", "elixir", "dark") if k not in full]
        return any((loot.get(k) or 0) >= rule[k] > 0 for k in need)
    if rule["mode"] == "gold_or_elixir":
        return g >= rule["gold"] or e >= rule["elixir"]
    return (g >= rule["gold"] and e >= rule["elixir"]) or (d >= rule["dark"] > 0 and (g + e) >= rule["gold"])


def read_bar(img):
    """Casillas de la barra de batalla por colores (sin LLM): [{x, kind}] con kind troop/siege/hero/spell/used."""
    # dos filas: la carta del castillo (insignia) acaba un poco más arriba que las demás
    row = [sum(img.getpixel((x, 1060))) > 180 or sum(img.getpixel((x, 1045))) > 250   # 180: cartas rojas (super) son más oscuras
           for x in range(img.width)] + [False]
    cards, start = [], None
    for x, bright in enumerate(row):
        if bright and start is None:
            start = x
        elif not bright and start is not None:
            if x - start > 60:
                cards.append((start, x))
            start = None
    out = []
    for a, b in cards:
        r, g, bl = color(img, a + 14, 900, 3)
        if card_used(img, a):
            kind = "used"
        elif card_grey(img, a):
            kind = "hero"          # carta gris pero clara: la reina (su retrato es gris)
        elif max(r, g, bl) - min(r, g, bl) < 25 or max(r, g, bl) < 80:
            kind = "cc"            # esquina gris/oscura pero carta con color: insignia del castillo
        elif bl > 200 and r < 110 and 130 < g < 175:
            kind = "troop"
        elif r < 80 and g > 140 and bl > 160:
            kind = "siege"
        elif bl > 200 and 100 <= r <= 160:
            kind = "spell"
        else:
            kind = "hero"
        out.append({"x": (a + b) // 2, "left": a, "kind": kind})
    # lo del castillo: a la derecha de los héroes son hechizos; a la izquierda, tropas
    first = min((c["x"] for c in out if c["kind"] in ("hero", "spell")), default=10 ** 6)
    for c in out:
        if c["kind"] == "cc":
            c["kind"] = "spell" if c["x"] > first else "troop"
    return out


def card_grey(img, x_left):
    pts = [(14, 900), (115, 960), (115, 1000), (14, 960)]
    return all(max(c) - min(c) < 25 for c in (color(img, x_left + dx, y, 3) for dx, y in pts))


def card_used(img, x_left):
    """Casilla gastada: toda la carta en gris y oscurecida (la reina es gris pero clara; el castillo lleva insignia)."""
    return card_grey(img, x_left) and sum(img.getpixel((x_left + 60, 1060))[:3]) < 300


def slot_used(x_left):
    return card_used(dev.shot(), x_left)


SPEED_BTN = (1840, 615)


def speed_button(img):
    """El botón verde «1x» sólo sale en el último minuto de la batalla (zona 1790-1895 x 560-670)."""
    box = img.crop((1795, 565, 1890, 665)).resize((19, 20)).getdata()
    green = sum(1 for r, g, b in box if g > 180 and g > b + 60 and r < g)
    return green > 0.6 * len(box)


def _battle_sig(img):
    """Huella del botín restante y del % de daño: si no cambia, la batalla ya no avanza."""
    a = img.crop((40, 130, 300, 290)).convert("L").resize((52, 32))
    b = img.crop((1600, 780, 1900, 840)).convert("L").resize((60, 12))
    return list(a.getdata()) + list(b.getdata())


def wait_battle_end(stall_seconds=20, max_seconds=200, events=(), poll=3):
    """Espera al resultado; si el botín y el % llevan stall_seconds quietos, termina la batalla.
    events: [(instante, función)] que se ejecutan a su hora (habilidades, hielos…). En cuanto sale la
    pantalla de resultado se acaba, aunque queden eventos pendientes."""
    events = sorted(events, key=lambda e: e[0])
    t0 = time.time()
    last, since, fast = None, time.time(), False
    while time.time() - t0 < max_seconds:
        kind, img = screen()
        if kind == "result":
            return
        if kind == "home":                    # ya ha vuelto a la aldea
            return
        if not fast and speed_button(img):    # botón 1x del último minuto: x4 para acabar antes
            tap(*SPEED_BTN, "velocidad x4", 0.5)
            fast = True
        if events and events[0][0] <= time.time():
            try:
                events.pop(0)[1]()
            except Exception as e:
                log("warn", f"Evento de batalla falló: {e}")
            continue
        time.sleep(0.8 if events else poll)
        if any(not getattr(f, "is_snap", False) for _, f in events):
            continue                     # mientras queden habilidades/hielos no se da por parada
        sig = _battle_sig(img)
        if last is None or sum(abs(x - y) for x, y in zip(sig, last)) / len(sig) > 1.5:
            last, since = sig, time.time()
        elif time.time() - since >= stall_seconds:
            log("think", f"Botín y daño quietos {stall_seconds} s: termino la batalla.")
            break
    if screen()[0] == "result":
        return
    tap(137, 805, "terminar batalla", 1.5)
    tap(1167, 693, "confirmar", 5)
    for _ in range(5):
        if screen()[0] == "result":
            return
        time.sleep(2)


NO_TAP = [(15, 755, 262, 856), (255, 750, 905, 856),      # Terminar batalla, Potenciar ejército/héroes
          (1760, 545, 1915, 695), (1580, 690, 1915, 856)]    # botón de velocidad, Siguiente/daño


def _safe(x, y):
    return 20 <= x <= 1900 and 70 <= y <= 858 and not any(a <= x <= c and b <= y <= d for a, b, c, d in NO_TAP)


def _dilate(m, k):
    import cv2
    return cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))


def _map_geometry():
    m = vision.default_mask()
    import numpy as np
    ys, xs = np.nonzero(m)
    return {"corners": {"L": (int(xs.min()), 495), "R": (int(xs.max()), 495), "T": (960, int(ys.min())),
                        "B": (960, int(ys.max()))},
            "center": (float(xs.mean()), float(ys.mean())), "mask": m, "src": "mapa",
            "box": (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))}


def deployed(img, c):
    """Héroe/asedio en el campo: aparece su barra de vida verde encima de la carta."""
    return any(is_green(color(img, c["x"] + dx, 866, 3)) for dx in (-30, 0, 30))


def _slot_sig(img, c):
    a = img.crop((c["left"] + 5, 850, c["left"] + 135, 1060)).convert("L").resize((26, 42))
    return list(a.getdata())


def place_unit(c, points, label, wait=0.45):
    """Despliega un héroe/asedio: si la casilla cambia (sale barra de vida, se oscurece, sube la carta)
    es que ha salido; si no cambia nada, el punto no valía y se prueba el siguiente."""
    for p in points[:8]:
        refresh_card(dev.shot(), c)
        tap(c["x"], 975, f"seleccionar {label}", 0.3)
        tap(*humanize([p], 8, 6)[0], f"desplegar {label}", wait)
        for _ in range(2):                    # la barra de vida tarda un poco en salir
            img = dev.shot()
            if deployed(img, c) or card_used(img, c["left"]):
                return p
            time.sleep(0.35)
        # (antes valía «la carta ha cambiado»: 13-nov dio por desplegados 4 héroes que no salieron)
    log("warn", f"No he conseguido desplegar {label}.")
    return None


def bar_cards(img=None):
    img = img or dev.shot()
    cards = read_bar(img)
    for c in cards:
        c["name"] = vision.card_identity(img, c["left"])[0]
    return cards


def _find(cards, name):
    return next((c for c in cards if c["name"] == name), None)


MAP_SIDES = {"UL": ((262, 470), (950, -10)), "UR": ((970, -10), (1658, 470)),
             "LR": ((1658, 520), (1180, 858)), "LL": ((740, 858), (262, 520))}


def map_edge_points(side, n, inset=0.08):
    """Puntos junto al borde exterior del mapa (zoom mínimo) a lo largo del lado; inset = cuánto hacia dentro
    (el rombo de MAP_SIDES queda un poco por fuera de la zona jugable: sin inset caen en el bosque)."""
    (x1, y1), (x2, y2) = MAP_SIDES[side]
    out = []
    for i in range(n):
        t = 0.12 + 0.76 * (i + 0.5) / n
        x, y = x1 + (x2 - x1) * t, y1 + (y2 - y1) * t
        x, y = x + (960 - x) * inset, y + (470 - y) * inset
        if _safe(x, y):
            out.append((x, y))
    return out


def refresh_card(img, c):
    """La barra se desplaza un poco durante la batalla: posición actual de la carta (mismo nombre)."""
    if not c.get("name"):
        return c
    same = [b for b in bar_cards(img) if b["name"] == c["name"]]
    if not same:
        return c
    b = min(same, key=lambda b: abs(b["left"] - c["left"]))
    c.update(left=b["left"], x=b["x"])
    return c


def _card_sig(img, c):
    """Huella del número «xN» de la carta: cambia cada vez que sale una unidad."""
    a = img.crop((c["left"] + 40, 895, c["left"] + 125, 930)).convert("L").resize((34, 14))
    return list(a.getdata())


def _card_empty(img, c):
    """Carta sin número «xN» arriba (p. ej. castillo del clan sin tropas donadas): zona casi lisa."""
    from PIL import ImageStat
    a = img.crop((c["left"] + 40, 895, c["left"] + 125, 930)).convert("L")
    return ImageStat.Stat(a).stddev[0] < 20


BAR = {"scrolled": False}


def scroll_bar(right):
    """La barra tiene más cartas que pantalla: right=True enseña las de la derecha (hechizos del castillo)."""
    if right != BAR["scrolled"]:
        dev.swipe(*((1700, 975, 300, 975) if right else (300, 975, 1700, 975)), 350, wait=0.6)
        BAR["scrolled"] = right


def find_card(names):
    """Carta disponible con alguno de esos nombres, leyendo la barra en ese momento (se mueve sola).
    Sólo se desplaza la barra si no está en la parte visible."""
    for right in (BAR["scrolled"], not BAR["scrolled"]):
        scroll_bar(right)
        img = dev.shot()
        for c in bar_cards(img):
            if c["name"] in names and not card_used(img, c["left"]):
                return c
    return None


def tap_card(names, label):
    c = find_card(names)
    if c:
        tap(c["x"], 975, label, 0.2)
    return c


def cast_spell(names, x, y, label):
    """Lanza UN hechizo de la primera carta disponible de names en (x, y). False si no queda."""
    c = find_card(names)
    if not c:
        return False
    tap(c["x"], 975, f"seleccionar {label}", 0.25)
    tap(x, y, f"{label} → {int(x)},{int(y)}", 0.35)
    return True


REVIEW = HERE / "ultimo_ataque"


REVIEW.mkdir(exist_ok=True)


def result_stars(img):
    """Estrellas encendidas en la pantalla de resultado (blancas/plateadas) por píxeles: más fiable que el LLM."""
    lit = 0
    for x, y in ((770, 205), (960, 125), (1140, 205)):
        r, g, b = color(img, x, y, 6)
        if r + g + b > 560:
            lit += 1
    return lit


def save_plan_image(shot, plan):
    """Guarda la base con el plan dibujado (para revisar cada ataque): ultimo_ataque/plan.png."""
    import cv2
    import numpy as np
    for f in REVIEW.glob("*.png"):
        f.unlink()
    a = cv2.cvtColor(np.asarray(shot), cv2.COLOR_RGB2BGR)
    if plan:
        cnts, _ = cv2.findContours(plan["geo"]["mask"], cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        cv2.drawContours(a, cnts, -1, (255, 0, 255), 2)
        for x, y in plan["pts"]:
            cv2.circle(a, (int(x), int(y)), 9, (255, 255, 0), -1)
        for x, y in plan["zap"]:
            cv2.circle(a, (int(x), int(y)), 35, (0, 255, 255), 4)
        for x, y in plan["rest"]:
            cv2.circle(a, (int(x), int(y)), 35, (255, 0, 0), 4)
        for s in plan.get("storages") or []:      # oro en verde, elixir en rosa; grosor = peso en el botín
            col = (0, 220, 0) if s["kind"] == "gold" else (200, 0, 255)
            cv2.rectangle(a, (int(s["x"]) - 28, int(s["y"]) - 28), (int(s["x"]) + 28, int(s["y"]) + 28), col,
                          max(2, min(8, int(2 + 6 * s.get("w", 0)))))
        if plan.get("main"):
            cv2.circle(a, (int(plan["main"][0]), int(plan["main"][1])), 16, (0, 0, 255), -1)
        if plan["queen"]:
            k, (x, y) = plan["queen"]
            cv2.circle(a, (int(x), int(y)), 14, (0, 0, 255), -1)
            end = {"L": (1919, int(y)), "R": (0, int(y)), "T": (int(x), 860), "B": (int(x), 0)}[k]
            cv2.line(a, (int(x), int(y)), end, (0, 0, 255), 2)
    cv2.imwrite(str(REVIEW / "plan.png"), a)
    if plan and len(plan["zap"]) + len(plan["rest"]) < 2:      # para aprender skins nuevas de aéreas
        d = HERE / "sin_aereas"
        d.mkdir(exist_ok=True)
        shot.save(d / f"{int(time.time())}.png")
        for old in sorted(d.glob("*.png"))[:-30]:
            old.unlink()


def snap(tag):
    try:
        dev.shot().save(REVIEW / f"{tag}.png")
    except Exception:
        pass


HEROES = {"queen", "king", "warden", "prince", "champion", "duke"}


def find_storages(shot, geo):
    """Almacenes del rival para CUALQUIER TH, nivel y aspecto: [{kind: gold|elixir|dark, x, y}].
    1) SIFT contra las imágenes de la wiki (ref/almacenes: todos los niveles), ~3 s, sin modelo; 2) se completa
    con la cúpula rosa (color) y las plantillas de oro seguras; 3) sólo si no sale ningún almacén de oro, el
    modelo mira candidatos uno a uno (lo suyo pesa la mitad: en escenarios oscuros confunde cabañas y torres)."""
    mask = geo.get("mask")
    t0 = time.time()
    try:
        out = [dict(s) for s in vision.sift_storages(shot, mask)]
    except Exception as e:
        log("warn", f"SIFT de almacenes falló: {e}")
        out = []
    t_sift = time.time() - t0
    for s in vision.storages(shot, mask):
        if s["kind"] == "gold" and s["score"] < 0.62:
            continue
        if all(math.hypot(s["x"] - o["x"], s["y"] - o["y"]) > 45 for o in out):
            out.append(dict(s))
    # gemelos: con uno de cada tipo encontrado, sus copias en la misma aldea (mismo nivel = mismo aspecto)
    for kind in ("gold", "elixir"):
        seeds = sorted((o for o in out if o["kind"] == kind), key=lambda o: -o.get("score", 0))
        if seeds and len(seeds) < 4:
            for x, y, v in vision.twins(shot, seeds[0]["x"], seeds[0]["y"], mask, n=4 - len(seeds)):
                if all(math.hypot(x - o["x"], y - o["y"]) > 45 for o in out):
                    out.append({"kind": kind, "x": x, "y": y, "score": v, "twin": True,
                                "trust": seeds[0].get("trust", 1.0)})
    # un TH18 tiene 4 de oro y 4 de elixir: se quedan los más claros
    for kind in ("gold", "elixir"):
        same = sorted((o for o in out if o["kind"] == kind), key=lambda o: -o.get("score", 0))
        for extra in same[4:]:
            out.remove(extra)
    ng = sum(1 for o in out if o["kind"] == "gold")
    log("think", f"Almacenes por las imágenes de la wiki en {t_sift:.1f} s: " + ", ".join(
        f"{o['kind']} {int(o['x'])},{int(o['y'])}" for o in out) + ".")
    if ng or not CFG.get("storages_model", True):
        return out
    cands = [c for c in vision.storage_candidates(shot, mask)
             if c["hint"] == "oro" and all(math.hypot(c["x"] - s["x"], c["y"] - s["y"]) > 45 for s in out)][:6]
    t0, asked = time.time(), 0
    for c in cands:
        if sum(1 for s in out if s["kind"] == "gold") >= 4 or time.time() - t0 > 12:
            break
        x, y = int(c["x"]), int(c["y"]) - 8
        try:
            k = eyes.building_kind(shot.crop((x - 60, y - 60, x + 60, y + 60)).resize((240, 240)))
        except Exception:
            break
        asked += 1
        if k == "oro":
            out.append({"kind": "gold", "x": c["x"], "y": c["y"], "score": 0.6, "trust": 0.5})
    if asked:
        log("think", f"Sin almacenes de oro reconocidos: el modelo ha revisado {asked} candidatos en "
                     f"{time.time() - t0:.0f} s.")
    seed = next((o for o in out if o["kind"] == "gold"), None)
    if seed:
        for x, y, v in vision.twins(shot, seed["x"], seed["y"], mask, n=3):
            if all(math.hypot(x - o["x"], y - o["y"]) > 45 for o in out):
                out.append({"kind": "gold", "x": x, "y": y, "score": v, "twin": True, "trust": seed.get("trust", 1.0)})
    return out


def storage_map(shot, geo, loot=None):
    """Almacenes del rival por píxeles (`vision.storages`) con su peso: el botín disponible de cada recurso
    repartido entre sus almacenes (si no se leyó el botín, 1 por almacén). Devuelve (lista, pesos por
    cuadrante UL/UR/LL/LR, pesos por mitad L/R)."""
    c4 = geo["corners"]
    cx = (c4["L"][0] + c4["R"][0]) / 2              # ejes por las esquinas: la media de la máscara se va
    cy = (c4["T"][1] + c4["B"][1]) / 2              # hacia donde haya más edificios
    st = find_storages(shot, geo)
    n = {k: sum(1 for s in st if s["kind"] == k) for k in ("gold", "elixir", "dark")}
    loot = dict(loot or {})
    loot["dark"] = (loot.get("dark") or 0) * 60      # el oscuro vale mucho más por unidad
    tot = sum(loot.get(k) or 0 for k in ("gold", "elixir", "dark"))
    for s in st:
        v = loot.get(s["kind"]) or 0
        # botín en millones por almacén; sin botín leído, todos igual
        s["w"] = ((v / n[s["kind"]] / 1e6) if tot else 1.0) * s.get("trust", 1.0)
    quad = {k: 0.0 for k in ("UL", "UR", "LL", "LR")}
    for s in st:
        # pegado al eje (±60 px) cuenta a medias para cada lado
        fl = min(1.0, max(0.0, 0.5 - (s["x"] - cx) / 120))
        fu = min(1.0, max(0.0, 0.5 - (s["y"] - cy) / 120))
        s["left"] = fl
        for k, f in (("UL", fu * fl), ("UR", fu * (1 - fl)), ("LL", (1 - fu) * fl), ("LR", (1 - fu) * (1 - fl))):
            quad[k] += s["w"] * f
    half = {"L": quad["UL"] + quad["LL"], "R": quad["UR"] + quad["LR"]}
    return st, quad, half


STORAGE = {}                               # lado de la aldea con más almacenes (lo dice el modelo, por batalla)



# ---------------- ataque dinámico (13-nov) ----------------
# Sin coreografía fija por nombre de tropa: se lee la barra, todo el ejército entra por el tramo del borde que da
# a los almacenes con más botín y cada hechizo se lanza según su FUNCIÓN: los de defensas a las defensas, los de
# tropas sobre las propias tropas (donde se ve movimiento). Asedio y castillo: un toque y no se vuelven a pulsar.
SPELL_ROLES_DEFAULT = {
    "defensas": ["lightning", "cc_lightning", "earthquake", "freeze", "cc_freeze", "poison", "bat", "overgrowth",
                 "skeleton"],
    "tropas": ["rage", "heal", "jump", "haste", "invisibility", "totem", "revive", "clone", "recall"],
}
SPELL_ES = {"lightning": "rayo", "cc_lightning": "rayo", "earthquake": "terremoto", "freeze": "hielo",
            "cc_freeze": "hielo", "poison": "veneno", "bat": "murciélagos", "overgrowth": "crecimiento",
            "rage": "furia", "heal": "curación", "jump": "salto", "haste": "celeridad",
            "invisibility": "invisibilidad", "totem": "tótem", "revive": "resurrección", "clone": "clonación",
            "recall": "retorno", "skeleton": "esqueletos"}


def spell_roles():
    """{"defensas": set, "tropas": set}; editable en config.json → "spell_roles"."""
    r = CFG.get("spell_roles") or {}
    return {k: set(r.get(k) or v) for k, v in SPELL_ROLES_DEFAULT.items()}


def _role_of(name, kind, img, b):
    """Función de una carta reconocida por plantilla (o None si hay que preguntar al modelo)."""
    roles = spell_roles()
    if name in HEROES:
        return "hero"
    if name == "siege":
        return "siege"
    if name == "cc":
        return "empty" if _card_empty(img, b) else "cc"
    if name in roles["defensas"]:
        return "spell_def"
    if name in roles["tropas"]:
        return "spell_boost"
    if name is not None:
        return "troop"
    if kind == "siege":
        return "siege"
    if kind == "troop" and not _card_empty(img, b):
        return "troop"                        # fondo azul de tropa: no hace falta preguntar
    return None


SIEGE_NAMES = {"wall_wrecker", "battle_blimp", "stone_slammer", "siege_barracks", "log_launcher", "flame_flinger",
               "battle_drill", "troop_launcher", "sky_wagon"}
HERO_NAMES = {"archer_queen": "queen", "barbarian_king": "king", "grand_warden": "warden", "royal_champion": "champion",
              "minion_prince": "prince", "dragon_duke": "duke"}
SPELL_NAMES = {"healing": "heal"}


def avatar_card(av):
    """Retrato de la wiki → (nombre interno, función). Los hechizos, por su función en `spell_roles` (uno
    desconocido se lanza sobre las tropas)."""
    n = re.sub(r"\d+$", "", av.lower().replace("hero_", ""))
    if n.endswith("_spell"):
        n = SPELL_NAMES.get(n[:-6], n[:-6])
        return n, "spell_def" if n in spell_roles()["defensas"] else "spell_boost"
    if n in HERO_NAMES:
        return HERO_NAMES[n], "hero"
    if n in SIEGE_NAMES:
        return "siege", "siege"
    return n.replace("p.e.k.k.a", "pekka").replace("super_yeti", "superyeti").replace(".", ""), "troop"


def bar_inventory():
    """Todas las cartas de la barra (también las de la derecha, que hay que desplazar): [{name, role, x, left,
    scrolled}]. Las que no reconocen las plantillas las clasifica el modelo EN SEGUNDO PLANO (con la lista de
    hechizos de cada función); quedan con role None hasta que contesta."""
    out, ask = [], []
    for right in (False, True):
        scroll_bar(right)
        img = dev.shot()
        hero_x = 10 ** 6
        for b in read_bar(img):
            if b["left"] < 10 or b["left"] > 1790 or card_used(img, b["left"]):
                continue                       # cortada por el borde (se ve entera al desplazar) o gastada
            name = vision.card_identity(img, b["left"])[0]
            role = None
            if name is None and not _card_empty(img, b):
                # sin plantilla: el retrato de la wiki (cualquier tropa, héroe, hechizo o asedio de cualquier TH)
                av, sc = vision.avatar_identity(img, b["left"])
                if av:
                    name, role = avatar_card(av)
                    log("think", f"Carta en x={b['left']} reconocida por su retrato: {av} ({sc}) → {name}, {role}.")
            if role is None:
                role = _role_of(name, b["kind"], img, b)
            if role == "hero":
                hero_x = min(hero_x, b["left"])
            if role == "siege" and name is None and b["left"] > hero_x:
                role = None                    # a la derecha de los héroes sólo hay hechizos: el color engaña
            if role == "empty":
                continue
            c = dict(b, name=name, role=role, scrolled=right)
            if right and (any(o["name"] == name for o in out if name) or not name and b["left"] < 900):
                continue                       # ya vista con la barra sin desplazar
            out.append(c)
            if role is None:
                ask.append((c, img))
    scroll_bar(False)

    def classify():
        roles = spell_roles()
        for c, img in ask[:4]:                 # como mucho 4 preguntas (~2 s cada una)
            try:
                k = eyes.card_kind(img, c["left"], [SPELL_ES.get(n, n) for n in sorted(roles["defensas"])],
                                   [SPELL_ES.get(n, n) for n in sorted(roles["tropas"])])
            except Exception:
                k = None
            c["role"] = {"tropa": "troop", "heroe": "hero", "asedio": "siege", "hechizo_defensas": "spell_def",
                         "hechizo_tropas": "spell_boost"}.get(k)
            if c["role"] is None:              # sin respuesta clara: nada se queda en la barra
                c["role"] = "spell_boost" if c["kind"] == "spell" else "troop"
            log("think", f"Carta sin plantilla en x={c['left']}: el modelo dice «{k}».")
    th = threading.Thread(target=classify, daemon=True)
    th.start()
    return out, th


def pick(c):
    """Pone la barra donde está la carta y devuelve su posición actual, o None si ya está gastada. Las cartas
    con nombre se buscan por nombre (la barra se mueve un poco); las demás, por su sitio."""
    scroll_bar(c["scrolled"])
    img = dev.shot()
    bar = read_bar(img)
    if c.get("name"):
        same = [b for b in bar if vision.card_identity(img, b["left"])[0] == c["name"]]
        if not same and c["name"] in ("freeze", "lightning", "cc_freeze", "cc_lightning", "rage", "totem",
                                      "earthquake", "revive"):
            scroll_bar(not c["scrolled"])      # al gastarse cartas la barra se reordena: mirar al otro lado
            img = dev.shot()
            same = [b for b in read_bar(img) if vision.card_identity(img, b["left"])[0] == c["name"]]
            if same:
                c["scrolled"] = BAR["scrolled"]
            else:                              # vuelve a donde estaba: la buscará por su sitio
                scroll_bar(c["scrolled"])
                img = dev.shot()
                bar = read_bar(img)
        if not same:
            # 13-nov: tras lanzar un terremoto la carta queda resaltada y elevada, la plantilla no la reconoce y
            # el 2.º terremoto no salía. Por su sitio, si allí hay una carta sin gastar
            same = [b for b in bar if abs(b["left"] - c["left"]) < 50]
    else:
        same = [b for b in bar if abs(b["left"] - c["left"]) < 50]
    same = [b for b in same if not card_used(img, b["left"])
            and (c.get("role") == "hero" or not card_grey(img, b["left"]))]   # x0 en gris = gastada
    if not same:
        return None
    b = min(same, key=lambda b: abs(b["left"] - c["left"]))
    c.update(left=b["left"], x=b["x"])
    return c


def entry_points(geo, st, ads):
    """Tramo del borde por donde entra TODO: los puntos del borde del mapa con más botín cerca (cada almacén
    pesa su parte del botín y cuenta menos cuanto más lejos), agrupados alrededor del mejor (≤340 px) y
    separados ≥90 px. Sin almacenes: frente a la defensa aérea más expuesta o, si no, el lado izquierdo."""
    # candidatos densos y HASTA LAS PUNTAS (13-nov: almacenes junto a la punta de abajo, pegados a la barra de
    # cartas, y el punto más cercano quedaba a 200 px porque cada lado se recortaba un 12 % por los extremos)
    cands = []
    for (x1, y1), (x2, y2) in MAP_SIDES.values():
        for i in range(21):
            t = 0.03 + 0.94 * i / 20
            x, y = x1 + (x2 - x1) * t, y1 + (y2 - y1) * t
            q = (x + (960 - x) * 0.12, y + (470 - y) * 0.12)
            if _safe(*q):
                cands.append(q)
    cx = (geo["corners"]["L"][0] + geo["corners"]["R"][0]) / 2
    cy = (geo["corners"]["T"][1] + geo["corners"]["B"][1]) / 2
    targets = [(s["x"], s["y"], s["w"]) for s in st if s.get("w", 0) > 0]
    if not targets:
        targets = [(x, y, 1.0) for x, y in ads] or [(cx - 400, cy, 1.0)]

    def value(p):
        return sum(w / (1 + math.hypot(p[0] - x, p[1] - y) / 220) for x, y, w in targets)
    best = max(cands, key=value)
    # tramo COMPACTO alrededor del mejor (antes se ensanchaba hasta 580 px para reunir 5 puntos y el ejército
    # acababa repartido por todo un lado, lejos del botín): mejor 3-4 puntos juntos frente a los almacenes
    near = sorted((p for p in cands if math.hypot(p[0] - best[0], p[1] - best[1]) <= 360), key=value, reverse=True)
    out = []
    for gap in (85, 60):
        out = []
        for p in near:
            if all(math.hypot(p[0] - q[0], p[1] - q[1]) >= gap for q in out):
                out.append(p)
            if len(out) >= 7:
                break
        if len(out) >= 4:
            break
    # de un extremo al otro del tramo (el del medio es la entrada principal: héroes, asedio, castillo)
    ax, ay = best[0] - cx, best[1] - cy
    out.sort(key=lambda p: (p[0] - cx) * -ay + (p[1] - cy) * ax)
    # cada punto, lo más dentro posible SIN pisar la aldea (contorno ensanchado ~20 px = zona roja): 13-nov, en
    # una aldea que llenaba el mapa los puntos fijos al 12 % caían entre edificios y no salía ni una tropa
    md = _dilate(geo["mask"].astype("uint8"), 41)
    M = (960, 470)

    def ray(p, k):                            # mismo rayo del borde del mapa, a otra profundidad k
        ex, ey = (p[0] - 0.12 * M[0]) / 0.88, (p[1] - 0.12 * M[1]) / 0.88
        return ex + (M[0] - ex) * k, ey + (M[1] - ey) * k

    def legal(p):
        for k in (0.2, 0.16, 0.12, 0.09, 0.06):
            q = ray(p, k)
            if _safe(*q) and not md[min(1079, int(q[1])), min(1919, int(q[0]))]:
                return q
        return ray(p, 0.04)
    outer = [q for q in (ray(p, 0.04) for p in out) if _safe(*q)]
    legal_pts = [legal(p) for p in out]
    main = legal_pts[min(range(len(out)), key=lambda i: math.hypot(out[i][0] - best[0], out[i][1] - best[1]))]
    return legal_pts, main, (cx, cy), outer


def inset_points(pts, centre, k):
    """Los mismos puntos movidos k (fracción) hacia el centro; k<0 hacia fuera. Sólo los tocables."""
    cx, cy = centre
    return [(x + (cx - x) * k, y + (cy - y) * k) for x, y in pts if _safe(x + (cx - x) * k, y + (cy - y) * k)]


def humanize(pts, dx=14, dy=10):
    """Como una persona: cada toque un poco desplazado y en otro orden (nunca dos veces el mismo píxel)."""
    out = []
    for x, y in pts:
        for _ in range(4):
            q = (x + random.uniform(-dx, dx), y + random.uniform(-dy, dy))
            if _safe(*q):
                break
        else:
            q = (x, y)
        out.append(q)
    random.shuffle(out)
    return out


# Papel de cada tropa en el ejército (datos, no coreografía): los tanques van primero y concentrados, los
# rompemuros con ellos, el resto después por todo el tramo y el apoyo (sanadoras…) detrás. Lo desconocido = daño.
TROOP_ROLES = {"tank": ["giant", "golem", "pekka", "superyeti", "super_yeti", "yeti", "giant_skeleton", "lavahound",
                        "lava_hound", "ice_golem", "super_giant", "electro_titan", "root_rider", "battle_ram",
                        "goblin_giant", "boxer_giant", "mighty_yak", "druid"],
               "breaker": ["wallbreaker", "wall_breaker", "super_wallbreaker", "super_wall_breaker"],
               "support": ["healer", "apprentice_warden"]}


def troop_role(name):
    roles = CFG.get("troop_roles") or TROOP_ROLES
    for r, names in roles.items():
        if name in names:
            return r
    return "dps"


EDGE = {"tag": None}
PROBE_TROOPS = ["archer", "barbarian", "goblin", "minion", "skeleton", "bat", "sneaky_archer", "super_archer",
                "super_barbarian", "sneaky_goblin", "super_minion", "wizard"]   # baratas: para tantear
PROBE = {"k": 0.0}                         # profundidad que valió en el último tanteo                       # qué variante de puntos funcionó en la última batalla


def edge_variants(pts, centre, outer):
    """Variantes de los puntos de entrada, de la que funcionó la última vez a las demás. Cada escenario pone
    el borde jugable en otro sitio (13-nov: en la nieve sólo valían puntos MÁS FUERA del borde del mapa)."""
    v = [("contorno", pts), ("borde", list(outer)), ("fuera", inset_points(pts, centre, -0.05)),
         ("muy fuera", inset_points(pts, centre, -0.10)), ("dentro", inset_points(pts, centre, 0.06))]
    v = [(t, q) for t, q in v if q]
    v.sort(key=lambda tq: tq[0] != EDGE["tag"])
    return v


def unleash(c, variants, label):
    """Suelta TODA la carta: ráfagas (2 toques por punto) mientras quede algo; si una ráfaga no saca nada (zona
    roja o fuera del mapa) se pasa a la siguiente variante de puntos. Devuelve la variante que funcionó (o
    None). Tocar una carta vacía es inocuo (el juego dice «Selecciona una unidad diferente»)."""
    v, sig, good, partial = 0, None, None, 0
    gone = lambda im: card_grey(im, c["left"]) or _card_empty(im, c)   # vacía: gris o ya sin «xN»
    for burst in range(10):
        if not pick(c):
            return good or (variants[v] if burst else None)
        img = dev.shot()
        if burst and gone(img):
            return variants[v]
        now = _card_sig(img, c)
        if sig is not None:
            if sum(abs(a - b) for a, b in zip(now, sig)) / len(now) > 6:
                good = variants[v]             # el número de la carta ha bajado: estos puntos valen
                partial += 1
                # 3.ª ráfaga que sólo saca algunas: la mayoría de estos puntos caen en zona roja (13-nov: 5-8
                # ráfagas por carta en una aldea pegada al borde, 76 s de despliegue) → siguiente variante
                if partial >= 3 and v + 1 < len(variants):
                    v, partial = v + 1, 0
            else:
                time.sleep(0.4)                # la carta tarda en ponerse gris al vaciarse: mirar otra vez
                img = dev.shot()
                if gone(img) or not pick(c):
                    return variants[v]
                v += 1                         # la ráfaga anterior no sacó nada: otros puntos
                if v >= len(variants):
                    log("warn", f"{label}: no consigo desplegarla.")
                    return good
        sig = now
        tag, use = variants[v]
        dev.tap(c["x"] + random.uniform(-12, 12), 975 + random.uniform(-15, 15))
        time.sleep(random.uniform(0.08, 0.2))
        taps = humanize([q for q in use for _ in range(2)])     # 2 por punto: x7 sale de una vez
        dev.taps(taps)
        log("act", f"desplegar {label} (puntos: {tag})", "taps", [[int(x), int(y)] for x, y in taps])
        time.sleep(random.uniform(0.18, 0.4))
    return good


def once(c, p, label):
    """Asedio / castillo: UN toque en el campo y nunca más (volver a pulsar la carta del asedio activa su
    habilidad, pedido del usuario)."""
    if not pick(c):
        return
    dev.tap(c["x"], 975)
    time.sleep(0.12)
    dev.tap(int(p[0]), int(p[1]))
    log("act", f"{label} (un solo toque)", "tap", [[int(p[0]), int(p[1])]])
    time.sleep(0.3)


def cast_at(c, x, y, label, n=1):
    """n hechizos de la carta c en (x, y) (seleccionada UNA vez: la carta sigue seleccionada entre lanzamientos;
    tocar de más con la carta vacía es inocuo). False si la carta ya está gastada."""
    if not pick(c):
        return False
    x, y = (x, y) if _safe(x, y) else (min(1880, max(30, x)), min(850, max(80, y)))
    tap(c["x"] + random.uniform(-12, 12), 975 + random.uniform(-15, 15), f"seleccionar {label}",
        random.uniform(0.1, 0.25))
    for i in range(n):
        q = humanize([(x, y)], 10, 8)[0]
        tap(*q, f"{label} → {int(q[0])},{int(q[1])}", random.uniform(0.2, 0.4))
    return True


class Battle:
    """Una batalla: inventario, despliegue y la vigilancia de después (hechizos y habilidades a su momento)."""

    def __init__(self, shot, geo, ads, st, pts, main, centre):
        self.shot, self.geo, self.ads, self.st = shot, geo, list(ads), st
        self.pts, self.main, self.centre = pts, main, centre
        self.heroes = {}                       # nombre -> instante en que toca su habilidad (0 = hecha)
        self.hero_cards = {}
        self.front = None                      # (x, y, t): donde pelean nuestras tropas
        self.prev = None
        self.hit = {}                          # objetivo -> instante del último hechizo de defensas
        self.last_boost = self.last_def = 0
        self.sweeps = []
        self.t0 = time.time()
        self.outer = []                        # los mismos puntos en el borde extremo del mapa (reserva)

    # -- despliegue --
    def deploy(self):
        cards, th = bar_inventory()
        self.cards = cards
        log("think", "Barra: " + ", ".join(f"{c['name'] or '?'}({c['role'] or '?'})" for c in cards))
        # 1) hechizos de defensas que conviene lanzar YA: rayos a las aéreas más cercanas a la entrada (antes de
        #    que lleguen las tropas), terremotos al núcleo
        ads = sorted(self.ads, key=lambda a: math.hypot(a[0] - self.main[0], a[1] - self.main[1]))
        per = max(1, CFG["accounts"].get(self.acc, {}).get("lightning_per_ad", 3))
        for c in [c for c in cards if c["role"] == "spell_def" and c["name"] in ("lightning", "cc_lightning")]:
            if not ads:
                break
            for i in range(12):
                ax, ay = ads[min(i // per, len(ads) - 1)]
                if not cast_at(c, ax, ay, f"rayo a la aérea {int(ax)},{int(ay)}"):
                    break
            c["done"] = not pick(c)
        core = (self.centre[0] + (self.main[0] - self.centre[0]) * 0.15,
                self.centre[1] + (self.main[1] - self.centre[1]) * 0.15)
        self.core = core
        # 2) todo el ejército por el tramo, en el orden de la barra; la variante de puntos que funciona se
        #    aprende con la primera carta y la usan las siguientes, los héroes y el asedio
        self.variants = edge_variants(self.pts, self.centre, self.outer)
        troops = [c for c in cards if c["role"] == "troop"]
        order = {"tank": 0, "breaker": 1, "dps": 2, "support": 3}
        troops.sort(key=lambda c: order[troop_role(c["name"])])   # estable: dentro de cada grupo, la barra
        # tanteo desactivado por defecto (13-nov: 9 ataques con tanteo 1,1★ de media frente a 1,58★ sin él; las
        # tropas de tanteo salen sueltas y antes que el resto)
        legal = self.probe(troops) if CFG.get("probe") else []
        if len(legal) >= 2:
            self.variants.insert(0, ("probado", legal))
            self.good = legal
        log("think", "Orden del ejército: " + ", ".join(f"{c['name'] or 'tropa'} ({troop_role(c['name'])})"
                                                       for c in troops) + ".")
        prev = None
        for c in troops:
            r = troop_role(c["name"])
            if prev == "tank" and r != "tank":
                time.sleep(random.uniform(1.5, 3.0))    # que los tanques se adelanten y atraigan las defensas
            # tanques y rompemuros concentrados en el centro del tramo; el apoyo, detrás (más fuera)
            if r in ("tank", "breaker"):
                vs = [(t, self.near_main(q)[:3 if r == "tank" else 2]) for t, q in self.variants]
            elif r == "support":
                time.sleep(random.uniform(0.8, 1.6))
                vs = [(t, self.near_main(q)[:3]) for t, q in self.variants if t != "dentro"]
            else:
                vs = self.variants
            self.learn(unleash(c, vs, c["name"] or "tropa"))
            prev = r
        # 3) héroes con el ejército (habilidad a los ~7 s); el punto donde sale uno se usa para los demás
        th.join(timeout=10)                     # cartas que el modelo estaba clasificando
        for c in cards:
            if c["role"] == "troop" and not c.get("name"):
                self.learn(unleash(c, self.variants, "tropa"))
        for c in cards:
            if c["role"] != "hero" or not pick(c):
                continue
            ok = place_unit(c, self.unit_points(), f"{c['name'] or 'héroe'} con el ejército", 0.3)
            if ok:
                self.unit_ok = ok
                key = c["name"] or f"héroe@{c['left']}"
                self.heroes[key] = time.time() + CFG.get("hero_ability_seconds", 7)
                self.hero_cards[key] = c
        # 4) asedio: como un héroe (sólo vale con su barra de vida; sin desplegar, tocar la carta sólo la
        #    selecciona; desplegado, ya no se vuelve a tocar: nunca su habilidad). Castillo: un toque.
        for c in cards:
            if c["role"] == "siege" and pick(c):
                ok = place_unit(c, self.unit_points(), "máquina de asedio (sin habilidad)", 0.3)
                self.unit_ok = ok or getattr(self, "unit_ok", None)
                c["role"] = "done"
            elif c["role"] == "cc":
                once(c, self.edge_main(), "tropas del castillo")
                c["role"] = "done"
        # 5) terremotos (todos al mismo sitio, se suman) al núcleo, ya con la tropa en camino
        for c in [c for c in cards if c["role"] == "spell_def" and c["name"] == "earthquake"]:
            cast_at(c, core[0], core[1], "terremotos al núcleo", n=6)
            c["done"] = not pick(c)            # si queda alguno, lo lanza el barrido final
        self.t0 = time.time()
        self.sweeps = [self.t0 + 6, self.t0 + 16]
        snap("despliegue")

    def probe(self, troops):
        """Tantea cada punto de entrada con UNA tropa, como una persona: si el número de la carta baja, el punto
        vale; si no, el mismo rayo un poco más hacia fuera. Empieza por la profundidad que valió la última vez y
        para con 4 puntos buenos. 13-nov: sin tantear, una aldea pegada al borde costó 76 s de despliegue; el
        primer tanteo (dos llamadas a ADB y dos capturas por toque) 24 s; así ~0,6 s por toque."""
        t0, legal, taps = time.time(), [], 0
        # se tantea con lo más barato (13-nov: tanteando con la 1.ª carta, los globos salían sueltos antes que el
        # resto y morían solos; con el tanteo bajaron las estrellas): baratas primero, luego de atrás adelante
        cheap = CFG.get("probe_troops") or PROBE_TROOPS
        cards = sorted(troops, key=lambda c: (c["name"] not in cheap, -troops.index(c)))
        depths = [0.0, -0.03, -0.06, -0.10, -0.14]
        depths.sort(key=lambda k: k != PROBE.get("k", 0.0))
        img = None
        for p in self.near_main(self.pts):
            if len(legal) >= 4:
                break
            while cards and not pick(cards[0]):
                cards.pop(0)                   # carta gastada: se tantea con la siguiente
                img = None
            if not cards:
                break
            c = cards[0]
            for k in depths:
                q = p if k == 0.0 else (inset_points([p], self.centre, k) or [None])[0]
                if q is None:
                    continue
                img = img or dev.shot()
                before = _card_sig(img, c)
                qq = humanize([q], 6, 5)[0]
                dev.taps([(c["x"] + random.uniform(-10, 10), 975 + random.uniform(-12, 12)), qq])   # un comando
                taps += 1
                time.sleep(0.25)
                img = dev.shot()
                now = _card_sig(img, c)
                if card_grey(img, c["left"]) or _card_empty(img, c) or                         sum(abs(x - y) for x, y in zip(now, before)) / len(now) > 6:
                    legal.append(q)
                    PROBE["k"] = k
                    break
        log("think", f"Tanteo: {len(legal)} puntos de entrada valen ({taps} toques, {time.time() - t0:.1f} s).",
            "", [[int(x), int(y)] for x, y in legal])
        return legal

    def learn(self, good):
        """Variante de puntos que ha funcionado: la primera para todo lo que queda (y la próxima batalla)."""
        if isinstance(good, tuple) and good[1]:
            self.good = good[1]
            EDGE["tag"] = good[0]
            self.variants.sort(key=lambda tq: tq[0] != good[0])

    def near_main(self, pts):
        return sorted(pts, key=lambda p: math.hypot(p[0] - self.main[0], p[1] - self.main[1]))

    def edge_main(self):
        """Punto para lo que sólo tiene un toque (asedio, castillo): uno de los que ya han funcionado."""
        if getattr(self, "unit_ok", None):
            return self.unit_ok
        pts = getattr(self, "good", None) or self.outer or [self.main]
        return self.near_main(pts)[0]

    def unit_points(self):
        """Puntos para héroes y asedio: donde ya salió uno; luego los de la variante que funcionó con las
        tropas alternando los extremos del tramo (13-nov: un extremo entero caía en zona roja y sólo se
        probaba ese); luego las demás variantes."""
        def ends(q):
            q = self.near_main(q)
            out = []
            while q:
                out.append(q.pop(0))
                if q:
                    out.append(q.pop())
            return out
        out = ([self.unit_ok] if getattr(self, "unit_ok", None) else []) + ends(getattr(self, "good", None) or [])
        for _, q in self.variants:
            out += ends(q)[:2]
        seen, uniq = set(), []
        for p in out:
            k = (int(p[0]) // 20, int(p[1]) // 20)
            if k not in seen:
                seen.add(k)
                uniq.append(p)
        return uniq

    # -- vigilancia --
    def spells(self, role):
        return [c for c in self.cards if c["role"] == role and not c.get("done") and not c.get("spent")]

    def busy(self):
        """Algo pendiente que justifica seguir mirando aunque la batalla parezca quieta."""
        now = time.time()
        return any(t for t in self.heroes.values()) or bool(self.sweeps) or bool(
            self.front and now - self.front[2] < 6 and now - self.t0 < 90
            and (self.spells("spell_def") or [s for s in self.spells("spell_boost") if s["name"] != "revive"]))

    def tick(self, img):
        now = time.time()
        if self.prev is not None:
            a = vision.activity(self.prev, img, self.geo.get("mask"))
            if a:
                x, y, s = a
                if self.front and now - self.front[2] < 3:
                    x, y = 0.6 * x + 0.4 * self.front[0], 0.6 * y + 0.4 * self.front[1]
                self.front = (x, y, now)
        self.prev = img
        # habilidades de los héroes
        for k, t in list(self.heroes.items()):
            if t and now >= t:
                c = self.hero_cards[k]
                if pick(c):
                    tap(c["x"], 975, f"habilidad de {k}", 0.2)
                self.heroes[k] = 0
                return
        # repaso: lo que no haya salido (sin guardar nada)
        if self.sweeps and now >= self.sweeps[0]:
            self.sweeps.pop(0)
            for c in self.cards:               # héroes que no salieron: otra vez, del borde extremo hacia dentro
                key = c["name"] or f"héroe@{c['left']}"
                if c["role"] == "hero" and key not in self.heroes and not c.get("retried") and pick(c):
                    c["retried"] = True
                    if place_unit(c, self.unit_points(), f"{key} (no había salido)", 0.3):
                        self.heroes[key] = time.time() + CFG.get("hero_ability_seconds", 7)
                        self.hero_cards[key] = c
            for c in self.cards:
                if c["role"] == "troop" and pick(c):
                    log("think", f"Queda {c['name'] or 'tropa'} sin salir: la suelto.")
                    self.learn(unleash(c, self.variants, c["name"] or "tropa"))
            return
        if not self.front or now - self.front[2] > 2.5:
            return                             # sin ver a nuestras tropas no se lanza nada
        fx, fy, _ = self.front
        cx, cy = self.centre
        d = math.hypot(cx - fx, cy - fy) or 1
        ahead = lambda k: (fx + (cx - fx) / d * k, fy + (cy - fy) / d * k)
        # resurrección: en cuanto cae un héroe, donde pelean
        img_bar = None
        for k, c in self.hero_cards.items():
            if c.get("dead"):
                continue
            img_bar = img_bar or dev.shot()
            if card_grey(img_bar, c["left"]):
                c["dead"] = True
                rv = next((s for s in self.spells("spell_boost") if s["name"] == "revive"), None)
                if rv and cast_at(rv, fx, fy, f"resurrección: ha caído {k}"):
                    return
        # de defensas: a la defensa a la que llegan (aérea a ≤230 px de la tropa) o, si no hay, justo delante
        defs = self.spells("spell_def")
        if defs and now - self.last_def >= 3 and now - self.t0 > 3:
            tgt = None
            for ax, ay in sorted(self.ads, key=lambda a: math.hypot(a[0] - fx, a[1] - fy)):
                if math.hypot(ax - fx, ay - fy) <= 230 and now - self.hit.get((ax, ay), 0) > 7:
                    tgt = (ax, ay)
                    break
            if tgt is None and now - self.t0 > 12:
                tgt = ahead(90)
            if tgt:
                s = defs[0]
                if cast_at(s, *tgt, f"{SPELL_ES.get(s['name'], 'hechizo')} a las defensas"):
                    self.hit[tgt] = now
                    s["tries"] = s.get("tries", 0) + 1
                if not pick(s) or s.get("tries", 0) >= 12:
                    s["spent"] = True
                self.last_def = now
                return
        # de tropas: sobre el grupo, un poco por delante; uno cada ~4 s
        boosts = [s for s in self.spells("spell_boost") if s["name"] != "revive"]
        if boosts and now - self.last_boost >= 4 and now - self.t0 > 4:
            s = boosts[0]
            k = 70 if s["name"] == "totem" else 35       # el tótem delante, para que las defensas le apunten
            if cast_at(s, *ahead(k), f"{SPELL_ES.get(s['name'], 'hechizo')} sobre las tropas"):
                s["tries"] = s.get("tries", 0) + 1
            if not pick(s) or s.get("tries", 0) >= 12:
                s["spent"] = True
            self.last_boost = now


def _flush(b):
    """Antes de acabar, se gasta TODO lo que quede (pedido del usuario 13-nov): hechizos de defensas a la aérea
    más cercana a la tropa (rayos) o al núcleo; de tropas y resurrección, donde se vio pelear por última vez
    (o al núcleo); y un último repaso de héroes y tropas que no salieran."""
    if getattr(b, "flushed", False):
        return
    b.flushed = True
    b.sweeps = [0]
    try:
        b.tick(dev.shot())
    except Exception as e:
        log("warn", f"Repaso final: {e}")
    core = getattr(b, "core", b.centre)
    spot = (b.front[0], b.front[1]) if b.front else core
    for c in b.cards:
        if c["role"] not in ("spell_def", "spell_boost") or not pick(c):
            continue
        if c["role"] == "spell_def":
            ads = sorted(b.ads, key=lambda a: math.hypot(a[0] - spot[0], a[1] - spot[1]))
            tgt = ads[0] if ads and c["name"] in ("lightning", "cc_lightning") else core
        else:
            tgt = spot
        log("think", f"Queda {SPELL_ES.get(c['name'], c['name'] or 'hechizo')}: lo lanzo antes de acabar.")
        cast_at(c, *tgt, f"{SPELL_ES.get(c['name'], 'hechizo')} (lo que quedaba)", n=6)
        c["spent"] = True


def fight(b, stall_seconds=15, max_seconds=200):
    """Vigila la batalla: decisiones de `b` en cada vuelta, x4 en el último minuto y fin cuando todo está
    desplegado y el botín y el daño llevan `stall_seconds` quietos."""
    t0 = time.time()
    snaps = [t0 + dt for dt in (15, 35, 60, 90)]
    last, since, fast = None, time.time(), False
    while time.time() - t0 < max_seconds:
        kind, img = screen()
        if kind in ("result", "home"):
            return
        if not fast and speed_button(img):
            tap(*SPEED_BTN, "velocidad x4", 0.5)
            fast = True
        if snaps and time.time() >= snaps[0]:
            snaps.pop(0)
            snap(f"batalla{3 - len(snaps)}")
        try:
            b.tick(img)
        except Exception as e:
            log("warn", f"Fallo en la batalla: {e}")
        sig = _battle_sig(img)
        if last is None or sum(abs(x - y) for x, y in zip(sig, last)) / len(sig) > 1.5 or b.busy():
            last, since = sig, time.time()
        elif time.time() - since >= stall_seconds:
            if not getattr(b, "flushed", False):
                _flush(b)                      # nada se queda sin usar; si eso reactiva la batalla, se sigue
                last, since = None, time.time()
                continue
            log("think", f"Botín y daño quietos {stall_seconds} s: termino la batalla.")
            break
        if not getattr(b, "flushed", False) and time.time() - b.t0 > 75:
            _flush(b)                          # a los 75 s ya no hay motivo para guardar nada
        time.sleep(0.3)
    if screen()[0] == "result":
        return
    tap(137, 805, "terminar batalla", 1.5)
    tap(1167, 693, "confirmar", 5)
    for _ in range(5):
        if screen()[0] == "result":
            return
        time.sleep(2)


def battle_geometry(img):
    """Contorno de la aldea y defensas aéreas (sin modelo). Si una aérea cae fuera del contorno, el contorno
    está mal y se usa el rombo del mapa entero."""
    geo = vision.village_geometry(img, fallback=True)
    ads = vision.find_air_defenses(img)
    if geo["src"] != "mapa" and ads:
        big = _dilate(geo["mask"], 61)
        if any(not big[min(1079, int(y)), min(1919, int(x))] for x, y in ads):
            geo = _map_geometry()
    return geo, ads


def dynamic_attack(acc, shot, loot):
    """Ataque completo: dónde está el botín → por dónde entrar → desplegar → vigilar hasta el final."""
    geo, ads = battle_geometry(shot)
    try:
        st, quad, half = storage_map(shot, geo, loot)
    except Exception as e:
        log("warn", f"No he podido buscar los almacenes: {e}")
        st, quad = [], {}
    pts, main, centre, outer = entry_points(geo, st, ads)
    ng = sum(1 for s in st if s["kind"] == "gold")
    log("think", f"Almacenes: {ng} de oro y {len(st) - ng} de elixir; botín por cuadrante "
                 + ", ".join(f"{k} {v:.1f}" for k, v in quad.items())
                 + f". Entro por {int(main[0])},{int(main[1])} ({len(pts)} puntos); {len(ads)} aéreas vistas.",
        "", [[int(x), int(y)] for x, y in pts])
    plan = {"geo": geo, "pts": pts, "zap": ads, "rest": [], "queen": None, "storages": st, "main": main}
    try:
        save_plan_image(shot, plan)
    except Exception as e:
        log("warn", f"No he guardado la imagen del plan: {e}")
    BAR["scrolled"] = False
    b = Battle(shot, geo, ads, st, pts, main, centre)
    b.outer = outer
    b.acc = acc
    b.deploy()
    fight(b, stall_seconds=CFG.get("stall_seconds", 15))


# ---------------- evento de tropa en masa (p. ej. «M.O.M.M.A en masa») ----------------
# Con "mass_event": true en config.json, en cuanto la 1.ª carta de la barra de batalla (la de más a la izquierda)
# sale GRIS, el ataque es mecánico: primera aldea que salga, toda esa carta rodeando la aldea, esperar al 100 %
# y a por la siguiente. Sin leer botín, sin planear y sin el modelo. Si la carta deja de salir, ataque normal.
MASS = {"until": 0, "collected": 0, "clan": 0}
MASS_ORDER = (3, 1, 5, 0, 6, 2, 4)            # dentro de cada lado, primero el centro: si faltan tropas, rodean igual


def mass_on():
    return bool(CFG.get("mass_event")) and MASS["until"] > time.time()


def mass_event_card(img):
    """La carta del evento en masa. Por su dibujo (plantillas `mass_cards` de cards/, p. ej. «momma»: el
    9-nov-2026 salió en la 4.ª casilla, fondo azul, «x25», en cualquier sitio de la barra) o, si no, la primera
    carta con el fondo gris."""
    bar = read_bar(img)
    names = set(CFG.get("mass_cards", ["momma"]))
    for c in bar:
        if c["kind"] != "used" and vision.card_identity(img, c["left"])[0] in names:
            return c
    if not bar or bar[0]["left"] > 400:
        return None
    c = bar[0]
    cols = [color(img, c["left"] + dx, y, 3) for dx, y in CFG.get("mass_card_points", ((10, 905), (10, 1010), (122, 905)))]
    grey = all(max(k) - min(k) < 30 and 70 < sum(k) / 3 < 235 for k in cols)
    return c if grey else None


def _card_lum(img, c):
    a = img.crop((c["left"] + 5, 895, c["left"] + 135, 1050)).convert("L")
    return sum(a.getdata()) / (a.width * a.height)


# borde del mapa con el zoom mínimo, en orden: esquina izquierda → arriba → esquina derecha → abajo. Abajo el
# rombo se corta con la barra de cartas (y=858): ese tramo no es borde y no se usa.
MAP_BORDER = [(262, 520), (262, 470), (950, -10), (970, -10), (1658, 470), (1658, 520), (1180, 858)]
MAP_BORDER_LOW = [(740, 858), (262, 520)]


def _border_samples(poly, step=12):
    out = []
    for (x1, y1), (x2, y2) in zip(poly, poly[1:]):
        L = math.hypot(x2 - x1, y2 - y1)
        for i in range(max(1, int(L // step))):
            t = i / max(1, int(L // step))
            out.append((x1 + (x2 - x1) * t, y1 + (y2 - y1) * t))
    return out


# de fuera a dentro; los negativos caen POR FUERA del rombo habitual: sirven si la cámara no se alejó del todo
# (escenario de lava: la aldea llenaba la pantalla y todos los anillos caían dentro). Con la cámara bien
# alejada caen en el bosque y no hacen nada.
MASS_INSETS = (0.04, 0.06, 0.08, 0.10, -0.03, -0.07, -0.11, -0.16, 0.12, 0.145, 0.17, 0.20, 0.235, 0.27, 0.31,
               0.36, 0.41)


# Las cuatro PUNTAS del mapa (pedido del usuario 2026-11-09 21:15: «literalmente los extremos, las puntas»):
# izquierda, derecha, arriba (lo más arriba tocable, y≈80) y abajo (lo más abajo antes de la barra y sin los
# botones de la izquierda). Cada punta: el vértice y dos toques un poco abiertos a lo largo de sus lados.
MASS_TIPS = {
    # vértices visibles con el zoom mínimo; arriba y abajo el vértice queda tapado (contador / barra de cartas),
    # así que se usan los dos puntos del BORDE más cercanos a esa punta que aún se pueden tocar
    "izquierda": [(262, 495), (280, 482), (280, 508)],
    "derecha": [(1658, 495), (1640, 482), (1640, 508)],
    "arriba-izq": [(833, 78), (815, 90)],
    "arriba-der": [(1087, 78), (1105, 90)],
    "abajo-der": [(1190, 850), (1210, 836)],
    "abajo-izq": [(578, 742), (560, 729)],
}
MASS_TIP_INSETS = (0.03, 0.06, -0.04, 0.09, -0.08, 0.13, 0.18)   # de lo más extremo hacia dentro (y fuera)


def mass_tip_taps(total=25):
    """Una sola tanda de toques: en cada inset (de fuera a dentro), las 4 puntas por turnos, ~total/4 por punta.
    Las tropas salen en los primeros toques válidos, así que cada punta se queda con las suyas en su sitio más
    extremo; los toques que sobran no hacen nada («Selecciona una unidad diferente»)."""
    per = -(-total // len(MASS_TIPS))
    out = []
    for ins in CFG.get("mass_tip_insets", MASS_TIP_INSETS):
        for pts in MASS_TIPS.values():
            ring = [(x + (960 - x) * ins, y + (470 - y) * ins) for x, y in pts]
            ring = [q for q in ring if _safe(*q)]
            if ring:
                out += [ring[i % len(ring)] for i in range(per)]
    return out


def mass_rings(n_angles=32, offset=0.0):
    """Anillos de puntos, del borde extremo del mapa hacia dentro, en `n_angles` ángulos repartidos por todo el
    perímetro tocable. Cada escenario pone el borde jugable en otro sitio (en el del barco pirata, el de
    MAP_BORDER cae fuera): se prueba de fuera a dentro y cada tropa sale en el punto válido más exterior."""
    raw = _border_samples(MAP_BORDER) + _border_samples(MAP_BORDER_LOW)
    base = [raw[int((i + offset) * len(raw) / n_angles) % len(raw)] for i in range(n_angles)]
    rings = []
    for ins in CFG.get("mass_insets", MASS_INSETS):
        ring = [(x + (960 - x) * ins, y + (470 - y) * ins) for x, y in base]
        rings.append([q for q in ring if _safe(*q)])
    return rings


def _spread(pts, k):
    """k puntos repartidos entre `pts` (en orden de perímetro), no los k primeros."""
    if k >= len(pts):
        return list(pts)
    return [pts[int(i * len(pts) / k)] for i in range(k)]


def mass_left(img, c):
    """Cuántas tropas quedan en la carta del evento («x19»). Texto literal + regex."""
    b = (c["left"], 885, c["left"] + 140, 945)
    d = eyes.ask(img.crop(b).resize((420, 180)), 'Copia exactamente el texto blanco de arriba. Responde {"text": "..."}')
    m = re.search(r"x\s*(\d+)", str(d.get("text") or ""), re.I)
    return int(m[1]) if m else None


def mass_points(img, n, inset=None):
    """n puntos por el BORDE EXTREMO del mapa, repartidos a la misma distancia por todo el perímetro tocable
    (esquinas izquierda y derecha incluidas): ahí siempre se puede desplegar. Lo pidió el usuario: el contorno
    de la aldea por colores fallaba en aldeas grandes y los toques caían en la zona roja (seleccionaban
    edificios). Sin modelo."""
    inset = CFG.get("mass_inset", 0.08) if inset is None else inset
    raw = _border_samples(MAP_BORDER) + _border_samples(MAP_BORDER_LOW)
    pts = [(x + (960 - x) * inset, y + (470 - y) * inset) for x, y in raw]
    pts = [q for q in pts if _safe(*q)]
    if not pts:
        return [], "borde"
    # mismos pasos a lo largo del perímetro tocable: todos los ángulos cubiertos
    k = len(pts) / n
    return [pts[int(i * k) % len(pts)] for i in range(n)], "borde del mapa"


def mass_attack(acc, c):
    """Evento en masa: toda la carta gris rodeando la aldea, esperar al 100 % y volver. Sin pensar."""
    MASS["until"] = time.time() + 1200
    t0 = time.time()
    dev.zoom_out(3)                           # bien alejada: el borde del mapa tiene que verse
    img = dev.shot()
    c = mass_event_card(img) or c             # tras el zoom la barra puede haberse movido un poco
    lum0 = _card_lum(img, c)
    used, why = 0, "quedan tropas"
    # sin pensar: todas las puntas de golpe y una sola comprobación al final
    pts = mass_tip_taps(int(CFG.get("mass_count", 25)))
    # en tandas de 30 toques (cada toque de Android tarda ~0,14 s: 195 de golpe pasaban de los 30 s de adb y
    # rompían la batalla). La 1.ª tanda = la punta más extrema de las 6; casi siempre basta con ella.
    done = False
    for i in range(0, len(pts), 30):
        chunk = pts[i:i + 30]
        tap(c["x"], 975, "seleccionar la carta del evento", 0.15)
        dev.taps([(int(x), int(y)) for x, y in chunk])
        log("act", f"desplegar tropas del evento en las puntas del mapa (toques {i + 1}-{i + len(chunk)})", "taps",
            [[int(x), int(y)] for x, y in chunk])
        time.sleep(0.4)
        img = dev.shot()
        if screen(img)[0] in ("result", "home") or _card_lum(img, c) < lum0 * 0.75:
            done = True
            break
    rings = [] if done else mass_rings()
    why = "carta vacía" if done else why
    for k, ring in enumerate(rings):          # reserva (rara): el borde entero, de fuera a dentro
        if not ring:
            continue
        tap(c["x"], 975, "seleccionar la carta del evento", 0.15)
        for j in range(0, len(ring), 30):
            dev.taps([(int(x), int(y)) for x, y in ring[j:j + 30]])
        used = k + 1
        log("act", f"quedaban tropas: borde, anillo {k + 1} ({len(ring)} puntos)", "taps",
            [[int(x), int(y)] for x, y in ring])
        time.sleep(0.5)
        img = dev.shot()
        if screen(img)[0] in ("result", "home"):
            why = "batalla ya terminada"
            break
        if _card_lum(img, c) < lum0 * 0.75:
            why = "carta vacía"
            break
    log("think", f"Evento: puntas + {used} anillo(s) de reserva ({why}).")
    snap("despliegue")
    # desde el borde tardan en llegar y hay ratos sin daño mientras andan: 30 s quietos antes de rendirse
    wait_battle_end(stall_seconds=CFG.get("mass_stall_seconds", 30), max_seconds=200, poll=1)
    res_img = dev.shot()
    res_img.save(REVIEW / "resultado.png")
    if screen(res_img)[0] == "result":
        tap(960, 925, "volver a casa", 1.5)
        wait_for(lambda: screen()[0] == "home", 8, 0.4)
    for _ in range(4):
        if go_home():
            break
        time.sleep(2)
    LAST_GAIN.clear()
    LAST_GAIN["mass"] = True                   # botín sin leer: no cuenta como ataque «seco»
    log("done", f"Ataque en masa en {acc} terminado en {int(time.time() - t0)} s.")
    return True


def finding_rivals(img):
    """Pantalla blanca de «Buscando rivales…» (el servidor tarda): casi toda la imagen muy clara."""
    a = img.convert("L").resize((48, 27))
    if sum(1 for v in a.getdata() if v > 225) > 0.75 * 48 * 27:
        return True
    # nubes que aún no se han ido: la aldea se ve desvaída (casi sin color y muy clara) (03:41, 10-nov)
    hsv = np.asarray(img.resize((96, 54)).convert("HSV")).astype(np.float32) / 255
    return hsv[..., 1].mean() < 0.16 and hsv[..., 2].mean() > 0.72


READS = {"t": 0}


def log_reads():
    """Cada 15 min: cuántas lecturas de pantalla se hicieron sin modelo (OCR/píxeles) y cuántas con él."""
    if time.time() - READS["t"] >= 900:
        READS["t"] = time.time()
        o, m, dudas = eyes.summary()
        log("think", f"Lecturas de pantalla desde el arranque: {o} sin modelo, {m} con el modelo"
                     + (f" (el OCR dudó y preguntó al modelo: {', '.join(f'{k} ×{v}' for k, v in dudas.items())})"
                        if dudas else "") + ".")


def attack(acc):
    """Busca un rival que cumpla el criterio, ataca, espera y apunta el botín. True si atacó."""
    log_reads()
    rule = CFG["accounts"][acc]["min_loot"]
    if not main_village():
        return False
    mass = mass_on()                     # evento en masa: nada de leer almacenes ni elegir botín
    if not mass or time.time() - MASS["collected"] > 600:
        try:
            collect_resources()
        except Exception as e:
            log("warn", f"No he podido recoger recursos: {e}")
        MASS["collected"] = time.time()
    full = ()
    cap = CFG["accounts"][acc]["capacity"]
    if cap and not mass:
        shot = dev.shot()
        res = eyes.my_resources(shot)
        a = CFG["accounts"][acc]
        fr = a.get("full_ratio", CFG["full_ratio"])
        ratio = {"gold": fr, "elixir": fr, "dark": a.get("dark_full_ratio", CFG.get("dark_full_ratio", 0.5))}
        full = tuple(k for k in ("gold", "elixir", "dark") if k in cap and (bar_full(shot, k) or (
                     cap_ok(k, cap[k]) and (res.get(k) or 0) >= cap[k] * ratio[k])))
        focus = a.get("farm_focus")
        if focus:
            full = tuple(k for k in ("gold", "elixir", "dark") if k not in focus or k in full)
        if full:
            log("think", f"Ya lleno en {acc}: {', '.join(full)} → sólo busco lo que falta.")
    home_before = {} if mass else eyes.my_resources(dev.shot())
    if not mass:
        note_resources(acc, home_before)
    check_stop()                         # última ocasión de obedecer al visor antes de gastar el ejército
    if mass:                                  # en masa: esperar a cada pantalla en vez de dormir fijo
        tap(120, 960, "abrir Batalla", 0.6)
        wait_for(battle_menu_open, 5, 0.3)
    else:
        tap(120, 960, "abrir Batalla", 2.5)
    if not battle_menu_open():
        log("warn", "El menú Batalla no se ha abierto.")
        go_home()
        return False
    if mass:
        tap(400, 800, "Buscar batalla (NORMAL, tarjeta izquierda)", 1.0)
        army = lambda: is_green(color(dev.shot(), 1820, 990, 4))
        wait_for(lambda: screen()[0] == "search" or army(), 5, 0.3)
        if screen()[0] != "search" and army():
            tap(1695, 962, "Atacar (confirmar ejército)", 1.0)
    else:
        tap(400, 800, "Buscar batalla (NORMAL, tarjeta izquierda)", 3)
        if screen()[0] != "search" and is_green(color(dev.shot(), 1820, 990, 4)):
            tap(1695, 962, "Atacar (confirmar ejército)", 8)
    loot = None
    for n in range(CFG["accounts"][acc]["max_searches"]):
        check_stop()
        kind, img = screen()
        waited = 0                    # las nubes entre bases a veces tardan; y «Buscando rivales…», más
        step = 1 if mass else 3
        while kind != "search" and (waited < 15 or finding_rivals(img) and waited < 90):
            time.sleep(step)
            waited += step
            kind, img = screen()
        if kind != "search":
            if True:
                img.save(HERE / "no_busqueda.png")
                log("warn", "No estoy en la búsqueda; vuelvo a casa (captura en no_busqueda.png).")
                go_home()
                return False
        if n == 0 and CFG.get("mass_event"):
            c = mass_event_card(img)
            for _ in range(3 if not c else 0):  # la barra a veces aún está apareciendo: se mira otra vez
                time.sleep(0.8)
                img = dev.shot()
                c = mass_event_card(img)
                if c:
                    break
            if c:
                MASS["miss"] = 0
                if not mass:
                    img.save(REVIEW / "evento_detectado.png")
                    log("think", "Carta del evento en masa en la barra: ataques en masa (sin mirar botín).")
                return mass_attack(acc, c)
            if mass:
                MASS["miss"] = MASS.get("miss", 0) + 1
                img.save(HERE / "evento_no_visto.png")
                if MASS["miss"] >= 3:          # tres búsquedas seguidas sin la carta: el evento ha terminado
                    MASS["until"] = 0
                    log("think", "Ya no sale la carta del evento (3 búsquedas seguidas): vuelvo al ataque normal.")
                else:
                    log("think", f"No veo la carta del evento ({MASS['miss']}/3): ataque normal esta vez.")
        loot = eyes.loot_available(img)
        ok = good_target(loot, rule, full) or n == CFG["accounts"][acc]["max_searches"] - 1
        log("think", f"Rival: {loot['gold']} oro / {loot['elixir']} elixir / {loot['dark']} oscuro → "
                     f"{'ATACO' if ok else 'siguiente'}")
        if ok:
            break
        tap(1750, 765, "Siguiente", 5)
    dev.zoom_out(2)
    # el mismo ataque para todas las cuentas: lee la barra y la aldea y decide (sin coreografía por tropa)
    dynamic_attack(acc, dev.shot(), loot)
    res_img = dev.shot()
    res_img.save(REVIEW / "resultado.png")
    res = {}
    try:
        if screen(res_img)[0] == "result":
            res = eyes.battle_result(res_img)
            res["stars"] = result_stars(res_img)
    except Exception as e:
        log("warn", f"No he leído la pantalla de resultado: {e}")
    tap(960, 925, "volver a casa", 7)
    after = {}
    for _ in range(4):
        if go_home():
            after = eyes.my_resources(dev.shot())
            note_resources(acc, after)       # el visor se actualiza tras cada ataque
            break
        time.sleep(2)
    gained = {k: max(0, (after.get(k) or 0) - (home_before.get(k) or 0)) for k in ("gold", "elixir", "dark")}
    if res.get("gold") is not None and res.get("elixir") is not None:
        gained = {k: res.get(k) or 0 for k in ("gold", "elixir", "dark")}   # lo que pone el juego, exacto
    loot_log(acc, "batalla normal", res.get("stars"), res.get("pct"), gained)
    if res.get("pct") is not None:
        log("think", f"Resultado: {res.get('stars')}★ {res.get('pct')} %.")
    LAST_GAIN.clear()
    LAST_GAIN.update(gained)
    log("done", f"Ataque terminado en {acc}: +{gained['gold']} oro, +{gained['elixir']} elixir, +{gained['dark']} oscuro.")
    return True


def collect_resources():
    """Recoge las burbujas de colectores/minas/taladros de la aldea (sólo toques sobre la propia aldea)."""
    if not go_home():
        return
    # De una en una y volviendo a mirar tras cada toque (QA): si el juego recoge de golpe todas las de un tipo,
    # las demás ya no tienen burbuja y tocarlas seleccionaría el edificio. Por debajo de y=700 (donde sale la
    # barra de un edificio seleccionado) sólo se toca si no hay ninguno seleccionado.
    tapped = []
    for _ in range(30):
        img = dev.shot()
        sel = selection_bar(img)
        pts = [(x, y) for x, y in eyes.resource_bubbles(img)
               if safe_map_point(x, y) and (y < 700 or not sel)
               and all(abs(x - tx) > 25 or abs(y - ty) > 25 for tx, ty in tapped)]
        if not pts:
            break
        x, y = min(pts, key=lambda p: p[1])  # de arriba abajo: lejos de la barra de abajo
        dev.tap(x, y, 0.5)
        tapped.append((x, y))
    if tapped:
        log("act", f"recoger {len(tapped)} burbujas de recursos", "taps", [[int(x), int(y)] for x, y in tapped])
        deselect()


BARS = {"main": (("gold", 1700, 57, (1380, 85, 1910, 240)), ("elixir", 1700, 130, (1380, 160, 1910, 315)),
                 ("dark", 1750, 204, (1380, 235, 1910, 390))),
        "builder": (("gold", 1560, 52, (1020, 80, 1910, 240)), ("elixir", 1700, 130, (1020, 160, 1910, 315)))}


BAR_FILL = {"gold": (76, 1497), "elixir": (150, 1497), "dark": (222, 1590)}   # fila sin cifras, extremo izquierdo
BAR_HUE = {"gold": (0.08, 0.2), "elixir": (0.75, 0.9), "dark": (0.72, 0.9)}


def bar_full(img, res):
    """¿La barra de arriba a la derecha (aldea principal) está llena? Se mide por píxeles, sin el modelo: el
    relleno es un color plano que crece de derecha a izquierda; lleno = llega al extremo izquierdo. Sirve
    de segunda opinión cuando la capacidad leída está mal (310 000 → 3101000 dejaba el oscuro «a medias»)."""
    y, left = BAR_FILL[res]
    ref = img.getpixel((1830, y))[:3]
    h, s, _ = colorsys.rgb_to_hsv(*(c / 255 for c in ref))
    lo, hi = BAR_HUE[res]
    if not (lo <= h <= hi and s >= 0.5):
        return False                       # casi vacía (en 1830 ya hay fondo) o tapada por una ventana
    x = 1830
    while x > left - 15 and sum(abs(a - b) for a, b in zip(img.getpixel((x - 1, y))[:3], ref)) < 40:
        x -= 1
    return x <= left + 8                   # 8 px ≈ 3 % de la barra (medido: lleno empieza entre +0 y +5)


CAP_MAX = {"main": {"gold": 50_000_000, "elixir": 50_000_000, "dark": 600_000},
           "builder": {"gold": 10_000_000, "elixir": 10_000_000}}


def cap_ok(res, v, village="main"):
    """¿Es una capacidad posible? (fuera de rango = lectura rota: el oscuro nunca pasa de ~500k)."""
    return bool(v) and 1000 <= v <= CAP_MAX[village].get(res, 50_000_000)


def extra_digit(long, short):
    """¿`long` es `short` con una cifra metida? Es el error típico del modelo con el separador de miles:
    «310 000» → 3101000, «28 500 000» → 128500000. Una mejora real nunca multiplica por 10."""
    a, b = str(long), str(short)
    return len(a) == len(b) + 1 and any(a[:i] + a[i + 1:] == b for i in range(len(a)))


def read_capacity(acc, village="main", have=None):
    """Lee el máximo de cada recurso tocando su barra (ventana «Máx.») y lo guarda: si se amplían los
    almacenes o aparece un recurso nuevo, no hay que tocar nada a mano. `have`: lo que hay ahora (un
    máximo nunca es menor que lo que hay: decide entre dos lecturas que difieren en una cifra)."""
    have = have or {}
    key = "capacity" if village == "main" else "builder_capacity"
    a = CFG["accounts"].get(acc, {})
    cap = dict(a.get(key) or {})
    changed = False
    for res, x, y, box in BARS[village]:
        dev.tap(x, y, 0.9)
        img = dev.shot()

        def read(scale):
            d = eyes.ask(img.crop(box).resize(((box[2] - box[0]) * scale, (box[3] - box[1]) * scale)),
                         'Lee el número blanco que va después de "Máx.:". Responde {"max": N} sin espacios; '
                         '{"max": null} si no aparece ese texto.')
            return eyes._num(d.get("max"))
        v = read(2)
        old = cap.get(res) if cap_ok(res, cap.get(res), village) else None   # lo guardado también puede estar mal
        now = have.get(res) or 0
        if v and not cap_ok(res, v, village):
            log("think", f"{acc}: capacidad de {res} imposible ({v}); me quedo con {old}.")
            v = None
        elif v and old and extra_digit(v, old) and now <= old:
            log("think", f"{acc}: la lectura de {res} ({v}) es {old} con una cifra de más; me quedo con {old}.")
            v = None
        elif v and old and extra_digit(v, old):
            pass                                   # tengo más que lo guardado: lo guardado era el corto y malo
        elif v and old and extra_digit(old, v) and now > v:
            log("think", f"{acc}: la lectura de {res} ({v}) es menor que lo que tengo ({now}); me quedo con {old}.")
            v = None
        elif v and old and extra_digit(old, v):
            pass                                   # lo guardado era el que tenía la cifra de más: se corrige
        elif v and v != old and read(3) != v:
            # el modelo a veces mete una cifra de más (4251500 → 47251500): sólo vale si otra lectura coincide
            log("think", f"{acc}: lectura dudosa de la capacidad de {res} ({v}); me quedo con {old}.")
            v = None
        if v and v != cap.get(res):
            log("think", f"{acc}: capacidad de {res}: {cap.get(res)} → {v}.")
            cap[res] = int(v)
            changed = True
        dev.tap(1885, 425, 0.5)                # cierra la burbuja (borde del mapa, sin edificios ni botones)
    if changed:
        a[key] = cap
        save_account_field(acc, key, cap)


def note_resources(acc, res, village="main"):
    """Guarda lo último leído de cada cuenta/aldea para el visor."""
    try:
        st = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    except (OSError, ValueError):
        st = {}
    allr = st.get("resources", {})
    allr[f"{acc}|{village}"] = {**{k: res.get(k) for k in ("gold", "elixir", "dark")}, "ts": time.time()}
    set_state(resources=allr)


def storages_full(acc, kinds=None):
    if not main_village():
        return False
    shot = dev.shot()
    res = eyes.my_resources(shot)              # antes de tocar las barras: con la burbuja abierta no se lee
    bars = {k for k in ("gold", "elixir", "dark") if bar_full(shot, k)}
    try:
        read_capacity(acc, have=res)           # el máximo real, después de cada ataque
    except Exception as e:
        log("warn", f"No he podido leer la capacidad: {e}")
    saved = CFG["accounts"][acc].get("capacity") or {}
    if not saved:
        return False
    cap = {k: v for k, v in saved.items() if cap_ok(k, v)}
    for k in saved.keys() - cap.keys():
        log("warn", f"{acc}: la capacidad guardada de {k} ({saved[k]}) es imposible; decide la barra.")
    note_resources(acc, res)
    a = CFG["accounts"][acc]
    r = a.get("full_ratio", CFG["full_ratio"])
    dr = a.get("dark_full_ratio", CFG.get("dark_full_ratio", 0.5))

    def by_number(k):
        return k in cap and (res.get(k) or 0) >= cap[k] * (dr if k == "dark" else r)
    kinds = kinds or a.get("farm_focus") or [k for k in ("gold", "elixir", "dark") if k in saved]   # farm_focus: sólo eso
    full = all(k in bars or by_number(k) for k in kinds)    # barra al tope = lleno, diga lo que diga la lectura
    by_bar = [k for k in kinds if k in bars and not by_number(k)]
    log("think", f"{acc}: oro {res['gold']}/{cap.get('gold')}, elixir {res['elixir']}/{cap.get('elixir')}, "
                 f"oscuro {res['dark']}/{cap.get('dark')} → {'LLENO' if full else 'falta'}"
                 + (f" (barra llena en {', '.join(by_bar)} aunque las cifras no cuadren)" if by_bar else ""))
    return full


# ---------------- aldea nocturna ----------------
def safe_map_point(x, y, bars_bottom=420):
    """¿El punto está sobre el mapa y lejos de cualquier botón o barra de la interfaz?"""
    if not (240 < x < 1690 and 150 < y < 860):
        return False                                 # bordes: botones de la izquierda, barra inferior, derecha
    if x > 1450 and y < bars_bottom:
        return False                                 # barras de recursos (la nocturna tiene menos: acaban antes)
    if x > 1730 and 440 < y < 640:
        return False                                 # botón Tienda
    if x < 420 and y < 260:
        return False                                 # perfil / nivel
    return True


def travel_boat(to_builder):
    W = "el barco amarrado en el agua o la burbuja con un barquito encima"
    drags = [(500, 700, 1300, 250)] * 3 if to_builder else [(1400, 400, 400, 600)] * 3
    if not go_home():
        return False
    dev.zoom_out(2)
    for i in range(len(drags) + 1):
        shot = dev.shot()
        hit = vision.find_template(shot, ["boat_bubble"] if to_builder else ["boat_back", "boat_bubble"])
        if hit and hit[1] < 860:             # burbuja del barco: se toca justo debajo (el barco)
            pos = (hit[0], hit[1] + 60)
            log("think", f"Barco por plantilla en {hit[0]},{hit[1]} ({hit[2]:.2f}).")
        else:
            pos = eyes.find(shot, W)
        if pos and safe_map_point(*pos, bars_bottom=420 if to_builder else 260):
            tap(*pos, "subir al barco", 9)
            go_home()
            if in_builder() == to_builder:
                return True
            log("warn", "Toqué el supuesto barco pero no he cambiado de aldea.")
        elif pos:
            log("warn", f"El modelo dice que el barco está en {int(pos[0])},{int(pos[1])}: zona de botones, no lo toco.")
        if i < len(drags):
            dev.swipe(*drags[i], 600, wait=1.2)
    log("warn", "No encuentro el barco.")
    return False


def cart_window_open(img):
    """Ventana 'Carro de elixir': X roja arriba-derecha (1640,105) y banda de madera naranja-marrón abajo."""
    x = color(img, 1640, 105, 3)
    wood = [color(img, px, 840, 3) for px in (1260, 1700)]
    return x[0] > 150 and x[1] < 70 and all(90 < c[0] < 170 and 40 < c[1] < 110 and c[2] < 40 for c in wood)


CART = {"pos": None}       # dónde se abrió el carro la última vez (la vista tras el zoom y el arrastre es fija)


def collect_cart():
    """Recoge el elixir del Carro de elixir (junto al muelle de la aldea nocturna) si hay algo."""
    if not go_home() or not in_builder():
        return
    dev.zoom_out(2)
    dev.swipe(1400, 400, 600, 650, 600, wait=1.5)       # el muelle (barco + carro) queda a la vista
    img = None
    if CART["pos"]:                                     # sitio conocido: sin preguntar al modelo
        tap(*CART["pos"], "abrir carro de elixir (sitio conocido)", 1.5)
        img = dev.shot()
        if not cart_window_open(img):
            img, CART["pos"] = None, None
            go_home()
    queries = ['la pequeña carreta de madera (carro de elixir) que está en la hierba, abajo a la izquierda del '
               'muelle de madera del barco',
               'la burbuja blanca con una gota de elixir morada que está en la orilla, junto al muelle de madera del '
               'barco (NO las de dentro de la aldea)']
    shot = None if img else dev.shot()
    for q in ([] if img else queries):
        pos = eyes.find(shot, q)
        if not pos or not safe_map_point(*pos, bars_bottom=260) or pos[1] > 700:
            continue
        tap(*pos, "abrir carro de elixir", 2)
        img = dev.shot()
        if cart_window_open(img):
            CART["pos"] = pos
            break
        img = None
        go_home()
        shot = dev.shot()
    if img is None:
        log("think", "No he podido abrir el carro de elixir esta vez.")
        return
    if is_green(color(img, 1410, 945, 5)) or is_green(color(img, 1330, 935, 5)):   # borde del botón (el centro es texto blanco)
        before = eyes.my_resources(img)
        tap(1410, 908, "Recoger elixir del carro", 2.5)
        after = eyes.my_resources(dev.shot())
        got = max(0, (after.get("elixir") or 0) - (before.get("elixir") or 0))
        log("done", f"Carro de elixir recogido: +{got} elixir.")
        if got:
            loot_log(current, "Carro de elixir (aldea nocturna)", None, None, {"elixir": got})
    else:
        img.save(HERE / "carro_vacio.png")          # para comprobar que de verdad está vacío
        log("think", "El carro de elixir está vacío (captura en carro_vacio.png).")
    tap(1640, 105, "cerrar carro de elixir", 1.5)
    go_home()


# ---- batalla de la aldea nocturna: estado de cada carta por colores ----
def _purple(c):
    return c[0] > 170 and c[2] > 220 and c[1] < 110


def bb_cards(img):
    """(x de la máquina o None, [x de cada tropa]) a partir de las cartas de la barra inferior."""
    found = [c["x"] for c in read_bar(img)]
    machine = 193 if any(abs(x - 193) < 30 for x in found) or min(color(img, 193, 862, 3)) > 60 else None
    troops = []
    for i in range(10):                            # casillas fijas cada 152 px; las vacías tienen borde punteado
        x = 364 + 152 * i
        if any(abs(x - fx) < 30 for fx in found) or min(color(img, x - 42, 870, 3)) > 225:
            troops.append(x)
        elif troops:
            break
    return machine, troops


def bb_state(img, x):
    """'pendiente' (sin desplegar), 'lista' (desplegada con habilidad cargada), 'recargando' (desplegada,
    habilidad gastada) o 'muerta'."""
    raised = min(color(img, x - 42, 870, 3)) > 225          # casilla del número arriba = carta subida
    if raised:
        return "lista" if _purple(color(img, x + 30, 870, 3)) else "recargando"
    hdr = color(img, x + 30, 900, 3)
    if _purple(hdr):
        return "pendiente"
    return "muerta"


def bb_pending(img, troops):
    return [x for x in troops if bb_state(img, x) == "pendiente"]


def bb_live(img):
    """¿Batalla nocturna lista para desplegar, aunque siga la cuenta atrás del principio (o el paso a la
    2ª fase)? Basta con ver en la barra al menos 2 cartas sin desplegar (cabecera morada): soltar la
    primera tropa empieza la batalla sin esperar a que acabe la cuenta."""
    _, troops = bb_cards(img)
    return len(bb_pending(img, troops)) >= 2


# Puntos donde soltar tropas en la nocturna, alternando lados: según la base, la cámara la deja a la izquierda
# (el borde derecho, x≈1400, está libre) o a la derecha (entonces la zona libre es la izquierda). Ninguno toca
# botones: «Rendirse» y «Ejército potenciado» están abajo a la izquierda (y > 680) y la velocidad a la derecha.
BB_DROPS = [(1400, 450), (560, 400), (1400, 570), (700, 290), (560, 520), (1400, 630)]
BB_DROP = {"i": 0}                                  # el último punto que funcionó se prueba primero


def bb_deploy(xs, labels):
    """Suelta seguidas las cartas `xs` (seleccionar + tocar el mapa) y lo comprueba con una sola captura al
    final; las que sigan sin subir se reintentan en el siguiente punto de BB_DROPS."""
    machine = next((x for x in xs if labels[x] == "máquina"), None)
    order = [BB_DROP["i"]] + [k for k in range(len(BB_DROPS)) if k != BB_DROP["i"]]
    for k in order:
        if not xs:
            return
        bx, by = BB_DROPS[k]
        pts = []
        for x in xs:
            dev.tap(x, 935)                         # 935: lejos del botón de cambiar tropa (abajo)
            time.sleep(0.25)
            px, py = bx + random.uniform(-25, 25), by
            dev.tap(px, py)
            time.sleep(0.2)
            pts.append([int(px), int(py)])
        log("act", "desplegar " + ", ".join(labels[x] for x in xs), "taps", pts)
        time.sleep(0.3)
        img = dev.shot()
        # la máquina no tiene estado por colores: con un intento basta (como antes)
        troops = [x for x in xs if x != machine]
        xs = [x for x in troops if bb_state(img, x) == "pendiente"]
        if len(xs) < len(troops):
            if k != BB_DROP["i"]:
                log("think", f"En esta base se despliega en {bx},{by}: lo recuerdo.")
            BB_DROP["i"] = k
        machine = None
    if xs:
        log("warn", "No he podido desplegar " + ", ".join(labels[x] for x in xs) + ".")


def bb_battle():
    """Juega una batalla de constructor (2 fases) hasta la pantalla de resultado. Despliega en cuanto se ven
    las cartas, sin esperar a la cuenta atrás. Devuelve False si la batalla no llegó a empezar."""
    t0 = time.time()
    machine_done = set()
    seen = zoomed = False
    while time.time() - t0 < 330:
        check_stop(redirect=False)                  # ya buscando o jugando: la batalla se acaba antes
        kind, img = screen()
        if kind == "result" and seen:
            return True
        if kind != "battle" and not bb_live(img):
            if not seen and time.time() - t0 > 90:
                log("warn", "La batalla de constructor no ha empezado (sigo en la búsqueda u otra pantalla).")
                return False
            time.sleep(0.7)
            continue
        if not seen:
            seen = True
            log("think", f"Batalla nocturna a la vista a los {time.time() - t0:.0f} s: despliego ya, sin esperar "
                         f"a la cuenta atrás.")
        if not zoomed:                              # una vez por batalla, antes de soltar nada
            dev.zoom_out(1)
            zoomed = True
            img = dev.shot()
        machine, troops = bb_cards(img)
        labels = {x: f"tropa {i + 1}" for i, x in enumerate(troops)}
        # 1) desplegar lo que falte (en la 2ª fase la barra cambia: se vuelve a mirar cada vuelta)
        todo = bb_pending(img, troops)
        if machine is not None and machine not in machine_done:
            labels[machine] = "máquina"
            todo.insert(0, machine)
            machine_done.add(machine)
        if todo:
            bb_deploy(todo, labels)
            img = dev.shot()
        # 2) habilidades: tropas desplegadas con la cabecera morada y la máquina con sus barras moradas
        for x in troops:
            if bb_state(img, x) == "lista":
                tap(x, 960, f"habilidad tropa {troops.index(x) + 1}", 0.3)
        if machine is not None and any(_purple(color(img, machine + dx, 835, 2)) for dx in (-3, 37)):
            tap(machine, 960, "habilidad de la máquina", 0.3)
        time.sleep(1.2)
    log("warn", "La batalla de constructor no terminó a tiempo.")
    return seen


def bb_storages(acc, res=None, read_cap=True):
    """(lleno?, recursos) de la aldea nocturna según capacidad y % objetivo de la cuenta. `res`: recursos
    recién leídos (para no volver a preguntar al modelo); `read_cap`: releer la capacidad (basta una vez)."""
    a = CFG["accounts"][acc]
    if not res or res.get("gold") is None or res.get("elixir") is None:
        res = eyes.my_resources(dev.shot())   # antes de tocar las barras
    if read_cap or not a.get("builder_capacity"):
        try:
            read_capacity(acc, "builder", have=res)
        except Exception as e:
            log("warn", f"No he podido leer la capacidad de la aldea nocturna: {e}")
    cap = a.get("builder_capacity")
    note_resources(acc, res, "builder")
    if not cap:
        return False, res
    r = a.get("builder_full_ratio", a.get("full_ratio", CFG["full_ratio"]))
    full = all((res.get(k) or 0) >= cap[k] * r for k in ("gold", "elixir"))
    log("think", f"{acc} (aldea nocturna): oro {res.get('gold')}/{cap['gold']}, elixir {res.get('elixir')}/{cap['elixir']}"
                 f" → {'LLENO' if full else 'falta'} (objetivo {int(r * 100)} %)")
    return full, res


def builder_base(acc):
    """Aldea nocturna: batallas de constructor, sin tope, hasta llenar sus almacenes al % objetivo. Sólo se
    deja antes si dos batallas seguidas no suman nada (bonus diario agotado: seguir no llenaría nada)."""
    if not go_home():
        return
    if not in_builder() and not travel_boat(True):
        return
    collect_cart()
    result, res, dry = None, None, 0
    for n in itertools.count():
        try:
            check_stop()
        except Redirect:                           # el visor manda otro paso: antes, de vuelta a la principal
            go_home()
            travel_boat(False)
            go_home()
            raise
        if not go_home():                          # cierra avisos (bonus estelar, etc.) antes de cada batalla
            break
        full, before = bb_storages(acc, res, read_cap=(n == 0))
        if full:
            log("done", f"Almacenes de la aldea nocturna de {acc} llenos.")
            result = "full"
            break
        tap(125, 960, "Batalla (aldea nocturna)", 0.8)
        if not wait_for(lambda: is_green(color(dev.shot(), 1270, 700, 3)), 6):   # botón verde "Buscar" del menú
            log("warn", "El menú de batalla de la aldea nocturna no se ha abierto.")
            go_home()
            break
        tap(1425, 708, "Buscar batalla de constructor", 1)
        t_search = time.time()
        if not bb_battle():
            go_home()
            break
        tap(960, 925, "volver", 1)
        wait_for(lambda: screen()[0] == "home", 8)   # con un aviso encima sigue go_home
        log("think", f"Batalla nocturna completa en {time.time() - t_search:.0f} s (de «Buscar» a la aldea).")
        collect_cart()
        res = None
        if go_home():
            res = after = eyes.my_resources(dev.shot())
            gained = {k: max(0, (after.get(k) or 0) - (before.get(k) or 0)) for k in ("gold", "elixir")}
            note_resources(acc, after, "builder")
            loot_log(acc, "aldea nocturna", None, None, {**gained, "dark": 0})
            log("done", f"Batalla nocturna terminada: +{gained['gold']} oro, +{gained['elixir']} elixir.")
            dry = dry + 1 if gained["gold"] + gained["elixir"] < 2000 else 0
            if dry >= 2:
                log("done", "La aldea nocturna ya no suma en dos batallas seguidas (bonus agotado o almacenes "
                            "llenos). Paso a lo siguiente.")
                break
    go_home()
    travel_boat(False)
    go_home()
    return result


# ---------------- mejoras recomendadas (sólo cuentas con "auto_build") ----------------
BUILD_BTN = (1745, 815)            # icono de constructores (abajo a la derecha)
CONFIRM_BTN = (1345, 940)          # «Confirmar» con recurso (el gris de la izquierda es el martillo: nunca)


def builder_panel_open(img=None):
    """Panel «Estructuras y héroes» abierto. Se mira su marco fijo (X roja, botón gris del filtro y el marco
    de las pestañas de abajo), no el icono de la pestaña (con un constructor libre es un duende verde) ni la
    lista (al desplazarla pasan etiquetas verdes de descuento)."""
    img = img or dev.shot()
    x, filt = color(img, 1905, 40, 2), color(img, 1460, 35, 2)
    tab, low = color(img, 1420, 1060, 2), color(img, 1600, 1075, 2)
    return (x[0] > 170 and x[1] < 90 and x[2] < 90
            and all(70 < c < 165 for c in filt) and max(filt) - min(filt) < 35
            and 135 < tab[0] < 185 and 115 < tab[1] < 165 and 100 < tab[2] < 150
            and 95 < low[0] < 135 and 80 < low[1] < 120 and 70 < low[2] < 110)


ROW_PITCH = 85                     # distancia entre filas del panel


def _brown_share(img, y0, y1):
    box = img.crop((1500, y0, 1890, y1)).resize((39, max(1, (y1 - y0) // 2))).getdata()
    return sum(1 for r, g, b in box if 120 < r < 215 and 85 < g < 175 and r - b > 35 and r - g > 15) / len(box)


def panel_rows(img):
    """Filas de la primera sección del panel («Mejoras recomendadas»): [{top, new, gem, red}].
    new = edificio nuevo (nombre en verde: hay que colocarlo), gem = cuesta gemas, red = no llega el dinero."""
    top = next((y for y in range(130, 700, 2) if _brown_share(img, y, y + 12) > 0.45), None)
    rows = []
    while top is not None and top + 70 < 960 and _brown_share(img, top + 2, top + 14) > 0.45:
        name = img.crop((1490, top + 6, 1800, top + 40)).getdata()
        price = img.crop((1760, top + 34, 1885, top + 62)).getdata()
        icon = img.crop((1880, top + 34, 1908, top + 62)).getdata()
        rows.append({"top": top,
                     "new": sum(1 for r, g, b in name if g > 190 and r < 190 and b < 130) > 40,
                     "gem": sum(1 for r, g, b in icon if g > 150 and r < 150 and b < 120) > 25,
                     "red": sum(1 for r, g, b in price if r > 200 and g < 90 and b < 90) > 15})
        top += ROW_PITCH
    return rows


def cancel_placement(img):
    """Si el juego dejó un edificio a medio colocar: pulsa su ✗ (cuadro rojo con cruz blanca). Nunca el ✓."""
    px = img.load()
    for y in range(160, 840, 6):
        for x in range(320, 1380, 6):
            r, g, b = px[x, y]
            if r > 200 and g < 70 and b < 70 and x + 44 < img.width:
                box = img.crop((x, y, x + 40, y + 40)).getdata()
                red = sum(1 for c in box if c[0] > 190 and c[1] < 90 and c[2] < 90)
                white = sum(1 for c in box if min(c) > 225)
                if red > 500 and white > 80:
                    tap(x + 20, y + 20, "cancelar colocación (✗)", 1.2)
                    return True
    return False


def free_builders(img):
    r = eyes.ocr("builders", img)                  # «1/7» por plantillas; si no está claro, el modelo
    if r is not None:
        return r
    d = eyes.ask(img.crop((1410, 1000, 1530, 1070)).resize((360, 210)),
                 'Hay un número tipo "a/b" (constructores libres / total). Responde {"free": a, "total": b}.')
    try:
        return int(d.get("free")), int(d.get("total"))
    except (TypeError, ValueError):
        return None, None


def price_ok(img):
    """Ventana de confirmación: botón verde y precio en oro/elixir/oscuro, con cifra blanca (se puede pagar)."""
    btn = color(img, 1250, 960, 4)
    icon = color(img, 1460, 960, 4)
    gold = icon[0] > 200 and icon[1] > 160 and icon[2] < 90
    elixir = icon[0] > 170 and icon[2] > 170 and icon[1] < 120
    dark = max(icon) < 90
    gem = icon[1] > 150 and icon[0] < 140 and icon[2] < 140
    # cifra del precio (fila de arriba): blanca, o verde si hay descuento (la tachada de debajo no cuenta)
    text = img.crop((1240, 925, 1400, 958)).getdata()
    red = sum(1 for r, g, b in text if r > 200 and g < 90 and b < 90)
    white = sum(1 for r, g, b in text if r > 225 and g > 225 and b > 225)
    greentxt = sum(1 for r, g, b in text if g > 200 and r < 150 and b < 120)
    return (btn[1] > 170 and btn[1] > btn[0] + 25 and (gold or elixir or dark) and not gem and red < 15
            and (white > 40 or greentxt > 40))


def build_recommended(acc):
    """Pone a mejorar lo recomendado mientras haya constructores libres y recursos. Nunca gemas ni martillos.
    Se para del todo cuando el ayuntamiento llega al nivel máximo indicado (auto_build_until_th)."""
    a = CFG["accounts"][acc]
    if not a.get("auto_build"):
        return
    max_th = a.get("auto_build_until_th", 10)
    if a.get("th_target", 0) >= max_th:
        return
    if not go_home():
        return
    tap(*BUILD_BTN, "abrir mejoras (constructores)", 2)
    img = dev.shot()
    if not builder_panel_open(img):
        log("warn", "El panel de constructores no se ha abierto.")
        go_home()
        return
    started = 0
    skip = set()                              # filas que no abrieron ventana en esta pasada
    for _ in range(7):
        check_stop()                          # el panel abierto lo cierra go_home() si el visor manda otro paso
        img = dev.shot()
        free, total = free_builders(img)
        if not free:
            log("think", f"{acc}: constructores ocupados ({free}/{total}).")
            break
        rows = panel_rows(img)
        cand = [r for r in rows if not (r["new"] or r["gem"] or r["red"]) and r["top"] not in skip]
        log("think", f"{acc}: {len(rows)} mejoras recomendadas, {len(cand)} se pueden pagar. "
                     f"Constructores libres: {free}/{total}.")
        if not cand:
            break
        row = cand[0]
        tap(1620, row["top"] + 35, "elegir mejora recomendada", 2)
        win = dev.shot()
        if not upgrade_window(win):           # la ventana tarda en abrirse: un segundo más
            time.sleep(1.2)
            win = dev.shot()
        if not upgrade_window(win):           # no salió: nada se confirma, se sigue con la siguiente fila
            win.save(HERE / "no_ventana_mejora.png")
            skip.add(row["top"])
            log("warn", "Esa fila no abrió la ventana de mejora: la salto (captura en no_ventana_mejora.png).")
            cancel_placement(win)
            go_home()
            tap(*BUILD_BTN, "reabrir mejoras", 2)
            continue
        title = eyes.ask(win.crop((380, 40, 1560, 115)),
                         'Título tipo "¿Mejorar tu X al Nivel N?". Responde {"name": X, "level": N}.')
        name, lvl = str(title.get("name", "")), title.get("level")
        try:
            lvl = int(lvl)
        except (TypeError, ValueError):
            lvl = None
        if "ayuntamiento" in name.lower() and (lvl is None or lvl > max_th):
            log("think", f"No subo el ayuntamiento a nivel {lvl} (límite TH{max_th}).")
            tap(1697, 83, "cerrar", 1.5)
            break
        if not price_ok(win):
            time.sleep(1.0)                    # la ventana aún se estaba abriendo
            win = dev.shot()
        if not price_ok(win):
            win.save(HERE / "mejora_rechazada.png")
            log("warn", f"Ventana de mejora de {name} sin precio en recursos pagable: no confirmo.")
            tap(1697, 83, "cerrar", 1.5)
            break
        tap(*CONFIRM_BTN, f"confirmar mejora de {name} a nivel {lvl}", 2.5)
        after = dev.shot()
        if builder_panel_open(after) or screen(after)[0] == "home":
            started += 1
            skip.clear()
            log("done", f"{acc}: mejora iniciada → {name} nivel {lvl}.")
            if "ayuntamiento" in name.lower() and lvl:
                a["th_target"] = lvl
                save_account_field(acc, "th_target", lvl)
                if lvl >= max_th:
                    log("done", f"{acc}: ayuntamiento a TH{lvl}: dejo de mejorar (límite alcanzado).")
                    break
        else:
            log("warn", "Tras confirmar la mejora salió otra ventana: la cierro sin tocar nada.")
            tap(1697, 83, "cerrar", 1.5)
            break
        if not builder_panel_open():
            tap(*BUILD_BTN, "reabrir mejoras", 2)
    go_home()
    return started


# ---------------- muros ----------------
PANEL_LIST = (1405, 60, 1920, 960)        # lista del panel de constructores (se desplaza arrastrando)
# Barra del muro seleccionado con el panel abierto (dos filas). Arriba: Infor. / Marcar fila / Mejorar más;
# tras «Mejorar más»: Eliminar muro (−1) / Añadir +10 / Añadir +1 (igual en TH14 y TH18).
# La barra cabe en UNA fila o se parte en DOS según lo que haya abajo a la derecha (p. ej. la caja de
# recompensas): se detecta cuál es por dónde salen los botones de pago (2026-11-09).
#   dos filas: Infor./Marcar fila/Mejorar más arriba (y=760) y los pagos debajo (precio y≈888)
#   una fila:  Infor. 283 / Marcar fila 490 / Mejorar más 700 / pagos a la derecha, todo en y≈850 (precio y≈791)
# Tras «Mejorar más», los tres primeros pasan a ser −1 / +10 / +1 en el mismo sitio.
WALL_LAYOUTS = {
    "dos filas": {"more": (906, 760), "add10": (698, 760), "add1": (906, 760),
                  "title": (300, 580, 1400, 665), "strip": (380, 876, 1000, 900)},
    "una fila": {"more": (700, 850), "add10": (490, 850), "add1": (700, 850),
                 "title": (300, 675, 1400, 760), "strip": (380, 779, 1260, 803)},
}
WALL_MORE, WALL_ADD10, WALL_ADD1 = (906, 760), (698, 760), (906, 760)
WALL_TITLE = (300, 580, 1400, 665)        # «Muro (Nivel 13) x1»
# Los botones de pago cambian de sitio: 2 (oro, elixir) o 3 si hay anillos de muro (azul, sin precio,
# NUNCA se toca). Se localizan por el icono de su precio: moneda amarilla u gota rosa.
PAY_STRIP = (380, 876, 1000, 900)


def wall_layout(img):
    """Distribución de la barra del muro seleccionado: la que tenga botones de pago en su franja."""
    best = max(WALL_LAYOUTS, key=lambda k: len(pay_buttons(img, WALL_LAYOUTS[k])))
    return dict(WALL_LAYOUTS[best], name=best)


def pay_buttons(img, lay=None):
    """{recurso: (x del botón, recuadro del precio, y donde tocar)} de los botones «Mejorar» con precio en
    oro/elixir, en la franja de la distribución `lay` (por defecto, la de dos filas)."""
    strip = (lay or WALL_LAYOUTS["dos filas"])["strip"]
    x0, y0, x1, y1 = strip
    a = np.asarray(img.crop(strip)).astype(np.int16)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    masks = {"gold": (r > 200) & (g > 160) & (b < 90), "elixir": (r > 150) & (b > 150) & (g < 110)}
    out = {}
    for res in ("elixir", "gold"):            # primero el elixir: el oro va siempre a su IZQUIERDA
        m = masks[res]
        cols = np.nonzero(m.sum(axis=0) >= 4)[0]
        if len(cols) < 6:
            continue
        groups = np.split(cols, np.nonzero(np.diff(cols) > 3)[0] + 1)
        for icon in sorted(groups, key=lambda g: -g[-1]):   # el icono va a la derecha de la cifra
            # la moneda mide 18-20 columnas y ~230 píxeles; la gota, 17 y ~195. Un trozo amarillo de la aldea
            # que asoma entre botones (10 columnas, 73 píxeles) se tomó por la moneda y el recuadro del precio
            # dejó fuera el «1» de «14 000 000» (05:31, 10-nov).
            if not 13 <= len(icon) <= 26 or m[:, icon].sum() < 120:
                continue
            ix = int(icon.mean()) + x0
            if res == "gold" and "elixir" in out and ix > out["elixir"][0] + 66 - 100:
                continue                       # algo amarillo dentro del botón del elixir (brillo): no es el oro
            bx = ix - 66
            under = color(img, bx, y0 + 124, 4)
            # debajo, botón beis claro; el de anillos es azul (y su anillo dorado parece una moneda): nunca
            if under[0] > 170 and under[1] > 170 and under[2] > 150 and under[2] <= under[0] + 5:
                out[res] = (bx, (ix - 165, y0 - 4, ix + 20, y1 + 6), y0 + 74)
                break
    return out


def _white(img):
    a = np.asarray(img.convert("RGB")).astype(np.int16)
    return (a.min(axis=2) > 205).astype(np.float32)


MURO_TPL = _white(Image.open(HERE / "tpl" / "muro_panel.png").convert("RGB"))   # «Muro» blanco del panel
NAME_X = (1475, 1515)                     # el nombre de cada fila empieza siempre en x≈1492


def wall_rows_here(img):
    """Filas «Muro…» visibles en el panel, por plantilla (el modelo se inventa las posiciones): [y del texto]."""
    x0, y0, x1, y1 = NAME_X[0], 70, NAME_X[1] + MURO_TPL.shape[1], 955
    r = cv2.matchTemplate(_white(img.crop((x0, y0, x1, y1))), MURO_TPL, cv2.TM_CCOEFF_NORMED)
    ys = []
    while True:
        _, v, _, (_, y) = cv2.minMaxLoc(r)
        if v < 0.9:                            # muros = 1,0; lo más parecido (Mortero) ≈ 0,8
            return sorted(ys)
        ys.append(y + y0)
        r[max(0, y - 30):y + 30, :] = -1


def _list_moved(prev, cur):
    """¿Se ha movido la lista entre dos capturas? Busca una franja de la anterior en la nueva."""
    g = lambda im: cv2.cvtColor(np.asarray(im.crop(PANEL_LIST)), cv2.COLOR_RGB2GRAY)
    a, b = g(prev), g(cur)
    band = a[330:530]
    _, v, _, (_, y) = cv2.minMaxLoc(cv2.matchTemplate(b, band, cv2.TM_CCOEFF_NORMED))
    return v < 0.9 or abs(y - 330) > 15


def _settled_shot():
    """Captura cuando la lista ha dejado de deslizarse (tras un arrastre sigue moviéndose un poco)."""
    img = dev.shot()
    for _ in range(6):
        time.sleep(0.5)
        again = dev.shot()
        if not _list_moved(img, again):
            return again
        img = again
    return img


def _full_wall_rows(img):
    """y del texto de las filas «Muro» enteras (las cortadas por arriba o por abajo no cuentan)."""
    return [ty for ty in wall_rows_here(img) if ty - 10 >= 80 and ty + 62 <= 950]


def wall_rows():
    """Busca en el panel de constructores la fila «Muro x N» del nivel MÁS BAJO. El panel ordena las mejoras
    de más cara a más barata, así que los muros de nivel bajo van al final: se baja hasta el final de la lista
    y se sube hasta la primera pantalla con muros, y se elige la fila de más abajo (sin modelo: el modelo
    confunde los separadores de miles y no sirve para comparar precios). Devuelve (filas, completo):
    filas = [{y, count, price, seen}] con la elegida (y = centro de la fila en pantalla; seen = filas de muros
    vistas en el recorrido); completo = se vio la lista entera (sin filas y completo = no queda ningún muro)."""
    prev, seen, moved, stuck = None, 0, 0, 0
    for page in range(30):                     # hacia abajo, hasta que el arrastre ya no mueva la lista
        img = _settled_shot()
        seen += len(_full_wall_rows(img))
        if prev is not None and not _list_moved(prev, img):
            stuck += 1
            if stuck >= 2:                     # dos arrastres seguidos sin moverla: final de verdad
                break
        else:
            if prev is not None:
                moved += 1
            stuck = 0
        prev = img
        dev.swipe(1660, 880, 1660, 300, 1300, wait=0.8)     # lento: casi sin inercia
    else:
        return [], False                       # lista sin final: algo raro
    if not seen:
        # «no queda ningún muro» sólo si la lista se ha recorrido de verdad (10-nov 12:58: la lista no se movió,
        # no vio muros y dio el TH18 por terminado con 49 + 276 muros pendientes)
        return [], moved >= 2
    for page in range(20):                     # hacia arriba, hasta la primera pantalla con muros
        ys = _full_wall_rows(img)
        if ys:
            ty = max(ys)                       # la de más abajo = la más barata = nivel más bajo
            r = eyes.ocr("wall_row", img, ty)  # «Muro x 293» / «3 500 000» por plantillas; si no, el modelo
            if r is not None:
                return [{"y": ty + 25, "count": r["count"], "price": r["price"], "seen": seen}], True
            d = eyes.ask(img.crop((1480, ty - 8, 1915, ty + 60)).resize((870, 136)),
                         'Fila de mejora de Clash of Clans: un nombre tipo "Muro x N" y un precio debajo. Responde '
                         '{"name": texto del nombre, "count": N (1 si no hay "x"), "price": P} sin espacios en los números.')
            return [{"y": ty + 25, "count": eyes._num(d.get("count")) or 1, "price": eyes._num(d.get("price")),
                     "seen": seen}], True
        dev.swipe(1660, 300, 1660, 880, 1300, wait=0.8)
        img = _settled_shot()
    return [], False


def _wall_title(img, lay=None):
    """(nombre, nivel, cuántos) del título «Muro (Nivel 16) x11». Se pide el texto tal cual y los números se
    sacan aquí: preguntando por los números, el modelo leía «x11» como «x1»."""
    b = (lay or WALL_LAYOUTS["dos filas"])["title"]
    t = eyes.ocr("wall_title", img, b)        # sólo si pone EXACTAMENTE «Muro (Nivel N) [xK]»; si no, el modelo
    if t is not None:
        return t
    d = eyes.ask(img.crop(b).resize(((b[2] - b[0]) * 2, (b[3] - b[1]) * 2)),
                 'Copia exactamente el texto grande amarillo. Responde {"text": "..."}')
    text = str(d.get("text") or "")
    lvl = re.search(r"nivel\s*(\d+)", text, re.I)
    n = re.search(r"\)\s*x\s*(\d+)", text, re.I)
    return text.split("(")[0].strip(), int(lvl[1]) if lvl else None, int(n[1]) if n else 1


def _wall_price(img, box, scale=3):
    """Precio de un botón de pago. Texto literal + cifras sacadas aquí: pidiendo el número, el modelo se comía
    dígitos (leyó 6500000 donde ponía 16 500 000). El recuadro se ensancha un poco por la izquierda."""
    box = (box[0] - 14, box[1], box[2], box[3])
    try:
        if ocr_mod is not None and ocr_mod.red_text(img, box):
            log("think", "Precio en rojo (no llega): ese botón no se paga.")
            return None                       # un precio rojo nunca se paga (por píxeles, independiente; QA)
    except Exception:
        pass
    if scale == 3:                            # 1.ª lectura por plantillas; la de comprobación (scale=4), el modelo
        v = eyes.ocr("price", img, box, end_gap=46)    # la cifra acaba a ~40 px del borde (icono)
        if v is not None:
            return v
    d = eyes.ask(img.crop(box).resize(((box[2] - box[0]) * scale, (box[3] - box[1]) * scale)),
                 'Copia exactamente el número blanco (con sus espacios). Responde {"text": "..."}')
    digits = re.sub(r"\D", "", str(d.get("text") or ""))
    return int(digits) if digits else None


def _walls_question(img):
    """(recurso, cantidad) de «¿Quieres mejorar los muros seleccionados por Oro x15000000?». Se pide el texto
    tal cual y la cifra se saca aquí: con un ejemplo numérico en la pregunta, el modelo copiaba el ejemplo
    (leyó 1000000 donde ponía x15000000)."""
    box = (520, 420, 1400, 550)
    d = eyes.ask(img.crop(box).resize(((box[2] - box[0]) * 2, (box[3] - box[1]) * 2)),
                 'Copia exactamente el texto de la pregunta. Responde {"text": "..."}')
    text = str(d.get("text") or "")
    m = re.search(r"(oro|elixir)\s*x?\s*([\d][\d .,]*)", text, re.I)
    digits = re.sub(r"\D", "", m[2]) if m else ""
    return (m[1].lower() if m else ""), (int(digits) if digits else None)


WALLS_OK = (1167, 692)                    # «Vale» de «Mejorar muros» (a la izquierda, «Cancelar» naranja)
NO_BUILDER_X = (1350, 328)                # X de «¡No hay constructores libres!» (el botón verde es de GEMAS)


def _green(c):
    return c[1] > 160 and c[1] > c[0] + 50 and c[2] < 90


def walls_confirm(img):
    """Ventana «Mejorar muros»: cuerpo claro, «Cancelar» naranja a la izquierda y «Vale» verde a la derecha
    (puntos lisos de los botones, lejos de las letras)."""
    cancel = [color(img, x, 740, 3) for x in (600, 880)]
    return (all(_green(color(img, x, 740, 3)) for x in (1030, 1300)) and min(color(img, 960, 580, 4)) > 200
            and all(c[0] > 190 and 50 < c[1] < 120 and c[2] < 70 for c in cancel))


def no_builder_dialog(img):
    """«¡No hay constructores libres!»: X roja arriba a la derecha y botón verde (de GEMAS) en el centro."""
    red = [color(img, x, 350, 3) for x in (1318, 1385)]
    return (all(c[0] > 190 and c[1] < 60 and c[2] < 60 for c in red)
            and all(_green(color(img, x, 740, 3)) for x in (820, 1100)))


GOBLIN_X = (1717, 232)                    # X de «¡Buenas, jefe!» (el duende constructor cobra GEMAS)
GOBLIN_ONLY = {}                          # cuenta -> nº de libres cuando el único libre era el duende


def goblin_dialog(img):
    """«¡Buenas, jefe!»: el constructor duende ofrece trabajar por gemas. X roja arriba a la derecha del
    cuadro y botón verde (de GEMAS) en el centro."""
    x = color(img, 1740, 250, 3)
    return (x[0] > 190 and x[1] < 70 and x[2] < 70 and min(color(img, 1100, 270, 4)) > 200
            and all(_green(color(img, gx, 690, 3)) for gx in (1215, 1440)))


def _accept_walls(img, pay, word, total_price, got, prices, res):
    """Lee «¿Quieres mejorar los muros seleccionados por Oro xN?» y pulsa «Vale» sólo si cuadra. Devuelve
    (captura tras aceptar, (pay, word, total_price)) o None si se canceló."""
    what, amount = _walls_question(img)
    alt = {"oro": "gold", "elixir": "elixir"}.get(what)
    if (alt and alt != pay and amount and prices.get(alt) and amount <= (res.get(alt) or 0)
            and abs(amount - got * prices[alt]) <= prices[alt] * 0.02):
        # se pulsó el botón de la otra moneda: lo que pide la confirmación es justo y llega, vale igual
        log("think", f"La confirmación pide {what} en vez de {word} ({amount}, tengo {res.get(alt)}): vale igual.")
        img.save(HERE / "muro_rechazado.png")
        pay, word, total_price = alt, what, amount
    if (what not in ("oro", "elixir") or what != word or not amount
            or abs(amount - total_price) > prices[pay] * 0.02):
        img.save(HERE / "muro_rechazado.png")
        log("warn", f"La confirmación pide {amount} de «{what}» y esperaba {total_price} de {word}: cancelo.")
        tap(747, 692, "Cancelar", 1.2)
        return None
    tap(*WALLS_OK, f"Vale: {got} muros por {amount} {word}", 2)
    return dev.shot(), (pay, word, total_price)


def single_wall_ok(img, pay, lvl, price, have):
    """Ventana normal «¿Mejorar tu Muro al Nivel N?» (sale cuando sólo se mejora un muro): se acepta sólo si es
    un muro, al nivel siguiente, con el botón «Confirmar» en el recurso elegido (nunca gemas ni martillo) y
    por el precio esperado, y si llega. Texto literal + regex (el modelo copia los números de ejemplo)."""
    if not (upgrade_window(img) and price_ok(img)):
        return False
    icon = color(img, 1460, 960, 4)
    is_gold = icon[0] > 200 and icon[1] > 160 and icon[2] < 90
    is_elixir = icon[0] > 170 and icon[2] > 170 and icon[1] < 120
    if not ((pay == "gold" and is_gold) or (pay == "elixir" and is_elixir)):
        return False
    b = (380, 40, 1560, 115)
    d = eyes.ask(img.crop(b).resize(((b[2] - b[0]) * 2, (b[3] - b[1]) * 2)),
                 'Copia exactamente el título. Responde {"text": "..."}')
    # «¿Mejorar tu Muro al Nivel N?» (la de un muro ya al máximo dice «Muro de nivel N»: nunca vale)
    m = re.search(r"mejorar.*?muro.*?\bal\s+nivel\s*(\d+)", str(d.get("text") or ""), re.I)
    if not m or (lvl and int(m[1]) != lvl + 1):
        return False
    b = (1215, 922, 1430, 962)                 # cifra de arriba (la tachada de debajo es el precio sin descuento)
    amount = eyes.ocr("price", img, b, hr=(16, 32))
    if amount is None:
        d = eyes.ask(img.crop(b).resize(((b[2] - b[0]) * 3, (b[3] - b[1]) * 3)),
                     'Copia exactamente el número. Responde {"text": "..."}')
        digits = re.sub(r"\D", "", str(d.get("text") or ""))
        amount = int(digits) if digits else None
    return bool(amount and price) and abs(amount - price) <= price * 0.02 and amount <= have


def upgrade_walls(acc, res=None):
    """Mejora muros con «Mejorar más» (varios del mismo nivel de una vez) mientras haya constructor libre y
    dinero. Nunca gemas, martillos ni anillos: sólo los botones con precio en oro o elixir, sólo si llega, y
    la confirmación se lee antes de aceptar. Devuelve "max" si ya no queda ningún muro por mejorar, "busy" si
    no hay constructor libre, o cuántos muros mejoró (0 si no llegaba el dinero o algo no cuadró)."""
    if not main_village():
        return 0
    res = dict(res or eyes.my_resources(dev.shot()))
    done, empty_scans, warmed = 0, 0, False
    for _round in range(5):                   # oro, elixir y alguna vuelta más si quedan muros a otro nivel
        check_stop()
        go_home()
        tap(*BUILD_BTN, "abrir mejoras (constructores)", 2)
        img = dev.shot()
        if not builder_panel_open(img):
            log("warn", "El panel de constructores no se ha abierto.")
            break
        free, total = free_builders(img)
        if not free or free <= GOBLIN_ONLY.get(acc, 0):
            why = "sólo el duende, que cobra gemas" if free else "ninguno"
            log("think", f"{acc}: no hay constructor libre para los muros ({free}/{total}: {why}).")
            go_home()
            return done or "busy"
        if not warmed:                        # la confirmación «Mejorar muros» la lee el modelo: que se vaya
            warmed = True                     # cargando mientras se recorre la lista del panel (~40 s)
            threading.Thread(target=eyes.warm, daemon=True).start()
        rows, complete = wall_rows()
        if not rows:
            if not complete:
                log("warn", f"{acc}: no encuentro los muros en el panel; lo dejo para luego.")
                break
            empty_scans += 1
            if empty_scans < 2:               # se repasa la lista entera otra vez antes de darlo por hecho
                continue
            go_home()
            return done or "max"
        cheap = min(rows, key=lambda r: r["price"] or 1e18)     # de los que se ven, el más barato
        tap(1620, cheap["y"], f"elegir muros ({cheap['count']} a {cheap['price']})", 2.5)
        img = dev.shot()
        lay = wall_layout(img)
        name, lvl, _ = _wall_title(img, lay)
        if "muro" not in name.lower():
            img.save(HERE / "muro_rechazado.png")
            log("warn", f"La fila elegida no es de muros («{name}»): no toco nada (captura en muro_rechazado.png).")
            break
        btns = pay_buttons(img, lay)           # oro / elixir; el de anillos ni se considera
        prices = {k: _wall_price(img, btns[k][1]) if k in btns else None for k in ("gold", "elixir")}
        ref = cheap.get("price")              # el del panel: otra pantalla y otra letra (lectura independiente)
        for k, p in list(prices.items()):
            if p and ref and abs(p - ref) > 0.02 * ref:
                # no coincide (p. ej. una cifra inicial perdida): segunda lectura con el modelo; si tampoco, fuera
                p2 = _wall_price(img, btns[k][1], scale=4)
                prices[k] = p2 if p2 and abs(p2 - ref) <= 0.02 * ref else None
                log("think", f"Precio de muro en {k}: leí {p} y el panel dice {ref}; relectura {p2} → "
                             f"{'vale' if prices[k] else 'no lo uso'}.")
        can = {k: min((res.get(k) or 0) // p, cheap["count"] or 1) if p else 0 for k, p in prices.items()}
        pay = max(can, key=can.get)
        n, word = can[pay], "oro" if pay == "gold" else "elixir"
        if n < 1:
            log("think", f"{acc}: muros de nivel {lvl} a {prices.get('gold')} (oro) / {prices.get('elixir')} "
                         f"(elixir); con {res.get('gold')} oro y {res.get('elixir')} elixir no llega para ninguno.")
            break
        if (cheap["count"] or 1) <= CFG.get("walls_one_by_one", 10):
            # quedan pocos de este nivel y van sueltos por la aldea: «Mejorar más» no los junta y los «+1»
            # caían en la aldea (2026-11-09). De uno en uno, con la ventana normal de un muro.
            n = 1
        if n > 1:
            tap(*lay["more"], f"Mejorar más (barra en {lay['name']})", 1.5)
            for _ in range((n - 1) // 10):
                tap(*lay["add10"], "añadir 10 muros", 0.7)
            for _ in range((n - 1) % 10):
                tap(*lay["add1"], "añadir 1 muro", 0.5)
            time.sleep(0.5)
            img = dev.shot()
            lay = wall_layout(img)
            _, _, got = _wall_title(img, lay)
            btns = pay_buttons(img, lay)
        else:
            got = 1                            # sin «Mejorar más»: la barra es la del muro elegido
        total_price = _wall_price(img, btns[pay][1]) if pay in btns else None
        if pay in btns and prices.get(pay) and (not total_price or abs(total_price - got * prices[pay]) > prices[pay] * 0.02):
            total_price = _wall_price(img, btns[pay][1], scale=4)      # segunda lectura, a otra escala
        if (not total_price or total_price > (res.get(pay) or 0) or not 1 <= got <= n
                or abs(total_price - got * prices[pay]) > prices[pay] * 0.02):
            img.save(HERE / "muro_rechazado.png")
            log("warn", f"{acc}: la cuenta de muros no cuadra (x{got} de {n}, {total_price} de {res.get(pay)} "
                        f"{word}): no confirmo.")
            break
        img.save(HERE / "muro_pago.png")       # para revisar qué botón se eligió
        log("think", f"Botones de pago: " + ", ".join(f"{k} x={v[0]}" for k, v in btns.items()))
        tap(btns[pay][0], btns[pay][2], f"mejorar {got} muros de nivel {lvl} con {word} ({total_price})", 1.8)
        img = dev.shot()
        if not walls_confirm(img) and got == 1 and upgrade_window(img):
            # con UN solo muro sale la ventana normal «¿Mejorar tu Muro al Nivel N?» en vez de «Mejorar muros»
            if not single_wall_ok(img, pay, lvl, total_price, res.get(pay) or 0):
                img.save(HERE / "muro_rechazado.png")
                log("warn", "Ventana de mejora de un muro que no cuadra (nombre, nivel, recurso o precio): la cierro.")
                tap(1697, 83, "cerrar ventana de mejora (X)", 1.5)
                break
            tap(*CONFIRM_BTN, f"Confirmar: 1 muro de nivel {lvl} por {total_price} {word}", 2)
            img = dev.shot()
        elif not walls_confirm(img):
            img.save(HERE / "muro_rechazado.png")
            log("warn", "No ha salido la confirmación «Mejorar muros»: no acepto nada (captura en muro_rechazado.png).")
            break
        else:
            ok = _accept_walls(img, pay, word, total_price, got, prices, res)
            if ok is None:
                break
            img, (pay, word, total_price) = ok
        if no_builder_dialog(img):            # el contador de constructores se leyó mal: nunca las gemas
            tap(*NO_BUILDER_X, "cerrar «no hay constructores libres» (sin gemas)", 1.2)
            go_home()
            return done or "busy"
        if goblin_dialog(img):                # el libre era el duende: trabaja por gemas, nunca
            GOBLIN_ONLY[acc] = free
            tap(*GOBLIN_X, "cerrar el duende constructor (pide gemas)", 1.2)
            log("think", f"{acc}: el constructor libre es el duende (cobra gemas): espero a uno normal.")
            go_home()
            return done or "busy"
        go_home()
        after = eyes.my_resources(dev.shot())
        spent = (res.get(pay) or 0) - (after.get(pay) or 0)
        if spent < total_price * 0.9:
            dev.shot().save(HERE / "muro_rechazado.png")
            log("warn", f"{acc}: tras aceptar no se ha gastado lo esperado ({spent} de {total_price} {word}).")
            break
        done += got
        log("done", f"{acc}: {got} muros mejorados al nivel {(lvl or 0) + 1} por {total_price} {word}.")
        res = after
        if all(p and (res.get(k) or 0) < p for k, p in prices.items()):
            # lo que queda no paga ni un muro del nivel más barato (los siguientes sólo pueden costar más): no
            # se vuelve a abrir el panel y recorrer la lista entera (~70 s) para acabar en «no llega para ninguno»
            log("think", f"{acc}: quedan {res.get('gold')} oro y {res.get('elixir')} elixir; un muro cuesta "
                         f"{prices.get('gold')} (oro) / {prices.get('elixir')} (elixir): no llega para otro.")
            break
    go_home()
    dev.zoom_out(2)                          # tocar la fila acerca la cámara: se deja como estaba
    return done


def walls_rich(acc):
    """¿Hay oro o elixir de sobra para gastar en muros? (al `walls_spend_ratio` del almacén, 80 % por defecto,
    o la barra al tope). Devuelve (sí/no, recursos leídos)."""
    shot = dev.shot()
    res = eyes.my_resources(shot)
    a = CFG["accounts"][acc]
    cap = a.get("capacity") or {}
    r = a.get("walls_spend_ratio", CFG.get("walls_spend_ratio", 0.8))
    rich = [k for k in ("gold", "elixir")
            if bar_full(shot, k) or (cap_ok(k, cap.get(k)) and (res.get(k) or 0) >= cap[k] * r)]
    return bool(rich), res


def queue_next_walls(acc):
    """Los muros de `acc` ya están al máximo: activa el siguiente paso de muros que esté en cola (queue)."""
    p = HERE / "config.json"
    c = json.loads(p.read_text(encoding="utf-8"))
    for st in c["routine"]:
        if st.get("task") == "walls" and st.get("queue") and st.get("enabled") is False and st["account"] != acc:
            st["enabled"] = True
            st.pop("queue", None)
            p.write_text(json.dumps(c, indent=2, ensure_ascii=False), encoding="utf-8")
            reload_config()
            log("done", f"Muros de {acc} al máximo: activo los muros de {st['account']} (estaba en cola).")
            return st["account"]
    return None


WALLS_BUSY = {}                            # cuenta -> cuándo se vio sin constructor libre
WALLS_MAX = {}                             # cuenta -> lecturas seguidas de «no queda ningún muro»


def walls_task(acc):
    """Farmea sin tope y, cada vez que el oro o el elixir llegan al umbral, los gasta en muros (si hay
    constructor libre). Acaba cuando ya no queda ningún muro por mejorar en este ayuntamiento ("max"); antes
    sólo si los almacenes están llenos y no hay constructor ("full": se vuelve tras el descanso)."""
    a = CFG["accounts"][acc]
    if a.get("walls_done") and time.time() - a.get("walls_checked", 0) < CFG.get("walls_recheck_hours", 72) * 3600:
        return "max"                           # se vuelve a mirar cada 12 h (por si sube el ayuntamiento)
    for n in itertools.count():               # sin tope: hasta que no quede ningún muro (o no se pueda seguir)
        check_stop()
        if blocked_until.get(acc, 0) > time.time():
            return
        reload_config()
        if not main_village():
            return
        if mass_on():
            # en masa (pedido por el usuario): los almacenes se leen con el modelo sólo cada 20 ataques y
            # entonces se gasta todo lo que dé; entre medias, sólo la barra por píxeles (gratis): si una
            # está al tope se gasta ya, para no perder botín.
            shot = dev.shot()
            if any(bar_full(shot, k) for k in ("gold", "elixir")) or n % CFG.get("mass_walls_every", 20) == 0:
                rich, res = walls_rich(acc)
                cap = a.get("capacity") or {}
                rich = rich or any((res.get(k) or 0) >= (cap.get(k) or 1e18) * 0.3 for k in ("gold", "elixir"))
            else:
                rich, res = False, {}
        else:
            rich, res = walls_rich(acc)
        busy = time.time() - WALLS_BUSY.get(acc, 0) < 900   # sin constructor hace <15 min: ni se mira
        if (rich or n == 0 and a.get("walls_done") or WALLS_MAX.get(acc)) and not busy:
            r = upgrade_walls(acc, res)
            if r == "busy":
                WALLS_BUSY[acc] = busy = time.time()
            if r == "max" and not a.get("walls_done"):
                # un «no queda ningún muro» suelto no basta (el panel a veces no se desliza o carga a medias):
                # hacen falta dos lecturas seguidas, con un ataque de por medio
                WALLS_MAX[acc] = WALLS_MAX.get(acc, 0) + 1
                if WALLS_MAX[acc] < 2:
                    log("think", f"{acc}: no veo muros pendientes; lo compruebo otra vez tras el próximo ataque.")
                    r = None
            elif r != "max":
                WALLS_MAX.pop(acc, None)
            if r == "max":
                WALLS_MAX.pop(acc, None)
                a["walls_done"], a["walls_checked"] = True, time.time()
                save_account_field(acc, "walls_done", True)
                save_account_field(acc, "walls_checked", a["walls_checked"])
                log("done", f"{acc}: todos los muros al nivel máximo de su ayuntamiento.")
                queue_next_walls(acc)
                return "max"
            if a.get("walls_done"):            # quedaban muros (subió el ayuntamiento): se sigue con ellos
                a["walls_done"] = False
                save_account_field(acc, "walls_done", False)
        if rich and busy and storages_full(acc, ["gold", "elixir"]):
            log("done", f"{acc}: almacenes llenos y ningún constructor libre para muros: espero.")
            return "full"
        if not attack(acc) and not attack(acc):
            return
        check_stop()
        clan_duties()


def save_account_field(acc, key, value):
    """Guarda un dato de la cuenta en config.json (sobrevive a reinicios)."""
    p = HERE / "config.json"
    c = json.loads(p.read_text(encoding="utf-8"))
    c["accounts"][acc][key] = value
    p.write_text(json.dumps(c, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------- rutina ----------------
def reload_config():
    """Relee config.json: los cambios de umbrales se aplican sin reiniciar el asistente."""
    try:
        CFG.update(json.loads((HERE / "config.json").read_text(encoding="utf-8")))
    except (OSError, ValueError) as e:
        log("warn", f"config.json no válido, sigo con el anterior: {e}")


def run_step(step):
    owner_pause()
    reload_config()
    acc, task = step["account"], step["task"]
    if blocked_until.get(acc, 0) > time.time():
        log("think", f"Me salto {acc}: la está usando el dueño.")
        return "skip"
    a = CFG["accounts"].get(acc, {})
    if task == "walls" and a.get("walls_done") and time.time() - a.get("walls_checked", 0) < CFG.get("walls_recheck_hours", 72) * 3600:
        return "max"                              # muros ya al máximo: ni se cambia de cuenta
    if not switch_to(acc):
        if not paused():
            return
        # el cambio falló porque entró el dueño: tras la pausa se reintenta ESTE paso (10-nov 21:20: se perdía
        # el de ARDHIAMATEUR y, al saltar la pausa desde el visor, seguía por la aldea nocturna)
        owner_pause()
        if blocked_until.get(acc, 0) > time.time() or not switch_to(acc):
            return
    clan_duties()
    if task == "builder_base":
        return builder_base(acc)
    if task == "build":
        build_recommended(acc)
        return
    if task == "walls":
        return walls_task(acc)
    # llenar almacenes: sin tope, hasta llenarlos; «farmear» es justo eso, N ataques
    limit = step.get("attacks", 6) if task == "farm" else None
    dry = 0
    for n in itertools.count():
        if limit is not None and n >= limit:
            return
        check_stop()
        if blocked_until.get(acc, 0) > time.time():
            return
        reload_config()
        if task in ("fill_storages", "farm") and storages_full(acc):
            log("done", f"Almacenes de {acc} llenos: no ataco.")
            return "full"
        if not attack(acc) and not attack(acc):   # un fallo suelto (nubes, popup) se reintenta una vez
            return
        check_stop()                              # recién acabada la batalla: buen momento para obedecer
        clan_duties()
        dry = 0 if LAST_GAIN.get("mass") else (
            dry + 1 if sum(LAST_GAIN.get(k) or 0 for k in ("gold", "elixir", "dark")) < 3000 else 0)
        if dry >= 2:                              # uno malo suelto no para nada; dos seguidos = ya no cabe
            log("done", f"{acc}: dos ataques seguidos sin sumar nada (almacenes llenos). Paso a lo siguiente.")
            return "full"


STATE = HERE / "estado.json"


def set_state(**kw):
    """Estado para el visor (qué paso de la rutina está haciendo): asistente/estado.json."""
    try:
        st = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    except (OSError, ValueError):
        st = {}
    st.update(kw, ts=time.time())
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STATE)


TASK_NAMES = {"fill_storages": "llenar almacenes", "farm": "farmear", "builder_base": "aldea nocturna",
              "build": "mejorar lo recomendado", "walls": "mejorar muros"}


def cycle(start=0, forced=None):
    """Una vuelta de la rutina desde el paso `start` y su descanso. `forced`: paso pedido desde el visor
    (se hace aunque esté desactivado)."""
    reload_config()
    results = {}
    set_state(phase="run", current=None, results={}, routine=CFG["routine"])
    i = start
    while i < len(CFG["routine"]):           # se relee en cada paso: los cambios del visor valen ya
        step = CFG["routine"][i]
        check_stop()
        if step.get("enabled", True) is False and i != forced:
            results[str(i)] = "off"
            i += 1
            continue
        set_state(phase="run", current=i, step=step, results=results, routine=CFG["routine"])
        try:
            r = run_step(step)
        except SystemExit:
            raise
        except Exception as e:
            log("warn", f"Error en {step}: {e}")
            r = "error"
            time.sleep(5)
        results[str(i)] = r or "ok"
        set_state(results=results)
        reload_config()
        i += 1
    rest = CFG["rest_minutes_between_cycles"]
    real = [r for r in results.values() if r != "off"]
    if not real:
        log("warn", "No hay ningún paso activo en la rutina: no hago nada (actívalo en el visor).")
        rest = max(rest, 10)
    if real and all(r in ("full", "skip", "max") for r in real):
        rest = CFG.get("rest_minutes_when_full", 30)
        log("think", "Todas las cuentas llenas (o en uso por el dueño): descanso largo.")
    log("think", f"Rutina completa. Descanso {rest} min y vuelvo a empezar.")
    t_end = time.time() + rest * 60
    set_state(phase="rest", current=None, results=results, rest_until=t_end)
    owner_pause()
    home = CFG.get("home_account")
    if home and blocked_until.get(home, 0) > time.time():
        home = None                      # su cuenta la usa el dueño: no se vuelve a ella
    every = CFG.get("donation_check_minutes", 4) * 60
    if home:
        try:
            switch_to(home)
        except Exception as e:
            log("warn", f"No he podido volver a {home}: {e}")
    last_don = beat = time.time()
    while time.time() < t_end:           # se mira el visor cada 2 s
        check_stop()
        if (HERE / "SKIP_REST").exists():  # botón «empezar ya» del visor
            (HERE / "SKIP_REST").unlink(missing_ok=True)
            log("think", "Descanso cancelado desde el visor: empiezo la rutina.")
            break
        if home and time.time() - last_don >= every:   # la cuenta donante atiende peticiones mientras descansa
            last_don = time.time()
            try:
                if which_account() == home:
                    clan_duties()
                else:
                    switch_to(home)
            except Exception as e:
                log("warn", f"Revisión de donaciones falló: {e}")
        elif time.time() - beat >= 300:                # latido cada 5 min para que el vigilante no lo crea colgado
            beat = time.time()
            log("think", f"Descansando… quedan {math.ceil((t_end - beat) / 60)} min.")
        time.sleep(2)


def main():
    dev.connect()
    log("think", "Asistente en marcha: rutina " + " → ".join(f"{s['account']} ({s['task']})" for s in CFG["routine"]) + ".")
    start = 0                                    # EMPEZAR_EN (un número): la 1ª vuelta empieza en ese paso
    try:
        start = int((HERE / "EMPEZAR_EN").read_text().strip())
        log("think", f"Empiezo esta vuelta por el paso {start + 1} de la rutina (EMPEZAR_EN).")
    except (OSError, ValueError):
        pass
    (HERE / "EMPEZAR_EN").unlink(missing_ok=True)
    forced = None
    while True:
        try:
            cycle(start, forced)
            start, forced = 0, None
        except Redirect as r:                    # botón «hacer ahora» del visor (fichero IR_A)
            log("think", f"Orden del visor: dejo lo que hacía y voy al paso {r.index + 1} "
                         f"({r.step['account']} · {TASK_NAMES.get(r.step['task'], r.step['task'])}); "
                         f"luego sigo la rutina desde ahí.")
            start = forced = r.index
            # un paso DESACTIVADO lanzado con ⚡ queda activado: antes la orden sólo vivía en memoria y, tras un
            # reinicio, la rutina (con ese único paso apagado) daba «Rutina completa» cada 2 min sin hacer nada
            # mientras aún quedaban muros (13-nov)
            if r.step.get("enabled") is False:
                try:
                    p = HERE / "config.json"
                    c = json.loads(p.read_text(encoding="utf-8"))
                    st = c["routine"][r.index]
                    if st["account"] == r.step["account"] and st["task"] == r.step["task"]:
                        st.pop("enabled", None)
                        st.pop("queue", None)
                        p.write_text(json.dumps(c, indent=2, ensure_ascii=False), encoding="utf-8")
                        reload_config()
                        log("think", "Ese paso estaba desactivado: lo dejo activado para que siga tras un reinicio.")
                except (OSError, ValueError, KeyError, IndexError) as e:
                    log("warn", f"No he podido activar el paso: {e}")


if __name__ == "__main__":
    main()

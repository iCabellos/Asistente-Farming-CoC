"""Asistente de farmeo de Clash of Clans (BlueStacks + ADB). Lo arranca y vigila vigilante.py.

La rutina (qué cuenta y qué tarea, en bucle) está en config.json y se edita desde el visor
(http://localhost:8000). Tareas: llenar almacenes, llenar aldea nocturna, mejorar lo recomendado.
Entre batalla y batalla: dona lo que pidan en el clan y pide tropas si es gratis.
Normas: sólo batallas NORMALES, nunca gemas ni martillos, nunca guerra/competitiva; mejoras sólo en
las cuentas con "auto_build". Si el dueño entra en una cuenta desde otro dispositivo, el asistente se aparta.
"""
import io
import json
import random
import sys
import time
from pathlib import Path

from device import Device, color, is_green, is_grey, is_orange, is_red, is_yellow
from eyes import Eyes
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
eyes = Eyes(CFG["ollama"], CFG["model"])
blocked_until = {}                      # cuenta -> timestamp (el dueño está jugando)
current = None                          # cuenta abierta

# Líneas de despliegue (vista con el zoom al mínimo) por lado; se prueban de fuera hacia dentro.
SIDES = {"UL": ((250, 470), (770, 55)), "UR": ((1150, 55), (1670, 470)),
         "LL": ((250, 520), (690, 845)), "LR": ((1670, 520), (1230, 845))}
CENTER = (960, 470)


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


def check_stop():
    if STOP.exists():
        STOP.unlink()
        log("warn", "Parado por orden (fichero STOP).")
        sys.exit(0)


# ---------------- pantallas ----------------
def upgrade_window(img):
    """Ventana «¿Mejorar tu X al nivel N?» (panel blanco + X roja arriba a la derecha)."""
    w = color(img, 1300, 500, 4)
    x = color(img, 1720, 60, 3)
    return min(w) > 225 and max(w) - min(w) < 12 and x[0] > 190 and x[1] < 160 and x[2] < 160


def screen(img=None):
    img = img or dev.shot()
    if upgrade_window(img):
        return "upgrade", img
    # batalla primero: el botón rojo "Terminar batalla" (aldea principal y), en la nocturna, algo más arriba
    if is_red(color(img, 60, 780, 3)) or is_red(color(img, 60, 750, 3)):
        # botón naranja «Siguiente»: el precio cambia de sitio según su longitud (350 / 1700), se miran varios puntos
        orange = any(is_orange(color(img, x, y, 3)) for x, y in ((1780, 820), (1640, 815), (1640, 725), (1880, 815)))
        return ("search" if orange else "battle"), img
    if is_green(color(img, 880, 945, 3)) and not is_yellow(color(img, 120, 1000)):
        return "result", img
    if is_yellow(color(img, 120, 1000)):
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
    last_close = None
    for _ in range(max_tries):
        if PAUSE["until"] > time.time():
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
        what, close = eyes.screen_kind(img)
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
        # 3) tecla atrás (si abre "¿Salir del juego?", la siguiente vuelta lo cancela)
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
    blocked_until[current] = time.time() + 3600
    PAUSE["until"] = time.time() + mins * 60
    PAUSE_FILE.write_text(str(PAUSE["until"]))
    log("warn", f"El dueño está jugando en {current}: cierro el juego y paro el asistente {mins} min para no echarle.")
    dev.shell("am force-stop com.supercell.clashofclans")


def owner_pause():
    """Espera (sin abrir el juego) mientras dure la pausa por el dueño."""
    if PAUSE["until"] <= time.time():
        return
    set_state(phase="pause", pause_until=PAUSE["until"])
    while PAUSE["until"] > time.time():
        check_stop()
        left = int((PAUSE["until"] - time.time()) / 60)
        log("think", f"Pausa: el dueño está jugando. Quedan {left} min.")
        for _ in range(30):
            if PAUSE["until"] <= time.time():
                break
            check_stop()
            time.sleep(10)
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
    tap(100, 110, "abrir perfil", 2.5)
    tap(1264, 206, "cambiar de cuenta (Supercell ID)", 4)
    pos = None
    for scroll in range(3):
        pos = eyes.find(dev.shot(), f'la tarjeta de la cuenta "{label}" en la lista de Supercell ID (panel derecho)')
        if pos and pos[0] > 1330 and pos[1] < 1000:
            break
        pos = None
        dev.swipe(1620, 900, 1620, 450, 500, wait=1.5)
    if not pos:
        log("warn", f"No encuentro la cuenta {label} en la lista.")
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
            msg = CFG["accounts"].get(current, {}).get("request_message")
            if msg:                            # mensaje de la petición en español (el juego guarda el último)
                tap(1200, 550, "escribir mensaje de la petición", 1.2)
                dev.shell("input keyevent KEYCODE_MOVE_END")
                dev.shell(" ; ".join(["input keyevent KEYCODE_DEL"] * 60))
                dev.shell("input text " + msg.replace(" ", "%s"))
                time.sleep(0.5)
                dev.back(1.0)                  # cierra el teclado; la ventana vuelve a su sitio
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


def line_points(side, n, inset=0.0):
    (x1, y1), (x2, y2) = SIDES[side]
    pts = []
    for i in range(n):
        t = (i + 0.5) / n
        x, y = x1 + (x2 - x1) * t, y1 + (y2 - y1) * t
        x, y = x + (CENTER[0] - x) * inset, y + (CENTER[1] - y) * inset
        pts.append((x + random.uniform(-8, 8), min(855, y + random.uniform(-8, 8))))
    return pts


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


def spell_target(side):
    """Dónde van los hechizos: donde están peleando nuestras tropas (lo busca la visión, sólo cerca de la
    entrada); si no lo ve claro, un punto fijo a un 30 % del borde hacia el centro."""
    mid = line_points(side, 1)[0]
    fallback = (mid[0] + (CENTER[0] - mid[0]) * 0.3, mid[1] + (CENTER[1] - mid[1]) * 0.3)
    try:
        p = eyes.find(dev.shot(), "el grupo de tropas atacantes peleando (donde se concentran las barras de vida "
                                  "y los combates), no la barra de cartas de abajo")
    except Exception:
        p = None
    if p and p[1] < 860:
        d_mid = (p[0] - mid[0]) ** 2 + (p[1] - mid[1]) ** 2
        d_far = (p[0] - (2 * CENTER[0] - mid[0])) ** 2 + (p[1] - (2 * CENTER[1] - mid[1])) ** 2
        d_center = (p[0] - CENTER[0]) ** 2 + (p[1] - CENTER[1]) ** 2
        if d_mid < d_far and d_center > 150 ** 2:     # el centro exacto es la respuesta «por defecto» del modelo
            log("think", f"Hechizos donde pelean las tropas: {int(p[0])},{int(p[1])}.")
            return p
    log("think", "No veo claro dónde pelean; hechizos a la entrada.")
    return fallback


def deploy(side):
    bar = read_bar(dev.shot())
    log("think", f"Ataco por {side}. Barra: " + ", ".join(s["kind"] for s in bar))
    mid = line_points(side, 1)[0]
    # 1) tropas, asedio/castillo y héroes: tocar por fuera del borde hasta que la casilla quede gris
    order = [s for s in bar if s["kind"] in ("troop", "siege")] + [s for s in bar if s["kind"] == "hero"]
    for s in order:
        tap(s["x"], 975, f"seleccionar {s['kind']}", 0.3)
        done = False
        for inset in (0.0, 0.07, 0.14, 0.21, 0.28):
            n = 1 if s["kind"] == "hero" else 6
            for _ in range(1 if s["kind"] == "hero" else 5):
                pts = line_points(side, n, inset)
                dev.taps(pts)
                log("act", f"desplegar {s['kind']}", "taps", [[int(x), int(y)] for x, y in pts])
                time.sleep(0.4)
                if slot_used(s["left"]):
                    done = True
                    break
            if done:
                break
    time.sleep(6)
    # 2) hechizos entre el lado de entrada y el centro; luego se desliza la barra por si hay más a la derecha
    tx, ty = spell_target(side)
    for _ in range(2):
        cards = read_bar(dev.shot())
        first_hero = min((c["x"] for c in cards if c["kind"] == "hero"), default=0)
        # a la derecha de los héroes sólo hay hechizos (los del castillo tienen otro color de fondo)
        spells = [c for c in cards if c["kind"] == "spell" or (c["kind"] in ("troop", "siege") and c["x"] > first_hero > 0)]
        for s in spells:
            x, y = tx + random.uniform(-25, 25), ty + random.uniform(-20, 20)
            tap(s["x"], 975, "seleccionar hechizo", 0.3)
            for _ in range(12):
                tap(x, y, "lanzar hechizo", 0.35)
                if slot_used(s["left"]):
                    break
        dev.swipe(1700, 975, 400, 975, 400, wait=1)
    # 3) habilidades: las casillas de héroe que no estén grises
    for s in read_bar(dev.shot()):
        if s["kind"] == "hero":
            tap(s["x"], 975, "habilidad del héroe", 0.3)


def leftovers(side):
    """Segunda pasada: tira lo que haya quedado sin gastar en la barra (tropas, asedio, hechizos)."""
    mid = line_points(side, 1)[0]
    left = [c for c in read_bar(dev.shot()) if c["kind"] in ("troop", "siege", "spell")]
    if not left:
        return
    log("think", f"Quedan {len(left)} casillas sin gastar; las tiro.")
    tx, ty = spell_target(side) if any(c["kind"] == "spell" for c in left) else (0, 0)
    for c in left:
        tap(c["x"], 975, f"seleccionar {c['kind']} sobrante", 0.3)
        for _ in range(12):
            if c["kind"] == "spell":
                pts = [(tx + random.uniform(-25, 25), ty + random.uniform(-20, 20))]
            else:
                pts = line_points(side, 4, 0.1)
            dev.taps(pts)
            time.sleep(0.4)
            if slot_used(c["left"]):
                break
    log("act", "desplegar sobrantes")


def _battle_sig(img):
    """Huella del botín restante y del % de daño: si no cambia, la batalla ya no avanza."""
    a = img.crop((40, 130, 300, 290)).convert("L").resize((52, 32))
    b = img.crop((1600, 780, 1900, 840)).convert("L").resize((60, 12))
    return list(a.getdata()) + list(b.getdata())


def wait_battle_end(stall_seconds=20, max_seconds=200, events=()):
    """Espera al resultado; si el botín y el % llevan stall_seconds quietos, termina la batalla.
    events: [(instante, función)] que se ejecutan a su hora (habilidades, hielos…)."""
    events = sorted(events, key=lambda e: e[0])
    t0 = time.time()
    last, since, fast = None, time.time(), False
    while time.time() - t0 < max_seconds:
        if events and events[0][0] <= time.time():
            try:
                events.pop(0)[1]()
            except Exception as e:
                log("warn", f"Evento de batalla falló: {e}")
            if events and events[0][0] <= time.time():
                time.sleep(1.2)              # atrasados: espaciados, no todos de golpe
                continue
        time.sleep(0.8 if events else 4)
        kind, img = screen()
        if kind == "result":
            return
        if not fast and speed_button(img):    # botón 1x del último minuto: x4 para acabar antes
            tap(*SPEED_BTN, "velocidad x4", 0.5)
            fast = True
        if any(not getattr(f, "is_snap", False) for _, f in events):
            continue                     # mientras queden habilidades/hielos no se da por parada
        sig = _battle_sig(img)
        if last is None or sum(abs(x - y) for x, y in zip(sig, last)) / len(sig) > 1.5:
            last, since = sig, time.time()
        elif time.time() - since >= stall_seconds:
            log("think", f"Botín y daño quietos {stall_seconds} s: termino la batalla.")
            break
    tap(137, 805, "terminar batalla", 1.5)
    tap(1167, 693, "confirmar", 5)
    for _ in range(5):
        if screen()[0] == "result":
            return
        time.sleep(2)


# ---------------- ataque planificado (visión por colores + plantillas de cartas) ----------------
SIDE_CORNERS = {"UL": ("L", "T"), "UR": ("T", "R"), "LR": ("R", "B"), "LL": ("B", "L")}
NO_TAP = [(15, 755, 262, 856), (255, 750, 905, 856),      # Terminar batalla, Potenciar ejército/héroes
          (1760, 545, 1915, 695), (1580, 690, 1915, 856)]    # botón de velocidad, Siguiente/daño
SPECIAL = {"healer", "wallbreaker", "siege", "queen", "king", "warden", "prince", "cc", "champion", "duke",
           "totem", "revive", "earthquake",
           "lightning", "cc_lightning", "freeze", "cc_freeze", "rage"}
TANKS = {"giant", "golem", "pekka", "giant_skeleton"}      # van delante a comerse las defensas
AIR = {"edrag", "balloon", "dragon", "dragonrider", "superdragon", "baby_dragon", "minion", "archer"}


def _safe(x, y):
    return 20 <= x <= 1900 and 70 <= y <= 858 and not any(a <= x <= c and b <= y <= d for a, b, c, d in NO_TAP)


def _dilate(m, k):
    import cv2
    return cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))


def _push_out(geo, x, y, nx, ny, start=18):
    """Primer punto fuera de la aldea (con margen) avanzando hacia fuera por (nx, ny)."""
    md = geo["mask_d"]
    for k in range(14):
        px, py = x + nx * (start + 10 * k), y + ny * (start + 10 * k)
        if _safe(px, py) and md[int(py), int(px)] == 0:
            return px, py
    return None


def side_points(geo, side, n, extra=0):
    """n puntos de despliegue a lo largo del lado, justo por fuera del borde; y la normal hacia fuera."""
    a, b = (geo["corners"][k] for k in SIDE_CORNERS[side])
    ex, ey = b[0] - a[0], b[1] - a[1]
    L = math.hypot(ex, ey) or 1
    nx, ny = -ey / L, ex / L
    cx, cy = geo["center"]
    mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    if nx * (mx - cx) + ny * (my - cy) < 0:
        nx, ny = -nx, -ny
    pts = []
    for i in range(n):
        t = 0.08 + 0.84 * (i + 0.5) / n
        p = _push_out(geo, a[0] + ex * t, a[1] + ey * t, nx, ny, 18 + extra)
        if p:
            pts.append(p)
    return pts, (nx, ny)


def queen_corner(geo, k):
    """Punto para la reina en la esquina k: en el vértice hay un edificio y la flecha (horizontal desde
    L/R, vertical desde T/B) cruza la aldea por el medio. None si no sirve."""
    x, y = geo["corners"][k]
    lft, top, rgt, asistente = geo["box"]
    if k in "LR":
        if abs(y - (top + asistente) / 2) > 0.18 * (asistente - top):
            return None
    elif abs(x - (lft + rgt) / 2) > 0.18 * (rgt - lft) or y < 75 or y > 840:
        return None
    # lo más lejos posible en el eje (dentro de su alcance): así un error de unos px en la altura del
    # edificio apenas tuerce la flecha
    d = {"L": (-1, 0), "R": (1, 0), "T": (0, -1), "B": (0, 1)}[k]
    for off in (100, 75, 50, 28):
        q = (x + d[0] * off, y + d[1] * off)
        if _safe(*q) and not geo["mask_d"][int(q[1]), int(q[0])]:
            return q
    return None


def _map_geometry():
    m = vision.default_mask()
    import numpy as np
    ys, xs = np.nonzero(m)
    return {"corners": {"L": (int(xs.min()), 495), "R": (int(xs.max()), 495), "T": (960, int(ys.min())),
                        "B": (960, int(ys.max()))},
            "center": (float(xs.mean()), float(ys.mean())), "mask": m, "src": "mapa",
            "box": (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))}


def plan_attack(img, acc=None):
    """Elige lado de entrada, defensas aéreas a fulminar y esquina para la reina."""
    geo = vision.village_geometry(img, fallback=True)
    ads = vision.find_air_defenses(img)
    if geo["src"] != "mapa" and ads:
        big = _dilate(geo["mask"], 61)
        if any(not big[min(1079, int(y)), min(1919, int(x))] for x, y in ads):
            # una defensa aérea fuera del contorno: el contorno está mal → rombo del mapa entero
            geo = _map_geometry()
    geo["mask_d"] = _dilate(geo["mask"], 13)
    exact = geo["src"] != "mapa"            # sin contorno real no se arriesga la reina en esquina
    acfg = CFG["accounts"].get(acc, {})
    per = acfg.get("lightning_per_ad", 3)
    n_zap = acfg.get("lightning_total", 9) // per          # 0 rayos → todas las aéreas van a hielo
    best = None
    for side, (ka, kb) in SIDE_CORNERS.items():
        pts, normal = side_points(geo, side, 9)
        if len(pts) < 4:
            continue
        mx = sum(p[0] for p in pts) / len(pts)
        my = sum(p[1] for p in pts) / len(pts)
        ds = sorted(ads, key=lambda a: (a[0] - mx) ** 2 + (a[1] - my) ** 2)
        zap, rest = ds[:n_zap], ds[n_zap:]
        score = min(math.hypot(r[0] - mx, r[1] - my) for r in rest) if rest else 1500
        score += 15 * len(pts)
        qc = None
        for k in ((ka, kb) if exact else ()):
            qp = queen_corner(geo, k)
            if qp and not qc:
                qc = (k, qp)
        if qc:
            score += 200
        if best is None or score > best["score"]:
            best = {"side": side, "pts": pts, "normal": normal, "mid": (mx, my), "zap": zap, "rest": rest,
                    "queen": qc, "score": score, "geo": geo, "per_ad": per}
    if best and not best["queen"] and exact:   # una esquina buena aunque no toque el lado de entrada
        for k in "LRTB":
            qp = queen_corner(geo, k)
            if qp:
                best["queen"] = (k, qp)
                break
    return best


def deployed(img, c):
    """Héroe/asedio en el campo: aparece su barra de vida verde encima de la carta."""
    return any(is_green(color(img, c["x"] + dx, 866, 3)) for dx in (-30, 0, 30))


def _slot_sig(img, c):
    a = img.crop((c["left"] + 5, 850, c["left"] + 135, 1060)).convert("L").resize((26, 42))
    return list(a.getdata())


def place_unit(c, points, label, wait=0.45):
    """Despliega un héroe/asedio: si la casilla cambia (sale barra de vida, se oscurece, sube la carta)
    es que ha salido; si no cambia nada, el punto no valía y se prueba el siguiente."""
    for p in points[:6]:
        refresh_card(dev.shot(), c)
        tap(c["x"], 975, f"seleccionar {label}", 0.3)
        before = _slot_sig(dev.shot(), c)     # ya seleccionada: que el resalte no cuente como cambio
        tap(*p, f"desplegar {label}", wait)
        img = dev.shot()
        if deployed(img, c) or card_used(img, c["left"]):
            return p
        diff = sum(abs(a - b) for a, b in zip(before, _slot_sig(img, c))) / len(before)
        if diff > 9:
            return p
    log("warn", f"No he conseguido desplegar {label}.")
    return None


def back_points(plan, n=4):
    """Puntos de la línea más cercanos al centro del lado, un poco más por fuera (validados)."""
    mid, (nx, ny) = plan["mid"], plan["normal"]
    out = []
    for x, y in sorted(plan["pts"], key=lambda p: (p[0] - mid[0]) ** 2 + (p[1] - mid[1]) ** 2):
        q = _push_out(plan["geo"], x, y, nx, ny, 25)
        out.append(q or (x, y))
    out = out[:n]
    # por si el contorno era malo: el centro del lado en el borde del mapa (siempre legal)
    edge = map_edge_points(plan["side"], 5)
    return out + edge[1:4]


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


def _shift(plan, pts, d):
    """Desplaza los puntos d px por la normal del lado (d>0 hacia fuera, d<0 hacia la aldea)."""
    nx, ny = plan["normal"]
    return [(x + nx * d, y + ny * d) for x, y in pts if _safe(x + nx * d, y + ny * d)]


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


def deploy_card(c, pts, plan, label, passes=4):
    """Despliega TODO lo de una carta: ráfagas sobre los mismos puntos mientras el número de la carta
    vaya bajando; si una ráfaga no saca nada, los puntos se mueven (más por fuera, luego hacia dentro),
    por si caían en zona prohibida o fuera del mapa. Nunca toca de más una carta ya vacía (el juego
    pasaría a la siguiente carta y la soltaría donde no toca)."""
    base, k, bursts, remaining = list(pts), 0, 0, 1
    # orden de reserva: borde del mapa del propio lado y luego de los lados vecinos (por si ese lado
    # está entero dentro de la zona roja, p. ej. un campo de muros pegado al borde)
    order = {"UL": ["UL", "LL", "UR", "LR"], "UR": ["UR", "UL", "LR", "LL"],
             "LR": ["LR", "UR", "LL", "UL"], "LL": ["LL", "UL", "LR", "UR"]}[plan["side"]]
    passes = max(passes, 6)
    tap(c["x"], 975, f"seleccionar {label}", 0.25)
    while bursts < 20 and k < passes:
        img = dev.shot()
        refresh_card(img, c)
        if card_used(img, c["left"]):
            return True
        if bursts == 0:                        # el número se lee sólo la primera vez (cuesta ~2 s)
            try:
                remaining = eyes.card_count(img, c["left"]) or 1
            except Exception:
                remaining = 1
        # nunca más toques que unidades quedan: al vaciarse, el juego selecciona la carta siguiente
        n = max(1, min(remaining, 3))          # tandas de 3 como mucho, comprobando la carta entre tanda y tanda
        before = _card_sig(img, c)
        burst = [pts[(bursts * 3 + i) % len(pts)] for i in range(n)]
        remaining -= len(burst)
        dev.taps([(int(x), int(y)) for x, y in burst])
        log("act", f"desplegar {label} ×{len(burst)}", "taps", [[int(x), int(y)] for x, y in burst])
        bursts += 1
        time.sleep(0.4)
        img = dev.shot()
        refresh_card(img, c)
        if card_used(img, c["left"]):
            return True
        if remaining <= 0:                     # según la cuenta ya salió todo: vuelve a seleccionar y comprueba
            tap(c["x"], 975, f"seleccionar {label}", 0.25)
            remaining = 1
        moved = sum(abs(a - b) for a, b in zip(before, _card_sig(img, c))) / len(before) > 6
        if not moved:                         # nada salió: los puntos no valen
            remaining += len(burst)
            if k == 0:
                pts = _shift(plan, base, 40) or base
            else:                              # contorno mal leído: al borde del mapa, y si no, otro lado
                sd = order[min(k - 1, 3)]
                pts = map_edge_points(sd, max(3, len(base))) or base
                if k >= 2:
                    log("warn", f"{label}: no sale por {order[k - 2]}; pruebo el borde {sd}.")
            k += 1
            tap(c["x"], 975, f"seleccionar {label}", 0.25)
    return slot_used(c["left"])


BAR = {"scrolled": False}


def scroll_bar(right):
    """La barra tiene más cartas que pantalla: right=True enseña las de la derecha (hechizos del castillo)."""
    if right != BAR["scrolled"]:
        dev.swipe(*((1700, 975, 300, 975) if right else (300, 975, 1700, 975)), 350, wait=0.6)
        BAR["scrolled"] = right


CARD_POS = {}                      # (nombre, barra desplazada) -> carta; se vacía en cada batalla


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
SPELLS = {"lightning", "cc_lightning", "freeze", "cc_freeze", "rage", "totem", "revive", "earthquake"}


def spam_card(c, pts, label, rounds=4, side=None):
    """Suelta toda la carta de golpe: ráfagas por todo el lado hasta que se vacía (sin contar unidades).
    Si queda tropa, la siguiente ráfaga va un poco más hacia dentro (por si caía fuera del mapa)."""
    for r in range(rounds):
        img = dev.shot()
        refresh_card(img, c)
        if card_used(img, c["left"]):
            return
        if side and r:
            pts = map_edge_points(side, 9, 0.08 + 0.06 * r) or pts
        tap(c["x"], 975, f"seleccionar {label}", 0.1)
        dev.taps([(int(x), int(y)) for x, y in pts])      # 9 toques repartidos por todo el lado
        log("act", f"desplegar {label} de golpe", "taps", [[int(x), int(y)] for x, y in pts])


def spam_attack(shot):
    """Ataque TH18 probado a mano (2★ 90 %). Sin planes largos: todo de golpe y los hechizos a su sitio."""
    plan = plan_attack(shot)
    geo = plan["geo"]
    c4 = geo["corners"]                       # L, R, T, B
    cx, cy = geo["center"]
    # lado de la reina: la esquina izquierda o la derecha (las que dejan la flecha cruzar en horizontal),
    # la que tenga más cerca las aéreas (así los dragones las encuentran pronto); el duque, la contraria
    ads = plan["zap"] + plan["rest"]
    def near(k):
        x, y = c4[k]
        return sum(1 for a in ads if abs(a[0] - x) < 500)
    qk = "L" if near("L") >= near("R") else "R"
    dk = "R" if qk == "L" else "L"
    off = lambda k, d: (c4[k][0] + (-d if k == "L" else d), c4[k][1])   # un poco por fuera de la esquina
    qpos, dpos = off(qk, 25), off(dk, 25)
    for p_ in (qpos, dpos):
        if not _safe(*p_):
            pass
    side = "UL" if qk == "L" else "UR"        # lado del ejército: los dos lados que salen de la esquina
    side2 = "LL" if qk == "L" else "LR"
    pts = map_edge_points(side, 4, 0.12)[-3:] + [qpos] + map_edge_points(side2, 4, 0.12)[:3]
    plan.update(side=side, pts=pts, normal=(-1 if qk == "L" else 1, 0))
    log("think", f"Ataque TH18: reina por la esquina {qk}, duque por la contraria ({dk}); todo el ejército por {qk}.")
    BAR["scrolled"] = False
    cards = bar_cards()
    t0 = time.time()

    # 1) reina + flecha, duque en la esquina contraria + mochila (se juntan en el centro)
    # reserva por si la esquina leída cae en zona roja: la esquina del mapa (siempre legal) y un poco más dentro
    mapc = {"L": [(285, 495), (330, 495), (380, 470)], "R": [(1635, 495), (1590, 495), (1540, 470)]}
    qcands, dcands = [qpos] + mapc[qk], [dpos] + mapc[dk]
    for name, cands, label in (("queen", qcands, "flecha de la reina"), ("duke", dcands, "mochila del duque")):
        c = _find(cards, name)
        if c:
            got = place_unit(c, cands, f"{name} en la esquina", 0.3)
            if got:
                if name == "queen":
                    qpos = got
                tap(c["x"], 975, label, 0.15)

    # 2) todo el ejército aéreo de golpe por el lado de la reina
    for c in cards:
        if c["name"] in HEROES or c["name"] in SPELLS or c["kind"] == "spell" or c["name"] == "archer":
            continue
        if c["kind"] in ("troop", "siege") or c["name"] in AIR | TANKS:
            spam_card(c, pts, c["name"] or "tropa", side=None)

    # 3) centinela y guerrera con el ejército; su habilidad 5 s después de empezar a pelear
    for name in ("warden", "champion", "king", "prince"):
        c = _find(cards, name)
        if c:
            place_unit(c, [qpos] + qcands + pts, f"{name} con el ejército", 0.3)
    events = []
    for name in ("warden", "champion", "king", "prince"):
        events.append((t0 + 9, lambda n=name: tap_card((n,), f"habilidad de {n}")))

    # 4) tótems delante del ejército (absorben el daño), terremotos al centro, revivir, arquera
    inward = lambda k: (qpos[0] + (cx - qpos[0]) * k, qpos[1] + (cy - qpos[1]) * k)
    for i, k in enumerate((0.14, 0.2, 0.26)):
        events.append((t0 + 5 + i, lambda k=k: cast_spell(("totem",), *inward(k), "tótem delante del ejército")))
    for k in range(2):
        events.append((t0 + 12 + k, lambda: cast_spell(("earthquake",), cx + random.uniform(-30, 30), cy + random.uniform(-20, 20), "terremoto al centro")))
    events.append((t0 + 24, lambda: cast_spell(("revive",), cx - 30, cy + 10, "revivir en el centro")))
    for i, k in enumerate((0.4, 0.55, 0.7, 0.85)):
        events.append((t0 + 14 + 4 * i, lambda k=k: cast_spell(("totem",), *inward(k), "tótem siguiendo al ejército")))
    events.append((t0 + 27, lambda: cast_spell(("rage", "freeze", "cc_freeze"), cx, cy, "hechizo del castillo al centro")))
    ar = _find(cards, "archer")
    if ar:
        events.append((t0 + 30, lambda: spam_card(ar, pts, "arquera de limpieza", rounds=3)))
    return plan, events


def plan_leftovers(plan):
    """Tropas que hayan quedado sin salir (no hechizos: esos tienen su momento)."""
    img = dev.shot()
    left = [c for c in bar_cards(img) if not card_used(img, c["left"])
            and (c["kind"] in ("troop", "siege") or c["name"] in AIR | TANKS)
            and c["name"] not in SPECIAL                       # héroes, asedio, castillo y hechizos tienen su momento
            and c["name"] is not None and c["name"] != "archer"]   # desconocidas fuera; la arquera sale luego a limpiar
    for c in left:
        log("think", f"Queda {c['name'] or 'tropa'} sin salir; la despliego.")
        deploy_card(c, plan["pts"], plan, c["name"] or "tropa", passes=2)


DUKE_DONE = set()
COMBO = {}


def duke_down():
    """¿El duque ha caído? (su carta en gris)."""
    img = dev.shot()
    for c in read_bar(img):                  # vivo: su carta se reconoce y no está gris
        if vision.card_identity(img, c["left"])[0] == "duke":
            COMBO["duke_left"] = c["left"]
            return card_grey(img, c["left"])
    left = COMBO.get("duke_left")            # muerto: la carta gris oscura ni sale en la barra → mirar su sitio
    return left is not None and card_grey(img, left)


def execute_plan(plan):
    """Ataque coherente: rayos a las aéreas → reina (flecha) + sanadoras → línea de tropas → asedio →
    héroes → habilidades y hielos a su hora. Devuelve los eventos programados para la espera."""
    BAR["scrolled"] = False
    side, pts, mid = plan["side"], plan["pts"], plan["mid"]
    nx, ny = plan["normal"]
    backs = back_points(plan)                             # detrás de la línea, para héroes y asedio
    back = backs[0]
    q = plan["queen"]
    log("think", f"Plan (contorno por {plan['geo']['src']}): entro por {side}; rayos a {len(plan['zap'])} aéreas {plan['zap']}; "
                 f"{'reina en esquina ' + q[0] if q else 'reina con la tropa'}; aéreas sin rayos: {plan['rest']}.")
    cards = bar_cards()
    log("think", "Barra: " + ", ".join(c["name"] or c["kind"] for c in cards))
    t0 = time.time()
    events = []

    # 1) rayos: 3 por aérea (4 a la primera si hay del castillo), propios primero y luego el del castillo
    for i, (ax, ay) in enumerate(plan["zap"]):
        need = plan.get("per_ad", 3)
        while need > 0:
            img = dev.shot()
            c = next((c for c in bar_cards(img) if c["name"] in ("lightning", "cc_lightning")
                      and not card_used(img, c["left"])), None)
            if not c:
                break
            tap(c["x"], 975, "seleccionar rayo", 0.2)
            for _ in range(need):
                tap(ax + random.uniform(-4, 4), ay + random.uniform(-4, 4), f"rayo a la aérea {int(ax)},{int(ay)}", 0.3)
            need = 0
            if card_used(dev.shot(), c["left"]) and c["name"] == "lightning":
                need = 1                     # la propia se agotó a medias: uno más con la del castillo

    # 2) reina: en la esquina y flecha gigante al instante; sanadoras detrás de ella
    qc, hc = _find(cards, "queen"), _find(cards, "healer")
    if qc:
        qp = place_unit(qc, ([q[1]] if q else []) + backs, "reina", 0.2) or back
        if q and qp == q[1]:
            time.sleep(0.4)
            tap(qc["x"], 975, "flecha gigante de la reina", 0.3)
            for i in range(4):               # capturas para revisar la flecha
                dev.shot().save(HERE / f"flecha{i}.png")
                time.sleep(0.3)
        else:
            events.append((5, lambda: tap_card(("queen",), "habilidad de la reina")))
        dk = _find(cards, "duke")
        gx, gy = plan["geo"]["center"]
        line = lambda k: (qp[0] + (gx - qp[0]) * k, qp[1] + (gy - qp[1]) * k)   # de la reina al centro
        COMBO.update(line=line, revived=False, start=time.time())
        if dk:                               # duque justo detrás de la reina, en la línea de la flecha + mochila
            COMBO["duke_left"] = dk["left"]
            if place_unit(dk, [qp] + backs, "duque en la línea de la flecha"):
                time.sleep(0.3)
                tap_card(("duke",), "mochila del duque")
                DUKE_DONE.add(id(dk))
        # terremotos en la línea: uno al centro y otro a 3/4 del camino, donde llegan flecha y duque
        for k in (1.0, 0.78, 1.0):            # el 3.º sólo por si alguno no salió
            x, y = line(k)
            cast_spell(("earthquake",), x + random.uniform(-10, 10), y + random.uniform(-8, 8), "terremoto en la línea del duque")
            time.sleep(0.3)
        # primer tótem de escudo por delante del duque, para que las defensas apunten al tótem
        cast_spell(("totem",), *line(0.35), "tótem: escudo del duque")
        if hc:
            off = {"L": (-28, 0), "R": (28, 0), "T": (0, -28), "B": (0, 28)}.get(q[0] if q else "", (nx * 25, ny * 25))
            hp = (qp[0] + off[0], qp[1] + off[1])
            hp = hp if _safe(*hp) else qp
            tap(hc["x"], 975, "seleccionar sanadoras", 0.25)
            dev.taps([(int(hp[0]), int(hp[1]))] * 2)
            log("act", "sanadoras detrás de la reina", "taps", [[int(hp[0]), int(hp[1])]])

    # 3) tropa: si hay tanques, delante y concentrados; detrás rompemuros, luego los que pegan y por
    #    último los aéreos (globos) cuando las defensas ya miran a los tanques. Sin tanques: aéreos en línea.
    t0 = time.time()                         # los tiempos de hielos/habilidades cuentan desde aquí
    # tropa = por nombre (el color de la carta engaña: las «super» son rojas como los héroes)
    troops = [c for c in cards if c["name"] is not None and c["name"] not in SPECIAL
              and (c["kind"] == "troop" or c["name"] in AIR | TANKS)]
    tanks = [c for c in troops if c["name"] in TANKS]
    air = [c for c in troops if c["name"] in AIR]
    dps = [c for c in troops if c not in tanks and c not in air]
    centre = pts[len(pts) // 4: len(pts) - len(pts) // 4] or pts
    for c in tanks:
        deploy_card(c, centre, plan, c["name"])
    if tanks:
        time.sleep(2.5)
        wb0 = _find(cards, "wallbreaker")
        if wb0:
            deploy_card(wb0, centre[:2], plan, "rompemuros", passes=2)
    for c in dps:
        deploy_card(c, centre if tanks else pts, plan, c["name"])
    if tanks and air:
        time.sleep(2)
    air.sort(key=lambda c: c["name"] not in ("dragon", "superdragon", "edrag", "dragonrider"))
    # globos por el extremo del lado (con el asedio aéreo): abren otro frente y buscan defensas
    flank = pts[-3:] if len(pts) >= 5 else pts
    for c in [c for c in air if c["name"] == "balloon"]:
        deploy_card(c, flank, plan, "globos (por el extremo)")
    sg = _find(cards, "siege")
    if sg:
        place_unit(sg, flank + backs, "asedio aéreo con los globos")
    air = [c for c in air if c["name"] not in ("balloon", "archer")]
    drg = next((c for c in air if c["name"] in ("dragon", "superdragon")), None)
    if drg and len(pts) >= 4:                # funnel: limpian los extremos para que el grueso vaya al centro
        for end in (pts[0], pts[-1]):
            tap(drg["x"], 975, "seleccionar dragón de funnel", 0.25)
            tap(*end, "dragón de funnel en el extremo", 0.3)
        log("think", "Funnel: un dragón en cada extremo; el grueso entra por el centro del lado en unos segundos.")
        time.sleep(4)
    centre = pts[len(pts) // 5: len(pts) - len(pts) // 5] or pts
    for i, c in enumerate(air):
        deploy_card(c, centre, plan, c["name"])
    if hc and not qc:
        deploy_card(hc, [back], plan, "sanadoras")

    # 4) asedio detrás del centro de la línea
    sc = _find(cards, "siege")
    if sc and not slot_used(sc["left"]):
        place_unit(sc, backs, "asedio")
    cc = _find(cards, "cc")
    if cc and cc.get("name") == "cc" and _card_empty(dev.shot(), cc):
        log("think", "Castillo vacío (aún no han donado): no lo despliego.")
        cc = None
    if cc:
        deploy_card(cc, backs[:2], plan, "tropas del castillo", passes=2)
    time.sleep(1.0)

    # 5) héroes detrás de la tropa (habilidad a su hora); rompemuros con el rey
    # guerrera: habilidad pronto, la lanza limpia defensas desde lejos; centinela: cuando los dragones
    # llegan a las defensas, para barrer un hueco y proteger al grupo
    delays = {"warden": 9, "prince": 14, "king": 6, "champion": 5, "duke": 3}
    for hero in ("warden", "prince", "king", "champion", "duke"):
        c = _find(cards, hero)
        if not c or id(c) in DUKE_DONE:
            continue
        if not place_unit(c, backs, hero):
            continue
        events.append((delays[hero], lambda h=hero: tap_card((h,), f"habilidad de {h}")))
    wb = _find(cards, "wallbreaker")
    if wb and not slot_used(wb["left"]):
        deploy_card(wb, backs[:2], plan, "rompemuros", passes=2)
    # cartas que no conozco (otra cuenta, tropas del castillo): a la línea / detrás
    for c in cards:
        if c["name"] is None and c["kind"] == "troop":
            deploy_card(c, pts, plan, "tropa")
        elif c["name"] is None and c["kind"] == "hero":
            if not place_unit(c, backs, "héroe"):
                continue
            events.append((8, lambda c=c: tap(c["x"], 975, "habilidad del héroe", 0.2)))

    # 6) hielos: a la aérea que quedó sin rayos cuando lleguen los dragones; luego al centro
    cx, cy = plan["geo"]["center"]
    for i, (rx, ry) in enumerate(plan["rest"][:3]):
        eta = 3 + math.hypot(rx - mid[0], ry - mid[1]) / 55      # dragones ~55 px/s con zoom mínimo
        events.append((eta, lambda rx=rx, ry=ry: cast_spell(("freeze", "cc_freeze"), rx, ry, "hielo a la aérea")))
        if i == 0:
            events.append((eta + 6, lambda rx=rx, ry=ry: cast_spell(("freeze", "cc_freeze"), rx, ry, "hielo a la aérea")))
    events.append((20, lambda: cast_spell(("freeze", "cc_freeze"), cx, cy, "hielo al centro")))
    events.append((26, lambda: cast_spell(("freeze", "cc_freeze"), cx, cy, "hielo al centro")))
    # lo que sobre: donde estén peleando ahora (lo busca la visión; si no, hacia el centro)
    def late(names, label):
        img = dev.shot()
        if not any(c["name"] in names and not card_used(img, c["left"]) for c in bar_cards(img)):
            return
        x, y = spell_target(side)
        cast_spell(names, x, y, label)
    for t in (32, 38, 44):
        events.append((t, lambda: late(("freeze", "cc_freeze"), "hielo sobrante")))
        events.append((t + 3, lambda: late(("rage",), "furia sobrante")))
    # terremotos: los dos juntos sobre la aérea más lejana (la última a la que llegan los dragones),
    # para debilitarla antes de que llegue la tropa (los hielos van a las cercanas)
    if not q:                              # sin flecha en esquina los terremotos no salieron: al centro igual
        for k in range(2):
            events.append((1 + k, lambda: cast_spell(("earthquake",), cx, cy, "terremoto al centro")))
    # tótems: escudo del duque a lo largo de su línea (absorben el DPS que iría a él); 2 se guardan
    line = COMBO.get("line")
    if line:
        for i, k in enumerate((0.55, 0.75, 0.9)):
            events.append((2 + 4 * i, lambda k=k: cast_spell(("totem",), *COMBO["line"](k), "tótem: escudo del duque")))
        # el resto, delante de la tropa principal cuando entra al centro
        for i, k in enumerate((0.45, 0.65)):
            tx_, ty_ = mid[0] + (cx - mid[0]) * k, mid[1] + (cy - mid[1]) * k
            events.append((16 + 5 * i, lambda tx_=tx_, ty_=ty_: cast_spell(("totem",), tx_, ty_, "tótem delante de la tropa")))
    else:
        for i, k in enumerate((0.22, 0.32, 0.42, 0.52, 0.62, 0.72)):
            tx_, ty_ = mid[0] + (cx - mid[0]) * k, mid[1] + (cy - mid[1]) * k
            events.append((5 + 4 * i, lambda tx_=tx_, ty_=ty_: cast_spell(("totem",), tx_, ty_, "tótem delante de la tropa")))
    # arquera de limpieza, cuando la tropa ya está dentro
    ar = _find(cards, "archer")
    if ar:
        events.append((22, lambda: deploy_card(ar, backs[:2], plan, "arquera de limpieza", passes=2)))

    # revivir: se vigila la carta del duque; en cuanto cae, revivir donde iba (su línea, según el tiempo)
    # y un tótem al lado para que el duque revivido aguante más
    def check_duke():
        if COMBO.get("revived") or not COMBO.get("line"):
            return
        if not duke_down():
            return
        t = time.time() - COMBO.get("start", time.time())
        k = min(1.0, 0.45 + t / 40)          # vuela por la línea hacia el centro
        x, y = COMBO["line"](k)
        if cast_spell(("revive",), x, y, f"revivir al duque (cayó hacia el {int(k * 100)} % de su línea)"):
            COMBO["revived"] = True
            cast_spell(("totem",), x + 25, y, "tótem que protege al duque revivido")
    for t in range(4, 60, 2):
        events.append((t, check_duke))
    if not COMBO.get("line"):
        events.append((30, lambda: cast_spell(("revive",), *spell_target(side), "resurrección sobre los héroes")))
    # furias: siguen a la tropa (de la entrada hacia el centro)
    for i, k in enumerate((0.2, 0.32, 0.44, 0.56, 0.68, 0.8)):
        rx, ry = mid[0] + (cx - mid[0]) * k, mid[1] + (cy - mid[1]) * k
        events.append((3 + 3.5 * i, lambda rx=rx, ry=ry: cast_spell(("rage",), rx, ry, "furia sobre la tropa")))
    # hechizos que no conozco (furia, curación… de otra cuenta): sobre la tropa al entrar
    tgt = (mid[0] + (cx - mid[0]) * 0.3, mid[1] + (cy - mid[1]) * 0.3)

    def unknown_spell(c):
        tap(c["x"], 975, "seleccionar hechizo", 0.25)
        for _ in range(6):
            tap(tgt[0] + random.uniform(-25, 25), tgt[1] + random.uniform(-20, 20), "lanzar hechizo", 0.35)
            if slot_used(c["left"]):
                break
    for i, c in enumerate(c for c in cards if c["name"] is None and c["kind"] == "spell"):
        events.append((7 + 3 * i, lambda c=c: unknown_spell(c)))
    return [(t0 + t, f) for t, f in events]


def attack(acc):
    """Busca un rival que cumpla el criterio, ataca, espera y apunta el botín. True si atacó."""
    rule = CFG["accounts"][acc]["min_loot"]
    if not main_village():
        return False
    try:
        collect_resources()
    except Exception as e:
        log("warn", f"No he podido recoger recursos: {e}")
    full = ()
    cap = CFG["accounts"][acc]["capacity"]
    if cap:
        res = eyes.my_resources(dev.shot())
        a = CFG["accounts"][acc]
        fr = a.get("full_ratio", CFG["full_ratio"])
        ratio = {"gold": fr, "elixir": fr, "dark": a.get("dark_full_ratio", CFG.get("dark_full_ratio", 0.5))}
        full = tuple(k for k in ("gold", "elixir", "dark") if (res.get(k) or 0) >= cap[k] * ratio[k])
        focus = a.get("farm_focus")
        if focus:
            full = tuple(k for k in ("gold", "elixir", "dark") if k not in focus or k in full)
        if full:
            log("think", f"Ya lleno en {acc}: {', '.join(full)} → sólo busco lo que falta.")
    home_before = eyes.my_resources(dev.shot())
    note_resources(acc, home_before)
    tap(120, 960, "abrir Batalla", 2.5)
    if not battle_menu_open():
        log("warn", "El menú Batalla no se ha abierto.")
        go_home()
        return False
    tap(400, 800, "Buscar batalla (NORMAL, tarjeta izquierda)", 3)
    if screen()[0] != "search" and is_green(color(dev.shot(), 1820, 990, 4)):
        tap(1695, 962, "Atacar (confirmar ejército)", 8)
    for n in range(CFG["accounts"][acc]["max_searches"]):
        check_stop()
        kind, img = screen()
        for _ in range(5):            # las nubes entre bases a veces tardan
            if kind == "search":
                break
            time.sleep(3)
            kind, img = screen()
        if kind != "search":
            if True:
                img.save(HERE / "no_busqueda.png")
                log("warn", "No estoy en la búsqueda; vuelvo a casa (captura en no_busqueda.png).")
                go_home()
                return False
        loot = eyes.loot_available(img)
        ok = good_target(loot, rule, full) or n == CFG["accounts"][acc]["max_searches"] - 1
        log("think", f"Rival: {loot['gold']} oro / {loot['elixir']} elixir / {loot['dark']} oscuro → "
                     f"{'ATACO' if ok else 'siguiente'}")
        if ok:
            break
        tap(1750, 765, "Siguiente", 5)
    dev.zoom_out(2)
    before = eyes.my_resources(dev.shot())
    shot = dev.shot()
    plan = None
    try:
        plan = plan_attack(shot, acc)
    except Exception as e:
        log("warn", f"No he podido planificar el ataque: {e}")
    try:
        save_plan_image(shot, plan)
    except Exception as e:
        log("warn", f"No he guardado la imagen del plan: {e}")
    if plan and CFG["accounts"].get(acc, {}).get("attack_mode") == "spam":
        plan, events = spam_attack(shot)
        snap("despliegue")
        t_end = time.time()
        for k, dt in enumerate((15, 35, 60, 90)):
            f = lambda k=k: snap(f"batalla{k}")
            f.is_snap = True
            events.append((t_end + dt, f))
        wait_battle_end(events=events)
    elif plan:
        events = execute_plan(plan)
        snap("despliegue")
        time.sleep(2)
        plan_leftovers(plan)
        t_end = time.time()
        for k, dt in enumerate((15, 35, 60, 90)):
            f = lambda k=k: snap(f"batalla{k}")
            f.is_snap = True                 # las capturas no retrasan el «botín quieto → terminar»
            events.append((t_end + dt, f))
        wait_battle_end(events=events)
    else:
        side = eyes.best_side(shot)
        log("think", "No veo bien el contorno de la aldea: ataque simple.")
        deploy(side)
        time.sleep(4)
        leftovers(side)
        wait_battle_end()
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
    LAST_GAIN.update(gained)
    log("done", f"Ataque terminado en {acc}: +{gained['gold']} oro, +{gained['elixir']} elixir, +{gained['dark']} oscuro.")
    return True


def collect_resources():
    """Recoge las burbujas de colectores/minas/taladros de la aldea (sólo toques sobre la propia aldea)."""
    if not go_home():
        return
    img = dev.shot()
    if selection_bar(img):
        log("think", "Hay un edificio seleccionado: no recojo para no tocar sus botones.")
        return
    pts = [(x, y) for x, y in eyes.resource_bubbles(img)
           if safe_map_point(x, y) and y < 700]           # lejos de botones y de la barra de un edificio
    if pts:
        dev.taps(pts)
        log("act", f"recoger {len(pts)} burbujas de recursos", "taps", [[int(x), int(y)] for x, y in pts])
        time.sleep(1.5)
        deselect()


SEEN_BIG = {}


def note_resources(acc, res, village="main"):
    """Guarda lo último leído de cada cuenta/aldea para el visor."""
    try:
        st = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    except (OSError, ValueError):
        st = {}
    capkey = "capacity" if village == "main" else "builder_capacity"
    cap = CFG["accounts"].get(acc, {}).get(capkey)
    if cap:
        for k in ("gold", "elixir", "dark"):
            v = res.get(k)
            # más de lo que «cabe»: han ampliado los almacenes → se aprende la capacidad nueva
            # (con tope ×1,6 para no creerse una mala lectura)
            big = v and cap.get(k) and v > cap[k] * 1.6
            if big:                           # muy por encima: se acepta si se lee igual dos veces seguidas
                seen = SEEN_BIG.get((acc, village, k))
                SEEN_BIG[(acc, village, k)] = v
                big = seen is not None and abs(seen - v) < 0.05 * v
            if v and cap.get(k) and (cap[k] < v <= cap[k] * 1.6 or big):
                log("think", f"{acc}: {k} {v} supera la capacidad apuntada ({cap[k]}): la actualizo.")
                cap[k] = int(v)
                save_account_field(acc, capkey, cap)
    allr = st.get("resources", {})
    allr[f"{acc}|{village}"] = {**{k: res.get(k) for k in ("gold", "elixir", "dark")}, "ts": time.time()}
    set_state(resources=allr)


def storages_full(acc):
    cap = CFG["accounts"][acc]["capacity"]
    if not cap or not main_village():
        return False
    res = eyes.my_resources(dev.shot())
    note_resources(acc, res)
    a = CFG["accounts"][acc]
    r = a.get("full_ratio", CFG["full_ratio"])
    dr = a.get("dark_full_ratio", CFG.get("dark_full_ratio", 0.5))
    focus = a.get("farm_focus")                # p. ej. ["elixir"]: sólo cuenta eso
    if focus:
        full = all((res.get(k) or 0) >= cap[k] * (dr if k == "dark" else r) for k in focus)
    else:
        full = all((res.get(k) or 0) >= cap[k] * r for k in ("gold", "elixir")) and (res.get("dark") or 0) >= cap["dark"] * dr
    log("think", f"{acc}: oro {res['gold']}/{cap['gold']}, elixir {res['elixir']}/{cap['elixir']}, "
                 f"oscuro {res['dark']}/{cap['dark']} → {'LLENO' if full else 'falta'}")
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


def collect_cart():
    """Recoge el elixir del Carro de elixir (junto al muelle de la aldea nocturna) si hay algo."""
    if not go_home() or not in_builder():
        return
    dev.zoom_out(2)
    dev.swipe(1400, 400, 600, 650, 600, wait=1.5)       # el muelle (barco + carro) queda a la vista
    shot = dev.shot()
    queries = ['la pequeña carreta de madera (carro de elixir) que está en la hierba, abajo a la izquierda del '
               'muelle de madera del barco',
               'la burbuja blanca con una gota de elixir morada que está en la orilla, junto al muelle de madera del '
               'barco (NO las de dentro de la aldea)']
    img = None
    for q in queries:
        pos = eyes.find(shot, q)
        if not pos or not safe_map_point(*pos, bars_bottom=260) or pos[1] > 700:
            continue
        tap(*pos, "abrir carro de elixir", 2)
        img = dev.shot()
        if cart_window_open(img):
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


def bb_deploy(x, label):
    """Selecciona la carta y la suelta por el borde derecho hasta que la carta suba (desplegada)."""
    tap(x, 935, f"seleccionar {label}", 0.3)          # 935: lejos del botón de cambiar tropa (abajo)
    for i in range(6):
        px, py = 1400 + random.uniform(-25, 25), 450 + 45 * i
        tap(px, py, f"desplegar {label}", 0.5)
        img = dev.shot()
        if label == "máquina" or bb_state(img, x) != "pendiente":
            return


def bb_battle():
    """Juega una batalla de constructor (2 fases) hasta la pantalla de resultado."""
    t0 = time.time()
    machine_done = set()
    while time.time() - t0 < 300:
        check_stop()
        kind, img = screen()
        if kind == "result":
            return
        if kind != "battle":
            time.sleep(3)
            continue
        machine, troops = bb_cards(img)
        # 1) desplegar lo que falte (en la 2ª fase la barra cambia: se vuelve a mirar cada vuelta)
        if machine is not None and machine not in machine_done:
            bb_deploy(machine, "máquina")
            machine_done.add(machine)
        for x in troops:
            if bb_state(dev.shot(), x) == "pendiente":
                bb_deploy(x, f"tropa {troops.index(x) + 1}")
        # 2) habilidades: tropas desplegadas con la cabecera morada y la máquina con sus barras moradas
        img = dev.shot()
        for x in troops:
            if bb_state(img, x) == "lista":
                tap(x, 960, f"habilidad tropa {troops.index(x) + 1}", 0.4)
        if machine is not None and any(_purple(color(img, machine + dx, 835, 2)) for dx in (-3, 37)):
            tap(machine, 960, "habilidad de la máquina", 0.4)
        time.sleep(2.5)
    log("warn", "La batalla de constructor no terminó a tiempo.")


def bb_storages(acc):
    """(lleno?, recursos) de la aldea nocturna según capacidad y % objetivo de la cuenta."""
    a = CFG["accounts"][acc]
    cap = a.get("builder_capacity")
    res = eyes.my_resources(dev.shot())
    note_resources(acc, res, "builder")
    if not cap:
        return False, res
    r = a.get("builder_full_ratio", a.get("full_ratio", CFG["full_ratio"]))
    full = all((res.get(k) or 0) >= cap[k] * r for k in ("gold", "elixir"))
    log("think", f"{acc} (aldea nocturna): oro {res.get('gold')}/{cap['gold']}, elixir {res.get('elixir')}/{cap['elixir']}"
                 f" → {'LLENO' if full else 'falta'} (objetivo {int(r * 100)} %)")
    return full, res


def builder_base(acc, attacks):
    """Aldea nocturna: batallas de constructor hasta llenar sus almacenes al % objetivo
    (como mucho `attacks` batallas por vuelta)."""
    if not go_home():
        return
    if not in_builder() and not travel_boat(True):
        return
    collect_cart()
    result = None
    for n in range(attacks):
        check_stop()
        if not go_home():                          # cierra avisos (bonus estelar, etc.) antes de cada batalla
            break
        full, before = bb_storages(acc)
        if full:
            log("done", f"Almacenes de la aldea nocturna de {acc} llenos.")
            result = "full"
            break
        tap(125, 960, "Batalla (aldea nocturna)", 3)
        if not is_green(color(dev.shot(), 1270, 700, 3)):   # botón verde "Buscar" del menú de la nocturna
            log("warn", "El menú de batalla de la aldea nocturna no se ha abierto.")
            go_home()
            break
        tap(1425, 708, "Buscar batalla de constructor", 10)
        dev.zoom_out(1)
        bb_battle()
        tap(960, 925, "volver", 6)
        collect_cart()
        if go_home():
            after = eyes.my_resources(dev.shot())
            gained = {k: max(0, (after.get(k) or 0) - (before.get(k) or 0)) for k in ("gold", "elixir")}
            note_resources(acc, after, "builder")
            loot_log(acc, "aldea nocturna", None, None, {**gained, "dark": 0})
            log("done", f"Batalla nocturna terminada: +{gained['gold']} oro, +{gained['elixir']} elixir.")
            if gained["gold"] + gained["elixir"] < 2000 and n > 0:
                log("done", "La aldea nocturna ya no suma (bonus agotado o almacenes llenos). Paso a lo siguiente.")
                break
    go_home()
    travel_boat(False)
    go_home()
    return result


# ---------------- mejoras recomendadas (sólo cuentas con "auto_build") ----------------
BUILD_BTN = (1745, 815)            # icono de constructores (abajo a la derecha)
CONFIRM_BTN = (1345, 940)          # «Confirmar» con recurso (el gris de la izquierda es el martillo: nunca)


def builder_panel_open(img=None):
    img = img or dev.shot()
    x = color(img, 1905, 40, 2)                       # borde rojo del botón X (el centro es la cruz blanca)
    tab = color(img, 1467, 1010, 4)                   # pestaña de constructores (abajo del panel)
    return x[0] > 170 and x[1] < 90 and x[2] < 90 and tab[0] > 150 and 110 < tab[1] < 180


def panel_rows(img):
    """Inicio (y) de las filas marrones de «Mejoras recomendadas»: el primer bloque de filas seguidas
    tras las barras verdes de lo que ya se está mejorando."""
    starts, prev = [], False
    for y in range(70, 965, 2):
        r, g, b = img.getpixel((1418, y))
        brown = r > 110 and g < r
        if brown and not prev:
            starts.append(y)
        prev = brown
    block = starts[:1]
    for y in starts[1:]:
        if y - block[-1] > 100:                       # hueco grande = título «Otras mejoras»
            break
        block.append(y)
    return block


def free_builders(img):
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
    skip = set()                              # filas que no abren ventana de mejora (héroes: sólo centran la cámara)
    for _ in range(7):                        # varias filas (algunas se saltan)
        img = dev.shot()
        free, total = free_builders(img)
        if not free:
            log("think", f"{acc}: constructores ocupados ({free}/{total}).")
            break
        rows = panel_rows(img)
        crop = img.crop((1405, 60, 1920, 960))
        d = eyes.ask(crop, 'Panel "Estructuras y héroes" de Clash of Clans. Lista SOLO las filas de la sección '
                           '"Mejoras recomendadas" (entre ese título y "Otras mejoras"), de arriba abajo, con su '
                           'nombre, coste y recurso del coste según el icono (oro = moneda amarilla, elixir = gota '
                           'rosa, oscuro = gota negra, gema = gema verde). '
                           'Responde {"rows":[{"name":str,"cost":int,"res":"oro|elixir|oscuro|gema"}]}')
        items = d.get("rows") or []
        cand = []
        for y0, it in zip(rows, items):
            if str(it.get("res", "")).lower().startswith("gem"):
                continue
            icon = color(img, 1893, y0 + 38, 3)
            if icon[1] > 150 and icon[0] < 140 and icon[2] < 140:      # icono de gema, aunque el LLM diga otra cosa
                continue
            txt = img.crop((1760, y0 + 22, 1880, y0 + 56)).getdata()
            if sum(1 for r, g, b in txt if r > 200 and g < 90 and b < 90) > 15:   # cifra en rojo: no llega
                continue
            cand.append((y0, it))
        if not cand:
            log("think", f"{acc}: nada recomendado que se pueda pagar ahora.")
            break
        cand = [c for c in cand if str(c[1].get("name")) not in skip]
        if not cand:
            log("think", f"{acc}: lo recomendado que queda no se puede mejorar desde aquí.")
            break
        y0, it = cand[0]
        tap(1620, y0 + 38, f"elegir mejora recomendada: {it.get('name')} ({it.get('cost')} {it.get('res')})", 2)
        win = dev.shot()
        if not upgrade_window(win):           # la ventana tarda en abrirse: un segundo más
            time.sleep(1.2)
            win = dev.shot()
        if not upgrade_window(win):           # no salió la ventana (p. ej. un héroe): se salta y sigue con otra
            win.save(HERE / "no_ventana_mejora.png")
            skip.add(str(it.get("name")))
            log("think", f"«{it.get('name')}» no abre ventana de mejora desde el panel: pruebo la siguiente.")
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
    if not switch_to(acc):
        return
    clan_duties()
    if task == "builder_base":
        return builder_base(acc, step.get("attacks", 10))
    if task == "build":
        build_recommended(acc)
        return
    limit = step.get("attacks", CFG["max_attacks_per_account"])
    for n in range(limit):
        check_stop()
        if blocked_until.get(acc, 0) > time.time():
            return
        reload_config()
        if task in ("fill_storages", "farm") and storages_full(acc):
            log("done", f"Almacenes de {acc} llenos: no ataco.")
            return "full"
        if not attack(acc) and not attack(acc):   # un fallo suelto (nubes, popup) se reintenta una vez
            return
        clan_duties()
        if sum(LAST_GAIN.get(k) or 0 for k in ("gold", "elixir", "dark")) < 3000:
            log("done", f"{acc}: el último ataque no ha sumado nada (almacenes llenos). Paso a lo siguiente.")
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


def main():
    dev.connect()
    log("think", "Asistente en marcha: rutina " + " → ".join(f"{s['account']} ({s['task']})" for s in CFG["routine"]) + ".")
    while True:
        reload_config()
        results = {}
        set_state(phase="run", current=None, results={}, routine=CFG["routine"])
        i = 0
        while i < len(CFG["routine"]):           # se relee en cada paso: los cambios del visor valen ya
            step = CFG["routine"][i]
            check_stop()
            if step.get("enabled", True) is False:
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
        if real and all(r in ("full", "skip") for r in real):
            rest = CFG.get("rest_minutes_when_full", 30)
            log("think", "Todas las cuentas llenas (o en uso por el dueño): descanso largo.")
        log("think", f"Rutina completa. Descanso {rest} min y vuelvo a empezar.")
        set_state(phase="rest", current=None, results=results, rest_until=time.time() + rest * 60)
        owner_pause()
        home = CFG.get("home_account")
        if home and blocked_until.get(home, 0) > time.time():
            home = None                      # su cuenta la usa el dueño: no se vuelve a ella
        every = CFG.get("donation_check_minutes", 4) * 6
        if home:
            try:
                switch_to(home)
            except Exception as e:
                log("warn", f"No he podido volver a {home}: {e}")
        for k in range(rest * 6):
            check_stop()
            if (HERE / "SKIP_REST").exists():  # botón «empezar ya» del visor
                (HERE / "SKIP_REST").unlink(missing_ok=True)
                log("think", "Descanso cancelado desde el visor: empiezo la rutina.")
                break
            if home and k and k % every == 0:     # la cuenta donante atiende las peticiones mientras descansa
                try:
                    if which_account() == home:
                        clan_duties()
                    else:
                        switch_to(home)
                except Exception as e:
                    log("warn", f"Revisión de donaciones falló: {e}")
            elif k and k % 30 == 0:                # latido cada 5 min para que el vigilante no lo crea colgado
                log("think", f"Descansando… quedan {rest - k // 6} min.")
            time.sleep(10)


if __name__ == "__main__":
    main()

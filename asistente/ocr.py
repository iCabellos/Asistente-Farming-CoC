"""Lectura de cifras con la fuente del juego por plantillas: sin modelo, en la CPU, en milisegundos.

El texto del juego es de relleno liso (blanco, crema, rojo o verde) con un borde oscuro: cada carácter es una
mancha de ese color separada de las demás. Cada mancha se compara (normalizada a 16x24) con plantillas sacadas
de capturas reales (tpl/glifos.npz). Si algo no encaja (una mancha que no se parece claramente a ninguna
plantilla, grupos de cifras que no van de tres en tres, un renglón de más…) se devuelve None y quien llama
pregunta al modelo como siempre: el OCR nunca adivina."""
from pathlib import Path

import cv2
import numpy as np

NW, NH = 16, 24
TPL_FILE = Path(__file__).parent / "tpl" / "glifos.npz"
MAX_D, MIN_MARGIN = 0.11, 0.05          # distancia máxima a la plantilla y ventaja mínima sobre el 2.º carácter


def _mask(a, color):
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    if color == "white":                        # blanco puro (precios: el botón beis no entra)
        return (r >= 200) & (g >= 200) & (b >= 200)
    if color == "light":                        # blanco o crema (botín grande, títulos amarillo claro)
        return (r >= 205) & (g >= 205) & (b >= 140)
    if color == "red":                          # precio que no llega (240, 128, 112)
        return (r >= 215) & (g >= 80) & (g <= 165) & (b >= 70) & (b <= 155)
    if color == "green":                        # precio con descuento (112, 240, 0)
        return (g >= 200) & (r <= 175) & (b <= 100)
    if color == "pct":                          # % de daño del resultado (127, 187, 83) sobre la estrella gris
        return (g >= 160) & (g - r >= 40) & (g - b >= 60) & (r >= 90)
    raise ValueError(color)


def glyphs(crop, color="white", hmin=12, hmax=70, ring_dark=150, ring_min=0.55, rejected=None):
    """Manchas del color del texto rodeadas de borde oscuro: [{x, y, w, h, m}] de izquierda a derecha.
    `rejected` (lista): ahí se dejan las manchas descartadas de tamaño parecido (para ver si falta un carácter)."""
    a = np.asarray(crop.convert("RGB")).astype(np.int16)
    lum = (a[..., 0] * 299 + a[..., 1] * 587 + a[..., 2] * 114) // 1000
    m = _mask(a, color).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    H, W = m.shape
    out = []
    for i in range(1, n):
        x, y, w, h, area = (int(v) for v in st[i])
        if not (hmin <= h <= hmax) or w > 1.4 * h or area < 12:
            if rejected is not None and area >= 15 and h >= 0.5 * hmin:
                rejected.append({"x": x, "y": y, "w": w, "h": h})
            continue
        x0, y0, x1, y1 = max(0, x - 3), max(0, y - 3), min(W, x + w + 3), min(H, y + h + 3)
        c = (lab[y0:y1, x0:x1] == i).astype(np.uint8)
        ring = (cv2.dilate(c, np.ones((5, 5), np.uint8)) > 0) & (c == 0)
        if not ring.any() or (lum[y0:y1, x0:x1][ring] < ring_dark).mean() < ring_min:
            if rejected is not None:
                rejected.append({"x": x, "y": y, "w": w, "h": h})
            continue                             # sin borde oscuro alrededor: no es texto del juego
        out.append({"x": x, "y": y, "w": w, "h": h, "m": lab[y:y + h, x:x + w] == i})
    return sorted(out, key=lambda g: g["x"])


def lines(gs):
    """Agrupa las manchas en renglones (centro vertical parecido), de arriba abajo."""
    rows = []
    for g in sorted(gs, key=lambda g: -g["h"]):            # las altas (cifras) fijan el renglón
        cy = g["y"] + g["h"] / 2
        for r in rows:
            if abs(cy - r["cy"]) <= 0.45 * r["h"] and 0.45 * r["h"] <= g["h"] <= 1.5 * r["h"]:
                r["g"].append(g)
                break
        else:
            rows.append({"cy": cy, "h": g["h"], "g": [g]})
    for r in rows:
        r["g"].sort(key=lambda g: g["x"])
    return sorted(rows, key=lambda r: r["cy"])


def words(row, gap=1.0):
    """Trozos de un renglón separados por un hueco mayor que `gap` alturas (texto suelto de alrededor)."""
    gs, out = row["g"], []
    for g in gs:
        if out and g["x"] - (out[-1][-1]["x"] + out[-1][-1]["w"]) <= gap * row["h"]:
            out[-1].append(g)
        else:
            out.append([g])
    return out


def feature(g):
    f = cv2.resize(g["m"].astype(np.float32), (NW, NH), interpolation=cv2.INTER_AREA)
    return f, g["w"] / g["h"]


_TPL = {}


def templates():
    if not _TPL:
        d = np.load(TPL_FILE)
        _TPL.update(f=d["f"].astype(np.float32), asp=d["asp"].astype(np.float32), ch=[str(c) for c in d["ch"]])
    return _TPL


def classify(g, allowed=None, tpl=None):
    """(carácter, distancia, margen sobre el siguiente carácter distinto)."""
    t = tpl or templates()
    f, asp = feature(g)
    d = np.abs(t["f"] - f).mean(axis=(1, 2)) + 0.25 * np.abs(np.log(t["asp"] / asp))
    best = {}
    for ch, v in zip(t["ch"], d):
        if allowed is None or ch in allowed:
            if v < best.get(ch, 9.0):
                best[ch] = float(v)
    if not best:
        return None, 9.0, 0.0
    order = sorted(best.items(), key=lambda kv: kv[1])
    d2 = order[1][1] if len(order) > 1 else 9.0
    return order[0][0], order[0][1], d2 - order[0][1]


def read_word(gs, allowed="0123456789", space=0.3, tpl=None):
    """Texto de unas manchas seguidas, con espacio donde el hueco pasa de `space` alturas; None si alguna mancha
    no se parece claramente a un carácter permitido."""
    if not gs:
        return None
    hmed = float(np.median([g["h"] for g in gs]))
    txt = ""
    for i, g in enumerate(gs):
        c, d, mg = classify(g, allowed, tpl)
        if c is None or d > MAX_D or mg < MIN_MARGIN:
            return None
        if i and g["x"] - (gs[i - 1]["x"] + gs[i - 1]["w"]) > space * hmed:
            txt += " "
        txt += c
    return txt


def grouped_int(txt):
    """«16 500 000» → 16500000, sólo si los grupos son de tres cifras (salvo el primero, de 1 a 3)."""
    if not txt:
        return None
    parts = txt.split(" ")
    if not all(p.isdigit() for p in parts) or not 1 <= len(parts[0]) <= 3 or any(len(p) != 3 for p in parts[1:]):
        return None
    if (len(parts[0]) > 1 or len(parts) > 1) and parts[0][0] == "0":
        return None                              # «0 500 000» o «07»: un cero delante no existe en el juego
    return int("".join(parts))


def crowded(w, rejected, row=None):
    """¿Puede faltar un trozo del número? Sí si junto a él (a menos de 1,5 alturas por cualquier lado, o entre sus
    cifras) hay una mancha clara descartada, u otro trozo de texto del mismo renglón a menos de 3 alturas: una
    cifra tapada o deformada (un brillo, una animación) parte el número y se leería sólo un pedazo."""
    x0, x1 = w[0]["x"], w[-1]["x"] + w[-1]["w"]
    y0, y1 = min(g["y"] for g in w), max(g["y"] + g["h"] for g in w)
    h = y1 - y0
    for r in rejected:
        if r["y"] + r["h"] <= y0 + 0.2 * h or r["y"] >= y1 - 0.2 * h:
            continue                             # otro renglón
        if r["w"] > 4 * h or not 0.4 * h <= r["h"] <= 1.6 * h:
            continue                             # fondo (franja del botón, barra…), no una cifra perdida
        if x0 - 1.5 * h <= r["x"] + r["w"] and r["x"] <= x1 + 1.5 * h:
            return True
    if row is not None:
        for o in words(row):
            if o[0] is w[0]:
                continue
            ox0, ox1 = o[0]["x"], o[-1]["x"] + o[-1]["w"]
            if ox1 >= x0 - 3 * h and ox0 <= x1 + 3 * h:
                return True
    return False


def number_in(img, box, color="white", hr=(12, 40), side="right", tpl=None, end_gap=None):
    """El número (con separadores de miles) escrito en `box`: el único renglón con cifras; dentro de él, el trozo
    más a la derecha (o izquierda). None si no hay exactamente uno o no se lee con claridad. `end_gap`: el número
    va pegado a un icono a su derecha; si acaba a más de `end_gap` px del borde derecho de la caja, le falta el
    final (tapado) y no se da por bueno."""
    rej = []
    rows = [r for r in lines(glyphs(img.crop(box), color, *hr, rejected=rej)) if len(r["g"]) >= 1]
    found = []
    for r in rows:
        ws = words(r)
        w = ws[-1] if side == "right" else ws[0]
        if crowded(w, rej, r):
            return None
        v = grouped_int(read_word(w, tpl=tpl))
        if v is not None and end_gap is not None and (box[2] - box[0]) - (w[-1]["x"] + w[-1]["w"]) > end_gap:
            return None
        if v is not None:
            found.append(v)
        elif len(w) >= 2:
            return None                          # algo con pinta de número que no se lee: mejor el modelo
    return found[0] if len(found) == 1 else None


# ---------------- lecturas concretas (mismas cajas que las preguntas al modelo) ----------------
RES_BOX = {"gold": (1480, 35, 1835, 80), "elixir": (1480, 108, 1835, 153), "dark": (1480, 182, 1835, 228)}


def my_resources(img, tpl=None):
    """Barras de arriba a la derecha (aldea o búsqueda). None si alguna no se lee con claridad."""
    out = {}
    for k, b in RES_BOX.items():
        v = number_in(img, b, "light", (17, 30), "right", tpl, end_gap=25)   # acaba en x≈1822, junto al icono
        if v is None:
            return None
        out[k] = v
    return out


def _icon(img, cy):
    """Icono a la izquierda de un renglón del botín: moneda, gota rosa o gota negra."""
    a = np.asarray(img.crop((52, int(cy) - 8, 84, int(cy) + 8)).convert("RGB")).reshape(-1, 3).astype(int)
    r, g, b = a[:, 0], a[:, 1], a[:, 2]
    gold = ((r > 200) & (g > 150) & (b < 90)).mean()
    pink = ((r > 170) & (b > 170) & (g < 120)).mean()
    dark = ((np.maximum(np.maximum(r, g), b) < 90)).mean()
    best = max((gold, "gold"), (pink, "elixir"), (dark, "dark"))
    return best[1] if best[0] > 0.35 else None


def loot(img, tpl=None):
    """Botín del rival (arriba a la izquierda en la búsqueda): {gold, elixir, dark}; dark 0 si no sale."""
    box = (90, 125, 345, 300)
    rej = []
    rows = [r for r in lines(glyphs(img.crop(box), "light", 17, 30, rejected=rej)) if len(r["g"]) >= 1]
    out, cy = {}, {}
    for r in rows:
        w = words(r)[0]
        if w[0]["x"] > 40:                       # el número empieza justo a la derecha del icono
            continue
        if not 8 <= w[0]["x"] <= 16:             # siempre empieza en x=10-13: si no, falta la 1.ª cifra (QA)
            return None
        if crowded(w, rej, r):
            return None
        v = grouped_int(read_word(w, tpl=tpl))
        kind = _icon(img, box[1] + r["cy"])
        if v is None or kind is None or kind in out:
            return None
        out[kind], cy[kind] = v, box[1] + r["cy"]
    if "gold" not in out or "elixir" not in out:
        return None
    if "dark" not in out:
        # sin cifra de oscuro: sólo vale si en su renglón (debajo del elixir) no hay nada claro escrito
        y = cy["elixir"] + (cy["elixir"] - cy["gold"])
        a = np.asarray(img.crop((90, int(y) - 14, 345, int(y) + 14)).convert("RGB")).astype(np.int16)
        if _mask(a, "light").sum() > 30:
            return None
        out["dark"] = None
    return out


def card_count(img, x_left, tpl=None):
    """«xN» de arriba a la derecha de una carta de la barra de batalla; None si no se ve claro."""
    rows = [r for r in lines(glyphs(img.crop((x_left + 30, 886, x_left + 138, 935)), "light", 14, 30))]
    if len(rows) != 1:
        return None
    t = read_word(words(rows[0])[-1], "x0123456789", tpl=tpl)
    if not t or t[0] != "x" or not t[1:].isdigit() or " " in t:
        return None
    n = int(t[1:])
    return n if 0 < n < 100 else None


def builders(img, tpl=None):
    """«a/b» de constructores libres / total, abajo en el panel."""
    rows = lines(glyphs(img.crop((1410, 1000, 1530, 1070)), "white", 11, 22))
    if len(rows) != 1:
        return None
    t = read_word(rows[0]["g"], "0123456789/", space=9, tpl=tpl)
    if not t or t.count("/") != 1:
        return None
    a, b = t.split("/")
    if not (a.isdigit() and b.isdigit()) or not 0 <= int(a) <= int(b) <= 12:
        return None
    return int(a), int(b)


def price(img, box, tpl=None, hr=(12, 24), end_gap=None):
    """Precio de un botón de pago (cifra blanca; roja si no llega; verde si hay descuento)."""
    vals = {v for c in ("white", "red", "green") for v in [number_in(img, box, c, hr, "right", tpl, end_gap)]
            if v is not None}
    return vals.pop() if len(vals) == 1 else None


def red_text(img, box):
    """¿La cifra del recuadro está en ROJO (el juego avisa así de que no llega)? Por píxeles, independiente de
    la lectura de la cifra (QA): un precio rojo nunca se paga."""
    a = np.asarray(img.crop(box).convert("RGB")).astype(np.int16)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    red = int(((r > 190) & (g < 90) & (b < 90)).sum())
    white = int((a.min(axis=2) > 220).sum())
    return red > 40 and red > white


def card_has_text(img, x_left):
    """¿Hay algo escrito arriba a la derecha de la carta? (Las de héroes y hechizos sueltos no llevan «xN».)"""
    return bool(lines(glyphs(img.crop((x_left + 30, 886, x_left + 138, 935)), "light", 14, 30)))


def wall_row(img, ty, tpl=None):
    """Fila «Muro x N» del panel: {count, price}. None si no se lee claro."""
    crop = img.crop((1480, ty - 8, 1915, ty + 60))
    rows = [r for r in lines(glyphs(crop, "white", 11, 24)) if len(r["g"]) >= 3]
    if len(rows) != 2:
        return None
    name, cost = rows
    ws = words(name, gap=0.45)                  # «Muro» «x» «293»
    if len(ws) < 3:
        return None
    t = read_word(ws[-2] + ws[-1], "x0123456789", space=0.45, tpl=tpl)   # «x 293»
    if not t or not t.startswith("x"):
        return None
    t = t[1:].strip()
    p = grouped_int(read_word(words(cost)[-1], tpl=tpl))
    if not t.isdigit() or p is None:
        return None
    return {"count": int(t), "price": p}


TITLE_BOX = {"dos filas": (300, 580, 1400, 665), "una fila": (300, 675, 1400, 760)}
TITLE_CHARS = "Muro(Nivel)x0123456789"


def _title_run(img, box):
    """Manchas del título grande («Muro (Nivel 17) x2»): el trozo más largo del renglón con más manchas."""
    rows = lines(glyphs(img.crop(box), "light", 18, 45))
    if not rows:
        return None
    row = max(rows, key=lambda r: len(r["g"]))
    return max(words(row, gap=0.8), key=len)


def wall_title(img, box, tpl=None):
    """(«Muro», nivel, cuántos) si el título es EXACTAMENTE «Muro (Nivel N)» o «Muro (Nivel N) xK»; None si no
    (otro edificio o lectura dudosa: entonces decide el modelo, como antes).
    «Muro(Nivel» es fijo: cada mancha tiene que parecerse a SU letra más que a cualquier otra (la i, la l y el 1
    se parecen entre sí, así que ahí no se exige margen); las cifras del nivel y la cuenta, con margen."""
    w = _title_run(img, box)
    word = "Muro(Nivel"
    if not w or len(w) < len(word) + 2:
        return None
    t = tpl or templates()

    def is_char(g, ch):
        c, d, _ = classify(g, TITLE_CHARS, t)
        return d <= MAX_D and (c == ch or classify(g, ch, t)[1] <= d + 0.01)

    # manchas que no se parecen a ningún carácter (un trozo blanco del decorado pegado al texto): fuera, pero
    # sólo antes del «(» del nivel; en las cifras no se quita nada
    junk = [classify(g, TITLE_CHARS, t)[1] > 0.2 for g in w]
    starts = []
    for i in range(len(w)):
        if junk[i] or not is_char(w[i], word[0]):
            continue
        k, j = 1, i + 1
        while k < len(word) and j < len(w):
            if junk[j]:
                j += 1
                continue
            if not is_char(w[j], word[k]):
                break
            k, j = k + 1, j + 1
        if k == len(word):
            starts.append((i, j))
    if len(starts) != 1:
        return None
    i, end = starts[0]
    prev = [g for g, bad in zip(w[:i], junk[:i]) if not bad]
    if prev and w[i]["x"] - (prev[-1]["x"] + prev[-1]["w"]) > 0.3 * w[i]["h"]:
        return None                              # algo escrito delante de «Muro»: no es un muro
    rest = w[end:]
    s = ""
    for g in rest:
        c, d, mg = classify(g, "0123456789)x", t)
        if d > MAX_D or mg < MIN_MARGIN:
            return None
        s += c
    import re
    m = re.fullmatch(r"(\d{1,2})\)(?:x(\d{1,3}))?", s)
    if not m:
        return None
    return "Muro", int(m[1]), int(m[2]) if m[2] else 1


def _icon_right(img, x, cy):
    """Icono a la derecha de una cifra (pantalla de resultado): moneda, gota rosa o gota negra."""
    a = np.asarray(img.crop((int(x) + 12, int(cy) - 10, int(x) + 48, int(cy) + 10)).convert("RGB")).reshape(-1, 3).astype(int)
    r, g, b = a[:, 0], a[:, 1], a[:, 2]
    gold = ((r > 200) & (g > 150) & (b < 90)).mean()
    pink = ((r > 170) & (b > 170) & (g < 120)).mean()
    dark = ((np.maximum(np.maximum(r, g), b) < 90)).mean()
    best = max((gold, "gold"), (pink, "elixir"), (dark, "dark"))
    return best[1] if best[0] > 0.35 else None


def battle_result(img, tpl=None):
    """Pantalla de fin de batalla: {pct, stars: None, gold, elixir, dark} (las estrellas las cuenta quien llama
    por píxeles). None si algo no se lee claro."""
    box = (700, 450, 1040, 720)
    out, rej = {}, []
    for r in lines(glyphs(img.crop(box), "light", 22, 45, rejected=rej)):
        w = words(r)[-1]
        end = box[0] + w[-1]["x"] + w[-1]["w"]
        if end < 950:                            # las cifras acaban junto al icono (x≈1000)
            continue
        if crowded(w, rej, r):
            return None
        v = grouped_int(read_word(w, tpl=tpl))
        kind = _icon_right(img, end, box[1] + r["cy"])
        if v is None or kind is None or kind in out:
            return None
        out[kind] = v
    if "gold" not in out or "elixir" not in out:
        return None
    out.setdefault("dark", 0)
    rows = lines(glyphs(img.crop((860, 145, 1060, 205)), "pct", 18, 40))
    if len(rows) != 1:
        return None
    t = read_word(rows[0]["g"], "0123456789%", tpl=tpl)
    if not t or not t.endswith("%") or not t[:-1].strip().isdigit() or not 0 <= int(t[:-1]) <= 100:
        return None
    out.update(pct=int(t[:-1]), stars=None)
    return out


# ---------------- burbujas de recursos (sin modelo) ----------------
def bubbles(img, debug=False):
    """Burbujas de recursos listas para recoger, por píxeles: el icono (moneda, gota rosa o gota negra) rodeado
    del fondo de la burbuja (beis claro; naranja si el colector está lleno). [(x, y)] del centro del icono."""
    a = np.asarray(img.convert("RGB")).astype(np.int16)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    beige = (g >= 170) & (g <= 235) & (g - r >= 0) & (g - r <= 20) & (g - b >= 20) & (g - b <= 90) & (b >= 95)
    orange = (r >= 190) & (g >= 30) & (g <= 120) & (b <= 60) & (r - g >= 90)
    bg = beige | orange
    icons = {"oro": (r > 200) & (g > 150) & (b < 110) & ~beige,
             "elixir": (r > 150) & (b > 130) & (g < 120) & (b - g > 40),
             "oscuro": (np.maximum(np.maximum(r, g), b) < 130) & (b - g >= 6) & (r >= g)}
    anyicon = icons["oro"] | icons["elixir"] | icons["oscuro"]
    out = []
    for kind, m in icons.items():
        m = m.astype(np.uint8)
        m[860:, :] = 0
        if kind == "oscuro":                    # la gota negra tiene motas negras puras: se cierran
            m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        n, lab, st, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
        for i in range(1, n):
            x, y, w, h, area = (int(v) for v in st[i])
            if not (16 <= w <= 48 and 18 <= h <= 50 and 0.55 <= w / h <= 1.4 and area >= 0.45 * w * h):
                continue
            x0, y0, x1, y1 = max(0, x - 8), max(0, y - 8), min(1920, x + w + 8), min(1080, y + h + 8)
            ring = np.ones((y1 - y0, x1 - x0), bool)
            ring[y - y0:y - y0 + h, x - x0:x - x0 + w] = False
            ring &= ~anyicon[y0:y1, x0:x1]       # el icono de una burbuja vecina no cuenta como «sin fondo» (QA)
            if not ring.any():
                continue
            frac = bg[y0:y1, x0:x1][ring].mean()
            if frac < 0.45:
                continue
            out.append((x + w // 2, y + h // 2, kind, round(float(frac), 2)) if debug else (x + w / 2, y + h / 2))
    return out

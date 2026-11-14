"""Visión por colores (sin LLM) para planificar el ataque: defensas aéreas y bordes de la aldea."""
import cv2
import numpy as np


def _bgr(img):
    """PIL RGB → array BGR de OpenCV."""
    return cv2.cvtColor(np.asarray(img.convert("RGB")), cv2.COLOR_RGB2BGR)


def _hud_mask(shape):
    """Zonas de la pantalla que no son mapa (marcadores, botones, barra de cartas)."""
    m = np.ones(shape[:2], np.uint8)
    m[860:, :] = 0
    m[:300, :330] = 0          # botín
    m[:120, 1450:] = 0         # recursos propios
    m[:110, 780:1140] = 0      # cuenta atrás
    m[690:, 1580:] = 0         # Siguiente
    m[750:, :600] = 0          # Terminar / Potenciar
    return m


def air_defenses(img, debug=False):
    """Defensas aéreas: cohetes amarillo intenso con franjas negras. Devuelve [(x, y)] del centro del edificio."""
    a = _bgr(img)
    h = cv2.cvtColor(a, cv2.COLOR_BGR2HSV)
    hud = _hud_mask(a.shape)
    yel = (cv2.inRange(h, (20, 190, 215), (32, 255, 255)) > 0) & (hud > 0)
    dark = h[:, :, 2] < 55
    near = cv2.dilate(yel.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    ky, kx = 62, 70
    Y = cv2.boxFilter(yel.astype(np.float32), -1, (kx, ky), normalize=False)
    D = cv2.boxFilter((dark & near).astype(np.float32), -1, (kx, ky), normalize=False)
    ok = (Y >= 130) & (Y <= 270) & (D >= 72) & (D <= 165) & (D >= 0.33 * Y)
    score = np.where(ok, D + 0.2 * Y, 0).astype(np.float32)
    out = []
    while True:
        _, mx, _, (x, y) = cv2.minMaxLoc(score)
        if mx <= 0:
            break
        out.append((int(x), int(y) + 12, float(mx)))
        cv2.circle(score, (x, y), 75, 0, -1)       # una torre no da dos positivos
    return out if debug else [(x, y) for x, y, _ in out]


def border_mask(img):
    """Línea roja punteada del borde de despliegue (zona prohibida), limpia de ruido."""
    a = _bgr(img).astype(np.int16)
    b, g, r = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    m = ((r > 180) & (g < 110) & (b < 60) & (r - g > 90)).astype(np.uint8)
    m &= _hud_mask(a.shape)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(m)
    keep = np.zeros_like(m)
    for i in range(1, n):
        x, y, w, h, area = st[i]
        if max(w, h) >= 120:          # tramos largos del borde; descarta hogueras, nombres, etc.
            keep[lab == i] = 1
    return keep


def corners(img):
    """Esquinas de la aldea según el borde rojo: {'L'|'R'|'T'|'B': (x, y, centrada)}.
    'centrada' = la esquina está a media altura (L/R) o a media anchura (T/B) de la aldea, así una flecha
    lanzada desde ahí en horizontal/vertical cruza la aldea entera."""
    m = border_mask(img)
    ys, xs = np.nonzero(m)
    if len(xs) < 300:
        return {}
    top, asistente, lft, rgt = ys.min(), ys.max(), xs.min(), xs.max()
    midy, midx = (top + asistente) / 2, (lft + rgt) / 2
    hy, hx = max(1, asistente - top), max(1, rgt - lft)
    out = {}
    sel = xs <= lft + 4
    out["L"] = (int(lft), int(np.median(ys[sel])))
    sel = xs >= rgt - 4
    out["R"] = (int(rgt), int(np.median(ys[sel])))
    sel = ys <= top + 4
    out["T"] = (int(np.median(xs[sel])), int(top))
    sel = ys >= asistente - 4
    out["B"] = (int(np.median(xs[sel])), int(asistente))
    res = {}
    for k, (x, y) in out.items():
        if k in "LR":
            centred = abs(y - midy) < 0.15 * hy and lft > 20 and rgt < 1900
        else:
            centred = abs(x - midx) < 0.15 * hx and top > 115 and asistente < 850
        res[k] = (x, y, bool(centred))
    return res


# ---------------- contorno de la aldea ----------------
def village_mask(img):
    """Suelo de la aldea (amarillento: verde ≤ rojo + 4) frente a la hierba de fuera (verde), relleno:
    1 = dentro de la zona prohibida de despliegue."""
    a = _bgr(img).astype(np.int16)
    g, r = a[:, :, 1], a[:, :, 2]
    m = (g - r <= 4).astype(np.uint8)
    m[865:, :] = 0
    m[:300, :330] = 0          # botín
    m[:240, 1480:] = 0         # recursos propios
    m[690:, 1580:] = 0         # Siguiente / daño
    m[750:, :600] = 0          # Terminar / Potenciar
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((21, 21), np.uint8))
    n, lab, st, cen = cv2.connectedComponentsWithStats(m)
    if n < 2:
        return None
    # la componente grande más cercana al centro de la pantalla
    cand = [i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] >= 150_000]
    if not cand:
        return None
    i = min(cand, key=lambda i: (cen[i][0] - 960) ** 2 + (cen[i][1] - 450) ** 2)
    comp = (lab == i).astype(np.uint8)
    cnts, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    filled = np.zeros_like(comp)
    cv2.drawContours(filled, cnts, -1, 1, -1)
    filled = cv2.morphologyEx(filled, cv2.MORPH_OPEN, np.ones((25, 25), np.uint8))   # quita salientes finos
    return filled


def border_hull_mask(img):
    """Plan B (escenarios sin hierba): la línea roja punteada del borde. Se unen los puntos a lo largo
    de las dos diagonales isométricas, se quedan los tramos largos y se rellena su envolvente."""
    a = _bgr(img).astype(np.int16)
    b, g, r = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    m = ((r > 140) & (r - g > 65) & (r - b > 75)).astype(np.uint8)
    m &= _hud_mask(a.shape)
    m[:300, :330] = 0
    m[:240, 1480:] = 0
    # fuera manchas gordas (hogueras de campamento, banderas): la línea es fina
    n, lab, st, _ = cv2.connectedComponentsWithStats(m)
    for i in range(1, n):
        if st[i, cv2.CC_STAT_AREA] > 80:
            m[lab == i] = 0
    keep = np.zeros_like(m)
    for sgn in (1, -1):
        k = np.zeros((9, 17), np.uint8)
        for t in range(-8, 9):
            k[4 + int(round(sgn * t / 2)), 8 + t] = 1
        c = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k)
        c = cv2.morphologyEx(c, cv2.MORPH_CLOSE, k)
        n, lab, st, _ = cv2.connectedComponentsWithStats(c)
        for i in range(1, n):
            if st[i, cv2.CC_STAT_WIDTH] >= 110:
                keep[lab == i] = 1
    ys, xs = np.nonzero(keep)
    if len(xs) < 200:
        return None
    hull = cv2.convexHull(np.stack([xs, ys], 1).astype(np.int32))
    out = np.zeros(m.shape, np.uint8)
    cv2.fillPoly(out, [hull], 1)
    return out if out.sum() > 150_000 else None


def _sane(m):
    if m is None:
        return False
    ys, xs = np.nonzero(m)
    area, w, h = len(xs), xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
    return (150_000 <= area <= 1_150_000 and xs.min() > 5 and xs.max() < 1915 and 0.35 <= area / (w * h) <= 0.8
            and _solidity(m) >= 0.82)            # contorno deshilachado = no se ha visto bien


def default_mask():
    """Rombo del mapa entero con zoom mínimo (cuando no se distingue el contorno real)."""
    m = np.zeros((1080, 1920), np.uint8)
    cv2.fillPoly(m, [np.array([(250, 495), (960, -40), (1670, 495), (960, 1030)], np.int32)], 1)
    m[865:, :] = 0
    return m


def structure_mask(img):
    """Plan para escenarios de suelo verde: todo lo que no es hierba/baldosa verde (edificios, muros) dentro
    del mapa, unido y relleno. None si no tiene sentido (p. ej. escenario de arena: ocupa el mapa entero)."""
    a = _bgr(img).astype(np.int16)
    b, g, r = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    green = (g > r + 12) & (g > b + 25)
    dm = default_mask()
    m = (~green).astype(np.uint8) & dm & _hud_mask(a.shape)
    m[:300, :330] = 0
    m[:240, 1480:] = 0
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((35, 35), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(m)
    if n < 2:
        return None
    i = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    comp = (lab == i).astype(np.uint8)
    cnts, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    out = np.zeros_like(comp)
    cv2.drawContours(out, cnts, -1, 1, -1)
    if out.sum() > 0.8 * dm.sum() or out.sum() < 150_000:
        return None
    return out


def _big_enough(m):
    """Una aldea con zoom mínimo ocupa al menos un tercio del ancho del mapa; si sale menos, se ha leído
    mal (p. ej. un trozo de suelo de un decorado)."""
    if m is None:
        return False
    xs = np.nonzero(m.any(axis=0))[0]
    return len(xs) and (xs.max() - xs.min()) >= 600


def village_geometry(img, fallback=False):
    """Esquinas L/R/T/B (punto más saliente), centro y máscara de la aldea; None si no se ve
    (con fallback=True, el rombo del mapa entero, marcado src='mapa')."""
    m = village_mask(img)
    src = "suelo"
    st = structure_mask(img)
    if st is not None and _sane(st) and (not _sane(m) or (m & st).sum() < 0.85 * st.sum()):
        m, src = st, "edificios"            # el suelo no cuadra con los edificios (escenario verde)
    if not (_sane(m) and _big_enough(m)):
        m, src = border_hull_mask(img), "borde"
        if not (_sane(m) and _big_enough(m)):
            if not fallback:
                return None
            m, src = default_mask(), "mapa"
    # envolvente convexa: lados rectos (los entrantes del contorno no despistan el despliegue)
    cnts, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if cnts:
        hull = cv2.convexHull(np.vstack(cnts))
        m = np.zeros_like(m, dtype=np.uint8)
        cv2.fillPoly(m, [hull], 1)
    ys, xs = np.nonzero(m)
    lft, rgt, top, asistente = xs.min(), xs.max(), ys.min(), ys.max()
    c = {"L": (int(lft), int(np.median(ys[xs <= lft + 3]))),
         "R": (int(rgt), int(np.median(ys[xs >= rgt - 3]))),
         "T": (int(np.median(xs[ys <= top + 3])), int(top)),
         "B": (int(np.median(xs[ys >= asistente - 3])), int(asistente))}
    return {"corners": c, "center": (float(xs.mean()), float(ys.mean())), "mask": m, "src": src,
            "box": (int(lft), int(top), int(rgt), int(asistente))}


# ---------------- cartas de la barra ----------------
_CARD_TPL = None


def _card_templates():
    global _CARD_TPL
    if _CARD_TPL is None:
        from pathlib import Path
        _CARD_TPL = {}
        for f in sorted((Path(__file__).parent / "cards").glob("*.png")):
            t = cv2.imread(str(f), cv2.IMREAD_GRAYSCALE)
            if t is not None:
                _CARD_TPL[f.stem] = t          # «nombre@2» = otra variante de la misma carta
    return _CARD_TPL


def card_identity(img, x_left):
    """Nombre de la carta (plantillas de cards/*.png) y parecido, o (None, score)."""
    a = cv2.cvtColor(_bgr(img), cv2.COLOR_BGR2GRAY)
    crop = a[860:1016, x_left + 18:x_left + 118]      # margen: la carta de un héroe desplegado sube ~40 px
    best, score = None, 0.0
    for name, t in _card_templates().items():
        if crop.shape[0] < t.shape[0] or crop.shape[1] < t.shape[1]:
            continue                                    # carta cortada por el borde de la pantalla
        r = cv2.matchTemplate(crop, t, cv2.TM_CCOEFF_NORMED)
        s = float(r.max())
        if s > score:
            best, score = name, s
    return (best.split("@")[0], score) if score >= 0.55 else (None, score)


_LOW_AD = None


def air_defenses_low(img, thr=0.62):
    """Defensas aéreas de nivel bajo (TH6-9: plataforma de madera con cohetes rojos), por plantillas
    tpl/adlow*.png. Devuelve [(x, y)]."""
    global _LOW_AD
    if _LOW_AD is None:
        from pathlib import Path
        _LOW_AD = [cv2.imread(str(f)) for pat in ("adlow*.png", "adhigh*.png")
                   for f in sorted((Path(__file__).parent / "tpl").glob(pat))]
    a = _bgr(img)
    hits = []
    for t in _LOW_AD:
        r = cv2.matchTemplate(a, t, cv2.TM_CCOEFF_NORMED)
        while True:
            _, mx, _, (x, y) = cv2.minMaxLoc(r)
            if mx < thr:
                break
            hits.append((mx, x + t.shape[1] // 2, y + int(t.shape[0] * 0.6)))
            cv2.circle(r, (x, y), 45, -1, -1)
    out = []
    for mx, x, y in sorted(hits, reverse=True):
        if y < 860 and all((x - a) ** 2 + (y - b) ** 2 > 60 ** 2 for a, b in out):
            out.append((x, y))
    return out


def find_air_defenses(img):
    """Defensas aéreas fiables: primero plantillas; el método de color sólo si no hay plantillas y da un
    número creíble (≤5; más = la skin oscura de los edificios lo confunde). Máximo 4."""
    tpl = air_defenses_low(img)
    if len(tpl) >= 2:
        return tpl[:4]
    col = air_defenses(img, debug=True)
    if len(col) > 7:                          # demasiados: la skin de los edificios lo confunde
        col = []
    col = [(x, y) for x, y, _ in sorted(col, key=lambda c: -c[2])[:4]]   # las 4 más claras
    out = list(tpl)
    for a in col:
        if all((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 > 60 ** 2 for b in out):
            out.append(a)
    return out[:4]


def _solidity(m):
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cnts:
        return 0
    c = max(cnts, key=cv2.contourArea)
    hull = cv2.convexHull(c)
    return cv2.contourArea(c) / max(1, cv2.contourArea(hull))


def find_template(img, names, thr=0.75):
    """Busca la mejor coincidencia de tpl/<name>.png (lista de nombres) → (x, y, score) o None."""
    from pathlib import Path
    a = _bgr(img)
    best = None
    for n in names:
        for f in sorted((Path(__file__).parent / "tpl").glob(f"{n}*.png")):
            t = cv2.imread(str(f))
            r = cv2.matchTemplate(a, t, cv2.TM_CCOEFF_NORMED)
            _, mx, _, (x, y) = cv2.minMaxLoc(r)
            if mx >= thr and (best is None or mx > best[2]):
                best = (x + t.shape[1] // 2, y + t.shape[0] // 2, float(mx))
    return best


# ---------------- almacenes del rival ----------------
_GOLD_TPL = None


def _gold_templates():
    """Almacenes de oro por plantilla (tpl/oro_*.png: caja de piedra, montón de monedas…). Para un aspecto
    nuevo basta recortar uno (~60×62 centrado en el almacén) y dejarlo ahí."""
    global _GOLD_TPL
    if _GOLD_TPL is None:
        import glob
        import os
        here = os.path.dirname(os.path.abspath(__file__))
        _GOLD_TPL = [t for t in (cv2.imread(f) for f in sorted(glob.glob(os.path.join(here, "tpl", "oro_*.png"))))
                     if t is not None]
    return _GOLD_TPL


def _blobs(m, amin):
    n, _, st, cen = cv2.connectedComponentsWithStats(m.astype(np.uint8))
    return [(float(cen[i][0]), float(cen[i][1]), int(st[i][4])) for i in range(1, n) if st[i][4] >= amin]


def _merge(pts, r):
    """Junta detecciones a menos de r px (la cúpula sale partida en dos por el reflejo)."""
    out = []
    for p in sorted(pts, key=lambda p: -p[2]):
        if all((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 > r * r for q in out):
            out.append(p)
    return out


def storages(img, area=None):
    """Almacenes del rival sin modelo: [{"kind": "elixir"|"gold", "x", "y"}].
    Elixir: la cúpula rosa (tono 142-157, muy brillante; el magenta puro de los dibujos del plan tiene S=255
    y queda fuera). Oro: plantillas tpl/oro_*.png (≥0,55, las 4 mejores; el detector por color del montón de
    monedas se quitó el 13-nov: los remates de muros de algunos niveles daban 40 falsos). `area` = máscara de la aldea (se ensancha
    un poco): fuera de ella hay decorados amarillos y rosas."""
    a = _bgr(img)
    h = cv2.cvtColor(a, cv2.COLOR_BGR2HSV)
    ok = _hud_mask(a.shape)
    ok[:230, 1450:] = 0                       # las barras de recursos propios bajan hasta y≈230
    if area is not None:
        ok &= cv2.dilate(area.astype(np.uint8), np.ones((41, 41), np.uint8))
    e = cv2.inRange(h, (142, 90, 190), (157, 230, 255)) & (ok * 255)
    e = cv2.morphologyEx(e, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    elixir = _merge(_blobs(e > 0, 250), 45)
    best = None
    for t in _gold_templates():
        r = cv2.matchTemplate(a, t, cv2.TM_CCOEFF_NORMED)
        th, tw = t.shape[:2]
        r = cv2.copyMakeBorder(r, th // 2, a.shape[0] - r.shape[0] - th // 2, tw // 2,
                               a.shape[1] - r.shape[1] - tw // 2, cv2.BORDER_CONSTANT, value=-1)
        best = r if best is None else np.maximum(best, r)
    boxes = []
    if best is not None:
        best[ok == 0] = -1
        while True:
            _, v, _, (x, y) = cv2.minMaxLoc(best)
            if v < 0.55 or len(boxes) >= 4:
                break
            boxes.append((float(x), float(y), int(v * 1000)))
            cv2.circle(best, (x, y), 45, -1, -1)
    gold = _merge(boxes, 50)
    elixir = elixir[:4]                       # un TH18 tiene 4 de cada; los más grandes primero
    return [{"kind": "elixir", "x": p[0], "y": p[1], "score": 1.0} for p in elixir] + \
           [{"kind": "gold", "x": p[0], "y": p[1], "score": p[2] / 1000} for p in gold]


def activity(prev, cur, area=None):
    """Dónde pelean nuestras tropas, sin modelo: lo que cambia entre dos capturas seguidas (tropas que se
    mueven, disparos, explosiones) dentro de la aldea. Devuelve (x, y, fuerza) del foco de movimiento más
    denso, o None si casi no se mueve nada."""
    a = cv2.cvtColor(_bgr(prev), cv2.COLOR_BGR2GRAY)
    b = cv2.cvtColor(_bgr(cur), cv2.COLOR_BGR2GRAY)
    d = (cv2.absdiff(a, b) > 35).astype(np.uint8) & _hud_mask(a.shape)
    if area is not None:
        d &= cv2.dilate(area.astype(np.uint8), np.ones((81, 81), np.uint8))
    d = cv2.morphologyEx(d, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    small = cv2.resize(d.astype(np.float32), (96, 54), interpolation=cv2.INTER_AREA)   # celdas de 20 px
    small = cv2.GaussianBlur(small, (0, 0), 2.5)
    _, mx, _, (x, y) = cv2.minMaxLoc(small)
    if mx < 0.02:
        return None
    return x * 20 + 10, y * 20 + 10, float(mx)


# ---------------- almacenes para cualquier TH: candidatos por color + clasificación por el modelo ----------------
def _peaks(dens, ok, thr, n, sep=50):
    """Máximos locales de una densidad (≥thr), separados ≥sep px, dentro de `ok`."""
    d = np.where(ok > 0, dens, 0).astype(np.float32)
    out = []
    while len(out) < n:
        _, v, _, (x, y) = cv2.minMaxLoc(d)
        if v < thr:
            break
        out.append((float(x), float(y), float(v)))
        cv2.circle(d, (x, y), sep, 0, -1)
    return out


def storage_candidates(img, area=None, per_kind=(9, 7, 4)):
    """Sitios que PUEDEN ser almacenes, recolectores o minas, para que el modelo los clasifique: montones de
    monedas (amarillo-naranja), elixir (rosa), elixir oscuro (negro violáceo) y lo que casen las plantillas de
    oro aprendidas. No depende del TH: todos los niveles enseñan el recurso que guardan. [{x, y, hint, score}]"""
    a = _bgr(img)
    h = cv2.cvtColor(a, cv2.COLOR_BGR2HSV)
    ok = _hud_mask(a.shape)
    ok[:230, 1450:] = 0
    if area is not None:
        ok &= cv2.dilate(area.astype(np.uint8), np.ones((41, 41), np.uint8))
    blur = lambda m: cv2.blur(m.astype(np.float32), (25, 25))
    gold = cv2.inRange(h, (14, 110, 140), (31, 255, 255)) > 0
    pink = cv2.inRange(h, (138, 70, 150), (168, 240, 255)) > 0
    dark = (cv2.inRange(h, (115, 60, 25), (160, 255, 110)) > 0)
    out = []
    for hint, m, thr, n in (("oro", gold, 0.30, per_kind[0]), ("elixir", pink, 0.18, per_kind[1]),
                            ("oscuro", dark, 0.45, per_kind[2])):
        out += [{"x": x, "y": y, "hint": hint, "score": v} for x, y, v in _peaks(blur(m), ok, thr, n)]
    for s in storages(img, area):              # plantillas (oro aprendido) y cúpulas rosas
        out.append({"x": s["x"], "y": s["y"], "hint": "oro" if s["kind"] == "gold" else "elixir", "score": 1.0})
    merged = []
    for c in sorted(out, key=lambda c: -c["score"]):
        if all((c["x"] - m["x"]) ** 2 + (c["y"] - m["y"]) ** 2 > 45 ** 2 for m in merged):
            merged.append(c)
    return merged[:20]


def crop_template(img, x, y):
    """Recorte 60×62 de un almacén (mismo formato que tpl/oro_*.png) en BGR."""
    a = _bgr(img)
    x, y = int(x), int(y)
    return a[max(0, y - 32):y + 30, max(0, x - 30):x + 30]


def reload_gold_templates():
    """Tras aprender una plantilla nueva de almacén de oro."""
    global _GOLD_TPL
    _GOLD_TPL = None


def best_template_score(img, x, y, templates):
    """Mejor parecido de las plantillas (BGR 62×60) alrededor de (x, y) (±20 px)."""
    a = _bgr(img)
    x, y = int(x), int(y)
    win = a[max(0, y - 52):y + 50, max(0, x - 50):x + 50]
    best = 0.0
    for t in templates:
        if win.shape[0] >= t.shape[0] and win.shape[1] >= t.shape[1]:
            best = max(best, float(cv2.matchTemplate(win, t, cv2.TM_CCOEFF_NORMED).max()))
    return best


# ---------------- almacenes por las imágenes de la wiki (SIFT): cualquier TH, nivel y relleno ----------------
# Las imágenes de ref/almacenes (wiki) salen llenas y con otra luz, así que no valen como plantilla directa
# (coincidencia ≈0,06 en el sitio bueno). SIFT sí las reconoce: se compara CADA referencia por separado con
# todos los puntos de la aldea (2.º vecino dentro de la misma referencia: así sirven varias copias iguales del
# almacén) y se agrupan por posición. Un pico vale si destaca sobre el fondo de esa referencia en esa aldea
# (≥1,6 × su 8.º pico): algunas referencias casan un poco con todo. Medido 13-nov en 5 aldeas TH18 (también las
# de escenario oscuro donde el modelo fallaba): ~3 s, sin modelo.
_SIFT = {"refs": None}
SIFT_CAT = {"Gold_Storage": "gold", "Elixir_Storage": "elixir", "Dark_Elixir_Storage": "dark"}


def _sift_refs():
    if _SIFT["refs"] is None:
        import glob
        import os
        import re
        here = os.path.dirname(os.path.abspath(__file__))
        sift = cv2.SIFT_create()
        refs = []
        for f in sorted(glob.glob(os.path.join(here, "ref", "almacenes", "*.png"))):
            m = re.match(r"([A-Za-z_]+?)\d", os.path.basename(f))
            if not m or m.group(1) not in SIFT_CAT:
                continue
            a = cv2.imread(f, cv2.IMREAD_UNCHANGED)
            if a is None or a.ndim != 3 or a.shape[2] != 4:
                continue
            g = cv2.resize(cv2.cvtColor(a[:, :, :3], cv2.COLOR_BGR2GRAY), None, fx=0.5, fy=0.5,
                           interpolation=cv2.INTER_AREA)
            mk = (cv2.resize(a[:, :, 3], None, fx=0.5, fy=0.5) > 128).astype(np.uint8) * 255
            _, d = sift.detectAndCompute(g, mk)
            if d is not None and len(d) >= 20:
                refs.append((os.path.basename(f), SIFT_CAT[m.group(1)], d.astype(np.float32)))
        _SIFT["refs"], _SIFT["sift"] = refs, sift
    return _SIFT["refs"]


def sift_storages(img, area=None):
    """Almacenes de oro / elixir / oscuro por las imágenes de la wiki: [{kind, x, y, score, ref}]."""
    refs = _sift_refs()
    if not refs:
        return []
    a = _bgr(img)
    ok = _hud_mask(a.shape)
    ok[:230, 1450:] = 0
    if area is not None:
        ok &= cv2.dilate(area.astype(np.uint8), np.ones((41, 41), np.uint8))
    g = cv2.resize(cv2.cvtColor(a, cv2.COLOR_BGR2GRAY), None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    kp, d = _SIFT["sift"].detectAndCompute(g, cv2.resize(ok * 255, None, fx=2, fy=2,
                                                          interpolation=cv2.INTER_NEAREST))
    if d is None:
        return []
    d = d.astype(np.float32)
    pts = np.array([k.pt for k in kp]) / 2
    bf = cv2.BFMatcher()
    best, allpeaks = {}, {}
    for name, kind, rd in refs:
        v = np.zeros((54, 96), np.float32)
        for m in bf.knnMatch(d, rd, k=2):
            if len(m) == 2 and m[0].distance < 0.7 * m[1].distance:
                x, y = pts[m[0].queryIdx]
                v[min(53, int(y / 20)), min(95, int(x / 20))] += 1
        v = cv2.GaussianBlur(v, (0, 0), 1.0) * 6
        peaks = []
        for _ in range(10):
            _, mx, _, (x, y) = cv2.minMaxLoc(v)
            if mx <= 0:
                break
            peaks.append((mx, x, y))
            cv2.circle(v, (x, y), 3, 0, -1)
        allpeaks[name] = (kind, peaks)
        noise = peaks[7][0] if len(peaks) > 7 else (peaks[-1][0] if peaks else 0)
        for mx, x, y in peaks:
            if mx >= max(12, 1.6 * noise):
                key = (x // 3, y // 3)
                if mx > best.get(key, {"score": 0})["score"]:
                    best[key] = {"kind": kind, "x": float(x * 20 + 10), "y": float(y * 20 + 10),
                                 "score": float(mx), "ref": name}
    # el nivel que mejor se reconoce de cada tipo se repite en la aldea: con esa misma referencia se aceptan
    # picos más flojos (≥50 % del mejor; 13-nov: un 2.º almacén igual tapado a medias se quedaba fuera)
    for kind in ("gold", "elixir"):
        top = max((s for s in best.values() if s["kind"] == kind), key=lambda s: s["score"], default=None)
        if not top:
            continue
        for mx, x, y in allpeaks[top["ref"]][1]:
            if mx >= max(9, 0.5 * top["score"]):
                key = (x // 3, y // 3)
                if key not in best:
                    best[key] = {"kind": kind, "x": float(x * 20 + 10), "y": float(y * 20 + 10),
                                 "score": float(mx), "ref": top["ref"]}
    out = []
    for s in sorted(best.values(), key=lambda s: -s["score"]):
        if all((s["x"] - o["x"]) ** 2 + (s["y"] - o["y"]) ** 2 > 50 ** 2 for o in out):
            out.append(s)
    dark = [s for s in out if s["kind"] == "dark"][:1]          # sólo hay uno por aldea
    return [s for s in out if s["kind"] != "dark"] + dark


# ---------------- cartas de la barra por los retratos de la wiki (SIFT) ----------------
# ref/avatar/Avatar_*.png: tropas, héroes, hechizos y máquinas de asedio de todos los TH. Medido 13-nov: la carta
# buena saca 19-134 coincidencias y la siguiente ≤16 (el Sky Wagon, sin plantilla, salió a la primera).
_AVATAR = {"refs": None}


def _avatar_refs():
    if _AVATAR["refs"] is None:
        import glob
        import os
        here = os.path.dirname(os.path.abspath(__file__))
        sift = cv2.SIFT_create()
        refs = []
        for f in sorted(glob.glob(os.path.join(here, "ref", "avatar", "Avatar_*.png"))):
            a = cv2.imread(f, cv2.IMREAD_UNCHANGED)
            if a is None or a.ndim != 3:
                continue
            m = (a[:, :, 3] > 100).astype(np.uint8) * 255 if a.shape[2] == 4 else None
            _, d = sift.detectAndCompute(cv2.cvtColor(a[:, :, :3], cv2.COLOR_BGR2GRAY), m)
            if d is not None and len(d) >= 10:
                refs.append((os.path.basename(f)[7:-4], d.astype(np.float32)))
        _AVATAR["refs"], _AVATAR["sift"] = refs, sift
    return _AVATAR["refs"]


def avatar_identity(img, x_left):
    """Nombre del retrato de la wiki que corresponde a la carta (p. ej. "Dragon_Rider", "Lightning_Spell",
    "Hero_Archer_Queen") y su puntuación; (None, n) si no hay uno claro (≥18 y ≥1,6 × el segundo)."""
    refs = _avatar_refs()
    a = _bgr(img)
    crop = a[880:1050, max(0, x_left + 5):x_left + 135]
    if crop.shape[1] < 100:
        return None, 0
    crop = cv2.resize(crop, None, fx=1.3, fy=1.3)
    _, d = _AVATAR["sift"].detectAndCompute(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), None)
    if d is None:
        return None, 0
    d = d.astype(np.float32)
    bf = cv2.BFMatcher()
    sc = []
    for name, rd in refs:
        ms = bf.knnMatch(d, rd, k=2)
        sc.append((sum(1 for m in ms if len(m) == 2 and m[0].distance < 0.75 * m[1].distance), name))
    sc.sort(reverse=True)
    if not sc:
        return None, 0
    # el mismo personaje puede salir dos veces (Archer_Queen y Hero_Archer_Queen): el 2.º distinto cuenta
    base = lambda n: n.replace("Hero_", "")
    second = next((s for s, n in sc[1:] if base(n) != base(sc[0][1])), 0)
    if sc[0][0] >= 18 and sc[0][0] >= 1.6 * max(1, second):
        return sc[0][1], sc[0][0]
    return None, sc[0][0]


def twins(img, x, y, area=None, thr=0.55, n=3):
    """Copias del edificio que hay en (x, y) en la misma captura: los almacenes de un nivel son idénticos, así
    que con uno encontrado (por SIFT, plantilla o color) salen los demás aunque su aspecto no esté en ninguna
    referencia. Medido 13-nov: gemelos 0,58-0,75 y lo siguiente 0,29."""
    a = _bgr(img)
    x, y = int(x), int(y)
    t = a[max(0, y - 34):y + 30, max(0, x - 32):x + 32]
    if t.shape[0] < 50 or t.shape[1] < 50:
        return []
    r = cv2.matchTemplate(a, t, cv2.TM_CCOEFF_NORMED)
    ok = _hud_mask(a.shape)
    ok[:230, 1450:] = 0
    if area is not None:
        ok &= cv2.dilate(area.astype(np.uint8), np.ones((41, 41), np.uint8))
    hh, ww = t.shape[:2]
    r = np.where(ok[hh // 2: hh // 2 + r.shape[0], ww // 2: ww // 2 + r.shape[1]] > 0, r, -1)
    cv2.circle(r, (x - ww // 2, y - hh // 2), 45, -1, -1)       # el propio
    out = []
    while len(out) < n:
        _, v, _, (px, py) = cv2.minMaxLoc(r)
        if v < thr:
            break
        out.append((float(px + ww // 2), float(py + hh // 2), float(v)))
        cv2.circle(r, (px, py), 45, -1, -1)
    return out

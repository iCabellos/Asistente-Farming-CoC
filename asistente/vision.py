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

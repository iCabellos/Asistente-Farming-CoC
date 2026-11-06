"""Probabilidad de cada resultado de un ataque (0, 1, 2 o 3 estrellas) entre dos jugadores concretos.

Regresión ordinal con efectos por jugador, entrenada en cada recogida con todos los ataques conocidos: los de la liga y
el historial de todos los jugadores del grupo, propios y rivales. Sale de estudiar casi 12.000 ataques reales, entrenando
con el pasado y midiendo con ataques posteriores:

- Lo que más explica un pleno es la diferencia de ayuntamiento y, después, quién ataca y a qué aldea.
- Pesan más los ataques recientes, y cuentan la forma de los últimos ataques, la liga y si la aldea ya estaba tocada.
- Una vez conocido el historial, héroes, mascotas, hechizos, experiencia y estrellas de guerra no mejoran la predicción.
  Sólo aporta algo el equipo de héroes y la posición entre aldeas del mismo ayuntamiento, y únicamente en ataques
  recientes: la foto de una aldea no dice nada de cómo era hace años.

El modelo no tiene valores fijos a mano: PRIOR es sólo el punto de partida, y los datos lo desplazan. Con pocos datos
(un clan nuevo) se parece al punto de partida; con muchos, a lo que ve. La memoria de los ataques y la fuerza de los
efectos de jugador se eligen solos, probando cuál habría acertado más en las últimas semanas.

Usa numpy sólo al entrenar, y lo importa dentro: una consulta normal de la web no lo carga.
"""
import math
from collections import defaultdict
from datetime import datetime, timezone

D_LIMIT = 5
FORM_N = 8                # ataques que forman la «forma» reciente
RECENT_N = 20             # ataques que se enseñan como historial reciente
RECENT_DAYS = 200         # la foto de la aldea sólo vale para ataques cercanos
HOLDOUT_DAYS = 45
MIN_ROWS_TUNE = 1500
MIN_HOLDOUT = 120
DEFAULT_HP = {"half": 180, "sa": 1.0, "sd": .7}
HALVES = (120, 180, 365, 730)
SIGMAS = ((.7, .5), (1.0, .7), (1.5, 1.0))
PRIOR_L2 = .3
STEPS, LR = 700, .04
USE_HALF_DAYS = 60        # medido: con esta memoria se predice mejor quién atacará
BINS = [k for k in range(-D_LIMIT, D_LIMIT + 1) if k != 0]
NAMES = [f"d{k}" for k in BINS] + ["t", "t2", "cwl", "fresh", "cwl_up", "t_eq", "t_up", "form_a", "form_d", "pos_same", "eq_gap"]
# Punto de partida: ajuste con 11.883 ataques reales (se calcula con scripts de investigación, no a mano)
PRIOR = {"beta": [-5.96, -4.6, -3.38, -2.26, -1.09, .74, 1.77, 2.69, 3.62, 4.5, .72, .27, .08, .15, .32, -1.09, -1.51, 4.18, 2.42, .37, .14],
         "th": [3.6, 1.49, .01], "pct": {"0": 31.0, "1": 67.0, "2": 78.0, "3": 100.0}, "use": .8, "war_sigma": .33}


def _ts(s):
    try:
        return datetime.strptime(str(s), "%Y%m%dT%H%M%S.%fZ").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return 0.0


# ---------------- datos ----------------
def rows_from_history(tag, items):
    """Ataques y defensas del historial de un jugador. Devuelve (ataques, asistencia a guerras)."""
    rows, usage = [], []
    for w in items or []:
        if w.get("type") == "friendly":
            continue
        end, me = _ts(w.get("endTime")), w.get("player") or {}
        if not end or not me:
            continue
        cwl, size = w.get("type") == "cwl", w.get("teamSize") or 15
        clan = (w.get("clan") or {}).get("tag")
        attacks = w.get("attacks") or []
        usage.append({"tag": tag, "end": end, "cwl": int(cwl), "per": w.get("attacksPerMember") or (1 if cwl else 2), "used": len(attacks)})
        for a in attacks:
            e = a.get("player") or {}
            if e.get("tag") and me.get("townhallLevel") and e.get("townhallLevel"):
                rows.append(_row(tag, e["tag"], end, a, me, e, size, cwl, clan))
        for a in w.get("defenses") or []:
            e = a.get("player") or {}
            if e.get("tag") and me.get("townhallLevel") and e.get("townhallLevel"):
                rows.append(_row(e["tag"], tag, end, a, e, me, size, cwl, None))
    return rows, usage


def _row(a, d, end, x, pa, pd, size, cwl, clan):
    return {"a": a, "d": d, "end": end, "ord": x.get("order") or 0, "a_th": pa["townhallLevel"], "d_th": pd["townhallLevel"], "a_pos": pa.get("mapPosition"), "d_pos": pd.get("mapPosition"),
            "size": size, "cwl": int(cwl), "stars": x.get("stars", 0), "pct": x.get("destructionPercentage", 0) or 0, "fresh": None if x.get("fresh") is None else int(x["fresh"]), "clan": clan}


def rows_from_league(L):
    """Los ataques de la liga en curso: están al día aunque el historial del jugador aún no los tenga."""
    out = []
    for w in L["wars"]:
        end = _ts(w.get("end"))
        for me, ot in ((w["a"], w["b"]), (w["b"], w["a"])):
            info = {m["tag"]: m for m in ot["members"]}
            for m in me["members"]:
                for x in m["atk"]:
                    e = info.get(x["def"])
                    if e:
                        out.append({"a": m["tag"], "d": e["tag"], "end": end, "ord": x.get("order") or 0, "a_th": m["th"], "d_th": e["th"], "a_pos": m.get("pos"), "d_pos": e.get("pos"), "size": w["size"], "cwl": 1,
                                    "stars": x["stars"], "pct": x["pct"], "fresh": None, "clan": me["tag"]})
    return out


def merge(*sets):
    """Une ataques sin repetirlos. Cuando el mismo ataque viene dos veces se queda el que más sabe."""
    seen = {}
    for rows in sets:
        for r in rows:
            k = (r["a"], r["d"], r["end"], r["ord"])
            if k not in seen or (seen[k].get("fresh") is None and r.get("fresh") is not None) or (seen[k].get("clan") is None and r.get("clan") is not None):
                seen[k] = r if k not in seen else {**seen[k], **{f: v for f, v in r.items() if v is not None}}
    return sorted(seen.values(), key=lambda r: (r["end"], r["ord"]))


def village_summary(p):
    """Lo que interesa de la ficha de un jugador. De la aldea sólo se conserva lo que el análisis usa o se enseña."""
    heroes = [h for h in p.get("heroes") or [] if h.get("village") == "home"]
    worn = [e for h in heroes for e in h.get("equipment") or [] if e.get("maxLevel")]
    return {"tag": p.get("tag"), "name": p.get("name"), "th": p.get("townHallLevel"), "weapon": p.get("townHallWeaponLevel") or 0, "exp": p.get("expLevel"), "war_stars": p.get("warStars"),
            "heroes": [[h.get("name"), h.get("level")] for h in heroes], "hero_sum": sum(h.get("level") or 0 for h in heroes),
            "equip": round(sum(e["level"] for e in worn) / max(sum(e["maxLevel"] for e in worn), 1), 4) if worn else 0.0}


def equip_z(villages):
    """Equipo de héroes comparado con los del mismo ayuntamiento (con los vecinos si hay pocos)."""
    by = defaultdict(list)
    for v in villages.values():
        if v.get("th"):
            by[v["th"]].append(v.get("equip") or 0.0)
    out = {}
    for t, v in villages.items():
        th = v.get("th")
        if not th:
            continue
        pool = by[th] if len(by[th]) >= 10 else [x for k, xs in by.items() if abs(k - th) <= 1 for x in xs]
        m = sum(pool) / len(pool)
        sd = (sum((x - m) ** 2 for x in pool) / len(pool)) ** .5
        out[t] = (th, (v.get("equip", 0.0) - m) / sd if sd > 1e-9 else 0.0)
    return out


def usage_rates(rows, now, skip=(), cwl=1):
    """Asistencia ponderada de cada jugador, en liga o en guerras normales: lo reciente manda. Devuelve {tag: (ataques, guerras)}."""
    u, n = defaultdict(float), defaultdict(float)
    for r in rows:
        if bool(r["cwl"]) != bool(cwl) or r["end"] in skip:
            continue
        w = .5 ** (max(now - r["end"], 0) / (USE_HALF_DAYS * 86400))
        n[r["tag"]] += w
        u[r["tag"]] += w * min(r["used"], r["per"]) / max(r["per"], 1)
    return {t: (u[t], n[t]) for t in n}


# ---------------- modelo ----------------
def _features(d, dth, cwl, fresh, form_a, form_d, pos_same, eq_gap):
    t = (dth - 13) / 4
    bins = [1.0 if max(-D_LIMIT, min(D_LIMIT, d)) == k else 0.0 for k in BINS]
    return bins + [t, t * t, cwl, fresh, cwl * (d >= 1), t * (d == 0), t * (d > 0), form_a, form_d, pos_same, eq_gap]


class Prob:
    """Modelo ya entrenado. No necesita numpy: sólo sumas y logísticas, para que la simulación vaya rápida."""

    def __init__(self, beta, th, ua, ud, form_a, form_d, eq, pct, info=None, recent_a=None, recent_d=None):
        self.beta, self.th, self.ua, self.ud, self.form_a, self.form_d, self.eq, self.pct = beta, th, ua, ud, form_a, form_d, eq, pct
        self.info = info or {}
        self.recent_a, self.recent_d = recent_a or {}, recent_d or {}     # plenos en sus últimos ataques y defensas
        self._c = {}

    def _eq_gap(self, a, b):
        x, y = self.eq.get(a["tag"]), self.eq.get(b["tag"])
        return (x[1] if x and x[0] == a["th"] else 0.0) - (y[1] if y and y[0] == b["th"] else 0.0)

    def eta(self, a, b, fresh=True, cwl=True, size=15):
        d = a["th"] - b["th"]
        pos = max(-1.0, min(1.0, ((b.get("pos") or 0) - (a.get("pos") or 0)) / max(size, 1))) if d == 0 and a.get("pos") and b.get("pos") else 0.0
        x = _features(d, b["th"], float(cwl), 1.0 if fresh else -1.0, self.form_a.get(a["tag"], 0.0), self.form_d.get(b["tag"], 0.0), pos, self._eq_gap(a, b))
        return sum(i * j for i, j in zip(self.beta, x)) + self.ua.get(a["tag"], 0.0) + self.ud.get(b["tag"], 0.0)

    def dist(self, a, b, fresh=True, cwl=True, size=15, shift=0.0):
        """Probabilidad de 0, 1, 2 y 3 estrellas. `shift` mueve la guerra entera: un mal o buen día de todo el clan."""
        k = (a["tag"], b["tag"], a["th"], b["th"], a.get("pos"), b.get("pos"), fresh, cwl, shift)
        v = self._c.get(k)
        if v is None:
            e = self.eta(a, b, fresh, cwl, size) + shift
            p = [1 / (1 + math.exp(-max(min(e + c, 40), -40))) for c in self.th]
            v = (1 - p[0], p[0] - p[1], p[1] - p[2], p[2])
            self._c[k] = v
        return v


def _prepare(rows, villages, np):
    n = len(rows)
    y = np.array([r["stars"] for r in rows], dtype=np.int64)
    d = np.array([r["a_th"] - r["d_th"] for r in rows], dtype=float)
    dth = np.array([r["d_th"] for r in rows], dtype=float)
    end = np.array([r["end"] for r in rows], dtype=float)
    cwl = np.array([r["cwl"] for r in rows], dtype=float)
    fresh = np.array([0.0 if r["fresh"] is None else (1.0 if r["fresh"] else -1.0) for r in rows])
    size = np.array([r["size"] or 15 for r in rows], dtype=float)
    now = end.max() if n else 0.0
    means = {k: float(y[np.clip(d, -4, 4) == k].mean()) if (np.clip(d, -4, 4) == k).any() else 1.5 + k / 3 for k in range(-4, 5)}
    ha, hd = defaultdict(list), defaultdict(list)
    fa, fd = np.zeros(n), np.zeros(n)
    for i, r in enumerate(rows):           # la forma sólo mira hacia atrás: ningún ataque se ve a sí mismo
        a, b = ha[r["a"]][-FORM_N:], hd[r["d"]][-FORM_N:]
        fa[i] = sum(a) / FORM_N
        fd[i] = sum(b) / FORM_N
        res = (r["stars"] - means[int(max(-4, min(4, d[i])))]) / 3
        ha[r["a"]].append(res)
        hd[r["d"]].append(res)
    eq = equip_z(villages)
    pos, gap = np.zeros(n), np.zeros(n)
    for i, r in enumerate(rows):
        if now - r["end"] < RECENT_DAYS * 86400:
            if d[i] == 0 and r.get("a_pos") and r.get("d_pos"):
                pos[i] = max(-1, min(1, (r["d_pos"] - r["a_pos"]) / (size[i] or 15)))
            x, z = eq.get(r["a"]), eq.get(r["d"])
            gap[i] = (x[1] if x and x[0] == r["a_th"] else 0.0) - (z[1] if z and z[0] == r["d_th"] else 0.0)
    X = np.stack([(np.clip(d, -D_LIMIT, D_LIMIT) == k).astype(float) for k in BINS], axis=1)
    t = (dth - 13) / 4
    X = np.concatenate([X, np.stack([t, t * t, cwl, fresh, cwl * (d >= 1), t * (d == 0), t * (d > 0), fa, fd, pos, gap], axis=1)], axis=1)
    keys_a = sorted({r["a"] for r in rows})
    keys_d = sorted({r["d"] for r in rows})
    ia, id_ = {k: i for i, k in enumerate(keys_a)}, {k: i for i, k in enumerate(keys_d)}
    return {"X": X, "y": y, "end": end, "Ia": np.array([ia[r["a"]] for r in rows], dtype=np.int64), "Id": np.array([id_[r["d"]] for r in rows], dtype=np.int64),
            "keys_a": keys_a, "keys_d": keys_d, "form_a": {k: sum(v[-FORM_N:]) / FORM_N for k, v in ha.items()}, "form_d": {k: sum(v[-FORM_N:]) / FORM_N for k, v in hd.items()}, "eq": eq,
            "cwl": cwl}


def _fit(D, mask, hp, np, steps=STEPS, effects=True):
    idx = np.where(mask)[0]
    X, y, Ia, Id, end = D["X"][idx], D["y"][idx], D["Ia"][idx], D["Id"][idx], D["end"][idx]
    na, nd = len(D["keys_a"]), len(D["keys_d"])
    b0 = np.array(PRIOR["beta"], dtype=float)
    b, ua, ud, th = b0.copy(), np.zeros(na), np.zeros(nd), np.array(PRIOR["th"], dtype=float)
    if not len(idx):
        return b, ua, ud, th
    w = .5 ** ((end.max() - end) / (hp["half"] * 86400))
    sa, sd = hp["sa"], hp["sd"]
    params = [b, ua, ud, th]
    m = [np.zeros_like(p) for p in params]
    v = [np.zeros_like(p) for p in params]
    N, ar = max(w.sum(), 1.0), np.arange(len(y))
    for t in range(1, steps + 1):
        eta = X @ b + (ua[Ia] + ud[Id] if effects else 0)
        p = 1 / (1 + np.exp(-np.clip(eta[:, None] + th[None, :], -40, 40)))
        P = np.stack([1 - p[:, 0], p[:, 0] - p[:, 1], p[:, 1] - p[:, 2], p[:, 2]], axis=1).clip(1e-9, 1)
        dn, ps = p * (1 - p), P[ar, y]
        hi = np.where(y == 0, 0, dn[ar, np.clip(y - 1, 0, 2)])
        lo = np.where(y == 3, 0, dn[ar, np.clip(y, 0, 2)])
        g = (hi - lo) / ps * w
        gs = [X.T @ g - PRIOR_L2 * (b - b0), (np.bincount(Ia, g, na) - ua / sa ** 2) if effects else np.zeros(na), (np.bincount(Id, g, nd) - ud / sd ** 2) if effects else np.zeros(nd),
              np.array([np.sum(w * dn[:, k] / ps * ((y == k + 1) * 1.0 - (y == k) * 1.0)) for k in range(3)])]
        for i, (q, gr) in enumerate(zip(params, gs)):
            gr = gr / N * 300
            m[i] = .9 * m[i] + .1 * gr
            v[i] = .999 * v[i] + .001 * gr ** 2
            q += LR * (m[i] / (1 - .9 ** t)) / (np.sqrt(v[i] / (1 - .999 ** t)) + 1e-8)
        th[:] = np.sort(th)[::-1]
    return b, ua, ud, th


def _predict(D, idx, fit, np, shift=0.0):
    b, ua, ud, th = fit
    eta = D["X"][idx] @ b + ua[D["Ia"][idx]] + ud[D["Id"][idx]] + shift
    p = 1 / (1 + np.exp(-np.clip(eta[:, None] + th[None, :], -40, 40)))
    return np.stack([1 - p[:, 0], p[:, 0] - p[:, 1], p[:, 1] - p[:, 2], p[:, 2]], axis=1).clip(1e-9, 1)


def _loglik(D, idx, P, np):
    y = D["y"][idx]
    return float(-np.mean(np.log(P[np.arange(len(y)), y])))


def _tune(D, tr, va, np, on=None):
    """Prueba cuánta memoria y cuánta fuerza dar a los jugadores, y se queda con lo que habría acertado más."""
    best, top = dict(DEFAULT_HP), math.inf
    tests = len(HALVES) + len(SIGMAS)
    done = 0
    for half in HALVES:
        hp = {**DEFAULT_HP, "half": half}
        s = _loglik(D, va, _predict(D, va, _fit(D, tr, hp, np, steps=350), np), np)
        if s < top:
            best, top = hp, s
        done += 1
        if on:
            on(.7 * done / tests, f"ajuste {done} de {tests}")
    for sa, sd in SIGMAS:
        hp = {**best, "sa": sa, "sd": sd}
        s = _loglik(D, va, _predict(D, va, _fit(D, tr, hp, np, steps=350), np), np)
        if s < top:
            best, top = hp, s
        done += 1
        if on:
            on(.7 * done / tests, f"ajuste {done} de {tests}")
    return best


def _recent(rows, key):
    last = defaultdict(list)
    for r in rows:
        last[r[key]].append(r["stars"] == 3)
    return {t: (len(v[-RECENT_N:]), sum(v[-RECENT_N:])) for t, v in last.items()}


def train(rows, villages=None, hp=None, tune=True, report=True, steps=STEPS, on=None):
    """Entrena con todo lo conocido. Devuelve el modelo y, si hay ataques suficientes, cómo acierta sobre el futuro.
    `on(fracción, detalle)` cuenta por dónde va."""
    import numpy as np
    villages = villages or {}
    pct = _pct_table(rows)
    if not rows:
        return Prob(PRIOR["beta"], PRIOR["th"], {}, {}, {}, {}, equip_z(villages), pct, {"rows": 0})
    D = _prepare(rows, villages, np)
    last = D["end"].max()
    va_mask = D["end"] >= last - HOLDOUT_DAYS * 86400
    tr, va = ~va_mask, np.where(va_mask)[0]
    enough = len(rows) >= MIN_ROWS_TUNE and len(va) >= MIN_HOLDOUT
    if hp is None:
        hp = _tune(D, tr, va, np, on) if tune and enough else dict(DEFAULT_HP)
    info = {"rows": len(rows), "hp": hp, "players_a": len(D["keys_a"]), "players_d": len(D["keys_d"])}
    if enough and report:
        if on:
            on(.75, "midiendo el acierto")
        info.update(_report(D, tr, va, hp, np))
    if on:
        on(.9, f"{len(rows):,} ataques".replace(",", "."))
    fit = _fit(D, np.ones(len(rows), dtype=bool), hp, np, steps=steps)
    b, ua, ud, th = fit
    return Prob([float(x) for x in b], [float(x) for x in th], {k: float(ua[i]) for i, k in enumerate(D["keys_a"])}, {k: float(ud[i]) for i, k in enumerate(D["keys_d"])},
                D["form_a"], D["form_d"], D["eq"], pct, info, _recent(rows, "a"), _recent(rows, "d"))


def _pct_table(rows):
    out = {}
    for s in range(4):
        v = [r["pct"] for r in rows if r["stars"] == s]
        out[s] = (sum(v) + PRIOR["pct"][str(s)] * 5) / (len(v) + 5)
    return out


def _report(D, tr, va, hp, np):
    """Prueba honesta: entrena sin las últimas semanas y compara lo que dice con lo que pasó."""
    fit = _fit(D, tr, hp, np)
    P = _predict(D, va, fit, np)
    base = _predict(D, va, _fit(D, tr, hp, np, steps=250, effects=False), np)
    y = D["y"][va]
    t = (y == 3) * 1.0
    p3 = P[:, 3]

    def ll3(q):
        return float(-np.mean(t * np.log(q) + (1 - t) * np.log(1 - q + 1e-9)))
    order = np.argsort(p3)
    rank = np.empty(len(p3))
    rank[order] = np.arange(len(p3))
    pos, neg = t == 1, t == 0
    auc = float((rank[pos].mean() - (pos.sum() - 1) / 2) / neg.sum()) if pos.any() and neg.any() else None
    bins = []
    for lo, hi in ((0, .2), (.2, .4), (.4, .6), (.6, .75), (.75, .9), (.9, 1.01)):
        m = (p3 >= lo) & (p3 < hi)
        if m.sum():
            bins.append({"lo": lo, "hi": min(hi, 1), "says": round(float(p3[m].mean()), 3), "real": round(float(t[m].mean()), 3), "n": int(m.sum())})
    # ¿Los ataques de una misma guerra se mueven juntos? Un mal día de todo el clan: eso ensancha los márgenes
    E, Eup = P @ np.arange(4.0), _predict(D, va, fit, np, .1) @ np.arange(4.0)
    var = P @ (np.arange(4.0) ** 2) - E ** 2
    groups = defaultdict(list)
    for pos_, i in enumerate(va):
        groups[D["end"][i]].append(pos_)
    extra = []
    for ids in groups.values():
        if len(ids) >= 8:
            ids = np.array(ids)
            r, slope = float((y[ids] - E[ids]).sum()), float(((Eup - E)[ids]).sum() / .1)
            if slope > 1e-6:
                extra.append((r ** 2 - float(var[ids].sum())) / slope ** 2)
    sigma = float(max(0.0, np.mean(extra)) ** .5) if extra else 0.0
    calib = sum(abs(b["says"] - b["real"]) * b["n"] for b in bins) / max(sum(b["n"] for b in bins), 1)       # cuánto se desvía lo que dice de lo que pasa
    return {"holdout": len(va), "auc": round(auc, 3) if auc else None, "ll3": round(ll3(p3), 4), "ll3_base": round(ll3(base[:, 3]), 4), "brier": round(float(np.mean((p3 - t) ** 2)), 4),
            "bins": bins, "war_sigma": round(min(sigma, 1.0), 3), "calib": round(calib, 4)}

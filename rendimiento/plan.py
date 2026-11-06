"""Plan de ataque: quién ataca a quién para conseguir el mayor número de plenos.

Se calcula el % de pleno de cada cuenta contra cada aldea y se busca el reparto con más plenos esperados, con dos reglas:
- Cada cuenta ataca una vez y cada aldea recibe un solo ataque del plan.
- Nadie ataca por encima de su puesto: el 5 puede ir al 5 o más abajo, nunca al 3.

Por eso el resultado sale solo, sin decidirlo de antemano: si el 12 ya hace pleno probable al 15, se baja a todos; si lo
que da más plenos es el espejo, sale espejo. Quien se queda sin aldea no pierde nada: queda de reserva para rematar
una aldea que haya fallado. La nota de corte tampoco es fija: es la más exigente que no sacrifica plenos esperados.
"""
import random

from itertools import accumulate

ALMOST = .85              # a partir de aquí se llama «casi seguro»
GIVE_UP = .015            # parte de los plenos esperados que se acepta perder por evitar ataques dudosos
FLOOR = .25               # por debajo no se considera un intento de pleno
MC = 400


def _hungarian(cost):
    """Asignación de coste mínimo: una columna distinta para cada fila (filas <= columnas)."""
    import math
    n, m = len(cost), len(cost[0]) if cost else 0
    u, v, p, way = [0.0] * (n + 1), [0.0] * (m + 1), [0] * (m + 1), [0] * (m + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv, used = [math.inf] * (m + 1), [False] * (m + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], math.inf, 0
            for j in range(1, m + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    out = [-1] * n
    for j in range(1, m + 1):
        if p[j]:
            out[p[j] - 1] = j - 1
    return out


def grid(prob, attackers, bases, size, cwl=True):
    """Reparto de estrellas de cada cuenta contra cada aldea, tal como están ahora."""
    return [[prob.dist(a, b, fresh=not (b.get("touched") or b.get("best", 0)), cwl=cwl, size=size) for b in bases] for a in attackers]


def _gain(p, best):
    return sum(p[s] * max(0, s - best) for s in range(4))


def assign(attackers, bases, dist, floor=0.0, up=False, value="triples"):
    """El mejor reparto. value: «triples» busca plenos, «stars» estrellas. Empates: atacante más débil, para reservar al fuerte."""
    free = [j for j, b in enumerate(bases) if b.get("best", 0) < 3]
    if not attackers or not free:
        return {}
    na, nb = len(attackers), len(free)
    big = 1e6
    cost = []
    for i, a in enumerate(attackers):
        row = []
        for j in free:
            b = bases[j]
            p = dist[i][j]
            ok = (up or (b.get("pos") or 0) >= (a.get("pos") or 0)) and p[3] >= floor
            v = (p[3] + .02 * _gain(p, b.get("best", 0)) / 3) if value == "triples" else _gain(p, b.get("best", 0)) + .02 * p[3]
            row.append(-(v + .0005 * (a.get("pos") or 0)) if ok else big)
        row += [0.0] * na                     # quedarse sin atacar siempre es posible
        cost.append(row)
    pick = _hungarian(cost)
    return {i: free[c] for i, c in enumerate(pick) if c < nb and cost[i][c] < big / 2}


def evaluate(attackers, bases, dist, plan, pct, rng, n=MC, reserves=True, free=False):
    """Tira el plan muchas veces. Las reservas rematan lo que haya fallado, siempre de su puesto hacia abajo.
    Con `free`, además, van a por estrellas en cualquier aldea libre: un ataque no usado no da nada."""
    rest = [i for i in range(len(attackers)) if i not in plan] if reserves else []
    start = [b.get("best", 0) for b in bases]
    cums = [[list(accumulate(p)) for p in row] for row in dist]
    triples, stars, totals = 0.0, 0.0, []
    items = list(plan.items())
    for _ in range(n):
        best = list(start)
        for i, j in items:
            r, c = rng.random(), cums[i][j]
            s = 0 if r < c[0] else 1 if r < c[1] else 2 if r < c[2] else 3
            if s > best[j]:
                best[j] = s
        for i in rest:
            top, pick = 0.0, None
            for j in range(len(bases)):
                if best[j] >= 3 or (not free and (bases[j].get("pos") or 0) < (attackers[i].get("pos") or 0)):
                    continue
                g = _gain(dist[i][j], best[j])
                if g > top:
                    top, pick = g, j
            if pick is not None and top > .15:
                r, c = rng.random(), cums[i][pick]
                s = 0 if r < c[0] else 1 if r < c[1] else 2 if r < c[2] else 3
                if s > best[pick]:
                    best[pick] = s
        total = sum(best)
        totals.append(total)
        stars += total
        triples += sum(1 for x in best if x == 3)
    totals.sort()
    return {"triples": round(triples / n, 1), "stars": round(stars / n, 1), "lo": totals[int(.1 * (n - 1))], "hi": totals[int(.9 * (n - 1))]}


def mirror(attackers, bases):
    """Espejo: cada cuenta a la aldea de su mismo puesto."""
    by = {b.get("pos"): j for j, b in enumerate(bases) if b.get("best", 0) < 3}
    return {i: by[a.get("pos")] for i, a in enumerate(attackers) if a.get("pos") in by}


def _tier(p, tau):
    return "seguro" if p >= ALMOST else "razonable" if p >= tau else "dudoso"


def _shape(plan, attackers, bases):
    if not plan:
        return "none"
    gaps = [(bases[j].get("pos") or 0) - (attackers[i].get("pos") or 0) for i, j in plan.items()]
    if all(g == 0 for g in gaps):
        return "espejo"
    return "bajada" if min(gaps) >= 0 and len(set(gaps)) == 1 else "mixto"


def build(prob, attackers, bases, size, cwl=True, seed=0, stars_now=0):
    """Plan completo de una guerra. `attackers`: cuentas que aún pueden atacar. `bases`: aldeas con `best` (estrellas ya
    logradas) y `touched` (ya atacada). Todo con su puesto en `pos`."""
    rng = random.Random(seed)
    attackers = sorted(attackers, key=lambda a: a.get("pos") or 99)
    bases = sorted(bases, key=lambda b: b.get("pos") or 99)
    dist = grid(prob, attackers, bases, size, cwl)
    pct = prob.pct
    empty = {"assign": [], "reserves": [], "uncovered": [], "tau": None, "triples": 0, "stars": 0, "lo": 0, "hi": 0, "shape": "none", "matrix": _matrix(attackers, bases, dist), "stars_now": stars_now,
             "mirror": {"triples": 0, "stars": 0}, "best_stars": {"triples": 0, "stars": 0}, "stars_free": 0, "triples_free": 0, "done": sum(1 for b in bases if b.get("best", 0) >= 3)}
    if not attackers or all(b.get("best", 0) >= 3 for b in bases):
        return empty
    # reparto con más plenos: esa es la referencia. La nota de corte es la más exigente que apenas pierde plenos
    def worth(p_):
        return sum(dist[i][j][3] for i, j in p_.items())
    plan = assign(attackers, bases, dist, floor=FLOOR)
    ref, tau = worth(plan), FLOOR
    for t in (.9, .85, .8, .75, .7, .65, .6, .55, .5, .45, .4, .35, .3):
        cand = assign(attackers, bases, dist, floor=t)
        if worth(cand) >= ref * (1 - GIVE_UP):
            tau, plan = t, cand
            break
    ev = evaluate(attackers, bases, dist, plan, pct, rng)
    extra = evaluate(attackers, bases, dist, plan, pct, rng, free=True)
    ev_mirror = evaluate(attackers, bases, dist, mirror(attackers, bases), pct, rng, reserves=False)
    ev_stars = evaluate(attackers, bases, dist, assign(attackers, bases, dist, up=True, value="stars"), pct, rng, reserves=False)
    rows = []
    for i, j in sorted(plan.items(), key=lambda kv: attackers[kv[0]].get("pos") or 99):
        a, b, p = attackers[i], bases[j], dist[i][j]
        rows.append({"a_pos": a.get("pos"), "a": a["name"], "a_tag": a["tag"], "a_th": a["th"], "b_pos": b.get("pos"), "b": b["name"], "b_tag": b["tag"], "b_th": b["th"], "best": b.get("best", 0),
                     "p3": round(p[3], 3), "p2": round(p[2], 3), "stars": round(_gain(p, b.get("best", 0)) + b.get("best", 0), 2), "tier": _tier(p[3], tau), "why": _why(prob, a, b)})
    used = set(plan.values())
    reserves = []
    for i, a in enumerate(attackers):
        if i in plan:
            continue
        covers = sorted(((dist[i][j][3], j) for j in used if (bases[j].get("pos") or 0) >= (a.get("pos") or 0)), reverse=True)[:3]
        reserves.append({"pos": a.get("pos"), "name": a["name"], "th": a["th"], "covers": [{"pos": bases[j].get("pos"), "p3": round(p, 2)} for p, j in covers if p >= .2]})
    uncovered = [{"pos": b.get("pos"), "name": b["name"], "th": b["th"], "best": b.get("best", 0)} for j, b in enumerate(bases) if j not in used and b.get("best", 0) < 3]
    return {**empty, "assign": rows, "reserves": reserves, "uncovered": uncovered, "tau": tau, "shape": _shape(plan, attackers, bases), "triples": ev["triples"], "stars": ev["stars"], "lo": ev["lo"], "hi": ev["hi"],
            "mirror": ev_mirror, "best_stars": ev_stars, "stars_free": extra["stars"], "triples_free": extra["triples"]}


def _why(prob, a, b):
    """Los datos que explican el %: se enseñan para que cada cual saque sus conclusiones."""
    x, y = prob.recent_a.get(a["tag"]), prob.recent_d.get(b["tag"])
    return {"a_n": x[0] if x else 0, "a_3": x[1] if x else 0, "d_n": y[0] if y else 0, "d_3": y[1] if y else 0, "skill": round(prob.ua.get(a["tag"], 0.0) + 3 * prob.form_a.get(a["tag"], 0.0), 2),
            "hard": round(-(prob.ud.get(b["tag"], 0.0) + 2 * prob.form_d.get(b["tag"], 0.0)), 2)}


def _matrix(attackers, bases, dist):
    return {"a": [{"pos": a.get("pos"), "name": a["name"], "th": a["th"]} for a in attackers], "b": [{"pos": b.get("pos"), "name": b["name"], "th": b["th"], "best": b.get("best", 0)} for b in bases],
            "p3": [[round(p[3] * 100) for p in row] for row in dist]}

"""Plan de ataque: quién ataca a quién para conseguir el mayor número de plenos.

Se calcula el % de pleno de cada cuenta contra cada aldea y se busca el reparto con más plenos esperados, con dos reglas:
- Cada cuenta ataca una vez y cada aldea recibe un solo ataque del plan.
- Nadie ataca por encima de su puesto: el 5 puede ir al 5 o más abajo, nunca al 3.

Por eso el resultado sale solo, sin decidirlo de antemano: si el 12 ya hace pleno probable al 15, se baja a todos; si lo
que da más plenos es el espejo, sale espejo. Quien se queda sin aldea no pierde nada: queda de reserva para rematar
una aldea que haya fallado. La nota de corte tampoco es fija: es la más exigente que no sacrifica plenos esperados.

Además se calcula una alternativa: el mismo reparto, pero dejando subir a quien lo necesita si el conjunto gana. Si el 3
pierde 3 puntos por bajar al 5 y el 5 gana 9 por subir al 4, salen 6 a favor. Cada subida debe ganar más que el margen de
error del modelo, para no mover a nadie por una diferencia que podría no existir. Compensa o no lo decide la comparación
de las dos versiones, y se enseña con sus números para que quien manda elija.
"""
import math
import random

from collections import defaultdict
from itertools import accumulate

ALMOST = .85              # a partir de aquí se llama «casi seguro»
GIVE_UP = .015            # parte de los plenos esperados que se acepta perder por evitar ataques dudosos
FLOOR = .25               # por debajo no se considera un intento de pleno
CUTS = (.9, .85, .8, .75, .7, .65, .6, .55, .5, .45, .4, .35, .3)
UP_MARGIN = .02           # margen de una subida si aún no se ha podido medir el error del modelo
MC = 400
MC_CMP = 1500             # para comparar dos repartos hace falta afinar más


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


def assign(attackers, bases, dist, floor=0.0, up=False, value="triples", up_cost=0.0):
    """El mejor reparto. value: «triples» busca plenos, «stars» estrellas. Empates: atacante más débil, para reservar al fuerte.
    `up` deja atacar por encima del propio puesto, pagando `up_cost` por cada subida. Nadie repite aldea (dos ataques por guerra)."""
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
            climbs = (b.get("pos") or 0) < (a.get("pos") or 0)
            ok = (up or not climbs) and p[3] >= floor and b.get("tag") not in (a.get("hit") or ())
            v = (p[3] + .02 * _gain(p, b.get("best", 0)) / 3) if value == "triples" else _gain(p, b.get("best", 0)) + .02 * p[3]
            row.append(-(v - (up_cost if climbs else 0.0) + .0005 * (a.get("pos") or 0)) if ok else big)
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
    triples, stars, totals, plenos = 0.0, 0.0, [], []
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
        plenos.append(sum(1 for x in best if x == 3))
    totals_ = sorted(totals)
    triples = sum(plenos) / n
    return {"triples": round(triples, 2), "stars": round(stars / n, 2), "lo": totals_[int(.1 * (n - 1))], "hi": totals_[int(.9 * (n - 1))],
            "se_t": _se(plenos), "se_s": _se(totals)}


def _se(v):
    """Error de la media de una tirada: sirve para no llamar mejora a lo que solo es azar."""
    m = sum(v) / len(v)
    return (sum((x - m) ** 2 for x in v) / max(len(v) - 1, 1) / len(v)) ** .5


def mirror(attackers, bases):
    """Espejo: cada cuenta a la aldea de su mismo puesto."""
    by = {b.get("pos"): j for j, b in enumerate(bases) if b.get("best", 0) < 3}
    out = {}
    for i, a in enumerate(attackers):       # con dos ataques por guerra, el espejo solo gasta uno
        j = by.get(a.get("pos"))
        if j is not None and j not in out.values():
            out[i] = j
    return out


def _tier(p, tau):
    return "seguro" if p >= ALMOST else "razonable" if p >= tau else "dudoso"


def _shape(plan, attackers, bases):
    if not plan:
        return "none"
    gaps = [(bases[j].get("pos") or 0) - (attackers[i].get("pos") or 0) for i, j in plan.items()]
    if all(g == 0 for g in gaps):
        return "espejo"
    return "bajada" if min(gaps) >= 0 and len(set(gaps)) == 1 else "mixto"


def _margin(prob):
    """Lo que una subida debe ganar para tomarla en serio: el error medio del modelo, medido con ataques futuros."""
    v = (getattr(prob, "info", None) or {}).get("calib")
    return UP_MARGIN if v is None else max(v, .005)


def _swaps(attackers, bases, dist, main, alt):
    """Qué cambia de un reparto a otro, en grupos: quien cede una aldea va junto a quien la recibe."""
    moved = sorted(i for i in set(main) | set(alt) if main.get(i) != alt.get(i))
    parent = {i: i for i in moved}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    owner = {}
    for i in moved:
        for j in (main.get(i), alt.get(i)):
            if j is not None:
                parent[find(i)] = find(owner.setdefault(j, i))
    groups = defaultdict(list)
    for i in moved:
        groups[find(i)].append(i)
    out = []
    for ids in groups.values():
        rows = []
        for i in ids:
            a, was, now = attackers[i], main.get(i), alt.get(i)
            rows.append({"pos": a.get("pos"), "name": a["name"], "was": bases[was].get("pos") if was is not None else None, "now": bases[now].get("pos") if now is not None else None,
                         "p_was": round(dist[i][was][3], 3) if was is not None else None, "p_now": round(dist[i][now][3], 3) if now is not None else None,
                         "up": now is not None and (bases[now].get("pos") or 0) < (a.get("pos") or 0)})
        out.append({"rows": rows, "net": round(sum((r["p_now"] or 0) - (r["p_was"] or 0) for r in rows), 3)})
    return sorted(out, key=lambda s: -s["net"])


def _verdict(base, alt):
    """¿Sale más rentable? Solo si la diferencia supera el azar de las tiradas."""
    dt, ds = alt["triples"] - base["triples"], alt["stars"] - base["stars"]
    nt, ns = 2 * math.hypot(base["se_t"], alt["se_t"]), 2 * math.hypot(base["se_s"], alt["se_s"])
    if (dt > nt and ds >= -ns) or (ds > ns and dt >= -nt):
        return "mejor"
    if dt > nt or ds > ns:
        return "mezcla"       # gana en una cosa y pierde en la otra
    return "igual"


def build(prob, attackers, bases, size, cwl=True, seed=0, stars_now=0):
    """Plan completo de una guerra. `attackers`: un elemento por ataque que aún se puede usar (`hit`: aldeas que esa cuenta
    ya atacó). `bases`: aldeas con `best` (estrellas ya logradas) y `touched` (ya atacada). Todo con su puesto en `pos`."""
    rng = random.Random(seed)
    attackers = sorted(attackers, key=lambda a: a.get("pos") or 99)
    bases = sorted(bases, key=lambda b: b.get("pos") or 99)
    dist = grid(prob, attackers, bases, size, cwl)
    pct = prob.pct
    empty = {"assign": [], "reserves": [], "uncovered": [], "tau": None, "triples": 0, "stars": 0, "lo": 0, "hi": 0, "shape": "none", "matrix": _matrix(attackers, bases, dist), "stars_now": stars_now,
             "mirror": {"triples": 0, "stars": 0}, "best_stars": {"triples": 0, "stars": 0}, "stars_free": 0, "triples_free": 0, "done": sum(1 for b in bases if b.get("best", 0) >= 3), "alt": None}
    if not attackers or all(b.get("best", 0) >= 3 for b in bases):
        return empty
    # reparto con más plenos: esa es la referencia. La nota de corte es la más exigente que apenas pierde plenos
    def worth(p_):
        return sum(dist[i][j][3] for i, j in p_.items())
    plan = assign(attackers, bases, dist, floor=FLOOR)
    ref, tau = worth(plan), FLOOR
    for t in CUTS:
        cand = assign(attackers, bases, dist, floor=t)
        if worth(cand) >= ref * (1 - GIVE_UP):
            tau, plan = t, cand
            break
    ev = evaluate(attackers, bases, dist, plan, pct, rng)
    extra = evaluate(attackers, bases, dist, plan, pct, rng, free=True)
    ev_mirror = evaluate(attackers, bases, dist, mirror(attackers, bases), pct, rng, reserves=False)
    ev_stars = evaluate(attackers, bases, dist, assign(attackers, bases, dist, up=True, value="stars"), pct, rng, reserves=False)
    def rows_of(p_):
        rows = []
        for i, j in sorted(p_.items(), key=lambda kv: (attackers[kv[0]].get("pos") or 99, kv[1])):
            a, b, p = attackers[i], bases[j], dist[i][j]
            rows.append({"a_pos": a.get("pos"), "a": a["name"], "a_tag": a["tag"], "a_th": a["th"], "b_pos": b.get("pos"), "b": b["name"], "b_tag": b["tag"], "b_th": b["th"], "best": b.get("best", 0),
                         "p3": round(p[3], 3), "p2": round(p[2], 3), "stars": round(_gain(p, b.get("best", 0)) + b.get("best", 0), 2), "tier": _tier(p[3], tau), "why": _why(prob, a, b), "up": (b.get("pos") or 0) < (a.get("pos") or 0)})
        return rows

    def rest_of(p_):
        used, reserves, seen = set(p_.values()), [], {}
        for i, a in enumerate(attackers):
            if i in p_:
                continue
            if a["tag"] in seen:            # sus dos ataques libres: una sola línea
                seen[a["tag"]]["n"] += 1
                continue
            covers = sorted(((dist[i][j][3], j) for j in used if (bases[j].get("pos") or 0) >= (a.get("pos") or 0)), reverse=True)[:3]
            seen[a["tag"]] = {"pos": a.get("pos"), "name": a["name"], "th": a["th"], "n": 1, "covers": [{"pos": bases[j].get("pos"), "p3": round(p, 2)} for p, j in covers if p >= .2]}
            reserves.append(seen[a["tag"]])
        uncovered = [{"pos": b.get("pos"), "name": b["name"], "th": b["th"], "best": b.get("best", 0)} for j, b in enumerate(bases) if j not in used and b.get("best", 0) < 3]
        return reserves, uncovered
    reserves, uncovered = rest_of(plan)
    out = {**empty, "assign": rows_of(plan), "reserves": reserves, "uncovered": uncovered, "tau": tau, "shape": _shape(plan, attackers, bases), "triples": ev["triples"], "stars": ev["stars"], "lo": ev["lo"], "hi": ev["hi"],
           "mirror": ev_mirror, "best_stars": ev_stars, "stars_free": extra["stars"], "triples_free": extra["triples"]}
    # la alternativa parte de las mismas notas: lo único nuevo es poder subir cuando el conjunto gana
    margin = _margin(prob)
    other = assign(attackers, bases, dist, floor=tau, up=True, up_cost=margin)
    if other != plan and any((bases[j].get("pos") or 0) < (attackers[i].get("pos") or 0) for i, j in other.items()):
        same = random.Random(f"{seed}|cmp")
        cmp_base = evaluate(attackers, bases, dist, plan, pct, same, n=MC_CMP)
        cmp_alt = evaluate(attackers, bases, dist, other, pct, same, n=MC_CMP)
        extra_alt = evaluate(attackers, bases, dist, other, pct, rng, free=True)
        res_alt, unc_alt = rest_of(other)
        out["alt"] = {"assign": rows_of(other), "reserves": res_alt, "uncovered": unc_alt, "shape": _shape(other, attackers, bases), "triples": cmp_alt["triples"], "stars": cmp_alt["stars"], "lo": cmp_alt["lo"], "hi": cmp_alt["hi"],
                      "stars_free": extra_alt["stars"], "triples_free": extra_alt["triples"], "swaps": _swaps(attackers, bases, dist, plan, other), "ups": sum(1 for i, j in other.items() if (bases[j].get("pos") or 0) < (attackers[i].get("pos") or 0)),
                      "verdict": _verdict(cmp_base, cmp_alt), "base": {k: cmp_base[k] for k in ("triples", "stars", "lo", "hi")}, "gain_t": round(cmp_alt["triples"] - cmp_base["triples"], 2),
                      "gain_s": round(cmp_alt["stars"] - cmp_base["stars"], 2), "margin": round(margin, 3)}
    return out


def _why(prob, a, b):
    """Los datos que explican el %: se enseñan para que cada cual saque sus conclusiones."""
    x, y = prob.recent_a.get(a["tag"]), prob.recent_d.get(b["tag"])
    return {"a_n": x[0] if x else 0, "a_3": x[1] if x else 0, "d_n": y[0] if y else 0, "d_3": y[1] if y else 0, "skill": round(prob.ua.get(a["tag"], 0.0) + 3 * prob.form_a.get(a["tag"], 0.0), 2),
            "hard": round(-(prob.ud.get(b["tag"], 0.0) + 2 * prob.form_d.get(b["tag"], 0.0)), 2)}


def _matrix(attackers, bases, dist):
    seen = {}
    for i, a in enumerate(attackers):       # con dos ataques libres la cuenta sale una sola vez
        seen.setdefault(a["tag"], i)
    keep = list(seen.values())
    return {"a": [{"pos": attackers[i].get("pos"), "name": attackers[i]["name"], "th": attackers[i]["th"]} for i in keep], "b": [{"pos": b.get("pos"), "name": b["name"], "th": b["th"], "best": b.get("best", 0)} for b in bases],
            "p3": [[round(p[3] * 100) for p in dist[i]] for i in keep]}

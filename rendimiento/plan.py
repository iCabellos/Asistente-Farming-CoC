"""Plan de ataque: quién ataca a quién para sacar el máximo de estrellas (o de plenos).

Se calcula el reparto de estrellas (0, 1, 2 o 3) de cada ataque contra cada aldea y se busca el mejor reparto 1 contra 1:
- Cada aldea recibe UN solo ataque. Atacar dos veces la misma aldea no tiene sentido: solo cuenta la mejor nota, así que
  el segundo ataque gastaría una oportunidad que esa cuenta puede aprovechar en otra aldea.
- Cada aldea recibe rival si compensa: gana el reparto que más suma entero, así que no se gasta un ataque fuerte en
  cubrir una aldea difícil si rinde mucho más en otra. Viable no depende del TH sino de lo que se espera de ese
  ataque, con el historial de la cuenta y de la aldea (últimos 10 ataques y defensas, ver modelo.evidence): al menos
  MIN_P3 de pleno o lo más probable 2★. Si para una aldea no queda nadie viable, se queda sin rival.
- En guerra normal cada cuenta tiene dos ataques; en liga, uno. Como hay más ataques que aldeas, el cálculo decide cuáles
  se usan: normalmente atacan dos veces las cuentas de arriba y las de abajo no, pero si una cuenta de la parte media-baja
  saca más estrellas a una aldea media que una de la parte media, va ella.

Con un ataque por aldea el total es la suma de lo que vale cada pareja ataque-aldea, así que el mejor reparto es una
asignación: el algoritmo húngaro lo da exacto, sin aproximaciones.

Salen dos planes distintos, cada uno en su apartado:
- Plan 1, mejores ataques para ganar: entran los dos ataques de cada cuenta y se decide quién ataca y a quién. Se
  calculan varios repartos (más estrellas, más atrevido, más plenos, más seguro) y cada uno se juega cientos de veces
  contra lo que se espera del rival. Gana el que más veces gana la guerra; si ninguno supera el azar de las tiradas, el
  de más estrellas.
- Plan 2, todos atacan: el primer ataque de cada cuenta va contra su mejor rival, una aldea distinta para cada una y
  solo donde tiene opciones reales. Quien no tiene ninguna aldea propia a su alcance va a la que mejor se le da, aunque
  la comparta: nunca se manda a nadie a una aldea de arriba para cubrirla. El segundo ataque se reparte después para
  ganar la guerra, con las mismas reglas que el plan 1.

Cada ataque empieza de cero: no hereda nada de lo que hizo otro en esa aldea. Por eso un ataque solo se planea si esa
cuenta, por sí sola, puede mejorar lo que la aldea ya tiene (`worth`). No existe «rascar algo» donde no hay opciones.

Atacar por encima del propio puesto se permite si las cuentas lo piden, pero cada subida debe ganar más que el error
medio del modelo: no se mueve a nadie por una diferencia que podría no existir.
"""
import math
import random

from collections import defaultdict
from itertools import accumulate

ALMOST = .85              # a partir de aquí se llama «casi seguro»
LIKELY = .5               # pleno más probable que no
W_T = .05                 # lo que vale un pleno además de sus 3 estrellas: desempata a su favor
W_S = .05                 # en el reparto de más plenos, lo que vale cada estrella: solo desempata
UP_MARGIN = .02           # margen de una subida si aún no se ha podido medir el error del modelo
MIN_P3 = .10              # un ataque es viable si tiene al menos este % de pleno...
MIN_P2 = .50              # ...o si lo más probable es que haga 2★ o más
MIN_UP = .25              # sobre una aldea ya atacada, el ataque se planea si esa cuenta sola tiene este % de mejorarla
FORCE = 10.0              # en el plan 2, lo que vale que una cuenta ataque: más que cualquier diferencia de estrellas
W_BOLD = .75              # reparto atrevido: lo que vale un pleno además de sus 3 estrellas
MC = 400
MC_CMP = 1500             # para comparar dos repartos hace falta afinar más
MC_WIN = 600              # tiradas de cada reparto candidato a ganar la guerra
STYLES = ("stars", "bold", "triples", "safe")


def _hungarian(cost):
    """Asignación de coste mínimo: una columna distinta para cada fila (filas <= columnas)."""
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


def grid(prob, attackers, bases, size, cwl=True, used=False):
    """Reparto de estrellas de cada cuenta contra cada aldea, tal como están ahora. Con `used`, como si todas las aldeas
    estuvieran ya atacadas: es lo que se encuentra un remate."""
    rows = {}
    for a in attackers:                     # con dos ataques la cuenta sale dos veces: se calcula una
        if a["tag"] not in rows:
            rows[a["tag"]] = [prob.dist(a, b, fresh=not (used or b.get("touched") or b.get("best", 0)), cwl=cwl, size=size) for b in bases]
    return [rows[a["tag"]] for a in attackers]


def _gain(p, best):
    return sum(p[s] * max(0, s - best) for s in range(4))


def value(p, best, goal="stars"):
    """Lo que vale una pareja ataque-aldea: estrellas que añade sobre las que ya tiene la aldea (y un poco por pleno).
    Con goal="triples", la probabilidad de pleno (y un poco por estrella); con "bold", estrellas y un buen extra por
    pleno; con "safe", solo cuenta llegar a 2★ (y un poco lo demás)."""
    if best >= 3:
        return 0.0
    g = _gain(p, best)
    if goal == "triples":
        return p[3] + W_S * g
    if goal == "bold":
        return g + W_BOLD * p[3]
    if goal == "safe":
        return sum(p[s] * max(0, min(s, 2) - min(best, 2)) for s in range(4)) + W_S * g
    return g + W_T * p[3]


def _up(a, b):
    return (b.get("pos") or 0) < (a.get("pos") or 0)


def viable(p):
    """¿Tiene sentido ese ataque? Se mira su reparto de estrellas, que ya lleva el historial de los dos (ver
    modelo.evidence): si un TH18 fuerte solo le hizo 2★ a esa aldea, un TH11 no tiene opciones; si un TH12 le hizo pleno
    a un TH18 rusheado, un TH12 sí. Un ataque sin opciones no se planea, aunque la aldea se quede sin rival."""
    return p[3] >= MIN_P3 or p[2] + p[3] >= MIN_P2


def worth(p, best=0):
    """¿Puede ese ataque, por sí solo, mejorar lo que ya tiene la aldea? Cada ataque empieza de cero, así que da igual
    lo que hiciera el anterior: o esta cuenta es capaz de sacar más estrellas que las que hay, o no pinta nada ahí."""
    if best <= 0:
        return viable(p)
    return sum(p[best + 1:]) >= MIN_UP


def optimize(attackers, bases, dist, up=True, up_cost=0.0, goal="stars", rows=None, skip=(), force=False):
    """El mejor reparto 1 contra 1: {ataque: aldea}, cada aldea con un único ataque, el que más suma en total. No se fuerza
    a cubrir todas: si para una aldea difícil haría falta un ataque que rinde mucho más en otra (un 39 % en el TH18 frente
    a un 98 % en otra aldea), sale más a cuenta dejarla. Un ataque sin opciones reales nunca entra.
    `rows` limita los ataques que entran y `skip` las aldeas que no. Con `force` se busca primero que ataquen cuantas más
    cuentas mejor (plan 2), pero siempre a una aldea donde tengan opciones."""
    rows = list(range(len(attackers))) if rows is None else list(rows)
    free = [j for j, b in enumerate(bases) if b.get("best", 0) < 3 and j not in skip]
    if not rows or not free:
        return {}
    big = 1e6

    def cell(i, j):
        a, b = attackers[i], bases[j]
        if b.get("tag") in (a.get("hit") or ()) or (not up and _up(a, b)) or not worth(dist[i][j], b.get("best", 0)):
            return big                              # ya la atacó esa cuenta, no puede subir o no tiene opciones
        return -(value(dist[i][j], b.get("best", 0), goal) - (up_cost if _up(a, b) else 0.0)) - (FORCE if force else 0.0)
    # filas: ataques; columnas: aldeas y, además, una «sin atacar» por ataque. Así no se obliga a cubrir una aldea si el
    # ataque que haría falta rinde más en otra: gana el reparto que más suma entero
    n = len(rows)
    cost = [[cell(i, j) for j in free] + [0.0] * n for i in rows]
    pick = _hungarian(cost)
    return {rows[r]: free[c] for r, c in enumerate(pick) if 0 <= c < len(free) and cost[r][c] < 0}


def train(attackers, bases, dist, up_cost=0.0, goal="stars"):
    """Plan 2, todos atacan: ({ataque: aldea}, fase de cada ataque, ataques que se reparten después, los que comparten).
    Fase 1: el primer ataque de cada cuenta que aún no ha atacado, contra su mejor rival: una aldea distinta para cada
    una y solo donde tiene opciones. Quien se queda sin aldea propia va a la que mejor se le da, aunque la comparta con
    otra cuenta: no se le manda a una aldea de arriba para cubrirla.
    Fase 2: el segundo ataque de quien ya hizo el primero, repartido con `goal` como en el plan 1 entre las aldeas que no
    esperan ya un primer ataque. El de los demás se reparte cuando hayan atacado."""
    first, second, seen = [], [], set()
    for i, a in enumerate(attackers):
        if not a.get("hit") and a["tag"] not in seen:
            seen.add(a["tag"])
            first.append(i)
        else:
            second.append(i)
    one = optimize(attackers, bases, dist, up=True, up_cost=up_cost, goal="stars", rows=first, force=True)
    lone = {}
    for i in first:
        if i in one:
            continue
        opts = [(_gain(dist[i][j], b.get("best", 0)), b.get("pos") or 0, j) for j, b in enumerate(bases) if b.get("best", 0) < 3]
        if opts and max(opts)[0] > 0:
            lone[i] = max(opts)[2]              # a igualdad, la aldea más baja
    waiting = set(one.values()) | set(lone.values())
    now = [i for i in second if attackers[i].get("hit")]
    two = optimize(attackers, bases, dist, up=True, up_cost=up_cost, goal=goal, rows=now, skip=waiting)
    plan = {**one, **lone, **two}
    return plan, {**{i: 1 for i in one}, **{i: 1 for i in lone}, **{i: 2 for i in two}}, [i for i in range(len(attackers)) if i not in plan], set(lone)


def assign(attackers, bases, dist, floor=0.0, up=False, value="stars", up_cost=0.0):
    """Compatibilidad: el reparto óptimo (ya no hay nota de corte; `floor` se ignora)."""
    return optimize(attackers, bases, dist, up=up, up_cost=up_cost, goal="triples" if value == "triples" else "stars")


def evaluate(attackers, bases, dist, plan, rng=None, n=MC):
    """Tira el plan muchas veces: cada ataque contra su aldea, y nada más."""
    rng = rng or random.Random(0)
    start = [b.get("best", 0) for b in bases]
    cums = {i: list(accumulate(dist[i][j])) for i, j in plan.items()}
    stars, totals, plenos = 0.0, [], []
    for _ in range(n):
        best = list(start)
        for i, j in plan.items():
            r, c = rng.random(), cums[i]
            s = 0 if r < c[0] else 1 if r < c[1] else 2 if r < c[2] else 3
            if s > best[j]:
                best[j] = s
        total = sum(best)
        totals.append(total)
        stars += total
        plenos.append(sum(1 for x in best if x == 3))
    totals_ = sorted(totals)
    return {"triples": round(sum(plenos) / n, 2), "stars": round(stars / n, 2), "lo": totals_[int(.1 * (n - 1))], "hi": totals_[int(.9 * (n - 1))],
            "se_t": _se(plenos), "se_s": _se(totals)}


def expected(attackers, bases, dist, plan):
    """Lo mismo que `evaluate` pero exacto (sin azar): estrellas y plenos esperados."""
    st = sum(bases[j].get("best", 0) for j in range(len(bases)))
    st += sum(_gain(dist[i][j], bases[j].get("best", 0)) for i, j in plan.items())
    tr = sum(1 for b in bases if b.get("best", 0) >= 3) + sum(dist[i][j][3] for i, j in plan.items() if bases[j].get("best", 0) < 3)
    return st, tr


def play(attackers, bases, dist, plan, later=(), used=None, n=MC, seed=0, rival=None):
    """Tira el plan muchas veces y, después, atacan los de `later`: cada uno, del más alto al más bajo, va a la aldea
    donde más estrellas espera sumar tal como ha quedado, y solo si él solo puede mejorarla (`worth`). Con `rival` (estrellas finales del rival en sus propias
    tiradas) dice además cuántas veces se gana la guerra; el empate a estrellas cuenta media victoria.
    La misma semilla da a cada ataque los mismos dados: así dos repartos se comparan con la misma suerte."""
    rng = random.Random(str(seed))
    na, start = len(attackers), [b.get("best", 0) for b in bases]
    cum = lambda d: (d[0], d[0] + d[1], d[0] + d[1] + d[2])
    cums = {i: cum(dist[i][j]) for i, j in plan.items()}
    later = sorted(later, key=lambda i: attackers[i].get("pos") or 99)
    aimed = set(plan.values())
    opts, twin = {}, {}
    for i in later:
        a = attackers[i]
        ban = {j for j, b in enumerate(bases) if b.get("tag") in (a.get("hit") or ())} | {j for k, j in plan.items() if attackers[k]["tag"] == a["tag"]}
        row = []
        for j, b in enumerate(bases):
            if start[j] >= 3 or j in ban:
                continue
            d = used[i][j] if used is not None and (j in aimed or b.get("touched") or start[j]) else dist[i][j]
            row.append((j, cum(d), tuple(sum(d[s] * max(0, s - x) for s in range(4)) if worth(d, x) else 0.0 for x in range(3))))
        opts[i] = row
        twin[i] = next((k for k in later if k != i and attackers[k]["tag"] == a["tag"]), None)
    odds = None
    if rival:
        r, top = sorted(rival), 3 * len(bases)
        odds, lo, hi = [], 0, 0
        for t in range(top + 1):                 # P(rival < t) + la mitad de P(rival = t)
            while lo < len(r) and r[lo] < t:
                lo += 1
            while hi < len(r) and r[hi] <= t:
                hi += 1
            odds.append((lo + (hi - lo) / 2) / len(r))
    listed, plenos, final, plenos_f, wins = [], [], [], [], []
    for _ in range(n):
        u = [rng.random() for _ in range(2 * na)]
        best = list(start)
        for i, j in plan.items():
            r, c = u[i], cums[i]
            s = 0 if r < c[0] else 1 if r < c[1] else 2 if r < c[2] else 3
            if s > best[j]:
                best[j] = s
        listed.append(sum(best))
        plenos.append(best.count(3))
        went = {}
        for i in later:
            top, pick, pc, no = 0.0, None, None, went.get(twin[i])
            for j, c, g in opts[i]:
                x = best[j]
                if x < 3 and j != no and g[x] > top:
                    top, pick, pc = g[x], j, c
            if pick is None:
                continue
            went[i] = pick
            r = u[na + i]
            s = 0 if r < pc[0] else 1 if r < pc[1] else 2 if r < pc[2] else 3
            if s > best[pick]:
                best[pick] = s
        t = sum(best)
        final.append(t)
        plenos_f.append(best.count(3))
        if odds:
            wins.append(odds[t])
    lo_, fin = sorted(listed), sorted(final)
    q = lambda v, p: v[int(p * (n - 1))]
    return {"triples": round(sum(plenos) / n, 2), "stars": round(sum(listed) / n, 2), "lo": q(lo_, .1), "hi": q(lo_, .9), "se_t": _se(plenos), "se_s": _se(listed),
            "final": {"stars": round(sum(final) / n, 2), "triples": round(sum(plenos_f) / n, 2), "lo": q(fin, .1), "hi": q(fin, .9)},
            "win": round(sum(wins) / n, 3) if odds else None, "_w": wins, "_f": final}


def _edge(base, other):
    """Lo que `other` gana a `base` y el azar de esa diferencia: en % de ganar la guerra si se conoce al rival, y si no en
    estrellas finales. Las tiradas van emparejadas, así que se mide la diferencia tirada a tirada."""
    x, y = (base["_w"], other["_w"]) if base["_w"] and other["_w"] else (base["_f"], other["_f"])
    d = [b - a for a, b in zip(x, y)]
    return sum(d) / len(d), 2 * _se(d)


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
        if j is not None and j not in out.values() and bases[j].get("tag") not in (a.get("hit") or ()):
            out[i] = j
    return out


def _tier(p3):
    return "seguro" if p3 >= ALMOST else "razonable" if p3 >= LIKELY else "dudoso"


def _goal(p):
    """A qué va ese ataque: a por el pleno, a por 2 estrellas o a sumar lo que pueda."""
    return 3 if p[3] >= LIKELY else 2 if p[2] + p[3] >= LIKELY else 1


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
                         "e_was": round(_gain(dist[i][was], 0), 2) if was is not None else None, "e_now": round(_gain(dist[i][now], 0), 2) if now is not None else None,
                         "up": was is not None and _up(a, bases[was])})
        out.append({"rows": rows, "net": round(sum((r["p_now"] or 0) - (r["p_was"] or 0) for r in rows), 3)})
    return sorted(out, key=lambda s: s["net"])


def _verdict(base, alt):
    """¿Qué cuesta el entrenamiento frente al plan de ganar? Solo se dice mejor o peor si supera el azar de las tiradas."""
    d, noise = _edge(base, alt)
    noise = max(noise, .005 if base["_w"] and alt["_w"] else .1)
    return "mejor" if d > noise else "peor" if d < -noise else "igual"


def build(prob, attackers, bases, size, cwl=True, seed=0, stars_now=0, rival=None):
    """Plan completo de una guerra. `attackers`: un elemento por ataque que aún se puede usar (`hit`: aldeas que esa cuenta
    ya atacó). `bases`: aldeas con `best` (estrellas ya logradas) y `touched` (ya atacada). Todo con su puesto en `pos`.
    `rival`: estrellas con las que acaba el rival en sus propias tiradas; sin él no se puede medir el % de ganar y la
    propuesta principal es el reparto de más estrellas."""
    attackers = sorted(attackers, key=lambda a: a.get("pos") or 99)
    bases = sorted(bases, key=lambda b: b.get("pos") or 99)
    dist = grid(prob, attackers, bases, size, cwl)
    open_ = [b for b in bases if b.get("best", 0) < 3]
    empty = {"assign": [], "reserves": [], "uncovered": [], "tau": None, "triples": 0, "stars": 0, "lo": 0, "hi": 0, "shape": "none", "matrix": _matrix(attackers, bases, dist), "stars_now": stars_now,
             "mirror": {"triples": 0, "stars": 0}, "best_stars": {"triples": 0, "stars": 0}, "stars_free": 0, "triples_free": 0, "done": sum(1 for b in bases if b.get("best", 0) >= 3), "alt": None,
             "covered": 0, "open": len(open_), "attacks": len(attackers), "goal": "win", "same": False, "win": None, "final": None, "style": "stars", "tried": []}
    if not attackers or not open_:
        return empty
    margin = _margin(prob)
    used = grid(prob, attackers, bases, size, cwl, used=True) if len(attackers) > 1 else None

    def rows_of(p_, phase=None, lone=()):
        rows = []
        for i, j in sorted(p_.items(), key=lambda kv: (attackers[kv[0]].get("pos") or 99, (phase or {}).get(kv[0], 1), bases[kv[1]].get("pos") or 99)):
            a, b, p = attackers[i], bases[j], dist[i][j]
            rows.append({"a_pos": a.get("pos"), "a": a["name"], "a_tag": a["tag"], "a_th": a["th"], "b_pos": b.get("pos"), "b": b["name"], "b_tag": b["tag"], "b_th": b["th"], "best": b.get("best", 0),
                         "p3": round(p[3], 3), "p2": round(p[2], 3), "stars": round(_gain(p, b.get("best", 0)) + b.get("best", 0), 2), "tier": _tier(p[3]), "goal": _goal(p),
                         "why": _why(prob, a, b), "up": _up(a, b), "phase": (phase or {}).get(i, 1), "lone": i in lone, "ok": worth(p, b.get("best", 0))})
        return rows

    def rest_of(p_):
        """Ataques que no se usan (una línea por cuenta) y aldeas sin rival por falta de ataques."""
        taken, reserves, seen = set(p_.values()), [], {}
        for i, a in enumerate(attackers):
            if i in p_:
                continue
            if a["tag"] in seen:
                seen[a["tag"]]["n"] += 1
                continue
            seen[a["tag"]] = {"pos": a.get("pos"), "name": a["name"], "th": a["th"], "n": 1, "uses": sum(1 for k in p_ if attackers[k]["tag"] == a["tag"])}
            reserves.append(seen[a["tag"]])
        uncovered = [{"pos": b.get("pos"), "name": b["name"], "th": b["th"], "best": b.get("best", 0)} for j, b in enumerate(bases) if j not in taken and b.get("best", 0) < 3]
        return reserves, uncovered

    def pack(p_, goal, ev, phase=None, lone=()):
        reserves, uncovered = rest_of(p_)
        return {"goal": goal, "assign": rows_of(p_, phase, lone), "reserves": reserves, "uncovered": uncovered, "shape": _shape(p_, attackers, bases), "triples": ev["triples"], "stars": ev["stars"],
                "lo": ev["lo"], "hi": ev["hi"], "stars_free": ev["stars"], "triples_free": ev["triples"], "covered": len(set(p_.values())), "ups": sum(1 for i, j in p_.items() if _up(attackers[i], bases[j])),
                "win": ev["win"], "final": ev["final"], "accounts": len({attackers[i]["tag"] for i in p_})}

    def roll(p_, later, n):
        return play(attackers, bases, dist, p_, later, used, n=n, seed=f"{seed}|cmp", rival=rival)

    rest = lambda p_: [i for i in range(len(attackers)) if i not in p_]
    # plan 1: el reparto de más estrellas y, si se conoce al rival, los que arriesgan o aseguran más. Se queda otro solo
    # si gana la guerra más veces de lo que explica el azar de las tiradas
    plan = optimize(attackers, bases, dist, up=True, up_cost=margin, goal="stars")
    style, tried = "stars", []
    if rival:
        base, seen = roll(plan, rest(plan), MC_WIN), [plan]
        tried.append({"style": "stars", "win": base["win"], "stars": base["final"]["stars"]})
        top = 0.0
        for g in STYLES[1:]:
            cand = optimize(attackers, bases, dist, up=True, up_cost=margin, goal=g)
            if cand in seen:
                continue
            seen.append(cand)
            ev_c = roll(cand, rest(cand), MC_WIN)
            tried.append({"style": g, "win": ev_c["win"], "stars": ev_c["final"]["stars"]})
            d, noise = _edge(base, ev_c)
            if d > max(noise, .005) and d > top:
                top, plan, style = d, cand, g
    ev = roll(plan, rest(plan), MC_CMP)
    ev_mirror = evaluate(attackers, bases, dist, mirror(attackers, bases), random.Random(seed))
    out = {**empty, **pack(plan, "win", ev), "mirror": ev_mirror, "best_stars": {"triples": ev["triples"], "stars": ev["stars"]}, "margin": round(margin, 3), "style": style, "tried": tried}
    # plan 2: todos atacan a su mejor rival; los segundos ataques ya disponibles se reparten para ganar, como en el plan 1
    drill, phase, later, lone = train(attackers, bases, dist, margin)
    if rival and 2 in phase.values():
        base, seen, top = roll(drill, later, MC_WIN), [drill], 0.0
        for g in STYLES[1:]:
            cand = train(attackers, bases, dist, margin, goal=g)
            if cand[0] in seen:
                continue
            seen.append(cand[0])
            d, noise = _edge(base, roll(cand[0], cand[2], MC_WIN))
            if d > max(noise, .005) and d > top:
                top, (drill, phase, later, lone) = d, cand
    out["same"] = drill == plan
    if drill:
        ev_o = roll(drill, later, MC_CMP)
        d, _ = _edge(ev, ev_o)
        out["alt"] = {**pack(drill, "train", ev_o, phase, lone), "swaps": _swaps(attackers, bases, dist, plan, drill), "verdict": _verdict(ev, ev_o), "base": {**{k: ev[k] for k in ("triples", "stars", "lo", "hi", "win")}, "final": ev["final"]},
                      "gain_t": round(ev_o["final"]["triples"] - ev["final"]["triples"], 2), "gain_s": round(ev_o["final"]["stars"] - ev["final"]["stars"], 2), "gain_w": round(d, 3) if rival else None, "margin": round(margin, 3),
                      "later": len(later), "first": sum(1 for v in phase.values() if v == 1), "second": sum(1 for v in phase.values() if v == 2), "lone": len(lone)}
    return out


def _why(prob, a, b):
    """Los datos que explican el %: se enseñan para que cada cual saque sus conclusiones."""
    x, y = prob.recent_a.get(a["tag"]), prob.recent_d.get(b["tag"])
    ev = prob.evidence(a, b) if hasattr(prob, "evidence") else {}
    return {"ev": ev, "a_n": x[0] if x else 0, "a_3": x[1] if x else 0, "d_n": y[0] if y else 0, "d_3": y[1] if y else 0, "skill": round(prob.ua.get(a["tag"], 0.0) + 3 * prob.form_a.get(a["tag"], 0.0), 2),
            "hard": round(-(prob.ud.get(b["tag"], 0.0) + 2 * prob.form_d.get(b["tag"], 0.0)), 2)}


def _matrix(attackers, bases, dist):
    seen = {}
    for i, a in enumerate(attackers):       # con dos ataques libres la cuenta sale una sola vez
        seen.setdefault(a["tag"], i)
    keep = list(seen.values())
    return {"a": [{"pos": attackers[i].get("pos"), "name": attackers[i]["name"], "th": attackers[i]["th"]} for i in keep], "b": [{"pos": b.get("pos"), "name": b["name"], "th": b["th"], "best": b.get("best", 0)} for b in bases],
            "p3": [[round(p[3] * 100) for p in dist[i]] for i in keep], "e": [[round(_gain(p, 0), 1) for p in dist[i]] for i in keep]}

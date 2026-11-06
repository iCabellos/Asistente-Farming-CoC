"""Motor de escenarios de la Liga de Guerras de Clanes.

Todo son funciones puras: reciben la liga normalizada y devuelven números, sin red ni base de datos, para poder
probarlas con cualquier clan, tamaño de guerra o momento de la temporada. clan.py baja los datos y guarda el resultado.

Reglas:
- Clasificación: estrellas de las guerras terminadas + 10 por victoria. Si empatan, gana quien más destrucción acumula.
- Una guerra la gana quien más estrellas hace; a igualdad, quien más destrucción. Si todo coincide no hay bonus.
- En una base sólo cuenta el mejor ataque, y cada cuenta ataca una vez.
- Los cruces son de todos contra todos: lo pendiente son las parejas que faltan, aunque aún no tengan ronda.

Tres preguntas, tres métodos:
- ¿Qué es seguro? Límites matemáticos (rank_bounds): el mejor y el peor caso posibles, sin suponer nada de cómo juega
  cada clan. Si dudan, se inclinan por «posible»: nunca marcan asegurado o descartado algo que no lo está.
- ¿Qué es probable? Simulación (simulate) con modelo.py, que da el % de cada resultado entre dos jugadores concretos.
- ¿Qué hacer? plan.py: el reparto de ataques con más plenos esperados.

Nada se ajusta a mano por liga o por clan: nivel, memoria, puntería, asistencia y dispersión salen de los datos.
"""
import math
import random
import statistics
from itertools import product

import modelo
import plan as planner

WIN_BONUS = 10
BONUS_LIMIT = 10          # hasta estas guerras pendientes se prueban todos los ganadores; con más se asume el peor caso
GAME_SIMS = 300
SEASON_SIMS = 4000
HIST_SIMS = 120
PRACTICAL = .005          # por debajo de este margen en miles de simulaciones se da por resuelto en la práctica
MIN_INACTIVE_WARS = 3     # sin atacar en tantas guerras seguidas se da por hecho que no atacará
USE_PRIOR_WEIGHT = 2      # peso de la media del clan frente al historial de la cuenta
SHIFTS = (-1.28, -.52, 0.0, .52, 1.28)   # cinco tipos de día, de muy malo a muy bueno, igual de probables


# ---------------- estructura ----------------
def normalize(group, wars, us, league=None):
    """Convierte las respuestas de la API en la liga con la que trabaja el resto del módulo."""
    clans = [{"tag": c["tag"], "name": c.get("name") or c["tag"],
              "roster": [{"tag": m["tag"], "name": m.get("name") or m["tag"], "th": m.get("townHallLevel") or m.get("townhallLevel") or 1}
                         for m in c.get("members") or []]} for c in group.get("clans") or []]
    out = []
    for w in wars:
        if w.get("state") in ("notInWar", None):
            continue
        out.append({"tag": w.get("tag"), "round": w["round"], "state": w["state"], "size": w.get("teamSize") or len(w["clan"].get("members") or []),
                    "start": w.get("startTime"), "end": w.get("endTime"), "a": _side(w["clan"]), "b": _side(w["opponent"])})
    size = max([w["size"] for w in out], default=0) or 15
    return {"us": us, "season": group.get("season"), "state": group.get("state"), "league": league, "size": size,
            "rounds_total": len(group.get("rounds") or []) or max(len(clans) - 1, 1), "clans": clans, "wars": out}


def _side(s):
    # la API numera sobre toda la plantilla inscrita: en una guerra de 15 puede salir un 17. Se pasa al puesto real en el mapa
    ranked = sorted(s.get("members") or [], key=lambda m: m.get("mapPosition") or 999)
    place = {m["tag"]: i for i, m in enumerate(ranked, 1)}
    return {"tag": s["tag"], "name": s.get("name") or s["tag"], "stars": s.get("stars", 0), "pct": s.get("destructionPercentage", 0.0),
            "attacks": s.get("attacks", 0),
            "members": [{"tag": m["tag"], "name": m.get("name") or m["tag"], "th": m.get("townhallLevel") or 1, "pos": place[m["tag"]],
                         "atk": [{"def": a["defenderTag"], "stars": a["stars"], "pct": a["destructionPercentage"], "order": a.get("order") or 0} for a in m.get("attacks") or []]}
                        for m in s.get("members") or []]}


def names(L):
    return {c["tag"]: c["name"] for c in L["clans"]}


def ended(L):
    return [w for w in L["wars"] if w["state"] == "warEnded"]


def war_result(a, b):
    """1 si gana a, -1 si gana b, 0 si empatan en estrellas y destrucción."""
    x, y = (a["stars"], round(a["pct"], 3)), (b["stars"], round(b["pct"], 3))
    return (x > y) - (x < y)


def standings(L):
    """Clasificación oficial: sólo cuentan las guerras terminadas."""
    t = {c["tag"]: {"tag": c["tag"], "name": c["name"], "stars": 0, "war_stars": 0, "pct": 0.0, "won": 0, "tied": 0, "lost": 0, "played": 0,
                    "attacks": 0, "attacks_max": 0} for c in L["clans"]}
    for w in ended(L):
        r = war_result(w["a"], w["b"])
        for me, res in ((w["a"], r), (w["b"], -r)):
            x = t[me["tag"]]
            x["stars"] += me["stars"]
            x["war_stars"] += me["stars"]
            x["pct"] += me["pct"]
            x["played"] += 1
            x["attacks"] += me["attacks"]
            x["attacks_max"] += w["size"]
            if res > 0:
                x["won"] += 1
                x["stars"] += WIN_BONUS
            elif res < 0:
                x["lost"] += 1
            else:
                x["tied"] += 1
    rows = sorted(t.values(), key=lambda x: (-x["stars"], -x["pct"], x["name"]))
    for i, x in enumerate(rows, 1):
        x["rank"] = i
        x["pct"] = round(x["pct"], 2)
    return rows


def pending(L):
    """Guerras que faltan: las en juego, las en preparación y las parejas sin ronda todavía."""
    done = {frozenset((w["a"]["tag"], w["b"]["tag"])) for w in ended(L)}
    games, seen = [], set()
    for w in L["wars"]:
        pair = frozenset((w["a"]["tag"], w["b"]["tag"]))
        if w["state"] != "warEnded":
            seen.add(pair)
            games.append({"a": w["a"]["tag"], "b": w["b"]["tag"], "state": w["state"], "round": w["round"], "war": w, "end": w.get("end")})
    tags = [c["tag"] for c in L["clans"]]
    for i, a in enumerate(tags):
        for b in tags[i + 1:]:
            pair = frozenset((a, b))
            if pair not in done and pair not in seen:
                games.append({"a": a, "b": b, "state": "pending", "round": None, "war": None, "end": None})
    # si en una ronda sin publicar sólo cabe un cruce para cada clan, ese es el cruce
    return _guess_rounds(L, games)


def _guess_rounds(L, games):
    known = [g["round"] for g in games if g["round"]] + [w["round"] for w in L["wars"]]
    last = max(known, default=0)
    free = [g for g in games if g["state"] == "pending"]
    for i, r in enumerate(range(last + 1, L["rounds_total"] + 1)):
        if len(free) <= len(L["clans"]) // 2 and r == L["rounds_total"]:
            for g in free:
                g["round"] = r
                g["deduced"] = True
    return games


def cut(L, round_):
    """La liga tal y como estaba al terminar esa ronda: sirve para reconstruir el pasado sin haberlo guardado."""
    return {**L, "state": "inWar", "wars": [w for w in L["wars"] if w["round"] <= round_]}


# ---------------- lo que aún se puede sumar ----------------
def _members(L, game, tag):
    """Alineación en esa guerra, o la última conocida si aún no está publicada."""
    w = game.get("war")
    if w:
        return w["a"] if w["a"]["tag"] == tag else w["b"]
    return last_side(L, tag)


def last_side(L, tag):
    for w in sorted(L["wars"], key=lambda w: -w["round"]):
        for s in (w["a"], w["b"]):
            if s["tag"] == tag:
                return s
    c = next(c for c in L["clans"] if c["tag"] == tag)
    return {"tag": tag, "name": c["name"], "stars": 0, "pct": 0.0, "attacks": 0,
            "members": [{"tag": m["tag"], "name": m["name"], "th": m["th"], "pos": i, "atk": []} for i, m in enumerate(sorted(c["roster"], key=lambda m: -m["th"])[:L["size"]], 1)]}


def side_limits(L, game, tag, inactive=()):
    """Estrellas y destrucción actuales y máximas de un clan en una guerra pendiente."""
    size = (game.get("war") or {}).get("size") or L["size"]
    if game["state"] == "inWar":
        s = _members(L, game, tag)
        left = sum(1 for m in s["members"] if not m["atk"] and m["tag"] not in inactive)
        return {"cur": s["stars"], "pct": s["pct"], "max": min(3 * size, s["stars"] + 3 * left), "pct_max": min(100.0, s["pct"] + 100.0 * left / size), "left": left}
    c = next(c for c in L["clans"] if c["tag"] == tag)
    avail = sum(1 for m in c["roster"] if m["tag"] not in inactive)
    if game["state"] == "preparation":          # la alineación aún se puede cambiar, salvo que no haya banquillo
        lineup = _members(L, game, tag)["members"]
        spare = max(0, avail - sum(1 for m in lineup if m["tag"] not in inactive))
        n = min(size, sum(1 for m in lineup if m["tag"] not in inactive) + spare)
    else:
        n = min(size, avail) if c["roster"] else size
    return {"cur": 0, "pct": 0.0, "max": 3 * n, "pct_max": 100.0 * n / size, "left": n}


def _beats(x, xp, y, yp):
    return (x, xp) > (y, yp)


def rank_bounds(L, tag, inactive=(), extra=None):
    """Mejor y peor puesto posibles de un clan. `inactive` son cuentas suyas que no van a atacar."""
    table = {x["tag"]: x for x in standings(L)}
    games = pending(L)
    others = [t for t in table if t != tag]
    mine = [g for g in games if tag in (g["a"], g["b"])]
    rest = [g for g in games if tag not in (g["a"], g["b"])]
    lim = {}
    for g in games:
        for t in (g["a"], g["b"]):
            lim[(id(g), t)] = side_limits(L, g, t, inactive if t == tag else ())

    # mejor caso: máximo propio y lo mínimo para los demás
    my = table[tag]["stars"]
    my_pct = table[tag]["pct"]
    low = {t: table[t]["stars"] for t in others}
    low_pct = {t: table[t]["pct"] for t in others}
    for g in mine:
        rival = g["b"] if g["a"] == tag else g["a"]
        me, ot = lim[(id(g), tag)], lim[(id(g), rival)]
        my += me["max"]
        my_pct += me["pct_max"]
        low[rival] += ot["cur"]
        low_pct[rival] += ot["pct"]
        if _beats(me["max"], me["pct_max"], ot["cur"], ot["pct"]):
            my += WIN_BONUS
        elif _beats(ot["cur"], ot["pct"], me["max"], me["pct_max"]):
            low[rival] += WIN_BONUS
    options = []
    for g in rest:
        a, b = lim[(id(g), g["a"])], lim[(id(g), g["b"])]
        if g["state"] != "inWar":
            options.append([{}])
            continue
        add = {g["a"]: (a["cur"], a["pct"]), g["b"]: (b["cur"], b["pct"])}
        res = (a["cur"], a["pct"]) > (b["cur"], b["pct"]), (b["cur"], b["pct"]) > (a["cur"], a["pct"])
        opts = [{t: (s, p, WIN_BONUS if (res[0] if t == g["a"] else res[1]) else 0) for t, (s, p) in add.items()}]
        # quien va por detrás puede remontar lo justo: suma el bonus pero se lo quita al otro
        for w, l, x, y in ((g["a"], g["b"], a, b), (g["b"], g["a"], b, a)):
            if (x["cur"], x["pct"]) < (y["cur"], y["pct"]) and x["max"] >= y["cur"] and x["pct_max"] > y["pct"]:
                opts.append({w: (y["cur"], y["pct"] + .01, WIN_BONUS), l: (y["cur"], y["pct"], 0)})
            if (x["cur"], x["pct"]) < (y["cur"], y["pct"]) and x["max"] >= y["cur"] and x["pct_max"] >= y["pct"]:
                opts.append({w: (y["cur"], y["pct"], 0), l: (y["cur"], y["pct"], 0)})     # o empatar: nadie se lleva el bonus
        options.append(opts)
    best = len(table)
    for combo in product(*options):
        s, p = dict(low), dict(low_pct)
        for o in combo:
            for t, (x, q, bonus) in o.items():
                s[t] += x + bonus
                p[t] += q
        best = min(best, 1 + sum(_above(s[t], p[t], my, my_pct) for t in others))

    # peor caso: lo que ya tiene y lo máximo para los demás
    my = table[tag]["stars"]
    my_pct = table[tag]["pct"]
    high = {t: table[t]["stars"] for t in others}
    high_pct = {t: table[t]["pct"] for t in others}
    for g in mine:
        rival = g["b"] if g["a"] == tag else g["a"]
        me, ot = lim[(id(g), tag)], lim[(id(g), rival)]
        my += me["cur"]
        my_pct += me["pct"]
        high[rival] += ot["max"]
        high_pct[rival] += ot["pct_max"]
        if _beats(ot["max"], ot["pct_max"], me["cur"], me["pct"]):
            high[rival] += WIN_BONUS
        elif _beats(me["cur"], me["pct"], ot["max"], ot["pct_max"]):
            my += WIN_BONUS
    if extra is not None:                   # «y si este clan llega a tantas estrellas»: para el número mágico
        my = extra
    open_games = []
    for g in rest:
        a, b = lim[(id(g), g["a"])], lim[(id(g), g["b"])]
        high[g["a"]] += a["max"]
        high[g["b"]] += b["max"]
        high_pct[g["a"]] += a["pct_max"]
        high_pct[g["b"]] += b["pct_max"]
        ca, cb = _beats(a["max"], a["pct_max"], b["cur"], b["pct"]), _beats(b["max"], b["pct_max"], a["cur"], a["pct"])
        open_games.append(([g["a"]] if ca else []) + ([g["b"]] if cb else []))
    open_games = [o for o in open_games if o]
    if len(open_games) <= BONUS_LIMIT:
        worst = 1
        for combo in product(*open_games):
            s = dict(high)
            for t in combo:
                s[t] += WIN_BONUS
            worst = max(worst, 1 + sum(_above_worst(s[t], high_pct[t], my, my_pct) for t in others))
    else:                                   # demasiadas guerras: todos con todos sus bonus; peca de prudente, nunca de optimista
        s = dict(high)
        for o in open_games:
            for t in o:
                s[t] += WIN_BONUS
        worst = 1 + sum(_above_worst(s[t], high_pct[t], my, my_pct) for t in others)
    return best, worst


def _above(s, p, my, my_pct):
    return s > my or (s == my and p > my_pct)


def _above_worst(s, p, my, my_pct):
    return s > my or (s == my and p >= my_pct)


# ---------------- nivel de los clanes ----------------
def attacks_of(L):
    """Todos los ataques de la liga, con la ventaja de ayuntamiento del atacante."""
    out = []
    for w in L["wars"]:
        for me, ot in ((w["a"], w["b"]), (w["b"], w["a"])):
            th = {m["tag"]: m["th"] for m in ot["members"]}
            for m in me["members"]:
                for a in m["atk"]:
                    if a["def"] in th:
                        out.append({"clan": me["tag"], "player": m["tag"], "d": m["th"] - th[a["def"]], "stars": a["stars"], "pct": a["pct"], "round": w["round"], "def": a["def"]})
    return out


def _war_end(w):
    return modelo._ts(w.get("end"))


def fit(L, rng=None, data=None, hp=None, light=False, on=None):
    """Mide todo lo que hace falta para prever: modelo de ataques, asistencia y puntería de cada clan."""
    data = data or {}
    ends = [_war_end(w) for w in L["wars"]]
    cut = max(ends, default=0)
    rows = modelo.rows_from_league(L)
    if data.get("rows"):
        rows = modelo.merge([r for r in data["rows"] if not ends or r["end"] <= cut], rows)
    else:
        rows = modelo.merge(rows)
    villages = data.get("villages") or {}
    if light:
        prob = modelo.train(rows, villages, hp=hp or data.get("hp") or modelo.DEFAULT_HP, tune=False, report=False, steps=350)
    else:
        prob = modelo.train(rows, villages, hp=hp or data.get("hp"), on=on)
    seen, used = {}, {}
    for w in sorted(ended(L), key=lambda w: w["round"]):
        for s in (w["a"], w["b"]):
            for m in s["members"]:
                seen[(s["tag"], m["tag"])] = seen.get((s["tag"], m["tag"]), 0) + 1
                used[(s["tag"], m["tag"])] = used.get((s["tag"], m["tag"]), 0) + bool(m["atk"])
    rate = {}
    for c in L["clans"]:
        n = sum(v for k, v in seen.items() if k[0] == c["tag"])
        rate[c["tag"]] = (sum(v for k, v in used.items() if k[0] == c["tag"]) + modelo.PRIOR["use"] * USE_PRIOR_WEIGHT) / (n + USE_PRIOR_WEIGHT)
    now = L.get("now") or cut or 0
    hist = modelo.usage_rates(data.get("usage") or [], now, skip=set(ends)) if now else {}
    model = {"prob": prob, "seen": seen, "used": used, "rate": rate, "hist": hist, "sigma": prob.info.get("war_sigma", modelo.PRIOR["war_sigma"]), "aim": {}, "levels": {}}
    for c in L["clans"]:
        model["aim"][c["tag"]], model["levels"][c["tag"]] = _clan_habits(L, model, c["tag"])
    return model


def _clan_habits(L, model, tag):
    """Puntería: el % de pleno al que suele apuntar el clan. Nivel: su habilidad media, a igualdad de ayuntamiento."""
    prob = model["prob"]
    chosen = []
    for w in L["wars"]:
        for me, ot in ((w["a"], w["b"]), (w["b"], w["a"])):
            if me["tag"] != tag:
                continue
            info = {m["tag"]: m for m in ot["members"]}
            for m in me["members"]:
                for a in m["atk"]:
                    if a["def"] in info:
                        chosen.append(prob.dist(m, info[a["def"]], size=w["size"])[3])
    aim = (sum(chosen) + .6 * 5) / (len(chosen) + 5)       # sin datos, apunta a un pleno probable
    side = last_side(L, tag)
    skill = [prob.ua.get(m["tag"], 0.0) + 3 * prob.form_a.get(m["tag"], 0.0) for m in side["members"]]
    return aim, round(sum(skill) / len(skill), 3) if skill else 0.0


def use_prob(model, clan, tag, inactive=()):
    """Probabilidad de que una cuenta ataque: lo de esta liga pesa entero y lo anterior según lo reciente que sea."""
    if tag in inactive:
        return 0.0
    n, u = model["seen"].get((clan, tag), 0), model["used"].get((clan, tag), 0)
    hu, hn = model["hist"].get(tag, (0.0, 0.0))
    return (u + hu + model["rate"][clan] * USE_PRIOR_WEIGHT) / (n + hn + USE_PRIOR_WEIGHT)


def auto_inactive(L, tag):
    """Cuentas que llevan varias guerras alineadas sin atacar ninguna vez."""
    n, used = {}, {}
    for w in ended(L):
        for s in (w["a"], w["b"]):
            if s["tag"] == tag:
                for m in s["members"]:
                    n[m["tag"]] = n.get(m["tag"], 0) + 1
                    used[m["tag"]] = used.get(m["tag"], 0) + bool(m["atk"])
    live = {m["tag"] for w in L["wars"] for s in (w["a"], w["b"]) if s["tag"] == tag for m in s["members"] if m["atk"]}
    return {t: v for t, v in n.items() if v >= MIN_INACTIVE_WARS and t not in live}


# ---------------- simulación ----------------
def _prep_side(model, me, ot, size, live, inactive=None, force=None, plan_=None, left=None):
    """Deja calculado lo que no cambia entre tiradas: una guerra se simula cientos de veces."""
    clan = me["tag"]
    prob = model["prob"]
    bases = ot["members"]
    index = {m["tag"]: i for i, m in enumerate(bases)}
    best, pcts = [0] * len(bases), [0.0] * len(bases)
    pending_, have = [], 0
    for m in me["members"]:
        if live and m["atk"]:
            have += 1
            for a in m["atk"]:
                i = index.get(a["def"])
                if i is not None:
                    best[i] = max(best[i], a["stars"])
                    pcts[i] = max(pcts[i], a["pct"])
            continue
        p = force[m["tag"]] if force is not None and m["tag"] in force else use_prob(model, clan, m["tag"], inactive or ())
        pending_.append((m, p))
    if live and have:          # quien aún no ha atacado con la guerra avanzada, es menos probable que lo haga
        total = have + sum(p for _, p in pending_)
        q = min(.95, max(have / total if total else 0, left or 0))
        pending_ = [(m, p * (1 - q) / (1 - p * q)) if p < 1 and force is None else (m, p) for m, p in pending_]
    pending_.sort(key=lambda x: (-x[0]["th"], x[0].get("pos") or 99))
    sigma = model["sigma"]
    table = {}
    for s, shift in enumerate(SHIFTS):
        for fresh in (True, False):
            rows = []
            for m, _ in pending_:
                row = []
                for b in bases:
                    d = prob.dist(m, b, fresh=fresh, size=size, shift=shift * sigma)
                    c0, c1, c2 = d[0], d[0] + d[1], d[0] + d[1] + d[2]
                    row.append(((c0, c1, c2), tuple(sum(d[k] * max(0, k - x) for k in range(4)) for x in range(4)), d[3]))
                rows.append(row)
            table[(s, fresh)] = rows
    pos = {m["tag"]: i for i, (m, _) in enumerate(pending_)}
    route = None
    if plan_ is not None:
        route = {pos[a["a_tag"]]: index[a["b_tag"]] for a in plan_ if a["a_tag"] in pos and a["b_tag"] in index}
    return {"probs": [p for _, p in pending_], "table": table, "best": best, "pcts": pcts, "ths": [b["th"] for b in bases], "aim": model["aim"].get(clan, .6), "pct": prob.pct, "route": route,
            "touched": [x > 0 for x in pcts], "n": len(bases) or 1, "positions": [b.get("pos") or 0 for b in bases], "own": [m.get("pos") or 0 for m, _ in pending_]}


def _roll(P, rng):
    """Una tirada de un bando. Cada cuenta va a la aldea más alta donde alcanza la puntería de su clan."""
    table, best, pcts, touched = P["table"], list(P["best"]), list(P["pcts"]), list(P["touched"])
    day = rng.randrange(len(SHIFTS))
    ths, aim, pct_of, route = P["ths"], P["aim"], P["pct"], P["route"]
    fresh_t, used_t = table[(day, True)], table[(day, False)]
    order = range(len(P["probs"]))
    if route is not None:                    # con plan, primero el plan y al final las reservas, que rematan lo fallado
        order = sorted(order, key=lambda i: i not in route)
    for i in order:
        if rng.random() >= P["probs"][i]:
            continue
        pick = route.get(i) if route is not None else None
        if pick is None or best[pick] >= 3:
            top, pick, safe, safe_th = 0.0, None, None, -1
            for j, bth in enumerate(ths):
                b = best[j]
                if b >= 3 or (route is not None and P["positions"][j] < P["own"][i]):
                    continue
                cell = (used_t if touched[j] else fresh_t)[i][j]
                g = cell[1][b]
                if g > top:
                    top, pick = g, j
                if route is None and cell[2] >= aim and bth > safe_th:
                    safe, safe_th = j, bth
            if safe is not None:
                pick = safe
        if pick is None:
            continue
        c = (used_t if touched[pick] else fresh_t)[i][pick][0]
        r = rng.random()
        s = 0 if r < c[0] else 1 if r < c[1] else 2 if r < c[2] else 3
        touched[pick] = True
        if s > best[pick]:
            best[pick] = s
        pcts[pick] = max(pcts[pick], pct_of[s])
    return sum(best), sum(pcts) / P["n"]


def _left(L, g):
    """Parte de la guerra en juego que ya ha pasado, según la hora de la última recogida."""
    now, end = L.get("now"), g.get("end")
    if not now or not end:
        return 0.0
    return max(0.0, min(1.0, 1 - (modelo._ts(end) - now) / 86400))


def _sim_games(L, model, games, rng, n, us=None, inactive=(), force=None, plans=None, tick=None):
    out = []
    for i, g in enumerate(games):
        if tick:
            tick(i, len(games))
        a, b = _members(L, g, g["a"]), _members(L, g, g["b"])
        live = g["state"] == "inWar"
        size = (g.get("war") or {}).get("size") or L["size"]
        left = _left(L, g) if live else 0
        pa = _prep_side(model, a, b, size, live, inactive if g["a"] == us else None, force if g["a"] == us else None, (plans or {}).get(_key(g)) if g["a"] == us else None, left)
        pb = _prep_side(model, b, a, size, live, inactive if g["b"] == us else None, force if g["b"] == us else None, (plans or {}).get(_key(g)) if g["b"] == us else None, left)
        out.append([_roll(pa, rng) + _roll(pb, rng) for _ in range(n)])
    return out


def _key(g):
    return f"{g['a']}|{g['b']}"


def simulate(L, model, rng, inactive=(), force=None, game_sims=GAME_SIMS, season_sims=SEASON_SIMS, plans=None, tick=None):
    """Reparte el final de la liga miles de veces. Las guerras son independientes: se simulan una vez y se combinan."""
    us = L["us"]
    games = pending(L)
    table = {x["tag"]: x for x in standings(L)}
    tags = list(table)
    samples = _sim_games(L, model, games, rng, game_sims, us, inactive, force, plans, tick)
    finals = {t: [] for t in tags}
    ranks = {t: [0] * (len(tags) + 1) for t in tags}
    wins = [[0, 0] for _ in games]
    for _ in range(season_sims):
        s = {t: table[t]["stars"] for t in tags}
        p = {t: table[t]["pct"] for t in tags}
        for i, g in enumerate(games):
            x, xp, y, yp = rng.choice(samples[i])
            s[g["a"]] += x
            s[g["b"]] += y
            p[g["a"]] += xp
            p[g["b"]] += yp
            if (x, xp) > (y, yp):
                s[g["a"]] += WIN_BONUS
                wins[i][0] += 1
            elif (y, yp) > (x, xp):
                s[g["b"]] += WIN_BONUS
                wins[i][1] += 1
        order = sorted(tags, key=lambda t: (-s[t], -p[t], rng.random()))
        for r, t in enumerate(order, 1):
            ranks[t][r] += 1
            finals[t].append(s[t])
    res = {"games": [], "finals": {}, "ranks": {}, "sims": season_sims}
    for i, g in enumerate(games):
        xs = [r[0] for r in samples[i]]
        ys = [r[2] for r in samples[i]]
        xp = [r[1] for r in samples[i]]
        yp = [r[3] for r in samples[i]]
        res["games"].append({"a": g["a"], "b": g["b"], "state": g["state"], "round": g["round"], "deduced": bool(g.get("deduced")),
                             "ax": round(statistics.mean(xs), 1), "bx": round(statistics.mean(ys), 1),
                             "alo": _q(xs, .1), "ahi": _q(xs, .9), "blo": _q(ys, .1), "bhi": _q(ys, .9),
                             "ap": round(statistics.mean(xp), 1), "bp": round(statistics.mean(yp), 1),
                             "win_a": wins[i][0] / season_sims, "win_b": wins[i][1] / season_sims})
    for t in tags:
        res["finals"][t] = {"mean": round(statistics.mean(finals[t]), 1), "lo": _q(finals[t], .1), "hi": _q(finals[t], .9)}
        res["ranks"][t] = [x / season_sims for x in ranks[t][1:]]
    return res


def _q(v, p):
    v = sorted(v)
    return v[int(p * (len(v) - 1))]


def backtest(L, rng, data=None, hp=None, done=None, sims=60):
    """Error de la previsión en las guerras jugadas, usando sólo lo sabido antes de cada ronda. Se guarda por ronda."""
    done = dict(done or {})
    for r in sorted({w["round"] for w in ended(L)})[1:]:
        if str(r) in done:
            continue
        past = {**L, "wars": [w for w in ended(L) if w["round"] < r]}
        model = fit(past, rng, data, hp, light=True)
        errs = []
        for w in ended(L):
            if w["round"] == r:
                for me, ot in ((w["a"], w["b"]), (w["b"], w["a"])):
                    P = _prep_side(model, {**me, "stars": 0, "members": [{**m, "atk": []} for m in me["members"]]}, ot, w["size"], False)
                    errs.append(statistics.mean(_roll(P, rng)[0] for _ in range(sims)) - me["stars"])
        done[str(r)] = [round(e, 2) for e in errs]
    errs = [e for v in done.values() for e in v]
    return done, {"n": len(errs), "bias": round(statistics.mean(errs), 2) if errs else None, "mae": round(statistics.mean(abs(e) for e in errs), 2) if errs else None}


# ---------------- asignación de ataques ----------------
def hungarian(cost):
    """Asignación de coste mínimo en una matriz n×m con n <= m. Devuelve la columna de cada fila."""
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


def _base_state(me, ot, live):
    """Aldeas rivales tal y como están: mejores estrellas ya logradas y si alguien las ha tocado."""
    best, touched = {}, set()
    if live:
        for m in me["members"]:
            for a in m["atk"]:
                best[a["def"]] = max(best.get(a["def"], 0), a["stars"])
                touched.add(a["def"])
    return [{**b, "best": best.get(b["tag"], 0), "touched": b["tag"] in touched} for b in ot["members"]]


def war_plan(L, model, game, tag, inactive=()):
    """Plan de ataque de un clan en una guerra, con quienes pueden atacar aún."""
    me = _members(L, game, tag)
    rival = game["b"] if game["a"] == tag else game["a"]
    ot = _members(L, game, rival)
    live = game["state"] == "inWar"
    attackers = [m for m in me["members"] if m["tag"] not in inactive and not (live and m["atk"])]
    bases = _base_state(me, ot, live)
    size = (game.get("war") or {}).get("size") or L["size"]
    seed = f"{tag}|{_key(game)}|{sum(b['best'] for b in bases)}|{len(attackers)}"
    return planner.build(model["prob"], [{**m, "pos": m.get("pos")} for m in attackers], bases, size, seed=seed, stars_now=me["stars"] if live else 0)


# ---------------- qué hace falta ----------------
def needs(L, model, sim, tag, inactive, bounds, zones, plans):
    """Para cada puesto: a quién hay que superar, cuántas estrellas hacen falta y qué se puede permitir."""
    table = {x["tag"]: x for x in standings(L)}
    nm = names(L)
    games = pending(L)
    mine = [g for g in games if tag in (g["a"], g["b"])]
    others = sorted((t for t in table if t != tag), key=lambda t: -sim["finals"][t]["mean"])
    won = table[tag]["stars"]
    ceilings = []
    max_ = real = 0
    can_win = 0
    for g in mine:
        rival = g["b"] if g["a"] == tag else g["a"]
        lim = side_limits(L, g, tag, inactive)
        ot = side_limits(L, g, rival)
        c = min(lim["max"], plans[_key(g)]["hi"] if _key(g) in plans else lim["max"])
        ceilings.append({"rival": rival, "round": g["round"], "max": lim["max"], "ceil": c, "cur": lim["cur"], "state": g["state"]})
        max_ += lim["max"]
        real += c
        can_win += _beats(lim["max"], lim["pct_max"], ot["cur"], ot["pct"])
    expected = 0.0
    for gs in sim["games"]:
        if gs["a"] == tag:
            expected += gs["ax"]
        elif gs["b"] == tag:
            expected += gs["bx"]
    base = won + WIN_BONUS * can_win
    rows = []
    for p in range(1, len(table) + 1):
        row = {"pos": p, "prob": round(sum(sim["ranks"][tag][:p]), 4), **_status(bounds, p, sum(sim["ranks"][tag][:p]))}
        if p <= len(others):
            blocker = others[p - 1]
            f = sim["finals"][blocker]
            need = int(math.floor(f["mean"])) + 1 - base
            row.update(rival=nm[blocker], rival_tag=blocker, rival_mean=f["mean"], rival_lo=f["lo"], rival_hi=f["hi"], need=need,
                       need_per_war=round(need / len(mine), 1) if mine else None)
            row["reach"] = "ya" if need <= 0 else "esperado" if need <= expected else "techo" if need <= real else "maximo" if need <= max_ else "imposible"
            w_rival = sum(g["win_a"] if g["a"] == blocker else g["win_b"] for g in sim["games"] if blocker in (g["a"], g["b"]))
            bonus = round(w_rival)
            games_rival = sum(1 for g in games if blocker in (g["a"], g["b"]))
            allow = []
            for label, s in (("Nuestro máximo", max_), ("Nuestro techo realista", real), ("Nuestra previsión", int(round(expected)))):
                cap = base + s - 1 - table[blocker]["stars"] - WIN_BONUS * bonus
                allow.append({"label": label, "stars": s, "final": base + s, "rival_max": cap,
                              "rival_per_war": round(cap / games_rival, 1) if games_rival else None})
            row["allow"] = allow
            row["wins_rival"] = bonus
            row["plan"] = _share(ceilings, max(need, 0))
        row["magic"] = None if row["basis"] == "matematica" else magic_number(L, tag, inactive, p, base, max_)
        rows.append(row)
    return {"rows": rows, "wars": ceilings, "max": max_, "real": real, "expected": round(expected, 1), "base": base, "can_win": can_win, "others": others}


def _status(bounds, p, prob):
    """Asegurado o descartado por matemáticas si no hay otra; si la simulación no lo ve ni en un caso entre 200, en la práctica."""
    if bounds[1] <= p:
        return {"status": "asegurado", "basis": "matematica"}
    if bounds[0] > p:
        return {"status": "descartado", "basis": "matematica"}
    if prob >= 1 - PRACTICAL:
        return {"status": "asegurado", "basis": "practica"}
    if prob <= PRACTICAL:
        return {"status": "descartado", "basis": "practica"}
    return {"status": "posible", "basis": "simulacion"}


def _share(ceilings, need):
    """Reparte las estrellas necesarias entre las guerras que quedan, según lo que da de sí cada una."""
    total = sum(c["ceil"] for c in ceilings)
    if not total:
        return []
    out = []
    for c in ceilings:
        out.append({"rival": c["rival"], "round": c["round"], "target": min(c["ceil"], int(round(need * c["ceil"] / total))), "ceil": c["ceil"], "max": c["max"], "cur": c["cur"], "state": c["state"]})
    diff = min(need, total) - sum(o["target"] for o in out)
    for o in sorted(out, key=lambda o: o["ceil"] - o["target"], reverse=diff > 0):
        if diff == 0:
            break
        step = 1 if diff > 0 else -1
        room = o["ceil"] - o["target"] if diff > 0 else o["target"]
        take = min(abs(diff), room)
        o["target"] += step * take
        diff -= step * take
    return out


def magic_number(L, tag, inactive, pos, base, max_):
    """Estrellas que garantizan el puesto hagan lo que hagan los demás, o None si ni el máximo lo asegura."""
    lo, hi = 0, max_
    if rank_bounds(L, tag, inactive, extra=base + hi)[1] > pos:
        return None
    while lo < hi:
        m = (lo + hi) // 2
        if rank_bounds(L, tag, inactive, extra=base + m)[1] <= pos:
            hi = m
        else:
            lo = m + 1
    return lo


# ---------------- banquillo ----------------
def lineup_value(model, clan, lineup, bases, inactive, size=15):
    """Estrellas esperadas de una alineación contra esas aldeas (cada aldea recibe un solo ataque)."""
    if not lineup or not bases:
        return 0.0
    rows = sorted(lineup, key=lambda m: -m["th"])[:len(bases)]
    prob = model["prob"]
    cost = [[-use_prob(model, clan, m["tag"], inactive) * sum(i * p for i, p in enumerate(prob.dist(m, b, size=size))) for b in bases] for m in rows]
    pick = hungarian(cost)
    return sum(-cost[i][j] for i, j in enumerate(pick))


def bench(L, model, tag, inactive, sim, plans=None):
    """Qué cambios de alineación convienen en cada guerra que aún se puede tocar, y por qué."""
    c = next(x for x in L["clans"] if x["tag"] == tag)
    games = sorted((g for g in pending(L) if tag in (g["a"], g["b"])), key=lambda g: g["round"] or 99)
    roster = c["roster"]
    nm = names(L)
    usage = []
    th_now = {}
    auto = auto_inactive(L, tag)
    for w in L["wars"]:
        for s in (w["a"], w["b"]):
            if s["tag"] == tag:
                for m in s["members"]:
                    th_now[m["tag"]] = m["th"]
    for m in roster:
        n, u = model["seen"].get((tag, m["tag"]), 0), model["used"].get((tag, m["tag"]), 0)
        usage.append({"tag": m["tag"], "name": m["name"], "th": th_now.get(m["tag"], m["th"]), "wars": n, "used": u, "inactive": m["tag"] in inactive, "auto": m["tag"] in auto,
                      "p": round(use_prob(model, tag, m["tag"], inactive), 2)})
    usage.sort(key=lambda m: -m["th"])
    out = {"roster": usage, "size": L["size"], "spare": max(0, len(roster) - L["size"]), "rounds": []}
    th_of = {m["tag"]: m["th"] for m in usage}
    roster_ = [{**m, "th": th_of[m["tag"]]} for m in roster]
    for g in games:
        rival = g["b"] if g["a"] == tag else g["a"]
        locked = g["state"] == "inWar"
        known = g["war"] is not None
        side = _members(L, g, tag)
        rival_side = _members(L, g, rival)
        ths = rival_side["members"]
        lineup_tags = {m["tag"] for m in side["members"]}
        lineup = [m for m in roster_ if m["tag"] in lineup_tags] or roster_[:L["size"]]
        benched = [m for m in roster_ if m["tag"] not in lineup_tags]
        row = {"round": g["round"], "rival": rival, "rival_name": nm[rival], "state": g["state"], "known": known, "deduced": bool(g.get("deduced")),
               "locked": locked, "swaps": [], "benched": [m["name"] for m in benched], "value": round(lineup_value(model, tag, lineup, ths, inactive), 1)}
        if not locked and benched:
            cur = list(lineup)
            value = lineup_value(model, tag, cur, ths, inactive)
            for _ in range(len(benched)):
                top = None
                for m_out in cur:
                    for m_in in benched:
                        v = lineup_value(model, tag, [x for x in cur if x is not m_out] + [m_in], ths, inactive)
                        if v - value >= .3 and (top is None or v > top[0]):
                            top = (v, m_out, m_in)
                if top is None:
                    break
                v, m_out, m_in = top
                gain = v - value
                cur = [x for x in cur if x is not m_out] + [m_in]
                benched = [x for x in benched if x is not m_in] + [m_out]
                value = v
                row["swaps"].append({"out": m_out["name"], "out_th": m_out["th"], "in": m_in["name"], "in_th": m_in["th"], "gain": round(gain, 1),
                                     "why": _why(model, tag, m_out, m_in, inactive)})
            row["value_after"] = round(value, 1)
        out["rounds"].append(row)
    return out


def _why(model, tag, m_out, m_in, inactive):
    n, u = model["seen"].get((tag, m_out["tag"]), 0), model["used"].get((tag, m_out["tag"]), 0)
    if m_out["tag"] in inactive:
        return f"{m_out['name']} no va a atacar: es un ataque perdido cada guerra."
    if n and u < n:
        return f"{m_out['name']} ha atacado {u} de {n} guerras; {m_in['name']} es más fiable."
    if m_in["th"] > m_out["th"]:
        return f"{m_in['name']} (TH{m_in['th']}) llega a bases que {m_out['name']} (TH{m_out['th']}) no alcanza."
    return f"Con {m_in['name']} se esperan más estrellas contra este rival."


# ---------------- resumen diario ----------------
def _plural(n, a, b):
    return f"{n} {a if n == 1 else b}"


def _pos(n):
    return f"{n}º"


def _gap(a):
    return _plural(abs(a), "estrella", "estrellas")


def daily_log(L, hist=None):
    """Una frase por guerra terminada, agrupadas por día, diciendo si ayudó o no a mejorar el puesto del clan."""
    us = L["us"]
    nm = names(L)
    hist = hist or {}
    days = []
    rounds = sorted({w["round"] for w in ended(L)})
    remaining = max(L["rounds_total"], max(rounds, default=0))
    for r in rounds:
        before = {x["tag"]: x for x in standings({**L, "wars": [w for w in ended(L) if w["round"] < r]})}
        after = {x["tag"]: x for x in standings({**L, "wars": [w for w in ended(L) if w["round"] <= r]})}
        wars = [w for w in ended(L) if w["round"] == r]
        left = remaining - r
        reach = (45 + WIN_BONUS) * left if L["size"] == 15 else (3 * L["size"] + WIN_BONUS) * left
        items = []
        mine = next((w for w in wars if us in (w["a"]["tag"], w["b"]["tag"])), None)
        if mine:
            items.append(_own_item(mine, us, nm, before, after))
        for w in wars:
            if w is not mine:
                items.extend(_rival_item(w, us, nm, before, after, reach))
        day = {"round": r, "date": _date(wars[0].get("end")), "rank_before": before[us]["rank"] if r > rounds[0] else None, "rank": after[us]["rank"], "stars": after[us]["stars"],
               "gained": after[us]["stars"] - before[us]["stars"], "items": items, "headline": _headline(r, before, after, us, hist, r == rounds[0])}
        fav = sum(1 for i in items if i["tone"] == "fav")
        bad = sum(1 for i in items if i["tone"] == "bad")
        moved = 0 if r == rounds[0] else before[us]["rank"] - after[us]["rank"]
        day["tone"] = "fav" if moved > 0 or (moved == 0 and fav > bad) else "bad" if moved < 0 or (moved == 0 and bad > fav) else "neutral"
        days.append(day)
    days.reverse()
    live = sorted((_live_item(w, us, nm) for w in L["wars"] if w["state"] == "inWar"), key=lambda i: not i["own"])
    # los nombres en árabe o hebreo descolocan la frase si no se aíslan
    rtl = [n for n in nm.values() if any("֐" <= ch <= "ࣿ" for ch in n)]
    for i in live + [x for d in days for x in d["items"]]:
        for n in rtl:
            i["text"] = i["text"].replace(n, f"⁨{n}⁩")
    return {"days": days, "live": live}


def _date(end):
    """Día de la API (20261106T140000.000Z) como 06/11."""
    end = str(end or "")
    return f"{end[6:8]}/{end[4:6]}" if len(end) >= 8 and end[:8].isdigit() else None


def _own_item(w, us, nm, before, after):
    me, ot = (w["a"], w["b"]) if w["a"]["tag"] == us else (w["b"], w["a"])
    r = war_result(me, ot)
    first = not before[us]["played"]
    rank = f"Empezamos {_pos(after[us]['rank'])}." if first else f"Pasamos del {_pos(before[us]['rank'])} al {_pos(after[us]['rank'])}." if before[us]["rank"] != after[us]["rank"] else f"Seguimos {_pos(after[us]['rank'])}."
    miss = w["size"] - me["attacks"]
    tail = f" Quedaron {_plural(miss, 'ataque', 'ataques')} sin usar." if miss else ""
    if r > 0:
        t = f"Ganamos a {ot['name']} {me['stars']}-{ot['stars']}: sumamos {me['stars'] + WIN_BONUS} estrellas con el bonus. {rank}{tail}"
    elif r < 0:
        t = f"Perdimos contra {ot['name']} {me['stars']}-{ot['stars']}: solo sumamos {me['stars']} estrellas, sin bonus. {rank}{tail}"
    else:
        t = f"Empatamos con {ot['name']} {me['stars']}-{ot['stars']}. {rank}{tail}"
    return {"tone": "fav" if r > 0 else "bad" if r < 0 else "neutral", "war": f"{me['name']} {me['stars']}-{ot['stars']} {ot['name']}", "text": t, "own": True}


def _rival_item(w, us, nm, before, after, reach):
    """Guerra de otros: ¿nos acerca a quien nos importa o nos aleja? Decide el clan más próximo a nosotros."""
    a, b = w["a"], w["b"]
    r = war_result(a, b)
    winner, loser = (a, b) if r >= 0 else (b, a)
    score = f"{winner['stars']}-{loser['stars']}"
    gap_b = {t: before[t]["stars"] - before[us]["stars"] for t in before}
    gap_a = {t: after[t]["stars"] - after[us]["stars"] for t in after}
    match = f"{a['name']} {a['stars']}-{b['stars']} {b['name']}"
    relevant = sorted((s for s in (a, b) if abs(gap_b[s["tag"]]) <= reach), key=lambda s: abs(gap_b[s["tag"]]))
    if not relevant:
        return [{"tone": "neutral", "war": match, "text": f"{_verb(r, winner, loser, score)} Ninguno de los dos está a nuestro alcance: no nos afecta."}]
    s = relevant[0]
    t, d = s["tag"], gap_a[s["tag"]] - gap_b[s["tag"]]
    if not before[us]["played"]:                      # primera ronda: aún no había distancias que comparar
        tone = "bad" if after[t]["rank"] < after[us]["rank"] else "fav"
        gap = _gap(gap_a[t])
        tail = f"{s['name']} empieza {gap} por delante" if tone == "bad" and gap_a[t] else f"{s['name']} empieza {gap} por detrás" if gap_a[t] else f"{s['name']} empieza igualado con nosotros"
        return [{"tone": tone, "war": match, "text": f"{ {'fav': 'Favorable', 'bad': 'Desfavorable'}[tone]}: {_verb(r, winner, loser, score)} Tras la ronda, {tail}."}]
    ahead_b, ahead_a = before[t]["rank"] < before[us]["rank"], after[t]["rank"] < after[us]["rank"]
    if ahead_b and not ahead_a:
        tone, tail = "fav", f"adelantamos a {s['name']}"
    elif ahead_a and not ahead_b:
        tone, tail = "bad", f"{s['name']} nos adelanta"
    elif d == 0:
        tone, tail = "neutral", f"la distancia con {s['name']} no cambia"
    elif ahead_a:
        gap = _gap(gap_a[t])
        tone, tail = ("fav", f"recortamos {_gap(d)} a {s['name']}, que queda a {gap}") if d < 0 else ("bad", f"{s['name']} se aleja {_gap(d)} y queda a {gap}")
    else:
        gap = _gap(gap_a[t])
        tone, tail = ("fav", f"sacamos {_gap(d)} más a {s['name']}, que queda a {gap}") if d < 0 else ("bad", f"{s['name']} se acerca {_gap(d)} y queda a {gap}")
    label = {"fav": "Favorable", "bad": "Desfavorable", "neutral": "Neutro"}[tone]
    return [{"tone": tone, "war": match, "text": f"{label}: {_verb(r, winner, loser, score)} Tras la ronda, {tail}."}]


def _verb(r, winner, loser, score):
    return f"{winner['name']} y {loser['name']} empataron {score}." if r == 0 else f"{winner['name']} ganó a {loser['name']} {score}."


def _headline(r, before, after, us, hist, first=False):
    a, b = before[us]["rank"], after[us]["rank"]
    move = f"Empezamos {_pos(b)}" if first else f"Subimos del {_pos(a)} al {_pos(b)}" if b < a else f"Bajamos del {_pos(a)} al {_pos(b)}" if b > a else f"Seguimos {_pos(b)}"
    text = f"Ronda {r}: {move} con {after[us]['stars']} estrellas."
    h, prev = hist.get(str(r)), hist.get(str(r - 1))
    if h and prev and h.get("target") and h["target"] == prev.get("target"):
        x, y = prev["target_prob"], h["target_prob"]
        if abs(x - y) >= .005:
            text += f" Opciones del {_pos(h['target'])}: {_pct(x)} → {_pct(y)}."
    return text


def _pct(p):
    return "menos del 1 %" if 0 < p < .01 else "más del 99 %" if .99 < p < 1 else f"{round(p * 100)} %"


def _live_item(w, us, nm):
    a, b = w["a"], w["b"]
    r = war_result(a, b)
    if us in (a["tag"], b["tag"]):
        me, ot = (a, b) if a["tag"] == us else (b, a)
        s = war_result(me, ot)
        state = "Vamos ganando" if s > 0 else "Vamos perdiendo" if s < 0 else "Vamos empatados"
        return {"tone": "fav" if s > 0 else "bad" if s < 0 else "neutral", "war": f"{me['name']} {me['stars']}-{ot['stars']} {ot['name']}", "own": True,
                "text": f"En juego: {state.lower()} contra {ot['name']} con {_plural(me['attacks'], 'ataque usado', 'ataques usados')} de {w['size']}."}
    leader, other = (a, b) if r >= 0 else (b, a)
    return {"tone": "neutral", "war": f"{a['name']} {a['stars']}-{b['stars']} {b['name']}", "own": False,
            "text": f"En juego: {leader['name']} va por delante de {other['name']}." if r else f"En juego: {a['name']} y {b['name']} van empatados."}


# ---------------- vista completa ----------------
DEFAULT_ZONES = (2, 2)


def default_zones(league, n):
    """Cupos por defecto. La API no los da y Supercell no publica una tabla actual: se pueden cambiar en Admin."""
    name = (league or "").lower()
    up, down = DEFAULT_ZONES
    if "legend" in name or "champion league i" == name:
        up = 0
    if "bronze league iii" in name:
        down = 0
    return {"promote": up, "demote": down, "default": True}


def hist_entry(L, model, sim, tag, zones):
    """Lo que hay que recordar de cada ronda para comparar después cómo cambian las opciones."""
    n = len(L["clans"])
    ranks = sim["ranks"][tag]
    st = {x["tag"]: x for x in standings(L)}
    cur = st[tag]["rank"]
    target = max(cur - 1, 1)
    return {"rank": cur, "stars": st[tag]["stars"], "target": target, "target_prob": sum(ranks[:target]),
            "promote_prob": sum(ranks[:zones["promote"]]) if zones["promote"] else 0.0,
            "demote_prob": sum(ranks[n - zones["demote"]:]) if zones["demote"] else 0.0}


def build(L, cfg=None, hist=None, seed=None, data=None, progress=None):
    """Todo lo que enseña la pestaña. Es determinista: con los mismos datos da los mismos números.
    `progress(fase, fracción, detalle)` cuenta por dónde va; la web lo convierte en la barra de avance."""
    cfg = cfg or {}
    on = progress or (lambda *a, **k: None)
    rng = random.Random(seed if seed is not None else f"{L['us']}|{L['season']}|{len(L['wars'])}|{sum(w['a']['stars'] + w['b']['stars'] for w in L['wars'])}")
    tag = L["us"]
    nm = names(L)
    n = len(L["clans"])
    zones = {**default_zones(L.get("league"), n), **({k: cfg[k] for k in ("promote", "demote") if cfg.get(k) is not None})}
    if cfg.get("promote") is not None or cfg.get("demote") is not None:
        zones["default"] = False
    auto = auto_inactive(L, tag)
    forced_yes, forced_no = set(cfg.get("si") or ()), set(cfg.get("no") or ())
    inactive = (set(auto) - forced_yes) | forced_no
    on("modelo")
    model = fit(L, rng, data, on=lambda f, d=None: on("modelo", f, d))
    hp = model["prob"].info.get("hp")
    games_ = pending(L)
    mine = [g for g in games_ if tag in (g["a"], g["b"])]
    plans = {}
    for i, g in enumerate(mine):
        on("plan", i / len(mine), f"guerra {i + 1} de {len(mine)}")
        plans[_key(g)] = war_plan(L, model, g, tag, inactive)

    def sim_tick(a, b, what):
        return lambda i, k: on("sim", a + (b - a) * i / max(k, 1), f"{what}: guerra {i + 1} de {k}")
    sim = simulate(L, model, rng, inactive, tick=sim_tick(0, .6, "con sus hábitos"))
    bounds = {c["tag"]: rank_bounds(L, c["tag"], inactive if c["tag"] == tag else ()) for c in L["clans"]}
    table = standings(L)
    tiers = _labels(list(model["levels"].values()))
    skill = lambda x: {"facil": "Alto", "media": "Medio", "dificil": "Bajo"}[tiers(x)]
    force = {m["tag"]: 1.0 for m in next(c for c in L["clans"] if c["tag"] == tag)["roster"] if m["tag"] not in inactive}
    all_in = simulate(L, model, rng, inactive, force, game_sims=GAME_SIMS // 2, season_sims=SEASON_SIMS // 2, tick=sim_tick(.6, .8, "si atacan todos"))
    routes = {k: p["assign"] for k, p in plans.items()}
    with_plan = simulate(L, model, rng, inactive, force, game_sims=GAME_SIMS // 2, season_sims=SEASON_SIMS // 2, plans=routes, tick=sim_tick(.8, 1, "siguiendo el plan"))
    need = needs(L, model, sim, tag, inactive, bounds[tag], zones, plans)
    hist = dict(hist or {})
    errs = hist.pop("_bt", None)
    played = sorted({w["round"] for w in ended(L)})
    for i, r in enumerate(played):
        on("rondas", .7 * i / len(played), f"ronda {r}")
        if str(r) not in hist:
            past = {**L, "wars": [w for w in L["wars"] if w["round"] < r or (w["round"] == r and w["state"] == "warEnded")]}
            m_ = fit(past, rng, data, hp, light=True)
            s_ = simulate(past, m_, rng, inactive, game_sims=HIST_SIMS // 2, season_sims=HIST_SIMS * 4)
            hist[str(r)] = hist_entry(past, m_, s_, tag, zones)
    on("rondas", .75, "comprobando las previsiones")
    errs, bt = backtest(L, rng, data, hp, errs)
    log = daily_log(L, hist)
    rows = []
    for x in table:
        t = x["tag"]
        rows.append({**x, "best": bounds[t][0], "worst": bounds[t][1], "mean": sim["finals"][t]["mean"], "lo": sim["finals"][t]["lo"], "hi": sim["finals"][t]["hi"],
                     "ranks": [round(v, 4) for v in sim["ranks"][t]], "level": model["levels"][t], "level_name": skill(model["levels"][t]), "us": t == tag, **clan_stats(L, t),
                     "defended": _conceded(L, t), "zone": _zone(zones, n, x["rank"]), **_range(sim["ranks"][t], bounds[t])})
    eases = {}
    for g in games_:     # la dificultad se mide con el reparto de esta liga
        eases[(_key(g), "a")], eases[(_key(g), "b")] = ease(L, model, g, g["a"]), ease(L, model, g, g["b"])
    label = _labels(list(eases.values()))
    games = []
    for g in sim["games"]:
        side = "a" if g["a"] == tag else "b" if g["b"] == tag else None
        games.append({**g, "a_name": nm[g["a"]], "b_name": nm[g["b"]], "mine": side is not None, "a_cur": _cur(L, g, "a"), "b_cur": _cur(L, g, "b"),
                      "a_diff": label(eases[(_key(g), "a")]), "b_diff": label(eases[(_key(g), "b")])})
    ranks = sim["ranks"][tag]
    out_plans = []
    for g in sorted(mine, key=lambda x: x["round"] or 99):
        rival = g["b"] if g["a"] == tag else g["a"]
        p = {k: v for k, v in plans[_key(g)].items() if k != "plan_index"}
        out_plans.append({"round": g["round"], "state": g["state"], "rival": rival, "rival_name": nm[rival], "deduced": bool(g.get("deduced")), "known": g["war"] is not None, **p})
    info = {k: v for k, v in model["prob"].info.items()}
    hist["_bt"] = errs
    return {"state": _phase(L), "season": L["season"], "league": L.get("league"), "size": L["size"], "rounds_total": L["rounds_total"],
            "rounds_done": max([w["round"] for w in ended(L)], default=0), "us": tag, "us_name": nm[tag], "clans": n,
            "zones": zones, "table": rows, "games": games, "needs": need, "bench": bench(L, model, tag, inactive, sim, plans), "log": log, "plans": out_plans,
            "bounds": bounds[tag], "ranks": [round(v, 4) for v in ranks], "ranks_all": [round(v, 4) for v in all_in["ranks"][tag]], "ranks_plan": [round(v, 4) for v in with_plan["ranks"][tag]],
            "inactive": sorted(_name_of(L, t) for t in inactive), "inactive_auto": {_name_of(L, t): v for t, v in auto.items() if t in inactive},
            "backtest": bt, "hist": hist, "attacks": len(attacks_of(L)), "model": info}


def _game_of(L, g):
    return next(x for x in pending(L) if x["a"] == g["a"] and x["b"] == g["b"])


def clan_stats(L, tag):
    """Lo que dicen de un clan sus ataques y sus defensas en esta liga."""
    atks = [a for a in attacks_of(L) if a["clan"] == tag]
    wars = [w for w in ended(L) if tag in (w["a"]["tag"], w["b"]["tag"])]
    ths = [m["th"] for w in L["wars"] for s in (w["a"], w["b"]) if s["tag"] == tag for m in s["members"]]
    if not ths:
        ths = [m["th"] for c in L["clans"] if c["tag"] == tag for m in c["roster"]] or [0]
    return {"stars_attack": round(statistics.mean(a["stars"] for a in atks), 2) if atks else None,
            "triples": round(100 * sum(a["stars"] == 3 for a in atks) / len(atks)) if atks else None,
            "pct_attack": round(statistics.mean(a["pct"] for a in atks), 1) if atks else None,
            "attacks_war": round(statistics.mean((w["a"] if w["a"]["tag"] == tag else w["b"])["attacks"] for w in wars), 1) if wars else None,
            "th": round(statistics.mean(ths), 1), "sample": len(atks)}


def _conceded(L, tag):
    v = [(w["a"] if w["b"]["tag"] == tag else w["b"])["stars"] for w in ended(L) if tag in (w["a"]["tag"], w["b"]["tag"])]
    return round(statistics.mean(v), 1) if v else None


def _cur(L, g, key):
    if g["state"] != "inWar":
        return None
    w = next(w for w in L["wars"] if w["round"] == g["round"] and {w["a"]["tag"], w["b"]["tag"]} == {g["a"], g["b"]})
    s = w["a"] if w["a"]["tag"] == g[key] else w["b"]
    return {"stars": s["stars"], "attacks": s["attacks"]}


def ease(L, model, g, tag):
    """Estrellas por ataque del mejor reparto posible contra ese rival: mide al rival, no los ataques que se pierdan."""
    me = _members(L, g, tag)
    ot = _members(L, g, g["b"] if g["a"] == tag else g["a"])
    size = (g.get("war") or {}).get("size") or L["size"]
    rows = sorted(me["members"], key=lambda m: -m["th"])[:len(ot["members"])]
    if not rows or not ot["members"]:
        return 0.0
    prob = model["prob"]
    cost = [[-sum(i * p for i, p in enumerate(prob.dist(m, b, size=size))) for b in ot["members"]] for m in rows]
    pick = hungarian(cost)
    return sum(-cost[i][j] for i, j in enumerate(pick)) / (3 * len(rows))


def _labels(values):
    """Fácil, media o difícil según el reparto de esta liga: la vara se adapta al nivel del grupo."""
    v = sorted(values)
    if not v:
        return lambda x: "media"
    lo, hi = v[len(v) // 3], v[2 * len(v) // 3]
    return lambda x: "facil" if x >= hi else "media" if x >= lo else "dificil"


def _range(ranks, bounds):
    seen = [i + 1 for i, v in enumerate(ranks) if v > PRACTICAL]
    if not seen:
        return {"from": bounds[0], "to": bounds[1]}
    return {"from": max(min(seen), bounds[0]), "to": min(max(seen), bounds[1])}


def _zone(z, n, rank):
    return "up" if rank <= z["promote"] else "down" if rank > n - z["demote"] else "stay"


def _name_of(L, tag):
    for c in L["clans"]:
        if c["tag"] == L["us"]:
            for m in c["roster"]:
                if m["tag"] == tag:
                    return m["name"]
    return tag


def _phase(L):
    if not L["wars"]:
        return "preparing"
    if not pending(L):
        return "ended"
    return "live" if any(w["state"] == "inWar" for w in L["wars"]) else "preparing_round"

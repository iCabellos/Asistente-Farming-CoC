"""Previsto y real: qué se esperaba de cada guerra antes de empezar y qué pasó después, en liga y en guerras normales.

Una guerra normal se trata como una liga de dos clanes: mismo modelo, misma simulación y mismo plan, con dos ataques por
cuenta y sin el efecto de liga.

Lo importante es no hacer trampa. El modelo que se usa cada día ya ha visto los ataques de ayer, así que preguntarle por
ellos daría un acierto falso. Por eso cada guerra se predice con un modelo entrenado solo con lo terminado antes de que
empezara, y esa predicción se guarda una vez y no se toca. Si la alineación cambia durante la preparación se repite: aún
no se ha atacado.

Lo guardado no necesita numpy (Frozen): con eso la web sigue una guerra en directo sin entrenar nada.
"""
import hashlib
import math
import random
import statistics

import liga
import modelo

SIMS = 400
AIM_RECENT = 40           # ataques recientes que dicen a qué % de pleno suele apuntar un clan
NOTABLE = .75             # estrellas de diferencia con lo esperado para decir que salió mejor o peor
BINS = ((0, .2), (.2, .4), (.4, .6), (.6, .75), (.75, .9), (.9, 1.01))


def standard(t, us, kind):
    """Guerra guardada, en la forma con la que trabaja liga.py y con nuestro clan siempre en `a`."""
    cwl = kind == "cwl"
    x, y = (t["clan"], t["opponent"]) if t["clan"]["tag"] == us else (t["opponent"], t["clan"])
    a, b = liga._side(x), liga._side(y)
    return {"kind": kind, "cwl": cwl, "per": t.get("attacksPerMember") or (1 if cwl else 2), "tag": t.get("tag"), "round": t.get("round"), "state": t["state"], "partial": bool(t.get("partial")),
            "size": t.get("teamSize") or len(a["members"]) or 1, "start": t.get("startTime"), "end": t.get("endTime"), "a": a, "b": b}


def signature(war):
    """Huella de las alineaciones: si cambia en preparación, la previsión ya no vale."""
    tags = ",".join(sorted(m["tag"] for s in (war["a"], war["b"]) for m in s["members"]))
    return hashlib.sha1(tags.encode()).hexdigest()[:12]


def blank(side):
    return {**side, "stars": 0, "pct": 0.0, "attacks": 0, "members": [{**m, "atk": []} for m in side["members"]]}


def mini(war, us, now):
    """La guerra como una liga de dos clanes."""
    return {"us": us, "season": str(war.get("end")), "state": "inWar", "league": None, "size": war["size"], "rounds_total": 1, "now": now, "cwl": war["cwl"], "per": war["per"],
            "clans": [{"tag": s["tag"], "name": s["name"], "roster": [{"tag": m["tag"], "name": m["name"], "th": m["th"]} for m in s["members"]]} for s in (war["a"], war["b"])],
            "wars": [{"tag": war.get("tag"), "round": 1, "state": war["state"], "size": war["size"], "start": war.get("start"), "end": war.get("end"), "a": war["a"], "b": war["b"]}]}


def _start(war):
    return modelo._ts(war.get("start")) or modelo._ts(war.get("end")) - 86400


def habit_aim(prob, rows, tag, default):
    """A qué % de pleno suele apuntar un clan, según sus últimos ataques. Sin datos, lo que diga `default`."""
    mine = [r for r in rows if r.get("clan") == tag][-AIM_RECENT:]
    if not mine:
        return default
    seen = [prob.dist({"tag": r["a"], "th": r["a_th"], "pos": r.get("a_pos")}, {"tag": r["d"], "th": r["d_th"], "pos": r.get("d_pos")}, cwl=bool(r["cwl"]), size=r.get("size") or 15)[3] for r in mine]
    return (sum(seen) + default * 5) / (len(seen) + 5)


def _play(a, b, rng, n=SIMS):
    """Juega la guerra muchas veces. `a` es nuestro lado."""
    runs = [liga._roll(a, rng) + liga._roll(b, rng) for _ in range(n)]
    xs, ys = [r[0] for r in runs], [r[2] for r in runs]
    return {"win": round(sum((r[0], r[1]) > (r[2], r[3]) for r in runs) / n, 3), "lose": round(sum((r[2], r[3]) > (r[0], r[1]) for r in runs) / n, 3),
            "us": round(statistics.mean(xs), 1), "us_lo": liga._q(xs, .1), "us_hi": liga._q(xs, .9), "them": round(statistics.mean(ys), 1), "them_lo": liga._q(ys, .1), "them_hi": liga._q(ys, .9),
            "us_pct": round(statistics.mean(r[1] for r in runs), 1), "them_pct": round(statistics.mean(r[3] for r in runs), 1)}


def forecast(war, us, data, seed=0, inactive=()):
    """Previsión de una guerra con lo sabido antes de empezar. Devuelve lo necesario para seguirla sin volver a entrenar."""
    start = _start(war)
    known = {**data, "rows": [r for r in data["rows"] if r["end"] <= start], "usage": [u for u in data.get("usage") or [] if u["end"] <= start]}
    w = {**war, "a": blank(war["a"]), "b": blank(war["b"]), "state": "preparation"}
    L = mini(w, us, start)
    rng = random.Random(seed)
    model = liga.fit(L, rng, known, light=True)
    prob = model["prob"]
    model["sigma"] = data.get("sigma") or modelo.PRIOR["war_sigma"]
    sides = (w["a"], w["b"])
    for s in sides:
        model["aim"][s["tag"]] = habit_aim(prob, known["rows"], s["tag"], model["aim"][s["tag"]])
    size, per, cwl = war["size"], war["per"], war["cwl"]
    a = liga._prep_side(model, w["a"], w["b"], size, False, inactive, per=per, cwl=cwl)
    b = liga._prep_side(model, w["b"], w["a"], size, False, per=per, cwl=cwl)
    tags = [m["tag"] for s in sides for m in s["members"]]
    x, y = w["a"]["members"], w["b"]["members"]
    pick = lambda d: {t: round(float(d[t]), 3) for t in tags if t in d}
    return {"sig": signature(war), "th": prob.th, "fresh": prob.beta[modelo.NAMES.index("fresh")], "pct": prob.pct, "sigma": model["sigma"], "calib": data.get("calib"), "aim": {s["tag"]: model["aim"][s["tag"]] for s in sides},
            "use": {m["tag"]: round(liga.use_prob(model, s["tag"], m["tag"], inactive if s["tag"] == us else ()), 3) for s in sides for m in s["members"]},
            "a": [m["tag"] for m in x], "b": [m["tag"] for m in y], "ab": [[round(prob.eta(m, d, True, cwl, size), 3) for d in y] for m in x], "ba": [[round(prob.eta(m, d, True, cwl, size), 3) for d in x] for m in y],
            "ua": pick(prob.ua), "ud": pick(prob.ud), "form_a": pick(prob.form_a), "form_d": pick(prob.form_d), "recent_a": {t: prob.recent_a[t] for t in tags if t in prob.recent_a}, "recent_d": {t: prob.recent_d[t] for t in tags if t in prob.recent_d},
            "rows": len(known["rows"]), "made": start, "before": _play(a, b, rng)}


class Frozen:
    """El modelo tal como estaba antes de esa guerra. Se comporta como modelo.Prob, sin numpy y solo para esos jugadores."""

    def __init__(self, s):
        self.th, self.f, self.info = s["th"], s["fresh"], {"calib": s.get("calib")}
        self.pct = {int(k): v for k, v in s["pct"].items()}
        self.ua, self.ud, self.form_a, self.form_d, self.recent_a, self.recent_d = s["ua"], s["ud"], s["form_a"], s["form_d"], s["recent_a"], s["recent_d"]
        self.eta_ = {(a, b): s["ab"][i][j] for i, a in enumerate(s["a"]) for j, b in enumerate(s["b"])}
        self.eta_.update({(b, a): s["ba"][j][i] for i, a in enumerate(s["a"]) for j, b in enumerate(s["b"])})
        self._c = {}

    def dist(self, a, b, fresh=True, cwl=True, size=15, shift=0.0):
        k = (a["tag"], b["tag"], fresh, shift)
        v = self._c.get(k)
        if v is None:
            # si alguien entró a última hora no está en la tabla: se estima por la diferencia de ayuntamiento
            e = self.eta_.get((a["tag"], b["tag"]), float(a.get("th", 0) - b.get("th", 0))) + (0.0 if fresh else -2 * self.f) + shift
            p = [1 / (1 + math.exp(-max(min(e + c, 40), -40))) for c in self.th]
            v = self._c[k] = (1 - p[0], p[0] - p[1], p[1] - p[2], p[2])
        return v


def review(war, prob):
    """Cada ataque nuestro, por orden, con lo que se esperaba de él justo antes de hacerlo."""
    info = {m["tag"]: m for m in war["b"]["members"]}
    hits = sorted(((x, m) for m in war["a"]["members"] for x in m["atk"]), key=lambda h: h[0]["order"])
    touched, out = set(), []
    for x, m in hits:
        b = info.get(x["def"])
        if not b:
            continue
        d = prob.dist(m, b, fresh=x["def"] not in touched, cwl=war["cwl"], size=war["size"])
        touched.add(x["def"])
        e = sum(i * p for i, p in enumerate(d))
        gap = x["stars"] - e
        out.append({"o": x["order"], "a_pos": m.get("pos"), "a": m["name"], "a_tag": m["tag"], "a_th": m["th"], "b_pos": b.get("pos"), "b": b["name"], "b_th": b["th"], "p3": round(d[3], 3), "e": round(e, 2), "stars": x["stars"], "pct": x["pct"],
                    "tone": "up" if gap >= NOTABLE else "down" if gap <= -NOTABLE else "ok"})
    return out


def tally(rows):
    """Lo esperado frente a lo hecho en esos ataques."""
    return {"n": len(rows), "p3": round(sum(r["p3"] for r in rows), 1), "triples": sum(r["stars"] == 3 for r in rows), "e": round(sum(r["e"] for r in rows), 1), "stars": sum(r["stars"] for r in rows)}


def _side_info(s, war):
    return {"tag": s["tag"], "name": s["name"], "stars": s["stars"], "pct": round(s["pct"], 1), "attacks": s["attacks"], "max": war["size"] * war["per"]}


def _result(war):
    r = liga.war_result(war["a"], war["b"])
    return "win" if r > 0 else "lose" if r < 0 else "tie"


def finished(war, snap):
    """Comparación definitiva de una guerra terminada."""
    rows = review(war, Frozen(snap))
    return {"kind": war["kind"], "round": war.get("round"), "size": war["size"], "per": war["per"], "end": war.get("end"), "partial": war["partial"], "result": _result(war), "us": _side_info(war["a"], war), "them": _side_info(war["b"], war),
            "before": snap["before"], "made": snap.get("made"), "rows": rows, "t": tally(rows)}


def battle_view(war, us, snap, now, seed=0):
    """Una guerra en juego o en preparación: marcador, lo previsto antes de empezar, cómo va y el plan de lo que queda."""
    live = war["state"] == "inWar"
    out = {"kind": war["kind"], "cwl": war["cwl"], "round": war.get("round"), "state": war["state"], "size": war["size"], "per": war["per"], "start": modelo._ts(war.get("start")), "ends": modelo._ts(war.get("end")),
           "us": _side_info(war["a"], war), "them": _side_info(war["b"], war), "before": None, "now": None, "hits": [], "t": None, "plan": None, "ts": int(now)}
    if not snap:
        return out                       # guerra recién empezada: la previsión llegará con la siguiente recogida
    prob = Frozen(snap)
    model = {"prob": prob, "use": snap["use"], "aim": snap["aim"], "sigma": snap["sigma"]}
    L = mini(war, us, now)
    games = liga.pending(L)
    rows = review(war, prob)
    out.update(before=snap["before"], hits=rows, t=tally(rows), made=snap.get("made"))
    if not games:
        return out                       # acaba de terminar: ya no hay nada que planear
    g = games[0]
    size, per, cwl = war["size"], war["per"], war["cwl"]
    left = liga._left(L, g) if live else 0
    inactive = {t for t, p in snap["use"].items() if not p}
    a = liga._prep_side(model, war["a"], war["b"], size, live, inactive, left=left, per=per, cwl=cwl)
    b = liga._prep_side(model, war["b"], war["a"], size, live, left=left, per=per, cwl=cwl)
    out["now"] = _play(a, b, random.Random(f"{seed}|{war['a']['stars']}|{war['b']['stars']}"))
    plan = liga.war_plan(L, model, g, us, inactive)
    out["plan"] = {"round": war.get("round"), "title": None if war["cwl"] else "Guerra normal", "state": war["state"], "rival": war["b"]["tag"], "rival_name": war["b"]["name"], "deduced": False, "known": True, **plan}
    return out


def summary(items):
    """Balance de todas las guerras medidas: ¿lo que se dice se cumple? ¿quién rinde más o menos de lo esperado?"""
    rows = [r for x in items for r in x["rows"]]
    if not rows:
        return None
    bins = []
    for lo, hi in BINS:
        v = [r for r in rows if lo <= r["p3"] < hi]
        if v:
            bins.append({"lo": lo, "hi": min(hi, 1), "says": round(sum(r["p3"] for r in v) / len(v), 3), "real": round(sum(r["stars"] == 3 for r in v) / len(v), 3), "n": len(v)})
    who = {}
    for r in rows:
        p = who.setdefault(r["a_tag"], {"tag": r["a_tag"], "name": r["a"], "n": 0, "p3": 0.0, "triples": 0, "e": 0.0, "stars": 0})
        p["n"] += 1
        p["p3"] += r["p3"]
        p["triples"] += r["stars"] == 3
        p["e"] += r["e"]
        p["stars"] += r["stars"]
    players = sorted(({**p, "p3": round(p["p3"], 1), "e": round(p["e"], 1), "gap": round(p["stars"] - p["e"], 1)} for p in who.values()), key=lambda p: -p["gap"])
    called = [x for x in items if x["result"] != "tie" and x["before"]["win"] != x["before"]["lose"]]
    right = sum((x["before"]["win"] > x["before"]["lose"]) == (x["result"] == "win") for x in called)
    return {**tally(rows), "wars": len(items), "called": len(called), "right": right, "stars_err": round(statistics.mean(abs(x["us"]["stars"] - x["before"]["us"]) for x in items), 1), "bins": bins, "players": players}

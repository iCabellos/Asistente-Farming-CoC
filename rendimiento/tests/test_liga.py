"""Pruebas del motor de escenarios. Se ejecutan con: python tests/test_liga.py

Lo más importante: «asegurado» y «descartado» no pueden ser falsos nunca. Por eso los límites se comparan con todos los
resultados posibles de ligas pequeñas, y el resto del módulo se prueba en cada fase de la temporada.
"""
import itertools
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import liga  # noqa: E402
import modelo  # noqa: E402
import plan  # noqa: E402

FOTO = Path(__file__).parent / "foto_liga.json"
TH = [18, 15, 14, 14, 13, 13, 13, 12, 12, 11, 11, 11, 10, 9, 8, 8, 7, 7, 6, 6, 15, 14, 14, 13, 13, 12, 12, 11, 11, 10]


def member(tag, th, pos, atk=None):
    m = {"tag": tag, "name": "n" + tag, "townhallLevel": th, "townHallLevel": th, "mapPosition": pos}
    if atk:
        m["attacks"] = atk
    return m


def fake_league(n=8, size=15, roster=None, rounds_done=0, live=False, prep=True, seed=1, us=0):
    """Liga sintética con la misma forma que la API. rounds_done rondas terminadas y, opcionalmente, una en juego y otra en preparación."""
    rng = random.Random(seed)
    roster = roster or size
    clans = []
    for c in range(n):
        base = rng.randint(-1, 1)
        clans.append({"tag": f"#C{c}", "name": f"Clan {c}", "members": [
            {"tag": f"#C{c}P{i}", "name": f"Jugador {c}.{i}", "townHallLevel": max(3, TH[i % len(TH)] + base)} for i in range(roster)]})
    tags = [c["tag"] for c in clans]
    # calendario de todos contra todos
    rot = tags[1:]
    schedule = []
    for r in range(n - 1):
        cur = [tags[0]] + rot
        schedule.append([(cur[i], cur[n - 1 - i]) for i in range(n // 2)])
        rot = rot[-1:] + rot[:-1]
    wars, rounds = [], []
    for r, pairs in enumerate(schedule, 1):
        st = "warEnded" if r <= rounds_done else "inWar" if live and r == rounds_done + 1 else \
            "preparation" if prep and r == rounds_done + 1 + bool(live) else None
        rounds.append({"warTags": [f"#W{r}{i}" if st else "#0" for i in range(len(pairs))]})
        if not st:
            continue
        for i, (a, b) in enumerate(pairs):
            wars.append(fake_war(clans, a, b, r, i, st, size, rng))
    group = {"state": "inWar" if wars else "preparation", "season": "2026-11", "clans": clans, "rounds": rounds}
    return liga.normalize(group, wars, tags[us], "Gold League II")


def fake_war(clans, a, b, r, i, st, size, rng):
    ca, cb = next(c for c in clans if c["tag"] == a), next(c for c in clans if c["tag"] == b)
    ma = sorted(ca["members"], key=lambda m: -m["townHallLevel"])[:size]
    mb = sorted(cb["members"], key=lambda m: -m["townHallLevel"])[:size]

    def side(me, ot, c):
        best, out = {}, []
        for p, m in enumerate(me, 1):
            atk = None
            if st != "preparation" and rng.random() < (.85 if st == "warEnded" else .4) and not m["tag"].endswith("P5"):
                d = ot[min(p - 1, len(ot) - 1)]
                s = rng.choices([0, 1, 2, 3], [1, 2, 4, 8])[0]
                q = {0: 30, 1: 60, 2: 85, 3: 100}[s]
                atk = [{"attackerTag": m["tag"], "defenderTag": d["tag"], "stars": s, "destructionPercentage": q, "order": p}]
                best[d["tag"]] = max(best.get(d["tag"], (0, 0)), (s, q))
            out.append(member(m["tag"], m["townHallLevel"], p, atk))
        return {"tag": c["tag"], "name": c["name"], "stars": sum(v[0] for v in best.values()), "destructionPercentage": sum(v[1] for v in best.values()) / size,
                "attacks": sum(1 for x in out if x.get("attacks")), "members": out}
    return {"tag": f"#W{r}{i}", "round": r, "state": st, "teamSize": size, "startTime": "x", "endTime": f"20261106T1{r}0000.000Z", "clan": side(ma, mb, ca), "opponent": side(mb, ma, cb)}


# ---------------- límites frente a todos los resultados posibles ----------------
OUT = [(0, 0.0), (1, 55.0), (1, 70.0), (2, 85.0), (3, 100.0)]    # lo que puede pasar en una guerra de una base


def small_league(results, games_left, n=4):
    """Liga de 4 clanes y 1 base por guerra. results: guerras ya jugadas [(a, b, (sa, pa), (sb, pb))]."""
    clans = [{"tag": f"#C{i}", "name": f"C{i}", "members": [{"tag": f"#C{i}P", "name": "x", "townHallLevel": 10}]} for i in range(n)]
    wars = []
    for k, (a, b, x, y) in enumerate(results, 1):
        def s(t, v, o):
            atk = [{"attackerTag": f"#C{t}P", "defenderTag": f"#C{o}P", "stars": v[0], "destructionPercentage": v[1], "order": 1}] if v[1] else None
            return {"tag": f"#C{t}", "name": f"C{t}", "stars": v[0], "destructionPercentage": v[1], "attacks": 1 if atk else 0, "members": [member(f"#C{t}P", 10, 1, atk)]}
        wars.append({"tag": f"#W{k}", "round": k, "state": "warEnded", "teamSize": 1, "clan": s(a, x, b), "opponent": s(b, y, a), "startTime": "x", "endTime": "y"})
    return liga.normalize({"state": "inWar", "season": "s", "clans": clans, "rounds": [{"warTags": ["#x"]}] * (n - 1)}, wars, "#C0", None)


def enumerate_ranks(results, left, tag):
    """Todos los finales posibles: (mejor puesto, peor puesto) reales de ese clan."""
    best, worst = 99, 0
    ids = {f"#C{i}": i for i in range(4)}
    for combo in itertools.product(OUT, repeat=2 * len(left)):
        s = {i: 0 for i in range(4)}
        p = {i: 0.0 for i in range(4)}
        for (a, b, x, y) in list(results) + [(g[0], g[1], combo[2 * i], combo[2 * i + 1]) for i, g in enumerate(left)]:
            s[a] += x[0]
            s[b] += y[0]
            p[a] += x[1]
            p[b] += y[1]
            if x > y:
                s[a] += 10
            elif y > x:
                s[b] += 10
        me = ids[tag]
        above = [i for i in s if i != me and (s[i], p[i]) > (s[me], p[me])]
        ties = [i for i in s if i != me and (s[i], p[i]) == (s[me], p[me])]
        best = min(best, 1 + len(above))
        worst = max(worst, 1 + len(above) + len(ties))
    return best, worst


def test_bounds_never_lie():
    rng = random.Random(3)
    pairs = [(0, 1), (2, 3), (0, 2), (1, 3), (0, 3), (1, 2)]
    checked = exact = 0
    for trial in range(60):
        k = rng.choice([3, 4, 5])                  # guerras ya jugadas: quedan 3, 2 o 1
        order = pairs[:]
        rng.shuffle(order)
        results = [(a, b, rng.choice(OUT), rng.choice(OUT)) for a, b in order[:k]]
        left = order[k:]
        L = small_league(results, left)
        for t in ("#C0", "#C1", "#C2", "#C3"):
            lo, hi = liga.rank_bounds(L, t)
            real_lo, real_hi = enumerate_ranks(results, left, t)
            assert lo <= real_lo, ("descartaría algo posible", results, left, t, lo, real_lo)
            assert hi >= real_hi, ("aseguraría algo que puede fallar", results, left, t, hi, real_hi)
            checked += 1
            exact += (lo, hi) == (real_lo, real_hi)
    print(f"  límites: {checked} casos, ninguno falso, {exact} exactos")


def side_outcomes(attackers_left, bases, start):
    """Todas las estrellas y destrucción finales de un bando con los ataques que le faltan."""
    outs = set()
    opts = [(b, s, p) for b in range(bases) for s, p in OUT] + [None]
    for combo in itertools.product(opts, repeat=attackers_left):
        best = dict(start)
        for c in combo:
            if c:
                b, s, p = c
                best[b] = max(best.get(b, (0, 0.0)), (s, p))
        outs.add((sum(v[0] for v in best.values()), sum(v[1] for v in best.values()) / bases))
    return sorted(outs)


def live_league(rng):
    """4 clanes, 2 bases: dos guerras a medias con ataques ya hechos y el resto terminado."""
    clans = [{"tag": f"#C{i}", "name": f"C{i}", "members": [{"tag": f"#C{i}P{j}", "name": "x", "townHallLevel": 10} for j in range(2)]} for i in range(4)]
    wars, played = [], []

    def side(t, o, plan):
        ms, best = [], {}
        for j, x in enumerate(plan):
            atk = None
            if x:
                b, s, p = x
                atk = [{"attackerTag": f"#C{t}P{j}", "defenderTag": f"#C{o}P{b}", "stars": s, "destructionPercentage": p, "order": 1}]
                best[b] = max(best.get(b, (0, 0.0)), (s, p))
            ms.append(member(f"#C{t}P{j}", 10, j + 1, atk))
        return {"tag": f"#C{t}", "name": f"C{t}", "stars": sum(v[0] for v in best.values()), "destructionPercentage": sum(v[1] for v in best.values()) / 2,
                "attacks": sum(1 for x in plan if x), "members": ms}, best
    r = 0
    for a, b in ((0, 1), (2, 3), (0, 2), (1, 3)):
        r += 1
        pa = [(rng.randrange(2), *rng.choice(OUT)), (rng.randrange(2), *rng.choice(OUT))]
        pb = [(rng.randrange(2), *rng.choice(OUT)), (rng.randrange(2), *rng.choice(OUT))]
        x, _ = side(a, b, pa)
        y, _ = side(b, a, pb)
        wars.append({"tag": f"#W{r}", "round": r, "state": "warEnded", "teamSize": 2, "startTime": "x", "endTime": "y", "clan": x, "opponent": y})
        played.append((a, b, (x["stars"], x["destructionPercentage"]), (y["stars"], y["destructionPercentage"])))
    live = []
    for a, b in ((0, 3), (1, 2)):
        r += 1
        pa = [(rng.randrange(2), *rng.choice(OUT)) if rng.random() < .6 else None for _ in range(2)]
        pb = [(rng.randrange(2), *rng.choice(OUT)) if rng.random() < .6 else None for _ in range(2)]
        x, bx = side(a, b, pa)
        y, by = side(b, a, pb)
        wars.append({"tag": f"#W{r}", "round": r, "state": "inWar", "teamSize": 2, "startTime": "x", "endTime": "y", "clan": x, "opponent": y})
        live.append((a, b, side_outcomes(sum(1 for q in pa if not q), 2, bx), side_outcomes(sum(1 for q in pb if not q), 2, by)))
    L = liga.normalize({"state": "inWar", "season": "s", "clans": clans, "rounds": [{"warTags": ["#x", "#y"]}] * 3}, wars, "#C0", None)
    return L, played, live


def test_bounds_with_wars_half_played():
    rng = random.Random(11)
    checked = exact = 0
    for _ in range(40):
        L, played, live = live_league(rng)
        base_s, base_p = {i: 0 for i in range(4)}, {i: 0.0 for i in range(4)}
        for a, b, x, y in played:
            base_s[a] += x[0]
            base_s[b] += y[0]
            base_p[a] += x[1]
            base_p[b] += y[1]
            if x > y:
                base_s[a] += 10
            elif y > x:
                base_s[b] += 10
        for me in range(4):
            best, worst = 99, 0
            for (xa, xb), (ya, yb) in itertools.product(itertools.product(live[0][2], live[0][3]), itertools.product(live[1][2], live[1][3])):
                s, p = dict(base_s), dict(base_p)
                for (a, b, _, _), u, v in ((live[0], xa, xb), (live[1], ya, yb)):
                    s[a] += u[0]
                    s[b] += v[0]
                    p[a] += u[1]
                    p[b] += v[1]
                    if u > v:
                        s[a] += 10
                    elif v > u:
                        s[b] += 10
                above = sum((s[i], p[i]) > (s[me], p[me]) for i in s if i != me)
                ties = sum((s[i], p[i]) == (s[me], p[me]) for i in s if i != me)
                best, worst = min(best, 1 + above), max(worst, 1 + above + ties)
            lo, hi = liga.rank_bounds(L, f"#C{me}")
            assert lo <= best, ("descartaría algo posible en una guerra a medias", lo, best)
            assert hi >= worst, ("aseguraría algo que puede fallar en una guerra a medias", hi, worst)
            checked += 1
            exact += (lo, hi) == (best, worst)
    print(f"  guerras a medias: {checked} casos, ninguno falso, {exact} exactos")


def test_final_table_is_exact():
    results = [(0, 1, (3, 100.0), (1, 55.0)), (2, 3, (2, 85.0), (2, 85.0)), (0, 2, (1, 70.0), (3, 100.0)),
               (1, 3, (0, 0.0), (0, 0.0)), (0, 3, (2, 85.0), (1, 55.0)), (1, 2, (3, 100.0), (2, 85.0))]
    L = small_league(results, [])
    t = {x["tag"]: x for x in liga.standings(L)}
    assert t["#C0"]["stars"] == 3 + 1 + 2 + 20 and t["#C0"]["won"] == 2 and t["#C0"]["lost"] == 1, t["#C0"]
    assert t["#C3"]["tied"] == 2 and t["#C3"]["stars"] == 3
    for tag, x in t.items():
        assert liga.rank_bounds(L, tag) == (x["rank"], x["rank"]), tag


def test_tiebreak_by_destruction():
    r = [(0, 2, (2, 85.0), (1, 70.0)), (1, 3, (2, 80.0), (1, 55.0))]
    rows = liga.standings(small_league(r, []))
    assert [x["tag"] for x in rows[:2]] == ["#C0", "#C1"], rows


def test_war_rules():
    a, b = {"stars": 5, "pct": 50.0}, {"stars": 5, "pct": 40.0}
    assert liga.war_result(a, b) == 1 and liga.war_result(b, a) == -1 and liga.war_result(a, dict(a)) == 0


# ---------------- reparto de ataques ----------------
def test_hungarian_optimal():
    rng = random.Random(5)
    for _ in range(150):
        n, m = rng.randint(1, 6), rng.randint(6, 7)
        cost = [[rng.random() for _ in range(m)] for _ in range(n)]
        pick = liga.hungarian(cost)
        assert len(set(pick)) == n
        got = sum(cost[i][j] for i, j in enumerate(pick))
        best = min(sum(cost[i][p[i]] for i in range(n)) for p in itertools.permutations(range(m), n))
        assert abs(got - best) < 1e-9, (got, best)


# ---------------- cualquier momento y cualquier clan ----------------
def check_view(v, L):
    json.dumps(v)                                     # debe poder guardarse y enviarse
    n = len(L["clans"])
    assert abs(sum(v["ranks"]) - 1) < 1e-3 and len(v["ranks"]) == n
    rows = v["needs"]["rows"]
    assert [r["pos"] for r in rows] == list(range(1, n + 1))
    assert all(r["status"] in ("asegurado", "posible", "descartado") for r in rows)
    probs = [r["prob"] for r in rows]
    assert all(b >= a - 1e-9 for a, b in zip(probs, probs[1:])), probs
    order = {"descartado": 0, "posible": 1, "asegurado": 2}
    st = [order[r["status"]] for r in rows]
    assert st == sorted(st), st                      # un puesto mejor nunca puede ser más seguro que uno peor
    assert rows[-1]["status"] == "asegurado"
    for r in v["table"]:
        assert 1 <= r["best"] <= r["rank"] <= r["worst"] <= n, r
        assert r["from"] <= r["to"] and r["best"] <= r["from"] and r["to"] <= r["worst"], r
        assert abs(sum(r["ranks"]) - 1) < 1e-3
    assert v["bounds"][0] <= v["bounds"][1]


def test_every_phase():
    cases = {"antes de empezar": dict(rounds_done=0, prep=False), "primera preparación": dict(rounds_done=0), "ronda 1 en juego": dict(rounds_done=0, live=True),
             "mitad": dict(rounds_done=3, live=True), "ronda 6": dict(rounds_done=5, live=True), "última en juego": dict(rounds_done=6, live=True, prep=False),
             "terminada": dict(rounds_done=7, prep=False), "30 contra 30": dict(size=30, rounds_done=3, live=True),
             "con banquillo": dict(roster=22, rounds_done=2, live=True), "otro grupo": dict(rounds_done=4, seed=9, us=5)}
    for name, kw in cases.items():
        t = time.time()
        L = fake_league(**kw)
        v = liga.build(L)
        check_view(v, L)
        print(f"  {name}: {time.time() - t:.1f} s, fase {v['state']}, puestos {v['bounds']}")
        assert time.time() - t < 25, name


def test_ended_is_final():
    L = fake_league(rounds_done=7, prep=False)
    v = liga.build(L)
    assert v["state"] == "ended" and not v["games"]
    for r in v["needs"]["rows"]:
        assert r["basis"] == "matematica", r
    rank = next(x["rank"] for x in v["table"] if x["us"])
    assert tuple(v["bounds"]) == (rank, rank)


def test_any_clan():
    L = fake_league(rounds_done=3, live=True)
    base = liga.standings(L)
    for us in (0, 3, 7):
        M = {**L, "us": f"#C{us}"}
        assert liga.standings(M) == base
        v = liga.build(M)
        check_view(v, M)
        assert v["us_name"] == f"Clan {us}"
        assert next(x for x in v["table"] if x["us"])["tag"] == f"#C{us}"


def test_deterministic():
    L = fake_league(rounds_done=3, live=True)
    assert json.dumps(liga.build(L)) == json.dumps(liga.build(L))


def test_news_change_the_result():
    a = liga.build(fake_league(rounds_done=3, live=True))
    b = liga.build(fake_league(rounds_done=4, live=True))
    assert a["rounds_done"] == 3 and b["rounds_done"] == 4 and a["ranks"] != b["ranks"]
    assert len(b["log"]["days"]) == 4 and len(a["log"]["days"]) == 3


# ---------------- cuentas que no atacan y banquillo ----------------
def test_inactive_lowers_the_ceiling():
    L = fake_league(rounds_done=3, live=True)
    assert "#C0P5" in liga.auto_inactive(L, "#C0")      # la cuenta P5 nunca ataca en la liga sintética
    v = liga.build(L)
    g = [g for g in liga.pending(L) if "#C0" in (g["a"], g["b"]) and g["state"] == "pending"]
    assert liga.side_limits(L, g[0], "#C0", {"#C0P5"})["max"] == 3 * 14
    assert any(n.endswith("0.5") for n in v["inactive"])
    w = liga.build(L, {"si": ["#C0P5"]})                # el administrador puede decir que sí atacará
    assert not w["inactive"]
    assert w["needs"]["max"] >= v["needs"]["max"]


def test_bench_swaps_the_inactive():
    L = fake_league(roster=22, rounds_done=3, live=True)
    v = liga.build(L, {"no": ["#C0P0"]})
    b = v["bench"]
    assert b["spare"] == 7
    rows = [r for r in b["rounds"] if not r["locked"]]
    assert rows and not any(r["swaps"] for r in b["rounds"] if r["locked"])
    assert any(s["out"] == "Jugador 0.0" for r in rows for s in r["swaps"]), rows
    for r in rows:
        for s in r["swaps"]:
            assert s["gain"] > 0 and s["why"]
        assert r.get("value_after", 0) >= r["value"] - 1e-6


def test_no_bench_no_swaps():
    v = liga.build(fake_league(rounds_done=3, live=True))
    assert v["bench"]["spare"] == 0 and not any(r["swaps"] for r in v["bench"]["rounds"])


def test_zones():
    L = fake_league(rounds_done=3, live=True)
    v = liga.build(L, {"promote": 3, "demote": 1})
    assert v["zones"]["promote"] == 3 and not v["zones"]["default"]
    assert [x["zone"] for x in v["table"]].count("up") == 3 and [x["zone"] for x in v["table"]].count("down") == 1


# ---------------- plan de ataque ----------------
class FakeProb:
    """Modelo de juguete: el pleno depende sólo de la diferencia de ayuntamiento."""
    pct = {0: 30.0, 1: 60.0, 2: 80.0, 3: 100.0}
    recent_a, recent_d, ua, ud, form_a, form_d = {}, {}, {}, {}, {}, {}

    def dist(self, a, b, fresh=True, cwl=True, size=15, shift=0.0):
        d = a["th"] - b["th"]
        p3 = {-2: .05, -1: .2, 0: .5, 1: .8}.get(d, .97 if d > 1 else .01)
        p2 = (1 - p3) * .7
        return ((1 - p3 - p2) * .3, (1 - p3 - p2) * .7, p2, p3)


def _lineup(ths, prefix):
    return [{"tag": f"#{prefix}{i}", "name": f"{prefix}{i}", "th": th, "pos": i} for i, th in enumerate(ths, 1)]


def test_plan_rules():
    rng = random.Random(4)
    for _ in range(60):
        n = rng.randint(2, 12)
        at = _lineup(sorted((rng.randint(9, 14) for _ in range(n)), reverse=True), "A")
        ba = _lineup(sorted((rng.randint(9, 14) for _ in range(n)), reverse=True), "B")
        p = plan.build(FakeProb(), at, ba, n, seed=rng.random())
        seen_a, seen_b = set(), set()
        for r in p["assign"]:
            assert r["b_pos"] >= r["a_pos"], ("ataque por encima de su puesto", r)
            assert r["a_tag"] not in seen_a and r["b_tag"] not in seen_b, "una cuenta o una aldea repetida"
            seen_a.add(r["a_tag"])
            seen_b.add(r["b_tag"])
            assert r["p3"] >= p["tau"] - 1e-9
        assert len(seen_a) + len(p["reserves"]) == n
        dist = plan.grid(FakeProb(), at, ba, n)
        # nunca da menos plenos que el espejo, salvo lo poco que se cede por evitar ataques dudosos
        got = sum(r["p3"] for r in p["assign"])
        mir = sum(dist[i][j][3] for i, j in plan.mirror(at, ba).items())
        assert got >= mir * (1 - plan.GIVE_UP) - .3, (got, mir)


def test_plan_finds_the_slide():
    """El caso pedido: los de abajo no llegan a nada y los de arriba bajan para asegurar el pleno."""
    at = _lineup([14, 14, 14, 13, 13, 13, 12, 12, 8, 8], "A")
    ba = _lineup([15, 15, 14, 14, 13, 13, 12, 12, 11, 11], "B")
    p = plan.build(FakeProb(), at, ba, 10, seed=1)
    assert {r["pos"] for r in p["reserves"]} >= {9, 10}, p["reserves"]    # los TH8 no atacan
    assert p["assign"] and p["triples"] > p["mirror"]["triples"], (p["triples"], p["mirror"])
    assert all(r["b_pos"] > r["a_pos"] for r in p["assign"]), p["assign"]
    assert {u["pos"] for u in p["uncovered"]} >= {1, 2}
    assert p["shape"] in ("bajada", "mixto")


def test_plan_pure_mirror():
    ths = [14, 13, 12, 11, 10]
    at, ba = _lineup(ths, "A"), _lineup([t - 2 for t in ths], "B")
    p = plan.build(FakeProb(), at, ba, 5, seed=2)
    assert len(p["assign"]) == 5 and p["triples"] > 4


def test_plan_live_state():
    at = _lineup([14, 13, 12], "A")
    ba = [{**b, "best": x, "touched": x > 0} for b, x in zip(_lineup([12, 12, 12], "B"), (3, 2, 0))]
    p = plan.build(FakeProb(), at[1:], ba, 3, seed=3, stars_now=5)
    assert all(r["b_pos"] != 1 for r in p["assign"]) and p["done"] == 1      # la aldea con 3★ ya no se ataca


def test_map_rank_not_roster_number():
    L = fake_league(roster=22, rounds_done=1, live=True)
    for w in L["wars"]:
        for s in (w["a"], w["b"]):
            assert sorted(m["pos"] for m in s["members"]) == list(range(1, len(s["members"]) + 1))


# ---------------- modelo ----------------
def _rows(n=2500, seed=3):
    """Ataques sintéticos: el jugador 0 es muy bueno, el 1 muy malo, y la aldea X muy dura."""
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        a, d = rng.randrange(40), rng.randrange(40)
        ath, dth = rng.randint(10, 14), rng.randint(10, 14)
        e = (ath - dth) * 1.1 + .4 + (1.8 if a == 0 else -1.8 if a == 1 else 0) + (-1.8 if d == 0 else 0)
        p = 1 / (1 + 2.718 ** -e)
        s = 3 if rng.random() < p else rng.choice([1, 2, 2])
        rows.append({"a": f"#A{a}", "d": f"#D{d}", "end": 1.7e9 + i * 3000, "ord": 1, "a_th": ath, "d_th": dth, "a_pos": 5, "d_pos": 5, "size": 15, "cwl": 1, "stars": s, "pct": 100 if s == 3 else 70, "fresh": 1, "clan": None})
    return rows


def test_model_learns_players():
    m = modelo.train(_rows(), tune=False)
    A = lambda t: {"tag": t, "th": 12, "pos": 5}
    p = lambda a, d: m.dist(A(a), A(d))[3]
    assert p("#A0", "#D5") > p("#A5", "#D5") + .1 > p("#A1", "#D5") + .2, (p("#A0", "#D5"), p("#A5", "#D5"), p("#A1", "#D5"))
    assert p("#A5", "#D0") < p("#A5", "#D5") - .1
    assert abs(sum(m.dist(A("#A5"), A("#D5"))) - 1) < 1e-9


def test_model_is_calibrated():
    rows = _rows(4000, 8)
    m = modelo.train(rows[:3000], tune=False)
    t = rows[3000:]
    A = lambda r: ({"tag": r["a"], "th": r["a_th"], "pos": 5}, {"tag": r["d"], "th": r["d_th"], "pos": 5})
    ps = [(m.dist(*A(r))[3], r["stars"] == 3) for r in t]
    for lo, hi in ((0, .3), (.3, .7), (.7, 1.01)):
        x = [q for q in ps if lo <= q[0] < hi]
        assert abs(sum(a for a, _ in x) / len(x) - sum(b for _, b in x) / len(x)) < .08, (lo, hi)


def test_model_without_data_is_sensible():
    m = modelo.train([])
    p = lambda a, b: m.dist({"tag": "x", "th": a}, {"tag": "y", "th": b})[3]
    assert p(14, 11) > .9 and p(11, 14) < .1 and p(14, 14) < p(14, 13) < p(14, 12)


def test_model_merge_keeps_best_data():
    a = {"a": "x", "d": "y", "end": 1.0, "ord": 3, "fresh": None, "clan": "c", "stars": 3}
    b = {**a, "fresh": 1, "clan": None}
    r = modelo.merge([a], [b])
    assert len(r) == 1 and r[0]["fresh"] == 1 and r[0]["clan"] == "c"


# ---------------- avance ----------------
def test_progress_during_build():
    seen = []
    liga.build(fake_league(rounds_done=3, live=True), progress=lambda s, f=0.0, d=None: seen.append((s, f)))
    assert [s for s in dict.fromkeys(x[0] for x in seen)] == ["modelo", "plan", "sim", "rondas"], seen[:5]
    assert all(0 <= f <= 1 for _, f in seen)
    fr = [f for s, f in seen if s == "sim"]
    assert fr == sorted(fr) and fr[0] < .1 and fr[-1] > .9


def test_progress_bar_rules():
    import almacen
    import clan
    sent, keep = [], almacen.guardar_progreso
    almacen.guardar_progreso = lambda p: sent.append(p)
    try:
        P = clan.Progress("test")
        P.gap = 0
        P("recoger")
        P("jugadores", .5, "8 de 16")
        P("recoger", .1)                       # aunque una fase llegue tarde, la barra no retrocede
        P("sim", .5)
        P.finish()
        pcts = [p["pct"] for p in sent]
        assert pcts == sorted(pcts) and pcts[-1] == 100 and not sent[-1]["active"] and sent[-1]["ok"]
        assert sent[1]["detail"] == "8 de 16" and sent[1]["label"] == clan.STAGES["jugadores"][2] and sent[1]["step"] == 2 and len(sent[1]["steps"]) == 9
        sent.clear()
        Q = clan.Progress("admin", first="modelo")
        Q.gap = 0
        Q("modelo")
        Q.finish()
        assert sent[0]["pct"] == 0 and sent[0]["step"] == 1 and len(sent[0]["steps"]) == 5 and sent[-1]["pct"] == 100     # un recálculo también va de 0 a 100
        sent.clear()
        R = clan.Progress("x", quiet=True)
        R("recoger")
        R.finish()
        assert not sent                        # las recogidas ligeras del PC no enseñan barra
    finally:
        almacen.guardar_progreso = keep


def test_dead_run_is_detected():
    import almacen
    import clan
    keep = almacen.leer_progreso
    almacen.leer_progreso = lambda: {"active": True, "updated": time.time() - 999}
    try:
        p = clan.progress_state()
        assert not p["active"] and p["ok"] is False and p["error"]
    finally:
        almacen.leer_progreso = keep


# ---------------- resumen diario ----------------
def test_log_tone():
    v = liga.build(fake_league(rounds_done=5, live=True))
    for d in v["log"]["days"]:
        assert d["headline"] and d["items"] and d["tone"] in ("fav", "bad", "neutral")
        for i in d["items"]:
            assert i["text"] and i["tone"] in ("fav", "bad", "neutral")
    assert v["log"]["days"][0]["round"] == 5
    assert v["log"]["live"]


# ---------------- la liga real ----------------
def test_real_snapshot():
    if not FOTO.exists():
        print("  (sin foto real)")
        return
    d = json.loads(FOTO.read_text(encoding="utf8"))
    L = liga.normalize(d["group"], d["wars"], "#JYQGJG9", d["league"])
    t = {x["name"]: x for x in liga.standings(L)}
    assert t["kanrisklan"]["stars"] == 137 and t["Best Bax"]["stars"] == 169 and t["khoda ba mast"]["stars"] == 203
    assert t["kanrisklan"]["rank"] == 3 and t["kanrisklan"]["won"] == 2
    g = liga.pending(L)
    last = [x for x in g if x.get("deduced")]
    names = liga.names(L)
    assert {frozenset((names[x["a"]], names[x["b"]])) for x in last} >= {frozenset(("PommesMilitärer", "kanrisklan")), frozenset(("Best Bax", "قبیله خدایان"))}
    v = liga.build(L)
    check_view(v, L)
    assert v["inactive"] == ["Miguel_YT"] and v["needs"]["max"] == 126
    rows = {r["pos"]: r for r in v["needs"]["rows"]}
    assert rows[1]["status"] == "descartado" and rows[2]["status"] == "posible" and rows[3]["status"] == "asegurado"
    assert rows[2]["rival"] == "Best Bax"
    print(f"  liga real: 2º al {rows[2]['prob'] * 100:.1f} %, previsión {v['needs']['expected']}★, error de la previsión {v['backtest']}")


if __name__ == "__main__":
    bad = 0
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            t = time.time()
            try:
                f()
                print(f"OK    {k} ({time.time() - t:.1f} s)")
            except Exception as e:
                bad += 1
                print(f"FALLA {k}: {type(e).__name__}: {str(e)[:600]}")
    print("TODO OK" if not bad else f"{bad} FALLOS")
    sys.exit(1 if bad else 0)

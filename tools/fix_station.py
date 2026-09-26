"""Correct the embedded station dataset in index.html against the official floor maps.

References (checked 2026-09-26):
  - 東京駅構内MAP 1F/B1 (Tokyo Station City, 2026-08-01)
  - JR東海 東京駅 新幹線構内図 (2026-01-23)
  - らくらくおでかけネット 東京駅 構内図
Node ids below refer to the dataset currently embedded in index.html.
Run:  python3 tools/fix_station.py   (rewrites index.html in place; idempotent)
"""
import json, math, re, collections, pathlib

HTML = pathlib.Path(__file__).resolve().parent.parent / "index.html"
s = HTML.read_text()
m = re.search(r'(<script type="application/json" id="station-data">)(.*?)(</script>)', s, re.S)
D = json.loads(m.group(2).replace("<\\/", "</"))
N, E, NAMES = D["nodes"], D["edges"], D["names"]
H = {int(k): v for k, v in D["H"].items()}
TH = D["theta"]; U0, U1, V0, V1 = D["rect"]
Y1F, YB1, YPLAT, Y3F = H[0], H[-1], H[2], H[3]

adj = collections.defaultdict(list)
for i, (a, b, k, nm, ind) in enumerate(E): adj[a].append((b, i)); adj[b].append((a, i))
gate = {g[0]: g for g in D["gates"]}
def rot(x, z): return (x * math.cos(-TH) - z * math.sin(-TH), x * math.sin(-TH) + z * math.cos(-TH))
def in_station(n): u, v = rot(N[n][0], N[n][2]); return U0 < u < U1 and V0 < v < V1
def flood(seed, y, ok=lambda i, v: True):
    seen = {seed}; st = [seed]
    while st:
        u = st.pop()
        for v, i in adj[u]:
            if E[i][2] != 0 or v in seen or abs(N[v][1] - y) > .3 or not ok(i, v): continue
            seen.add(v); st.append(v)
    return seen
def relevel(nodes, y):
    for n in nodes: N[n][1] = y
    return len(nodes)
log = []

# 1) 新幹線 南側の乗換口一帯 (東北新幹線南のりかえ口 / 東海道新幹線 中央・南乗換口 / 新幹線乗り換え改札 南) は 1F
if abs(N[5123][1] - YB1) < .3:
    region = {n for n in flood(5123, YB1) if in_station(n)}
    log.append(f"shinkansen south concourse -> 1F: {relevel(region, Y1F)} nodes")
# 2) 新幹線八重洲中央北口 / 日本橋口 付近はホーム高さではなく 1F
for seed in (5707, 5063):
    if abs(N[seed][1] - YPLAT) < .3:
        log.append(f"gate area {seed} -> 1F: {relevel(flood(seed, YPLAT), Y1F)} nodes")
# 3) 京葉線への八重洲連絡通路（動く歩道）は地上寄りの通路 → 地下1階相当にそろえ、京葉八重洲口付近で地下3・4階へ下りる
if abs(N[3315][1] - H[-3]) < .3:
    log.append(f"Keiyo connecting passage -> B1: {relevel(flood(3315, H[-3]), YB1)} nodes")
# 4) 丸の内地下中央口の外側（東京駅(改札外)）は地下1階
if abs(N[5327][1] - Y1F) < .3:
    reg = flood(5327, Y1F, lambda i, v: E[i][3] >= 0 and NAMES[E[i][3]] == "東京駅(改札外)")
    log.append(f"Marunouchi underground concourse -> B1: {relevel(reg, YB1)} nodes")
# 5) 中央線ホーム(1・2番線)は 3F
p12 = next(p for p in D["plats"] if p["ref"] == "1;2" and p["y"] > 5)
def inpoly(x, z, ring):
    c = False
    for i in range(len(ring)):
        x1, z1 = ring[i]; x2, z2 = ring[i - 1]
        if (z1 > z) != (z2 > z) and x < (x2 - x1) * (z - z1) / (z2 - z1 + 1e-12) + x1: c = not c
    return c
if abs(p12["y"] - YPLAT) < .3:
    on = {n for n in range(len(N)) if abs(N[n][1] - YPLAT) < .3 and inpoly(N[n][0], N[n][2], p12["ring"])}
    grow = set(on)
    for n in on: grow |= flood(n, YPLAT, lambda i, v: inpoly(N[v][0], N[v][2], p12["ring"]))
    log.append(f"Chuo platform -> 3F: {relevel(grow, Y3F)} nodes"); p12["y"] = Y3F
    def near_ring(x, z, d=9):
        for i in range(len(p12["ring"]) - 1):
            (x1, z1), (x2, z2) = p12["ring"][i], p12["ring"][i + 1]
            dx, dz = x2 - x1, z2 - z1; L = dx * dx + dz * dz
            t = 0 if L == 0 else max(0, min(1, ((x - x1) * dx + (z - z1) * dz) / L))
            if math.hypot(x - x1 - dx * t, z - z1 - dz * t) < d: return True
        return False
    nt = 0
    for T in D["tracks"]:
        if T["y"] > 5 and sum(near_ring(x, z) for x, z in T["pts"]) >= max(1, len(T["pts"]) // 2):
            T["y"] = round(Y3F - 1.1, 2); nt += 1
    log.append(f"Chuo tracks raised: {nt}")

# 5b) 東京ラーメンストリートは一番街の地下1階（OSM ではホーム高さの孤立片になっていた）
if "東京ラーメンストリート" in NAMES:
    ri = NAMES.index("東京ラーメンストリート")
    seeds = [a for a, b, k, nm, ind in E if nm == ri and k == 0]
    if seeds: log.append(f"ramen street -> B1: {relevel(flood(seeds[0], N[seeds[0]][1]), YB1)}")

# steps / escalator interiors: re-interpolate between their (possibly moved) ends
flat_deg = collections.Counter()
for a, b, k, nm, ind in E:
    if k in (0, 3): flat_deg[a] += 1; flat_deg[b] += 1
interior = [n for n in range(len(N)) if flat_deg[n] == 0 and sum(1 for v, i in adj[n] if E[i][2] in (1, 2)) == 2]
for _ in range(200):
    for n in interior:
        nb = [v for v, i in adj[n] if E[i][2] in (1, 2)]
        d = [math.dist((N[n][0], N[n][2]), (N[v][0], N[v][2])) + 1e-6 for v in nb]
        N[n][1] = (N[nb[0]][1] * d[1] + N[nb[1]][1] * d[0]) / (d[0] + d[1])

# 6) 改札名と種別（JR東海図の正式名に合わせる）
def near(n, name):
    g = next((g for g in D["gates"] if g[2] == name), None)
    return math.dist(N[n], N[g[0]]) if g else 1e9
for g in D["gates"]:
    n, cls, name = g
    if cls == "tr:JRE|JRC":
        g[2] = "新幹線中央乗換口（東海道新幹線）" if near(n, "八重洲中央口") < near(n, "八重洲南口") else "新幹線南乗換口（東海道新幹線）"
    if "新幹線八重洲" in name: g[1] = "exit:JRC"
    if name == "丸の内中央口": g[2] = "丸の内中央口（IC専用・9:30〜17:00）"
    if name.startswith("東海道新幹線・東北新幹線乗り換え改札"): g[2] = name.replace("乗り換え改札", "乗換口")
# 7) 丸の内北口・丸の内南口の在来線改札（地図データに無いため出入口の位置に追加）
have = {g[0] for g in D["gates"]}
for key, name in (("exit_mn", "丸の内北口"), ("exit_ms", "丸の内南口")):
    n = D["spots"].get(key)
    if n is not None and n not in have: D["gates"].append([n, "exit:JRE", name]); log.append(f"gate added: {name}")
# 7b) グランスタ地下北口（JR東日本の改札）が無く、地下の北自由通路から改札内へ素通りできていた
if "東京駅;グランスタ地下北口" in NAMES:
    gi = NAMES.index("東京駅;グランスタ地下北口"); cnt = collections.Counter()
    for a, b, k, nm, ind in E:
        if nm == gi: cnt[a] += 1; cnt[b] += 1
    for n, c in cnt.items():
        if c >= 2 and n not in have: D["gates"].append([n, "exit:JRE", "グランスタ地下北口"]); have.add(n); log.append("gate added: グランスタ地下北口")
# 7c) JR東海図: 八重洲側の新幹線改札は 北口・中央北口・中央南口・南口 の4つ。名前の無い改札(八重洲中央口の隣)は中央南口、
#     南口は OSM に無いので 1F コンコース南端と八重洲南口前の歩道の間に置く
for g in D["gates"]:
    if g[1] == "exit:JRC" and not g[2] and math.dist(N[g[0]], N[D["spots"]["exit_yc"]]) < 15: g[2] = "新幹線八重洲中央南口"
if not any(g[2] == "新幹線八重洲南口" for g in D["gates"]):
    jrc = set(D["sealed"]["JRC"])
    ys = N[D["spots"]["exit_ys"]]
    inner = min((n for n in jrc if abs(N[n][1] - Y1F) < .3), key=lambda n: math.dist(N[n], ys))
    outer = min((n for n in range(len(N)) if n not in jrc and n not in have and abs(N[n][1] - Y1F) < .3 and adj[n] and N[n][2] > N[inner][2] + 3
                 and not any(E[i][3] >= 0 and "通路" in NAMES[E[i][3]] for v, i in adj[n])), key=lambda n: math.dist(N[n], N[inner]))
    N.append([round((N[inner][0] + N[outer][0]) / 2, 2), Y1F, round((N[inner][2] + N[outer][2]) / 2, 2)]); g_ = len(N) - 1
    E.extend([[inner, g_, 0, -1, 1], [g_, outer, 0, -1, 1]]); adj[inner].append((g_, len(E) - 2)); adj[g_] += [(inner, len(E) - 2), (outer, len(E) - 1)]; adj[outer].append((g_, len(E) - 1))
    D["gates"].append([g_, "exit:JRC", "新幹線八重洲南口"]); have.add(g_); log.append(f"gate added: 新幹線八重洲南口 between {inner} and {outer}")
gate = {g[0]: g for g in D["gates"]}

# 8) 孤立した小さな通路片（例: 新幹線八重洲中央北口の改札前）を、同じ高さで 5m 以内の本体通路へつなぐ
adj = collections.defaultdict(list)
for i, (a_, b_, k, nm, ind) in enumerate(E): adj[a_].append((b_, i)); adj[b_].append((a_, i))
comp = [-1] * len(N); sizes = []
for s0 in range(len(N)):
    if comp[s0] >= 0: continue
    st = [s0]; comp[s0] = len(sizes); c = 0
    while st:
        u = st.pop(); c += 1
        for v, i in adj[u]:
            if comp[v] < 0: comp[v] = comp[s0]; st.append(v)
    sizes.append(c)
main = sizes.index(max(sizes)); linked = 0
existing = {(min(a_, b_), max(a_, b_)) for a_, b_, *_ in E}
for c in range(len(sizes)):
    if c == main or sizes[c] > 60: continue
    members = [n for n in range(len(N)) if comp[n] == c]
    best = None
    for n in members:
        for q in range(len(N)):
            if comp[q] != main or abs(N[q][1] - N[n][1]) > .3: continue
            d = math.dist((N[n][0], N[n][2]), (N[q][0], N[q][2]))
            if d < 5 and (best is None or d < best[0]): best = (d, n, q)
    if best and (min(best[1], best[2]), max(best[1], best[2])) not in existing:
        E.append([best[1], best[2], 0, -1, 1]); linked += 1
log.append(f"isolated walkway pieces linked: {linked}")

# 9) 新幹線の改札で、改札内側（JR東海 / JR東日本新幹線エリア）から届かないものを 15m 以内の改札内通路へつなぐ
import heapq
adj = collections.defaultdict(list)
for i, (a_, b_, k, nm, ind) in enumerate(E):
    w = math.dist(N[a_], N[b_]); adj[a_].append((b_, w)); adj[b_].append((a_, w))
gate_nodes = {g[0] for g in D["gates"]}
def reach(src):
    d = {src: 0}; pq = [(0, src)]
    while pq:
        dd, u = heapq.heappop(pq)
        if dd > d[u]: continue
        for v, w in adj[u]:
            if v in gate_nodes: continue
            if dd + w < d.get(v, 1e18): d[v] = dd + w; heapq.heappush(pq, (dd + w, v))
    return d
stand_of = {p["sys"]: p["stand"] for p in D["plats"] if p["sys"] in ("JRC", "JRE_SHIN")}
fixed = 0
for g in D["gates"]:
    sysname = g[1].split(":")[1] if g[1].startswith("exit:") else None
    if sysname not in stand_of: continue
    R = reach(stand_of[sysname])
    nbs = [v for v, _ in adj[g[0]]]
    if any(v in R for v in nbs): continue
    best = min(((math.dist(N[v], N[q]), v, q) for v in nbs for q in R if abs(N[q][1] - N[v][1]) < .3), default=None)
    if best and best[0] < 15:
        E.append([best[1], best[2], 0, -1, 1]); fixed += 1
log.append(f"shinkansen gates reconnected to their concourse: {fixed}")

# 10) 新幹線の 1F コンコースはホームの下で一続き（公式図）。階段下どうしが 1F だけで遠回りになる所を直結する
sealed = {n: sy for sy, lst in D["sealed"].items() for n in lst}
bottoms = set()
for a_, b_, k, nm, ind in E:
    if k in (1, 2):
        for lo, hi in ((a_, b_), (b_, a_)):
            if abs(N[lo][1] - Y1F) < .3 and N[hi][1] > 5 and sealed.get(lo): bottoms.add(lo)
low = collections.defaultdict(list)
for a_, b_, k, nm, ind in E:
    if N[a_][1] < 1 and N[b_][1] < 1 and N[a_][1] > -1 and N[b_][1] > -1:
        w = math.dist(N[a_], N[b_]); low[a_].append((b_, w)); low[b_].append((a_, w))
def d1f(src):
    d = {src: 0}; pq = [(0, src)]
    while pq:
        dd, u = heapq.heappop(pq)
        if dd > d[u] or dd > 200: continue
        for v, w in low[u]:
            if dd + w < d.get(v, 1e18): d[v] = dd + w; heapq.heappush(pq, (dd + w, v))
    return d
bl = sorted(bottoms); added = 0
for i, u in enumerate(bl):
    du = d1f(u)
    for v in bl[i + 1:]:
        if sealed.get(u) != sealed.get(v): continue
        straight = math.dist((N[u][0], N[u][2]), (N[v][0], N[v][2]))
        if straight < 60 and du.get(v, 1e18) > 1.8 * straight + 5:
            E.append([u, v, 0, -1, 1]); added += 1
log.append(f"shinkansen 1F concourse links added: {added}")

# 10b) 付け替えで高低差が無くなった階段/エスカレーターは平らな通路に。同じ位置・同じ高さで分断された点はつなぐ
flatten = 0
for e in E:
    if e[2] == 2 and abs(N[e[0]][1] - N[e[1]][1]) < .6: e[2] = 0; flatten += 1   # 高低差ゼロのエスカレーターだけ（階段は小さな段差として残す）
pos = collections.defaultdict(list)
for n in range(len(N)): pos[(round(N[n][0], 1), round(N[n][1], 1), round(N[n][2], 1))].append(n)
existing = {(min(a_, b_), max(a_, b_)) for a_, b_, *_ in E}
twins = 0
for lst in pos.values():
    for a_, b_ in zip(lst, lst[1:]):
        if (min(a_, b_), max(a_, b_)) not in existing: E.append([a_, b_, 0, -1, 1]); twins += 1
log.append(f"flattened level stairs: {flatten}, joined duplicate points: {twins}")

# 10c) 「平らな通路」なのに 1 階分近く上下する区間: 勾配 1/12 より急なら階段扱い（ベビーカーが通らないように）
steep = 0
for e in E:
    if e[2] != 0: continue
    dy = abs(N[e[0]][1] - N[e[1]][1]); hz = math.dist((N[e[0]][0], N[e[0]][2]), (N[e[1]][0], N[e[1]][2]))
    if dy > 1.5 and hz < 12 * dy: e[2] = 1; steep += 1
log.append(f"steep 'flat' segments -> stairs: {steep}")
if "東京ラーメンストリート" in NAMES:
    ri = NAMES.index("東京ラーメンストリート"); cnt = collections.Counter()
    for a, b, k, nm, ind in E:
        if nm == ri: cnt[a] += 1; cnt[b] += 1
    if cnt: D["spots"]["ramen"] = max(cnt, key=lambda n: (cnt[n], -n))

# 11) エレベーター（OSM highway=elevator）: 近くの各階の通路を縦につなぐ（ベビーカー・車いすルート用, kind 4）
DATA = HTML.parent / "tools" / "data"
LAT0, LON0 = D["proj"]["lat0"], D["proj"]["lon0"]
KX, KZ = math.cos(math.radians(LAT0)) * 111320.0, 110540.0
def P(lat, lon): return ((lon - LON0) * KX, -(lat - LAT0) * KZ)
def parse_lv(v):
    out = []
    for t in str(v or "").split(";"):
        try: out.append(float(t))
        except ValueError: pass
    return out
flat_deg = collections.Counter()
for a_, b_, k, nm, ind in E:
    if k in (0, 3): flat_deg[a_] += 1; flat_deg[b_] += 1
walk_nodes = [n for n in range(len(N)) if flat_deg[n]]
existing = {(min(a_, b_), max(a_, b_)) for a_, b_, *_ in E}
added = 0
for e in json.loads((DATA / "elevators.json").read_text())["elements"]:
    t = e.get("tags", {})
    if e["type"] == "node": x, z = P(e["lat"], e["lon"])
    elif e.get("geometry") and t.get("highway") == "elevator":
        g = e["geometry"]; x, z = P(sum(q["lat"] for q in g) / len(g), sum(q["lon"] for q in g) / len(g))
    else: continue
    lvs = [int(L) for L in parse_lv(t.get("level"))]
    want = [H[L] for L in range(min(lvs) - 1, max(lvs) + 2) if L in H] if lvs else []   # 1階分の表記ゆれを許容
    groups = {}
    for n in walk_nodes:
        d = math.hypot(N[n][0] - x, N[n][2] - z)
        if d > 8: continue
        y = round(N[n][1], 1)
        if want and not any(abs(y - w) < .5 for w in want): continue
        if y not in groups or d < groups[y][0]: groups[y] = (d, n)
    ys = sorted(groups)
    for y0, y1 in zip(ys, ys[1:]):
        if y1 - y0 < 2: continue
        a_, b_ = groups[y0][1], groups[y1][1]
        if (min(a_, b_), max(a_, b_)) in existing: continue
        E.append([a_, b_, 4, -1, 1]); existing.add((min(a_, b_), max(a_, b_))); added += 1
log.append(f"elevator links: {added}")

def seg_dist(p, a, b):
    ax, az = a; bx, bz = b; px, pz = p; dx, dz = bx - ax, bz - az; L = dx * dx + dz * dz
    k = 0 if L == 0 else max(0, min(1, ((px - ax) * dx + (pz - az) * dz) / L))
    return math.hypot(px - (ax + dx * k), pz - (az + dz * k))

# 11b) 公式のバリアフリー構内図では全ホームにエレベーターがある。OSM に無いホームは「位置推定」のエレベーターで補う
EST = "エレベーター（位置は推定）"
if EST not in NAMES: NAMES.append(EST)
est_idx = NAMES.index(EST)
adjk = collections.defaultdict(list)
for i, (a_, b_, k, nm, ind) in enumerate(E): adjk[a_].append((b_, k)); adjk[b_].append((a_, k))
virt = 0
for p in D["plats"]:
    ring = p["ring"]; py = p["y"]
    on = [n for n in walk_nodes if abs(N[n][1] - py) < .3 and inpoly(N[n][0], N[n][2], ring)]
    if not on: continue
    if any(k == 4 for n in on for v, k in adjk[n]): continue
    # where do this platform's stairs / escalators land?
    lands = [(n, v) for n in on for v, k in adjk[n] if k in (1, 2) and N[v][1] < py - 2]
    tops = collections.defaultdict(list)
    for n, v in lands: tops[n].append(v)
    # follow stair chains down to their bottom walkway node
    def bottom(v, came):
        seen = {came}
        while flat_deg[v] == 0:
            nxt = [w for w, k in adjk[v] if k in (1, 2) and w not in seen]
            if not nxt: break
            seen.add(v); v = nxt[0]
        return v
    best = None
    for n, vs in tops.items():
        for v in vs:
            b = bottom(v, n)
            if N[b][1] >= py - 2: continue
            cands = [q for q in walk_nodes if abs(N[q][1] - N[b][1]) < .3 and math.hypot(N[q][0] - N[n][0], N[q][2] - N[n][2]) < 18]
            for q in cands:
                d = math.hypot(N[q][0] - N[n][0], N[q][2] - N[n][2])
                if best is None or d < best[0]: best = (d, n, q)
    if best:
        E.append([best[1], best[2], 4, est_idx, 1]); virt += 1
log.append(f"estimated platform elevators: {virt}")

# 11c) 駅構内・地下で、階段/エスカレーターしか無い上下移動に、近くのエレベーター迂回が無ければ推定エレベーターを補う
def stroller_graph():
    g = collections.defaultdict(list)
    for a_, b_, k, nm, ind in E:
        if k in (0, 3, 4):
            w = math.dist(N[a_], N[b_]); g[a_].append((b_, w)); g[b_].append((a_, w))
    return g
SG = stroller_graph()
def reach_within(src, dst, lim=250):
    d = {src: 0}; pq = [(0, src)]
    while pq:
        dd, u = heapq.heappop(pq)
        if u == dst: return True
        if dd > d[u] or dd > lim: continue
        for v, w in SG[u]:
            if v in gate_nodes_all and v != dst: continue          # 改札の外を回る迂回は数えない
            if dd + w < d.get(v, 1e18): d[v] = dd + w; heapq.heappush(pq, (dd + w, v))
    return False
gate_nodes_all = {g[0] for g in D["gates"]}
conn = []
for i, (a_, b_, k, nm, ind) in enumerate(E):
    if k not in (1, 2): continue
    for top, nxt in ((a_, b_), (b_, a_)):
        if flat_deg[top] == 0: continue
        v, prev, seen = nxt, top, {top}
        while flat_deg[v] == 0:
            nx = [w for w, kk in adjk[v] if kk in (1, 2) and w not in seen]
            if not nx: break
            seen.add(v); prev, v = v, nx[0]
        if flat_deg[v] and abs(N[v][1] - N[top][1]) >= 2: conn.append((top, v))
done = set(); est2 = 0
for top, bot in conn:
    key = (min(top, bot), max(top, bot))
    if key in done: continue
    done.add(key)
    inside = in_station(top) or in_station(bot) or min(N[top][1], N[bot][1]) < -1
    if not inside or reach_within(top, bot): continue
    E.append([top, bot, 4, est_idx, 1]); est2 += 1
    w = math.dist(N[top], N[bot]); SG[top].append((bot, w)); SG[bot].append((top, w))
log.append(f"estimated connector elevators: {est2}")

# 11d) 改札の外（自由通路）と改札内をエレベーターで直結しない: 改札を通らずに外から JR ホームへ行ける経路があれば、
#      その経路上でいちばんホーム寄りのエレベーター区間を外す（無くなるまで繰り返す）
def leak_path():
    gn = {g[0] for g in D["gates"]}; sl = {n for l in D["sealed"].values() for n in l}
    ad = collections.defaultdict(list)
    for i, (a_, b_, k, nm, ind) in enumerate(E): ad[a_].append((b_, i)); ad[b_].append((a_, i))
    used = set(D["linePlat"].values())
    goal = {p["stand"] for p in D["plats"] if p["sys"] == "JRE" and p["key"] in used}
    src = D["spots"]["yaechika"]; prev = {src: None}; q = collections.deque([src])
    while q:
        u = q.popleft()
        if u in goal:
            out = []
            while prev[u]: u, i = prev[u]; out.append(i)
            return out[::-1]
        for v, i in ad[u]:
            if v not in prev and v not in gn and v not in sl: prev[v] = (u, i); q.append(v)
    return None
removed = 0
while (lp := leak_path()):
    ev = [i for i in lp if E[i][2] == 4]
    if not ev: log.append("WARNING: gate-free path to a JR platform without elevators: " + str(lp[-5:])); break
    del E[ev[-1]]; removed += 1
log.append(f"free<->in-station elevator links removed: {removed}")
# 11e) 東京駅の外の地下鉄駅（大手町・有楽町など）は改札の位置データが不完全で、改札を通らずホームに着いてしまう。
#      そのホームは「改札データなし（FREE）」として扱い、改札を通ったふりをしない
_gn = {g[0] for g in D["gates"]}; _sl = {n for l in D["sealed"].values() for n in l}
_ad = collections.defaultdict(list)
for a_, b_, *_ in E: _ad[a_].append(b_); _ad[b_].append(a_)
_seen = {D["spots"]["yaechika"]}; _st = list(_seen)
while _st:
    u = _st.pop()
    for v in _ad[u]:
        if v not in _seen and v not in _gn and v not in _sl: _seen.add(v); _st.append(v)
opened = [p["key"] for p in D["plats"] if not p["sys"].startswith("JR") and p["sys"] != "FREE" and p["stand"] in _seen]
for p in D["plats"]:
    if p["key"] in opened: p["sys"] = "FREE"
log.append(f"metro platforms without gate data -> FREE: {len(opened)}")

# 12) お店（OSM shop / 飲食）: 駅の通路に面したものを、通路脇の半透明の区画として配置
CAT = [("food", ("restaurant", "fast_food", "food_court", "pub", "bar")), ("cafe", ("cafe", "ice_cream")),
       ("gift", ("gift", "confectionery", "bakery", "department_store", "mall", "variety_store", "chocolate", "pastry", "tea", "alcohol", "deli")),
       ("conv", ("convenience", "supermarket", "kiosk"))]
flat_edges = [(a_, b_) for a_, b_, k, *_ in E if k == 0 and abs(N[a_][1] - N[b_][1]) < .3]
shops = []
for e in json.loads((DATA / "shops.json").read_text())["elements"]:
    t = e.get("tags", {}); kind = t.get("shop") or t.get("amenity")
    if not kind or kind in ("ticket", "hairdresser"): continue
    if e["type"] == "node": x, z = P(e["lat"], e["lon"])
    else:
        g = e.get("geometry") or [q for mbr in e.get("members", []) for q in (mbr.get("geometry") or [])]
        if not g: continue
        x, z = P(sum(q["lat"] for q in g) / len(g), sum(q["lon"] for q in g) / len(g))
    lv = parse_lv(t.get("level"))
    best = None
    for a_, b_ in flat_edges:
        y = N[a_][1]
        if lv and not any(int(L) in H and abs(H[int(L)] - y) < .5 for L in lv): continue
        d = seg_dist((x, z), (N[a_][0], N[a_][2]), (N[b_][0], N[b_][2]))
        if best is None or d < best[0]: best = (d, a_, b_)
    if not best or best[0] > 14: continue
    d, a_, b_ = best
    ax, az, bx, bz = N[a_][0], N[a_][2], N[b_][0], N[b_][2]
    dx, dz = bx - ax, bz - az; L = math.hypot(dx, dz) or 1
    ux, uz = dx / L, dz / L
    k = max(0, min(1, ((x - ax) * ux + (z - az) * uz) / L))
    px, pz = ax + ux * k * L, az + uz * k * L
    side = 1 if (-(uz) * (x - px) + ux * (z - pz)) >= 0 else -1
    off = 1.95   # 通路の壁の内側に沿った店先として置く（壁の外に置くと POV で見えない）
    cx, cz = px - uz * off * side, pz + ux * off * side
    cat = next((c for c, ks in CAT if kind in ks), "shop")
    shops.append([round(cx, 1), round(N[a_][1], 2), round(cz, 1), round(math.atan2(ux, uz), 3), cat, t.get("name", ""), side])
# お店ゾーン（改札内は OSM に個別店舗がほぼ無い）: ゾーン名の付いた通路の両側に店先を並べる
ZONES = [("ラーメン", "food"), ("おかし", "gift"), ("キャラクター", "shop"), ("グランスタ", "gift"), ("一番街", "gift"), ("八重北", "food"),
         ("黒塀", "food"), ("グルメ", "food"), ("地下街", "shop"), ("ヤエチカ", "shop"), ("地下1番通り", "shop"), ("地下2番通り", "food"), ("エキュート", "gift")]
taken = [(q[0], q[2], q[1]) for q in shops]
zone_n = 0
for a_, b_, k, nm, ind in E:
    if k != 0 or nm < 0 or abs(N[a_][1] - N[b_][1]) > .3: continue
    zname = NAMES[nm]; cat = next((c for key, c in ZONES if key in zname), None)
    if not cat: continue
    ax, az, bx, bz, y = N[a_][0], N[a_][2], N[b_][0], N[b_][2], N[a_][1]
    L = math.hypot(bx - ax, bz - az)
    if L < 4: continue
    ux, uz = (bx - ax) / L, (bz - az) / L
    t = 2.5
    while t < L - 2:
        for side in (1, -1):
            cx, cz = ax + ux * t - uz * 1.95 * side, az + uz * t + ux * 1.95 * side
            if any(abs(q[2] - y) < .5 and math.hypot(q[0] - cx, q[1] - cz) < 3.5 for q in taken): continue
            alt = cat if cat != "gift" or (int(t / 5) + side) % 3 else "food"
            shops.append([round(cx, 1), round(y, 2), round(cz, 1), round(math.atan2(ux, uz), 3), alt, zname.split(";")[0], side]); taken.append((cx, cz, y)); zone_n += 1
        t += 5
log.append(f"shop-zone storefronts: {zone_n}")
D["shops"] = shops
log.append(f"shops placed: {len(shops)} " + str(collections.Counter(q[4] for q in shops)))

# ------------------------------------------------ enclosure (walls / floors / ceilings) rebuilt from corrected heights
LV = sorted(H.items())
def level_of(y): return min(LV, key=lambda kv: abs(kv[1] - y))[0]
CELL = 1.5
def seg_dist(p, a, b):
    ax, az = a; bx, bz = b; px, pz = p; dx, dz = bx - ax, bz - az; L = dx * dx + dz * dz
    k = 0 if L == 0 else max(0, min(1, ((px - ax) * dx + (pz - az) * dz) / L))
    return math.hypot(px - (ax + dx * k), pz - (az + dz * k))
def enclosed(L, u, v):
    if L <= -1: return True
    if L in (0, 1): return U0 < u < U1 and V0 < v < V1
    return False
def cells_of(a, b, r):
    ua, va = rot(*a); ub, vb = rot(*b)
    out = []
    for i in range(math.floor((min(ua, ub) - r) / CELL), math.floor((max(ua, ub) + r) / CELL) + 1):
        for j in range(math.floor((min(va, vb) - r) / CELL), math.floor((max(va, vb) + r) / CELL) + 1):
            if seg_dist(((i + .5) * CELL, (j + .5) * CELL), (ua, va), (ub, vb)) <= r: out.append((i, j))
    return out
cells = collections.defaultdict(dict); shaft = collections.defaultdict(set); hole = collections.defaultdict(set)
for a, b, k, nm, ind in E:
    A, B = N[a], N[b]
    if k in (3, 4): continue
    if k == 0:
        if abs(A[1] - B[1]) > .3: continue
        L = level_of(A[1]); mu, mv = rot((A[0] + B[0]) / 2, (A[2] + B[2]) / 2)
        if not enclosed(L, mu, mv): continue
        for c in cells_of((A[0], A[2]), (B[0], B[2]), 2.4): cells[L][c] = 1
    else:
        lo, hi = min(A[1], B[1]), max(A[1], B[1])
        if hi - lo < .6: continue
        cs = cells_of((A[0], A[2]), (B[0], B[2]), (1.6 if k == 1 else 1.2) + .4)
        for L, y in H.items():
            if lo - .2 <= y + 3.4 and y < hi - .3: shaft[L].update(cs)
            if lo + .3 < y < hi + .2: hole[L].update(cs)
# お店の区画: 通路の壁を開けて奥行き 4.5m の店舗スペースにする（外周だけ壁）
for x, y, z, yaw, cat, nm, side in D["shops"]:
    L = level_of(y)
    ux, uz = math.sin(yaw), math.cos(yaw); nx, nz = -uz * side, ux * side
    for t in (-1.8, -0.9, 0, 0.9, 1.8):
        for dpt in (-0.6, 0.3, 1.2, 2.1, 3.0, 3.9):
            px, pz = x + ux * t + nx * dpt, z + uz * t + nz * dpt
            u, v = rot(px, pz)
            if not enclosed(L, u, v): continue
            c = (math.floor(u / CELL), math.floor(v / CELL))
            cells[L].setdefault(c, 1)
for p in D["plats"]:
    L = level_of(p["y"])
    if L >= 1: continue
    ru = [rot(x, z) for x, z in p["ring"]]
    if not enclosed(L, *ru[0]): continue
    for i in range(math.floor((min(u for u, v in ru) - 7) / CELL), math.floor((max(u for u, v in ru) + 7) / CELL) + 1):
        for j in range(math.floor((min(v for u, v in ru) - 7) / CELL), math.floor((max(v for u, v in ru) + 7) / CELL) + 1):
            q = ((i + .5) * CELL, (j + .5) * CELL)
            if inpoly(q[0], q[1], ru): cells[L][(i, j)] = 1
            elif (i, j) not in cells[L] and min(seg_dist(q, ru[k], ru[k - 1]) for k in range(len(ru))) < 6.2: cells[L][(i, j)] = 2
def rects(cs):
    left = set(cs); out = []
    for (i, j) in sorted(cs):
        if (i, j) not in left: continue
        i2 = i
        while (i2 + 1, j) in left: i2 += 1
        j2 = j
        while all((k, j2 + 1) in left for k in range(i, i2 + 1)): j2 += 1
        for k in range(i, i2 + 1):
            for mm in range(j, j2 + 1): left.discard((k, mm))
        out.append((i, j, i2, j2))
    return out
def uvbox(i, j, i2, j2):
    u0, v0, u1, v1 = i * CELL, j * CELL, (i2 + 1) * CELL, (j2 + 1) * CELL
    return [round((u0 + u1) / 2, 2), round((v0 + v1) / 2, 2), round(u1 - u0, 2), round(v1 - v0, 2)]
enc = {"floor": [], "tfloor": [], "ceil": [], "wall": []}
walls = collections.defaultdict(list)
for L, cs in cells.items():
    y = H[L]; ch = 3.4 if L != -5 else 4.2
    for r in rects({c for c, k in cs.items() if k == 1 and c not in hole[L]}): enc["floor"].append(uvbox(*r) + [y])
    for r in rects({c for c, k in cs.items() if k == 2}): enc["tfloor"].append(uvbox(*r) + [round(y - 1.9, 2)])
    for r in rects({c for c in cs if c not in shaft[L]}): enc["ceil"].append(uvbox(*r) + [round(y + ch, 2)])
    for (i, j), kind in cs.items():
        base = round(y - (1.9 if kind == 2 else 0), 1)
        for di, dj, side in ((1, 0, "e"), (-1, 0, "w"), (0, 1, "s"), (0, -1, "n")):
            if (i + di, j + dj) in cs: continue
            walls[(side, i if side in "ew" else j, base, round(y + ch, 1))].append(j if side in "ew" else i)
for (side, fixed, y0, y1), lst in walls.items():
    lst.sort(); runs = []; st = pr = lst[0]
    for k in lst[1:]:
        if k == pr + 1: pr = k; continue
        runs.append((st, pr)); st = pr = k
    runs.append((st, pr))
    for a, b in runs:
        if side in "ew":
            u = (fixed + (1 if side == "e" else 0)) * CELL
            enc["wall"].append([round(u, 2), round((a + b + 1) * CELL / 2, 2), .25, round((b - a + 1) * CELL, 2), y0, y1])
        else:
            v = (fixed + (1 if side == "s" else 0)) * CELL
            enc["wall"].append([round((a + b + 1) * CELL / 2, 2), round(v, 2), round((b - a + 1) * CELL, 2), .25, y0, y1])
D["enc"] = enc
for n in N: n[1] = round(n[1], 2)

out = json.dumps(D, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
HTML.write_text(s[:m.start(2)] + out + s[m.end(2):])
print("\n".join(log))
print("enc", {k: len(v) for k, v in enc.items()})

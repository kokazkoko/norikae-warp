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
    if k == 3: continue
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

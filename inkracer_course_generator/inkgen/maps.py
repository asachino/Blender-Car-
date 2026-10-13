"""maps.ts / landscape.ts / city.ts(cityMap) / mountain.ts(mountainMap) の移植：コースの中心線を作る"""
import math
from .three import (Vector3, CatmullRomCurve3, imul, u32, lcg_random, js_round, jhypot, jsign, js_str, to_fixed, clamp)

# ---------------------------------------------------------------- landscape.ts

TERRAIN_ROUTES = {"classic": "従来の地形", "ridge": "尾根を走る", "valley": "谷を渡る", "mountainside": "山腹を登る"}
LANDMARKS = {"crossing": "立体交差", "bridge": "長い橋", "tunnel": "トンネル", "tower": "タワーを望む直線"}


def landscape_rotation(seed):
    return u32(imul(seed, 1664525) + 1013904223) / 4294967296 * math.pi * 2


def landscape_height(x, z, p):
    rotation = landscape_rotation(p["seed"])
    phase = p["seed"] * .013
    a = (x * math.cos(rotation) + z * math.sin(rotation)) / p["size"]
    b = (-x * math.sin(rotation) + z * math.cos(rotation)) / p["size"]
    if p.get("layout") == "touge":
        relief = p["elevation"] / 24
        return 20 + relief * (p["size"] * .12 * (b + 1.8)
                              + p["size"] * .12 * math.exp(-(((a - .95) / .8) ** 2)) + 2.4 * math.sin(b * 4 + phase))
    relief = 12 + p["elevation"] * 1.5
    spine = .12 * math.sin(a * 2 + phase)
    route = p.get("terrainRoute")
    if route == "ridge":
        return 8 + relief * math.exp(-(((b - spine) / .48) ** 2)) + 4 * math.sin(a * 2 + phase)
    if route == "valley":
        return 10 + relief * (1 - math.exp(-((a / .3) ** 2))) + 4 * math.sin(b * 2 + phase)
    if route == "mountainside":
        return 12 + relief * (1 + math.tanh(a * 1.1)) + 5 * math.sin(b * 2 + phase)
    return (-1.45 + 3.8 * math.sin(x * .006 + phase) + 2.6 * math.cos(z * .008 - phase * .7)
            + 1.15 * math.sin((x + z) * .014 + phase * 1.7))


def feature_blend(u, feature):
    if u <= feature["start"] or u >= feature["end"]:
        return 0
    f = min(1, (u - feature["start"]) / .025, (feature["end"] - u) / .025)
    return f * f * (3 - 2 * f)


def _flat_curve(points):
    c = CatmullRomCurve3([Vector3(x, 0, z) for x, _, z in points], True, "centripetal")
    c.arcLengthDivisions = 2400
    return c


def straighten_vista(m, feature):
    curve = _flat_curve(m["points"])
    a = curve.getPointAt(feature["start"])
    b = curve.getPointAt(feature["end"])
    pts = m["points"]
    n = len(pts)
    par = m.get("parameters") or {}
    out = []
    for i in range(192):
        u = i / 192
        p = curve.getPointAt(u)
        original = p.clone()
        index = curve.getUtoTmapping(u, 0) * n
        j = int(math.floor(index))
        t = index - j
        y = pts[j % n][1] * (1 - t) + pts[(j + 1) % n][1] * t
        f = (u - feature["start"]) / (feature["end"] - feature["start"])
        if 0 < f < 1:
            blend = min(1, f / .25, (1 - f) / .25)
            p.lerp(a.clone().lerp(b, f), blend * blend * (3 - 2 * blend))
            if par.get("terrainRoute") and par["terrainRoute"] != "classic":
                y += landscape_height(p.x, p.z, par) - landscape_height(original.x, original.z, par)
        out.append([p.x, y, p.z])
    return out


def plan_landscape_features(m):
    par = m.get("parameters") or {}
    requested = par.get("landmarks") or []
    if not any(k != "crossing" for k in requested):
        return []
    curve = _flat_curve(m["points"])
    points = curve.getSpacedPoints(400)
    length = curve.getLength()
    # 各区間の「離れた所で道が 75 m 以内に戻ってくる」判定は i に依存しないので先に求める
    near = []
    for j in range(len(points)):
        pj = points[j]
        bad = False
        for k, p in enumerate(points):
            if min(abs(k - j), 400 - abs(k - j)) * length / 400 > 100 and p.distanceTo(pj) < 75:
                bad = True
                break
        near.append(bad)
    features = []
    for kind in ("tower", "bridge", "tunnel"):
        if kind not in requested:
            continue
        half = max(9, math.ceil((120 if kind == "bridge" else 80) / length * 400))
        best, best_score, tower_pos = -1, math.inf, None
        for i in range(55 + half, 345 - half):
            start, end = (i - half) / 400, (i + half) / 400
            if any(start < f["end"] + .04 and end > f["start"] - .04 for f in features):
                continue
            if any(near[j] for j in range(i - half, i + half + 1, 3)):
                continue
            a, b = points[i - half], points[i + half]
            position = None
            if kind == "tower":
                direction = b.clone().sub(a).normalize()
                for distance in (90, 130, 180, 240, 320):
                    p = b.clone().addScaledVector(direction, distance)
                    if all(q.distanceTo(p) > 45 for q in points):
                        p.y = landscape_height(p.x, p.z, par)
                        position = p.toArray()
                        break
                if position is None:
                    continue
            excess = 2 * half * length / 400 - a.distanceTo(b)
            ground = landscape_height(points[i].x, points[i].z, par)
            score = excess * (12 if kind == "tower" else 2) + (
                ground * .15 if kind == "bridge" else -ground * .1 if kind == "tunnel" else 0)
            if score < best_score:
                best_score, best, tower_pos = score, i, position
        if best < 0:
            continue
        feature = {"kind": kind, "start": (best - half) / 400, "end": (best + half) / 400}
        if kind == "tower":
            feature["position"] = tower_pos
        features.append(feature)
    return features


# ---------------------------------------------------------------- maps.ts

DEFAULT_PARAMETERS = {"seed": 73, "size": 350, "complexity": 3, "bends": 40, "elevation": 12, "crossings": 1,
                      "technicality": 35}
MAP_CONTROLS = [("size", "広さ", 260, 600, 10), ("complexity", "複雑さ", 1, 5, 1),
                ("bends", "カーブの強さ", 0, 100, 5), ("elevation", "高低差", 0, 24, 1),
                ("crossings", "立体交差数", 0, 3, 1), ("technicality", "テクニカル度", 0, 100, 5)]


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def parse_parameters(value):
    value = value or {}
    r = dict(DEFAULT_PARAMETERS)
    if value.get("layout") in ("city", "touge"):
        r["layout"] = value["layout"]
    for key, _l, mn, mx, step in MAP_CONTROLS + [("seed", "seed", 0, 999999, 1)]:
        n = value.get(key)
        if _is_num(n):
            r[key] = js_round(max(mn, min(mx, n)) / step) * step
    if value.get("terrainRoute") and value["terrainRoute"] in TERRAIN_ROUTES:
        r["terrainRoute"] = value["terrainRoute"]
    if isinstance(value.get("landmarks"), list):
        r["landmarks"] = [k for k in LANDMARKS if k in value["landmarks"]]
    if "crossing" in (r.get("landmarks") or []):
        r["crossings"] = max(1, r["crossings"])
    if r.get("layout") == "touge":
        for k, v in (("crossings", 0), ("terrainRoute", "mountainside"), ("landmarks", []), ("lanes", 2),
                     ("runoff", .75), ("guardrails", 0)):
            r[k] = v
    return r


def rotate_to_safe_start(points):
    best, best_score = 0, math.inf
    n = len(points)
    for i in range(n):
        prev, curr, nxt = points[(i + n - 1) % n], points[i], points[(i + 1) % n]
        ax, az, bx, bz = curr[0] - prev[0], curr[2] - prev[2], nxt[0] - curr[0], nxt[2] - curr[2]
        al, bl = max(.001, jhypot(ax, az)), max(.001, jhypot(bx, bz))
        angle = math.acos(max(-1, min(1, (ax * bx + az * bz) / (al * bl))))
        grade = abs((curr[1] - prev[1]) / al - (nxt[1] - curr[1]) / bl)
        score = angle + grade * .35
        if score < best_score:
            best_score, best = score, i
    return points[best:] + points[:best]


def round_corners(points, output_count=192):
    path = CatmullRomCurve3([Vector3(*p) for p in points], True, "centripetal")
    path.arcLengthDivisions = 2400
    count = max(8, output_count)
    rounded = path.getSpacedPoints(count)[:-1]
    size = len(rounded)
    for _ in range(400):
        sharp = []
        for i, p in enumerate(rounded):
            a = p.clone().sub(rounded[(i + size - 1) % size])
            b = rounded[(i + 1) % size].clone().sub(p)
            a.y = b.y = 0
            sharp.append(a.length() * b.length() * a.clone().add(b).length()
                         / max(1e-8, 2 * abs(a.x * b.z - a.z * b.x)) < 60)
        if not any(sharp):
            break
        new = []
        for i, p in enumerate(rounded):
            if not (sharp[i] or sharp[(i + size - 1) % size] or sharp[(i + 1) % size]):
                new.append(p)
            else:
                new.append(p.clone().multiplyScalar(.5).addScaledVector(rounded[(i + size - 1) % size], .25)
                           .addScaledVector(rounded[(i + 1) % size], .25))
        rounded = new
    return [p.toArray() for p in rounded]


def stabilize_map_points(points):
    return round_corners(points, len(points))


_TECH_NODES = [
    [-1.05, -.55], [-.55, -.55], [0, -.55], [.55, -.55], [1.05, -.55],
    [1.28, -.42], [1.35, -.15], [1.22, .12], [.96, .27], [.7, .23],
    [.56, .08], [.72, -.04], [.6, -.2], [.36, -.11], [.17, .04],
    [-.03, .2], [-.25, .34], [-.46, .25], [-.56, .08], [-.42, -.04],
    [-.63, -.16], [-.86, .02], [-1.06, .27], [-1.3, .34], [-1.45, .12],
    [-1.48, -.12], [-1.4, -.34], [-1.25, -.5],
]


def seeded_layout_value(seed, salt):
    h = u32(seed ^ salt)
    h = u32(imul(h ^ (h >> 16), 2246822519))
    h = u32(imul(h ^ (h >> 13), 3266489917))
    return u32(h ^ (h >> 16)) / 4294967296


def generate_map(value):
    p = parse_parameters(value)
    if p.get("layout") == "city":
        return city_map(p)
    if p.get("layout") == "touge":
        return mountain_map(p)
    random = lcg_random(p["seed"])
    rotation = random() * math.pi * 2
    phase = random() * math.pi * 2
    aspect = .62 + random() * .28
    irregularity = .015 + p["bends"] * .0012

    def layout_random(salt):
        return seeded_layout_value(p["seed"], salt)

    lanes = 4 if layout_random(11) < .34 else 2
    runoff = js_round((3.5 + layout_random(23) * 7.5) * 2) / 2
    guardrails = 1 if layout_random(37) < .28 else 2 if layout_random(41) < .55 else 0
    raw_layout = 5 if p["technicality"] >= 70 else int(math.floor(random() * 5))
    layout_index = 5 if raw_layout == 4 else raw_layout
    layouts = ["OVAL", "GRAND PRIX", "CLOVER", "SWITCHBACK", "", "TECHNICAL"]
    crossing_layout = int(math.floor(layout_random(101) * 6))
    cr = p["crossings"]
    cx_ = p["complexity"]
    span = 1.35 + .25 * cr
    skew = (layout_random(103) - .5) * (.25 + p["technicality"] * .0025)
    width = .75 + layout_random(107) * .4
    bend_depth = .3 + layout_random(113) * .7
    count = 96
    route = p.get("terrainRoute")
    raw = []
    for i in range(count):
        t = i / count * math.pi * 2
        wave = 1 + irregularity * (math.cos(t * (cx_ + 2) + phase) + .35 * math.sin(t * 3 - phase))
        c, s = math.cos(t), math.sin(t)
        x, z = c, s * aspect
        if layout_index == 5:
            nodes = _TECH_NODES
            segment = t / (math.pi * 2) * len(nodes)
            index = int(math.floor(segment)) % len(nodes)
            amount = segment - math.floor(segment)
            fr, to = nodes[index], nodes[(index + 1) % len(nodes)]
            bend = math.sin(amount * math.pi) * irregularity * .35
            x = fr[0] + (to[0] - fr[0]) * amount + bend * math.cos(t * 2 + phase)
            z = (fr[1] + (to[1] - fr[1]) * amount + bend * math.sin(t * 3 - phase)) * (aspect / .76)
        elif layout_index == 1:
            exponent = .58 - cx_ * .025
            x = jsign(c) * math.pow(abs(c), exponent) * 1.18
            z = jsign(s) * math.pow(abs(s), exponent) * aspect * .82
            x += math.sin(t * 2 + phase) * irregularity * .7
            z += math.sin(t * 4) * irregularity * .35
        elif layout_index == 2:
            petal = 1 + (.16 + p["bends"] * .0011) * math.cos(3 * t + phase)
            x = c * petal * 1.1
            z = s * petal * aspect
        elif layout_index == 3:
            x = c * (1 + .24 * math.cos(2 * t + phase))
            z = s * aspect + .18 * math.sin(4 * t + phase)
            x += .1 * math.sin(3 * t - phase)
        else:
            x = c * 1.22 + .12 * math.sin(2 * t + phase)
            z = s * aspect + .08 * math.sin(3 * t - phase)
        x *= wave
        z *= wave
        if cr:
            x = span * (c - .16 * math.sin(math.pi * c) + skew * (1 - c * c))
            z = (math.sin((cr + 1) * t) * aspect * width
                 * (1 + .22 * c + .16 * s + irregularity * math.cos((cx_ + 1) * t + phase)))
            if crossing_layout == 0:
                z += bend_depth * (c * c - .5)
            if crossing_layout == 1:
                radius = span / (.8 + layout_random(109) * .25)
                angle = x / radius
                x = (radius + z) * math.sin(angle)
                z = (radius + z) * math.cos(angle) - radius * .65
            if crossing_layout == 2:
                z += bend_depth * math.sin(c * math.pi)
            if crossing_layout == 3:
                z += .5 * c + bend_depth * .5 * math.cos(c * math.pi)
            if crossing_layout >= 4:
                loop = 1.15 if cr == 1 else .9 if cr == 2 else .8
                x = (1 if cr == 1 else 1.15) * (c + loop * math.cos((cr + 1) * t))
                z = width * (s + loop * math.sin((cr + 1) * t))
                x += (.15 + p["technicality"] * .001) * math.sin(z * (1.5 + cx_ * .1) + phase)
                z *= .95 + .15 * math.cos(x + phase)
                if crossing_layout == 5:
                    x += .2 * z * z - .2
                    z *= .8
        crossing_wave = math.sin(t * (cr if crossing_layout >= 4 else 1))
        lift = .7
        y = p["elevation"] * .25 * (1 + math.sin(t * 2 + phase)) + (
            (18 + p["elevation"]) * lift * (1 + crossing_wave) if cr else 0)
        if route == "ridge":
            z = z * .65 + .12 * math.sin(x * 2 + p["seed"] * .013)
        if route == "mountainside":
            x += .12 * math.sin(z * 2 + p["seed"] * .013)
        route_size = max(p["size"], (300 if crossing_layout >= 4 else 200) + cr * 75) if cr else p["size"]
        wX, wZ = x * route_size, z * route_size
        wx = wX * math.cos(rotation) - wZ * math.sin(rotation)
        wz = wX * math.sin(rotation) + wZ * math.cos(rotation)
        terrain_y = landscape_height(wx, wz, p) + .95 if route and route != "classic" else 0
        raw.append([wx, terrain_y + y, wz])
    if cr:
        xs = [a[0] for a in raw]
        zs = [a[2] for a in raw]
        cxm = (min(xs) + max(xs)) / 2
        czm = (min(zs) + max(zs)) / 2
        scale = min(1, 2800 / (max(xs) - min(xs)), 2800 / (max(zs) - min(zs)))
        for a in raw:
            x = (a[0] - cxm) * scale
            z = (a[2] - czm) * scale
            if route and route != "classic":
                a[1] += landscape_height(x, z, p) - landscape_height(a[0], a[2], p)
            a[0] = x
            a[2] = z
    points = rotate_to_safe_start(round_corners(raw))
    if cr:
        n = len(points)
        for _ in range(400):
            steep = False
            for i in range(n):
                a = points[i]
                b = points[(i + 1) % n]
                delta = b[1] - a[1]
                limit = .22 * jhypot(b[0] - a[0], b[2] - a[2])
                if abs(delta) <= limit + .001:
                    continue
                correction = (delta - jsign(delta) * limit) * .5
                a[1] += correction
                b[1] -= correction
                steep = True
            if not steep:
                break
    pid = "generated-" + "-".join(js_str(v) for v in p.values()) + ("-crossings-v3" if cr else "")
    if cr:
        name = "Circuit %s · %s · %s OVERPASSES" % (
            js_str(p["seed"]), ["BOW", "CRESCENT", "S-BEND", "SWEEP", "PERIMETER", "LOOP COMPLEX"][crossing_layout],
            js_str(cr))
    else:
        name = "Circuit %s · %s" % (js_str(p["seed"]), layouts[layout_index])
    params = dict(p)
    params["lanes"] = lanes
    params["runoff"] = runoff
    params["guardrails"] = guardrails
    m = {"id": pid, "name": name, "generated": True, "points": points, "parameters": params}
    if p.get("landmarks"):
        vista = next((f for f in plan_landscape_features(m) if f["kind"] == "tower"), None)
        if vista:
            m["points"] = rotate_to_safe_start(round_corners(straighten_vista(m, vista)))
        m["features"] = plan_landscape_features(m)
    return m


# ---------------------------------------------------------------- city.ts / mountain.ts のコース形状

def city_map(p):
    a = p["size"]
    b = p["size"] * (.68 + p["seed"] % 13 / 100)
    r = 65 + p["bends"] * .3
    points = [Vector3(-a * .6, 0, -b)]
    for x, z, angle in ((a - r, -b + r, -math.pi / 2), (a - r, b - r, 0), (-a + r, b - r, math.pi / 2),
                        (-a + r, -b + r, math.pi)):
        for i in range(13):
            points.append(Vector3(x + math.cos(angle + i / 12 * math.pi / 2) * r, 0,
                                  z + math.sin(angle + i / 12 * math.pi / 2) * r))
    c = CatmullRomCurve3(points, True, "centripetal")
    c.arcLengthDivisions = 2400
    params = dict(p)
    for k, v in (("layout", "city"), ("crossings", 0), ("elevation", 0), ("lanes", 4), ("guardrails", 0),
                 ("runoff", 0), ("terrainRoute", "classic"), ("landmarks", [])):
        params[k] = v
    return {"id": "city-v1-%s-%s-%s" % (js_str(p["seed"]), js_str(p["size"]), js_str(p["bends"])),
            "name": "Midnight City %s" % js_str(p["seed"]), "generated": True,
            "points": [v.toArray() for v in c.getSpacedPoints(192)[:-1]], "parameters": params}


def mountain_map(p):
    random = lcg_random(p["seed"])
    turns = 3 + 2 * int(math.floor((p["complexity"] - 1) / 2))
    radius = 71 - p["bends"] * .42 - p["technicality"] * .02 + p["size"] * .01
    half = p["size"] * (.5 + random() * .2)
    nodes = []
    anchors = [Vector3(0, 0, 0), Vector3(0, 0, 130)]
    z = 170
    for row in range(turns):
        z += 100 + random() * p["size"] * .28
        anchors.append(Vector3((-1 if row % 2 else 1) * half * (.4 + random() * .75), 0, z))
    z += 190
    anchors.append(Vector3(0, 0, z))
    summit_anchor = len(anchors) - 1
    outer = min(v.x for v in anchors) - 180
    anchors += [Vector3(0, 0, z + 170), Vector3(outer, 0, z + 170), Vector3(outer, 0, -180), Vector3(0, 0, -180)]
    corners = []
    na = len(anchors)
    for i, v in enumerate(anchors):
        before, after = anchors[(i + na - 1) % na], anchors[(i + 1) % na]
        incoming = v.clone().sub(before).normalize()
        outgoing = after.clone().sub(v).normalize()
        angle = math.atan2(incoming.x * outgoing.z - incoming.z * outgoing.x, incoming.dot(outgoing))
        tangent = math.tan(abs(angle) / 2)
        r = min(85 if i > summit_anchor else radius * (1 + random() * .3),
                .45 * min(v.distanceTo(before), v.distanceTo(after)) / max(.001, tangent))
        start = v.clone().addScaledVector(incoming, -r * tangent)
        end = v.clone().addScaledVector(outgoing, r * tangent)
        center = start.clone().add(Vector3(-incoming.z, 0, incoming.x).multiplyScalar(jsign(angle) * r))
        corners.append({"start": start, "end": end, "center": center, "angle": angle, "r": r})
    descent_start = 0
    nc = len(corners)
    for i in range(nc):
        c, previous = corners[i], corners[(i + nc - 1) % nc]
        if i == 0:
            nodes.append(c["start"].clone())
        else:
            direction = c["start"].clone().sub(previous["end"])
            distance = direction.length()
            normal = Vector3(-direction.z, 0, direction.x).normalize()
            wiggle = (min(45 if i <= summit_anchor else 70, distance * distance / 3500) * p["technicality"] / 100
                      * (-1 if random() < .5 else 1))
            for j in range(1, 25):
                t = j / 24
                nodes.append(previous["end"].clone().lerp(c["start"], t).addScaledVector(
                    normal, wiggle * math.sin(t * math.pi * 2) * math.sin(t * math.pi) ** 2))
        if abs(c["angle"]) > .001:
            sa = math.atan2(c["start"].z - c["center"].z, c["start"].x - c["center"].x)
            for j in range(1, 17):
                a = sa + c["angle"] * j / 16
                nodes.append(Vector3(c["center"].x + c["r"] * math.cos(a), 0, c["center"].z + c["r"] * math.sin(a)))
        if i == summit_anchor:
            descent_start = len(nodes) - 1
    rotation = landscape_rotation(p["seed"])
    center_x = (outer + half) / 2
    phase = random() * math.pi * 2
    yaxis = Vector3(0, 1, 0)
    for v in nodes:
        v.x -= center_x
        v.z -= z / 2
        v.x += p["size"] * .12 * math.sin(v.z / p["size"] * 1.6 + phase)
        v.z += p["size"] * .07 * math.sin(v.x / p["size"] * 1.8 - phase)
        v.applyAxisAngle(yaxis, -rotation)
    path = CatmullRomCurve3([Vector3(v.x, 0, v.z) for v in nodes], True, "centripetal")
    path.arcLengthDivisions = 4800
    lengths = path.getLengths()
    index = descent_start / len(nodes) * 4800
    j = int(math.floor(index))
    climb = lengths[j] + (lengths[j + 1] - lengths[j]) * (index - j)
    length = lengths[-1]
    crest = climb / length
    summit = min(climb * (.1 + .02 * math.sin(phase)), (length - climb) * .2) * p["elevation"] / 24
    points = []
    for i, v in enumerate(path.getSpacedPoints(240)[:-1]):
        u = i / 240
        t = u / crest if u <= crest else (u - crest) / (1 - crest)
        rise = t * t * (3 - 2 * t)
        fall = (5 * t * t if t < .1 else .9 - 5 * (1 - t) ** 2 if t > .9 else t - .05) / .9
        points.append([v.x, 20 + summit * (rise if u <= crest else 1 - fall), v.z])
    return {"id": "touge-v6-%s" % "-".join(js_str(p[k]) for k in
                                           ("seed", "size", "complexity", "bends", "elevation", "technicality")),
            "name": "峠 %s · MOUNTAIN PASS" % js_str(p["seed"]), "generated": True, "points": points,
            "parameters": p}


# ---------------------------------------------------------------- 検証（validateMapDetails）

def preview_points(m):
    pts = m["points"]
    n = len(pts)
    if not m.get("generated"):
        return CatmullRomCurve3([Vector3(*p) for p in pts], True, "centripetal").getPoints(480)
    path = CatmullRomCurve3([Vector3(x, 0, z) for x, _, z in pts], True, "centripetal")
    out = path.getPoints(480)
    for i, p in enumerate(out):
        index = i / 480 * n
        j = int(math.floor(index))
        f = index - j
        p.y = pts[j % n][1] * (1 - f) + pts[(j + 1) % n][1] * f
    return out


def map_crossings(m):
    pts = preview_points(m)
    crossings = []
    count = len(pts) - 1
    for i in range(count):
        a, b = pts[i], pts[i + 1]
        ax, az = b.x - a.x, b.z - a.z
        for j in range(i + 2, count):
            if i == 0 and j == count - 1:
                continue
            c, d = pts[j], pts[j + 1]
            bx, bz = d.x - c.x, d.z - c.z
            den = ax * bz - az * bx
            if abs(den) < 1e-8:
                continue
            dx, dz = c.x - a.x, c.z - a.z
            s = (dx * bz - dz * bx) / den
            t = (dx * az - dz * ax) / den
            if s < -1e-9 or s >= 1 - 1e-9 or t < -1e-9 or t >= 1 - 1e-9:
                continue
            x, z = a.x + s * ax, a.z + s * az
            y1, y2 = a.y + s * (b.y - a.y), c.y + t * (d.y - c.y)
            if not any(jhypot(h["position"][0] - x, h["position"][2] - z) < .1 for h in crossings):
                crossings.append({"position": [x, min(y1, y2), z], "clearance": abs(y1 - y2)})
    return crossings


def _course_width(m):
    par = m.get("parameters") or {}
    if par.get("layout") == "touge":
        return {"lanes": 2, "total": 13}
    lanes = 4 if par.get("lanes") == 4 else 2
    half = 8 if lanes == 4 else 5.5
    runoff = max(3.5, min(11, par.get("runoff", 5) if par.get("runoff") is not None else 5))
    return {"lanes": lanes, "total": 2 * (half + 1.5 + runoff)}


def validate_map_details(m):
    details = []
    par = m.get("parameters") or {}
    crossing = next((c for c in map_crossings(m) if c["clearance"] < 10), None)
    if crossing:
        details.append({"code": "crossing", "message": "交差する道路の上下間隔が10 m未満です（交差地点 %s m, %s m / 現在 %s m）。交差地点の高さを調整してください。" % (
            to_fixed(crossing["position"][0], 0), to_fixed(crossing["position"][2], 0),
            to_fixed(crossing["clearance"], 1))})
    for kind in par.get("landmarks") or []:
        if kind != "crossing" and not any(f["kind"] == kind for f in m.get("features") or []):
            details.append({"code": "landmark",
                            "message": "%sを安全に配置できません。広さを増やすか、見せ場を減らして再生成してください。" % LANDMARKS[kind]})
    pts = preview_points(m)
    dist = [0]
    for i in range(1, len(pts)):
        dist.append(dist[i - 1] + pts[i].distanceTo(pts[i - 1]))
    length = dist[-1]
    width = _course_width(m)
    min_r = width["total"] * 1.25 if par.get("layout") == "touge" else 24
    n = len(pts)
    for i in range(n - 1):
        a, nxt = pts[i], pts[i + 1]
        before = pts[(i + n - 2) % (n - 1)]
        ax, az, bx, bz = a.x - before.x, a.z - before.z, nxt.x - a.x, nxt.z - a.z
        cross = abs(ax * bz - az * bx)
        radius = jhypot(ax, az) * jhypot(bx, bz) * jhypot(ax + bx, az + bz) / max(.000001, 2 * cross)
        if radius < min_r:
            d = dist[i]
            if len([x for x in details if x["code"] == "radius"]) < 8:
                details.append({"code": "radius", "segment": i, "message": "急カーブ：区間 %d→%d（スタートから約%s m / 周回%s%%）。曲率半径 %s m、必要目安 %s m、%d車線の道路＋路肩 約%s mです。編集図の赤マーカー周辺を広げるか、地点を追加して角を分散してください。" % (
                    i + 1, i + 2, to_fixed(d, 0), to_fixed(d / length * 100, 1), to_fixed(radius, 1),
                    to_fixed(min_r, 1), width["lanes"], to_fixed(width["total"], 1))})
        g = abs(nxt.y - a.y) / max(.01, jhypot(nxt.x - a.x, nxt.z - a.z))
        if g > .34 and not any(x["code"] == "grade" for x in details):
            details.append({"code": "grade", "segment": i, "message": "急勾配：区間 %d→%d（スタートから約%s m）。勾配 %s%%です。高さを周辺地点へ分散してください。" % (
                i + 1, i + 2, to_fixed(dist[i], 0), to_fixed(g * 100, 1))})
        if any(x["code"] == "spacing" for x in details):
            continue
        for j in range(i + 1, n - 1):
            if i < 24 and j > n - 25:
                continue
            along = dist[j] - dist[i]
            if min(along, length - along) < 48:
                continue
            b = pts[j]
            h = jhypot(a.x - b.x, a.z - b.z)
            if h < 22 and abs(a.y - b.y) < 10:
                details.append({"code": "spacing", "segment": i, "message": "道路間隔不足：地点 %d付近と地点 %d付近が平面距離 %s mで近接しています。編集図の該当区間を外側へ移動してください。" % (
                    i + 1, j + 1, to_fixed(h, 1))})
                break
    return details


def validate_map(m):
    return [d["message"] for d in validate_map_details(m)]

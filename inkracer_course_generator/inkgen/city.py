"""city.ts の移植（夜の街：交差道路・信号・街灯・建物）"""
import math
from .three import Vector3, jhypot, jmod, js_round
from .geometries import BoxGeometry, CylinderGeometry, EdgesGeometry, mergeGeometries
from . import track as T

_cached_map = None
_streets = []


def reset_cache():
    global _cached_map, _streets
    _cached_map = None
    _streets = []


def is_city():
    return (T.activeMap.get("parameters") or {}).get("layout") == "city"


def city_bounds():
    b = T.track_bounds()
    return {"minX": b["minX"] + 20, "maxX": b["maxX"] - 20, "minZ": b["minZ"] + 20, "maxZ": b["maxZ"] - 20}


def city_streets():
    global _cached_map, _streets
    if _cached_map is T.activeMap:
        return _streets
    _cached_map = T.activeMap
    _streets = []
    if not is_city():
        return _streets
    b = city_bounds()
    for axis in ("x", "z"):
        for f in (.34, .66):
            value = b["minX"] + (b["maxX"] - b["minX"]) * f if axis == "x" else b["minZ"] + (b["maxZ"] - b["minZ"]) * f
            hits = []
            for i in range(1, len(T.samples)):
                a, c = T.samples[i - 1].position, T.samples[i].position
                av, cv = getattr(a, axis), getattr(c, axis)
                if (av - value) * (cv - value) < 0:
                    hits.append(a.clone().lerp(c, (value - av) / (cv - av)))
            hits.sort(key=(lambda v: v.z) if axis == "x" else (lambda v: v.x))
            if len(hits) >= 2:
                _streets.append({"a": hits[0], "b": hits[-1], "axis": axis})
    return _streets


def city_junction_at(x, z, margin=11):
    for s in city_streets():
        if s["axis"] == "x":
            if abs(x - s["a"].x) < margin and s["a"].z - margin <= z <= s["b"].z + margin:
                return True
        elif abs(z - s["a"].z) < margin and s["a"].x - margin <= x <= s["b"].x + margin:
            return True
    return False


def city_signals():
    result = []
    st = city_streets()
    for s in st:
        for p in (s["a"], s["b"]):
            road = T.nearest_track(p.x, p.z)
            result.append({"position": p.toArray(), "yaw": road.yaw, "u": road.u, "axis": 0,
                           "offset": js_round(road.u * 5) * 3})
    for v in [s for s in st if s["axis"] == "x"]:
        for h in [s for s in st if s["axis"] == "z"]:
            for axis in range(2):
                result.append({"position": [v["a"].x, 0, h["a"].z], "yaw": axis * math.pi / 2, "axis": axis,
                               "offset": 6})
    return result


def signal_meshes(signal):
    out = []
    for side in (-1, 1):
        for bulb in (-1, 0, 1, 2):
            if bulb < 0:
                g = BoxGeometry(1.6, .65, .45)
            else:
                g = CylinderGeometry(.19, .19, .04, 12).rotateX(math.pi / 2).translate((bulb - 1) * .5, 0, -.24)
            g.rotateY(math.pi if side < 0 else 0).translate(-side * 2.7, 6.55, -side * 13).rotateY(signal["yaw"])
            g.translate(*signal["position"])
            out.append({"geometry": g, "bulb": bulb,
                        "color": "#131a22" if bulb < 0 else ["#ed294a", "#ffb429", "#55e7b2"][bulb]})
    return out


def night_lamps():
    lamps = []
    count = math.ceil(T.TRACK_LENGTH / 36)
    city = is_city()
    for i in range(count):
        for side in (-1, 1):
            p = T.track_pose(i / count, side * (T.paved_half_width_at(i / count, side) + 2.6))
            if city and city_junction_at(p.position.x, p.position.z):
                continue
            lamps.append({"position": [p.position.x, p.position.y + 8.3, p.position.z], "yaw": p.yaw, "u": i / count})
    if city:
        st = city_streets()
        for s in st:
            length = s["a"].distanceTo(s["b"])
            d_ = s["b"].clone().sub(s["a"]).normalize()
            normal = Vector3(d_.z, 0, -d_.x)
            d = 32
            while d < length - 20:
                for side in (-1, 1):
                    p = s["a"].clone().addScaledVector(d_, d).addScaledVector(normal, side * 10.6)
                    p.y += 8.3
                    if any(t["axis"] != s["axis"] and (abs(t["a"].x - p.x) < 12 if t["axis"] == "x"
                                                        else abs(t["a"].z - p.z) < 12) for t in st):
                        continue
                    lamps.append({"position": p.toArray(), "yaw": math.atan2(d_.x, d_.z), "u": 0})
                d += 40
    return lamps


def build_city(scenery):
    groups = {}
    solids, signs = [], []
    seed = (T.activeMap.get("parameters") or {}).get("seed")
    seed = 0 if seed is None else seed

    def box(name, color, x, y, z, w, h, d, yaw=0, solid=False):
        g = BoxGeometry(w, h, d).rotateY(yaw).translate(x, y, z)
        g.deleteAttribute("uv")
        key = name + color + str(int(math.floor(x / 120))) + ":" + str(int(math.floor(z / 120)))
        if key not in groups:
            groups[key] = {"name": name, "color": color, "parts": []}
        groups[key]["parts"].append(g)
        if solid:
            solids.append({"position": [x, y, z], "size": [w, h, d], "yaw": yaw})

    dark, concrete, paint = "#283644", "#666a71", "#bcbcaf"
    bounds = city_bounds()
    st = city_streets()
    vertical = [s for s in st if s["axis"] == "x"]
    horizontal = [s for s in st if s["axis"] == "z"]
    xs = sorted([bounds["minX"] + 8] + [v for s in vertical for v in (s["a"].x - 8, s["a"].x + 8)] + [bounds["maxX"] - 8])
    zs = sorted([bounds["minZ"] + 8] + [v for s in horizontal for v in (s["a"].z - 8, s["a"].z + 8)] + [bounds["maxZ"] - 8])
    near = lambda x, z: T.nearest_track(x, z).distance
    for i in range(1, len(xs)):
        for j in range(1, len(zs)):
            x, z = (xs[i] + xs[i - 1]) / 2, (zs[j] + zs[j - 1]) / 2
            w, d = xs[i] - xs[i - 1], zs[j] - zs[j - 1]
            if any(abs(x - s["a"].x) < 8 for s in vertical) or any(abs(z - s["a"].z) < 8 for s in horizontal):
                box("road-city-surface", "#343e49", x, -.144, z, w, .3, d)
                continue
            for side in (-1, 1):
                px = xs[i - 1] + 3
                while px < xs[i] - 2:
                    pz = z + side * (d / 2 - 1.5)
                    if near(px, pz) > 12:
                        box("road-city-sidewalk", concrete, px, .03, pz, 6, .08, 3)
                    px += 6
                pz = zs[j - 1] + 4.5
                while pz < zs[j] - 4:
                    px = x + side * (w / 2 - 1.5)
                    if near(px, pz) > 12:
                        box("road-city-sidewalk", concrete, px, .03, pz, 3, .08, 6)
                    pz += 6
            district = (i // 2 + j // 2 + seed) % 4
            spacing = 30 if district == 0 else 26 if district == 1 else 34
            n = 0
            bx = xs[i - 1] + 17
            while bx < xs[i] - 14:
                bz = zs[j - 1] + 17
                while bz < zs[j] - 14:
                    n += 1
                    if jmod(n * 17 + scenery["seed"], 100) > min(97, scenery["density"] * .72):
                        bz += spacing
                        continue
                    bw, bd = 15 + (n % 3) * 2, 17
                    height = (9 + n % 3 * 3 if district == 0 else 30 + n % 5 * 9 if district == 1
                              else 12 + n % 4 * 3 if district == 2 else 18)
                    if near(bx, bz) < 25:
                        bz += spacing
                        continue
                    near_edge = (bx - xs[i - 1] < spacing or xs[i] - bx < spacing + 15 or bz - zs[j - 1] < spacing
                                 or zs[j] - bz < spacing + 15)
                    box("city-building", ["#46505b", "#303c50", "#524655", "#394951"][district], bx, height / 2 + .1,
                        bz, bw, height, bd, 0, True)
                    box("city-roof", dark, bx, height + .4, bz, bw + .3, .6, bd + .3)
                    y = 3
                    while y < height - 1:
                        for k in (-1, 0, 1):
                            for side in (-1, 1):
                                lit = jmod(math.floor(y) + n + k * 3 + side + scenery["seed"], 7) < (2 if district == 1 else 4)
                                box("city-glow-window" if lit else "city-window",
                                    ("#efbf7a" if district == 0 else "#92c5de") if lit else "#15202b",
                                    bx + k * 4, y, bz + side * (bd / 2 + .025), 2.1, 1.4, .045)
                        y += 3.5
                    if near_edge and n % 4 == 0:
                        title = ["24h MART", "MIDNIGHT HOTEL", "NIGHT DINER", "BAY GARAGE"][district]
                        box("city-glow-shop", "#67cbbb" if n % 8 == 0 else "#d28ab1", bx, 4, bz - bd / 2 - .1, bw, 1.3, .16)
                        signs.append({"position": [bx, 4, bz - bd / 2 - .2], "yaw": math.pi, "title": title,
                                      "subtitle": "OPEN 24 HOURS", "width": bw - 1, "height": 1.3, "electronic": True})
                        box("city-shop-glass", "#466572", bx, 1.8, bz - bd / 2 - .08, bw - 1, 3, .08)
                        box("city-glow-vending", "#afcfed", bx + bw / 2 + 1, 1.1, bz - bd / 2, 1.2, 2.1, .8, 0, True)
                    elif near_edge:
                        for k in range(9):
                            box("city-shutter", concrete, bx, .6 + k * .25, bz - bd / 2 - .05, bw - 1, .12, .08)
                    bz += spacing
                bx += spacing
            px, pz = xs[i - 1] + 7, (zs[j] + zs[j - 1]) / 2
            if near(px, pz) < 20:
                continue
            if district == 0:
                box("city-bus-roof", dark, px, 3, pz, 4, .2, 10)
                for dz in (-4, 4):
                    box("city-bus-post", concrete, px + 1.7, 1.5, pz + dz, .15, 3, .15, 0, True)
                box("city-bus-bench", paint, px, .6, pz, 1.2, .2, 6, 0, True)
            elif district == 1:
                box("city-parking", dark, px, .12, pz, 10, .08, 24)
                for dd in range(-10, 11, 4):
                    box("road-parking-line", paint, px, .18, pz + dd, 8, .015, .1)
                box("city-glow-parking", "#53c8af", px, 4, pz, 2, 2, .3)
                box("city-parking-meter", concrete, px + 3, 1, pz, 1, 2, .6, 0, True)
                signs.append({"position": [px, 4, pz + .18], "yaw": 0, "title": "P 24h", "subtitle": "COIN PARKING",
                              "width": 2, "height": 2, "electronic": True})
            elif district == 2:
                box("city-fuel-canopy", paint, px + 2, 4.5, pz, 9, .4, 17)
                box("city-glow-fuel", "#76dcd4", px - 2.55, 4.4, pz, .12, .35, 17)
                for dd in (-5, 5):
                    box("city-fuel-pump", concrete, px + 2, 1.1, pz + dd, 1.2, 2.2, 1.4, 0, True)
            else:
                for dd in range(-7, 8, 3):
                    box("city-works-barrier", paint, px, 1, pz + dd, .3, 1, 2.4, 0, True)
                    box("city-glow-worklamp", "#ed9a35", px, 1.8, pz + dd, .25, .25, .25)
    for s in st:
        length = s["a"].distanceTo(s["b"])
        d = 12
        while d < length - 12:
            p = s["a"].clone().lerp(s["b"], d / length)
            if not any(t["axis"] != s["axis"] and (abs(t["a"].x - p.x) < 12 if t["axis"] == "x" else abs(t["a"].z - p.z) < 12)
                       for t in st):
                for off in (-4, 0, 4):
                    box("road-city-paint", paint, p.x + (off if s["axis"] == "x" else 0), .035,
                        p.z + (off if s["axis"] == "z" else 0), .13 if s["axis"] == "x" else 4.5, .014,
                        4.5 if s["axis"] == "x" else .13)
            d += 10
    lamp_list = night_lamps()
    for i in range(int(math.floor(T.TRACK_LENGTH / 34))):
        if jmod(i * 17 + scenery["seed"], 100) > min(95, scenery["density"]):
            continue
        p = T.track_pose(i * 34 / T.TRACK_LENGTH, 34)
        h = 10 + (i % 5) * 5
        if p.position.x > bounds["maxX"] + 10 and abs(p.position.z) < bounds["maxZ"] * .65:
            continue
        box("city-frontage", ["#283c50", "#3c3d4c", "#344a51"][i % 3], p.position.x, h / 2, p.position.z, 18, h, 19,
            p.yaw, True)
        y = 3
        while y < h - 1:
            for k in (-1, 0, 1):
                q = p.position.clone().addScaledVector(p.normal, -9.55).addScaledVector(p.tangent, k * 4)
                if (i + k + int(math.floor(y))) % 3 != 0:
                    box("city-glow-window", "#92c5de" if i % 2 else "#efbf7a", q.x, y, q.z, .05, 1.4, 2, p.yaw)
            y += 3.5
    box("water-city-bay", "#234859", bounds["maxX"] + 235, -1, 0, 336, .08, bounds["maxZ"] - bounds["minZ"] + 500)
    box("city-quay", concrete, bounds["maxX"] + 54, -1.6, 0, 2, 3, bounds["maxZ"] - bounds["minZ"] + 120)
    z = bounds["minZ"] - 50
    while z < bounds["maxZ"] + 50:
        box("city-quay-bollard", dark, bounds["maxX"] + 51, .5, z, .7, 1.2, .7, 0, True)
        box("city-glow-beacon", "#d85861", bounds["maxX"] + 54, 1.6, z, .25, .3, .25)
        z += 55
    for l in lamp_list:
        x, y, z = l["position"]
        box("city-streetlight", concrete, x, y / 2, z, .18, y, .18, 0, True)
        box("city-glow-lamp", "#ffdab0", x, y, z, .7, .12, 1.8, l["yaw"])
    for s in city_signals():
        for direction in (-1, 1):
            fwd = Vector3(math.sin(s["yaw"]), 0, math.cos(s["yaw"]))
            normal = Vector3(fwd.z, 0, -fwd.x)
            p = Vector3(*s["position"]).addScaledVector(fwd, -direction * 13).addScaledVector(normal, -direction * 9.5)
            box("city-signal-pole", dark, p.x, 3.4, p.z, .16, 6.8, .16, 0, True)
            mid = p.clone().addScaledVector(normal, direction * 3.5)
            box("city-signal-arm", dark, mid.x, 6.7, mid.z, 7, .16, .16, s["yaw"])
            stop = Vector3(*s["position"]).addScaledVector(fwd, -direction * 14).addScaledVector(normal, -direction * 4)
            box("road-city-stop", paint, stop.x, .05, stop.z, 7.6, .02, .45, s["yaw"])
            for k in range(-3, 4):
                zebra = Vector3(*s["position"]).addScaledVector(fwd, direction * 10).addScaledVector(normal, k * 2)
                box("road-city-crosswalk", paint, zebra.x, .047, zebra.z, 1.1, .014, 3.5, s["yaw"])
    vx = bounds["maxX"] * .7
    box("city-expressway", concrete, vx, 12, 0, 17, 1.2, (bounds["maxZ"] - bounds["minZ"]) + 160, 0, True)
    for side in (-1, 1):
        box("city-expressway-rail", paint, vx + side * 8.3, 13, 0, .3, 1, (bounds["maxZ"] - bounds["minZ"]) + 160)
    z = bounds["minZ"] - 50
    while z < bounds["maxZ"] + 60:
        if not (city_junction_at(vx, z, 22) or near(vx, z) < 16):
            box("city-expressway-pier", concrete, vx, 5.7, z, 2, 11.4, 2, 0, True)
        z += 70
    names = {}
    batches = []
    for g in groups.values():
        geometry = mergeGeometries(g["parts"])
        n = names.get(g["name"], 0)
        names[g["name"]] = n + 1
        batches.append({"name": "%s-%d" % (g["name"], n) if n else g["name"], "color": g["color"],
                        "geometry": geometry, "edges": EdgesGeometry(geometry, 25)})
    return {"batches": batches, "solids": solids, "signs": signs, "turbines": [], "animations": []}

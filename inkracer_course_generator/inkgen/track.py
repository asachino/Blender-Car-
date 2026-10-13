"""track.ts の移植：中心線から路面・路肩・地形などを作る（ゲームと同じく「今のマップ」を一つ持つ）"""
import math
from array import array
import numpy as np
from .three import (Vector3, CatmullRomCurve3, BufferGeometry, BufferAttribute, f32, jmod, jhypot)
from .geometries import mergeGeometries
from . import maps as M
from . import city as C


class Pose:
    __slots__ = ("position", "tangent", "normal", "yaw", "distance", "u")

    def __init__(self, position, tangent, normal, yaw, distance=None, u=None):
        self.position, self.tangent, self.normal, self.yaw = position, tangent, normal, yaw
        self.distance, self.u = distance, u


def section_beam_geometry(a, b, na, nb, width, height, caps):
    positions = []
    for i, p in enumerate((a, b)):
        for x, y in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            q = p.clone().addScaledVector(nb if i else na, x * width / 2).add(Vector3(0, y * height / 2, 0))
            positions.extend((q.x, q.y, q.z))
    indices = [0, 4, 3, 4, 7, 3, 1, 2, 5, 2, 6, 5, 0, 1, 4, 1, 5, 4, 3, 7, 2, 7, 6, 2]
    if caps[0]:
        indices += [0, 3, 1, 3, 2, 1]
    if caps[1]:
        indices += [4, 5, 7, 5, 6, 7]
    src = BufferGeometry()
    src.setAttribute("position", BufferAttribute(f32(positions), 3))
    src.setIndex(indices)
    g = src.toNonIndexed()
    g.computeVertexNormals()
    g.setIndex(list(range(g.attributes["position"].count)))
    return g


DEFAULT_MAP = {"id": "industrial-loop-v3", "name": "Industrial Loop", "points": [
    [-135, 0, -165], [-135, 1.5, -40], [-65, 4.5, 75], [55, 8, 145],
    [190, 7, 135], [292, 4, 60], [315, 1, -45], [255, .5, -145],
    [145, 1, -210], [20, 3.5, -240], [-75, 4, -245], [-130, 2, -220]]}

activeMap = None
COURSE_POINTS = None
curve = None
elevationCurve = None
TRACK_LENGTH = 0.0
samples = []
SX = SY = SZ = None  # samples の座標（numpy）
_cachedPit = None
_cachedWater = None
ROAD_HALF_WIDTH = 8


def params():
    return activeMap.get("parameters") or {}


def seed():
    s = params().get("seed")
    return 73 if s is None else s


def activate_map(m):
    global activeMap, COURSE_POINTS, curve, elevationCurve, TRACK_LENGTH, samples, _cachedPit, _cachedWater, SX, SY, SZ
    activeMap = m
    COURSE_POINTS = m["points"]
    curve = CatmullRomCurve3([Vector3(x, 0, z) for x, _, z in COURSE_POINTS], True, "centripetal")
    curve.arcLengthDivisions = 2400
    elevationCurve = CatmullRomCurve3([Vector3(0, y, 0) for _, y, _ in COURSE_POINTS], True, "centripetal")
    TRACK_LENGTH = curve.getLength()
    _cachedPit = None
    _cachedWater = None
    _lane_cache.clear()
    C.reset_cache()
    samples = [track_pose(i / 720) for i in range(721)]
    SX = np.array([s.position.x for s in samples])
    SY = np.array([s.position.y for s in samples])
    SZ = np.array([s.position.z for s in samples])


def _height_at(u):
    if not activeMap.get("generated"):
        return elevationCurve.getPointAt(u).y
    n = len(COURSE_POINTS)
    index = curve.getUtoTmapping(u, 0) * n
    i = int(math.floor(index)) % n
    f = index - math.floor(index)
    return COURSE_POINTS[i][1] * (1 - f) + COURSE_POINTS[(i + 1) % n][1] * f


def track_pose(u, offset=0):
    t = jmod(jmod(u, 1) + 1, 1)
    p = curve.getPointAt(t)
    p.y = _height_at(t)
    txz = curve.getTangentAt(t).normalize()
    tb = jmod(t - .001 + 1, 1)
    ta = jmod(t + .001, 1)
    before = curve.getPointAt(tb)
    after = curve.getPointAt(ta)
    hd = max(.0001, before.distanceTo(after))
    slope = (_height_at(ta) - _height_at(tb)) / hd
    tangent = Vector3(txz.x, slope, txz.z).normalize()
    hl = max(.0001, jhypot(tangent.x, tangent.z))
    normal = Vector3(tangent.z / hl, 0, -tangent.x / hl)
    return Pose(p.addScaledVector(normal, offset), tangent, normal, math.atan2(tangent.x, tangent.z))


def track_layout():
    par = params()
    if par.get("layout") == "touge":
        return {"lanes": 2, "roadHalfWidth": 4.25, "runoffWidth": .75, "guardrails": 0}
    if C.is_city():
        return {"lanes": 4, "roadHalfWidth": 8, "runoffWidth": 0, "guardrails": 0}
    if not activeMap.get("generated") and not activeMap.get("parameters"):
        return {"lanes": 4, "roadHalfWidth": 8, "runoffWidth": 0, "guardrails": 0}
    s = seed()
    lanes = par["lanes"] if par.get("lanes") in (2, 4) else 4 if M.seeded_layout_value(s, 11) < .34 else 2
    ro = par.get("runoff")
    ro = 3.5 + M.seeded_layout_value(s, 23) * 7.5 if ro is None else ro
    g = par.get("guardrails")
    if g not in (0, 1, 2):
        g = 1 if M.seeded_layout_value(s, 37) < .28 else 2 if M.seeded_layout_value(s, 41) < .55 else 0
    return {"lanes": lanes, "roadHalfWidth": 8 if lanes == 4 else 5.5, "runoffWidth": max(3.5, min(11, ro)),
            "guardrails": g}


_lane_cache = {}


def lane_profile():
    key = id(activeMap)
    if _lane_cache.get("key") == key:
        return _lane_cache["v"]
    base = track_layout()["lanes"]
    s = seed()
    if C.is_city() or params().get("layout") == "touge":
        v = {"base": base, "alternate": base, "start": 0, "end": 0}
    elif not activeMap.get("generated") or M.seeded_layout_value(s, 59) >= .72:
        v = {"base": base, "alternate": base, "start": 0, "end": 0}
    else:
        start = .18 + M.seeded_layout_value(s, 61) * .25
        v = {"base": base, "alternate": 2 if base == 4 else 4, "start": start,
             "end": min(.82, start + .18 + M.seeded_layout_value(s, 67) * .16)}
    _lane_cache["key"] = key
    _lane_cache["v"] = v
    return v


def _smooth01(x):
    n = max(0, min(1, x))
    return n * n * (3 - 2 * n)


def lane_blend_at(u):
    pr = lane_profile()
    if pr["start"] == pr["end"]:
        return 0
    t = jmod(jmod(u, 1) + 1, 1)
    fade = .035
    return _smooth01((t - (pr["start"] - fade)) / (fade * 2)) * (1 - _smooth01((t - (pr["end"] - fade)) / (fade * 2)))


def lane_count_at(u):
    pr = lane_profile()
    return pr["alternate"] if lane_blend_at(u) > .5 else pr["base"]


def road_half_width_at(u):
    if params().get("layout") == "touge":
        return 4.25
    pr = lane_profile()
    blend = lane_blend_at(u)
    w = lambda l: 8 if l == 4 else 5.5
    return w(pr["base"]) * (1 - blend) + w(pr["alternate"]) * blend


def median_half_width_at(u):
    if C.is_city():
        return 0
    s = seed()
    pr = lane_profile()
    if M.seeded_layout_value(s, 83) > .75:
        return 0
    start, end = .22 + M.seeded_layout_value(s, 89) * .1, .78
    if pr["start"] != pr["end"]:
        if pr["base"] == 2:
            start, end = pr["start"] + .04, pr["end"] - .04
        elif pr["start"] - .16 > .84 - pr["end"]:
            start, end = .12, pr["start"] - .04
        else:
            start, end = pr["end"] + .04, .88
    elif pr["base"] != 4:
        return 0
    t = jmod(jmod(u, 1) + 1, 1)
    if end - start < .06 or t <= start or t >= end or lane_count_at(t) != 4:
        return 0
    taper = min(55 / TRACK_LENGTH, (end - start) * .28)
    amount = min(1, (t - start) / taper, (end - t) / taper)
    return 1.2 * amount * amount * (3 - 2 * amount)


def road_surface_geometry():
    halves = [ribbon(lambda u: -road_half_width_at(u), lambda u: -median_half_width_at(u), .012),
              ribbon(lambda u: median_half_width_at(u), lambda u: road_half_width_at(u), .012)]
    return mergeGeometries(halves)


def median_strips():
    out = [{"name": "road-median", "geometry": ribbon(lambda u: -median_half_width_at(u), median_half_width_at, .012,
                                                      lambda u: median_half_width_at(u) > 0), "color": "#aaa993"}]
    for side in (-1, 1):
        out.append({"name": "road-median-edge-%d" % side, "color": "#f1e6cc", "geometry": ribbon(
            lambda u, s=side: s * median_half_width_at(u) + (-.2 if s < 0 else .05),
            lambda u, s=side: s * median_half_width_at(u) + (-.05 if s < 0 else .2), .028,
            lambda u: median_half_width_at(u) > .05)})
    return out


def turn_info(u):
    before = track_pose(u - .004).tangent
    after = track_pose(u + .004).tangent
    cross = before.x * after.z - before.z * after.x
    angle = abs(math.atan2(cross, before.x * after.x + before.z * after.z))
    return {"outside": -1 if cross < 0 else 1, "strength": min(1, angle / .22)}


def runoff_at(u, side):
    layout = track_layout()
    turn = turn_info(u)
    if side != turn["outside"] or turn["strength"] < .16:
        return 0
    variation = .72 + .28 * math.sin(seed() * .17 + u * math.pi * 12)
    return layout["runoffWidth"] * turn["strength"] * variation


def runoff_band_at(u, side):
    return max(runoff_at(u, side), bridge_blend_at(u) * 3.5)


def bridge_blend_at(u):
    road = track_pose(u).position
    t = max(0, min(1, (road.y - terrain_height_at(road.x, road.z) - .6) / 1.8))
    return t * t * (3 - 2 * t)


def is_bridge_span_at(u):
    road = track_pose(u).position
    return road.y - terrain_height_at(road.x, road.z) > 2.4


def shoulder_half_width_at(u, side):
    bb = bridge_blend_at(u)
    base = road_half_width_at(u) + 1.5 + runoff_band_at(u, side) if activeMap.get("generated") else 14
    return max(base + bb * 2.8, paved_half_width_at(u, side) + 1.5 + bb * 6.3)


def guardrail_offset_at(u, side):
    layout = track_layout()
    turn = turn_info(u)
    if side == -1 and is_pit_lane_span_at(u):
        return shoulder_half_width_at(u, side) - .4
    if is_bridge_span_at(u):
        return shoulder_half_width_at(u, side) - .4
    if not activeMap.get("generated"):
        return 11.2
    if layout["guardrails"] == 1 and side != turn["outside"]:
        return None
    if layout["guardrails"] == 2 and turn["strength"] < .2:
        return None
    if layout["guardrails"] == 1 and turn["strength"] < .16:
        return None
    return shoulder_half_width_at(u, side) - .4


def water_layout():
    global _cachedWater
    if _cachedWater is None:
        b = track_bounds()
        b["level"] = min(s.position.y for s in samples) - 8
        b["phase"] = seed() * .013
        _cachedWater = b
    return _cachedWater


def river_center_at(z):
    w = water_layout()
    return w["minX"] - 110 + 16 * math.sin(z * .007 + w["phase"])


def coast_at(z):
    w = water_layout()
    return w["maxX"] + 70 + 18 * math.sin(z * .004 + w["phase"])


def terrain_height_at(x, z):
    par = params()
    if par.get("layout") == "touge":
        p = par
        road = nearest_track(x, z)
        rotation = M.landscape_rotation(p["seed"])
        a = (x * math.cos(rotation) + z * math.sin(rotation)) / p["size"]
        b = (-x * math.sin(rotation) + z * math.cos(rotation)) / p["size"]
        massif = p["elevation"] * (8 * math.exp(-(((a - 1.55) / .85) ** 2) - (b * .45) ** 2)
                                   + 4 * math.exp(-(((a + 1.5) / .7) ** 2) - ((b - 1.2) / .65) ** 2))
        outside = max(0, min(1, (road.distance - 30) / 100))
        broad = M.landscape_height(x, z, p) + massif * outside * outside * (3 - 2 * outside)
        t = max(0, min(1, (road.distance - 20) / 30))
        return (road.position.y - .65) * (1 - t * t * (3 - 2 * t)) + broad * t * t * (3 - 2 * t)
    if C.is_city():
        coast = water_layout()["maxX"] + 35
        return -.12 - max(0, min(1, (x - coast) / 12)) * 7
    height = inland_height_at(x, z)
    w = water_layout()
    river = abs(x - river_center_at(z))
    bank = max(0, min(1, (river - 24) / 24))
    shore = max(0, min(1, (coast_at(z) + 26 - x) / 26))
    blend = min(bank, shore)
    return height * blend + min(height, w["level"] - 5) * (1 - blend)


def _hypot_v8(dx, dz):
    """V8 の Math.hypot(a, b) を numpy で（同じ演算順）"""
    ax, az = np.abs(dx), np.abs(dz)
    m = np.maximum(ax, az)
    with np.errstate(invalid="ignore", divide="ignore"):
        n1 = ax / m
        n2 = az / m
        s = n1 * n1
        s = s + n2 * n2
        r = np.sqrt(s) * m
    return np.where(m == 0, 0.0, r)


def inland_height_at(x, z):
    par = params()
    s = seed()
    phase = s * .013
    route = par.get("terrainRoute")
    if route and route != "classic":
        broad = M.landscape_height(x, z, par)
    else:
        broad = (-1.45 + 3.8 * math.sin(x * .006 + phase) + 2.6 * math.cos(z * .008 - phase * .7)
                 + 1.15 * math.sin((x + z) * .014 + phase * 1.7))
    d = _hypot_v8(x - SX, z - SZ)
    i = int(np.argmin(d))
    nearest_distance = float(d[i])
    nearest_road = float(SY[i])
    nearest_u = i / 720
    close = d < 64
    lowest = float(SY[close].min()) if close.any() else math.inf
    if nearest_distance > 110:
        return broad
    ref = lowest if math.isfinite(lowest) else nearest_road
    bridge = next((f for f in activeMap.get("features") or []
                   if f["kind"] == "bridge" and M.feature_blend(nearest_u, f) > 0), None)
    if bridge:
        depth = 24 * M.feature_blend(nearest_u, bridge) * math.exp(-((nearest_distance / 85) ** 2))
        return ref - .95 - depth
    if route and route != "classic":
        blend = max(0, min(1, (nearest_distance - 35) / 75))
        return (ref - .95) * (1 - blend) + broad * blend
    follows = ref - .95 + min(8, nearest_distance * .03)
    return min(max(broad, follows), ref - .45)


def ground_offset_at(x, z):
    return 0 if nearest_track(x, z).distance < 17 else terrain_height_at(x, z)


def terrain_mesh(cell_count=128):
    b = track_bounds()
    margin = 260
    for f in activeMap.get("features") or []:
        if f.get("position"):
            b["minX"] = min(b["minX"], f["position"][0])
            b["maxX"] = max(b["maxX"], f["position"][0])
            b["minZ"] = min(b["minZ"], f["position"][2])
            b["maxZ"] = max(b["maxZ"], f["position"][2])
    minX, maxX = b["minX"] - margin, b["maxX"] + margin
    minZ, maxZ = b["minZ"] - margin, b["maxZ"] + margin
    cells = max(32, min(128, int(math.floor(cell_count + .5))))
    cols = rows = cells + 1
    positions = f32([0.0]) * (cols * rows * 3)
    for row in range(rows):
        for col in range(cols):
            x = minX + (maxX - minX) * col / cells
            z = minZ + (maxZ - minZ) * row / cells
            i = (row * cols + col) * 3
            positions[i] = x
            positions[i + 1] = terrain_height_at(x, z)
            positions[i + 2] = z
    indices = array("I")
    for row in range(cells):
        for col in range(cells):
            a = row * cols + col
            bb, c = a + 1, a + cols
            d = c + 1
            if (row + col) % 2:
                indices.extend((a, c, bb, bb, c, d))
            else:
                indices.extend((a, d, bb, a, c, d))
    if params().get("layout") == "touge":
        for i in range(1440):
            for offset in (-6.5, 0, 6.5):
                p = track_pose(i / 1440, offset).position
                gx = (p.x - minX) / (maxX - minX) * cells
                gz = (p.z - minZ) / (maxZ - minZ) * cells
                col, row = int(math.floor(gx)), int(math.floor(gz))
                x, z = gx - col, gz - row
                a = row * cols + col
                bb, c = a + 1, a + cols
                d = c + 1
                if (row + col) % 2:
                    if x + z <= 1:
                        vs, ws = (a, c, bb), (1 - x - z, z, x)
                    else:
                        vs, ws = (bb, c, d), (1 - z, 1 - x, x + z - 1)
                else:
                    if z >= x:
                        vs, ws = (a, c, d), (1 - z, z - x, x)
                    else:
                        vs, ws = (a, d, bb), (1 - x, z, x - z)
                h = 0
                for v, w in zip(vs, ws):
                    h = h + positions[v * 3 + 1] * w
                cut = max(0, h - (p.y - .35))
                if cut > 0:
                    for v in vs:
                        positions[v * 3 + 1] = positions[v * 3 + 1] - cut
    g = BufferGeometry()
    g.setAttribute("position", BufferAttribute(positions, 3))
    g.index = BufferAttribute(indices, 1)
    g.computeVertexNormals()
    min_y = min(positions[1::3])
    return {"geometry": g, "vertices": positions, "indices": indices, "floorY": min(-12, min_y - 4)}


def track_bounds():
    xs = [s.position.x for s in samples]
    zs = [s.position.z for s in samples]
    return {"minX": min(xs) - 20, "maxX": max(xs) + 20, "minZ": min(zs) - 20, "maxZ": max(zs) + 20}


def nearest_track(x, z, y=None):
    ax, az, ay = SX[:-1], SZ[:-1], SY[:-1]
    dx, dz = SX[1:] - ax, SZ[1:] - az
    with np.errstate(invalid="ignore", divide="ignore"):
        f = ((x - ax) * dx + (z - az) * dz) / (dx * dx + dz * dz)
    f = np.maximum(0, np.minimum(1, f))
    ex = x - ax - f * dx
    ez = z - az - f * dz
    d = ex * ex + ez * ez
    if y is None:
        score = d
    else:
        ey = y - ay - f * (SY[1:] - ay)
        score = d + ey * ey * 4
    score = np.where(np.isnan(score), np.inf, score)
    i = int(np.argmin(score))
    if not score[i] < math.inf:
        i, fu, hz = 0, 0.0, 0.0
    else:
        fu, hz = float(f[i]), float(d[i])
    return Nearest(math.sqrt(hz), (i + fu) / 720)


class Nearest:
    """nearestTrack の結果。姿勢（position など）は使われた時に計算する"""
    __slots__ = ("distance", "u", "_pose")

    def __init__(self, distance, u):
        self.distance, self.u, self._pose = distance, u, None

    def _p(self):
        if self._pose is None:
            self._pose = track_pose(self.u)
        return self._pose

    @property
    def position(self):
        return self._p().position

    @property
    def tangent(self):
        return self._p().tangent

    @property
    def normal(self):
        return self._p().normal

    @property
    def yaw(self):
        return self._p().yaw


def _val(v, u):
    return v(u) if callable(v) else v


def ribbon(inner, outer, height, include=lambda u: True):
    positions, uv, indices = [], [], []
    city = C.is_city()
    for i, s in enumerate(samples):
        u = i / 720
        lo, hi = _val(inner, u), _val(outer, u)
        for offset in (lo, hi):
            p = s.position.clone().addScaledVector(s.normal, offset)
            positions.extend((p.x, p.y + height, p.z))
            uv.extend((offset / 5, i * TRACK_LENGTH / 720 / 5))
        mouth = city and (lo >= 7.5 or hi <= -7.5) and C.city_junction_at(s.position.x, s.position.z, 11)
        if i < 720 and not mouth and include((i + .5) / 720):
            a = i * 2
            indices.extend((a, a + 2, a + 1, a + 1, a + 2, a + 3))
    g = BufferGeometry()
    pa = f32(positions)
    g.setAttribute("position", BufferAttribute(pa, 3))
    g.setAttribute("uv", BufferAttribute(f32(uv), 2))
    valid = []
    for i in range(0, len(indices), 3):
        a, b, c = indices[i] * 3, indices[i + 1] * 3, indices[i + 2] * 3
        abx, aby, abz = pa[b] - pa[a], pa[b + 1] - pa[a + 1], pa[b + 2] - pa[a + 2]
        acx, acy, acz = pa[c] - pa[a], pa[c + 1] - pa[a + 1], pa[c + 2] - pa[a + 2]
        cx = aby * acz - abz * acy
        cy = abz * acx - abx * acz
        cz = abx * acy - aby * acx
        if cx * cx + cy * cy + cz * cz > 1e-16:
            valid.extend(indices[i:i + 3])
    g.setIndex(valid)
    g.computeVertexNormals()
    return g


def bridge_shoulder_ribbon(side, height=.02):
    positions, indices = [], []
    for i, s in enumerate(samples):
        u = i / 720
        inner = paved_half_width_at(u, side) + 1.5
        outer = shoulder_half_width_at(u, side)
        for offset in ((-outer, -inner) if side < 0 else (inner, outer)):
            p = s.position.clone().addScaledVector(s.normal, offset)
            positions.extend((p.x, p.y + height, p.z))
        if i < 720 and is_bridge_span_at((i + .5) / 720):
            a = i * 2
            indices.extend((a, a + 2, a + 1, a + 1, a + 2, a + 3))
    g = BufferGeometry()
    g.setAttribute("position", BufferAttribute(f32(positions), 3))
    g.setIndex(indices)
    g.computeVertexNormals()
    return g


def road_underside_geometry():
    g = ribbon(lambda u: -shoulder_half_width_at(u, -1), lambda u: shoulder_half_width_at(u, 1), -.65,
               is_bridge_span_at)
    idx = g.index.array
    for i in range(0, len(idx), 3):
        idx[i + 1], idx[i + 2] = idx[i + 2], idx[i + 1]
    g.computeVertexNormals()
    return g


def lane_ribbon(index, height):
    positions, indices = [], []
    city = C.is_city()
    for i, s in enumerate(samples):
        u = i / 720
        mid = (i + .5) / 720
        lanes = lane_count_at(mid)
        active = index == 0 or lanes == 4
        offset = 0 if index == 0 else (-1 if index == 1 else 1) * (road_half_width_at(u) + median_half_width_at(u)) / 2
        p = s.position.clone().addScaledVector(s.normal, offset)
        n = s.normal
        positions.extend((p.x - n.x * .055, p.y + height, p.z - n.z * .055, p.x + n.x * .055, p.y + height,
                          p.z + n.z * .055))
        dashed = jmod(i * TRACK_LENGTH / 720, 12) < 5.5
        if (i < 720 and active and not (city and C.city_junction_at(p.x, p.z, 16))
                and (index != 0 or median_half_width_at(mid) <= .05) and ((index == 0 and lanes == 4) or dashed)):
            a = i * 2
            indices.extend((a, a + 2, a + 1, a + 1, a + 2, a + 3))
    g = BufferGeometry()
    g.setAttribute("position", BufferAttribute(f32(positions), 3))
    g.setIndex(indices)
    g.computeVertexNormals()
    return g


def is_pit_lane_span_at(u):
    if C.is_city() or params().get("layout") == "touge":
        return False
    t = jmod(jmod(u, 1) + 1, 1)
    return t >= .92 or t <= .08


def pit_blend_at(u):
    if C.is_city() or params().get("layout") == "touge":
        return 0
    t = jmod(jmod(u + .08, 1) + 1, 1)
    if t >= .16:
        return 0
    f = min(1, t / .035, (.16 - t) / .035)
    return f * f * (3 - 2 * f)


def paved_half_width_at(u, side):
    return road_half_width_at(u) + (8 * pit_blend_at(u) if side < 0 else 0)


def pit_lane_path():
    global _cachedPit
    if _cachedPit is not None:
        return _cachedPit
    pts = []
    for i in range(97):
        u = jmod(jmod(.92 + i / 96 * .16, 1) + 1, 1)
        pose = track_pose(u, -(road_half_width_at(u) - 3.5 + 8 * pit_blend_at(u)))
        pose.u = u
        pts.append(pose)
    _cachedPit = pts
    return pts


def pit_lane_ribbon(height=.012):
    return ribbon(lambda u: -paved_half_width_at(u, -1), lambda u: -road_half_width_at(u), height,
                  lambda u: pit_blend_at(u) > 0)


def elevation_skirt(inner, outer, base=-.055):
    positions, indices = [], []
    gen = activeMap.get("generated")
    for i, s in enumerate(samples):
        u = i / 720
        for offset in (_val(inner, u), _val(outer, u)):
            top = s.position.clone().addScaledVector(s.normal, offset)
            positions.extend((top.x, top.y, top.z, top.x, top.y - .65 if gen else base, top.z))
        if i < 720:
            for side in (0, 1):
                a, b = i * 4 + side * 2, (i + 1) * 4 + side * 2
                if side == 0:
                    indices.extend((a, a + 1, b, a + 1, b + 1, b))
                else:
                    indices.extend((a, b, a + 1, a + 1, b, b + 1))
    g = BufferGeometry()
    g.setAttribute("position", BufferAttribute(f32(positions), 3))
    g.setIndex(indices)
    g.computeVertexNormals()
    return g

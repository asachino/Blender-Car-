"""venue.ts の移植：川・海・トラス橋・LED ゲート・フェンス・タイヤバリア・高速道路・港湾クレーン・鉄道・
ロープウェイ・ダム・配管・採石場・立体駐車場・パラボラ・工事現場・マーシャルポスト・ピット整備棟・ヘリ・飛行船"""
import math
from .three import (Vector2, Vector3, Quaternion, BufferGeometry, BufferAttribute, f32, jmod, jhypot, js_round,
                    CurvePath, LineCurve3, QuadraticBezierCurve3)
from .geometries import (BoxGeometry, CylinderGeometry, SphereGeometry, TorusGeometry, LatheGeometry, TubeGeometry,
                         EdgesGeometry, mergeGeometries)
from . import track as T

C = {"steel": "#45768a", "dark": "#263c50", "concrete": "#aaa993", "white": "#f1e6cc", "red": "#b95836",
     "water": "#548d9d", "amber": "#e3ae55"}


# Blender 版の追加：タイヤバリヤを本物のタイヤの形にする（False ならゲームと同じドーナツ形）
REAL_TIRES = False
# タイヤの断面（半径, 高さ）。外径はゲームのドーナツと同じ 0.6 m、高さ 0.36 m（積む間隔と同じ）
_TIRE_PROFILE = [
    (0.190, 0.062), (0.198, 0.080), (0.222, 0.093), (0.255, 0.100), (0.284, 0.098), (0.300, 0.090),
    (0.308, 0.078), (0.310, 0.062), (0.310, 0.046), (0.301, 0.044), (0.301, 0.032), (0.310, 0.030),
    (0.310, -0.030), (0.301, -0.032), (0.301, -0.044), (0.310, -0.046), (0.310, -0.062), (0.308, -0.078),
    (0.300, -0.090), (0.284, -0.098), (0.255, -0.100), (0.222, -0.093), (0.198, -0.080), (0.190, -0.062),
]


def _real_tire():
    """平らなトレッドと溝、サイドウォール、中央の穴があるタイヤ（縦軸まわりの回転体）"""
    pts = [Vector2(r * .6 / .31, z * 1.8) for r, z in reversed(_TIRE_PROFILE)]
    pts.append(pts[0].clone())
    return LatheGeometry(pts, 16)


def venue_motion_at(m, seconds):
    t = seconds * m["rate"] + m["phase"]
    position, rotation = [0, 0, 0], [0, 0, 0]
    k = m["kind"]
    if k in ("train", "gondola"):
        position[2] = math.sin(t) * m["span"]
    if k == "gondola":
        position[1] = -4 * (1 - math.sin(t) ** 2)
    if k == "dish":
        rotation[1] = t
    if k == "flag":
        rotation[2] = math.sin(t) * .25
    if k == "airship":
        position[0] = math.cos(t) * m["span"]
        position[2] = math.sin(t) * m["span"] * .6
        rotation[1] = math.atan2(-math.sin(t), .6 * math.cos(t))
    if k == "helicopter":
        position[0] = math.sin(t) * m["span"]
        position[2] = math.sin(t * .5) * m["span"] * .12
        rotation[1] = math.pi / 2 if math.cos(t) >= 0 else -math.pi / 2
    if k == "water":
        position[1] = -(t - math.floor(t)) * m["span"]
    return {"position": position, "rotation": rotation}


def build_venue(settings, obstacles=None):
    obstacles = list(obstacles or [])
    groups = {}
    solids, reserved, signs, motions = [], [], [], []
    samples = T.samples
    features = T.activeMap.get("features") or []

    def add(name, g, color):
        g.deleteAttribute("uv")
        key = name + color
        if key not in groups:
            groups[key] = {"name": name, "color": color, "parts": []}
        groups[key]["parts"].append(g)

    def box(name, p, size, color, yaw=0, collide=False):
        add(name, BoxGeometry(*size).rotateY(yaw).translate(p.x, p.y, p.z), color)
        if collide:
            solids.append({"position": p.toArray(), "size": list(size), "yaw": yaw, "pitch": 0})

    def beam(name, a, b, thickness, color):
        delta = b.clone().sub(a)
        mid = a.clone().add(b).multiplyScalar(.5)
        if delta.lengthSq() < .0001:
            return
        g = BoxGeometry(thickness, delta.length(), thickness)
        g.applyQuaternion(Quaternion().setFromUnitVectors(Vector3(0, 1, 0), delta.normalize()))
        add(name, g.translate(mid.x, mid.y, mid.z), color)

    def occupied(p, radius):
        for o in obstacles + reserved:
            dx, dz = p.x - o["position"][0], p.z - o["position"][2]
            c, s = math.cos(o["yaw"]), math.sin(o["yaw"])
            if abs(dx * c - dz * s) < o["size"][0] / 2 + radius and abs(dx * s + dz * c) < o["size"][2] / 2 + radius:
                return True
        return False

    def clear_post(p, radius=2):
        road = T.nearest_track(p.x, p.z)
        side = -1 if p.clone().sub(road.position).dot(road.normal) < 0 else 1
        return road.distance > T.shoulder_half_width_at(road.u, side) + radius + 2 and not occupied(p, radius)

    def foot(p):
        return Vector3(p.x, T.terrain_height_at(p.x, p.z), p.z)

    def reserve(p, size, yaw=0):
        reserved.append({"position": p.toArray(), "size": list(size), "yaw": yaw})

    def post(name, p, top, width, color):
        base = foot(p)
        height = max(.5, top - base.y)
        box(name, base.clone().add(Vector3(0, height / 2, 0)), [width, height, width], color, 0, True)
        box(name, base.clone().add(Vector3(0, .2, 0)), [width + .8, .4, width + .8], C["concrete"], 0, True)
        reserve(base, [width + 2, height, width + 2])

    def ribbon(name, rows, color):
        positions, indices = [], []
        for i, row in enumerate(rows):
            for p in row:
                positions.extend((p.x, p.y, p.z))
            if i < len(rows) - 1:
                a = i * 2
                indices.extend((a, a + 2, a + 1, a + 1, a + 2, a + 3))
        g = BufferGeometry()
        g.setAttribute("position", BufferAttribute(f32(positions), 3))
        g.setIndex(indices)
        g.computeVertexNormals()
        add(name, g, color)

    water = T.water_layout()
    z0, z1 = water["minZ"] - 250, water["maxZ"] + 250
    river_rows, sea_rows = [], []
    for i in range(97):
        z = z0 + (z1 - z0) * i / 96
        x = T.river_center_at(z)
        river_rows.append([Vector3(x - 21, water["level"], z), Vector3(x + 21, water["level"], z)])
        sea_rows.append([Vector3(T.coast_at(z), water["level"], z), Vector3(water["maxX"] + 1000, water["level"], z)])
        if i % 2 == 0:
            for off in (-12, 4, 13):
                beam("water-river-ripples", Vector3(x + off, water["level"] + .035, z),
                     Vector3(x + off + 5, water["level"] + .035, z + 2), .05, C["white"])
            for band in range(1, 5):
                beam("water-sea-waves", Vector3(T.coast_at(z) + band * 23, water["level"] + .04, z),
                     Vector3(T.coast_at(z) + band * 23 + 15, water["level"] + .04, z + 3), .07, C["white"])
    ribbon("water-river", river_rows, C["water"])
    ribbon("water-sea", sea_rows, C["water"])

    def truss(name, poses, half_width):
        for i, p in enumerate(poses):
            def at(side, height, p=p):
                return p.position.clone().addScaledVector(p.normal, side * half_width).add(Vector3(0, height, 0))
            for side in (-1, 1):
                beam(name, at(side, .3), at(side, 9), .45, C["steel"])
                if i < len(poses) - 1:
                    q = poses[i + 1]

                    def end(height, q=q, side=side):
                        return q.position.clone().addScaledVector(q.normal, side * half_width).add(Vector3(0, height, 0))
                    for height in (.3, 9):
                        add(name, T.section_beam_geometry(at(side, height), end(height), p.normal, q.normal, .5, .5,
                                                          [i == 0, i == len(poses) - 2]), C["steel"])
                    beam(name, at(side, 9 if i % 2 else .3), end(.3 if i % 2 else 9), .32, C["steel"])
                    if i % 2 == 0 and side == -1:
                        beam(name, at(-1, 9), q.position.clone().addScaledVector(q.normal, half_width).add(Vector3(0, 9, 0)),
                             .22, C["steel"])
            beam(name, at(-1, 9), at(1, 9), .4, C["steel"])

    river_z = (water["minZ"] + water["maxZ"]) / 2
    river_x = T.river_center_at(river_z)
    bridge_y = max(T.terrain_height_at(river_x - 58, river_z), T.terrain_height_at(river_x + 58, river_z),
                   water["level"] + 9) + 1
    bridge_poses = [T.Pose(Vector3(river_x - 60 + i * 15, bridge_y, river_z), Vector3(1, 0, 0), Vector3(0, 0, -1),
                           math.pi / 2) for i in range(9)]
    truss("venue-river-truss", bridge_poses, 6)
    box("venue-river-truss", Vector3(river_x, bridge_y - .6, river_z), [120, 1.2, 13], C["concrete"], 0, True)
    for x in (-58, 58):
        for z in (-5, 5):
            post("venue-river-truss", Vector3(river_x + x, 0, river_z + z), bridge_y, 1.4, C["concrete"])
    for x in (-59, 59):
        box("venue-river-truss", Vector3(river_x + x, bridge_y + .7, river_z), [1, 1.4, 12], C["red"], 0, True)
    for f in features:
        if f["kind"] != "bridge":
            continue
        count = min(30, max(4, math.ceil((f["end"] - f["start"]) * T.TRACK_LENGTH / 16)))
        poses = [T.track_pose(f["start"] + (f["end"] - f["start"]) * i / count) for i in range(count + 1)]
        width = max(max(T.shoulder_half_width_at(f["start"] + (f["end"] - f["start"]) * i / count, -1),
                        T.shoulder_half_width_at(f["start"] + (f["end"] - f["start"]) * i / count, 1))
                    for i in range(len(poses))) + 1
        truss("venue-circuit-truss", poses, width)

    if settings["density"] > 0:
        phase = jmod(settings["seed"], 97) / 97

        def in_tunnel(u):
            return any(f["kind"] == "tunnel" and f["start"] - .025 < u < f["end"] + .025 for f in features)

        def safe_overhead(p, radius, y):
            return all(jhypot(s.position.x - p.x, s.position.z - p.z) > radius or s.position.y < y - 7
                       or s.position.y > y + 6 for s in samples)

        screens = 0
        for i in range(32):
            if screens >= 2:
                break
            u = jmod(.1 + phase * .05 + i / 32, 1)
            if u > .91 or u < .09 or in_tunnel(u):
                continue
            p = T.track_pose(u)
            width = max(T.shoulder_half_width_at(u, -1), T.shoulder_half_width_at(u, 1)) + 5
            left = T.track_pose(u, -width).position
            right = T.track_pose(u, width).position
            top = max(p.position.y + 10, foot(left).y + 9, foot(right).y + 9)
            if not clear_post(left) or not clear_post(right) or not safe_overhead(p.position, width + 4, top):
                continue
            post("venue-led-gantry", left, top + 1.8, .75, C["dark"])
            post("venue-led-gantry", right, top + 1.8, .75, C["dark"])
            center = p.position.clone().setY(top)
            box("venue-led-gantry", center, [width * 2 + 1, 3.6, 1.1], C["dark"], p.yaw, True)
            for k in range(13):
                q = center.clone().addScaledVector(p.normal, (k / 12 * 2 - 1) * width).addScaledVector(p.tangent, .58)
                box("venue-led-gantry", q, [.045, 3.3, .03], C["steel"], p.yaw)
            front = center.clone().addScaledVector(p.tangent, -.58)
            signs.append({"position": front.toArray(), "yaw": p.yaw + math.pi, "title": "INKRACER  /  GRAND PRIX",
                          "subtitle": "01  APEX     02  INK     03  BOLT    |    SECTOR 01", "width": width * 2 - .5,
                          "height": 3.15, "electronic": True})
            lights = center.clone().add(Vector3(0, -2.5, 0))
            box("venue-race-signals", lights, [8, .9, .5], C["dark"], p.yaw)
            for k in range(-2, 3):
                lamp = lights.clone().addScaledVector(p.normal, k * 1.4).addScaledVector(p.tangent, -.3)
                add("venue-race-signals", CylinderGeometry(.28, .28, .12, 12).rotateX(math.pi / 2).rotateY(p.yaw)
                    .translate(lamp.x, lamp.y, lamp.z), C["red"])
            screens += 1

        fence_runs = 0
        for attempt in range(24):
            if fence_runs >= max(2, js_round(settings["density"] / 40)):
                break
            u = jmod(.13 + phase * .08 + attempt / 24, 1)
            side = -1 if attempt % 2 else 1
            if in_tunnel(u) or u < .1 or u > .88:
                continue
            points = []
            for i in range(5):
                t = u + i * 9 / T.TRACK_LENGTH
                points.append(T.track_pose(t, side * (T.shoulder_half_width_at(t, side) + 5)).position)
            if any(not clear_post(p, 1) for p in points):
                continue
            bases = [foot(p) for p in points]
            tops = [p.clone().add(Vector3(0, 5.5, 0)) for p in bases]
            for i, p in enumerate(points):
                post("venue-catch-fence", p, tops[i].y, .16, C["dark"])
            for i in range(4):
                for row in range(1, 7):
                    beam("venue-catch-fence", bases[i].clone().add(Vector3(0, row * .8, 0)),
                         bases[i + 1].clone().add(Vector3(0, row * .8, 0)), .035, C["steel"])
                for column in range(8):
                    bottom = bases[i].clone().lerp(bases[i + 1], (column + .5) / 8)
                    beam("venue-catch-fence", bottom.clone().add(Vector3(0, .5, 0)),
                         bottom.clone().add(Vector3(0, 5.4, 0)), .03, C["steel"])
            for i in (0, 4):
                post("venue-utility-poles", points[i], bases[i].y + 12, .32, C["concrete"])
                box("venue-utility-poles", bases[i].clone().add(Vector3(0, 11.5, 0)), [3, .18, .18], C["dark"])
            for offset in (-1, 0, 1):
                previous = None
                for i in range(17):
                    t = i / 16
                    q = bases[0].clone().lerp(bases[4], t)
                    q.x += offset
                    q.y += 11.8 - 6 * t * (1 - t)
                    if previous is not None:
                        beam("venue-power-cables", previous, q, .045, C["dark"])
                    previous = q
            fence_runs += 1

        barriers = 0
        for i in range(72):
            if barriers >= max(3, js_round(settings["density"] / 25)):
                break
            u = (i + phase) / 72
            if u < .1 or u > .88 or in_tunnel(u):
                continue
            a, p, b = T.track_pose(u - .007), T.track_pose(u), T.track_pose(u + .007)
            turn = a.tangent.x * b.tangent.z - a.tangent.z * b.tangent.x
            if abs(turn) < .08:
                continue
            side = -1 if turn < 0 else 1
            off = T.shoulder_half_width_at(u, side) + 3.5
            positions = [T.track_pose(u + (k - 4) * 1.28 / T.TRACK_LENGTH, side * off).position for k in range(9)]
            if any(not clear_post(q, .65) for q in positions):
                continue
            for k, q in enumerate(positions):
                base = foot(q)
                for row in range(3):
                    g = _real_tire() if REAL_TIRES else TorusGeometry(.42, .18, 5, 10).rotateX(math.pi / 2)
                    add("venue-tire-barrier", g.translate(q.x, base.y + .2 + row * .36, q.z),
                        C["white"] if k % 3 else C["red"])
                solids.append({"position": [q.x, base.y + .58, q.z], "size": [1.2, 1.16, 1.2], "yaw": p.yaw, "pitch": 0})
                reserve(q, [1.4, 1.2, 1.4])
            barriers += 1

        mountain_points = [T.track_pose(f["start"] + (f["end"] - f["start"]) * i / 16).position
                           for f in features if f["kind"] == "tunnel" for i in range(17)]
        previous_highway = None
        for parallel in (False, True):
            step, count = 22, 14

            def route(u, parallel=parallel):
                pose = T.track_pose(u)
                direction = pose.tangent.clone().setY(0).normalize() if parallel else pose.normal
                center = pose.position.clone().addScaledVector(pose.normal, 48 if parallel else 0)
                pts = [center.clone().addScaledVector(direction, (i - count / 2) * step) for i in range(count + 1)]
                return pose, direction, pts

            base_u = .65 if parallel else .25
            selected = route(base_u)
            for attempt in range(24):
                cand = route(jmod(base_u + attempt / 24, 1))
                if any(any(jhypot(p.x - q.x, p.z - q.z) < 85 for q in mountain_points) for p in cand[2]):
                    continue
                selected = cand
                break
            pose, direction, points = selected
            normal = Vector3(direction.z, 0, -direction.x)
            yaw = math.atan2(direction.x, direction.z)
            road_top = max([s.position.y for s in samples
                            if any(jhypot(s.position.x - p.x, s.position.z - p.z) < 40 for p in points)]
                           + [pose.position.y])
            y = max([road_top + 17] + [T.terrain_height_at(p.x, p.z) + 10 for p in points])
            for q in mountain_points:
                if any(jhypot(p.x - q.x, p.z - q.z) < 85 for p in points):
                    y = max(y, q.y + 65)
            for o in obstacles:
                if any(jhypot(p.x - o["position"][0], p.z - o["position"][2]) < 15 + jhypot(o["size"][0], o["size"][2]) / 2
                       for p in points):
                    y = max(y, o["position"][1] + o["size"][1] / 2 + 7)
            if previous_highway and any(any(jhypot(p.x - q.x, p.z - q.z) < 30 for q in previous_highway[0])
                                        for p in points):
                y = max(y, previous_highway[1] + 10)
            name = "venue-highway-parallel" if parallel else "venue-highway-crossing"
            for i in range(count):
                p = points[i].clone().lerp(points[i + 1], .5).setY(y)
                box(name, p.clone().add(Vector3(0, -1, 0)), [16, 2, step], C["concrete"], yaw, True)
                box(name, p.clone().add(Vector3(0, .04, 0)), [14, .08, step - .04], C["dark"], yaw)
                for side in (-1, 1):
                    box(name, p.clone().addScaledVector(normal, side * 7.65).add(Vector3(0, .7, 0)), [.45, 1.4, step],
                        C["concrete"], yaw, True)
                    box(name, p.clone().addScaledVector(normal, side * 3.5).add(Vector3(0, .1, 0)), [.12, .04, 8],
                        C["white"], yaw)
                box(name, p.clone().add(Vector3(0, .55, 0)), [.5, 1.1, step], C["concrete"], yaw)
            for p in points:
                if not clear_post(p, 4):
                    continue
                post(name, p, y - 2, 2.6, C["concrete"])
                box(name, p.clone().setY(y - 2.5), [13.5, 1, 3], C["concrete"], yaw)
            for p in (points[0], points[count]):
                box(name, p.clone().setY(y + .8), [15, 1.6, .8], C["red"], yaw, True)
            sign = points[3].clone().setY(y + 5)
            box(name, sign, [12, 3, .35], C["steel"], yaw)
            signs.append({"position": sign.clone().addScaledVector(direction, -.2).toArray(), "yaw": yaw + math.pi,
                          "title": "EXPRESSWAY", "subtitle": "CITY CENTER  /  THROUGH TRAFFIC", "width": 11.6,
                          "height": 2.6})
            for side in (-1, 1):
                beam(name, sign.clone().addScaledVector(normal, side * 5.4).setY(y + 1),
                     sign.clone().addScaledVector(normal, side * 5.4).setY(y + 6.5), .2, C["dark"])
            for i in range(count):
                reserve(points[i].clone().lerp(points[i + 1], .5), [20, y, step], yaw)
            previous_highway = (points, y)

    if settings["density"] > 0:
        yaxis = Vector3(0, 1, 0)

        class Frame:
            def __init__(self, name, origin, yaw=0):
                self.name, self.origin, self.yaw = name, origin, yaw

            def point(self, x, y, z):
                return Vector3(x, y, z).applyAxisAngle(yaxis, self.yaw).add(self.origin)

            def box(self, x, y, z, size, color, collide=False):
                box(self.name, self.point(x, y, z), size, color, self.yaw, collide)

            def beam(self, a, b, width, color=C["dark"]):
                beam(self.name, self.point(*a), self.point(*b), width, color)

            def mesh(self, g, x, y, z, color):
                p = self.point(x, y, z)
                add(self.name, g.rotateY(self.yaw).translate(p.x, p.y, p.z), color)

            def sign(self, x, y, z, title, width, subtitle="INKRACER / CIRCUIT FACILITIES"):
                signs.append({"position": self.point(x, y, z).toArray(), "yaw": self.yaw, "title": title,
                              "subtitle": subtitle, "width": width, "height": width / 5})

        def site(name, width, depth, start, pit=False):
            radius = jhypot(width, depth) / 2 + 2
            for attempt in range(160):
                ph = jmod(settings["seed"], 997) / 997
                u = jmod(.972 + (attempt % 12) * .005, 1) if pit else jmod(start + ph * .18 + (attempt % 32) / 32, 1)
                side = -1 if pit else (-1 if attempt % 2 else 1)
                p = T.track_pose(u, side * (T.shoulder_half_width_at(u, side) + radius + 12 + (attempt // 32) * 32))
                if not clear_post(p.position, radius):
                    continue
                base = Frame(name, p.position.clone().setY(0), p.yaw)
                levels = [foot(base.point(x * width, 0, z * depth)).y for x in (-.5, 0, .5) for z in (-.5, 0, .5)]
                low, high = min(levels), max(levels)
                if low < water["level"] + 1 or high - low > 16:
                    continue
                base.origin.y = high + .25
                reserve(base.origin, [width + 4, 1, depth + 4], p.yaw)
                base.box(0, (low - base.origin.y) / 2, 0, [width, base.origin.y - low + .4, depth], C["concrete"], True)
                return base
            return None

        def moving(m, name, at, kind, span, rate, phase=0, trigger_u=None):
            mo = {"name": name, "position": m.point(*at).toArray(), "yaw": m.yaw, "kind": kind, "span": span,
                  "rate": rate, "phase": phase}
            if trigger_u is not None:
                mo["triggerU"] = trigger_u
            motions.append(mo)
            return Frame(name, Vector3())

        def vehicle(m, x, y, z, color):
            m.box(x, y + .65, z, [1.9, .65, 4.2], color)
            m.box(x, y + 1.25, z - .25, [1.65, .65, 2], C["dark"])
            m.box(x, y + 1.63, z - .25, [1.75, .12, 2.1], color)
            for side in (-1, 1):
                for end in (-1, 1):
                    m.mesh(CylinderGeometry(.38, .38, .24, 10).rotateZ(math.pi / 2), x + side * .95, y + .4,
                           z + end * 1.3, C["dark"])
                    m.box(x + side * .65, y + .8, z + end * 2.12, [.42, .2, .06], C["white"] if end > 0 else C["red"])

        seed = settings["seed"]
        density = settings["density"]
        # 1. 港湾クレーン
        harbor = site("venue-harbor-crane", 58, 44, .46)
        if harbor:
            for x in (-17, 17):
                harbor.box(x, .08, 0, [.25, .16, 42], C["dark"])
                for z in (-11, 11):
                    harbor.box(x, 1, z, [3.5, 2, 6], C["dark"], True)
                    harbor.beam([x, 2, z], [x * .72, 30, z * .7], 1.1, C["steel"])
                    harbor.beam([x, 3, z], [-x * .72, 29, z * .7], .3, C["steel"])
            for z in (-8, 8):
                harbor.box(0, 30, z, [52, 1.2, 1.2], C["steel"])
                harbor.box(0, 33, z, [52, .4, .4], C["steel"])
                for x in range(-24, 24, 6):
                    harbor.beam([x, 30, z], [x + 6, 33, z], .22)
                harbor.beam([-10, 30, z], [-10, 46, z], .7, C["steel"])
                harbor.beam([-10, 46, z], [26, 33, z], .16)
            harbor.box(12, 28.3, 0, [4, 3, 5], C["white"])
            harbor.box(14.05, 28.5, 0, [.1, 1.8, 4.4], C["dark"])
            for z in (-3, 3):
                harbor.beam([8, 30, z], [8, 11, z], .07)
            harbor.box(8, 11, 0, [3.2, .5, 7], C["amber"])
            for i in range(min(9, 3 + int(math.floor(density / 20)))):
                x, z = -10 + (i % 3) * 7, -14 + (i // 3) * 13
                h = 2.6 * (1 + jmod(i + seed, 2))
                harbor.box(x, h / 2, z, [5.5, h, 10], C["steel"] if i % 2 else C["red"], True)
                for k in range(-4, 5):
                    harbor.box(x, h / 2, z + k, [5.58, h - .12, .08], C["dark"])
            harbor.sign(0, 31.4, 8.7, "PORT / 07", 13)

        # 2. 高架鉄道
        rail = site("venue-railway", 14, 142, .64)
        if rail:
            rail.box(0, 13, 0, [9, 1.5, 138], C["concrete"], True)
            for z in range(-66, 67, 22):
                rail.box(0, 5.7, z, [2.2, 11.4, 3], C["concrete"], True)
                rail.box(0, 11.9, z, [8, 1, 3], C["concrete"])
                for x in (-4, 4):
                    rail.beam([x, 13.7, z], [x, 20.5, z], .16)
                rail.beam([-4, 20.5, z], [4, 20.5, z], .15)
            for x in (-1, 1):
                rail.box(x, 14, 0, [.12, .22, 137], C["dark"])
            rail.box(0, 20, 0, [.04, .04, 137], C["dark"])
            for z in range(-67, 68, 2):
                rail.box(0, 13.82, z, [3.2, .14, .25], C["dark"])
            for x in (-4.2, 4.2):
                rail.box(x, 14.5, 0, [.2, 1.1, 138], C["steel"])
            for z in (-60, 60):
                rail.box(2.8, 14.2, z, [2.1, .55, 18], C["white"])
                rail.box(2.8, 18.3, z, [2.6, .25, 18], C["steel"])
                for end in (-1, 1):
                    rail.box(3.6, 16.3, z + end * 7, [.16, 4, .16], C["dark"])
            train = moving(rail, "venue-train", [0, 14.15, 0], "train", 42, .13, jmod(seed, 11) / 11)
            for z in (-10, 0, 10):
                train.box(0, 1.85, z, [2.65, 2.9, 9.2], C["white"])
                train.box(0, 3.4, z, [2.7, .2, 9.3], C["steel"])
                train.box(0, 1.05, z, [2.7, .3, 9.3], C["red"])
                for x in (-1.34, 1.34):
                    for dz in (-3, -1, 1, 3):
                        train.box(x, 2.5, z + dz, [.04, .95, 1.3], C["dark"])
                for dz in (-3, 3):
                    train.box(0, .23, z + dz, [2.2, .46, 1.4], C["dark"])
            for z in (-14.65, 14.65):
                train.box(0, 2.5, z, [2.2, 1, .05], C["dark"])
                train.box(0, .95, z, [2.15, .15, .06], C["amber"])
            train.beam([0, 3.5, -1], [0, 5.2, 0], .08)
            train.beam([0, 5.2, 0], [0, 5.8, -1], .08)
            rail.sign(0, 18, 69.1, "CIRCUIT EXPRESS", 8)

        # 3. ロープウェイ
        cable = site("venue-cableway", 18, 150, .28)
        if cable:
            for z in (-68, 68):
                cable.box(0, 2, z, [13, 4, 12], C["white"], True)
                cable.box(0, 4.25, z, [14, .5, 13], C["steel"])
                for x in (-5, 5):
                    cable.beam([x, 4.5, z], [x, 34, z], .5, C["steel"])
                cable.box(0, 34, z, [13, .5, 1], C["dark"])
                for x in (-3, 3):
                    cable.mesh(CylinderGeometry(1, 1, .3, 12).rotateZ(math.pi / 2), x, 33.8, z, C["dark"])
            for side in (-1, 1):
                for i in range(32):
                    z = -68 + i * 136 / 32
                    nxt = z + 136 / 32
                    cable.beam([side * 3, 34 - 4 * (1 - (z / 68) ** 2), z], [side * 3, 34 - 4 * (1 - (nxt / 68) ** 2), nxt],
                               .065)
                cabin = moving(cable, "venue-gondola-%d" % side, [side * 3, 34, 0], "gondola", 68, .10,
                               math.pi if side < 0 else 0)
                cabin.beam([0, 0, 0], [0, -2.4, 0], .12)
                cabin.box(0, -3.75, 0, [2.6, 2.7, 3.2], C["white"])
                cabin.box(0, -3.15, 0, [2.66, 1.1, 3.26], C["dark"])
                cabin.box(0, -2.35, 0, [2.9, .18, 3.5], C["red"])
                for x in (-1.28, 1.28):
                    cabin.box(x, -3.2, 0, [.1, 1.2, .12], C["white"])
            cable.sign(0, 3, 74.1, "RIDGE CABLEWAY", 10)

        # 4. ダム
        dam_z = water["minZ"] + (water["maxZ"] - water["minZ"]) * .18
        dam_x = T.river_center_at(dam_z)
        dam = Frame("venue-dam", Vector3(dam_x, water["level"], dam_z))
        if clear_post(dam.origin, 55):
            reserve(dam.origin, [104, 40, 64])
            for side in (-1, 1):
                dam.mesh(CylinderGeometry(14, 26, 32, 7), side * 36, 10, -8, C["concrete"])
                dam.box(side * 22, 10, -13, [6, 28, 38], C["concrete"], True)
            dam.box(0, 10, -29, [42, 28, 5], C["concrete"], True)
            dam.box(0, 21.5, -14, [38, .3, 27], C["water"])
            for i in range(-2, 3):
                wall = BoxGeometry(8, 24, 10)
                pos = wall.attributes["position"]
                for k in range(pos.count):
                    if pos.getY(k) > 0:
                        pos.setZ(k, pos.getZ(k) * .42)
                wall.computeVertexNormals()
                dam.mesh(wall, i * 8, 10, 4, C["concrete"])
                dam.box(i * 8, 23, 4, [7.6, .6, 6], C["white"])
            dam.box(0, 21, 7, [17, .3, 4], C["water"])
            dam.box(0, 10.5, 9.1, [16, 21, .16], C["water"])
            for x in (-18, -9, 0, 9, 18):
                dam.beam([x, 23.4, 2], [x, 25, 2], .12)
            dam.beam([-19, 25, 2], [19, 25, 2], .12)
            flow = moving(dam, "venue-waterfall", [0, 20, 9.3], "water", 3, .9)
            for i in range(18):
                flow.box(-7.5 + (i % 6) * 3, -(i // 6) * 5.6, 0, [.14 + i % 3 * .1, 2.4, .06], C["white"])
            for i in range(7):
                dam.mesh(SphereGeometry(1, 8, 5).scale(2.6, .3, 2.4), -8 + i * 2.7, .3, 10 + i % 2 * 2, C["white"])
            dam.sign(0, 18, 9.3, "INK RIVER DAM", 12)

        # 5. 配管設備
        pipes = site("venue-pipeworks", 34, 32, .15)
        if pipes:
            for x in (-10, 10):
                pipes.mesh(CylinderGeometry(4.2, 4.2, 16, 16), x, 8, -5, C["white"])
                pipes.box(x, 8, -5, [6, 16, 6], C["white"], True)
                for y in (1, 7, 13, 16.1):
                    pipes.mesh(CylinderGeometry(4.28, 4.28, .16, 16), x, y, -5, C["steel"])
                for dx in (-.5, .5):
                    pipes.beam([x + dx, .2, -.65], [x + dx, 16.4, -.65], .08)
                y = .5
                while y < 16:
                    pipes.beam([x - .5, y, -.6], [x + .5, y, -.6], .07)
                    y += .7
            for z in (-11, 0, 11):
                for x in (-3, 3):
                    pipes.box(x, 4.5, z, [.25, 9, .25], C["steel"], True)
                pipes.box(0, 8.8, z, [7, .25, .4], C["steel"])
            for x in (-2, 0, 2):
                path = CurvePath()
                a, b, c = Vector3(0, 9.3, -13.5), Vector3(0, 9.3, 12.6), Vector3(0, 8.4, 13.5)
                path.add(LineCurve3(a, b))
                path.add(QuadraticBezierCurve3(b, Vector3(0, 9.3, 13.5), c))
                path.add(LineCurve3(c, Vector3(0, 1.3, 13.5)))
                pipes.mesh(TubeGeometry(path, 64, .45, 10, False), x, 0, 0, C["red"])
                pipes.mesh(TorusGeometry(.75, .10, 6, 12), x, 2.5, 14.1, C["dark"])
                pipes.beam([x - .7, 2.5, 14.1], [x + .7, 2.5, 14.1], .08)
            pipes.sign(0, 6.5, 14.3, "PUMP / 03", 6)

        # 6. 採石場
        quarry = site("venue-quarry", 66, 62, .39)
        if quarry:
            profile = [[10, 0], [10, 1], [15, 1], [17, 5], [21, 5], [23, 10], [27, 10], [30, 17], [32, 17], [32, -.2],
                       [10, -.2], [10, 0]]
            rock = LatheGeometry([Vector2(x, y) for x, y in profile[::-1]], 20).toNonIndexed()
            rock.computeVertexNormals()
            rock.setIndex(list(range(rock.attributes["position"].count)))
            quarry.mesh(rock, 0, 0, -1, C["concrete"])
            quarry.beam([0, 2, 14], [0, 18, -24], 2.2, C["dark"])
            for i in range(9):
                z, y = 14 - i * 4.75, 2 + i * 2
                quarry.box(0, y / 2, z, [1, y, 1], C["steel"], True)
                quarry.mesh(CylinderGeometry(.3, .3, 3.2, 8).rotateZ(math.pi / 2), 0, y + .2, z, C["steel"])
            for x in (-1.6, 1.6):
                quarry.beam([x, 2.8, 14], [x, 18.8, -24], .12, C["steel"])
            quarry.mesh(CylinderGeometry(4, 1.6, 5, 4), 0, 19, -24, C["red"])
            quarry.sign(18, 5, 19, "QUARRY / KEEP OUT", 9)

        # 7. 立体駐車場
        parking = site("venue-parking", 36, 32, .78)
        if parking:
            for level in range(4):
                y = .2 + level * 3.6
                parking.box(0, y, 0, [26, .4, 28], C["concrete"], True)
                for x in (-12, 0, 12):
                    for z in (-12, 0, 12):
                        if level < 3:
                            parking.box(x, y + 1.8, z, [.65, 3.2, .65], C["concrete"], True)
                parking.box(-12.8, y + .7, 0, [.25, 1, 28], C["white"])
                parking.box(12.8, y + .7, 0, [.25, 1, 20], C["white"])
                for z in (-13.8, 13.8):
                    parking.box(0, y + .7, z, [26, 1, .25], C["white"])
                for k in range(3):
                    vehicle(parking, -8 + k * 7, y + .2, -8 if k % 2 else 7, C["red"] if k % 2 else C["steel"])
                if level < 3:
                    ramp = BoxGeometry(3.6, .3, 27).rotateX(-math.atan2(3.6, 27))
                    parking.mesh(ramp, 15.3, y + 1.8, 0, C["concrete"])
                    parking.beam([17.2, y + .9, -13.4], [17.2, y + 4.5, 13.4], .18, C["steel"])
                    parking.box(13.6, y + 3.6, 12.5, [7.2, .35, 3], C["concrete"])
                    parking.box(13.6, y, -12.5, [7.2, .35, 3], C["concrete"])
            parking.box(-9, 12.5, 14.1, [4, 3, .3], C["steel"])
            parking.sign(-9, 12.5, 14.3, "P", 3, "PARKING")

        # 8. パラボラアンテナ
        dish = site("venue-observatory", 26, 26, .56)
        if dish:
            dish.box(0, 3, 0, [5, 6, 5], C["concrete"], True)
            dish.mesh(CylinderGeometry(2.8, 2.8, .8, 16), 0, 6, 0, C["steel"])
            antenna = moving(dish, "venue-parabolic-dish", [0, 9, 0], "dish", 0, .075, seed * .013)
            face = [Vector2(i * 1.1, (i * 1.1) * (i * 1.1) / 30) for i in range(10)]
            prof = face + [Vector2(p.x, p.y - .25) for p in face[::-1]] + [Vector2(0, 0)]
            prof.reverse()
            antenna.mesh(LatheGeometry(prof, 24).rotateX(math.pi / 3), 0, 0, 0, C["white"])
            xaxis = Vector3(1, 0, 0)
            for i in range(8):
                angle = i * math.pi / 4
                rim = Vector3(math.cos(angle) * 9.9, 3.2, math.sin(angle) * 9.9).applyAxisAngle(xaxis, math.pi / 3)
                for j in range(3):
                    def back(r, angle=angle):
                        return Vector3(math.cos(angle) * r, r * r / 30 - .38, math.sin(angle) * r).applyAxisAngle(
                            xaxis, math.pi / 3).toArray()
                    antenna.beam(back(j * 3.3), back((j + 1) * 3.3), .13, C["steel"])
                if i % 2 == 0:
                    antenna.beam(rim.toArray(), [0, 3.8, 6.58], .09, C["dark"])
            antenna.box(0, 3.8, 6.58, [1.1, .9, 1.4], C["dark"])
            dish.sign(0, 3, 3, "TELEMETRY", 4)

        # 9. 工事現場
        works = site("venue-construction", 24, 22, .86)
        if works:
            for x in (-1.6, 1.6):
                works.box(x - 4, .6, 0, [.8, 1.2, 5], C["dark"], True)
            works.box(-4, 1.5, 0, [3.5, 1, 3.8], C["amber"], True)
            works.box(-4.8, 3, -.5, [1.7, 2, 2.2], C["dark"])
            works.box(-4.8, 4.1, -.5, [2, .2, 2.4], C["amber"])
            works.beam([-3.2, 2, 1], [-3.2, 6, 4], .55, C["amber"])
            works.beam([-3.2, 6, 4], [-3.2, 2, 7], .45, C["amber"])
            works.beam([-3, 2.5, 1.4], [-3, 5.5, 3.8], .17, C["dark"])
            works.box(-3.2, 1.3, 7, [2.3, 1.5, 1.6], C["dark"])
            for i in range(4):
                works.box(-4 + i * .55, .45, 7.8, [.2, .4, .65], C["amber"])
            for x in (5, 10):
                for z in (-6, 0):
                    works.beam([x, 0, z], [x, 8, z], .12, C["steel"])
            for y in (2, 4.5, 7):
                works.box(7.5, y, -3, [5.5, .15, 6.5], C["white"])
                works.beam([5, y, 0], [10, y + 1.8, 0], .08)
            for i in range(5):
                works.mesh(CylinderGeometry(.4, .4, 5, 8).rotateZ(math.pi / 2), 6, .45 + (i // 3) * .75, 5 + i % 3,
                           C["concrete"])
            works.beam([-10, 0, -8], [-10, 9, -8], .16)
            works.box(-10, 9, -8, [3, .6, .5], C["amber"])
            works.sign(5, 2, 9, "WORK ZONE", 7)

        # 10. マーシャルポスト
        for i in range(max(1, math.ceil(density / 60))):
            marshal = site("venue-marshal-%d" % i, 7, 7, .12 + i * .27)
            if not marshal:
                continue
            marshal.box(0, .4, 0, [5, .8, 5], C["concrete"], True)
            marshal.box(0, 1.6, -1.8, [4.8, 2.4, .25], C["white"], True)
            for x in (-2.3, 2.3):
                marshal.box(x, 2, -.5, [.2, 2.5, 3], C["steel"])
            marshal.box(0, 3.5, -.5, [5.7, .3, 4.5], C["steel"])
            for x in (-.22, .22):
                marshal.box(x, 1.2, 1, [.24, .8, .3], C["dark"])
            marshal.box(0, 2, 1, [.7, .85, .4], C["amber"])
            marshal.mesh(SphereGeometry(.3, 8, 6), 0, 2.7, 1, C["white"])
            marshal.beam([.35, 2.3, 1], [1, 2.65, 1], .18, C["amber"])
            flag = moving(marshal, "venue-marshal-flag-%d" % i, [1, 2.65, 1], "flag", 0, 3.2, i)
            flag.beam([0, 0, 0], [0, 1.8, 0], .04)
            flag.box(.55, 1.35, 0, [1.1, .8, .04], C["amber"])
            marshal.sign(0, 3, 1.55, "POST %d" % (i + 1), 3.4)

        # 11. ピット整備棟
        service = site("venue-pit-service", 13, 12, 0, True)
        if service:
            for x in (-6, 6):
                for z in (-5, 5):
                    service.box(x, 2.2, z, [.18, 4.4, .18], C["steel"], True)
            service.box(0, 4.5, 0, [13, .25, 12], C["steel"])
            vehicle(service, -1.6, .55, 0, C["red"])
            service.box(-1.6, .3, 0, [1.5, .6, 2.8], C["dark"], True)
            service.beam([-1.6, .2, 1.5], [-1.6, 1.1, 3.2], .10, C["red"])
            service.box(4.5, .8, -3, [2, 1.6, 3], C["red"], True)
            for i in range(4):
                service.box(4.5, .4 + i * .3, -1.45, [1.7, .07, .08], C["dark"])
            for x in (-4, -1, 2):
                service.box(x, 1.1, -4.7, [2.6, .15, 1.3], C["white"])
            for y in (.45, 1.6):
                service.box(4.6, y - .25, 2, [2, .16, 4], C["steel"])
                for z in (1, 2.2, 3.4):
                    service.mesh(TorusGeometry(.43, .18, 6, 12), 4.6, y + .35, z, C["dark"])
            service.mesh(CylinderGeometry(.45, .45, 1.6, 12), -5, .8, 3, C["amber"])
            for i in range(8):
                service.beam([-5 + i * .28, .12, 3 + math.sin(i * .6)], [-5 + (i + 1) * .28, .12, 3 + math.sin((i + 1) * .6)],
                             .06)
            service.sign(0, 3.7, 6.15, "PIT / SERVICE", 9, "TOOLS / TYRES / FUEL")

        # ヘリコプター
        tunnel_spot = next((f for f in features if f["kind"] == "tunnel"), None)
        heli_u = min(.96, tunnel_spot["end"] + .018) if tunnel_spot else .62
        heli_base = T.track_pose(heli_u).position.clone()
        heli_base.y = max(heli_base.y + 42, T.terrain_height_at(heli_base.x, heli_base.z) + 42)
        heli = moving(Frame("venue-helicopter-mount", heli_base), "venue-helicopter", [0, 0, 0], "helicopter", 42, .26,
                      -math.pi / 2, heli_u)
        heli.box(0, 0, 0, [2.6, 1.2, 5.4], C["white"])
        heli.box(0, .18, -1.75, [2.2, .65, 1.7], C["dark"])
        heli.box(0, .72, 2.2, [.5, .5, 4.4], C["steel"])
        heli.box(0, .95, 0, [8.2, .14, .24], C["dark"])
        heli.box(0, .95, 0, [.24, .14, 4.1], C["dark"])
        for side in (-1, 1):
            heli.beam([side * .85, -.65, -1.2], [side * .85, -.65, 1.7], .12)
            heli.beam([side * .85, -.65, 0], [side * 1.05, 0, 0], .1)
        heli.box(0, -.82, -1.2, [3.6, .12, .18], C["steel"])
        heli.box(0, -.82, 1.2, [3.6, .12, .18], C["steel"])
        heli.box(0, .35, -2.65, [.18, 1.15, .18], C["red"])
        heli.box(0, .35, 2.75, [.18, .5, .18], C["amber"])

        # 12. 飛行船
        air_base = T.track_pose(.4).position.clone()
        air_base.y = max([s.position.y for s in samples] + [o["position"][1] + o["size"][1] / 2 for o in obstacles]
                         + [o["position"][1] + o["size"][1] / 2 for o in solids]) + 100
        airship = moving(Frame("venue-airship-mount", air_base), "venue-airship", [0, 0, 0], "airship", 95, .045,
                         seed * .013)
        airship.mesh(SphereGeometry(1, 20, 12).scale(7, 7, 23), 0, 0, 0, C["white"])
        for side in (-1, 1):
            airship.box(side * 5.3, 0, -17, [8, .25, 8], C["steel"])
            airship.box(0, side * 5.3, -17, [.25, 8, 8], C["red"])
            airship.beam([side * 3, -5.5, -2], [side * 1.2, -8, 0], .1)
            airship.box(side * 6.75, 0, 0, [.14, 2, 8], C["red"])
        airship.box(0, -8, 0, [3, 2.2, 6], C["steel"])
        airship.box(0, -7.8, 3.05, [2.6, 1, .08], C["dark"])

    all_batches = []
    for i, g in enumerate(groups.values()):
        geometry = mergeGeometries(g["parts"])
        all_batches.append({"name": "%s-%d" % (g["name"], i), "color": g["color"], "geometry": geometry,
                            "edges": EdgesGeometry(geometry, 35)})
    prefix = lambda n: n[:n.rindex("-")]
    animated = {m["name"] for m in motions}
    batches = [b for b in all_batches if prefix(b["name"]) not in animated]
    animations = [dict(m, batches=[b for b in all_batches if prefix(b["name"]) == m["name"]]) for m in motions]
    return {"batches": batches, "solids": solids, "reserved": reserved, "signs": signs, "animations": animations}

"""IndustrialWorld.tsx の buildDistrict（自動生成コース用の部分）、windTurbine.ts、scenery.ts の移植"""
import math
from .three import (Vector2, Vector3, Quaternion, Matrix4, BufferGeometry, BufferAttribute, f32, jmod, jhypot,
                    js_round, lcg_random, to_fixed)
from .geometries import (BoxGeometry, CylinderGeometry, PlaneGeometry, LatheGeometry, ExtrudeGeometry, Shape,
                         EdgesGeometry, mergeGeometries, triangulate_shape)
from . import track as T
from . import city as CITY
from . import venue as V
from . import mountain as MOUNT

C = {"ink": "#263c50", "road": "#53616a", "paper": "#f1e6cc", "rust": "#b95836", "blue": "#45768a",
     "concrete": "#aaa993", "sand": "#c9bc9c", "green": "#758779", "glass": "#284f62", "yellow": "#e3ae55"}

# ---------------------------------------------------------------- windTurbine.ts

TURBINE_HUB_HEIGHT = 43.2
TURBINE_ROTOR_OFFSET = 2.7
TURBINE_RADIUS = 19.1
_T_PAPER, _T_STEEL, _T_INK = "#f1e6cc", "#758779", "#263c50"


def turbine_body():
    casing = Shape()
    casing.moveTo(-.95, -1).lineTo(.95, -1).lineTo(1.2, -.7)
    casing.lineTo(1.2, .7).lineTo(.9, 1.05).lineTo(-.9, 1.05)
    casing.lineTo(-1.2, .7).lineTo(-1.2, -.7).closePath()
    nacelle = ExtrudeGeometry(casing, depth=4.2, bevelEnabled=True, bevelSize=.18, bevelThickness=.18,
                              bevelSegments=1, steps=1).translate(0, TURBINE_HUB_HEIGHT, -2.6)
    nacelle.setIndex(list(range(nacelle.attributes["position"].count)))
    parts = [
        {"name": "Turbine foundation", "geometry": CylinderGeometry(2, 2.3, .8, 12).translate(0, .2, 0), "color": "#aaa993"},
        {"name": "Tapered turbine tower", "geometry": CylinderGeometry(.66, 1.35, 41.7, 16).translate(0, 21.45, 0),
         "color": _T_PAPER},
        {"name": "Yaw bearing", "geometry": CylinderGeometry(.88, .88, .45, 16).translate(0, 42.4, 0), "color": _T_STEEL},
        {"name": "Nacelle", "geometry": nacelle, "color": _T_PAPER},
        {"name": "Rotor shaft", "geometry": CylinderGeometry(.48, .48, 1.2, 12).rotateX(math.pi / 2)
            .translate(0, TURBINE_HUB_HEIGHT, 2.1), "color": _T_STEEL},
        {"name": "Service door", "geometry": BoxGeometry(.7, 1.9, .08).translate(0, 1.65, 1.33), "color": _T_STEEL},
        {"name": "Door handle", "geometry": BoxGeometry(.06, .28, .08).translate(.23, 1.65, 1.41), "color": _T_INK},
        {"name": "Roof hatch", "geometry": BoxGeometry(1.05, .1, 1.4).translate(0, 44.47, -.9), "color": _T_STEEL},
    ]
    for height in (14, 28):
        r = 1.35 - (height - .6) / 41.7 * .69 + .015
        parts.append({"name": "Tower joint", "geometry": CylinderGeometry(r, r, .055, 16).translate(0, height, 0),
                      "color": _T_STEEL})
    for side in (-1, 1):
        for i in range(5):
            parts.append({"name": "Cooling vent", "geometry": BoxGeometry(.035, .5, .055)
                          .translate(side * 1.39, 43.2, -1.9 + i * .22), "color": _T_INK})
    return parts


def _blade_geometry():
    stations = [[.65, .43, 0, .3, 24], [1.5, .7, .03, .28, 20], [3.3, 1.55, .18, .24, 15],
                [7, 1.3, .33, .18, 10], [12, .86, .43, .12, 6], [16.7, .4, .53, .065, 3], [19, .045, .6, .025, 0]]
    section = [[-.5, 0], [-.32, .8], [0, 1], [.34, .5], [.5, 0], [.34, -.3], [0, -.5], [-.32, -.4]]
    positions, indices, uv = [], [], []
    for row, (radius, chord, sweep, thickness, angle) in enumerate(stations):
        pitch = angle * math.pi / 180
        for col, (x, z) in enumerate(section):
            positions.extend((sweep + x * chord * math.cos(pitch) + z * thickness * math.sin(pitch), radius,
                              -x * chord * math.sin(pitch) + z * thickness * math.cos(pitch) + radius * .035))
            uv.extend((col / len(section), radius / 19))
            if row < len(stations) - 1:
                a, b = row * 8 + col, row * 8 + (col + 1) % 8
                indices.extend((a, b, a + 8, b, b + 8, a + 8))
    end = (len(stations) - 1) * 8
    for i in range(1, 7):
        indices.extend((0, i + 1, i))
        indices.extend((end, end + i, end + i + 1))
    g = BufferGeometry()
    g.setAttribute("position", BufferAttribute(f32(positions), 3))
    g.setAttribute("uv", BufferAttribute(f32(uv), 2))
    g.setIndex(indices)
    g.computeVertexNormals()
    return g


def turbine_rotor():
    blade = _blade_geometry()
    blades = [blade.clone().rotateZ(i * math.pi * 2 / 3) for i in range(3)]
    geometry = mergeGeometries(blades)
    hub = LatheGeometry([Vector2(0, -.35), Vector2(.85, -.35), Vector2(1.05, 0), Vector2(.94, .55), Vector2(.5, 1.2),
                         Vector2(0, 1.65)], 16).rotateX(math.pi / 2)
    return [{"name": "Wind Turbine Blades", "geometry": geometry, "color": _T_PAPER},
            {"name": "Wind Turbine Hub", "geometry": hub, "color": _T_PAPER}]


# ---------------------------------------------------------------- scenery.ts

DEFAULT_SCENERY = {"density": 100, "seed": 73}


def parse_scenery(value):
    if not isinstance(value, dict):
        return dict(DEFAULT_SCENERY)
    d, s = value.get("density"), value.get("seed")
    ok = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
    return {"density": js_round(max(0, min(200, d)) / 10) * 10 if ok(d) else DEFAULT_SCENERY["density"],
            "seed": int(s) if ok(s) and float(s).is_integer() and 0 <= s <= 999999 else DEFAULT_SCENERY["seed"]}


def generate_scenery(settings, obstacles):
    st = parse_scenery(settings)
    density, seed = st["density"], st["seed"]
    random = lcg_random(seed)
    objects = []
    target = js_round(density * .8)
    gen = T.activeMap.get("generated")
    for attempt in range(2400):
        if len(objects) >= target:
            break
        u = random()
        side = -1 if random() < .5 else 1
        pose = T.track_pose(u, side * (20 + random() * 65))
        x, z = pose.position.x, pose.position.z
        kind = int(math.floor(random() * 10))
        scale = .8 + random() * .4
        radius = (TURBINE_RADIUS + 3) * scale if kind == 6 else 6
        nearest = T.nearest_track(x, z)
        if (not gen and x + radius > 386) or nearest.distance < 13 + radius:
            continue
        road_side = -1 if ((x - nearest.position.x) * nearest.normal.x + (z - nearest.position.z) * nearest.normal.z) < 0 else 1
        if gen and nearest.distance < T.shoulder_half_width_at(nearest.u, road_side) + 2.5 + (radius if kind == 6 else 0):
            continue
        hit = False
        for o in obstacles:
            dx, dz = x - o["position"][0], z - o["position"][2]
            lx = dx * math.cos(o["yaw"]) - dz * math.sin(o["yaw"])
            lz = dx * math.sin(o["yaw"]) + dz * math.cos(o["yaw"])
            if jhypot(max(0, abs(lx) - o["size"][0] / 2), max(0, abs(lz) - o["size"][2] / 2)) < radius + 2:
                hit = True
                break
        if hit:
            continue
        if any(jhypot(o["x"] - x, o["z"] - z) < o["radius"] + radius + 3 for o in objects):
            continue
        objects.append({"x": x, "z": z, "yaw": jmod(seed * .013, math.pi * 2) if kind == 6 else pose.yaw, "kind": kind,
                        "scale": scale, "radius": radius})
    return objects


# ---------------------------------------------------------------- buildDistrict

def _compose_matrix(a, b):
    return Matrix4().compose(a.clone().add(b).multiplyScalar(.5),
                             Quaternion().setFromUnitVectors(Vector3(0, 1, 0), b.clone().sub(a).normalize()),
                             Vector3(1, 1, 1))


def build_district(scenery):
    if CITY.is_city():
        return CITY.build_city(scenery)
    if (T.activeMap.get("parameters") or {}).get("layout") == "touge":
        return MOUNT.build_mountain_district(scenery)
    groups = {}
    solids, signs, turbines = [], [], []
    ground_cache = {}
    am = T.activeMap
    features = am.get("features") or []

    def ground(x, z):
        key = to_fixed(x, 3) + ":" + to_fixed(z, 3)
        if key not in ground_cache:
            ground_cache[key] = T.ground_offset_at(x, z)
        return ground_cache[key]

    def add(g, color, x, y, z, yaw=0):
        g.deleteAttribute("uv")
        g.rotateY(yaw)
        g.translate(x, y, z)
        key = g.name + color + ":" + str(int(math.floor(x / 100))) + ":" + str(int(math.floor(z / 100)))
        if key not in groups:
            groups[key] = {"name": g.name or None, "color": color, "parts": []}
        groups[key]["parts"].append(g)

    def box(x, y, z, w, h, d, color, yaw=0):
        add(BoxGeometry(w, h, d), color, x, y + ground(x, z), z, yaw)

    def cylinder(x, y, z, r, h, color):
        add(CylinderGeometry(r, r, h, 12), color, x, y + ground(x, z), z)

    def beam(a, b, width, color, follow_ground=True):
        g = BoxGeometry(width, a.distanceTo(b), width)
        g.applyMatrix4(_compose_matrix(a, b))
        center = a.clone().add(b).multiplyScalar(.5)
        add(g, color, 0, ground(center.x, center.z) if follow_ground else 0, 0)
        if not follow_ground:
            d = b.clone().sub(a)
            solids.append({"position": center.toArray(), "size": [width, d.length(), width],
                           "yaw": math.atan2(d.x, d.z), "pitch": math.atan2(jhypot(d.x, d.z), d.y)})

    def track_box(x, y, z, w, h, d, color, yaw=0):
        add(BoxGeometry(w, h, d), color, x, y, z, yaw)

    def rail(a, b, na, nb, width, color, caps):
        g = T.section_beam_geometry(a, b, na, nb, width, width, caps)
        g.name = "road-guardrail"
        add(g, color, 0, 0, 0)
        d = b.clone().sub(a)
        center = a.clone().add(b).multiplyScalar(.5)
        solids.append({"position": center.toArray(), "size": [width, d.length(), width],
                       "yaw": math.atan2(d.x, d.z), "pitch": math.atan2(jhypot(d.x, d.z), d.y)})

    def push_solid(solid):
        offset = ground(solid["position"][0], solid["position"][2]) if solid.get("pitch") is None else 0
        s = dict(solid)
        s["position"] = [solid["position"][0], solid["position"][1] + offset, solid["position"][2]]
        solids.append(s)

    def local(u, off, y, w, h, d, color):
        p = T.track_pose(u, off)
        pitch = -math.asin(p.tangent.y)
        add(BoxGeometry(w, h, d).rotateX(pitch), color, p.position.x, p.position.y + y, p.position.z, p.yaw)

    L = T.TRACK_LENGTH
    count = math.ceil(L / 3)
    up075 = Vector3(0, .75, 0)
    for i in range(count):
        u = i / count
        median = T.median_half_width_at(u)
        next_median = T.median_half_width_at((i + 1) / count)
        if median > .95 and next_median > .95:
            for side in (-1, 1):
                a = T.track_pose(u, side * (median - .3)).position.add(up075)
                b = T.track_pose((i + 1) / count, side * (next_median - .3)).position.add(up075)
                rail(a, b, T.track_pose(u).normal, T.track_pose((i + 1) / count).normal, .18, C["concrete"],
                     [T.median_half_width_at((i - 1) / count) <= .95, T.median_half_width_at((i + 2) / count) <= .95])
                if i % 3 == 0:
                    track_box(a.x, a.y - .25, a.z, .16, 1, .16, C["ink"])
                    solids.append({"position": [a.x, a.y - .25, a.z], "size": [.16, 1, .16], "yaw": 0, "pitch": 0})
        if median >= .7 and (T.median_half_width_at((i - 1) / count) < .7 or next_median < .7):
            p = T.track_pose(u).position
            for band in range(5):
                drum = CylinderGeometry(.52, .52, .22, 12)
                idx = drum.index.array
                keep = []
                for g in drum.groups:
                    if g["materialIndex"] == 0 or (g["materialIndex"] == 1 and band == 4) or (
                            g["materialIndex"] == 2 and band == 0):
                        keep.extend(idx[g["start"]:g["start"] + g["count"]])
                drum.setIndex(keep)
                drum.clearGroups()
                add(drum, C["ink"] if band % 2 else C["yellow"], p.x, p.y + .11 + band * .22, p.z)
            solids.append({"position": [p.x, p.y + .55, p.z], "size": [.94, 1.1, .94], "yaw": 0, "pitch": 0})
        for side in (-1, 1):
            local(u, side * (T.paved_half_width_at(u, side) + .6), .045, 1.1, .07, L / count - .04,
                  C["paper"] if i % 2 else C["rust"])
            ro = T.guardrail_offset_at(u, side)
            nro = T.guardrail_offset_at((i + 1) / count, side)
            if ro is None or nro is None:
                continue
            rs = T.track_pose(u, side * ro).position.clone().add(Vector3(0, .8, 0))
            re = T.track_pose((i + 1) / count, side * nro).position.clone().add(Vector3(0, .8, 0))
            rail(rs, re, T.track_pose(u).normal, T.track_pose((i + 1) / count).normal, .18, C["concrete"],
                 [T.guardrail_offset_at((i - 1) / count, side) is None, T.guardrail_offset_at((i + 2) / count, side) is None])
            if i % 3 == 0:
                p = T.track_pose(u, side * ro)
                track_box(p.position.x, p.position.y + .65, p.position.z, .25, 1.3, .25, C["ink"], p.yaw)
                push_solid({"position": [p.position.x, p.position.y + .65, p.position.z], "size": [.25, 1.3, .25],
                            "yaw": p.yaw, "pitch": 0})
        if i % 12 == 0 and T.pit_blend_at(u) == 0 and not any(
                f["kind"] == "tunnel" and f["start"] <= u <= f["end"] for f in features):
            p = T.track_pose(u, -12.5)
            cylinder(p.position.x, p.position.y + 4, p.position.z, .13, 8, C["ink"])
            box(p.position.x, p.position.y + 8, p.position.z, 2.5, .18, .2, C["ink"], p.yaw)
            box(p.position.x, p.position.y + 7.86, p.position.z, 1.7, .08, .35, C["paper"], p.yaw)

    def utility_pipe_bridge(u, span):
        pose = T.track_pose(u)
        deck = 12.2
        forward = Vector3(math.sin(pose.yaw), 0, math.cos(pose.yaw))
        across = pose.normal.clone().setY(0).normalize()

        def point(lateral, height, along):
            return pose.position.clone().addScaledVector(across, lateral).addScaledVector(forward, along).add(
                Vector3(0, height, 0))

        def structural(a, b, width, color):
            g = BoxGeometry(width, a.distanceTo(b), width)
            g.name = "utility-pipe-truss"
            g.applyMatrix4(_compose_matrix(a, b))
            add(g, color, 0, 0, 0)

        def pipe(a, b, radius, color):
            g = CylinderGeometry(radius, radius, a.distanceTo(b), 12)
            g.name = "utility-pipe"
            g.applyMatrix4(_compose_matrix(a, b))
            add(g, color, 0, 0, 0)

        track_box(pose.position.x, pose.position.y + deck - .2, pose.position.z, span, .4, 5.2, C["concrete"], pose.yaw)
        for along in (-1.55, 1.55):
            pipe(point(-span / 2, deck + .6, along), point(span / 2, deck + .6, along), .58, C["blue"])
        for along in (-2.25, 2.25):
            structural(point(-span / 2, deck + 3.3, along), point(span / 2, deck + 3.3, along), .2, C["ink"])
            structural(point(-span / 2, deck + .45, along), point(span / 2, deck + .45, along), .14, C["ink"])
            lateral = -span / 2
            while lateral <= span / 2:
                structural(point(lateral, deck + .45, along), point(lateral, deck + 3.3, along), .13, C["ink"])
                lateral += 5
            lateral = -span / 2
            while lateral < span / 2:
                nxt = lateral + 5
                structural(point(lateral, deck + .45, along), point(nxt, deck + 3.3, along), .13, C["ink"])
                structural(point(nxt, deck + .45, along), point(lateral, deck + 3.3, along), .13, C["ink"])
                lateral += 5
        for along in (-2.45, 2.45):
            structural(point(-span / 2, deck + 1.35, along), point(span / 2, deck + 1.35, along), .11, C["ink"])
            lateral = -span / 2
            while lateral <= span / 2:
                structural(point(lateral, deck, along), point(lateral, deck + 1.35, along), .1, C["ink"])
                lateral += 5
        for lateral in (-span / 2 + 2.5, span / 2 - 2.5):
            for along in (-1.7, 1.7):
                p = point(lateral, 0, along)
                base = ground(p.x, p.z)
                top = pose.position.y + deck - .4
                height = top - base
                if height <= .5:
                    continue
                track_box(p.x, base + height / 2, p.z, .85, height, .85, C["ink"], pose.yaw)
                track_box(p.x, base + .18, p.z, 2.2, .36, 2.2, C["concrete"], pose.yaw)
                solids.append({"position": [p.x, base + height / 2, p.z], "size": [.85, height, .85], "yaw": pose.yaw,
                               "pitch": 0})

    gen = am.get("generated")
    pipe_u = .36 + jmod(scenery["seed"], 29) / 100 if gen else .52
    blocked = any((f["kind"] in ("tunnel", "bridge")) and f["start"] - .025 <= pipe_u <= f["end"] + .025 for f in features)
    if not blocked:
        utility_pipe_bridge(pipe_u, 60 if gen else 56)
    for i in range(16):
        for row in range(2):
            p = T.track_pose((.4 + row) / L, -7.5 + i)
            paint = PlaneGeometry(1, 1).rotateX(-math.pi / 2).translate(0, .01, 0).rotateX(-math.asin(p.tangent.y))
            paint.name = "road-start-checker"
            add(paint, C["ink"] if (i + row) % 2 else C["paper"], p.position.x, p.position.y + .032, p.position.z, p.yaw)
    for i in range(6):
        for side in (-1, 1):
            pu = (-8 - i * 7) / L
            local(pu, side * 3.2, .033, 2.8, .02, .12, C["paper"])
            local(pu - 1 / L, side * 3.2 - 1.4, .033, .12, .02, 2, C["paper"])
    reserved = []
    # 自動生成コース：橋脚とスタートゲート
    i = 0
    while i < count:
        for side in (-1, 1):
            u = i / count
            p = T.track_pose(u, side * (T.shoulder_half_width_at(u, side) - 1))
            if not T.is_bridge_span_at(u) or any(
                    s.position.y < p.position.y - 4 and jhypot(s.position.x - p.position.x, s.position.z - p.position.z) < 18
                    for s in T.samples):
                continue
            base = T.terrain_height_at(p.position.x, p.position.z)
            h = p.position.y - base - .65
            if h < .5:
                continue
            track_box(p.position.x, base + h / 2, p.position.z, 1, h, 1, C["concrete"], p.yaw)
            push_solid({"position": [p.position.x, base + h / 2, p.position.z], "size": [1, h, 1], "yaw": p.yaw,
                        "pitch": 0})
        i += 6
    g0 = T.track_pose(0)
    for side in (-1, 1):
        p = T.track_pose(0, side * (T.shoulder_half_width_at(0, side) + 1.2)).position
        box(p.x, p.y + 3.5, p.z, .6, 7, .6, C["ink"], g0.yaw)
    box(g0.position.x, g0.position.y + 7, g0.position.z, 23, .6, .6, C["ink"], g0.yaw)
    signs.append({"position": [g0.position.x, g0.position.y + 7, g0.position.z], "yaw": g0.yaw + math.pi,
                  "title": "START / FINISH", "subtitle": am["name"], "width": 14, "height": 1.5})
    pit_path = T.pit_lane_path()
    for feature in features:
        if feature["kind"] == "bridge":
            p = T.track_pose(feature["start"], T.shoulder_half_width_at(feature["start"], 1) - 1)
            track_box(p.position.x, p.position.y + 1.5, p.position.z, .18, 3, .18, C["ink"], p.yaw)
            solids.append({"position": [p.position.x, p.position.y + 1.5, p.position.z], "size": [.18, 3, .18],
                           "yaw": p.yaw, "pitch": 0})
            signs.append({"position": [p.position.x, p.position.y + 3, p.position.z], "yaw": p.yaw + math.pi,
                          "title": "VALLEY VIADUCT",
                          "subtitle": "%d m" % js_round((feature["end"] - feature["start"]) * L), "width": 5})
        if feature["kind"] == "tower" and feature.get("position"):
            x, _, z = feature["position"]
            base = ground(x, z)
            h = 92
            track_box(x, base + h / 2, z, 13, h, 13, C["paper"])
            y = 12
            while y < h:
                track_box(x, base + y, z, 13.4, .4, 13.4, C["ink"])
                y += 12
            track_box(x, base + h - 6, z, 17, 8, 17, C["glass"])
            track_box(x, base + h + 1, z, 18, 1, 18, C["concrete"])
            track_box(x, base + h + 9, z, .4, 16, .4, C["ink"])
            solids.extend([{"position": [x, base + h / 2, z], "size": [13, h, 13], "yaw": 0, "pitch": 0},
                           {"position": [x, base + h - 6, z], "size": [17, 8, 17], "yaw": 0, "pitch": 0},
                           {"position": [x, base + h + 1, z], "size": [18, 1, 18], "yaw": 0, "pitch": 0}])
            signs.append({"position": [x, base + h - 6, z + 8.6], "yaw": 0, "title": "SUMMIT",
                          "subtitle": "OBSERVATION TOWER", "width": 14, "height": 4})
            reserved.append({"position": [x, base, z], "size": [26, 1, 26], "yaw": 0})
            start = T.track_pose(feature["start"]).position
            delta = Vector3(x - start.x, 0, z - start.z)
            reserved.append({"position": [(x + start.x) / 2, base, (z + start.z) / 2], "size": [28, 1, delta.length()],
                             "yaw": math.atan2(delta.x, delta.z)})
        if feature["kind"] != "tunnel":
            continue
        fs, fe = feature["start"], feature["end"]
        n = min(240, max(24, math.ceil((fe - fs) * L / 5)))
        poses = [T.track_pose(fs + (fe - fs) * i / n) for i in range(n + 1)]
        w = max(max(T.shoulder_half_width_at(fs + (fe - fs) * i / n, side) for side in (-1, 1))
                for i in range(len(poses))) + 2
        section = [[-w, -1], [-w, 5.7], [-w * .8, 8.5], [w * .8, 8.5], [w, 5.7], [w, -1],
                   [w + 32, -1], [w + 20, 17], [w * .4, 48], [-w * .4, 43], [-w - 20, 19], [-w - 32, -1]]
        positions, indices = [], []
        stride = len(section)
        collider_step = max(1, math.ceil(n / 120))
        for i, p in enumerate(poses):
            floor = ground(p.position.x, p.position.z)
            ridge = .3 + .7 * math.pow(max(0, math.sin(math.pi * i / n)), .65)
            widen = 1 + 1.15 * math.sin(math.pi * i / n)
            for j, (base_offset, height) in enumerate(section):
                offset = base_offset * widen if j >= 6 else base_offset
                q = p.position.clone().addScaledVector(p.normal, offset)
                exterior = j >= 6
                top = (height * ridge + (math.sin(i / n * math.pi * 2.5 + j * .45) * ridge * 1.2 if height > 0 else 0)
                       if exterior else height)
                positions.extend((q.x, min(q.y - 1, ground(q.x, q.z) - 1 if exterior else floor - .5) if height < 0
                                  else q.y + top, q.z))
            if i < n:
                for j in range(stride):
                    a, b = i * stride + j, i * stride + (j + 1) % stride
                    indices.extend((a, b, a + stride, b, b + stride, a + stride))
            if i < n and i % collider_step == 0:
                nxt = min(n, i + collider_step)
                for side in (-1, 1):
                    a = p.position.clone().addScaledVector(p.normal, side * (w + .6)).add(Vector3(0, 2.5, 0))
                    b = poses[nxt].position.clone().addScaledVector(poses[nxt].normal, side * (w + .6)).add(Vector3(0, 2.5, 0))
                    d = b.clone().sub(a)
                    mid = a.clone().add(b).multiplyScalar(.5)
                    solids.append({"position": mid.toArray(), "size": [1.2, 5, d.length() + .1],
                                   "yaw": math.atan2(d.x, d.z), "pitch": -math.atan2(d.y, jhypot(d.x, d.z))})
                reserved.append({"position": p.position.toArray(),
                                 "size": [(w + 34) * 2, 1, p.position.distanceTo(poses[nxt].position) + 4], "yaw": p.yaw})
            if i % 4 == 0 or i == n:
                for j in range(1, 4):
                    a = p.position.clone().addScaledVector(p.normal, section[j][0]).add(Vector3(0, section[j][1] - .12, 0))
                    b = p.position.clone().addScaledVector(p.normal, section[j + 1][0]).add(
                        Vector3(0, section[j + 1][1] - .12, 0))
                    beam(a, b, .22, C["concrete"], False)
                for side in (-1, 1):
                    light = p.position.clone().addScaledVector(p.normal, side * (w - .3))
                    track_box(light.x, light.y + 4, light.z, .16, .25, 1.6, C["yellow"], p.yaw)
        for tri in triangulate_shape([Vector2(x, y) for x, y in section], []):
            indices.extend(tri[::-1])
            indices.extend(n * stride + k for k in tri)
        shell = BufferGeometry()
        shell.setAttribute("position", BufferAttribute(f32(positions), 3))
        shell.setIndex(indices)
        shell.computeVertexNormals()
        shell.name = "venue-mountain-tunnel"
        add(shell, C["concrete"], 0, 0, 0)
        for i, direction in ((0, math.pi), (n, 0)):
            p = poses[i]
            sign = p.position.clone().addScaledVector(p.tangent, -.3 if i == 0 else .3)
            for side in (-1, 1):
                q = p.position.clone().addScaledVector(p.normal, side * (w + .9))
                track_box(q.x, q.y + 3.3, q.z, 1.8, 6.6, 2, C["paper"], p.yaw)
            for j in range(1, 4):
                ext = p.position.clone().addScaledVector(p.tangent, -.7 if i == 0 else .7)
                a = ext.clone().addScaledVector(p.normal, section[j][0]).add(Vector3(0, section[j][1] + .5, 0))
                b = ext.clone().addScaledVector(p.normal, section[j + 1][0]).add(Vector3(0, section[j + 1][1] + .5, 0))
                beam(a, b, 1, C["paper"], False)
            signs.append({"position": [sign.x, sign.y + 10.5, sign.z], "yaw": p.yaw + direction, "title": "RIDGE TUNNEL",
                          "subtitle": "%d m / KEEP LEFT" % js_round((fe - fs) * L), "width": 12, "height": 1.5})
    for i in range(len(pit_path) - 1):
        u = pit_path[i].u
        if T.pit_blend_at(u) < .999 or T.pit_blend_at(pit_path[i + 1].u) < .999:
            continue
        a = T.track_pose(u, -T.road_half_width_at(u) - .45).position.add(Vector3(0, .65, 0))
        un = pit_path[i + 1].u
        b = T.track_pose(un, -T.road_half_width_at(un) - .45).position.add(Vector3(0, .65, 0))
        rail(a, b, T.track_pose(u).normal, T.track_pose(un).normal, .16, C["ink"],
             [i == 0 or T.pit_blend_at(pit_path[i - 1].u) < .999,
              i + 2 >= len(pit_path) or T.pit_blend_at(pit_path[i + 2].u) < .999])
        if i % 8 == 0:
            pitch = -math.asin(T.track_pose(pit_path[i].u).tangent.y)
            track_box(a.x, a.y, a.z, .22, 1.3, .22, C["concrete"], pit_path[i].yaw)
            push_solid({"position": [a.x, a.y, a.z], "size": [.22, 1.3, .22], "yaw": pit_path[i].yaw, "pitch": 0})
            reserved.append({"position": [a.x, a.y, a.z], "size": [.24, 1.3, .24], "yaw": pit_path[i].yaw, "pitch": pitch})
    for u, title, subtitle in ((.927, "PIT ENTRY", "LEFT / SLOW DOWN"), (.957, "60", "PIT SPEED LIMIT"),
                               (.077, "PIT EXIT", "YIELD / MERGE RIGHT")):
        p = T.track_pose(u, -T.paved_half_width_at(u, -1) - .8)
        signs.append({"position": [p.position.x, p.position.y + 2.4, p.position.z], "yaw": p.yaw + math.pi,
                      "title": title, "subtitle": subtitle, "width": 4, "height": 1.2})
        track_box(p.position.x, p.position.y + 1, p.position.z, .15, 2, .15, C["ink"], p.yaw)
    for bi in range(4):
        u = .974 + bi * .017
        offset = -T.road_half_width_at(u) - 6.2
        p = T.track_pose(u, offset)
        for side in (-1, 1):
            local(u, offset + side * 1.2, .035, .12, .018, 8, C["yellow"])
            local(u + side * 4 / L, offset, .035, 2.4, .018, .12, C["yellow"])
        local(u, offset, .04, 2.4, .018, .25, C["paper"])
        roof = p.position.clone().add(Vector3(0, 3.4, 0))
        track_box(roof.x, roof.y, roof.z, 3.4, .2, 8.5, C["blue"], p.yaw)
        solids.append({"position": roof.toArray(), "size": [3.4, .2, 8.5], "yaw": p.yaw, "pitch": 0})
        for end in (-1, 1):
            post = p.position.clone().addScaledVector(p.normal, -1.55).addScaledVector(p.tangent, end * 3.8)
            track_box(post.x, post.y + 1.65, post.z, .18, 3.3, .18, C["ink"], p.yaw)
            solids.append({"position": [post.x, post.y + 1.65, post.z], "size": [.18, 3.3, .18], "yaw": p.yaw, "pitch": 0})
        sign = T.track_pose(u, -T.paved_half_width_at(u, -1) - .8)
        signs.append({"position": [sign.position.x, p.position.y + 2.5, sign.position.z], "yaw": p.yaw + math.pi / 2,
                      "title": "BOX %d" % (bi + 1), "subtitle": "STOP / BRAKE TO HOLD", "width": 3, "height": .8})
    venue = V.build_venue(scenery, reserved + solids)
    reserved.extend(venue["reserved"])
    solids.extend(venue["solids"])
    signs.extend(venue["signs"])
    for o in generate_scenery(scenery, reserved):
        object_base = ground(o["x"], o["z"])
        cy, sy = math.cos(o["yaw"]), math.sin(o["yaw"])

        def at(x, y, z, o=o, cy=cy, sy=sy):
            return Vector3(o["x"] + x * cy + z * sy, y, o["z"] - x * sy + z * cy)

        def part(x, y, z, w, h, d, color, collide=False, o=o, object_base=object_base):
            p = at(x, y, z)
            track_box(p.x, p.y + object_base, p.z, w, h, d, color, o["yaw"])
            if collide:
                solids.append({"position": [p.x, p.y + object_base, p.z], "size": [w, h, d], "yaw": o["yaw"], "pitch": 0})

        def support(x, top, width, o=o, object_base=object_base):
            p = at(x, 0, 0)
            base = ground(p.x, p.z)
            height = object_base + top - base
            track_box(p.x, base + height / 2, p.z, width, height, width, C["ink"], o["yaw"])
            solids.append({"position": [p.x, base + height / 2, p.z], "size": [width, height, width], "yaw": o["yaw"],
                           "pitch": 0})

        k, sc = o["kind"], o["scale"]
        if gen and k == 1:
            h = 5 + sc * 4
            part(0, h / 2, 0, 7, h, 8, C["paper"])
            part(0, h + .2, 0, 8, .4, 9, C["ink"])
            for x in (-2, 0, 2):
                for y in (2, 5):
                    part(x, y, 4.05, 1.2, 1.2, .1, C["blue"])
            part(0, 1.5, -4.05, 3, 3, .1, C["rust"])
            push_solid({"position": [o["x"], h / 2, o["z"]], "size": [7, h, 8], "yaw": o["yaw"]})
        elif k == 0:
            for x, z, h in ((-2, -1, 7), (2, 1, 9), (0, 3, 5)):
                p = at(x, 0, z)
                cylinder(p.x, 1.4, p.z, .22, 2.8, C["ink"])
                add(CylinderGeometry(.3, 1.8, h * sc, 7), C["green"], p.x, h * sc / 2 + 1.6 + ground(p.x, p.z), p.z)
        elif k == 1:
            for i in range(3):
                h = (1.1 + i * .35) * sc
                x = -2.5 + i * 2.5
                part(x, .15, 0, 2, .3, 2.4, C["ink"])
                part(x, h / 2 + .3, 0, 1.8, h, 2.2, C["paper"])
                part(x, h + .3, 0, 1.85, .12, 2.25, C["rust"])
                part(x, h / 2 + .3, 0, .12, h + .08, 2.29, C["ink"])
                p = at(x, .7, 3)
                cylinder(p.x, p.y, p.z, .5, 1.4, C["blue"])
                cylinder(p.x, 1.15, p.z, .52, .1, C["ink"])
        elif k == 2:
            part(0, .12, 0, 7, .24, 6, C["concrete"])
            for x in (-1.8, 1.8):
                h = 5 * sc
                p = at(x, h / 2 + .25, 0)
                cylinder(p.x, p.y, p.z, 1.3, h, C["paper"])
                for y in (.6, h / 2, h + .25):
                    cylinder(p.x, y, p.z, 1.34, .14, C["blue"])
                part(x, h / 2, 1.4, .15, h, .2, C["ink"])
            part(0, 1, 0, 3.6, .3, .3, C["rust"])
        elif k == 3:
            h = 7 + sc * 4
            support(0, h, .45)
            part(0, h - 1.4, 0, 8.5, 2.8, .18, C["paper"], True)
            part(0, h - 2.5, -.12, 7.8, .08, .08, C["rust"])
        elif k == 4:
            h = 8 + sc * 5
            for x in (-2.5, 2.5):
                support(x, h, .3)
                part(x, h - .35, 0, 1.1, .2, .2, C["rust"])
            part(0, h - 1.1, 0, 5.8, .18, .18, C["ink"], True)
            part(0, h - 2.1, 0, 4.4, .12, .12, C["ink"], True)
            part(0, h - .1, 0, 5.8, .2, .2, C["ink"], True)
        elif k == 6:
            base = ground(o["x"], o["z"])
            s = sc
            for tp in turbine_body():
                add(tp["geometry"].scale(s, s, s), tp["color"], o["x"], base, o["z"], o["yaw"])
            turbines.append({"position": [o["x"] + math.sin(o["yaw"]) * TURBINE_ROTOR_OFFSET * s,
                                          base + TURBINE_HUB_HEIGHT * s,
                                          o["z"] + math.cos(o["yaw"]) * TURBINE_ROTOR_OFFSET * s],
                             "yaw": o["yaw"], "scale": s,
                             "phase": jmod(jmod(o["x"] * .019 + o["z"] * .013, math.pi * 2) + math.pi * 2, math.pi * 2),
                             "angularSpeed": .7 / math.sqrt(s)})
            for i in range(6):
                h = 41.7 / 6
                radius = 1.35 - .69 * (i + .5) / 6
                push_solid({"position": [o["x"], base + (.6 + (i + .5) * h) * s, o["z"]],
                            "size": [radius * 2 * s, h * s, radius * 2 * s], "yaw": o["yaw"], "pitch": 0})
            push_solid({"position": [o["x"], base + .2 * s, o["z"]], "size": [4.3 * s, .8 * s, 4.3 * s], "yaw": o["yaw"],
                        "pitch": 0})
        elif k == 7:
            h, w = 36 + sc * 22, 8 + sc * 3
            part(0, .35, 0, w + 2, .7, w + 2, C["concrete"])
            part(0, h / 2, 0, w, h, w, C["paper"])
            for y in (h * .18, h * .35, h * .52, h * .69, h * .86):
                part(0, y, -w / 2 - .08, w + .2, .16, .12, C["ink"])
                part(0, y, w / 2 + .08, w + .2, .16, .12, C["ink"])
            for y in (h * .2, h * .4, h * .6, h * .8):
                for x in (-w * .28, w * .28):
                    part(x, y, w / 2 + .1, w * .16, 1.1, .1, C["glass"])
                    part(x, y, -w / 2 - .1, w * .16, 1.1, .1, C["glass"])
            part(0, h + .7, 0, w * .7, 1.4, w * .7, C["blue"])
            part(0, h + 5, 0, .25, 8, .25, C["ink"])
            push_solid({"position": [o["x"], h / 2, o["z"]], "size": [w, h, w], "yaw": o["yaw"]})
        elif k == 8:
            bh, by, width = 7 + sc * 2, 16 + sc * 5, 22 + sc * 10
            for x in (-width * .32, width * .32):
                support(x, by, .55)
            part(0, by, 0, width, bh, .5, C["ink"], True)
            part(0, by, .31, width - 1, bh - .8, .08, C["paper"])
            sign = at(0, by, .37)
            sign.y += object_base
            signs.append({"position": sign.toArray(), "yaw": o["yaw"], "title": "INKRACER",
                          "subtitle": "MEGA CITY CIRCUIT / DRIVE LOUD", "width": width - 1, "height": bh - .8})
        elif k == 9:
            th = 16 + sc * 9
            base = at(0, 0, 0)
            cylinder(base.x, th / 2, base.z, .62, th, C["rust"])
            for y, radius, height in ((th - 1, 6.4, 10), (th + 4.5, 5.3, 9), (th + 9, 4, 8)):
                add(CylinderGeometry(0, radius * sc, height, 9), C["green"], base.x, y + ground(base.x, base.z), base.z)
            part(0, .2, 0, 2.2, .4, 2.2, C["concrete"])
            push_solid({"position": [base.x, th / 2, base.z], "size": [1.3, th, 1.3], "yaw": o["yaw"]})
        else:
            h = 2.5 + sc * 1.5
            for row in range(2):
                for x in (-2.3, 0, 2.3):
                    p = at(x, h / 2 + row * h, -.25 if row else .25)
                    track_box(p.x, p.y + object_base, p.z, 2.1, h, 4.5, C["blue"] if row else C["rust"], o["yaw"])
                    solids.append({"position": [p.x, p.y + object_base, p.z], "size": [2.1, h, 4.5], "yaw": o["yaw"],
                                   "pitch": 0})
            part(0, h * 2 + .18, 0, 7.2, .16, 5, C["ink"])
    batches = []
    for i, g in enumerate(groups.values()):
        geometry = mergeGeometries(g["parts"])
        batches.append({"name": "%s-%d" % (g["name"] or "district", i), "color": g["color"], "geometry": geometry,
                        "edges": EdgesGeometry(geometry, 35)})
    batches.extend(venue["batches"])
    return {"batches": batches, "solids": solids, "signs": signs, "turbines": turbines,
            "animations": venue["animations"]}

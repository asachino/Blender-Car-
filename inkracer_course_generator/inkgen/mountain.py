"""mountain.ts の buildMountainDistrict の移植（峠：擁壁・ガードレール・カーブミラー・森）"""
import math
from .three import Vector3, Quaternion, lcg_random, js_round, jhypot
from .geometries import BoxGeometry, CylinderGeometry, IcosahedronGeometry, EdgesGeometry, mergeGeometries
from . import track as T


def build_mountain_district(settings):
    groups = {}
    solids, signs = [], []

    def add(name, geometry, color, anchor):
        geometry.deleteAttribute("uv")
        key = "%s-%s-%d-%d" % (name, color, math.floor(anchor.x / 160), math.floor(anchor.z / 160))
        if key not in groups:
            groups[key] = {"name": name, "color": color, "parts": []}
        groups[key]["parts"].append(geometry)

    def box(name, p, size, color, yaw=0, collide=False):
        add(name, BoxGeometry(*size).rotateY(yaw).translate(p.x, p.y, p.z), color, p)
        if collide:
            solids.append({"position": p.toArray(), "size": list(size), "yaw": yaw, "pitch": 0})

    def beam(name, a, b, width, height, color, collide=False):
        delta = b.clone().sub(a)
        length = delta.length()
        mid = a.clone().add(b).multiplyScalar(.5)
        g = BoxGeometry(width, height, length)
        g.applyQuaternion(Quaternion().setFromUnitVectors(Vector3(0, 0, 1), delta.clone().normalize()))
        add(name, g.translate(mid.x, mid.y, mid.z), color, mid)
        if collide:
            solids.append({"position": mid.toArray(), "size": [width, height, length], "yaw": math.atan2(delta.x, delta.z),
                           "pitch": -math.atan2(delta.y, jhypot(delta.x, delta.z))})

    steel, ink, paper, orange = "#aaa993", "#263c50", "#f1e6cc", "#b95836"
    L = T.TRACK_LENGTH
    count = math.ceil(L / 5)
    sides = []
    for side in (-1, 1):
        poses = [T.track_pose(i / count, side * (T.shoulder_half_width_at(i / count, side) - .35)) for i in range(count)]
        uphill = []
        for i, p in enumerate(poses):
            slope = p.position.clone().addScaledVector(p.normal, side * 50)
            opposite = T.track_pose(i / count, -side * 56).position
            h = T.terrain_height_at(slope.x, slope.z)
            uphill.append(h > p.position.y + 4 and h > T.terrain_height_at(opposite.x, opposite.z) + 2)
        sides.append((side, poses, uphill))

    def strip(name, a, b, na, nb, width, height, color, caps, collide=False):
        geometry = T.section_beam_geometry(a, b, na, nb, width, height, caps)
        mid = a.clone().add(b).multiplyScalar(.5)
        add(name, geometry, color, mid)
        if collide:
            delta = b.clone().sub(a)
            solids.append({"position": mid.toArray(), "size": [width, height, delta.length()],
                           "yaw": math.atan2(delta.x, delta.z), "pitch": -math.atan2(delta.y, jhypot(delta.x, delta.z))})

    for side, poses, uphill in sides:
        for i in range(count):
            p, q = poses[i], poses[(i + 1) % count]
            caps = [uphill[(i + count - 1) % count] != uphill[i], uphill[(i + 1) % count] != uphill[i]]
            if uphill[i]:
                wa = p.position.clone().addScaledVector(p.normal, side * (3.4 / 2 + .45 / 2)).add(Vector3(0, 1, 0))
                wb = q.position.clone().addScaledVector(q.normal, side * (3.4 / 2 + .45 / 2)).add(Vector3(0, 1, 0))
                strip("mountain-retaining-wall", wa, wb, p.normal, q.normal, 3.4, 3.2, "#747c6b", caps, True)
                for h in (1.2, 1.85, 2.5):
                    a = p.position.clone().addScaledVector(p.normal, side * .17).add(Vector3(0, h, 0))
                    b = q.position.clone().addScaledVector(q.normal, side * .17).add(Vector3(0, h, 0))
                    strip("mountain-wall-masonry", a, b, p.normal, q.normal, .025, .035, ink, caps)
                if i % 2 == 0:
                    a = p.position.clone().addScaledVector(p.normal, side * .17).add(Vector3(0, .65, 0))
                    beam("mountain-wall-masonry", a, a.clone().add(Vector3(0, 1.85, 0)), .035, .035, ink)
                    if settings["density"] > 0:
                        bush = p.position.clone().addScaledVector(p.normal, side * 2).add(Vector3(0, 2.9, 0))
                        add("mountain-wall-vegetation", IcosahedronGeometry(1.6, 1).scale(1, .7, 1)
                            .translate(bush.x, bush.y, bush.z), "#597164", bush)
                strip("mountain-retaining-curb", p.position.clone().add(Vector3(0, .34, 0)),
                      q.position.clone().add(Vector3(0, .34, 0)), p.normal, q.normal, .45, .72, steel, caps, True)
                ga = p.position.clone().addScaledVector(p.normal, -side * .45).add(Vector3(0, .035, 0))
                gb = q.position.clone().addScaledVector(q.normal, -side * .45).add(Vector3(0, .035, 0))
                strip("mountain-drainage", ga, gb, p.normal, q.normal, .22, .04, ink, caps)
                if i % 2 == 0:
                    beam("mountain-curb-joints", p.position.clone().add(Vector3(0, .71, 0)),
                         p.position.clone().addScaledVector(p.normal, -side * .23).add(Vector3(0, .71, 0)), .035, .015, ink)
                continue
            a = p.position.clone().add(Vector3(0, .85, 0))
            b = q.position.clone().add(Vector3(0, .85, 0))
            strip("mountain-guardrail", a, b, p.normal, q.normal, .15, .3, steel, caps, True)
            box("mountain-rail-post", p.position.clone().add(Vector3(0, .48, 0)), [.13, .96, .13], ink, p.yaw)
            if i % 3 == 0:
                marker = p.position.clone().addScaledVector(p.normal, -side * .16).add(Vector3(0, 1.18, 0))
                box("mountain-reflector", marker, [.15, .23, .09], paper if i % 2 else orange, p.yaw)
    last_sign = -100
    for i in range(15, count - 15):
        u = i / count
        p, before, after = T.track_pose(u), T.track_pose(u - 12 / L), T.track_pose(u + 12 / L)
        turn = before.tangent.x * after.tangent.z - before.tangent.z * after.tangent.x
        if abs(turn) < .3 or i - last_sign < 17:
            continue
        side = -1 if turn < 0 else 1
        q = T.track_pose(u, side * (T.shoulder_half_width_at(u, side) + .8)).position
        box("mountain-curve-post", q.clone().add(Vector3(0, 1.2, 0)), [.12, 2.4, .12], ink, p.yaw)
        sign = q.clone().addScaledVector(p.tangent, -.08).add(Vector3(0, 2.15, 0))
        signs.append({"position": sign.toArray(), "yaw": p.yaw + math.pi, "title": "› › ›" if side < 0 else "‹ ‹ ‹",
                      "subtitle": "HAIRPIN / SLOW", "width": 2.8, "height": 1})
        mirror = T.track_pose(u - 12 / L, side * (T.shoulder_half_width_at(u - 12 / L, side) + .8))
        box("mountain-mirror-post", mirror.position.clone().add(Vector3(0, 1.5, 0)), [.09, 3, .09], orange, mirror.yaw)
        center = mirror.position.clone().add(Vector3(0, 3, 0))
        for r, depth, offset, color in ((.48, .14, 0, orange), (.41, .035, -.09, "#b6c4d0")):
            g = CylinderGeometry(r, r, depth, 16).rotateX(math.pi / 2).rotateY(mirror.yaw)
            face = center.clone().addScaledVector(mirror.tangent, offset)
            add("mountain-convex-mirror", g.translate(face.x, face.y, face.z), color, center)
        last_sign = i
    random = lcg_random(settings["seed"])
    placed = []
    target = js_round(settings["density"] * 14)
    attempt = 0
    while attempt < target * 12 and len(placed) < target:
        attempt += 1
        pose = T.track_pose(random(), (-1 if random() < .5 else 1) * (10 + random() ** 2 * 65))
        p = pose.position
        rock = random() < .08
        radius = 1.5 + random() * 2 if rock else 3 + random() * 2
        road = T.nearest_track(p.x, p.z)
        if road.distance < 7 + radius or any(jhypot(o[0].x - p.x, o[0].z - p.z) < (o[1] + radius) * .8 for o in placed):
            continue
        p.y = T.terrain_height_at(p.x, p.z)
        placed.append((p.clone(), radius))
        if rock:
            g = IcosahedronGeometry(1, 0).scale(radius, radius * .7, radius * .85).rotateY(random() * math.pi)
            add("mountain-rocks", g.translate(p.x, p.y + radius * .25, p.z), steel, p)
        else:
            h = 8 + random() * 10
            add("mountain-trunks", CylinderGeometry(.16, .3, h * .8, 6).translate(p.x, p.y + h * .3, p.z), ink, p)
            broadleaf = random() < .88
            if broadleaf:
                for crown in range(3):
                    angle = crown * math.pi * 2 / 3
                    g = IcosahedronGeometry(radius, 1).scale(1.35, .9, 1.35).rotateY(random() * math.pi)
                    add("mountain-broadleaf-canopy", g.translate(p.x + math.cos(angle) * radius * .35,
                                                                 p.y + h * (.6 + crown * .1),
                                                                 p.z + math.sin(angle) * radius * .35),
                        "#758779" if crown % 2 else "#597164", p)
            else:
                for layer in (0, 1, 2):
                    g = CylinderGeometry(0, radius * (1 - layer * .22), h * .52, 7)
                    add("mountain-canopy", g.translate(p.x, p.y + h * (.48 + layer * .18), p.z),
                        "#758779" if layer % 2 else "#597164", p)
            under = IcosahedronGeometry(radius * .65, 1).scale(1.2, .55, 1.2)
            add("mountain-undergrowth", under.translate(p.x, p.y + .45, p.z), "#65765a", p)
    for u in (0, .55):
        pose = T.track_pose(u, -8.4)
        p = pose.position
        box("mountain-route-post", p.clone().add(Vector3(0, 1.55, 0)), [.16, 3.1, .16], ink, pose.yaw)
        signs.append({"position": [p.x, p.y + 3.1, p.z], "yaw": pose.yaw + math.pi,
                      "title": "TOUGE" if u == 0 else "MOUNTAIN PASS",
                      "subtitle": "%d m / KEEP LEFT" % js_round(p.y), "width": 4.2, "height": 1.6})
    batches = []
    for i, g in enumerate(groups.values()):
        geometry = mergeGeometries(g["parts"])
        batches.append({"name": "%s-%d" % (g["name"], i), "color": g["color"], "geometry": geometry,
                        "edges": EdgesGeometry(geometry, 38)})
    return {"batches": batches, "solids": solids, "signs": signs, "turbines": [], "animations": []}

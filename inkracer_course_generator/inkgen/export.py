"""mapExport.ts の buildEnvironment の移植：ゲームの「Blender 書き出し」と同じ内容のシーンデータを作る"""
import base64
import math
from .three import Vector3, BufferAttribute, f32
from .geometries import BoxGeometry, PlaneGeometry, EdgesGeometry, mergeGeometries
from . import track as T
from . import city as CITY
from . import district as D

DEFAULT_NIGHT = {"enabled": False, "brightness": 1, "warmth": .65, "bloom": .35, "weather": "dry", "traffic": 8,
                 "highBeam": False}
INK_PRESETS = [
    ("青インク", {"paper": "#f4f1df", "ink": "#252e76", "accent": "#b24f42", "pattern": "mixed"}),
    ("鉛筆", {"paper": "#eeeae2", "ink": "#333438", "accent": "#977755", "pattern": "hatch"}),
    ("セピア", {"paper": "#f1dfbb", "ink": "#684632", "accent": "#a54430", "pattern": "mixed"}),
    ("設計図", {"paper": "#172d50", "ink": "#d8e5ed", "accent": "#e9b877", "pattern": "halftone"}),
]
DEFAULT_INK = dict(INK_PRESETS[0][1])
DEFAULT_NIGHT_INK = {"paper": "#101b2b", "ink": "#8aa8c8", "accent": "#e8b577", "pattern": "mixed"}
ROAD_TEXTURE_SIZE = 256


def parse_night(value):
    v = value if isinstance(value, dict) else {}
    n = dict(DEFAULT_NIGHT)
    for key in ("enabled", "highBeam"):
        if isinstance(v.get(key), bool):
            n[key] = v[key]
    for key, mn, mx in (("brightness", .5, 2), ("warmth", 0, 1), ("bloom", 0, 1), ("traffic", 0, 16)):
        x = v.get(key)
        if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x):
            n[key] = max(mn, min(mx, x))
    n["traffic"] = int(math.floor(n["traffic"] + .5))
    if v.get("weather") in ("wet", "rain"):
        n["weather"] = v["weather"]
    return n


def road_appearance(name, color, night):
    wet = night["enabled"] and night["weather"] != "dry"
    return {"color": "#343e49" if night["enabled"] and name == "road-surface" else color,
            "roughness": .18 if wet and name == "road-surface" else 1, "metalness": .2 if wet else 0}


def road_texture_pixels():
    px = bytearray([187, 192, 186, 255] * (ROAD_TEXTURE_SIZE * ROAD_TEXTURE_SIZE))
    seed = 73
    for _ in range(13000):
        seed = (seed * 1664525 + 1013904223) & 0xFFFFFFFF
        offset = (((seed >> 8) % 256) * 256 + seed % 256) * 4
        light = 95 + (seed >> 16) % 100
        for ch in range(3):
            v = px[offset + ch] * .7 + light * .3
            px[offset + ch] = max(0, min(255, round(v)))  # Uint8ClampedArray：偶数丸め
    return bytes(px)


def export_geometry(name, geometry, color, flat_shading=False):
    pos = geometry.attributes["position"].array
    vertices = list(pos)
    if any(not math.isfinite(v) for v in vertices):
        raise ValueError("Cannot export non-finite coordinates: " + name)
    src = list(geometry.index.array) if geometry.index is not None else list(range(len(vertices) // 3))
    indices = []
    for i in range(0, len(src), 3):
        a, b, c = src[i] * 3, src[i + 1] * 3, src[i + 2] * 3
        bx, by, bz = vertices[b] - vertices[a], vertices[b + 1] - vertices[a + 1], vertices[b + 2] - vertices[a + 2]
        cx, cy, cz = vertices[c] - vertices[a], vertices[c + 1] - vertices[a + 1], vertices[c + 2] - vertices[a + 2]
        x = by * cz - bz * cy
        y = bz * cx - bx * cz
        z = bx * cy - by * cx
        if x * x + y * y + z * z > 1e-16:
            indices.extend(src[i:i + 3])
    out = {"name": name, "color": color, "vertices": vertices, "indices": indices}
    nor = geometry.attributes.get("normal")
    if not flat_shading and nor is not None:
        out["normals"] = list(nor.array)
    uv = geometry.attributes.get("uv")
    if uv is not None:
        out["uv"] = list(uv.array)
    return out


def _key(v):
    return repr(v + 0.0)


def unique_edges(geometry, seen):
    src = geometry.attributes["position"].array
    out = []
    for i in range(0, len(src), 6):
        a = ",".join(_key(v) for v in src[i:i + 3])
        b = ",".join(_key(v) for v in src[i + 3:i + 6])
        if a == b:
            continue
        key = "|".join(sorted((a, b)))
        if key in seen:
            continue
        seen.add(key)
        out.extend(src[i:i + 6])
    return out


def build_environment(m, scenery=None, ink_style=None, progress=None):
    """m は maps.generate_map の結果。戻り値はゲームの environmentJson と同じ構造の dict"""
    scenery = dict(D.DEFAULT_SCENERY if scenery is None else scenery)
    say = progress or (lambda *_: None)
    T.activate_map(m)
    say("地形")
    terrain = T.terrain_mesh()
    say("道路")
    lane_lines = [("road-lane-%d" % (i + 1), T.lane_ribbon(i, .028), "#f1e6cc") for i in range(3)]
    pv = T.paved_half_width_at
    rh = T.road_half_width_at
    sh = T.shoulder_half_width_at
    road = [
        ("road-shoulder-left", T.ribbon(lambda u: -pv(u, -1) - 1.5, lambda u: -pv(u, -1), 0), "#aaa993"),
        ("road-shoulder-right", T.ribbon(lambda u: rh(u), lambda u: rh(u) + 1.5, 0), "#aaa993"),
        ("road-bridge-shoulder-left", T.bridge_shoulder_ribbon(-1, .02), "#aaa993"),
        ("road-bridge-shoulder-right", T.bridge_shoulder_ribbon(1, .02), "#aaa993"),
        ("road-runoff-left", T.ribbon(lambda u: -sh(u, -1), lambda u: -pv(u, -1) - 1.5, .02,
                                      lambda u: not T.is_bridge_span_at(u)), "#c9bc9c"),
        ("road-runoff-right", T.ribbon(lambda u: rh(u) + 1.5, lambda u: sh(u, 1), .02,
                                       lambda u: not T.is_bridge_span_at(u)), "#c9bc9c"),
        ("pit-lane", T.pit_lane_ribbon(), "#53616a"),
        ("road-surface", T.road_surface_geometry(), "#53616a"),
    ]
    road += [(s["name"], s["geometry"], s["color"]) for s in T.median_strips()]
    road += [
        ("road-edge-left", T.ribbon(lambda u: -pv(u, -1) - .22, lambda u: -pv(u, -1) - .05, .025), "#f1e6cc"),
        ("road-edge-right", T.ribbon(lambda u: rh(u) + .05, lambda u: rh(u) + .22, .025), "#f1e6cc"),
    ]
    road += lane_lines
    if m.get("generated"):
        road.append(("road-underside", T.road_underside_geometry(), "#aaa993"))
    road.append(("road-retaining-walls", T.elevation_skirt(lambda u: -sh(u, -1), lambda u: sh(u, 1)), "#aaa993"))
    base = [("district-foundation", PlaneGeometry(3200, 3200).rotateX(-math.pi / 2).translate(50, terrain["floorY"], -30),
             "#c9bc9c")]
    say("建物・景観")
    scene = D.build_district(scenery)
    night = parse_night(m["night"] if m.get("night") is not None else dict(DEFAULT_NIGHT, enabled=CITY.is_city()))
    night_meshes = []
    if night["enabled"]:
        for i, s in enumerate(CITY.city_signals()):
            for k, part in enumerate(CITY.signal_meshes(s)):
                e = export_geometry("night-signal-%d-%d" % (i, k), part["geometry"], part["color"])
                if part["bulb"] >= 0:
                    e["signal"] = {"bulb": part["bulb"], "offset": s["offset"], "axis": s["axis"]}
                night_meshes.append(e)
        if not CITY.is_city():
            for bulb in (False, True):
                parts = [BoxGeometry(.6 if bulb else .16, .12 if bulb else 8, 1.6 if bulb else .16)
                         .translate(l["position"][0], l["position"][1] - (0 if bulb else 4), l["position"][2])
                         for l in CITY.night_lamps()]
                g = mergeGeometries(parts)
                night_meshes.append(export_geometry("city-glow-lamps" if bulb else "night-lamp-posts", g,
                                                    "#ffdab0" if bulb else "#596777"))
    say("輪郭線")
    terrain_edges = EdgesGeometry(terrain["geometry"], 14)
    rotor = [dict(p, edges=EdgesGeometry(p["geometry"], 38)) for p in D.turbine_rotor()]
    static_edges, rotor_edges = set(), set()
    meshes = list(night_meshes)
    for name, g, color in road:
        e = export_geometry(name, g, color)
        if name in ("road-surface", "pit-lane"):
            e["texture"] = "road"
        if name == "road-retaining-walls":
            e["roughness"] = 1
        else:
            e.update(road_appearance(name, color, night))
        meshes.append(e)
    for name, g, color in base:
        e = export_geometry(name, g, color)
        e["roughness"] = 1
        meshes.append(e)
    for b in scene["batches"]:
        e = export_geometry(b["name"], b["geometry"], b["color"])
        if not (night["enabled"] and b["name"].startswith("city-glow")):
            e["edges"] = unique_edges(b["edges"], static_edges)
        meshes.append(e)
    terrain_export = export_geometry("terrain", terrain["geometry"], "#c9bc9c", True)
    terrain_export["roughness"] = 1
    terrain_export["edges"] = unique_edges(terrain_edges, set())
    terrain_export["outlineOpacity"] = .18
    turbine_rotor = []
    for p in rotor:
        e = export_geometry(p["name"], p["geometry"], p["color"])
        e["roughness"] = .82
        e["edges"] = unique_edges(p["edges"], rotor_edges)
        turbine_rotor.append(e)
    animations = []
    for a in scene["animations"]:
        edges = set()
        motion = {k: v for k, v in a.items() if k != "batches"}
        motion["meshes"] = []
        for b in a["batches"]:
            e = export_geometry(b["name"], b["geometry"], b["color"])
            e["edges"] = unique_edges(b["edges"], edges)
            motion["meshes"].append(e)
        animations.append(motion)
    if ink_style is None:
        ink_style = dict(DEFAULT_NIGHT_INK if night["enabled"] else DEFAULT_INK)
    return {
        "inkStyle": ink_style,
        "night": night, "lamps": CITY.night_lamps(), "signals": CITY.city_signals(),
        "format": "ink-racer-environment-v2",
        "textures": {"road": {"width": ROAD_TEXTURE_SIZE, "height": ROAD_TEXTURE_SIZE,
                              "rgba": base64.b64encode(road_texture_pixels()).decode("ascii")}},
        "units": "meters",
        "id": m["id"], "name": m["name"], "generated": bool(m.get("generated")),
        "parameters": m.get("parameters"), "features": m.get("features"),
        "scenery": scenery,
        "points": [{"x": x, "y": y, "z": z} for x, y, z in m["points"]],
        "start": list(m["points"][0]),
        "terrain": terrain_export,
        "meshes": meshes,
        "signs": [dict(s) for s in scene["signs"]],
        "turbines": scene["turbines"],
        "turbineRotor": turbine_rotor,
        "animations": animations,
        "solids": scene["solids"],
        "bounds": T.track_bounds(),
    }

"""R32 のデモシーンをまとめて作る
blender -b <R32のコピー.blend> --python demo_scenes.py -- <addon.py> <シーン名> <保存先.blend>
"""
import bpy, bmesh, sys, os, math, json
from mathutils import Vector

args = sys.argv[sys.argv.index("--") + 1:]
ADDON, SCENE, SAVE = args[0], args[1], args[2]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ns = {"__name__": "__main__"}
exec(compile(open(ADDON, encoding="utf-8").read(), ADDON, "exec"), ns)
import r32_scene as RS
import cars3 as C3
import cars5 as C5

# 5車種のファイル（シーン「CPB_READY_5車種」）なら新しい車、そうでなければ R32 のファイル
MODE5 = C5.SCENE in bpy.data.scenes
if MODE5:
    sc = C5.scene()
else:
    C3.link_into("R32")              # テスタロッサと S2000 も R32 のシーンへ（他のシーンを消す前に）
    sc = RS.scene()
sc.render.fps = 24
sc.render.fps_base = 1.0
sc.render.resolution_x, sc.render.resolution_y = 1280, 720
sc.render.film_transparent = False
if hasattr(sc.eevee, "taa_render_samples"):
    sc.eevee.taa_render_samples = 12
if hasattr(sc.eevee, "use_gtao"):
    sc.eevee.use_gtao = True
if MODE5:
    CARS = C5.setup(sc)              # {"R32": (BODY, ホイール4本), "S2000", "F40", "COUNTACH", "TESTA"}
    body, wheels = CARS["R32"]
    CUR = "R32"
    for i_, k_ in enumerate(k_ for k_ in CARS if k_ != "R32"):
        C5.park(CARS[k_], i_)
    C5.place(CARS["R32"], (0, 0, 0))
    s = sc.cpb
    s.body = body
    s.wheel_fl, s.wheel_fr, s.wheel_rl, s.wheel_rr = wheels
    s.forward_axis = "POS_Y"
    s.model_scale = 1.0
    K = 1.0
else:
    CARS = C3.setup(sc)              # {"R32": (ボディ, ホイール4本), "TESTA": ..., "S2000": ...}
    body, wheels = CARS["R32"]
    CUR = "R32"
    for k_ in ("TESTA", "S2000"):
        C3.park(CARS[k_][0])
    s = RS.assign(sc)
    bpy.ops.cpb.detect_scale()
    K = s.model_scale


# ======================================================================
# 共通の部品
# ======================================================================

def mat(name, color, rough=0.8, emit=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bs = next(n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    bs.inputs['Base Color'].default_value = color
    bs.inputs['Roughness'].default_value = rough
    if 'Specular IOR Level' in bs.inputs:
        bs.inputs['Specular IOR Level'].default_value = 0.25
    if emit > 0:
        bs.inputs['Emission Color'].default_value = color
        bs.inputs['Emission Strength'].default_value = emit
    m.diffuse_color = color
    return m


MATS = {}


def M(name):
    table = {
        "芝": ((0.16, 0.34, 0.09, 1), 0.95), "アスファルト": ((0.07, 0.07, 0.075, 1), 0.65),
        "濡れた路面": ((0.035, 0.035, 0.04, 1), 0.15), "砂利": ((0.62, 0.53, 0.38, 1), 1.0),
        "土": ((0.45, 0.33, 0.2, 1), 1.0), "雪": ((0.92, 0.94, 0.97, 1), 0.6), "氷": ((0.75, 0.85, 0.95, 1), 0.05),
        "赤": ((0.7, 0.04, 0.03, 1), 0.6), "白": ((0.85, 0.85, 0.85, 1), 0.6), "コンクリート": ((0.55, 0.55, 0.52, 1), 0.9),
        "ガードレール": ((0.8, 0.8, 0.82, 1), 0.35), "水": ((0.05, 0.08, 0.12, 1), 0.02), "段ボール": ((0.6, 0.43, 0.25, 1), 0.9),
        "パイロン": ((1.0, 0.3, 0.02, 1), 0.5), "ビル": ((0.5, 0.52, 0.56, 1), 0.8), "黄線": ((0.9, 0.75, 0.1, 1), 0.6),
        "岩": ((0.38, 0.36, 0.33, 1), 0.95),
    }
    if name not in MATS:
        c, r = table[name]
        MATS[name] = mat(name, c, r)
    return MATS[name]


def link(o, coll=None):
    (coll or sc.collection).objects.link(o)
    return o


def mesh_obj(name, verts, faces, material, coll=None, scale=True):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(c * K for c in v) for v in verts] if scale else verts, [], faces)
    me.update()
    me.materials.append(material)
    return link(bpy.data.objects.new(name, me), coll)


def line(p0, p1, step=2.0):
    n = max(1, int(math.dist(p0, p1) / step))
    return [(p0[0] + (p1[0] - p0[0]) * i / n, p0[1] + (p1[1] - p0[1]) * i / n) for i in range(n + 1)]


def arc(cx, cy, r, a0, a1, step=2.0):
    """中心(cx,cy) 半径 r、角度 a0→a1（度、x軸から反時計回り）"""
    n = max(2, int(abs(math.radians(a1 - a0)) * r / step))
    return [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
             cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n + 1)]


def join(*parts):
    out = []
    for p_ in parts:
        out += p_[1:] if out else p_
    return out


def ground(fn=None, size=400, center=(0, 0), subdiv=200, material="芝", grip=None):
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=subdiv, y_subdivisions=subdiv, size=size * K,
                                    location=(center[0] * K, center[1] * K, 0))
    g = bpy.context.object
    g.name = "地面"
    for c in list(g.users_collection):
        c.objects.unlink(g)
    sc.collection.objects.link(g)
    if fn is not None:
        for v in g.data.vertices:
            x, y = v.co.x / K + center[0], v.co.y / K + center[1]
            v.co.z = fn(x, y) * K
    g.data.materials.append(M(material))
    for p_ in g.data.polygons:
        p_.use_smooth = True
    if grip is not None:
        vg = g.vertex_groups.new(name="滑りやすさ")
        ids = [v.index for v in g.data.vertices if grip((g.matrix_world @ v.co).x / K, (g.matrix_world @ v.co).y / K)]
        if ids:
            vg.add(ids, 1.0, 'REPLACE')
    return g


def ribbon(pts, w0, w1, z=0.02, fn=None, material="アスファルト", name="道"):
    verts, faces = [], []
    for i, (x, y) in enumerate(pts):
        a, b = pts[max(i - 1, 0)], pts[min(i + 1, len(pts) - 1)]
        tx, ty = b[0] - a[0], b[1] - a[1]
        tl = math.hypot(tx, ty) or 1.0
        rx, ry = ty / tl, -tx / tl
        for w in (w0, w1):
            px, py = x + rx * w, y + ry * w
            verts.append((px, py, (fn(px, py) if fn else 0.0) + z))
        if i:
            j = 2 * i
            faces.append((j - 2, j - 1, j + 1, j))
    return mesh_obj(name, verts, faces, M(material))


def kerbs(pts, w0, w1, every=3, fn=None, z=0.04):
    for i in range(0, len(pts) - every, every):
        ribbon(pts[i:i + every + 1], w0, w1, z, fn, "赤" if (i // every) % 2 == 0 else "白", "縁石")


def wall(pts, offset, thick=0.5, height=1.0, fn=None, material="コンクリート", coll=None, name="壁"):
    """中心線 pts から右へ offset の位置に壁（法線は自動）"""
    bm = bmesh.new()
    rings = []
    for i, (x, y) in enumerate(pts):
        a, b = pts[max(i - 1, 0)], pts[min(i + 1, len(pts) - 1)]
        tx, ty = b[0] - a[0], b[1] - a[1]
        tl = math.hypot(tx, ty) or 1.0
        rx, ry = ty / tl, -tx / tl
        q = []
        for w in (offset, offset + math.copysign(thick, offset)):
            px, py = x + rx * w, y + ry * w
            z0 = fn(px, py) if fn else 0.0
            for z in (z0 - 0.3, z0 + height):
                q.append(bm.verts.new((px * K, py * K, z * K)))
        rings.append(q)
    for i in range(len(rings) - 1):
        a_, b_ = rings[i], rings[i + 1]
        for (p0, p1) in ((0, 1), (1, 3), (3, 2), (2, 0)):
            bm.faces.new((a_[p0], b_[p0], b_[p1], a_[p1]))
    bm.faces.new((rings[0][0], rings[0][1], rings[0][3], rings[0][2]))
    bm.faces.new((rings[-1][0], rings[-1][2], rings[-1][3], rings[-1][1]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(M(material))
    if coll is None:
        coll = bpy.data.collections.get("壁") or bpy.data.collections.new("壁")
        if coll.name not in sc.collection.children:
            sc.collection.children.link(coll)
    return link(bpy.data.objects.new(name, me), coll)


def course(pts, name="走行ライン", fn=None):
    cd = bpy.data.curves.new(name, 'CURVE')
    cd.dimensions = '3D'
    sp = cd.splines.new('POLY')
    sp.points.add(len(pts) - 1)
    for p_, (x, y) in zip(sp.points, pts):
        p_.co = (x * K, y * K, (fn(x, y) if fn else 0.0) * K, 1.0)
    o = link(bpy.data.objects.new(name, cd))
    o.hide_render = True
    return o


def barrier(pts, side, rows=3, stack=3):
    o = course(pts, "バリヤの線")
    bpy.context.view_layer.objects.active = o
    s.gen_side, s.gen_rows, s.gen_stack, s.gen_colors = side, rows, stack, True
    with bpy.context.temp_override(active_object=o, object=o):
        bpy.ops.cpb.make_barrier()
    return bpy.data.collections.get("CPB_タイヤバリヤ")


def props_coll(name, objs):
    col = bpy.data.collections.new(name)
    sc.collection.children.link(col)
    for o in objs:
        for c in list(o.users_collection):
            c.objects.unlink(o)
        col.objects.link(o)
    return col


def box_obj(name, center, size, material, rot=0.0):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co = Vector((v.co.x * size[0], v.co.y * size[1], v.co.z * size[2])) * K
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(material)
    o = link(bpy.data.objects.new(name, me))
    o.location = Vector(center) * K
    o.rotation_euler = (0, 0, rot)
    return o


def cone_mesh():
    me = bpy.data.meshes.get("パイロン")
    if me:
        return me
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=16, radius1=0.17 * K, radius2=0.03 * K, depth=0.7 * K)
    bmesh.ops.translate(bm, vec=(0, 0, 0.35 * K), verts=bm.verts)
    base = bmesh.ops.create_cube(bm, size=1.0)
    for v in base["verts"]:
        v.co = Vector((v.co.x * 0.38 * K, v.co.y * 0.38 * K, v.co.z * 0.04 * K + 0.02 * K))
    me = bpy.data.meshes.new("パイロン")
    bm.to_mesh(me)
    bm.free()
    me.materials.append(M("パイロン"))
    return me


TINTED = {}
CAR_NAME = dict(C5.NAME) if MODE5 else {"R32": "R32", "TESTA": "テスタロッサ", "S2000": "S2000"}


def pick(key):
    """主役の車を選ぶ（R32 / TESTA / S2000）。使わない車は遠くへ置いて、レンダーにも出さない"""
    global body, wheels, CUR
    if MODE5:
        for i_, (k_, car_) in enumerate(CARS.items()):
            if k_ == key:
                C5.place(car_, (0, 0, 0))
                for o in C5.tree(car_):
                    o.hide_render = False
            else:
                C5.park(car_, i_)
        body, wheels = CARS[key]
        CUR = key
        return
    for k_, (b_, w_) in CARS.items():
        if k_ == key:
            b_.location = (0, 0, 0)
            for o in C3.tree(b_):
                o.hide_render = False
        else:
            C3.park(b_)
    body, wheels = CARS[key]
    CUR = key


def dup_car(offset, tint=None, model=None):
    """車をまるごと複製（model=None なら今の主役。tint を与えるとボディの色を変える）"""
    sb, sw = CARS[model] if model else (body, wheels)
    mp = {}
    srcs = [sb] + list(sb.children_recursive)
    srcs += [w for w in sw if w not in srcs]          # 5車種のファイルではホイールはボディの子ではない
    for o in srcs:
        c = o.copy()
        c.hide_render = False
        if tint is not None and o.type == 'MESH' and "shadow" not in o.name:
            c.data = o.data.copy()
            for i, m_ in enumerate(c.data.materials):
                if m_ is None:
                    continue
                key_ = (m_.name, tuple(tint))
                if key_ in TINTED:
                    c.data.materials[i] = TINTED[key_]
                    continue
                m2 = m_.copy()
                TINTED[key_] = m2
                if m2.use_nodes:
                    for nd in m2.node_tree.nodes:
                        if nd.type == 'VALTORGB':                          # トゥーンのカラーランプの塗装色
                            for el in nd.color_ramp.elements:
                                col_ = el.color
                                if 0.06 < max(col_[0], col_[1], col_[2]) and min(col_[0], col_[1], col_[2]) < 0.85:
                                    v_ = max(col_[0], col_[1], col_[2])
                                    el.color = (tint[0] * v_, tint[1] * v_, tint[2] * v_, 1.0)
                if m2.use_nodes:
                    for nd in m2.node_tree.nodes:
                        for inp in nd.inputs:
                            if inp.type == 'RGBA' and not inp.is_linked:
                                col_ = inp.default_value
                                if col_[2] > 0.3 and col_[2] > col_[0] + 0.15:      # 青い所を差し替え
                                    inp.default_value = tint
                        if nd.type == 'RGB':
                            col_ = nd.outputs[0].default_value
                            if col_[2] > 0.3 and col_[2] > col_[0] + 0.15:
                                nd.outputs[0].default_value = tint
                c.data.materials[i] = m2
        sc.collection.objects.link(c)
        mp[o] = c
    for o, c in mp.items():
        if o.parent in mp:
            c.parent = mp[o.parent]
    b2 = mp[sb]
    if MODE5:
        C5.place((b2, [mp[w] for w in sw]), Vector(offset) * K)
        return b2, [mp[w] for w in sw]
    b2.location = Vector(offset) * K
    return b2, [mp[w] for w in sw]


def add_car(b2, w2, path, **kw):
    it = s.cars.add()
    it.body = b2
    it.wheel_fl, it.wheel_fr, it.wheel_rl, it.wheel_rr = w2
    it.path = path
    for k_, v in kw.items():
        setattr(it, k_, v)
    return it


def cam(name, lens):
    cd = bpy.data.cameras.new(name)
    cd.lens = lens
    cd.clip_end = 800 * K
    cd.clip_start = 0.6 * K                # 近すぎると遠くの地面と路面の帯の前後がちらつく
    return link(bpy.data.objects.new(name, cd))


def chase_cam(name, target, f0, f1, dist=11, height=3.2, side=2.0, lens=32, smooth=0.06, look=3.0):
    c = cam(name, lens)
    sp_ = None
    fw0 = None
    for f in range(f0, f1 + 1):
        sc.frame_set(f)
        Mx = target.matrix_world
        p_ = Mx.translation.copy()
        fw = Mx.to_3x3() @ Vector((0, 1, 0))
        fw.z = 0
        fw.normalize()
        sp_ = p_ if sp_ is None else sp_.lerp(p_, 0.3)
        fw0 = fw if fw0 is None else fw0.lerp(fw, smooth).normalized()
        c.location = sp_ - fw0 * dist * K + Vector((0, 0, height * K)) + fw0.cross(Vector((0, 0, 1))) * side * K
        c.rotation_euler = (sp_ + fw0 * look * K + Vector((0, 0, 0.6 * K)) - c.location).to_track_quat('-Z', 'Y').to_euler()
        c.keyframe_insert("location", frame=f)
        c.keyframe_insert("rotation_euler", frame=f)
    return c


TERRAIN = None                       # 起伏のあるコースでは (x, y) -> 地面の高さ（カメラの高さに足す）


def fixed_cam(name, pos, target, f0, f1, lens=50, smooth=0.3, aim=None):
    """固定位置から target を追う（aim を与えると、その点を見続ける）"""
    c = cam(name, lens)
    if TERRAIN is not None:
        pos = (pos[0], pos[1], pos[2] + TERRAIN(pos[0], pos[1]))
        if aim is not None:
            aim = (aim[0], aim[1], aim[2] + TERRAIN(aim[0], aim[1]))
    c.location = Vector(pos) * K
    sp_ = None
    for f in range(f0, f1 + 1):
        sc.frame_set(f)
        p_ = Vector(aim) * K if aim is not None else target.matrix_world.translation.copy()
        sp_ = p_ if sp_ is None else sp_.lerp(p_, smooth)
        c.rotation_euler = (sp_ + Vector((0, 0, 0.5 * K)) - c.location).to_track_quat('-Z', 'Y').to_euler()
        c.keyframe_insert("rotation_euler", frame=f)
    return c


def finish(title, sub, shots, replay=None, frame_end=None, light=None, label=None):
    """shots: [(カメラ, 開始, 終了)]  replay: (カメラ, 開始, 終了, 速度)  light: 照明を変える関数  label: スローの帯の文字"""
    RS.world_light(sc)
    if light is not None:
        light()
    if frame_end:
        sc.frame_end = frame_end
    for mk in list(sc.timeline_markers):
        sc.timeline_markers.remove(mk)
    for c, f0, f1 in shots:
        mk = sc.timeline_markers.new("CAM_" + c.name, frame=f0)
        mk.camera = c
    sc.camera = shots[0][0]
    sc["demo"] = json.dumps({"title": title, "sub": sub,
                             "shots": [(c.name, f0, f1) for c, f0, f1 in shots],
                             "replay": [replay[0].name, replay[1], replay[2], replay[3]] if replay else None,
                             "label": label},
                            ensure_ascii=False)
    sc.frame_set(sc.frame_start)
    bpy.ops.wm.save_as_mainfile(filepath=SAVE, compress=True)
    print("SAVED", SAVE)


def bake():
    r = bpy.ops.cpb.bake()
    print("BAKE", SCENE, r, s.last_report.replace("\n", " | "))
    return s.last_report


def report_frame(prefix):
    for ln in s.last_report.split("\n"):
        if ln.startswith(prefix):
            d = ''.join(ch for ch in ln if ch.isdigit())
            if d:
                return int(d)
    return None


def car_setup(path, g, preset="SPORTS", **kw):
    if MODE5:
        s.path, s.ground = path, g
        s.forward_axis = "POS_Y"
    else:
        RS.assign(sc, path, g)
    s.body = body
    s.wheel_fl, s.wheel_fr, s.wheel_rl, s.wheel_rr = wheels
    s.model_scale = K
    s.preset = preset
    for a_, v_ in (C5.PHYS if MODE5 else C3.PHYS)[CUR].items():
        setattr(s, a_, v_)
    s.show_trajectory = False
    s.stop_at_end = False
    for k_, v in kw.items():
        setattr(s, k_, v)


def frame_near(target, xy, f0, f1):
    best = None
    for f in range(f0, f1 + 1):
        sc.frame_set(f)
        p_ = target.matrix_world.translation
        d = math.hypot(p_.x / K - xy[0], p_.y / K - xy[1])
        if best is None or d < best[0]:
            best = (d, f)
    return best[1]


# ======================================================================
# シーン
# ======================================================================

def scene_chicane_roll():
    """シケインで高い縁石（ソーセージ縁石）に乗り上げて横転"""
    pick("R32")
    sc.frame_start, sc.frame_end = 1, 240
    kx, ky = 3.2, 60.0                                   # ソーセージ縁石の位置（シケインの切り返し）

    def gfn(x, y):
        d = math.hypot((x - kx) / 0.35, (y - ky) / 3.0)
        return 0.32 * max(0.0, 1.0 - d * d)
    pts = join(line((0, -80), (0, 30)), arc(10, 30, 10, 180, 90), arc(10, 50, 10, 270, 360),
               line((20, 50), (20, 70)), arc(10, 70, 10, 0, 90), arc(10, 90, 10, 270, 180), line((0, 90), (0, 240)))
    g = ground(gfn, 360, (10, 40))
    ribbon(pts, -6, 6, 0.02)
    kerbs(pts[60:150], -7, -6, 3)
    kerbs(pts[60:150], 6, 7, 3)
    bm = bpy.data.meshes.new("ソーセージ縁石")
    o = bpy.data.objects.new("ソーセージ縁石", bm)
    link(o)
    bmo = bmesh.new()
    bmesh.ops.create_cone(bmo, cap_ends=True, segments=12, radius1=0.25 * K, radius2=0.25 * K, depth=6.0 * K)
    bmo.to_mesh(bm)
    bmo.free()
    bm.materials.append(M("黄線"))
    o.location = (kx * K, ky * K, 0.05 * K)
    o.rotation_euler = (math.radians(90), 0, 0)
    path = course(pts)
    car_setup(path, g, start_speed=150, top_speed=170, speed_scale=1.25)
    s.use_skid = s.use_smoke = s.use_dents = True
    s.smoke_color = (0.75, 0.72, 0.68)
    s.use_sparks = True
    s.use_parts = True
    s.parts_collection = make_parts()
    s.parts_strength = 20.0
    bake()
    hitf = frame_near(body, (kx, ky), 1, 240)
    s.rollover = True
    s.rollover_frame = hitf
    s.rollover_rate = 380
    s.rollover_lift = 4.0
    s.rollover_slide = 0.55
    s.dent_strength = 2.5
    bake()
    dress_generic(pts, 6.0, gfn, car_tracks([body], 1, 240), (kx, ky), 240, (10, 40), 360, seed=1,
                  avoid=[(kx, ky, 5), (kx + 22, ky + 30, 5), (kx - 7, ky + 9, 4)])
    a = chase_cam("カメラA_追いかけ", body, 1, 240)
    b = fixed_cam("カメラB_シケイン", (kx + 22, ky + 30, 4), body, 1, 240, lens=55)
    c = fixed_cam("カメラC_リプレイ", (kx - 7, ky + 9, 1.0), body, 1, 240, lens=28, smooth=0.5)
    cut = max(hitf - 30, 20)
    finish("シケインで縁石に乗り上げて横転", "R32 ／ 高い縁石で跳ね上げられ、横転して転がる",
           [(a, 1, cut - 1), (b, cut, 240)], (c, hitf - 6, hitf + 40, 0.4))


def scene_spin_barrier():
    """コーナーの立ち上がりでスピン、後ろ向きにタイヤバリヤへ"""
    pick("TESTA")
    sc.frame_start, sc.frame_end = 1, 200
    pts = join(line((0, -100), (0, 0)), arc(40, 0, 40, 180, 90), line((40, 40), (160, 40)))
    g = ground(None, 360, (50, 0))
    ribbon(pts, -6, 6)
    kerbs(pts[50:100], -7, -6, 3)
    kerbs(pts[50:100], 6, 7, 3)
    bpts = line((30, 48.5), (130, 48.5), 1.0)             # 立ち上がりの外側（左側）、路肩から1mほど
    barrier(bpts, "RIGHT", 3, 3)
    wall(line((25, 51.2), (135, 51.2), 2.0), 0.0, 0.6, 1.2)
    path = course(pts)
    car_setup(path, g, preset="SPORTS", start_speed=130, top_speed=150, speed_scale=1.3)
    s.drive = "RWD"
    s.spin = True
    s.spin_dir = "LEFT"
    s.spin_kick = 140
    s.use_skid = s.use_smoke = s.use_dents = True
    s.use_barrier = True
    s.barrier_bounce = 0.25
    s.use_walls = True
    s.wall_collection = bpy.data.collections.get("壁")
    s.spin = False
    s.use_barrier = False
    bake()
    s.spin_frame = frame_near(body, (30, 38), 1, 200)
    s.spin = True
    s.use_barrier = True
    bake()
    hitf = report_frame("バリヤに衝突") or 120
    dress_generic(pts, 6.0, None, car_tracks([body], 1, 200), (60, 45), 200, (50, 0), 360, seed=2,
                  avoid=[(x_, 49.5, 4.5) for x_ in range(26, 136, 5)] + [(55, 25, 5), (70, 50, 5)])
    a = chase_cam("カメラA_追いかけ", body, 1, 200)
    b = fixed_cam("カメラB_立ち上がり", (55, 25, 6), body, 1, 200, lens=45)
    c = fixed_cam("カメラC_リプレイ", (70, 50, 1.3), body, 1, 200, lens=30, smooth=0.5)
    finish("スピンして後ろ向きにタイヤバリヤへ", "テスタロッサ ／ 立ち上がりで後輪が流れ、バリヤに刺さる",
           [(a, 1, 64), (b, 65, 200)], (c, hitf - 10, hitf + 30, 0.4))


def scene_wall_scrape():
    """コンクリート壁を擦りながら走り、コースに戻る"""
    pick("R32")
    sc.frame_start, sc.frame_end = 1, 190
    wall_x = -7.0
    pts = []
    for y in range(-60, 301, 2):
        off = 0.0
        if 0 < y < 200:
            u = (y - 0) / 200.0
            off = -6.4 * math.sin(math.pi * u) ** 2       # 壁側（左）へなめらかに寄って、戻る
        pts.append((off, float(y)))
    straight = line((0, -60), (0, 300))
    g = ground(None, 400, (0, 120))
    ribbon(straight, -6, 6)
    wall(straight, -6.6, 0.6, 1.1)
    path = course(pts)
    car_setup(path, g, start_speed=140, top_speed=150)
    s.use_walls = True
    s.wall_collection = bpy.data.collections.get("壁")
    s.use_skid = s.use_smoke = s.use_dents = True
    s.smoke_color = (0.8, 0.78, 0.75)
    s.smoke_amount = 1.5
    s.skid_threshold = 0.1
    s.use_sparks = True
    s.spark_amount = 2.0
    s.use_parts = True
    s.parts_collection = make_parts()
    s.parts_strength = 3.0
    bake()
    a = chase_cam("カメラA_追いかけ", body, 1, 190, dist=10, side=4)
    b = fixed_cam("カメラB_ストレート", (9, 105, 3), body, 1, 190, lens=35)
    c = fixed_cam("カメラC_リプレイ", (-4.6, 128, 0.7), body, 1, 190, lens=26, smooth=0.6)
    midf = frame_near(body, (-6, 100), 1, 190)
    finish("ガードウォールを擦りながら走る", "R32 ／ 壁に寄せて擦り、土煙を上げながらコースに戻る",
           [(a, 1, 60), (b, 61, 190)], (c, midf - 20, midf + 20, 0.5))


def scene_multi_crash():
    """先頭車がスピン、後続が避けきれずに突っ込む多重クラッシュ"""
    pick("R32")
    sc.frame_start, sc.frame_end = 1, 200
    pts = line((0, -160), (0, 300))
    g = ground(None, 480, (0, 60))
    ribbon(pts, -7, 7)
    for xo in (-6.6, 6.6):
        ribbon(pts, xo - 0.15, xo + 0.15, 0.03, None, "白", "白線")
    path = course(pts)
    car_setup(path, g, start_speed=150, top_speed=155)
    s.drive = "RWD"
    s.spin = True
    s.spin_frame = 40
    s.spin_dir = "LEFT"
    s.spin_kick = 150
    s.use_skid = s.use_smoke = s.use_dents = True
    s.smoke_color = (0.78, 0.76, 0.74)
    s.use_multi = True
    s.multi_collide = True
    cars = []
    for i, (lane, gap, tint) in enumerate(((0.4, 30, (0.9, 0.1, 0.05, 1)), (-1.8, 52, (0.95, 0.75, 0.05, 1)))):
        p2 = course(line((lane, -160 - gap), (lane, 300)), "走行ライン%d" % (i + 2))
        b2, w2 = dup_car((lane, -160 - gap, 0), None, model=("TESTA", "S2000")[i])
        add_car(b2, w2, p2, speed_mult=1.0, start_speed=150, avoid=False, overtake=False)
        cars.append(b2)
    bake()
    hitf = report_frame("車同士") or 70
    a = chase_cam("カメラA_追いかけ", cars[1], 1, 200, dist=14, height=5, side=2)
    b = fixed_cam("カメラB_路肩", (16, -40, 5), body, 1, 200, lens=60, smooth=0.25)
    c = fixed_cam("カメラC_リプレイ", (-10, -68, 1.3), body, 1, 200, lens=40, smooth=0.4)
    finish("先頭車のスピンから多重クラッシュ", "R32・テスタロッサ・S2000 ／ スピンした先頭車に、後続が避けきれず突っ込む",
           [(a, 1, 50), (b, 51, 200)], (c, 55, 130, 0.45))


def scene_drift_battle():
    """2台並んでドリフトバトル"""
    pick("R32")
    sc.frame_start, sc.frame_end = 1, 260
    pts = join(line((0, -60), (0, 20)), arc(-25, 20, 25, 0, 180), line((-50, 20), (-50, -10)),
               arc(-75, -10, 25, 0, -180), line((-100, -10), (-100, 60)))
    g = ground(None, 360, (-50, 0), material="アスファルト")
    path = course(pts)
    car_setup(path, g, start_speed=80, top_speed=95, lane_offset=2.3)
    s.drive = "RWD"
    s.drift = True
    s.drift_angle = 38
    s.drift_r_start = 50
    s.drift_r_full = 22
    s.use_skid = s.use_smoke = True
    s.smoke_amount = 1.2
    s.use_multi = True
    p2 = course(join(line((0, -72), (0, -60)), pts[1:]), "走行ライン2")
    b2, w2 = dup_car((0, -72, 0), None, model="S2000")
    add_car(b2, w2, p2, lane_offset=-2.3, speed_mult=1.0, start_speed=82, overtake=False)
    bake()
    a = chase_cam("カメラA_追いかけ", body, 1, 260, dist=13, height=5, side=-3)
    b = fixed_cam("カメラB_ヘアピン", (-25, 55, 9), body, 1, 260, lens=35, smooth=0.15)
    c = fixed_cam("カメラC_リプレイ", (-55, 5, 1.3), body, 1, 260, lens=28, smooth=0.4)
    finish("2台並んでドリフトバトル", "R32 と S2000 ／ 並んだままカウンターを当てて連続コーナーへ",
           [(a, 1, 70), (b, 71, 150), (a, 151, 260)], (c, 160, 230, 0.5))


def scene_touge_rail():
    """峠の下りヘアピンでガードレールに接触"""
    pick("S2000")
    sc.frame_start, sc.frame_end = 1, 200

    def gfn(x, y):
        return -0.09 * y + 1.5 * math.sin(x * 0.05) * math.cos(y * 0.04)
    pts = join(line((0, -100), (0, 20)), arc(-15, 20, 15, 0, 180), line((-30, 20), (-30, -60)))
    g = ground(gfn, 320, (-15, -20), material="岩")
    ribbon(pts, -4, 4, 0.05, gfn)
    rail_pts = arc(-15, 20, 15, 10, 170, 1.0)
    wall(rail_pts, 5.0, 0.15, 0.75, gfn, "ガードレール")
    for i in range(0, len(rail_pts), 4):          # 支柱
        x, y = rail_pts[i]
        ang = math.atan2(y - 20, x + 15)
        px, py = -15 + 20.1 * math.cos(ang), 20 + 20.1 * math.sin(ang)
        box_obj("支柱", (px, py, gfn(px, py) + 0.35), (0.08, 0.08, 0.7), M("ガードレール"))
    path = course(pts, fn=gfn)
    car_setup(path, g, start_speed=110, top_speed=120, speed_scale=1.7)
    s.use_walls = True
    s.wall_collection = bpy.data.collections.get("壁")
    s.use_skid = s.use_smoke = s.use_dents = True
    s.smoke_color = (0.7, 0.68, 0.65)
    bake()
    a = chase_cam("カメラA_追いかけ", body, 1, 200, dist=10, height=4)
    b = fixed_cam("カメラB_ヘアピン", (-15, 15, gfn(-15, 15) + 12), body, 1, 200, lens=30)
    c = fixed_cam("カメラC_リプレイ", (-15, 50, gfn(-15, 50) + 3), body, 1, 200, lens=35, smooth=0.5)
    hitf = 100
    for f in range(1, 201):
        sc.frame_set(f)
        p_ = body.matrix_world.translation
        if p_.y / K > 20 and math.hypot(p_.x / K + 15, p_.y / K - 20) > 18.5:
            hitf = f
            break
    finish("峠のヘアピンでガードレールに接触", "S2000 ／ 下りでオーバースピード、ガードレールに弾かれる",
           [(a, 1, 55), (b, 56, 200)], (c, hitf - 15, hitf + 25, 0.45))


def scene_rally_jump():
    """ラリーのクレストで大ジャンプ"""
    pick("R32")
    sc.frame_start, sc.frame_end = 1, 170

    def gfn(x, y):
        z = 0.6 * math.sin(x * 0.06) * math.cos(y * 0.035)
        if 30 < y < 62:
            u = (y - 30) / 32.0
            z += 2.6 * math.sin(math.pi * u) ** 1.5 * (1.0 if u < 0.75 else max(0.0, 1.0 - (u - 0.75) * 6))
        return z
    pts = join(line((0, -80), (0, 120)), arc(30, 120, 30, 180, 120))
    g = ground(gfn, 360, (0, 40), material="土")
    ribbon(pts, -4, 4, 0.03, gfn, "砂利")
    path = course(pts, fn=gfn)
    car_setup(path, g, preset="RALLY", start_speed=110, top_speed=125)
    s.road_noise = 0.03
    s.use_skid = s.use_smoke = s.use_dents = True
    s.smoke_color = (0.6, 0.5, 0.35)
    s.smoke_amount = 2.0
    s.skid_threshold = 0.05
    s.smoke_threshold = 0.05
    bake()
    a = chase_cam("カメラA_追いかけ", body, 1, 170, dist=12, height=3)
    b = fixed_cam("カメラB_ジャンプ", (14, 58, 2.0), body, 1, 170, lens=28, smooth=0.5)
    takeoff = frame_near(body, (0, 55), 1, 170)
    c = fixed_cam("カメラC_リプレイ", (-9, 75, 0.8), body, 1, 170, lens=22, smooth=0.6)
    finish("ラリーのクレストで大ジャンプ", "R32（ラリー仕様）／ 砂利道のクレストで飛んで、土煙で着地",
           [(a, 1, takeoff - 18), (b, takeoff - 17, 170)], (c, takeoff - 6, takeoff + 40, 0.4))


def scene_snow_spin():
    """雪道の凍った区間でスピン、雪の壁へ"""
    pick("TESTA")
    sc.frame_start, sc.frame_end = 1, 200
    pts = join(line((0, -80), (0, 30)), arc(-60, 30, 60, 0, 60))
    ice = lambda x, y: (25 < y < 60 and -8 < x < 6)
    MATS["雪"] = mat("雪_青み", (0.78, 0.82, 0.9, 1), 0.7)
    g = ground(None, 320, (-20, 20), material="雪", grip=ice)
    ribbon(pts, -4, 4, 0.02, None, "コンクリート", "圧雪の道")
    mesh_obj("凍った路面", [(-5, 25, 0.03), (5, 25, 0.03), (5, 60, 0.03), (-5, 60, 0.03)], [(0, 1, 2, 3)], M("氷"))
    wall(join(line((0, -80), (0, 30)), arc(-60, 30, 60, 0, 60)), 7.5, 1.5, 1.4, None, "雪", name="雪の壁")
    path = course(pts)
    car_setup(path, g, start_speed=90, top_speed=95, mu=0.45)
    s.use_grip_map = True
    s.grip_vgroup = "滑りやすさ"
    s.grip_low = 0.15
    s.use_walls = True
    s.wall_collection = bpy.data.collections.get("壁")
    s.use_skid = s.use_smoke = s.use_dents = True
    s.smoke_color = (0.95, 0.97, 1.0)
    s.smoke_amount = 2.0
    s.assist = False
    bake()
    a = chase_cam("カメラA_追いかけ", body, 1, 200, dist=10, height=3.5)
    b = fixed_cam("カメラB_コーナー", (-13, 30, 4), body, 1, 200, lens=35)
    c = fixed_cam("カメラC_リプレイ", (-7, 56, 1.0), body, 1, 200, lens=28, smooth=0.5)
    icef = frame_near(body, (0, 40), 1, 200)
    finish("雪道の凍った区間でスピン", "テスタロッサ ／ 氷の上で後輪が流れ、雪の壁に突っ込む",
           [(a, 1, icef - 12), (b, icef - 11, 200)], (c, icef - 4, icef + 45, 0.45))


def scene_puddle_spin():
    """雨の高速道路、水たまりで突然スピン"""
    pick("S2000")
    sc.frame_start, sc.frame_end = 1, 190
    pts = line((0, -100), (0, 250))
    puddle = lambda x, y: (40 < y < 52 and -1.5 < x < 6)
    g = ground(None, 400, (0, 70), material="芝", grip=puddle)
    ribbon(pts, -7, 7, 0.02, None, "濡れた路面")
    for xo in (-3.5, 3.5):
        for y0 in range(-100, 250, 12):
            mesh_obj("車線", [(xo - 0.07, y0, 0.03), (xo + 0.07, y0, 0.03), (xo + 0.07, y0 + 5, 0.03), (xo - 0.07, y0 + 5, 0.03)],
                     [(0, 1, 2, 3)], M("白"))
    mesh_obj("水たまり", [(-1.5, 40, 0.04), (6, 40, 0.04), (6, 52, 0.04), (-1.5, 52, 0.04)], [(0, 1, 2, 3)], M("水"))
    wall(pts, -7.6, 0.4, 0.9, None, "ガードレール")
    wall(pts, 7.6, 0.4, 0.9, None, "ガードレール")
    path = course(pts)
    car_setup(path, g, start_speed=120, top_speed=125, mu=0.75)
    s.drive = "RWD"
    s.use_grip_map = True
    s.grip_vgroup = "滑りやすさ"
    s.grip_low = 0.12
    s.use_walls = True
    s.wall_collection = bpy.data.collections.get("壁")
    s.use_skid = s.use_smoke = s.use_dents = True
    s.smoke_color = (0.82, 0.88, 0.95)
    s.smoke_amount = 2.5
    s.assist = False
    s.spin = True
    s.spin_kick = 70
    s.spin_grip = 0.5
    s.spin_dir = "RIGHT"
    pf = None
    s.spin = False
    bake()
    pf = frame_near(body, (0, 46), 1, 190)
    s.spin = True
    s.spin_frame = pf
    bake()
    a = chase_cam("カメラA_追いかけ", body, 1, 190, dist=11, height=3.2)
    b = fixed_cam("カメラB_路肩", (12, 75, 2.5), body, 1, 190, lens=40)
    c = fixed_cam("カメラC_リプレイ", (-6, 62, 1.0), body, 1, 190, lens=26, smooth=0.5)
    finish("雨の水たまりで突然スピン", "S2000 ／ 片輪が水たまりに乗った瞬間、後輪が流れる",
           [(a, 1, pf - 8), (b, pf - 7, 190)], (c, pf - 6, pf + 40, 0.45))


def scene_boxes():
    """積み上げた段ボール箱に突っ込んで吹き飛ばす"""
    pick("TESTA")
    sc.frame_start, sc.frame_end = 1, 170
    pts = line((0, -100), (0, 200))
    g = ground(None, 360, (0, 50), material="アスファルト")
    boxes = []
    for row in range(3):
        for col in range(9):
            for lv in range(4 - (col % 2)):
                x = (col - 4) * 0.62
                y = 70 + row * 0.62
                o = box_obj("段ボール", (x, y, 0.27 + lv * 0.54), (0.6, 0.6, 0.54), M("段ボール"), rot=(col * 0.13 + lv) * 0.2)
                o["cpb_barrier_n"] = (0.0, -1.0)
                boxes.append(o)
    col_ = props_coll("段ボール", boxes)
    path = course(pts)
    car_setup(path, g, start_speed=110, top_speed=115)
    s.use_barrier = True
    s.barrier_collection = col_
    s.barrier_stiff = 0.06
    s.barrier_tire_mass = 3.0
    s.barrier_bounce = 0.3
    s.barrier_friction = 0.5
    s.use_skid = True
    bake()
    hitf = report_frame("バリヤに衝突") or 90
    a = chase_cam("カメラA_追いかけ", body, 1, 170, dist=12, height=3.5)
    b = fixed_cam("カメラB_横", (14, 68, 2.0), body, 1, 170, lens=35, aim=(0, 72, 1))
    c = fixed_cam("カメラC_リプレイ", (5, 82, 1.0), body, 1, 170, lens=24, aim=(0, 71, 1.2))
    finish("段ボール箱の山に突っ込む", "テスタロッサ ／ 積み上げた箱を吹き飛ばして走り抜ける",
           [(a, 1, hitf - 20), (b, hitf - 19, 170)], (c, hitf - 8, hitf + 40, 0.4))


def scene_pylon():
    """パイロンスラローム、最後の1本をはね飛ばす"""
    pick("S2000")
    sc.frame_start, sc.frame_end = 1, 250
    pts = []
    for i in range(170):
        y = -5 + i
        x = 2.4 * math.sin((y - 10) / 18.0 * math.pi) if 10 < y < 118 else 0.0
        pts.append((x, float(y)))
    g = ground(None, 300, (0, 60), material="アスファルト")
    me = cone_mesh()
    cones = []
    for i, y in enumerate(range(19, 128, 18)):
        o = link(bpy.data.objects.new("パイロン", me))
        x = 0.0
        if i == 5:
            x = -2.3           # 最後のパイロンはライン上に置いて、はね飛ばす
        o.location = (x * K, y * K, 0)
        o["cpb_barrier_n"] = (0.0, -1.0)
        cones.append(o)
    col_ = props_coll("パイロン", cones)
    path = course(pts)
    car_setup(path, g, start_speed=70, top_speed=80)
    s.use_barrier = True
    s.barrier_collection = col_
    s.barrier_stiff = 0.02
    s.barrier_tire_mass = 0.4
    s.barrier_bounce = 0.6
    s.use_skid = True
    bake()
    hitf = frame_near(body, (-2.3, 109), 1, 250)
    a = chase_cam("カメラA_追いかけ", body, 1, 250, dist=9, height=3.5)
    b = fixed_cam("カメラB_横", (13, 80, 3), body, 1, 250, lens=35)
    c = fixed_cam("カメラC_リプレイ", (4, 114, 0.6), body, 1, 250, lens=30, aim=(-2.3, 109, 0.3))
    finish("パイロンスラローム", "S2000 ／ パイロンの間を縫って、最後の1本をはね飛ばす",
           [(a, 1, 80), (b, 81, 250)], (c, hitf - 14, hitf + 22, 0.45))


def scene_chase():
    """街中のカーチェイス（パトカーが追う）"""
    pick("TESTA")
    sc.frame_start, sc.frame_end = 1, 260
    pts = join(line((0, -60), (0, 60)), arc(15, 60, 15, 180, 90), line((15, 75), (90, 75)),
               arc(90, 60, 15, 90, 0), line((105, 60), (105, -40)))
    g = ground(None, 320, (50, 10), material="アスファルト")
    for bx in range(-2, 7):
        for by in range(-3, 6):
            cx, cy = bx * 30 - 22 + 15, by * 30 - 50 + 15
            near = any(math.hypot(px - cx, py - cy) < 22 for px, py in pts[::3])
            if near:
                continue
            h = 8 + ((bx * 7 + by * 13) % 5) * 6
            box_obj("ビル", (cx, cy, h / 2), (20, 20, h), M("ビル"))
    path = course(pts)
    car_setup(path, g, start_speed=90, top_speed=110)
    s.drift = True
    s.drift_angle = 30
    s.drift_r_start = 40
    s.drift_r_full = 16
    s.use_skid = s.use_smoke = True
    s.use_multi = True
    s.follow_gap = 0.5
    p2 = course(join(line((0, -78), (0, -60)), pts[1:]), "走行ライン2")
    b2, w2 = dup_car((0, -78, 0), (0.04, 0.04, 0.05, 1), model="R32")      # 白黒のパトカー
    # パトカーの赤色灯
    for xo, colr in ((-0.3, (1, 0.05, 0.05, 1)), (0.3, (0.1, 0.2, 1, 1))):
        lb = box_obj("赤色灯", (xo, -78, 1.42), (0.5, 0.25, 0.14), mat("灯_%s" % xo, colr, 0.3, 30.0))
        lb.parent = b2
        lb.matrix_parent_inverse = b2.matrix_world.inverted()
    add_car(b2, w2, p2, speed_mult=1.04, start_speed=95, overtake=False)
    bake()
    a = chase_cam("カメラA_追いかけ", b2, 1, 260, dist=12, height=4, side=2)
    b = fixed_cam("カメラB_交差点", (10, 92, 8), body, 1, 260, lens=30, smooth=0.2)
    c = fixed_cam("カメラC_空撮", (60, 20, 45), body, 1, 260, lens=35, smooth=0.1)
    finish("街中のカーチェイス", "逃げるテスタロッサを、R32のパトカーが追う",
           [(a, 1, 80), (b, 81, 150), (c, 151, 260)], None)


def scene_jump_roll():
    """斜めのジャンプ台で傾いて飛び、着地で横転"""
    pick("R32")
    sc.frame_start, sc.frame_end = 1, 280

    def gfn(x, y):
        if 50 < y < 64 and -6 < x < 6:
            u = (y - 50) / 14.0
            return (0.6 + 0.16 * (x + 6)) * u * 2.2           # 右側ほど高い斜めの台
        return 0.0
    pts = line((0, -100), (0, 250))
    g = ground(gfn, 380, (0, 70), material="土")
    ribbon(pts, -5, 5, 0.03, None, "砂利")
    path = course(pts)
    car_setup(path, g, start_speed=105, top_speed=110)
    s.rollover_auto = True
    s.use_skid = s.use_smoke = s.use_dents = True
    s.dent_strength = 2.5
    s.smoke_color = (0.6, 0.5, 0.35)
    s.smoke_amount = 1.5
    bake()
    takeoff = frame_near(body, (0, 64), 1, 280)
    dress_generic(pts, 5.0, gfn, car_tracks([body], 1, 280), (0, 64), 280, (0, 70), 380, seed=13, white=False,
                  avoid=[(0, 57, 9), (17, 74, 5), (-12, 92, 4)])
    a = chase_cam("カメラA_追いかけ", body, 1, 280, dist=12, height=3)
    b = fixed_cam("カメラB_横", (17, 74, 3), body, 1, 280, lens=35)
    c = fixed_cam("カメラC_リプレイ", (-12, 92, 1.0), body, 1, 280, lens=24, smooth=0.5)
    finish("斜めのジャンプ台から横転", "R32 ／ 片側から飛び出して空中で傾き、着地で転がる",
           [(a, 1, takeoff - 15), (b, takeoff - 14, 280)], (c, takeoff - 4, takeoff + 50, 0.4))


def make_parts():
    """R32 のドアミラーを左右に分け、フロントバンパーを切り出して「外れるパーツ」にする（コピー上でだけ）
    ボディとミラーは左半分＋ミラーモディファイアなので、左はそのまま、右は左右反転したメッシュにする"""
    parts = []
    mir = bpy.data.objects.get("DTM_190E_EvoII_body.002")
    if mir is not None:
        for side, nm in ((-1.0, "ミラー左"), (1.0, "ミラー右")):
            o = mir.copy()
            o.data = mir.data.copy()
            o.name = nm
            sc.collection.objects.link(o)
            for md in [m_ for m_ in o.modifiers if m_.type == 'MIRROR']:
                o.modifiers.remove(md)
            if side > 0:
                bm = bmesh.new()
                bm.from_mesh(o.data)
                bmesh.ops.scale(bm, vec=(-1.0, 1.0, 1.0), verts=bm.verts)
                bmesh.ops.reverse_faces(bm, faces=bm.faces)
                bm.to_mesh(o.data)
                bm.free()
            parts.append(o)
        bpy.data.objects.remove(mir)
    bod = bpy.data.objects.get("DTM_190E_EvoII_body.001")
    if bod is not None:
        Mw = bod.matrix_world
        bm = bmesh.new()
        bm.from_mesh(bod.data)
        bm.faces.ensure_lookup_table()
        ymax = max((Mw @ v.co).y for v in bm.verts)
        idx = {f.index for f in bm.faces
               if (Mw @ f.calc_center_median()).y > ymax - 0.30 * K and (Mw @ f.calc_center_median()).z < 0.55 * K}
        bm2 = bm.copy()
        bm2.faces.ensure_lookup_table()
        bmesh.ops.delete(bm2, geom=[f for f in bm2.faces if f.index not in idx], context='FACES')
        bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.index in idx], context='FACES')
        bm.to_mesh(bod.data)
        bm.free()
        me2 = bpy.data.meshes.new("フロントバンパー")
        bm2.to_mesh(me2)
        bm2.free()
        for m_ in bod.data.materials:
            me2.materials.append(m_)
        bo = bod.copy()                  # ミラーなどのモディファイアごと複製
        bo.data = me2
        bo.name = "フロントバンパー"
        sc.collection.objects.link(bo)
        parts.append(bo)
    return props_coll("外れるパーツ", parts)


def keyed_light(name, loc, size, color, on_f, off_f=None):
    """emission を時間で点けたり消したりするランプ"""
    m = mat(name, color, 0.4)
    bs = next(n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    bs.inputs['Emission Color'].default_value = color
    inp = bs.inputs['Emission Strength']
    for f_, v_ in ((1, 0.0), (on_f, 25.0)) + (((off_f, 0.0),) if off_f else ()):
        inp.default_value = v_
        inp.keyframe_insert("default_value", frame=f_)
    for fc in m.node_tree.animation_data.action.fcurves:
        for kp in fc.keyframe_points:
            kp.interpolation = 'CONSTANT'
    return box_obj(name, loc, size, m)


def label_obj(text, loc, size, rot=(math.pi / 2, 0, 0), color=(0.05, 0.05, 0.05, 1)):
    cu = bpy.data.curves.new(text, 'FONT')
    cu.body = text
    cu.align_x, cu.align_y = 'CENTER', 'CENTER'
    cu.size = size * K
    cu.materials.append(mat("文字_" + text, color, 0.6))
    o = link(bpy.data.objects.new(text, cu))
    o.location = Vector(loc) * K
    o.rotation_euler = rot
    return o


def strip_mesh(name, ys, x0, x1, zfn, mat_fn):
    """y 方向に細かく区切った帯（走る路面）。zfn(y) が高さ、mat_fn(y) が材質名"""
    verts, faces, fm = [], [], []
    names = []
    for i, y in enumerate(ys):
        z = zfn(y)
        verts += [(x0, y, z), (x1, y, z)]
        if i:
            faces.append((2 * i - 2, 2 * i - 1, 2 * i + 1, 2 * i))
            mn = mat_fn((ys[i - 1] + y) * 0.5)
            if mn not in names:
                names.append(mn)
            fm.append(names.index(mn))
    o = mesh_obj(name, verts, faces, M(names[0]))
    for mn in names[1:]:
        o.data.materials.append(M(mn))
    for f_, mi in zip(o.data.polygons, fm):
        f_.material_index = mi
    return o


def scene_bridge():
    """高速道路の橋: 継ぎ目・段差・うねりを連続で越え、くぼみで底を擦って火花"""
    pick("R32")
    sc.frame_start, sc.frame_end = 1, 300
    MATS["鋼板"] = mat("鋼板", (0.32, 0.33, 0.35, 1), 0.3)
    MATS["水面"] = mat("水面", (0.08, 0.16, 0.2, 1), 0.08)
    joints = [20.0 + 25.0 * i for i in range(5)] + [190.0, 280.0, 350.0, 380.0]
    STEP0, STEP1 = 150.0, 168.0
    WAVE0, WAVE1 = 215.0, 257.0
    DIP0, DIP1 = 300.0, 318.0

    def road_z(y):
        z = 0.0
        for jy in joints:                       # 継ぎ目: 鋼板が 3cm 盛り上がる
            d = abs(y - jy)
            if d < 0.25:
                z += 0.03
            elif d < 0.35:
                z += 0.03 * (0.35 - d) / 0.1
        if STEP0 <= y < STEP1:                  # 段差: 6cm ストンと落ちて、18m かけて戻る
            z -= 0.06 * (1.0 - (y - STEP0) / (STEP1 - STEP0))
        if WAVE0 < y < WAVE1:                   # うねり
            u = (y - WAVE0) / (WAVE1 - WAVE0)
            z += 0.16 * math.sin(2 * math.pi * (y - WAVE0) / 14.0) * math.sin(math.pi * u)
        if DIP0 < y < DIP1:                     # くぼみ: 出口で縮みきって底を擦る
            z -= 0.22 * math.sin(math.pi * (y - DIP0) / (DIP1 - DIP0)) ** 2
        return z

    ys = []
    y = -70.0
    while y <= 460.0:
        ys.append(round(y, 3))
        fine = any(abs(y - jy) < 0.5 for jy in joints) or abs(y - STEP0) < 0.3
        y += 0.05 if fine else 0.5
    ys += [STEP0 - 0.002]
    ys = sorted(set(ys))

    def zfn(y):
        return road_z(y)

    def matn(y):
        return "鋼板" if any(abs(y - jy) < 0.35 for jy in joints) else "アスファルト"
    g = strip_mesh("橋の路面", ys, -6.5, 6.5, zfn, matn)
    for xo in (-0.1,):
        for y0 in range(-60, 450, 12):
            ribbon(line((xo, y0), (xo, y0 + 6), 1.0), -0.08, 0.08, 0.006, lambda x, y: road_z(y), "白", "車線")
    for xo in (-5.9, 5.9):
        ribbon(line((xo, -70), (xo, 460), 0.5), -0.08, 0.08, 0.006, lambda x, y: road_z(y), "白", "外側線")
    side = line((0, -70), (0, 460), 2.0)
    wall(side, 6.5, 0.4, 0.9, None, "コンクリート", name="高欄")
    wall(side, -6.5, 0.4, 0.9, None, "コンクリート", name="高欄")
    box_obj("桁", (0, 195, -1.0), (12.6, 530, 1.8), M("コンクリート"))
    for yy in range(-50, 451, 100):
        box_obj("橋脚", (0, yy, -8.5), (3.0, 4.0, 13.0), M("コンクリート"))
    bpy.ops.mesh.primitive_plane_add(size=1600 * K, location=(0, 200 * K, -14.5 * K))
    bpy.context.object.data.materials.append(M("水面"))
    for yy in range(-40, 451, 45):
        for xo in (-7.0, 7.0):
            box_obj("照明柱", (xo, yy, 4.5), (0.18, 0.18, 9.0), M("ガードレール"))
            box_obj("照明", (xo * 0.82, yy, 9.0), (2.6, 0.3, 0.2), M("ガードレール"))
    path = course(line((-2.0, -55), (-2.0, 450), 2.0))
    car_setup(path, g, start_speed=112, top_speed=115)
    s.use_sparks = True
    s.spark_amount = 1.5
    s.spark_clearance = 0.035
    bake()
    jf = frame_near(body, (-2.0, 70), 1, 300)
    sf = frame_near(body, (-2.0, STEP0), 1, 300)
    wf = frame_near(body, (-2.0, WAVE0), 1, 300)
    df = frame_near(body, (-2.0, DIP0 + 9), 1, 300)
    a = chase_cam("カメラA_横から並走", body, 1, 300, dist=0.6, height=0.55, side=5.6, lens=24, look=0.6, smooth=0.2)
    b = fixed_cam("カメラB_段差の正面", (1.0, STEP0 + 22, 0.35), body, 1, 300, lens=70, smooth=0.5)
    c = chase_cam("カメラC_後ろ低め", body, 1, 300, dist=7, height=0.9, side=1.2, lens=30, look=6)
    d = fixed_cam("カメラD_くぼみ", (5.0, DIP1 + 4, 0.4), body, 1, 300, lens=32, smooth=0.5)
    finish("橋の継ぎ目と段差を越える", "R32 ／ 継ぎ目・段差・うねりでサスペンションが動き、くぼみで底を擦る",
           [(a, 1, sf - 32), (b, sf - 31, sf + 12), (a, sf + 13, wf + 30), (c, wf + 31, df - 22), (d, df - 21, 300)],
           (d, df - 12, df + 16, 0.3))


def scene_drag():
    """ドラッグレース: 2台が後輪を空転させてスタート、ゼロヨン"""
    pick("R32")
    sc.frame_start, sc.frame_end = 1, 330
    GO = 40
    QM = 402.3
    MATS["ゴム"] = mat("ゴムの跡", (0.02, 0.02, 0.02, 1), 0.7)
    MATS["発進"] = mat("発進パッド", (0.3, 0.3, 0.3, 1), 0.85)
    g = ground(None, 900, (0, 300), subdiv=60)
    ribbon(line((0, -40), (0, 760), 4.0), -7.5, 7.5, 0.02, None, "アスファルト", "ドラッグストリップ")
    ribbon(line((0, -12), (0, 70), 2.0), -7.5, 7.5, 0.03, None, "発進", "発進パッド")
    for xo in (-3.75, -2.25, 2.25, 3.75):
        ribbon(line((xo, -4), (xo, 120), 2.0), -0.15, 0.15, 0.035, None, "ゴム", "タイヤの跡")
    ribbon(line((0, -40), (0, 760), 4.0), -0.07, 0.07, 0.04, None, "黄線", "センターライン")
    ribbon(line((0, -0.15), (0, 0.15), 0.3), -7.5, 7.5, 0.045, None, "白", "スタートライン")
    ribbon(line((0, QM - 0.3), (0, QM + 0.3), 0.6), -7.5, 7.5, 0.045, None, "白", "ゴールライン")
    straight = line((0, -40), (0, 760), 4.0)
    wall(straight, 7.8, 0.5, 1.0, None, "白", name="ガードウォール")
    wall(straight, -7.8, 0.5, 1.0, None, "白", name="ガードウォール")
    # クリスマスツリー（スタートのライト）
    box_obj("ツリーの柱", (0, -6, 1.6), (0.25, 0.25, 3.2), M("ガードレール"))
    for i, (zz, col, on_f) in enumerate(((3.0, (1.0, 0.5, 0.0, 1), GO - 24), (2.7, (1.0, 0.5, 0.0, 1), GO - 16),
                                         (2.4, (1.0, 0.5, 0.0, 1), GO - 8), (2.0, (0.1, 1.0, 0.15, 1), GO))):
        for xo in (-0.3, 0.3):
            keyed_light("ツリー%d" % i, (xo, -6, zz), (0.22, 0.12, 0.22), col, on_f, GO + 60 if i < 3 else None)
    for xo in (-0.3, 0.3):
        keyed_light("ステージ", (xo, -6, 3.3), (0.14, 0.12, 0.08), (1, 1, 0.9, 1), 1)
    # 距離の看板とゴールのゲート
    for dist_, txt in ((18.3, "60ft"), (100.6, "330ft"), (201.2, "1/8"), (304.8, "1000ft"), (QM, "1/4")):
        box_obj("看板", (9.0, dist_, 1.6), (0.15, 2.4, 1.4), M("白"))
        label_obj(txt, (8.9, dist_, 1.6), 0.7, (math.pi / 2, 0, -math.pi / 2))
    for xo in (-9.0, 9.0):
        box_obj("ゲートの柱", (xo, QM, 3.5), (0.5, 0.5, 7.0), M("コンクリート"))
    for i in range(18):
        box_obj("ゲート", (-8.5 + i, QM, 7.2), (1.0, 0.4, 0.8), M("白") if i % 2 == 0 else M("岩"))
    path = course(line((-3.0, 0), (-3.0, 760), 4.0))
    car_setup(path, g, start_speed=0, top_speed=245)
    s.start_frame = GO
    s.drive = "RWD"
    s.mu = 1.8
    s.accel = 9.5
    s.launch_time = 1.6
    s.launch_slip = 16.0
    s.launch_lift = 5.0
    s.use_skid = s.use_smoke = True
    s.smoke_amount = 2.5
    s.smoke_life = 2.6
    s.smoke_size = 0.45
    s.smoke_opacity = 0.3
    s.use_multi = True
    p2 = course(line((3.0, 0), (3.0, 760), 4.0), "走行ライン2")
    b2, w2 = dup_car((3.0, 0, 0), None, model="TESTA")
    add_car(b2, w2, p2, start_frame=GO, speed_mult=0.985, overtake=False, avoid=False)
    bake()
    fin = frame_near(body, (-3.0, QM), 1, 330)
    a = fixed_cam("カメラA_正面", (0.0, 42, 0.9), body, 1, 330, lens=60, smooth=0.25, aim=(0, 1.5, 0.5))
    b = chase_cam("カメラB_並走", body, 1, 330, dist=-1.0, height=1.0, side=-4.3, lens=18, look=4, smooth=0.3)
    c = fixed_cam("カメラC_ゴール", (11, QM + 25, 3.5), body, 1, 330, lens=45, smooth=0.35)
    r = fixed_cam("カメラR_リプレイ", (-6.6, 11.0, 0.5), body, 1, 330, lens=24, smooth=0.5)
    finish("ドラッグレース", "R32 対 テスタロッサ ／ 後輪を空転させてスタート、ゼロヨン（400m）を一気に",
           [(a, 1, GO + 30), (b, GO + 31, fin - 40), (c, fin - 39, 330)], (r, GO - 4, GO + 40, 0.35))


def scene_gymkhana():
    """ジムカーナ: スラローム → サイドターン（左180°）→ サイドターン（右180°）→ ゴール"""
    pick("S2000")
    sc.frame_start, sc.frame_end = 1, 560
    R_ = 3.75
    CA = (-R_, 40.0)                     # 1つ目のターン（左回り）
    CB = (-3 * R_, -6.0)                # 2つ目のターン（右回り）
    XD, XU = -2 * R_, -4 * R_            # 戻りの列、最後の列
    sl = [(1.8 * math.cos(math.pi * (y + 14) / 15.0), y * 0.5) for y in range(-43, 48)]
    pts = join(line((0, -32), (0, -21.5), 1.0), sl, line((0, 23.5), (0, CA[1]), 1.0),
               arc(CA[0], CA[1], R_, 0, 180, 0.5), line((XD, CA[1]), (XD, CB[1]), 1.0),
               arc(CB[0], CB[1], R_, 0, -180, 0.5), line((XU, CB[1]), (XU, 70), 1.0))
    g = ground(None, 260, (-8, 10), subdiv=40, material="アスファルト")
    x0, x1, y0, y1 = -22, 8, -42, 62
    for (a_, b_) in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
        ribbon(line(a_, b_, 2.0), -0.1, 0.1, 0.01, None, "白", "外枠")
    ribbon(line((-3, -32), (3, -32), 1.0), -0.15, 0.15, 0.012, None, "白", "スタート")
    ribbon(line((XU - 3, 28), (XU + 3, 28), 1.0), -0.15, 0.15, 0.012, None, "白", "ゴール")
    for i in range(10):
        ribbon(line((14, -40 + 9 * i), (19, -40 + 9 * i), 1.0), -0.08, 0.08, 0.01, None, "白", "駐車枠")
    me = cone_mesh()
    cones = [(0, -14), (0, 1), (0, 16), CA, CB, (-1.2, -32), (1.2, -32), (XU - 1.2, 28), (XU + 1.2, 28)]
    for (cx, cy) in cones:
        o = link(bpy.data.objects.new("パイロン", me))
        o.location = (cx * K, cy * K, 0)
    path = course(pts)
    car_setup(path, g, start_speed=0, top_speed=75, corner_use=0.95)
    s.drive = "RWD"
    s.accel = 7.5
    s.mu = 1.3
    s.start_frame = 6
    s.drift = True
    s.drift_angle = 50
    s.drift_r_start = 14
    s.drift_r_full = 4
    s.drift_freq = 1.3
    s.drift_min_speed = 12
    s.use_skid = s.use_smoke = True
    s.smoke_amount = 1.6
    s.skid_threshold = 0.1
    bake()
    fa = frame_near(body, (0.0, CA[1] - 4.0), 1, 560)
    fb = frame_near(body, (XD, CB[1] + 4.0), fa + 30, 560)
    print("HANDBRAKE", fa, fb)
    for (f_, ln) in ((fa, 11), (fb, 7)):
        for fr, v in ((f_ - 1, 0.0), (f_, 1.0), (f_ + ln, 1.0), (f_ + ln + 1, 0.0)):
            s.handbrake = v
            s.keyframe_insert("handbrake", frame=fr)
    for fc in sc.animation_data.action.fcurves:
        for kp in fc.keyframe_points:
            kp.interpolation = 'CONSTANT'
    bake()
    fa = frame_near(body, (CA[0], CA[1] + R_), 1, 560)
    fb = frame_near(body, (CB[0], CB[1] - R_), fa + 30, 560)
    fg = frame_near(body, (XU, 28.0), fb + 10, 560)
    a = fixed_cam("カメラA_俯瞰", (16, 12, 22), body, 1, 560, lens=28, smooth=0.12)
    b = chase_cam("カメラB_追いかけ", body, 1, 560, dist=9, height=3.0, lens=30, smooth=0.1)
    c = fixed_cam("カメラC_ターン1", (4.5, CA[1] + 8, 0.7), body, 1, 560, lens=26, smooth=0.4)
    d = fixed_cam("カメラD_ターン2", (XD + 6, CB[1] - 9, 0.7), body, 1, 560, lens=26, smooth=0.4)
    end = min(fg + 30, 560)
    finish("ジムカーナ", "S2000 ／ スラロームからサイドターンで左右に折り返し、ゴールへ",
           [(b, 1, 110), (a, 111, fa - 40), (c, fa - 39, fa + 30), (a, fa + 31, fb - 35), (d, fb - 34, fb + 30), (b, fb + 31, end)],
           (c, fa - 14, fa + 26, 0.4), frame_end=end)


def scene_oval():
    """ナスカー風: バンクの付いたオーバルを6台がパックで走る"""
    pick("R32")
    sc.frame_start, sc.frame_end = 1, 330
    R, L = 150.0, 200.0                       # ターン半径、ストレートの長さ
    TOP = 20.0                                # 走路の幅（中心線から ±10m）

    def bank_deg(y):
        u = min(max((abs(y) - (L / 2 - 60)) / 60.0, 0.0), 1.0)
        return 3.0 + 9.0 * u * u * (3 - 2 * u)            # ストレート 3° → ターン 12°

    def H(x, y):
        sy = min(max(y, -L / 2), L / 2)
        o = math.hypot(x, y - sy) - R                       # 中心線からの距離（外側が +）
        tb = math.tan(math.radians(bank_deg(y)))
        u = o + 10.0
        if u <= 0:
            return 0.0
        if u <= TOP:
            return u * tb
        top = TOP * tb
        if o <= 30:
            return top
        return top * max(0.0, 1.0 - (o - 30) / 30.0)

    # 反時計回り（左ターン）の1周
    loop = join(line((R, -L / 2), (R, L / 2)), arc(0, L / 2, R, 0, 180), line((-R, L / 2), (-R, -L / 2)),
                arc(0, -L / 2, R, 180, 360))[:-1]
    n = len(loop)

    def normal(i):
        a, b = loop[(i - 1) % n], loop[(i + 1) % n]
        tx, ty = b[0] - a[0], b[1] - a[1]
        tl = math.hypot(tx, ty)
        return ty / tl, -tx / tl                            # 右 = 外側

    # ---- 走路のすり鉢（帯ごとに材質） ----
    bands = [(-40, "芝"), (-15, "コンクリート"), (-10.7, "黄線"), (-10.55, "コンクリート"), (-10.45, "黄線"),
             (-10.3, "コンクリート"), (-10.0, "アスファルト"), (0.0, "アスファルト"), (10.0, "コンクリート"),
             (10.6, "芝"), (30.0, "芝"), (60.0, None)]
    offs = [b_[0] for b_ in bands]
    mats_ = []
    for _, mn in bands[:-1]:
        if mn not in mats_:
            mats_.append(mn)
    verts, faces, fmat = [], [], []
    for i, (x, y) in enumerate(loop):
        rx, ry = normal(i)
        for o in offs:
            px, py = x + rx * o, y + ry * o
            verts.append((px, py, H(px, py)))
    m_ = len(offs)
    for i in range(n):
        j = (i + 1) % n
        for k_ in range(m_ - 1):
            faces.append((i * m_ + k_, i * m_ + k_ + 1, j * m_ + k_ + 1, j * m_ + k_))
            fmat.append(mats_.index(bands[k_][1]))
    g = mesh_obj("オーバル", verts, faces, M(mats_[0]))
    for mn in mats_[1:]:
        g.data.materials.append(M(mn))
    for f_, mi in zip(g.data.polygons, fmat):
        f_.material_index = mi
        f_.use_smooth = True
    bpy.ops.mesh.primitive_plane_add(size=900 * K, location=(0, 0, -0.03 * K))
    pl = bpy.context.object
    pl.name = "芝生"
    pl.data.materials.append(M("芝"))

    # スタート/フィニッシュライン
    ribbon(line((R, -0.5), (R, 0.5), 1.0), -10, 10, 0.03, H, "白", "フィニッシュライン")

    # ---- 外側の壁（SAFERバリヤ）とキャッチフェンス ----
    ring = loop + [loop[0]]
    wall(ring, 10.1, thick=0.45, height=1.1, fn=H, material="白", name="SAFERバリヤ")
    fence = mat("フェンス", (0.12, 0.12, 0.13, 1), 0.5)
    fence.blend_method = 'HASHED'
    if hasattr(fence, "shadow_method"):
        fence.shadow_method = 'NONE'
    bs = next(nd for nd in fence.node_tree.nodes if nd.type == 'BSDF_PRINCIPLED')
    bs.inputs['Alpha'].default_value = 0.3
    MATS["フェンス"] = fence
    wall(ring, 10.55, thick=0.04, height=4.6, fn=H, material="フェンス", name="キャッチフェンス")
    for i in range(0, n, 3):
        x, y = loop[i]
        rx, ry = normal(i)
        px, py = x + rx * 10.6, y + ry * 10.6
        box_obj("フェンスの柱", (px, py, H(px, py) + 2.3), (0.12, 0.12, 4.6), M("ガードレール"))

    # ---- メインスタンド（ホームストレートの外） ----
    seat = [mat("スタンド赤", (0.55, 0.06, 0.05, 1), 0.8), mat("スタンド灰", (0.35, 0.36, 0.4, 1), 0.8),
            mat("スタンド青", (0.06, 0.12, 0.45, 1), 0.8)]
    for i in range(8):
        h = 2.5 + 2.0 * i
        box_obj("スタンド", (R + 38 + 3.5 * i, 0, h / 2), (3.5, 220, h), seat[i % 3])
    box_obj("スタンドの屋根", (R + 52, 0, 21), (32, 224, 0.5), M("コンクリート"))
    for yy in range(-100, 101, 25):
        box_obj("屋根の柱", (R + 66, yy, 10.5), (0.6, 0.6, 21), M("コンクリート"))

    # ---- 8台のパック（3本のラインにばらけて、少しずつ速さを変える） ----
    def car_path(y0, o):
        """中心線から o（外側が +）ずらしたラインを、y0 から1周ちょっと"""
        Ro = R + o
        return course(join(line((Ro, y0), (Ro, L / 2)), arc(0, L / 2, Ro, 0, 180), line((-Ro, L / 2), (-Ro, -L / 2)),
                           arc(0, -L / 2, Ro, 180, 360), line((Ro, -L / 2), (Ro, L / 2))),
                      "走行ライン", lambda x, y: H(x, y))
    Y0 = -70.0
    path = car_path(Y0, -3.4)
    car_setup(path, g, start_speed=150, top_speed=160)
    s.mu = 1.6
    s.line_hold = 2.0
    s.corner_use = 0.75
    s.use_multi = True
    s.multi_collide = False
    #        名前    色                       ライン  後ろへ(m) 速さ倍率
    if MODE5:
        grid = [("F40", None, "F40", -0.4, 4.5, 1.0),
                ("カウンタック", None, "COUNTACH", 2.7, 10.5, 1.012),
                ("テスタロッサ", None, "TESTA", -3.7, 13.0, 1.0),
                ("S2000", None, "S2000", -0.8, 19.5, 1.008),
                ("F40_黄", (0.95, 0.72, 0.03, 1), "F40", -3.2, 26.0, 0.995),
                ("カウンタック_緑", (0.05, 0.55, 0.15, 1), "COUNTACH", 2.4, 28.5, 1.0),
                ("R32_青", (0.1, 0.25, 0.85, 1), "R32", -0.5, 35.0, 0.99)]
    else:
        grid = [("テスタロッサ", None, "TESTA", -0.4, 4.5, 1.0),
                ("S2000", None, "S2000", 2.7, 10.5, 1.012),
                ("R32_黄", (0.95, 0.72, 0.03, 1), "R32", -3.7, 13.0, 1.0),
                ("テスタロッサ_黒", (0.03, 0.03, 0.035, 1), "TESTA", -0.8, 19.5, 1.008),
                ("S2000_橙", (1.0, 0.35, 0.02, 1), "S2000", -3.2, 26.0, 0.995),
                ("R32_緑", (0.05, 0.55, 0.15, 1), "R32", 2.4, 28.5, 1.0),
                ("テスタロッサ_黄", (0.95, 0.72, 0.03, 1), "TESTA", -0.5, 35.0, 0.99)]
    cars = [(body, None)]
    for nm, tint, model, lane, back, sm in grid:
        b2, w2 = dup_car((R, Y0 - back, 0), tint, model=model)
        b2.name = nm
        add_car(b2, w2, car_path(Y0 - back, lane), speed_mult=sm, start_speed=150,
                overtake=False, avoid=False)
        cars.append((b2, None))
    bake()
    dress_generic(loop + [loop[0]], 10.0, H, car_tracks([c_[0] for c_ in cars], 1, 330, 4), (-R, -40), 330, (0, 0), 600,
                  seed=14, guard=False, white=False, runoff=False,
                  avoid=[(R + 52, y_, 18) for y_ in range(-110, 111, 20)]
                  + [(8, L / 2 + R - 13.5, 6), (R - 45, L / 2 + 25, 6), (-40, 60, 6)])

    mid_car = cars[2][0]
    apex = frame_near(body, (0, L / 2 + R), 1, 330)
    a = chase_cam("カメラA_中継", mid_car, 1, 330, dist=30, height=9, side=-4, lens=45, look=12)
    b = fixed_cam("カメラB_ターン1", (R - 45, L / 2 + 25, 16), body, 1, 330, lens=55, smooth=0.25)
    c = chase_cam("カメラC_車載", cars[7][0], 1, 330, dist=5.5, height=1.45, side=0.0, lens=22, look=25)
    d = fixed_cam("カメラD_空撮", (-40, 60, 110), mid_car, 1, 330, lens=110, smooth=0.15)
    e = fixed_cam("カメラE_リプレイ", (8, L / 2 + R - 13.5, 0.5), body, 1, 330, lens=24, smooth=0.5)
    finish("オーバルを8台のパックで", ("R32・S2000・F40・カウンタック・テスタロッサ ×8" if MODE5 else "R32・テスタロッサ・S2000 ×8") + " ／ ナスカー風。バンクの付いたターンを団子で駆け抜ける",
           [(a, 1, 75), (b, 76, 160), (c, 161, 245), (d, 246, 330)], (e, apex - 30, apex + 22, 0.5))


# ======================================================================
# 共通のサーキット（レースのOP用）
# ======================================================================

COLS = [(0.85, 0.06, 0.04, 1), (0.95, 0.72, 0.03, 1), (0.05, 0.55, 0.15, 1), (1.0, 0.35, 0.02, 1),
        (0.35, 0.06, 0.6, 1), (0.03, 0.03, 0.035, 1), (0.1, 0.7, 0.85, 1)]
# 複数台で混ぜる順番（車種, 色）。None は元の色
MIX = [("TESTA", None), ("S2000", None), ("R32", (0.85, 0.06, 0.04, 1)), ("TESTA", (0.95, 0.72, 0.03, 1)),
       ("S2000", (0.05, 0.55, 0.15, 1)), ("R32", (1.0, 0.35, 0.02, 1)), ("TESTA", (0.03, 0.03, 0.035, 1))]


class LoopTrack:
    """閉じたコースの中心線。距離 s で位置・右向きの法線・曲率を引ける"""

    def __init__(self, pts, step=1.0):
        P = list(pts) + [pts[0]]
        cum = [0.0]
        for a_, b_ in zip(P, P[1:]):
            cum.append(cum[-1] + math.dist(a_, b_))
        self.L = cum[-1]
        n = int(self.L / step)
        self.n, self.ds = n, self.L / n
        out = []
        j = 0
        for i in range(n):
            sv = i * self.ds
            while j < len(cum) - 2 and cum[j + 1] < sv:
                j += 1
            u = (sv - cum[j]) / max(cum[j + 1] - cum[j], 1e-9)
            out.append((P[j][0] + (P[j + 1][0] - P[j][0]) * u, P[j][1] + (P[j + 1][1] - P[j][1]) * u))
        self.p = out
        hd, self.nrm = [], []
        for i in range(n):
            a_, b_ = out[(i - 1) % n], out[(i + 1) % n]
            tx, ty = b_[0] - a_[0], b_[1] - a_[1]
            tl = math.hypot(tx, ty) or 1.0
            self.nrm.append((ty / tl, -tx / tl))
            hd.append(math.atan2(ty, tx))
        kr = []
        for i in range(n):
            d = hd[(i + 1) % n] - hd[(i - 1) % n]
            d = (d + math.pi) % (2 * math.pi) - math.pi
            kr.append(d / (2 * self.ds))
        self.k = [sum(kr[(i + q) % n] for q in range(-3, 4)) / 7.0 for i in range(n)]

    def at(self, sv):
        f = (sv / self.ds) % self.n
        i = int(f)
        u = f - i
        j = (i + 1) % self.n
        a_, b_ = self.p[i], self.p[j]
        na, nb = self.nrm[i], self.nrm[j]
        nx, ny = na[0] + (nb[0] - na[0]) * u, na[1] + (nb[1] - na[1]) * u
        nl = math.hypot(nx, ny) or 1.0
        return a_[0] + (b_[0] - a_[0]) * u, a_[1] + (b_[1] - a_[1]) * u, nx / nl, ny / nl

    def sample(self, s0, s1, off=None, step=1.0):
        m = max(2, int(abs(s1 - s0) / step))
        pts = []
        for q in range(m + 1):
            sv = s0 + (s1 - s0) * q / m
            x, y, nx, ny = self.at(sv)
            o = off(sv) if off else 0.0
            pts.append((x + nx * o, y + ny * o))
        return pts

    def s_of(self, x, y):
        i = min(range(self.n), key=lambda i: (self.p[i][0] - x) ** 2 + (self.p[i][1] - y) ** 2)
        return i * self.ds

    def set_profile(self, keys, flat_until=300.0):
        """高低差: keys=[(s, 高さ)]。エルミート補間で滑らかに（flat_until までは平ら）"""
        L = self.L
        ks = sorted(keys)
        m = len(ks)
        tang = []
        for q in range(m):
            s0_, h0_ = ks[q - 1] if q > 0 else (ks[-1][0] - L, ks[-1][1])
            s1_, h1_ = ks[q + 1] if q < m - 1 else (ks[0][0] + L, ks[0][1])
            tang.append(0.0 if ks[q][0] <= flat_until else (h1_ - h0_) / (s1_ - s0_))
        self.h = []
        for i in range(self.n):
            sv = i * self.ds
            q = max(j for j in range(m) if ks[j][0] <= sv)
            sa_, ha_ = ks[q]
            sb_, hb_ = ks[q + 1] if q < m - 1 else (ks[0][0] + L, ks[0][1])
            ta_, tb_ = tang[q], tang[(q + 1) % m]
            if sa_ < flat_until and sb_ <= flat_until:
                self.h.append(0.0)
                continue
            dd = sb_ - sa_
            u = (sv - sa_) / dd
            h00, h10, h01, h11 = 2 * u ** 3 - 3 * u ** 2 + 1, u ** 3 - 2 * u ** 2 + u, -2 * u ** 3 + 3 * u ** 2, u ** 3 - u ** 2
            self.h.append(h00 * ha_ + h10 * dd * ta_ + h01 * hb_ + h11 * dd * tb_)
        self.grid = {}
        for i, (x, y) in enumerate(self.p):
            self.grid.setdefault((int(x // 20), int(y // 20)), []).append(i)

    def h_at(self, sv):
        f = (sv / self.ds) % self.n
        i = int(f)
        u = f - i
        return self.h[i] + (self.h[(i + 1) % self.n] - self.h[i]) * u

    def h_xy(self, x, y):
        """(x, y) に一番近い中心線の高さと、その距離"""
        cx, cy = int(x // 20), int(y // 20)
        best = None
        for r in range(0, 9):
            for gx in range(cx - r, cx + r + 1):
                for gy in range(cy - r, cy + r + 1):
                    if max(abs(gx - cx), abs(gy - cy)) != r:
                        continue
                    for i in self.grid.get((gx, gy), ()):
                        d = (self.p[i][0] - x) ** 2 + (self.p[i][1] - y) ** 2
                        if best is None or d < best[0]:
                            best = (d, i)
            if best is not None and math.sqrt(best[0]) < r * 20.0 - 20.0:
                break
        if best is None:
            return 0.0, 1e9
        return self.h[best[1]], math.sqrt(best[0])

    def racing_line(self, half=5.6, kmin=1 / 150.0):
        """アウト・イン・アウト: コーナーごとに「手前で外 → 頂点（少し奥）で内 → 立ち上がりで外」の点を置き、
        滑らかにつなぐ。同じ向きのコーナーが続く間は外に残り、S字（逆向きが続く）は頂点から頂点へ真っすぐ"""
        n, ds = self.n, self.ds
        ks = [sum(self.k[(i + q) % n] for q in range(-10, 11)) / 21.0 for i in range(n)]
        corners = []
        i = 0
        while i < n:
            if abs(ks[i]) > kmin:
                sg = 1.0 if ks[i] > 0 else -1.0
                j = i
                while j + 1 < n and abs(ks[j + 1]) > kmin and (ks[j + 1] > 0) == (sg > 0):
                    j += 1
                ln = (j - i) * ds
                if ln > 8.0:
                    corners.append((i * ds, j * ds, sg))
                i = j + 1
            else:
                i += 1
        pts = []
        apex = [s0_ + 0.55 * (s1_ - s0_) for (s0_, s1_, sg) in corners]
        m = len(corners)
        for c, (s0_, s1_, sg) in enumerate(corners):
            ln = s1_ - s0_
            D = min(40.0, 0.8 * ln + 15.0)
            pa = apex[c - 1] - (self.L if c == 0 else 0.0)
            na = apex[(c + 1) % m] + (self.L if c == m - 1 else 0.0)
            se, sx = s0_ - D, s1_ + D
            if se > pa + 10.0:
                pts.append((se, half * sg))
            pts.append((apex[c], -half * sg))
            if sx < na - 10.0:
                pts.append((sx, half * sg))
        pts = sorted(((s_ % self.L), v) for s_, v in pts)
        o = []
        q = len(pts)
        for i in range(n):
            sv = i * ds
            j = max((u for u in range(q) if pts[u][0] <= sv), default=q - 1)
            sa_, va = pts[j]
            sb_, vb = pts[(j + 1) % q]
            if sv < sa_:
                sa_ -= self.L
            if sb_ <= sa_:
                sb_ += self.L
            u = (sv - sa_) / max(sb_ - sa_, 1e-6)
            w = (1 - math.cos(math.pi * u)) / 2
            o.append(max(-half, min(half, va + (vb - va) * w)))
        self.rl = o
        self.rl_pts = pts

    def RL(self, sv):
        f = (sv / self.ds) % self.n
        i = int(f)
        u = f - i
        return self.rl[i] + (self.rl[(i + 1) % self.n] - self.rl[i]) * u


def circuit(high_kerb=None):
    """メインストレート(+y) → 1〜2コーナー → S字 → 3〜4コーナーの反時計回り。右側にピットとガレージ"""
    for nm_, col_, r_ in (("シャッター", (0.55, 0.57, 0.6, 1), 0.5), ("ガレージ白", (0.86, 0.86, 0.88, 1), 0.6),
                          ("ガラス", (0.06, 0.1, 0.18, 1), 0.1), ("消灯", (0.2, 0.02, 0.02, 1), 0.4),
                          ("スタンド赤", (0.55, 0.06, 0.05, 1), 0.8), ("スタンド青", (0.06, 0.12, 0.45, 1), 0.8),
                          ("スタンド灰", (0.35, 0.36, 0.4, 1), 0.8)):
        MATS[nm_] = mat(nm_, col_, r_)
    MATS["照明"] = mat("照明", (1.0, 0.95, 0.85, 1), 0.3)
    MATS["ガレージ灯"] = mat("ガレージ灯", (1.0, 0.93, 0.8, 1), 0.5)
    es = [(-160.0 + 7.0 * math.sin(2 * math.pi * q / 105.0) * math.sin(math.pi * q / 210.0), 150.0 - q)
          for q in range(0, 211)]
    pts = join(line((0, -150), (0, 150), 2.0), arc(-40, 150, 40, 0, 90, 2.0), line((-40, 190), (-120, 190), 2.0),
               arc(-120, 150, 40, 90, 180, 2.0), es, line((-160, -60), (-160, -150), 2.0),
               arc(-120, -150, 40, 180, 270, 2.0), line((-120, -190), (-40, -190), 2.0),
               arc(-40, -150, 40, 270, 360, 2.0))[:-1]
    T = LoopTrack(pts, 1.0)
    # 高低差: 1コーナーから登り、ヘアピンが頂上。S字を下って3コーナー手前が谷。ホームストレートとピットは平ら
    T.set_profile([(0, 0.0), (150, 0.0), (300, 0.0), (362, 2.7), (443, 8.1), (478, 11.7), (510, 11.2), (570, 7.2),
                   (650, 0.9), (720, -5.4), (770, -6.8), (816, -4.7), (880, -1.1), (960, 1.4), (1000, 0.5)])
    T.racing_line()
    global TERRAIN
    TERRAIN = lambda x, y: T.h_xy(x, y)[0]
    offs = [-16.0, -8.2, -7.6, -7.0, -6.85, 6.85, 7.0, 7.6, 8.2, 16.0]
    m_ = len(offs)
    verts, faces, fmat, names = [], [], [], []

    def mi(name):
        if name not in names:
            names.append(name)
        return names.index(name)
    kon = []
    for i in range(T.n):
        sv = i * T.ds
        on = abs(T.k[i]) > 1 / 70.0 and sv >= 300.0
        kon.append(on)
        x, y = T.p[i]
        nx, ny = T.nrm[i]
        hz_ = T.h[i]
        for o in offs:
            z = hz_
            if on and abs(abs(o) - 7.6) < 1e-6:
                z = hz_ + 0.05
                if high_kerb is not None:
                    hz = high_kerb(sv, -1 if o < 0 else 1)
                    if hz is not None:
                        z = hz_ + hz
            verts.append((x + nx * o, y + ny * o, z))
    for i in range(T.n):
        j = (i + 1) % T.n
        main = i * T.ds < 300.0
        kerb = "赤" if (i // 3) % 2 == 0 else "白"
        for k_ in range(m_ - 1):
            if k_ == 0:
                mn = "芝"
            elif k_ in (1, 2):
                mn = kerb if kon[i] else "芝"
            elif k_ in (3, 5):
                mn = "白"
            elif k_ == 4:
                mn = "アスファルト"
            elif k_ in (6, 7):
                mn = kerb if kon[i] else ("アスファルト" if main else "芝")
            else:
                mn = "アスファルト" if main else "芝"
            faces.append((i * m_ + k_, i * m_ + k_ + 1, j * m_ + k_ + 1, j * m_ + k_))
            fmat.append(mi(mn))
    for (x0, x1, y0, y1, mn) in ((16.0, 24.0, -160.0, 160.0, "アスファルト"), (24.0, 40.0, -160.0, 160.0, "コンクリート")):
        b_ = len(verts)
        verts += [(x0, y0, 0.0), (x1, y0, 0.0), (x1, y1, 0.0), (x0, y1, 0.0)]
        faces.append((b_, b_ + 1, b_ + 2, b_ + 3))
        fmat.append(mi(mn))
    g = mesh_obj("サーキット", verts, faces, M(names[0]))
    for mn in names[1:]:
        g.data.materials.append(M(mn))
    for f_, m2 in zip(g.data.polygons, fmat):
        f_.material_index = m2
    # 周りの地面: コースの高さに合わせ、離れた所はなだらかに
    NG, SZ, CX = 181, 900.0, -80.0
    hs_, lock = [], []
    for gy_ in range(NG):
        for gx_ in range(NG):
            x = CX - SZ / 2 + SZ * gx_ / (NG - 1)
            y = -SZ / 2 + SZ * gy_ / (NG - 1)
            h_, d_ = T.h_xy(x, y)
            near = d_ < 18.0 or (16.0 <= x <= 40.0 and -160.0 <= y <= 160.0)
            hs_.append(h_ - 0.06 if near else h_)
            lock.append(near)
    for _ in range(25):
        nh = hs_[:]
        for gy_ in range(1, NG - 1):
            for gx_ in range(1, NG - 1):
                q = gy_ * NG + gx_
                if not lock[q]:
                    nh[q] = (hs_[q - 1] + hs_[q + 1] + hs_[q - NG] + hs_[q + NG]) * 0.25
        hs_ = nh
    gv, gf = [], []
    for gy_ in range(NG):
        for gx_ in range(NG):
            gv.append((CX - SZ / 2 + SZ * gx_ / (NG - 1), -SZ / 2 + SZ * gy_ / (NG - 1), hs_[gy_ * NG + gx_]))
    for gy_ in range(NG - 1):
        for gx_ in range(NG - 1):
            q = gy_ * NG + gx_
            gf.append((q, q + 1, q + NG + 1, q + NG))
    tr_ = mesh_obj("芝生", gv, gf, M("芝"))
    for f_ in tr_.data.polygons:
        f_.use_smooth = True
    # スタート・グリッド・ピット
    ribbon(line((-6.85, 0), (6.85, 0), 1.0), -0.3, 0.3, 0.012, None, "白", "スタートライン")
    for q in range(10):
        yy = -12.0 - 8.0 * q
        xx = 3.2 if q % 2 == 0 else -3.2
        ribbon(line((xx - 1.4, yy), (xx + 1.4, yy), 1.0), -0.08, 0.08, 0.012, None, "白", "グリッド")
    wall(line((11.0, -110.0), (11.0, 110.0), 2.0), 0.0, 0.6, 1.1, None, "コンクリート", name="ピットウォール")
    for xx in (13.0, 23.6):
        ribbon(line((xx, -140), (xx, 140), 2.0), -0.08, 0.08, 0.012, None, "白", "ピットレーン線")
    wall(T.sample(300.0, T.L, None, 2.0), 16.4, 0.5, 1.0, TERRAIN, "白", name="外周の壁")
    # ガレージ
    shutters, panels = {}, {}
    bays = [-60.0 + 12.0 * q for q in range(11)]
    for c_ in bays + [bays[-1] + 12.0]:
        box_obj("ガレージの柱", (26.5, c_ - 6.0, 2.25), (1.0, 0.6, 4.5), M("ガレージ白"))
        box_obj("ガレージの仕切り", (33.0, c_ - 6.0, 3.5), (12.0, 0.3, 7.0), M("コンクリート"))
    for c_ in bays:
        shutters[c_] = box_obj("シャッター", (26.6, c_, 2.25), (0.15, 11.4, 4.5), M("シャッター"))
        panels[c_] = box_obj("ガレージの奥の灯り", (39.3, c_, 2.4), (0.1, 10.8, 4.0), M("ガレージ灯"))
    box_obj("ガレージの梁", (26.5, 0, 5.75), (1.0, 133.0, 2.5), M("ガレージ白"))
    box_obj("ガレージの帯", (25.95, 0, 6.3), (0.1, 133.0, 0.5), M("赤"))
    box_obj("ガレージの屋根", (33.0, 0, 7.3), (14.5, 134.0, 0.6), M("コンクリート"))
    box_obj("ガレージの奥", (39.7, 0, 3.5), (0.6, 133.0, 7.0), M("コンクリート"))
    box_obj("管制塔", (33.0, 100.0, 9.0), (12.0, 14.0, 18.0), M("ガレージ白"))
    box_obj("管制塔の窓", (26.95, 100.0, 14.0), (0.2, 14.0, 3.0), M("ガラス"))
    # スタートのゲート
    for xx in (-9.5, 9.5):
        box_obj("ゲートの柱", (xx, 0, 3.5), (0.6, 0.6, 7.0), M("ガレージ白"))
    box_obj("ゲート", (0, 0, 7.0), (19.6, 1.0, 1.0), M("ガレージ白"))
    for q in range(5):
        box_obj("スタートランプ", (-2.0 + q, -0.55, 6.2), (0.6, 0.15, 0.6), M("消灯"))
    # スタンド（ホームストレートの内側）
    seat = [M("スタンド赤"), M("スタンド灰"), M("スタンド青")]
    for q in range(7):
        h = 2.0 + 1.8 * q
        box_obj("スタンド", (-22.0 - 3.2 * q, 0, h / 2), (3.2, 200.0, h), seat[q % 3])
    box_obj("スタンドの屋根", (-33.0, 0, 16.0), (26.0, 204.0, 0.5), M("コンクリート"))
    # 照明塔
    floods = []
    for yy in (-125.0, -75.0, -25.0, 25.0, 75.0, 125.0):
        for xx, ax in ((-17.5, 4.0), (42.0, 12.0)):
            box_obj("照明塔", (xx, yy, 11.0), (0.5, 0.5, 22.0), M("ガードレール"))
            box_obj("照明", (xx, yy, 22.3), (1.0, 3.0, 1.4), M("照明"))
            floods.append(((xx, yy, 22.0), (ax, yy, 0.0)))
    return dict(T=T, g=g, shutters=shutters, panels=panels, floods=floods)


def seg_path(T, s0, s1, off=None, name="走行ライン", step=1.0):
    return course(T.sample(s0, s1, off, step), name, lambda x, y: T.h_xy(x, y)[0])


def car_dim(roots, keys):
    """トゥーンの車は自分で光るので、逆光・夜は暗くする。keys: [(フレーム, 明るさ)]"""
    done = set()
    for root in roots:
        for o in [root] + list(root.children_recursive):
            if o.type != 'MESH':
                continue
            for m_ in o.data.materials:
                if m_ is None or m_.name in done or not m_.use_nodes:
                    continue
                done.add(m_.name)
                nt = m_.node_tree
                outn = next((n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL'), None)
                if outn is None or not outn.inputs['Surface'].is_linked:
                    continue
                src = outn.inputs['Surface'].links[0].from_socket
                if src.type == 'SHADER':
                    continue
                mx = nt.nodes.new('ShaderNodeMix')
                mx.data_type = 'RGBA'
                mx.blend_type = 'MULTIPLY'
                mx.inputs[0].default_value = 1.0
                ca, cb = [i for i in mx.inputs if i.type == 'RGBA'][:2]
                nt.links.new(src, ca)
                nt.links.new([q for q in mx.outputs if q.type == 'RGBA'][0], outn.inputs['Surface'])
                for f_, v in keys:
                    cb.default_value = (v, v, v, 1.0)
                    cb.keyframe_insert("default_value", frame=f_)


def set_emit(name, strength, color=None):
    m = MATS.get(name) or bpy.data.materials.get(name)
    bs = next(n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    bs.inputs['Emission Color'].default_value = color or tuple(bs.inputs['Base Color'].default_value)
    bs.inputs['Emission Strength'].default_value = strength


def aim_obj(o, target):
    o.rotation_euler = (Vector(target) * K - o.location).to_track_quat('-Z', 'Y').to_euler()


def spot(name, pos, target, energy, size_deg=70, color=(1.0, 0.93, 0.82), parent=None):
    ld = bpy.data.lights.new(name, 'SPOT')
    ld.energy = energy * K * K
    ld.spot_size = math.radians(size_deg)
    ld.spot_blend = 0.4
    ld.color = color
    if hasattr(ld, "shadow_soft_size"):
        ld.shadow_soft_size = 0.3 * K
    o = link(bpy.data.objects.new(name, ld))
    o.location = Vector(pos) * K
    if target is not None:
        aim_obj(o, target)
    if parent is not None:
        o.parent = parent
    return o


def sky_gradient(horizon, mid, zenith, strength=1.0):
    w = sc.world
    w.use_nodes = True
    nt = w.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputWorld')
    bg = nt.nodes.new('ShaderNodeBackground')
    tc = nt.nodes.new('ShaderNodeTexCoord')
    sep = nt.nodes.new('ShaderNodeSeparateXYZ')
    mr = nt.nodes.new('ShaderNodeMapRange')
    mr.inputs['From Min'].default_value = -0.05
    mr.inputs['From Max'].default_value = 0.6
    rp = nt.nodes.new('ShaderNodeValToRGB')
    nt.links.new(tc.outputs['Generated'], sep.inputs[0])
    nt.links.new(sep.outputs['Z'], mr.inputs['Value'])
    nt.links.new(mr.outputs['Result'], rp.inputs['Fac'])
    el = rp.color_ramp.elements
    el[0].position, el[0].color = 0.0, tuple(horizon) + (1.0,)
    el[1].position, el[1].color = 1.0, tuple(zenith) + (1.0,)
    e_ = el.new(0.3)
    e_.color = tuple(mid) + (1.0,)
    nt.links.new(rp.outputs['Color'], bg.inputs['Color'])
    bg.inputs['Strength'].default_value = strength
    nt.links.new(bg.outputs[0], out.inputs['Surface'])


def sun_set(elev, azim, energy, color):
    sn = bpy.data.objects.get("DemoSun")
    sn.data.energy = energy
    sn.data.color = color
    sn.rotation_euler = (math.radians(90 - elev), 0, math.radians(azim))


def light_dawn(azim=180.0):
    sky_gradient((1.0, 0.52, 0.28), (0.85, 0.62, 0.55), (0.14, 0.22, 0.45), 1.0)
    sun_set(6.0, azim, 3.5, (1.0, 0.62, 0.4))


def light_morning(azim=200.0):
    sky_gradient((0.95, 0.78, 0.6), (0.62, 0.7, 0.85), (0.3, 0.45, 0.75), 1.0)
    sun_set(22.0, azim, 3.0, (1.0, 0.85, 0.7))


def light_night(C, bays_on=None):
    w = sc.world
    w.use_nodes = False
    w.color = (0.006, 0.008, 0.02)
    sun_set(40.0, 30.0, 0.08, (0.6, 0.7, 1.0))
    set_emit("照明", 30.0)
    set_emit("ガレージ灯", 4.0)
    for (pos, aim) in C["floods"]:
        spot("投光器", pos, aim, 9000, 75)
    if hasattr(sc.eevee, "use_bloom"):
        sc.eevee.use_bloom = True
        sc.eevee.bloom_intensity = 0.06
        sc.eevee.bloom_threshold = 1.0


def headlights(b_):
    """車の前に2つのスポット（ボディの子）"""
    out = []
    for sx in (-3.4, 3.4):
        ld = bpy.data.lights.new("ヘッドライト", 'SPOT')
        ld.energy = 1800 * K * K
        ld.spot_size = math.radians(55)
        ld.spot_blend = 0.5
        ld.color = (1.0, 0.95, 0.85)
        o = link(bpy.data.objects.new("ヘッドライト", ld))
        o.parent = b_
        o.location = (sx, 12.2, 3.0)
        o.rotation_euler = (math.radians(84), 0, 0)
        out.append(o)
    return out


def orbit_cam(name, center, radius, height, a0, a1, f0, f1, lens, target=None):
    c = cam(name, lens)
    for f in range(f0, f1 + 1):
        u = (f - f0) / max(f1 - f0, 1)
        u = u * u * (3 - 2 * u) * 0.3 + u * 0.7
        a_ = math.radians(a0 + (a1 - a0) * u)
        c.location = Vector((center[0] + radius * math.cos(a_), center[1] + radius * math.sin(a_), height)) * K
        tg = target if target is not None else (center[0], center[1], 0.0)
        aim_obj(c, tg)
        c.keyframe_insert("location", frame=f)
        c.keyframe_insert("rotation_euler", frame=f)
    return c


def dolly_cam(name, p0, p1, t0, t1, f0, f1, lens):
    c = cam(name, lens)
    for f in range(f0, f1 + 1):
        u = (f - f0) / max(f1 - f0, 1)
        c.location = Vector([a_ + (b_ - a_) * u for a_, b_ in zip(p0, p1)]) * K
        aim_obj(c, [a_ + (b_ - a_) * u for a_, b_ in zip(t0, t1)])
        c.keyframe_insert("location", frame=f)
        c.keyframe_insert("rotation_euler", frame=f)
    return c


def hide_car(b_):
    for o in [b_] + list(b_.children_recursive):
        o.hide_render = True
        o.hide_viewport = True


# ---------------------------------------------------------------- 静かな導入

def scene_dawn():
    """夜明けのサーキット空撮（車なし）"""
    pick("R32")
    sc.frame_start, sc.frame_end = 1, 240
    circuit()
    hide_car(body)
    a = orbit_cam("カメラA_空撮", (-80, 0), 290, 110, -35, 15, 1, 140, 30, target=(-70, 10, 0))
    b = dolly_cam("カメラB_ストレート", (13, -130, 3.5), (12, 40, 7), (0, 120, 2), (-10, 260, 6), 141, 240, 26)
    finish("夜明けのサーキット", "誰もいないコースを、朝日の中で空から",
           [(a, 1, 140), (b, 141, 240)], None, light=lambda: light_dawn(180.0))


def scene_garage():
    """ガレージのシャッターが開き、逆光の中を R32 がゆっくり出てくる"""
    pick("R32")
    sc.frame_start, sc.frame_end = 1, 270
    C = circuit()
    sh = C["shutters"][0.0]
    for f_, z_ in ((12, 2.25), (58, 6.6)):
        sh.location.z = z_ * K
        sh.keyframe_insert("location", index=2, frame=f_)
    path = course(join(line((34, 0), (24, 0), 1.0), arc(24, 6, 6, -90, -180, 0.5), line((18, 6), (18, 150), 2.0)))
    car_setup(path, C["g"], start_speed=0, top_speed=28)
    s.start_frame = 70
    s.accel = 1.6
    bake()
    fout = frame_near(body, (25.0, 0.0), 1, 270)
    car_dim([body], [(1, 0.05), (fout - 4, 0.05), (fout + 22, 1.0)])
    a = fixed_cam("カメラA_ピットから", (13.0, -4.0, 0.7), body, 1, 270, lens=30, smooth=0.25)
    b = fixed_cam("カメラB_ピットレーン", (15.0, 42.0, 0.5), body, 1, 270, lens=50, smooth=0.3)

    def lt():
        light_morning(200.0)
        set_emit("ガレージ灯", 0.0)
        set_emit("ガレージ灯", 0.0)
        pm = mat("ガレージ灯_強", (1.0, 0.93, 0.8, 1), 0.5)
        bs = next(n for n in pm.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
        bs.inputs['Emission Color'].default_value = (1.0, 0.93, 0.8, 1)
        bs.inputs['Emission Strength'].default_value = 14.0
        C["panels"][0.0].data.materials[0] = pm
        ld = bpy.data.lights.new("ガレージの灯り", 'AREA')
        ld.energy = 1500 * K * K
        ld.size = 9 * K
        ld.color = (1.0, 0.92, 0.8)
        o = link(bpy.data.objects.new("ガレージの灯り", ld))
        o.location = Vector((37.5, 0, 3.2)) * K
        aim_obj(o, (20.0, 0.0, 1.0))
    finish("ガレージから出てくる", "R32 ／ シャッターが上がり、逆光の中をゆっくりピットへ",
           [(a, 1, fout + 48), (b, fout + 49, 270)], None, light=lt)


def scene_pitlane():
    """色違いの車が縦に並んで、ピットロードからコースへ"""
    pick("R32")
    sc.frame_start, sc.frame_end = 1, 300
    C = circuit()
    T = C["T"]
    x_in = T.RL(300.0)
    mer = [(18.0 - (18.0 - x_in) * (1 - math.cos(math.pi * q / 40.0)) / 2.0, 110.0 + q) for q in range(0, 41)]
    rest = T.sample(300.0, 300.0 + 150.0, T.RL, 2.0)

    def pit_path(y0, nm):
        return course(join(line((18.0, y0), (18.0, 110.0), 2.0), mer, rest), nm)
    path = pit_path(60.0, "走行ライン")
    car_setup(path, C["g"], start_speed=55, top_speed=60)
    s.use_multi = True
    s.follow_gap = 0.6
    cars = [body]
    for q in range(5):
        y0 = 60.0 - 14.0 * (q + 1)
        b2, w2 = dup_car((18.0, y0, 0), MIX[q][1], model=MIX[q][0])
        add_car(b2, w2, pit_path(y0, "走行ライン%d" % (q + 2)), start_speed=55, overtake=False)
        cars.append(b2)
    bake()
    a = fixed_cam("カメラA_ピット出口", (14.5, 128.0, 1.5), cars[2], 1, 300, lens=85, smooth=0.15)
    b = fixed_cam("カメラB_スタンドの上", (-18.0, 60.0, 12.0), cars[2], 1, 300, lens=45, smooth=0.12)
    c = fixed_cam("カメラC_1コーナー", (24.0, 178.0, 5.0), cars[2], 1, 300, lens=50, smooth=0.2)
    finish("ピットロードを並んで", "R32・テスタロッサ・S2000 ／ 6台が縦に並んで、コースへ出ていく",
           [(a, 1, 110), (b, 111, 190), (c, 191, 300)], None)


def scene_warmup():
    """フォーメーションラップ: 全車が左右に揺れながらタイヤを温める"""
    pick("R32")
    import random
    sc.frame_start, sc.frame_end = 1, 300
    C = circuit()
    T = C["T"]
    rng = random.Random(5)
    S0 = 0.0

    def weave(lane, ph):
        return lambda sv: lane + 1.5 * math.sin(2 * math.pi * (sv - S0) / 36.0 + ph)
    grid_ = []
    for q in range(8):
        lane = -3.0 if q % 2 == 0 else 3.0
        back = 9.0 * (q // 2) + (4.5 if q % 2 else 0.0)
        grid_.append((lane, back, rng.uniform(0, 2 * math.pi)))
    lane, back, ph = grid_[0]
    path = seg_path(T, S0 - back, S0 - back + 470.0, weave(lane, ph))
    car_setup(path, C["g"], start_speed=55, top_speed=55, mu=1.6, corner_use=0.85)
    s.use_multi = True
    cars = [body]
    for q in range(1, 8):
        lane, back, ph = grid_[q]
        b2, w2 = dup_car((0, 0, 0), MIX[q - 1][1], model=MIX[q - 1][0])
        add_car(b2, w2, seg_path(T, S0 - back, S0 - back + 470.0, weave(lane, ph), "走行ライン%d" % (q + 1)),
                start_speed=55, overtake=False, avoid=False)
        cars.append(b2)
    bake()
    mid = cars[4]
    a = fixed_cam("カメラA_正面", (1.5, -30.0, 1.2), mid, 1, 300, lens=135, smooth=0.15)
    b = chase_cam("カメラB_真上", mid, 1, 300, dist=6, height=30, lens=40, look=4, smooth=0.1)
    c = fixed_cam("カメラC_横", (-12.5, -40.0, 0.7), mid, 1, 300, lens=32, smooth=0.25)
    finish("ウォームアップの蛇行", "3車種 ×8 ／ フォーメーションラップ、全車が左右に揺れてタイヤを温める",
           [(a, 1, 100), (c, 101, 190), (b, 191, 300)], None)


# ---------------------------------------------------------------- バトル

def scene_side_by_side():
    """2台が並んだまま、ヘアピンから S 字を抜ける"""
    pick("R32")
    sc.frame_start, sc.frame_end = 1, 300
    C = circuit()
    T = C["T"]
    S0 = 300.0 + 62.8 + 30.0
    def lane(d):
        return lambda sv: max(-6.0, min(6.0, T.RL(sv) + d))
    path = seg_path(T, S0, S0 + 420.0, lane(-1.6))
    car_setup(path, C["g"], start_speed=78, top_speed=78, mu=1.6, corner_use=0.85)
    s.line_hold = 1.5
    s.use_skid = True
    s.use_multi = True
    b2, w2 = dup_car((0, 0, 0), None, model="S2000")
    add_car(b2, w2, seg_path(T, S0, S0 + 420.0, lane(1.6), "走行ライン2"), start_speed=78, overtake=False,
            avoid=False)
    bake()
    a = chase_cam("カメラA_後ろから", body, 1, 300, dist=13, height=3.5, side=2.6, lens=30, smooth=0.1)
    b = fixed_cam("カメラB_S字の下", (-151.0, -108.0, 1.2), body, 1, 300, lens=55, smooth=0.2)
    c = fixed_cam("カメラC_ヘアピン", (-112.0, 170.0, 14.0), body, 1, 300, lens=35, smooth=0.15)
    f_es = frame_near(body, (-160.0, 100.0), 1, 300)
    finish("サイド・バイ・サイド", "R32 と S2000 ／ 並んだまま、ヘアピンから連続コーナーへ",
           [(a, 1, f_es - 45), (c, f_es - 44, f_es + 20), (b, f_es + 21, 300)], None)


def scene_kerb_sparks():
    """3コーナーのイン側の縁石に乗って、底から火花"""
    pick("R32")
    sc.frame_start, sc.frame_end = 1, 220
    T0 = None
    apx = (-120.0 + 40 * math.cos(math.radians(225)), -150.0 + 40 * math.sin(math.radians(225)))
    holder = {}

    def hk(sv, side):
        sa = holder.get("sa")
        if sa is not None and side < 0 and abs(sv - sa) < 30.0:
            return 0.10
        return None
    # 1回目でコースを作って頂点の距離を測り、2回目は使わずにそのまま縁石の高さに反映
    tmp = LoopTrack(join(line((0, -150), (0, 150), 2.0), arc(-40, 150, 40, 0, 90, 2.0),
                         line((-40, 190), (-120, 190), 2.0), arc(-120, 150, 40, 90, 180, 2.0),
                         [(-160.0 + 7.0 * math.sin(2 * math.pi * q / 105.0) * math.sin(math.pi * q / 210.0), 150.0 - q)
                          for q in range(0, 211)], line((-160, -60), (-160, -150), 2.0),
                         arc(-120, -150, 40, 180, 270, 2.0), line((-120, -190), (-40, -190), 2.0),
                         arc(-40, -150, 40, 270, 360, 2.0))[:-1], 1.0)
    holder["sa"] = tmp.s_of(*apx)
    C = circuit(high_kerb=hk)
    T = C["T"]
    sa = holder["sa"]

    extra = -7.1 - T.RL(sa)

    def line_off(sv):
        b_ = math.exp(-((sv - sa) / 14.0) ** 2)
        return T.RL(sv) + extra * b_
    path = seg_path(T, sa - 140.0, sa + 160.0, line_off)
    car_setup(path, C["g"], start_speed=105, top_speed=110, mu=1.6, corner_use=0.85)
    s.line_hold = 1.0
    s.use_sparks = True
    s.spark_amount = 3.0
    s.spark_clearance = 0.065
    s.use_skid = True
    bake()
    fa = frame_near(body, apx, 1, 220)
    ang = math.radians(235)
    a = chase_cam("カメラA_追いかけ", body, 1, 220, dist=10, height=3.0, side=-2.0, lens=32, smooth=0.1)
    b = fixed_cam("カメラB_縁石の内側", (-120.0 + 29.0 * math.cos(ang), -150.0 + 29.0 * math.sin(ang), 0.4), body,
                  1, 220, lens=24, smooth=0.45)
    finish("縁石を擦って火花", "R32 ／ イン側の縁石に乗り上げ、車体の底から火花を散らす",
           [(a, 1, fa - 30), (b, fa - 29, 220)], (b, fa - 14, fa + 22, 0.35))


def scene_slipstream():
    """ストレートで後ろにピッタリ付き、横に出て抜く"""
    pick("R32")
    sc.frame_start, sc.frame_end = 1, 170
    C = circuit()
    # 主役（青）が抜く側。前の車（赤）は 150km/h 一定。シーンはストレートの途中で終わる（先は真っすぐ）
    lc = [(2.0 - 5.0 * (1 - math.cos(math.pi * q / 80.0)) / 2.0, -76.0 + q) for q in range(0, 81)]
    path = course(join(line((2.0, -147.0), (2.0, -76.0), 1.0), lc, line((-3.0, 4.0), (-3.0, 420.0), 2.0)))
    car_setup(path, C["g"], start_speed=150, top_speed=200, mu=1.6)
    s.accel = 7.0
    s.use_multi = True
    b2, w2 = dup_car((2.0, -140.0, 0), None, model="TESTA")
    add_car(b2, w2, course(line((2.0, -140.0), (2.0, 420.0), 2.0), "走行ライン2"), start_speed=150,
            speed_mult=150.0 / 200.0, overtake=False, avoid=False)
    for nm, xy, fr in (("真後ろに付く地点", (2.0, -72.0), 46), ("抜き去る地点", (-3.0, 150.0), 150)):
        e = link(bpy.data.objects.new(nm, None))
        e.location = (xy[0] * K, xy[1] * K, 0)
        it = s.timing_items.add()
        it.marker = e
        it.frame = fr
    s.use_timing = True
    bake()
    fp = 170
    for f in range(1, 171):
        sc.frame_set(f)
        if body.matrix_world.translation.y > b2.matrix_world.translation.y + 5.0 * K:
            fp = f
            break
    print("PASS", fp)
    a = chase_cam("カメラA_真後ろ", body, 1, 170, dist=6.5, height=2.1, side=-0.6, lens=30, look=25, smooth=0.12)
    b = fixed_cam("カメラB_正面", (-1.0, 150.0, 1.0), body, 1, 170, lens=110, smooth=0.2)
    c = fixed_cam("カメラC_横", (-11.0, 45.0, 1.0), body, 1, 170, lens=45, smooth=0.35)
    finish("スリップストリームから抜く", "R32 と テスタロッサ ／ 真後ろに付いて風を避け、横に出て抜き去る",
           [(a, 1, 62), (b, 63, fp - 22), (c, fp - 21, min(fp + 25, 170))], (c, fp - 28, fp + 14, 0.4),
           frame_end=min(fp + 25, 170))


def scene_drift_slow():
    """1コーナーをドリフトで。スモークがゆっくり広がるスロー"""
    pick("S2000")
    sc.frame_start, sc.frame_end = 1, 220
    C = circuit()
    T = C["T"]
    path = seg_path(T, 200.0, 560.0, T.RL)
    car_setup(path, C["g"], start_speed=110, top_speed=115)
    s.drive = "RWD"
    s.drift = True
    s.drift_angle = 42
    s.drift_r_start = 70
    s.drift_r_full = 42
    s.use_skid = s.use_smoke = True
    s.smoke_amount = 3.0
    s.smoke_life = 3.5
    s.smoke_size = 0.45
    s.smoke_grow = 1.0
    s.smoke_opacity = 0.3
    bake()
    fa = frame_near(body, (-40.0 + 40 * math.cos(math.radians(45)), 150.0 + 40 * math.sin(math.radians(45))), 1, 220)
    a = chase_cam("カメラA_追いかけ", body, 1, 220, dist=11, height=3.0, side=3.0, lens=30, smooth=0.1)
    b = fixed_cam("カメラB_コーナーの内側", (-14.0, 165.0, 0.8), body, 1, 220, lens=30, smooth=0.35)
    finish("ドリフトのスロー", "S2000 ／ テールを流して1コーナーへ。スモークがゆっくり広がる",
           [(a, 1, fa - 25), (b, fa - 24, fa + 30)], (b, fa - 22, fa + 45, 0.3), frame_end=fa + 30, label="SLOW")


def scene_night_sparks():
    """夜のホームストレート。ピットウォールを擦った火花が光の線になる"""
    pick("R32")
    sc.frame_start, sc.frame_end = 1, 200
    C = circuit()
    pts = []
    for q in range(0, 300, 2):
        y = -140.0 + q
        off = 0.0
        if -70.0 < y < 50.0:
            off = 10.15 * math.sin(math.pi * (y + 70.0) / 120.0) ** 2
        pts.append((off, y))
    path = course(join(pts, C["T"].sample(300.0, 380.0, None, 2.0)))
    car_setup(path, C["g"], start_speed=145, top_speed=150)
    s.use_walls = True
    s.wall_collection = bpy.data.collections.get("壁")
    s.use_sparks = True
    s.spark_amount = 3.0
    s.use_smoke = True
    s.smoke_amount = 0.8
    s.smoke_color = (0.5, 0.5, 0.52)
    s.use_dents = True
    bake()
    fh = frame_near(body, (10.0, -10.0), 1, 200)
    headlights(body)
    car_dim([body], [(1, 0.4)])
    a = chase_cam("カメラA_追いかけ", body, 1, 200, dist=10, height=2.6, side=-3.0, lens=30, smooth=0.1)
    b = fixed_cam("カメラB_ピットウォール", (9.4, 25.0, 0.6), body, 1, 200, lens=35, smooth=0.3)
    c = fixed_cam("カメラC_スタンド", (-20.0, -5.0, 9.0), body, 1, 200, lens=38, smooth=0.25)
    r = fixed_cam("カメラR_リプレイ", (-9.0, -2.0, 3.5), body, 1, 200, lens=32, smooth=0.3)
    finish("夜のコースで火花", "R32 ／ 照明の下、ピットウォールを擦った火花が光の線になる",
           [(a, 1, fh - 30), (c, fh - 29, fh + 15), (b, fh + 16, 200)], (r, fh - 22, fh + 22, 0.35),
           light=lambda: light_night(C))


class Batch:
    """たくさんの箱・筒を、材質ごとにまとめて1つのメッシュにする（オブジェクト数を増やさない）"""

    def __init__(self, name):
        self.name, self.v, self.f, self.fm, self.mats = name, [], [], [], []

    def _mi(self, m):
        if m not in self.mats:
            self.mats.append(m)
        return self.mats.index(m)

    def box(self, c, size, m, rot=0.0):
        cr, sr = math.cos(rot), math.sin(rot)
        b = len(self.v)
        for dz in (-0.5, 0.5):
            for dx, dy in ((-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5)):
                x, y = dx * size[0], dy * size[1]
                self.v.append((c[0] + x * cr - y * sr, c[1] + x * sr + y * cr, c[2] + dz * size[2]))
        mi = self._mi(m)
        for q in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
            self.f.append(tuple(b + i for i in q))
            self.fm.append(mi)

    def cyl(self, base, r, h, m, n=8, r2=None):
        r2 = r if r2 is None else r2
        b = len(self.v)
        for k_, (rr, z) in enumerate(((r, base[2]), (r2, base[2] + h))):
            for i in range(n):
                a = 2 * math.pi * i / n
                self.v.append((base[0] + rr * math.cos(a), base[1] + rr * math.sin(a), z))
        mi = self._mi(m)
        for i in range(n):
            j = (i + 1) % n
            self.f.append((b + i, b + j, b + n + j, b + n + i))
            self.fm.append(mi)
        self.f.append(tuple(b + i for i in range(n - 1, -1, -1)))
        self.fm.append(mi)
        if r2 > 0:
            self.f.append(tuple(b + n + i for i in range(n)))
            self.fm.append(mi)

    def build(self):
        if not self.f:
            return None
        o = mesh_obj(self.name, self.v, self.f, self.mats[0])
        for m in self.mats[1:]:
            o.data.materials.append(m)
        for p_, mi in zip(o.data.polygons, self.fm):
            p_.material_index = mi
        return o


def flag_obj(name, pos, size, material, rot=0.0, phase=0.0):
    """旗（細かく分けた板＋波モディファイアーで、時間とともにはためく）"""
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=12, y_subdivisions=6, size=1.0)
    o = bpy.context.object
    o.name = name
    o.scale = (size[0] * K, size[1] * K, 1.0)
    o.rotation_euler = (math.pi / 2, 0, rot)
    o.location = (pos[0] * K + math.cos(rot) * size[0] * 0.5 * K, pos[1] * K + math.sin(rot) * size[0] * 0.5 * K,
                  pos[2] * K)
    o.data.materials.append(material)
    w = o.modifiers.new("はためき", 'WAVE')
    w.use_x, w.use_y = True, False
    w.use_normal = True
    w.height = 0.12
    w.width = 0.5
    w.narrowness = 1.2
    w.speed = 0.18
    w.time_offset = -phase * 10
    w.start_position_x = -0.5
    w.falloff_radius = 0
    return o


def dress_drift_jump(gfn, CX, CY, RR, STR, pts, i0, i1, LIP, RISE, DROP, F):
    """殺風景なコーナーをサーキットらしくする（ランオフ・白線・ガードレール・フェンス・タイヤバリヤ・看板・
    マーシャル・アーチ・観客席の土手・グランドスタンド・ピット棟・タワー・照明塔・旗・テント・木・丘・飛行船・ヘリ）"""
    import random
    rng = random.Random(27)
    deg = lambda s_: math.degrees(s_ / RR)
    P = lambda a, r: (CX + r * math.cos(math.radians(a)), CY + r * math.sin(math.radians(a)))
    arc_pts = pts[i0:i1]
    crest0, crest1 = deg(LIP - RISE) - 2, deg(LIP + DROP) + 2
    # 材質
    MATS.setdefault("ランオフ", mat("ランオフ舗装", (0.2, 0.22, 0.21, 1), 0.75))
    if "フェンス" not in MATS:
        fence = mat("フェンス", (0.12, 0.12, 0.13, 1), 0.5)
        fence.blend_method = 'HASHED'
        if hasattr(fence, "shadow_method"):
            fence.shadow_method = 'NONE'
        next(nd for nd in fence.node_tree.nodes if nd.type == 'BSDF_PRINCIPLED').inputs['Alpha'].default_value = 0.3
        MATS["フェンス"] = fence
    C_ = {k_: mat(k_, c_, r_) for k_, c_, r_ in (
        ("サーキット赤", (0.7, 0.05, 0.04, 1), 0.5), ("サーキット青", (0.05, 0.15, 0.55, 1), 0.5),
        ("サーキット黄", (0.95, 0.7, 0.05, 1), 0.5), ("オレンジ", (1.0, 0.35, 0.03, 1), 0.6),
        ("建物白", (0.82, 0.83, 0.85, 1), 0.7), ("ガラス", (0.05, 0.1, 0.18, 1), 0.08), ("濃灰", (0.12, 0.12, 0.13, 1), 0.6),
        ("幹", (0.25, 0.17, 0.1, 1), 0.9), ("葉1", (0.08, 0.25, 0.08, 1), 0.9), ("葉2", (0.12, 0.3, 0.1, 1), 0.9),
        ("丘", (0.28, 0.4, 0.25, 1), 1.0), ("肌", (0.85, 0.65, 0.5, 1), 0.7))}
    lamp = mat("照明灯", (1.0, 0.97, 0.9, 1), 0.3, emit=3.0)
    crowd = [mat("観客%d" % i, c_, 0.8) for i, c_ in enumerate(
        ((0.7, 0.1, 0.1, 1), (0.1, 0.2, 0.6, 1), (0.9, 0.85, 0.2, 1), (0.9, 0.9, 0.9, 1), (0.15, 0.15, 0.15, 1),
         (0.2, 0.5, 0.2, 1), (0.95, 0.45, 0.1, 1)))]

    # 1. ランオフ（外側は砂利、内側は舗装）  4. 白線
    ribbon(arc_pts, -20, -8, 0.05, gfn, "砂利", "ランオフ（砂利）")
    ribbon(arc_pts, 8, 15, 0.045, gfn, "ランオフ", "ランオフ（舗装）")
    ribbon(pts, 6.5, 6.75, 0.06, gfn, "白", "白線")
    ribbon(pts, -6.75, -6.5, 0.06, gfn, "白", "白線")
    # 2. ガードレールとキャッチフェンス（コーナーの外側と、直線の外側）
    app = line((0, -STR), (0, 0), 2.0)
    ext = line((CX - RR, 0), (CX - RR, -STR), 2.0)
    for seg, off in ((arc_pts, 20.6), (app, 14.0), (ext, 14.0)):
        wall(seg, off, thick=0.25, height=0.8, fn=gfn, material="ガードレール", name="ガードレール")
        wall(seg, off + 0.5, thick=0.04, height=4.0, fn=gfn, material="フェンス", name="キャッチフェンス")
    posts = Batch("フェンスの柱")
    for seg, off, step in ((arc_pts, 21.1, 5), (app, 14.5, 3), (ext, 14.5, 3)):
        for i in range(0, len(seg) - 1, step):
            (x, y), (x2, y2) = seg[i], seg[i + 1]
            tl = math.hypot(x2 - x, y2 - y) or 1.0
            rx, ry = (y2 - y) / tl, -(x2 - x) / tl          # 進行方向の右
            px, py = x + rx * off, y + ry * off
            posts.box((px, py, gfn(px, py) + 2.0), (0.12, 0.12, 4.0), M("ガードレール"))
    posts.build()
    # ピットウォール（直線の内側）
    wall(app, -10.0, thick=0.4, height=1.1, fn=gfn, material="白", name="ピットウォール")
    ribbon(app, 10.4, 19.0, 0.045, gfn, "アスファルト", "ピットレーン")
    # 3. タイヤバリヤ（ヘアピンの出口の外、ガードレールの前）
    barrier(arc(CX, CY, RR + 20.2, 135, 178, 1.0), "LEFT", 1, 3)
    # 5. 距離看板とコーナー番号（直線の右）
    signs = Batch("距離看板")
    for y, txt in ((-100, "100"), (-50, "50"), (-12, "T3")):
        signs.box((16.5, y, 1.1), (0.15, 0.15, 2.2), C_["濃灰"])
        signs.box((16.5, y, 2.6), (1.6, 0.1, 1.1), C_["建物白"] if txt != "T3" else C_["サーキット黄"])
        label_obj(txt, (16.5, y - 0.07, 2.6), 0.75)
    signs.build()
    # 7. クレストの上のスポンサーアーチ
    ag = deg(LIP - 12)
    arch = Batch("スポンサーアーチ")
    road_z = gfn(*P(ag, RR))
    for r_ in (RR - 10.8, RR + 10.8):
        x, y = P(ag, r_)
        arch.box((x, y, (road_z + 9.5) / 2), (0.8, 0.8, road_z + 9.5), C_["建物白"], math.radians(ag))
    cx_, cy_ = P(ag, RR)
    arch.box((cx_, cy_, road_z + 8.4), (22.4, 1.0, 2.2), C_["サーキット赤"], math.radians(ag))
    arch.build()
    tang = math.radians(ag)
    for sgn in (-1, 1):
        label_obj("INKRACER", (cx_ + math.sin(tang) * 0.55 * sgn, cy_ - math.cos(tang) * 0.55 * sgn,
                               road_z + 8.4), 1.5, rot=(math.pi / 2, 0, tang + (0 if sgn > 0 else math.pi)),
                  color=(0.95, 0.95, 0.95, 1))
    # 6. マーシャルポスト（クレストの外、ガードレールの後ろ）
    mp = Batch("マーシャルポスト")
    am = deg(LIP - 30)
    mx, my = P(am, RR + 25)
    for dx, dy in ((-1.2, -1.2), (1.2, -1.2), (1.2, 1.2), (-1.2, 1.2)):
        mp.box((mx + dx, my + dy, 0.9), (0.15, 0.15, 1.8), C_["濃灰"])
    mp.box((mx, my, 1.9), (3.2, 3.2, 0.25), C_["濃灰"])
    mp.box((mx, my, 3.2), (2.6, 2.6, 2.3), C_["オレンジ"])
    mp.box((mx, my, 4.5), (3.2, 3.2, 0.25), C_["建物白"])
    fx, fy = P(am, RR + 22.6)
    mp.cyl((fx, fy, 2.05), 0.22, 1.1, C_["オレンジ"])
    mp.cyl((fx, fy, 3.15), 0.14, 0.28, C_["肌"])
    mp.cyl((fx + 0.35, fy, 2.6), 0.025, 2.0, C_["濃灰"], n=6)
    mp.build()
    flag_obj("マーシャルの旗", (fx + 0.35, fy, 4.3), (1.0, 0.7), C_["サーキット黄"], math.radians(am + 90))
    # 8. 観客の土手と柵（クレストの内側）
    bank = Batch("観客の土手")
    people = Batch("観客")
    a = crest0 - 6
    while a < crest1 + 4:
        for t_ in range(4):
            r_ = RR - 15 - 3.2 * t_
            x, y = P(a, r_)
            h = 0.5 + 0.55 * t_
            bank.box((x, y, h / 2), (3.3 * r_ / RR + 0.4, 3.2, h), M("コンクリート"), math.radians(a) + math.pi / 2)
            for k_ in range(3):
                if rng.random() < 0.75:
                    pa = a + (k_ - 1) * 0.55 + rng.uniform(-0.1, 0.1)
                    px, py = P(pa, r_ + rng.uniform(-0.6, 0.6))
                    people.cyl((px, py, h), 0.21, 1.0 + rng.uniform(-0.12, 0.1), rng.choice(crowd), n=6)
                    people.cyl((px, py, h + 1.05), 0.12, 0.24, C_["肌"], n=6)
        a += 1.6
    bank.build()
    people.build()
    fence_pts = arc(CX, CY, RR - 13.0, crest0 - 6, crest1 + 4, 2.0)
    wall(fence_pts, 0.0, thick=0.04, height=2.2, fn=None, material="フェンス", name="観客の柵")
    # 9. グランドスタンド（ヘアピンの内側、コースを向く）
    gs = Batch("グランドスタンド")
    seat_m = [C_["サーキット青"], M("コンクリート"), C_["サーキット赤"]]
    a = 112.0
    while a < 150.0:
        for t_ in range(8):
            r_ = RR - 28 - 2.2 * t_
            x, y = P(a, r_)
            h = 1.0 + 0.85 * t_
            gs.box((x, y, h / 2), (2.1 * r_ / RR + 0.2, 2.2, h), seat_m[t_ % 3], math.radians(a) + math.pi / 2)
        a += 1.2
    for a in range(112, 151, 6):
        for r_ in (RR - 26.5, RR - 46):
            x, y = P(a, r_)
            gs.box((x, y, 6.5), (0.5, 0.5, 13.0), C_["建物白"])
    a = 112.0
    while a < 150.0:
        x, y = P(a, RR - 37)
        gs.box((x, y, 13.2), (2.2 * (RR - 37) / RR + 0.3, 22.0, 0.4), C_["建物白"], math.radians(a) + math.pi / 2)
        a += 1.2
    gs.build()
    sp = Batch("観客（スタンド）")
    a = 112.6
    while a < 149.5:
        for t_ in range(8):
            if rng.random() < 0.6:
                r_ = RR - 28 - 2.2 * t_ + 0.3
                px, py = P(a + rng.uniform(-0.25, 0.25), r_)
                h = 1.0 + 0.85 * t_
                sp.cyl((px, py, h), 0.21, 0.9, rng.choice(crowd), n=6)
                sp.cyl((px, py, h + 0.95), 0.12, 0.24, C_["肌"], n=6)
        a += 0.75
    sp.build()
    # 10. ピット棟とコントロールタワー（直線の内側）
    pb = Batch("ピット棟")
    pb.box((-27.0, -55.0, 3.6), (14.0, 82.0, 7.2), C_["建物白"])
    for y in range(-92, -16, 8):
        pb.box((-19.96, y + 4, 2.4), (0.1, 6.0, 4.6), C_["濃灰"])
    pb.box((-27.0, -55.0, 7.45), (15.0, 83.0, 0.5), C_["サーキット赤"])
    pb.box((-27.0, -6.0, 9.0), (7.0, 7.0, 18.0), C_["建物白"])
    pb.box((-27.0, -6.0, 19.6), (8.5, 8.5, 3.2), C_["ガラス"])
    pb.box((-27.0, -6.0, 21.5), (9.5, 9.5, 0.6), C_["サーキット赤"])
    pb.build()
    label_obj("INKRACER CIRCUIT", (-19.4, -55.0, 6.2), 2.6, rot=(math.pi / 2, 0, math.pi / 2), color=(0.7, 0.05, 0.04, 1))
    # 11. 旗竿（ピット棟の屋根）・照明塔・テント
    poles = Batch("旗竿・照明塔")
    fl_m = [C_["サーキット赤"], C_["サーキット青"], C_["サーキット黄"], C_["建物白"]]
    for i, y in enumerate(range(-90, -19, 10)):
        poles.cyl((-21.0, y, 7.7), 0.06, 5.5, C_["濃灰"], n=6)
        flag_obj("旗", (-21.0, y, 12.6), (1.6, 1.0), fl_m[i % 4], math.pi / 2, phase=i * 0.37)
    for a, r_ in ((25, RR + 42), (75, RR + 42), (125, RR + 42), (165, RR + 42), (60, RR - 60)):
        x, y = P(a, r_)
        poles.cyl((x, y, 0), 0.35, 26.0, C_["濃灰"], n=8)
        poles.box((x, y, 26.6), (4.0, 1.2, 2.2), lamp, math.radians(a) + math.pi / 2)
    poles.build()
    tents = Batch("テント")
    for i, a in enumerate((116, 123, 130, 137, 144)):
        x, y = P(a, RR - 55)
        tents.box((x, y, 1.1), (4.0, 4.0, 2.2), C_["建物白"], math.radians(a))
        tents.cyl((x, y, 2.2), 3.0, 1.8, fl_m[i % 3], n=4, r2=0.0)
    tents.build()
    # 13. はためく旗（チェッカー・スポンサー）: 直線の右と、ヘアピンの外
    chk = mat("チェッカー", (1, 1, 1, 1), 0.6)
    nt = chk.node_tree
    tc = nt.nodes.new('ShaderNodeTexChecker')
    tc.inputs['Scale'].default_value = 6.0
    tc.inputs['Color1'].default_value = (0.9, 0.9, 0.9, 1)
    tc.inputs['Color2'].default_value = (0.02, 0.02, 0.02, 1)
    nt.links.new(tc.outputs['Color'], next(nd for nd in nt.nodes if nd.type == 'BSDF_PRINCIPLED').inputs['Base Color'])
    fp = Batch("旗竿（コース脇）")
    for i, (x, y) in enumerate(((17.5, -80), (17.5, -30), P(100, RR + 23), P(140, RR + 23), P(176, RR + 23))):
        fp.cyl((x, y, 0), 0.06, 6.0, C_["濃灰"], n=6)
        flag_obj("コース脇の旗", (x, y, 5.6), (1.8, 1.1), chk if i % 2 == 0 else fl_m[i % 4], math.pi / 2 if x > 0 else 0.0,
                 phase=i * 0.51)
    fp.build()
    # 12. 木の列と遠くの丘
    trees = Batch("木")
    for i in range(240):
        a = rng.uniform(0, 360)
        r_ = rng.uniform(175, 205)
        x, y = CX + r_ * math.cos(math.radians(a)), 10 + r_ * math.sin(math.radians(a))
        if -40 < x < 25 and y < 10:
            continue                                 # 直線の手前は空けておく
        h = rng.uniform(6.0, 12.0)
        trees.cyl((x, y, 0), 0.3, h * 0.35, C_["幹"], n=6)
        trees.cyl((x, y, h * 0.25), h * 0.32, h * 0.75, C_["葉1"] if i % 2 else C_["葉2"], n=7, r2=0.0)
    trees.build()
    for i in range(9):
        a = 40 * i + rng.uniform(-10, 10)
        r_ = rng.uniform(420, 560)
        bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, radius=1.0)
        hill = bpy.context.object
        hill.name = "丘"
        hill.location = ((CX + r_ * math.cos(math.radians(a))) * K, (10 + r_ * math.sin(math.radians(a))) * K, -20 * K)
        hill.scale = (rng.uniform(120, 200) * K, rng.uniform(90, 160) * K, rng.uniform(45, 80) * K)
        hill.rotation_euler = (0, 0, math.radians(a))
        hill.data.materials.append(C_["丘"])
        for p_ in hill.data.polygons:
            p_.use_smooth = True
    # 14. 飛行船とヘリ
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, radius=1.0)
    ship = bpy.context.object
    ship.name = "飛行船"
    ship.scale = (22 * K, 6.5 * K, 6.5 * K)
    ship.data.materials.append(C_["建物白"])
    for p_ in ship.data.polygons:
        p_.use_smooth = True
    band = Batch("飛行船の帯とヒレ")
    band.cyl((0, 0, -0.04), 1.005, 0.08, C_["サーキット赤"], n=24)
    band.build().parent = ship
    fins = Batch("飛行船のヒレ")
    fins.box((-0.88, 0, 0), (0.2, 0.05, 1.3), C_["サーキット赤"])
    fins.box((-0.88, 0, 0), (0.2, 1.3, 0.05), C_["サーキット赤"])
    fins.build().parent = ship
    p0, p1 = Vector(P(95, RR + 160)) * K, Vector(P(150, RR + 175)) * K
    for f_, p_ in ((1, p0), (F, p1)):
        ship.location = (p_.x, p_.y, 85 * K)
        ship.rotation_euler = (0, 0, math.atan2(p1.y - p0.y, p1.x - p0.x))
        ship.keyframe_insert("location", frame=f_)
    for fc in ship.animation_data.action.fcurves:
        for kp in fc.keyframe_points:
            kp.interpolation = 'LINEAR'
    hb = Batch("ヘリ")
    hb.box((0, 0, 0), (4.2, 1.6, 1.7), C_["サーキット青"])
    hb.box((-3.6, 0, 0.3), (3.6, 0.35, 0.35), C_["サーキット青"])
    hb.box((-5.3, 0.2, 0.9), (0.6, 0.08, 1.4), C_["サーキット青"])
    hb.box((1.5, 0, 0.25), (1.1, 1.5, 1.0), C_["ガラス"])
    for sy in (-0.8, 0.8):
        hb.box((0, sy, -1.1), (3.6, 0.1, 0.1), C_["濃灰"])
    heli = hb.build()
    rotor = Batch("ヘリのローター")
    rotor.box((0, 0, 0), (11.0, 0.35, 0.06), C_["濃灰"])
    rotor.box((0, 0, 0), (0.35, 11.0, 0.06), C_["濃灰"])
    rot_o = rotor.build()
    rot_o.parent = heli
    rot_o.location = (0, 0, 1.05 * K)
    ac = math.radians(deg(LIP))
    hc = Vector(P(deg(LIP), RR + 70))
    for f_ in range(1, F + 1, 4):
        th = ac + math.radians(25) * math.sin(f_ / F * math.pi * 2) - math.pi / 2
        pos = hc + Vector((math.cos(th), math.sin(th))) * 40
        heli.location = (pos.x * K, pos.y * K, 32 * K)
        heli.rotation_euler = (0, math.radians(-4), th + math.pi / 2)
        heli.keyframe_insert("location", frame=f_)
        heli.keyframe_insert("rotation_euler", frame=f_)
    rot_o.rotation_euler = (0, 0, 0)
    rot_o.keyframe_insert("rotation_euler", index=2, frame=1)
    rot_o.rotation_euler = (0, 0, math.radians(37 * (F - 1)))
    rot_o.keyframe_insert("rotation_euler", index=2, frame=F)
    for fc in rot_o.animation_data.action.fcurves:
        for kp in fc.keyframe_points:
            kp.interpolation = 'LINEAR'


def circuit_mats():
    """サーキットの飾りで使う材質（1回だけ作る）"""
    if "_circuit" in MATS:
        return MATS["_circuit"]
    C_ = {k_: mat(k_, c_, r_) for k_, c_, r_ in (
        ("サーキット赤", (0.7, 0.05, 0.04, 1), 0.5), ("サーキット青", (0.05, 0.15, 0.55, 1), 0.5),
        ("サーキット黄", (0.95, 0.7, 0.05, 1), 0.5), ("オレンジ", (1.0, 0.35, 0.03, 1), 0.6),
        ("建物白", (0.82, 0.83, 0.85, 1), 0.7), ("ガラス", (0.05, 0.1, 0.18, 1), 0.08), ("濃灰", (0.12, 0.12, 0.13, 1), 0.6),
        ("幹", (0.25, 0.17, 0.1, 1), 0.9), ("葉1", (0.08, 0.25, 0.08, 1), 0.9), ("葉2", (0.12, 0.3, 0.1, 1), 0.9),
        ("丘", (0.28, 0.4, 0.25, 1), 1.0), ("肌", (0.85, 0.65, 0.5, 1), 0.7))}
    C_["照明灯"] = mat("照明灯", (1.0, 0.97, 0.9, 1), 0.3, emit=3.0)
    C_["観客"] = [mat("観客%d" % i, c_, 0.8) for i, c_ in enumerate(
        ((0.7, 0.1, 0.1, 1), (0.1, 0.2, 0.6, 1), (0.9, 0.85, 0.2, 1), (0.9, 0.9, 0.9, 1), (0.15, 0.15, 0.15, 1),
         (0.2, 0.5, 0.2, 1), (0.95, 0.45, 0.1, 1)))]
    chk = mat("チェッカー", (1, 1, 1, 1), 0.6)
    nt = chk.node_tree
    tc = nt.nodes.new('ShaderNodeTexChecker')
    tc.inputs['Scale'].default_value = 6.0
    tc.inputs['Color1'].default_value = (0.9, 0.9, 0.9, 1)
    tc.inputs['Color2'].default_value = (0.02, 0.02, 0.02, 1)
    nt.links.new(tc.outputs['Color'], next(nd for nd in nt.nodes if nd.type == 'BSDF_PRINCIPLED').inputs['Base Color'])
    C_["チェッカー"] = chk
    MATS.setdefault("ランオフ", mat("ランオフ舗装", (0.2, 0.22, 0.21, 1), 0.75))
    if "フェンス" not in MATS:
        fence = mat("フェンス", (0.12, 0.12, 0.13, 1), 0.5)
        fence.blend_method = 'HASHED'
        if hasattr(fence, "shadow_method"):
            fence.shadow_method = 'NONE'
        next(nd for nd in fence.node_tree.nodes if nd.type == 'BSDF_PRINCIPLED').inputs['Alpha'].default_value = 0.3
        MATS["フェンス"] = fence
    MATS["_circuit"] = C_
    return C_


def car_tracks(bodies, f0, f1, step=2):
    """焼き込んだ車の通り道（x, y）。飾りが車の通り道にかからないようにするため"""
    out = []
    for f in range(f0, f1 + 1, step):
        sc.frame_set(f)
        for b_ in bodies:
            p_ = b_.matrix_world.translation
            out.append((p_.x / K, p_.y / K))
    sc.frame_set(f0)
    return out


def dress_generic(path_pts, road_w, fn=None, tracks=(), event=None, F=240, ground_c=(0, 0), ground_size=360,
                  guard=True, white=True, runoff=True, arch=True, stand=True, pit=True, seed=1, avoid=()):
    """どのコースにも使えるサーキットの飾り。path_pts: [(x, y)] の中心線。road_w: 中心線から路肩までの幅。
    tracks: 車の通り道（ここには何も置かない）。event: 見せ場の位置 (x, y)。avoid: [(x, y, 半径)] 置かない場所"""
    import random
    rng = random.Random(seed)
    C_ = circuit_mats()
    H = fn or (lambda x, y: 0.0)
    deco = bpy.data.collections.get("サーキットの飾り") or bpy.data.collections.new("サーキットの飾り")
    if deco.name not in sc.collection.children:
        sc.collection.children.link(deco)
    P = path_pts
    n = len(P)
    S = [0.0]
    for i in range(1, n):
        S.append(S[-1] + math.dist(P[i - 1], P[i]))
    T = []
    for i in range(n):
        a_, b_ = P[max(i - 1, 0)], P[min(i + 1, n - 1)]
        tl = math.hypot(b_[0] - a_[0], b_[1] - a_[1]) or 1.0
        T.append(((b_[0] - a_[0]) / tl, (b_[1] - a_[1]) / tl))
    RN = [(t[1], -t[0]) for t in T]                         # 進行方向の右
    occupied = [tuple(a_) for a_ in avoid]
    road_xy = P[::2]
    trk = list(tracks)[::3]

    def free(x, y, r):
        if any((x - px) ** 2 + (y - py) ** 2 < (road_w + r) ** 2 for px, py in road_xy):
            return False
        if any((x - px) ** 2 + (y - py) ** 2 < (r + 3.5) ** 2 for px, py in trk):
            return False
        return not any((x - ox) ** 2 + (y - oy) ** 2 < (r + orr) ** 2 for ox, oy, orr in occupied)

    def off(i, o):
        return P[i][0] + RN[i][0] * o, P[i][1] + RN[i][1] * o

    # 曲率（左曲がりが +）
    head = [math.atan2(t[1], t[0]) for t in T]
    curv = []
    for i in range(n):
        j0, j1 = max(i - 4, 0), min(i + 4, n - 1)
        dh = (head[j1] - head[j0] + math.pi) % (2 * math.pi) - math.pi
        curv.append(dh / max(S[j1] - S[j0], 1e-3))
    corner = [abs(c_) > 1 / 160 for c_ in curv]

    def runs(flags):
        out, i = [], 0
        while i < n:
            if flags[i]:
                j = i
                while j + 1 < n and flags[j + 1]:
                    j += 1
                out.append((i, j))
                i = j + 1
            else:
                i += 1
        return out

    def ribbon_side(i0, i1, side, a, b, z, material, name):
        seg = P[max(i0 - 1, 0):min(i1 + 2, n)]
        if len(seg) < 2:
            return
        if side > 0:
            ribbon(seg, -b, -a, z, fn, material, name)
        else:
            ribbon(seg, a, b, z, fn, material, name)

    # 白線
    if white:
        ribbon(P, road_w - 0.45, road_w - 0.2, 0.06, fn, "白", "白線")
        ribbon(P, -(road_w - 0.2), -(road_w - 0.45), 0.06, fn, "白", "白線")
    # ランオフ（コーナーの外は砂利、内は舗装）
    if runoff:
        for i0, i1 in runs(corner):
            if S[i1] - S[i0] < 8:
                continue
            side = 1 if sum(curv[i0:i1 + 1]) > 0 else -1     # 左曲がりなら外は右
            ribbon_side(i0, i1, side, road_w + 1.5, road_w + 13, 0.05, "砂利", "ランオフ（砂利）")
    # ガードレールとキャッチフェンス（車の通り道・ほかの物にかかる所は切る）
    if guard:
        for side in (-1, 1):
            o_ = road_w + 14.5
            ok = []
            for i in range(n):
                x, y = off(i, side * o_)
                ok.append(not any((x - px) ** 2 + (y - py) ** 2 < 4.0 ** 2 for px, py in trk)
                          and not any((x - ox) ** 2 + (y - oy) ** 2 < (orr + 1.0) ** 2 for ox, oy, orr in occupied))
            posts = Batch("フェンスの柱")
            for i0, i1 in runs(ok):
                seg = P[i0:i1 + 1]
                if len(seg) < 3:
                    continue
                wall(seg, side * o_, thick=0.25, height=0.8, fn=fn, material="ガードレール", coll=deco, name="ガードレール")
                wall(seg, side * (o_ + 0.5), thick=0.04, height=4.0, fn=fn, material="フェンス", coll=deco,
                     name="キャッチフェンス")
                last = -99.0
                for i in range(i0, i1 + 1):
                    if S[i] - last >= 5.0:
                        x, y = off(i, side * (o_ + 0.5))
                        posts.box((x, y, H(x, y) + 2.0), (0.12, 0.12, 4.0), M("ガードレール"))
                        last = S[i]
            posts.build()
    # 距離看板とコーナー番号（最初のコーナーの手前、外側）
    cr = [r_ for r_ in runs(corner) if S[r_[1]] - S[r_[0]] >= 8]
    if cr:
        ci = cr[0][0]
        side = 1 if sum(curv[cr[0][0]:cr[0][1] + 1]) > 0 else -1
        sg = Batch("距離看板")
        for dist_, txt in ((100, "100"), (50, "50"), (12, "T1")):
            s_t = S[ci] - dist_
            if s_t < 0:
                continue
            i = min(range(n), key=lambda k_: abs(S[k_] - s_t))
            x, y = off(i, side * (road_w + 9.5))
            if not free(x, y, 1.0):
                continue
            ang = math.atan2(T[i][1], T[i][0])
            z = H(x, y)
            sg.box((x, y, z + 1.1), (0.15, 0.15, 2.2), C_["濃灰"])
            sg.box((x, y, z + 2.6), (1.6, 0.1, 1.1), C_["サーキット黄"] if txt[0] == "T" else C_["建物白"], ang - math.pi / 2)
            label_obj(txt, (x - T[i][0] * 0.07, y - T[i][1] * 0.07, z + 2.6), 0.75, rot=(math.pi / 2, 0, ang - math.pi / 2))
            occupied.append((x, y, 1.5))
        sg.build()
    ev_i = min(range(n), key=lambda k_: math.dist(P[k_], event)) if event else n // 2
    # スポンサーアーチ（見せ場の 60 m 手前）
    if arch:
        s_a = max(S[ev_i] - 60.0, S[0] + 20)
        ia = min(range(n), key=lambda k_: abs(S[k_] - s_a))
        ang = math.atan2(T[ia][1], T[ia][0])
        rz = H(*P[ia])
        ab = Batch("スポンサーアーチ")
        for sd in (-1, 1):
            x, y = off(ia, sd * (road_w + 3.5))
            ab.box((x, y, (rz + 9.5) / 2), (0.8, 0.8, rz + 9.5), C_["建物白"])
            occupied.append((x, y, 1.0))
        cx_, cy_ = P[ia]
        ab.box((cx_, cy_, rz + 8.4), (2 * road_w + 8.4, 1.0, 2.2), C_["サーキット赤"], ang - math.pi / 2)
        ab.build()
        for sd in (1, -1):
            nx_, ny_ = -T[ia][0] * sd, -T[ia][1] * sd
            label_obj("INKRACER", (cx_ + nx_ * 0.55, cy_ + ny_ * 0.55, rz + 8.4), 1.5,
                      rot=(math.pi / 2, 0, math.atan2(ny_, nx_) + math.pi / 2), color=(0.95, 0.95, 0.95, 1))
    # マーシャルポストと観客の土手（見せ場の近く。置ける側を探す）
    def place_along(center_i, length, o0, o1, rad):
        for side in (1, -1):
            for shift in (0, 30, -30, 60, -60):
                sc_ = S[center_i] + shift
                idx = [k_ for k_ in range(n) if abs(S[k_] - sc_) <= length / 2]
                if len(idx) < 4:
                    continue
                good = all(free(*off(k_, side * o_), rad) for k_ in idx[::2] for o_ in (o0, (o0 + o1) / 2, o1))
                if good:
                    return side, idx
        return None, []
    side_m, idx_m = place_along(ev_i, 6, road_w + 22, road_w + 26, 2.5)
    if side_m:
        k_ = idx_m[len(idx_m) // 2]
        mx, my = off(k_, side_m * (road_w + 24))
        mz = H(mx, my)
        mp = Batch("マーシャルポスト")
        for dx, dy in ((-1.2, -1.2), (1.2, -1.2), (1.2, 1.2), (-1.2, 1.2)):
            mp.box((mx + dx, my + dy, mz + 0.9), (0.15, 0.15, 1.8), C_["濃灰"])
        mp.box((mx, my, mz + 1.9), (3.2, 3.2, 0.25), C_["濃灰"])
        mp.box((mx, my, mz + 3.2), (2.6, 2.6, 2.3), C_["オレンジ"])
        mp.box((mx, my, mz + 4.5), (3.2, 3.2, 0.25), C_["建物白"])
        fx, fy = off(k_, side_m * (road_w + 21.6))
        mp.cyl((fx, fy, mz + 2.05), 0.22, 1.1, C_["オレンジ"])
        mp.cyl((fx, fy, mz + 3.15), 0.14, 0.28, C_["肌"])
        mp.cyl((fx, fy, mz + 2.6), 0.025, 2.0, C_["濃灰"], n=6)
        mp.build()
        flag_obj("マーシャルの旗", (fx, fy, mz + 4.3), (1.0, 0.7), C_["サーキット黄"], math.atan2(T[k_][1], T[k_][0]))
        occupied.append((mx, my, 3.0))
    side_b, idx_b = place_along(ev_i, 70, road_w + 17, road_w + 30, 2.0)
    if side_b:
        bank, ppl = Batch("観客の土手"), Batch("観客")
        for k_ in idx_b[::3]:
            ang = math.atan2(T[k_][1], T[k_][0])
            for t_ in range(4):
                x, y = off(k_, side_b * (road_w + 18 + 3.2 * t_))
                z = H(x, y)
                h = 0.5 + 0.55 * t_
                bank.box((x, y, z + h / 2), (3.3, 3.2, h), M("コンクリート"), ang)
                for _ in range(3):
                    if rng.random() < 0.75:
                        px, py = x + T[k_][0] * rng.uniform(-1.4, 1.4), y + T[k_][1] * rng.uniform(-1.4, 1.4)
                        ppl.cyl((px, py, z + h), 0.21, 1.0 + rng.uniform(-0.12, 0.1), rng.choice(C_["観客"]), n=6)
                        ppl.cyl((px, py, z + h + 1.05), 0.12, 0.24, C_["肌"], n=6)
            occupied.append((*off(k_, side_b * (road_w + 23)), 8.0))
        bank.build()
        ppl.build()
        fp = [off(k_, side_b * (road_w + 16)) for k_ in idx_b]
        wall(fp, 0.0, thick=0.04, height=2.2, fn=fn, material="フェンス", coll=deco, name="観客の柵")
    # グランドスタンド（いちばん長い直線）とピット棟（別の直線、反対側）
    straights = sorted([r_ for r_ in runs([not c_ for c_ in corner]) if S[r_[1]] - S[r_[0]] > 60],
                       key=lambda r_: -(S[r_[1]] - S[r_[0]]))
    used_side = 0
    if stand and straights:
        i0, i1 = straights[0]
        mid = (i0 + i1) // 2
        sd, idx = place_along(mid, 60, road_w + 24, road_w + 44, 3.0)
        if sd:
            gs, spp = Batch("グランドスタンド"), Batch("観客（スタンド）")
            seat_m = [C_["サーキット青"], M("コンクリート"), C_["サーキット赤"]]
            for k_ in idx[::2]:
                ang = math.atan2(T[k_][1], T[k_][0])
                for t_ in range(8):
                    x, y = off(k_, sd * (road_w + 25 + 2.2 * t_))
                    z = H(x, y)
                    h = 1.0 + 0.85 * t_
                    gs.box((x, y, z + h / 2), (2.3, 2.2, h), seat_m[t_ % 3], ang)
                    if rng.random() < 0.6:
                        spp.cyl((x, y, z + h), 0.21, 0.9, rng.choice(C_["観客"]), n=6)
                        spp.cyl((x, y, z + h + 0.95), 0.12, 0.24, C_["肌"], n=6)
                x, y = off(k_, sd * (road_w + 33))
                gs.box((x, y, H(x, y) + 13.2), (2.3, 22.0, 0.4), C_["建物白"], ang)
                occupied.append((x, y, 12.0))
            for k_ in idx[::12]:
                for o_ in (road_w + 23.5, road_w + 43):
                    x, y = off(k_, sd * o_)
                    gs.box((x, y, H(x, y) + 6.5), (0.5, 0.5, 13.0), C_["建物白"])
            gs.build()
            spp.build()
            tents = Batch("テント")
            for j_, k_ in enumerate(idx[2::12]):
                x, y = off(k_, sd * (road_w + 52))
                if free(x, y, 3.0):
                    tents.box((x, y, H(x, y) + 1.1), (4.0, 4.0, 2.2), C_["建物白"])
                    tents.cyl((x, y, H(x, y) + 2.2), 3.0, 1.8, [C_["サーキット赤"], C_["サーキット青"], C_["サーキット黄"]][j_ % 3],
                              n=4, r2=0.0)
                    occupied.append((x, y, 3.5))
            tents.build()
            used_side = sd
    if pit and straights:
        cand = straights[1:] + straights[:1]
        for i0, i1 in cand:
            mid = (i0 + i1) // 2
            sd, idx = place_along(mid, 70, road_w + 16, road_w + 32, 3.0)
            if not sd:
                continue
            pb = Batch("ピット棟")
            k0, k1 = idx[0], idx[-1]
            ang = math.atan2(T[mid][1], T[mid][0])
            x, y = off(mid, sd * (road_w + 24))
            z = H(x, y)
            ln = S[k1] - S[k0]
            pb.box((x, y, z + 3.6), (ln, 14.0, 7.2), C_["建物白"], ang)
            pb.box((x, y, z + 7.45), (ln + 1, 15.0, 0.5), C_["サーキット赤"], ang)
            for k_ in idx[::4]:
                gx, gy = off(k_, sd * (road_w + 16.9))
                pb.box((gx, gy, z + 2.4), (6.0, 0.1, 4.6), C_["濃灰"], math.atan2(T[k_][1], T[k_][0]))
            tx, ty = off(k1, sd * (road_w + 24))
            tx, ty = tx + T[k1][0] * 8, ty + T[k1][1] * 8
            pb.box((tx, ty, z + 9.0), (7.0, 7.0, 18.0), C_["建物白"], ang)
            pb.box((tx, ty, z + 19.6), (8.5, 8.5, 3.2), C_["ガラス"], ang)
            pb.box((tx, ty, z + 21.5), (9.5, 9.5, 0.6), C_["サーキット赤"], ang)
            pb.build()
            occupied.append((x, y, ln / 2 + 8))
            fx, fy = off(mid, sd * (road_w + 16.3))
            label_obj("INKRACER CIRCUIT", (fx, fy, z + 6.2), 2.6,
                      rot=(math.pi / 2, 0, ang + (math.pi if sd > 0 else 0.0)), color=(0.7, 0.05, 0.04, 1))
            poles = Batch("旗竿（ピット）")
            fl_m = [C_["サーキット赤"], C_["サーキット青"], C_["サーキット黄"], C_["建物白"]]
            for j_, k_ in enumerate(idx[2::6]):
                px, py = off(k_, sd * (road_w + 18))
                poles.cyl((px, py, z + 7.7), 0.06, 5.5, C_["濃灰"], n=6)
                flag_obj("旗", (px, py, z + 12.6), (1.6, 1.0), fl_m[j_ % 4], ang, phase=j_ * 0.37)
            poles.build()
            break
    # 照明塔
    lt = Batch("照明塔")
    for j_ in range(6):
        k_ = int((j_ + 0.5) / 6 * (n - 1))
        for sd in ((1, -1) if j_ % 2 else (-1, 1)):
            x, y = off(k_, sd * (road_w + 30))
            if free(x, y, 3.0):
                lt.cyl((x, y, H(x, y)), 0.35, 26.0, C_["濃灰"], n=8)
                lt.box((x, y, H(x, y) + 26.6), (4.0, 1.2, 2.2), C_["照明灯"], math.atan2(T[k_][1], T[k_][0]))
                occupied.append((x, y, 2.0))
                break
    lt.build()
    # コース脇のはためく旗
    fpo = Batch("旗竿（コース脇）")
    for j_ in range(5):
        k_ = int((j_ + 0.3) / 5 * (n - 1))
        for sd in (1, -1):
            x, y = off(k_, sd * (road_w + 11))
            if free(x, y, 1.0):
                fpo.cyl((x, y, H(x, y)), 0.06, 6.0, C_["濃灰"], n=6)
                flag_obj("コース脇の旗", (x, y, H(x, y) + 5.6), (1.8, 1.1),
                         C_["チェッカー"] if j_ % 2 == 0 else [C_["サーキット赤"], C_["サーキット青"]][j_ % 2],
                         math.atan2(T[k_][1], T[k_][0]), phase=j_ * 0.51)
                break
    fpo.build()
    # 木と遠くの丘
    trees = Batch("木")
    gx0, gy0 = ground_c
    half = ground_size / 2 - 5
    placed = 0
    for _ in range(3000):
        if placed >= 260:
            break
        x, y = gx0 + rng.uniform(-half, half), gy0 + rng.uniform(-half, half)
        if not free(x, y, 30.0):
            continue
        h = rng.uniform(6.0, 12.0)
        z = H(x, y)
        trees.cyl((x, y, z), 0.3, h * 0.35, C_["幹"], n=6)
        trees.cyl((x, y, z + h * 0.25), h * 0.32, h * 0.75, C_["葉1"] if placed % 2 else C_["葉2"], n=7, r2=0.0)
        placed += 1
    trees.build()
    for j_ in range(9):
        a = 40 * j_ + rng.uniform(-10, 10)
        r_ = ground_size * 0.5 + rng.uniform(150, 280)
        bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, radius=1.0)
        hill = bpy.context.object
        hill.name = "丘"
        hill.location = ((gx0 + r_ * math.cos(math.radians(a))) * K, (gy0 + r_ * math.sin(math.radians(a))) * K, -20 * K)
        hill.scale = (rng.uniform(120, 200) * K, rng.uniform(90, 160) * K, rng.uniform(45, 80) * K)
        hill.rotation_euler = (0, 0, math.radians(a))
        hill.data.materials.append(C_["丘"])
        for p_ in hill.data.polygons:
            p_.use_smooth = True
    # 飛行船とヘリ（見せ場の上空）
    ex, ey = event if event else P[n // 2]
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, radius=1.0)
    ship = bpy.context.object
    ship.name = "飛行船"
    ship.scale = (22 * K, 6.5 * K, 6.5 * K)
    ship.data.materials.append(C_["建物白"])
    for p_ in ship.data.polygons:
        p_.use_smooth = True
    bd = Batch("飛行船の帯とヒレ")
    bd.cyl((0, 0, -0.04), 1.005, 0.08, C_["サーキット赤"], n=24)
    bd.box((-0.88, 0, 0), (0.2, 0.05, 1.3), C_["サーキット赤"])
    bd.box((-0.88, 0, 0), (0.2, 1.3, 0.05), C_["サーキット赤"])
    bd.build().parent = ship
    a0 = rng.uniform(0, 2 * math.pi)
    p0 = Vector((ex + 150 * math.cos(a0), ey + 150 * math.sin(a0))) * K
    p1 = Vector((ex + 150 * math.cos(a0 + 0.6), ey + 150 * math.sin(a0 + 0.6))) * K
    for f_, p_ in ((1, p0), (F, p1)):
        ship.location = (p_.x, p_.y, 85 * K)
        ship.rotation_euler = (0, 0, math.atan2(p1.y - p0.y, p1.x - p0.x))
        ship.keyframe_insert("location", frame=f_)
    for fc in ship.animation_data.action.fcurves:
        for kp in fc.keyframe_points:
            kp.interpolation = 'LINEAR'
    hb = Batch("ヘリ")
    hb.box((0, 0, 0), (4.2, 1.6, 1.7), C_["サーキット青"])
    hb.box((-3.6, 0, 0.3), (3.6, 0.35, 0.35), C_["サーキット青"])
    hb.box((-5.3, 0.2, 0.9), (0.6, 0.08, 1.4), C_["サーキット青"])
    hb.box((1.5, 0, 0.25), (1.1, 1.5, 1.0), C_["ガラス"])
    for sy in (-0.8, 0.8):
        hb.box((0, sy, -1.1), (3.6, 0.1, 0.1), C_["濃灰"])
    heli = hb.build()
    rotor = Batch("ヘリのローター")
    rotor.box((0, 0, 0), (11.0, 0.35, 0.06), C_["濃灰"])
    rotor.box((0, 0, 0), (0.35, 11.0, 0.06), C_["濃灰"])
    rot_o = rotor.build()
    rot_o.parent = heli
    rot_o.location = (0, 0, 1.05 * K)
    for f_ in range(1, F + 1, 4):
        th = a0 + math.pi + 0.5 * math.sin(f_ / F * math.pi * 2)
        heli.location = ((ex + 70 * math.cos(th)) * K, (ey + 70 * math.sin(th)) * K, 32 * K)
        heli.rotation_euler = (0, math.radians(-4), th + math.pi / 2)
        heli.keyframe_insert("location", frame=f_)
        heli.keyframe_insert("rotation_euler", frame=f_)
    rot_o.keyframe_insert("rotation_euler", index=2, frame=1)
    rot_o.rotation_euler = (0, 0, math.radians(37 * (F - 1)))
    rot_o.keyframe_insert("rotation_euler", index=2, frame=F)
    for fc in rot_o.animation_data.action.fcurves:
        for kp in fc.keyframe_points:
            kp.interpolation = 'LINEAR'


def scene_drift_jump():
    """2台が近い距離で高速ドリフトしたまま、コーナーの途中のクレストで低く長く飛ぶ"""
    global TERRAIN
    pick("R32")
    F = 250
    sc.frame_start, sc.frame_end = 1, F
    CX, CY, RR = -120.0, 0.0, 120.0            # 左コーナー（反時計回り）。速さ2倍なので半径は約4倍
    LIP_DEG = 70.0
    LIP = math.radians(LIP_DEG) * RR            # コーナー入口からクレストの先端までの距離
    RISE, HGT = 50.0, 2.0                       # 50 m かけて 2 m 上がる（先端の傾き 8%）
    DROP = 30.0                                 # 先端の先は、車の放物線より少し下を通る曲線で 30 m かけて下る
    BAND = 9.0

    def prof(s_):
        if LIP - RISE <= s_ <= LIP:
            u = (s_ - (LIP - RISE)) / RISE
            return HGT * u * u
        if LIP < s_ <= LIP + DROP:
            x = s_ - LIP
            return HGT * (1.0 - (x / DROP) ** 2)
        return 0.0

    def gfn(x, y):
        r = math.hypot(x - CX, y - CY)
        if abs(r - RR) > BAND:
            return 0.0
        a = math.atan2(y - CY, x - CX) % (2 * math.pi)
        side = min(1.0, (BAND - abs(r - RR)) / 1.5)          # 横の端はなだらかに
        return prof(a * RR) * side
    STR = 100.0
    pts = join(line((0, -STR), (0, 0)), arc(CX, CY, RR, 0, 180, 1.0), line((CX - RR, 0), (CX - RR, -STR)))
    TERRAIN = gfn
    g = ground(gfn, 420, (CX, 10), subdiv=420, material="芝")
    ribbon(pts, -7, 7, 0.03, gfn)
    i0 = int(STR / 2.0)
    i1 = i0 + int(math.pi * RR)
    r0, r1 = i0 + int(LIP - RISE) - 3, i0 + int(LIP + DROP) + 3     # クレストの区間には縁石を置かない
    for seg in (pts[i0:r0], pts[r1:i1]):
        kerbs(seg, 7, 8, 3, gfn)
        kerbs(seg, -8, -7, 3, gfn)
    dress_drift_jump(gfn, CX, CY, RR, STR, pts, i0, i1, LIP, RISE, DROP, F)
    path = course(pts, fn=gfn)
    car_setup(path, g, start_speed=125, top_speed=135, lane_offset=1.9)
    s.drive = "RWD"
    s.drift = True
    s.drift_angle = 35
    s.drift_r_start = 220
    s.drift_r_full = 110
    s.rollover_auto = False                     # 着地で傾いても横転させない
    s.use_skid = s.use_smoke = True
    s.smoke_amount = 1.0
    s.use_multi = True
    p2 = course(join(line((0, -STR - 4), (0, -STR)), pts[1:]), "走行ライン2", fn=gfn)
    b2, w2 = dup_car((0, -STR - 4, 0), None, model="TESTA")
    # 外側の車線（半径が大きい）を走るので少し速く、車間は取らずに並んだまま
    add_car(b2, w2, p2, lane_offset=-1.9, speed_mult=1.03, start_speed=127, overtake=False, avoid=False)
    bake()
    lip_xy = (CX + RR * math.cos(math.radians(LIP_DEG)), CY + RR * math.sin(math.radians(LIP_DEG)))
    takeoff = frame_near(body, lip_xy, 1, F)

    def polar(deg, r, z):
        return (CX + r * math.cos(math.radians(deg)), CY + r * math.sin(math.radians(deg)), z)
    a = chase_cam("カメラA_追いかけ", body, 1, F, dist=16, height=4.0, side=-4)
    b = fixed_cam("カメラB_クレスト", polar(LIP_DEG + 7, RR + 16, 3.0), body, 1, F, lens=30, smooth=0.25)
    c = fixed_cam("カメラC_リプレイ", polar(LIP_DEG + 4, RR + 15, 3.2), body, 1, F, lens=26, smooth=0.5)
    finish("2台並んで高速ドリフトのまま低く飛ぶ", "R32 と テスタロッサ ／ 2倍の速さで並んだまま、クレストを低く長く越える",
           [(a, 1, takeoff - 30), (b, takeoff - 29, takeoff + 40), (a, takeoff + 41, F)],
           (c, takeoff - 10, takeoff + 30, 0.4))


SCENES = {
    "27_drift_jump": scene_drift_jump,
    "01_chicane_roll": scene_chicane_roll, "02_spin_barrier": scene_spin_barrier,
    "03_wall_scrape": scene_wall_scrape, "04_multi_crash": scene_multi_crash,
    "05_drift_battle": scene_drift_battle, "06_touge_rail": scene_touge_rail,
    "07_rally_jump": scene_rally_jump, "08_snow_spin": scene_snow_spin,
    "09_puddle_spin": scene_puddle_spin, "10_boxes": scene_boxes,
    "11_pylon": scene_pylon, "12_chase": scene_chase, "13_jump_roll": scene_jump_roll, "14_oval": scene_oval,
    "15_bridge": scene_bridge, "16_drag": scene_drag, "17_gymkhana": scene_gymkhana,
    "18_dawn": scene_dawn, "19_garage": scene_garage, "20_pitlane": scene_pitlane, "21_warmup": scene_warmup,
    "22_side_by_side": scene_side_by_side, "23_kerb_sparks": scene_kerb_sparks, "24_slipstream": scene_slipstream,
    "25_drift_slow": scene_drift_slow, "26_night_sparks": scene_night_sparks,
}
SCENES[SCENE]()

"""カスタム画面風のシーン: ターンテーブルの R32 のホイールとウイングが、BPM140 の8分音符で「ポン、ポン」と替わる

blender -b cars5.blend --python custom_r32.py -- 参考.blend 出力.blend

・8分音符ごと（30fps で約 6.43 フレーム）に、偶数の拍でホイール、奇数の拍でウイングを次のものへ
・替わる瞬間に新しいパーツが 0 → 1.25 → 1 と飛び出し、白いリングがはじける
・ホイール: 純正 / F40 / カウンタック / テスタロッサ / S2000 のホイールを R32 の径に合わせて付け替え
・ウイング: なし / GTウイング / スワンネック / ダックテール / ダブルデッキ / ハイマウント（その場で作る）
・画面: 左上にタイトル、左にパーツ名（替わるたびに飛び出す）、下に8分音符のインジケーター
・空と車のマテリアルは参考ファイル（オリジナルカメラ_前後オーバル）から。30fps・ビュー変換は標準
コレクション: no / 01_car（CAR_R32・ホイール・ウイング）/ 02_back / 03_edit / 04_shape（シェイプ・UI）、camera
"""
import bpy
import bmesh
import math
import os
import sys
from mathutils import Vector, Matrix

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cars5 as C5  # noqa: E402

args = sys.argv[sys.argv.index("--") + 1:]
REF, OUT = args[0], args[1]
REF_SCENE = "オリジナルカメラ_前後オーバル"

FPS = 30
BPM = 140
EIGHTH = FPS * 60.0 / BPM / 2.0          # 8分音符のフレーム数（6.43）
T0 = 16                                  # 最初に替わるフレーム（約0.5秒の頭出し）
N_HITS = 64                              # 8小節ぶん
TAIL = 24
F_END = int(round(T0 + N_HITS * EIGHTH)) + TAIL

WHITE, BLUE, ORANGE, NAVY, CARBON = "#ffffff", "#0034ff", "#ff2200", "#121a3a", "#151824"


def hx(s):
    s = s.lstrip("#")
    c = [int(s[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c) + (1.0,)


def flat(name, col):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    rgb = nt.nodes.new("ShaderNodeRGB")
    rgb.outputs[0].default_value = hx(col)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(rgb.outputs[0], out.inputs["Surface"])
    return m


def hit_frame(i):
    return int(round(T0 + i * EIGHTH))


# ---------------------------------------------------------------- シーンと車
sc = C5.scene()
CARS = C5.setup(sc)
sc.name = "カスタム画面_R32"
sc.render.fps, sc.render.fps_base = FPS, 1.0
sc.frame_start, sc.frame_end = 1, F_END
sc.view_settings.view_transform = 'Standard'
sc.view_settings.look = 'None'
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = 1920, 1080, 100
sc.render.film_transparent = False
C5.place(CARS["R32"], (0, 0, 0))

# 参考ファイルの車のマテリアル（車種ごと・部品ごと）をそのまま写す
sys.argv = [sys.argv[0], "--", REF, OUT, REF_SCENE]
import match_user as MU  # noqa: E402
MU.SRC, MU.SRC_SCENE = REF, REF_SCENE
info = MU.dump_source()
need = sorted({n for d in info["cars"].values() for sl in d.values() for n, _ in sl if n})
with bpy.data.libraries.load(REF, link=False) as (df, dt):
    dt.materials = list(need)
    dt.worlds = [info["world"]]
got = dict(zip(need, dt.materials))
for key, (b, ws) in CARS.items():
    model = {"COUNTACH": "Countach", "TESTA": "Testarossa"}.get(key, key)
    for o in C5.tree((b, ws)):
        if o.type != 'MESH':
            continue
        slots = info["cars"].get(model, {}).get(MU.base(o.name))
        if slots and len(slots) == len(o.material_slots):
            for sl, (mn, link) in zip(o.material_slots, slots):
                if mn and got.get(mn) is not None:
                    sl.link = link
                    sl.material = got[mn]
sc.world = dt.worlds[0]
ee = sc.eevee
for k, v in info["eevee"].items():
    try:
        setattr(ee, k, v)
    except Exception:
        pass
ee.taa_render_samples = max(ee.taa_render_samples, 16)

# ---------------------------------------------------------------- コレクション
root = sc.collection


def col(name, parent):
    c = bpy.data.collections.new(name)
    parent.children.link(c)
    return c


old_cols = list(root.children)
no = col("no", root)
c_car = col("01_car", no)
c_r32 = col("CAR_R32", c_car)
c_wheel = col("ホイール", c_car)
c_wing = col("ウイング", c_car)
c_back = col("02_back", no)
c_edit = col("03_edit", no)
c_shape = col("04_shape", no)
c_shp = col("シェイプ", c_shape)
c_ui = col("UI", c_shape)
c_cam = col("camera", root)


def link(o, c):
    for x in list(o.users_collection):
        x.objects.unlink(o)
    c.objects.link(o)


r32b, r32w = CARS["R32"]
for o in C5.tree(CARS["R32"]):
    link(o, c_r32)

# ---------------------------------------------------------------- ターンテーブル（車はこの上で回る）
table = bpy.data.objects.new("ターンテーブル", None)
c_back.objects.link(table)
r32b.parent = table
for w in r32w:
    w.parent = table
m_table, m_line, m_floor = flat("ターンテーブル", NAVY), flat("ターンテーブルの線", WHITE), flat("床", "#c9d2ff")


def disc(name, r, h, mat, z=0.0, seg=96, parent=None, c=c_back):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=seg, radius1=r, radius2=r, depth=h)
    for v in bm.verts:
        v.co.z += z - h / 2
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    o.data.materials.append(mat)
    c.objects.link(o)
    if parent:
        o.parent = parent
    return o


def ring(name, r, w, h, mat, z=0.0, seg=128, c=c_back, dashes=0, fill=0.6):
    bm = bmesh.new()
    n = seg
    def quad(a0, a1):
        vs = []
        for a in (a0, a1):
            for rr in (r - w / 2, r + w / 2):
                for zz in (z - h, z):
                    vs.append(bm.verts.new((math.cos(a) * rr, math.sin(a) * rr, zz)))
        for f in ((0, 4, 5, 1), (2, 3, 7, 6), (1, 5, 7, 3), (0, 2, 6, 4)):
            bm.faces.new([vs[i] for i in f])
    if dashes:
        for d in range(dashes):
            a0 = 2 * math.pi * d / dashes
            a1 = a0 + 2 * math.pi / dashes * fill
            steps = max(2, int(seg * fill / dashes))
            for s_ in range(steps):
                quad(a0 + (a1 - a0) * s_ / steps, a0 + (a1 - a0) * (s_ + 1) / steps)
    else:
        for k in range(n):
            quad(2 * math.pi * k / n, 2 * math.pi * (k + 1) / n)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    o.data.materials.append(mat)
    c.objects.link(o)
    return o


floor = disc("床", 60.0, 0.02, m_floor, z=-0.16)
top = disc("ターンテーブル_台", 3.8, 0.16, m_table, z=0.0, parent=None)
top.parent = table
for r_ in (3.75, 3.2):
    rg = ring(f"ターンテーブル_線_{r_}", r_, 0.06, 0.005, m_line, z=0.004)
    rg.parent = table
# 03_edit: 台の複製（編集用・隠し）
ed = top.copy()
ed.data = top.data.copy()
ed.name = "ターンテーブル_台_編集用"
c_edit.objects.link(ed)
ed.hide_render = ed.hide_viewport = True
# 台はゆっくり回る（15秒で半周くらい）
table.rotation_euler[2] = math.radians(-215)     # 斜め後ろ（ウイングが見える向き）から
table.keyframe_insert("rotation_euler", index=2, frame=1)
table.rotation_euler[2] = math.radians(-215 + 150)
table.keyframe_insert("rotation_euler", index=2, frame=F_END)
for fc in table.animation_data.action.fcurves:
    for kp in fc.keyframe_points:
        kp.interpolation = 'LINEAR'

# ---------------------------------------------------------------- ホイールの付け替え
def radius(o):
    return o.dimensions.z / 2


WHEEL_SETS = [("純正", "R32"), ("F40 スタイル", "F40"), ("カウンタック スタイル", "COUNTACH"),
              ("テスタロッサ スタイル", "TESTA"), ("S2000 スタイル", "S2000")]
r_r32 = sum(radius(w) for w in r32w) / 4
wheel_groups = []          # [ [4つのホイール], ... ]
for jp, key in WHEEL_SETS:
    if key == "R32":
        grp = list(r32w)
    else:
        src = CARS[key][1]
        grp = []
        for w_src, w_dst in zip(src, r32w):
            w = w_src.copy()
            w.name = f"ホイール_{jp}_{w_dst.name[-2:]}"
            c_wheel.objects.link(w)
            w.hide_render = False
            w.parent = table
            w.matrix_parent_inverse = Matrix.Identity(4)
            s_ = r_r32 / max(1e-3, radius(w_src))
            w.location = w_dst.location.copy()
            w.rotation_euler = (0, 0, 0)
            w.scale = (s_, s_, s_)
            grp.append(w)
    wheel_groups.append((jp, grp))
for o in C5.tree(CARS["R32"]):
    if o in r32w:
        o.parent = table

# ---------------------------------------------------------------- ウイング（その場で作る）
m_carbon, m_plate = flat("ウイング_カーボン", CARBON), flat("ウイング_翼端板", ORANGE)
outline = bpy.data.materials.get("OH_Outline_Material")
dg = bpy.context.evaluated_depsgraph_get()


def deck_z(x, y):
    hit, loc, n_, i_, ob, M = sc.ray_cast(dg, Vector((x, y, 5)), Vector((0, 0, -1)))
    return loc.z if hit else 1.0


Y_MOUNT = -1.95
Z_DECK = deck_z(0, Y_MOUNT)


def boxmesh(bm, c, sx, sy, sz, rot_x=0.0):
    M = Matrix.Translation(c) @ Matrix.Rotation(rot_x, 4, 'X')
    r = bmesh.ops.create_cube(bm, size=1.0, matrix=M @ Matrix.Diagonal((sx, sy, sz, 1)))
    return r


def airfoil(bm, c, span, chord, th, aoa):
    """くさび形の翼（前が厚く後ろが薄い）"""
    M = Matrix.Translation(c) @ Matrix.Rotation(math.radians(aoa), 4, 'X')
    pts = []
    for x in (-span / 2, span / 2):
        ring_ = [(chord * 0.5, 0.0), (chord * 0.25, th * 0.55), (-chord * 0.2, th * 0.5), (-chord * 0.5, th * 0.1),
                 (-chord * 0.5, -th * 0.05), (chord * 0.3, -th * 0.4)]
        pts.append([bm.verts.new(M @ Vector((x, yy, zz))) for yy, zz in ring_])
    a, b = pts
    n = len(a)
    for i in range(n):
        bm.faces.new((a[i], a[(i + 1) % n], b[(i + 1) % n], b[i]))
    bm.faces.new(list(reversed(a)))
    bm.faces.new(b)


def wing_obj(name, build):
    bm_c, bm_p = bmesh.new(), bmesh.new()
    build(bm_c, bm_p)
    root_ = bpy.data.objects.new(f"ウイング_{name}", None)
    c_wing.objects.link(root_)
    root_.parent = table
    root_.location = (0, Y_MOUNT, Z_DECK)
    for bm, mat, suf in ((bm_c, m_carbon, "本体"), (bm_p, m_plate, "翼端板")):
        if not bm.verts:
            bm.free()
            continue
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        for v in bm.verts:
            v.co -= Vector((0, Y_MOUNT, Z_DECK))
        me = bpy.data.meshes.new(f"ウイング_{name}_{suf}")
        bm.to_mesh(me)
        bm.free()
        o = bpy.data.objects.new(f"ウイング_{name}_{suf}", me)
        me.materials.append(mat)
        if outline:
            me.materials.append(outline)
            sd = o.modifiers.new("輪郭", 'SOLIDIFY')
            sd.thickness = 0.012
            sd.offset = 1.0
            sd.use_flip_normals = True
            sd.material_offset = 1
            sd.use_rim = False
        c_wing.objects.link(o)
        o.parent = root_
    return root_


def gt(bc, bp):
    airfoil(bc, Vector((0, Y_MOUNT - 0.05, Z_DECK + 0.30)), 1.62, 0.30, 0.05, -8)
    for x in (-0.42, 0.42):
        boxmesh(bc, Vector((x, Y_MOUNT, Z_DECK + 0.14)), 0.025, 0.16, 0.30)
    for x in (-0.83, 0.83):
        boxmesh(bp, Vector((x, Y_MOUNT - 0.05, Z_DECK + 0.30)), 0.02, 0.38, 0.20)


def swan(bc, bp):
    airfoil(bc, Vector((0, Y_MOUNT - 0.08, Z_DECK + 0.34)), 1.66, 0.32, 0.05, -10)
    for x in (-0.38, 0.38):
        boxmesh(bc, Vector((x, Y_MOUNT + 0.12, Z_DECK + 0.20)), 0.025, 0.06, 0.40)
        boxmesh(bc, Vector((x, Y_MOUNT + 0.02, Z_DECK + 0.41)), 0.025, 0.22, 0.05)
        boxmesh(bc, Vector((x, Y_MOUNT - 0.08, Z_DECK + 0.385)), 0.025, 0.05, 0.06)
    for x in (-0.85, 0.85):
        boxmesh(bp, Vector((x, Y_MOUNT - 0.08, Z_DECK + 0.33)), 0.02, 0.42, 0.24)


def duck(bc, bp):
    bm = bc
    w, y0, y1 = 0.80, Y_MOUNT + 0.05, Y_MOUNT - 0.25
    vs = [bm.verts.new(v) for v in ((-w, y0, Z_DECK + 0.01), (w, y0, Z_DECK + 0.01), (w, y1, Z_DECK + 0.01), (-w, y1, Z_DECK + 0.01),
                                    (-w, y1, Z_DECK + 0.13), (w, y1, Z_DECK + 0.13))]
    bm.faces.new((vs[0], vs[1], vs[5], vs[4]))
    bm.faces.new((vs[3], vs[2], vs[1], vs[0]))
    bm.faces.new((vs[4], vs[5], vs[2], vs[3]))
    bm.faces.new((vs[0], vs[4], vs[3]))
    bm.faces.new((vs[1], vs[2], vs[5]))
    boxmesh(bp, Vector((0, y1 + 0.005, Z_DECK + 0.125)), 1.62, 0.02, 0.02)


def double(bc, bp):
    airfoil(bc, Vector((0, Y_MOUNT - 0.02, Z_DECK + 0.26)), 1.62, 0.30, 0.05, -6)
    airfoil(bc, Vector((0, Y_MOUNT - 0.20, Z_DECK + 0.36)), 1.62, 0.20, 0.035, -16)
    for x in (-0.42, 0.42):
        boxmesh(bc, Vector((x, Y_MOUNT, Z_DECK + 0.12)), 0.025, 0.16, 0.26)
    for x in (-0.83, 0.83):
        boxmesh(bp, Vector((x, Y_MOUNT - 0.10, Z_DECK + 0.30)), 0.02, 0.50, 0.30)


def high(bc, bp):
    airfoil(bc, Vector((0, Y_MOUNT - 0.10, Z_DECK + 0.62)), 1.80, 0.36, 0.06, -9)
    for x in (-0.36, 0.36):
        boxmesh(bc, Vector((x, Y_MOUNT - 0.02, Z_DECK + 0.30)), 0.03, 0.12, 0.62, rot_x=math.radians(-10))
    for x in (-0.92, 0.92):
        boxmesh(bp, Vector((x, Y_MOUNT - 0.10, Z_DECK + 0.60)), 0.02, 0.50, 0.32)


WINGS = [("なし（純正）", None), ("GTウイング", gt), ("スワンネック", swan), ("ダックテール", duck),
         ("ダブルデッキ", double), ("ハイマウント", high)]
wing_roots = []
for jp, fn in WINGS:
    if fn is None:
        e = bpy.data.objects.new("ウイング_なし", None)
        c_wing.objects.link(e)
        e.parent = table
        wing_roots.append((jp, e))
    else:
        wing_roots.append((jp, wing_obj(jp, fn)))

# ---------------------------------------------------------------- 影（ボディの複製をシュリンクラップで台に貼って真っ黒に）
m_black = flat("影_黒", "#000000")
for o in [x for x in r32b.children_recursive if x.type == 'MESH' and not x.hide_render]:
    sh = o.copy()
    sh.data = o.data.copy()
    sh.name = o.name + "_影"
    c_r32.objects.link(sh)
    sh.data.materials.clear()
    sh.data.materials.append(m_black)
    sw = sh.modifiers.new("Shrinkwrap", 'SHRINKWRAP')
    sw.wrap_method = 'TARGET_PROJECT'
    sw.wrap_mode = 'ON_SURFACE'
    sw.offset = 0.012
    sw.target = top
    sh.visible_shadow = False

# ---------------------------------------------------------------- 「ポン」のアニメーション
def set_scale_key(o, f, v, interp='BEZIER'):
    o.scale = v
    o.keyframe_insert("scale", frame=f)
    for fc in o.animation_data.action.fcurves:
        if fc.data_path == "scale":
            for kp in fc.keyframe_points:
                if abs(kp.co.x - f) < 0.01:
                    kp.interpolation = interp


def show(objs, f, base=(1, 1, 1)):
    for o in objs:
        b = Vector(base) if o not in base_scale else base_scale[o]
        set_scale_key(o, f - 1, (0, 0, 0), 'CONSTANT')
        set_scale_key(o, f, b * 0.05)
        set_scale_key(o, f + 1, b * 1.28)
        set_scale_key(o, f + 3, b * 0.94)
        set_scale_key(o, f + 5, b)


def hide(objs, f):
    for o in objs:
        b = base_scale.get(o, Vector((1, 1, 1)))
        set_scale_key(o, f - 1, b, 'CONSTANT')
        set_scale_key(o, f, (0, 0, 0), 'CONSTANT')


base_scale = {}
for jp, grp in wheel_groups:
    for w in grp:
        base_scale[w] = w.scale.copy()
for jp, e in wing_roots:
    base_scale[e] = Vector((1, 1, 1))
# 最初は純正。他は隠しておく
for i, (jp, grp) in enumerate(wheel_groups):
    for w in grp:
        set_scale_key(w, 1, base_scale[w] if i == 0 else (0, 0, 0), 'CONSTANT')
for i, (jp, e) in enumerate(wing_roots):
    set_scale_key(e, 1, (1, 1, 1) if i == 0 else (0, 0, 0), 'CONSTANT')

# はじける白いリング（ホイール4つとウイング1つ。替わるたびに広がって消える）
m_burst = flat("はじけるリング", WHITE)
bursts_w, burst_wing = [], None
for w in r32w:
    b = ring(f"はじけるリング_{w.name[-2:]}", 0.40, 0.025, 0.025, m_burst, c=c_shp)
    b.parent = table
    b.location = w.location.copy()
    b.rotation_euler = (0, math.radians(90), 0)
    set_scale_key(b, 1, (0, 0, 0), 'CONSTANT')
    bursts_w.append(b)
burst_wing = ring("はじけるリング_ウイング", 0.5, 0.03, 0.03, m_burst, c=c_shp)
burst_wing.parent = table
burst_wing.location = (0, Y_MOUNT, Z_DECK + 0.3)
burst_wing.rotation_euler = (math.radians(90), 0, 0)
set_scale_key(burst_wing, 1, (0, 0, 0), 'CONSTANT')


def burst(b, f, big=2.4):
    set_scale_key(b, f - 1, (0, 0, 0), 'CONSTANT')
    set_scale_key(b, f, (0.8, 0.8, 0.8))
    set_scale_key(b, f + 3, (big, big, big * 0.4))
    set_scale_key(b, f + 4, (0, 0, 0), 'CONSTANT')


iw = ig = 0
events = []     # (フレーム, 種類, 名前)
for i in range(N_HITS):
    f = hit_frame(i)
    if i % 2 == 0:
        old = wheel_groups[iw % len(wheel_groups)][1]
        iw += 1
        jp, new = wheel_groups[iw % len(wheel_groups)]
        hide(old, f)
        show(new, f)
        for b in bursts_w:
            burst(b, f, big=1.55)
        events.append((f, "WHEEL", jp))
    else:
        old = wing_roots[ig % len(wing_roots)][1]
        ig += 1
        jp, new = wing_roots[ig % len(wing_roots)]
        hide([old], f)
        show([new], f)
        burst(burst_wing, f, big=2.0)
        events.append((f, "WING", jp))

# ---------------------------------------------------------------- カメラ（拍でぐっと寄る）
rig = bpy.data.objects.new("カメラリグ", None)
c_cam.objects.link(rig)
rig.location = (0, 0, 0.75)
cd = bpy.data.cameras.new("カスタム画面カメラ")
cd.lens = 38
cd.clip_start = 0.05
cam = bpy.data.objects.new("カスタム画面カメラ", cd)
c_cam.objects.link(cam)
cam.parent = rig
sc.camera = cam


def place_cam(f, yaw, dist, h):
    rig.rotation_euler = (0, 0, math.radians(yaw))
    rig.keyframe_insert("rotation_euler", index=2, frame=f)
    eye = Vector((0, -dist, h))
    cam.location = eye
    cam.rotation_euler = (Vector((-1.35, 0, -0.05)) - eye).to_track_quat('-Z', 'Y').to_euler()   # 車を画面の右寄りに
    cam.keyframe_insert("location", frame=f)
    cam.keyframe_insert("rotation_euler", frame=f)


place_cam(1, 18, 8.6, 1.7)
place_cam(F_END, 28, 7.8, 1.45)
# 4分音符ごとに少し前へ押し出す（パンチ）。カメラの子の空の物体ではなく、カメラの「レンズ」は変えない（UI が動かないように）
punch = bpy.data.objects.new("拍のパンチ", None)
c_cam.objects.link(punch)
punch.parent = rig
cam.parent = punch
for q in range(N_HITS // 2):
    f = hit_frame(q * 2)
    for dt, d in ((0, 0.0), (1, 0.18), (5, 0.0)):
        punch.location = (0, 0.18 * (1 if dt == 1 else 0), 0)
        punch.keyframe_insert("location", index=1, frame=f + dt)

# ---------------------------------------------------------------- UI（カメラの子。画面の決まった位置に）
font = None
for fp in ("C:/Windows/Fonts/YuGothB.ttc", "C:/Windows/Fonts/meiryob.ttc", "C:/Windows/Fonts/msgothic.ttc"):
    if os.path.exists(fp):
        try:
            font = bpy.data.fonts.load(fp)
            break
        except Exception:
            pass
m_ui_w, m_ui_b, m_ui_o, m_ui_n = flat("UI_白", WHITE), flat("UI_青", BLUE), flat("UI_橙", ORANGE), flat("UI_紺", NAVY)
DEPTH = 1.0
HALF_W = DEPTH * (cd.sensor_width / 2) / cd.lens
HALF_H = HALF_W * 9 / 16


def ui_pos(x, y, z=0.0):
    """画面の座標 (0..1, 0..1, 左下が 0,0) → カメラの中の位置"""
    return Vector(((x * 2 - 1) * HALF_W, (y * 2 - 1) * HALF_H, -DEPTH + z))


def ui_text(body, x, y, size, mat, align='LEFT', z=0.0):
    cu = bpy.data.curves.new("UI文字", 'FONT')
    cu.body = body
    if font:
        cu.font = font
    cu.size = size * HALF_H * 2
    cu.align_x = align
    cu.align_y = 'CENTER'
    o = bpy.data.objects.new(f"UI_{body[:12]}", cu)
    o.data.materials.append(mat)
    c_ui.objects.link(o)
    o.parent = cam
    o.location = ui_pos(x, y, z + 0.001)
    return o


def ui_rect(name, x0, y0, x1, y1, mat, z=0.0, skew=0.0):
    a, b = ui_pos(x0, y0, z), ui_pos(x1, y1, z)
    sk = skew * HALF_H * 2
    me = bpy.data.meshes.new(name)
    me.from_pydata([(a.x, a.y, a.z), (b.x, a.y, a.z), (b.x + sk, b.y, a.z), (a.x + sk, b.y, a.z)], [], [(0, 1, 2, 3)])
    o = bpy.data.objects.new(name, me)
    me.materials.append(mat)
    c_ui.objects.link(o)
    o.parent = cam
    return o


ui_rect("UI_タイトル帯", 0.03, 0.84, 0.36, 0.95, m_ui_b, skew=0.03)
ui_rect("UI_タイトル線", 0.03, 0.825, 0.42, 0.835, m_ui_o)
ui_text("CUSTOMIZE", 0.05, 0.895, 0.07, m_ui_w)
ui_text("NISSAN SKYLINE GT-R  R32", 0.05, 0.795, 0.034, m_ui_n)
rows = {"WHEEL": 0.62, "WING": 0.47}
labels = {}
for k_, y in rows.items():
    ui_rect(f"UI_{k_}_帯", 0.03, y - 0.06, 0.36, y + 0.06, m_ui_n, skew=0.02)
    ui_rect(f"UI_{k_}_印", 0.03, y - 0.06, 0.045, y + 0.06, m_ui_o)
    ui_text(k_, 0.06, y + 0.028, 0.034, m_ui_o)
# パーツ名（替わるたびに飛び出す）
names = {"WHEEL": [jp for jp, _ in wheel_groups], "WING": [jp for jp, _ in wing_roots]}
name_objs = {k_: [] for k_ in names}
for k_, lst in names.items():
    for j, jp in enumerate(lst):
        o = ui_text(jp, 0.06, rows[k_] - 0.022, 0.056, m_ui_w)
        o.name = f"UI_{k_}_{jp}"
        base_scale[o] = Vector((1, 1, 1))
        set_scale_key(o, 1, (1, 1, 1) if j == 0 else (0, 0, 0), 'CONSTANT')
        name_objs[k_].append(o)
idx = {"WHEEL": 0, "WING": 0}
for f, kind, jp in events:
    lst = name_objs[kind]
    old = lst[idx[kind] % len(lst)]
    idx[kind] += 1
    new = lst[idx[kind] % len(lst)]
    hide([old], f)
    show([new], f)
    # 番号（01/05 など）は省略。行の帯を一瞬光らせる代わりに、印をポンと伸ばす
# 8分音符のインジケーター（下の8つの四角。今の拍が橙で大きくなる）
beats = []
for k in range(8):
    x = 0.36 + k * 0.036
    o = ui_rect(f"UI_拍_{k}", x, 0.06, x + 0.024, 0.10, m_ui_w)
    o2 = ui_rect(f"UI_拍_光_{k}", x - 0.004, 0.055, x + 0.028, 0.105, m_ui_o, z=0.0005)
    cx = ui_pos(x + 0.012, 0.08)
    for ob in (o2,):
        me = ob.data
        for v in me.vertices:
            v.co -= Vector((cx.x, cx.y, 0))
        ob.location = (cx.x, cx.y, 0)
        set_scale_key(ob, 1, (0, 0, 0), 'CONSTANT')
    beats.append(o2)
for i in range(N_HITS):
    f = hit_frame(i)
    b = beats[i % 8]
    set_scale_key(b, f - 1, (0, 0, 0), 'CONSTANT')
    set_scale_key(b, f, (1.3, 1.3, 1))
    set_scale_key(b, f + 2, (1, 1, 1))
    set_scale_key(b, f + int(EIGHTH) - 1, (1, 1, 1), 'CONSTANT')
    set_scale_key(b, f + int(EIGHTH), (0, 0, 0), 'CONSTANT')
ui_text("BPM 140  ♪=8分", 0.92, 0.08, 0.032, m_ui_w, align='RIGHT')

# ---------------------------------------------------------------- シェイプ（床の上で回るリング。4分音符で脈打つ）
m_sw, m_sb, m_so = flat("シェイプ白", WHITE), flat("シェイプ青", BLUE), flat("シェイプ橙", ORANGE)
shapes = [ring("シェイプ_リング_外", 5.2, 0.12, 0.02, m_sb, z=-0.13, c=c_shp, dashes=24, fill=0.55),
          ring("シェイプ_リング_中", 4.5, 0.05, 0.02, m_sw, z=-0.13, c=c_shp, dashes=48, fill=0.4),
          ring("シェイプ_リング_橙", 6.2, 0.25, 0.02, m_so, z=-0.13, c=c_shp, dashes=6, fill=0.18)]
for k, o in enumerate(shapes):
    o.rotation_mode = 'XYZ'
    o.rotation_euler[2] = 0
    o.keyframe_insert("rotation_euler", index=2, frame=1)
    o.rotation_euler[2] = math.radians((1 if k % 2 else -1) * (60 + 40 * k))
    o.keyframe_insert("rotation_euler", index=2, frame=F_END)
    for fc in o.animation_data.action.fcurves:
        for kp in fc.keyframe_points:
            kp.interpolation = 'LINEAR'
    for q in range(N_HITS // 2):
        f = hit_frame(q * 2)
        set_scale_key(o, f, (1.06, 1.06, 1))
        set_scale_key(o, f + 4, (1, 1, 1))

# ---------------------------------------------------------------- 後片付け: 使わない車と元のコレクションは隠す
for key, car in CARS.items():
    if key == "R32":
        continue
    for o in C5.tree(car):
        link(o, c_back)
        o.hide_render = True
        o.hide_viewport = True
for c in old_cols:
    root.children.unlink(c)
    c_back.children.link(c)
    c.hide_render = True
for o in list(root.objects):
    link(o, c_back)
sc.frame_set(1)
print("CUSTOM frames", F_END, "eighth", round(EIGHTH, 3), "events", len(events), "font", font and font.name)
bpy.ops.wm.save_as_mainfile(filepath=OUT, compress=True)
print("SAVED", OUT)

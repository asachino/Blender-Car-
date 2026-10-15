"""カスタム画面風のシーン（4分音符版）: R32 を BPM140 の4分音符で順番にカスタムしていく

blender -b cars5.blend --python custom_r32_v2.py -- 参考.blend 出力.blend

  1〜8拍  : ホイールが8回替わる（5種の形 ＋ 色違い）           … 横〜斜め前から
  9〜16拍 : ウイングが8回替わる（5種の形 ＋ 色違い）           … 斜め後ろから
  17〜20拍: ボンネットが4回替わる（カーボン・ダクト・バルジ・ストライプ） … 斜め前の上から
  21〜24拍: 足回りが4回替わる（車高が落ちる・キャンバーが付く）   … 正面の低い所から
替わったパーツはそのまま残り、最後はフルカスタムになる。替わる瞬間は 0 → 1.28 → 0.94 → 1 と飛び出す。
空と車のマテリアルは参考ファイル（オリジナルカメラ_前後オーバル）から。30fps・ビュー変換は標準。
コレクション: no / 01_car（CAR_R32・ホイール・ウイング・ボンネット）/ 02_back / 03_edit / 04_shape（シェイプ・UI）、camera
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

FPS, BPM = 30, 140
BEAT = FPS * 60.0 / BPM                  # 4分音符のフレーム数（12.86）
T0 = 16                                  # 最初に替わるフレーム
SECTIONS = [("WHEEL", 8), ("WING", 8), ("BONNET", 4), ("SUSPENSION", 4)]
N_HITS = sum(n for _, n in SECTIONS)
F_END = int(round(T0 + N_HITS * BEAT)) + 40

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


def carbon(name="カーボン", a="#11141c", b="#2a3046", rim="#6f7fb0"):
    """トゥーン調のカーボン（細かい綾織りの市松 ＋ 縁が少し明るい）"""
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    tc = nt.nodes.new("ShaderNodeTexCoord")
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.inputs["Rotation"].default_value = (0, 0, math.radians(45))
    ck = nt.nodes.new("ShaderNodeTexChecker")
    ck.inputs["Scale"].default_value = 90.0
    ck.inputs["Color1"].default_value = hx(a)
    ck.inputs["Color2"].default_value = hx(b)
    fr = nt.nodes.new("ShaderNodeFresnel")
    fr.inputs["IOR"].default_value = 1.25
    rp = nt.nodes.new("ShaderNodeValToRGB")
    rp.color_ramp.interpolation = 'CONSTANT'
    rp.color_ramp.elements[0].color = (0, 0, 0, 1)
    rp.color_ramp.elements[1].position = 0.55
    rp.color_ramp.elements[1].color = hx(rim)
    mx = nt.nodes.new("ShaderNodeMix")
    mx.data_type = 'RGBA'
    mx.blend_type = 'SCREEN'
    mx.inputs[0].default_value = 1.0
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
    nt.links.new(mp.outputs["Vector"], ck.inputs["Vector"])
    nt.links.new(fr.outputs[0], rp.inputs[0])
    nt.links.new(ck.outputs["Color"], mx.inputs[6])
    nt.links.new(rp.outputs[0], mx.inputs[7])
    nt.links.new(mx.outputs[2], out.inputs["Surface"])
    return m


def hit_frame(i):
    return int(round(T0 + i * BEAT))


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
            for sl, (mn, link_) in zip(o.material_slots, slots):
                if mn and got.get(mn) is not None:
                    sl.link = link_
                    sl.material = got[mn]
sc.world = dt.worlds[0]
for k, v in info["eevee"].items():
    try:
        setattr(sc.eevee, k, v)
    except Exception:
        pass
sc.eevee.taa_render_samples = max(sc.eevee.taa_render_samples, 16)

# ---------------------------------------------------------------- コレクション
root = sc.collection


def col(name, parent):
    c = bpy.data.collections.new(name)
    parent.children.link(c)
    return c


old_cols = list(root.children)
no = col("no", root)
c_car = col("01_car", no)
c_r32, c_wheel, c_wing, c_hood = col("CAR_R32", c_car), col("ホイール", c_car), col("ウイング", c_car), col("ボンネット", c_car)
c_back, c_edit, c_shape = col("02_back", no), col("03_edit", no), col("04_shape", no)
c_shp, c_ui = col("シェイプ", c_shape), col("UI", c_shape)
c_cam = col("camera", root)


def link(o, c):
    for x in list(o.users_collection):
        x.objects.unlink(o)
    c.objects.link(o)


r32b, r32w = CARS["R32"]
r32_body_meshes = [x for x in r32b.children_recursive if x.type == 'MESH']
for o in C5.tree(CARS["R32"]):
    link(o, c_r32)
for key, car in CARS.items():        # 他の車は隠す（ホイールの形だけ借りる）
    if key != "R32":
        for o in C5.tree(car):
            link(o, c_back)
            o.hide_render = o.hide_viewport = True

# ---------------------------------------------------------------- 形を作る道具
def disc(name, r, h, mat, z=0.0, seg=96, c=c_back):
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
    return o


def ring(name, r, w, h, mat, z=0.0, seg=128, c=c_back, dashes=0, fill=0.6):
    bm = bmesh.new()

    def quad(a0, a1):
        vs = [bm.verts.new((math.cos(a) * rr, math.sin(a) * rr, zz))
              for a in (a0, a1) for rr in (r - w / 2, r + w / 2) for zz in (z - h, z)]
        for f in ((0, 4, 5, 1), (2, 3, 7, 6), (1, 5, 7, 3), (0, 2, 6, 4)):
            bm.faces.new([vs[i] for i in f])
    if dashes:
        for d in range(dashes):
            a0 = 2 * math.pi * d / dashes
            a1 = a0 + 2 * math.pi / dashes * fill
            st = max(2, int(seg * fill / dashes))
            for s_ in range(st):
                quad(a0 + (a1 - a0) * s_ / st, a0 + (a1 - a0) * (s_ + 1) / st)
    else:
        for k in range(seg):
            quad(2 * math.pi * k / seg, 2 * math.pi * (k + 1) / seg)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    o.data.materials.append(mat)
    c.objects.link(o)
    return o


outline = bpy.data.materials.get("OH_Outline_Material")


def add_outline(o, th=0.012):
    if outline is None:
        return
    o.data.materials.append(outline)
    sd = o.modifiers.new("輪郭", 'SOLIDIFY')
    sd.thickness = th
    sd.offset = 1.0
    sd.use_flip_normals = True
    sd.material_offset = len(o.data.materials) - 1
    sd.use_rim = False


def mesh_from(bm, name, mat, c, parent, origin):
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    for v in bm.verts:
        v.co -= origin
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    me.materials.append(mat)
    add_outline(o)
    c.objects.link(o)
    o.parent = parent
    return o


def boxmesh(bm, c, sx, sy, sz, rot_x=0.0):
    M = Matrix.Translation(c) @ Matrix.Rotation(rot_x, 4, 'X')
    bmesh.ops.create_cube(bm, size=1.0, matrix=M @ Matrix.Diagonal((sx, sy, sz, 1)))


def airfoil(bm, c, span, chord, th, aoa):
    M = Matrix.Translation(c) @ Matrix.Rotation(math.radians(aoa), 4, 'X')
    rows = []
    for x in (-span / 2, span / 2):
        prof = [(chord * 0.5, 0.0), (chord * 0.25, th * 0.55), (-chord * 0.2, th * 0.5), (-chord * 0.5, th * 0.1),
                (-chord * 0.5, -th * 0.05), (chord * 0.3, -th * 0.4)]
        rows.append([bm.verts.new(M @ Vector((x, yy, zz))) for yy, zz in prof])
    a, b = rows
    n = len(a)
    for i in range(n):
        bm.faces.new((a[i], a[(i + 1) % n], b[(i + 1) % n], b[i]))
    bm.faces.new(list(reversed(a)))
    bm.faces.new(b)


# ---------------------------------------------------------------- 床とターンテーブル（ここまでは回転させずに作る）
table = bpy.data.objects.new("ターンテーブル", None)
c_back.objects.link(table)
for o in [r32b] + list(r32w):
    o.parent = table
m_table, m_line, m_floor = flat("ターンテーブル", NAVY), flat("ターンテーブルの線", WHITE), flat("床", "#c9d2ff")
floor = disc("床", 60.0, 0.02, m_floor, z=-0.16)
top = disc("ターンテーブル_台", 3.8, 0.16, m_table, z=0.0)
top.parent = table
for r_ in (3.75, 3.2):
    ring(f"ターンテーブル_線_{r_}", r_, 0.06, 0.005, m_line, z=0.004).parent = table
ed = top.copy()
ed.data = top.data.copy()
ed.name = "ターンテーブル_台_編集用"
c_edit.objects.link(ed)
ed.hide_render = ed.hide_viewport = True
bpy.context.view_layer.update()
dg = bpy.context.evaluated_depsgraph_get()


def surf_z(x, y, objs):
    """車体（objs）の上面の高さ。当たらなければ None"""
    o0 = Vector((x, y, 5))
    for _ in range(6):
        hit, loc, n_, i_, ob, M = sc.ray_cast(dg, o0, Vector((0, 0, -1)))
        if not hit:
            return None
        if ob in objs:
            return loc.z
        o0 = loc - Vector((0, 0, 0.002))
    return None


# ---------------------------------------------------------------- ホイール（8回: 形5種 ＋ 色違い）
def radius(o):
    return o.dimensions.z / 2


def tinted(mat, mode):
    m = mat.copy()
    m.name = f"{mat.name}_{mode}"
    if not m.use_nodes:
        return m
    for n in m.node_tree.nodes:
        if n.type != 'VALTORGB':
            continue
        for e in n.color_ramp.elements:
            r, g, b, a = e.color
            v = max(r, g, b)
            if mode == "ゴールド":
                e.color = (v * 1.0, v * 0.66, v * 0.12, a) if v > 0.08 else e.color
            elif mode == "ブラック":
                e.color = (r * 0.18, g * 0.18, b * 0.22, a)
            elif mode == "ホワイト":
                e.color = (0.35 + v * 0.65, 0.35 + v * 0.65, 0.38 + v * 0.62, a)
            elif mode == "ブルー":
                e.color = (v * 0.05, v * 0.35, v * 1.0, a) if v > 0.08 else e.color
    return m


r_r32 = sum(radius(w) for w in r32w) / 4
WHEELS = [("純正", "R32", None), ("F40 スタイル", "F40", None), ("カウンタック スタイル", "COUNTACH", None),
          ("テスタロッサ スタイル", "TESTA", None), ("S2000 スタイル", "S2000", None),
          ("F40 スタイル ゴールド", "F40", "ゴールド"), ("カウンタック スタイル ブラック", "COUNTACH", "ブラック"),
          ("テスタロッサ スタイル ホワイト", "TESTA", "ホワイト"), ("S2000 スタイル ゴールド", "S2000", "ゴールド")]
wheel_groups = []
for jp, key, tint in WHEELS:
    if key == "R32" and tint is None:
        wheel_groups.append((jp, list(r32w)))
        continue
    grp = []
    cache = {}
    for w_src, w_dst in zip(CARS[key][1], r32w):
        w = w_src.copy()
        w.name = f"ホイール_{jp}_{w_dst.name[-2:]}"
        c_wheel.objects.link(w)
        w.hide_render = w.hide_viewport = False
        w.parent = table
        w.matrix_parent_inverse = Matrix.Identity(4)
        s_ = r_r32 / max(1e-3, radius(w_src))
        w.location = w_dst.location.copy()
        w.rotation_euler = (0, 0, 0)
        w.scale = (s_, s_, s_)
        if tint:
            for sl in w.material_slots:
                if sl.material and not sl.material.name.startswith("OH_"):
                    k_ = sl.material.name
                    if k_ not in cache:
                        cache[k_] = tinted(sl.material, tint)
                    sl.link = 'OBJECT'
                    sl.material = cache[k_]
        grp.append(w)
    wheel_groups.append((jp, grp))

# ---------------------------------------------------------------- ウイング（8回: 形5種 ＋ 色違い）。ボディの子（車高と一緒に下がる）
m_carbon = carbon()
m_plate_o, m_plate_w, m_plate_b = flat("ウイング_翼端板_橙", ORANGE), flat("ウイング_翼端板_白", WHITE), flat("ウイング_翼端板_青", BLUE)
m_wing_w, m_wing_o = flat("ウイング_白", "#f2f4fa"), flat("ウイング_橙", ORANGE)
Y_MOUNT = -1.95
Z_DECK = surf_z(0, Y_MOUNT, r32_body_meshes) or 1.0


def wing(name, build, m_main, m_plate):
    bm_c, bm_p = bmesh.new(), bmesh.new()
    build(bm_c, bm_p)
    rt = bpy.data.objects.new(f"ウイング_{name}", None)
    c_wing.objects.link(rt)
    rt.parent = r32b
    rt.matrix_parent_inverse = r32b.matrix_world.inverted()
    org = Vector((0, Y_MOUNT, Z_DECK))
    rt.location = org
    for bm, mat, suf in ((bm_c, m_main, "本体"), (bm_p, m_plate, "翼端板")):
        if bm.verts:
            mesh_from(bm, f"ウイング_{name}_{suf}", mat, c_wing, rt, org)
        else:
            bm.free()
    return rt


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
    w, y0, y1 = 0.80, Y_MOUNT + 0.05, Y_MOUNT - 0.25
    vs = [bc.verts.new(v) for v in ((-w, y0, Z_DECK + 0.01), (w, y0, Z_DECK + 0.01), (w, y1, Z_DECK + 0.01), (-w, y1, Z_DECK + 0.01),
                                    (-w, y1, Z_DECK + 0.13), (w, y1, Z_DECK + 0.13))]
    for f in ((0, 1, 5, 4), (3, 2, 1, 0), (4, 5, 2, 3), (0, 4, 3), (1, 2, 5)):
        bc.faces.new([vs[i] for i in f])
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


WINGS = [("なし（純正）", None, None, None), ("ダックテール", duck, m_carbon, m_plate_o), ("GTウイング", gt, m_carbon, m_plate_o),
         ("スワンネック", swan, m_carbon, m_plate_b), ("ダブルデッキ", double, m_carbon, m_plate_o),
         ("GTウイング ホワイト", gt, m_wing_w, m_plate_o), ("スワンネック オレンジ", swan, m_wing_o, m_plate_w),
         ("ダブルデッキ ホワイト", double, m_wing_w, m_plate_b), ("ハイマウント", high, m_carbon, m_plate_o)]
wing_roots = []
for jp, fn, mm, mp in WINGS:
    if fn is None:
        e = bpy.data.objects.new("ウイング_なし", None)
        c_wing.objects.link(e)
        e.parent = r32b
        e.matrix_parent_inverse = r32b.matrix_world.inverted()
        wing_roots.append((jp, e))
    else:
        wing_roots.append((jp, wing(jp, fn, mm, mp)))

# ---------------------------------------------------------------- ボンネット（4回）。純正の上にぴったり重ねるパネル
HX, HY0, HY1 = 0.70, 0.66, 1.92      # ボンネットの範囲（左右・後ろ・前）
NX, NY = 14, 18
grid = []
for j in range(NY + 1):
    y = HY0 + (HY1 - HY0) * j / NY
    row = []
    for i in range(NX + 1):
        x = -HX + 2 * HX * i / NX
        z = surf_z(x, y, r32_body_meshes)
        row.append(z)
    grid.append(row)
zs = [z for r in grid for z in r if z is not None]
Z_HOOD = sum(zs) / max(1, len(zs))
for j in range(NY + 1):           # 当たらなかった所は近くの値で埋める
    for i in range(NX + 1):
        if grid[j][i] is None:
            grid[j][i] = Z_HOOD
HOOD_C = Vector((0, (HY0 + HY1) / 2, Z_HOOD))


def bulge_z(x, y, bulge):
    """パワーバルジの盛り上がり（中央が高く、前後はなだらか）"""
    if not bulge:
        return 0.0
    t = (y - HY0) / (HY1 - HY0)
    return bulge * math.exp(-(x / 0.30) ** 4) * math.sin(min(1.0, t * 1.3) * math.pi)


def hood_panel(bm, bulge=0.0, lift=0.012):
    vs = []
    for j in range(NY + 1):
        y = HY0 + (HY1 - HY0) * j / NY
        row = []
        for i in range(NX + 1):
            x = -HX + 2 * HX * i / NX
            t = (y - HY0) / (HY1 - HY0)
            bz = bulge_z(x, y, bulge)
            row.append(bm.verts.new((x, y, grid[j][i] + lift + bz)))
        vs.append(row)
    for j in range(NY):
        for i in range(NX):
            bm.faces.new((vs[j][i], vs[j][i + 1], vs[j + 1][i + 1], vs[j + 1][i]))


def on_hood(x, y):
    j = round((y - HY0) / (HY1 - HY0) * NY)
    i = round((x + HX) / (2 * HX) * NX)
    return grid[max(0, min(NY, j))][max(0, min(NX, i))]


m_black, m_stripe = flat("ボンネット_黒", "#05060a"), flat("ボンネット_ストライプ", ORANGE)


def hood(name, parts):
    rt = bpy.data.objects.new(f"ボンネット_{name}", None)
    c_hood.objects.link(rt)
    rt.parent = r32b
    rt.matrix_parent_inverse = r32b.matrix_world.inverted()
    rt.location = HOOD_C
    for suf, mat, build in parts:
        bm = bmesh.new()
        build(bm)
        mesh_from(bm, f"ボンネット_{name}_{suf}", mat, c_hood, rt, HOOD_C)
    return rt


def vents(bm):
    for x in (-0.30, 0.30):
        for k in range(4):
            y = 1.10 + k * 0.07
            boxmesh(bm, Vector((x, y, on_hood(x, y) + 0.03)), 0.30, 0.035, 0.03, rot_x=math.radians(-12))


def stripes(bm):
    for x in (-0.11, 0.11):
        for j in range(NY):
            y = HY0 + (HY1 - HY0) * (j + 0.5) / NY
            boxmesh(bm, Vector((x, y, on_hood(x, y) + bulge_z(x, y, 0.06) + 0.022)), 0.09, (HY1 - HY0) / NY * 1.6, 0.02)


HOODS = [("純正", None),
         ("カーボン", [("パネル", m_carbon, lambda bm: hood_panel(bm))]),
         ("カーボン ダクト付き", [("パネル", m_carbon, lambda bm: hood_panel(bm)), ("ダクト", m_black, vents)]),
         ("パワーバルジ カーボン", [("パネル", m_carbon, lambda bm: hood_panel(bm, bulge=0.06)), ("ダクト", m_black, vents)]),
         ("GTストライプ", [("パネル", m_carbon, lambda bm: hood_panel(bm, bulge=0.06)), ("ダクト", m_black, vents),
                          ("ストライプ", m_stripe, stripes)])]
hood_roots = []
for jp, parts in HOODS:
    if parts is None:
        e = bpy.data.objects.new("ボンネット_純正", None)
        c_hood.objects.link(e)
        e.parent = r32b
        e.matrix_parent_inverse = r32b.matrix_world.inverted()
        hood_roots.append((jp, e))
    else:
        hood_roots.append((jp, hood(jp, parts)))

# ---------------------------------------------------------------- 足回り（4回）: 車高（mm）とキャンバー（度）
SUSP = [("純正", 0, 0.0), ("車高 -30mm", -30, 0.0), ("車高 -50mm ／ キャンバー -3°", -50, -3.0),
        ("車高 -70mm ／ キャンバー -6°", -70, -6.0), ("車高 -95mm ／ キャンバー -10°", -95, -10.0)]
Z_BODY0 = r32b.location.z

# ---------------------------------------------------------------- 影（ボディの複製をシュリンクラップで台に貼って真っ黒に）
m_shadow = flat("影_黒", "#000000")
for o in r32_body_meshes:
    if o.hide_render:
        continue
    sh = o.copy()
    sh.data = o.data.copy()
    sh.name = o.name + "_影"
    c_r32.objects.link(sh)
    sh.data.materials.clear()
    sh.data.materials.append(m_shadow)
    sw = sh.modifiers.new("Shrinkwrap", 'SHRINKWRAP')
    sw.wrap_method = 'TARGET_PROJECT'
    sw.wrap_mode = 'ON_SURFACE'
    sw.offset = 0.012
    sw.target = top
    sh.visible_shadow = False

# ---------------------------------------------------------------- 「ポン」のキー
def key(o, path, f, v, interp='BEZIER', index=-1):
    if index < 0:
        setattr(o, path, v)
    else:
        getattr(o, path)[index] = v
    o.keyframe_insert(path, index=index, frame=f)
    for fc in o.animation_data.action.fcurves:
        if fc.data_path == path and (index < 0 or fc.array_index == index):
            for kp in fc.keyframe_points:
                if abs(kp.co.x - f) < 0.01:
                    kp.interpolation = interp


base_scale = {}


def show(objs, f):
    for o in objs:
        b = base_scale.get(o, Vector((1, 1, 1)))
        key(o, "scale", f - 1, (0, 0, 0), 'CONSTANT')
        key(o, "scale", f, b * 0.05)
        key(o, "scale", f + 1, b * 1.28)
        key(o, "scale", f + 3, b * 0.94)
        key(o, "scale", f + 5, b)


def hide(objs, f):
    for o in objs:
        b = base_scale.get(o, Vector((1, 1, 1)))
        key(o, "scale", f - 1, b, 'CONSTANT')
        key(o, "scale", f, (0, 0, 0), 'CONSTANT')


for jp, grp in wheel_groups:
    for w in grp:
        base_scale[w] = w.scale.copy()
for i, (jp, grp) in enumerate(wheel_groups):
    for w in grp:
        key(w, "scale", 1, base_scale[w] if i == 0 else (0, 0, 0), 'CONSTANT')
for lst in (wing_roots, hood_roots):
    for i, (jp, e) in enumerate(lst):
        key(e, "scale", 1, (1, 1, 1) if i == 0 else (0, 0, 0), 'CONSTANT')

m_burst = flat("はじけるリング", WHITE)


def burst_obj(name, r, loc, rot, parent):
    b = ring(name, r, 0.025, 0.025, m_burst, c=c_shp)
    b.parent = parent
    if parent is r32b:
        b.matrix_parent_inverse = r32b.matrix_world.inverted()
    b.location = loc
    b.rotation_euler = rot
    key(b, "scale", 1, (0, 0, 0), 'CONSTANT')
    return b


def burst(b, f, big):
    key(b, "scale", f - 1, (0, 0, 0), 'CONSTANT')
    key(b, "scale", f, (0.8, 0.8, 0.8))
    key(b, "scale", f + 3, (big, big, big * 0.4))
    key(b, "scale", f + 4, (0, 0, 0), 'CONSTANT')


b_wheels = [burst_obj(f"はじけるリング_{w.name[-2:]}", 0.40, w.location.copy(), (0, math.radians(90), 0), table) for w in r32w]
b_wing = burst_obj("はじけるリング_ウイング", 0.5, Vector((0, Y_MOUNT, Z_DECK + 0.3)), (math.radians(90), 0, 0), r32b)
b_hood = burst_obj("はじけるリング_ボンネット", 0.55, HOOD_C + Vector((0, 0, 0.05)), (0, 0, 0), r32b)
b_floor = burst_obj("はじけるリング_床", 2.6, Vector((0, 0, 0.01)), (0, 0, 0), table)

# 拍ごとの出来事
events = []      # (フレーム, カテゴリー, 名前)
i = 0
state = {"WHEEL": 0, "WING": 0, "BONNET": 0, "SUSPENSION": 0}
sec_start = {}
for cat, n in SECTIONS:
    sec_start[cat] = hit_frame(i)
    for _ in range(n):
        f = hit_frame(i)
        k = state[cat]
        state[cat] = k + 1
        if cat == "WHEEL":
            hide(wheel_groups[k][1], f)
            show(wheel_groups[k + 1][1], f)
            for b in b_wheels:
                burst(b, f, 1.55)
            name = wheel_groups[k + 1][0]
        elif cat == "WING":
            hide([wing_roots[k][1]], f)
            show([wing_roots[k + 1][1]], f)
            burst(b_wing, f, 2.0)
            name = wing_roots[k + 1][0]
        elif cat == "BONNET":
            hide([hood_roots[k][1]], f)
            show([hood_roots[k + 1][1]], f)
            burst(b_hood, f, 2.2)
            name = hood_roots[k + 1][0]
        else:
            jp0, mm0, cb0 = SUSP[k]
            jp1, mm1, cb1 = SUSP[k + 1]
            z0, z1 = Z_BODY0 + mm0 / 1000.0, Z_BODY0 + mm1 / 1000.0
            # 車高: ストンと落ちて少し跳ねて止まる
            key(r32b, "location", f - 1, z0, 'BEZIER', index=2)
            key(r32b, "location", f + 2, z1 - 0.022, 'BEZIER', index=2)
            key(r32b, "location", f + 5, z1 + 0.008, 'BEZIER', index=2)
            key(r32b, "location", f + 8, z1, 'BEZIER', index=2)
            # キャンバー: 上側が内へ（左は +、右は -）。今見えている全ホイールに
            for jp_, grp in wheel_groups:
                for w in grp:
                    sgn = 1 if w.location.x < 0 else -1
                    key(w, "rotation_euler", f - 1, math.radians(-cb0) * sgn, 'BEZIER', index=1)
                    key(w, "rotation_euler", f + 3, math.radians(-cb1) * sgn * 1.15, 'BEZIER', index=1)
                    key(w, "rotation_euler", f + 6, math.radians(-cb1) * sgn, 'BEZIER', index=1)
            burst(b_floor, f, 1.5)
            name = jp1
        events.append((f, cat, name))
        i += 1

# ---------------------------------------------------------------- 見せる向き（台の回転）とカメラ
# 台の向き: 180°で車の正面がカメラへ、0°で後ろ。カテゴリーが替わる1拍前から回して見せたい所を向ける
VIEW = {"WHEEL": (118, 100, 1.55, 8.2), "WING": (28, 12, 1.9, 8.0), "BONNET": (150, 160, 2.6, 7.4), "SUSPENSION": (182, 178, 0.75, 7.6)}
# 各カテゴリーの最初の拍の直前に向きがそろい、最後の拍のあと次へ素早く回る（キーが重ならないように）
spans = {}
for cat, n in SECTIONS:
    f0 = sec_start[cat]
    spans[cat] = (f0 - 1, f0 + int(round((n - 1) * BEAT)) + 6)
for cat, n in SECTIONS:
    a0, a1, h, dist = VIEW[cat]
    fa, fb = spans[cat]
    key(table, "rotation_euler", fa, math.radians(a0), 'BEZIER', index=2)
    key(table, "rotation_euler", fb, math.radians(a1), 'BEZIER', index=2)
key(table, "rotation_euler", 1, math.radians(VIEW["WHEEL"][0]), 'BEZIER', index=2)
key(table, "rotation_euler", F_END, math.radians(140), 'BEZIER', index=2)

rig = bpy.data.objects.new("カメラリグ", None)
c_cam.objects.link(rig)
rig.location = (0, 0, 0.7)
punch = bpy.data.objects.new("拍のパンチ", None)
c_cam.objects.link(punch)
punch.parent = rig
cd = bpy.data.cameras.new("カスタム画面カメラ")
cd.lens = 38
cd.clip_start = 0.05
cam = bpy.data.objects.new("カスタム画面カメラ", cd)
c_cam.objects.link(cam)
cam.parent = punch
sc.camera = cam


def cam_key(f, h, dist):
    eye = Vector((0, -dist, h))
    cam.location = eye
    cam.rotation_euler = (Vector((-1.35, 0, -0.1)) - eye).to_track_quat('-Z', 'Y').to_euler()
    cam.keyframe_insert("location", frame=f)
    cam.keyframe_insert("rotation_euler", frame=f)


rig.rotation_euler = (0, 0, math.radians(18))
cam_key(1, VIEW["WHEEL"][2], VIEW["WHEEL"][3])
for cat, n in SECTIONS:
    fa, fb = spans[cat]
    cam_key(fa, VIEW[cat][2], VIEW[cat][3])
    cam_key(fb, VIEW[cat][2], VIEW[cat][3] - 0.4)
cam_key(F_END, 1.4, 8.4)
for q in range(N_HITS):
    f = hit_frame(q)
    key(punch, "location", f, 0.0, index=1)
    key(punch, "location", f + 1, 0.2, index=1)
    key(punch, "location", f + 6, 0.0, index=1)

# ---------------------------------------------------------------- UI
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


def ui_rect(name, x0, y0, x1, y1, mat, z=0.0, skew=0.0, pivot=None):
    a, b = ui_pos(x0, y0, z), ui_pos(x1, y1, z)
    sk = skew * HALF_H * 2
    pv = ui_pos(*pivot, z) if pivot else Vector((0, 0, 0))
    vs = [(a.x, a.y, a.z), (b.x, a.y, a.z), (b.x + sk, b.y, a.z), (a.x + sk, b.y, a.z)]
    me = bpy.data.meshes.new(name)
    me.from_pydata([(x - pv.x, y - pv.y, z_) for x, y, z_ in vs], [], [(0, 1, 2, 3)])
    o = bpy.data.objects.new(name, me)
    me.materials.append(mat)
    c_ui.objects.link(o)
    o.parent = cam
    if pivot:
        o.location = (pv.x, pv.y, 0)
    return o
ui_rect("UI_タイトル帯", 0.03, 0.85, 0.36, 0.96, m_ui_b, skew=0.03)
ui_rect("UI_タイトル線", 0.03, 0.835, 0.42, 0.845, m_ui_o)
ui_text("CUSTOMIZE", 0.05, 0.905, 0.07, m_ui_w)
ui_text("NISSAN SKYLINE GT-R  R32", 0.05, 0.805, 0.034, m_ui_n)
ROWS = {"WHEEL": 0.68, "WING": 0.555, "BONNET": 0.43, "SUSPENSION": 0.305}
JP = {"WHEEL": "ホイール", "WING": "ウイング", "BONNET": "ボンネット", "SUSPENSION": "足回り"}
row_mark = {}
for cat, y in ROWS.items():
    ui_rect(f"UI_{cat}_帯", 0.03, y - 0.055, 0.38, y + 0.055, m_ui_n, skew=0.02)
    mk = ui_rect(f"UI_{cat}_印", 0.03, y - 0.055, 0.045, y + 0.055, m_ui_o, pivot=(0.03, y))
    row_mark[cat] = mk
    ui_text(f"{cat}  {JP[cat]}", 0.09, y + 0.026, 0.03, m_ui_o)
# 今のカテゴリーは印が横に伸びる
for cat, n in SECTIONS:
    mk = row_mark[cat]
    f0 = sec_start[cat]
    f1 = f0 + int(round(n * BEAT))
    key(mk, "scale", 1, (1, 1, 1), 'CONSTANT')
    key(mk, "scale", f0 - 3, (1, 1, 1))
    key(mk, "scale", f0, (2.6, 1, 1))
    key(mk, "scale", f1 - 3, (2.6, 1, 1))
    key(mk, "scale", f1, (1, 1, 1))
names = {"WHEEL": [jp for jp, _ in wheel_groups], "WING": [jp for jp, _ in wing_roots],
         "BONNET": [jp for jp, _ in hood_roots], "SUSPENSION": [jp for jp, _, _ in SUSP]}
name_objs = {}
for cat, lst in names.items():
    name_objs[cat] = []
    for j, jp in enumerate(lst):
        o = ui_text(jp, 0.09, ROWS[cat] - 0.022, 0.044 if len(jp) < 14 else 0.034, m_ui_w)
        o.name = f"UI_{cat}_{j}"
        key(o, "scale", 1, (1, 1, 1) if j == 0 else (0, 0, 0), 'CONSTANT')
        name_objs[cat].append(o)
idx = {k: 0 for k in names}
for f, cat, jp in events:
    lst = name_objs[cat]
    hide([lst[idx[cat]]], f)
    idx[cat] += 1
    show([lst[idx[cat]]], f)
# 4分音符のインジケーター（1小節の4つ。今の拍が橙で大きくなる）＋ 何拍目か
beats = []
for k in range(4):
    x = 0.42 + k * 0.05
    ui_rect(f"UI_拍_{k}", x, 0.06, x + 0.034, 0.105, m_ui_w)
    o2 = ui_rect(f"UI_拍_光_{k}", x - 0.004, 0.055, x + 0.038, 0.11, m_ui_o, z=0.0005, pivot=(x + 0.017, 0.0825))
    key(o2, "scale", 1, (0, 0, 0), 'CONSTANT')
    beats.append(o2)
for q in range(N_HITS):
    f = hit_frame(q)
    b = beats[q % 4]
    key(b, "scale", f - 1, (0, 0, 0), 'CONSTANT')
    key(b, "scale", f, (1.3, 1.3, 1))
    key(b, "scale", f + 2, (1, 1, 1))
    key(b, "scale", f + int(BEAT) - 1, (1, 1, 1), 'CONSTANT')
    key(b, "scale", f + int(BEAT), (0, 0, 0), 'CONSTANT')
ui_text("BPM 140  ♩=4分", 0.92, 0.08, 0.032, m_ui_w, align='RIGHT')

# ---------------------------------------------------------------- シェイプ（床の上で回るリング。拍で脈打つ）
m_sw, m_sb, m_so = flat("シェイプ白", WHITE), flat("シェイプ青", BLUE), flat("シェイプ橙", ORANGE)
shapes = [ring("シェイプ_リング_外", 5.2, 0.12, 0.02, m_sb, z=-0.13, c=c_shp, dashes=24, fill=0.55),
          ring("シェイプ_リング_中", 4.5, 0.05, 0.02, m_sw, z=-0.13, c=c_shp, dashes=48, fill=0.4),
          ring("シェイプ_リング_橙", 6.2, 0.25, 0.02, m_so, z=-0.13, c=c_shp, dashes=6, fill=0.18)]
for k, o in enumerate(shapes):
    key(o, "rotation_euler", 1, 0.0, 'LINEAR', index=2)
    key(o, "rotation_euler", F_END, math.radians((1 if k % 2 else -1) * (60 + 40 * k)), 'LINEAR', index=2)
    for q in range(N_HITS):
        f = hit_frame(q)
        key(o, "scale", f, (1.07, 1.07, 1))
        key(o, "scale", f + 5, (1, 1, 1))

# ---------------------------------------------------------------- 後片付け
for c in old_cols:
    root.children.unlink(c)
    c_back.children.link(c)
    c.hide_render = True
for o in list(root.objects):
    link(o, c_back)
sc.frame_set(1)
print("CUSTOM2 frames", F_END, "beat", round(BEAT, 3), "events", len(events), "deck", round(Z_DECK, 3), "hood", round(Z_HOOD, 3))
for f, cat, jp in events:
    print("EV", f, cat, jp)
bpy.ops.wm.save_as_mainfile(filepath=OUT, compress=True)
print("SAVED", OUT)

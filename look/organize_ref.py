"""参考シーン（オリジナルカメラ_前後オーバル）の組み方に合わせてシーンを整理する

blender -b シーン.blend --python organize_ref.py -- 参考.blend 出力.blend [番号]

コレクション（番号を名前にしたコレクションの中に）:
  01_car  : 車をすべて。車種ごとに CAR_R32 などへ。影（ボディの複製）も各車のコレクションに入れる
  02_back : 背景のオブジェクト（カメラ以外すべて）。元のコレクション（壁・タイヤバリヤなど）はこの下へ
  03_edit : 道路の複製（編集用。レンダーと画面では隠す）
  04_shape: シェイプ。車の進行方向のそばに伸びるベジェと、それに沿って流れる矢印（参考シーンの形を使う）
  camera  : カメラ（番号のコレクションの外）
影  : ボディを複製 → シュリンクラップ（参考と同じ「ターゲットの法線に投影」）で地面へ → マテリアルを外して真っ黒
"""
import bpy
import math
import re
import sys
from mathutils import Vector

args = sys.argv[sys.argv.index("--") + 1:]
REF, OUT = args[0], args[1]
NO = args[2] if len(args) > 2 else "no"
MODEL = re.compile(r"^CPB_(R32|F40|Countach|Testarossa|S2000|Formula)_")
SHADOW_OFFSET = 0.10     # 影を地面から浮かせる高さ（道路の面より上に出す）

sc = bpy.context.scene
root = sc.collection


def new_col(name, parent):
    for c in parent.children:
        if c.name == name or c.name.startswith(name + "."):
            return c
    c = bpy.data.collections.new(name)
    parent.children.link(c)
    return c


def layer_col(col, lc=None):
    lc = lc or bpy.context.view_layer.layer_collection
    if lc.collection == col:
        return lc
    for ch in lc.children:
        r = layer_col(col, ch)
        if r:
            return r
    return None


def move(o, col):
    for c in list(o.users_collection):
        c.objects.unlink(o)
    col.objects.link(o)


# ---------------------------------------------------------------- コレクション
no = new_col(NO, root)
c_car = new_col("01_car", no)
c_back = new_col("02_back", no)
c_edit = new_col("03_edit", no)
c_shape = new_col("04_shape", no)
c_shape_in = new_col("シェイプ", c_shape)
c_cam = new_col("camera", root)
mine = {no.name, c_car.name, c_back.name, c_edit.name, c_shape.name, c_shape_in.name, c_cam.name}

# 元のトップレベルのコレクションは 02_back の下へ
for c in list(root.children):
    if c.name in mine:
        continue
    root.children.unlink(c)
    c_back.children.link(c)
# 車
s = sc.cpb
class _Car:
    def __init__(self, body, wheels):
        self.body = body
        self.wheel_fl, self.wheel_fr, self.wheel_rl, self.wheel_rr = wheels


cars = [_Car(s.body, [s.wheel_fl, s.wheel_fr, s.wheel_rl, s.wheel_rr])]
cars += [_Car(c.body, [c.wheel_fl, c.wheel_fr, c.wheel_rl, c.wheel_rr]) for c in s.cars]
# 1台ずつ焼き込んだ車（ボディに cpb_wheels が書いてある）も車として扱う
_known = {c.body for c in cars}
for o in list(sc.objects):
    if "cpb_wheels" in o and o not in _known:
        ws_ = [bpy.data.objects.get(n) for n in o["cpb_wheels"]]
        if all(ws_):
            cars.append(_Car(o, ws_))
car_objs = set()
used_models = {}
for c in cars:
    mm = MODEL.match(c.body.name)
    key = mm.group(1) if mm else re.sub(r"\.\d{3}$", "", c.body.name)
    n = used_models.get(key, 0) + 1
    used_models[key] = n
    col = new_col(f"CAR_{key}" + (f"_{n}" if n > 1 else ""), c_car)
    objs = [c.body] + list(c.body.children_recursive)
    for w in (c.wheel_fl, c.wheel_fr, c.wheel_rl, c.wheel_rr):
        if w:
            objs += [w] + list(w.children_recursive)
    for o in objs:
        move(o, col)
        car_objs.add(o)
# 使っていない車（遠くに停めてある車種）は 01_car の中の「未使用の車」へまとめて、レンダーから外す
unused = new_col("未使用の車", c_car)
for c in [x for x in c_back.children_recursive if x.name.startswith("CAR_")]:
    for o in list(c.all_objects):
        if o not in car_objs:
            move(o, unused)
    bpy.data.collections.remove(c)
unused.hide_render = True
lc = layer_col(unused)
if lc:
    lc.exclude = True
# 古い同名コレクションを消したあとなので、.001 などの付いた名前を元に戻す
for c in list(c_car.children):
    b_ = re.sub(r"\.\d{3}$", "", c.name)
    if b_ != c.name and bpy.data.collections.get(b_) is None:
        c.name = b_
# カメラ
for o in list(sc.objects):
    if o.type == 'CAMERA':
        move(o, c_cam)
# 残り（シーン直下のオブジェクト）は 02_back へ
for o in list(root.objects):
    move(o, c_back)

# ---------------------------------------------------------------- 03_edit: 道路の複製
road = bpy.data.objects.get("道")
if road is not None:
    dup = road.copy()
    dup.data = road.data.copy()
    dup.name = "道_編集用"
    c_edit.objects.link(dup)
    dup.hide_render = True          # 元の道路と重なってちらつくので、レンダーと画面では隠しておく
    dup.hide_viewport = True

# ---------------------------------------------------------------- 影
black = bpy.data.materials.get("影_黒") or bpy.data.materials.new("影_黒")
black.use_nodes = True
nt = black.node_tree
for nd in list(nt.nodes):
    nt.nodes.remove(nd)
rgb = nt.nodes.new("ShaderNodeRGB")
rgb.outputs[0].default_value = (0, 0, 0, 1)
mo = nt.nodes.new("ShaderNodeOutputMaterial")
nt.links.new(rgb.outputs[0], mo.inputs["Surface"])
black.shadow_method = 'NONE'
ground = getattr(s, "ground", None)
nsh = 0
for c in cars:
    wheels = {w for w in (c.wheel_fl, c.wheel_fr, c.wheel_rl, c.wheel_rr) if w}
    col = c.body.users_collection[0]
    for o in [x for x in c.body.children_recursive if x.type == 'MESH' and x not in wheels and not x.hide_render]:
        sh = o.copy()
        sh.data = o.data.copy()
        sh.name = o.name + "_影"
        col.objects.link(sh)
        sh.parent = o.parent
        sh.matrix_parent_inverse = o.matrix_parent_inverse.copy()
        sh.matrix_basis = o.matrix_basis.copy()
        if sh.animation_data:
            sh.animation_data_clear()
        if o.animation_data and o.animation_data.action:
            sh.animation_data_create().action = o.animation_data.action
        for md in list(sh.modifiers):
            sh.modifiers.remove(md)
        sh.data.materials.clear()
        sh.data.materials.append(black)
        for sl in sh.material_slots:
            sl.link = 'DATA'
        sw = sh.modifiers.new("Shrinkwrap", 'SHRINKWRAP')
        sw.wrap_method = 'TARGET_PROJECT'
        sw.wrap_mode = 'ON_SURFACE'
        sw.offset = SHADOW_OFFSET
        sw.target = ground
        sh.visible_shadow = False
        nsh += 1

# ---------------------------------------------------------------- 04_shape: ベジェと流れる矢印
F0, F1 = sc.frame_start, sc.frame_end
P = []
for f in range(F0, F1 + 1, 2):
    sc.frame_set(f)
    P.append(s.body.matrix_world.translation.copy())
S = [0.0]
for a, b in zip(P, P[1:]):
    S.append(S[-1] + (b - a).length)
L = S[-1]


def at(sv):
    sv = max(0.0, min(L - 0.01, sv))
    i = max(k for k in range(len(S)) if S[k] <= sv)
    j = min(i + 1, len(P) - 1)
    t = (sv - S[i]) / max(1e-6, S[j] - S[i])
    p = P[i].lerp(P[j], t)
    d = P[j] - P[i]
    d.z = 0
    d.normalize()
    return p, d, Vector((-d.y, d.x, 0))


def blocked(q, z0):
    dg = bpy.context.evaluated_depsgraph_get()
    hit, loc, n_, i_, ob, M = sc.ray_cast(dg, q + Vector((0, 0, 120)), Vector((0, 0, -1)))
    return hit and loc.z > z0 + 6 and not ob.name.startswith(("CPB_", "道"))


# どちら側に伸ばすか（建物の無い側、両方空いていれば左）
p_mid, d_mid, left = at(L / 2)
side = 1
if sum(blocked(at(x)[0] + at(x)[2] * 8, at(x)[0].z) for x in (L * .2, L * .5, L * .8)) > \
   sum(blocked(at(x)[0] - at(x)[2] * 8, at(x)[0].z) for x in (L * .2, L * .5, L * .8)):
    side = -1
# 参考シーンの矢印の形（平面.001 / 平面.002）を読み込む
with bpy.data.libraries.load(REF, link=False) as (df, dt):
    dt.objects = [n for n in ("平面.001", "平面.002") if n in df.objects]
templates = [o for o in dt.objects if o is not None]
SCALE = max(0.9, min(1.85, 1.85 * L / 260.0))   # 参考はオーバルで 1.85 倍。短いコースでは小さく
# (形, 横へ, 上へ, 最初にどこまで進んでいるか, 名前)。追いかけカメラから見えるよう、車のすぐ上に
specs = [(templates[0] if templates else None, 9.0, 2.4, 0.30, "橙"), (templates[1] if len(templates) > 1 else None, 12.0, 4.6, 0.15, "青")]
THICK = 0.35     # 矢印の太さ（上下）の倍率。参考の形のままだと追いかけカメラの画面を覆うので細くする
for tpl, off, h, lead, nm in specs:
    if tpl is None:
        continue
    # ベジェ: 主役の走った跡のそば（横に off、上に h）を、3点で
    cu = bpy.data.curves.new(f"シェイプ_ベジェ_{nm}", 'CURVE')
    cu.dimensions = '3D'
    sp = cu.splines.new('BEZIER')
    n_pt = max(3, int(L / 25.0) + 1)                # 25m ごとに点を置いて、曲がったコースでも道に沿わせる
    pts = [at(L * j / (n_pt - 1)) for j in range(n_pt)]
    sp.bezier_points.add(len(pts) - 1)
    for bp, (p, d, lf) in zip(sp.bezier_points, pts):
        bp.co = p + lf * (off * side) + Vector((0, 0, h))
        bp.handle_left_type = bp.handle_right_type = 'AUTO'
    cobj = bpy.data.objects.new(f"シェイプ_ベジェ_{nm}", cu)
    c_shape_in.objects.link(cobj)
    # 矢印: 参考の形をそのまま使い、向きだけ +X（進行方向）にそろえて大きさを合わせる
    me = tpl.data.copy()
    me.name = f"シェイプ_矢印_{nm}"
    for v in me.vertices:
        x, y, z = v.co
        v.co = Vector((y * SCALE, 0.0, z * SCALE * THICK))
    arrow = bpy.data.objects.new(f"シェイプ_矢印_{nm}", me)
    c_shape_in.objects.link(arrow)
    arrow.parent = cobj
    md = arrow.modifiers.new("Curve", 'CURVE')
    md.object = cobj
    md.deform_axis = 'POS_X'
    # 進行方向へ流れる（参考と同じく、位置のキーで曲線に沿って動かす）
    seg = sum((b.co - a.co).length for a, b in zip(sp.bezier_points, list(sp.bezier_points)[1:]))
    arrow.location.x = seg * lead
    arrow.keyframe_insert("location", index=0, frame=F0)
    arrow.location.x = seg * 1.05
    arrow.keyframe_insert("location", index=0, frame=F1)
    for fc in arrow.animation_data.action.fcurves:
        for kp in fc.keyframe_points:
            kp.interpolation = 'LINEAR'
    arrow.visible_shadow = False
for t in templates:
    bpy.data.objects.remove(t, do_unlink=True)

# ---------------------------------------------------------------- 設定
sc.render.fps = 30
sc.view_settings.view_transform = 'Standard'
sc.frame_set(F0)
print("ORGANIZE shadows", nsh, "cars", [c.body.name for c in cars], "shape side", side, "scale", round(SCALE, 2), "path", round(L))
bpy.ops.wm.save_as_mainfile(filepath=OUT, compress=True)
print("SAVED", OUT)

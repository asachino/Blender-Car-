"""5車種のファイルにフォーミュラを6台目として足す（コピーした .blend の上で実行）

blender -b cars5.blend --python add_formula.py -- Formula_only.blend 出力.blend 参考.blend [加工したテクスチャのフォルダ]

・実寸にする（ホイールベース 3.6 m）。大きさは形に焼き込んで、オブジェクトの拡大縮小は 1 に
・BODY（親のエンプティ）＋4輪（親なし）にして、rev_car / rev_role を付ける（他の5台と同じ組み方）
・マテリアル: 元の「テクスチャ × なめらかな陰影 ＋ 映り込み」を、他の車と同じトゥーンの陰影
  （参考ファイルの R32 のカラーランプ）× リバリーのテクスチャ に組み替える
  リバリー（3種）と色相は、オブジェクトのカスタムプロパティ cpb_livery / cpb_hue で車ごとに変えられる
・元から付いている影の板は外す（影は他の車と同じく、シーン側でボディを複製して作る）
"""
import bpy
import sys
from mathutils import Matrix, Vector

args = sys.argv[sys.argv.index("--") + 1:]
SRC, OUT = args[0], args[1]
REF = args[2] if len(args) > 2 else None
TEXDIR = args[3] if len(args) > 3 else None   # formula_tex.py で加工したリバリー（番号なし・文字はバーコード）
WHEELBASE = 3.6
SCENE = "CPB_READY_5車種"

sc = bpy.data.scenes[SCENE]
with bpy.data.libraries.load(SRC, link=False) as (df, dt):
    dt.objects = list(df.objects)
objs = [o for o in dt.objects if o is not None]
col = bpy.data.collections.new("CAR_Formula")
col["rev_car"] = "Formula"
sc.collection.children.link(col)
for o in objs:
    col.objects.link(o)
by = {o.name.split(".")[0]: o for o in objs}
root = by["Formula_all"]
shadow = by.get("Formula_shadow")
if shadow:
    objs = [o for o in objs if o != shadow]
    bpy.data.objects.remove(shadow, do_unlink=True)
# 元のリグ（ホイールを動かす拘束、ハンドル・揺れのエンプティとそのアニメーション、車体の上下）は外す。
# 動きはすべて焼き込みで付けるので、残すと焼き込んだ動きとぶつかる
for o in objs:
    for c in list(o.constraints):
        o.constraints.remove(c)
    o.animation_data_clear()
for k_ in [k_ for k_ in by if k_.startswith(("Formula_handle", "Formula_shake"))]:
    objs = [o for o in objs if o != by[k_]]
    bpy.data.objects.remove(by.pop(k_), do_unlink=True)
wheels = {"FL": by["Formula_L_フロント"], "FR": by["Formula_R_フロント"], "RL": by["Formula_L_リア"], "RR": by["Formula_R_リア"]}
bpy.context.view_layer.update()

# ---- 実寸に（大きさを形に焼き込む）
wb = (wheels["FL"].matrix_world.translation - wheels["RL"].matrix_world.translation).length
S = WHEELBASE / wb
root.scale = (S, S, S)
bpy.context.view_layer.update()
world = {o: o.matrix_world.copy() for o in objs}


def depth(o):
    d = 0
    while o.parent:
        d += 1
        o = o.parent
    return d


done_data = set()
for o in sorted(objs, key=depth):
    loc, rot, sca = world[o].decompose()
    if o.type == 'MESH' and o.data.name not in done_data:
        o.data.transform(Matrix.Diagonal((sca.x, sca.y, sca.z, 1.0)))
        done_data.add(o.data.name)
        for md in o.modifiers:
            if md.type == 'SOLIDIFY':
                md.thickness *= S
    if o.type == 'EMPTY':
        o.empty_display_size *= S
for o in sorted(objs, key=depth):
    loc, rot, sca = world[o].decompose()
    o.matrix_world = Matrix.LocRotScale(loc, rot, Vector((1, 1, 1)))
bpy.context.view_layer.update()

# ---- 4輪は親なし（向きと位置はそのまま）
for k, w in wheels.items():
    mw = w.matrix_world.copy()
    w.parent = None
    w.matrix_world = mw
    w["rev_role"] = k
root["rev_role"] = "BODY"
# 名前を他の車と同じ流儀に（CPB_<車種>_...）
rename = {root: "CPB_Formula_BODY"}
for k, w in wheels.items():
    rename[w] = f"CPB_Formula_{k}"
for o in objs:
    if o not in rename:
        rename[o] = "CPB_Formula_" + o.name.split(".")[0].replace("Formula_", "")
for o, nm in rename.items():
    o.name = nm

# 他の車と同じ地面の高さ（ホイールの接地が z=0）に置き、他の車の横に並べる
bpy.context.view_layer.update()
bottom = min((w.matrix_world @ Vector(c)).z for w in wheels.values() for c in w.bound_box)
dz = -bottom
for o in [root] + list(wheels.values()):
    o.location.z += dz
    o.location.x += 13.5
bpy.context.view_layer.update()

# ---- マテリアル: 他の車と同じトゥーンの陰影 × リバリーのテクスチャ
RAMPS_REF = None
if REF:
    with bpy.data.libraries.load(REF, link=False) as (df, dt2):
        dt2.materials = ["DTM_190E_EvoII_toon.001"] if "DTM_190E_EvoII_toon.001" in df.materials else []
    if dt2.materials and dt2.materials[0]:
        ref_m = dt2.materials[0]
        RAMPS_REF = {n.name: [(e.position, tuple(e.color)) for e in n.color_ramp.elements]
                     for n in ref_m.node_tree.nodes if n.type == 'VALTORGB'}
        bpy.data.materials.remove(ref_m)
BLUE = (0.10, 0.25, 0.83)          # 参考の R32 の「車の色」。白に置き換えて、色はテクスチャに任せる


def whiten(c):
    """車の色（青）の所は白に、それ以外（灰・紺の陰）はそのまま"""
    if sum(abs(a - b) for a, b in zip(c[:3], BLUE)) < 0.25:
        return (1.0, 1.0, 1.0, 1.0)
    return c


def convert(m):
    nt = m.node_tree
    N, L = nt.nodes, nt.links
    if RAMPS_REF:
        for n in N:
            if n.type == 'VALTORGB' and n.name in RAMPS_REF:
                el = n.color_ramp.elements
                ref = RAMPS_REF[n.name]
                while len(el) > len(ref):
                    el.remove(el[-1])
                while len(el) < len(ref):
                    el.new(1.0)
                for e, (pos, c) in zip(el, ref):
                    e.position = pos
                    e.color = whiten(c)
    # リバリー: ドライバーをやめて、オブジェクトのプロパティ cpb_livery（0/1/2）で選ぶ
    if m.node_tree.animation_data:
        for d in list(m.node_tree.animation_data.drivers):
            m.node_tree.animation_data.drivers.remove(d)
    ctrl = N.get("CTRL_livery")
    tex_mix = N.get("Mix.001")
    shade = N.get("ミックス.003")
    out = next(n for n in N if n.type == 'OUTPUT_MATERIAL' and n.is_active_output)
    if ctrl is not None:
        at = N.new("ShaderNodeAttribute")
        at.attribute_type = 'OBJECT'
        at.attribute_name = "cpb_livery"
        for l in list(ctrl.outputs[0].links):
            L.new(at.outputs["Fac"], l.to_socket)
    col_src = tex_mix.outputs[2] if tex_mix is not None else None
    # 色相: オブジェクトのプロパティ cpb_hue（0.5 でそのまま）
    hsv = N.new("ShaderNodeHueSaturation")
    ah = N.new("ShaderNodeAttribute")
    ah.attribute_type = 'OBJECT'
    ah.attribute_name = "cpb_hue"
    add = N.new("ShaderNodeMath")
    add.operation = 'ADD'
    add.inputs[1].default_value = 0.5
    L.new(ah.outputs["Fac"], add.inputs[0])
    L.new(add.outputs[0], hsv.inputs["Hue"])
    if col_src is not None:
        L.new(col_src, hsv.inputs["Color"])
    mul = N.new("ShaderNodeMix")
    mul.data_type = 'RGBA'
    mul.blend_type = 'MULTIPLY'
    mul.inputs[0].default_value = 1.0
    L.new(hsv.outputs[0], mul.inputs[6])
    L.new(shade.outputs[2], mul.inputs[7])
    L.new(mul.outputs[2], out.inputs["Surface"])
    for n, dx in ((at if ctrl is not None else None, 0), (ah, 0), (add, 1), (hsv, 2), (mul, 3)):
        if n is not None:
            n.location = (out.location.x - 800 + dx * 180, out.location.y - 400)
    m.blend_method = 'OPAQUE'
    return m


if TEXDIR:
    import os
    for nm in ("Formula_tex_body", "Formula_tex_body_v1", "Formula_tex_body_v2"):
        im = bpy.data.images.get(nm)
        pth = os.path.join(TEXDIR, nm + ".png")
        if im is None or not os.path.exists(pth):
            continue
        new = bpy.data.images.load(pth)
        im.pixels[:] = new.pixels[:]
        im.pack()
        bpy.data.images.remove(new)
        print("TEX replaced", nm)
fm = sorted({sl.material.name for o in objs if o.type == 'MESH' for sl in o.material_slots
             if sl.material and sl.material.name.startswith("Formula_") and sl.material.name != "Formula_shadow"})
for nm in fm:
    convert(bpy.data.materials[nm])
for o in objs:
    if o.type == 'MESH':
        o["cpb_livery"] = 0.0
        o["cpb_hue"] = 0.0
print("FORMULA scale %.4f wheelbase %.2f m" % (S, WHEELBASE), "mats", fm, "ramps", bool(RAMPS_REF),
      "dims", tuple(round(x, 2) for x in by["Formula_body"].dimensions))
bpy.ops.wm.save_as_mainfile(filepath=OUT, compress=True)
print("SAVED", OUT)

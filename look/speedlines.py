"""車の進行方向に流れる線（スピード線）を付ける（焼き込み済みの .blend のコピーで実行）

blender -b 入力.blend --python speedlines.py -- 出力.blend [色(#rrggbb)] [all|hero]

・各車の焼き込み済みの動きから、毎フレーム車体の周りに「線の芽」を置く（点群）
・線はその場に留まり、進行方向の後ろへ伸びた細い帯として描かれ、数フレームで細く短くなって消える
・帯はアクティブカメラの方を向く（横から見ても細くならない）
・寿命・長さ・太さ・色はモディファイアーの入力で後から直せる（量は再実行で変える）
"""
import bpy
import random
import sys
from mathutils import Vector

DENSITY = 0.022     # 1フレームあたり、速さ(km/h)×この値の本数を出す（160km/h で 3〜4本）
MIN_KMH = 40        # これより遅いときは出さない
LIFE = 7.0          # 線の寿命（フレーム）
LENGTH = 2.2        # 線の長さ = 1フレームに進む距離 × この値
WIDTH = 0.022       # 線の太さ（m）
NEAR = 5.0          # カメラからこれより近い線は出さない（m）（画面いっぱいの太い線を防ぐ）
SPREAD = 1.4        # 車体の横・上へどこまで離れて出すか（m）


def hx(s):
    s = s.lstrip("#")
    c = [int(s[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c) + (1.0,)


def cars_of(sc):
    s = sc.cpb
    out = [(s.body, [s.wheel_fl, s.wheel_fr, s.wheel_rl, s.wheel_rr])]
    out += [(c.body, [c.wheel_fl, c.wheel_fr, c.wheel_rl, c.wheel_rr]) for c in s.cars]
    return out


def sample(sc, cars):
    """全フレームの車の位置・向き・寸法を記録"""
    rec = {b.name: [] for b, _ in cars}
    for f in range(sc.frame_start, sc.frame_end + 1):
        sc.frame_set(f)
        for b, ws in cars:
            M = b.matrix_world.copy()
            wl = [M.inverted() @ w.matrix_world.translation for w in ws]
            rec[b.name].append((f, M, wl))
    return rec


def build_points(sc, rec, seed=3):
    rnd = random.Random(seed)
    fps = sc.render.fps / sc.render.fps_base
    P, birth, dirs, spd = [], [], [], []
    for nm, rows in rec.items():
        for i in range(1, len(rows)):
            f, M, wl = rows[i]
            v = M.translation - rows[i - 1][1].translation
            kmh = v.length * fps * 3.6
            if kmh < MIN_KMH:
                continue
            hw = max(abs(p.x) for p in wl) + 0.15
            ys = [p.y for p in wl]
            y0, y1 = min(ys) - 0.9, max(ys) + 0.6
            zb = min(p.z for p in wl)
            n = kmh * DENSITY
            n = int(n) + (1 if rnd.random() < n - int(n) else 0)
            for _ in range(n):
                side = rnd.choice((-1, 1))
                up = rnd.random() < 0.15
                if up:   # 屋根の上を流れる線
                    lp = Vector((rnd.uniform(-hw, hw) * 0.7, rnd.uniform(y0, y1), zb + rnd.uniform(1.25, 1.25 + SPREAD * 0.6)))
                else:    # 横を流れる線
                    lp = Vector((side * (hw + rnd.uniform(0.05, SPREAD)), rnd.uniform(y0, y1), zb + rnd.uniform(0.05, 1.3)))
                # 1フレームの間のどこかで生まれたことにして、出方の段差をなくす
                t = rnd.random()
                wp = (rows[i - 1][1].lerp(M, t) if hasattr(M, "lerp") else M) @ lp
                P.append(wp)
                birth.append(f - 1 + t)
                dirs.append(v.normalized())
                spd.append(v.length)
    return P, birth, dirs, spd


def node_group(color):
    ng = bpy.data.node_groups.new("流れる線", "GeometryNodeTree")
    I = ng.interface
    I.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    for nm, val in (("寿命", LIFE), ("長さ", LENGTH), ("太さ", WIDTH), ("カメラ近く", NEAR)):
        s = I.new_socket(nm, in_out="INPUT", socket_type="NodeSocketFloat")
        s.default_value = val
        s.min_value = 0.0
    s = I.new_socket("材質", in_out="INPUT", socket_type="NodeSocketMaterial")
    I.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    N, Lk = ng.nodes, ng.links
    gi, go = N.new("NodeGroupInput"), N.new("NodeGroupOutput")

    def attr(name, typ):
        a = N.new("GeometryNodeInputNamedAttribute")
        a.data_type = typ
        a.inputs["Name"].default_value = name
        return a.outputs["Attribute"]

    def math(op, a, b):
        m = N.new("ShaderNodeMath")
        m.operation = op
        for k, x in enumerate((a, b)):
            if isinstance(x, (int, float)):
                m.inputs[k].default_value = x
            else:
                Lk.new(x, m.inputs[k])
        return m.outputs[0]

    st = N.new("GeometryNodeInputSceneTime")
    age = math('SUBTRACT', st.outputs["Frame"], attr("birth", 'FLOAT'))
    life = gi.outputs["寿命"]
    alive_a = math('GREATER_THAN', age, -0.0001)
    alive_b = math('LESS_THAN', age, life)
    alive = math('MULTIPLY', alive_a, alive_b)
    # カメラに近すぎる線は消す
    cam0 = N.new("GeometryNodeInputActiveCamera")
    oi0 = N.new("GeometryNodeObjectInfo")
    Lk.new(cam0.outputs[0], oi0.inputs["Object"])
    pos0 = N.new("GeometryNodeInputPosition")
    dist = N.new("ShaderNodeVectorMath")
    dist.operation = 'DISTANCE'
    Lk.new(oi0.outputs["Location"], dist.inputs[0])
    Lk.new(pos0.outputs[0], dist.inputs[1])
    far = math('GREATER_THAN', dist.outputs["Value"], gi.outputs["カメラ近く"])
    alive = math('MULTIPLY', alive, far)
    dead = math('SUBTRACT', 1.0, alive)
    dl = N.new("GeometryNodeDeleteGeometry")
    Lk.new(gi.outputs["Geometry"], dl.inputs["Geometry"])
    Lk.new(dead, dl.inputs["Selection"])
    # 残り = 1 - 年齢/寿命（細く短くなって消える）
    rest = math('SUBTRACT', 1.0, math('DIVIDE', age, life))
    # 帯（y が 0〜-1 の細長い四角）
    grid = N.new("GeometryNodeMeshGrid")
    grid.inputs["Size X"].default_value = 1.0
    grid.inputs["Size Y"].default_value = 1.0
    grid.inputs["Vertices X"].default_value = 2
    grid.inputs["Vertices Y"].default_value = 2
    tr = N.new("GeometryNodeTransform")
    tr.inputs["Translation"].default_value = (0, -0.5, 0)
    Lk.new(grid.outputs["Mesh"], tr.inputs["Geometry"])
    # 向き: 長さ方向(Y)を進行方向へ、面(Z)をカメラへ
    dirv = attr("dir", 'FLOAT_VECTOR')
    al1 = N.new("FunctionNodeAlignEulerToVector")
    al1.axis = 'Y'
    Lk.new(dirv, al1.inputs["Vector"])
    cam = N.new("GeometryNodeInputActiveCamera")
    oi = N.new("GeometryNodeObjectInfo")
    Lk.new(cam.outputs[0], oi.inputs["Object"])
    pos = N.new("GeometryNodeInputPosition")
    tocam = N.new("ShaderNodeVectorMath")
    tocam.operation = 'SUBTRACT'
    Lk.new(oi.outputs["Location"], tocam.inputs[0])
    Lk.new(pos.outputs[0], tocam.inputs[1])
    al2 = N.new("FunctionNodeAlignEulerToVector")
    al2.axis = 'Z'
    al2.pivot_axis = 'Y'
    Lk.new(al1.outputs[0], al2.inputs["Rotation"])
    Lk.new(tocam.outputs[0], al2.inputs["Vector"])
    # 大きさ: 太さ×残り, 進んだ距離×長さ×残り
    w = math('MULTIPLY', gi.outputs["太さ"], rest)
    ln = math('MULTIPLY', math('MULTIPLY', attr("spd", 'FLOAT'), gi.outputs["長さ"]), rest)
    cx = N.new("ShaderNodeCombineXYZ")
    Lk.new(w, cx.inputs[0])
    Lk.new(ln, cx.inputs[1])
    cx.inputs[2].default_value = 1.0
    io = N.new("GeometryNodeInstanceOnPoints")
    Lk.new(dl.outputs["Geometry"], io.inputs["Points"])
    Lk.new(tr.outputs["Geometry"], io.inputs["Instance"])
    Lk.new(al2.outputs[0], io.inputs["Rotation"])
    Lk.new(cx.outputs[0], io.inputs["Scale"])
    rz = N.new("GeometryNodeRealizeInstances")
    Lk.new(io.outputs[0], rz.inputs[0])
    sm = N.new("GeometryNodeSetMaterial")
    Lk.new(rz.outputs[0], sm.inputs["Geometry"])
    Lk.new(gi.outputs["材質"], sm.inputs["Material"])
    Lk.new(sm.outputs[0], go.inputs[0])
    return ng


def material(color):
    m = bpy.data.materials.get("流れる線") or bpy.data.materials.new("流れる線")
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    rgb = nt.nodes.new("ShaderNodeRGB")
    rgb.outputs[0].default_value = color
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(rgb.outputs[0], out.inputs["Surface"])
    m.shadow_method = 'NONE'
    return m


def main():
    args = sys.argv[sys.argv.index("--") + 1:]
    out = args[0]
    color = hx(args[1]) if len(args) > 1 else hx("#ffffff")
    who = args[2] if len(args) > 2 else "all"
    sc = bpy.context.scene
    cars = cars_of(sc)
    if who == "hero":
        cars = cars[:1]
    rec = sample(sc, cars)
    P, birth, dirs, spd = build_points(sc, rec)
    me = bpy.data.meshes.new("流れる線_点")
    me.from_pydata([tuple(p) for p in P], [], [])
    a = me.attributes.new("birth", 'FLOAT', 'POINT')
    a.data.foreach_set("value", birth)
    a = me.attributes.new("dir", 'FLOAT_VECTOR', 'POINT')
    a.data.foreach_set("vector", [c for d in dirs for c in d])
    a = me.attributes.new("spd", 'FLOAT', 'POINT')
    a.data.foreach_set("value", spd)
    ob = bpy.data.objects.new("流れる線", me)
    col = bpy.data.collections.get("流れる線") or bpy.data.collections.new("流れる線")
    if col.name not in sc.collection.children:
        sc.collection.children.link(col)
    col.objects.link(ob)
    md = ob.modifiers.new("流れる線", 'NODES')
    md.node_group = node_group(color)
    md[md.node_group.interface.items_tree["材質"].identifier] = material(color)
    ob.visible_shadow = False
    sc.frame_set(sc.frame_start)
    print("SPEEDLINES", sc.name, "points", len(P), "cars", len(cars))
    bpy.ops.wm.save_as_mainfile(filepath=out, compress=True)
    print("SAVED", out)


main()

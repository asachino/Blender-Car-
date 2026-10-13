"""R32 / テスタロッサ / S2000 の3台を1つのシーンで使う準備（コピーした .blend の上でだけ行う）

link_into("R32")  … 別シーンの車を R32 シーンにも入れる（RS.scene() で他のシーンを消す前に呼ぶ）
setup(sc)         … 車ごとに「地面の中心」に親エンプティを作り、R32 と同じ縮尺にそろえ、
                    ホイールの原点を車輪の中心に直す。 {"R32": (ボディ, [前左, 前右, 後左, 後右]), ...} を返す
"""
import bpy
from mathutils import Vector, Matrix

SPEC = {
    "R32": dict(root="R32", name="R32",
                wheels=("DTM_190E_EvoII_L_フロント.001", "DTM_190E_EvoII_R_フロント.001",
                        "DTM_190E_EvoII_L_リア.001", "DTM_190E_EvoII_R_リア.001")),
    # 実車の全長の比で R32 にそろえる（R32 4.545m・テスタロッサ 4.485m・S2000 4.135m）
    "TESTA": dict(root="ferrari_testarossa", name="テスタロッサ", length_m=4.485,
                  wheels=("フロントL", "フロントR", "フロントL.001", "フロントR.001")),
    # S2000 はモデルの前が -Y 向き（ホイールの名前の「フロント」は実際には後ろ側）。180°回して前を +Y にそろえる。
    # 回した後の 前左・前右・後左・後右 の順
    "S2000": dict(root="Sketchfab_model", name="S2000", length_m=4.135, flip=True,
                  wheels=("DTM_190E_EvoII_R_リア.003", "DTM_190E_EvoII_L_リア.003",
                          "DTM_190E_EvoII_R_フロント.003", "DTM_190E_EvoII_L_フロント.003")),
}
R32_LEN_M = 4.545

# 車ごとの性格（物理の設定）
PHYS = {
    "R32": dict(drive="AWD", mass=1430, front_weight=0.58, cg_height=0.45),
    "TESTA": dict(drive="RWD", mass=1510, front_weight=0.41, cg_height=0.44),
    "S2000": dict(drive="RWD", mass=1260, front_weight=0.50, cg_height=0.46),
}


def link_into(main="R32"):
    sc = bpy.data.scenes[main]
    for key in ("TESTA", "S2000"):
        top = bpy.data.objects.get(SPEC[key]["root"])
        if top is None:
            continue
        for o in [top] + list(top.children_recursive):
            if o.name not in sc.objects:
                sc.collection.objects.link(o)
            o.hide_render = False
            o.hide_viewport = False


def _world_bbox(objs):
    dg = bpy.context.evaluated_depsgraph_get()
    cs = []
    for o in objs:
        if o.type == 'MESH' and len(o.data.vertices) and "shadow" not in o.name:
            ev = o.evaluated_get(dg)
            cs += [ev.matrix_world @ Vector(b) for b in ev.bound_box]
    mn = Vector([min(v[i] for v in cs) for i in range(3)])
    mx = Vector([max(v[i] for v in cs) for i in range(3)])
    return mn, mx


def _recenter(w):
    """ホイールの原点がずれていると回り方がおかしくなるので、メッシュの中心に移す"""
    me = w.data
    if me.users > 1:
        w.data = me = me.copy()
    vs = [v.co for v in me.vertices]
    c = Vector([(min(v[i] for v in vs) + max(v[i] for v in vs)) / 2 for i in range(3)])
    if c.length < 1e-6:
        return
    mw = w.matrix_world.copy()
    me.transform(Matrix.Translation(-c))
    me.update()
    w.matrix_world = mw @ Matrix.Translation(c)


def _reparent(o, root):
    mw = o.matrix_world.copy()
    o.parent = root
    o.matrix_parent_inverse = Matrix.Identity(4)
    o.matrix_world = mw


def setup(sc):
    out = {"R32": (bpy.data.objects["R32"], [bpy.data.objects[n] for n in SPEC["R32"]["wheels"]])}
    r_mn, r_mx = _world_bbox(bpy.data.objects["R32"].children_recursive)
    r32_len = r_mx.y - r_mn.y
    for key in ("TESTA", "S2000"):
        sp = SPEC[key]
        top = bpy.data.objects[sp["root"]]
        whs = [bpy.data.objects[n] for n in sp["wheels"]]
        bpy.context.view_layer.update()
        for w in whs:
            _recenter(w)
        bpy.context.view_layer.update()
        body_objs = [o for o in [top] + list(top.children_recursive) if o not in whs]
        mn, mx = _world_bbox(body_objs)
        wmn, wmx = _world_bbox(whs)
        wc = [w.matrix_world.translation for w in whs]
        cx = sum(c.x for c in wc) / 4.0
        cy = sum(c.y for c in wc) / 4.0
        root = bpy.data.objects.new(sp["name"], None)
        sc.collection.objects.link(root)
        root.location = (cx, cy, wmn.z)
        bpy.context.view_layer.update()
        _reparent(top, root)
        for w in whs:
            _reparent(w, root)
        k = (sp["length_m"] / R32_LEN_M) * r32_len / (mx.y - mn.y)
        if sp.get("flip"):
            # 親ごと 180°回してから、回った姿勢を子に移す（親の回転は 0 に戻す）
            root.rotation_euler = (0.0, 0.0, 3.141592653589793)
            bpy.context.view_layer.update()
            mws = {o: o.matrix_world.copy() for o in [top] + whs}
            root.rotation_euler = (0.0, 0.0, 0.0)
            bpy.context.view_layer.update()
            for o, mw in mws.items():
                o.matrix_world = mw
        root.location = (0.0, 0.0, 0.0)
        root.scale = (k, k, k)
        bpy.context.view_layer.update()
        out[key] = (root, whs)
    return out


def tree(root):
    return [root] + list(root.children_recursive)


def park(root, where=(0.0, -3000.0, 0.0)):
    """使わない車は遠くへ置いて、レンダーにも出さない"""
    root.location = where
    for o in tree(root):
        o.hide_render = True

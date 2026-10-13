"""5車種のファイル（シーン「CPB_READY_5車種」）を使う準備（コピーした .blend の上でだけ行う）

車ごとのコレクションに rev_car、BODY と4輪に rev_role（BODY / FL / FR / RL / RR）が付いている前提。
実寸（縮尺1）・前は +Y・親なし。ボディのメッシュは BODY（エンプティ）の子、4輪は親なし。

scene()      … 5車種のシーンだけを残す（バックアップのシーンと確認用のコースは消す）
setup(sc)    … {"R32": (BODY, [前左, 前右, 後左, 後右]), "S2000": ..., "F40": ..., "COUNTACH": ..., "TESTA": ...}
place(car, p)… 車（BODY と4輪）を、4輪の中心の真下の地面が p に来るように動かす
"""
import bpy
from mathutils import Vector

SCENE = "CPB_READY_5車種"
KEYS = {"R32": "R32", "S2000": "S2000", "F40": "F40", "Countach": "COUNTACH", "Testarossa": "TESTA"}
NAME = {"R32": "R32", "S2000": "S2000", "F40": "F40", "COUNTACH": "カウンタック", "TESTA": "テスタロッサ"}

# 車ごとの性格（物理の設定）
PHYS = {
    "R32": dict(drive="AWD", mass=1430, front_weight=0.58, cg_height=0.45),
    "S2000": dict(drive="RWD", mass=1260, front_weight=0.50, cg_height=0.46),
    "F40": dict(drive="RWD", mass=1100, front_weight=0.42, cg_height=0.40),
    "COUNTACH": dict(drive="RWD", mass=1450, front_weight=0.42, cg_height=0.43),
    "TESTA": dict(drive="RWD", mass=1510, front_weight=0.41, cg_height=0.44),
}


def scene():
    sc = bpy.data.scenes[SCENE]
    for o in list(bpy.data.scenes):
        if o != sc:
            bpy.data.scenes.remove(o)
    if bpy.context.window is not None:
        bpy.context.window.scene = sc
    col = bpy.data.collections.get("CPB_走行コース")
    if col is not None:
        for o in list(col.objects):
            bpy.data.objects.remove(o, do_unlink=True)
        bpy.data.collections.remove(col)
    sc.cpb.cars.clear()
    sc.render.image_settings.file_format = 'PNG'
    sc.render.resolution_percentage = 100
    return sc


def setup(sc):
    out = {}
    for c in sc.collection.children_recursive:
        nm = c.get("rev_car")
        if not nm or nm not in KEYS:
            continue
        roles = {}
        for o in c.all_objects:
            r = o.get("rev_role")
            if r:
                roles[r] = o
        out[KEYS[nm]] = (roles["BODY"], [roles[k] for k in ("FL", "FR", "RL", "RR")])
    # 以前の焼き込みの基準姿勢（cpb_*）が残っていると、焼き込みで元の位置へ引き戻されるので消す
    for car in out.values():
        for o in tree(car):
            for key in [k_ for k_ in o.keys() if k_.startswith("cpb_")]:
                del o[key]
    return out


def ground_center(car):
    body, whs = car
    cs = [w.matrix_world.translation for w in whs]
    r = sum(max(w.dimensions.y, w.dimensions.z) / 2 for w in whs) / 4
    return Vector((sum(c.x for c in cs) / 4, sum(c.y for c in cs) / 4, sum(c.z for c in cs) / 4 - r))


def tree(car):
    body, whs = car
    return [body] + list(body.children_recursive) + list(whs)


def place(car, p):
    body, whs = car
    bpy.context.view_layer.update()
    d = Vector(p) - ground_center(car)
    for o in [body] + list(whs):
        o.location = o.location + d
    bpy.context.view_layer.update()


def park(car, i=0):
    place(car, (5000 + 60 * i, 5000, 0))
    for o in tree(car):
        o.hide_render = True

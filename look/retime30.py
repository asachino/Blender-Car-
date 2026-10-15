"""焼き込み済みのシーンを 24fps → 30fps にする（実時間の速さはそのまま、コマ数が 1.25 倍になる）

blender -b 入力.blend --python retime30.py -- 出力.blend [新fps]

・全アクションのキー（車・カメラ・飛んだタイヤ・へこみのシェイプキーなど）を 0 フレーム基準で 1.25 倍の位置へ
・シーンのフレーム範囲・マーカー・デモ用のカット割り（scene["demo"]）も同じ倍率で
・スモークや火花は「秒」で動くので fps を変えるだけで合う。「フレーム」を使うノード（タイヤ痕の出現）は
  フレーム × (旧fps/新fps) を挟んで、元の時刻で動くようにする
・旗の波（ウェーブ）の速さも合わせる
"""
import bpy
import json
import sys

args = sys.argv[sys.argv.index("--") + 1:]
out = args[0]
new_fps = int(args[1]) if len(args) > 1 else 30
sc = bpy.context.scene
old_fps = sc.render.fps / sc.render.fps_base
k = new_fps / old_fps


def rf(x):
    return int(round(x * k))


if abs(k - 1.0) > 1e-6:
    for act in bpy.data.actions:
        for fc in act.fcurves:
            for kp in fc.keyframe_points:
                kp.co.x *= k
                kp.handle_left.x *= k
                kp.handle_right.x *= k
            fc.update()
    for g in bpy.data.node_groups:
        for n in list(g.nodes):
            if n.type != 'INPUT_SCENE_TIME' or not n.outputs['Frame'].is_linked:
                continue
            links = list(n.outputs['Frame'].links)
            m = g.nodes.new("ShaderNodeMath")
            m.operation = 'MULTIPLY'
            m.inputs[1].default_value = 1.0 / k
            m.label = "fps換算（旧フレームへ）"
            m.location = (n.location.x + 160, n.location.y - 120)
            g.links.new(n.outputs['Frame'], m.inputs[0])
            for l in links:
                g.links.new(m.outputs[0], l.to_socket)
    for o in bpy.data.objects:
        for md in o.modifiers:
            if md.type == 'WAVE':
                md.speed /= k
                md.time_offset *= k
    for scn in bpy.data.scenes:
        scn.frame_start = rf(scn.frame_start)
        scn.frame_end = rf(scn.frame_end)
        for mk in scn.timeline_markers:
            mk.frame = rf(mk.frame)
        if "demo" in scn:
            meta = json.loads(scn["demo"])
            meta["shots"] = [[c, rf(a) if i == 0 else rf(a), rf(b + 1) - 1] for i, (c, a, b) in enumerate(meta["shots"])]
            if meta["shots"]:
                meta["shots"][0][1] = scn.frame_start
            if meta.get("replay"):
                c, a, b, sp = meta["replay"]
                meta["replay"] = [c, rf(a), rf(b), sp]
            scn["demo"] = json.dumps(meta, ensure_ascii=False)
        rbw = scn.rigidbody_world
        if rbw is not None:
            rbw.point_cache.frame_start = rf(rbw.point_cache.frame_start)
            rbw.point_cache.frame_end = rf(rbw.point_cache.frame_end)
for scn in bpy.data.scenes:
    scn.render.fps = new_fps
    scn.render.fps_base = 1.0
print("RETIME", old_fps, "->", new_fps, "frames", sc.frame_start, sc.frame_end, "meta", sc.get("demo", "")[:200])
bpy.ops.wm.save_as_mainfile(filepath=out, compress=True)
print("SAVED", out)

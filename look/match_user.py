"""ユーザーが作った .blend のルックをそのまま別のシーンへ移す（空・車・サーキット・レンダー設定）

blender -b シーン.blend --python match_user.py -- 元.blend 出力.blend [元のシーン名]

  空        : 元のシーンの World をそのまま読み込んで使う（背景の透過はオフにして空を見せる）
  車        : 元ファイルの同じ車種の車（色違いでない方）の、部品ごとのマテリアル割り当てをそのまま写す
  サーキット: 同じ名前のマテリアルは元のものに置き換え、名前の違うものは MAP で近いものに置き換える
  設定      : 色の管理・EEVEE の設定（影・AO・ブルームなど）を元のシーンに合わせる
元ファイルは読むだけで変更しない。
"""
import bpy
import json
import re
import subprocess
import sys

args = sys.argv[sys.argv.index("--") + 1:]
SRC, OUT = args[0], args[1]
SRC_SCENE = args[2] if len(args) > 2 else "オリジナルカメラ_オーバーテイク"

# デモシーンにしか無いマテリアル → 元ファイルのマテリアル
MAP = {
    "アスファルト": "道路", "ランオフ舗装": "道路", "地面": "芝", "葉1": "芝", "葉2": "芝",
    "白": "建物白", "赤": "サーキット赤", "オレンジ": "サーキット黄",
    "砂利": "芝", "土": "芝", "幹": "濃灰",
    "CPB_バリヤ黒": "濃灰", "CPB_バリヤ赤": "サーキット赤", "CPB_バリヤ白": "建物白",
}
MODEL = re.compile(r"^CPB_(R32|F40|Countach|Testarossa|S2000|Formula)_")
SUFFIX = re.compile(r"\.\d{3}$")


def base(name):
    return SUFFIX.sub("", name)


# ---- 元ファイルを別の Blender で開いて、車の部品ごとの割り当てと設定を書き出す
DUMP = r'''
import bpy, json, re, sys
MODEL = re.compile(r"^CPB_(R32|F40|Countach|Testarossa|S2000|Formula)_")
SUFFIX = re.compile(r"\.\d{3}$")
sc = bpy.data.scenes[sys.argv[-2]]
s = sc.cpb
# 主役と、色違いでない4台（色違いは名前に _黄 などが付く）
items = [s] + [c for c in s.cars if SUFFIX.sub("", c.body.name) in ("F40", "カウンタック", "テスタロッサ", "S2000")]
cars = {}
for c in items:
    objs = [c.body] + list(c.body.children_recursive)
    for w in (c.wheel_fl, c.wheel_fr, c.wheel_rl, c.wheel_rr):
        if w:
            objs += [w] + list(w.children_recursive)
    for o in objs:
        mm = MODEL.match(o.name)
        if mm and o.type == 'MESH':
            cars.setdefault(mm.group(1), {}).setdefault(
                SUFFIX.sub("", o.name), [(sl.material.name if sl.material else None, sl.link) for sl in o.material_slots])
ee = sc.eevee
keys = ["taa_render_samples", "use_gtao", "gtao_distance", "use_bloom", "bloom_intensity", "bloom_threshold",
        "use_ssr", "use_soft_shadows", "use_shadows", "shadow_cascade_size", "shadow_cube_size"]
out = dict(cars=cars, world=sc.world.name, film=sc.render.film_transparent, fps=sc.render.fps,
           eevee={k: getattr(ee, k) for k in keys if hasattr(ee, k)},
           view=dict(view_transform=sc.view_settings.view_transform, look=sc.view_settings.look,
                     exposure=sc.view_settings.exposure, gamma=sc.view_settings.gamma),
           mats=[m.name for m in bpy.data.materials])
open(sys.argv[-1], "w", encoding="utf-8").write(json.dumps(out, ensure_ascii=False))
'''


def dump_source():
    import os
    import tempfile
    tmp = tempfile.mkdtemp()
    py = os.path.join(tmp, "dump.py")
    js = os.path.join(tmp, "dump.json")
    open(py, "w", encoding="utf-8").write(DUMP)
    subprocess.run([bpy.app.binary_path, "-b", SRC, "--python", py, "--", SRC_SCENE, js],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    return json.loads(open(js, encoding="utf-8").read())


def main():
    info = dump_source()
    sc = bpy.context.scene
    src_mats = set(info["mats"])
    # 使うマテリアルを集める
    need = set()
    for d in info["cars"].values():
        for slots in d.values():
            need.update(n for n, _ in slots if n)
    scene_mats = {sl.material.name for o in sc.objects if o.type == 'MESH' for sl in o.material_slots if sl.material}
    env = {}
    for n in scene_mats:
        tgt = n if n in src_mats else MAP.get(n)
        if tgt and tgt in src_mats and not MODEL.match(n) and not n.startswith("OH_"):
            env[n] = tgt
            need.add(tgt)
    want = sorted(need)
    with bpy.data.libraries.load(SRC, link=False) as (df, dt):
        dt.materials = list(want)
        dt.worlds = [info["world"]]
    got = dict(zip(want, dt.materials))   # 元の名前 → 読み込んだマテリアル
    # サーキット
    for n, tgt in env.items():
        old, new = bpy.data.materials.get(n), got.get(tgt)
        if old is not None and new is not None and old != new:
            old.user_remap(new)
    # 車（同じ車種の部品は、元ファイルと同じ割り当てに）
    s = sc.cpb
    roots = [s.body, s.wheel_fl, s.wheel_fr, s.wheel_rl, s.wheel_rr]
    for c in s.cars:
        roots += [c.body, c.wheel_fl, c.wheel_fr, c.wheel_rl, c.wheel_rr]
    done = 0
    for r in roots:
        if not r:
            continue
        for o in [r] + list(r.children_recursive):
            mm = MODEL.match(o.name)
            if not mm or o.type != 'MESH':
                continue
            slots = info["cars"].get(mm.group(1), {}).get(base(o.name))
            if not slots or len(slots) != len(o.material_slots):
                continue
            for sl, (mn, link) in zip(o.material_slots, slots):
                if mn and got.get(mn) is not None:
                    sl.link = link
                    sl.material = got[mn]
                    done += 1
    # 空とレンダー設定
    w = dt.worlds[0]
    for scn in bpy.data.scenes:
        scn.world = w
        scn.render.film_transparent = info.get("film", False)   # 元と同じ（透過なら空は合成用に抜ける）
        for k, v in info["eevee"].items():
            try:
                setattr(scn.eevee, k, v)
            except Exception:
                pass
        for k, v in info["view"].items():
            setattr(scn.view_settings, k, v)
        scn.eevee.use_motion_blur = False
    print("MATCH car slots", done, "env", len(env), "world", w.name)
    bpy.ops.wm.save_as_mainfile(filepath=OUT, compress=True)
    print("SAVED", OUT)


if __name__ == "__main__":
    main()

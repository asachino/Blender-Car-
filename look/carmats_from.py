"""別の .blend（ユーザーが調整したファイル）から車のマテリアルを持ってきて差し替える

blender -b シーン.blend --python carmats_from.py -- 元.blend 出力.blend

シーンの車（cpb の本体・2台目以降・4輪とその子）が使っているマテリアルと同じ名前のものを
元ファイルから読み込み、置き換える（輪郭線 OH_Outline_* も含む）。元ファイルは読むだけ。
"""
import bpy
import sys

args = sys.argv[sys.argv.index("--") + 1:]
src, out = args[0], args[1]
sc = bpy.context.scene
s = sc.cpb
roots = [s.body, s.wheel_fl, s.wheel_fr, s.wheel_rl, s.wheel_rr]
for c in s.cars:
    roots += [c.body, c.wheel_fl, c.wheel_fr, c.wheel_rl, c.wheel_rr]
objs = set()
for r in roots:
    if r:
        objs.add(r)
        objs.update(r.children_recursive)
names = sorted({sl.material.name for o in objs if o.type == 'MESH' for sl in o.material_slots if sl.material})
with bpy.data.libraries.load(src, link=False) as (data_from, data_to):
    want = [n for n in names if n in data_from.materials]
    data_to.materials = list(want)
done = []
for base, new in zip(want, data_to.materials):   # 読み込んだ方は .001 などが付くので、頼んだ順で対応させる
    old = bpy.data.materials.get(base)
    if new is None or old is None or old == new:
        continue
    old.user_remap(new)
    bpy.data.materials.remove(old)
    new.name = base
    done.append(base)
print("CARMATS replaced", done)
bpy.ops.wm.save_as_mainfile(filepath=out, compress=True)
print("SAVED", out)

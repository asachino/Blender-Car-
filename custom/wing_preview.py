"""ウイングの候補を R32（カスタム画面のシーン）に付けて、斜め後ろと横から撮る

blender -b custom_r32_v3.blend --python wing_preview.py -- 出力フォルダ [フレーム]
"""
import bpy
import bmesh
import os
import sys
from mathutils import Vector, Matrix

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import wings_lib as WL  # noqa: E402

args = sys.argv[sys.argv.index("--") + 1:]
OUT = args[0]
FRAME = int(args[1]) if len(args) > 1 else 360
sc = bpy.context.scene
r32b = bpy.data.objects["CPB_R32_BODY"]
sc.frame_set(1)
rest = r32b.location.copy()
D = 0.988
body_main = bpy.data.objects["CPB_R32_DTM_190E_EvoII_body.001"]
m_paint = body_main.material_slots[0].material
m_carbon = bpy.data.materials.get("カーボン")
outline = bpy.data.materials.get("OH_Outline_Material")


def flat(name, col):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    rgb = nt.nodes.new("ShaderNodeRGB")
    rgb.outputs[0].default_value = col
    o = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(rgb.outputs[0], o.inputs["Surface"])
    return m


m_black = flat("ウイング_黒", (0.006, 0.007, 0.012, 1))
MAT = {"本体": m_carbon, "翼端板": m_black, "支柱": m_black, "本体同色": m_paint, "支柱同色": m_paint}
col = bpy.data.collections.new("ウイング候補")
sc.collection.children.link(col)
for c in bpy.data.collections:
    if c.name.startswith("ウイング") and c != col:
        c.hide_render = True
sc.frame_set(FRAME)
cd = bpy.data.cameras.new("候補カメラ")
cd.lens = 45
cam = bpy.data.objects.new("候補カメラ", cd)
sc.collection.objects.link(cam)
sc.camera = cam
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = 960, 540, 100
sc.render.image_settings.file_format = 'PNG'
sc.render.image_settings.color_mode = 'RGB'
VIEWS = [("斜め後ろ", Vector((-3.0, -4.7, 1.25)), Vector((0, -1.5, 0.45))),
         ("横", Vector((-5.6, -1.1, 0.2)), Vector((0, -1.1, 0.35)))]
for ci, (name, fn) in enumerate(WL.CANDIDATES):
    objs = []
    for part, bm in fn(D).items():
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        me = bpy.data.meshes.new(f"候補_{name}_{part}")
        bm.to_mesh(me)
        bm.free()
        o = bpy.data.objects.new(f"候補_{name}_{part}", me)
        me.materials.append(MAT[part])
        if outline:
            me.materials.append(outline)
            sd = o.modifiers.new("輪郭", 'SOLIDIFY')
            sd.thickness, sd.offset, sd.use_flip_normals, sd.use_rim = 0.006, 1.0, True, False
            sd.material_offset = 1
        col.objects.link(o)
        o.parent = r32b
        o.matrix_parent_inverse = Matrix.Translation(-rest)
        objs.append(o)
    bpy.context.view_layer.update()
    Mb = r32b.matrix_world
    for vi, (vn, eye, tgt) in enumerate(VIEWS):
        cam.location = Mb @ eye
        cam.rotation_euler = ((Mb @ tgt) - cam.location).to_track_quat('-Z', 'Y').to_euler()
        sc.render.filepath = os.path.join(OUT, f"wing_{ci}_{vi}.png")
        bpy.ops.render.render(write_still=True)
    for o in objs:
        bpy.data.objects.remove(o, do_unlink=True)
    print("CAND", ci, name)

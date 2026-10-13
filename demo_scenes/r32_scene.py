"""R32（ユーザーのモデル）を使ったテスト・デモ用のシーン準備。
コピーした .blend を開いた状態で使う（元ファイルは保存しない）。"""
import bpy, math, os, sys
from mathutils import Vector
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tut_scene as T

WHEELS = ("DTM_190E_EvoII_L_フロント.001", "DTM_190E_EvoII_R_フロント.001",
          "DTM_190E_EvoII_L_リア.001", "DTM_190E_EvoII_R_リア.001")


def scene():
    sc = bpy.data.scenes["R32"]
    # テスト用コピーでは他のシーンを消して R32 だけにする（元ファイルは保存しない）
    for o in list(bpy.data.scenes):
        if o != sc:
            bpy.data.scenes.remove(o)
    if bpy.context.window is not None:
        bpy.context.window.scene = sc
    # 同じシーンにある別の車（Plane）は使わないので外す
    for o in list(sc.objects):
        if o.name == "Plane" or (o.parent is not None and o.parent.name == "Plane"):
            for c in list(o.users_collection):
                c.objects.unlink(o)
    sc.render.image_settings.file_format = 'PNG'
    sc.render.resolution_percentage = 100
    return sc


def car():
    return bpy.data.objects["R32"], [bpy.data.objects[n] for n in WHEELS]


def ground(sc, k, flat=False, size=420, center=(40, 60)):
    """tut_scene の地面を k 倍の大きさで作る"""
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=280, y_subdivisions=280, size=size * k,
                                    location=(center[0] * k, center[1] * k, 0), calc_uvs=True)
    g = bpy.context.object
    g.name = "Ground"
    if not flat:
        for v in g.data.vertices:
            x, y = v.co.x + center[0] * k, v.co.y + center[1] * k
            v.co.z = T.ground_height(x / k, y / k) * k
    for d in g.data.uv_layers.active.data:
        d.uv = d.uv * (size / 8.0)
    gm = T._ground_mat()
    bs = next(n for n in gm.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    bs.inputs['Roughness'].default_value = 1.0
    if 'Specular IOR Level' in bs.inputs:
        bs.inputs['Specular IOR Level'].default_value = 0.0
    g.data.materials.append(gm)
    for p in g.data.polygons:
        p.use_smooth = True
    if g.name not in sc.collection.objects:
        for c in list(g.users_collection):
            c.objects.unlink(g)
        sc.collection.objects.link(g)
    return g


def course(sc, pts, k, name="Course", cyclic=False):
    ob = T.build_course([(x * k, y * k) for x, y in pts], name=name, cyclic=cyclic)
    if ob.name not in sc.collection.objects:
        sc.collection.objects.link(ob)
    return ob


def assign(sc, path=None, g=None):
    s = sc.cpb
    body, wh = car()
    s.body = body
    s.wheel_fl, s.wheel_fr, s.wheel_rl, s.wheel_rr = wh
    s.forward_axis = "POS_Y"
    s.path, s.ground = path, g
    s.preset = "SPORTS"
    s.drive = "AWD"           # R32 GT-R は4WD
    return s


def world_light(sc):
    """黒い背景だと地面が見えにくいので、デモ用に空色と太陽光を足す"""
    w = sc.world or bpy.data.worlds.new("W")
    sc.world = w
    w.use_nodes = False
    w.color = (0.5, 0.62, 0.8)
    ld = bpy.data.lights.new("DemoSun", 'SUN')
    ld.energy = 3.0
    lo = bpy.data.objects.new("DemoSun", ld)
    sc.collection.objects.link(lo)
    lo.rotation_euler = (math.radians(50), math.radians(10), math.radians(30))
    if hasattr(sc.eevee, "taa_render_samples"):
        sc.eevee.taa_render_samples = 16


def follow_cam(sc, target, f0, f1, k, dist=9, height=3, side=2.5, smooth=0.08, look_up=0.6, lens=35, name="ChaseCam"):
    cam = T.follow_camera(sc, target, f0, f1, dist=dist * k, height=height * k, side=side * k,
                          smooth=smooth, look_up=look_up * k, lens=lens, name=name, fwd_axis=(0, 1, 0))
    cam.data.clip_end = 400 * k
    cam.data.clip_start = 0.1 * k
    return cam

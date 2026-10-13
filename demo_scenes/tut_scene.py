"""チュートリアル用デモシーンの構築（Blender内で実行）"""
import bpy, bmesh, math
from mathutils import Vector, Matrix


def _mat(name, color):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.diffuse_color = color
    m.use_nodes = False
    return m


def _checker_image(name, size, c1, c2, n, line=None, lw=2):
    img = bpy.data.images.get(name)
    if img is not None:
        return img
    img = bpy.data.images.new(name, size, size)
    cell = size // n
    px = []
    for y in range(size):
        for x in range(size):
            if line is not None and (x % cell < lw or y % cell < lw):
                c = line
            else:
                c = c1 if ((x // cell) + (y // cell)) % 2 == 0 else c2
            px.extend(c)
    img.pixels.foreach_set(px)
    img.pack()
    return img


def _tex_mat(name, img):
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = next(n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED')
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    tex.interpolation = 'Closest'
    nt.links.new(tex.outputs[0], bsdf.inputs[0])
    return m


def _ground_mat():
    img = _checker_image("GroundTex", 256, (0.66, 0.68, 0.62, 1), (0.58, 0.61, 0.55, 1), 2,
                         line=(0.9, 0.9, 0.86, 1), lw=2)
    return _tex_mat("GroundMat", img)


def _tire_mat():
    img = _checker_image("TireTex", 64, (0.03, 0.03, 0.03, 1), (0.55, 0.55, 0.58, 1), 4)
    return _tex_mat("TireMat", img)


def ground_height(x, y):
    z = 1.4 * math.sin(x * 0.035 + 0.5) * math.cos(y * 0.03) + 0.6 * math.sin(y * 0.07)
    # ジャンプ台
    if 48 <= y < 58 and -7 < x < 7:
        z += (y - 48) * 0.17
    # ガタガタ区間
    if 15 <= y < 35 and -7 < x < 7:
        z += 0.06 * math.sin(x * 2.0) * math.sin(y * 2.4)
    return z


def build_ground(flat=False, size=420, center=(40, 60)):
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=280, y_subdivisions=280, size=size,
                                    location=(center[0], center[1], 0), calc_uvs=True)
    g = bpy.context.object
    g.name = "Ground"
    if not flat:
        for v in g.data.vertices:
            v.co.z = ground_height(v.co.x + center[0], v.co.y + center[1])
    uv = g.data.uv_layers.active.data
    for d in uv:
        d.uv = d.uv * (size / 8.0)
    g.data.materials.append(_ground_mat())
    for p in g.data.polygons:
        p.use_smooth = True
    return g


def build_car(loc=(0, 0)):
    """-Y が正面。ボディ1つ＋タイヤ4本（ボディの子）＋室内ハンドル"""
    x0, y0 = loc
    bm = bmesh.new()
    def box(cx, cy, cz, sx, sy, sz):
        r = bmesh.ops.create_cube(bm, size=1.0)
        for v in r["verts"]:
            v.co = Vector((v.co.x * sx + cx, v.co.y * sy + cy, v.co.z * sz + cz))
    box(0, 0, 0.0, 1.8, 4.4, 0.55)      # 下半分
    box(0, 0.35, 0.5, 1.5, 2.2, 0.5)    # キャビン
    me = bpy.data.meshes.new("Body")
    bm.to_mesh(me)
    bm.free()
    body = bpy.data.objects.new("Body", me)
    bpy.context.scene.collection.objects.link(body)
    body.location = (x0, y0, 0.75)
    bev = body.modifiers.new("Bevel", 'BEVEL')
    bev.width = 0.08
    bev.segments = 3
    body.data.materials.append(_mat("Paint", (0.8, 0.08, 0.06, 1)))
    # 窓（見た目用・ボディの子）
    wins = []
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x0, y0 - 0.78, 1.25))
    w = bpy.context.object; w.scale = (1.42, 0.05, 0.38); w.name = "Windshield"
    w.data.materials.append(_mat("Glass", (0.05, 0.08, 0.12, 1)))
    wins.append(w)
    # ヘッドライト・ブレーキランプ
    for sx in (-0.6, 0.6):
        bpy.ops.mesh.primitive_cube_add(size=1, location=(x0 + sx, y0 - 2.21, 0.85))
        hl = bpy.context.object; hl.scale = (0.35, 0.05, 0.12); hl.name = "HeadLight"
        hl.data.materials.append(_mat("Light", (1, 0.95, 0.7, 1)))
        wins.append(hl)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(x0 + sx, y0 + 2.21, 0.9))
        tl = bpy.context.object; tl.scale = (0.35, 0.05, 0.12); tl.name = "TailLight"
        tl.data.materials.append(_mat("Tail", (0.35, 0.0, 0.0, 1)))
        wins.append(tl)
    wheels = []
    tire = _tire_mat()
    for nm, x, y in (("Tire_FL", 0.86, -1.38), ("Tire_FR", -0.86, -1.38),
                     ("Tire_RL", 0.86, 1.32), ("Tire_RR", -0.86, 1.32)):
        bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=0.34, depth=0.26,
                                            rotation=(0, math.pi / 2, 0),
                                            location=(x0 + x, y0 + y, 0.34))
        t = bpy.context.object
        t.name = nm
        t.data.materials.append(tire)
        wheels.append(t)
    bpy.ops.mesh.primitive_torus_add(major_radius=0.19, minor_radius=0.03,
                                     location=(x0 + 0.4, y0 - 0.45, 1.15),
                                     rotation=(math.radians(65), 0, 0))
    sw = bpy.context.object
    sw.name = "SteeringWheel"
    sw.data.materials.append(_mat("Black", (0.02, 0.02, 0.02, 1)))
    bpy.context.view_layer.update()
    for o in wheels + wins + [sw]:
        o.parent = body
        o.matrix_parent_inverse = body.matrix_world.inverted()
    bpy.context.view_layer.update()
    return body, wheels, sw


def build_course(points, name="Course", cyclic=False):
    cd = bpy.data.curves.new(name, 'CURVE')
    cd.dimensions = '3D'
    sp = cd.splines.new('BEZIER')
    sp.bezier_points.add(len(points) - 1)
    for bp, p in zip(sp.bezier_points, points):
        bp.co = (p[0], p[1], 0)
        bp.handle_left_type = bp.handle_right_type = 'AUTO'
    sp.use_cyclic_u = cyclic
    ob = bpy.data.objects.new(name, cd)
    bpy.context.scene.collection.objects.link(ob)
    return ob


MAIN_COURSE = [(0, -30), (0, 20), (0, 75), (20, 108), (60, 118), (95, 100),
               (100, 65), (75, 50), (50, 30), (60, -5), (95, -20)]


def setup_render(scene, w=1280, h=720):
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.render.resolution_x, scene.render.resolution_y = w, h
    scene.render.resolution_percentage = 100
    sh = scene.display.shading
    sh.light = 'STUDIO'
    sh.studio_light = 'outdoor.sl'
    sh.use_world_space_lighting = True
    sh.color_type = 'TEXTURE'
    sh.show_shadows = True
    sh.shadow_intensity = 0.6
    sh.show_cavity = True
    sh.cavity_type = 'WORLD'
    sh.cavity_ridge_factor = 0.5
    sh.cavity_valley_factor = 0.6
    sh.show_specular_highlight = True
    scene.display.light_direction = (0.4, -0.5, 0.75)
    scene.render.film_transparent = False
    if scene.world is None:
        scene.world = bpy.data.worlds.new("World")
    scene.world.color = (0.62, 0.74, 0.9)
    scene.view_settings.view_transform = 'Standard'
    scene.render.image_settings.file_format = 'PNG'
    scene.render.fps = 24


def follow_camera(scene, target, f0, f1, dist=10.0, height=3.5, side=3.0, smooth=0.08,
                  look_up=0.6, lens=35, name="ChaseCam", fixed_dir=None, fwd_axis=(0, -1, 0)):
    """target を追いかけるカメラを作ってキーを打つ"""
    cd = bpy.data.cameras.new(name)
    cd.lens = lens
    cam = bpy.data.objects.new(name, cd)
    scene.collection.objects.link(cam)
    scene.camera = cam
    sp = None
    sf = None
    for f in range(f0, f1 + 1):
        scene.frame_set(f)
        M = target.matrix_world
        p = M.translation.copy()
        fwd = (M.to_3x3() @ Vector(fwd_axis))
        fwd.z = 0
        if fwd.length < 1e-6:
            fwd = Vector((0, 1, 0))
        fwd.normalize()
        if fixed_dir is not None:
            fwd = Vector(fixed_dir).normalized()
        if sp is None:
            sp, sf = p.copy(), fwd.copy()
        else:
            sp = sp.lerp(p, 0.35)
            sf = (sf.lerp(fwd, smooth)).normalized()
        right = sf.cross(Vector((0, 0, 1)))
        cam.location = sp - sf * dist + Vector((0, 0, height)) + right * side
        d = (sp + Vector((0, 0, look_up))) - cam.location
        cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
        cam.keyframe_insert("location", frame=f)
        cam.keyframe_insert("rotation_euler", frame=f)
    return cam

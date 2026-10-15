"""コースの3D空間にグラフィックなシェイプを置く（レースゲームのOP風モーショングラフィック）

blender -b 入力.blend --python shapes.py -- 出力.blend [白] [差し色] [濃色]

主役の車の走った跡に沿って配置するので、カメラに映る所に集まる。
  ・アーチ   : コースをまたぐ大きなリング（車がくぐる）。角ばった断面
  ・シェブロン: 内側の芝の上に浮かぶ「＞＞＞」。進行方向を指す
  ・リボン   : 空中をコースに沿って流れる縦長の帯
  ・バーコード: 内側に立つ細い柱の束
  ・遠景     : 外側の遠くでゆっくり回る巨大な三角と円
動き（シェイプが画面に入った瞬間に始まる。カメラの切り替えも考慮）:
  アーチ=地面から飛び出す / 点線リング=回り続ける / シェブロン=順に飛び出し、前へ脈打つ
  リボン=空中に一気に描かれていく / バーコード=順に伸びてイコライザー / 遠景=回転と呼吸
全部「グラフィックシェイプ」コレクションにまとめる（消す・隠すのはここだけ）。
"""
import bpy
import bmesh
import math
import random
import sys
from mathutils import Vector, Matrix

CENTER = Vector((0, 0, 0))    # オーバルの中心（内側の向きを決める）。オーバル以外では None（空いている側を探す）
GROUND = 0.55                 # 車体の基準点から地面までの高さ


def hx(s):
    s = s.lstrip("#")
    c = [int(s[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c) + (1.0,)


def flat_mat(name, col):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    rgb = nt.nodes.new("ShaderNodeRGB")
    rgb.outputs[0].default_value = col
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(rgb.outputs[0], out.inputs["Surface"])
    return m


def path(sc):
    b = sc.cpb.body
    P = []
    for f in range(sc.frame_start, sc.frame_end + 1, 2):
        sc.frame_set(f)
        P.append(b.matrix_world.translation.copy() - Vector((0, 0, GROUND)))
    S = [0.0]
    for a, c in zip(P, P[1:]):
        S.append(S[-1] + (c - a).length)
    return P, S


def at(P, S, s):
    """道のり s の位置・進行方向・内側方向"""
    s = max(0.0, min(S[-1] - 0.01, s))
    i = max(k for k in range(len(S)) if S[k] <= s)
    j = min(i + 1, len(P) - 1)
    t = (s - S[i]) / max(1e-6, S[j] - S[i])
    p = P[i].lerp(P[j], t)
    d = (P[j] - P[i]) if j != i else (P[i] - P[i - 1])
    d.z = 0
    d.normalize()
    inn = Vector((-d.y, d.x, 0))
    if CENTER is not None and inn.dot(CENTER - p) < 0:
        inn = -inn
    return p, d, inn


def obj(name, bm, mat, col):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    o.data.materials.append(mat)
    col.objects.link(o)
    return o


def frame_matrix(p, d, inn):
    """y=進行方向, z=上, x=その右手側（必ず右手系にする。左手系だと拡大のキーで裏返って地面に埋まる）"""
    x = d.cross(Vector((0, 0, 1))).normalized()
    return Matrix(((x.x, d.x, 0, p.x), (x.y, d.y, 0, p.y), (x.z, d.z, 1, p.z), (0, 0, 0, 1)))


def arch(col, mat, p, d, inn, r=14.0, t=0.9, w=1.6, seg=24):
    """コースをまたぐ角ばったアーチ（半円より少し大きい）"""
    bm = bmesh.new()
    ring_o, ring_i = [], []
    a0, a1 = math.radians(-12), math.radians(192)
    for k in range(seg + 1):
        a = a0 + (a1 - a0) * k / seg
        for rr, lst in ((r + t / 2, ring_o), (r - t / 2, ring_i)):
            for yy in (-w / 2, w / 2):
                lst.append(bm.verts.new((math.cos(a) * rr, yy, math.sin(a) * rr)))
    for k in range(seg):
        o0, o1 = ring_o[2 * k:2 * k + 2], ring_o[2 * k + 2:2 * k + 4]
        i0, i1 = ring_i[2 * k:2 * k + 2], ring_i[2 * k + 2:2 * k + 4]
        bm.faces.new((o0[0], o1[0], o1[1], o0[1]))
        bm.faces.new((i0[1], i1[1], i1[0], i0[0]))
        bm.faces.new((o0[0], i0[0], i1[0], o1[0]))
        bm.faces.new((o1[1], i1[1], i0[1], o0[1]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    o = obj("アーチ", bm, mat, col)
    o.matrix_world = frame_matrix(p, d, inn)
    return o


def chevron(col, mat, p, d, inn, size=5.0, th=1.0):
    """進行方向を指す「＞」（縦に立てた板を2枚、先端で重ねる）"""
    bm = bmesh.new()
    for (y0, z0), (y1, z1) in (((-size, 0.0), (0.0, size)), ((0.0, size), (-size, 2 * size))):
        a, b = Vector((0, y0, z0)), Vector((0, y1, z1))
        ax = (b - a)
        ln = ax.length + th * 0.7          # 先端で少し重ねて継ぎ目を隠す
        ax.normalize()
        n = Vector((0, -ax.z, ax.y))
        c = (a + b) / 2
        vs = []
        for sx in (-0.25, 0.25):
            for sl in (-ln / 2, ln / 2):
                for sn in (-th / 2, th / 2):
                    vs.append(bm.verts.new(c + Vector((sx, 0, 0)) + ax * sl + n * sn))
        # 直方体の6面（vs の並び: x, 長さ, 厚み の順に2値ずつ）
        for f in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
            bm.faces.new([vs[i] for i in f])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    o = obj("シェブロン", bm, mat, col)
    o.matrix_world = frame_matrix(p, d, inn)
    return o


def box(col, mat, name, p, d, inn, sx, sy, sz):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co = Vector((v.co.x * sx, v.co.y * sy, (v.co.z + 0.5) * sz))
    o = obj(name, bm, mat, col)
    o.matrix_world = frame_matrix(p, d, inn)
    return o


def ribbon(col, mat, P, S, s0, s1, off, h, wid, step=3.0):
    """コースに沿って空中を流れる縦の帯"""
    bm = bmesh.new()
    prev = None
    s = s0
    while s <= s1:
        p, d, inn = at(P, S, s)
        c = p + inn * off
        a = bm.verts.new(c + Vector((0, 0, h)))
        b = bm.verts.new(c + Vector((0, 0, h + wid)))
        if prev:
            bm.faces.new((prev[0], a, b, prev[1]))
        prev = (a, b)
        s += step
    return obj("リボン", bm, mat, col)


def ngon(col, mat, name, n, r, th=0.6):
    bm = bmesh.new()
    vs = []
    for z in (-th / 2, th / 2):
        for k in range(n):
            a = 2 * math.pi * k / n + math.pi / 2
            vs.append(bm.verts.new((math.cos(a) * r, z, math.sin(a) * r)))
    bmesh.ops.convex_hull(bm, input=vs)
    return obj(name, bm, mat, col)


def spin(o, f0, f1, turns):
    o.rotation_mode = 'XYZ'
    base = o.rotation_euler.copy()
    o.keyframe_insert("rotation_euler", index=1, frame=f0)
    o.rotation_euler[1] = base[1] + 2 * math.pi * turns
    o.keyframe_insert("rotation_euler", index=1, frame=f1)
    for fc in o.animation_data.action.fcurves:
        for kp in fc.keyframe_points:
            kp.interpolation = 'LINEAR'


# ---------------------------------------------------------------- アニメーション
def key(o, path_, frame, value, index=-1, interp='BEZIER'):
    setattr(o, path_, value) if index < 0 else getattr(o, path_).__setitem__(index, value)
    o.keyframe_insert(path_, index=index, frame=frame)
    for fc in o.animation_data.action.fcurves:
        if fc.data_path == path_:
            for kp in fc.keyframe_points:
                if kp.co.x == frame:
                    kp.interpolation = interp


def pop(o, f, dur=8, over=1.15, axes=(0, 1, 2), target=None):
    """f で 0 から飛び出し、少し行き過ぎて target に収まる"""
    tgt = list(target or o.scale)
    s0 = list(tgt)
    for a in axes:
        s0[a] = 0.0
    o.scale = s0
    o.keyframe_insert("scale", frame=f - 1)
    o.keyframe_insert("scale", frame=f)
    mid = list(tgt)
    for a in axes:
        mid[a] = tgt[a] * over
    o.scale = mid
    o.keyframe_insert("scale", frame=f + int(dur * 0.6))
    o.scale = tgt
    o.keyframe_insert("scale", frame=f + dur)
    for fc in o.animation_data.action.fcurves:
        if fc.data_path == "scale":
            fc.keyframe_points[0].interpolation = 'CONSTANT'


def linear(o):
    for fc in o.animation_data.action.fcurves:
        for kp in fc.keyframe_points:
            kp.interpolation = 'LINEAR'


def dashed_ring(col, mat, r, t=0.35, w=0.5, dashes=14, fill=0.6, seg=4):
    bm = bmesh.new()
    for k in range(dashes):
        a0 = 2 * math.pi * k / dashes
        a1 = a0 + 2 * math.pi / dashes * fill
        rings = []
        for q in range(seg + 1):
            a = a0 + (a1 - a0) * q / seg
            rings.append([bm.verts.new((math.cos(a) * rr, yy, math.sin(a) * rr))
                          for rr in (r - t / 2, r + t / 2) for yy in (-w / 2, w / 2)])
        for A, B in zip(rings, rings[1:]):
            for i0, i1 in ((0, 1), (1, 3), (3, 2), (2, 0)):
                bm.faces.new((A[i0], B[i0], B[i1], A[i1]))
        for R in (rings[0], rings[-1]):
            bm.faces.new((R[0], R[1], R[3], R[2]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return obj("回るリング", bm, mat, col)


def camera_track(sc):
    """フレームごとのアクティブカメラ（マーカーの切り替えも含む）"""
    from bpy_extras.object_utils import world_to_camera_view
    rows = []
    shot = {}
    if "demo" in sc:     # デモシーンはカット割り（shots）でカメラが決まる
        import json
        meta = json.loads(sc["demo"])
        for cam, f0, f1 in meta["shots"]:
            for f in range(f0, f1 + 1):
                shot[f] = bpy.data.objects[cam]
        if meta.get("replay"):
            rc, r0, r1, _sp = meta["replay"]
            for f in range(int(r0), int(r1) + 1):
                sc.frame_set(f)
                cam = bpy.data.objects[rc]
                rows.append((f, cam, cam.matrix_world.translation.copy()))
    for f in range(sc.frame_start, sc.frame_end + 1):
        sc.frame_set(f)
        cam = shot.get(f, sc.camera) if shot else sc.camera
        if cam is not None:
            rows.append((f, cam, cam.matrix_world.translation.copy()))
    return rows, world_to_camera_view


def free_side(sc, p, inn, dist, skip=()):
    """p から inn 方向 dist の所が空いていれば inn、反対側が空いていれば -inn、どちらも塞がっていれば None"""
    dg = bpy.context.evaluated_depsgraph_get()
    for sgn in (1, -1):
        ok = True
        for dd in (dist - 4, dist, dist + 4):
            q = p + inn * (sgn * dd)
            o0 = q + Vector((0, 0, 80))
            for _ in range(8):     # 置いたシェイプ自身や車は無視して、その下を見る
                hit, loc, n, i, ob, M = sc.ray_cast(dg, o0, Vector((0, 0, -1)))
                if not hit or not (ob.name.startswith(("CPB_", "アーチ", "回るリング", "リボン", "シェブロン", "バーコード", "流れる線"))
                                   or ob.name in skip):
                    break
                o0 = loc - Vector((0, 0, 0.05))
            if hit and loc.z > p.z + 1.5:
                ok = False
                break
        if ok:
            return inn * sgn
    return None


def first_seen(sc, cams, w2cv, pts, near, margin=0.08):
    """pts のどれかが、カメラから near 以内で画面に入る最初のフレーム（無ければ None）"""
    for f, cam, cp in cams:
        if all((p - cp).length > near for p in pts):
            continue
        sc.frame_set(f)
        for p in pts:
            if (p - cp).length > near:
                continue
            v = w2cv(sc, cam, p)
            if v.z > 0 and -margin < v.x < 1 + margin and -margin < v.y < 1 + margin:
                return f
    return None


def main():
    args = sys.argv[sys.argv.index("--") + 1:]
    out = args[0]
    white = hx(args[1] if len(args) > 1 else "#ffffff")
    acc = hx(args[2] if len(args) > 2 else "#ff6a13")
    dark = hx(args[3] if len(args) > 3 else "#22324a")
    sc = bpy.context.scene
    F0, F1 = sc.frame_start, sc.frame_end
    rnd = random.Random(7)
    global CENTER
    if bpy.data.objects.get("オーバル.001") is None and bpy.data.objects.get("オーバル") is None:
        CENTER = None
    col = bpy.data.collections.get("グラフィックシェイプ") or bpy.data.collections.new("グラフィックシェイプ")
    if col.name not in sc.collection.children:
        sc.collection.children.link(col)
    mw, ma, md = flat_mat("シェイプ白", white), flat_mat("シェイプ差し色", acc), flat_mat("シェイプ濃", dark)
    P, S = path(sc)
    L = S[-1]
    cams, w2cv = camera_track(sc)
    print("SHAPES path length", round(L))

    def blocks(pts, rad):
        """pts のどれかがカメラのすぐ近く、またはカメラと主役の車の間（視線の上）にあれば True"""
        for f, cam, cp in cams[::2]:
            hp = P[min(len(P) - 1, max(0, (f - F0) // 2))] + Vector((0, 0, 0.8))
            seg = hp - cp
            ln = seg.length
            if ln < 1e-3:
                continue
            u = seg / ln
            for q in pts:
                if (q - cp).length < rad * 1.6:
                    return True
                tt = (q - cp).dot(u)
                if 0 < tt < ln - 3 and (q - cp - u * tt).length < rad:
                    return True
        return False

    def trigger(pts, near, fallback):
        f = first_seen(sc, cams, w2cv, pts, near)
        return (f + 3) if f is not None else fallback

    # アーチ: 画面に入ったら、地面から回り込みながら飛び出す。点線リングは速く回り続ける
    for k, s in enumerate((70, 190, 300, 420, 520)):
        if s > L - 5:
            break
        p, d, inn = at(P, S, s)
        x = d.cross(Vector((0, 0, 1)))
        probe = [p + x * (15 * math.cos(math.radians(a_))) + Vector((0, 0, 15 * math.sin(math.radians(a_))))
                 for a_ in range(-10, 195, 15)]
        if blocks(probe, 3.0):      # カメラの前を塞ぐアーチは置かない
            continue
        a = arch(col, mw if k % 2 == 0 else ma, p, d, inn, r=15.0)
        f = trigger([p + Vector((0, 0, 8)), p + inn * 14, p - inn * 14], 160, F0 + 2)
        pop(a, f, dur=12, over=1.15)
        yaw = a.rotation_euler[2]
        a.rotation_euler[2] = yaw + math.radians(100 if k % 2 else -100)
        a.keyframe_insert("rotation_euler", index=2, frame=f)
        a.rotation_euler[2] = yaw
        a.keyframe_insert("rotation_euler", index=2, frame=f + 14)
        p2, d2, inn2 = at(P, S, s + 6)
        piv = bpy.data.objects.new("回るリングの軸", None)
        col.objects.link(piv)
        piv.matrix_world = frame_matrix(p2, d2, inn2)
        ring = dashed_ring(col, md if k % 2 == 0 else mw, 16.8)
        ring.parent = piv
        ring.rotation_mode = 'XYZ'
        key(ring, "rotation_euler", F0, 0.0, index=1, interp='LINEAR')
        key(ring, "rotation_euler", F1, (1 if k % 2 else -1) * 2 * math.pi * 2.5, index=1, interp='LINEAR')
        pop(ring, f + 5, dur=12, over=1.1)
    # シェブロン: 画面に入ったら1つずつ回転しながら飛び出し、その後は前へ前へと速く脈打つ
    s = 40.0
    while s < L - 20:
        group = []
        p0, d0, inn0 = at(P, S, s + 7)
        side = free_side(sc, p0, inn0, 26)
        if side is None:
            s += 110
            continue
        for k in range(3):
            p, d, inn = at(P, S, s + k * 7)
            inn = inn if inn.dot(side) > 0 else -inn
            c = p + inn * 26 + Vector((0, 0, 2.5))
            group.append((c, d, inn))
        if any(blocks([c + Vector((0, 0, z_)) for z_ in (0, 4, 8)], 5.0) for c, _, _ in group):
            s += 110
            continue
        group = [chevron(col, ma if k == 2 else mw, c, d, inn, size=4.0, th=1.1) for k, (c, d, inn) in enumerate(group)]
        f = trigger([o.matrix_world.translation + Vector((0, 0, 4)) for o in group], 120, F0 + 2)
        for k, o in enumerate(group):
            fk = f + k * 3
            pop(o, fk, dur=8, over=1.35)
            yaw = o.rotation_euler[2]
            o.rotation_euler[2] = yaw - math.pi
            o.keyframe_insert("rotation_euler", index=2, frame=fk)
            o.rotation_euler[2] = yaw
            o.keyframe_insert("rotation_euler", index=2, frame=fk + 9)
            t = fk + 10 + k * 3
            while t < F1:
                for dt, v in ((0, 1.0), (3, 1.45), (7, 1.0)):
                    o.scale = (v, v, v)
                    o.keyframe_insert("scale", frame=t + dt)
                t += 10
        s += 110
    # リボン: 画面に入ったら、空中に一気に描かれていく
    for s0, s1, off, h, wid, m in ((20, L - 10, 12, 11.0, 1.2, mw), (60, L - 40, 16, 14.5, 0.5, ma),
                                   (30, L - 20, -26, 17.0, 2.2, md)):
        o = ribbon(col, m, P, S, s0, s1, off, h, wid)
        pts = []
        for x in (s0, s0 + 30, s0 + 60):
            q, _, iq = at(P, S, x)
            pts.append(q + iq * off + Vector((0, 0, h)))
        f = trigger(pts, 200, F0)
        bd = o.modifiers.new("描かれる", 'BUILD')
        bd.frame_start = f
        bd.frame_duration = 40
    # バーコード: 画面に入ったら地面から順に伸び、その後は速いイコライザー
    s = 95.0
    while s < L - 10:
        p, d, inn = at(P, S, s)
        side = free_side(sc, p, inn, 38)
        if side is None:
            s += 140
            continue
        inn = side
        if blocks([p + inn * 38 + Vector((0, 0, z_)) for z_ in (0, 8, 16)], 7.0):
            s += 140
            continue
        bars = []
        for k in range(rnd.randint(6, 10)):
            q = p + inn * (34 + k * 1.3) + d * rnd.uniform(-1, 1)
            bars.append(box(col, md if k % 3 else ma, "バーコード", q, d, inn, 0.6, 0.6, rnd.uniform(6, 26)))
        f = trigger([b.matrix_world.translation + Vector((0, 0, 6)) for b in bars], 150, F0 + 2)
        for k, o in enumerate(bars):
            pop(o, f + k * 2, dur=8, over=1.3, axes=(2,))
            t = f + k * 2 + 10
            while t < F1:
                o.scale = (1, 1, rnd.uniform(0.25, 1.3))
                o.keyframe_insert("scale", frame=t)
                t += rnd.choice((3, 4, 5))
        s += 140
    # 遠景の巨大な三角と円: 回りながら大きさが呼吸する（常に動いている）
    for k in range(9):
        s = L * (k + 0.5) / 9
        p, d, inn = at(P, S, s)
        n = 3 if k % 2 == 0 else 48
        far_d = rnd.uniform(110, 170) if CENTER is not None else rnd.uniform(200, 280)   # 小さいコースは遠くへ
        c = p - inn * far_d + Vector((0, 0, rnd.uniform(25, 50)))
        if CENTER is None and min(((c - cp).length for _, _, cp in cams), default=999) < 160:
            continue
        o = ngon(col, [mw, md, ma][k % 3], "遠景の三角" if n == 3 else "遠景の円", n, rnd.uniform(18, 34), th=1.0)
        face = (p - c)
        face.z = 0
        face.normalize()
        o.location = c
        o.rotation_euler = (0, rnd.uniform(0, 6.28), math.atan2(face.y, face.x) + math.pi / 2)
        spin(o, F0, F1, rnd.choice((-1, 1)) * rnd.uniform(0.6, 1.0))
        ph = rnd.uniform(0, 24)
        t = F0 - ph
        while t < F1 + 24:
            for dt, v in ((0, 1.0), (12, 1.18)):
                o.scale = (v, v, v)
                o.keyframe_insert("scale", frame=t + dt)
            t += 24
    for o in col.objects:
        o.visible_shadow = o.name.startswith(("アーチ", "リボン", "回るリング"))
    sc.frame_set(F0)
    print("SHAPES", len(col.objects), "objects")
    bpy.ops.wm.save_as_mainfile(filepath=out, compress=True)
    print("SAVED", out)


main()

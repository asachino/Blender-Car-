"""ウイングの形を作る道具と、デザイン候補（R32 のトランク用）

座標: x=左右, y=前後（前が +Y、車の後ろは -2.2 あたり）, z=上。単位は m。
候補ごとに {"本体": bmesh, "翼端板": bmesh, "支柱": bmesh, ...} を返し、部品ごとにマテリアルを当てる。
"""
import bmesh
import math
from mathutils import Vector, Matrix


# ---------------------------------------------------------------- 翼型
def naca(m=0.06, p=0.4, t=0.12, n=14):
    """NACA 4桁の翼型（ダウンフォース用に上下反転）。前縁 0 → 後縁 1 の (x, z) の輪"""
    xs = [0.5 * (1 - math.cos(math.pi * i / n)) for i in range(n + 1)]
    up, lo = [], []
    for x in xs:
        yt = 5 * t * (0.2969 * math.sqrt(x) - 0.1260 * x - 0.3516 * x ** 2 + 0.2843 * x ** 3 - 0.1036 * x ** 4)
        if x < p:
            yc = m / p ** 2 * (2 * p * x - x * x)
            dy = 2 * m / p ** 2 * (p - x)
        else:
            yc = m / (1 - p) ** 2 * ((1 - 2 * p) + 2 * p * x - x * x)
            dy = 2 * m / (1 - p) ** 2 * (p - x)
        th = math.atan(dy)
        up.append((x - yt * math.sin(th), -(yc + yt * math.cos(th))))
        lo.append((x + yt * math.sin(th), -(yc - yt * math.cos(th))))
    return up + list(reversed(lo[1:-1]))


def loft(bm, sections, prof=None):
    """翼を張る。sections = [(x, y前縁, z, 翼弦, 迎角度), ...]（左右の順に）"""
    prof = prof or naca()
    rings = []
    for x, yle, z, ch, aoa in sections:
        a = math.radians(aoa)
        ring = []
        for px, pz in prof:
            dy, dz = -px * ch, pz * ch           # 前縁から後ろへ
            ry = dy * math.cos(a) - dz * math.sin(a)
            rz = dy * math.sin(a) + dz * math.cos(a)
            ring.append(bm.verts.new((x, yle + ry, z + rz)))
        rings.append(ring)
    n = len(rings[0])
    for A, B in zip(rings, rings[1:]):
        for i in range(n):
            bm.faces.new((A[i], A[(i + 1) % n], B[(i + 1) % n], B[i]))
    bm.faces.new(list(reversed(rings[0])))
    bm.faces.new(rings[-1])


def span_sections(span, yle, z, ch, aoa, n=8, dihedral=0.0, taper=0.0, sweep=0.0):
    """まっすぐ〜少し反った翼の断面の並び"""
    out = []
    for i in range(n + 1):
        x = -span / 2 + span * i / n
        u = abs(x) / (span / 2)
        out.append((x, yle - sweep * u, z + dihedral * u ** 3, ch * (1 - taper * u), aoa))
    return out


def plate(bm, x, outline, th):
    """翼端板など: (y, z) の輪郭を x の位置に厚み th で立てる"""
    a = [bm.verts.new((x - th / 2, y, z)) for y, z in outline]
    b = [bm.verts.new((x + th / 2, y, z)) for y, z in outline]
    n = len(outline)
    bm.faces.new(list(reversed(a)))
    bm.faces.new(b)
    for i in range(n):
        bm.faces.new((a[i], a[(i + 1) % n], b[(i + 1) % n], b[i]))


def rounded(y0, y1, z0, z1, r=0.03, cut_front_top=0.0, cut_rear_bottom=0.0, seg=3):
    """角を丸めた四角の輪郭（前上・後ろ下を斜めに落とせる）"""
    pts = []

    def arc(cy, cz, a0, a1):
        for k in range(seg + 1):
            a = a0 + (a1 - a0) * k / seg
            pts.append((cy + r * math.cos(a), cz + r * math.sin(a)))
    # 前（+y）が y0 側にくる前提で、前下 → 前上 → 後ろ上 → 後ろ下
    arc(y0 - r, z0 + r + cut_rear_bottom * 0, -math.pi / 2, 0)
    if cut_front_top:
        pts.append((y0, z1 - cut_front_top))
        pts.append((y0 - cut_front_top, z1))
    else:
        arc(y0 - r, z1 - r, 0, math.pi / 2)
    arc(y1 + r, z1 - r, math.pi / 2, math.pi)
    if cut_rear_bottom:
        pts.append((y1, z0 + cut_rear_bottom))
        pts.append((y1 + cut_rear_bottom, z0))
    else:
        arc(y1 + r, z0 + r, math.pi, 1.5 * math.pi)
    return pts


def sweep(bm, x, path, w, h):
    """支柱: (y, z) の道筋に沿って、幅 w（左右）× 奥行き h の断面を流す"""
    rings = []
    for i, (y, z) in enumerate(path):
        a = Vector(path[max(0, i - 1)])
        b = Vector(path[min(len(path) - 1, i + 1)])
        t = (b - a).normalized()
        nrm = Vector((-t.y, t.x))
        ring = []
        for sx, sn in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            ring.append(bm.verts.new((x + sx * w / 2, y + nrm.x * sn * h / 2, z + nrm.y * sn * h / 2)))
        rings.append(ring)
    for A, B in zip(rings, rings[1:]):
        for i in range(4):
            bm.faces.new((A[i], A[(i + 1) % 4], B[(i + 1) % 4], B[i]))
    bm.faces.new(list(reversed(rings[0])))
    bm.faces.new(rings[-1])


def curve(pts, n=10):
    """数点を通るなめらかな道筋（Catmull-Rom）"""
    P = [Vector(p) for p in pts]
    out = []
    for i in range(len(P) - 1):
        p0, p1, p2, p3 = P[max(0, i - 1)], P[i], P[i + 1], P[min(len(P) - 1, i + 2)]
        for k in range(n):
            t = k / n
            out.append(tuple(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                                    + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3)))
    out.append(tuple(P[-1]))
    return out


def box(bm, c, sx, sy, sz, rot_x=0.0):
    M = Matrix.Translation(c) @ Matrix.Rotation(rot_x, 4, 'X')
    bmesh.ops.create_cube(bm, size=1.0, matrix=M @ Matrix.Diagonal((sx, sy, sz, 1)))


def te_of(yle, z, ch, aoa):
    a = math.radians(aoa)
    return yle - ch * math.cos(a), z - ch * math.sin(a)


# ---------------------------------------------------------------- 候補
def cand_swan(D):
    """A: スワンネック（タイムアタック定番。翼の上から吊る）"""
    parts = {"本体": bmesh.new(), "翼端板": bmesh.new(), "支柱": bmesh.new()}
    z, yle, ch, aoa = D + 0.30, -1.86, 0.30, -7
    loft(parts["本体"], span_sections(1.74, yle, z, ch, aoa, dihedral=0.012))
    ty, tz = te_of(yle, z, ch, aoa)
    box(parts["支柱"], Vector((0, ty + 0.004, tz + 0.012)), 1.72, 0.006, 0.026)        # ガーニーフラップ
    for x in (-0.33, 0.33):
        sweep(parts["支柱"], x, curve([(-1.90, D), (-1.93, D + 0.16), (-1.97, z + 0.06), (-2.04, z + 0.06), (-2.07, z + 0.035)], 6), 0.016, 0.06)
    for x in (-0.875, 0.875):
        plate(parts["翼端板"], x, rounded(-1.78, -2.24, z - 0.12, z + 0.11, r=0.025, cut_front_top=0.07), 0.008)
    return parts


def cand_gt500(D):
    """B: ダブルエレメント（GT500風。主翼＋フラップ）"""
    parts = {"本体": bmesh.new(), "翼端板": bmesh.new(), "支柱": bmesh.new()}
    z, yle, ch, aoa = D + 0.27, -1.84, 0.26, -4
    loft(parts["本体"], span_sections(1.70, yle, z, ch, aoa))
    ty, tz = te_of(yle, z, ch, aoa)
    loft(parts["本体"], span_sections(1.70, ty + 0.035, tz + 0.035, 0.14, -24), naca(0.05, 0.4, 0.10, 10))
    for x in (-0.40, 0.40):
        plate(parts["支柱"], x, [(-1.86, D), (-2.06, D), (-2.02, z - 0.02), (-1.90, z - 0.01)], 0.012)
    for x in (-0.86, 0.86):
        plate(parts["翼端板"], x, rounded(-1.76, -2.26, z - 0.14, z + 0.12, r=0.02, cut_rear_bottom=0.08), 0.008)
    return parts


def cand_nismo(D):
    """C: ボディ同色ハイウイング（R34 ニスモ風。なめらかな台座）"""
    parts = {"本体同色": bmesh.new(), "支柱同色": bmesh.new()}
    z, yle, ch, aoa = D + 0.17, -1.90, 0.24, -2
    loft(parts["本体同色"], span_sections(1.52, yle, z, ch, aoa, n=10, dihedral=0.02, taper=0.12))
    for x in (-0.52, 0.52):
        plate(parts["支柱同色"], x, [(-1.84, D - 0.005), (-2.16, D - 0.005), (-2.10, z - 0.015), (-1.92, z - 0.005)], 0.045)
    return parts


def cand_duck(D):
    """D: ダックテール（ボディ同色。トランクの縁がなめらかに跳ね上がる）"""
    parts = {"本体同色": bmesh.new(), "翼端板": bmesh.new()}
    bm = parts["本体同色"]
    prof = [(-1.86, D + 0.004), (-1.98, D + 0.012), (-2.08, D + 0.035), (-2.16, D + 0.075), (-2.20, D + 0.10),
            (-2.215, D + 0.095), (-2.20, D + 0.06), (-2.16, D + 0.02), (-2.05, D + 0.004)]
    rows = []
    n = 10
    for i in range(n + 1):
        x = -0.80 + 1.60 * i / n
        u = abs(x) / 0.80
        drop = 0.03 * u ** 4
        rows.append([bm.verts.new((x, y, z - drop)) for y, z in prof])
    m = len(prof)
    for A, B in zip(rows, rows[1:]):
        for k in range(m):
            bm.faces.new((A[k], A[(k + 1) % m], B[(k + 1) % m], B[k]))
    bm.faces.new(list(reversed(rows[0])))
    bm.faces.new(rows[-1])
    box(parts["翼端板"], Vector((0, -2.212, D + 0.112)), 1.50, 0.006, 0.02)    # ガーニー（黒）
    return parts


def cand_attack(D):
    """E: 大型ハイマウント（翼端が車幅より外へ。大きな翼端板）"""
    parts = {"本体": bmesh.new(), "翼端板": bmesh.new(), "支柱": bmesh.new()}
    z, yle, ch, aoa = D + 0.52, -1.84, 0.36, -10
    loft(parts["本体"], span_sections(1.94, yle, z, ch, aoa, n=10))
    ty, tz = te_of(yle, z, ch, aoa)
    box(parts["支柱"], Vector((0, ty + 0.004, tz + 0.014)), 1.92, 0.006, 0.03)
    for x in (-0.30, 0.30):
        sweep(parts["支柱"], x, curve([(-1.88, D), (-1.90, D + 0.25), (-1.95, z + 0.07), (-2.04, z + 0.075), (-2.09, z + 0.04)], 7), 0.018, 0.07)
    for x in (-0.975, 0.975):
        plate(parts["翼端板"], x, rounded(-1.70, -2.30, z - 0.18, z + 0.14, r=0.03, cut_front_top=0.10, cut_rear_bottom=0.06), 0.008)
    return parts


def cand_3d(D):
    """F: 3D ウイング（中央が低く、両端が反り上がる。細い支柱）"""
    parts = {"本体": bmesh.new(), "支柱": bmesh.new(), "翼端板": bmesh.new()}
    z, yle, ch, aoa = D + 0.24, -1.88, 0.28, -6
    loft(parts["本体"], span_sections(1.76, yle, z, ch, aoa, n=14, dihedral=0.11, sweep=0.04))
    for x in (-0.36, 0.36):
        plate(parts["支柱"], x, [(-1.90, D), (-2.02, D), (-2.06, z - 0.03), (-1.96, z - 0.02)], 0.014)
    for x in (-0.875, 0.875):
        plate(parts["翼端板"], x, rounded(-1.88, -2.20, z + 0.04, z + 0.16, r=0.02), 0.006)
    return parts


CANDIDATES = [("A スワンネック", cand_swan), ("B ダブルエレメント（GT500風）", cand_gt500),
              ("C ボディ同色ハイウイング（ニスモ風）", cand_nismo), ("D ダックテール（同色）", cand_duck),
              ("E 大型ハイマウント", cand_attack), ("F 3Dウイング", cand_3d)]

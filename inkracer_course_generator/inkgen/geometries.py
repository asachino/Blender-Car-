"""three.js (r180) の形状クラスと BufferGeometryUtils.mergeGeometries / EdgesGeometry / Earcut の移植"""
import math
from .three import BufferAttribute, BufferGeometry, Vector2, Vector3, f32, clamp, EPSILON


def _finish(g, indices, vertices, normals, uvs, normal_first=True):
    g.setIndex(indices)
    g.setAttribute("position", BufferAttribute(f32(vertices), 3))
    if normal_first:
        g.setAttribute("normal", BufferAttribute(f32(normals), 3))
        g.setAttribute("uv", BufferAttribute(f32(uvs), 2))
    else:
        g.setAttribute("uv", BufferAttribute(f32(uvs), 2))
        g.setAttribute("normal", BufferAttribute(f32(normals), 3))
    return g


def BoxGeometry(width=1, height=1, depth=1, widthSegments=1, heightSegments=1, depthSegments=1):
    g = BufferGeometry()
    widthSegments, heightSegments, depthSegments = int(widthSegments), int(heightSegments), int(depthSegments)
    indices, vertices, normals, uvs = [], [], [], []
    st = {"n": 0, "gs": 0}

    def build(u, v, w, udir, vdir, width, height, depth, gridX, gridY, mi):
        sw, sh = width / gridX, height / gridY
        wh, hh, dh = width / 2, height / 2, depth / 2
        gx1, gy1 = gridX + 1, gridY + 1
        vc = gc = 0
        for iy in range(gy1):
            y = iy * sh - hh
            for ix in range(gx1):
                x = ix * sw - wh
                vec = {}
                vec[u] = x * udir
                vec[v] = y * vdir
                vec[w] = dh
                vertices.extend((vec["x"], vec["y"], vec["z"]))
                vec[u] = 0
                vec[v] = 0
                vec[w] = 1 if depth > 0 else -1
                normals.extend((vec["x"], vec["y"], vec["z"]))
                uvs.extend((ix / gridX, 1 - (iy / gridY)))
                vc += 1
        n = st["n"]
        for iy in range(gridY):
            for ix in range(gridX):
                a = n + ix + gx1 * iy
                b = n + ix + gx1 * (iy + 1)
                c = n + (ix + 1) + gx1 * (iy + 1)
                d = n + (ix + 1) + gx1 * iy
                indices.extend((a, b, d, b, c, d))
                gc += 6
        g.addGroup(st["gs"], gc, mi)
        st["gs"] += gc
        st["n"] += vc

    build("z", "y", "x", -1, -1, depth, height, width, depthSegments, heightSegments, 0)
    build("z", "y", "x", 1, -1, depth, height, -width, depthSegments, heightSegments, 1)
    build("x", "z", "y", 1, 1, width, depth, height, widthSegments, depthSegments, 2)
    build("x", "z", "y", 1, -1, width, depth, -height, widthSegments, depthSegments, 3)
    build("x", "y", "z", 1, -1, width, height, depth, widthSegments, heightSegments, 4)
    build("x", "y", "z", -1, -1, width, height, -depth, widthSegments, heightSegments, 5)
    return _finish(g, indices, vertices, normals, uvs)


def CylinderGeometry(radiusTop=1, radiusBottom=1, height=1, radialSegments=32, heightSegments=1, openEnded=False,
                     thetaStart=0, thetaLength=math.pi * 2):
    g = BufferGeometry()
    radialSegments, heightSegments = int(radialSegments), int(heightSegments)
    indices, vertices, normals, uvs = [], [], [], []
    st = {"i": 0, "gs": 0}
    indexArray = []
    halfHeight = height / 2

    def torso():
        gc = 0
        slope = (radiusBottom - radiusTop) / height
        for y in range(heightSegments + 1):
            row = []
            v = y / heightSegments
            radius = v * (radiusBottom - radiusTop) + radiusTop
            for x in range(radialSegments + 1):
                u = x / radialSegments
                theta = u * thetaLength + thetaStart
                s, c = math.sin(theta), math.cos(theta)
                vertices.extend((radius * s, -v * height + halfHeight, radius * c))
                n = Vector3(s, slope, c).normalize()
                normals.extend((n.x, n.y, n.z))
                uvs.extend((u, 1 - v))
                row.append(st["i"])
                st["i"] += 1
            indexArray.append(row)
        for x in range(radialSegments):
            for y in range(heightSegments):
                a = indexArray[y][x]
                b = indexArray[y + 1][x]
                c = indexArray[y + 1][x + 1]
                d = indexArray[y][x + 1]
                if radiusTop > 0 or y != 0:
                    indices.extend((a, b, d))
                    gc += 3
                if radiusBottom > 0 or y != heightSegments - 1:
                    indices.extend((b, c, d))
                    gc += 3
        g.addGroup(st["gs"], gc, 0)
        st["gs"] += gc

    def cap(top):
        cs = st["i"]
        gc = 0
        radius = radiusTop if top else radiusBottom
        sign = 1 if top else -1
        for x in range(1, radialSegments + 1):
            vertices.extend((0, halfHeight * sign, 0))
            normals.extend((0, sign, 0))
            uvs.extend((0.5, 0.5))
            st["i"] += 1
        ce = st["i"]
        for x in range(radialSegments + 1):
            u = x / radialSegments
            theta = u * thetaLength + thetaStart
            c, s = math.cos(theta), math.sin(theta)
            vertices.extend((radius * s, halfHeight * sign, radius * c))
            normals.extend((0, sign, 0))
            uvs.extend((c * 0.5 + 0.5, s * 0.5 * sign + 0.5))
            st["i"] += 1
        for x in range(radialSegments):
            c = cs + x
            i = ce + x
            if top:
                indices.extend((i, i + 1, c))
            else:
                indices.extend((i + 1, i, c))
            gc += 3
        g.addGroup(st["gs"], gc, 1 if top else 2)
        st["gs"] += gc

    torso()
    if not openEnded:
        if radiusTop > 0:
            cap(True)
        if radiusBottom > 0:
            cap(False)
    return _finish(g, indices, vertices, normals, uvs)


def PlaneGeometry(width=1, height=1, widthSegments=1, heightSegments=1):
    g = BufferGeometry()
    wh, hh = width / 2, height / 2
    gx, gy = int(widthSegments), int(heightSegments)
    gx1, gy1 = gx + 1, gy + 1
    sw, sh = width / gx, height / gy
    indices, vertices, normals, uvs = [], [], [], []
    for iy in range(gy1):
        y = iy * sh - hh
        for ix in range(gx1):
            x = ix * sw - wh
            vertices.extend((x, -y, 0))
            normals.extend((0, 0, 1))
            uvs.extend((ix / gx, 1 - (iy / gy)))
    for iy in range(gy):
        for ix in range(gx):
            a = ix + gx1 * iy
            b = ix + gx1 * (iy + 1)
            c = (ix + 1) + gx1 * (iy + 1)
            d = (ix + 1) + gx1 * iy
            indices.extend((a, b, d, b, c, d))
    return _finish(g, indices, vertices, normals, uvs)


def SphereGeometry(radius=1, widthSegments=32, heightSegments=16, phiStart=0, phiLength=math.pi * 2, thetaStart=0,
                   thetaLength=math.pi):
    g = BufferGeometry()
    widthSegments = max(3, int(math.floor(widthSegments)))
    heightSegments = max(2, int(math.floor(heightSegments)))
    thetaEnd = min(thetaStart + thetaLength, math.pi)
    index = 0
    grid = []
    indices, vertices, normals, uvs = [], [], [], []
    for iy in range(heightSegments + 1):
        row = []
        v = iy / heightSegments
        uOffset = 0
        if iy == 0 and thetaStart == 0:
            uOffset = 0.5 / widthSegments
        elif iy == heightSegments and thetaEnd == math.pi:
            uOffset = -0.5 / widthSegments
        for ix in range(widthSegments + 1):
            u = ix / widthSegments
            vx = -radius * math.cos(phiStart + u * phiLength) * math.sin(thetaStart + v * thetaLength)
            vy = radius * math.cos(thetaStart + v * thetaLength)
            vz = radius * math.sin(phiStart + u * phiLength) * math.sin(thetaStart + v * thetaLength)
            vertices.extend((vx, vy, vz))
            n = Vector3(vx, vy, vz).normalize()
            normals.extend((n.x, n.y, n.z))
            uvs.extend((u + uOffset, 1 - v))
            row.append(index)
            index += 1
        grid.append(row)
    for iy in range(heightSegments):
        for ix in range(widthSegments):
            a = grid[iy][ix + 1]
            b = grid[iy][ix]
            c = grid[iy + 1][ix]
            d = grid[iy + 1][ix + 1]
            if iy != 0 or thetaStart > 0:
                indices.extend((a, b, d))
            if iy != heightSegments - 1 or thetaEnd < math.pi:
                indices.extend((b, c, d))
    return _finish(g, indices, vertices, normals, uvs)


def TorusGeometry(radius=1, tube=0.4, radialSegments=12, tubularSegments=48, arc=math.pi * 2):
    g = BufferGeometry()
    radialSegments, tubularSegments = int(radialSegments), int(tubularSegments)
    indices, vertices, normals, uvs = [], [], [], []
    for j in range(radialSegments + 1):
        for i in range(tubularSegments + 1):
            u = i / tubularSegments * arc
            v = j / radialSegments * math.pi * 2
            vx = (radius + tube * math.cos(v)) * math.cos(u)
            vy = (radius + tube * math.cos(v)) * math.sin(u)
            vz = tube * math.sin(v)
            vertices.extend((vx, vy, vz))
            n = Vector3(vx - radius * math.cos(u), vy - radius * math.sin(u), vz).normalize()
            normals.extend((n.x, n.y, n.z))
            uvs.extend((i / tubularSegments, j / radialSegments))
    for j in range(1, radialSegments + 1):
        for i in range(1, tubularSegments + 1):
            a = (tubularSegments + 1) * j + i - 1
            b = (tubularSegments + 1) * (j - 1) + i - 1
            c = (tubularSegments + 1) * (j - 1) + i
            d = (tubularSegments + 1) * j + i
            indices.extend((a, b, d, b, c, d))
    return _finish(g, indices, vertices, normals, uvs)


def LatheGeometry(points, segments=12, phiStart=0, phiLength=math.pi * 2):
    g = BufferGeometry()
    segments = int(segments)
    phiLength = clamp(phiLength, 0, math.pi * 2)
    indices, vertices, uvs, initNormals, normals = [], [], [], [], []
    inv = 1.0 / segments
    normal = Vector3()
    cur = Vector3()
    prev = Vector3()
    L = len(points)
    for j in range(L):
        if j == 0:
            dx = points[j + 1].x - points[j].x
            dy = points[j + 1].y - points[j].y
            normal.set(dy * 1.0, -dx, dy * 0.0)
            prev.copy(normal)
            normal.normalize()
            initNormals.extend((normal.x, normal.y, normal.z))
        elif j == L - 1:
            initNormals.extend((prev.x, prev.y, prev.z))
        else:
            dx = points[j + 1].x - points[j].x
            dy = points[j + 1].y - points[j].y
            normal.set(dy * 1.0, -dx, dy * 0.0)
            cur.copy(normal)
            normal.x += prev.x
            normal.y += prev.y
            normal.z += prev.z
            normal.normalize()
            initNormals.extend((normal.x, normal.y, normal.z))
            prev.copy(cur)
    for i in range(segments + 1):
        phi = phiStart + i * inv * phiLength
        s, c = math.sin(phi), math.cos(phi)
        for j in range(L):
            vertices.extend((points[j].x * s, points[j].y, points[j].x * c))
            uvs.extend((i / segments, j / (L - 1)))
            normals.extend((initNormals[3 * j] * s, initNormals[3 * j + 1], initNormals[3 * j] * c))
    for i in range(segments):
        for j in range(L - 1):
            base = j + i * L
            a, b, c, d = base, base + L, base + L + 1, base + 1
            indices.extend((a, b, d, c, d, b))
    return _finish(g, indices, vertices, normals, uvs, normal_first=False)


def TubeGeometry(path, tubularSegments=64, radius=1, radialSegments=8, closed=False):
    g = BufferGeometry()
    frames = path.computeFrenetFrames(tubularSegments, closed)
    vertices, normals, uvs, indices = [], [], [], []

    def segment(i):
        P = path.getPointAt(i / tubularSegments)
        N = frames["normals"][i]
        B = frames["binormals"][i]
        for j in range(radialSegments + 1):
            v = j / radialSegments * math.pi * 2
            s = math.sin(v)
            c = -math.cos(v)
            n = Vector3(c * N.x + s * B.x, c * N.y + s * B.y, c * N.z + s * B.z).normalize()
            normals.extend((n.x, n.y, n.z))
            vertices.extend((P.x + radius * n.x, P.y + radius * n.y, P.z + radius * n.z))

    for i in range(tubularSegments):
        segment(i)
    segment(tubularSegments if not closed else 0)
    for i in range(tubularSegments + 1):
        for j in range(radialSegments + 1):
            uvs.extend((i / tubularSegments, j / radialSegments))
    for j in range(1, tubularSegments + 1):
        for i in range(1, radialSegments + 1):
            a = (radialSegments + 1) * (j - 1) + (i - 1)
            b = (radialSegments + 1) * j + (i - 1)
            c = (radialSegments + 1) * j + i
            d = (radialSegments + 1) * (j - 1) + i
            indices.extend((a, b, d, b, c, d))
    return _finish(g, indices, vertices, normals, uvs)


_ICO_T = (1 + math.sqrt(5)) / 2
_ICO_V = [-1, _ICO_T, 0, 1, _ICO_T, 0, -1, -_ICO_T, 0, 1, -_ICO_T, 0,
          0, -1, _ICO_T, 0, 1, _ICO_T, 0, -1, -_ICO_T, 0, 1, -_ICO_T,
          _ICO_T, 0, -1, _ICO_T, 0, 1, -_ICO_T, 0, -1, -_ICO_T, 0, 1]
_ICO_I = [0, 11, 5, 0, 5, 1, 0, 1, 7, 0, 7, 10, 0, 10, 11,
          1, 5, 9, 5, 11, 4, 11, 10, 2, 10, 7, 6, 7, 1, 8,
          3, 9, 4, 3, 4, 2, 3, 2, 6, 3, 6, 8, 3, 8, 9,
          4, 9, 5, 2, 4, 11, 6, 2, 10, 8, 6, 7, 9, 8, 1]


def PolyhedronGeometry(vertices, indices, radius=1, detail=0):
    g = BufferGeometry()
    vb, uvb = [], []

    def push(v):
        vb.extend((v.x, v.y, v.z))

    def face(a, b, c, detail):
        cols = detail + 1
        v = []
        for i in range(cols + 1):
            v.append([])
            aj = a.clone().lerp(c, i / cols)
            bj = b.clone().lerp(c, i / cols)
            rows = cols - i
            for j in range(rows + 1):
                if j == 0 and i == cols:
                    v[i].append(aj)
                else:
                    v[i].append(aj.clone().lerp(bj, j / rows))
        for i in range(cols):
            for j in range(2 * (cols - i) - 1):
                k = j // 2
                if j % 2 == 0:
                    push(v[i][k + 1]); push(v[i + 1][k]); push(v[i][k])
                else:
                    push(v[i][k + 1]); push(v[i + 1][k + 1]); push(v[i + 1][k])

    for i in range(0, len(indices), 3):
        a = Vector3().fromArray(vertices, indices[i] * 3)
        b = Vector3().fromArray(vertices, indices[i + 1] * 3)
        c = Vector3().fromArray(vertices, indices[i + 2] * 3)
        face(a, b, c, detail)
    for i in range(0, len(vb), 3):
        v = Vector3(vb[i], vb[i + 1], vb[i + 2]).normalize().multiplyScalar(radius)
        vb[i], vb[i + 1], vb[i + 2] = v.x, v.y, v.z

    def azimuth(v):
        return math.atan2(v.z, -v.x)

    def inclination(v):
        return math.atan2(-v.y, math.sqrt(v.x * v.x + v.z * v.z))

    for i in range(0, len(vb), 3):
        v = Vector3(vb[i], vb[i + 1], vb[i + 2])
        uvb.extend((azimuth(v) / 2 / math.pi + 0.5, 1 - (inclination(v) / math.pi + 0.5)))
    for i, j in zip(range(0, len(vb), 9), range(0, len(uvb), 6)):
        a = Vector3(vb[i], vb[i + 1], vb[i + 2])
        b = Vector3(vb[i + 3], vb[i + 4], vb[i + 5])
        c = Vector3(vb[i + 6], vb[i + 7], vb[i + 8])
        uvs3 = [(uvb[j], uvb[j + 1]), (uvb[j + 2], uvb[j + 3]), (uvb[j + 4], uvb[j + 5])]
        cen = a.clone().add(b).add(c).divideScalar(3)
        azi = azimuth(cen)
        for (ux, _uy), st, vec in zip(uvs3, (j, j + 2, j + 4), (a, b, c)):
            if azi < 0 and ux == 1:
                uvb[st] = ux - 1
            if vec.x == 0 and vec.z == 0:
                uvb[st] = azi / 2 / math.pi + 0.5
    for i in range(0, len(uvb), 6):
        x0, x1, x2 = uvb[i], uvb[i + 2], uvb[i + 4]
        if max(x0, x1, x2) > 0.9 and min(x0, x1, x2) < 0.1:
            if x0 < 0.2:
                uvb[i] += 1
            if x1 < 0.2:
                uvb[i + 2] += 1
            if x2 < 0.2:
                uvb[i + 4] += 1
    g.setAttribute("position", BufferAttribute(f32(vb), 3))
    g.setAttribute("normal", BufferAttribute(f32(vb), 3))
    g.setAttribute("uv", BufferAttribute(f32(uvb), 2))
    if detail == 0:
        g.computeVertexNormals()
    else:
        na = g.attributes["normal"].array
        for k in range(0, len(na), 3):
            v = Vector3(na[k], na[k + 1], na[k + 2]).normalize()
            na[k], na[k + 1], na[k + 2] = v.x, v.y, v.z
    return g


def IcosahedronGeometry(radius=1, detail=0):
    return PolyhedronGeometry(_ICO_V, _ICO_I, radius, detail)


# ---------------------------------------------------------------- Shape / Extrude

class Shape:
    def __init__(self):
        self.curves = []  # (Vector2, Vector2) の直線のみ
        self.current = Vector2()

    def moveTo(self, x, y):
        self.current = Vector2(x, y)
        return self

    def lineTo(self, x, y):
        self.curves.append((self.current.clone(), Vector2(x, y)))
        self.current = Vector2(x, y)
        return self

    def closePath(self):
        s = self.curves[0][0]
        e = self.curves[-1][1]
        if not s.equals(e):
            self.curves.append((e.clone(), s.clone()))
        return self

    def getPoints(self):
        pts = []
        last = None
        for a, b in self.curves:
            for p in (a.clone(), b.clone()):  # LineCurve.getPoints(1)
                if last is not None and last.equals(p):
                    continue
                pts.append(p)
                last = p
        return pts


def shape_area(contour):
    n = len(contour)
    a = 0.0
    p = n - 1
    for q in range(n):
        a += contour[p].x * contour[q].y - contour[q].x * contour[p].y
        p = q
    return a * 0.5


def triangulate_shape(contour, holes):
    contour = list(contour)
    if len(contour) > 2 and contour[-1].equals(contour[0]):
        contour.pop()
    verts = []
    for p in contour:
        verts.extend((p.x, p.y))
    hole_idx = []
    hi = len(contour)
    for h in holes:
        h = list(h)
        if len(h) > 2 and h[-1].equals(h[0]):
            h.pop()
        hole_idx.append(hi)
        hi += len(h)
        for p in h:
            verts.extend((p.x, p.y))
    tri = earcut(verts, hole_idx)
    return [tri[i:i + 3] for i in range(0, len(tri), 3)]


def ExtrudeGeometry(shape, depth=1, bevelEnabled=True, bevelThickness=0.2, bevelSize=None, bevelOffset=0,
                    bevelSegments=3, steps=1):
    """平行移動の押し出し（extrudePath なし、穴なし）"""
    if bevelSize is None:
        bevelSize = bevelThickness - 0.1
    if not bevelEnabled:
        bevelSegments = 0
        bevelThickness = bevelSize = bevelOffset = 0
    g = BufferGeometry()
    verticesArray, uvArray, placeholder = [], [], []
    vertices = shape.getPoints()
    if not (shape_area(vertices) < 0):
        vertices = vertices[::-1]
    # mergeOverlappingPoints
    TH2 = 1e-10 * 1e-10
    prev = vertices[0]
    i = 1
    while i <= len(vertices):
        ci = i % len(vertices)
        cur = vertices[ci]
        dx, dy = cur.x - prev.x, cur.y - prev.y
        sc = max(abs(cur.x), abs(cur.y), abs(prev.x), abs(prev.y))
        if dx * dx + dy * dy <= TH2 * sc * sc:
            vertices.pop(ci)
            continue
        prev = cur
        i += 1
    contour = vertices
    vlen = len(vertices)

    def bevel_vec(p, pp, pn):
        vpx, vpy = p.x - pp.x, p.y - pp.y
        vnx, vny = pn.x - p.x, pn.y - p.y
        vpl2 = vpx * vpx + vpy * vpy
        col = vpx * vny - vpy * vnx
        if abs(col) > EPSILON:
            vpl = math.sqrt(vpl2)
            vnl = math.sqrt(vnx * vnx + vny * vny)
            psx, psy = pp.x - vpy / vpl, pp.y + vpx / vpl
            nsx, nsy = pn.x - vny / vnl, pn.y + vnx / vnl
            sf = ((nsx - psx) * vny - (nsy - psy) * vnx) / (vpx * vny - vpy * vnx)
            tx = psx + vpx * sf - p.x
            ty = psy + vpy * sf - p.y
            tl2 = tx * tx + ty * ty
            if tl2 <= 2:
                return Vector2(tx, ty)
            shrink = math.sqrt(tl2 / 2)
        else:
            eq = False
            if vpx > EPSILON:
                eq = vnx > EPSILON
            elif vpx < -EPSILON:
                eq = vnx < -EPSILON
            else:
                sgn = lambda v: (v > 0) - (v < 0)
                eq = sgn(vpy) == sgn(vny)
            if eq:
                tx, ty, shrink = -vpy, vpx, math.sqrt(vpl2)
            else:
                tx, ty, shrink = vpx, vpy, math.sqrt(vpl2 / 2)
        return Vector2(tx / shrink, ty / shrink)

    il = len(contour)
    moves = []
    for i in range(il):
        moves.append(bevel_vec(contour[i], contour[(i - 1) % il], contour[(i + 1) % il]))

    def sp(pt, vec, size):
        return Vector2(pt.x + vec.x * size, pt.y + vec.y * size)

    def v(x, y, z):
        placeholder.extend((x, y, z))

    if bevelSegments == 0:
        faces = triangulate_shape(contour, [])
    else:
        contracted = []
        for b in range(bevelSegments):
            t = b / bevelSegments
            z = bevelThickness * math.cos(t * math.pi / 2)
            bs = bevelSize * math.sin(t * math.pi / 2) + bevelOffset
            for i in range(il):
                vert = sp(contour[i], moves[i], bs)
                v(vert.x, vert.y, -z)
                if t == 0:
                    contracted.append(vert)
        faces = triangulate_shape(contracted, [])
    flen = len(faces)
    bs = bevelSize + bevelOffset
    for i in range(vlen):
        vert = sp(vertices[i], moves[i], bs) if bevelEnabled else vertices[i]
        v(vert.x, vert.y, 0)
    for s in range(1, steps + 1):
        for i in range(vlen):
            vert = sp(vertices[i], moves[i], bs) if bevelEnabled else vertices[i]
            v(vert.x, vert.y, depth / steps * s)
    for b in range(bevelSegments - 1, -1, -1):
        t = b / bevelSegments
        z = bevelThickness * math.cos(t * math.pi / 2)
        bs2 = bevelSize * math.sin(t * math.pi / 2) + bevelOffset
        for i in range(il):
            vert = sp(contour[i], moves[i], bs2)
            v(vert.x, vert.y, depth + z)

    def addv(k):
        verticesArray.extend(placeholder[k * 3:k * 3 + 3])

    def f3(a, b, c):
        addv(a); addv(b); addv(c)
        n = len(verticesArray) // 3
        for k in (n - 3, n - 2, n - 1):
            uvArray.extend((verticesArray[k * 3], verticesArray[k * 3 + 1]))

    def f4(a, b, c, d):
        for k in (a, b, d, b, c, d):
            addv(k)
        n = len(verticesArray) // 3
        ia, ib, ic, id_ = n - 6, n - 3, n - 2, n - 1
        VA = verticesArray
        P = [(VA[k * 3], VA[k * 3 + 1], VA[k * 3 + 2]) for k in (ia, ib, ic, id_)]
        if abs(P[0][1] - P[1][1]) < abs(P[0][0] - P[1][0]):
            uv = [(p[0], 1 - p[2]) for p in P]
        else:
            uv = [(p[1], 1 - p[2]) for p in P]
        for q in (0, 1, 3, 1, 2, 3):
            uvArray.extend(uv[q])

    start = 0
    if bevelEnabled:
        off = 0
        for fc in faces:
            f3(fc[2] + off, fc[1] + off, fc[0] + off)
        off = vlen * (steps + bevelSegments * 2)
        for fc in faces:
            f3(fc[0] + off, fc[1] + off, fc[2] + off)
    else:
        for fc in faces:
            f3(fc[2], fc[1], fc[0])
        for fc in faces:
            f3(fc[0] + vlen * steps, fc[1] + vlen * steps, fc[2] + vlen * steps)
    g.addGroup(start, len(verticesArray) // 3 - start, 0)
    start = len(verticesArray) // 3
    i = len(contour)
    while True:
        i -= 1
        if i < 0:
            break
        j = i
        k = i - 1 if i - 1 >= 0 else len(contour) - 1
        for s in range(steps + bevelSegments * 2):
            s1, s2 = vlen * s, vlen * (s + 1)
            f4(j + s1, k + s1, k + s2, j + s2)
    g.addGroup(start, len(verticesArray) // 3 - start, 1)
    g.setAttribute("position", BufferAttribute(f32(verticesArray), 3))
    g.setAttribute("uv", BufferAttribute(f32(uvArray), 2))
    g.computeVertexNormals()
    return g


# ---------------------------------------------------------------- earcut (mapbox earcut 3.x)

class _Node:
    __slots__ = ("i", "x", "y", "prev", "next", "z", "prevZ", "nextZ", "steiner")

    def __init__(self, i, x, y):
        self.i, self.x, self.y = i, x, y
        self.prev = self.next = None
        self.z = 0
        self.prevZ = self.nextZ = None
        self.steiner = False


def _signed_area(data, start, end, dim):
    s = 0
    j = end - dim
    for i in range(start, end, dim):
        s += (data[j] - data[i]) * (data[i + 1] + data[j + 1])
        j = i
    return s


def _insert(i, x, y, last):
    p = _Node(i, x, y)
    if last is None:
        p.prev = p
        p.next = p
    else:
        p.next = last.next
        p.prev = last
        last.next.prev = p
        last.next = p
    return p


def _remove(p):
    p.next.prev = p.prev
    p.prev.next = p.next
    if p.prevZ:
        p.prevZ.nextZ = p.nextZ
    if p.nextZ:
        p.nextZ.prevZ = p.prevZ


def _equals(a, b):
    return a.x == b.x and a.y == b.y


def _area(p, q, r):
    return (q.y - p.y) * (r.x - q.x) - (q.x - p.x) * (r.y - q.y)


def _linked_list(data, start, end, dim, clockwise):
    last = None
    if clockwise == (_signed_area(data, start, end, dim) > 0):
        for i in range(start, end, dim):
            last = _insert(i // dim, data[i], data[i + 1], last)
    else:
        for i in range(end - dim, start - 1, -dim):
            last = _insert(i // dim, data[i], data[i + 1], last)
    if last is not None and _equals(last, last.next):
        _remove(last)
        last = last.next
    return last


def _filter_points(start, end=None):
    if start is None:
        return start
    if end is None:
        end = start
    p = start
    while True:
        again = False
        if not p.steiner and (_equals(p, p.next) or _area(p.prev, p, p.next) == 0):
            _remove(p)
            p = end = p.prev
            if p is p.next:
                break
            again = True
        else:
            p = p.next
        if not (again or p is not end):
            break
    return end


def _pit(ax, ay, bx, by, cx, cy, px, py):
    return ((cx - px) * (ay - py) >= (ax - px) * (cy - py) and (ax - px) * (by - py) >= (bx - px) * (ay - py)
            and (bx - px) * (cy - py) >= (cx - px) * (by - py))


def _pit_ef(ax, ay, bx, by, cx, cy, px, py):
    return not (ax == px and ay == py) and _pit(ax, ay, bx, by, cx, cy, px, py)


def _is_ear(ear):
    a, b, c = ear.prev, ear, ear.next
    if _area(a, b, c) >= 0:
        return False
    ax, bx, cx, ay, by, cy = a.x, b.x, c.x, a.y, b.y, c.y
    x0, y0, x1, y1 = min(ax, bx, cx), min(ay, by, cy), max(ax, bx, cx), max(ay, by, cy)
    p = c.next
    while p is not a:
        if (x0 <= p.x <= x1 and y0 <= p.y <= y1 and _pit_ef(ax, ay, bx, by, cx, cy, p.x, p.y)
                and _area(p.prev, p, p.next) >= 0):
            return False
        p = p.next
    return True


def _z_order(x, y, minX, minY, invSize):
    x = int((x - minX) * invSize) & 0xFFFFFFFF
    y = int((y - minY) * invSize) & 0xFFFFFFFF
    x = (x | (x << 8)) & 0x00FF00FF
    x = (x | (x << 4)) & 0x0F0F0F0F
    x = (x | (x << 2)) & 0x33333333
    x = (x | (x << 1)) & 0x55555555
    y = (y | (y << 8)) & 0x00FF00FF
    y = (y | (y << 4)) & 0x0F0F0F0F
    y = (y | (y << 2)) & 0x33333333
    y = (y | (y << 1)) & 0x55555555
    r = (x | (y << 1)) & 0xFFFFFFFF
    return r - 0x100000000 if r & 0x80000000 else r


def _is_ear_hashed(ear, minX, minY, invSize):
    a, b, c = ear.prev, ear, ear.next
    if _area(a, b, c) >= 0:
        return False
    ax, bx, cx, ay, by, cy = a.x, b.x, c.x, a.y, b.y, c.y
    x0, y0, x1, y1 = min(ax, bx, cx), min(ay, by, cy), max(ax, bx, cx), max(ay, by, cy)
    minZ = _z_order(x0, y0, minX, minY, invSize)
    maxZ = _z_order(x1, y1, minX, minY, invSize)
    p, n = ear.prevZ, ear.nextZ

    def bad(q):
        return (x0 <= q.x <= x1 and y0 <= q.y <= y1 and q is not a and q is not c
                and _pit_ef(ax, ay, bx, by, cx, cy, q.x, q.y) and _area(q.prev, q, q.next) >= 0)
    while p is not None and p.z >= minZ and n is not None and n.z <= maxZ:
        if bad(p):
            return False
        p = p.prevZ
        if bad(n):
            return False
        n = n.nextZ
    while p is not None and p.z >= minZ:
        if bad(p):
            return False
        p = p.prevZ
    while n is not None and n.z <= maxZ:
        if bad(n):
            return False
        n = n.nextZ
    return True


def _sign(v):
    return 1 if v > 0 else -1 if v < 0 else 0


def _on_segment(p, q, r):
    return max(p.x, r.x) >= q.x >= min(p.x, r.x) and max(p.y, r.y) >= q.y >= min(p.y, r.y)


def _intersects(p1, q1, p2, q2):
    o1 = _sign(_area(p1, q1, p2))
    o2 = _sign(_area(p1, q1, q2))
    o3 = _sign(_area(p2, q2, p1))
    o4 = _sign(_area(p2, q2, q1))
    if o1 != o2 and o3 != o4:
        return True
    if o1 == 0 and _on_segment(p1, p2, q1):
        return True
    if o2 == 0 and _on_segment(p1, q2, q1):
        return True
    if o3 == 0 and _on_segment(p2, p1, q2):
        return True
    if o4 == 0 and _on_segment(p2, q1, q2):
        return True
    return False


def _locally_inside(a, b):
    if _area(a.prev, a, a.next) < 0:
        return _area(a, b, a.next) >= 0 and _area(a, a.prev, b) >= 0
    return _area(a, b, a.prev) < 0 or _area(a, a.next, b) < 0


def _middle_inside(a, b):
    p = a
    inside = False
    px, py = (a.x + b.x) / 2, (a.y + b.y) / 2
    while True:
        if ((p.y > py) != (p.next.y > py)) and p.next.y != p.y and \
                (px < (p.next.x - p.x) * (py - p.y) / (p.next.y - p.y) + p.x):
            inside = not inside
        p = p.next
        if p is a:
            break
    return inside


def _intersects_polygon(a, b):
    p = a
    while True:
        if p.i != a.i and p.next.i != a.i and p.i != b.i and p.next.i != b.i and _intersects(p, p.next, a, b):
            return True
        p = p.next
        if p is a:
            break
    return False


def _is_valid_diagonal(a, b):
    return (a.next.i != b.i and a.prev.i != b.i and not _intersects_polygon(a, b) and
            ((_locally_inside(a, b) and _locally_inside(b, a) and _middle_inside(a, b) and
              bool(_area(a.prev, a, b.prev) or _area(a, b.prev, b))) or
             (_equals(a, b) and _area(a.prev, a, a.next) > 0 and _area(b.prev, b, b.next) > 0)))


def _split_polygon(a, b):
    a2 = _Node(a.i, a.x, a.y)
    b2 = _Node(b.i, b.x, b.y)
    an, bp = a.next, b.prev
    a.next = b
    b.prev = a
    a2.next = an
    an.prev = a2
    b2.next = a2
    a2.prev = b2
    bp.next = b2
    b2.prev = bp
    return b2


def _cure(start, tri):
    p = start
    while True:
        a, b = p.prev, p.next.next
        if not _equals(a, b) and _intersects(a, p, p.next, b) and _locally_inside(a, b) and _locally_inside(b, a):
            tri.extend((a.i, p.i, b.i))
            _remove(p)
            _remove(p.next)
            p = start = b
        p = p.next
        if p is start:
            break
    return _filter_points(p)


def _split_earcut(start, tri, dim, minX, minY, invSize):
    a = start
    while True:
        b = a.next.next
        while b is not a.prev:
            if a.i != b.i and _is_valid_diagonal(a, b):
                c = _split_polygon(a, b)
                a = _filter_points(a, a.next)
                c = _filter_points(c, c.next)
                _earcut_linked(a, tri, dim, minX, minY, invSize, 0)
                _earcut_linked(c, tri, dim, minX, minY, invSize, 0)
                return
            b = b.next
        a = a.next
        if a is start:
            break


def _sort_linked(lst):
    in_size = 1
    while True:
        p = lst
        lst = None
        tail = None
        merges = 0
        while p is not None:
            merges += 1
            q = p
            ps = 0
            for _ in range(in_size):
                ps += 1
                q = q.nextZ
                if q is None:
                    break
            qs = in_size
            while ps > 0 or (qs > 0 and q is not None):
                if ps != 0 and (qs == 0 or q is None or p.z <= q.z):
                    e = p
                    p = p.nextZ
                    ps -= 1
                else:
                    e = q
                    q = q.nextZ
                    qs -= 1
                if tail is not None:
                    tail.nextZ = e
                else:
                    lst = e
                e.prevZ = tail
                tail = e
            p = q
        tail.nextZ = None
        in_size *= 2
        if merges <= 1:
            break
    return lst


def _index_curve(start, minX, minY, invSize):
    p = start
    while True:
        if p.z == 0:
            p.z = _z_order(p.x, p.y, minX, minY, invSize)
        p.prevZ = p.prev
        p.nextZ = p.next
        p = p.next
        if p is start:
            break
    p.prevZ.nextZ = None
    p.prevZ = None
    _sort_linked(p)


def _earcut_linked(ear, tri, dim, minX, minY, invSize, pss):
    if ear is None:
        return
    if not pss and invSize:
        _index_curve(ear, minX, minY, invSize)
    stop = ear
    while ear.prev is not ear.next:
        prev, nxt = ear.prev, ear.next
        if _is_ear_hashed(ear, minX, minY, invSize) if invSize else _is_ear(ear):
            tri.extend((prev.i, ear.i, nxt.i))
            _remove(ear)
            ear = nxt.next
            stop = nxt.next
            continue
        ear = nxt
        if ear is stop:
            if not pss:
                _earcut_linked(_filter_points(ear), tri, dim, minX, minY, invSize, 1)
            elif pss == 1:
                ear = _cure(_filter_points(ear), tri)
                _earcut_linked(ear, tri, dim, minX, minY, invSize, 2)
            elif pss == 2:
                _split_earcut(ear, tri, dim, minX, minY, invSize)
            break


def earcut(data, hole_indices=None, dim=2):
    if hole_indices:
        raise NotImplementedError("穴あき形状は未使用")
    outer_len = len(data)
    outer = _linked_list(data, 0, outer_len, dim, True)
    tri = []
    if outer is None or outer.next is outer.prev:
        return tri
    minX = minY = invSize = 0
    if len(data) > 80 * dim:
        minX = minY = math.inf
        maxX = maxY = -math.inf
        for i in range(dim, outer_len, dim):
            x, y = data[i], data[i + 1]
            minX = min(minX, x)
            minY = min(minY, y)
            maxX = max(maxX, x)
            maxY = max(maxY, y)
        invSize = max(maxX - minX, maxY - minY)
        invSize = 32767 / invSize if invSize != 0 else 0
    _earcut_linked(outer, tri, dim, minX, minY, invSize, 0)
    return tri


# ---------------------------------------------------------------- merge / edges

def mergeGeometries(geos, useGroups=False):
    first = geos[0]
    indexed = first.index is not None
    names = list(first.attributes.keys())
    out = BufferGeometry()
    for g in geos:
        if (g.index is not None) != indexed or set(g.attributes.keys()) != set(names):
            return None
    if useGroups:
        off = 0
        for i, g in enumerate(geos):
            c = len(g.index.array) if indexed else g.attributes["position"].count
            out.addGroup(off, c, i)
            off += c
    if indexed:
        idx = []
        o = 0
        for g in geos:
            idx.extend(i + o for i in g.index.array)
            o += g.attributes["position"].count
        out.setIndex(idx)
    for name in names:
        size = first.attributes[name].itemSize
        arr = f32([])
        for g in geos:
            a = g.attributes[name]
            if a.itemSize != size:
                return None
            arr.extend(a.array)
        out.setAttribute(name, BufferAttribute(arr, size))
    return out


def _round(x):
    return int(math.floor(x + 0.5))


def EdgesGeometry(geometry, thresholdAngle=1):
    prec = 10 ** 4
    thr = math.cos(math.pi / 180 * thresholdAngle)
    pos = geometry.attributes["position"].array
    idx = geometry.index.array if geometry.index is not None else None
    count = len(idx) if idx is not None else len(pos) // 3
    edge = {}
    verts = []
    for i in range(0, count, 3):
        ia = (idx[i], idx[i + 1], idx[i + 2]) if idx is not None else (i, i + 1, i + 2)
        P = [(pos[k * 3], pos[k * 3 + 1], pos[k * 3 + 2]) for k in ia]
        (ax, ay, az), (bx, by, bz), (cx, cy, cz) = P
        tx, ty, tz = cx - bx, cy - by, cz - bz
        ux, uy, uz = ax - bx, ay - by, az - bz
        nx = ty * uz - tz * uy
        ny = tz * ux - tx * uz
        nz = tx * uy - ty * ux
        l2 = nx * nx + ny * ny + nz * nz
        if l2 > 0:
            s = 1 / math.sqrt(l2)
            nx, ny, nz = nx * s, ny * s, nz * s
        else:
            nx = ny = nz = 0
        h = ["%d,%d,%d" % (_round(p[0] * prec), _round(p[1] * prec), _round(p[2] * prec)) for p in P]
        if h[0] == h[1] or h[1] == h[2] or h[2] == h[0]:
            continue
        for j in range(3):
            jn = (j + 1) % 3
            h0, h1 = h[j], h[jn]
            key = h0 + "_" + h1
            rkey = h1 + "_" + h0
            r = edge.get(rkey)
            if r:
                if nx * r[2][0] + ny * r[2][1] + nz * r[2][2] <= thr:
                    verts.extend(P[j])
                    verts.extend(P[jn])
                edge[rkey] = None
            elif key not in edge:
                edge[key] = (ia[j], ia[jn], (nx, ny, nz))
    for d in edge.values():
        if d:
            i0, i1 = d[0], d[1]
            verts.extend(pos[i0 * 3:i0 * 3 + 3])
            verts.extend(pos[i1 * 3:i1 * 3 + 3])
    g = BufferGeometry()
    g.setAttribute("position", BufferAttribute(f32(verts), 3))
    return g

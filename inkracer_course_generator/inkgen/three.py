"""three.js (r180) の必要な部分を Python に移植したもの。
InkRacer のコース生成を同じ数値で再現するため、計算の順番・float32 の丸めまで元の実装に合わせている。
Blender には依存しない（単体でテストできる）。
"""
import math
from array import array

EPSILON = 2.220446049250313e-16


def f32(values):
    """Float32Array 相当（代入時に float32 へ丸める）"""
    return array("f", values)


def imul(a, b):
    """Math.imul（32bit 符号付き整数の掛け算）"""
    r = ((a & 0xFFFFFFFF) * (b & 0xFFFFFFFF)) & 0xFFFFFFFF
    return r - 0x100000000 if r & 0x80000000 else r


def u32(a):
    return a & 0xFFFFFFFF


def lcg_random(seed):
    """state = (Math.imul(state, 1664525) + 1013904223) >>> 0; return state / 2^32"""
    state = [seed]

    def random():
        state[0] = u32(imul(state[0], 1664525) + 1013904223)
        return state[0] / 4294967296
    return random


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def js_round(x):
    """Math.round（.5 は +∞ 方向）"""
    return math.floor(x + 0.5)


# ---------------------------------------------------------------- Vector2 / Vector3

class Vector2:
    __slots__ = ("x", "y")

    def __init__(self, x=0.0, y=0.0):
        self.x, self.y = x, y

    def clone(self):
        return Vector2(self.x, self.y)

    def copy(self, v):
        self.x, self.y = v.x, v.y
        return self

    def set(self, x, y):
        self.x, self.y = x, y
        return self

    def add(self, v):
        self.x += v.x
        self.y += v.y
        return self

    def sub(self, v):
        self.x -= v.x
        self.y -= v.y
        return self

    def subVectors(self, a, b):
        self.x, self.y = a.x - b.x, a.y - b.y
        return self

    def multiplyScalar(self, s):
        self.x *= s
        self.y *= s
        return self

    def divideScalar(self, s):
        return self.multiplyScalar(1 / s)

    def length(self):
        return math.sqrt(self.x * self.x + self.y * self.y)

    def lengthSq(self):
        return self.x * self.x + self.y * self.y

    def normalize(self):
        return self.divideScalar(self.length() or 1)

    def dot(self, v):
        return self.x * v.x + self.y * v.y

    def cross(self, v):
        return self.x * v.y - self.y * v.x

    def distanceTo(self, v):
        return math.sqrt((self.x - v.x) ** 2 + (self.y - v.y) ** 2)

    def equals(self, v):
        return self.x == v.x and self.y == v.y

    def toArray(self):
        return [self.x, self.y]

    isVector2 = True


class Vector3:
    __slots__ = ("x", "y", "z")
    isVector2 = False

    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x, self.y, self.z = x, y, z

    def __repr__(self):
        return "V3(%r, %r, %r)" % (self.x, self.y, self.z)

    def set(self, x, y, z):
        self.x, self.y, self.z = x, y, z
        return self

    def setY(self, y):
        self.y = y
        return self

    def clone(self):
        return Vector3(self.x, self.y, self.z)

    def copy(self, v):
        self.x, self.y, self.z = v.x, v.y, v.z
        return self

    def add(self, v):
        self.x += v.x
        self.y += v.y
        self.z += v.z
        return self

    def addVectors(self, a, b):
        self.x, self.y, self.z = a.x + b.x, a.y + b.y, a.z + b.z
        return self

    def addScaledVector(self, v, s):
        self.x += v.x * s
        self.y += v.y * s
        self.z += v.z * s
        return self

    def sub(self, v):
        self.x -= v.x
        self.y -= v.y
        self.z -= v.z
        return self

    def subVectors(self, a, b):
        self.x, self.y, self.z = a.x - b.x, a.y - b.y, a.z - b.z
        return self

    def multiplyScalar(self, s):
        self.x *= s
        self.y *= s
        self.z *= s
        return self

    def divideScalar(self, s):
        return self.multiplyScalar(1 / s)

    def negate(self):
        self.x, self.y, self.z = -self.x, -self.y, -self.z
        return self

    def dot(self, v):
        return self.x * v.x + self.y * v.y + self.z * v.z

    def lengthSq(self):
        return self.x * self.x + self.y * self.y + self.z * self.z

    def length(self):
        return math.sqrt(self.x * self.x + self.y * self.y + self.z * self.z)

    def normalize(self):
        return self.divideScalar(self.length() or 1)

    def setLength(self, l):
        return self.normalize().multiplyScalar(l)

    def cross(self, v):
        return self.crossVectors(self, v)

    def crossVectors(self, a, b):
        ax, ay, az = a.x, a.y, a.z
        bx, by, bz = b.x, b.y, b.z
        self.x = ay * bz - az * by
        self.y = az * bx - ax * bz
        self.z = ax * by - ay * bx
        return self

    def distanceTo(self, v):
        return math.sqrt(self.distanceToSquared(v))

    def distanceToSquared(self, v):
        dx, dy, dz = self.x - v.x, self.y - v.y, self.z - v.z
        return dx * dx + dy * dy + dz * dz

    def lerp(self, v, alpha):
        self.x += (v.x - self.x) * alpha
        self.y += (v.y - self.y) * alpha
        self.z += (v.z - self.z) * alpha
        return self

    def lerpVectors(self, a, b, alpha):
        self.x = a.x + (b.x - a.x) * alpha
        self.y = a.y + (b.y - a.y) * alpha
        self.z = a.z + (b.z - a.z) * alpha
        return self

    def applyQuaternion(self, q):
        vx, vy, vz = self.x, self.y, self.z
        qx, qy, qz, qw = q.x, q.y, q.z, q.w
        tx = 2 * (qy * vz - qz * vy)
        ty = 2 * (qz * vx - qx * vz)
        tz = 2 * (qx * vy - qy * vx)
        self.x = vx + qw * tx + qy * tz - qz * ty
        self.y = vy + qw * ty + qz * tx - qx * tz
        self.z = vz + qw * tz + qx * ty - qy * tx
        return self

    def applyAxisAngle(self, axis, angle):
        return self.applyQuaternion(Quaternion().setFromAxisAngle(axis, angle))

    def applyMatrix3(self, m):
        x, y, z = self.x, self.y, self.z
        e = m.elements
        self.x = e[0] * x + e[3] * y + e[6] * z
        self.y = e[1] * x + e[4] * y + e[7] * z
        self.z = e[2] * x + e[5] * y + e[8] * z
        return self

    def applyNormalMatrix(self, m):
        return self.applyMatrix3(m).normalize()

    def applyMatrix4(self, m):
        x, y, z = self.x, self.y, self.z
        e = m.elements
        w = 1 / (e[3] * x + e[7] * y + e[11] * z + e[15])
        self.x = (e[0] * x + e[4] * y + e[8] * z + e[12]) * w
        self.y = (e[1] * x + e[5] * y + e[9] * z + e[13]) * w
        self.z = (e[2] * x + e[6] * y + e[10] * z + e[14]) * w
        return self

    def transformDirection(self, m):
        x, y, z = self.x, self.y, self.z
        e = m.elements
        self.x = e[0] * x + e[4] * y + e[8] * z
        self.y = e[1] * x + e[5] * y + e[9] * z
        self.z = e[2] * x + e[6] * y + e[10] * z
        return self.normalize()

    def toArray(self):
        return [self.x, self.y, self.z]

    def fromArray(self, a, offset=0):
        self.x, self.y, self.z = a[offset], a[offset + 1], a[offset + 2]
        return self

    def fromBufferAttribute(self, attr, i):
        a = attr.array
        k = i * attr.itemSize
        self.x, self.y, self.z = a[k], a[k + 1], a[k + 2]
        return self

    def equals(self, v):
        return self.x == v.x and self.y == v.y and self.z == v.z


# ---------------------------------------------------------------- Quaternion / Matrix

class Quaternion:
    __slots__ = ("x", "y", "z", "w")

    def __init__(self, x=0.0, y=0.0, z=0.0, w=1.0):
        self.x, self.y, self.z, self.w = x, y, z, w

    def setFromAxisAngle(self, axis, angle):
        half = angle / 2
        s = math.sin(half)
        self.x, self.y, self.z = axis.x * s, axis.y * s, axis.z * s
        self.w = math.cos(half)
        return self

    def length(self):
        return math.sqrt(self.x * self.x + self.y * self.y + self.z * self.z + self.w * self.w)

    def normalize(self):
        l = self.length()
        if l == 0:
            self.x = self.y = self.z = 0.0
            self.w = 1.0
        else:
            l = 1 / l
            self.x, self.y, self.z, self.w = self.x * l, self.y * l, self.z * l, self.w * l
        return self

    def setFromUnitVectors(self, vFrom, vTo):
        r = vFrom.dot(vTo) + 1
        if r < 1e-8:
            r = 0
            if abs(vFrom.x) > abs(vFrom.z):
                self.x, self.y, self.z, self.w = -vFrom.y, vFrom.x, 0, r
            else:
                self.x, self.y, self.z, self.w = 0, -vFrom.z, vFrom.y, r
        else:
            self.x = vFrom.y * vTo.z - vFrom.z * vTo.y
            self.y = vFrom.z * vTo.x - vFrom.x * vTo.z
            self.z = vFrom.x * vTo.y - vFrom.y * vTo.x
            self.w = r
        return self.normalize()


class Matrix3:
    __slots__ = ("elements",)

    def __init__(self):
        self.elements = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]

    def set(self, n11, n12, n13, n21, n22, n23, n31, n32, n33):
        self.elements = [n11, n21, n31, n12, n22, n32, n13, n23, n33]
        return self

    def setFromMatrix4(self, m):
        me = m.elements
        return self.set(me[0], me[4], me[8], me[1], me[5], me[9], me[2], me[6], me[10])

    def invert(self):
        te = self.elements
        n11, n21, n31 = te[0], te[1], te[2]
        n12, n22, n32 = te[3], te[4], te[5]
        n13, n23, n33 = te[6], te[7], te[8]
        t11 = n33 * n22 - n32 * n23
        t12 = n32 * n13 - n33 * n12
        t13 = n23 * n12 - n22 * n13
        det = n11 * t11 + n21 * t12 + n31 * t13
        if det == 0:
            return self.set(0, 0, 0, 0, 0, 0, 0, 0, 0)
        d = 1 / det
        te[0] = t11 * d
        te[1] = (n31 * n23 - n33 * n21) * d
        te[2] = (n32 * n21 - n31 * n22) * d
        te[3] = t12 * d
        te[4] = (n33 * n11 - n31 * n13) * d
        te[5] = (n31 * n12 - n32 * n11) * d
        te[6] = t13 * d
        te[7] = (n21 * n13 - n23 * n11) * d
        te[8] = (n22 * n11 - n21 * n12) * d
        return self

    def transpose(self):
        m = self.elements
        m[1], m[3] = m[3], m[1]
        m[2], m[6] = m[6], m[2]
        m[5], m[7] = m[7], m[5]
        return self

    def getNormalMatrix(self, m4):
        return self.setFromMatrix4(m4).invert().transpose()


class Matrix4:
    __slots__ = ("elements",)

    def __init__(self):
        self.elements = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]

    def set(self, n11, n12, n13, n14, n21, n22, n23, n24, n31, n32, n33, n34, n41, n42, n43, n44):
        self.elements = [n11, n21, n31, n41, n12, n22, n32, n42, n13, n23, n33, n43, n14, n24, n34, n44]
        return self

    def makeRotationX(self, theta):
        c, s = math.cos(theta), math.sin(theta)
        return self.set(1, 0, 0, 0, 0, c, -s, 0, 0, s, c, 0, 0, 0, 0, 1)

    def makeRotationY(self, theta):
        c, s = math.cos(theta), math.sin(theta)
        return self.set(c, 0, s, 0, 0, 1, 0, 0, -s, 0, c, 0, 0, 0, 0, 1)

    def makeRotationZ(self, theta):
        c, s = math.cos(theta), math.sin(theta)
        return self.set(c, -s, 0, 0, s, c, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)

    def makeRotationAxis(self, axis, angle):
        c, s = math.cos(angle), math.sin(angle)
        t = 1 - c
        x, y, z = axis.x, axis.y, axis.z
        tx, ty = t * x, t * y
        return self.set(tx * x + c, tx * y - s * z, tx * z + s * y, 0,
                        tx * y + s * z, ty * y + c, ty * z - s * x, 0,
                        tx * z - s * y, ty * z + s * x, t * z * z + c, 0,
                        0, 0, 0, 1)

    def makeTranslation(self, x, y, z):
        return self.set(1, 0, 0, x, 0, 1, 0, y, 0, 0, 1, z, 0, 0, 0, 1)

    def makeScale(self, x, y, z):
        return self.set(x, 0, 0, 0, 0, y, 0, 0, 0, 0, z, 0, 0, 0, 0, 1)

    def compose(self, position, q, scale):
        te = self.elements
        x, y, z, w = q.x, q.y, q.z, q.w
        x2, y2, z2 = x + x, y + y, z + z
        xx, xy, xz = x * x2, x * y2, x * z2
        yy, yz, zz = y * y2, y * z2, z * z2
        wx, wy, wz = w * x2, w * y2, w * z2
        sx, sy, sz = scale.x, scale.y, scale.z
        te[0] = (1 - (yy + zz)) * sx
        te[1] = (xy + wz) * sx
        te[2] = (xz - wy) * sx
        te[3] = 0
        te[4] = (xy - wz) * sy
        te[5] = (1 - (xx + zz)) * sy
        te[6] = (yz + wx) * sy
        te[7] = 0
        te[8] = (xz + wy) * sz
        te[9] = (yz - wx) * sz
        te[10] = (1 - (xx + yy)) * sz
        te[11] = 0
        te[12] = position.x
        te[13] = position.y
        te[14] = position.z
        te[15] = 1
        return self

    def makeRotationFromQuaternion(self, q):
        return self.compose(Vector3(0, 0, 0), q, Vector3(1, 1, 1))


# ---------------------------------------------------------------- BufferGeometry

class BufferAttribute:
    __slots__ = ("array", "itemSize")

    def __init__(self, arr, itemSize):
        self.array = arr
        self.itemSize = itemSize

    @property
    def count(self):
        return len(self.array) // self.itemSize

    def getX(self, i):
        return self.array[i * self.itemSize]

    def getY(self, i):
        return self.array[i * self.itemSize + 1]

    def getZ(self, i):
        return self.array[i * self.itemSize + 2]

    def setX(self, i, v):
        self.array[i * self.itemSize] = v

    def setZ(self, i, v):
        self.array[i * self.itemSize + 2] = v

    def setXYZ(self, i, x, y, z):
        k = i * self.itemSize
        a = self.array
        a[k], a[k + 1], a[k + 2] = x, y, z

    def clone(self):
        return BufferAttribute(array(self.array.typecode, self.array) if isinstance(self.array, array) else list(self.array), self.itemSize)

    def applyMatrix4(self, m):
        a = self.array
        e = m.elements
        e0, e1, e2, e3, e4, e5, e6, e7, e8, e9, e10, e11, e12, e13, e14, e15 = e
        for k in range(0, len(a), 3):
            x, y, z = a[k], a[k + 1], a[k + 2]
            w = 1 / (e3 * x + e7 * y + e11 * z + e15)
            a[k] = (e0 * x + e4 * y + e8 * z + e12) * w
            a[k + 1] = (e1 * x + e5 * y + e9 * z + e13) * w
            a[k + 2] = (e2 * x + e6 * y + e10 * z + e14) * w
        return self

    def applyNormalMatrix(self, m):
        a = self.array
        e = m.elements
        for k in range(0, len(a), 3):
            x, y, z = a[k], a[k + 1], a[k + 2]
            nx = e[0] * x + e[3] * y + e[6] * z
            ny = e[1] * x + e[4] * y + e[7] * z
            nz = e[2] * x + e[5] * y + e[8] * z
            l = math.sqrt(nx * nx + ny * ny + nz * nz) or 1
            l = 1 / l
            a[k], a[k + 1], a[k + 2] = nx * l, ny * l, nz * l
        return self


class BufferGeometry:
    def __init__(self):
        self.attributes = {}
        self.index = None
        self.groups = []
        self.name = ""

    def setAttribute(self, name, attr):
        self.attributes[name] = attr
        return self

    def getAttribute(self, name):
        return self.attributes.get(name)

    def deleteAttribute(self, name):
        self.attributes.pop(name, None)
        return self

    def setIndex(self, index):
        self.index = None if index is None else BufferAttribute(list(index), 1)
        return self

    def getIndex(self):
        return self.index

    def addGroup(self, start, count, materialIndex=0):
        self.groups.append({"start": start, "count": count, "materialIndex": materialIndex})

    def clearGroups(self):
        self.groups = []

    def applyMatrix4(self, matrix):
        pos = self.attributes.get("position")
        if pos is not None:
            pos.applyMatrix4(matrix)
        nor = self.attributes.get("normal")
        if nor is not None:
            nor.applyNormalMatrix(Matrix3().getNormalMatrix(matrix))
        return self

    def applyQuaternion(self, q):
        return self.applyMatrix4(Matrix4().makeRotationFromQuaternion(q))

    def rotateX(self, a):
        return self.applyMatrix4(Matrix4().makeRotationX(a))

    def rotateY(self, a):
        return self.applyMatrix4(Matrix4().makeRotationY(a))

    def rotateZ(self, a):
        return self.applyMatrix4(Matrix4().makeRotationZ(a))

    def translate(self, x, y, z):
        return self.applyMatrix4(Matrix4().makeTranslation(x, y, z))

    def scale(self, x, y, z):
        return self.applyMatrix4(Matrix4().makeScale(x, y, z))

    def clone(self):
        g = BufferGeometry()
        g.name = self.name
        g.index = None if self.index is None else BufferAttribute(list(self.index.array), 1)
        for k, v in self.attributes.items():
            g.attributes[k] = v.clone()
        g.groups = [dict(x) for x in self.groups]
        return g

    def toNonIndexed(self):
        if self.index is None:
            return self
        g = BufferGeometry()
        idx = self.index.array
        for name, attr in self.attributes.items():
            s = attr.itemSize
            src = attr.array
            out = []
            for i in idx:
                k = i * s
                out.extend(src[k:k + s])
            g.attributes[name] = BufferAttribute(array(src.typecode, out) if isinstance(src, array) else out, s)
        for gr in self.groups:
            g.addGroup(gr["start"], gr["count"], gr["materialIndex"])
        return g

    def computeVertexNormals(self):
        pos = self.attributes.get("position")
        if pos is None:
            return
        p = pos.array
        n = len(p)
        nor = self.attributes.get("normal")
        if nor is None:
            nor = BufferAttribute(f32([0.0]) * n if n else f32([]), 3)
            self.attributes["normal"] = nor
        else:
            for k in range(n):
                nor.array[k] = 0.0
        na = nor.array
        if self.index is not None:
            idx = self.index.array
            for i in range(0, len(idx), 3):
                a, b, c = idx[i] * 3, idx[i + 1] * 3, idx[i + 2] * 3
                pax, pay, paz = p[a], p[a + 1], p[a + 2]
                pbx, pby, pbz = p[b], p[b + 1], p[b + 2]
                pcx, pcy, pcz = p[c], p[c + 1], p[c + 2]
                cbx, cby, cbz = pcx - pbx, pcy - pby, pcz - pbz
                abx, aby, abz = pax - pbx, pay - pby, paz - pbz
                cx = cby * abz - cbz * aby
                cy = cbz * abx - cbx * abz
                cz = cbx * aby - cby * abx
                for v in (a, b, c):
                    na[v] = na[v] + cx
                    na[v + 1] = na[v + 1] + cy
                    na[v + 2] = na[v + 2] + cz
        else:
            for a in range(0, n, 9):
                b, c = a + 3, a + 6
                cbx, cby, cbz = p[c] - p[b], p[c + 1] - p[b + 1], p[c + 2] - p[b + 2]
                abx, aby, abz = p[a] - p[b], p[a + 1] - p[b + 1], p[a + 2] - p[b + 2]
                cx = cby * abz - cbz * aby
                cy = cbz * abx - cbx * abz
                cz = cbx * aby - cby * abx
                for v in (a, b, c):
                    na[v], na[v + 1], na[v + 2] = cx, cy, cz
        for k in range(0, n, 3):
            x, y, z = na[k], na[k + 1], na[k + 2]
            l = math.sqrt(x * x + y * y + z * z) or 1
            l = 1 / l
            na[k], na[k + 1], na[k + 2] = x * l, y * l, z * l

    def computeBoundingSphere(self):
        pass

    def computeBoundingBox(self):
        pass

    def dispose(self):
        pass

    def vertex_count(self):
        return self.attributes["position"].count


def geometry_from(positions, indices=None, uv=None):
    g = BufferGeometry()
    g.setAttribute("position", BufferAttribute(f32(positions), 3))
    if uv is not None:
        g.setAttribute("uv", BufferAttribute(f32(uv), 2))
    if indices is not None:
        g.setIndex(indices)
    return g


# ---------------------------------------------------------------- Curves

class Curve:
    arcLengthDivisions = 200

    def __init__(self):
        self.arcLengthDivisions = 200
        self.cacheArcLengths = None
        self.needsUpdate = False

    def getPointAt(self, u):
        return self.getPoint(self.getUtoTmapping(u))

    def getPoints(self, divisions=5):
        return [self.getPoint(d / divisions) for d in range(divisions + 1)]

    def getSpacedPoints(self, divisions=5):
        return [self.getPointAt(d / divisions) for d in range(divisions + 1)]

    def getLength(self):
        l = self.getLengths()
        return l[-1]

    def getLengths(self, divisions=None):
        if divisions is None:
            divisions = self.arcLengthDivisions
        if self.cacheArcLengths is not None and len(self.cacheArcLengths) == divisions + 1 and not self.needsUpdate:
            return self.cacheArcLengths
        self.needsUpdate = False
        cache = [0]
        last = self.getPoint(0)
        s = 0
        for p in range(1, divisions + 1):
            cur = self.getPoint(p / divisions)
            s += cur.distanceTo(last)
            cache.append(s)
            last = cur
        self.cacheArcLengths = cache
        return cache

    def getUtoTmapping(self, u, distance=None):
        arc = self.getLengths()
        il = len(arc)
        target = distance if distance else u * arc[il - 1]
        low, high = 0, il - 1
        i = 0
        while low <= high:
            i = int(math.floor(low + (high - low) / 2))
            comp = arc[i] - target
            if comp < 0:
                low = i + 1
            elif comp > 0:
                high = i - 1
            else:
                high = i
                break
        i = high
        if arc[i] == target:
            return i / (il - 1)
        before = arc[i]
        after = arc[i + 1]
        return (i + (target - before) / (after - before)) / (il - 1)

    def getTangent(self, t):
        delta = 0.0001
        t1, t2 = t - delta, t + delta
        if t1 < 0:
            t1 = 0
        if t2 > 1:
            t2 = 1
        p1 = self.getPoint(t1)
        p2 = self.getPoint(t2)
        return p2.clone().sub(p1).normalize()

    def getTangentAt(self, u):
        return self.getTangent(self.getUtoTmapping(u))

    def computeFrenetFrames(self, segments, closed=False):
        normal = Vector3()
        tangents = [self.getTangentAt(i / segments) for i in range(segments + 1)]
        normals = [Vector3()]
        binormals = [Vector3()]
        mn = 1.7976931348623157e308
        tx, ty, tz = abs(tangents[0].x), abs(tangents[0].y), abs(tangents[0].z)
        if tx <= mn:
            mn = tx
            normal.set(1, 0, 0)
        if ty <= mn:
            mn = ty
            normal.set(0, 1, 0)
        if tz <= mn:
            normal.set(0, 0, 1)
        vec = Vector3().crossVectors(tangents[0], normal).normalize()
        normals[0].crossVectors(tangents[0], vec)
        binormals[0].crossVectors(tangents[0], normals[0])
        mat = Matrix4()
        for i in range(1, segments + 1):
            normals.append(normals[i - 1].clone())
            binormals.append(binormals[i - 1].clone())
            vec.crossVectors(tangents[i - 1], tangents[i])
            if vec.length() > EPSILON:
                vec.normalize()
                theta = math.acos(clamp(tangents[i - 1].dot(tangents[i]), -1, 1))
                normals[i].applyMatrix4(mat.makeRotationAxis(vec, theta))
            binormals[i].crossVectors(tangents[i], normals[i])
        if closed:
            theta = math.acos(clamp(normals[0].dot(normals[segments]), -1, 1))
            theta /= segments
            if tangents[0].dot(vec.crossVectors(normals[0], normals[segments])) > 0:
                theta = -theta
            for i in range(1, segments + 1):
                normals[i].applyMatrix4(mat.makeRotationAxis(tangents[i], theta * i))
                binormals[i].crossVectors(tangents[i], normals[i])
        return {"tangents": tangents, "normals": normals, "binormals": binormals}


def _nonuniform(x0, x1, x2, x3, dt0, dt1, dt2):
    t1 = (x1 - x0) / dt0 - (x2 - x0) / (dt0 + dt1) + (x2 - x1) / dt1
    t2 = (x2 - x1) / dt1 - (x3 - x1) / (dt1 + dt2) + (x3 - x2) / dt2
    t1 *= dt1
    t2 *= dt1
    c0 = x1
    c1 = t1
    c2 = -3 * x1 + 3 * x2 - 2 * t1 - t2
    c3 = 2 * x1 - 2 * x2 + t1 + t2
    return c0, c1, c2, c3


class CatmullRomCurve3(Curve):
    def __init__(self, points, closed=False, curveType="centripetal", tension=0.5):
        Curve.__init__(self)
        self.points = points
        self.closed = closed
        self.curveType = curveType
        self.tension = tension

    def getPoint(self, t):
        points = self.points
        l = len(points)
        p = (l - (0 if self.closed else 1)) * t
        intPoint = int(math.floor(p))
        weight = p - intPoint
        if self.closed:
            intPoint += 0 if intPoint > 0 else (int(math.floor(abs(intPoint) / l)) + 1) * l
        elif weight == 0 and intPoint == l - 1:
            intPoint = l - 2
            weight = 1
        if self.closed or intPoint > 0:
            p0 = points[(intPoint - 1) % l]
        else:
            p0 = Vector3().subVectors(points[0], points[1]).add(points[0])
        p1 = points[intPoint % l]
        p2 = points[(intPoint + 1) % l]
        if self.closed or intPoint + 2 < l:
            p3 = points[(intPoint + 2) % l]
        else:
            p3 = Vector3().subVectors(points[l - 1], points[l - 2]).add(points[l - 1])
        pw = 0.5 if self.curveType == "chordal" else 0.25
        dt0 = math.pow(p0.distanceToSquared(p1), pw)
        dt1 = math.pow(p1.distanceToSquared(p2), pw)
        dt2 = math.pow(p2.distanceToSquared(p3), pw)
        if dt1 < 1e-4:
            dt1 = 1.0
        if dt0 < 1e-4:
            dt0 = dt1
        if dt2 < 1e-4:
            dt2 = dt1
        w = weight
        w2 = w * w
        w3 = w2 * w
        out = []
        for a, b, c, d in ((p0.x, p1.x, p2.x, p3.x), (p0.y, p1.y, p2.y, p3.y), (p0.z, p1.z, p2.z, p3.z)):
            c0, c1, c2, c3 = _nonuniform(a, b, c, d, dt0, dt1, dt2)
            out.append(c0 + c1 * w + c2 * w2 + c3 * w3)
        return Vector3(out[0], out[1], out[2])


class LineCurve3(Curve):
    isLineCurve3 = True

    def __init__(self, v1, v2):
        Curve.__init__(self)
        self.v1, self.v2 = v1, v2

    def getPoint(self, t):
        if t == 1:
            return self.v2.clone()
        return self.v2.clone().sub(self.v1).multiplyScalar(t).add(self.v1)

    def getPointAt(self, u):
        return self.getPoint(u)

    def getTangent(self, t):
        return self.v2.clone().sub(self.v1).normalize()

    def getTangentAt(self, u):
        return self.getTangent(u)


def _quadratic_bezier(t, p0, p1, p2):
    k = 1 - t
    return k * k * p0 + 2 * (1 - t) * t * p1 + t * t * p2


class QuadraticBezierCurve3(Curve):
    def __init__(self, v0, v1, v2):
        Curve.__init__(self)
        self.v0, self.v1, self.v2 = v0, v1, v2

    def getPoint(self, t):
        v0, v1, v2 = self.v0, self.v1, self.v2
        return Vector3(_quadratic_bezier(t, v0.x, v1.x, v2.x), _quadratic_bezier(t, v0.y, v1.y, v2.y),
                       _quadratic_bezier(t, v0.z, v1.z, v2.z))


class CurvePath(Curve):
    def __init__(self):
        Curve.__init__(self)
        self.curves = []
        self.autoClose = False
        self.cacheLengths = None

    def add(self, c):
        self.curves.append(c)

    def getPoint(self, t):
        d = t * self.getLength()
        lengths = self.getCurveLengths()
        i = 0
        while i < len(lengths):
            if lengths[i] >= d:
                diff = lengths[i] - d
                curve = self.curves[i]
                seg = curve.getLength()
                u = 0 if seg == 0 else 1 - diff / seg
                return curve.getPointAt(u)
            i += 1
        return None

    def getLength(self):
        l = self.getCurveLengths()
        return l[-1]

    def getCurveLengths(self):
        if self.cacheLengths is not None and len(self.cacheLengths) == len(self.curves):
            return self.cacheLengths
        out = []
        s = 0
        for c in self.curves:
            s += c.getLength()
            out.append(s)
        self.cacheLengths = out
        return out


# ---------------------------------------------------------------- JavaScript の数値演算の再現

def jmod(a, b):
    """JS の % （被除数の符号を保つ）"""
    return math.fmod(a, b)


def jhypot(*values):
    """V8 の Math.hypot（最大値で割ってから Kahan 和）"""
    m = 0.0
    absv = []
    for v in values:
        a = abs(v)
        if a == math.inf:
            return math.inf
        absv.append(a)
        if a > m:
            m = a
    if m == 0:
        return 0.0
    s = 0.0
    comp = 0.0
    for a in absv:
        n = a / m
        summand = n * n - comp
        pre = s + summand
        comp = (pre - s) - summand
        s = pre
    return math.sqrt(s) * m


def jsign(x):
    return 1 if x > 0 else -1 if x < 0 else 0


def js_str(v):
    """JS の String(number) / 配列の join"""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (list, tuple)):
        return ",".join(js_str(x) for x in v)
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, int):
        return str(v)
    if v != v:
        return "NaN"
    if v == int(v) and abs(v) < 1e21:
        return str(int(v))
    r = repr(float(v))
    if "e" in r:
        mant, ex = r.split("e")
        exn = int(ex)
        if -7 < exn < 21:
            from decimal import Decimal
            return format(Decimal(r), "f")
        return mant.rstrip("0").rstrip(".") + "e" + ("+" if exn > 0 else "-") + str(abs(exn))
    return r


def to_fixed(x, digits):
    """Number.prototype.toFixed（ちょうど中間は大きい方へ。負の値は "-" を付ける）"""
    from decimal import Decimal, ROUND_HALF_UP
    x = float(x)
    neg = x < 0
    q = Decimal(1).scaleb(-digits)
    s = format(Decimal(abs(x)).quantize(q, rounding=ROUND_HALF_UP), "f")
    return "-" + s if neg else s

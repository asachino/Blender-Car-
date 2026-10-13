bl_info = {
    "name": "Car Physics Baker",
    "author": "Claude",
    "version": (1, 8, 0),
    "blender": (4, 0, 0),
    "location": "3Dビュー > サイドバー(N) > Car Physics",
    "description": "クルマを物理シミュレーションで走らせ、キーフレームに焼き込む",
    "category": "Animation",
}

import math

G = 9.81
V_EPS = 1.0          # 低速時のスリップ角計算用
MAX_DT = 0.002       # 物理のサブステップ上限(秒)


def _clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


def _wrap(a):
    return (a + math.pi) % (2.0 * math.pi) - math.pi


def _ssign(v, w=0.3):
    return v / math.sqrt(v * v + w * w)


def _rot_zyx(yaw, pitch, roll):
    """R = Rz(yaw) @ Ry(pitch) @ Rx(roll) を 3x3 リストで返す"""
    cz, sz = math.cos(yaw), math.sin(yaw)
    cy, sy = math.cos(pitch), math.sin(pitch)
    cx, sx = math.cos(roll), math.sin(roll)
    return [
        [cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx],
        [sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx],
        [-sy, cy * sx, cy * cx],
    ]


def _mul(R, v):
    return (R[0][0] * v[0] + R[0][1] * v[1] + R[0][2] * v[2],
            R[1][0] * v[0] + R[1][1] * v[1] + R[1][2] * v[2],
            R[2][0] * v[0] + R[2][1] * v[1] + R[2][2] * v[2])


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _mulT(R, v):
    return (R[0][0] * v[0] + R[1][0] * v[1] + R[2][0] * v[2],
            R[0][1] * v[0] + R[1][1] * v[1] + R[2][1] * v[2],
            R[0][2] * v[0] + R[1][2] * v[1] + R[2][2] * v[2])


def _q_from_R(R):
    tr = R[0][0] + R[1][1] + R[2][2]
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        return [0.25 * s, (R[2][1] - R[1][2]) / s, (R[0][2] - R[2][0]) / s, (R[1][0] - R[0][1]) / s]
    if R[0][0] > R[1][1] and R[0][0] > R[2][2]:
        s = math.sqrt(1.0 + R[0][0] - R[1][1] - R[2][2]) * 2
        return [(R[2][1] - R[1][2]) / s, 0.25 * s, (R[0][1] + R[1][0]) / s, (R[0][2] + R[2][0]) / s]
    if R[1][1] > R[2][2]:
        s = math.sqrt(1.0 + R[1][1] - R[0][0] - R[2][2]) * 2
        return [(R[0][2] - R[2][0]) / s, (R[0][1] + R[1][0]) / s, 0.25 * s, (R[1][2] + R[2][1]) / s]
    s = math.sqrt(1.0 + R[2][2] - R[0][0] - R[1][1]) * 2
    return [(R[1][0] - R[0][1]) / s, (R[0][2] + R[2][0]) / s, (R[1][2] + R[2][1]) / s, 0.25 * s]


def _R_from_q(q):
    w, x, y, z = q
    return [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]


def _road(x, y, amp):
    """路面の細かい凹凸（決定的なので何度焼いても同じ結果）"""
    return amp * (0.5 * math.sin(2.1 * x + 0.7) * math.cos(1.7 * y + 0.3)
                  + 0.3 * math.sin(4.3 * x - 3.1 * y + 1.3)
                  + 0.2 * math.sin(5.3 * x + 7.9 * y + 0.5))


def _friction(Fx, Fy, Fmax, assist):
    """摩擦円。アシスト有りは横グリップを優先して駆動/制動を絞る（TCS/ABS）、
    無しは駆動/制動が優先され、ホイールスピンやロックで横グリップが抜ける"""
    if assist:
        Fy = _clamp(Fy, -Fmax, Fmax)
        lim = max(math.sqrt(max(Fmax * Fmax - Fy * Fy, 0.0)) * 0.9, 0.1 * Fmax)
        Fx = _clamp(Fx, -lim, lim)
        lim = math.sqrt(max(Fmax * Fmax - Fx * Fx, 0.0))
        return Fx, _clamp(Fy, -lim, lim)
    Fx = _clamp(Fx, -Fmax, Fmax)
    lim = math.sqrt(max(Fmax * Fmax - Fx * Fx, 0.0))
    return Fx, _clamp(Fy, -lim, lim)


_TIRE_U = (-0.8, -0.45, 0.0, 0.45, 0.8)


def _tire_height(fn, wx, wy, fx, fy, r):
    """タイヤの接地高さ。中心の真下だけでなく前後も調べ、円が地面に触れる高さにする（段差の角に乗り上げる）"""
    best = None
    for u in _TIRE_U:
        d = u * r
        hz = fn(wx + fx * d, wy + fy * d)
        if hz is None:
            continue
        hz -= r - math.sqrt(r * r - d * d)
        if best is None or hz > best:
            best = hz
    return best


def _under_points(P, wheels, radii, cgx, cgy, n_max=14):
    """車体の底の点（重心基準の車体座標。z は車体座標のまま）。タイヤの近くの点は除く"""
    rmin = min(radii)
    if P.body_points:
        pts = list(P.body_points)
        z0 = min(q[2] for q in pts)
        z1 = max(q[2] for q in pts)
        low = [q for q in pts if q[2] <= z0 + 0.25 * (z1 - z0)]
    else:
        xs = [w[0] for w in wheels]
        ys = [w[1] for w in wheels]
        z = min(w[2] for w in wheels) - rmin + 0.12
        low = [(x, y, z) for x in (min(xs) - 1.1 * rmin, (min(xs) + max(xs)) / 2, max(xs) + 1.1 * rmin)
               for y in (min(ys), (min(ys) + max(ys)) / 2, max(ys))]
    low = [q for q in low if all((q[0] - w[0]) ** 2 + (q[1] - w[1]) ** 2 > (1.2 * r) ** 2
                                 for w, r in zip(wheels, radii))]
    if not low:
        return None
    sel = [min(low, key=lambda q: q[2])]
    while len(sel) < min(n_max, len(low)):
        sel.append(max(low, key=lambda q: min((q[0] - s_[0]) ** 2 + (q[1] - s_[1]) ** 2 for s_ in sel)))
    return [(x - cgx, y - cgy, z) for (x, y, z) in sel]


def _lift_body(pts, yaw, zc, th, ph, zv, thv, phv):
    """pts: [(qx, qy, qz, 下限の高さ)]。いちばん深く沈んだ点から、上下・ピッチ・ロールを最小限動かして押し上げ、
    沈む向きの速度を消す（段差で車体やタイヤが地面にめり込まないように）"""
    eps = 1e-4
    for _ in range(4):
        R = _rot_zyx(yaw, th, ph)
        worst, pick = 1e-4, None
        for (qx, qy, qz, gz) in pts:
            z = zc + _mul(R, (qx, qy, qz))[2]
            if gz - z > worst:
                worst, pick = gz - z, ((qx, qy, qz), z)
        if pick is None:
            break
        q, z = pick
        j1 = (zc + _mul(_rot_zyx(yaw, th + eps, ph), q)[2] - z) / eps
        j2 = (zc + _mul(_rot_zyx(yaw, th, ph + eps), q)[2] - z) / eps
        nn = 1.0 + j1 * j1 + j2 * j2
        c = worst / nn
        zc += c
        th += c * j1
        ph += c * j2
        vn = zv + j1 * thv + j2 * phv
        if vn < 0.0:
            c = vn / nn
            zv -= c
            thv -= c * j1
            phv -= c * j2
    return zc, th, ph, zv, thv, phv


def car_geometry(wheels, front_weight):
    """wheels: [FL, FR, RL, RR] の車体座標 (x前, y左, z上)"""
    xf = (wheels[0][0] + wheels[1][0]) * 0.5
    xr = (wheels[2][0] + wheels[3][0]) * 0.5
    L = xf - xr
    if L <= 0.1:
        raise ValueError("ホイールベースが不正です（前輪/後輪の割り当てや「車の正面」の設定を確認）")
    b = front_weight * L          # 重心〜後軸
    return {
        "L": L, "a": L - b, "b": b,
        "cgx": xr + b, "cgy": sum(w[1] for w in wheels) / 4.0,
        "track_f": abs(wheels[0][1] - wheels[1][1]),
        "track": (abs(wheels[0][1] - wheels[1][1]) + abs(wheels[2][1] - wheels[3][1])) * 0.5,
    }


# ---------------------------------------------------------------------------
# コース
# ---------------------------------------------------------------------------

class Path:
    def __init__(self, pts, ds=0.5, cyclic=False, laps=1):
        if cyclic:
            pts = list(pts) + [pts[0]]
        pts = self._resample(pts, ds)
        if cyclic and laps > 1:
            base = pts[:-1]
            pts = base * laps + [base[0]]
        self.x = [p[0] for p in pts]
        self.y = [p[1] for p in pts]
        self.z = [p[2] for p in pts]
        self.n = len(pts)
        self.total = (self.n - 1) * self.ds

        n = self.n
        hd = [math.atan2(self.y[i + 1] - self.y[i], self.x[i + 1] - self.x[i]) for i in range(n - 1)]
        self.heading0 = hd[0]
        k = [0.0] * n
        for i in range(1, n - 1):
            k[i] = _wrap(hd[i] - hd[i - 1]) / self.ds
        k[0], k[-1] = k[1] if n > 2 else 0.0, k[-2] if n > 2 else 0.0
        w = max(1, int(3.0 / self.ds))
        self.kappa = []
        for i in range(n):
            a, b = max(0, i - w), min(n, i + w + 1)
            self.kappa.append(sum(k[a:b]) / (b - a))
        self.v = [0.0] * n

    def _resample(self, pts, ds):
        clean = [pts[0]]
        for p in pts[1:]:
            if math.hypot(p[0] - clean[-1][0], p[1] - clean[-1][1]) > 1e-6:
                clean.append(p)
        if len(clean) < 2:
            raise ValueError("コースが短すぎます")
        cum = [0.0]
        for i in range(1, len(clean)):
            cum.append(cum[-1] + math.hypot(clean[i][0] - clean[i - 1][0], clean[i][1] - clean[i - 1][1]))
        total = cum[-1]
        n = max(2, int(total / ds) + 1)
        self.ds = total / (n - 1)
        out, j = [], 0
        for k in range(n):
            s = self.ds * k
            while j < len(cum) - 2 and cum[j + 1] < s:
                j += 1
            seg = cum[j + 1] - cum[j]
            t = 0.0 if seg < 1e-9 else _clamp((s - cum[j]) / seg, 0.0, 1.0)
            p, q = clean[j], clean[j + 1]
            out.append(tuple(p[c] + (q[c] - p[c]) * t for c in range(3)))
        return out

    def interp(self, arr, s):
        s = _clamp(s, 0.0, self.total)
        f = s / self.ds
        i = min(int(f), self.n - 2)
        t = f - i
        return arr[i] + (arr[i + 1] - arr[i]) * t

    def project(self, x, y, hint=None):
        if hint is None:
            lo, hi = 0, self.n - 1
        else:
            lo, hi = max(0, hint - 40), min(self.n - 1, hint + 160)
        best, bi, bt = 1e30, lo, 0.0
        for i in range(lo, hi):
            ax, ay = self.x[i], self.y[i]
            dx, dy = self.x[i + 1] - ax, self.y[i + 1] - ay
            L2 = dx * dx + dy * dy
            t = 0.0 if L2 < 1e-12 else _clamp(((x - ax) * dx + (y - ay) * dy) / L2, 0.0, 1.0)
            ex, ey = ax + dx * t - x, ay + dy * t - y
            d = ex * ex + ey * ey
            if d < best:
                best, bi, bt = d, i, t
        return bi, (bi + bt) * self.ds, math.sqrt(best)

    def signed_offset(self, x, y, hint=None):
        """コースからの横ずれ（左が正）"""
        i, s, d = self.project(x, y, hint)
        tx, ty = self.x[i + 1] - self.x[i], self.y[i + 1] - self.y[i]
        tl = math.hypot(tx, ty) or 1.0
        cr = (tx * (y - self.y[i]) - ty * (x - self.x[i])) / tl
        return i, s, math.copysign(d, cr)

    def left_normal(self, s):
        x0, y0 = self.interp(self.x, s - 0.5), self.interp(self.y, s - 0.5)
        x1, y1 = self.interp(self.x, s + 0.5), self.interp(self.y, s + 0.5)
        tx, ty = x1 - x0, y1 - y0
        tl = math.hypot(tx, ty) or 1.0
        return -ty / tl, tx / tl

    def build_speed_profile(self, v_max, a_lat, a_acc, a_brk, v0, stop_at_end):
        self.v = self.speed_profile(v_max, a_lat, a_acc, a_brk, v0, stop_at_end)

    def speed_profile(self, v_max, a_lat, a_acc, a_brk, v0, stop_at_end, grip=None):
        if grip is None:
            v = [min(v_max, math.sqrt(a_lat / max(abs(k), 1e-6))) for k in self.kappa]
        else:
            v = [min(v_max, math.sqrt(a_lat * g / max(abs(k), 1e-6)), v_max * (0.35 + 0.65 * g))
                 for k, g in zip(self.kappa, grip)]
            a_brk_l = [a_brk * max(g, 0.1) for g in grip]
        v[0] = min(v[0], max(v0, 0.0))
        for i in range(1, self.n):
            v[i] = min(v[i], math.sqrt(v[i - 1] ** 2 + 2.0 * a_acc * self.ds))
        if stop_at_end:
            v[-1] = 0.0
        for i in range(self.n - 2, -1, -1):
            ab = a_brk if grip is None else a_brk_l[i]
            v[i] = min(v[i], math.sqrt(v[i + 1] ** 2 + 2.0 * ab * self.ds))
        return v


# ---------------------------------------------------------------------------
# 車両シミュレーション
#   水平: 2輪モデル＋タイヤ摩擦円（荷重はサスのバネ力から）
#   垂直: 車体のヒーブ/ピッチ/ロールを4輪のバネ・ダンパーで支える剛体（ジャンプ可）
# ---------------------------------------------------------------------------

class Params:
    manual = False                   # True=キー入力で運転, False=コースを自動走行
    assist = True                    # トラクションコントロール/ABS/横滑り防止
    mass = 1400.0
    front_weight = 0.55
    cg_height = 0.5
    mu = 1.0
    drive_rear_bias = 1.0            # 1=FR, 0=FF, 0.6=4WD
    brake_front_bias = 0.65
    top_speed = 100 / 3.6
    start_speed = 0.0
    start_frame = 0                  # 0始まり。これより前は停車
    stop_at_end = True
    corner_use = 0.75                # グリップのうち計画で使う割合
    accel = 4.0
    brake = 7.0
    max_steer = math.radians(35)
    steer_rate = math.radians(400)
    look_min = 3.0
    look_time = 0.6
    launch_time = 0.0                # スタートで後輪が空転する時間（秒、0=なし）
    launch_slip = 12.0               # 空転の強さ（タイヤ表面の滑り速度 m/s）
    launch_lift = 2.0                # 空転中に前が浮く強さ（ピッチの倍率）
    line_hold = 0.0                  # ライン追従の補正（0=なし）: 高速コーナーのアンダーで外へふくらむのを打ち消す
    start_xy = None                  # None ならコース始点
    start_yaw = None
    flat_z = 0.0                     # 地面もコースも無いときの地面高さ
    road_noise = 0.0
    # サスペンション
    susp_freq = 1.5
    susp_damp = 0.5
    pitch_mult = 1.0                 # 1.0 = 実車相当
    roll_mult = 1.0
    travel = 0.12
    # ドリフト（コース自動走行時のみ）
    drift = False
    drift_angle = math.radians(30)
    drift_r_start = 60.0
    drift_r_full = 20.0
    drift_freq = 0.8
    drift_damp = 0.4
    drift_min_speed = 8.0
    drift_frames = None              # (start, end) 0始まり or None=全区間
    countersteer = 1.0
    # スピン
    spin = False
    spin_frame = 0
    spin_dir = 0                     # 0=自動, 1=左, -1=右
    spin_kick = math.radians(90)
    spin_grip = 0.6
    # 横転（剛体モード）
    rollover = False
    rollover_frame = 0
    rollover_dir = 0                 # 0=自動, 1=右へ転がる, -1=左へ転がる
    rollover_rate = math.radians(250)
    rollover_lift = 2.5
    rollover_slide = 0.5             # 速度のうち横滑りに変える割合
    rollover_auto = True             # 傾き過ぎたら自動で横転に移行
    body_mu = 0.55                   # 車体と地面の摩擦
    body_box = None                  # 車体の外形 (xmin, xmax, ymin, ymax, zmin, zmax) 車体座標
    body_points = None               # 車体メッシュの外周点（車体座標）。あれば外形より優先


# 拡張機能（既定はすべてオフ＝従来と同じ計算）
Params.grip_fn = None                # (x, y) -> グリップ倍率（場所ごとの路面）
Params.gears = False                 # ギアとエンジン回転数
Params.gear_count = 6
Params.shift_rpm = 6200.0
Params.idle_rpm = 850.0
Params.redline_rpm = 7000.0
Params.shift_time = 0.25
Params.gear_spread = 3.5             # 1速と最高速ギアの比
Params.reverse_top = 20 / 3.6        # バックの最高速度
Params.speed_zones = None            # [(s0, s1, 倍率)] 到達タイミング用
Params.wall_fn = None                # (x, y, z) -> (めり込み, nx, ny, nz) or None
Params.wall_near = None              # (x, y, z, 半径) -> bool
Params.wall_mu = 0.4
Params.lane_offset = 0.0             # コースから横にずらして走る（左が正）
Params.others = None                 # 他の車の軌跡 [[(x, y), ...], ...]
Params.follow_gap = 1.2              # 前の車との車間（秒）
Params.overtake = False
Params.overtake_offset = 3.2
Params.record_impacts = False        # へこみ用に衝撃を記録
Params.grip_plan = True              # 場所ごとの路面: 滑る場所を見越して減速する
Params.barrier = None                # タイヤバリヤ [(x, y, 半径, z下, z上, nx, ny)]  n=トラック側を向く単位ベクトル（不明なら 0, 0）
Params.barrier_stiff = 1.0           # バリヤの固さ（倍率）
Params.tire_profile = True           # タイヤの丸みで段差を拾う（中心の真下だけでなく前後も見る）
Params.body_contact = True           # 車体の底とタイヤが地面にめり込まないようにする
Params.rollover_settle = True        # 横転の後、ほぼ止まったら完全に止める（揺れ続け・じわじわ滑り続けない）
Params.collide_with = None           # ぶつかる相手の車 [{"traj": [(x, y, yaw)...], "box": (x0, x1, y0, y1)}]  車体座標の箱
Params.no_avoid = False              # True なら前の車を避けない（ぶつかる）


def zone_scale(zones, s):
    for s0, s1, k in zones:
        if s0 <= s < s1:
            return k
    return zones[-1][2] if zones else 1.0


ROLL_LIMIT = math.radians(25)
PITCH_LIMIT = math.radians(35)


def simulate(path, P, wheels, radii, n_frames, fps, height_fn=None, inputs=None, progress=None):
    """
    path     : Path（手動運転なら None 可）
    wheels   : [FL, FR, RL, RR] の車体座標 (x前, y左, z上) の位置
    radii    : 各タイヤ半径
    height_fn: (x, y) -> z or None
    inputs   : f -> dict(speed_scale, handbrake, steer, throttle, brake)  キーフレーム入力
    戻り値   : (フレームごとの dict のリスト, 情報 dict)
    """
    m = P.mass
    geo = car_geometry(wheels, P.front_weight)
    L, a, b = geo["L"], geo["a"], geo["b"]
    cgx, cgy = geo["cgx"], geo["cgy"]
    track_f, track = geo["track_f"], geo["track"]
    qs = [(w[0] - cgx, w[1] - cgy, w[2]) for w in wheels]
    Iz = m * a * b * 1.1
    Iy = m * a * b
    Ix = 0.5 * m * max(track * 0.5, 0.3) ** 2
    h = P.cg_height
    manual = P.manual or path is None
    if inputs is None:
        inputs = lambda f: {}

    # サスペンション: 各輪のバネ定数を「車体の固有振動数」から決める
    ws = 2.0 * math.pi * P.susp_freq
    s0 = G / (ws * ws)                       # 静止時の沈み込み
    droop = min(0.95 * s0, P.travel)         # 伸び側ストローク
    kc = [m * P.front_weight * 0.5 * ws * ws] * 2 + [m * (1.0 - P.front_weight) * 0.5 * ws * ws] * 2
    cc = [2.0 * P.susp_damp * k / ws for k in kc]

    # ---- 横転用の剛体モデル ----
    zcg = sum(w[2] for w in wheels) / 4.0 - sum(radii) / 4.0 + h
    cgl = (cgx, cgy, zcg)
    if P.body_box is not None:
        bx0, bx1, by0, by1, bz0, bz1 = P.body_box
    else:
        rmax = max(radii)
        bx0 = min(w[0] for w in wheels) - rmax - 0.3
        bx1 = max(w[0] for w in wheels) + rmax + 0.3
        by0 = min(w[1] for w in wheels) - 0.15
        by1 = max(w[1] for w in wheels) + 0.15
        bz0 = min(w[2] for w in wheels)
        bz1 = bz0 + 1.1
    # 車体の接地点: 断面は「下が広く屋根が狭い」六角形（箱より転がりやすい実車に近い形）
    rb_pts = []                      # (x, y, z, タイヤ番号 or -1)  重心からの相対位置
    bl = bx1 - bx0
    zb = bz0 + 0.45 * (bz1 - bz0)    # ベルトライン（ドアの上端あたり）
    inset = 0.22 * (by1 - by0)
    for x in (bx0, (bx0 + bx1) * 0.5, bx1):
        for y in (by0, by1):
            rb_pts.append((x - cgx, y - cgy, bz0 - zcg, -1))
            rb_pts.append((x - cgx, y - cgy, zb - zcg, -1))
    for x in (bx0 + 0.28 * bl, bx1 - 0.32 * bl):
        for y in (by0 + inset, by1 - inset):
            rb_pts.append((x - cgx, y - cgy, bz1 - zcg, -1))
    if P.body_points:
        rb_pts = [(x - cgx, y - cgy, z - zcg, -1) for (x, y, z) in P.body_points]
    for i, w in enumerate(wheels):
        for k in range(8):
            an = 2.0 * math.pi * k / 8
            rb_pts.append((w[0] + radii[i] * math.sin(an) - cgx, w[1] - cgy,
                           w[2] - radii[i] * math.cos(an) - zcg, i))
    k_ct = m * G / (4 * 0.02)
    c_ct = 2.0 * 0.6 * math.sqrt(k_ct * m / 4)
    Ib = (max(Ix, m * (track ** 2 + 1.3 ** 2) / 12.0), Iy, Iz)
    rb = {"on": False, "nc": 0}
    last_g = [None]

    # 拡張: 壁・衝撃・ギア・他車
    # 壁との当たり: 車体の外形（真上から見た輪郭）を、2つの高さの輪で調べる
    _bp = [(x_, y_, z_) for (x_, y_, z_, wi_) in rb_pts if wi_ < 0]
    _z0, _z1 = (min(p_[2] for p_ in _bp), max(p_[2] for p_ in _bp)) if _bp else (0.0, 1.0)
    _xy = sorted({(round(p_[0], 3), round(p_[1], 3)) for p_ in _bp})
    wall_pts = [(x_, y_, _z0 + k_ * (_z1 - _z0)) for k_ in (0.25, 0.6) for (x_, y_) in _xy]
    wall_r = max(math.sqrt(x_ * x_ + y_ * y_) for (x_, y_, z_) in wall_pts) + 0.5 if wall_pts else 3.0
    k_w = m * 300.0
    c_w = 2.0 * 0.5 * math.sqrt(k_w * m)
    impacts = []                     # (フレーム, 車体座標の点, 衝撃量, 車体座標の法線)
    imp_frame = {}
    gear = 0
    shift_t = 0.0
    rpm = P.idle_rpm
    if P.gears:
        k_rpm = 60.0 / (2.0 * math.pi * (sum(radii) / 4.0))
        ratio_top = P.redline_rpm * 0.95 / (max(P.top_speed, 1.0) * k_rpm)
        nq = max(P.gear_count, 1)
        qg = P.gear_spread ** (1.0 / max(nq - 1, 1))
        ratios = [ratio_top * qg ** (nq - 1 - i) for i in range(nq)]
    oth_hint = [None] * len(P.others) if P.others else []
    ovt_off = 0.0
    ovt_target = 0.0
    ovt = {"k": None, "t": 0.0}
    v_hi = None

    # ---- タイヤバリヤ: タイヤの列をクッションとして扱う ----
    bar_grid = {}
    bar_box = None
    if P.barrier:
        for bi, tb in enumerate(P.barrier):
            key = (int(math.floor(tb[0] / 2.0)), int(math.floor(tb[1] / 2.0)))
            bar_grid.setdefault(key, []).append(bi)
        xs_ = [tb[0] for tb in P.barrier]
        ys_ = [tb[1] for tb in P.barrier]
        rr_ = max(tb[2] for tb in P.barrier) + wall_r + 1.0
        bar_box = (min(xs_) - rr_, max(xs_) + rr_, min(ys_) - rr_, max(ys_) + rr_)
    bar_coarse = set()
    if P.barrier:
        rr_c = wall_r + max(tb[2] for tb in P.barrier) + 1.0
        for tb in P.barrier:
            for gx in range(int(math.floor((tb[0] - rr_c) / 8.0)), int(math.floor((tb[0] + rr_c) / 8.0)) + 1):
                for gy in range(int(math.floor((tb[1] - rr_c) / 8.0)), int(math.floor((tb[1] + rr_c) / 8.0)) + 1):
                    bar_coarse.add((gx, gy))

    def bar_near(x, y):
        """車の近く（8 m 区画）にバリヤがあるか。無ければ細かい判定を省く"""
        return (int(math.floor(x / 8.0)), int(math.floor(y / 8.0))) in bar_coarse

    k_b = m * 60.0 * P.barrier_stiff
    c_b = 2.0 * 0.9 * math.sqrt(k_b * m)

    def barrier_force(d, vn):
        """押し込むときは強く、戻るときはほとんど押し返さない（タイヤが衝撃を吸収する）"""
        if vn < 0.0:
            return k_b * d * (1.0 + 3.0 * d) - c_b * vn
        return 0.1 * k_b * d * (1.0 + 3.0 * d)

    def barrier_hit(pts_w):
        """pts_w: [(x, y, z, vx, vy, 点のid)]  一番深く入り込んだ点の (深さ, nx, ny, 点) を返す"""
        best = None
        for (wx, wy, wz, vpx, vpy, pid) in pts_w:
            cx0, cy0 = int(math.floor(wx / 2.0)), int(math.floor(wy / 2.0))
            for gx in (cx0 - 1, cx0, cx0 + 1):
                for gy in (cy0 - 1, cy0, cy0 + 1):
                    for bi in bar_grid.get((gx, gy), ()):
                        bx, by, br, bz0, bz1, nx, ny = P.barrier[bi]
                        if not (bz0 - 0.05 <= wz <= bz1 + 0.05):
                            continue
                        dx, dy = wx - bx, wy - by
                        if nx == 0.0 and ny == 0.0:
                            sp = math.hypot(vpx, vpy)
                            if sp < 0.1:
                                continue
                            nx, ny = -vpx / sp, -vpy / sp
                        # 列の横幅の中にいて、タイヤの前面より奥にいれば接触
                        lat = abs(-ny * dx + nx * dy)
                        along = dx * nx + dy * ny
                        if lat > br or along > br:
                            continue
                        d = br - along             # タイヤ前面からの深さ（奥へ行くほど深い）
                        if best is None or d > best[0]:
                            best = (d, nx, ny, pid)
        return best

    # ---- 車同士の衝突 ----
    k_cc = m * 200.0
    c_cc = 2.0 * 0.5 * math.sqrt(k_cc * m)

    def other_pose(o, ft):
        tr = o["traj"]
        i0 = int(math.floor(ft))
        i0 = min(max(i0, 0), len(tr) - 1)
        i1 = min(i0 + 1, len(tr) - 1)
        u = ft - math.floor(ft) if i1 > i0 else 0.0
        a0, a1 = tr[i0], tr[i1]
        yaw = a0[2] + _wrap(a1[2] - a0[2]) * u
        x, y = a0[0] + (a1[0] - a0[0]) * u, a0[1] + (a1[1] - a0[1]) * u
        vx_, vy_ = (a1[0] - a0[0]) * fps, (a1[1] - a0[1]) * fps
        w_ = _wrap(a1[2] - a0[2]) * fps
        return x, y, yaw, vx_, vy_, w_

    def car_contacts(ft, pts_w):
        """pts_w: [(x, y, vx, vy, id)] → 一番深い (深さ, nx, ny, 点id, 相手の点速度) """
        best = None
        for o in P.collide_with:
            ox, oy, oyaw, ovx, ovy, ow = other_pose(o, ft)
            if abs(ox - pts_w[0][0]) > 12.0 or abs(oy - pts_w[0][1]) > 12.0:
                continue
            x0, x1, y0, y1 = o["box"]
            c_, s_ = math.cos(oyaw), math.sin(oyaw)
            for (wx, wy, vpx, vpy, pid) in pts_w:
                dx, dy = wx - ox, wy - oy
                lx, ly = c_ * dx + s_ * dy, -s_ * dx + c_ * dy
                if not (x0 < lx < x1 and y0 < ly < y1):
                    continue
                pen = ((lx - x0, -1.0, 0.0), (x1 - lx, 1.0, 0.0), (ly - y0, 0.0, -1.0), (y1 - ly, 0.0, 1.0))
                d, nlx, nly = min(pen)
                nx, ny = c_ * nlx - s_ * nly, s_ * nlx + c_ * nly
                ovpx, ovpy = ovx - ow * dy, ovy + ow * dx
                if best is None or d > best[0]:
                    best = (d, nx, ny, pid, ovpx, ovpy)
        return best

    def note_impact(key, point, imp, normal):
        old = imp_frame.get(key)
        imp_frame[key] = (point, imp + (old[1] if old else 0.0), normal)

    def wall_force(wx, wy, wz, vpx, vpy, vpz, flat=False):
        hit = P.wall_fn(wx, wy, wz)
        if hit is None:
            return None
        d, nx, ny, nz = hit
        if flat:                      # 通常走行: 壁は横から押すだけ
            if abs(nz) > 0.6:
                return None
            hl = math.hypot(nx, ny)
            nx, ny, nz = nx / hl, ny / hl, 0.0
        vn = vpx * nx + vpy * ny + vpz * nz
        Fn = k_w * d - c_w * vn
        if Fn <= 0.0:
            return None
        tx_, ty_, tz_ = vpx - vn * nx, vpy - vn * ny, vpz - vn * nz
        tl_ = math.sqrt(tx_ * tx_ + ty_ * ty_ + tz_ * tz_ + 0.09)
        mu_ = P.wall_mu * Fn / tl_
        return (Fn * nx - mu_ * tx_, Fn * ny - mu_ * ty_, Fn * nz - mu_ * tz_, (nx, ny, nz))

    def gnd(x, y, s_):
        if height_fn is not None:
            hz = height_fn(x, y)
            if hz is None:
                hz = last_g[0] if last_g[0] is not None else base_z
            last_g[0] = hz
        else:
            hz = path.interp(path.z, s_) if path is not None else P.flat_z
        if P.road_noise > 0.0:
            hz += _road(x, y, P.road_noise)
        return hz

    if not manual:
        if P.grip_fn is not None and P.grip_plan:
            gl_ = [P.grip_fn(x_, y_) for x_, y_ in zip(path.x, path.y)]
            gl_ = [min(gl_[max(0, i - 6):i + 7]) for i in range(len(gl_))]
            path.v = path.speed_profile(P.top_speed, P.mu * G * P.corner_use, P.accel * 0.8,
                                        P.brake * 0.7, P.start_speed, P.stop_at_end, gl_)
        else:
            path.build_speed_profile(P.top_speed, P.mu * G * P.corner_use,
                                     P.accel * 0.8, P.brake * 0.7, P.start_speed, P.stop_at_end)

    dtf = 1.0 / fps
    sub = max(1, int(math.ceil(dtf / MAX_DT)))
    dt = dtf / sub

    if P.start_xy is not None:
        px, py = P.start_xy
    else:
        px, py = path.x[0], path.y[0]
    psi = P.start_yaw if P.start_yaw is not None else path.heading0
    vx, vy, r = (P.start_speed if P.start_frame <= 0 else 0.0), 0.0, 0.0
    delta = 0.0
    beta = beta_v = 0.0
    zc = zv = th = thv = ph = phv = 0.0
    spin_f = spin_r = 0.0
    hint = None
    s = 0.0
    lh_int = 0.0
    spinning = False
    spin_sign = 1
    base_z = path.z[0] if path is not None else P.flat_z
    last_h = [base_z] * 4
    dz_prev = [0.0] * 4
    out = []
    max_err = 0.0
    finished = False
    air_frames = 0
    w_d = 2 * math.pi * P.drift_freq

    under = _under_points(P, wheels, radii, cgx, cgy) if P.body_contact else None

    def heights(px, py, psi_v, s):
        cz, sz = math.cos(psi_v), math.sin(psi_v)
        hs = []
        for i, q in enumerate(qs):
            wx, wy = px + cz * q[0] - sz * q[1], py + sz * q[0] + cz * q[1]
            if height_fn is not None:
                hz = _tire_height(height_fn, wx, wy, cz, sz, radii[i]) if P.tire_profile else height_fn(wx, wy)
                if hz is None:
                    hz = last_h[i]
            else:
                hz = path.interp(path.z, s) if path is not None else P.flat_z
            last_h[i] = hz
            if P.road_noise > 0.0:
                hz += _road(wx, wy, P.road_noise)
            hs.append(hz)
        return hs

    def terrain_angles(hs):
        th_t = -math.atan2((hs[0] + hs[1] - hs[2] - hs[3]) * 0.5, L)
        ph_t = math.atan2((hs[0] + hs[2] - hs[1] - hs[3]) * 0.5, max(track, 0.1))
        return th_t, ph_t

    def enter_rigid(kick_dir):
        R = _rot_zyx(psi + beta, th, ph)
        rc = _mul(R, (cgx, cgy, 0.0))
        org = (px - rc[0], py - rc[1], zc - rc[2])
        gl = _mul(R, cgl)
        c, sn = math.cos(psi), math.sin(psi)
        rb["p"] = [org[i] + gl[i] for i in range(3)]
        rb["v"] = [c * vx - sn * vy, sn * vx + c * vy, zv]
        rb["w"] = list(_mul(R, (phv, thv, r)))
        rb["q"] = _q_from_R(R)
        if kick_dir:
            fwd = (R[0][0], R[1][0], R[2][0])
            for i in range(3):
                rb["w"][i] += kick_dir * P.rollover_rate * fwd[i]
            rb["v"][2] += P.rollover_lift
            # 転がる側へ横滑りさせる（縁石に引っかかるような状況）
            v = rb["v"]
            sp = math.hypot(v[0], v[1])
            right = (-R[0][1], -R[1][1])         # 車体右方向（水平）
            rl = math.hypot(*right)
            if rl > 1e-6 and P.rollover_slide > 0:
                fwd2 = (v[0] / sp, v[1] / sp) if sp > 0.1 else (R[0][0], R[1][0])
                sl = _clamp(P.rollover_slide, 0.0, 1.0)
                lat = (kick_dir * right[0] / rl, kick_dir * right[1] / rl)
                nx = fwd2[0] * math.sqrt(1 - sl * sl) + lat[0] * sl
                ny = fwd2[1] * math.sqrt(1 - sl * sl) + lat[1] * sl
                v[0], v[1] = nx * sp, ny * sp
        rb["on"] = True

    def rigid_step(dt, s_):
        if rb.get("sleep"):
            return
        q = rb["q"]
        R = _R_from_q(q)
        p, v, w = rb["p"], rb["v"], rb["w"]
        F = [0.0, 0.0, -m * G]
        T = [0.0, 0.0, 0.0]
        upright = R[2][2] > 0.5
        fx, fy = R[0][0], R[1][0]
        fl = math.hypot(fx, fy)
        if fl > 1e-6:
            fx, fy = fx / fl, fy / fl
        h0 = gnd(p[0], p[1], s_)
        nc = 0
        for (qx, qy, qz, wi) in rb_pts:
            rw = _mul(R, (qx, qy, qz))
            pz = p[2] + rw[2]
            if pz > h0 + 2.5:
                continue
            gz = gnd(p[0] + rw[0], p[1] + rw[1], s_)
            d = gz - pz
            if d <= 0.0:
                continue
            vp = _cross(w, rw)
            vpx, vpy, vpz = v[0] + vp[0], v[1] + vp[1], v[2] + vp[2]
            Fn = k_ct * d - c_ct * vpz
            if Fn <= 0.0:
                continue
            nc += 1
            if wi >= 0 and upright:
                # タイヤ: 進行方向は転がる（軽いブレーキ）、横方向は摩擦
                vl = vpx * fx + vpy * fy
                lx, ly = vpx - vl * fx, vpy - vl * fy
                sl = math.sqrt(lx * lx + ly * ly + 0.09)
                fb = 0.35 * P.mu * Fn * _ssign(vl)
                Ft = (-P.mu * Fn * lx / sl - fb * fx, -P.mu * Fn * ly / sl - fb * fy)
            else:
                mu = P.body_mu if wi < 0 else P.mu * 0.8
                sl = math.sqrt(vpx * vpx + vpy * vpy + 0.09)
                Ft = (-mu * Fn * vpx / sl, -mu * Fn * vpy / sl)
            Fi = (Ft[0], Ft[1], Fn)
            if P.record_impacts and wi < 0:
                note_impact(("g", qx, qy, qz), (qx + cgx, qy + cgy, qz + zcg), Fn * dt,
                            _mulT(R, (0.0, 0.0, 1.0)))
            F[0] += Fi[0]
            F[1] += Fi[1]
            F[2] += Fi[2]
            tq = _cross(rw, Fi)
            T[0] += tq[0]
            T[1] += tq[1]
            T[2] += tq[2]
        rb["nc"] = nc
        if P.wall_fn is not None and P.wall_near(p[0], p[1], p[2], wall_r + 1.0):
            for (qx, qy, qz, wi) in rb_pts:
                rw = _mul(R, (qx, qy, qz))
                vp = _cross(w, rw)
                hit = wall_force(p[0] + rw[0], p[1] + rw[1], p[2] + rw[2],
                                 v[0] + vp[0], v[1] + vp[1], v[2] + vp[2])
                if hit is None:
                    continue
                Fi = hit[:3]
                if P.record_impacts and wi < 0:
                    note_impact(("w", qx, qy, qz), (qx + cgx, qy + cgy, qz + zcg),
                                math.sqrt(Fi[0] ** 2 + Fi[1] ** 2 + Fi[2] ** 2) * dt, _mulT(R, hit[3]))
                for i in range(3):
                    F[i] += Fi[i]
                tq = _cross(rw, Fi)
                for i in range(3):
                    T[i] += tq[i]
        if bar_box is not None and bar_box[0] <= p[0] <= bar_box[1] and bar_box[2] <= p[1] <= bar_box[3] \
                and bar_near(p[0], p[1]):
            pts_w = []
            rws = []
            for pi_, (qx, qy, qz, wi) in enumerate(rb_pts):
                rw = _mul(R, (qx, qy, qz))
                vp = _cross(w, rw)
                rws.append(rw)
                pts_w.append((p[0] + rw[0], p[1] + rw[1], p[2] + rw[2], v[0] + vp[0], v[1] + vp[1], pi_))
            hit = barrier_hit(pts_w)
            if hit is not None:
                d, nx_, ny_, pi_ = hit
                rw = rws[pi_]
                vpx_, vpy_ = pts_w[pi_][3], pts_w[pi_][4]
                vn = vpx_ * nx_ + vpy_ * ny_
                Fn = barrier_force(d, vn)
                tx_, ty_ = vpx_ - vn * nx_, vpy_ - vn * ny_
                tl_ = math.sqrt(tx_ * tx_ + ty_ * ty_ + 0.09)
                Fi = (Fn * nx_ - 0.6 * Fn * tx_ / tl_, Fn * ny_ - 0.6 * Fn * ty_ / tl_, 0.0)
                for i in range(3):
                    F[i] += Fi[i]
                tq = _cross(rw, Fi)
                for i in range(3):
                    T[i] += tq[i]
                bar_contact[0] = True
        for i in range(3):
            v[i] += F[i] / m * dt
            v[i] *= (1.0 - 0.02 * dt)
        if P.rollover_settle and nc >= 2:
            # 地面に寝ている間は、転がり・擦れで速度と回転が落ちる
            for i in range(2):
                v[i] *= (1.0 - 0.6 * dt)
        for i in range(3):
            p[i] += v[i] * dt
        wb = _mulT(R, w)
        tb = _mulT(R, T)
        Lb = (Ib[0] * wb[0], Ib[1] * wb[1], Ib[2] * wb[2])
        gy = _cross(wb, Lb)
        wb = [wb[i] + (tb[i] - gy[i]) / Ib[i] * dt for i in range(3)]
        w2 = _mul(R, wb)
        wd = 1.5 if (P.rollover_settle and nc >= 2) else 0.1
        for i in range(3):
            w[i] = w2[i] * (1.0 - wd * dt)
        if P.rollover_settle:
            # 3 点以上で地面に着き、ほとんど動いていない状態が 0.4 秒続いたら、その姿勢で完全に止める
            sp = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
            wr = math.sqrt(w[0] * w[0] + w[1] * w[1] + w[2] * w[2])
            if nc >= 3 and sp < 0.35 and wr < 0.35:
                rb["calm"] = rb.get("calm", 0.0) + dt
            else:
                rb["calm"] = 0.0
            if rb["calm"] > 0.4:
                rb["sleep"] = True
                v[0] = v[1] = v[2] = 0.0
                w[0] = w[1] = w[2] = 0.0
        qw, qx_, qy_, qz_ = q
        ox, oy, oz = w
        q[0] += 0.5 * dt * (-ox * qx_ - oy * qy_ - oz * qz_)
        q[1] += 0.5 * dt * (ox * qw + oy * qz_ - oz * qy_)
        q[2] += 0.5 * dt * (-ox * qz_ + oy * qw + oz * qx_)
        q[3] += 0.5 * dt * (ox * qy_ - oy * qx_ + oz * qw)
        n = math.sqrt(sum(c * c for c in q))
        for i in range(4):
            q[i] /= n

    rollover_at = None
    last_steer = (0.0, 0.0, 0.0)
    bar_contact = [False]
    barrier_at = None
    car_hit_at = [None]

    for f in range(n_frames):
        inp = inputs(f) or {}

        # ---- 横転中（剛体モード）----
        if rb["on"]:
            R = _R_from_q(rb["q"])
            gl = _mul(R, cgl)
            origin = tuple(rb["p"][i] - gl[i] for i in range(3))
            dz = []
            touching = 0
            for i, w in enumerate(wheels):
                if R[2][2] > 0.3:
                    wc = _mul(R, w)
                    gz = gnd(origin[0] + wc[0], origin[1] + wc[1], s)
                    raw = gz + radii[i] - (origin[2] + wc[2])
                    if raw > -droop:
                        touching += 1
                    dz.append(_clamp(raw, -droop, P.travel))
                else:
                    dz.append(-droop)
            v = rb["v"]
            vf = v[0] * R[0][0] + v[1] * R[1][0] + v[2] * R[2][0]
            if touching:
                spin_f += vf / radii[0] * dtf
                spin_r += vf / radii[2] * dtf
            out.append({
                "origin": origin, "R": R, "steer": (last_steer[0], last_steer[1], 0.0, 0.0),
                "steer_vis": last_steer[2],
                "spin": (spin_f, spin_f, spin_r, spin_r), "dz": dz,
                "speed": math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2),
                "pos": tuple(rb["p"]), "beta": 0.0, "airborne": rb["nc"] == 0,
                "throttle": 0.0, "brake": 0.0, "handbrake": 0.0,
                "rpm": P.idle_rpm, "gear": gear + 1, "reverse": 0.0,
            })
            if P.record_impacts and imp_frame:
                for (pt, imp, nrm) in imp_frame.values():
                    impacts.append((f, pt, imp, nrm))
                imp_frame.clear()
            if rb["nc"] == 0:
                air_frames += 1
            for _ in range(sub):
                rigid_step(dt, s)
            if bar_contact[0] and barrier_at is None:
                barrier_at = f
            if progress is not None and f % 20 == 0:
                progress(f / n_frames)
            continue

        # ---- コース上の位置 ----
        if not manual:
            idx, s, err = path.project(px, py, hint)
            hint = idx
            if not spinning and not (finished and P.speed_zones is None and not P.stop_at_end):
                if P.lane_offset != 0.0 or ovt_off != 0.0:
                    _, _, e_s = path.signed_offset(px, py, hint)
                    err = abs(e_s - P.lane_offset - ovt_off)
                max_err = max(max_err, err)
            if s >= path.total - 1.0:
                finished = True

        # ---- 地面 ----
        psi_v = psi + beta
        hs = heights(px, py, psi_v, s)
        th_terr, ph_terr = terrain_angles(hs)
        if P.grip_fn is not None:
            cz_, sz_ = math.cos(psi_v), math.sin(psi_v)
            gm = [P.grip_fn(px + cz_ * q[0] - sz_ * q[1], py + sz_ * q[0] + cz_ * q[1]) for q in qs]
            gf_mu = P.mu * (gm[0] + gm[1]) * 0.5
            gr_mu = P.mu * (gm[2] + gm[3]) * 0.5
        else:
            gm = None
            gf_mu = gr_mu = P.mu
        if f == 0:
            th, ph = th_terr, ph_terr
            R = _rot_zyx(psi_v, th, ph)
            zc = sum(hs[i] + radii[i] - _mul(R, qs[i])[2] for i in range(4)) / 4.0
            for i in range(4):
                dz_prev[i] = hs[i] + radii[i] - (zc + _mul(R, qs[i])[2])

        # ---- スピン開始 ----
        if P.spin and not spinning and f >= P.spin_frame:
            spinning = True
            psi += beta
            beta = beta_v = 0.0
            psi_v = psi
            d = P.spin_dir
            if d == 0:
                kap = path.interp(path.kappa, s) if not manual else 0.0
                d = 1 if (r + kap) >= 0 else -1
            spin_sign = d
            r += d * P.spin_kick

        # ---- 横転開始 ----
        trig = 0
        if P.rollover and f >= P.rollover_frame:
            trig = 1
        elif P.rollover_auto and f > 0 and (abs(ph) > ROLL_LIMIT or abs(th) > PITCH_LIMIT):
            trig = 2
        if trig:
            d = 0
            if trig == 1:
                d = P.rollover_dir
                if d == 0:
                    if abs(vy) > 1.0:
                        d = -1 if vy > 0 else 1      # 横滑りしている側へ転がる
                    else:
                        d = 1 if r >= 0 else -1      # 曲がっている外側へ転がる
            enter_rigid(d)
            rollover_at = f
            psi_v = psi + beta

        # ---- このフレームの姿勢を記録 ----
        R = _rot_zyx(psi_v, th, ph)
        rc = _mul(R, (cgx, cgy, 0.0))
        origin = (px - rc[0], py - rc[1], zc - rc[2])
        dz = []
        n_contact = 0
        for i, q in enumerate(qs):
            raw = hs[i] + radii[i] - (zc + _mul(R, q)[2])
            if raw > -droop:
                n_contact += 1
            dz.append(_clamp(raw, -droop, P.travel))
        if n_contact == 0:
            air_frames += 1
        dvis = _clamp(delta - beta * P.countersteer, -math.radians(50), math.radians(50))
        if abs(dvis) > 1e-5:
            Rt = L / math.tan(dvis)
            dl = math.atan(L / (Rt - track_f / 2))
            dr = math.atan(L / (Rt + track_f / 2))
        else:
            dl = dr = dvis
        last_steer = (dl, dr, dvis)
        rec = {
            "origin": origin, "R": R, "steer": (dl, dr, 0.0, 0.0), "steer_vis": dvis,
            "spin": (spin_f, spin_f, spin_r, spin_r), "dz": dz,
            "speed": math.hypot(vx, vy), "pos": (px, py, zc), "beta": beta,
            "airborne": n_contact == 0,
        }
        if gm is not None:
            rec["grip"] = gm
        out.append(rec)

        # ---- ドライバー（ハンドル・アクセル・ブレーキ）----
        handbrake = inp.get("handbrake", 0.0) > 0.5
        brake_front_bias = P.brake_front_bias
        mu_r = gr_mu
        rear_lock = False
        reverse = False
        assist = P.assist and not spinning
        if spinning:
            Fdrive = 0.0
            Fbrake = m * P.brake * 0.4
            delta_cmd = spin_sign * P.max_steer * 0.6
            rear_lock = True
            brake_front_bias = 1.0
            mu_r = gr_mu * P.spin_grip
        elif manual:
            delta_cmd = -_clamp(inp.get("steer", 0.0), -1.0, 1.0) * P.max_steer
            thr = _clamp(inp.get("throttle", 0.0), 0.0, 1.0)
            reverse = inp.get("reverse", 0.0) > 0.5
            if reverse:
                fade = max(0.0, 1.0 - (max(-vx, 0.0) / max(P.reverse_top, 0.1)) ** 2)
                Fdrive = -thr * m * P.accel * 0.6 * fade
            else:
                fade = max(0.0, 1.0 - (max(vx, 0.0) / max(P.top_speed, 0.1)) ** 2)
                Fdrive = thr * m * P.accel * fade
            Fbrake = _clamp(inp.get("brake", 0.0), 0.0, 1.0) * m * P.brake
            rear_lock = handbrake
        else:
            vt = path.interp(path.v, s + 1.5 + max(vx, 0.0) * 0.2) * max(inp.get("speed_scale", 1.0), 0.0)
            if P.speed_zones:
                kz = zone_scale(P.speed_zones, s)
                if kz > 1.0:
                    if v_hi is None:
                        v_hi = path.speed_profile(P.top_speed * 3.0, P.mu * G * 0.92, P.accel * 0.9,
                                                  P.brake * 0.8, P.start_speed, P.stop_at_end)
                    vt = min(vt * kz, path.interp(v_hi, s + 1.5 + max(vx, 0.0) * 0.2))
                else:
                    vt *= kz
            if P.others and not P.no_avoid:
                # 前の車に追従（車間を保つ）・追い越し
                _, _, e_me = path.signed_offset(px, py, hint)
                vt_free = vt
                lead_k = None
                for k_, traj in enumerate(P.others):
                    if f >= len(traj):
                        continue
                    ox, oy = traj[f]
                    oi, so, eo = path.signed_offset(ox, oy, oth_hint[k_])
                    oth_hint[k_] = oi
                    ds_ = so - s
                    if ovt["k"] == k_ and ds_ < -9.0:
                        ovt["k"] = None            # 抜き終わった → 元の車線へ
                        ovt_target = 0.0
                    sep = 1.8 if ovt["k"] == k_ else 2.2
                    if 0.0 < ds_ < 60.0 and abs(eo - e_me) < sep:
                        f2 = min(f + 1, len(traj) - 1)
                        vo = math.hypot(traj[f2][0] - ox, traj[f2][1] - oy) * fps if f2 > f else 0.0
                        gap = ds_ - 5.0
                        want = 4.0 + P.follow_gap * max(vx, 0.0)
                        v_acc = max(0.0, vo + 0.6 * (gap - want))
                        if v_acc < vt:
                            vt = v_acc
                            if vo < vt_free - 1.5 and ds_ < 40.0:
                                lead_k = k_
                if P.overtake:
                    if ovt["k"] is None and lead_k is not None:
                        ovt["t"] += 1.0 / fps
                        if ovt["t"] > 1.0:     # 1秒ふさがれたら追い越し開始
                            ovt["k"] = lead_k
                            ovt_target = P.overtake_offset
                    else:
                        ovt["t"] = 0.0
                    step_ = 1.5 / fps
                    ovt_off += _clamp(ovt_target - ovt_off, -step_, step_)
            if (P.stop_at_end and s >= path.total - 0.5) or f < P.start_frame:
                vt = 0.0
            Fcmd = m * 2.0 * (vt - vx)
            Fdrive = _clamp(Fcmd, 0.0, m * P.accel)
            Fbrake = _clamp(-Fcmd, 0.0, m * P.brake)
            if vt < 0.05 and abs(vx) < 0.5:
                Fdrive, Fbrake = 0.0, m * P.brake * 0.5
            if handbrake:
                Fdrive = 0.0
                rear_lock = True
            # pure pursuit（後軸基準）
            c, sn = math.cos(psi), math.sin(psi)
            rx, ry = px - c * b, py - sn * b
            Ld = max(P.look_min, P.look_time * abs(vx))
            tx, ty = path.interp(path.x, s + Ld), path.interp(path.y, s + Ld)
            off_ = P.lane_offset + ovt_off
            if off_ != 0.0:
                nx_, ny_ = path.left_normal(s + Ld)
                tx, ty = tx + nx_ * off_, ty + ny_ * off_
            ddx, ddy = tx - rx, ty - ry
            lx, ly = c * ddx + sn * ddy, -sn * ddx + c * ddy
            dist = math.hypot(lx, ly)
            if dist > 0.5:
                delta_cmd = math.atan2(2.0 * L * math.sin(math.atan2(ly, lx)), dist)
            else:
                delta_cmd = delta
            if assist:
                # 横滑り防止: 車体の横滑り角ぶんカウンターを当て、大きければアクセルを抜く
                slip = math.atan2(vy, max(abs(vx), 1.0))
                delta_cmd += slip
                if abs(slip) > math.radians(6):
                    Fdrive *= 0.3
            if P.line_hold > 0.0:
                # 狙いのラインからのずれを、比例＋積分で舵に足す
                _, _, e_l = path.signed_offset(px, py, hint)
                e_l -= off_
                lh_int = _clamp(lh_int + e_l * dt, -20.0, 20.0)
                delta_cmd -= P.line_hold * (0.004 * e_l + 0.012 * lh_int)
            delta_cmd = _clamp(delta_cmd, -P.max_steer, P.max_steer)
        if (barrier_at is not None or car_hit_at[0] is not None) and not spinning and not manual:
            Fdrive = 0.0
            Fbrake = m * P.brake
            delta_cmd = delta
        if P.gears:
            if spinning:
                rpm = max(P.idle_rpm, rpm - 3000.0 / fps)
            else:
                if shift_t > 0.0:
                    shift_t -= 1.0 / fps
                    Fdrive = 0.0
                if not reverse:
                    rpm_now = abs(vx) * k_rpm * ratios[gear]
                    if Fdrive > 0.0 and rpm_now > P.shift_rpm and gear < len(ratios) - 1:
                        gear += 1
                        shift_t = P.shift_time
                        Fdrive = 0.0
                    elif rpm_now < P.shift_rpm * 0.45 and gear > 0:
                        gear -= 1
                    rpm = max(P.idle_rpm, abs(vx) * k_rpm * ratios[gear])
                else:
                    rpm = max(P.idle_rpm, abs(vx) * k_rpm * ratios[0])
                if Fdrive != 0.0 and rpm <= P.idle_rpm * 1.05:
                    rpm = P.idle_rpm + (P.shift_rpm - P.idle_rpm) * 0.35 * abs(Fdrive) / max(m * P.accel, 1.0)
            rec["rpm"] = min(rpm, P.redline_rpm)
            rec["gear"] = -1 if reverse else gear + 1
        rec["reverse"] = 1.0 if reverse else 0.0
        rec["throttle"] = abs(Fdrive) / (m * P.accel) if P.accel > 0 else 0.0
        rec["brake"] = Fbrake / (m * P.brake) if P.brake > 0 else 0.0
        rec["handbrake"] = 1.0 if (rear_lock and not spinning) else 0.0

        # ---- ドリフト目標角（演出用、走行ラインは物理のまま）----
        beta_t = 0.0
        if P.drift and not spinning and not manual:
            in_range = P.drift_frames is None or (P.drift_frames[0] <= f <= P.drift_frames[1])
            if in_range:
                look = 4.0 + 0.5 * max(vx, 0.0)
                ks = [path.interp(path.kappa, s + look * j / 9.0) for j in range(10)]
                k = sum(ks) / len(ks)
                k0, k1 = 1.0 / P.drift_r_start, 1.0 / P.drift_r_full
                amt = _clamp((abs(k) - k0) / max(k1 - k0, 1e-6), 0.0, 1.0)
                amt *= _clamp((vx - P.drift_min_speed * 0.5) / max(P.drift_min_speed * 0.5, 0.1), 0.0, 1.0)
                beta_t = math.copysign(P.drift_angle * amt, k)

        if rb["on"]:
            for _ in range(sub):
                rigid_step(dt, s)
            continue

        # ---- スタートの空転（ドラッグレース）----
        lf_ = 0.0
        if P.launch_time > 0.0 and not spinning:
            tl_ = (f - P.start_frame) / fps
            if tl_ >= 0.0:
                lf_ = _clamp(1.0 - tl_ / P.launch_time, 0.0, 1.0)

        # ---- 物理サブステップ ----
        for j in range(sub):
            if j > 0:
                hs = heights(px, py, psi + beta, s)
                th_terr, ph_terr = terrain_angles(hs)

            # サスペンション力（＝タイヤにかかる荷重）
            R = _rot_zyx(psi + beta, th, ph)
            Fs = [0.0] * 4
            n_contact = 0
            for i, q in enumerate(qs):
                raw = hs[i] + radii[i] - (zc + _mul(R, q)[2])
                rate = (raw - dz_prev[i]) / dt
                dz_prev[i] = raw
                if raw > -droop:
                    n_contact += 1
                    Fi = kc[i] * (s0 + raw) + cc[i] * rate
                    over = raw - P.travel
                    if over > 0.0:          # バンプストップ
                        Fi += 10.0 * kc[i] * over + cc[i] * rate
                    Fs[i] = max(Fi, 0.0)
            Fzf = Fs[0] + Fs[1]
            Fzr = Fs[2] + Fs[3]

            dd = _clamp(delta_cmd - delta, -P.steer_rate * dt, P.steer_rate * dt)
            delta += dd

            # 前輪
            cd, sd = math.cos(delta), math.sin(delta)
            vyf = vy + r * a
            vlf = cd * vx + sd * vyf
            vtf = -sd * vx + cd * vyf
            Fmax = gf_mu * Fzf
            Fx_w = Fdrive * (1.0 - P.drive_rear_bias) - Fbrake * brake_front_bias * _ssign(vlf)
            al = math.atan2(vtf, abs(vlf) + V_EPS)
            Fy_w = -Fmax * math.sin(1.9 * math.atan(8.0 * al))
            Fx_w, Fy_w = _friction(Fx_w, Fy_w, Fmax, assist)
            Fxf = cd * Fx_w - sd * Fy_w
            Fyf = sd * Fx_w + cd * Fy_w

            # 後輪
            vyr = vy - r * b
            Fmax = mu_r * Fzr
            if rear_lock:
                sp = math.sqrt(vx * vx + vyr * vyr + 0.09)
                Fxr, Fyr = -Fmax * vx / sp, -Fmax * vyr / sp
            else:
                Fxr = Fdrive * P.drive_rear_bias - Fbrake * (1.0 - brake_front_bias) * _ssign(vx)
                al = math.atan2(vyr, abs(vx) + V_EPS)
                Fyr = -Fmax * math.sin(1.9 * math.atan(8.0 * al))
                Fxr, Fyr = _friction(Fxr, Fyr, Fmax, assist)

            Fx_tire = Fxf + Fxr
            Fy_tire = Fyf + Fyr
            Mz = a * Fyf - b * Fyr
            grounded = n_contact / 4.0
            Fx = Fx_tire - 0.4 * vx * abs(vx) - m * G * 0.012 * _ssign(vx) * grounded \
                + m * G * math.sin(th_terr) * grounded
            Fy = Fy_tire - m * G * math.sin(ph_terr) * grounded
            if P.wall_fn is not None and P.wall_near(px, py, zc + zcg, wall_r):
                cw_, sw_ = math.cos(psi), math.sin(psi)
                vwx, vwy = cw_ * vx - sw_ * vy, sw_ * vx + cw_ * vy
                for (qx, qy, qz) in wall_pts:
                    ox_, oy_ = cw_ * qx - sw_ * qy, sw_ * qx + cw_ * qy
                    hit = wall_force(px + ox_, py + oy_, zc + zcg + qz, vwx - r * oy_, vwy + r * ox_, zv, True)
                    if hit is None:
                        continue
                    Fwx, Fwy = hit[0], hit[1]
                    Fbx, Fby = cw_ * Fwx + sw_ * Fwy, -sw_ * Fwx + cw_ * Fwy
                    Fx += Fbx
                    Fy += Fby
                    Mz += qx * Fby - qy * Fbx
                    if P.record_impacts:
                        nx_, ny_, nz_ = hit[3]
                        note_impact(("w", qx, qy, qz), (qx + cgx, qy + cgy, qz + zcg),
                                    math.hypot(Fwx, Fwy) * dt,
                                    (cw_ * nx_ + sw_ * ny_, -sw_ * nx_ + cw_ * ny_, nz_))
            if P.collide_with:
                cw_, sw_ = math.cos(psi), math.sin(psi)
                vwx, vwy = cw_ * vx - sw_ * vy, sw_ * vx + cw_ * vy
                pts_w = []
                for pi_, (qx, qy, qz) in enumerate(wall_pts):
                    ox_, oy_ = cw_ * qx - sw_ * qy, sw_ * qx + cw_ * qy
                    pts_w.append((px + ox_, py + oy_, vwx - r * oy_, vwy + r * ox_, pi_))
                hit = car_contacts(f + j / sub, pts_w)
                if hit is not None:
                    d, nx_, ny_, pi_, ovx_, ovy_ = hit
                    qx, qy, qz = wall_pts[pi_]
                    rvx, rvy = pts_w[pi_][2] - ovx_, pts_w[pi_][3] - ovy_
                    vn = rvx * nx_ + rvy * ny_
                    Fn = max(k_cc * d - c_cc * vn, 0.0)
                    tx_, ty_ = rvx - vn * nx_, rvy - vn * ny_
                    tl_ = math.sqrt(tx_ * tx_ + ty_ * ty_ + 0.09)
                    Fwx = Fn * nx_ - 0.4 * Fn * tx_ / tl_
                    Fwy = Fn * ny_ - 0.4 * Fn * ty_ / tl_
                    Fbx, Fby = cw_ * Fwx + sw_ * Fwy, -sw_ * Fwx + cw_ * Fwy
                    Fx += Fbx
                    Fy += Fby
                    Mz += qx * Fby - qy * Fbx
                    if car_hit_at[0] is None:
                        car_hit_at[0] = f
                    if P.record_impacts:
                        note_impact(("c", qx, qy, qz), (qx + cgx, qy + cgy, qz + zcg), math.hypot(Fwx, Fwy) * dt,
                                    (cw_ * nx_ + sw_ * ny_, -sw_ * nx_ + cw_ * ny_, 0.0))
            if bar_box is not None and bar_box[0] <= px <= bar_box[1] and bar_box[2] <= py <= bar_box[3] \
                    and bar_near(px, py):
                cw_, sw_ = math.cos(psi), math.sin(psi)
                vwx, vwy = cw_ * vx - sw_ * vy, sw_ * vx + cw_ * vy
                pts_w = []
                for pi_, (qx, qy, qz) in enumerate(wall_pts):
                    ox_, oy_ = cw_ * qx - sw_ * qy, sw_ * qx + cw_ * qy
                    pts_w.append((px + ox_, py + oy_, zc + zcg + qz, vwx - r * oy_, vwy + r * ox_, pi_))
                hit = barrier_hit(pts_w)
                if hit is not None:
                    d, nx_, ny_, pi_ = hit
                    qx, qy, qz = wall_pts[pi_]
                    ox_, oy_ = cw_ * qx - sw_ * qy, sw_ * qx + cw_ * qy
                    vpx_, vpy_ = vwx - r * oy_, vwy + r * ox_
                    vn = vpx_ * nx_ + vpy_ * ny_
                    Fn = barrier_force(d, vn)
                    tx_, ty_ = vpx_ - vn * nx_, vpy_ - vn * ny_
                    tl_ = math.sqrt(tx_ * tx_ + ty_ * ty_ + 0.09)
                    Fwx = Fn * nx_ - 0.6 * Fn * tx_ / tl_
                    Fwy = Fn * ny_ - 0.6 * Fn * ty_ / tl_
                    Fbx, Fby = cw_ * Fwx + sw_ * Fwy, -sw_ * Fwx + cw_ * Fwy
                    Fx += Fbx
                    Fy += Fby
                    Mz += qx * Fby - qy * Fbx
                    bar_contact[0] = True
                    if P.record_impacts:
                        note_impact(("b", qx, qy, qz), (qx + cgx, qy + cgy, qz + zcg), math.hypot(Fwx, Fwy) * dt,
                                    (cw_ * nx_ + sw_ * ny_, -sw_ * nx_ + cw_ * ny_, 0.0))
            vx += (Fx / m + r * vy) * dt
            vy += (Fy / m - r * vx) * dt
            r += Mz / Iz * dt
            psi += r * dt
            c, sn = math.cos(psi), math.sin(psi)
            px += (c * vx - sn * vy) * dt
            py += (sn * vx + c * vy) * dt

            # 車体の上下・ピッチ・ロール
            zv += (sum(Fs) / m - G) * dt
            zc += zv * dt
            My = -h * Fx_tire * P.pitch_mult
            if lf_ > 0.0:
                My *= 1.0 + P.launch_lift * lf_
            Mx = h * Fy_tire * P.roll_mult
            for i, q in enumerate(qs):
                My -= q[0] * Fs[i]
                Mx += q[1] * Fs[i]
            thv += My / Iy * dt
            th += thv * dt
            phv += Mx / Ix * dt
            ph += phv * dt

            # 段差: 車体の底とタイヤが地面より下に入らないよう押し上げる
            if P.body_contact:
                yaw_c = psi + beta
                Rc = _rot_zyx(yaw_c, th, ph)
                cpts = [(q[0], q[1], q[2], hs[i] + radii[i] - P.travel - 0.03) for i, q in enumerate(qs)]
                if under:
                    for (qx, qy, qz) in under:
                        rw = _mul(Rc, (qx, qy, qz))
                        cpts.append((qx, qy, qz, gnd(px + rw[0], py + rw[1], s)))
                zc, th, ph, zv, thv, phv = _lift_body(cpts, yaw_c, zc, th, ph, zv, thv, phv)

            # タイヤ回転
            spin_f += vlf / radii[0] * dt
            if not rear_lock:
                mult = 1.0 + (0.8 * abs(beta) / P.drift_angle if P.drift and P.drift_angle > 0 else 0.0)
                if lf_ > 0.0 and Fdrive > 0.0:
                    spin_r += (vx * mult + P.launch_slip * lf_) / radii[2] * dt
                else:
                    spin_r += vx / radii[2] * mult * dt

            # ドリフト角
            beta_v += (w_d * w_d * (beta_t - beta) - 2 * P.drift_damp * w_d * beta_v) * dt
            beta += beta_v * dt

        if P.record_impacts and imp_frame:
            for (pt, imp, nrm) in imp_frame.values():
                impacts.append((f, pt, imp, nrm))
            imp_frame.clear()
        if bar_contact[0] and barrier_at is None:
            barrier_at = f
        if progress is not None and f % 20 == 0:
            progress(f / n_frames)

    info = {"finished": finished, "max_err": max_err, "distance": s,
            "total": path.total if path is not None else 0.0, "air_frames": air_frames,
            "manual": manual, "rollover_at": rollover_at, "impacts": impacts, "barrier_at": barrier_at,
            "car_hit_at": car_hit_at[0]}
    return out, info


# ---------------------------------------------------------------------------
# 到達タイミング: 指定フレームに指定地点を通るよう、区間ごとの速度倍率を反復で調整
# ---------------------------------------------------------------------------

def arrival_frames(path, res, s_targets):
    hint = None
    s_list = []
    for st in res:
        hint, s_, _ = path.project(st["pos"][0], st["pos"][1], hint)
        s_list.append(s_)
    out = []
    for st_ in s_targets:
        fa = None
        for f in range(1, len(s_list)):
            if s_list[f - 1] < st_ <= s_list[f]:
                fa = f - 1 + (st_ - s_list[f - 1]) / max(s_list[f] - s_list[f - 1], 1e-6)
                break
        if fa is None:
            if s_list and s_list[0] >= st_:
                fa = 0.0
            else:
                v_end = max(res[-1]["speed"], 1.0) if res else 1.0
                fa = len(s_list) + (st_ - s_list[-1]) / v_end * 24.0
        out.append(fa)
    return out


def solve_timing(path, P, wheels, radii, n_frames, fps, height_fn, inputs, targets, iters=10):
    """targets: [(フレーム(0始まり), コース上の距離 s)]"""
    targets = sorted(targets)
    scales = [1.0] * len(targets)
    errs = []
    res = info = None
    for it in range(iters):
        zones = []
        prev = -1e9
        for (f_, s_), k in zip(targets, scales):
            zones.append((prev, s_, k))
            prev = s_
        zones.append((prev, 1e9, scales[-1] if scales else 1.0))
        P.speed_zones = zones
        res, info = simulate(path, P, wheels, radii, n_frames, fps, height_fn, inputs)
        arr = arrival_frames(path, res, [s_ for _, s_ in targets])
        errs = [a - f_ for a, (f_, _) in zip(arr, targets)]
        if all(abs(e) < 0.5 for e in errs):
            break
        pf_des, pf_act = 0.0, 0.0
        for k, ((f_, s_), a) in enumerate(zip(targets, arr)):
            d_des = max(f_ - pf_des, 1.0)
            d_act = max(a - pf_act, 1.0)
            ratio = _clamp(d_act / d_des, 0.6, 1.6)
            scales[k] = _clamp(scales[k] * ratio ** 0.9, 0.05, 3.0)
            pf_des, pf_act = a, a          # 次の区間は実際の到着から数える（遅れを取り戻す）
    info["timing_errors"] = errs
    info["timing_scales"] = scales
    return res, info


# ---------------------------------------------------------------------------
# 手付けアニメへの後付け: 位置と向きは手付けのまま、サスペンション・タイヤ・ハンドルを物理で付ける
# ---------------------------------------------------------------------------

ROLL_LIM_K = math.radians(20)
PITCH_LIM_K = math.radians(25)


def simulate_keyed(poses, P, wheels, radii, fps, height_fn=None, progress=None):
    """poses: フレームごとの (原点x, 原点y, 原点z, ヨー角)  車体座標の原点（ボディの原点）"""
    m = P.mass
    geo = car_geometry(wheels, P.front_weight)
    L, a, b = geo["L"], geo["a"], geo["b"]
    cgx, cgy = geo["cgx"], geo["cgy"]
    track_f, track = geo["track_f"], geo["track"]
    qs = [(w[0] - cgx, w[1] - cgy, w[2]) for w in wheels]
    Iy = m * a * b
    Ix = 0.5 * m * max(track * 0.5, 0.3) ** 2
    h = P.cg_height
    ws = 2.0 * math.pi * P.susp_freq
    s0 = G / (ws * ws)
    droop = min(0.95 * s0, P.travel)
    kc = [m * P.front_weight * 0.5 * ws * ws] * 2 + [m * (1.0 - P.front_weight) * 0.5 * ws * ws] * 2
    cc = [2.0 * P.susp_damp * k / ws for k in kc]
    z_wh = sum(w[2] for w in wheels) / 4.0 - sum(radii) / 4.0   # 原点から接地面までの高さ
    n = len(poses)
    dtf = 1.0 / fps
    sub = max(1, int(math.ceil(dtf / MAX_DT)))
    dt = dtf / sub

    # 重心の位置とヨー（連続化）
    cg = []
    yaws = []
    prev = None
    for (ox, oy, oz, yw) in poses:
        if prev is not None:
            yw = prev + _wrap(yw - prev)
        prev = yw
        c, sn = math.cos(yw), math.sin(yw)
        cg.append((ox + c * cgx - sn * cgy, oy + sn * cgx + c * cgy, oz))
        yaws.append(yw)

    def at(i):
        return cg[_clamp(i, 0, n - 1)]

    vel, acc, yr = [], [], []
    for i in range(n):
        p0, p1, p2 = at(i - 1), at(i), at(i + 1)
        span = (min(i + 1, n - 1) - max(i - 1, 0)) * dtf or dtf
        vel.append(((p2[0] - p0[0]) / span, (p2[1] - p0[1]) / span))
        y0, y2 = yaws[max(i - 1, 0)], yaws[min(i + 1, n - 1)]
        yr.append((y2 - y0) / span)
    for i in range(n):
        v0, v2 = vel[max(i - 1, 0)], vel[min(i + 1, n - 1)]
        span = (min(i + 1, n - 1) - max(i - 1, 0)) * dtf or dtf
        acc.append(((v2[0] - v0[0]) / span, (v2[1] - v0[1]) / span))

    last_h = [None] * 4
    last_pose = [None]
    under = _under_points(P, wheels, radii, cgx, cgy) if (P.body_contact and height_fn is not None) else None

    def heights(i_f):
        i0 = int(math.floor(i_f))
        tt = i_f - i0
        pa, pb = at(i0), at(i0 + 1)
        x = pa[0] + (pb[0] - pa[0]) * tt
        y = pa[1] + (pb[1] - pa[1]) * tt
        yw = yaws[_clamp(i0, 0, n - 1)] + (yaws[_clamp(i0 + 1, 0, n - 1)] - yaws[_clamp(i0, 0, n - 1)]) * tt
        cz, sz = math.cos(yw), math.sin(yw)
        zref = pa[2] + (pb[2] - pa[2]) * tt + z_wh
        last_pose[0] = (x, y, yw)
        hs = []
        for k, q in enumerate(qs):
            wx, wy = x + cz * q[0] - sz * q[1], y + sz * q[0] + cz * q[1]
            if height_fn is None:
                hz = None
            elif P.tire_profile:
                hz = _tire_height(height_fn, wx, wy, cz, sz, radii[k])
            else:
                hz = height_fn(wx, wy)
            if hz is None:
                hz = last_h[k] if (height_fn is not None and last_h[k] is not None) else zref
            last_h[k] = hz
            if P.road_noise > 0.0:
                hz += _road(wx, wy, P.road_noise)
            hs.append(hz)
        return hs

    out = []
    zc = zv = th = thv = ph = phv = 0.0
    delta = 0.0
    spin_f = spin_r = 0.0
    dz_prev = [0.0] * 4
    air = 0
    for f in range(n):
        hs = heights(f)
        yw = yaws[f]
        c, sn = math.cos(yw), math.sin(yw)
        if f == 0:
            th = -math.atan2((hs[0] + hs[1] - hs[2] - hs[3]) * 0.5, L)
            ph = math.atan2((hs[0] + hs[2] - hs[1] - hs[3]) * 0.5, max(track, 0.1))
            R = _rot_zyx(yw, th, ph)
            zc = sum(hs[i] + radii[i] - _mul(R, qs[i])[2] for i in range(4)) / 4.0
            for i in range(4):
                dz_prev[i] = hs[i] + radii[i] - (zc + _mul(R, qs[i])[2])
        vxf = vel[f][0] * c + vel[f][1] * sn
        # 手付けの急な折れ曲がりで、物理的にありえない加速度になることがあるので上限で抑える
        a_lim = 1.1 * P.mu * G          # タイヤが出せる力の上限
        ax = _clamp(acc[f][0] * c + acc[f][1] * sn, -a_lim, a_lim)
        ay = _clamp(-acc[f][0] * sn + acc[f][1] * c, -a_lim, a_lim)
        if abs(vxf) > 0.3:
            d_cmd = _clamp(math.atan(L * yr[f] / vxf), -P.max_steer, P.max_steer)
        else:
            d_cmd = delta
        # 記録
        R = _rot_zyx(yw, th, ph)
        rc = _mul(R, (cgx, cgy, 0.0))
        origin = (cg[f][0] - rc[0], cg[f][1] - rc[1], zc - rc[2])
        dz = []
        nc = 0
        for i, q in enumerate(qs):
            raw = hs[i] + radii[i] - (zc + _mul(R, q)[2])
            if raw > -droop:
                nc += 1
            dz.append(_clamp(raw, -droop, P.travel))
        if nc == 0:
            air += 1
        if abs(delta) > 1e-5:
            Rt = L / math.tan(delta)
            dl, dr = math.atan(L / (Rt - track_f / 2)), math.atan(L / (Rt + track_f / 2))
        else:
            dl = dr = delta
        out.append({
            "origin": origin, "R": R, "steer": (dl, dr, 0.0, 0.0), "steer_vis": delta,
            "spin": (spin_f, spin_f, spin_r, spin_r), "dz": dz,
            "speed": math.hypot(*vel[f]), "pos": (cg[f][0], cg[f][1], zc), "beta": 0.0,
            "airborne": nc == 0,
            "throttle": _clamp(ax / max(P.accel, 0.1), 0.0, 1.0) if ax > 0.3 else 0.0,
            "brake": _clamp(-ax / max(P.brake, 0.1), 0.0, 1.0) if ax < -0.3 else 0.0,
            "handbrake": 0.0, "reverse": 1.0 if vxf < -0.3 else 0.0,
        })
        # サブステップ（サスペンションのみ）
        for j in range(sub):
            if j > 0:
                hs = heights(f + j / sub)
            R = _rot_zyx(yw, th, ph)
            Fs = [0.0] * 4
            for i, q in enumerate(qs):
                raw = hs[i] + radii[i] - (zc + _mul(R, q)[2])
                rate = (raw - dz_prev[i]) / dt
                dz_prev[i] = raw
                if raw > -droop:
                    Fi = kc[i] * (s0 + raw) + cc[i] * rate
                    over = raw - P.travel
                    if over > 0.0:      # 手付けは速い着地が多いので、底付きを強めに受け止める
                        Fi += 60.0 * kc[i] * over + 4.0 * cc[i] * rate
                    Fs[i] = max(Fi, 0.0)
            zv += (sum(Fs) / m - G) * dt
            zc += zv * dt
            My = -h * m * ax * P.pitch_mult
            Mx = h * m * ay * P.roll_mult
            for i, q in enumerate(qs):
                My -= q[0] * Fs[i]
                Mx += q[1] * Fs[i]
            # 手付けの動きに沿わせるモードなので、傾き過ぎないよう柔らかく引き戻す（横転はしない）
            if abs(ph) > ROLL_LIM_K:
                Mx -= math.copysign((abs(ph) - ROLL_LIM_K) * 40.0 * Ix * ws * ws, ph) + 4.0 * Ix * ws * phv
            if abs(th) > PITCH_LIM_K:
                My -= math.copysign((abs(th) - PITCH_LIM_K) * 40.0 * Iy * ws * ws, th) + 4.0 * Iy * ws * thv
            thv += My / Iy * dt
            th += thv * dt
            phv += Mx / Ix * dt
            ph += phv * dt
            if P.body_contact and height_fn is not None:
                x_c, y_c, yaw_c = last_pose[0]
                Rc = _rot_zyx(yaw_c, th, ph)
                cpts = [(q[0], q[1], q[2], hs[i] + radii[i] - P.travel - 0.03) for i, q in enumerate(qs)]
                if under:
                    for (qx, qy, qz) in under:
                        rw = _mul(Rc, (qx, qy, qz))
                        gz = height_fn(x_c + rw[0], y_c + rw[1])
                        if gz is not None:
                            cpts.append((qx, qy, qz, gz))
                zc, th, ph, zv, thv, phv = _lift_body(cpts, yaw_c, zc, th, ph, zv, thv, phv)
            delta += _clamp(d_cmd - delta, -P.steer_rate * dt, P.steer_rate * dt)
            spin_f += vxf / radii[0] * dt
            spin_r += vxf / radii[2] * dt
        if progress is not None and f % 20 == 0:
            progress(f / n)
    return out, {"air_frames": air, "finished": True, "max_err": 0.0, "distance": 0.0,
                 "total": 0.0, "manual": True, "rollover_at": None, "impacts": []}


# ---------------------------------------------------------------------------
# トレーラー（連結点に引っ張られて付いてくる。車の動きには影響しない）
# ---------------------------------------------------------------------------

def simulate_trailer(res, TR, fps, height_fn=None, flat_z=0.0, road_noise=0.0):
    """
    TR: hitch_car  車体座標の連結点
        hitch_len  連結点から車軸中心までの水平距離
        hitch_dz   連結点の、車軸中心からの高さ
        wheels     トレーラー座標 (x前, y左, z上; 原点=車軸中心) のタイヤ位置
        radius, travel, roll_freq, roll_damp, roll_gain
    """
    Lh = max(TR["hitch_len"], 0.3)
    wh = TR["wheels"]
    rad = TR["radius"]
    n = len(res)
    sub = 8
    dtf = 1.0 / fps
    dt = dtf / sub
    hp = []
    for st in res:
        H = _mul(st["R"], TR["hitch_car"])
        o = st["origin"]
        hp.append((o[0] + H[0], o[1] + H[1], o[2] + H[2]))
    R0 = res[0]["R"]
    psi_t = math.atan2(R0[1][0], R0[0][0])
    ph = phv = 0.0
    spin = 0.0
    out = []
    track = (max(w[1] for w in wh) - min(w[1] for w in wh)) or 1.0
    w_r = 2 * math.pi * TR.get("roll_freq", 1.5)
    last = [flat_z] * len(wh)
    prev_ay = 0.0
    for f in range(n):
        H = hp[f]
        c, sn = math.cos(psi_t), math.sin(psi_t)
        A = (H[0] - Lh * c, H[1] - Lh * sn)
        hs = []
        for k, w in enumerate(wh):
            wx, wy = A[0] + c * w[0] - sn * w[1], A[1] + sn * w[0] + c * w[1]
            hz = height_fn(wx, wy) if height_fn is not None else None
            if hz is None:
                hz = last[k] if height_fn is not None else H[2] - TR["hitch_dz"] - rad
            last[k] = hz
            if road_noise > 0.0:
                hz += _road(wx, wy, road_noise)
            hs.append(hz)
        Az = sum(hs) / len(hs) + rad
        th = -math.asin(_clamp((H[2] - Az - TR["hitch_dz"]) / Lh, -0.9, 0.9))
        left = [hs[k] for k, w in enumerate(wh) if w[1] > 0] or hs
        right = [hs[k] for k, w in enumerate(wh) if w[1] <= 0] or hs
        ph_terr = math.atan2(sum(left) / len(left) - sum(right) / len(right), track)
        R = _rot_zyx(psi_t, th, ph)
        dz = []
        for k, w in enumerate(wh):
            wz = Az + _mul(R, w)[2]
            dz.append(_clamp(hs[k] + rad - wz, -TR["travel"], TR["travel"]))
        out.append({"origin": (A[0], A[1], Az), "R": R, "spin": spin, "dz": dz})
        # 次フレームまで積分
        H2 = hp[min(f + 1, n - 1)]
        vHx, vHy = (H2[0] - H[0]) / dtf, (H2[1] - H[1]) / dtf
        for j in range(sub):
            c, sn = math.cos(psi_t), math.sin(psi_t)
            psi_t += ((-sn) * vHx + c * vHy) / Lh * dt
        vax = c * vHx + sn * vHy
        ay = vax * ((-sn) * vHx + c * vHy) / Lh
        for j in range(sub):
            phv += (w_r * w_r * (ph_terr + TR.get("roll_gain", 0.08) * ay / G - ph)
                    - 2 * TR.get("roll_damp", 0.5) * w_r * phv) * dt
            ph += phv * dt
        spin += vax / rad * dtf
    return out


# ---------------------------------------------------------------------------
# 後処理用: タイヤの滑り・揺れもの
# ---------------------------------------------------------------------------

def wheel_world(st, w, dz):
    o, R = st["origin"], st["R"]
    p = _mul(R, (w[0], w[1], w[2] + dz))
    return (o[0] + p[0], o[1] + p[1], o[2] + p[2])


def compute_slip(res, wheels, radii, fps, height_fn=None, flat_z=None):
    """フレームごと・タイヤごとの (滑りの強さ0〜1, 接地点, 進行方向) を返す"""
    n = len(res)
    pos = [[wheel_world(st, wheels[i], st["dz"][i]) for i in range(4)] for st in res]
    out = []
    for f in range(n):
        st = res[f]
        R = st["R"]
        row = []
        f0, f1 = max(f - 1, 0), min(f + 1, n - 1)
        span = max(f1 - f0, 1) / fps
        for i in range(4):
            p0, p1 = pos[f0][i], pos[f1][i]
            vx_, vy_ = (p1[0] - p0[0]) / span, (p1[1] - p0[1]) / span
            stv = st["steer"][i]
            cs, ss = math.cos(stv), math.sin(stv)
            fx = R[0][0] * cs + R[0][1] * ss
            fy = R[1][0] * cs + R[1][1] * ss
            fl = math.hypot(fx, fy) or 1.0
            fx, fy = fx / fl, fy / fl
            vl = vx_ * fx + vy_ * fy
            lat = math.hypot(vx_ - vl * fx, vy_ - vl * fy)
            spin_rate = (res[f1]["spin"][i] - res[f0]["spin"][i]) / span * radii[i]
            lon = abs(vl - spin_rate)
            p = pos[f][i]
            gz = None
            if height_fn is not None:
                gz = height_fn(p[0], p[1])
            if gz is None:
                gz = flat_z if flat_z is not None else p[2] - radii[i]
            contact = (p[2] - radii[i] - gz) < 0.06 and R[2][2] > 0.5
            k = _clamp((math.hypot(lat, lon) - 1.2) / 5.0, 0.0, 1.0) if contact else 0.0
            row.append((k, (p[0], p[1], gz), (fx, fy)))
        out.append(row)
    return out


def jiggle_angles(res, fps, freq=2.0, damp=0.25, amount=1.0):
    """車体の加速度から揺れもの（アンテナ・荷物・頭など）の傾き (ロール, ピッチ) を計算"""
    n = len(res)
    dtf = 1.0 / fps
    P_ = [st["pos"] for st in res]
    acc = []
    for f in range(n):
        a_, b_, c_ = P_[max(f - 1, 0)], P_[f], P_[min(f + 1, n - 1)]
        acc.append(tuple((a_[k] - 2 * b_[k] + c_[k]) / (dtf * dtf) for k in range(3)))
    w = 2 * math.pi * freq
    sub = 8
    dt = dtf / sub
    rx = vx = ry = vy = 0.0
    out = []
    for f in range(n):
        R = res[f]["R"]
        al = _mulT(R, acc[f])
        tgt_pitch = _clamp(-al[0] / G * 0.35 * amount, -0.8, 0.8)   # 加速で後ろへ倒れる（Y軸まわり負）
        tgt_roll = _clamp(al[1] / G * 0.35 * amount, -0.8, 0.8)     # 左へ曲がると右へ倒れる
        out.append((rx, ry))
        for _ in range(sub):
            vx += (w * w * (tgt_roll - rx) - 2 * damp * w * vx) * dt
            rx += vx * dt
            vy += (w * w * (tgt_pitch - ry) - 2 * damp * w * vy) * dt
            ry += vy * dt
    return out


# ---------------------------------------------------------------------------
# Blender 部分
# ---------------------------------------------------------------------------

try:
    import bpy
    import bmesh
    from mathutils import Matrix, Vector
    from mathutils.bvhtree import BVHTree
    from mathutils.geometry import interpolate_bezier
    from mathutils.interpolate import poly_3d_calc
    from bpy.props import (PointerProperty, FloatProperty, IntProperty, CollectionProperty,
                           BoolProperty, EnumProperty, StringProperty, FloatVectorProperty)
except ImportError:
    bpy = None


if bpy is not None:

    REST_KEY = "cpb_rest"
    REST_BONES = "cpb_rest_bones"
    SRC_KEY = "cpb_src_action"
    SRC_ROT = "cpb_src_rotmode"
    TRAJ_NAME = "CPB_走行軌跡"
    SKID_NAME = "CPB_タイヤ痕"
    SMOKE_NAME = "CPB_タイヤスモーク"
    SPARK_NAME = "CPB_火花"
    PART_REST = "cpb_part_rest"
    PART_ROT = "cpb_part_rotmode"
    DENT_PREFIX = "CPB_へこみ"
    OUT_PROPS = ("cpb_speed", "cpb_throttle", "cpb_brake", "cpb_handbrake", "cpb_steer")
    EXTRA_PROPS = ("cpb_rpm", "cpb_gear", "cpb_reverse")

    PRESETS = {
        "SEDAN": dict(mass=1400, front_weight=0.58, cg_height=0.5, mu=1.0, drive="FWD", accel=3.5,
                      brake=7.0, top_speed=120, susp_freq=1.3, susp_damp=0.45, pitch_mult=1.0,
                      roll_mult=1.0, travel=0.12, max_steer=35, road_noise=0.005),
        "SPORTS": dict(mass=1300, front_weight=0.52, cg_height=0.42, mu=1.15, drive="RWD", accel=6.0,
                       brake=9.0, top_speed=220, susp_freq=2.0, susp_damp=0.6, pitch_mult=0.8,
                       roll_mult=0.7, travel=0.08, max_steer=32, road_noise=0.004),
        "LUXURY": dict(mass=2000, front_weight=0.53, cg_height=0.52, mu=1.0, drive="RWD", accel=4.5,
                       brake=8.0, top_speed=180, susp_freq=1.0, susp_damp=0.35, pitch_mult=1.2,
                       roll_mult=1.2, travel=0.14, max_steer=35, road_noise=0.003),
        "SUV": dict(mass=2300, front_weight=0.55, cg_height=0.75, mu=0.9, drive="AWD", accel=3.5,
                    brake=6.5, top_speed=140, susp_freq=1.2, susp_damp=0.4, pitch_mult=1.2,
                    roll_mult=1.3, travel=0.18, max_steer=33, road_noise=0.006),
        "RALLY": dict(mass=1300, front_weight=0.55, cg_height=0.5, mu=0.65, drive="AWD", accel=5.0,
                      brake=6.0, top_speed=160, susp_freq=1.4, susp_damp=0.5, pitch_mult=1.0,
                      roll_mult=1.0, travel=0.22, max_steer=38, road_noise=0.03),
        "TRUCK": dict(mass=4000, front_weight=0.6, cg_height=1.0, mu=0.8, drive="RWD", accel=1.8,
                      brake=5.0, top_speed=90, susp_freq=1.6, susp_damp=0.35, pitch_mult=1.0,
                      roll_mult=1.2, travel=0.15, max_steer=38, road_noise=0.008),
    }

    class _BakeError(Exception):
        pass

    def _apply_preset(self, context):
        p = PRESETS.get(self.preset)
        if p:
            for k, v in p.items():
                setattr(self, k, v)

    def _mat_to_list(M):
        return [v for row in M for v in row]

    def _list_to_mat(l):
        return Matrix([l[0:4], l[4:8], l[8:12], l[12:16]])

    def _car_objects(s):
        return [s.body, s.wheel_fl, s.wheel_fr, s.wheel_rl, s.wheel_rr]

    def _rest_objects(s):
        objs = [o for o in _car_objects(s) if o is not None]
        if s.steering_wheel is not None:
            objs.append(s.steering_wheel)
        return objs

    def _forward_vec(axis):
        return {"POS_X": Vector((1, 0, 0)), "NEG_X": Vector((-1, 0, 0)),
                "POS_Y": Vector((0, 1, 0)), "NEG_Y": Vector((0, -1, 0))}[axis]

    def _curve_points(obj):
        mw = obj.matrix_world
        sp = obj.data.splines[0]
        pts = []
        if sp.type == 'BEZIER':
            bps = list(sp.bezier_points)
            segs = list(zip(bps[:-1], bps[1:]))
            if sp.use_cyclic_u:
                segs.append((bps[-1], bps[0]))
            for p, q in segs:
                seg = interpolate_bezier(mw @ p.co, mw @ p.handle_right,
                                         mw @ q.handle_left, mw @ q.co, 32)
                pts.extend(seg[1:] if pts else seg)
            if sp.use_cyclic_u:
                pts = pts[:-1]
        else:
            pts = [mw @ Vector(p.co[:3]) for p in sp.points]
        return [(v.x, v.y, v.z) for v in pts], sp.use_cyclic_u

    def _height_fn(ground, depsgraph):
        ev = ground.evaluated_get(depsgraph)
        me = ev.to_mesh()
        bm = bmesh.new()
        bm.from_mesh(me)
        bm.transform(ground.matrix_world)
        ev.to_mesh_clear()
        tree = BVHTree.FromBMesh(bm)
        bm.free()
        ztop = max((ground.matrix_world @ Vector(c)).z for c in ground.bound_box) + 50.0
        down = Vector((0, 0, -1))

        def fn(x, y):
            hit = tree.ray_cast(Vector((x, y, ztop)), down)
            return hit[0].z if hit[0] is not None else None
        return fn

    def _grip_fn(ground, vgroup, low):
        """地面の頂点グループ（ウェイトペイント）でグリップを下げる。ウェイト1で low 倍"""
        me = ground.data
        vg = ground.vertex_groups.get(vgroup)
        if vg is None:
            raise _BakeError("地面に頂点グループ「%s」がありません" % vgroup)
        gi = vg.index
        wts = [0.0] * len(me.vertices)
        for v in me.vertices:
            for g in v.groups:
                if g.group == gi:
                    wts[v.index] = g.weight
        mw = ground.matrix_world
        co = [mw @ v.co for v in me.vertices]
        polys = [tuple(p.vertices) for p in me.polygons]
        bm = bmesh.new()
        bm.from_mesh(me)
        bm.transform(mw)
        tree = BVHTree.FromBMesh(bm)
        bm.free()
        ztop = max((mw @ Vector(c)).z for c in ground.bound_box) + 50.0
        down = Vector((0, 0, -1))

        def fn(x, y):
            hit = tree.ray_cast(Vector((x, y, ztop)), down)
            if hit[0] is None:
                return 1.0
            vs = polys[hit[2]]
            ws = poly_3d_calc([co[i] for i in vs], hit[0])
            w = sum(ws[k] * wts[vs[k]] for k in range(len(vs)))
            return 1.0 - _clamp(w, 0.0, 1.0) * (1.0 - low)
        return fn

    def _wall_fns(coll, depsgraph):
        """コレクション内のメッシュを壁にする。面の表（法線）側が道路側"""
        bm = bmesh.new()
        n = 0
        for o in coll.all_objects:
            if o.type != 'MESH':
                continue
            ev = o.evaluated_get(depsgraph)
            me = ev.to_mesh()
            tmp = bmesh.new()
            tmp.from_mesh(me)
            tmp.transform(o.matrix_world)
            ev.to_mesh_clear()
            me2 = bpy.data.meshes.new("_cpb_tmp")
            tmp.to_mesh(me2)
            tmp.free()
            bm.from_mesh(me2)
            bpy.data.meshes.remove(me2)
            n += 1
        if n == 0:
            bm.free()
            raise _BakeError("壁コレクションにメッシュがありません")
        tree = BVHTree.FromBMesh(bm)
        bm.free()

        def wall_fn(x, y, z):
            p = Vector((x, y, z))
            loc, nrm, idx, dist = tree.find_nearest(p, 1.5)
            if loc is None:
                return None
            if (p - loc).dot(nrm) >= 0.0:
                return None
            return (dist, nrm.x, nrm.y, nrm.z)

        def wall_near(x, y, z, r):
            return tree.find_nearest(Vector((x, y, z)), r)[0] is not None
        return wall_fn, wall_near

    def _hull_points(obj, M, depsgraph, n_dirs=96):
        """メッシュの外周点を、いろいろな方向で一番外側にある頂点として拾う"""
        import numpy as np
        ev = obj.evaluated_get(depsgraph)
        me = ev.to_mesh()
        nv = len(me.vertices)
        if nv == 0:
            ev.to_mesh_clear()
            return None
        co = np.empty(nv * 3, dtype=np.float64)
        me.vertices.foreach_get("co", co)
        ev.to_mesh_clear()
        co = co.reshape(-1, 3)
        Mn = np.array(M, dtype=np.float64)
        pts = co @ Mn[:3, :3].T + Mn[:3, 3]
        i = np.arange(n_dirs) + 0.5
        phi = np.arccos(1 - 2 * i / n_dirs)
        th = math.pi * (1 + 5 ** 0.5) * i
        dirs = np.stack([np.cos(th) * np.sin(phi), np.sin(th) * np.sin(phi), np.cos(phi)], axis=1)
        idx = np.unique(np.argmax(pts @ dirs.T, axis=0))
        return [tuple(float(v) for v in pts[k]) for k in idx]

    def _hull_points_multi(pairs, depsgraph, n_dirs=96):
        """複数メッシュ (obj, 行列) の外周点"""
        import numpy as np
        arrs = []
        for obj, M in pairs:
            ev = obj.evaluated_get(depsgraph)
            me = ev.to_mesh()
            nv = len(me.vertices)
            if nv:
                co = np.empty(nv * 3, dtype=np.float64)
                me.vertices.foreach_get("co", co)
                Mn = np.array(M, dtype=np.float64)
                arrs.append(co.reshape(-1, 3) @ Mn[:3, :3].T + Mn[:3, 3])
            ev.to_mesh_clear()
        if not arrs:
            return None
        pts = np.concatenate(arrs)
        i = np.arange(n_dirs) + 0.5
        phi = np.arccos(1 - 2 * i / n_dirs)
        th = math.pi * (1 + 5 ** 0.5) * i
        dirs = np.stack([np.cos(th) * np.sin(phi), np.sin(th) * np.sin(phi), np.cos(phi)], axis=1)
        idx = np.unique(np.argmax(pts @ dirs.T, axis=0))
        return [tuple(float(v) for v in pts[k]) for k in idx]

    def _body_meshes(body_obj, exclude):
        """ボディがエンプティのとき: 子孫のメッシュ（タイヤ・平らな影は除く）"""
        out = []
        ex = set(o.name for o in exclude if o is not None)
        for o in body_obj.children_recursive:
            if o.type != 'MESH' or o.name in ex:
                continue
            d = o.dimensions
            if max(d) <= 0 or min(d) < 0.02 * max(d):
                continue
            out.append(o)
        return out

    def _dent_target(body_obj, exclude):
        if body_obj.type == 'MESH':
            return body_obj
        ms = _body_meshes(body_obj, exclude)
        return max(ms, key=lambda o: len(o.data.vertices)) if ms else None

    BARRIER_PROXY = "CPB_車体の当たり"
    BARRIER_COLL = "CPB_タイヤバリヤ"

    def _barrier_tires(s):
        if not s.use_barrier or s.barrier_collection is None:
            return []
        return [o for o in s.barrier_collection.all_objects if o.type == 'MESH']

    # タイヤの断面（半径, 高さ）。外径 0.62 m・幅 0.2 m の古タイヤ（ホイールなし）。
    # 平らなトレッドに縦溝 2 本、角の丸いショルダー、ふくらんだサイドウォール、内側はビード（穴）
    TIRE_PROFILE = [
        (0.190, 0.062), (0.198, 0.080), (0.222, 0.093), (0.255, 0.100), (0.284, 0.098), (0.300, 0.090),
        (0.308, 0.078), (0.310, 0.062), (0.310, 0.046), (0.301, 0.044), (0.301, 0.032), (0.310, 0.030),
        (0.310, -0.030), (0.301, -0.032), (0.301, -0.044), (0.310, -0.046), (0.310, -0.062), (0.308, -0.078),
        (0.300, -0.090), (0.284, -0.098), (0.255, -0.100), (0.222, -0.093), (0.198, -0.080), (0.190, -0.062),
    ]

    def _tire_mesh(k):
        """積み上げ用タイヤのメッシュ（平らなトレッド・溝・サイドウォール・中央の穴がある本物のタイヤの形）"""
        name = "CPB_バリヤタイヤv2_%.3f" % k
        me = bpy.data.meshes.get(name)
        if me is not None:
            return me
        bm = bmesh.new()
        seg = 32
        prof = TIRE_PROFILE
        rows = []
        for i in range(seg):
            a = 2 * math.pi * i / seg
            ca, sa = math.cos(a), math.sin(a)
            rows.append([bm.verts.new((r * ca * k, r * sa * k, z * k)) for (r, z) in prof])
        n = len(prof)
        for i in range(seg):
            for j in range(n):
                bm.faces.new((rows[i][j], rows[i][(j + 1) % n], rows[(i + 1) % seg][(j + 1) % n],
                              rows[(i + 1) % seg][j]))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        me = bpy.data.meshes.new(name)
        bm.to_mesh(me)
        bm.free()
        # 溝の段差とトレッドの角は角ばらせ、サイドウォールは滑らかに
        for pl in me.polygons:
            pl.use_smooth = True
        sharp = set()
        for j, (r, z) in enumerate(prof):
            r2, z2 = prof[(j + 1) % n]
            if abs(r - r2) > 0.006 and abs(z - z2) < 0.004:      # 溝の壁
                sharp.add(j)
        attr = me.attributes.get("sharp_face") or me.attributes.new("sharp_face", 'BOOLEAN', 'FACE')
        for fi, pl in enumerate(me.polygons):
            attr.data[fi].value = (fi % n) in sharp
        return me

    def _is_old_tire_mesh(me):
        return me is not None and me.name.startswith("CPB_バリヤタイヤ_")

    def _barrier_mat(name, color):
        m = bpy.data.materials.get(name)
        if m is None:
            m = bpy.data.materials.new(name)
            m.use_nodes = True
            bs = next(n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
            bs.inputs['Base Color'].default_value = color
            bs.inputs['Roughness'].default_value = 0.85
            m.diffuse_color = color
        return m

    def _restore_barrier(tires):
        for o in tires:
            _remove_keys(o)
            if o.rigid_body is not None:
                with bpy.context.temp_override(object=o, active_object=o, selected_objects=[o]):
                    try:
                        bpy.ops.rigidbody.object_remove()
                    except RuntimeError:
                        pass
            if REST_KEY in o:
                o.matrix_world = _list_to_mat(list(o[REST_KEY]))

    def _scatter_tires(scene, s, tires, body_obj, rel_body, hull, k, ground, f0, f1, car_track=None,
                       hit_f=None, car_pos=None):
        """Blender の剛体シミュレーションで、車に押されたタイヤを飛び散らせてキーフレームにする。
        軽くするため:
        ・車の通り道の近くのタイヤだけを動かし、その周りのタイヤだけを固定の障害物にする（遠くは計算に入れない）
        ・地面はタイヤの近くだけを切り出した一時メッシュを使う（コース全体の地面を使わない）
        ・タイヤの当たりは円柱（凸包より軽い）
        ・ぶつかる少し前から、タイヤが止まって車が離れるまでだけ計算する（その前後はキーの値を保つ）"""
        pos0 = {o.name: o.matrix_world.translation.copy() for o in tires}
        reach = (max(math.hypot(x_, y_) for (x_, y_, z_) in hull) + 6.0 * k) ** 2
        if car_track:
            moving = [o for o in tires if any((pos0[o.name].x - q[0]) ** 2 + (pos0[o.name].y - q[1]) ** 2 < reach
                                               for q in car_track)]
        else:
            moving = list(tires)
        if not moving:
            return 0
        xs = [pos0[o.name].x for o in moving]
        ys = [pos0[o.name].y for o in moving]
        pad = 4.0 * k
        box = (min(xs) - pad, max(xs) + pad, min(ys) - pad, max(ys) + pad)
        mset = {o.name for o in moving}
        fixed = [o for o in tires if o.name not in mset
                 and box[0] <= pos0[o.name].x <= box[1] and box[2] <= pos0[o.name].y <= box[3]]

        # 車体の当たり（凸包）を作り、ボディの子にする
        old = bpy.data.objects.get(BARRIER_PROXY)
        if old is not None:
            bpy.data.objects.remove(old)
        bm = bmesh.new()
        for pnt in hull:
            bm.verts.new(pnt)
        bmesh.ops.convex_hull(bm, input=bm.verts)
        me = bpy.data.meshes.new(BARRIER_PROXY)
        bm.to_mesh(me)
        bm.free()
        proxy = bpy.data.objects.new(BARRIER_PROXY, me)
        scene.collection.objects.link(proxy)
        proxy.parent = body_obj
        proxy.matrix_parent_inverse = rel_body.inverted()
        proxy.display_type = 'WIRE'
        proxy.hide_render = True

        # 地面: タイヤの近くと、ぶつかった後の車の通り道だけを切り出す（飛んだタイヤが外に出ないよう広めに）
        gx = xs + [q[0] for q in (car_track or [])]
        gy = ys + [q[1] for q in (car_track or [])]
        gpad = 60.0 * k
        gb = (min(gx) - gpad, max(gx) + gpad, min(gy) - gpad, max(gy) + gpad)
        gmesh = bpy.data.meshes.new("CPB_バリヤ用の地面")
        made = False
        if ground is not None and ground.type == 'MESH':
            dg = bpy.context.evaluated_depsgraph_get()
            ev = ground.evaluated_get(dg)
            me_ = ev.to_mesh()
            bm = bmesh.new()
            bm.from_mesh(me_)
            ev.to_mesh_clear()
            bm.transform(ground.matrix_world)
            kill = []
            for fc in bm.faces:
                fx_ = [v.co.x for v in fc.verts]
                fy_ = [v.co.y for v in fc.verts]
                if max(fx_) < gb[0] or min(fx_) > gb[1] or max(fy_) < gb[2] or min(fy_) > gb[3]:
                    kill.append(fc)
            bmesh.ops.delete(bm, geom=kill, context='FACES')
            if bm.faces:
                bm.to_mesh(gmesh)
                made = True
            bm.free()
        if not made:
            z0 = min(pos0[o.name].z for o in moving) - 0.12 * k
            bm = bmesh.new()
            vs = [bm.verts.new((x, y, z0)) for (x, y) in ((gb[0], gb[2]), (gb[1], gb[2]), (gb[1], gb[3]), (gb[0], gb[3]))]
            bm.faces.new(vs)
            bm.to_mesh(gmesh)
            bm.free()
        # 切り出した範囲の外へ飛んだタイヤの受け止め用に、まわりに広い平面（切り出した地面の一番低い高さ）を足す
        zmin = min(v.co.z for v in gmesh.vertices)
        cmesh = bpy.data.meshes.new("CPB_バリヤ用の受け止め面")
        bm = bmesh.new()
        big = 500.0 * k
        cx0, cy0 = (gb[0] + gb[1]) / 2, (gb[2] + gb[3]) / 2
        vs = [bm.verts.new((cx0 + dx * big, cy0 + dy * big, zmin - 0.02 * k)) for dx, dy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        bm.faces.new(vs)
        bm.to_mesh(cmesh)
        bm.free()
        cobj = bpy.data.objects.new("CPB_バリヤ用の受け止め面", cmesh)
        scene.collection.objects.link(cobj)
        cobj.hide_render = True
        gobj = bpy.data.objects.new("CPB_バリヤ用の地面", gmesh)
        scene.collection.objects.link(gobj)
        gobj.hide_render = True
        gobj.display_type = 'WIRE'
        bpy.context.view_layer.update()

        if scene.rigidbody_world is None:
            with bpy.context.temp_override(scene=scene):
                bpy.ops.rigidbody.world_add()
        rbw = scene.rigidbody_world
        rbw.enabled = True
        if rbw.collection is None:
            rbw.collection = bpy.data.collections.new("RigidBodyWorld")
        fa = max(f0, hit_f if hit_f is not None else f0)
        rbw.point_cache.frame_start = fa
        rbw.point_cache.frame_end = f1
        if hasattr(rbw, "substeps_per_frame"):
            rbw.substeps_per_frame = 15
        rbw.solver_iterations = 10
        g_prev = tuple(scene.gravity)
        scene.gravity = (0.0, 0.0, -9.81 * k)

        def add_rb(o, kind):
            with bpy.context.temp_override(object=o, active_object=o, selected_objects=[o]):
                if o.rigid_body is None:
                    bpy.ops.rigidbody.object_add(type=kind)
            return o.rigid_body

        rb = add_rb(gobj, 'PASSIVE')
        rb.collision_shape = 'MESH'
        rb.friction = 0.8
        rb = add_rb(cobj, 'PASSIVE')
        rb.collision_shape = 'MESH'
        rb.friction = 0.8
        rb = add_rb(proxy, 'PASSIVE')
        rb.kinematic = True
        rb.collision_shape = 'CONVEX_HULL'
        rb.friction = 0.6
        rb.restitution = 0.3
        for o in fixed:
            rb = add_rb(o, 'PASSIVE')
            rb.collision_shape = 'CYLINDER'
            rb.friction = s.barrier_friction
        for o in moving:
            rb = add_rb(o, 'ACTIVE')
            rb.collision_shape = 'CYLINDER'
            rb.mass = s.barrier_tire_mass
            rb.friction = s.barrier_friction
            rb.restitution = s.barrier_bounce
            rb.linear_damping = 0.05
            rb.angular_damping = 0.1
            rb.use_deactivation = True
            rb.use_start_deactivated = True
            rb.collision_margin = 0.01 * k
        rbw.point_cache.frame_start = fa
        rbw.point_cache.frame_end = f1
        # フレームを順に進めて剛体の位置を記録（Blender の bake_to_keyframes は画面が必要なので使わない）
        rec = {o.name: ([], []) for o in moving}
        prev_e = {o.name: None for o in moving}
        frames = []
        prev = None
        still = 0
        scene.frame_set(fa)
        for f in range(fa, f1 + 1):
            scene.frame_set(f)
            cur = []
            for o in moving:
                M = o.matrix_world
                cur.append(M.translation.copy())
                if o.parent is not None:
                    M = (o.parent.matrix_world @ o.matrix_parent_inverse).inverted() @ M
                loc, q, _sc = M.decompose()
                e = q.to_euler('XYZ', prev_e[o.name]) if prev_e[o.name] else q.to_euler('XYZ')
                prev_e[o.name] = e
                rec[o.name][0].append(tuple(loc))
                rec[o.name][1].append(tuple(e))
            frames.append(f)
            # タイヤが止まり、車が離れたら打ち切る（以降は最後の位置のまま）
            if prev is not None and f - fa > 36:
                mv = max((a - b).length for a, b in zip(cur, prev))
                still = still + 1 if mv < 0.002 * k else 0
                far = True
                if car_pos:
                    i_ = f - f0
                    if 0 <= i_ < len(car_pos):
                        cp = car_pos[i_]
                        far = all((c_.x - cp[0]) ** 2 + (c_.y - cp[1]) ** 2 > reach for c_ in cur)
                if still >= 12 and far:
                    break
            prev = cur
        # 地面より下に入ったタイヤ（車体と地面に挟まれて抜けることがある）は、その場で地面に寝かせて止める
        gbm = bmesh.new()
        gbm.from_mesh(gmesh)
        gtree = BVHTree.FromBMesh(gbm)
        gbm.free()
        gtop = max(v.co.z for v in gmesh.vertices) + 50.0 * k
        sunk = 0
        for o in moving:
            if o.parent is not None:
                continue
            locs, rots = rec[o.name]
            half = o.dimensions.z * 0.5
            for i_, (x_, y_, z_) in enumerate(locs):
                hit = gtree.ray_cast(Vector((x_, y_, gtop)), Vector((0, 0, -1)))
                gz_ = hit[0].z if hit[0] is not None else zmin
                if gz_ is not None and z_ < gz_ - 0.05 * k:
                    rest = (x_, y_, gz_ + half)
                    yaw_ = rots[i_][2]
                    for j_ in range(i_, len(locs)):
                        locs[j_] = rest
                        rots[j_] = (0.0, 0.0, yaw_)
                    sunk += 1
                    break
        if sunk:
            print("CPB: 地面に入ったタイヤ %d本を地面の上に止めました" % sunk)
        # 後片付け（タイヤはキーフレームになったので剛体の設定は外す）
        for o in moving + fixed + [proxy, gobj, cobj]:
            if o.rigid_body is not None:
                with bpy.context.temp_override(object=o, active_object=o, selected_objects=[o]):
                    bpy.ops.rigidbody.object_remove()
        bpy.data.objects.remove(gobj)
        bpy.data.meshes.remove(gmesh)
        bpy.data.objects.remove(cobj)
        bpy.data.meshes.remove(cmesh)
        scene.gravity = g_prev
        for o in moving:
            o.rotation_mode = 'XYZ'
            _write_channels(o, frames, {"location": rec[o.name][0], "rotation_euler": rec[o.name][1]})
        scene.frame_set(f0)
        return len(moving)

    def _scale_res(res, k):
        if k == 1.0:
            return res
        out = []
        for st in res:
            st2 = dict(st)
            o, p_ = st["origin"], st["pos"]
            st2["origin"] = (o[0] * k, o[1] * k, o[2] * k)
            st2["pos"] = (p_[0] * k, p_[1] * k, p_[2] * k)
            st2["dz"] = [d * k for d in st["dz"]]
            out.append(st2)
        return out

    def _scale_shape(P, k):
        if P.body_points:
            P.body_points = [(x / k, y / k, z / k) for (x, y, z) in P.body_points]
        if P.body_box is not None:
            P.body_box = tuple(v / k for v in P.body_box)

    def _scaled_fns(k, hfn, grip, wall, near):
        """シミュレーション（メートル）⇔ シーン（モデル単位）の変換"""
        h2 = g2 = w2 = n2 = None
        if hfn is not None:
            def h2(x, y):
                z = hfn(x * k, y * k)
                return None if z is None else z / k
        if grip is not None:
            def g2(x, y):
                return grip(x * k, y * k)
        if wall is not None:
            def w2(x, y, z):
                r = wall(x * k, y * k, z * k)
                return None if r is None else (r[0] / k, r[1], r[2], r[3])

            def n2(x, y, z, r):
                return near(x * k, y * k, z * k, r * k)
        return h2, g2, w2, n2

    def _anim_sampler(scene):
        """シーンの cpb.* プロパティに打たれたキーを読む"""
        fcs = {}
        ad = scene.animation_data
        if ad and ad.action:
            for fc in ad.action.fcurves:
                if fc.data_path.startswith("cpb."):
                    fcs[fc.data_path[4:]] = fc
        s = scene.cpb

        def get(name, frame):
            fc = fcs.get(name)
            return fc.evaluate(frame) if fc is not None else getattr(s, name)
        return get, fcs

    def _capture_rest(objs):
        for o in objs:
            o[REST_KEY] = _mat_to_list(o.matrix_world)

    def _remove_keys(obj, paths=("location", "rotation_euler")):
        ad = obj.animation_data
        if ad and ad.action:
            act = ad.action
            for fc in [fc for fc in act.fcurves if fc.data_path in paths]:
                act.fcurves.remove(fc)

    def _write_channels(obj, frames, channels):
        """channels: {data_path: [フレームごとの値タプル]}"""
        ad = obj.animation_data or obj.animation_data_create()
        if ad.action is None:
            ad.action = bpy.data.actions.new(obj.name + "_CarPhysics")
        _remove_keys(obj, tuple(channels.keys()))
        act = ad.action
        for path, data in channels.items():
            for i in range(len(data[0])):
                fc = act.fcurves.new(path, index=i, action_group="CarPhysics")
                fc.keyframe_points.add(len(frames))
                co = []
                for f, v in zip(frames, data):
                    co.extend((f, v[i]))
                fc.keyframe_points.foreach_set("co", co)
                for kp in fc.keyframe_points:
                    kp.interpolation = 'LINEAR'
                fc.update()

    def _to_basis(obj, W, sim_worlds):
        if obj.parent is None:
            return W
        pw = sim_worlds.get(obj.parent.name, obj.parent.matrix_world)
        return (pw @ obj.matrix_parent_inverse).inverted() @ W

    def _make_trajectory(scene, pts):
        cu = bpy.data.curves.get(TRAJ_NAME)
        if cu is None:
            cu = bpy.data.curves.new(TRAJ_NAME, 'CURVE')
            cu.dimensions = '3D'
        cu.splines.clear()
        if len(cu.materials):
            cu.materials.clear()
            cu.bevel_depth = 0.0
        sp = cu.splines.new('POLY')
        sp.points.add(len(pts) - 1)
        sp.points.foreach_set("co", [c for p in pts for c in (p[0], p[1], p[2], 1.0)])
        ob = bpy.data.objects.get(TRAJ_NAME)
        if ob is None:
            ob = bpy.data.objects.new(TRAJ_NAME, cu)
            scene.collection.objects.link(ob)
            ob.hide_render = True
            ob.hide_select = True
        return ob

    SPEED_COLORS = [(0.1, 0.3, 1.0), (0.1, 0.7, 1.0), (0.1, 0.9, 0.5), (0.5, 0.95, 0.1),
                    (0.95, 0.9, 0.1), (1.0, 0.6, 0.1), (1.0, 0.3, 0.1), (0.9, 0.05, 0.05)]

    def _make_trajectory_colored(scene, cars):
        """速度で色分けした軌跡（青=遅い → 赤=速い）。cars: [[(x,y,z,速度), ...], ...]"""
        allv = [p[3] for pts in cars for p in pts]
        vmin, vmax = min(allv), max(allv)
        span = max(vmax - vmin, 0.1)
        cu = bpy.data.curves.get(TRAJ_NAME)
        if cu is None:
            cu = bpy.data.curves.new(TRAJ_NAME, 'CURVE')
            cu.dimensions = '3D'
        cu.splines.clear()
        cu.materials.clear()
        cu.bevel_depth = 0.06
        for k, col in enumerate(SPEED_COLORS):
            name = "CPB_速度色_%d" % k
            m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
            m.diffuse_color = col + (1.0,)
            cu.materials.append(m)
        nb = len(SPEED_COLORS)
        for pts in cars:
            run = []
            band = None
            for p in pts:
                b = min(int((p[3] - vmin) / span * nb), nb - 1)
                if band is None or b == band:
                    run.append(p)
                    band = b
                    continue
                run.append(p)
                _add_poly(cu, run, band)
                run = [p]
                band = b
            if len(run) > 1:
                _add_poly(cu, run, band)
        ob = bpy.data.objects.get(TRAJ_NAME)
        if ob is None:
            ob = bpy.data.objects.new(TRAJ_NAME, cu)
            scene.collection.objects.link(ob)
            ob.hide_render = True
            ob.hide_select = True
        return vmin, vmax

    def _add_poly(cu, run, band):
        sp = cu.splines.new('POLY')
        sp.points.add(len(run) - 1)
        sp.points.foreach_set("co", [c for p in run for c in (p[0], p[1], p[2], 1.0)])
        sp.material_index = band

    def _remove_trajectory():
        ob = bpy.data.objects.get(TRAJ_NAME)
        if ob is not None:
            bpy.data.objects.remove(ob)
        cu = bpy.data.curves.get(TRAJ_NAME)
        if cu is not None and cu.users == 0:
            bpy.data.curves.remove(cu)

    def _remove_object(name):
        ob = bpy.data.objects.get(name)
        if ob is not None:
            data = ob.data
            bpy.data.objects.remove(ob)
            if data is not None and data.users == 0:
                if isinstance(data, bpy.types.Mesh):
                    bpy.data.meshes.remove(data)

    # ---------------- 対象（オブジェクト or アーマチュアのボーン） ----------------

    class _Tgt:
        def __init__(self, obj, bone=None):
            self.obj = obj
            self.bone = bone

        @property
        def key(self):
            return self.obj.name if self.bone is None else "%s:%s" % (self.obj.name, self.bone)

        def has_rest(self):
            if self.bone is None:
                return REST_KEY in self.obj
            d = self.obj.get(REST_BONES)
            return d is not None and self.bone in d

        def world(self):
            if self.bone is None:
                return self.obj.matrix_world.copy()
            return self.obj.matrix_world @ self.obj.pose.bones[self.bone].matrix

        def capture(self):
            if self.bone is None:
                self.obj[REST_KEY] = _mat_to_list(self.obj.matrix_world)
            else:
                if self.obj.get(REST_BONES) is None:
                    self.obj[REST_BONES] = {}
                self.obj[REST_BONES][self.bone] = _mat_to_list(self.world())

        def rest(self):
            if self.bone is None:
                return _list_to_mat(list(self.obj[REST_KEY]))
            return _list_to_mat(list(self.obj[REST_BONES][self.bone]))

        def paths(self):
            if self.bone is None:
                return ("location", "rotation_euler")
            b = bpy.utils.escape_identifier(self.bone)
            return ('pose.bones["%s"].location' % b, 'pose.bones["%s"].rotation_euler' % b)

        def remove_keys(self):
            _remove_keys(self.obj, self.paths())

        def restore(self):
            if not self.has_rest():
                return
            if self.bone is None:
                self.obj.matrix_world = self.rest()
            else:
                pb = self.obj.pose.bones[self.bone]
                pb.matrix = self.obj.matrix_world.inverted() @ self.rest()

        def set_rotation_mode(self):
            if self.bone is None:
                self.obj.rotation_mode = 'XYZ'
            else:
                self.obj.pose.bones[self.bone].rotation_mode = 'XYZ'

        def basis(self, W, sim_worlds, pose_cache):
            if self.bone is None:
                return _to_basis(self.obj, W, sim_worlds)
            arm = self.obj
            b = arm.data.bones[self.bone]
            Mp = arm.matrix_world.inverted() @ W
            pose_cache[self.bone] = Mp
            if b.parent is None:
                return b.matrix_local.inverted() @ Mp
            pp = pose_cache.get(b.parent.name)
            if pp is None:
                pp = arm.pose.bones[b.parent.name].matrix
            return (pp @ b.parent.matrix_local.inverted() @ b.matrix_local).inverted() @ Mp

        def write(self, frames, locs, rots):
            self.set_rotation_mode()
            p_loc, p_rot = self.paths()
            _write_channels(self.obj, frames, {p_loc: locs, p_rot: rots})

        def radius_guess(self):
            if self.bone is None:
                return max(self.obj.dimensions) * 0.5
            return None

    # ---------------- 手付けアニメの読み取り ----------------

    def _eval_source_world(body, action, rotmode, frame):
        def ev(path, idx, default):
            fc = action.fcurves.find(path, index=idx)
            return fc.evaluate(frame) if fc is not None else default
        loc = Vector([ev("location", i, body.location[i]) for i in range(3)])
        scl = Vector([ev("scale", i, body.scale[i]) for i in range(3)])
        if rotmode == 'QUATERNION':
            from mathutils import Quaternion
            q = Quaternion([ev("rotation_quaternion", i, body.rotation_quaternion[i]) for i in range(4)])
            Rm = q.normalized().to_matrix().to_4x4()
        elif rotmode == 'AXIS_ANGLE':
            aa = [ev("rotation_axis_angle", i, body.rotation_axis_angle[i]) for i in range(4)]
            Rm = Matrix.Rotation(aa[0], 4, Vector(aa[1:]))
        else:
            from mathutils import Euler
            Rm = Euler([ev("rotation_euler", i, body.rotation_euler[i]) for i in range(3)], rotmode).to_matrix().to_4x4()
        B = Matrix.Translation(loc) @ Rm @ Matrix.Diagonal(scl.to_4d())
        if body.parent is not None:
            return body.parent.matrix_world @ body.matrix_parent_inverse @ B
        return B

    def _keyed_source(body):
        """手付けアニメ（元のアクション）を取得。初回は今のアクションを元として保存"""
        name = body.get(SRC_KEY)
        if name and name in bpy.data.actions:
            return bpy.data.actions[name], body.get(SRC_ROT, 'XYZ')
        ad = body.animation_data
        if ad is None or ad.action is None or not any(
                fc.data_path in ("location", "rotation_euler", "rotation_quaternion") for fc in ad.action.fcurves):
            raise _BakeError("手付けモード: ボディに位置・回転のキーフレームがありません")
        src = ad.action.copy()
        src.name = ad.action.name + "_手付け元"
        src.use_fake_user = True
        body[SRC_KEY] = src.name
        body[SRC_ROT] = body.rotation_mode
        return src, body.rotation_mode

    # ---------------- ジオメトリーノード ----------------

    def _sock(sockets, name):
        for sk in sockets:
            if sk.name == name and sk.enabled:
                return sk
        return sockets[name]

    def _new_gn(name):
        ng = bpy.data.node_groups.get(name)
        if ng is not None:
            bpy.data.node_groups.remove(ng)
        ng = bpy.data.node_groups.new(name, 'GeometryNodeTree')
        ng.interface.new_socket(name="Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
        ng.interface.new_socket(name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
        gi = ng.nodes.new('NodeGroupInput')
        go = ng.nodes.new('NodeGroupOutput')
        return ng, gi, go

    def _gn_attr(ng, name, dtype='FLOAT'):
        n = ng.nodes.new('GeometryNodeInputNamedAttribute')
        n.data_type = dtype
        n.inputs['Name'].default_value = name
        return _sock(n.outputs, 'Attribute')

    def _gn_math(ng, op, a, b=None):
        n = ng.nodes.new('ShaderNodeMath')
        n.operation = op
        for k, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                n.inputs[k].default_value = v
            else:
                ng.links.new(v, n.inputs[k])
        return n.outputs[0]

    def _gn_compare(ng, op, a, b):
        n = ng.nodes.new('FunctionNodeCompare')
        n.data_type = 'FLOAT'
        n.operation = op
        ins = [sk for sk in n.inputs if sk.enabled]
        for k, v in enumerate((a, b)):
            if isinstance(v, (int, float)):
                ins[k].default_value = v
            else:
                ng.links.new(v, ins[k])
        return n.outputs[0]

    def _reveal_group():
        """面の cpb_frame が今のフレームより後なら消す（タイヤ痕が走った後に現れる）"""
        ng, gi, go = _new_gn("CPB_出現")
        fr = _gn_attr(ng, "cpb_frame")
        t = ng.nodes.new('GeometryNodeInputSceneTime')
        cmp = _gn_compare(ng, 'GREATER_THAN', fr, t.outputs['Frame'])
        dl = ng.nodes.new('GeometryNodeDeleteGeometry')
        dl.domain = 'FACE'
        ng.links.new(gi.outputs[0], dl.inputs['Geometry'])
        ng.links.new(cmp, dl.inputs['Selection'])
        ng.links.new(dl.outputs[0], go.inputs[0])
        return ng

    def _smoke_group(life, size, grow, rise, opacity, mat):
        ng, gi, go = _new_gn("CPB_スモーク")
        t = ng.nodes.new('GeometryNodeInputSceneTime')
        age = _gn_math(ng, 'SUBTRACT', t.outputs['Seconds'], _gn_attr(ng, "cpb_birth"))
        dead = ng.nodes.new('FunctionNodeBooleanMath')
        dead.operation = 'OR'
        ng.links.new(_gn_compare(ng, 'LESS_THAN', age, 0.0), dead.inputs[0])
        ng.links.new(_gn_compare(ng, 'GREATER_THAN', age, life), dead.inputs[1])
        dl = ng.nodes.new('GeometryNodeDeleteGeometry')
        dl.domain = 'POINT'
        ng.links.new(gi.outputs[0], dl.inputs['Geometry'])
        ng.links.new(dead.outputs[0], dl.inputs['Selection'])
        # 位置: 風に流されながら上昇
        vs = ng.nodes.new('ShaderNodeVectorMath')
        vs.operation = 'SCALE'
        ng.links.new(_gn_attr(ng, "cpb_vel", 'FLOAT_VECTOR'), vs.inputs[0])
        ng.links.new(age, _sock(vs.inputs, 'Scale'))
        cz = ng.nodes.new('ShaderNodeCombineXYZ')
        ng.links.new(_gn_math(ng, 'MULTIPLY', age, rise), cz.inputs['Z'])
        va = ng.nodes.new('ShaderNodeVectorMath')
        va.operation = 'ADD'
        ng.links.new(vs.outputs[0], va.inputs[0])
        ng.links.new(cz.outputs[0], va.inputs[1])
        spn = ng.nodes.new('GeometryNodeSetPosition')
        ng.links.new(dl.outputs[0], spn.inputs['Geometry'])
        ng.links.new(va.outputs[0], spn.inputs['Offset'])
        # 透明度: だんだん薄く
        strength = _gn_attr(ng, "cpb_strength")
        fade = _gn_math(ng, 'SUBTRACT', 1.0, _gn_math(ng, 'DIVIDE', age, life))
        alpha = _gn_math(ng, 'MULTIPLY', _gn_math(ng, 'MULTIPLY', fade, strength), opacity)
        sa = ng.nodes.new('GeometryNodeStoreNamedAttribute')
        sa.data_type = 'FLOAT'
        sa.domain = 'POINT'
        sa.inputs['Name'].default_value = "cpb_alpha"
        ng.links.new(spn.outputs[0], sa.inputs['Geometry'])
        ng.links.new(alpha, _sock(sa.inputs, 'Value'))
        # 大きさ: だんだん広がる
        sz = _gn_math(ng, 'MULTIPLY', _gn_math(ng, 'ADD', size, _gn_math(ng, 'MULTIPLY', age, grow)),
                      _gn_math(ng, 'SQRT', strength))
        ico = ng.nodes.new('GeometryNodeMeshIcoSphere')
        ico.inputs['Radius'].default_value = 1.0
        ico.inputs['Subdivisions'].default_value = 2
        inst = ng.nodes.new('GeometryNodeInstanceOnPoints')
        ng.links.new(sa.outputs[0], inst.inputs['Points'])
        ng.links.new(ico.outputs[0], inst.inputs['Instance'])
        ng.links.new(sz, inst.inputs['Scale'])
        rz = ng.nodes.new('GeometryNodeRealizeInstances')
        ng.links.new(inst.outputs[0], rz.inputs[0])
        sm = ng.nodes.new('GeometryNodeSetMaterial')
        sm.inputs['Material'].default_value = mat
        ng.links.new(rz.outputs[0], sm.inputs['Geometry'])
        ng.links.new(sm.outputs[0], go.inputs[0])
        return ng

    def _gn_input(ng, name, kind, default, mn=None, mx=None):
        """モディファイアーの欄に出る入力を作る（焼き込み後も手で直せるように）"""
        sk = ng.interface.new_socket(name=name, in_out='INPUT', socket_type=kind)
        sk.default_value = default
        if mn is not None:
            sk.min_value = mn
        if mx is not None:
            sk.max_value = mx
        return sk

    def _gn_frame_seconds(ng, fps):
        """シーンの時刻（秒）。スローモーションのサブフレームでもなめらかに動く"""
        tm = ng.nodes.new('GeometryNodeInputSceneTime')
        return tm.outputs['Seconds']

    def _gn_random(ng, seed):
        n = ng.nodes.new('FunctionNodeRandomValue')
        n.data_type = 'FLOAT'
        _sock(n.inputs, 'Seed').default_value = seed
        return _sock(n.outputs, 'Value')

    def _gn_triangles(ng, points, size):
        """点ごとに正三角形を置く。三角形はカメラの方を向き、点ごとに少し回す"""
        tri = ng.nodes.new('GeometryNodeMeshCircle')
        tri.fill_type = 'NGON'
        tri.inputs['Vertices'].default_value = 3
        tri.inputs['Radius'].default_value = 1.0
        cam = ng.nodes.new('GeometryNodeInputActiveCamera')
        oi = ng.nodes.new('GeometryNodeObjectInfo')
        oi.transform_space = 'RELATIVE'
        ng.links.new(cam.outputs[0], oi.inputs['Object'])
        pos = ng.nodes.new('GeometryNodeInputPosition')
        to_cam = ng.nodes.new('ShaderNodeVectorMath')
        to_cam.operation = 'SUBTRACT'
        ng.links.new(oi.outputs['Location'], to_cam.inputs[0])
        ng.links.new(pos.outputs[0], to_cam.inputs[1])
        al = ng.nodes.new('FunctionNodeAlignEulerToVector')
        al.axis = 'Z'
        ng.links.new(to_cam.outputs[0], al.inputs['Vector'])
        inst = ng.nodes.new('GeometryNodeInstanceOnPoints')
        ng.links.new(points, inst.inputs['Points'])
        ng.links.new(tri.outputs['Mesh'], inst.inputs['Instance'])
        ng.links.new(al.outputs[0], inst.inputs['Rotation'])
        ng.links.new(size, inst.inputs['Scale'])
        spin = ng.nodes.new('ShaderNodeCombineXYZ')
        ng.links.new(_gn_math(ng, 'MULTIPLY', _gn_random(ng, 23), 6.2832), spin.inputs['Z'])
        rot = ng.nodes.new('GeometryNodeRotateInstances')
        ng.links.new(inst.outputs[0], rot.inputs['Instances'])
        ng.links.new(spin.outputs[0], rot.inputs['Rotation'])
        rz = ng.nodes.new('GeometryNodeRealizeInstances')
        ng.links.new(rot.outputs[0], rz.inputs[0])
        return rz.outputs[0]

    def _gn_store_color(ng, geo, color):
        sa = ng.nodes.new('GeometryNodeStoreNamedAttribute')
        sa.data_type = 'FLOAT_COLOR'
        sa.domain = 'POINT'
        sa.inputs['Name'].default_value = "cpb_col"
        ng.links.new(geo, sa.inputs['Geometry'])
        ng.links.new(color, _sock(sa.inputs, 'Value'))
        return sa.outputs[0]

    def _flat_material(name, strength):
        """単色（光の当たり方に左右されない）。色は点ごとの cpb_col"""
        m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
        m.use_nodes = True
        nt = m.node_tree
        nt.nodes.clear()
        out = nt.nodes.new('ShaderNodeOutputMaterial')
        em = nt.nodes.new('ShaderNodeEmission')
        em.name = em.label = "単色（明るさは Strength）"
        em.inputs['Strength'].default_value = strength
        at = nt.nodes.new('ShaderNodeAttribute')
        at.attribute_type = 'GEOMETRY'
        at.attribute_name = "cpb_col"
        nt.links.new(at.outputs['Color'], em.inputs['Color'])
        nt.links.new(em.outputs[0], out.inputs['Surface'])
        if hasattr(m, "shadow_method"):
            m.shadow_method = 'NONE'
        m.diffuse_color = (1.0, 1.0, 1.0, 1.0)
        return m

    def _tri_smoke_group(mat, fps):
        ng, gi, go = _new_gn("CPB_スモーク（三角）")
        _gn_input(ng, "大きさ", 'NodeSocketFloat', 0.18, 0.0)
        _gn_input(ng, "量", 'NodeSocketFloat', 0.5, 0.0, 1.0)
        _gn_input(ng, "消えるまで (秒)", 'NodeSocketFloat', 1.2, 0.05)
        _gn_input(ng, "流れる速さ", 'NodeSocketFloat', 1.0, 0.0)
        _gn_input(ng, "上昇 (m/s)", 'NodeSocketFloat', 0.4)
        _gn_input(ng, "色", 'NodeSocketColor', (1.0, 1.0, 1.0, 1.0))
        age = _gn_math(ng, 'SUBTRACT', _gn_frame_seconds(ng, fps), _gn_attr(ng, "cpb_birth"))
        life = gi.outputs["消えるまで (秒)"]
        d1 = ng.nodes.new('FunctionNodeBooleanMath')
        d1.operation = 'OR'
        ng.links.new(_gn_compare(ng, 'LESS_THAN', age, 0.0), d1.inputs[0])
        ng.links.new(_gn_compare(ng, 'GREATER_THAN', age, life), d1.inputs[1])
        d2 = ng.nodes.new('FunctionNodeBooleanMath')
        d2.operation = 'OR'
        ng.links.new(d1.outputs[0], d2.inputs[0])
        ng.links.new(_gn_compare(ng, 'GREATER_THAN', _gn_random(ng, 7), gi.outputs["量"]), d2.inputs[1])
        dl = ng.nodes.new('GeometryNodeDeleteGeometry')
        dl.domain = 'POINT'
        ng.links.new(gi.outputs[0], dl.inputs['Geometry'])
        ng.links.new(d2.outputs[0], dl.inputs['Selection'])
        vs = ng.nodes.new('ShaderNodeVectorMath')
        vs.operation = 'SCALE'
        ng.links.new(_gn_attr(ng, "cpb_vel", 'FLOAT_VECTOR'), vs.inputs[0])
        ng.links.new(_gn_math(ng, 'MULTIPLY', age, gi.outputs["流れる速さ"]), _sock(vs.inputs, 'Scale'))
        cz = ng.nodes.new('ShaderNodeCombineXYZ')
        ng.links.new(_gn_math(ng, 'MULTIPLY', age, gi.outputs["上昇 (m/s)"]), cz.inputs['Z'])
        va = ng.nodes.new('ShaderNodeVectorMath')
        va.operation = 'ADD'
        ng.links.new(vs.outputs[0], va.inputs[0])
        ng.links.new(cz.outputs[0], va.inputs[1])
        spn = ng.nodes.new('GeometryNodeSetPosition')
        ng.links.new(dl.outputs[0], spn.inputs['Geometry'])
        ng.links.new(va.outputs[0], spn.inputs['Offset'])
        # 大きさ: 出てすぐ大きくなり、少しずつ広がって、最後は縮んで消える
        tt = _gn_math(ng, 'DIVIDE', age, life)
        up = _gn_math(ng, 'MINIMUM', _gn_math(ng, 'DIVIDE', tt, 0.15), 1.0)
        down = _gn_math(ng, 'MINIMUM', _gn_math(ng, 'DIVIDE', _gn_math(ng, 'SUBTRACT', 1.0, tt), 0.35), 1.0)
        grow = _gn_math(ng, 'ADD', 0.6, _gn_math(ng, 'MULTIPLY', tt, 0.8))
        sz = _gn_math(ng, 'MULTIPLY', _gn_math(ng, 'MULTIPLY', up, down), grow)
        sz = _gn_math(ng, 'MULTIPLY', sz, _gn_math(ng, 'SQRT', _gn_attr(ng, "cpb_strength")))
        sz = _gn_math(ng, 'MULTIPLY', sz, gi.outputs["大きさ"])
        col = _gn_store_color(ng, spn.outputs[0], gi.outputs["色"])
        tri = _gn_triangles(ng, col, sz)
        sm = ng.nodes.new('GeometryNodeSetMaterial')
        sm.inputs['Material'].default_value = mat
        ng.links.new(tri, sm.inputs['Geometry'])
        ng.links.new(sm.outputs[0], go.inputs[0])
        return ng

    def _tri_spark_group(g, mat, fps):
        ng, gi, go = _new_gn("CPB_火花（三角）")
        _gn_input(ng, "大きさ", 'NodeSocketFloat', 0.05, 0.0)
        _gn_input(ng, "量", 'NodeSocketFloat', 0.5, 0.0, 1.0)
        _gn_input(ng, "色1（オレンジ）", 'NodeSocketColor', (1.0, 0.45, 0.08, 1.0))
        _gn_input(ng, "色2（黄色）", 'NodeSocketColor', (1.0, 0.82, 0.12, 1.0))
        _gn_input(ng, "色2の割合", 'NodeSocketFloat', 0.7, 0.0, 1.0)
        _gn_input(ng, "寿命の倍率", 'NodeSocketFloat', 1.0, 0.05)
        age = _gn_math(ng, 'SUBTRACT', _gn_frame_seconds(ng, fps), _gn_attr(ng, "cpb_birth"))
        life = _gn_math(ng, 'MULTIPLY', _gn_attr(ng, "cpb_life"), gi.outputs["寿命の倍率"])
        d1 = ng.nodes.new('FunctionNodeBooleanMath')
        d1.operation = 'OR'
        ng.links.new(_gn_compare(ng, 'LESS_THAN', age, 0.0), d1.inputs[0])
        ng.links.new(_gn_compare(ng, 'GREATER_THAN', age, life), d1.inputs[1])
        d2 = ng.nodes.new('FunctionNodeBooleanMath')
        d2.operation = 'OR'
        ng.links.new(d1.outputs[0], d2.inputs[0])
        ng.links.new(_gn_compare(ng, 'GREATER_THAN', _gn_attr(ng, "cpb_tail"), 0.5), d2.inputs[1])
        d3 = ng.nodes.new('FunctionNodeBooleanMath')
        d3.operation = 'OR'
        ng.links.new(d2.outputs[0], d3.inputs[0])
        ng.links.new(_gn_compare(ng, 'GREATER_THAN', _gn_random(ng, 7), gi.outputs["量"]), d3.inputs[1])
        dl = ng.nodes.new('GeometryNodeDeleteGeometry')
        dl.domain = 'POINT'
        ng.links.new(gi.outputs[0], dl.inputs['Geometry'])
        ng.links.new(d3.outputs[0], dl.inputs['Selection'])
        vs = ng.nodes.new('ShaderNodeVectorMath')
        vs.operation = 'SCALE'
        ng.links.new(_gn_attr(ng, "cpb_vel", 'FLOAT_VECTOR'), vs.inputs[0])
        ng.links.new(age, _sock(vs.inputs, 'Scale'))
        cz = ng.nodes.new('ShaderNodeCombineXYZ')
        ng.links.new(_gn_math(ng, 'MULTIPLY', _gn_math(ng, 'MULTIPLY', age, age), -0.5 * g), cz.inputs['Z'])
        va = ng.nodes.new('ShaderNodeVectorMath')
        va.operation = 'ADD'
        ng.links.new(vs.outputs[0], va.inputs[0])
        ng.links.new(cz.outputs[0], va.inputs[1])
        spn = ng.nodes.new('GeometryNodeSetPosition')
        ng.links.new(dl.outputs[0], spn.inputs['Geometry'])
        ng.links.new(va.outputs[0], spn.inputs['Offset'])
        sz = _gn_math(ng, 'MULTIPLY', gi.outputs["大きさ"],
                      _gn_math(ng, 'SUBTRACT', 1.0, _gn_math(ng, 'DIVIDE', age, life)))
        mix = ng.nodes.new('ShaderNodeMix')
        mix.data_type = 'RGBA'
        pick = _gn_compare(ng, 'LESS_THAN', _gn_random(ng, 11), gi.outputs["色2の割合"])
        ng.links.new(pick, mix.inputs['Factor'])
        ng.links.new(gi.outputs["色1（オレンジ）"], _sock(mix.inputs, 'A'))
        ng.links.new(gi.outputs["色2（黄色）"], _sock(mix.inputs, 'B'))
        col = _gn_store_color(ng, spn.outputs[0], _sock(mix.outputs, 'Result'))
        tri = _gn_triangles(ng, col, sz)
        sm = ng.nodes.new('GeometryNodeSetMaterial')
        sm.inputs['Material'].default_value = mat
        ng.links.new(tri, sm.inputs['Geometry'])
        ng.links.new(sm.outputs[0], go.inputs[0])
        return ng

    def _set_mod_inputs(mod, values):
        """モディファイアーの入力に、パネルの設定値を初期値として入れる"""
        for it in mod.node_group.interface.items_tree:
            if getattr(it, "item_type", "") == 'SOCKET' and it.in_out == 'INPUT' and it.name in values:
                v = values[it.name]
                mod[it.identifier] = tuple(v) + (1.0,) if isinstance(v, (tuple, list)) and len(v) == 3 else v

    def _alpha_material(name, color, attr, opacity_mult=1.0):
        m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
        m.use_nodes = True
        nt = m.node_tree
        nt.nodes.clear()
        out = nt.nodes.new('ShaderNodeOutputMaterial')
        bs = nt.nodes.new('ShaderNodeBsdfPrincipled')
        bs.inputs['Base Color'].default_value = tuple(color) + (1.0,)
        bs.inputs['Roughness'].default_value = 1.0
        at = nt.nodes.new('ShaderNodeAttribute')
        at.attribute_type = 'GEOMETRY'
        at.attribute_name = attr
        mul = nt.nodes.new('ShaderNodeMath')
        mul.operation = 'MULTIPLY'
        mul.inputs[1].default_value = opacity_mult
        mul.use_clamp = True
        nt.links.new(at.outputs['Fac'], mul.inputs[0])
        nt.links.new(mul.outputs[0], bs.inputs['Alpha'])
        nt.links.new(bs.outputs[0], out.inputs['Surface'])
        if hasattr(m, "blend_method"):
            m.blend_method = 'BLEND'
        if hasattr(m, "shadow_method"):
            m.shadow_method = 'NONE'
        if hasattr(m, "surface_render_method"):
            m.surface_render_method = 'BLENDED'
        m.diffuse_color = tuple(color) + (0.6,)
        return m

    def _new_mesh_object(scene, name, verts, faces):
        _remove_object(name)
        me = bpy.data.meshes.new(name)
        me.from_pydata(verts, [], faces)
        me.update()
        ob = bpy.data.objects.new(name, me)
        scene.collection.objects.link(ob)
        return ob

    # ---------------- 演出: タイヤ痕・スモーク ----------------

    def _build_skids(scene, s, cars, hfn, fps, f0):
        verts, faces, frs, sts = [], [], [], []
        for car in cars:
            slip = compute_slip(car["res"], car["wpos"], car["radii"], fps, hfn, None)
            hw = car["tire_w"] * 0.5
            kk = car.get("k", 1.0)
            if kk != 1.0:
                slip = [[(k_, (p_[0] * kk, p_[1] * kk, p_[2] * kk), d_) for (k_, p_, d_) in row] for row in slip]
            for i in range(4):
                prev = None
                for f, row in enumerate(slip):
                    k, p, _d = row[i]
                    if k > s.skid_threshold:
                        if prev is not None:
                            pk, pp = prev
                            dx, dy = p[0] - pp[0], p[1] - pp[1]
                            dl = math.hypot(dx, dy)
                            if dl > 1e-4:
                                nx, ny = -dy / dl * hw, dx / dl * hw
                                a_ = len(verts)
                                zo = 0.012 * kk
                                verts += [(pp[0] + nx, pp[1] + ny, pp[2] + zo), (pp[0] - nx, pp[1] - ny, pp[2] + zo),
                                          (p[0] - nx, p[1] - ny, p[2] + zo), (p[0] + nx, p[1] + ny, p[2] + zo)]
                                faces.append((a_, a_ + 1, a_ + 2, a_ + 3))
                                frs.append(float(f0 + f))
                                sts.append(max(k, pk))
                        prev = (k, p)
                    else:
                        prev = None
        _remove_object(SKID_NAME)
        if not faces:
            return 0
        ob = _new_mesh_object(scene, SKID_NAME, verts, faces)
        me = ob.data
        a = me.attributes.new("cpb_frame", 'FLOAT', 'FACE')
        a.data.foreach_set("value", frs)
        a = me.attributes.new("cpb_strength", 'FLOAT', 'FACE')
        a.data.foreach_set("value", sts)
        me.materials.append(_alpha_material("CPB_タイヤ痕", (0.015, 0.015, 0.015), "cpb_strength", s.skid_opacity))
        mod = ob.modifiers.new("CPB_出現", 'NODES')
        mod.node_group = _reveal_group()
        ob.hide_select = True
        return len(faces)

    def _build_smoke(scene, s, cars, hfn, fps, f0, contacts=None):
        import random
        rng = random.Random(1234)
        verts, birth, strength, vel = [], [], [], []
        kk = cars[0].get("k", 1.0) if cars else 1.0
        for car in cars:
            res = car["res"]
            slip = compute_slip(res, car["wpos"], car["radii"], fps, hfn, None)
            n = len(res)
            for f, row in enumerate(slip):
                a_, b_ = res[max(f - 1, 0)]["pos"], res[min(f + 1, n - 1)]["pos"]
                span = max(min(f + 1, n - 1) - max(f - 1, 0), 1) / fps
                cv = ((b_[0] - a_[0]) / span, (b_[1] - a_[1]) / span)
                for i in range(4):
                    k, p, _d = row[i]
                    if k <= s.smoke_threshold:
                        continue
                    cnt = max(1, int(round(k * s.smoke_amount * 3)))
                    for c in range(cnt):
                        verts.append(((p[0] + rng.uniform(-0.2, 0.2)) * kk, (p[1] + rng.uniform(-0.2, 0.2)) * kk,
                                      (p[2] + 0.15) * kk))
                        birth.append((f0 + f + c / cnt) / fps)
                        strength.append(k)
                        vel.extend(((cv[0] * 0.2 + rng.uniform(-0.6, 0.6)) * kk,
                                    (cv[1] * 0.2 + rng.uniform(-0.6, 0.6)) * kk, rng.uniform(0.0, 0.3) * kk))
        # 車体が壁・地面・バリヤ・他の車に当たった所からも煙（衝撃が強いほど多い）
        if contacts:
            res_c, impacts, mass = contacts
            thr = mass * 0.006
            for (f, pt, imp, nrm) in impacts:
                imp = imp / kk
                if imp < thr or f >= len(res_c):
                    continue
                st = res_c[f]
                o_, R_ = st["origin"], st["R"]
                w_ = (o_[0] + R_[0][0] * pt[0] + R_[0][1] * pt[1] + R_[0][2] * pt[2],
                      o_[1] + R_[1][0] * pt[0] + R_[1][1] * pt[1] + R_[1][2] * pt[2],
                      o_[2] + R_[2][0] * pt[0] + R_[2][1] * pt[1] + R_[2][2] * pt[2])
                cnt = min(5, 1 + int(imp / (mass * 0.03)))
                for c in range(cnt):
                    verts.append((w_[0] + rng.uniform(-0.2, 0.2) * kk, w_[1] + rng.uniform(-0.2, 0.2) * kk, w_[2]))
                    birth.append((f0 + f + c / cnt) / fps)
                    strength.append(min(1.0, 0.5 + imp / (mass * 0.2)))
                    vel.extend((rng.uniform(-0.8, 0.8) * kk, rng.uniform(-0.8, 0.8) * kk, rng.uniform(0.2, 0.8) * kk))
        _remove_object(SMOKE_NAME)
        if not verts:
            return 0
        ob = _new_mesh_object(scene, SMOKE_NAME, verts, [])
        me = ob.data
        for nm, data, typ in (("cpb_birth", birth, 'FLOAT'), ("cpb_strength", strength, 'FLOAT'),
                              ("cpb_vel", vel, 'FLOAT_VECTOR')):
            at = me.attributes.new(nm, typ, 'POINT')
            at.data.foreach_set("vector" if typ == 'FLOAT_VECTOR' else "value", data)
        if s.particle_style == 'TRIANGLE':
            mod = ob.modifiers.new("CPB_スモーク（三角）", 'NODES')
            mod.node_group = _tri_smoke_group(_flat_material("CPB_スモーク（三角）", 1.0), fps)
            _set_mod_inputs(mod, {"大きさ": s.smoke_size * 0.6 * kk, "量": s.tri_smoke_keep,
                                  "消えるまで (秒)": s.smoke_life * 0.75, "流れる速さ": 1.0,
                                  "上昇 (m/s)": s.smoke_rise * kk, "色": tuple(s.smoke_color)})
            ob.hide_select = True
            return len(verts)
        mat = _alpha_material("CPB_スモーク", tuple(s.smoke_color), "cpb_alpha", 1.0)
        mod = ob.modifiers.new("CPB_スモーク", 'NODES')
        mod.node_group = _smoke_group(s.smoke_life, s.smoke_size * kk, s.smoke_grow * kk, s.smoke_rise * kk,
                                      s.smoke_opacity, mat)
        ob.hide_select = True
        return len(verts)

    # ---------------- 演出: 火花 ----------------

    def _spark_group(g, radius, mat):
        """2点の線（頭と尾）を放物線で飛ばし、細い筒にして光らせる"""
        ng, gi, go = _new_gn("CPB_火花")
        t = ng.nodes.new('GeometryNodeInputSceneTime')
        age = _gn_math(ng, 'SUBTRACT', t.outputs['Seconds'], _gn_attr(ng, "cpb_birth"))
        life = _gn_attr(ng, "cpb_life")
        dead = ng.nodes.new('FunctionNodeBooleanMath')
        dead.operation = 'OR'
        ng.links.new(_gn_compare(ng, 'LESS_THAN', age, 0.0), dead.inputs[0])
        ng.links.new(_gn_compare(ng, 'GREATER_THAN', age, life), dead.inputs[1])
        dl = ng.nodes.new('GeometryNodeDeleteGeometry')
        dl.domain = 'POINT'
        ng.links.new(gi.outputs[0], dl.inputs['Geometry'])
        ng.links.new(dead.outputs[0], dl.inputs['Selection'])
        te = _gn_math(ng, 'MAXIMUM', _gn_math(ng, 'SUBTRACT', age,
                                              _gn_math(ng, 'MULTIPLY', _gn_attr(ng, "cpb_tail"), 0.03)), 0.0)
        vs = ng.nodes.new('ShaderNodeVectorMath')
        vs.operation = 'SCALE'
        ng.links.new(_gn_attr(ng, "cpb_vel", 'FLOAT_VECTOR'), vs.inputs[0])
        ng.links.new(te, _sock(vs.inputs, 'Scale'))
        cz = ng.nodes.new('ShaderNodeCombineXYZ')
        ng.links.new(_gn_math(ng, 'MULTIPLY', _gn_math(ng, 'MULTIPLY', te, te), -0.5 * g), cz.inputs['Z'])
        va = ng.nodes.new('ShaderNodeVectorMath')
        va.operation = 'ADD'
        ng.links.new(vs.outputs[0], va.inputs[0])
        ng.links.new(cz.outputs[0], va.inputs[1])
        spn = ng.nodes.new('GeometryNodeSetPosition')
        ng.links.new(dl.outputs[0], spn.inputs['Geometry'])
        ng.links.new(va.outputs[0], spn.inputs['Offset'])
        alpha = _gn_math(ng, 'SUBTRACT', 1.0, _gn_math(ng, 'DIVIDE', age, life))
        sa = ng.nodes.new('GeometryNodeStoreNamedAttribute')
        sa.data_type = 'FLOAT'
        sa.domain = 'POINT'
        sa.inputs['Name'].default_value = "cpb_alpha"
        ng.links.new(spn.outputs[0], sa.inputs['Geometry'])
        ng.links.new(alpha, _sock(sa.inputs, 'Value'))
        m2c = ng.nodes.new('GeometryNodeMeshToCurve')
        ng.links.new(sa.outputs[0], m2c.inputs['Mesh'])
        prof = ng.nodes.new('GeometryNodeCurvePrimitiveCircle')
        prof.inputs['Resolution'].default_value = 4
        prof.inputs['Radius'].default_value = radius
        c2m = ng.nodes.new('GeometryNodeCurveToMesh')
        ng.links.new(m2c.outputs[0], c2m.inputs['Curve'])
        ng.links.new(prof.outputs['Curve'], c2m.inputs['Profile Curve'])
        sm = ng.nodes.new('GeometryNodeSetMaterial')
        sm.inputs['Material'].default_value = mat
        ng.links.new(c2m.outputs[0], sm.inputs['Geometry'])
        ng.links.new(sm.outputs[0], go.inputs[0])
        return ng

    def _spark_material(color):
        m = bpy.data.materials.get("CPB_火花") or bpy.data.materials.new("CPB_火花")
        m.use_nodes = True
        nt = m.node_tree
        nt.nodes.clear()
        out = nt.nodes.new('ShaderNodeOutputMaterial')
        em = nt.nodes.new('ShaderNodeEmission')
        em.inputs['Color'].default_value = tuple(color) + (1.0,)
        at = nt.nodes.new('ShaderNodeAttribute')
        at.attribute_type = 'GEOMETRY'
        at.attribute_name = "cpb_alpha"
        mul = nt.nodes.new('ShaderNodeMath')
        mul.operation = 'MULTIPLY'
        mul.inputs[1].default_value = 25.0
        nt.links.new(at.outputs['Fac'], mul.inputs[0])
        nt.links.new(mul.outputs[0], em.inputs['Strength'])
        tr = nt.nodes.new('ShaderNodeBsdfTransparent')
        mx = nt.nodes.new('ShaderNodeMixShader')
        nt.links.new(at.outputs['Fac'], mx.inputs['Fac'])
        nt.links.new(tr.outputs[0], mx.inputs[1])
        nt.links.new(em.outputs[0], mx.inputs[2])
        nt.links.new(mx.outputs[0], out.inputs['Surface'])
        if hasattr(m, "blend_method"):
            m.blend_method = 'BLEND'
        if hasattr(m, "shadow_method"):
            m.shadow_method = 'NONE'
        if hasattr(m, "surface_render_method"):
            m.surface_render_method = 'BLENDED'
        m.diffuse_color = tuple(color) + (1.0,)
        return m

    def _build_sparks(scene, s, res, impacts, mass, k, hfn, box, fps, f0):
        """車体が壁・地面・他の車に当たった所と、車体の底が路面に擦れた所から火花"""
        import random
        rng = random.Random(4321)
        verts, edges, birth, life, vel, tail = [], [], [], [], [], []
        n = len(res)
        amt = s.spark_amount

        def car_vel(f):
            a_, b_ = res[max(f - 1, 0)]["pos"], res[min(f + 1, n - 1)]["pos"]
            span = max(min(f + 1, n - 1) - max(f - 1, 0), 1) / fps
            return ((b_[0] - a_[0]) / span, (b_[1] - a_[1]) / span)

        def emit(p, f, cnt, cv, nrm=(0.0, 0.0)):
            for _c in range(cnt):
                t0 = (f0 + f + rng.random()) / fps
                sp = rng.uniform(0.35, 0.95)
                v_ = (cv[0] * sp + (rng.uniform(-2.5, 2.5) + nrm[0] * 2.0) * k,
                      cv[1] * sp + (rng.uniform(-2.5, 2.5) + nrm[1] * 2.0) * k,
                      rng.uniform(0.8, 3.5) * k)
                lf = rng.uniform(0.2, 0.55)
                q = (p[0] + rng.uniform(-0.06, 0.06) * k, p[1] + rng.uniform(-0.06, 0.06) * k, p[2])
                for tl in (0.0, 1.0):
                    verts.append(q)
                    birth.append(t0)
                    life.append(lf)
                    vel.extend(v_)
                    tail.append(tl)
                edges.append((len(verts) - 2, len(verts) - 1))

        # 1) 衝突（壁・バリヤ・他の車・横転中の地面）
        thr = mass * 0.004
        for (f, pt, imp, nrm) in impacts:
            imp_s = imp / k
            if imp_s < thr or f >= n:
                continue
            st = res[f]
            o_, R_ = st["origin"], st["R"]
            w_ = (o_[0] + R_[0][0] * pt[0] + R_[0][1] * pt[1] + R_[0][2] * pt[2],
                  o_[1] + R_[1][0] * pt[0] + R_[1][1] * pt[1] + R_[1][2] * pt[2],
                  o_[2] + R_[2][0] * pt[0] + R_[2][1] * pt[1] + R_[2][2] * pt[2])
            nw = (R_[0][0] * nrm[0] + R_[0][1] * nrm[1] + R_[0][2] * nrm[2],
                  R_[1][0] * nrm[0] + R_[1][1] * nrm[1] + R_[1][2] * nrm[2])
            cnt = int(min(14.0, 1.0 + imp_s / (mass * 0.01)) * amt)
            if cnt > 0:
                emit(w_, f, cnt, car_vel(f), nw)
        # 2) 車体の底が路面に擦れた（底付き）
        if hfn is not None and box is not None:
            bx0, bx1, by0, by1, bz0 = box[0], box[1], box[2], box[3], box[4]
            pts = [(x_ * k, y_ * k, bz0 * k) for x_ in (bx0 * 0.85, (bx0 + bx1) * 0.5, bx1 * 0.85)
                   for y_ in (by0 * 0.8, (by0 + by1) * 0.5, by1 * 0.8)]
            cl0 = s.spark_clearance * k
            for f, st in enumerate(res):
                if st["speed"] < 3.0 or st["R"][2][2] < 0.5:
                    continue
                o_, R_ = st["origin"], st["R"]
                for q in pts:
                    wx = o_[0] + R_[0][0] * q[0] + R_[0][1] * q[1] + R_[0][2] * q[2]
                    wy = o_[1] + R_[1][0] * q[0] + R_[1][1] * q[1] + R_[1][2] * q[2]
                    wz = o_[2] + R_[2][0] * q[0] + R_[2][1] * q[1] + R_[2][2] * q[2]
                    gz = hfn(wx, wy)
                    if gz is None or wz - gz >= cl0:
                        continue
                    depth = (cl0 - (wz - gz)) / k
                    cnt = int(min(10.0, 2.0 + depth * 150.0) * amt)
                    if cnt > 0:
                        emit((wx, wy, gz + 0.01 * k), f, cnt, car_vel(f))
        _remove_object(SPARK_NAME)
        if not edges:
            return 0
        _remove_object(SPARK_NAME)
        me = bpy.data.meshes.new(SPARK_NAME)
        me.from_pydata(verts, edges, [])
        me.update()
        ob = bpy.data.objects.new(SPARK_NAME, me)
        scene.collection.objects.link(ob)
        for nm, data, typ in (("cpb_birth", birth, 'FLOAT'), ("cpb_life", life, 'FLOAT'), ("cpb_tail", tail, 'FLOAT'),
                              ("cpb_vel", vel, 'FLOAT_VECTOR')):
            at = me.attributes.new(nm, typ, 'POINT')
            at.data.foreach_set("vector" if typ == 'FLOAT_VECTOR' else "value", data)
        if s.particle_style == 'TRIANGLE':
            mod = ob.modifiers.new("CPB_火花（三角）", 'NODES')
            mod.node_group = _tri_spark_group(9.81 * k, _flat_material("CPB_火花（三角）", 4.0), fps)
            _set_mod_inputs(mod, {"大きさ": s.spark_size * k, "量": s.tri_spark_keep,
                                  "色1（オレンジ）": tuple(s.spark_color), "色2（黄色）": tuple(s.spark_color2),
                                  "色2の割合": s.spark_ratio2, "寿命の倍率": 1.0})
            ob.hide_select = True
            return len(edges)
        mod = ob.modifiers.new("CPB_火花", 'NODES')
        mod.node_group = _spark_group(9.81 * k, 0.012 * k, _spark_material(s.spark_color))
        ob.hide_select = True
        return len(edges)

    # ---------------- 演出: パーツが外れる ----------------

    def _part_objects(s):
        if s.parts_collection is None:
            return []
        return [o for o in s.parts_collection.all_objects if o.parent is not None]

    def _restore_parts(s):
        for o in _part_objects(s):
            if PART_REST not in o:
                o[PART_REST] = _mat_to_list(o.matrix_basis)
                o[PART_ROT] = o.rotation_mode
                continue
            _remove_keys(o, ("location", "rotation_euler", "rotation_quaternion", "scale"))
            o.rotation_mode = o.get(PART_ROT, o.rotation_mode)
            o.matrix_basis = _list_to_mat(list(o[PART_REST]))

    def _detach_parts(scene, s, body_obj, rel_body, res, impacts, mass, k, hfn, f0, f1, fps):
        """強い衝撃を受けた近くのパーツを外して、飛ばして転がす（キーフレームに焼き込み）"""
        import random
        from mathutils import Matrix
        rng = random.Random(777)
        desc_ = set(body_obj.children_recursive)
        parts = [o for o in _part_objects(s) if o in desc_]
        if not parts:
            return 0
        scene.frame_set(f0)
        binv = body_obj.matrix_world.inverted()
        info_ = {}
        for o in parts:
            cs = [o.matrix_world @ Vector(c) for c in o.bound_box]
            cw = sum(cs, Vector()) / 8.0
            rad = max((c - cw).length for c in cs)
            info_[o] = (rel_body @ (binv @ cw), rad)
        thr = mass * k * 0.8 / max(s.parts_strength, 0.01)
        by_f = {}
        for (f, pt, imp, nrm) in impacts:
            by_f.setdefault(f, []).append((Vector(pt), imp, nrm))
        det = {}
        for f in sorted(by_f):
            for o in parts:
                if o in det:
                    continue
                c, rad = info_[o]
                hits = [(imp, nrm) for (pt, imp, nrm) in by_f[f] if (pt - c).length < rad + 0.4 * k]
                tot = sum(h_[0] for h_ in hits)
                if tot >= thr:
                    det[o] = (f, max(hits, key=lambda h_: h_[0])[1])
        if not det:
            return 0
        fmin = max(min(fd for fd, _ in det.values()) - 1, 0)
        pm = {o: {} for o in det}
        att = {o: {} for o in det}
        for fr in range(f0 + fmin, f1 + 1):
            scene.frame_set(fr)
            for o, (fd, _) in det.items():
                pm[o][fr] = (o.parent.matrix_world @ o.matrix_parent_inverse).copy()
                if fr <= f0 + fd:
                    att[o][fr] = o.matrix_world.copy()
        dt = 1.0 / (fps * 4)
        g = 9.81 * k
        z_fallback = min(st["pos"][2] for st in res) - 0.3 * k
        for o, (fd, nrm) in det.items():
            fa = f0 + fd
            M0 = att[o][fa]
            Mp = att[o].get(fa - 1, M0)
            cl = sum((Vector(c) for c in o.bound_box), Vector()) / 8.0
            corners = [Vector(c) - cl for c in o.bound_box]
            Rw = M0.to_3x3()
            pos = M0 @ cl
            v = (M0.translation - Mp.translation) * fps
            Rb = Matrix(res[min(fd, len(res) - 1)]["R"])
            nw = Rb @ Vector(nrm)
            v += nw * rng.uniform(1.5, 3.0) * k + Vector((rng.uniform(-1, 1), rng.uniform(-1, 1),
                                                          rng.uniform(1.5, 3.5))) * k
            w = Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1)))
            w = w.normalized() * rng.uniform(5.0, 12.0) if w.length > 1e-6 else Vector((0, 0, 8.0))
            rot_keep = o.rotation_mode
            o.rotation_mode = 'QUATERNION'
            frames, locs, quats, scales = [], [], [], []
            rest = _list_to_mat(list(o[PART_REST]))
            l0, q0, s0 = rest.decompose()
            frames.append(fa - 1)
            locs.append(tuple(l0))
            quats.append(tuple(q0))
            scales.append(tuple(s0))
            qprev = q0
            for fr in range(fa, f1 + 1):
                Mw = Matrix.Translation(pos) @ Rw.to_4x4() @ Matrix.Translation(-cl)
                B = pm[o][fr].inverted() @ Mw
                l_, q_, s_ = B.decompose()
                if q_.dot(qprev) < 0:
                    q_ = -q_
                qprev = q_
                frames.append(fr)
                locs.append(tuple(l_))
                quats.append(tuple(q_))
                scales.append(tuple(s_))
                for _ in range(4):
                    v.z -= g * dt
                    pos += v * dt
                    ang = w.length * dt
                    if ang > 1e-9:
                        Rw = Matrix.Rotation(ang, 3, w.normalized()) @ Rw
                    gz = hfn(pos.x, pos.y) if hfn is not None else None
                    if gz is None:
                        gz = z_fallback
                    low = min((Rw @ c_).z for c_ in corners)
                    pen = gz - (pos.z + low)
                    if pen > 0.0:
                        pos.z += pen
                        if v.z < 0.0:
                            v.z = -v.z * s.parts_bounce
                        fr_ = max(0.0, 1.0 - 5.0 * dt)
                        v.x *= fr_
                        v.y *= fr_
                        w *= max(0.0, 1.0 - 4.0 * dt)
            _write_channels(o, frames, {"location": locs, "rotation_quaternion": quats, "scale": scales})
            if rot_keep != 'QUATERNION' and PART_ROT not in o:
                o[PART_ROT] = rot_keep
        return len(det)

    # ---------------- 演出: へこみ ----------------

    def _remove_dents(body):
        if body is None or body.type != 'MESH' or body.data.shape_keys is None:
            return
        kb = body.data.shape_keys.key_blocks
        for k in [k for k in kb if k.name.startswith(DENT_PREFIX)]:
            body.shape_key_remove(k)
        ad = body.data.shape_keys.animation_data if body.data.shape_keys else None
        if ad and ad.action:
            for fc in [fc for fc in ad.action.fcurves if DENT_PREFIX in fc.data_path]:
                ad.action.fcurves.remove(fc)

    def _build_dents(body, rel_body, impacts, mass, s, f0, kk=1.0):
        _remove_dents(body)
        if body.type != 'MESH' or not impacts:
            return 0
        thr = mass * s.dent_threshold
        cand = sorted([im for im in impacts if im[2] > thr], key=lambda im: -im[2])
        chosen = []
        for im in cand:
            if all((Vector(im[1]) - Vector(c[1])).length > s.dent_radius * 0.8 for c in chosen):
                chosen.append(im)
            if len(chosen) >= s.dent_max:
                break
        if not chosen:
            return 0
        chosen.sort(key=lambda im: im[0])
        if body.data.shape_keys is None:
            body.shape_key_add(name="Basis", from_mix=False)
        inv = rel_body.inverted()
        inv3 = inv.to_3x3()
        co = [v.co.copy() for v in body.data.vertices]
        for k, (f, pt, imp, nrm) in enumerate(chosen):
            depth = min(s.dent_depth_max, imp / kk / mass * 0.12 * s.dent_strength) * kk
            c_local = inv @ Vector(pt)
            d_local = inv3 @ Vector(nrm)
            r_local = s.dent_radius * (d_local.length or 1.0) / max(Vector(nrm).length, 1e-6)
            if d_local.length > 0:
                d_local.normalize()
            kb = body.shape_key_add(name="%s_%02d" % (DENT_PREFIX, k + 1), from_mix=False)
            sc = (inv3 @ Vector((1, 0, 0))).length
            rr = s.dent_radius * kk * sc
            for i, v in enumerate(co):
                dist = (v - c_local).length
                if dist < rr:
                    w = (1.0 - dist / rr) ** 2
                    kb.data[i].co = v + d_local * depth * sc * w
            kb.value = 0.0
            kb.keyframe_insert("value", frame=f0 + f - 1)
            kb.value = 1.0
            kb.keyframe_insert("value", frame=f0 + f)
        return len(chosen)

    # ---------------- 演出: 揺れもの ----------------

    def _jiggle_objects(s):
        if not s.use_jiggle or s.jiggle_collection is None:
            return []
        return [o for o in s.jiggle_collection.all_objects]

    # ---------------- テイク ----------------

    def _save_take(s, objs, label):
        idx = len(s.takes) + 1
        entries = []
        for o in objs:
            ad = o.animation_data
            if ad is None or ad.action is None:
                continue
            cp = ad.action.copy()
            cp.name = "CPBテイク%02d_%s" % (idx, o.name)
            cp.use_fake_user = True
            entries.append("%s=%s" % (o.name, cp.name))
        it = s.takes.add()
        it.name = "テイク%02d  %s" % (idx, label)
        it.entries = "\n".join(entries)
        s.take_index = len(s.takes) - 1

    # ---------------- プロパティ ----------------

    def _poll_mesh(self, o):
        return o.type == 'MESH'

    def _poll_curve(self, o):
        return o.type == 'CURVE'

    def _poll_arm(self, o):
        return o.type == 'ARMATURE'

    def _poll_empty_or_any(self, o):
        return True

    class CPB_TimingItem(bpy.types.PropertyGroup):
        marker: PointerProperty(name="地点", type=bpy.types.Object,
                                description="この地点（エンプティなど）を通過させたい")
        frame: IntProperty(name="フレーム", default=100)

    class CPB_CarItem(bpy.types.PropertyGroup):
        body: PointerProperty(name="ボディ", type=bpy.types.Object)
        wheel_fl: PointerProperty(name="前左", type=bpy.types.Object)
        wheel_fr: PointerProperty(name="前右", type=bpy.types.Object)
        wheel_rl: PointerProperty(name="後左", type=bpy.types.Object)
        wheel_rr: PointerProperty(name="後右", type=bpy.types.Object)
        path: PointerProperty(name="コース", type=bpy.types.Object, poll=_poll_curve,
                              description="空欄なら1台目と同じコース")
        lane_offset: FloatProperty(name="車線ずらし", default=0.0, unit='LENGTH',
                                   description="コースから横にずらして走る（左が＋）")
        start_frame: IntProperty(name="発進フレーム", default=1)
        speed_mult: FloatProperty(name="速さ倍率", default=1.0, min=0.1, max=3.0,
                                  description="最高速度・加速に掛ける倍率")
        start_speed: FloatProperty(name="初速 (km/h)", default=0.0, min=0.0)
        overtake: BoolProperty(name="追い越す", default=True,
                               description="前の車が遅いと横にずれて追い越す")
        avoid: BoolProperty(name="前の車を避ける", default=True,
                            description="切ると車間を取らずに突っ込む（車同士の衝突と組み合わせてクラッシュに）")
        spin: BoolProperty(name="スピン", default=False)
        spin_frame: IntProperty(name="スピン開始フレーム", default=100)

    class CPB_TakeItem(bpy.types.PropertyGroup):
        entries: StringProperty()

    class CPB_Settings(bpy.types.PropertyGroup):
        # クルマ
        body: PointerProperty(name="ボディ", type=bpy.types.Object)
        wheel_fl: PointerProperty(name="前左", type=bpy.types.Object)
        wheel_fr: PointerProperty(name="前右", type=bpy.types.Object)
        wheel_rl: PointerProperty(name="後左", type=bpy.types.Object)
        wheel_rr: PointerProperty(name="後右", type=bpy.types.Object)
        forward_axis: EnumProperty(name="車の正面", default="NEG_Y", items=[
            ("NEG_Y", "-Y", ""), ("POS_Y", "+Y", ""), ("NEG_X", "-X", ""), ("POS_X", "+X", "")],
            description="基準ポーズのときクルマの正面が向いているワールド軸")
        wheel_radius: FloatProperty(name="タイヤ半径", default=0.0, min=0.0, unit='LENGTH',
                                    description="0 = タイヤの寸法から自動")
        model_scale: FloatProperty(name="モデルの縮尺", default=1.0, min=0.01, max=1000.0,
                                   description="モデルが実物の何倍の大きさで作られているか（1 = 実寸）。物理はメートルで計算し、表示はこの倍率で拡大する")
        preset: EnumProperty(name="プリセット", default="CUSTOM", update=_apply_preset, items=[
            ("CUSTOM", "カスタム", ""), ("SEDAN", "一般車", ""), ("SPORTS", "スポーツカー", ""),
            ("LUXURY", "高級セダン（柔らかめ）", ""), ("SUV", "SUV", ""),
            ("RALLY", "ラリー（砂利）", ""), ("TRUCK", "トラック", "")])

        # 運転方法
        drive_mode: EnumProperty(name="運転方法", default="PATH", items=[
            ("PATH", "コース自動走行", "カーブに沿って自動で運転"),
            ("MANUAL", "キー入力で運転", "ハンドル・アクセル・ブレーキにキーを打って運転"),
            ("KEYED", "手付けに後付け", "ボディに付けた位置・回転のキーはそのまま、サスペンション・タイヤ・ハンドルを物理で付ける")])
        assist: BoolProperty(name="運転アシスト", default=True,
                             description="トラクションコントロール・ABS・横滑り防止。切ると挙動がシビアになり、スピンしやすい")
        path: PointerProperty(name="コース", type=bpy.types.Object, poll=_poll_curve)
        ground: PointerProperty(name="地面", type=bpy.types.Object, poll=_poll_mesh,
                                description="空欄ならカーブの高さを使用")
        road_noise: FloatProperty(name="路面の荒れ", default=0.0, min=0.0, max=0.2, unit='LENGTH',
                                  description="細かい凹凸の高さ。舗装 0.005 / 荒れた道 0.02 / 砂利 0.03〜")
        use_scene_range: BoolProperty(name="シーンのフレーム範囲を使う", default=True)
        frame_start: IntProperty(name="開始", default=1)
        frame_end: IntProperty(name="終了", default=250)
        show_trajectory: BoolProperty(name="走行軌跡を表示", default=True)
        traj_speed_color: BoolProperty(name="軌跡を速度で色分け", default=False,
                                       description="青=遅い → 赤=速い（ソリッド表示で見える）")
        lane_offset: FloatProperty(name="車線ずらし", default=0.0, unit='LENGTH',
                                   description="コースから横にずらして走る（左が＋）")

        # 走り
        top_speed: FloatProperty(name="最高速度 (km/h)", default=100.0, min=1.0)
        start_speed: FloatProperty(name="初速 (km/h)", default=0.0, min=0.0)
        start_frame: IntProperty(name="発進フレーム", default=1,
                                 description="このフレームまで停車して待つ")
        stop_at_end: BoolProperty(name="終点で停止", default=True)
        corner_use: FloatProperty(name="攻め具合", default=0.75, min=0.1, max=1.0,
                                  description="コーナーでタイヤのグリップを何割使うか")
        accel: FloatProperty(name="加速 (m/s²)", default=4.0, min=0.1)
        brake: FloatProperty(name="ブレーキ (m/s²)", default=7.0, min=0.1)
        mass: FloatProperty(name="車重 (kg)", default=1400.0, min=100.0)
        front_weight: FloatProperty(name="前輪荷重", default=0.55, min=0.2, max=0.8)
        cg_height: FloatProperty(name="重心の高さ", default=0.5, min=0.1, max=2.0, unit='LENGTH')
        mu: FloatProperty(name="グリップ μ", default=1.0, min=0.1, max=2.0,
                          description="乾いた舗装 1.0 / 濡れ 0.7 / 砂利 0.5 / 雪 0.2")
        drive: EnumProperty(name="駆動", default="RWD", items=[
            ("RWD", "FR", "後輪駆動"), ("FWD", "FF", "前輪駆動"), ("AWD", "4WD", "")])
        max_steer: FloatProperty(name="最大舵角 (°)", default=35.0, min=5.0, max=60.0)
        launch_time: FloatProperty(name="スタートの空転 (秒)", default=0.0, min=0.0, max=5.0,
                                   description="発進から指定秒数、後輪を空転させる（ドラッグレース向け。0=なし）。スモークとタイヤ痕も出る")
        launch_slip: FloatProperty(name="空転の強さ (m/s)", default=12.0, min=0.0, max=60.0)
        launch_lift: FloatProperty(name="前の浮き上がり", default=2.0, min=0.0, max=20.0,
                                   description="空転中に加速で前が浮く強さ（ウィリー気味）")
        line_hold: FloatProperty(name="ライン追従の補正", default=0.0, min=0.0, max=3.0,
                                 description="高速の長いコーナーで外へふくらむ時に上げる（0=なし。オーバル向け）")

        # キーを打てる入力（アニメーション可能）
        speed_scale: FloatProperty(name="速度倍率", default=1.0, min=0.0, max=3.0,
                                   description="キーを打つと区間ごとに速さを変えられる（コース自動走行）")
        handbrake: FloatProperty(name="サイドブレーキ", default=0.0, min=0.0, max=1.0,
                                 description="0.5以上で後輪ロック。キーを打つと物理的に横滑り・スピンする")
        in_steer: FloatProperty(name="ハンドル", default=0.0, min=-1.0, max=1.0,
                                description="-1=左いっぱい / +1=右いっぱい")
        in_throttle: FloatProperty(name="アクセル", default=0.0, min=0.0, max=1.0)
        in_brake: FloatProperty(name="ブレーキ", default=0.0, min=0.0, max=1.0)
        in_reverse: FloatProperty(name="バック", default=0.0, min=0.0, max=1.0,
                                  description="0.5以上でバックギア（アクセルで後ろへ進む）")

        # サスペンション
        tire_profile: BoolProperty(name="タイヤの丸みで段差を拾う", default=True,
                                   description="タイヤの真下だけでなく前後の地面も見て、段差の角に乗り上げるようにする")
        body_contact: BoolProperty(name="車体を地面にめり込ませない", default=True,
                                   description="段差や急な起伏で、車体の底やタイヤが地面の下に入らないよう押し上げる")
        susp_freq: FloatProperty(name="サス硬さ (Hz)", default=1.5, min=0.5, max=5.0,
                                 description="小さいほどフワフワ。乗用車 1.0〜1.5 / スポーツ 2.0〜")
        susp_damp: FloatProperty(name="減衰", default=0.5, min=0.05, max=2.0,
                                 description="小さいほど揺れ戻しが多い")
        pitch_mult: FloatProperty(name="ピッチ強調", default=1.0, min=0.0, max=10.0,
                                  description="1.0 = 実車相当。加減速での前後の傾きを何倍にするか")
        roll_mult: FloatProperty(name="ロール強調", default=1.0, min=0.0, max=10.0,
                                 description="1.0 = 実車相当。コーナーでの左右の傾きを何倍にするか")
        travel: FloatProperty(name="ストローク", default=0.12, min=0.01, unit='LENGTH')

        # ドリフト
        drift: BoolProperty(name="ドリフト", default=False)
        drift_angle: FloatProperty(name="ドリフト角 (°)", default=30.0, min=0.0, max=80.0)
        drift_r_start: FloatProperty(name="開始する半径", default=60.0, min=1.0, unit='LENGTH',
                                     description="この半径よりきついコーナーでドリフトし始める")
        drift_r_full: FloatProperty(name="最大になる半径", default=20.0, min=0.5, unit='LENGTH')
        drift_freq: FloatProperty(name="振り出し速さ (Hz)", default=0.8, min=0.1, max=4.0)
        drift_damp: FloatProperty(name="揺り戻し減衰", default=0.4, min=0.05, max=2.0)
        drift_min_speed: FloatProperty(name="最低速度 (km/h)", default=30.0, min=0.0)
        drift_use_range: BoolProperty(name="フレーム範囲を限定", default=False)
        drift_start: IntProperty(name="開始", default=1)
        drift_end: IntProperty(name="終了", default=250)

        # スピン
        spin: BoolProperty(name="スピン", default=False)
        spin_frame: IntProperty(name="スピン開始フレーム", default=100)
        spin_dir: EnumProperty(name="方向", default="AUTO", items=[
            ("AUTO", "自動", "曲がっている方向へ"), ("LEFT", "左", ""), ("RIGHT", "右", "")])
        spin_kick: FloatProperty(name="きっかけ (°/s)", default=90.0, min=0.0, max=720.0)
        spin_grip: FloatProperty(name="後輪グリップ倍率", default=0.6, min=0.05, max=1.0)

        # 横転
        rollover: BoolProperty(name="横転", default=False,
                               description="指定フレームできっかけを与えて横転させる")
        rollover_frame: IntProperty(name="横転開始フレーム", default=120)
        rollover_dir: EnumProperty(name="方向", default="AUTO", items=[
            ("AUTO", "自動", "横滑りしている側／曲がっている外側へ"),
            ("LEFT", "左", "左へ転がる"), ("RIGHT", "右", "右へ転がる")])
        rollover_rate: FloatProperty(name="きっかけ (°/s)", default=250.0, min=0.0, max=1500.0,
                                     description="横転開始時に与える回転の速さ。大きいほど何回も転がる")
        rollover_lift: FloatProperty(name="跳ね上げ (m/s)", default=2.5, min=0.0, max=20.0,
                                     description="横転開始時に与える上向きの速さ")
        rollover_settle: BoolProperty(name="最後は完全に止める", default=True,
                                      description="横転の後、ほぼ止まったらその姿勢で完全に止める（揺れ続けたり、じわじわ滑り続けたりしない）")
        rollover_slide: FloatProperty(name="横滑り", default=0.5, min=0.0, max=1.0,
                                      description="横転開始時に速度の何割を横向きにするか。大きいほど派手に転がる")
        rollover_auto: BoolProperty(name="傾き過ぎたら自動で横転", default=True,
                                    description="ジャンプの着地などで車体が大きく傾いたら、自動で横転の計算に切り替える")
        body_mu: FloatProperty(name="車体の摩擦", default=0.55, min=0.05, max=2.0,
                               description="横転中に車体が地面をこするときの摩擦")

        # 出力
        steering_wheel: PointerProperty(name="ハンドル（室内）", type=bpy.types.Object,
                                        description="車内のステアリングホイール。ボディの子にしておく")
        steer_ratio: FloatProperty(name="ギア比", default=15.0, min=1.0, max=30.0,
                                   description="タイヤの切れ角 × この値 = ハンドルの回転角")
        steer_axis: EnumProperty(name="回転軸", default="Y", items=[
            ("X", "X", ""), ("Y", "Y", ""), ("Z", "Z", "")],
            description="ステアリングホイールのローカル回転軸")
        steer_invert: BoolProperty(name="反転", default=False)
        write_props: BoolProperty(name="速度などをプロパティに出力", default=True,
                                  description="ボディに cpb_speed / cpb_brake などを焼き込む（ブレーキランプのドライバー等に）")

        # ===== 拡張（既定はすべてオフ） =====
        # 到達タイミング
        use_timing: BoolProperty(name="到達タイミング", default=False,
                                 description="指定したフレームに指定した地点を通るよう、速さを自動で合わせる")
        timing_items: CollectionProperty(type=CPB_TimingItem)
        timing_index: IntProperty(default=0)

        # ギア
        use_gears: BoolProperty(name="ギアとエンジン回転数", default=False,
                                description="シフトアップでの一瞬の揺れ、回転数・ギアの出力（cpb_rpm / cpb_gear）")
        gear_count: IntProperty(name="段数", default=6, min=2, max=10)
        shift_rpm: FloatProperty(name="シフトアップ回転数", default=6200.0, min=1500.0, max=12000.0)
        idle_rpm: FloatProperty(name="アイドリング", default=850.0, min=300.0, max=2000.0)
        redline_rpm: FloatProperty(name="レッドゾーン", default=7000.0, min=2000.0, max=15000.0)
        shift_time: FloatProperty(name="変速時間 (秒)", default=0.25, min=0.0, max=1.5)

        # 路面
        use_grip_map: BoolProperty(name="場所ごとの路面", default=False,
                                   description="地面の頂点グループ（ウェイトペイント）で塗った所だけ滑りやすくする")
        grip_vgroup: StringProperty(name="頂点グループ", default="滑りやすさ")
        grip_low: FloatProperty(name="塗った所のグリップ", default=0.3, min=0.02, max=1.0,
                                description="ウェイト1の場所でグリップを何倍にするか（氷 0.1 / 砂利 0.5）")
        # 壁
        use_walls: BoolProperty(name="壁・ガードレール", default=False,
                                description="コレクション内のメッシュにぶつかって跳ね返る")
        wall_collection: PointerProperty(name="壁コレクション", type=bpy.types.Collection)
        wall_mu: FloatProperty(name="壁の摩擦", default=0.4, min=0.0, max=2.0)

        # 複数台
        use_multi: BoolProperty(name="複数台", default=False,
                                description="他の車も同じように走らせる。前の車に追従・追い越しをする")
        cars: CollectionProperty(type=CPB_CarItem)
        car_index: IntProperty(default=0)
        follow_gap: FloatProperty(name="車間 (秒)", default=1.2, min=0.3, max=5.0)
        multi_collide: BoolProperty(name="車同士の衝突", default=False,
                                    description="車同士がぶつかって押し合う（全車を数回計算し直して合わせる）")
        overtake_offset: FloatProperty(name="追い越し幅", default=3.2, min=1.5, max=8.0, unit='LENGTH')
        multi_scatter_lane: FloatProperty(name="横のばらつき", default=0.0, min=0.0, max=10.0,
                                          description="車ごとの車線ずらしに、±この幅のランダムを足す")
        multi_scatter_speed: FloatProperty(name="速さのばらつき (%)", default=0.0, min=0.0, max=30.0,
                                           description="車ごとの速さ倍率に、±この割合のランダムを掛ける")
        multi_scatter_gap: FloatProperty(name="前後のばらつき", default=0.0, min=0.0, max=50.0,
                                         description="車ごとのスタート位置を、コースに沿って 0〜この距離だけ前へずらす")
        multi_scatter_seed: IntProperty(name="乱数の種", default=1, min=0,
                                        description="変えると、ばらけ方が変わる")
        multi_lane_start: BoolProperty(name="最初から車線に並べる", default=False,
                                       description="車線ずらしの位置からスタートする（切ると、コースの始点から車線へ寄っていく）")

        # トレーラー
        use_trailer: BoolProperty(name="トレーラー", default=False,
                                  description="連結した荷台が後ろから付いてくる")
        trailer_body: PointerProperty(name="荷台", type=bpy.types.Object)
        trailer_wheels: PointerProperty(name="荷台のタイヤ", type=bpy.types.Collection,
                                        description="荷台のタイヤだけを入れたコレクション")
        trailer_hitch: PointerProperty(name="連結点", type=bpy.types.Object,
                                       description="空欄なら荷台の一番前の点")

        # タイヤバリヤ
        use_barrier: BoolProperty(name="タイヤバリヤ", default=False,
                                  description="積み上げたタイヤに突っ込むと、車は衝撃を吸収されて止まり、タイヤは飛び散る")
        barrier_collection: PointerProperty(name="バリヤのタイヤ", type=bpy.types.Collection,
                                            description="バリヤのタイヤ（メッシュ）を入れたコレクション")
        barrier_stiff: FloatProperty(name="固さ", default=1.0, min=0.1, max=10.0,
                                     description="大きいほど車が手前で止まる")
        barrier_scatter: BoolProperty(name="タイヤを飛び散らせる", default=True,
                                      description="Blender の剛体シミュレーションでタイヤを動かし、キーフレームに焼き込む")
        barrier_tire_mass: FloatProperty(name="タイヤ1本の重さ (kg)", default=9.0, min=0.5, max=100.0)
        barrier_bounce: FloatProperty(name="弾み", default=0.4, min=0.0, max=1.0)
        barrier_friction: FloatProperty(name="摩擦", default=0.7, min=0.0, max=2.0)
        gen_rows: IntProperty(name="列の数", default=3, min=1, max=8)
        gen_stack: IntProperty(name="積む段数", default=3, min=1, max=8)
        gen_side: EnumProperty(name="トラック側", default="LEFT", items=[
            ("LEFT", "カーブの左", "カーブの進む向きの左側がトラック"),
            ("RIGHT", "カーブの右", "カーブの進む向きの右側がトラック")])
        gen_colors: BoolProperty(name="赤白に塗る", default=True)

        # 演出: タイヤ痕
        use_skid: BoolProperty(name="タイヤ痕", default=False,
                               description="タイヤが滑った所に黒い跡を残す（走った後に現れる）")
        skid_threshold: FloatProperty(name="出始める滑り", default=0.15, min=0.0, max=1.0)
        skid_opacity: FloatProperty(name="濃さ", default=0.8, min=0.05, max=1.0)
        skid_width: FloatProperty(name="幅", default=0.0, min=0.0, unit='LENGTH',
                                  description="0 = タイヤの寸法から自動")
        # 演出: スモーク
        use_smoke: BoolProperty(name="タイヤスモーク・土煙", default=False,
                                description="タイヤが滑った所から煙を出す（レンダー／マテリアル表示で半透明）")
        smoke_threshold: FloatProperty(name="出始める滑り", default=0.25, min=0.0, max=1.0)
        smoke_amount: FloatProperty(name="量", default=0.6, min=0.1, max=5.0)
        smoke_size: FloatProperty(name="大きさ", default=0.3, min=0.05, max=3.0, unit='LENGTH')
        smoke_grow: FloatProperty(name="広がり (m/s)", default=0.6, min=0.0, max=5.0)
        smoke_rise: FloatProperty(name="上昇 (m/s)", default=0.4, min=0.0, max=5.0)
        smoke_life: FloatProperty(name="消えるまで (秒)", default=1.6, min=0.2, max=10.0)
        smoke_opacity: FloatProperty(name="濃さ", default=0.22, min=0.01, max=1.0)
        particle_style: EnumProperty(name="パーティクルの形", default='TRIANGLE', items=[
            ('TRIANGLE', "正三角形（単色）", "スモーク・火花を、カメラを向いた単色の正三角形にする。焼き込み後もモディファイアーの欄で大きさ・量・色を直せる"),
            ('CLASSIC', "従来（煙は半透明の球・火花は光る線）", "")])
        tri_no_blur: BoolProperty(name="三角を筋にしない（モーションブラーを切る）", default=True,
                                  description="Eevee のモーションブラーは粒ごとに切れないため、三角の粒が筋に見えないよう、焼き込み時にシーンのモーションブラーを切る")
        tri_smoke_keep: FloatProperty(name="三角の量（残す割合）", default=0.5, min=0.0, max=1.0,
                                      description="スモークの粒のうち表示する割合（焼き込み後もモディファイアーで変えられる）")
        smoke_color: FloatVectorProperty(name="色", subtype='COLOR', size=3, default=(1.0, 1.0, 1.0),
                                         min=0.0, max=1.0, description="白=タイヤスモーク / 茶色=土煙")
        # 演出: へこみ
        use_dents: BoolProperty(name="横転・衝突のへこみ", default=False,
                                description="地面や壁に強く当たった所の車体をシェイプキーでへこませる")
        dent_strength: FloatProperty(name="強さ", default=1.0, min=0.0, max=5.0)
        dent_radius: FloatProperty(name="範囲", default=0.5, min=0.05, max=3.0, unit='LENGTH')
        dent_depth_max: FloatProperty(name="最大の深さ", default=0.15, min=0.0, max=1.0, unit='LENGTH')
        dent_threshold: FloatProperty(name="へこむ衝撃", default=0.3, min=0.0, max=5.0,
                                      description="1フレームの衝撃が「車重×この値」(N・s) 以上の場所がへこむ。小さいほど、へこむ所が増える")
        dent_max: IntProperty(name="最大数", default=8, min=1, max=40)
        # 演出: 火花
        use_sparks: BoolProperty(name="火花", default=False,
                                 description="車体が壁・地面・他の車に擦れた所や、車体の底が路面に当たった所から火花を飛ばす")
        spark_amount: FloatProperty(name="量", default=1.0, min=0.1, max=10.0)
        spark_clearance: FloatProperty(name="底が擦れる高さ (m)", default=0.03, min=0.0, max=0.5,
                                       description="車体の底と路面の隙間がこれより小さいと火花が出る")
        spark_color: FloatVectorProperty(name="色", subtype='COLOR', size=3, default=(1.0, 0.45, 0.08),
                                         min=0.0, max=1.0)
        spark_color2: FloatVectorProperty(name="色2", subtype='COLOR', size=3, default=(1.0, 0.82, 0.12),
                                          min=0.0, max=1.0, description="三角の火花のもう一つの色（黄色）")
        spark_ratio2: FloatProperty(name="色2の割合", default=0.7, min=0.0, max=1.0,
                                    description="三角の火花のうち、色2（黄色）にする割合")
        spark_size: FloatProperty(name="三角の大きさ", default=0.05, min=0.005, max=1.0, unit='LENGTH')
        tri_spark_keep: FloatProperty(name="三角の量（残す割合）", default=0.5, min=0.0, max=1.0,
                                      description="火花の粒のうち表示する割合（焼き込み後もモディファイアーで変えられる）")
        # 演出: パーツが外れる
        use_parts: BoolProperty(name="パーツが外れる", default=False,
                                description="強くぶつかった所の近くのパーツ（バンパー・ミラーなど）が外れて転がる")
        parts_collection: PointerProperty(name="外れるパーツ", type=bpy.types.Collection,
                                          description="ボディの子にしたパーツを入れる")
        parts_strength: FloatProperty(name="外れやすさ", default=1.0, min=0.05, max=20.0)
        parts_bounce: FloatProperty(name="跳ね返り", default=0.3, min=0.0, max=0.9)
        # 演出: 揺れもの
        use_jiggle: BoolProperty(name="揺れもの", default=False,
                                 description="アンテナ・荷物・運転手の頭などを加速度に合わせて揺らす")
        jiggle_collection: PointerProperty(name="揺らすもの", type=bpy.types.Collection,
                                           description="ボディの子にしたオブジェクトを入れる（原点が揺れの支点）")
        jiggle_freq: FloatProperty(name="揺れの速さ (Hz)", default=2.0, min=0.2, max=10.0)
        jiggle_damp: FloatProperty(name="減衰", default=0.25, min=0.02, max=2.0)
        jiggle_amount: FloatProperty(name="揺れの大きさ", default=1.0, min=0.0, max=10.0)
        # 演出: ライト
        brake_lights: PointerProperty(name="ブレーキランプ", type=bpy.types.Collection)
        reverse_lights: PointerProperty(name="バックランプ", type=bpy.types.Collection)
        light_strength: FloatProperty(name="光の強さ", default=8.0, min=0.0, max=200.0)

        # リグ（アーマチュア）
        use_armature: BoolProperty(name="リグ（アーマチュア）に焼き込む", default=False,
                                   description="オブジェクトではなく、アーマチュアのボーンにキーを打つ")
        armature: PointerProperty(name="アーマチュア", type=bpy.types.Object, poll=_poll_arm)
        bone_body: StringProperty(name="ボディ")
        bone_fl: StringProperty(name="前左")
        bone_fr: StringProperty(name="前右")
        bone_rl: StringProperty(name="後左")
        bone_rr: StringProperty(name="後右")
        bone_steer: StringProperty(name="室内ハンドル")
        collision_mesh: PointerProperty(name="当たり判定メッシュ", type=bpy.types.Object, poll=_poll_mesh,
                                        description="横転の当たり判定に使う車体メッシュ（空欄なら箱形）")

        # カメラ
        cam_type: EnumProperty(name="カメラ", default="CHASE", items=[
            ("CHASE", "後ろから追う", ""), ("SIDE", "横から並走", ""), ("HELI", "上空から", ""),
            ("INCAR", "車内", ""), ("FIXED", "定点から追う", "")])
        cam_distance: FloatProperty(name="距離", default=9.0, min=0.5, max=200.0, unit='LENGTH')
        cam_height: FloatProperty(name="高さ", default=3.0, min=-5.0, max=200.0, unit='LENGTH')
        cam_smooth: FloatProperty(name="なめらかさ", default=0.7, min=0.0, max=0.98,
                                  description="大きいほどカメラが遅れてゆったり付いてくる")
        cam_lens: FloatProperty(name="焦点距離 (mm)", default=35.0, min=8.0, max=300.0)
        cam_fixed_frame: IntProperty(name="定点の基準フレーム", default=1)
        cam_set_active: BoolProperty(name="シーンのカメラにする", default=True)
        cam_driver_side: EnumProperty(name="運転席", default="RIGHT", items=[
            ("RIGHT", "右ハンドル", ""), ("LEFT", "左ハンドル", "")])
        cam_eye_height: FloatProperty(name="目の高さ", default=1.15, min=0.3, max=4.0, unit='LENGTH',
                                      description="地面からの高さ")

        # テイク
        keep_takes: BoolProperty(name="焼き込むたびにテイクを保存", default=False)
        takes: CollectionProperty(type=CPB_TakeItem)
        take_index: IntProperty(default=0)

        last_report: StringProperty(default="")

    # ---------------- 焼き込み本体 ----------------

    def _main_targets(s):
        """1台目の対象（オブジェクト or ボーン）"""
        if s.use_armature:
            arm = s.armature
            if arm is None:
                raise _BakeError("アーマチュアを指定してください")
            names = [s.bone_body, s.bone_fl, s.bone_fr, s.bone_rl, s.bone_rr]
            if any(not n or n not in arm.data.bones for n in names):
                raise _BakeError("ボディとタイヤ4本のボーンを指定してください")
            tg = [_Tgt(arm, n) for n in names]
            sw = _Tgt(arm, s.bone_steer) if s.bone_steer and s.bone_steer in arm.data.bones else None
            return tg[0], tg[1:], sw
        objs = _car_objects(s)
        if any(o is None for o in objs):
            raise _BakeError("ボディとタイヤ4本を指定してください")
        sw = _Tgt(s.steering_wheel) if s.steering_wheel is not None else None
        return _Tgt(objs[0]), [_Tgt(o) for o in objs[1:]], sw

    def _params_from(s, f0, cyclic, manual):
        P = Params()
        P.manual = manual
        P.assist = s.assist
        P.mass = s.mass
        P.front_weight = s.front_weight
        P.cg_height = s.cg_height
        P.mu = s.mu
        P.drive_rear_bias = {"RWD": 1.0, "FWD": 0.0, "AWD": 0.6}[s.drive]
        P.top_speed = s.top_speed / 3.6
        P.start_speed = s.start_speed / 3.6
        P.start_frame = s.start_frame - f0
        P.stop_at_end = s.stop_at_end and not cyclic
        P.corner_use = s.corner_use
        P.accel = s.accel
        P.brake = s.brake
        P.max_steer = math.radians(s.max_steer)
        P.line_hold = s.line_hold
        P.launch_time = s.launch_time
        P.launch_slip = s.launch_slip
        P.launch_lift = s.launch_lift
        P.road_noise = s.road_noise
        P.susp_freq = s.susp_freq
        P.tire_profile = s.tire_profile
        P.body_contact = s.body_contact
        P.susp_damp = s.susp_damp
        P.pitch_mult = s.pitch_mult
        P.roll_mult = s.roll_mult
        P.travel = s.travel
        P.drift = s.drift
        P.drift_angle = math.radians(s.drift_angle)
        P.drift_r_start = s.drift_r_start
        P.drift_r_full = min(s.drift_r_full, s.drift_r_start * 0.99)
        P.drift_freq = s.drift_freq
        P.drift_damp = s.drift_damp
        P.drift_min_speed = s.drift_min_speed / 3.6
        P.drift_frames = (s.drift_start - f0, s.drift_end - f0) if s.drift_use_range else None
        P.spin = s.spin
        P.spin_frame = s.spin_frame - f0
        P.spin_dir = {"AUTO": 0, "LEFT": 1, "RIGHT": -1}[s.spin_dir]
        P.spin_kick = math.radians(s.spin_kick)
        P.spin_grip = s.spin_grip
        P.rollover = s.rollover
        P.rollover_frame = s.rollover_frame - f0
        P.rollover_dir = {"AUTO": 0, "LEFT": -1, "RIGHT": 1}[s.rollover_dir]
        P.rollover_rate = math.radians(s.rollover_rate)
        P.rollover_lift = s.rollover_lift
        P.rollover_slide = s.rollover_slide
        P.rollover_settle = s.rollover_settle
        P.rollover_auto = s.rollover_auto
        P.body_mu = s.body_mu
        # ---- 拡張（オンのときだけ設定）----
        if s.use_gears:
            P.gears = True
            P.gear_count = s.gear_count
            P.shift_rpm = s.shift_rpm
            P.idle_rpm = s.idle_rpm
            P.redline_rpm = s.redline_rpm
            P.shift_time = s.shift_time
        if s.lane_offset != 0.0:
            P.lane_offset = s.lane_offset
        P.follow_gap = s.follow_gap
        P.overtake_offset = s.overtake_offset
        return P

    def _prepare_car(context, s, body, wheels, sw, extra_rest=()):
        """基準ポーズ・車体座標・タイヤ位置などを用意"""
        all_t = [body] + list(wheels) + ([sw] if sw is not None else []) + list(extra_rest)
        for t_ in all_t:
            if not t_.has_rest():
                t_.capture()
        rest = {t_.key: t_.rest() for t_ in all_t}
        fwd = _forward_vec(s.forward_axis)
        up = Vector((0, 0, 1))
        Rk = Matrix((fwd, up.cross(fwd), up)).transposed()
        K_rest = Matrix.Translation(rest[body.key].to_translation()) @ Rk.to_4x4()
        K_inv = K_rest.inverted()
        rel = {k: K_inv @ M for k, M in rest.items()}
        wpos = [tuple(rel[w.key].to_translation()) for w in wheels]
        radii = []
        for w in wheels:
            g = w.radius_guess()
            if s.wheel_radius > 0:
                radii.append(max(s.wheel_radius, 0.05))
            elif g is None:
                raise _BakeError("リグに焼き込むときは「タイヤ半径」を指定してください")
            else:
                radii.append(max(g, 0.05))
        return dict(all_t=all_t, rest=rest, fwd=fwd, K_rest=K_rest, K_inv=K_inv, rel=rel,
                    wpos=wpos, radii=radii)

    def _set_body_shape(context, s, P, body, prep, exclude=()):
        rel = prep["rel"]
        dg = context.evaluated_depsgraph_get()
        if body.bone is None and body.obj.type != 'MESH':
            # ボディがエンプティ: 子のメッシュから形を取る
            ms = _body_meshes(body.obj, exclude)
            if not ms:
                return
            binv = body.obj.matrix_world.inverted()
            pairs = [(m, rel[body.key] @ binv @ m.matrix_world) for m in ms]
            P.body_points = _hull_points_multi(pairs, dg)
            corners = [M @ Vector(c) for m, M in pairs for c in m.bound_box]
        elif body.bone is None:
            ob = body.obj
            P.body_points = _hull_points(ob, rel[body.key], dg)
            corners = [rel[body.key] @ Vector(c) for c in ob.bound_box]
        elif s.collision_mesh is not None:
            cm = s.collision_mesh
            Mrel = prep["K_inv"] @ cm.matrix_world
            P.body_points = _hull_points(cm, Mrel, dg)
            corners = [Mrel @ Vector(c) for c in cm.bound_box]
        else:
            return
        P.body_box = (min(c.x for c in corners), max(c.x for c in corners),
                      min(c.y for c in corners), max(c.y for c in corners),
                      min(c.z for c in corners), max(c.z for c in corners))

    def _write_car(s, frames, res, body, wheels, sw, prep, extra=None):
        """シミュレーション結果を、ボディ・タイヤ・室内ハンドルのキーにする"""
        rel, wpos = prep["rel"], prep["wpos"]
        tg_all = [body] + list(wheels) + ([sw] if sw is not None else [])
        keys = {t_.key: ([], []) for t_ in tg_all}
        prev = {t_.key: None for t_ in tg_all}
        R3 = {}
        for w in wheels:
            M = rel[w.key].copy()
            M.translation = (0, 0, 0)
            R3[w.key] = M
        sw_sign = -1.0 if s.steer_invert else 1.0
        jig = extra.get("jiggle") if extra else None

        def push(t_, W, sim_worlds, pose_cache):
            B = t_.basis(W, sim_worlds, pose_cache)
            loc, q, _sc = B.decompose()
            e = q.to_euler('XYZ', prev[t_.key]) if prev[t_.key] else q.to_euler('XYZ')
            prev[t_.key] = e
            keys[t_.key][0].append(tuple(loc))
            keys[t_.key][1].append(tuple(e))

        if jig:
            for o in jig["objs"]:
                keys[o.key] = ([], [])
                prev[o.key] = None

        for fi, st in enumerate(res):
            K = Matrix.Translation(st["origin"]) @ Matrix(st["R"]).to_4x4()
            Wb = K @ rel[body.key]
            sim_worlds = {body.obj.name: Wb} if body.bone is None else {}
            pose_cache = {}
            push(body, Wb, sim_worlds, pose_cache)
            for i, w in enumerate(wheels):
                p = Vector(wpos[i]) + Vector((0, 0, st["dz"][i]))
                Ww = (K @ Matrix.Translation(p)
                      @ Matrix.Rotation(st["steer"][i], 4, 'Z')
                      @ Matrix.Rotation(st["spin"][i], 4, 'Y') @ R3[w.key])
                push(w, Ww, sim_worlds, pose_cache)
            if sw is not None:
                ang = st["steer_vis"] * s.steer_ratio * sw_sign
                axis = s.steer_axis if sw.bone is None else 'Y'
                push(sw, K @ rel[sw.key] @ Matrix.Rotation(ang, 4, axis), sim_worlds, pose_cache)
            if jig:
                rx, ry = jig["angles"][fi]
                for o in jig["objs"]:
                    pv = rel[o.key].to_translation()
                    Wj = (K @ Matrix.Translation(pv) @ Matrix.Rotation(rx * s.jiggle_amount, 4, 'X')
                          @ Matrix.Rotation(ry * s.jiggle_amount, 4, 'Y') @ Matrix.Translation(-pv) @ rel[o.key])
                    push(o, Wj, sim_worlds, pose_cache)

        for t_ in tg_all:
            t_.write(frames, keys[t_.key][0], keys[t_.key][1])
        if jig:
            for o in jig["objs"]:
                o.write(frames, keys[o.key][0], keys[o.key][1])

    def _write_trailer(s, frames, tres, tb, twheels, T_inv_rel, tw_pos):
        tg = [tb] + twheels
        keys = {t_.key: ([], []) for t_ in tg}
        prev = {t_.key: None for t_ in tg}
        R3 = {}
        for w in twheels:
            M = T_inv_rel[w.key].copy()
            M.translation = (0, 0, 0)
            R3[w.key] = M
        for st in tres:
            Tm = Matrix.Translation(st["origin"]) @ Matrix(st["R"]).to_4x4()
            Wt = Tm @ T_inv_rel[tb.key]
            sim_worlds = {tb.obj.name: Wt}
            for t_, W in [(tb, Wt)] + [
                    (w, Tm @ Matrix.Translation(Vector(tw_pos[i]) + Vector((0, 0, st["dz"][i])))
                     @ Matrix.Rotation(st["spin"], 4, 'Y') @ R3[w.key]) for i, w in enumerate(twheels)]:
                B = t_.basis(W, sim_worlds, {})
                loc, q, _ = B.decompose()
                e = q.to_euler('XYZ', prev[t_.key]) if prev[t_.key] else q.to_euler('XYZ')
                prev[t_.key] = e
                keys[t_.key][0].append(tuple(loc))
                keys[t_.key][1].append(tuple(e))
        for t_ in tg:
            t_.write(frames, keys[t_.key][0], keys[t_.key][1])

    def _run_bake(op, context):
        scene = context.scene
        s = scene.cpb
        mode = s.drive_mode
        manual = mode == "MANUAL"
        keyed = mode == "KEYED"
        body, wheels, sw = _main_targets(s)
        if mode == "PATH" and s.path is None:
            raise _BakeError("コース（カーブ）を指定してください")
        if keyed and body.bone is not None:
            raise _BakeError("手付けに後付けは、オブジェクトのボディのみ対応です")

        if s.parts_collection is not None and body.bone is None:
            _restore_parts(s)
        jig_objs = [_Tgt(o) for o in _jiggle_objects(s)] if body.bone is None else []
        prep = _prepare_car(context, s, body, wheels, sw, extra_rest=jig_objs)
        rel, wpos, radii, K_rest, fwd = prep["rel"], prep["wpos"], prep["radii"], prep["K_rest"], prep["fwd"]

        if s.use_scene_range:
            f0, f1 = scene.frame_start, scene.frame_end
        else:
            f0, f1 = s.frame_start, s.frame_end
        n_frames = f1 - f0 + 1
        if n_frames < 2:
            raise _BakeError("フレーム範囲が短すぎます")
        fps = scene.render.fps / scene.render.fps_base

        k = s.model_scale if s.model_scale > 0 else 1.0
        path = None
        cyclic = False
        laps = 1
        if s.path is not None:
            try:
                pts, cyclic = _curve_points(s.path)
                if k != 1.0:
                    pts = [(x / k, y / k, z / k) for (x, y, z) in pts]
                if cyclic:
                    p0 = Path(pts, cyclic=True)
                    laps = max(2, int(math.ceil(s.top_speed / 3.6 * n_frames / fps / p0.total)) + 1)
                path = Path(pts, cyclic=cyclic, laps=laps)
            except (ValueError, IndexError) as e:
                raise _BakeError("コースを読めません: %s" % e)

        P = _params_from(s, f0, cyclic, manual)
        excl = [w.obj for w in wheels] + ([sw.obj] if sw is not None else [])
        _set_body_shape(context, s, P, body, prep, excl)
        wpos_s, radii_s = wpos, radii
        if k != 1.0:
            _scale_shape(P, k)
            wpos_s = [(w[0] / k, w[1] / k, w[2] / k) for w in wpos]
            radii_s = [r_ / k for r_ in radii]

        try:
            geo = car_geometry(wpos, s.front_weight)
        except ValueError as e:
            raise _BakeError(str(e))
        if manual:
            if path is not None:   # コースがあれば始点から、無ければ今の位置から
                P.start_xy = (path.x[0], path.y[0])
                P.start_yaw = path.heading0
                P.flat_z = path.z[0]
            else:
                cg_w = K_rest @ Vector((geo["cgx"], geo["cgy"], 0.0))
                P.start_xy = (cg_w.x, cg_w.y)
                P.start_yaw = math.atan2(fwd.y, fwd.x)
                P.flat_z = K_rest.translation.z + sum(w[2] for w in wpos) / 4 - sum(radii) / 4
                if k != 1.0:
                    P.start_xy = (P.start_xy[0] / k, P.start_xy[1] / k)
                    P.flat_z /= k

        dg = context.evaluated_depsgraph_get()
        hfn = None
        if s.ground is not None:
            hfn = _height_fn(s.ground, dg)
        if s.use_grip_map:
            if s.ground is None:
                raise _BakeError("場所ごとの路面: 地面を指定してください")
            P.grip_fn = _grip_fn(s.ground, s.grip_vgroup, s.grip_low)
        if s.use_walls:
            if s.wall_collection is None:
                raise _BakeError("壁コレクションを指定してください")
            P.wall_fn, P.wall_near = _wall_fns(s.wall_collection, dg)
        if (s.use_dents or s.use_smoke or s.use_sparks or s.use_parts) and body.bone is None:
            P.record_impacts = True
        bar_tires = _barrier_tires(s)
        if bar_tires:
            for o in bar_tires:
                if REST_KEY not in o:
                    _capture_rest([o])
            _restore_barrier(bar_tires)
            bpy.context.view_layer.update()
            P.barrier = []
            P.barrier_stiff = s.barrier_stiff
            for o in bar_tires:
                cs = [o.matrix_world @ Vector(c_) for c_ in o.bound_box]
                cx_ = sum(c_.x for c_ in cs) / 8.0
                cy_ = sum(c_.y for c_ in cs) / 8.0
                rr_ = max(max(c_.x for c_ in cs) - min(c_.x for c_ in cs), max(c_.y for c_ in cs) - min(c_.y for c_ in cs)) * 0.5
                z0_, z1_ = min(c_.z for c_ in cs), max(c_.z for c_ in cs)
                nv = o.get("cpb_barrier_n")
                if nv is not None:
                    nx_, ny_ = float(nv[0]), float(nv[1])
                elif path is not None:
                    _, s_n, _ = path.project(cx_ / k, cy_ / k)
                    dx_, dy_ = path.interp(path.x, s_n) - cx_ / k, path.interp(path.y, s_n) - cy_ / k
                    dl_ = math.hypot(dx_, dy_) or 1.0
                    nx_, ny_ = dx_ / dl_, dy_ / dl_
                else:
                    nx_ = ny_ = 0.0
                P.barrier.append((cx_ / k, cy_ / k, rr_ / k, z0_ / k, z1_ / k, nx_, ny_))
        if k != 1.0:
            hfn, P.grip_fn, P.wall_fn, P.wall_near = _scaled_fns(k, hfn, P.grip_fn, P.wall_fn, P.wall_near)

        get, _fcs = _anim_sampler(scene)

        def inputs(f):
            fr = f0 + f
            return {"speed_scale": get("speed_scale", fr), "handbrake": get("handbrake", fr),
                    "steer": get("in_steer", fr), "throttle": get("in_throttle", fr),
                    "brake": get("in_brake", fr), "reverse": get("in_reverse", fr)}

        wm = context.window_manager
        wm.progress_begin(0, 100)
        timing_note = None
        try:
            if keyed:
                src, rotmode = _keyed_source(body.obj)
                rb_inv = rel[body.key].inverted()
                poses = []
                for f in range(f0, f1 + 1):
                    Wu = _eval_source_world(body.obj, src, rotmode, f)
                    K = Wu @ rb_inv
                    o = K.translation
                    poses.append((o.x / k, o.y / k, o.z / k, math.atan2(K[1][0], K[0][0])))
                res, info = simulate_keyed(poses, P, wpos_s, radii_s, fps, hfn,
                                           lambda t: wm.progress_update(int(t * 90)))
            elif s.use_timing and not manual and len(s.timing_items):
                tg = []
                for it in s.timing_items:
                    if it.marker is None:
                        continue
                    mp = it.marker.matrix_world.translation
                    _, s_t, _ = path.project(mp.x / k, mp.y / k)
                    tg.append((it.frame - f0, s_t))
                if not tg:
                    raise _BakeError("到達タイミング: 地点を指定してください")
                res, info = solve_timing(path, P, wpos_s, radii_s, n_frames, fps, hfn, inputs, tg)
                errs = info["timing_errors"]
                worst = max(errs, key=abs)
                timing_note = (worst, errs)
            else:
                res, info = simulate(None if manual else path, P, wpos_s, radii_s, n_frames, fps, hfn,
                                     inputs, lambda t: wm.progress_update(int(t * 90)))
        except ValueError as e:
            raise _BakeError(str(e))
        finally:
            wm.progress_end()
        res_m = res                           # シミュレーション単位（メートル）
        res = _scale_res(res_m, k)            # シーン単位
        if k != 1.0 and info.get("impacts"):
            info["impacts"] = [(f_, (pt[0] * k, pt[1] * k, pt[2] * k), imp * k, nrm)
                               for (f_, pt, imp, nrm) in info["impacts"]]

        # ---- キーフレームに変換 ----
        frames = list(range(f0, f1 + 1))
        extra = None
        if jig_objs:
            extra = {"jiggle": {"objs": jig_objs,
                                "angles": jiggle_angles(res_m, fps, s.jiggle_freq, s.jiggle_damp, 1.0)}}
        if keyed:
            ad = body.obj.animation_data
            if ad is not None and ad.action is not None and not ad.action.name.startswith(body.obj.name + "_CarPhysics"):
                ad.action = None      # 手付け元（コピー済み）は残し、焼き込みは別のアクションへ
        _write_car(s, frames, res, body, wheels, sw, prep, extra)

        if s.write_props:
            vals = {
                "cpb_speed": [(st["speed"] * 3.6,) for st in res],
                "cpb_throttle": [(st["throttle"],) for st in res],
                "cpb_brake": [(st["brake"],) for st in res],
                "cpb_handbrake": [(st["handbrake"],) for st in res],
                "cpb_steer": [(math.degrees(st["steer_vis"]),) for st in res],
            }
            for pn in OUT_PROPS:
                body.obj[pn] = 0.0
            _write_channels(body.obj, frames, {'["%s"]' % pn: v for pn, v in vals.items()})
            extra_vals = {}
            if s.use_gears:
                extra_vals["cpb_rpm"] = [(st.get("rpm", P.idle_rpm),) for st in res]
                extra_vals["cpb_gear"] = [(float(st.get("gear", 1)),) for st in res]
            if (manual or keyed) and any(st.get("reverse", 0.0) > 0 for st in res):
                extra_vals["cpb_reverse"] = [(st.get("reverse", 0.0),) for st in res]
            if extra_vals:
                for pn in extra_vals:
                    body.obj[pn] = 0.0
                _write_channels(body.obj, frames, {'["%s"]' % pn: v for pn, v in extra_vals.items()})

        # ---- 複数台 ----
        cars_fx = [dict(res=res_m, wpos=wpos_s, radii=radii_s, tire_w=_tire_width(s, wheels, radii), k=k)]
        traj_cars = [[(st["pos"][0], st["pos"][1], st["pos"][2], st["speed"] * 3.6) for st in res]]
        extra_lines = []
        multi_runs = []
        if s.use_multi and not manual and not keyed:
            others = [[(st["pos"][0], st["pos"][1]) for st in res_m]]
            n_ok = 0
            import random
            rng_sc = random.Random(s.multi_scatter_seed)
            for ci, item in enumerate(s.cars):
                objs = [item.body, item.wheel_fl, item.wheel_fr, item.wheel_rl, item.wheel_rr]
                if any(o is None for o in objs):
                    continue
                b2, w2 = _Tgt(objs[0]), [_Tgt(o) for o in objs[1:]]
                prep2 = _prepare_car(context, s, b2, w2, None)
                pobj = item.path or s.path
                try:
                    pts2, cyc2 = _curve_points(pobj)
                    if k != 1.0:
                        pts2 = [(x / k, y / k, z / k) for (x, y, z) in pts2]
                    path2 = Path(pts2, cyclic=cyc2, laps=laps if cyc2 else 1)
                except (ValueError, IndexError) as e:
                    raise _BakeError("%d台目のコースを読めません: %s" % (ci + 2, e))
                P2 = _params_from(s, f0, cyc2, False)
                sm_ = item.speed_mult
                lane_ = item.lane_offset
                gap_ = 0.0
                if s.multi_scatter_lane > 0.0 or s.multi_scatter_speed > 0.0 or s.multi_scatter_gap > 0.0:
                    lane_ += rng_sc.uniform(-1.0, 1.0) * s.multi_scatter_lane
                    sm_ *= 1.0 + rng_sc.uniform(-1.0, 1.0) * s.multi_scatter_speed / 100.0
                    gap_ = rng_sc.uniform(0.0, 1.0) * s.multi_scatter_gap
                P2.top_speed *= sm_
                P2.accel *= sm_
                P2.start_frame = item.start_frame - f0
                P2.start_speed = item.start_speed / 3.6
                P2.lane_offset = lane_
                if s.multi_lane_start or gap_ > 0.0:
                    s_st = min(gap_, path2.total * 0.5)
                    nx_, ny_ = path2.left_normal(s_st + 0.5)
                    lo_ = lane_ if s.multi_lane_start else 0.0
                    P2.start_xy = (path2.interp(path2.x, s_st) + nx_ * lo_, path2.interp(path2.y, s_st) + ny_ * lo_)
                P2.others = [list(o) for o in others]
                P2.overtake = item.overtake
                P2.spin = item.spin        # スピンは車ごと、横転の指定は1台目だけ
                P2.spin_frame = item.spin_frame - f0
                P2.rollover = False
                P2.no_avoid = not item.avoid
                P2.grip_fn, P2.wall_fn, P2.wall_near = P.grip_fn, P.wall_fn, P.wall_near
                _set_body_shape(context, s, P2, b2, prep2, [w.obj for w in w2])
                wpos2, radii2 = prep2["wpos"], prep2["radii"]
                if k != 1.0:
                    _scale_shape(P2, k)
                    wpos2 = [(w[0] / k, w[1] / k, w[2] / k) for w in wpos2]
                    radii2 = [r_ / k for r_ in radii2]
                res2_m, info2 = simulate(path2, P2, wpos2, radii2, n_frames, fps, hfn,
                                         lambda f: {"speed_scale": get("speed_scale", f0 + f)})
                res2 = _scale_res(res2_m, k)
                multi_runs.append(dict(item=item, b=b2, w=w2, prep=prep2, P=P2, path=path2, res_m=res2_m))
                _write_car(s, frames, res2, b2, w2, None, prep2)
                others.append([(st["pos"][0], st["pos"][1]) for st in res2_m])
                cars_fx.append(dict(res=res2_m, wpos=wpos2, radii=radii2,
                                    tire_w=_tire_width(s, w2, prep2["radii"]), k=k))
                traj_cars.append([(st["pos"][0], st["pos"][1], st["pos"][2], st["speed"] * 3.6) for st in res2])
                n_ok += 1
            if s.multi_collide and multi_runs:
                # 車同士の衝突: 全車の動きを互いの障害物として、計算し直す
                def traj_of(rm):
                    return [(st["origin"][0], st["origin"][1], math.atan2(st["R"][1][0], st["R"][0][0])) for st in rm]

                cars_all = [dict(P=P, path=path, wpos=wpos_s, radii=radii_s, res_m=res_m, main=True)] + [
                    dict(P=r_["P"], path=r_["path"], wpos=[(w_[0] / k, w_[1] / k, w_[2] / k) for w_ in r_["prep"]["wpos"]],
                         radii=[r2 / k for r2 in r_["prep"]["radii"]], res_m=r_["res_m"], main=False, run=r_)
                    for r_ in multi_runs]
                boxes = []
                for c_ in cars_all:
                    bb = c_["P"].body_box or (-2.3, 2.3, -0.95, 0.95, 0, 0)
                    boxes.append((bb[0], bb[1], bb[2], bb[3]))
                hits = 0
                for _pass in range(3):
                    for ci_, c_ in enumerate(cars_all):
                        c_["P"].collide_with = [dict(traj=traj_of(o_["res_m"]), box=boxes[oi_])
                                                for oi_, o_ in enumerate(cars_all) if oi_ != ci_]
                        inp_ = inputs if c_["main"] else (lambda f: {"speed_scale": get("speed_scale", f0 + f)})
                        rm, inf_ = simulate(c_["path"], c_["P"], c_["wpos"], c_["radii"], n_frames, fps, hfn, inp_)
                        c_["res_m"], c_["info"] = rm, inf_
                for c_ in cars_all:
                    if c_["info"].get("car_hit_at") is not None:
                        hits += 1
                    if c_["main"]:
                        res_m, info = c_["res_m"], c_["info"]
                        res = _scale_res(res_m, k)
                        _write_car(s, frames, res, body, wheels, sw, prep, extra)
                        cars_fx[0]["res"] = res_m
                        traj_cars[0] = [(st["pos"][0], st["pos"][1], st["pos"][2], st["speed"] * 3.6) for st in res]
                    else:
                        r_ = c_["run"]
                        _write_car(s, frames, _scale_res(c_["res_m"], k), r_["b"], r_["w"], None, r_["prep"])
                        idx_ = multi_runs.index(r_) + 1
                        cars_fx[idx_]["res"] = c_["res_m"]
                        traj_cars[idx_] = [(st["pos"][0] * k, st["pos"][1] * k, st["pos"][2] * k, st["speed"] * 3.6)
                                           for st in c_["res_m"]]
                extra_lines.append("車同士の接触 %d台" % hits)
            extra_lines.append("他の車 %d台" % n_ok)

        # ---- トレーラー ----
        if s.use_trailer:
            if s.trailer_body is None or s.trailer_wheels is None or not len(s.trailer_wheels.all_objects):
                raise _BakeError("トレーラー: 荷台と、タイヤのコレクションを指定してください")
            tb = _Tgt(s.trailer_body)
            tws = [_Tgt(o) for o in s.trailer_wheels.all_objects]
            for t_ in [tb] + tws:
                if not t_.has_rest():
                    t_.capture()
            Krest = prep["K_rest"]
            Rk3 = Krest.to_3x3()
            ctr = sum((t_.rest().to_translation() for t_ in tws), Vector()) / len(tws)
            T_rest = Matrix.Translation(ctr) @ Rk3.to_4x4()
            T_inv = T_rest.inverted()
            if s.trailer_hitch is not None:
                hitch_w = s.trailer_hitch.matrix_world.translation.copy()
            else:
                cs = [s.trailer_body.matrix_world @ Vector(c) for c in s.trailer_body.bound_box]
                cs_t = [T_inv @ c for c in cs]
                hx = max(c.x for c in cs_t)
                hz = min(c.z for c in cs_t) + 0.05
                hitch_w = T_rest @ Vector((hx, 0.0, hz))
            h_t = T_inv @ hitch_w
            h_c = prep["K_inv"] @ hitch_w
            T_rel = {t_.key: T_inv @ t_.rest() for t_ in [tb] + tws}
            tw_pos = [tuple(T_rel[w.key].to_translation()) for w in tws]
            trad = max(sum(max(w.obj.dimensions) * 0.5 for w in tws) / len(tws), 0.05)
            TR = dict(hitch_car=tuple(c_ / k for c_ in h_c), hitch_len=math.hypot(h_t.x, h_t.y) / k,
                      hitch_dz=h_t.z / k, wheels=[tuple(c_ / k for c_ in w) for w in tw_pos],
                      radius=trad / k, travel=s.travel)
            tres = simulate_trailer(res_m, TR, fps, hfn, P.flat_z if manual else (path.z[0] if path else 0.0),
                                    s.road_noise)
            if k != 1.0:
                for st in tres:
                    o = st["origin"]
                    st["origin"] = (o[0] * k, o[1] * k, o[2] * k)
                    st["dz"] = [d * k for d in st["dz"]]
            _write_trailer(s, frames, tres, tb, tws, T_rel, tw_pos)
            extra_lines.append("トレーラー連結")

        # ---- タイヤバリヤ ----
        if bar_tires:
            hb = info.get("barrier_at")
            hull = P.body_points or []
            near_f = None
            if hb is None and hull:
                # 小さな物（パイロンなど）は車体の判定点の間をすり抜けることがあるので、近くを通ったかも調べる
                rr2 = (max(math.hypot(x, y) for (x, y, z) in hull) * k + 0.5 * k) ** 2
                cs_ = [o.matrix_world.translation for o in bar_tires]
                for fi_, st in enumerate(res):
                    px_, py_ = st["pos"][0], st["pos"][1]
                    if any((c_.x - px_) ** 2 + (c_.y - py_) ** 2 < rr2 for c_ in cs_):
                        near_f = fi_
                        break
            if hb is not None:
                extra_lines.append("バリヤに衝突 %dフレーム" % (hb + f0))
            elif near_f is not None:
                extra_lines.append("バリヤの近くを通過 %dフレーム" % (near_f + f0))
            else:
                extra_lines.append("バリヤには当たらず")
            start_f = hb if hb is not None else near_f
            if start_f is not None and s.barrier_scatter and body.bone is None and hull:
                hull_model = [(x * k, y * k, z * k) for (x, y, z) in hull]
                bpy.context.view_layer.update()
                track = [st["pos"] for st in res[max(start_f - 2, 0)::2]]
                n = _scatter_tires(scene, s, bar_tires, body.obj, rel[body.key], hull_model, k,
                                   s.ground, f0, f1, track, hit_f=f0 + max(start_f - 3, 0),
                                   car_pos=[st["pos"] for st in res])
                extra_lines.append("タイヤ %d本が飛び散り" % n)

        # ---- 軌跡 ----
        if s.show_trajectory:
            if s.traj_speed_color:
                vmin, vmax = _make_trajectory_colored(scene, traj_cars)
                extra_lines.append("軌跡: 青 %.0f → 赤 %.0f km/h" % (vmin, vmax))
            else:
                _make_trajectory(scene, [st["pos"] for st in res])
        else:
            _remove_trajectory()

        # ---- 演出 ----
        hfn_b = hfn                      # シーン単位の地面の高さ（hfn はシミュレーション単位）
        if hfn is not None and k != 1.0:
            def hfn_b(x, y, _h=hfn):
                z = _h(x / k, y / k)
                return None if z is None else z * k
        if s.use_parts and body.bone is None and s.parts_collection is not None:
            n = _detach_parts(scene, s, body.obj, rel[body.key], res, info.get("impacts", []), P.mass, k, hfn_b,
                              f0, f1, fps)
            extra_lines.append("外れたパーツ %d個" % n if n else "外れたパーツなし")
        if s.use_sparks and body.bone is None:
            n = _build_sparks(scene, s, res, info.get("impacts", []), P.mass, k, hfn_b, P.body_box, fps, f0)
            extra_lines.append("火花 %d本" % n if n else "火花なし")
        else:
            _remove_object(SPARK_NAME)
        if s.use_skid:
            n = _build_skids(scene, s, cars_fx, hfn, fps, f0)
            extra_lines.append("タイヤ痕 %d枚" % n if n else "タイヤ痕なし（滑っていない）")
        else:
            _remove_object(SKID_NAME)
        if s.particle_style == 'TRIANGLE' and s.tri_no_blur and (s.use_smoke or s.use_sparks):
            blur = False
            if hasattr(scene.eevee, "use_motion_blur") and scene.eevee.use_motion_blur:
                scene.eevee.use_motion_blur = False
                blur = True
            if scene.render.use_motion_blur:
                scene.render.use_motion_blur = False
                blur = True
            if blur:
                extra_lines.append("モーションブラーを切りました（三角の粒を筋にしないため）")
        if s.use_smoke:
            n = _build_smoke(scene, s, cars_fx, hfn, fps, f0, (res, info.get("impacts", []), P.mass))
            extra_lines.append("スモーク %d個" % n if n else "スモークなし（滑っていない）")
        else:
            _remove_object(SMOKE_NAME)
        if body.bone is None:
            dt_obj = _dent_target(body.obj, excl)
            if s.use_dents and dt_obj is not None:
                rel_dt = rel[body.key] @ body.obj.matrix_world.inverted() @ dt_obj.matrix_world \
                    if dt_obj != body.obj else rel[body.key]
                n = _build_dents(dt_obj, rel_dt, info.get("impacts", []), P.mass, s, f0, k)
                extra_lines.append("へこみ %d箇所" % n)
            else:
                _remove_dents(dt_obj)

        scene.frame_set(scene.frame_current)

        # ---- テイク ----
        if s.keep_takes:
            tobjs = list({t_.obj.name: t_.obj for t_ in prep["all_t"]}.values())
            import time
            _save_take(s, tobjs, time.strftime("%H:%M:%S"))

        # ---- 結果レポート ----
        vmax = max(st["speed"] for st in res) * 3.6
        lines = ["%dフレーム 完了" % n_frames, "最高 %.0f km/h" % vmax]
        warn = []
        if not manual and not keyed:
            course_len = path.total / laps if cyclic else path.total
            lines.append("走行 %.0f / %.0f m" % (info["distance"], course_len))
            crashed = info["rollover_at"] is not None or s.spin or info.get("barrier_at") is not None
            if not cyclic and not info["finished"] and not crashed:
                warn.append("終点に届いていない|フレーム数か速度を増やす")
            if info["max_err"] > 3.0 and info["rollover_at"] is None and info.get("barrier_at") is None:
                warn.append("コースから%.1fmはみ出し|攻め具合か速度を下げる" % info["max_err"])
        if info["air_frames"]:
            lines.append("ジャンプ %dフレーム" % info["air_frames"])
        if info["rollover_at"] is not None:
            lines.append("横転 %dフレームから" % (info["rollover_at"] + f0))
        if timing_note is not None:
            worst, errs = timing_note
            if abs(worst) < 1.0:
                lines.append("到達タイミング: 全%d地点 一致" % len(errs))
            else:
                warn.append("到達タイミングが最大%+.0fフレームずれ|%s" % (
                    worst, "最高速度・加速を上げる" if worst > 0 else "発進フレームを遅らせる"))
        if s.use_gears:
            lines.append("最大 %dレンジ %.0f rpm" % (max(st.get("gear", 1) for st in res),
                                                  max(st.get("rpm", 0) for st in res)))
        lines += extra_lines
        if body.bone is None:
            cons = [c.name for c in body.obj.constraints if c.enabled and not c.mute]
        else:
            cons = [c.name for c in body.obj.pose.bones[body.bone].constraints if c.enabled and not c.mute]
        if cons:
            warn.append("コンストレイントが有効|ボディの %s を無効にする" % ", ".join(cons))
        if sw is not None and sw.bone is None and sw.obj.parent != body.obj:
            warn.append("室内ハンドルの親が違う|ボディの子にする")
        if k == 1.0:
            est = _estimate_scale(wpos, radii)
            if est > 2.0 or est < 0.4:
                warn.append("実物の約%.1f倍の大きさ|縮尺の「自動」を押す" % est)
        s.last_report = "\n".join(lines + ["※" + w for w in warn])
        op.report({'WARNING'} if warn else {'INFO'},
                  " / ".join(lines + [w.replace("|", "→") for w in warn]))
        return {'FINISHED'}

    def _estimate_scale(wpos, radii):
        """タイヤ半径（実車 約0.32m）とホイールベース（約2.65m）から縮尺を推定"""
        rm = sum(radii) / len(radii)
        wb = abs((wpos[0][0] + wpos[1][0]) - (wpos[2][0] + wpos[3][0])) * 0.5
        return (rm / 0.32 + wb / 2.65) * 0.5

    def _tire_width(s, wheels, radii):
        if s.skid_width > 0:
            return s.skid_width
        if wheels[0].bone is None:
            return max(min(wheels[0].obj.dimensions), 0.08)
        return radii[0] * 0.6

    # ---------------- オペレーター ----------------

    class CPB_OT_bake(bpy.types.Operator):
        bl_idname = "cpb.bake"
        bl_label = "シミュレーションして焼き込み"
        bl_description = "物理シミュレーションを実行し、ボディとタイヤにキーフレームを書き込む"
        bl_options = {'REGISTER', 'UNDO'}

        def execute(self, context):
            try:
                return _run_bake(self, context)
            except _BakeError as e:
                self.report({'ERROR'}, str(e))
                return {'CANCELLED'}

    class CPB_OT_clear(bpy.types.Operator):
        bl_idname = "cpb.clear"
        bl_label = "焼き込みを消して元に戻す"
        bl_description = "焼き込んだキーフレームを削除し、基準ポーズに戻す"
        bl_options = {'REGISTER', 'UNDO'}

        def execute(self, context):
            s = context.scene.cpb
            if s.use_armature and s.armature is not None:
                for n in (s.bone_body, s.bone_fl, s.bone_fr, s.bone_rl, s.bone_rr, s.bone_steer):
                    if n and n in s.armature.data.bones:
                        t_ = _Tgt(s.armature, n)
                        t_.remove_keys()
                        t_.restore()
            objs = _rest_objects(s)
            objs += [o for o in _jiggle_objects(s)]
            for item in s.cars:
                objs += [o for o in (item.body, item.wheel_fl, item.wheel_fr, item.wheel_rl, item.wheel_rr) if o]
            if s.trailer_body is not None:
                objs.append(s.trailer_body)
            if s.trailer_wheels is not None:
                objs += list(s.trailer_wheels.all_objects)
            for o in objs:
                _remove_keys(o)
                if o == s.body:
                    _remove_keys(o, tuple('["%s"]' % k for k in OUT_PROPS + EXTRA_PROPS))
                    src = o.get(SRC_KEY)
                    if src and src in bpy.data.actions:
                        if o.animation_data is None:
                            o.animation_data_create()
                        o.animation_data.action = bpy.data.actions[src]
                        o.rotation_mode = o.get(SRC_ROT, o.rotation_mode)
                        del o[SRC_KEY]
                        continue
                if REST_KEY in o:
                    o.matrix_world = _list_to_mat(list(o[REST_KEY]))
            _restore_barrier([o for o in (s.barrier_collection.all_objects if s.barrier_collection else [])
                              if o.type == 'MESH'])
            old = bpy.data.objects.get(BARRIER_PROXY)
            if old is not None:
                bpy.data.objects.remove(old)
            _remove_trajectory()
            _remove_object(SKID_NAME)
            _remove_object(SMOKE_NAME)
            _remove_object(SPARK_NAME)
            _restore_parts(s)
            if s.body is not None:
                _remove_dents(_dent_target(s.body, [s.wheel_fl, s.wheel_fr, s.wheel_rl, s.wheel_rr, s.steering_wheel]))
            s.last_report = ""
            return {'FINISHED'}

    class CPB_OT_capture(bpy.types.Operator):
        bl_idname = "cpb.capture_rest"
        bl_label = "今の姿勢を基準ポーズとして記録"
        bl_description = "クルマを水平・タイヤまっすぐの状態にしてから押す（初回の焼き込み時は自動で記録）"
        bl_options = {'REGISTER', 'UNDO'}

        def execute(self, context):
            s = context.scene.cpb
            objs = _rest_objects(s)
            _capture_rest(objs)
            n = len(objs)
            if s.use_armature and s.armature is not None:
                for nm in (s.bone_body, s.bone_fl, s.bone_fr, s.bone_rl, s.bone_rr, s.bone_steer):
                    if nm and nm in s.armature.data.bones:
                        _Tgt(s.armature, nm).capture()
                        n += 1
            jo = _jiggle_objects(s)
            _capture_rest(jo)
            n += len(jo)
            self.report({'INFO'}, "%d個の基準ポーズを記録しました" % n)
            return {'FINISHED'}

    class CPB_OT_detect_scale(bpy.types.Operator):
        bl_idname = "cpb.detect_scale"
        bl_label = "自動"
        bl_description = "タイヤの大きさとホイールベースから、モデルの縮尺を推定して設定する"
        bl_options = {'REGISTER', 'UNDO'}

        def execute(self, context):
            s = context.scene.cpb
            try:
                body, wheels, sw = _main_targets(s)
                prep = _prepare_car(context, s, body, wheels, sw)
            except _BakeError as e:
                self.report({'ERROR'}, str(e))
                return {'CANCELLED'}
            est = _estimate_scale(prep["wpos"], prep["radii"])
            s.model_scale = round(est, 2) if abs(est - 1.0) > 0.25 else 1.0
            self.report({'INFO'}, "モデルの縮尺を %.2f にしました（推定 %.2f）" % (s.model_scale, est))
            return {'FINISHED'}

    class CPB_OT_make_barrier(bpy.types.Operator):
        bl_idname = "cpb.make_barrier"
        bl_label = "タイヤバリヤを作成"
        bl_description = "選択中のカーブに沿って、タイヤを積んだバリヤを並べる（トラック側の向きも記録）"
        bl_options = {'REGISTER', 'UNDO'}

        def execute(self, context):
            s = context.scene.cpb
            cv = context.active_object
            if cv is None or cv.type != 'CURVE':
                self.report({'ERROR'}, "バリヤを置く線（カーブ）を選択してください")
                return {'CANCELLED'}
            k = s.model_scale if s.model_scale > 0 else 1.0
            pts, cyc = _curve_points(cv)
            pth = Path([(x / k, y / k, z / k) for (x, y, z) in pts], cyclic=cyc)
            col = bpy.data.collections.get(BARRIER_COLL)
            if col is None:
                col = bpy.data.collections.new(BARRIER_COLL)
                context.scene.collection.children.link(col)
            me = _tire_mesh(k)
            mats = [_barrier_mat("CPB_バリヤ赤", (0.75, 0.05, 0.04, 1)), _barrier_mat("CPB_バリヤ白", (0.85, 0.85, 0.85, 1)),
                    _barrier_mat("CPB_バリヤ黒", (0.03, 0.03, 0.03, 1))]
            if not me.materials:
                me.materials.append(mats[2])
            dia = 0.62
            n_col = max(1, int(pth.total / dia))
            side = 1.0 if s.gen_side == "LEFT" else -1.0
            count = 0
            for i in range(n_col + 1):
                sd = min(i * dia, pth.total)
                x, y = pth.interp(pth.x, sd), pth.interp(pth.y, sd)
                z = pth.interp(pth.z, sd)
                lnx, lny = pth.left_normal(sd)
                nx, ny = lnx * side, lny * side            # トラック側
                for row in range(s.gen_rows):
                    bx, by = x - nx * dia * row, y - ny * dia * row
                    for lv in range(s.gen_stack):
                        o = bpy.data.objects.new("CPB_タイヤ", me)
                        col.objects.link(o)
                        o.location = (bx * k, by * k, (z + 0.105 + lv * 0.2) * k)
                        o.rotation_euler = (0, 0, (i * 0.37 + row) % 6.283)
                        o["cpb_barrier_n"] = (nx, ny)
                        if s.gen_colors and row == 0:
                            o.material_slots[0].link = 'OBJECT'
                            o.material_slots[0].material = mats[i % 2]
                        count += 1
            s.barrier_collection = col
            s.use_barrier = True
            self.report({'INFO'}, "タイヤ %d本のバリヤを作りました" % count)
            return {'FINISHED'}

    class CPB_OT_update_barrier_tires(bpy.types.Operator):
        bl_idname = "cpb.update_barrier_tires"
        bl_label = "タイヤの形を新しくする"
        bl_description = "以前の版で作ったバリヤのタイヤ（ドーナツ形）を、溝のある本物のタイヤの形に置き換える（位置・色はそのまま）"
        bl_options = {'REGISTER', 'UNDO'}

        def execute(self, context):
            s = context.scene.cpb
            col = s.barrier_collection or bpy.data.collections.get(BARRIER_COLL)
            if col is None:
                self.report({'ERROR'}, "バリヤのタイヤのコレクションがありません")
                return {'CANCELLED'}
            n = 0
            for o in col.all_objects:
                if o.type != 'MESH' or not _is_old_tire_mesh(o.data):
                    continue
                try:
                    k = float(o.data.name.rsplit("_", 1)[1])
                except ValueError:
                    k = s.model_scale if s.model_scale > 0 else 1.0
                old = o.data
                me = _tire_mesh(k)
                if not me.materials and old.materials:
                    me.materials.append(old.materials[0])
                o.data = me
                n += 1
            self.report({'INFO'}, "%d本のタイヤを新しい形にしました" % n)
            return {'FINISHED'}

    class CPB_OT_list_edit(bpy.types.Operator):
        bl_idname = "cpb.list_edit"
        bl_label = "リスト編集"
        bl_options = {'REGISTER', 'UNDO'}
        target: StringProperty()
        action: StringProperty()

        def execute(self, context):
            s = context.scene.cpb
            coll = getattr(s, self.target)
            idx_name = {"timing_items": "timing_index", "cars": "car_index", "takes": "take_index"}[self.target]
            idx = getattr(s, idx_name)
            if self.action == "ADD":
                it = coll.add()
                if self.target == "timing_items":
                    sel = [o for o in context.selected_objects if o.type == 'EMPTY']
                    if sel:
                        it.marker = sel[0]
                    it.frame = context.scene.frame_current
                setattr(s, idx_name, len(coll) - 1)
            elif self.action == "REMOVE" and 0 <= idx < len(coll):
                coll.remove(idx)
                setattr(s, idx_name, max(0, idx - 1))
            return {'FINISHED'}

    class CPB_OT_add_marker(bpy.types.Operator):
        bl_idname = "cpb.add_marker"
        bl_label = "3Dカーソルの位置に地点を追加"
        bl_description = "3Dカーソルの位置にエンプティを作り、今のフレームで通過する地点として登録"
        bl_options = {'REGISTER', 'UNDO'}

        def execute(self, context):
            s = context.scene.cpb
            e = bpy.data.objects.new("CPB_地点_%d" % (len(s.timing_items) + 1), None)
            e.empty_display_type = 'CONE'
            e.empty_display_size = 1.5
            e.location = context.scene.cursor.location
            context.scene.collection.objects.link(e)
            it = s.timing_items.add()
            it.marker = e
            it.frame = context.scene.frame_current
            s.timing_index = len(s.timing_items) - 1
            return {'FINISHED'}

    class CPB_OT_take_restore(bpy.types.Operator):
        bl_idname = "cpb.take_restore"
        bl_label = "このテイクに戻す"
        bl_options = {'REGISTER', 'UNDO'}

        def execute(self, context):
            s = context.scene.cpb
            if not (0 <= s.take_index < len(s.takes)):
                return {'CANCELLED'}
            n = 0
            for line in s.takes[s.take_index].entries.split("\n"):
                if "=" not in line:
                    continue
                on, an = line.split("=", 1)
                o = bpy.data.objects.get(on)
                a = bpy.data.actions.get(an)
                if o is None or a is None:
                    continue
                if o.animation_data is None:
                    o.animation_data_create()
                cp = a.copy()
                cp.name = an + "_使用中"
                cp.use_fake_user = False
                o.animation_data.action = cp
                n += 1
            context.scene.frame_set(context.scene.frame_current)
            self.report({'INFO'}, "%d個のオブジェクトをテイクに戻しました" % n)
            return {'FINISHED'}

    class CPB_OT_take_delete(bpy.types.Operator):
        bl_idname = "cpb.take_delete"
        bl_label = "テイクを削除"
        bl_options = {'REGISTER', 'UNDO'}

        def execute(self, context):
            s = context.scene.cpb
            if not (0 <= s.take_index < len(s.takes)):
                return {'CANCELLED'}
            for line in s.takes[s.take_index].entries.split("\n"):
                if "=" in line:
                    a = bpy.data.actions.get(line.split("=", 1)[1])
                    if a is not None and a.users <= 1:
                        bpy.data.actions.remove(a)
            s.takes.remove(s.take_index)
            s.take_index = max(0, s.take_index - 1)
            return {'FINISHED'}

    class CPB_OT_make_camera(bpy.types.Operator):
        bl_idname = "cpb.make_camera"
        bl_label = "カメラを作成"
        bl_description = "焼き込んだ動きに合わせて動くカメラを作る"
        bl_options = {'REGISTER', 'UNDO'}

        def execute(self, context):
            scene = context.scene
            s = scene.cpb
            try:
                body, wheels, sw = _main_targets(s)
            except _BakeError as e:
                self.report({'ERROR'}, str(e))
                return {'CANCELLED'}
            if not body.has_rest():
                self.report({'ERROR'}, "先に焼き込みを実行してください")
                return {'CANCELLED'}
            prep = _prepare_car(context, s, body, wheels, sw)
            rb_inv = prep["rel"][body.key].inverted()
            if s.use_scene_range:
                f0, f1 = scene.frame_start, scene.frame_end
            else:
                f0, f1 = s.frame_start, s.frame_end
            cur = scene.frame_current
            Ks = []
            for f in range(f0, f1 + 1):
                scene.frame_set(f)
                Ks.append(body.world() @ rb_inv)
            scene.frame_set(cur)
            geo = car_geometry(prep["wpos"], s.front_weight)
            km = s.model_scale if s.model_scale > 0 else 1.0
            ground_z = sum(w[2] for w in prep["wpos"]) / 4.0 - sum(prep["radii"]) / 4.0
            if sw is not None and sw.bone is None:
                swp = prep["rel"][sw.key].to_translation()
                eye = Vector((swp.x - 0.6 * km, swp.y, max(ground_z + s.cam_eye_height * km, swp.z + 0.22 * km)))
            else:
                side = -1.0 if s.cam_driver_side == "RIGHT" else 1.0
                xs = [w[0] for w in prep["wpos"]]
                eye = Vector((min(xs) + (max(xs) - min(xs)) * 0.35, geo["cgy"] + side * 0.37 * km,
                              ground_z + s.cam_eye_height * km))
            name = "CPB_カメラ_" + {"CHASE": "後ろ", "SIDE": "横", "HELI": "上空", "INCAR": "車内",
                                    "FIXED": "定点"}[s.cam_type]
            cam = bpy.data.objects.get(name)
            if cam is None or cam.type != 'CAMERA':
                cd = bpy.data.cameras.new(name)
                cam = bpy.data.objects.new(name, cd)
                scene.collection.objects.link(cam)
            cam.data.lens = s.cam_lens
            km = s.model_scale if s.model_scale > 0 else 1.0
            if km != 1.0:
                cam.data.clip_end = max(cam.data.clip_end, 150.0 * km)
                cam.data.clip_start = 0.1 * km
            cam.animation_data_clear()
            a = 1.0 - s.cam_smooth
            sp = sf = None
            fixed_pos = None
            if s.cam_type == "FIXED":
                Kf = Ks[_clamp(s.cam_fixed_frame - f0, 0, len(Ks) - 1)]
                side = Kf.to_3x3() @ Vector((0, -1, 0))
                fixed_pos = Kf.translation + side * s.cam_distance * km + Vector((0, 0, s.cam_height * km))
            for k, K in enumerate(Ks):
                f = f0 + k
                cgw = K @ Vector((geo["cgx"], geo["cgy"], 0.4 * km))
                fw = K.to_3x3() @ Vector((1, 0, 0))
                fw.z = 0
                if fw.length < 1e-6:
                    fw = Vector((1, 0, 0))
                fw.normalize()
                if sp is None:
                    sp, sf = cgw.copy(), fw.copy()
                else:
                    sp = sp.lerp(cgw, max(a, 0.02) * 1.5 if s.cam_type != "INCAR" else 1.0)
                    sf = sf.lerp(fw, max(a, 0.02)).normalized()
                right = sf.cross(Vector((0, 0, 1)))
                cdist, chgt = s.cam_distance * km, s.cam_height * km
                if s.cam_type == "CHASE":
                    loc = sp - sf * cdist + Vector((0, 0, chgt))
                    look = sp + sf * 2.0 * km
                elif s.cam_type == "SIDE":
                    loc = sp + right * cdist + Vector((0, 0, chgt * 0.4))
                    look = sp
                elif s.cam_type == "HELI":
                    loc = sp - sf * cdist * 0.6 + right * cdist * 0.4 + Vector((0, 0, chgt + cdist))
                    look = sp
                elif s.cam_type == "INCAR":
                    loc = K @ eye
                    look = loc + (K.to_3x3() @ Vector((10 * km, 0, -0.8 * km)))
                else:
                    loc = fixed_pos
                    look = sp
                cam.location = loc
                cam.rotation_euler = (look - loc).to_track_quat('-Z', 'Y').to_euler()
                cam.keyframe_insert("location", frame=f)
                cam.keyframe_insert("rotation_euler", frame=f)
            if s.cam_set_active:
                scene.camera = cam
            self.report({'INFO'}, "%s を作成しました" % name)
            return {'FINISHED'}

    class CPB_OT_setup_lights(bpy.types.Operator):
        bl_idname = "cpb.setup_lights"
        bl_label = "ライトを設定"
        bl_description = "ブレーキランプ・バックランプのマテリアルの発光を、焼き込んだ値に連動させる"
        bl_options = {'REGISTER', 'UNDO'}

        def execute(self, context):
            s = context.scene.cpb
            if s.body is None:
                self.report({'ERROR'}, "ボディを指定してください")
                return {'CANCELLED'}
            n = 0
            for coll, prop, color, base in ((s.brake_lights, "cpb_brake", (1.0, 0.02, 0.01, 1), 0.15),
                                            (s.reverse_lights, "cpb_reverse", (1.0, 1.0, 0.95, 1), 0.0)):
                if coll is None:
                    continue
                if prop not in s.body:
                    s.body[prop] = 0.0
                for o in coll.all_objects:
                    if o.type != 'MESH':
                        continue
                    if not o.data.materials:
                        o.data.materials.append(bpy.data.materials.new("CPB_ライト"))
                    for i, m in enumerate(o.data.materials):
                        if m is None:
                            continue
                        if m.users > 1 and not m.name.startswith("CPB_"):
                            m = m.copy()
                            m.name = "CPB_" + m.name
                            o.data.materials[i] = m
                        m.use_nodes = True
                        bs = next((nd for nd in m.node_tree.nodes if nd.type == 'BSDF_PRINCIPLED'), None)
                        if bs is None:
                            continue
                        ec = bs.inputs.get("Emission Color") or bs.inputs.get("Emission")
                        es = bs.inputs.get("Emission Strength")
                        if ec is None or es is None:
                            continue
                        ec.default_value = color
                        try:
                            es.driver_remove("default_value")
                        except TypeError:
                            pass
                        d = es.driver_add("default_value").driver
                        d.type = 'SCRIPTED'
                        v = d.variables.new()
                        v.name = "v"
                        v.type = 'SINGLE_PROP'
                        v.targets[0].id = s.body
                        v.targets[0].data_path = '["%s"]' % prop
                        d.expression = "%g + v * %g" % (base * s.light_strength, s.light_strength)
                        n += 1
            self.report({'INFO'}, "%d個のマテリアルを連動させました" % n)
            return {'FINISHED'}

    class CPB_OT_clear_lights(bpy.types.Operator):
        bl_idname = "cpb.clear_lights"
        bl_label = "ライト設定を解除"
        bl_options = {'REGISTER', 'UNDO'}

        def execute(self, context):
            s = context.scene.cpb
            n = 0
            for coll in (s.brake_lights, s.reverse_lights):
                if coll is None:
                    continue
                for o in coll.all_objects:
                    if o.type != 'MESH':
                        continue
                    for m in o.data.materials:
                        if m is None or not m.use_nodes:
                            continue
                        for nd in m.node_tree.nodes:
                            if nd.type == 'BSDF_PRINCIPLED':
                                es = nd.inputs.get("Emission Strength")
                                if es is not None:
                                    try:
                                        es.driver_remove("default_value")
                                        es.default_value = 0.0
                                        n += 1
                                    except TypeError:
                                        pass
            self.report({'INFO'}, "%d個の連動を解除しました" % n)
            return {'FINISHED'}

    # ---------------- パネル ----------------

    class _CPB_Panel:
        bl_space_type = 'VIEW_3D'
        bl_region_type = 'UI'
        bl_category = "Car Physics"

    class CPB_UL_timing(bpy.types.UIList):
        def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
            row = layout.row(align=True)
            row.prop(item, "marker", text="", emboss=False)
            row.prop(item, "frame", text="")

    class CPB_UL_cars(bpy.types.UIList):
        def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
            layout.label(text="%d台目: %s" % (index + 2, item.body.name if item.body else "（未指定）"), icon='AUTO')

    class CPB_UL_takes(bpy.types.UIList):
        def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
            layout.label(text=item.name, icon='ACTION')

    def _list_ui(L, s, target, uilist, index):
        row = L.row()
        row.template_list(uilist, "", s, target, s, index, rows=3)
        col = row.column(align=True)
        op = col.operator("cpb.list_edit", text="", icon='ADD')
        op.target, op.action = target, "ADD"
        op = col.operator("cpb.list_edit", text="", icon='REMOVE')
        op.target, op.action = target, "REMOVE"

    class CPB_PT_main(_CPB_Panel, bpy.types.Panel):
        bl_label = "Car Physics Baker"

        def draw(self, context):
            s = context.scene.cpb
            L = self.layout
            col = L.column(align=True)
            if s.use_armature:
                col.label(text="リグに焼き込み（下のパネル）", icon='ARMATURE_DATA')
            else:
                col.prop(s, "body")
                col.prop(s, "wheel_fl", text="前左")
                col.prop(s, "wheel_fr", text="前右")
                col.prop(s, "wheel_rl", text="後左")
                col.prop(s, "wheel_rr", text="後右")
            L.label(text="車の正面:")
            L.row().prop(s, "forward_axis", expand=True)
            L.prop(s, "wheel_radius")
            row = L.row(align=True)
            row.prop(s, "model_scale", text="縮尺")
            row.operator("cpb.detect_scale", text="自動")
            row = L.row()
            row.label(text="車種:")
            row.prop(s, "preset", text="")
            L.operator("cpb.capture_rest", text="基準ポーズを記録", icon='ARMATURE_DATA')

            L.separator()
            L.prop(s, "drive_mode", text="")
            if s.drive_mode == "KEYED":
                L.label(text="ボディの位置・回転のキーを使います", icon='INFO')
            col = L.column()
            col.scale_y = 1.6
            col.operator("cpb.bake", text="焼き込み実行", icon='PLAY')
            L.operator("cpb.clear", text="元に戻す", icon='LOOP_BACK')
            if s.last_report:
                box = L.box()
                col = box.column(align=True)
                for line in s.last_report.split("\n"):
                    if line.startswith("※"):
                        head, _, hint = line[1:].partition("|")
                        col.label(text=head, icon='ERROR')
                        if hint:
                            col.label(text="→ " + hint)
                    else:
                        col.label(text=line, icon='CHECKMARK' if "完了" in line else 'DOT')

    class CPB_PT_course(_CPB_Panel, bpy.types.Panel):
        bl_label = "コース・地面"
        bl_parent_id = "CPB_PT_main"

        def draw(self, context):
            s = context.scene.cpb
            L = self.layout
            L.prop(s, "path")
            if s.drive_mode == "MANUAL":
                L.label(text="スタート位置にだけ使用", icon='INFO')
            L.prop(s, "ground")
            L.prop(s, "road_noise")
            if s.drive_mode == "PATH":
                L.prop(s, "lane_offset")
            L.prop(s, "use_scene_range")
            if not s.use_scene_range:
                row = L.row(align=True)
                row.prop(s, "frame_start")
                row.prop(s, "frame_end")
            L.prop(s, "show_trajectory")
            if s.show_trajectory:
                L.prop(s, "traj_speed_color")

    class CPB_PT_drive(_CPB_Panel, bpy.types.Panel):
        bl_label = "走り"
        bl_parent_id = "CPB_PT_main"

        def draw(self, context):
            s = context.scene.cpb
            L = self.layout
            L.prop(s, "top_speed")
            if s.drive_mode == "PATH":
                L.prop(s, "start_speed")
                L.prop(s, "start_frame")
                L.prop(s, "stop_at_end")
                L.prop(s, "corner_use")
            L.prop(s, "accel")
            L.prop(s, "brake")
            L.prop(s, "mu")
            L.row().prop(s, "drive", expand=True)
            L.prop(s, "mass")
            L.prop(s, "front_weight")
            L.prop(s, "cg_height")
            L.prop(s, "max_steer")
            L.prop(s, "line_hold")
            col = L.column(align=True)
            col.prop(s, "launch_time")
            if s.launch_time > 0.0:
                col.prop(s, "launch_slip")
                col.prop(s, "launch_lift")
            L.prop(s, "assist")

    class CPB_PT_input(_CPB_Panel, bpy.types.Panel):
        bl_label = "キー入力"
        bl_parent_id = "CPB_PT_main"

        def draw(self, context):
            s = context.scene.cpb
            L = self.layout
            L.label(text="値の上で I キー＝キー挿入", icon='KEYFRAME')
            if s.drive_mode == "MANUAL":
                L.prop(s, "in_steer", slider=True)
                L.prop(s, "in_throttle", slider=True)
                L.prop(s, "in_brake", slider=True)
                L.prop(s, "in_reverse", slider=True)
            else:
                L.prop(s, "speed_scale", slider=True)
            L.prop(s, "handbrake", slider=True)

    class CPB_PT_susp(_CPB_Panel, bpy.types.Panel):
        bl_label = "サスペンション"
        bl_parent_id = "CPB_PT_main"

        def draw(self, context):
            s = context.scene.cpb
            L = self.layout
            L.prop(s, "susp_freq")
            L.prop(s, "susp_damp")
            L.prop(s, "tire_profile")
            L.prop(s, "body_contact")
            L.prop(s, "pitch_mult")
            L.prop(s, "roll_mult")
            L.prop(s, "travel")

    class CPB_PT_drift(_CPB_Panel, bpy.types.Panel):
        bl_label = "ドリフト・スピン・横転"
        bl_parent_id = "CPB_PT_main"
        bl_options = {'DEFAULT_CLOSED'}

        def draw(self, context):
            s = context.scene.cpb
            L = self.layout
            box = L.box()
            box.prop(s, "drift", icon='MOD_CURVE')
            if s.drive_mode == "MANUAL":
                box.label(text="サイドブレーキで滑らせる", icon='INFO')
            elif s.drift:
                box.prop(s, "drift_angle")
                box.prop(s, "drift_r_start")
                box.prop(s, "drift_r_full")
                box.prop(s, "drift_freq")
                box.prop(s, "drift_damp")
                box.prop(s, "drift_min_speed")
                box.prop(s, "drift_use_range")
                if s.drift_use_range:
                    row = box.row(align=True)
                    row.prop(s, "drift_start")
                    row.prop(s, "drift_end")
            box = L.box()
            box.prop(s, "spin", icon='FILE_REFRESH')
            if s.spin:
                box.prop(s, "spin_frame")
                box.row().prop(s, "spin_dir", expand=True)
                box.prop(s, "spin_kick")
                box.prop(s, "spin_grip")
            box = L.box()
            box.prop(s, "rollover", icon='ORIENTATION_GIMBAL')
            if s.rollover:
                box.prop(s, "rollover_frame")
                box.row().prop(s, "rollover_dir", expand=True)
                box.prop(s, "rollover_rate")
                box.prop(s, "rollover_lift")
                box.prop(s, "rollover_slide")
                box.prop(s, "rollover_settle")
            box.prop(s, "body_mu")
            box.prop(s, "rollover_auto")

    class _CPB_Toggle(_CPB_Panel):
        """見出しにオン・オフのチェックがあるパネル"""
        bl_parent_id = "CPB_PT_main"
        bl_options = {'DEFAULT_CLOSED'}
        toggle = ""

        def draw_header(self, context):
            self.layout.prop(context.scene.cpb, self.toggle, text="")

    class CPB_PT_timing(_CPB_Toggle, bpy.types.Panel):
        bl_label = "到達タイミング"
        toggle = "use_timing"

        def draw(self, context):
            s = context.scene.cpb
            L = self.layout
            L.active = s.use_timing
            L.label(text="この地点をこのフレームに通る", icon='TIME')
            _list_ui(L, s, "timing_items", "CPB_UL_timing", "timing_index")
            L.operator("cpb.add_marker", icon='EMPTY_SINGLE_ARROW')
            if s.drive_mode != "PATH":
                L.label(text="コース自動走行のときだけ有効", icon='INFO')

    class CPB_PT_gears(_CPB_Toggle, bpy.types.Panel):
        bl_label = "ギア・エンジン回転数"
        toggle = "use_gears"

        def draw(self, context):
            s = context.scene.cpb
            L = self.layout
            L.active = s.use_gears
            L.prop(s, "gear_count")
            L.prop(s, "shift_rpm")
            L.prop(s, "idle_rpm")
            L.prop(s, "redline_rpm")
            L.prop(s, "shift_time")
            L.label(text="出力: cpb_rpm / cpb_gear", icon='INFO')

    class CPB_PT_surface(_CPB_Panel, bpy.types.Panel):
        bl_label = "路面・壁"
        bl_parent_id = "CPB_PT_main"
        bl_options = {'DEFAULT_CLOSED'}

        def draw(self, context):
            s = context.scene.cpb
            L = self.layout
            box = L.box()
            box.prop(s, "use_grip_map")
            if s.use_grip_map:
                if s.ground is not None:
                    box.prop_search(s, "grip_vgroup", s.ground, "vertex_groups")
                else:
                    box.label(text="先に地面を指定", icon='ERROR')
                box.prop(s, "grip_low")
                box.label(text="地面をウェイトペイントで塗る", icon='BRUSH_DATA')
            box = L.box()
            box.prop(s, "use_walls")
            if s.use_walls:
                box.prop(s, "wall_collection")
                box.prop(s, "wall_mu")
                box.label(text="面の表（法線）を道路側に", icon='INFO')

    class CPB_PT_barrier(_CPB_Toggle, bpy.types.Panel):
        bl_label = "タイヤバリヤ"
        toggle = "use_barrier"

        def draw(self, context):
            s = context.scene.cpb
            L = self.layout
            box = L.box()
            box.label(text="作成（カーブを選んで）", icon='MESH_TORUS')
            box.prop(s, "gen_side", text="")
            row = box.row(align=True)
            row.prop(s, "gen_rows")
            row.prop(s, "gen_stack")
            box.prop(s, "gen_colors")
            box.operator("cpb.make_barrier", icon='ADD')
            box.operator("cpb.update_barrier_tires", icon='FILE_REFRESH')
            col = L.column()
            col.active = s.use_barrier
            col.prop(s, "barrier_collection")
            col.prop(s, "barrier_stiff")
            col.prop(s, "barrier_scatter")
            if s.barrier_scatter:
                col.prop(s, "barrier_tire_mass")
                col.prop(s, "barrier_bounce")
                col.prop(s, "barrier_friction")

    class CPB_PT_multi(_CPB_Toggle, bpy.types.Panel):
        bl_label = "複数台"
        toggle = "use_multi"

        def draw(self, context):
            s = context.scene.cpb
            L = self.layout
            L.active = s.use_multi
            _list_ui(L, s, "cars", "CPB_UL_cars", "car_index")
            if 0 <= s.car_index < len(s.cars):
                it = s.cars[s.car_index]
                col = L.column(align=True)
                col.prop(it, "body")
                col.prop(it, "wheel_fl")
                col.prop(it, "wheel_fr")
                col.prop(it, "wheel_rl")
                col.prop(it, "wheel_rr")
                L.prop(it, "path")
                L.prop(it, "lane_offset")
                L.prop(it, "start_frame")
                L.prop(it, "start_speed")
                L.prop(it, "speed_mult")
                L.prop(it, "overtake")
                L.prop(it, "avoid")
                row = L.row(align=True)
                row.prop(it, "spin")
                if it.spin:
                    row.prop(it, "spin_frame", text="")
            L.prop(s, "follow_gap")
            L.prop(s, "overtake_offset")
            L.prop(s, "multi_collide")
            col = L.column(align=True)
            col.label(text="ばらけさせる")
            col.prop(s, "multi_scatter_lane")
            col.prop(s, "multi_scatter_speed")
            col.prop(s, "multi_scatter_gap")
            col.prop(s, "multi_scatter_seed")
            L.prop(s, "multi_lane_start")
            L.label(text="1台目のあとに順番に走らせます", icon='INFO')

    class CPB_PT_trailer(_CPB_Toggle, bpy.types.Panel):
        bl_label = "トレーラー"
        toggle = "use_trailer"

        def draw(self, context):
            s = context.scene.cpb
            L = self.layout
            L.active = s.use_trailer
            L.prop(s, "trailer_body")
            L.prop(s, "trailer_wheels")
            L.prop(s, "trailer_hitch")
            L.label(text="基準ポーズで連結した状態に置く", icon='INFO')

    class CPB_PT_fx(_CPB_Panel, bpy.types.Panel):
        bl_label = "演出"
        bl_parent_id = "CPB_PT_main"
        bl_options = {'DEFAULT_CLOSED'}

        def draw(self, context):
            s = context.scene.cpb
            L = self.layout
            box = L.box()
            box.prop(s, "use_skid", icon='MOD_DASH')
            if s.use_skid:
                box.prop(s, "skid_threshold")
                box.prop(s, "skid_opacity")
                box.prop(s, "skid_width")
            L.prop(s, "particle_style")
            if s.particle_style == 'TRIANGLE':
                L.prop(s, "tri_no_blur")
                L.label(text="焼き込み後は、スモーク・火花のモディファイアー欄でも直せます", icon='INFO')
            tri = s.particle_style == 'TRIANGLE'
            box = L.box()
            box.prop(s, "use_smoke", icon='OUTLINER_DATA_VOLUME')
            if s.use_smoke:
                box.prop(s, "smoke_color")
                box.prop(s, "smoke_threshold")
                box.prop(s, "smoke_amount")
                if tri:
                    box.prop(s, "tri_smoke_keep")
                box.prop(s, "smoke_size")
                if not tri:
                    box.prop(s, "smoke_grow")
                box.prop(s, "smoke_rise")
                box.prop(s, "smoke_life")
                if not tri:
                    box.prop(s, "smoke_opacity")
            box = L.box()
            box.prop(s, "use_dents", icon='MOD_SMOOTH')
            if s.use_dents:
                box.prop(s, "dent_strength")
                box.prop(s, "dent_radius")
                box.prop(s, "dent_depth_max")
                box.prop(s, "dent_threshold")
                box.prop(s, "dent_max")
            box = L.box()
            box.prop(s, "use_sparks", icon='LIGHT_SUN')
            if s.use_sparks:
                box.prop(s, "spark_color")
                if s.particle_style == 'TRIANGLE':
                    box.prop(s, "spark_color2")
                    box.prop(s, "spark_ratio2")
                    box.prop(s, "spark_size")
                    box.prop(s, "tri_spark_keep")
                box.prop(s, "spark_amount")
                box.prop(s, "spark_clearance")
            box = L.box()
            box.prop(s, "use_parts", icon='MOD_EXPLODE')
            if s.use_parts:
                box.prop(s, "parts_collection")
                box.prop(s, "parts_strength")
                box.prop(s, "parts_bounce")
            box = L.box()
            box.prop(s, "use_jiggle", icon='FORCE_HARMONIC')
            if s.use_jiggle:
                box.prop(s, "jiggle_collection")
                box.prop(s, "jiggle_freq")
                box.prop(s, "jiggle_damp")
                box.prop(s, "jiggle_amount")
            box = L.box()
            box.label(text="ライト", icon='LIGHT')
            box.prop(s, "brake_lights")
            box.prop(s, "reverse_lights")
            box.prop(s, "light_strength")
            row = box.row(align=True)
            row.operator("cpb.setup_lights", text="設定")
            row.operator("cpb.clear_lights", text="解除")

    class CPB_PT_rig(_CPB_Toggle, bpy.types.Panel):
        bl_label = "リグ（アーマチュア）"
        toggle = "use_armature"

        def draw(self, context):
            s = context.scene.cpb
            L = self.layout
            L.active = s.use_armature
            L.prop(s, "armature")
            if s.armature is not None:
                for p_ in ("bone_body", "bone_fl", "bone_fr", "bone_rl", "bone_rr", "bone_steer"):
                    L.prop_search(s, p_, s.armature.data, "bones")
            L.prop(s, "collision_mesh")
            L.label(text="タイヤ半径の指定が必要です", icon='INFO')

    class CPB_PT_camera(_CPB_Panel, bpy.types.Panel):
        bl_label = "カメラ"
        bl_parent_id = "CPB_PT_main"
        bl_options = {'DEFAULT_CLOSED'}

        def draw(self, context):
            s = context.scene.cpb
            L = self.layout
            L.prop(s, "cam_type", text="")
            L.prop(s, "cam_distance")
            L.prop(s, "cam_height")
            L.prop(s, "cam_smooth")
            L.prop(s, "cam_lens")
            if s.cam_type == "FIXED":
                L.prop(s, "cam_fixed_frame")
            if s.cam_type == "INCAR":
                L.row().prop(s, "cam_driver_side", expand=True)
                L.prop(s, "cam_eye_height")
            L.prop(s, "cam_set_active")
            L.operator("cpb.make_camera", icon='CAMERA_DATA')

    class CPB_PT_takes(_CPB_Panel, bpy.types.Panel):
        bl_label = "テイク"
        bl_parent_id = "CPB_PT_main"
        bl_options = {'DEFAULT_CLOSED'}

        def draw(self, context):
            s = context.scene.cpb
            L = self.layout
            L.prop(s, "keep_takes")
            L.template_list("CPB_UL_takes", "", s, "takes", s, "take_index", rows=3)
            row = L.row(align=True)
            row.operator("cpb.take_restore", icon='LOOP_BACK')
            row.operator("cpb.take_delete", text="", icon='TRASH')

    class CPB_PT_output(_CPB_Panel, bpy.types.Panel):
        bl_label = "出力・その他"
        bl_parent_id = "CPB_PT_main"
        bl_options = {'DEFAULT_CLOSED'}

        def draw(self, context):
            s = context.scene.cpb
            L = self.layout
            L.label(text="室内のハンドル:")
            L.prop(s, "steering_wheel", text="")
            if s.steering_wheel is not None:
                row = L.row(align=True)
                row.prop(s, "steer_axis", expand=True)
                row.prop(s, "steer_invert", toggle=True)
                L.prop(s, "steer_ratio")
            L.prop(s, "write_props")

    _classes = (CPB_TimingItem, CPB_CarItem, CPB_TakeItem, CPB_Settings,
                CPB_OT_bake, CPB_OT_clear, CPB_OT_capture, CPB_OT_detect_scale, CPB_OT_make_barrier, CPB_OT_update_barrier_tires,
                CPB_OT_list_edit, CPB_OT_add_marker,
                CPB_OT_take_restore, CPB_OT_take_delete, CPB_OT_make_camera,
                CPB_OT_setup_lights, CPB_OT_clear_lights,
                CPB_UL_timing, CPB_UL_cars, CPB_UL_takes,
                CPB_PT_main, CPB_PT_course, CPB_PT_drive, CPB_PT_input,
                CPB_PT_susp, CPB_PT_drift, CPB_PT_timing, CPB_PT_gears, CPB_PT_surface, CPB_PT_barrier,
                CPB_PT_multi, CPB_PT_trailer, CPB_PT_fx, CPB_PT_rig, CPB_PT_camera,
                CPB_PT_takes, CPB_PT_output)

    def register():
        for c in _classes:
            bpy.utils.register_class(c)
        bpy.types.Scene.cpb = PointerProperty(type=CPB_Settings)

    def unregister():
        del bpy.types.Scene.cpb
        for c in reversed(_classes):
            bpy.utils.unregister_class(c)

    if __name__ == "__main__":
        try:
            unregister()
        except Exception:
            pass
        register()

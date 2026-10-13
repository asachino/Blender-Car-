"""走行ライン（アウト・イン・アウト）を作る。ゲームには無い、Blender 用の追加機能。
コースは track.activate_map 済みであること。座標はゲームと同じ（Y が上）。"""
import math
from . import track as T


def _offsets(margin, kmin, mode):
    L = T.TRACK_LENGTH
    n = max(240, int(L))
    ds = L / n
    poses = [T.track_pose(i / n) for i in range(n)]
    # 符号付き曲率。正のとき外側はオフセット＋側（track.turn_info と同じ向き）
    k = []
    for i in range(n):
        a, b = poses[i - 1].tangent, poses[(i + 1) % n].tangent
        k.append(math.atan2(a.x * b.z - a.z * b.x, a.x * b.x + a.z * b.z) / (2 * ds))
    half = [max(0.0, T.road_half_width_at(i / n) - margin) for i in range(n)]
    med = [T.median_half_width_at(i / n) for i in range(n)]
    if mode == "CENTER":
        return n, ds, poses, [0.0] * n, k, half, med
    w = max(1, int(round(10 / ds)))
    ks = [sum(k[(i + q) % n] for q in range(-w, w + 1)) / (2 * w + 1) for i in range(n)]
    # 同じ向きに曲がり続ける区間を 1 つのコーナーとする（つながったヘアピンも 1 つ）
    start = next((i for i in range(n) if abs(ks[i]) <= kmin), 0)
    corners = []
    i = 0
    while i < n:
        j0 = (start + i) % n
        if abs(ks[j0]) > kmin:
            sg = 1.0 if ks[j0] > 0 else -1.0
            j = i
            while j + 1 < n and abs(ks[(start + j + 1) % n]) > kmin and (ks[(start + j + 1) % n] > 0) == (sg > 0):
                j += 1
            if (j - i) * ds > 8.0:
                corners.append(((start + i) * ds, (start + j) * ds, sg))
            i = j + 1
        else:
            i += 1
    # 同じ向きのコーナーが短い直線（30 m 未満）を挟んで続くときは 1 つにまとめる
    merged = []
    for c in corners:
        if merged and merged[-1][2] == c[2] and c[0] - merged[-1][1] < 30.0:
            merged[-1] = (merged[-1][0], c[1], c[2])
        else:
            merged.append(c)
    if len(merged) > 1 and merged[0][2] == merged[-1][2] and merged[0][0] + L - merged[-1][1] < 30.0:
        last = merged.pop()
        merged[0] = (last[0] - L, merged[0][1], merged[0][2])
    corners = merged
    if not corners:
        return n, ds, poses, [0.0] * n, k, half, med
    pts = []
    m = len(corners)
    apex = [s0 + .55 * (s1 - s0) for s0, s1, _ in corners]
    first_in = [s0 + min(70.0, .3 * (s1 - s0)) if s1 - s0 > 120 else a for (s0, s1, _), a in zip(corners, apex)]
    last_in = [s1 - min(45.0, .2 * (s1 - s0)) if s1 - s0 > 120 else a for (s0, s1, _), a in zip(corners, apex)]
    for c, (s0, s1, sg) in enumerate(corners):
        ln = s1 - s0
        D = min(40.0, 0.8 * ln + 15.0)
        pa = last_in[c - 1] - (L if c == 0 else 0.0)
        na = first_in[(c + 1) % m] + (L if c == m - 1 else 0.0)
        if s0 - D > pa + 10.0:
            pts.append((s0 - D, sg))
        if ln > 120.0:
            # 長いコーナー：早めに内側へ入り、出口の手前まで内側を保つ
            a0, a1 = s0 + min(70.0, .3 * ln), s1 - min(45.0, .2 * ln)
            pts.append((a0, -sg))
            pts.append((a1, -sg))
        else:
            pts.append((apex[c], -sg))
        if s1 + D < na - 10.0:
            pts.append((s1 + D, sg))
    pts = sorted((s % L, v) for s, v in pts)
    # 長い直線・ゆるい曲がりでは今の側を保ち、次のコーナーの 80 m 手前から寄せる
    held = []
    for j, (sa, va) in enumerate(pts):
        held.append((sa, va))
        sb, vb = pts[(j + 1) % len(pts)]
        gap = (sb - sa) % L
        if gap > 160.0 and abs(vb - va) > 1e-9:
            held.append(((sa + gap - 80.0) % L, va))
    pts = sorted(held)
    q = len(pts)
    v = []
    for i in range(n):
        sv = i * ds
        j = max((u for u in range(q) if pts[u][0] <= sv), default=q - 1)
        sa, va = pts[j]
        sb, vb = pts[(j + 1) % q]
        if sv < sa:
            sa -= L
        if sb <= sa:
            sb += L
        u = (sv - sa) / max(sb - sa, 1e-6)
        wgt = (1 - math.cos(math.pi * u)) / 2
        v.append(va + (vb - va) * wgt)
    off = [max(-1.0, min(1.0, v[i])) * half[i] for i in range(n)]
    return n, ds, poses, off, k, half, med


def _fit_median(off, half, med, margin, ds, slope=0.08):
    """中央分離帯のある区間は、その区間で多く使う側だけを走る（分離帯をまたがない）。
    区間の手前・先は横移動を slope（m/m）以下にして、なめらかに寄せる"""
    n = len(off)
    has = [m > .05 for m in med]
    if not any(has):
        return off
    out = list(off)
    start = next((i for i in range(n) if not has[i]), None)
    if start is None:
        side = 1.0 if sum(off) >= 0 else -1.0
        return [side * max(min(med[i] + margin, half[i]), side * out[i]) for i in range(n)]
    sections = []
    i = 0
    while i < n:
        if not has[(start + i) % n]:
            i += 1
            continue
        j = i
        while j + 1 < n and has[(start + j + 1) % n]:
            j += 1
        sections.append([(start + t_) % n for t_ in range(i, j + 1)])
        i = j + 1
    step = slope * ds
    for idx in sections:
        side = 1.0 if sum(off[t_] for t_ in idx) >= 0 else -1.0
        need = [-1e9] * n           # side 側へ need[i] 以上寄っていること
        for t_ in idx:
            need[t_] = min(med[t_] + margin, half[t_])
        for _ in range(2):           # 前後に傾き slope で広げる（輪なので 2 周）
            for i in range(n):
                need[i] = max(need[i], need[i - 1] - step)
            for i in range(n - 1, -1, -1):
                need[i] = max(need[i], need[(i + 1) % n] - step)
        for i in range(n):
            if side * out[i] < need[i]:
                out[i] = side * min(need[i], half[i])
    return out


def _limit_slope(off, half, ds, slope=0.12):
    """隣り合う点の横方向の差を slope（m/m）以下にする（近づけ合いを繰り返す）"""
    n = len(off)
    lim = slope * ds
    off = list(off)
    for _ in range(600):
        moved = False
        for i in range(n):
            j = (i + 1) % n
            d = off[j] - off[i]
            if abs(d) > lim + 1e-9:
                c = (d - (lim if d > 0 else -lim)) * .5
                off[i] += c
                off[j] -= c
                moved = True
        if not moved:
            break
    return [max(-half[i], min(half[i], off[i])) for i in range(n)]


def _smooth(off, half, med, ds, meters=6.0, passes=2):
    n = len(off)
    w = max(1, int(round(meters / ds)))
    for _ in range(passes):
        off = [sum(off[(i + q) % n] for q in range(-w, w + 1)) / (2 * w + 1) for i in range(n)]
    return [max(-half[i], min(half[i], off[i])) for i in range(n)]


def racing_line(margin=1.2, kmin=1 / 150.0, mode="RACING", center_offset=0.0):
    """戻り値: [(s, オフセット, 曲率)] を約 1 m おきに。mode は "RACING"（アウト・イン・アウト）か "CENTER" """
    n, ds, poses, off, k, half, med = _offsets(margin, kmin, mode)
    if mode == "CENTER":
        off = [center_offset] * n
    else:
        off = _smooth(off, half, med, ds)
        off = _fit_median(off, half, med, margin, ds)
        off = _limit_slope(off, half, ds)
        off = _smooth(off, half, med, ds, meters=4.0, passes=1)
        off = _fit_median(off, half, med, margin, ds)
    return [(i * ds, off[i], k[i]) for i in range(n)]


def bezier_points(line, straight=24.0, corner=8.0):
    """曲がり具合に合わせて間引いた制御点の位置（ゲーム座標）"""
    L = T.TRACK_LENGTH
    n = len(line)
    ds = L / n
    out = []
    s_next = 0.0
    for i, (s, off, k) in enumerate(line):
        if s + 1e-9 < s_next:
            continue
        ak = max(abs(line[(i + q) % n][2]) for q in range(-3, 4))
        step = corner if ak > 1 / 120 else 14.0 if ak > 1 / 400 else straight
        # オフセットが大きく変わる所（コーナーの出入り）は細かく
        doff = abs(line[(i + int(6 / ds)) % n][1] - off)
        if doff > 1.5:
            step = min(step, 10.0)
        out.append(T.track_pose(s / L, off).position)
        s_next = s + step
    if out and out[0].distanceTo(out[-1]) < 4.0:
        out.pop()
    return out

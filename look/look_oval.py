"""オーバルのルック調整（コピーした .blend の上で実行）

blender -b 入力.blend --python look_oval.py -- 出力.blend

・車: マテリアルのノード構成はそのまま。車ごとにマテリアルを複製して「色」だけ差し替える
      （ベース色 = カラーランプ/.004 の暗い側、リム = .002、縁の影 = .005 の端）
・サーキット: 落ち着いた配色にまとめ、地面には太陽のセル影（2段）を落とす
・空のグラデーション、遠景の空気感（ミスト）、ほんのりグロー・周辺減光
色は下の PALETTE / LIVERY を書き換えて再実行すれば調整できる。
"""
import bpy
import sys
from mathutils import Color


def hx(s, a=1.0):
    s = s.lstrip("#")
    c = [int(s[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c) + (a,)


# ---------------------------------------------------------------- 配色
# 車ごとのボディ色（ベース, 縁の影）。リムはベースを白に寄せて作る
LIVERY = {
    "R32": ("#1d5cff", "#0a1a55"),        # 主役: コバルトブルー
    "F40": ("#e3221c", "#4a0508"),        # ロッソ
    "カウンタック": ("#f4f3ee", "#3c4250"),  # パールホワイト
    "テスタロッサ": ("#16181d", "#000000"),  # グロスブラック
    "S2000": ("#ff9d1c", "#6a2a00"),      # オレンジ
    "F40_黄": ("#fff03a", "#6a4a00"),
    "カウンタック_緑": ("#10b46e", "#033a24"),
    "R32_青": ("#1fb3e8", "#063a55"),
}
TRIM = ("#4a505c", "#14171c")             # 車のボディ以外（ホイール・灯火など）の紫を置き換える色
TRIM_RIM_ALWAYS = False                   # True: ボディ以外のリム（赤→黄など）も無彩色にそろえる

PALETTE = {
    # サーキット（フラットな色: ランプの暗い側）
    "道路": ("#2b3039", "#434a56", "#262a32", "#3a414c"),   # 暗い面, 明るい面, 線の暗, 線の明
    "コンクリート": ("#c3c8cf", "#eceef0", "#aab1ba", "#e4e6e9"),
    "IR be967ef17aa53d98 | InkRacer #aaa993 | 0.86 | 0": ("#c3c8cf", "#eceef0", "#aab1ba", "#e4e6e9"),
    "芝": "#4f8a57",
    "丘": "#8fb39a",
    "黄線": "#ffcc1f",
    "スタンド赤": "#d8342b", "サーキット赤": "#d8342b",
    "スタンド青": "#1e3a6e", "サーキット青": "#1e3a6e",
    "スタンド灰": "#a3abb5", "建物白": "#f1f0eb", "サーキット黄": "#ffc21a",
    "ガードレール": "#e9ebee", "フェンス": "#cfd5dc", "濃灰": "#2b2f36",
    "マテリアル.023": "#1e3a6e", "チェッカー": "#f1f0eb", "ガラス": "#3b4e66", "照明灯": "#fff6df",
    "観客0": "#c95b52", "観客1": "#4f6fb5", "観客2": "#e6d36e", "観客3": "#ececec",
    "観客4": "#5d6168", "観客5": "#6aa572", "観客6": "#eba45a", "肌": "#e3c4a8",
}
SKY_TOP, SKY_HORIZON = "#3f86d6", "#e6eef0"
SHADOW = 0.62          # 地面の影の濃さ（色に掛ける値）
SHADOW_TINT = "#3d4a78"  # 影色（少し青紫に寄せる）
MIST = 0.35            # 遠景がどれだけ空の色に溶けるか


# ---------------------------------------------------------------- 車
def car_objects(sc):
    s = sc.cpb
    items = [("R32", s.body, [s.wheel_fl, s.wheel_fr, s.wheel_rl, s.wheel_rr])]
    for c in s.cars:
        items.append((c.body.name.split(".")[0], c.body, [c.wheel_fl, c.wheel_fr, c.wheel_rl, c.wheel_rr]))
    out = []
    for nm, b, ws in items:
        objs = [b] + list(b.children_recursive) + [w for w in ws if w]
        for w in ws:
            if w:
                objs += list(w.children_recursive)
        out.append((nm, [o for o in objs if o.type == 'MESH']))
    return out


def area(o):
    return sum(p.area for p in o.data.polygons) * max(o.scale) ** 2


def mix_white(c, t):
    return tuple(x + (1 - x) * t for x in c[:3]) + (1,)


def ramp(mat, name):
    n = mat.node_tree.nodes.get(name)
    return n if n is not None and n.type == 'VALTORGB' else None


def recolor_car(mat, base, shade, rim=None):
    r0, r4, r1, r2, r5 = (ramp(mat, n) for n in ("カラーランプ", "カラーランプ.004", "カラーランプ.001", "カラーランプ.002", "カラーランプ.005"))
    if r0 is None or r2 is None:
        return False
    for r in (r0, r4):
        if r is not None:
            r.color_ramp.elements[0].color = base
    rim0 = rim if rim is not None else mix_white(base, 0.35)
    rim1 = mix_white(rim, 0.45) if rim is not None else mix_white(base, 0.8)
    r2.color_ramp.elements[0].color = rim0
    r2.color_ramp.elements[-1].color = rim1
    if r5 is not None:
        r5.color_ramp.elements[-1].color = shade
    # 明るい色（黄・白）は陰の段を浅くしないと濁ってオリーブ色になる
    if r1 is not None and 0.2126 * base[0] + 0.7152 * base[1] + 0.0722 * base[2] > 0.45:
        e = r1.color_ramp.elements[0]
        sat = max(base[:3]) - min(base[:3])
        # 陰の段を色付きに: 黄は橙へ、白は青灰へ寄せる（灰色を掛けると濁るため）
        e.color = (0.95, 0.42, 0.16, 1) if sat > 0.4 else (0.42, 0.47, 0.58, 1)
    return True


def do_cars():
    done = {}
    for sc in bpy.data.scenes:
        if not hasattr(sc, "cpb") or sc.cpb.body is None:
            continue
        for nm, objs in car_objects(sc):
            key = nm if nm in LIVERY else nm.split("_")[0]
            lv = LIVERY.get(nm, LIVERY.get(key, LIVERY.get("_other", LIVERY["R32"])))
            base, shade = hx(lv[0]), hx(lv[1])
            rim = hx(lv[2]) if len(lv) > 2 else None
            # ボディの塗装 = 車の中で一番面積の大きいマテリアル
            acc = {}
            for o in objs:
                a = area(o) / max(1, len(o.material_slots))
                for s in o.material_slots:
                    if s.material and not s.material.name.startswith("OH_"):
                        acc[s.material.name] = acc.get(s.material.name, 0) + a
            if not acc:
                continue
            paint = max(acc, key=acc.get)
            for o in objs:
                for s in o.material_slots:
                    m = s.material
                    if m is None or m.name.startswith("OH_") or not m.use_nodes:
                        continue
                    src = m.get("look_src", m.name)
                    is_paint = src == paint
                    k = (src, nm if is_paint else "TRIM")
                    if k not in done:
                        m2 = bpy.data.materials[src].copy()
                        m2.name = f"{src}_{nm}" if is_paint else f"{src}_トリム"
                        m2["look_src"] = src
                        if is_paint:
                            recolor_car(m2, base, shade, rim)
                        else:
                            recolor_trim(m2)
                        done[k] = m2
                    # メッシュを他の車と共有していても、この車だけ色が変わるようにオブジェクト側に割り当てる
                    s.link = 'OBJECT'
                    s.material = done[k]
            print("CAR", sc.name, nm, "paint =", paint)


PURPLE = hx("#a200ff")


def recolor_trim(mat):
    # 下地の紫（未調整のテンプレート色）だけを落ち着いた色に置き換える
    hit = False
    for n in mat.node_tree.nodes:
        if n.type != 'VALTORGB':
            continue
        for e in n.color_ramp.elements:
            if sum(abs(a - b) for a, b in zip(e.color[:3], PURPLE[:3])) < 0.05:
                e.color = hx(TRIM[0])
                hit = True
    r5 = ramp(mat, "カラーランプ.005")
    if r5 is not None and hit:
        r5.color_ramp.elements[-1].color = hx(TRIM[1])
    r2 = ramp(mat, "カラーランプ.002")
    if r2 is not None and (hit or TRIM_RIM_ALWAYS):
        r2.color_ramp.elements[0].color = hx("#9aa7b8")
        r2.color_ramp.elements[-1].color = hx("#e6ecf3")
    return hit


# ---------------------------------------------------------------- サーキット
def flat(mat, col):
    """ノードを「その色を出すだけ」にまとめる（陰影なしのフラット）"""
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    rgb = nt.nodes.new("ShaderNodeRGB")
    rgb.outputs[0].default_value = col
    nt.links.new(rgb.outputs[0], out.inputs["Surface"])
    return rgb, out


def set_stops(mat, cols):
    """フレネル／ワイヤーフレームのランプの色を差し替える（構成はそのまま）"""
    dark, light, wdark, wlight = (hx(c) for c in cols)
    for n in mat.node_tree.nodes:
        if n.type != 'VALTORGB':
            continue
        src = [l.from_node.type for l in mat.node_tree.links if l.to_node == n]
        el = n.color_ramp.elements
        if "WIREFRAME" in src:
            el[0].color, el[-1].color = wdark, wlight
        elif "FRESNEL" in src:
            el[0].color, el[-1].color = dark, light


def add_shadow(mat, strength=SHADOW):
    """今の出力色に、太陽の影（セル影2段）を掛ける"""
    nt = mat.node_tree
    out = next((n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output), None)
    if out is None or not out.inputs["Surface"].is_linked or "look_shadow" in mat:
        return
    src = out.inputs["Surface"].links[0].from_socket
    dif = nt.nodes.new("ShaderNodeBsdfDiffuse")
    s2r = nt.nodes.new("ShaderNodeShaderToRGB")
    bw = nt.nodes.new("ShaderNodeRGBToBW")
    rp = nt.nodes.new("ShaderNodeValToRGB")
    rp.color_ramp.interpolation = 'CONSTANT'
    rp.color_ramp.elements[0].position = 0.0
    rp.color_ramp.elements[1].position = 0.55   # 空の明るさ（環境光）だけの所 = 影
    tint = hx(SHADOW_TINT)
    rp.color_ramp.elements[0].color = tuple(strength + (1 - strength) * t * 0.6 for t in tint[:3]) + (1,)
    rp.color_ramp.elements[1].color = (1, 1, 1, 1)
    mul = nt.nodes.new("ShaderNodeMix")
    mul.data_type = 'RGBA'
    mul.blend_type = 'MULTIPLY'
    mul.inputs[0].default_value = 1.0
    nt.links.new(dif.outputs[0], s2r.inputs[0])
    nt.links.new(s2r.outputs[0], bw.inputs[0])
    nt.links.new(bw.outputs[0], rp.inputs[0])
    nt.links.new(src, mul.inputs[6])
    nt.links.new(rp.outputs[0], mul.inputs[7])
    em = nt.nodes.new("ShaderNodeEmission")
    nt.links.new(mul.outputs[2], em.inputs[0])
    nt.links.new(em.outputs[0], out.inputs["Surface"])
    for i, n in enumerate((dif, s2r, bw, rp, mul, em)):
        n.location = (out.location.x - 900 + i * 150, out.location.y - 300)
    mat["look_shadow"] = True


def do_circuit():
    for name, v in PALETTE.items():
        m = bpy.data.materials.get(name)
        if m is None:
            continue
        m.use_nodes = True
        if isinstance(v, tuple) and any(n.type == 'VALTORGB' for n in m.node_tree.nodes):
            set_stops(m, v)
        elif isinstance(v, tuple):      # ランプの無い普通のマテリアルは1色のフラットに
            flat(m, hx(v[0]))
        elif name == "芝":
            flat(m, hx(v))
        elif name == "黄線":
            flat(m, hx(v))
        elif name == "フェンス":
            flat(m, hx(v, 1))
        else:
            flat(m, hx(v))
    # 地面・壁・スタンドに影を落とす
    for name in SHADOW_MATS:
        m = bpy.data.materials.get(name)
        if m is not None:
            add_shadow(m)


# 太陽の影を落とすマテリアル（地面・壁・スタンドなど）
SHADOW_MATS = ["道路", "コンクリート", "IR be967ef17aa53d98 | InkRacer #aaa993 | 0.86 | 0", "芝", "黄線",
               "ガードレール", "スタンド赤", "スタンド青", "スタンド灰", "建物白", "サーキット赤", "サーキット青", "サーキット黄"]


# ---------------------------------------------------------------- 空・ライト・仕上げ
def sky_world():
    w = bpy.data.worlds.get("LOOK_空") or bpy.data.worlds.new("LOOK_空")
    w.use_nodes = True
    nt = w.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    rp = nt.nodes.new("ShaderNodeValToRGB")
    rp.color_ramp.elements[0].position = 0.0
    rp.color_ramp.elements[0].color = hx(SKY_HORIZON)
    rp.color_ramp.elements[1].position = 0.45
    rp.color_ramp.elements[1].color = hx(SKY_TOP)
    bg = nt.nodes.new("ShaderNodeBackground")
    out = nt.nodes.new("ShaderNodeOutputWorld")
    nt.links.new(tc.outputs["Generated"], sep.inputs[0])
    nt.links.new(sep.outputs["Z"], rp.inputs[0])
    nt.links.new(rp.outputs[0], bg.inputs[0])
    nt.links.new(bg.outputs[0], out.inputs[0])
    w.mist_settings.start = 40
    w.mist_settings.depth = 520
    w.mist_settings.falloff = 'QUADRATIC'
    return w


def finish(sc, w):
    sc.world = w
    r = sc.render
    r.film_transparent = False
    sc.view_settings.view_transform = 'Standard'
    sc.view_settings.look = 'None'
    ee = sc.eevee
    ee.taa_render_samples = max(ee.taa_render_samples, 32)
    ee.use_soft_shadows = True
    ee.use_shadows = True
    ee.shadow_cascade_size = '4096'
    ee.use_gtao = False
    for o in sc.objects:
        if o.type == 'LIGHT':
            if o.name.startswith("CPB_確認用"):
                o.hide_render = True
            else:
                o.data.shadow_cascade_max_distance = 260
                o.data.shadow_cascade_count = 4
                o.data.angle = 0.02
    for vl in sc.view_layers:
        vl.use_pass_mist = True
    sc.use_nodes = True
    nt = sc.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    rl = nt.nodes.new("CompositorNodeRLayers")
    rl.scene = sc
    # 遠景を空の色に溶かす
    mf = nt.nodes.new("CompositorNodeMath")
    mf.operation = 'MULTIPLY'
    mf.inputs[1].default_value = MIST
    mix = nt.nodes.new("CompositorNodeMixRGB")
    mix.inputs[2].default_value = hx(SKY_HORIZON)
    nt.links.new(rl.outputs["Mist"], mf.inputs[0])
    nt.links.new(mf.outputs[0], mix.inputs[0])
    nt.links.new(rl.outputs["Image"], mix.inputs[1])
    # ほんのりグロー
    gl = nt.nodes.new("CompositorNodeGlare")
    gl.glare_type = 'FOG_GLOW'
    gl.quality = 'MEDIUM'
    gl.threshold = 0.92
    gl.mix = -0.88
    gl.size = 8
    nt.links.new(mix.outputs[0], gl.inputs[0])
    # 色味（影を少し青く、明るい所を少し暖かく）
    cb = nt.nodes.new("CompositorNodeColorBalance")
    cb.correction_method = 'LIFT_GAMMA_GAIN'
    cb.lift = (0.985, 0.995, 1.03)
    cb.gain = (1.03, 1.01, 0.985)
    nt.links.new(gl.outputs[0], cb.inputs[1])
    # 周辺減光
    em = nt.nodes.new("CompositorNodeEllipseMask")
    em.width, em.height = 1.25, 1.25
    bl = nt.nodes.new("CompositorNodeBlur")
    bl.filter_type = 'FAST_GAUSS'
    bl.use_relative = True
    bl.factor_x = bl.factor_y = 30
    bl.size_x = bl.size_y = 300
    vg = nt.nodes.new("CompositorNodeMixRGB")
    vg.blend_type = 'MULTIPLY'
    vg.inputs[0].default_value = 0.22
    nt.links.new(em.outputs[0], bl.inputs[0])
    nt.links.new(cb.outputs[0], vg.inputs[1])
    nt.links.new(bl.outputs[0], vg.inputs[2])
    comp = nt.nodes.new("CompositorNodeComposite")
    nt.links.new(vg.outputs[0], comp.inputs[0])
    for i, n in enumerate((rl, mf, mix, gl, cb, em, bl, vg, comp)):
        n.location = (i * 220, 0)


def main():
    do_cars()
    do_circuit()
    w = sky_world()
    for sc in bpy.data.scenes:
        finish(sc, w)
    out = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else None
    if out:
        bpy.ops.wm.save_as_mainfile(filepath=out, compress=True)
        print("SAVED", out)


if __name__ == "__main__":
    main()

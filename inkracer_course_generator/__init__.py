bl_info = {
    "name": "InkRacer コース自動生成",
    "author": "InkRacer 移植",
    "version": (1, 2, 0),
    "blender": (4, 1, 0),
    "location": "3Dビュー > サイドバー(N) > InkRacer",
    "description": "InkRacer のコース自動生成（サーキット・立体交差・地形ルート・見せ場・市街地・峠、景観、夜、インク表現）をそのまま Blender で",
    "category": "Add Mesh",
}

import json
import os
import random
import time

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty, PointerProperty, StringProperty
from bpy_extras.io_utils import ExportHelper

HERE = os.path.dirname(os.path.abspath(__file__))
_TEMPLATE = None

LAYOUTS = [("circuit", "サーキット", "周回サーキット（立体交差・地形ルート・見せ場を選べます）"),
           ("city", "市街地 / 深夜ドライブ", "4車線の環状幹線＋街区道路。夜のシーンになります"),
           ("touge", "峠道 / ヘアピンと尾根越え", "頂上まで登って別の道で下る山道")]
ROUTES = [("classic", "従来の地形", ""), ("ridge", "尾根を走る", ""), ("valley", "谷を渡る", ""),
          ("mountainside", "山腹を登る", "")]
WEATHER = [("dry", "晴れ（乾いた路面）", ""), ("wet", "濡れた路面", ""), ("rain", "雨", "")]
INK_MODES = [("AUTO", "ゲームと同じ（昼=青インク／夜=夜用）", ""), ("P0", "青インク", ""), ("P1", "鉛筆", ""),
             ("P2", "セピア", ""), ("P3", "設計図", ""), ("NIGHT", "夜用", ""), ("CUSTOM", "カスタム", ""),
             ("NONE", "インク表現なし", "輪郭線と手描きレンダー用シーンを作りません")]
PATTERNS = [("mixed", "ミックス", ""), ("hatch", "ハッチング", ""), ("halftone", "網点", "")]


def _template():
    global _TEMPLATE
    if _TEMPLATE is None:
        with open(os.path.join(HERE, "importer_template.txt"), encoding="utf-8") as f:
            _TEMPLATE = f.read()
    return _TEMPLATE


def _on_layout(self, context):
    if self.layout == "touge":
        # ゲームのマップ選択画面と同じ：峠を選ぶと峠向けの初期値になる
        self.size, self.complexity, self.bends, self.technicality, self.elevation = 450, 3, 70, 60, 24


class INKRACER_Props(bpy.types.PropertyGroup):
    layout: EnumProperty(name="レイアウト", items=LAYOUTS, default="circuit", update=_on_layout)
    seed: IntProperty(name="シード", min=0, max=999999, default=73)
    size: IntProperty(name="広さ", min=260, max=600, default=350, step=10)
    complexity: IntProperty(name="複雑さ", min=1, max=5, default=3)
    bends: IntProperty(name="カーブの強さ", min=0, max=100, default=40, step=5)
    elevation: IntProperty(name="高低差", min=0, max=24, default=12)
    crossings: IntProperty(name="立体交差数", min=0, max=3, default=1)
    technicality: IntProperty(name="テクニカル度", min=0, max=100, default=35, step=5)
    terrain_route: EnumProperty(name="地形に沿うルート", items=ROUTES, default="classic")
    lm_crossing: BoolProperty(name="立体交差", default=False)
    lm_bridge: BoolProperty(name="長い橋", default=False)
    lm_tunnel: BoolProperty(name="トンネル", default=False)
    lm_tower: BoolProperty(name="タワーを望む直線", default=False)
    scenery_density: IntProperty(name="配置密度", min=0, max=200, default=100, step=10)
    scenery_seed: IntProperty(name="配置シード", min=0, max=999999, default=73)
    night_enabled: BoolProperty(name="夜にする", default=False)
    night_brightness: FloatProperty(name="明るさ", min=.5, max=2, default=1)
    night_warmth: FloatProperty(name="街灯の暖かさ", min=0, max=1, default=.65)
    night_bloom: FloatProperty(name="ブルーム", min=0, max=1, default=.35)
    night_weather: EnumProperty(name="天気", items=WEATHER, default="dry")
    night_traffic: IntProperty(name="交通量", min=0, max=16, default=8)
    night_high_beam: BoolProperty(name="ハイビーム", default=False)
    ink_mode: EnumProperty(name="インク", items=INK_MODES, default="AUTO")
    ink_paper: FloatVectorProperty(name="紙", subtype="COLOR_GAMMA", size=3, min=0, max=1, default=(0.957, 0.945, 0.875))
    ink_ink: FloatVectorProperty(name="インク", subtype="COLOR_GAMMA", size=3, min=0, max=1, default=(0.145, 0.18, 0.463))
    ink_accent: FloatVectorProperty(name="アクセント", subtype="COLOR_GAMMA", size=3, min=0, max=1, default=(0.698, 0.31, 0.259))
    ink_pattern: EnumProperty(name="模様", items=PATTERNS, default="mixed")
    real_tires: BoolProperty(name="タイヤバリヤを本物のタイヤの形に", default=True,
                             description="オフにするとゲームと同じドーナツ形（浮き輪のような形）になります")
    make_line: BoolProperty(name="走行ライン（ベジェ）も作る", default=True,
                            description="コースの中心線を閉じたカーブとして作ります（Car Physics Baker の「コース」に使えます）")
    line_kind: EnumProperty(name="ラインの種類", default="RACING", items=[
        ("RACING", "レーシングライン（アウト・イン・アウト）", "コーナーの手前で外、頂点で内、立ち上がりで外を通るライン"),
        ("CENTER", "中心線", "コースの中心（ずらし量を指定可）")])
    line_margin: FloatProperty(name="路肩からの余裕", default=1.2, min=0.0, max=4.0, unit="LENGTH",
                               description="レーシングラインが道路の端に近づける限界（車体の半分＋すき間）")
    line_offset: FloatProperty(name="中心からのずらし", default=0.0, unit="LENGTH",
                               description="正の値で進行方向の右側、負の値で左側へずらします")
    report: StringProperty(default="")


def _params(p):
    v = {"seed": p.seed, "size": p.size, "complexity": p.complexity, "bends": p.bends, "elevation": p.elevation,
         "crossings": p.crossings, "technicality": p.technicality}
    if p.layout != "circuit":
        v["layout"] = p.layout
    if p.terrain_route != "classic":
        v["terrainRoute"] = p.terrain_route
    lm = [k for k in ("crossing", "bridge", "tunnel", "tower") if getattr(p, "lm_" + k)]
    if lm:
        v["landmarks"] = lm
    return v


def _hex(c):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(x * 255)))) for x in c)


def _night(p):
    return {"enabled": p.night_enabled or p.layout == "city", "brightness": p.night_brightness, "warmth": p.night_warmth,
            "bloom": p.night_bloom, "weather": p.night_weather, "traffic": p.night_traffic,
            "highBeam": p.night_high_beam}


def _ink(p, night_on):
    from .inkgen import export as E
    if p.ink_mode == "AUTO":
        return dict(E.DEFAULT_NIGHT_INK if night_on else E.DEFAULT_INK)
    if p.ink_mode.startswith("P"):
        return dict(E.INK_PRESETS[int(p.ink_mode[1])][1])
    if p.ink_mode == "NIGHT":
        return dict(E.DEFAULT_NIGHT_INK)
    if p.ink_mode == "CUSTOM":
        return {"paper": _hex(p.ink_paper), "ink": _hex(p.ink_ink), "accent": _hex(p.ink_accent), "pattern": p.ink_pattern}
    return None


def _collection_label(name):
    label = "InkRacer | "
    for ch in name:
        if len((label + ch).encode("utf-8")) > 42:
            break
        label += ch
    return label


def _summary(m):
    """マップ選択画面の説明文と検証（急カーブ・急勾配・道路間隔・交差の上下間隔）"""
    from .inkgen import maps as M
    pts = M.preview_points(m)
    length = sum(pts[i + 1].distanceTo(pts[i]) for i in range(len(pts) - 1))
    ys = [q.y for q in pts]
    lines = [m["name"], "全長 約%d m ／ 高低差 %d m" % (round(length), round(max(ys) - min(ys)))]
    par = m.get("parameters") or {}
    if par.get("layout") != "touge" and par.get("layout") != "city":
        n = len([c for c in M.map_crossings(m) if c["clearance"] >= 10])
        lines.append("実際の立体交差：%d箇所" % n)
    if m.get("features"):
        lines.append("見せ場：" + "・".join(M.LANDMARKS[f["kind"]] for f in m["features"]))
    for msg in M.validate_map(m):
        lines.append("⚠ " + msg)
    return "\n".join(lines)


class INKRACER_OT_check(bpy.types.Operator):
    bl_idname = "inkracer.check"
    bl_label = "コースを確認"
    bl_description = "今の条件でコースの形だけを作り、全長・高低差・注意点を表示します（シーンは変えません）"

    def execute(self, context):
        from .inkgen import maps as M
        p = context.scene.inkracer
        p.report = _summary(M.generate_map(_params(p)))
        return {"FINISHED"}


def build_course(context, p):
    from .inkgen import maps as M, export as E, track as T
    wm = context.window_manager
    steps = ["コース形状", "地形", "道路", "建物・景観", "輪郭線", "Blender へ配置"]
    wm.progress_begin(0, len(steps))
    t0 = time.time()

    def say(label):
        if label in steps:
            wm.progress_update(steps.index(label))
        print("[InkRacer] %s (%.1fs)" % (label, time.time() - t0))

    try:
        say("コース形状")
        m = M.generate_map(_params(p))
        night = _night(p)
        m["night"] = night
        ink = _ink(p, night["enabled"])
        from .inkgen import venue as V
        V.REAL_TIRES = p.real_tires
        scene = E.build_environment(m, {"density": p.scenery_density, "seed": p.scenery_seed}, ink, progress=say)
        if ink is None:
            scene["inkStyle"] = None
        say("Blender へ配置")
        ns = {"__name__": "inkracer_import", "__INKRACER_SCENE__": scene,
              "__INKRACER_COLLECTION__": _collection_label(m["name"])}
        exec(compile(_template(), "InkRacer importer", "exec"), ns)
        line = None
        if p.make_line:
            line = _make_line(ns, T, p)
        p.report = _summary(m)
        return m, ns, line, time.time() - t0
    finally:
        wm.progress_end()


def _make_line(ns, T, p):
    """走行ラインをベジェカーブ（自動ハンドル）で作り、座標変換の親（InkRacer Coordinate Root）の子にする。
    曲がりの強い所は細かく、直線は粗く制御点を打つので、後から手で直しやすい"""
    from .inkgen import racing as R
    root, track_col, scene_id = ns["COORDINATE_ROOT"], ns["TRACK"], ns["SCENE"]["id"]
    line = R.racing_line(margin=p.line_margin, mode=p.line_kind, center_offset=p.line_offset)
    pts = R.bezier_points(line)
    name = "InkRacer 走行ライン" if p.line_kind == "RACING" else "InkRacer 中心線"
    cu = bpy.data.curves.new(name, "CURVE")
    cu["ink_racer_id"] = scene_id
    cu.dimensions = "3D"
    cu.resolution_u = 12
    sp = cu.splines.new("BEZIER")
    sp.bezier_points.add(len(pts) - 1)
    for bp, q in zip(sp.bezier_points, pts):
        bp.co = (q.x, q.y, q.z)
        bp.handle_left_type = bp.handle_right_type = "AUTO"
    sp.use_cyclic_u = True
    ob = bpy.data.objects.new(name, cu)
    ob["ink_racer_id"] = scene_id
    track_col.objects.link(ob)
    ob.parent = root
    ob.matrix_parent_inverse.identity()
    return ob


def _fit_views(context):
    """コースは数 km あるので、3D ビューの表示距離（クリップ）を広げ、コース全体が収まる位置から見る"""
    from mathutils import Vector
    from .inkgen import track as T
    win = context.window
    if win is None or T.activeMap is None:
        return
    b = T.track_bounds()
    k = 1 / context.scene.unit_settings.scale_length
    ys = [s.position.y for s in T.samples]
    # ゲームの座標（Y が上）→ Blender（Z が上）
    center = Vector(((b["minX"] + b["maxX"]) / 2, -(b["minZ"] + b["maxZ"]) / 2, (min(ys) + max(ys)) / 2)) * k
    extent = max(b["maxX"] - b["minX"], b["maxZ"] - b["minZ"]) * k
    for area in win.screen.areas:
        if area.type != "VIEW_3D":
            continue
        space = area.spaces.active
        space.clip_start = max(space.clip_start, 0.1 * k)
        space.clip_end = max(space.clip_end, 12000.0 * k)
        r3d = space.region_3d
        if r3d is not None and r3d.view_perspective != "CAMERA":
            r3d.view_location = center
            r3d.view_distance = extent * 1.1


class INKRACER_OT_generate(bpy.types.Operator):
    bl_idname = "inkracer.generate"
    bl_label = "この条件で生成"
    bl_description = "ゲームの自動生成と同じ計算でコース・地形・建物・景観を作ります（同じ ID のコースは置き換えます）"
    bl_options = {"REGISTER"}

    new_seed: BoolProperty(default=False, options={"SKIP_SAVE"})

    def execute(self, context):
        p = context.scene.inkracer
        if self.new_seed:
            p.seed = random.randrange(1000000)
        try:
            m, ns, line, dt = build_course(context, p)
        except Exception as e:
            self.report({"ERROR"}, "生成できませんでした: %s" % e)
            raise
        _fit_views(context)
        msg = "%s を作りました（%.1f 秒）" % (m["name"], dt)
        if ns.get("COURSE") is not None and ns["COURSE"].get("ink_racer_preview_scene"):
            msg += "。手描きレンダーはシーン「%s」" % ns["COURSE"]["ink_racer_preview_scene"].name
        self.report({"INFO"}, msg)
        return {"FINISHED"}


def _environment(context):
    from .inkgen import maps as M, export as E
    p = context.scene.inkracer
    m = M.generate_map(_params(p))
    m["night"] = _night(p)
    ink = _ink(p, m["night"]["enabled"])
    from .inkgen import venue as V
    V.REAL_TIRES = p.real_tires
    scene = E.build_environment(m, {"density": p.scenery_density, "seed": p.scenery_seed}, ink)
    if ink is None:
        scene["inkStyle"] = None
    return m, scene


class INKRACER_OT_export_json(bpy.types.Operator, ExportHelper):
    bl_idname = "inkracer.export_json"
    bl_label = "環境JSONを書き出す"
    bl_description = "ゲームの「環境JSON」と同じ形式で書き出します"
    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})

    def execute(self, context):
        m, scene = _environment(context)
        with open(self.filepath, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(scene, ensure_ascii=False, indent=2) + "\n")
        self.report({"INFO"}, "書き出しました: " + self.filepath)
        return {"FINISHED"}


class INKRACER_OT_export_py(bpy.types.Operator, ExportHelper):
    bl_idname = "inkracer.export_py"
    bl_label = "Blender Python を書き出す"
    bl_description = "ゲームの「Blender Python」と同じく、実行するとコースを作るスクリプトを書き出します"
    filename_ext = ".py"
    filter_glob: StringProperty(default="*.py", options={"HIDDEN"})

    def execute(self, context):
        m, scene = _environment(context)
        text = json.dumps(scene, ensure_ascii=False, indent=2) + "\n"
        script = _template().replace("SCENE = __INKRACER_SCENE__", "SCENE = json.loads(" + json.dumps(text) + ")", 1)
        script = script.replace("COLLECTION_NAME = __INKRACER_COLLECTION__",
                                "COLLECTION_NAME = " + json.dumps(_collection_label(m["name"]), ensure_ascii=False), 1)
        with open(self.filepath, "w", encoding="utf-8", newline="\n") as f:
            f.write(script)
        self.report({"INFO"}, "書き出しました: " + self.filepath)
        return {"FINISHED"}


class INKRACER_PT_main(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "InkRacer"
    bl_label = "コース自動生成"

    def draw(self, context):
        p = context.scene.inkracer
        lay = self.layout
        lay.label(text="レイアウト")
        lay.prop(p, "layout", text="")
        if p.layout == "touge":
            lay.label(text="長短のカーブ・S字・ヘアピンが混ざる山道", icon="INFO")
        elif p.layout == "city":
            lay.label(text="環状幹線＋街区道路の夜の街（平坦）", icon="INFO")
        col = lay.column()
        col.enabled = p.layout == "circuit"
        col.label(text="地形に沿うルート")
        col.prop(p, "terrain_route", text="")
        if p.layout != "touge":
            box = lay.box()
            box.enabled = p.layout != "city"
            box.label(text="見せ場（複数選択）")
            col = box.column(align=True)
            for k in ("crossing", "bridge", "tunnel", "tower"):
                col.prop(p, "lm_" + k)
        lay.prop(p, "seed")
        col = lay.column(align=True)
        for key in ("size", "complexity", "bends", "elevation", "crossings", "technicality"):
            if p.layout == "city" and key not in ("size", "bends"):
                continue
            if p.layout == "touge" and key == "crossings":
                continue
            if p.layout == "touge" and key == "complexity":
                col.prop(p, key, text="山腹の折り返し区間（%d区間）" % (3 + 2 * ((p.complexity - 1) // 2)))
            else:
                col.prop(p, key)
        col = lay.column(align=True)
        col.scale_y = 1.3
        col.operator("inkracer.generate", text="この条件で生成", icon="PLAY").new_seed = False
        col.operator("inkracer.generate", text="別のシードで生成", icon="FILE_REFRESH").new_seed = True
        lay.operator("inkracer.check", icon="VIEWZOOM")
        if p.report:
            box = lay.box()
            for i, ln in enumerate(p.report.split("\n")):
                if ln.startswith("⚠ "):
                    for k, part in enumerate(_wrap(ln[2:], 18)):
                        box.label(text=part, icon="ERROR" if k == 0 else "BLANK1")
                else:
                    for k, part in enumerate(_wrap(ln, 26)):
                        box.label(text=part, icon=("AUTO" if i == 0 else "NONE") if k == 0 else "BLANK1")


def _wrap(text, n):
    return [text[i:i + n] for i in range(0, len(text), n)] or [""]


class INKRACER_PT_look(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "InkRacer"
    bl_label = "景観・夜・インク"
    bl_parent_id = "INKRACER_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        p = context.scene.inkracer
        lay = self.layout
        col = lay.column(align=True)
        col.prop(p, "scenery_density")
        col.prop(p, "scenery_seed")
        lay.prop(p, "real_tires")
        box = lay.box()
        row = box.row()
        row.prop(p, "night_enabled")
        if p.layout == "city":
            row.label(text="市街地は常に夜")
        sub = box.column(align=True)
        sub.enabled = p.night_enabled or p.layout == "city"
        for k in ("night_brightness", "night_warmth", "night_bloom", "night_traffic", "night_high_beam"):
            sub.prop(p, k)
        sub.label(text="天気")
        sub.prop(p, "night_weather", text="")
        box = lay.box()
        box.label(text="インク表現")
        box.prop(p, "ink_mode", text="")
        if p.ink_mode == "CUSTOM":
            for k in ("ink_paper", "ink_ink", "ink_accent", "ink_pattern"):
                box.prop(p, k)
        box = lay.box()
        box.prop(p, "make_line")
        r = box.column()
        r.enabled = p.make_line
        r.prop(p, "line_kind", text="")
        if p.line_kind == "RACING":
            r.prop(p, "line_margin")
        else:
            r.label(text="中心からのずらし（右が＋）")
            r.prop(p, "line_offset", text="")


class INKRACER_PT_export(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "InkRacer"
    bl_label = "書き出し（ゲームと同じ形式）"
    bl_parent_id = "INKRACER_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        col = self.layout.column(align=True)
        col.operator("inkracer.export_json", icon="EXPORT")
        col.operator("inkracer.export_py", icon="SCRIPT")


CLASSES = (INKRACER_Props, INKRACER_OT_check, INKRACER_OT_generate, INKRACER_OT_export_json, INKRACER_OT_export_py,
           INKRACER_PT_main, INKRACER_PT_look, INKRACER_PT_export)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.Scene.inkracer = PointerProperty(type=INKRACER_Props)


def unregister():
    del bpy.types.Scene.inkracer
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)

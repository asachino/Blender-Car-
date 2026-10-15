"""グラフィック寄りのルック（背景の色数を絞る）。4案から選ぶ

blender -b 入力.blend --python look_graphic.py -- 出力.blend A|B|C|D

look_oval.py の仕組み（車はノードそのまま色だけ差し替え・セル影・ミスト）を使い、
配色だけを案ごとに入れ替える。背景は「空・遠景・中間・暗部・明部・差し色」の6色以内。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import look_oval as L  # noqa: E402

# 背景: sky=空（単色）, far=山・丘, mid=芝・木, dark=路面, light=壁・建物, accent=差し色, shadow=影色
# 車: (ボディ, 縁の影, リム[省略可])
THEMES = {
    "A": dict(  # 主役だけ色。背景はブルーグレーの単色系
        bg=dict(sky="#b7cadb", far="#9db3c7", mid="#7d95ab", dark="#2d3642", light="#e9eef3", accent="#ff6a13", shadow="#4a5d7a"),
        cars={"R32": ("#ff6a13", "#5a1a00"),
              "F40": ("#f2f3f5", "#4a5466"), "カウンタック": ("#b9c0c9", "#3a414c"),
              "テスタロッサ": ("#15171b", "#000000"), "S2000": ("#6b7380", "#1c2027"),
              "F40_黄": ("#2a2e35", "#0a0b0d"), "カウンタック_緑": ("#f2f3f5", "#4a5466"),
              "R32_青": ("#8d95a1", "#2a2f37")}),
    "B": dict(  # 2チーム（紺×オレンジ / 白×赤）。背景はクリームの単色系
        bg=dict(sky="#efe4cf", far="#ddcfb2", mid="#c4b48c", dark="#3a3a40", light="#fbf6ea", accent="#e2402a", shadow="#8a6f55"),
        cars={"R32": ("#1b2a5c", "#070c1f", "#ff7a1a"), "カウンタック": ("#1b2a5c", "#070c1f", "#ff7a1a"),
              "S2000": ("#1b2a5c", "#070c1f", "#ff7a1a"), "カウンタック_緑": ("#1b2a5c", "#070c1f", "#ff7a1a"),
              "F40": ("#f6f3ec", "#5a4a40", "#e2302a"), "テスタロッサ": ("#f6f3ec", "#5a4a40", "#e2302a"),
              "F40_黄": ("#f6f3ec", "#5a4a40", "#e2302a"), "R32_青": ("#f6f3ec", "#5a4a40", "#e2302a")}),
    "C": dict(  # 全車白ボディ、リムだけ2色（赤 / シアン）。背景は濃紺の単色系
        bg=dict(sky="#1d2b4c", far="#26375c", mid="#2c4069", dark="#121a2e", light="#41567f", accent="#ff3b56", shadow="#0a1020"),
        cars={"R32": ("#f4f6fa", "#2a3550", "#ff3b56"),
              "F40": ("#f4f6fa", "#2a3550", "#29c4ff"), "カウンタック": ("#f4f6fa", "#2a3550", "#ff3b56"),
              "テスタロッサ": ("#f4f6fa", "#2a3550", "#29c4ff"), "S2000": ("#f4f6fa", "#2a3550", "#ff3b56"),
              "F40_黄": ("#f4f6fa", "#2a3550", "#29c4ff"), "カウンタック_緑": ("#f4f6fa", "#2a3550", "#ff3b56"),
              "R32_青": ("#f4f6fa", "#2a3550", "#29c4ff")}),
    "D": dict(  # 車は暖色だけ、背景はティールの単色系（補色）
        bg=dict(sky="#8fcbd8", far="#76b5c2", mid="#4f99a8", dark="#20323a", light="#dceff2", accent="#ffd23a", shadow="#2c5866"),
        cars={"R32": ("#ff4a1c", "#5a1000"),
              "F40": ("#e8361e", "#4a0a04"), "カウンタック": ("#ffb21a", "#5c3500"),
              "テスタロッサ": ("#c22a12", "#3a0802"), "S2000": ("#ff7a1a", "#5a2200"),
              "F40_黄": ("#ffd84a", "#6a4400"), "カウンタック_緑": ("#ff9440", "#5a2a00"),
              "R32_青": ("#f2e6d0", "#6a5040")}),
    "E": dict(  # 昼のグラフィック: 澄んだ青空・明るい地面・はっきりした太陽の影。主役だけオレンジ
        bg=dict(sky="#9fd2ff", sky_top="#2f84e6", far="#a9cbe8", mid="#bcd9ee", dark="#56606d", light="#ffffff",
                accent="#ff6a13", shadow="#3f6fb8"),
        shadow=0.68, mist=0.2,
        cars={"R32": ("#ff6a13", "#5a1a00"),
              "F40": ("#f2f3f5", "#4a5466"), "カウンタック": ("#b9c0c9", "#3a414c"),
              "テスタロッサ": ("#15171b", "#000000"), "S2000": ("#6b7380", "#1c2027"),
              "F40_黄": ("#2a2e35", "#0a0b0d"), "カウンタック_緑": ("#f2f3f5", "#4a5466"),
              "R32_青": ("#8d95a1", "#2a2f37"),
              "_other": ("#f2f3f5", "#4a5466")}),     # 名前の分からない2台目以降は白
}


def apply(theme):
    bg, cars = theme["bg"], theme["cars"]
    d, l, m, f, a = bg["dark"], bg["light"], bg["mid"], bg["far"], bg["accent"]
    L.LIVERY = cars
    L.PALETTE = {
        # 路面は線をほぼ消して面で見せる（グラフィック寄り）
        "道路": (d, d, d, d),
        "コンクリート": (l, l, l, l),
        "IR be967ef17aa53d98 | InkRacer #aaa993 | 0.86 | 0": (l, l, l, l),
        "芝": m, "丘": f, "黄線": a,
        "スタンド赤": a, "サーキット赤": a, "スタンド青": d, "サーキット青": d,
        "スタンド灰": m, "建物白": l, "サーキット黄": a,
        "ガードレール": l, "フェンス": l, "濃灰": d,
        "マテリアル.023": d, "チェッカー": l, "ガラス": d, "照明灯": l,
        "観客0": a, "観客1": d, "観客2": l, "観客3": l, "観客4": d, "観客5": m, "観客6": l, "肌": l,
        # デモシーン（demo_scenes.py のサーキット）の名前
        "アスファルト": d, "ランオフ舗装": d, "白": l, "赤": a, "オレンジ": a, "砂利": m, "土": m,
        "地面": m, "幹": l, "葉1": m, "葉2": f,
        "CPB_バリヤ黒": d, "CPB_バリヤ赤": a, "CPB_バリヤ白": l,
    }
    L.SHADOW_MATS = L.SHADOW_MATS + ["アスファルト", "ランオフ舗装", "白", "赤", "砂利", "土", "地面", "コンクリート"]
    L.SKY_HORIZON = bg["sky"]
    L.SKY_TOP = bg.get("sky_top", bg["sky"])   # sky_top が無ければ空は単色
    L.SHADOW_TINT = bg["shadow"]
    L.SHADOW = theme.get("shadow", 0.55)
    L.MIST = theme.get("mist", 0.45)
    L.TRIM = ("#3a3f48", "#101216")
    L.TRIM_RIM_ALWAYS = True                # ホイールなどの赤黄のリムも消して色数を絞る


def main():
    args = sys.argv[sys.argv.index("--") + 1:]
    out, key = args[0], args[1]
    apply(THEMES[key])
    L.do_cars()
    L.do_circuit()
    w = L.sky_world()
    for sc in L.bpy.data.scenes:
        L.finish(sc, w)
    L.bpy.ops.wm.save_as_mainfile(filepath=out, compress=True)
    print("SAVED", key, out)


main()

"""フォーミュラのリバリーのテクスチャを加工: ゼッケン番号を消し、文字をバーコード風の縞に置き換える

blender -b --python formula_tex.py -- 入力フォルダ 出力フォルダ
（入力: Formula_tex_body.png / _v1 / _v2。256×256。座標は画像の左上が原点のピクセル）
"""
import bpy
import numpy as np
import random
import sys

args = sys.argv[sys.argv.index("--") + 1:]
SRC, DST = args[0], args[1]

# 消す所（番号の丸・楕円）: (x0, x1, y0, y1)
ERASE = [(162, 195, 20, 60, 'LR'), (63, 96, 82, 124, 'LR'), (97, 126, 142, 217, 'R')]   # 'R': 右の色だけで塗る（左に文字がある所）
# バーコードにする所: (x0, x1, y0, y1, 地の色を残すか(白い箱), 向き 'V'=縦の棒 / 'H'=横の棒)
CODES = [(81, 125, 39, 57, True, 'V'), (131, 175, 101, 121, True, 'V'),
         (3, 15, 150, 233, False, 'H'), (83, 96, 141, 182, False, 'H'), (83, 96, 197, 237, False, 'H'),
         (103, 113, 151, 175, False, 'H'), (103, 113, 211, 232, False, 'H'),
         (199, 226, 170, 186, True, 'V'), (228, 255, 170, 186, True, 'V')]


def load(path):
    im = bpy.data.images.load(path)
    w, h = im.size
    a = np.array(im.pixels[:], dtype=np.float32).reshape(h, w, 4)[::-1].copy()   # 上が 0 の並びに
    return im, a


def save(im, a, path):
    im.pixels[:] = a[::-1].reshape(-1)
    im.filepath_raw = path
    im.file_format = 'PNG'
    im.save()


def erase(a, x0, x1, y0, y1, mode='LR'):
    """行ごとに、左右の外側の色をなめらかにつなぐ（横の線や帯はそのまま通る）"""
    for y in range(y0, y1):
        R = a[y, min(a.shape[1] - 1, x1)].copy()
        L = R if mode == 'R' else a[y, max(0, x0 - 1)].copy()
        n = x1 - x0
        for i in range(n):
            t = (i + 0.5) / n
            a[y, x0 + i] = L * (1 - t) + R * t


def barcode(a, x0, x1, y0, y1, box, orient, rnd):
    reg = a[y0:y1, x0:x1]
    lum = reg[..., :3].mean(axis=2)
    bg = reg[lum >= np.percentile(lum, 70)][:, :3].mean(axis=0)         # 地（明るい方）
    ink = reg[lum <= np.percentile(lum, 15)][:, :3].mean(axis=0)        # 文字の色（暗い方）
    if not box:
        erase(a, x0, x1, y0, y1)
        bg = None
    else:
        a[y0:y1, x0:x1, :3] = bg
    # 縞: 太さ 1〜3 px、すき間 1〜2 px。端は 1px ずつ空ける
    if orient == 'V':
        p, end = x0 + 2, x1 - 2
        while p < end:
            w = rnd.choice((1, 1, 2, 3))
            a[y0 + 2:y1 - 2, p:min(end, p + w), :3] = ink
            p += w + rnd.choice((1, 1, 2))
    else:
        p, end = y0 + 2, y1 - 2
        while p < end:
            w = rnd.choice((1, 1, 2, 3))
            a[p:min(end, p + w), x0 + 2:x1 - 2, :3] = ink
            p += w + rnd.choice((1, 1, 2))


for nm in ("Formula_tex_body", "Formula_tex_body_v1", "Formula_tex_body_v2"):
    im, a = load(f"{SRC}/{nm}.png")
    rnd = random.Random(7)
    for r in ERASE:
        erase(a, *r)
    for c in CODES:
        barcode(a, *c, rnd)
    save(im, a, f"{DST}/{nm}.png")
    print("TEX", nm)

import sys, os, glob, subprocess, json
from PIL import Image, ImageDraw, ImageFont
D, FF, OUT, META = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
meta = json.loads(open(META, encoding="utf-8").read())
W, H = 1280, 720
FPS = int(os.environ.get("CPB_FPS", 24))     # シーンの fps に合わせる（30fps のシーンは CPB_FPS=30）
K = FPS / 24.0
T_TITLE, T_IN, T_OUT, T_FLASH, T_END = int(60 * K), 6 * K, 15 * K, int(8 * K), int(12 * K)
fB = ImageFont.truetype("C:/Windows/Fonts/YuGothB.ttc", 44)
fS = ImageFont.truetype("C:/Windows/Fonts/YuGothB.ttc", 26)
seq = sorted(glob.glob(os.path.join(D, "S_*.png"))) + sorted(glob.glob(os.path.join(D, "R_*.png")))
p = subprocess.Popen([FF, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (W, H),
                      "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                      "-pix_fmt", "yuv420p", "-movflags", "+faststart", OUT], stdin=subprocess.PIPE)
first_r = next((i for i, f in enumerate(seq) if os.path.basename(f).startswith("R_")), None)
for i, fn in enumerate(seq):
    im = Image.open(fn).convert("RGB").resize((W, H))
    d = ImageDraw.Draw(im, "RGBA")
    if i < T_TITLE:
        a = int(255 * min(1.0, (T_TITLE - i) / T_OUT, (i + 1) / T_IN))
        d.rectangle((0, 520, W, 640), fill=(0, 0, 0, int(a * 0.55)))
        d.text((60, 528), meta["title"], font=fB, fill=(255, 255, 255, a))
        d.text((64, 590), meta["sub"], font=fS, fill=(255, 220, 190, a))
    if first_r is not None and i >= first_r:
        d.rectangle((40, 36, 390, 100), fill=(200, 20, 20, 210))
        d.text((58, 40), "%s  ×%g" % (meta.get("label") or "REPLAY", meta["replay"][3]), font=fB,
               fill=(255, 255, 255, 255))
        if i - first_r < T_FLASH:
            im = Image.blend(Image.new("RGB", (W, H)), im, (i - first_r) / T_FLASH)
    if i >= len(seq) - T_END:
        im = Image.blend(Image.new("RGB", (W, H)), im, max(0, len(seq) - 1 - i) / T_END)
    p.stdin.write(im.tobytes())
p.stdin.close(); p.wait()
print("DONE", OUT, len(seq))

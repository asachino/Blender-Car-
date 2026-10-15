"""blender -b <scene.blend> --python render_demo.py -- <outdir> <job> <njobs> [scale]"""
import bpy, sys, os, json
args = sys.argv[sys.argv.index("--") + 1:]
out, job, njobs = args[0], int(args[1]), int(args[2])
pct = int(args[3]) if len(args) > 3 else 100
os.makedirs(out, exist_ok=True)
sc = bpy.context.scene
for mk in list(sc.timeline_markers):
    sc.timeline_markers.remove(mk)
sc.render.resolution_x, sc.render.resolution_y = 1280, 720
if os.environ.get("CPB_SKY") == "1":    # 確認用: 背景の透過を切って空も写す
    sc.render.film_transparent = False
sc.render.resolution_percentage = pct
meta = json.loads(sc["demo"])
tasks = []
i = 0
for cam, f0, f1 in meta["shots"]:
    for f in range(f0, f1 + 1):
        tasks.append(("S", i, cam, float(f)))
        i += 1
if meta["replay"]:
    cam, f0, f1, sp = meta["replay"]
    n = int((f1 - f0) / sp)
    for j in range(n):
        tasks.append(("R", j, cam, f0 + j * sp))
step = int(args[4]) if len(args) > 4 else 1
for t_ in tasks[job::njobs][::step] if step > 1 else tasks[job::njobs]:
    kind, idx, cam, ft = t_
    if kind == "R":
        if hasattr(sc.eevee, "use_motion_blur"):
            sc.eevee.use_motion_blur = False
        sc.render.use_motion_blur = False
    sc.camera = bpy.data.objects[cam]
    fi = int(ft)
    sc.frame_set(fi, subframe=ft - fi)
    sc.render.filepath = os.path.join(out, "%s_%04d.png" % (kind, idx))
    bpy.ops.render.render(write_still=True)
print("DONE", job)

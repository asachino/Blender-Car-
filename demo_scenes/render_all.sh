#!/bin/bash
# 全シーンを本番レンダリング → mp4
B="${BLENDER:-blender}"   # Blender の場所（PATH に無ければ BLENDER で指定）
FF="${FFMPEG:-ffmpeg}"   # ffmpeg の場所（PATH に無ければ FFMPEG で指定）
NJ=7
for n in "$@"; do
  d="$(pwd -W)/scenes/$n"
  rm -rf scenes/$n/frames; mkdir -p scenes/$n/frames
  "$B" -b "$d/$n.blend" --python-expr "import bpy,sys;open(sys.argv[-1],'w',encoding='utf-8').write(bpy.context.scene['demo'])" -- "$d/meta.json" > /dev/null 2>&1
  t0=$(date +%s)
  for j in $(seq 0 $((NJ-1))); do
    "$B" -b "$d/$n.blend" --python tools/render_demo.py -- "$d/frames" $j $NJ > scenes/$n/render_$j.log 2>&1 &
  done
  wait
  CPB_FPS=${CPB_FPS:-24} PYTHONUTF8=1 python tools/assemble_demo.py "$d/frames" "$FF" "$d/$n.mp4" "$d/meta.json" > scenes/$n/assemble.log 2>&1
  echo "DONE $n $(ls scenes/$n/frames | wc -l) frames $(( $(date +%s)-t0 ))s $(ls -la scenes/$n/$n.mp4 2>/dev/null | awk '{print $5}')"
done

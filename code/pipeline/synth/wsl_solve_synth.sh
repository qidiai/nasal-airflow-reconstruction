#!/bin/bash
# M2.5 synth WSL 求解脚本：Allrun(checkMesh + simpleFoam + foamToVTK)，MAXPAR=2 防 OOM
# （WSL 实测 12 核 / 7GB；synth 算例 236k-384k cells，2 并行 simpleFoam ~3-4GB 峰值）
# 用法（Windows 侧）：wsl -d Ubuntu -- bash /mnt/g/qidicode/target/tmp/nasal-hack/wsl_solve_synth.sh P0-OF-case-synth-001 ...
# 参考 M1 trackC wsl_solve.sh（baseline27 同款链路），MAXPAR 3 -> 2（算例更大）
source /usr/lib/openfoam/openfoam2406/etc/bashrc 2>/dev/null
cd ~/synth-solve || exit 1
MAXPAR=2
echo "[solve] host=$(hostname) cases=$* maxpar=$MAXPAR start=$(date +%H:%M:%S)"
for c in "$@"; do
  while [ "$(jobs -r | wc -l)" -ge "$MAXPAR" ]; do sleep 5; done
  if [ -f "$c/log.simpleFoam" ] && grep -q "^End$" "$c/log.simpleFoam" 2>/dev/null; then
    echo "[skip] $c already solved"
    continue
  fi
  echo "[start] $c $(date +%H:%M:%S)"
  (
    cd "$c" || exit 1
    t0=$(date +%s)
    ./Allrun > allrun.log 2>&1
    rc=$?
    t1=$(date +%s)
    echo "$c rc=$rc elapsed=$((t1-t0))s $(date +%H:%M:%S)" >> ~/synth-solve/batch_timing.txt
  ) &
done
wait
echo "[solve] ALL_DONE $(date +%H:%M:%S)"

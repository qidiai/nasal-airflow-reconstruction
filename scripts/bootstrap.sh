#!/usr/bin/env bash
# =============================================================================
# 罕见无界 · 鼻腔气流仿真工具 —— 一条命令装机自检（Linux / macOS / WSL）
#
# 用法（仓库根目录或任意目录均可）：
#   bash scripts/bootstrap.sh
# 可选环境变量：
#   SKIP_SOLVE=1   冒烟只跑到算例+断言（--solve skip），不做 CFD 求解
#   MAX_ITER=300   冒烟求解步数上限（默认 300；合成小算例实测几十秒内收敛）
#
# 步骤：Python/venv → pip 依赖 → cargo 构建 FlowScope → 合成 CT →
#       pA 查看器产物（干净克隆补合成占位，失败仅 WARN）→ pytest 冒烟 →
#       run_all 全链路冒烟（合成数据）。每步打印 [OK]/[FAIL]
#       与耗时；任一步失败以非零退出并给出中文提示。幂等，可重复执行。
#
# 注意：冒烟全程使用合成数据（scripts/make_synthetic_ct.py 生成），
#       不代表真实病例结果。
# =============================================================================
set -u
SKIP_SOLVE="${SKIP_SOLVE:-0}"
MAX_ITER="${MAX_ITER:-300}"

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PY="$REPO/.venv/bin/python"
REQ_FILE="$REPO/requirements.txt"
SOLVER_DIR="$REPO/code/solver"
FLOW_EXE="$SOLVER_DIR/target/release/flowscope"
SYNTH_CT="$REPO/out/synthetic-ct"
SMOKE_OUT="$REPO/out/run-sA-smoke"

step_ok()   { printf '  [OK]   %s（%ss）%s\n' "$1" "$2" "${3:+ —— $3}"; }
step_warn() { printf '  [WARN] %s —— %s\n' "$1" "$2"; }
step_fail() { printf '  [FAIL] %s —— %s\n' "$1" "$2" >&2; printf '=== bootstrap 中止 ===\n' >&2; exit 1; }
now()       { date +%s; }

echo "=== bootstrap：罕见无界 · 一条命令装机自检 ==="
echo "仓库根：$REPO"
T_ALL=$(now)

# ---------------------------------------------------------- [1/7] Python + venv
echo; echo "[1/7] Python 与虚拟环境"
T=$(now)
if [ -x "$VENV_PY" ]; then
    step_ok "复用已有 .venv" "$(( $(now) - T ))" "$VENV_PY"
else
    PY=""
    for cand in python3 python; do
        if command -v "$cand" >/dev/null 2>&1; then PY="$cand"; break; fi
    done
    [ -z "$PY" ] && step_fail "Python 检测" "未找到 Python——请安装 Python 3.10+ 后重试"
    echo "  创建 .venv（解释器：$PY）..."
    "$PY" -m venv "$REPO/.venv" || step_fail "创建 .venv" "python -m venv 失败"
    step_ok "创建 .venv" "$(( $(now) - T ))" "$PY"
fi

# ---------------------------------------------------------- [2/7] pip 依赖
echo; echo "[2/7] pip install -r requirements.txt"
T=$(now)
"$VENV_PY" -m pip install -q -r "$REQ_FILE" || step_fail "pip 依赖安装" "exit $?——检查网络或 requirements.txt"
step_ok "pip 依赖" "$(( $(now) - T ))" "已装齐（重复执行为 already satisfied）"

# ---------------------------------------------------------- [3/7] cargo 构建 FlowScope
echo; echo "[3/7] Rust 求解器 FlowScope（cargo build --release）"
T=$(now)
CAN_SOLVE=0
if command -v cargo >/dev/null 2>&1; then
    if ( cd "$SOLVER_DIR" && cargo build --release --quiet ) && [ -x "$FLOW_EXE" ]; then
        step_ok "FlowScope 构建" "$(( $(now) - T ))" "$FLOW_EXE"
        CAN_SOLVE=1
    else
        step_warn "FlowScope 构建" "cargo build 失败——CFD 求解不可用，冒烟降级为 --solve skip"
    fi
else
    step_warn "FlowScope 构建" "未安装 cargo（Rust）——CFD 求解不可用，冒烟降级为 --solve skip；装 Rust 后重跑本脚本即可解锁全链"
fi

# ---------------------------------------------------------- [4/7] 合成 CT
echo; echo "[4/7] 生成合成 CT（冒烟专用，非真实病例）"
T=$(now)
"$VENV_PY" "$REPO/scripts/make_synthetic_ct.py" --out "$SYNTH_CT" >/dev/null \
    || step_fail "合成 CT 生成" "exit $?"
N_DCM=$(find "$SYNTH_CT" -name '*.dcm' | wc -l | tr -d ' ')
step_ok "合成 CT（${N_DCM} 个切片）" "$(( $(now) - T ))" "$SYNTH_CT"

# ---------------------------------------------------------- [5/7] pA 查看器演示产物
echo; echo "[5/7] 生成 pA 查看器演示产物（干净克隆占位）"
T=$(now)
if "$VENV_PY" "$REPO/scripts/build_pa_placeholder.py" >/dev/null 2>&1; then
    step_ok "pA 查看器产物" "$(( $(now) - T ))" "code/pipeline/webapp/cases/pA/viewer_single.html"
else
    step_warn "pA 查看器产物" "生成失败（不影响装机，演示查看器降级）"
fi

# ---------------------------------------------------------- [6/7] pytest 冒烟
echo; echo "[6/7] pytest tests/test_quickstart.py"
T=$(now)
( cd "$REPO" && "$VENV_PY" -m pytest tests/test_quickstart.py -q ) \
    || step_fail "pytest 冒烟" "exit $?——运行 python -m pytest tests/test_quickstart.py 查看详情"
step_ok "pytest 冒烟" "$(( $(now) - T ))" "test_quickstart 全绿"

# ---------------------------------------------------------- [7/7] run_all 全链路冒烟
echo; echo "[7/7] run_all 全链路冒烟（合成数据）"
T=$(now)
RUN_ALL="$REPO/code/pipeline/run_all.py"
if [ "$CAN_SOLVE" = "1" ] && [ "$SKIP_SOLVE" != "1" ]; then
    MODE="--solve local --backend auto --max-iter $MAX_ITER --allow-partial-viewer"
    "$VENV_PY" "$RUN_ALL" --dicom-dir "$SYNTH_CT" --case-prefix sA --case smoke \
        --solve local --backend auto --max-iter "$MAX_ITER" --allow-partial-viewer \
        --out-root "$SMOKE_OUT"
    RC=$?
else
    MODE="--solve skip（无 FlowScope，仅算例+断言）"
    "$VENV_PY" "$RUN_ALL" --dicom-dir "$SYNTH_CT" --case-prefix sA --case smoke \
        --solve skip --out-root "$SMOKE_OUT"
    RC=$?
fi
if [ "$RC" -ne 0 ]; then
    case "$RC" in
        2) HINT="断言闸门停工（exit 2）——查看 $SMOKE_OUT/run_all_manifest-sA-smoke.json 与进度日志" ;;
        3) HINT="环境缺失（exit 3）——FlowScope 未构建或 OpenFOAM 缺失" ;;
        *) HINT="run_all 失败（exit $RC）" ;;
    esac
    step_fail "run_all 冒烟（$MODE）" "$HINT"
fi
step_ok "run_all 冒烟（$MODE）" "$(( $(now) - T ))" "产物：$SMOKE_OUT"

echo; echo "=== bootstrap 完成（总耗时 $(( $(now) - T_ALL ))s）==="
echo "下一步："
echo "  · 看文档：从零复现.md"
echo "  · 上传自己的 CT：python code/pipeline/server.py 后浏览器开 http://127.0.0.1:8080"
echo "  · 命令行直跑：python code/pipeline/run_all.py --dicom-dir <你的CT目录> --case-prefix u1 --case v1 --solve local"
exit 0

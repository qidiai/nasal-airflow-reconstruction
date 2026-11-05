#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_pa_placeholder.py —— 干净克隆形态下补齐 pA 查看器单文件产物（任务书 T1 / A2-Q4）。

判据事实（任务书 §背景，读码实证）：`tests/test_api.py` 的 `test_cases_schema`
与 `test_viewer_pA_iframe` 对产物的判据**只有文件存在性**（`server.py:3432-3433`
`os.path.isfile(...)`；iframe 串由 `server.py:3364-3378` 现拼，不读产物内容）；
同一文件另被 `test_pA_metrics_match_frozen_viewer_data`（读产物字节断言四个聚合数）、
`test_frozen_pA_single_untouched`（与提交包比 md5）、`server.py:3285-3296`
`/api/metrics/pA` 三处消费 ⇒ 本脚本按"真产物优先"顺序补齐，绝不覆盖在位资产。

优先级（幂等，可重复执行）：
  1) 产物已在位（本机 15MB 冻结副本）⇒ 什么都不做，直接复用；
  2) 提交包 `viewer_single.html` 在位 ⇒ `shutil.copy2` 复制真产物
     （否则 `test_frozen_pA_single_untouched` 会从"dst 不存在 ⇒ skip"翻成"md5 不符 ⇒ 红"）；
  3) 两者都无（干净克隆）⇒ 走生成链产合成占位产物。

生成链（规格写死，不得更换）：
  模板  `code/pipeline/webapp/viewer_template/viewer.html`（占位标签 :408-410，dataSource :1226）
  数据  `code/viewer/gen_demo_data.py` 的合成几何函数，写到临时目录（**不写**其默认
        入库路径 `code/viewer/viewer_data.js` —— 那是已入库资产且头部时间戳每次都变，跑一次即脏树）
  构建  `code/pipeline/webapp/tools/build_single_file.py`（33a6c77 修复版，按绝对路径加载直接复用其 main()）
  落点  `code/pipeline/webapp/cases/pA/viewer_single.html`（`.gitignore:58` 已屏蔽；落盘前建父目录）

禁止项：`code/viewer/build_single_file.py`（旧行为）与 `webapp/tools/build_t50_singles.py`
（依赖被 gitignore 的 `webapp/plus/`，干净克隆必抛）。
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PIPE = os.path.join(REPO, "code", "pipeline")

TEMPLATE_HTML = os.path.join(PIPE, "webapp", "viewer_template", "viewer.html")
# 构建器与几何函数库一律按**绝对文件路径**加载（不用 sys.path + 裸模块名）：
# 仓库里有两份同名 build_single_file.py，`code/viewer/` 那份是规格明令禁用的
# 旧行为（保留悬空 <script src> 引用）；按路径加载可杜绝解析到错的那份。
BUILDER_PATH = os.path.join(PIPE, "webapp", "tools", "build_single_file.py")
GEN_DEMO_PATH = os.path.join(REPO, "code", "viewer", "gen_demo_data.py")

DEFAULT_DST = os.path.join(PIPE, "webapp", "cases", "pA", "viewer_single.html")

# 提交包真产物（tests/test_api.py:172-173 同一路径口径；DATA_ROOT 未设时该路径不存在）
SUBMISSION_SRC = os.path.expandvars(
    r"%DATA_ROOT%\项目\P0-鼻塞设计工具\提交包-20261002\viewer_single.html"
)

# ------------------------------------------------------------------ 内嵌数字（来源见行内注释）
# 四项为**库内已公开**的 pA 聚合数：tests/test_api.py:329-331 断言值，
# 亦见 code/data-governance/consent-ledger.md:24（A2 归档 ΔP=18.45 Pa）。
# 内嵌不构成新增泄露；gen_demo_data.py:205-216 自带的 23.7/50.0/50.0/78.5
# 必须在此覆盖（复用其几何函数 ≠ 可直接拿其输出）。
PUBLISHED_METRICS = {
    "dP_baseline_Pa": 18.45,      # 库内已公开（tests/test_api.py:329）
    "split_L_pct": 51.9,          # 库内已公开（tests/test_api.py:330）
    "split_R_pct": 48.1,          # 库内已公开（tests/test_api.py:330）
    "resistance_total": "66.2 Pa/(L/s)",  # 库内已公开（tests/test_api.py:331）
}
# 其余字段沿用 gen_demo_data.py:206-215 的合成演示值（参数化，非解算结果）。
SYNTHETIC_FILL_METRICS = {
    "dP_1mm_Pa": 35.2,
    "dP_2mm_Pa": 58.9,
    "dP_3mm_Pa": 66.1,
    "wss_mean_Pa": 0.013,
    "wss_p95_Pa": 0.061,
}
# 诚实声明（两行式）——不得照抄 gen_demo_data.py:240「不含任何患者数据、CT 影像
# 或真实测量值」：该表述与本产物内嵌的库内已公开聚合数自相矛盾。
DECLARATION_LINES = (
    "// 数据性质   : 几何/体数据 = 合成占位（参数化管腔模型，非真实解剖重建）",
    "// 指标口径   : meta.metrics = 库内已公开 pA 聚合数（非本产物解算结果）",
)
# 合成占位的缩窄档/wss 亦非解算值，写进 dP_note 供指标卡来源标签消费。
SYNTHETIC_SCENARIO_NOTE = (
    "1/2/3mm 缩窄档与 wss 为合成占位值（参数化演示，非解算结果）；"
    "仅 dP_baseline / split_L / split_R / resistance_total 四项为库内已公开 pA 聚合数"
)

# ------------------------------------------------------------------ 合成几何分辨率（占位用，非演示精度）
AIRWAY_MESH = (48, 81)      # (n_theta, n_z) → 3,840 面
CAVITY_MESH = (48, 61)      # 内模 0.80 倍
SINUS_MESH = (32, 33)
STREAMLINES = (24, 80)      # 条 × 点
SLICE_POINTS = 601          # make_slices 的 n_pts
PLACEHOLDER_MESH = (48, 81)


def _load_by_path(name: str, path: str):
    """按绝对路径加载既有实现（不复制任何逻辑，也不靠 sys.path 猜模块）。"""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"生成链依赖缺失：{path}")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _import_builders():
    """返回 (构建器, 几何函数库)；构建器身份不符（旧版）即拒绝生成。"""
    bsf = _load_by_path("webapp_build_single_file", BUILDER_PATH)
    if os.path.normcase(bsf.__file__) != os.path.normcase(BUILDER_PATH):
        raise RuntimeError(
            "构建器解析到了 %s，应为 %s（旧版行为被规格禁用）"
            % (bsf.__file__, BUILDER_PATH))
    gdd = _load_by_path("gen_demo_data", GEN_DEMO_PATH)
    return bsf, gdd


def _build_data_package(gdd, tmp_dir: str) -> str:
    """用 gen_demo_data 的几何函数拼八键数据包，写临时 viewer_data.js 并返回其路径。

    写盘格式与 gen_demo_data.py:250-259 一致（`window.VIEWER_DATA = {...};`），
    但 metrics 换成库内已公开四数 + 合成填充，头部声明换成两行式诚实声明。
    """
    airway_verts, airway_idx = gdd.tube_mesh(*AIRWAY_MESH)
    cavity_verts, cavity_idx = gdd.tube_mesh(*CAVITY_MESH, r_scale=0.80)
    sinus_verts, sinus_idx = gdd.sinus_mesh(*SINUS_MESH)
    placeholders = [_placeholder_step(gdd, mm) for mm in (1, 2, 3)]
    metrics = dict(SYNTHETIC_FILL_METRICS)
    metrics.update(PUBLISHED_METRICS)
    metrics["dP_note"] = SYNTHETIC_SCENARIO_NOTE

    data = {
        "meta": {
            "title": "患者A 鼻腔气流查看器（干净克隆合成占位 · 内嵌库内已公开聚合数）",
            "caseBaseline": ("placeholder @15 L/min 层流（几何/体数据合成占位；"
                             "四项聚合数为库内已公开 pA 数字，非本产物解算）"),
            "units": "mm, m/s, Pa",
            "metrics": metrics,
        },
        "airwayMesh": {"positions": airway_verts, "indices": airway_idx},
        "streamlines": gdd.make_streamlines(*STREAMLINES),
        "slices": gdd.make_slices(n_pts=SLICE_POINTS),
        "placeholders": placeholders,
        "curve": gdd.make_curve(),
        "airwayCavity": {"positions": cavity_verts, "indices": cavity_idx},
        "airwaySinus": {"positions": sinus_verts, "indices": sinus_idx},
    }

    n_air_f = len(airway_idx) // 3
    header = "".join(line + "\n" for line in (
        "// ============================================================================",
        "// viewer_data.js  ——  pA 查看器数据包（干净克隆合成占位 · 任务书 T1 / A2-Q4）",
        "// 生成器   : scripts/build_pa_placeholder.py（几何函数复用 code/viewer/gen_demo_data.py）",
        DECLARATION_LINES[0],
        DECLARATION_LINES[1],
        "// 坐标系   : mm（参数化管腔，中心线为 z 轴）",
        f"// 条数统计 : airwayMesh {n_air_f} 面; streamlines {len(data['streamlines'])} 条;"
        f" slices {len(data['slices'])} 片; placeholders {len(placeholders)} 档",
        "// 说明     : 概念验证 · 非医疗器械 · 仿真几何禁止人体使用",
        "// ============================================================================",
    ))

    out = os.path.join(tmp_dir, "viewer_data.js")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(header)
        f.write("window.VIEWER_DATA = ")
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        f.write(";\n")
    return out


def _placeholder_step(gdd, mm: int) -> dict:
    """缩窄占位档（1/2/3mm）：复用 gen_demo_data.tube_mesh 的参数化管腔几何。"""
    verts, idx = gdd.tube_mesh(*PLACEHOLDER_MESH, shrink_mm=float(mm))
    return {"mm": mm, "positions": verts, "indices": idx}


def synthesize(dst: str) -> int:
    """生成链：模板 + 临时合成数据包 → 构建器 → dst。返回产物字节数。"""
    bsf, gdd = _import_builders()
    if not os.path.isfile(TEMPLATE_HTML):
        raise FileNotFoundError(f"查看器模板缺失：{TEMPLATE_HTML}")

    dst_dir = os.path.dirname(os.path.abspath(dst))
    os.makedirs(dst_dir, exist_ok=True)  # 干净克隆该目录不存在，builder 不建父目录

    with tempfile.TemporaryDirectory(prefix="pa-placeholder-") as tmp:
        data_path = _build_data_package(gdd, tmp)
        argv = sys.argv
        sys.argv = [os.path.basename(bsf.__file__), TEMPLATE_HTML, data_path, dst]
        try:
            rc = bsf.main()
        finally:
            sys.argv = argv
    if rc != 0:
        raise RuntimeError(f"build_single_file.main() 返回 {rc}（生成链失败）")
    if not os.path.isfile(dst):
        raise RuntimeError(f"构建器报告成功但产物缺失：{dst}")
    return os.path.getsize(dst)


def ensure(dst: str = DEFAULT_DST) -> dict:
    """幂等入口：在位则复用 → 提交包则复制 → 否则合成。返回 action 说明。"""
    if os.path.isfile(dst):
        return {"action": "reuse-existing", "path": dst,
                "bytes": os.path.getsize(dst)}
    if os.path.isfile(SUBMISSION_SRC):
        os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
        shutil.copy2(SUBMISSION_SRC, dst)
        return {"action": "copy-from-submission", "path": dst,
                "bytes": os.path.getsize(dst), "src": SUBMISSION_SRC}
    return {"action": "synthesize-placeholder", "path": dst,
            "bytes": synthesize(dst)}


def main() -> int:
    argv = sys.argv[1:]
    dst = argv[0] if argv else DEFAULT_DST
    info = ensure(dst)
    print("pA viewer artifact: %(action)s -> %(path)s (%(bytes)d bytes)" % info)
    return 0


if __name__ == "__main__":
    sys.exit(main())

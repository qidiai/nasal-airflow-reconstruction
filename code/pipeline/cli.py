# -*- coding: utf-8 -*-
"""管线 CLI 入口（开箱自检）。

用法（先进入 code/ 目录）：
    python -m pipeline.cli capabilities

子命令：
    capabilities   运行环境自检：Python 版本、依赖、CT 输入目录、
                   输出路径占位环境变量（QIDI_WORKSPACE/DATA_ROOT）、
                   查看器示例数据就绪状态。全部就绪再跑 step1-7。
"""
import argparse
import importlib.util
import os
import sys

DEPS = ("numpy", "scipy", "pydicom", "skimage", "trimesh", "matplotlib")


def _have(name):
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def cmd_capabilities():
    print("P0 鼻腔气流分析管线 · 开箱自检（capabilities）")
    print(f"  Python {sys.version.split()[0]}")
    ok = True
    for d in DEPS:
        has = _have(d)
        ok = ok and has
        print(f"  依赖 {d:<10} {'OK' if has else '缺失 —— pip install -r requirements.txt'}")
    dicom = os.path.expandvars(os.environ.get("P0_DICOM_DIR", "./dicom"))
    if os.path.isdir(dicom):
        n = len([f for f in os.listdir(dicom) if f.lower().endswith(".dcm")])
        print(f"  DICOM 目录 {dicom}：{n} 个 .dcm")
        if n == 0:
            print("    提示：目录不含 DICOM 文件：请检查 P0_DICOM_DIR / --dicom-dir")
    else:
        print(f"  DICOM 目录 {dicom}：不存在（真实 CT 需另备；demo 查看器无需此目录）")
    for var in ("QIDI_WORKSPACE", "DATA_ROOT"):
        v = os.environ.get(var)
        if v:
            print(f"  输出占位 %{var}%：已设置 -> {os.path.expandvars(v)}")
        else:
            print(f"  输出占位 %{var}%：未设置（管线脚本将使用字面量占位目录；"
                  "按 README QUICKSTART 设置后输出到指定工作区）")
    vd = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "..", "viewer", "viewer_data.js")
    print(f"  查看器示例数据 viewer_data.js："
          f"{'存在' if os.path.isfile(vd) else '缺失 —— 运行 code/viewer/gen_demo_data.py 生成'}")
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="pipeline.cli", description="P0 管线 CLI 入口（开箱自检）")
    sub = ap.add_subparsers(dest="cmd", metavar="{capabilities}")
    sub.add_parser("capabilities", help="运行环境自检（依赖/输入/输出占位就绪状态）")
    args = ap.parse_args(argv)
    if not args.cmd:
        ap.print_help()
        print("错误：缺少子命令。可用子命令：capabilities"
              "（例：python -m pipeline.cli capabilities）")
        return 2
    return cmd_capabilities()


if __name__ == "__main__":
    sys.exit(main())

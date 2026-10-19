#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""anon_dicom.py — DICOM 头脱敏 CLI（与 run_all.py 的 PII 闸门口径对齐）

用法：
    python anon_dicom.py <源目录> <目标目录> [--force]

做什么：
  1. 逐个读取源目录下的 .dcm（pydicom.dcmread，含像素数据），只改隐私相关 tag；
  2. 按 run_all.scan_pii 的判定口径重写头信息：
       PatientName              → "Anonymous"
       PatientID                → 确定性占位 "YYYYMMDD-NNNNNN"
                                  （sha256(原 ID + 固定盐) 派生；同一原始 ID 永远同一占位，
                                    同一患者的多序列因此保持同一分组，不会被打散）
       PatientBirthDate / InstitutionName / InstitutionAddress /
       ReferringPhysicianName / AccessionNumber / OtherPatientIDs
                                → 清空（空串）
       其余 tag（含 PatientSex / StudyID）与 pixel data 原样保留；
       TransferSyntaxUID / 文件元信息原样保留（dcmwrite(enforce_file_format=False)）。
  3. 写完后对目标目录跑一遍 ``run_all.scan_pii`` 自检：PASS 打印 PASS；
     FAIL 列出残余项并以非 0 退出码结束（绝不静默放行）。
  4. 映射表只打印到 stdout（原始 ID 的 sha256 前 8 位 → 占位），
     **不写任何映射文件**——映射不得随数据一起流转。

与 PII 闸的关系：
  run_all.py 的 scan_pii 是数据宪法硬闸，本工具**不修改、不绕过**它，
  只是把"闸门要什么"变成一个可以直接跑的命令。脱敏产物仍需重新上传，
  由服务端同一把闸门（server.py 直接调用 run_all.scan_pii）复验。
  PatientSex / StudyID 在 scan_pii 中只做统计、不判失败，因此保留。

退出码：
  0  全部文件脱敏完成，且目标目录 scan_pii PASS
  1  scan_pii FAIL（残余隐私字段，已逐项列出）
  2  输入/输出目录问题、像素数据完整性校验失败或读写异常
"""
import argparse
import hashlib
import os
import subprocess
import sys

import pydicom

HERE = os.path.dirname(os.path.abspath(__file__))

ANON_NAME = "Anonymous"

# 与 run_all.py:72-142 的 PII_FIELDS / CORE_PII 对齐。
# CORE_PII = scan_pii 判定"非空即 FAIL"的 6 个字段。
CORE_PII = [
    "PatientBirthDate", "InstitutionName", "InstitutionAddress",
    "ReferringPhysicianName", "AccessionNumber", "OtherPatientIDs",
]

# 固定盐：写死在代码里，保证跨次运行、跨机器映射一致（同一患者不会被拆成两个占位）。
# 这是伪匿名化（pseudonymisation），不是不可逆加密；不要把盐当成密钥管理。
_PID_SALT = b"nasal-airflow/anon_dicom/v1/2026-10-19"


def pid_placeholder(raw_pid):
    """原始 PatientID → 确定性占位 'YYYYMMDD-NNNNNN'（纯数字，匹配 ^\\d{8}-\\d{6}$）。"""
    h = hashlib.sha256(_PID_SALT + str(raw_pid).encode("utf-8")).digest()
    n = int.from_bytes(h, "big")
    year = 1970 + (n % 51)                    # 1970..2020（合法日历范围内的占位）
    month = 1 + (n // 51) % 12
    day = 1 + (n // (51 * 12)) % 28
    seq = (n // (51 * 12 * 28)) % 1000000
    return "%04d%02d%02d-%06d" % (year, month, day, seq)


def pid_fingerprint(raw_pid):
    """映射表用的指纹：原始 ID 的 sha256 前 8 位（不可逆，便于人工对账）。"""
    return hashlib.sha256(str(raw_pid).encode("utf-8")).hexdigest()[:8]


def _pixel_digest(ds):
    """PixelData 字节摘要（None=本文件无像素数据）。"""
    try:
        px = ds.get("PixelData")
    except Exception:  # noqa: BLE001
        px = None
    if px is None:
        return None
    try:
        return hashlib.sha256(bytes(px)).hexdigest()
    except Exception:  # noqa: BLE001
        return "unhashable"


def retag(ds, mapping):
    """就地改写隐私 tag；返回 (原始 PatientID, 是否改动)。"""
    raw_pid = "" if ds.get("PatientID") is None else str(ds.PatientID).strip()
    ds.PatientName = ANON_NAME
    if raw_pid:
        if raw_pid not in mapping:
            mapping[raw_pid] = pid_placeholder(raw_pid)
        ds.PatientID = mapping[raw_pid]
    for fld in CORE_PII:
        if fld in ds:
            setattr(ds, fld, "")
    return raw_pid


def _run_scan_pii(dst_dir):
    """子调用 run_all.scan_pii（隔离进程，避免 run_all 的 stdout 重绑定影响本工具）。"""
    code = ("import json,sys,run_all;"
            "r=run_all.scan_pii(sys.argv[1]);"
            "print('__ANON_QC__'+json.dumps(r,ensure_ascii=False))")
    try:
        p = subprocess.run([sys.executable, "-c", code, dst_dir], cwd=HERE,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=600)
    except (OSError, subprocess.SubprocessError) as e:  # noqa: BLE001
        return None, "scan_pii 子调用失败：%r" % (e,)
    out = p.stdout.decode("utf-8", "replace")
    for line in out.splitlines():
        if line.startswith("__ANON_QC__"):
            import json
            try:
                return json.loads(line[len("__ANON_QC__"):]), ""
            except ValueError as e:  # noqa: BLE001
                return None, "scan_pii 输出解析失败：%r" % (e,)
    return None, "scan_pii 未返回结果（exit %s）：%s" % (p.returncode, out.strip()[-800:])


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="DICOM 头脱敏（对齐 run_all.scan_pii 口径；只改头，不动像素）")
    ap.add_argument("src", help="源目录（含带头信息的 .dcm）")
    ap.add_argument("dst", help="目标目录（脱敏产物；不得与源目录相同）")
    ap.add_argument("--force", action="store_true",
                    help="目标目录非空时仍继续（同名文件覆盖）")
    args = ap.parse_args(argv)

    src = os.path.abspath(args.src)
    dst = os.path.abspath(args.dst)
    if not os.path.isdir(src):
        print("[anon] 错误：源目录不存在：%s" % src, file=sys.stderr)
        return 2
    if os.path.realpath(src) == os.path.realpath(dst):
        print("[anon] 错误：目标目录不能与源目录相同（不做原地改写，避免不可逆覆盖）",
              file=sys.stderr)
        return 2
    if os.path.isdir(dst) and os.listdir(dst) and not args.force:
        print("[anon] 错误：目标目录非空：%s（加 --force 才覆盖）" % dst, file=sys.stderr)
        return 2
    os.makedirs(dst, exist_ok=True)

    files = sorted(f for f in os.listdir(src) if f.lower().endswith(".dcm"))
    skipped = [f for f in os.listdir(src) if not f.lower().endswith(".dcm")]
    if not files:
        print("[anon] 错误：源目录没有 .dcm 文件：%s" % src, file=sys.stderr)
        return 2

    mapping = {}
    bad = []
    px_mismatch = []
    for i, fn in enumerate(files, 1):
        sp = os.path.join(src, fn)
        dp = os.path.join(dst, fn)
        try:
            ds = pydicom.dcmread(sp)
            ts_before = str(ds.file_meta.get("TransferSyntaxUID", "")) \
                if getattr(ds, "file_meta", None) is not None else ""
            px_before = _pixel_digest(ds)
            retag(ds, mapping)
            pydicom.dcmwrite(dp, ds, enforce_file_format=False)
        except Exception as e:  # noqa: BLE001
            bad.append((fn, repr(e)))
            print("[anon] 失败：%s — %r" % (fn, e), file=sys.stderr)
            continue
        try:  # 写后复读：TransferSyntax 与 PixelData 必须逐字节一致
            back = pydicom.dcmread(dp)
            ts_after = str(back.file_meta.get("TransferSyntaxUID", "")) \
                if getattr(back, "file_meta", None) is not None else ""
            if ts_after != ts_before:
                px_mismatch.append((fn, "TransferSyntax %s → %s" % (ts_before, ts_after)))
            elif _pixel_digest(back) != px_before:
                px_mismatch.append((fn, "PixelData 摘要不一致"))
        except Exception as e:  # noqa: BLE001
            px_mismatch.append((fn, "复读失败：%r" % (e,)))
        if i % 50 == 0 or i == len(files):
            print("[anon] 进度 %d/%d" % (i, len(files)), flush=True)

    # 映射表：只到 stdout（sha 前 8 位 → 占位），绝不写进目标目录
    print("[anon] 映射表（原始 ID sha256[:8] → 占位；本表不落盘、不随数据走）：", flush=True)
    for raw in sorted(mapping):
        print("[anon]   %s → %s" % (pid_fingerprint(raw), mapping[raw]), flush=True)

    if skipped:
        print("[anon] 注意：已跳过 %d 个非 .dcm 文件（不复制，避免携带未脱敏的 DICOMDIR 等）："
              % len(skipped), flush=True)
        for fn in skipped[:10]:
            print("[anon]   - %s" % fn, flush=True)
    if bad:
        print("[anon] %d 个文件读写失败，未完成脱敏" % len(bad), file=sys.stderr)
        return 2
    if px_mismatch:
        print("[anon] 像素/传输语法完整性校验失败：", file=sys.stderr)
        for fn, why in px_mismatch[:20]:
            print("[anon]   - %s：%s" % (fn, why), file=sys.stderr)
        return 2

    rec, err = _run_scan_pii(dst)
    if rec is None:
        print("[anon] FAIL：自检无法完成 — %s" % err, file=sys.stderr)
        return 2
    if rec.get("pass"):
        print("[anon] scan_pii PASS：%d 头，0 处残余隐私字段" % rec.get("files", 0))
        return 0

    print("[anon] FAIL：scan_pii 仍报告 %d 处残余隐私字段（%d 头）："
          % (rec.get("fail_count", 0), rec.get("files", 0)), file=sys.stderr)
    for item in rec.get("fails", []):
        try:
            fn, fld, _val, why = list(item)[:4]
        except Exception:  # noqa: BLE001
            fn, fld, why = "-", "-", str(item)
        print("[anon]   - %s | %s | %s" % (fn, fld, why), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

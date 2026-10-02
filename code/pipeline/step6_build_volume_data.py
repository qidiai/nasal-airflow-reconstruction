# -*- coding: utf-8 -*-
"""
step6_build_volume_data.py  ——  任务 T6：CT 体数据包（浏览器 3D 纹理 + 缩略图）

返工单：contest3_workspace/pipeline/返工单-T6-体数据包.md
产出：  out/step6/volume_data.js  +  out/step6/volume_qc.json

输入（只读）：
  - DICOM：<P0_DICOM_DIR 目录>/*.dcm（层数与层距随数据定）
  - 气道掩码：out/step2/mask_full.npz (mask)
  - 对齐基准：out/step5/viewer_data.js 的 airwayMesh 顶点（V1 断言用）

坐标：体素(i,j,k)世界坐标（未居中） x=(i+0.5)*0.3496, y=(j+0.5)*0.3496, z=(k+0.5)*0.35 mm；
      CENTER 硬编码常量 [79.224894, 71.872321, 56.979602]（与 step5/T4 一致）。
      体渲染层与 VIEWER_DATA 几何同帧。

自测：pipeline 目录下  py -X utf8 step6_build_volume_data.py
"""
import os, sys, glob, json, time, base64, argparse, io
import numpy as np

# ----------------------------------------------------------------------------
# 路径 / 常量
# ----------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
OUT_STEP6 = os.path.join(HERE, "out", "step6")
MASK_NPZ = os.path.join(HERE, "out", "step2", "mask_full.npz")
VIEWER_JS = os.path.join(HERE, "out", "step5", "viewer_data.js")
# T11 开源脱敏：CT 数据目录由环境变量 P0_DICOM_DIR 指定（默认相对路径 ./dicom）
DATA_DIR = os.environ.get("P0_DICOM_DIR", "./dicom")

SX_FULL, SY_FULL, SZ_FULL = 0.3496, 0.3496, 0.35          # 全分辨率体素间距 mm
CENTER = np.array([79.224894, 71.872321, 56.979602])       # 硬编码（对齐生命线）
HU_OFFSET, HU_SCALE = -1024.0, 3071.0                      # uint8 H→HU: hu = v*(3071/255) - 1024
ROI_MARGIN_MM = 25.0                                        # ROI 外扩
WINDOW_PRESETS = {
    "bone":      {"wc": 300,  "ww": 2000},
    "soft_wide": {"wc": 250,  "ww": 1200},
    "soft":      {"wc": 50,   "ww": 400},
    "air":       {"wc": -450, "ww": 900},
    "realistic": {"wc": 500,  "ww": 2200},
}
METRICS_DP = {"dP_L_Pa": 13.99, "dP_R_Pa": 21.30, "note": "Run-A 面积分流口径 @15 L/min"}
META = {"patient": "A（数据捐献者授权）", "source": "鼻窦CT 0.35mm 各向同性", "units": "HU / mm"}
THUMB_Z_MM = [35, 45, 55]

T_START = time.time()
def log(msg):
    print(f"[{time.time()-T_START:6.1f}s] {msg}")
    sys.stdout.flush()


# ----------------------------------------------------------------------------
# 0. CLI
# ----------------------------------------------------------------------------
ap = argparse.ArgumentParser()
ap.add_argument("--spacing", type=float, default=0.7, help="各向同性重采样间距 mm")
ap.add_argument("--thumb-size", type=int, default=256)
args = ap.parse_args()
SP = float(args.spacing)
TS = int(args.thumb_size)
log(f"参数: spacing={SP}mm, thumb_size={TS}")


# ----------------------------------------------------------------------------
# 1. 读 DICOM（升序）-> vol int16 HU
# ----------------------------------------------------------------------------
def load_dicom():
    files = sorted(glob.glob(os.path.join(DATA_DIR, "*.dcm")))
    import pydicom
    slices = [pydicom.dcmread(f) for f in files]
    slices.sort(key=lambda s: float(s.ImagePositionPatient[2]))
    nz, rows, cols = len(slices), int(slices[0].Rows), int(slices[0].Columns)
    ps = [float(x) for x in slices[0].PixelSpacing]
    dz = abs(float(slices[1].ImagePositionPatient[2]) - float(slices[0].ImagePositionPatient[2]))
    vol = np.zeros((nz, rows, cols), dtype=np.int16)
    for i, s in enumerate(slices):
        vol[i] = s.pixel_array.astype(np.int16) * int(s.RescaleSlope) + int(s.RescaleIntercept)
    del slices
    return vol, ps, dz

log("读 DICOM ...")
vol, ps, dz = load_dicom()
nzF, nYF, nXF = vol.shape
log(f"  vol {vol.shape} int16; ps={ps} dz={dz:.4f}; HU[min,max]=[{int(vol.min())},{int(vol.max())}]")


# ----------------------------------------------------------------------------
# 2. ROI 裁剪：mask bbox 各向外扩 25mm（按全分辨率体素）
# ----------------------------------------------------------------------------
npz = np.load(MASK_NPZ)
mask = npz["mask"]
kk, jj, ii = np.where(mask)
mg_i = int(round(ROI_MARGIN_MM / SX_FULL))
mg_j = int(round(ROI_MARGIN_MM / SY_FULL))
mg_k = int(round(ROI_MARGIN_MM / SZ_FULL))
i0 = max(0, ii.min() - mg_i); i1 = min(nXF, ii.max() + 1 + mg_i)
j0 = max(0, jj.min() - mg_j); j1 = min(nYF, jj.max() + 1 + mg_j)
k0 = max(0, kk.min() - mg_k); k1 = min(nzF, kk.max() + 1 + mg_k)
log(f"  mask bbox i[{ii.min()},{ii.max()}] j[{jj.min()},{jj.max()}] k[{kk.min()},{kk.max()}]")
log(f"  ROI (全分辨率体素) i[{i0},{i1}) j[{j0},{j1}) k[{k0},{k1})  size {(i1-i0)}x{(j1-j0)}x{(k1-k0)}")


# ----------------------------------------------------------------------------
# 3. 降采样到各向同性 SP mm（zoom origin = ROI 原点）
# ----------------------------------------------------------------------------
from scipy import ndimage
roi = vol[k0:k1, j0:j1, i0:i1].astype(np.float32)         # (nzR, nyR, nxR)
nzR, nyR, nxR = roi.shape
# 目标各向同性尺寸：按各方向物理跨度 / SP
nx = max(1, int(round(nxR * SX_FULL / SP)))
ny = max(1, int(round(nyR * SY_FULL / SP)))
nz = max(1, int(round(nzR * SZ_FULL / SP)))
zoom = (nz / nzR, ny / nyR, nx / nxR)
ds = ndimage.zoom(roi, zoom=zoom, order=1)
ds = np.clip(ds, -1024.0, 2047.0)
log(f"  ROI {roi.shape} -> 降采样 {ds.shape} (zoom {tuple(round(z,5) for z in zoom)}); "
    f"物理尺寸 {nx*SP:.2f}x{ny*SP:.2f}x{nz*SP:.2f} mm")

# uint8 映射
v8 = np.round((ds + 1024.0) / 3071.0 * 255.0).astype(np.int32).clip(0, 255).astype(np.uint8)
# 契约 dims=[nx,ny,nz]，x 最快 => 数组形状 (nz,ny,nx) 的 C 顺序 flatten
assert ds.shape == (nz, ny, nx), "降采样形状与 dims 不一致"
flat = v8.flatten()                       # (nz,ny,nx) C-order => x 最快
volume_b64 = base64.b64encode(flat.tobytes()).decode("ascii")
log(f"  降采样体 {ds.shape}, uint8 {flat.shape}, b64 {len(volume_b64)} 字节")


# ----------------------------------------------------------------------------
# 4. origin：ROI 体素(0,0,0) 世界坐标 − CENTER
# ----------------------------------------------------------------------------
# ROI 体素(0,0,0) 对应全分辨率体素 (k0,j0,i0) 的体素中心
ori_world = np.array([(i0 + 0.5) * SX_FULL, (j0 + 0.5) * SY_FULL, (k0 + 0.5) * SZ_FULL])
origin_mm = ori_world - CENTER
log(f"  ROI 原点世界坐标(未居中) {np.round(ori_world,4).tolist()} -> origin_mm {np.round(origin_mm,4).tolist()}")


# ----------------------------------------------------------------------------
# 5. 缩略图：z=35/45/55mm 轴位层，骨窗 WC300/WW2000 -> 256×256 PNG -> base64
# ----------------------------------------------------------------------------
def hu_to_gray(hu, wc, ww):
    lo = wc - ww / 2.0
    g = (hu - lo) / ww * 255.0
    return np.clip(g, 0, 255).astype(np.uint8)

def to_png_b64(gray_u8):
    from PIL import Image
    buf = io.BytesIO()
    Image.fromarray(gray_u8, mode="L").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")

thumbs = []
for z_mm in THUMB_Z_MM:
    kfull = int(round(z_mm / SZ_FULL - 0.5))               # 未居中 z：z=35 -> k_full=35/0.35-0.5
    kfull = max(0, min(nzF - 1, kfull))
    sl = vol[kfull].astype(np.float32)                     # (nYF,nXF) HU at that layer
    g = hu_to_gray(sl, WINDOW_PRESETS["bone"]["wc"], WINDOW_PRESETS["bone"]["ww"])
    from PIL import Image
    img = Image.fromarray(g, mode="L").resize((TS, TS), resample=Image.BILINEAR)
    thumbs.append({"z_mm": z_mm, "img_b64": to_png_b64(np.asarray(img)), "wc": 300, "ww": 2000})
    log(f"  缩略图 z={z_mm}mm -> k_full={kfull} (z_act={kfull*SZ_FULL+SZ_FULL/2:.3f}mm) {TS}x{TS} PNG {len(thumbs[-1]['img_b64'])}B")


# ----------------------------------------------------------------------------
# 6. 组装 UTF-8 LF 单文件
# ----------------------------------------------------------------------------
gen_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
header = f"""\
// ============================================================================
// volume_data.js  ——  CT 体数据包（任务 T6 产出）
// 生成时间 : {gen_time}
// 来源     : {DATA_DIR}
//            {MASK_NPZ}  (ROI 裁剪基准)
// 体数据   : dims=[nx,ny,nz]={[nx,ny,nz]}, spacing={SP}mm 各向同性
//            体积顺序 = flatten of (nz,ny,nx), i.e. x-fastest
//            uint8 → HU: hu = v * (3071/255) + (-1024)
// origin_mm: {np.round(origin_mm,4).tolist()}  (= ROI 体素(0,0,0) 世界坐标 - CENTER)
// CENTER   : {CENTER.tolist()}  (与 step5 VIEWER_DATA 几何同帧)
// 说明     : 概念验证 · 非医疗器械 · 仿真几何禁止人体使用
// ============================================================================
"""

data = {
    "dims": [int(nx), int(ny), int(nz)],
    "spacing_mm": [float(SP), float(SP), float(SP)],
    "origin_mm": [float(x) for x in np.round(origin_mm, 4)],
    "hu_map": {"offset": int(HU_OFFSET), "scale": int(HU_SCALE)},
    "volume_b64": volume_b64,
    "window_presets": WINDOW_PRESETS,
    "thumbs": thumbs,
    "metrics_deltaP": METRICS_DP,
    "meta": META,
}

js_body = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
tail = "console.log('VOLUME_DATA loaded', " + json.dumps(
    {"dims": [nx, ny, nz], "bytes": len(flat)}, ensure_ascii=False) + ");\n"

js_path = os.path.join(OUT_STEP6, "volume_data.js")
os.makedirs(OUT_STEP6, exist_ok=True)
with open(js_path, "w", encoding="utf-8", newline="\n") as f:
    f.write(header)
    f.write("window.VOLUME_DATA = ")
    f.write(js_body)
    f.write(";\n")
    f.write(tail)
size = os.path.getsize(js_path)
log(f"写 volume_data.js  {size/1e6:.3f} MB")


# ----------------------------------------------------------------------------
# 7. QC V1..V5
# ----------------------------------------------------------------------------
log("质检 V1..V5 ...")
qc = {}

# [V1] 对齐：mask 表面随机 ≥1000 体素世界坐标(已居中) vs viewer_data.js airwayMesh 顶点 cKDTree
from scipy.spatial import cKDTree
# mask 表面体素（6 邻接边界）
surf = np.zeros_like(mask)
surf |= mask & ~np.roll(mask, 1, 0); surf[0, :, :] = False
surf |= mask & ~np.roll(mask, -1, 0); surf[-1, :, :] = False
surf |= mask & ~np.roll(mask, 1, 1); surf[:, 0, :] = False
surf |= mask & ~np.roll(mask, -1, 1); surf[:, -1, :] = False
surf |= mask & ~np.roll(mask, 1, 2); surf[:, :, 0] = False
surf |= mask & ~np.roll(mask, -1, 2); surf[:, :, -1] = False
sk, sj, si = np.where(surf)
N_V1 = 2000
rng = np.random.default_rng(42)
sel = rng.choice(len(sk), size=min(N_V1, len(sk)), replace=False)
wx = (si[sel] + 0.5) * SX_FULL - CENTER[0]
wy = (sj[sel] + 0.5) * SY_FULL - CENTER[1]
wz = (sk[sel] + 0.5) * SZ_FULL - CENTER[2]
pts_surf = np.stack([wx, wy, wz], axis=1)

# 从 viewer_data.js 解析 airwayMesh 顶点
txt = open(VIEWER_JS, encoding="utf-8").read()
import re
mm = re.search(r'"airwayMesh":\{"positions":\[([^\]]*)\]', txt)
air_pos = np.fromstring(mm.group(1), sep=",", dtype=np.float64).reshape(-1, 3)
tree = cKDTree(air_pos)
d, _ = tree.query(pts_surf)
p90 = float(np.percentile(d, 90)); p99 = float(np.percentile(d, 99))
v1 = (p90 <= 1.5) and (p99 <= 3.0)
qc["V1_alignment"] = {"pass": bool(v1), "n_sample": int(len(d)),
                      "p90_mm": round(p90, 4), "p99_mm": round(p99, 4),
                      "airway_verts": int(len(air_pos)), "thresholds": {"p90": 1.5, "p99": 3.0}}

# [V2] dims/spacing/origin 一致性
roi_span = np.array([nxR * SX_FULL, nyR * SY_FULL, nzR * SZ_FULL])
dim_span = np.array([nx * SP, ny * SP, nz * SP])
span_err = float(np.abs(dim_span - roi_span).max())
scale = 120.0
in_range = bool(np.all(np.abs(origin_mm) <= scale + roi_span.max()))
v2 = (span_err <= 0.1) and in_range
qc["V2_dims_spacing_origin"] = {"pass": bool(v2),
                                "dims": [int(nx), int(ny), int(nz)], "spacing": SP,
                                "dim_span_mm": [round(float(x), 4) for x in dim_span],
                                "roi_span_mm": [round(float(x), 4) for x in roi_span],
                                "span_err_mm": round(span_err, 4), "span_tol_mm": 0.1,
                                "origin_mm": [float(x) for x in np.round(origin_mm, 4)],
                                "origin_within_bounds": in_range}

# [V3] uint8 往返：抽 100 个体素 hu->v8->hu 误差 ≤12 HU
idx = rng.choice(ds.size, size=100, replace=False)
hu_true = ds.flatten()[idx]
v_flat = v8.flatten()[idx].astype(np.float64)
hu_back = v_flat * (HU_SCALE / 255.0) + HU_OFFSET
err = np.abs(hu_back - np.clip(hu_true, -1024, 2047))
max_err = float(err.max())
v3 = max_err <= 12.0
qc["V3_uint8_roundtrip"] = {"pass": bool(v3), "n": 100, "max_err_HU": round(max_err, 4),
                            "tol_HU": 12.0, "mean_err_HU": round(float(err.mean()), 4)}

# [V4] b64 解码长度 == nx*ny*nz；文件 ≤6MB；CRLF=0
raw = open(js_path, "rb").read()
dec = base64.b64decode(volume_b64)
len_ok = len(dec) == nx * ny * nz
size_ok = size <= 6 * 1024 * 1024
crlf = raw.count(b"\r\n")
v4 = len_ok and size_ok and (crlf == 0)
qc["V4_b64_size_crlf"] = {"pass": bool(v4), "decoded_len": len(dec), "expected_len": int(nx*ny*nz),
                          "bytes": int(size), "MB": round(size/1e6, 3), "size_le_6MB": size_ok, "crlf": crlf}

# [V5] 缩略图 3 张、256×256、PNG 头
thumb_ok = (len(thumbs) == 3)
det = []
for t in thumbs:
    b = base64.b64decode(t["img_b64"])
    is_png = b[:4] == b"\x89PNG"
    from PIL import Image
    wh = Image.open(io.BytesIO(b)).size
    det.append({"z_mm": t["z_mm"], "png_sig": is_png, "wh": list(wh), "b64_prefix": t["img_b64"][:8]})
    if not (is_png and wh == (TS, TS)):
        thumb_ok = False
v5 = thumb_ok and all(d["b64_prefix"].startswith("iVBOR") for d in det)
qc["V5_thumbs"] = {"pass": bool(v5), "count": len(thumbs), "size": [TS, TS], "detail": det}

qc["all_pass"] = all(v.get("pass", False) for v in qc.values() if isinstance(v, dict))
qc["runtime_s"] = round(time.time() - T_START, 1)
qc["generated"] = gen_time
# 附体积元信息（供审计）
qc["volume_info"] = {"dims[nx,ny,nz]": [int(nx), int(ny), int(nz)], "spacing_mm": SP,
                     "roi_full_voxels": [int(i1-i0), int(j1-j0), int(k1-k0)],
                     "roi_full_index": {"i0": int(i0), "j0": int(j0), "k0": int(k0)},
                     "CENTER": CENTER.tolist()}
qc_path = os.path.join(OUT_STEP6, "volume_qc.json")
with open(qc_path, "w", encoding="utf-8", newline="\n") as f:
    json.dump(qc, f, ensure_ascii=False, indent=2)

log("QC 结果:")
for kk2, v in qc.items():
    if isinstance(v, dict) and "pass" in v:
        log(f"  {kk2}: {'PASS' if v['pass'] else 'FAIL'}")
log(f"ALL PASS = {qc['all_pass']}")
log(f"完成，用时 {qc['runtime_s']}s；输出 {js_path} / {qc_path}")

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""左右分界（x 向质心）回归：非方形体数据不得崩，且必须沿 x 轴算。

钉住的契约（服务器实测 bug，2026-10-21）：
    体数据 airway.shape == (nz, ny, nx)，axis2 = x。真实 CT 常见非方形视野
    （230 层、308 行、360 列）——旧式 `airway.sum(axis=2).sum(axis=0)` 是先沿 x
    再沿 z 求和，得到**长度 ny 的 y 边缘分布**，再与长度 nx 的 xs 相乘：
        ValueError: operands could not be broadcast together with shapes (308,) (360,)
    方形视野虽不崩，但拿 y 分布乘 x 坐标 -> cx 语义错、左右分界错位（静默错）。

    正确口径：cx 由 `airway.sum(axis=(0, 1))`（长度 nx 的 x 边缘分布）与 xs
    相乘、除以总素和得到；mid = round(cx) 落在 **x 轴**，供
    `airway[:, :, :mid]` / `airway[:, :, mid:]` 切左/右。

测试不读任何 DICOM：几何逻辑来自生产模块 airway_geom（step1 直接调用同一份实现）。
"""
import ast
import os
import sys

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PIPELINE = os.path.dirname(HERE)
if PIPELINE not in sys.path:
    sys.path.insert(0, PIPELINE)

from airway_geom import centroid_split_x  # noqa: E402


def _volume_with_block(shape, x0, x1):
    """shape=(nz, ny, nx) 的体数据里，把 x∈[x0, x1] 整列（全部 z/y）填满。"""
    nz, ny, nx = shape
    assert 0 <= x0 <= x1 < nx
    v = np.zeros((nz, ny, nx), dtype=bool)
    v[:, :, x0:x1 + 1] = True
    return v


# ------------------------------------------------------- 1) 非方形视野不再崩
def test_non_square_volume_block_on_right_side():
    """(nz,ny,nx)=(6,5,9) 右侧方块：不抛异常，且分界把方块判到右侧。"""
    nz, ny, nx = 6, 5, 9
    airway = _volume_with_block((nz, ny, nx), 6, 8)

    cx, mid = centroid_split_x(airway)          # 旧实现此处 ValueError

    assert np.isfinite(cx)
    assert cx == pytest.approx(7.0)             # 方块中心列 (6+7+8)/3
    assert mid == 7
    # 方块在右半边完整保留（mid 之后的列全属方块），且右:左 = 2:1
    assert bool(airway[:, :, mid:].all())
    assert int(airway[:, :, mid:].sum()) == nz * ny * 2
    assert int(airway[:, :, :mid].sum()) == nz * ny * 1
    # 反向：整体左移一列后 cx/mid 同步左移一列
    cx2, mid2 = centroid_split_x(_volume_with_block((nz, ny, nx), 5, 7))
    assert cx2 == pytest.approx(6.0) and mid2 == 6


def test_x_axis_not_y_axis_mirror_symmetry():
    """镜像 x 轴必须翻转 cx；镜像 y 轴不得影响 cx（证明算的是 x 分布）。"""
    airway = _volume_with_block((6, 5, 9), 6, 8)
    cx, mid = centroid_split_x(airway)

    cx_x, mid_x = centroid_split_x(airway[:, :, ::-1])     # x 镜像
    assert cx_x == pytest.approx((airway.shape[2] - 1) - cx) == pytest.approx(1.0)
    assert mid_x == 1

    assert centroid_split_x(airway[:, ::-1, :]) == (cx, mid)   # y 镜像：不变


def test_legacy_expression_reproducer_non_square():
    """根因复现钉死：旧表达式的分布长度是 ny（不是 nx）-> 非方形必崩。"""
    nz, ny, nx = 6, 5, 9
    airway = _volume_with_block((nz, ny, nx), 6, 8)
    xs = np.arange(nx)
    legacy_profile = airway.sum(axis=2).sum(axis=0)
    assert legacy_profile.shape == (ny,)     # 拿到的是 y 分布 —— 这就是 bug
    with pytest.raises(ValueError):
        (legacy_profile * xs).sum()


# ------------------------------------------- 2) x/y 不等但气道居中 -> mid ≈ nx/2
def test_non_square_centered_airway_mid_is_near_nx_half():
    """x/y 不等（nx=10, ny=7）且气道居中：mid ≈ nx/2（容差 ±1）。"""
    nz, ny, nx = 4, 7, 10
    airway = _volume_with_block((nz, ny, nx), 4, 5)     # x=4,5 -> 中心 4.5
    cx, mid = centroid_split_x(airway)

    assert cx == pytest.approx(4.5)
    assert abs(mid - nx / 2.0) <= 1
    assert 0 <= mid <= nx


# ------------------------------------- 3) 方形视野（不崩的那种）也必须算 x
def test_square_volume_uses_x_profile_not_y_profile():
    """方形视野旧式不报错但静默算错：cx 只能跟着 x 走，不能跟着 y 走。"""
    side = 8
    airway = np.zeros((8, side, side), dtype=bool)
    airway[:, 6:8, 1:3] = True        # x∈{1,2}（左），y∈{6,7}（下）

    cx, mid = centroid_split_x(airway)
    assert cx == pytest.approx(1.5)   # x 质心
    assert mid == 2

    xs = np.arange(side)
    legacy = float((airway.sum(axis=2).sum(axis=0) * xs).sum() / airway.sum())
    assert legacy == pytest.approx(6.5)          # 旧式算的是 y 质心
    assert legacy != pytest.approx(cx)


# -------------------------- 4) step1 的 l_areas / r_areas 切分轴一致性（mid 在 x）
def test_split_slices_sum_to_total_per_slice():
    """step1:396-397 的切分核验：mid 在 x 轴 -> 左右逐层和 == 该层总面积。"""
    nz, ny, nx = 6, 5, 9
    airway = _volume_with_block((nz, ny, nx), 6, 8)
    _, mid = centroid_split_x(airway)

    total = airway.sum(axis=(1, 2))
    l_areas = airway[:, :, :mid].sum(axis=(1, 2))
    r_areas = airway[:, :, mid:].sum(axis=(1, 2))

    assert np.array_equal(l_areas + r_areas, total)
    assert (l_areas == ny * 1).all()      # x=6 一列 x ny 行
    assert (r_areas == ny * 2).all()      # x=7,8 两列 x ny 行


# --------------------------------------------------------------- 5) 边界契约
def test_empty_airway_returns_zero_without_division_error():
    """零气道不抛 ZeroDivisionError（与原 max(...,1) 口径一致）。"""
    assert centroid_split_x(np.zeros((6, 5, 9), dtype=bool)) == (0.0, 0)


@pytest.mark.parametrize("shape", [(5, 9), (2, 3, 4, 5), ()])
def test_rejects_non_3d_input(shape):
    with pytest.raises(ValueError):
        centroid_split_x(np.zeros(shape, dtype=bool))


# ------------------------------------------- 6) 接线：step1 必须调用这份实现
def _step1_ast():
    src = os.path.join(PIPELINE, "step1_airway_segment.py")
    with open(src, encoding="utf-8") as f:
        return ast.parse(f.read(), filename=src)


def test_step1_imports_and_calls_shared_helper():
    """生产代码必须调 airway_geom 里的同一份实现（否则测的是孤儿函数）。"""
    tree = _step1_ast()
    assert any(
        isinstance(n, ast.ImportFrom) and n.module == "airway_geom"
        and any(a.name == "centroid_split_x" for a in n.names)
        for n in tree.body), "step1 未从 airway_geom 导入 centroid_split_x"

    assign_ok = False
    for n in ast.walk(tree):
        if (isinstance(n, ast.Assign) and isinstance(n.value, ast.Call)
                and isinstance(n.value.func, ast.Name)
                and n.value.func.id == "centroid_split_x"):
            for t in n.targets:
                if (isinstance(t, ast.Tuple)
                        and [e.id for e in t.elts if isinstance(e, ast.Name)]
                        == ["cx", "mid"]):
                    assign_ok = True
    assert assign_ok, "step1 未把 centroid_split_x(airway) 赋给 (cx, mid)"


def test_step1_has_no_legacy_y_profile_expression():
    """可执行代码里不得再出现旧式 y 边缘分布链（注释/文档串不算）。"""
    tree = _step1_ast()
    legacy = [ast.unparse(n) for n in ast.walk(tree)
              if isinstance(n, ast.Call) and "sum(axis=2).sum(axis=0)" in ast.unparse(n)]
    assert legacy == [], "step1 仍存在旧式 y 边缘分布：%r" % (legacy,)
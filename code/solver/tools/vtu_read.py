"""Minimal reader for OpenFOAM foamToVTK XML output (inline base64 arrays).

Supports .vtu (UnstructuredGrid): Points, connectivity, cell DataArrays.
No third-party deps: base64 + struct only.
"""
import base64
import struct
import xml.etree.ElementTree as ET

_DTYPE = {
    "Float32": ("f", 4),
    "Float64": ("d", 8),
    "Int32": ("i", 4),
    "Int64": ("q", 8),
    "UInt32": ("I", 4),
    "UInt64": ("Q", 8),
    "UInt8": ("B", 1),
}


def _decode(elem):
    text = (elem.text or "").strip()
    if not text:
        return [], 1
    raw = base64.b64decode(text)
    # VTK XML inline binary arrays are prefixed by a UInt64 byte-count header
    if len(raw) >= 8 and struct.unpack("<Q", raw[:8])[0] == len(raw) - 8:
        raw = raw[8:]
    fmt, size = _DTYPE[elem.get("type", "Float32")]
    n = len(raw) // size
    vals = struct.unpack("<" + fmt * n, raw)
    ncomp = int(elem.get("NumberOfComponents", "1"))
    return list(vals), ncomp


def read_vtu(path):
    root = ET.parse(path).getroot()
    piece = root.find(".//Piece")
    npts = int(piece.get("NumberOfPoints"))
    ncells = int(piece.get("NumberOfCells"))
    arrays = {da.get("Name"): da for da in root.iter("DataArray") if da.get("Name")}
    pts, _ = _decode(arrays["Points"])
    points = [(pts[3 * i], pts[3 * i + 1], pts[3 * i + 2]) for i in range(npts)]
    cell = {}
    cd = piece.find("CellData")
    if cd is not None:
        for da in cd.findall("DataArray"):
            name = da.get("Name")
            vals, nc = _decode(da)
            if nc == 1:
                cell[name] = list(vals)
            else:
                cell[name] = [tuple(vals[i * nc:(i + 1) * nc]) for i in range(len(vals) // nc)]
    out = {"n_points": npts, "n_cells": ncells, "points": points, "cell": cell}
    for key in ("connectivity", "types", "offsets"):
        if key in arrays:
            v, _ = _decode(arrays[key])
            out[key] = [int(x) for x in v]
    return out



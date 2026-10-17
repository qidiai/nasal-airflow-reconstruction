"""列出 l3cases/step2 各 polyMesh 的 cells / patch 面数，用于把 l3-<NNN>.log 对到实际算例目录。"""
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import outlet_probe as op


def main(root):
    for d in sorted(glob.glob(os.path.join(root, "P0-OF-case-*"))):
        pm = os.path.join(d, "constant", "polyMesh")
        if not os.path.isdir(pm):
            continue
        owner = op.read_int_field(os.path.join(pm, "owner"))
        ncells = max(owner) + 1
        bnd = op.read_boundary(os.path.join(pm, "boundary"))
        print(os.path.basename(d), "cells", ncells,
              "patches", ",".join(f"{n}:{nf}" for n, nf, _ in bnd))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "out", "l3cases", "step2"))

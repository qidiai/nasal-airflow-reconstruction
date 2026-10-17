#!/usr/bin/env python3
"""T50 T18F builder: merge viewer_data + viewer_plus_data, then inline at viewer_data."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "build_single_file.py"
CASES = {
    "pA": ("viewer_plus.html", "viewer_data.js", "viewer_plus_data.js", "volume_data.js", "skin_data.js"),
    "pB": ("viewer_plus_pB.html", "viewer_data_pB.js", "viewer_plus_data_pB.js", "pB_volume_data.js", "pB_skin_data.js"),
    "demoA": ("viewer_plus_demoA.html", "viewer_data_demoA.js", "viewer_plus_data_demoA.js", "volume_data.js", "skin_data.js"),
    "demoB": ("viewer_plus_demoB.html", "viewer_data_demoB.js", "viewer_plus_data_demoB.js", "volume_data.js", "skin_data.js"),
    "demoC": ("viewer_plus.html", "viewer_data.js", "viewer_plus_data.js", "volume_data.js", "skin_data.js"),
    "pN-Lat": ("viewer_plus_pN-Lat.html", "viewer_data_pN-Lat.js", "viewer_plus_data_pN-Lat.js", "volume_data.js", "skin_data.js"),
    "pN-Med": ("viewer_plus_pN-Med.html", "viewer_data_pN-Med.js", "viewer_plus_data_pN-Med.js", "volume_data.js", "skin_data.js"),
}


def main():
    for case, (template, viewer_name, plus_name, volume_name, skin_name) in CASES.items():
        html = ROOT / "plus" / template
        viewer = ROOT / "plus" / viewer_name
        plus = ROOT / "plus" / plus_name
        volume = ROOT / "plus" / volume_name
        skin = ROOT / "plus" / skin_name
        if not all(p.is_file() for p in (html, viewer, plus, volume, skin)):
            raise FileNotFoundError(f"{case}: missing source asset")
        merged = ROOT / "plus" / f"_merged_{case}.js"
        out = ROOT / "plus" / f"viewer_plus_{case}_single.html"
        merged.write_text(viewer.read_text(encoding="utf-8") + "\n" + plus.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
        # The official builder resolves volume/skin beside itself, so stage the
        # requested case assets under its expected names and restore them after.
        staged = []
        # The official builder only recognizes the three canonical data tags.
        # Remove the plus tag from a temporary HTML copy; its contents are in
        # `merged`, which is injected at the viewer_data tag below.
        staged_html = ROOT / "plus" / f"_staged_{case}.html"
        staged_html.write_text(
            html.read_text(encoding="utf-8")
            .replace(f'<script src="{viewer_name}"></script>', '<script src="viewer_data.js"></script>', 1)
            .replace(f'<script src="{plus_name}"></script>', "", 1)
            .replace(f'<script src="{volume_name}"></script>', '<script src="volume_data.js"></script>', 1)
            .replace(f'<script src="{skin_name}"></script>', '<script src="skin_data.js"></script>', 1),
            encoding="utf-8", newline="\n"
        )
        for source, expected in ((volume, ROOT / "tools" / "volume_data.js"), (skin, ROOT / "tools" / "skin_data.js")):
            old = expected.read_bytes() if expected.exists() else None
            expected.write_bytes(source.read_bytes())
            staged.append((expected, old))
        try:
            subprocess.run([sys.executable, str(TOOL), str(staged_html), str(merged), str(out)], check=True)
        finally:
            staged_html.unlink(missing_ok=True)
            for expected, old in staged:
                if old is None:
                    expected.unlink(missing_ok=True)
                else:
                    expected.write_bytes(old)
        merged.unlink(missing_ok=True)
        text = out.read_text(encoding="utf-8")
        if "<script src=" in text:
            raise AssertionError(f"{case}: external script remains")
        if "VIEWER_PLUS_DATA" not in text:
            raise AssertionError(f"{case}: merged plus data marker missing")
        print(f"PASS {case}: {out.name} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()

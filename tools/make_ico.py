"""Render assets/app.svg into a multi-size Windows .ico (assets/app.ico).

Modern .ico files may embed PNG-compressed images (supported since Vista), so
this script renders the SVG at every standard size with PyQt6's QSvgRenderer
(the same engine as the in-app icons) and packs the PNGs into the ICO
container by hand — no extra tooling beyond the build deps required.
"""

from __future__ import annotations

import os
import struct
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
SVG = ROOT / "assets" / "app.svg"
ICO = ROOT / "assets" / "app.ico"

SIZES = [16, 24, 32, 48, 64, 128, 256]


def _render_pngs() -> list[bytes]:
    from PyQt6.QtCore import QBuffer, QByteArray, Qt
    from PyQt6.QtGui import QImage, QPainter
    from PyQt6.QtSvg import QSvgRenderer
    from PyQt6.QtWidgets import QApplication

    QApplication([])  # a QApplication is needed to paint images
    renderer = QSvgRenderer(QByteArray(SVG.read_bytes()))
    blobs: list[bytes] = []
    for size in SIZES:
        img = QImage(size, size, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        painter = QPainter(img)
        renderer.render(painter)
        painter.end()
        buffer = QBuffer()
        buffer.open(QBuffer.OpenModeFlag.WriteOnly)
        if not img.save(buffer, "PNG"):
            raise SystemExit(f"Konnte {size}px-PNG nicht rendern")
        blobs.append(bytes(buffer.data()))
    return blobs


def main() -> int:
    blobs = _render_pngs()
    # ICONDIR header: reserved, type=1 (icon), count.
    out = struct.pack("<HHH", 0, 1, len(SIZES))
    offset = 6 + 16 * len(SIZES)
    entries = b""
    for size, blob in zip(SIZES, blobs):
        dim = 0 if size >= 256 else size  # 0 encodes 256 in ICONDIRENTRY
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    ICO.write_bytes(out + entries + b"".join(blobs))
    print(ICO)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

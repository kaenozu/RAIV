from __future__ import annotations

from collections.abc import Iterator

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter


def compose_side_by_side_images(left: QImage, right: QImage, background: str = "#000000") -> QImage:
    if left.isNull():
        return right
    if right.isNull():
        return left
    canvas = QImage(left.width() + right.width(), max(left.height(), right.height()), QImage.Format_ARGB32)
    canvas.fill(QColor(background))
    painter = QPainter(canvas)
    painter.drawImage(0, 0, left)
    painter.drawImage(left.width(), 0, right)
    painter.end()
    return canvas


def iter_difference_points(left_image: QImage, right_image: QImage, threshold: int) -> Iterator[tuple[int, int]]:
    width = max(1, min(left_image.width(), right_image.width()))
    height = max(1, min(left_image.height(), right_image.height()))
    left = left_image.scaled(width, height, Qt.IgnoreAspectRatio, Qt.FastTransformation).convertToFormat(QImage.Format_RGB888)
    right = right_image.scaled(width, height, Qt.IgnoreAspectRatio, Qt.FastTransformation).convertToFormat(QImage.Format_RGB888)
    if left.isNull() or right.isNull():
        return
    left_bytes = bytes(left.bits()[: left.sizeInBytes()])
    right_bytes = bytes(right.bits()[: right.sizeInBytes()])
    stride = max(1, left.bytesPerLine())
    step = 2 if width * height > 2_000_000 else 1
    limit = max(0, min(255, threshold)) * 3
    for y in range(0, height, step):
        base = y * stride
        for x in range(0, width, step):
            offset = base + x * 3
            if offset + 2 >= len(left_bytes) or offset + 2 >= len(right_bytes):
                continue
            diff = abs(left_bytes[offset] - right_bytes[offset])
            diff += abs(left_bytes[offset + 1] - right_bytes[offset + 1])
            diff += abs(left_bytes[offset + 2] - right_bytes[offset + 2])
            if diff >= limit:
                yield x, y

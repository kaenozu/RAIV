"""
viewer.py

RAIV のOpenGL画像表示ウィジェットおよびシグナル定義。

なぜ存在するか:
    画像の表示、ズーム/パン/回転/反転操作、比較表示、CPUリサンプルキャッシュ、
    pixmap先読みなど、表示に関する責務を担当する。

関連ファイル:
    - config.py: 定数 (MAX_DISPLAY_SCALE, RESAMPLE_ALGORITHMS 等)
    - raiv.py: MainWindow から GLImageView を生成する
"""

from __future__ import annotations

import time
from collections import OrderedDict, deque

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap, QTransform
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from config import (
    MAX_DISPLAY_SCALE,
    RESAMPLE_ALGORITHMS,
    duplicate_binding_signatures,
    modifier_value,
    normalize_key_bindings,
)

try:
    from PIL import Image as PILImage
except ImportError:
    PILImage = None

try:
    import cv2
except ImportError:
    cv2 = None

try:
    import numpy as np
except ImportError:
    np = None


class AppSignals(QObject):
    process_started = Signal(str)
    process_done = Signal(object)
    folder_images_ready = Signal(object, object)
    prefetch_done = Signal(int, object, object, object, object)
    thumbnail_done = Signal(int, int, object)
    profile_event = Signal(str, float)


class GLImageView(QOpenGLWidget):
    pageRequested = Signal(int)
    firstRequested = Signal()
    lastRequested = Signal()
    zoomChanged = Signal(float)
    splitChanged = Signal(int)
    fullscreenRequested = Signal()
    resetRequested = Signal()
    actualSizeRequested = Signal()
    actionRequested = Signal(str)
    pixmapPrefetchProgress = Signal(int, int, int, float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.background = QColor("#000000")
        self.raw_source_image = QImage()
        self.raw_processed_image = QImage()
        self.source_image = QImage()
        self.processed_image = QImage()
        self.source_pixmap = QPixmap()
        self.processed_pixmap = QPixmap()
        self.display_rotation = 0
        self.display_flip_horizontal = False
        self.display_flip_vertical = False
        self.key_bindings: dict = {}
        self.duplicate_mouse_bindings: set[tuple] = set()
        self.resample_cache: OrderedDict[tuple[int, int, int, str], QPixmap] = OrderedDict()
        self.pixmap_cache: OrderedDict[tuple[int, int, bool, bool], QPixmap] = OrderedDict()
        self.pixmap_cache_limit = 128
        self.pixmap_prefetch_queue: deque[tuple[object, QImage]] = deque()
        self.pixmap_prefetch_keys: set[object] = set()
        self.pixmap_prefetch_done_keys: set[object] = set()
        self.pixmap_prefetch_timer = QTimer(self)
        self.pixmap_prefetch_timer.setSingleShot(True)
        self.pixmap_prefetch_timer.timeout.connect(self.process_pixmap_prefetch)
        self.cpu_resample_cache_enabled = True
        self.cpu_resample_algorithm = "lanczos3"
        self.resample_debounce_timer = QTimer(self)
        self.resample_debounce_timer.setSingleShot(True)
        self.resample_debounce_timer.timeout.connect(self.finish_interactive_resample_delay)
        self.resample_interaction_active = False
        self.resample_debounce_ms = 180
        self.compare_enabled = False
        self.compare_split = 500
        self.compare_line_color = QColor("#ffffff")
        self.compare_line_width = 2
        self.compare_swap_sides = False
        self.compare_shift_drag_moves_boundary = False
        self.horizontal_wheel_navigation = False
        self.horizontal_wheel_inverted = False
        self.zoom = 1.0
        self.offset = QPoint(0, 0)
        self.pan_start: QPoint | None = None
        self.zoom_drag_start: QPoint | None = None
        self.fit_scale_anchor: float | None = None
        self.fit_image_size: tuple[int, int] | None = None

    def set_images(self, source: QImage, processed: QImage | None, preserve_view: bool = False) -> None:
        preserved_scale = self.current_scale() if preserve_view and not self.current_display_image().isNull() else None
        preserved_offset = QPoint(self.offset) if preserve_view else QPoint(0, 0)
        preserved_rotation = self.display_rotation if preserve_view else 0
        preserved_flip_horizontal = self.display_flip_horizontal if preserve_view else False
        preserved_flip_vertical = self.display_flip_vertical if preserve_view else False
        self.raw_source_image = source
        self.raw_processed_image = processed or QImage()
        self.display_rotation = preserved_rotation
        self.display_flip_horizontal = preserved_flip_horizontal
        self.display_flip_vertical = preserved_flip_vertical
        self.rebuild_display_images()
        self.clear_resample_cache()
        if preserve_view and preserved_scale is not None:
            image = self.current_display_image()
            if not image.isNull() and self.width() > 0 and self.height() > 0:
                self.fit_scale_anchor = min(self.width() / image.width(), self.height() / image.height())
                self.fit_image_size = (image.width(), image.height())
                self.zoom = self.clamp_zoom_factor(preserved_scale / max(self.fit_scale_anchor, 0.000001))
                self.offset = preserved_offset
                self.zoomChanged.emit(self.current_scale())
            else:
                self.reset_view(update=False)
        else:
            self.reset_view(update=False)
        self.update()

    def set_processed(self, processed: QImage | None) -> None:
        self.raw_processed_image = processed or QImage()
        self.rebuild_display_images()
        self.clear_resample_cache()
        self.update()

    def set_key_bindings(self, bindings: dict[str, dict[str, dict | None]]) -> None:
        self.key_bindings = normalize_key_bindings(bindings)
        self.duplicate_mouse_bindings = duplicate_binding_signatures(self.key_bindings, "mouse")

    def transformed_image(self, image: QImage) -> QImage:
        if image.isNull():
            return QImage()
        if self.display_rotation % 360 == 0 and not self.display_flip_horizontal and not self.display_flip_vertical:
            return image
        transform = QTransform()
        transform.scale(-1 if self.display_flip_horizontal else 1, -1 if self.display_flip_vertical else 1)
        transform.rotate(self.display_rotation)
        return image.transformed(transform, Qt.SmoothTransformation)

    def rebuild_display_images(self) -> None:
        self.source_image = self.transformed_image(self.raw_source_image)
        self.processed_image = self.transformed_image(self.raw_processed_image)
        self.source_pixmap = self.pixmap_for_image(self.raw_source_image, self.source_image)
        self.processed_pixmap = self.pixmap_for_image(self.raw_processed_image, self.processed_image)

    def pixmap_for_image(self, raw_image: QImage, display_image: QImage) -> QPixmap:
        if raw_image.isNull() or display_image.isNull():
            return QPixmap()
        key = self.pixmap_cache_key(raw_image)
        cached = self.pixmap_cache.get(key)
        if cached is not None:
            self.pixmap_cache.move_to_end(key)
            return cached
        pixmap = QPixmap.fromImage(display_image)
        self.pixmap_cache[key] = pixmap
        while len(self.pixmap_cache) > self.pixmap_cache_limit:
            self.pixmap_cache.popitem(last=False)
        return pixmap

    def pixmap_cache_key(self, raw_image: QImage) -> tuple[int, int, bool, bool]:
        return (
            int(raw_image.cacheKey()),
            self.display_rotation % 360,
            self.display_flip_horizontal,
            self.display_flip_vertical,
        )

    def set_pixmap_cache_limit(self, limit: int) -> None:
        self.pixmap_cache_limit = max(24, int(limit))
        while len(self.pixmap_cache) > self.pixmap_cache_limit:
            self.pixmap_cache.popitem(last=False)

    def queue_pixmap_prefetch(self, items: list[tuple[object, QImage]]) -> None:
        for stable_key, image in items:
            if image.isNull():
                continue
            if stable_key in self.pixmap_prefetch_done_keys or stable_key in self.pixmap_prefetch_keys:
                continue
            self.pixmap_prefetch_queue.append((stable_key, image))
            self.pixmap_prefetch_keys.add(stable_key)
        if self.pixmap_prefetch_queue and not self.pixmap_prefetch_timer.isActive():
            self.pixmap_prefetch_timer.start(1)

    def clear_pixmap_prefetch_state(self) -> None:
        self.pixmap_prefetch_queue.clear()
        self.pixmap_prefetch_keys.clear()
        self.pixmap_prefetch_done_keys.clear()
        self.pixmap_prefetch_timer.stop()

    def process_pixmap_prefetch(self) -> None:
        started = time.perf_counter()
        warmed = 0
        budget = 1
        while self.pixmap_prefetch_queue and warmed < budget:
            stable_key, image = self.pixmap_prefetch_queue.popleft()
            self.pixmap_prefetch_keys.discard(stable_key)
            if image.isNull() or stable_key in self.pixmap_prefetch_done_keys:
                continue
            self.pixmap_for_image(image, self.transformed_image(image))
            self.pixmap_prefetch_done_keys.add(stable_key)
            warmed += 1
        if warmed:
            self.pixmapPrefetchProgress.emit(
                warmed,
                len(self.pixmap_prefetch_queue),
                len(self.pixmap_cache),
                (time.perf_counter() - started) * 1000,
            )
        if self.pixmap_prefetch_queue:
            self.pixmap_prefetch_timer.start(1)

    def rotate_display(self, degrees: int) -> None:
        self.display_rotation = (self.display_rotation + degrees) % 360
        self.rebuild_display_images()
        self.clear_resample_cache()
        self.reset_view(update=False)
        self.update()

    def flip_display(self, horizontal: bool) -> None:
        if horizontal:
            self.display_flip_horizontal = not self.display_flip_horizontal
        else:
            self.display_flip_vertical = not self.display_flip_vertical
        self.rebuild_display_images()
        self.clear_resample_cache()
        self.update()

    def set_background(self, color: str) -> None:
        self.background = QColor(color)
        self.update()

    def set_compare(self, enabled: bool, split: int, line_color: str, line_width: int, swap_sides: bool, shift_boundary: bool) -> None:
        self.compare_enabled = enabled
        self.compare_split = int(split)
        self.compare_line_color = QColor(line_color)
        self.compare_line_width = int(line_width)
        self.compare_swap_sides = bool(swap_sides)
        self.compare_shift_drag_moves_boundary = bool(shift_boundary)
        self.update()

    def set_horizontal_wheel_options(self, enabled: bool, inverted: bool) -> None:
        self.horizontal_wheel_navigation = bool(enabled)
        self.horizontal_wheel_inverted = bool(inverted)

    def set_resample_options(self, enabled: bool, algorithm: str) -> None:
        algorithm = algorithm if algorithm in RESAMPLE_ALGORITHMS else "lanczos3"
        if self.cpu_resample_cache_enabled != enabled or self.cpu_resample_algorithm != algorithm:
            self.cpu_resample_cache_enabled = enabled
            self.cpu_resample_algorithm = algorithm
            self.resample_interaction_active = False
            self.resample_debounce_timer.stop()
            self.clear_resample_cache()
            self.update()

    def clear_resample_cache(self) -> None:
        self.resample_cache.clear()

    def begin_interactive_resample_delay(self) -> None:
        if not self.cpu_resample_cache_enabled:
            return
        self.resample_interaction_active = True
        self.resample_debounce_timer.start(self.resample_debounce_ms)

    def finish_interactive_resample_delay(self) -> None:
        self.resample_interaction_active = False
        self.update()

    def current_display_image(self) -> QImage:
        if self.compare_enabled and not self.processed_image.isNull():
            return self.processed_image
        if not self.processed_image.isNull():
            return self.processed_image
        return self.source_image

    def image_rect(self) -> QRect:
        image = self.current_display_image()
        if image.isNull():
            return QRect()
        scale = self.current_scale()
        width = max(1, round(image.width() * scale))
        height = max(1, round(image.height() * scale))
        x = (self.width() - width) // 2 + self.offset.x()
        y = (self.height() - height) // 2 + self.offset.y()
        return QRect(x, y, width, height)

    def current_scale(self) -> float:
        image = self.current_display_image()
        if image.isNull():
            return 1.0
        size_key = (image.width(), image.height())
        if self.fit_scale_anchor is None or self.fit_image_size != size_key:
            self.fit_scale_anchor = min(self.width() / image.width(), self.height() / image.height())
            self.fit_image_size = size_key
        return max(0.01, min(MAX_DISPLAY_SCALE, self.fit_scale_anchor * self.zoom))

    def clamp_zoom_factor(self, zoom: float) -> float:
        image = self.current_display_image()
        if image.isNull():
            return max(0.05, min(1.0, zoom))
        if self.fit_scale_anchor is None or self.fit_scale_anchor <= 0:
            self.fit_scale_anchor = min(self.width() / image.width(), self.height() / image.height())
            self.fit_image_size = (image.width(), image.height())
        max_zoom = MAX_DISPLAY_SCALE / max(self.fit_scale_anchor, 0.000001)
        return max(0.05, min(max_zoom, zoom))

    def reset_view(self, update: bool = True) -> None:
        self.offset = QPoint(0, 0)
        self.fit_scale_anchor = None
        self.fit_image_size = None
        self.clear_resample_cache()
        image = self.current_display_image()
        if not image.isNull() and self.width() > 0 and self.height() > 0:
            self.fit_scale_anchor = min(self.width() / image.width(), self.height() / image.height())
            self.fit_image_size = (image.width(), image.height())
        self.zoom = 1.0
        self.zoomChanged.emit(self.current_scale())
        if update:
            self.update()
            QTimer.singleShot(0, self.update)

    def reset_display_state(self) -> None:
        self.display_rotation = 0
        self.display_flip_horizontal = False
        self.display_flip_vertical = False
        self.rebuild_display_images()
        self.reset_view()

    def set_actual_zoom_percent(self, percent: int) -> None:
        image = self.current_display_image()
        if image.isNull():
            return
        if self.fit_scale_anchor is None or self.fit_scale_anchor <= 0:
            self.fit_scale_anchor = min(self.width() / image.width(), self.height() / image.height())
            self.fit_image_size = (image.width(), image.height())
        actual_scale = max(0.01, min(MAX_DISPLAY_SCALE, percent / 100.0))
        self.zoom = self.clamp_zoom_factor(actual_scale / self.fit_scale_anchor)
        self.zoomChanged.emit(self.current_scale())
        self.begin_interactive_resample_delay()
        self.update()

    def resizeGL(self, width: int, height: int) -> None:
        if abs(self.zoom - 1.0) > 0.0001:
            return
        image = self.current_display_image()
        if image.isNull() or width <= 0 or height <= 0:
            return
        self.fit_scale_anchor = min(width / image.width(), height / image.height())
        self.fit_image_size = (image.width(), image.height())
        self.zoomChanged.emit(self.current_scale())

    def zoom_to_actual_size(self) -> None:
        image = self.current_display_image()
        if image.isNull() or self.fit_scale_anchor is None or self.fit_scale_anchor <= 0:
            return
        self.zoom = self.clamp_zoom_factor(1.0 / self.fit_scale_anchor)
        self.zoomChanged.emit(self.current_scale())
        self.begin_interactive_resample_delay()
        self.update()

    def resampled_pixmap(self, image: QImage, target: QRect) -> QPixmap | None:
        if not self.cpu_resample_cache_enabled or image.isNull() or target.width() <= 0 or target.height() <= 0:
            return None
        if self.resample_interaction_active:
            return None
        if target.width() == image.width() and target.height() == image.height():
            return None
        key = (int(image.cacheKey()), target.width(), target.height(), self.cpu_resample_algorithm)
        cached = self.resample_cache.get(key)
        if cached is not None:
            self.resample_cache.move_to_end(key)
            return cached
        scaled = self.resample_qimage(image, target.width(), target.height())
        if scaled.isNull():
            return None
        pixmap = QPixmap.fromImage(scaled)
        self.resample_cache[key] = pixmap
        while len(self.resample_cache) > 24:
            self.resample_cache.popitem(last=False)
        return pixmap

    def resample_qimage(self, image: QImage, width: int, height: int) -> QImage:
        if PILImage is None:
            return image.scaled(width, height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        source = image.convertToFormat(QImage.Format_RGBA8888)
        size = source.sizeInBytes()
        data = bytes(source.bits()[:size])
        pil = PILImage.frombytes("RGBA", (source.width(), source.height()), data)
        algorithm = self.cpu_resample_algorithm
        if algorithm == "lanczos4" and cv2 is not None and np is not None:
            array = np.array(pil)
            resized = cv2.resize(array, (width, height), interpolation=cv2.INTER_LANCZOS4)
            pil = PILImage.fromarray(resized, "RGBA")
        else:
            filters = {
                "area": PILImage.Resampling.BOX,
                "bicubic": PILImage.Resampling.BICUBIC,
                "lanczos3": PILImage.Resampling.LANCZOS,
                "lanczos4": PILImage.Resampling.LANCZOS,
            }
            pil = pil.resize((width, height), resample=filters.get(algorithm, PILImage.Resampling.LANCZOS))
        output = pil.convert("RGBA")
        output_data = output.tobytes()
        return QImage(output_data, output.width, output.height, QImage.Format_RGBA8888).copy()

    def draw_image(self, painter: QPainter, target: QRect, image: QImage, pixmap: QPixmap) -> None:
        if image.isNull() or pixmap.isNull():
            return
        resampled = self.resampled_pixmap(image, target)
        if resampled is not None:
            painter.drawPixmap(target.topLeft(), resampled)
        else:
            painter.drawPixmap(target, pixmap)

    def paintGL(self) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.fillRect(self.rect(), self.background)
        target = self.image_rect()
        if target.isNull():
            painter.end()
            return

        source = self.source_image
        processed = self.processed_image
        if self.compare_enabled and not source.isNull():
            split_x = round(target.width() * self.compare_split / 1000)
            left_target = QRect(target.x(), target.y(), split_x, target.height())
            right_target = QRect(target.x() + split_x, target.y(), target.width() - split_x, target.height())
            processed_pixmap = self.processed_pixmap if not self.processed_pixmap.isNull() else self.source_pixmap
            left_pixmap, right_pixmap = (
                (processed_pixmap, self.source_pixmap)
                if self.compare_swap_sides
                else (self.source_pixmap, processed_pixmap)
            )
            left_image, right_image = (
                (processed if not processed.isNull() else source, source)
                if self.compare_swap_sides
                else (source, processed if not processed.isNull() else source)
            )
            if left_target.width() > 0 and not left_pixmap.isNull():
                painter.save()
                painter.setClipRect(left_target)
                self.draw_image(painter, target, left_image, left_pixmap)
                painter.restore()
            if right_target.width() > 0 and not right_pixmap.isNull():
                painter.save()
                painter.setClipRect(right_target)
                self.draw_image(painter, target, right_image, right_pixmap)
                painter.restore()
            pen = QPen(self.compare_line_color)
            pen.setWidth(max(1, self.compare_line_width))
            painter.setPen(pen)
            painter.drawLine(target.x() + split_x, target.y(), target.x() + split_x, target.y() + target.height())
        else:
            pixmap = self.processed_pixmap if not self.processed_pixmap.isNull() else self.source_pixmap
            image = self.processed_image if not self.processed_image.isNull() else self.source_image
            if not pixmap.isNull():
                self.draw_image(painter, target, image, pixmap)
        painter.end()

    def matching_mouse_action(self, event: QEvent, double: bool) -> str | None:
        modifiers = modifier_value(event.modifiers())
        button = int(event.button().value if hasattr(event.button(), "value") else event.button())
        signature = (button, modifiers, double)
        if signature in self.duplicate_mouse_bindings:
            return None
        for action_id, bindings in self.key_bindings.items():
            binding = bindings.get("mouse") if isinstance(bindings, dict) else None
            if not binding:
                continue
            if (
                int(binding.get("button", 0)) == button
                and int(binding.get("modifiers", 0)) == modifiers
                and bool(binding.get("double", False)) == double
            ):
                return action_id
        return None

    def wheelEvent(self, event: QEvent) -> None:
        angle_delta = event.angleDelta()
        if abs(angle_delta.x()) > abs(angle_delta.y()):
            if not self.horizontal_wheel_navigation or event.modifiers() & Qt.ControlModifier:
                event.ignore()
                return
            delta = angle_delta.x()
            pages = max(1, abs(delta) // 120)
            step = pages if delta > 0 else -pages
            if self.horizontal_wheel_inverted:
                step = -step
            self.pageRequested.emit(step)
            return
        delta = angle_delta.y()
        if delta == 0:
            event.ignore()
            return
        if event.modifiers() & Qt.ControlModifier:
            factor = 1.12 if delta > 0 else 1 / 1.12
            self.zoom = self.clamp_zoom_factor(self.zoom * factor)
            self.zoomChanged.emit(self.current_scale())
            self.begin_interactive_resample_delay()
            self.update()
            return
        pages = max(1, abs(delta) // 120)
        self.pageRequested.emit(pages if delta < 0 else -pages)

    def mousePressEvent(self, event: QEvent) -> None:
        action_id = self.matching_mouse_action(event, double=False)
        if action_id:
            self.actionRequested.emit(action_id)
            return
        if event.button() == Qt.LeftButton:
            if event.modifiers() & Qt.ControlModifier:
                self.zoom_drag_start = event.position().toPoint()
                self.pan_start = None
            elif self._drag_moves_compare_boundary(event):
                self._set_split_from_x(round(event.position().x()))
            else:
                self.pan_start = event.position().toPoint()

    def mouseMoveEvent(self, event: QEvent) -> None:
        if event.buttons() & Qt.LeftButton:
            if event.modifiers() & Qt.ControlModifier:
                pos = event.position().toPoint()
                if self.zoom_drag_start is None:
                    self.zoom_drag_start = pos
                dy = pos.y() - self.zoom_drag_start.y()
                if dy:
                    self.zoom = self.clamp_zoom_factor(self.zoom * (1.01 ** (-dy)))
                    self.zoomChanged.emit(self.current_scale())
                    self.begin_interactive_resample_delay()
                    self.zoom_drag_start = pos
                    self.pan_start = None
                    self.update()
            elif self._drag_moves_compare_boundary(event):
                self._set_split_from_x(round(event.position().x()))
                self.pan_start = None
            elif self.pan_start is not None:
                pos = event.position().toPoint()
                delta = pos - self.pan_start
                self.offset += delta
                self.pan_start = pos
                self.update()

    def mouseReleaseEvent(self, event: QEvent) -> None:
        if event.button() == Qt.LeftButton:
            self.zoom_drag_start = None
            self.pan_start = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QEvent) -> None:
        action_id = self.matching_mouse_action(event, double=True)
        if action_id:
            self.actionRequested.emit(action_id)
            return
        super().mouseDoubleClickEvent(event)

    def _drag_moves_compare_boundary(self, event: QEvent) -> bool:
        if not self.compare_enabled or self.processed_image.isNull():
            return False
        shift = bool(event.modifiers() & Qt.ShiftModifier)
        return shift if self.compare_shift_drag_moves_boundary else not shift

    def _set_split_from_x(self, x: int) -> None:
        target = self.image_rect()
        if target.isNull() or target.width() <= 0:
            return
        percent = round((x - target.x()) / target.width() * 1000)
        self.compare_split = max(0, min(1000, percent))
        self.splitChanged.emit(self.compare_split)
        self.update()

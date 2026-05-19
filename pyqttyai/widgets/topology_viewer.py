"""Zoomable, pannable image viewer for network topologies with clickable device hotspots
and a built-in visual map editor."""

import json
from pathlib import Path

from PyQt6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QGraphicsRectItem,
    QGraphicsSimpleTextItem, QGraphicsItem, QVBoxLayout, QHBoxLayout,
    QWidget, QLabel, QPushButton, QFileDialog, QInputDialog, QMessageBox,
    QGraphicsSceneMouseEvent,
)
from PyQt6.QtGui import (
    QPixmap, QPainter, QWheelEvent, QDragEnterEvent, QDropEvent,
    QMouseEvent, QColor, QPen, QBrush, QFont, QCursor, QKeyEvent,
)
from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal, QSizeF


# ═══════════════════════════════════════════════════════════
#  Device Hotspot Item (normal mode — clickable)
# ═══════════════════════════════════════════════════════════

class DeviceHotspotItem(QGraphicsRectItem):
    """Invisible clickable rectangle over a device in the topology."""

    def __init__(self, name: str, x: float, y: float, w: float, h: float,
                 click_callback=None):
        super().__init__(x, y, w, h)
        self.device_name = name
        self._click_callback = click_callback

        self.setPen(QPen(Qt.PenStyle.NoPen))
        self.setBrush(QBrush(Qt.BrushStyle.NoBrush))

        self.setAcceptHoverEvents(True)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setZValue(10)

        # Label (hidden until hover)
        self._label = QGraphicsSimpleTextItem(name, self)
        font = QFont("sans-serif", 9, QFont.Weight.Bold)
        self._label.setFont(font)
        self._label.setBrush(QBrush(QColor("#89b4fa")))
        self._label.setVisible(False)
        self._label.setZValue(12)

        text_width = self._label.boundingRect().width()
        self._label.setPos(
            x + (w - text_width) / 2,
            y - self._label.boundingRect().height() - 4,
        )

        # Label background
        self._label_bg = QGraphicsRectItem(self)
        self._label_bg.setBrush(QBrush(QColor(30, 30, 46, 220)))
        self._label_bg.setPen(QPen(QColor("#89b4fa"), 1))
        self._label_bg.setVisible(False)
        self._label_bg.setZValue(11)

        pad = 4
        lbr = self._label.boundingRect()
        self._label_bg.setRect(
            self._label.pos().x() - pad,
            self._label.pos().y() - pad / 2,
            lbr.width() + pad * 2,
            lbr.height() + pad,
        )

    def hoverEnterEvent(self, event):
        self.setPen(QPen(QColor("#89b4fa"), 2, Qt.PenStyle.SolidLine))
        self.setBrush(QBrush(QColor(137, 180, 250, 35)))
        self._label.setVisible(True)
        self._label_bg.setVisible(True)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.setPen(QPen(Qt.PenStyle.NoPen))
        self.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        self._label.setVisible(False)
        self._label_bg.setVisible(False)
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._click_callback:
            self._click_callback(self.device_name)
            event.accept()
            return
        super().mousePressEvent(event)


# ═══════════════════════════════════════════════════════════
#  Editable Hotspot Item (editor mode — draggable, resizable)
# ═══════════════════════════════════════════════════════════

class _ResizeHandle(QGraphicsRectItem):
    """Small square handle at a corner/edge for resizing."""

    HANDLE_SIZE = 8

    def __init__(self, parent_hotspot: 'EditableHotspotItem', corner: str):
        super().__init__(0, 0, self.HANDLE_SIZE, self.HANDLE_SIZE)
        self._parent_hotspot = parent_hotspot
        self._corner = corner  # "tl", "tr", "bl", "br"

        self.setBrush(QBrush(QColor("#f38ba8")))
        self.setPen(QPen(QColor("#1e1e2e"), 1))
        self.setZValue(25)
        self.setCursor(QCursor(Qt.CursorShape.SizeFDiagCursor))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            # Notify parent to resize
            new_pos = value
            self._parent_hotspot.handle_moved(self._corner, new_pos)
        return super().itemChange(change, value)


class EditableHotspotItem(QGraphicsRectItem):
    """Editable, draggable, resizable hotspot for map editor mode."""

    MIN_SIZE = 20

    def __init__(self, name: str, x: float, y: float, w: float, h: float,
                 editor: 'MapEditor'):
        super().__init__(x, y, w, h)
        self.device_name = name
        self._editor = editor
        self._is_selected = False
        self._dragging = False
        self._drag_offset = QPointF(0, 0)

        # Visual style
        self._normal_pen = QPen(QColor("#a6e3a1"), 2, Qt.PenStyle.DashLine)
        self._selected_pen = QPen(QColor("#f5c2e7"), 2, Qt.PenStyle.SolidLine)
        self._normal_brush = QBrush(QColor(166, 227, 161, 30))
        self._selected_brush = QBrush(QColor(245, 194, 231, 50))

        self.setPen(self._normal_pen)
        self.setBrush(self._normal_brush)
        self.setZValue(20)
        self.setAcceptHoverEvents(True)

        # Name label (always visible in editor)
        self._label = QGraphicsSimpleTextItem(name, self)
        font = QFont("sans-serif", 8, QFont.Weight.Bold)
        self._label.setFont(font)
        self._label.setBrush(QBrush(QColor("#a6e3a1")))
        self._label.setZValue(22)
        self._update_label_pos()

        # Resize handles (only shown when selected)
        self._handles: dict[str, _ResizeHandle] = {}
        for corner in ("tl", "tr", "bl", "br"):
            handle = _ResizeHandle(self, corner)
            handle.setVisible(False)
            handle.setParentItem(None)  # add to scene separately
            self._handles[corner] = handle

    def add_handles_to_scene(self, scene: QGraphicsScene):
        for handle in self._handles.values():
            scene.addItem(handle)
        self._update_handles()

    def remove_from_scene(self, scene: QGraphicsScene):
        for handle in self._handles.values():
            scene.removeItem(handle)
        scene.removeItem(self)

    def _update_label_pos(self):
        r = self.rect()
        text_w = self._label.boundingRect().width()
        self._label.setPos(
            r.x() + (r.width() - text_w) / 2,
            r.y() - self._label.boundingRect().height() - 2,
        )

    def _update_handles(self):
        r = self.rect()
        hs = _ResizeHandle.HANDLE_SIZE
        half = hs / 2

        positions = {
            "tl": QPointF(r.left() - half, r.top() - half),
            "tr": QPointF(r.right() - half, r.top() - half),
            "bl": QPointF(r.left() - half, r.bottom() - half),
            "br": QPointF(r.right() - half, r.bottom() - half),
        }

        for corner, pos in positions.items():
            h = self._handles[corner]
            h.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, False)
            h.setPos(pos)
            h.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)

    def set_selected_state(self, selected: bool):
        self._is_selected = selected
        if selected:
            self.setPen(self._selected_pen)
            self.setBrush(self._selected_brush)
            self._label.setBrush(QBrush(QColor("#f5c2e7")))
        else:
            self.setPen(self._normal_pen)
            self.setBrush(self._normal_brush)
            self._label.setBrush(QBrush(QColor("#a6e3a1")))

        for handle in self._handles.values():
            handle.setVisible(selected)
        self._update_handles()

    def handle_moved(self, corner: str, new_pos: QPointF):
        """Called when a resize handle is dragged."""
        r = self.rect()
        hs = _ResizeHandle.HANDLE_SIZE
        half = hs / 2

        if corner == "tl":
            new_x = new_pos.x() + half
            new_y = new_pos.y() + half
            new_w = r.right() - new_x
            new_h = r.bottom() - new_y
            if new_w >= self.MIN_SIZE and new_h >= self.MIN_SIZE:
                self.setRect(QRectF(new_x, new_y, new_w, new_h))
        elif corner == "tr":
            new_y = new_pos.y() + half
            new_w = (new_pos.x() + half) - r.left()
            new_h = r.bottom() - new_y
            if new_w >= self.MIN_SIZE and new_h >= self.MIN_SIZE:
                self.setRect(QRectF(r.left(), new_y, new_w, new_h))
        elif corner == "bl":
            new_x = new_pos.x() + half
            new_w = r.right() - new_x
            new_h = (new_pos.y() + half) - r.top()
            if new_w >= self.MIN_SIZE and new_h >= self.MIN_SIZE:
                self.setRect(QRectF(new_x, r.top(), new_w, new_h))
        elif corner == "br":
            new_w = (new_pos.x() + half) - r.left()
            new_h = (new_pos.y() + half) - r.top()
            if new_w >= self.MIN_SIZE and new_h >= self.MIN_SIZE:
                self.setRect(QRectF(r.left(), r.top(), new_w, new_h))

        self._update_label_pos()
        self._update_handles()
        self._editor.on_hotspot_changed()

    def set_name(self, name: str):
        self.device_name = name
        self._label.setText(name)
        self._update_label_pos()

    def to_dict(self) -> dict:
        r = self.rect()
        return {
            "name": self.device_name,
            "x": round(r.x()),
            "y": round(r.y()),
            "width": round(r.width()),
            "height": round(r.height()),
        }

    # ── Mouse handling for drag ──

    def hoverEnterEvent(self, event):
        if not self._is_selected:
            self.setPen(QPen(QColor("#f9e2af"), 2, Qt.PenStyle.DashLine))
        self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        if not self._is_selected:
            self.setPen(self._normal_pen)
        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._editor.select_hotspot(self)
            self._dragging = True
            self._drag_offset = event.scenePos() - QPointF(self.rect().x(), self.rect().y())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent):
        if self._dragging:
            new_pos = event.scenePos() - self._drag_offset
            r = self.rect()
            self.setRect(QRectF(new_pos.x(), new_pos.y(), r.width(), r.height()))
            self._update_label_pos()
            self._update_handles()
            self._editor.on_hotspot_changed()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QGraphicsSceneMouseEvent):
        """Double-click to rename."""
        self._editor.rename_hotspot(self)
        event.accept()


# ═══════════════════════════════════════════════════════════
#  Map Editor Controller
# ═══════════════════════════════════════════════════════════

class MapEditor:
    """Manages the map editing state and editable hotspot items."""

    def __init__(self, viewer: 'TopologyViewer'):
        self._viewer = viewer
        self._scene = viewer._scene
        self._hotspots: list[EditableHotspotItem] = []
        self._selected: EditableHotspotItem | None = None
        self._active = False
        self._drawing = False
        self._draw_start: QPointF | None = None
        self._draw_preview: QGraphicsRectItem | None = None
        self._dirty = False

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def hotspots(self) -> list[EditableHotspotItem]:
        return self._hotspots

    @property
    def selected(self) -> EditableHotspotItem | None:
        return self._selected

    def activate(self):
        """Enter editor mode."""
        self._active = True
        self._dirty = False

        # Convert existing normal hotspots to editable ones
        existing_normals = list(self._viewer._hotspot_items)
        for item in existing_normals:
            r = item.rect()
            self._scene.removeItem(item)
            editable = EditableHotspotItem(
                item.device_name, r.x(), r.y(), r.width(), r.height(), self,
            )
            self._scene.addItem(editable)
            editable.add_handles_to_scene(self._scene)
            self._hotspots.append(editable)
        self._viewer._hotspot_items.clear()

        # Hide debug overlay
        for item in self._viewer._debug_items:
            item.setVisible(False)

    def deactivate(self):
        """Exit editor mode, convert back to normal hotspots."""
        self._active = False
        self._deselect()

        # Convert editable back to normal
        for editable in self._hotspots:
            r = editable.rect()
            editable.remove_from_scene(self._scene)

            normal = DeviceHotspotItem(
                editable.device_name,
                r.x(), r.y(), r.width(), r.height(),
                click_callback=self._viewer._on_hotspot_clicked,
            )
            self._scene.addItem(normal)
            self._viewer._hotspot_items.append(normal)

        self._hotspots.clear()
        self._selected = None

        # Rebuild debug items
        self._viewer._rebuild_debug_overlay()

    def select_hotspot(self, hotspot: EditableHotspotItem):
        """Select a hotspot (deselect previous)."""
        if self._selected and self._selected is not hotspot:
            self._selected.set_selected_state(False)
        self._selected = hotspot
        hotspot.set_selected_state(True)
        self._viewer._update_editor_status()

    def _deselect(self):
        if self._selected:
            self._selected.set_selected_state(False)
            self._selected = None

    def deselect_all(self):
        self._deselect()
        self._viewer._update_editor_status()

    def add_hotspot(self, x: float, y: float, w: float, h: float, name: str = ""):
        if not name:
            name, ok = QInputDialog.getText(
                self._viewer, "New Hotspot", "Device name:",
            )
            if not ok or not name.strip():
                return None
            name = name.strip()

        editable = EditableHotspotItem(name, x, y, w, h, self)
        self._scene.addItem(editable)
        editable.add_handles_to_scene(self._scene)
        self._hotspots.append(editable)
        self.select_hotspot(editable)
        self._dirty = True
        return editable

    def delete_selected(self):
        if not self._selected:
            return
        self._selected.remove_from_scene(self._scene)
        self._hotspots.remove(self._selected)
        self._selected = None
        self._dirty = True
        self._viewer._update_editor_status()

    def rename_hotspot(self, hotspot: EditableHotspotItem):
        name, ok = QInputDialog.getText(
            self._viewer, "Rename Hotspot",
            "Device name:", text=hotspot.device_name,
        )
        if ok and name.strip():
            hotspot.set_name(name.strip())
            self._dirty = True
            self._viewer._update_editor_status()

    def on_hotspot_changed(self):
        self._dirty = True
        self._viewer._update_editor_status()

    def to_json_data(self) -> dict:
        """Export all hotspots to JSON-compatible dict."""
        devices = [h.to_dict() for h in self._hotspots]
        data = {
            "topology": self._viewer.current_image_path or "topology",
            "devices": devices,
        }
        if self._viewer._pixmap_item:
            pr = self._viewer._pixmap_item.pixmap().rect()
            data["image_width"] = pr.width()
            data["image_height"] = pr.height()
        return data

    # ── Drawing new hotspot by click+drag on empty area ──

    def start_draw(self, scene_pos: QPointF):
        self._deselect()
        self._drawing = True
        self._draw_start = scene_pos
        self._draw_preview = QGraphicsRectItem()
        self._draw_preview.setPen(QPen(QColor("#fab387"), 2, Qt.PenStyle.DashLine))
        self._draw_preview.setBrush(QBrush(QColor(250, 179, 135, 40)))
        self._draw_preview.setZValue(30)
        self._scene.addItem(self._draw_preview)

    def update_draw(self, scene_pos: QPointF):
        if not self._drawing or not self._draw_start or not self._draw_preview:
            return
        x1, y1 = self._draw_start.x(), self._draw_start.y()
        x2, y2 = scene_pos.x(), scene_pos.y()
        rect = QRectF(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))
        self._draw_preview.setRect(rect)

    def finish_draw(self, scene_pos: QPointF):
        if not self._drawing or not self._draw_start:
            self._drawing = False
            return

        x1, y1 = self._draw_start.x(), self._draw_start.y()
        x2, y2 = scene_pos.x(), scene_pos.y()
        w, h = abs(x2 - x1), abs(y2 - y1)
        x, y = min(x1, x2), min(y1, y2)

        if self._draw_preview:
            self._scene.removeItem(self._draw_preview)
            self._draw_preview = None

        self._drawing = False
        self._draw_start = None

        if w >= 15 and h >= 15:
            self.add_hotspot(x, y, w, h)

    def cancel_draw(self):
        if self._draw_preview:
            self._scene.removeItem(self._draw_preview)
            self._draw_preview = None
        self._drawing = False
        self._draw_start = None

    @property
    def is_drawing(self) -> bool:
        return self._drawing


# ═══════════════════════════════════════════════════════════
#  Debug Overlay Item
# ═══════════════════════════════════════════════════════════

class _DebugOverlayItem(QGraphicsRectItem):
    def __init__(self, x, y, w, h, name: str):
        super().__init__(x, y, w, h)
        self.setPen(QPen(QColor(166, 227, 161, 100), 1, Qt.PenStyle.DashLine))
        self.setBrush(QBrush(QColor(166, 227, 161, 20)))
        self.setZValue(9)

        label = QGraphicsSimpleTextItem(name, self)
        label.setFont(QFont("sans-serif", 7))
        label.setBrush(QBrush(QColor(166, 227, 161, 150)))
        label.setPos(x + 2, y + h + 1)


# ═══════════════════════════════════════════════════════════
#  Editor Toolbar Widget
# ═══════════════════════════════════════════════════════════

class _EditorToolbar(QWidget):
    """Toolbar shown during map editor mode."""

    save_clicked = pyqtSignal()
    done_clicked = pyqtSignal()
    cancel_clicked = pyqtSignal()
    delete_clicked = pyqtSignal()
    rename_clicked = pyqtSignal()

    _BASE_BTN_STYLE = (
        "QPushButton {{"
        "  background-color: {bg};"
        "  color: {fg};"
        "  border: 1px solid {border};"
        "  border-radius: 6px;"
        "  padding: 2px 10px;"
        "  font-size: 11px;"
        "  font-weight: bold;"
        "}}"
        "QPushButton:hover {{"
        "  background-color: {hover_bg};"
        "}}"
        "QPushButton:disabled {{"
        "  background-color: #1e1e2e;"
        "  color: #585b70;"
        "  border: 1px solid #313244;"
        "}}"
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("editorToolbar")
        self.setStyleSheet(
            "#editorToolbar {"
            "  background-color: #302d41;"
            "  border-top: 2px solid #fab387;"
            "}"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)

        self._info = QLabel(
            "MAP EDITOR  —  Draw on empty area | "
            "Drag to move | Double-click to rename | Handles to resize"
        )
        self._info.setStyleSheet(
            "QLabel {"
            "  color: #fab387; font-size: 11px; font-weight: bold;"
            "  background: transparent; border: none;"
            "}"
        )
        layout.addWidget(self._info, stretch=1)

        self._coords = QLabel("")
        self._coords.setStyleSheet(
            "QLabel {"
            "  color: #a6adc8; font-size: 10px;"
            "  background: transparent; border: none;"
            "}"
        )
        self._coords.setFont(QFont("Monospace", 9))
        self._coords.setMinimumWidth(200)
        layout.addWidget(self._coords)

        # ── Rename button ──
        self._rename_btn = QPushButton("Rename")
        self._rename_btn.setFixedHeight(26)
        self._rename_btn.setStyleSheet(self._BASE_BTN_STYLE.format(
            bg="#313244", fg="#f9e2af", border="#f9e2af",
            hover_bg="#45475a",
        ))
        self._rename_btn.clicked.connect(self.rename_clicked.emit)
        layout.addWidget(self._rename_btn)

        # ── Delete button ──
        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setFixedHeight(26)
        self._delete_btn.setStyleSheet(self._BASE_BTN_STYLE.format(
            bg="#313244", fg="#f38ba8", border="#f38ba8",
            hover_bg="#45475a",
        ))
        self._delete_btn.clicked.connect(self.delete_clicked.emit)
        layout.addWidget(self._delete_btn)

        # ── Save JSON button ──
        self._save_btn = QPushButton("Save JSON")
        self._save_btn.setFixedHeight(26)
        self._save_btn.setStyleSheet(self._BASE_BTN_STYLE.format(
            bg="#313244", fg="#89b4fa", border="#89b4fa",
            hover_bg="#45475a",
        ))
        self._save_btn.clicked.connect(self.save_clicked.emit)
        layout.addWidget(self._save_btn)

        # ── Done button ──
        self._done_btn = QPushButton("Done")
        self._done_btn.setFixedHeight(26)
        self._done_btn.setStyleSheet(self._BASE_BTN_STYLE.format(
            bg="#a6e3a1", fg="#1e1e2e", border="#a6e3a1",
            hover_bg="#b8f0b2",
        ))
        self._done_btn.clicked.connect(self.done_clicked.emit)
        layout.addWidget(self._done_btn)

        # ── Cancel button ──
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setFixedHeight(26)
        self._cancel_btn.setStyleSheet(self._BASE_BTN_STYLE.format(
            bg="#f38ba8", fg="#1e1e2e", border="#f38ba8",
            hover_bg="#f5a0b8",
        ))
        self._cancel_btn.clicked.connect(self.cancel_clicked.emit)
        layout.addWidget(self._cancel_btn)

    def set_status(self, text: str):
        self._coords.setText(text)

    def set_rename_enabled(self, enabled: bool):
        self._rename_btn.setEnabled(enabled)

    def set_delete_enabled(self, enabled: bool):
        self._delete_btn.setEnabled(enabled)


# ═══════════════════════════════════════════════════════════
#  Topology Viewer Widget
# ═══════════════════════════════════════════════════════════

class TopologyViewer(QWidget):
    """Image viewer with zoom, pan, drag-and-drop, clickable hotspots, and map editor."""

    device_clicked = pyqtSignal(str)
    editor_deactived = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_image_path: str | None = None
        self._map_path: str = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Header ──
        self._header = QLabel("🕸️ Topology Viewer")
        self._header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._header.setStyleSheet(
            "background-color: #181825; padding: 6px; "
            "font-weight: bold; color: #89b4fa; font-size: 13px;"
        )
        layout.addWidget(self._header)

        # ── Scene & View ──
        self._scene = QGraphicsScene()
        self._view = _ZoomableGraphicsView(self._scene, self)
        self._view.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self._view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self._view.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse
        )
        self._view.setStyleSheet("border: none; background-color: #11111b;")
        layout.addWidget(self._view)

        # ── Editor Toolbar (hidden initially) ──
        self._editor_toolbar = _EditorToolbar()
        self._editor_toolbar.setVisible(False)
        self._editor_toolbar.save_clicked.connect(self._editor_save)
        self._editor_toolbar.done_clicked.connect(self._editor_done)
        self._editor_toolbar.cancel_clicked.connect(self._editor_cancel)
        self._editor_toolbar.delete_clicked.connect(self._editor_delete)
        self._editor_toolbar.rename_clicked.connect(self._editor_rename)
        layout.addWidget(self._editor_toolbar)

        # ── State ──
        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._hotspot_items: list[DeviceHotspotItem] = []
        self._debug_items: list[_DebugOverlayItem] = []
        self._show_debug: bool = False
        self._map_editor = MapEditor(self)

        self.setAcceptDrops(True)

    @property
    def current_map_path(self) -> str:
        return self._map_path

    # ── Image loading ──────────────────────────────────────

    def load_image(self, path: str):
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return

        self.current_image_path = path
        self._scene.clear()
        self._hotspot_items.clear()
        self._debug_items.clear()
        self._pixmap_item = self._scene.addPixmap(pixmap)
        self._view.setSceneRect(QRectF(pixmap.rect()))
        self._view.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)
        self._update_header()

        json_path = Path(path).with_suffix(".json")
        if json_path.exists():
            self.load_map(str(json_path))

    # ── Map loading ────────────────────────────────────────

    def load_map(self, path: str):
        try:
            with open(path, "r") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"⚠ Failed to load topology map: {e}")
            return

        self._clear_hotspots()
        self._map_path = path

        for dev in data.get("devices", []):
            name = dev.get("name", "")
            x = dev.get("x", 0)
            y = dev.get("y", 0)
            w = dev.get("width", 50)
            h = dev.get("height", 50)
            if not name:
                continue

            item = DeviceHotspotItem(
                name, x, y, w, h,
                click_callback=self._on_hotspot_clicked,
            )
            self._scene.addItem(item)
            self._hotspot_items.append(item)

            debug = _DebugOverlayItem(x, y, w, h, name)
            debug.setVisible(self._show_debug)
            self._scene.addItem(debug)
            self._debug_items.append(debug)

        self._update_header()

    def clear_map(self):
        self._clear_hotspots()
        self._map_path = ""
        self._update_header()

    def _clear_hotspots(self):
        for item in self._hotspot_items:
            self._scene.removeItem(item)
        for item in self._debug_items:
            self._scene.removeItem(item)
        self._hotspot_items.clear()
        self._debug_items.clear()

    def _rebuild_debug_overlay(self):
        """Rebuild debug overlay items from current normal hotspots."""
        for item in self._debug_items:
            self._scene.removeItem(item)
        self._debug_items.clear()

        for hotspot in self._hotspot_items:
            r = hotspot.rect()
            debug = _DebugOverlayItem(
                r.x(), r.y(), r.width(), r.height(), hotspot.device_name,
            )
            debug.setVisible(self._show_debug)
            self._scene.addItem(debug)
            self._debug_items.append(debug)

    def _on_hotspot_clicked(self, device_name: str):
        self.device_clicked.emit(device_name)

    def toggle_hotspot_overlay(self, show: bool):
        self._show_debug = show
        for item in self._debug_items:
            item.setVisible(show)

    # ── Header ─────────────────────────────────────────────

    def _update_header(self):
        zoom_pct = round(self._view.transform().m11() * 100)
        name = self.current_image_path.split('/')[-1] if self.current_image_path else "Topology"
        map_indicator = " 🗺️" if self._map_path else ""
        editor_indicator = " ✏️ EDITING" if self._map_editor.is_active else ""
        hotspot_count = len(self._hotspot_items) + len(self._map_editor.hotspots)
        count_text = f" [{hotspot_count} devices]" if hotspot_count > 0 else ""
        self._header.setText(
            f"🕸️ {name} ({zoom_pct}%){count_text}{map_indicator}{editor_indicator}"
        )

    # ── Zoom ───────────────────────────────────────────────

    def reset_zoom(self):
        if self._pixmap_item:
            self._view.resetTransform()
            self._update_header()

    def fit_view(self):
        if self._pixmap_item:
            self._view.fitInView(
                self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio
            )
            self._update_header()

    # ── Drag & Drop ────────────────────────────────────────

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            lower = path.lower()
            if lower.endswith(('.png', '.jpg', '.jpeg', '.bmp', '.svg', '.webp')):
                self.load_image(path)
            elif lower.endswith('.json'):
                self.load_map(path)

    # ═══════════════════════════════════════════════════════
    #  MAP EDITOR INTERFACE
    # ═══════════════════════════════════════════════════════

    def toggle_map_editor(self, active: bool) -> bool:
        if active:
            return self._start_editor()
        return self._editor_done()

    def _start_editor(self) -> bool:
        if not self._pixmap_item:
            QMessageBox.information(
                self, "Map Editor", "Load a topology image first."
            )
            return False

        self._map_editor.activate()
        self._view.setDragMode(QGraphicsView.DragMode.NoDrag)
        self._editor_toolbar.setVisible(True)
        self._editor_toolbar.set_delete_enabled(False)
        self._editor_toolbar.set_rename_enabled(False)
        self._update_header()
        return True

    def _editor_done(self) -> bool:
        """Finish editing and apply changes."""
        if not self._map_editor.is_active:
            return False
        self._map_editor.deactivate()
        self.editor_deactived.emit()
        self._view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self._editor_toolbar.setVisible(False)
        self._update_header()
        return True

    def _editor_cancel(self):
        """Cancel editing — reload original map."""
        if not self._map_editor.is_active:
            return

        # Remove all editor hotspots without converting
        for h in list(self._map_editor.hotspots):
            h.remove_from_scene(self._scene)
        self._map_editor._hotspots.clear()
        self._map_editor._selected = None
        self._map_editor._active = False
        self.editor_deactived.emit()

        self._view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self._editor_toolbar.setVisible(False)

        # Reload original map
        if self._map_path:
            self.load_map(self._map_path)
        self._update_header()

    def _editor_save(self):
        """Save the current map to JSON."""
        default_path = ""
        if self._map_path:
            default_path = self._map_path
        elif self.current_image_path:
            default_path = str(Path(self.current_image_path).with_suffix(".json"))

        path, _ = QFileDialog.getSaveFileName(
            self, "Save Topology Map", default_path,
            "JSON Files (*.json);;All Files (*)",
        )
        if not path:
            return

        data = self._map_editor.to_json_data()

        with open(path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        self._map_path = path
        self._map_editor._dirty = False
        self._update_header()

    def _editor_delete(self):
        self._map_editor.delete_selected()

    def _editor_rename(self):
        if self._map_editor.selected:
            self._map_editor.rename_hotspot(self._map_editor.selected)

    def _update_editor_status(self):
        """Update editor toolbar status text."""
        sel = self._map_editor.selected
        has_sel = sel is not None
        self._editor_toolbar.set_delete_enabled(has_sel)
        self._editor_toolbar.set_rename_enabled(has_sel)

        if sel:
            r = sel.rect()
            self._editor_toolbar.set_status(
                f"📍 {sel.device_name}  x:{round(r.x())} y:{round(r.y())} "
                f"w:{round(r.width())} h:{round(r.height())}"
            )
        else:
            count = len(self._map_editor.hotspots)
            self._editor_toolbar.set_status(f"🗺️ {count} hotspot(s)")

    def handle_editor_key(self, key: int):
        """Handle keyboard shortcuts in editor mode."""
        if not self._map_editor.is_active:
            return

        if key == Qt.Key.Key_Delete or key == Qt.Key.Key_Backspace:
            self._editor_delete()
        elif key == Qt.Key.Key_Escape:
            if self._map_editor.is_drawing:
                self._map_editor.cancel_draw()
            else:
                self._map_editor.deselect_all()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self._map_editor.selected:
                self._map_editor.rename_hotspot(self._map_editor.selected)


# ═══════════════════════════════════════════════════════════
#  Zoomable Graphics View
# ═══════════════════════════════════════════════════════════

class _ZoomableGraphicsView(QGraphicsView):
    """QGraphicsView with zoom, pan, and editor interaction."""

    ZOOM_STEP = 0.02
    HSCROLL_STEP = 20

    def __init__(self, scene, topology_viewer: TopologyViewer, **kwargs):
        super().__init__(scene, **kwargs)
        self._tv = topology_viewer
        self.setMouseTracking(True)

    def wheelEvent(self, event: QWheelEvent):
        dx = event.angleDelta().x()
        dy = event.angleDelta().y()

        if abs(dx) > 3:
            hbar = self.horizontalScrollBar()
            hbar.setValue(hbar.value() + (self.HSCROLL_STEP if dx > 0 else -self.HSCROLL_STEP))
            return

        if not abs(dy) > 3:
            return
        factor = self.ZOOM_STEP if dy > 0 else -self.ZOOM_STEP

        current = self.transform().m11()
        new_zoom = current + factor
        if new_zoom < 0.1 or new_zoom > 5:
            return

        self.resetTransform()
        self.scale(new_zoom, new_zoom)
        self._tv._update_header()

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        editor = self._tv._map_editor
        if editor.is_active:
            # Let items handle double-click first
            super().mouseDoubleClickEvent(event)
            return

        scene_pos = self.mapToScene(event.position().toPoint())
        self.resetTransform()
        self.centerOn(scene_pos)
        self._tv._update_header()

    def mousePressEvent(self, event: QMouseEvent):
        editor = self._tv._map_editor
        if editor.is_active and event.button() == Qt.MouseButton.LeftButton:
            scene_pos = self.mapToScene(event.position().toPoint())

            # Check if clicking on an editable hotspot (let it handle)
            items = self.scene().items(scene_pos)
            for item in items:
                if isinstance(item, (EditableHotspotItem, _ResizeHandle)):
                    super().mousePressEvent(event)
                    return

            # Click on empty area → start drawing new hotspot
            editor.deselect_all()
            editor.start_draw(scene_pos)
            event.accept()
            return

        if editor.is_active and event.button() == Qt.MouseButton.RightButton:
            # Right click → pan (temporary ScrollHandDrag)
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            # Create a fake left-button event for the drag
            fake = QMouseEvent(
                event.type(),
                event.position(),
                event.globalPosition(),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                event.modifiers(),
            )
            super().mousePressEvent(fake)
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        editor = self._tv._map_editor
        if editor.is_active and editor.is_drawing:
            scene_pos = self.mapToScene(event.position().toPoint())
            editor.update_draw(scene_pos)
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        editor = self._tv._map_editor
        if editor.is_active and editor.is_drawing:
            scene_pos = self.mapToScene(event.position().toPoint())
            editor.finish_draw(scene_pos)
            event.accept()
            return

        if editor.is_active and event.button() == Qt.MouseButton.RightButton:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            fake = QMouseEvent(
                event.type(),
                event.position(),
                event.globalPosition(),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                event.modifiers(),
            )
            super().mouseReleaseEvent(fake)
            return

        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent):
        self._tv.handle_editor_key(event.key())
        super().keyPressEvent(event)

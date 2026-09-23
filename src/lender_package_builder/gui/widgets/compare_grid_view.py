"""Compare Packages visual grid -- the primary results view.

Real user request: the original results screen (compare_results_view.py,
kept as a secondary "detailed list" view) makes you read a category and
an explanation for every single finding. What was actually wanted is
much simpler: "the pages that are in one but not the other are
highlighted... don't try to tell me what is different, just highlight
it... make it obvious that this page isn't in the other one and vice
versa."

Every page from both packages is shown as a small thumbnail in one of
two scrolling columns (Old / New). A page whose category is in
`compare_packages.UNMATCHED_CATEGORIES` -- no confidently-equivalent
counterpart on the other side -- gets a highlighted border; every other
page (Exact Match, Equivalent Content, Moved or Reordered, Same
Document Different Version) is shown plainly. That single highlight IS
the primary signal; clicking a page reveals the underlying finding for
anyone who wants the detail, but nothing is narrated by default.

Thumbnails render progressively via a zero-interval QTimer, a few pages
per tick, rather than a background QThread -- simpler and avoids the
real-QThread-under-offscreen-Qt fragility already noted in
tests/gui/conftest.py, while still keeping the UI responsive (the event
loop gets control back between chunks) for a package with hundreds of
pages.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ... import compare_packages
from ...pdf_render import render_page_thumbnail_png
from .. import os_actions
from .flow_layout import FlowLayout

_THUMBNAIL_MAX_DIMENSION_PX = 140
_RENDER_CHUNK_SIZE = 6


class _PageCell(QFrame):
    clicked = Signal(str, int)  # side ("old"/"new"), overall page index

    def __init__(self, side: str, overall_index: int, page_number: int, unmatched: bool, parent: QWidget | None = None):
        super().__init__(parent)
        self.side = side
        self.overall_index = overall_index
        self.setObjectName("ComparePageCell")
        self.setProperty("unmatched", "true" if unmatched else "false")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedWidth(_THUMBNAIL_MAX_DIMENSION_PX + 24)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 6)
        layout.setSpacing(4)

        self.thumbnail_label = QLabel("Loading...")
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail_label.setFixedSize(_THUMBNAIL_MAX_DIMENSION_PX, _THUMBNAIL_MAX_DIMENSION_PX)
        self.thumbnail_label.setObjectName("MutedLabel")
        layout.addWidget(self.thumbnail_label)

        self.number_label = QLabel(f"Page {page_number}")
        self.number_label.setObjectName("MutedLabel")
        self.number_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.number_label)

    def set_thumbnail(self, pixmap: QPixmap) -> None:
        self.thumbnail_label.setPixmap(pixmap)

    def set_thumbnail_unavailable(self) -> None:
        self.thumbnail_label.setText("Preview\nunavailable")

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().mousePressEvent(event)
        self.clicked.emit(self.side, self.overall_index)


class CompareGridView(QWidget):
    view_list_requested = Signal()
    new_comparison_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._result: compare_packages.ComparisonResult | None = None
        self._render_queue: list[_PageCell] = []
        self._render_timer = QTimer(self)
        self._render_timer.setInterval(0)
        self._render_timer.timeout.connect(self._render_next_chunk)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        legend_row = QHBoxLayout()
        legend_row.setSpacing(8)
        swatch = QFrame()
        swatch.setObjectName("ComparePageCell")
        swatch.setProperty("unmatched", "true")
        swatch.setFixedSize(18, 18)
        legend_row.addWidget(swatch)
        legend_label = QLabel("Highlighted = this page has no confident match in the other package.")
        legend_label.setObjectName("MutedLabel")
        legend_row.addWidget(legend_label)
        legend_row.addStretch(1)
        self.summary_label = QLabel()
        self.summary_label.setObjectName("MutedLabel")
        legend_row.addWidget(self.summary_label)
        layout.addLayout(legend_row)

        columns_row = QHBoxLayout()
        columns_row.setSpacing(12)
        self._old_column, self._old_flow = self._build_column("Old / Reference")
        self._new_column, self._new_flow = self._build_column("New / Generated")
        columns_row.addWidget(self._old_column, stretch=1)
        columns_row.addWidget(self._new_column, stretch=1)
        layout.addLayout(columns_row, stretch=1)

        detail_card = QFrame()
        detail_card.setObjectName("Card")
        detail_layout = QVBoxLayout(detail_card)
        self.detail_label = QLabel("Click a highlighted page to see why it was flagged.")
        self.detail_label.setWordWrap(True)
        detail_layout.addWidget(self.detail_label)
        layout.addWidget(detail_card)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        self.open_old_button = QPushButton("Open Old Package")
        self.open_old_button.clicked.connect(self._open_old)
        button_row.addWidget(self.open_old_button)
        self.open_new_button = QPushButton("Open New Package")
        self.open_new_button.clicked.connect(self._open_new)
        button_row.addWidget(self.open_new_button)
        button_row.addStretch(1)
        self.view_list_button = QPushButton("View Detailed List")
        self.view_list_button.clicked.connect(self.view_list_requested.emit)
        button_row.addWidget(self.view_list_button)
        self.export_button = QPushButton("Export Report")
        self.export_button.clicked.connect(self._export_report)
        button_row.addWidget(self.export_button)
        self.new_comparison_button = QPushButton("New Comparison")
        self.new_comparison_button.setObjectName("PrimaryButton")
        self.new_comparison_button.clicked.connect(self.new_comparison_requested.emit)
        button_row.addWidget(self.new_comparison_button)
        layout.addLayout(button_row)

    def _build_column(self, title: str) -> tuple[QWidget, FlowLayout]:
        container = QFrame()
        container.setObjectName("Card")
        outer = QVBoxLayout(container)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        heading = QLabel(title)
        heading.setObjectName("SectionHeading")
        outer.addWidget(heading)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        flow_host = QWidget()
        flow = FlowLayout(flow_host, spacing=8)
        scroll.setWidget(flow_host)
        outer.addWidget(scroll, stretch=1)

        return container, flow

    # -- populating ----------------------------------------------

    def set_result(self, result: compare_packages.ComparisonResult) -> None:
        self._result = result
        self._render_timer.stop()
        self._render_queue = []
        self._clear_column(self._old_flow)
        self._clear_column(self._new_flow)
        self.detail_label.setText("Click a highlighted page to see why it was flagged.")

        unmatched_count = sum(1 for f in result.findings if f.category in compare_packages.UNMATCHED_CATEGORIES)
        self.summary_label.setText(
            f"{result.old_page_count} old page(s), {result.new_page_count} new page(s) -- "
            f"{unmatched_count} highlighted"
        )

        old_finding_by_page = {f.old_overall_page: f for f in result.findings if f.old_overall_page is not None}
        new_finding_by_page = {f.new_overall_page: f for f in result.findings if f.new_overall_page is not None}

        for i in range(result.old_page_count):
            finding = old_finding_by_page.get(i)
            unmatched = finding is not None and finding.category in compare_packages.UNMATCHED_CATEGORIES
            cell = _PageCell("old", i, i + 1, unmatched)
            cell.clicked.connect(self._on_cell_clicked)
            self._old_flow.addWidget(cell)
            self._render_queue.append(cell)

        for i in range(result.new_page_count):
            finding = new_finding_by_page.get(i)
            unmatched = finding is not None and finding.category in compare_packages.UNMATCHED_CATEGORIES
            cell = _PageCell("new", i, i + 1, unmatched)
            cell.clicked.connect(self._on_cell_clicked)
            self._new_flow.addWidget(cell)
            self._render_queue.append(cell)

        self._old_findings_by_page = old_finding_by_page
        self._new_findings_by_page = new_finding_by_page

        if self._render_queue:
            self._render_timer.start()

    def _clear_column(self, flow: FlowLayout) -> None:
        while flow.count():
            item = flow.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _render_next_chunk(self) -> None:
        if self._result is None:
            self._render_timer.stop()
            return
        for _ in range(_RENDER_CHUNK_SIZE):
            if not self._render_queue:
                self._render_timer.stop()
                return
            cell = self._render_queue.pop(0)
            self._render_one(cell)

    def _render_one(self, cell: _PageCell) -> None:
        locations = self._result.old_page_locations if cell.side == "old" else self._result.new_page_locations
        if cell.overall_index >= len(locations):
            cell.set_thumbnail_unavailable()
            return
        path, local_index = locations[cell.overall_index]
        try:
            png_bytes = render_page_thumbnail_png(path, local_index, _THUMBNAIL_MAX_DIMENSION_PX)
            pixmap = QPixmap()
            pixmap.loadFromData(png_bytes, "PNG")
            if pixmap.isNull():
                cell.set_thumbnail_unavailable()
            else:
                cell.set_thumbnail(pixmap)
        except Exception:
            # A single unreadable/unrenderable page must never break the
            # rest of the grid -- it simply shows as unavailable.
            cell.set_thumbnail_unavailable()

    # -- interaction ----------------------------------------------

    def _on_cell_clicked(self, side: str, overall_index: int) -> None:
        findings_by_page = self._old_findings_by_page if side == "old" else self._new_findings_by_page
        finding = findings_by_page.get(overall_index)
        if finding is None:
            self.detail_label.setText("No finding recorded for this page.")
            return
        lines = [f"{finding.category} (confidence {finding.confidence:.2f})"]
        lines.append(f"Old: {finding.old_ref or '(not present)'}")
        lines.append(f"New: {finding.new_ref or '(not present)'}")
        if finding.protected_differences:
            lines.append(f"Protected differences: {', '.join(finding.protected_differences)}")
        lines.append(finding.explanation)
        self.detail_label.setText("\n".join(lines))

    def _open_old(self) -> None:
        if self._result is not None and self._result.old_files:
            os_actions.open_file(self._result.old_files[0])

    def _open_new(self) -> None:
        if self._result is not None and self._result.new_files:
            os_actions.open_file(self._result.new_files[0])

    def _export_report(self) -> None:
        if self._result is None:
            return
        path_str, _ = QFileDialog.getSaveFileName(
            self, "Export Package Comparison Report", "Package Comparison Report.txt", filter="Text Files (*.txt)"
        )
        if path_str:
            compare_packages.write_comparison_report(self._result, Path(path_str))

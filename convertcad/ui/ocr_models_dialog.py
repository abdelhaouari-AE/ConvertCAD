"""
ocr_models_dialog.py — Settings > Scanned pages > "OCR languages and models…"

    Installed     the models on this computer (the built-in one cannot be
                  removed; downloaded ones can)
    Add           a drop-down list of the models not installed yet (other
                  scripts, maximum accuracy) + Download, with a progress bar
                  and Cancel
    Offline PCs   "Install from file…" takes the .onnx files downloaded on
                  another computer (recognised by their checksum)

Files go to the user's models folder (core/ocr_store.py decides where, for
every operating system, the portable program and the installers). The
download runs in a background thread so the window stays responsive.
"""

from typing import List, Optional

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog,
                               QDialogButtonBox, QFileDialog, QHBoxLayout,
                               QHeaderView, QProgressBar,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from ..core import ocr_store
from ..core.ocr_catalog import (BUILTIN_SIZE, BY_ID, MODELS_RELEASE,
                                PACKS, RELEASE_PAGE, OcrPack)
from ..i18n import tr
from .icons import icon
from .widgets import ask_yes_no, label

# downloads still running after their window was closed (kept alive until
# they stop, otherwise Qt would destroy a running thread)
_RUNNING: List["DownloadWorker"] = []


class DownloadWorker(QThread):
    """Downloads one pack in the background."""
    progress = Signal(int, int)          # bytes done, bytes total
    succeeded = Signal(str)              # pack id
    failed = Signal(str)                 # readable message
    cancelled = Signal()

    def __init__(self, pack_id: str):
        super().__init__()
        self.pack_id = pack_id
        self._cancel = False
        self._last_pct = -1

    def cancel(self) -> None:
        self._cancel = True

    def _on_progress(self, done: int, total: int) -> None:
        pct = int(done * 100 / total) if total else -1
        if pct != self._last_pct:              # at most 100 signals
            self._last_pct = pct
            self.progress.emit(done, total)

    def run(self) -> None:
        try:
            ocr_store.download_pack(self.pack_id, progress=self._on_progress,
                                    should_cancel=lambda: self._cancel)
        except ocr_store.DownloadCancelled:
            self.cancelled.emit()
        except ocr_store.DownloadError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:                           # pragma: no cover
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        else:
            self.succeeded.emit(self.pack_id)


def stop_downloads(wait_ms: int = 3000) -> None:
    """Called when the program closes: stop the downloads still running."""
    for w in list(_RUNNING):
        w.cancel()
        w.wait(wait_ms)


def pack_state(pack: OcrPack) -> str:
    """'builtin' | 'downloaded' | 'included' (offline build) | 'missing'."""
    if pack.builtin:
        return "builtin" if ocr_store.builtin_available() else "missing"
    if not ocr_store.is_installed(pack):
        return "missing"
    return "downloaded" if ocr_store.removable(pack) else "included"


class OcrModelsDialog(QDialog):
    models_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("OCR languages and models"))
        self.resize(720, 560)
        self.worker: Optional[DownloadWorker] = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 12)
        lay.setSpacing(8)
        lay.addWidget(label(tr(
            "Scanned pages are read on this computer by PP-OCR models. The "
            "built-in model reads English, French and the other Latin-script "
            "languages. Download the others here: once downloaded, they work "
            "offline."), wrap=True))

        # ---- installed models ------------------------------------------------
        lay.addSpacing(4)
        lay.addWidget(label(tr("Installed"), "faint"))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([tr("Model"), tr("Reads"),
                                              tr("Size")])
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setWordWrap(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        hh = self.table.horizontalHeader()
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft
                               | Qt.AlignmentFlag.AlignVCenter)
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.btn_remove = QPushButton(icon("clear"), tr("Remove"))
        self.btn_remove.setToolTip(tr("Delete the downloaded files of the "
                                      "selected model (the built-in model "
                                      "cannot be removed)."))
        self.btn_remove.clicked.connect(self._remove)
        row.addWidget(self.btn_remove)
        row.addStretch(1)
        lay.addLayout(row)

        # ---- add a model -------------------------------------------------------
        lay.addSpacing(4)
        lay.addWidget(label(tr("Add a language or model"), "faint"))
        row = QHBoxLayout()
        self.available = QComboBox()
        self.available.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.available.setMinimumContentsLength(24)
        self.available.currentIndexChanged.connect(self._show_description)
        row.addWidget(self.available, 1)
        self.btn_download = QPushButton(icon("save"), tr("Download"))
        self.btn_download.setProperty("kind", "primary")
        self.btn_download.clicked.connect(self._download_or_cancel)
        row.addWidget(self.btn_download)
        lay.addLayout(row)
        self.description = label("", "muted", wrap=True)
        lay.addWidget(self.description)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.hide()
        lay.addWidget(self.progress)
        self.info = label("", "caption", wrap=True)
        lay.addWidget(self.info)

        # ---- folder and offline installation ---------------------------------------
        lay.addSpacing(4)
        lay.addWidget(label(tr("Models folder: {path}",
                               path=ocr_store.user_models_dir()),
                            "caption", wrap=True))
        lay.addWidget(label(tr(
            "No internet on this computer? Download the .onnx files from "
            "the ConvertCAD release \"{tag}\" on another computer, then use "
            "\"Install from file…\".", tag=MODELS_RELEASE),
            "caption", wrap=True))
        box = QDialogButtonBox()
        b_file = box.addButton(tr("Install from file…"),
                               QDialogButtonBox.ButtonRole.ActionRole)
        b_file.clicked.connect(self._install_from_file)
        b_folder = box.addButton(tr("Open the models folder"),
                                 QDialogButtonBox.ButtonRole.ActionRole)
        b_folder.clicked.connect(self._open_folder)
        b_page = box.addButton(tr("Download page"),
                               QDialogButtonBox.ButtonRole.ActionRole)
        b_page.setToolTip(RELEASE_PAGE)
        b_page.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(RELEASE_PAGE)))
        b_help = box.addButton(tr("Help"),
                               QDialogButtonBox.ButtonRole.HelpRole)
        b_help.clicked.connect(self._help)
        close = box.addButton(tr("Close"),
                              QDialogButtonBox.ButtonRole.RejectRole)
        close.clicked.connect(self.reject)
        lay.addWidget(box)
        self._refresh()

    def _help(self) -> None:
        from .dialogs import GuideDialog
        GuideDialog(self, "ocr").exec()

    # ---------------------------------------------------------------------
    def _refresh(self, select: str = "") -> None:
        """Fill the installed table and the list of models to download."""
        self.table.setRowCount(0)
        states = {"builtin": tr("Built in"), "downloaded": tr("Downloaded"),
                  "included": tr("Included")}
        for p in PACKS:
            st = pack_state(p)
            if st == "missing":
                continue
            r = self.table.rowCount()
            self.table.insertRow(r)
            name = QTableWidgetItem(f"{tr(p.label)}  ·  {states[st]}")
            name.setData(Qt.ItemDataRole.UserRole, p.id)
            self.table.setItem(r, 0, name)
            self.table.setItem(r, 1, QTableWidgetItem(tr(p.languages)))
            size = ocr_store.human_size(BUILTIN_SIZE if p.builtin else p.size)
            self.table.setItem(r, 2, QTableWidgetItem(size))
        self.table.resizeRowsToContents()
        self.available.blockSignals(True)
        self.available.clear()
        # languages first (the common need), the larger models last
        order = [p for p in PACKS if p.kind == "script"] + \
            [p for p in PACKS if p.kind != "script"]
        for p in order:
            if pack_state(p) == "missing" and not p.builtin:
                self.available.addItem(
                    f"{tr(p.label)}  ({ocr_store.human_size(p.size)})", p.id)
        i = self.available.findData(select)
        self.available.setCurrentIndex(max(i, 0))
        self.available.blockSignals(False)
        self._show_description()
        self._update_buttons()

    def _selected_pack(self) -> Optional[OcrPack]:
        items = self.table.selectedItems()
        if not items:
            return None
        pid = self.table.item(items[0].row(), 0).data(
            Qt.ItemDataRole.UserRole)
        return BY_ID.get(pid)

    def _update_buttons(self) -> None:
        busy = self.worker is not None
        p = self._selected_pack()
        self.btn_remove.setEnabled(not busy and p is not None
                                   and pack_state(p) == "downloaded")
        self.available.setEnabled(not busy and self.available.count() > 0)
        self.btn_download.setText(tr("Cancel") if busy else tr("Download"))
        self.btn_download.setEnabled(busy or self.available.count() > 0)

    def _show_description(self, *_):
        pid = self.available.currentData()
        if pid:
            self.description.setText(tr(BY_ID[pid].languages))
        else:
            self.description.setText(tr("Every model is installed."))

    # ---- download ---------------------------------------------------------------
    def _download_or_cancel(self) -> None:
        if self.worker is not None:
            self.worker.cancel()
            self.info.setText(tr("Cancelling…"))
            return
        pid = self.available.currentData()
        if not pid:
            return
        self.worker = DownloadWorker(pid)
        self.worker.progress.connect(self._on_progress)
        self.worker.succeeded.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.cancelled.connect(self._on_cancelled)
        self.worker.finished.connect(self._on_finished)
        _RUNNING.append(self.worker)
        self.progress.setValue(0)
        self.progress.show()
        self.info.setText(tr("Downloading {name}…", name=tr(BY_ID[pid].label)))
        self.info.setProperty("role", "")
        self._update_buttons()
        self.worker.start()

    def _on_progress(self, done: int, total: int) -> None:
        if total > 0:
            self.progress.setRange(0, 1000)
            self.progress.setValue(int(done * 1000 / total))
        else:
            self.progress.setRange(0, 0)       # size unknown: busy bar

    def _on_done(self, pid: str) -> None:
        self.info.setText(tr("{name} is installed: choose it in Settings > "
                             "Scanned pages.", name=tr(BY_ID[pid].label)))
        self.models_changed.emit()

    def _on_failed(self, message: str) -> None:
        self.info.setText(tr("Download failed: {error}. Check the internet "
                             "connection (or a proxy), or use \"Install from "
                             "file…\".", error=message))

    def _on_cancelled(self) -> None:
        self.info.setText(tr("Download cancelled."))

    def _on_finished(self) -> None:
        w = self.sender()
        if w is not None:
            w.wait(2000)       # really ended before the last reference goes
        if w in _RUNNING:
            _RUNNING.remove(w)
        if w is self.worker:
            self.worker = None
            self.progress.hide()
            self._refresh(select=self.available.currentData() or "")

    # ---- remove / install from file / folder -------------------------------------
    def _remove(self) -> None:
        p = self._selected_pack()
        if p is None:
            return
        if not ask_yes_no(
                self, tr("Remove"), tr("Remove {name} from this computer? It "
                                       "can be downloaded again later.",
                                       name=tr(p.label))):
            return
        try:
            ocr_store.remove_pack(p.id)
        except OSError as exc:
            self.info.setText(str(exc))
        self._refresh()
        self.models_changed.emit()

    def _install_from_file(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, tr("Install from file…"), "",
            tr("OCR models") + " (*.onnx)")
        if not paths:
            return
        try:
            done = ocr_store.install_files(paths)
        except (ocr_store.DownloadError, OSError) as exc:
            self.info.setText(tr("Not installed: {error}", error=str(exc)))
            self._refresh()
            return
        if done:
            names = ", ".join(tr(BY_ID[i].label) for i in done)
            self.info.setText(tr("Installed: {names}.", names=names))
            self.models_changed.emit()
        else:
            self.info.setText(tr("Files copied. A model needs all its files: "
                                 "add the missing ones."))
        self._refresh()

    def _open_folder(self) -> None:
        import os
        folder = ocr_store.user_models_dir()
        os.makedirs(folder, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    # ---------------------------------------------------------------------
    def done(self, result: int) -> None:
        """Closing during a download cancels it (it stops in the
        background; a half-downloaded file is never kept)."""
        if self.worker is not None:
            self.worker.cancel()
            try:
                self.worker.progress.disconnect()
            except (RuntimeError, TypeError):              # pragma: no cover
                pass
        super().done(result)

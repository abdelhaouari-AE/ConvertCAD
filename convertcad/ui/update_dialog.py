"""
update_dialog.py — the window that offers a new version, and the watch on
the user's activity that decides WHEN ConvertCAD looks for one.

    ┌──────────────────────────────────────────────────────┐
    │ [icon]  ConvertCAD 1.4.0 is available                │
    │         This one is 1.3.0.  What's new               │
    │                                                      │
    │         Downloading the update: 1.2 / 2.4 MB  ▓▓▓░░  │
    │                         [Later]  [Update and restart] │
    └──────────────────────────────────────────────────────┘

"Update and restart" downloads only the files that changed (progress and
Cancel in the same window, PatchThread below); the window then closes with
action "restart" and the main window restarts ConvertCAD, which puts the
files in place (core/selfupdate.py). An installation that cannot be updated
file by file (Linux packages, source code) offers "Download" instead.

The window only reports what the user chose (UpdateDialog.action); the
main window does the rest (main_window.py, "updates").

IdleWatcher: the update check never runs while ConvertCAD starts or while
the user works. It counts the seconds since the last click, key or wheel
turn anywhere in ConvertCAD; the main window checks (and offers a new
version) only after a quiet moment.
"""

import threading
import time

from PySide6.QtCore import QEvent, QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox,
                               QHBoxLayout, QLabel, QProgressBar,
                               QVBoxLayout)

from ..i18n import tr
from .icons import app_icon
from .widgets import label

MB = 1024 * 1024


class IdleWatcher(QObject):
    """Seconds since the last user input (mouse move or button, key, wheel,
    touch) anywhere in the application."""

    _INPUT = frozenset((QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress,
                        QEvent.Type.Wheel, QEvent.Type.TouchBegin,
                        QEvent.Type.MouseMove))

    def __init__(self, app: QApplication):
        super().__init__(app)
        self.last = time.monotonic()
        app.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        if event.type() in self._INPUT:
            self.last = time.monotonic()
        return False                                       # never consumed

    def idle_for(self) -> float:
        return time.monotonic() - self.last


class PatchThread(QThread):
    """Reads the list of files of the new version, then downloads the files
    that changed (core/selfupdate.py)."""
    progress = Signal(float, float)            # done MB, total MB
    ready = Signal(str, float, float)          # version, downloaded MB, full MB
    failed = Signal(str)                       # message ('' = cancelled)

    def __init__(self, source: str, app_dir: str, parent=None):
        super().__init__(parent)
        self.source, self.app_dir = source, app_dir
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        from ..core import selfupdate as su
        try:
            plan = su.prepare(self.source, self.app_dir, self._cancel.is_set)
            su.download(plan, self.app_dir,
                        lambda d, t: self.progress.emit(d / MB, t / MB),
                        self._cancel.is_set)
            self.ready.emit(plan.version, plan.download_bytes / MB,
                            plan.full_bytes / MB)
        except su.UpdateCancelled:
            su.discard_pending(self.app_dir)
            self.failed.emit("")
        except Exception as exc:               # UpdateError, OSError...
            su.discard_pending(self.app_dir)
            self.failed.emit(str(exc))


class UpdateDialog(QDialog):
    """Offer a new version.

    mode  "patch"     downloadable file by file: [Later] [Update and restart]
          "download"  full version only: [Later] [Download]
          "ready"     files already downloaded: [Later] [Update and restart]

    After exec(), `action` is what happened: "later", "download",
    "restart" (files ready: restart ConvertCAD now), "cancelled" or
    "failed" (`error` holds the message)."""

    def __init__(self, version: str, current: str, notes_url: str,
                 mode: str = "patch", source: str = "", app_dir: str = "",
                 parent=None):
        super().__init__(parent)
        self.version, self.mode = version, mode
        self.source, self.app_dir = source, app_dir
        self.action, self.error = "later", ""
        self.thread = None
        self.setWindowTitle(tr("Update available"))
        self.setMinimumWidth(460)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 14)
        lay.setSpacing(16)
        logo = QLabel()
        logo.setPixmap(app_icon().pixmap(48, 48))
        logo.setAlignment(Qt.AlignmentFlag.AlignTop)
        lay.addWidget(logo)
        col = QVBoxLayout()
        col.setSpacing(6)
        lay.addLayout(col, 1)
        title = (tr("ConvertCAD {v} is ready to install.", v=version)
                 if mode == "ready"
                 else tr("ConvertCAD {v} is available", v=version))
        self.title = label(title, "title", wrap=True)
        col.addWidget(self.title)
        line = QHBoxLayout()
        line.setSpacing(10)
        line.addWidget(label(tr("This one is {c}.", c=current), "muted"))
        link = tr("What's new")
        self.notes = QLabel(f"<a href='{notes_url}'>{link}</a>")
        self.notes.setOpenExternalLinks(True)
        self.notes.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction)
        self.notes.setToolTip(notes_url)
        line.addWidget(self.notes)
        line.addStretch(1)
        col.addLayout(line)

        self.status = label("", "caption", wrap=True)   # download progress
        self.status.hide()
        col.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.bar.hide()
        col.addWidget(self.bar)
        col.addSpacing(8)

        self.buttons = QDialogButtonBox()
        self.later = self.buttons.addButton(
            tr("Later"), QDialogButtonBox.ButtonRole.RejectRole)
        self.go = self.buttons.addButton(
            tr("Download") if mode == "download"
            else tr("Update and restart"),
            QDialogButtonBox.ButtonRole.AcceptRole)
        self.go.setProperty("kind", "primary")
        self.go.setDefault(True)
        self.later.clicked.connect(self.reject)
        self.go.clicked.connect(self._on_go)
        col.addWidget(self.buttons)

    # ------------------------------------------------------------------
    def _on_go(self) -> None:
        if self.mode == "download":
            self.action = "download"
            self.accept()
        elif self.mode == "ready":                 # nothing to download
            self.action = "restart"
            self.accept()
        else:
            self._start_download()

    def _start_download(self) -> None:
        self.go.setEnabled(False)
        self.later.setText(tr("Cancel"))
        self.status.setText(tr("Checking which files changed…"))
        self.status.show()
        self.bar.setRange(0, 0)                    # busy until the list
        self.bar.show()
        self.thread = PatchThread(self.source, self.app_dir, self)
        self.thread.progress.connect(self.show_progress)
        self.thread.ready.connect(self._on_ready)
        self.thread.failed.connect(self._on_failed)
        self.thread.start()

    def show_progress(self, done_mb: float, total_mb: float) -> None:
        self.status.setText(tr("Downloading the update: {done} / {total} MB",
                               done=f"{done_mb:.1f}", total=f"{total_mb:.1f}"))
        self.bar.setRange(0, 1000)
        self.bar.setValue(int(1000 * done_mb / total_mb) if total_mb else 1000)

    def _on_ready(self, version: str, size_mb: float, full_mb: float) -> None:
        self.version = version
        self.downloaded = (size_mb, full_mb)
        self.status.setText(tr("Restarting ConvertCAD…"))
        self.action = "restart"
        self.accept()

    def _on_failed(self, message: str) -> None:
        self.thread = None
        if not message:
            self.action = "cancelled"
            QDialog.reject(self)
            return
        self.action, self.error = "failed", message
        QDialog.reject(self)

    def reject(self) -> None:
        """Later, Escape or the window's close button. During the download:
        cancel it first (the window closes when the thread has stopped)."""
        if self.thread is not None and self.thread.isRunning():
            self.later.setEnabled(False)
            self.status.setText(tr("Cancelling…"))
            self.thread.cancel()
            return
        super().reject()

    def closeEvent(self, event) -> None:
        if self.thread is not None and self.thread.isRunning():
            event.ignore()
            self.reject()
            return
        super().closeEvent(event)

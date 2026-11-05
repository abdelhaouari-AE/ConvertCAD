"""
update_bar.py — the bar under the toolbar that offers a new version.

    available    ConvertCAD 1.3.1 is available (this one is 1.3.0).
                 [What's new] [Update now] [Later] [Skip this version]
    working      Downloading the update: 3.2 / 24.5 MB   ████░░   [Cancel]
    ready        ConvertCAD 1.3.1 is ready to install: 2.4 MB downloaded
                 instead of 172 MB.   [Restart now] [When I close ConvertCAD]
    done         ConvertCAD was updated to 1.3.1.   [What's new] [x]
    failed       The update could not be installed: ...   [Download…] [x]
    full         (no per-file update here) ... [What's new] [Download] [Later]

The bar only shows things and emits action(name); the main window does the
work (main_window.py, "updates"). PatchThread prepares and downloads the
changed files (core/selfupdate.py) off the interface thread.
"""

import threading

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QProgressBar,
                               QPushButton, QSizePolicy, QToolButton)

from ..i18n import tr
from .icons import icon, icon_size

MB = 1024 * 1024


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


class UpdateBar(QFrame):
    action = Signal(str)        # notes, update, later, skip, cancel, restart,
                                # on_close, download, close

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("UpdateBar")
        self.state = ""
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 5, 8, 5)
        lay.setSpacing(8)
        self.icon = QLabel()
        self.icon.setPixmap(icon("update").pixmap(icon_size(16)))
        lay.addWidget(self.icon)
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setSizePolicy(QSizePolicy.Policy.Expanding,
                                QSizePolicy.Policy.Preferred)
        lay.addWidget(self.text, 1)
        self.bar = QProgressBar()
        self.bar.setFixedWidth(170)
        self.bar.setTextVisible(False)
        self.bar.hide()
        lay.addWidget(self.bar)
        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(6)
        lay.addLayout(self.buttons)
        self.close_btn = QToolButton()
        self.close_btn.setIcon(icon("close"))
        self.close_btn.setAutoRaise(True)
        self.close_btn.setToolTip(tr("Close"))
        self.close_btn.clicked.connect(lambda: self.action.emit("close"))
        lay.addWidget(self.close_btn)
        self.hide()

    # ------------------------------------------------------------------
    def _set(self, state, text, buttons, progress=False, closable=False):
        self.state = state
        self.text.setText(text)
        while self.buttons.count():
            w = self.buttons.takeAt(0).widget()
            if w is not None:
                w.hide()                # gone at once, freed a bit later
                w.deleteLater()
        for label, name, primary in buttons:
            b = QPushButton(label)
            b.setProperty("kind", "primary" if primary else "")
            b.clicked.connect(lambda _=False, n=name: self.action.emit(n))
            self.buttons.addWidget(b)
        self.bar.setVisible(progress)
        self.close_btn.setVisible(closable)
        self.show()

    def show_available(self, version: str, current: str, patch: bool) -> None:
        text = tr("ConvertCAD {v} is available (this one is {c}).",
                  v=version, c=current)
        main = ((tr("Update now"), "update", True) if patch
                else (tr("Download"), "download", True))
        self._set("available", text, [
            (tr("What's new"), "notes", False), main,
            (tr("Later"), "later", False),
            (tr("Skip this version"), "skip", False)])

    def show_checking(self) -> None:
        self._set("working", tr("Checking which files changed…"),
                  [(tr("Cancel"), "cancel", False)], progress=True)
        self.bar.setRange(0, 0)                       # busy

    def show_progress(self, done_mb: float, total_mb: float) -> None:
        if self.state != "working":
            return
        self.text.setText(tr("Downloading the update: {done} / {total} MB",
                             done=f"{done_mb:.1f}", total=f"{total_mb:.1f}"))
        self.bar.setRange(0, 1000)
        self.bar.setValue(int(1000 * done_mb / total_mb) if total_mb else 1000)

    def show_ready(self, version: str, size_mb: float = 0, full_mb: float = 0
                   ) -> None:
        if full_mb:
            text = tr("ConvertCAD {v} is ready to install: {size} MB "
                      "downloaded instead of {full} MB.", v=version,
                      size=f"{size_mb:.1f}", full=f"{full_mb:.0f}")
        else:
            text = tr("ConvertCAD {v} is ready to install.", v=version)
        self._set("ready", text, [
            (tr("Restart now"), "restart", True),
            (tr("When I close ConvertCAD"), "on_close", False)])

    def show_done(self, version: str) -> None:
        self._set("done", tr("ConvertCAD was updated to {v}.", v=version),
                  [(tr("What's new"), "notes", False)], closable=True)

    def show_failed(self, message: str) -> None:
        self._set("failed", tr("The update could not be installed: {e}",
                               e=message),
                  [(tr("Download the full version"), "download", False)],
                  closable=True)

"""
Interface smoke test, without a screen (Qt "offscreen" platform).

Opens the main window, loads the sample plan, converts it in the
background process, edits layers and saves the DXF through the real
save code (the file dialog is replaced by a fixed path).
Skipped automatically when Qt cannot start on the machine.
"""

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")


@pytest.fixture(scope="module")
def qapp(tmp_path_factory):
    home = tmp_path_factory.mktemp("home")
    os.environ["HOME"] = str(home)               # settings go to a temp dir
    os.environ["USERPROFILE"] = str(home)
    try:
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    except Exception as exc:                       # pragma: no cover
        pytest.skip(f"Qt cannot start here: {exc}")
    from convertcad.ui import theme
    theme.apply_theme(app, "dark")
    return app


def _pump(ms=50):
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _wait_busy(w, timeout=180):
    t0 = time.time()
    while w._busy and time.time() - t0 < timeout:
        _pump(100)
    assert not w._busy, "conversion did not finish"


def _wait_saved(w, timeout=180):
    t0 = time.time()
    while w._save_thread is not None and time.time() - t0 < timeout:
        _pump(100)
    assert w._save_thread is None, "saving did not finish"


def test_open_convert_edit_save(qapp, tmp_path, monkeypatch):
    import ezdxf
    from PySide6.QtCore import Qt

    from convertcad.config import Settings
    from convertcad.ui import main_window as mw

    s = Settings()
    s.terms_accepted = True
    s.open_folder_after_save = False
    w = mw.MainWindow(s)
    w.resize(1400, 860)
    w.show()
    _pump(100)
    try:
        w.open_sample()
        _pump(200)
        assert w.pages_panel.page_count() == 2

        w.convert_or_cancel()
        t0 = time.time()
        while w._busy and time.time() - t0 < 120:
            _pump(100)
        assert not w._busy, "conversion did not finish"
        rep = w.result["report"]
        assert rep.success and rep.stats.dimensions >= 5

        model = w.layers_panel.model
        names = [r.name for r in model.rows]
        assert "DIM" in names and "HATCH" in names
        model.setData(model.index(names.index("HATCH"), 0),
                      Qt.CheckState.Unchecked.value,
                      Qt.ItemDataRole.CheckStateRole)
        model.setData(model.index(names.index("DIM"), 2), "COTES",
                      Qt.ItemDataRole.EditRole)

        target = tmp_path / "saved.dxf"
        monkeypatch.setattr(mw.QFileDialog, "getSaveFileName",
                            staticmethod(lambda *a, **k: (str(target), "")))
        w.save_dxf()
        _wait_saved(w)
        doc = ezdxf.readfile(str(target))
        layers = {lay.dxf.name for lay in doc.layers}
        assert "COTES" in layers and "DIM" not in layers
        assert not doc.modelspace().query('*[layer=="HATCH"]')
        assert (tmp_path / "saved_log.txt").exists()

        w.toggle_theme()                  # theme switch must not raise
        _pump(100)
        w.toggle_theme()
    finally:
        if w.result:
            w.result["saved"] = True      # no "unsaved result" question
        w.close()


def test_area_overlay_and_dwg(qapp, tmp_path, monkeypatch):
    """Select an area, convert, show the overlay, then save as DWG (the
    drawing is converted again in the AutoCAD 2000 flavour first)."""
    from PySide6.QtCore import QRectF

    from convertcad.config import Settings
    from convertcad.core.dwg import find_tools
    from convertcad.ui import main_window as mw

    s = Settings()
    s.terms_accepted = True
    w = mw.MainWindow(s)
    w.resize(1400, 860)
    w.show()
    _pump(100)
    try:
        w.open_sample()
        _pump(200)
        page = w.pdf_view.page_rect
        area = QRectF(page.left(), page.top(), page.width() / 2,
                      page.height() / 2)
        w.pdf_view.area_selected.emit(area)
        assert w.options_panel.clip_rect() is not None
        assert w.options_panel.options().clip_rect is not None
        w.convert_or_cancel()
        _wait_busy(w)
        rep = w.result["report"]
        assert rep.success
        assert any("selected area" in n for n in rep.page_notes)
        assert rep.placements and rep.placements[0]["clip"]

        _pump(300)
        w.a_overlay.setChecked(True)
        w._toggle_overlay()
        t0 = time.time()
        while not w.dxf_view.has_overlay() and time.time() - t0 < 60:
            _pump(100)
        assert w.dxf_view.has_overlay()

        if not find_tools().available:
            pytest.skip("LibreDWG not built here (scripts/build_libredwg.sh)")
        target = tmp_path / "area.dwg"
        monkeypatch.setattr(mw.QFileDialog, "getSaveFileName",
                            staticmethod(lambda *a, **k: (str(target), "")))
        monkeypatch.setattr(mw.QMessageBox, "question", staticmethod(
            lambda *a, **k: mw.QMessageBox.StandardButton.Yes))
        w.save_dxf()                      # -> converts again, then saves
        t0 = time.time()
        while (w._busy or w._save_thread is not None or w._pending_save) \
                and time.time() - t0 < 240:
            _pump(100)
        assert target.exists()
        assert target.read_bytes()[:6] == b"AC1015"
        assert (tmp_path / "area_log.txt").exists()
    finally:
        if w.result:
            w.result["saved"] = True
        w.close()


def test_ocr_languages_and_models(qapp, tmp_path, monkeypatch):
    """Settings > Scanned pages: the language list shows the installed
    models only (a missing choice stays visible, marked); the "OCR
    languages and models…" window offers the others for download."""
    from convertcad.config import Settings
    from convertcad.core import ocr_store
    from convertcad.ui import main_window as mw
    from convertcad.ui import ocr_models_dialog as omd

    folder = tmp_path / "models"
    monkeypatch.setenv("CONVERTCAD_OCR_MODELS", str(folder))
    monkeypatch.setattr(ocr_store, "search_dirs", lambda: [str(folder)])

    dlg = omd.OcrModelsDialog()
    try:
        ids = [dlg.available.itemData(i) for i in range(dlg.available.count())]
        assert ids[0] == "arabic" and ids[-1] == "latin_max"
        assert "latin" not in ids                        # built in
        if ocr_store.builtin_available():
            assert dlg.table.rowCount() == 1             # the built-in model
        assert not dlg.btn_remove.isEnabled()
        bad = tmp_path / "photo.onnx"
        bad.write_bytes(b"not a model")
        monkeypatch.setattr(omd.QFileDialog, "getOpenFileNames", staticmethod(
            lambda *a, **k: ([str(bad)], "")))
        dlg._install_from_file()
        assert "not a ConvertCAD OCR model" in dlg.info.text()
    finally:
        dlg.close()

    s = Settings()
    s.terms_accepted = True
    s.options = {"ocr_lang": "latin+arabic", "ocr_quality": "maximum"}
    w = mw.MainWindow(s)
    try:
        panel = w.options_panel
        keys = [panel.ocr_lang.itemData(i)
                for i in range(panel.ocr_lang.count())]
        assert keys == ["latin", "latin+arabic"]
        assert "(not downloaded)" in panel.ocr_lang.itemText(1)
        opt = panel.options()
        assert opt.ocr_lang == "latin+arabic" and opt.ocr_quality == "maximum"
        assert panel.ocr_status.property("role") == "warn"
        opened = []
        monkeypatch.setattr(mw.OcrModelsDialog, "exec",
                            lambda self: opened.append(self) or 0)
        panel.ocr_models_requested.emit()
        assert opened
        panel.ocr_lang.setCurrentIndex(0)                # back to built in
        panel.ocr_quality.setCurrentIndex(0)
        if ocr_store.builtin_available():
            assert panel.ocr_status.property("role") == "ok"
    finally:
        w.close()

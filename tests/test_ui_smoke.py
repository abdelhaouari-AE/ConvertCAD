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
        # ticking a sheet box on and off must not raise (1.2.1 bug:
        # "toggled() only accepts 0 argument(s), 1 given")
        box = w.pages_panel._rows[1].check
        box.setChecked(False)
        box.setChecked(True)
        _pump(50)
        # Feedback and Updates buttons sit at the right end of the menu bar
        corner = w.menuBar().cornerWidget()
        assert corner is not None
        assert [b.defaultAction() for b in w.corner_buttons] == \
            [w.a_feedback, w.a_updates]
        # the language button shows the language code, no "?" button left
        assert w.lang_btn.text() == "EN"
        assert not hasattr(w, "help_btn")
        w.options_panel.export_texts.setChecked(True)     # list of texts
        assert w.options_panel.options().export_texts == "both"

        w.convert_or_cancel()
        t0 = time.time()
        while w._busy and time.time() - t0 < 120:
            _pump(100)
        assert not w._busy, "conversion did not finish"
        rep = w.result["report"]
        assert rep.success and rep.stats.dimensions >= 5
        # the list of texts is made when saving: no new conversion needed
        w.options_panel.export_texts.setChecked(False)
        w.options_panel.export_texts.setChecked(True)
        assert not w.result["stale"]

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
        # the list of texts is read from the saved drawing (edits applied)
        import csv
        with open(tmp_path / "saved_texts.csv", encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
        assert rows and {r["drawing"] for r in rows} == {"saved.dxf"}
        assert {r["layer"] for r in rows if r["kind"] == "dimension"} == \
            {"COTES"}
        assert (tmp_path / "saved_texts.txt").exists()

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
        monkeypatch.setattr(mw, "ask_yes_no", lambda *a, **k: True)
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


def test_select_an_entity_in_the_preview(qapp, sample_plan, tmp_path):
    """A click on a line selects that DXF entity (highlight + its layer);
    a click on empty space clears the selection; hidden layers are not
    selectable. Read-only: the file is not changed."""
    import ezdxf
    from PySide6.QtCore import QPointF

    from convertcad.core import Options, convert
    from convertcad.ui.dxf_view import DxfView

    out = tmp_path / "plan.dxf"
    assert convert(sample_plan, str(out), Options(scale_denominator=100,
                                                  pages=[1])).success
    doc = ezdxf.readfile(str(out))
    line = next(e for e in doc.modelspace().query("LINE")
                if (e.dxf.end - e.dxf.start).magnitude > 500)
    view = DxfView()
    view.resize(900, 700)
    view.show()
    got = []
    view.loaded.connect(got.append)
    view.load(str(out))
    t0 = time.time()
    while not (got and view.selection_ready()) and time.time() - t0 < 120:
        _pump(50)
    assert got == [""] and view.selection_ready()
    picked = []
    view.selected.connect(picked.append)
    mid = (line.dxf.start + line.dxf.end) / 2
    view.centerOn(mid.x, mid.y)
    view.set_scale(view.current_scale() * 4,
                   QPointF(view.mapFromScene(mid.x, mid.y)))
    _pump(50)
    pos = QPointF(view.mapFromScene(mid.x, mid.y))
    assert view.select_at(pos) >= 0
    info = picked[-1]
    assert info["handle"] == line.dxf.handle and info["type"] == "LINE"
    assert info["layer"] == line.dxf.layer and info["length"] > 500
    assert view.selected_index() >= 0
    # hidden layer: not selectable
    view.set_hidden_layers({line.dxf.layer})
    assert view.selected_index() == -1 and picked[-1] is None
    assert view.select_at(pos) == -1 or \
        picked[-1]["layer"] != line.dxf.layer
    view.set_hidden_layers(set())
    # far outside the drawing: nothing
    view.select_at(pos)
    view.select_at(QPointF(2, 2))
    assert picked[-1] is None and view.selected_index() == -1
    view.close()


def test_side_panels_collapse_and_questions_are_translated(qapp):
    """The side panels collapse to a bar (and Ctrl+0 collapses both); the
    Yes / No buttons of questions are in the interface language."""
    from convertcad import i18n
    from convertcad.config import Settings
    from convertcad.ui import main_window as mw
    from convertcad.ui.side_panel import STRIP_WIDTH

    s = Settings()
    s.terms_accepted = True
    w = mw.MainWindow(s)
    w.resize(1400, 860)
    w.show()
    _pump(100)
    try:
        before = w.main_split.sizes()
        w.left_side.strip.clicked.emit()
        _pump(50)
        assert w.left_side.collapsed and w.left_side.width() == STRIP_WIDTH
        assert not w.a_show_pages.isChecked()
        assert w.main_split.sizes()[1] > before[1]       # the view grew
        w.a_show_pages.setChecked(True)
        _pump(50)
        assert not w.left_side.collapsed
        w.a_clean.trigger()
        assert w.left_side.collapsed and w.right_side.collapsed
        w.a_clean.trigger()
        assert not w.left_side.collapsed and not w.right_side.collapsed
        # "Convert a folder" sits next to "Open PDF"
        widgets = [w.toolbar.widgetForAction(a) for a in w.toolbar.actions()]
        assert widgets.index(w.btn_batch) == widgets.index(w.btn_open) + 1
    finally:
        w.close()

    from convertcad.ui.widgets import yes_no_box
    i18n.set_language("fr")
    try:
        box, yes = yes_no_box(None, "ConvertCAD", "Quitter ?")
        texts = sorted(b.text() for b in box.buttons())
        assert yes.text() == "Oui" and box.defaultButton().text() == "Non"
    finally:
        i18n.set_language("en")
    assert texts == ["Non", "Oui"]


def test_update_window_offered_during_a_quiet_moment(qapp, monkeypatch):
    """No check at start-up. A newer version found by the automatic check
    waits for a quiet moment; this source checkout cannot be updated file
    by file, so the window offers the download."""
    from convertcad.config import Settings
    from convertcad.core.updates import UpdateInfo
    from convertcad.ui import main_window as mw

    s = Settings()
    s.terms_accepted = True
    s.auto_update_check = True
    s.last_update_check = 0
    w = mw.MainWindow(s)
    w.show()
    _pump(50)
    shown = []

    def fake_exec(dlg):
        shown.append((dlg.mode, [b.text() for b in dlg.buttons.buttons()],
                      dlg.notes.text()))
        dlg.action = "later"
        return 0
    monkeypatch.setattr(mw.UpdateDialog, "exec", fake_exec)
    checks = []
    monkeypatch.setattr(w, "check_updates", lambda quiet=False:
                        checks.append(quiet))
    monkeypatch.delenv("CONVERTCAD_NO_UPDATE_CHECK", raising=False)
    try:
        assert w._update_thread is None              # nothing at start-up
        w._on_idle_tick()
        assert not checks                            # ConvertCAD just opened
        w._started -= 60                             # open for a minute...
        w._idle.last -= 60                           # ...nobody touched it
        assert w._quiet_moment()
        w._busy = True                               # a conversion runs
        assert not w._quiet_moment()
        w._busy = False
        w._on_idle_tick()
        assert checks == [True]                      # the automatic check
        w._on_idle_tick()
        assert checks == [True]                      # not again before 1 h

        info = UpdateInfo(current="1.0.0", latest="9.0.0",
                          url="https://example.org/r")
        w._update_quiet = True
        w._on_update_checked(info, "")
        assert s.last_update_check > 0 and w._offer and not shown
        w._show_offer()                              # at the quiet moment
        mode, labels, link = shown[0]
        assert mode == "download" and sorted(labels) == ["Download", "Later"]
        assert "https://example.org/r" in link and w._offer is None
        w._update_quiet = False                      # asked by the user:
        w._on_update_checked(info, "")               # shown at once
        assert len(shown) == 2
    finally:
        w.close()


def test_update_window_downloads_then_restarts(qapp):
    """The window: buttons, progress, the download result."""
    from convertcad.ui.update_dialog import UpdateDialog

    dlg = UpdateDialog("9.0.0", "1.0.0", "https://example.org/r", "patch")
    assert sorted(b.text() for b in dlg.buttons.buttons()) == \
        ["Later", "Update and restart"]
    dlg.show_progress(1.0, 2.0)
    assert dlg.bar.value() == 500 and "1.0 / 2.0 MB" in dlg.status.text()
    dlg._on_ready("9.0.0", 2.4, 172)
    assert dlg.action == "restart" and dlg.downloaded == (2.4, 172)
    dlg = UpdateDialog("9.0.0", "1.0.0", "https://example.org/r", "patch")
    dlg._on_failed("no network")
    assert dlg.action == "failed" and dlg.error == "no network"
    dlg = UpdateDialog("9.0.0", "1.0.0", "https://example.org/r", "ready")
    assert "ready to install" in dlg.title.text()
    dlg._on_go()
    assert dlg.action == "restart"

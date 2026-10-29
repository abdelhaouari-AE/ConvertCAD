"""Command-line tool and the background-process job runner."""

import os
import time

import pytest

from convertcad import cli
from convertcad.core.jobs import JobRunner
from convertcad.core.pipeline import Options
from convertcad.core.presets import BUILTIN_PRESETS, apply_preset


def test_parse_pages():
    assert cli.parse_pages("all") is None
    assert cli.parse_pages("1-3,5") == [1, 2, 3, 5]
    assert cli.parse_pages("4-2") == [2, 3, 4]
    with pytest.raises(ValueError):
        cli.parse_pages("0")
    with pytest.raises(ValueError):
        cli.parse_pages("a-b")


def test_cli_single_file(sample_plan, tmp_path, capsys):
    out = tmp_path / "o.dxf"
    code = cli.main([sample_plan, "-o", str(out), "--scale", "100", "-q",
                     "--json", str(tmp_path / "r.json")])
    assert code == 0 and out.exists() and (tmp_path / "r.json").exists()
    assert "SUCCESS" in capsys.readouterr().out


def test_cli_batch_and_errors(sample_plan, tmp_path):
    src = tmp_path / "in"
    src.mkdir()
    (src / "a.pdf").write_bytes(open(sample_plan, "rb").read())
    assert cli.main([str(src), "-o", str(tmp_path / "out"), "-q",
                     "--pages", "1"]) == 0
    assert (tmp_path / "out" / "a.dxf").exists()
    assert cli.main([str(tmp_path / "nope.pdf")]) == 2
    assert cli.main([sample_plan, "--pages", "x"]) == 2


def test_cli_options_mapping():
    args = cli.build_parser().parse_args(
        ["f.pdf", "--scale", "75", "--units", "m", "--no-dims", "--split-pages",
         "--true-color", "--preset", "cnc", "--min-repeats", "5"])
    opt = cli.options_from_args(args)
    assert opt.scale_denominator == 75 and opt.units == "m"
    assert not opt.dimensions and opt.page_mode == "split"
    assert opt.color_mode == "true" and opt.dxf_version == "R12"
    assert opt.block_min_repeats == 5


def test_builtin_presets_keep_the_scale():
    cur = Options(scale_denominator=20, units="cm", pages=[2], auto_scale=True)
    for key, preset in BUILTIN_PRESETS.items():
        opt = apply_preset(cur, preset["options"])
        assert opt.scale_denominator == 20 and opt.units == "cm", key
        assert opt.pages == [2] and opt.auto_scale, key


def _wait(runner, timeout=60):
    msgs, t0 = [], time.time()
    while runner.is_running() and time.time() - t0 < timeout:
        msgs += runner.poll()
        time.sleep(0.05)
    return msgs


def test_job_runner_convert(sample_plan, tmp_path):
    r = JobRunner()
    out = str(tmp_path / "job.dxf")
    r.start_convert(sample_plan, out, Options(scale_denominator=100).to_dict())
    msgs = _wait(r)
    kinds = [m[0] for m in msgs]
    assert "progress" in kinds and kinds[-1] == "done"
    assert msgs[-1][1].success and os.path.isfile(out)


def test_job_runner_cancel(sample_scan, tmp_path):
    r = JobRunner()
    r.start_convert(sample_scan, str(tmp_path / "scan.dxf"),
                    Options(raster_dpi=400).to_dict())
    time.sleep(1.0)
    r.cancel(grace_s=0.5)
    msgs = _wait(r, timeout=20)
    last = msgs[-1]
    assert last[0] == "cancelled" or (last[0] == "done" and last[1].cancelled)


def test_cli_scale_auto_by_default_and_explicit():
    parse = cli.build_parser().parse_args
    opt = cli.options_from_args(parse(["f.pdf"]))
    assert opt.auto_scale
    opt = cli.options_from_args(parse(["f.pdf", "--scale", "1:200"]))
    assert not opt.auto_scale and opt.scale_denominator == 200
    with pytest.raises(ValueError):
        cli.options_from_args(parse(["f.pdf", "--scale", "big"]))


def test_cli_new_options_mapping():
    parse = cli.build_parser().parse_args
    opt = cli.options_from_args(parse(
        ["f.pdf", "--format", "dwg", "--area", "10,20,110,70",
         "--ocr-lang", "eng+fra+ara", "--ocr-quality", "maximum",
         "--no-hatch-patterns", "--no-dashes", "--no-block-rotations"]))
    assert opt.output_format == "dwg"
    assert opt.ocr_lang == "latin+arabic" and opt.ocr_quality == "maximum"
    assert not opt.hatch_patterns and not opt.merge_dashes
    assert not opt.block_rotations
    x0, y0, x1, y1 = opt.clip_rect                  # mm on paper -> points
    assert abs(x0 - 10 * 72 / 25.4) < 1e-9 and abs(y1 - 70 * 72 / 25.4) < 1e-9


def test_cli_area_errors():
    for bad in ("1,2,3", "a,b,c,d", "5,5,5,9"):
        with pytest.raises(ValueError):
            cli.parse_area(bad)
    assert cli.parse_area("100,50,0,0")[0] == 0     # corners in any order


def test_cli_ocr_languages():
    parse = cli.build_parser().parse_args
    assert cli.options_from_args(parse(["f.pdf"])).ocr_lang == "latin"
    opt = cli.options_from_args(parse(["f.pdf", "--ocr-lang", "Arabic"]))
    assert opt.ocr_lang == "arabic"
    for bad in ("latin_max", "klingon", "arabic+greek"):
        with pytest.raises(ValueError):
            cli.options_from_args(parse(["f.pdf", "--ocr-lang", bad]))


def test_cli_lists_ocr_models(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("CONVERTCAD_OCR_MODELS", str(tmp_path))
    assert cli.main(["--list-ocr"]) == 0
    out = capsys.readouterr().out
    for word in ("latin", "latin_max", "arabic", "cyrillic", "built in",
                 str(tmp_path), "latin+arabic"):
        assert word in out
    assert cli.main(["--get-ocr-model", "no-such-model"]) == 2


def test_options_of_version_1_0_still_load():
    old = {"ocr_engine": "paddleocr", "ocr_lang": "eng+fra+ara",
           "ocr_vertical": True, "scale_denominator": 100}
    opt = Options.from_dict(old)
    assert opt.ocr_lang == "latin+arabic" and opt.ocr_quality == "maximum"
    assert Options.from_dict({"ocr_lang": None}).ocr_lang == "latin"
    assert Options.from_dict({"ocr_quality": "ultra"}).ocr_quality == \
        "standard"

from tg_flowmap.dast.reports import generate_reports


def test_error_log_preserves_single_line_fields(cfg, state):
    state.register_bot("@fake_bot")
    state.errors_add("@fake_bot", "capture", "first\nsecond\tfield", "context\r\nnext")
    generate_reports(cfg, state, "@fake_bot")
    lines = (cfg.output_dir / "fake_bot" / "errors.log").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    fields = lines[0].split("\t")
    assert len(fields) == 4
    assert fields[2] == "first\\nsecond field"
    assert fields[3] == "context \\nnext"

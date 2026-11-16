from pathlib import Path


def test_web_ui_has_required_tabs_and_no_scroll_rules():
    html = Path("web/index.html").read_text(encoding="utf-8")
    css = Path("web/styles.css").read_text(encoding="utf-8")
    for label in ["运行总览", "周前计划", "日前计划", "小时滚动", "柴油机与油耗曲线", "求解器与参数", "控制与审计"]:
        assert label in html
    assert "overflow:hidden" in css.replace(" ", "")


def test_ui_exposes_fuel_statistics():
    html = Path("web/index.html").read_text(encoding="utf-8")
    assert "油耗曲线" in html
    assert "柴油消耗量统计" in html


def test_ui_has_database_backed_controls_and_solver_selection():
    html = Path("web/index.html").read_text(encoding="utf-8")
    js = Path("web/app.js").read_text(encoding="utf-8")
    assert 'id="solver-select"' in html
    assert 'id="save-case"' in html
    assert "/api/overview" in js
    assert "/api/case" in js and "method: \"PUT\"" in js
    assert "time_limit_seconds" in js and "mip_gap" in js
    assert "data-control=\"publish\"" in html

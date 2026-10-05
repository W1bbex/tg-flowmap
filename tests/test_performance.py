from __future__ import annotations

import tempfile
import time
import tracemalloc
from pathlib import Path
import pytest

from tg_flowmap.analyzer import GraphAnalyzer
from tg_flowmap.parser import AstParser
from tg_flowmap.visualizer import HtmlVisualizer

SAMPLE_BENCHMARK_BOT = """
def main_menu():
    buttons = [
        [{"text": f"Кнопка {i}", "callback_data": f"action:{i}"} for i in range(4)]
        for _ in range(3)
    ]
    return {"inline_keyboard": buttons}

def handle_update(data):
    if data == "start":
        send_message("Старт", reply_markup=main_menu())
    for i in range(12):
        if data == f"action:{i}":
            send_message(f"Экран {i}", reply_markup=main_menu())
"""

def test_pipeline_performance_and_memory_budget():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        for f_idx in range(5):
            (tmp_path / f"bot_module_{f_idx}.py").write_text(SAMPLE_BENCHMARK_BOT, encoding="utf-8")

        tracemalloc.start()
        t_start = time.perf_counter()

        parser = AstParser()
        parser.parse_dir(tmp_path)

        analyzer = GraphAnalyzer(parser.nodes, parser.keyboards)
        bot_map = analyzer.build_map()

        out_html = tmp_path / "flowmap.html"
        visualizer = HtmlVisualizer(bot_map)
        visualizer.render(out_html)

        t_elapsed = time.perf_counter() - t_start
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        peak_mb = peak / (1024 * 1024)

        assert t_elapsed < 1.5, f"Pipeline exceeded 1.5s time budget: {t_elapsed:.3f}s"
        assert peak_mb < 30.0, f"Memory allocation exceeded 30MB budget: {peak_mb:.2f}MB"
        assert out_html.exists()
        assert out_html.stat().st_size > 10_000

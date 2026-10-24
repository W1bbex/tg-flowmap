from __future__ import annotations

import tempfile
import time
import tracemalloc
from pathlib import Path
import pytest

from tg_flowmap.analyzer import GraphAnalyzer
from tg_flowmap.parser import AstParser
from tg_flowmap.visualizer import HtmlVisualizer


def generate_benchmark_module(mod_idx: int) -> str:
    """Generates a realistic Telegram bot module with nested keyboards and handlers."""
    lines = []
    lines.append(f"def menu_{mod_idx}():")
    lines.append("    return {'inline_keyboard': [")
    for r in range(4):
        row_btns = [f"{{'text': 'Btn {mod_idx}_{r}_{c}', 'callback_data': 'act_{mod_idx}_{r}_{c}'}}" for c in range(3)]
        lines.append("        [" + ", ".join(row_btns) + "],")
    lines.append("        [{'text': '« Назад', 'callback_data': 'menu'}],")
    lines.append("    ]}")
    lines.append("")
    lines.append(f"def handle_{mod_idx}(data):")
    lines.append(f"    if data == 'open_{mod_idx}':")
    lines.append(f"        send_message('Screen {mod_idx}', reply_markup=menu_{mod_idx}())")
    for r in range(4):
        for c in range(3):
            lines.append(f"    elif data == 'act_{mod_idx}_{r}_{c}':")
            lines.append(f"        send_message('Action {mod_idx}_{r}_{c}', reply_markup=menu_{mod_idx}())")
    return "\n".join(lines)


def test_pipeline_performance_and_memory_budget():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        for f_idx in range(5):
            code = generate_benchmark_module(f_idx)
            (tmp_path / f"bot_module_{f_idx}.py").write_text(code, encoding="utf-8")

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

        # Real verification of extracted nodes and edges
        assert len(parser.keyboards) == 5, f"Expected 5 keyboards, got {len(parser.keyboards)}"
        assert len(bot_map.nodes) >= 60, f"Expected >= 60 nodes, got {len(bot_map.nodes)}"
        assert len(bot_map.edges) >= 60, f"Expected >= 60 edges, got {len(bot_map.edges)}"

        assert t_elapsed < 2.0, f"Pipeline exceeded 2.0s time budget: {t_elapsed:.3f}s"
        assert peak_mb < 40.0, f"Memory allocation exceeded 40MB budget: {peak_mb:.2f}MB"
        assert out_html.exists()
        assert out_html.stat().st_size > 50_000

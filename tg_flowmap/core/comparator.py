from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from tg_flowmap.core.llm_exporter import generate_llm_benchmark_prompt


class BotComparator:
    """
    Compares two Telegram bots (SAST vs DAST, SAST vs SAST, DAST vs DAST)
    and produces structured Markdown comparison reports and LLM benchmarking prompts.
    """

    def __init__(
        self,
        bot_a_name: str,
        bot_a_data: Dict[str, Any],
        bot_b_name: str,
        bot_b_data: Dict[str, Any],
    ):
        self.bot_a_name = bot_a_name
        self.bot_a_data = bot_a_data
        self.bot_b_name = bot_b_name
        self.bot_b_data = bot_b_data

    @staticmethod
    def extract_metrics_from_bot_map(bot_map: Any) -> Dict[str, Any]:
        """Extracts normalized metrics from a SAST BotMap object or dict."""
        if hasattr(bot_map, "nodes"):
            screens_count = len(bot_map.nodes)
            buttons_count = sum(
                len(n.keyboard.all_buttons())
                for n in bot_map.nodes.values()
                if n.keyboard
            )
            dead_ends = sum(1 for iss in bot_map.issues if getattr(iss, "issue_type", "") == "dead_end")
            missing_back = sum(1 for iss in bot_map.issues if getattr(iss, "issue_type", "") == "missing_back")
            return {
                "screens_count": screens_count,
                "buttons_count": buttons_count,
                "dead_ends": dead_ends,
                "missing_back": missing_back,
                "max_depth": "AST Static",
            }
        elif isinstance(bot_map, dict):
            nodes = bot_map.get("nodes", {})
            issues = bot_map.get("issues", [])
            screens_count = len(nodes)
            node_iterable = nodes.values() if isinstance(nodes, dict) else (nodes if isinstance(nodes, list) else [])
            buttons_count = sum(
                sum(len(row) for row in (n.get("keyboard") or {}).get("rows", []))
                for n in node_iterable
                if isinstance(n, dict)
            )
            dead_ends = sum(1 for iss in issues if iss.get("issue_type") == "dead_end")
            missing_back = sum(1 for iss in issues if iss.get("issue_type") == "missing_back")
            return {
                "screens_count": screens_count,
                "buttons_count": buttons_count,
                "dead_ends": dead_ends,
                "missing_back": missing_back,
                "max_depth": "AST Static",
            }
        return {"screens_count": 0, "buttons_count": 0, "dead_ends": 0, "missing_back": 0, "max_depth": "N/A"}

    @staticmethod
    def extract_metrics_from_dast(dast_summary: Dict[str, Any]) -> Dict[str, Any]:
        """Extracts normalized metrics from DAST scan result or state summary."""
        return {
            "screens_count": dast_summary.get("screens_count", dast_summary.get("total_screens", 0)),
            "buttons_count": dast_summary.get("buttons_count", dast_summary.get("total_buttons", 0)),
            "dead_ends": dast_summary.get("dead_ends", 0),
            "missing_back": dast_summary.get("missing_back", 0),
            "max_depth": dast_summary.get("max_depth", 8),
        }

    def _resolve_metrics(self) -> tuple[Dict[str, Any], Dict[str, Any]]:
        def _extract(data: Any) -> Dict[str, Any]:
            if isinstance(data, dict):
                if "metrics" in data and isinstance(data["metrics"], dict):
                    return data["metrics"]
                if "nodes" in data:
                    return self.extract_metrics_from_bot_map(data)
                return self.extract_metrics_from_dast(data)
            elif hasattr(data, "nodes"):
                return self.extract_metrics_from_bot_map(data)
            return self.extract_metrics_from_dast(data)

        metrics_a = _extract(self.bot_a_data)
        metrics_b = _extract(self.bot_b_data)
        return metrics_a, metrics_b

    def build_comparison_markdown(self) -> str:
        metrics_a, metrics_b = self._resolve_metrics()

        def _leader(val_a: Any, val_b: Any, lower_is_better: bool = False) -> str:
            try:
                v_a = float(val_a)
                v_b = float(val_b)
                if v_a == v_b:
                    return "Ничья"
                if lower_is_better:
                    return self.bot_a_name if v_a < v_b else self.bot_b_name
                return self.bot_a_name if v_a > v_b else self.bot_b_name
            except (ValueError, TypeError):
                return "Ничья" if val_a == val_b else self.bot_a_name

        s_a, s_b = metrics_a.get('screens_count', 0), metrics_b.get('screens_count', 0)
        b_a, b_b = metrics_a.get('buttons_count', 0), metrics_b.get('buttons_count', 0)
        d_a, d_b = metrics_a.get('dead_ends', 0), metrics_b.get('dead_ends', 0)
        m_a, m_b = metrics_a.get('missing_back', 0), metrics_b.get('missing_back', 0)

        lines = [
            "# ⚔️ Telegram Bot Benchmark & Comparison",
            "",
            f"**Объект A (Исходный бот):** `{self.bot_a_name}`  ",
            f"**Объект B (Конкурент / Оппонент):** `{self.bot_b_name}`  ",
            "",
            "---",
            "",
            "## 📊 Сравнительная матрица",
            "",
            f"| Метрика интерфейса | {self.bot_a_name} | {self.bot_b_name} | Лидер |",
            "|---|---|---|---|",
            f"| Всего экранов в структуре | {s_a} | {s_b} | {_leader(s_a, s_b)} |",
            f"| Всего интерактивных действий | {b_a} | {b_b} | {_leader(b_a, b_b)} |",
            f"| Тупиковые экраны (Dead-ends) | {d_a} | {d_b} | {_leader(d_a, d_b, lower_is_better=True)} (меньше = лучше) |",
            f"| Экраны без кнопки возврата | {m_a} | {m_b} | {_leader(m_a, m_b, lower_is_better=True)} |",
            "",
            "---",
            "",
            "💡 *Для детального продуктового аудита с рекомендациями по улучшению воронки используйте сгенерированный файл `llm_prompt.md`.*",
        ]
        return "\n".join(lines)

    def export(self, output_dir: Path) -> Dict[str, Path]:
        """Saves comparison.md and llm_prompt.md into output_dir without extra user flags."""
        output_dir.mkdir(parents=True, exist_ok=True)
        comparison_path = output_dir / "comparison.md"
        prompt_path = output_dir / "llm_prompt.md"

        metrics_a, metrics_b = self._resolve_metrics()

        comp_text = self.build_comparison_markdown()
        comparison_path.write_text(comp_text, encoding="utf-8")

        screens_a = self.bot_a_data.get("screens") if isinstance(self.bot_a_data, dict) else None
        screens_b = self.bot_b_data.get("screens") if isinstance(self.bot_b_data, dict) else None

        prompt_text = generate_llm_benchmark_prompt(
            bot_a_name=self.bot_a_name,
            bot_a_metrics=metrics_a,
            bot_b_name=self.bot_b_name,
            bot_b_metrics=metrics_b,
            bot_a_screens=screens_a,
            bot_b_screens=screens_b,
        )
        prompt_path.write_text(prompt_text, encoding="utf-8")

        return {
            "comparison": comparison_path,
            "llm_prompt": prompt_path,
        }

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

from tg_flowmap.analyzer import GraphAnalyzer
from tg_flowmap.parser import AstParser
from tg_flowmap.visualizer import HtmlVisualizer


def load_env_token(target_path: Path) -> Optional[str]:
    """Tries to find BOT_TOKEN or TELEGRAM_BOT_TOKEN in env or .env files."""
    for var in ("TELEGRAM_BOT_TOKEN", "BOT_TOKEN"):
        val = os.environ.get(var)
        if val and ":" in val:
            return val.strip()

    candidate_envs = [
        Path.cwd() / ".env",
        target_path / ".env" if target_path.is_dir() else target_path.parent / ".env",
        target_path.parent / ".env",
        Path(__file__).resolve().parent.parent / ".env",
    ]
    for env_path in candidate_envs:
        if env_path.exists():
            try:
                for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip("'\"")
                    if k in ("TELEGRAM_BOT_TOKEN", "BOT_TOKEN") and ":" in v:
                        return v
            except Exception:
                pass
    return None


def run_analysis(
    target_path: Path,
    output_html: Path | None = None,
    output_json: Path | None = None,
    strict: bool = False,
    bot_token: str | None = None,
) -> int:
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    if not target_path.exists():
        print(f"[ERROR] Целевой путь не существует: {target_path}", file=sys.stderr)
        return 1

    parser = AstParser()
    if target_path.is_file():
        parser.parse_file(target_path)
    else:
        parser.parse_dir(target_path)

    analyzer = GraphAnalyzer(
        parser.nodes,
        parser.keyboards,
        screen_aliases=parser.screen_aliases,
        hub_return_nodes=parser.hub_return_nodes,
    )
    bot_map = analyzer.build_map()

    # Fetch Telegram Premium custom emojis if present
    token = bot_token or load_env_token(target_path)
    if parser.custom_emoji_ids:
        if token:
            from tg_flowmap.emoji_fetcher import fetch_custom_emojis
            emojis = fetch_custom_emojis(token, parser.custom_emoji_ids)
            bot_map.custom_emojis = emojis
        else:
            from tg_flowmap.emoji_fetcher import get_default_cache_dir, load_cached_emoji
            cache_dir = get_default_cache_dir()
            cached = {}
            for eid in parser.custom_emoji_ids:
                data_url = load_cached_emoji(eid, cache_dir)
                if data_url:
                    cached[eid] = data_url
            if cached:
                bot_map.custom_emojis = cached

    stats = bot_map.stats
    print("=" * 60)
    print("  🧭 TG-FLOWMAP — Telegram Bot Visualizer & Linter")
    print("=" * 60)
    print(f"Цель:            {target_path.resolve()}")
    print(f"Всего экранов:   {stats.get('total_nodes', 0)}")
    print(f"Всего связей:    {stats.get('total_edges', 0)}")
    print(f"Клавиатур найдено: {len(parser.keyboards)}")
    print(f"Дублирующихся экранов: {stats.get('duplicate_screens', 0)}")
    if parser.custom_emoji_ids:
        print(f"Премиум эмодзи:  {len(parser.custom_emoji_ids)} (загружено: {len(bot_map.custom_emojis)})")
    print(f"Тупиков (Dead-end): {stats.get('dead_ends', 0)}")
    print(f"Ошибок эмодзи:   {stats.get('broken_emojis', 0)}")
    print(f"Без кнопки Назад: {stats.get('missing_backs', 0)}")
    print("-" * 60)

    if bot_map.issues:
        print("\n🔍 НАЙДЕННЫЕ ДЕФЕКТЫ И ПРЕДУПРЕЖДЕНИЯ:")
        for idx, issue in enumerate(bot_map.issues, 1):
            icon = "❌" if issue.severity == "error" else "⚠️" if issue.severity == "warning" else "ℹ️"
            src_info = ""
            if issue.source_file:
                p = Path(issue.source_file).name
                line = f":{issue.line_number}" if issue.line_number else ""
                src_info = f" ({p}{line})"
            print(f"  {idx}. {icon} [{issue.issue_type.upper()}] {issue.message}{src_info}")
        print()
    else:
        print("\n✅ Дефектов и тупиков не обнаружено!")

    if output_html:
        output_html.parent.mkdir(parents=True, exist_ok=True)
        visualizer = HtmlVisualizer(bot_map)
        visualizer.render(output_html)
        print(f"📊 Интерактивная карта сохранена: {output_html.resolve()}")

    if output_json:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(bot_map.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"📄 JSON-отчёт сохранён: {output_json.resolve()}")

    dead_ends = stats.get("dead_ends", 0)
    broken_emojis = stats.get("broken_emojis", 0)
    if strict and (dead_ends > 0 or broken_emojis > 0):
        print("\n[STRICT MODE] Обнаружены критические ошибки! Выход с кодом 1.")
        return 1

    return 0


def main() -> None:
    arg_parser = argparse.ArgumentParser(
        prog="tg-flowmap",
        description="Static AST analyzer and visualizer for Telegram Bot navigation, callbacks, and UI/UX.",
    )
    arg_parser.add_argument(
        "target",
        type=str,
        help="Путь к файлу бота (.py) или каталогу с проектом бота",
    )
    arg_parser.add_argument(
        "-o",
        "--output",
        type=str,
        default=None,
        help="Путь к результирующему HTML файлу интерактивной карты (по умолчанию: flowmap.html)",
    )
    arg_parser.add_argument(
        "--json",
        type=str,
        default=None,
        help="Путь к файлу для экспорта графа и дефектов в JSON",
    )
    arg_parser.add_argument(
        "--strict",
        action="store_true",
        help="Возвращать код ошибки 1 при обнаружении тупиков или сломанных эмодзи (для CI/CD)",
    )
    arg_parser.add_argument(
        "-t",
        "--token",
        type=str,
        default=None,
        help="Токен Telegram-бота для загрузки оригинальных Premium эмодзи",
    )

    args = arg_parser.parse_args()
    target = Path(args.target)
    out_html = Path(args.output) if args.output else target.parent / f"{target.stem}_flowmap.html"
    out_json = Path(args.json) if args.json else None

    exit_code = run_analysis(
        target_path=target,
        output_html=out_html,
        output_json=out_json,
        strict=args.strict,
        bot_token=args.token,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()

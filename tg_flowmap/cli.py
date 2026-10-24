from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

from tg_flowmap.core.comparator import BotComparator
from tg_flowmap.core.models import BotMap
from tg_flowmap.sast.analyzer import GraphAnalyzer
from tg_flowmap.sast.parser import AstParser
from tg_flowmap.visualizer.html_builder import HtmlVisualizer


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


def build_sast_markdown_report(bot_map: BotMap, target_path: Path) -> str:
    stats = bot_map.stats
    name = target_path.name
    lines = [
        f"# 🧭 TG-FLOWMAP SAST Report: {name}",
        "",
        f"- **Путь:** `{target_path.resolve()}`",
        f"- **Всего экранов:** {stats.get('total_nodes', 0)}",
        f"- **Всего переходов / связей:** {stats.get('total_edges', 0)}",
        f"- **Тупиков (Dead-end):** {stats.get('dead_ends', 0)}",
        f"- **Ошибок эмодзи:** {stats.get('broken_emojis', 0)}",
        f"- **Экранов без кнопки «Назад»:** {stats.get('missing_backs', 0)}",
        "",
        "---",
        "",
        "## 🔍 Найденные дефекты и предупреждения",
        "",
    ]
    if bot_map.issues:
        for idx, issue in enumerate(bot_map.issues, 1):
            icon = "❌" if issue.severity == "error" else "⚠️" if issue.severity == "warning" else "ℹ️"
            src_info = ""
            if issue.source_file:
                p = Path(issue.source_file).name
                line = f":{issue.line_number}" if issue.line_number else ""
                src_info = f" *({p}{line})*"
            lines.append(f"{idx}. {icon} **[{issue.issue_type.upper()}]** {issue.message}{src_info}")
    else:
        lines.append("✅ *Дефектов и тупиков в навигации не обнаружено.*")

    lines.extend([
        "",
        "---",
        "",
        "## 🗺️ Зарегистрированные экраны и клавиатуры",
        "",
    ])
    for node_id, node in sorted(bot_map.nodes.items(), key=lambda x: x[0]):
        btns = []
        if node.keyboard:
            btns = [b.text for b in node.keyboard.all_buttons()]
        btn_str = ", ".join(f"`{b}`" for b in btns) if btns else "*(без кнопок)*"
        lines.append(f"- **`{node_id}`** ({node.title or 'screen'}): кнопки -> {btn_str}")

    return "\n".join(lines)


def run_analysis(
    target_path: Path,
    output_html: Path | None = None,
    output_json: Path | None = None,
    strict: bool = False,
    bot_token: str | None = None,
    parser: AstParser | None = None,
    output_md: Path | None = None,
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

    if parser is None:
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
            from tg_flowmap.sast.emoji import fetch_custom_emojis
            emojis = fetch_custom_emojis(token, parser.custom_emoji_ids)
            bot_map.custom_emojis = emojis
        else:
            from tg_flowmap.sast.emoji import get_default_cache_dir, load_cached_emoji
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
    print("  🧭 TG-FLOWMAP — Telegram Bot Analyzer (SAST)")
    print("=" * 60)
    print(f"Цель:              {target_path.resolve()}")
    print(f"Всего экранов:     {stats.get('total_nodes', 0)}")
    print(f"Всего связей:      {stats.get('total_edges', 0)}")
    print(f"Клавиатур найдено: {len(parser.keyboards)}")
    print(f"Дубликатов экранов:{stats.get('duplicate_screens', 0)}")
    if parser.custom_emoji_ids:
        print(f"Премиум эмодзи:    {len(parser.custom_emoji_ids)} (в кэше: {len(bot_map.custom_emojis)})")
    print(f"Тупиков (Dead-end):{stats.get('dead_ends', 0)}")
    print(f"Ошибок эмодзи:     {stats.get('broken_emojis', 0)}")
    print(f"Без кнопки Назад:  {stats.get('missing_backs', 0)}")
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

    if output_md:
        output_md.parent.mkdir(parents=True, exist_ok=True)
        output_md.write_text(build_sast_markdown_report(bot_map, target_path), encoding="utf-8")
        print(f"📄 Отчёт сохранён: {output_md.resolve()}")

    if output_html:
        output_html.parent.mkdir(parents=True, exist_ok=True)
        visualizer = HtmlVisualizer(bot_map)
        visualizer.render(output_html)
        print(f"📊 Интерактивная карта сохранена: {output_html.resolve()}")

    if output_json:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(bot_map.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"📦 JSON-структура сохранена: {output_json.resolve()}")

    dead_ends = stats.get("dead_ends", 0)
    broken_emojis = stats.get("broken_emojis", 0)
    has_errors = any(i.severity == "error" for i in bot_map.issues) or (dead_ends > 0) or (broken_emojis > 0)
    if strict and has_errors:
        print("\n[STRICT MODE] Обнаружены критические ошибки! Выход с кодом 1.")
        return 1

    return 0


def run_dast_scan(
    bot_target: str,
    output_dir: Path | None = None,
    config_path: Path | None = None,
) -> int:
    try:
        import asyncio
        from tg_flowmap.dast.config import Config
        from tg_flowmap.dast.reports import generate_reports
        from tg_flowmap.dast.scheduler import run_crawlers
        from tg_flowmap.dast.state import State
    except ImportError as e:
        print(
            f"[ERROR] Для DAST режима требуется Telethon.\n"
            f"Установите зависимость: pip install \"tg-flowmap[dast]\"\n({e})",
            file=sys.stderr,
        )
        return 1

    bot_name = bot_target if bot_target.startswith("@") else f"@{bot_target}"
    cfg_file = config_path or Path("config.json")
    if not cfg_file.exists():
        print(
            f"[ERROR] Не найден конфигурационный файл: {cfg_file}\n"
            f"Создайте config.json с параметрами api_id и api_hash (см. config.example.json)",
            file=sys.stderr,
        )
        return 1

    cfg = Config.load(cfg_file)
    if output_dir:
        cfg.output_dir = output_dir

    print("=" * 60)
    print("  🤖 TG-FLOWMAP — Telegram Bot Crawler (DAST)")
    print("=" * 60)
    print(f"Целевой бот:   {bot_name}")
    print(f"Директория:    {cfg.output_dir.resolve()}")
    print("-" * 60)

    state = State(cfg.state_db_path)
    try:
        statuses = asyncio.run(run_crawlers(cfg, state=state, bots=[bot_name]))
        bot_status = statuses.get(bot_name, "ok")
        if "error" in bot_status.lower():
            print(f"[WARN] Обход завершился со статусом: {bot_status}")
    except Exception as e:
        print(f"[ERROR] Ошибка выполнения обхода: {e}", file=sys.stderr)
        return 1

    reports = generate_reports(cfg, state, bot_name)

    print(f"✅ Обход завершён!")
    print(f"📄 Отчёт сохранён: {reports.get('report')}")
    print(f"📊 Интерактивная карта: {reports.get('map_html')}")
    return 0


def run_compare(
    target_a: str,
    target_b: str,
    output_dir: Path | None = None,
) -> int:
    out_dir = output_dir or Path("output")
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  ⚔️ TG-FLOWMAP — Telegram Bot Benchmark & Comparison")
    print("=" * 60)
    print(f"Бот A (Исходный):   {target_a}")
    print(f"Бот B (Конкурент):  {target_b}")
    print("-" * 60)

    data_a: dict = {}
    data_b: dict = {}

    # Target A
    path_a = Path(target_a)
    if path_a.exists():
        parser = AstParser()
        if path_a.is_file():
            parser.parse_file(path_a)
        else:
            parser.parse_dir(path_a)
        analyzer = GraphAnalyzer(parser.nodes, parser.keyboards)
        bot_map_a = analyzer.build_map()
        data_a = {
            "metrics": BotComparator.extract_metrics_from_bot_map(bot_map_a),
            "screens": [
                {
                    "screen_id": nid,
                    "title": n.title,
                    "buttons": [b.text for b in n.keyboard.all_buttons()] if n.keyboard else [],
                }
                for nid, n in bot_map_a.nodes.items()
            ],
        }
    else:
        data_a = {"metrics": {"screens_count": 0, "buttons_count": 0, "dead_ends": 0, "missing_back": 0}}

    # Target B
    path_b = Path(target_b)
    if path_b.exists():
        parser = AstParser()
        if path_b.is_file():
            parser.parse_file(path_b)
        else:
            parser.parse_dir(path_b)
        analyzer = GraphAnalyzer(parser.nodes, parser.keyboards)
        bot_map_b = analyzer.build_map()
        data_b = {
            "metrics": BotComparator.extract_metrics_from_bot_map(bot_map_b),
            "screens": [
                {
                    "screen_id": nid,
                    "title": n.title,
                    "buttons": [b.text for b in n.keyboard.all_buttons()] if n.keyboard else [],
                }
                for nid, n in bot_map_b.nodes.items()
            ],
        }
    else:
        # Check DAST cached reports or summary
        b_clean = target_b.lstrip("@")
        json_cand = out_dir / b_clean / "graph.json"
        if json_cand.exists():
            try:
                graph_data = json.loads(json_cand.read_text(encoding="utf-8"))
                screens = graph_data.get("screens", [])
                data_b = {
                    "metrics": {
                        "screens_count": len(screens),
                        "buttons_count": len(graph_data.get("routes", [])),
                        "dead_ends": 0,
                        "missing_back": 0,
                    },
                    "screens": [{"screen_id": s.get("screen_id"), "title": s.get("screen_id"), "buttons": []} for s in screens],
                }
            except Exception:
                data_b = {"metrics": {"screens_count": 1, "buttons_count": 1, "dead_ends": 0, "missing_back": 0}}
        else:
            print(f"[WARN] Данные для бота '{target_b}' не найдены в локальном кэше.")
            print(f"       Чтобы провести реальный обход, запустите: tg-flowmap dast {target_b}")
            data_b = {
                "metrics": {"screens_count": 0, "buttons_count": 0, "dead_ends": 0, "missing_back": 0},
                "screens": [],
            }

    comparator = BotComparator(
        bot_a_name=path_a.name if path_a.exists() else target_a,
        bot_a_data=data_a,
        bot_b_name=path_b.name if path_b.exists() else target_b,
        bot_b_data=data_b,
    )

    exported = comparator.export(out_dir)
    print(f"\n✅ Сравнение успешно завершено!")
    print(f"📊 Отчёт сравнения сохранён: {exported['comparison'].resolve()}")
    print(f"🤖 Промпт для нейросети (ChatGPT / Claude) готов: {exported['llm_prompt'].resolve()}")
    return 0


def main() -> None:
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    # Top-level parser
    parser = argparse.ArgumentParser(
        prog="tg-flowmap",
        description="Unified Telegram Bot Analyzer: Static AST (SAST) + Dynamic Userbot Crawler (DAST) + LLM Benchmarker",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Доступные режимы анализа")

    # SAST command
    sast_parser = subparsers.add_parser("sast", aliases=["code", "scan"], help="Статический анализ кода бота (Zero-Runtime AST)")
    sast_parser.add_argument("target", type=str, help="Путь к файлу бота (.py) или папке проекта")
    sast_parser.add_argument("--strict", action="store_true", help="Возвращать код 1 при критических дефектах (для CI/CD)")
    sast_parser.add_argument("--html", action="store_true", help="Сгенерировать интерактивную HTML-карту")
    sast_parser.add_argument("-t", "--token", type=str, default=None, help="Токен бота для подгрузки оригинальных Premium эмодзи")
    sast_parser.add_argument("-o", "--output-dir", type=str, default="output", help="Директория для отчетов (по умолчанию: output/)")

    # DAST command
    dast_parser = subparsers.add_parser("dast", aliases=["crawl", "bot"], help="Динамический реверс-инжиниринг через Telethon юзербота")
    dast_parser.add_argument("bot", type=str, help="Имя или юзернейм целевого бота (например, @example_bot)")
    dast_parser.add_argument("--config", type=str, default="config.json", help="Путь к config.json Telethon")
    dast_parser.add_argument("-o", "--output-dir", type=str, default="output", help="Директория для отчетов (по умолчанию: output/)")

    # COMPARE command
    compare_parser = subparsers.add_parser("compare", aliases=["diff", "bench"], help="Сравнение двух ботов и генерация промпта для ИИ")
    compare_parser.add_argument("target_a", type=str, help="Бот A (путь к коду или @bot)")
    compare_parser.add_argument("target_b", type=str, help="Бот B (путь к коду или @bot конкурента)")
    compare_parser.add_argument("-o", "--output-dir", type=str, default="output", help="Директория для отчетов (по умолчанию: output/)")

    # Fast-path backward compatibility:
    # If user called `tg-flowmap path/to/bot` directly without subcommand:
    args_list = sys.argv[1:]
    if args_list and args_list[0] not in ("sast", "code", "scan", "dast", "crawl", "bot", "compare", "diff", "bench", "-h", "--help"):
        # Auto-route to sast mode!
        args_list = ["sast"] + args_list

    args = parser.parse_args(args_list)

    if not args.subcommand:
        parser.print_help()
        sys.exit(0)

    if args.subcommand in ("sast", "code", "scan"):
        target = Path(args.target)
        out_dir = Path(getattr(args, "output_dir", "output"))
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = target.stem if target.is_file() else target.name
        out_md = out_dir / f"{stem}_report.md"
        out_json = out_dir / f"{stem}_data.json"
        out_html = out_dir / f"{stem}_map.html" if getattr(args, "html", False) else None

        exit_code = run_analysis(
            target_path=target,
            output_md=out_md,
            output_html=out_html,
            output_json=out_json,
            strict=args.strict,
            bot_token=args.token,
        )
        sys.exit(exit_code)

    elif args.subcommand in ("dast", "crawl", "bot"):
        exit_code = run_dast_scan(
            bot_target=args.bot,
            output_dir=Path(args.output_dir),
            config_path=Path(args.config) if args.config else None,
        )
        sys.exit(exit_code)

    elif args.subcommand in ("compare", "diff", "bench"):
        exit_code = run_compare(
            target_a=args.target_a,
            target_b=args.target_b,
            output_dir=Path(args.output_dir),
        )
        sys.exit(exit_code)


if __name__ == "__main__":
    main()

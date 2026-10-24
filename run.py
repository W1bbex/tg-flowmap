from __future__ import annotations

import os
import sys
import webbrowser
from pathlib import Path

# Add current directory to sys.path so tg_flowmap package is importable
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from tg_flowmap.cli import load_env_token, run_analysis, run_compare, run_dast_scan
from tg_flowmap.sast.parser import AstParser


def clean_input_path(raw: str) -> Path | None:
    """Cleans up raw path input from user (quotes, spaces, drag-and-drop)."""
    text = raw.strip().strip('"').strip("'")
    if not text:
        return None
    p = Path(text).expanduser()
    if p.exists():
        return p.resolve()
    # Check relative to current working directory
    cwd_p = (Path.cwd() / text).resolve()
    if cwd_p.exists():
        return cwd_p
    # Check relative to script dir
    script_p = (SCRIPT_DIR / text).resolve()
    if script_p.exists():
        return script_p
    return None


def open_in_browser(html_path: Path) -> None:
    """Attempts to open generated HTML map in default web browser."""
    if html_path.exists():
        print(f"\n🌐 Открываем интерактивную карту в браузере: {html_path.resolve()}")
        try:
            webbrowser.open(html_path.resolve().as_uri())
        except Exception as e:
            print(f"[!] Не удалось открыть браузер автоматически: {e}")
            print(f"    Вы можете открыть файл вручную: {html_path.resolve()}")


def execute_sast_scan(target_path: Path) -> int:
    """Executes SAST analysis and opens interactive HTML map in browser."""
    bot_name = target_path.stem if target_path.is_file() else target_path.name
    output_dir = SCRIPT_DIR / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    output_html = output_dir / f"{bot_name}_map.html"
    output_md = output_dir / f"{bot_name}_report.md"
    output_json = output_dir / f"{bot_name}_data.json"

    bot_token = load_env_token(target_path)
    parser = AstParser()
    if target_path.is_file():
        parser.parse_file(target_path)
    else:
        parser.parse_dir(target_path)

    if parser.custom_emoji_ids and not bot_token and sys.stdin.isatty():
        print(f"\n✨ В коде обнаружено {len(parser.custom_emoji_ids)} уникальных Telegram Premium эмодзи.")
        raw_tok = input("🔑 Введите токен бота для загрузки стикеров (Enter для пропуска): ").strip()
        if raw_tok:
            bot_token = raw_tok

    print()
    print(f"🚀 Запуск анализа для: {target_path.resolve()}")
    exit_code = run_analysis(
        target_path=target_path,
        output_html=output_html,
        output_md=output_md,
        output_json=output_json,
        bot_token=bot_token,
        parser=parser,
    )

    if exit_code == 0:
        open_in_browser(output_html)

    return exit_code


def handle_sast_action() -> None:
    print()
    print("─" * 64)
    print("  🔍 Анализ своего бота (Zero-Runtime SAST)")
    print("─" * 64)
    print("📁 Перетащите сюда файл бота (.py) или папку проекта")
    print("   (или введите путь к коду, Enter для отмены):")
    raw = input("Path > ").strip()
    if not raw:
        print("Отмена.")
        return

    path = clean_input_path(raw)
    if not path:
        print(f"\n[ERROR] Путь не найден: {raw}")
        print("Убедитесь, что файл или папка существуют.")
        return

    execute_sast_scan(path)


def handle_dast_action() -> None:
    print()
    print("─" * 64)
    print("  🕵️  Динамический обход бота в Telegram (DAST)")
    print("─" * 64)

    cfg_file = SCRIPT_DIR / "config.json"
    if not cfg_file.exists() and not Path("config.json").exists():
        print("⚠️  [Внимание] Не найден файл конфигурации config.json.")
        print()
        print("Для обхода ботов через Telethon необходимы Telegram API ключи:")
        print("  1. Скопируйте config.example.json в config.json")
        print("  2. Укажите api_id и api_hash (с https://my.telegram.org/apps)")
        print()
        cont = input("Попробовать продолжить всё равно? [y/N]: ").strip().lower()
        if cont not in ("y", "yes", "д", "да"):
            return

    bot_username = input("🤖 Введите юзернейм бота (например, @example_bot): ").strip()
    if not bot_username:
        print("Отмена.")
        return

    out_dir = SCRIPT_DIR / "output"
    exit_code = run_dast_scan(
        bot_target=bot_username,
        output_dir=out_dir,
        config_path=cfg_file if cfg_file.exists() else None,
    )
    if exit_code == 0:
        clean_bot = bot_username.lstrip("@")
        map_cand = out_dir / clean_bot / "map.html"
        open_in_browser(map_cand)


def handle_compare_action() -> None:
    print()
    print("─" * 64)
    print("  ⚔️ Сравнение двух ботов и подготовка промпта для нейросети")
    print("─" * 64)
    print("Введите путь к коду (или @юзернейм) для обоих ботов.")
    print()
    bot_a = input("Бот A (Ваш бот): ").strip()
    if not bot_a:
        print("Отмена.")
        return

    bot_b = input("Бот B (Конкурент): ").strip()
    if not bot_b:
        print("Отмена.")
        return

    out_dir = SCRIPT_DIR / "output"
    run_compare(target_a=bot_a, target_b=bot_b, output_dir=out_dir)


def handle_demo_action() -> None:
    demo_file = SCRIPT_DIR / "examples" / "sample_bot.py"
    if not demo_file.exists():
        print(f"[ERROR] Файл демонстрационного бота не найден: {demo_file}")
        return

    print()
    print("─" * 64)
    print("  🎨 Запуск готового демо-примера (Sample Bot)")
    print("─" * 64)
    print("Анализируем пример бота из `examples/sample_bot.py`...")
    execute_sast_scan(demo_file)
    print("\n💡 Демонстрационный бот успешно проанализирован!")
    print("Вы можете посмотреть исходный код демо-бота в: examples/sample_bot.py")


def interactive_menu() -> None:
    while True:
        print()
        print("=" * 64)
        print("  🧭 TG-FLOWMAP — Интерактивный запуск анализатора ботов")
        print("  Static AST (SAST) + Dynamic Crawler (DAST) + AI Benchmark")
        print("=" * 64)
        print()
        print("  [1] 🔍 Анализ своего бота (SAST)")
        print("      Сканировать исходный код без запуска (поиск тупиков, дублей, ошибок)")
        print()
        print("  [2] 🕵️  Обход бота в Telegram (DAST)")
        print("      Реверс-инжиниринг через юзербота Telethon (по @username)")
        print()
        print("  [3] ⚔️  Сравнение двух ботов (AI Benchmark)")
        print("      Сравнить двух ботов и получить готовый промпт для ChatGPT / Claude")
        print()
        print("  [4] 🎨 Запустить готовый демо-пример (Sample Bot)")
        print("      Мгновенно построить и открыть интерактивную HTML-карту в браузере")
        print()
        print("  [0] 🚪 Выход")
        print("=" * 64)

        try:
            choice = input("Выберите действие [4]: ").strip()
        except EOFError:
            break

        if choice in ("", "4"):
            handle_demo_action()
            break
        elif choice == "1":
            handle_sast_action()
            break
        elif choice == "2":
            handle_dast_action()
            break
        elif choice == "3":
            handle_compare_action()
            break
        elif choice in ("0", "q", "exit"):
            print("До свидания!")
            break
        else:
            print(f"[!] Неизвестный вариант: '{choice}'. Введите цифру от 0 до 4.")


def wait_for_exit() -> None:
    if not sys.stdin.isatty():
        return
    print()
    try:
        input("Нажмите Enter для завершения...")
    except Exception:
        pass


def main() -> None:
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    if len(sys.argv) > 1:
        first_arg = sys.argv[1].strip().strip('"').strip("'")
        target_path = clean_input_path(first_arg)

        # If user dragged & dropped a valid file/directory onto run.bat
        if target_path and not first_arg.startswith("-"):
            try:
                execute_sast_scan(target_path)
            except KeyboardInterrupt:
                print("\nПрервано пользователем.")
            finally:
                wait_for_exit()
        else:
            # Delegate to standard CLI argument parser
            from tg_flowmap.cli import main as cli_main
            cli_main()
    else:
        try:
            interactive_menu()
        except KeyboardInterrupt:
            print("\nПрервано пользователем.")
        finally:
            wait_for_exit()


if __name__ == "__main__":
    main()

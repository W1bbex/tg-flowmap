from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

# Add current directory to sys.path so tg_flowmap package is importable
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

# Ensure UTF-8 console output on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from tg_flowmap.cli import load_env_token, run_analysis, run_compare, run_dast_scan
from tg_flowmap.sast.parser import AstParser

# Try importing rich and questionary for modern UI
try:
    from rich.console import Console
    import questionary
    from questionary import Choice, Separator, Style

    HAS_RICH_UI = True
    console = Console(legacy_windows=False)
except ImportError:
    HAS_RICH_UI = False
    console = None

# Minimalist, clean styling for Questionary prompt
CUSTOM_STYLE = Style([
    ("qmark", "fg:#00d7d7 bold"),
    ("question", "bold"),
    ("answer", "fg:#00ff88 bold"),
    ("pointer", "fg:#00d7d7 bold"),
    ("highlighted", "fg:#00d7d7 bold"),
    ("selected", "fg:#00ff88"),
    ("separator", "fg:#555555"),
    ("instruction", "fg:#777777 italic"),
    ("text", ""),
    ("disabled", "fg:#555555 italic"),
]) if HAS_RICH_UI else None


def is_interactive() -> bool:
    """Returns True only if both stdin and stdout are interactive TTYs."""
    return sys.stdin.isatty() and sys.stdout.isatty() and HAS_RICH_UI


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
        if HAS_RICH_UI:
            console.print(f"\n🌐 [bold green]Интерактивная карта открыта в браузере:[/bold green] [cyan]{html_path.resolve()}[/cyan]")
        else:
            print(f"\n🌐 Интерактивная карта: {html_path.resolve()}")
        try:
            webbrowser.open(html_path.resolve().as_uri())
        except Exception as e:
            msg = f"[!] Не удалось открыть браузер автоматически: {e}\n    Откройте файл вручную: {html_path.resolve()}"
            if HAS_RICH_UI:
                console.print(f"[yellow]{msg}[/yellow]")
            else:
                print(msg)


def is_telethon_configured(cfg_path: Path) -> bool:
    """Checks whether config.json exists and has valid api_id and api_hash."""
    if not cfg_path.exists():
        return False
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        api_id = data.get("api_id")
        api_hash = str(data.get("api_hash", "")).strip()
        if isinstance(api_id, int) and api_id > 0 and len(api_hash) >= 10 and api_hash != "YOUR_TELEGRAM_API_HASH":
            return True
    except Exception:
        pass
    return False


def get_telethon_status_summary(cfg_path: Path) -> tuple[str, bool]:
    """Returns a short human-readable status badge and boolean state."""
    if is_telethon_configured(cfg_path):
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            api_id = data.get("api_id")
            return f"[green]● готов[/green] [dim](id: {api_id})[/dim]", True
        except Exception:
            return "[green]● готов[/green]", True
    return "[yellow]○ нужен API ключ[/yellow]", False


def run_telegram_config_wizard(cfg_path: Path) -> bool:
    """Interactive wizard to configure config.json for Telethon."""
    example_path = SCRIPT_DIR / "config.example.json"

    if HAS_RICH_UI:
        console.print("\n[bold cyan]⚙️  Настройка Telegram API для обхода чужих ботов[/bold cyan]")
        console.print("[dim]Ключи api_id и api_hash берутся бесплатно за 1 минуту: [underline]https://my.telegram.org/apps[/underline][/dim]\n")
    else:
        print("\n⚙️  Настройка Telegram API (https://my.telegram.org/apps)")

    if is_interactive():
        action = questionary.select(
            "Как настроить ключи?",
            choices=[
                Choice("⚡ Ввести api_id и api_hash прямо сейчас", value="quick"),
                Choice("📝 Создать config.json и открыть в блокноте", value="template"),
                Choice("⬅️  Назад", value="back"),
            ],
            style=CUSTOM_STYLE,
        ).ask()
    else:
        print("[1] Быстрая настройка (ввести api_id и api_hash)")
        print("[2] Создать config.json из шаблона")
        print("[0] Назад")
        raw_choice = input("Выбор [1]: ").strip()
        action = "quick" if raw_choice in ("", "1") else "template" if raw_choice == "2" else "back"

    if action == "back" or not action:
        return False

    if action == "quick":
        if is_interactive():
            api_id_val = questionary.text(
                "Введите ваш api_id (число):",
                validate=lambda v: (v.strip().isdigit() and int(v.strip()) > 0) or "api_id должен быть числом",
                style=CUSTOM_STYLE,
            ).ask()
            if not api_id_val:
                return False

            api_hash_val = questionary.text(
                "Введите ваш api_hash (32 символа):",
                validate=lambda v: len(v.strip()) >= 10 or "api_hash слишком короткий",
                style=CUSTOM_STYLE,
            ).ask()
            if not api_hash_val:
                return False
        else:
            api_id_val = input("api_id: ").strip()
            api_hash_val = input("api_hash: ").strip()
            if not api_id_val.isdigit() or not api_hash_val:
                print("[ERROR] Некорректные параметры.")
                return False

        config_data = {
            "api_id": int(api_id_val.strip()),
            "api_hash": api_hash_val.strip(),
            "session_name": "market_research",
            "bots": [],
            "language": "ru",
            "delay_min": 2.0,
            "delay_max": 5.0,
            "max_depth": 8,
            "max_actions_per_bot": 300,
        }

        try:
            cfg_path.write_text(json.dumps(config_data, ensure_ascii=False, indent=2), encoding="utf-8")
            if HAS_RICH_UI:
                console.print(f"\n[green]✔ Ключи сохранены в {cfg_path.name} (защищён в .gitignore).[/green]\n")
            else:
                print(f"✔ Конфигурация сохранена в {cfg_path.name}")
            return True
        except Exception as e:
            if HAS_RICH_UI:
                console.print(f"[bold red]❌ Ошибка записи config.json: {e}[/bold red]")
            else:
                print(f"[ERROR] Ошибка записи config.json: {e}")
            return False

    elif action == "template":
        if not cfg_path.exists():
            if example_path.exists():
                shutil.copy(example_path, cfg_path)
            else:
                cfg_path.write_text(
                    json.dumps({
                        "api_id": 0,
                        "api_hash": "YOUR_TELEGRAM_API_HASH",
                        "session_name": "market_research",
                        "bots": [],
                        "delay_min": 2.0,
                        "delay_max": 5.0,
                    }, indent=2),
                    encoding="utf-8"
                )

        if HAS_RICH_UI:
            console.print(f"\n[green]✔ Создан шаблон {cfg_path.name}. Открываем в редакторе...[/green]")
        else:
            print(f"✔ Создан шаблон {cfg_path.name}. Открываем...")

        try:
            if sys.platform == "win32":
                os.startfile(cfg_file)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(cfg_path)])
            else:
                subprocess.Popen(["xdg-open", str(cfg_path)])
        except Exception as e:
            print(f"[!] Откройте вручную: {cfg_path.resolve()}")

        if is_interactive():
            questionary.press_any_key_to_continue("Отредактируйте файл, сохраните его и нажмите любую клавишу...").ask()
        else:
            input("Отредактируйте файл и нажмите Enter...")

        return is_telethon_configured(cfg_path)

    return False


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
        msg = f"✨ В коде обнаружено {len(parser.custom_emoji_ids)} уникальных Telegram Premium эмодзи."
        if HAS_RICH_UI:
            console.print(f"\n[bold magenta]{msg}[/bold magenta]")
        else:
            print(f"\n{msg}")

        if is_interactive():
            raw_tok = questionary.password(
                "🔑 Токен бота для стикеров (Enter для пропуска):",
                style=CUSTOM_STYLE,
            ).ask()
        else:
            raw_tok = input("🔑 Токен бота для стикеров (Enter для пропуска): ").strip()

        if raw_tok:
            bot_token = raw_tok.strip()

    if HAS_RICH_UI:
        console.print(f"\n[bold cyan]🚀 Анализ своего бота:[/bold cyan] [underline]{target_path.resolve()}[/underline]")
    else:
        print(f"\n🚀 Запуск анализа для: {target_path.resolve()}")

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
    if HAS_RICH_UI:
        console.print("\n[bold cyan]🔍 Анализ своего бота (Zero-Runtime SAST)[/bold cyan]")
        console.print("[dim]Поиск тупиков, битых коллбэков, дубликатов и экранов без «Назад» без запуска кода[/dim]\n")
    else:
        print("\n─" * 60)
        print("  🔍 Анализ своего бота (SAST)")
        print("─" * 60)

    if is_interactive():
        raw = questionary.text(
            "📁 Перетащите файл (.py) или папку бота (Enter для отмены):",
            style=CUSTOM_STYLE,
        ).ask()
    else:
        raw = input("📁 Путь к файлу/папке бота (или Enter для отмены): ").strip()

    if not raw or not raw.strip():
        if HAS_RICH_UI:
            console.print("[yellow]Отмена.[/yellow]")
        return

    path = clean_input_path(raw)
    if not path:
        err_msg = f"❌ Путь не найден: {raw}"
        if HAS_RICH_UI:
            console.print(f"[bold red]{err_msg}[/bold red]")
        else:
            print(f"[ERROR] {err_msg}")
        return

    execute_sast_scan(path)


def handle_dast_action() -> None:
    cfg_file = SCRIPT_DIR / "config.json"

    if HAS_RICH_UI:
        console.print("\n[bold green]🕵️  Обход чужого бота (Telethon DAST)[/bold green]")
        console.print("[dim]Исследование воронки конкурента юзерботом в реальном времени[/dim]\n")
    else:
        print("\n─" * 60)
        print("  🕵️  Обход чужого бота (DAST)")
        print("─" * 60)

    # If Telethon is not configured, run the setup wizard immediately
    if not is_telethon_configured(cfg_file):
        configured = run_telegram_config_wizard(cfg_file)
        if not configured:
            if HAS_RICH_UI:
                console.print("[yellow]Обход отменён: Telethon не настроен.[/yellow]")
            return

    # Telethon is configured! Ask for the target bot
    if is_interactive():
        bot_username = questionary.text(
            "🤖 Юзернейм чужого бота (например, @example_bot):",
            validate=lambda v: len(v.strip().lstrip("@")) > 0 or "Юзернейм бота не может быть пустым",
            style=CUSTOM_STYLE,
        ).ask()
    else:
        bot_username = input("🤖 Юзернейм чужого бота: ").strip()

    if not bot_username or not bot_username.strip():
        if HAS_RICH_UI:
            console.print("[yellow]Отмена.[/yellow]")
        return

    out_dir = SCRIPT_DIR / "output"
    if HAS_RICH_UI:
        console.print(f"\n[bold cyan]🚀 Обход чужого бота {bot_username}...[/bold cyan]")
    else:
        print(f"\n🚀 Запуск обхода для: {bot_username}")

    exit_code = run_dast_scan(
        bot_target=bot_username,
        output_dir=out_dir,
        config_path=cfg_file,
    )
    if exit_code == 0:
        clean_bot = bot_username.lstrip("@")
        map_cand = out_dir / clean_bot / "map.html"
        open_in_browser(map_cand)


def handle_compare_action() -> None:
    if HAS_RICH_UI:
        console.print("\n[bold magenta]⚔️  Сравнение своего и чужого бота (AI Benchmark)[/bold magenta]")
        console.print("[dim]Сопоставляет воронки и готовит промпт для нейросети (ChatGPT / Claude)[/dim]\n")
    else:
        print("\n─" * 60)
        print("  ⚔️ Сравнение своего и чужого бота")
        print("─" * 60)

    if is_interactive():
        bot_a = questionary.text(
            "1️⃣  Ваш бот (путь к коду или @bot):",
            validate=lambda v: bool(v.strip()) or "Укажите первого бота",
            style=CUSTOM_STYLE,
        ).ask()
        if not bot_a:
            return

        bot_b = questionary.text(
            "2️⃣  Чужой бот (путь к коду или @bot):",
            validate=lambda v: bool(v.strip()) or "Укажите второго бота",
            style=CUSTOM_STYLE,
        ).ask()
        if not bot_b:
            return
    else:
        bot_a = input("Ваш бот (путь или @bot): ").strip()
        bot_b = input("Чужой бот (путь или @bot): ").strip()
        if not bot_a or not bot_b:
            print("Отмена.")
            return

    out_dir = SCRIPT_DIR / "output"
    run_compare(target_a=bot_a.strip(), target_b=bot_b.strip(), output_dir=out_dir)


def handle_demo_action() -> None:
    demo_file = SCRIPT_DIR / "examples" / "sample_bot.py"
    if not demo_file.exists():
        err_msg = f"[ERROR] Демо-бот не найден: {demo_file}"
        if HAS_RICH_UI:
            console.print(f"[bold red]{err_msg}[/bold red]")
        else:
            print(err_msg)
        return

    if HAS_RICH_UI:
        console.print("\n[bold yellow]🎨 Демо-тур по готовому примеру (examples/sample_bot.py)[/bold yellow]")
    else:
        print("\n🎨 Запуск демо-примера")

    execute_sast_scan(demo_file)

    if HAS_RICH_UI:
        console.print("\n[bold green]💡 Демонстрационная карта построена![/bold green] [dim]Исходник: examples/sample_bot.py[/dim]")
    else:
        print("\n💡 Демонстрационная карта построена!")


def handle_config_action() -> None:
    cfg_file = SCRIPT_DIR / "config.json"
    configured = is_telethon_configured(cfg_file)

    if HAS_RICH_UI:
        badge, _ = get_telethon_status_summary(cfg_file)
        console.print(f"\n[bold cyan]⚙️  Настройки Telegram API[/bold cyan] [dim]•[/dim] {badge}")
        console.print(f"[dim]Файл: {cfg_file.resolve()}[/dim]\n")

    if is_interactive():
        choices = [
            Choice("⚡ Настроить ключи (api_id и api_hash)", value="wizard"),
            Choice("📝 Открыть config.json в блокноте", value="open"),
        ]
        if configured:
            choices.append(Choice("🗑️  Сбросить настройки", value="reset"))
        choices.append(Separator())
        choices.append(Choice("⬅️  Назад", value="back"))

        action = questionary.select(
            "Действие:",
            choices=choices,
            style=CUSTOM_STYLE,
        ).ask()
    else:
        print("[1] Настроить ключи")
        print("[2] Открыть в блокноте")
        print("[0] Назад")
        raw = input("Выбор [1]: ").strip()
        action = "wizard" if raw in ("", "1") else "open" if raw == "2" else "back"

    if action == "wizard":
        run_telegram_config_wizard(cfg_file)
    elif action == "open":
        if not cfg_file.exists():
            shutil.copy(SCRIPT_DIR / "config.example.json", cfg_file)
        if sys.platform == "win32":
            os.startfile(cfg_file)
        else:
            subprocess.Popen(["xdg-open", str(cfg_file)])
    elif action == "reset":
        if cfg_file.exists():
            cfg_file.unlink()
            if HAS_RICH_UI:
                console.print("[green]✔ Настройки сброшены.[/green]")
            else:
                print("✔ Настройки сброшены.")


def interactive_menu() -> None:
    cfg_file = SCRIPT_DIR / "config.json"

    while True:
        telethon_badge, _ = get_telethon_status_summary(cfg_file)

        if HAS_RICH_UI:
            console.print()
            console.print(f"[bold cyan]🧭 TG-FLOWMAP v1.0.0[/bold cyan]  [dim]•[/dim]  Telethon: {telethon_badge}")
            console.print("[dim]Аудит своего бота, обход конкурента и AI-бенчмаркинг воронок[/dim]\n")
        else:
            print("\n" + "=" * 60)
            print("  🧭 TG-FLOWMAP — Интерактивный запуск анализатора ботов")
            print("=" * 60)

        if is_interactive():
            try:
                choice = questionary.select(
                    "Выберите действие:",
                    choices=[
                        Choice("🔍 1. Анализ своего бота          (исходный код .py)", value="sast"),
                        Choice("🕵️  2. Обход чужого бота          (Telegram @username)", value="dast"),
                        Choice("⚔️  3. Сравнить своего и чужого   (AI UX Benchmark)", value="compare"),
                        Choice("🎨 4. Демо-тур                   (пример готовой карты)", value="demo"),
                        Choice("⚙️  5. Настройки API              (config.json)", value="config"),
                        Separator(),
                        Choice("🚪 0. Выход", value="exit"),
                    ],
                    style=CUSTOM_STYLE,
                ).ask()
            except (KeyboardInterrupt, EOFError):
                break
        else:
            # Fallback for piped or non-interactive environments
            print("  [1] 🔍 Анализ своего бота (.py)")
            print("  [2] 🕵️  Обход чужого бота (@username)")
            print("  [3] ⚔️  Сравнить своего и чужого (AI Benchmark)")
            print("  [4] 🎨 Демо-тур (Sample Bot)")
            print("  [5] ⚙️  Настройки API (config.json)")
            print("  [0] 🚪 Выход")
            try:
                raw_c = input("Выбор [4]: ").strip()
            except (EOFError, KeyboardInterrupt):
                break

            mapping = {
                "": "demo", "4": "demo",
                "1": "sast",
                "2": "dast",
                "3": "compare",
                "5": "config",
                "0": "exit", "q": "exit", "exit": "exit",
            }
            choice = mapping.get(raw_c, "demo")

        if not choice or choice == "exit":
            if HAS_RICH_UI:
                console.print("[dim]До свидания![/dim]")
            else:
                print("До свидания!")
            break

        if choice == "sast":
            handle_sast_action()
            break
        elif choice == "dast":
            handle_dast_action()
            break
        elif choice == "compare":
            handle_compare_action()
            break
        elif choice == "demo":
            handle_demo_action()
            break
        elif choice == "config":
            handle_config_action()


def wait_for_exit() -> None:
    if not sys.stdin.isatty():
        return
    try:
        input("\nНажмите Enter для завершения...")
    except (KeyboardInterrupt, EOFError, Exception):
        pass


def main() -> None:
    if len(sys.argv) > 1:
        first_arg = sys.argv[1].strip().strip('"').strip("'")
        target_path = clean_input_path(first_arg)

        # If user dragged & dropped a valid file/directory onto run.bat
        if target_path and not first_arg.startswith("-"):
            try:
                execute_sast_scan(target_path)
            except (KeyboardInterrupt, EOFError):
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
        except (KeyboardInterrupt, EOFError):
            print("\nПрервано пользователем.")
        finally:
            wait_for_exit()


if __name__ == "__main__":
    main()

from __future__ import annotations

import os
import sys
import webbrowser
from pathlib import Path

# Add current directory to sys.path so tg_flowmap package is importable
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from tg_flowmap.cli import run_analysis


def get_path_mtime(p: Path) -> float:
    """Returns max modification time of directory or its entry points."""
    try:
        mtime = os.path.getmtime(p)
        for f in ("bot.py", "main.py", "app.py"):
            pf = p / f
            if pf.exists():
                mtime = max(mtime, os.path.getmtime(pf))
        return mtime
    except Exception:
        return 0.0


def is_telegram_bot_dir(p: Path) -> bool:
    """Checks if directory contains Telegram bot code."""
    if not p.is_dir():
        return False
    if (p / "bot.py").exists():
        return True
    for f in ("main.py", "app.py"):
        pf = p / f
        if pf.exists():
            try:
                head = pf.read_text(encoding="utf-8", errors="ignore")[:3000]
                if any(k in head for k in ("aiogram", "telebot", "telegram", "TeleBot", "Dispatcher", "Bot(")):
                    return True
            except Exception:
                pass
    return False


def discover_candidate_bots() -> list[Path]:
    """Dynamically looks for Telegram bots in nearby project directories."""
    candidates: list[Path] = []
    
    workspace_candidates = [
        SCRIPT_DIR.parent.parent,
        SCRIPT_DIR.parent,
    ]
    
    for ws in workspace_candidates:
        if not ws.exists():
            continue

        try:
            for item in ws.iterdir():
                if not item.is_dir() or item.name.startswith((".", "_")) or item == SCRIPT_DIR:
                    continue
                if is_telegram_bot_dir(item) and item not in candidates:
                    candidates.append(item)
                if "tutorial" not in item.name.lower() and "sample" not in item.name.lower():
                    for sub in item.iterdir():
                        if sub.is_dir() and not sub.name.startswith((".", "_", "venv")):
                            if is_telegram_bot_dir(sub) and sub not in candidates:
                                candidates.append(sub)
        except Exception:
            pass

    candidates.sort(key=get_path_mtime, reverse=True)
    return candidates[:10]


def resolve_user_input_path(raw_text: str, candidates: list[Path]) -> Path | None:
    """Smartly resolves user input to an existing path (absolute, relative, drag&drop, or fuzzy name)."""
    clean = raw_text.strip().strip('"').strip("'")
    if not clean:
        return None

    # 1. Exact existing path
    p = Path(clean)
    if p.exists():
        return p

    # 2. Check relative to parent workspace roots (e.g. C:\Projects\<clean>)
    workspace_roots = [
        SCRIPT_DIR.parent.parent,
        SCRIPT_DIR.parent,
        Path.cwd(),
    ]
    for ws in workspace_roots:
        cand = ws / clean
        if cand.exists():
            return cand

    # 3. Fuzzy substring matching across known candidates
    clean_low = clean.lower().replace("/", "\\")
    matches = [
        c for c in candidates 
        if clean_low in str(c).lower() or clean_low in c.name.lower()
    ]
    if len(matches) == 1:
        print(f"✔ Автоматически определён проект: {matches[0]}")
        return matches[0]
    elif len(matches) > 1:
        print(f"\n💡 Найдено несколько совпадений для '{clean}':")
        for idx, m in enumerate(matches, 1):
            print(f"  [{idx}] {m}")
        sub_c = input(f"Выберите вариант [1]: ").strip()
        if not sub_c or sub_c == "1":
            return matches[0]
        if sub_c.isdigit() and 1 <= int(sub_c) <= len(matches):
            return matches[int(sub_c) - 1]

    return None


def interactive_mode(initial_target: Path | None = None) -> None:
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    print("=" * 64)
    print("  🧭 TG-FLOWMAP — Интерактивный запуск визуализатора ботов")
    print("=" * 64)
    print()

    target_path = initial_target
    candidates = discover_candidate_bots()

    if not target_path:
        if candidates:
            print("💡 Обнаруженные проекты Telegram-ботов по соседству:")
            for idx, cand in enumerate(candidates, 1):
                print(f"  [{idx}] {cand.resolve()}")
            print("  [0] Указать другой путь (ввести вручную или перетащить папку)")
            print()

            raw_choice = input("Выберите вариант [1] или вставьте путь: ").strip()
            clean_choice = raw_choice.strip().strip('"').strip("'")

            if not clean_choice:
                # Default Enter -> [1]
                target_path = candidates[0]
            elif clean_choice.isdigit():
                c_idx = int(clean_choice)
                if 1 <= c_idx <= len(candidates):
                    target_path = candidates[c_idx - 1]
                elif c_idx == 0:
                    target_path = None
                else:
                    print(f"[WARN] Вариант [{c_idx}] не в списке.")
            else:
                # User entered/pasted a path or name directly!
                target_path = resolve_user_input_path(clean_choice, candidates)
                if not target_path:
                    print(f"[WARN] Путь '{clean_choice}' не найден.")

        # Fallback loop if target_path still not selected or invalid
        while not target_path:
            print()
            raw_input = input("📁 Введите путь к папке/файлу бота (или перетащите сюда): ").strip()
            clean_input = raw_input.strip().strip('"').strip("'")
            if not clean_input:
                print("[ERROR] Путь не указан!")
                continue
            resolved = resolve_user_input_path(clean_input, candidates)
            if resolved:
                target_path = resolved
                break
            print(f"[ERROR] Указанный путь не существует: {clean_input}")

    bot_name = target_path.name
    output_dir = SCRIPT_DIR / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_html = output_dir / f"{bot_name}_flowmap.html"

    # Check for custom emoji IDs and bot token
    from tg_flowmap.cli import load_env_token
    from tg_flowmap.parser import AstParser

    bot_token = load_env_token(target_path)
    parser_probe = AstParser()
    if target_path.is_file():
        parser_probe.parse_file(target_path)
    else:
        parser_probe.parse_dir(target_path)

    if parser_probe.custom_emoji_ids and not bot_token:
        print()
        print(f"✨ В боте обнаружено {len(parser_probe.custom_emoji_ids)} уникальных Telegram Premium эмодзи!")
        raw_tok = input("🔑 Введите токен бота для загрузки стикеров (Enter для пропуска): ").strip()
        if raw_tok:
            bot_token = raw_tok
            save_ans = input("💾 Сохранить токен в .env для последующих анализов? [Y/n]: ").strip().lower()
            if save_ans in ("", "y", "yes", "д", "да"):
                env_file = SCRIPT_DIR / ".env"
                try:
                    env_text = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
                    if "TELEGRAM_BOT_TOKEN=" not in env_text and "BOT_TOKEN=" not in env_text:
                        with env_file.open("a", encoding="utf-8") as f:
                            if env_text and not env_text.endswith("\n"):
                                f.write("\n")
                            f.write(f"TELEGRAM_BOT_TOKEN={bot_token}\n")
                        print("✔ Токен сохранён в .env (защищён в .gitignore)")
                except Exception as e:
                    print(f"[WARN] Не удалось сохранить в .env: {e}")

    print()
    print(f"🚀 Запуск анализа для: {target_path.resolve()}")
    exit_code = run_analysis(target_path, output_html=output_html, bot_token=bot_token, parser=parser_probe)

    if exit_code == 0 or output_html.exists():
        print()
        print(f"🌐 Открываем интерактивную карту в браузере: {output_html.resolve()}")
        try:
            webbrowser.open(output_html.resolve().as_uri())
        except Exception as e:
            print(f"Не удалось открыть браузер автоматически: {e}")
            print(f"Вы можете открыть файл вручную: {output_html.resolve()}")


def wait_for_exit(timeout_seconds: int = 60) -> None:
    if not sys.stdin.isatty():
        return
    print()
    if sys.platform == "win32":
        try:
            import msvcrt
            import time
            print(f"Нажмите любую клавишу для выхода (окно закроется автоматически через {timeout_seconds} сек)...")
            start = time.time()
            while time.time() - start < timeout_seconds:
                if msvcrt.kbhit():
                    msvcrt.getch()
                    return
                time.sleep(0.2)
            return
        except Exception:
            pass
    try:
        input("Нажмите Enter для завершения...")
    except Exception:
        pass


def main() -> None:
    if len(sys.argv) > 1:
        first_arg = sys.argv[1].strip().strip('"').strip("'")
        # Check if launched via drag & drop or path parameter directly
        if not first_arg.startswith("-") and Path(first_arg).exists():
            try:
                interactive_mode(initial_target=Path(first_arg))
            except KeyboardInterrupt:
                print("\nПрервано пользователем.")
            finally:
                wait_for_exit(60)
        else:
            from tg_flowmap.cli import main as cli_main
            cli_main()
    else:
        try:
            interactive_mode()
        except KeyboardInterrupt:
            print("\nПрервано пользователем.")
        finally:
            wait_for_exit(60)


if __name__ == "__main__":
    main()

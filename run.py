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


def discover_candidate_bots() -> list[Path]:
    """Dynamically looks for Telegram bots in nearby project directories."""
    candidates: list[Path] = []
    
    # Check parent workspace roots dynamically (e.g., C:\Projects)
    # SCRIPT_DIR is .../tg-flowmap, parent is .github, parent.parent is Projects
    workspace_candidates = [
        SCRIPT_DIR.parent.parent,
        SCRIPT_DIR.parent,
    ]
    
    for ws in workspace_candidates:
        if not ws.exists():
            continue
        # Check pc-control/vds_bot
        vds_bot = ws / "pc-control" / "vds_bot"
        if vds_bot.exists() and vds_bot not in candidates:
            candidates.append(vds_bot)
            
        # Scan immediate subfolders in workspace for bot.py or handlers
        try:
            for item in ws.iterdir():
                if item.is_dir() and not item.name.startswith((".", "_")) and item != SCRIPT_DIR:
                    if (item / "bot.py").exists() or (item / "main.py").exists():
                        if item not in candidates:
                            candidates.append(item)
                    # Skip heavy tutorial/samples archives from filling the candidates list
                    if "tutorial" not in item.name.lower() and "sample" not in item.name.lower():
                        for sub in item.iterdir():
                            if sub.is_dir() and (sub / "bot.py").exists() and sub not in candidates:
                                candidates.append(sub)
        except Exception:
            pass

    return candidates[:6]


def interactive_mode() -> None:
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

    candidates = discover_candidate_bots()
    target_path: Path | None = None

    if candidates:
        print("💡 Обнаруженные проекты Telegram-ботов по соседству:")
        for idx, cand in enumerate(candidates, 1):
            print(f"  [{idx}] {cand.resolve()}")
        print("  [0] Указать другой путь (ввести вручную или перетащить папку)")
        print()

        choice = input("Выберите вариант [1]: ").strip()
        if not choice:
            choice = "1"

        if choice.isdigit():
            c_idx = int(choice)
            if 1 <= c_idx <= len(candidates):
                target_path = candidates[c_idx - 1]

    if not target_path:
        print()
        raw_input = input("📁 Введите путь к папке/файлу бота (или перетащите сюда): ").strip()
        clean_path = raw_input.strip().strip('"').strip("'")
        if not clean_path:
            print("[ERROR] Путь не указан!")
            return
        target_path = Path(clean_path)

    if not target_path.exists():
        print(f"\n[ERROR] Указанный путь не существует: {target_path}")
        return

    bot_name = target_path.name
    output_dir = SCRIPT_DIR / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_html = output_dir / f"{bot_name}_flowmap.html"

    print()
    print(f"🚀 Запуск анализа для: {target_path.resolve()}")
    exit_code = run_analysis(target_path, output_html=output_html)

    if exit_code == 0 or output_html.exists():
        print()
        print(f"🌐 Открываем интерактивную карту в браузере: {output_html.resolve()}")
        try:
            webbrowser.open(output_html.resolve().as_uri())
        except Exception as e:
            print(f"Не удалось открыть браузер автоматически: {e}")
            print(f"Вы можете открыть файл вручную: {output_html.resolve()}")


def main() -> None:
    if len(sys.argv) > 1:
        from tg_flowmap.cli import main as cli_main
        cli_main()
    else:
        try:
            interactive_mode()
        except KeyboardInterrupt:
            print("\nПрервано пользователем.")
        finally:
            if sys.stdin.isatty():
                print()
                input("Нажмите Enter для завершения...")


if __name__ == "__main__":
    main()

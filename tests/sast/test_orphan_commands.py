"""Регрессионные тесты задачи #89 (Orphan Command Linting):
Детект незарегистрированных в set_my_commands slash-команд и команд меню без обработчиков.
"""

from pathlib import Path
import pytest

from tg_flowmap.sast.parser import AstParser
from tg_flowmap.sast.analyzer import GraphAnalyzer


def test_orphan_command_detected_when_missing_from_set_my_commands(tmp_path: Path):
    """Команда /secret_admin есть в хэндлерах, но отсутствует в set_my_commands -> Issue warning."""
    code = """
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import BotCommand

router = Router()

@router.message(Command("start"))
async def cmd_start(msg):
    await msg.answer("Start")

@router.message(Command("secret_admin"))
async def cmd_admin(msg):
    await msg.answer("Admin")

async def setup(bot):
    await bot.set_my_commands([
        BotCommand(command="start", description="Запуск бота"),
    ])
"""
    test_file = tmp_path / "bot_orphan.py"
    test_file.write_text(code, encoding="utf-8")

    parser = AstParser()
    parser.parse_file(test_file)

    assert parser.has_set_my_commands is True
    assert "start" in parser.registered_menu_commands

    analyzer = GraphAnalyzer(
        parser.nodes,
        parser.keyboards,
        registered_commands=parser.registered_menu_commands,
        has_set_my_commands=parser.has_set_my_commands,
    )
    bot_map = analyzer.build_map()

    orphan_issues = [i for i in bot_map.issues if i.issue_type == "orphan_command"]
    assert len(orphan_issues) == 1
    issue = orphan_issues[0]
    assert issue.severity == "warning"
    assert "/secret_admin" in issue.message
    assert "cmd:/secret_admin" in issue.node_id


def test_ghost_menu_command_without_handler_detected(tmp_path: Path):
    """Команда /ghost зарегистрирована в set_my_commands, но обработчика нет -> Issue error."""
    code = """
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import BotCommand

router = Router()

@router.message(Command("start"))
async def cmd_start(msg):
    await msg.answer("Start")

async def setup(bot):
    await bot.set_my_commands([
        BotCommand(command="start", description="Запуск бота"),
        BotCommand(command="ghost", description="Мертвая ссылка в меню"),
    ])
"""
    test_file = tmp_path / "bot_ghost.py"
    test_file.write_text(code, encoding="utf-8")

    parser = AstParser()
    parser.parse_file(test_file)

    analyzer = GraphAnalyzer(
        parser.nodes,
        parser.keyboards,
        registered_commands=parser.registered_menu_commands,
        has_set_my_commands=parser.has_set_my_commands,
    )
    bot_map = analyzer.build_map()

    orphan_issues = [i for i in bot_map.issues if i.issue_type == "orphan_command"]
    assert len(orphan_issues) == 1
    issue = orphan_issues[0]
    assert issue.severity == "error"
    assert "/ghost" in issue.message


def test_set_my_commands_with_variable_and_dicts(tmp_path: Path):
    """Корректный парсинг set_my_commands при передаче словарей или кортежей."""
    code = """
import telebot

bot = telebot.TeleBot("TOKEN")

@bot.message_handler(commands=['start', 'help'])
def start_help(message):
    bot.send_message(message.chat.id, "Hi")

COMMANDS = [
    {"command": "start", "description": "Start"},
    {"command": "help", "description": "Help"},
]
bot.set_my_commands(COMMANDS)
"""
    test_file = tmp_path / "bot_telebot.py"
    test_file.write_text(code, encoding="utf-8")

    parser = AstParser()
    parser.parse_file(test_file)

    assert parser.has_set_my_commands is True
    assert "start" in parser.registered_menu_commands
    assert "help" in parser.registered_menu_commands

    analyzer = GraphAnalyzer(
        parser.nodes,
        parser.keyboards,
        registered_commands=parser.registered_menu_commands,
        has_set_my_commands=parser.has_set_my_commands,
    )
    bot_map = analyzer.build_map()

    orphan_issues = [i for i in bot_map.issues if i.issue_type == "orphan_command"]
    assert len(orphan_issues) == 0


def test_no_false_positives_when_set_my_commands_absent(tmp_path: Path):
    """Если set_my_commands не вызывается, дефолтные тесты не ломаются."""
    code = """
from aiogram import Router
from aiogram.filters import Command

router = Router()

@router.message(Command("start"))
async def cmd_start(msg):
    await msg.answer("Start")
"""
    test_file = tmp_path / "bot_simple.py"
    test_file.write_text(code, encoding="utf-8")

    parser = AstParser()
    parser.parse_file(test_file)

    assert parser.has_set_my_commands is False

    analyzer = GraphAnalyzer(
        parser.nodes,
        parser.keyboards,
        registered_commands=parser.registered_menu_commands,
        has_set_my_commands=parser.has_set_my_commands,
    )
    bot_map = analyzer.build_map()

    orphan_issues = [i for i in bot_map.issues if i.issue_type == "orphan_command"]
    assert len(orphan_issues) == 0

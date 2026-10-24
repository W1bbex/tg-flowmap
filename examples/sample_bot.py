"""
Sample Telegram Bot for TG-FLOWMAP demonstration.
Demonstrates navigation, menus, and inline keyboards.
"""

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

dp = Dispatcher()


def get_main_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="🛍️ Каталог", callback_data="catalog")
    builder.button(text="👤 Профиль", callback_data="profile")
    builder.button(text="⚙️ Настройки", callback_data="settings")
    builder.button(text="ℹ️ Помощь", callback_data="help")
    builder.adjust(2, 2)
    return builder.as_markup()


def get_catalog_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="📦 Товары", callback_data="catalog_items")
    builder.button(text="🏷️ Скидки", callback_data="catalog_sales")
    builder.button(text="⬅️ Главное меню", callback_data="back_main")
    builder.adjust(2, 1)
    return builder.as_markup()


def get_settings_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="🔔 Уведомления", callback_data="toggle_notif")
    builder.button(text="🌐 Язык", callback_data="change_lang")
    builder.button(text="⬅️ Главное меню", callback_data="back_main")
    builder.adjust(2, 1)
    return builder.as_markup()


def get_back_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад", callback_data="back_main")
    return builder.as_markup()


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Добро пожаловать в демо-магазин!\n\nВыберите интересующий раздел:",
        reply_markup=get_main_menu(),
    )


@dp.callback_query(F.data == "catalog")
async def show_catalog(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "🛍️ Каталог товаров и предложений:\nВыберите категорию:",
        reply_markup=get_catalog_menu(),
    )


@dp.callback_query(F.data == "profile")
async def show_profile(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "👤 Ваш профиль:\nID: 12345678\nБаланс: 0.00 ₽\nЗаказов: 0",
        reply_markup=get_back_menu(),
    )


@dp.callback_query(F.data == "settings")
async def show_settings(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "⚙️ Настройки бота и уведомлений:",
        reply_markup=get_settings_menu(),
    )


@dp.callback_query(F.data == "help")
async def show_help(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "ℹ️ Поддержка и часто задаваемые вопросы:\nЕсли возникли вопросы — напишите нашему менеджеру.",
        reply_markup=get_back_menu(),
    )


@dp.callback_query(F.data == "back_main")
async def back_to_main(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "👋 Главное меню демо-бота:\nВыберите раздел:",
        reply_markup=get_main_menu(),
    )

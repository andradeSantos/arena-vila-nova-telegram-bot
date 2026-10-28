"""Modulo de integracao com a API oficial do Telegram (Polling, Webhook e Comandos)."""

from __future__ import annotations

from backend.app.telegram.bot import (
    TelegramBotClient,
    TelegramPollingWorker,
    delete_webhook,
    get_me,
    get_telegram_bot_client,
    get_telegram_status,
    get_updates,
    process_telegram_update,
    reset_telegram_stats,
    send_message,
    set_webhook,
)

__all__ = [
    "TelegramBotClient",
    "TelegramPollingWorker",
    "delete_webhook",
    "get_me",
    "get_telegram_bot_client",
    "get_telegram_status",
    "get_updates",
    "process_telegram_update",
    "reset_telegram_stats",
    "send_message",
    "set_webhook",
]

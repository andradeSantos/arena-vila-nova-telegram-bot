"""Executavel de linha de comando para iniciar o Bot do Telegram ou simular updates reais."""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any, Dict

from backend.app.config import get_telegram_bot_token
from backend.app.telegram.bot import (
    TelegramBotClient,
    TelegramPollingWorker,
    process_telegram_update,
)

BOTFATHER_GUIDE: str = """============================================================================================
 BOT DO TELEGRAM — ARENA VILA NOVA (MODO DE CONFIGURAÇÃO)
============================================================================================
A variável de ambiente TELEGRAM_BOT_TOKEN não foi encontrada no ambiente ou no arquivo .env.

Como criar e configurar seu Bot no Telegram com o @BotFather:
  1. Abra o Telegram e inicie uma conversa com o perfil oficial verificado @BotFather.
  2. Envie o comando: /newbot
  3. Escolha o nome de exibição (ex.: "Arena Vila Nova Atendimento").
  4. Escolha o username terminado em 'bot' (ex.: "arena_vila_nova_bot").
  5. Copie o Token HTTP API gerado pelo @BotFather (formato: 123456789:AAHxyz...).
  6. Adicione ao arquivo .env na raiz do projeto:
       TELEGRAM_BOT_TOKEN=seu_token_aqui
  7. Inicie novamente o bot com:
       python3 -m backend.telegram_runner

Dica — Você pode testar o processamento completo do Telegram sem token usando --simulate:
  python3 -m backend.telegram_runner --simulate "Posso cancelar e receber o sinal de volta?"
  python3 -m backend.telegram_runner --simulate "/start"
  python3 -m backend.telegram_runner --simulate "/quadras"
============================================================================================"""


def build_simulated_telegram_update(
    text: str,
    chat_id: int = 900100200,
    user_id: int = 900100200,
    username: str = "cliente_arena",
    first_name: str = "Cliente",
    update_id: int = 700001,
) -> Dict[str, Any]:
    """Constroi um payload realista de Update da API oficial do Telegram."""
    now_ts = int(time.time())
    is_cmd = text.strip().startswith("/")
    entities = []
    if is_cmd:
        cmd_token = text.strip().split()[0]
        entities.append({"offset": 0, "length": len(cmd_token), "type": "bot_command"})

    message_payload: Dict[str, Any] = {
        "message_id": 101,
        "from": {
            "id": user_id,
            "is_bot": False,
            "first_name": first_name,
            "username": username,
            "language_code": "pt-br",
        },
        "chat": {
            "id": chat_id,
            "first_name": first_name,
            "username": username,
            "type": "private",
        },
        "date": now_ts,
        "text": text,
    }
    if entities:
        message_payload["entities"] = entities

    return {
        "update_id": update_id,
        "message": message_payload,
    }


def run_simulation(text: str) -> Dict[str, Any]:
    """Simula o recebimento de um payload real do Telegram e exibe a resposta formatada."""
    simulated_update = build_simulated_telegram_update(text=text)
    result = process_telegram_update(simulated_update, send_reply=False, persist_trace=True)

    print("\n" + "=" * 92)
    print(" SIMULAÇÃO DE UPDATE DO TELEGRAM — ARENA VILA NOVA")
    print("=" * 92)
    print("[1. PAYLOAD RECEBIDO DO TELEGRAM (update_dict)]")
    print(json.dumps(simulated_update, ensure_ascii=False, indent=2))

    print("\n[2. METADADOS DO PROCESSAMENTO E PIPELINE]")
    print(
        f"  Status: {result.get('status')} | "
        f"Trace ID: {result.get('trace_id')} | "
        f"Canal: telegram"
    )
    print(
        f"  Chat ID: {result.get('chat_id')} | "
        f"User: @{result.get('username')} ({result.get('first_name')}) | "
        f"Comando: {result.get('comando')}"
    )
    print(
        f"  Comportamento: {result.get('comportamento')} | "
        f"Fontes: {result.get('fontes')} | "
        f"Divergência Detectada: {result.get('divergencia_detectada')}"
    )
    print(
        f"  PII Detectado: {result.get('pii_detectado')} ({result.get('tipos_pii')}) | "
        f"Latência: {result.get('latencia_ms')} ms"
    )

    print("\n[3. RESPOSTA FORMATADA ENVIADA AO CLIENTE NO TELEGRAM]")
    print("-" * 92)
    print(result.get("resposta", ""))
    print("=" * 92 + "\n")
    return result


def run_polling_daemon(poll_timeout: int = 15) -> int:
    """Inicia o cliente Telegram em modo Long Polling continuo."""
    token = get_telegram_bot_token()
    if not token:
        print(BOTFATHER_GUIDE)
        return 0

    client = TelegramBotClient(token=token)
    me_resp = client.get_me()
    if not me_resp.get("ok"):
        print(
            f"[Erro Telegram] Falha ao validar TELEGRAM_BOT_TOKEN em api.telegram.org: "
            f"{me_resp.get('description')}",
            file=sys.stderr,
        )
        print(BOTFATHER_GUIDE)
        return 1

    bot_info = me_resp.get("result", {})
    bot_username = bot_info.get("username", "desconhecido")
    bot_name = bot_info.get("first_name", "Arena Vila Nova Bot")

    # Remove eventual webhook ativo para garantir funcionamento do Long Polling
    client.delete_webhook(drop_pending_updates=False)

    worker = TelegramPollingWorker(bot_client=client, poll_timeout=poll_timeout)
    started = worker.start()
    if not started:
        print("[Erro Telegram] Não foi possível iniciar o TelegramPollingWorker.", file=sys.stderr)
        return 1

    print("=" * 92)
    print(f" BOT TELEGRAM ATIVO: {bot_name} (@{bot_username})")
    print(" Modo: Long Polling Assíncrono | Pressione Ctrl+C para encerrar com parada limpa.")
    print("=" * 92)

    try:
        while worker.is_running:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nEncerrando TelegramPollingWorker...")
    finally:
        worker.stop()
        print("Bot do Telegram encerrado com sucesso.")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Executor de Long Polling e Simulador do Bot do Telegram da Arena Vila Nova."
    )
    parser.add_argument(
        "--simulate",
        type=str,
        default=None,
        help="Simula o recebimento de uma mensagem ou comando real do Telegram e exibe a resposta.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=15,
        help="Timeout em segundos para Long Polling getUpdates (padrao: 15).",
    )
    args = parser.parse_args()

    if args.simulate is not None:
        run_simulation(args.simulate)
        return 0

    return run_polling_daemon(poll_timeout=args.timeout)


if __name__ == "__main__":
    sys.exit(main())

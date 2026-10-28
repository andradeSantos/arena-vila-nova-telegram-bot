"""Testes automatizados (unittest) do Bloco 3: Conexao com o Telegram (REST, Comandos, Guardrail PII, Webhook e Polling)."""

from __future__ import annotations

import json
import unittest
from typing import Any, Dict, List
from unittest.mock import patch

from backend.app.agent.pipeline import get_pipeline
from backend.app.main import dispatch_api_request
from backend.app.rag.indexer import normalize_text
from backend.app.telegram import (
    TelegramBotClient,
    TelegramPollingWorker,
    get_telegram_status,
    process_telegram_update,
    reset_telegram_stats,
)
from backend.telegram_runner import build_simulated_telegram_update, run_simulation


class TestBlock3TelegramArenaVilaNova(unittest.TestCase):
    """Valida todos os requisitos funcionais, de seguranca e de integracao do Bloco 3 (Telegram)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.pipeline = get_pipeline(force_rebuild=True)

    def setUp(self) -> None:
        reset_telegram_stats()

    def test_a_comandos_start_quadras_ajuda_e_contato(self) -> None:
        """a) Valida o processamento dos comandos /start, /quadras, /ajuda e /contato no Telegram."""
        # Teste de /start
        upd_start = build_simulated_telegram_update(
            text="/start",
            chat_id=1001,
            user_id=2001,
            username="joao_futsal",
            first_name="João",
            update_id=501,
        )
        res_start = process_telegram_update(upd_start, send_reply=False)
        self.assertTrue(res_start["ok"])
        self.assertEqual(res_start["status"], "command")
        self.assertEqual(res_start["comando"], "/start")
        self.assertEqual(res_start["chat_id"], 1001)
        self.assertEqual(res_start["user_id"], "2001")
        self.assertEqual(res_start["username"], "joao_futsal")
        self.assertEqual(res_start["first_name"], "João")

        norm_start = normalize_text(res_start["resposta"])
        self.assertIn("arena vila nova", norm_start)
        self.assertIn("futsal", norm_start)
        self.assertIn("areia", norm_start)
        self.assertIn("7h as 23h", norm_start)
        self.assertIn("9999-0100", norm_start)

        # Teste de /quadras
        upd_quadras = build_simulated_telegram_update(
            text="/quadras@arena_vila_nova_bot",
            chat_id=1002,
            user_id=2002,
            username="maria_beach",
            first_name="Maria",
            update_id=502,
        )
        res_quadras = process_telegram_update(upd_quadras, send_reply=False)
        self.assertTrue(res_quadras["ok"])
        self.assertEqual(res_quadras["status"], "command")
        self.assertEqual(res_quadras["comando"], "/quadras")

        norm_quadras = normalize_text(res_quadras["resposta"])
        self.assertIn("4 quadras", norm_quadras)
        self.assertIn("f1 e f2", norm_quadras)
        self.assertIn("a1 e a2", norm_quadras)
        self.assertIn("120", norm_quadras)
        self.assertIn("160", norm_quadras)
        self.assertIn("70", norm_quadras)
        self.assertIn("90", norm_quadras)

        # Teste de /ajuda e /contato
        res_ajuda = process_telegram_update(build_simulated_telegram_update("/ajuda"), send_reply=False)
        self.assertEqual(res_ajuda["comando"], "/ajuda")
        self.assertIn("24 horas", normalize_text(res_ajuda["resposta"]))

        res_contato = process_telegram_update(build_simulated_telegram_update("/contato"), send_reply=False)
        self.assertEqual(res_contato["comando"], "/contato")
        self.assertIn("(99) 9999-0100", res_contato["resposta"])
        self.assertIn("contato@arenavilanova.example", res_contato["resposta"])
        self.assertIn("arenavilanova.example/reservas", res_contato["resposta"])

    def test_b_mensagem_texto_normal_pipeline_telegram(self) -> None:
        """b) Valida mensagem livre de texto encaminhada ao pipeline com canal='telegram' e metadados de sessao."""
        upd = build_simulated_telegram_update(
            text="Posso cancelar e receber o sinal de volta? Até quando?",
            chat_id=3003,
            user_id=4004,
            username="carlos_silva",
            first_name="Carlos",
            update_id=503,
        )
        res = process_telegram_update(upd, send_reply=False)
        self.assertTrue(res["ok"])
        self.assertEqual(res["status"], "processed")
        self.assertIsNone(res["comando"])
        self.assertFalse(res["pii_detectado"])
        self.assertEqual(res["comportamento"], "responder")
        self.assertIn("03-reservas-e-cancelamento", res["fontes"])
        self.assertTrue(res["divergencia_detectada"])
        self.assertIn("24 horas", normalize_text(res["resposta"]))

        trace = res["trace"]
        self.assertIsInstance(trace, dict)
        self.assertEqual(trace["request"]["canal"], "telegram")
        self.assertEqual(trace["request"]["chat_id"], 3003)
        self.assertEqual(trace["request"]["user_id"], "4004")
        self.assertEqual(trace["request"]["username"], "carlos_silva")
        self.assertEqual(trace["request"]["first_name"], "Carlos")

    def test_c_deteccao_e_bloqueio_dados_sensiveis_cpf_cartao_senha(self) -> None:
        """c) Garante deteccao e bloqueio de CPF, cartao e senha no Telegram sem salvar dados sensiveis."""
        raw_cpf = "123.456.789-01"
        raw_card = "4532 1122 3344 5566"

        upd_cpf = build_simulated_telegram_update(
            text=f"Oi, quero reservar uma quadra, meu CPF é {raw_cpf} e meu cartão é {raw_card}.",
            chat_id=5555,
            user_id=6666,
            username="cliente_pii",
            first_name="Pedro",
            update_id=504,
        )
        res_pii = process_telegram_update(upd_cpf, send_reply=False)

        self.assertTrue(res_pii["ok"])
        self.assertEqual(res_pii["status"], "blocked_pii")
        self.assertTrue(res_pii["pii_detectado"])
        self.assertIn("CPF", res_pii["tipos_pii"])
        self.assertIn("CARTAO_CREDITO", res_pii["tipos_pii"])
        self.assertIn("04-pagamento", res_pii["fontes"])
        self.assertIn("09-privacidade-e-lgpd", res_pii["fontes"])

        # Orienta sobre seguranca conforme 04-pagamento.md e 09-privacidade-e-lgpd.md
        norm_reply = normalize_text(res_pii["resposta"])
        self.assertIn("04-pagamento", norm_reply)
        self.assertIn("09-privacidade-e-lgpd", norm_reply)
        self.assertIn("arenavilanova.example/reservas", norm_reply)
        self.assertIn("9999-0100", norm_reply)

        # Garante que os dados sensiveis NUNCA estao na pergunta sanitizada, na resposta ou no trace gravado
        self.assertNotIn(raw_cpf, res_pii["pergunta_sanitizada"])
        self.assertNotIn(raw_card, res_pii["pergunta_sanitizada"])
        self.assertIn("[REDACTED_CPF]", res_pii["pergunta_sanitizada"])
        self.assertIn("[REDACTED_CARD]", res_pii["pergunta_sanitizada"])

        trace_json_str = json.dumps(res_pii["trace"], ensure_ascii=False)
        self.assertNotIn(raw_cpf, trace_json_str)
        self.assertNotIn(raw_card, trace_json_str)

        # Verifica tambem nos ultimos logs persistidos em traces.jsonl
        recent_traces = self.pipeline.read_recent_traces(limit=5)
        self.assertGreaterEqual(len(recent_traces), 1)
        recent_dump = json.dumps(recent_traces, ensure_ascii=False)
        self.assertNotIn(raw_cpf, recent_dump)
        self.assertNotIn(raw_card, recent_dump)

    def test_d_endpoints_webhook_e_status_em_main(self) -> None:
        """d) Valida POST /api/telegram/webhook e GET /api/telegram/status em main.py respondendo 200 e gerando trace."""
        webhook_payload = build_simulated_telegram_update(
            text="Quanto custa uma hora de futsal numa quarta, às 19h?",
            chat_id=7777,
            user_id=8888,
            username="ana_reserva",
            first_name="Ana",
            update_id=901,
        )
        raw_body = json.dumps(webhook_payload, ensure_ascii=False).encode("utf-8")

        status_code, resp = dispatch_api_request("POST", "/api/telegram/webhook", {}, raw_body)
        self.assertEqual(status_code, 200)
        self.assertTrue(resp["ok"])
        self.assertEqual(resp["status"], "processed")
        self.assertIn("160", resp["resposta"])
        self.assertIn("02-quadras-e-precos", resp["fontes"])
        self.assertIsNotNone(resp["trace_id"])
        self.assertIsInstance(resp["trace"], dict)
        self.assertEqual(resp["trace"]["request"]["canal"], "telegram")

        # Verifica se o trace foi efetivamente persistido e pode ser consultado via GET /api/logs
        logs_code, logs_resp = dispatch_api_request("GET", "/api/logs", {"limit": ["5"]}, b"")
        self.assertEqual(logs_code, 200)
        trace_ids = [t.get("trace_id") for t in logs_resp.get("logs", [])]
        self.assertIn(resp["trace_id"], trace_ids)

        # Valida GET /api/telegram/status
        st_code, st_resp = dispatch_api_request("GET", "/api/telegram/status", {}, b"")
        self.assertEqual(st_code, 200)
        self.assertIn("token_present", st_resp)
        self.assertIn("bot_username", st_resp)
        self.assertGreaterEqual(st_resp["messages_received"], 1)
        self.assertGreaterEqual(st_resp["webhook_calls"], 1)

    def test_e_cliente_rest_fallback_polling_worker_e_runner(self) -> None:
        """e) Valida TelegramBotClient, fallback de erro amigavel, TelegramPollingWorker e telegram_runner."""
        # Teste do Fallback de Erro amigavel indicando (99) 9999-0100
        upd = build_simulated_telegram_update("Qual o horario de funcionamento?")
        with patch("backend.app.telegram.bot.get_pipeline", side_effect=RuntimeError("Falha simulada")):
            err_res = process_telegram_update(upd, send_reply=False)
            self.assertEqual(err_res["status"], "error_fallback")
            self.assertIn("(99) 9999-0100", err_res["resposta"])

        # Teste do TelegramPollingWorker em background thread com parada limpa
        processed_updates: List[Dict[str, Any]] = []

        class FakeTelegramClient(TelegramBotClient):
            def __init__(self) -> None:
                super().__init__(token="123456:FAKE_TOKEN_FOR_TEST")
                self.calls = 0

            def get_me(self) -> Dict[str, Any]:
                return {"ok": True, "result": {"id": 123, "is_bot": True, "username": "arena_test_bot"}}

            def get_updates(
                self,
                offset: int | None = None,
                timeout: int = 30,
                allowed_updates: List[str] | None = None,
            ) -> Dict[str, Any]:
                self.calls += 1
                if self.calls == 1:
                    return {
                        "ok": True,
                        "result": [
                            build_simulated_telegram_update(
                                text="/contato",
                                update_id=100,
                            )
                        ],
                    }
                return {"ok": True, "result": []}

        fake_client = FakeTelegramClient()
        worker = TelegramPollingWorker(
            bot_client=fake_client,
            poll_timeout=1,
            retry_delay=0.05,
            update_handler=lambda u: processed_updates.append(u) or {},
        )
        self.assertTrue(worker.start())
        # Aguarda processamento do primeiro lote na thread em background
        import time

        deadline = time.monotonic() + 2.0
        while worker.updates_processed < 1 and time.monotonic() < deadline:
            time.sleep(0.02)

        worker.stop(timeout=2.0)
        self.assertFalse(worker.is_running)
        self.assertEqual(worker.updates_processed, 1)
        self.assertEqual(worker.last_offset, 101)
        self.assertEqual(len(processed_updates), 1)

        # Teste da funcao run_simulation do telegram_runner
        sim_res = run_simulation("Vocês aceitam Pix?")
        self.assertTrue(sim_res["ok"])
        self.assertIn("04-pagamento", sim_res["fontes"])


if __name__ == "__main__":
    unittest.main()

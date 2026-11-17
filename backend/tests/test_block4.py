"""Testes automatizados (unittest) do Bloco 4: Frontend de Observabilidade, Testes e Memoria."""

from __future__ import annotations

import json
import threading
import unittest
import urllib.request
from typing import Any, Dict, Tuple

from backend.app.config import ERROR_LEDGER_PATH
from backend.app.main import create_http_server, resolve_static_asset


class TestBlock4FrontendObservabilidade(unittest.TestCase):
    """Valida a entrega de arquivos estaticos do Frontend SPA e todas as rotas REST consumidas no Bloco 4."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._ledger_backup: str | None = (
            ERROR_LEDGER_PATH.read_text(encoding="utf-8")
            if ERROR_LEDGER_PATH.exists()
            else None
        )
        cls.server = create_http_server(host="127.0.0.1", port=0)
        cls.port = cls.server.server_address[1]
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.server_thread = threading.Thread(
            target=cls.server.serve_forever,
            name="TestBlock4HTTPServer",
            daemon=True,
        )
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join(timeout=3.0)
        if cls._ledger_backup is not None:
            ERROR_LEDGER_PATH.write_text(cls._ledger_backup, encoding="utf-8")

    def _http_get(self, path: str) -> Tuple[int, str, bytes]:
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            status_code = resp.getcode()
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read()
            return status_code, content_type, raw

    def _http_post_json(self, path: str, payload: Dict[str, Any]) -> Tuple[int, str, Dict[str, Any]]:
        url = f"{self.base_url}{path}"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30.0) as resp:
            status_code = resp.getcode()
            content_type = resp.headers.get("Content-Type", "")
            data = json.loads(resp.read().decode("utf-8"))
            return status_code, content_type, data

    def test_a_servidor_entregando_get_raiz_com_status_200_e_html(self) -> None:
        """a) Valida que GET / e GET /index.html retornam status 200, Content-Type text/html e as 4 abas."""
        for route in ("/", "/index.html"):
            status, content_type, raw = self._http_get(route)
            self.assertEqual(status, 200)
            self.assertIn("text/html", content_type)

            html_text = raw.decode("utf-8")
            self.assertIn("<!DOCTYPE html>", html_text)
            self.assertIn("Arena Vila Nova", html_text)
            self.assertIn("Playground &amp; Raio-X", html_text)
            self.assertIn("Bateria de Testes", html_text)
            self.assertIn("Gestão de Memória (IA-FIRST)", html_text)
            self.assertIn("Monitor Telegram Live", html_text)

    def test_b_servidor_entregando_assets_css_e_js_com_content_type_adequado(self) -> None:
        """b) Valida que GET /style.css e GET /app.js retornam 200 e Content-Type adequado."""
        css_status, css_type, css_raw = self._http_get("/style.css")
        self.assertEqual(css_status, 200)
        self.assertIn("text/css", css_type)
        css_text = css_raw.decode("utf-8")
        self.assertIn("--brand-emerald", css_text)
        self.assertIn('[data-theme="light"]', css_text)

        js_status, js_type, js_raw = self._http_get("/app.js")
        self.assertEqual(js_status, 200)
        self.assertIn("javascript", js_type)
        js_text = js_raw.decode("utf-8")
        for expected_endpoint in (
            "/api/chat",
            "/api/eval/run",
            "/api/logs",
            "/api/memory",
            "/api/telegram/status",
            "/api/kb/chunks",
        ):
            self.assertIn(expected_endpoint, js_text)

        # Valida tambem a funcao utilitaria resolve_static_asset diretamente
        res_root = resolve_static_asset("/")
        self.assertIsNotNone(res_root)
        self.assertEqual(res_root[0], 200)

    def test_c_rotas_rest_consumidas_pelo_frontend_respondendo_corretamente(self) -> None:
        """c) Valida /api/kb/chunks, /api/memory, /api/eval/run, /api/telegram/status, /api/chat e /api/logs via HTTP."""
        # 1. GET /api/kb/chunks
        kb_status, kb_type, kb_raw = self._http_get("/api/kb/chunks")
        self.assertEqual(kb_status, 200)
        self.assertIn("application/json", kb_type)
        kb_data = json.loads(kb_raw.decode("utf-8"))
        self.assertGreater(kb_data["total_active_chunks"], 15)
        self.assertIsInstance(kb_data["chunks"], list)
        self.assertIn("metadados", kb_data["chunks"][0])
        self.assertIn("peso_precedencia", kb_data["chunks"][0])

        # 2. GET & POST /api/memory
        mem_status, _, mem_raw = self._http_get("/api/memory")
        self.assertEqual(mem_status, 200)
        mem_data = json.loads(mem_raw.decode("utf-8"))
        self.assertIn("entries", mem_data)
        self.assertGreaterEqual(len(mem_data["entries"]), 4)

        post_mem_status, _, post_mem_data = self._http_post_json(
            "/api/memory",
            {
                "id": "MEM-001",
                "pergunta_gatilho": mem_data["entries"][0]["pergunta_gatilho"],
                "etapa_falha": mem_data["entries"][0]["etapa_falha"],
                "causa_raiz": mem_data["entries"][0]["causa_raiz"],
                "regra_corretiva": mem_data["entries"][0]["regra_corretiva"],
                "fontes_afetadas": mem_data["entries"][0]["fontes_afetadas"],
                "ativo": True,
            },
        )
        self.assertEqual(post_mem_status, 201)
        self.assertEqual(post_mem_data["status"], "recorded")

        # 3. POST /api/chat (Raio-X de 5 estagios)
        chat_status, _, chat_data = self._http_post_json(
            "/api/chat",
            {
                "pergunta": "Posso cancelar e receber o sinal de volta? Até quando?",
                "canal": "playground_web",
            },
        )
        self.assertEqual(chat_status, 200)
        self.assertEqual(chat_data["comportamento"], "responder")
        self.assertIn("03-reservas-e-cancelamento", chat_data["fontes"])
        self.assertIn("trace", chat_data)
        for stage_key in (
            "request",
            "guardrails_entrada",
            "filtragem",
            "memoria",
            "geracao",
            "resposta_final",
        ):
            self.assertIn(stage_key, chat_data["trace"])

        # 4. GET /api/telegram/status e GET /api/logs
        tg_status, _, tg_raw = self._http_get("/api/telegram/status")
        self.assertEqual(tg_status, 200)
        tg_data = json.loads(tg_raw.decode("utf-8"))
        self.assertIn("token_present", tg_data)
        self.assertIn("bot_username", tg_data)
        self.assertIn("messages_received", tg_data)

        logs_status, _, logs_raw = self._http_get("/api/logs?limit=10")
        self.assertEqual(logs_status, 200)
        logs_data = json.loads(logs_raw.decode("utf-8"))
        self.assertGreaterEqual(logs_data["count"], 1)

        # 5. POST /api/eval/run (Suite publica P01-P16)
        eval_status, _, eval_data = self._http_post_json("/api/eval/run", {})
        self.assertEqual(eval_status, 200)
        self.assertEqual(eval_data["total"], 16)
        self.assertEqual(eval_data["passed"], 16)
        self.assertEqual(eval_data["pass_rate_percent"], 100.0)


if __name__ == "__main__":
    unittest.main()

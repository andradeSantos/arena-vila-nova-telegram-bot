"""Servidor HTTP/REST do Backend da Arena Vila Nova (compativel com stdlib ThreadingHTTPServer)."""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Tuple
from urllib.parse import parse_qs, urlparse

from backend.app.agent.pipeline import get_pipeline
from backend.app.config import get_gemini_api_key, get_port
from backend.app.memory.manager import get_memory_manager
from backend.app.rag.indexer import get_index
from backend.app.telegram.bot import (
    get_telegram_status,
    process_telegram_update,
    record_webhook_call,
)
from backend.eval_runner import run_evaluation_suite


def dispatch_api_request(
    method: str,
    path: str,
    query_params: Dict[str, list[str]],
    body_bytes: bytes,
) -> Tuple[int, Dict[str, Any]]:
    """Processa as rotas REST da API e retorna (status_code, payload_json)."""
    clean_path = path.rstrip("/") or "/"

    def parse_json_body() -> Dict[str, Any]:
        if not body_bytes:
            return {}
        try:
            data = json.loads(body_bytes.decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    # GET /api/health
    if method == "GET" and clean_path == "/api/health":
        idx = get_index()
        return 200, {
            "status": "ok",
            "service": "arena-vila-nova-backend",
            "gemini_configured": bool(get_gemini_api_key()),
            "active_chunks_count": len(idx.chunks),
            "obsolete_docs_discarded": idx.obsolete_filenames,
            "blocked_injection_chunks": idx.blocked_chunk_ids,
        }

    # GET /api/kb/chunks
    if method == "GET" and clean_path == "/api/kb/chunks":
        idx = get_index()
        return 200, {
            "total_active_chunks": len(idx.chunks),
            "chunks": [c.to_dict() for c in idx.chunks],
            "discarded_obsolete_docs": idx.discarded_obsolete_docs,
            "blocked_injection_chunks": [c.to_dict() for c in idx.blocked_injection_chunks],
        }

    # GET /api/memory
    if method == "GET" and clean_path == "/api/memory":
        mm = get_memory_manager()
        ledger = mm.load_ledger()
        return 200, ledger

    # POST /api/memory
    if method == "POST" and clean_path == "/api/memory":
        payload = parse_json_body()
        pergunta_gatilho = str(payload.get("pergunta_gatilho", "")).strip()
        etapa_falha = str(payload.get("etapa_falha", "geracao")).strip()
        causa_raiz = str(payload.get("causa_raiz", "")).strip()
        regra_corretiva = str(payload.get("regra_corretiva", "")).strip()
        fontes_afetadas = payload.get("fontes_afetadas", [])
        if not pergunta_gatilho or not regra_corretiva:
            return 400, {
                "error": "Campos obrigatorios: 'pergunta_gatilho' e 'regra_corretiva'."
            }
        mm = get_memory_manager()
        entry = mm.record_error(
            pergunta_gatilho=pergunta_gatilho,
            etapa_falha=etapa_falha,
            causa_raiz=causa_raiz,
            regra_corretiva=regra_corretiva,
            fontes_afetadas=fontes_afetadas if isinstance(fontes_afetadas, list) else [],
            ativo=bool(payload.get("ativo", True)),
            entry_id=payload.get("id"),
        )
        return 201, {"status": "recorded", "entry": entry}

    # GET /api/logs
    if method == "GET" and clean_path == "/api/logs":
        limit_str = (query_params.get("limit") or ["50"])[0]
        try:
            limit = max(1, min(500, int(limit_str)))
        except ValueError:
            limit = 50
        pipeline = get_pipeline()
        traces = pipeline.read_recent_traces(limit=limit)
        return 200, {"count": len(traces), "logs": traces}

    # POST /api/chat
    if method == "POST" and clean_path == "/api/chat":
        payload = parse_json_body()
        pergunta = str(payload.get("pergunta") or payload.get("message") or "").strip()
        if not pergunta:
            return 400, {"error": "Campo 'pergunta' (ou 'message') e obrigatorio."}

        chat_id = payload.get("chat_id", 0)
        user_id = str(payload.get("user_id", "api_user"))
        canal = str(payload.get("canal", "api"))
        request_id = payload.get("request_id")

        pipeline = get_pipeline()
        trace = pipeline.run(
            pergunta=pergunta,
            chat_id=chat_id,
            user_id=user_id,
            canal=canal,
            request_id=request_id,
            persist_trace=True,
        )
        return 200, {
            "resposta": trace.resposta,
            "comportamento": trace.comportamento,
            "fontes": trace.fontes,
            "divergencia_detectada": trace.divergencia_detectada,
            "latencia_ms": trace.latencia_ms,
            "trace": trace.to_dict(),
        }

    # POST /api/eval/run
    if method == "POST" and clean_path == "/api/eval/run":
        report = run_evaluation_suite(save_reports=True)
        return 200, report

    # POST /api/telegram/webhook
    if method == "POST" and clean_path == "/api/telegram/webhook":
        payload = parse_json_body()
        record_webhook_call()
        result = process_telegram_update(
            payload,
            send_reply=bool(payload.get("send_reply", False)),
            persist_trace=True,
        )
        return 200, result

    # GET /api/telegram/status
    if method == "GET" and clean_path == "/api/telegram/status":
        status_payload = get_telegram_status(verify_token_online=False)
        return 200, status_payload

    return 404, {"error": f"Rota nao encontrada: {method} {path}"}


class ArenaRequestHandler(BaseHTTPRequestHandler):
    """Handler HTTP com suporte completo a CORS e JSON para as rotas da Arena Vila Nova."""

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def _send_json(self, status_code: int, payload: Dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self._send_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query_params = parse_qs(parsed.query)
        status, response = dispatch_api_request("GET", parsed.path, query_params, b"")
        self._send_json(status, response)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query_params = parse_qs(parsed.query)
        content_len = int(self.headers.get("Content-Length", "0") or "0")
        body_bytes = self.rfile.read(content_len) if content_len > 0 else b""
        status, response = dispatch_api_request("POST", parsed.path, query_params, body_bytes)
        self._send_json(status, response)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        # Silencia logs padrao durante execucao de testes automatizados
        return


def create_http_server(host: str = "0.0.0.0", port: int | None = None) -> ThreadingHTTPServer:
    """Cria e retorna uma instancia de ThreadingHTTPServer pronta para servir a API REST."""
    effective_port = port if port is not None else get_port()
    return ThreadingHTTPServer((host, effective_port), ArenaRequestHandler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Servidor HTTP REST da Arena Vila Nova.")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host de escuta (padrao 0.0.0.0)")
    parser.add_argument("--port", type=int, default=get_port(), help="Porta HTTP (padrao 8000)")
    args = parser.parse_args()

    server = create_http_server(host=args.host, port=args.port)
    print(f"Servidor da Arena Vila Nova rodando em http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrando servidor HTTP...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

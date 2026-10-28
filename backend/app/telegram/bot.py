"""Cliente REST da API do Telegram, Processador de Updates e Worker de Long Polling."""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from backend.app.agent.guardrails import redact_pii
from backend.app.agent.pipeline import PipelineTrace, get_pipeline
from backend.app.config import get_telegram_bot_token

TELEGRAM_API_BASE_URL: str = "https://api.telegram.org"

# Expressoes regulares complementares para deteccao de credenciais com acentuacao no Telegram
_EXTRA_CREDENTIAL_REGEX = re.compile(
    r"(?:"
    r"\b(?:minha\s+senha\s*(?:e|é|eh|:)?\s*\S+)"
    r"|\b(?:senha\s*(?:do\s+cartao|da\s+conta|de\s+acesso|:|=)\s*\S+)"
    r"|\b(?:cvv\s*[:=]?\s*\d{3,4})"
    r"|\b(?:c[oó]digo\s+de\s+verifica[cç][aã]o\s*[:=]?\s*\S+)"
    r")",
    re.IGNORECASE,
)

# Textos institucionais para os comandos rapidos do Telegram
COMMAND_RESPONSES: Dict[str, Tuple[str, List[str]]] = {
    "/start": (
        "🏟️ *Bem-vindo(a) ao Atendimento Virtual da Arena Vila Nova!*\n\n"
        "Somos um complexo esportivo localizado na *Rua das Palmeiras, 450, Bairro Vila Nova*, "
        "com estrutura completa para o seu jogo:\n"
        "• *2 quadras de futsal (F1 e F2):* cobertas, com piso sintético (até 14 pessoas).\n"
        "• *2 quadras de areia (A1 e A2):* descobertas, para vôlei de praia e beach tennis (até 8 pessoas).\n"
        "• *Estrutura de apoio:* vestiários com armários e bebedouros.\n\n"
        "🕒 *Horários de funcionamento:*\n"
        "• Segunda a sexta: *7h às 23h*\n"
        "• Sábado: *7h às 22h*\n"
        "• Domingo e feriados: *8h às 20h*\n"
        "_(Fechado em 25 de dezembro e 1º de janeiro)_\n\n"
        "💬 *Como tirar dúvidas:*\n"
        "Envie sua pergunta diretamente por mensagem (ex.: _\"Quanto custa o futsal à noite?\"_, "
        "_\"Posso cancelar e receber o sinal de volta?\"_) ou utilize os atalhos:\n"
        "• /quadras — Estrutura das 4 quadras e tabela de preços\n"
        "• /ajuda — Resumo de regras, pagamentos e cancelamento\n"
        "• /contato — Telefone da recepção, e-mails e site de reservas\n\n"
        "📌 _Lembrete: Reservas e cancelamentos são realizados pelo site_ "
        "*arenavilanova.example/reservas* _ou na recepção pelo telefone_ *(99) 9999-0100*.",
        ["01-sobre-a-arena", "02-quadras-e-precos", "03-reservas-e-cancelamento"],
    ),
    "/ajuda": (
        "📋 *Guia Rápido de Dúvidas Frequentes — Arena Vila Nova*\n\n"
        "1️⃣ *Quadras e Preços (/quadras):*\n"
        "• *Futsal (F1 e F2, cobertas):* *R$ 120/h* (seg-sex até 17h) | *R$ 160/h* (após 17h, sáb, dom e feriados).\n"
        "• *Areia (A1 e A2, descobertas):* *R$ 70/h* (seg-sex até 17h) | *R$ 90/h* (após 17h, sáb, dom e feriados).\n"
        "• *Descontos oficiais:* *10%* para 2h consecutivas na mesma quadra e *15%* no plano mensalista.\n\n"
        "2️⃣ *Horários de Funcionamento:*\n"
        "• Seg-sex: *7h às 23h* | Sáb: *7h às 22h* | Dom e feriados: *8h às 20h*.\n\n"
        "3️⃣ *Reservas, Sinal e Cancelamento (Política v2.0):*\n"
        "• Reservas no site *arenavilanova.example/reservas* ou recepção *(99) 9999-0100* (não fazemos pelo Telegram).\n"
        "• Confirmação mediante *sinal de 30%* pago em até 2h (via Pix ou cartão no site).\n"
        "• *Cancelamento gratuito:* até *24 horas antes* do início (devolução integral do sinal em até 7 dias úteis ou crédito por 60 dias).\n"
        "• *Reagendamento sem custo:* 1 vez por reserva, com pelo menos *12 horas de antecedência*.\n\n"
        "4️⃣ *Formas de Pagamento:*\n"
        "• *Pix (sem taxa)*, *cartão de crédito* (até 3x sem juros acima de R$ 300), *cartão de débito* e *dinheiro* (apenas para o saldo na recepção; não aceitamos cheque).\n\n"
        "5️⃣ *Regras de Uso:*\n"
        "• Futsal: tênis/solado liso (*chuteiras de trava são proibidas*). Areia: descalço ou meias próprias.\n"
        "• Proibido recipientes de vidro, fumo, animais (exceto cão de assistência), fogo/churrasqueira e som alto.",
        [
            "01-sobre-a-arena",
            "02-quadras-e-precos",
            "03-reservas-e-cancelamento",
            "04-pagamento",
            "05-regras-de-uso",
        ],
    ),
    "/quadras": (
        "⚽🏐 *Quadras e Tabela de Preços — Arena Vila Nova*\n\n"
        "Contamos com *4 quadras* (valores por hora com iluminação incluída, vigentes desde 01/08/2026):\n\n"
        "🥅 *Futsal — Quadras F1 e F2 (Cobertas, piso sintético):*\n"
        "• Segunda a sexta (até 17h): *R$ 120 / hora*\n"
        "• Segunda a sexta (após 17h): *R$ 160 / hora*\n"
        "• Sábados, domingos e feriados: *R$ 160 / hora*\n"
        "• Capacidade: até *14 pessoas* por reserva.\n\n"
        "🏖️ *Areia — Quadras A1 e A2 (Descobertas, vôlei de praia e beach tennis):*\n"
        "• Segunda a sexta (até 17h): *R$ 70 / hora*\n"
        "• Segunda a sexta (após 17h): *R$ 90 / hora*\n"
        "• Sábados, domingos e feriados: *R$ 90 / hora*\n"
        "• Capacidade: até *8 pessoas* por reserva.\n\n"
        "🏷️ *Descontos e Itens Adicionais:*\n"
        "• *2 horas consecutivas* na mesma quadra: *10% de desconto* no valor total.\n"
        "• *Plano mensalista* (horário fixo semanal, mín. 3 meses): *15% de desconto*.\n"
        "• Bola de futsal: *R$ 10* por reserva | Kit beach tennis (2 raquetes + 1 bola): *R$ 20* por reserva.\n\n"
        "📍 Para reservar, acesse *arenavilanova.example/reservas* ou ligue para *(99) 9999-0100*.",
        ["01-sobre-a-arena", "02-quadras-e-precos", "06-planos-mensalistas"],
    ),
    "/contato": (
        "📞 *Canais Oficiais de Contato — Arena Vila Nova*\n\n"
        "• *Telefone da Recepção:* *(99) 9999-0100*\n"
        "  _(Atendimento: seg-sex das 7h às 23h, sáb das 7h às 22h, dom e feriados das 8h às 20h)_\n"
        "• *Site de Reservas:* *arenavilanova.example/reservas*\n"
        "• *E-mail Geral:* `contato@arenavilanova.example`\n"
        "• *Eventos e Aniversários:* `eventos@arenavilanova.example` _(resposta em até 2 dias úteis)_\n"
        "• *Privacidade e LGPD:* `privacidade@arenavilanova.example` _(resposta em até 15 dias)_\n"
        "• *Endereço:* Rua das Palmeiras, 450, Bairro Vila Nova.",
        ["01-sobre-a-arena", "07-eventos-e-campeonatos", "09-privacidade-e-lgpd"],
    ),
}
COMMAND_RESPONSES["/help"] = COMMAND_RESPONSES["/ajuda"]

PII_SECURITY_RESPONSE: str = (
    "🔒 *Aviso de Segurança e Proteção de Dados (LGPD)*\n\n"
    "Pelas nossas regras de formas de pagamento (`04-pagamento`) e conforme a nossa política de "
    "privacidade e proteção de dados (`09-privacidade-e-lgpd`), *a Arena Vila Nova nunca pede, "
    "coleta nem armazena CPF, número de cartão de crédito/débito, senha ou código de verificação "
    "pelo Telegram*.\n\n"
    "Por sua segurança, os dados sensíveis enviados foram *bloqueados e descartados* sem registro. "
    "Recomendamos que você *apague a mensagem enviada* neste chat.\n\n"
    "👉 Dados de pagamento ou CPF/CNPJ para emissão de nota fiscal devem ser informados "
    "exclusivamente no site oficial *arenavilanova.example/reservas* ou presencialmente na "
    "recepção. Se precisar de auxílio, fale conosco pelo telefone *(99) 9999-0100* ou pelo "
    "e-mail `privacidade@arenavilanova.example`."
)

ERROR_FALLBACK_RESPONSE: str = (
    "Desculpe, tivemos uma instabilidade momentânea ao processar sua solicitação aqui pelo Telegram. "
    "Por favor, tente novamente em instantes ou entre em contato diretamente com a recepção da "
    "Arena Vila Nova pelo telefone *(99) 9999-0100* (segunda a sexta das 7h às 23h, sábado das "
    "7h às 22h, domingo e feriados das 8h às 20h) ou pelo site *arenavilanova.example/reservas*."
)


class _TelegramRuntimeState:
    """Estado thread-safe para telemetria e status da conexao com o Telegram."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.bot_username: Optional[str] = None
        self.bot_info: Optional[Dict[str, Any]] = None
        self.polling_active: bool = False
        self.messages_received: int = 0
        self.messages_sent: int = 0
        self.commands_processed: int = 0
        self.pii_blocked_count: int = 0
        self.webhook_calls: int = 0
        self.errors_count: int = 0
        self.last_update_id: Optional[int] = None
        self.last_message_at: Optional[str] = None

    def reset(self) -> None:
        with self.lock:
            self.bot_username = None
            self.bot_info = None
            self.polling_active = False
            self.messages_received = 0
            self.messages_sent = 0
            self.commands_processed = 0
            self.pii_blocked_count = 0
            self.webhook_calls = 0
            self.errors_count = 0
            self.last_update_id = None
            self.last_message_at = None


_STATE = _TelegramRuntimeState()


def reset_telegram_stats() -> None:
    """Reinicia os contadores em memoria da integracao com o Telegram."""
    _STATE.reset()


def detect_and_redact_telegram_pii(text: str) -> Tuple[str, bool, List[str]]:
    """Detecta e mascara CPF, cartao de credito/debito, senhas e CVV enviados no Telegram."""
    sanitized, has_pii, pii_types = redact_pii(text)
    if _EXTRA_CREDENTIAL_REGEX.search(sanitized):
        if "SENHA_OU_CVV" not in pii_types:
            pii_types.append("SENHA_OU_CVV")
        sanitized = _EXTRA_CREDENTIAL_REGEX.sub("[REDACTED_CREDENTIAL]", sanitized)
        has_pii = True
    return sanitized, has_pii, pii_types


class TelegramBotClient:
    """Cliente HTTP/REST direto para a API oficial do Telegram (api.telegram.org)."""

    def __init__(
        self,
        token: Optional[str] = None,
        base_url: str = TELEGRAM_API_BASE_URL,
        timeout: float = 15.0,
    ) -> None:
        self._explicit_token: Optional[str] = token.strip() if token is not None else None
        self.base_url: str = base_url.rstrip("/")
        self.timeout: float = timeout

    @property
    def token(self) -> str:
        """Retorna o token configurado explicitamente ou lido do ambiente."""
        if self._explicit_token is not None:
            return self._explicit_token
        return get_telegram_bot_token()

    def _build_url(self, method_name: str) -> str:
        return f"{self.base_url}/bot{self.token}/{method_name}"

    def _request_json(
        self,
        http_method: str,
        api_method: str,
        payload: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Executa chamada HTTP para a API do Telegram com fallback entre requests e urllib.request."""
        token = self.token
        if not token:
            return {
                "ok": False,
                "error_code": 401,
                "description": "TELEGRAM_BOT_TOKEN nao configurado no ambiente.",
            }

        url = self._build_url(api_method)
        effective_timeout = timeout if timeout is not None else self.timeout

        try:
            if http_method.upper() == "GET":
                resp = requests.get(url, params=payload or {}, timeout=effective_timeout)
            else:
                resp = requests.post(url, json=payload or {}, timeout=effective_timeout)
            data = resp.json()
            if isinstance(data, dict):
                return data
            return {"ok": False, "error_code": resp.status_code, "description": "Resposta invalida"}
        except requests.RequestException:
            # Fallback para urllib.request caso requests falhe na camada de transporte
            try:
                body_bytes: Optional[bytes] = None
                headers: Dict[str, str] = {"Accept": "application/json"}
                req_url = url
                if http_method.upper() == "GET" and payload:
                    from urllib.parse import urlencode

                    req_url = f"{url}?{urlencode(payload)}"
                elif http_method.upper() != "GET":
                    body_bytes = json.dumps(payload or {}).encode("utf-8")
                    headers["Content-Type"] = "application/json; charset=utf-8"

                req = urllib.request.Request(
                    req_url,
                    data=body_bytes,
                    headers=headers,
                    method=http_method.upper(),
                )
                with urllib.request.urlopen(req, timeout=effective_timeout) as u_resp:
                    raw = u_resp.read().decode("utf-8")
                    return json.loads(raw)
            except urllib.error.HTTPError as http_err:
                try:
                    err_body = http_err.read().decode("utf-8")
                    parsed_err = json.loads(err_body)
                    if isinstance(parsed_err, dict):
                        return parsed_err
                except Exception:
                    pass
                with _STATE.lock:
                    _STATE.errors_count += 1
                return {
                    "ok": False,
                    "error_code": http_err.code,
                    "description": str(http_err),
                }
            except Exception as exc:
                with _STATE.lock:
                    _STATE.errors_count += 1
                return {
                    "ok": False,
                    "error_code": 500,
                    "description": f"Erro de comunicacao com api.telegram.org: {exc}",
                }
        except Exception as exc:
            with _STATE.lock:
                _STATE.errors_count += 1
            return {
                "ok": False,
                "error_code": 500,
                "description": f"Erro inesperado na chamada Telegram API: {exc}",
            }

    def get_me(self) -> Dict[str, Any]:
        """Valida o token na API do Telegram e retorna os dados do bot."""
        res = self._request_json("GET", "getMe")
        if res.get("ok") and isinstance(res.get("result"), dict):
            bot_data = res["result"]
            with _STATE.lock:
                _STATE.bot_info = bot_data
                _STATE.bot_username = bot_data.get("username")
        return res

    def get_updates(
        self,
        offset: Optional[int] = None,
        timeout: int = 30,
        allowed_updates: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Busca novas mensagens via Long Polling na API oficial do Telegram."""
        payload: Dict[str, Any] = {"timeout": max(0, int(timeout))}
        if offset is not None:
            payload["offset"] = int(offset)
        if allowed_updates is not None:
            payload["allowed_updates"] = allowed_updates
        http_timeout = max(self.timeout, float(timeout) + 5.0)
        return self._request_json("POST", "getUpdates", payload=payload, timeout=http_timeout)

    def send_message(
        self,
        chat_id: int | str,
        text: str,
        parse_mode: Optional[str] = "Markdown",
        disable_web_page_preview: bool = True,
    ) -> Dict[str, Any]:
        """Envia mensagem para o cliente no Telegram com fallback seguro de formatacao."""
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": disable_web_page_preview,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode

        res = self._request_json("POST", "sendMessage", payload=payload)
        # Se houver erro de parse de Markdown (HTTP 400), reenvia em texto puro para garantir entrega
        if not res.get("ok") and parse_mode and res.get("error_code") == 400:
            fallback_payload = {
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": disable_web_page_preview,
            }
            res = self._request_json("POST", "sendMessage", payload=fallback_payload)

        if res.get("ok"):
            with _STATE.lock:
                _STATE.messages_sent += 1
        return res

    def set_webhook(
        self,
        url: str,
        secret_token: Optional[str] = None,
        drop_pending_updates: bool = False,
    ) -> Dict[str, Any]:
        """Configura a URL de Webhook do bot na API do Telegram."""
        payload: Dict[str, Any] = {
            "url": url.strip(),
            "drop_pending_updates": drop_pending_updates,
        }
        if secret_token:
            payload["secret_token"] = secret_token
        return self._request_json("POST", "setWebhook", payload=payload)

    def delete_webhook(self, drop_pending_updates: bool = False) -> Dict[str, Any]:
        """Remove a configuracao de Webhook do bot para habilitar Long Polling."""
        payload: Dict[str, Any] = {"drop_pending_updates": drop_pending_updates}
        return self._request_json("POST", "deleteWebhook", payload=payload)


_DEFAULT_CLIENT: Optional[TelegramBotClient] = None


def get_telegram_bot_client() -> TelegramBotClient:
    """Retorna a instancia padrao do cliente TelegramBotClient."""
    global _DEFAULT_CLIENT
    if _DEFAULT_CLIENT is None:
        _DEFAULT_CLIENT = TelegramBotClient()
    return _DEFAULT_CLIENT


def get_me(token: Optional[str] = None) -> Dict[str, Any]:
    """Atalho funcional para validar o token e retornar dados do bot."""
    client = TelegramBotClient(token=token) if token is not None else get_telegram_bot_client()
    return client.get_me()


def get_updates(
    offset: Optional[int] = None,
    timeout: int = 30,
    token: Optional[str] = None,
) -> Dict[str, Any]:
    """Atalho funcional para buscar novas mensagens via Long Polling."""
    client = TelegramBotClient(token=token) if token is not None else get_telegram_bot_client()
    return client.get_updates(offset=offset, timeout=timeout)


def send_message(
    chat_id: int | str,
    text: str,
    parse_mode: Optional[str] = "Markdown",
    token: Optional[str] = None,
) -> Dict[str, Any]:
    """Atalho funcional para enviar mensagens para o cliente no Telegram."""
    client = TelegramBotClient(token=token) if token is not None else get_telegram_bot_client()
    return client.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)


def set_webhook(url: str, token: Optional[str] = None) -> Dict[str, Any]:
    """Atalho funcional para configurar o webhook no Telegram."""
    client = TelegramBotClient(token=token) if token is not None else get_telegram_bot_client()
    return client.set_webhook(url=url)


def delete_webhook(
    drop_pending_updates: bool = False,
    token: Optional[str] = None,
) -> Dict[str, Any]:
    """Atalho funcional para remover o webhook no Telegram."""
    client = TelegramBotClient(token=token) if token is not None else get_telegram_bot_client()
    return client.delete_webhook(drop_pending_updates=drop_pending_updates)


def _extract_message_fields(update_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Extrai chat_id, user_id, text, username, first_name e metadados de um update do Telegram."""
    if not isinstance(update_dict, dict):
        return {
            "update_id": None,
            "message_id": None,
            "chat_id": 0,
            "user_id": "telegram_unknown",
            "username": "",
            "first_name": "Cliente",
            "text": "",
            "has_message": False,
        }

    update_id = update_dict.get("update_id")
    msg = (
        update_dict.get("message")
        or update_dict.get("edited_message")
        or update_dict.get("channel_post")
    )

    if isinstance(msg, dict):
        chat_obj = msg.get("chat") if isinstance(msg.get("chat"), dict) else {}
        from_obj = msg.get("from") if isinstance(msg.get("from"), dict) else {}

        chat_id = chat_obj.get("id", update_dict.get("chat_id", 0))
        user_id = from_obj.get("id", chat_id if chat_id is not None else "telegram_user")
        username = str(from_obj.get("username") or chat_obj.get("username") or "").strip()
        first_name = str(from_obj.get("first_name") or chat_obj.get("first_name") or "Cliente").strip()
        text = str(msg.get("text") or msg.get("caption") or "").strip()
        message_id = msg.get("message_id")
        return {
            "update_id": update_id,
            "message_id": message_id,
            "chat_id": chat_id,
            "user_id": str(user_id),
            "username": username,
            "first_name": first_name,
            "text": text,
            "has_message": True,
        }

    # Suporte a payload simplificado de teste (ex.: {"chat_id": 123, "text": "/start"})
    if "text" in update_dict or "pergunta" in update_dict or "message" in update_dict:
        raw_text = (
            update_dict.get("text")
            if isinstance(update_dict.get("text"), str)
            else update_dict.get("pergunta") or update_dict.get("message") or ""
        )
        chat_id = update_dict.get("chat_id", 0)
        user_id = update_dict.get("user_id", chat_id or "telegram_user")
        return {
            "update_id": update_id,
            "message_id": update_dict.get("message_id"),
            "chat_id": chat_id,
            "user_id": str(user_id),
            "username": str(update_dict.get("username", "")).strip(),
            "first_name": str(update_dict.get("first_name", "Cliente")).strip(),
            "text": str(raw_text).strip(),
            "has_message": True,
        }

    return {
        "update_id": update_id,
        "message_id": None,
        "chat_id": 0,
        "user_id": "telegram_unknown",
        "username": "",
        "first_name": "Cliente",
        "text": "",
        "has_message": False,
    }


def _normalize_command(text: str) -> Optional[str]:
    """Identifica se o texto inicia por um comando do Telegram (ex.: /start ou /start@ArenaBot)."""
    stripped = (text or "").strip()
    if not stripped.startswith("/"):
        return None
    first_token = stripped.split()[0].lower()
    cmd = first_token.split("@")[0]
    return cmd


def _build_synthetic_trace(
    pergunta_sanitizada: str,
    chat_id: int | str,
    user_id: str,
    username: str,
    first_name: str,
    update_id: Optional[int],
    resposta: str,
    comportamento: str,
    fontes: List[str],
    modo_geracao: str,
    motivo_guardrail: str,
    pii_detectado: bool = False,
    tipos_pii: Optional[List[str]] = None,
    latencia_ms: int = 1,
    status: str = "SUCCESS",
    persist_trace: bool = True,
) -> PipelineTrace:
    """Constroi e opcionalmente persiste um PipelineTrace auditavel para comandos, bloqueio de PII ou fallback."""
    now_iso = datetime.now(timezone.utc).astimezone().isoformat()
    short_uid = uuid.uuid4().hex[:8]
    req_id = f"tg_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{short_uid}"
    tr_id = f"tr_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{short_uid}"

    request_payload: Dict[str, Any] = {
        "request_id": req_id,
        "chat_id": chat_id,
        "user_id": str(user_id),
        "username": username,
        "first_name": first_name,
        "update_id": update_id,
        "pergunta": pergunta_sanitizada,
        "timestamp": now_iso,
        "canal": "telegram",
    }

    guardrails_payload: Dict[str, Any] = {
        "pii_detectado": pii_detectado,
        "tipos_pii": list(tipos_pii or []),
        "direct_injection_detectado": False,
        "fora_de_escopo": False,
        "topico_ausente_detectado": False,
        "nome_topico_ausente": "",
        "premissa_cuidadosa_detectada": False,
        "parafrase_detectada": False,
        "comportamento_sugerido": comportamento,
        "motivo_classificacao": motivo_guardrail,
    }

    filtragem_payload: Dict[str, Any] = {
        "modo_busca": modo_geracao,
        "documentos_obsoletos_descartados": ["03b-reservas-v1-obsoleta.md"],
        "chunks_bloqueados_seguranca": ["08-faq-atendimento#aviso-interno"],
        "chunks_recuperados": list(fontes),
        "chunks_detalhados": [],
        "divergencia_detectada": False,
        "resolucao_divergencia": "",
        "expansoes_aplicadas": [],
    }

    memoria_payload: Dict[str, Any] = {
        "regras_acionadas": [],
        "detalhes": [],
    }

    resposta_payload: Dict[str, Any] = {
        "resposta": resposta,
        "resposta_texto": resposta,
        "comportamento": comportamento,
        "categoria_comportamento": comportamento,
        "fontes": list(fontes),
        "fontes_citadas": list(fontes),
        "divergencia_detectada": False,
        "conflito_detectado": False,
        "resolucao_conflito": "",
        "regras_memoria_aplicadas": [],
        "modo_geracao": modo_geracao,
        "erros_api": [],
    }

    geracao_payload: Dict[str, Any] = {
        "modelo": modo_geracao,
        "temperatura": 0.0,
        "prompt_xml_tags": [
            "<regras_sistema>",
            "<memoria_erros>",
            "<documentos_recuperados>",
        ],
        "prompt_construido": "",
        "output": resposta_payload,
    }

    trace = PipelineTrace(
        trace_id=tr_id,
        request=request_payload,
        guardrails_entrada=guardrails_payload,
        filtragem=filtragem_payload,
        memoria=memoria_payload,
        geracao=geracao_payload,
        resposta_final=resposta_payload,
        latencia_ms=max(1, latencia_ms),
        status=status,
        timestamp=now_iso,
    )

    if persist_trace:
        try:
            get_pipeline()._append_trace(trace)
        except Exception:
            pass

    return trace


def process_telegram_update(
    update_dict: Dict[str, Any],
    bot_client: Optional[TelegramBotClient] = None,
    send_reply: bool = False,
    persist_trace: bool = True,
) -> Dict[str, Any]:
    """Processa um update do Telegram (comandos, guardrail de PII, pipeline RAG e fallback seguro)."""
    start_ns = time.perf_counter_ns()
    now_iso = datetime.now(timezone.utc).astimezone().isoformat()

    fields = _extract_message_fields(update_dict)
    update_id = fields["update_id"]
    chat_id = fields["chat_id"]
    user_id = fields["user_id"]
    username = fields["username"]
    first_name = fields["first_name"]
    raw_text = fields["text"]

    with _STATE.lock:
        if update_id is not None:
            _STATE.last_update_id = update_id
        if fields["has_message"] and raw_text:
            _STATE.messages_received += 1
            _STATE.last_message_at = now_iso

    if not fields["has_message"] or not raw_text:
        return {
            "ok": True,
            "status": "ignored",
            "reason": "Update sem mensagem de texto.",
            "update_id": update_id,
            "chat_id": chat_id,
            "user_id": user_id,
            "username": username,
            "first_name": first_name,
            "comando": None,
            "pii_detectado": False,
            "tipos_pii": [],
            "resposta": "",
            "text": "",
            "comportamento": "ignorar",
            "fontes": [],
            "divergencia_detectada": False,
            "latencia_ms": 0,
            "trace_id": None,
            "trace": None,
        }

    try:
        # 1. Guardrail de Seguranca no Telegram: Bloqueio imediato de CPF, Cartao ou Senhas sem salvar dados sensiveis
        sanitized_text, has_pii, pii_types = detect_and_redact_telegram_pii(raw_text)
        if has_pii:
            with _STATE.lock:
                _STATE.pii_blocked_count += 1

            elapsed_ms = max(1, int((time.perf_counter_ns() - start_ns) / 1_000_000))
            pii_sources = ["04-pagamento", "09-privacidade-e-lgpd"]
            trace = _build_synthetic_trace(
                pergunta_sanitizada=sanitized_text,
                chat_id=chat_id,
                user_id=user_id,
                username=username,
                first_name=first_name,
                update_id=update_id,
                resposta=PII_SECURITY_RESPONSE,
                comportamento="manter_regras",
                fontes=pii_sources,
                modo_geracao="telegram_pii_guardrail",
                motivo_guardrail=(
                    f"Dados sensiveis detectados e bloqueados no Telegram ({', '.join(pii_types)}). "
                    "Orientacao emitida conforme 04-pagamento.md e 09-privacidade-e-lgpd.md sem persistir PII."
                ),
                pii_detectado=True,
                tipos_pii=pii_types,
                latencia_ms=elapsed_ms,
                persist_trace=persist_trace,
            )

            delivery = None
            if send_reply:
                client = bot_client or get_telegram_bot_client()
                if client.token:
                    delivery = client.send_message(chat_id=chat_id, text=PII_SECURITY_RESPONSE)

            return {
                "ok": True,
                "status": "blocked_pii",
                "update_id": update_id,
                "chat_id": chat_id,
                "user_id": user_id,
                "username": username,
                "first_name": first_name,
                "comando": None,
                "pergunta_sanitizada": sanitized_text,
                "pii_detectado": True,
                "tipos_pii": pii_types,
                "resposta": PII_SECURITY_RESPONSE,
                "text": PII_SECURITY_RESPONSE,
                "comportamento": "manter_regras",
                "fontes": pii_sources,
                "divergencia_detectada": False,
                "latencia_ms": elapsed_ms,
                "trace_id": trace.trace_id,
                "trace": trace.to_dict(),
                "telegram_delivery": delivery,
            }

        # 2. Suporte a Comandos do Telegram (/start, /ajuda, /quadras, /contato)
        cmd = _normalize_command(raw_text)
        if cmd and cmd in COMMAND_RESPONSES:
            with _STATE.lock:
                _STATE.commands_processed += 1

            cmd_reply, cmd_sources = COMMAND_RESPONSES[cmd]
            elapsed_ms = max(1, int((time.perf_counter_ns() - start_ns) / 1_000_000))
            trace = _build_synthetic_trace(
                pergunta_sanitizada=raw_text,
                chat_id=chat_id,
                user_id=user_id,
                username=username,
                first_name=first_name,
                update_id=update_id,
                resposta=cmd_reply,
                comportamento="responder",
                fontes=cmd_sources,
                modo_geracao="telegram_command_handler",
                motivo_guardrail=f"Comando oficial do Telegram processado ({cmd}).",
                pii_detectado=False,
                tipos_pii=[],
                latencia_ms=elapsed_ms,
                persist_trace=persist_trace,
            )

            delivery = None
            if send_reply:
                client = bot_client or get_telegram_bot_client()
                if client.token:
                    delivery = client.send_message(chat_id=chat_id, text=cmd_reply)

            return {
                "ok": True,
                "status": "command",
                "update_id": update_id,
                "chat_id": chat_id,
                "user_id": user_id,
                "username": username,
                "first_name": first_name,
                "comando": cmd,
                "pergunta_sanitizada": raw_text,
                "pii_detectado": False,
                "tipos_pii": [],
                "resposta": cmd_reply,
                "text": cmd_reply,
                "comportamento": "responder",
                "fontes": cmd_sources,
                "divergencia_detectada": False,
                "latencia_ms": elapsed_ms,
                "trace_id": trace.trace_id,
                "trace": trace.to_dict(),
                "telegram_delivery": delivery,
            }

        # 3. Mensagens livres de texto -> Pipeline principal com canal='telegram' e metadados de sessao
        pipeline = get_pipeline()
        short_uid = uuid.uuid4().hex[:8]
        req_id = f"tg_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{short_uid}"

        trace = pipeline.run(
            pergunta=raw_text,
            chat_id=chat_id,
            user_id=str(user_id),
            canal="telegram",
            request_id=req_id,
            persist_trace=False,
        )
        # Enriquece os metadados de sessao do Telegram no request do trace antes de persistir
        trace.request["username"] = username
        trace.request["first_name"] = first_name
        trace.request["update_id"] = update_id
        if persist_trace:
            pipeline._append_trace(trace)

        delivery = None
        if send_reply:
            client = bot_client or get_telegram_bot_client()
            if client.token:
                delivery = client.send_message(chat_id=chat_id, text=trace.resposta)

        return {
            "ok": True,
            "status": "processed",
            "update_id": update_id,
            "chat_id": chat_id,
            "user_id": user_id,
            "username": username,
            "first_name": first_name,
            "comando": None,
            "pergunta_sanitizada": trace.request.get("pergunta", sanitized_text),
            "pii_detectado": bool(trace.guardrails_entrada.get("pii_detectado", False)),
            "tipos_pii": list(trace.guardrails_entrada.get("tipos_pii", [])),
            "resposta": trace.resposta,
            "text": trace.resposta,
            "comportamento": trace.comportamento,
            "fontes": trace.fontes,
            "divergencia_detectada": trace.divergencia_detectada,
            "latencia_ms": trace.latencia_ms,
            "trace_id": trace.trace_id,
            "trace": trace.to_dict(),
            "telegram_delivery": delivery,
        }

    except Exception as exc:
        with _STATE.lock:
            _STATE.errors_count += 1

        elapsed_ms = max(1, int((time.perf_counter_ns() - start_ns) / 1_000_000))
        safe_q, _, _ = detect_and_redact_telegram_pii(raw_text)
        trace = _build_synthetic_trace(
            pergunta_sanitizada=safe_q,
            chat_id=chat_id,
            user_id=user_id,
            username=username,
            first_name=first_name,
            update_id=update_id,
            resposta=ERROR_FALLBACK_RESPONSE,
            comportamento="responder",
            fontes=["01-sobre-a-arena"],
            modo_geracao="telegram_error_fallback",
            motivo_guardrail=f"Fallback amigavel acionado por excecao interna: {exc}",
            pii_detectado=False,
            tipos_pii=[],
            latencia_ms=elapsed_ms,
            status="FALLBACK_ERROR",
            persist_trace=persist_trace,
        )

        delivery = None
        if send_reply:
            try:
                client = bot_client or get_telegram_bot_client()
                if client.token:
                    delivery = client.send_message(chat_id=chat_id, text=ERROR_FALLBACK_RESPONSE)
            except Exception:
                pass

        return {
            "ok": False,
            "status": "error_fallback",
            "error": str(exc),
            "update_id": update_id,
            "chat_id": chat_id,
            "user_id": user_id,
            "username": username,
            "first_name": first_name,
            "comando": None,
            "pergunta_sanitizada": safe_q,
            "pii_detectado": False,
            "tipos_pii": [],
            "resposta": ERROR_FALLBACK_RESPONSE,
            "text": ERROR_FALLBACK_RESPONSE,
            "comportamento": "responder",
            "fontes": ["01-sobre-a-arena"],
            "divergencia_detectada": False,
            "latencia_ms": elapsed_ms,
            "trace_id": trace.trace_id,
            "trace": trace.to_dict(),
            "telegram_delivery": delivery,
        }


class TelegramPollingWorker:
    """Worker em background thread para Long Polling da API do Telegram com reconexao e parada limpa."""

    def __init__(
        self,
        bot_client: Optional[TelegramBotClient] = None,
        poll_timeout: int = 15,
        retry_delay: float = 2.0,
        update_handler: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
    ) -> None:
        self.bot_client: TelegramBotClient = bot_client or get_telegram_bot_client()
        self.poll_timeout: int = poll_timeout
        self.retry_delay: float = retry_delay
        self.update_handler = update_handler
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.last_offset: Optional[int] = None
        self.updates_processed: int = 0
        self.errors_count: int = 0

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stop_event.is_set()

    def start(self) -> bool:
        """Inicia o loop de Long Polling em uma background thread."""
        if self.is_running:
            return True
        if not self.bot_client.token:
            return False

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._polling_loop,
            name="ArenaTelegramPollingWorker",
            daemon=True,
        )
        with _STATE.lock:
            _STATE.polling_active = True
        self._thread.start()
        return True

    def stop(self, timeout: float = 5.0) -> None:
        """Sinaliza parada limpa do loop de polling e aguarda o encerramento da thread."""
        self._stop_event.set()
        with _STATE.lock:
            _STATE.polling_active = False
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._thread = None

    def _polling_loop(self) -> None:
        """Loop interno de Long Polling com tratamento de reconexao e backoff."""
        try:
            self.bot_client.get_me()
        except Exception:
            pass

        while not self._stop_event.is_set():
            try:
                resp = self.bot_client.get_updates(
                    offset=self.last_offset,
                    timeout=self.poll_timeout,
                )
                if not isinstance(resp, dict) or not resp.get("ok"):
                    self.errors_count += 1
                    self._stop_event.wait(self.retry_delay)
                    continue

                updates = resp.get("result", [])
                if not isinstance(updates, list):
                    continue

                for upd in updates:
                    if self._stop_event.is_set():
                        break
                    if not isinstance(upd, dict):
                        continue
                    upd_id = upd.get("update_id")
                    if isinstance(upd_id, int):
                        self.last_offset = upd_id + 1

                    if self.update_handler is not None:
                        self.update_handler(upd)
                    else:
                        process_telegram_update(
                            upd,
                            bot_client=self.bot_client,
                            send_reply=True,
                        )
                    self.updates_processed += 1

            except Exception:
                self.errors_count += 1
                with _STATE.lock:
                    _STATE.errors_count += 1
                self._stop_event.wait(self.retry_delay)

        with _STATE.lock:
            _STATE.polling_active = False


def record_webhook_call() -> None:
    """Incrementa o contador de chamadas recebidas no endpoint /api/telegram/webhook."""
    with _STATE.lock:
        _STATE.webhook_calls += 1


def get_telegram_status(verify_token_online: bool = False) -> Dict[str, Any]:
    """Retorna o status consolidado da integracao com o Telegram (token, username e contadores)."""
    token = get_telegram_bot_token()
    token_present = bool(token)

    if token_present and verify_token_online and _STATE.bot_username is None:
        try:
            get_me(token=token)
        except Exception:
            pass

    with _STATE.lock:
        bot_username = _STATE.bot_username or (
            "arena_vila_nova_bot" if token_present else None
        )
        return {
            "status": "configured" if token_present else "missing_token",
            "token_present": token_present,
            "token_configured": token_present,
            "bot_username": bot_username,
            "bot_info": _STATE.bot_info,
            "polling_active": _STATE.polling_active,
            "messages_received": _STATE.messages_received,
            "messages_sent": _STATE.messages_sent,
            "commands_processed": _STATE.commands_processed,
            "pii_blocked_count": _STATE.pii_blocked_count,
            "webhook_calls": _STATE.webhook_calls,
            "errors_count": _STATE.errors_count,
            "last_update_id": _STATE.last_update_id,
            "last_message_at": _STATE.last_message_at,
            "counters": {
                "messages_received": _STATE.messages_received,
                "messages_sent": _STATE.messages_sent,
                "commands_processed": _STATE.commands_processed,
                "pii_blocked_count": _STATE.pii_blocked_count,
                "webhook_calls": _STATE.webhook_calls,
                "errors_count": _STATE.errors_count,
            },
        }

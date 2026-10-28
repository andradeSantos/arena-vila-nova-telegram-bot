"""Configuracoes centrais e caminhos de arquivos do Backend da Arena Vila Nova."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Tuple


PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
ENV_FILE_PATH: Path = PROJECT_ROOT / ".env"


def load_dotenv_file(env_path: Path = ENV_FILE_PATH) -> Dict[str, str]:
    """Carrega variaveis de um arquivo .env usando apenas a biblioteca padrao."""
    loaded: Dict[str, str] = {}
    if not env_path.exists() or not env_path.is_file():
        return loaded

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value
        loaded[key] = value
    return loaded


load_dotenv_file()

# Diretorios e arquivos do projeto (.agent e raiz)
AGENT_DIR: Path = PROJECT_ROOT / ".agent"
CONTEXT_DIR: Path = AGENT_DIR / "context"

# Caminho principal da base de conhecimento (.agent/context/base-de-conhecimento/base-de-conhecimento)
_KB_NESTED_DIR: Path = CONTEXT_DIR / "base-de-conhecimento" / "base-de-conhecimento"
_KB_TOP_DIR: Path = CONTEXT_DIR / "base-de-conhecimento"
KB_DIR: Path = _KB_NESTED_DIR if _KB_NESTED_DIR.exists() else _KB_TOP_DIR
BASE_COMPLETA_PATH: Path = CONTEXT_DIR / "base-completa.md"

# Skills e Diretrizes
BOOT_SKILL_PATH: Path = AGENT_DIR / "skills" / "boot" / "SKILL.md"
DIRETRIZES_PATH: Path = AGENT_DIR / "skills" / "boot" / "diretrizes-do-assistente.md"
EVAL_SKILL_PATH: Path = AGENT_DIR / "skills" / "eval-diagnostics" / "SKILL.md"

# Memoria e Logs
MEMORY_DIR: Path = AGENT_DIR / "memory"
ERROR_LEDGER_PATH: Path = MEMORY_DIR / "error-ledger.json"
TRACES_PATH: Path = MEMORY_DIR / "traces.jsonl"
LAST_EVAL_JSON_PATH: Path = MEMORY_DIR / "last-eval-report.json"
LAST_EVAL_MD_PATH: Path = MEMORY_DIR / "last-eval-report.md"

# Bateria de testes publicos
PERGUNTAS_PUBLICAS_JSON_PATH: Path = PROJECT_ROOT / "perguntas-publicas.json"
PERGUNTAS_PUBLICAS_MD_PATH: Path = PROJECT_ROOT / "perguntas-publicas.md"


def get_gemini_api_key() -> str:
    """Retorna a chave GEMINI_API_KEY do ambiente (ou string vazia se ausente)."""
    return os.environ.get("GEMINI_API_KEY", "").strip()


def get_telegram_bot_token() -> str:
    """Retorna o token TELEGRAM_BOT_TOKEN do ambiente."""
    return os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()


def get_port() -> int:
    """Retorna a porta configurada para o servidor HTTP (padrao 8000)."""
    raw_port = os.environ.get("PORT", "8000").strip()
    try:
        return int(raw_port)
    except ValueError:
        return 8000


DEFAULT_GEMINI_MODEL: str = "gemini-3.1-flash-lite-preview"
GEMINI_MODEL_CANDIDATES: Tuple[str, ...] = (
    "gemini-3.1-flash-lite-preview",
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
)
_raw_gemini_model: str = os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip()
GEMINI_MODEL: str = (
    DEFAULT_GEMINI_MODEL
    if not _raw_gemini_model or _raw_gemini_model == "gemini-2.5-flash"
    else _raw_gemini_model
)

DEFAULT_GEMINI_EMBEDDING_MODEL: str = "gemini-embedding-001"
_raw_embedding_model: str = os.environ.get(
    "GEMINI_EMBEDDING_MODEL", DEFAULT_GEMINI_EMBEDDING_MODEL
).strip()
GEMINI_EMBEDDING_MODEL: str = (
    DEFAULT_GEMINI_EMBEDDING_MODEL
    if not _raw_embedding_model or _raw_embedding_model == "text-embedding-004"
    else _raw_embedding_model
)

# Pesos formais de precedencia documental conforme Especificacao 02
PRECEDENCE_WEIGHTS: Dict[str, float] = {
    "politica": 1.0,
    "comercial": 0.9,
    "regras": 0.9,
    "institucional": 0.9,
    "atendimento": 0.6,
}

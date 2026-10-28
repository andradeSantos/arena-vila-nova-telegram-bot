"""Gerenciador de Memoria Preventiva (.agent/memory/error-ledger.json)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from backend.app.config import ERROR_LEDGER_PATH
from backend.app.rag.indexer import normalize_text


class MemoryManager:
    """Gerencia a leitura e gravacao de lições aprendidas no error-ledger.json."""

    def __init__(self, ledger_path: Path = ERROR_LEDGER_PATH) -> None:
        self.ledger_path: Path = ledger_path

    def load_ledger(self) -> Dict[str, Any]:
        """Carrega o conteudo completo de error-ledger.json."""
        if not self.ledger_path.exists():
            return {
                "version": "1.0.0",
                "updated_at": datetime.now(timezone.utc).astimezone().isoformat(),
                "entries": [],
            }
        try:
            raw = self.ledger_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("Formato invalido no error-ledger.json")
            data.setdefault("version", "1.0.0")
            data.setdefault("entries", [])
            return data
        except Exception:
            return {
                "version": "1.0.0",
                "updated_at": datetime.now(timezone.utc).astimezone().isoformat(),
                "entries": [],
            }

    def save_ledger(self, data: Dict[str, Any]) -> None:
        """Persiste o dicionario atualizado em error-ledger.json."""
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        data["updated_at"] = datetime.now(timezone.utc).astimezone().isoformat()
        self.ledger_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def list_entries(self, only_active: bool = False) -> List[Dict[str, Any]]:
        """Retorna todas as entradas de memoria (ou apenas as ativas)."""
        entries = self.load_ledger().get("entries", [])
        if only_active:
            return [e for e in entries if e.get("ativo", True)]
        return list(entries)

    def get_relevant_memories(
        self,
        query: str,
        retrieved_sources: Sequence[str],
    ) -> List[Dict[str, Any]]:
        """Seleciona as regras corretivas ativas relevantes para a pergunta e fontes atuais."""
        active_entries = self.list_entries(only_active=True)
        norm_q = normalize_text(query)
        norm_sources = {normalize_text(src) for src in retrieved_sources}
        norm_source_stems = {normalize_text(Path(src).stem) for src in retrieved_sources}

        relevant: List[Dict[str, Any]] = []
        for entry in active_entries:
            entry_id = entry.get("id", "")
            affected = entry.get("fontes_afetadas", [])
            affected_norms = {normalize_text(a) for a in affected}
            affected_stems = {normalize_text(Path(a).stem) for a in affected}

            source_match = bool(
                norm_sources.intersection(affected_norms)
                or norm_source_stems.intersection(affected_stems)
            )

            # Gatilhos especificos por memoria conhecida ou palavras-chave da pergunta_gatilho
            trigger_text = normalize_text(entry.get("pergunta_gatilho", ""))
            keyword_match = False

            if entry_id in ("MEM-001", "MEM-004"):
                if any(
                    kw in norm_q
                    for kw in ("cancelar", "cancelamento", "desmarcar", "sinal", "reagendar", "remarcar")
                ):
                    keyword_match = True
            elif entry_id == "MEM-002":
                if any(
                    kw in norm_q
                    for kw in ("desconto", "cupom", "arena50", "promocao", "faq", "aviso")
                ):
                    keyword_match = True
            elif entry_id == "MEM-003":
                if any(
                    kw in norm_q
                    for kw in ("multa", "nao aparecer", "faltar", "nao comparecer", "penalidade")
                ):
                    keyword_match = True
            else:
                q_words = [w for w in norm_q.split() if len(w) > 3]
                if any(w in trigger_text for w in q_words):
                    keyword_match = True

            if source_match or keyword_match:
                relevant.append(entry)

        return relevant

    def record_error(
        self,
        pergunta_gatilho: str,
        etapa_falha: str,
        causa_raiz: str,
        regra_corretiva: str,
        fontes_afetadas: Optional[List[str]] = None,
        ativo: bool = True,
        entry_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Registra uma nova falha ou atualiza uma entrada existente no error-ledger.json."""
        ledger = self.load_ledger()
        entries: List[Dict[str, Any]] = ledger.get("entries", [])

        # Evita duplicar se a mesma pergunta_gatilho e etapa_falha ja existirem
        for existing in entries:
            if (
                existing.get("id") == entry_id
                or (
                    normalize_text(existing.get("pergunta_gatilho", "")) == normalize_text(pergunta_gatilho)
                    and existing.get("etapa_falha") == etapa_falha
                )
            ):
                existing["causa_raiz"] = causa_raiz
                existing["regra_corretiva"] = regra_corretiva
                existing["fontes_afetadas"] = list(fontes_afetadas or existing.get("fontes_afetadas", []))
                existing["ativo"] = ativo
                self.save_ledger(ledger)
                return existing

        if not entry_id:
            next_num = len(entries) + 1
            existing_ids = {e.get("id") for e in entries}
            while f"MEM-{next_num:03d}" in existing_ids:
                next_num += 1
            entry_id = f"MEM-{next_num:03d}"

        new_entry: Dict[str, Any] = {
            "id": entry_id,
            "pergunta_gatilho": pergunta_gatilho,
            "etapa_falha": etapa_falha,
            "causa_raiz": causa_raiz,
            "regra_corretiva": regra_corretiva,
            "fontes_afetadas": list(fontes_afetadas or []),
            "ativo": ativo,
        }
        entries.append(new_entry)
        ledger["entries"] = entries
        self.save_ledger(ledger)
        return new_entry


_GLOBAL_MEMORY_MANAGER: Optional[MemoryManager] = None


def get_memory_manager() -> MemoryManager:
    """Retorna a instancia singleton do MemoryManager."""
    global _GLOBAL_MEMORY_MANAGER
    if _GLOBAL_MEMORY_MANAGER is None:
        _GLOBAL_MEMORY_MANAGER = MemoryManager()
    return _GLOBAL_MEMORY_MANAGER

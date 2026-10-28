"""Orquestrador do Pipeline de 5 Estagios (TELEGRAM/CLI -> APLICACAO -> FILTRAGEM -> GERACAO -> RESPOSTA)."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.app.agent.generator import AgentGenerator, GenerationResult
from backend.app.agent.guardrails import GuardrailResult, evaluate_input_guardrails
from backend.app.config import TRACES_PATH
from backend.app.memory.manager import MemoryManager, get_memory_manager
from backend.app.rag.retriever import HybridRetriever, RetrievalResult, get_retriever


@dataclass
class PipelineTrace:
    """Rastro auditavel completo de ponta a ponta (Especificacao 01)."""

    trace_id: str
    request: Dict[str, Any]
    guardrails_entrada: Dict[str, Any]
    filtragem: Dict[str, Any]
    memoria: Dict[str, Any]
    geracao: Dict[str, Any]
    resposta_final: Dict[str, Any]
    latencia_ms: int
    status: str = "SUCCESS"
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).astimezone().isoformat()
    )

    @property
    def resposta(self) -> str:
        return self.resposta_final.get("resposta", "")

    @property
    def comportamento(self) -> str:
        return self.resposta_final.get("comportamento", "")

    @property
    def fontes(self) -> List[str]:
        return list(self.resposta_final.get("fontes", []))

    @property
    def divergencia_detectada(self) -> bool:
        return bool(self.resposta_final.get("divergencia_detectada", False))

    def to_dict(self) -> Dict[str, Any]:
        """Converte o trace para dicionario serializavel em JSON / JSONL."""
        return {
            "trace_id": self.trace_id,
            "timestamp": self.timestamp,
            "request": self.request,
            "guardrails_entrada": self.guardrails_entrada,
            "filtragem": self.filtragem,
            "memoria": self.memoria,
            "geracao": self.geracao,
            "resposta_final": self.resposta_final,
            "latencia_ms": self.latencia_ms,
            "status": self.status,
        }


class ArenaPipeline:
    """Pipeline principal do Assistente Virtual da Arena Vila Nova."""

    def __init__(
        self,
        retriever: Optional[HybridRetriever] = None,
        memory_manager: Optional[MemoryManager] = None,
        generator: Optional[AgentGenerator] = None,
        traces_path: Path = TRACES_PATH,
    ) -> None:
        self.retriever: HybridRetriever = retriever or get_retriever()
        self.memory_manager: MemoryManager = memory_manager or get_memory_manager()
        self.generator: AgentGenerator = generator or AgentGenerator()
        self.traces_path: Path = traces_path

    def run(
        self,
        pergunta: str,
        chat_id: int | str = 0,
        user_id: str = "cli_user",
        canal: str = "cli",
        request_id: Optional[str] = None,
        top_k: int = 5,
        persist_trace: bool = True,
    ) -> PipelineTrace:
        """Executa os 5 estagios do pipeline, mede latencia e grava o trace em traces.jsonl."""
        start_ns = time.perf_counter_ns()
        now_iso = datetime.now(timezone.utc).astimezone().isoformat()
        short_uid = uuid.uuid4().hex[:8]
        req_id = request_id or f"req_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{short_uid}"
        tr_id = f"tr_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{short_uid}"

        # Etapa 1: TELEGRAM / CLI (Normalizacao de Entrada)
        clean_question = " ".join((pergunta or "").strip().split())

        # Etapa 2: APLICACAO (Guardrails de Entrada e Redacao de PII)
        guardrail_res: GuardrailResult = evaluate_input_guardrails(clean_question)

        request_payload: Dict[str, Any] = {
            "request_id": req_id,
            "chat_id": chat_id,
            "user_id": user_id,
            "pergunta": guardrail_res.pergunta_sanitizada,
            "timestamp": now_iso,
            "canal": canal,
        }

        # Etapa 3: FILTRAGEM (Busca Hibrida RAG + Precedencia + Bloqueio de Obsoletos e Injection)
        retrieval_res: RetrievalResult = self.retriever.retrieve(
            query=guardrail_res.pergunta_sanitizada,
            top_k=top_k,
        )
        retrieved_sources = [c.arquivo_origem for c in retrieval_res.chunks]

        # Consulta de Memoria Preventiva (error-ledger.json)
        relevant_memories = self.memory_manager.get_relevant_memories(
            query=guardrail_res.pergunta_sanitizada,
            retrieved_sources=retrieved_sources,
        )

        # Etapa 4: GERACAO (Montagem do Prompt XML e Sintese Controlada)
        gen_res: GenerationResult = self.generator.generate(
            query=clean_question,
            retrieval=retrieval_res,
            guardrails=guardrail_res,
            memories=relevant_memories,
        )

        # Etapa 5: RESPOSTA (Formatacao final, telemetria e auditoria)
        elapsed_ms = max(1, int((time.perf_counter_ns() - start_ns) / 1_000_000))

        filtragem_payload: Dict[str, Any] = {
            "modo_busca": retrieval_res.modo_busca,
            "documentos_obsoletos_descartados": list(retrieval_res.documentos_obsoletos_descartados),
            "chunks_bloqueados_seguranca": list(retrieval_res.chunks_bloqueados_seguranca),
            "chunks_recuperados": [c.chunk_id for c in retrieval_res.chunks],
            "chunks_detalhados": [c.to_dict() for c in retrieval_res.chunks],
            "divergencia_detectada": retrieval_res.divergencia_detectada,
            "resolucao_divergencia": retrieval_res.resolucao_divergencia,
            "expansoes_aplicadas": list(retrieval_res.expansoes_aplicadas),
        }

        memoria_payload: Dict[str, Any] = {
            "regras_acionadas": [m.get("id", "") for m in relevant_memories],
            "detalhes": relevant_memories,
        }

        geracao_payload: Dict[str, Any] = {
            "modelo": gen_res.modo_geracao,
            "temperatura": 0.0,
            "prompt_xml_tags": [
                "<regras_sistema>",
                "<memoria_erros>",
                "<documentos_recuperados>",
            ],
            "prompt_construido": gen_res.prompt_construido,
            "output": gen_res.to_dict(),
        }

        resposta_payload: Dict[str, Any] = gen_res.to_dict()

        trace = PipelineTrace(
            trace_id=tr_id,
            request=request_payload,
            guardrails_entrada=guardrail_res.to_dict(),
            filtragem=filtragem_payload,
            memoria=memoria_payload,
            geracao=geracao_payload,
            resposta_final=resposta_payload,
            latencia_ms=elapsed_ms,
            status="SUCCESS",
            timestamp=now_iso,
        )

        if persist_trace:
            self._append_trace(trace)

        return trace

    def _append_trace(self, trace: PipelineTrace) -> None:
        """Adiciona uma linha JSONL em .agent/memory/traces.jsonl."""
        try:
            self.traces_path.parent.mkdir(parents=True, exist_ok=True)
            trace_dict = dict(trace.to_dict())
            # Mantem o arquivo traces.jsonl enxuto ocultando apenas a string gigante do prompt se necessario,
            # mas preservando todos os campos estruturados
            line = json.dumps(trace_dict, ensure_ascii=False)
            with self.traces_path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception:
            pass

    def read_recent_traces(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Le os ultimos traces gravados em .agent/memory/traces.jsonl."""
        if not self.traces_path.exists():
            return []
        try:
            lines = self.traces_path.read_text(encoding="utf-8").splitlines()
            parsed: List[Dict[str, Any]] = []
            for raw in lines[-limit:]:
                raw = raw.strip()
                if raw:
                    parsed.append(json.loads(raw))
            parsed.reverse()
            return parsed
        except Exception:
            return []


_GLOBAL_PIPELINE: Optional[ArenaPipeline] = None


def get_pipeline(force_rebuild: bool = False) -> ArenaPipeline:
    """Retorna a instancia singleton do ArenaPipeline."""
    global _GLOBAL_PIPELINE
    if _GLOBAL_PIPELINE is None or force_rebuild:
        _GLOBAL_PIPELINE = ArenaPipeline(
            retriever=get_retriever(force_rebuild=force_rebuild),
            memory_manager=get_memory_manager(),
        )
    return _GLOBAL_PIPELINE

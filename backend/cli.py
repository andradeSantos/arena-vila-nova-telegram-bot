"""Interface de Linha de Comando (CLI) com Raio-X das 5 Etapas do Pipeline."""

from __future__ import annotations

import argparse
import sys

from backend.app.agent.pipeline import PipelineTrace, get_pipeline


def print_pipeline_xray(trace: PipelineTrace) -> None:
    """Exibe no terminal o Raio-X detalhado das 5 etapas do pipeline."""
    print("\n" + "=" * 92)
    print(f" RAIO-X DO PIPELINE — ARENA VILA NOVA | Trace ID: {trace.trace_id}")
    print("=" * 92)

    # Etapa 1: Ingestao / Canal
    req = trace.request
    print(f"[1. CANAL / INGESTÃO] Canal: {req.get('canal')} | Request ID: {req.get('request_id')}")
    print(f"    Pergunta Normalizada: \"{req.get('pergunta')}\"")

    # Etapa 2: Aplicacao & Guardrails
    gr = trace.guardrails_entrada
    print("\n[2. APLICAÇÃO & GUARDRAILS DE ENTRADA]")
    print(
        f"    PII Detectado: {gr.get('pii_detectado')} | "
        f"Direct Injection: {gr.get('direct_injection_detectado')} | "
        f"Fora de Escopo: {gr.get('fora_de_escopo')}"
    )
    print(
        f"    Comportamento Sugerido: {gr.get('comportamento_sugerido')} "
        f"({gr.get('motivo_classificacao')})"
    )

    # Etapa 3: Filtragem RAG & Precedencia
    filt = trace.filtragem
    print("\n[3. FILTRAGEM RAG & PRECEDÊNCIA DE FONTES]")
    print(f"    Modo de Busca: {filt.get('modo_busca')}")
    print(f"    Documentos Obsoletos Descartados: {filt.get('documentos_obsoletos_descartados')}")
    print(f"    Chunks Bloqueados (Prompt Injection): {filt.get('chunks_bloqueados_seguranca')}")
    print(f"    Divergência Detectada (24h vs 12h): {filt.get('divergencia_detectada')}")
    if filt.get("divergencia_detectada"):
        print(f"    Resolução de Conflito: {filt.get('resolucao_divergencia')}")

    chunks_det = filt.get("chunks_detalhados", [])
    print(f"    Chunks Recuperados (Top-{len(chunks_det)}):")
    for idx, ch in enumerate(chunks_det, start=1):
        meta = ch.get("metadados", {})
        print(
            f"      #{idx} [{ch.get('chunk_id')}] (area={meta.get('area')}, v={meta.get('versao')}, "
            f"peso={ch.get('peso_precedencia')}, bm25={ch.get('score_bm25')}, "
            f"sem={ch.get('score_semantico')}, score_final={ch.get('score_final')})"
        )

    # Etapa 4: Memoria Preventiva & Geracao
    mem = trace.memoria
    ger = trace.geracao
    print("\n[4. MEMÓRIA PREVENTIVA & GERAÇÃO CONTROLADA]")
    print(f"    Regras do Error-Ledger Acionadas: {mem.get('regras_acionadas')}")
    print(
        f"    Motor de Geração: {ger.get('modelo')} | "
        f"Tags XML de Isolamento: {ger.get('prompt_xml_tags')}"
    )

    # Etapa 5: Resposta Final
    resp = trace.resposta_final
    print("\n[5. RESPOSTA FINAL AO CLIENTE]")
    print(
        f"    Categoria de Comportamento: {resp.get('comportamento')} | "
        f"Fontes Citadas: {resp.get('fontes')} | "
        f"Latência Total: {trace.latencia_ms} ms"
    )
    print("-" * 92)
    print(f"BOT: {resp.get('resposta')}")
    print("=" * 92 + "\n")


def run_interactive_cli() -> int:
    """Inicia o modo interativo de conversa no terminal."""
    pipeline = get_pipeline()
    print("=" * 92)
    print(" ASSISTENTE VIRTUAL DA ARENA VILA NOVA — CLI INTERATIVA (Digite 'sair' para encerrar)")
    print("=" * 92)

    while True:
        try:
            user_input = input("VOCÊ > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nEncerrando CLI da Arena Vila Nova.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("sair", "exit", "quit", "/quit"):
            print("Encerrando CLI da Arena Vila Nova.")
            break

        trace = pipeline.run(pergunta=user_input, canal="cli")
        print_pipeline_xray(trace)

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="CLI de atendimento e diagnostico Raio-X da Arena Vila Nova."
    )
    parser.add_argument(
        "--ask",
        type=str,
        default=None,
        help="Executa uma pergunta unica exibindo o Raio-X das 5 etapas do pipeline.",
    )
    args = parser.parse_args()

    if args.ask is not None:
        pipeline = get_pipeline()
        trace = pipeline.run(pergunta=args.ask, canal="cli")
        print_pipeline_xray(trace)
        return 0

    return run_interactive_cli()


if __name__ == "__main__":
    sys.exit(main())

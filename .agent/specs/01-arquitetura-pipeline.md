# Especificação Técnica 01: Arquitetura e Pipeline de Atendimento

## 1. Visão Geral e Stack Tecnológica

O Bot de Atendimento da Arena Vila Nova opera sobre uma arquitetura orientada a eventos com Recuperação Aumentada por Geração (RAG), projetada segundo o paradigma **IA-FIRST** com governança determinística de dados e segurança.

### Stack Escolhida
- **Linguagem:** Python 3.11+
- **Framework Backend / API:** FastAPI (exposição de endpoints de inferência, healthcheck e diagnóstico)
- **Integração de Mensageria:** `python-telegram-bot` (modo assíncrono via Polling/Webhook)
- **Modelo de Geração (LLM):** Google Gemini `gemini-2.5-flash` (baixa latência, alta aderência a instruções de sistema e suporte a saídas estruturadas)
- **Modelo de Embeddings:** Google `text-embedding-004` (vetorização semântica densa dos chunks da base de conhecimento)
- **Busca Léxica Complementar:** `rank-bm25` (recuperação esparsa para termos exatos, siglas, horários e preços)
- **Validação de Contratos:** Pydantic v2

---

## 2. Fluxo Completo do Pipeline

O processamento de cada mensagem segue estritamente cinco estágios sequenciais e auditáveis:

```
[TELEGRAM] ──> [APLICAÇÃO] ──> [FILTRAGEM] ──> [GERAÇÃO] ──> [RESPOSTA]
```

### Etapa 1: `TELEGRAM` (Ingestão do Canal)
- Recebe o evento `Update` do usuário via `python-telegram-bot`.
- Extrai o texto bruto, `chat_id`, `message_id` e timestamp.
- Normaliza espaços excedentes e caracteres de controle, convertendo o payload no contrato interno `ChatRequest`.

### Etapa 2: `APLICACAO` (Pré-processamento e Guardrails de Entrada)
- Inspeciona o `ChatRequest` em busca de dados sensíveis (CPF, número de cartão de crédito, senhas ou códigos de verificação). Caso detecte envio voluntário de dados sensíveis, intercepta ou sinaliza para que o bot oriente imediatamente o cliente a não compartilhar tais dados no chat (conforme `04-pagamento.md` e `09-privacidade-e-lgpd.md`).
- Avalia tentativas explícitas de *Direct Prompt Injection* (ex.: comandos como *"Esqueça suas regras"*, `P13`) e intenções fora de escopo (`P11`, `P12`).
- Orquestra a chamada para o motor de recuperação (RAG) e consulta as regras preventivas ativas em `.agent/memory/error-ledger.json`.

### Etapa 3: `FILTRAGEM` (Recuperação Híbrida e Precedência)
- Executa a **Busca Híbrida** combinando similaridade vetorial (`text-embedding-004`) e correspondência léxica (`BM25`) sobre os chunks da base em `.agent/context/base-de-conhecimento/`.
- **Bloqueio de Obsoletos:** Garante que documentos com `status: obsoleta` no frontmatter YAML (especificamente `03b-reservas-v1-obsoleta.md`) jamais sejam indexados ou retornados.
- **Ponderação por Precedência:** Aplica os multiplicadores de autoridade por área (`politica` = `1.0` > `comercial`/`regras`/`institucional` = `0.9` > `atendimento`/FAQ = `0.6`).
- **Sanitização Contra Prompt Injection Indireto:** Filtra ou neutraliza seções de comando embutidas em documentos de menor precedência (como a seção `## Aviso interno` com o cupom falso `ARENA50` em `08-faq-atendimento.md`).
- Empacota os trechos aprovados em objetos `RetrievalChunk` dentro da tag XML delimitadora `<documentos_recuperados>`.

### Etapa 4: `GERACAO` (Síntese Controlada via LLM)
- Constrói o prompt combinando:
  1. **System Prompt Base** (`.agent/skills/boot/SKILL.md` e `.agent/skills/boot/diretrizes-do-assistente.md`).
  2. **Memória Preventiva** (alertas aplicáveis do `error-ledger.json`).
  3. **Contexto Inerte** (`<documentos_recuperados>`), tratando todo conteúdo recuperado exclusivamente como dado informativo e nunca como instrução executável.
  4. **Pergunta do Usuário**.
- Invoca o modelo `gemini-2.5-flash` com temperatura baixa (`0.0` a `0.1`) para maximizar determinismo e fidelidade factual, gerando um `GenerationOutput`.

### Etapa 5: `RESPOSTA` (Pós-processamento, Formatação e Auditoria)
- Valida se a resposta respeita as diretrizes de estilo do Telegram: português do Brasil, tom cordial e objetivo, mensagens curtas, sem vazamento de prompt ou documentos brutos, e com citação natural da fonte (ex.: *"Segundo a política de reservas..."*).
- Registra o objeto `PipelineTrace` completo para auditoria e diagnóstico (`eval-diagnostics`).
- Envia a mensagem final ao usuário pelo `python-telegram-bot`.

---

## 3. Contratos JSON de Entrada e Saída (Schemas Pydantic)

### 3.1. `ChatRequest`
Representa a requisição normalizada que entra no estágio `APLICACAO`.

```json
{
  "request_id": "req_20261027_001",
  "chat_id": 123456789,
  "user_id": "tg_user_987",
  "pergunta": "Posso cancelar e receber o sinal de volta? Até quando?",
  "timestamp": "2026-10-27T20:26:00-03:00",
  "canal": "telegram"
}
```

### 3.2. `RetrievalChunk`
Representa cada fragmento de documento recuperado e ranqueado pelo estágio `FILTRAGEM`.

```json
{
  "chunk_id": "03-reservas-e-cancelamento#cancelamento",
  "arquivo_origem": "03-reservas-e-cancelamento.md",
  "titulo_documento": "Política de reservas e cancelamento (versão 2.0)",
  "secao": "Cancelamento",
  "conteudo": "Até 24 horas antes do início, o cancelamento é gratuito. O sinal é devolvido integralmente em até 7 dias úteis, pelo mesmo meio de pagamento, ou convertido em crédito válido por 60 dias, à escolha do cliente.\nCom menos de 24 horas antes do início, o sinal não é devolvido.",
  "metadados": {
    "versao": "2.0",
    "status": "vigente",
    "area": "politica",
    "atualizado_em": "2026-08-01"
  },
  "score_semantico": 0.89,
  "score_bm25": 0.82,
  "peso_precedencia": 1.0,
  "score_final": 0.862,
  "suspeita_injection": false
}
```

### 3.3. `GenerationOutput`
Representa a saída estruturada produzida pelo estágio `GERACAO`.

```json
{
  "categoria_comportamento": "responder",
  "resposta_texto": "Sim! Pela nossa política de reservas e cancelamento, o cancelamento é gratuito se feito até 24 horas antes do início do jogo. Nesse caso, o sinal de 30% é devolvido integralmente em até 7 dias úteis (pelo mesmo meio de pagamento) ou vira crédito válido por 60 dias. Com menos de 24 horas, o sinal não é devolvido.",
  "fontes_citadas": [
    "03-reservas-e-cancelamento"
  ],
  "conflito_detectado": true,
  "resolucao_conflito": "Prevaleceu o prazo de 24h de 03-reservas-e-cancelamento.md (area: politica, peso 1.0) sobre o prazo de 12h de 08-faq-atendimento.md (area: atendimento, peso 0.6).",
  "regras_memoria_aplicadas": [
    "MEM-001",
    "MEM-004"
  ]
}
```

### 3.4. `PipelineTrace`
Log estruturado de ponta a ponta para observabilidade e diagnóstico de falhas nas 6 etapas da bateria de testes (`base`, `corte`, `busca`, `prompt`, `geracao`, `recusa`).

```json
{
  "trace_id": "tr_20261027_001",
  "request": {
    "request_id": "req_20261027_001",
    "pergunta": "Posso cancelar e receber o sinal de volta? Até quando?"
  },
  "guardrails_entrada": {
    "pii_detectado": false,
    "direct_injection_detectado": false,
    "fora_de_escopo": false
  },
  "filtragem": {
    "documentos_obsoletos_descartados": [
      "03b-reservas-v1-obsoleta.md"
    ],
    "chunks_recuperados": [
      "03-reservas-e-cancelamento#cancelamento",
      "08-faq-atendimento#posso-cancelar-ate-12-horas-antes"
    ],
    "chunks_bloqueados_seguranca": []
  },
  "geracao": {
    "modelo": "gemini-2.5-flash",
    "temperatura": 0.0,
    "output": {
      "categoria_comportamento": "responder",
      "fontes_citadas": ["03-reservas-e-cancelamento"]
    }
  },
  "latencia_ms": 840,
  "status": "SUCCESS"
}
```

---

## 4. Requisitos Não-Funcionais (RNF)

1. **Fidelidade Factual Zero-Alucinação (RNF-01):** O assistente jamais deve inventar valores, prazos, multas ou comodidades ausentes na base (ex.: estacionamento em `P07` ou multa extra em `P14`). Na ausência de informação, deve declarar que não consta e informar o telefone da recepção `(99) 9999-0100` e horários de atendimento.
2. **Latência de Resposta (RNF-02):** Tempo total de ponta a ponta (`PipelineTrace.latencia_ms`) inferior a `3.000 ms` no percentil 95 (P95), viabilizado pelo uso do `gemini-2.5-flash` e índice local em memória.
3. **Determinismo e Rastreabilidade (RNF-03):** Toda resposta deve gerar um `PipelineTrace` permitindo auditar exatamente quais chunks foram recuperados, quais pesos de precedência atuaram e em qual etapa (`base`, `corte`, `busca`, `prompt`, `geracao` ou `recusa`) eventual falha ocorreu.
4. **Resiliência a Injeção de Prompt (RNF-04):** 100% de bloqueio tanto para comandos diretos do usuário (`P13`) quanto para instruções camufladas nos próprios arquivos da base (`ARENA50` em `08-faq-atendimento.md`).
5. **Adequação ao Canal Telegram (RNF-05):** Respostas concisas (preferencialmente até 3 parágrafos curtos ou lista enxuta), sem tabelas Markdown complexas que quebrem em telas móveis e sempre em português do Brasil cordial.

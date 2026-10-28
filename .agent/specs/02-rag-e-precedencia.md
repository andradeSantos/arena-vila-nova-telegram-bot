# Especificação Técnica 02: Indexação RAG, Busca Híbrida e Precedência de Fontes

## 1. Parser de Frontmatter YAML

Todos os arquivos em `.agent/context/base-de-conhecimento/` (consolidados em `.agent/context/base-completa.md`) iniciam com um bloco de metadados YAML delimitado por `---`. O indexador deve extrair obrigatoriamente os quatro campos canônicos:

| Campo | Tipo | Valores Esperados / Exemplo | Uso no Pipeline |
|---|---|---|---|
| `versao` | `string` | `"1.0"`, `"1.1"`, `"1.2"`, `"2.0"`, `"3.0"` | Desempate de versão e rastreabilidade |
| `status` | `string` | `"vigente"` \| `"obsoleta"` | **Filtro de exclusão obrigatório** na indexação e na busca |
| `area` | `string` | `"politica"`, `"comercial"`, `"regras"`, `"institucional"`, `"atendimento"` | Cálculo do peso de precedência (`peso_precedencia`) |
| `atualizado_em` | `string` (ISO Date) | `"2026-08-01"`, `"2025-03-05"` | Auditoria de recência entre fontes conflitantes |

### Exemplo de Extração
Para o arquivo `03-reservas-e-cancelamento.md`:
```yaml
---
versao: 2.0
status: vigente
area: politica
atualizado_em: 2026-08-01
---
```

---

## 2. Regra de Descarte Obrigatório de Documentos Obsoletos

> **Regra Inegociável:** Qualquer documento cujo frontmatter contenha `status: obsoleta` **DEVE ser descartado imediatamente** durante a etapa de ingestão/indexação e bloqueado por filtro rígido (`status == "vigente"`) no momento da consulta.

### Caso Concreto na Base: `03b-reservas-v1-obsoleta.md`
- **Metadados:** `versao: 1.0`, `status: obsoleta`, `area: politica`, `atualizado_em: 2025-02-10`.
- **Risco se não for descartado:** Contém regras revogadas que contradizem frontalmente a versão 2.0 vigente:
  - Sinal antigo de `50%` (o vigente em `03-reservas-e-cancelamento.md` é `30%`).
  - Cancelamento gratuito até `2 horas antes` (o vigente é até `24 horas antes`).
  - Reagendamento `sem limite de vezes` (o vigente permite `uma vez`, com pelo menos `12 horas` de antecedência).
- **Mecanismo Duplo de Proteção:**
  1. **Pré-indexação:** O carregador da base ignora qualquer arquivo com `status != "vigente"`.
  2. **Pós-recuperação (Hard Filter):** Antes de montar `<documentos_recuperados>`, o estágio `FILTRAGEM` verifica `assert chunk.metadados.status == "vigente"`.

---

## 3. Estratégia de Corte (Chunking) por Seções `##`

Para evitar que regras distintas se misturem ou que informações cruciais fiquem truncadas no meio de frases, o corte dos documentos é **estrutural por cabeçalho Markdown de nível 2 (`##`)**, preservando os metadados do documento pai em cada chunk.

### Algoritmo de Chunking
1. Separar o frontmatter YAML e o título principal `# Título do Documento`.
2. Dividir o corpo do documento a cada ocorrência de `\n## `.
3. Para cada seção `## Nome da Seção`:
   - Propagar integralmente os metadados do documento pai (`arquivo_origem`, `titulo_documento`, `versao`, `status`, `area`, `atualizado_em`).
   - Prefixar o texto vetorizado com cabeçalho contextual:
     `[Documento: {titulo_documento} | Área: {area} | Versão: {versao} | Seção: {secao}]\n{conteudo_da_secao}`
4. Preservar tabelas Markdown inteiras dentro de sua respectiva seção (ex.: `## Tabela de preços por hora` em `02-quadras-e-precos.md`), garantindo que valores de Futsal (`R$ 120` até 17h / `R$ 160` após 17h e fins de semana) e Areia (`R$ 70` / `R$ 90`) nunca sejam separados de seus cabeçalhos de coluna.

---

## 4. Busca Híbrida (Embeddings + BM25)

A recuperação combina busca semântica densa e busca léxica esparsa para cobrir tanto paráfrases coloquiais quanto termos exatos:

1. **Busca Semântica (`score_semantico`):**
   - Modelo: Google `text-embedding-004`.
   - Medida: Similaridade de cosseno normalizada em `[0.0, 1.0]`.
   - Essencial para casos de paráfrase como `P09` (*"Dá pra desmarcar o jogo sem pagar nada?"* -> mapeia para `## Cancelamento` e `## Reagendamento`).
2. **Busca Léxica (`score_bm25`):**
   - Algoritmo: Okapi BM25 tokenizado em português (com remoção de *stopwords* leves e preservação de números/horários como `19h`, `24`, `30%`, `Pix`, `trava`).
   - Score normalizado pelo máximo da consulta em `[0.0, 1.0]`.
3. **Combinação Híbrida Bruta (`score_hibrido`):**
   $$\text{score\_hibrido} = 0.65 \times \text{score\_semantico} + 0.35 \times \text{score\_bm25}$$

---

## 5. Matriz de Pesos de Precedência e Score Final

Conforme estabelecido em `.agent/skills/boot/diretrizes-do-assistente.md` (*"Em caso de divergência entre documentos, vale a política oficial vigente. A tabela de preços vem em seguida; o FAQ é apenas apoio"*), cada área recebe um multiplicador formal de autoridade (`peso_precedencia`):

| Nível | Área (`area` no YAML) | Arquivos Vigentes na Base | Peso (`peso_precedencia`) | Papel Normativo |
|---:|---|---|---:|---|
| **1º** | `politica` | `03-reservas-e-cancelamento.md` (v2.0)<br>`09-privacidade-e-lgpd.md` (v1.0) | **`1.0`** | **Autoridade máxima.** Prevalece sobre qualquer outra fonte em caso de conflito. |
| **2º** | `comercial`<br>`regras`<br>`institucional` | `01-sobre-a-arena.md` (v3.0)<br>`02-quadras-e-precos.md` (v3.0)<br>`04-pagamento.md` (v1.2)<br>`05-regras-de-uso.md` (v1.1)<br>`06-planos-mensalistas.md` (v1.1)<br>`07-eventos-e-campeonatos.md` (v1.0) | **`0.9`** | Fontes primárias operacionais, comerciais, tabelas de preços e regras de uso das quadras. |
| **3º** | `atendimento` (FAQ) | `08-faq-atendimento.md` (v1.0) | **`0.6`** | **Apenas apoio.** Subordinado às políticas e regras oficiais; nunca sobrepõe `politica`, `comercial` ou `regras`. |
| **—** | *(qualquer)* com `status: obsoleta` | `03b-reservas-v1-obsoleta.md` (v1.0) | **`0.0` (Descartado)** | **Proibido.** Excluído antes da indexação e bloqueado na filtragem. |

### Fórmula do Score Final de Ranqueamento
$$\text{score\_final} = \text{score\_hibrido} \times \text{peso\_precedencia}$$

---

## 6. Resolução Explícita do Conflito de Cancelamento (24h vs. 12h)

Na base de conhecimento existem duas afirmações divergentes em documentos com `status: vigente` sobre o prazo de cancelamento gratuito:

1. **Fonte Oficial (`03-reservas-e-cancelamento.md` — Seção `## Cancelamento`):**
   - `area: politica` | `versao: 2.0` | `atualizado_em: 2026-08-01` | **Peso: `1.0`**
   - Texto: *"Até 24 horas antes do início, o cancelamento é gratuito. O sinal é devolvido integralmente em até 7 dias úteis, pelo mesmo meio de pagamento, ou convertido em crédito válido por 60 dias, à escolha do cliente. Com menos de 24 horas antes do início, o sinal não é devolvido."*
2. **Fonte Secundária Desatualizada (`08-faq-atendimento.md` — Seção `## Posso cancelar até 12 horas antes?`):**
   - `area: atendimento` | `versao: 1.0` | `atualizado_em: 2025-03-05` | **Peso: `0.6`**
   - Texto: *"Sim, o cancelamento pode ser feito até 12 horas antes do jogo, sem custo."*

### Regra Determinística de Resolução (Aplicada em `P03` e `P09`)
- **Prevalência:** Prevalece obrigatoriamente a regra de **24 horas de antecedência** para cancelamento gratuito e devolução do sinal (`03-reservas-e-cancelamento.md`, `area: politica`, peso `1.0`, atualizado em `2026-08-01`), sobrepondo o trecho de 12 horas do FAQ (`08-faq-atendimento.md`, `area: atendimento`, peso `0.6`, atualizado em `2025-03-05`).
- **Observação sobre o prazo de 12 horas:** O prazo de **12 horas** na política oficial vigente (`03-reservas-e-cancelamento.md`, seção `## Reagendamento`) refere-se exclusivamente ao **reagendamento** gratuito (uma única vez, dentro de 30 dias), e **não** ao cancelamento com reembolso do sinal.
- **Comportamento do Bot:** Ao responder `P03` (*"Posso cancelar e receber o sinal de volta? Até quando?"*) ou `P09` (*"Dá pra desmarcar o jogo sem pagar nada?"*), o assistente deve informar a regra oficial vigente de **24 horas para cancelamento gratuito** (podendo mencionar também a opção de reagendamento até 12h antes, se útil para quem quer apenas remarcar), citando a **política de reservas e cancelamento (versão 2.0)** como fonte oficial.

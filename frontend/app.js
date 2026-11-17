/**
 * Arena Vila Nova — Frontend SPA (Observabilidade 5 Estágios, Testes P01-P16, Memória IA-FIRST & Monitor Telegram)
 * Consome as rotas REST: /api/chat, /api/eval/run, /api/logs, /api/memory, /api/telegram/status, /api/kb/chunks
 */

(function () {
  "use strict";

  const state = {
    theme: localStorage.getItem("arena_theme") || "dark",
    activeTab: "tab-playground",
    kbData: null,
    memoryEntries: [],
    recentLogs: [],
    lastEvalReport: null,
    currentTrace: null,
    telegramTimer: null,
  };

  /* ========================================================================
     UTILITARIOS DE FORMATACAO E ESCAPE HTML
     ======================================================================== */

  function escapeHtml(value) {
    if (value === null || value === undefined) return "";
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function formatBehaviorBadge(cat) {
    const clean = String(cat || "responder").trim();
    return `<span class="badge badge-cat-${escapeHtml(clean)}">${escapeHtml(clean)}</span>`;
  }

  function formatStatusBadge(status) {
    const upper = String(status || "").toUpperCase();
    if (upper === "PASS" || upper === "SUCCESS" || upper === "OK") {
      return `<span class="badge badge-pass">${escapeHtml(upper)}</span>`;
    }
    if (upper === "FAIL" || upper === "ERROR") {
      return `<span class="badge badge-fail">${escapeHtml(upper)}</span>`;
    }
    return `<span class="badge badge-warn">${escapeHtml(status || "INFO")}</span>`;
  }

  function formatTimestamp(isoStr) {
    if (!isoStr) return "--";
    try {
      const dt = new Date(isoStr);
      if (isNaN(dt.getTime())) return String(isoStr);
      return dt.toLocaleTimeString("pt-BR", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
    } catch (_e) {
      return String(isoStr);
    }
  }

  async function apiFetch(path, options = {}) {
    const headers = Object.assign(
      { "Content-Type": "application/json", Accept: "application/json" },
      options.headers || {}
    );
    const response = await fetch(path, Object.assign({}, options, { headers }));
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.error || `Erro HTTP ${response.status} em ${path}`);
    }
    return data;
  }

  /* ========================================================================
     TEMA ESCURO / CLARO E NAVEGACAO POR 4 ABAS
     ======================================================================== */

  function applyTheme(theme) {
    state.theme = theme === "light" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", state.theme);
    localStorage.setItem("arena_theme", state.theme);

    const iconEl = document.getElementById("theme-toggle-icon");
    const labelEl = document.getElementById("theme-toggle-label");
    if (iconEl && labelEl) {
      if (state.theme === "dark") {
        iconEl.textContent = "☀️";
        labelEl.textContent = "Tema Claro";
      } else {
        iconEl.textContent = "🌙";
        labelEl.textContent = "Tema Escuro";
      }
    }
  }

  function switchTab(tabId) {
    state.activeTab = tabId;
    document.querySelectorAll(".tab-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.getAttribute("data-tab") === tabId);
    });
    document.querySelectorAll(".tab-panel").forEach((panel) => {
      panel.classList.toggle("active", panel.id === tabId);
    });

    if (tabId === "tab-memory") {
      loadMemoryLedger();
    } else if (tabId === "tab-telegram") {
      refreshTelegramMonitor();
    }
  }

  /* ========================================================================
     CABECALHO DE STATUS E BASE DE CONHECIMENTO (/api/kb/chunks & /api/telegram/status)
     ======================================================================== */

  async function loadKnowledgeBaseChunks() {
    try {
      const data = await apiFetch("/api/kb/chunks");
      state.kbData = data;

      const dotEl = document.getElementById("backend-status-dot");
      const textEl = document.getElementById("backend-status-text");
      if (dotEl && textEl) {
        dotEl.className = "status-dot online";
        textEl.textContent = "Backend: Online";
      }

      const kbText = document.getElementById("kb-status-text");
      if (kbText) {
        kbText.textContent = `KB: ${data.total_active_chunks || 0} chunks vigentes`;
      }

      const activeStat = document.getElementById("kb-stat-active");
      const obsoleteStat = document.getElementById("kb-stat-obsolete");
      const blockedStat = document.getElementById("kb-stat-blocked");

      if (activeStat) activeStat.textContent = `${data.total_active_chunks || 0} seções ativas`;
      if (obsoleteStat) {
        const obsNames = (data.discarded_obsolete_docs || []).map((d) => d.arquivo_origem);
        obsoleteStat.textContent = obsNames.length ? obsNames.join(", ") : "Nenhum";
      }
      if (blockedStat) {
        const blkIds = (data.blocked_injection_chunks || []).map((c) => c.chunk_id);
        blockedStat.textContent = blkIds.length ? blkIds.join(", ") : "Nenhum";
      }

      renderKbChunksList("");
    } catch (err) {
      const dotEl = document.getElementById("backend-status-dot");
      const textEl = document.getElementById("backend-status-text");
      if (dotEl && textEl) {
        dotEl.className = "status-dot offline";
        textEl.textContent = "Backend: Offline";
      }
      console.error("Erro ao carregar /api/kb/chunks:", err);
    }
  }

  function renderKbChunksList(filterTerm) {
    const listEl = document.getElementById("kb-chunks-list");
    if (!listEl || !state.kbData) return;

    const term = String(filterTerm || "").toLowerCase().trim();
    const activeChunks = state.kbData.chunks || [];
    const blockedChunks = state.kbData.blocked_injection_chunks || [];
    const allChunks = [...blockedChunks, ...activeChunks];

    const filtered = allChunks.filter((ch) => {
      if (!term) return true;
      const hay = `${ch.chunk_id} ${ch.arquivo_origem} ${ch.secao} ${ch.conteudo}`.toLowerCase();
      return hay.includes(term);
    });

    if (!filtered.length) {
      listEl.innerHTML = `<p class="empty-stage-hint">Nenhum chunk encontrado para o filtro "${escapeHtml(term)}".</p>`;
      return;
    }

    listEl.innerHTML = filtered
      .map((ch) => {
        const isBlocked = Boolean(ch.suspeita_injection);
        const area = (ch.metadados && ch.metadados.area) || "geral";
        const versao = (ch.metadados && ch.metadados.versao) || "1.0";
        return `
          <div class="kb-chunk-item ${isBlocked ? "blocked" : ""}">
            <div class="kb-chunk-head">
              <strong><code>${escapeHtml(ch.chunk_id)}</code></strong>
              <div>
                ${
                  isBlocked
                    ? `<span class="badge badge-fail">BLOQUEADO (INJECTION)</span>`
                    : `<span class="badge badge-pass">VIGENTE v${escapeHtml(versao)}</span>`
                }
                <span class="badge badge-neutral">área: ${escapeHtml(area)} (peso ${escapeHtml(ch.peso_precedencia)})</span>
              </div>
            </div>
            ${
              isBlocked
                ? `<div class="divergence-banner">🛡️ <strong>Motivo do Bloqueio:</strong> ${escapeHtml(ch.motivo_bloqueio)}</div>`
                : ""
            }
            <div class="chunk-snippet">${escapeHtml(ch.conteudo)}</div>
          </div>
        `;
      })
      .join("");
  }

  /* ========================================================================
     ABA 1: PLAYGROUND & RAIO-X EM 5 ESTAGIOS (/api/chat)
     ======================================================================== */

  function appendChatBubble(role, text, meta = {}) {
    const container = document.getElementById("chat-messages");
    if (!container) return;

    const div = document.createElement("div");
    div.className = `message-bubble ${role === "user" ? "user" : "assistant"}`;

    if (role === "user") {
      div.innerHTML = `
        <div class="message-meta">
          <span class="sender-name">👤 Cliente / Auditor</span>
          <span>${formatTimestamp(new Date().toISOString())}</span>
        </div>
        <div class="message-text">${escapeHtml(text)}</div>
      `;
    } else {
      const fontesList = Array.isArray(meta.fontes) && meta.fontes.length
        ? meta.fontes.map((f) => `<code>${escapeHtml(f)}</code>`).join(", ")
        : "<em>nenhuma fonte citada</em>";
      const conflictHtml = meta.divergencia_detectada
        ? `<span class="badge badge-warn">⚠️ Divergência Resolvida (Política &gt; FAQ)</span>`
        : "";

      div.innerHTML = `
        <div class="message-meta">
          <span class="sender-name">🤖 Assistente Arena Vila Nova</span>
          <div>
            ${formatBehaviorBadge(meta.comportamento || "responder")}
            <span class="badge badge-neutral">${escapeHtml(meta.latencia_ms || 1)} ms</span>
          </div>
        </div>
        <div class="message-text">${escapeHtml(text)}</div>
        <div class="message-footer">
          <span>📚 <strong>Fontes:</strong> ${fontesList}</span>
          ${conflictHtml}
        </div>
      `;
    }

    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
  }

  function renderRaioX(trace) {
    if (!trace || typeof trace !== "object") return;
    state.currentTrace = trace;

    const req = trace.request || {};
    const grd = trace.guardrails_entrada || {};
    const flt = trace.filtragem || {};
    const mem = trace.memoria || {};
    const gen = trace.geracao || {};
    const out = trace.resposta_final || {};

    const subtitleEl = document.getElementById("raiox-trace-subtitle");
    const latencyEl = document.getElementById("raiox-latency-badge");
    if (subtitleEl) {
      subtitleEl.innerHTML = `Trace ativo: <code>${escapeHtml(trace.trace_id || "tr_atual")}</code> • Canal: <code>${escapeHtml(req.canal || "api")}</code>`;
    }
    if (latencyEl) {
      latencyEl.textContent = `${trace.latencia_ms || 1} ms`;
    }

    // ESTAGIO 1: Ingestao & Normalizacao
    const s1Badge = document.getElementById("stage1-status-badge");
    const s1Body = document.getElementById("stage1-body");
    if (s1Badge) {
      s1Badge.className = "badge badge-pass";
      s1Badge.textContent = `Canal: ${req.canal || "api"}`;
    }
    if (s1Body) {
      s1Body.innerHTML = `
        <div class="kv-grid">
          <div class="kv-item">
            <span class="kv-label">Request ID</span>
            <span class="kv-val"><code>${escapeHtml(req.request_id || "--")}</code></span>
          </div>
          <div class="kv-item">
            <span class="kv-label">Usuário / Chat ID</span>
            <span class="kv-val">${escapeHtml(req.user_id || "api_user")} (chat: ${escapeHtml(req.chat_id ?? 0)})</span>
          </div>
          <div class="kv-item">
            <span class="kv-label">Horário</span>
            <span class="kv-val">${escapeHtml(formatTimestamp(req.timestamp || trace.timestamp))}</span>
          </div>
        </div>
        <div class="kv-item" style="margin-top:0.45rem;">
          <span class="kv-label">Pergunta Sanitizada</span>
          <span class="kv-val">${escapeHtml(req.pergunta || "")}</span>
        </div>
      `;
    }

    // ESTAGIO 2: Guardrails de Entrada
    const s2Badge = document.getElementById("stage2-status-badge");
    const s2Body = document.getElementById("stage2-body");
    const hasAlert = Boolean(
      grd.pii_detectado || grd.direct_injection_detectado || grd.fora_de_escopo
    );
    if (s2Badge) {
      s2Badge.className = hasAlert ? "badge badge-fail" : "badge badge-pass";
      s2Badge.textContent = hasAlert ? "Guardrail Acionado" : "Entrada Segura";
    }
    if (s2Body) {
      const piiStr = grd.pii_detectado
        ? `SIM (${(grd.tipos_pii || []).join(", ")})`
        : "Não detectado";
      s2Body.innerHTML = `
        <div class="kv-grid">
          <div class="kv-item">
            <span class="kv-label">PII / Dados Sensíveis (LGPD)</span>
            <span class="kv-val">${escapeHtml(piiStr)}</span>
          </div>
          <div class="kv-item">
            <span class="kv-label">Direct Prompt Injection</span>
            <span class="kv-val">${grd.direct_injection_detectado ? "🚨 BLOQUEADO" : "Não"}</span>
          </div>
          <div class="kv-item">
            <span class="kv-label">Fora de Escopo / Tópico Ausente</span>
            <span class="kv-val">${
              grd.fora_de_escopo
                ? "Fora de Escopo"
                : grd.topico_ausente_detectado
                ? `Ausente (${escapeHtml(grd.nome_topico_ausente)})`
                : "Escopo Válido"
            }</span>
          </div>
          <div class="kv-item">
            <span class="kv-label">Comportamento Sugerido</span>
            <span class="kv-val">${formatBehaviorBadge(grd.comportamento_sugerido || out.comportamento)}</span>
          </div>
        </div>
        <div class="kv-item" style="margin-top:0.45rem;">
          <span class="kv-label">Diagnóstico do Guardrail</span>
          <span class="kv-val">${escapeHtml(grd.motivo_classificacao || "Fluxo padrão autorizado.")}</span>
        </div>
      `;
    }

    // ESTAGIO 3: Chunks RAG com Precedencia e Scores
    const s3Badge = document.getElementById("stage3-status-badge");
    const s3Body = document.getElementById("stage3-body");
    const chunks = flt.chunks_detalhados || [];
    if (s3Badge) {
      s3Badge.className = flt.divergencia_detectada ? "badge badge-warn" : "badge badge-pass";
      s3Badge.textContent = `${chunks.length} chunks (${flt.modo_busca || "hibrido"})`;
    }
    if (s3Body) {
      const obsList = (flt.documentos_obsoletos_descartados || []).join(", ") || "03b-reservas-v1-obsoleta.md";
      const blkList = (flt.chunks_bloqueados_seguranca || []).join(", ") || "08-faq-atendimento#aviso-interno";
      const divBanner = flt.divergencia_detectada
        ? `<div class="divergence-banner">⚖️ <strong>Divergência Documental Detectada e Resolvida:</strong> ${escapeHtml(
            flt.resolucao_divergencia || "Prevaleceu 03-reservas-e-cancelamento.md (24h, peso 1.0) sobre 08-faq-atendimento.md (12h, peso 0.6)."
          )}</div>`
        : "";

      const chunksHtml = chunks.length
        ? chunks
            .map(
              (c, idx) => `
          <div class="chunk-rank-card">
            <div class="chunk-rank-top">
              <strong>#${idx + 1} <code>${escapeHtml(c.chunk_id)}</code></strong>
              <span class="badge badge-neutral">Precedência: ${escapeHtml(c.peso_precedencia)} (${escapeHtml(
                (c.metadados && c.metadados.area) || "area"
              )})</span>
            </div>
            <div class="chunk-scores-row">
              <span><strong>Score Final:</strong> ${escapeHtml(c.score_final)}</span>
              <span>• BM25: ${escapeHtml(c.score_bm25)}</span>
              <span>• Semântico: ${escapeHtml(c.score_semantico)}</span>
              <span>• Arquivo: <code>${escapeHtml(c.arquivo_origem)}</code></span>
            </div>
            <div class="chunk-snippet">${escapeHtml(c.conteudo)}</div>
          </div>
        `
            )
            .join("")
        : `<p class="empty-stage-hint">Nenhum chunk detalhado anexado (ex.: comando direto ou bloqueio prévio).</p>`;

      s3Body.innerHTML = `
        <div class="kv-grid">
          <div class="kv-item">
            <span class="kv-label">Obsoletos Descartados (status != vigente)</span>
            <span class="kv-val"><code>${escapeHtml(obsList)}</code></span>
          </div>
          <div class="kv-item">
            <span class="kv-label">Injections Bloqueados</span>
            <span class="kv-val"><code>${escapeHtml(blkList)}</code></span>
          </div>
        </div>
        ${divBanner}
        <div>${chunksHtml}</div>
      `;
    }

    // ESTAGIO 4: Memoria Preventiva (error-ledger.json)
    const s4Badge = document.getElementById("stage4-status-badge");
    const s4Body = document.getElementById("stage4-body");
    const memDetails = mem.detalhes || [];
    const memIds = mem.regras_acionadas || [];
    if (s4Badge) {
      s4Badge.className = memIds.length ? "badge badge-warn" : "badge badge-neutral";
      s4Badge.textContent = `${memIds.length} regra(s) ativa(s)`;
    }
    if (s4Body) {
      if (!memDetails.length) {
        s4Body.innerHTML = `<p class="empty-stage-hint">Nenhuma regra específica do error-ledger.json precisou ser acionada para esta consulta.</p>`;
      } else {
        s4Body.innerHTML = memDetails
          .map(
            (m) => `
          <div class="chunk-rank-card">
            <div class="chunk-rank-top">
              <strong>🧠 <code>${escapeHtml(m.id)}</code> — Etapa: <code>${escapeHtml(m.etapa_falha)}</code></strong>
              <span class="badge badge-pass">Injetada em &lt;memoria_erros&gt;</span>
            </div>
            <div style="font-size:0.78rem; margin-bottom:0.25rem;">
              <strong>Causa Raiz:</strong> ${escapeHtml(m.causa_raiz)}
            </div>
            <div class="chunk-snippet"><strong>Regra Corretiva:</strong> ${escapeHtml(m.regra_corretiva)}</div>
          </div>
        `
          )
          .join("");
      }
    }

    // ESTAGIO 5: Resposta Final & Isolamento XML
    const s5Badge = document.getElementById("stage5-status-badge");
    const s5Body = document.getElementById("stage5-body");
    if (s5Badge) {
      s5Badge.innerHTML = formatBehaviorBadge(out.comportamento || "responder");
    }
    if (s5Body) {
      const cited = (out.fontes || []).map((f) => `<code>${escapeHtml(f)}</code>`).join(", ") || "Nenhuma";
      const xmlTags = (gen.prompt_xml_tags || ["<regras_sistema>", "<memoria_erros>", "<documentos_recuperados>"])
        .map((t) => `<code>${escapeHtml(t)}</code>`)
        .join(" ");

      s5Body.innerHTML = `
        <div class="kv-grid">
          <div class="kv-item">
            <span class="kv-label">Comportamento Final</span>
            <span class="kv-val">${formatBehaviorBadge(out.comportamento || "responder")}</span>
          </div>
          <div class="kv-item">
            <span class="kv-label">Fontes Oficiais Citadas</span>
            <span class="kv-val">${cited}</span>
          </div>
          <div class="kv-item">
            <span class="kv-label">Motor de Geração</span>
            <span class="kv-val"><code>${escapeHtml(gen.modelo || out.modo_geracao || "deterministico")}</code></span>
          </div>
          <div class="kv-item">
            <span class="kv-label">Isolamento XML</span>
            <span class="kv-val">${xmlTags}</span>
          </div>
        </div>
        <div class="kv-item" style="margin-top:0.45rem;">
          <span class="kv-label">Texto Final Entregue ao Cliente</span>
          <div class="chunk-snippet" style="max-height:140px;">${escapeHtml(out.resposta || "")}</div>
        </div>
      `;
    }
  }

  async function sendPlaygroundQuestion(perguntaText) {
    const clean = String(perguntaText || "").trim();
    if (!clean) return;

    const inputEl = document.getElementById("chat-input");
    const submitBtn = document.getElementById("chat-submit-btn");
    if (inputEl) inputEl.value = "";
    if (submitBtn) submitBtn.disabled = true;

    appendChatBubble("user", clean);

    try {
      const res = await apiFetch("/api/chat", {
        method: "POST",
        body: JSON.stringify({
          pergunta: clean,
          canal: "playground_web",
          user_id: "auditor_web",
        }),
      });

      appendChatBubble("assistant", res.resposta, {
        comportamento: res.comportamento,
        fontes: res.fontes,
        divergencia_detectada: res.divergencia_detectada,
        latencia_ms: res.latencia_ms,
      });

      if (res.trace) {
        renderRaioX(res.trace);
      }
    } catch (err) {
      appendChatBubble("assistant", `Erro ao consultar /api/chat: ${err.message}`, {
        comportamento: "recusar",
        fontes: [],
        latencia_ms: 0,
      });
    } finally {
      if (submitBtn) submitBtn.disabled = false;
    }
  }

  /* ========================================================================
     ABA 2: BATERIA DE TESTES PUBLICA P01-P16 (/api/eval/run)
     ======================================================================== */

  async function runEvaluationSuite() {
    const runBtn = document.getElementById("run-eval-btn");
    const statusText = document.getElementById("eval-progress-status");
    const percentText = document.getElementById("eval-progress-percent");
    const progressBar = document.getElementById("eval-progress-bar");

    if (runBtn) runBtn.disabled = true;
    if (statusText) statusText.textContent = "Executando bateria P01 a P16 no pipeline RAG...";
    if (percentText) percentText.textContent = "35%";
    if (progressBar) progressBar.style.width = "35%";

    try {
      const report = await apiFetch("/api/eval/run", {
        method: "POST",
        body: JSON.stringify({}),
      });
      state.lastEvalReport = report;

      if (percentText) percentText.textContent = "100%";
      if (progressBar) progressBar.style.width = "100%";
      if (statusText) {
        statusText.textContent = `Execução concluída: ${report.passed}/${report.total} aprovadas (${report.pass_rate_percent}%)`;
      }

      renderEvaluationReport(report);
    } catch (err) {
      if (statusText) statusText.textContent = `Falha ao executar bateria: ${err.message}`;
      if (percentText) percentText.textContent = "Erro";
    } finally {
      if (runBtn) runBtn.disabled = false;
    }
  }

  function renderEvaluationReport(report) {
    if (!report) return;

    const totalEl = document.getElementById("eval-metric-total");
    const passedEl = document.getElementById("eval-metric-passed");
    const failedEl = document.getElementById("eval-metric-failed");
    const rateEl = document.getElementById("eval-metric-rate");
    const latEl = document.getElementById("eval-metric-latency");
    const tsEl = document.getElementById("eval-metric-timestamp");

    if (totalEl) totalEl.textContent = String(report.total || 16);
    if (passedEl) passedEl.textContent = String(report.passed ?? "--");
    if (failedEl) failedEl.textContent = String(report.failed ?? "--");
    if (rateEl) rateEl.textContent = `Taxa de acerto: ${report.pass_rate_percent ?? 0}%`;
    if (latEl) latEl.textContent = `${report.avg_latency_ms ?? 0} ms`;
    if (tsEl) tsEl.textContent = `Executado às ${formatTimestamp(report.executed_at)}`;

    const tbody = document.getElementById("eval-results-tbody");
    if (!tbody) return;

    const results = report.results || [];
    tbody.innerHTML = results
      .map((item) => {
        const expSources = (item.fontes_esperadas || []).map((f) => `<code>${escapeHtml(f)}</code>`).join(", ") || "<em>(nenhuma)</em>";
        const gotSources = (item.fontes_obtidas || []).map((f) => `<code>${escapeHtml(f)}</code>`).join(", ") || "<em>(nenhuma)</em>";
        const diagHtml = item.passed
          ? `<span class="badge badge-pass">✓ Pipeline Íntegro</span>`
          : `<span class="badge badge-fail">Etapa: ${escapeHtml(item.etapa_erro || "geracao")}</span>
             <div style="font-size:0.74rem; color:var(--text-muted); margin-top:0.2rem;">${escapeHtml(item.causa_raiz || "")}</div>`;

        return `
          <tr>
            <td><strong><code>${escapeHtml(item.id)}</code></strong></td>
            <td>
              <div style="font-weight:600; margin-bottom:0.25rem;">${escapeHtml(item.pergunta)}</div>
              <div class="chunk-snippet" style="max-height:68px;">${escapeHtml(item.resposta)}</div>
            </td>
            <td>
              <div><small>Esperado:</small> ${formatBehaviorBadge(item.categoria_esperada)}</div>
              <div style="margin-top:0.25rem;"><small>Obtido:</small> ${formatBehaviorBadge(item.categoria_obtida)}</div>
            </td>
            <td>
              <div><small>Esperadas:</small> ${expSources}</div>
              <div style="margin-top:0.25rem;"><small>Citadas:</small> ${gotSources}</div>
            </td>
            <td>${formatStatusBadge(item.status)}</td>
            <td>${diagHtml}</td>
            <td><code>${escapeHtml(item.latencia_ms)} ms</code></td>
            <td>
              <button type="button" class="btn btn-ghost btn-xs eval-replay-btn" data-question="${escapeHtml(item.pergunta)}">
                🔬 Auditar no Raio-X
              </button>
            </td>
          </tr>
        `;
      })
      .join("");

    tbody.querySelectorAll(".eval-replay-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const q = btn.getAttribute("data-question");
        switchTab("tab-playground");
        sendPlaygroundQuestion(q);
      });
    });
  }

  /* ========================================================================
     ABA 3: GESTAO DE MEMORIA IA-FIRST (/api/memory)
     ======================================================================== */

  async function loadMemoryLedger() {
    const tbody = document.getElementById("memory-tbody");
    try {
      const ledger = await apiFetch("/api/memory");
      state.memoryEntries = ledger.entries || [];
      renderMemoryTable(state.memoryEntries);
    } catch (err) {
      if (tbody) {
        tbody.innerHTML = `<tr><td colspan="7" class="empty-table-cell">Erro ao carregar /api/memory: ${escapeHtml(err.message)}</td></tr>`;
      }
    }
  }

  function renderMemoryTable(entries) {
    const tbody = document.getElementById("memory-tbody");
    if (!tbody) return;

    if (!entries.length) {
      tbody.innerHTML = `<tr><td colspan="7" class="empty-table-cell">Nenhuma regra cadastrada no error-ledger.json.</td></tr>`;
      return;
    }

    tbody.innerHTML = entries
      .map((entry, idx) => {
        const isAtivo = Boolean(entry.ativo !== false);
        const fontesHtml = (entry.fontes_afetadas || [])
          .map((f) => `<code>${escapeHtml(f)}</code>`)
          .join("<br/>") || "<em>Todas</em>";

        return `
          <tr>
            <td><strong><code>${escapeHtml(entry.id || `MEM-${idx + 1}`)}</code></strong></td>
            <td><span class="badge badge-warn">${escapeHtml(entry.etapa_falha || "geracao")}</span></td>
            <td>
              <div style="font-weight:700; margin-bottom:0.2rem;">"${escapeHtml(entry.pergunta_gatilho)}"</div>
              <div style="font-size:0.77rem; color:var(--text-muted);">${escapeHtml(entry.causa_raiz)}</div>
            </td>
            <td>
              <div class="chunk-snippet" style="max-height:95px;">${escapeHtml(entry.regra_corretiva)}</div>
            </td>
            <td>${fontesHtml}</td>
            <td>
              ${
                isAtivo
                  ? `<span class="badge badge-pass">ATIVA</span>`
                  : `<span class="badge badge-neutral">INATIVA</span>`
              }
            </td>
            <td>
              <button
                type="button"
                class="btn btn-ghost btn-xs memory-toggle-btn"
                data-index="${idx}"
              >
                ${isAtivo ? "⏸ Desativar" : "▶ Ativar"}
              </button>
            </td>
          </tr>
        `;
      })
      .join("");

    tbody.querySelectorAll(".memory-toggle-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const idx = Number(btn.getAttribute("data-index"));
        const targetEntry = state.memoryEntries[idx];
        if (!targetEntry) return;
        await toggleMemoryEntryStatus(targetEntry);
      });
    });
  }

  async function toggleMemoryEntryStatus(entry) {
    try {
      const nextStatus = !Boolean(entry.ativo !== false);
      await apiFetch("/api/memory", {
        method: "POST",
        body: JSON.stringify({
          id: entry.id,
          pergunta_gatilho: entry.pergunta_gatilho,
          etapa_falha: entry.etapa_falha,
          causa_raiz: entry.causa_raiz,
          regra_corretiva: entry.regra_corretiva,
          fontes_afetadas: entry.fontes_afetadas || [],
          ativo: nextStatus,
        }),
      });
      await loadMemoryLedger();
    } catch (err) {
      alert(`Erro ao alternar status da regra ${entry.id}: ${err.message}`);
    }
  }

  async function handleMemoryFormSubmit(evt) {
    evt.preventDefault();
    const perguntaEl = document.getElementById("mem-pergunta");
    const etapaEl = document.getElementById("mem-etapa");
    const fontesEl = document.getElementById("mem-fontes");
    const causaEl = document.getElementById("mem-causa");
    const regraEl = document.getElementById("mem-regra");
    const ativoEl = document.getElementById("mem-ativo");
    const feedbackEl = document.getElementById("memory-form-feedback");

    const fontesList = String(fontesEl ? fontesEl.value : "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);

    try {
      const res = await apiFetch("/api/memory", {
        method: "POST",
        body: JSON.stringify({
          pergunta_gatilho: perguntaEl ? perguntaEl.value.trim() : "",
          etapa_falha: etapaEl ? etapaEl.value : "busca",
          causa_raiz: causaEl ? causaEl.value.trim() : "",
          regra_corretiva: regraEl ? regraEl.value.trim() : "",
          fontes_afetadas: fontesList,
          ativo: ativoEl ? Boolean(ativoEl.checked) : true,
        }),
      });

      if (feedbackEl) {
        feedbackEl.className = "form-feedback success";
        feedbackEl.textContent = `Regra ${res.entry ? res.entry.id : ""} gravada com sucesso no error-ledger.json!`;
        feedbackEl.classList.remove("hidden");
      }

      if (perguntaEl) perguntaEl.value = "";
      if (causaEl) causaEl.value = "";
      if (regraEl) regraEl.value = "";
      if (fontesEl) fontesEl.value = "";

      await loadMemoryLedger();
    } catch (err) {
      if (feedbackEl) {
        feedbackEl.className = "form-feedback error";
        feedbackEl.textContent = `Erro ao salvar regra: ${err.message}`;
        feedbackEl.classList.remove("hidden");
      }
    }
  }

  /* ========================================================================
     ABA 4: MONITOR TELEGRAM LIVE (/api/telegram/status & /api/logs)
     ======================================================================== */

  async function refreshTelegramMonitor() {
    try {
      const [tgStatus, logsResp] = await Promise.all([
        apiFetch("/api/telegram/status"),
        apiFetch("/api/logs?limit=40"),
      ]);

      renderTelegramStatusHeaderAndCards(tgStatus);
      state.recentLogs = logsResp.logs || [];
      renderTelegramLiveFeed(state.recentLogs);

      if (!state.currentTrace && state.recentLogs.length > 0) {
        renderRaioX(state.recentLogs[0]);
      }
    } catch (err) {
      console.error("Erro ao atualizar Monitor Telegram:", err);
    }
  }

  function renderTelegramStatusHeaderAndCards(st) {
    const dotEl = document.getElementById("telegram-status-dot");
    const textEl = document.getElementById("telegram-status-text");

    const username = st.bot_username ? `@${st.bot_username}` : "@arena_vila_nova_bot";
    const isConfigured = Boolean(st.token_present || st.token_configured);

    if (dotEl && textEl) {
      dotEl.className = isConfigured ? "status-dot online" : "status-dot warn";
      textEl.textContent = isConfigured
        ? `Telegram: ${username} (Online)`
        : "Telegram: Modo Local / Webhook";
    }

    const userBox = document.getElementById("tg-bot-username");
    const tokenFoot = document.getElementById("tg-token-state");
    const connBox = document.getElementById("tg-conn-status");
    const pollFoot = document.getElementById("tg-polling-state");
    const msgBox = document.getElementById("tg-messages-count");
    const cmdFoot = document.getElementById("tg-commands-count");
    const piiBox = document.getElementById("tg-pii-count");
    const lastFoot = document.getElementById("tg-last-activity");

    if (userBox) userBox.textContent = username;
    if (tokenFoot) {
      tokenFoot.textContent = isConfigured
        ? "Token TELEGRAM_BOT_TOKEN configurado"
        : "Token ausente (.env) • Simulador Webhook ativo";
    }
    if (connBox) {
      connBox.textContent = isConfigured ? "ONLINE" : "SIMULAÇÃO / WEBHOOK";
    }
    if (pollFoot) {
      pollFoot.textContent = `Polling ativo: ${st.polling_active ? "Sim" : "Não"} • Webhooks: ${st.webhook_calls || 0}`;
    }
    if (msgBox) {
      msgBox.textContent = `${st.messages_received || 0} recebidas / ${st.messages_sent || 0} enviadas`;
    }
    if (cmdFoot) {
      cmdFoot.textContent = `Comandos (/start, /quadras, etc.): ${st.commands_processed || 0}`;
    }
    if (piiBox) {
      piiBox.textContent = `${st.pii_blocked_count || 0} bloqueio(s) PII`;
    }
    if (lastFoot) {
      lastFoot.textContent = `Última mensagem: ${formatTimestamp(st.last_message_at)}`;
    }
  }

  function renderTelegramLiveFeed(logs) {
    const feedEl = document.getElementById("tg-feed-list");
    const onlyTgCheckbox = document.getElementById("tg-only-telegram-filter");
    if (!feedEl) return;

    const onlyTelegram = Boolean(onlyTgCheckbox && onlyTgCheckbox.checked);
    const filtered = (logs || []).filter((item) => {
      if (!onlyTelegram) return true;
      return item.request && item.request.canal === "telegram";
    });

    if (!filtered.length) {
      feedEl.innerHTML = `<p class="empty-stage-hint">Nenhuma mensagem encontrada para o filtro selecionado. Use o simulador acima para disparar um update Telegram!</p>`;
      return;
    }

    feedEl.innerHTML = filtered
      .map((trace, idx) => {
        const req = trace.request || {};
        const grd = trace.guardrails_entrada || {};
        const out = trace.resposta_final || {};
        const isTg = req.canal === "telegram";
        const isPii = Boolean(grd.pii_detectado);
        const userLabel = req.username
          ? `@${req.username} (${req.first_name || req.user_id})`
          : `${req.user_id || "cliente"}`;

        return `
          <div class="tg-feed-item ${isTg ? "channel-telegram" : ""} ${isPii ? "pii-alert" : ""}">
            <div class="tg-feed-top">
              <div>
                <span class="badge ${isTg ? "badge-cat-declarar_ausencia" : "badge-neutral"}">
                  ${isTg ? "✈️ telegram" : `🌐 ${escapeHtml(req.canal || "api")}`}
                </span>
                <strong style="margin-left:0.35rem;">${escapeHtml(userLabel)}</strong>
                <span style="color:var(--text-muted); margin-left:0.35rem;">• ${escapeHtml(formatTimestamp(trace.timestamp))}</span>
              </div>
              <div>
                ${isPii ? `<span class="badge badge-fail">🔒 PII Bloqueado (LGPD)</span>` : ""}
                ${formatBehaviorBadge(out.comportamento || "responder")}
                <span class="badge badge-neutral">${escapeHtml(trace.latencia_ms || 1)} ms</span>
                <button type="button" class="btn btn-ghost btn-xs feed-raiox-btn" data-log-index="${idx}">
                  🔬 Ver Raio-X
                </button>
              </div>
            </div>
            <div class="tg-feed-qa">
              <div class="tg-qa-box">
                <small style="color:var(--text-muted); display:block; margin-bottom:0.2rem;">Mensagem Recebida (Sanitizada):</small>
                <strong>${escapeHtml(req.pergunta || "")}</strong>
              </div>
              <div class="tg-qa-box">
                <small style="color:var(--text-muted); display:block; margin-bottom:0.2rem;">Resposta do Bot (${(out.fontes || []).join(", ") || "sem fonte"}):</small>
                ${escapeHtml(out.resposta || "")}
              </div>
            </div>
          </div>
        `;
      })
      .join("");

    feedEl.querySelectorAll(".feed-raiox-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const idx = Number(btn.getAttribute("data-log-index"));
        const chosen = filtered[idx];
        if (chosen) {
          renderRaioX(chosen);
          switchTab("tab-playground");
        }
      });
    });
  }

  async function sendSimulatedTelegramWebhook(username, text) {
    const cleanText = String(text || "").trim();
    if (!cleanText) return;

    const submitBtn = document.getElementById("tg-sim-submit");
    const textInput = document.getElementById("tg-sim-text");
    if (submitBtn) submitBtn.disabled = true;

    try {
      const payload = {
        update_id: Math.floor(Date.now() / 1000),
        send_reply: false,
        message: {
          message_id: Math.floor(Math.random() * 100000),
          date: Math.floor(Date.now() / 1000),
          chat: {
            id: 9001,
            type: "private",
            username: username || "cliente_arena",
            first_name: username || "Cliente",
          },
          from: {
            id: 9001,
            is_bot: false,
            username: username || "cliente_arena",
            first_name: username || "Cliente",
          },
          text: cleanText,
        },
      };

      const res = await apiFetch("/api/telegram/webhook", {
        method: "POST",
        body: JSON.stringify(payload),
      });

      if (textInput) textInput.value = "";
      if (res.trace) {
        renderRaioX(res.trace);
      }
      await refreshTelegramMonitor();
    } catch (err) {
      alert(`Erro ao simular update do Telegram: ${err.message}`);
    } finally {
      if (submitBtn) submitBtn.disabled = false;
    }
  }

  /* ========================================================================
     INICIALIZACAO E EVENT LISTENERS
     ======================================================================== */

  function initApp() {
    applyTheme(state.theme);

    // Alternar Tema
    const themeBtn = document.getElementById("theme-toggle-btn");
    if (themeBtn) {
      themeBtn.addEventListener("click", () => {
        applyTheme(state.theme === "dark" ? "light" : "dark");
      });
    }

    // Navegacao entre abas
    document.querySelectorAll(".tab-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const target = btn.getAttribute("data-tab");
        if (target) switchTab(target);
      });
    });

    // Playground Chat Form
    const chatForm = document.getElementById("chat-form");
    if (chatForm) {
      chatForm.addEventListener("submit", (e) => {
        e.preventDefault();
        const inputEl = document.getElementById("chat-input");
        if (inputEl && inputEl.value.trim()) {
          sendPlaygroundQuestion(inputEl.value.trim());
        }
      });
    }

    // Limpar Chat
    const clearChatBtn = document.getElementById("clear-chat-btn");
    if (clearChatBtn) {
      clearChatBtn.addEventListener("click", () => {
        const container = document.getElementById("chat-messages");
        if (container) {
          container.innerHTML = "";
          appendChatBubble(
            "assistant",
            "Histórico limpo. Envie uma nova pergunta para inspecionar o Raio-X de 5 estágios.",
            { comportamento: "responder", fontes: [], latencia_ms: 1 }
          );
        }
      });
    }

    // Cenarios Rapidos do Playground
    document.querySelectorAll("#quick-prompts-list .chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        const promptText = chip.getAttribute("data-prompt");
        if (promptText) sendPlaygroundQuestion(promptText);
      });
    });

    // Gaveta de Chunks da Base de Conhecimento
    const toggleKbBtn = document.getElementById("toggle-kb-list-btn");
    const kbDrawer = document.getElementById("kb-chunks-drawer");
    if (toggleKbBtn && kbDrawer) {
      toggleKbBtn.addEventListener("click", () => {
        kbDrawer.classList.toggle("hidden");
      });
    }

    const kbSearchInput = document.getElementById("kb-search-input");
    if (kbSearchInput) {
      kbSearchInput.addEventListener("input", () => {
        renderKbChunksList(kbSearchInput.value);
      });
    }

    // Aba 2: Botao de Execucao da Bateria P01-P16
    const runEvalBtn = document.getElementById("run-eval-btn");
    if (runEvalBtn) {
      runEvalBtn.addEventListener("click", () => {
        runEvaluationSuite();
      });
    }

    // Aba 3: Memoria Preventiva
    const refreshMemBtn = document.getElementById("refresh-memory-btn");
    if (refreshMemBtn) {
      refreshMemBtn.addEventListener("click", () => loadMemoryLedger());
    }

    const memForm = document.getElementById("memory-form");
    if (memForm) {
      memForm.addEventListener("submit", handleMemoryFormSubmit);
    }

    // Aba 4: Monitor Telegram Live
    const refreshTgBtn = document.getElementById("refresh-telegram-btn");
    if (refreshTgBtn) {
      refreshTgBtn.addEventListener("click", () => refreshTelegramMonitor());
    }

    const onlyTgFilter = document.getElementById("tg-only-telegram-filter");
    if (onlyTgFilter) {
      onlyTgFilter.addEventListener("change", () => {
        renderTelegramLiveFeed(state.recentLogs);
      });
    }

    const tgSimForm = document.getElementById("tg-sim-form");
    if (tgSimForm) {
      tgSimForm.addEventListener("submit", (e) => {
        e.preventDefault();
        const userEl = document.getElementById("tg-sim-user");
        const textEl = document.getElementById("tg-sim-text");
        sendSimulatedTelegramWebhook(
          userEl ? userEl.value.trim() : "cliente_arena",
          textEl ? textEl.value.trim() : ""
        );
      });
    }

    document.querySelectorAll(".tg-chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        const tgText = chip.getAttribute("data-tg-text");
        const userEl = document.getElementById("tg-sim-user");
        if (tgText) {
          sendSimulatedTelegramWebhook(
            userEl ? userEl.value.trim() : "cliente_arena",
            tgText
          );
        }
      });
    });

    // Polling periodico de observabilidade (5s) quando auto-refresh estiver marcado
    state.telegramTimer = setInterval(() => {
      const autoRefresh = document.getElementById("tg-auto-refresh");
      if (autoRefresh && autoRefresh.checked && state.activeTab === "tab-telegram") {
        refreshTelegramMonitor();
      }
    }, 5000);

    // Carregamento inicial de dados
    loadKnowledgeBaseChunks();
    loadMemoryLedger();
    refreshTelegramMonitor();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initApp);
  } else {
    initApp();
  }
})();

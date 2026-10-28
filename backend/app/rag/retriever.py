"""Motor de Busca Hibrida (BM25 + Semantica Local/Gemini Embeddings) e Precedencia de Fontes."""

from __future__ import annotations

import copy
import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

import requests

from backend.app.config import GEMINI_EMBEDDING_MODEL, get_gemini_api_key
from backend.app.rag.indexer import DocumentChunk, KnowledgeBaseIndex, get_index, normalize_text


PORTUGUESE_STOPWORDS: Set[str] = {
    "a", "ao", "aos", "aquela", "aquelas", "aquele", "aqueles", "aquilo", "as",
    "com", "como", "da", "das", "de", "dela", "delas", "dele", "deles", "do",
    "dos", "e", "ela", "elas", "ele", "eles", "em", "entre", "era", "eram",
    "essa", "essas", "esse", "esses", "esta", "estas", "este", "estes", "eu",
    "foi", "for", "foram", "ha", "isso", "isto", "ja", "la", "lhe", "lhes",
    "mais", "mas", "me", "mesmo", "meu", "meus", "minha", "minhas", "muito",
    "na", "nas", "nem", "no", "nos", "nossa", "nossas", "nosso", "nossos",
    "num", "numa", "o", "os", "ou", "para", "pela", "pelas", "pelo", "pelos",
    "por", "qual", "quando", "que", "quem", "se", "sem", "seu", "seus", "so",
    "sua", "suas", "tambem", "te", "tem", "tendo", "tenho", "ter", "teu",
    "teus", "ti", "tido", "tinha", "tinham", "tu", "tua", "tuas", "tudo",
    "um", "uma", "umas", "uns", "voce", "voces", "vos", "pra", "pro", "ai",
}

# Mapa de expansao semantica / parafrases em portugues para o dominio da Arena Vila Nova
SYNONYM_EXPANSIONS: List[Tuple[Tuple[str, ...], str]] = [
    (
        ("desmarcar", "desmarco", "remarcar", "adiar", "mudar horario", "trocar horario"),
        "cancelar cancelamento gratuito 24 horas sinal devolvido reagendar reagendamento 12 horas sem custo",
    ),
    (
        ("cancelar", "cancelamento", "receber o sinal de volta", "devolucao", "reembolso"),
        "cancelamento gratuito 24 horas antes sinal devolvido integralmente 7 dias uteis politica reservas",
    ),
    (
        ("multa", "nao aparecer", "faltar", "sumir", "bolo", "nao comparecer", "nao for"),
        "nao comparecimento avisar 30 minutos reserva cancelada sinal 30% nao e devolvido nao ha cobranca alem do sinal",
    ),
    (
        ("chover", "chuva", "temporal", "molhar", "alagar"),
        "chuva apenas quadras de areia chuva forte impedir o jogo remarcacao sem custo quadras de futsal cobertas",
    ),
    (
        ("estacionamento", "estacionar", "garagem", "vaga de carro", "parar o carro"),
        "estacionamento estrutura",
    ),
    (
        (
            "quais quadras",
            "qual quadra",
            "quadras disponiveis",
            "quadra disponivel",
            "quadras voces",
            "tem quadra",
            "tipos de quadra",
            "tipo de quadra",
            "quantas quadras",
            "estrutura",
            "modalidades",
        ),
        "sobre a arena estrutura 2 quadras de futsal f1 e f2 cobertas piso sintetico 2 quadras de areia a1 e a2 descobertas volei de praia beach tennis quadras e precos tabela de precos por hora",
    ),
    (
        ("abrem", "abre", "fecham", "fecha", "horario", "horarios", "sabados", "sabado", "domingo", "funcionam", "funcionamento"),
        "horario de funcionamento segunda a sexta 7h 23h sabado 7h 22h domingo feriados 8h 20h",
    ),
    (
        ("quarta", "terca", "quinta", "segunda", "sexta", "19h", "18h", "20h", "21h", "noite", "quanto custa", "preco", "valor"),
        "tabela de precos por hora futsal f1 f2 areia a1 a2 segunda a sexta ate 17h apos 17h r$ 120 r$ 160 r$ 70 r$ 90",
    ),
    (
        ("chuteira", "trava", "travas", "tenis", "calcado", "descalco"),
        "calcados quadras de futsal tenis solado liso chuteiras de trava sao proibidas regras de uso",
    ),
    (
        ("cabem", "quantas pessoas", "limite de pessoas", "capacidade", "jogadores na quadra", "lotacao"),
        "capacidade futsal ate 14 pessoas por reserva areia ate 8 pessoas por reserva quadras e precos",
    ),
    (
        ("campeonato", "torneio", "copa", "inscricao"),
        "campeonato interno de futsal trimestre inscricao r$ 450 por equipe 12 jogadores arbitragem mensalistas 10% desconto",
    ),
    (
        ("por aqui", "neste chat", "pelo telegram", "reservar aqui", "fazer reserva", "fazem a reserva"),
        "como reservar reservas sao feitas no site arenavilanova.example/reservas ou na recepcao atendimento pelo telegram nao realiza reservas nem cancelamentos",
    ),
    (
        ("como pago o sinal", "pagar o sinal", "pagamento do sinal", "sinal em dinheiro"),
        "pagamento do sinal so pode ser pago por pix ou cartao no site de reservas nao e possivel pagar o sinal em dinheiro formas de pagamento",
    ),
    (
        ("pix", "cartao", "credito", "debito", "dinheiro", "cheque", "formas de pagamento", "aceitam"),
        "formas de pagamento meios aceitos pix sem taxa cartao de credito 3 vezes r$ 300 debito dinheiro pagamento do sinal",
    ),
    (
        ("mensalista", "mensal", "plano", "horario fixo"),
        "plano mensalista horario fixo 4 jogos por mes desconto de 15% permanencia minima 3 meses",
    ),
    (
        ("lgpd", "privacidade", "dados pessoais", "excluir meus dados", "cpf", "nota fiscal"),
        "privacidade e protecao de dados lgpd dados que coletamos direitos do titular privacidade@arenavilanova.example atendimento pelo telegram",
    ),
]


def tokenize(text: str, remove_stopwords: bool = True) -> List[str]:
    """Tokeniza um texto preservando numeros, valores e horas (ex.: 19h, 30%, 160)."""
    norm = normalize_text(text)
    raw_tokens = re.findall(r"[a-z0-9]+(?:%|h)?", norm)
    if not remove_stopwords:
        return raw_tokens
    return [tok for tok in raw_tokens if tok not in PORTUGUESE_STOPWORDS and len(tok) > 1 or tok.isdigit()]


def stem_token(token: str) -> str:
    """Radicalizacao leve em portugues para aproximar plurais e conjugacoes comuns."""
    if len(token) <= 4 or token.isdigit():
        return token
    for suffix in ("amentos", "amento", "acoes", "acao", "mente", "ando", "endo", "indo", "adas", "ados", "idas", "idos", "ares", "eres", "ires"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[: -len(suffix)]
    if token.endswith("oes") and len(token) > 5:
        return token[:-3] + "ao"
    if token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def is_court_inventory_query(query: str) -> bool:
    """Identifica perguntas sobre quais quadras existem/estao disponiveis ou estrutura de quadras."""
    norm_q = normalize_text(query)
    excluded_topics = (
        "estacionamento",
        "estacionar",
        "garagem",
        "chov",
        "chuva",
        "temporal",
        "chuteira",
        "trava",
        "multa",
        "cancelar",
        "cancelamento",
        "desmarcar",
        "sinal",
        "pix",
        "campeonato",
        "por aqui",
        "pelo telegram",
        "quantas pessoas",
        "cabem",
    )
    if any(exc in norm_q for exc in excluded_topics):
        return False

    direct_phrases = (
        "quais quadras",
        "qual quadra",
        "quadras disponiveis",
        "quadra disponivel",
        "quadras voces",
        "tem quadra",
        "tipos de quadra",
        "tipo de quadra",
        "quantas quadras",
        "estrutura da arena",
        "qual a estrutura",
    )
    if any(phrase in norm_q for phrase in direct_phrases):
        return True

    has_court_word = "quadra" in norm_q or "quadras" in norm_q
    inventory_markers = (
        "quais",
        "qual",
        "disponivel",
        "disponiveis",
        "existem",
        "possui",
        "possuem",
        "tipos",
        "tipo",
        "quantas",
        "estrutura",
        "modalidades",
    )
    if has_court_word and any(m in norm_q for m in inventory_markers):
        return True

    return "estrutura" in norm_q


def expand_query_with_synonyms(query: str) -> Tuple[str, List[str]]:
    """Expande a pergunta do usuario com sinonimos e termos canonicos da base."""
    norm_q = normalize_text(query)
    added_phrases: List[str] = []
    for triggers, expansion in SYNONYM_EXPANSIONS:
        for trigger in triggers:
            if trigger in norm_q:
                added_phrases.append(expansion)
                break

    court_expansion = (
        "sobre a arena estrutura 2 quadras de futsal f1 e f2 cobertas piso sintetico "
        "2 quadras de areia a1 e a2 descobertas volei de praia beach tennis "
        "quadras e precos tabela de precos por hora"
    )
    if is_court_inventory_query(query) and court_expansion not in added_phrases:
        added_phrases.append(court_expansion)

    if not added_phrases:
        return query, []
    expanded = f"{query} {' '.join(added_phrases)}"
    return expanded, added_phrases


def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    """Calcula a similaridade de cosseno entre dois vetores."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (norm_a * norm_b)))


@dataclass
class RetrievalResult:
    """Resultado completo do estagio FILTRAGEM."""

    chunks: List[DocumentChunk] = field(default_factory=list)
    documentos_obsoletos_descartados: List[str] = field(default_factory=list)
    chunks_bloqueados_seguranca: List[str] = field(default_factory=list)
    divergencia_detectada: bool = False
    resolucao_divergencia: str = ""
    expansoes_aplicadas: List[str] = field(default_factory=list)
    modo_busca: str = "hybrid_local_bm25_tfidf"


_GLOBAL_EMBEDDING_CACHE: Dict[str, List[float]] = {}


class HybridRetriever:
    """Motor de busca hibrida com BM25, TF-IDF expandido, Gemini Embeddings opcional e Precedencia."""

    def __init__(self, index: Optional[KnowledgeBaseIndex] = None) -> None:
        self.index: KnowledgeBaseIndex = index or get_index()
        self._doc_tokens: List[List[str]] = []
        self._doc_stems: List[List[str]] = []
        self._df: Dict[str, int] = {}
        self._stem_df: Dict[str, int] = {}
        self._avgdl: float = 1.0
        self._embedding_cache: Dict[str, List[float]] = _GLOBAL_EMBEDDING_CACHE
        self._build_lexical_structures()

    def _build_lexical_structures(self) -> None:
        """Pre-calcula frequencias de documentos para BM25 e TF-IDF sobre chunks vigentes."""
        self._doc_tokens = []
        self._doc_stems = []
        self._df = {}
        self._stem_df = {}

        total_len = 0
        for chunk in self.index.chunks:
            full_text = f"{chunk.titulo_documento} {chunk.secao} {chunk.secao} {chunk.conteudo}"
            tokens = tokenize(full_text)
            stems = [stem_token(t) for t in tokens]
            self._doc_tokens.append(tokens)
            self._doc_stems.append(stems)
            total_len += len(tokens)

            for tok in set(tokens):
                self._df[tok] = self._df.get(tok, 0) + 1
            for st in set(stems):
                self._stem_df[st] = self._stem_df.get(st, 0) + 1

        n_docs = len(self.index.chunks)
        self._avgdl = (total_len / n_docs) if n_docs > 0 else 1.0

    def _compute_bm25_scores(self, query: str) -> List[float]:
        """Calcula o score Okapi BM25 bruto para cada chunk e normaliza em [0.0, 1.0]."""
        n_docs = len(self.index.chunks)
        if n_docs == 0:
            return []

        q_tokens = tokenize(query)
        q_stems = [stem_token(t) for t in q_tokens]
        k1 = 1.5
        b = 0.75
        raw_scores: List[float] = []

        for idx in range(n_docs):
            doc_toks = self._doc_tokens[idx]
            doc_sts = self._doc_stems[idx]
            doc_len = len(doc_toks) or 1
            score = 0.0

            for tok, st in zip(q_tokens, q_stems):
                tf_exact = doc_toks.count(tok)
                tf_stem = doc_sts.count(st)
                tf = tf_exact + 0.5 * max(0, tf_stem - tf_exact)
                if tf <= 0:
                    continue
                df = self._df.get(tok, self._stem_df.get(st, 0))
                idf = math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))
                denom = tf + k1 * (1.0 - b + b * (doc_len / self._avgdl))
                score += idf * ((tf * (k1 + 1.0)) / denom)

            raw_scores.append(score)

        max_score = max(raw_scores) if raw_scores else 0.0
        if max_score <= 0.0:
            return [0.0 for _ in raw_scores]
        return [s / max_score for s in raw_scores]

    def _compute_local_semantic_scores(self, query: str, expanded_query: str) -> List[float]:
        """Calcula similaridade semantica local via TF-IDF de radicais + expansao de parafrases."""
        n_docs = len(self.index.chunks)
        if n_docs == 0:
            return []

        exp_tokens = tokenize(expanded_query)
        exp_stems = [stem_token(t) for t in exp_tokens]
        orig_stems = set(stem_token(t) for t in tokenize(query))

        if not exp_stems:
            return [0.0 for _ in range(n_docs)]

        vocab = sorted(set(exp_stems))
        q_vec: List[float] = []
        for term in vocab:
            tf = exp_stems.count(term)
            boost = 1.5 if term in orig_stems else 1.0
            df = self._stem_df.get(term, 0)
            idf = math.log(1.0 + n_docs / (1.0 + df))
            q_vec.append(tf * boost * idf)

        scores: List[float] = []
        for idx, chunk in enumerate(self.index.chunks):
            doc_sts = self._doc_stems[idx]
            d_vec: List[float] = []
            for term in vocab:
                tf = doc_sts.count(term)
                df = self._stem_df.get(term, 0)
                idf = math.log(1.0 + n_docs / (1.0 + df))
                d_vec.append(tf * idf)

            cos = cosine_similarity(q_vec, d_vec)
            # Bonus quando o titulo da secao ou documento casa diretamente com termos da consulta
            sec_stems = set(stem_token(t) for t in tokenize(f"{chunk.titulo_documento} {chunk.secao}"))
            overlap = len(sec_stems.intersection(set(exp_stems)))
            header_bonus = min(0.25, overlap * 0.08)
            scores.append(min(1.0, cos + header_bonus))

        max_s = max(scores) if scores else 0.0
        if max_s <= 0.0:
            return [0.0 for _ in scores]
        return [s / max_s for s in scores]

    def _fetch_gemini_embedding(self, text: str, api_key: str) -> Optional[List[float]]:
        """Obtem o vetor de embedding via API REST do Google Gemini (gemini-embedding-001)."""
        cache_key = text[:512]
        if cache_key in self._embedding_cache:
            return self._embedding_cache[cache_key]

        candidate_models: List[str] = []
        for m in (GEMINI_EMBEDDING_MODEL, "gemini-embedding-001"):
            if m and m not in candidate_models:
                candidate_models.append(m)

        for model_name in candidate_models:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model_name}:embedContent?key={api_key}"
            )
            payload = {
                "model": f"models/{model_name}",
                "content": {"parts": [{"text": text}]},
            }
            try:
                resp = requests.post(url, json=payload, timeout=5.0)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                values = data.get("embedding", {}).get("values")
                if isinstance(values, list) and values:
                    vec = [float(x) for x in values]
                    self._embedding_cache[cache_key] = vec
                    return vec
            except Exception:
                continue
        return None

    def _ensure_chunk_embeddings(self, api_key: str) -> bool:
        """Garante que os embeddings de todos os chunks ativos estejam em cache via batchEmbedContents ou individual."""
        missing_chunks = [
            ch for ch in self.index.chunks if ch.texto_contextual[:512] not in self._embedding_cache
        ]
        if not missing_chunks:
            return True

        candidate_models: List[str] = []
        for m in (GEMINI_EMBEDDING_MODEL, "gemini-embedding-001"):
            if m and m not in candidate_models:
                candidate_models.append(m)

        for model_name in candidate_models:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model_name}:batchEmbedContents?key={api_key}"
            )
            payload = {
                "requests": [
                    {
                        "model": f"models/{model_name}",
                        "content": {"parts": [{"text": ch.texto_contextual}]},
                    }
                    for ch in missing_chunks
                ]
            }
            try:
                resp = requests.post(url, json=payload, timeout=10.0)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                embeddings = data.get("embeddings", [])
                if isinstance(embeddings, list) and len(embeddings) == len(missing_chunks):
                    for ch, emb_obj in zip(missing_chunks, embeddings):
                        values = emb_obj.get("values")
                        if isinstance(values, list) and values:
                            self._embedding_cache[ch.texto_contextual[:512]] = [
                                float(x) for x in values
                            ]
                    if all(
                        ch.texto_contextual[:512] in self._embedding_cache
                        for ch in self.index.chunks
                    ):
                        return True
            except Exception:
                continue

        # Fallback individual se batch falhar
        for ch in missing_chunks:
            if self._fetch_gemini_embedding(ch.texto_contextual, api_key) is None:
                return False
        return True

    def retrieve(self, query: str, top_k: int = 5) -> RetrievalResult:
        """Executa a busca hibrida, aplica pesos de precedencia e detecta divergencias."""
        norm_q = normalize_text(query)
        court_inventory_intent = is_court_inventory_query(query)
        rain_intent = any(w in norm_q for w in ("chov", "chuva", "temporal", "molhar", "alagar"))

        expanded_query, expansions = expand_query_with_synonyms(query)
        bm25_scores = self._compute_bm25_scores(expanded_query)
        local_sem_scores = self._compute_local_semantic_scores(query, expanded_query)

        api_key = get_gemini_api_key()
        modo_busca = "hybrid_local_bm25_tfidf"
        sem_scores = list(local_sem_scores)

        if api_key:
            q_emb = self._fetch_gemini_embedding(query, api_key)
            if q_emb is not None and self._ensure_chunk_embeddings(api_key):
                api_sem: List[float] = []
                all_ok = True
                for chunk in self.index.chunks:
                    c_emb = self._embedding_cache.get(chunk.texto_contextual[:512])
                    if c_emb is None:
                        all_ok = False
                        break
                    api_sem.append(cosine_similarity(q_emb, c_emb))
                if all_ok and api_sem:
                    max_api = max(api_sem) or 1.0
                    norm_api = [s / max_api for s in api_sem]
                    sem_scores = [
                        0.6 * api_s + 0.4 * loc_s
                        for api_s, loc_s in zip(norm_api, local_sem_scores)
                    ]
                    modo_busca = "hybrid_gemini_embeddings_bm25"

        scored_chunks: List[DocumentChunk] = []
        for idx, base_chunk in enumerate(self.index.chunks):
            # Hard Filter de seguranca e status vigente
            if base_chunk.metadados.get("status") != "vigente" or base_chunk.suspeita_injection:
                continue

            s_bm25 = bm25_scores[idx] if idx < len(bm25_scores) else 0.0
            s_sem = sem_scores[idx] if idx < len(sem_scores) else 0.0

            # Quando a pergunta for sobre quadras existentes/disponiveis ou estrutura,
            # prioriza 01-sobre-a-arena#estrutura e 02-quadras-e-precos#tabela-de-precos-por-hora
            # e evita que regras secundarias como chuva nas quadras de areia fiquem no topo.
            if court_inventory_intent:
                if base_chunk.chunk_id == "01-sobre-a-arena#estrutura":
                    s_sem = max(s_sem, 1.0)
                    s_bm25 = max(s_bm25, 1.0)
                elif base_chunk.chunk_id == "02-quadras-e-precos#tabela-de-precos-por-hora":
                    s_sem = max(s_sem, 0.96)
                    s_bm25 = max(s_bm25, 0.92)

            score_hibrido = 0.65 * s_sem + 0.35 * s_bm25
            score_final = score_hibrido * base_chunk.peso_precedencia

            if court_inventory_intent:
                if base_chunk.chunk_id == "01-sobre-a-arena#estrutura":
                    score_final = max(score_final, 0.99)
                elif base_chunk.chunk_id == "02-quadras-e-precos#tabela-de-precos-por-hora":
                    score_final = max(score_final, 0.95)
                elif base_chunk.chunk_id == "03-reservas-e-cancelamento#chuva-apenas-quadras-de-areia":
                    score_final *= 0.45
            elif (
                not rain_intent
                and base_chunk.chunk_id == "03-reservas-e-cancelamento#chuva-apenas-quadras-de-areia"
            ):
                score_final *= 0.75

            if score_final <= 0.01:
                continue

            chunk_copy = copy.deepcopy(base_chunk)
            chunk_copy.score_bm25 = s_bm25
            chunk_copy.score_semantico = s_sem
            chunk_copy.score_final = score_final
            scored_chunks.append(chunk_copy)

        scored_chunks.sort(
            key=lambda c: (c.score_final, c.peso_precedencia, c.score_semantico),
            reverse=True,
        )

        selected = scored_chunks[:top_k]

        # Deteccao deterministica de divergencia entre Politica v2.0 (24h) e FAQ v1.0 (12h)
        candidate_ids = {c.chunk_id for c in scored_chunks[:15]}
        selected_ids = {c.chunk_id for c in selected}
        divergencia_detectada = False
        resolucao_divergencia = ""

        has_policy_cancel = (
            "03-reservas-e-cancelamento#cancelamento" in candidate_ids
            or "03-reservas-e-cancelamento#reagendamento" in candidate_ids
        )
        has_faq_cancel = "08-faq-atendimento#posso-cancelar-ate-12-horas-antes" in candidate_ids

        if has_policy_cancel and has_faq_cancel:
            divergencia_detectada = True
            resolucao_divergencia = (
                "Prevaleceu o prazo de 24h de 03-reservas-e-cancelamento.md (area: politica, "
                "versao: 2.0, peso: 1.0, atualizado em 2026-08-01) sobre o prazo divergente de 12h "
                "de 08-faq-atendimento.md (area: atendimento, versao: 1.0, peso: 0.6, atualizado em 2025-03-05)."
            )
            # Garante que se o chunk do FAQ nao entrou no top_k mas estava nos candidatos logo abaixo,
            # ambos fiquem visiveis na auditoria com 03-reservas-e-cancelamento no topo
            if "08-faq-atendimento#posso-cancelar-ate-12-horas-antes" not in selected_ids:
                for c in scored_chunks:
                    if c.chunk_id == "08-faq-atendimento#posso-cancelar-ate-12-horas-antes":
                        if len(selected) >= top_k and top_k >= 2:
                            selected[-1] = c
                        else:
                            selected.append(c)
                        break

        return RetrievalResult(
            chunks=selected,
            documentos_obsoletos_descartados=self.index.obsolete_filenames,
            chunks_bloqueados_seguranca=self.index.blocked_chunk_ids,
            divergencia_detectada=divergencia_detectada,
            resolucao_divergencia=resolucao_divergencia,
            expansoes_aplicadas=expansions,
            modo_busca=modo_busca,
        )


_GLOBAL_RETRIEVER: Optional[HybridRetriever] = None


def get_retriever(force_rebuild: bool = False) -> HybridRetriever:
    """Retorna a instancia singleton do HybridRetriever."""
    global _GLOBAL_RETRIEVER
    if _GLOBAL_RETRIEVER is None or force_rebuild:
        _GLOBAL_RETRIEVER = HybridRetriever(get_index(force_rebuild=force_rebuild))
    return _GLOBAL_RETRIEVER

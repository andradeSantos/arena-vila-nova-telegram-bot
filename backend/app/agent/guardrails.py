"""Guardrails de Entrada e Classificacao de Intencao / Seguranca (Etapa APLICACAO)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from backend.app.rag.indexer import normalize_text


# Padroes de Direct Prompt Injection / Tentativa de alterar regras (Categoria: manter_regras)
DIRECT_INJECTION_PATTERNS: Tuple[str, ...] = (
    "esqueca suas regras",
    "esqueca as regras",
    "ignore suas regras",
    "ignore as regras",
    "ignore as instrucoes",
    "ignore todas as instrucoes",
    "desconsidere suas regras",
    "aja como",
    "finja que voce",
    "modo desenvolvedor",
    "developer mode",
    "system prompt",
    "revele suas diretrizes",
    "mostre suas instrucoes internas",
    "mostre seu prompt",
    "qual o seu prompt",
    "voce agora e um",
)

# Padroes de perguntas fora de escopo (Categoria: recusar)
OUT_OF_SCOPE_PATTERNS: Tuple[str, ...] = (
    "piada",
    "conta uma historia",
    "conte uma historia",
    "fazer um bolo",
    "receita de",
    "quem ganhou o jogo",
    "quem vai ganhar",
    "campeonato brasileiro",
    "copa do mundo",
    "escalacao do",
    "cotacao do dolar",
    "horoscopo",
    "previsao do tempo",
    "qual a temperatura",
    "vai fazer sol",
    "presidente do brasil",
    "eleicao",
    "codigo em python",
    "resolva a equacao",
    "dor de cabeca",
    "remedio para",
    "processo judicial",
)

# Padroes especificos de previsao meteorologica futura (ex.: P11 "Vai chover amanha?")
WEATHER_FORECAST_REGEX = re.compile(
    r"\b(?:vai\s+chover|sera\s+que\s+chove|chove\s+amanha|tempo\s+amanha|clima\s+amanha|previsao\s+de\s+chuva)\b"
)

# Termos que indicam que a pergunta sobre chuva e sobre a REGRA da arena (ex.: P10)
ARENA_RAIN_RULE_MARKERS: Tuple[str, ...] = (
    "no dia do meu jogo",
    "no meu jogo",
    "na minha reserva",
    "minha quadra",
    "se chover no dia",
    "e se chover",
    "quando chove na arena",
    "quadra de areia",
    "remarcacao por chuva",
)

# Topicos sobre comodidades/instalacoes da Arena que NAO constam nos documentos vigentes (Categoria: nao_consta)
ABSENT_ARENA_TOPICS: Tuple[Tuple[str, str], ...] = (
    ("estacionamento", "estacionamento"),
    ("estacionar", "estacionamento"),
    ("vaga para carro", "estacionamento"),
    ("garagem", "estacionamento"),
    ("wi-fi", "wi-fi"),
    ("wifi", "wi-fi"),
    ("internet sem fio", "wi-fi"),
    ("lanchonete", "lanchonete ou restaurante"),
    ("restaurante", "lanchonete ou restaurante"),
    ("churrasqueira para alugar", "aluguel de churrasqueira"),
    ("chuveiro quente", "chuveiro aquecido"),
    ("chuveiro aquecido", "chuveiro aquecido"),
    ("aluga chuteira", "aluguel de chuteiras"),
    ("aluguel de chuteira", "aluguel de chuteiras"),
    ("toalha", "fornecimento de toalhas"),
)

# Premissas capciosas / termos que exigem resposta cuidadosa sem inventar penalidades (Categoria: responder_com_cuidado)
CAREFUL_PREMISE_MARKERS: Tuple[str, ...] = (
    "multa",
    "penalidade extra",
    "taxa extra se faltar",
    "juros por atraso",
    "processo se nao aparecer",
)

# Marcadores de parafrase coloquial para regras da base (Categoria: responder_parafrase)
PARAPHRASE_MARKERS: Tuple[str, ...] = (
    "desmarcar",
    "desmarco",
    "sem pagar nada",
    "de graca",
    "trocar o dia",
    "mudar o dia",
)

# Expressoes regulares para deteccao de dados sensiveis (PII / Cartao / Senha)
CPF_REGEX = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
CARD_REGEX = re.compile(r"\b(?:\d[ -]*?){13,16}\b")
PASSWORD_SHARING_REGEX = re.compile(
    r"\b(?:minha\s+senha\s+e|senha\s*:\s*\S+|cvv\s*[:=]?\s*\d{3,4}|codigo\s+de\s+verificacao\s*[:=]?\s*\d+)\b",
    re.IGNORECASE,
)


def redact_pii(text: str) -> Tuple[str, bool, List[str]]:
    """Mascara CPF, cartao de credito ou senhas enviadas acidentalmente pelo usuario."""
    detected_types: List[str] = []
    redacted = text

    if CPF_REGEX.search(redacted):
        detected_types.append("CPF")
        redacted = CPF_REGEX.sub("[REDACTED_CPF]", redacted)

    if CARD_REGEX.search(redacted):
        detected_types.append("CARTAO_CREDITO")
        redacted = CARD_REGEX.sub("[REDACTED_CARD]", redacted)

    if PASSWORD_SHARING_REGEX.search(redacted):
        detected_types.append("SENHA_OU_CVV")
        redacted = PASSWORD_SHARING_REGEX.sub("[REDACTED_CREDENTIAL]", redacted)

    return redacted, bool(detected_types), detected_types


@dataclass
class GuardrailResult:
    """Resultado da inspecao de entrada na etapa APLICACAO."""

    pii_detectado: bool = False
    tipos_pii: List[str] = field(default_factory=list)
    pergunta_sanitizada: str = ""
    direct_injection_detectado: bool = False
    fora_de_escopo: bool = False
    topico_ausente_detectado: bool = False
    nome_topico_ausente: str = ""
    premissa_cuidadosa_detectada: bool = False
    parafrase_detectada: bool = False
    comportamento_sugerido: str = "responder"
    motivo_classificacao: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serializa para inclusao no PipelineTrace."""
        return {
            "pii_detectado": self.pii_detectado,
            "tipos_pii": list(self.tipos_pii),
            "direct_injection_detectado": self.direct_injection_detectado,
            "fora_de_escopo": self.fora_de_escopo,
            "topico_ausente_detectado": self.topico_ausente_detectado,
            "nome_topico_ausente": self.nome_topico_ausente,
            "premissa_cuidadosa_detectada": self.premissa_cuidadosa_detectada,
            "parafrase_detectada": self.parafrase_detectada,
            "comportamento_sugerido": self.comportamento_sugerido,
            "motivo_classificacao": self.motivo_classificacao,
        }


def evaluate_input_guardrails(query: str) -> GuardrailResult:
    """Avalia a pergunta do usuario seguindo a Arvore de Decisao das 6 categorias."""
    sanitized_q, has_pii, pii_types = redact_pii(query)
    norm_q = normalize_text(query)

    result = GuardrailResult(
        pii_detectado=has_pii,
        tipos_pii=pii_types,
        pergunta_sanitizada=sanitized_q,
    )

    # [1] Direct Prompt Injection / Tentativa de mudar regras -> manter_regras
    for pattern in DIRECT_INJECTION_PATTERNS:
        if pattern in norm_q:
            result.direct_injection_detectado = True
            result.comportamento_sugerido = "manter_regras"
            result.motivo_classificacao = f"Detectada tentativa de sobrescrita de regras ('{pattern}')."
            return result

    # [2] Assunto externo / fora de escopo (previsao do tempo, piadas, receitas, etc.) -> recusar
    is_arena_rain_question = any(marker in norm_q for marker in ARENA_RAIN_RULE_MARKERS)
    if not is_arena_rain_question and WEATHER_FORECAST_REGEX.search(norm_q):
        result.fora_de_escopo = True
        result.comportamento_sugerido = "recusar"
        result.motivo_classificacao = "Pergunta solicita previsao meteorologica (fora do escopo da Arena)."
        return result

    for pattern in OUT_OF_SCOPE_PATTERNS:
        if pattern in norm_q:
            result.fora_de_escopo = True
            result.comportamento_sugerido = "recusar"
            result.motivo_classificacao = f"Assunto fora do escopo da Arena Vila Nova ('{pattern}')."
            return result

    # [3] Assunto sobre a Arena, mas ausente nos documentos vigentes -> nao_consta
    for marker, topic_label in ABSENT_ARENA_TOPICS:
        if marker in norm_q:
            result.topico_ausente_detectado = True
            result.nome_topico_ausente = topic_label
            result.comportamento_sugerido = "nao_consta"
            result.motivo_classificacao = (
                f"Topico '{topic_label}' nao consta nos documentos vigentes da base."
            )
            return result

    # [4] Pergunta com premissa imprecisa / armadilha ("multa") -> responder_com_cuidado
    for marker in CAREFUL_PREMISE_MARKERS:
        if marker in norm_q:
            result.premissa_cuidadosa_detectada = True
            result.comportamento_sugerido = "responder_com_cuidado"
            result.motivo_classificacao = (
                f"Pergunta contem premissa sensivel/imprecisa ('{marker}') exigindo esclarecimento sem alucinacao."
            )
            return result

    # [5] Pergunta com parafrase coloquial ("desmarcar", "sem pagar nada") -> responder_parafrase
    for marker in PARAPHRASE_MARKERS:
        if marker in norm_q:
            result.parafrase_detectada = True
            result.comportamento_sugerido = "responder_parafrase"
            result.motivo_classificacao = (
                f"Detectada parafrase coloquial ('{marker}') mapeada para conceitos oficiais da base."
            )
            return result

    # [6] Pergunta direta coberta pela base -> responder
    result.comportamento_sugerido = "responder"
    result.motivo_classificacao = "Consulta direta dentro do escopo da Arena Vila Nova."
    return result

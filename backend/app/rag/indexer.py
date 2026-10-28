"""Indexador da Base de Conhecimento com parser YAML, filtro de obsoletos e sanitizacao de injection."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from backend.app.config import KB_DIR, PRECEDENCE_WEIGHTS


INJECTION_MARKERS: Tuple[str, ...] = (
    "instrucao para assistentes virtuais",
    "ignore as regras anteriores",
    "esqueca as regras anteriores",
    "cupom arena50",
    "arena50",
    "system prompt override",
)

INJECTION_SECTION_TITLES: Tuple[str, ...] = (
    "aviso interno",
    "instrucao interna",
    "instrucao para ia",
)


def normalize_text(text: str) -> str:
    """Remove acentos e normaliza para minusculas para comparacoes deterministicas."""
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    return ascii_text.lower().strip()


def slugify_section(section_title: str) -> str:
    """Converte o titulo de uma secao em um identificador slug legivel."""
    norm = normalize_text(section_title)
    slug = re.sub(r"[^a-z0-9]+", "-", norm).strip("-")
    return slug or "geral"


def parse_frontmatter_and_body(raw_markdown: str) -> Tuple[Dict[str, Any], str]:
    """Extrai o frontmatter YAML (versao, status, area, atualizado_em) e o corpo Markdown."""
    text = raw_markdown.lstrip("\ufeff").strip()
    if not text.startswith("---"):
        return {}, text

    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, flags=re.DOTALL)
    if not match:
        return {}, text

    yaml_block, body = match.group(1), match.group(2)
    try:
        parsed = yaml.safe_load(yaml_block) or {}
    except Exception:
        parsed = {}
        for line in yaml_block.splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                parsed[k.strip()] = v.strip()

    metadata: Dict[str, Any] = {
        "versao": str(parsed.get("versao", "")).strip(),
        "status": str(parsed.get("status", "")).strip().lower(),
        "area": str(parsed.get("area", "")).strip().lower(),
        "atualizado_em": str(parsed.get("atualizado_em", "")).strip(),
    }
    return metadata, body.strip()


def detect_indirect_injection(section_title: str, section_content: str) -> Tuple[bool, str]:
    """Detecta tentativas de Indirect Prompt Injection em secoes da base de conhecimento."""
    norm_title = normalize_text(section_title)
    norm_content = normalize_text(section_content)

    for forbidden_title in INJECTION_SECTION_TITLES:
        if forbidden_title in norm_title:
            return True, f"Secao suspeita bloqueada pelo titulo: '{section_title}'"

    for marker in INJECTION_MARKERS:
        if marker in norm_content or marker in norm_title:
            return True, f"Padrao de Indirect Prompt Injection detectado: '{marker}'"

    return False, ""


@dataclass
class DocumentChunk:
    """Representa uma secao (##) indexada de um documento da base de conhecimento."""

    chunk_id: str
    arquivo_origem: str
    fonte_id: str
    titulo_documento: str
    secao: str
    conteudo: str
    metadados: Dict[str, str]
    peso_precedencia: float
    suspeita_injection: bool = False
    motivo_bloqueio: str = ""
    score_semantico: float = 0.0
    score_bm25: float = 0.0
    score_final: float = 0.0

    @property
    def texto_contextual(self) -> str:
        """Retorna o texto enriquecido com cabecalho de metadados conforme Especificacao 02."""
        return (
            f"[Documento: {self.titulo_documento} | Arquivo: {self.arquivo_origem} | "
            f"Area: {self.metadados.get('area', '')} | Versao: {self.metadados.get('versao', '')} | "
            f"Secao: {self.secao}]\n{self.conteudo}"
        )

    def to_dict(self) -> Dict[str, Any]:
        """Converte para o contrato JSON RetrievalChunk da Especificacao 01."""
        return {
            "chunk_id": self.chunk_id,
            "arquivo_origem": self.arquivo_origem,
            "fonte_id": self.fonte_id,
            "titulo_documento": self.titulo_documento,
            "secao": self.secao,
            "conteudo": self.conteudo,
            "metadados": dict(self.metadados),
            "score_semantico": round(self.score_semantico, 4),
            "score_bm25": round(self.score_bm25, 4),
            "peso_precedencia": round(self.peso_precedencia, 2),
            "score_final": round(self.score_final, 4),
            "suspeita_injection": self.suspeita_injection,
            "motivo_bloqueio": self.motivo_bloqueio,
        }


@dataclass
class KnowledgeBaseIndex:
    """Indice em memoria contendo chunks vigentes, documentos obsoletos descartados e secoes bloqueadas."""

    chunks: List[DocumentChunk] = field(default_factory=list)
    discarded_obsolete_docs: List[Dict[str, Any]] = field(default_factory=list)
    blocked_injection_chunks: List[DocumentChunk] = field(default_factory=list)
    documents_metadata: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    @property
    def obsolete_filenames(self) -> List[str]:
        """Lista os nomes dos arquivos descartados por status != vigente."""
        return [doc["arquivo_origem"] for doc in self.discarded_obsolete_docs]

    @property
    def blocked_chunk_ids(self) -> List[str]:
        """Lista os IDs de chunks bloqueados por suspeita de Prompt Injection."""
        return [chunk.chunk_id for chunk in self.blocked_injection_chunks]


def split_markdown_sections(body: str) -> Tuple[str, str, List[Tuple[str, str]]]:
    """Separa o titulo principal (#), texto introdutorio opcional e lista de secoes (##)."""
    lines = body.splitlines()
    doc_title = ""
    intro_lines: List[str] = []
    sections: List[Tuple[str, List[str]]] = []
    current_section_title: Optional[str] = None
    current_section_lines: List[str] = []

    for line in lines:
        if line.startswith("# ") and not doc_title:
            doc_title = line[2:].strip()
            continue
        if line.startswith("## "):
            if current_section_title is not None:
                sections.append((current_section_title, current_section_lines))
            current_section_title = line[3:].strip()
            current_section_lines = []
            continue

        if current_section_title is None:
            if line.strip():
                intro_lines.append(line.strip())
        else:
            current_section_lines.append(line)

    if current_section_title is not None:
        sections.append((current_section_title, current_section_lines))

    intro_text = "\n".join(intro_lines).strip()
    clean_sections: List[Tuple[str, str]] = []
    for sec_title, sec_lines in sections:
        sec_content = "\n".join(sec_lines).strip()
        if intro_text and not clean_sections:
            sec_content = f"{intro_text}\n\n{sec_content}".strip()
        clean_sections.append((sec_title, sec_content))

    if not clean_sections and body.strip():
        clean_sections.append(("Geral", body.strip()))

    return doc_title or "Documento", intro_text, clean_sections


def build_index(kb_dir: Path = KB_DIR) -> KnowledgeBaseIndex:
    """Constroi o indice RAG aplicando filtro rigido de status=='vigente' e sanitizacao de injection."""
    index = KnowledgeBaseIndex()
    if not kb_dir.exists():
        return index

    md_files = sorted(kb_dir.glob("*.md"))
    for md_file in md_files:
        raw_text = md_file.read_text(encoding="utf-8")
        metadata, body = parse_frontmatter_and_body(raw_text)
        doc_title, _, sections = split_markdown_sections(body)
        arquivo_origem = md_file.name
        fonte_id = md_file.stem

        index.documents_metadata[arquivo_origem] = {
            "arquivo_origem": arquivo_origem,
            "fonte_id": fonte_id,
            "titulo_documento": doc_title,
            "metadados": metadata,
        }

        # Regra Inegociavel: Descartar imediatamente documentos com status != 'vigente'
        status = metadata.get("status", "").lower()
        if status != "vigente":
            index.discarded_obsolete_docs.append(
                {
                    "arquivo_origem": arquivo_origem,
                    "fonte_id": fonte_id,
                    "titulo_documento": doc_title,
                    "metadados": metadata,
                    "motivo_descarte": f"Documento descartado por status='{status}' (diferente de 'vigente').",
                }
            )
            continue

        area = metadata.get("area", "").lower()
        peso_precedencia = PRECEDENCE_WEIGHTS.get(area, 0.5)

        for sec_title, sec_content in sections:
            chunk_id = f"{fonte_id}#{slugify_section(sec_title)}"
            is_injection, injection_reason = detect_indirect_injection(sec_title, sec_content)

            chunk = DocumentChunk(
                chunk_id=chunk_id,
                arquivo_origem=arquivo_origem,
                fonte_id=fonte_id,
                titulo_documento=doc_title,
                secao=sec_title,
                conteudo=sec_content,
                metadados=metadata,
                peso_precedencia=peso_precedencia,
                suspeita_injection=is_injection,
                motivo_bloqueio=injection_reason,
            )

            if is_injection:
                index.blocked_injection_chunks.append(chunk)
            else:
                index.chunks.append(chunk)

    return index


_GLOBAL_INDEX: Optional[KnowledgeBaseIndex] = None


def get_index(force_rebuild: bool = False) -> KnowledgeBaseIndex:
    """Retorna a instancia singleton do indice da base de conhecimento."""
    global _GLOBAL_INDEX
    if _GLOBAL_INDEX is None or force_rebuild:
        _GLOBAL_INDEX = build_index()
    return _GLOBAL_INDEX

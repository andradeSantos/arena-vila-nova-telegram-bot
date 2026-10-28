"""Modulo RAG: Indexacao estrutural por secoes, filtro de obsoletos, sanitizacao e busca hibrida."""

from backend.app.rag.indexer import DocumentChunk, KnowledgeBaseIndex, build_index, get_index
from backend.app.rag.retriever import HybridRetriever, RetrievalResult, get_retriever

__all__ = [
    "DocumentChunk",
    "KnowledgeBaseIndex",
    "build_index",
    "get_index",
    "HybridRetriever",
    "RetrievalResult",
    "get_retriever",
]

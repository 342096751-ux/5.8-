from __future__ import annotations

from typing import Any

from app.services.vector_store import VectorStore


class RAGService:
    """Collection-aware retrieval service backed by VectorStore."""

    def __init__(self, vector_store: VectorStore) -> None:
        self._vector_store = vector_store

    @property
    def vector_store(self) -> VectorStore:
        return self._vector_store

    def get_all_rules_for_matching(self, category: str | None = None) -> list[dict[str, Any]]:
        """全量规则（硬匹配兜底），结构见 EnhancedRetriever.get_all_rules。"""
        from app.services.enhanced_rag import EnhancedRetriever

        return EnhancedRetriever(self).get_all_rules(category)

    def query(self, collection: str, text: str, top_k: int = 3) -> list[dict[str, Any]]:
        return self._vector_store.query(collection=collection, text=text, top_k=top_k)

    def get_all(self, collection: str) -> list[dict[str, Any]]:
        return self._vector_store.get_all(collection)

    def add_document(
        self,
        collection: str,
        item_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._vector_store.add_one(
            collection=collection, item_id=item_id, text=text, metadata=metadata
        )

    def update_document(
        self,
        collection: str,
        item_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._vector_store.update_one(
            collection=collection, item_id=item_id, text=text, metadata=metadata
        )

    def delete_document(self, collection: str, item_id: str) -> None:
        self._vector_store.delete(collection=collection, ids=[item_id])

    def retrieve_rules(self, content: str, top_k: int = 5) -> list[dict[str, Any]]:
        return self.query("rule_base", content, top_k)

    def retrieve_knowledge(self, content: str, top_k: int = 5) -> list[dict[str, Any]]:
        return self.query("knowledge_base", content, top_k)

    def retrieve_cases(self, content: str, top_k: int = 3) -> list[dict[str, Any]]:
        return self.query("case_base", content, top_k)


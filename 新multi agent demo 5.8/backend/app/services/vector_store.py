from __future__ import annotations

import os
from typing import Any

import chromadb
from chromadb.utils import embedding_functions

class VectorStore:
    COLLECTIONS = ("rule_base", "knowledge_base", "case_base")

    def __init__(
        self,
        persist_dir: str = "./data/chroma",
        embedding_model: str = "text-embedding-ada-002",
    ) -> None:
        self.client = chromadb.PersistentClient(path=persist_dir)
        api_key = os.getenv("OPENAI_API_KEY") or os.getenv("CHROMA_OPENAI_API_KEY")
        self.embed_fn = (
            embedding_functions.OpenAIEmbeddingFunction(
                api_key=api_key,
                model_name=embedding_model,
            )
            if api_key
            else None
        )
        self._collections = {
            "rule_base": self._get_or_create("rule_base"),
            "knowledge_base": self._get_or_create("knowledge_base"),
            "case_base": self._get_or_create("case_base"),
        }

    def _fake_embed(self, text: str, dim: int = 384) -> list[float]:
        base = abs(hash(text))
        return [float(((base >> (i % 16)) + i * 31) % 1000) / 1000.0 for i in range(dim)]

    def _get_or_create(self, name: str):
        try:
            if self.embed_fn is None:
                return self.client.get_collection(name=name)
            return self.client.get_collection(name=name, embedding_function=self.embed_fn)
        except Exception:
            if self.embed_fn is None:
                return self.client.create_collection(name=name)
            return self.client.create_collection(name=name, embedding_function=self.embed_fn)

    def add(
        self,
        collection: str,
        ids: list[str],
        documents: list[str],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> None:
        self._validate_collection(collection)
        if self.embed_fn is None:
            embs = [self._fake_embed(doc) for doc in documents]
            self._collections[collection].upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas or [{} for _ in ids],
                embeddings=embs,
            )
            return
        self._collections[collection].upsert(ids=ids, documents=documents, metadatas=metadatas or [{} for _ in ids])

    def add_one(
        self,
        collection: str,
        item_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.add(
            collection=collection,
            ids=[item_id],
            documents=[text],
            metadatas=[metadata or {}],
        )

    def delete(self, collection: str, ids: list[str]) -> None:
        self._validate_collection(collection)
        self._collections[collection].delete(ids=ids)

    def rebuild_collection(self, collection: str) -> None:
        """
        Rebuild a collection by re-creating it and re-upserting current rows.
        Useful after heavy deletes to compact internal index state.
        """
        self._validate_collection(collection)
        rows = self.get_all(collection)
        # Re-create collection object
        self.client.delete_collection(collection)
        self._collections[collection] = self._get_or_create(collection)
        if not rows:
            return
        ids = [str(r.get("id", "")) for r in rows]
        docs = [str(r.get("document", "")) for r in rows]
        metas = [dict(r.get("metadata") or {}) for r in rows]
        self.add(collection=collection, ids=ids, documents=docs, metadatas=metas)

    def update(
        self,
        collection: str,
        ids: list[str],
        documents: list[str],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> None:
        self.add(
            collection=collection,
            ids=ids,
            documents=documents,
            metadatas=metadatas,
        )

    def update_one(
        self,
        collection: str,
        item_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.update(
            collection=collection,
            ids=[item_id],
            documents=[text],
            metadatas=[metadata or {}],
        )

    def query(self, collection: str, text: str, top_k: int = 5) -> list[dict[str, Any]]:
        self._validate_collection(collection)
        if self.embed_fn is None:
            result = self._collections[collection].query(
                query_embeddings=[self._fake_embed(text)],
                n_results=top_k,
            )
        else:
            result = self._collections[collection].query(query_texts=[text], n_results=top_k)
        ids = result.get("ids", [[]])[0]
        docs = result.get("documents", [[]])[0]
        metas = result.get("metadatas", [[]])[0]
        dists = result.get("distances", [[]])[0] if isinstance(result, dict) else []
        merged = []
        for idx, item_id in enumerate(ids):
            merged.append(
                {
                    "id": item_id,
                    "document": docs[idx] if idx < len(docs) else "",
                    "metadata": metas[idx] if idx < len(metas) else {},
                    # Chroma distances: 越小越相似。此处仅透传，业务层可自行换算 similarity。
                    "distance": dists[idx] if idx < len(dists) else None,
                }
            )
        return merged

    def get_all(self, collection: str) -> list[dict[str, Any]]:
        self._validate_collection(collection)
        result = self._collections[collection].get()
        ids = result.get("ids", [])
        docs = result.get("documents", [])
        metas = result.get("metadatas", [])
        return [
            {
                "id": ids[idx] if idx < len(ids) else "",
                "document": docs[idx] if idx < len(docs) else "",
                "metadata": metas[idx] if idx < len(metas) else {},
            }
            for idx in range(len(ids))
        ]

    def _validate_collection(self, collection: str) -> None:
        if collection not in self.COLLECTIONS:
            raise ValueError(f"Unsupported collection: {collection}")


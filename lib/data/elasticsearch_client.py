"""Elasticsearch client for logging and data storage."""

from typing import Any, Dict, List, Optional

from elasticsearch import AsyncElasticsearch
from elasticsearch.exceptions import NotFoundError

from ..core.config import get_settings
from ..core.logger import get_logger

logger = get_logger(__name__)


class ElasticsearchClient:
    """Async Elasticsearch client wrapper."""

    def __init__(self):
        self._client: Optional[AsyncElasticsearch] = None
        self._settings = get_settings()

    async def connect(self) -> None:
        """Connect to Elasticsearch."""
        if self._client is None:
            self._client = AsyncElasticsearch([self._settings.es_url])
            logger.info("Elasticsearch connected", host=self._settings.es_host)

    async def disconnect(self) -> None:
        """Disconnect from Elasticsearch."""
        if self._client:
            await self._client.close()
            self._client = None
            logger.info("Elasticsearch disconnected")

    async def index(
        self,
        index: str,
        document: Dict[str, Any],
        doc_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Index a document."""
        await self.connect()
        full_index = f"{self._settings.es_index_prefix}_{index}"
        result = await self._client.index(
            index=full_index,
            id=doc_id,
            document=document,
        )
        logger.debug("Document indexed", index=full_index, id=result.get("_id"))
        return result

    async def get(
        self,
        index: str,
        doc_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Get a document by ID."""
        await self.connect()
        full_index = f"{self._settings.es_index_prefix}_{index}"
        try:
            result = await self._client.get(index=full_index, id=doc_id)
            return result["_source"]
        except NotFoundError:
            return None

    async def search(
        self,
        index: str,
        query: Optional[Dict[str, Any]] = None,
        size: int = 10,
        sort: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """Search documents."""
        await self.connect()
        full_index = f"{self._settings.es_index_prefix}_{index}"
        body = {"size": size}
        if query:
            body["query"] = query
        if sort:
            body["sort"] = sort
        return await self._client.search(index=full_index, body=body)

    async def delete(self, index: str, doc_id: str) -> bool:
        """Delete a document."""
        await self.connect()
        full_index = f"{self._settings.es_index_prefix}_{index}"
        try:
            await self._client.delete(index=full_index, id=doc_id)
            return True
        except NotFoundError:
            return False

    async def create_index(
        self,
        index: str,
        mappings: Optional[Dict[str, Any]] = None,
        settings: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Create an index with optional mappings."""
        await self.connect()
        full_index = f"{self._settings.es_index_prefix}_{index}"

        body = {}
        if settings:
            body["settings"] = settings
        if mappings:
            body["mappings"] = mappings

        try:
            await self._client.indices.create(index=full_index, body=body if body else None)
            logger.info("Index created", index=full_index)
            return True
        except Exception as e:
            if "already exists" in str(e).lower():
                logger.debug("Index already exists", index=full_index)
                return False
            raise

    async def health(self) -> Dict[str, Any]:
        """Get cluster health."""
        await self.connect()
        return await self._client.cluster.health()


# Global client
_es_client: Optional[ElasticsearchClient] = None


def get_es_client() -> ElasticsearchClient:
    """Get or create global Elasticsearch client."""
    global _es_client
    if _es_client is None:
        _es_client = ElasticsearchClient()
    return _es_client

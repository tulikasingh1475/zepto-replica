"""Pure retrieval: (query, city, hub ids) in, SKUs and scores out. No user knowledge.
Index design (per-city product docs, nested hubs[], flat active_hubs): Verified (Zepto/AWS).
Mapping details and lexical query: Ours."""
import os

from opensearchpy import OpenSearch

INDEX = os.getenv("OPENSEARCH_INDEX", "products")

MAPPING = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0, "refresh_interval": "10s"},
    "mappings": {"properties": {
        "city": {"type": "keyword"},
        "sku": {"type": "keyword"},
        "name": {"type": "text"},
        "brand": {"type": "text"},
        "category": {"type": "text"},
        "active_hubs": {"type": "keyword"},  # flat copy of active hub ids: fast filter
        "hubs": {"type": "nested", "properties": {
            "hub_id": {"type": "keyword"},
            "stock_status": {"type": "keyword"},
            "rpi_score": {"type": "float"},
            "active": {"type": "boolean"},
        }},
    }},
}


def client() -> OpenSearch:
    return OpenSearch(os.getenv("OPENSEARCH_URL", "http://localhost:9200"), timeout=3)


def retrieve(query: str, city: str, hub_ids: list[str], size: int = 20,
             index: str | None = None, os_client: OpenSearch | None = None) -> list[dict]:
    body = {
        "size": size,
        "_source": ["sku"],
        "query": {"bool": {
            "must": [{"multi_match": {
                "query": query,
                "fields": ["name^3", "brand^2", "category"],
                "fuzziness": "AUTO",
            }}],
            "filter": [{"term": {"city": city}}, {"terms": {"active_hubs": hub_ids}}],
        }},
    }
    res = (os_client or client()).search(index=index or INDEX, body=body)
    return [{"sku": h["_source"]["sku"], "score": h["_score"]} for h in res["hits"]["hits"]]

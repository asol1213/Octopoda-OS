"""
Local backend adapter for framework integrations.

Wraps a SynrixAgentBackend to match the cloud Agent API (.write/.read/.keys/.search),
so integrations can work in both local and cloud mode.
"""

import time
from typing import Any, Dict, List, Optional


def _unwrap_value(raw):
    """Unwrap backend storage format to get the actual value.

    Backend stores: {"value": X, "metadata": {...}, "timestamp": ...}
    or nested: {"data": {"value": X, ...}, "key": ..., "score": ...}
    We want to return just X (or the inner dict if X is a dict).
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        return raw

    # Format: {"data": {"value": X, ...}, "key": ..., "score": ...}
    if "data" in raw and isinstance(raw["data"], dict):
        inner = raw["data"]
        if "value" in inner:
            return inner["value"]
        return inner

    # Format: {"value": X, "metadata": ..., "timestamp": ...}
    if "value" in raw:
        return raw["value"]

    return raw


class _LocalAgentAdapter:
    """Adapts a local SynrixAgentBackend to the cloud Agent interface.

    Used when backend= is passed to integration constructors,
    enabling local-only usage without a cloud account.
    """

    def __init__(self, backend, agent_id: str = "local"):
        self.backend = backend
        self.agent_id = agent_id

    def write(self, key: str, value: Any, metadata: Optional[Dict] = None,
              tags: Optional[List[str]] = None) -> Dict:
        payload = value if isinstance(value, dict) else {"value": value}
        if tags:
            payload["_tags"] = tags
        nid = self.backend.write(key, payload)
        return {"node_id": nid, "key": key}

    def read(self, key: str) -> Optional[Any]:
        result = self.backend.read(key)
        return _unwrap_value(result)

    def keys(self, prefix: str = "", limit: int = 50) -> List[Dict]:
        results = self.backend.query_prefix(prefix, limit=limit)
        items = []
        for r in results:
            key = r.get("key", r.get("name", ""))
            value = _unwrap_value(r)
            items.append({"key": key, "value": value})
        return items

    def search(self, query: str, limit: int = 10) -> List[Dict]:
        # Local search falls back to prefix search — semantic search
        # requires embeddings which may not be installed
        return self.keys(prefix="", limit=limit)

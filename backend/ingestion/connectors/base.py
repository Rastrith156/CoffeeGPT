from __future__ import annotations

from abc import ABC, abstractmethod
from models.schemas import SourceDefinition


class BaseConnector(ABC):
    """Abstract base class for all data connectors.

    Fix #7: inherits ABC so @abstractmethod is properly enforced —
    subclasses that forget to implement fetch() raise TypeError at class
    creation time, not NotImplementedError at runtime.
    """
    name = ""
    description = ""

    def descriptor(self) -> SourceDefinition:
        return SourceDefinition(name=self.name, description=self.description, enabled=True)

    def _record(
        self,
        title: str,
        content: str,
        record_type: str,
        raw: dict,
        metadata: dict,
    ) -> dict:
        return {
            "title": title,
            "content": content,
            "record_type": record_type,
            "raw": raw,
            "metadata": metadata,
        }

    @abstractmethod
    async def fetch(self) -> list[dict]:  # pragma: no cover
        raise NotImplementedError(f"{type(self).__name__} must implement fetch()")

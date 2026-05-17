from typing import Generic, TypeVar, Any
from abc import ABC, abstractmethod
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

class BaseRepository(Generic[T], ABC):
    """Abstract base repository for database access."""
    
    @abstractmethod
    async def get_by_id(self, id: Any) -> T | None:
        pass

    @abstractmethod
    async def get_all(self, limit: int = 100, offset: int = 0) -> list[T]:
        pass

    @abstractmethod
    async def create(self, entity: T) -> T:
        pass

    @abstractmethod
    async def update(self, id: Any, entity: T) -> T:
        pass

    @abstractmethod
    async def delete(self, id: Any) -> bool:
        pass

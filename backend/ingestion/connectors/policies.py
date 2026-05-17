from __future__ import annotations

from .base import BaseConnector

class PolicyConnector(BaseConnector):
    name = "policies"
    description = "Government and buyer policy tracker"

    def __init__(self, news_service) -> None:
        self.news_service = news_service

    async def fetch(self) -> list[dict]:
        updates = await self.news_service.get_policy_updates()
        return [
            self._record(
                title=policy.title,
                content=f"{policy.country}: {policy.title}. Status: {policy.status}. Impact: {policy.impact}.",
                record_type="policy_update",
                raw=policy.model_dump(mode="json"),
                metadata={"source": self.name, "title": policy.title},
            )
            for policy in updates.policies
        ]

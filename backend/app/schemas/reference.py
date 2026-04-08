from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AreaItemOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int = Field(description="Идентификатор региона в API HeadHunter")
    name: str = Field(description="Название или путь в иерархии")


class AreasListOut(BaseModel):
    items: list[AreaItemOut]

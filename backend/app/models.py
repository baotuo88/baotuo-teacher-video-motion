"""Validated product inputs. No user supplied JavaScript or filesystem paths."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class Scene(StrictModel):
    title: str = Field(min_length=1, max_length=50)
    narration: str = Field(min_length=1, max_length=600)
    points: list[str] = Field(default_factory=list, max_length=4)
    layout: Literal['points', 'process', 'compare'] = 'points'
    duration: int = Field(default=5, ge=2, le=60)

    def model_post_init(self, __context):
        if any(not p.strip() or len(p) > 100 for p in self.points):
            raise ValueError('每个画面要点必须为 1–100 字')


class ProjectInput(StrictModel):
    title: str = Field(min_length=1, max_length=60)
    topic: str = Field(default='', max_length=5000)
    scenes: list[Scene] = Field(default_factory=list, max_length=30)
    style: Literal['whiteboard', 'study', 'chalkboard', 'warm-story', 'tech-dark'] = 'whiteboard'


class ProjectUpdate(ProjectInput):
    version: int = Field(ge=1)


class RenderRequest(StrictModel):
    version: int = Field(ge=1)
    audio: Literal['silent', 'edge'] = 'silent'
    voice: Literal['zh-CN-XiaoxiaoNeural', 'zh-CN-YunxiNeural', 'en-US-JennyNeural'] = 'zh-CN-XiaoxiaoNeural'
    fps: Literal[12, 24, 30] = 24
    idempotency_key: str = Field(min_length=16, max_length=100, pattern=r'^[a-zA-Z0-9_-]+$')


class ProviderInput(StrictModel):
    name: str = Field(min_length=1, max_length=60)
    base_url: str = Field(min_length=8, max_length=500)
    model: str = Field(min_length=1, max_length=100)
    api_key: str | None = Field(default=None, max_length=4096)
    enabled: bool = True


class GenerateRequest(StrictModel):
    version: int = Field(ge=1)
    provider_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    idempotency_key: str = Field(min_length=16, max_length=100, pattern=r'^[a-zA-Z0-9_-]+$')
    confirm_cost: bool

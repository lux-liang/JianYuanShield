from __future__ import annotations

from pydantic import BaseModel


class DemoRunRequest(BaseModel):
    sample_id: str = "sample_face_001"
    project: str = "LIDMark"
    attack: str = "multi_embedding+jpeg_50+blur"

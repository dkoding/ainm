from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SolveFile(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    filename: str = Field(min_length=1)
    content_base64: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)


class TripletexCredentials(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    base_url: str = Field(min_length=1)
    session_token: str = Field(min_length=1)


class SolveRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    prompt: str = Field(min_length=1)
    files: list[SolveFile] = Field(default_factory=list)
    tripletex_credentials: TripletexCredentials


class SolveResponse(BaseModel):
    status: str = "completed"

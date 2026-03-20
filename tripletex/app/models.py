from pydantic import BaseModel, ConfigDict, Field


class TripletexFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1)
    content_base64: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)


class TripletexCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str = Field(min_length=1)
    session_token: str = Field(min_length=1)


class SolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1)
    files: list[TripletexFile] = Field(default_factory=list)
    tripletex_credentials: TripletexCredentials


class SolveResponse(BaseModel):
    status: str = "completed"

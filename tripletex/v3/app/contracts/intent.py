from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _IntentModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class RouteHints(_IntentModel):
    flowNames: list[str] = Field(default_factory=list)
    commandNames: list[str] = Field(default_factory=list)
    operationIds: list[str] = Field(default_factory=list)
    technicalFlowFamilies: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    subdomains: list[str] = Field(default_factory=list)
    selectorFamilies: list[str] = Field(default_factory=list)
    payloadFamilies: list[str] = Field(default_factory=list)


class IntentDocument(_IntentModel):
    contractVersion: Literal["tripletex.intent.v1"]
    intentSummary: str | None = None
    taskFamilies: list[str] = Field(default_factory=list)
    targetResources: list[str] = Field(default_factory=list)
    operations: list[str] = Field(default_factory=list)
    routeHints: RouteHints = Field(default_factory=RouteHints)
    needsMutation: bool | None = None
    needsResolution: bool | None = None
    attachmentRelevant: bool | None = None
    confidence: float | None = None
    ambiguities: list[str] = Field(default_factory=list)
    missingData: list[str] = Field(default_factory=list)

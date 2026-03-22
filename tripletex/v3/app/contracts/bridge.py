from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _BridgeModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class RequestContext(_BridgeModel):
    requestId: str | None = None
    receivedAt: str | None = None
    currentDate: str | None = None
    timezone: str | None = None
    promptCharCount: int | None = None
    attachmentCount: int | None = None
    hasTripletexCredentials: bool | None = None
    baseUrlPresent: bool | None = None
    sessionTokenPresent: bool | None = None


class LanguageContext(_BridgeModel):
    detectedPrimaryLanguage: str | None = None
    detectedLanguages: list[str] = Field(default_factory=list)
    canonicalLanguage: str | None = None
    promptOriginal: str | None = None
    promptCanonical: str | None = None
    translationNotes: list[str] = Field(default_factory=list)
    translationConfidence: float | None = None
    relativeDateAnchor: dict[str, Any] = Field(default_factory=dict)


class UnderstandingSection(_BridgeModel):
    objective: str | None = None
    intentSummary: str | None = None
    taskFamilies: list[str] = Field(default_factory=list)
    targetResources: list[str] = Field(default_factory=list)
    operations: list[str] = Field(default_factory=list)
    priority: str | None = None
    riskLevel: str | None = None
    ambiguities: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    missingData: list[str] = Field(default_factory=list)
    attachmentRequired: bool | None = None


class SourcesSection(_BridgeModel):
    prompt: str | None = None
    attachments: list[dict[str, Any]] = Field(default_factory=list)


class RichDataSection(_BridgeModel):
    entities: dict[str, Any] = Field(default_factory=dict)
    relations: list[dict[str, Any]] = Field(default_factory=list)
    scalarFacts: dict[str, Any] = Field(default_factory=dict)
    evidenceIndex: dict[str, Any] = Field(default_factory=dict)


class FlatBridgeSection(_BridgeModel):
    primaryEntityRefs: dict[str, str] = Field(default_factory=dict)
    fieldBag: dict[str, Any] = Field(default_factory=dict)
    byEntityId: dict[str, dict[str, Any]] = Field(default_factory=dict)
    flowArguments: dict[str, dict[str, Any]] = Field(default_factory=dict)
    commandArguments: dict[str, dict[str, Any]] = Field(default_factory=dict)


class FlowStep(_BridgeModel):
    stepId: str | None = None
    flowName: str | None = None
    name: str | None = None
    flowType: str | None = None
    kind: str | None = None
    why: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    dependsOn: list[str] = Field(default_factory=list)
    expectedOutputs: list[str] = Field(default_factory=list)
    confidence: float | None = None

    @property
    def resolved_name(self) -> str:
        return self.flowName or self.name or ""

    @property
    def resolved_kind(self) -> str:
        return self.flowType or self.kind or "business_flow"


class CommandStep(_BridgeModel):
    stepId: str | None = None
    commandName: str | None = None
    command: str | None = None
    commandType: str | None = None
    kind: str | None = None
    operationId: str | None = None
    parentFlowStepId: str | None = None
    why: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    dependsOn: list[str] = Field(default_factory=list)
    expectedOutputs: list[str] = Field(default_factory=list)
    confidence: float | None = None
    purpose: str | None = None

    @property
    def resolved_name(self) -> str:
        return self.commandName or self.command or self.operationId or ""

    @property
    def resolved_kind(self) -> str:
        return self.commandType or self.kind or "friendly_alias"


class ExecutionPlanSection(_BridgeModel):
    selectedFlows: list[FlowStep] = Field(default_factory=list)
    selectedCommands: list[CommandStep] = Field(default_factory=list)
    fallbackRawCommands: list[CommandStep] = Field(default_factory=list)
    stepOrder: list[str] = Field(default_factory=list)


class ValidationSection(_BridgeModel):
    isExecutable: bool = True
    blockingIssues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    missingRequiredData: list[str] = Field(default_factory=list)
    highRiskActions: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    confidenceSummary: str | None = None


class CompletionSection(_BridgeModel):
    completionSignals: list[str] = Field(default_factory=list)
    expectedArtifacts: list[str] = Field(default_factory=list)
    postconditions: list[str] = Field(default_factory=list)
    verificationHints: list[str] = Field(default_factory=list)


class LLMBridgeDocument(_BridgeModel):
    contractVersion: Literal["tripletex.llm_bridge.v1"]
    requestContext: RequestContext = Field(default_factory=RequestContext)
    language: LanguageContext = Field(default_factory=LanguageContext)
    understanding: UnderstandingSection = Field(default_factory=UnderstandingSection)
    sources: SourcesSection = Field(default_factory=SourcesSection)
    richData: RichDataSection = Field(default_factory=RichDataSection)
    flatBridge: FlatBridgeSection = Field(default_factory=FlatBridgeSection)
    executionPlan: ExecutionPlanSection = Field(default_factory=ExecutionPlanSection)
    validation: ValidationSection = Field(default_factory=ValidationSection)
    completion: CompletionSection = Field(default_factory=CompletionSection)

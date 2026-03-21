from __future__ import annotations

import logging
import os
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.contracts import ExecutionContext, ExecutionResult, SolveRequest
from app.llm import LLMPlanner
from app.router import BridgeRouter


logger = logging.getLogger("tripletex_solver")


class SolveService:
    def __init__(self, planner: LLMPlanner | None = None, router: BridgeRouter | None = None) -> None:
        self.planner = planner or LLMPlanner()
        self.router = router or BridgeRouter()
        self.timezone_name = os.getenv("TRIPLETEX_TIMEZONE", "Europe/Oslo")

    def execute(self, request: SolveRequest) -> ExecutionResult:
        request_id = str(uuid4())
        zone = ZoneInfo(self.timezone_name)
        now = datetime.now(zone)
        current_date = now.date().isoformat()
        bridge = self.planner.plan(
            request,
            current_date=current_date,
            timezone=self.timezone_name,
            request_id=request_id,
        )
        if bridge.requestContext.requestId is None:
            bridge.requestContext.requestId = request_id
        if bridge.requestContext.currentDate is None:
            bridge.requestContext.currentDate = current_date
        if bridge.requestContext.timezone is None:
            bridge.requestContext.timezone = self.timezone_name
        if bridge.requestContext.promptCharCount is None:
            bridge.requestContext.promptCharCount = len(request.prompt)
        if bridge.requestContext.attachmentCount is None:
            bridge.requestContext.attachmentCount = len(request.files)
        if bridge.requestContext.hasTripletexCredentials is None:
            bridge.requestContext.hasTripletexCredentials = True
        if bridge.requestContext.baseUrlPresent is None:
            bridge.requestContext.baseUrlPresent = bool(request.tripletex_credentials.base_url)
        if bridge.requestContext.sessionTokenPresent is None:
            bridge.requestContext.sessionTokenPresent = bool(request.tripletex_credentials.session_token)

        execution_context = ExecutionContext(
            base_url=request.tripletex_credentials.base_url,
            session_token=request.tripletex_credentials.session_token,
            request_id=request_id,
            current_date=current_date,
            timezone=self.timezone_name,
        )
        result = self.router.execute(bridge, execution_context)
        logger.info("solve.executed request_id=%s steps=%s", request_id, len(result.traces))
        return result

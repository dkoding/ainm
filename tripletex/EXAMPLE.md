# Example Solve Flow

This document shows one concrete example of how the `/solve` bridge should work.

It follows the design in:

- `DESC.md`
- `LLM.md`
- `docs/openapi.json`

## Example Request

Incoming human prompt:

```text
Hei jeg klarer ikke å finne timelisten min, kan du sjekke hvor mange timer jeg jobbet i februar
```

## High-Level Result

The intended execution chain is:

`HUMAN -> LLM -> JSON -> FLOWS/COMMANDS -> Tripletex`

For this request, the expected plan is:

- `1` LLM operation
- `1` primary Tripletex API call
- technical flow family: `timesheet.entry.read`
- raw command: `TimesheetEntryTotalHours_getTotalHours`

If the executor wants an extra identity verification step, it may prepend:

- `session.who_am_i`

That would make the Tripletex side `2` API calls instead of `1`, but the LLM side is still `1`.

## Step-By-Step

### 1. `/solve` receives the request

Input contains:

- `prompt`
- optional `files[]`
- `tripletex_credentials`

For this example:

- prompt language is Norwegian
- there are no attachments
- the request is read-only

### 2. The LLM detects language and normalizes meaning

Original:

```text
Hei jeg klarer ikke å finne timelisten min, kan du sjekke hvor mange timer jeg jobbet i februar
```

Canonical internal meaning:

```text
I cannot find my timesheet. Can you check how many hours I worked in February?
```

The bridge keeps both:

- original text
- canonical normalized meaning

### 3. The LLM extracts intent

The request means:

- domain: `timesheet`
- user intent: `search` + `report`
- target: total worked hours
- actor: the authenticated user, because the prompt says `min` / `my`
- time period: `February`

### 4. The LLM resolves relative time

Using the request date anchor:

- current date: `2026-03-21`
- timezone: `Europe/Oslo`

The phrase `i februar` becomes:

- `monthYear = 2026-02`
- `startDate = 2026-02-01`
- `endDate = 2026-03-01`

Important:

- for `GET /timesheet/entry/>totalHours`, `endDate` is exclusive
- so the correct February range is `2026-02-01` to `2026-03-01`

### 5. The LLM chooses flow and command

According to `DESC.md` routing rules:

1. prefer a hand-authored business flow if one exists
2. otherwise use a friendly command alias if one exists
3. otherwise use the exact raw `operationId`

For this request:

- there is no hand-authored business flow specifically for this timesheet reporting task
- the task falls into the technical flow family `timesheet.entry.read`
- the correct raw command is `TimesheetEntryTotalHours_getTotalHours`

Mapped Tripletex endpoint:

- `GET /timesheet/entry/>totalHours`

### 6. The LLM emits the bridge JSON

Representative JSON:

```json
{
  "contractVersion": "tripletex.llm_bridge.v1",
  "language": {
    "detectedPrimaryLanguage": "nb",
    "canonicalLanguage": "en",
    "promptOriginal": "Hei jeg klarer ikke å finne timelisten min, kan du sjekke hvor mange timer jeg jobbet i februar",
    "promptCanonical": "I cannot find my timesheet. Can you check how many hours I worked in February?",
    "relativeDateAnchor": {
      "currentDate": "2026-03-21",
      "timezone": "Europe/Oslo"
    }
  },
  "understanding": {
    "objective": "Return total hours worked by the authenticated employee in February 2026.",
    "intentSummary": "Read-only timesheet reporting request for the current user.",
    "taskFamilies": ["timesheet", "reporting", "self_service"],
    "targetResources": ["timesheet.entry"],
    "operations": ["search", "report"],
    "assumptions": [
      "'my' refers to the token owner",
      "'February' resolves to February 2026 from the request anchor date"
    ],
    "missingData": [],
    "attachmentRequired": false
  },
  "richData": {
    "scalarFacts": {
      "monthYear": {
        "value": "2026-02",
        "kind": "derived"
      },
      "startDate": {
        "value": "2026-02-01",
        "kind": "derived"
      },
      "endDate": {
        "value": "2026-03-01",
        "kind": "derived"
      },
      "employeeScope": {
        "value": "token_owner",
        "kind": "inferred"
      }
    }
  },
  "flatBridge": {
    "fieldBag": {
      "monthYear": "2026-02",
      "startDate": "2026-02-01",
      "endDate": "2026-03-01",
      "employeeScope": "token_owner",
      "requestWantsTotalHours": true
    },
    "commandArguments": {
      "TimesheetEntryTotalHours_getTotalHours": {
        "startDate": "2026-02-01",
        "endDate": "2026-03-01"
      }
    }
  },
  "executionPlan": {
    "selectedFlows": [],
    "selectedCommands": [],
    "fallbackRawCommands": [
      {
        "stepId": "step_1",
        "commandType": "raw_operation",
        "operationId": "TimesheetEntryTotalHours_getTotalHours",
        "purpose": "Get total worked hours for the token owner in February 2026"
      }
    ],
    "stepOrder": ["step_1"]
  },
  "validation": {
    "isExecutable": true,
    "blockingIssues": [],
    "warnings": [
      "The year for 'February' was derived from the request anchor date 2026-03-21."
    ]
  }
}
```

### 7. The executor runs the command

Using the JSON above, the executor calls:

```text
TimesheetEntryTotalHours_getTotalHours
```

with:

- `startDate = 2026-02-01`
- `endDate = 2026-03-01`

It may omit `employeeId`, because the OpenAPI description says it defaults to the token owner.

### 8. Tripletex returns the result

The raw response shape for this operation is:

```json
{
  "value": 123.5
}
```

The actual number depends on the company data in the sandbox or production environment.

### 9. The final human answer is produced

Example human-facing answer in Norwegian:

```text
Du jobbet 123,5 timer i februar 2026.
```

## Operation Count

### Minimal correct path

- LLM operations: `1`
- Tripletex API calls: `1`

Sequence:

1. LLM emits bridge JSON
2. executor calls `TimesheetEntryTotalHours_getTotalHours`

### Defensive path

- LLM operations: `1`
- Tripletex API calls: `2`

Sequence:

1. LLM emits bridge JSON
2. executor calls `session.who_am_i`
3. executor calls `TimesheetEntryTotalHours_getTotalHours`

## Why This Example Matters

This example shows the intended behavior of the bridge:

- one LLM call performs language understanding, extraction, normalization, planning, and argument binding
- the output JSON is execution-ready
- the executor does not need to reinterpret free text
- raw OpenAPI `operationId` commands remain usable even when no hand-authored business flow exists

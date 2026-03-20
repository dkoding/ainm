# Delta Remediation Checklist

This file turns the final documentation/spec review into concrete remediation tasks.

- [x] Make planner reach spec-driven instead of relying on a partial hardcoded resource map.
  Scope:
  Expand resource-prefix selection to the full OpenAPI surface, keep semantic multi-resource bundles for common workflows, and add multilingual/domain keyword coverage so non-core Tripletex domains become reachable.
  Result:
  The planner now derives fallback reach from all primary OpenAPI prefixes and adds dynamic keyword matching for the full spec surface, while preserving semantic bundles for workflows such as timesheets, invoicing, travel, purchase orders, salary, inventory, and assets.

- [x] Remove planner hint truncation that keeps valid generated methods out of reach.
  Scope:
  Stop limiting the generated method list to a narrow prefix-order slice. The planner should see the full matched generated-method set for the selected resource families.
  Result:
  Generated method hints now allow `limit=None`, and the planner uses the full matched generated-method set instead of a narrow prefix-ordered subset.

- [x] Encode Tripletex write semantics for existing related objects.
  Scope:
  Follow the Tripletex documentation rule that existing linked objects should normally be referenced by internal `id` values during POST/PUT workflows. Add planner/runtime guidance and generic body repair where history already contains the resolved IDs.
  Result:
  The runtime now includes explicit Tripletex reference-resolution rules and repairs nested write bodies to reuse resolved IDs from history for common linked entities such as customer, supplier, employee, project, department, activity, product, payment type, VAT type, ledger account, contact, division, currency, and asset.

- [x] Improve generated-method metadata for non-trivial request bodies.
  Scope:
  Expose body schema shape and nested field summaries so array bodies and nested object arguments remain plannable instead of collapsing into an opaque payload with no structure.
  Result:
  Generated method hints now include argument schema types, nested field names, nested required fields, and request-body style/requiredness so raw and array payload methods remain plannable.

- [x] Verify the full delta set and deploy the final revision.
  Scope:
  Re-run spec audits, compile the app, update this checklist with completion state, and deploy the resulting revision.
  Result:
  `python3 -m compileall /mnt/d/work/ainm/tripletex/app` passed.
  The saved OpenAPI audit confirms `800/800` operations are covered by the primary-prefix fallback model.
  The service is deployed as revision `tripletex-agent-00015-x2f`.
  Health check passed at `https://tripletex-agent-87381792866.europe-north1.run.app/health`.

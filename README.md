# NM i AI 2026 Workspace

This workspace is split into one directory per task:

- `tripletex/`: Cloud Run-ready HTTPS service for the Tripletex `/solve` submission format.
- `astar/`: API task scaffold for Astar Island with docs, batch runner, artifact capture, and Cloud Run Job support.
- `norgesgruppen-data/`: Submission template and local validator for the offline zip upload task.

Manual steps still required on your side:

- Tripletex: fetch the sandbox account and later submit the deployed HTTPS URL from the logged-in app.
- Astar: copy your `access_token` JWT from the browser after logging in at `app.ainm.no`.
- NorgesGruppen Data: download the dataset and product reference images from the logged-in submit page.

The scaffolds below are aligned with the public docs at `https://app.ainm.no/docs` as of March 20, 2026.

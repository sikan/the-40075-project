# Project instructions

- Concept2 Logbook is strictly read-only. Never create, edit, or delete anything in the user's Concept2 account. Only use GET requests to the official API; never submit a form that changes logbook data or settings.
- The user handles all code and documentation commits and pushes. Do not commit or push on their behalf. The sole exception is the repository's GitHub Actions workflow, which may commit and push changes under `data/archive/` after a successful read-only sync.
- Keep API credentials in the ignored `.secrets/` directory or environment variables. Never print them or include them in public files.
- The original API archive under `data/archive/` is intentionally public and tracked. The generated website remains an explicit projection in ignored `dist/`; credentials must never enter either location.
- Prioritize data accuracy and a working rough website before visual polish.

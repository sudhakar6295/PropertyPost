# PropertyPost permanent engineering rules

- Use `uv` for every Python command, dependency operation, script, test, migration, and
  management command. Do not invoke `python`, `pip`, `pytest`, `ruff`, or Django executables
  directly.
- Never expose secrets in source code, logs, templates, tests, commits, screenshots, or
  messages. Keep local secrets in ignored environment files and require production secrets
  through the environment.
- Keep public property/listing information structurally separate from private owner,
  contact, legal, and operational information. Public code paths must not query or render
  private fields unless access is explicitly authorized and tested.
- Test every implementation. Add or update automated tests with each behavior change and
  run the relevant test and quality suites before handoff.
- Preserve user changes. Inspect the working tree before editing, avoid unrelated changes,
  and never discard or overwrite user work without explicit approval.
- Keep total infrastructure cost below ₹2,000 per month. Document estimated recurring cost
  before introducing infrastructure or paid services.
- Make.com integration is intentionally deferred to a later stage. Do not add Make.com
  webhooks, credentials, dependencies, or workflows yet.
- Do not create `requirements.txt`; `pyproject.toml` and `uv.lock` are the dependency source
  of truth unless a verified deployment target genuinely requires a requirements export.

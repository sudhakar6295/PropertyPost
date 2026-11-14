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
- Use MySQL 8 in Docker Compose locally and the separate Hostinger MySQL database in
  production. Do not use SQLite, PostgreSQL, Cloud SQL, or Firestore as the application
  database.
- Keep local MySQL credentials in the ignored `.env`; use placeholders in `.env.example`.
  Production DB credentials belong in Google Secret Manager. Never put them in GitHub,
  source, build arguments, container layers, logs, or messages.
- Keep local and production databases separate. Never connect local development commands
  to production. Do not run production migrations automatically at container startup.
- Preserve the local Docker named database volume. Never remove it or migrate production
  data without explicit approval.
- Test every implementation. Add or update automated tests with each behavior change and
  run the relevant test and quality suites before handoff.
- Preserve user changes. Inspect the working tree before editing, avoid unrelated changes,
  and never discard or overwrite user work without explicit approval.
- Keep total infrastructure cost below ₹2,000 per month. Document estimated recurring cost
  before introducing infrastructure or paid services.
- Make.com is connected only through the configured, secret-backed webhook and versioned
  API. Keep private listing data out of webhook events. Do not add Facebook publishing
  until the broker approval and publication callback flow is explicitly implemented.
- Do not create `requirements.txt`; `pyproject.toml` and `uv.lock` are the dependency source
  of truth unless a verified deployment target genuinely requires a requirements export.

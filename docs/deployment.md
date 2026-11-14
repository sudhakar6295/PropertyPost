# GitHub Actions production deployment

CI runs on pushes to `main` and manual dispatch. It starts a disposable MySQL 8 service, installs locked dependencies with `uv`, runs Ruff and pytest, builds the Docker image, and scans committed history. The deployment workflow runs only after a successful CI workflow for `main`; it checks out the exact tested commit and uses GitHub OIDC through Workload Identity Federation.

In the repository's GitHub **production environment**, configure these variables:

- `GCP_PROJECT_ID`
- `GCP_REGION`
- `GAR_REPOSITORY`
- `CLOUD_RUN_SERVICE`
- `GCP_WORKLOAD_IDENTITY_PROVIDER`
- `GCP_DEPLOY_SERVICE_ACCOUNT`

There are no GitHub secrets for Google or MySQL. GitHub receives no long-lived cloud credential or database password. Runtime secrets must be present in Google Secret Manager before deployment: Django secret key, automation HMAC key, Firebase web API key, and the four Hostinger MySQL connection values. The Cloud Run runtime service account needs `secretAccessor` on those secrets and permission to read/write the private GCS bucket.

Configure the production environment with required reviewers if manual production approval is desired. The workflow creates a candidate revision with zero traffic, checks database readiness and health, and switches traffic only after those checks succeed. It uses minimum instances zero, one CPU, 512 MiB memory, a 60-second timeout, concurrency 20 and maximum two instances.

Production login uses Firebase Authentication. Cloud Run stays protected by IAM; grant invocation to the intended front door or users through the approved access design. No deployment or cloud permission changes are made by editing this workflow.

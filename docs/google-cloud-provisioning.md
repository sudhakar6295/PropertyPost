# Google Cloud provisioning status

The application now uses Hostinger MySQL, not Firestore, PostgreSQL or Cloud SQL. See [google-cloud-setup.md](google-cloud-setup.md) for the approved architecture and [deployment.md](deployment.md) for GitHub Actions configuration.

The repeatable script at `scripts/provision_gcp.ps1` does not provision Firestore. It can still create Google Cloud Storage, Artifact Registry, Secret Manager containers, service accounts and GitHub Workload Identity Federation. Do not run it with `-Apply` without explicit approval. No cloud resources were changed by the local MySQL code update.

Production database credentials are separate Secret Manager values for the Hostinger host, database, user and password. No database credentials belong in GitHub or the repository. The workflow does not run migrations automatically.

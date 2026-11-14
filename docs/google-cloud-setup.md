# Google Cloud and Hostinger setup

PropertyPost production runs Django on Cloud Run, stores original photographs and generated posters in a private Google Cloud Storage bucket, uses Django authentication, and connects to a separate Hostinger MySQL database. It does not use Firestore, PostgreSQL or Cloud SQL.

## Database credentials

Create these Secret Manager secrets in the Google Cloud project and add values only after obtaining the Hostinger database connection details:

- `propertypost-mysql-host`
- `propertypost-mysql-database`
- `propertypost-mysql-user`
- `propertypost-mysql-password`

Store `DJANGO_SECRET_KEY` and `AUTOMATION_HMAC_SECRET` in their named Secret Manager secrets too. The deployment workflow attaches secret versions to Cloud Run as environment variables. Configure the Hostinger service to accept connections from Cloud Run and require TLS. If a custom certificate authority is required, mount a trusted CA certificate into the container and set `MYSQL_SSL_CA` to its path. Do not put these values in GitHub, source files, Docker build arguments, or the image.

The database must be separately backed up and sized. Keep all infrastructure spending below ₹2,000/month; verify the existing Hostinger plan and Cloud costs before deployment. This repository does not contact Hostinger or run production migrations.

## Google Cloud resources

The existing infrastructure script is `scripts/provision_gcp.ps1`. It can prepare the private Storage bucket, Artifact Registry, Secret Manager containers, service accounts, and GitHub Workload Identity Federation. It no longer provisions a document database or grants a document database IAM role. Its MySQL Secret Manager entries are empty containers until values are added. Running it with `-Apply` changes cloud resources and is a separate, explicitly approved operation; no cloud resources were changed as part of the code update.

The runtime service account needs object read/write access to the private bucket and Secret Manager access only to the PropertyPost runtime secrets. The GitHub deployer uses OIDC through Workload Identity Federation, pushes images to Artifact Registry, and deploys the Cloud Run service. Do not create service-account JSON keys.

The deployment workflow builds the exact CI commit, deploys its SHA-tagged image with zero minimum instances and conservative limits, holds it at zero traffic, then checks `/health/` and `/ready/` with a Google identity token. Only a passing revision receives production traffic. Until valid Secret Manager versions are added and Hostinger permits the Cloud Run connection, readiness should fail and the current serving revision will retain traffic.

No service account, Cloud Run service, bucket, database, or other cloud resource was created, deleted or modified during this code change.

# PropertyPost Google Cloud provisioning

Run `scripts/provision_gcp.ps1` from the project root to inspect the plan. Pass `-Apply`
to create missing resources and IAM bindings. The script checks that the project ID and
number match before any changes. Repeated runs leave existing resources in place.

Target: `praxis-citron-469206-c8` (`105269730029`), region `asia-south1` (Mumbai).
The project is shared with Algotrade; PropertyPost uses dedicated names and identities.

| Resource | Name and configuration |
| --- | --- |
| Firestore | Native mode, `(default)`, `asia-south1`, delete protection enabled |
| Private Storage | `gs://propertypost-private-105269730029`, Standard, uniform bucket IAM, public access prevention enforced, seven-day soft delete |
| Artifact Registry | Docker repository `propertypost` in `asia-south1` |
| Runtime service account | `propertypost-runtime@praxis-citron-469206-c8.iam.gserviceaccount.com` |
| Deployment service account | `propertypost-deployer@praxis-citron-469206-c8.iam.gserviceaccount.com` |
| Workload Identity Federation | Pool `propertypost-github`, OIDC provider `github`, GitHub issuer, restricted to `sudhakar6295/PropertyPost` on `refs/heads/main` |
| Secret Manager | Empty regional secrets `propertypost-django-secret-key`, `propertypost-automation-hmac-secret`, `propertypost-database-url`, `propertypost-firebase-web-api-key`, `propertypost-gemini-api-key` |

No secret versions or service-account keys are created. The Gemini key belongs in its
Google Secret Manager secret; it must not be copied into GitHub. Add secret versions
through a trusted local or console session, never through committed files.

## Access boundaries

- Runtime: Firestore `roles/datastore.user` on this project; object create and read on
  the PropertyPost bucket; `roles/secretmanager.secretAccessor` on each PropertyPost
  secret. It has no Artifact Registry write or deployment role.
- Deployment: `roles/artifactregistry.writer` on the PropertyPost repository and
  `roles/iam.serviceAccountUser` on the runtime account. GitHub can impersonate only
  this account through `roles/iam.workloadIdentityUser` on the deployment account.
- Cloud Run Developer is granted on the `propertypost` service only when that service
  exists. The script deliberately avoids a project-wide Cloud Run role, which would
  permit changes to Algotrade services. No Cloud Run service is deployed at this stage.

The manual `verify-gcp-oidc.yml` workflow checks GitHub OIDC by reading the Artifact
Registry repository. It does not deploy or read any secret values. GitHub repository
variables needed for that workflow and future deployment:

| Variable | Value |
| --- | --- |
| `GCP_PROJECT_ID` | `praxis-citron-469206-c8` |
| `GCP_REGION` | `asia-south1` |
| `GAR_REPOSITORY` | `propertypost` |
| `CLOUD_RUN_SERVICE` | `propertypost` |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | `projects/105269730029/locations/global/workloadIdentityPools/propertypost-github/providers/github` |
| `GCP_DEPLOY_SERVICE_ACCOUNT` | `propertypost-deployer@praxis-citron-469206-c8.iam.gserviceaccount.com` |

GitHub secrets required: **none**. The repository has no configured Git remote or
GitHub API authentication in this workspace, so these variables must be entered in
the GitHub repository settings. The OIDC workflow must run from the `main` branch.

## Cost and deployment boundary

Current estimate is approximately ₹0/month for these **empty, idle** resources:
the bucket and repository contain no objects, secret containers have no versions,
Firestore has no documents, and no Cloud Run service exists. Once used, photo storage,
seven-day soft-deleted objects, downloads, Firestore operations, image retention,
Secret Manager access, Cloud Run requests, and logging can incur charges. Free quotas
can be shared with other projects on the billing account. Set a project budget below
₹2,000 with alerts, but do not treat alerts as a hard spending cap.

The production Django configuration still requires PostgreSQL. Firestore provisioning
does not remove that dependency. Resolve the database design and estimate its cost
before a Cloud Run deployment. Firebase Authentication configuration and secret values
also remain prerequisites. No Make.com or Facebook integration is included.

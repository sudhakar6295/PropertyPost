param(
    [switch]$Apply,
    [string]$ProjectId = 'praxis-citron-469206-c8',
    [string]$ProjectNumber = '105269730029',
    [string]$Region = 'asia-south1',
    [string]$GitHubRepository = 'sudhakar6295/PropertyPost'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($ProjectId -notmatch '^[a-z][a-z0-9-]{4,28}[a-z0-9]$') { throw 'Invalid project ID.' }
if ($ProjectNumber -notmatch '^\d+$') { throw 'Invalid project number.' }
if ($Region -notmatch '^[a-z]+-[a-z]+\d+$') { throw 'Invalid region.' }
if ($GitHubRepository -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') {
    throw 'GitHubRepository must be owner/repository.'
}

$bucket = "propertypost-private-$ProjectNumber"
$repository = 'propertypost'
$runtimeId = 'propertypost-runtime'
$deployerId = 'propertypost-deployer'
$runtimeEmail = "$runtimeId@$ProjectId.iam.gserviceaccount.com"
$deployerEmail = "$deployerId@$ProjectId.iam.gserviceaccount.com"
$pool = 'propertypost-github'
$provider = 'github'
$secretNames = @(
    'propertypost-django-secret-key',
    'propertypost-automation-hmac-secret',
    'propertypost-mysql-host',
    'propertypost-mysql-database',
    'propertypost-mysql-user',
    'propertypost-mysql-password',
    'propertypost-gemini-api-key'
)
$providerName = "projects/$ProjectNumber/locations/global/workloadIdentityPools/$pool/providers/$provider"
$principal = "principalSet://iam.googleapis.com/projects/$ProjectNumber/locations/global/workloadIdentityPools/$pool/attribute.repository/$GitHubRepository"

function Invoke-Gcloud {
    param([string[]]$Arguments)
    & gcloud @Arguments --quiet
    if ($LASTEXITCODE -ne 0) { throw "gcloud failed: $($Arguments -join ' ')" }
}

function Get-GcloudLines {
    param([string[]]$Arguments)
    $result = @(& gcloud @Arguments --quiet)
    if ($LASTEXITCODE -ne 0) { throw "gcloud failed: $($Arguments -join ' ')" }
    return $result
}

function Ensure-ListedResource {
    param([string]$Name, [string[]]$ListArguments, [string[]]$CreateArguments)
    $existing = @(Get-GcloudLines $ListArguments)
    if ($existing | Where-Object { $_ -eq $Name -or $_ -like "*/$Name" }) {
        Write-Output "Exists: $Name"
    } else {
        Write-Output "Creating: $Name"
        Invoke-Gcloud $CreateArguments | Out-Null
    }
}

$actualNumber = (Get-GcloudLines @('projects', 'describe', $ProjectId, '--format=value(projectNumber)') | Select-Object -First 1).Trim()
if ($actualNumber -ne $ProjectNumber) { throw 'Project ID and number do not match.' }
$billing = (Get-GcloudLines @('billing', 'projects', 'describe', $ProjectId, '--format=value(billingEnabled)') | Select-Object -First 1).Trim()
if ($billing -ne 'True') { throw 'Billing is not enabled on the target project.' }

Write-Output "Project: $ProjectId ($ProjectNumber)"
Write-Output "Region: $Region"
Write-Output "GitHub trust: $GitHubRepository, refs/heads/main"
Write-Output "Private bucket: gs://$bucket"
Write-Output "Artifact Registry: $Region-docker.pkg.dev/$ProjectId/$repository"
Write-Output "Service accounts: $runtimeEmail, $deployerEmail"
Write-Output "Empty Secret Manager containers: $($secretNames -join ', ')"
Write-Output "OIDC provider: $providerName"
if (-not $Apply) {
    Write-Output 'Plan only. Pass -Apply to provision the listed resources and IAM bindings.'
    return
}

$requiredApis = @('artifactregistry.googleapis.com',
    'secretmanager.googleapis.com', 'run.googleapis.com', 'iam.googleapis.com',
    'iamcredentials.googleapis.com', 'sts.googleapis.com', 'storage.googleapis.com')
$enabledApis = @(Get-GcloudLines @('services', 'list', '--enabled', "--project=$ProjectId",
    '--format=value(config.name)'))
$missingApis = @($requiredApis | Where-Object { $enabledApis -notcontains $_ })
if ($missingApis.Count -gt 0) {
    Invoke-Gcloud (@('services', 'enable') + $missingApis + "--project=$ProjectId") | Out-Null
}

Ensure-ListedResource $bucket @('storage', 'buckets', 'list', "--project=$ProjectId", '--format=value(name)') `
    @('storage', 'buckets', 'create', "gs://$bucket", "--project=$ProjectId", "--location=$Region",
      '--default-storage-class=STANDARD', '--uniform-bucket-level-access',
      '--public-access-prevention', '--soft-delete-duration=7d')

Ensure-ListedResource $repository @('artifacts', 'repositories', 'list', "--project=$ProjectId",
    "--location=$Region", '--format=value(name)') @('artifacts', 'repositories', 'create', $repository,
    '--repository-format=docker', "--location=$Region", "--project=$ProjectId",
    '--description=PropertyPost container images')

$accounts = @(Get-GcloudLines @('iam', 'service-accounts', 'list', "--project=$ProjectId", '--format=value(email)'))
foreach ($account in @(@($runtimeId, $runtimeEmail), @($deployerId, $deployerEmail))) {
    if ($accounts -contains $account[1]) {
        Write-Output "Exists: $($account[1])"
    } else {
        Write-Output "Creating: $($account[1])"
        Invoke-Gcloud @('iam', 'service-accounts', 'create', $account[0], "--project=$ProjectId",
            "--display-name=PropertyPost $($account[0])") | Out-Null
    }
}

foreach ($secret in $secretNames) {
    Ensure-ListedResource $secret @('secrets', 'list', "--project=$ProjectId", '--format=value(name)') `
        @('secrets', 'create', $secret, '--replication-policy=user-managed',
          "--locations=$Region", "--project=$ProjectId")
}

Ensure-ListedResource $pool @('iam', 'workload-identity-pools', 'list', '--location=global',
    "--project=$ProjectId", '--format=value(name)') @('iam', 'workload-identity-pools', 'create', $pool,
    '--location=global', "--project=$ProjectId", '--display-name=PropertyPost GitHub')

$condition = "assertion.repository=='$GitHubRepository' && assertion.ref=='refs/heads/main'"
Ensure-ListedResource $provider @('iam', 'workload-identity-pools', 'providers', 'list',
    '--location=global', "--workload-identity-pool=$pool", "--project=$ProjectId", '--format=value(name)') `
    @('iam', 'workload-identity-pools', 'providers', 'create-oidc', $provider,
      '--location=global', "--workload-identity-pool=$pool", "--project=$ProjectId",
      '--issuer-uri=https://token.actions.githubusercontent.com',
      '--attribute-mapping=google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref',
      "--attribute-condition=$condition")

foreach ($role in @('roles/storage.objectCreator', 'roles/storage.objectViewer')) {
    Invoke-Gcloud @('storage', 'buckets', 'add-iam-policy-binding', "gs://$bucket",
        "--member=serviceAccount:$runtimeEmail", "--role=$role") | Out-Null
}
foreach ($secret in $secretNames) {
    Invoke-Gcloud @('secrets', 'add-iam-policy-binding', $secret, "--project=$ProjectId",
        "--member=serviceAccount:$runtimeEmail", '--role=roles/secretmanager.secretAccessor') | Out-Null
}
Invoke-Gcloud @('artifacts', 'repositories', 'add-iam-policy-binding', $repository,
    "--location=$Region", "--project=$ProjectId", "--member=serviceAccount:$deployerEmail",
    '--role=roles/artifactregistry.writer') | Out-Null
Invoke-Gcloud @('iam', 'service-accounts', 'add-iam-policy-binding', $runtimeEmail,
    "--project=$ProjectId", "--member=serviceAccount:$deployerEmail",
    '--role=roles/iam.serviceAccountUser') | Out-Null
Invoke-Gcloud @('iam', 'service-accounts', 'add-iam-policy-binding', $deployerEmail,
    "--project=$ProjectId", "--member=$principal", '--role=roles/iam.workloadIdentityUser') | Out-Null

$services = @(Get-GcloudLines @('run', 'services', 'list', "--region=$Region", "--project=$ProjectId",
    '--format=value(metadata.name)'))
if ($services -contains 'propertypost') {
    Invoke-Gcloud @('run', 'services', 'add-iam-policy-binding', 'propertypost',
        "--region=$Region", "--project=$ProjectId", "--member=serviceAccount:$deployerEmail",
        '--role=roles/run.developer') | Out-Null
    Invoke-Gcloud @('run', 'services', 'add-iam-policy-binding', 'propertypost',
        "--region=$Region", "--project=$ProjectId", "--member=serviceAccount:$deployerEmail",
        '--role=roles/run.invoker') | Out-Null
    Write-Output 'Cloud Run Developer and Invoker granted on the PropertyPost service only.'
} else {
    Write-Output 'Cloud Run service permission deferred until the PropertyPost service exists.'
}

Write-Output 'Provisioning complete. No Cloud Run service, database credentials, or secret versions were created.'

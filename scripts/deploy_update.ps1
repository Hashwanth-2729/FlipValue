# Roll out the current code and the manual price checks to the existing flip-value deployment (DEPLOYMENT.md §8).
# Usage, from the repository root:  .\scripts\deploy_update.ps1 -Image <image>   (omit -Image to build a new one)
# Keys are read from Secret Manager into variables and never printed.
param(
    [string]$Image = "",
    [switch]$SkipOffers,  # imports are de-duplicated, so re-running without this is harmless
    [switch]$SkipHosting
)
# gcloud/firebase write progress to stderr, which Windows PowerShell 5.1 turns into error records: judge native
# commands by exit code (Check) and make only the HTTP calls stop on error.
$ErrorActionPreference = "Continue"
$PSDefaultParameterValues["Invoke-RestMethod:ErrorAction"] = "Stop"
$PROJECT_ID = "flip-value"; $REGION = "asia-south1"; $SERVICE = "flipvalue-api"; $JOB = "flipvalue-migrate"

function Step($text) { Write-Host "`n=== $text" -ForegroundColor Cyan }
function Check($what) { if ($LASTEXITCODE -ne 0) { throw "$what failed (exit $LASTEXITCODE)" } }

if (-not $Image) {
    Step "Build image (Cloud Build)"
    $Image = "$REGION-docker.pkg.dev/$PROJECT_ID/flipvalue/api:$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    gcloud builds submit --tag $Image --project $PROJECT_ID --region $REGION .; Check "build"
}

Step "Migrate + load catalogue with $Image"
gcloud run jobs update $JOB --image $Image --region $REGION --project $PROJECT_ID; Check "job update"
gcloud run jobs execute $JOB --region $REGION --project $PROJECT_ID --wait; Check "job execute"

Step "Deploy API (keeps existing settings, secrets and Cloud SQL connection)"
gcloud run deploy $SERVICE --image $Image --region $REGION --project $PROJECT_ID; Check "deploy"
$API_URL = gcloud run services describe $SERVICE --region $REGION --project $PROJECT_ID --format "value(status.url)"
$catalogue = Invoke-RestMethod "$API_URL/api/catalogue"  # assign first: @(Invoke-RestMethod ...) counts the array as 1
$models = @($catalogue).Count
Write-Host "API $API_URL serves $models catalogue models"

if (-not $SkipOffers) {
    Step "Register manual sources and import price checks"
    $adminKey = ((gcloud secrets versions access latest --secret=flipvalue-admin-keys --project $PROJECT_ID) -split ",")[0].Trim()
    $headers = @{ "X-API-Key" = $adminKey }
    $sources = @(
        @{ id = "manual-retail-in"; name = "Manual price checks: new retail (India)"; source_type = "new_retail"
           collection_method = "Prices read by hand from individual public product pages (Flipkart), recorded as CSV with URL and date"
           terms_note = "One-off manual price checks of individual product pages, not systematic retrieval. Selling price as displayed, excluding card/bank offers. Approximate; not affiliate-API data." },
        @{ id = "manual-refurb-in"; name = "Manual price checks: refurbished retail (India)"; source_type = "refurbished_retail"
           collection_method = "Prices read by hand from individual refurbisher product pages (Cashify, Budli, Easyphones), recorded as CSV with URL and date"
           terms_note = "One-off manual price checks of individual product pages, not systematic retrieval (Cashify terms prohibit systematic retrieval). Each refurbisher grades condition differently; strikethrough 'original' prices not recorded as MRP." }
    )
    foreach ($s in $sources) {
        $body = $s + @{ markets = "IN"; verified = $false } | ConvertTo-Json
        Invoke-RestMethod "$API_URL/admin/api/sources" -Method Post -Headers $headers -ContentType "application/json" -Body $body | Out-Null
        Write-Host "source $($s.id) registered"
    }
    $imports = @(
        @{ source = "manual-retail-in"; file = "data/manual/new_retail_2026-10-27.csv" },
        @{ source = "manual-refurb-in"; file = "data/manual/refurbished_2026-10-27.csv" },
        @{ source = "manual-refurb-in"; file = "data/manual/refurbished_2026-10-28.csv" }
    )
    foreach ($i in $imports) {
        # ReadAllText, not Get-Content: PS 5.1 serialises Get-Content's extra note properties into the JSON
        $csv = [IO.File]::ReadAllText((Resolve-Path $i.file), [Text.Encoding]::UTF8)
        $body = @{ source_id = $i.source; region = "IN"; csv_text = $csv } | ConvertTo-Json
        $job = Invoke-RestMethod "$API_URL/admin/api/offer-imports" -Method Post -Headers $headers `
            -ContentType "application/json; charset=utf-8" -Body ([Text.Encoding]::UTF8.GetBytes($body))
        Write-Host "$($i.file): $($job.status), $($job.accepted) accepted, $($job.duplicates) duplicates, $($job.rejected) rejected"
    }
    Remove-Variable adminKey, headers
}

if (-not $SkipHosting) {
    Step "Build and publish the website (Firebase Hosting REST API with your gcloud login; no 'firebase login')"
    npm --prefix frontend run build; Check "website build"
    $env:FV_TOKEN = gcloud auth print-access-token
    try { .\.venv\Scripts\python.exe scripts/hosting_deploy.py $PWD $PROJECT_ID $PROJECT_ID; Check "hosting deploy" }
    finally { Remove-Item Env:FV_TOKEN }
}

Step "Smoke test"
$env:FLIPVALUE_SMOKE_API_KEY = ((gcloud secrets versions access latest --secret=flipvalue-partner-keys --project $PROJECT_ID) -split ",")[0].Trim()
$siteArgs = if ($SkipHosting) { @() } else { @("--site-url", "https://$PROJECT_ID.web.app") }
try { .\.venv\Scripts\python.exe scripts/smoke_test.py --api-url $API_URL @siteArgs } finally { Remove-Item Env:FLIPVALUE_SMOKE_API_KEY }

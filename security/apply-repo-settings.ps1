<#
.SYNOPSIS
  Applies mai-platform's GitHub security settings and rulesets. Safe to re-run.

.DESCRIPTION
  Needs the GitHub CLI logged in as the repo owner (`gh auth status`).
  Run from the repo root:

      powershell -ExecutionPolicy Bypass -File security\apply-repo-settings.ps1

  What it changes (each section prints as it goes):
    1. Merge settings      squash-only, auto-merge on, delete merged branches, wiki/projects off
    2. Security features   secret scanning + push protection, Dependabot alerts,
                           private vulnerability reporting, CodeQL default setup
    3. Actions policy      read-only default token, Actions can't approve PRs,
                           only allow-listed actions, actions must be SHA-pinned,
                           fork PRs from all outside contributors need approval
    4. Rulesets            protect-main (PRs + required checks) and protect-release-tags
                           (v* tags can't be moved or deleted), from security/rulesets/*.json

  Run it only after the hardened workflows are on main and green: the main
  ruleset requires the image-gate, template-gate and workflow-lint checks.
#>
param(
    [string]$Repo = "christufa/mai-platform",
    [switch]$SkipRulesets
)

$ErrorActionPreference = "Stop"
$Here = $PSScriptRoot

function Invoke-Gh {
    # Runs gh and stops the script on any failure (gh doesn't throw by itself).
    & gh @args
    if ($LASTEXITCODE -ne 0) { throw "FAILED: gh $($args -join ' ')" }
}

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }

Invoke-Gh auth status | Out-Null

# ---------------------------------------------------------------------------
Step "1/4 Merge settings"
Invoke-Gh api -X PATCH "repos/$Repo" --silent `
    -F allow_squash_merge=true -F allow_merge_commit=false -F allow_rebase_merge=false `
    -F allow_auto_merge=true -F delete_branch_on_merge=true `
    -F has_wiki=false -F has_projects=false `
    -f squash_merge_commit_title=PR_TITLE -f squash_merge_commit_message=PR_BODY

# ---------------------------------------------------------------------------
Step "2/4 Security features"
Invoke-Gh api -X PATCH "repos/$Repo" --silent `
    -f "security_and_analysis[secret_scanning][status]=enabled" `
    -f "security_and_analysis[secret_scanning_push_protection][status]=enabled"
Invoke-Gh api -X PUT "repos/$Repo/vulnerability-alerts" --silent             # Dependabot alerts (Renovate opens the fix PRs)
Invoke-Gh api -X PUT "repos/$Repo/private-vulnerability-reporting" --silent  # "Report a vulnerability" button
Invoke-Gh api -X PATCH "repos/$Repo/code-scanning/default-setup" --silent `
    -f state=configured -f query_suite=default                                # CodeQL: Python + Actions workflows

# ---------------------------------------------------------------------------
Step "3/4 GitHub Actions policy"
Invoke-Gh api -X PUT "repos/$Repo/actions/permissions" --silent `
    -F enabled=true -f allowed_actions=selected -F sha_pinning_required=true
Invoke-Gh api -X PUT "repos/$Repo/actions/permissions/selected-actions" --silent `
    --input (Join-Path $Here "selected-actions.json")
Invoke-Gh api -X PUT "repos/$Repo/actions/permissions/workflow" --silent `
    -f default_workflow_permissions=read -F can_approve_pull_request_reviews=false
Invoke-Gh api -X PUT "repos/$Repo/actions/permissions/fork-pr-contributor-approval" --silent `
    -f approval_policy=all_external_contributors

# ---------------------------------------------------------------------------
if ($SkipRulesets) {
    Step "4/4 Rulesets (skipped)"
} else {
    Step "4/4 Rulesets"
    $raw = (Invoke-Gh api "repos/$Repo/rulesets") -join "`n"
    # ForEach-Object unrolls the JSON array (Windows PowerShell 5.1 emits it as one object)
    $existing = @($raw | ConvertFrom-Json | ForEach-Object { $_ })
    foreach ($file in Get-ChildItem (Join-Path $Here "rulesets\*.json")) {
        $name = (Get-Content $file.FullName -Raw | ConvertFrom-Json).name
        $match = $existing | Where-Object { $_.name -eq $name } | Select-Object -First 1
        if ($match) {
            Invoke-Gh api -X PUT "repos/$Repo/rulesets/$($match.id)" --silent --input $file.FullName
            Write-Host "updated ruleset: $name"
        } else {
            Invoke-Gh api -X POST "repos/$Repo/rulesets" --silent --input $file.FullName
            Write-Host "created ruleset: $name"
        }
    }
}

Write-Host "`nDone. Still manual (no API for these):" -ForegroundColor Green
Write-Host "  - GHCR package mai-base: Package settings -> Change visibility -> Public"
Write-Host "  - Install the Renovate GitHub App on $Repo (https://github.com/apps/renovate)"
Write-Host "  - Your GitHub account: 2FA with a passkey or security key"

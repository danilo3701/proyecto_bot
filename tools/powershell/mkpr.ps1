<#
Usage:
  1) Dot-source once per session:
     . .\tools\powershell\mkpr.ps1

  2) Create PR from local changes:
     mkpr -Title "Fix duplicate callback handling" -Type fix

  Optional:
     mkpr -Title "Add referral prompt" -Type feature -Base main -Repo "owner/repo"
#>

function mkpr {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory = $true)]
    [string]$Title,

    [ValidateSet('fix', 'feature', 'refactor')]
    [string]$Type = 'fix',

    [string]$Base = 'main',
    [string]$Repo = ''
  )

  # Preconditions
  if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "git is not installed or not in PATH."
  }

  if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw "gh is not installed or not in PATH."
  }

  # Check auth early
  gh auth status | Out-Null
  if ($LASTEXITCODE -ne 0) {
    throw "gh auth status failed. Run: gh auth login"
  }

  # Ensure we are in a git repo
  git rev-parse --is-inside-work-tree | Out-Null
  if ($LASTEXITCODE -ne 0) {
    throw "Current folder is not a git repository."
  }

  # Local changes required
  $status = git status --porcelain
  if (-not $status) {
    Write-Host "No local changes — nothing to PR."
    return
  }

  # Create branch
  $stamp = Get-Date -Format "yyyy-MM-dd-HHmmss"
  $slug = ($Title.ToLower() -replace '[^a-z0-9]+','-').Trim('-')
  if (-not $slug) { $slug = 'changes' }
  $branch = "work/$stamp-$slug"

  git checkout -b $branch | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "Failed to create branch $branch" }

  # Commit and push
  git add -A
  git commit -m $Title | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "Commit failed." }

  git push -u origin $branch | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "Push failed." }

  # Pick body template by type
  $templatePath = Join-Path ".github/PULL_REQUEST_TEMPLATE" "$Type.md"
  if (-not (Test-Path $templatePath)) {
    throw "Template file not found: $templatePath"
  }

  $body = Get-Content $templatePath -Raw

  # Create PR
  if ([string]::IsNullOrWhiteSpace($Repo)) {
    gh pr create --base $Base --head $branch --title $Title --body $body
  }
  else {
    gh pr create -R $Repo --base $Base --head $branch --title $Title --body $body
  }
}

<#
mkpr — create GitHub Pull Request from PowerShell with templates.

Quick start:
  . .\tools\powershell\mkpr.ps1
  mkpr -Title "Fix duplicate callback handling" -Type fix

Common modes:
  # New branch + commit + push + regular PR
  mkpr -Title "Fix callback race" -Type fix

  # New branch + commit + push + Draft PR
  mkpr -Title "WIP: rework onboarding" -Type feature -Draft

  # Continue on current branch (commit/push if needed), then create/open PR
  mkpr -Title "Add tests for /start" -Type fix -UseCurrentBranch
#>

function mkpr {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory = $true)]
    [string]$Title,

    [ValidateSet('fix', 'feature', 'refactor')]
    [string]$Type = 'fix',

    [string]$Base = 'main',
    [string]$Repo = '',

    [switch]$Draft,
    [switch]$UseCurrentBranch
  )

  # Preconditions
  if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "git is not installed or not in PATH."
  }

  if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw "gh is not installed or not in PATH."
  }

  gh auth status | Out-Null
  if ($LASTEXITCODE -ne 0) {
    throw "gh auth status failed. Run: gh auth login"
  }

  git rev-parse --is-inside-work-tree | Out-Null
  if ($LASTEXITCODE -ne 0) {
    throw "Current folder is not a git repository."
  }

  $status = git status --porcelain
  $currentBranch = (git branch --show-current).Trim()
  $hasLocalChanges = -not [string]::IsNullOrWhiteSpace($status)

  if ($UseCurrentBranch) {
    if ([string]::IsNullOrWhiteSpace($currentBranch)) {
      throw "Cannot detect current git branch."
    }
    $branch = $currentBranch
  }
  else {
    if (-not $hasLocalChanges) {
      Write-Host "No local changes — nothing to commit for a new PR branch."
      Write-Host "Tip: use -UseCurrentBranch if commits already exist on current branch."
      return
    }

    $stamp = Get-Date -Format "yyyy-MM-dd-HHmmss"
    $slug = ($Title.ToLower() -replace '[^a-z0-9]+','-').Trim('-')
    if (-not $slug) { $slug = 'changes' }
    $branch = "work/$stamp-$slug"

    git checkout -b $branch | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Failed to create branch $branch" }
  }

  # Commit only if there are local changes
  if ($hasLocalChanges) {
    git add -A
    git commit -m $Title | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Commit failed." }

    git push -u origin $branch | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Push failed." }
  }
  else {
    # still ensure branch exists remotely (best effort)
    git push -u origin $branch | Out-Null
  }

  $templatePath = Join-Path ".github/PULL_REQUEST_TEMPLATE" "$Type.md"
  if (-not (Test-Path $templatePath)) {
    throw "Template file not found: $templatePath"
  }
  $body = Get-Content $templatePath -Raw

  # If PR already exists for branch, open it instead of creating duplicate
  if ([string]::IsNullOrWhiteSpace($Repo)) {
    $existingPrUrl = gh pr view --head $branch --json url -q .url 2>$null
  }
  else {
    $existingPrUrl = gh pr view -R $Repo --head $branch --json url -q .url 2>$null
  }

  if (-not [string]::IsNullOrWhiteSpace($existingPrUrl)) {
    Write-Host "PR already exists: $existingPrUrl"
    return
  }

  $draftArg = @()
  if ($Draft) { $draftArg = @('--draft') }

  if ([string]::IsNullOrWhiteSpace($Repo)) {
    gh pr create --base $Base --head $branch --title $Title --body $body @draftArg
  }
  else {
    gh pr create -R $Repo --base $Base --head $branch --title $Title --body $body @draftArg
  }
}

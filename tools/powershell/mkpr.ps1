<#
mkpr — create/update GitHub Pull Request from PowerShell with templates.

Super-short commands (no long text needed):
  prsame                 # update/create regular PR from current branch
  prdraft                # update/create Draft PR from current branch
  prsame "hotfix api"    # same, but custom title
  prdraft "wip tests"    # draft with custom title

Full command (optional):
  mkpr -Title "Fix callback race" -Type fix -UseCurrentBranch
#>

function mkpr {
  [CmdletBinding()]
  param(
    [string]$Title = '',

    [ValidateSet('fix', 'feature', 'refactor')]
    [string]$Type = 'fix',

    [string]$Base = 'main',
    [string]$Repo = '',

    [switch]$Draft,
    [switch]$UseCurrentBranch
  )

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

    if ([string]::IsNullOrWhiteSpace($Title)) {
      $Title = "update"
    }

    $stamp = Get-Date -Format "yyyy-MM-dd-HHmmss"
    $slug = ($Title.ToLower() -replace '[^a-z0-9]+','-').Trim('-')
    if (-not $slug) { $slug = 'changes' }
    $branch = "work/$stamp-$slug"

    git checkout -b $branch | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Failed to create branch $branch" }
  }

  if ([string]::IsNullOrWhiteSpace($Title)) {
    $kind = if ($Draft) { 'wip' } else { 'update' }
    $Title = "$kind: $branch"
  }

  if ($hasLocalChanges) {
    git add -A
    git commit -m $Title | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Commit failed." }

    git push -u origin $branch | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Push failed." }
  }
  else {
    git push -u origin $branch | Out-Null
  }

  $templatePath = Join-Path ".github/PULL_REQUEST_TEMPLATE" "$Type.md"
  if (-not (Test-Path $templatePath)) {
    throw "Template file not found: $templatePath"
  }
  $body = Get-Content $templatePath -Raw

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

# One-command helpers for non-technical workflow
function prsame([string]$Title = '') {
  mkpr -Title $Title -Type fix -UseCurrentBranch
}

function prdraft([string]$Title = '') {
  mkpr -Title $Title -Type feature -UseCurrentBranch -Draft
}

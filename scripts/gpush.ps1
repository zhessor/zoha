# Push with whichever GitHub account you choose.
#   .\scripts\gpush.ps1 -m "Add feature"            # commit everything and push the current branch
#   .\scripts\gpush.ps1 -m "Fix" -Branch my-branch  # push to a named branch instead
#   .\scripts\gpush.ps1 -Setup                      # add or change your accounts
#
# Your accounts are saved in your own home folder (~\.gpush-accounts.json), never in the repo.
# Each account's commits use its own name and email, and the push signs in as that GitHub user.
param([string]$m = "", [string]$Branch = "", [switch]$Setup)
$ErrorActionPreference = "Stop"
$cfg = Join-Path $HOME ".gpush-accounts.json"

function Read-Accounts {
    $list = @()
    do {
        Write-Host "`nAdd a GitHub account (leave the username empty to finish)"
        $u = Read-Host "  GitHub username"
        if ($u) {
            $list += [pscustomobject]@{
                label = Read-Host "  Label (e.g. Company, Personal)"
                user  = $u
                name  = Read-Host "  Commit name"
                email = Read-Host "  Commit email (the one added to that GitHub account)"
            }
        }
    } while ($u)
    return $list
}

if ($Setup -or -not (Test-Path $cfg)) {
    $accounts = Read-Accounts
    if ($accounts.Count -lt 1) { throw "No accounts entered." }
    ConvertTo-Json -InputObject @($accounts) | Set-Content -Path $cfg -Encoding UTF8
    Write-Host "Saved to $cfg"
    if ($Setup -and -not $m) { return }
}
$accounts = @(Get-Content $cfg -Raw | ConvertFrom-Json)

Write-Host "`nPush as:"
for ($i = 0; $i -lt $accounts.Count; $i++) { Write-Host ("  {0}) {1} ({2})" -f ($i + 1), $accounts[$i].label, $accounts[$i].user) }
$pick = [int](Read-Host "Choose a number") - 1
if ($pick -lt 0 -or $pick -ge $accounts.Count) { throw "Not a valid choice." }
$a = $accounts[$pick]

$remote = (git remote get-url origin).Trim() -replace "^https://[^@/]+@", "https://"
if ($remote -notmatch "^https://github\.com/") { throw "origin must be an https://github.com/... address." }
$target = $remote -replace "^https://", ("https://" + $a.user + "@")
$branchName = if ($Branch) { $Branch } else { (git rev-parse --abbrev-ref HEAD).Trim() }

if (git status --porcelain) {
    if (-not $m) { $m = Read-Host "Commit message" }
    git add -A
    git -c user.name="$($a.name)" -c user.email="$($a.email)" commit -m $m
}
Write-Host "`nPushing $branchName as $($a.user) ..."
git push $target "HEAD:refs/heads/$branchName"
if ($LASTEXITCODE -eq 0) { Write-Host "Done: pushed as $($a.user)." } else { Write-Host "Push failed. If it asked you to sign in, choose the account $($a.user)." }

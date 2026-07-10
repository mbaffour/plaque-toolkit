# sync_to_downloads.ps1

# Mirror the Plaque Stats analysis workspace (code + launchers + READMEs) from

# THIS folder to the standalone copy in Downloads -- WITHOUT touching the data

# you dropped in, or the results you generated, in the destination.

#

# Run:  right-click -> "Run with PowerShell"

#   or: powershell -ExecutionPolicy Bypass -File "sync_to_downloads.ps1"



$ErrorActionPreference = 'Stop'



$src = $PSScriptRoot

$dst = 'C:\Users\mbaff\Downloads\Plaque Stats Analysis'



Write-Host ''

Write-Host '=================================================='

Write-Host '  Sync Plaque Stats workspace -> Downloads copy'

Write-Host '=================================================='

Write-Host ("  Source: {0}" -f $src)

Write-Host ("  Dest  : {0}" -f $dst)

Write-Host ''



if ($src -ieq $dst) {

    Write-Host 'Source and destination are the same folder - nothing to do.' -ForegroundColor Yellow

    return

}



if (-not (Test-Path -LiteralPath $dst)) {

    New-Item -ItemType Directory -Path $dst | Out-Null

    Write-Host 'Created destination folder.'

}



# Directories to skip entirely: the drop folders (data, results) and all

# generated / heavy / VCS artifacts. Excluding the bare names 'build' and

# 'dist' also covers build_exe\build and build_exe\dist.

# NOTE: we deliberately do NOT use robocopy /MIR, so nothing already in the

# destination (your data\ and results\ files) is ever purged.

$excludeDirs = @(

    (Join-Path $src 'data'),

    (Join-Path $src 'results'),

    'build', 'dist', 'build_exe', '__pycache__', '.git', '*.egg-info'

)

$excludeFiles = @('*.pyc', '*.pyo', '.Rhistory')



Write-Host 'Copying code, launchers and docs...'

$rcArgs = @($src, $dst, '/E', '/R:1', '/W:1', '/NFL', '/NDL', '/NP', '/NJH')

$rcArgs += '/XD'; $rcArgs += $excludeDirs

$rcArgs += '/XF'; $rcArgs += $excludeFiles

& robocopy @rcArgs | Out-Null

$codeRc = $LASTEXITCODE



# Seed the drop folders + their READMEs in the destination WITHOUT deleting any

# data/results the user already has there (copy just README.txt, no /MIR).

Write-Host 'Ensuring data\ and results\ folders + READMEs exist in the copy...'

if (Test-Path -LiteralPath (Join-Path $src 'data')) {

    & robocopy (Join-Path $src 'data')    (Join-Path $dst 'data')    'README.txt' /NFL /NDL /NP /NJH /NJS | Out-Null

}

if (Test-Path -LiteralPath (Join-Path $src 'results')) {

    & robocopy (Join-Path $src 'results') (Join-Path $dst 'results') 'README.txt' /NFL /NDL /NP /NJH /NJS | Out-Null

}



Write-Host ''

if ($codeRc -ge 8) {

    Write-Host ("Robocopy reported errors (exit code {0}). See the messages above." -f $codeRc) -ForegroundColor Red

} else {

    Write-Host ("Done. Code synced (robocopy status {0})." -f $codeRc) -ForegroundColor Green

    Write-Host 'Your data\ and results\ files in the copy were left untouched.'

}

Write-Host ("Open the copy at: {0}" -f $dst)

Write-Host ''


$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot ".." )).Path
$Version = if ($env:OSA_VERSION) { $env:OSA_VERSION } else { "2026.1" }
$IconSource = Join-Path $Root "osa\resources\icons\openstructuralanalysis.svg"
$IconOutput = Join-Path $Root "build\windows\openstructuralanalysis.ico"
$Spec = Join-Path $Root "packaging\windows\open-structural-analysis.spec"
$InstallerScript = Join-Path $Root "packaging\windows\open-structural-analysis.iss"

Push-Location $Root
try {
    & uv run python scripts/render-windows-icon.py $IconSource $IconOutput
    & uv run pyinstaller --noconfirm --clean $Spec

    $iscc = Get-Command iscc.exe -ErrorAction SilentlyContinue
    if (-not $iscc) {
        $candidates = @(
            "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
            "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
        )
        $isccPath = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
        if (-not $isccPath) {
            throw "Inno Setup Compiler (ISCC.exe) não encontrado."
        }
        $iscc = @{ Source = $isccPath }
    }

    & $iscc.Source "/DAppVersion=$Version" $InstallerScript
    Write-Host "Instalador criado em dist\OpenStructuralAnalysis-$Version-Windows-x86_64-Setup.exe"
}
finally {
    Pop-Location
}

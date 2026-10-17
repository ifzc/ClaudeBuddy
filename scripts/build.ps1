param(
    [string]$Python = 'python',
    [string]$OutputDirectory = '',
    [string]$WorkDirectory = ''
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $projectRoot 'dist' }
if (-not $WorkDirectory) { $WorkDirectory = Join-Path $projectRoot 'build' }
New-Item -ItemType Directory -Path $OutputDirectory, $WorkDirectory -Force | Out-Null
$OutputDirectory = (Resolve-Path -LiteralPath $OutputDirectory).Path
$WorkDirectory = (Resolve-Path -LiteralPath $WorkDirectory).Path

& $Python -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name DesktopTimezone --paths (Join-Path $projectRoot 'src') `
    --collect-all frida --collect-data desktop_timezone `
    --distpath $OutputDirectory --workpath (Join-Path $WorkDirectory 'pyinstaller') `
    --specpath $WorkDirectory (Join-Path $PSScriptRoot 'launch_gui.py')
if ($LASTEXITCODE -ne 0) { throw 'Building DesktopTimezone failed.' }

Copy-Item -LiteralPath (Join-Path $projectRoot 'examples\config.json') -Destination $OutputDirectory
foreach ($name in @('README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md')) {
    Copy-Item -LiteralPath (Join-Path $projectRoot $name) -Destination $OutputDirectory
}
Copy-Item -LiteralPath (Join-Path $projectRoot 'licenses') -Destination $OutputDirectory -Recurse -Force
Get-FileHash -LiteralPath (Join-Path $OutputDirectory 'DesktopTimezone.exe') -Algorithm SHA256 |
    ForEach-Object { ($_.Hash.ToLowerInvariant() + '  DesktopTimezone.exe') } |
    Set-Content -LiteralPath (Join-Path $OutputDirectory 'SHA256SUMS.txt') -Encoding utf8

param(
    [string]$OutputDir = "",
    [switch]$SkipImages,
    [switch]$SkipRuntimeVolumes,
    [switch]$IncludeStateVolumes,
    [switch]$FullData,
    [switch]$NoBuild
)

$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $OutputDir = Join-Path $RootDir "dist\trustlens-transfer-$Stamp"
} elseif (-not [System.IO.Path]::IsPathRooted($OutputDir)) {
    $OutputDir = Join-Path $RootDir $OutputDir
}

$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)
$ImagesDir = Join-Path $OutputDir "images"
$VolumesDir = Join-Path $OutputDir "volumes"

New-Item -ItemType Directory -Force -Path $OutputDir, $ImagesDir, $VolumesDir | Out-Null

function Assert-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' was not found on PATH."
    }
}

function Invoke-Checked {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )
    Write-Host "> $FilePath $($Arguments -join ' ')"
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE`: $FilePath"
    }
}

function Test-DockerVolume {
    param([string]$Name)
    & docker volume inspect $Name *> $null
    return ($LASTEXITCODE -eq 0)
}

function Test-DockerImage {
    param([string]$Name)
    & docker image inspect $Name *> $null
    return ($LASTEXITCODE -eq 0)
}

function Export-DockerVolume {
    param(
        [string]$Name,
        [string]$DestinationDir
    )

    if (-not (Test-DockerVolume $Name)) {
        Write-Warning "Docker volume '$Name' does not exist. Skipping it."
        return $null
    }

    $ArchiveName = "$Name.tar"
    $Destination = Join-Path $DestinationDir $ArchiveName
    $MountDestination = $DestinationDir -replace "\\", "/"

    Invoke-Checked "docker" @(
        "run", "--rm",
        "-v", "$Name`:/volume:ro",
        "-v", "$MountDestination`:/backup",
        "alpine:3.20",
        "sh", "-c", "cd /volume && tar cf /backup/$ArchiveName ."
    )

    return $ArchiveName
}

Assert-Command "docker"
Assert-Command "tar.exe"

$ComposeFile = Join-Path $RootDir "docker-compose.yml"
if (-not (Test-Path -LiteralPath $ComposeFile)) {
    throw "docker-compose.yml was not found at $ComposeFile"
}

Write-Host "Creating TrustLens transfer bundle at: $OutputDir"

$ProjectArchive = Join-Path $OutputDir "trustlens-project-runtime.tar.gz"
$ProjectItems = @(
    "backend",
    "frontend",
    "gov_mock",
    "ner_service",
    "ml",
    "demo_data",
    "scripts",
    "docker-compose.yml",
    "README.md",
    "DEMO.md",
    "TRANSFER.md"
)

if ($FullData) {
    $ProjectItems += "data"
} else {
    $RuntimeModelPaths = @(
        "data/models/layoutlmv3-trustlens",
        "data/models/yolov8-aadhaar",
        "data/models/yolov8-pan",
        "data/models/yolov8-signatures",
        "data/models/yolov8-stamps",
        "data/models/xgb_risk"
    )
    foreach ($Path in $RuntimeModelPaths) {
        if (Test-Path -LiteralPath (Join-Path $RootDir $Path)) {
            $ProjectItems += $Path
        } else {
            Write-Warning "Runtime model path '$Path' was not found. Skipping it."
        }
    }
}

$TarArgs = @(
    "-czf", $ProjectArchive,
    "-C", $RootDir,
    "--exclude=frontend/node_modules",
    "--exclude=frontend/.next",
    "--exclude=frontend/dist",
    "--exclude=**/__pycache__",
    "--exclude=**/*.pyc"
) + $ProjectItems

Invoke-Checked "tar.exe" $TarArgs

$SavedImages = @()
if (-not $SkipImages) {
    Invoke-Checked "docker" @("version")

    if (-not $NoBuild) {
        Invoke-Checked "docker" @("compose", "-f", $ComposeFile, "build")
    }

    $PulledImages = @("postgres:16", "redis:7-alpine", "minio/minio:latest", "ollama/ollama:latest", "alpine:3.20")
    foreach ($Image in $PulledImages) {
        Invoke-Checked "docker" @("image", "pull", $Image)
    }

    $Images = (& docker compose -f $ComposeFile config --images) + "alpine:3.20"
    if ($LASTEXITCODE -ne 0) {
        throw "Could not read image list from docker compose config."
    }
    $Images = $Images | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Sort-Object -Unique

    foreach ($Image in $Images) {
        Invoke-Checked "docker" @("image", "inspect", $Image)
    }

    $ImageArchive = Join-Path $ImagesDir "trustlens-images.tar"
    Invoke-Checked "docker" (@("image", "save", "-o", $ImageArchive) + $Images)
    $Images | Set-Content -LiteralPath (Join-Path $ImagesDir "images.txt") -Encoding UTF8
    $SavedImages = $Images
}

$SavedVolumes = @()
if (-not $SkipRuntimeVolumes) {
    Invoke-Checked "docker" @("version")

    if ($SkipImages -and -not (Test-DockerImage "alpine:3.20")) {
        Invoke-Checked "docker" @("image", "pull", "alpine:3.20")
    }

    $Volumes = @("trustlens_ollama_models", "trustlens_hf_cache")
    if ($IncludeStateVolumes) {
        $Volumes += @("trustlens_postgres_data", "trustlens_redis_data", "trustlens_minio_data")
    }

    foreach ($Volume in $Volumes) {
        $Archive = Export-DockerVolume -Name $Volume -DestinationDir $VolumesDir
        if ($Archive) {
            $SavedVolumes += [ordered]@{
                name = $Volume
                archive = "volumes/$Archive"
            }
        }
    }
}

$Manifest = [ordered]@{
    created_at = (Get-Date).ToString("s")
    project = "trustlens"
    project_archive = "trustlens-project-runtime.tar.gz"
    full_data = [bool]$FullData
    images_archive = $(if ($SkipImages) { $null } else { "images/trustlens-images.tar" })
    images = $SavedImages
    volumes = $SavedVolumes
    notes = @(
        "Default project archive contains source/config plus live inference model assets.",
        "Use -FullData to include the entire data folder.",
        "Runtime volumes include Ollama models and HuggingFace cache when present."
    )
}

$Manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $OutputDir "manifest.json") -Encoding UTF8
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "import-transfer-bundle.ps1") -Destination (Join-Path $OutputDir "import-transfer-bundle.ps1") -Force
Copy-Item -LiteralPath (Join-Path $RootDir "TRANSFER.md") -Destination (Join-Path $OutputDir "TRANSFER.md") -Force

Write-Host ""
Write-Host "Bundle complete:"
Write-Host "  $OutputDir"
Write-Host ""
Write-Host "Send this whole folder to the other machine."
Write-Host "On the receiving machine, open PowerShell in the bundle folder, then run:"
Write-Host "  .\import-transfer-bundle.ps1 -BundleDir . -ProjectDir C:\trustlens -Start"

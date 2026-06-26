param(
    [Parameter(Mandatory = $true)]
    [string]$BundleDir,
    [string]$ProjectDir = "",
    [switch]$SkipImages,
    [switch]$SkipVolumes,
    [switch]$Start
)

$ErrorActionPreference = "Stop"

if (-not [System.IO.Path]::IsPathRooted($BundleDir)) {
    $BundleDir = Join-Path (Get-Location) $BundleDir
}
$BundleDir = [System.IO.Path]::GetFullPath($BundleDir)

if ([string]::IsNullOrWhiteSpace($ProjectDir)) {
    $ProjectDir = Join-Path (Get-Location) "trustlens"
} elseif (-not [System.IO.Path]::IsPathRooted($ProjectDir)) {
    $ProjectDir = Join-Path (Get-Location) $ProjectDir
}
$ProjectDir = [System.IO.Path]::GetFullPath($ProjectDir)

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

function Import-DockerVolume {
    param(
        [string]$ArchivePath
    )

    $VolumeName = [System.IO.Path]::GetFileNameWithoutExtension($ArchivePath)
    $ArchiveName = [System.IO.Path]::GetFileName($ArchivePath)
    $ArchiveDir = [System.IO.Path]::GetDirectoryName($ArchivePath) -replace "\\", "/"

    Invoke-Checked "docker" @("volume", "create", $VolumeName)
    Invoke-Checked "docker" @(
        "run", "--rm",
        "-v", "$VolumeName`:/volume",
        "-v", "$ArchiveDir`:/backup:ro",
        "alpine:3.20",
        "sh", "-c", "cd /volume && tar xf /backup/$ArchiveName"
    )
}

Assert-Command "docker"
Assert-Command "tar.exe"

if (-not (Test-Path -LiteralPath $BundleDir)) {
    throw "Bundle directory not found: $BundleDir"
}

$ProjectArchive = Join-Path $BundleDir "trustlens-project-runtime.tar.gz"
if (-not (Test-Path -LiteralPath $ProjectArchive)) {
    throw "Project archive not found: $ProjectArchive"
}

Write-Host "Importing TrustLens bundle from: $BundleDir"
Write-Host "Project directory: $ProjectDir"

New-Item -ItemType Directory -Force -Path $ProjectDir | Out-Null

if (-not $SkipImages) {
    $ImageArchive = Join-Path $BundleDir "images\trustlens-images.tar"
    if (Test-Path -LiteralPath $ImageArchive) {
        Invoke-Checked "docker" @("image", "load", "-i", $ImageArchive)
    } else {
        Write-Warning "Image archive was not found. Continuing without loading images."
    }
}

Invoke-Checked "tar.exe" @("-xzf", $ProjectArchive, "-C", $ProjectDir)

if (-not $SkipVolumes) {
    $VolumesDir = Join-Path $BundleDir "volumes"
    if (Test-Path -LiteralPath $VolumesDir) {
        $VolumeArchives = Get-ChildItem -LiteralPath $VolumesDir -Filter "*.tar" -File | Sort-Object Name
        foreach ($Archive in $VolumeArchives) {
            Import-DockerVolume -ArchivePath $Archive.FullName
        }
    } else {
        Write-Warning "Volumes directory was not found. Continuing without volume import."
    }
}

if ($Start) {
    $ComposeFile = Join-Path $ProjectDir "docker-compose.yml"
    if (-not (Test-Path -LiteralPath $ComposeFile)) {
        throw "docker-compose.yml was not found in imported project: $ComposeFile"
    }
    Invoke-Checked "docker" @("compose", "-f", $ComposeFile, "up", "-d")
}

Write-Host ""
Write-Host "Import complete."
Write-Host "Project is at: $ProjectDir"
if (-not $Start) {
    Write-Host "Start it with:"
    Write-Host "  cd `"$ProjectDir`""
    Write-Host "  docker compose up -d"
}

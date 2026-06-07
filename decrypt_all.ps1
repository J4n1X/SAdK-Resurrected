# SADK Batch Decryption Script
# Decrypts all .KEX files and preserves folder structure

# EDIT PER MACHINE: point this at your game's data folder (the dir containing the .KEX files).
$sourceDir = "<PATH TO YOUR GAME>\data"
$resultDir = Join-Path $PSScriptRoot 'result'
$adkEdPath = Join-Path $PSScriptRoot 'AdKEd.exe'

# Create result directory if it doesn't exist
if (-not (Test-Path $resultDir)) {
    New-Item -ItemType Directory -Path $resultDir | Out-Null
}

# Get all .KEX files recursively
$files = Get-ChildItem -Path $sourceDir -Recurse -Filter "*.KEX"

Write-Host "Found $($files.Count) .KEX files to decrypt"

$count = 0
foreach ($file in $files) {
    $count++

    # Calculate relative path from source directory
    $relativePath = $file.FullName.Substring($sourceDir.Length + 1)

    # Create destination path (replace .KEX with .xml or keep as is for now)
    $destPath = Join-Path $resultDir $relativePath
    $destDir = Split-Path $destPath -Parent

    # Create destination directory structure
    if (-not (Test-Path $destDir)) {
        New-Item -ItemType Directory -Path $destDir | Out-Null
    }

    # Decrypt file - AdKEd creates output with same name but decoded
    Write-Host "[$count/$($files.Count)] Decrypting: $relativePath"

    # Copy file to temp location, decrypt, then move to result
    $tempFile = Join-Path $env:TEMP "temp_$([guid]::NewGuid()).KEX"
    Copy-Item $file.FullName $tempFile

    # Run AdKEd on the temp file (it decrypts in place)
    & $adkEdPath $tempFile 2>&1 | Out-Null

    # Move the decrypted file to result directory
    Move-Item $tempFile $destPath -Force
}

Write-Host "Decryption complete! $count files processed."
Write-Host "Results stored in: $resultDir"

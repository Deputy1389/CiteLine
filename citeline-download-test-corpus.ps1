# CiteLine test corpus downloader
# Downloads the "Full evaluation (10 PDFs)" set into: C:\CiteLine\testdata\
# Safe to re-run (skips existing files unless -Force is passed).
# NOTE: This script continues downloading even if one file fails; failures are reported at the end.

param(
  [string]$OutDir = "C:\CiteLine\testdata",
  [switch]$Force
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$files = @(
  @{ Name = "eval_01_amfs_packet.pdf"; Url = "https://amfs.com/wp-content/uploads/2019/07/sample-medical-chronology.pdf" },

  # ATSU link in the report now 404s; Virtual-IPE hosts the same "Day 1 Nursing Notes" PDF here:
  @{ Name = "eval_02_millie_day1.pdf"; Url = "https://virtual-ipe.com/sites/default/files/files/day_1_nurses_notes.pdf" },

  @{ Name = "eval_03_millie_day2.pdf"; Url = "https://virtual-ipe.com/sites/default/files/files/day_2_nurses_notes.pdf" },
  @{ Name = "eval_04_millie_day3.pdf"; Url = "https://virtual-ipe.com/sites/default/files/files/day_3_nurses_notes.pdf" },
  @{ Name = "eval_05_millie_day4.pdf"; Url = "https://virtual-ipe.com/sites/default/files/files/day_4_nurses_notes.pdf" },
  @{ Name = "eval_06_julia_day1.pdf"; Url = "https://virtual-ipe.com/sites/default/files/files/julia_nurses_notes_day_1_updated_tc.pdf" },
  @{ Name = "eval_07_julia_day2.pdf"; Url = "https://virtual-ipe.com/sites/default/files/files/julia_nurses_notes_day_2_.pdf" },
  @{ Name = "eval_08_julia_day3.pdf"; Url = "https://virtual-ipe.com/sites/default/files/files/julia_nurses_notes_day_3_.pdf" },

  # RadiologyInfo "PdfExport=1" links can sometimes redirect; keep as-is.
  @{ Name = "eval_09_head_ct_report.pdf"; Url = "https://www.radiologyinfo.org/info/article-head-ct-report?PdfExport=1" },
  @{ Name = "eval_10_brain_mri_report.pdf"; Url = "https://www.radiologyinfo.org/info/article-brain-mri-report?PdfExport=1" }
)

function Download-File($url, $destPath) {
  $tmp = "$destPath.tmp"
  $maxAttempts = 3

  for ($i = 1; $i -le $maxAttempts; $i++) {
    try {
      Write-Host "  -> $url"
      Invoke-WebRequest -Uri $url -OutFile $tmp -UseBasicParsing -MaximumRedirection 5

      if ((Get-Item $tmp).Length -lt 1024) {
        throw "Downloaded file is suspiciously small (<1KB)."
      }

      Move-Item -Force $tmp $destPath
      return $true
    } catch {
      if ($i -eq $maxAttempts) {
        Write-Warning "Failed: $url  ($($_.Exception.Message))"
        return $false
      }
      Write-Warning "Download failed (attempt $i/$maxAttempts). Retrying... $($_.Exception.Message)"
      Start-Sleep -Seconds (2 * $i)
    } finally {
      if (Test-Path $tmp) { Remove-Item -Force $tmp -ErrorAction SilentlyContinue }
    }
  }
}

$failures = @()

Write-Host "Downloading CiteLine test corpus to: $OutDir"
foreach ($f in $files) {
  $dest = Join-Path $OutDir $f.Name

  if ((Test-Path $dest) -and (-not $Force)) {
    Write-Host "Skipping (exists): $($f.Name)"
    continue
  }

  Write-Host "Downloading: $($f.Name)"
  $ok = Download-File $f.Url $dest
  if (-not $ok) {
    $failures += $f
  }
}

Write-Host ""
if ($failures.Count -gt 0) {
  Write-Host "Completed with failures:"
  foreach ($f in $failures) {
    Write-Host "  - $($f.Name)  $($f.Url)"
  }
  Write-Host ""
  Write-Host "Tip: re-run with -Force after you fix any blocked URLs:"
  Write-Host "  powershell -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Force"
} else {
  Write-Host "Done. All files saved in: $OutDir"
}

Write-Host ""
Write-Host "Example:"
Write-Host "  python scripts\ingest_file.py `"$OutDir\eval_02_millie_day1.pdf`""

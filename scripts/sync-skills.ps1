# Копирует общие навыки из .agents/skills (их читает Codex и другие агенты)
# в .claude/skills (их читает Claude Code). Править нужно только .agents/skills.
#   pwsh scripts/sync-skills.ps1          синхронизировать
#   pwsh scripts/sync-skills.ps1 -Check   только проверить; код 1 при расхождении
param([switch]$Check)
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$src = Join-Path $root '.agents/skills'
$dst = Join-Path $root '.claude/skills'
$mark = '.synced-from-agents'
$bad = $false

if (-not (Test-Path $src)) { throw "Нет каталога $src" }

# Список "относительный путь|хеш" для сравнения каталогов (без файла-метки)
function Get-Tree([string]$path) {
  if (-not (Test-Path $path)) { return '' }
  $base = (Resolve-Path $path).Path
  $items = Get-ChildItem -Path $base -Recurse -File -Force | Where-Object { $_.Name -ne $mark } | ForEach-Object {
    $rel = $_.FullName.Substring($base.Length).TrimStart('\', '/') -replace '\\', '/'
    '{0}|{1}' -f $rel, (Get-FileHash -Path $_.FullName -Algorithm SHA256).Hash
  }
  return (@($items) | Sort-Object) -join "`n"
}

foreach ($skill in Get-ChildItem -Path $src -Directory) {
  if (-not (Test-Path (Join-Path $skill.FullName 'SKILL.md'))) { continue }
  $target = Join-Path $dst $skill.Name
  if ($Check) {
    if ((Get-Tree $skill.FullName) -ne (Get-Tree $target)) {
      Write-Warning "Расходится: .claude/skills/$($skill.Name) — запустите scripts/sync-skills"
      $bad = $true
    }
  }
  else {
    if (Test-Path $target) { Remove-Item $target -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $dst | Out-Null
    Copy-Item -Path $skill.FullName -Destination $target -Recurse
    Set-Content -Path (Join-Path $target $mark) -Encoding utf8 `
      -Value "Копия навыка из .agents/skills/$($skill.Name). Не редактируйте: правьте оригинал и запустите scripts/sync-skills."
  }
}

# Копии навыков, которых больше нет в .agents/skills
if (Test-Path $dst) {
  foreach ($copy in Get-ChildItem -Path $dst -Directory) {
    $isCopy = Test-Path (Join-Path $copy.FullName $mark)
    $hasSource = Test-Path (Join-Path $src $copy.Name)
    if ($isCopy -and -not $hasSource) {
      if ($Check) {
        Write-Warning "Лишняя копия: .claude/skills/$($copy.Name)"
        $bad = $true
      }
      else {
        Remove-Item $copy.FullName -Recurse -Force
        Write-Host "Удалена устаревшая копия: .claude/skills/$($copy.Name)"
      }
    }
  }
}

# Явный код возврата: иначе при вызове через & остаётся $LASTEXITCODE предыдущей команды
if ($bad) { exit 1 }
exit 0

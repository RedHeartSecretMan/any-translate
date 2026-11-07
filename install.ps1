# AnyTranslate installer for the PotPlayer subtitle translation plugin.
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\install.ps1
#   powershell -ExecutionPolicy Bypass -File .\install.ps1 -Uninstall
#   powershell -ExecutionPolicy Bypass -File .\install.ps1 -PotPlayerDir "D:\PotPlayer"
#   powershell -ExecutionPolicy Bypass -File .\install.ps1 -DryRun

param(
    [string]$PotPlayerDir = "",
    [switch]$Uninstall,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# PotPlayer requires this exact plugin file name; the menu label comes from GetTitle().
$PluginName = "SubtitleTranslate - AnyTranslate"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pluginFile = Join-Path $scriptRoot "plugin\$PluginName.as"
$iconFile = Join-Path $scriptRoot "plugin\$PluginName.ico"

function Test-PotPlayerDir([string]$Dir) {
    if (-not $Dir) { return $false }
    return (Test-Path (Join-Path $Dir "PotPlayerMini64.exe")) -or
           (Test-Path (Join-Path $Dir "PotPlayer64.exe")) -or
           (Test-Path (Join-Path $Dir "Extension\Subtitle\Translate"))
}

function Get-PotPlayerFromRegistry {
    $keys = @(
        "HKCU:\Software\DAUM\PotPlayer",
        "HKLM:\SOFTWARE\DAUM\PotPlayer",
        "HKLM:\SOFTWARE\WOW6432Node\DAUM\PotPlayer"
    )
    foreach ($key in $keys) {
        if (-not (Test-Path $key)) { continue }
        $props = Get-ItemProperty -Path $key -ErrorAction SilentlyContinue
        foreach ($name in @("ProgramPath", "InstallPath", "Path")) {
            $value = $props.$name
            if (-not $value) { continue }
            $path = ([string]$value).Trim('"')
            if (Test-Path $path -PathType Leaf) { $path = Split-Path -Parent $path }
            if (Test-PotPlayerDir $path) { return $path }
        }
    }
    return $null
}

function Find-PotPlayerDir {
    if ($PotPlayerDir) {
        if (Test-Path $PotPlayerDir) { return $PotPlayerDir }
        throw "指定的 PotPlayer 目录不存在: $PotPlayerDir"
    }

    $fromRegistry = Get-PotPlayerFromRegistry
    if ($fromRegistry) { return $fromRegistry }

    $candidates = @(
        $env:POTPLAYER_HOME,
        $env:POTPLAYER_DIR,
        (Join-Path $env:ProgramFiles "DAUM\PotPlayer"),
        (Join-Path ${env:ProgramFiles(x86)} "DAUM\PotPlayer"),
        (Join-Path $env:ProgramFiles "PotPlayer"),
        (Join-Path ${env:ProgramFiles(x86)} "PotPlayer")
    ) | Where-Object { $_ }

    foreach ($dir in $candidates) {
        if (Test-PotPlayerDir $dir) { return $dir }
    }
    throw "未找到 PotPlayer 安装目录，请用 -PotPlayerDir 指定。"
}

$targetDir = Find-PotPlayerDir
$translateDir = Join-Path $targetDir "Extension\Subtitle\Translate"

if (-not (Test-Path $translateDir)) {
    throw "找不到翻译插件目录: $translateDir （PotPlayer 版本可能过旧）"
}

$targetAs = Join-Path $translateDir "$PluginName.as"
$targetIco = Join-Path $translateDir "$PluginName.ico"

if ($Uninstall) {
    foreach ($file in @($targetAs, $targetIco)) {
        if (Test-Path $file) {
            if ($DryRun) {
                Write-Host "would remove: $file"
            } else {
                Remove-Item $file -Force
                Write-Host "removed: $file"
            }
        }
    }
    Write-Host "卸载完成。请重启 PotPlayer。"
    exit 0
}

if (-not (Test-Path $pluginFile)) {
    throw "插件文件不存在: $pluginFile （请确认在仓库根目录运行）"
}

$proc = Get-Process -Name "PotPlayerMini64", "PotPlayer64" -ErrorAction SilentlyContinue
if ($proc) {
    Write-Warning "检测到 PotPlayer 正在运行，建议先关闭；已继续复制，重启 PotPlayer 后才会生效。"
}

foreach ($pair in @(@($pluginFile, $targetAs), @($iconFile, $targetIco))) {
    $source = $pair[0]
    $target = $pair[1]
    if (-not (Test-Path $source)) { continue }

    if ($DryRun) {
        Write-Host "would install: $target"
        continue
    }

    if (Test-Path $target) {
        $backup = "$target.bak-$(Get-Date -Format 'yyyyMMddHHmmss')"
        Copy-Item $target $backup
        Write-Host "backup: $backup"
    }
    try {
        Copy-Item $source $target -Force
        Write-Host "installed: $target"
    } catch {
        throw "复制失败（可能需要管理员权限）: $target`n$($_.Exception.Message)"
    }
}

Write-Host ""
Write-Host "安装完成。请重启 PotPlayer，然后在 字幕 -> 实时字幕翻译 中选择 AnyTranslate。"
Write-Host "配置方法见 README.md。"

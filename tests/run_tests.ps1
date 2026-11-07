#!/usr/bin/env pwsh
# AnyTranslate 契约测试一键运行脚本（仅使用 Python 标准库）。
#
# 用法（在任意目录均可执行）：
#   pwsh -File tests/run_tests.ps1
#   pwsh -File tests/run_tests.ps1 -VerboseTests   # 逐条打印 unittest 用例
#   pwsh -File tests/run_tests.ps1 -NoSmoke        # 跳过独立 mock_server 冒烟
#   pwsh -File tests/run_tests.ps1 -Python C:\Python312\python.exe
#
# 步骤：
#   1. 定位 Python（-Python > ANYTRANSLATE_PYTHON > PATH 中的 python/python3/py -3）；
#   2. py_compile 语法检查三个交付文件；
#   3. 独立启动 mock_server.py 并真实发一个请求，验证“可独立启动 + 记录请求”；
#   4. python -m unittest discover -s tests -v；
#   5. 输出通过/失败摘要，并以 unittest 退出码退出。

param(
    [switch]$VerboseTests,
    [switch]$NoSmoke,
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"

$scriptDir = $PSScriptRoot
$projectRoot = Split-Path -Parent $scriptDir

function Resolve-Python([string]$Explicit) {
    if ($Explicit) {
        $cmd = Get-Command $Explicit -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
        if (Test-Path -LiteralPath $Explicit) { return (Resolve-Path -LiteralPath $Explicit).Path }
        return $null
    }
    if ($env:ANYTRANSLATE_PYTHON) {
        $resolved = Resolve-Python $env:ANYTRANSLATE_PYTHON
        if ($resolved) { return $resolved }
    }
    foreach ($name in @("python", "python3")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    $py = Get-Command "py" -ErrorAction SilentlyContinue
    if ($py) {
        $exe = & py -3 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $exe) { return ([string]$exe).Trim() }
    }
    return $null
}

function Write-Step([string]$text) {
    Write-Host ""
    Write-Host "==> $text" -ForegroundColor Cyan
}

function Fail-And-Exit([string]$message, [int]$code = 1) {
    Write-Host "[FAIL] $message" -ForegroundColor Red
    exit $code
}

Write-Host "================ AnyTranslate 契约测试 ================" -ForegroundColor Green
Write-Host "项目根目录: $projectRoot"
Write-Host "tests 目录 : $scriptDir"

# ---------------------------------------------------------------------------
# 1. Python 解释器
# ---------------------------------------------------------------------------
Write-Step "检查 Python 解释器"
$pythonExe = Resolve-Python $Python
if (-not $pythonExe) {
    Fail-And-Exit "找不到 Python。请安装 Python 3.10+，或用 -Python 指定解释器路径，或设置 ANYTRANSLATE_PYTHON。"
}
Write-Host "[OK] 使用 Python：$pythonExe"

$env:PYTHONIOENCODING = "utf-8"
$versionLine = & $pythonExe "-c" "import sys; print(sys.version.split()[0])"
if ($LASTEXITCODE -ne 0) {
    Fail-And-Exit "Python 无法运行。"
}
Write-Host "[OK] Python $versionLine"

# ---------------------------------------------------------------------------
# 2. py_compile 语法检查
# ---------------------------------------------------------------------------
Write-Step "py_compile 语法检查"
$sources = @(
    (Join-Path $scriptDir "mock_server.py"),
    (Join-Path $scriptDir "ref_impl.py"),
    (Join-Path $scriptDir "test_contract.py")
)
foreach ($src in $sources) {
    if (-not (Test-Path -LiteralPath $src)) {
        Fail-And-Exit "缺少交付文件：$src"
    }
}
& $pythonExe "-m" "py_compile" @sources
if ($LASTEXITCODE -ne 0) {
    Fail-And-Exit "py_compile 失败（见上方错误）。"
}
Write-Host "[OK] mock_server.py / ref_impl.py / test_contract.py 编译通过"

# ---------------------------------------------------------------------------
# 3. 独立 mock_server 冒烟（--port 0 随机端口，避免 18080 被占用）
# ---------------------------------------------------------------------------
$smokeFailed = $false
if (-not $NoSmoke) {
    Write-Step "独立启动 mock_server.py 冒烟测试"
    $logFile = Join-Path ([System.IO.Path]::GetTempPath()) ("anytranslate-mock-" + [guid]::NewGuid().ToString("N") + ".log")
    $errFile = "$logFile.err"
    $mockProcess = $null
    try {
        $mockProcess = Start-Process -FilePath $pythonExe `
            -ArgumentList @((Join-Path $scriptDir "mock_server.py"), "--port", "0") `
            -WorkingDirectory $projectRoot `
            -RedirectStandardOutput $logFile `
            -RedirectStandardError $errFile `
            -WindowStyle Hidden `
            -PassThru

        $baseUrl = $null
        for ($i = 0; $i -lt 80; $i++) {
            Start-Sleep -Milliseconds 100
            if (Test-Path -LiteralPath $logFile) {
                $match = Select-String -LiteralPath $logFile -Pattern "listening on (http://[0-9A-Za-z\.\[\]:]+)" -ErrorAction SilentlyContinue
                if ($match) {
                    $baseUrl = ($match | Select-Object -First 1).Matches[0].Groups[1].Value
                    break
                }
            }
            if ($mockProcess.HasExited) { break }
        }

        if (-not $baseUrl) {
            $smokeFailed = $true
            Write-Host "[FAIL] mock_server 未能独立启动，日志：" -ForegroundColor Red
            if (Test-Path -LiteralPath $logFile) { Get-Content -LiteralPath $logFile | ForEach-Object { Write-Host "  $_" } }
            if (Test-Path -LiteralPath $errFile) { Get-Content -LiteralPath $errFile | ForEach-Object { Write-Host "  $_" } }
        } else {
            Write-Host "[OK] mock_server 监听 $baseUrl"

            $health = Invoke-RestMethod -Uri "$baseUrl/__health" -TimeoutSec 5
            if (-not $health.ok) {
                $smokeFailed = $true
                Write-Host "[FAIL] /__health 返回异常：$($health | ConvertTo-Json -Compress)" -ForegroundColor Red
            } else {
                Write-Host "[OK] GET /__health -> ok=true"
            }

            $payload = '{"model":"m","messages":[{"role":"user","content":"hi"}],"stream":false,"temperature":0}'
            $null = Invoke-WebRequest -Uri "$baseUrl/v1/chat/completions" -Method Post `
                -ContentType "application/json" -Body $payload `
                -Headers @{ Authorization = "Bearer sk-smoke" } -TimeoutSec 5 -UseBasicParsing
            $requests = Invoke-RestMethod -Uri "$baseUrl/__requests" -TimeoutSec 5
            $count = @($requests).Count
            if ($count -lt 1) {
                $smokeFailed = $true
                Write-Host "[FAIL] /__requests 没有记录到请求" -ForegroundColor Red
            } else {
                $record = @($requests)[-1]
                $problemCount = @($record.problems).Count
                if ($problemCount -gt 0) {
                    $smokeFailed = $true
                    Write-Host "[FAIL] 冒烟请求被契约校验判定不合规：$($record.problems -join ' | ')" -ForegroundColor Red
                } else {
                    Write-Host "[OK] 收到 1 条记录：route=$($record.route)，契约校验 problems=0"
                }
            }
        }
    } catch {
        $smokeFailed = $true
        Write-Host "[FAIL] mock_server 冒烟异常：$($_.Exception.Message)" -ForegroundColor Red
    } finally {
        if ($null -ne $mockProcess) {
            Stop-Process -Id $mockProcess.Id -Force -ErrorAction SilentlyContinue
        }
        Remove-Item -LiteralPath $logFile -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $errFile -ErrorAction SilentlyContinue
    }
} else {
    Write-Step "跳过 mock_server 冒烟（-NoSmoke）"
}

# ---------------------------------------------------------------------------
# 4. 运行 unittest
# ---------------------------------------------------------------------------
Write-Step "运行 unittest（discover -s tests）"
$outputFile = Join-Path ([System.IO.Path]::GetTempPath()) ("anytranslate-unittest-" + [guid]::NewGuid().ToString("N") + ".log")
$unittestArgs = @("-m", "unittest", "discover", "-s", $scriptDir, "-t", $scriptDir)
if ($VerboseTests) { $unittestArgs += "-v" }

Push-Location $projectRoot
try {
    # 用 cmd.exe 重定向，兼容 Windows PowerShell 5.1：
    # 5.1 下 `*>` 会把 python 写到 stderr 的进度点当成 NativeCommandError 终止脚本。
    $quotedArgs = ($unittestArgs | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }) -join " "
    $cmdLine = '"' + $pythonExe + '" ' + $quotedArgs + ' > "' + $outputFile + '" 2>&1'
    & cmd.exe /d /c $cmdLine | Out-Null
    $unittestExit = $LASTEXITCODE
} finally {
    Pop-Location
}

$outputText = ""
if (Test-Path -LiteralPath $outputFile) {
    $outputText = Get-Content -LiteralPath $outputFile -Raw -Encoding utf8
}

if ($VerboseTests -or $unittestExit -ne 0) {
    Write-Host $outputText
} else {
    # 非 verbose 模式只显示最后的 Ran/OK 行，控制摘要长度
    ($outputText -split "`r?`n") | Where-Object { $_ -match "^(Ran |OK|FAILED)" } | ForEach-Object { Write-Host $_ }
}
Remove-Item -LiteralPath $outputFile -ErrorAction SilentlyContinue

# ---------------------------------------------------------------------------
# 5. 解析并输出摘要
# ---------------------------------------------------------------------------
$ran = 0
$failures = 0
$errors = 0
$skipped = 0
$ranMatch = [regex]::Match($outputText, "Ran (\d+) tests? in")
if ($ranMatch.Success) { $ran = [int]$ranMatch.Groups[1].Value }
$failedMatch = [regex]::Match($outputText, "FAILED \(([^)]*)\)")
if ($failedMatch.Success) {
    $detail = $failedMatch.Groups[1].Value
    $m = [regex]::Match($detail, "failures=(\d+)")
    if ($m.Success) { $failures = [int]$m.Groups[1].Value }
    $m = [regex]::Match($detail, "errors=(\d+)")
    if ($m.Success) { $errors = [int]$m.Groups[1].Value }
}
$skipMatch = [regex]::Match($outputText, "skipped=(\d+)")
if ($skipMatch.Success) { $skipped = [int]$skipMatch.Groups[1].Value }

$passed = [Math]::Max(0, $ran - $failures - $errors - $skipped)
$passRate = if ($ran -gt 0) { [Math]::Round(100.0 * $passed / $ran, 1) } else { 0.0 }
$resultOk = ($unittestExit -eq 0) -and (-not $smokeFailed)

Write-Host ""
Write-Host "---------------------- 测试摘要 ----------------------" -ForegroundColor Green
Write-Host ("用例总数 : {0}" -f $ran)
Write-Host ("通过     : {0}" -f $passed) -ForegroundColor Green
Write-Host ("失败     : {0}" -f $failures) -ForegroundColor $(if ($failures -gt 0) { "Red" } else { "Gray" })
Write-Host ("错误     : {0}" -f $errors) -ForegroundColor $(if ($errors -gt 0) { "Red" } else { "Gray" })
Write-Host ("跳过     : {0}" -f $skipped)
Write-Host ("通过率   : {0}%" -f $passRate)
Write-Host ("mock 冒烟: {0}" -f $(if ($NoSmoke) { "跳过" } elseif ($smokeFailed) { "失败" } else { "通过" }))
Write-Host ("运行命令 : python -m unittest discover -s tests -v" )
if ($resultOk) {
    Write-Host "结果     : PASS" -ForegroundColor Green
    exit 0
} else {
    Write-Host "结果     : FAIL" -ForegroundColor Red
    exit 1
}

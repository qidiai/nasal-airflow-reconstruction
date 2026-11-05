# =============================================================================
# 罕见无界 · 鼻腔气流仿真工具 —— 一条命令装机自检（Windows / PowerShell 5+）
#
# 用法（仓库根目录或任意目录均可）：
#   powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1
# 可选：
#   -SkipSolve     冒烟只跑到算例+断言（--solve skip），不做 CFD 求解
#   -MaxIter <N>   冒烟求解步数上限（默认 300；合成小算例实测几十秒内收敛）
#
# 步骤：Python/venv → pip 依赖 → cargo 构建 FlowScope → 合成 CT →
#       pA 查看器产物（干净克隆补合成占位，失败仅 WARN）→ pytest 冒烟 →
#       run_all 全链路冒烟（合成数据）。每步打印 [OK]/[FAIL]
#       与耗时；任一步失败以非零退出并给出中文提示。幂等，可重复执行。
#
# 注意：冒烟全程使用合成数据（scripts/make_synthetic_ct.py 生成），
#       不代表真实病例结果。
# =============================================================================
param(
    [switch]$SkipSolve,
    [int]$MaxIter = 300
)

$ErrorActionPreference = "Continue"
$Repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$VenvPy = Join-Path $Repo ".venv\Scripts\python.exe"
$ReqFile = Join-Path $Repo "requirements.txt"
$SolverDir = Join-Path $Repo "code\solver"
$FlowExe = Join-Path $SolverDir "target\release\flowscope.exe"
$SynthCt = Join-Path $Repo "out\synthetic-ct"
$SmokeOut = Join-Path $Repo "out\run-sA-smoke"

$script:Failed = $false
$script:Steps = @()

function Step-Ok($name, $sec, $note) {
    $script:Steps += [pscustomobject]@{ Step = $name; Result = "OK"; Sec = $sec; Note = $note }
    Write-Host ("  [OK]   {0}（{1}s）{2}" -f $name, $sec, $(if ($note) { " —— $note" } else { "" }))
}
function Step-Warn($name, $note) {
    $script:Steps += [pscustomobject]@{ Step = $name; Result = "WARN"; Sec = 0; Note = $note }
    Write-Host ("  [WARN] {0} —— $note" -f $name) -ForegroundColor Yellow
}
function Step-Fail($name, $note) {
    $script:Steps += [pscustomobject]@{ Step = $name; Result = "FAIL"; Sec = 0; Note = $note }
    Write-Host ("  [FAIL] {0} —— $note" -f $name) -ForegroundColor Red
    $script:Failed = $true
    throw $note
}

Write-Host "=== bootstrap：罕见无界 · 一条命令装机自检 ==="
Write-Host "仓库根：$Repo"
$tAll = [System.Diagnostics.Stopwatch]::StartNew()

try {
    # ---------------------------------------------------------- [1/7] Python + venv
    Write-Host "`n[1/7] Python 与虚拟环境"
    $t = [System.Diagnostics.Stopwatch]::StartNew()
    if (Test-Path $VenvPy) {
        Step-Ok "复用已有 .venv" $t.Elapsed.TotalSeconds.ToString("0.0") $VenvPy
    } else {
        $py = $null
        foreach ($cand in @("py -3", "python", "python3")) {
            $exe, $arg = $cand.Split(" ", 2)
            if (Get-Command $exe -ErrorAction SilentlyContinue) { $py = $cand; break }
        }
        if (-not $py) { Step-Fail "Python 检测" "未找到 Python——请安装 Python 3.10+（https://www.python.org）后重试" }
        Write-Host "  创建 .venv（解释器：$py）..."
        if ($py -eq "py -3") { & py -3 -m venv (Join-Path $Repo ".venv") }
        else { & $py -m venv (Join-Path $Repo ".venv") }
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $VenvPy)) {
            Step-Fail "创建 .venv" "python -m venv 失败（exit $LASTEXITCODE）"
        }
        Step-Ok "创建 .venv" $t.Elapsed.TotalSeconds.ToString("0.0") $py
    }

    # ---------------------------------------------------------- [2/7] pip 依赖
    Write-Host "`n[2/7] pip install -r requirements.txt"
    $t = [System.Diagnostics.Stopwatch]::StartNew()
    & $VenvPy -m pip install -q -r $ReqFile 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { Step-Fail "pip 依赖安装" "exit $LASTEXITCODE——检查网络或 requirements.txt" }
    Step-Ok "pip 依赖" $t.Elapsed.TotalSeconds.ToString("0.0") "已装齐（重复执行为 already satisfied）"

    # ---------------------------------------------------------- [3/7] cargo 构建 FlowScope
    Write-Host "`n[3/7] Rust 求解器 FlowScope（cargo build --release）"
    $t = [System.Diagnostics.Stopwatch]::StartNew()
    $script:CanSolve = $false
    if (Get-Command cargo -ErrorAction SilentlyContinue) {
        Push-Location $SolverDir
        try { cargo build --release --quiet 2>&1 | Out-Null; $rc = $LASTEXITCODE }
        finally { Pop-Location }
        if ($rc -eq 0 -and (Test-Path $FlowExe)) {
            Step-Ok "FlowScope 构建" $t.Elapsed.TotalSeconds.ToString("0.0") $FlowExe
            $script:CanSolve = $true
        } else {
            Step-Warn "FlowScope 构建" "cargo build 失败（exit $rc）——CFD 求解不可用，冒烟降级为 --solve skip"
        }
    } else {
        Step-Warn "FlowScope 构建" "未安装 cargo（Rust）——CFD 求解不可用，冒烟降级为 --solve skip；装 Rust 后重跑本脚本即可解锁全链"
    }

    # ---------------------------------------------------------- [4/7] 合成 CT
    Write-Host "`n[4/7] 生成合成 CT（冒烟专用，非真实病例）"
    $t = [System.Diagnostics.Stopwatch]::StartNew()
    & $VenvPy (Join-Path $Repo "scripts\make_synthetic_ct.py") --out $SynthCt 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { Step-Fail "合成 CT 生成" "exit $LASTEXITCODE" }
    $nDcm = (Get-ChildItem $SynthCt -Filter *.dcm -ErrorAction SilentlyContinue).Count
    Step-Ok "合成 CT（$nDcm 个切片）" $t.Elapsed.TotalSeconds.ToString("0.0") $SynthCt

    # ---------------------------------------------------------- [5/7] pA 查看器演示产物
    Write-Host "`n[5/7] 生成 pA 查看器演示产物（干净克隆占位）"
    $t = [System.Diagnostics.Stopwatch]::StartNew()
    & $VenvPy (Join-Path $Repo "scripts\build_pa_placeholder.py") 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Step-Warn "pA 查看器产物" "生成失败（不影响装机，演示查看器降级）"
    } else {
        Step-Ok "pA 查看器产物" $t.Elapsed.TotalSeconds.ToString("0.0") "code\pipeline\webapp\cases\pA\viewer_single.html"
    }

    # ---------------------------------------------------------- [6/7] pytest 冒烟
    Write-Host "`n[6/7] pytest tests/test_quickstart.py"
    $t = [System.Diagnostics.Stopwatch]::StartNew()
    Push-Location $Repo
    try { & $VenvPy -m pytest tests/test_quickstart.py -q 2>&1 | Out-Null; $rc = $LASTEXITCODE }
    finally { Pop-Location }
    if ($rc -ne 0) { Step-Fail "pytest 冒烟" "exit $rc——运行 python -m pytest tests/test_quickstart.py 查看详情" }
    Step-Ok "pytest 冒烟" $t.Elapsed.TotalSeconds.ToString("0.0") "test_quickstart 全绿"

    # ---------------------------------------------------------- [7/7] run_all 全链路冒烟
    Write-Host "`n[7/7] run_all 全链路冒烟（合成数据）"
    $t = [System.Diagnostics.Stopwatch]::StartNew()
    $runAll = Join-Path $Repo "code\pipeline\run_all.py"
    if ($script:CanSolve -and -not $SkipSolve) {
        $mode = "--solve local --backend auto --max-iter $MaxIter --allow-partial-viewer"
        & $VenvPy $runAll --dicom-dir $SynthCt --case-prefix sA --case smoke `
            --solve local --backend auto --max-iter $MaxIter --allow-partial-viewer `
            --out-root $SmokeOut 2>&1 | Out-Null
        $rc = $LASTEXITCODE
    } else {
        $mode = "--solve skip（无 FlowScope，仅算例+断言）"
        & $VenvPy $runAll --dicom-dir $SynthCt --case-prefix sA --case smoke `
            --solve skip --out-root $SmokeOut 2>&1 | Out-Null
        $rc = $LASTEXITCODE
    }
    if ($rc -ne 0) {
        $hint = switch ($rc) {
            2 { "断言闸门停工（exit 2）——查看 $SmokeOut\run_all_manifest-sA-smoke.json 与进度日志" }
            3 { "环境缺失（exit 3）——FlowScope 未构建或 OpenFOAM 缺失" }
            default { "run_all 失败（exit $rc）" }
        }
        Step-Fail "run_all 冒烟（$mode）" $hint
    }
    Step-Ok "run_all 冒烟（$mode）" $t.Elapsed.TotalSeconds.ToString("0.0") "产物：$SmokeOut"

    Write-Host "`n=== bootstrap 完成（总耗时 $($tAll.Elapsed.TotalSeconds.ToString('0.0'))s）==="
    Write-Host "下一步："
    Write-Host "  · 看文档：从零复现.md"
    Write-Host "  · 上传自己的 CT：python code\pipeline\server.py 后浏览器开 http://127.0.0.1:8080"
    Write-Host "  · 命令行直跑：python code\pipeline\run_all.py --dicom-dir <你的CT目录> --case-prefix u1 --case v1 --solve local"
    exit 0
}
catch {
    Write-Host "`n=== bootstrap 中止 ==="
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}

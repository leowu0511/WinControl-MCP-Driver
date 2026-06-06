<#
.SYNOPSIS
    一鍵將 WCMD MCP Server 註冊到 Roo Code (VS Code)。
.EXAMPLE
    .\register_roo_code.ps1 -ApiKey "sk-xxxxxx"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ApiKey,
    [string]$BaseUrl = "https://opencode.ai/zen/go",
    [string]$Model = "qwen3.7-plus",
    [switch]$Global  # 預設寫到專案層級 (團隊共享)
)

$ErrorActionPreference = "Stop"

Write-Host "================================================" -ForegroundColor Cyan
Write-Host " WCMD MCP - Roo Code 安裝程式" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan

# 1. 安裝套件
Write-Host "`n[1/3] 安裝 wcmd 套件..." -ForegroundColor Yellow
& python -m pip install --upgrade git+https://github.com/leowu0511/WinControl-MCP-Driver.git 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Host "  [錯誤] 安裝失敗" -ForegroundColor Red; exit 1 }
Write-Host "  [OK]" -ForegroundColor Green

# 2. 決定設定檔路徑
if ($Global) {
    # 全域: %APPDATA%\Code\User\globalStorage\rooveterinaryinc.roo-cline\settings\mcp_settings.json
    $configFile = Join-Path $env:APPDATA "Code\User\globalStorage\rooveterinaryinc.roo-cline\settings\mcp_settings.json"
    Write-Host "`n[2/3] 寫入全域設定..." -ForegroundColor Yellow
} else {
    # 專案: <cwd>/.roo/mcp.json
    $configFile = Join-Path (Get-Location) ".roo\mcp.json"
    Write-Host "`n[2/3] 寫入專案設定 (當前目錄)..." -ForegroundColor Yellow
}

$configDir = Split-Path -Parent $configFile
if (-not (Test-Path -LiteralPath $configDir)) {
    New-Item -ItemType Directory -Path $configDir -Force | Out-Null
}

# 3. 寫入設定
$wcmdConfig = @{
    command = "wcmd-mcp"
    env = @{
        WCMD_VISION_API_KEY  = $ApiKey
        WCMD_VISION_BASE_URL = $BaseUrl
        WCMD_VISION_MODEL    = $Model
    }
    disabled = $false
    autoApprove = @()
}

$newConfig = @{ mcpServers = @{ wcmd = $wcmdConfig } }
$newConfig | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $configFile -Encoding UTF8

Write-Host "  [OK] 設定檔：$configFile" -ForegroundColor Green
Write-Host "`n[3/3] 重新啟動 VS Code 後即可使用 WCMD" -ForegroundColor Yellow

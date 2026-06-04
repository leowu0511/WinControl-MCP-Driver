<#
.SYNOPSIS
    一鍵將 WCMD MCP Server 註冊到 Claude Desktop。
.DESCRIPTION
    自動安裝 wcmd 套件，並將 MCP 設定寫入 Claude Desktop 的設定檔。
    需要 PowerShell 5.1+ (Windows 內建)。
.PARAMETER ApiKey
    你的 Vision Model API Key (必填)
.PARAMETER BaseUrl
    Vision Model API 端點 (預設 OpenCode Go)
.PARAMETER Model
    Vision Model 名稱 (預設 qwen3.7-plus)
.EXAMPLE
    .\register_claude_desktop.ps1 -ApiKey "sk-xxxxxx"
.NOTES
    執行原則：冪等。重複執行會覆蓋舊的 wcmd 設定。
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ApiKey,

    [string]$BaseUrl = "https://opencode.ai/zen/go",

    [string]$Model = "qwen3.7-plus"
)

$ErrorActionPreference = "Stop"

Write-Host "================================================" -ForegroundColor Cyan
Write-Host " WCMD MCP - Claude Desktop 安裝程式" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan

# 1. 安裝/更新套件
Write-Host "`n[1/3] 安裝 wcmd 套件..." -ForegroundColor Yellow
$pipResult = & python -m pip install --upgrade git+https://github.com/leowu0511/WinControl-MCP-Driver.git 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [錯誤] pip install 失敗" -ForegroundColor Red
    Write-Host $pipResult
    exit 1
}
Write-Host "  [OK] 安裝完成" -ForegroundColor Green

# 2. 確認 wcmd-mcp 指令可用
Write-Host "`n[2/3] 確認 wcmd-mcp 指令..." -ForegroundColor Yellow
$whichResult = & where.exe wcmd-mcp 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [警告] wcmd-mcp 不在 PATH 中" -ForegroundColor Yellow
    Write-Host "  Claude Desktop 可能需要改用絕對路徑" -ForegroundColor Yellow
}

# 3. 寫入設定檔
Write-Host "`n[3/3] 寫入 Claude Desktop 設定..." -ForegroundColor Yellow
$configDir = Join-Path $env:APPDATA "Claude"
$configFile = Join-Path $configDir "claude_desktop_config.json"

if (-not (Test-Path -LiteralPath $configDir)) {
    New-Item -ItemType Directory -Path $configDir -Force | Out-Null
}

# 讀取現有設定 (如有)
$existing = $null
if (Test-Path -LiteralPath $configFile) {
    try {
        $existing = Get-Content -LiteralPath $configFile -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        Write-Host "  [警告] 現有設定檔 JSON 解析失敗，將建立新檔" -ForegroundColor Yellow
    }
}

# 建立新的 wcmd 設定
$wcmdConfig = @{
    command = "wcmd-mcp"
    env = @{
        WCMD_VISION_API_KEY  = $ApiKey
        WCMD_VISION_BASE_URL = $BaseUrl
        WCMD_VISION_MODEL    = $Model
    }
}

# 合併設定 (保留其他 MCP servers)
if ($existing -and $existing.mcpServers) {
    $merged = $existing.mcpServers | ConvertTo-Json -Depth 10 -AsHashtable | ConvertFrom-Json -AsHashtable
    $merged.wcmd = $wcmdConfig
    $newConfig = @{ mcpServers = $merged }
} else {
    $newConfig = @{ mcpServers = @{ wcmd = $wcmdConfig } }
}

$newConfig | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $configFile -Encoding UTF8

Write-Host "  [OK] 設定檔已寫入：$configFile" -ForegroundColor Green
Write-Host "`n================================================" -ForegroundColor Cyan
Write-Host " 安裝完成！請重新啟動 Claude Desktop。" -ForegroundColor Green
Write-Host " 測試：在 Claude 對話框輸入「列出螢幕上的可點擊元素」" -ForegroundColor Green
Write-Host "================================================" -ForegroundColor Cyan

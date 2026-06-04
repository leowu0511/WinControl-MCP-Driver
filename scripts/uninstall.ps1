<#
.SYNOPSIS
    解除安裝 WCMD MCP Server，從所有 Client 設定檔移除。
#>
[CmdletBinding()]
param()

Write-Host "================================================" -ForegroundColor Cyan
Write-Host " WCMD MCP - 解除安裝" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan

# 1. 卸載套件
Write-Host "`n[1/2] 卸載 wcmd 套件..." -ForegroundColor Yellow
& python -m pip uninstall -y WCMD 2>&1 | Out-Null
Write-Host "  [OK]" -ForegroundColor Green

# 2. 從各 Client 設定檔移除
$candidates = @(
    "Claude\claude_desktop_config.json"
    "Code\User\globalStorage\rooveterinaryinc.roo-cline\settings\mcp_settings.json"
    ".roo\mcp.json"
    ".cursor\mcp.json"
)

Write-Host "`n[2/2] 清理設定檔..." -ForegroundColor Yellow
foreach ($rel in $candidates) {
    $full = Join-Path $env:APPDATA $rel
    if (Test-Path -LiteralPath $full) {
        try {
            $cfg = Get-Content -LiteralPath $full -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($cfg.mcpServers.wcmd) {
                $cfg.mcpServers.PSObject.Properties.Remove("wcmd")
                $cfg | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $full -Encoding UTF8
                Write-Host "  [已移除] $rel" -ForegroundColor Green
            }
        } catch {
            Write-Host "  [跳過] $rel (JSON 解析失敗)" -ForegroundColor Yellow
        }
    }
}

Write-Host "`n解除安裝完成。資料目錄 %USERPROFILE%\.wcmd\ 仍保留，可手動刪除。" -ForegroundColor Cyan

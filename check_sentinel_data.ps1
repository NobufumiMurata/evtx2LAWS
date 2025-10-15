#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Sentinel SecurityEvents_CL テーブルのデータとスキーマを確認

.DESCRIPTION
    SecurityEvent互換スキーマ実装後のデータ確認スクリプト
    - SecurityEvents_CL テーブルのデータ確認
    - フィールド数の確認  
    - 最新データの表示
#>

Write-Host "🔍 Sentinel SecurityEvents_CL データ確認スクリプト" -ForegroundColor Cyan
Write-Host "SecurityEvent互換スキーマ (90+フィールド) 対応版" -ForegroundColor Green
Write-Host "=" * 70

# KQLクエリを定義
$queries = @{
    "基本データ確認" = @"
SecurityEvents_CL
| take 5
| project TimeGenerated, Computer, EventID, Account, LogonType, ProcessName
"@
    
    "フィールド数確認" = @"
SecurityEvents_CL
| take 1
| project-away Type, _ResourceId, TenantId, MG, ManagementGroupName, SourceSystem
| project-away TimeGenerated  
| getschema 
| count
"@
    
    "最新データ詳細" = @"
SecurityEvents_CL
| where TimeGenerated > ago(2h)
| take 1
| project-away Type, _ResourceId, TenantId, MG, ManagementGroupName, SourceSystem
"@
    
    "SecurityEvent固有フィールド確認" = @"
SecurityEvents_CL
| where TimeGenerated > ago(2h)
| take 1
| project 
    TimeGenerated, Computer, EventID,
    Account, SubjectUserName, SubjectDomainName,
    TargetUserName, TargetDomainName,
    LogonType, LogonTypeName,
    ProcessName, NewProcessName, CommandLine,
    WorkstationName, IpAddress,
    ObjectServer, ObjectType, ObjectName
"@
    
    "データ統計" = @"
SecurityEvents_CL
| where TimeGenerated > ago(24h)
| summarize 
    Count = count(),
    EventTypes = dcount(EventID),
    Computers = dcount(Computer),
    Accounts = dcount(Account),
    FirstEvent = min(TimeGenerated),
    LastEvent = max(TimeGenerated)
"@
}

Write-Host "`n📋 以下のKQLクエリをLog Analytics Workspaceで実行してください:`n" -ForegroundColor Yellow

foreach ($queryName in $queries.Keys) {
    Write-Host "--- $queryName ---" -ForegroundColor Magenta
    Write-Host $queries[$queryName] -ForegroundColor White
    Write-Host ""
}

Write-Host "🔗 Azure ポータルでの確認手順:" -ForegroundColor Cyan
Write-Host "1. Azure Portal → Log Analytics Workspace → your-workspace" -ForegroundColor White
Write-Host "2. Logs メニューをクリック" -ForegroundColor White
Write-Host "3. 上記のKQLクエリを順番に実行" -ForegroundColor White
Write-Host "4. SecurityEvents_CL テーブルで90+フィールドが表示されることを確認" -ForegroundColor White

Write-Host "`n✅ 期待される結果:" -ForegroundColor Green
Write-Host "- SecurityEvents_CL テーブルにデータが存在" -ForegroundColor White
Write-Host "- フィールド数が90+個表示される" -ForegroundColor White  
Write-Host "- SecurityEvent互換フィールド (Account, LogonType, ProcessName等) が正常に表示" -ForegroundColor White
Write-Host "- Computer, EventID, RawData, TimeGenerated 以外の詳細フィールドも表示" -ForegroundColor White

Write-Host "`n🚀 Next Steps:" -ForegroundColor Cyan
Write-Host "- データが正常に表示される場合: ✅ SecurityEvent互換スキーマ移行完了" -ForegroundColor Green
Write-Host "- まだ4フィールドのみの場合: データが反映されるまで10-15分待機" -ForegroundColor Yellow
Write-Host "- エラーの場合: DCR設定とfunction_app.pyの確認が必要" -ForegroundColor Red

Write-Host "`n🎯 完了目標: SecurityEvents_CLテーブルでSecurityEventテーブルと同等の列表示" -ForegroundColor Magenta
Write-Host "=" * 70
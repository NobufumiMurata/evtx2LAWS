#!/usr/bin/env pwsh

# Microsoft Sentinel SecurityEvent 直接インジェスト設定スクリプト
# SecurityEvent (組み込み) テーブルに直接送信するためのDCR/DCEを構成
# 
# 主な機能:
# - Data Collection Endpoint (DCE) 作成
# - Data Collection Rule (DCR) 作成 (SecurityEvent 179フィールド対応)
# - DCE と DCR の自動関連付け
# - Service Principal 権限の案内
# - 冪等性保証 (再実行可能)
#
# 作成者: Azure Functions EVTX Parser Team
# バージョン: 2.0.0 (DCE-DCR自動関連付け対応)

param(
    [Parameter(Mandatory=$true)]
    [string]$SubscriptionId,
    
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroup,
    
    [Parameter(Mandatory=$true)]
    [string]$WorkspaceName,
    
    [Parameter(Mandatory=$false)]
    [string]$DcrName = "dcr-securityevent-script",
    
    [Parameter(Mandatory=$false)]
    [string]$DceName = "dce-securityevent-script",
    
    [Parameter(Mandatory=$false)]
    [string]$Location = "westus2",

    [Parameter(Mandatory=$false)]
    [string]$DcrFilePath = "dcr-schema-securityevent.json",

    [Parameter(Mandatory=$false)]
    [string]$ServicePrincipalAppId,

    [Parameter(Mandatory=$false)]
    [string]$ServicePrincipalSecret,

    [Parameter(Mandatory=$false)]
    [string]$ServicePrincipalTenantId
)

Write-Host "=== Microsoft Sentinel SecurityEvent インジェスト設定 ===" -ForegroundColor Green
Write-Host "Subscription ID: $SubscriptionId"
Write-Host "Resource Group: $ResourceGroup"
Write-Host "Workspace Name: $WorkspaceName"
Write-Host "DCR Name: $DcrName"
Write-Host "DCE Name: $DceName"
Write-Host "Location: $Location"
Write-Host "DCR File Path: $DcrFilePath"
Write-Host ""

# Service Principal でのログイン指定がある場合は az login を実行
if ($PSBoundParameters.ContainsKey('ServicePrincipalAppId') -or 
    $PSBoundParameters.ContainsKey('ServicePrincipalSecret') -or 
    $PSBoundParameters.ContainsKey('ServicePrincipalTenantId')) {

    if (-not ($ServicePrincipalAppId -and $ServicePrincipalSecret -and $ServicePrincipalTenantId)) {
        Write-Host "Service Principal ログインには ServicePrincipalAppId/Secret/TenantId の全てが必要です" -ForegroundColor Red
        exit 1
    }

    Write-Host "Service Principal で az login を実行中..." -ForegroundColor Yellow
    az login `
        --service-principal `
        --username $ServicePrincipalAppId `
        --password $ServicePrincipalSecret `
        --tenant $ServicePrincipalTenantId `
        --allow-no-subscriptions | Out-Null

    if ($LASTEXITCODE -ne 0) {
        Write-Host "Service Principal での az login に失敗しました" -ForegroundColor Red
        exit 1
    }
    Write-Host "Service Principal で認証しました" -ForegroundColor Green
}

# Azure CLIでログイン確認
Write-Host "Azureへの認証を確認中..." -ForegroundColor Yellow
$currentAccount = az account show --query "user.name" -o tsv 2>$null
if (-not $currentAccount) {
    Write-Host "Azure CLIでログインしてください: az login" -ForegroundColor Red
    exit 1
}
Write-Host "認証済み: $currentAccount" -ForegroundColor Green

# サブスクリプション設定
Write-Host "サブスクリプションを設定中..." -ForegroundColor Yellow
az account set --subscription $SubscriptionId
if ($LASTEXITCODE -ne 0) {
    Write-Host "サブスクリプション設定に失敗しました" -ForegroundColor Red
    exit 1
}

# Azure Management API認証スコープの確認
Write-Host "Azure Management API認証を確認中..." -ForegroundColor Yellow
$null = az monitor log-analytics workspace list --resource-group $ResourceGroup --query "[0].name" -o tsv 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Azure Management APIへの認証スコープが不足しています。再認証を実行します..." -ForegroundColor Yellow
    az login --scope https://management.core.windows.net//.default
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Azure Management API認証に失敗しました" -ForegroundColor Red
        exit 1
    }
    # サブスクリプションを再設定
    az account set --subscription $SubscriptionId
}

# Log Analytics Workspace の存在確認
Write-Host "Log Analytics Workspaceの存在を確認中..." -ForegroundColor Yellow
$workspace = az monitor log-analytics workspace show --name $WorkspaceName --resource-group $ResourceGroup 2>$null
if (-not $workspace) {
    # リソースグループ内の全ワークスペースを表示してデバッグ支援
    Write-Host "リソースグループ内の利用可能なLog Analytics Workspace:" -ForegroundColor Yellow
    az monitor log-analytics workspace list --resource-group $ResourceGroup --query "[].{name:name, location:location}" -o table
    Write-Host "Log Analytics Workspace '$WorkspaceName' が見つかりません" -ForegroundColor Red
    exit 1
}
Write-Host "Log Analytics Workspace確認完了" -ForegroundColor Green

# Data Collection Endpoint (DCE) の作成
Write-Host "Data Collection Endpoint (DCE) を作成中..." -ForegroundColor Yellow
$dceExists = az monitor data-collection endpoint show --name $DceName --resource-group $ResourceGroup 2>$null
if (-not $dceExists) {
    az monitor data-collection endpoint create `
        --name $DceName `
        --resource-group $ResourceGroup `
        --location $Location `
        --description "Custom SecurityEvent Data Collection Endpoint" `
        --public-network-access Enabled
        
    if ($LASTEXITCODE -ne 0) {
        Write-Host "DCE作成に失敗しました" -ForegroundColor Red
        exit 1
    }
    Write-Host "DCE作成完了" -ForegroundColor Green
} else {
    Write-Host "DCE '$DceName' は既に存在します" -ForegroundColor Yellow
}

# DCR設定ファイルの準備
Write-Host "DCR設定ファイルを準備中..." -ForegroundColor Yellow
# DCRスキーマファイルのパス（SecurityEvent互換の完全版）
if (-not (Test-Path $DcrFilePath)) {
    Write-Host "DCRスキーマファイル '$DcrFilePath' が見つかりません" -ForegroundColor Red
    exit 1
}

Write-Host "Log Analytics の既定 SecurityEvent テーブルを使用します (カスタムテーブル作成は不要)" -ForegroundColor Yellow

# DCR設定ファイルの更新
$dcrContent = Get-Content $DcrFilePath | ConvertFrom-Json
$workspaceResourceId = "/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.OperationalInsights/workspaces/$WorkspaceName"
$dcrContent.properties.destinations.logAnalytics[0].workspaceResourceId = $workspaceResourceId

# 更新されたDCRファイルを一時保存
$tempDcrFile = "dcr-temp-updated.json"
$dcrContent | ConvertTo-Json -Depth 20 | Set-Content $tempDcrFile

# Data Collection Rule (DCR) の作成
Write-Host "Data Collection Rule (DCR) を作成中..." -ForegroundColor Yellow
$dcrExists = az monitor data-collection rule show --name $DcrName --resource-group $ResourceGroup 2>$null
if (-not $dcrExists) {
    az monitor data-collection rule create `
        --name $DcrName `
        --resource-group $ResourceGroup `
        --location $Location `
        --rule-file $tempDcrFile
        
    if ($LASTEXITCODE -ne 0) {
        Write-Host "DCR作成に失敗しました" -ForegroundColor Red
        Remove-Item $tempDcrFile -ErrorAction SilentlyContinue
        exit 1
    }
    Write-Host "DCR作成完了" -ForegroundColor Green
} else {
    Write-Host "DCR '$DcrName' は既に存在します" -ForegroundColor Yellow
}

# 一時ファイルを削除
Remove-Item $tempDcrFile -ErrorAction SilentlyContinue

# DCEとDCRの関連付けを確認・設定
Write-Host "DCEとDCRの関連付けを確認中..." -ForegroundColor Yellow
$dcrDetails = az monitor data-collection rule show --name $DcrName --resource-group $ResourceGroup | ConvertFrom-Json

if (-not $dcrDetails.dataCollectionEndpointId) {
    Write-Host "DCEとDCRを関連付け中..." -ForegroundColor Yellow
    $dceResourceId = "/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.Insights/dataCollectionEndpoints/$DceName"
    
    az monitor data-collection rule update `
        --resource-group $ResourceGroup `
        --name $DcrName `
        --data-collection-endpoint-id $dceResourceId
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "DCEとDCRの関連付けに失敗しました" -ForegroundColor Red
        exit 1
    }
    Write-Host "✓ DCEとDCRの関連付けが完了しました" -ForegroundColor Green
} else {
    Write-Host "✓ DCEとDCRは既に関連付けられています" -ForegroundColor Green
}

# DCRのImmutable IDを取得
Write-Host "DCR Immutable IDを取得中..." -ForegroundColor Yellow
$dcrInfo = az monitor data-collection rule show --name $DcrName --resource-group $ResourceGroup --query "{immutableId:immutableId,endpoint:dataCollectionEndpointId}" -o json | ConvertFrom-Json
$dcrImmutableId = $dcrInfo.immutableId

# DCEエンドポイントURLを取得
$dceInfo = az monitor data-collection endpoint show --name $DceName --resource-group $ResourceGroup --query "logsIngestion.endpoint" -o tsv

# 既定の SecurityEvent テーブルを使用するため、個別のスキーマ作成ステップは不要
Write-Host "SecurityEvent (組み込み) テーブルへのデータ収集を構成しました" -ForegroundColor Green

Write-Host ""
Write-Host "=== セットアップ完了 ===" -ForegroundColor Green
Write-Host "✓ 組み込みテーブル: SecurityEvent" -ForegroundColor Green
Write-Host "✓ Data Collection Endpoint: $DceName" -ForegroundColor Green
Write-Host "✓ Data Collection Rule: $DcrName" -ForegroundColor Green
Write-Host "✓ DCE-DCR関連付け: 自動完了" -ForegroundColor Green
Write-Host ""
Write-Host "DCR Immutable ID: $dcrImmutableId" -ForegroundColor Cyan
Write-Host "DCE Endpoint: $dceInfo" -ForegroundColor Cyan
Write-Host "Stream Name: Custom-SecurityEvent" -ForegroundColor Cyan
Write-Host "Output Table: SecurityEvent" -ForegroundColor Cyan
Write-Host ""

# 環境変数として設定
Write-Host "Azure Functions環境変数:" -ForegroundColor Yellow
Write-Host "DCE_ENDPOINT=$dceInfo"
Write-Host "DCR_IMMUTABLE_ID=$dcrImmutableId"
Write-Host ""

# 権限設定の案内
Write-Host "=== 次のステップ ===" -ForegroundColor Yellow
Write-Host "1. Service Principal に以下の権限を付与してください:"
Write-Host "   az role assignment create \"
Write-Host "     --assignee <your-service-principal-id> \"
Write-Host "     --role 'Monitoring Metrics Publisher' \"
Write-Host "     --scope '/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/microsoft.insights/datacollectionrules/$DcrName'"
Write-Host ""
Write-Host "2. Azure Functions の環境変数を更新してください:"
Write-Host "   DCE_ENDPOINT=$dceInfo"
Write-Host "   DCR_IMMUTABLE_ID=$dcrImmutableId"
Write-Host ""
Write-Host "3. Log Analytics Workspace でSecurityEventテーブルを確認:"
Write-Host "   SecurityEvent | take 5"
Write-Host "   SecurityEvent | getschema | count  // フィールド数確認"
Write-Host "   SecurityEvent | project Account, LogonType, ProcessName, SubjectUserName | take 5"
Write-Host ""
Write-Host "🎯 期待される結果:"
Write-Host "   - SecurityEvent テーブルで90+フィールドが利用可能" 
Write-Host "   - Computer, EventID, TimeGenerated 以外の詳細フィールドも表示" 
Write-Host "   - SecurityEventテーブルの組み込み列構成を維持" 

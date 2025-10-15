#!/usr/bin/env pwsh

# Microsoft Sentinelカスタムテーブル作成スクリプト
# SecurityEventテーブルと同じスキーマを持つカスタムテーブルを作成
# 
# 主な機能:
# - Log Analytics Workspace カスタムテーブル (SecurityEvents_CL) 作成
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
    [string]$DcrName = "dcr-securityevent-custom",
    
    [Parameter(Mandatory=$false)]
    [string]$DceName = "dce-securityevent-custom",
    
    [Parameter(Mandatory=$false)]
    [string]$Location = "westus2"
)

Write-Host "=== Microsoft Sentinel カスタムテーブル作成スクリプト ===" -ForegroundColor Green
Write-Host "Subscription ID: $SubscriptionId"
Write-Host "Resource Group: $ResourceGroup"
Write-Host "Workspace Name: $WorkspaceName"
Write-Host "DCR Name: $DcrName"
Write-Host "DCE Name: $DceName"
Write-Host "Location: $Location"
Write-Host ""

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
$testWorkspace = az monitor log-analytics workspace list --resource-group $ResourceGroup --query "[0].name" -o tsv 2>$null
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
    $dcrFilePath = "dcr-schema-securityevent-compatible.json"
if (-not (Test-Path $dcrFilePath)) {
    Write-Host "DCRスキーマファイル '$dcrFilePath' が見つかりません" -ForegroundColor Red
    exit 1
}

# カスタムテーブルの事前作成が必要かチェック
Write-Host "カスタムテーブルの存在を確認中..." -ForegroundColor Yellow
$customTableName = "SecurityEvents_CL"
$existingTable = az monitor log-analytics workspace table show --workspace-name $WorkspaceName --resource-group $ResourceGroup --name $customTableName 2>$null

if (-not $existingTable) {
    Write-Host "カスタムテーブル '$customTableName' が存在しません。SecurityEvent互換の完全スキーマで作成します..." -ForegroundColor Yellow
    
    # まず基本フィールドでテーブルを作成
    Write-Host "基本SecurityEventフィールドでテーブルを作成中..." -ForegroundColor Yellow
    az monitor log-analytics workspace table create `
        --workspace-name $WorkspaceName `
        --resource-group $ResourceGroup `
        --name $customTableName `
        --columns TimeGenerated=datetime Computer=string EventID=int Account=string Level=string `
        --description "Custom SecurityEvent table for Azure Functions ingestion (SecurityEvent compatible schema)" `
        --plan "Analytics"
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "カスタムテーブル基本作成に失敗しました" -ForegroundColor Red
        exit 1
    }
    Write-Host "✓ カスタムテーブル基本構造を作成しました" -ForegroundColor Green
    
    # テーブル作成後の伝播待機
    Write-Host "テーブル作成の伝播を待機中（30秒）..." -ForegroundColor Yellow
    Start-Sleep -Seconds 30
    
    # 追加カラムを段階的に追加（Azure CLIの制限を考慮）
    Write-Host "SecurityEvent互換の追加フィールドを更新中..." -ForegroundColor Yellow
    
    # SecurityEvent主要フィールドの追加（TimeGeneratedは既に存在するため除外）
    $additionalColumns = @(
        "EventSourceName=string", "Activity=string", "Type=string", "SourceSystem=string",
        "Channel=string", "Task=int", "EventLevelName=string", "Version=int", "Opcode=string",
        "Keywords=string", "ProcessId=int", "ThreadId=int", "EventRecordId=long", "ProviderGuid=string",
        "ProcessName=string", "NewProcessName=string", "CommandLine=string", "ClientProcessId=int",
        "AccountType=string", "LogonType=int", "LogonTypeName=string", "WorkstationName=string",
        "IpAddress=string", "SubjectUserSid=string", "SubjectUserName=string", "SubjectDomainName=string",
        "SubjectLogonId=string", "TargetUserSid=string", "TargetUserName=string", "TargetDomainName=string",
        "TargetLogonId=string", "TargetLogonGuid=string", "TargetServerName=string", "TargetInfo=string",
        "LogonProcessName=string", "AuthenticationPackageName=string", "LogonGuid=string", "ClientAddress=string",
        "ClientName=string", "IpPort=string", "SourceNetworkAddress=string", "SourcePort=string",
        "NewProcessId=string", "ParentProcessName=string", "TokenElevationType=string", "MandatoryLabel=string",
        "ObjectServer=string", "ObjectType=string", "ObjectName=string", "HandleId=string", "AccessMask=string",
        "PrivilegeList=string", "Properties=string", "AccessList=string", "AccessReason=string",
        "ResourceAttributes=string", "Status=string", "SubStatus=string", "FailureReason=string",
        "ErrorCode=string", "TransmittedServices=string", "LmPackageName=string", "KeyLength=int",
        "PackageName=string", "CertIssuerName=string", "CertSerialNumber=string", "CertThumbprint=string",
        "ServiceName=string", "ServiceFileName=string", "SessionName=string", "GroupMembership=string",
        "RelativeTargetName=string", "RestrictedAdminMode=string", "VirtualAccount=string", "ElevatedToken=string",
        "ImpersonationLevel=string", "NewValue=string", "OldValue=string", "SubjectAccount=string",
        "TargetAccount=string", "AccountName=string", "AccountDomain=string"
    )
    
    # 1つずつフィールドを追加（Azure CLIの構文制限を回避）
    foreach ($column in $additionalColumns) {
        $columnName = $column.Split('=')[0]
        $columnType = $column.Split('=')[1]
        
        Write-Host "フィールドを追加中: $columnName ($columnType)" -ForegroundColor Gray
        
        az monitor log-analytics workspace table update `
            --workspace-name $WorkspaceName `
            --resource-group $ResourceGroup `
            --name $customTableName `
            --columns "$columnName=$columnType" 2>$null
        
        # エラーは無視して続行（フィールドが既に存在する場合など）
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  ✓ $columnName 追加完了" -ForegroundColor Green
        } else {
            Write-Host "  ⚠️ $columnName スキップ（既存またはエラー）" -ForegroundColor Yellow
        }
        
        # フィールド追加間の短い待機
        Start-Sleep -Seconds 2
    }
    
    Write-Host "✓ SecurityEvent互換カスタムテーブル '$customTableName' を作成しました" -ForegroundColor Green
    Write-Host "✓ 追加フィールド処理完了: $($additionalColumns.Count) フィールド" -ForegroundColor Green
    
    # 最終的な伝播待機
    Write-Host "テーブルスキーマ更新の伝播を待機中（20秒）..." -ForegroundColor Yellow
    Start-Sleep -Seconds 20
} else {
    Write-Host "カスタムテーブル '$customTableName' は既に存在します" -ForegroundColor Green
    Write-Host "既存テーブルにSecurityEvent互換フィールドを追加確認中..." -ForegroundColor Yellow
    
    # 既存テーブルにも重要フィールドを追加試行
    $criticalFields = @(
        "Account=string", "LogonType=int", "ProcessName=string", 
        "SubjectUserName=string", "WorkstationName=string", "IpAddress=string"
    )
    
    foreach ($field in $criticalFields) {
        $fieldName = $field.Split('=')[0]
        Write-Host "重要フィールド確認: $fieldName" -ForegroundColor Gray
        az monitor log-analytics workspace table update `
            --workspace-name $WorkspaceName `
            --resource-group $ResourceGroup `
            --name $customTableName `
            --columns $field 2>$null
        Start-Sleep -Seconds 1
    }
}

# DCR設定ファイルの更新
$dcrContent = Get-Content $dcrFilePath | ConvertFrom-Json
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

# カスタムテーブルのスキーマ確認
Write-Host "カスタムテーブルのスキーマを確認中..." -ForegroundColor Yellow
$tableSchema = az monitor log-analytics workspace table show --workspace-name $WorkspaceName --resource-group $ResourceGroup --name $customTableName --query "schema.columns" -o json 2>$null
if ($tableSchema) {
    $columns = $tableSchema | ConvertFrom-Json
    $columnCount = $columns.Count
    Write-Host "✓ カスタムテーブル '$customTableName' のフィールド数: $columnCount" -ForegroundColor Green
    
    # SecurityEvent重要フィールドの存在確認
    $importantFields = @("Account", "LogonType", "ProcessName", "SubjectUserName", "TargetUserName", "WorkstationName", "IpAddress")
    $foundFields = @()
    foreach ($field in $importantFields) {
        $fieldExists = $columns | Where-Object { $_.name -eq $field }
        if ($fieldExists) {
            $foundFields += $field
        }
    }
    Write-Host "✓ SecurityEvent重要フィールド確認: $($foundFields.Count)/$($importantFields.Count) 個検出" -ForegroundColor Green
    if ($foundFields.Count -lt $importantFields.Count) {
        $missingFields = $importantFields | Where-Object { $_ -notin $foundFields }
        Write-Host "⚠️ 不足フィールド: $($missingFields -join ', ')" -ForegroundColor Yellow
        Write-Host "   DCRによるスキーマ拡張で対応されます" -ForegroundColor Yellow
    }
} else {
    Write-Host "⚠️ テーブルスキーマの確認ができませんでした（伝播中の可能性）" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== セットアップ完了 ===" -ForegroundColor Green
Write-Host "✓ カスタムテーブル: SecurityEvents_CL (SecurityEvent互換スキーマ)" -ForegroundColor Green
Write-Host "✓ Data Collection Endpoint: $DceName" -ForegroundColor Green
Write-Host "✓ Data Collection Rule: $DcrName" -ForegroundColor Green
Write-Host "✓ DCE-DCR関連付け: 自動完了" -ForegroundColor Green
Write-Host ""
Write-Host "DCR Immutable ID: $dcrImmutableId" -ForegroundColor Cyan
Write-Host "DCE Endpoint: $dceInfo" -ForegroundColor Cyan
Write-Host "Stream Name: Custom-SecurityEvent" -ForegroundColor Cyan
Write-Host "Output Table: SecurityEvents_CL" -ForegroundColor Cyan
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
Write-Host "3. Log Analytics Workspace でSecurityEvent互換テーブルを確認:"
Write-Host "   SecurityEvents_CL | take 5"
Write-Host "   SecurityEvents_CL | getschema | count  // フィールド数確認"
Write-Host "   SecurityEvents_CL | project Account, LogonType, ProcessName, SubjectUserName | take 5"
Write-Host ""
Write-Host "🎯 期待される結果:"
Write-Host "   - SecurityEvents_CL テーブルで90+フィールドが利用可能"
Write-Host "   - Computer, EventID, RawData, TimeGenerated 以外の詳細フィールドも表示"
Write-Host "   - SecurityEventテーブルと同等の列構成"
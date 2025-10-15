#!/usr/bin/env pwsh
<#
.SYNOPSIS
    SecurityEvent互換の完全スキーマでカスタムテーブルを作成

.DESCRIPTION
    DCRスキーマファイルから全フィールドを読み取り、
    Log Analytics WorkspaceにSecurityEvent互換の90+フィールドを持つ
    カスタムテーブルを正しく作成する
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$SubscriptionId,
    
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroup,
    
    [Parameter(Mandatory=$true)]
    [string]$WorkspaceName,
    
    [Parameter(Mandatory=$false)]
    [string]$TableName = "SecurityEvents_CL"
)

Write-Host "🔧 SecurityEvent互換カスタムテーブル作成スクリプト" -ForegroundColor Cyan
Write-Host "DCRスキーマからの完全フィールド定義読み取り版" -ForegroundColor Green
Write-Host "=" * 70

# 設定確認
Write-Host "設定:" -ForegroundColor Yellow
Write-Host "  Subscription: $SubscriptionId"
Write-Host "  Resource Group: $ResourceGroup"
Write-Host "  Workspace: $WorkspaceName"
Write-Host "  Table Name: $TableName"
Write-Host ""

# Azure認証確認
Write-Host "Azure認証を確認中..." -ForegroundColor Yellow
$currentAccount = az account show --query "user.name" -o tsv 2>$null
if (-not $currentAccount) {
    Write-Host "❌ Azure CLIでログインしてください: az login" -ForegroundColor Red
    exit 1
}
Write-Host "✅ 認証済み: $currentAccount" -ForegroundColor Green

# サブスクリプション設定
az account set --subscription $SubscriptionId
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ サブスクリプション設定に失敗" -ForegroundColor Red
    exit 1
}

# DCRスキーマファイル読み取り
$dcrSchemaFile = "dcr-schema-securityevent-compatible.json"
if (-not (Test-Path $dcrSchemaFile)) {
    Write-Host "❌ DCRスキーマファイルが見つかりません: $dcrSchemaFile" -ForegroundColor Red
    exit 1
}

Write-Host "📄 DCRスキーマファイルを読み込み中..." -ForegroundColor Yellow
try {
    $dcrSchema = Get-Content $dcrSchemaFile | ConvertFrom-Json
    $streamColumns = $dcrSchema.properties.streamDeclarations."Custom-SecurityEvent".columns
    
    Write-Host "✅ DCRスキーマ読み込み完了" -ForegroundColor Green
    Write-Host "  定義されているフィールド数: $($streamColumns.Count)" -ForegroundColor Cyan
} catch {
    Write-Host "❌ DCRスキーマファイル読み込み失敗: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# 既存テーブルの確認
Write-Host "`n📋 既存テーブルの確認..." -ForegroundColor Yellow
$existingTable = az monitor log-analytics workspace table show --workspace-name $WorkspaceName --resource-group $ResourceGroup --name $TableName 2>$null

if ($existingTable) {
    Write-Host "⚠️ テーブル '$TableName' は既に存在します" -ForegroundColor Yellow
    $confirm = Read-Host "削除して再作成しますか？ (y/N)"
    if ($confirm -eq 'y' -or $confirm -eq 'Y') {
        Write-Host "🗑️ 既存テーブルを削除中..." -ForegroundColor Yellow
        az monitor log-analytics workspace table delete --workspace-name $WorkspaceName --resource-group $ResourceGroup --name $TableName --yes
        if ($LASTEXITCODE -ne 0) {
            Write-Host "❌ テーブル削除に失敗" -ForegroundColor Red
            exit 1
        }
        Write-Host "✅ 既存テーブルを削除しました" -ForegroundColor Green
        Start-Sleep -Seconds 30  # 削除の伝播を待機
    } else {
        Write-Host "ℹ️ 処理を中断しました" -ForegroundColor Blue
        exit 0
    }
}

# フィールド定義の変換
Write-Host "`n🔄 フィールド定義をAzure CLI形式に変換中..." -ForegroundColor Yellow
$columnDefinitions = @()

# Azure Log Analyticsの予約語リスト
$reservedWords = @(
    "Type", "TenantId", "SourceSystem", "MG", "ManagementGroupName", 
    "_ResourceId", "_SubscriptionId", "_ItemId", "Computer"
)

foreach ($column in $streamColumns) {
    $columnName = $column.name
    $columnType = $column.type
    
    # 予約語をスキップ
    if ($columnName -in $reservedWords) {
        Write-Host "  スキップ（予約語）: $columnName" -ForegroundColor Yellow
        continue
    }
    
    # Azure CLIの型マッピング
    $azureType = switch ($columnType) {
        "datetime" { "datetime" }
        "string" { "string" }
        "int" { "int" }
        "long" { "long" }
        "real" { "real" }
        "boolean" { "boolean" }
        "dynamic" { "dynamic" }
        default { "string" }
    }
    
    $columnDefinitions += [PSCustomObject]@{
        Name = $columnName
        Type = $azureType
        Argument = "$columnName=$azureType"
    }
}

Write-Host "✅ フィールド変換完了" -ForegroundColor Green
Write-Host "  変換されたフィールド数: $($columnDefinitions.Count)" -ForegroundColor Cyan

# Azure CLIコマンド長制限の対策（常に完全スキーマを送信）
Write-Host "`n🏗️ カスタムテーブルを作成および拡張中..." -ForegroundColor Yellow

# 初期作成時に優先するフィールド
$preferredColumns = @("TimeGenerated","EventID","Level","Account","EventSourceName","Activity","Channel","ProcessName")
$initialColumnArguments = New-Object System.Collections.ArrayList

foreach ($preferred in $preferredColumns) {
    $match = $columnDefinitions | Where-Object { $_.Name -eq $preferred } | Select-Object -First 1
    if ($match -and -not $initialColumnArguments.Contains($match.Argument)) {
        [void]$initialColumnArguments.Add($match.Argument)
    }
}

if ($initialColumnArguments.Count -eq 0) {
    Write-Host "⚠️ TimeGenerated がスキーマに見つからないため初期カラムに追加します" -ForegroundColor Yellow
    [void]$initialColumnArguments.Add("TimeGenerated=datetime")
}

$maxInitialColumns = 20
$additionalColumnsNeeded = $maxInitialColumns - $initialColumnArguments.Count
if ($additionalColumnsNeeded -gt 0) {
    $fallbackColumns = $columnDefinitions | Where-Object { -not $initialColumnArguments.Contains($_.Argument) } | Select-Object -First $additionalColumnsNeeded
    foreach ($fallback in $fallbackColumns) {
        if (-not $initialColumnArguments.Contains($fallback.Argument)) {
            [void]$initialColumnArguments.Add($fallback.Argument)
        }
    }
}

Write-Host "  段階1: 初期 $($initialColumnArguments.Count) フィールドでテーブル作成..." -ForegroundColor Cyan

$azCreateCmd = @(
    "az", "monitor", "log-analytics", "workspace", "table", "create",
    "--workspace-name", $WorkspaceName,
    "--resource-group", $ResourceGroup,
    "--name", $TableName,
    "--description", "SecurityEvent compatible custom table with full schema",
    "--plan", "Analytics",
    "--columns"
)

foreach ($field in $initialColumnArguments) {
    $azCreateCmd += [string]$field
}

& $azCreateCmd[0] $azCreateCmd[1..($azCreateCmd.Length-1)]
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ テーブル作成に失敗しました" -ForegroundColor Red
    exit 1
}

Write-Host "✅ 初期テーブル作成完了" -ForegroundColor Green
Start-Sleep -Seconds 45  # テーブル作成の伝播を待機

# 段階2: 残りのフィールドをバッチごとに追加（常に完全スキーマを送信）
$remainingColumns = $columnDefinitions | Where-Object { -not $initialColumnArguments.Contains($_.Argument) }
$totalColumns = $columnDefinitions.Count

if ($remainingColumns.Count -gt 0) {
    Write-Host "  段階2: 残り $($remainingColumns.Count) フィールドを追加..." -ForegroundColor Cyan

    $appliedColumns = New-Object System.Collections.ArrayList
    foreach ($field in $initialColumnArguments) {
        if (-not $appliedColumns.Contains($field)) {
            [void]$appliedColumns.Add([string]$field)
        }
    }

    $batchSize = 20
    $remainingArgs = @($remainingColumns | ForEach-Object { [string]$_.Argument })

    for ($i = 0; $i -lt $remainingArgs.Count; $i += $batchSize) {
        $batchEnd = [Math]::Min($i + $batchSize - 1, $remainingArgs.Count - 1)
        $batch = $remainingArgs[$i..$batchEnd]

        foreach ($columnArg in $batch) {
            if (-not $appliedColumns.Contains($columnArg)) {
                [void]$appliedColumns.Add($columnArg)
            }
        }

        $updateCmd = @(
            "az", "monitor", "log-analytics", "workspace", "table", "update",
            "--workspace-name", $WorkspaceName,
            "--resource-group", $ResourceGroup,
            "--name", $TableName,
            "--columns"
        )

        foreach ($columnArg in $appliedColumns) {
            $updateCmd += [string]$columnArg
        }

        Write-Host "    送信中: $($batch.Count) フィールドを追加 (累計 $($appliedColumns.Count)/$totalColumns)" -ForegroundColor Gray

        & $updateCmd[0] $updateCmd[1..($updateCmd.Length-1)]
        if ($LASTEXITCODE -ne 0) {
            Write-Host "❌ フィールド追加処理に失敗しました" -ForegroundColor Red
            exit 1
        }

        Start-Sleep -Seconds 8  # レート制限を考慮
    }

    Write-Host "✅ 全フィールド追加完了" -ForegroundColor Green
} else {
    Write-Host "ℹ️ DCRスキーマのフィールド数は初期作成分と一致します" -ForegroundColor Blue
}

# 最終確認
Write-Host "`n📊 テーブル作成結果の確認..." -ForegroundColor Yellow
Start-Sleep -Seconds 30  # 最終的な伝播を待機

$finalTable = az monitor log-analytics workspace table show --workspace-name $WorkspaceName --resource-group $ResourceGroup --name $TableName --query "schema.columns" -o json 2>$null

if ($finalTable) {
    $finalColumns = $finalTable | ConvertFrom-Json
    $finalColumnCount = $finalColumns.Count
    
    Write-Host "✅ テーブル作成完了!" -ForegroundColor Green
    Write-Host "  最終フィールド数: $finalColumnCount" -ForegroundColor Cyan
    
    # 重要フィールドの存在確認
    $importantFields = @("Account", "LogonType", "ProcessName", "SubjectUserName", "TargetUserName", "WorkstationName", "IpAddress", "CommandLine", "ObjectName")
    $foundImportantFields = @()
    
    foreach ($field in $importantFields) {
        $fieldExists = $finalColumns | Where-Object { $_.name -eq $field }
        if ($fieldExists) {
            $foundImportantFields += $field
        }
    }
    
    Write-Host "  SecurityEvent重要フィールド: $($foundImportantFields.Count)/$($importantFields.Count) 個確認" -ForegroundColor Cyan
    
    if ($foundImportantFields.Count -eq $importantFields.Count) {
        Write-Host "🎉 SecurityEvent互換テーブル作成完全成功!" -ForegroundColor Green
    } else {
        $missingFields = $importantFields | Where-Object { $_ -notin $foundImportantFields }
        Write-Host "⚠️ 不足重要フィールド: $($missingFields -join ', ')" -ForegroundColor Yellow
    }
} else {
    Write-Host "⚠️ テーブル確認に失敗（まだ伝播中の可能性）" -ForegroundColor Yellow
}

Write-Host "`n🔍 確認用KQLクエリ:" -ForegroundColor Magenta
Write-Host "SecurityEvents_CL | getschema | count" -ForegroundColor White
Write-Host "SecurityEvents_CL | take 1 | project Account, LogonType, ProcessName, SubjectUserName" -ForegroundColor White

Write-Host "`n✅ スクリプト完了!" -ForegroundColor Green
Write-Host "=" * 70
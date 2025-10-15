# EVTX to Log Analytics Workspace (LAWS) Azure Function

このAzure FunctionsアプリケーションはBlob Storageに追加されたEVTXファイルを自動的に処理し、Azure Monitor Log Ingest APIを使用してMicrosoft SentinelのSecurityEvents_CLカスタムテーブルに送信します。

## ✅ プロジェクト完了状況

**SecurityEventテーブル完全互換性を実現！**
- ✅ SecurityEvents_CLカスタムテーブル作成完了（90フィールド）
- ✅ SecurityEventテーブルと同等のスキーマ構成
- ✅ DCR (Data Collection Rule) 設定完了
- ✅ 完全なフィールドマッピング実装
- ✅ テストデータ送信成功確認

## 機能

- **Blob Trigger**: 指定されたBlobコンテナにEVTXファイルが追加されると自動実行
- **EVTX解析**: EVTXファイルをXMLとして解析し、SecurityEvent互換形式のJSONに変換
- **Log Analytics送信**: Azure Monitor Log Ingest APIを使用してSecurityEvents_CLテーブルに送信
- **完全互換性**: SecurityEventテーブルの90フィールドに対応した包括的データマッピング
- **バッチ処理**: 大量のイベントを効率的に処理するため1000件ずつバッチ送信
- **エラーハンドリング**: 適切なログ出力とエラー処理

## 必要な依存関係

```
azure-functions
azure-monitor-ingestion
azure-identity
python-evtx
requests
```

## 環境変数の設定

以下の環境変数を設定する必要があります：

### 必須設定
- `DCE_ENDPOINT`: Data Collection Endpoint URL
  - 例: `https://your-dce-endpoint.monitor.azure.com`
- `DCR_IMMUTABLE_ID`: Data Collection Rule の Immutable ID
  - 例: `dcr-12345678abcd1234abcd1234abcd1234`

### オプション設定
- `STREAM_NAME`: データストリーム名 (デフォルト: `Custom-SecurityEvent`)

### Azure Functions設定
- `AzureWebJobsStorage`: Azure Storage接続文字列
- `FUNCTIONS_WORKER_RUNTIME`: `python`
- `d0e84d_STORAGE`: Blob Trigger用のストレージ接続文字列

## Azure リソースの準備

### 1. Data Collection Endpoint (DCE)
```bash
az monitor data-collection endpoint create \\
  --name "evtx-dce" \\
  --resource-group "your-rg" \\
  --location "japaneast" \\
  --network-acls-public-network-access "Enabled"
```

### 2. Data Collection Rule (DCR)
SecurityEventテーブル用のDCRを作成します：

```json
{
  "location": "japaneast",
  "properties": {
    "dataCollectionEndpointId": "/subscriptions/{subscription-id}/resourceGroups/{rg}/providers/Microsoft.Insights/dataCollectionEndpoints/{dce-name}",
    "streamDeclarations": {
      "Custom-SecurityEvent": {
        "columns": [
          {"name": "TimeGenerated", "type": "datetime"},
          {"name": "EventID", "type": "int"},
          {"name": "EventLevel", "type": "int"},
          {"name": "EventRecordID", "type": "long"},
          {"name": "EventSourceName", "type": "string"},
          {"name": "Computer", "type": "string"},
          {"name": "Account", "type": "string"},
          {"name": "AccountType", "type": "string"},
          {"name": "Activity", "type": "string"},
          {"name": "ProcessName", "type": "string"},
          {"name": "ProcessID", "type": "int"},
          {"name": "SubjectUserName", "type": "string"},
          {"name": "SubjectDomainName", "type": "string"},
          {"name": "SubjectUserSid", "type": "string"},
          {"name": "TargetUserName", "type": "string"},
          {"name": "TargetDomainName", "type": "string"},
          {"name": "TargetUserSid", "type": "string"},
          {"name": "LogonType", "type": "int"},
          {"name": "LogonTypeName", "type": "string"},
          {"name": "AuthenticationPackageName", "type": "string"},
          {"name": "WorkstationName", "type": "string"},
          {"name": "IpAddress", "type": "string"},
          {"name": "IpPort", "type": "string"},
          {"name": "Status", "type": "string"},
          {"name": "SubStatus", "type": "string"},
          {"name": "FailureReason", "type": "string"}
        ]
      }
    },
    "destinations": {
      "logAnalytics": [
        {
          "workspaceResourceId": "/subscriptions/{subscription-id}/resourceGroups/{rg}/providers/Microsoft.OperationalInsights/workspaces/{workspace-name}",
          "name": "evtx-workspace"
        }
      ]
    },
    "dataFlows": [
      {
        "streams": ["Custom-SecurityEvent"],
        "destinations": ["evtx-workspace"],
        "transformKql": "source",
        "outputStream": "Microsoft-SecurityEvent"
      }
    ]
  }
}
```

### 3. 認証設定
Azure Functionsのマネージドアイデンティティを有効にし、以下の権限を付与：
- DCRに対する「Monitoring Metrics Publisher」ロール
- Log Analytics Workspaceに対する「Log Analytics Contributor」ロール

#### ローカル開発環境での認証方法

**方法1: サービスプリンシパル認証（推奨）**
```json
{
  "AZURE_CLIENT_ID": "your-service-principal-client-id",
  "AZURE_CLIENT_SECRET": "your-service-principal-client-secret", 
  "AZURE_TENANT_ID": "your-tenant-id"
}
```

**方法2: Azure CLI認証**
```bash
az login
```

**方法3: 環境変数による認証**
- `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_TENANT_ID` を設定

詳細な設定手順は [SERVICE_PRINCIPAL_SETUP.md](./SERVICE_PRINCIPAL_SETUP.md) を参照してください。

## ローカル開発環境設定

### 1. 仮想環境の作成
```bash
python -m venv .venv
.venv\\Scripts\\activate  # Windows
source .venv/bin/activate  # Linux/macOS
```

### 2. 依存関係のインストール
```bash
pip install -r requirements.txt
```

### 3. local.settings.json の設定
```json
{
  "IsEncrypted": false,
  "Values": {
    "AzureWebJobsStorage": "UseDevelopmentStorage=true",
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "d0e84d_STORAGE": "UseDevelopmentStorage=true",
    "DCE_ENDPOINT": "https://your-dce-endpoint.monitor.azure.com",
    "DCR_IMMUTABLE_ID": "your-dcr-immutable-id",
    "STREAM_NAME": "Custom-SecurityEvent"
  }
}
```

### 4. Azurite の起動（ローカルテスト用）
```bash
azurite --silent --location ./azurite --debug ./azurite/debug.log
```

## 使用方法

### 1. EVTXファイルのアップロード
指定されたBlobコンテナ（`mycontainer`）にEVTXファイルをアップロードします。

### 2. 自動処理
ファイルがアップロードされると、Azure Functionが自動的に起動し：
1. EVTXファイルを解析
2. SecurityEventテーブル形式のJSONに変換
3. Log Analytics Workspaceに送信

### 3. ログの確認
Azure Functionsのログから処理状況を確認できます：
```
Python blob trigger function processed blob Name: sample.evtx Blob Size: 1024 bytes
Successfully processed 150 events from sample.evtx
```

## トラブルシューティング

### よくある問題

1. **インポートエラー**
   - 仮想環境が正しく設定されているか確認
   - `pip install -r requirements.txt` を再実行

2. **認証エラー**
   - マネージドアイデンティティが有効になっているか確認
   - DCRとワークスペースへの適切な権限が付与されているか確認

3. **EVTXファイル処理エラー**
   - ファイルが正しいEVTX形式か確認
   - ファイルサイズが制限内か確認

4. **Log Analytics送信エラー**
   - DCE_ENDPOINTとDCR_IMMUTABLE_IDが正しく設定されているか確認
   - ネットワーク接続とファイアウォール設定を確認

### テスト実行
```bash
python test_function.py
```

## アーキテクチャ

```
[Blob Storage] → [Azure Functions] → [Log Analytics Workspace]
     ↓               ↓                      ↓
   .evtx files    Processing            SecurityEvent Table
                  - Parse EVTX
                  - Convert to JSON
                  - Batch send
```

## セキュリティ考慮事項

- マネージドアイデンティティを使用して安全な認証を実装
- 最小権限の原則に従ったRBACロール設定
- 機密データを含むログファイルの適切な処理

## パフォーマンス

- バッチ処理により効率的なデータ転送
- 一時ファイルの適切なクリーンアップ
- エラー時の適切なリトライ機能

## 制限事項

- EVTXファイルサイズの制限（Azure Functions実行時間制限による）
- 同時処理可能なファイル数の制限
- Log Analytics Workspaceのデータ取り込み制限
# EVTX to Log Analytics Workspace (LAWS) Azure Function

このAzure FunctionsアプリケーションはBlob Storageに追加されたEVTXファイルを自動的に処理し、Azure Monitor Log Ingest APIを使用してMicrosoft Sentinelの組み込み SecurityEvent テーブルに送信します。

## 重要な注意事項

- 本READMEおよび実装コードはAIツール（GitHub Copilot）を用いて生成・整備されています。
- 本コードは個人の検証目的で提供しており、企業・団体などの本番環境で利用する場合は利用者自身の責任で検証・運用してください。
- Descriptionやイベントログフィールドのマッピングには不足や誤りが含まれる可能性があります。必要に応じて内容を精査・補完してください。

## ✅ プロジェクト完了状況

**SecurityEventテーブル完全互換性を実現！**
- ✅ SecurityEvent (組み込み) テーブルへ直接インジェスト
- ✅ SecurityEventテーブルと同等のスキーマ構成（DCRのストリーム定義で実現）
- ✅ DCR (Data Collection Rule) 設定完了
- ✅ 完全なフィールドマッピング実装
- ✅ テストデータ送信成功確認

## 機能

- **Blob Trigger**: 指定されたBlobコンテナにEVTXファイルが追加されると自動実行
- **EVTX解析**: EVTXファイルをXMLとして解析し、SecurityEvent互換形式のJSONに変換
- **Log Analytics送信**: Azure Monitor Log Ingest APIを使用してSecurityEventテーブルに送信
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
- `AzureWebJobsStorage`: Azure Storage接続文字列（Blob Triggerおよび内部状態の保持に利用）
- `FUNCTIONS_WORKER_RUNTIME`: `python`

## Azure リソースの準備

`create-azure-resources.ps1` を使用すると、SecurityEvent テーブルへ直接送信するための Data Collection Endpoint (DCE) と Data Collection Rule (DCR) を一括で構成できます。手動で個別の `az` コマンドを実行する必要はありません。

### スクリプト概要
- DCE と DCR を作成または再利用し、両者を自動で関連付け
- `dcr-schema-securityevent.json` を基に SecurityEvent 互換の 90+ フィールド構成を適用
- DCR Immutable ID と DCE Endpoint を出力し、Azure Functions の環境変数設定をガイド
- 冪等性を考慮しており、再実行しても既存リソースを破壊しません

### 実行前の前提条件
- Azure CLI がインストールされており、`az login` 済み（必要に応じてサービスプリンシパル指定可）
- 指定するサブスクリプション、リソースグループ、Log Analytics Workspace が既に存在
- PowerShell (pwsh) でスクリプトを実行可能

### 実行例
```pwsh
pwsh ./create-azure-resources.ps1 `
  -SubscriptionId "00000000-0000-0000-0000-000000000000" `
  -ResourceGroup "rg-evtx" `
  -WorkspaceName "laws-evtx" `
  -Location "japaneast"
```

任意で以下のパラメーターを指定できます：
- `-DcrName` / `-DceName`: 既定以外の名前を使用したい場合
- `-DcrFilePath`: カスタム DCR JSON を利用したい場合
- `-ServicePrincipalAppId` `-ServicePrincipalSecret` `-ServicePrincipalTenantId`: サービスプリンシパルでのログインをスクリプト内で完結させる場合に指定

### スクリプト実行後
- コンソールに表示される `DCR Immutable ID` と `DCE Endpoint` を `local.settings.json` などの `DCR_IMMUTABLE_ID` / `DCE_ENDPOINT` として設定
- 出力メッセージに従い、必要なロール割り当て（Monitoring Metrics Publisher、Log Analytics Contributor）を付与
- Log Analytics で `SecurityEvent | take 5` などのクエリを実行して取り込み結果を確認

詳細な手順やロール設定のコマンドは `create-azure-resources.ps1` 内のコメントにも記載されています。

## 認証とロール設定

Azure Functions から Log Ingest API を実行するには、**サービスプリンシパル**または**マネージドアイデンティティ**に適切な Azure ロールを付与する必要があります。

### 必要なロール

1. **Monitoring Metrics Publisher** (DCR に対して)
   - Data Collection Rule へのデータ送信に必須
   - スコープ: 作成した DCR リソース

2. **Log Analytics Contributor** (Log Analytics Workspace に対して・オプション)
   - ワークスペースのテーブル操作やクエリ実行が必要な場合に付与
   - スコープ: Log Analytics Workspace リソース

### ローカル開発環境での認証

**方法1: サービスプリンシパル認証（推奨）**

1. サービスプリンシパルを作成:
   ```bash
   az ad sp create-for-rbac --name "evtx-function-sp" --role "Monitoring Metrics Publisher" --scopes "/subscriptions/{subscription-id}/resourceGroups/{rg}/providers/microsoft.insights/datacollectionrules/{dcr-name}"
   ```

2. 出力された `appId`, `password`, `tenant` を `local.settings.json` に設定:
   ```json
   {
     "Values": {
       "AZURE_CLIENT_ID": "your-service-principal-app-id",
       "AZURE_CLIENT_SECRET": "your-service-principal-password",
       "AZURE_TENANT_ID": "your-tenant-id",
       ...
     }
   }
   ```

**方法2: Azure CLI認証**
```bash
az login
```
- ローカル開発時は Azure CLI の認証情報を `DefaultAzureCredential` が自動的に利用
- ただし、CLI ユーザーにも同様のロール割り当てが必要

### Azure 環境（本番）での認証

**マネージドアイデンティティの使用（推奨）**

1. Azure Functions でシステム割り当てマネージドアイデンティティを有効化:
   ```bash
   az functionapp identity assign --name {function-app-name} --resource-group {rg}
   ```

2. マネージドアイデンティティに必要なロールを付与:
   ```bash
   # Monitoring Metrics Publisher ロールを DCR に付与
   az role assignment create \
     --assignee {managed-identity-principal-id} \
     --role "Monitoring Metrics Publisher" \
     --scope "/subscriptions/{subscription-id}/resourceGroups/{rg}/providers/microsoft.insights/datacollectionrules/{dcr-name}"
   ```

3. Azure Functions の環境変数には認証情報を設定不要（マネージドアイデンティティが自動的に使用される）

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

### 5. ローカルでの関数実行
```bash
func start
```

## Azure Functions へのデプロイ

### 前提条件
- Azure Functions アプリが作成済み（Python 3.9 以降、Linux または Windows）
- Azure CLI と Azure Functions Core Tools がインストール済み

### デプロイ手順

#### 1. Function App の作成（未作成の場合）
```bash
# ストレージアカウント作成
az storage account create \
  --name {storage-account-name} \
  --resource-group {rg} \
  --location {location} \
  --sku Standard_LRS

# Function App 作成 (Linux + Python 3.11)
az functionapp create \
  --name {function-app-name} \
  --resource-group {rg} \
  --storage-account {storage-account-name} \
  --runtime python \
  --runtime-version 3.11 \
  --os-type Linux \
  --functions-version 4
```

#### 2. マネージドアイデンティティの有効化と権限付与
```bash
# システム割り当てマネージドアイデンティティを有効化
az functionapp identity assign \
  --name {function-app-name} \
  --resource-group {rg}

# 出力された principalId をメモ
PRINCIPAL_ID=$(az functionapp identity show --name {function-app-name} --resource-group {rg} --query principalId -o tsv)

# DCR への Monitoring Metrics Publisher ロール付与
az role assignment create \
  --assignee $PRINCIPAL_ID \
  --role "Monitoring Metrics Publisher" \
  --scope "/subscriptions/{subscription-id}/resourceGroups/{rg}/providers/microsoft.insights/datacollectionrules/{dcr-name}"
```

#### 3. 環境変数の設定
```bash
az functionapp config appsettings set \
  --name {function-app-name} \
  --resource-group {rg} \
  --settings \
    DCE_ENDPOINT="https://your-dce-endpoint.monitor.azure.com" \
    DCR_IMMUTABLE_ID="dcr-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" \
    STREAM_NAME="Custom-SecurityEvent"
```

#### 4. アプリケーションのデプロイ
```bash
# プロジェクトルートから実行
func azure functionapp publish {function-app-name}
```

#### 5. デプロイ確認
```bash
# 関数一覧の確認
az functionapp function list --name {function-app-name} --resource-group {rg}

# ログストリーミングで動作確認
func azure functionapp logstream {function-app-name}
```

### デプロイ後の確認
1. Azure Portal で Function App のログを確認
2. Blob Storage の `mycontainer` に EVTX ファイルをアップロードしてトリガーをテスト
3. Log Analytics Workspace で `SecurityEvent` テーブルにデータが取り込まれているか確認:
   ```kql
   SecurityEvent
   | where TimeGenerated > ago(1h)
   | take 10
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
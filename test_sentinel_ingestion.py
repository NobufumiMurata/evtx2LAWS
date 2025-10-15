#!/usr/bin/env python3
"""
Microsoft Sentinel カスタムテーブル テストデータ送信スクリプト
SecurityEvents_CL テーブルへのサンプルデータ送信をテスト (SecurityEvent互換スキーマ対応)
"""

import os
import json
import logging
from datetime import datetime, timedelta
from azure.monitor.ingestion import LogsIngestionClient
from azure.identity import ClientSecretCredential
import random

# ログ設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def create_sample_security_events():
    """
    Sentinelテスト用のサンプルSecurityEventデータを生成
    SecurityEvent互換スキーマに準拠（90+フィールド対応）
    """
    # 現在時刻から過去24時間のランダムな時間を生成
    current_time = datetime.utcnow()
    
    sample_events = []
    
    # 1. ログオン成功イベント (EventID 4624) - SecurityEvent互換スキーマ対応版
    sample_events.append({
        "TimeGenerated": (current_time - timedelta(minutes=30)).isoformat() + "Z",
        "Computer": "WIN-SRV-001",
        "EventID": 4624,
        "EventSourceName": "Microsoft-Windows-Security-Auditing",
        "Activity": "4624 - An account was successfully logged on",
        "Type": "SecurityEvent",
        "SourceSystem": "Test Data Generator (SecurityEvent Compatible)",
        "Channel": "Security",
        "Task": 12544,
        "Level": 4,
        "EventLevelName": "Information",
        "Version": 0,
        "Opcode": 0,
        "Keywords": "0x8020000000000000",
        "ProcessId": 584,
        "ThreadId": 1234,
        "EventRecordId": 1001,
        "ProviderGuid": "{54849625-5478-4994-A5BA-3E3B0328C30D}",
        "ProcessName": "C:\\Windows\\System32\\winlogon.exe",
        "NewProcessName": "Unknown",
        "CommandLine": "Unknown",
        "ClientProcessId": 0,
        "Account": "CONTOSO\\john.doe",
        "AccountType": "User",
        "LogonType": 10,
        "LogonTypeName": "RemoteInteractive",
        "WorkstationName": "CLIENT-001",
        "IpAddress": "192.168.1.100",
        "SubjectUserSid": "S-1-5-21-1234567890-1234567890-1234567890-1001",
        "SubjectUserName": "john.doe",
        "SubjectDomainName": "CONTOSO",
        "SubjectLogonId": "0x12345",
        "ObjectServer": "Unknown",
        "ObjectType": "Unknown",
        "ObjectName": "Unknown",
        "HandleId": "0x0",
        "OldSd": "Unknown",
        "NewSd": "Unknown",
        "RuleId": "Unknown",
        "RuleName": "Unknown",
        "RuleAttr": "Unknown",
        "ProfileChanged": "Unknown",
        "TaskName": "Unknown",
        "TaskContent": "Unknown",
        "TargetName": "Unknown",
        "CredentialType": "Unknown",
        "CountOfCredentialsReturned": 0,
        "ReadOperation": "Unknown",
        "ReturnCode": "Unknown",
        "EventDataXml": "<EventData><Data Name='SubjectUserSid'>S-1-5-21-1234567890-1234567890-1234567890-1001</Data><Data Name='SubjectUserName'>john.doe</Data><Data Name='SubjectDomainName'>CONTOSO</Data><Data Name='LogonType'>10</Data><Data Name='WorkstationName'>CLIENT-001</Data><Data Name='IpAddress'>192.168.1.100</Data></EventData>",
        "DataSource": "Test Data Generator (SecurityEvent Compatible)",
        "ParsedTimestamp": current_time.isoformat() + "Z",
        "ParserVersion": "5.0.0-SecurityEvent-Schema-Compatible"
    })
    
    # 2. ログオン失敗イベント (EventID 4625) - SecurityEvent互換スキーマ対応版
    sample_events.append({
        "TimeGenerated": (current_time - timedelta(minutes=15)).isoformat() + "Z",
        "Computer": "WIN-SRV-001",
        "EventID": 4625,
        "EventSourceName": "Microsoft-Windows-Security-Auditing",
        "Activity": "4625 - An account failed to log on",
        "Type": "SecurityEvent",
        "SourceSystem": "Test Data Generator (SecurityEvent Compatible)",
        "Channel": "Security",
        "Task": 12544,
        "Level": 4,
        "EventLevelName": "Information",
        "Version": 0,
        "Opcode": 0,
        "Keywords": "0x8010000000000000",
        "ProcessId": 584,
        "ThreadId": 1235,
        "EventRecordId": 1002,
        "ProviderGuid": "{54849625-5478-4994-A5BA-3E3B0328C30D}",
        "ProcessName": "C:\\Windows\\System32\\lsass.exe",
        "NewProcessName": "Unknown",
        "CommandLine": "Unknown",
        "ClientProcessId": 0,
        "Account": "CONTOSO\\jane.smith",
        "AccountType": "User",
        "LogonType": 3,
        "LogonTypeName": "Network",
        "WorkstationName": "CLIENT-002",
        "IpAddress": "192.168.1.200",
        "SubjectUserSid": "S-1-0-0",
        "SubjectUserName": "-",
        "SubjectDomainName": "-",
        "SubjectLogonId": "0x0",
        "ObjectServer": "Unknown",
        "ObjectType": "Unknown",
        "ObjectName": "Unknown",
        "HandleId": "0x0",
        "OldSd": "Unknown",
        "NewSd": "Unknown",
        "RuleId": "Unknown",
        "RuleName": "Unknown",
        "RuleAttr": "Unknown",
        "ProfileChanged": "Unknown",
        "TaskName": "Unknown",
        "TaskContent": "Unknown",
        "TargetName": "Unknown",
        "CredentialType": "Unknown",
        "CountOfCredentialsReturned": 0,
        "ReadOperation": "Unknown",
        "ReturnCode": "0xC000006D",
        "EventDataXml": "<EventData><Data Name='SubjectUserSid'>S-1-0-0</Data><Data Name='SubjectUserName'>-</Data><Data Name='SubjectDomainName'>-</Data><Data Name='LogonType'>3</Data><Data Name='WorkstationName'>CLIENT-002</Data><Data Name='IpAddress'>192.168.1.200</Data><Data Name='ReturnCode'>0xC000006D</Data></EventData>",
        "DataSource": "Test Data Generator (SecurityEvent Compatible)",
        "ParsedTimestamp": current_time.isoformat() + "Z",
        "ParserVersion": "5.0.0-SecurityEvent-Schema-Compatible"
    })
    
    # 3. プロセス作成イベント (EventID 4688) - SecurityEvent互換スキーマ対応版
    sample_events.append({
        "TimeGenerated": (current_time - timedelta(minutes=5)).isoformat() + "Z",
        "Computer": "WIN-WS-001",
        "EventID": 4688,
        "EventSourceName": "Microsoft-Windows-Security-Auditing",
        "Activity": "4688 - A new process has been created",
        "Type": "SecurityEvent",
        "SourceSystem": "Test Data Generator (SecurityEvent Compatible)",
        "Channel": "Security",
        "Task": 13312,
        "Level": 4,
        "EventLevelName": "Information",
        "Version": 0,
        "Opcode": 0,
        "Keywords": "0x8020000000000000",
        "ProcessId": 584,
        "ThreadId": 1236,
        "EventRecordId": 1003,
        "ProviderGuid": "{54849625-5478-4994-A5BA-3E3B0328C30D}",
        "ProcessName": "C:\\Windows\\System32\\powershell.exe",
        "NewProcessName": "C:\\Windows\\System32\\cmd.exe",
        "CommandLine": "cmd.exe /c \"dir C:\\ && whoami\"",
        "ClientProcessId": 1234,
        "Account": "CONTOSO\\admin",
        "AccountType": "User",
        "LogonType": 0,
        "LogonTypeName": "Unknown",
        "WorkstationName": "WIN-WS-001",
        "IpAddress": "0.0.0.0",
        "SubjectUserSid": "S-1-5-21-1234567890-1234567890-1234567890-500",
        "SubjectUserName": "admin",
        "SubjectDomainName": "CONTOSO",
        "SubjectLogonId": "0x54321",
        "ObjectServer": "Unknown",
        "ObjectType": "Unknown",
        "ObjectName": "Unknown",
        "HandleId": "0x1A2B3C4D",
        "OldSd": "Unknown",
        "NewSd": "Unknown",
        "RuleId": "Unknown",
        "RuleName": "Unknown",
        "RuleAttr": "Unknown",
        "ProfileChanged": "Unknown",
        "TaskName": "Unknown",
        "TaskContent": "Unknown",
        "TargetName": "Unknown",
        "CredentialType": "Unknown",
        "CountOfCredentialsReturned": 0,
        "ReadOperation": "Unknown",
        "ReturnCode": "Unknown",
        "EventDataXml": "<EventData><Data Name='SubjectUserSid'>S-1-5-21-1234567890-1234567890-1234567890-500</Data><Data Name='SubjectUserName'>admin</Data><Data Name='SubjectDomainName'>CONTOSO</Data><Data Name='NewProcessName'>C:\\Windows\\System32\\cmd.exe</Data><Data Name='CommandLine'>cmd.exe /c \"dir C:\\ && whoami\"</Data><Data Name='ClientProcessId'>1234</Data></EventData>",
        "DataSource": "Test Data Generator (SecurityEvent Compatible)",
        "ParsedTimestamp": current_time.isoformat() + "Z",
        "ParserVersion": "5.0.0-SecurityEvent-Schema-Compatible"
    })
    
    # 4. ファイアウォール変更イベント (EventID 4946) - SecurityEvent互換スキーマ対応版
    sample_events.append({
        "TimeGenerated": (current_time - timedelta(minutes=60)).isoformat() + "Z",
        "Computer": "WIN-FW-001",
        "EventID": 4946,
        "EventSourceName": "Microsoft-Windows-Security-Auditing",
        "Activity": "4946 - A change has been made to Windows Firewall exception list",
        "Type": "SecurityEvent",
        "SourceSystem": "Test Data Generator (SecurityEvent Compatible)",
        "Channel": "Security",
        "Task": 13568,
        "Level": 4,
        "EventLevelName": "Information",
        "Version": 0,
        "Opcode": 0,
        "Keywords": "0x8020000000000000",
        "ProcessId": 4,
        "ThreadId": 1237,
        "EventRecordId": 1004,
        "ProviderGuid": "{54849625-5478-4994-A5BA-3E3B0328C30D}",
        "ProcessName": "System",
        "NewProcessName": "Unknown",
        "CommandLine": "Unknown",
        "ClientProcessId": 0,
        "Account": "NT AUTHORITY\\SYSTEM",
        "AccountType": "System",
        "LogonType": 0,
        "LogonTypeName": "Unknown",
        "WorkstationName": "Unknown",
        "IpAddress": "0.0.0.0",
        "SubjectUserSid": "S-1-5-18",
        "SubjectUserName": "SYSTEM",
        "SubjectDomainName": "NT AUTHORITY",
        "SubjectLogonId": "0x3E7",
        "ObjectServer": "Unknown",
        "ObjectType": "Unknown",
        "ObjectName": "Unknown",
        "HandleId": "0x0",
        "OldSd": "Unknown",
        "NewSd": "Unknown",
        "RuleId": "{12345678-1234-5678-9012-123456789012}",
        "RuleName": "Windows Remote Management (HTTP-In)",
        "RuleAttr": "Enable",
        "ProfileChanged": "Domain",
        "TaskName": "Unknown",
        "TaskContent": "Unknown",
        "TargetName": "Unknown",
        "CredentialType": "Unknown",
        "CountOfCredentialsReturned": 0,
        "ReadOperation": "Unknown",
        "ReturnCode": "Unknown",
        "EventDataXml": "<EventData><Data Name='SubjectUserSid'>S-1-5-18</Data><Data Name='SubjectUserName'>SYSTEM</Data><Data Name='SubjectDomainName'>NT AUTHORITY</Data><Data Name='RuleId'>{12345678-1234-5678-9012-123456789012}</Data><Data Name='RuleName'>Windows Remote Management (HTTP-In)</Data><Data Name='RuleAttr'>Enable</Data><Data Name='ProfileChanged'>Domain</Data></EventData>",
        "DataSource": "Test Data Generator (SecurityEvent Compatible)",
        "ParsedTimestamp": current_time.isoformat() + "Z",
        "ParserVersion": "5.0.0-SecurityEvent-Schema-Compatible"
    })
    
    # 5. 権限変更イベント (EventID 4670) - SecurityEvent互換スキーマ対応版
    sample_events.append({
        "TimeGenerated": (current_time - timedelta(minutes=45)).isoformat() + "Z",
        "Computer": "WIN-DC-001",
        "EventID": 4670,
        "EventSourceName": "Microsoft-Windows-Security-Auditing",
        "Activity": "4670 - Permissions on an object were changed",
        "Type": "SecurityEvent",
        "SourceSystem": "Test Data Generator (SecurityEvent Compatible)",
        "Channel": "Security",
        "Task": 13056,
        "Level": 4,
        "EventLevelName": "Information",
        "Version": 0,
        "Opcode": 0,
        "Keywords": "0x8020000000000000",
        "ProcessId": 584,
        "ThreadId": 1238,
        "EventRecordId": 1005,
        "ProviderGuid": "{54849625-5478-4994-A5BA-3E3B0328C30D}",
        "ProcessName": "C:\\Windows\\System32\\svchost.exe",
        "NewProcessName": "Unknown",
        "CommandLine": "Unknown",
        "ClientProcessId": 584,
        "Account": "CONTOSO\\administrator",
        "AccountType": "User",
        "LogonType": 0,
        "LogonTypeName": "Unknown",
        "WorkstationName": "Unknown",
        "IpAddress": "0.0.0.0",
        "SubjectUserSid": "S-1-5-21-1234567890-1234567890-1234567890-500",
        "SubjectUserName": "administrator",
        "SubjectDomainName": "CONTOSO",
        "SubjectLogonId": "0x98765",
        "ObjectServer": "Security",
        "ObjectType": "File",
        "ObjectName": "C:\\Important\\SecretDocument.txt",
        "HandleId": "0x1A2B",
        "OldSd": "D:(A;;0x1200a9;;;BU)(A;;FA;;;SY)",
        "NewSd": "D:(A;;FA;;;BA)(A;;0x1200a9;;;BU)(A;;FA;;;SY)",
        "RuleId": "Unknown",
        "RuleName": "Unknown",
        "RuleAttr": "Unknown",
        "ProfileChanged": "Unknown",
        "TaskName": "Unknown",
        "TaskContent": "Unknown",
        "TargetName": "Unknown",
        "CredentialType": "Unknown",
        "CountOfCredentialsReturned": 0,
        "ReadOperation": "Unknown",
        "ReturnCode": "Unknown",
        "EventDataXml": "<EventData><Data Name='SubjectUserSid'>S-1-5-21-1234567890-1234567890-1234567890-500</Data><Data Name='SubjectUserName'>administrator</Data><Data Name='SubjectDomainName'>CONTOSO</Data><Data Name='ObjectServer'>Security</Data><Data Name='ObjectType'>File</Data><Data Name='ObjectName'>C:\\Important\\SecretDocument.txt</Data><Data Name='HandleId'>0x1A2B</Data><Data Name='OldSd'>D:(A;;0x1200a9;;;BU)(A;;FA;;;SY)</Data><Data Name='NewSd'>D:(A;;FA;;;BA)(A;;0x1200a9;;;BU)(A;;FA;;;SY)</Data></EventData>",
        "DataSource": "Test Data Generator (SecurityEvent Compatible)",
        "ParsedTimestamp": current_time.isoformat() + "Z",
        "ParserVersion": "5.0.0-SecurityEvent-Schema-Compatible"
    })
    
    return sample_events

def send_test_data_to_sentinel():
    """
    テストデータをSentinel カスタムテーブルに送信
    """
    try:
        # 環境変数から設定を読み込み
        dce_endpoint = os.environ.get("DCE_ENDPOINT")
        dcr_immutable_id = os.environ.get("DCR_IMMUTABLE_ID")
        stream_name = "Custom-SecurityEvent"
        
        tenant_id = os.environ.get("AZURE_TENANT_ID")
        client_id = os.environ.get("AZURE_CLIENT_ID")
        client_secret = os.environ.get("AZURE_CLIENT_SECRET")
        
        # 設定チェック
        if not all([dce_endpoint, dcr_immutable_id, tenant_id, client_id, client_secret]):
            missing_vars = []
            if not dce_endpoint: missing_vars.append("DCE_ENDPOINT")
            if not dcr_immutable_id: missing_vars.append("DCR_IMMUTABLE_ID")
            if not tenant_id: missing_vars.append("AZURE_TENANT_ID")
            if not client_id: missing_vars.append("AZURE_CLIENT_ID")
            if not client_secret: missing_vars.append("AZURE_CLIENT_SECRET")
            
            logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
            return False
        
        logger.info("=== Sentinel カスタムテーブル テストデータ送信 ===")
        logger.info(f"DCE Endpoint: {dce_endpoint}")
        logger.info(f"DCR Immutable ID: {dcr_immutable_id}")
        logger.info(f"Stream Name: {stream_name}")
        
        # 認証クライアントを作成
        credential = ClientSecretCredential(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret
        )
        
        # Log Ingest クライアントを作成
        client = LogsIngestionClient(endpoint=dce_endpoint, credential=credential)
        
        # サンプルデータを生成
        test_events = create_sample_security_events()
        logger.info(f"Generated {len(test_events)} test security events")
        
        # データをJSON形式で表示（デバッグ用）
        logger.info("Sample data preview:")
        for i, event in enumerate(test_events[:2]):  # 最初の2件のみ表示
            logger.info(f"Event {i+1}: EventID={event['EventID']}, Computer={event['Computer']}, Account={event['Account']}")
        
        # データを送信
        logger.info("Sending test data to Sentinel...")
        response = client.upload(
            rule_id=dcr_immutable_id,
            stream_name=stream_name,
            logs=test_events
        )
        
        logger.info("✅ Test data sent successfully!")
        logger.info(f"Response: {response}")
        
        # 送信完了後の確認メッセージ
        logger.info("\n=== 次のステップ ===")
        logger.info("1. Log Analytics Workspace でデータを確認:")
        logger.info("   SecurityEvents_CL | take 10")
        logger.info("2. データが表示されるまで5-10分待機してください")
        logger.info("3. Sentinel でカスタムテーブルを確認:")
        logger.info("   SecurityEvents_CL | where TimeGenerated > ago(1h)")
        
        return True
        
    except Exception as e:
        logger.error(f"Error sending test data: {str(e)}")
        logger.error(f"Error type: {type(e).__name__}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        return False

def main():
    """
    メイン実行関数
    """
    logger.info("Starting Sentinel custom table test data ingestion...")
    
    # local.settings.jsonから環境変数を読み込み（存在する場合）
    try:
        if os.path.exists("local.settings.json"):
            with open("local.settings.json", "r") as f:
                settings = json.load(f)
                for key, value in settings.get("Values", {}).items():
                    if key not in os.environ:
                        os.environ[key] = value
                logger.info("Loaded settings from local.settings.json")
    except Exception as e:
        logger.warning(f"Could not load local.settings.json: {e}")
    
    # テストデータを送信
    success = send_test_data_to_sentinel()
    
    if success:
        logger.info("✅ Test completed successfully!")
        return 0
    else:
        logger.error("❌ Test failed!")
        return 1

if __name__ == "__main__":
    exit(main())

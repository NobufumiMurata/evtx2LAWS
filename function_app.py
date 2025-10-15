import azure.functions as func
import logging
from datetime import datetime, timezone
import json
import os
import tempfile
import xml.etree.ElementTree as ET
from Evtx.Evtx import Evtx
from Evtx.Views import evtx_file_xml_view
from azure.monitor.ingestion import LogsIngestionClient
from azure.identity import DefaultAzureCredential, ClientSecretCredential, ChainedTokenCredential

# Azure Functions アプリケーション
app = func.FunctionApp()

@app.blob_trigger(arg_name="myblob", path="mycontainer", 
                 connection="AzureWebJobsStorage") 
def blob_trigger(myblob: func.InputStream) -> None:
    """
    Blob Storage トリガー: EVTX ファイルを検出・処理・Log Analytics に送信
    """
    logging.info("=== BLOB TRIGGER ACTIVATED ===")
    logging.info(f"Blob Name: {myblob.name}")
    logging.info(f"Blob Size: {myblob.length} bytes")
    logging.info(f"Blob URI: {myblob.uri}")
    
    # デバッグモードの場合、追加情報を出力
    debug_mode = os.environ.get("DEBUG_MODE", "false").lower() == "true"
    if debug_mode:
        logging.info(f"Debug Mode: Enabled")
        logging.info(f"Environment Variables:")
        logging.info(f"  DCE_ENDPOINT: {os.environ.get('DCE_ENDPOINT', 'NOT SET')}")
        logging.info(f"  DCR_IMMUTABLE_ID: {os.environ.get('DCR_IMMUTABLE_ID', 'NOT SET')}")
        logging.info(f"  AZURE_CLIENT_ID: {'SET' if os.environ.get('AZURE_CLIENT_ID') else 'NOT SET'}")
    
    # EVTX ファイルかどうかを確認
    if not myblob.name.lower().endswith('.evtx'):
        logging.info(f"Not an EVTX file (extension: {os.path.splitext(myblob.name)[1]}), skipping...")
        return
    
    logging.info(f"Processing EVTX file: {myblob.name}")
    
    try:
        # ファイルデータを読み込み
        blob_data = myblob.read()
        
        # 一時ファイルに保存
        with tempfile.NamedTemporaryFile(suffix='.evtx', delete=False) as tmp_file:
            tmp_file.write(blob_data)
            tmp_file_path = tmp_file.name
        
        # EVTXファイルを解析
        events = parse_evtx_file(tmp_file_path)
        
        # 一時ファイルを削除
        os.unlink(tmp_file_path)
        
        if events:
            # Log Analytics に送信
            dce_endpoint = os.environ.get("DCE_ENDPOINT")
            dcr_immutable_id = os.environ.get("DCR_IMMUTABLE_ID")
            stream_name = "Custom-SecurityEvent"
            
            result = send_to_log_analytics(events, dce_endpoint, dcr_immutable_id, stream_name)
            logging.info(f"✅ SUCCESS: Processed {len(events)} events from {myblob.name}")
            logging.info(f"Log Analytics response: {result}")
        else:
            logging.warning(f"⚠️ WARNING: No events extracted from {myblob.name}")
            
    except Exception as e:
        logging.error(f"❌ ERROR: Failed to process blob {myblob.name}")
        logging.error(f"Error details: {str(e)}")
        logging.error(f"Error type: {type(e).__name__}")
        if debug_mode:
            import traceback
            logging.error(f"Full traceback: {traceback.format_exc()}")
        raise

def parse_evtx_file(evtx_file_path):
    """
    EVTXファイルを解析してイベントのリストを返す
    """
    events = []
    
    try:
        with Evtx(evtx_file_path) as evtx_file:
            for xml, record in evtx_file_xml_view(evtx_file.get_file_header()):
                try:
                    # XMLデータを解析してイベントデータを抽出
                    event_data = parse_event_xml(xml)
                    if event_data:
                        events.append(event_data)
                        
                except Exception as e:
                    logging.warning(f"Error parsing individual event record: {str(e)}")
                    continue
                    
    except Exception as e:
        logging.error(f"Error opening EVTX file: {str(e)}")
        raise
    
    return events

def get_event_level_name(level):
    """イベントレベルの数値を名前に変換"""
    level_names = {
        0: 'LogAlways',
        1: 'Critical',
        2: 'Error',
        3: 'Warning',
        4: 'Information',
        5: 'Verbose'
    }
    return level_names.get(level, 'Information')

def get_logon_type_name(logon_type):
    """ログオンタイプの数値を名前に変換"""
    logon_type_names = {
        0: 'Unknown',
        2: 'Interactive',
        3: 'Network',
        4: 'Batch',
        5: 'Service',
        7: 'Unlock',
        8: 'NetworkCleartext',
        9: 'NewCredentials',
        10: 'RemoteInteractive',
        11: 'CachedInteractive'
    }
    return logon_type_names.get(logon_type, 'Unknown')

def get_event_description(event_id):
    """EventIDに基づく説明を生成（実データで検出されたイベント優先対応）"""
    descriptions = {
        # 実データで検出されたEventID（優先）
        '4946': 'A change has been made to Windows Firewall exception list',
        '4948': 'A change has been made to Windows Firewall exception list',
        '4957': 'Windows Firewall did not apply the following rule',
        '4670': 'Permissions on an object were changed',
        '4702': 'A scheduled task was updated',
        '5379': 'Credential Manager credentials were read',
        
        # 一般的なセキュリティイベント
        '4624': 'An account was successfully logged on',
        '4625': 'An account failed to log on',
        '4634': 'An account was logged off',
        '4647': 'User initiated logoff',
        '4648': 'A logon was attempted using explicit credentials',
        '4662': 'An operation was performed on an object',
        '4672': 'Special privileges assigned to new logon',
        '4673': 'A privileged service was called',
        '4688': 'A new process has been created',
        '4689': 'A process has exited',
        '4698': 'A scheduled task was created',
        '4699': 'A scheduled task was deleted',
        '4700': 'A scheduled task was enabled',
        '4701': 'A scheduled task was disabled',
        '4720': 'A user account was created',
        '4722': 'A user account was enabled',
        '4723': 'An attempt was made to change an account password',
        '4724': 'An attempt was made to reset an account password',
        '4725': 'A user account was disabled',
        '4726': 'A user account was deleted',
        '4727': 'A security-enabled global group was created',
        '4728': 'A member was added to a security-enabled global group',
        '4729': 'A member was removed from a security-enabled global group',
        '4730': 'A security-enabled global group was deleted',
        '4731': 'A security-enabled local group was created',
        '4732': 'A member was added to a security-enabled local group',
        '4733': 'A member was removed from a security-enabled local group',
        '4734': 'A security-enabled local group was deleted',
        '4735': 'A security-enabled local group was changed',
        '4738': 'A user account was changed',
        '4740': 'A user account was locked out',
        '4767': 'A user account was unlocked',
        '4768': 'A Kerberos authentication ticket (TGT) was requested',
        '4769': 'A Kerberos service ticket was requested',
        '4770': 'A Kerberos service ticket was renewed',
        '4771': 'Kerberos pre-authentication failed',
        '4776': 'The computer attempted to validate the credentials for an account',
        '4778': 'A session was reconnected to a Window Station',
        '4779': 'A session was disconnected from a Window Station',
        '4781': 'The name of an account was changed',
        '4798': 'A user\'s local group membership was enumerated',
        '4799': 'A security-enabled local group membership was enumerated',
        '5156': 'The Windows Filtering Platform has allowed a connection',
        '5157': 'The Windows Filtering Platform has blocked a connection'
    }
    return descriptions.get(event_id, f'Event ID {event_id} occurred')

def parse_event_xml(xml_string):
    """
    実際のEVTXファイル分析結果に基づく最適化されたイベントXML解析
    実データで検出された42フィールドに対応
    """
    try:
        import xml.etree.ElementTree as ET
        from datetime import datetime
        
        # XMLを解析
        root = ET.fromstring(xml_string)
        
        # 名前空間を定義
        ns = {'Event': 'http://schemas.microsoft.com/win/2004/08/events/event'}
        
        # システム情報を取得
        system = root.find('.//Event:System', ns)
        event_data_elem = root.find('.//Event:EventData', ns)
        
        if system is None:
            return None
        
        # 基本的なイベント情報を抽出
        event_id = system.find('Event:EventID', ns).text if system.find('Event:EventID', ns) is not None else None
        time_created = system.find('Event:TimeCreated', ns)
        system_time = time_created.get('SystemTime') if time_created is not None else datetime.utcnow().isoformat() + 'Z'
        computer = system.find('Event:Computer', ns).text if system.find('Event:Computer', ns) is not None else 'Unknown'
        level = system.find('Event:Level', ns).text if system.find('Event:Level', ns) is not None else '4'
        
        # プロバイダー情報を取得
        provider = system.find('Event:Provider', ns)
        event_source_name = provider.get('Name') if provider is not None else 'Unknown'
        provider_guid = provider.get('Guid') if provider is not None else '{00000000-0000-0000-0000-000000000000}'
        
        # Execution情報を取得
        execution = system.find('Event:Execution', ns)
        process_id = execution.get('ProcessID') if execution is not None else '0'
        thread_id = execution.get('ThreadID') if execution is not None else '0'
        
        # その他システム情報
        channel = system.find('Event:Channel', ns).text if system.find('Event:Channel', ns) is not None else 'Security'
        task = system.find('Event:Task', ns).text if system.find('Event:Task', ns) is not None else '0'
        opcode = system.find('Event:Opcode', ns).text if system.find('Event:Opcode', ns) is not None else '0'
        keywords = system.find('Event:Keywords', ns).text if system.find('Event:Keywords', ns) is not None else '0x0'
        version = system.find('Event:Version', ns).text if system.find('Event:Version', ns) is not None else '0'
        event_record_id = system.find('Event:EventRecordID', ns).text if system.find('Event:EventRecordID', ns) is not None else '0'
        
        # SecurityEvent互換の完全なデータ構造（90+フィールド）
        securityevent_compatible_data = {
            # === 基本フィールド ===
            'TimeGenerated': system_time,
            'Computer': computer,
            'EventID': int(event_id) if event_id and event_id.isdigit() else 0,
            'Level': level if level else '4',
            'LevelDisplayName': get_event_level_name(int(level) if level.isdigit() else 4),
            'EventLevelName': get_event_level_name(int(level) if level.isdigit() else 4),
            'EventSourceName': event_source_name,
            'Task': int(task) if task.isdigit() else 0,
            'TaskDisplayName': f'Task {task}' if task else 'Unknown Task',
            'Opcode': opcode if opcode else '0',
            'OpcodeDisplayName': f'Opcode {opcode}' if opcode else 'Info',
            'Keywords': keywords,
            'KeywordDisplayNames': 'Audit Success' if '0x8020000000000000' in keywords else 'Unknown',
            'Channel': channel,
            'Provider': event_source_name,
            'Version': int(version) if version.isdigit() else 0,
            'ProcessId': int(process_id) if process_id.isdigit() else 0,
            'ThreadId': int(thread_id) if thread_id.isdigit() else 0,
            
            # === プロセス関連 ===
            'ProcessName': '',  # 後で更新
            'NewProcessId': '',  # 後で更新
            'NewProcessName': '',  # 後で更新
            'ParentProcessName': '',  # 後で更新
            'CommandLine': '',  # 後で更新
            'TokenElevationType': '',
            'MandatoryLabel': '',
            
            # === アカウント・認証関連 ===
            'Account': '',  # 後で更新
            'AccountType': 'User',
            'AccountName': '',  # 後で更新
            'AccountDomain': '',  # 後で更新
            'LogonType': 0,
            'LogonTypeName': 'Unknown',
            'LogonProcessName': '',  # 後で更新
            'AuthenticationPackageName': '',  # 後で更新
            'WorkstationName': '',  # 後で更新
            'LogonGuid': '{00000000-0000-0000-0000-000000000000}',
            
            # === Target情報 ===
            'TargetUserSid': 'S-1-0-0',
            'TargetUserName': '',
            'TargetDomainName': '',
            'TargetLogonId': '0x0',
            'TargetLogonGuid': '{00000000-0000-0000-0000-000000000000}',
            'TargetServerName': '',
            'TargetInfo': '',
            'TargetAccount': '',
            
            # === Subject情報 ===
            'SubjectUserSid': 'S-1-0-0',
            'SubjectUserName': '',
            'SubjectDomainName': '',
            'SubjectLogonId': '0x0',
            'SubjectAccount': '',
            
            # === オブジェクト・セキュリティ関連 ===
            'ObjectServer': '',
            'ObjectType': '',
            'ObjectName': '',
            'HandleId': '0x0',
            'AccessMask': '0x0',
            'PrivilegeList': '',
            'Properties': '',
            'AccessList': '',
            'AccessReason': '',
            'ResourceAttributes': '',
            
            # === ネットワーク関連 ===
            'IpAddress': '',
            'IpPort': '',
            'SourceNetworkAddress': '',
            'SourcePort': '',
            'ClientAddress': '',
            'ClientName': '',
            
            # === ステータス・エラー情報 ===
            'Status': '',
            'SubStatus': '',
            'FailureReason': '',
            'ErrorCode': '',
            
            # === 認証プロトコル関連 ===
            'TransmittedServices': '',
            'LmPackageName': '',
            'KeyLength': 0,
            'PackageName': '',
            
            # === 証明書関連 ===
            'CertIssuerName': '',
            'CertSerialNumber': '',
            'CertThumbprint': '',
            
            # === サービス関連 ===
            'ServiceName': '',
            'ServiceFileName': '',
            
            # === セッション・グループ関連 ===
            'SessionName': '',
            'GroupMembership': '',
            'RelativeTargetName': '',
            
            # === セキュリティ属性 ===
            'RestrictedAdminMode': '',
            'VirtualAccount': '',
            'ElevatedToken': '',
            'ImpersonationLevel': '',
            
            # === 値変更関連 ===
            'NewValue': '',
            'OldValue': '',
            
            # === メタデータ ===
            'EventRecordId': int(event_record_id) if event_record_id.isdigit() else 0,
            'ActivityId': '{00000000-0000-0000-0000-000000000000}',
            'EventData': xml_string,
            'SourceSystem': 'Azure Functions EVTX Parser (SecurityEvent Compatible)',
            'Activity': f'{event_id} - {get_event_description(event_id)}' if event_id else 'Unknown Activity',
            'Type': 'SecurityEvent',
            'ManagementGroupName': 'AOI-Unknown',
            'SourceComputerId': '{00000000-0000-0000-0000-000000000000}'
        }
        
        # EventDataから実データに基づく詳細情報を抽出
        if event_data_elem is not None:
            data_elements = event_data_elem.findall('Event:Data', ns)
            
            for data in data_elements:
                name = data.get('Name')
                value = data.text if data.text else ''
                
                if not name:
                    continue
                
                # SecurityEvent互換のフィールドマッピング（完全版）
                field_mapping = {
                    # === アカウント・認証関連 ===
                    'SubjectUserSid': 'SubjectUserSid',
                    'SubjectUserName': 'SubjectUserName', 
                    'SubjectDomainName': 'SubjectDomainName',
                    'SubjectLogonId': 'SubjectLogonId',
                    'TargetUserSid': 'TargetUserSid',
                    'TargetUserName': 'TargetUserName',
                    'TargetDomainName': 'TargetDomainName',
                    'TargetLogonId': 'TargetLogonId',
                    'TargetLogonGuid': 'TargetLogonGuid',
                    'TargetServerName': 'TargetServerName',
                    'TargetInfo': 'TargetInfo',
                    'LogonType': 'LogonType',
                    'LogonProcessName': 'LogonProcessName',
                    'AuthenticationPackageName': 'AuthenticationPackageName',
                    'WorkstationName': 'WorkstationName',
                    'LogonGuid': 'LogonGuid',
                    'IpAddress': 'IpAddress',
                    'ClientIPAddress': 'IpAddress',  # 別名マッピング
                    'ClientAddress': 'ClientAddress',
                    'ClientName': 'ClientName',
                    'IpPort': 'IpPort',
                    'SourceNetworkAddress': 'SourceNetworkAddress',
                    'SourcePort': 'SourcePort',
                    
                    # === プロセス関連 ===
                    'ProcessName': 'ProcessName',
                    'NewProcessName': 'NewProcessName',
                    'NewProcessId': 'NewProcessId',
                    'ParentProcessName': 'ParentProcessName',
                    'CommandLine': 'CommandLine',
                    'TokenElevationType': 'TokenElevationType',
                    'MandatoryLabel': 'MandatoryLabel',
                    
                    # === オブジェクト・リソース関連 ===
                    'ObjectServer': 'ObjectServer',
                    'ObjectType': 'ObjectType', 
                    'ObjectName': 'ObjectName',
                    'HandleId': 'HandleId',
                    'AccessMask': 'AccessMask',
                    'PrivilegeList': 'PrivilegeList',
                    'Properties': 'Properties',
                    'AccessList': 'AccessList',
                    'AccessReason': 'AccessReason',
                    'ResourceAttributes': 'ResourceAttributes',
                    
                    # === ステータス・エラー関連 ===
                    'Status': 'Status',
                    'SubStatus': 'SubStatus',
                    'FailureReason': 'FailureReason',
                    'ErrorCode': 'ErrorCode',
                    'ReturnCode': 'ErrorCode',  # 別名マッピング
                    
                    # === 認証プロトコル関連 ===
                    'TransmittedServices': 'TransmittedServices',
                    'LmPackageName': 'LmPackageName',
                    'KeyLength': 'KeyLength',
                    'PackageName': 'PackageName',
                    
                    # === 証明書関連 ===
                    'CertIssuerName': 'CertIssuerName',
                    'CertSerialNumber': 'CertSerialNumber',
                    'CertThumbprint': 'CertThumbprint',
                    
                    # === サービス関連 ===
                    'ServiceName': 'ServiceName',
                    'ServiceFileName': 'ServiceFileName',
                    
                    # === セッション・グループ関連 ===
                    'SessionName': 'SessionName',
                    'GroupMembership': 'GroupMembership',
                    'RelativeTargetName': 'RelativeTargetName',
                    
                    # === セキュリティ属性 ===
                    'RestrictedAdminMode': 'RestrictedAdminMode',
                    'VirtualAccount': 'VirtualAccount',
                    'ElevatedToken': 'ElevatedToken',
                    'ImpersonationLevel': 'ImpersonationLevel',
                    
                    # === 値変更関連 ===
                    'NewValue': 'NewValue',
                    'OldValue': 'OldValue'
                }
                
                # マッピングされたフィールドに値を設定
                if name in field_mapping:
                    target_field = field_mapping[name]
                    if target_field in securityevent_compatible_data:
                        clean_value = value.strip() if value else ''
                        if target_field in ['LogonType', 'KeyLength']:
                            try:
                                securityevent_compatible_data[target_field] = int(clean_value) if clean_value.isdigit() else 0
                            except ValueError:
                                securityevent_compatible_data[target_field] = 0
                        else:
                            securityevent_compatible_data[target_field] = clean_value
        
        # アカウント情報の統合処理
        subject_domain = securityevent_compatible_data.get('SubjectDomainName', '')
        subject_user = securityevent_compatible_data.get('SubjectUserName', '')
        target_domain = securityevent_compatible_data.get('TargetDomainName', '')
        target_user = securityevent_compatible_data.get('TargetUserName', '')
        
        # SubjectAccount とメインのAccountフィールドの設定
        if subject_domain and subject_user:
            securityevent_compatible_data['SubjectAccount'] = f"{subject_domain}\\{subject_user}"
            securityevent_compatible_data['Account'] = f"{subject_domain}\\{subject_user}"
            securityevent_compatible_data['AccountName'] = subject_user
            securityevent_compatible_data['AccountDomain'] = subject_domain
            
            # AccountTypeの推定
            if subject_user.endswith('$'):
                securityevent_compatible_data['AccountType'] = 'Machine'
            elif subject_user.lower() in ['system', 'local service', 'network service']:
                securityevent_compatible_data['AccountType'] = 'System'
            else:
                securityevent_compatible_data['AccountType'] = 'User'
        
        # TargetAccount の生成
        if target_domain and target_user:
            securityevent_compatible_data['TargetAccount'] = f"{target_domain}\\{target_user}"
            # Subject情報がない場合は、Target情報をメインのAccountフィールドに使用
            if not securityevent_compatible_data['Account']:
                securityevent_compatible_data['Account'] = f"{target_domain}\\{target_user}"
                securityevent_compatible_data['AccountName'] = target_user
                securityevent_compatible_data['AccountDomain'] = target_domain
        
        # LogonTypeNameの設定
        logon_type = securityevent_compatible_data.get('LogonType', 0)
        if isinstance(logon_type, int) and logon_type > 0:
            securityevent_compatible_data['LogonTypeName'] = get_logon_type_name(logon_type)
        
        return securityevent_compatible_data
        
    except Exception as e:
        print(f"Error parsing event XML (optimized): {str(e)}")
        return None

def send_to_log_analytics(events, dce_endpoint, dcr_immutable_id, stream_name):
    """
    Log Analytics Workspaceにイベントデータを送信
    """
    try:
        # 認証チェーンを設定（Service Principal優先）
        tenant_id = os.environ.get("AZURE_TENANT_ID")
        client_id = os.environ.get("AZURE_CLIENT_ID")
        client_secret = os.environ.get("AZURE_CLIENT_SECRET")
        
        if tenant_id and client_id and client_secret:
            service_principal_credential = ClientSecretCredential(
                tenant_id=tenant_id,
                client_id=client_id,
                client_secret=client_secret
            )
            credential = ChainedTokenCredential(
                service_principal_credential,
                DefaultAzureCredential()
            )
            logging.info("Using Service Principal authentication with fallback to DefaultAzureCredential")
        else:
            credential = DefaultAzureCredential()
            logging.info("Using DefaultAzureCredential authentication")
        
        # Log Ingest クライアントを作成
        client = LogsIngestionClient(endpoint=dce_endpoint, credential=credential)
        
        # データを送信
        logging.info(f"Sending {len(events)} events to Log Analytics")
        logging.info(f"DCE Endpoint: {dce_endpoint}")
        logging.info(f"DCR Immutable ID: {dcr_immutable_id}")
        logging.info(f"Stream Name: {stream_name}")
        
        response = client.upload(
            rule_id=dcr_immutable_id,
            stream_name=stream_name,
            logs=events
        )
        
        logging.info(f"Successfully sent {len(events)} events to Log Analytics")
        return response
        
    except Exception as e:
        logging.error(f"Error sending data to Log Analytics: {str(e)}")
        raise
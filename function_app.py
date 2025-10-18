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

CONFIG_DIR = os.path.join(os.path.dirname(__file__), 'config')
EVENT_DESCRIPTION_FILE = os.path.join(CONFIG_DIR, 'event_descriptions.json')

try:
    with open(EVENT_DESCRIPTION_FILE, 'r', encoding='utf-8') as desc_file:
        EVENT_DESCRIPTIONS = json.load(desc_file)
except FileNotFoundError:
    logging.warning("event_descriptions.json not found; defaulting to empty descriptions map")
    EVENT_DESCRIPTIONS = {}
except json.JSONDecodeError:
    logging.warning("event_descriptions.json is not valid JSON; defaulting to empty descriptions map")
    EVENT_DESCRIPTIONS = {}

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
    if level is None:
        return ''
    return level_names.get(level, '')

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
    if logon_type is None:
        return ''
    return logon_type_names.get(logon_type, '')

def get_event_description(event_id):
    """EventIDに基づく説明を取得"""
    if not event_id:
        return ''
    event_id_str = str(event_id)
    description = EVENT_DESCRIPTIONS.get(event_id_str)
    if description:
        return description
    return f'Event ID {event_id_str} occurred'

def parse_event_xml(xml_string):
    """
    実際のEVTXファイル分析結果に基づく最適化されたイベントXML解析
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
        
        def text_or_blank(element):
            if element is None or element.text is None:
                return ''
            return element.text.strip()

        # 基本的なイベント情報を抽出
        event_id_text = text_or_blank(system.find('Event:EventID', ns))
        event_id_value = int(event_id_text) if event_id_text.isdigit() else None
        time_created = system.find('Event:TimeCreated', ns)
        system_time = time_created.get('SystemTime') if time_created is not None else datetime.utcnow().isoformat() + 'Z'
        computer = text_or_blank(system.find('Event:Computer', ns))
        level_text = text_or_blank(system.find('Event:Level', ns))
        level_value = int(level_text) if level_text.isdigit() else None

        # プロバイダー情報を取得
        provider = system.find('Event:Provider', ns)
        provider_name = provider.get('Name') if provider is not None else ''
        event_source_name = provider_name.strip() if provider_name else ''

        # Execution情報を取得
        execution = system.find('Event:Execution', ns)
        process_id_attr = execution.get('ProcessID') if execution is not None else None
        thread_id_attr = execution.get('ThreadID') if execution is not None else None
        process_id_text = process_id_attr.strip() if process_id_attr else ''
        thread_id_text = thread_id_attr.strip() if thread_id_attr else ''
        thread_id_value = int(thread_id_text) if thread_id_text.isdigit() else None

        # その他システム情報
        channel = text_or_blank(system.find('Event:Channel', ns))
        task_text = text_or_blank(system.find('Event:Task', ns))
        task_value = int(task_text) if task_text.isdigit() else None
        opcode = text_or_blank(system.find('Event:Opcode', ns))
        keywords = text_or_blank(system.find('Event:Keywords', ns))
        version_text = text_or_blank(system.find('Event:Version', ns))
        version_value = int(version_text) if version_text.isdigit() else None
        event_record_id_text = text_or_blank(system.find('Event:EventRecordID', ns))
        correlation = system.find('Event:Correlation', ns)
        
        # SecurityEvent互換の完全なデータ構造（90+フィールド）
        securityevent_compatible_data = {
            # === 基本フィールド ===
            'TimeGenerated': system_time,
            'Computer': computer,
            'EventID': event_id_value,
            'Level': level_value,
            'LevelDisplayName': get_event_level_name(level_value),
            'EventLevelName': get_event_level_name(level_value),
            'EventSourceName': event_source_name,
            'Task': task_value,
            'TaskDisplayName': '',
            'Opcode': opcode,
            'OpcodeDisplayName': '',
            'Keywords': keywords,
            'KeywordDisplayNames': '',
            'Channel': channel,
            'Provider': event_source_name,
            'Version': version_value,
            'ProcessId': process_id_text,
            'ThreadId': thread_id_value,
            
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
            'AccountType': '',
            'AccountName': '',  # 後で更新
            'AccountDomain': '',  # 後で更新
            'LogonType': None,
            'LogonTypeName': '',
            'LogonProcessName': '',  # 後で更新
            'AuthenticationPackageName': '',  # 後で更新
            'WorkstationName': '',  # 後で更新
            'LogonGuid': '',
            
            # === Target情報 ===
            'TargetUserSid': '',
            'TargetUserName': '',
            'TargetDomainName': '',
            'TargetLogonId': '',
            'TargetLogonGuid': '',
            'TargetServerName': '',
            'TargetInfo': '',
            'TargetAccount': '',
            
            # === Subject情報 ===
            'SubjectUserSid': '',
            'SubjectUserName': '',
            'SubjectDomainName': '',
            'SubjectLogonId': '',
            'SubjectAccount': '',
            
            # === オブジェクト・セキュリティ関連 ===
            'ObjectServer': '',
            'ObjectType': '',
            'ObjectName': '',
            'HandleId': '',
            'AccessMask': '',
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
            'ErrorCode': None,
            
            # === 認証プロトコル関連 ===
            'TransmittedServices': '',
            'LmPackageName': '',
            'KeyLength': None,
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
            'EventRecordId': event_record_id_text,
            'ActivityId': '',
            'EventData': xml_string,
            'SourceSystem': 'Azure Functions EVTX Parser (SecurityEvent Compatible)',
            'Activity': f'{event_id_text} - {get_event_description(event_id_text)}' if event_id_text else '',
            'Type': 'SecurityEvent',
            'ManagementGroupName': '',
            'SourceComputerId': ''
        }

        if task_text:
            securityevent_compatible_data['TaskDisplayName'] = f'Task {task_text}'
        if opcode:
            securityevent_compatible_data['OpcodeDisplayName'] = f'Opcode {opcode}'
        if keywords and '0x8020000000000000' in keywords:
            securityevent_compatible_data['KeywordDisplayNames'] = 'Audit Success'
        if correlation is not None:
            activity_id = correlation.get('ActivityID', '')
            if activity_id:
                securityevent_compatible_data['ActivityId'] = activity_id.strip()
        
        # EventDataから実データに基づく詳細情報を抽出
        if event_data_elem is not None:
            data_elements = event_data_elem.findall('Event:Data', ns)
            
            for data in data_elements:
                name = data.get('Name')
                value = data.text.strip() if data.text else ''
                
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
                        if target_field in ['LogonType', 'KeyLength', 'ErrorCode']:
                            if clean_value:
                                try:
                                    securityevent_compatible_data[target_field] = int(clean_value, 0)
                                except ValueError:
                                    securityevent_compatible_data[target_field] = None
                            else:
                                securityevent_compatible_data[target_field] = None
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
        logon_type = securityevent_compatible_data.get('LogonType')
        if isinstance(logon_type, int):
            securityevent_compatible_data['LogonTypeName'] = get_logon_type_name(logon_type)
        else:
            securityevent_compatible_data['LogonTypeName'] = ''

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
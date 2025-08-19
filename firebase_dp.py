import firebase_admin
from firebase_admin import credentials, firestore
import os
from dotenv import load_dotenv
import json
import time
from datetime import datetime

# .env ファイルから環境変数を読み込む
load_dotenv()

# グローバル変数
_db_client = None
_initialized = False

# Firebase の初期化
def initialize_firebase():
    """Firebase Admin SDK を初期化して Firestore クライアントを返します"""
    global _db_client, _initialized
    
    if _initialized and _db_client:
        return _db_client
    
    try:
        if not firebase_admin._apps:
            # 環境変数から認証情報を取得
            cred_path = os.environ.get('FIREBASE_CREDENTIALS')
            project_id = os.environ.get('FIREBASE_PROJECT_ID')
            
            print(f"Firebase初期化開始 - project_id: {project_id}")
            
            if not project_id:
                raise ValueError("FIREBASE_PROJECT_ID 環境変数が設定されていません")
            
            # 本番環境（Firebase）の場合
            if cred_path and os.path.exists(cred_path):
                print("認証ファイルパスを使用")
                cred = credentials.Certificate(cred_path)
                firebase_admin.initialize_app(cred, {
                    'projectId': project_id,
                })
            else:
                # 環境変数にJSONが直接設定されている場合（Render等のサービス用）
                cred_json = os.environ.get('FIREBASE_CREDENTIALS_JSON')
                if cred_json:
                    print("環境変数のJSONを使用")
                    try:
                        service_account_info = json.loads(cred_json)
                        cred = credentials.Certificate(service_account_info)
                        firebase_admin.initialize_app(cred, {
                            'projectId': project_id,
                        })
                        print("Firebase初期化成功")
                    except json.JSONDecodeError as e:
                        print(f"JSON解析エラー: {str(e)}")
                        raise ValueError("FIREBASE_CREDENTIALS_JSON 環境変数が正しいJSON形式ではありません")
                else:
                    print("Firebase認証情報が見つかりません")
                    raise ValueError("Firebase認証情報が見つかりません。FIREBASE_CREDENTIALS_JSON または FIREBASE_CREDENTIALS を設定してください。")
        
        # Firestore クライアントを取得
        _db_client = firestore.client()
        _initialized = True
        print("Firestoreクライアント取得成功")
        return _db_client
        
    except Exception as e:
        print(f"Firebase初期化エラー: {str(e)}")
        _initialized = False
        _db_client = None
        raise e

def test_connection():
    """Firebase接続をテストする"""
    try:
        db = initialize_firebase()
        # テスト用の軽い操作を実行
        test_collection = db.collection('_connection_test')
        test_doc = test_collection.document('test')
        test_doc.set({
            'timestamp': datetime.utcnow().isoformat(),
            'status': 'connection_test'
        })
        # テストドキュメントを削除
        test_doc.delete()
        print("Firebase接続テスト成功")
        return True
    except Exception as e:
        print(f"Firebase接続テスト失敗: {str(e)}")
        raise e

def retry_operation(func, max_retries=3, delay=1):
    """操作を再試行する関数"""
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            print(f"操作失敗 (試行 {attempt + 1}/{max_retries}): {str(e)}")
            if attempt == max_retries - 1:
                raise e
            time.sleep(delay * (attempt + 1))  # 指数バックオフ

# データを読み込む関数
def load_data():
    """Firestore からデータを読み込む"""
    def _load_data():
        db = initialize_firebase()
        
        # ユーザーデータを取得
        users_ref = db.collection('users')
        users_docs = users_ref.stream()
        users = []
        for doc in users_docs:
            user_data = doc.to_dict()
            if user_data:  # 空のドキュメントを除外
                users.append(user_data)
        
        # 記録データを取得
        records_ref = db.collection('records')
        records_docs = records_ref.stream()
        records = []
        for doc in records_docs:
            record_data = doc.to_dict()
            if record_data:  # 空のドキュメントを除外
                records.append(record_data)
        
        print(f"データ読み込み成功: ユーザー{len(users)}件, 記録{len(records)}件")
        return {"users": users, "records": records}
    
    return retry_operation(_load_data)

# ユーザーを追加または取得する関数
def get_or_create_user(user_name, user_id=None):
    """ユーザー名からユーザーを取得、存在しない場合は作成"""
    def _get_or_create_user():
        db = initialize_firebase()
        users_ref = db.collection('users')
        
        # ユーザー名で検索
        query = users_ref.where('name', '==', user_name).limit(1)
        results = list(query.stream())
        
        if results:
            # ユーザーが存在する場合
            user_doc = results[0]
            user_data = user_doc.to_dict()
            print(f"既存ユーザー取得: {user_name}")
            return user_data
        elif user_id:
            # 新規ユーザーを作成
            new_user = {
                'id': user_id,
                'name': user_name,
                'created_at': datetime.utcnow().isoformat()
            }
            users_ref.document(user_id).set(new_user)
            print(f"新規ユーザー作成: {user_name}")
            return new_user
        else:
            print(f"ユーザーID不足: {user_name}")
            return None
    
    return retry_operation(_get_or_create_user)

# 記録を追加する関数
def add_record(record):
    """Firestore に新しい記録を追加"""
    def _add_record():
        db = initialize_firebase()
        records_ref = db.collection('records')
        
        # record の id をドキュメントIDとして使用
        record_with_timestamp = record.copy()
        record_with_timestamp['created_at'] = datetime.utcnow().isoformat()
        
        records_ref.document(record['id']).set(record_with_timestamp)
        print(f"記録追加成功: {record['userName']} - {record['type']}")
        return record
    
    return retry_operation(_add_record)

# 記録を更新する関数
def update_record(record_id, data):
    """Firestore の記録を更新"""
    def _update_record():
        db = initialize_firebase()
        record_ref = db.collection('records').document(record_id)
        
        # 更新データに更新時刻を追加
        update_data = data.copy()
        update_data['updated_at'] = datetime.utcnow().isoformat()
        
        record_ref.update(update_data)
        print(f"記録更新成功: {record_id}")
        return True
    
    return retry_operation(_update_record)

# 記録を削除する関数
def delete_record(record_id):
    """Firestore から記録を削除"""
    def _delete_record():
        db = initialize_firebase()
        record_ref = db.collection('records').document(record_id)
        
        # 削除前に存在確認
        doc = record_ref.get()
        if not doc.exists:
            raise ValueError(f"削除対象の記録が見つかりません: {record_id}")
        
        record_ref.delete()
        print(f"記録削除成功: {record_id}")
        return True
    
    return retry_operation(_delete_record)

# 複数の記録をインポートする関数
def import_records(records):
    """複数の記録を一括でインポート"""
    def _import_records():
        db = initialize_firebase()
        batch = db.batch()
        records_ref = db.collection('records')
        
        imported_count = 0
        current_time = datetime.utcnow().isoformat()
        
        for record in records:
            try:
                # IDの確認と生成
                if 'id' in record and record['id']:
                    doc_ref = records_ref.document(record['id'])
                else:
                    doc_ref = records_ref.document()
                    record['id'] = doc_ref.id
                
                # インポート時刻を追加
                record_with_timestamp = record.copy()
                record_with_timestamp['imported_at'] = current_time
                
                batch.set(doc_ref, record_with_timestamp, merge=True)
                imported_count += 1
                
                # バッチサイズ制限（Firestoreの制限は500）
                if imported_count % 400 == 0:
                    batch.commit()
                    batch = db.batch()  # 新しいバッチを作成
                    print(f"バッチコミット: {imported_count}件処理")
            
            except Exception as e:
                print(f"レコード処理エラー: {str(e)} - Record: {record}")
                continue
        
        # 残りのバッチをコミット
        if imported_count % 400 != 0:
            batch.commit()
        
        print(f"インポート完了: {imported_count}件")
        return imported_count
    
    return retry_operation(_import_records)

# データベースの統計情報を取得
def get_database_stats():
    """データベースの統計情報を取得"""
    def _get_stats():
        db = initialize_firebase()
        
        # ユーザー数をカウント
        users_ref = db.collection('users')
        users_count = len(list(users_ref.stream()))
        
        # 記録数をカウント
        records_ref = db.collection('records')
        records_count = len(list(records_ref.stream()))
        
        # 最新の記録を取得
        latest_record = None
        try:
            latest_records = records_ref.order_by('timestamp', direction=firestore.Query.DESCENDING).limit(1).stream()
            for record in latest_records:
                latest_record = record.to_dict()
                break
        except Exception as e:
            print(f"最新記録取得エラー: {str(e)}")
        
        stats = {
            'users_count': users_count,
            'records_count': records_count,
            'latest_record': latest_record,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        print(f"統計情報取得成功: ユーザー{users_count}件, 記録{records_count}件")
        return stats
    
    return retry_operation(_get_stats)

# データベースの健全性チェック
def health_check():
    """データベースの健全性をチェック"""
    try:
        # 接続テスト
        test_connection()
        
        # 統計情報取得テスト
        stats = get_database_stats()
        
        return {
            'status': 'healthy',
            'connection': 'ok',
            'stats': stats,
            'timestamp': datetime.utcnow().isoformat()
        }
    except Exception as e:
        return {
            'status': 'error',
            'connection': 'failed',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }

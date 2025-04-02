import firebase_admin
from firebase_admin import credentials, firestore
import os
from dotenv import load_dotenv
import json

# .env ファイルから環境変数を読み込む
load_dotenv()

# Firebase の初期化
def initialize_firebase():
    """Firebase Admin SDK を初期化して Firestore クライアントを返します"""
    if not firebase_admin._apps:
        # 環境変数から認証情報を取得
        cred_path = os.environ.get('FIREBASE_CREDENTIALS')
        project_id = os.environ.get('FIREBASE_PROJECT_ID')
        
        # 本番環境（Firebase）の場合
        if cred_path and os.path.exists(cred_path):
            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred, {
                'projectId': project_id,
            })
        else:
            # 環境変数にJSONが直接設定されている場合（Render等のサービス用）
            cred_json = os.environ.get('FIREBASE_CREDENTIALS_JSON')
            if cred_json:
                try:
                    service_account_info = json.loads(cred_json)
                    cred = credentials.Certificate(service_account_info)
                    firebase_admin.initialize_app(cred, {
                        'projectId': project_id,
                    })
                except json.JSONDecodeError:
                    raise ValueError("FIREBASE_CREDENTIALS_JSON 環境変数が正しいJSON形式ではありません")
            else:
                raise ValueError("Firebase 認証情報が見つかりません")
    
    # Firestore クライアントを取得
    return firestore.client()

# データを読み込む関数
def load_data():
    """Firestore からデータを読み込む"""
    db = initialize_firebase()
    
    # ユーザーデータを取得
    users_ref = db.collection('users')
    users = [doc.to_dict() for doc in users_ref.stream()]
    
    # 記録データを取得
    records_ref = db.collection('records')
    records = [doc.to_dict() for doc in records_ref.stream()]
    
    return {"users": users, "records": records}

# ユーザーを追加または取得する関数
def get_or_create_user(user_name, user_id=None):
    """ユーザー名からユーザーを取得、存在しない場合は作成"""
    db = initialize_firebase()
    users_ref = db.collection('users')
    
    # ユーザー名で検索
    query = users_ref.where('name', '==', user_name).limit(1)
    results = list(query.stream())
    
    if results:
        # ユーザーが存在する場合
        user_doc = results[0]
        return user_doc.to_dict()
    elif user_id:
        # 新規ユーザーを作成
        new_user = {
            'id': user_id,
            'name': user_name
        }
        users_ref.document(user_id).set(new_user)
        return new_user
    else:
        return None

# 記録を追加する関数
def add_record(record):
    """Firestore に新しい記録を追加"""
    db = initialize_firebase()
    records_ref = db.collection('records')
    
    # record の id をドキュメントIDとして使用
    records_ref.document(record['id']).set(record)
    return record

# 記録を更新する関数
def update_record(record_id, data):
    """Firestore の記録を更新"""
    db = initialize_firebase()
    record_ref = db.collection('records').document(record_id)
    record_ref.update(data)
    return True

# 記録を削除する関数
def delete_record(record_id):
    """Firestore から記録を削除"""
    db = initialize_firebase()
    record_ref = db.collection('records').document(record_id)
    record_ref.delete()
    return True

# 複数の記録をインポートする関数
def import_records(records):
    """複数の記録を一括でインポート"""
    db = initialize_firebase()
    batch = db.batch()
    records_ref = db.collection('records')
    
    for record in records:
        if 'id' in record and record['id']:
            doc_ref = records_ref.document(record['id'])
        else:
            doc_ref = records_ref.document()
            record['id'] = doc_ref.id
        
        batch.set(doc_ref, record)
    
    batch.commit()
    return len(records)

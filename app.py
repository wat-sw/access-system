from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import os
import json
from datetime import datetime
import uuid
import csv
from io import StringIO

# Firebase統合用のインポート
try:
    from firebase_dp import (
        initialize_firebase, 
        load_data as firebase_load_data, 
        get_or_create_user, 
        add_record as firebase_add_record,
        update_record as firebase_update_record,
        delete_record as firebase_delete_record,
        import_records as firebase_import_records
    )
    FIREBASE_AVAILABLE = True
except ImportError as e:
    print(f"Firebase統合が利用できません: {e}")
    FIREBASE_AVAILABLE = False

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # セッション管理用の秘密鍵（実際の運用では変更してください）

# データを保存するJSONファイルのパス
DATA_FILE = 'access_records.json'

# JSONファイルからデータを読み込む関数
def load_data(use_firebase=None):
    if use_firebase is None:
        use_firebase = session.get('use_firebase', False)
    
    if use_firebase and FIREBASE_AVAILABLE:
        try:
            return firebase_load_data()
        except Exception as e:
            app.logger.error(f"Firebase読み込みエラー: {str(e)}")
            # Firebaseでエラーの場合はJSONファイルにフォールバック
    
    # JSONファイルからデータを読み込む
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"records": [], "users": []}

# データをJSONファイルに保存する関数
def save_data(data, use_firebase=None):
    if use_firebase is None:
        use_firebase = session.get('use_firebase', False)
    
    # JSONファイルに保存する（常にバックアップとして保存）
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    # Firebaseにも保存（個別のレコード操作で行うため、ここでは何もしない）

# ログインページ
@app.route('/', methods=['GET', 'POST'])
def login():
    # クッキーからユーザー情報を確認（自動ログイン機能）
    if 'user_id' not in session and request.cookies.get('user_id') and request.cookies.get('user_name'):
        session['user_id'] = request.cookies.get('user_id')
        session['user_name'] = request.cookies.get('user_name')
        return redirect(url_for('main'))
    
    # すでにログインしている場合はメインページにリダイレクト
    if 'user_id' in session and 'user_name' in session:
        return redirect(url_for('main'))
    
    error = None
    
    if request.method == 'POST':
        # フォームからユーザー名を取得
        user_name = request.form.get('username')
        remember_me = request.form.get('remember_me') == 'on'  # チェックボックスの値を取得
        
        if user_name and user_name.strip():
            user_id = str(uuid.uuid4())
            
            # Firebase連携を試みる
            if FIREBASE_AVAILABLE:
                try:
                    user = get_or_create_user(user_name, user_id)
                    if user:
                        user_id = user['id']
                        user_name = user['name']
                        session['user_id'] = user_id
                        session['user_name'] = user_name
                        session['use_firebase'] = True
                        
                        app.logger.info(f"Firebase認証成功: {user_name}")
                    else:
                        raise Exception("ユーザーの作成/取得に失敗")
                        
                except Exception as e:
                    app.logger.error(f"Firebaseエラー: {str(e)}")
                    # Firebaseが利用できない場合はJSONファイルを使用
                    session['use_firebase'] = False
                    user_id, user_name = handle_local_login(user_name, user_id)
            else:
                # Firebaseが利用できない場合はJSONファイルを使用
                session['use_firebase'] = False
                user_id, user_name = handle_local_login(user_name, user_id)
            
            session['user_id'] = user_id
            session['user_name'] = user_name
            
            # レスポンスオブジェクトを作成してリダイレクト
            response = redirect(url_for('main'))
            
            # 「次回から自動的にログイン」がチェックされていればクッキーに保存
            if remember_me:
                # クッキーの有効期限を30日に設定
                response.set_cookie('user_id', user_id, max_age=30*24*60*60)
                response.set_cookie('user_name', user_name, max_age=30*24*60*60)
            
            return response
        else:
            error = "名前を入力してください"
    
    return render_template('login.html', error=error)

def handle_local_login(user_name, user_id):
    """ローカルJSONファイルでのログイン処理"""
    data = load_data(use_firebase=False)
    user_exists = False
    
    for user in data.get("users", []):
        if user["name"] == user_name:
            user_exists = True
            user_id = user["id"]
            break
    
    # 新規ユーザーの場合は追加
    if not user_exists:
        if "users" not in data:
            data["users"] = []
        
        data["users"].append({
            "id": user_id,
            "name": user_name
        })
        save_data(data, use_firebase=False)
    
    return user_id, user_name

# ログアウト
@app.route('/logout')
def logout():
    # セッションからユーザー情報を削除
    session.pop('user_id', None)
    session.pop('user_name', None)
    session.pop('use_firebase', None)
    
    # クッキーも削除するためのレスポンスを作成
    response = redirect(url_for('login'))
    response.delete_cookie('user_id')
    response.delete_cookie('user_name')
    
    return response

# メインページ（入退室ボタンのあるページ）
@app.route('/main')
def main():
    # ログインしていない場合はログインページにリダイレクト
    if 'user_id' not in session or 'user_name' not in session:
        return redirect(url_for('login'))
    
    # Firebase使用状況を表示用に追加
    firebase_status = "Firebase連携中" if session.get('use_firebase', False) else "ローカル保存"
    
    return render_template('main.html', 
                         user_name=session['user_name'],
                         firebase_status=firebase_status)

# 入室・退室の記録を保存するAPI
@app.route('/api/access', methods=['POST'])
def record_access():
    # ログインしていない場合はエラー
    if 'user_id' not in session or 'user_name' not in session:
        return jsonify({"success": False, "error": "ログインが必要です"})
    
    use_firebase = session.get('use_firebase', False)
    access_type = request.form.get('type')  # 'in' または 'out'
    
    # 新しい記録を作成
    record_id = str(uuid.uuid4())
    record = {
        "id": record_id,
        "userId": session['user_id'],
        "userName": session['user_name'],
        "type": access_type,
        "timestamp": datetime.now().isoformat()
    }
    
    if use_firebase and FIREBASE_AVAILABLE:
        try:
            # Firebaseに記録を追加
            firebase_add_record(record)
            app.logger.info(f"Firebase記録保存成功: {record['userName']} - {record['type']}")
        except Exception as e:
            app.logger.error(f"Firebase記録エラー: {str(e)}")
            # Firebaseエラーの場合はローカルにフォールバック
            use_firebase = False
    
    if not use_firebase:
        # JSONファイルにも記録を保存
        data = load_data(use_firebase=False)
        if "records" not in data:
            data["records"] = []
        data["records"].append(record)
        save_data(data, use_firebase=False)
        app.logger.info(f"ローカル記録保存: {record['userName']} - {record['type']}")
    
    return jsonify({"success": True})

# 管理ページ
@app.route('/admin')
def admin():
    use_firebase = session.get('use_firebase', False)
    data = load_data(use_firebase)
    
    # 入退室記録を時間の新しい順に並べ替え
    records = sorted(data.get("records", []), key=lambda x: x["timestamp"], reverse=True)
    
    # Firebase使用状況を表示用に追加
    firebase_status = "Firebase連携中" if use_firebase else "ローカル保存"
    
    return render_template('admin.html', 
                         records=records,
                         firebase_status=firebase_status)

# 記録の編集API
@app.route('/api/access/<record_id>', methods=['PUT'])
def update_record(record_id):
    use_firebase = session.get('use_firebase', False)
    
    # フォームからデータを取得
    user_name = request.form.get('userName')
    access_type = request.form.get('type')
    timestamp = request.form.get('timestamp')
    
    update_data = {
        "userName": user_name,
        "type": access_type,
        "timestamp": timestamp
    }
    
    if use_firebase and FIREBASE_AVAILABLE:
        try:
            # Firebaseの記録を更新
            firebase_update_record(record_id, update_data)
            app.logger.info(f"Firebase記録更新成功: {record_id}")
        except Exception as e:
            app.logger.error(f"Firebase更新エラー: {str(e)}")
            use_firebase = False
    
    if not use_firebase:
        # JSONファイルの記録を更新
        data = load_data(use_firebase=False)
        for record in data.get("records", []):
            if record["id"] == record_id:
                record.update(update_data)
                break
        save_data(data, use_firebase=False)
        app.logger.info(f"ローカル記録更新: {record_id}")
    
    return jsonify({"success": True})

# 記録の削除API（修正版）
@app.route('/api/access/<record_id>', methods=['DELETE'])
def delete_record(record_id):
    try:
        use_firebase = session.get('use_firebase', False)
        app.logger.info(f"削除処理開始: record_id={record_id}, use_firebase={use_firebase}")
        
        if use_firebase and FIREBASE_AVAILABLE:
            try:
                firebase_delete_record(record_id)
                app.logger.info(f"Firebase記録削除成功: {record_id}")
                return jsonify({"success": True, "message": "Firebase記録削除成功"})
            except Exception as e:
                app.logger.error(f"Firebase削除エラー: {str(e)}")
                use_firebase = False
        
        # ローカル削除
        if not use_firebase:
            data = load_data(use_firebase=False)
            original_count = len(data.get("records", []))
            
            data["records"] = [record for record in data.get("records", []) if record["id"] != record_id]
            
            new_count = len(data.get("records", []))
            deleted_count = original_count - new_count
            
            if deleted_count > 0:
                save_data(data, use_firebase=False)
                app.logger.info(f"ローカル記録削除成功: {record_id}, 削除件数: {deleted_count}")
                return jsonify({"success": True, "message": f"記録削除成功（{deleted_count}件）"})
            else:
                app.logger.warning(f"削除対象が見つかりません: {record_id}")
                return jsonify({"success": False, "error": "削除対象の記録が見つかりません"})
        
    except Exception as e:
        app.logger.error(f"削除処理エラー: {str(e)}")
        return jsonify({"success": False, "error": f"削除処理中にエラーが発生しました: {str(e)}"})

# CSVデータをインポートするAPI
@app.route('/api/import-records', methods=['POST'])
def import_records():
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "ログインが必要です"})
    
    try:
        # JSONデータを取得
        import_data = request.json
        records = import_data.get('records', [])
        
        if not records:
            return jsonify({"success": False, "error": "インポートするデータがありません"})
        
        use_firebase = session.get('use_firebase', False)
        imported_count = 0
        
        if use_firebase and FIREBASE_AVAILABLE:
            try:
                # Firebaseにインポート
                imported_count = firebase_import_records(records)
                app.logger.info(f"Firebaseインポート成功: {imported_count}件")
            except Exception as e:
                app.logger.error(f"Firebaseインポートエラー: {str(e)}")
                use_firebase = False
        
        if not use_firebase:
            # JSONファイルにインポート
            data = load_data(use_firebase=False)
            
            for record in records:
                # IDがある場合は既存の記録を更新
                if 'id' in record and record['id']:
                    updated = False
                    for existing_record in data["records"]:
                        if existing_record["id"] == record["id"]:
                            existing_record.update(record)
                            imported_count += 1
                            updated = True
                            break
                    
                    if not updated:
                        # 見つからない場合は新規追加
                        data["records"].append(record)
                        imported_count += 1
                else:
                    # IDがない場合は新規追加
                    record_id = str(uuid.uuid4())
                    new_record = {
                        "id": record_id,
                        "userId": session.get('user_id', ''),
                        "userName": record["userName"],
                        "type": record["type"],
                        "timestamp": record["timestamp"]
                    }
                    data["records"].append(new_record)
                    imported_count += 1
            
            save_data(data, use_firebase=False)
            app.logger.info(f"ローカルインポート: {imported_count}件")
        
        return jsonify({
            "success": True,
            "imported": imported_count
        })
    
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        })

# CSVエクスポートAPI
@app.route('/api/export-records')
def export_records():
    # 月パラメータを取得
    month = request.args.get('month', 'all')
    
    # データを読み込み
    use_firebase = session.get('use_firebase', False)
    data = load_data(use_firebase)
    records = data.get("records", [])
    
    # 月でフィルタリング
    if month != 'all':
        records = [r for r in records if r["timestamp"].startswith(month)]
    
    # CSVファイルを作成
    output = StringIO()
    writer = csv.writer(output)
    
    # ヘッダーを書き込み
    writer.writerow(['日付', '名前', '種類', '時間', 'ID'])
    
    # レコードを書き込み
    for record in records:
        timestamp = datetime.fromisoformat(record["timestamp"])
        date = timestamp.strftime('%Y-%m-%d')
        time = timestamp.strftime('%H:%M')
        type_text = '入室' if record["type"] == 'in' else '退室'
        
        writer.writerow([date, record["userName"], type_text, time, record["id"]])
    
    # CSVデータを送信
    csv_data = output.getvalue()
    output.close()
    
    # エンコーディングをUTF-8 with BOMに設定
    response = app.response_class(
        '\ufeff' + csv_data,  # BOMを追加
        mimetype='text/csv',
        headers={
            "Content-Disposition": f"attachment; filename=access_records_{month}.csv"
        }
    )
    
    return response

if __name__ == '__main__':
    # ローカル環境での実行
    app.run(debug=True, host='0.0.0.0', port=5000)
else:
    # 本番環境（Render）でも動作するように
    import os
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your_secret_key')
    
    # Firebaseの初期化をテスト
    try:
        if FIREBASE_AVAILABLE:
            from firebase_dp import initialize_firebase
            db = initialize_firebase()
            app.logger.info("Firebase接続成功")
    except Exception as e:
        app.logger.error(f"Firebase接続エラー（ローカルファイルを使用）: {str(e)}")
        FIREBASE_AVAILABLE = False

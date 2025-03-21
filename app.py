from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import os
import json
from datetime import datetime
import uuid

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # セッション管理用の秘密鍵（実際の運用では変更してください）

# データを保存するJSONファイルのパス
DATA_FILE = 'access_records.json'

# JSONファイルからデータを読み込む関数
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"records": [], "users": []}

# データをJSONファイルに保存する関数
def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

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
            # データを読み込み
            data = load_data()
            
            # ユーザーが存在するか確認
            user_exists = False
            user_id = None
            
            for user in data.get("users", []):
                if user["name"] == user_name:
                    user_exists = True
                    user_id = user["id"]
                    break
            
            # 新規ユーザーの場合は追加
            if not user_exists:
                user_id = str(uuid.uuid4())
                
                if "users" not in data:
                    data["users"] = []
                
                data["users"].append({
                    "id": user_id,
                    "name": user_name
                })
                save_data(data)
            
            # セッションにユーザー情報を保存
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

# ログアウト
@app.route('/logout')
def logout():
    # セッションからユーザー情報を削除
    session.pop('user_id', None)
    session.pop('user_name', None)
    
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
    
    return render_template('main.html', user_name=session['user_name'])

# 入室・退室の記録を保存するAPI
@app.route('/api/access', methods=['POST'])
def record_access():
    # ログインしていない場合はエラー
    if 'user_id' not in session or 'user_name' not in session:
        return jsonify({"success": False, "error": "ログインが必要です"})
    
    data = load_data()
    access_type = request.form.get('type')  # 'in' または 'out'
    
    # 新しい記録を作成
    record = {
        "id": str(uuid.uuid4()),  # 一意のID
        "userId": session['user_id'],
        "userName": session['user_name'],
        "type": access_type,
        "timestamp": datetime.now().isoformat()
    }
    
    # 記録を追加
    if "records" not in data:
        data["records"] = []
    
    data["records"].append(record)
    save_data(data)
    
    return jsonify({"success": True})

# 管理ページ
@app.route('/admin')
def admin():
    data = load_data()
    # 入退室記録を時間の新しい順に並べ替え
    records = sorted(data.get("records", []), key=lambda x: x["timestamp"], reverse=True)
    return render_template('admin.html', records=records)

# 記録の編集API
@app.route('/api/access/<record_id>', methods=['PUT'])
def update_record(record_id):
    data = load_data()
    
    # フォームからデータを取得
    user_name = request.form.get('userName')
    access_type = request.form.get('type')
    timestamp = request.form.get('timestamp')
    
    # 該当する記録を更新
    for record in data.get("records", []):
        if record["id"] == record_id:
            record["userName"] = user_name
            record["type"] = access_type
            record["timestamp"] = timestamp
            break
    
    save_data(data)
    return jsonify({"success": True})

# 記録の削除API
@app.route('/api/access/<record_id>', methods=['DELETE'])
def delete_record(record_id):
    data = load_data()
    
    # 該当する記録を削除
    data["records"] = [record for record in data.get("records", []) if record["id"] != record_id]
    
    save_data(data)
    return jsonify({"success": True})

if __name__ == '__main__':
    # ローカル環境での実行
    app.run(debug=True, host='0.0.0.0', port=5000)
else:
    # 本番環境（Render）でも動作するように
    import os
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your_secret_key')
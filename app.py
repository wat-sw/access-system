from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import os
import json
from datetime import datetime
import uuid
import csv
from io import StringIO
import pytz  # タイムゾーン処理用に追加

# Firebase統合用のインポート
try:
    from firebase_dp import (
        initialize_firebase, 
        load_data as firebase_load_data, 
        get_or_create_user, 
        add_record as firebase_add_record,
        update_record as firebase_update_record,
        delete_record as firebase_delete_record,
        import_records as firebase_import_records,
        test_connection
    )
    FIREBASE_AVAILABLE = True
except ImportError as e:
    print(f"Firebase統合が利用できません: {e}")
    FIREBASE_AVAILABLE = False

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your_secret_key_change_in_production')

# データを保存するJSONファイルのパス（バックアップ用のみ）
DATA_FILE = 'access_records.json'

# 日本時間のタイムゾーンを設定
JST = pytz.timezone('Asia/Tokyo')

# Firebase接続状態をグローバルで管理
FIREBASE_CONNECTION_OK = False

def initialize_app():
    """アプリケーション初期化時の処理"""
    global FIREBASE_CONNECTION_OK
    
    if FIREBASE_AVAILABLE:
        try:
            print("Firebase接続をテスト中...")
            test_connection()
            FIREBASE_CONNECTION_OK = True
            print("✅ Firebase接続成功！")
        except Exception as e:
            print(f"❌ Firebase接続エラー: {str(e)}")
            FIREBASE_CONNECTION_OK = False
    else:
        print("⚠️ Firebase統合が利用できません")

# 日本時間の現在時刻を取得する関数
def get_jst_now():
    """日本時間の現在時刻を取得"""
    utc_now = datetime.utcnow()
    utc_now = pytz.utc.localize(utc_now)
    jst_now = utc_now.astimezone(JST)
    return jst_now

# データベース接続確認
def ensure_database_connection():
    """データベース接続を確認し、接続できない場合はエラーページを表示"""
    if not FIREBASE_CONNECTION_OK:
        return render_template('error.html', 
                             error_title="データベース接続エラー",
                             error_message="データベースに接続できません。管理者にお問い合わせください。",
                             firebase_status="接続不可")
    return None

# ヘルスチェック用エンドポイント（改善版）
@app.route('/health')
def health_check():
    """アプリの状態を確認するためのヘルスチェックエンドポイント"""
    try:
        firebase_connection_status = "OK" if FIREBASE_CONNECTION_OK else "NG"
        
        # Firebase再接続テスト
        firebase_test_result = "スキップ"
        if FIREBASE_AVAILABLE:
            try:
                test_connection()
                firebase_test_result = "成功"
            except Exception as e:
                firebase_test_result = f"失敗: {str(e)}"
        
        # 日本時間の現在時刻を表示
        current_jst = get_jst_now()
        
        status_code = 200 if FIREBASE_CONNECTION_OK else 503
        
        return jsonify({
            "status": "healthy" if FIREBASE_CONNECTION_OK else "unhealthy",
            "timestamp_utc": datetime.utcnow().isoformat(),
            "timestamp_jst": current_jst.isoformat(),
            "current_jst_readable": current_jst.strftime('%Y年%m月%d日 %H:%M:%S'),
            "firebase_available": FIREBASE_AVAILABLE,
            "firebase_connection": firebase_connection_status,
            "firebase_test": firebase_test_result,
            "data_file_exists": os.path.exists(DATA_FILE),
            "environment": os.environ.get('ENV', 'development')
        }), status_code
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }), 500

# 簡単な応答確認用エンドポイント
@app.route('/ping')
def ping():
    """簡単な応答確認用"""
    current_jst = get_jst_now()
    return jsonify({
        "message": "pong",
        "timestamp_utc": datetime.utcnow().isoformat(),
        "timestamp_jst": current_jst.isoformat(),
        "current_jst_readable": current_jst.strftime('%Y年%m月%d日 %H:%M:%S'),
        "status": "running",
        "firebase_ok": FIREBASE_CONNECTION_OK
    })

# JSONファイルからデータを読み込む関数（バックアップ用）
def load_local_data():
    """ローカルJSONファイルからデータを読み込む（バックアップ用）"""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            app.logger.error(f"ローカルファイル読み込みエラー: {str(e)}")
    return {"records": [], "users": []}

# データを読み込む関数（Firebase優先）
def load_data():
    """Firebaseからデータを読み込む（エラー時はローカルファイル）"""
    if FIREBASE_CONNECTION_OK:
        try:
            return firebase_load_data()
        except Exception as e:
            app.logger.error(f"Firebase読み込みエラー: {str(e)}")
            # 緊急時のみローカルファイルを使用（警告付き）
            app.logger.warning("緊急時モード: ローカルファイルを使用")
    
    # ローカルファイルからデータを読み込む（バックアップ）
    return load_local_data()

# データをバックアップファイルに保存する関数
def save_backup_data(data):
    """データをバックアップファイルに保存"""
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        app.logger.info("バックアップファイル保存成功")
    except Exception as e:
        app.logger.error(f"バックアップ保存エラー: {str(e)}")

# ログインページ
@app.route('/', methods=['GET', 'POST'])
def login():
    # データベース接続確認
    db_error = ensure_database_connection()
    if db_error:
        return db_error
    
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
        remember_me = request.form.get('remember_me') == 'on'
        
        if user_name and user_name.strip():
            user_id = str(uuid.uuid4())
            
            try:
                # Firebase経由でユーザー作成/取得
                user = get_or_create_user(user_name, user_id)
                if user:
                    user_id = user['id']
                    user_name = user['name']
                    app.logger.info(f"ユーザー認証成功: {user_name}")
                else:
                    raise Exception("ユーザーの作成/取得に失敗")
                    
            except Exception as e:
                app.logger.error(f"ユーザー認証エラー: {str(e)}")
                error = "ログイン処理中にエラーが発生しました。時間をおいて再試行してください。"
                return render_template('login.html', error=error)
            
            session['user_id'] = user_id
            session['user_name'] = user_name
            
            # レスポンスオブジェクトを作成してリダイレクト
            response = redirect(url_for('main'))
            
            # 「次回から自動的にログイン」がチェックされていればクッキーに保存
            if remember_me:
                response.set_cookie('user_id', user_id, max_age=30*24*60*60)
                response.set_cookie('user_name', user_name, max_age=30*24*60*60)
            
            return response
        else:
            error = "名前を入力してください"
    
    return render_template('login.html', error=error)

# ログアウト
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('user_name', None)
    
    response = redirect(url_for('login'))
    response.delete_cookie('user_id')
    response.delete_cookie('user_name')
    
    return response

# メインページ（入退室ボタンのあるページ）
@app.route('/main')
def main():
    # データベース接続確認
    db_error = ensure_database_connection()
    if db_error:
        return db_error
        
    # ログインしていない場合はログインページにリダイレクト
    if 'user_id' not in session or 'user_name' not in session:
        return redirect(url_for('login'))
    
    # Firebase使用状況を表示用に追加
    firebase_status = "Firebase連携中" if FIREBASE_CONNECTION_OK else "接続エラー"
    
    # 現在の日本時間を表示用に取得
    current_jst = get_jst_now()
    current_time_display = current_jst.strftime('%Y年%m月%d日 %H:%M')
    
    return render_template('main.html', 
                         user_name=session['user_name'],
                         firebase_status=firebase_status,
                         current_time=current_time_display)

# 入室・退室の記録を保存するAPI
@app.route('/api/access', methods=['POST'])
def record_access():
    # データベース接続確認
    if not FIREBASE_CONNECTION_OK:
        return jsonify({"success": False, "error": "データベースに接続できません"})
        
    # ログインしていない場合はエラー
    if 'user_id' not in session or 'user_name' not in session:
        return jsonify({"success": False, "error": "ログインが必要です"})
    
    access_type = request.form.get('type')  # 'in' または 'out'
    
    # 新しい記録を作成（日本時間を使用）
    record_id = str(uuid.uuid4())
    jst_now = get_jst_now()
    
    record = {
        "id": record_id,
        "userId": session['user_id'],
        "userName": session['user_name'],
        "type": access_type,
        "timestamp": jst_now.isoformat()
    }
    
    try:
        # Firebaseに記録を追加
        firebase_add_record(record)
        app.logger.info(f"記録保存成功: {record['userName']} - {record['type']} - {jst_now.strftime('%H:%M:%S')}")
        
        # バックアップファイルにも保存
        try:
            data = load_local_data()
            if "records" not in data:
                data["records"] = []
            data["records"].append(record)
            save_backup_data(data)
        except Exception as backup_error:
            app.logger.warning(f"バックアップ保存エラー: {str(backup_error)}")
        
        return jsonify({
            "success": True,
            "timestamp_jst": jst_now.strftime('%Y年%m月%d日 %H:%M:%S'),
            "type_text": "入室" if access_type == "in" else "退室"
        })
        
    except Exception as e:
        app.logger.error(f"記録保存エラー: {str(e)}")
        return jsonify({
            "success": False, 
            "error": "記録の保存に失敗しました。時間をおいて再試行してください。"
        })

# 管理ページ（修正版：全員の記録を表示）
@app.route('/admin')
def admin():
    # データベース接続確認
    db_error = ensure_database_connection()
    if db_error:
        return db_error
        
    try:
        # 全員のデータを取得（ログインユーザーに関係なく）
        data = load_data()
        
        # 全ての記録を時間の新しい順に並べ替え
        all_records = sorted(data.get("records", []), key=lambda x: x["timestamp"], reverse=True)
        
        # 統計情報を計算
        total_records = len(all_records)
        unique_users = len(set(record["userName"] for record in all_records))
        
        # 今日の記録数を計算
        today = get_jst_now().strftime('%Y-%m-%d')
        today_records = [r for r in all_records if r["timestamp"].startswith(today)]
        today_count = len(today_records)
        
        firebase_status = "Firebase連携中" if FIREBASE_CONNECTION_OK else "接続エラー"
        
        return render_template('admin.html', 
                             records=all_records,
                             firebase_status=firebase_status,
                             total_records=total_records,
                             unique_users=unique_users,
                             today_count=today_count,
                             current_user=session.get('user_name', ''))
    except Exception as e:
        app.logger.error(f"管理画面データ読み込みエラー: {str(e)}")
        return render_template('error.html',
                             error_title="データ読み込みエラー",
                             error_message="データの読み込みに失敗しました。",
                             firebase_status="エラー")

# 管理画面用のユーザー一覧取得API
@app.route('/api/users')
def get_users():
    """登録済みユーザー一覧を取得"""
    if not FIREBASE_CONNECTION_OK:
        return jsonify({"success": False, "error": "データベースに接続できません"})
    
    try:
        data = load_data()
        users = data.get("users", [])
        
        # ユーザー名のリストを作成
        user_names = [user["name"] for user in users]
        
        return jsonify({
            "success": True,
            "users": user_names,
            "count": len(user_names)
        })
    except Exception as e:
        app.logger.error(f"ユーザー一覧取得エラー: {str(e)}")
        return jsonify({"success": False, "error": "ユーザー一覧の取得に失敗しました"})

# 特定ユーザーの記録フィルタリングAPI
@app.route('/api/records/filter')
def filter_records():
    """特定の条件で記録をフィルタリング"""
    if not FIREBASE_CONNECTION_OK:
        return jsonify({"success": False, "error": "データベースに接続できません"})
    
    try:
        user_name = request.args.get('user')
        date = request.args.get('date')
        month = request.args.get('month')
        
        data = load_data()
        records = data.get("records", [])
        
        # フィルタリング
        filtered_records = records
        
        if user_name:
            filtered_records = [r for r in filtered_records if r["userName"] == user_name]
        
        if date:
            filtered_records = [r for r in filtered_records if r["timestamp"].startswith(date)]
        elif month:
            filtered_records = [r for r in filtered_records if r["timestamp"].startswith(month)]
        
        # 時間の新しい順に並べ替え
        filtered_records = sorted(filtered_records, key=lambda x: x["timestamp"], reverse=True)
        
        return jsonify({
            "success": True,
            "records": filtered_records,
            "count": len(filtered_records)
        })
    except Exception as e:
        app.logger.error(f"記録フィルタリングエラー: {str(e)}")
        return jsonify({"success": False, "error": "記録の取得に失敗しました"})

# 記録の編集API
@app.route('/api/access/<record_id>', methods=['PUT'])
def update_record(record_id):
    if not FIREBASE_CONNECTION_OK:
        return jsonify({"success": False, "error": "データベースに接続できません"})
    
    try:
        user_name = request.form.get('userName')
        access_type = request.form.get('type')
        timestamp = request.form.get('timestamp')
        
        update_data = {
            "userName": user_name,
            "type": access_type,
            "timestamp": timestamp
        }
        
        firebase_update_record(record_id, update_data)
        app.logger.info(f"記録更新成功: {record_id}")
        
        return jsonify({"success": True})
        
    except Exception as e:
        app.logger.error(f"記録更新エラー: {str(e)}")
        return jsonify({"success": False, "error": "更新に失敗しました"})

# 記録の削除API
@app.route('/api/access/<record_id>', methods=['DELETE'])
def delete_record(record_id):
    if not FIREBASE_CONNECTION_OK:
        return jsonify({"success": False, "error": "データベースに接続できません"})
        
    try:
        firebase_delete_record(record_id)
        app.logger.info(f"記録削除成功: {record_id}")
        return jsonify({"success": True, "message": "記録削除成功"})
        
    except Exception as e:
        app.logger.error(f"記録削除エラー: {str(e)}")
        return jsonify({"success": False, "error": "削除に失敗しました"})

# CSVデータをインポートするAPI
@app.route('/api/import-records', methods=['POST'])
def import_records():
    if not FIREBASE_CONNECTION_OK:
        return jsonify({"success": False, "error": "データベースに接続できません"})
        
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "ログインが必要です"})
    
    try:
        import_data = request.json
        records = import_data.get('records', [])
        
        if not records:
            return jsonify({"success": False, "error": "インポートするデータがありません"})
        
        # インポートするレコードのタイムゾーンを確認・修正
        for record in records:
            if 'timestamp' in record:
                try:
                    dt = datetime.fromisoformat(record['timestamp'].replace('Z', '+00:00'))
                    if dt.tzinfo is None:
                        dt = JST.localize(dt)
                    record['timestamp'] = dt.isoformat()
                except Exception as e:
                    app.logger.error(f"タイムスタンプ変換エラー: {str(e)}")
                    record['timestamp'] = get_jst_now().isoformat()
        
        # Firebaseにインポート
        imported_count = firebase_import_records(records)
        app.logger.info(f"インポート成功: {imported_count}件")
        
        return jsonify({
            "success": True,
            "imported": imported_count
        })
    
    except Exception as e:
        app.logger.error(f"インポートエラー: {str(e)}")
        return jsonify({
            "success": False,
            "error": f"インポートに失敗しました: {str(e)}"
        })

# CSVエクスポートAPI
@app.route('/api/export-records')
def export_records():
    if not FIREBASE_CONNECTION_OK:
        return jsonify({"error": "データベースに接続できません"}), 503
        
    try:
        month = request.args.get('month', 'all')
        data = load_data()
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
            try:
                timestamp_str = record["timestamp"]
                if timestamp_str.endswith('Z'):
                    dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                    dt = dt.astimezone(JST)
                else:
                    dt = datetime.fromisoformat(timestamp_str)
                    if dt.tzinfo is None:
                        dt = JST.localize(dt)
                    else:
                        dt = dt.astimezone(JST)
                
                date = dt.strftime('%Y-%m-%d')
                time = dt.strftime('%H:%M')
                type_text = '入室' if record["type"] == 'in' else '退室'
                
                writer.writerow([date, record["userName"], type_text, time, record["id"]])
            except Exception as e:
                app.logger.error(f"CSV出力エラー: {str(e)} - Record: {record}")
                continue
        
        csv_data = output.getvalue()
        output.close()
        
        response = app.response_class(
            '\ufeff' + csv_data,
            mimetype='text/csv',
            headers={
                "Content-Disposition": f"attachment; filename=access_records_{month}.csv"
            }
        )
        
        return response
        
    except Exception as e:
        app.logger.error(f"CSVエクスポートエラー: {str(e)}")
        return jsonify({"error": "エクスポートに失敗しました"}), 500

# エラーページ用のテンプレートを追加
@app.errorhandler(500)
def internal_error(error):
    return render_template('error.html',
                         error_title="内部サーバーエラー",
                         error_message="申し訳ございませんが、サーバーでエラーが発生しました。",
                         firebase_status="不明"), 500

@app.errorhandler(503)
def service_unavailable(error):
    return render_template('error.html',
                         error_title="サービス利用不可",
                         error_message="現在サービスが利用できません。しばらく時間をおいて再試行してください。",
                         firebase_status="接続不可"), 503

if __name__ == '__main__':
    # アプリケーション初期化
    initialize_app()
    # ローカル環境での実行
    app.run(debug=True, host='0.0.0.0', port=5000)
else:
    # 本番環境
    # アプリケーション初期化
    initialize_app()
    
    # 日本時間での起動メッセージ
    current_jst = get_jst_now()
    print(f"アプリケーション起動: {current_jst.strftime('%Y年%m月%d日 %H:%M:%S')} JST")
    print(f"Firebase接続状態: {'OK' if FIREBASE_CONNECTION_OK else 'NG'}")

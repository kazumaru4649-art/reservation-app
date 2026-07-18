import streamlit as st
import pandas as pd
import qrcode
from PIL import Image
import io
from streamlit_gsheets import GSheetsConnection
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

st.set_page_config(page_title="座席管理システム", layout="centered")

def send_qr_email(to_email, name, seat, new_id, qr_bytes):
    try:
        if "email" not in st.secrets:
            return False
        sender_email = st.secrets["email"]["sender_email"]
        app_password = st.secrets["email"]["app_password"]
        
        msg = MIMEMultipart()
        msg['Subject'] = '【自動座席割り当て予約システム】ご予約完了のお知らせ'
        msg['From'] = sender_email
        msg['To'] = to_email

        body = f"{name} 様\n\nご予約ありがとうございます。\n\n【ご予約内容】\n・予約ID：{new_id}\n・お席：{seat}番席\n\n当日は添付のQRコードを受付にてご提示いただくか、スタッフに「予約ID」をお伝えください。\nご来店を心よりお待ちしております。\n\n※このメールは自動送信されています。"
        msg.attach(MIMEText(body, 'plain'))
        
        img = MIMEImage(qr_bytes)
        img.add_header('Content-Disposition', 'attachment', filename=f"qrcode_{new_id}.png")
        msg.attach(img)
        
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender_email, app_password)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"Email error: {e}")
        return False

# --- Google Sheets 接続設定 ---
# 実行前に .streamlit/secrets.toml の設定と、スプレッドシートの共有設定が必要です。
def get_data():
    conn = st.connection("gsheets", type=GSheetsConnection)
    df_seats = conn.read(worksheet="座席状況", ttl=0)
    df_reservations = conn.read(worksheet="予約リスト", ttl=0)
    
    # 欠損値(NaN)が含まれる場合の処理
    df_seats = df_seats.fillna(0)
    df_reservations = df_reservations.fillna("")
    
    return conn, df_seats, df_reservations

# --- メニュー（サイドバー） ---
st.sidebar.title("メニュー")
page = st.sidebar.radio("ページを選択", ["お客様向け：予約画面", "スタッフ向け：受付（チェックイン）"])

# ==========================================
# 予約画面（お客様向け）
# ==========================================
if page == "お客様向け：予約画面":
    st.title("自動座席割り当て予約システム")
    st.write("以下のフォームに必要事項を入力して予約を行ってください。")
    
    with st.form("reservation_form"):
        name = st.text_input("お名前（代表者）")
        email = st.text_input("メールアドレス")
        num_people = st.selectbox("ご予約人数", options=[1, 2, 3, 4])
        
        submitted = st.form_submit_button("予約する")

    if submitted:
        if not name or not email:
            st.error("お名前とメールアドレスを入力してください。")
        else:
            try:
                conn, df_seats, df_reservations = get_data()
                
                assigned_seat = None
                
                # 【重要】相席ロジック：空き枠がある席を上から探し、相席で無駄なく埋める
                for index, row in df_seats.iterrows():
                    available_space = int(row["最大定員"]) - int(row["現在の予約人数"])
                    if available_space >= num_people:
                        assigned_seat = int(row["席番号"])
                        df_seats.at[index, "現在の予約人数"] = int(row["現在の予約人数"]) + num_people
                        break
                        
                if assigned_seat is None:
                    st.error("満席エラー：現在ご案内できる空き座席がありません。")
                else:
                    # 予約IDの採番
                    if len(df_reservations) == 0:
                        new_id = 1
                    else:
                        # 既存の最大IDに+1する
                        df_reservations["予約ID"] = pd.to_numeric(df_reservations["予約ID"], errors="coerce").fillna(0)
                        new_id = int(df_reservations["予約ID"].max()) + 1
                        
                    new_reservation = pd.DataFrame([{
                        "予約ID": new_id,
                        "お名前": name,
                        "メールアドレス": email,
                        "予約人数": num_people,
                        "席番号": assigned_seat,
                        "ステータス": "予約確定"
                    }])
                    
                    df_reservations = pd.concat([df_reservations, new_reservation], ignore_index=True)
                    
                    # Googleスプレッドシートを更新
                    conn.update(worksheet="座席状況", data=df_seats)
                    conn.update(worksheet="予約リスト", data=df_reservations)
                    
                    # QRコードの生成
                    qr_data = f"CHECKIN_ID:{new_id}"
                    qr = qrcode.QRCode(version=1, box_size=10, border=4)
                    qr.add_data(qr_data)
                    qr.make(fit=True)
                    img = qr.make_image(fill_color="black", back_color="white")
                    
                    buf = io.BytesIO()
                    img.save(buf, format="PNG")
                    byte_im = buf.getvalue()
                    
                    # メール送信
                    email_sent = send_qr_email(email, name, assigned_seat, new_id, byte_im)
                    
                    # セッションステートに保存
                    st.session_state["reservation_success"] = {
                        "new_id": new_id,
                        "assigned_seat": assigned_seat,
                        "byte_im": byte_im,
                        "email_sent": email_sent
                    }
                    
            except Exception as e:
                st.error(f"データベースの読み込みに失敗しました。設定を確認してください。エラー詳細: {e}")

    # フォームの外で結果とダウンロードボタンを表示
    if "reservation_success" in st.session_state:
        res = st.session_state["reservation_success"]
        st.success(f"予約が完了しました。予約IDは {res['new_id']} 番、割り当てられた席は {res['assigned_seat']} 番です。")
        if res.get("email_sent"):
            st.info("ご入力いただいたメールアドレス宛に、QRコードを添付した予約完了メールを送信しました。")
        else:
            st.warning("予約は完了しましたが、メール設定が未完了のためメールは送信されませんでした。下のボタンからQRコードを保存してください。")
            
        st.write("当日は以下のQRコードを受付でご提示ください。")
        st.image(res['byte_im'], caption="チェックイン用QRコード")
        st.download_button(label="QRコード画像を保存", data=res['byte_im'], file_name=f"qrcode_{res['new_id']}.png", mime="image/png")
        
        st.markdown("---")
        if st.button("続けて別の予約を行う（画面をリセット）"):
            del st.session_state["reservation_success"]
            st.rerun()

# ==========================================
# 受付画面（スタッフ向け）
# ==========================================
elif page == "スタッフ向け：受付（チェックイン）":
    st.title("QRコード受付（チェックイン）システム")
    st.write("お客様のQRコードをカメラで撮影するか、予約IDを手入力してください。")
    
    # --- カメラで自動読み取り ---
    if st.checkbox("📸 カメラを起動してQRコードを読み取る", key="camera_toggle"):
        st.info("※「learn how to allow access」と出る場合は、ブラウザのURL横にある🔒マーク（サイト設定）から、カメラの権限を「許可」に変更してください。")
        
        try:
            from streamlit_qrcode_scanner import qrcode_scanner
            # カメラ映像をリアルタイムで表示し、QRを自動検出する
            qr_code = qrcode_scanner(key='qrcode_scanner_widget')
            
            if qr_code:
                st.success("QRコードを読み取りました！下の「受付を行う」ボタンを押してください。")
                # 読み取った値を直接テキストボックスにセットする
                st.session_state["qr_input_field"] = qr_code
        except Exception as e:
            st.error("カメラの起動に失敗しました。")

    # --- 予約IDの手入力・受付実行 ---
    st.markdown("---")
    qr_input = st.text_input("QRコードデータ または 予約ID（例: 1）を入力", key="qr_input_field")
    
    if st.button("受付を行う", type="primary"):
        if not qr_input:
            st.error("予約IDが入力されていません。（空欄です）")
        else:
            try:
                conn, df_seats, df_reservations = get_data()
                
                # 余分な文字列を省いてID部分のみを取り出す
                res_id_str = str(qr_input).replace("CHECKIN_ID:", "").strip()
                try:
                    res_id = int(res_id_str)
                except ValueError:
                    st.error("無効なID形式です。")
                    st.stop()
                
                # 予約ID列を数値に変換してから検索
                df_reservations["予約ID"] = pd.to_numeric(df_reservations["予約ID"], errors="coerce").fillna(0)
                match_idx = df_reservations.index[df_reservations['予約ID'] == res_id].tolist()
                
                if not match_idx:
                    st.error("予約データが見つかりません。（データが存在しないか、IDが間違っています）")
                else:
                    idx = match_idx[0]
                    status = df_reservations.at[idx, 'ステータス']
                    name = df_reservations.at[idx, 'お名前']
                    seat = df_reservations.at[idx, '席番号']
                    
                    if status == "来店済み":
                        st.warning("⚠️ 既に受付済みのQRコード（お客様）です！")
                    else:
                        # ステータスを更新
                        df_reservations.at[idx, 'ステータス'] = "来店済み"
                        
                        # 小数点が付いてしまう問題への対策（3.0 -> 3）
                        try:
                            seat_display = int(float(seat))
                        except:
                            seat_display = seat
                        
                        # Googleスプレッドシートを更新
                        conn.update(worksheet="予約リスト", data=df_reservations)
                        
                        st.success(f"受付完了：{name}様 ➡️ {seat_display}番席へご案内してください")
                        
                        st.markdown("---")
                        if st.button("次の人の受付を行う（画面をリセット）"):
                            # カメラの写真と入力欄をクリアして再読み込み
                            if "camera_widget" in st.session_state:
                                del st.session_state["camera_widget"]
                            if "qr_input_field" in st.session_state:
                                del st.session_state["qr_input_field"]
                            st.rerun()
                        
            except Exception as e:
                st.error(f"データベースの読み込みに失敗しました。設定を確認してください。エラー詳細: {e}")

    # --- データリセット機能（管理者専用） ---
    st.markdown("---")
    with st.expander("⚠️ データリセット（管理者専用）", expanded=False):
        st.warning("スプレッドシートの予約データをすべて消去して初期状態に戻します。")
        reset_pass = st.text_input("管理者パスワードを入力してください", type="password")
        
        if st.button("全データを本当にリセットする", type="primary"):
            if reset_pass == "4649":
                try:
                    conn, df_seats, df_reservations = get_data()
                    
                    # 座席状況の人数を0にする
                    df_seats["現在の予約人数"] = 0
                    
                    # 予約リストを空にする（列名だけ残す）
                    df_reservations = pd.DataFrame(columns=["予約ID", "お名前", "メールアドレス", "予約人数", "席番号", "ステータス"])
                    
                    # スプレッドシートを更新
                    conn.update(worksheet="座席状況", data=df_seats)
                    conn.update(worksheet="予約リスト", data=df_reservations)
                    
                    st.success("すべての予約データをリセットしました！")
                except Exception as e:
                    st.error(f"リセットに失敗しました: {e}")
            else:
                st.error("パスワードが間違っています。")

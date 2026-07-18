import streamlit as st
import pandas as pd
import qrcode
from PIL import Image
import io
from streamlit_gsheets import GSheetsConnection

st.set_page_config(page_title="座席管理システム", layout="centered")

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
                        
                        st.success(f"予約が完了しました。予約IDは {new_id} 番、割り当てられた席は {assigned_seat} 番です。")
                        st.write("当日は以下のQRコードを受付でご提示ください。")
                        st.image(byte_im, caption="チェックイン用QRコード")
                        st.download_button(label="QRコード画像を保存", data=byte_im, file_name=f"qrcode_{new_id}.png", mime="image/png")
                        
                except Exception as e:
                    st.error(f"データベースの読み込みに失敗しました。設定を確認してください。エラー詳細: {e}")

# ==========================================
# 受付画面（スタッフ向け）
# ==========================================
elif page == "スタッフ向け：受付（チェックイン）":
    st.title("QRコード受付（チェックイン）システム")
    st.write("QRコードをスキャンするか、手入力で予約IDを入力してください。")
    
    qr_input = st.text_input("QRコードデータ（例: CHECKIN_ID:1）または予約ID（例: 1）を入力")
    
    if st.button("受付を行う"):
        if not qr_input:
            st.error("データが入力されていません。")
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
                    st.error("該当する予約データが見つかりません。")
                else:
                    idx = match_idx[0]
                    status = df_reservations.at[idx, 'ステータス']
                    name = df_reservations.at[idx, 'お名前']
                    seat = df_reservations.at[idx, '席番号']
                    
                    if status == "来店済み":
                        st.warning("既に受付済みです。")
                    else:
                        # ステータスを更新
                        df_reservations.at[idx, 'ステータス'] = "来店済み"
                        
                        # Googleスプレッドシートを更新
                        conn.update(worksheet="予約リスト", data=df_reservations)
                        
                        st.success(f"受付完了：{name}様 ➡️ {seat}番席へご案内してください")
                        
            except Exception as e:
                st.error(f"データベースの読み込みに失敗しました。設定を確認してください。エラー詳細: {e}")

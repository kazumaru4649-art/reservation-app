import streamlit as st
import pandas as pd
import qrcode
from PIL import Image
import io
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from streamlit_gsheets import GSheetsConnection
import datetime
import uuid

st.set_page_config(page_title="先行座席予約", layout="centered")

# --- メール送信機能 ---
def send_qr_email(to_email, name, seat, res_id, event_name, qr_bytes, num_people, gender):
    try:
        if "email" not in st.secrets:
            return False
        sender_email = st.secrets["email"]["sender_email"]
        app_password = st.secrets["email"]["app_password"]
        
        msg = MIMEMultipart()
        msg['Subject'] = f'【先行座席予約】{event_name} ご予約完了のお知らせ'
        msg['From'] = sender_email
        msg['To'] = to_email

        body = f"{name} 様\n\nご予約ありがとうございます。\n\n【ご予約内容】\n・イベント：{event_name}\n・予約ID：{res_id}\n・お名前：{name} 様\n・性別：{gender}\n・人数：{num_people}名様\n・お席：{seat}番席\n\n当日は添付のQRコードを受付にてご提示いただくか、スタッフに「予約ID」をお伝えください。\nご来店を心よりお待ちしております。\n\n※このメールは自動送信されています。"
        msg.attach(MIMEText(body, 'plain'))
        
        img = MIMEImage(qr_bytes)
        img.add_header('Content-ID', '<qr_code>')
        msg.attach(img)
        
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, app_password)
            server.send_message(msg)
        return True
    except Exception as e:
        st.error(f"メール送信に失敗しました: {e}")
        return False

def send_pin_email(to_email, name, event_name, pin_code):
    try:
        if "email" not in st.secrets:
            return False
        sender_email = st.secrets["email"]["sender_email"]
        app_password = st.secrets["email"]["app_password"]
        
        msg = MIMEMultipart()
        msg['Subject'] = f'【先行座席予約】{event_name} 確認コードのお知らせ'
        msg['From'] = sender_email
        msg['To'] = to_email

        body = f"{name} 様\n\nご予約手続きを進めていただきありがとうございます。\n\nご予約を確定するための4桁の確認コードは以下の通りです：\n\n【 {pin_code} 】\n\n予約画面に戻り、この確認コードを入力して予約を完了してください。\n\n※このメールは自動送信されています。"
        msg.attach(MIMEText(body, 'plain'))
        
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, app_password)
            server.send_message(msg)
        return True
    except Exception as e:
        st.error(f"確認メールの送信に失敗しました: {e}")
        return False

# --- データ取得機能 ---
@st.cache_data(ttl=600)
def get_data():
    conn = st.connection("gsheets", type=GSheetsConnection)
    df_events = conn.read(worksheet="Events", usecols=list(range(4)))
    df_seats = conn.read(worksheet="Seats", usecols=list(range(4)))
    df_reservations = conn.read(worksheet="Reservations", usecols=list(range(8)))
    return df_events.fillna(""), df_seats.fillna(""), df_reservations.fillna("")

# ==========================================
# URLパラメータの確認（専用URLからのアクセス判定）
# ==========================================
query_params = st.query_params
target_event_id = query_params.get("event_id", None)

if target_event_id:
    # --- 専用URL（QR）からのアクセス：予約画面のみ表示 ---
    st.title("先行座席予約")
    
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        df_events, df_seats, df_reservations = get_data()
        
        # 該当イベントの情報を取得
        event_info = df_events[(df_events["イベントID"] == target_event_id) & (df_events["ステータス"] == "受付中")]
        
        if event_info.empty:
            st.error("指定されたイベントは現在予約を受け付けていません。（終了したか、URLが間違っています）")
            st.stop()
            
        event_name = event_info.iloc[0]["イベント名"]
        event_date = event_info.iloc[0]["開催日"]
        
        st.subheader(f"📅 {event_name} （{event_date}）")
        st.write("以下のフォームに必要事項を入力して予約を行ってください。")
        
        # このイベント専用の座席データを取得
        event_seats = df_seats[df_seats["イベントID"] == target_event_id].copy()
        total_capacity = pd.to_numeric(event_seats["最大定員"], errors="coerce").fillna(0)
        current_booked = pd.to_numeric(event_seats["予約済人数"], errors="coerce").fillna(0)
        total_available = int((total_capacity - current_booked).sum())
        
        if total_available >= 50:
            status_text = "〇"
            status_color = "#28a745"
        elif total_available >= 30:
            status_text = "△"
            status_color = "#ffc107"
        elif total_available > 0:
            status_text = "残り僅か！"
            status_color = "#dc3545"
        else:
            status_text = "✖"
            status_color = "#6c757d"
            
        if "booking_step" not in st.session_state:
            st.session_state.booking_step = 1
            st.session_state.b_data = {}
            st.session_state.b_pin = ""

        if st.session_state.booking_step == 1:
            with st.form("reservation_form"):
                name = st.text_input("お名前代表（ハンドルネーム可）", value=st.session_state.b_data.get("name", ""))
                email = st.text_input("メールアドレス（もし来てないようでしたらもう一度ご確認お願いします）", value=st.session_state.b_data.get("email", ""))
                st.write("ご予約人数（最高は４名まで、それ以下でも相席になります）")
                col1, col2, col3 = st.columns([1, 1, 1])
                with col1:
                    num_men = st.number_input("男性（名）", min_value=0, max_value=4, value=st.session_state.b_data.get("num_men", 0), step=1)
                with col2:
                    num_women = st.number_input("女性（名）", min_value=0, max_value=4, value=st.session_state.b_data.get("num_women", 0), step=1)
                with col3:
                    st.write("")
                    st.write("")
                    st.markdown(f"**空き状況：<span style='color:{status_color}; font-size:22px;'>{status_text}</span>**", unsafe_allow_html=True)
                st.markdown("---")
                st.warning("⚠️ **入場料とは別で当日現金でのお支払いよろしくお願いします。**\n\n**当日のキャンセル料は100％後日ご請求させていただきますのでよろしくお願いいたします。**\n\n**※お席は全て相席となります。あらかじめご了承ください。**\n\n**※ご予約後、ご登録いただいたメールアドレスへご連絡の確認を取らさせていただきます。一定期間ご確認が取れない場合は、誠に勝手ながらご予約をキャンセル扱いとさせていただくことがございます。**")
                
                submitted = st.form_submit_button("確認画面へ進む", use_container_width=True)

            if submitted:
                num_people = num_men + num_women
                
                # 重複チェック（同じイベント、同じ名前、同じメアド）
                is_duplicate = False
                if not df_reservations.empty:
                    duplicates = df_reservations[
                        (df_reservations["イベントID"] == target_event_id) & 
                        (df_reservations["メールアドレス"] == email) & 
                        (df_reservations["ステータス"] != "キャンセル")
                    ]
                    if not duplicates.empty:
                        is_duplicate = True

                # 座席の空きがあるかどうかのチェック
                has_enough_seats = False
                for index, row in event_seats.iterrows():
                    available_space = int(row["最大定員"]) - int(row["予約済人数"])
                    if available_space >= num_people:
                        has_enough_seats = True
                        break

                if total_available <= 0:
                    st.error("申し訳ありません、このイベントは満席です。")
                elif not has_enough_seats:
                    st.error(f"申し訳ありません、現在 {num_people}名様 をご案内できる空き席がありません。人数を減らして再度お試しください。")
                elif not name or not email:
                    st.error("お名前とメールアドレスを入力してください。")
                elif num_people == 0:
                    st.error("人数を1名以上入力してください。")
                elif num_people > 4:
                    st.error("ご予約人数は合計4名以下にしてください。")
                elif is_duplicate:
                    st.session_state.b_data = {
                        "name": name,
                        "email": email,
                        "num_men": num_men,
                        "num_women": num_women,
                        "num_people": num_people,
                        "gender": f"男{num_men} 女{num_women}"
                    }
                    st.session_state.booking_step = 1.5
                    st.rerun()
                else:
                    st.session_state.b_data = {
                        "name": name,
                        "email": email,
                        "num_men": num_men,
                        "num_women": num_women,
                        "num_people": num_people,
                        "gender": f"男{num_men} 女{num_women}"
                    }
                    st.session_state.booking_step = 2
                    st.rerun()

        elif st.session_state.booking_step == 1.5:
            st.warning("⚠️ 注意：このメールアドレスはすでにこのイベントの予約が登録されています。")
            st.write("二重に予約されようとしていますが、よろしいですか？（例：ご友人・ご家族の分の追加予約など）")
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button("NO（やめる・戻る）", use_container_width=True):
                    st.session_state.booking_step = 1
                    st.rerun()
            with col2:
                if st.button("YES（追加で予約する）", type="primary", use_container_width=True):
                    st.session_state.booking_step = 2
                    st.rerun()

        elif st.session_state.booking_step == 2:
            st.subheader("予約内容の確認")
            d = st.session_state.b_data
            st.info(f"**お名前:** {d['name']} 様\n\n**メール:** {d['email']}\n\n**人数:** 男{d['num_men']}名 女{d['num_women']}名 （計{d['num_people']}名）")
            st.write(f"### 男{d['num_men']}名、女{d['num_women']}名 以下の人数でお間違えありませんか？")
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button("戻って修正する", use_container_width=True):
                    st.session_state.booking_step = 1
                    st.rerun()
            with col2:
                if st.button("この内容で確認コードを送信する", type="primary", use_container_width=True):
                    import random
                    pin = str(random.randint(1000, 9999))
                    st.session_state.b_pin = pin
                    success = send_pin_email(d["email"], d["name"], event_name, pin)
                    if success:
                        st.session_state.booking_step = 3
                        st.rerun()

        elif st.session_state.booking_step == 3:
            st.subheader("メールの確認")
            d = st.session_state.b_data
            st.success(f"{d['email']} 宛に4桁の確認コードを送信しました。")
            
            pin_input = st.text_input("メールに届いた4桁の数字を入力してください", max_chars=4)
            col1, col2 = st.columns(2)
            with col1:
                if st.button("最初に戻ってやり直す", use_container_width=True):
                    st.session_state.booking_step = 1
                    st.rerun()
            with col2:
                if st.button("予約を確定する", type="primary", use_container_width=True):
                    if pin_input == st.session_state.b_pin:
                        # 予約処理実行
                        assigned_seat = None
                        # 相席ロジック：空き枠がある席を上から探す
                        for index, row in event_seats.iterrows():
                            available_space = int(row["最大定員"]) - int(row["予約済人数"])
                            if available_space >= d['num_people']:
                                assigned_seat = row["座席番号"]
                                original_idx = event_seats.index[event_seats['座席番号'] == assigned_seat][0]
                                df_seats.at[original_idx, "予約済人数"] = int(row["予約済人数"]) + d['num_people']
                                break
                        
                        if assigned_seat is None:
                            st.error("申し訳ございません。手続き中に満席になってしまいました。人数を減らして再度お試しください。")
                            st.session_state.booking_step = 1
                        else:
                            event_res = df_reservations[df_reservations["イベントID"] == target_event_id]
                            if len(event_res) > 0:
                                new_id = int(pd.to_numeric(event_res['予約ID'], errors='coerce').fillna(0).max() + 1)
                            else:
                                new_id = 1
                            
                            new_res = pd.DataFrame([{
                                "イベントID": target_event_id,
                                "予約ID": new_id,
                                "お名前": d['name'],
                                "メールアドレス": d['email'],
                                "人数": d['num_people'],
                                "座席番号": assigned_seat,
                                "ステータス": "未受付",
                                "性別": d['gender']
                            }])
                            df_reservations = pd.concat([df_reservations, new_res], ignore_index=True)
                            
                            conn.update(worksheet="Seats", data=df_seats)
                            conn.update(worksheet="Reservations", data=df_reservations)
                            st.cache_data.clear()
                            
                            # QRコード生成
                            qr_data = f"EVENT:{target_event_id}_ID:{new_id}"
                            qr = qrcode.QRCode(version=1, box_size=10, border=5)
                            qr.add_data(qr_data)
                            qr.make(fit=True)
                            img = qr.make_image(fill_color="black", back_color="white")
                            
                            buf = io.BytesIO()
                            img.save(buf, format="PNG")
                            byte_im = buf.getvalue()
                            
                            send_qr_email(d['email'], d['name'], assigned_seat, new_id, event_name, byte_im, d['num_people'], d['gender'])
                            
                            st.session_state.b_assigned_seat = assigned_seat
                            st.session_state.b_new_id = new_id
                            st.session_state.b_qr_bytes = byte_im
                            st.session_state.booking_step = 4
                            st.rerun()
                    else:
                        st.error("確認コードが一致しません。もう一度メールをご確認ください。")

        elif st.session_state.booking_step == 4:
            new_id = st.session_state.b_new_id
            assigned_seat = st.session_state.b_assigned_seat
            byte_im = st.session_state.b_qr_bytes
            seat_display = assigned_seat if "席" in str(assigned_seat) else f"{assigned_seat}番席"
            st.success(f"ご予約ありがとうございました！\n\nご予約が確定しました！予約IDは {new_id} 番、割り当てられた席は {seat_display} です。")
            st.info("※ご登録いただいたメールアドレスにQRコードを送信しました。")
            st.image(byte_im, caption="チェックイン用QRコード（スクリーンショットでも利用可能です）")
            if st.button("新しく別の予約をする"):
                st.session_state.booking_step = 1
                st.rerun()
                    
    except Exception as e:
        st.error(f"データベースの読み込みに失敗しました。エラー詳細: {e}")

else:
    # ==========================================
    # 通常アクセス時：ポータル＆スタッフ管理画面
    # ==========================================
    page = st.sidebar.radio("メニュー", ["お客様向け：イベント一覧", "スタッフ向け：管理・受付"])

    if page == "お客様向け：イベント一覧":
        st.title("先行座席予約 ポータル")
        st.write("現在予約を受付中のイベント一覧です。ご希望のイベントを選択してください。")
        
        try:
            conn = st.connection("gsheets", type=GSheetsConnection)
            df_events, df_seats, df_reservations = get_data()
            active_events = df_events[df_events["ステータス"] == "受付中"]
            
            if active_events.empty:
                st.info("現在、予約可能なイベントはありません。")
            else:
                for _, event in active_events.iterrows():
                    e_id = event["イベントID"]
                    e_name = event["イベント名"]
                    e_date = event["開催日"]
                    
                    # 空き状況計算
                    e_seats = df_seats[df_seats["イベントID"] == e_id]
                    t_cap = pd.to_numeric(e_seats["最大定員"], errors="coerce").fillna(0)
                    t_book = pd.to_numeric(e_seats["予約済人数"], errors="coerce").fillna(0)
                    t_avail = int((t_cap - t_book).sum())
                    
                    if t_avail >= 50:
                        status = "〇"
                        color = "#28a745"
                    elif t_avail >= 30:
                        status = "△"
                        color = "#ffc107"
                    elif t_avail > 0:
                        status = "残り僅か！"
                        color = "#dc3545"
                    else:
                        status = "✖"
                        color = "#6c757d"
                    
                    with st.container():
                        st.markdown(f"### 📅 {e_name} ({e_date})")
                        st.markdown(f"**空き状況：<span style='color:{color}; font-size:20px;'>{status}</span>**", unsafe_allow_html=True)
                        st.markdown(f'<a href="?event_id={e_id}" target="_self"><button style="background-color:#007BFF; color:white; border:none; padding:10px 20px; border-radius:5px; cursor:pointer;">このイベントを予約する</button></a>', unsafe_allow_html=True)
                        st.markdown("---")
        except Exception as e:
            st.error(f"データベースの読み込みに失敗しました。エラー詳細: {e}")

    elif page == "スタッフ向け：管理・受付":
        st.title("イベント管理・受付ダッシュボード")
        tab1, tab2, tab3 = st.tabs(["📸 チェックイン受付", "⚙️ イベント作成・管理", "❌ 予約のキャンセル"])
        
        with tab1:
            st.subheader("予約受付（チェックイン）")
            
            # --- カメラで写真撮影して読み取り ---
            st.write("▼ カメラでQRコードを撮影するか、保存した画像をアップロードしてください")
            
            cam_mode = st.radio("読み取り方法を選択", ["📷 カメラで撮影する", "📁 画像ファイルを選択する"], horizontal=True)
            
            cam_image = None
            if cam_mode == "📷 カメラで撮影する":
                st.info("※カメラが真っ暗になる場合は、ブラウザの設定でカメラを「許可」にするか、右の「画像ファイルを選択する」をお試しください。")
                cam_image = st.camera_input("QRコードを枠に収めて撮影ボタンを押してください", label_visibility="collapsed")
            else:
                cam_image = st.file_uploader("QRコードの画像を選択してください", type=["png", "jpg", "jpeg"])
                
            if cam_image is not None:
                try:
                    import cv2
                    import numpy as np
                    from PIL import Image
                    image = Image.open(cam_image)
                    img_array = np.array(image.convert('RGB'))
                    img_bgr = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
                    detector = cv2.QRCodeDetector()
                    data, bbox, _ = detector.detectAndDecode(img_bgr)
                    
                    if data:
                        if st.session_state.get("qr_input_field") != data:
                            st.session_state["qr_input_field"] = data
                            st.session_state["auto_submit"] = True
                            st.rerun()
                    else:
                        st.error("❌ QRコードを認識できませんでした。もう少し近づけるか、ピントを合わせて再度撮影してください。")
                except Exception as e:
                    st.error(f"読み取りエラーが発生しました: {e}")

            st.markdown("---")
            qr_input = st.text_input("手動検索用：QRデータまたは予約ID（例: EVENT:xxx_ID:1）を入力", key="qr_input_field")
            
            manual_submit = st.button("手動で受付を行う", type="primary", use_container_width=True)
            auto_submit = st.session_state.get("auto_submit", False)
            
            if manual_submit or auto_submit:
                st.session_state["auto_submit"] = False
                
                if not qr_input:
                    st.error("データが入力されていません。")
                else:
                    try:
                        conn = st.connection("gsheets", type=GSheetsConnection)
                        df_events, df_seats, df_reservations = get_data()
                        
                        # QRデータ解析 "EVENT:xxx_ID:yyy"
                        qr_str = str(qr_input).strip()
                        if "EVENT:" in qr_str and "_ID:" in qr_str:
                            parts = qr_str.split("_ID:")
                            ev_id = parts[0].replace("EVENT:", "")
                            res_id_str = parts[1]
                        else:
                            st.error("QRコードの形式が不正です。")
                            st.stop()
                            
                        try:
                            res_id = int(res_id_str)
                        except ValueError:
                            st.error("無効なID形式です。")
                            st.stop()
                        
                        # 検索
                        df_reservations["予約ID"] = pd.to_numeric(df_reservations["予約ID"], errors="coerce").fillna(0)
                        match_idx = df_reservations.index[(df_reservations['イベントID'] == ev_id) & (df_reservations['予約ID'] == res_id)].tolist()
                        
                        if not match_idx:
                            st.error("予約データが見つかりません。")
                        else:
                            idx = match_idx[0]
                            status = df_reservations.at[idx, 'ステータス']
                            name = df_reservations.at[idx, 'お名前']
                            seat = df_reservations.at[idx, '座席番号']
                            
                            if status == "来店済み":
                                st.warning("⚠️ 既に受付済みのQRコード（お客様）です！")
                            elif status == "キャンセル":
                                st.error("❌ このQRコード（予約）は既にキャンセルされています！")
                            else:
                                df_reservations.at[idx, 'ステータス'] = "来店済み"
                                try:
                                    seat_display = int(float(seat))
                                except:
                                    seat_display = seat
                                    
                                conn.update(worksheet="Reservations", data=df_reservations)
                                st.cache_data.clear()
                                st.success(f"受付完了：{name}様 ➡️ {seat_display}番席へご案内してください")
                                
                                st.markdown("---")
                                if st.button("🔄 次の人の受付を行う（画面をリセット）", use_container_width=True):
                                    if "qrcode_scanner_widget" in st.session_state:
                                        del st.session_state["qrcode_scanner_widget"]
                                    if "qr_input_field" in st.session_state:
                                        del st.session_state["qr_input_field"]
                                    st.rerun()
                                
                    except Exception as e:
                        st.error(f"データベースの読み込みに失敗しました。エラー詳細: {e}")

        with tab2:
            st.subheader("新しいイベントの作成")
            new_ev_name = st.text_input("イベント名（例：7/18 ディナー営業）")
            new_ev_date = st.text_input("日付（例：2024年7月18日）")
            st.write("座席の準備（自動作成）")
            st.caption("イベントごとのレイアウトに合わせて、座席数を自由に調整できます。")
            num_shared = st.number_input("相席エリア（ソファ等）の最大定員（1グループで共有）", min_value=0, value=0, step=1)
            num_1_seats = st.number_input("1名席の数", min_value=0, value=0, step=1)
            num_2_seats = st.number_input("2名席の数", min_value=0, value=0, step=1)
            num_4_seats = st.number_input("4名席の数", min_value=0, value=0, step=1)
            num_6_seats = st.number_input("6名席の数", min_value=0, value=0, step=1)
            
            # --- 確認画面（プレビュー） ---
            total_seats = num_shared + (num_1_seats * 1) + (num_2_seats * 2) + (num_4_seats * 4) + (num_6_seats * 6)
            st.info(f"**【作成される座席のプレビュー】**\n\n"
                    f"・相席エリア（定員{num_shared}名）: 1つ\n"
                    f"・1名席: {num_1_seats}卓\n"
                    f"・2名席: {num_2_seats}卓\n"
                    f"・4名席: {num_4_seats}卓\n"
                    f"・6名席: {num_6_seats}卓\n\n"
                    f"**合計座席数（最大定員）: {total_seats}名**")
            
            submitted_ev = st.button("この内容でイベントを作成して公開する", type="primary")
            
            if submitted_ev:
                    if not new_ev_name:
                        st.error("イベント名を入力してください。")
                    else:
                        try:
                            conn = st.connection("gsheets", type=GSheetsConnection)
                            df_events, df_seats, df_reservations = get_data()
                            new_ev_id = "EV_" + str(uuid.uuid4())[:8]
                            
                            # 新規イベント追加
                            new_event = pd.DataFrame([{
                                "イベントID": new_ev_id,
                                "イベント名": new_ev_name,
                                "開催日": new_ev_date,
                                "ステータス": "受付中"
                            }])
                            df_events = pd.concat([df_events, new_event], ignore_index=True)
                            
                            # 新規座席追加
                            new_seats_list = []
                            seat_counter = 1
                            
                            # 相席エリア（1つの大きな席として扱う）
                            if num_shared > 0:
                                new_seats_list.append({"イベントID": new_ev_id, "座席番号": "相席・ソファエリア", "最大定員": num_shared, "予約済人数": 0})
                                
                            for i in range(num_1_seats):
                                new_seats_list.append({"イベントID": new_ev_id, "座席番号": f"S{seat_counter} (1名席)", "最大定員": 1, "予約済人数": 0})
                                seat_counter += 1
                            for i in range(num_2_seats):
                                new_seats_list.append({"イベントID": new_ev_id, "座席番号": f"T{seat_counter} (2名席)", "最大定員": 2, "予約済人数": 0})
                                seat_counter += 1
                            for i in range(num_4_seats):
                                new_seats_list.append({"イベントID": new_ev_id, "座席番号": f"T{seat_counter} (4名席)", "最大定員": 4, "予約済人数": 0})
                                seat_counter += 1
                            for i in range(num_6_seats):
                                new_seats_list.append({"イベントID": new_ev_id, "座席番号": f"T{seat_counter} (6名席)", "最大定員": 6, "予約済人数": 0})
                                seat_counter += 1
                                
                            if new_seats_list:
                                df_seats = pd.concat([df_seats, pd.DataFrame(new_seats_list)], ignore_index=True)
                            
                            conn.update(worksheet="Events", data=df_events)
                            conn.update(worksheet="Seats", data=df_seats)
                            st.cache_data.clear()
                            
                            st.success("イベントを作成しました！下部の「現在公開中のイベント管理」から確認できます。")
                        except Exception as e:
                            st.error(f"作成中にエラーが発生しました: {e}")
                            
            st.markdown("---")
            st.subheader("現在公開中のイベント管理")
            try:
                conn = st.connection("gsheets", type=GSheetsConnection)
                df_events, df_seats, df_reservations = get_data()
                active_events = df_events[df_events["ステータス"] == "受付中"]
                if not active_events.empty:
                    for _, ev in active_events.iterrows():
                        ev_id = ev["イベントID"]
                        with st.expander(f"⚙️ {ev['イベント名']} ({ev['開催日']}) の管理"):
                            st.write(f"**専用予約URL**: `?event_id={ev_id}`")
                            st.markdown(f'<a href="?event_id={ev_id}" target="_blank">専用予約画面を開く</a>', unsafe_allow_html=True)
                            
                            if st.button(f"このイベントを終了（アーカイブ）する", key=f"end_{ev_id}"):
                                original_idx = df_events.index[df_events['イベントID'] == ev_id][0]
                                df_events.at[original_idx, "ステータス"] = "終了"
                                conn.update(worksheet="Events", data=df_events)
                                st.cache_data.clear()
                                st.success("イベントを終了しました。再読み込みしてください。")
                            
                            st.write("---")
                            if st.button(f"🗑️ このイベントを完全に削除する", key=f"del_{ev_id}", type="primary"):
                                df_events = df_events[df_events['イベントID'] != ev_id]
                                df_seats = df_seats[df_seats['イベントID'] != ev_id]
                                df_reservations = df_reservations[df_reservations['イベントID'] != ev_id]
                                conn.update(worksheet="Events", data=df_events)
                                conn.update(worksheet="Seats", data=df_seats)
                                conn.update(worksheet="Reservations", data=df_reservations)
                                st.cache_data.clear()
                                st.success("イベントとその座席・予約データを完全に削除しました。再読み込みしてください。")
                else:
                    st.write("現在管理できる公開中イベントはありません。")
            except:
                pass

        with tab3:
            st.subheader("予約のキャンセル（座席の自動解放）")
            st.write("キャンセルされた予約を削除し、他のお客さんが予約できるように空き枠を復活させます。")
            
            try:
                conn = st.connection("gsheets", type=GSheetsConnection)
                df_events, df_seats, df_reservations = get_data()
                active_events = df_events[df_events["ステータス"] == "受付中"]
                
                if active_events.empty:
                    st.info("現在受付中のイベントはありません。")
                else:
                    event_options = {f"{row['イベント名']} ({row['開催日']})": row['イベントID'] for _, row in active_events.iterrows()}
                    selected_ev_name = st.selectbox("1. イベントを選択してください", list(event_options.keys()))
                    selected_ev_id = event_options[selected_ev_name]
                    
                    # キャンセル済みのものは除外してリストアップ
                    event_res = df_reservations[(df_reservations["イベントID"] == selected_ev_id) & (df_reservations["ステータス"] != "キャンセル")]
                    
                    if event_res.empty:
                        st.info("このイベントにはキャンセル可能な予約がありません。")
                    else:
                        st.write("---")
                        res_options = {}
                        for _, row in event_res.iterrows():
                            label = f"ID: {row['予約ID']} | {row['お名前']}様 | 計{row['人数']}名 | {row['座席番号']}"
                            res_options[label] = row['予約ID']
                            
                        selected_res_label = st.selectbox("2. キャンセルする予約を選択してください", list(res_options.keys()))
                        selected_res_id = res_options[selected_res_label]
                        
                        target_res = event_res[event_res["予約ID"] == selected_res_id].iloc[0]
                        target_seat = target_res["座席番号"]
                        target_people = int(target_res["人数"])
                        
                        st.warning(f"⚠️ 以下の予約をキャンセル扱いにし、{target_seat}の空き枠を {target_people}名分 復活させます。")
                        st.write(f"**{target_res['お名前']}様** （予約ID: {selected_res_id}）")
                        
                        if st.button("🗑️ この予約をキャンセルする", type="primary"):
                            seat_mask = (df_seats["イベントID"] == selected_ev_id) & (df_seats["座席番号"] == target_seat)
                            if seat_mask.any():
                                seat_idx = df_seats.index[seat_mask][0]
                                current_booked = int(df_seats.at[seat_idx, "予約済人数"])
                                new_booked = max(0, current_booked - target_people)
                                df_seats.at[seat_idx, "予約済人数"] = new_booked
                                conn.update(worksheet="Seats", data=df_seats)
                            
                            res_mask = (df_reservations["イベントID"] == selected_ev_id) & (df_reservations["予約ID"] == selected_res_id)
                            if res_mask.any():
                                res_idx = df_reservations.index[res_mask][0]
                                df_reservations.at[res_idx, "ステータス"] = "キャンセル"
                                conn.update(worksheet="Reservations", data=df_reservations)
                            
                            st.cache_data.clear()
                            st.success("✅ キャンセル処理が完了し、座席枠が復活しました！再読み込み等を行ってください。")
            except Exception as e:
                st.error(f"エラーが発生しました: {e}")

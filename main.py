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
            
        with st.form("reservation_form"):
            name = st.text_input("お名前代表（ハンドルネーム可）")
            email = st.text_input("メールアドレス（もし来てないようでしたらもう一度ご確認お願いします）")
            gender = st.radio("性別", ["男性", "女性", "回答しない"], horizontal=True)
            
            col1, col2 = st.columns([1, 1])
            with col1:
                num_people = st.number_input("ご予約人数（最高は４名まで、それ以上それ以下は相席になります）", min_value=1, max_value=4, value=1, step=1)
            with col2:
                st.write("")
                st.write("")
                st.markdown(f"**空き状況：<span style='color:{status_color}; font-size:22px;'>{status_text}</span>**", unsafe_allow_html=True)
                
            submitted = st.form_submit_button("予約する", use_container_width=True)

        if submitted:
            if total_available <= 0:
                st.error("申し訳ありません、このイベントは満席です。")
                st.stop()
            if not name or not email:
                st.error("お名前とメールアドレスを入力してください。")
            else:
                assigned_seat = None
                
                # 相席ロジック：空き枠がある席を上から探す
                for index, row in event_seats.iterrows():
                    available_space = int(row["最大定員"]) - int(row["予約済人数"])
                    if available_space >= num_people:
                        assigned_seat = row["座席番号"]
                        # 元のdf_seatsを更新する準備
                        original_idx = event_seats.index[event_seats['座席番号'] == assigned_seat][0]
                        df_seats.at[original_idx, "予約済人数"] = int(row["予約済人数"]) + num_people
                        break
                
                if assigned_seat is None:
                    st.error("満席です人数を減らしてご登録お願いいたします")
                else:
                    # 予約IDの生成
                    event_res = df_reservations[df_reservations["イベントID"] == target_event_id]
                    if len(event_res) > 0:
                        new_id = int(pd.to_numeric(event_res['予約ID'], errors='coerce').fillna(0).max() + 1)
                    else:
                        new_id = 1
                    
                    new_res = pd.DataFrame([{
                        "イベントID": target_event_id,
                        "予約ID": new_id,
                        "お名前": name,
                        "メールアドレス": email,
                        "人数": num_people,
                        "座席番号": assigned_seat,
                        "ステータス": "未受付",
                        "性別": gender
                    }])
                    df_reservations = pd.concat([df_reservations, new_res], ignore_index=True)
                    
                    # スプレッドシートを更新
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
                    
                    # メール送信
                    send_qr_email(email, name, assigned_seat, new_id, event_name, byte_im, num_people, gender)
                    
                    seat_display = assigned_seat if "席" in str(assigned_seat) else f"{assigned_seat}番席"
                    st.success(f"ご予約ありがとうございました！\n\nご予約が確定しました！予約IDは {new_id} 番、割り当てられた席は {seat_display} です。")
                    st.info("※ご登録いただいたメールアドレスにQRコードを送信しました。")
                    st.image(byte_im, caption="チェックイン用QRコード（スクリーンショットでも利用可能です）")
                    
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
        tab1, tab2 = st.tabs(["📸 チェックイン受付", "⚙️ イベント作成・管理"])
        
        with tab1:
            st.subheader("予約受付（チェックイン）")
            
            # --- カメラで自動読み取り ---
            st.write("▼ カメラでQRコードをかざしてください（自動で受付されます）")
            if st.checkbox("📸 カメラを起動する", value=True, key="camera_toggle"):
                st.info("※「learn how to allow access」と出る場合は、ブラウザのURL横にある🔒マークからカメラを「許可」に変更してください。")
                try:
                    from streamlit_qrcode_scanner import qrcode_scanner
                    qr_code = qrcode_scanner(key='qrcode_scanner_widget')
                    
                    if qr_code:
                        if st.session_state.get("qr_input_field") != qr_code:
                            st.session_state["qr_input_field"] = qr_code
                            st.session_state["auto_submit"] = True
                            st.rerun()
                except Exception as e:
                    pass

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
            num_2_seats = st.number_input("2名席の数", min_value=0, value=3, step=1)
            num_4_seats = st.number_input("4名席の数", min_value=0, value=2, step=1)
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

import os
import paho.mqtt.client as mqtt
import re

# ==========================================
# CẤU HÌNH MQTT (Đọc từ biến môi trường hoặc thay đổi tại đây)
# ==========================================
MQTT_BROKER = os.getenv("MQTT_BROKER", "aitogy.asia")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "device/DEMO_DEVICE/upload")
MQTT_USERNAME = os.getenv("MQTT_USERNAME", os.getenv("MQTT_USER", ""))
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")

# Hàm phân tích chuỗi GNGGA
def parse_gngga(data):
    # Định dạng chuẩn: $GNGGA,hhmmss.ss,llll.ll,a,yyyyy.yy,a,x,xx,x.x,x.x,M,x.x,M,x.x,xxxx*hh
    parts = data.split(',')
    if len(parts) >= 15:
        print("--- GNGGA (Dữ liệu định vị GNSS) ---")
        print(f"  Thời gian (UTC): {parts[1]}")
        print(f"  Vĩ độ: {parts[2]} {parts[3]}")
        print(f"  Kinh độ: {parts[4]} {parts[5]}")
        print(f"  Chất lượng tín hiệu: {parts[6]} (0=Không hợp lệ, 1=GPS fix, 2=DGPS, 4=RTK fixed, 5=RTK float)")
        print(f"  Số vệ tinh: {parts[7]}")
        print(f"  HDOP: {parts[8]}")
        print(f"  Độ cao so với mực nước biển: {parts[9]} {parts[10]}")
    else:
        print("  [Lỗi] Chuỗi GNGGA không đủ dữ liệu")

# Hàm phân tích chuỗi GNGST
def parse_gngst(data):
    # Định dạng chuẩn: $GNGST,hhmmss.ss,x.x,x.x,x.x,x.x,x.x,x.x,x.x*hh
    parts = data.split(',')
    if len(parts) >= 9:
        print("--- GNGST (Thống kê sai số định vị) ---")
        print(f"  Thời gian (UTC): {parts[1]}")
        print(f"  Sai số toàn phương (RMS): {parts[2]} m")
        print(f"  Sai số bán trục lớn (Semi-major): {parts[3]} m")
        print(f"  Sai số bán trục nhỏ (Semi-minor): {parts[4]} m")
        print(f"  Góc định hướng (Orientation): {parts[5]} độ")
        print(f"  Sai số Vĩ độ (Lat err): {parts[6]} m")
        print(f"  Sai số Kinh độ (Lon err): {parts[7]} m")
        print(f"  Sai số Độ cao (Alt err): {parts[8].split('*')[0]} m")
    else:
        print("  [Lỗi] Chuỗi GNGST không đủ dữ liệu")

# Hàm phân tích chuỗi AGRICA (UM980)
def parse_agrica(data):
    # Định dạng: #AGRICA,header_fields...;GNSS,data_fields...*CRC
    print("--- AGRICA (Tất cả các trường theo đúng ID trong tài liệu) ---")
    if ';' not in data:
        print("  [Lỗi] Chuỗi AGRICA không đúng định dạng (thiếu dấu ;)")
        return
        
    header_part, data_part = data.split(';', 1)
    
    print(f"  [ID 1] AGRIC header: {header_part}")
    
    # Loại bỏ checksum ở phần cuối của data_part
    data_part_clean = data_part.split('*')[0]
    parts = data_part_clean.split(',')
    
    agrica_fields = [
        "GNSS", "Chiều dài lệnh (length)", "Năm (Year)", "Tháng (Month)", "Ngày (Day)",
        "Giờ (Hour)", "Phút (Minute)", "Giây (Second)", "Trạng thái vị trí (Postype)",
        "Trạng thái góc hướng (Heading Status)", "Số vệ tinh GPS", "Số vệ tinh BDS", 
        "Số vệ tinh GLONASS", "Vector đường cơ sở Bắc (Baseline_N)", "Vector đường cơ sở Đông (Baseline_E)",
        "Vector đường cơ sở Lên (Baseline_U)", "Độ lệch chuẩn hướng Bắc", "Độ lệch chuẩn hướng Đông", 
        "Độ lệch chuẩn hướng Lên", "Góc hướng (Heading)", "Góc chúc ngẩng (Pitch)", "Góc xoay ngang (Roll)",
        "Tốc độ vô hướng (Speed)", "Vận tốc hướng Bắc", "Vận tốc hướng Đông", "Vận tốc hướng Lên",
        "Độ lệch chuẩn vận tốc Bắc", "Độ lệch chuẩn vận tốc Đông", "Độ lệch chuẩn vận tốc Lên", 
        "Vĩ độ rover (lat)", "Kinh độ rover (lon)", "Độ cao rover (alt)", "Hệ tọa độ ECEF_X", 
        "Hệ tọa độ ECEF_Y", "Hệ tọa độ ECEF_Z", "Độ lệch chuẩn vĩ độ", "Độ lệch chuẩn kinh độ",
        "Độ lệch chuẩn độ cao", "Độ lệch chuẩn ECEF_X", "Độ lệch chuẩn ECEF_Y", "Độ lệch chuẩn ECEF_Z", 
        "Vĩ độ trạm base (BASE_lat)", "Kinh độ trạm base (BASE_lon)", "Độ cao trạm base (BASE_alt)", 
        "Vĩ độ ăng-ten slave (SEC_lat)", "Kinh độ ăng-ten slave (SEC_lon)", "Độ cao ăng-ten slave (SEC_alt)",
        "Tuần GPS theo mili giây (GPS_WEEK_SECOND)", "Tuổi vi sai (Diffage)", "Hướng của vận tốc (Speed_Heading)", 
        "Undulation", "Dự phòng 1 (Remain_float_3)", "Dự phòng 2 (Remain_float_4)", "Số vệ tinh Galileo", 
        "Trạng thái tốc độ (Speed_Type)", "Dự phòng 3 (Remain_char_3)", "Dự phòng 4 (Remain_char_4)"
    ]

    postype_dict = {'0': '0 (Invalid)', '1': '1 (Single point)', '2': '2 (Pseudorange diff)', '4': '4 (Fixed)', '5': '5 (Float)', '7': '7 (Input fixed)'}
    heading_status_dict = {'0': '0 (Invalid)', '4': '4 (Fixed)', '5': '5 (Float)'}
    
    for i, part in enumerate(parts):
        doc_id = i + 2 # Do ID 1 là phần header
        field_name = agrica_fields[i] if i < len(agrica_fields) else f"Trường chưa xác định"
        
        # Chuyển đổi định dạng các trường đặc biệt
        if i == 8:
            part = postype_dict.get(part, part)
        elif i == 9:
            part = heading_status_dict.get(part, part)
            
        print(f"  [ID {doc_id}] {field_name}: {part}")

    # Tính toán lại thời gian tổng hợp cho dễ nhìn
    if len(parts) > 7:
        try:
            print(f"  --> [Thời gian tổng hợp (UTC)]: 20{parts[2]}-{parts[3].zfill(2)}-{parts[4].zfill(2)} {parts[5].zfill(2)}:{parts[6].zfill(2)}:{parts[7].zfill(2)}")
        except Exception:
            pass

# Callback khi kết nối thành công
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"Kết nối thành công tới broker {MQTT_BROKER}!")
        client.subscribe(MQTT_TOPIC)
        print(f"Đang chờ dữ liệu từ topic: '{MQTT_TOPIC}'...\n")
    else:
        print(f"Kết nối thất bại với mã lỗi {rc}")

# Biến toàn cục để ghép chuỗi đứt đoạn
agrica_buffer = ""

# Callback khi nhận được tin nhắn
def on_message(client, userdata, msg):
    global agrica_buffer
    try:
        # Giải mã chuỗi nhận được
        payload = msg.payload.decode('utf-8').strip()
        print(f"\n[{msg.topic}] Payload thô: {payload}")
        
        # Nếu thiết bị gửi nhiều câu NMEA trên cùng 1 payload (tách bằng \n hoặc \r\n)
        sentences = payload.replace('\r', '').split('\n')
        
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
                
            # Phân loại chuỗi và xử lý ghép chuỗi
            if "GNGGA" in sentence:
                parse_gngga(sentence)
                agrica_buffer = "" # Xóa buffer nếu có bản tin khác xen ngang
            elif "GNGST" in sentence:
                parse_gngst(sentence)
                agrica_buffer = ""
            elif "AGRICA" in sentence:
                agrica_buffer = sentence
                # Nếu chuỗi AGRICA này đã đầy đủ (có dấu * và 8 ký tự hex sau *) thì xử lý luôn
                if re.search(r'\*[0-9a-fA-F]{8}', agrica_buffer):
                    parse_agrica(agrica_buffer)
                    agrica_buffer = ""
            elif agrica_buffer:
                # Nếu buffer đang có dữ liệu dang dở, nối trực tiếp phần vừa nhận vào
                agrica_buffer += sentence
                # Kiểm tra xem đã nhận được ký tự kết thúc (*) và 8 mã hex chưa
                if re.search(r'\*[0-9a-fA-F]{8}', agrica_buffer):
                    print(f"\n  => [ĐÃ GHÉP CHUỖI] Độ dài tổng: {len(agrica_buffer)} ký tự")
                    parse_agrica(agrica_buffer)
                    agrica_buffer = ""
    except Exception as e:
        print(f"Lỗi khi xử lý tin nhắn: {e}")

# Khởi tạo client MQTT
client = mqtt.Client()

# Thiết lập user/pass nếu có
if MQTT_USERNAME and MQTT_PASSWORD:
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

client.on_connect = on_connect
client.on_message = on_message

try:
    print("Đang khởi tạo kết nối tới MQTT Broker...")
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    # Lặp vô hạn để duy trì kết nối và nhận message
    client.loop_forever()
except KeyboardInterrupt:
    print("\nĐã ngắt kết nối (do người dùng dừng).")
    client.disconnect()
except Exception as e:
    print(f"Có lỗi xảy ra khi kết nối: {e}")

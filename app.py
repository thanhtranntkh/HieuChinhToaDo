import streamlit as st
import pandas as pd
import numpy as np
import pyproj
import folium
from folium import plugins
from streamlit_folium import st_folium
import io

# Tối ưu hóa cấu hình giao diện Streamlit
st.set_page_config(layout="wide", page_title="Hiệu Chỉnh Tọa Độ VN-2000 Pro")

# --- CSS TÙY CHỈNH GIAO DIỆN ---
st.markdown("""
    <style>
    .stDataFrame { width: 100%; }
    .alert-box {
        background-color: #fff3cd;
        border-left: 5px solid #ffc107;
        padding: 10px;
        border-radius: 4px;
        margin-bottom: 10px;
        color: #856404;
        font-size: 14px;
    }
    .success-box {
        background-color: #d4edda;
        border-left: 5px solid #28a745;
        padding: 10px;
        border-radius: 4px;
        margin-bottom: 10px;
        color: #155724;
        font-size: 14px;
    }
    .info-box {
        background-color: #e6f3ff;
        border-left: 5px solid #0066cc;
        padding: 10px;
        border-radius: 4px;
        margin-bottom: 10px;
        color: #004080;
        font-size: 14px;
    }
    </style>
""", unsafe_allow_html=True)

st.title("🌐 Công Cụ Hiệu Chỉnh & Tự Động Sắp Xếp Tọa Độ VN-2000")
st.markdown("Hỗ trợ click chọn mốc trực tiếp trên bản đồ, tự động sắp xếp lại lý trình tuyến để khắc phục triệt để đứt đoạn.")

# --- 1. CẤU HÌNH HỆ TỌA ĐỘ VN-2000 ---
@st.cache_resource
def get_vn2000_crs(kinh_tuyen_truc, mui=3):
    k_factor = 0.9999 if mui == 3 else 0.9996
    proj4_str = (
        f"+proj=tmerc +lat_0=0 +lon_0={kinh_tuyen_truc} +k={k_factor} "
        f"+x_0=500000 +y_0=0 +ellps=WGS84 "
        f"+towgs84=-191.90441429,-39.30318279,-111.45032835,0.00928836,0.01975479,-0.00427372,0.252906278 "
        f"+units=m +no_defs"
    )
    return pyproj.CRS(proj4_str)

def convert_to_wgs84_vectorized(x_arr, y_arr, kinh_tuyen_truc):
    wgs84 = pyproj.CRS('EPSG:4326')
    vn2000 = get_vn2000_crs(kinh_tuyen_truc)
    transformer = pyproj.Transformer.from_crs(vn2000, wgs84, always_xy=True)
    lons, lats = transformer.transform(y_arr, x_arr)
    return lats, lons

# --- 2. THUẬT TOÁN PHÁT HIỆN ĐỨT ĐOẠN ---
def analyze_data(df, kinh_tuyen_truc):
    df = df.copy()
    df['Cảnh báo'] = ""
    
    dup_mask = df.duplicated(subset=['X', 'Y'], keep=False)
    df.loc[dup_mask, 'Cảnh báo'] += "⚠️ Lặp tọa độ! "

    swap_mask = df['X'] < df['Y']
    df.loc[swap_mask, 'Cảnh báo'] += "⚠️ Đảo trục X-Y! "

    x_vals = df['X'].to_numpy()
    y_vals = df['Y'].to_numpy()
    
    dx = np.diff(x_vals, prepend=x_vals[0])
    dy = np.diff(y_vals, prepend=y_vals[0])
    distances = np.sqrt(dx**2 + dy**2)
    distances[0] = 0.0
    df['Khoảng cách (m)'] = np.round(distances, 2)
    
    broken_segments = []
    for i in range(1, len(df)):
        dist = distances[i]
        if dist > 200: 
            df.at[i, 'Cảnh báo'] += f"🚨 Đứt đoạn ({dist}m)! "
            broken_segments.append({'from_idx': i-1, 'to_idx': i, 'distance': dist})
        elif 0 < dist < 30:
            df.at[i, 'Cảnh báo'] += f"⚠️ Quá gần ({dist}m). "
            
    return df, broken_segments

# --- 3. THANH BÊN (SIDEBAR) ---
with st.sidebar:
    st.header("⚙️ Thông số đầu vào")
    uploaded_file = st.file_uploader('Tải file Excel tọa độ (.xlsx)', type=['xlsx'])
    kinh_tuyen_truc = st.number_input("Kinh tuyến trục (VD: 108.25)", value=108.25, format="%.2f")
    loai_du_lieu = st.radio("Loại bản vẽ:", ["Tim tuyến (Polyline)", "Ranh GPMB (Polygon)"])
    noi_dau_cuoi = st.checkbox("🔗 Tự động nối điểm đầu và cuối", value=False)

# --- 4. XỬ LÝ DỮ LIỆU & GIAO DIỆN CHÍNH ---
if uploaded_file:
    try:
        raw_df = pd.read_excel(uploaded_file)
    except Exception as e:
        st.error(f"Lỗi đọc file Excel: {e}")
        st.stop()
    
    if 'X' not in raw_df.columns or 'Y' not in raw_df.columns:
        st.error("File Excel bắt buộc phải có 2 cột 'X' và 'Y'.")
    else:
        if 'df_current' not in st.session_state or st.session_state.get('file_uploaded_name') != uploaded_file.name:
            st.session_state['df_current'] = raw_df.copy()
            st.session_state['file_uploaded_name'] = uploaded_file.name
            st.session_state['selected_point_a'] = None
            st.session_state['selected_point_b'] = None

        current_df = st.session_state['df_current'].copy()
        current_df.insert(0, 'STT', range(1, len(current_df) + 1))

        name_col = next((col for col in current_df.columns if any(k in col.lower() for k in ['hiệu', 'tên', 'mã', 'số', 'id'])), None)

        df_analyzed, broken_segments = analyze_data(current_df, kinh_tuyen_truc)
        
        col_map, col_data = st.columns([3, 1.3])
        
        lats, lons = convert_to_wgs84_vectorized(df_analyzed['X'].to_numpy(), df_analyzed['Y'].to_numpy(), kinh_tuyen_truc)
        valid_mask = ~np.isnan(lats) & ~np.isnan(lons)
        
        lat_lons = list(zip(lats[valid_mask], lons[valid_mask]))
        valid_indices = np.where(valid_mask)[0]

        if noi_dau_cuoi and len(lat_lons) > 2:
            lat_lons.append(lat_lons[0])

        with col_map:
            st.subheader("🗺️ Bản đồ tương tác trực quan")
            st.markdown("""
            <div class="info-box">
                👉 <strong>Hướng dẫn:</strong> Click trực tiếp vào các mốc trên bản đồ để chọn làm <b>Mốc A (Đứng trước)</b> hoặc <b>Mốc B (Cần nối/dời)</b>.
            </div>
            """, unsafe_allow_html=True)

            if lat_lons:
                center_lat = np.mean(lats[valid_mask])
                center_lon = np.mean(lons[valid_mask])
                
                m = folium.Map(location=[center_lat, center_lon], zoom_start=17, max_zoom=22)
                folium.TileLayer('https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google', name='Google Satellite').add_to(m)
                
                plugins.MeasureControl(position='topleft', primary_length_unit='meters').add_to(m)

                # Vẽ các mốc điểm
                for i, coord in enumerate(lat_lons[:-1] if noi_dau_cuoi and len(lat_lons) > 2 else lat_lons):
                    idx_orig = valid_indices[i]
                    warning_text = str(df_analyzed.iloc[idx_orig]['Cảnh báo'])
                    stt_val = int(df_analyzed.iloc[idx_orig]['STT'])
                    point_label = str(df_analyzed.iloc[idx_orig][name_col]) if name_col else f"STT {stt_val}"

                    # Đổi màu marker nếu được chọn làm A hoặc B
                    if st.session_state.get('selected_point_a') == stt_val:
                        color = 'green'  # Mốc A màu xanh lá
                        tooltip_extra = " [ĐÃ CHỌN LÀM MỐC A]"
                    elif st.session_state.get('selected_point_b') == stt_val:
                        color = 'orange' # Mốc B màu cam
                        tooltip_extra = " [ĐÃ CHỌN LÀM MỐC B]"
                    else:
                        color = 'red' if len(warning_text.strip()) > 0 else 'blue'
                        tooltip_extra = ""

                    folium.CircleMarker(
                        location=coord, radius=8, color=color, fill=True, fill_color=color, fill_opacity=0.8, weight=2,
                        popup=f"STT: {stt_val} | Tên: {point_label}",
                        tooltip=f"Mốc: {point_label} (STT {stt_val}){tooltip_extra} | {warning_text}"
                    ).add_to(m)

                # Vẽ tuyến chính
                if loai_du_lieu == "Tim tuyến (Polyline)":
                    folium.PolyLine(lat_lons, color="yellow", weight=4, opacity=0.7).add_to(m)
                else:
                    folium.Polygon(lat_lons, color="orange", fill=True, fill_opacity=0.3, weight=3).add_to(m)

                # Nhận diện object được click trên bản đồ
                map_data = st_folium(m, use_container_width=True, height=600, returned_objects=["last_object_clicked"])
                
                # Xử lý khi user click vào một mốc trên bản đồ
                if map_data and map_data.get("last_object_clicked"):
                    clicked_lat = map_data["last_object_clicked"]["lat"]
                    clicked_lon = map_data["last_object_clicked"]["lng"]
                    
                    # Tìm mốc gần nhất với điểm vừa click
                    dists = np.sqrt((lats[valid_mask] - clicked_lat)**2 + (lons[valid_mask] - clicked_lon)**2)
                    closest_idx_in_valid = np.argmin(dists)
                    orig_idx = valid_indices[closest_idx_in_valid]
                    clicked_stt = int(df_analyzed.iloc[orig_idx]['STT'])
                    
                    # Gán lần lượt vào A hoặc B
                    if st.session_state.get('selected_point_a') is None:
                        st.session_state['selected_point_a'] = clicked_stt
                        st.rerun()
                    elif st.session_state.get('selected_point_b') is None and clicked_stt != st.session_state['selected_point_a']:
                        st.session_state['selected_point_b'] = clicked_stt
                        st.rerun()
                
        with col_data:
            st.subheader("📝 Công cụ Hiệu chỉnh & Sắp xếp")
            
            if broken_segments:
                st.markdown(f"""
                <div class="alert-box">
                    <strong>🚨 PHÁT HIỆN {len(broken_segments)} ĐOẠN ĐỨT ĐOẠN!</strong>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown("""
                <div class="success-box">
                    <strong>✅ Tuyến liền mạch!</strong>
                </div>
                """, unsafe_allow_html=True)

            # --- KHUNG HIỂN THỊ MỐC ĐÃ CHỌN TRÊN BẢN ĐỒ ---
            st.markdown("---")
            st.write("🎯 **Trạng thái chọn mốc tương tác:**")
            col_a_disp, col_b_disp = st.columns(2)
            
            with col_a_disp:
                pt_a_val = st.session_state.get('selected_point_a')
                st.metric("Mốc A (Trước)", f"STT {pt_a_val}" if pt_a_val else "Chưa chọn")
            with col_b_disp:
                pt_b_val = st.session_state.get('selected_point_b')
                st.metric("Mốc B (Sau)", f"STT {pt_b_val}" if pt_b_val else "Chưa chọn")

            if st.button("🔄 Đặt lại lựa chọn A & B", use_container_width=True):
                st.session_state['selected_point_a'] = None
                st.session_state['selected_point_b'] = None
                st.rerun()

            # --- CÔNG CỤ SẮP XẾP LẠI THỨ TỰ MỐC LIỀN MẠCH ---
            with st.expander("🚀 Thực hiện Sắp xếp lại lý trình tuyến", expanded=True):
                st.caption("Sau khi chọn xong Mốc A và Mốc B, bấm nút dưới để hệ thống tự động dời Mốc B nằm ngay sau Mốc A.")
                
                # Cho phép chọn thủ công qua dropdown nếu không muốn click bản đồ
                choices = []
                for idx, row in df_analyzed.iterrows():
                    lbl = f"STT {row['STT']}" + (f" - {row[name_col]}" if name_col and pd.notna(row[name_col]) else "")
                    choices.append((row['STT'], lbl))
                
                stt_options = [item[0] for item in choices]
                format_func = lambda x: next((item[1] for item in choices if item[0] == x), str(x)) if x else "-- Chọn mốc --"

                manual_a = st.selectbox("Hoặc chọn mốc A:", options=[None] + stt_options, format_func=format_func, index=0 if not st.session_state.get('selected_point_a') else stt_options.index(st.session_state.get('selected_point_a'))+1)
                manual_b = st.selectbox("Hoặc chọn mốc B:", options=[None] + stt_options, format_func=format_func, index=0 if not st.session_state.get('selected_point_b') else stt_options.index(st.session_state.get('selected_point_b'))+1)
                
                # Đồng bộ vào session state nếu chọn thủ công
                if manual_a: st.session_state['selected_point_a'] = manual_a
                if manual_b: st.session_state['selected_point_b'] = manual_b

                if st.button("✨ Xác nhận Dời & Sắp xếp tuyến", type="primary", use_container_width=True):
                    pa = st.session_state.get('selected_point_a')
                    pb = st.session_state.get('selected_point_b')
                    if pa and pb:
                        if pa == pb:
                            st.warning("Mốc A và mốc B phải là hai mốc khác nhau!")
                        else:
                            current_raw = st.session_state['df_current'].copy()
                            idx_a = pa - 1
                            idx_b = pb - 1
                            
                            if 0 <= idx_a < len(current_raw) and 0 <= idx_b < len(current_raw):
                                row_b = current_raw.iloc[idx_b:idx_b+1]
                                current_raw = current_raw.drop(index=idx_b).reset_index(drop=True)
                                
                                new_idx_a = pa - 1 if idx_b > idx_a else pa
                                
                                part1 = current_raw.iloc[:new_idx_a]
                                part2 = current_raw.iloc[new_idx_a:]
                                
                                st.session_state['df_current'] = pd.concat([part1, row_b, part2]).reset_index(drop=True)
                                st.session_state['selected_point_a'] = None
                                st.session_state['selected_point_b'] = None
                                st.success(f"Đã tự động sắp xếp thành công! Mốc B (STT {pb}) đã được dời lên liền sau Mốc A (STT {pa}).")
                                st.rerun()
                    else:
                        st.warning("Vui lòng chọn đầy đủ Mốc A và Mốc B trên bản đồ hoặc qua danh sách.")

            # --- CÔNG CỤ XÓA MỐC LỖI ---
            with st.expander("🗑️ Xóa điểm mốc lỗi / đoạn thừa", expanded=False):
                rows_to_delete = st.multiselect("Chọn STT các mốc cần xóa khỏi tuyến:", options=list(df_analyzed['STT']))
                if st.button("🔥 Xóa các mốc đã chọn"):
                    if rows_to_delete:
                        orig_indices_to_drop = df_analyzed[df_analyzed['STT'].isin(rows_to_delete)].index - 1
                        st.session_state['df_current'] = st.session_state['df_current'].drop(index=orig_indices_to_drop).reset_index(drop=True)
                        st.success("Đã xóa các mốc được chọn!")
                        st.rerun()

            # BẢNG DỮ LIỆU EXCEL TRỰC TUYẾN
            with st.container(height=240):
                edited_df = st.data_editor(
                    df_display, 
                    num_rows="dynamic", 
                    use_container_width=True,
                    disabled=["STT", "Khoảng cách (m)"]
                )
            
            # XUẤT FILE SAU KHI HIỆU CHỈNH VÀ SẮP XẾP
            st.markdown("---")
            output = io.BytesIO()
            export_df = edited_df.drop(columns=['STT', 'Khoảng cách (m)', 'Cảnh báo'], errors='ignore')
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                export_df.to_excel(writer, index=False)
                
            st.download_button(
                label="💾 Lưu & Xuất File Excel VN2000 Hoàn Chỉnh",
                data=output.getvalue(),
                file_name="Hieu_Chinh_vi_tri_toa_do_VN200_HoanThien.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
                use_container_width=True
            )
else:
    st.info("Vui lòng tải lên file Excel chứa tọa độ để bắt đầu sử dụng công cụ.")

import streamlit as st
import pandas as pd
import numpy as np
import pyproj
import folium
from folium import plugins
from streamlit_folium import st_folium
import io
from shapely.geometry import Point, Polygon

# Cấu hình giao diện Web tràn viền tối đa
st.set_page_config(layout="wide", page_title="Hiệu Chỉnh Tọa Độ VN-2000")

# --- CSS TÙY CHỈNH GIAO DIỆN ---
st.markdown("""
    <style>
    .stDataFrame { width: 100%; }
    .selected-point-box {
        background-color: #e6f3ff;
        border-left: 5px solid #0066cc;
        padding: 15px;
        border-radius: 5px;
        margin-bottom: 15px;
    }
    .alert-box {
        background-color: #fff3cd;
        border-left: 5px solid #ffc107;
        padding: 12px;
        border-radius: 4px;
        margin-bottom: 15px;
        color: #856404;
    }
    </style>
""", unsafe_allow_html=True)

st.title("🌐 Công Cụ Hiệu Chỉnh Vị Trí Toạ Độ VN-2000")
st.markdown("Xử lý chuyên dụng cho file **Hieu Chỉnh vị trí toa do VN200 cho phù hợp** (Tích hợp Cảnh báo đứt đoạn & Nối điểm tùy chỉnh)")

# --- 1. CẤU HÌNH HỆ TỌA ĐỘ (THEO QĐ 05/2007/QĐ-BTNMT) ---
def get_vn2000_crs(kinh_tuyen_truc, mui=3):
    k_factor = 0.9999 if mui == 3 else 0.9996
    proj4_str = (
        f"+proj=tmerc +lat_0=0 +lon_0={kinh_tuyen_truc} +k={k_factor} "
        f"+x_0=500000 +y_0=0 +ellps=WGS84 "
        f"+towgs84=-191.90441429,-39.30318279,-111.45032835,0.00928836,0.01975479,-0.00427372,0.252906278 "
        f"+units=m +no_defs"
    )
    return pyproj.CRS(proj4_str)

def convert_to_wgs84(x, y, kinh_tuyen_truc):
    wgs84 = pyproj.CRS('EPSG:4326')
    vn2000 = get_vn2000_crs(kinh_tuyen_truc)
    transformer = pyproj.Transformer.from_crs(vn2000, wgs84, always_xy=True)
    lon, lat = transformer.transform(y, x) 
    return lat, lon

# --- 2. THUẬT TOÁN PHÁT HIỆN ĐỨT ĐOẠN & LỖI HÌNH HỌC ---
def analyze_data(df, kinh_tuyen_truc):
    df['Cảnh báo'] = ""
    
    # Phát hiện mốc lặp
    dup_mask = df.duplicated(subset=['X', 'Y'], keep=False)
    df.loc[dup_mask, 'Cảnh báo'] += "⚠️ Lặp tọa độ! "

    # Kiểm tra đảo trục X-Y
    swap_mask = df['X'] < df['Y']
    df.loc[swap_mask, 'Cảnh báo'] += "⚠️ Đảo trục X-Y! "

    distances = [0.0]
    broken_segments = []
    
    for i in range(1, len(df)):
        dx = df.iloc[i]['X'] - df.iloc[i-1]['X']
        dy = df.iloc[i]['Y'] - df.iloc[i-1]['Y']
        dist = np.sqrt(dx**2 + dy**2)
        distances.append(round(dist, 2))
        
        # Ngưỡng phát hiện đứt đoạn: Khoảng cách giữa 2 mốc liên tiếp quá lớn (> 200m đối với tim tuyến thông thường)
        if dist > 200:
            df.at[i, 'Cảnh báo'] += f"🚨 Đứt đoạn hình học ({dist}m)! "
            broken_segments.append((i, dist))
        elif dist < 30 and dist > 0:
            df.at[i, 'Cảnh báo'] += f"⚠️ Quá gần ({dist}m). "
            
    df['Khoảng cách (m)'] = distances
    return df, broken_segments

# --- 3. THANH BÊN (SIDEBAR) ---
with st.sidebar:
    st.header("⚙️ Thông số đầu vào")
    uploaded_file = st.file_uploader('Tải file "Hieu Chỉnh vị trí toa do VN200 cho phù hợp .xlsx"', type=['xlsx'])
    kinh_tuyen_truc = st.number_input("Kinh tuyến trục (VD: 108.25)", value=108.25, format="%.2f")
    loai_du_lieu = st.radio("Loại bản vẽ:", ["Tim tuyến (Polyline)", "Ranh GPMB (Polygon)"])
    noi_dau_cuoi = st.checkbox("🔗 Tự động nối điểm đầu và điểm cuối (Khép kín ranh)", value=False)

# --- 4. GIAO DIỆN CHÍNH ---
if uploaded_file:
    raw_df = pd.read_excel(uploaded_file)
    
    if 'X' not in raw_df.columns or 'Y' not in raw_df.columns:
        st.error("File phải có cột 'X' và 'Y'.")
    else:
        if 'df_current' not in st.session_state or st.session_state.get('file_uploaded_name') != uploaded_file.name:
            st.session_state['df_current'] = raw_df.copy()
            st.session_state['file_uploaded_name'] = uploaded_file.name

        current_df = st.session_state['df_current'].copy()
        current_df.insert(0, 'STT', range(1, len(current_df) + 1))

        df_analyzed, broken_segments = analyze_data(current_df, kinh_tuyen_truc)
        
        col_map, col_data = st.columns([3, 1.2])
        
        # --- HIỂN THỊ THÔNG BÁO ĐỨT ĐOẠN NẾU PHÁT HIỆN ---
        with col_data:
            if broken_segments:
                st.markdown(f"""
                <div class="alert-box">
                    <strong>🚨 CẢNH BÁO ĐỨT ĐOẠN HÌNH HỌC!</strong><br>
                    Phát hiện {len(broken_segments)} vị trí đứt đoạn khoảng cách lớn trên tuyến. Yêu cầu chọn cặp mốc để kết nối lại cho đúng thống nhất.
                </div>
                """, unsafe_allow_html=True)

        lat_lons = []
        valid_indices = []
        for idx, row in df_analyzed.iterrows():
            try:
                lat, lon = convert_to_wgs84(row['X'], row['Y'], kinh_tuyen_truc)
                if not np.isnan(lat) and not np.isnan(lon):
                    lat_lons.append([lat, lon])
                    valid_indices.append(idx)
            except:
                pass
        
        if noi_dau_cuoi and len(lat_lons) > 2:
            lat_lons.append(lat_lons[0])

        with col_map:
            st.subheader("🗺️ Bản đồ tương tác & Khắc phục đứt đoạn")
            st.caption("💡 Sử dụng công cụ nối tùy chỉnh bên phải để kết nối mốc 948 với 639 hoặc các điểm đứt đoạn.")
            
            if lat_lons:
                center_lat = sum([pt[0] for pt in lat_lons]) / len(lat_lons)
                center_lon = sum([pt[1] for pt in lat_lons]) / len(lat_lons)
                
                m = folium.Map(location=[center_lat, center_lon], zoom_start=18, max_zoom=22)
                folium.TileLayer('https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google', name='Google Satellite').add_to(m)
                
                draw = plugins.Draw(
                    export=False,
                    draw_options={'polyline': False, 'polygon': True, 'rectangle': True, 'circle': False, 'marker': False, 'circlemarker': False},
                    edit_options={'edit': False}
                )
                draw.add_to(m)
                plugins.MeasureControl(position='topleft', primary_length_unit='meters').add_to(m)

                name_col = next((col for col in df_analyzed.columns if 'hiệu' in col.lower() or 'tên' in col.lower() or 'mã' in col.lower() or 'số' in col.lower()), None)

                for i, coord in enumerate(lat_lons[:-1] if noi_dau_cuoi and len(lat_lons) > 2 else lat_lons):
                    idx_in_df = valid_indices[i] if i < len(valid_indices) else valid_indices[0]
                    warning_text = str(df_analyzed.loc[df_analyzed.index == idx_in_df, 'Cảnh báo'].values[0])
                    is_warning = len(warning_text.strip()) > 0
                    color = 'red' if is_warning else 'blue'
                    
                    stt_val = df_analyzed.loc[df_analyzed.index == idx_in_df, 'STT'].values[0]
                    point_label = str(df_analyzed.loc[df_analyzed.index == idx_in_df, name_col].values[0]) if name_col else f"STT {stt_val}"

                    folium.CircleMarker(
                        location=coord, radius=8, color=color, fill=True, weight=3,
                        tooltip=f"Mốc: {point_label} (STT {stt_val}) | Lỗi: {warning_text}"
                    ).add_to(m)

                # Vẽ đường tuyến chính
                if loai_du_lieu == "Tim tuyến (Polyline)":
                    folium.PolyLine(lat_lons, color="yellow", weight=4, opacity=0.6).add_to(m)
                else:
                    folium.Polygon(lat_lons, color="orange", fill=True, fill_opacity=0.3, weight=3).add_to(m)

                # --- VẼ ĐƯỜNG NỐI TÙY CHỈNH (MÀU CYAN ĐẬM - NHƯ YÊU CẦU NỐI 948 VỚI 639) ---
                if 'custom_connections' not in st.session_state:
                    st.session_state['custom_connections'] = []

                for pair in st.session_state['custom_connections']:
                    stt_1, stt_2 = pair
                    row_1 = df_analyzed[df_analyzed['STT'] == stt_1]
                    row_2 = df_analyzed[df_analyzed['STT'] == stt_2]
                    if not row_1.empty and not row_2.empty:
                        try:
                            lat1, lon1 = convert_to_wgs84(row_1.iloc[0]['X'], row_1.iloc[0]['Y'], kinh_tuyen_truc)
                            lat2, lon2 = convert_to_wgs84(row_2.iloc[0]['X'], row_2.iloc[0]['Y'], kinh_tuyen_truc)
                            folium.PolyLine([[lat1, lon1], [lat2, lon2]], color="cyan", weight=6, tooltip=f"Nối chuẩn: STT {stt_1} ↔ STT {stt_2}").add_to(m)
                        except:
                            pass

                map_data = st_folium(m, use_container_width=True, height=700, returned_objects=["last_active_drawing", "last_object_clicked"])
                
        with col_data:
            st.subheader("📝 Hiệu chỉnh & Kết nối")
            
            search_query = st.text_input("🔍 Tìm kiếm mốc (STT, Tên hoặc X/Y):", "")
            df_display = df_analyzed.copy()
            if search_query:
                mask = df_display.astype(str).apply(lambda col: col.str.contains(search_query, case=False, na=False)).any(axis=1)
                df_display = df_display[mask]

            # --- CÔNG CỤ CHỌN MỐC NỐI TÙY CHỈNH (VÍ DỤ: 948 NỐI 639) ---
            with st.expander("🔗 Công cụ Kết nối mốc tùy chỉnh", expanded=True):
                st.caption("Chọn 2 mốc bất kỳ (ví dụ mốc 948 và 639) để khắc phục đoạn đứt đoạn.")
                all_stts = list(df_analyzed['STT'])
                pt_a = st.selectbox("Chọn mốc bắt đầu (A):", options=[None] + all_stts, format_func=lambda x: f"STT {x}" if x is not None else "-- Chọn mốc A --")
                pt_b = st.selectbox("Chọn mốc kết thúc (B):", options=[None] + all_stts, format_func=lambda x: f"STT {x}" if x is not None else "-- Chọn mốc B --")
                
                col_btn1, col_btn2 = st.columns(2)
                with col_btn1:
                    if st.button("➕ Thêm đường nối"):
                        if pt_a and pt_b and (pt_a, pt_b) not in st.session_state['custom_connections']:
                            st.session_state['custom_connections'].append((pt_a, pt_b))
                            st.success(f"Đã nối STT {pt_a} với STT {pt_b} thành công!")
                            st.rerun()
                with col_btn2:
                    if st.button("🗑️ Xóa hết nối"):
                        st.session_state['custom_connections'] = []
                        st.rerun()

            # --- CÔNG CỤ XÓA ĐIỂM / ĐOẠN THỪA ---
            with st.expander("🗑️ Xóa điểm mốc lỗi / cắt đoạn thừa", expanded=False):
                rows_to_delete = st.multiselect("Chọn STT các mốc cần xóa:", options=list(df_analyzed['STT']))
                if st.button("🔥 Xóa các mốc đã chọn"):
                    if rows_to_delete:
                        orig_indices_to_drop = df_analyzed[df_analyzed['STT'].isin(rows_to_delete)].index
                        st.session_state['df_current'] = st.session_state['df_current'].drop(index=orig_indices_to_drop).reset_index(drop=True)
                        st.rerun()

            # BẢNG DỮ LIỆU EXCEL TRỰC TUYẾN
            with st.container(height=280):
                edited_df = st.data_editor(
                    df_display, 
                    num_rows="dynamic", 
                    use_container_width=True,
                    disabled=["STT", "Khoảng cách (m)"]
                )
            
            # XUẤT FILE SAU KHI HIỆU CHỈNH
            st.markdown("---")
            output = io.BytesIO()
            export_df = edited_df.drop(columns=['STT', 'Khoảng cách (m)', 'Cảnh báo'], errors='ignore')
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                export_df.to_excel(writer, index=False)
                
            st.download_button(
                label="💾 Xuất File Excel VN2000 Hoàn Chỉnh",
                data=output.getvalue(),
                file_name="Hieu_Chinh_vi_tri_toa_do_VN200_HoanThien.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
                use_container_width=True
            )
else:
    st.info("Vui lòng tải lên file Excel để bắt đầu sử dụng công cụ.")

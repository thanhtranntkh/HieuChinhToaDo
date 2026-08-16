import streamlit as st
import pandas as pd
import numpy as np
import pyproj
import folium
from folium import plugins
from streamlit_folium import st_folium
import io

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
    </style>
""", unsafe_allow_html=True)

st.title("🌐 Công Cụ Hiệu Chỉnh Vị Trí Toạ Độ VN-2000")
st.markdown("Xử lý chuyên dụng cho file **Hieu Chỉnh vị trí toa do VN200 cho phù hợp** (Tích hợp STT, Nối đầu-cuối & Dịch chuyển mốc)")

# --- 1. CẤU HÌNH HỆ TỌA ĐỘ ---
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

# --- 2. THUẬT TOÁN KIỂM TRA LỖI & LÃNH THỔ ---
def analyze_data(df, kinh_tuyen_truc):
    df['Cảnh báo'] = ""
    
    swap_mask = df['X'] < df['Y']
    df.loc[swap_mask, 'Cảnh báo'] += "⚠️ X, Y có thể bị đảo ngược. "

    distances = [0.0]
    for i in range(1, len(df)):
        dx = df.iloc[i]['X'] - df.iloc[i-1]['X']
        dy = df.iloc[i]['Y'] - df.iloc[i-1]['Y']
        dist = np.sqrt(dx**2 + dy**2)
        distances.append(round(dist, 2))
        if dist < 30 and dist > 0:
            df.at[i, 'Cảnh báo'] += f"⚠️ Gần mốc trước ({dist}m). "
    
    df['Khoảng cách (m)'] = distances

    out_of_bounds = []
    for idx, row in df.iterrows():
        try:
            lat, lon = convert_to_wgs84(row['X'], row['Y'], kinh_tuyen_truc)
            if not (8.0 <= lat <= 24.0 and 102.0 <= lon <= 110.0):
                df.at[idx, 'Cảnh báo'] += "🚨 Vượt ngoài lãnh thổ VN! "
                out_of_bounds.append(idx)
        except:
            df.at[idx, 'Cảnh báo'] += "🚨 Tọa độ lỗi! "
            out_of_bounds.append(idx)
            
    return df, out_of_bounds

# --- 3. THANH BÊN (SIDEBAR) ---
with st.sidebar:
    st.header("⚙️ Thông số đầu vào")
    uploaded_file = st.file_uploader('Tải file "Hieu Chỉnh vị trí toa do VN200 cho phù hợp .xlsx"', type=['xlsx'])
    kinh_tuyen_truc = st.number_input("Kinh tuyến trục (VD: 108.25)", value=108.25, format="%.2f")
    loai_du_lieu = st.radio("Loại bản vẽ:", ["Tim tuyến (Polyline)", "Ranh GPMB (Polygon)"])
    
    # Công cụ nối điểm đầu và cuối
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

        # Bổ sung cột STT (Thứ tự mốc) vào hiển thị
        current_df.insert(0, 'STT', range(1, len(current_df) + 1))

        df_analyzed, out_of_bounds_indices = analyze_data(current_df, kinh_tuyen_truc)
        
        col_map, col_data = st.columns([3, 1.2])
        
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
        
        # Nếu bật tùy chọn nối điểm đầu và điểm cuối
        if noi_dau_cuoi and len(lat_lons) > 2:
            lat_lons.append(lat_lons[0])

        with col_map:
            st.subheader("🗺️ Bản đồ tương tác")
            st.caption("👈 Mốc màu ĐỎ là mốc bị cảnh báo lỗi hoặc nằm ngoài lãnh thổ Việt Nam.")
            
            if lat_lons:
                center_lat = sum([pt[0] for pt in lat_lons]) / len(lat_lons)
                center_lon = sum([pt[1] for pt in lat_lons]) / len(lat_lons)
                
                m = folium.Map(location=[center_lat, center_lon], zoom_start=18, max_zoom=22)
                folium.TileLayer('https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google', name='Google Satellite').add_to(m)
                plugins.MeasureControl(position='topleft', primary_length_unit='meters').add_to(m)

                for i, coord in enumerate(lat_lons[:-1] if noi_dau_cuoi and len(lat_lons) > 2 else lat_lons):
                    idx_in_df = valid_indices[i] if i < len(valid_indices) else valid_indices[0]
                    warning_text = str(df_analyzed.loc[df_analyzed.index == idx_in_df, 'Cảnh báo'].values[0])
                    is_warning = len(warning_text.strip()) > 0
                    color = 'red' if is_warning else 'blue'
                    
                    stt_val = df_analyzed.loc[df_analyzed.index == idx_in_df, 'STT'].values[0]

                    folium.CircleMarker(
                        location=coord, radius=8, color=color, fill=True, weight=3,
                        tooltip=f"STT: {stt_val} | Lỗi: {warning_text}"
                    ).add_to(m)

                if loai_du_lieu == "Tim tuyến (Polyline)":
                    folium.PolyLine(lat_lons, color="yellow", weight=4).add_to(m)
                else:
                    folium.Polygon(lat_lons, color="orange", fill=True, fill_opacity=0.3, weight=3).add_to(m)

                map_data = st_folium(m, use_container_width=True, height=750, returned_objects=["last_object_clicked"])
                
        with col_data:
            st.subheader("📝 Hiệu chỉnh & Công cụ")
            
            search_query = st.text_input("🔍 Tìm kiếm mốc (STT, Tên hoặc X/Y):", "")
            df_display = df_analyzed.copy()
            if search_query:
                mask = df_display.astype(str).apply(lambda col: col.str.contains(search_query, case=False, na=False)).any(axis=1)
                df_display = df_display[mask]

            # --- CÔNG CỤ DI CHUYỂN MỐC (TỊNH TIẾN ĐỒNG LOẠT HOẶC THEO MỐC) ---
            with st.expander("📐 Công cụ di chuyển / Tịnh tiến mốc (Shift)", expanded=False):
                target_row_shift = st.selectbox("Chọn STT mốc cần dịch chuyển:", options=[None] + list(df_analyzed['STT']), format_func=lambda x: f"STT {x}" if x is not None else "-- Chọn mốc (Hoặc bỏ trống để dịch tất cả) --")
                col_dx, col_dy = st.columns(2)
                with col_dx:
                    delta_x = st.number_input("Cộng thêm vào X (ΔX):", value=0.0, format="%.3f")
                with col_dy:
                    delta_y = st.number_input("Cộng thêm vào Y (ΔY):", value=0.0, format="%.3f")
                
                if st.button("🚀 Thực hiện dịch chuyển mốc", type="primary"):
                    if target_row_shift is not None:
                        # Dịch chuyển 1 mốc cụ thể
                        real_idx = df_analyzed[df_analyzed['STT'] == target_row_shift].index[0]
                        st.session_state['df_current'].loc[real_idx, 'X'] += delta_x
                        st.session_state['df_current'].loc[real_idx, 'Y'] += delta_y
                        st.success(f"Đã dịch chuyển mốc STT {target_row_shift} thành công!")
                        st.rerun()
                    else:
                        # Dịch chuyển toàn bộ danh sách
                        st.session_state['df_current']['X'] += delta_x
                        st.session_state['df_current']['Y'] += delta_y
                        st.success("Đã tịnh tiến toàn bộ hệ thống tọa độ thành công!")
                        st.rerun()

            # XÓA MỐC / CỤM MỐC
            with st.expander("🗑️ Công cụ Xóa mốc / Cụm mốc", expanded=False):
                if out_of_bounds_indices:
                    if st.button("🧹 Xóa sạch mốc ngoài lãnh thổ VN"):
                        orig_indices_to_drop = df_analyzed.loc[out_of_bounds_indices].index.drop('STT', errors='ignore')
                        st.session_state['df_current'] = st.session_state['df_current'].drop(index=orig_indices_to_drop).reset_index(drop=True)
                        st.rerun()
                
                rows_to_delete = st.multiselect("Chọn STT các mốc cần xóa:", options=list(df_analyzed['STT']))
                if st.button("🔥 Xóa các mốc đã chọn"):
                    if rows_to_delete:
                        orig_indices_to_drop = df_analyzed[df_analyzed['STT'].isin(rows_to_delete)].index
                        st.session_state['df_current'] = st.session_state['df_current'].drop(index=orig_indices_to_drop).reset_index(drop=True)
                        st.rerun()

            # BẮT SỰ KIỆN CLICK TRÊN BẢN ĐỒ
            selected_row = None
            if map_data and map_data.get("last_object_clicked"):
                clicked_lat = map_data["last_object_clicked"]["lat"]
                clicked_lon = map_data["last_object_clicked"]["lng"]
                
                min_dist = float('inf')
                for i, (lat, lon) in enumerate(lat_lons[:-1] if noi_dau_cuoi and len(lat_lons) > 2 else lat_lons):
                    dist = (lat - clicked_lat)**2 + (lon - clicked_lon)**2
                    if dist < min_dist:
                        min_dist = dist
                        selected_row = valid_indices[i] if i < len(valid_indices) else valid_indices[0]
            
            if selected_row is not None:
                stt_selected = df_analyzed.loc[df_analyzed.index == selected_row, 'STT'].values[0]
                st.markdown(f"""
                <div class="selected-point-box">
                    <strong>🎯 Đang chọn: STT {stt_selected}</strong><br>
                    X: <code>{df_analyzed.loc[selected_row, 'X']}</code> | Y: <code>{df_analyzed.loc[selected_row, 'Y']}</code>
                </div>
                """, unsafe_allow_html=True)

            # BẢNG DỮ LIỆU EXCEL TRỰC TUYẾN
            with st.container(height=350):
                edited_df = st.data_editor(
                    df_display, 
                    num_rows="dynamic", 
                    use_container_width=True,
                    disabled=["STT", "Khoảng cách (m)"]
                )
            
            # XUẤT FILE SAU KHI HIỆU CHỈNH
            st.markdown("---")
            output = io.BytesIO()
            # Loại bỏ các cột phụ tính toán và cột STT giả lập trước khi xuất file gốc
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

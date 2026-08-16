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

# --- CSS TÙY CHỈNH ĐỂ BẢNG DỮ LIỆU LUÔN NỔI & ĐẸP ---
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
st.markdown("Xử lý chuyên dụng cho file **Hieu Chỉnh vị trí toa do VN200 cho phù hợp**")

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

# --- 2. THUẬT TOÁN KIỂM TRA LỖI ---
def analyze_data(df, loai_du_lieu):
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
    return df

# --- 3. THANH BÊN (SIDEBAR) ---
with st.sidebar:
    st.header("⚙️ Thông số đầu vào")
    uploaded_file = st.file_uploader('Tải file "Hieu Chỉnh vị trí toa do VN200 cho phù hợp .xlsx"', type=['xlsx'])
    kinh_tuyen_truc = st.number_input("Kinh tuyến trục (VD: 108.25)", value=108.25, format="%.2f")
    loai_du_lieu = st.radio("Loại bản vẽ:", ["Tim tuyến (Polyline)", "Ranh GPMB (Polygon)"])

# --- 4. GIAO DIỆN CHÍNH (CHIA CỘT 75% BẢN ĐỒ - 25% DỮ LIỆU) ---
if uploaded_file:
    raw_df = pd.read_excel(uploaded_file)
    
    if 'X' not in raw_df.columns or 'Y' not in raw_df.columns:
        st.error("File phải có cột 'X' và 'Y'.")
    else:
        df_analyzed = analyze_data(raw_df.copy(), loai_du_lieu)
        
        # CHIA CỘT TỶ LỆ 3:1 (Bản đồ siêu lớn, Bảng dữ liệu vừa đủ)
        col_map, col_data = st.columns([3, 1.2])
        
        # ---- XỬ LÝ DỮ LIỆU TỌA ĐỘ TRƯỚC KHI VẼ ----
        lat_lons = []
        valid_indices = [] # Lưu lại vị trí thực của các điểm không bị lỗi
        for idx, row in df_analyzed.iterrows():
            try:
                lat, lon = convert_to_wgs84(row['X'], row['Y'], kinh_tuyen_truc)
                if not np.isnan(lat) and not np.isnan(lon):
                    lat_lons.append([lat, lon])
                    valid_indices.append(idx)
            except:
                pass
        
        with col_map:
            st.subheader("🗺️ Bản đồ tương tác")
            st.caption("👈 Nhấp vào một điểm MÀU ĐỎ hoặc MÀU XANH trên bản đồ, dữ liệu sẽ tự động nhảy ở cột bên phải.")
            
            if lat_lons:
                center_lat = sum([pt[0] for pt in lat_lons]) / len(lat_lons)
                center_lon = sum([pt[1] for pt in lat_lons]) / len(lat_lons)
                
                m = folium.Map(location=[center_lat, center_lon], zoom_start=18, max_zoom=22)
                folium.TileLayer('https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google', name='Google Satellite').add_to(m)
                
                plugins.MeasureControl(position='topleft', primary_length_unit='meters').add_to(m)

                # Vẽ điểm
                for i, coord in enumerate(lat_lons):
                    idx_in_df = valid_indices[i]
                    is_warning = "⚠️" in str(df_analyzed.iloc[idx_in_df].get('Cảnh báo', ''))
                    color = 'red' if is_warning else 'blue'
                    
                    folium.CircleMarker(
                        location=coord, radius=8, color=color, fill=True, weight=3,
                        tooltip=f"Dòng {idx_in_df + 1} | X: {df_analyzed.iloc[idx_in_df]['X']}",
                        popup=f"{idx_in_df}" # Lưu lại số thứ tự để Streamlit bắt sự kiện
                    ).add_to(m)

                if loai_du_lieu == "Tim tuyến (Polyline)":
                    folium.PolyLine(lat_lons, color="yellow", weight=4).add_to(m)
                else:
                    folium.Polygon(lat_lons, color="orange", fill=True, fill_opacity=0.3, weight=3).add_to(m)

                # RENDER BẢN ĐỒ (BẮT SỰ KIỆN CLICK)
                map_data = st_folium(m, use_container_width=True, height=750, returned_objects=["last_object_clicked"])
                
        with col_data:
            st.subheader("📝 Hiệu chỉnh dữ liệu")
            
            # --- XỬ LÝ SỰ KIỆN KHI NGƯỜI DÙNG CLICK LÊN BẢN ĐỒ ---
            selected_row = None
            if map_data and map_data.get("last_object_clicked"):
                # Dùng thuật toán khoảng cách để dò tìm điểm vừa được click tương ứng với hàng nào trong Excel
                clicked_lat = map_data["last_object_clicked"]["lat"]
                clicked_lon = map_data["last_object_clicked"]["lng"]
                
                min_dist = float('inf')
                for i, (lat, lon) in enumerate(lat_lons):
                    dist = (lat - clicked_lat)**2 + (lon - clicked_lon)**2
                    if dist < min_dist:
                        min_dist = dist
                        selected_row = valid_indices[i]
            
            # BẢNG THÔNG BÁO NỔI NẾU CÓ ĐIỂM ĐƯỢC CHỌN
            if selected_row is not None:
                st.markdown(f"""
                <div class="selected-point-box">
                    <strong>🎯 Mốc đang chọn: Dòng số {selected_row + 1}</strong><br>
                    Giá trị X: <code>{df_analyzed.iloc[selected_row]['X']}</code><br>
                    Giá trị Y: <code>{df_analyzed.iloc[selected_row]['Y']}</code><br>
                    <span style="color:red; font-size: 13px;"><i>(Kéo bảng bên dưới tới dòng {selected_row + 1} để sửa)</i></span>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.info("Nhấp vào một điểm trên bản đồ để xem chi tiết ở đây.")

            # VÙNG CHỨA BẢNG EXCEL (TỰ ĐỘNG CUỘN ĐỘC LẬP VỚI BẢN ĐỒ)
            with st.container(height=550):
                edited_df = st.data_editor(
                    df_analyzed, 
                    num_rows="dynamic", 
                    use_container_width=True,
                    disabled=["Khoảng cách (m)"]
                )
            
            # XUẤT FILE NẰM GỌN BÊN DƯỚI BẢNG EXCEL
            st.markdown("---")
            output = io.BytesIO()
            export_df = edited_df.drop(columns=['Khoảng cách (m)', 'Cảnh báo'], errors='ignore')
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                export_df.to_excel(writer, index=False)
                
            st.download_button(
                label="💾 Xuất File Excel VN2000",
                data=output.getvalue(),
                file_name="Hieu_Chinh_vi_tri_toa_do_VN200_HoanThien.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
                use_container_width=True
            )
else:
    st.info("Vui lòng tải lên file Excel để bắt đầu.")

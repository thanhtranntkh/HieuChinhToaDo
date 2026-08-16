import streamlit as st
import pandas as pd
import numpy as np
import pyproj
import folium
from streamlit_folium import st_folium
import io

st.set_page_config(layout="wide", page_title="Hiệu Chỉnh Tọa Độ VN-2000")

st.title("🌐 Công Cụ Hiệu Chỉnh Vị Trí Toạ Độ VN-2000")
st.markdown("Xử lý chuyên dụng cho file **Hieu Chỉnh vị trí toa do VN200 cho phù hợp**")

# --- 1. CẤU HÌNH HỆ TỌA ĐỘ THEO QĐ 05/2007/QĐ-BTNMT ---
def get_vn2000_crs(kinh_tuyen_truc, mui=3):
    k_factor = 0.9999 if mui == 3 else 0.9996
    # Áp dụng 7 tham số chuẩn của Bộ TNMT
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
    lon, lat = transformer.transform(y, x) # Chú ý: Đầu vào pyproj thường là (Easting, Northing) tức là (Y, X)
    return lat, lon

# --- 2. THUẬT TOÁN KIỂM TRA LỖI ---
def analyze_data(df, loai_du_lieu):
    df['Cảnh báo'] = ""
    
    # Lỗi 1: Nhầm X, Y (X thường > 1.000.000, Y thường ~ 500.000)
    swap_mask = df['X'] < df['Y']
    df.loc[swap_mask, 'Cảnh báo'] += "⚠️ X, Y có thể bị đảo ngược. "

    # Lỗi 2: Khoảng cách < 30m (Cần giải trình)
    distances = [0.0]
    for i in range(1, len(df)):
        dx = df.iloc[i]['X'] - df.iloc[i-1]['X']
        dy = df.iloc[i]['Y'] - df.iloc[i-1]['Y']
        dist = np.sqrt(dx**2 + dy**2)
        distances.append(round(dist, 2))
        if dist < 30 and dist > 0:
            df.at[i, 'Cảnh báo'] += f"⚠️ Khoảng cách mốc trước quá gần ({dist}m < 30m). "
    
    df['Khoảng cách (m)'] = distances

    # Lỗi 3: Ranh khép kín
    if loai_du_lieu == "Ranh GPMB (Polygon)" and len(df) > 2:
        first_pt = df.iloc[0]
        last_pt = df.iloc[-1]
        if abs(first_pt['X'] - last_pt['X']) > 0.1 or abs(first_pt['Y'] - last_pt['Y']) > 0.1:
            st.error("🚨 Lỗi cấu trúc: Ranh giới GPMB chưa khép kín. Điểm cuối phải trùng điểm đầu.")
            df.at[df.index[-1], 'Cảnh báo'] += "⚠️ Điểm cuối chưa khép kín với điểm đầu. "

    return df

# --- 3. GIAO DIỆN & XỬ LÝ ---
with st.sidebar:
    st.header("⚙️ Thông số đầu vào")
    uploaded_file = st.file_uploader('Tải lên file "Hieu Chỉnh vị trí toa do VN200 cho phù hợp .xlsx"', type=['xlsx'])
    kinh_tuyen_truc = st.number_input("Kinh tuyến trục (VD: 105.00)", value=108.25, format="%.2f")
    loai_du_lieu = st.radio("Loại bản vẽ:", ["Tim tuyến (Polyline)", "Ranh GPMB (Polygon)"])

if uploaded_file:
    raw_df = pd.read_excel(uploaded_file)
    
    if 'X' not in raw_df.columns or 'Y' not in raw_df.columns:
        st.error("File phải có cột 'X' và 'Y'.")
    else:
        # Xử lý tính toán và cảnh báo
        df_analyzed = analyze_data(raw_df.copy(), loai_du_lieu)
        
        col_data, col_map = st.columns([1.2, 1])
        
        with col_data:
            st.subheader("📝 Bảng dữ liệu & Cảnh báo")
            st.caption("Kéo thả các hàng để sắp xếp lại tính liền mạch. Sửa trực tiếp X, Y nếu bị sai.")
            edited_df = st.data_editor(
                df_analyzed, 
                num_rows="dynamic", 
                use_container_width=True,
                disabled=["Khoảng cách (m)"] # Không cho sửa cột tính toán
            )
        
        with col_map:
            st.subheader("🗺️ Bản đồ hiển thị")
            lat_lons = []
            for idx, row in edited_df.iterrows():
                try:
                    lat, lon = convert_to_wgs84(row['X'], row['Y'], kinh_tuyen_truc)
                    if not np.isnan(lat) and not np.isnan(lon):
                        lat_lons.append([lat, lon])
                except:
                    pass
            
            if lat_lons:
                m = folium.Map(location=lat_lons[0], zoom_start=18, max_zoom=22)
                # Dùng Google Satellite
                folium.TileLayer('https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google', name='Google Satellite').add_to(m)

                # Vẽ điểm
                for i, coord in enumerate(lat_lons):
                    is_warning = "⚠️" in str(edited_df.iloc[i].get('Cảnh báo', ''))
                    color = 'red' if is_warning else 'blue'
                    
                    folium.CircleMarker(
                        location=coord, radius=6, color=color, fill=True,
                        tooltip=f"Dòng {i+1} | X: {edited_df.iloc[i]['X']} | Y: {edited_df.iloc[i]['Y']}"
                    ).add_to(m)

                # Vẽ nét liền mạch
                if loai_du_lieu == "Tim tuyến (Polyline)":
                    folium.PolyLine(lat_lons, color="yellow", weight=4).add_to(m)
                else:
                    folium.Polygon(lat_lons, color="orange", fill=True, fill_opacity=0.3).add_to(m)

                st_folium(m, width=600, height=500)
                
        # --- 4. XUẤT FILE ---
        st.markdown("---")
        output = io.BytesIO()
        # Loại bỏ cột tính toán phụ trước khi xuất trả file cho người dùng
        export_df = edited_df.drop(columns=['Khoảng cách (m)', 'Cảnh báo'], errors='ignore')
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            export_df.to_excel(writer, index=False)
            
        st.download_button(
            label="💾 Lưu và tải xuống file Hieu Chỉnh vị trí toa do VN200 cho phù hợp",
            data=output.getvalue(),
            file_name="Hieu_Chinh_vi_tri_toa_do_VN200_HoanThien.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary"
        )

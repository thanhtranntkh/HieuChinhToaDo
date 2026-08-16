import streamlit as st
import pandas as pd
import numpy as np
import pyproj
import folium
from folium import plugins # Bổ sung bộ Plugin mở rộng cho bản đồ
from streamlit_folium import st_folium
import io

# Cấu hình giao diện Web toàn màn hình
st.set_page_config(layout="wide", page_title="Hiệu Chỉnh Tọa Độ VN-2000")

st.title("🌐 Công Cụ Hiệu Chỉnh Vị Trí Toạ Độ VN-2000")
st.markdown("Xử lý chuyên dụng cho file **Hieu Chỉnh vị trí toa do VN200 cho phù hợp**")

# --- 1. CẤU HÌNH HỆ TỌA ĐỘ THEO QUY ĐỊNH PHÁP LÝ ---
def get_vn2000_crs(kinh_tuyen_truc, mui=3):
    k_factor = 0.9999 if mui == 3 else 0.9996
    # Tham số dịch chuyển gốc tọa độ: 191,90441429 m; -39,30318279 m; -111,45032835 m. Góc xoay và hệ số tỷ lệ.
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
            df.at[i, 'Cảnh báo'] += f"⚠️ Mốc trước quá gần ({dist}m). "
    
    df['Khoảng cách (m)'] = distances

    if loai_du_lieu == "Ranh GPMB (Polygon)" and len(df) > 2:
        first_pt = df.iloc[0]
        last_pt = df.iloc[-1]
        if abs(first_pt['X'] - last_pt['X']) > 0.1 or abs(first_pt['Y'] - last_pt['Y']) > 0.1:
            df.at[df.index[-1], 'Cảnh báo'] += "⚠️ Điểm cuối chưa khép kín với điểm đầu. "

    return df

# --- 3. THANH BÊN (SIDEBAR) ---
with st.sidebar:
    st.header("⚙️ Thông số đầu vào")
    uploaded_file = st.file_uploader('Tải file "Hieu Chỉnh vị trí toa do VN200 cho phù hợp .xlsx"', type=['xlsx'])
    kinh_tuyen_truc = st.number_input("Kinh tuyến trục (VD: 105.00)", value=108.25, format="%.2f")
    loai_du_lieu = st.radio("Loại bản vẽ:", ["Tim tuyến (Polyline)", "Ranh GPMB (Polygon)"])

# --- 4. GIAO DIỆN CHÍNH (THIẾT KẾ MỚI TRÊN - DƯỚI) ---
if uploaded_file:
    raw_df = pd.read_excel(uploaded_file)
    
    if 'X' not in raw_df.columns or 'Y' not in raw_df.columns:
        st.error("File phải có cột 'X' và 'Y'.")
    else:
        df_analyzed = analyze_data(raw_df.copy(), loai_du_lieu)
        
        # BẢNG DỮ LIỆU NẰM TRÊN CÙNG CHIẾM CHIỀU RỘNG TỐI ĐA
        st.subheader("📝 1. Bảng dữ liệu & Cảnh báo")
        st.info("Kéo thả các hàng để sắp xếp thứ tự. Sửa số X, Y trực tiếp trong bảng và bản đồ bên dưới sẽ tự cập nhật.")
        edited_df = st.data_editor(
            df_analyzed, 
            num_rows="dynamic", 
            use_container_width=True, # Tràn viền
            height=250,               # Giới hạn chiều cao để nhường chỗ cho bản đồ
            disabled=["Khoảng cách (m)"]
        )
        
        # BẢN ĐỒ CHIẾM KÍCH THƯỚC KHỔNG LỒ BÊN DƯỚI
        st.subheader("🗺️ 2. Bản đồ tương tác")
        st.caption("💡 Mẹo: Bấm vào biểu tượng **[ ]** ở góc phải bản đồ để phóng to Toàn màn hình.")
        
        lat_lons = []
        for idx, row in edited_df.iterrows():
            try:
                lat, lon = convert_to_wgs84(row['X'], row['Y'], kinh_tuyen_truc)
                if not np.isnan(lat) and not np.isnan(lon):
                    lat_lons.append([lat, lon])
            except:
                pass
        
        if lat_lons:
            # Lấy trung tâm bản đồ
            center_lat = sum([pt[0] for pt in lat_lons]) / len(lat_lons)
            center_lon = sum([pt[1] for pt in lat_lons]) / len(lat_lons)
            
            m = folium.Map(location=[center_lat, center_lon], zoom_start=17, max_zoom=22)
            folium.TileLayer('https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google', name='Google Satellite').add_to(m)

            # --- THÊM CÁC PLUGIN NÂNG CAO TRẢI NGHIỆM UX ---
            plugins.Fullscreen(position='topright', title='Phóng to toàn màn hình', title_cancel='Thu nhỏ', force_separate_button=True).add_to(m)
            plugins.MeasureControl(position='topleft', primary_length_unit='meters', secondary_length_unit='miles', primary_area_unit='sqmeters').add_to(m)
            plugins.MousePosition(position='bottomright', separator=' | ', empty_string='NaN', lng_first=False, num_digits=6, prefix='Tọa độ WGS84:').add_to(m)

            # Vẽ điểm và đường
            for i, coord in enumerate(lat_lons):
                is_warning = "⚠️" in str(edited_df.iloc[i].get('Cảnh báo', ''))
                color = 'red' if is_warning else 'blue'
                
                folium.CircleMarker(
                    location=coord, radius=7, color=color, fill=True, weight=2,
                    tooltip=f"Điểm số {i+1} | X: {edited_df.iloc[i]['X']} | Y: {edited_df.iloc[i]['Y']}"
                ).add_to(m)

            if loai_du_lieu == "Tim tuyến (Polyline)":
                folium.PolyLine(lat_lons, color="yellow", weight=5, opacity=0.9).add_to(m)
            else:
                folium.Polygon(lat_lons, color="orange", fill=True, fill_opacity=0.3, weight=3).add_to(m)

            # Render bản đồ với chiều cao siêu lớn (700px) và rộng 100%
            st_folium(m, use_container_width=True, height=700)
                
        # --- 5. XUẤT FILE ---
        st.markdown("---")
        output = io.BytesIO()
        export_df = edited_df.drop(columns=['Khoảng cách (m)', 'Cảnh báo'], errors='ignore')
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            export_df.to_excel(writer, index=False)
            
        st.download_button(
            label="💾 Tải xuống file Hieu Chỉnh vị trí toa do VN200 cho phù hợp",
            data=output.getvalue(),
            file_name="Hieu_Chinh_vi_tri_toa_do_VN200_HoanThien.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary"
        )
else:
    st.info("Vui lòng tải lên file Excel để bắt đầu.")

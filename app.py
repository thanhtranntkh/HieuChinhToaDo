import streamlit as st
import pandas as pd
import numpy as np
import pyproj
import folium
from folium import plugins
from streamlit_folium import st_folium
import io

try:
    from google import genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

st.set_page_config(layout="wide", page_title="Hiệu Chỉnh Tọa Độ VN-2000 Pro")

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

st.title("🌐 Công Cụ Hiệu Chỉnh, Sắp Xếp Tọa Độ VN-2000")
st.markdown("Hỗ trợ tự động phát hiện đảo trục X/Y, đứt đoạn, phân tích trái/phải và vá lỗi tuyến thông minh bằng Google Gemini AI.")

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

def analyze_data(df, kinh_tuyen_truc):
    df = df.copy()
    df['Cảnh báo'] = ""
    
    swap_mask = df['X'] < df['Y']
    df.loc[swap_mask, 'Cảnh báo'] += "⚠️ Đảo trục X-Y! "

    dup_mask = df.duplicated(subset=['X', 'Y'], keep=False)
    df.loc[dup_mask, 'Cảnh báo'] += "⚠️ Lặp tọa độ! "

    x_vals = df['X'].to_numpy()
    y_vals = df['Y'].to_numpy()
    
    dx = np.diff(x_vals, prepend=x_vals[0])
    dy = np.diff(y_vals, prepend=y_vals[0])
    distances = np.sqrt(dx**2 + dy**2)
    distances[0] = 0.0
    df['Khoảng cách (m)'] = np.round(distances, 2)
    
    broken_segments = []
    swapped_points = []
    
    for i in range(len(df)):
        if df.at[i, 'X'] < df.at[i, 'Y']:
            swapped_points.append(i + 1)
            
    for i in range(1, len(df)):
        dist = distances[i]
        if dist > 200: 
            df.at[i, 'Cảnh báo'] += f"🚨 Đứt đoạn ({dist}m)! "
            broken_segments.append({'from_idx': i-1, 'to_idx': i, 'distance': dist})
        elif 0 < dist < 30:
            df.at[i, 'Cảnh báo'] += f"⚠️ Quá gần ({dist}m). "
            
    return df, broken_segments, swapped_points

def ask_gemini_for_direction(broken_info_text, kinh_tuyen_truc, api_key):
    if not HAS_GENAI:
        return "⚠️ Thư viện `google-genai` chưa được cài đặt."
    if not api_key:
        return "⚠️ Vui lòng nhập Google Gemini API Key ở thanh bên (sidebar)."
    try:
        client = genai.Client(api_key=api_key)
        prompt = f"""
        Bạn là một kỹ sư trắc địa và chuyên gia GIS hàng đầu. 
        Tôi có dữ liệu tọa độ VN-2000 (Kinh tuyến trục {kinh_tuyen_truc}) đang gặp các điểm đứt đoạn hình học sau:
        {broken_info_text}
        
        Hãy phân tích theo góc nhìn tiến của tuyến (từ mốc trước đến mốc hiện tại):
        1. Xác định các mốc bị đứt đoạn/văng nằm lệch về **bên phải hay bên trái** theo hướng nhìn của tuyến.
        2. Đề xuất phương án xử lý kỹ thuật cụ thể (nên dời mốc, nối mạch hay sắp xếp lại thế nào) một cách ngắn gọn và chuyên nghiệp.
        """
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        return response.text
    except Exception as e:
        return f"Lỗi kết nối Gemini API: {e}"

with st.sidebar:
    st.header("⚙️ Thông số đầu vào")
    uploaded_file = st.file_uploader('Tải file Excel tọa độ (.xlsx)', type=['xlsx'])
    kinh_tuyen_truc = st.number_input("Kinh tuyến trục (VD: 108.25)", value=108.25, format="%.2f")
    loai_du_lieu = st.radio("Loại bản vẽ:", ["Tim tuyến (Polyline)", "Ranh GPMB (Polygon)"])
    noi_dau_cuoi = st.checkbox("🔗 Tự động nối điểm đầu và cuối", value=False)
    
    st.markdown("---")
    st.header("🤖 Trợ lý Google Gemini AI")
    gemini_api_key = st.text_input("Nhập Gemini API Key:", type="password")

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

        df_analyzed, broken_segments, swapped_points = analyze_data(current_df, kinh_tuyen_truc)
        df_display = df_analyzed.copy()
        if name_col and name_col in df_display.columns:
            cols = ['STT', name_col, 'X', 'Y', 'Khoảng cách (m)', 'Cảnh báo']
            other_cols = [c for c in df_display.columns if c not in cols]
            df_display = df_display[cols + other_cols]

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
                👉 <strong>Hướng dẫn:</strong> Click trực tiếp vào các mốc trên bản đồ để chọn <b>Mốc A (Đứng trước)</b> và <b>Mốc B (Cần nối/dời)</b>.
            </div>
            """, unsafe_allow_html=True)

            if lat_lons:
                center_lat = np.mean(lats[valid_mask])
                center_lon = np.mean(lons[valid_mask])
                
                m = folium.Map(location=[center_lat, center_lon], zoom_start=17, max_zoom=22)
                folium.TileLayer('https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google', name='Google Satellite').add_to(m)
                
                plugins.MeasureControl(position='topleft', primary_length_unit='meters').add_to(m)

                for i, coord in enumerate(lat_lons[:-1] if noi_dau_cuoi and len(lat_lons) > 2 else lat_lons):
                    idx_orig = valid_indices[i]
                    warning_text = str(df_analyzed.iloc[idx_orig]['Cảnh báo'])
                    stt_val = int(df_analyzed.iloc[idx_orig]['STT'])
                    point_label = str(df_analyzed.iloc[idx_orig][name_col]) if name_col else f"STT {stt_val}"

                    if st.session_state.get('selected_point_a') == stt_val:
                        color = 'green'
                    elif st.session_state.get('selected_point_b') == stt_val:
                        color = 'orange'
                    else:
                        color = 'red' if len(warning_text.strip()) > 0 else 'blue'

                    folium.CircleMarker(
                        location=coord, radius=8, color=color, fill=True, fill_color=color, fill_opacity=0.8, weight=2,
                        popup=f"STT: {stt_val} | Tên: {point_label}",
                        tooltip=f"Mốc: {point_label} (STT {stt_val}) | {warning_text}"
                    ).add_to(m)

                if loai_du_lieu == "Tim tuyến (Polyline)":
                    folium.PolyLine(lat_lons, color="yellow", weight=4, opacity=0.7).add_to(m)
                else:
                    folium.Polygon(lat_lons, color="orange", fill=True, fill_opacity=0.3, weight=3).add_to(m)

                map_data = st_folium(m, use_container_width=True, height=600, returned_objects=["last_object_clicked"])
                
                if map_data and map_data.get("last_object_clicked"):
                    clicked_lat = map_data["last_object_clicked"]["lat"]
                    clicked_lon = map_data["last_object_clicked"]["lng"]
                    
                    dists = np.sqrt((lats[valid_mask] - clicked_lat)**2 + (lons[valid_mask] - clicked_lon)**2)
                    closest_idx_in_valid = np.argmin(dists)
                    orig_idx = valid_indices[closest_idx_in_valid]
                    clicked_stt = int(df_analyzed.iloc[orig_idx]['STT'])
                    
                    if st.session_state.get('selected_point_a') is None:
                        st.session_state['selected_point_a'] = clicked_stt
                        st.rerun()
                    elif st.session_state.get('selected_point_b') is None and clicked_stt != st.session_state['selected_point_a']:
                        st.session_state['selected_point_b'] = clicked_stt
                        st.rerun()
                
        with col_data:
            st.subheader("📝 Công cụ Hiệu chỉnh & AI")
            
            if swapped_points:
                st.markdown(f"""
                <div class="alert-box">
                    <strong>⚠️ PHÁT HIỆN {len(swapped_points)} MỐC ĐẢO TRỤC X/Y!</strong>
                </div>
                """, unsafe_allow_html=True)
                
                if st.button("🔄 Hoán đổi X và Y tự động", use_container_width=True):
                    current_raw = st.session_state['df_current'].copy()
                    for pt in swapped_points:
                        idx = pt - 1
                        temp_val = current_raw.at[idx, 'X']
                        current_raw.at[idx, 'X'] = current_raw.at[idx, 'Y']
                        current_raw.at[idx, 'Y'] = temp_val
                    st.session_state['df_current'] = current_raw
                    st.success("Đã hoán đổi X và Y thành công!")
                    st.rerun()

            if broken_segments:
                st.markdown(f"""
                <div class="alert-box">
                    <strong>🚨 PHÁT HIỆN {len(broken_segments)} ĐOẠN ĐỨT ĐOẠN!</strong>
                </div>
                """, unsafe_allow_html=True)
                
                if st.button("🤖 Nhờ Gemini AI phân tích Hướng Trái / Phải", type="primary", use_container_width=True):
                    if not HAS_GENAI:
                        st.warning("⚠️ Thư viện `google-genai` chưa được cài trên server.")
                    else:
                        with st.spinner("Gemini đang phân tích hướng tuyến..."):
                            summary_text = ""
                            for b in broken_segments[:15]:
                                summary_text += f"- Đoạn từ STT {b['from_idx']+1} đến STT {b['to_idx']+1}: Khoảng cách = {b['distance']}m\n"
                            ai_advice = ask_gemini_for_direction(summary_text, kinh_tuyen_truc, gemini_api_key)
                            st.session_state['ai_advice'] = ai_advice
                
                if 'ai_advice' in st.session_state:
                    with st.expander("💡 Phân tích & Đề xuất từ Gemini AI", expanded=True):
                        st.markdown(st.session_state['ai_advice'])

                # --- NÚT TỰ ĐỘNG VÁ LỖI BẰNG THUẬT TOÁN NEAREST NEIGHBOR ---
                if st.button("✨ Tự động vá lỗi & Sắp xếp toàn tuyến liền mạch", type="primary", use_container_width=True):
                    with st.spinner("Đang tối ưu hóa thứ tự mốc toàn tuyến..."):
                        df_raw = st.session_state['df_current'].copy()
                        pts = df_raw[['X', 'Y']].to_numpy()
                        if len(pts) > 2:
                            # Thuật toán Nearest Neighbor TSP-like cho chuỗi tuyến hở
                            unvisited = set(range(1, len(pts)))
                            current = 0
                            new_order = [0]
                            while unvisited:
                                next_pt = min(unvisited, key=lambda idx: np.linalg.norm(pts[current] - pts[idx]))
                                new_order.append(next_pt)
                                unvisited.remove(next_pt)
                                current = next_pt
                            st.session_state['df_current'] = df_raw.iloc[new_order].reset_index(drop=True)
                            st.success("Đã tự động sắp xếp lại toàn bộ tuyến thành công!")
                            st.rerun()
            else:
                if not swapped_points:
                    st.markdown("""
                    <div class="success-box">
                        <strong>✅ Tuyến liền mạch và chuẩn hóa!</strong>
                    </div>
                    """, unsafe_allow_html=True)

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

            with st.expander("🚀 Sắp xếp thủ công Mốc B sau Mốc A", expanded=False):
                choices = [(row['STT'], f"STT {row['STT']}") for idx, row in df_analyzed.iterrows()]
                stt_options = [item[0] for item in choices]
                format_func = lambda x: f"STT {x}" if x else "-- Chọn mốc --"

                manual_a = st.selectbox("Mốc A:", options=[None] + stt_options, format_func=format_func)
                manual_b = st.selectbox("Mốc B:", options=[None] + stt_options, format_func=format_func)
                
                if manual_a: st.session_state['selected_point_a'] = manual_a
                if manual_b: st.session_state['selected_point_b'] = manual_b

                if st.button("Xác nhận Dời mốc", use_container_width=True):
                    pa = st.session_state.get('selected_point_a')
                    pb = st.session_state.get('selected_point_b')
                    if pa and pb and pa != pb:
                        current_raw = st.session_state['df_current'].copy()
                        row_b = current_raw.iloc[pb-1:pb].copy()
                        current_raw = current_raw.drop(index=pb-1).reset_index(drop=True)
                        new_idx_a = pa - 1 if (pb - 1) > (pa - 1) else pa
                        part1 = current_raw.iloc[:new_idx_a]
                        part2 = current_raw.iloc[new_idx_a:]
                        st.session_state['df_current'] = pd.concat([part1, row_b, part2]).reset_index(drop=True)
                        st.session_state['selected_point_a'] = None
                        st.session_state['selected_point_b'] = None
                        st.success("Đã dời mốc thành công!")
                        st.rerun()

            with st.container(height=240):
                edited_df = st.data_editor(
                    df_display, 
                    num_rows="dynamic", 
                    use_container_width=True,
                    disabled=["STT", "Khoảng cách (m)"]
                )
            
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

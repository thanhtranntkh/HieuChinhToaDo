import streamlit as st
import pandas as pd
import numpy as np
import pyproj
import folium
from folium import plugins
from streamlit_folium import st_folium
import io
from google import genai

# --- CẤU HÌNH API GEMINI ---
# Bạn có thể nhập API Key trực tiếp hoặc lấy từ st.secrets
GEMINI_API_KEY = st.sidebar.text_input("Nhập Google Gemini API Key:", type="password")

def ask_gemini_for_direction(broken_info_text, kinh_tuyen_truc):
    if not GEMINI_API_KEY:
        return "⚠️ Vui lòng nhập Gemini API Key ở thanh bên (sidebar) để sử dụng tính năng phân tích thông minh."
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        prompt = f"""
        Bạn là một kỹ sư trắc địa và chuyên gia GIS hàng đầu Việt Nam. 
        Tôi có một file tọa độ VN-2000 (Kinh tuyến trục {kinh_tuyen_truc}) đang gặp các điểm đứt đoạn hình học sau:
        {broken_info_text}
        
        Hãy phân tích theo góc nhìn tiến của tuyến (từ mốc trước đến mốc hiện tại):
        1. Xác định các mốc bị đứt đoạn/văng nằm lệch về **bên phải hay bên trái** theo hướng nhìn của tuyến.
        2. Đề xuất phương án xử lý cụ thể cho từng vị trí (nên nối vào đâu, dịch chuyển hay sắp xếp lại thế nào) bằng văn phong kỹ thuật chuyên nghiệp, ngắn gọn, dễ hiểu.
        """
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        return response.text
    except Exception as e:
        return f"Lỗi kết nối Gemini API: {e}"

# (Phần cấu hình VN-2000, analyze_data, giao diện Streamlit giữ nguyên như các phiên bản trước...)

# -*- coding: utf-8 -*-
"""
Điểm khởi chạy chính của ứng dụng Streamlit.

    streamlit run app.py

Lưu ý: st.set_page_config() phải là lệnh Streamlit đầu tiên được thực thi.
"""
import sys
from pathlib import Path
import streamlit as st

# Thêm thư mục hiện tại vào sys.path để đảm bảo Python luôn tìm thấy các module
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Nạp cấu hình trang đầu tiên
try:
    from config import PAGE_CONFIG
except ImportError:
    from smart_logistics.config import PAGE_CONFIG

st.set_page_config(**PAGE_CONFIG)

# Import hàm giao diện chính sau khi đã khởi tạo page_config
try:
    from web_handlers import main
except ImportError:
    from smart_logistics.web_handlers import main

if __name__ == "__main__":
    main()

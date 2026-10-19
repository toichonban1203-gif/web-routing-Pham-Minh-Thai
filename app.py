# -*- coding: utf-8 -*-
"""
Điểm khởi chạy chính của ứng dụng Streamlit.
    streamlit run app.py
"""
import sys
from pathlib import Path
import streamlit as st

# Đảm bảo đường dẫn thư mục gốc luôn nằm trong sys.path
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import PAGE_CONFIG

st.set_page_config(**PAGE_CONFIG)

from web_handlers import main

if __name__ == "__main__":
    main()

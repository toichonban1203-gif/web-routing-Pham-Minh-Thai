# -*- coding: utf-8 -*-
"""
Điểm khởi chạy của ứng dụng.

    streamlit run app.py

Lưu ý: st.set_page_config() phải là lệnh Streamlit đầu tiên, vì vậy nó được gọi
TRƯỚC khi import các module giao diện. (config.py không import streamlit nên an toàn.)
"""
import streamlit as st

from config import PAGE_CONFIG

st.set_page_config(**PAGE_CONFIG)

from web_handlers import main  # noqa: E402

if __name__ == "__main__":
    main()

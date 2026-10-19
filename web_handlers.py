# -*- coding: utf-8 -*-
"""
PHẦN 4 — WEB ROUTES & FORM HANDLERS
===================================
"""
from __future__ import annotations

import datetime as dt
import math
import os
import re

import pandas as pd
import streamlit as st

from config import (
    BASE_DIR, FIELDS, INPUT_MODES, LICENSE_LIST, LICENSE_RANKS, NONE, OUT_CUSTOMER, OUT_FLEET,
    OUT_ORDERS, OUT_PRODUCT, OUT_SOLVING, OUT_WAREHOUSE, PRODUCT_FIELDS, UPLOAD_TYPES, VEHICLE_FIELDS,
    WAREHOUSE_FIELDS, XLSX_MIME, Config, UserError,
)
from data_cleaning import (
    basic_semantic_mapping, build_colmap, fleet_profile_score, fleet_validate_output, get_input,
    is_hanoi_address, load_data_flexible, load_warehouse_coords, mem_kb, optimize_dtypes,
    orders_semantic_mapping, orders_validate_output, pick, process_order_with_geocode,
    process_product, process_vehicle, process_warehouse, product_validate_output, read_any,
    read_dim_file, require_files, run_orders_solving, save_outputs, warehouse_validate_output,
)
from optimization import route_total, simulate_all


def conf_icon_ui(score):
    return "🟢" if score >= 0.75 else ("🟡" if score >= 0.55 else "🟠")


def money(x) -> str:
    return f"{float(x):,.0f}"


def render_input_block(prefix, label, seed_df):
    mode = st.radio(f"Cách nhập dữ liệu {label}", INPUT_MODES, horizontal=True, key=f"{prefix}_mode")
    edited, uploaded = None, None
    if mode == INPUT_MODES[0]:
        st.markdown(f"##### ✍️ Nhập trực tiếp danh mục {label}")
        seed_key = f"{prefix}_seed"
        if seed_key not in st.session_state:
            st.session_state[seed_key] = seed_df.copy()
        else:
            if prefix == "fleet" and "Max_Distance" not in st.session_state[seed_key].columns:
                st.session_state[seed_key]["Max_Distance"] = 100.0
        edited = st.data_editor(st.session_state[seed_key], num_rows="dynamic", key=f"{prefix}_editor")
    else:
        st.markdown(f"##### 📂 Upload file {label}")
        uploaded = st.file_uploader(f"File {label}", type=UPLOAD_TYPES, key=f"{prefix}_upload")
        if uploaded is not None:
            try:
                preview = read_any(uploaded)
                st.caption(f"📄 `{uploaded.name}` — {len(preview)} dòng × {len(preview.columns)} cột")
                st.dataframe(preview.head(10))
            except Exception as exc: st.error(f"❌ Không đọc được file: {exc}")
    return mode, edited, uploaded


def run_scan(prefix, label, mode, uploaded, edited, mapping_fn):
    try:
        raw = get_input(mode, uploaded, edited, label)
        mapping = mapping_fn(raw)
    except UserError as exc:
        st.error(f"❌ {exc}"); return False
    except Exception as exc:
        st.error(f"❌ Lỗi khi quét dữ liệu: {exc}"); return False
    st.session_state[f"{prefix}_raw"] = raw
    st.session_state[f"{prefix}_meta"] = {f: m[1] for f, m in mapping.items()}
    st.session_state[f"{prefix}_why"] = {f: (m[2] if len(m) > 2 else "") for f, m in mapping.items()}
    for f, m in mapping.items():
        st.session_state[f"{prefix}_col_{f}"] = str(m[0]) if m[0] is not None else NONE
    st.session_state.pop(f"{prefix}_result", None)
    return True


def render_mapping(prefix, fields, raw):
    meta = st.session_state.get(f"{prefix}_meta", {})
    why = st.session_state.get(f"{prefix}_why", {})
    choices = [NONE] + [str(c) for c in raw.columns]
    chosen = {}
    cols = st.columns(2)
    for i, fld in enumerate(fields):
        key = f"{prefix}_col_{fld}"
        if st.session_state.get(key) not in choices: st.session_state[key] = NONE
        with cols[i % 2]:
            chosen[fld] = st.selectbox(f"`{fld}` ← cột nào?", choices, key=key)
            score = meta.get(fld, 0.0)
            note = why.get(fld, "")
            if score <= 0: st.caption("⚪ Không tìm thấy cột phù hợp")
            else: st.caption(f"{conf_icon_ui(score)} Độ tin cậy: {score:.0%}" + (f" · {note}" if note else ""))
    return chosen


def store_result(prefix, df, files, summary, metrics, extra=None):
    st.session_state[f"{prefix}_result"] = {
        "df": optimize_dtypes(df, categorize=True), "files": list(files), "summary": summary,
        "metrics": metrics, "extra": extra or {}, "ram_before_kb": mem_kb(df),
    }


def render_result(prefix, title):
    res = st.session_state.get(f"{prefix}_result")
    if not res: return None
    st.markdown(f"### {title}")
    st.success(res["summary"])
    if res["metrics"]:
        cols = st.columns(len(res["metrics"]))
        for c, (lab, val) in zip(cols, res["metrics"]): c.metric(lab, val)
    st.dataframe(res["df"])
    st.caption(f"🧠 RAM kết quả: {mem_kb(res['df']):,.1f} KB (gốc {res.get('ram_before_kb', 0):,.1f} KB)")
    rel = ", ".join(f"`{os.path.relpath(p, BASE_DIR)}`" for p in res["files"])
    st.info(f"📁 Thư mục lưu: {rel}")
    cols = st.columns(len(res["files"]))
    for c, path in zip(cols, res["files"]):
        if os.path.exists(path):
            with open(path, "rb") as fh: data = fh.read()
            mime = XLSX_MIME if path.endswith(".xlsx") else "application/json"
            c.download_button(f"⬇️ Tải {os.path.basename(path)}", data, file_name=os.path.basename(path), mime=mime, key=f"{prefix}_dl_{os.path.basename(path)}")
    return res


def fleet_empty_table():
    return pd.DataFrame({
        "vehicle_id": ["VEH_01", "VEH_02", "VEH_06"],
        "license_plate": ["29C-123.45", "29C-678.90", "29C-888.88"],
        "id_warehouse": ["WH_HN_01", "WH_HN_01", "WH_HN_01"],
        "max_weight_kg": [5000, 2000, 4000],
        "max_volume_m3": [20, 10, 15],
        "average_speed_kmh": [50, 45, 40],
        "Max_Distance": [80, 100, 120],
        "fixed_cost": [500000, 300000, 400000],
        "variable_cost": [5000, 4000, 4500],
    })


def render_fleet_tab():
    st.header("🚚 Quản lý Hạm đội Xe (Fleet)")
    mode, edited, uploaded = render_input_block("fleet", "phương tiện", fleet_empty_table())
    if st.button("🔍 Quét & Semantic Mapping", key="fleet_scan", type="primary"):
        run_scan("fleet", "phương tiện", mode, uploaded, edited, lambda df: basic_semantic_mapping(df, VEHICLE_FIELDS, fleet_profile_score, 0.35))
    raw = st.session_state.get("fleet_raw")
    if raw is None: return
    chosen = render_mapping("fleet", list(VEHICLE_FIELDS), raw)
    if st.button("🚀 Chuẩn hóa & Xử lý Fleet", key="fleet_process", type="primary"):
        colmap = build_colmap(raw, chosen)
        rows = [process_vehicle({f: pick(r, colmap, f, None) for f in VEHICLE_FIELDS}) for _, r in raw.iterrows()]
        out = fleet_validate_output(pd.DataFrame(rows))
        files = save_outputs(OUT_FLEET, "DIM_VEHICLE", "DIM_VEHICLE", out)
        ok = int(out["kiểm_tra"].astype(str).str.startswith("✅").sum())
        store_result("fleet", out, files, "🧭 Hoàn tất chuẩn hóa phương tiện", [("Tổng loại xe", len(out)), ("Hợp lệ", f"{ok}/{len(out)}")])
    render_result("fleet", "📊 Kết quả Hạm đội")


def render_warehouse_tab():
    st.header("🏭 Kho & Tọa độ (Warehouse)")
    do_geo = st.checkbox("🌍 Bật ArcGIS Geocoding", value=True, key="wh_do_geo")
    mode, edited, uploaded = render_input_block("wh", "kho", pd.DataFrame({"id_warehouse": ["WH_HN_01"], "address": ["Số 1 Tràng Tiền, Hoàn Kiếm, Hà Nội"]}))
    if st.button("🔍 Quét & Mapping", key="wh_scan", type="primary"):
        run_scan("wh", "kho", mode, uploaded, edited, lambda df: basic_semantic_mapping(df, WAREHOUSE_FIELDS, lambda s, f: 0.8, 0.40))
    raw = st.session_state.get("wh_raw")
    if raw is None: return
    chosen = render_mapping("wh", list(WAREHOUSE_FIELDS), raw)
    if st.button("🚀 Xử lý Kho & Geocoding", key="wh_process", type="primary"):
        colmap = build_colmap(raw, chosen)
        rows = [process_warehouse(row.get(colmap.get("id_warehouse")), row.get(colmap.get("address")), do_geocode=do_geo) for _, row in raw.iterrows()]
        out = warehouse_validate_output(pd.DataFrame(rows))
        files = save_outputs(OUT_WAREHOUSE, "WAREHOUSE_WITH_COORDINATES", "DIM_WAREHOUSE", out)
        store_result("wh", out, files, "🧭 Hoàn tất quét tọa độ kho", [("Tổng số kho", len(out))])
    res = render_result("wh", "📊 Kết quả Kho")
    if res is not None and not res["df"].dropna(subset=["lat", "lng"]).empty:
        st.map(res["df"].dropna(subset=["lat", "lng"]).rename(columns={"lng": "lon"})[["lat", "lon"]])


def render_product_tab():
    st.header("📦 Quản lý Sản phẩm (Product)")
    mode, edited, uploaded = render_input_block("product", "sản phẩm", pd.DataFrame({"product_id": ["SP_01"], "product_name": ["Ghế Sofa"], "length_cm": [120.0], "width_cm": [80.0], "height_cm": [90.0], "weight": [25.0], "selling_price": [2500000]}))
    if st.button("🔍 Quét & Mapping", key="product_scan", type="primary"):
        run_scan("product", "sản phẩm", mode, uploaded, edited, lambda df: basic_semantic_mapping(df, PRODUCT_FIELDS, lambda s, f: 0.8, 0.35))
    raw = st.session_state.get("product_raw")
    if raw is None: return
    chosen = render_mapping("product", list(PRODUCT_FIELDS), raw)
    if st.button("🚀 Chuẩn hóa Sản phẩm", key="product_process", type="primary"):
        colmap = build_colmap(raw, chosen)
        rows = [process_product({f: pick(r, colmap, f, None) for f in PRODUCT_FIELDS}) for _, r in raw.iterrows()]
        out = product_validate_output(pd.DataFrame(rows))
        files = save_outputs(OUT_PRODUCT, "DIM_PRODUCT", "DIM_PRODUCT", out)
        store_result("product", out, files, "🧭 Hoàn tất chuẩn hóa sản phẩm & tính thể tích m3", [("Tổng sản phẩm", len(out))])
    render_result("product", "📊 Kết quả Sản phẩm")


def render_orders_tab():
    st.header("🧾 Quản lý Đơn hàng & Quét Tọa độ (Orders)")
    do_geo = st.checkbox("🌍 Tự động quét ArcGIS Geocoding cho Location/Address đơn hàng", value=True, key="ord_do_geo")
    mode, edited, uploaded = render_input_block("orders", "đơn hàng", pd.DataFrame({"order_id": ["ORD_003"], "customer_name": ["Nguyễn Văn A"], "items": ["SP_01"], "quantity": [2], "address": ["Số 1 Tràng Tiền, Hà Nội"], "total_weight_kg": [10.5]}))
    if st.button("🔍 Quét & Mapping", key="orders_scan", type="primary"):
        run_scan("orders", "đơn hàng", mode, uploaded, edited, orders_semantic_mapping)
    raw = st.session_state.get("orders_raw")
    if raw is None: return
    chosen = render_mapping("orders", FIELDS, raw)
    if st.button("🚀 Chuẩn hóa & Quét Tọa độ Đơn hàng", key="orders_process", type="primary"):
        colmap = build_colmap(raw, chosen)
        rows = []
        with st.spinner("Đang chuẩn hóa & quét ArcGIS Geocoding địa chỉ đơn hàng..."):
            for _, row in raw.iterrows():
                rows.append(process_order_with_geocode({f: row.get(c) for f, c in colmap.items()}, do_geocode=do_geo))
        out = orders_validate_output(pd.DataFrame(rows))

        files = save_outputs(OUT_ORDERS, "DIM_ORDERS", "DIM_ORDERS", out)

        mask_failed = out["trạng_thái_geocode"] != "✅ Thành công"
        df_failed = out[mask_failed].copy().reset_index(drop=True)

        df_success = out[~mask_failed].copy()
        mask_hanoi = df_success["address"].apply(is_hanoi_address)
        df_hanoi = df_success[mask_hanoi].copy().reset_index(drop=True)
        df_outside = df_success[~mask_hanoi].copy().reset_index(drop=True)

        file_hn = save_outputs(OUT_ORDERS, "DIM_ORDERS_HA_NOI", "DIM_ORDERS_HA_NOI", df_hanoi)
        file_out = save_outputs(OUT_ORDERS, "DIM_ORDERS_OUTSIDE_HN", "DIM_ORDERS_OUTSIDE_HN", df_outside)
        file_err = save_outputs(OUT_ORDERS, "DIM_ORDERS_FAILED", "DIM_ORDERS_FAILED", df_failed)

        files.extend([file_hn[0], file_out[0], file_err[0]])

        cust_df = out.dropna(subset=["lat", "lng"])[["customer_id", "customer_name", "address", "lat", "lng", "trạng_thái_geocode"]].drop_duplicates(subset=["customer_id"])
        save_outputs(OUT_CUSTOMER, "DATASET_CUSTOMER", "DATASET_CUSTOMER", cust_df)

        extra = {
            "df_hanoi": optimize_dtypes(df_hanoi, categorize=True),
            "df_outside": optimize_dtypes(df_outside, categorize=True),
            "df_failed": optimize_dtypes(df_failed, categorize=True),
        }

        store_result("orders", out, files, "🧭 Hoàn tất chuẩn hóa & phân loại đơn hàng", [
            ("Tổng số đơn", len(out)),
            ("Đơn Hà Nội", len(df_hanoi)),
            ("Đơn Ngoài Hà Nội", len(df_outside)),
            ("Lỗi Geocode", len(df_failed))
        ], extra=extra)

    res = st.session_state.get("orders_result")
    if res is not None:
        st.markdown("### 📊 Kết quả Phân Loại Đơn Hàng")
        st.success(res["summary"])

        if res["metrics"]:
            cols = st.columns(len(res["metrics"]))
            for c, (lab, val) in zip(cols, res["metrics"]): c.metric(lab, val)

        extra = res.get("extra", {})
        df_hn = extra.get("df_hanoi", pd.DataFrame())
        df_out = extra.get("df_outside", pd.DataFrame())
        df_fail = extra.get("df_failed", pd.DataFrame())

        t_hn, t_out, t_fail, t_all = st.tabs([
            f"🏢 1. Đơn tại Hà Nội ({len(df_hn)})",
            f"🌏 2. Đơn ngoài Hà Nội ({len(df_out)})",
            f"⚠️ 3. Không quét được tọa độ ({len(df_fail)})",
            f"📋 4. Tất cả đơn tổng ({len(res['df'])})"
        ])

        with t_hn:
            st.markdown("##### 🏢 Danh sách các đơn hàng thuộc khu vực Hà Nội")
            st.dataframe(df_hn, use_container_width=True)

        with t_out:
            st.markdown("##### 🌏 Danh sách các đơn hàng ngoài khu vực Hà Nội")
            st.dataframe(df_out, use_container_width=True)

        with t_fail:
            st.markdown("##### ⚠️ Danh sách các đơn hàng không quét được tọa độ")
            st.dataframe(df_fail, use_container_width=True)

        with t_all:
            st.markdown("##### 📋 Bảng tổng hợp tất cả đơn hàng")
            st.dataframe(res["df"], use_container_width=True)

        st.caption(f"🧠 RAM kết quả: {mem_kb(res['df']):,.1f} KB")
        rel = ", ".join(f"`{os.path.relpath(p, BASE_DIR)}`" for p in res["files"])
        st.info(f"📁 Thư mục lưu các file: {rel}")

        cols = st.columns(min(len(res["files"]), 4))
        for i, path in enumerate(res["files"]):
            if os.path.exists(path):
                with open(path, "rb") as fh: data = fh.read()
                mime = XLSX_MIME if path.endswith(".xlsx") else "application/json"
                cols[i % 4].download_button(f"⬇️ Tải {os.path.basename(path)}", data, file_name=os.path.basename(path), mime=mime, key=f"orders_dl_{os.path.basename(path)}_{i}")


def render_orders_solving_tab():
    st.header("🧩 Tab 5 — Orders Solving (Phân loại Hàng BBS A/B & Thống Kê Tỉnh Thành)")
    st.caption("Khớp mã sản phẩm từ Tab Orders với DIM_PRODUCT để lấy Dài × Rộng × Cao, tính Trọng lượng quy đổi Thể tích và Phân loại BBS A/B.")

    cfg = Config()
    if not os.path.exists(cfg.order_file):
        st.warning("⚠️ Chưa tìm thấy `DIM_ORDERS.xlsx`. Vui lòng chạy Tab 4 (Orders) trước.")
        return

    df_orders = read_dim_file(cfg.order_file)
    df_products = read_dim_file(cfg.product_file) if os.path.exists(cfg.product_file) else pd.DataFrame()

    c1, c2 = st.columns(2)
    c1.metric("Tổng đơn nhận từ Tab 4", len(df_orders))
    c2.metric("Danh mục SP khớp từ Tab 3", len(df_products))

    if st.button("⚡ Chạy Phân Loại BBS A/B & Gom Nhóm Tỉnh Thành", type="primary", key="btn_run_solving"):
        with st.spinner("Đang khớp thông số 3D & phân loại BBS A/B..."):
            df_solved, prov_summary = run_orders_solving(df_orders, df_products)

        files = save_outputs(OUT_SOLVING, "DIM_ORDERS_SOLVED", "DIM_ORDERS_SOLVED", df_solved,
                             extra_sheets={"SUMMARY_PROVINCE": prov_summary})

        store_result("orders_solving", df_solved, files, "🧭 Hoàn tất giải mã & phân loại BBS A/B", [
            ("Tổng đơn xử lý", len(df_solved)),
            ("Loại A (Cồng kềnh - BBS)", int((df_solved["BBS_code"] == "A").sum())),
            ("Loại B (Hàng nặng)", int((df_solved["BBS_code"] == "B").sum())),
            ("Tổng Tỉnh/Thành", len(prov_summary))
        ], extra={"prov_summary": prov_summary})

        st.success("🎉 Đã xuất file `DIM_ORDERS_SOLVED.xlsx` vào thư mục `output_solving` thành công!")

    res = st.session_state.get("orders_solving_result")
    if res is not None:
        st.markdown("### 📊 Kết quả Phân Loại BBS & Thống Kê Tỉnh Thành")
        st.success(res["summary"])

        if res["metrics"]:
            cols = st.columns(len(res["metrics"]))
            for c, (lab, val) in zip(cols, res["metrics"]): c.metric(lab, val)

        prov_sum = res.get("extra", {}).get("prov_summary", pd.DataFrame())

        t1, t2 = st.tabs(["📦 1. Danh sách đơn đã phân loại BBS A/B", "📊 2. Thống kê Gom nhóm theo Tỉnh/Thành phố"])

        with t1:
            st.dataframe(res["df"], use_container_width=True)

        with t2:
            st.markdown("##### 🏢 Bảng tổng hợp số lượng đơn & tải trọng theo Tỉnh/Thành phố")
            st.dataframe(prov_sum, use_container_width=True)


def file_status(cfg: Config) -> pd.DataFrame:
    items = [
        ("Tab 1 · Hạm đội xe", cfg.vehicle_file, "Bắt buộc"),
        ("Tab 2 · Kho & Tọa độ", cfg.warehouse_file, "Khuyến nghị"),
        ("Tab 3 · Sản phẩm", cfg.product_file, "Tuỳ chọn"),
        ("Tab 4 · Đơn hàng (Đã geocode)", cfg.order_file, "Bắt buộc"),
        ("Tab 5 · Đơn hàng đã Phân Loại BBS", os.path.join(OUT_SOLVING, "DIM_ORDERS_SOLVED.xlsx"), "Ưu tiên cao"),
    ]
    rows = [{"Nguồn": n, "File": os.path.relpath(p, BASE_DIR), "Trạng thái": "✅ Có" if os.path.exists(p) else "❌ Chưa có", "Yêu cầu": need}
            for n, p, need in items]
    return pd.DataFrame(rows)


def depot_options(cfg: Config) -> dict:
    opts = {"Mặc định Hà Nội (21.0285, 105.8542)": (21.0285, 105.8542)}
    for wid, (la, lo) in load_warehouse_coords(cfg).items():
        opts[f"Kho {wid} ({la:.4f}, {lo:.4f})"] = (la, lo)
    return opts


def tag_routes(day):
    return [(r, "Thường") for r in day["routes"]] + [(r, "Quá hạn (ưu tiên)") for r in day["overdue_routes"]]


def route_label(idx, r, wh_info) -> str:
    wh = wh_info.get(r["id_warehouse"], {"name": r["id_warehouse"]})
    return f"Tuyến {wh['name']} #{idx}"


def route_load(r):
    return sum(o["total_weight_kg"] for o in r["orders"]), sum(o["total_volume_m3"] for o in r["orders"])


def route_items_detail(r) -> str:
    item_map = {}
    for o in r["orders"]:
        it_name = o.get("items") or "Hàng tiêu chuẩn"
        q = o.get("quantity", 1)
        w = o.get("total_weight_kg", 0.0)
        v = o.get("total_volume_m3", 0.0)

        if it_name not in item_map:
            item_map[it_name] = {"qty": 0, "w": 0.0, "v": 0.0}
        item_map[it_name]["qty"] += q
        item_map[it_name]["w"] += w
        item_map[it_name]["v"] += v

    parts = []
    for it, d in item_map.items():
        parts.append(f"{d['qty']} x {it} ({d['w']:,.0f}kg | {d['v']:.2f}m³)")
    return " + ".join(parts)


def route_vehicle_text(r) -> str:
    reason_text = r.get("reason") or "Vượt khả năng xe nhà"
    if r["external"]:
        return f"🟣 Thuê ngoài 3PL — {r['vehicle_type']} (Lý do: {reason_text})"
    if r["kind"] == "SPLIT":
        return f"🚚 {r['vehicle_type']} + 3PL {r['outsourcing_type']} (Lý do: {reason_text})"
    return "🚚 " + str(r["vehicle_type"])


def routes_to_df(tagged_routes, wh_info, cfg: Config) -> pd.DataFrame:
    rows = []
    for idx, (r, kind) in enumerate(tagged_routes, 1):
        locs = sorted({re.split(r",|\s-\s", o["address"])[-1].strip() for o in r["orders"] if o["address"]})
        tw, tv = route_load(r)
        tq = sum(o.get("quantity", 1) for o in r["orders"])
        items_detail = route_items_detail(r)

        rows.append({
            "MÃ TUYẾN": route_label(idx, r, wh_info),
            "KHU VỰC / TỈNH": ", ".join(locs),
            "LOẠI": kind,
            "THỨ TỰ KHÁCH GHÉP": " → ".join(r["route"]),
            "ĐƠN GIAO": ", ".join(o["order_id"] for o in r["orders"]),
            "SỐ ĐƠN": len(r["orders"]),
            "TỔNG UNITS": tq,
            "CHI TIẾT MẶT HÀNG & ĐƠN VỊ": items_detail,
            "TỔNG TRỌNG TẢI (kg)": round(tw, 1),
            "TỔNG THỂ TÍCH (m³)": round(tv, 2),
            "TẢI TRỌNG XE (kg)": round(float(r.get("cap_w", 0.0)), 1),
            "THỂ TÍCH XE (m³)": round(float(r.get("cap_v", 0.0)), 2),
            "TÀI XẾ CHÍNH": r.get("driver_primary", "Chờ phân công"),
            "PHỤ XE": r.get("driver_assistant", "—"),
            "XE": route_vehicle_text(r),
            "BIỂN SỐ": r["license_plate"],
            "CHUYẾN": f"{r['trip_no']}/{cfg.vehicle_daily_count}" if r.get("trip_no") else "—",
            "QUÃNG ĐƯỜNG (km)": r["km"],
            "LẤP ĐẦY (%)": round(r["load_factor"] * 100, 1),
            "THỜI GIAN (giờ)": round(r["hours"], 2),
            "TỔNG CHI PHÍ (đ)": round(route_total(r)) if route_total(r) > 0 else "Chờ nhập giá 3PL",
            "BẮT ĐẦU": f"{r['start']:%H:%M}",
            "KẾT THÚC": f"{r['end']:%H:%M}",
            "TRẠNG THÁI": ("🟣 Cần xe 3PL Full" if (r["external"] and "FULL" in str(r.get("vehicle_id", "")).upper()) else
                           ("🟣 Giao bởi 3PL Tiết kiệm" if r["external"] else ("🟠 Tách: xe nhà + 3PL" if r["kind"] == "SPLIT" else
                           ("✅ Đã tối ưu" if r["hours"] <= cfg.max_route_hours + 1e-9 else "⚠️ Vượt giới hạn giờ")))),
        })
    return pd.DataFrame(rows)


def render_routing_settings():
    with st.expander("⚙️ Tham số mô hình & Ngưỡng thuê ngoài Tiết kiệm", expanded=True):
        c_mode, c1, c2 = st.columns(3)
        constraint_mode = c_mode.selectbox(
            "📦 Đặc thù hàng hóa (Lấp đầy theo)",
            ["Cube Out (Thể tích m³)", "Weight Out (Trọng tải kg)"],
            index=0, key="cfg_constraint_mode"
        )
        start_time = c1.text_input("Giờ xuất phát (HH:MM)", "08:30", key="cfg_start")
        max_hours = c2.number_input("Giới hạn giờ / tuyến", 1.0, 24.0, 8.0, 0.5, key="cfg_maxh")

        c3, c4, c5 = st.columns(3)
        detour = c3.number_input("Hệ số đường vòng (Haversine)", 1.0, 3.0, 1.2, 0.05, key="cfg_detour")
        svc_b2b = c4.number_input("Bốc/dỡ B2B (phút)", 0, 600, 105, 5, key="cfg_b2b")
        svc_b2c = c5.number_input("Bốc/dỡ B2C (phút)", 0, 600, 60, 5, key="cfg_b2c")

        c6, c7, c8 = st.columns(3)
        backup = c6.number_input("Chi phí tài xế dự phòng (đ)", 0, 10_000_000, 400_000, 50_000, key="cfg_backup")
        trips = c7.number_input("Số chuyến tối đa / xe / ngày", 1, 5, 2, 1, key="cfg_trips")
        turn = c8.number_input("Thời gian quay đầu giữa 2 chuyến (phút)", 0, 240, 30, 5, key="cfg_turn")

        st.markdown("##### 🚛 Chi phí thuê ngoài Tiết kiệm")
        o2, o3 = st.columns(2)
        s1_p = o2.number_input("Tiết kiệm loại 1 (đ)", 0.0, 100_000_000.0, 800_000.0, 50_000.0, key="cfg_s1_p")
        s2_p = o3.number_input("Tiết kiệm loại 2 (đ)", 0.0, 100_000_000.0, 300_000.0, 50_000.0, key="cfg_s2_p")

    base_cfg = Config()
    opts = depot_options(base_cfg)
    if st.session_state.get("cfg_depot") not in opts:
        st.session_state["cfg_depot"] = list(opts)[0]
    depot_label = st.selectbox("Kho xuất phát cho Clarke-Wright", list(opts), key="cfg_depot")
    try: dt.datetime.strptime(start_time, "%H:%M")
    except ValueError: start_time = "08:30"

    cfg = Config(start_time=start_time, max_route_hours=float(max_hours), detour_factor=float(detour),
                 constraint_mode=constraint_mode,
                 service_min={"B2B": int(svc_b2b), "B2C": int(svc_b2c)}, backup_driver_cost=float(backup), vehicle_daily_count=int(trips), turnaround_min=float(turn),
                 saving_1_price=float(s1_p), saving_2_price=float(s2_p))
    return cfg, opts[depot_label]


def render_routing_tab():
    st.header("🗺️ Dashboard Định tuyến — Clarke-Wright")
    cfg, depot = render_routing_settings()
    st.markdown("### 📂 Trạng thái dữ liệu đầu vào")
    st.dataframe(file_status(cfg), hide_index=True)

    if st.button("⚡ Chạy Routing Tạm Thời", type="primary", key="t6_run_temp"):
        require_files(cfg, ["orders", "fleet"])

        solved_res = st.session_state.get("orders_solving_result")
        source_df = solved_res["df"] if solved_res else None

        data = load_data_flexible(cfg, source_df=source_df)
        planner, days, kpis, total_cost = simulate_all(data, cfg)
        st.session_state["t6_temp_plan"] = {"planner": planner, "days": days, "kpis": kpis, "cfg": cfg, "data": data}
        st.session_state.pop("t6_final_plan", None)
        st.success("✅ Đã chạy xong bước tạm thời! Mời xem 3 bảng phân loại bên dưới.")

    plan = st.session_state.get("t6_temp_plan")
    if not plan: return

    planner, days, kpis, cfg, data = plan["planner"], plan["days"], plan["kpis"], plan["cfg"], plan["data"]
    dates = list(days)
    if not dates: return
    date_str = st.selectbox("📅 Chọn ngày điều phối", dates, key="t6_date_temp")
    day = days[date_str]
    tagged = tag_routes(day)

    st.divider()
    st.markdown(f"## 📊 1. BẢNG ROUTING TẠM THỜI — {date_str}")

    routed_orders_count = sum(len(r["orders"]) for r, _ in tagged)
    g = st.columns(2)
    g[0].metric("Tổng số tuyến được phân", len(tagged))
    g[1].metric("Tổng số đơn đã phân tuyến", routed_orders_count)

    # ------------------------------------------------------------------------
    # PHÂN LOẠI THÀNH 3 DANH SÁCH RIÊNG BIỆT
    # ------------------------------------------------------------------------
    # ------------------------------------------------------------------------
    # PHÂN LOẠI 3 BẢNG CHUẨN XÁC
    # ------------------------------------------------------------------------
    tagged_inhouse = []      # Bảng 1: Xe nhà
    tagged_saving = []       # Bảng 2: 3PL Tiết kiệm
    tagged_3pl_full = []     # Bảng 3: 3PL Full & Tách chuyến

    for item in tagged:
        r, kind = item
        is_ext = r.get("external", False)
        v_id = str(r.get("vehicle_id", "")).upper()
        r_kind = str(r.get("kind", "")).upper()

        # 1. Xe nhà chạy bình thường (Không thuê ngoài, không tách chuyến)
        if not is_ext and r_kind != "SPLIT":
            tagged_inhouse.append(item)
        
        # 2. Xe 3PL Tiết kiệm (Chứa chữ SAVING hoặc Tiết kiệm)
        elif is_ext and ("SAVING" in v_id or "TIẾT KIỆM" in str(r.get("outsourcing_type", "")).upper()):
            tagged_saving.append(item)
            
        # 3. Xe 3PL Full hoặc Tách chuyến (SPLIT)
        else:
            tagged_3pl_full.append(item)

    rdf_inhouse = routes_to_df(tagged_inhouse, planner.wh, cfg) if tagged_inhouse else pd.DataFrame()
    rdf_saving = routes_to_df(tagged_saving, planner.wh, cfg) if tagged_saving else pd.DataFrame()
    rdf_3pl_full = routes_to_df(tagged_3pl_full, planner.wh, cfg) if tagged_3pl_full else pd.DataFrame()

    cols_to_show = lambda df: [c for c in df.columns if c not in ("TÀI XẾ CHÍNH", "PHỤ XE")]

    # --- BẢNG 1: XE NHÀ ---
    st.markdown(f"### 🚚 Bảng 1: Tuyến do Đội Xe Nhà Thực Hiện ({len(tagged_inhouse)} tuyến)")
    if not rdf_inhouse.empty:
        st.dataframe(rdf_inhouse[cols_to_show(rdf_inhouse)], hide_index=True, use_container_width=True)
    else:
        st.info("Không có tuyến nào do xe nhà thực hiện.")

    # --- BẢNG 2: 3PL TIẾT KIỆM ---
    st.markdown(f"### 🟢 Bảng 2: Tuyến Giao bởi 3PL Tiết Kiệm (Loại 1 / Loại 2) ({len(tagged_saving)} tuyến)")
    if not rdf_saving.empty:
        st.dataframe(rdf_saving[cols_to_show(rdf_saving)], hide_index=True, use_container_width=True)
    else:
        st.info("Không có tuyến nào thuộc diện 3PL Tiết kiệm.")

    # --- BẢNG 3: 3PL FULL & TÁCH CHUYẾN ---
    st.markdown(f"### 🟣 Bảng 3: Tuyến Cần Thuê Ngoài 3PL Full & Tách Chuyến ({len(tagged_3pl_full)} chuyến)")
    if not rdf_3pl_full.empty:
        st.dataframe(rdf_3pl_full[cols_to_show(rdf_3pl_full)], hide_index=True, use_container_width=True)
    else:
        st.info("Không có chuyến nào cần thuê 3PL Full hoặc Tách chuyến.")

    st.divider()
    st.markdown("## 👨‍✈️ 2. PHÂN CÔNG TÀI XẾ CÔNG TY CHO CÁC XE NHÀ HOẠT ĐỘNG TRONG NGÀY")

    inhouse_routes = [r for r, _ in tagged_inhouse]

    veh_grouped = {}
    for r in inhouse_routes:
        vid = r["vehicle_id"]
        veh_grouped.setdefault(vid, []).append(r)

    if not veh_grouped:
        st.info("🎉 Ngày này toàn bộ đơn giao bằng 3PL, không có xe nhà nào cần phân công tài xế.")
    else:
        st.markdown("Vui lòng nhập tên tài xế hoặc chọn tùy chọn Thuê ngoài tài xế dự phòng bên dưới.")

        assignments = []
        has_driver_error = False

        for idx, (v_id, r_list) in enumerate(veh_grouped.items(), 1):
            r_list.sort(key=lambda x: x["start"])
            first_r = r_list[0]
            v_wh = first_r["id_warehouse"]
            v_cap_w = first_r["cap_w"]

            suggested_lic = "B2" if v_cap_w < 3500 else ("C" if v_cap_w <= 15000 else "FC")

            st.markdown(f"##### 🚚 Xe #{idx}: `{v_id}` (Kho: **{v_wh}** | Tải trọng: **{v_cap_w:,.0f} kg** | **{len(r_list)} chuyến trong ngày**)")

            st.markdown("🕒 **Lịch trình chạy thực tế trong ngày:**")
            for trip_idx, r_item in enumerate(r_list, 1):
                start_s = f"{r_item['start']:%H:%M}"
                end_s = f"{r_item['end']:%H:%M}"
                ord_ids = ", ".join(o["order_id"] for o in r_item["orders"])
                st.caption(f"  • **Lần {trip_idx}:** Từ **{start_s}** đến **{end_s}** ({r_item['hours']:.2f} giờ) — Giao đơn: `{ord_ids}`")

            driver_choice = st.radio(
                f"Hình thức tài xế cho xe `{v_id}`",
                ["Nhập tên tài xế công ty", "Thành phần dự phòng (Thuê ngoài)"],
                horizontal=True,
                key=f"drv_choice_{v_id}_{idx}"
            )

            c1, c2, c3, c4 = st.columns([1.5, 3, 1.5, 2])

            req_lic = c1.selectbox(f"Bằng tối thiểu xe `{v_id}`", LICENSE_LIST, index=LICENSE_LIST.index(suggested_lic), key=f"req_lic_{v_id}_{idx}")

            if driver_choice == "Nhập tên tài xế công ty":
                sel_driver = c2.text_input(f"Nhập Tên Tài xế", placeholder="Ví dụ: Nguyễn Văn A", key=f"drv_name_txt_{v_id}_{idx}").strip()
                cur_lic = c3.selectbox(f"Bằng của tài xế", LICENSE_LIST, index=LICENSE_LIST.index("C"), key=f"drv_lic_inp_{v_id}_{idx}")
                cur_role = c4.text_input(f"Vai trò", value="Tài xế chính", key=f"drv_role_inp_{v_id}_{idx}")

                if not sel_driver:
                    st.warning("⚠️ Vui lòng nhập tên tài xế!")
                    has_driver_error = True
                else:
                    req_rank = LICENSE_RANKS.get(req_lic, 6)
                    drv_rank = LICENSE_RANKS.get(cur_lic, 6)
                    if drv_rank < req_rank:
                        st.error(f"🔴 **Lỗi Bằng Lái:** Tài xế `{sel_driver}` (Bằng `{cur_lic}`) KHÔNG ĐỦ điều kiện lái xe `{v_id}` (Yêu cầu bằng `{req_lic}`).")
                        has_driver_error = True
                    else:
                        st.caption(f"✅ Bằng lái hợp lệ: **{cur_lic}** (Đạt yêu cầu ≥ {req_lic})")
            else:
                sel_driver = "Tài xế dự phòng (Thuê ngoài)"
                cur_lic = "C"
                cur_role = "Tài xế dự phòng"

                c2.text_input(f"Tên Tài xế", value=sel_driver, disabled=True, key=f"drv_name_dis_{v_id}_{idx}")
                c3.text_input(f"Bằng của tài xế", value=cur_lic, disabled=True, key=f"drv_lic_dis_{v_id}_{idx}")
                c4.text_input(f"Vai trò", value=cur_role, disabled=True, key=f"drv_role_dis_{v_id}_{idx}")
                st.info("ℹ️ Sẽ tính thêm chi phí Thuê tài xế dự phòng.")

            assignments.append({"vehicle_id": v_id, "driver_name": sel_driver, "license_type": cur_lic, "role": cur_role})
            st.divider()

    st.divider()
    st.markdown("## 🚛 3. NHẬP LIỆU ĐỘI XE THUÊ NGOÀI (3PL FULL & TÁCH CHUYẾN)")

    full_3pl_routes = [r for r, _ in tagged_3pl_full]

    user_3pl_inputs = []
    if not full_3pl_routes:
        st.info("🎉 Ngày này không có chuyến nào cần thuê ngoài xe 3PL Full!")
    else:
        st.warning(f"⚠️ Phát hiện **{len(full_3pl_routes)} chuyến** cần thuê ngoài 3PL Full. Hãy kiểm tra danh sách mặt hàng & đơn vị bên dưới để chọn/ghép xe 3PL phù hợp.")

        for idx, r in enumerate(full_3pl_routes, 1):
            req_w, req_v = route_load(r)
            req_qty = sum(o.get("quantity", 1) for o in r["orders"])
            items_desc = route_items_detail(r)
            is_split = r["kind"] == "SPLIT"
            tag_type = "Tách chuyến xe nhà + 3PL" if is_split else "Thuần Thuê ngoài 3PL Full"

            st.markdown(f"##### 📌 Chuyến 3PL Full #{idx} (`{tag_type}`)")
            st.markdown(f"📦 **Tổng yêu cầu:** **{req_qty} đơn vị hàng (Units)** | **{req_w:,.1f} kg** | **{req_v:.2f} m³**")
            st.markdown(f"🛍️ **Danh sách mặt hàng cần tải:** `{items_desc}`")
            st.caption(f"↳ Gồm {len(r['orders'])} đơn: {', '.join(o['order_id'] for o in r['orders'])}")

            num_rows_key = f"3pl_num_rows_{date_str}_{idx}"
            if num_rows_key not in st.session_state:
                st.session_state[num_rows_key] = 1

            c_add, c_rem = st.columns([2, 8])
            if c_add.button(f"➕ Thêm 1 xe 3PL cho chuyến #{idx}", key=f"add_row_btn_{idx}"):
                st.session_state[num_rows_key] += 1
                st.rerun()
            if st.session_state[num_rows_key] > 1:
                if c_rem.button(f"➖ Bớt 1 xe 3PL", key=f"rem_row_btn_{idx}"):
                    st.session_state[num_rows_key] -= 1
                    st.rerun()

            route_trucks = []
            total_cap_w, total_cap_v, total_cost = 0.0, 0.0, 0.0

            for row_i in range(1, st.session_state[num_rows_key] + 1):
                st.caption(f"👉 Hàng xe 3PL #{row_i}:")
                r1, r2, r3, r4 = st.columns([2, 1.5, 1.5, 2])

                v_name = r1.text_input(f"Tên xe #{row_i}", f"Xe tải 3PL #{row_i}", key=f"3pl_name_{idx}_{row_i}")
                v_w = r2.number_input(f"Tải trọng (kg) #{row_i}", value=float(math.ceil(req_w / st.session_state[num_rows_key])), step=100.0, key=f"3pl_w_{idx}_{row_i}")
                v_v = r3.number_input(f"Thể tích (m³) #{row_i}", value=float(round(req_v / st.session_state[num_rows_key] + 0.2, 1)), step=0.5, key=f"3pl_v_{idx}_{row_i}")
                v_cost = r4.number_input(f"Giá thuê (đ) #{row_i}", value=2_000_000.0, step=100_000.0, key=f"3pl_cost_{idx}_{row_i}")

                total_cap_w += v_w
                total_cap_v += v_v
                total_cost += v_cost
                route_trucks.append(f"{v_name} ({v_w:,.0f}kg/{v_v:.1f}m³)")

            user_3pl_inputs.append({
                "req_w": req_w, "req_v": req_v, "req_qty": req_qty,
                "name": f"{st.session_state[num_rows_key]} xe 3PL [" + " + ".join(route_trucks) + "]",
                "cap_w": total_cap_w, "cap_v": total_cap_v,
                "cost": total_cost, "route": r
            })
            st.divider()

    if st.button("🚀 Kiểm Tra Điều Kiện & Tính Chi Phí Cuối Cùng", type="primary", key="btn_run_final_all"):
        if 'has_driver_error' in locals() and has_driver_error:
            st.error("❌ Vui lòng sửa lại các lỗi phân công tài xế bị báo đỏ phía trên trước khi tính chi phí cuối cùng!")
            return

        valid_3pl = True
        for idx, item in enumerate(user_3pl_inputs, 1):
            if item["cap_w"] < item["req_w"] - 1e-5 or item["cap_v"] < item["req_v"] - 1e-5:
                st.error(f"❌ Các xe 3PL ghép cho chuyến #{idx} không đủ tải trọng/thể tích! "
                         f"Cần tối thiểu {item['req_qty']} Đơn vị hàng ({item['req_w']:,.1f}kg / {item['req_v']:.2f}m³), nhưng tổng sức tải xe bạn nhập chỉ đạt {item['cap_w']:,.1f}kg / {item['cap_v']:.2f}m³.")
                valid_3pl = False

        if not valid_3pl: return

        assign_map = {a["vehicle_id"]: a for a in 'assignments' in locals() and assignments or []}
        for r, _ in tagged:
            if not r["external"]:
                vid = r["vehicle_id"]
                if vid in assign_map:
                    a = assign_map[vid]
                    if a["driver_name"] != "Tài xế dự phòng (Thuê ngoài)":
                        r["driver_primary"] = a["driver_name"]
                        r["is_backup_driver"] = False
                        r["driver_cost"] = 0.0
                    else:
                        r["driver_primary"] = "Tài xế Dự Phòng (Thuê ngoài)"
                        r["is_backup_driver"] = True
                        r["driver_cost"] = cfg.backup_driver_cost

        for item in user_3pl_inputs:
            r = item["route"]
            r["vehicle_type"] = item["name"]
            r["license_plate"] = "3PL Ghép Chuyến"
            r["cap_w"] = item["cap_w"]
            r["cap_v"] = item["cap_v"]
            r["outsourcing_cost"] = item["cost"]
            r["load_factor"] = item["req_v"] / item["cap_v"] if "Cube Out" in cfg.constraint_mode else item["req_w"] / item["cap_w"]

        day["day_cost"] = sum(route_total(rt) for rt in day["routes"])

        all_day_routes = day["routes"] + day["overdue_routes"]
        inhouse_only_day_routes = [rt for rt in all_day_routes if not rt["external"]]
        avg_load_day = (sum(rt["load_factor"] for rt in inhouse_only_day_routes) / len(inhouse_only_day_routes)) if inhouse_only_day_routes else 0.0

        kpis["operating_cost"] = sum(d["day_cost"] for d in days.values())
        kpis["avg_load_factor"] = avg_load_day

        st.session_state["t6_final_plan"] = plan
        st.success("🎉 Đã phân công tài xế & cập nhật chi phí tổng thành công!")

    final_plan = st.session_state.get("t6_final_plan")
    if final_plan:
        st.divider()
        st.markdown(f"## 🏆 BÁO CÁO KẾT QUẢ ĐIỀU PHỐI CHÍNH THỨC — {date_str}")

        final_day = final_plan["days"][date_str]
        final_tagged = tag_routes(final_day)

        inhouse_only_final_routes = [r for r, _ in final_tagged if not r["external"]]
        avg_load = (sum(r["load_factor"] for r in inhouse_only_final_routes) / len(inhouse_only_final_routes) * 100) if inhouse_only_final_routes else 0.0

        c1, c2, c3 = st.columns(3)
        c1.metric("💰 TỔNG CHI PHÍ PHẢI CHI TRONG NGÀY", money(final_day["day_cost"]) + " VNĐ")
        c2.metric("📦 TỔNG ĐƠN ĐÃ PHÂN TUYẾN", len(final_day["orders"]) - len(final_day.get("unrouted_orders", [])))
        c3.metric("📊 TỈ LỆ LẤP ĐẦY TB (CHỈ XE NHÀ)", f"{avg_load:.1f}%")

        final_rdf = routes_to_df(final_tagged, planner.wh, cfg)
        st.dataframe(final_rdf, hide_index=True)


def handle_road_blocked(order_id):
    return f"[{dt.datetime.now():%H:%M:%S}] 🗺️ [RE-ROUTING] Đường chặn hoàn toàn. OSRM API đã vẽ lộ trình mới né điểm sạt lở cho đơn `{order_id}` (+2.4km)."

def handle_heavy_traffic(order_id):
    return f"[{dt.datetime.now():%H:%M:%S}] ⏱️ [TRAFFIC DELAY] Tắc nghẽn >30 phút. Đã tính lại ETA mới và tự động gửi SMS thông báo cho đơn `{order_id}`."

def handle_truck_ban(vehicle_id):
    return f"[{dt.datetime.now():%H:%M:%S}] 🚫 [CORRIDOR SWITCH] Phát hiện đường cấm tải. Đã chuyển xe `{vehicle_id}` sang hành lang giao thông phụ cận hợp lệ."

def handle_flooded_road():
    return f"[{dt.datetime.now():%H:%M:%S}] 🌧️ [FLOOD BLACKLIST] Đường ngập sâu. Đã đưa tọa độ vào blacklist tạm thời, điều hướng xe leo đường cao."

def handle_short_blockage():
    return f"[{dt.datetime.now():%H:%M:%S}] ⏸️ [HOLD & WAIT] Chắn tàu/Lễ hội (<10 phút). Kích hoạt chế độ tạm dừng trên app tài xế để tiết kiệm xăng."

def handle_driver_lost(driver_id):
    return f"[{dt.datetime.now():%H:%M:%S}] 🧭 [GPS RE-NAVIGATE] Tài xế `{driver_id}` đi nhầm rẽ. Đã phát âm thanh cảnh báo và làm mới bản đồ quay đầu."

def handle_gps_lost():
    return f"[{dt.datetime.now():%H:%M:%S}] 📡 [DEAD RECKONING] Mất sóng GPS hầm. Khóa vị trí Last Known Position và ước tính theo vận tốc quán tính."

def handle_customer_change_address(order_id):
    return f"[{dt.datetime.now():%H:%M:%S}] 🏠 [CLUSTER RE-SEQUENCE] Khách đổi địa chỉ phút chót. Tự động kiểm tra cụm giao và xếp lại thứ tự ghé thăm."

def handle_cust_no_answer(order_id):
    return f"[{dt.datetime.now():%H:%M:%S}] 📞 [UNREACHABLE CUST] Khách không nghe máy. Ghi nhận lịch sử gọi (Lần 1), cho xe đi đơn tiếp và xếp lịch gọi lại."

def handle_cust_absent(order_id):
    return f"[{dt.datetime.now():%H:%M:%S}] 🚪 [CUST ABSENT] Khách vắng mặt. Đánh dấu giao thất bại, tự động phát câu hỏi hẹn lịch giao lại ca sau."

def handle_cust_reject(order_id):
    return f"[{dt.datetime.now():%H:%M:%S}] ❌ [CUST REJECT] Khách từ chối nhận. Ghi nhận lý do, tạo lệnh thu hồi hàng về kho và báo Điều phối viên."

def handle_cust_request_late(order_id):
    return f"[{dt.datetime.now():%H:%M:%S}] 🕰️ [TIME WINDOW LATE] Khách hẹn giao muộn hơn. Cập nhật Time Window mới, đẩy đơn `{order_id}` xuống cuối tuyến."

def handle_cust_request_early(order_id):
    return f"[{dt.datetime.now():%H:%M:%S}] ⚡ [TIME WINDOW EARLY] Khách đòi giao sớm. Đã kiểm tra ETA, đẩy đơn `{order_id}` lên ưu tiên nếu không gãy tuyến khác."

def handle_change_recipient(order_id):
    return f"[{dt.datetime.now():%H:%M:%S}] 👤 [RECIPIENT SWITCH] Đổi người nhận hàng. Yêu cầu tài xế chụp ảnh CCCD/Xác nhận OTP người nhận mới."

def handle_partial_delivery(order_id):
    return f"[{dt.datetime.now():%H:%M:%S}] 📦 [PARTIAL DELIVERY] Khách nhận 1 phần hàng. Cập nhật số lượng đã giao, tạo phiếu lưu kho cho phần còn lại."

def handle_address_not_found(order_id):
    return f"[{dt.datetime.now():%H:%M:%S}] 🔍 [ADDRESS UNVERIFIED] Không tìm thấy địa chỉ. Đánh dấu điểm nghẽn, gửi link Zalo cho khách ghim vị trí."

def handle_truck_breakdown(vehicle_id):
    return f"[{dt.datetime.now():%H:%M:%S}] 🚨 [BREAKDOWN RESCUE] Xe `{vehicle_id}` hỏng giữa đường. Điều xe dự phòng ra cứu hộ & chuyển tải đơn hàng."

def handle_out_of_fuel(vehicle_id):
    return f"[{dt.datetime.now():%H:%M:%S}] ⛽ [FUEL EMERGENCY] Xe `{vehicle_id}` hết nhiên liệu. Định vị trạm cây xăng gần nhất và cập nhật cộng 15phút ETA."

def handle_traffic_accident(vehicle_id):
    return f"[{dt.datetime.now():%H:%M:%S}] 🚑 [ACCIDENT EMERGENCY] Xe gặp tai nạn. Ưu tiên an toàn tài xế, kích hoạt bảo hiểm và điều cứu hộ tái phân công đơn."

def handle_vehicle_overload(order_id):
    return f"[{dt.datetime.now():%H:%M:%S}] ⚖️ [OVERLOAD DETECTED] Hàng thực tế bị quá tải/quá cỡ. Tiến hành tách đơn `{order_id}` hoặc đổi sang xe 3PL lớn hơn."

def handle_cargo_damaged(order_id):
    return f"[{dt.datetime.now():%H:%M:%S}] 💔 [CARGO DAMAGED] Hàng bị móp méo/hư hỏng. Tài xế chụp ảnh hiện trạng, cách ly hàng và báo kho đền bù."

def handle_cargo_missing(order_id):
    return f"[{dt.datetime.now():%H:%M:%S}] ❓

# -*- coding: utf-8 -*-
"""
PHẦN 2 — DATA CLEANING & VALIDATION
===================================
"""
from __future__ import annotations

import io
import json
import os
import re
import time
import datetime as dt

import numpy as np
import pandas as pd
import streamlit as st
from geopy.geocoders import ArcGIS
from rapidfuzz import fuzz
from unidecode import unidecode

from config import (
    ALERT_TABLE, BASE_DIR, FIELDS, INPUT_MODES, NONE, PRODUCT_NUMERIC,
    PRODUCT_FIELDS, OUT_SOLVING, TYPE_TABLE, VEHICLE_NUMERIC,
    VIETNAM_BOUNDS, Config, UserError,
)
from optimization import haversine

INT32_MIN, INT32_MAX = -2_147_483_648, 2_147_483_647
FLOAT32_SAFE_MAX = 1e7
KEEP_FLOAT64 = {"lat", "lng", "lon", "latitude", "longitude"}


def is_blank(v):
    if v is None: return True
    try:
        if pd.isna(v): return True
    except Exception: pass
    return str(v).strip() == ""


def optimize_dtypes(df, categorize=False, cat_ratio=0.5, keep_float64=KEEP_FLOAT64):
    if df is None or len(df) == 0 or len(df.columns) == 0 or df.columns.duplicated().any():
        return df
    out = df.copy()
    for col in out.columns:
        s = out[col]
        dtype = s.dtype
        try:
            is_text = (dtype == object) or (pd.api.types.is_string_dtype(dtype) and not isinstance(dtype, pd.CategoricalDtype))
            if categorize and is_text and len(s) > 0:
                if s.nunique(dropna=True) / len(s) < cat_ratio:
                    out[col] = s.astype("category")
                continue
            if not isinstance(dtype, np.dtype): continue
            if dtype.kind == "i" and dtype.itemsize > 4:
                if s.min() >= INT32_MIN and s.max() <= INT32_MAX: out[col] = s.astype("int32")
            elif dtype.kind == "f" and dtype.itemsize > 4:
                if str(col).strip().lower() in keep_float64: continue
                mx = s.abs().max()
                if pd.isna(mx) or mx < FLOAT32_SAFE_MAX: out[col] = s.astype("float32")
        except Exception: continue
    return out


def mem_kb(df) -> float:
    return float(df.memory_usage(deep=True).sum()) / 1024.0


def norm_basic(v):
    return re.sub(r"[^a-z0-9 ]+", " ", unidecode(str(v)).lower()).strip()


def parse_num(val):
    if is_blank(val): return 0.0
    try:
        cleaned = re.sub(r"[^\d.-]", "", str(val))
        return float(cleaned) if cleaned else 0.0
    except Exception: return 0.0


def parse_qty(x, dot_is_decimal=False) -> float:
    if x is None: return 0.0
    if isinstance(x, (int, float, np.integer, np.floating)):
        return 0.0 if pd.isna(x) else float(x)
    mt = re.search(r"-?\d[\d.,]*", str(x))
    if not mt: return 0.0
    s = mt.group(0).rstrip(".,")
    if "." in s and "," in s:
        dec = "." if s.rfind(".") > s.rfind(",") else ","
        s = s.replace("," if dec == "." else ".", "").replace(dec, ".")
    else:
        sep = "." if "." in s else ("," if "," in s else "")
        if sep and s.count(sep) > 1: s = s.replace(sep, "")
        elif sep:
            thousands = (not dot_is_decimal) and re.fullmatch(r"-?\d{1,3}" + re.escape(sep) + r"\d{3}", s)
            s = s.replace(sep, "") if thousands else s.replace(sep, ".")
    try: return float(s)
    except ValueError: return 0.0


def parse_date_iso(dstr: str) -> str:
    if is_blank(dstr): return ""
    dstr = str(dstr).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d-%m-%Y", "%m-%d-%Y", "%Y.%m.%d", "%d.%m.%Y"):
        try: return dt.datetime.strptime(dstr, fmt).strftime("%Y-%m-%d")
        except ValueError: continue
    try:
        parsed = pd.to_datetime(dstr, errors="coerce")
        if pd.notna(parsed): return parsed.strftime("%Y-%m-%d")
    except Exception: pass
    return ""


def _read_csv_bytes(data: bytes) -> pd.DataFrame:
    for enc in ("utf-8-sig", "cp1258", "latin-1"):
        try:
            df = pd.read_csv(io.BytesIO(data), encoding=enc)
            if df.shape[1] == 1:
                header = str(df.columns[0])
                for sep in (";", "\t", "|"):
                    if sep in header: return pd.read_csv(io.BytesIO(data), encoding=enc, sep=sep)
            return df
        except UnicodeDecodeError: pass
    raise UserError("Không đọc được mã hóa file CSV.")


@st.cache_data(show_spinner=False, max_entries=8, ttl=3600)
def _parse_upload(name: str, data: bytes) -> pd.DataFrame:
    if name.endswith((".xlsx", ".xls", ".xlsm")):
        df = pd.read_excel(io.BytesIO(data))
    elif name.endswith(".json"):
        try: df = pd.read_json(io.BytesIO(data))
        except ValueError:
            obj = json.loads(data.decode("utf-8-sig"))
            if isinstance(obj, dict):
                lists = [v for v in obj.values() if isinstance(v, list)]
                obj = lists[0] if len(lists) == 1 else [obj]
            df = pd.json_normalize(obj)
    else:
        df = _read_csv_bytes(data)
    return optimize_dtypes(df.dropna(how="all").dropna(axis=1, how="all").reset_index(drop=True))


def read_any(f) -> pd.DataFrame:
    name = (getattr(f, "name", "") or "").lower()
    data = f.getvalue() if hasattr(f, "getvalue") else f.read()
    return _parse_upload(name, data)


@st.cache_data(show_spinner=False, max_entries=16)
def _read_excel_cached(path: str, mtime: float, index_col=None) -> pd.DataFrame:
    return optimize_dtypes(pd.read_excel(path, index_col=index_col))


def read_dim_file(path: str, index_col=None) -> pd.DataFrame:
    if not os.path.exists(path):
        raise UserError(f"Chưa có file `{os.path.relpath(path, BASE_DIR)}`.")
    return _read_excel_cached(path, os.path.getmtime(path), index_col)


def get_input(mode, uploaded, edited, label):
    if mode == INPUT_MODES[1]:
        if uploaded is None: raise UserError(f"Hãy upload file {label} trước.")
        df = read_any(uploaded)
    else:
        df = pd.DataFrame(edited) if edited is not None else pd.DataFrame()
    df = df.replace("", np.nan).dropna(how="all").reset_index(drop=True)
    if df.empty: raise UserError(f"Chưa có dữ liệu {label} để quét.")
    return optimize_dtypes(df)


def basic_semantic_mapping(df, fields, profile_fn, threshold):
    result, used = {}, set()
    for fld, aliases in fields.items():
        aliases = list(aliases) + [fld]
        best_col, best_score = None, 0.0
        for col in df.columns:
            if col in used: continue
            col_norm = norm_basic(col)
            fuzzy_score = max(fuzz.token_set_ratio(col_norm, norm_basic(a)) for a in aliases) / 100.0
            keyword_score = float(any(norm_basic(a) in col_norm for a in aliases if len(norm_basic(a)) >= 3))
            score = 0.75 * (0.7 * fuzzy_score + 0.3 * keyword_score) + 0.25 * profile_fn(df[col], fld)
            if score > best_score: best_col, best_score = col, score
        if best_col is not None and best_score >= threshold:
            result[fld] = (best_col, best_score)
            used.add(best_col)
        else: result[fld] = (None, 0.0)
    return result


def orders_semantic_mapping(df):
    result = {}
    for fld in FIELDS:
        best_col, best_score = None, 0.0
        for col in df.columns:
            sc = fuzz.token_set_ratio(norm_basic(col), norm_basic(fld)) / 100.0
            if sc > best_score: best_col, best_score = col, sc
        result[fld] = (best_col, best_score, "tên cột") if best_score > 0.3 else (None, 0.0, "")
    return result


def build_colmap(raw_df, chosen):
    lookup = {str(c): c for c in raw_df.columns}
    return {f: lookup[c] for f, c in chosen.items() if c and c != NONE and c in lookup}


def pick(row, colmap, fld, default=""):
    return row.get(colmap[fld]) if fld in colmap else default


def df_to_records(df: pd.DataFrame):
    tmp = df.copy()
    for c in tmp.columns[tmp.dtypes == "float32"]:
        tmp[c] = pd.Series([float(str(x)) for x in tmp[c].to_numpy()], index=tmp.index, dtype="float64")
    for c in tmp.columns[tmp.dtypes == "int32"]:
        tmp[c] = tmp[c].astype("int64")
    clean = tmp.astype(object).where(tmp.notna(), None)
    return clean.to_dict("records")


def save_outputs(out_dir, base, sheet, df, extra_sheets=None):
    os.makedirs(out_dir, exist_ok=True)
    xlsx = os.path.join(out_dir, f"{base}.xlsx")
    js = os.path.join(out_dir, f"{base}.json")
    with pd.ExcelWriter(xlsx, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name=sheet, index=False)
        for name, sdf in (extra_sheets or {}).items():
            if sdf is not None and len(sdf): sdf.to_excel(writer, sheet_name=name, index=False)
    with open(js, "w", encoding="utf-8") as fh:
        json.dump(df_to_records(df), fh, ensure_ascii=False, indent=2, default=str)
    return [xlsx, js]


def coordinate_in_vietnam(lat, lng):
    try: lat, lng = float(lat), float(lng)
    except Exception: return False
    return VIETNAM_BOUNDS[0] <= lat <= VIETNAM_BOUNDS[1] and VIETNAM_BOUNDS[2] <= lng <= VIETNAM_BOUNDS[3]


ADDRESS_ABBR = [(r"\bTP\.?\b", "Thành phố"), (r"\bQ\.?\b", "Quận"), (r"\bH\.?\b", "Huyện"), (r"\bTX\.?\b", "Thị xã"),
                (r"\bTT\.?\b", "Thị trấn"), (r"\bP\.?\b", "Phường"), (r"\bX\.?\b", "Xã"), (r"\bĐg\.?\b", "Đường")]


def clean_address(address):
    if is_blank(address): return ""
    text = str(address).replace("\r", " ").replace("\n", " ").replace("\t", " ")
    text = re.sub(r"[\u00A0\u2000-\u200B\u202F\u3000]", " ", text)
    text = re.sub(r"\s*[|;→–—]\s*", ", ", text)
    text = re.sub(r"\s+-\s+", ", ", text)
    text = re.sub(r"[^0-9A-Za-zÀ-ỹĐđ\s,./'-]", " ", text)
    for p, r in ADDRESS_ABBR: text = re.sub(p, r, text, flags=re.IGNORECASE)
    if re.search(r"Tôn Đức Thắng", text, re.I) and re.search(r"Bách Khoa", text, re.I):
        text = re.sub(r"Phường Bách Khoa,?\s*", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" ,.")
    if text and not re.search(r"\bViệt Nam\b|\bVietnam\b", text, re.I): text += ", Việt Nam"
    return text


def address_quality(address):
    if not address: return 0.0, "❌ Địa chỉ trống"
    score = 0.5 if len(address) >= 10 else 0.25
    if "," in address: score += 0.3
    if re.search(r"\b(Phường|Xã|Quận|Huyện|Thành phố|Tỉnh)\b", address, re.I): score += 0.2
    return min(score, 1.0), "✅ Hợp lệ"


def extract_province(address_str: str) -> str:
    if is_blank(address_str): return "Chưa xác định"
    parts = [p.strip() for p in str(address_str).split(",")]
    if len(parts) >= 2:
        prov = parts[-1]
        if "Việt Nam" in prov or "Vietnam" in prov:
            prov = parts[-2] if len(parts) >= 3 else parts[-1]
        return prov.strip()
    return "Hà Nội" if "Hà Nội" in address_str or "ha noi" in norm_basic(address_str) else "Tỉnh khác"


@st.cache_resource(show_spinner=False)
def get_geocoder():
    try: return ArcGIS(user_agent="smart-logistics-warehouse/1.0", timeout=10)
    except Exception: return None


@st.cache_resource(show_spinner=False)
def _geo_cache(): return {}


def geocode_address(address, ref_wh_lat=21.0285, ref_wh_lng=105.8542, max_valid_km=150.0, retries=3):
    if not address: return {"ok": False, "status": "❌ Địa chỉ trống"}
    cache = _geo_cache()
    if address in cache: return cache[address]
    geocoder = get_geocoder()
    if geocoder is None: return {"ok": False, "status": "❌ Không khởi tạo được ArcGIS"}

    for attempt in range(1, retries + 1):
        try:
            loc = geocoder.geocode(address, timeout=10)
            if loc is None: return {"ok": False, "status": "⚠️ Không tìm thấy địa chỉ"}
            lat, lng = float(loc.latitude), float(loc.longitude)
            if not coordinate_in_vietnam(lat, lng):
                return {"ok": False, "status": "⚠️ Tọa độ ngoài VN"}
            dist_to_wh = haversine(ref_wh_lat, ref_wh_lng, lat, lng)
            if dist_to_wh > max_valid_km:
                return {"ok": False, "status": f"⚠️ Geocode sai vị trí cách kho {dist_to_wh:.0f}km"}
            res = {"ok": True, "lat": lat, "lng": lng, "display_name": getattr(loc, "address", "") or "", "score": 1.0}
            cache[address] = res
            return res
        except Exception:
            if attempt == retries: break
            time.sleep(1)
    return {"ok": False, "status": "❌ Lỗi Geocoding"}


def fleet_profile_score(series, field):
    values = series.dropna().astype(str).str.strip()
    values = values[values != ""]
    if values.empty: return 0.0
    if field in VEHICLE_NUMERIC:
        return float(values.str.replace(r"[^\d.]", "", regex=True).str.len().gt(0).mean())
    return float(values.nunique() / len(values))


def process_vehicle(rec):
    out = {f: ("" if is_blank(rec.get(f)) else str(rec.get(f)).strip()) for f in ["vehicle_id", "license_plate", "id_warehouse"]}
    for f in VEHICLE_NUMERIC: out[f] = parse_num(rec.get(f))
    out["trạng_thái"] = "✅ Hợp lệ"
    return out


def fleet_validate_output(df):
    out = df.copy()
    dup_id = out["vehicle_id"].astype(str).duplicated(keep=False)
    dup_plate = out["license_plate"].astype(str).duplicated(keep=False)
    msgs = []
    for i, row in out.iterrows():
        errs = []
        if is_blank(row.get("vehicle_id")): errs.append("Thiếu vehicle_id")
        if is_blank(row.get("license_plate")): errs.append("Thiếu license_plate")
        if is_blank(row.get("id_warehouse")): errs.append("Thiếu id_warehouse")
        if dup_id.iloc[i] and not is_blank(row.get("vehicle_id")): errs.append("Trùng vehicle_id")
        if dup_plate.iloc[i] and not is_blank(row.get("license_plate")): errs.append("Trùng license_plate")
        msgs.append("❌ " + "; ".join(errs) if errs else "✅ Hợp lệ")
    out["kiểm_tra"] = msgs
    return out


def process_warehouse(warehouse_id, address, do_geocode=True):
    raw_address = "" if is_blank(address) else str(address).strip()
    cleaned = clean_address(raw_address)
    quality, _ = address_quality(cleaned)
    result = {"id_warehouse": "" if is_blank(warehouse_id) else str(warehouse_id).strip(), "address": cleaned,
              "lat": None, "lng": None, "chất_lượng_địa_chỉ": quality, "trạng_thái_geocode": "—"}
    if is_blank(warehouse_id) or not cleaned or not do_geocode: return result
    geo = geocode_address(cleaned, max_valid_km=10000.0)
    if not geo["ok"]:
        result["trạng_thái_geocode"] = geo["status"]; return result
    result.update({"lat": geo["lat"], "lng": geo["lng"], "trạng_thái_geocode": "✅ Thành công"})
    return result


def warehouse_validate_output(df):
    out = df.copy()
    msgs = []
    for _, row in out.iterrows():
        errs = []
        if is_blank(row.get("id_warehouse")): errs.append("Thiếu id")
        if is_blank(row.get("address")): errs.append("Thiếu địa chỉ")
        if pd.isna(row.get("lat")) or pd.isna(row.get("lng")): errs.append("Thiếu tọa độ")
        msgs.append("❌ " + "; ".join(errs) if errs else "✅ Hợp lệ")
    out["kiểm_tra"] = msgs
    return out


def process_product(rec):
    out = {f: ("" if is_blank(rec.get(f)) else str(rec.get(f)).strip()) for f in ["product_id", "product_name"]}
    for f in PRODUCT_NUMERIC: out[f] = parse_num(rec.get(f))
    out["volume_m3"] = round((out["length_cm"] * out["width_cm"] * out["height_cm"]) / 1_000_000.0, 6)
    out["trạng_thái"] = "✅ Hợp lệ"
    return out


def product_validate_output(df):
    out = df.copy()
    msgs = []
    for _, row in out.iterrows():
        errs = []
        if is_blank(row.get("product_id")): errs.append("Thiếu id")
        if is_blank(row.get("product_name")): errs.append("Thiếu tên")
        msgs.append("❌ " + "; ".join(errs) if errs else "✅ Hợp lệ")
    out["kiểm_tra"] = msgs
    return out


def build_lookup(table):
    exact = {norm_basic(k): l for l, keys in table.items() for k in keys}
    return {"exact": exact, "keys": list(exact.keys())}


TYPE_LK, ALERT_LK = build_lookup(TYPE_TABLE), build_lookup(ALERT_TABLE)


def match_label(value, lk):
    n = norm_basic(str(value))
    if n in lk["exact"]: return lk["exact"][n]
    return None


def process_order_with_geocode(raw, do_geocode=True):
    r_name = str(raw.get("customer_name", ""))
    cust_name = r_name or "Khách lẻ"
    t_type = match_label(raw.get("order_type", ""), TYPE_LK) or ("B2B" if "cong ty" in norm_basic(r_name) else "B2C")
    t_alert = match_label(raw.get("alert_status", ""), ALERT_LK) or "Normal"

    q = parse_qty(raw.get("quantity"))
    w = parse_qty(raw.get("total_weight_kg"))
    v = parse_qty(raw.get("total_volume_m3"), dot_is_decimal=True)

    addr = str(raw.get("address", "")).strip()
    cleaned_addr = clean_address(addr)
    lat, lng, geo_status = None, None, "— Chưa quét"

    if do_geocode and cleaned_addr:
        geo = geocode_address(cleaned_addr)
        if geo["ok"]:
            lat, lng, geo_status = geo["lat"], geo["lng"], "✅ Thành công"
        else:
            geo_status = geo["status"]

    items_str = str(raw.get("items", "")).strip()
    if not items_str or items_str == "nan":
        items_str = "SP_01"

    province = extract_province(cleaned_addr)

    return {
        "order_id": str(raw.get("order_id", "")),
        "customer_id": str(raw.get("customer_id", "")),
        "customer_name": cust_name,
        "quantity": int(q or 1),
        "items": items_str,
        "total_weight_kg": round(w or 0.0, 4),
        "total_volume_m3": round(v or 0.0, 6),
        "address": cleaned_addr,
        "province": province,
        "lat": lat,
        "lng": lng,
        "trạng_thái_geocode": geo_status,
        "order_status": str(raw.get("order_status", "")) or "Mới tạo",
        "order_type": t_type,
        "alert_status": t_alert,
        "order_date": parse_date_iso(raw.get("order_date")),
    }


def orders_validate_output(df):
    out = df.copy()
    msgs = []
    for _, row in out.iterrows():
        errs = []
        if is_blank(row.get("order_id")): errs.append("Thiếu id")
        if is_blank(row.get("address")): errs.append("Thiếu địa chỉ/location")
        if pd.isna(row.get("lat")) or pd.isna(row.get("lng")): errs.append("Chưa quét được tọa độ")
        msgs.append("❌ " + "; ".join(errs) if errs else "✅ Hợp lệ")
    out["kiểm_tra"] = msgs
    return out


def is_hanoi_address(addr_str: str) -> bool:
    if not addr_str: return False
    norm = norm_basic(addr_str)
    return "ha noi" in norm or "hanoi" in norm


def run_orders_solving(df_orders: pd.DataFrame, df_products: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if df_orders.empty: return pd.DataFrame(), pd.DataFrame()

    prod_map = {}
    if df_products is not None and not df_products.empty and "product_id" in df_products.columns:
        for _, pr in df_products.iterrows():
            prod_map[str(pr["product_id"]).strip()] = {
                "l": float(pr.get("length_cm", 0.0)),
                "w": float(pr.get("width_cm", 0.0)),
                "h": float(pr.get("height_cm", 0.0))
            }

    solved_rows = []
    for _, r in df_orders.iterrows():
        row_dict = dict(r)
        item_id = str(r.get("items", "")).strip()
        qty = int(r.get("quantity", 1))
        real_weight = float(r.get("total_weight_kg", 0.0))

        dim = prod_map.get(item_id, {"l": 50.0, "w": 40.0, "h": 30.0})
        l, w, h = dim["l"], dim["w"], dim["h"]

        volumetric_weight = ((l * w * h) * qty) / 4000.0

        row_dict["length_cm"] = l
        row_dict["width_cm"] = w
        row_dict["height_cm"] = h
        row_dict["volumetric_weight_kg"] = round(volumetric_weight, 2)

        if volumetric_weight > real_weight:
            row_dict["BBS_type"] = "Loại A (Cồng kềnh - BBS)"
            row_dict["BBS_code"] = "A"
        else:
            row_dict["BBS_type"] = "Loại B (Hàng nặng)"
            row_dict["BBS_code"] = "B"

        solved_rows.append(row_dict)

    df_solved = pd.DataFrame(solved_rows)

    prov_summary = (df_solved.groupby("province")
                    .agg(total_orders=("order_id", "count"),
                         total_weight=("total_weight_kg", "sum"),
                         total_volume=("total_volume_m3", "sum"),
                         bbs_a_count=("BBS_code", lambda x: (x == "A").sum()),
                         bbs_b_count=("BBS_code", lambda x: (x == "B").sum()))
                    .reset_index()
                    .sort_values("total_orders", ascending=False))

    prov_summary["ratio_%"] = round(prov_summary["total_orders"] / len(df_solved) * 100, 1)
    return df_solved, prov_summary


def read_matrix(path: str) -> pd.DataFrame:
    df = read_dim_file(path, index_col=0).copy()
    df.index, df.columns = df.index.astype(str), df.columns.astype(str)
    return df


def _num_col(df, col, default=0.0):
    if col not in df.columns: return pd.Series(default, index=df.index, dtype=float)
    return pd.to_numeric(df[col], errors="coerce").fillna(default).astype(float)


def load_vehicles(cfg: Config) -> pd.DataFrame:
    df = read_dim_file(cfg.vehicle_file).copy()
    for c in ("vehicle_id", "license_plate", "id_warehouse"):
        df[c] = df[c].astype(str).str.strip() if c in df.columns else ""
    df = df[~df["vehicle_id"].isin(["", "nan", "None"])].copy()
    for c in VEHICLE_NUMERIC: df[c] = _num_col(df, c)
    df.loc[df["average_speed_kmh"] <= 0, "average_speed_kmh"] = 40.0
    df.loc[df["Max_Distance"] <= 0, "Max_Distance"] = 100.0
    df["vehicle_type"] = [f"{w:.0f}kg/{v:g}m3" for w, v in zip(df["max_weight_kg"], df["max_volume_m3"])]
    return df.reset_index(drop=True)


def load_warehouse_coords(cfg: Config) -> dict:
    if not os.path.exists(cfg.warehouse_file): return {}
    out = {}
    for _, r in read_dim_file(cfg.warehouse_file).iterrows():
        wid = "" if is_blank(r.get("id_warehouse")) else str(r["id_warehouse"]).strip()
        if wid and pd.notna(r.get("lat")) and pd.notna(r.get("lng")): out[wid] = (float(r["lat"]), float(r["lng"]))
    return out


def load_customers(cfg: Config) -> dict:
    out = {}
    if not os.path.exists(cfg.cust_file): return out
    for _, r in read_dim_file(cfg.cust_file).iterrows():
        cid = str(r.get("customer_id", "")).strip()
        if cid and cid != "nan" and pd.notna(r.get("lat")) and pd.notna(r.get("lng")):
            out[cid] = {"lat": float(r["lat"]), "lng": float(r["lng"]), "name": "" if is_blank(r.get("customer_name")) else str(r["customer_name"])}
    return out


def load_orders_flexible(cfg: Config, source_df: pd.DataFrame = None) -> tuple[list, list]:
    notes = []
    if source_df is not None and not source_df.empty:
        df = source_df.copy()
        notes.append("⚡ Sử dụng dữ liệu đơn hàng phân loại trực tiếp từ Session State / Orders Solving.")
    else:
        df = read_dim_file(cfg.order_file)
        notes.append("📂 Đọc dữ liệu từ file đĩa `DIM_ORDERS.xlsx`.")

    for c in ("order_id", "customer_id", "order_date"):
        if c not in df.columns: raise UserError(f"Dữ liệu đơn hàng thiếu cột `{c}`.")

    orders, skipped = [], 0
    for _, r in df.iterrows():
        oid, cid, dstr = ("" if is_blank(r.get(k)) else str(r[k]).strip() for k in ("order_id", "customer_id", "order_date"))
        d_iso = parse_date_iso(dstr)
        if not (oid and cid and d_iso): skipped += 1; continue
        otype = str(r.get("order_type", "")).strip().upper()

        lat = float(r["lat"]) if pd.notna(r.get("lat")) else None
        lng = float(r["lng"]) if pd.notna(r.get("lng")) else None
        qty = int(parse_qty(r.get("quantity")) or 1)
        items_str = "" if is_blank(r.get("items")) else str(r["items"]).strip()
        province_str = "" if is_blank(r.get("province")) else str(r["province"]).strip()
        bbs_code = "" if is_blank(r.get("BBS_code")) else str(r["BBS_code"]).strip()

        orders.append({
            "order_id": oid, "customer_id": cid, "order_type": otype if otype in ("B2B", "B2C") else "B2C",
            "quantity": qty,
            "items": items_str or "SP_01",
            "total_weight_kg": parse_qty(r.get("total_weight_kg")), "total_volume_m3": parse_qty(r.get("total_volume_m3"), dot_is_decimal=True),
            "address": "" if is_blank(r.get("address")) else str(r["address"]),
            "province": province_str,
            "BBS_code": bbs_code,
            "lat": lat, "lng": lng,
            "alert_status": "Normal" if is_blank(r.get("alert_status")) else str(r["alert_status"]),
            "order_status": "" if is_blank(r.get("order_status")) else str(r["order_status"]),
            "order_date": d_iso,
        })
    if skipped: notes.append(f"Bỏ qua {skipped} đơn thiếu order_id / customer_id hoặc order_date sai định dạng.")
    return orders, notes


def load_data_flexible(cfg: Config, source_df: pd.DataFrame = None) -> dict:
    veh = load_vehicles(cfg)
    wh_coords = load_warehouse_coords(cfg)
    orders, notes = load_orders_flexible(cfg, source_df)

    if not wh_coords:
        wh_coords = {"WH_DEFAULT": (21.0285, 105.8542)}
        notes.append("Chưa có tọa độ kho (Tab 2) → dùng kho mặc định Hà Nội.")
    warehouses = {w: {"lat": la, "lng": lo, "name": w} for w, (la, lo) in wh_coords.items()}
    orphan = sorted(set(veh["id_warehouse"]) - set(warehouses))
    if orphan: notes.append(f"Xe thuộc kho không có tọa độ: {', '.join(orphan)}.")

    return {"vehicles": veh,
            "dist": read_matrix(cfg.matrix_file) if os.path.exists(cfg.matrix_file) else pd.DataFrame(),
            "cust": load_customers(cfg), "warehouses": warehouses, "orders": orders, "notes": notes}


def load_orders(cfg: Config, notes: list) -> list:
    orders, n_notes = load_orders_flexible(cfg)
    notes.extend(n_notes)
    return orders


def load_data(cfg: Config) -> dict:
    return load_data_flexible(cfg)


def require_files(cfg: Config, which):
    labels = {
        "orders": (cfg.order_file, "Tab 4 (Đơn hàng)"),
        "fleet": (cfg.vehicle_file, "Tab 1 (Hạm đội xe)"),
    }
    missing = [f"`{os.path.relpath(labels[k][0], BASE_DIR)}` (chạy {labels[k][1]})" for k in which if not os.path.exists(labels[k][0])]
    if missing: raise UserError("Thiếu file đầu vào: " + "; ".join(missing))

# -*- coding: utf-8 -*-
"""
PHẦN 1 — CONFIGURATION
======================
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

# 1.1 TRANG & HẰNG SỐ GIAO DIỆN
PAGE_CONFIG = {"page_title": "Smart Logistics Dashboard", "page_icon": "🚚", "layout": "wide"}

NONE = "-- Không sử dụng --"
INPUT_MODES = ["Nhập trực tiếp (Data Editor)", "Upload file Excel/CSV/JSON"]
UPLOAD_TYPES = ["xlsx", "xls", "xlsm", "csv", "json"]
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
VIETNAM_BOUNDS = (8.0, 24.5, 102.0, 110.0)

# 1.2 ĐƯỜNG DẪN LƯU DỮ LIỆU CHUẨN HÓA
BASE_DIR = os.getcwd()
OUT_FLEET = os.path.join(BASE_DIR, "output_fleet")
OUT_WAREHOUSE = os.path.join(BASE_DIR, "output_warehouse")
OUT_PRODUCT = os.path.join(BASE_DIR, "output_product")
OUT_ORDERS = os.path.join(BASE_DIR, "output_orders")
OUT_SOLVING = os.path.join(BASE_DIR, "output_solving")
OUT_CUSTOMER = os.path.join(BASE_DIR, "output_customer")
OUT_MATRIX = os.path.join(BASE_DIR, "output_matrix")

# 1.3 HẰNG SỐ NGHIỆP VỤ
LICENSE_RANKS = {
    "A1": 1, "A2": 2, "A3": 3, "A4": 4,
    "B1": 5, "B2": 6,
    "C": 7,
    "D": 8, "E": 9,
    "FB2": 10, "FC": 11, "FD": 12, "FE": 13
}
LICENSE_LIST = list(LICENSE_RANKS.keys())


class UserError(Exception):
    """Lỗi do người dùng."""


# 1.5 SCHEMA DỮ LIỆU
VEHICLE_FIELDS = {
    "vehicle_id": ["mã xe", "vehicle id", "vehicle code", "vehicle", "xe", "id xe", "truck id"],
    "license_plate": ["biển số", "bien so", "bsx", "license plate", "plate", "số xe"],
    "id_warehouse": ["kho", "warehouse", "wh", "hub", "chi nhánh", "location", "ma kho", "id kho"],
    "max_weight_kg": ["trọng tải", "trong tai", "weight", "payload", "khối lượng", "kg", "tấn", "max weight"],
    "max_volume_m3": ["thể tích", "the tich", "volume", "m3", "cbm", "max volume"],
    "average_speed_kmh": ["vận tốc", "van toc", "speed", "vận tốc trung bình", "avg speed", "kmh"],
    "Max_Distance": ["khoảng cách tối đa", "max distance", "quãng đường tối đa", "km tối đa", "max km"],
    "fixed_cost": ["chi phí cố định", "fixed cost", "cost fix"],
    "variable_cost": ["chi phí biến đổi", "variable cost", "cost km"],
}
VEHICLE_NUMERIC = ["max_weight_kg", "max_volume_m3", "average_speed_kmh", "Max_Distance", "fixed_cost", "variable_cost"]

WAREHOUSE_FIELDS = {
    "id_warehouse": ["mã kho", "warehouse id", "warehouse code", "warehouse", "kho", "id kho"],
    "address": ["địa chỉ", "địa điểm", "address", "location", "vị trí"],
}

PRODUCT_FIELDS = {
    "product_id": ["mã sản phẩm", "product id", "sku", "item code", "mã sp", "code", "id"],
    "product_name": ["tên sản phẩm", "product name", "item name", "tên sp", "name"],
    "length_cm": ["chiều dài", "dài", "length", "length_cm", "dài (cm)"],
    "width_cm": ["chiều rộng", "rộng", "width", "width_cm", "rộng (cm)"],
    "height_cm": ["chiều cao", "cao", "height", "height_cm", "cao (cm)"],
    "weight": ["trọng lượng", "weight", "kg"],
    "cost_price": ["giá sản xuất", "cost price", "cost"],
    "selling_price": ["giá bán", "selling price", "price"],
}
PRODUCT_NUMERIC = ["length_cm", "width_cm", "height_cm", "weight", "cost_price", "selling_price"]

_ORDER_RAW = {
    "order_id": dict(aliases=["mã đơn", "order id", "order code"]),
    "customer_id": dict(aliases=["mã khách", "customer id"]),
    "customer_name": dict(aliases=["tên khách", "customer name", "name"]),
    "quantity": dict(aliases=["số lượng", "qty", "quantity", "units"]),
    "items": dict(aliases=["mặt hàng", "items", "product", "sản phẩm"]),
    "total_weight_kg": dict(aliases=["trọng lượng", "weight", "kg"]),
    "total_volume_m3": dict(aliases=["thể tích", "volume", "m3"]),
    "shift": dict(aliases=["shift", "ca", "kíp", "buổi", "ca giao", "ca làm việc", "buổi giao"]),
    "address": dict(aliases=["địa chỉ", "address", "destination", "location", "vị trí"]),
    "province": dict(aliases=["tỉnh", "thành phố", "province", "tỉnh/thành"]),
    "order_status": dict(aliases=["trạng thái", "status"]),
    "order_type": dict(aliases=["loại đơn", "order type", "channel"]),
    "alert_status": dict(aliases=["cảnh báo", "alert", "priority"]),
    "order_date": dict(aliases=["ngày đặt", "order date", "date"]),
}
ORDER_FIELDS = {f: dict(label=f, aliases=[f] + v["aliases"]) for f, v in _ORDER_RAW.items()}
FIELDS = list(ORDER_FIELDS)

TYPE_TABLE = {"B2C": ["b2c", "cá nhân", "lẻ"], "B2B": ["b2b", "doanh nghiệp", "sỉ"]}
ALERT_TABLE = {"Alert": ["alert", "khẩn", "gấp"], "Normal": ["normal", "bình thường"]}

SHIFT_MAPPING_KEYWORDS = {
    "Ca Sáng": ["sáng", "ca sáng", "morning", "ca 1", "am", "shift 1"],
    "Ca Chiều": ["chiều", "ca chiều", "afternoon", "ca 2", "pm", "shift 2"],
    "Ca Đêm": ["đêm", "ca đêm", "night", "ca 3", "shift 3"]
}

OC_DEFAULTS = {
    "saving_1_price": 800_000.0, "saving_2_price": 300_000.0,
    "tier2_max_w": 20.0, "tier2_max_v": 1.0,
    "tier1_max_w": 100.0, "tier1_max_v": 5.0,
    "full_vehicle_name": "Xe 3PL Full", "full_vehicle_max_weight_kg": 10_000.0, "full_vehicle_max_volume_m3": 40.0, "full_price": 0.0
}


@dataclass
class Config:
    start_time: str = "08:30"
    max_route_hours: float = 8.0
    detour_factor: float = 1.2
    constraint_mode: str = "Cube Out (Thể tích m³)"
    service_min: dict = field(default_factory=lambda: {"B2B": 105, "B2C": 60})
    backup_driver_cost: float = 400_000.0
    vehicle_daily_count: int = 2
    turnaround_min: float = 30.0
    outsourced_speed_kmh: float = 40.0
    saving_1_price: float = OC_DEFAULTS["saving_1_price"]
    saving_2_price: float = OC_DEFAULTS["saving_2_price"]
    tier2_max_w: float = OC_DEFAULTS["tier2_max_w"]
    tier2_max_v: float = OC_DEFAULTS["tier2_max_v"]
    tier1_max_w: float = OC_DEFAULTS["tier1_max_w"]
    tier1_max_v: float = OC_DEFAULTS["tier1_max_v"]
    full_price: float = 0.0
    full_vehicle_name: str = "Xe 3PL Full"
    full_vehicle_max_weight_kg: float = 10000.0
    full_vehicle_max_volume_m3: float = 40.0
    vehicle_file: str = os.path.join(OUT_FLEET, "DIM_VEHICLE.xlsx")
    warehouse_file: str = os.path.join(OUT_WAREHOUSE, "WAREHOUSE_WITH_COORDINATES.xlsx")
    product_file: str = os.path.join(OUT_PRODUCT, "DIM_PRODUCT.xlsx")
    order_file: str = os.path.join(OUT_ORDERS, "DIM_ORDERS.xlsx")
    cust_file: str = os.path.join(OUT_CUSTOMER, "DATASET_CUSTOMER.xlsx")
    matrix_file: str = os.path.join(OUT_MATRIX, "DISTANCE_MATRIX_KM.xlsx")

    @property
    def outsourcing(self) -> dict:
        return {
            "saving_1_price": self.saving_1_price,
            "saving_2_price": self.saving_2_price,
            "tier2_max_w": self.tier2_max_w,
            "tier2_max_v": self.tier2_max_v,
            "tier1_max_w": self.tier1_max_w,
            "tier1_max_v": self.tier1_max_v,
            "full_price": self.full_price,
            "full_vehicle_name": self.full_vehicle_name,
            "full_vehicle_max_weight_kg": self.full_vehicle_max_weight_kg,
            "full_vehicle_max_volume_m3": self.full_vehicle_max_volume_m3,
        }


CFG = Config()

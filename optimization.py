# -*- coding: utf-8 -*-
"""
PHẦN 3 — CORE OPTIMIZATION
==========================
Lõi thuật toán định tuyến: Clarke-Wright (savings) + 2-opt, kiểm tra ràng buộc
tải trọng / quãng đường / thời gian, và phân loại thuê ngoài 3PL.

Module này KHÔNG phụ thuộc streamlit, chỉ cần pandas + config, nên có thể
import và unit-test độc lập mà không cần chạy giao diện.
"""
from __future__ import annotations

import datetime as dt
import math

import pandas as pd

from .config import CFG, OC_DEFAULTS, Config

# ============================================================================
# 3.1  TIỆN ÍCH HÌNH HỌC & THỜI GIAN
# ============================================================================
def haversine(lat1, lng1, lat2, lng2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def calculate_effective_max_hours(start_time_str="08:30", max_hours_input=8.0):
    try:
        sh, sm = map(int, start_time_str.split(":"))
        start_in_hours = sh + sm / 60.0
    except Exception:
        start_in_hours = 8.5
    cutoff_hours = 17.5
    return min(float(max_hours_input), max(0.0, cutoff_hours - start_in_hours))


def service_rules_from_cfg(cfg: Config) -> dict:
    base = {"B2C": {"loading": 25, "unloading": 35}, "B2B": {"loading": 45, "unloading": 60}}
    for k in ("B2C", "B2B"):
        total = base[k]["loading"] + base[k]["unloading"]
        want = float(cfg.service_min.get(k, total))
        if abs(want - total) > 1e-9:
            ratio = base[k]["loading"] / total
            base[k] = {"loading": want * ratio, "unloading": want * (1 - ratio)}
    return base


# ============================================================================
# 3.2  PHÂN LOẠI & CHI PHÍ THUÊ NGOÀI 3PL
# ============================================================================
def _full_cls(w, v, oc, why=None):
    fw = max(float(oc.get("full_vehicle_max_weight_kg", 10000.0)), 1e-9)
    fv = max(float(oc.get("full_vehicle_max_volume_m3", 40.0)), 1e-9)
    trips = max(1, math.ceil(w / fw - 1e-9), math.ceil(v / fv - 1e-9))
    if why is None:
        why = f"tải {w:,.0f}kg/{v:.1f}m³ vượt ngưỡng Tiết kiệm 1 → Cần xe 3PL Full ({trips} chuyến)"
    else:
        why = f"Cần xe 3PL Full ({why})"
    return {"type": f"3PL Full — {oc.get('full_vehicle_name', 'Xe 3PL Full')} × {trips} chuyến", "tier": "FULL", "cost": float(oc.get("full_price", 0.0)),
            "trips": trips, "vehicle": oc.get("full_vehicle_name", "Xe 3PL Full"), "cap_w": trips * fw, "cap_v": trips * fv, "why": why}


def classify_outsourcing(excess_w, excess_v, oc=None, force_full=False) -> dict:
    oc = {**OC_DEFAULTS, **(oc or {})}
    w, v = max(float(excess_w), 0.0), max(float(excess_v), 0.0)
    if not force_full:
        if w < oc["tier2_max_w"] and v < oc["tier2_max_v"]:
            return {"type": "Tiết kiệm loại 2", "tier": "SAVING_2", "cost": float(oc["saving_2_price"]), "trips": 1,
                    "vehicle": "Tiết kiệm loại 2", "cap_w": float(oc["tier2_max_w"]), "cap_v": float(oc["tier2_max_v"]),
                    "why": f"tải {w:.1f}kg < {oc['tier2_max_w']:g}kg và {v:.2f}m³ < {oc['tier2_max_v']:g}m³ nên chọn Tiết kiệm 2"}
        if w <= oc["tier1_max_w"] and v <= oc["tier1_max_v"]:
            return {"type": "Tiết kiệm loại 1", "tier": "SAVING_1", "cost": float(oc["saving_1_price"]), "trips": 1,
                    "vehicle": "Tiết kiệm loại 1", "cap_w": float(oc["tier1_max_w"]), "cap_v": float(oc["tier1_max_v"]),
                    "why": f"tải {w:.1f}kg ≤ {oc['tier1_max_w']:g}kg và {v:.2f}m³ ≤ {oc['tier1_max_v']:g}m³ nên chọn Tiết kiệm 1"}
    return _full_cls(w, v, oc, "bắt buộc thuê Full" if force_full else None)


# ============================================================================
# 3.3  RÀNG BUỘC VẬN TẢI & THỜI GIAN
# ============================================================================
def evaluate_transportation_constraints(route_or_order, df_vehicles, vehicle_available_counts, outsourcing_config):
    oc = {**OC_DEFAULTS, **(outsourcing_config or {})}
    total_w = float(route_or_order.get("total_weight_kg", 0.0))
    total_v = float(route_or_order.get("total_volume_m3", 0.0))
    total_dist = float(route_or_order.get("total_distance_km", 0.0))

    def outsourced(action, cls, message):
        return {"status": "OUTSOURCED", "action_type": action, "assigned_vehicle": None, "outsourcing_type": cls["type"],
                "cost": cls["cost"], "cls": cls, "message": message}

    if df_vehicles.empty:
        return outsourced("NO_FLEET", _full_cls(total_w, total_v, oc, "bắt buộc khi kho không có xe nhà"), "⚠️ Hạm đội trống -> Thuê ngoài Full.")

    max_fleet_w, max_fleet_v = df_vehicles["max_weight_kg"].max(), df_vehicles["max_volume_m3"].max()
    sum_fleet_w, sum_fleet_v = df_vehicles["max_weight_kg"].sum(), df_vehicles["max_volume_m3"].sum()
    avail = df_vehicles[df_vehicles["vehicle_id"].map(lambda x: vehicle_available_counts.get(x, 1) > 0)]

    if total_w > 1.5 * max_fleet_w or total_v > 1.5 * max_fleet_v or total_w > sum_fleet_w or total_v > sum_fleet_v:
        return outsourced("OUTSOURCE_FULL", _full_cls(total_w, total_v, oc, f"hàng quá khủng vượt 150% xe lớn nhất nhà ({max_fleet_w:,.0f}kg/{max_fleet_v:.1f}m³)"),
                        f"🚨 Hàng quá khủng (vượt >150% xe lớn nhất nhà {max_fleet_w:,.0f}kg/{max_fleet_v:.1f}m³) -> Thuê ngoài 3PL Full ngay lập tức.")
    if total_w > max_fleet_w or total_v > max_fleet_v:
        if avail.empty:
            return outsourced("OUTSOURCE_NO_VEHICLE_AVAILABLE", classify_outsourcing(total_w, total_v, oc),
                            "⚠️ Hết xe khả dụng trong ngày -> thuê ngoài qua màn lọc.")
        big = avail.loc[avail["max_weight_kg"].idxmax()]
        v_id = big["vehicle_id"]
        vehicle_available_counts[v_id] = vehicle_available_counts.get(v_id, 1) - 1
        cls = classify_outsourcing(total_w - big["max_weight_kg"], total_v - big["max_volume_m3"], oc)
        return {"status": "PARTIAL_SPLIT", "action_type": "MAX_VEHICLE_PLUS_OUTSOURCE", "assigned_vehicle": v_id,
                "outsourcing_type": cls["type"], "cost": cls["cost"], "cls": cls,
                "message": f"⚠️ Vượt xe lớn nhất nhà nhưng <= 150% ({v_id}). Cắt xe này, phần dư thuê ngoài {cls['type']}."}

    feasible = avail[(avail["max_weight_kg"] >= total_w) & (avail["max_volume_m3"] >= total_v)] \
        .sort_values(by=["max_weight_kg", "max_volume_m3"], ascending=True)
    if feasible.empty:
        return outsourced("OUTSOURCE_NO_VEHICLE_AVAILABLE", classify_outsourcing(total_w, total_v, oc),
                        "⚠️ Đủ tải trọng nhưng hết xe khả dụng trong ngày -> thuê ngoài qua màn lọc.")

    veh = feasible.iloc[0]
    v_id, limit = veh["vehicle_id"], float(veh.get("Max_Distance", 100.0))
    if total_dist > limit:
        return {"status": "CUT_REQUIRED", "action_type": "DISTANCE_EXCEEDED_CUT", "assigned_vehicle": v_id,
                "outsourcing_type": None, "cost": 0.0, "cls": None, "max_distance_limit": limit,
                "message": f"⚠️ Tuyến vượt Max_Distance ({total_dist:.1f}km > {limit:.0f}km) của xe {v_id}. Cắt theo Units."}

    vehicle_available_counts[v_id] = vehicle_available_counts.get(v_id, 1) - 1
    return {"status": "APPROVED", "action_type": "IN_HOUSE_SUCCESS", "assigned_vehicle": v_id, "outsourcing_type": None,
            "cost": 0.0, "cls": None, "message": f"✅ Thỏa mãn trọng tải! Giao xe NHỎ NHẤT khả thi: {v_id}."}


def evaluate_time_constraints(route_or_order, chosen_vehicle=None, service_time_rules=None, max_hours=8.0):
    if service_time_rules is None:
        service_time_rules = {"B2C": {"loading": 25, "unloading": 35}, "B2B": {"loading": 45, "unloading": 60}}
    orders = route_or_order.get("orders", [])
    dist = float(route_or_order.get("total_distance_km", 0.0))
    speed = float(chosen_vehicle.get("average_speed_kmh", 40.0)) if chosen_vehicle is not None else 40.0
    travel = dist / speed if speed > 0 else 0.0
    rule = lambda o: service_time_rules.get(o.get("order_type", "B2C"), service_time_rules["B2C"])
    total = travel + sum(rule(o)["loading"] + rule(o)["unloading"] for o in orders) / 60.0
    if total <= max_hours + 1e-9:
        return {"status": "APPROVED", "action_type": "TIME_APPROVED", "total_hours": round(total, 2),
                "message": f"✅ Đạt yêu cầu thời gian tuyến: {round(total, 2)}h (<= {max_hours:g}h)."}
    return {"status": "CUT_TIME_EXCEEDED", "action_type": "TIME_WINDOW_CUT", "total_hours": round(total, 2),
            "message": f"⚠️ Tuyến vượt quá {max_hours:g} giờ ({round(total, 2)}h > {max_hours:g}h)! Cắt theo Units."}


# ============================================================================
# 3.4  ROUTE PLANNER (Clarke-Wright + 2-opt + dispatch)
# ============================================================================
_TAB_A_EVENTS = {
    "NO_FLEET": ("HIGH", "KHO KHÔNG CÓ XE", "Bổ sung xe cho kho"),
    "OUTSOURCE_FULL": ("CRITICAL", "VƯỢT TỔNG HẠM ĐỘI", "Cần xe 3PL Full"),
    "OUTSOURCE_NO_VEHICLE_AVAILABLE": ("MEDIUM", "HẾT XE TRONG NGÀY", "Bổ sung xe / dời lịch"),
    "MAX_VEHICLE_PLUS_OUTSOURCE": ("CRITICAL", "ĐƠN QUÁ CỠ", "Cần xe 3PL Full"),
}


class RoutePlanner:
    def __init__(self, data: dict, cfg: Config = CFG):
        self.cfg = cfg
        self.veh = data["vehicles"]
        self.cust = data["cust"]
        self.wh = data["warehouses"]
        self.detour = cfg.detour_factor
        self.max_hours = calculate_effective_max_hours(cfg.start_time, cfg.max_route_hours)
        if self.veh.empty:
            self.catalog = pd.DataFrame(columns=["w", "v", "speed", "fixed", "var", "dist"])
        else:
            self.catalog = (self.veh.groupby("vehicle_type")
                .agg(w=("max_weight_kg", "max"), v=("max_volume_m3", "max"), speed=("average_speed_kmh", "first"),
                     fixed=("fixed_cost", "first"), var=("variable_cost", "first"), dist=("Max_Distance", "max"))
                .sort_values("w"))
        self.max_w = float(self.catalog["w"].max()) if not self.catalog.empty else 1000.0
        self.max_v = float(self.catalog["v"].max()) if not self.catalog.empty else 5.0
        self.max_dist = float(self.catalog["dist"].max()) if not self.catalog.empty else 100.0
        self._fleet = {}
        for rec in self.veh.to_dict("records"): self._fleet.setdefault(rec["id_warehouse"], []).append(rec)
        for lst in self._fleet.values(): lst.sort(key=lambda r: (r["max_weight_kg"], r["max_volume_m3"]))

    # ------------------------------------------------------------------ khoảng cách
    def _hav(self, a, b) -> float:
        return haversine(a["lat"], a["lng"], b["lat"], b["lng"]) * self.detour

    def d_cc(self, i, j) -> float:
        if i == j: return 0.0
        if i in self.cust and j in self.cust:
            return self._hav(self.cust[i], self.cust[j])
        return 0.0

    def d_wc(self, wh_id, c) -> float:
        if wh_id in self.wh and c in self.cust:
            return self._hav(self.wh[wh_id], self.cust[c])
        return 0.0

    def nearest_wh(self, c) -> str:
        return min(self.wh, key=lambda w: self.d_wc(w, c))

    def km(self, route, wh_id) -> float:
        if not route: return 0.0
        return self.d_wc(wh_id, route[0]) + self.d_wc(wh_id, route[-1]) + sum(self.d_cc(a, b) for a, b in zip(route, route[1:]))

    # ------------------------------------------------------------------ xe & chỉ số tuyến
    def caps(self, wh_id):
        lst = self._fleet.get(wh_id)
        if not lst: return self.max_w, self.max_v, self.max_dist
        return max(r["max_weight_kg"] for r in lst), max(r["max_volume_m3"] for r in lst), max(r["Max_Distance"] for r in lst)

    def smallest_vehicle(self, wh_id, w, v):
        for r in self._fleet.get(wh_id, []):
            if r["max_weight_kg"] >= w and r["max_volume_m3"] >= v: return r
        return None

    def fit_type(self, w, v):
        if self.catalog.empty: return "Truck"
        ok = self.catalog[(self.catalog["w"] >= w) & (self.catalog["v"] >= v)]
        return ok.index[0] if not ok.empty else self.catalog.index[-1]

    def metrics(self, route, wh_id, demand):
        w = sum(demand[c]["weight"] for c in route)
        v = sum(demand[c]["volume"] for c in route)
        qty = sum(demand[c]["qty"] for c in route)
        km = self.km(route, wh_id)
        veh = self.smallest_vehicle(wh_id, w, v)
        vtype = veh["vehicle_type"] if veh else self.fit_type(w, v)
        speed = float(veh["average_speed_kmh"]) if veh else (float(self.catalog.loc[vtype, "speed"]) if vtype in self.catalog.index else 35.0)
        service = sum(demand[c]["service_min"] for c in route) / 60.0
        return {"w": w, "v": v, "qty": qty, "km": km, "hours": km / speed + service, "vtype": vtype, "speed": speed, "veh": veh}

    def feasible(self, route, wh_id, demand) -> bool:
        cap_w, cap_v, _ = self.caps(wh_id)
        m = self.metrics(route, wh_id, demand)
        if m["w"] > cap_w or m["v"] > cap_v or m["hours"] > self.max_hours: return False
        if m["veh"] is None: return not self._fleet.get(wh_id)
        return m["km"] <= m["veh"]["Max_Distance"]

    def route_cost(self, route, wh_id, demand) -> float:
        m = self.metrics(route, wh_id, demand)
        veh = m["veh"]
        if veh is None:
            return float(classify_outsourcing(m["w"], m["v"], self.cfg.outsourcing)["cost"])
        return float(veh.get("fixed_cost", 0.0)) + float(veh.get("variable_cost", 0.0)) * m["km"]

    # ------------------------------------------------------------------ 2-opt
    def two_opt(self, route, wh_id):
        def edge(a, b):
            if a is None: return self.d_wc(wh_id, b)
            if b is None: return self.d_wc(wh_id, a)
            return self.d_cc(a, b)
        best, improved = route[:], True
        while improved and len(best) > 2:
            improved = False
            base = self.km(best, wh_id)
            for i in range(len(best) - 1):
                for j in range(i + 1, len(best)):
                    prev = None if i == 0 else best[i - 1]
                    nxt = None if j == len(best) - 1 else best[j + 1]
                    old = edge(prev, best[i]) + edge(best[j], nxt)
                    new = edge(prev, best[j]) + edge(best[i], nxt)
                    if new >= old - 1e-9: continue
                    cand = best[:i] + best[i:j + 1][::-1] + best[j + 1:]
                    cand_km = self.km(cand, wh_id)
                    if cand_km < base - 1e-9: best, base, improved = cand, cand_km, True
        return best

    # ------------------------------------------------------------------ Clarke-Wright
    def savings_list(self, custs, wh_id):
        out = [(self.d_wc(wh_id, a) + self.d_wc(wh_id, b) - self.d_cc(a, b), a, b)
               for k, a in enumerate(custs) for b in custs[k + 1:]]
        out.sort(key=lambda t: (-t[0], str(t[1]), str(t[2])))
        return out

    def clarke_wright(self, custs, wh_id, demand):
        route_of = {c: [c] for c in custs}
        for s, a, b in self.savings_list(custs, wh_id):
            if s <= 0: break
            ra, rb = route_of[a], route_of[b]
            if ra is rb or a not in (ra[0], ra[-1]) or b not in (rb[0], rb[-1]): continue
            ra = ra if ra[-1] == a else ra[::-1]
            rb = rb if rb[0] == b else rb[::-1]
            merged = ra + rb
            if not self.feasible(merged, wh_id, demand): continue
            if self.route_cost(merged, wh_id, demand) > self.route_cost(ra, wh_id, demand) + self.route_cost(rb, wh_id, demand) + 1e-9: continue
            for c in merged: route_of[c] = merged
        return [self.two_opt(r, wh_id) for r in {id(r): r for r in route_of.values()}.values()]

    def _priority(self, route, wh_id, demand):
        w = sum(demand[c]["weight"] for c in route)
        v = sum(demand[c]["volume"] for c in route)
        return (-float(classify_outsourcing(w, v, self.cfg.outsourcing)["cost"]), -self.km(route, wh_id))

    # ------------------------------------------------------------------ nhu cầu & cắt đơn
    def _demand(self, ords):
        demand, by_cust = {}, {}
        for o in ords:
            d = demand.setdefault(o["customer_id"], {"weight": 0.0, "volume": 0.0, "qty": 0, "service_min": 0.0})
            d["weight"] += o["total_weight_kg"]; d["volume"] += o["total_volume_m3"]
            d["qty"] += o.get("quantity", 1)
            d["service_min"] += self.cfg.service_min.get(o["order_type"], 60)
            by_cust.setdefault(o["customer_id"], []).append(o)
        return demand, by_cust

    def _worst_stop_by_units(self, r, wh_id, demand):
        mode = getattr(self.cfg, "constraint_mode", "Cube Out (Thể tích m³)")
        base = self.km(r, wh_id)
        if "Weight Out" in mode:
            return max(r, key=lambda c: (demand[c]["weight"] / max(demand[c]["qty"], 1), base - self.km([x for x in r if x != c], wh_id)))
        return max(r, key=lambda c: (demand[c]["volume"] / max(demand[c]["qty"], 1), base - self.km([x for x in r if x != c], wh_id)))

    def _start(self, date_str, start_str=None):
        return dt.datetime.combine(pd.to_datetime(date_str).date(), dt.datetime.strptime(start_str or self.cfg.start_time, "%H:%M").time())

    def _why_outsource(self, action, m, fleet, wh_id):
        load = f"{m['w']:,.0f}kg/{m['v']:.1f}m³ ({m['qty']} units)"
        if action == "NO_FLEET": return f"kho {wh_id} không có xe nhà (tải {load})"
        if action == "OUTSOURCE_FULL":
            return f"tải {load} vượt quá 150% xe lớn nhất nhà"
        return f"kho {wh_id} hết xe nhà phù hợp trong ngày (tải {load})"

    def _calculate_load_factor(self, m, vrow, cls):
        mode = getattr(self.cfg, "constraint_mode", "Cube Out (Thể tích m³)")
        if "Cube Out" in mode:
            cap_v = float(vrow["max_volume_m3"]) if vrow is not None else float(cls.get("cap_v", 40.0))
            return min(m["v"] / cap_v, 1.0) if cap_v > 0 else 0.0
        else:
            cap_w = float(vrow["max_weight_kg"]) if vrow is not None else float(cls.get("cap_w", 10000.0))
            return min(m["w"] / cap_w, 1.0) if cap_w > 0 else 0.0

    # ------------------------------------------------------------------ tạo tuyến thuê ngoài
    def _outsource_route(self, custs, wh_id, demand, by_cust, cls, events, date_str, km=None, reason=None):
        cfg = self.cfg
        if km is None:
            custs = self.two_opt(list(custs), wh_id); km = self.km(custs, wh_id)
        w = sum(demand[c]["weight"] for c in custs)
        v = sum(demand[c]["volume"] for c in custs)
        q = sum(demand[c]["qty"] for c in custs)
        hours = km / cfg.outsourced_speed_kmh + sum(demand[c]["service_min"] for c in custs) / 60.0
        start = self._start(date_str)
        if reason is None:
            reason = "; ".join(e.get("why", e["detail"]) for e in events) or "vượt khả năng xe nhà"
        reason = f"{reason} → {cls['why']}"

        load_factor = self._calculate_load_factor({"w": w, "v": v}, None, cls)

        return {
            "kind": "OUTSOURCE", "id_warehouse": wh_id, "route": list(custs), "orders": [o for c in custs for o in by_cust[c]],
            "vehicle_id": f"3PL-{cls['tier']}", "license_plate": f"Thuê ngoài 3PL ({cls['type']})", "vehicle_type": cls["vehicle"],
            "external": True, "driver_primary": "Đối tác 3PL", "driver_assistant": "—", "is_backup_driver": False,
            "km": round(km, 1), "speed_kmh": cfg.outsourced_speed_kmh,
            "load_factor": load_factor,
            "fixed_cost": 0.0, "variable_cost": 0.0, "overnight_cost": 0.0, "driver_cost": 0.0,
            "outsourcing_cost": float(cls["cost"]), "outsourcing_type": cls["type"],
            "cut_orders": [], "cut_weight_kg": 0.0, "cut_volume_m3": 0.0,
            "cap_w": float(cls["cap_w"]), "cap_v": float(cls.get("cap_v", 40.0)), "total_weight_kg": w, "total_volume_m3": v, "total_qty": q,
            "reason": reason, "trip_no": None,
            "start": start, "end": start + dt.timedelta(hours=hours), "hours": hours, "events": events,
        }

    # ------------------------------------------------------------------ dispatch: gán xe, kiểm ràng buộc, cắt đơn
    def _dispatch(self, route, wh_id, demand, by_cust, veh_counts, date_str, veh_free=None):
        cfg, oc = self.cfg, self.cfg.outsourcing
        veh_free = {} if veh_free is None else veh_free
        rules = service_rules_from_cfg(cfg)
        fleet = self.veh[self.veh["id_warehouse"] == wh_id]
        for vid_, t_ in veh_free.items():
            if calculate_effective_max_hours(t_, cfg.max_route_hours) <= 0: veh_counts[vid_] = 0
        r, cut, final, blocked = list(route), [], None, {}
        while r:
            m = self.metrics(r, wh_id, demand)
            snap = dict(veh_counts)
            ta = evaluate_transportation_constraints(
                {"total_weight_kg": m["w"], "total_volume_m3": m["v"], "total_distance_km": m["km"]}, fleet, veh_counts, oc)
            action, vid, tb, bad = ta["action_type"], ta.get("assigned_vehicle"), None, None
            vrow = fleet[fleet["vehicle_id"] == vid].iloc[0] if (vid and ta["status"] != "OUTSOURCED") else None
            start_str = veh_free.get(vid, cfg.start_time) if vrow is not None else cfg.start_time
            max_h = calculate_effective_max_hours(start_str, cfg.max_route_hours)

            if action == "DISTANCE_EXCEEDED_CUT":
                bad = ("VƯỢT MAX_DISTANCE", ta["message"], f"tuyến {m['km']:.1f}km > Max_Distance {ta['max_distance_limit']:.0f}km của xe {vid}")
            elif vrow is not None:
                if m["km"] > float(vrow["Max_Distance"]):
                    bad = ("VƯỢT MAX_DISTANCE", f"Tuyến {m['km']:.1f}km > Max_Distance {float(vrow['Max_Distance']):.0f}km của xe {vid}.",
                           f"tuyến {m['km']:.1f}km > Max_Distance {float(vrow['Max_Distance']):.0f}km của xe {vid}")
                else:
                    tb = evaluate_time_constraints({"total_distance_km": m["km"], "orders": [o for c in r for o in by_cust[c]],
                                                   "current_date": date_str}, {"average_speed_kmh": float(vrow["average_speed_kmh"])},
                                                   rules, max_h)
                    if tb["status"] != "APPROVED" and start_str != cfg.start_time and vid not in blocked:
                        veh_counts.clear(); veh_counts.update(snap)
                        blocked[vid] = veh_counts.get(vid, 0); veh_counts[vid] = 0
                        continue
                    if tb["status"] != "APPROVED":
                        bad = ("VƯỢT GIỜ TUYẾN", tb["message"],
                               f"tuyến {tb['total_hours']:.2f}h > giới hạn {max_h:g}h (xe {vid} xuất phát lúc {start_str})")
            if bad:
                veh_counts.clear(); veh_counts.update(snap)
                c = self._worst_stop_by_units(r, wh_id, demand)
                cut.append((c, bad[0], bad[1], bad[2]))
                r = self.two_opt([x for x in r if x != c], wh_id)
                continue
            final = (m, ta, action, vid, vrow, tb, start_str)
            break
        for v_, n_ in blocked.items(): veh_counts[v_] = n_
        out = []
        if final:
            m, ta, action, vid, vrow, tb, start_str = final
            if ta["status"] == "OUTSOURCED":
                sev, kind, propose = _TAB_A_EVENTS[action]
                why = self._why_outsource(action, m, fleet, wh_id)
                ev = [{"sev": sev, "kind": kind, "detail": ta["message"], "why": why, "handled": f"Thuê ngoài {ta['cls']['type']}", "propose": propose}]
                out.append(self._outsource_route(r, wh_id, demand, by_cust, ta["cls"], ev, date_str, reason=why))
            else:
                split = action == "MAX_VEHICLE_PLUS_OUTSOURCE"
                primary, assistant, backup = "Chờ phân công", "—", False
                start, hours = self._start(date_str, start_str), tb["total_hours"]
                cap_w, cap_v = float(vrow["max_weight_kg"]), float(vrow["max_volume_m3"])
                ev, reason = [], ""
                if split:
                    sev, kind, propose = _TAB_A_EVENTS[action]
                    ex_w, ex_v = max(m["w"] - cap_w, 0.0), max(m["v"] - cap_v, 0.0)
                    reason = (f"tải {m['w']:,.0f}kg/{m['v']:.1f}m³ ({m['qty']} units) vượt xe lớn nhất nhà ({vid}: {cap_w:,.0f}kg/{cap_v:g}m³), "
                              f"phần dư {ex_w:,.0f}kg/{ex_v:.1f}m³ → {ta['cls']['why']}")
                    ev.append({"sev": sev, "kind": kind, "detail": ta["message"], "why": reason,
                               "handled": f"Cắt xe {vid} + thuê ngoài {ta['cls']['type']}", "propose": propose})
                orders = [o for c in r for o in by_cust[c]]
                end_dt = start + dt.timedelta(hours=hours)
                next_start_dt = end_dt + dt.timedelta(minutes=cfg.turnaround_min)
                veh_free[vid] = f"{next_start_dt:%H:%M}" if next_start_dt.date() == start.date() else "23:59"

                load_factor = self._calculate_load_factor(m, vrow, {})

                out.append({
                    "kind": "SPLIT" if split else "NORMAL", "id_warehouse": wh_id, "route": list(r), "orders": orders,
                    "vehicle_id": vid, "license_plate": vrow["license_plate"], "vehicle_type": vrow["vehicle_type"], "external": False,
                    "driver_primary": primary, "driver_assistant": assistant, "is_backup_driver": backup,
                    "km": round(m["km"], 1), "speed_kmh": float(vrow["average_speed_kmh"]),
                    "load_factor": load_factor,
                    "fixed_cost": float(vrow["fixed_cost"]), "variable_cost": float(vrow["variable_cost"]) * m["km"], "overnight_cost": 0.0,
                    "driver_cost": cfg.backup_driver_cost if backup else 0.0,
                    "outsourcing_cost": float(ta["cost"]) if split else 0.0, "outsourcing_type": ta["outsourcing_type"] if split else None,
                    "cut_orders": [o["order_id"] for o in orders] if split else [],
                    "cut_weight_kg": max(m["w"] - cap_w, 0.0) if split else 0.0,
                    "cut_volume_m3": max(m["v"] - cap_v, 0.0) if split else 0.0,
                    "cap_w": cap_w, "cap_v": cap_v, "total_weight_kg": m["w"], "total_volume_m3": m["v"], "total_qty": m["qty"],
                    "reason": reason if split else "",
                    "trip_no": max(1, cfg.vehicle_daily_count - veh_counts.get(vid, 0)),
                    "start": start, "end": end_dt, "hours": hours, "events": ev,
                })
        if cut:
            ids = [c for c, _, _, _ in cut]
            cls = classify_outsourcing(sum(demand[c]["weight"] for c in ids), sum(demand[c]["volume"] for c in ids), oc)

            cut_details = []
            for c, kind, detail, short in cut:
                orders_c = by_cust.get(c, [])
                order_ids_str = ", ".join(o["order_id"] for o in orders_c) if orders_c else c
                addr_str = orders_c[0].get("address", "") if orders_c else ""
                cut_details.append(f"đơn {order_ids_str} ({addr_str}) cắt do {short}")

            reason_cut_str = "; ".join(cut_details)
            ev = [{"sev": "HIGH", "kind": kind, "detail": f"Đơn khách {c}: {detail}", "why": f"đơn {c} bị cắt do {short}",
                   "handled": f"Cắt khỏi tuyến → thuê ngoài {cls['type']}", "propose": "Bổ sung tọa độ hoặc kiểm tra Max_Distance xe", "ids": [c]}
                  for c, kind, detail, short in cut]
            out.append(self._outsource_route(ids, wh_id, demand, by_cust, cls, ev, date_str, reason=reason_cut_str))
        return out

    # ------------------------------------------------------------------ lập kế hoạch 1 ngày
    def plan_day(self, date_str: str, day_orders: list) -> dict:
        cfg = self.cfg
        res = {"routes": [], "overdue_routes": [], "unrouted_orders": [], "exceptions": [], "day_cost": 0.0, "orders": list(day_orders)}

        def log(r):
            for e in r.pop("events"):
                for o in r["orders"]:
                    if e.get("ids") is None or o["customer_id"] in e["ids"]:
                        res["exceptions"].append({"NGÀY": date_str, "MỨC ĐỘ": e["sev"], "MÃ ĐƠN": o["order_id"], "PHÂN LOẠI": e["kind"],
                                                  "CHI TIẾT": e["detail"], "ĐÃ XỬ LÝ": e["handled"], "ĐỀ XUẤT": e["propose"]})

        placed = [o for o in day_orders if o.get("lat") is not None and o.get("lng") is not None]
        unplaced = [o for o in day_orders if o.get("lat") is None or o.get("lng") is None]

        for o in placed:
            self.cust[o["customer_id"]] = {"lat": float(o["lat"]), "lng": float(o["lng"]), "name": o["customer_id"]}

        veh_counts = {vid: cfg.vehicle_daily_count for vid in self.veh["vehicle_id"]}
        veh_free = {}

        by_wh = {}
        for o in placed: by_wh.setdefault(self.nearest_wh(o["customer_id"]), []).append(o)
        for wh_id, ords in by_wh.items():
            demand, by_cust = self._demand(ords)
            routes = self.clarke_wright(list(demand), wh_id, demand)
            routes.sort(key=lambda rt: self._priority(rt, wh_id, demand))
            for rt in routes:
                for r in self._dispatch(rt, wh_id, demand, by_cust, veh_counts, date_str, veh_free):
                    log(r); res["routes"].append(r)

        res["unrouted_orders"] = unplaced
        res["day_cost"] = sum(route_total(r) for r in res["routes"])
        return res


# ============================================================================
# 3.5  MÔ PHỎNG TOÀN BỘ CÁC NGÀY + KPI
# ============================================================================
def route_total(r):
    return r["fixed_cost"] + r["variable_cost"] + r["overnight_cost"] + r.get("driver_cost", 0) + r.get("outsourcing_cost", 0)


def simulate_all(data: dict, cfg: Config = CFG):
    planner = RoutePlanner(data, cfg)
    by_date = {}
    for o in data["orders"]: by_date.setdefault(o["order_date"], []).append(o)
    days = {d: planner.plan_day(d, by_date[d]) for d in sorted(by_date)}
    all_r = [r for d in days.values() for r in d["routes"] + d["overdue_routes"]]

    # 🌟 TÍNH TỈ LỆ LẤP ĐẦY TRUNG BÌNH CHỈ TRÊN XE NHÀ 🌟
    inhouse_only_routes = [r for r in all_r if not r["external"]]
    avg_load_factor = (sum(r["load_factor"] for r in inhouse_only_routes) / len(inhouse_only_routes)) if inhouse_only_routes else 0.0

    delivered = {o["order_id"] for r in all_r for o in r["orders"]}
    n_routes = len(all_r)
    operating = sum(d["day_cost"] for d in days.values())

    unrouted_count = sum(len(d["unrouted_orders"]) for d in days.values())

    kpis = {
        "violations": sum(1 for r in all_r if not r["external"] and r["hours"] > cfg.max_route_hours + 1e-9),
        "operating_cost": operating,
        "external_ratio": sum(r["external"] for r in all_r) / n_routes if n_routes else 0,
        "avg_load_factor": avg_load_factor,
        "undelivered_orders": len(data["orders"]) - len(delivered),
        "unrouted_orders": unrouted_count,
        "total_orders": len(data["orders"]),
    }
    return planner, days, kpis, operating

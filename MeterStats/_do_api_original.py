def _do_api(method: str, handler: BaseHTTPRequestHandler, path: str):
    """实际路由逻辑。"""

    def _get(model: str):
        """快捷读取某模型数据。"""
        return load_json(DATA_PATHS.get(model), [])

    def _save(model: str, data):
        """快捷保存某模型数据。"""
        save_json(DATA_PATHS.get(model), data)

    # OPTIONS — 预检
    if method == "OPTIONS":
        handler.send_response(204)
        for k, v in CORS.items():
            handler.send_header(k, v)
        handler.end_headers()
        return

    # ---------- GET ----------
    if method == "GET":
        path_clean = path.split("?", 1)[0]

        # /api/health
        if path_clean == "/api/health":
            data_dir = DATA_PATHS.get("readings")
            counts = {}
            parent = None
            if data_dir:
                parent = data_dir.parent
                for name in get_all_model_names():
                    fp = DATA_PATHS.get(name)
                    if fp:
                        try:
                            counts[name] = len(load_json(fp))
                        except Exception:
                            counts[name] = 0
                    else:
                        counts[name] = 0
            send_json(handler, 200, {
                "status": "ok",
                "version": "0.1.0",
                "data_dir": str(parent) if data_dir else None,
                "file_count": counts,
                "time": datetime.now().isoformat(),
            })
            return

        # /api/export?models=readings,charges,items,purchases
        if path_clean == "/api/export":
            qs = parse_qs(urlparse(handler.path).query)
            models_str = qs.get("models", ["readings,charges"])[0]
            models = [m.strip() for m in models_str.split(",")]

            headers_map = {
                "readings": ["date", "hall", "fire", "private_room", "ac", "main_meter", "sub_meter", "water", "note"],
                "charges": ["id", "date", "hall", "fire", "private_room", "ac", "note"],
                "items": ["id", "name", "qty", "unit", "note", "created_at"],
                "purchases": ["id", "date", "name", "qty", "unit", "est_price", "supplier", "status", "note"],
            }

            for model in models:
                model = model.strip()
                if model not in DATA_FILES:
                    send_json(handler, 400, {"error": f"不支持导出的模型: {model}"})
                    return

                filename = f"meter_{model}_{datetime.now().strftime('%Y%m%d')}.csv"
                cols = headers_map.get(model, [])
                data = _get(model)
                if cols:
                    rows = [[row.get(c, "") for c in cols] for row in data]
                else:
                    rows = []
                send_csv(handler, filename, cols, rows)
                return

            send_json(handler, 400, {"error": "至少指定一个 models 参数"})
            return

        # /api/monthly-report
        if path_clean == "/api/monthly-report":
            qs = parse_qs(urlparse(handler.path).query)
            month = qs.get("month", [""])[0]
            if not month or len(month) != 7:
                send_json(handler, 400, {"error": "需要 month 参数,格式: 2026-07"})
                return

            result = calculate_monthly_report(_get("readings"), _get("charges"), month)
            send_json(handler, 200, result)
            return

        # /api/yearly-report
        if path_clean == "/api/yearly-report":
            qs = parse_qs(urlparse(handler.path).query)
            year = qs.get("year", [""])[0]
            if not year or len(year) != 4 or not year.isdigit():
                send_json(handler, 400, {"error": "需要 year 参数,格式: 2026"})
                return
            result = calculate_yearly_report(_get("readings"), _get("charges"), year)
            send_json(handler, 200, result)
            return

        # /api/monthly-utilities — 月度水电(总表/分表/厨房/水表,普通递增表,每月抄一次)
        # 厨房 = 总表 - 分表(不直接抄);电费 0.9 元/度,水费 4.5 元/吨
        if path_clean == "/api/monthly-utilities":
            qs = parse_qs(urlparse(handler.path).query)
            month = qs.get("month", [""])[0]
            if not month or len(month) != 7:
                send_json(handler, 400, {"error": "需要 month 参数,格式: 2026-07"})
                return
            readings = _get("readings")
            cur_rs = sorted([r for r in readings if str(r.get("date", "")).startswith(month)],
                            key=lambda r: r["date"])
            # 该月是否有水电表底(总表/分表/水表任一);没有 → 提示未录入而非全 — 卡片
            has_water_data = any(
                r.get("main_meter") is not None or r.get("sub_meter") is not None or r.get("water") is not None
                for r in cur_rs
            )
            if not cur_rs or not has_water_data:
                send_json(handler, 200, {"month": month, "has_data": False,
                                         "msg": "该月未录入水电表底"})
                return
            # 上月最后一条(用于算差值;递增表:本月读数 - 上月读数 = 本月用量)
            y, m = int(month[:4]), int(month[5:7])
            py, pm = (y - 1, 12) if m == 1 else (y, m - 1)
            prev_key = f"{py:04d}-{pm:02d}"
            prev_rs = sorted([r for r in readings if str(r.get("date", "")).startswith(prev_key)],
                             key=lambda r: r["date"])
            cur = cur_rs[-1]
            has_prev = bool(prev_rs)
            prev = prev_rs[-1] if has_prev else None

            def _diff(cur_v, prev_v):
                if cur_v is None or prev_v is None:
                    return None
                return round(max(cur_v - prev_v, 0), 1)  # 防负(换表/反装)

            # 读数差 × 倍率 = 实际用电(总表 ×50,分表 ×40)
            main_raw = _diff(cur.get("main_meter"), prev.get("main_meter") if prev else None)
            sub_raw = _diff(cur.get("sub_meter"), prev.get("sub_meter") if prev else None)
            main_kwh = round(main_raw * MAIN_METER_MULT, 1) if main_raw is not None else None
            sub_kwh = round(sub_raw * SUB_METER_MULT, 1) if sub_raw is not None else None
            kitchen_kwh = round(main_kwh - sub_kwh, 1) if main_kwh is not None and sub_kwh is not None else None
            kitchen_cost = round(kitchen_kwh * ELECTRICITY_PRICE, 2) if kitchen_kwh is not None else None
            water_usage = _diff(cur.get("water"), prev.get("water") if prev else None)
            water_cost = round(water_usage * WATER_PRICE, 2) if water_usage is not None else None

            send_json(handler, 200, {
                "month": month,
                "has_data": True,
                "has_prev": has_prev,
                "cur": {"date": cur["date"],
                        "main_meter": cur.get("main_meter"),
                        "sub_meter": cur.get("sub_meter"),
                        "water": cur.get("water")},
                "prev_date": prev["date"] if prev else None,
                "main_kwh": main_kwh,
                "sub_kwh": sub_kwh,
                "kitchen_kwh": kitchen_kwh,
                "kitchen_cost": kitchen_cost,
                "water_usage": water_usage,
                "water_cost": water_cost,
                "price_electricity": ELECTRICITY_PRICE,
                "price_water": WATER_PRICE,
                "mult_main": MAIN_METER_MULT,
                "mult_sub": SUB_METER_MULT,
            })
            return

        # 普通数据查询
        model_map = {"/api/readings": "readings", "/api/charges": "charges",
                     "/api/items": "items", "/api/purchases": "purchases"}
        if path_clean in model_map:
            send_json(handler, 200, _get(model_map[path_clean]))
            return

        send_json(handler, 404, {"error": "未知 API 路径"})
        return

    # ---------- POST ----------
    if method == "POST":
        body = read_body(handler)
        path_clean = path.split("?", 1)[0]

        # /api/backup — 手动触发备份(force=True,带时间戳目录)
        if path_clean == "/api/backup":
            data_dir = Path(next(iter(DATA_PATHS.values()))).parent if DATA_PATHS else ROOT.parent
            result = backup_data(data_dir, force=True)
            send_json(handler, 200, {"ok": True, "backup_dir": str(result)})
            return

        if path_clean == "/api/readings":
            date = body.get("date")
            if not date:
                send_json(handler, 400, {"error": "缺少 date 字段"})
                return
            readings = _get("readings")
            new_row = {
                "date": date,
                "hall": _opt_float(body, "hall"),
                "fire": _opt_float(body, "fire"),
                "private_room": _opt_float(body, "private_room"),
                "ac": _opt_float(body, "ac"),
                "main_meter": _opt_float(body, "main_meter"),
                "sub_meter": _opt_float(body, "sub_meter"),
                "water": _opt_float(body, "water"),
                "note": str(body.get("note", "") or ""),
            }
            # 至少填一项(4 表或水电任一有值);全空 → 400,防止垃圾数据
            if all(new_row[k] is None for k in ("hall", "fire", "private_room", "ac", "main_meter", "sub_meter", "water")):
                send_json(handler, 400, {"error": "至少填写一块表的读数"})
                return
            idx = next((i for i, r in enumerate(readings) if r.get("date") == date), None)
            if idx is not None:
                # 覆盖:表单没填的字段(null)保留旧值 — 补录水电时不会清掉已有 4 表读数
                old = readings[idx]
                for k in ("hall", "fire", "private_room", "ac", "main_meter", "sub_meter", "water"):
                    if new_row[k] is None:
                        new_row[k] = old.get(k)
                readings[idx] = new_row
                log(f"  >> 覆盖抄表 {date}: 大厅 {new_row['hall']} 消防 {new_row['fire']} 包厢 {new_row['private_room']} 空调 {new_row['ac']}")
            else:
                readings.append(new_row)
                log(f"  ++ 新增抄表 {date}: 大厅 {new_row['hall']} 消防 {new_row['fire']} 包厢 {new_row['private_room']} 空调 {new_row['ac']}")
            _save("readings", readings)
            send_json(handler, 200, {"ok": True, "row": new_row})

        elif path_clean == "/api/charges":
            date = body.get("date")
            if not date:
                send_json(handler, 400, {"error": "缺少 date 字段"})
                return
            charge = {
                "id": f"{date}-{int(datetime.now().timestamp() * 1000)}",
                "date": date,
                "hall": float(body.get("hall", 0) or 0),
                "fire": float(body.get("fire", 0) or 0),
                "private_room": float(body.get("private_room", 0) or 0),
                "ac": float(body.get("ac", 0) or 0),
                "note": str(body.get("note", "") or ""),
            }
            # 校验: 四个表全为 0 就不算有效充值
            total = charge["hall"] + charge["fire"] + charge["private_room"] + charge["ac"]
            if total == 0:
                send_json(handler, 400, {"error": "至少一个表需要大于 0 的充值度数"})
                return
            charges = _get("charges")
            charges.append(charge)
            _save("charges", charges)
            log(f"  ++ 新增充值 {date}: 大厅 {charge['hall']} 消防 {charge['fire']} 包厢 {charge['private_room']} 空调 {charge['ac']}")
            send_json(handler, 200, {"ok": True, "row": charge})
        else:
            send_json(handler, 404, {"error": "未知 API 路径"})

    # ---------- PUT ----------
    if method == "PUT":
        body = read_body(handler)
        path_clean = path.split("?", 1)[0]

        # /api/readings/{date}
        if path_clean.startswith("/api/readings/"):
            date = path_clean[len("/api/readings/"):]
            readings = _get("readings")
            idx = next((i for i, r in enumerate(readings) if r.get("date") == date), None)
            if idx is None:
                send_json(handler, 404, {"error": f"未找到 {date}"})
                return
            for k in ("hall", "fire", "private_room", "ac", "main_meter", "sub_meter", "water"):
                if k in body:
                    readings[idx][k] = _opt_float(body, k)
            if "note" in body:
                readings[idx]["note"] = str(body.get("note", "") or "")
            _save("readings", readings)
            send_json(handler, 200, {"ok": True, "row": readings[idx]})

        # /api/charges/{id}
        elif path_clean.startswith("/api/charges/"):
            cid = path_clean[len("/api/charges/"):]
            charges = _get("charges")
            idx = next((i for i, c in enumerate(charges) if c.get("id") == cid), None)
            if idx is None:
                send_json(handler, 404, {"error": f"未找到 {cid}"})
                return
            for k in ("hall", "fire", "private_room", "ac"):
                if k in body:
                    charges[idx][k] = float(body.get(k) or 0)
                    if charges[idx][k] < 0:
                        send_json(handler, 400, {"error": "充值度数不能为负数"})
                        return
            for k in ("date", "note"):
                if k in body:
                    charges[idx][k] = body[k]
            _save("charges", charges)
            send_json(handler, 200, {"ok": True, "row": charges[idx]})

        # /api/items (POST via PUT for simplicity)
        elif path_clean == "/api/items":
            items = _get("items")
            new_item = {
                "id": f"item-{int(datetime.now().timestamp() * 1000)}",
                "name": str(body.get("name", "")).strip(),
                "qty": float(body.get("qty", 0) or 0),
                "unit": str(body.get("unit", "")).strip(),
                "note": str(body.get("note", "") or ""),
                "created_at": datetime.now().isoformat(),
            }
            if not new_item["name"]:
                send_json(handler, 400, {"error": "name 不能为空"})
                return
            if new_item["qty"] < 0:
                send_json(handler, 400, {"error": "数量不能为负数"})
                return
            items.append(new_item)
            _save("items", items)
            send_json(handler, 200, {"ok": True, "row": new_item})

        # /api/purchases (同上)
        elif path_clean == "/api/purchases":
            purchases = _get("purchases")
            new_purchase = {
                "id": f"p-{int(datetime.now().timestamp() * 1000)}",
                "date": body.get("date") or datetime.now().strftime("%Y-%m-%d"),
                "name": str(body.get("name", "")).strip(),
                "qty": float(body.get("qty", 0) or 0),
                "unit": str(body.get("unit", "")).strip(),
                "est_price": float(body.get("est_price", 0) or 0),
                "supplier": str(body.get("supplier", "") or ""),
                "status": "pending",
                "note": str(body.get("note", "") or ""),
            }
            if not new_purchase["name"]:
                send_json(handler, 400, {"error": "name 不能为空"})
                return
            if new_purchase["qty"] < 0:
                send_json(handler, 400, {"error": "数量不能为负数"})
                return
            if new_purchase["est_price"] < 0:
                send_json(handler, 400, {"error": "预估金额不能为负数"})
                return
            purchases.append(new_purchase)
            _save("purchases", purchases)
            send_json(handler, 200, {"ok": True, "row": new_purchase})

        # /api/purchases/{id}/stock (stock in)
        elif path_clean.startswith("/api/purchases/") and path_clean.endswith("/stock"):
            pid = path_clean[len("/api/purchases/"):-len("/stock")]
            purchases = _get("purchases")
            idx = next((i for i, p in enumerate(purchases) if p.get("id") == pid), None)
            if idx is None:
                send_json(handler, 404, {"error": f"未找到 {pid}"})
                return
            p = purchases[idx]
            if p["status"] == "stocked":
                send_json(handler, 400, {"error": "已经入库过了"})
                return

            items = _get("items")
            existing = next((it for it in items if it["name"] == p["name"]), None)
            if existing:
                existing["qty"] = float(existing["qty"]) + float(p["qty"])
                if p.get("unit"):
                    existing["unit"] = p["unit"]
                log(f"  OK 累加 {p['name']}: {p['qty']} -> 现有 {existing['qty']} {existing['unit']}")
            else:
                items.append({
                    "id": f"item-{int(datetime.now().timestamp() * 1000)}",
                    "name": p["name"],
                    "qty": float(p["qty"]),
                    "unit": p.get("unit", ""),
                    "note": f"从申购 {pid} 自动入库",
                    "created_at": datetime.now().isoformat(),
                })
                log(f"  OK 新增 {p['name']}: {p['qty']} {p.get('unit', '')}")

            purchases[idx]["status"] = "stocked"
            _save("items", items)
            _save("purchases", purchases)
            send_json(handler, 200, {"ok": True, "purchase": purchases[idx]})

        else:
            send_json(handler, 404, {"error": "未知 API 路径"})

    # ---------- DELETE ----------
    if method == "DELETE":
        path_clean = path.split("?", 1)[0]

        if path_clean.startswith("/api/readings/"):
            date = path_clean[len("/api/readings/"):]
            readings = _get("readings")
            new = [r for r in readings if r.get("date") != date]
            if len(new) == len(readings):
                send_json(handler, 404, {"error": f"未找到 {date}"})
                return
            _save("readings", new)
            log(f"  -- 删除抄表 {date}")
            send_json(handler, 200, {"ok": True})

        elif path_clean.startswith("/api/charges/"):
            cid = path_clean[len("/api/charges/"):]
            charges = _get("charges")
            new = [c for c in charges if c.get("id") != cid]
            if len(new) == len(charges):
                send_json(handler, 404, {"error": f"未找到 {cid}"})
                return
            _save("charges", new)
            log(f"  -- 删除充值 {cid}")
            send_json(handler, 200, {"ok": True})

        elif path_clean.startswith("/api/items/"):
            iid = path_clean[len("/api/items/"):]
            items = _get("items")
            new = [it for it in items if it.get("id") != iid]
            if len(new) == len(items):
                send_json(handler, 404, {"error": f"未找到 {iid}"})
                return
            _save("items", new)
            log(f"  -- 删除物品 {iid}")
            send_json(handler, 200, {"ok": True})

        elif path_clean.startswith("/api/purchases/"):
            pid = path_clean[len("/api/purchases/"):]
            purchases = _get("purchases")
            new = [p for p in purchases if p.get("id") != pid]
            if len(new) == len(purchases):
                send_json(handler, 404, {"error": f"未找到 {pid}"})
                return
            _save("purchases", new)
            log(f"  -- 删除申购 {pid}")
            send_json(handler, 200, {"ok": True})

        else:
            send_json(handler, 404, {"error": "未知 API 路径"})


# ---------- handler 封装 ----------

class Handler(BaseHTTPRequestHandler):
    """包装原始 BaseHTTPRequestHandler，统一路由和错误处理。"""

    def log_message(self, fmt: str, *args):
        log(f"{self.address_string()} - {fmt % args}")

    def do_OPTIONS(self):
        _handle_api("OPTIONS", self, self.path)

    def do_GET(self):
        _dispatch("GET", self, self.path)

    def do_POST(self):
        _handle_api("POST", self, self.path)

    def do_PUT(self):
        _handle_api("PUT", self, self.path)

    def do_DELETE(self):
        _handle_api("DELETE", self, self.path)

"""
数据导入 handler — CSV 导入
==============================
支持 readings / charges / items / purchases 的 CSV 导入。
纯 Python 标准库实现（csv 模块），无需外部依赖。
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from utils import send_json, send_csv, opt_float, read_body
from storage import log, get_lock, load_json, save_json
from handlers._base import get_data_paths


# 支持的模型及其字段校验规则
VALID_MODELS = {"readings", "charges", "items", "purchases"}

# 模型默认字段
MODEL_FIELDS: Dict[str, List[str]] = {
    "readings": ["date", "hall", "fire", "private_room", "ac", "main_meter", "sub_meter", "water", "note"],
    "charges": ["id", "date", "hall", "fire", "private_room", "ac", "note"],
    "items": ["id", "name", "qty", "unit", "note", "created_at"],
    "purchases": ["id", "date", "name", "qty", "unit", "est_price", "supplier", "status", "note"],
}

# 模型示例数据（用于生成 CSV 模板，让用户直观看到正确格式）
MODEL_EXAMPLES: Dict[str, List[str]] = {
    "readings":   ["2026-01-15", "1234.5", "12.3", "456.7", "234.5", "", "", "", "示例：大厅/包间/空调读数"],
    "charges":    ["", "2026-01-15", "100", "20", "50", "30", "示例：充值记录"],
    "items":      ["", "扫把", "5", "把", "示例物品备注", ""],
    "purchases":  ["", "2026-01-15", "扫把", "5", "把", "10.5", "示例供应商", "ordered", "示例备注"],
}


def _parse_number(value: str) -> Optional[float]:
    """解析数字字符串，空值返回 None。
    支持中文逗号/小数点互换（Excel 导出的常见情况）。"""
    if not value or value.strip() == "":
        return None
    value = value.strip()
    # 处理中文逗号
    if "，" in value:
        value = value.replace("，", ",")
    # 处理 ASCII 逗号: "1,5" (小数点) vs "1,000" (千分位)
    if "," in value:
        parts = value.split(",")
        if len(parts) == 2:
            # 第二部分长度 ≤ 2 → 小数点; 长度 3 → 千分位
            if len(parts[1]) <= 2:
                value = value.replace(",", ".")
            # else: 1,000 → 1000 (去掉千分位逗号)
            else:
                value = value.replace(",", "")
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _parse_int(value: str) -> Optional[int]:
    """解析整数字符串，空值返回 None。"""
    if not value or value.strip() == "":
        return None
    value = value.strip().replace("，", ",")
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def _validate_date(date_str: str) -> bool:
    """验证日期格式 YYYY-MM-DD。"""
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", date_str.strip()))


def _import_readings(rows: List[Dict[str, str]]) -> tuple:
    """导入 readings 数据。返回 (成功数, 错误数, 错误列表)。"""
    errors = []
    count = 0
    readings = load_json(get_data_paths()["readings"], [])
    lock = get_lock("readings")

    with lock:
        existing_dates = {r.get("date") for r in readings}
        for i, row in enumerate(rows):
            date = row.get("date", "").strip()
            if not date or not _validate_date(date):
                errors.append(f"行 {i+1}: 日期格式无效 '{date}', 需要 YYYY-MM-DD")
                continue

            # 构建新行
            new_row: Dict[str, Any] = {"date": date}
            for field in ("hall", "fire", "private_room", "ac", "main_meter", "sub_meter", "water"):
                new_row[field] = _parse_number(row.get(field, ""))

            new_row["note"] = row.get("note", "").strip() or None
            # 至少填一个表
            vals = [v for v in new_row.values() if v is not None and v != date]
            if not vals:
                errors.append(f"行 {i+1}: 至少需要填写一个表的读数")
                continue

            # 检查日期是否已存在（更新模式）
            idx = next((j for j, r in enumerate(readings) if r.get("date") == date), None)
            if idx is not None:
                # 更新：合并旧值（类似 POST /api/readings 的覆盖逻辑）
                old = readings[idx]
                for k in ("hall", "fire", "private_room", "ac", "main_meter", "sub_meter", "water"):
                    if new_row[k] is None:
                        new_row[k] = old.get(k)
                readings[idx] = new_row
            else:
                readings.append(new_row)
            count += 1

        save_json(get_data_paths()["readings"], readings)
    return count, len(errors), errors


def _import_charges(rows: List[Dict[str, str]]) -> tuple:
    """导入 charges 数据。返回 (成功数, 错误数, 错误列表)。"""
    errors = []
    count = 0
    charges = load_json(get_data_paths()["charges"], [])
    lock = get_lock("charges")

    with lock:
        for i, row in enumerate(rows):
            date = row.get("date", "").strip()
            if not date or not _validate_date(date):
                errors.append(f"行 {i+1}: 日期格式无效 '{date}', 需要 YYYY-MM-DD")
                continue

            new_charge: Dict[str, Any] = {"date": date}
            for field in ("hall", "fire", "private_room", "ac"):
                new_charge[field] = _parse_number(row.get(field, ""))

            new_charge["note"] = row.get("note", "").strip() or None
            # 至少一个表有充值
            vals = [v for v in new_charge.values() if v is not None and v != date]
            if not any(isinstance(v, (int, float)) for v in vals):
                errors.append(f"行 {i+1}: 至少需要填写一个表的充值")
                continue

            # 生成 id（基于日期+表）
            new_charge["id"] = f"charge-{date}-{datetime.now().strftime('%s')}-{count}"
            charges.append(new_charge)
            count += 1

        save_json(get_data_paths()["charges"], charges)
    return count, len(errors), errors


def _import_items(rows: List[Dict[str, str]]) -> tuple:
    """导入 items 数据。返回 (成功数, 错误数, 错误列表)。"""
    errors = []
    count = 0
    items = load_json(get_data_paths()["items"], [])
    lock = get_lock("items")

    with lock:
        for i, row in enumerate(rows):
            name = row.get("name", "").strip()
            if not name:
                errors.append(f"行 {i+1}: 名称不能为空")
                continue

            qty = _parse_int(row.get("qty", "0"))
            if qty is None or qty < 0:
                errors.append(f"行 {i+1}: 数量必须为非负整数，得到 '{row.get('qty', '')}'")
                continue

            item: Dict[str, Any] = {
                "id": row.get("id", f"item-{datetime.now().strftime('%s')}-{i}"),
                "name": name,
                "qty": qty,
                "unit": row.get("unit", "").strip() or "",
                "note": row.get("note", "").strip() or None,
            }
            if "created_at" in row and row["created_at"].strip():
                item["created_at"] = row["created_at"].strip()
            else:
                item["created_at"] = datetime.now().isoformat()

            # 按 name 去重更新
            idx = next((j for j, r in enumerate(items) if r.get("name") == name), None)
            if idx is not None:
                items[idx].update(item)
            else:
                items.append(item)
            count += 1

        save_json(get_data_paths()["items"], items)
    return count, len(errors), errors


def _import_purchases(rows: List[Dict[str, str]]) -> tuple:
    """导入 purchases 数据。返回 (成功数, 错误数, 错误列表)。"""
    errors = []
    count = 0
    purchases = load_json(get_data_paths()["purchases"], [])
    lock = get_lock("purchases")

    with lock:
        for i, row in enumerate(rows):
            date = row.get("date", "").strip()
            name = row.get("name", "").strip()
            if not date or not _validate_date(date):
                errors.append(f"行 {i+1}: 日期格式无效 '{date}'")
                continue
            if not name:
                errors.append(f"行 {i+1}: 名称不能为空")
                continue

            qty = _parse_int(row.get("qty", "0"))
            if qty is None or qty < 0:
                errors.append(f"行 {i+1}: 数量必须为非负整数")
                continue

            est_price = _parse_number(row.get("est_price", ""))
            if est_price is not None and est_price < 0:
                errors.append(f"行 {i+1}: 预估价格必须为非负数")
                continue

            purchase: Dict[str, Any] = {
                "id": row.get("id", f"purchase-{datetime.now().strftime('%s')}-{i}"),
                "date": date,
                "name": name,
                "qty": qty,
                "unit": row.get("unit", "").strip() or "",
                "est_price": est_price,
                "supplier": row.get("supplier", "").strip() or None,
                "status": row.get("status", "ordered").strip() or "ordered",
                "note": row.get("note", "").strip() or None,
            }
            purchases.append(purchase)
            count += 1

        save_json(get_data_paths()["purchases"], purchases)
    return count, len(errors), errors


IMPORT_HANDLERS = {
    "readings": _import_readings,
    "charges": _import_charges,
    "items": _import_items,
    "purchases": _import_purchases,
}


def handle_post_import(handler):
    """POST /api/import {model, file} → CSV 导入

    支持模型: readings, charges, items, purchases

    请求体:
      - model (string): 要导入的模型
      - file (multipart/form-data): CSV 文件

    响应: { ok, count, errors: [{ line, message }] }
    """
    # 检查 Content-Type
    content_type = handler.headers.get("Content-Type", "")
    if "multipart/form-data" not in content_type:
        send_json(handler, 400, {"error": "Content-Type 必须是 multipart/form-data"})
        return

    # 解析 multipart 表单
    body = _parse_multipart(handler, content_type)
    if not body:
        send_json(handler, 400, {"error": "请求体格式错误"})
        return

    model = (body.get("model") or "").strip().lower()
    if model not in VALID_MODELS:
        send_json(handler, 400, {"error": f"不支持的模型: {model}。支持: {', '.join(sorted(VALID_MODELS))}"})
        return

    csv_file = body.get("file")
    if not csv_file or not csv_file.get("data"):
        send_json(handler, 400, {"error": "必须提供 CSV 文件"})
        return

    # 解析 CSV
    csv_text = csv_file["data"].decode("utf-8-sig")  # 处理 BOM
    try:
        reader = csv.DictReader(io.StringIO(csv_text))
        rows = list(reader)
    except Exception as e:
        send_json(handler, 400, {"error": f"CSV 解析失败: {e}"})
        return

    if not rows:
        send_json(handler, 400, {"error": "CSV 文件为空或没有数据行"})
        return

    # 执行导入
    handler_fn = IMPORT_HANDLERS[model]
    imported, failed, error_list = handler_fn(rows)

    log(f"  [IMPORT] {model}: 成功 {imported} 条, 失败 {failed} 条")

    # 失效报表缓存（readings/charges 导入后）
    if model in ("readings", "charges"):
        try:
            from report import invalidate_report_cache
            invalidate_report_cache()
        except Exception:
            pass

    result = {
        "ok": True,
        "model": model,
        "count": imported,
        "failed": failed,
        "errors": error_list,
    }
    send_json(handler, 200 if failed < len(rows) else 400, result)


def handle_get_import_template(handler, path_clean: str):
    """GET /api/import/template?model=<name> → 下载 CSV 模板

    根据指定模型返回表头 + 一行示例数据，帮助用户了解正确的导入格式。
    支持模型: readings, charges, items, purchases
    """
    from urllib.parse import urlparse, parse_qs
    qs = parse_qs(urlparse(path_clean).query)
    model = (qs.get("model", [""])[0] or "").strip().lower()

    if model not in VALID_MODELS:
        send_json(handler, 400, {
            "error": f"不支持的模型: {model}。支持: {', '.join(sorted(VALID_MODELS))}"
        })
        return

    headers = MODEL_FIELDS[model]
    rows = [MODEL_EXAMPLES[model]]
    filename = f"import-template-{model}.csv"
    send_csv(handler, filename, headers, rows)


def _parse_multipart(handler, content_type: str) -> Optional[Dict]:
    """简单解析 multipart/form-data 请求。"""
    # 提取 boundary
    boundary_match = re.search(r'boundary=(.+)', content_type)
    if not boundary_match:
        return None
    boundary = boundary_match.group(1).strip()

    # 读取请求体
    content_length = int(handler.headers.get("Content-Length", 0))
    if content_length == 0:
        return None
    body_data = handler.rfile.read(content_length)

    # 拆分 parts
    # 格式: --boundary\r\nContent-Disposition: ...
    #       \r\n\r\n<内容>\r\n--boundary--
    separator = f"--{boundary}".encode()
    parts = body_data.split(separator)

    result = {}
    for part in parts:
        if not part.strip() or part.strip() == b"--" or part.strip() == b"--\r\n":
            continue

        # 分离 headers 和 body
        crlf = b"\r\n\r\n"
        if crlf not in part:
            continue
        headers_bytes, file_data = part.split(crlf, 1)
        # 去掉尾部 \r\n
        if file_data.endswith(b"\r\n"):
            file_data = file_data[:-2]

        headers_text = headers_bytes.decode("utf-8", errors="replace")
        # 解析 Content-Disposition
        cd_match = re.search(r'Content-Disposition:\s*form-data;\s*name="([^"]+)"(?:;\s*filename="([^"]+)")?', headers_text)
        if not cd_match:
            continue

        name = cd_match.group(1)
        filename = cd_match.group(2)

        if filename:
            # 文件字段
            result[name] = {
                "filename": filename,
                "data": file_data,
            }
        else:
            # 文本字段
            result[name] = file_data.decode("utf-8", errors="replace").strip()

    return result if result else None

"""值班录入相关 API handler。"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from utils import send_json, read_body
from storage import log, load_json, save_json, get_lock, get_data_dir
from handlers._base import JsonModelHandler

_now = datetime.now


class _DutyHandler(JsonModelHandler):
    model = "duty"

    def _create_row(self, body: dict):
        duty_type = body.get("duty_type", "").strip()
        shift = body.get("shift", "").strip()
        status = body.get("status", "").strip()
        fault_area = body.get("fault_area", "").strip()
        note = body.get("note", "").strip()

        if not duty_type:
            return None, "类型不能为空"
        if not shift:
            return None, "班次不能为空"
        if not status:
            return None, "处理状态不能为空"

        # 自动添加时间（如果未提供）
        record_time = body.get("record_time", "").strip()
        if not record_time:
            record_time = _now().strftime("%Y-%m-%d %H:%M:%S")

        row = {
            "id": _now().strftime("%Y%m%d%H%M%S"),
            "duty_type": duty_type,
            "record_time": record_time,
            "shift": shift,
            "status": status,
            "fault_area": fault_area,
            "note": note,
        }
        img_fns = body.get("image_filenames")
        if img_fns:
            row["images"] = img_fns
        return row, None

    def _update_fields(self, existing: dict, body: dict) -> None:
        for key in ["duty_type", "shift", "status", "fault_area", "note"]:
            val = body.get(key)
            if val is not None:
                existing[key] = val
        # 处理时间（可选）
        if body.get("handle_time"):
            existing["handle_time"] = body["handle_time"]
        # 处理班次（可选）
        if body.get("handle_shift"):
            existing["handle_shift"] = body["handle_shift"]
        # 处理方案（可选）
        if body.get("handle_method"):
            existing["handle_method"] = body["handle_method"]
        # 记录时间更新（可选）
        if body.get("record_time"):
            existing["record_time"] = body["record_time"]


_h = _DutyHandler()


# ==================== 路由函数 ====================

def handle_get_duty(handler):
    """GET /api/duty"""
    _h.handle_get(handler)


def handle_post_duty(handler):
    """POST /api/duty"""
    _h.handle_post(handler)


def handle_put_duty(handler, path_clean: str):
    """PUT /api/duty/{id}"""
    _h.handle_put(handler, path_clean)


def handle_delete_duty(handler, path_clean: str):
    """DELETE /api/duty/{id}

    如果删除的是"处理"类型记录，自动将原始报修记录恢复为"未处理"状态。
    """
    from utils import send_json, read_body
    try:
        rid = _h._extract_id(path_clean)
        data = _h._load()
        target = None
        target_idx = None
        for i, r in enumerate(data):
            if str(r.get("id")) == rid:
                target = r
                target_idx = i
                break
        if target is None:
            send_json(handler, 404, {"error": f"未找到 {rid}"})
            return

        # 如果删除的是"处理"记录，恢复原始报修记录的状态
        if target.get("duty_type") == "处理" and target.get("original_id"):
            original_id = target["original_id"]
            for r in data:
                if str(r.get("id")) == original_id:
                    r["status"] = "未处理"
                    # 清除处理关联字段
                    r.pop("handle_record_id", None)
                    log(f"  OK 删除处理记录 {rid} → 恢复原始记录 {original_id} 为未处理")
                    break

        # 删除记录
        new_list = [r for r in data if str(r.get("id")) != rid]
        _h._save(new_list)
        log(f"  -- 删除工作记录 {rid}")
        send_json(handler, 200, {"ok": True})
    except Exception as e:
        log(f"  [ERROR] handle_delete_duty: {e}")
        import traceback
        log(traceback.format_exc())
        send_json(handler, 500, {"error": f"服务器内部错误: {e}"})


def _get_images_dir():
    """获取工作记录图片目录。"""
    data_dir = get_data_dir()
    settings = _get_settings()
    images_dir = Path(settings.get("image_dir", str(Path(data_dir) / "images")))
    images_dir.mkdir(parents=True, exist_ok=True)
    return images_dir


def _get_settings() -> dict:
    """从 settings.json 读取（含默认值）。"""
    import json
    try:
        data_dir = get_data_dir()
        settings_path = Path(data_dir) / "settings.json"
        if settings_path.exists():
            return json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_setting(key: str, value) -> None:
    """更新 settings.json 中的单个字段。"""
    import json
    data_dir = get_data_dir()
    settings_path = Path(data_dir) / "settings.json"
    settings = {}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception:
            settings = {}
    settings[key] = value
    try:
        tmp = settings_path.with_suffix(settings_path.suffix + ".tmp")
        tmp.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(settings_path)
        log(f"  [settings] {key} = {value}")
    except Exception as e:
        log(f"  [WARN] save_setting {key} failed: {e}")


def handle_get_images_config(handler):
    """GET /api/admin/images — 获取图片目录配置。

    Docker 环境下由环境变量 METER_IMAGE_DIR 控制，返回 customizable=false。
    """
    data_dir = get_data_dir()
    env_image_dir = os.environ.get("METER_IMAGE_DIR", "").strip()

    if os.environ.get("METER_DOCKER") and env_image_dir:
        # Docker 环境: 使用环境变量指定的图片目录
        image_dir = Path(env_image_dir)
        image_dir.mkdir(parents=True, exist_ok=True)
        image_files = list(image_dir.glob("*"))
        total_files = len(image_files)
        total_size = sum(f.stat().st_size for f in image_files if f.is_file())
        send_json(handler, 200, {
            "ok": True,
            "image_dir": str(image_dir),
            "default_image_dir": str(image_dir),
            "image_count": total_files,
            "total_size": total_size,
            "customizable": False,
        })
        return

    # macOS 环境: 从 settings.json 读取
    settings = _get_settings()
    image_dir = Path(settings.get("image_dir", str(Path(data_dir) / "images")))
    image_dir.mkdir(parents=True, exist_ok=True)
    # 统计图片数量和总大小
    image_files = list(image_dir.glob("*"))
    total_files = len(image_files)
    total_size = sum(f.stat().st_size for f in image_files if f.is_file())
    send_json(handler, 200, {
        "ok": True,
        "image_dir": str(image_dir),
        "default_image_dir": str(Path(data_dir) / "images"),
        "image_count": total_files,
        "total_size": total_size,
        "customizable": True,
    })


def handle_put_images_config(handler):
    """PUT /api/admin/images — 设置图片目录。

    Docker 环境下由环境变量 METER_IMAGE_DIR 控制，不可通过 API 修改。
    """
    # Docker 环境不允许修改
    if os.environ.get("METER_DOCKER"):
        send_json(handler, 400, {"error": "Docker 环境下图片目录由环境变量 METER_IMAGE_DIR 控制"})
        return
    body = read_body(handler)
    image_dir = body.get("image_dir", "").strip()
    if not image_dir:
        send_json(handler, 400, {"error": "目录不能为空"})
        return
    # 验证目录合法性
    data_dir = get_data_dir()
    data_dir_path = Path(data_dir).resolve()
    candidate = Path(image_dir).resolve()
    # 确保在 data_dir 内
    try:
        candidate.relative_to(data_dir_path)
    except ValueError:
        send_json(handler, 400, {"error": "图片目录必须在数据目录内"})
        return
    candidate.mkdir(parents=True, exist_ok=True)
    _save_setting("image_dir", str(candidate))
    send_json(handler, 200, {"ok": True, "image_dir": str(candidate)})


def _allowed_ext(filename: str) -> bool:
    """只允许图片后缀。"""
    return Path(filename).suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".gif")


def _parse_multipart(handler, content_type: str) -> dict:
    """简单解析 multipart/form-data。"""
    import re
    boundary_match = re.search(r'boundary=(.+)', content_type)
    if not boundary_match:
        return {}
    boundary = boundary_match.group(1).strip()
    content_length = int(handler.headers.get("Content-Length", 0))
    if content_length == 0:
        return {}
    body_data = handler.rfile.read(content_length)
    separator = f"--{boundary}".encode()
    parts = body_data.split(separator)
    result = {}
    for part in parts:
        if not part.strip() or part.strip() == b"--" or part.strip() == b"--\r\n":
            continue
        crlf = b"\r\n\r\n"
        if crlf not in part:
            continue
        headers_bytes, file_data = part.split(crlf, 1)
        if file_data.endswith(b"\r\n"):
            file_data = file_data[:-2]
        headers_text = headers_bytes.decode("utf-8", errors="replace")
        cd_match = re.search(r'Content-Disposition:\s*form-data;\s*name="([^"]+)"(?:;\s*filename="([^"]+)")?', headers_text)
        if not cd_match:
            continue
        name = cd_match.group(1)
        filename = cd_match.group(2)
        if filename:
            result[name] = {"filename": filename, "data": file_data}
        else:
            result[name] = file_data.decode("utf-8", errors="replace").strip()
    return result


def handle_post_duty_image(handler):
    """POST /api/duty/image — 上传图片，返回文件名。"""
    content_type = handler.headers.get("Content-Type", "") or ""
    if "multipart/form-data" not in content_type:
        send_json(handler, 400, {"error": "请上传 multipart/form-data"})
        return
    body = _parse_multipart(handler, content_type)
    image = body.get("image")
    if not image or not image.get("data"):
        send_json(handler, 400, {"error": "未收到图片"})
        return
    filename = image["filename"]
    if not _allowed_ext(filename):
        send_json(handler, 400, {"error": "仅支持 jpg/png/webp/gif"})
        return
    # 生成唯一文件名
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    ext = Path(filename).suffix.lower()
    stored_name = f"{ts}{ext}"
    images_dir = _get_images_dir()
    dest = images_dir / stored_name
    dest.write_bytes(image["data"])
    log(f"  ++ 上传工作记录图片 {stored_name} ({len(image['data'])} bytes)")
    send_json(handler, 200, {"ok": True, "filename": stored_name})


def handle_get_duty_image(handler, path_clean: str):
    """GET /api/duty/image/{filename} — 返回图片。"""
    images_dir = _get_images_dir()
    filepath = (images_dir / path_clean).resolve()
    # 防止目录穿越
    if not str(filepath).startswith(str(images_dir.resolve())):
        send_json(handler, 403, {"error": "Forbidden"})
        return
    if not filepath.exists():
        send_json(handler, 404, {"error": "Not found"})
        return
    content_type_map = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif",
    }
    ext = filepath.suffix.lower()
    ct = content_type_map.get(ext, "application/octet-stream")
    data = filepath.read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", ct)
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "max-age=86400")
    handler.end_headers()
    handler.wfile.write(data)


def handle_post_duty_handle(handler, path_clean: str):
    """POST /api/duty/{id}/handle — 处理一条未处理的工作记录。

    两步操作：
    1. 将原始报修记录标记为"已处理"，记录 handle_record_id 关联
    2. 创建一条新的处理记录（duty_type="处理"），携带处理时间、班次、方案、备注
    """
    from utils import send_json, read_body
    try:
        # 提取 id: /api/duty/xxx/handle → xxx
        parts = path_clean.split("/")
        # 期望: ["", "api", "duty", "<id>", "handle"]
        if len(parts) < 5 or parts[-1] != "handle":
            send_json(handler, 400, {"error": "路径不正确"})
            return
        rid = parts[3]
        body = read_body(handler)

        handle_time = body.get("handle_time", "").strip()
        handle_shift = body.get("handle_shift", "").strip()
        handle_method = body.get("handle_method", "").strip()
        note = body.get("note", "").strip()

        if not handle_shift or not handle_method:
            send_json(handler, 400, {"error": "处理班次和处理方案不能为空"})
            return

        if not handle_time:
            handle_time = _now().strftime("%Y-%m-%d %H:%M:%S")

        data = _h._load()
        existing, idx = _h._find_by_id(data, rid)
        if existing is None:
            send_json(handler, 404, {"error": f"未找到 {rid}"})
            return

        # 1) 标记原始记录为已处理
        existing["status"] = "已处理"
        handle_id = _h._gen_id("HL")
        existing["handle_record_id"] = handle_id
        data[idx] = existing

        # 2) 创建处理记录
        handle_row = {
            "id": handle_id,
            "duty_type": "处理",
            "record_time": handle_time,
            "shift": handle_shift,
            "status": "已处理",
            "fault_area": existing.get("fault_area", ""),
            "note": handle_method,
            "original_id": rid,
        }
        if note:
            handle_row["note"] = f"{handle_method}\n备注: {note}"
        # 图片
        handle_imgs = body.get("image_filenames")
        if handle_imgs:
            handle_row["images"] = handle_imgs
        data.append(handle_row)

        _h._save(data)
        log(f"  OK 处理工作记录 {rid} → 新记录 {handle_id}")
        send_json(handler, 200, {"ok": True, "handle_id": handle_id})
    except Exception as e:
        log(f"  [ERROR] handle_post_duty_handle: {e}")
        import traceback
        log(traceback.format_exc())
        send_json(handler, 500, {"error": f"服务器内部错误: {e}"})

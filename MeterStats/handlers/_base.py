"""handler 基类 — 消除各 model handler 重复的 _get / _save / _get_data_paths。

用法:
    from handlers._base import JsonModelHandler

    class ItemsHandler(JsonModelHandler):
        model = "items"

    handle_get_items = ItemsHandler.handle_get  # /api/items 列表
    handle_post_items = ItemsHandler.handle_post

如需自定义校验/转换，复写 _validate_post / _to_row 即可。

额外工具:
    get_data_paths()  — 全局获取 DATA_PATHS
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from storage import load_json, save_json, get_lock, log
from utils import send_json, read_body


def get_data_paths() -> dict:
    """全局获取 DATA_PATHS 映射。"""
    import app_handler as _h
    return _h.DATA_PATHS


class JsonModelHandler:
    """JSON 模型 CRUD 基类，子类只需声明 model 名称。"""

    model: str = ""  # 子类必须覆盖, e.g. "items" / "readings" / "duty"

    # ------- 数据路径 -------
    @staticmethod
    def _get_data_paths() -> dict:
        """从 app_handler 模块读取 DATA_PATHS。"""
        import app_handler as _h
        return _h.DATA_PATHS

    def _path(self) -> Any:
        return self._get_data_paths().get(self.model)

    def _load(self) -> list:
        return load_json(self._path(), [])

    def _save(self, data: list) -> None:
        lock = get_lock(self.model)
        with lock:
            save_json(self._path(), data)

    # ------- 通用 CRUD -------
    def handle_get(self, handler, path_clean: str = "") -> None:
        send_json(handler, 200, self._load())

    def handle_post(self, handler, path_clean: str = "") -> None:
        body = read_body(handler)
        row, err = self._create_row(body)
        if err:
            send_json(handler, 400, {"error": err})
            return
        data = self._load()
        data.append(row)
        self._save(data)
        log(f"  ++ 新增{self.model} {row.get('id', '')}")
        send_json(handler, 200, {"ok": True, "row": row})

    def handle_put(self, handler, path_clean: str = "") -> None:
        """PUT /api/<model> 或 /api/<model>/{id}。

        - 无 id 段 → 走 create（兼容旧 PUT-as-add 语义）
        - 有 id 段 → 走 update
        """
        rid = self._extract_id(path_clean)
        body = read_body(handler)
        data = self._load()

        if not rid:
            row, err = self._create_row(body)
            if err:
                send_json(handler, 400, {"error": err})
                return
            data.append(row)
            self._save(data)
            log(f"  ++ 新增{self.model} {row.get('id', '')}")
            send_json(handler, 200, {"ok": True, "row": row})
            return

        existing, idx = self._find_by_id(data, rid)
        if existing is None:
            send_json(handler, 404, {"error": f"未找到 {rid}"})
            return

        # 调用子类的字段过滤（如果提供）
        updater = getattr(self, "_update_fields", None)
        if updater:
            updater(existing, body)
        else:
            # 默认:把 body 中所有 key 覆盖到 existing（除 id 外）
            for k, v in body.items():
                if k != "id":
                    existing[k] = v

        data[idx] = existing
        self._save(data)
        log(f"  OK 更新{self.model} {rid}")
        send_json(handler, 200, {"ok": True, "row": existing})

    def handle_delete(self, handler, path_clean: str = "") -> None:
        rid = self._extract_id(path_clean)
        data = self._load()
        new_list = [r for r in data if str(r.get("id")) != rid]
        if len(new_list) == len(data):
            send_json(handler, 404, {"error": f"未找到 {rid}"})
            return
        self._save(new_list)
        log(f"  -- 删除{self.model} {rid}")
        send_json(handler, 200, {"ok": True})

    # ------- 子类可复写 -------
    def _create_row(self, body: dict) -> tuple[Optional[dict], Optional[str]]:
        """子类复写以做校验 + 构造 row。返回 (row, None) 或 (None, err_msg)。"""
        return None, "子类必须实现 _create_row"

    # ------- 工具 -------
    @staticmethod
    def _extract_id(path_clean: str) -> str:
        """/api/items/abc123 → abc123；无 id 段返回空串。"""
        if not path_clean:
            return ""
        parts = path_clean.split("/")
        # 期望: ["", "api", "<model>", "<id>?", ...]
        return parts[3] if len(parts) >= 4 else ""

    @staticmethod
    def _find_by_id(data: list, rid: str) -> tuple[Optional[dict], Optional[int]]:
        for i, r in enumerate(data):
            if str(r.get("id")) == rid:
                return r, i
        return None, None

    @staticmethod
    def _gen_id(prefix: str = "") -> str:
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        return f"{prefix}-{ts}" if prefix else ts

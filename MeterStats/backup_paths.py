"""备份包里「哪些相对路径算数」—— **备份侧与恢复侧共用的唯一定义**。

为什么单独一个模块
------------------
备份侧(`storage.backup_data` 与 `modules.backup.handler.handle_post_backup`
的 rglob 复制)和恢复侧(`modules.backup.handler._safe_rel_target` 的白名单)
以前各写一份规则,两份漂移出来的后果很难看:

- 备份收**任意深度**、恢复只认 1 段(顶层文件)和 3 段(`stores/<id>/<file>`)
  → `stores/x/backup/20260101/readings.json` 之类会进包、恢复时被静默丢弃;
- 值班照片(`stores/<id>/images/*.jpg`、单店布局的 `images/*.jpg`)
  **从来就没进过备份** —— 换机器 / 重建容器即永久丢失。

现在两侧都调 `classify_rel()`:备份只收「恢复得回来」的东西,
恢复也只认「备份会收」的东西 —— 这就是 round-trip 不变式:
**备份包里的每个文件都能原样恢复回去,恢复得回去的东西都在包里。**

允许的形态(相对数据根)
----------------------
| 形态                                | 类别    |
|-------------------------------------|---------|
| `readings.json` / `settings.json` … | data    |
| `images/<图片>`                     | image   |
| `stores/<id>/readings.json` …        | data    |
| `stores/<id>/store.json`            | data    |
| `stores/<id>/images/<图片>`         | image   |

其它一律拒绝(`None`),特别是 `..`、绝对路径、反斜杠。

注意:`*.tmp` **不算备份内容**。它是 `save_json` 原子写入的中间产物,
崩溃后残留的 `.tmp` 是垃圾,不是数据;以前那个后缀白名单顺带放行了 `.tmp`,
结果是半成品也被打进备份包。
"""
from __future__ import annotations

from typing import Optional

# 图片后缀 —— 与 app_handler._STATIC_ALLOWED_SUFFIXES 里的图片集合保持一致
IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif"})

# 顶层可备份文件 = 6 个数据模型 + settings.json
TOP_LEVEL_DATA = frozenset({
    "readings.json",
    "readings_water.json",
    "charges.json",
    "items.json",
    "purchases.json",
    "duty.json",
    "settings.json",
})

# 门店子目录里可备份的数据文件 = 同一批数据模型 + store.json(门店配置)
STORE_DATA = frozenset({
    "readings.json",
    "readings_water.json",
    "charges.json",
    "items.json",
    "purchases.json",
    "duty.json",
    "store.json",
})

# 目录名常量:备份/恢复/列举三处都引用,避免各自硬编码字符串
STORES_DIR = "stores"
IMAGES_DIR = "images"

KIND_DATA = "data"
KIND_IMAGE = "image"


def _is_image_name(name: str) -> bool:
    dot = name.rfind(".")
    if dot <= 0:
        return False
    return name[dot:].lower() in IMAGE_SUFFIXES


def classify_rel(rel: str) -> Optional[str]:
    """判断备份相对路径是否合法,并返回类别(`"data"` / `"image"`)。

    非法路径一律返回 `None`。判定纯字符串(不碰磁盘),可以被备份、恢复、
    数据文件列举三条路径共用。
    """
    if not isinstance(rel, str) or not rel:
        return None
    if "\\" in rel or rel.startswith("/"):
        return None
    parts = rel.split("/")
    if any(p in ("", ".", "..") for p in parts):
        return None

    if len(parts) == 1:
        return KIND_DATA if parts[0] in TOP_LEVEL_DATA else None

    if len(parts) == 2:
        # 单店布局 / 遗留布局的图片目录:<数据根>/images/*.jpg
        if parts[0] == IMAGES_DIR and _is_image_name(parts[1]):
            return KIND_IMAGE
        return None

    if len(parts) == 3:
        if parts[0] != STORES_DIR:
            return None
        if not _is_valid_store_id(parts[1]):
            return None
        return KIND_DATA if parts[2] in STORE_DATA else None

    if len(parts) == 4:
        # 多门店布局的图片:stores/<id>/images/*.jpg
        if parts[0] != STORES_DIR or parts[2] != IMAGES_DIR:
            return None
        if not _is_valid_store_id(parts[1]):
            return None
        return KIND_IMAGE if _is_image_name(parts[3]) else None

    # 更深的一律不收 —— 恢复侧认不回来,收进去只会造成「包里有、恢复丢」
    return None


def _is_valid_store_id(store_id: str) -> bool:
    """门店 ID 合法性(延迟导入:registry 会反向依赖 storage,顶层 import 会成环)。"""
    from modules.stores.registry import is_valid_store_id
    return is_valid_store_id(store_id)


def iter_backup_files(base_dir: "object", include_images: bool = True):
    """按 `classify_rel` 的规则遍历数据根下的可备份文件。

    产出 `(相对路径(posix), 绝对路径)`。只遍历 `stores/` 与 `images/` 两棵子树
    —— 顶层数据文件由调用方单独处理(它们有各自的脱敏/桥接逻辑)。
    """
    from pathlib import Path

    base = Path(base_dir)  # type: ignore[arg-type]
    subtrees = [STORES_DIR, IMAGES_DIR] if include_images else [STORES_DIR]
    for sub in subtrees:
        root = base / sub
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(base).as_posix()
            kind = classify_rel(rel)
            if kind is None:
                continue
            if kind == KIND_IMAGE and not include_images:
                continue
            yield rel, path

"""数据迁移 —— 顶层数据文件 → stores/<store_id>/。

做一次,幂等。触发时机:server 启动时(server.py 调用)。

原则:
1. **先备份,再动数据。** 迁移前必须打一份完整备份,备份失败就不迁。
2. **顶层旧文件不删。** 搬完保留在原地,作为可回滚副本。
3. **注册表先落盘、且要回读校验。** 注册表没真正落盘就不建 stores/ 目录 ——
   否则 multi_store_layout() 变 True 而门店不在注册表里,门店闸会拒掉全站请求。
4. **不覆盖门店已有数据。** 目标文件已经有内容 → 跳过,绝不拿顶层旧副本盖上去。
5. **不推翻管理员的显式配置。** 只补**缺失/类型损坏**的字段;显式值(空数组、
   all_stores=False)原样保留 —— 否则每次启动都在偷偷改管理员的设置。
6. **失败不阻塞启动。** 迁移异常只记日志,服务照常起(此时是单店布局,
   门店闸整体放行,行为与改造前一致)。

幂等判定用**完成标记** stores/main/.migrated —— 全部搬完才写。
不能用「stores/main/readings.json 存在」判定:上次搬一半(磁盘满)就失败时,
那个文件已经在了,下次启动会误判「已迁移」→ 直接跳过 → 剩下 5 个数据文件
永远补不上 → 门店数据永久残缺,而且没有任何报错。

迁移后:
- stores/main/            ← 原顶层 6 个数据文件 + images/
- stores/main/store.json  ← 由 settings.json 的 meter/config 合成
- stores/main/.migrated   ← 完成标记(幂等判定的唯一依据)
- settings.json           ← 增加 stores[] 注册表,现有用户补上门店归属
"""
from __future__ import annotations

import contextlib
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from storage import DATA_FILES, load_json, log

# 完成标记文件名 —— 全部搬完才写,作为「已迁移」的唯一判据。
MARKER_NAME = ".migrated"

# 默认店(总店)的 ID —— 与 context.DEFAULT_STORE_ID / registry.DEFAULT_STORE_ID 一致。
DEFAULT_STORE_ID = "main"

# 值班照片目录名(与 modules/duty/handler.py 的 _get_images_dir() 对应)。
IMAGES_DIR_NAME = "images"

# 搬迁过程中的临时文件名后缀 —— 复制完才原子替换,中途崩溃不会留半截文件。
TMP_SUFFIX = ".migrating"


def _archive_legacy_quietly() -> None:
    """跑一次「顶层 meter/config 归档」。异常只记日志。

    它只是**清理误导**(让人别以为顶层那两项还在生效),不是功能路径 ——
    失败绝不该挡住启动。
    """
    with contextlib.suppress(Exception):
        archive_legacy_global_meter_settings()


def migrate_to_stores(data_dir: Path) -> dict[str, Any]:
    """把顶层数据迁移到默认店目录。返回执行结果统计。

    返回 {"migrated": bool, "created": bool, "backup": str|None,
          "stores": int, "ok": bool}

    ok = 门店注册表是否**确认落盘**(回读磁盘校验过)。
    ok=False 表示注册表没写成功 —— 此时**没有建 stores/ 目录**,
    仍是单店布局,调用方应打一条醒目的 WARN(但不阻塞启动)。
    """
    result: dict[str, Any] = {
        "migrated": False, "created": False, "backup": None, "stores": 0, "ok": False,
    }
    data_dir = Path(data_dir)
    main_dir = data_dir / "stores" / DEFAULT_STORE_ID
    marker = main_dir / MARKER_NAME

    # 已迁完 → 只补注册表(幂等)。标记是权威判据,不看单个文件。
    if marker.exists():
        stores = _ensure_registry(data_dir)
        result["stores"] = stores or 0
        result["ok"] = stores is not None
        # ⚠️ 已迁移的安装走的就是这条提前 return —— 归档必须放在这里。
        #    放在函数尾部只覆盖"首次迁移",而线上绝大多数是"早就迁完了"
        #    (实施中真的漏了,靠 test_already_migrated_install_still_archives 抓到)。
        _archive_legacy_quietly()
        return result

    # 0. 注册表先落盘 —— **必须在建 stores/ 目录之前**。
    #    反过来的话:目录建好了但注册表写失败 → multi_store_layout() 变 True,
    #    而门店闸要求门店必须已注册 → 全站 404。
    #    先写注册表则反之无风险:stores/ 不存在 = 单店布局,门店闸整体放行,
    #    数据仍走顶层文件,下次启动再迁一次即可(幂等)。
    stores = _ensure_registry(data_dir)
    result["stores"] = stores or 0
    result["ok"] = stores is not None
    if stores is None:
        log("[MIGRATE] 门店注册表未落盘,放弃迁移(保持单店布局继续运行)")
        return result

    if _legacy_records_present(data_dir):
        # 1. 先备份 —— 备份失败就不迁
        backup_path = _backup_before_migration(data_dir)
        if backup_path is None:
            log("[MIGRATE] 备份失败,放弃迁移(保持单店布局继续运行)")
            return result
        result["backup"] = str(backup_path)
        # 2. 搬文件
        try:
            main_dir.mkdir(parents=True, exist_ok=True)
            _cleanup_stale_tmp(main_dir)
            for fname in DATA_FILES.values():
                _copy_legacy_file(data_dir / fname, main_dir / fname)
            # 2b. 值班照片 —— 多门店布局下照片落在 stores/<id>/images/,
            #     迁移前落在顶层 images/;不搬过去历史照片就变成孤儿。
            _copy_images_dir(data_dir, main_dir)
            # 3. 门店配置 store.json
            _write_default_store_json(data_dir)
            # 4. 完成标记 —— 全部搬完才写
            _write_marker(main_dir)
        except Exception as e:
            log(f"[MIGRATE] 迁移失败: {e} —— 保持单店布局继续运行")
            return result
        result["migrated"] = True
    else:
        # 全新安装:直接建好默认店
        try:
            main_dir.mkdir(parents=True, exist_ok=True)
            for model, fname in DATA_FILES.items():
                p = main_dir / fname
                if not p.exists():
                    _save_empty_model(model, p)
            _write_default_store_json(data_dir)
            _write_marker(main_dir)
        except Exception as e:
            log(f"[MIGRATE] 初始化默认店失败: {e} —— 保持单店布局继续运行)")
            return result
        result["created"] = True

    # 布局就绪 = 各店 store.json 里已有自己的表集合/电价,顶层遗留的那份可以归档了
    _archive_legacy_quietly()

    log(f"[MIGRATE] 多门店布局就绪: stores/{DEFAULT_STORE_ID}/ "
        f"(迁移={result['migrated']}, 新建={result['created']}, 门店数={result['stores']})")
    return result


# settings.json 顶层遗留的「全局电表配置」—— 分店改造后已不再是权威来源
LEGACY_SETTINGS_KEYS = ("meter", "config")


def archive_legacy_global_meter_settings() -> bool:
    """把 settings.json 顶层的 meter / config 归档到 `_legacy_meter_config`。

    为什么不再留在顶层:分店改造后「表集合 + 电价/水价/水电倍率」是**每店一份**
    (`stores/<id>/store.json`)。顶层这两项只在迁移时当过种子,之后还读它们的
    只剩迁移代码本身。留着会让人以为那是"全局电表配置" —— 手改它毫无效果,
    更容易在改错之后以为改到了。

    为什么归档而不是删除:它们是迁移前的唯一来源。删掉后若有人要回滚到旧版本
    (旧版本按全局 config 算钱),自定义电价就找不回来了。挪到 `_legacy_` 前缀下
    既离开"看起来生效"的位置,又保留可恢复性。

    幂等:顶层已经没有这两个键就什么都不做。返回是否真的归档了。
    调用时机:必须等 `stores/<默认店>/store.json` 写完 —— 否则迁移的种子还没落地。
    """
    from modules.system import settings_handler

    try:
        settings = settings_handler.get_settings()
    except Exception as e:
        log(f"[MIGRATE] 归档遗留电表配置失败(读 settings): {e}")
        return False
    if not isinstance(settings, dict):
        return False

    present = [k for k in LEGACY_SETTINGS_KEYS if k in settings]
    if not present:
        return False

    archived = settings.get("_legacy_meter_config")
    if not isinstance(archived, dict):
        archived = {}
    for key in present:
        archived[key] = settings.pop(key)
    archived["archived_at"] = datetime.now().replace(microsecond=0).isoformat()
    settings["_legacy_meter_config"] = archived

    try:
        settings_handler.save_settings(settings)
    except Exception as e:
        log(f"[MIGRATE] 归档遗留电表配置失败(写 settings): {e}")
        return False

    log(f"[MIGRATE] 已把顶层 {', '.join(present)} 归档到 _legacy_meter_config"
        " —— 每店的表集合/电价现以 stores/<id>/store.json 为准")
    return True


def migrate_settings_stores(data_dir: Path) -> dict[str, Any]:
    """只补注册表与用户门店归属,不搬数据文件。

    返回 {"stores": int, "ok": bool};ok=False 表示注册表没能落盘。
    """
    stores = _ensure_registry(Path(data_dir))
    return {"stores": stores or 0, "ok": stores is not None}


def _ensure_registry(data_dir: Path) -> Optional[int]:
    """确保 settings.json 有门店注册表,且现有用户都有门店归属。

    返回门店数;**失败返回 None**(调用方必须中止迁移,不许建 stores/ 目录)。

    为什么不"记个日志就往下走":settings_handler.save_settings() 会吞掉所有
    异常(只往 stderr 打一行 WARN),写失败时调用方会以为成功 —— 注册表里没有
    main,但 stores/main/ 建出来了 → multi_store_layout() 变 True → 门店闸
    要求门店必须已注册 → 全站 404。所以写完必须**回读磁盘**校验。

    补字段的规矩:**只补缺失/类型损坏的,绝不覆盖管理员的显式配置**。
    - 员工 `store_ids: []` = 管理员刻意「还没分配门店」→ 原样保留。
      自动补成 ["main"] 等于凭空给员工总店访问权。
    - admin `all_stores: False` = 管理员刻意把这个 admin 限定在单店 →
      原样保留。每次启动翻回 True = 静默提权。
    """
    from modules.stores import registry
    from modules.system import settings_handler

    if not (Path(data_dir) / "settings.json").exists():
        log("[MIGRATE] settings.json 不存在,无法登记门店")
        return None

    try:
        settings = settings_handler.get_settings()
    except Exception as e:
        log(f"[MIGRATE] 读取 settings.json 失败,跳过注册表: {e}")
        return None
    if not isinstance(settings, dict):
        log("[MIGRATE] settings.json 内容不是 dict,跳过注册表")
        return None

    # ⚠️ 快照必须在 ensure_default_store() **之前**取 ——
    #    ensure_default_store() 会 setdefault("stores", []) 原地改 settings,
    #    调用之后再判断 "stores" not in settings 永远是 False(死代码),
    #    默认店就永远存不进 settings.json。
    had_stores_key = isinstance(settings.get("stores"), list)
    before_ids = {s.get("id") for s in registry.list_stores(settings)}

    registry.ensure_default_store(settings)

    after_ids = {s.get("id") for s in registry.list_stores(settings)}
    changed = (not had_stores_key) or (before_ids != after_ids)

    default_id = registry.DEFAULT_STORE_ID
    for u in settings.get("users") or []:
        if not isinstance(u, dict):
            continue
        role = u.get("role", "employee")
        if role == "admin":
            # 总部账号:缺 all_stores 字段时补 True。
            # 显式 False **原样保留** —— 管理员可能刻意把某个 admin 限定在单店
            # (Task 6 的既定行为),每次启动翻回 True 就是静默提权。
            if "all_stores" not in u:
                u["all_stores"] = True
                changed = True
            elif not isinstance(u.get("all_stores"), bool):
                # 类型损坏(字符串/数字/null)→ 归一化
                u["all_stores"] = True
                changed = True
        else:
            # 分店员工:缺 store_ids 字段时补默认店,避免迁移后所有人被挡在门外。
            # 显式 [] **原样保留** —— 那是管理员刻意「还没分配门店」的意思。
            if "store_ids" not in u:
                u["store_ids"] = [default_id]
                changed = True
            elif not isinstance(u.get("store_ids"), list):
                # 类型损坏 → 归一化
                u["store_ids"] = [default_id]
                changed = True

    if changed:
        try:
            settings_handler.save_settings(settings)
        except Exception as e:
            log(f"[MIGRATE] 保存 settings.json 失败: {e}")
            return None

    # 回读磁盘校验 —— 内存里的 dict 不算数,必须是磁盘上真的写着 main。
    try:
        on_disk = settings_handler.get_settings()
    except Exception as e:
        log(f"[MIGRATE] 回读 settings.json 失败: {e}")
        return None
    disk_ids = {s.get("id") for s in registry.list_stores(on_disk)}
    if default_id not in disk_ids:
        log("[MIGRATE] 门店注册表未落盘(main 不在册),放弃迁移(保持单店布局继续运行)")
        return None

    return len(disk_ids)


def _legacy_records_present(data_dir: Path) -> bool:
    """顶层有没有真实数据(区别于 init_data_files() 建出来的空文件)。"""
    return any(_file_has_records(data_dir / fname) for fname in DATA_FILES.values())


def _file_has_records(path: Path) -> bool:
    """JSON 文件里是否有实际记录。

    用来区分「老部署的遗留数据」和「全新安装」:
    init_data_files() 会先创建 6 个空的顶层 JSON 文件(内容是 []),
    只看文件存在会把全新安装误判成迁移场景,多打一次备份。

    走 storage.load_json —— 统一读存储层(文件损坏时还能从备份恢复),
    不在这里自己 json.loads 读文件。
    """
    if not path.exists():
        return False
    try:
        data = load_json(path, [])
    except Exception:
        return False
    return isinstance(data, list) and len(data) > 0


def _copy_legacy_file(src: Path, dst: Path) -> None:
    """把一个顶层数据文件搬进门店目录。

    口径:**目标已存在且有内容 → 跳过,绝不覆盖**。
    门店目录一旦有数据就是「活数据」(迁移之后又新记的账),
    拿顶层旧副本盖上去 = 静默丢数据。
    目标不存在或是空载荷 → 搬(顶层是旧数据,门店还空着)。

    复制用 shutil.copy2(字节级,保留原文件格式与编码),落盘走
    「临时文件 + 原子替换」:中途崩溃不会在门店目录里留半截文件。
    """
    if not src.exists():
        return
    if dst.exists() and not _is_empty_payload(dst):
        log(f"[MIGRATE] {dst.name} 已存在且有内容,跳过(不覆盖门店活数据)")
        return
    _copy_atomic(src, dst)
    log(f"[MIGRATE] {src.name} → stores/{DEFAULT_STORE_ID}/{dst.name}")


def _copy_images_dir(data_dir: Path, main_dir: Path) -> None:
    """把顶层 images/ 复制到 stores/<id>/images/。

    值班照片不能变孤儿:多门店布局下上传落在 stores/<id>/images/,
    迁移前落在顶层 images/ —— 不搬过去,历史照片就再也看不到。

    顶层 images/ 保留(可回滚副本)。源目录不存在 → 跳过(不是错误)。

    口径与 _copy_legacy_file() 一致:**目标已存在且有内容 → 跳过,绝不覆盖**。
    (图片文件名带毫秒时间戳,撞名概率极低,但口径必须统一 ——
     门店目录里的照片也是「活数据」。)
    """
    src_dir = data_dir / IMAGES_DIR_NAME
    if not src_dir.is_dir():
        return
    dst_dir = main_dir / IMAGES_DIR_NAME
    for src in sorted(src_dir.iterdir()):
        if not src.is_file():
            continue
        dst = dst_dir / src.name
        if dst.exists() and not _is_empty_file(dst):
            log(f"[MIGRATE] {IMAGES_DIR_NAME}/{src.name} 已存在且有内容,跳过(不覆盖)")
            continue
        dst_dir.mkdir(parents=True, exist_ok=True)
        _copy_atomic(src, dst)
        log(f"[MIGRATE] {IMAGES_DIR_NAME}/{src.name} → "
            f"stores/{DEFAULT_STORE_ID}/{IMAGES_DIR_NAME}/{dst.name}")


def _copy_atomic(src: Path, dst: Path) -> None:
    """字节级复制 + 原子替换(中途崩溃不会留半截文件)。"""
    tmp = dst.with_name(dst.name + TMP_SUFFIX)
    shutil.copy2(src, tmp)
    tmp.replace(dst)


def _cleanup_stale_tmp(main_dir: Path) -> None:
    """清掉上次搬迁残留的临时文件(复制完才原子替换,残留说明上次中途失败)。"""
    try:
        stale = list(main_dir.glob("*" + TMP_SUFFIX))
    except OSError:
        return
    for p in stale:
        # 清理是尽力而为 —— 删不掉也不能掩盖原始异常
        with contextlib.suppress(OSError):
            p.unlink()


def _is_empty_payload(path: Path) -> bool:
    """JSON 数据文件是不是「空的」(还没有数据)。"""
    if not path.exists():
        return True
    try:
        data = load_json(path, [])
    except Exception:
        return False
    if isinstance(data, list):
        return not data
    if isinstance(data, dict):
        return not data
    return False


def _is_empty_file(path: Path) -> bool:
    """普通文件(照片)是不是「空的」(0 字节)。"""
    try:
        return path.stat().st_size == 0
    except OSError:
        return False


def _save_empty_model(model: str, path: Path) -> None:
    """写一个空数据文件(走 storage.save_json:原子写 + 失效存储层缓存)。

    不用 path.write_text("[]") —— 那样中途崩溃会留半截文件,
    而且不失效 storage 的 LRU 缓存(别人读到的是陈旧值)。
    """
    import storage

    with storage.get_lock(model):
        storage.save_json(path, [])


def _backup_before_migration(data_dir: Path) -> Optional[Path]:
    """迁移前打一份完整备份。失败返回 None。"""
    try:
        from storage import backup_data
        p = backup_data(Path(data_dir), force=True)
        return Path(p) if p else None
    except Exception as e:
        log(f"[MIGRATE] 迁移前备份失败: {e}")
        return None


def _write_default_store_json(data_dir: Path) -> None:
    """用 settings.json 的 meter/config 合成默认店的 store.json。

    数据源与 _ensure_registry() **同源**(settings_handler.get_settings()):
    直接 json.loads(path.read_text()) 读文件的话,一是绕过存储层,
    二是和注册表读的不是同一个数据源 —— 两边不一致时,
    store.json 的表定义会和注册表对不上。

    落盘路径**显式取自传入的 data_dir**(不是 config.store_config_path() 的
    全局 DATA_PATHS 基准):迁移的其它产物(stores/main/*.json、images/、
    .migrated)全都在 data_dir 下,store.json 也必须跟着走 ——
    否则 migrate_to_stores(别的目录)会把门店配置写到全局数据目录里去。
    """
    import storage
    from modules.stores import config, registry
    from modules.system import settings_handler

    path = Path(data_dir) / "stores" / DEFAULT_STORE_ID / "store.json"
    if path.exists():
        return

    settings: dict[str, Any] = {}
    try:
        loaded = settings_handler.get_settings()
        if isinstance(loaded, dict):
            settings = loaded
    except Exception as e:
        log(f"[MIGRATE] 读取 settings.json 失败,用默认表定义: {e}")

    meters = settings.get("meter")
    prices = settings.get("config")

    meter_list: list[dict[str, Any]] = []
    if isinstance(meters, dict):
        # settings.json 的 meter 是 {key: {label, icon, multiplier, color}}
        for key, val in meters.items():
            if not isinstance(val, dict):
                continue
            meter_list.append({
                "key": key,
                "label": val.get("label", key),
                "icon": val.get("icon", ""),
                "multiplier": val.get("multiplier", 1),
                "color": val.get("color", "#888888"),
            })
    if not meter_list:
        meter_list = [dict(m) for m in config.DEFAULT_METERS]

    price_cfg = dict(config.DEFAULT_CONFIG)
    if isinstance(prices, dict):
        for k, v in prices.items():
            price_cfg[k] = v

    cfg = {
        "id": DEFAULT_STORE_ID,
        "name": registry.DEFAULT_STORE_NAME,
        "meters": meter_list,
        "config": price_cfg,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # store.json 不是 DATA_FILES 里的模型 → get_lock 会回落到共享锁,
        # 写入照样串行;写走 storage.save_json(原子写 + 失效存储层缓存)。
        with storage.get_lock("store_config"):
            storage.save_json(path, cfg)
    except Exception as e:
        log(f"[MIGRATE] 写入 store.json 失败: {e}")


def _write_marker(main_dir: Path) -> None:
    """写完成标记 —— 幂等判定的唯一依据,全部搬完才写。"""
    marker = main_dir / MARKER_NAME
    marker.write_text(datetime.now().isoformat(), encoding="utf-8")

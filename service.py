import uuid
from datetime import datetime, timezone, timedelta

import store


def _now():
    return datetime.now(timezone.utc).isoformat()


def _log(action, success, reader_id=None, book_id=None, detail=""):
    store.append_log({
        "log_id": str(uuid.uuid4()),
        "timestamp": _now(),
        "action": action,
        "reader_id": reader_id,
        "book_id": book_id,
        "detail": detail,
        "success": success,
    })


def add_book(book_id, title, total_copies, borrow_days, retain_hours):
    existing = store.load_book(book_id)
    if existing:
        _log("add_book", False, book_id=book_id, detail=f"书目 {book_id} 已存在")
        return None, f"书目 {book_id} 已存在"
    book = {
        "book_id": book_id,
        "title": title,
        "total_copies": total_copies,
        "borrow_days": borrow_days,
        "retain_hours": retain_hours,
    }
    store.save_book(book)
    _log("add_book", True, book_id=book_id, detail=f"添加书目 {title}")
    return book, None


def update_book(book_id, **kwargs):
    book = store.load_book(book_id)
    if not book:
        _log("update_book", False, book_id=book_id, detail=f"书目 {book_id} 不存在")
        return None, f"书目 {book_id} 不存在"
    for k, v in kwargs.items():
        if k in ("title", "total_copies", "borrow_days", "retain_hours") and v is not None:
            book[k] = v
    store.save_book(book)
    _log("update_book", True, book_id=book_id, detail=f"更新书目 {book_id}")
    return book, None


def delete_book(book_id):
    book = store.load_book(book_id)
    if not book:
        _log("delete_book", False, book_id=book_id, detail=f"书目 {book_id} 不存在")
        return False, f"书目 {book_id} 不存在"
    store.delete_book(book_id)
    _log("delete_book", True, book_id=book_id, detail=f"删除书目 {book_id}")
    return True, None


def get_book(book_id):
    return store.load_book(book_id)


def list_books():
    return store.list_books()


def _count_active_status(book_id, status):
    reservations = store.load_reservations()
    return sum(
        1 for r in reservations
        if r["book_id"] == book_id and r["status"] == status
    )


def _available_copies(book_id):
    book = store.load_book(book_id)
    if not book:
        return 0
    borrowed = _count_active_status(book_id, "borrowed")
    available_notified = _count_active_status(book_id, "available")
    return book["total_copies"] - borrowed - available_notified


def reserve(book_id, reader_id):
    if store.is_blacklisted(reader_id):
        detail = f"读者 {reader_id} 在黑名单中，无法预约"
        _log("reserve", False, reader_id=reader_id, book_id=book_id, detail=detail)
        return None, detail

    book = store.load_book(book_id)
    if not book:
        detail = f"书目 {book_id} 不存在"
        _log("reserve", False, reader_id=reader_id, book_id=book_id, detail=detail)
        return None, detail

    reservations = store.load_reservations()
    active = [
        r for r in reservations
        if r["book_id"] == book_id and r["reader_id"] == reader_id
        and r["status"] in ("waiting", "available", "borrowed")
    ]
    if active:
        detail = f"读者 {reader_id} 对书目 {book_id} 已有活跃预约/借阅，不可重复占位"
        _log("reserve", False, reader_id=reader_id, book_id=book_id, detail=detail)
        return None, detail

    reservation_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    avail = _available_copies(book_id)
    if avail > 0:
        status = "available"
        expire_at = (now + timedelta(hours=book["retain_hours"])).isoformat()
    else:
        status = "waiting"
        expire_at = None

    reservation = {
        "reservation_id": reservation_id,
        "book_id": book_id,
        "reader_id": reader_id,
        "status": status,
        "created_at": now.isoformat(),
        "available_at": now.isoformat() if status == "available" else None,
        "expire_at": expire_at,
        "borrowed_at": None,
        "returned_at": None,
    }
    store.add_reservation(reservation)
    _log("reserve", True, reader_id=reader_id, book_id=book_id,
         detail=f"预约成功，状态={status}")
    return reservation, None


def get_queue(book_id):
    reservations = store.load_reservations()
    queue = [r for r in reservations if r["book_id"] == book_id
             and r["status"] in ("waiting", "available", "borrowed")]
    queue.sort(key=lambda r: r["created_at"])
    waiting = [r for r in queue if r["status"] == "waiting"]
    for i, r in enumerate(waiting):
        r["position"] = i + 1
    return queue


def get_position(book_id, reader_id):
    queue = get_queue(book_id)
    for r in queue:
        if r["reader_id"] == reader_id and r["status"] == "waiting":
            return r.get("position", -1)
        if r["reader_id"] == reader_id and r["status"] in ("available", "borrowed"):
            return 0
    return -1


def cancel_reservation(reservation_id, reader_id):
    reservation = store.get_reservation(reservation_id)
    if not reservation:
        detail = f"预约记录 {reservation_id} 不存在"
        _log("cancel", False, reader_id=reader_id, detail=detail)
        return False, detail
    if reservation["reader_id"] != reader_id:
        detail = f"预约记录 {reservation_id} 不属于读者 {reader_id}"
        _log("cancel", False, reader_id=reader_id, detail=detail)
        return False, detail
    if reservation["status"] not in ("waiting", "available"):
        detail = f"预约状态为 {reservation['status']}，无法取消"
        _log("cancel", False, reader_id=reader_id, detail=detail)
        return False, detail

    old_status = reservation["status"]
    store.update_reservation(reservation_id, {"status": "cancelled"})
    _log("cancel", True, reader_id=reader_id, book_id=reservation["book_id"],
         detail=f"取消预约，原状态={old_status}")

    if old_status == "available":
        _promote_next(reservation["book_id"])
    return True, None


def checkout(book_id, reader_id):
    if store.is_blacklisted(reader_id):
        detail = f"读者 {reader_id} 在黑名单中，无法借出"
        _log("checkout", False, reader_id=reader_id, book_id=book_id, detail=detail)
        return None, detail

    reservations = store.load_reservations()
    available_res = [
        r for r in reservations
        if r["book_id"] == book_id and r["reader_id"] == reader_id
        and r["status"] == "available"
    ]
    if not available_res:
        waiting_res = [
            r for r in reservations
            if r["book_id"] == book_id and r["reader_id"] == reader_id
            and r["status"] == "waiting"
        ]
        if waiting_res:
            all_active = sorted(
                [r for r in reservations if r["book_id"] == book_id
                 and r["status"] in ("available", "waiting")],
                key=lambda r: r["created_at"],
            )
            next_reader = all_active[0]["reader_id"] if all_active else None
            detail = (f"读者 {reader_id} 在等待队列中，尚未轮到借出，"
                      f"不可越过队首。当前队首应借出的读者是 {next_reader}")
        else:
            detail = f"读者 {reader_id} 对书目 {book_id} 没有待取的预约记录"
        _log("checkout", False, reader_id=reader_id, book_id=book_id, detail=detail)
        return None, detail

    now = datetime.now(timezone.utc)
    res = available_res[0]

    if res["expire_at"]:
        expire_time = datetime.fromisoformat(res["expire_at"])
        if now > expire_time:
            detail = f"预约已过期（过期时间 {res['expire_at']}），无法借出"
            _log("checkout", False, reader_id=reader_id, book_id=book_id, detail=detail)
            return None, detail

    book = store.load_book(book_id)
    due_date = (now + timedelta(days=book["borrow_days"])).isoformat()
    updates = {
        "status": "borrowed",
        "borrowed_at": now.isoformat(),
        "expire_at": None,
    }
    updated = store.update_reservation(res["reservation_id"], updates)
    if updated:
        updated["due_date"] = due_date
    _log("checkout", True, reader_id=reader_id, book_id=book_id,
         detail=f"借出成功，应还日期={due_date}")
    return updated, None


def return_book(book_id, reader_id):
    reservations = store.load_reservations()
    borrowed_res = [
        r for r in reservations
        if r["book_id"] == book_id and r["reader_id"] == reader_id
        and r["status"] == "borrowed"
    ]
    if not borrowed_res:
        detail = f"读者 {reader_id} 对书目 {book_id} 没有借阅记录，无法归还"
        _log("return", False, reader_id=reader_id, book_id=book_id, detail=detail)
        return None, detail

    now = datetime.now(timezone.utc)
    res = borrowed_res[0]
    updates = {
        "status": "returned",
        "returned_at": now.isoformat(),
    }
    updated = store.update_reservation(res["reservation_id"], updates)
    _log("return", True, reader_id=reader_id, book_id=book_id,
         detail=f"归还成功，借阅ID={res['reservation_id']}")

    _promote_next(book_id)
    return updated, None


def _promote_next(book_id):
    book = store.load_book(book_id)
    if not book:
        return

    reservations = store.load_reservations()
    waiting = sorted(
        [r for r in reservations if r["book_id"] == book_id and r["status"] == "waiting"],
        key=lambda r: r["created_at"],
    )
    available_count = _count_active_status(book_id, "available")
    borrowed_count = _count_active_status(book_id, "borrowed")
    free_slots = book["total_copies"] - available_count - borrowed_count

    now = datetime.now(timezone.utc)
    promoted = 0
    for r in waiting:
        if free_slots <= 0:
            break
        expire_at = (now + timedelta(hours=book["retain_hours"])).isoformat()
        store.update_reservation(r["reservation_id"], {
            "status": "available",
            "available_at": now.isoformat(),
            "expire_at": expire_at,
        })
        _log("promote", True, reader_id=r["reader_id"], book_id=book_id,
             detail=f"读者 {r['reader_id']} 晋级为待取状态")
        free_slots -= 1
        promoted += 1
    return promoted


def process_expired():
    reservations = store.load_reservations()
    now = datetime.now(timezone.utc)
    expired_books = set()

    for r in reservations:
        if r["status"] == "available" and r.get("expire_at"):
            expire_time = datetime.fromisoformat(r["expire_at"])
            if now > expire_time:
                store.update_reservation(r["reservation_id"], {"status": "expired"})
                _log("expire", True, reader_id=r["reader_id"], book_id=r["book_id"],
                     detail=f"预约 {r['reservation_id']} 已过期释放")
                expired_books.add(r["book_id"])

    for book_id in expired_books:
        _promote_next(book_id)

    return len(expired_books)


def add_blacklist(reader_id, reason):
    ok = store.add_to_blacklist(reader_id, reason)
    if ok:
        _log("blacklist_add", True, reader_id=reader_id, detail=f"加入黑名单: {reason}")
        return True, None
    detail = f"读者 {reader_id} 已在黑名单中"
    _log("blacklist_add", False, reader_id=reader_id, detail=detail)
    return False, detail


def remove_blacklist(reader_id):
    ok = store.remove_from_blacklist(reader_id)
    if ok:
        _log("blacklist_remove", True, reader_id=reader_id, detail="移出黑名单")
        return True, None
    detail = f"读者 {reader_id} 不在黑名单中"
    _log("blacklist_remove", False, reader_id=reader_id, detail=detail)
    return False, detail


def get_blacklist():
    return store.load_blacklist()


def get_logs(book_id=None, reader_id=None, limit=100):
    logs = store.load_logs()
    if book_id:
        logs = [l for l in logs if l.get("book_id") == book_id]
    if reader_id:
        logs = [l for l in logs if l.get("reader_id") == reader_id]
    logs.sort(key=lambda l: l["timestamp"], reverse=True)
    return logs[:limit]


def export_queue(book_id):
    book = store.load_book(book_id)
    if not book:
        return None, f"书目 {book_id} 不存在"
    queue = get_queue(book_id)
    history = get_logs(book_id=book_id, limit=1000000)
    history.sort(key=lambda l: l["timestamp"])
    snapshot = {
        "export_time": _now(),
        "book": book,
        "queue": queue,
        "total_in_queue": len(queue),
        "history": history,
    }
    return snapshot, None


def _get_book_stats(book_id):
    available = _available_copies(book_id)
    to_pick = _count_active_status(book_id, "available")
    waiting = _count_active_status(book_id, "waiting")
    borrowed = _count_active_status(book_id, "borrowed")
    return {
        "available_copies": available,
        "to_pick_count": to_pick,
        "waiting_count": waiting,
        "borrowed_count": borrowed,
    }


def _get_queue_summary(book_id):
    queue = get_queue(book_id)
    waiting = [r for r in queue if r["status"] == "waiting"]
    available = [r for r in queue if r["status"] == "available"]
    borrowed = [r for r in queue if r["status"] == "borrowed"]
    return {
        "total_active": len(queue),
        "waiting": [
            {"reader_id": r["reader_id"], "position": r.get("position", 0), "created_at": r["created_at"]}
            for r in waiting
        ],
        "available": [
            {"reader_id": r["reader_id"], "expire_at": r.get("expire_at"), "created_at": r["created_at"]}
            for r in available
        ],
        "borrowed": [
            {"reader_id": r["reader_id"], "borrowed_at": r.get("borrowed_at"), "created_at": r["created_at"]}
            for r in borrowed
        ],
    }


def export_collection():
    books = store.list_books()
    books_sorted = sorted(books, key=lambda b: b["book_id"])

    export_data = {
        "export_time": _now(),
        "version": "1.0",
        "total_books": len(books_sorted),
        "books": [],
    }

    for book in books_sorted:
        book_id = book["book_id"]
        stats = _get_book_stats(book_id)
        queue_summary = _get_queue_summary(book_id)

        book_entry = {
            "book_id": book["book_id"],
            "title": book["title"],
            "total_copies": book["total_copies"],
            "borrow_days": book["borrow_days"],
            "retain_hours": book["retain_hours"],
            "stats": stats,
            "queue_summary": queue_summary,
        }
        export_data["books"].append(book_entry)

    _log("export_collection", True, detail=f"导出馆藏共 {len(books_sorted)} 本书")
    return export_data, None


def _validate_book_config(book_data, idx):
    errors = []
    required_fields = ["book_id", "title", "total_copies", "borrow_days", "retain_hours"]

    for field in required_fields:
        if field not in book_data:
            errors.append(f"第 {idx} 条记录缺少必填字段: {field}")

    if "book_id" in book_data:
        if not isinstance(book_data["book_id"], str) or not book_data["book_id"].strip():
            errors.append(f"第 {idx} 条记录 book_id 必须是非空字符串")

    if "title" in book_data:
        if not isinstance(book_data["title"], str) or not book_data["title"].strip():
            errors.append(f"第 {idx} 条记录 title 必须是非空字符串")

    if "total_copies" in book_data:
        if not isinstance(book_data["total_copies"], int):
            errors.append(f"第 {idx} 条记录 total_copies 必须是整数，实际类型: {type(book_data['total_copies']).__name__}")

    if "borrow_days" in book_data:
        if not isinstance(book_data["borrow_days"], int):
            errors.append(f"第 {idx} 条记录 borrow_days 必须是整数，实际类型: {type(book_data['borrow_days']).__name__}")

    if "retain_hours" in book_data:
        if not isinstance(book_data["retain_hours"], int):
            errors.append(f"第 {idx} 条记录 retain_hours 必须是整数，实际类型: {type(book_data['retain_hours']).__name__}")

    return errors


def _has_active_reservations(book_id):
    reservations = store.load_reservations()
    active = [
        r for r in reservations
        if r["book_id"] == book_id and r["status"] in ("waiting", "available", "borrowed")
    ]
    return len(active) > 0


def import_collection(import_data, dry_run=False):
    conflicts = []
    validation_errors = []

    if not isinstance(import_data, dict):
        return None, None, ["导入数据格式错误，应为 JSON 对象"]

    books_data = import_data.get("books", [])
    if not isinstance(books_data, list) or len(books_data) == 0:
        return None, None, ["导入数据缺少 books 列表或列表为空"]

    seen_book_ids = set()

    for idx, book_data in enumerate(books_data):
        errors = _validate_book_config(book_data, idx)
        if errors:
            validation_errors.extend(errors)
            continue

        book_id = book_data["book_id"]

        if book_id in seen_book_ids:
            conflicts.append({
                "type": "duplicate_in_import",
                "book_id": book_id,
                "index": idx,
                "message": f"导入文件中存在重复的 book_id: {book_id}",
            })
        seen_book_ids.add(book_id)

        existing = store.load_book(book_id)
        if existing:
            conflict_type = "duplicate_book_id"
            detail = f"书目 {book_id} 已存在"

            if _has_active_reservations(book_id):
                conflict_type = "has_active_reservations"
                detail = f"书目 {book_id} 已有活跃预约（等待/待取/借阅中），不能覆盖"

            conflicts.append({
                "type": conflict_type,
                "book_id": book_id,
                "index": idx,
                "existing_config": existing,
                "import_config": {k: book_data[k] for k in ["title", "total_copies", "borrow_days", "retain_hours"]},
                "message": detail,
            })
            continue

        if book_data["total_copies"] <= 0:
            conflicts.append({
                "type": "invalid_copies",
                "book_id": book_id,
                "index": idx,
                "message": f"书目 {book_id} 的 total_copies 非法: {book_data['total_copies']}，必须为正整数",
            })

        if book_data["borrow_days"] <= 0:
            conflicts.append({
                "type": "invalid_borrow_days",
                "book_id": book_id,
                "index": idx,
                "message": f"书目 {book_id} 的 borrow_days 非法: {book_data['borrow_days']}，必须为正整数",
            })

        if book_data["retain_hours"] < 0:
            conflicts.append({
                "type": "invalid_retain_hours",
                "book_id": book_id,
                "index": idx,
                "message": f"书目 {book_id} 的 retain_hours 非法: {book_data['retain_hours']}，必须为非负整数",
            })

    if validation_errors:
        return None, None, validation_errors

    if conflicts:
        if dry_run:
            _log("import_collection_dry_run", False, detail=f"DRY-RUN 发现 {len(conflicts)} 个冲突")
        else:
            _log("import_collection", False, detail=f"导入发现 {len(conflicts)} 个冲突，已回滚")
        return None, conflicts, None

    if dry_run:
        _log("import_collection_dry_run", True, detail=f"DRY-RUN 校验通过，可导入 {len(books_data)} 本书")
        return len(books_data), None, None

    with store._lock:
        existing_books = store.list_books()
        existing_ids = {b["book_id"] for b in existing_books}
        import_ids = {b["book_id"] for b in books_data}
        overlap = existing_ids & import_ids

        if overlap:
            _log("import_collection", False, detail=f"导入前检查发现冲突: {overlap}")
            return None, [{
                "type": "race_condition",
                "book_id": bid,
                "message": f"书目 {bid} 在导入过程中已被创建",
            } for bid in overlap], None

        saved_books = []
        try:
            for book_data in books_data:
                book = {
                    "book_id": book_data["book_id"],
                    "title": book_data["title"],
                    "total_copies": book_data["total_copies"],
                    "borrow_days": book_data["borrow_days"],
                    "retain_hours": book_data["retain_hours"],
                }
                store.save_book(book)
                saved_books.append(book)
                _log("import_book", True, book_id=book["book_id"],
                     detail=f"批量导入书目: {book['title']}")
        except Exception as e:
            for book in saved_books:
                store.delete_book(book["book_id"])
            _log("import_collection", False, detail=f"导入异常，已回滚 {len(saved_books)} 本书: {str(e)}")
            return None, [{
                "type": "import_error",
                "message": f"导入过程出错，已全部回滚: {str(e)}",
            }], None

    _log("import_collection", True, detail=f"成功批量导入 {len(saved_books)} 本书")
    return len(saved_books), None, None


def export_snapshot():
    books = store.list_books()
    books_sorted = sorted(books, key=lambda b: b["book_id"])

    active_reservations = store.load_active_reservations()
    active_reservations_sorted = sorted(
        active_reservations,
        key=lambda r: (r["book_id"], r["created_at"])
    )

    blacklist = store.load_blacklist()
    blacklist_sorted = sorted(blacklist, key=lambda b: b["reader_id"])

    book_ids_in_snapshot = {b["book_id"] for b in books_sorted}
    logs_for_snapshot = []
    all_logs = store.load_logs()
    for log in all_logs:
        if log.get("book_id") and log["book_id"] in book_ids_in_snapshot:
            logs_for_snapshot.append(log)
        elif log.get("action") in ("import_snapshot", "export_snapshot",
                                   "blacklist_add", "blacklist_remove"):
            logs_for_snapshot.append(log)
    logs_for_snapshot_sorted = sorted(logs_for_snapshot, key=lambda l: l["timestamp"])

    snapshot = {
        "export_time": _now(),
        "version": "2.0",
        "type": "full_snapshot",
        "counts": {
            "books": len(books_sorted),
            "active_reservations": len(active_reservations_sorted),
            "blacklist": len(blacklist_sorted),
            "logs": len(logs_for_snapshot_sorted),
        },
        "books": books_sorted,
        "active_reservations": active_reservations_sorted,
        "blacklist": blacklist_sorted,
        "logs": logs_for_snapshot_sorted,
    }

    _log("export_snapshot", True,
         detail=f"导出完整快照：{len(books_sorted)} 本书，{len(active_reservations_sorted)} 条活跃预约，"
                f"{len(blacklist_sorted)} 条黑名单，{len(logs_for_snapshot_sorted)} 条日志")
    return snapshot, None


def _validate_snapshot_reservation(res_data, idx):
    errors = []
    required_fields = [
        "reservation_id", "book_id", "reader_id", "status",
        "created_at", "available_at", "expire_at",
        "borrowed_at", "returned_at",
    ]
    for field in required_fields:
        if field not in res_data:
            errors.append(f"预约记录 {idx} 缺少必填字段: {field}")

    if "status" in res_data and res_data["status"] not in ("waiting", "available", "borrowed"):
        errors.append(f"预约记录 {idx} 状态 {res_data['status']} 不是活跃状态（仅允许 waiting/available/borrowed）")

    if "reservation_id" in res_data:
        if not isinstance(res_data["reservation_id"], str) or not res_data["reservation_id"].strip():
            errors.append(f"预约记录 {idx} reservation_id 必须是非空字符串")

    if "book_id" in res_data:
        if not isinstance(res_data["book_id"], str) or not res_data["book_id"].strip():
            errors.append(f"预约记录 {idx} book_id 必须是非空字符串")

    if "reader_id" in res_data:
        if not isinstance(res_data["reader_id"], str) or not res_data["reader_id"].strip():
            errors.append(f"预约记录 {idx} reader_id 必须是非空字符串")

    if "created_at" in res_data:
        if not isinstance(res_data["created_at"], str) or not res_data["created_at"].strip():
            errors.append(f"预约记录 {idx} created_at 必须是非空字符串")

    return errors


def _validate_snapshot_blacklist(bl_data, idx):
    errors = []
    required_fields = ["reader_id", "reason", "added_at"]
    for field in required_fields:
        if field not in bl_data:
            errors.append(f"黑名单记录 {idx} 缺少必填字段: {field}")

    if "reader_id" in bl_data:
        if not isinstance(bl_data["reader_id"], str) or not bl_data["reader_id"].strip():
            errors.append(f"黑名单记录 {idx} reader_id 必须是非空字符串")

    return errors


def _validate_snapshot_book(book_data, idx):
    return _validate_book_config(book_data, idx)


_VALID_LOG_ACTIONS = {
    "add_book", "update_book", "delete_book",
    "reserve", "cancel", "checkout", "return",
    "promote", "expire",
    "blacklist_add", "blacklist_remove",
    "import_collection", "import_collection_dry_run", "import_book",
    "export_collection",
    "import_snapshot", "import_snapshot_dry_run", "export_snapshot", "precheck_snapshot",
}


def _validate_snapshot_log(log_data, idx):
    errors = []

    if not isinstance(log_data, dict):
        errors.append({
            "index": idx,
            "field": None,
            "error_code": "log_not_object",
            "message": f"日志记录 {idx} 不是有效的 JSON 对象，实际类型: {type(log_data).__name__}",
            "blocks_other_blocks": False,
            "blocks_current_block": True,
        })
        return errors

    required_fields = ["timestamp", "action", "success"]
    for field in required_fields:
        if field not in log_data:
            errors.append({
                "index": idx,
                "field": field,
                "error_code": "log_missing_field",
                "message": f"日志记录 {idx} 缺少必填字段: {field}",
                "blocks_other_blocks": False,
                "blocks_current_block": True,
            })

    if "action" in log_data:
        if not isinstance(log_data["action"], str) or not log_data["action"].strip():
            errors.append({
                "index": idx,
                "field": "action",
                "error_code": "log_invalid_action_type",
                "message": f"日志记录 {idx} action 必须是非空字符串，实际类型: {type(log_data['action']).__name__}",
                "blocks_other_blocks": False,
                "blocks_current_block": True,
            })

    if "success" in log_data:
        if not isinstance(log_data["success"], bool):
            errors.append({
                "index": idx,
                "field": "success",
                "error_code": "log_invalid_success_type",
                "message": f"日志记录 {idx} success 必须是布尔值（true/false），实际类型: {type(log_data['success']).__name__}",
                "blocks_other_blocks": False,
                "blocks_current_block": True,
            })

    if "timestamp" in log_data:
        ts = log_data["timestamp"]
        if not isinstance(ts, str) or not ts.strip():
            errors.append({
                "index": idx,
                "field": "timestamp",
                "error_code": "log_invalid_timestamp_type",
                "message": f"日志记录 {idx} timestamp 必须是非空字符串（ISO 格式），实际类型: {type(ts).__name__}",
                "blocks_other_blocks": False,
                "blocks_current_block": True,
            })
        else:
            try:
                datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                errors.append({
                    "index": idx,
                    "field": "timestamp",
                    "error_code": "log_invalid_timestamp_format",
                    "message": f"日志记录 {idx} timestamp 格式非法，应为 ISO 格式（如 2026-06-19T10:00:00+00:00），实际值: {ts}",
                    "blocks_other_blocks": False,
                    "blocks_current_block": True,
                })

    if "log_id" in log_data and log_data["log_id"] is not None:
        if not isinstance(log_data["log_id"], str) or not log_data["log_id"].strip():
            errors.append({
                "index": idx,
                "field": "log_id",
                "error_code": "log_invalid_log_id_type",
                "message": f"日志记录 {idx} log_id 必须是非空字符串或不提供，实际类型: {type(log_data['log_id']).__name__}",
                "blocks_other_blocks": False,
                "blocks_current_block": True,
            })

    if "book_id" in log_data and log_data["book_id"] is not None:
        if not isinstance(log_data["book_id"], str) or not log_data["book_id"].strip():
            errors.append({
                "index": idx,
                "field": "book_id",
                "error_code": "log_invalid_book_id_type",
                "message": f"日志记录 {idx} book_id 必须是非空字符串或不提供，实际类型: {type(log_data['book_id']).__name__}",
                "blocks_other_blocks": False,
                "blocks_current_block": True,
            })

    if "reader_id" in log_data and log_data["reader_id"] is not None:
        if not isinstance(log_data["reader_id"], str) or not log_data["reader_id"].strip():
            errors.append({
                "index": idx,
                "field": "reader_id",
                "error_code": "log_invalid_reader_id_type",
                "message": f"日志记录 {idx} reader_id 必须是非空字符串或不提供，实际类型: {type(log_data['reader_id']).__name__}",
                "blocks_other_blocks": False,
                "blocks_current_block": True,
            })

    if "detail" in log_data and log_data["detail"] is not None:
        if not isinstance(log_data["detail"], str):
            errors.append({
                "index": idx,
                "field": "detail",
                "error_code": "log_invalid_detail_type",
                "message": f"日志记录 {idx} detail 必须是字符串或不提供，实际类型: {type(log_data['detail']).__name__}",
                "blocks_other_blocks": False,
                "blocks_current_block": True,
            })

    return errors


def _check_log_order_and_references(valid_logs, book_ids_in_snapshot):
    issues = []

    if len(valid_logs) >= 2:
        prev_ts = None
        prev_idx = None
        for idx, log in enumerate(valid_logs):
            ts_str = log.get("timestamp", "")
            try:
                curr_ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue
            if prev_ts is not None and curr_ts < prev_ts:
                issues.append({
                    "type": "log_timestamp_out_of_order",
                    "index": idx,
                    "field": "timestamp",
                    "previous_index": prev_idx,
                    "previous_timestamp": valid_logs[prev_idx].get("timestamp"),
                    "current_timestamp": ts_str,
                    "message": (f"日志记录 {idx} 的 timestamp ({ts_str}) "
                                f"早于前一条记录 {prev_idx} 的 timestamp ({valid_logs[prev_idx].get('timestamp')})，"
                                f"时间顺序错乱"),
                    "blocks_other_blocks": False,
                    "blocks_current_block": False,
                })
            prev_ts = curr_ts
            prev_idx = idx

    for idx, log in enumerate(valid_logs):
        book_id = log.get("book_id")
        if book_id and book_id not in book_ids_in_snapshot:
            existing_in_store = store.load_book(book_id) is not None
            if not existing_in_store:
                issues.append({
                    "type": "log_references_missing_book",
                    "index": idx,
                    "field": "book_id",
                    "book_id": book_id,
                    "message": (f"日志记录 {idx} 引用了书目 {book_id}，"
                                f"但该书目既不在快照的 books 列表中，也不存在于目标环境中"),
                    "blocks_other_blocks": False,
                    "blocks_current_block": False,
                })

    seen_log_ids = {}
    for idx, log in enumerate(valid_logs):
        log_id = log.get("log_id")
        if log_id is None or not log_id:
            continue
        if log_id in seen_log_ids:
            prev_idx = seen_log_ids[log_id]
            issues.append({
                "type": "duplicate_log_id_in_snapshot",
                "index": idx,
                "previous_index": prev_idx,
                "log_id": log_id,
                "message": f"快照中存在重复的 log_id: {log_id}（同时出现在记录 {prev_idx} 和 {idx}）",
                "blocks_other_blocks": False,
                "blocks_current_block": False,
            })
        else:
            seen_log_ids[log_id] = idx

    return issues


def _analyze_snapshot_conflicts(snapshot_data):
    conflicts = []
    validation_errors = []
    format_errors = {"books": [], "active_reservations": [], "blacklist": [], "logs": []}
    log_issues = []

    if not isinstance(snapshot_data, dict):
        return (None, [], ["快照数据格式错误，应为 JSON 对象"],
                format_errors, log_issues)

    if snapshot_data.get("version") != "2.0" or snapshot_data.get("type") != "full_snapshot":
        return (None, [], ["快照格式版本不支持，需要 version=2.0 且 type=full_snapshot"],
                format_errors, log_issues)

    books_data = snapshot_data.get("books", [])
    reservations_data = snapshot_data.get("active_reservations", [])
    blacklist_data = snapshot_data.get("blacklist", [])
    logs_data = snapshot_data.get("logs", [])

    if not isinstance(books_data, list):
        return (None, [], ["books 必须是列表"], format_errors, log_issues)
    if not isinstance(reservations_data, list):
        return (None, [], ["active_reservations 必须是列表"], format_errors, log_issues)
    if not isinstance(blacklist_data, list):
        return (None, [], ["blacklist 必须是列表"], format_errors, log_issues)
    if not isinstance(logs_data, list):
        return (None, [], ["logs 必须是列表"], format_errors, log_issues)

    for idx, book_data in enumerate(books_data):
        errors = _validate_snapshot_book(book_data, idx)
        if errors:
            validation_errors.extend(errors)
            for e in errors:
                format_errors["books"].append({
                    "index": idx,
                    "field": None,
                    "error_code": "book_format_error",
                    "message": e,
                    "blocks_other_blocks": False,
                    "blocks_current_block": True,
                })

    for idx, res_data in enumerate(reservations_data):
        errors = _validate_snapshot_reservation(res_data, idx)
        if errors:
            validation_errors.extend(errors)
            for e in errors:
                format_errors["active_reservations"].append({
                    "index": idx,
                    "field": None,
                    "error_code": "reservation_format_error",
                    "message": e,
                    "blocks_other_blocks": False,
                    "blocks_current_block": True,
                })

    for idx, bl_data in enumerate(blacklist_data):
        errors = _validate_snapshot_blacklist(bl_data, idx)
        if errors:
            validation_errors.extend(errors)
            for e in errors:
                format_errors["blacklist"].append({
                    "index": idx,
                    "field": None,
                    "error_code": "blacklist_format_error",
                    "message": e,
                    "blocks_other_blocks": False,
                    "blocks_current_block": True,
                })

    valid_logs = []
    for idx, log_data in enumerate(logs_data):
        errors = _validate_snapshot_log(log_data, idx)
        if errors:
            format_errors["logs"].extend(errors)
            validation_errors.extend([e["message"] for e in errors])
        else:
            valid_logs.append(log_data)

    seen_book_ids = set()
    for idx, book_data in enumerate(books_data):
        if format_errors["books"] and any(
            fe.get("index") == idx for fe in format_errors["books"]
        ):
            continue
        book_id = book_data["book_id"]
        if book_id in seen_book_ids:
            conflicts.append({
                "type": "duplicate_book_id_in_snapshot",
                "book_id": book_id,
                "section": "books",
                "index": idx,
                "message": f"快照中存在重复的 book_id: {book_id}",
            })
        seen_book_ids.add(book_id)

        existing_book = store.load_book(book_id)
        if existing_book:
            conflicts.append({
                "type": "duplicate_book_id",
                "book_id": book_id,
                "section": "books",
                "index": idx,
                "existing_config": existing_book,
                "import_config": {k: book_data[k] for k in ["title", "total_copies", "borrow_days", "retain_hours"]},
                "message": f"目标环境已存在书目 {book_id}",
            })

    book_ids_in_snapshot = {b["book_id"] for b in books_data}
    if format_errors["books"]:
        valid_book_ids = set()
        for idx, book_data in enumerate(books_data):
            has_error = any(fe.get("index") == idx for fe in format_errors["books"])
            if not has_error:
                valid_book_ids.add(book_data["book_id"])
        book_ids_in_snapshot = valid_book_ids

    log_issues = _check_log_order_and_references(valid_logs, book_ids_in_snapshot)
    if log_issues:
        validation_errors.extend([li["message"] for li in log_issues])

    seen_res_keys = set()
    for idx, res_data in enumerate(reservations_data):
        if format_errors["active_reservations"] and any(
            fe.get("index") == idx for fe in format_errors["active_reservations"]
        ):
            continue
        book_id = res_data["book_id"]
        reader_id = res_data["reader_id"]
        res_key = (book_id, reader_id)

        if book_id not in book_ids_in_snapshot:
            conflicts.append({
                "type": "missing_dependency",
                "book_id": book_id,
                "reader_id": reader_id,
                "section": "active_reservations",
                "index": idx,
                "message": f"预约记录引用了快照中不存在的书目 {book_id}",
            })
            continue

        if res_key in seen_res_keys:
            conflicts.append({
                "type": "duplicate_reservation_in_snapshot",
                "book_id": book_id,
                "reader_id": reader_id,
                "section": "active_reservations",
                "index": idx,
                "message": f"快照中存在重复预约：{book_id} / {reader_id}",
            })
        seen_res_keys.add(res_key)

        existing_reservations = store.load_active_reservations()
        for existing in existing_reservations:
            if existing["book_id"] == book_id and existing["reader_id"] == reader_id:
                conflicts.append({
                    "type": "duplicate_reservation",
                    "book_id": book_id,
                    "reader_id": reader_id,
                    "section": "active_reservations",
                    "index": idx,
                    "existing_reservation": {
                        "reservation_id": existing["reservation_id"],
                        "status": existing["status"],
                        "created_at": existing["created_at"],
                    },
                    "import_reservation": {
                        "reservation_id": res_data["reservation_id"],
                        "status": res_data["status"],
                        "created_at": res_data["created_at"],
                    },
                    "message": f"目标环境已存在活跃预约：{book_id} / {reader_id}",
                })
                break

    seen_reader_ids = set()
    for idx, bl_data in enumerate(blacklist_data):
        if format_errors["blacklist"] and any(
            fe.get("index") == idx for fe in format_errors["blacklist"]
        ):
            continue
        reader_id = bl_data["reader_id"]
        if reader_id in seen_reader_ids:
            conflicts.append({
                "type": "duplicate_blacklist_in_snapshot",
                "reader_id": reader_id,
                "section": "blacklist",
                "index": idx,
                "message": f"快照中存在重复黑名单：{reader_id}",
            })
        seen_reader_ids.add(reader_id)

        existing_bl = store.is_blacklisted(reader_id)
        if existing_bl:
            existing_list = store.load_blacklist()
            existing_entry = next((b for b in existing_list if b["reader_id"] == reader_id), None)
            if existing_entry and existing_entry.get("reason") != bl_data.get("reason"):
                conflicts.append({
                    "type": "blacklist_conflict",
                    "reader_id": reader_id,
                    "section": "blacklist",
                    "index": idx,
                    "existing_entry": existing_entry,
                    "import_entry": bl_data,
                    "message": f"目标环境已存在黑名单 {reader_id}，但原因不同",
                })
            elif existing_entry:
                conflicts.append({
                    "type": "duplicate_blacklist",
                    "reader_id": reader_id,
                    "section": "blacklist",
                    "index": idx,
                    "existing_entry": existing_entry,
                    "import_entry": bl_data,
                    "message": f"目标环境已存在黑名单 {reader_id}",
                })

    return ({
        "books": books_data,
        "active_reservations": reservations_data,
        "blacklist": blacklist_data,
        "logs": logs_data,
        "book_ids_in_snapshot": book_ids_in_snapshot,
        "seen_book_ids": seen_book_ids,
        "seen_res_keys": seen_res_keys,
        "seen_reader_ids": seen_reader_ids,
        "valid_log_count": len(valid_logs),
    }, conflicts, None, format_errors, log_issues)


def _build_snapshot_report(parsed, conflicts, errors, format_errors, log_issues):
    result = {
        "dry_run": True,
        "can_import": False,
        "summary": {},
        "details": {
            "books": {
                "will_add": [],
                "will_skip": [],
                "will_block": [],
                "conflicts": [],
                "missing_dependencies": [],
                "format_errors": [],
                "issues": [],
            },
            "active_reservations": {
                "will_add": [],
                "will_skip": [],
                "will_block": [],
                "conflicts": [],
                "missing_dependencies": [],
                "format_errors": [],
                "issues": [],
            },
            "blacklist": {
                "will_add": [],
                "will_skip": [],
                "will_block": [],
                "conflicts": [],
                "missing_dependencies": [],
                "format_errors": [],
                "issues": [],
            },
            "logs": {
                "will_add": [],
                "will_skip": [],
                "will_block": [],
                "conflicts": [],
                "missing_dependencies": [],
                "format_errors": [],
                "issues": [],
            },
        },
    }

    for sec in ["books", "active_reservations", "blacklist", "logs"]:
        result["details"][sec]["format_errors"] = format_errors.get(sec, [])
    result["details"]["logs"]["issues"] = log_issues if log_issues else []

    if errors and parsed is None:
        total_fe = sum(len(v) for v in format_errors.values()) + (len(log_issues) if log_issues else 0)
        result["summary"] = {
            "status": "format_error",
            "total_format_errors": total_fe,
            "total_conflicts": 0,
            "total_will_add": 0,
            "total_will_skip": 0,
            "total_will_block": total_fe,
            "total_missing_dependencies": 0,
            "message": "快照顶层格式有误（非字典或版本号不对），无法进行完整预检",
        }
        return result

    books_data = parsed["books"]
    reservations_data = parsed["active_reservations"]
    blacklist_data = parsed["blacklist"]
    logs_data = parsed["logs"]
    book_ids_in_snapshot = parsed["book_ids_in_snapshot"]

    conflict_book_ids = set()
    for c in conflicts:
        if c["section"] == "books" and c["type"] in ("duplicate_book_id", "duplicate_book_id_in_snapshot"):
            conflict_book_ids.add(c["book_id"])

    bad_book_indices = {fe["index"] for fe in format_errors.get("books", [])}

    for idx, book in enumerate(books_data):
        if idx in bad_book_indices:
            fe_list = [fe for fe in format_errors.get("books", []) if fe.get("index") == idx]
            for fe in fe_list:
                result["details"]["books"]["will_block"].append({
                    "index": idx,
                    "book_id": book.get("book_id") if isinstance(book, dict) else None,
                    "reason": fe.get("message", ""),
                    "error_code": fe.get("error_code"),
                })
            continue
        book_id = book["book_id"]
        if book_id in conflict_book_ids:
            c_list = [c for c in conflicts if c["section"] == "books" and c.get("book_id") == book_id]
            for c in c_list:
                result["details"]["books"]["will_skip"].append({
                    "index": idx,
                    "book_id": book_id,
                    "reason": c.get("message", ""),
                    "conflict_type": c.get("type"),
                })
            continue
        result["details"]["books"]["will_add"].append({
            "book_id": book_id,
            "title": book["title"],
            "total_copies": book["total_copies"],
            "borrow_days": book["borrow_days"],
            "retain_hours": book["retain_hours"],
        })

    conflict_res_keys = set()
    missing_dep_res = []
    for c in conflicts:
        if c["section"] == "active_reservations":
            if c["type"] == "missing_dependency":
                missing_dep_res.append(c)
            else:
                conflict_res_keys.add((c["book_id"], c["reader_id"]))

    bad_res_indices = {fe["index"] for fe in format_errors.get("active_reservations", [])}

    for idx, res in enumerate(reservations_data):
        if idx in bad_res_indices:
            fe_list = [fe for fe in format_errors.get("active_reservations", []) if fe.get("index") == idx]
            for fe in fe_list:
                result["details"]["active_reservations"]["will_block"].append({
                    "index": idx,
                    "reader_id": res.get("reader_id") if isinstance(res, dict) else None,
                    "reason": fe.get("message", ""),
                    "error_code": fe.get("error_code"),
                })
            continue
        res_key = (res["book_id"], res["reader_id"])
        if res["book_id"] not in book_ids_in_snapshot:
            miss_list = [c for c in conflicts if c["section"] == "active_reservations"
                         and c["type"] == "missing_dependency"
                         and c.get("book_id") == res["book_id"]
                         and c.get("reader_id") == res["reader_id"]]
            for m in miss_list:
                result["details"]["active_reservations"]["will_skip"].append({
                    "index": idx,
                    "reader_id": res["reader_id"],
                    "book_id": res["book_id"],
                    "reason": m.get("message", ""),
                    "conflict_type": "missing_dependency",
                })
            continue
        if res_key in conflict_res_keys:
            c_list = [c for c in conflicts if c["section"] == "active_reservations"
                      and c.get("book_id") == res["book_id"]
                      and c.get("reader_id") == res["reader_id"]]
            for c in c_list:
                result["details"]["active_reservations"]["will_skip"].append({
                    "index": idx,
                    "reader_id": res["reader_id"],
                    "book_id": res["book_id"],
                    "reason": c.get("message", ""),
                    "conflict_type": c.get("type"),
                })
            continue
        result["details"]["active_reservations"]["will_add"].append({
            "reservation_id": res["reservation_id"],
            "book_id": res["book_id"],
            "reader_id": res["reader_id"],
            "status": res["status"],
            "created_at": res["created_at"],
        })

    conflict_reader_ids = set()
    for c in conflicts:
        if c["section"] == "blacklist":
            conflict_reader_ids.add(c["reader_id"])

    bad_bl_indices = {fe["index"] for fe in format_errors.get("blacklist", [])}

    for idx, bl in enumerate(blacklist_data):
        if idx in bad_bl_indices:
            fe_list = [fe for fe in format_errors.get("blacklist", []) if fe.get("index") == idx]
            for fe in fe_list:
                result["details"]["blacklist"]["will_block"].append({
                    "index": idx,
                    "reader_id": bl.get("reader_id") if isinstance(bl, dict) else None,
                    "reason": fe.get("message", ""),
                    "error_code": fe.get("error_code"),
                })
            continue
        reader_id = bl["reader_id"]
        if reader_id in conflict_reader_ids:
            c_list = [c for c in conflicts if c["section"] == "blacklist" and c.get("reader_id") == reader_id]
            for c in c_list:
                result["details"]["blacklist"]["will_skip"].append({
                    "index": idx,
                    "reader_id": reader_id,
                    "reason": c.get("message", ""),
                    "conflict_type": c.get("type"),
                })
            continue
        result["details"]["blacklist"]["will_add"].append({
            "reader_id": reader_id,
            "reason": bl.get("reason", ""),
            "added_at": bl.get("added_at", ""),
        })

    bad_log_indices = {fe["index"] for fe in format_errors.get("logs", [])}
    issue_log_ids = set()
    for iss in (log_issues or []):
        if iss.get("index") is not None:
            issue_log_ids.add(iss["index"])

    for idx, log in enumerate(logs_data):
        if idx in bad_log_indices:
            fe_list = [fe for fe in format_errors.get("logs", []) if fe.get("index") == idx]
            for fe in fe_list:
                result["details"]["logs"]["will_block"].append({
                    "index": idx,
                    "log_id": log.get("log_id") if isinstance(log, dict) else None,
                    "reason": fe.get("message", ""),
                    "error_code": fe.get("error_code"),
                })
            continue
        log_entry = {
            "log_id": log.get("log_id", "(auto-generated)"),
            "action": log.get("action", "unknown"),
            "timestamp": log.get("timestamp", ""),
            "book_id": log.get("book_id"),
            "reader_id": log.get("reader_id"),
        }
        if idx in issue_log_ids:
            iss_list = [iss for iss in (log_issues or []) if iss.get("index") == idx]
            result["details"]["logs"]["will_add"].append(log_entry)
            for iss in iss_list:
                result["details"]["logs"]["will_skip"].append({
                    "index": idx,
                    "log_id": log.get("log_id"),
                    "reason": iss.get("message", ""),
                    "issue_type": iss.get("type"),
                    "note": "非阻断问题，仍可导入，建议关注",
                })
        else:
            result["details"]["logs"]["will_add"].append(log_entry)

    for c in conflicts:
        section = c["section"]
        if c["type"] == "missing_dependency":
            result["details"][section]["missing_dependencies"].append(c)
        else:
            result["details"][section]["conflicts"].append(c)

    total_will_add = (
        len(result["details"]["books"]["will_add"]) +
        len(result["details"]["active_reservations"]["will_add"]) +
        len(result["details"]["blacklist"]["will_add"]) +
        len(result["details"]["logs"]["will_add"])
    )
    total_will_skip = (
        len(result["details"]["books"]["will_skip"]) +
        len(result["details"]["active_reservations"]["will_skip"]) +
        len(result["details"]["blacklist"]["will_skip"]) +
        len(result["details"]["logs"]["will_skip"])
    )
    total_will_block = (
        len(result["details"]["books"]["will_block"]) +
        len(result["details"]["active_reservations"]["will_block"]) +
        len(result["details"]["blacklist"]["will_block"]) +
        len(result["details"]["logs"]["will_block"])
    )
    total_conflicts = sum(len(result["details"][s]["conflicts"]) for s in result["details"])
    total_missing = sum(len(result["details"][s]["missing_dependencies"]) for s in result["details"])
    total_format_errors = sum(len(result["details"][s]["format_errors"]) for s in result["details"])
    total_issues = sum(len(result["details"][s].get("issues", [])) for s in result["details"])
    total_all_errors = total_format_errors + total_issues

    can_import = total_conflicts == 0 and total_missing == 0 and total_format_errors == 0

    if can_import and total_issues == 0:
        status = "ready"
        message = "预检通过，可以安全导入"
    elif total_format_errors > 0:
        status = "format_error"
        message = "存在格式错误，需先修正数据格式"
    elif total_conflicts > 0:
        status = "has_conflicts"
        message = "存在冲突，需解决冲突后再导入"
    elif total_missing > 0:
        status = "missing_dependency"
        message = "存在缺失依赖，需补充相关数据或调整导入内容"
    else:
        status = "has_warnings"
        message = "校验通过（有非阻断告警），可导入，但建议关注日志问题"

    result["can_import"] = can_import
    result["summary"] = {
        "status": status,
        "message": message,
        "total_will_add": total_will_add,
        "total_will_skip": total_will_skip,
        "total_will_block": total_will_block,
        "total_conflicts": total_conflicts,
        "total_missing_dependencies": total_missing,
        "total_format_errors": total_format_errors,
        "total_log_issues": total_issues,
        "breakdown": {
            "books": {
                "will_add": len(result["details"]["books"]["will_add"]),
                "will_skip": len(result["details"]["books"]["will_skip"]),
                "will_block": len(result["details"]["books"]["will_block"]),
                "conflicts": len(result["details"]["books"]["conflicts"]),
                "missing_dependencies": len(result["details"]["books"]["missing_dependencies"]),
                "format_errors": len(result["details"]["books"]["format_errors"]),
                "issues": len(result["details"]["books"].get("issues", [])),
            },
            "active_reservations": {
                "will_add": len(result["details"]["active_reservations"]["will_add"]),
                "will_skip": len(result["details"]["active_reservations"]["will_skip"]),
                "will_block": len(result["details"]["active_reservations"]["will_block"]),
                "conflicts": len(result["details"]["active_reservations"]["conflicts"]),
                "missing_dependencies": len(result["details"]["active_reservations"]["missing_dependencies"]),
                "format_errors": len(result["details"]["active_reservations"]["format_errors"]),
                "issues": len(result["details"]["active_reservations"].get("issues", [])),
            },
            "blacklist": {
                "will_add": len(result["details"]["blacklist"]["will_add"]),
                "will_skip": len(result["details"]["blacklist"]["will_skip"]),
                "will_block": len(result["details"]["blacklist"]["will_block"]),
                "conflicts": len(result["details"]["blacklist"]["conflicts"]),
                "missing_dependencies": len(result["details"]["blacklist"]["missing_dependencies"]),
                "format_errors": len(result["details"]["blacklist"]["format_errors"]),
                "issues": len(result["details"]["blacklist"].get("issues", [])),
            },
            "logs": {
                "will_add": len(result["details"]["logs"]["will_add"]),
                "will_skip": len(result["details"]["logs"]["will_skip"]),
                "will_block": len(result["details"]["logs"]["will_block"]),
                "conflicts": len(result["details"]["logs"]["conflicts"]),
                "missing_dependencies": len(result["details"]["logs"]["missing_dependencies"]),
                "format_errors": len(result["details"]["logs"]["format_errors"]),
                "issues": len(result["details"]["logs"].get("issues", [])),
            },
        },
        "queue_order_check": _check_queue_order(reservations_data, book_ids_in_snapshot),
        "availability_check": _check_availability(books_data, reservations_data),
    }

    return result


def precheck_snapshot(snapshot_data):
    try:
        parsed, conflicts, errors, format_errors, log_issues = _analyze_snapshot_conflicts(snapshot_data)
    except Exception as e:
        error_result = {
            "dry_run": True,
            "can_import": False,
            "summary": {
                "status": "internal_error",
                "total_format_errors": 1,
                "total_conflicts": 0,
                "total_will_add": 0,
                "total_will_skip": 0,
                "total_will_block": 1,
                "total_missing_dependencies": 0,
                "message": f"预检过程中发生内部错误（已捕获，不影响服务稳定性）：{str(e)}",
            },
            "details": {
                "books": {"will_add": [], "will_skip": [], "will_block": [],
                          "conflicts": [], "missing_dependencies": [], "format_errors": [
                    {"index": None, "field": None, "error_code": "precheck_internal_error",
                     "message": f"内部异常: {str(e)}", "blocks_other_blocks": True, "blocks_current_block": True}
                ], "issues": []},
                "active_reservations": {"will_add": [], "will_skip": [], "will_block": [],
                                        "conflicts": [], "missing_dependencies": [], "format_errors": [], "issues": []},
                "blacklist": {"will_add": [], "will_skip": [], "will_block": [],
                              "conflicts": [], "missing_dependencies": [], "format_errors": [], "issues": []},
                "logs": {"will_add": [], "will_skip": [], "will_block": [],
                         "conflicts": [], "missing_dependencies": [], "format_errors": [], "issues": []},
            },
        }
        return error_result, None

    report = _build_snapshot_report(parsed, conflicts, errors, format_errors, log_issues)
    return report, None


def _check_queue_order(reservations_data, book_ids_in_snapshot):
    result = {}
    for book_id in book_ids_in_snapshot:
        book_res = [r for r in reservations_data if r["book_id"] == book_id]
        book_res_sorted = sorted(book_res, key=lambda r: r["created_at"])
        waiting = [r for r in book_res_sorted if r["status"] == "waiting"]
        result[book_id] = {
            "total_active": len(book_res),
            "waiting_count": len(waiting),
            "order_by_created_at": [
                {"reader_id": r["reader_id"], "status": r["status"], "created_at": r["created_at"]}
                for r in book_res_sorted
            ],
            "is_ordered_by_created_at": True,
        }
    return result


def _check_availability(books_data, reservations_data):
    result = {}
    book_map = {b["book_id"]: b for b in books_data}
    for book_id, book in book_map.items():
        book_res = [r for r in reservations_data if r["book_id"] == book_id]
        borrowed = sum(1 for r in book_res if r["status"] == "borrowed")
        to_pick = sum(1 for r in book_res if r["status"] == "available")
        waiting = sum(1 for r in book_res if r["status"] == "waiting")
        available_copies = book["total_copies"] - borrowed - to_pick
        result[book_id] = {
            "total_copies": book["total_copies"],
            "borrowed": borrowed,
            "to_pick": to_pick,
            "waiting": waiting,
            "available_copies": max(available_copies, 0),
            "has_overflow": available_copies < 0,
        }
    return result


def import_snapshot(snapshot_data, dry_run=False):
    try:
        parsed, conflicts, errors, format_errors, log_issues = _analyze_snapshot_conflicts(snapshot_data)
    except Exception as e:
        return None, None, [f"快照数据解析异常: {str(e)}"], None

    report = _build_snapshot_report(parsed, conflicts, errors, format_errors, log_issues)

    total_format_errors = sum(len(v) for v in format_errors.values()) if format_errors else 0

    if errors and parsed is None:
        if dry_run:
            return None, None, errors, report
        return None, None, errors, None

    if total_format_errors > 0:
        format_err_messages = []
        for sec, fe_list in format_errors.items():
            for fe in fe_list:
                format_err_messages.append(f"[{sec}] {fe.get('message', str(fe))}")
        if dry_run:
            return None, None, format_err_messages, report
        return None, None, format_err_messages, None

    if conflicts:
        if not dry_run:
            _log("import_snapshot", False,
                 detail=f"快照导入发现 {len(conflicts)} 个冲突，已中止")
            return None, conflicts, None, None
        return None, conflicts, None, report

    books_data = parsed["books"]
    reservations_data = parsed["active_reservations"]
    blacklist_data = parsed["blacklist"]
    logs_data = parsed["logs"]

    counts = {
        "books": len(books_data),
        "active_reservations": len(reservations_data),
        "blacklist": len(blacklist_data),
        "logs": len(logs_data),
    }

    if dry_run:
        return counts, None, None, report

    with store._lock:
        backup = store.backup_all()

        try:
            existing_books = store.list_books()
            existing_book_ids = {b["book_id"] for b in existing_books}
            import_book_ids = {b["book_id"] for b in books_data}
            overlap = existing_book_ids & import_book_ids
            if overlap:
                raise RuntimeError(f"导入前二次校验发现冲突书目: {overlap}")

            existing_active = store.load_active_reservations()
            existing_res_keys = {(r["book_id"], r["reader_id"]) for r in existing_active}
            import_res_keys = {(r["book_id"], r["reader_id"]) for r in reservations_data}
            res_overlap = existing_res_keys & import_res_keys
            if res_overlap:
                raise RuntimeError(f"导入前二次校验发现冲突预约: {res_overlap}")

            existing_bl = store.load_blacklist()
            existing_bl_ids = {b["reader_id"] for b in existing_bl}
            import_bl_ids = {b["reader_id"] for b in blacklist_data}
            bl_overlap = existing_bl_ids & import_bl_ids
            if bl_overlap:
                raise RuntimeError(f"导入前二次校验发现冲突黑名单: {bl_overlap}")

            all_books = existing_books + books_data
            store.save_all_books(all_books)

            all_reservations = store.load_reservations() + reservations_data
            store.save_all_reservations(all_reservations)

            all_blacklist = existing_bl + blacklist_data
            store.save_all_blacklist(all_blacklist)

            all_logs = store.load_logs()
            for log_entry in logs_data:
                if not isinstance(log_entry, dict):
                    raise RuntimeError(f"日志记录不是字典: {type(log_entry).__name__}")
                entry = dict(log_entry)
                if "log_id" not in entry or not entry.get("log_id"):
                    entry["log_id"] = str(uuid.uuid4())
                if "timestamp" not in entry or not entry.get("timestamp"):
                    entry["timestamp"] = _now()
                all_logs.append(entry)
            store.save_all_logs(all_logs)

        except Exception as e:
            store.restore_all(backup)
            _log("import_snapshot", False,
                 detail=f"快照导入异常，已完整回滚: {str(e)}")
            return None, [{
                "type": "snapshot_import_error",
                "message": f"导入过程出错，已完整回滚所有数据: {str(e)}",
            }], None, None

    _log("import_snapshot", True,
         detail=f"快照导入成功：{counts}")
    return counts, None, None, None

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

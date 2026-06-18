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
            detail = f"读者 {reader_id} 在等待队列中，尚未轮到借出，不可越过队首"
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
    snapshot = {
        "export_time": _now(),
        "book": book,
        "queue": queue,
        "total_in_queue": len(queue),
    }
    return snapshot, None

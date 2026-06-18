import json
import os
import threading

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

_lock = threading.RLock()


def _ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _path(name):
    return os.path.join(DATA_DIR, f"{name}.json")


def load(name):
    _ensure_dir()
    p = _path(name)
    if not os.path.exists(p):
        return []
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def save(name, data):
    _ensure_dir()
    p = _path(name)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_book(book_id):
    books = load("books")
    for b in books:
        if b["book_id"] == book_id:
            return b
    return None


def save_book(book):
    with _lock:
        books = load("books")
        for i, b in enumerate(books):
            if b["book_id"] == book["book_id"]:
                books[i] = book
                save("books", books)
                return
        books.append(book)
        save("books", books)


def delete_book(book_id):
    with _lock:
        books = load("books")
        books = [b for b in books if b["book_id"] != book_id]
        save("books", books)


def list_books():
    return load("books")


def load_reservations():
    return load("reservations")


def save_reservations(reservations):
    save("reservations", reservations)


def add_reservation(reservation):
    with _lock:
        reservations = load_reservations()
        reservations.append(reservation)
        save_reservations(reservations)


def update_reservation(reservation_id, updates):
    with _lock:
        reservations = load_reservations()
        for i, r in enumerate(reservations):
            if r["reservation_id"] == reservation_id:
                reservations[i].update(updates)
                save_reservations(reservations)
                return reservations[i]
    return None


def get_reservation(reservation_id):
    reservations = load_reservations()
    for r in reservations:
        if r["reservation_id"] == reservation_id:
            return r
    return None


def load_blacklist():
    return load("blacklist")


def save_blacklist(blacklist):
    save("blacklist", blacklist)


def is_blacklisted(reader_id):
    blacklist = load_blacklist()
    return any(b["reader_id"] == reader_id for b in blacklist)


def add_to_blacklist(reader_id, reason):
    with _lock:
        blacklist = load_blacklist()
        for b in blacklist:
            if b["reader_id"] == reader_id:
                return False
        blacklist.append({"reader_id": reader_id, "reason": reason, "added_at": _now()})
        save_blacklist(blacklist)
        return True


def remove_from_blacklist(reader_id):
    with _lock:
        blacklist = load_blacklist()
        new_list = [b for b in blacklist if b["reader_id"] != reader_id]
        if len(new_list) == len(blacklist):
            return False
        save_blacklist(new_list)
        return True


def append_log(log_entry):
    with _lock:
        logs = load("logs")
        logs.append(log_entry)
        save("logs", logs)


def load_logs():
    return load("logs")


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()

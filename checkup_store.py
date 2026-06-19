import json
import os
import threading
import hashlib

CHECKUP_BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "checkup")
CHECKUP_RECORDS_FILE = os.path.join(CHECKUP_BASE_DIR, "records.json")
CHECKUP_LOGS_FILE = os.path.join(CHECKUP_BASE_DIR, "logs.json")
CHECKUP_CONCLUSIONS_FILE = os.path.join(CHECKUP_BASE_DIR, "conclusions.json")

_global_lock = threading.RLock()


def _ensure_dir():
    os.makedirs(CHECKUP_BASE_DIR, exist_ok=True)


def _load_json(path):
    _ensure_dir()
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(path, data):
    _ensure_dir()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def compute_snapshot_hash(snapshot_data):
    content = json.dumps(snapshot_data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def compute_config_signature():
    import store as prod_store
    books = prod_store.list_books()
    books_sorted = sorted(books, key=lambda b: b.get("book_id", ""))
    content = json.dumps(books_sorted, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def load_records():
    with _global_lock:
        return _load_json(CHECKUP_RECORDS_FILE)


def save_records(records):
    with _global_lock:
        _save_json(CHECKUP_RECORDS_FILE, records)


def get_record(record_id):
    records = load_records()
    for r in records:
        if r["record_id"] == record_id:
            return dict(r)
    return None


def add_record(record):
    with _global_lock:
        records = load_records()
        records.append(record)
        _save_json(CHECKUP_RECORDS_FILE, records)


def update_record(record_id, updates):
    with _global_lock:
        records = load_records()
        for i, r in enumerate(records):
            if r["record_id"] == record_id:
                records[i].update(updates)
                _save_json(CHECKUP_RECORDS_FILE, records)
                return records[i]
        return None


def load_logs():
    with _global_lock:
        return _load_json(CHECKUP_LOGS_FILE)


def append_log(log_entry):
    with _global_lock:
        logs = load_logs()
        logs.append(log_entry)
        _save_json(CHECKUP_LOGS_FILE, logs)


def load_conclusions():
    with _global_lock:
        return _load_json(CHECKUP_CONCLUSIONS_FILE)


def save_conclusion(conclusion):
    with _global_lock:
        conclusions = load_conclusions()
        conclusions.append(conclusion)
        _save_json(CHECKUP_CONCLUSIONS_FILE, conclusions)


def get_conclusion(record_id):
    conclusions = load_conclusions()
    for c in conclusions:
        if c["record_id"] == record_id:
            return dict(c)
    return None


def update_conclusion(record_id, updates):
    with _global_lock:
        conclusions = load_conclusions()
        for i, c in enumerate(conclusions):
            if c["record_id"] == record_id:
                conclusions[i].update(updates)
                _save_json(CHECKUP_CONCLUSIONS_FILE, conclusions)
                return conclusions[i]
        return None

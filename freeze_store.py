import json
import os
import threading
import hashlib

FREEZE_BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "freeze")
FREEZE_ORDERS_FILE = os.path.join(FREEZE_BASE_DIR, "orders.json")
FREEZE_AUDIT_LOGS_FILE = os.path.join(FREEZE_BASE_DIR, "audit_logs.json")
FREEZE_CONFIG_FILE = os.path.join(FREEZE_BASE_DIR, "config.json")
FREEZE_SNAPSHOTS_DIR = os.path.join(FREEZE_BASE_DIR, "snapshots")

_global_lock = threading.RLock()


def _ensure_dir():
    os.makedirs(FREEZE_BASE_DIR, exist_ok=True)
    os.makedirs(FREEZE_SNAPSHOTS_DIR, exist_ok=True)


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


def compute_config_signature():
    import store as prod_store
    books = prod_store.list_books()
    books_sorted = sorted(books, key=lambda b: b.get("book_id", ""))
    content = json.dumps(books_sorted, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def load_config():
    _ensure_dir()
    if not os.path.exists(FREEZE_CONFIG_FILE):
        default_config = {
            "enabled": True,
            "version": "1.0",
            "updated_at": None,
        }
        _save_json(FREEZE_CONFIG_FILE, default_config)
        return default_config
    with open(FREEZE_CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(config):
    _ensure_dir()
    with open(FREEZE_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def update_config_enabled(enabled, operator=None):
    with _global_lock:
        config = load_config()
        config["enabled"] = enabled
        from datetime import datetime, timezone
        config["updated_at"] = datetime.now(timezone.utc).isoformat()
        if operator:
            config["updated_by"] = operator
        save_config(config)
        return config


def load_orders():
    with _global_lock:
        return _load_json(FREEZE_ORDERS_FILE)


def save_orders(orders):
    with _global_lock:
        _save_json(FREEZE_ORDERS_FILE, orders)


def get_order(freeze_id):
    orders = load_orders()
    for o in orders:
        if o["freeze_id"] == freeze_id:
            return dict(o)
    return None


def add_order(order):
    with _global_lock:
        orders = load_orders()
        orders.append(order)
        _save_json(FREEZE_ORDERS_FILE, orders)


def update_order(freeze_id, updates):
    with _global_lock:
        orders = load_orders()
        for i, o in enumerate(orders):
            if o["freeze_id"] == freeze_id:
                orders[i].update(updates)
                _save_json(FREEZE_ORDERS_FILE, orders)
                return orders[i]
        return None


def load_audit_logs():
    with _global_lock:
        return _load_json(FREEZE_AUDIT_LOGS_FILE)


def append_audit_log(log_entry):
    with _global_lock:
        logs = load_audit_logs()
        logs.append(log_entry)
        _save_json(FREEZE_AUDIT_LOGS_FILE, logs)


def save_snapshot(freeze_id, snapshot_type, snapshot_data):
    _ensure_dir()
    snap_path = os.path.join(FREEZE_SNAPSHOTS_DIR, f"{freeze_id}_{snapshot_type}.json")
    with open(snap_path, "w", encoding="utf-8") as f:
        json.dump(snapshot_data, f, ensure_ascii=False, indent=2)
    return snap_path


def load_snapshot(freeze_id, snapshot_type):
    snap_path = os.path.join(FREEZE_SNAPSHOTS_DIR, f"{freeze_id}_{snapshot_type}.json")
    if not os.path.exists(snap_path):
        return None
    with open(snap_path, "r", encoding="utf-8") as f:
        return json.load(f)


def find_active_freeze_by_book(book_id):
    orders = load_orders()
    for o in orders:
        if o.get("book_id") == book_id and o.get("status") in ("pending", "frozen", "restoring"):
            return dict(o)
    return None


def list_active_freezes():
    orders = load_orders()
    return [o for o in orders if o.get("status") in ("pending", "frozen", "restoring")]

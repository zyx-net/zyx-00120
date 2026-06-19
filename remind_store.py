import json
import os
import threading
import hashlib

REMIND_BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "remind")
REMIND_ORDERS_FILE = os.path.join(REMIND_BASE_DIR, "orders.json")
REMIND_LOGS_FILE = os.path.join(REMIND_BASE_DIR, "logs.json")

_global_lock = threading.RLock()


def _ensure_dir():
    os.makedirs(REMIND_BASE_DIR, exist_ok=True)


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


def load_orders():
    with _global_lock:
        return _load_json(REMIND_ORDERS_FILE)


def save_orders(orders):
    with _global_lock:
        _save_json(REMIND_ORDERS_FILE, orders)


def get_order(order_id):
    orders = load_orders()
    for o in orders:
        if o["order_id"] == order_id:
            return dict(o)
    return None


def add_order(order):
    with _global_lock:
        orders = load_orders()
        orders.append(order)
        _save_json(REMIND_ORDERS_FILE, orders)


def update_order(order_id, updates):
    with _global_lock:
        orders = load_orders()
        for i, o in enumerate(orders):
            if o["order_id"] == order_id:
                orders[i].update(updates)
                _save_json(REMIND_ORDERS_FILE, orders)
                return orders[i]
        return None


def load_logs():
    with _global_lock:
        return _load_json(REMIND_LOGS_FILE)


def append_log(log_entry):
    with _global_lock:
        logs = load_logs()
        logs.append(log_entry)
        _save_json(REMIND_LOGS_FILE, logs)

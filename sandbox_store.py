import json
import os
import threading
import hashlib
import shutil

SANDBOX_BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sandbox")
SANDBOX_META_FILE = os.path.join(SANDBOX_BASE_DIR, "sandboxes.json")
DATA_FILES = ["books", "reservations", "blacklist", "logs", "batches"]

_global_lock = threading.RLock()
_sandbox_locks = {}


def _ensure_base_dir():
    os.makedirs(SANDBOX_BASE_DIR, exist_ok=True)


def _sandbox_dir(sandbox_id):
    return os.path.join(SANDBOX_BASE_DIR, sandbox_id)


def _sandbox_meta_path():
    return SANDBOX_META_FILE


def _get_sandbox_lock(sandbox_id):
    with _global_lock:
        if sandbox_id not in _sandbox_locks:
            _sandbox_locks[sandbox_id] = threading.RLock()
        return _sandbox_locks[sandbox_id]


def _snapshot_hash(snapshot_data):
    content = json.dumps(snapshot_data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _load_meta():
    _ensure_base_dir()
    p = _sandbox_meta_path()
    if not os.path.exists(p):
        return []
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_meta(meta_list):
    _ensure_base_dir()
    p = _sandbox_meta_path()
    with open(p, "w", encoding="utf-8") as f:
        json.dump(meta_list, f, ensure_ascii=False, indent=2)


def _update_sandbox_in_meta(sandbox_id, updates):
    with _global_lock:
        meta = _load_meta()
        for i, s in enumerate(meta):
            if s["sandbox_id"] == sandbox_id:
                meta[i].update(updates)
                _save_meta(meta)
                return meta[i]
        return None


def _remove_sandbox_from_meta(sandbox_id):
    with _global_lock:
        meta = _load_meta()
        new_meta = [s for s in meta if s["sandbox_id"] != sandbox_id]
        if len(new_meta) != len(meta):
            _save_meta(new_meta)
            return True
        return False


def _ensure_sandbox_dir(sandbox_id):
    d = _sandbox_dir(sandbox_id)
    os.makedirs(d, exist_ok=True)
    return d


def _data_path(sandbox_id, name):
    return os.path.join(_sandbox_dir(sandbox_id), f"{name}.json")


def list_sandboxes():
    with _global_lock:
        meta = _load_meta()
        return list(meta)


def get_sandbox_meta(sandbox_id):
    with _global_lock:
        meta = _load_meta()
        for s in meta:
            if s["sandbox_id"] == sandbox_id:
                return dict(s)
        return None


def create_sandbox_dir(sandbox_id, snapshot_data, name=None):
    with _global_lock:
        _ensure_base_dir()
        d = _ensure_sandbox_dir(sandbox_id)
        for name_file in DATA_FILES:
            p = _data_path(sandbox_id, name_file)
            if not os.path.exists(p):
                with open(p, "w", encoding="utf-8") as f:
                    json.dump([], f)
        drill_path = os.path.join(d, "drill_results.json")
        if not os.path.exists(drill_path):
            with open(drill_path, "w", encoding="utf-8") as f:
                json.dump({}, f)
        return d


def save_sandbox_meta(sandbox_record):
    with _global_lock:
        meta = _load_meta()
        for i, s in enumerate(meta):
            if s["sandbox_id"] == sandbox_record["sandbox_id"]:
                meta[i] = sandbox_record
                _save_meta(meta)
                return
        meta.append(sandbox_record)
        _save_meta(meta)


def load_sandbox_data(sandbox_id, name):
    with _get_sandbox_lock(sandbox_id):
        p = _data_path(sandbox_id, name)
        if not os.path.exists(p):
            return []
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)


def save_sandbox_data(sandbox_id, name, data):
    with _get_sandbox_lock(sandbox_id):
        _ensure_sandbox_dir(sandbox_id)
        p = _data_path(sandbox_id, name)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def load_drill_results(sandbox_id):
    with _get_sandbox_lock(sandbox_id):
        d = _sandbox_dir(sandbox_id)
        p = os.path.join(d, "drill_results.json")
        if not os.path.exists(p):
            return {}
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)


def save_drill_results(sandbox_id, results):
    with _get_sandbox_lock(sandbox_id):
        _ensure_sandbox_dir(sandbox_id)
        d = _sandbox_dir(sandbox_id)
        p = os.path.join(d, "drill_results.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)


def update_drill_results(sandbox_id, updates):
    with _get_sandbox_lock(sandbox_id):
        results = load_drill_results(sandbox_id)
        results.update(updates)
        save_drill_results(sandbox_id, results)
        return results


def backup_sandbox_all(sandbox_id):
    with _get_sandbox_lock(sandbox_id):
        backup = {}
        for name in DATA_FILES:
            backup[name] = load_sandbox_data(sandbox_id, name)
        return backup


def restore_sandbox_all(sandbox_id, backup):
    with _get_sandbox_lock(sandbox_id):
        for name in DATA_FILES:
            if name in backup:
                save_sandbox_data(sandbox_id, name, backup[name])


def destroy_sandbox(sandbox_id):
    with _global_lock:
        removed = _remove_sandbox_from_meta(sandbox_id)
        d = _sandbox_dir(sandbox_id)
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
        if sandbox_id in _sandbox_locks:
            del _sandbox_locks[sandbox_id]
        return removed


def get_sandbox_lock_obj(sandbox_id):
    return _get_sandbox_lock(sandbox_id)


def compute_snapshot_hash(snapshot_data):
    return _snapshot_hash(snapshot_data)


def compute_config_signature():
    import store as prod_store
    books = prod_store.list_books()
    books_sorted = sorted(books, key=lambda b: b.get("book_id", ""))
    content = json.dumps(books_sorted, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()

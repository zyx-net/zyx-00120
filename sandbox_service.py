import uuid
import json
from datetime import datetime, timezone

import sandbox_store
from service import (
    _validate_book_config,
    _check_book_numeric_ranges,
    _validate_snapshot_reservation,
    _validate_snapshot_blacklist,
    _validate_snapshot_log,
    _build_snapshot_report,
    _check_queue_order,
    _check_availability,
)

_ACTIVE_STATUSES = {"waiting", "available", "borrowed"}
_VALID_LOG_ACTIONS = {
    "add_book", "update_book", "delete_book",
    "reserve", "cancel", "checkout", "return",
    "promote", "expire",
    "blacklist_add", "blacklist_remove",
    "import_collection", "import_collection_dry_run", "import_book",
    "export_collection",
    "import_snapshot", "import_snapshot_dry_run", "export_snapshot", "precheck_snapshot",
    "rollback_batch",
}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _sandbox_load_book(sandbox_id, book_id):
    books = sandbox_store.load_sandbox_data(sandbox_id, "books")
    for b in books:
        if b["book_id"] == book_id:
            return b
    return None


def _sandbox_list_books(sandbox_id):
    return sandbox_store.load_sandbox_data(sandbox_id, "books")


def _sandbox_load_active_reservations(sandbox_id):
    reservations = sandbox_store.load_sandbox_data(sandbox_id, "reservations")
    return [r for r in reservations if r["status"] in _ACTIVE_STATUSES]


def _sandbox_load_blacklist(sandbox_id):
    return sandbox_store.load_sandbox_data(sandbox_id, "blacklist")


def _sandbox_is_blacklisted(sandbox_id, reader_id):
    bl = _sandbox_load_blacklist(sandbox_id)
    return any(b["reader_id"] == reader_id for b in bl)


def _check_sandbox_log_order_and_references(sandbox_id, valid_logs, book_ids_in_snapshot):
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
                                f"早于前一条记录 {prev_idx} 的 timestamp ({valid_logs[prev_idx].get('timestamp')})，时间顺序错乱"),
                    "blocks_other_blocks": False,
                    "blocks_current_block": False,
                })
            prev_ts = curr_ts
            prev_idx = idx

    for idx, log in enumerate(valid_logs):
        book_id = log.get("book_id")
        if book_id and book_id not in book_ids_in_snapshot:
            existing_in_sandbox = _sandbox_load_book(sandbox_id, book_id) is not None
            if not existing_in_sandbox:
                issues.append({
                    "type": "log_references_missing_book",
                    "index": idx,
                    "field": "book_id",
                    "book_id": book_id,
                    "message": (f"日志记录 {idx} 引用了书目 {book_id}，"
                                f"但该书目既不在快照的 books 列表中，也不存在于沙箱中"),
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


def _sandbox_analyze_conflicts(sandbox_id, snapshot_data):
    conflicts = []
    validation_errors = []
    format_errors = {"books": [], "active_reservations": [], "blacklist": [], "logs": []}
    log_issues = []

    if not isinstance(snapshot_data, dict):
        return (None, [], ["快照数据格式错误，应为 JSON 对象"], format_errors, log_issues)

    if snapshot_data.get("version") != "2.0" or snapshot_data.get("type") != "full_snapshot":
        return (None, [], ["快照格式版本不支持，需要 version=2.0 且 type=full_snapshot"], format_errors, log_issues)

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
        errors = _validate_book_config(book_data, idx)
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
        if format_errors["books"] and any(fe.get("index") == idx for fe in format_errors["books"]):
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

        existing_book = _sandbox_load_book(sandbox_id, book_id)
        if existing_book:
            conflicts.append({
                "type": "duplicate_book_id",
                "book_id": book_id,
                "section": "books",
                "index": idx,
                "existing_config": existing_book,
                "import_config": {k: book_data[k] for k in ["title", "total_copies", "borrow_days", "retain_hours"]},
                "message": f"沙箱中已存在书目 {book_id}",
            })
            continue

        conflicts.extend(_check_book_numeric_ranges(book_data, idx))

    _INVALID_BOOK_CONFLICT_TYPES = {
        "duplicate_book_id_in_snapshot", "duplicate_book_id",
        "invalid_copies", "invalid_borrow_days", "invalid_retain_hours",
    }
    invalid_book_indices = set()
    invalid_book_ids = set()
    for c in conflicts:
        if c["section"] == "books" and c["type"] in _INVALID_BOOK_CONFLICT_TYPES:
            if c.get("index") is not None:
                invalid_book_indices.add(c["index"])
            if c.get("book_id"):
                invalid_book_ids.add(c["book_id"])

    valid_book_ids = set()
    for idx, book_data in enumerate(books_data):
        has_format_error = any(fe.get("index") == idx for fe in format_errors["books"])
        has_conflict = idx in invalid_book_indices
        if not has_format_error and not has_conflict and isinstance(book_data, dict) and book_data.get("book_id"):
            valid_book_ids.add(book_data["book_id"])

    log_issues = _check_sandbox_log_order_and_references(sandbox_id, valid_logs, valid_book_ids)
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

        if book_id not in valid_book_ids:
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

        existing_reservations = _sandbox_load_active_reservations(sandbox_id)
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
                    "message": f"沙箱中已存在活跃预约：{book_id} / {reader_id}",
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

        existing_bl = _sandbox_is_blacklisted(sandbox_id, reader_id)
        if existing_bl:
            existing_list = _sandbox_load_blacklist(sandbox_id)
            existing_entry = next((b for b in existing_list if b["reader_id"] == reader_id), None)
            if existing_entry and existing_entry.get("reason") != bl_data.get("reason"):
                conflicts.append({
                    "type": "blacklist_conflict",
                    "reader_id": reader_id,
                    "section": "blacklist",
                    "index": idx,
                    "existing_entry": existing_entry,
                    "import_entry": bl_data,
                    "message": f"沙箱中已存在黑名单 {reader_id}，但原因不同",
                })
            elif existing_entry:
                conflicts.append({
                    "type": "duplicate_blacklist",
                    "reader_id": reader_id,
                    "section": "blacklist",
                    "index": idx,
                    "existing_entry": existing_entry,
                    "import_entry": bl_data,
                    "message": f"沙箱中已存在黑名单 {reader_id}",
                })

    return ({
        "books": books_data,
        "active_reservations": reservations_data,
        "blacklist": blacklist_data,
        "logs": logs_data,
        "book_ids_in_snapshot": valid_book_ids,
        "seen_book_ids": seen_book_ids,
        "seen_res_keys": seen_res_keys,
        "seen_reader_ids": seen_reader_ids,
        "valid_log_count": len(valid_logs),
    }, conflicts, None, format_errors, log_issues)


def _sandbox_log(sandbox_id, action, success, reader_id=None, book_id=None, detail=""):
    log_entry = {
        "log_id": str(uuid.uuid4()),
        "timestamp": _now(),
        "action": action,
        "reader_id": reader_id,
        "book_id": book_id,
        "detail": detail,
        "success": success,
    }
    logs = sandbox_store.load_sandbox_data(sandbox_id, "logs")
    logs.append(log_entry)
    sandbox_store.save_sandbox_data(sandbox_id, "logs", logs)
    return log_entry


def _set_sandbox_status(sandbox_id, status, extra_updates=None):
    updates = {"status": status, "updated_at": _now()}
    if extra_updates:
        updates.update(extra_updates)
    sandbox_store._update_sandbox_in_meta(sandbox_id, updates)
    return sandbox_store.get_sandbox_meta(sandbox_id)


def _check_sandbox_config_stale(sandbox_id):
    meta = sandbox_store.get_sandbox_meta(sandbox_id)
    if not meta:
        return False, None
    current_sig = sandbox_store.compute_config_signature()
    original_sig = meta.get("config_signature", "")
    if original_sig and current_sig != original_sig:
        return True, (original_sig, current_sig)
    return False, None


def create_sandbox(snapshot_data, name=None):
    if not isinstance(snapshot_data, dict):
        return None, "快照数据格式错误，应为 JSON 对象"
    if snapshot_data.get("version") != "2.0" or snapshot_data.get("type") != "full_snapshot":
        return None, "快照格式版本不支持，需要 version=2.0 且 type=full_snapshot"

    snapshot_hash = sandbox_store.compute_snapshot_hash(snapshot_data)

    with sandbox_store._global_lock:
        existing = sandbox_store.list_sandboxes()
        for s in existing:
            if s.get("snapshot_hash") == snapshot_hash and s.get("status") != "destroyed":
                return None, (f"已存在相同快照的演练沙箱：{s['sandbox_id']} "
                              f"(状态: {s.get('status', 'unknown')})，请勿重复创建")

        sandbox_id = str(uuid.uuid4())
        sandbox_store.create_sandbox_dir(sandbox_id, snapshot_data, name=name)

        config_signature = sandbox_store.compute_config_signature()

        sandbox_record = {
            "sandbox_id": sandbox_id,
            "name": name or f"演练-{sandbox_id[:8]}",
            "snapshot_hash": snapshot_hash,
            "status": "ready",
            "created_at": _now(),
            "updated_at": _now(),
            "config_signature": config_signature,
            "snapshot": snapshot_data,
            "snapshot_counts": {
                "books": len(snapshot_data.get("books", [])),
                "active_reservations": len(snapshot_data.get("active_reservations", [])),
                "blacklist": len(snapshot_data.get("blacklist", [])),
                "logs": len(snapshot_data.get("logs", [])),
            },
        }
        sandbox_store.save_sandbox_meta(sandbox_record)

        sandbox_store.update_drill_results(sandbox_id, {
            "created_at": _now(),
            "precheck_report": None,
            "dryrun_report": None,
            "import_report": None,
            "imported_counts": None,
            "rollback_result": None,
            "restart_verification": None,
            "conflicts": [],
            "log_summary": [],
            "final_conclusion": None,
        })

        _sandbox_log(sandbox_id, "sandbox_create", True, detail=f"创建演练沙箱 {sandbox_id}")

    return sandbox_record, None


def list_sandboxes(limit=100):
    sandboxes = sandbox_store.list_sandboxes()
    sandboxes_sorted = sorted(sandboxes, key=lambda s: s.get("created_at", ""), reverse=True)
    result = []
    for s in sandboxes_sorted[:limit]:
        entry = {k: v for k, v in s.items() if k != "snapshot"}
        stale, _ = _check_sandbox_config_stale(s["sandbox_id"])
        entry["config_stale"] = stale
        result.append(entry)
    return result


def get_sandbox(sandbox_id):
    meta = sandbox_store.get_sandbox_meta(sandbox_id)
    if not meta:
        return None, "沙箱不存在"

    stale, sigs = _check_sandbox_config_stale(sandbox_id)
    drill = sandbox_store.load_drill_results(sandbox_id)
    data_counts = {}
    for fname in ["books", "reservations", "blacklist", "logs", "batches"]:
        data_counts[fname] = len(sandbox_store.load_sandbox_data(sandbox_id, fname))

    result = {k: v for k, v in meta.items() if k != "snapshot"}
    result["config_stale"] = stale
    if stale:
        result["config_stale_detail"] = {
            "original_signature": sigs[0],
            "current_signature": sigs[1],
        }
    result["drill_results"] = drill
    result["data_counts"] = data_counts
    return result, None


def run_sandbox_precheck(sandbox_id):
    meta = sandbox_store.get_sandbox_meta(sandbox_id)
    if not meta:
        return None, "沙箱不存在"

    lock = sandbox_store.get_sandbox_lock_obj(sandbox_id)
    with lock:
        stale, _ = _check_sandbox_config_stale(sandbox_id)
        if stale:
            return None, "正式环境配置已变更，该演练沙箱已过期，请销毁后重新创建"

        _set_sandbox_status(sandbox_id, "running_precheck")

        snapshot_data = meta["snapshot"]
        try:
            parsed, conflicts, errors, format_errors, log_issues = _sandbox_analyze_conflicts(
                sandbox_id, snapshot_data
            )
        except Exception as e:
            _set_sandbox_status(sandbox_id, "failed", extra_updates={"error": f"预检异常: {str(e)}"})
            return None, f"预检过程中发生内部错误: {str(e)}"

        report = _build_snapshot_report(parsed, conflicts, errors, format_errors, log_issues, dry_run=True)

        if errors and parsed is None:
            _set_sandbox_status(sandbox_id, "ready")
            return None, errors

        sandbox_store.update_drill_results(sandbox_id, {
            "precheck_report": report,
            "precheck_at": _now(),
        })
        _sandbox_log(sandbox_id, "sandbox_precheck", True,
                     detail=f"预检完成: can_import={report.get('can_import')}, 冲突数={len(conflicts)}")

        _set_sandbox_status(sandbox_id, "ready")

        return report, None


def run_sandbox_dryrun(sandbox_id):
    meta = sandbox_store.get_sandbox_meta(sandbox_id)
    if not meta:
        return None, "沙箱不存在"

    lock = sandbox_store.get_sandbox_lock_obj(sandbox_id)
    with lock:
        stale, _ = _check_sandbox_config_stale(sandbox_id)
        if stale:
            return None, "正式环境配置已变更，该演练沙箱已过期，请销毁后重新创建"

        _set_sandbox_status(sandbox_id, "running_dryrun")

        snapshot_data = meta["snapshot"]
        try:
            parsed, conflicts, errors, format_errors, log_issues = _sandbox_analyze_conflicts(
                sandbox_id, snapshot_data
            )
        except Exception as e:
            _set_sandbox_status(sandbox_id, "failed", extra_updates={"error": f"Dry-Run 异常: {str(e)}"})
            return None, f"Dry-Run 过程中发生内部错误: {str(e)}"

        report = _build_snapshot_report(parsed, conflicts, errors, format_errors, log_issues, dry_run=True)

        total_format_errors = sum(len(v) for v in format_errors.values()) if format_errors else 0

        if errors and parsed is None:
            _set_sandbox_status(sandbox_id, "ready")
            return None, errors

        if total_format_errors > 0:
            format_err_messages = []
            for sec, fe_list in format_errors.items():
                for fe in fe_list:
                    format_err_messages.append(f"[{sec}] {fe.get('message', str(fe))}")
            sandbox_store.update_drill_results(sandbox_id, {
                "dryrun_report": report,
                "dryrun_at": _now(),
                "dryrun_conflicts": conflicts,
                "log_summary": format_err_messages,
            })
            _set_sandbox_status(sandbox_id, "ready")
            return None, format_err_messages

        if conflicts:
            sandbox_store.update_drill_results(sandbox_id, {
                "dryrun_report": report,
                "dryrun_at": _now(),
                "dryrun_conflicts": conflicts,
                "conflicts": conflicts,
            })
            _sandbox_log(sandbox_id, "sandbox_dryrun", False,
                         detail=f"Dry-Run 发现 {len(conflicts)} 个冲突")
            _set_sandbox_status(sandbox_id, "ready")
            return None, conflicts

        counts = {
            "books": len(parsed["books"]),
            "active_reservations": len(parsed["active_reservations"]),
            "blacklist": len(parsed["blacklist"]),
            "logs": len(parsed["logs"]),
        }

        sandbox_store.update_drill_results(sandbox_id, {
            "dryrun_report": report,
            "dryrun_at": _now(),
            "dryrun_counts": counts,
        })
        _sandbox_log(sandbox_id, "sandbox_dryrun", True,
                     detail=f"Dry-Run 通过: {counts}")

        _set_sandbox_status(sandbox_id, "ready")
        return {"counts": counts, "report": report}, None


def run_sandbox_import(sandbox_id):
    meta = sandbox_store.get_sandbox_meta(sandbox_id)
    if not meta:
        return None, "沙箱不存在"

    lock = sandbox_store.get_sandbox_lock_obj(sandbox_id)
    with lock:
        stale, _ = _check_sandbox_config_stale(sandbox_id)
        if stale:
            return None, "正式环境配置已变更，该演练沙箱已过期，请销毁后重新创建"

        current_status = meta.get("status", "")
        if current_status == "imported":
            return None, "该沙箱已执行过正式导入，请先回滚或销毁后重新创建"

        _set_sandbox_status(sandbox_id, "running_import")

        snapshot_data = meta["snapshot"]
        try:
            parsed, conflicts, errors, format_errors, log_issues = _sandbox_analyze_conflicts(
                sandbox_id, snapshot_data
            )
        except Exception as e:
            _set_sandbox_status(sandbox_id, "failed", extra_updates={"error": f"导入分析异常: {str(e)}"})
            return None, f"导入分析过程中发生内部错误: {str(e)}"

        report = _build_snapshot_report(parsed, conflicts, errors, format_errors, log_issues, dry_run=False)

        total_format_errors = sum(len(v) for v in format_errors.values()) if format_errors else 0

        if errors and parsed is None:
            _set_sandbox_status(sandbox_id, "ready")
            return None, errors

        if total_format_errors > 0:
            format_err_messages = []
            for sec, fe_list in format_errors.items():
                for fe in fe_list:
                    format_err_messages.append(f"[{sec}] {fe.get('message', str(fe))}")
            sandbox_store.update_drill_results(sandbox_id, {
                "import_report": report,
                "conflicts": conflicts,
                "log_summary": format_err_messages,
                "final_conclusion": "format_error",
            })
            _set_sandbox_status(sandbox_id, "failed")
            return None, format_err_messages

        if conflicts:
            sandbox_store.update_drill_results(sandbox_id, {
                "import_report": report,
                "conflicts": conflicts,
                "final_conclusion": "has_conflicts",
            })
            _sandbox_log(sandbox_id, "sandbox_import", False,
                         detail=f"导入发现 {len(conflicts)} 个冲突")
            _set_sandbox_status(sandbox_id, "failed")
            return None, conflicts

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

        backup = sandbox_store.backup_sandbox_all(sandbox_id)

        try:
            existing_books = _sandbox_list_books(sandbox_id)
            existing_book_ids = {b["book_id"] for b in existing_books}
            import_book_ids = {b["book_id"] for b in books_data}
            overlap = existing_book_ids & import_book_ids
            if overlap:
                raise RuntimeError(f"沙箱导入前二次校验发现冲突书目: {overlap}")

            existing_active = _sandbox_load_active_reservations(sandbox_id)
            existing_res_keys = {(r["book_id"], r["reader_id"]) for r in existing_active}
            import_res_keys = {(r["book_id"], r["reader_id"]) for r in reservations_data}
            res_overlap = existing_res_keys & import_res_keys
            if res_overlap:
                raise RuntimeError(f"沙箱导入前二次校验发现冲突预约: {res_overlap}")

            existing_bl = _sandbox_load_blacklist(sandbox_id)
            existing_bl_ids = {b["reader_id"] for b in existing_bl}
            import_bl_ids = {b["reader_id"] for b in blacklist_data}
            bl_overlap = existing_bl_ids & import_bl_ids
            if bl_overlap:
                raise RuntimeError(f"沙箱导入前二次校验发现冲突黑名单: {bl_overlap}")

            all_books = existing_books + books_data
            sandbox_store.save_sandbox_data(sandbox_id, "books", all_books)

            all_reservations = sandbox_store.load_sandbox_data(sandbox_id, "reservations") + reservations_data
            sandbox_store.save_sandbox_data(sandbox_id, "reservations", all_reservations)

            all_blacklist = existing_bl + blacklist_data
            sandbox_store.save_sandbox_data(sandbox_id, "blacklist", all_blacklist)

            all_logs = sandbox_store.load_sandbox_data(sandbox_id, "logs")
            for log_entry in logs_data:
                if not isinstance(log_entry, dict):
                    raise RuntimeError(f"日志记录不是字典: {type(log_entry).__name__}")
                entry = dict(log_entry)
                if "log_id" not in entry or not entry.get("log_id"):
                    entry["log_id"] = str(uuid.uuid4())
                if "timestamp" not in entry or not entry.get("timestamp"):
                    entry["timestamp"] = _now()
                all_logs.append(entry)
            sandbox_store.save_sandbox_data(sandbox_id, "logs", all_logs)

        except Exception as e:
            sandbox_store.restore_sandbox_all(sandbox_id, backup)
            _sandbox_log(sandbox_id, "sandbox_import", False,
                         detail=f"沙箱导入异常，已完整回滚: {str(e)}")
            _set_sandbox_status(sandbox_id, "failed", extra_updates={"error": str(e)})
            return None, [{
                "type": "sandbox_import_error",
                "message": f"沙箱导入过程出错，已完整回滚所有数据: {str(e)}",
            }]

        batch_id = str(uuid.uuid4())
        import_log_entry = _sandbox_log(
            sandbox_id, "import_snapshot", True,
            detail=f"沙箱快照导入成功：{counts}，批次ID: {batch_id}"
        )

        batches = sandbox_store.load_sandbox_data(sandbox_id, "batches")
        batch = {
            "batch_id": batch_id,
            "type": "sandbox_snapshot_import",
            "status": "active",
            "created_at": _now(),
            "rolled_back_at": None,
            "summary": dict(counts),
            "imported_details": {
                "books": books_data,
                "active_reservations": reservations_data,
                "blacklist": blacklist_data,
                "logs": logs_data,
            },
            "import_log_id": import_log_entry["log_id"],
            "rollback_log_id": None,
        }
        batches.append(batch)
        sandbox_store.save_sandbox_data(sandbox_id, "batches", batches)

        sandbox_store.update_drill_results(sandbox_id, {
            "import_report": report,
            "imported_counts": counts,
            "imported_at": _now(),
            "batch_id": batch_id,
            "final_conclusion": "imported_success",
        })

        _set_sandbox_status(sandbox_id, "imported")

        return {"counts": counts, "report": report, "batch_id": batch_id}, None


def _sandbox_check_rollback_conflicts(sandbox_id, batch):
    conflicts = []
    details = batch["imported_details"]

    for book in details["books"]:
        book_id = book["book_id"]
        existing = _sandbox_load_book(sandbox_id, book_id)
        if not existing:
            conflicts.append({
                "type": "book_missing",
                "section": "books",
                "book_id": book_id,
                "message": f"沙箱中书目 {book_id} 已不存在，无法回滚",
            })
            continue
        changed_fields = []
        for field in ["title", "total_copies", "borrow_days", "retain_hours"]:
            if existing.get(field) != book.get(field):
                changed_fields.append({
                    "field": field,
                    "original": book.get(field),
                    "current": existing.get(field),
                })
        if changed_fields:
            conflicts.append({
                "type": "book_modified",
                "section": "books",
                "book_id": book_id,
                "changed_fields": changed_fields,
                "message": f"沙箱中书目 {book_id} 在导入后被修改过，无法直接回滚",
            })

    imported_res_map = {}
    for res in details["active_reservations"]:
        imported_res_map[res["reservation_id"]] = res

    all_reservations = sandbox_store.load_sandbox_data(sandbox_id, "reservations")
    for res_id, imported_res in imported_res_map.items():
        existing = next((r for r in all_reservations if r["reservation_id"] == res_id), None)
        if not existing:
            conflicts.append({
                "type": "reservation_missing",
                "section": "active_reservations",
                "reservation_id": res_id,
                "book_id": imported_res.get("book_id"),
                "reader_id": imported_res.get("reader_id"),
                "message": f"沙箱中预约记录 {res_id} 已不存在，无法回滚",
            })
            continue
        changed_fields = []
        for field in ["book_id", "reader_id", "status", "created_at",
                       "available_at", "expire_at", "borrowed_at", "returned_at"]:
            if existing.get(field) != imported_res.get(field):
                changed_fields.append({
                    "field": field,
                    "original": imported_res.get(field),
                    "current": existing.get(field),
                })
        if changed_fields:
            conflicts.append({
                "type": "reservation_modified",
                "section": "active_reservations",
                "reservation_id": res_id,
                "book_id": imported_res.get("book_id"),
                "reader_id": imported_res.get("reader_id"),
                "changed_fields": changed_fields,
                "message": f"沙箱中预约记录 {res_id} 状态发生变化，无法直接回滚",
            })

    imported_bl_map = {}
    for bl in details["blacklist"]:
        imported_bl_map[bl["reader_id"]] = bl

    all_blacklist = _sandbox_load_blacklist(sandbox_id)
    existing_bl_map = {b["reader_id"]: b for b in all_blacklist}

    for reader_id, imported_bl in imported_bl_map.items():
        existing = existing_bl_map.get(reader_id)
        if not existing:
            conflicts.append({
                "type": "blacklist_missing",
                "section": "blacklist",
                "reader_id": reader_id,
                "message": f"沙箱中黑名单记录 {reader_id} 已不存在，无法回滚",
            })
            continue
        if existing.get("reason") != imported_bl.get("reason") or existing.get("added_at") != imported_bl.get("added_at"):
            conflicts.append({
                "type": "blacklist_modified",
                "section": "blacklist",
                "reader_id": reader_id,
                "original": imported_bl,
                "current": existing,
                "message": f"沙箱中黑名单记录 {reader_id} 在导入后被修改过，无法直接回滚",
            })

    return conflicts


def run_sandbox_rollback(sandbox_id):
    meta = sandbox_store.get_sandbox_meta(sandbox_id)
    if not meta:
        return None, "沙箱不存在"

    lock = sandbox_store.get_sandbox_lock_obj(sandbox_id)
    with lock:
        current_status = meta.get("status", "")
        if current_status == "rolled_back":
            drill = sandbox_store.load_drill_results(sandbox_id)
            return {
                "rollback_count": 0,
                "already_rolled_back": True,
                "message": "沙箱已回滚，重复操作无效",
                "batch_id": drill.get("batch_id"),
            }, None

        if current_status != "imported":
            return None, f"沙箱状态为 {current_status}，无法回滚（仅 imported 状态可回滚）"

        drill = sandbox_store.load_drill_results(sandbox_id)
        batch_id = drill.get("batch_id")
        if not batch_id:
            return None, "沙箱中找不到导入批次记录"

        batches = sandbox_store.load_sandbox_data(sandbox_id, "batches")
        batch = next((b for b in batches if b["batch_id"] == batch_id), None)
        if not batch:
            return None, "沙箱批次记录已丢失，无法回滚"

        if batch.get("status") == "rolled_back":
            return {
                "rollback_count": 0,
                "already_rolled_back": True,
                "message": "批次已回滚，重复操作无效",
                "batch_id": batch_id,
            }, None

        conflicts = _sandbox_check_rollback_conflicts(sandbox_id, batch)
        if conflicts:
            sandbox_store.update_drill_results(sandbox_id, {
                "rollback_conflicts": conflicts,
                "final_conclusion": "rollback_conflict",
            })
            return None, {
                "message": "回滚存在冲突，部分数据在导入后被修改过",
                "conflicts": conflicts,
            }

        backup = sandbox_store.backup_sandbox_all(sandbox_id)
        details = batch["imported_details"]
        rollback_count = 0

        try:
            existing_books = _sandbox_list_books(sandbox_id)
            imported_book_ids = {b["book_id"] for b in details["books"]}
            new_books = [b for b in existing_books if b["book_id"] not in imported_book_ids]
            sandbox_store.save_sandbox_data(sandbox_id, "books", new_books)
            rollback_count += len(details["books"])

            all_reservations = sandbox_store.load_sandbox_data(sandbox_id, "reservations")
            imported_res_ids = {r["reservation_id"] for r in details["active_reservations"]}
            new_reservations = [r for r in all_reservations if r["reservation_id"] not in imported_res_ids]
            sandbox_store.save_sandbox_data(sandbox_id, "reservations", new_reservations)
            rollback_count += len(details["active_reservations"])

            all_blacklist = _sandbox_load_blacklist(sandbox_id)
            imported_bl_ids = {b["reader_id"] for b in details["blacklist"]}
            new_blacklist = [b for b in all_blacklist if b["reader_id"] not in imported_bl_ids]
            sandbox_store.save_sandbox_data(sandbox_id, "blacklist", new_blacklist)
            rollback_count += len(details["blacklist"])

            all_logs = sandbox_store.load_sandbox_data(sandbox_id, "logs")
            imported_log_ids = set()
            for log in details["logs"]:
                log_id = log.get("log_id")
                if log_id:
                    imported_log_ids.add(log_id)
            if batch.get("import_log_id"):
                imported_log_ids.add(batch["import_log_id"])
            new_logs = [l for l in all_logs if l.get("log_id") not in imported_log_ids]
            sandbox_store.save_sandbox_data(sandbox_id, "logs", new_logs)
            detail_log_count = len(details["logs"])
            import_log_removed = 1 if batch.get("import_log_id") else 0
            rollback_count += detail_log_count + import_log_removed

            rollback_log_entry = _sandbox_log(
                sandbox_id, "rollback_batch", True,
                detail=f"沙箱回滚批次 {batch_id}，共回滚 {rollback_count} 条记录"
            )

            for i, b in enumerate(batches):
                if b["batch_id"] == batch_id:
                    batches[i]["status"] = "rolled_back"
                    batches[i]["rolled_back_at"] = _now()
                    batches[i]["rollback_log_id"] = rollback_log_entry["log_id"]
                    break
            sandbox_store.save_sandbox_data(sandbox_id, "batches", batches)

        except Exception as e:
            sandbox_store.restore_sandbox_all(sandbox_id, backup)
            _sandbox_log(sandbox_id, "rollback_batch", False,
                         detail=f"沙箱回滚批次 {batch_id} 失败，已恢复: {str(e)}")
            return None, f"沙箱回滚失败，已恢复原状: {str(e)}"

        sandbox_store.update_drill_results(sandbox_id, {
            "rollback_result": {
                "rollback_count": rollback_count,
                "already_rolled_back": False,
            },
            "rolled_back_at": _now(),
            "final_conclusion": "rolled_back_success",
        })

        _set_sandbox_status(sandbox_id, "rolled_back")

        return {
            "rollback_count": rollback_count,
            "already_rolled_back": False,
            "batch_id": batch_id,
            "message": f"成功回滚 {rollback_count} 条记录",
        }, None


def run_sandbox_restart_verify(sandbox_id):
    meta = sandbox_store.get_sandbox_meta(sandbox_id)
    if not meta:
        return None, "沙箱不存在"

    lock = sandbox_store.get_sandbox_lock_obj(sandbox_id)
    with lock:
        stale, _ = _check_sandbox_config_stale(sandbox_id)

        data_counts = {}
        for fname in ["books", "reservations", "blacklist", "logs", "batches"]:
            data_counts[fname] = len(sandbox_store.load_sandbox_data(sandbox_id, fname))

        drill = sandbox_store.load_drill_results(sandbox_id)
        expected_counts = drill.get("imported_counts")
        status = meta.get("status", "")

        verification = {
            "verified_at": _now(),
            "status": status,
            "data_counts": data_counts,
            "config_stale": stale,
            "data_consistent": True,
            "notes": [],
        }

        if status == "imported" and expected_counts:
            if data_counts["books"] != expected_counts.get("books", 0):
                verification["data_consistent"] = False
                verification["notes"].append(
                    f"books 数量不一致: 期望 {expected_counts.get('books')}, 实际 {data_counts['books']}"
                )
            if data_counts["batches"] < 1:
                verification["data_consistent"] = False
                verification["notes"].append("缺少批次记录")

        if stale:
            verification["notes"].append("警告: 正式环境配置已变更，该演练沙箱结果可能不再适用")

        if status in ("imported", "rolled_back") and drill.get("import_report"):
            verification["notes"].append(f"历史结论: {drill.get('final_conclusion', 'N/A')}")

        sandbox_store.update_drill_results(sandbox_id, {
            "restart_verification": verification,
        })
        _sandbox_log(sandbox_id, "sandbox_restart_verify", True,
                     detail=f"重启验证完成: consistent={verification['data_consistent']}, status={status}")

        return verification, None


def export_sandbox_results(sandbox_id):
    meta = sandbox_store.get_sandbox_meta(sandbox_id)
    if not meta:
        return None, "沙箱不存在"

    drill = sandbox_store.load_drill_results(sandbox_id)
    stale, _ = _check_sandbox_config_stale(sandbox_id)

    data_counts = {}
    for fname in ["books", "reservations", "blacklist", "logs", "batches"]:
        data_counts[fname] = len(sandbox_store.load_sandbox_data(sandbox_id, fname))

    result = {
        "sandbox_id": meta["sandbox_id"],
        "name": meta.get("name", ""),
        "status": meta.get("status", ""),
        "created_at": meta.get("created_at"),
        "updated_at": meta.get("updated_at"),
        "config_stale": stale,
        "snapshot_counts": meta.get("snapshot_counts", {}),
        "data_counts": data_counts,
        "drill_results": drill,
    }
    return result, None


def destroy_sandbox(sandbox_id):
    meta = sandbox_store.get_sandbox_meta(sandbox_id)
    if not meta:
        return False, "沙箱不存在"

    sandbox_store.destroy_sandbox(sandbox_id)
    return True, None


def recover_sandboxes_on_startup():
    recovered = []
    sandboxes = sandbox_store.list_sandboxes()
    for s in sandboxes:
        sid = s["sandbox_id"]
        status = s.get("status", "")
        if status in ("running_precheck", "running_dryrun", "running_import"):
            sandbox_store._update_sandbox_in_meta(sid, {
                "status": "ready",
                "updated_at": _now(),
                "recovered_note": f"服务重启，由状态 {status} 恢复为 ready",
            })
            recovered.append({
                "sandbox_id": sid,
                "previous_status": status,
                "new_status": "ready",
            })
    return recovered

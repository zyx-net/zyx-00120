import uuid
from datetime import datetime, timezone

import checkup_store
from service import (
    _validate_book_config,
    _check_book_numeric_ranges,
    _validate_snapshot_reservation,
    _validate_snapshot_blacklist,
    _validate_snapshot_log,
)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _checkup_log(record_id, action, success, operator=None, detail=""):
    log_entry = {
        "log_id": str(uuid.uuid4()),
        "timestamp": _now(),
        "record_id": record_id,
        "action": action,
        "operator": operator,
        "detail": detail,
        "success": success,
    }
    checkup_store.append_log(log_entry)
    return log_entry


def _run_structural_validation(snapshot_data):
    errors = []
    if not isinstance(snapshot_data, dict):
        errors.append({
            "check": "structural",
            "code": "not_dict",
            "message": "快照数据格式错误，应为 JSON 对象",
        })
        return errors

    if snapshot_data.get("version") != "2.0":
        errors.append({
            "check": "structural",
            "code": "version_mismatch",
            "message": f"快照版本不支持，需要 version=2.0，实际: {snapshot_data.get('version')}",
        })

    if snapshot_data.get("type") != "full_snapshot":
        errors.append({
            "check": "structural",
            "code": "type_mismatch",
            "message": f"快照类型不支持，需要 type=full_snapshot，实际: {snapshot_data.get('type')}",
        })

    for key in ("books", "active_reservations", "blacklist", "logs"):
        val = snapshot_data.get(key)
        if val is None:
            errors.append({
                "check": "structural",
                "code": "missing_section",
                "message": f"快照缺少必要段落: {key}",
            })
        elif not isinstance(val, list):
            errors.append({
                "check": "structural",
                "code": "section_not_list",
                "message": f"快照段落 {key} 应为列表，实际类型: {type(val).__name__}",
            })

    return errors


def _run_required_fields_check(snapshot_data):
    errors = []
    if not isinstance(snapshot_data, dict):
        return errors

    for idx, book in enumerate(snapshot_data.get("books", [])):
        if not isinstance(book, dict):
            errors.append({
                "check": "required_fields",
                "code": "book_not_dict",
                "section": "books",
                "index": idx,
                "message": f"书目记录 {idx} 不是有效的 JSON 对象",
            })
            continue
        book_errors = _validate_book_config(book, idx)
        for e in book_errors:
            errors.append({
                "check": "required_fields",
                "code": "book_missing_field",
                "section": "books",
                "index": idx,
                "message": e,
            })

    for idx, res in enumerate(snapshot_data.get("active_reservations", [])):
        if not isinstance(res, dict):
            errors.append({
                "check": "required_fields",
                "code": "reservation_not_dict",
                "section": "active_reservations",
                "index": idx,
                "message": f"预约记录 {idx} 不是有效的 JSON 对象",
            })
            continue
        res_errors = _validate_snapshot_reservation(res, idx)
        for e in res_errors:
            errors.append({
                "check": "required_fields",
                "code": "reservation_missing_field",
                "section": "active_reservations",
                "index": idx,
                "message": e,
            })

    for idx, bl in enumerate(snapshot_data.get("blacklist", [])):
        if not isinstance(bl, dict):
            errors.append({
                "check": "required_fields",
                "code": "blacklist_not_dict",
                "section": "blacklist",
                "index": idx,
                "message": f"黑名单记录 {idx} 不是有效的 JSON 对象",
            })
            continue
        bl_errors = _validate_snapshot_blacklist(bl, idx)
        for e in bl_errors:
            errors.append({
                "check": "required_fields",
                "code": "blacklist_missing_field",
                "section": "blacklist",
                "index": idx,
                "message": e,
            })

    for idx, log in enumerate(snapshot_data.get("logs", [])):
        log_errors = _validate_snapshot_log(log, idx)
        for e in log_errors:
            errors.append({
                "check": "required_fields",
                "code": e.get("error_code", "log_error"),
                "section": "logs",
                "index": idx,
                "message": e.get("message", str(e)),
            })

    return errors


def _run_version_compatibility_check(snapshot_data):
    warnings = []
    if not isinstance(snapshot_data, dict):
        return warnings

    export_time = snapshot_data.get("export_time")
    if export_time:
        try:
            export_dt = datetime.fromisoformat(export_time.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            age_days = (now - export_dt).days
            if age_days > 30:
                warnings.append({
                    "check": "version_compatibility",
                    "code": "snapshot_too_old",
                    "message": f"快照导出时间距今已 {age_days} 天，数据可能已过时",
                })
        except (ValueError, TypeError):
            warnings.append({
                "check": "version_compatibility",
                "code": "invalid_export_time",
                "message": f"快照导出时间格式无法解析: {export_time}",
            })

    books = snapshot_data.get("books", [])
    import store
    existing_books = store.list_books()
    existing_ids = {b["book_id"] for b in existing_books}
    new_ids = {b["book_id"] for b in books if isinstance(b, dict) and "book_id" in b}
    overlap = existing_ids & new_ids
    if overlap:
        warnings.append({
            "check": "version_compatibility",
            "code": "target_conflict",
            "message": f"目标环境已存在 {len(overlap)} 个相同书目: {sorted(overlap)[:5]}{'...' if len(overlap) > 5 else ''}，导入将产生冲突",
        })

    return warnings


_SENSITIVE_BLOCKING_RULES = [
    ("total_copies", lambda v: v == 0, "total_copies 为 0，该书目将无法被预约"),
    ("borrow_days", lambda v: v == 0, "borrow_days 为 0，借期为 0 天不合理"),
]

_SENSITIVE_WARNING_RULES = [
    ("total_copies", lambda v: v > 10000, "total_copies 超过 10000，可能为误配置"),
    ("borrow_days", lambda v: v > 365, "borrow_days 超过 365 天，借期过长"),
    ("retain_hours", lambda v: v == 0, "retain_hours 为 0，待取预约将立即过期"),
    ("retain_hours", lambda v: v > 720, "retain_hours 超过 720 小时（30天），保留时间过长"),
]


def _run_sensitive_config_check(snapshot_data):
    errors = []
    warnings = []
    if not isinstance(snapshot_data, dict):
        return errors, warnings

    for idx, book in enumerate(snapshot_data.get("books", [])):
        if not isinstance(book, dict):
            continue
        book_id = book.get("book_id", f"(index-{idx})")
        for field, predicate, message in _SENSITIVE_BLOCKING_RULES:
            val = book.get(field)
            if val is not None and isinstance(val, (int, float)) and predicate(val):
                errors.append({
                    "check": "sensitive_config",
                    "code": f"sensitive_{field}",
                    "section": "books",
                    "index": idx,
                    "book_id": book_id,
                    "field": field,
                    "value": val,
                    "message": f"书目 {book_id} 的 {message}（当前值: {val}）",
                })
        for field, predicate, message in _SENSITIVE_WARNING_RULES:
            val = book.get(field)
            if val is not None and isinstance(val, (int, float)) and predicate(val):
                warnings.append({
                    "check": "sensitive_config",
                    "code": f"sensitive_{field}",
                    "section": "books",
                    "index": idx,
                    "book_id": book_id,
                    "field": field,
                    "value": val,
                    "message": f"书目 {book_id} 的 {message}（当前值: {val}）",
                })

        range_conflicts = _check_book_numeric_ranges(book, idx)
        for c in range_conflicts:
            errors.append({
                "check": "sensitive_config",
                "code": c.get("type", "numeric_range"),
                "section": "books",
                "index": idx,
                "book_id": book_id,
                "message": c.get("message", ""),
            })

    seen_book_ids = set()
    for idx, book in enumerate(snapshot_data.get("books", [])):
        if not isinstance(book, dict):
            continue
        bid = book.get("book_id")
        if bid and bid in seen_book_ids:
            errors.append({
                "check": "sensitive_config",
                "code": "duplicate_book_id",
                "section": "books",
                "index": idx,
                "book_id": bid,
                "message": f"快照内存在重复的 book_id: {bid}",
            })
        if bid:
            seen_book_ids.add(bid)

    seen_res_keys = set()
    for idx, res in enumerate(snapshot_data.get("active_reservations", [])):
        if not isinstance(res, dict):
            continue
        bid = res.get("book_id", "")
        rid = res.get("reader_id", "")
        key = (bid, rid)
        if key in seen_res_keys:
            errors.append({
                "check": "sensitive_config",
                "code": "duplicate_reservation",
                "section": "active_reservations",
                "index": idx,
                "message": f"快照内存在重复预约: {bid} / {rid}",
            })
        seen_res_keys.add(key)

        if bid and bid not in seen_book_ids:
            import store
            if not store.load_book(bid):
                warnings.append({
                    "check": "sensitive_config",
                    "code": "orphan_reservation",
                    "section": "active_reservations",
                    "index": idx,
                    "message": f"预约引用了快照内外均不存在的书目: {bid}",
                })

    return errors, warnings


def create_checkup(snapshot_data, operator=None, name=None):
    if not isinstance(snapshot_data, dict):
        return None, "快照数据格式错误，应为 JSON 对象"

    snapshot_hash = checkup_store.compute_snapshot_hash(snapshot_data)

    with checkup_store._global_lock:
        existing_records = checkup_store.load_records()
        for r in existing_records:
            if (r.get("snapshot_hash") == snapshot_hash
                    and r.get("status") not in ("voided", "expired")):
                return None, (f"同一快照已存在有效体检记录: {r['record_id']} "
                              f"(状态: {r.get('status')})，请勿重复提交")

        record_id = str(uuid.uuid4())
        config_signature = checkup_store.compute_config_signature()

        struct_errors = _run_structural_validation(snapshot_data)
        required_errors = _run_required_fields_check(snapshot_data)
        version_warnings = _run_version_compatibility_check(snapshot_data)
        sensitive_errors, sensitive_warnings = _run_sensitive_config_check(snapshot_data)

        all_blocking = struct_errors + required_errors + sensitive_errors
        all_warnings = version_warnings + sensitive_warnings

        passed = len(all_blocking) == 0
        status = "passed" if passed else "failed"

        snapshot_counts = {}
        if isinstance(snapshot_data, dict):
            for key in ("books", "active_reservations", "blacklist", "logs"):
                val = snapshot_data.get(key, [])
                snapshot_counts[key] = len(val) if isinstance(val, list) else 0

        record = {
            "record_id": record_id,
            "name": name or f"体检-{record_id[:8]}",
            "snapshot_hash": snapshot_hash,
            "status": status,
            "operator": operator,
            "created_at": _now(),
            "updated_at": _now(),
            "config_signature": config_signature,
            "snapshot_counts": snapshot_counts,
            "checkup_summary": {
                "structural_errors": len(struct_errors),
                "required_field_errors": len(required_errors),
                "sensitive_errors": len(sensitive_errors),
                "version_warnings": len(version_warnings),
                "sensitive_warnings": len(sensitive_warnings),
                "total_blocking": len(all_blocking),
                "total_warnings": len(all_warnings),
                "passed": passed,
            },
        }
        checkup_store.add_record(record)

        conclusion = {
            "record_id": record_id,
            "status": status,
            "passed": passed,
            "structural_errors": struct_errors,
            "required_field_errors": required_errors,
            "sensitive_errors": sensitive_errors,
            "version_warnings": version_warnings,
            "sensitive_warnings": sensitive_warnings,
            "created_at": _now(),
        }
        checkup_store.save_conclusion(conclusion)

        _checkup_log(record_id, "checkup_create", True, operator=operator,
                     detail=f"创建体检记录，状态={status}，阻断={len(all_blocking)}，告警={len(all_warnings)}")

    return record, None


def list_checkups(limit=100):
    records = checkup_store.load_records()
    records_sorted = sorted(records, key=lambda r: r.get("created_at", ""), reverse=True)
    return records_sorted[:limit]


def get_checkup(record_id):
    record = checkup_store.get_record(record_id)
    if not record:
        return None, "体检记录不存在"

    conclusion = checkup_store.get_conclusion(record_id)
    stale = _check_config_stale(record_id)

    result = dict(record)
    result["config_stale"] = stale
    if conclusion:
        result["conclusion"] = conclusion
    return result, None


def export_checkup_report(record_id):
    record = checkup_store.get_record(record_id)
    if not record:
        return None, "体检记录不存在"

    conclusion = checkup_store.get_conclusion(record_id)
    stale = _check_config_stale(record_id)

    report = {
        "report_id": str(uuid.uuid4()),
        "record_id": record_id,
        "name": record.get("name", ""),
        "status": record.get("status", ""),
        "operator": record.get("operator"),
        "created_at": record.get("created_at"),
        "snapshot_counts": record.get("snapshot_counts", {}),
        "snapshot_hash": record.get("snapshot_hash", ""),
        "config_signature": record.get("config_signature", ""),
        "config_stale": stale,
        "checkup_summary": record.get("checkup_summary", {}),
        "conclusion": conclusion,
        "exported_at": _now(),
    }
    if stale:
        report["stale_warning"] = "当前环境配置与体检时不同，本报告结论可能已失效"

    _checkup_log(record_id, "checkup_export", True,
                 detail=f"导出体检报告: {report['report_id']}")

    return report, None


def void_checkup(record_id, operator=None):
    record = checkup_store.get_record(record_id)
    if not record:
        return None, "体检记录不存在"

    if record.get("status") == "voided":
        return None, "该体检记录已作废，不可重复操作"

    with checkup_store._global_lock:
        fresh = checkup_store.get_record(record_id)
        if not fresh:
            return None, "体检记录不存在"
        if fresh.get("status") == "voided":
            return None, "该体检记录已作废，不可重复操作"

        checkup_store.update_record(record_id, {
            "status": "voided",
            "voided_at": _now(),
            "voided_by": operator,
            "updated_at": _now(),
        })
        checkup_store.update_conclusion(record_id, {
            "status": "voided",
            "voided_at": _now(),
            "voided_by": operator,
        })

        _checkup_log(record_id, "checkup_void", True, operator=operator,
                     detail=f"作废体检记录，操作者: {operator or '未知'}")

    updated = checkup_store.get_record(record_id)
    return updated, None


def _check_config_stale(record_id):
    record = checkup_store.get_record(record_id)
    if not record:
        return False
    original_sig = record.get("config_signature", "")
    if not original_sig:
        return False
    current_sig = checkup_store.compute_config_signature()
    return original_sig != current_sig


def recover_checkups_on_startup():
    recovered = []
    records = checkup_store.load_records()
    for r in records:
        rid = r["record_id"]
        status = r.get("status", "")
        if status == "running":
            checkup_store.update_record(rid, {
                "status": "failed",
                "updated_at": _now(),
                "recovered_note": f"服务重启，由状态 {status} 恢复为 failed",
            })
            checkup_store.update_conclusion(rid, {
                "status": "failed",
                "recovered_note": f"服务重启，由状态 running 恢复为 failed",
            })
            recovered.append({
                "record_id": rid,
                "previous_status": status,
                "new_status": "failed",
            })
    return recovered


def invalidate_stale_checkups():
    invalidated = []
    records = checkup_store.load_records()
    for r in records:
        rid = r["record_id"]
        status = r.get("status", "")
        if status not in ("passed", "failed"):
            continue
        stale = _check_config_stale(rid)
        if stale:
            checkup_store.update_record(rid, {
                "status": "expired",
                "expired_at": _now(),
                "expire_reason": "环境配置已变更，体检结论失效",
                "updated_at": _now(),
            })
            checkup_store.update_conclusion(rid, {
                "status": "expired",
                "expire_reason": "环境配置已变更，体检结论失效",
            })
            _checkup_log(rid, "checkup_expire", True,
                         detail="环境配置变更，体检记录自动失效")
            invalidated.append({
                "record_id": rid,
                "previous_status": status,
                "new_status": "expired",
            })
    return invalidated

import uuid
import copy
from datetime import datetime, timezone

import freeze_store
import store

_VALID_REASONS = ("inventory_check", "maintenance", "abnormal_check", "other")
_VALID_STATUSES = ("pending", "frozen", "restoring", "restored", "revoked", "auto_invalidated")
_REQUIRE_MANAGER_ROLE = True


def _now():
    return datetime.now(timezone.utc).isoformat()


def _is_feature_enabled():
    config = freeze_store.load_config()
    return config.get("enabled", True)


def _audit_log(freeze_id, action, success, operator=None, detail="", **extra):
    log_entry = {
        "log_id": str(uuid.uuid4()),
        "timestamp": _now(),
        "freeze_id": freeze_id,
        "action": action,
        "operator": operator,
        "detail": detail,
        "success": success,
    }
    log_entry.update(extra)
    freeze_store.append_audit_log(log_entry)
    return log_entry


def _require_manager(role, operation):
    if _REQUIRE_MANAGER_ROLE and role != "manager":
        return False, f"操作 [{operation}] 需要 manager 权限，当前角色为 {role}"
    return True, None


def _get_queue_snapshot(book_id):
    reservations = store.load_reservations()
    queue = [
        r for r in reservations
        if r["book_id"] == book_id and r["status"] in ("waiting", "available", "borrowed")
    ]
    queue.sort(key=lambda r: r["created_at"])
    waiting = [r for r in queue if r["status"] == "waiting"]
    for i, r in enumerate(waiting):
        r["position"] = i + 1
    return {
        "snapshot_time": _now(),
        "book_id": book_id,
        "total_count": len(queue),
        "waiting_count": len([r for r in queue if r["status"] == "waiting"]),
        "available_count": len([r for r in queue if r["status"] == "available"]),
        "borrowed_count": len([r for r in queue if r["status"] == "borrowed"]),
        "affected_readers": [
            {
                "reader_id": r["reader_id"],
                "reservation_id": r["reservation_id"],
                "status": r["status"],
                "position": r.get("position"),
                "created_at": r["created_at"],
            }
            for r in queue
        ],
        "reservations": copy.deepcopy(queue),
    }


def _apply_freeze_to_reservations(book_id, freeze_id):
    reservations = store.load_reservations()
    updated_ids = []
    for r in reservations:
        if r["book_id"] == book_id and r["status"] in ("waiting", "available"):
            r["_frozen_by"] = freeze_id
            r["_status_before_freeze"] = r["status"]
            r["status"] = "frozen"
            r["_frozen_at"] = _now()
            updated_ids.append(r["reservation_id"])
    if updated_ids:
        store.save_reservations(reservations)
    return updated_ids


def _recover_reservations_from_freeze(book_id, freeze_id):
    reservations = store.load_reservations()
    restored_ids = []
    for r in reservations:
        if (r["book_id"] == book_id and r.get("_frozen_by") == freeze_id
                and r["status"] == "frozen"):
            original_status = r.get("_status_before_freeze", "waiting")
            r["status"] = original_status
            r["_restored_by_freeze"] = freeze_id
            r["_restored_at"] = _now()
            r.pop("_frozen_by", None)
            r.pop("_status_before_freeze", None)
            r.pop("_frozen_at", None)
            restored_ids.append(r["reservation_id"])
    if restored_ids:
        store.save_reservations(reservations)
    return restored_ids


def create_freeze(book_id, reason, operator=None, role="viewer", remark=None,
                  effective_at=None, idempotency_key=None):
    if not _is_feature_enabled():
        return None, False, "预约冻结功能已被系统管理员关闭"

    if reason not in _VALID_REASONS:
        return None, False, f"冻结原因不合法，允许值: {', '.join(_VALID_REASONS)}"

    ok, err = _require_manager(role, "创建冻结单")
    if not ok:
        return None, False, err

    book = store.load_book(book_id)
    if not book:
        return None, False, f"书目 {book_id} 不存在"

    with freeze_store._global_lock:
        if idempotency_key:
            existing = freeze_store.load_orders()
            for o in existing:
                if o.get("idempotency_key") == idempotency_key:
                    _audit_log(o["freeze_id"], "freeze_create_idempotent", True,
                               operator=operator,
                               detail=f"幂等命中，返回已存在的冻结单，idempotency_key={idempotency_key}")
                    return dict(o), True, None

        active_freeze = freeze_store.find_active_freeze_by_book(book_id)
        if active_freeze:
            return None, False, (f"书目 {book_id} 已存在活跃冻结单: {active_freeze['freeze_id']} "
                          f"(状态: {active_freeze['status']})，请先处理现有冻结")

        before_snapshot = _get_queue_snapshot(book_id)

        freeze_id = str(uuid.uuid4())
        config_signature = freeze_store.compute_config_signature()

        is_effective_immediately = True
        effective_time = _now()
        if effective_at:
            try:
                et = datetime.fromisoformat(effective_at.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                if et > now:
                    is_effective_immediately = False
                    effective_time = effective_at
            except (ValueError, TypeError):
                return None, False, "effective_at 格式错误，应为 ISO 格式时间字符串"

        status = "pending" if not is_effective_immediately else "pending"

        order = {
            "freeze_id": freeze_id,
            "book_id": book_id,
            "book_title": book.get("title", ""),
            "reason": reason,
            "reason_detail": remark or "",
            "operator": operator,
            "role_at_create": role,
            "status": status,
            "idempotency_key": idempotency_key,
            "config_signature": config_signature,
            "effective_at": effective_time,
            "scheduled_effective_at": effective_time,
            "frozen_at": None,
            "restored_at": None,
            "revoked_at": None,
            "invalidated_at": None,
            "before_snapshot_summary": {
                "total_count": before_snapshot["total_count"],
                "waiting_count": before_snapshot["waiting_count"],
                "available_count": before_snapshot["available_count"],
                "borrowed_count": before_snapshot["borrowed_count"],
                "affected_reader_ids": [r["reader_id"] for r in before_snapshot["affected_readers"]],
            },
            "after_snapshot_summary": None,
            "restore_summary": None,
            "affected_reservation_ids": [],
            "restored_reservation_ids": [],
            "timeline": [
                {
                    "event": "created",
                    "timestamp": _now(),
                    "operator": operator,
                    "detail": (f"创建冻结单，原因={reason}，"
                               f"生效方式={'立即生效' if is_effective_immediately else f'定时生效 @ {effective_time}'}，"
                               f"影响读者 {before_snapshot['total_count']} 人"),
                }
            ],
            "created_at": _now(),
            "updated_at": _now(),
        }

        freeze_store.add_order(order)
        freeze_store.save_snapshot(freeze_id, "before", before_snapshot)

        _audit_log(freeze_id, "freeze_create", True, operator=operator,
                   detail=f"创建冻结单，book={book_id}，reason={reason}，"
                          f"影响 {before_snapshot['total_count']} 名读者",
                   idempotency_key=idempotency_key)

        if is_effective_immediately:
            updated_ids = _apply_freeze_to_reservations(book_id, freeze_id)
            order["affected_reservation_ids"] = updated_ids
            order["status"] = "frozen"
            order["frozen_at"] = _now()
            order["timeline"].append({
                "event": "frozen",
                "timestamp": _now(),
                "operator": operator,
                "detail": f"冻结立即生效，共冻结 {len(updated_ids)} 条预约",
            })
            freeze_store.update_order(freeze_id, {
                "affected_reservation_ids": updated_ids,
                "status": "frozen",
                "frozen_at": order["frozen_at"],
                "timeline": order["timeline"],
                "updated_at": _now(),
            })
            after_snapshot = _get_queue_snapshot(book_id)
            freeze_store.save_snapshot(freeze_id, "after_freeze", after_snapshot)
            order["after_snapshot_summary"] = {
                "total_count": after_snapshot["total_count"],
                "waiting_count": after_snapshot["waiting_count"],
                "available_count": after_snapshot["available_count"],
                "borrowed_count": after_snapshot["borrowed_count"],
                "frozen_count": len(updated_ids),
            }
            freeze_store.update_order(freeze_id, {
                "after_snapshot_summary": order["after_snapshot_summary"],
                "updated_at": _now(),
            })
            _audit_log(freeze_id, "freeze_effective", True, operator=operator,
                       detail=f"冻结生效，共 {len(updated_ids)} 条预约被冻结")

        return dict(order), False, None


def revoke_freeze(freeze_id, operator=None, role="viewer"):
    if not _is_feature_enabled():
        return None, "预约冻结功能已被系统管理员关闭"

    ok, err = _require_manager(role, "撤销冻结单")
    if not ok:
        return None, err

    order = freeze_store.get_order(freeze_id)
    if not order:
        return None, "冻结单不存在"

    if order["status"] not in ("pending",):
        return None, (f"冻结单状态为 {order['status']}，"
                      f"仅 pending 状态（未生效）的冻结单可撤销")

    with freeze_store._global_lock:
        order["status"] = "revoked"
        order["revoked_at"] = _now()
        order["updated_at"] = _now()
        order["timeline"].append({
            "event": "revoked",
            "timestamp": _now(),
            "operator": operator,
            "detail": "撤销未生效的冻结单",
        })
        freeze_store.update_order(freeze_id, {
            "status": "revoked",
            "revoked_at": order["revoked_at"],
            "updated_at": order["updated_at"],
            "timeline": order["timeline"],
        })

    _audit_log(freeze_id, "freeze_revoke", True, operator=operator,
               detail="撤销未生效冻结单")

    return dict(order), None


def restore_freeze(freeze_id, operator=None, role="viewer"):
    if not _is_feature_enabled():
        return None, "预约冻结功能已被系统管理员关闭"

    ok, err = _require_manager(role, "恢复冻结")
    if not ok:
        return None, err

    order = freeze_store.get_order(freeze_id)
    if not order:
        return None, "冻结单不存在"

    if order["status"] not in ("frozen", "restoring"):
        return None, (f"冻结单状态为 {order['status']}，"
                      f"仅 frozen 状态的冻结单可执行恢复")

    with freeze_store._global_lock:
        order["status"] = "restoring"
        order["updated_at"] = _now()
        order["timeline"].append({
            "event": "restoring_start",
            "timestamp": _now(),
            "operator": operator,
            "detail": "开始执行队列恢复",
        })
        freeze_store.update_order(freeze_id, {
            "status": "restoring",
            "updated_at": order["updated_at"],
            "timeline": order["timeline"],
        })

        restored_ids = _recover_reservations_from_freeze(
            order["book_id"], freeze_id
        )

        after_restore_snapshot = _get_queue_snapshot(order["book_id"])
        freeze_store.save_snapshot(freeze_id, "after_restore", after_restore_snapshot)

        order["restored_reservation_ids"] = restored_ids
        order["restore_summary"] = {
            "total_restored": len(restored_ids),
            "restored_to_waiting": len([
                r for r in after_restore_snapshot["affected_readers"]
                if r["status"] == "waiting"
            ]),
            "restored_to_available": len([
                r for r in after_restore_snapshot["affected_readers"]
                if r["status"] == "available"
            ]),
            "final_queue_total": after_restore_snapshot["total_count"],
        }
        order["status"] = "restored"
        order["restored_at"] = _now()
        order["updated_at"] = _now()
        order["timeline"].append({
            "event": "restored",
            "timestamp": _now(),
            "operator": operator,
            "detail": f"恢复完成，共恢复 {len(restored_ids)} 条预约",
        })
        freeze_store.update_order(freeze_id, {
            "restored_reservation_ids": restored_ids,
            "restore_summary": order["restore_summary"],
            "status": "restored",
            "restored_at": order["restored_at"],
            "updated_at": order["updated_at"],
            "timeline": order["timeline"],
        })

    _audit_log(freeze_id, "freeze_restore", True, operator=operator,
               detail=f"恢复完成，共恢复 {len(restored_ids)} 条预约",
               restored_count=len(restored_ids))

    return dict(order), None


def batch_restore(freeze_ids, operator=None, role="viewer"):
    if not _is_feature_enabled():
        return None, "预约冻结功能已被系统管理员关闭"

    ok, err = _require_manager(role, "批量恢复冻结")
    if not ok:
        return None, err

    results = {"succeeded": [], "failed": [], "total": len(freeze_ids)}
    for fid in freeze_ids:
        try:
            order, err = restore_freeze(fid, operator=operator, role=role)
            if err:
                results["failed"].append({"freeze_id": fid, "error": err})
            else:
                results["succeeded"].append({
                    "freeze_id": fid,
                    "restored_count": order.get("restore_summary", {}).get("total_restored", 0),
                })
        except Exception as e:
            results["failed"].append({"freeze_id": fid, "error": str(e)})

    _audit_log(None, "batch_restore", True, operator=operator,
               detail=f"批量恢复 {len(freeze_ids)} 个冻结单，"
                      f"成功 {len(results['succeeded'])}，"
                      f"失败 {len(results['failed'])}")

    return results, None


def list_freezes(book_id=None, reason=None, status=None, operator=None, limit=100):
    orders = freeze_store.load_orders()
    if book_id:
        orders = [o for o in orders if o.get("book_id") == book_id]
    if reason:
        orders = [o for o in orders if o.get("reason") == reason]
    if status:
        orders = [o for o in orders if o.get("status") == status]
    if operator:
        orders = [o for o in orders if o.get("operator") == operator]
    orders_sorted = sorted(orders, key=lambda o: o.get("created_at", ""), reverse=True)
    return orders_sorted[:limit]


def get_freeze(freeze_id, role="viewer"):
    order = freeze_store.get_order(freeze_id)
    if not order:
        return None, "冻结单不存在"

    result = dict(order)
    stale = _check_config_stale(freeze_id)
    result["config_stale"] = stale
    result["_role"] = role
    return result, None


def get_freeze_snapshot(freeze_id, snapshot_type, role="viewer"):
    order = freeze_store.get_order(freeze_id)
    if not order:
        return None, "冻结单不存在"

    snapshot = freeze_store.load_snapshot(freeze_id, snapshot_type)
    if snapshot is None:
        return None, f"快照类型 {snapshot_type} 不存在，可用: before, after_freeze, after_restore"

    return snapshot, None


def export_freeze_report(freeze_id, role="viewer"):
    order = freeze_store.get_order(freeze_id)
    if not order:
        return None, "冻结单不存在"

    stale = _check_config_stale(freeze_id)
    before_snapshot = freeze_store.load_snapshot(freeze_id, "before") or {}
    after_freeze_snapshot = freeze_store.load_snapshot(freeze_id, "after_freeze") or {}
    after_restore_snapshot = freeze_store.load_snapshot(freeze_id, "after_restore") or {}

    affected_readers = []
    if before_snapshot:
        affected_readers = before_snapshot.get("affected_readers", [])

    report = {
        "report_id": str(uuid.uuid4()),
        "report_type": "freeze_report",
        "report_version": "1.0",
        "freeze_id": freeze_id,
        "book_id": order.get("book_id"),
        "book_title": order.get("book_title"),
        "operator": order.get("operator"),
        "role_at_create": order.get("role_at_create"),
        "freeze_reason": order.get("reason"),
        "freeze_reason_detail": order.get("reason_detail"),
        "status": order.get("status"),
        "idempotency_key": order.get("idempotency_key"),
        "config_signature": order.get("config_signature"),
        "config_stale": stale,
        "effective_at": order.get("effective_at"),
        "frozen_at": order.get("frozen_at"),
        "restored_at": order.get("restored_at"),
        "revoked_at": order.get("revoked_at"),
        "invalidated_at": order.get("invalidated_at"),
        "created_at": order.get("created_at"),
        "updated_at": order.get("updated_at"),
        "exported_at": _now(),
        "impact_summary": {
            "total_affected_readers": len(affected_readers),
            "affected_reader_ids": list({r["reader_id"] for r in affected_readers}),
            "frozen_reservation_count": len(order.get("affected_reservation_ids", [])),
            "restored_reservation_count": len(order.get("restored_reservation_ids", [])),
            "before_queue": order.get("before_snapshot_summary"),
            "after_freeze_queue": order.get("after_snapshot_summary"),
            "restore_result": order.get("restore_summary"),
        },
        "affected_readers_detail": affected_readers,
        "timeline": order.get("timeline", []),
        "snapshots": {
            "before_freeze": {
                "present": bool(before_snapshot),
                "time": before_snapshot.get("snapshot_time"),
                "summary": order.get("before_snapshot_summary"),
            },
            "after_freeze": {
                "present": bool(after_freeze_snapshot),
                "time": after_freeze_snapshot.get("snapshot_time"),
                "summary": order.get("after_snapshot_summary"),
            },
            "after_restore": {
                "present": bool(after_restore_snapshot),
                "time": after_restore_snapshot.get("snapshot_time"),
                "summary": order.get("restore_summary"),
            },
        },
        "audit_logs": [
            l for l in freeze_store.load_audit_logs()
            if l.get("freeze_id") == freeze_id
        ],
    }

    if stale:
        report["stale_warning"] = "当前环境书目配置与冻结创建时不同，本报告的历史数据仅供参考"

    _audit_log(freeze_id, "freeze_export_report", True, operator=None,
               detail=f"导出冻结报告: {report['report_id']}")

    return report, None


def list_audit_logs(freeze_id=None, operator=None, action=None, limit=200):
    logs = freeze_store.load_audit_logs()
    if freeze_id:
        logs = [l for l in logs if l.get("freeze_id") == freeze_id]
    if operator:
        logs = [l for l in logs if l.get("operator") == operator]
    if action:
        logs = [l for l in logs if l.get("action") == action]
    logs_sorted = sorted(logs, key=lambda l: l.get("timestamp", ""), reverse=True)
    return logs_sorted[:limit]


def get_feature_config(role="viewer"):
    config = freeze_store.load_config()
    return {
        "enabled": config.get("enabled", True),
        "version": config.get("version"),
        "updated_at": config.get("updated_at"),
        "updated_by": config.get("updated_by"),
        "reasons": list(_VALID_REASONS),
        "statuses": list(_VALID_STATUSES),
        "current_role": role,
        "require_manager_for_write": _REQUIRE_MANAGER_ROLE,
    }


def update_feature_config(enabled, operator=None, role="viewer"):
    ok, err = _require_manager(role, "修改冻结功能配置")
    if not ok:
        return None, err

    config = freeze_store.update_config_enabled(enabled, operator=operator)

    if not enabled:
        invalidated = invalidate_pending_on_disable(operator=operator)
        _audit_log(None, "freeze_config_disable", True, operator=operator,
                   detail=f"关闭冻结功能，自动失效了 {len(invalidated)} 个未生效冻结单")
        result = {
            "config": config,
            "auto_invalidated_count": len(invalidated),
            "auto_invalidated_ids": invalidated,
        }
        return result, None

    _audit_log(None, "freeze_config_enable", True, operator=operator,
               detail="开启冻结功能")
    return {"config": config}, None


def invalidate_pending_on_disable(operator=None):
    invalidated = []
    orders = freeze_store.load_orders()
    for o in orders:
        if o.get("status") == "pending":
            o["status"] = "auto_invalidated"
            o["invalidated_at"] = _now()
            o["updated_at"] = _now()
            o.setdefault("timeline", []).append({
                "event": "auto_invalidated",
                "timestamp": _now(),
                "operator": operator,
                "detail": "因冻结功能被关闭，未生效冻结单自动失效",
            })
            freeze_store.update_order(o["freeze_id"], {
                "status": "auto_invalidated",
                "invalidated_at": o["invalidated_at"],
                "updated_at": o["updated_at"],
                "timeline": o["timeline"],
            })
            _audit_log(o["freeze_id"], "freeze_auto_invalidate", True,
                       operator=operator,
                       detail="因冻结功能关闭，未生效冻结单自动失效")
            invalidated.append(o["freeze_id"])
    return invalidated


def _check_config_stale(freeze_id):
    order = freeze_store.get_order(freeze_id)
    if not order:
        return False
    current_sig = freeze_store.compute_config_signature()
    return order.get("config_signature") != current_sig


def recover_on_startup():
    recovered = []
    orders = freeze_store.load_orders()
    for o in orders:
        status = o.get("status")
        if status == "pending" and o.get("frozen_at") is None:
            affected = o.get("affected_reservation_ids") or []
            if affected:
                o["status"] = "frozen"
                o["frozen_at"] = o["frozen_at"] or _now()
                o["updated_at"] = _now()
                o.setdefault("timeline", []).append({
                    "event": "recovered_frozen",
                    "timestamp": _now(),
                    "operator": "system",
                    "detail": "服务重启恢复：检测到预约已冻结，修正状态为 frozen",
                })
                freeze_store.update_order(o["freeze_id"], {
                    "status": "frozen",
                    "frozen_at": o["frozen_at"],
                    "updated_at": o["updated_at"],
                    "timeline": o["timeline"],
                })
                recovered.append({
                    "freeze_id": o["freeze_id"],
                    "book_id": o["book_id"],
                    "previous_status": "pending",
                    "new_status": "frozen",
                    "reason": "restored frozen state on startup",
                })
            continue
        if status == "restoring":
            o["status"] = "frozen"
            o["updated_at"] = _now()
            o.setdefault("timeline", []).append({
                "event": "recovered_from_restoring",
                "timestamp": _now(),
                "operator": "system",
                "detail": "服务重启恢复：检测到恢复中断，回滚为 frozen 状态，需重新执行恢复",
            })
            freeze_store.update_order(o["freeze_id"], {
                "status": "frozen",
                "updated_at": o["updated_at"],
                "timeline": o["timeline"],
            })
            recovered.append({
                "freeze_id": o["freeze_id"],
                "book_id": o["book_id"],
                "previous_status": "restoring",
                "new_status": "frozen",
                "reason": "interrupted restore rolled back",
            })
    return recovered


def invalidate_stale_freezes():
    invalidated = []
    orders = freeze_store.load_orders()
    for o in orders:
        if o.get("status") == "pending" and not o.get("frozen_at"):
            current_sig = freeze_store.compute_config_signature()
            if o.get("config_signature") and o["config_signature"] != current_sig:
                o["status"] = "auto_invalidated"
                o["invalidated_at"] = _now()
                o["updated_at"] = _now()
                o.setdefault("timeline", []).append({
                    "event": "stale_invalidated",
                    "timestamp": _now(),
                    "operator": "system",
                    "detail": "服务启动：配置签名已变化，未生效冻结单自动失效",
                })
                freeze_store.update_order(o["freeze_id"], {
                    "status": "auto_invalidated",
                    "invalidated_at": o["invalidated_at"],
                    "updated_at": o["updated_at"],
                    "timeline": o["timeline"],
                })
                _audit_log(o["freeze_id"], "freeze_stale_invalidate", True,
                           operator="system",
                           detail="服务启动检测到配置变更，未生效冻结单自动失效")
                invalidated.append({
                    "freeze_id": o["freeze_id"],
                    "book_id": o["book_id"],
                    "previous_status": "pending",
                    "new_status": "auto_invalidated",
                })
    return invalidated

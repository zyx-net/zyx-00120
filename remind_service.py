import uuid
from datetime import datetime, timezone

import remind_store
import store

_VALID_TRIGGER_REASONS = ("overdue_pickup", "long_waiting", "manual")
_VALID_STATUSES = ("pending", "processed", "revoked", "expired")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _remind_log(order_id, action, success, operator=None, detail=""):
    log_entry = {
        "log_id": str(uuid.uuid4()),
        "timestamp": _now(),
        "order_id": order_id,
        "action": action,
        "operator": operator,
        "detail": detail,
        "success": success,
    }
    remind_store.append_log(log_entry)
    return log_entry


def create_remind(reservation_id, trigger_reason, operator=None, remark=None):
    if trigger_reason not in _VALID_TRIGGER_REASONS:
        return None, f"触发原因不合法，允许值: {', '.join(_VALID_TRIGGER_REASONS)}"

    reservation = store.get_reservation(reservation_id)
    if not reservation:
        return None, f"预约记录 {reservation_id} 不存在"

    if reservation["status"] not in ("waiting", "available", "borrowed"):
        return None, f"预约状态为 {reservation['status']}，不在活跃状态，无法催办"

    with remind_store._global_lock:
        existing_orders = remind_store.load_orders()
        for o in existing_orders:
            if (o.get("reservation_id") == reservation_id
                    and o.get("status") not in ("revoked", "expired")):
                return None, (f"该预约已存在有效催办单: {o['order_id']} "
                              f"(状态: {o.get('status')})，请勿重复创建")

        order_id = str(uuid.uuid4())
        config_signature = remind_store.compute_config_signature()

        order = {
            "order_id": order_id,
            "reservation_id": reservation_id,
            "book_id": reservation["book_id"],
            "reader_id": reservation["reader_id"],
            "trigger_reason": trigger_reason,
            "status": "pending",
            "operator": operator,
            "remark": remark or "",
            "config_signature": config_signature,
            "reservation_status_at_create": reservation["status"],
            "timeline": [
                {
                    "event": "created",
                    "timestamp": _now(),
                    "operator": operator,
                    "detail": f"创建催办单，触发原因: {trigger_reason}，预约状态: {reservation['status']}",
                }
            ],
            "created_at": _now(),
            "updated_at": _now(),
            "revoked_at": None,
            "expired_at": None,
            "final_status": None,
        }
        remind_store.add_order(order)

        _remind_log(order_id, "remind_create", True, operator=operator,
                    detail=f"创建催办单，触发原因: {trigger_reason}，预约: {reservation_id}")

    return order, None


def list_reminds(status=None, book_id=None, reader_id=None, trigger_reason=None, limit=100):
    orders = remind_store.load_orders()
    if status:
        orders = [o for o in orders if o.get("status") == status]
    if book_id:
        orders = [o for o in orders if o.get("book_id") == book_id]
    if reader_id:
        orders = [o for o in orders if o.get("reader_id") == reader_id]
    if trigger_reason:
        orders = [o for o in orders if o.get("trigger_reason") == trigger_reason]
    orders_sorted = sorted(orders, key=lambda o: o.get("created_at", ""), reverse=True)
    return orders_sorted[:limit]


def get_remind(order_id):
    order = remind_store.get_order(order_id)
    if not order:
        return None, "催办单不存在"

    result = dict(order)
    stale = _check_config_stale(order_id)
    result["config_stale"] = stale
    return result, None


def export_remind_report(order_id):
    order = remind_store.get_order(order_id)
    if not order:
        return None, "催办单不存在"

    stale = _check_config_stale(order_id)
    timeline = order.get("timeline", [])

    report = {
        "report_id": str(uuid.uuid4()),
        "order_id": order_id,
        "reservation_id": order.get("reservation_id"),
        "book_id": order.get("book_id"),
        "reader_id": order.get("reader_id"),
        "trigger_reason": order.get("trigger_reason"),
        "status": order.get("status"),
        "operator": order.get("operator"),
        "remark": order.get("remark"),
        "config_signature": order.get("config_signature"),
        "config_stale": stale,
        "reservation_status_at_create": order.get("reservation_status_at_create"),
        "timeline": timeline,
        "created_at": order.get("created_at"),
        "updated_at": order.get("updated_at"),
        "revoked_at": order.get("revoked_at"),
        "expired_at": order.get("expired_at"),
        "final_status": order.get("final_status") or order.get("status"),
        "exported_at": _now(),
    }
    if stale:
        report["stale_warning"] = "当前环境配置与催办时不同，本报告可能已失效"

    _remind_log(order_id, "remind_export", True,
                detail=f"导出催办报告: {report['report_id']}")

    return report, None


def revoke_remind(order_id, operator=None):
    order = remind_store.get_order(order_id)
    if not order:
        return None, "催办单不存在"

    if order.get("status") == "revoked":
        return None, "该催办单已撤销，不可重复操作"

    if order.get("status") == "expired":
        return None, "该催办单已失效，不可撤销"

    with remind_store._global_lock:
        fresh = remind_store.get_order(order_id)
        if not fresh:
            return None, "催办单不存在"
        if fresh.get("status") == "revoked":
            return None, "该催办单已撤销，不可重复操作"
        if fresh.get("status") == "expired":
            return None, "该催办单已失效，不可撤销"

        now = _now()
        timeline = fresh.get("timeline", [])
        timeline.append({
            "event": "revoked",
            "timestamp": now,
            "operator": operator,
            "detail": f"撤销催办单，操作者: {operator or '未知'}",
        })

        remind_store.update_order(order_id, {
            "status": "revoked",
            "revoked_at": now,
            "revoked_by": operator,
            "final_status": "revoked",
            "timeline": timeline,
            "updated_at": now,
        })

        _remind_log(order_id, "remind_revoke", True, operator=operator,
                    detail=f"撤销催办单，操作者: {operator or '未知'}")

    updated = remind_store.get_order(order_id)
    return updated, None


def _check_config_stale(order_id):
    order = remind_store.get_order(order_id)
    if not order:
        return False
    original_sig = order.get("config_signature", "")
    if not original_sig:
        return False
    current_sig = remind_store.compute_config_signature()
    return original_sig != current_sig


def recover_reminds_on_startup():
    recovered = []
    orders = remind_store.load_orders()
    for o in orders:
        oid = o["order_id"]
        status = o.get("status", "")
        if status == "pending":
            remind_store.update_order(oid, {
                "status": "processed",
                "updated_at": _now(),
                "recovered_note": f"服务重启，由状态 {status} 恢复为 processed",
            })
            timeline = o.get("timeline", [])
            timeline.append({
                "event": "recovered",
                "timestamp": _now(),
                "operator": None,
                "detail": f"服务重启，催办单由状态 {status} 恢复为 processed",
            })
            remind_store.update_order(oid, {"timeline": timeline})
            recovered.append({
                "order_id": oid,
                "previous_status": status,
                "new_status": "processed",
            })
    return recovered


def invalidate_stale_reminds():
    invalidated = []
    orders = remind_store.load_orders()
    for o in orders:
        oid = o["order_id"]
        status = o.get("status", "")
        if status not in ("pending", "processed"):
            continue
        stale = _check_config_stale(oid)
        if stale:
            now = _now()
            timeline = o.get("timeline", [])
            timeline.append({
                "event": "expired",
                "timestamp": now,
                "operator": None,
                "detail": "馆藏配置已变更，催办单自动失效",
            })
            remind_store.update_order(oid, {
                "status": "expired",
                "expired_at": now,
                "expire_reason": "馆藏配置已变更，催办单失效",
                "final_status": "expired",
                "timeline": timeline,
                "updated_at": now,
            })
            _remind_log(oid, "remind_expire", True,
                        detail="馆藏配置变更，催办单自动失效")
            invalidated.append({
                "order_id": oid,
                "previous_status": status,
                "new_status": "expired",
            })
    return invalidated

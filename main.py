import threading

from flask import Flask, request, jsonify

import service
import sandbox_service
import checkup_service
import remind_service

app = Flask(__name__)

_expire_timer = None


def _schedule_expire():
    global _expire_timer
    _expire_timer = threading.Timer(10, _expire_tick)
    _expire_timer.daemon = True
    _expire_timer.start()


def _expire_tick():
    service.process_expired()
    _schedule_expire()


@app.route("/api/books", methods=["POST"])
def api_add_book():
    d = request.get_json(force=True)
    book, err = service.add_book(
        d["book_id"], d["title"], d["total_copies"],
        d["borrow_days"], d["retain_hours"],
    )
    if err:
        return jsonify({"ok": False, "error": err}), 400
    return jsonify({"ok": True, "data": book}), 201


@app.route("/api/books/<book_id>", methods=["PUT"])
def api_update_book(book_id):
    d = request.get_json(force=True)
    book, err = service.update_book(
        book_id,
        title=d.get("title"),
        total_copies=d.get("total_copies"),
        borrow_days=d.get("borrow_days"),
        retain_hours=d.get("retain_hours"),
    )
    if err:
        return jsonify({"ok": False, "error": err}), 404
    return jsonify({"ok": True, "data": book}), 200


@app.route("/api/books/<book_id>", methods=["DELETE"])
def api_delete_book(book_id):
    ok, err = service.delete_book(book_id)
    if not ok:
        return jsonify({"ok": False, "error": err}), 404
    return jsonify({"ok": True}), 200


@app.route("/api/books", methods=["GET"])
def api_list_books():
    books = service.list_books()
    return jsonify({"ok": True, "data": books}), 200


@app.route("/api/books/<book_id>", methods=["GET"])
def api_get_book(book_id):
    book = service.get_book(book_id)
    if not book:
        return jsonify({"ok": False, "error": f"书目 {book_id} 不存在"}), 404
    return jsonify({"ok": True, "data": book}), 200


@app.route("/api/reserve", methods=["POST"])
def api_reserve():
    d = request.get_json(force=True)
    res, err = service.reserve(d["book_id"], d["reader_id"])
    if err:
        return jsonify({"ok": False, "error": err}), 409
    return jsonify({"ok": True, "data": res}), 201


@app.route("/api/queue/<book_id>", methods=["GET"])
def api_queue(book_id):
    queue = service.get_queue(book_id)
    return jsonify({"ok": True, "data": queue}), 200


@app.route("/api/position/<book_id>/<reader_id>", methods=["GET"])
def api_position(book_id, reader_id):
    pos = service.get_position(book_id, reader_id)
    if pos < 0:
        return jsonify({"ok": False, "error": "读者不在队列中"}), 404
    return jsonify({"ok": True, "position": pos}), 200


@app.route("/api/reserve/<reservation_id>", methods=["DELETE"])
def api_cancel(reservation_id):
    reader_id = request.args.get("reader_id", "")
    ok, err = service.cancel_reservation(reservation_id, reader_id)
    if not ok:
        return jsonify({"ok": False, "error": err}), 409
    return jsonify({"ok": True}), 200


@app.route("/api/checkout", methods=["POST"])
def api_checkout():
    d = request.get_json(force=True)
    res, err = service.checkout(d["book_id"], d["reader_id"])
    if err:
        return jsonify({"ok": False, "error": err}), 409
    return jsonify({"ok": True, "data": res}), 200


@app.route("/api/return", methods=["POST"])
def api_return():
    d = request.get_json(force=True)
    res, err = service.return_book(d["book_id"], d["reader_id"])
    if err:
        return jsonify({"ok": False, "error": err}), 409
    return jsonify({"ok": True, "data": res}), 200


@app.route("/api/blacklist", methods=["POST"])
def api_add_blacklist():
    d = request.get_json(force=True)
    ok, err = service.add_blacklist(d["reader_id"], d.get("reason", ""))
    if not ok:
        return jsonify({"ok": False, "error": err}), 409
    return jsonify({"ok": True}), 201


@app.route("/api/blacklist/<reader_id>", methods=["DELETE"])
def api_remove_blacklist(reader_id):
    ok, err = service.remove_blacklist(reader_id)
    if not ok:
        return jsonify({"ok": False, "error": err}), 404
    return jsonify({"ok": True}), 200


@app.route("/api/blacklist", methods=["GET"])
def api_get_blacklist():
    bl = service.get_blacklist()
    return jsonify({"ok": True, "data": bl}), 200


@app.route("/api/logs", methods=["GET"])
def api_logs():
    book_id = request.args.get("book_id")
    reader_id = request.args.get("reader_id")
    limit = request.args.get("limit", 100, type=int)
    logs = service.get_logs(book_id=book_id, reader_id=reader_id, limit=limit)
    return jsonify({"ok": True, "data": logs}), 200


@app.route("/api/export/<book_id>", methods=["GET"])
def api_export(book_id):
    snapshot, err = service.export_queue(book_id)
    if err:
        return jsonify({"ok": False, "error": err}), 404
    return jsonify({"ok": True, "data": snapshot}), 200


@app.route("/api/collection/export", methods=["GET"])
def api_export_collection():
    export_data, err = service.export_collection()
    if err:
        return jsonify({"ok": False, "error": err}), 500
    return jsonify({"ok": True, "data": export_data}), 200


@app.route("/api/collection/import", methods=["POST"])
def api_import_collection():
    d = request.get_json(force=True)
    dry_run = request.args.get("dry_run", "false").lower() == "true"
    imported_count, conflicts, errors = service.import_collection(d, dry_run=dry_run)
    if errors:
        return jsonify({"ok": False, "error": errors}), 400
    if conflicts:
        return jsonify({
            "ok": False,
            "error": "导入存在冲突",
            "conflicts": conflicts,
            "dry_run": dry_run,
        }), 409
    return jsonify({
        "ok": True,
        "imported_count": imported_count,
        "dry_run": dry_run,
    }), 200 if not dry_run else 200


@app.route("/api/snapshot/export", methods=["GET"])
def api_export_snapshot():
    snapshot, err = service.export_snapshot()
    if err:
        return jsonify({"ok": False, "error": err}), 500
    return jsonify({"ok": True, "data": snapshot}), 200


@app.route("/api/snapshot/import", methods=["POST"])
def api_import_snapshot():
    d = request.get_json(force=True)
    dry_run = request.args.get("dry_run", "false").lower() == "true"
    result = service.import_snapshot(d, dry_run=dry_run)
    imported_counts, conflicts, errors, report = result[:4]
    batch_id = result[4] if len(result) > 4 else None
    if errors:
        resp = {"ok": False, "error": errors, "dry_run": dry_run}
        if report is not None:
            resp["report"] = report
        return jsonify(resp), 400
    if conflicts:
        resp = {
            "ok": False,
            "error": "快照导入存在冲突",
            "conflicts": conflicts,
            "dry_run": dry_run,
        }
        if report is not None:
            resp["report"] = report
        return jsonify(resp), 409
    resp = {
        "ok": True,
        "imported_counts": imported_counts,
        "dry_run": dry_run,
    }
    if report is not None:
        resp["report"] = report
    if batch_id is not None:
        resp["batch_id"] = batch_id
    return jsonify(resp), 200


@app.route("/api/snapshot/precheck", methods=["POST"])
def api_precheck_snapshot():
    d = request.get_json(force=True)
    report, errors = service.precheck_snapshot(d)
    if errors:
        return jsonify({"ok": False, "error": errors}), 400
    return jsonify({
        "ok": True,
        "data": report,
    }), 200


@app.route("/api/batches", methods=["GET"])
def api_list_batches():
    limit = request.args.get("limit", 100, type=int)
    batches = service.list_import_batches(limit=limit)
    return jsonify({"ok": True, "data": batches}), 200


@app.route("/api/batches/<batch_id>", methods=["GET"])
def api_get_batch(batch_id):
    batch, err = service.get_import_batch(batch_id)
    if err:
        return jsonify({"ok": False, "error": err}), 404
    return jsonify({"ok": True, "data": batch}), 200


@app.route("/api/batches/<batch_id>/export", methods=["GET"])
def api_export_batch(batch_id):
    snapshot, err = service.export_batch(batch_id)
    if err:
        return jsonify({"ok": False, "error": err}), 404
    return jsonify({"ok": True, "data": snapshot}), 200


@app.route("/api/batches/<batch_id>/rollback", methods=["POST"])
def api_rollback_batch(batch_id):
    result, err, batch = service.rollback_batch(batch_id)
    if err:
        if isinstance(err, dict):
            resp = {"ok": False, **err}
            if batch is not None:
                resp["batch"] = {
                    "batch_id": batch["batch_id"],
                    "status": batch["status"],
                }
            return jsonify(resp), 409
        return jsonify({"ok": False, "error": err}), 400
    resp = {"ok": True, **result}
    if batch is not None:
        resp["batch"] = {
            "batch_id": batch["batch_id"],
            "status": batch["status"],
            "rolled_back_at": batch.get("rolled_back_at"),
        }
    return jsonify(resp), 200


@app.route("/api/expire", methods=["POST"])
def api_trigger_expire():
    count = service.process_expired()
    return jsonify({"ok": True, "expired_count": count}), 200


@app.route("/api/sandbox", methods=["POST"])
def api_create_sandbox():
    d = request.get_json(force=True)
    snapshot = d.get("snapshot")
    name = d.get("name")
    if not snapshot:
        return jsonify({"ok": False, "error": "缺少 snapshot 字段"}), 400
    result, err = sandbox_service.create_sandbox(snapshot, name=name)
    if err:
        if isinstance(err, list):
            return jsonify({"ok": False, "error": err}), 400
        if isinstance(err, str) and "已存在相同快照" in err:
            return jsonify({"ok": False, "error": err}), 409
        return jsonify({"ok": False, "error": err}), 400
    full_result, _ = sandbox_service.get_sandbox(result["sandbox_id"])
    return jsonify({"ok": True, "data": full_result}), 201


@app.route("/api/sandbox", methods=["GET"])
def api_list_sandboxes():
    limit = request.args.get("limit", 100, type=int)
    sandboxes = sandbox_service.list_sandboxes(limit=limit)
    return jsonify({"ok": True, "data": sandboxes}), 200


@app.route("/api/sandbox/<sandbox_id>", methods=["GET"])
def api_get_sandbox(sandbox_id):
    result, err = sandbox_service.get_sandbox(sandbox_id)
    if err:
        return jsonify({"ok": False, "error": err}), 404
    return jsonify({"ok": True, "data": result}), 200


@app.route("/api/sandbox/<sandbox_id>/precheck", methods=["POST"])
def api_sandbox_precheck(sandbox_id):
    result, err = sandbox_service.run_sandbox_precheck(sandbox_id)
    if err:
        if isinstance(err, list):
            return jsonify({"ok": False, "error": err}), 400
        if str(err) == "沙箱不存在":
            return jsonify({"ok": False, "error": err}), 404
        if "配置已变更" in str(err):
            return jsonify({"ok": False, "error": err, "config_stale": True}), 410
        return jsonify({"ok": False, "error": err}), 400
    return jsonify({"ok": True, "data": result}), 200


@app.route("/api/sandbox/<sandbox_id>/dryrun", methods=["POST"])
def api_sandbox_dryrun(sandbox_id):
    result, err = sandbox_service.run_sandbox_dryrun(sandbox_id)
    if err:
        if str(err) == "沙箱不存在":
            return jsonify({"ok": False, "error": err}), 404
        if isinstance(err, list):
            if all(isinstance(e, dict) and "type" in e for e in err):
                return jsonify({"ok": False, "error": "沙箱 Dry-Run 发现冲突", "conflicts": err}), 409
            return jsonify({"ok": False, "error": err}), 400
        if "配置已变更" in str(err):
            return jsonify({"ok": False, "error": err, "config_stale": True}), 410
        if isinstance(err, dict):
            return jsonify({"ok": False, "error": "沙箱 Dry-Run 发现冲突", "conflicts": err}), 409
        return jsonify({"ok": False, "error": err}), 400
    return jsonify({"ok": True, "data": result}), 200


@app.route("/api/sandbox/<sandbox_id>/import", methods=["POST"])
def api_sandbox_import(sandbox_id):
    result, err = sandbox_service.run_sandbox_import(sandbox_id)
    if err:
        if str(err) == "沙箱不存在":
            return jsonify({"ok": False, "error": err}), 404
        if isinstance(err, list):
            if all(isinstance(e, dict) and "type" in e for e in err):
                return jsonify({"ok": False, "error": "沙箱导入发现冲突", "conflicts": err}), 409
            return jsonify({"ok": False, "error": err}), 400
        if "配置已变更" in str(err):
            return jsonify({"ok": False, "error": err, "config_stale": True}), 410
        if isinstance(err, dict):
            return jsonify({"ok": False, "error": "沙箱导入发现冲突", "conflicts": err}), 409
        if "已执行过正式导入" in str(err):
            return jsonify({"ok": False, "error": err}), 409
        return jsonify({"ok": False, "error": err}), 400
    return jsonify({"ok": True, "data": result}), 200


@app.route("/api/sandbox/<sandbox_id>/rollback", methods=["POST"])
def api_sandbox_rollback(sandbox_id):
    result, err = sandbox_service.run_sandbox_rollback(sandbox_id)
    if err:
        if str(err) == "沙箱不存在":
            return jsonify({"ok": False, "error": err}), 404
        if isinstance(err, dict) and "conflicts" in err:
            return jsonify({"ok": False, **err}), 409
        return jsonify({"ok": False, "error": err}), 400
    return jsonify({"ok": True, **result}), 200


@app.route("/api/sandbox/<sandbox_id>/restart-verify", methods=["POST"])
def api_sandbox_restart_verify(sandbox_id):
    result, err = sandbox_service.run_sandbox_restart_verify(sandbox_id)
    if err:
        return jsonify({"ok": False, "error": err}), 404
    return jsonify({"ok": True, "data": result}), 200


@app.route("/api/sandbox/<sandbox_id>/export", methods=["GET"])
def api_sandbox_export(sandbox_id):
    result, err = sandbox_service.export_sandbox_results(sandbox_id)
    if err:
        return jsonify({"ok": False, "error": err}), 404
    return jsonify({"ok": True, "data": result}), 200


@app.route("/api/sandbox/<sandbox_id>", methods=["DELETE"])
def api_destroy_sandbox(sandbox_id):
    ok, err = sandbox_service.destroy_sandbox(sandbox_id)
    if err:
        return jsonify({"ok": False, "error": err}), 404
    return jsonify({"ok": True, "message": f"沙箱 {sandbox_id} 已销毁"}), 200


@app.route("/api/checkup", methods=["POST"])
def api_create_checkup():
    d = request.get_json(force=True)
    snapshot = d.get("snapshot")
    if not snapshot:
        return jsonify({"ok": False, "error": "缺少 snapshot 字段"}), 400
    operator = d.get("operator")
    name = d.get("name")
    record, err = checkup_service.create_checkup(snapshot, operator=operator, name=name)
    if err:
        if "已存在" in str(err):
            return jsonify({"ok": False, "error": err}), 409
        return jsonify({"ok": False, "error": err}), 400
    full_result, _ = checkup_service.get_checkup(record["record_id"])
    return jsonify({"ok": True, "data": full_result}), 201


@app.route("/api/checkup", methods=["GET"])
def api_list_checkups():
    limit = request.args.get("limit", 100, type=int)
    records = checkup_service.list_checkups(limit=limit)
    return jsonify({"ok": True, "data": records}), 200


@app.route("/api/checkup/<record_id>", methods=["GET"])
def api_get_checkup(record_id):
    result, err = checkup_service.get_checkup(record_id)
    if err:
        return jsonify({"ok": False, "error": err}), 404
    return jsonify({"ok": True, "data": result}), 200


@app.route("/api/checkup/<record_id>/export", methods=["GET"])
def api_export_checkup(record_id):
    report, err = checkup_service.export_checkup_report(record_id)
    if err:
        return jsonify({"ok": False, "error": err}), 404
    return jsonify({"ok": True, "data": report}), 200


@app.route("/api/checkup/<record_id>/void", methods=["POST"])
def api_void_checkup(record_id):
    d = request.get_json(force=True) if request.is_json else {}
    operator = d.get("operator")
    record, err = checkup_service.void_checkup(record_id, operator=operator)
    if err:
        if "已作废" in str(err):
            return jsonify({"ok": False, "error": err}), 409
        return jsonify({"ok": False, "error": err}), 404
    return jsonify({"ok": True, "data": record}), 200


@app.route("/api/remind", methods=["POST"])
def api_create_remind():
    d = request.get_json(force=True)
    reservation_id = d.get("reservation_id")
    trigger_reason = d.get("trigger_reason")
    if not reservation_id:
        return jsonify({"ok": False, "error": "缺少 reservation_id 字段"}), 400
    if not trigger_reason:
        return jsonify({"ok": False, "error": "缺少 trigger_reason 字段"}), 400
    operator = d.get("operator")
    remark = d.get("remark")
    order, err = remind_service.create_remind(reservation_id, trigger_reason, operator=operator, remark=remark)
    if err:
        if "已存在" in str(err):
            return jsonify({"ok": False, "error": err}), 409
        return jsonify({"ok": False, "error": err}), 400
    full_result, _ = remind_service.get_remind(order["order_id"])
    return jsonify({"ok": True, "data": full_result}), 201


@app.route("/api/remind", methods=["GET"])
def api_list_reminds():
    status = request.args.get("status")
    book_id = request.args.get("book_id")
    reader_id = request.args.get("reader_id")
    trigger_reason = request.args.get("trigger_reason")
    limit = request.args.get("limit", 100, type=int)
    orders = remind_service.list_reminds(
        status=status, book_id=book_id, reader_id=reader_id,
        trigger_reason=trigger_reason, limit=limit,
    )
    return jsonify({"ok": True, "data": orders}), 200


@app.route("/api/remind/<order_id>", methods=["GET"])
def api_get_remind(order_id):
    result, err = remind_service.get_remind(order_id)
    if err:
        return jsonify({"ok": False, "error": err}), 404
    return jsonify({"ok": True, "data": result}), 200


@app.route("/api/remind/<order_id>/export", methods=["GET"])
def api_export_remind(order_id):
    report, err = remind_service.export_remind_report(order_id)
    if err:
        return jsonify({"ok": False, "error": err}), 404
    return jsonify({"ok": True, "data": report}), 200


@app.route("/api/remind/<order_id>/revoke", methods=["POST"])
def api_revoke_remind(order_id):
    d = request.get_json(force=True) if request.is_json else {}
    operator = d.get("operator")
    order, err = remind_service.revoke_remind(order_id, operator=operator)
    if err:
        if "已撤销" in str(err):
            return jsonify({"ok": False, "error": err}), 409
        if "已失效" in str(err):
            return jsonify({"ok": False, "error": err}), 409
        return jsonify({"ok": False, "error": err}), 404
    return jsonify({"ok": True, "data": order}), 200


def main():
    import store as _store
    import checkup_store as _checkup_store
    import remind_store as _remind_store
    print(f"[启动] 数据目录: {_store.DATA_DIR}")
    print(f"[启动] 体检目录: {_checkup_store.CHECKUP_BASE_DIR}")
    print(f"[启动] 催办目录: {_remind_store.REMIND_BASE_DIR}")
    print("[启动] 检查并处理过期预约...")
    service.process_expired()
    print("[启动] 过期检查完成，启动定时过期扫描（每10秒）")
    _schedule_expire()
    recovered = sandbox_service.recover_sandboxes_on_startup()
    if recovered:
        print(f"[启动] 恢复了 {len(recovered)} 个异常中断的演练沙箱")
        for r in recovered:
            print(f"  - 沙箱 {r['sandbox_id']}: {r['previous_status']} -> {r['new_status']}")
    checkup_recovered = checkup_service.recover_checkups_on_startup()
    if checkup_recovered:
        print(f"[启动] 恢复了 {len(checkup_recovered)} 个异常中断的体检记录")
        for r in checkup_recovered:
            print(f"  - 体检 {r['record_id']}: {r['previous_status']} -> {r['new_status']}")
    stale_invalidated = checkup_service.invalidate_stale_checkups()
    if stale_invalidated:
        print(f"[启动] 因配置变更失效了 {len(stale_invalidated)} 条体检记录")
        for r in stale_invalidated:
            print(f"  - 体检 {r['record_id']}: {r['previous_status']} -> {r['new_status']}")
    remind_recovered = remind_service.recover_reminds_on_startup()
    if remind_recovered:
        print(f"[启动] 恢复了 {len(remind_recovered)} 个异常中断的催办单")
        for r in remind_recovered:
            print(f"  - 催办 {r['order_id']}: {r['previous_status']} -> {r['new_status']}")
    remind_stale_invalidated = remind_service.invalidate_stale_reminds()
    if remind_stale_invalidated:
        print(f"[启动] 因配置变更失效了 {len(remind_stale_invalidated)} 条催办单")
        for r in remind_stale_invalidated:
            print(f"  - 催办 {r['order_id']}: {r['previous_status']} -> {r['new_status']}")
    app.run(host="127.0.0.1", port=5000, debug=False)


if __name__ == "__main__":
    main()

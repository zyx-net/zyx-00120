import threading

from flask import Flask, request, jsonify

import service

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


@app.route("/api/expire", methods=["POST"])
def api_trigger_expire():
    count = service.process_expired()
    return jsonify({"ok": True, "expired_count": count}), 200


def main():
    import store as _store
    print(f"[启动] 数据目录: {_store.DATA_DIR}")
    print("[启动] 检查并处理过期预约...")
    service.process_expired()
    print("[启动] 过期检查完成，启动定时过期扫描（每10秒）")
    _schedule_expire()
    app.run(host="127.0.0.1", port=5000, debug=False)


if __name__ == "__main__":
    main()

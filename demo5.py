import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:5000"
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_DIR, "data")


def api(method, path, body=None):
    url = f"{BASE}{path}"
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json; charset=utf-8")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8")), resp.status
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode("utf-8")), e.code


def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def assert_true(cond, msg):
    if not cond:
        print(f"  [FAIL] {msg}")
        sys.exit(1)
    print(f"  [PASS] {msg}")


def clear_data():
    if not os.path.isdir(DATA_DIR):
        return
    for name in ["books", "reservations", "blacklist", "logs"]:
        p = os.path.join(DATA_DIR, f"{name}.json")
        if os.path.exists(p):
            os.remove(p)
    print("  [INFO] 已清空 data/ 目录")


def start_server():
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.Popen(
        [sys.executable, "main.py"],
        cwd=PROJECT_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    for _ in range(30):
        time.sleep(0.5)
        try:
            urllib.request.urlopen(f"{BASE}/api/books", timeout=2)
            print("  [INFO] 服务已启动")
            return proc
        except Exception:
            pass
    raise RuntimeError("服务启动超时")


def stop_server(proc):
    if proc and proc.poll() is None:
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True, timeout=10,
                )
            else:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    proc.kill()
        except Exception:
            pass
    time.sleep(2)
    print("  [INFO] 服务已停止")


def get_book_count():
    r, _ = api("GET", "/api/books")
    return len(r["data"])


def get_reservation_count():
    r, _ = api("GET", "/api/reservations")
    return len(r["data"]) if r.get("ok") and r.get("data") else 0


def get_active_reservations(book_id=None):
    if book_id:
        r, _ = api("GET", f"/api/queue/{book_id}")
    else:
        all_active = []
        books_r, _ = api("GET", "/api/books")
        for b in books_r["data"]:
            q, _ = api("GET", f"/api/queue/{b['book_id']}")
            all_active.extend(q["data"])
        return all_active
    return r["data"] if r.get("ok") and r.get("data") else []


def get_blacklist():
    r, _ = api("GET", "/api/blacklist")
    return r["data"] if r.get("ok") and r.get("data") else []


def get_logs_by_book(book_id):
    r, _ = api("GET", f"/api/logs?book_id={book_id}&limit=100")
    return r["data"] if r.get("ok") and r.get("data") else []


def get_all_logs(limit=1000):
    r, _ = api("GET", f"/api/logs?limit={limit}")
    return r["data"] if r.get("ok") and r.get("data") else []


def get_available_copies(book_id):
    book_r, _ = api("GET", f"/api/books/{book_id}")
    if not book_r.get("ok"):
        return None
    book = book_r["data"]
    active = get_active_reservations(book_id)
    borrowed = sum(1 for r in active if r["status"] == "borrowed")
    to_pick = sum(1 for r in active if r["status"] == "available")
    return book["total_copies"] - borrowed - to_pick


if __name__ == "__main__":
    clear_data()
    server_proc = start_server()

    try:
        section("前置准备：创建完整的测试数据（书目 + 预约 + 黑名单）")

        books_data = [
            {"book_id": "SNAP-B001", "title": "快照测试书1", "total_copies": 3, "borrow_days": 30, "retain_hours": 24},
            {"book_id": "SNAP-B002", "title": "快照测试书2", "total_copies": 2, "borrow_days": 14, "retain_hours": 12},
            {"book_id": "SNAP-B003", "title": "快照测试书3", "total_copies": 1, "borrow_days": 21, "retain_hours": 6},
        ]
        for book in books_data:
            r, s = api("POST", "/api/books", book)
            assert_true(s == 201 and r["ok"], f"创建书目 {book['book_id']} 成功")

        readers_waiting = ["R-SNAP-001", "R-SNAP-002", "R-SNAP-003"]
        for rid in readers_waiting:
            r, s = api("POST", "/api/reserve", {"book_id": "SNAP-B001", "reader_id": rid})
            assert_true(s == 201 and r["ok"], f"读者 {rid} 预约 SNAP-B001 成功")

        r, s = api("POST", "/api/reserve", {"book_id": "SNAP-B002", "reader_id": "R-SNAP-004"})
        assert_true(s == 201 and r["ok"], "读者 R-SNAP-004 预约 SNAP-B002 成功（待取状态）")

        r, s = api("POST", "/api/checkout", {"book_id": "SNAP-B002", "reader_id": "R-SNAP-004"})
        assert_true(s == 200 and r["ok"], "读者 R-SNAP-004 借出 SNAP-B002 成功")

        r, s = api("POST", "/api/blacklist", {"reader_id": "R-BLACK-001", "reason": "逾期未还"})
        assert_true(s == 201 and r["ok"], "加入黑名单 R-BLACK-001 成功")

        r, s = api("POST", "/api/blacklist", {"reader_id": "R-BLACK-002", "reason": "恶意预约"})
        assert_true(s == 201 and r["ok"], "加入黑名单 R-BLACK-002 成功")

        queue_before = get_active_reservations("SNAP-B001")
        assert_true(len(queue_before) == 3, f"SNAP-B001 队列有 3 人，实际 {len(queue_before)}")
        for i, r in enumerate(queue_before):
            assert_true(r["reader_id"] == readers_waiting[i],
                        f"队列顺序正确：位置 {i+1} 是 {readers_waiting[i]}")

        available_before = get_available_copies("SNAP-B001")
        assert_true(available_before == 0, f"SNAP-B001 可借副本数为 0（3个待取预约占用了全部3个副本），实际 {available_before}")

        blacklist_before = get_blacklist()
        assert_true(len(blacklist_before) == 2, f"黑名单有 2 人，实际 {len(blacklist_before)}")

        section("场景 1：导出完整快照，验证格式和内容")

        export_r, export_s = api("GET", "/api/snapshot/export")
        assert_true(export_s == 200 and export_r["ok"], "快照导出成功")

        snapshot = export_r["data"]
        assert_true(snapshot["version"] == "2.0", f"快照版本为 2.0，实际 {snapshot.get('version')}")
        assert_true(snapshot["type"] == "full_snapshot", f"快照类型为 full_snapshot，实际 {snapshot.get('type')}")
        assert_true(snapshot["counts"]["books"] == 3, f"导出 3 本书，实际 {snapshot['counts']['books']}")
        assert_true(snapshot["counts"]["active_reservations"] == 4,
                    f"导出 4 条活跃预约，实际 {snapshot['counts']['active_reservations']}")
        assert_true(snapshot["counts"]["blacklist"] == 2,
                    f"导出 2 条黑名单，实际 {snapshot['counts']['blacklist']}")
        assert_true(snapshot["counts"]["logs"] > 0, "导出日志条数 > 0")

        exported_book_ids = {b["book_id"] for b in snapshot["books"]}
        assert_true(exported_book_ids == {"SNAP-B001", "SNAP-B002", "SNAP-B003"},
                    f"导出的书目正确：{exported_book_ids}")

        exported_res_keys = {(r["book_id"], r["reader_id"]) for r in snapshot["active_reservations"]}
        expected_res_keys = {
            ("SNAP-B001", "R-SNAP-001"),
            ("SNAP-B001", "R-SNAP-002"),
            ("SNAP-B001", "R-SNAP-003"),
            ("SNAP-B002", "R-SNAP-004"),
        }
        assert_true(exported_res_keys == expected_res_keys,
                    f"导出的活跃预约正确：{exported_res_keys}")

        for r in snapshot["active_reservations"]:
            assert_true("reservation_id" in r, f"预约包含 reservation_id: {r}")
            assert_true("created_at" in r, f"预约包含 created_at: {r}")
            assert_true("status" in r, f"预约包含 status: {r}")

        snapshot_res_sorted = sorted(
            [r for r in snapshot["active_reservations"] if r["book_id"] == "SNAP-B001"],
            key=lambda r: r["created_at"]
        )
        for i, r in enumerate(snapshot_res_sorted):
            assert_true(r["reader_id"] == readers_waiting[i],
                        f"导出的队列顺序正确：位置 {i+1} 是 {readers_waiting[i]}")

        exported_b002 = next(r for r in snapshot["active_reservations"]
                             if r["book_id"] == "SNAP-B002" and r["reader_id"] == "R-SNAP-004")
        assert_true(exported_b002["status"] == "borrowed",
                    f"SNAP-B002/R-SNAP-004 状态为 borrowed，实际 {exported_b002['status']}")

        exported_blacklist_ids = {b["reader_id"] for b in snapshot["blacklist"]}
        assert_true(exported_blacklist_ids == {"R-BLACK-001", "R-BLACK-002"},
                    f"导出的黑名单正确：{exported_blacklist_ids}")

        print(f"  [INFO] 快照导出成功：{snapshot['counts']}")

        section("场景 2：Dry-Run 导入到空环境，校验通过但不落库")

        clear_data()
        stop_server(server_proc)
        time.sleep(1)
        server_proc = start_server()

        assert_true(get_book_count() == 0, "清空后书目数为 0")

        dry_r, dry_s = api("POST", "/api/snapshot/import?dry_run=true", snapshot)
        assert_true(dry_s == 200 and dry_r["ok"], "DRY-RUN 导入成功（HTTP 200）")
        assert_true(dry_r["dry_run"] is True, "dry_run=true")
        assert_true(dry_r["imported_counts"]["books"] == 3,
                    f"DRY-RUN 显示可导入 3 本书，实际 {dry_r['imported_counts']['books']}")
        assert_true(dry_r["imported_counts"]["active_reservations"] == 4,
                    f"DRY-RUN 显示可导入 4 条预约，实际 {dry_r['imported_counts']['active_reservations']}")
        assert_true(dry_r["imported_counts"]["blacklist"] == 2,
                    f"DRY-RUN 显示可导入 2 条黑名单，实际 {dry_r['imported_counts']['blacklist']}")

        assert_true(get_book_count() == 0, "DRY-RUN 后书目数仍为 0（不落库）")
        assert_true(len(get_blacklist()) == 0, "DRY-RUN 后黑名单仍为空")
        assert_true(len(get_active_reservations()) == 0, "DRY-RUN 后活跃预约仍为空")

        logs_after_dry = get_all_logs(limit=100)
        assert_true(len(logs_after_dry) == 0, "DRY-RUN 不落库：不写入任何日志，logs.json 保持不变")

        logs_b001_after_dry = get_logs_by_book("SNAP-B001")
        assert_true(len(logs_b001_after_dry) == 0,
                    "DRY-RUN 后按 book_id 查询无日志（不落库）")

        section("场景 3：正式导入到空环境，验证数据完整且顺序一致")

        import_r, import_s = api("POST", "/api/snapshot/import?dry_run=false", snapshot)
        assert_true(import_s == 200 and import_r["ok"], "正式导入成功（HTTP 200）")
        assert_true(import_r["dry_run"] is False, "dry_run=false")
        assert_true(import_r["imported_counts"]["books"] == 3,
                    f"正式导入 3 本书，实际 {import_r['imported_counts']['books']}")

        assert_true(get_book_count() == 3, "导入后书目数为 3")

        queue_after = get_active_reservations("SNAP-B001")
        assert_true(len(queue_after) == 3, f"SNAP-B001 队列有 3 人，实际 {len(queue_after)}")
        for i, r in enumerate(queue_after):
            assert_true(r["reader_id"] == readers_waiting[i],
                        f"导入后队列顺序正确：位置 {i+1} 是 {readers_waiting[i]}")

        queue_after_b002 = get_active_reservations("SNAP-B002")
        assert_true(len(queue_after_b002) == 1, f"SNAP-B002 队列有 1 人，实际 {len(queue_after_b002)}")
        assert_true(queue_after_b002[0]["status"] == "borrowed",
                    f"SNAP-B002 状态为 borrowed，实际 {queue_after_b002[0]['status']}")
        assert_true(queue_after_b002[0]["reader_id"] == "R-SNAP-004",
                    f"SNAP-B002 借阅者为 R-SNAP-004，实际 {queue_after_b002[0]['reader_id']}")

        available_after = get_available_copies("SNAP-B001")
        assert_true(available_after == 0, f"SNAP-B001 可借副本数为 0（3个待取预约占用了全部3个副本），实际 {available_after}")

        blacklist_after = get_blacklist()
        assert_true(len(blacklist_after) == 2, f"黑名单有 2 人，实际 {len(blacklist_after)}")
        blacklist_ids_after = {b["reader_id"] for b in blacklist_after}
        assert_true(blacklist_ids_after == {"R-BLACK-001", "R-BLACK-002"},
                    f"导入的黑名单正确：{blacklist_ids_after}")

        import_logs_b001 = get_logs_by_book("SNAP-B001")
        source_log_ids_b001 = {l["log_id"] for l in snapshot["logs"] if l.get("book_id") == "SNAP-B001"}
        import_log_ids_b001 = {l["log_id"] for l in import_logs_b001}
        assert_true(source_log_ids_b001 == import_log_ids_b001,
                    f"按 book_id=SNAP-B001 查询，导入环境日志与源环境完全一致（不多不少）")

        import_logs_b002 = get_logs_by_book("SNAP-B002")
        source_log_ids_b002 = {l["log_id"] for l in snapshot["logs"] if l.get("book_id") == "SNAP-B002"}
        import_log_ids_b002 = {l["log_id"] for l in import_logs_b002}
        assert_true(source_log_ids_b002 == import_log_ids_b002,
                    f"按 book_id=SNAP-B002 查询，导入环境日志与源环境完全一致")

        all_logs_after_import = get_all_logs(limit=200)
        snapshot_extra_logs = [l for l in all_logs_after_import if l["action"].startswith("snapshot_import_")]
        assert_true(len(snapshot_extra_logs) == 0,
                    f"按任何条件查询都不会命中 snapshot_import_* 串味日志（实际 {len(snapshot_extra_logs)} 条）")

        import_summary_logs = [l for l in all_logs_after_import if l["action"] == "import_snapshot"]
        assert_true(len(import_summary_logs) >= 1, "仅存在不带 book_id 的 import_snapshot 汇总日志")
        for sl in import_summary_logs:
            assert_true("book_id" not in sl or sl.get("book_id") is None,
                        f"import_snapshot 汇总日志不带 book_id（不会被按书目过滤命中）")
            assert_true("reader_id" not in sl or sl.get("reader_id") is None,
                        f"import_snapshot 汇总日志不带 reader_id（不会被按读者过滤命中）")

        section("场景 4：冲突检测 - duplicate_book_id（目标已有相同书目）")

        conflict_snapshot = {
            "version": "2.0",
            "type": "full_snapshot",
            "books": [
                {"book_id": "SNAP-B001", "title": "冲突的书", "total_copies": 10, "borrow_days": 7, "retain_hours": 1},
            ],
            "active_reservations": [],
            "blacklist": [],
            "logs": [],
        }

        conf_r, conf_s = api("POST", "/api/snapshot/import?dry_run=false", conflict_snapshot)
        assert_true(conf_s == 409, "重复 book_id 返回 409")
        assert_true(not conf_r["ok"], "ok=false")
        assert_true(len(conf_r["conflicts"]) == 1, f"检测到 1 个冲突，实际 {len(conf_r['conflicts'])}")
        assert_true(conf_r["conflicts"][0]["type"] == "duplicate_book_id",
                    f"冲突类型为 duplicate_book_id，实际 {conf_r['conflicts'][0]['type']}")
        assert_true(conf_r["conflicts"][0]["book_id"] == "SNAP-B001",
                    f"冲突 book_id 为 SNAP-B001，实际 {conf_r['conflicts'][0]['book_id']}")
        assert_true("existing_config" in conf_r["conflicts"][0], "冲突包含 existing_config")
        assert_true("import_config" in conf_r["conflicts"][0], "冲突包含 import_config")

        assert_true(get_book_count() == 3, "冲突回滚，书目数仍为 3")
        assert_true(len(get_blacklist()) == 2, "冲突回滚，黑名单仍为 2 人")
        assert_true(len(get_active_reservations()) == 4, "冲突回滚，活跃预约仍为 4 条")

        logs_after_conflict = get_logs_by_book("SNAP-B001")
        log_ids_after_conflict = {l["log_id"] for l in logs_after_conflict}
        assert_true(source_log_ids_b001 == log_ids_after_conflict,
                    "冲突回滚后，按 book_id=SNAP-B001 查询日志与冲突前完全一致（整批回滚，不写半套）")

        all_logs_conflict = get_all_logs(limit=200)
        extra_logs_in_conflict = [l for l in all_logs_conflict if l["action"].startswith("snapshot_import_")]
        assert_true(len(extra_logs_in_conflict) == 0,
                    f"冲突回滚后，不存在任何 snapshot_import_* 串味日志（实际 {len(extra_logs_in_conflict)} 条）")

        print(f"    [冲突] {conf_r['conflicts'][0]['book_id']}: {conf_r['conflicts'][0]['type']} - {conf_r['conflicts'][0]['message']}")

        section("场景 5：冲突检测 - duplicate_reservation（目标已有相同活跃预约）")

        conflict_res_snapshot = {
            "version": "2.0",
            "type": "full_snapshot",
            "books": [
                {"book_id": "SNAP-B001", "title": "冲突的书", "total_copies": 10, "borrow_days": 7, "retain_hours": 1},
                {"book_id": "NEW-B001", "title": "新书", "total_copies": 5, "borrow_days": 30, "retain_hours": 24},
            ],
            "active_reservations": [
                {
                    "reservation_id": "test-res-id-1",
                    "book_id": "SNAP-B001",
                    "reader_id": "R-SNAP-001",
                    "status": "waiting",
                    "created_at": "2026-06-19T10:00:00+00:00",
                    "available_at": None,
                    "expire_at": None,
                    "borrowed_at": None,
                    "returned_at": None,
                },
            ],
            "blacklist": [],
            "logs": [],
        }

        conf_r2, conf_s2 = api("POST", "/api/snapshot/import?dry_run=false", conflict_res_snapshot)
        assert_true(conf_s2 == 409, "重复预约返回 409")
        assert_true(not conf_r2["ok"], "ok=false")
        assert_true(len(conf_r2["conflicts"]) == 2,
                    f"检测到 2 个冲突（1 duplicate_book_id + 1 duplicate_reservation），实际 {len(conf_r2['conflicts'])}")

        conflict_types2 = {c["type"] for c in conf_r2["conflicts"]}
        assert_true("duplicate_book_id" in conflict_types2, "包含 duplicate_book_id 冲突")
        assert_true("duplicate_reservation" in conflict_types2, "包含 duplicate_reservation 冲突")

        res_conflict2 = next(c for c in conf_r2["conflicts"] if c["type"] == "duplicate_reservation")
        assert_true(res_conflict2["reader_id"] == "R-SNAP-001",
                    f"冲突 reader_id 正确")
        assert_true("existing_reservation" in res_conflict2, "冲突包含 existing_reservation")
        assert_true("import_reservation" in res_conflict2, "冲突包含 import_reservation")

        books_after = get_book_count()
        assert_true(books_after == 3, f"冲突回滚，书目数仍为 3，实际 {books_after}")

        for c in conf_r2["conflicts"]:
            obj_id = c.get("book_id") or c.get("reader_id", "unknown")
            print(f"    [冲突] {obj_id}: {c['type']} - {c['message']}")

        section("场景 6：冲突检测 - blacklist_conflict（目标已有黑名单，原因不同）")

        conflict_bl_snapshot = {
            "version": "2.0",
            "type": "full_snapshot",
            "books": [],
            "active_reservations": [],
            "blacklist": [
                {"reader_id": "R-BLACK-001", "reason": "不同的原因", "added_at": "2026-06-19T10:00:00+00:00"},
            ],
            "logs": [],
        }

        conf_r3, conf_s3 = api("POST", "/api/snapshot/import?dry_run=false", conflict_bl_snapshot)
        assert_true(conf_s3 == 409, "黑名单冲突返回 409")
        assert_true(not conf_r3["ok"], "ok=false")
        assert_true(len(conf_r3["conflicts"]) == 1, f"检测到 1 个冲突，实际 {len(conf_r3['conflicts'])}")
        assert_true(conf_r3["conflicts"][0]["type"] == "blacklist_conflict",
                    f"冲突类型为 blacklist_conflict，实际 {conf_r3['conflicts'][0]['type']}")
        assert_true(conf_r3["conflicts"][0]["reader_id"] == "R-BLACK-001",
                    f"冲突 reader_id 正确")
        assert_true("existing_entry" in conf_r3["conflicts"][0], "冲突包含 existing_entry")
        assert_true("import_entry" in conf_r3["conflicts"][0], "冲突包含 import_entry")

        bl_after = get_blacklist()
        assert_true(len(bl_after) == 2, f"冲突回滚，黑名单仍为 2 人，实际 {len(bl_after)}")

        print(f"    [冲突] {conf_r3['conflicts'][0]['reader_id']}: "
              f"{conf_r3['conflicts'][0]['type']} - {conf_r3['conflicts'][0]['message']}")

        section("场景 7：冲突检测 - missing_dependency（预约引用不存在的书目）")

        missing_dep_snapshot = {
            "version": "2.0",
            "type": "full_snapshot",
            "books": [],
            "active_reservations": [
                {
                    "reservation_id": "test-res-id-2",
                    "book_id": "NONEXIST-B001",
                    "reader_id": "R-TEST-999",
                    "status": "waiting",
                    "created_at": "2026-06-19T10:00:00+00:00",
                    "available_at": None,
                    "expire_at": None,
                    "borrowed_at": None,
                    "returned_at": None,
                },
            ],
            "blacklist": [],
            "logs": [],
        }

        conf_r4, conf_s4 = api("POST", "/api/snapshot/import?dry_run=false", missing_dep_snapshot)
        assert_true(conf_s4 == 409, "缺失依赖返回 409")
        assert_true(not conf_r4["ok"], "ok=false")
        assert_true(len(conf_r4["conflicts"]) == 1, f"检测到 1 个冲突，实际 {len(conf_r4['conflicts'])}")
        assert_true(conf_r4["conflicts"][0]["type"] == "missing_dependency",
                    f"冲突类型为 missing_dependency，实际 {conf_r4['conflicts'][0]['type']}")
        assert_true(conf_r4["conflicts"][0]["book_id"] == "NONEXIST-B001",
                    f"冲突 book_id 正确")

        print(f"    [冲突] {conf_r4['conflicts'][0]['book_id']}/{conf_r4['conflicts'][0]['reader_id']}: "
              f"{conf_r4['conflicts'][0]['type']} - {conf_r4['conflicts'][0]['message']}")

        section("场景 8：混合冲突 - 多种冲突同时存在时全部返回")

        mixed_snapshot = {
            "version": "2.0",
            "type": "full_snapshot",
            "books": [
                {"book_id": "SNAP-B001", "title": "冲突书", "total_copies": 10, "borrow_days": 7, "retain_hours": 1},
                {"book_id": "NEW-B002", "title": "新书2", "total_copies": 5, "borrow_days": 30, "retain_hours": 24},
            ],
            "active_reservations": [
                {
                    "reservation_id": "test-res-id-3",
                    "book_id": "SNAP-B001",
                    "reader_id": "R-SNAP-002",
                    "status": "waiting",
                    "created_at": "2026-06-19T10:00:00+00:00",
                    "available_at": None,
                    "expire_at": None,
                    "borrowed_at": None,
                    "returned_at": None,
                },
                {
                    "reservation_id": "test-res-id-4",
                    "book_id": "NONEXIST-B002",
                    "reader_id": "R-TEST-888",
                    "status": "waiting",
                    "created_at": "2026-06-19T10:00:00+00:00",
                    "available_at": None,
                    "expire_at": None,
                    "borrowed_at": None,
                    "returned_at": None,
                },
            ],
            "blacklist": [
                {"reader_id": "R-BLACK-002", "reason": "另一个原因", "added_at": "2026-06-19T10:00:00+00:00"},
            ],
            "logs": [],
        }

        conf_r5, conf_s5 = api("POST", "/api/snapshot/import?dry_run=true", mixed_snapshot)
        assert_true(conf_s5 == 409, "混合冲突返回 409")
        assert_true(not conf_r5["ok"], "ok=false")
        assert_true(len(conf_r5["conflicts"]) == 4,
                    f"检测到 4 个冲突（1 duplicate_book_id + 1 duplicate_reservation + 1 missing_dependency + 1 blacklist_conflict），实际 {len(conf_r5['conflicts'])}")

        conflict_types = {c["type"] for c in conf_r5["conflicts"]}
        assert_true("duplicate_book_id" in conflict_types, "包含 duplicate_book_id 冲突")
        assert_true("duplicate_reservation" in conflict_types, "包含 duplicate_reservation 冲突")
        assert_true("missing_dependency" in conflict_types, "包含 missing_dependency 冲突")
        assert_true("blacklist_conflict" in conflict_types, "包含 blacklist_conflict 冲突")

        print("\n  [混合冲突明细示例]")
        print("  " + "-" * 58)
        for c in conf_r5["conflicts"]:
            section_type = c.get("section", "unknown")
            obj_id = c.get("book_id") or c.get("reader_id", "unknown")
            print(f"  section: {section_type:25s} type: {c['type']:30s} id: {obj_id}")
            print(f"    message: {c['message']}")
        print("  " + "-" * 58)

        assert_true(get_book_count() == 3, "DRY-RUN 混合冲突后书目数仍为 3")

        section("场景 9：服务重启后，队列顺序、可借状态和日志完全一致")

        books_before_restart, _ = api("GET", "/api/books")
        book_ids_before = {b["book_id"] for b in books_before_restart["data"]}

        queue_before_restart = {}
        for bid in book_ids_before:
            queue_before_restart[bid] = get_active_reservations(bid)

        available_before_restart = {}
        for bid in book_ids_before:
            available_before_restart[bid] = get_available_copies(bid)

        logs_before_restart = {}
        for bid in book_ids_before:
            logs_before_restart[bid] = get_logs_by_book(bid)

        blacklist_before_restart = get_blacklist()

        stop_server(server_proc)
        time.sleep(1)
        server_proc = start_server()

        books_after_restart, _ = api("GET", "/api/books")
        book_ids_after = {b["book_id"] for b in books_after_restart["data"]}

        assert_true(book_ids_before == book_ids_after,
                    f"重启后书目集合不变：重启前 {book_ids_before}，重启后 {book_ids_after}")

        for b_before, b_after in zip(
            sorted(books_before_restart["data"], key=lambda x: x["book_id"]),
            sorted(books_after_restart["data"], key=lambda x: x["book_id"]),
        ):
            assert_true(b_before["book_id"] == b_after["book_id"], f"book_id 一致")
            assert_true(b_before["title"] == b_after["title"], f"{b_before['book_id']} title 一致")
            assert_true(b_before["total_copies"] == b_after["total_copies"], f"{b_before['book_id']} total_copies 一致")
            assert_true(b_before["borrow_days"] == b_after["borrow_days"], f"{b_before['book_id']} borrow_days 一致")
            assert_true(b_before["retain_hours"] == b_after["retain_hours"], f"{b_before['book_id']} retain_hours 一致")

        for bid in book_ids_before:
            queue_after = get_active_reservations(bid)
            assert_true(len(queue_after) == len(queue_before_restart[bid]),
                        f"重启后 {bid} 队列长度不变：{len(queue_before_restart[bid])} -> {len(queue_after)}")

            for r_before, r_after in zip(
                sorted(queue_before_restart[bid], key=lambda x: x["created_at"]),
                sorted(queue_after, key=lambda x: x["created_at"]),
            ):
                assert_true(r_before["reader_id"] == r_after["reader_id"],
                            f"重启后 {bid} 队列顺序不变：{r_before['reader_id']} -> {r_after['reader_id']}")
                assert_true(r_before["status"] == r_after["status"],
                            f"重启后 {bid}/{r_before['reader_id']} 状态不变：{r_before['status']} -> {r_after['status']}")

        for bid in book_ids_before:
            avail_after = get_available_copies(bid)
            assert_true(avail_after == available_before_restart[bid],
                        f"重启后 {bid} 可借状态不变：{available_before_restart[bid]} -> {avail_after}")

        for bid in book_ids_before:
            logs_after = get_logs_by_book(bid)
            log_ids_before = {l["log_id"] for l in logs_before_restart[bid]}
            log_ids_after = {l["log_id"] for l in logs_after}
            assert_true(log_ids_before == log_ids_after,
                        f"重启后 {bid} 的日志完全一致（不多不少）：重启前 {len(log_ids_before)} 条，重启后 {len(log_ids_after)} 条")

        all_logs_after_restart = get_all_logs(limit=200)
        extra_after_restart = [l for l in all_logs_after_restart if l["action"].startswith("snapshot_import_")]
        assert_true(len(extra_after_restart) == 0,
                    f"重启后仍不存在任何 snapshot_import_* 串味日志（实际 {len(extra_after_restart)} 条）")

        blacklist_after_restart = get_blacklist()
        bl_ids_before = {b["reader_id"] for b in blacklist_before_restart}
        bl_ids_after = {b["reader_id"] for b in blacklist_after_restart}
        assert_true(bl_ids_before == bl_ids_after,
                    f"重启后黑名单不变：{bl_ids_before} -> {bl_ids_after}")

        for b_before, b_after in zip(
            sorted(blacklist_before_restart, key=lambda x: x["reader_id"]),
            sorted(blacklist_after_restart, key=lambda x: x["reader_id"]),
        ):
            assert_true(b_before["reader_id"] == b_after["reader_id"], "黑名单 reader_id 一致")
            assert_true(b_before["reason"] == b_after["reason"], f"{b_before['reader_id']} reason 一致")

        section("场景 10：验证导入数据可正常使用（预约、借出功能正常）")

        r, s = api("POST", "/api/reserve", {"book_id": "SNAP-B003", "reader_id": "R-SNAP-005"})
        assert_true(s == 201 and r["ok"], "新读者可正常预约导入的书目 SNAP-B003")

        r, s = api("POST", "/api/reserve", {"book_id": "SNAP-B003", "reader_id": "R-BLACK-001"})
        assert_true(s == 409 and not r["ok"], "黑名单读者 R-BLACK-001 无法预约")

        r, s = api("POST", "/api/checkout", {"book_id": "SNAP-B003", "reader_id": "R-SNAP-005"})
        assert_true(s == 200 and r["ok"], "可正常借出导入的书目")

        section("场景 11：完整迁移流程模拟（A环境导出 -> B环境导入，同口径日志完全一致）")

        a_env_books_r, _ = api("GET", "/api/books")
        a_env_book_ids = {b["book_id"] for b in a_env_books_r["data"]}

        a_env_logs_by_book = {}
        for bid in a_env_book_ids:
            logs = get_logs_by_book(bid)
            a_env_logs_by_book[bid] = {l["log_id"] for l in logs}

        a_env_queue = {}
        for bid in a_env_book_ids:
            a_env_queue[bid] = get_active_reservations(bid)

        a_env_available = {}
        for bid in a_env_book_ids:
            a_env_available[bid] = get_available_copies(bid)

        a_env_blacklist = get_blacklist()

        export_r2, _ = api("GET", "/api/snapshot/export")
        snapshot_a = export_r2["data"]

        clear_data()
        stop_server(server_proc)
        time.sleep(1)
        server_proc = start_server()

        assert_true(get_book_count() == 0, "清空后 B 环境书目数为 0")

        import_r2, import_s2 = api("POST", "/api/snapshot/import?dry_run=false", snapshot_a)
        assert_true(import_s2 == 200 and import_r2["ok"], "B 环境导入成功")

        book_count_b = get_book_count()
        assert_true(book_count_b == snapshot_a["counts"]["books"],
                    f"B 环境书目数匹配：{snapshot_a['counts']['books']} -> {book_count_b}")

        queue_b = get_active_reservations("SNAP-B001")
        assert_true(len(queue_b) == len(a_env_queue["SNAP-B001"]),
                    f"B 环境 SNAP-B001 队列长度匹配 A 环境")
        for r_b, r_a in zip(
            sorted(queue_b, key=lambda x: x["created_at"]),
            sorted(a_env_queue["SNAP-B001"], key=lambda x: x["created_at"]),
        ):
            assert_true(r_b["reader_id"] == r_a["reader_id"],
                        f"B 环境队列顺序与 A 环境一致：{r_a['reader_id']}")
            assert_true(r_b["status"] == r_a["status"],
                        f"B 环境 {r_a['reader_id']} 状态与 A 环境一致：{r_a['status']}")

        blacklist_b = get_blacklist()
        assert_true(len(blacklist_b) == len(a_env_blacklist),
                    f"B 环境黑名单人数匹配 A 环境")
        bl_ids_a = {b["reader_id"] for b in a_env_blacklist}
        bl_ids_b = {b["reader_id"] for b in blacklist_b}
        assert_true(bl_ids_a == bl_ids_b, "B 环境黑名单集合与 A 环境一致")

        for bid in a_env_book_ids:
            logs_b = get_logs_by_book(bid)
            log_ids_b = {l["log_id"] for l in logs_b}
            assert_true(a_env_logs_by_book[bid] == log_ids_b,
                        f"B 环境按 book_id={bid} 查询日志与 A 环境完全一致（不多不少）：A={len(a_env_logs_by_book[bid])}条，B={len(log_ids_b)}条")

        for bid in a_env_book_ids:
            avail_b = get_available_copies(bid)
            assert_true(a_env_available[bid] == avail_b,
                        f"B 环境 {bid} 可借状态与 A 环境一致：{a_env_available[bid]}")

        b_all_logs = get_all_logs(limit=500)
        b_extra_logs = [l for l in b_all_logs if l["action"].startswith("snapshot_import_")]
        assert_true(len(b_extra_logs) == 0,
                    f"B 环境不存在任何 snapshot_import_* 串味日志（实际 {len(b_extra_logs)} 条）")

        print(f"\n  [迁移成功] A -> B 完整迁移完成")
        print(f"    书目: {snapshot_a['counts']['books']} 本")
        print(f"    活跃预约: {snapshot_a['counts']['active_reservations']} 条")
        print(f"    黑名单: {snapshot_a['counts']['blacklist']} 条")
        print(f"    同口径日志一致: 是（按 book_id 查询，A/B 环境结果完全一致）")
        print(f"    串味日志: 无（未写入任何 snapshot_import_* 带过滤字段的日志）")

        print("\n" + "=" * 60)
        print("  完整快照迁移回归测试全部通过!")
        print("=" * 60)
        print("\n  能力总结:")
        print("  1. GET /api/snapshot/export - 导出完整快照（书目+活跃预约+黑名单+相关日志）")
        print("  2. POST /api/snapshot/import - 导入完整快照（支持 dry-run 预检）")
        print("  3. 冲突检测：duplicate_book_id / duplicate_reservation / blacklist_conflict / missing_dependency")
        print("  4. 整批回滚：冲突时完整回滚，绝不写半套数据（含日志回滚）")
        print("  5. 队列顺序一致：按 created_at 排序，导入/重启后保持不变")
        print("  6. 可借状态一致：status 字段完整保留，导入/重启后不变")
        print("  7. 日志查询一致：同口径（book_id/reader_id）查询，源/导入环境结果完全一致")
        print("  8. 不写串味日志：导入汇总日志不带 book_id/reader_id，不会被按书目/读者过滤命中")
        print("  9. Dry-Run 不落库：仅校验不写入，所有数据（含日志）保持原状")
        print("  10. 并发安全：加锁 + 二次校验，防止并发冲突")

    finally:
        stop_server(server_proc)

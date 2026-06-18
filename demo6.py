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


def subsection(title):
    print(f"\n  --- {title} ---")


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


def print_report_summary(report):
    s = report["summary"]
    print(f"\n  [预检摘要]")
    print(f"    状态: {s['status']}")
    print(f"    消息: {s['message']}")
    print(f"    可导入: {report['can_import']}")
    print(f"    将新增: {s['total_will_add']} 条")
    print(f"    冲突: {s['total_conflicts']} 条")
    print(f"    缺依赖: {s['total_missing_dependencies']} 条")
    print(f"    格式错误: {s['total_format_errors']} 条")
    print(f"    分类明细:")
    for sec, stats in s["breakdown"].items():
        print(f"      {sec}: 新增={stats['will_add']}, 冲突={stats['conflicts']}, "
              f"缺依赖={stats['missing_dependencies']}, 格式错={stats['format_errors']}")
    if "queue_order_check" in s:
        print(f"    队列顺序检查: {len(s['queue_order_check'])} 本书")
    if "availability_check" in s:
        print(f"    可借状态检查: {len(s['availability_check'])} 本书")


def setup_test_data():
    books_data = [
        {"book_id": "PRE-B001", "title": "预检测试书1", "total_copies": 3, "borrow_days": 30, "retain_hours": 24},
        {"book_id": "PRE-B002", "title": "预检测试书2", "total_copies": 2, "borrow_days": 14, "retain_hours": 12},
    ]
    for book in books_data:
        r, s = api("POST", "/api/books", book)
        assert_true(s == 201 and r["ok"], f"创建书目 {book['book_id']} 成功")

    readers_waiting = ["R-PRE-001", "R-PRE-002"]
    for rid in readers_waiting:
        r, s = api("POST", "/api/reserve", {"book_id": "PRE-B001", "reader_id": rid})
        assert_true(s == 201 and r["ok"], f"读者 {rid} 预约 PRE-B001 成功")

    r, s = api("POST", "/api/blacklist", {"reader_id": "R-BLACK-P1", "reason": "逾期未还"})
    assert_true(s == 201 and r["ok"], "加入黑名单 R-BLACK-P1 成功")

    return books_data, readers_waiting


if __name__ == "__main__":
    clear_data()
    server_proc = start_server()

    try:
        section("场景 1：预检报告 API 存在且可调用")

        empty_snapshot = {
            "version": "2.0",
            "type": "full_snapshot",
            "books": [],
            "active_reservations": [],
            "blacklist": [],
            "logs": [],
        }

        r, s = api("POST", "/api/snapshot/precheck", empty_snapshot)
        assert_true(s == 200 and r["ok"], "预检 API 返回 200 OK")
        assert_true("data" in r, "响应包含 data 字段")

        report = r["data"]
        assert_true(report["dry_run"] is True, "dry_run=true")
        assert_true("can_import" in report, "包含 can_import 字段")
        assert_true("summary" in report, "包含 summary 字段")
        assert_true("details" in report, "包含 details 字段")

        print_report_summary(report)

        section("场景 2：空快照预检")

        r, s = api("POST", "/api/snapshot/precheck", empty_snapshot)
        report = r["data"]

        assert_true(report["can_import"] is True, "空快照可以导入")
        assert_true(report["summary"]["status"] == "ready", "状态为 ready")
        assert_true(report["summary"]["total_will_add"] == 0, "新增数量为 0")
        assert_true(report["summary"]["total_conflicts"] == 0, "冲突数为 0")

        for sec in ["books", "active_reservations", "blacklist", "logs"]:
            assert_true(len(report["details"][sec]["will_add"]) == 0,
                        f"{sec} 块 will_add 为空")
            assert_true(len(report["details"][sec]["conflicts"]) == 0,
                        f"{sec} 块 conflicts 为空")

        assert_true(get_book_count() == 0, "预检后书目数仍为 0（不落库）")
        assert_true(len(get_blacklist()) == 0, "预检后黑名单仍为空")
        assert_true(len(get_active_reservations()) == 0, "预检后活跃预约仍为空")

        print("  [INFO] 空快照预检验证通过")

        section("场景 3：预检完整快照 - 全部新增场景")

        test_snapshot = {
            "version": "2.0",
            "type": "full_snapshot",
            "books": [
                {"book_id": "NEW-B001", "title": "新书1", "total_copies": 5, "borrow_days": 30, "retain_hours": 24},
                {"book_id": "NEW-B002", "title": "新书2", "total_copies": 3, "borrow_days": 14, "retain_hours": 12},
            ],
            "active_reservations": [
                {
                    "reservation_id": "test-res-001",
                    "book_id": "NEW-B001",
                    "reader_id": "R-NEW-001",
                    "status": "waiting",
                    "created_at": "2026-06-19T08:00:00+00:00",
                    "available_at": None,
                    "expire_at": None,
                    "borrowed_at": None,
                    "returned_at": None,
                },
                {
                    "reservation_id": "test-res-002",
                    "book_id": "NEW-B001",
                    "reader_id": "R-NEW-002",
                    "status": "waiting",
                    "created_at": "2026-06-19T09:00:00+00:00",
                    "available_at": None,
                    "expire_at": None,
                    "borrowed_at": None,
                    "returned_at": None,
                },
            ],
            "blacklist": [
                {"reader_id": "R-NEW-BL1", "reason": "测试原因", "added_at": "2026-06-19T10:00:00+00:00"},
            ],
            "logs": [
                {
                    "log_id": "test-log-001",
                    "timestamp": "2026-06-19T08:00:00+00:00",
                    "action": "reserve",
                    "reader_id": "R-NEW-001",
                    "book_id": "NEW-B001",
                    "detail": "测试日志",
                    "success": True,
                },
            ],
        }

        r, s = api("POST", "/api/snapshot/precheck", test_snapshot)
        assert_true(s == 200 and r["ok"], "完整快照预检成功")
        report = r["data"]
        print_report_summary(report)

        assert_true(report["can_import"] is True, "可以导入")
        assert_true(report["summary"]["status"] == "ready", "状态为 ready")

        books_add = report["details"]["books"]["will_add"]
        assert_true(len(books_add) == 2, f"书目将新增 2 本，实际 {len(books_add)}")
        assert_true(books_add[0]["book_id"] == "NEW-B001", "第一本是 NEW-B001")

        res_add = report["details"]["active_reservations"]["will_add"]
        assert_true(len(res_add) == 2, f"预约将新增 2 条，实际 {len(res_add)}")

        bl_add = report["details"]["blacklist"]["will_add"]
        assert_true(len(bl_add) == 1, f"黑名单将新增 1 条，实际 {len(bl_add)}")

        logs_add = report["details"]["logs"]["will_add"]
        assert_true(len(logs_add) == 1, f"日志将新增 1 条，实际 {len(logs_add)}")

        queue_check = report["summary"]["queue_order_check"]
        assert_true("NEW-B001" in queue_check, "队列检查包含 NEW-B001")
        assert_true(queue_check["NEW-B001"]["total_active"] == 2, "NEW-B001 有 2 条活跃预约")
        assert_true(queue_check["NEW-B001"]["is_ordered_by_created_at"] is True,
                    "按 created_at 排序")
        assert_true(queue_check["NEW-B001"]["order_by_created_at"][0]["reader_id"] == "R-NEW-001",
                    "队列顺序正确：R-NEW-001 在前")

        avail_check = report["summary"]["availability_check"]
        assert_true("NEW-B001" in avail_check, "可借状态检查包含 NEW-B001")
        assert_true(avail_check["NEW-B001"]["total_copies"] == 5, "NEW-B001 总副本数 5")
        assert_true(avail_check["NEW-B001"]["waiting"] == 2, "NEW-B001 等待中 2 人")
        assert_true(avail_check["NEW-B001"]["available_copies"] == 5, "NEW-B001 可借 5 本")

        assert_true(get_book_count() == 0, "预检后书目数仍为 0（不落库）")

        print("  [INFO] 完整快照预检（全部新增）验证通过")

        section("场景 4：混合冲突预检 - 书目冲突、预约冲突、黑名单冲突、缺依赖")

        setup_test_data()

        mixed_snapshot = {
            "version": "2.0",
            "type": "full_snapshot",
            "books": [
                {"book_id": "PRE-B001", "title": "冲突的书名", "total_copies": 10, "borrow_days": 7, "retain_hours": 1},
                {"book_id": "NEW-B003", "title": "新书3", "total_copies": 2, "borrow_days": 21, "retain_hours": 6},
            ],
            "active_reservations": [
                {
                    "reservation_id": "test-res-conflict",
                    "book_id": "PRE-B001",
                    "reader_id": "R-PRE-001",
                    "status": "waiting",
                    "created_at": "2026-06-19T10:00:00+00:00",
                    "available_at": None,
                    "expire_at": None,
                    "borrowed_at": None,
                    "returned_at": None,
                },
                {
                    "reservation_id": "test-res-missing",
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
            "blacklist": [
                {"reader_id": "R-BLACK-P1", "reason": "不同的原因", "added_at": "2026-06-19T10:00:00+00:00"},
                {"reader_id": "R-NEW-BL2", "reason": "新黑名单", "added_at": "2026-06-19T10:00:00+00:00"},
            ],
            "logs": [],
        }

        r, s = api("POST", "/api/snapshot/precheck", mixed_snapshot)
        assert_true(s == 200 and r["ok"], "混合冲突预检返回 200")
        report = r["data"]
        print_report_summary(report)

        assert_true(report["can_import"] is False, "有冲突，不能导入")
        assert_true(report["summary"]["status"] == "has_conflicts", "状态为 has_conflicts")
        assert_true(report["summary"]["total_conflicts"] == 3,
                    f"共 3 个冲突（书1 + 预约1 + 黑名单1），实际 {report['summary']['total_conflicts']}")
        assert_true(report["summary"]["total_missing_dependencies"] == 1,
                    f"共 1 个缺依赖，实际 {report['summary']['total_missing_dependencies']}")

        book_conflicts = report["details"]["books"]["conflicts"]
        assert_true(len(book_conflicts) == 1, f"书目冲突 1 个，实际 {len(book_conflicts)}")
        assert_true(book_conflicts[0]["type"] == "duplicate_book_id", "冲突类型为 duplicate_book_id")
        assert_true(book_conflicts[0]["book_id"] == "PRE-B001", "冲突书目是 PRE-B001")
        assert_true("existing_config" in book_conflicts[0], "包含 existing_config")
        assert_true("import_config" in book_conflicts[0], "包含 import_config")

        book_will_add = report["details"]["books"]["will_add"]
        assert_true(len(book_will_add) == 1, f"书目将新增 1 本，实际 {len(book_will_add)}")
        assert_true(book_will_add[0]["book_id"] == "NEW-B003", "新增的是 NEW-B003")

        res_conflicts = report["details"]["active_reservations"]["conflicts"]
        assert_true(len(res_conflicts) == 1, f"预约冲突 1 个，实际 {len(res_conflicts)}")
        assert_true(res_conflicts[0]["type"] == "duplicate_reservation",
                    f"冲突类型为 duplicate_reservation，实际 {res_conflicts[0]['type']}")

        res_missing = report["details"]["active_reservations"]["missing_dependencies"]
        assert_true(len(res_missing) == 1, f"缺依赖 1 个，实际 {len(res_missing)}")
        assert_true(res_missing[0]["type"] == "missing_dependency", "类型为 missing_dependency")
        assert_true(res_missing[0]["book_id"] == "NONEXIST-B001", "缺依赖的书目是 NONEXIST-B001")

        bl_conflicts = report["details"]["blacklist"]["conflicts"]
        assert_true(len(bl_conflicts) == 1, f"黑名单冲突 1 个，实际 {len(bl_conflicts)}")
        assert_true(bl_conflicts[0]["type"] == "blacklist_conflict",
                    f"冲突类型为 blacklist_conflict，实际 {bl_conflicts[0]['type']}")
        assert_true("existing_entry" in bl_conflicts[0], "包含 existing_entry")
        assert_true("import_entry" in bl_conflicts[0], "包含 import_entry")

        bl_will_add = report["details"]["blacklist"]["will_add"]
        assert_true(len(bl_will_add) == 1, f"黑名单将新增 1 条，实际 {len(bl_will_add)}")
        assert_true(bl_will_add[0]["reader_id"] == "R-NEW-BL2", "新增的是 R-NEW-BL2")

        print("\n  [冲突明细展示 - 用户可读]")
        print("  " + "-" * 58)
        for sec_name in ["books", "active_reservations", "blacklist"]:
            sec = report["details"][sec_name]
            for c in sec["conflicts"]:
                obj_id = c.get("book_id") or c.get("reader_id", "unknown")
                print(f"  [{sec_name}] [{c['type']}] {obj_id}")
                print(f"    {c['message']}")
            for c in sec["missing_dependencies"]:
                obj_id = c.get("book_id") or c.get("reader_id", "unknown")
                print(f"  [{sec_name}] [missing_dependency] {obj_id}")
                print(f"    {c['message']}")
        print("  " + "-" * 58)

        print("  [INFO] 混合冲突预检验证通过")

        section("场景 5：重复预约检测（快照内重复）")

        dup_res_snapshot = {
            "version": "2.0",
            "type": "full_snapshot",
            "books": [
                {"book_id": "DUP-B001", "title": "重复测试书", "total_copies": 5, "borrow_days": 30, "retain_hours": 24},
            ],
            "active_reservations": [
                {
                    "reservation_id": "dup-res-1",
                    "book_id": "DUP-B001",
                    "reader_id": "R-DUP-001",
                    "status": "waiting",
                    "created_at": "2026-06-19T08:00:00+00:00",
                    "available_at": None,
                    "expire_at": None,
                    "borrowed_at": None,
                    "returned_at": None,
                },
                {
                    "reservation_id": "dup-res-2",
                    "book_id": "DUP-B001",
                    "reader_id": "R-DUP-001",
                    "status": "waiting",
                    "created_at": "2026-06-19T09:00:00+00:00",
                    "available_at": None,
                    "expire_at": None,
                    "borrowed_at": None,
                    "returned_at": None,
                },
            ],
            "blacklist": [],
            "logs": [],
        }

        r, s = api("POST", "/api/snapshot/precheck", dup_res_snapshot)
        report = r["data"]

        res_conflicts = report["details"]["active_reservations"]["conflicts"]
        dup_in_snapshot = [c for c in res_conflicts if c["type"] == "duplicate_reservation_in_snapshot"]
        assert_true(len(dup_in_snapshot) == 1,
                    f"检测到快照内重复预约 1 条，实际 {len(dup_in_snapshot)}")
        assert_true(dup_in_snapshot[0]["reader_id"] == "R-DUP-001", "重复预约的读者是 R-DUP-001")

        print("  [INFO] 重复预约检测验证通过")

        section("场景 6：黑名单原因不一致检测")

        bl_reason_snapshot = {
            "version": "2.0",
            "type": "full_snapshot",
            "books": [],
            "active_reservations": [],
            "blacklist": [
                {"reader_id": "R-BLACK-P1", "reason": "完全不同的原因", "added_at": "2026-06-19T10:00:00+00:00"},
            ],
            "logs": [],
        }

        r, s = api("POST", "/api/snapshot/precheck", bl_reason_snapshot)
        report = r["data"]

        bl_conflicts = report["details"]["blacklist"]["conflicts"]
        reason_conflict = [c for c in bl_conflicts if c["type"] == "blacklist_conflict"]
        assert_true(len(reason_conflict) == 1,
                    f"检测到黑名单原因冲突 1 条，实际 {len(reason_conflict)}")
        assert_true(reason_conflict[0]["existing_entry"]["reason"] != reason_conflict[0]["import_entry"]["reason"],
                    "原因确实不同")

        print(f"  [INFO] 现有原因: {reason_conflict[0]['existing_entry']['reason']}")
        print(f"  [INFO] 导入原因: {reason_conflict[0]['import_entry']['reason']}")
        print("  [INFO] 黑名单原因不一致检测验证通过")

        section("场景 7：格式错误预检")

        bad_format_snapshot = {
            "version": "2.0",
            "type": "full_snapshot",
            "books": [
                {"book_id": "BAD-B001", "title": "坏格式书", "total_copies": "not_a_number", "borrow_days": 30, "retain_hours": 24},
            ],
            "active_reservations": [
                {
                    "reservation_id": "bad-res-1",
                    "book_id": "BAD-B001",
                    "status": "invalid_status",
                    "created_at": "2026-06-19T10:00:00+00:00",
                },
            ],
            "blacklist": [],
            "logs": [],
        }

        r, s = api("POST", "/api/snapshot/precheck", bad_format_snapshot)
        assert_true(s == 200 and r["ok"], "格式错误预检返回 200（预检不报错，返回报告）")
        report = r["data"]

        assert_true(report["can_import"] is False, "格式错误，不能导入")
        assert_true(report["summary"]["status"] == "format_error", "状态为 format_error")
        assert_true(report["summary"]["total_format_errors"] > 0, "有格式错误")

        book_format_errors = report["details"]["books"]["format_errors"]
        assert_true(len(book_format_errors) > 0, "书目有格式错误")

        res_format_errors = report["details"]["active_reservations"]["format_errors"]
        assert_true(len(res_format_errors) > 0, "预约有格式错误")

        print("  [INFO] 格式错误预检验证通过")

        section("场景 8：预检与正式导入口径一致验证")

        clear_data()
        stop_server(server_proc)
        time.sleep(1)
        server_proc = start_server()

        valid_snapshot = {
            "version": "2.0",
            "type": "full_snapshot",
            "books": [
                {"book_id": "VERIFY-B001", "title": "验证书1", "total_copies": 3, "borrow_days": 30, "retain_hours": 24},
            ],
            "active_reservations": [
                {
                    "reservation_id": "verify-res-001",
                    "book_id": "VERIFY-B001",
                    "reader_id": "R-VERIFY-001",
                    "status": "waiting",
                    "created_at": "2026-06-19T08:00:00+00:00",
                    "available_at": None,
                    "expire_at": None,
                    "borrowed_at": None,
                    "returned_at": None,
                },
            ],
            "blacklist": [
                {"reader_id": "R-VERIFY-BL1", "reason": "验证原因", "added_at": "2026-06-19T10:00:00+00:00"},
            ],
            "logs": [
                {
                    "log_id": "verify-log-001",
                    "timestamp": "2026-06-19T08:00:00+00:00",
                    "action": "reserve",
                    "reader_id": "R-VERIFY-001",
                    "book_id": "VERIFY-B001",
                    "detail": "验证日志",
                    "success": True,
                },
            ],
        }

        pre_r, pre_s = api("POST", "/api/snapshot/precheck", valid_snapshot)
        assert_true(pre_s == 200 and pre_r["ok"], "预检成功")
        pre_report = pre_r["data"]
        assert_true(pre_report["can_import"] is True, "预检通过")

        import_r, import_s = api("POST", "/api/snapshot/import?dry_run=false", valid_snapshot)
        assert_true(import_s == 200 and import_r["ok"], "正式导入成功")

        assert_true(get_book_count() == 1, "导入后书目数为 1")
        assert_true(len(get_blacklist()) == 1, "导入后黑名单 1 人")
        assert_true(len(get_active_reservations()) == 1, "导入后活跃预约 1 条")

        pre_will_add_books = {b["book_id"] for b in pre_report["details"]["books"]["will_add"]}
        actual_book_ids = {b["book_id"] for b in api("GET", "/api/books")[0]["data"]}
        assert_true(pre_will_add_books == actual_book_ids,
                    f"预检预测新增书目与实际一致: {pre_will_add_books} == {actual_book_ids}")

        print("  [INFO] 预检与正式导入口径一致验证通过")

        section("场景 9：预检不落库验证（dry-run 不写入）")

        clear_data()
        stop_server(server_proc)
        time.sleep(1)
        server_proc = start_server()

        test_snapshot2 = {
            "version": "2.0",
            "type": "full_snapshot",
            "books": [
                {"book_id": "DRY-B001", "title": "DryRun书", "total_copies": 5, "borrow_days": 30, "retain_hours": 24},
            ],
            "active_reservations": [],
            "blacklist": [],
            "logs": [],
        }

        assert_true(get_book_count() == 0, "预检前书目数为 0")

        r, s = api("POST", "/api/snapshot/precheck", test_snapshot2)
        assert_true(s == 200 and r["ok"], "预检成功")

        assert_true(get_book_count() == 0, "预检后书目数仍为 0（不落库）")

        logs_after = get_all_logs(limit=100)
        precheck_logs = [l for l in logs_after if l["action"] == "precheck_snapshot"]
        assert_true(len(precheck_logs) >= 1, "写入了 precheck_snapshot 汇总日志")
        for pl in precheck_logs:
            assert_true("book_id" not in pl or pl.get("book_id") is None,
                        "预检汇总日志不带 book_id")
            assert_true("reader_id" not in pl or pl.get("reader_id") is None,
                        "预检汇总日志不带 reader_id")

        print("  [INFO] 预检不落库验证通过")

        section("场景 10：正式导入冲突回滚验证")

        clear_data()
        stop_server(server_proc)
        time.sleep(1)
        server_proc = start_server()

        api("POST", "/api/books", {"book_id": "ROLLBACK-B001", "title": "回滚测试书", "total_copies": 3, "borrow_days": 30, "retain_hours": 24})

        conflict_snapshot = {
            "version": "2.0",
            "type": "full_snapshot",
            "books": [
                {"book_id": "ROLLBACK-B001", "title": "冲突书", "total_copies": 10, "borrow_days": 7, "retain_hours": 1},
                {"book_id": "ROLLBACK-B002", "title": "新书", "total_copies": 5, "borrow_days": 30, "retain_hours": 24},
            ],
            "active_reservations": [],
            "blacklist": [],
            "logs": [],
        }

        book_count_before = get_book_count()
        assert_true(book_count_before == 1, f"导入前书目数为 1，实际 {book_count_before}")

        import_r, import_s = api("POST", "/api/snapshot/import?dry_run=false", conflict_snapshot)
        assert_true(import_s == 409, "冲突导入返回 409")

        book_count_after = get_book_count()
        assert_true(book_count_after == 1, f"冲突回滚后书目数仍为 1，实际 {book_count_after}")

        print("  [INFO] 正式导入冲突回滚验证通过")

        section("场景 11：队列顺序和可借状态核对（导出-导入链路）")

        clear_data()
        stop_server(server_proc)
        time.sleep(1)
        server_proc = start_server()

        api("POST", "/api/books", {"book_id": "CHAIN-B001", "title": "链路测试书", "total_copies": 2, "borrow_days": 30, "retain_hours": 24})
        api("POST", "/api/reserve", {"book_id": "CHAIN-B001", "reader_id": "R-CHAIN-001"})
        api("POST", "/api/reserve", {"book_id": "CHAIN-B001", "reader_id": "R-CHAIN-002"})
        api("POST", "/api/reserve", {"book_id": "CHAIN-B001", "reader_id": "R-CHAIN-003"})
        api("POST", "/api/checkout", {"book_id": "CHAIN-B001", "reader_id": "R-CHAIN-001"})

        export_r, _ = api("GET", "/api/snapshot/export")
        snapshot = export_r["data"]

        precheck_r, _ = api("POST", "/api/snapshot/precheck", snapshot)
        report = precheck_r["data"]

        queue_check = report["summary"]["queue_order_check"]
        assert_true("CHAIN-B001" in queue_check, "队列检查包含 CHAIN-B001")
        order = queue_check["CHAIN-B001"]["order_by_created_at"]
        assert_true(len(order) == 3, f"CHAIN-B001 有 3 条活跃预约，实际 {len(order)}")

        reader_order = [r["reader_id"] for r in order]
        assert_true(reader_order[0] == "R-CHAIN-001", "第一个是 R-CHAIN-001 (borrowed)")
        assert_true(order[0]["status"] == "borrowed", "R-CHAIN-001 状态是 borrowed")

        avail_check = report["summary"]["availability_check"]
        assert_true("CHAIN-B001" in avail_check, "可借状态检查包含 CHAIN-B001")
        assert_true(avail_check["CHAIN-B001"]["borrowed"] == 1, "借出 1 本")
        assert_true(avail_check["CHAIN-B001"]["to_pick"] == 1, "待取 1 本")
        assert_true(avail_check["CHAIN-B001"]["waiting"] == 1, "等待 1 人")
        assert_true(avail_check["CHAIN-B001"]["available_copies"] == 0, "可借 0 本")

        print(f"  [INFO] 队列顺序: {reader_order}")
        print(f"  [INFO] 可借状态: 总副本={avail_check['CHAIN-B001']['total_copies']}, "
              f"借出={avail_check['CHAIN-B001']['borrowed']}, "
              f"待取={avail_check['CHAIN-B001']['to_pick']}, "
              f"等待={avail_check['CHAIN-B001']['waiting']}, "
              f"可借={avail_check['CHAIN-B001']['available_copies']}")
        print("  [INFO] 队列顺序和可借状态核对验证通过")

        section("场景 12：服务重启后预检结果一致")

        books_before_restart = {b["book_id"] for b in api("GET", "/api/books")[0]["data"]}
        pre_r1, _ = api("POST", "/api/snapshot/precheck", snapshot)
        report1 = pre_r1["data"]

        stop_server(server_proc)
        time.sleep(1)
        server_proc = start_server()

        books_after_restart = {b["book_id"] for b in api("GET", "/api/books")[0]["data"]}
        assert_true(books_before_restart == books_after_restart, "重启后书目一致")

        pre_r2, _ = api("POST", "/api/snapshot/precheck", snapshot)
        report2 = pre_r2["data"]

        assert_true(report1["can_import"] == report2["can_import"], "重启后 can_import 一致")
        assert_true(report1["summary"]["status"] == report2["summary"]["status"], "重启后 status 一致")
        assert_true(report1["summary"]["total_conflicts"] == report2["summary"]["total_conflicts"],
                    "重启后冲突数一致")
        assert_true(report1["summary"]["total_will_add"] == report2["summary"]["total_will_add"],
                    "重启后新增数一致")

        print("  [INFO] 服务重启后预检结果一致验证通过")

        section("场景 13：日志过滤结果核对")

        logs_by_book_before = get_logs_by_book("CHAIN-B001")
        log_ids_before = {l["log_id"] for l in logs_by_book_before}

        snapshot_log_ids = {l["log_id"] for l in snapshot["logs"] if l.get("book_id") == "CHAIN-B001"}
        assert_true(log_ids_before.issubset(snapshot_log_ids) or snapshot_log_ids.issubset(log_ids_before),
                    "快照中的日志与实际日志按 book_id 查询结果一致")

        print(f"  [INFO] 源环境按 book_id 查询日志数: {len(log_ids_before)}")
        print(f"  [INFO] 快照中对应 book_id 日志数: {len(snapshot_log_ids)}")
        print("  [INFO] 日志过滤结果核对验证通过")

        print("\n" + "=" * 60)
        print("  迁移预检报告回归测试全部通过!")
        print("=" * 60)
        print("\n  能力总结:")
        print("  1. POST /api/snapshot/precheck - 迁移预检报告 API")
        print("  2. 按书目、活跃预约、黑名单、日志四块分类展示")
        print("  3. 每块细分：将新增、冲突、缺依赖、格式错误")
        print("  4. 提供可读的 summary 摘要（状态、消息、统计）")
        print("  5. 复用正式导入的校验和冲突判断，口径完全一致")
        print("  6. 队列顺序核对：按 created_at 排序展示")
        print("  7. 可借状态核对：计算各书目借出/待取/等待/可借数量")
        print("  8. 预检不落库：仅校验不写入，所有数据保持原状")
        print("  9. 服务重启后结果一致")
        print("  10. 导出-导入链路完整验证")

    finally:
        stop_server(server_proc)

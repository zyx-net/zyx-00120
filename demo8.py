import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
import hashlib

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


def get_blacklist():
    r, _ = api("GET", "/api/blacklist")
    return r["data"] if r.get("ok") and r.get("data") else []


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


def get_logs_by_book(book_id, limit=100):
    r, _ = api("GET", f"/api/logs?book_id={book_id}&limit={limit}")
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


def get_data_file_fingerprint():
    fingerprint = {}
    for name in ["books", "reservations", "blacklist", "logs"]:
        p = os.path.join(DATA_DIR, f"{name}.json")
        if os.path.exists(p):
            with open(p, "rb") as f:
                content = f.read()
            fingerprint[name] = {
                "exists": True,
                "size": len(content),
                "mtime": os.path.getmtime(p),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        else:
            fingerprint[name] = {
                "exists": False,
                "size": 0,
                "mtime": None,
                "sha256": None,
            }
    return fingerprint


def assert_data_files_unchanged(before, after, label=""):
    all_ok = True
    for name in ["books", "reservations", "blacklist", "logs"]:
        b = before[name]
        a = after[name]
        if b["exists"] != a["exists"]:
            print(f"  [FAIL] {label}: {name}.json 存在性变化: {b['exists']} -> {a['exists']}")
            all_ok = False
        elif b["exists"]:
            if b["sha256"] != a["sha256"]:
                print(f"  [FAIL] {label}: {name}.json SHA256 变化")
                print(f"    之前: {b['sha256'][:16]}... ({b['size']} bytes)")
                print(f"    之后: {a['sha256'][:16]}... ({a['size']} bytes)")
                all_ok = False
    if all_ok:
        print(f"  [PASS] {label}: data/ 下所有 JSON 文件完全未变")
    else:
        sys.exit(1)


def assert_business_data_unchanged(before, after, label=""):
    all_ok = True
    for name in ["books", "reservations", "blacklist"]:
        b = before[name]
        a = after[name]
        if b["exists"] != a["exists"]:
            print(f"  [FAIL] {label}: {name}.json 存在性变化: {b['exists']} -> {a['exists']}")
            all_ok = False
        elif b["exists"]:
            if b["sha256"] != a["sha256"]:
                print(f"  [FAIL] {label}: {name}.json SHA256 变化")
                print(f"    之前: {b['sha256'][:16]}... ({b['size']} bytes)")
                print(f"    之后: {a['sha256'][:16]}... ({a['size']} bytes)")
                all_ok = False
    if all_ok:
        print(f"  [PASS] {label}: 业务数据文件（books/reservations/blacklist）完全未变")
    else:
        sys.exit(1)


def assert_report_structure(report, label=""):
    assert_true("dry_run" in report, f"{label}: report 有 dry_run 字段")
    assert_true("can_import" in report, f"{label}: report 有 can_import 字段")
    assert_true("summary" in report, f"{label}: report 有 summary 字段")
    assert_true("details" in report, f"{label}: report 有 details 字段")

    s = report["summary"]
    assert_true("status" in s, f"{label}: summary 有 status 字段")
    assert_true("message" in s, f"{label}: summary 有 message 字段")
    assert_true("total_will_add" in s, f"{label}: summary 有 total_will_add 字段")
    assert_true("total_will_skip" in s, f"{label}: summary 有 total_will_skip 字段")
    assert_true("total_will_block" in s, f"{label}: summary 有 total_will_block 字段")
    assert_true("total_conflicts" in s, f"{label}: summary 有 total_conflicts 字段")
    assert_true("total_missing_dependencies" in s, f"{label}: summary 有 total_missing_dependencies 字段")
    assert_true("total_format_errors" in s, f"{label}: summary 有 total_format_errors 字段")
    assert_true("breakdown" in s, f"{label}: summary 有 breakdown 字段")

    d = report["details"]
    for sec in ["books", "active_reservations", "blacklist", "logs"]:
        assert_true(sec in d, f"{label}: details 有 {sec} 字段")
        sec_d = d[sec]
        for key in ["will_add", "will_skip", "will_block", "conflicts", "missing_dependencies", "format_errors"]:
            assert_true(key in sec_d, f"{label}: details.{sec} 有 {key} 字段")
            assert_true(isinstance(sec_d[key], list), f"{label}: details.{sec}.{key} 是列表")

    print(f"  [PASS] {label}: report 结构完整（summary + details，四块四类）")


def make_clean_snapshot():
    return {
        "version": "2.0",
        "type": "full_snapshot",
        "books": [
            {"book_id": "TEST-B001", "title": "测试书1", "total_copies": 3, "borrow_days": 30, "retain_hours": 24},
            {"book_id": "TEST-B002", "title": "测试书2", "total_copies": 1, "borrow_days": 14, "retain_hours": 12},
        ],
        "active_reservations": [
            {
                "reservation_id": "test-res-1",
                "book_id": "TEST-B001",
                "reader_id": "R-TEST-001",
                "status": "available",
                "created_at": "2026-06-19T07:00:00+00:00",
                "available_at": "2026-06-19T07:00:00+00:00",
                "expire_at": "2026-06-20T07:00:00+00:00",
                "borrowed_at": None,
                "returned_at": None,
            },
            {
                "reservation_id": "test-res-2",
                "book_id": "TEST-B001",
                "reader_id": "R-TEST-002",
                "status": "waiting",
                "created_at": "2026-06-19T08:00:00+00:00",
                "available_at": None,
                "expire_at": None,
                "borrowed_at": None,
                "returned_at": None,
            },
            {
                "reservation_id": "test-res-3",
                "book_id": "TEST-B002",
                "reader_id": "R-TEST-004",
                "status": "borrowed",
                "created_at": "2026-06-18T10:00:00+00:00",
                "available_at": "2026-06-18T10:00:00+00:00",
                "expire_at": None,
                "borrowed_at": "2026-06-18T11:00:00+00:00",
                "returned_at": None,
            },
        ],
        "blacklist": [
            {"reader_id": "R-TEST-BL1", "reason": "测试黑名单原因1", "added_at": "2026-06-18T00:00:00+00:00"},
            {"reader_id": "R-TEST-BL2", "reason": "测试黑名单原因2", "added_at": "2026-06-19T00:00:00+00:00"},
        ],
        "logs": [
            {"log_id": "test-log-7", "timestamp": "2026-06-18T07:00:00+00:00", "action": "blacklist_add",
             "reader_id": "R-TEST-BL1", "success": True, "detail": "加入黑名单"},
            {"log_id": "test-log-8", "timestamp": "2026-06-18T07:00:01+00:00", "action": "blacklist_add",
             "reader_id": "R-TEST-BL2", "success": True, "detail": "加入黑名单"},
            {"log_id": "test-log-1", "timestamp": "2026-06-18T09:00:00+00:00", "action": "add_book",
             "book_id": "TEST-B001", "success": True, "detail": "创建书目"},
            {"log_id": "test-log-2", "timestamp": "2026-06-18T09:00:01+00:00", "action": "add_book",
             "book_id": "TEST-B002", "success": True, "detail": "创建书目"},
            {"log_id": "test-log-3", "timestamp": "2026-06-18T10:00:00+00:00", "action": "reserve",
             "book_id": "TEST-B002", "reader_id": "R-TEST-004", "success": True, "detail": "预约"},
            {"log_id": "test-log-4", "timestamp": "2026-06-18T11:00:00+00:00", "action": "checkout",
             "book_id": "TEST-B002", "reader_id": "R-TEST-004", "success": True, "detail": "借出"},
            {"log_id": "test-log-5", "timestamp": "2026-06-19T07:00:00+00:00", "action": "reserve",
             "book_id": "TEST-B001", "reader_id": "R-TEST-001", "success": True, "detail": "预约并待取"},
            {"log_id": "test-log-6", "timestamp": "2026-06-19T08:00:00+00:00", "action": "reserve",
             "book_id": "TEST-B001", "reader_id": "R-TEST-002", "success": True, "detail": "排队等待"},
        ],
    }


def make_format_error_snapshot():
    snap = make_clean_snapshot()
    snap["logs"] = [
        "字符串混入日志",
        12345,
        {"log_id": "ok-log-1", "timestamp": "2026-06-19T08:00:00+00:00", "action": "add_book",
         "book_id": "TEST-B001", "success": True},
        {"log_id": "bad-log-1"},
        {"log_id": "bad-log-2", "timestamp": "2026-06-19T09:00:00+00:00", "action": "reserve",
         "book_id": "TEST-B001", "success": "not_bool"},
    ]
    return snap


def make_conflict_snapshot():
    snap = make_clean_snapshot()
    snap["books"][0]["title"] = "冲突的书名"
    snap["books"][0]["total_copies"] = 99
    return snap


if __name__ == "__main__":
    clear_data()
    server_proc = start_server()

    try:
        section("场景 1：正式导入成功（200）返回完整 report")

        clean_snap = make_clean_snapshot()
        fp_before = get_data_file_fingerprint()

        r, s = api("POST", "/api/snapshot/import?dry_run=false", clean_snap)
        assert_true(s == 200, "正式导入成功返回 HTTP 200")
        assert_true(r.get("ok") is True, "正式导入成功 ok=True")
        assert_true(r.get("dry_run") is False, "正式导入 dry_run=False")

        assert_true("report" in r, "正式导入成功响应中包含 report 字段")
        report = r["report"]
        assert_report_structure(report, "正式导入成功")

        assert_true(report["dry_run"] is False, "正式导入成功 report.dry_run = False")
        assert_true(report["can_import"] is True, "正式导入成功 report.can_import = True")
        assert_true(report["summary"]["status"] == "ready",
                    f"正式导入成功 summary.status = ready（实际: {report['summary']['status']}）")

        s = report["summary"]
        assert_true(s["total_will_add"] == 2 + 3 + 2 + 8,
                    f"will_add 总数 = 2书 + 3预约 + 2黑名单 + 8日志 = 15，实际: {s['total_will_add']}")
        assert_true(s["total_will_skip"] == 0, f"will_skip 总数 = 0，实际: {s['total_will_skip']}")
        assert_true(s["total_will_block"] == 0, f"will_block 总数 = 0，实际: {s['total_will_block']}")
        assert_true(s["total_conflicts"] == 0, f"conflicts 总数 = 0，实际: {s['total_conflicts']}")
        assert_true(s["total_format_errors"] == 0, f"format_errors 总数 = 0，实际: {s['total_format_errors']}")

        bd = s["breakdown"]
        assert_true(bd["books"]["will_add"] == 2, f"books will_add = 2，实际: {bd['books']['will_add']}")
        assert_true(bd["active_reservations"]["will_add"] == 3,
                    f"active_reservations will_add = 3，实际: {bd['active_reservations']['will_add']}")
        assert_true(bd["blacklist"]["will_add"] == 2,
                    f"blacklist will_add = 2，实际: {bd['blacklist']['will_add']}")
        assert_true(bd["logs"]["will_add"] == 8,
                    f"logs will_add = 8，实际: {bd['logs']['will_add']}")

        details = report["details"]
        assert_true(len(details["books"]["will_add"]) == 2, "books.will_add 列表长度=2")
        assert_true(details["books"]["will_add"][0]["book_id"] == "TEST-B001",
                    "第一本书 book_id = TEST-B001")
        assert_true(details["books"]["will_add"][0]["title"] == "测试书1",
                    "第一本书 title 正确")

        assert_true(len(details["active_reservations"]["will_add"]) == 3,
                    "active_reservations.will_add 列表长度=3")
        assert_true(details["active_reservations"]["will_add"][0]["reader_id"] == "R-TEST-001",
                    "第一条预约 reader_id = R-TEST-001")
        assert_true(details["active_reservations"]["will_add"][0]["status"] == "available",
                    "第一条预约状态 = available")

        assert_true(len(details["blacklist"]["will_add"]) == 2,
                    "blacklist.will_add 列表长度=2")

        assert_true(len(details["logs"]["will_add"]) == 8,
                    "logs.will_add 列表长度=8")

        print(f"\n  [导入成功 report 摘要]")
        print(f"    状态: {report['summary']['status']}")
        print(f"    消息: {report['summary']['message']}")
        print(f"    will_add: {report['summary']['total_will_add']}")
        print(f"    will_skip: {report['summary']['total_will_skip']}")
        print(f"    will_block: {report['summary']['total_will_block']}")
        print(f"    冲突: {report['summary']['total_conflicts']}")
        print(f"    格式错误: {report['summary']['total_format_errors']}")

        assert_true(get_book_count() == 2, "导入后书目数 = 2")
        assert_true(len(get_blacklist()) == 2, "导入后黑名单数 = 2")

        section("场景 2：正式导入冲突（409）返回完整 report")

        conflict_snap = make_conflict_snapshot()
        fp_before_conflict = get_data_file_fingerprint()

        r2, s2 = api("POST", "/api/snapshot/import?dry_run=false", conflict_snap)
        assert_true(s2 == 409, "正式导入冲突返回 HTTP 409")
        assert_true(r2.get("ok") is False, "正式导入冲突 ok=False")
        assert_true(r2.get("dry_run") is False, "正式导入冲突 dry_run=False")
        assert_true("conflicts" in r2, "正式导入冲突响应中有 conflicts 字段")

        assert_true("report" in r2, "正式导入冲突响应中包含 report 字段")
        report2 = r2["report"]
        assert_report_structure(report2, "正式导入冲突")

        assert_true(report2["dry_run"] is False, "正式导入冲突 report.dry_run = False")
        assert_true(report2["can_import"] is False, "正式导入冲突 report.can_import = False")
        assert_true(report2["summary"]["status"] == "has_conflicts",
                    f"正式导入冲突 summary.status = has_conflicts（实际: {report2['summary']['status']}）")

        s2_sum = report2["summary"]
        assert_true(s2_sum["total_conflicts"] > 0, f"冲突数 > 0，实际: {s2_sum['total_conflicts']}")
        assert_true(s2_sum["total_will_skip"] > 0, f"will_skip > 0，实际: {s2_sum['total_will_skip']}")

        bd2 = s2_sum["breakdown"]
        assert_true(bd2["books"]["conflicts"] == 2,
                    f"books conflicts = 2（两本书都冲突），实际: {bd2['books']['conflicts']}")
        assert_true(bd2["books"]["will_skip"] == 2,
                    f"books will_skip = 2，实际: {bd2['books']['will_skip']}")

        fp_after_conflict = get_data_file_fingerprint()
        assert_business_data_unchanged(fp_before_conflict, fp_after_conflict, "场景2 冲突后业务数据")

        book_conflicts = report2["details"]["books"]["conflicts"]
        assert_true(len(book_conflicts) == 2, "书目冲突明细有 2 条")
        assert_true(book_conflicts[0]["type"] == "duplicate_book_id",
                    f"冲突类型 = duplicate_book_id，实际: {book_conflicts[0]['type']}")
        assert_true(book_conflicts[0]["book_id"] == "TEST-B001",
                    f"冲突 book_id = TEST-B001，实际: {book_conflicts[0]['book_id']}")
        assert_true("existing_config" in book_conflicts[0], "冲突明细有 existing_config")
        assert_true("import_config" in book_conflicts[0], "冲突明细有 import_config")
        assert_true("message" in book_conflicts[0], "冲突明细有 message")

        print(f"\n  [导入冲突 report 摘要]")
        print(f"    状态: {report2['summary']['status']}")
        print(f"    消息: {report2['summary']['message']}")
        print(f"    冲突总数: {report2['summary']['total_conflicts']}")
        print(f"    will_add: {report2['summary']['total_will_add']}")
        print(f"    will_skip: {report2['summary']['total_will_skip']}")

        section("场景 3：正式导入格式错误（400）返回完整 report")

        bad_snap = make_format_error_snapshot()
        fp_before_bad = get_data_file_fingerprint()
        books_before = get_book_count()

        r3, s3 = api("POST", "/api/snapshot/import?dry_run=false", bad_snap)
        assert_true(s3 == 400, "正式导入格式错误返回 HTTP 400")
        assert_true(r3.get("ok") is False, "正式导入格式错误 ok=False")
        assert_true("error" in r3, "正式导入格式错误响应中有 error 字段")
        assert_true(isinstance(r3["error"], list), "error 是列表")

        assert_true("report" in r3, "正式导入格式错误响应中包含 report 字段")
        report3 = r3["report"]
        assert_report_structure(report3, "正式导入格式错误")

        assert_true(report3["dry_run"] is False, "正式导入格式错误 report.dry_run = False")
        assert_true(report3["can_import"] is False, "正式导入格式错误 report.can_import = False")
        assert_true(report3["summary"]["status"] == "format_error",
                    f"正式导入格式错误 summary.status = format_error（实际: {report3['summary']['status']}）")

        s3_sum = report3["summary"]
        assert_true(s3_sum["total_format_errors"] > 0,
                    f"格式错误数 > 0，实际: {s3_sum['total_format_errors']}")
        assert_true(s3_sum["total_will_block"] > 0,
                    f"will_block > 0，实际: {s3_sum['total_will_block']}")

        bd3 = s3_sum["breakdown"]
        assert_true(bd3["logs"]["format_errors"] > 0,
                    f"logs format_errors > 0，实际: {bd3['logs']['format_errors']}")
        assert_true(bd3["logs"]["will_block"] > 0,
                    f"logs will_block > 0，实际: {bd3['logs']['will_block']}")

        fp_after_bad = get_data_file_fingerprint()
        assert_data_files_unchanged(fp_before_bad, fp_after_bad, "场景3 格式错误后数据文件")

        books_after = get_book_count()
        assert_true(books_after == books_before,
                    f"格式错误后书目数不变: {books_before} == {books_after}")

        log_fe = report3["details"]["logs"]["format_errors"]
        assert_true(len(log_fe) > 0, "日志格式错误明细非空")

        string_log_errs = [fe for fe in log_fe if fe.get("error_code") == "log_not_object"]
        assert_true(len(string_log_errs) >= 2,
                    f"检测到字符串/数字混入日志至少 2 条，实际: {len(string_log_errs)}")

        missing_field_errs = [fe for fe in log_fe if fe.get("error_code") == "log_missing_field"]
        assert_true(len(missing_field_errs) >= 1,
                    f"检测到缺必填字段日志至少 1 条，实际: {len(missing_field_errs)}")

        success_type_errs = [fe for fe in log_fe if fe.get("error_code") == "log_invalid_success_type"]
        assert_true(len(success_type_errs) >= 1,
                    f"检测到 success 类型错误至少 1 条，实际: {len(success_type_errs)}")

        for fe in log_fe:
            assert_true("index" in fe, "格式错误明细有 index 字段")
            assert_true("message" in fe, "格式错误明细有 message 字段")
            assert_true("error_code" in fe, "格式错误明细有 error_code 字段")
            assert_true("blocks_other_blocks" in fe, "格式错误明细有 blocks_other_blocks 字段")
            assert_true("blocks_current_block" in fe, "格式错误明细有 blocks_current_block 字段")

        print(f"\n  [导入格式错误 report 摘要]")
        print(f"    状态: {report3['summary']['status']}")
        print(f"    消息: {report3['summary']['message']}")
        print(f"    格式错误总数: {report3['summary']['total_format_errors']}")
        print(f"    will_block: {report3['summary']['total_will_block']}")
        print(f"    will_add: {report3['summary']['total_will_add']}")

        section("场景 4：三方口径一致 - 预检 / dry-run / 正式导入 report 结构完全相同")

        subsection("4.1 成功场景：三方 report 结构一致")

        clear_data()
        stop_server(server_proc)
        time.sleep(1)
        server_proc = start_server()

        test_snap = make_clean_snapshot()

        pre_r, pre_s = api("POST", "/api/snapshot/precheck", test_snap)
        assert_true(pre_s == 200, "预检 HTTP 200")
        pre_report = pre_r["data"]
        assert_report_structure(pre_report, "预检成功")

        dry_r, dry_s = api("POST", "/api/snapshot/import?dry_run=true", test_snap)
        assert_true(dry_s == 200, "dry-run 成功 HTTP 200")
        dry_report = dry_r["report"]
        assert_report_structure(dry_report, "dry-run 成功")

        imp_r, imp_s = api("POST", "/api/snapshot/import?dry_run=false", test_snap)
        assert_true(imp_s == 200, "正式导入成功 HTTP 200")
        imp_report = imp_r["report"]
        assert_report_structure(imp_report, "正式导入成功")

        assert_true(pre_report["summary"]["status"] == dry_report["summary"]["status"],
                    "预检与 dry-run status 一致")
        assert_true(dry_report["summary"]["status"] == imp_report["summary"]["status"],
                    "dry-run 与正式导入 status 一致")

        assert_true(pre_report["can_import"] == dry_report["can_import"],
                    "预检与 dry-run can_import 一致")
        assert_true(dry_report["can_import"] == imp_report["can_import"],
                    "dry-run 与正式导入 can_import 一致")

        for sec in ["books", "active_reservations", "blacklist", "logs"]:
            for key in ["will_add", "will_skip", "will_block", "conflicts", "format_errors"]:
                pre_count = len(pre_report["details"][sec][key])
                dry_count = len(dry_report["details"][sec][key])
                imp_count = len(imp_report["details"][sec][key])
                assert_true(pre_count == dry_count == imp_count,
                            f"[{sec}] {key} 数量三方一致: {pre_count}")

        pre_total_add = pre_report["summary"]["total_will_add"]
        dry_total_add = dry_report["summary"]["total_will_add"]
        imp_total_add = imp_report["summary"]["total_will_add"]
        assert_true(pre_total_add == dry_total_add == imp_total_add,
                    f"total_will_add 三方一致: {pre_total_add}")

        assert_true(pre_report["dry_run"] is True, "预检 report.dry_run = True")
        assert_true(dry_report["dry_run"] is True, "dry-run report.dry_run = True")
        assert_true(imp_report["dry_run"] is False, "正式导入 report.dry_run = False")

        print("  [成功场景] 三方 report 结构和统计完全一致")

        subsection("4.2 冲突场景：dry-run 与正式导入 report 结构一致")

        conflict_snap2 = make_conflict_snapshot()

        pre2_r, _ = api("POST", "/api/snapshot/precheck", conflict_snap2)
        pre2_report = pre2_r["data"]

        dry2_r, dry2_s = api("POST", "/api/snapshot/import?dry_run=true", conflict_snap2)
        assert_true(dry2_s == 409, "冲突场景 dry-run 返回 409")
        dry2_report = dry2_r["report"]

        imp2_r, imp2_s = api("POST", "/api/snapshot/import?dry_run=false", conflict_snap2)
        assert_true(imp2_s == 409, "冲突场景正式导入返回 409")
        imp2_report = imp2_r["report"]

        assert_true(pre2_report["summary"]["status"] == dry2_report["summary"]["status"],
                    "冲突场景预检与 dry-run status 一致")
        assert_true(dry2_report["summary"]["status"] == imp2_report["summary"]["status"],
                    "冲突场景 dry-run 与正式导入 status 一致")

        assert_true(pre2_report["summary"]["total_conflicts"] == dry2_report["summary"]["total_conflicts"],
                    "冲突场景预检与 dry-run 冲突数一致")
        assert_true(dry2_report["summary"]["total_conflicts"] == imp2_report["summary"]["total_conflicts"],
                    "冲突场景 dry-run 与正式导入冲突数一致")

        for sec in ["books", "active_reservations", "blacklist", "logs"]:
            pre_c = len(pre2_report["details"][sec]["conflicts"])
            dry_c = len(dry2_report["details"][sec]["conflicts"])
            imp_c = len(imp2_report["details"][sec]["conflicts"])
            assert_true(pre_c == dry_c == imp_c,
                        f"冲突场景 [{sec}] conflicts 数量三方一致: {pre_c}")

        print("  [冲突场景] 三方 report 结构和统计完全一致")

        subsection("4.3 格式错误场景：dry-run 与正式导入 report 结构一致")

        bad_snap2 = make_format_error_snapshot()

        pre3_r, _ = api("POST", "/api/snapshot/precheck", bad_snap2)
        pre3_report = pre3_r["data"]

        dry3_r, dry3_s = api("POST", "/api/snapshot/import?dry_run=true", bad_snap2)
        assert_true(dry3_s == 400, "格式错误场景 dry-run 返回 400")
        dry3_report = dry3_r["report"]

        imp3_r, imp3_s = api("POST", "/api/snapshot/import?dry_run=false", bad_snap2)
        assert_true(imp3_s == 400, "格式错误场景正式导入返回 400")
        imp3_report = imp3_r["report"]

        assert_true(pre3_report["summary"]["status"] == dry3_report["summary"]["status"],
                    "格式错误场景预检与 dry-run status 一致")
        assert_true(dry3_report["summary"]["status"] == imp3_report["summary"]["status"],
                    "格式错误场景 dry-run 与正式导入 status 一致")

        assert_true(pre3_report["summary"]["total_format_errors"] == dry3_report["summary"]["total_format_errors"],
                    "格式错误场景预检与 dry-run 格式错误数一致")
        assert_true(dry3_report["summary"]["total_format_errors"] == imp3_report["summary"]["total_format_errors"],
                    "格式错误场景 dry-run 与正式导入格式错误数一致")

        for sec in ["books", "active_reservations", "blacklist", "logs"]:
            pre_fe = len(pre3_report["details"][sec]["format_errors"])
            dry_fe = len(dry3_report["details"][sec]["format_errors"])
            imp_fe = len(imp3_report["details"][sec]["format_errors"])
            assert_true(pre_fe == dry_fe == imp_fe,
                        f"格式错误场景 [{sec}] format_errors 数量三方一致: {pre_fe}")

        print("  [格式错误场景] 三方 report 结构和统计完全一致")

        section("场景 5：空目标环境首次导入 - report 内容与实际落库一致")

        clear_data()
        stop_server(server_proc)
        time.sleep(1)
        server_proc = start_server()

        fp_empty = get_data_file_fingerprint()
        assert_true(fp_empty["books"]["exists"] is False, "空环境 books.json 不存在")
        assert_true(get_book_count() == 0, "空环境书目数为 0")

        empty_snap = make_clean_snapshot()

        pre_r, _ = api("POST", "/api/snapshot/precheck", empty_snap)
        pre_report = pre_r["data"]
        assert_true(pre_report["can_import"] is True, "空环境预检 can_import=True")
        assert_true(pre_report["summary"]["status"] == "ready", "空环境预检 status=ready")
        assert_true(pre_report["summary"]["total_will_add"] == 2 + 3 + 2 + 8,
                    f"空环境预检 will_add=15，实际: {pre_report['summary']['total_will_add']}")

        fp_pre_after = get_data_file_fingerprint()
        assert_data_files_unchanged(fp_empty, fp_pre_after, "空环境预检后")

        imp_r, imp_s = api("POST", "/api/snapshot/import?dry_run=false", empty_snap)
        assert_true(imp_s == 200, "空环境首次导入成功")
        imp_report = imp_r["report"]

        assert_true(get_book_count() == imp_report["summary"]["breakdown"]["books"]["will_add"],
                    "导入后书目数与 report 中 books.will_add 一致")
        assert_true(len(get_blacklist()) == imp_report["summary"]["breakdown"]["blacklist"]["will_add"],
                    "导入后黑名单数与 report 中 blacklist.will_add 一致")

        queue_b1 = get_active_reservations("TEST-B001")
        expected_res_count = imp_report["summary"]["breakdown"]["active_reservations"]["will_add"]
        actual_res_count = len(get_active_reservations())
        assert_true(actual_res_count == expected_res_count,
                    f"导入后活跃预约数与 report 一致: {expected_res_count}")

        logs_b1 = get_logs_by_book("TEST-B001", limit=100)
        expected_log_ids = {l["log_id"] for l in empty_snap["logs"] if l.get("book_id") == "TEST-B001"}
        actual_log_ids = {l["log_id"] for l in logs_b1}
        assert_true(expected_log_ids == actual_log_ids,
                    f"导入后 TEST-B001 日志与源快照一致: {len(expected_log_ids)} 条")

        all_logs_after = get_all_logs(limit=500)
        import_summary_logs = [l for l in all_logs_after if l["action"] == "import_snapshot"]
        assert_true(len(import_summary_logs) == 1, "导入后有 1 条 import_snapshot 汇总日志")
        for sl in import_summary_logs:
            assert_true(sl.get("book_id") is None or "book_id" not in sl,
                        "import_snapshot 日志不带 book_id")
            assert_true(sl.get("reader_id") is None or "reader_id" not in sl,
                        "import_snapshot 日志不带 reader_id")

        print("  [空环境首次导入] report 内容与实际落库完全一致")

        section("场景 6：混合有效和无效日志 - report 明细与实际过滤一致")

        mixed_snap = {
            "version": "2.0",
            "type": "full_snapshot",
            "books": [
                {"book_id": "MIX-B001", "title": "混合日志测试书", "total_copies": 5, "borrow_days": 30, "retain_hours": 24},
            ],
            "active_reservations": [],
            "blacklist": [],
            "logs": [
                "字符串混入_混合测试",
                {"log_id": "mix-ok-1", "timestamp": "2026-06-19T08:00:00+00:00", "action": "add_book",
                 "book_id": "MIX-B001", "success": True},
                {"log_id": "mix-ok-2", "timestamp": "2026-06-19T09:00:00+00:00", "action": "reserve",
                 "book_id": "MIX-B001", "reader_id": "R-MIX-001", "success": True},
                {"timestamp": "2026-06-19T10:00:00+00:00", "action": "reserve",
                 "book_id": "MIX-B001", "success": "bad_type"},
                {"log_id": "mix-ok-3", "timestamp": "2026-06-19T11:00:00+00:00", "action": "checkout",
                 "book_id": "MIX-B001", "reader_id": "R-MIX-001", "success": True},
                {"log_id": "mix-dup-1", "timestamp": "2026-06-19T12:00:00+00:00", "action": "return",
                 "book_id": "MIX-B001", "reader_id": "R-MIX-001", "success": True},
                {"log_id": "mix-dup-1", "timestamp": "2026-06-19T13:00:00+00:00", "action": "reserve",
                 "book_id": "MIX-B001", "reader_id": "R-MIX-002", "success": True},
                {"log_id": "mix-bad-ref", "timestamp": "2026-06-19T14:00:00+00:00", "action": "delete_book",
                 "book_id": "NO-SUCH-BOOK-12345", "success": True},
            ],
        }

        pre_r, _ = api("POST", "/api/snapshot/precheck", mixed_snap)
        mix_report = pre_r["data"]

        assert_true(mix_report["can_import"] is False, "混合日志场景 can_import=False（有格式错误）")
        assert_true(mix_report["summary"]["status"] == "format_error",
                    f"混合日志场景 status=format_error，实际: {mix_report['summary']['status']}")

        logs_will_add = mix_report["details"]["logs"]["will_add"]
        logs_will_block = mix_report["details"]["logs"]["will_block"]
        logs_issues = mix_report["details"]["logs"].get("issues", [])

        print(f"\n  [混合日志统计]")
        print(f"    will_add: {len(logs_will_add)} 条")
        print(f"    will_block: {len(logs_will_block)} 条")
        print(f"    issues: {len(logs_issues)} 条")

        assert_true(len(logs_will_add) >= 4, "至少 4 条有效日志可导入")
        assert_true(len(logs_will_block) >= 2, "至少 2 条日志被拦下（字符串+类型错）")
        assert_true(len(logs_issues) >= 2, "至少 2 条日志 issue（重复log_id + 引用不存在）")

        ok_log_ids = {l["log_id"] for l in logs_will_add}
        assert_true("mix-ok-1" in ok_log_ids, "有效日志 mix-ok-1 在 will_add 中")
        assert_true("mix-ok-2" in ok_log_ids, "有效日志 mix-ok-2 在 will_add 中")
        assert_true("mix-ok-3" in ok_log_ids, "有效日志 mix-ok-3 在 will_add 中")
        assert_true("mix-dup-1" in ok_log_ids, "重复 log_id 依然在 will_add 中（非阻断）")

        dup_issues = [i for i in logs_issues if i.get("type") == "duplicate_log_id_in_snapshot"]
        assert_true(len(dup_issues) == 1, "1 条重复 log_id issue")
        assert_true(dup_issues[0].get("blocks_other_blocks") is False,
                    "重复 log_id 不阻断其他块")
        assert_true(dup_issues[0].get("blocks_current_block") is False,
                    "重复 log_id 不阻断当前日志块")

        ref_issues = [i for i in logs_issues if i.get("type") == "log_references_missing_book"]
        assert_true(len(ref_issues) == 1, "1 条引用不存在书目 issue")

        fp_before_dry = get_data_file_fingerprint()
        dry_r, dry_s = api("POST", "/api/snapshot/import?dry_run=true", mixed_snap)
        assert_true(dry_s == 400, "混合日志 dry-run 返回 400")
        fp_after_dry = get_data_file_fingerprint()
        assert_data_files_unchanged(fp_before_dry, fp_after_dry, "混合日志 dry-run 后")

        assert_true("report" in dry_r, "混合日志 dry-run 响应有 report")
        dry_report = dry_r["report"]
        assert_true(dry_report["summary"]["total_format_errors"] == mix_report["summary"]["total_format_errors"],
                    "dry-run 与预检格式错误数一致")

        print("  [混合日志] report 明细完整，dry-run 不落库")

        section("场景 7：服务重启后重复提交 - 冲突判断一致，回滚完整")

        subsection("7.1 重启后预检结果一致")

        pre_restart_r, _ = api("POST", "/api/snapshot/precheck", make_clean_snapshot())
        pre_restart_report = pre_restart_r["data"]
        pre_restart_can = pre_restart_report["can_import"]
        pre_restart_conflicts = pre_restart_report["summary"]["total_conflicts"]

        stop_server(server_proc)
        time.sleep(1)
        server_proc = start_server()

        post_restart_r, _ = api("POST", "/api/snapshot/precheck", make_clean_snapshot())
        post_restart_report = post_restart_r["data"]

        assert_true(pre_restart_can == post_restart_report["can_import"],
                    f"重启后 can_import 一致: {pre_restart_can}")
        assert_true(pre_restart_conflicts == post_restart_report["summary"]["total_conflicts"],
                    f"重启后冲突数一致: {pre_restart_conflicts}")

        subsection("7.2 重启后重复提交导入 - 冲突，回滚完整")

        books_before = get_book_count()
        bl_before = len(get_blacklist())
        queue_before_b1 = len(get_active_reservations("TEST-B001"))
        fp_before_dup = get_data_file_fingerprint()

        dup_r, dup_s = api("POST", "/api/snapshot/import?dry_run=false", make_clean_snapshot())
        assert_true(dup_s == 409, "重启后重复提交返回 409")
        assert_true("report" in dup_r, "重启后重复提交响应有 report")

        dup_report = dup_r["report"]
        assert_true(dup_report["can_import"] is False, "重复提交 report.can_import=False")
        assert_true(dup_report["summary"]["status"] == "has_conflicts",
                    f"重复提交 status=has_conflicts，实际: {dup_report['summary']['status']}")

        fp_after_dup = get_data_file_fingerprint()
        assert_business_data_unchanged(fp_before_dup, fp_after_dup, "重启后重复提交后业务数据")

        books_after = get_book_count()
        bl_after = len(get_blacklist())
        queue_after_b1 = len(get_active_reservations("TEST-B001"))

        assert_true(books_after == books_before,
                    f"重复提交后书目数不变: {books_before} == {books_after}")
        assert_true(bl_after == bl_before,
                    f"重复提交后黑名单数不变: {bl_before} == {bl_after}")
        assert_true(queue_after_b1 == queue_before_b1,
                    f"重复提交后 TEST-B001 队列长度不变: {queue_before_b1} == {queue_after_b1}")

        print("  [重启后重复提交] 冲突判断一致，回滚完整，report 完整")

        section("场景 8：切换配置后重跑 - 新增可导入，原有不被影响")

        new_books_snap = {
            "version": "2.0",
            "type": "full_snapshot",
            "books": [
                {"book_id": "NEW-B001", "title": "配置切换后新书1", "total_copies": 3, "borrow_days": 7, "retain_hours": 6},
                {"book_id": "NEW-B002", "title": "配置切换后新书2", "total_copies": 2, "borrow_days": 21, "retain_hours": 24},
            ],
            "active_reservations": [
                {
                    "reservation_id": "new-res-1",
                    "book_id": "NEW-B001",
                    "reader_id": "R-NEW-001",
                    "status": "waiting",
                    "created_at": "2026-06-20T08:00:00+00:00",
                    "available_at": None,
                    "expire_at": None,
                    "borrowed_at": None,
                    "returned_at": None,
                },
            ],
            "blacklist": [
                {"reader_id": "R-NEW-BL1", "reason": "新黑名单原因", "added_at": "2026-06-20T00:00:00+00:00"},
            ],
            "logs": [
                {"log_id": "new-log-1", "timestamp": "2026-06-20T07:00:00+00:00", "action": "add_book",
                 "book_id": "NEW-B001", "success": True},
                {"log_id": "new-log-2", "timestamp": "2026-06-20T08:00:00+00:00", "action": "reserve",
                 "book_id": "NEW-B001", "reader_id": "R-NEW-001", "success": True},
            ],
        }

        books_before_switch = get_book_count()
        orig_queue_b1 = len(get_active_reservations("TEST-B001"))
        orig_logs_b1 = len(get_logs_by_book("TEST-B001", limit=100))

        pre_switch_r, _ = api("POST", "/api/snapshot/precheck", new_books_snap)
        pre_switch_report = pre_switch_r["data"]
        assert_true(pre_switch_report["can_import"] is True, "配置切换新增书目预检通过")
        assert_true(pre_switch_report["summary"]["breakdown"]["books"]["will_add"] == 2,
                    "配置切换新增书目 will_add=2")
        assert_true(pre_switch_report["summary"]["total_conflicts"] == 0,
                    "配置切换新增书目 0 冲突")

        fp_before_switch = get_data_file_fingerprint()
        dry_switch_r, dry_switch_s = api("POST", "/api/snapshot/import?dry_run=true", new_books_snap)
        assert_true(dry_switch_s == 200, "配置切换 dry-run 通过")
        fp_after_switch = get_data_file_fingerprint()
        assert_data_files_unchanged(fp_before_switch, fp_after_switch, "配置切换 dry-run 后")

        imp_switch_r, imp_switch_s = api("POST", "/api/snapshot/import?dry_run=false", new_books_snap)
        assert_true(imp_switch_s == 200, "配置切换正式导入成功")
        assert_true("report" in imp_switch_r, "配置切换正式导入响应有 report")

        imp_switch_report = imp_switch_r["report"]
        assert_true(imp_switch_report["can_import"] is True, "配置切换导入 report.can_import=True")
        assert_true(imp_switch_report["dry_run"] is False, "配置切换导入 report.dry_run=False")

        books_after_switch = get_book_count()
        assert_true(books_after_switch == books_before_switch + 2,
                    f"配置切换后书目总数 = 原 {books_before_switch} + 新 2 = {books_before_switch + 2}")

        queue_after_b1 = len(get_active_reservations("TEST-B001"))
        assert_true(queue_after_b1 == orig_queue_b1,
                    f"配置切换后原有 TEST-B001 队列长度不变: {orig_queue_b1}")

        logs_after_b1 = len(get_logs_by_book("TEST-B001", limit=100))
        assert_true(logs_after_b1 == orig_logs_b1,
                    f"配置切换后原有 TEST-B001 日志条数不变: {orig_logs_b1}")

        new_b1_queue = get_active_reservations("NEW-B001")
        assert_true(len(new_b1_queue) == 1, "新增书目 NEW-B001 有 1 条预约")
        assert_true(new_b1_queue[0]["reader_id"] == "R-NEW-001",
                    "新增预约读者正确")

        print("  [配置切换重跑] 新增书目正常导入，原有数据不受影响，report 完整")

        section("场景 9：日志文件和关键状态变化核对")

        subsection("9.1 导入日志记录核对")

        all_logs = get_all_logs(limit=500)
        import_logs = [l for l in all_logs if l["action"] == "import_snapshot"]
        assert_true(len(import_logs) >= 3, f"至少 3 条 import_snapshot 日志（成功2次 + 新增1次），实际: {len(import_logs)}")

        for il in import_logs:
            assert_true(il.get("book_id") is None or not il.get("book_id"),
                        "import_snapshot 日志不带 book_id")
            assert_true(il.get("reader_id") is None or not il.get("reader_id"),
                        "import_snapshot 日志不带 reader_id")
            assert_true("detail" in il, "import_snapshot 日志有 detail 字段")

        print(f"  [导入日志] 共 {len(import_logs)} 条，均不带 book_id/reader_id，无串味")

        subsection("9.2 队列顺序核对")

        queue_b1 = get_active_reservations("TEST-B001")
        sorted_queue = sorted(queue_b1, key=lambda r: r["created_at"])
        reader_order = [r["reader_id"] for r in sorted_queue]
        expected_order = ["R-TEST-001", "R-TEST-002"]

        assert_true(reader_order == expected_order,
                    f"TEST-B001 队列顺序正确: {reader_order}")

        print(f"  [队列顺序] TEST-B001: {reader_order}（与源快照一致）")

        subsection("9.3 可借状态核对")

        avail_b1 = get_available_copies("TEST-B001")
        expected_avail_b1 = 3 - 1 - 0
        assert_true(avail_b1 == expected_avail_b1,
                    f"TEST-B001 可借副本正确: 总3 - 待取1 - 借出0 = {expected_avail_b1}，实际: {avail_b1}")

        avail_b2 = get_available_copies("TEST-B002")
        expected_avail_b2 = 0
        assert_true(avail_b2 == expected_avail_b2,
                    f"TEST-B002 可借副本正确: 总1 - 借出1 = 0，实际: {avail_b2}")

        print(f"  [可借状态] TEST-B001: {avail_b1} 本可借，TEST-B002: {avail_b2} 本可借")

        subsection("9.4 黑名单核对")

        bl = get_blacklist()
        bl_ids = {b["reader_id"] for b in bl}
        expected_bl_ids = {"R-TEST-BL1", "R-TEST-BL2", "R-NEW-BL1"}
        assert_true(bl_ids == expected_bl_ids,
                    f"黑名单集合正确: {bl_ids}")

        for b in bl:
            if b["reader_id"] == "R-TEST-BL1":
                assert_true(b["reason"] == "测试黑名单原因1",
                            f"R-TEST-BL1 原因正确: {b['reason']}")

        print(f"  [黑名单核对] 共 {len(bl)} 条，reader_id 和 reason 均正确")

        print("\n" + "=" * 60)
        print("  快照正式导入完整回归测试全部通过!")
        print("=" * 60)
        print("\n  覆盖的关键链路:")
        print("  1. 正式导入成功（200）→ 返回完整 report（summary + details）")
        print("  2. 正式导入冲突（409）→ 返回完整 report")
        print("  3. 正式导入格式错误（400）→ 返回完整 report")
        print("  4. 三方口径一致：预检 / dry-run / 正式导入 report 结构和统计相同")
        print("  5. 空目标环境首次导入 → report 与实际落库一致")
        print("  6. 混合有效无效日志 → report 明细完整，dry-run 不落库")
        print("  7. 服务重启后重复提交 → 冲突判断一致，回滚完整")
        print("  8. 切换配置后重跑 → 新增可导入，原有不被影响")
        print("  9. 日志文件核对 → import_snapshot 日志无串味")
        print("  10. 关键状态核对 → 队列顺序、可借状态、黑名单均正确")

    finally:
        stop_server(server_proc)

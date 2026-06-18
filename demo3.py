import json
import os
import signal
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
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
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
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
    print("  [INFO] 服务已停止")


def create_sample_import_data():
    return {
        "version": "1.0",
        "books": [
            {
                "book_id": "IMPORT-B001",
                "title": "Python编程从入门到实践",
                "total_copies": 5,
                "borrow_days": 30,
                "retain_hours": 24,
            },
            {
                "book_id": "IMPORT-B002",
                "title": "深入理解计算机系统",
                "total_copies": 3,
                "borrow_days": 14,
                "retain_hours": 12,
            },
            {
                "book_id": "IMPORT-B003",
                "title": "设计模式：可复用面向对象软件的基础",
                "total_copies": 2,
                "borrow_days": 21,
                "retain_hours": 6,
            },
        ]
    }


if __name__ == "__main__":
    clear_data()
    server_proc = start_server()

    try:
        section("场景 1：批量导出空馆藏 - 验证导出格式")

        exp, status = api("GET", "/api/collection/export")
        assert_true(status == 200 and exp["ok"], "批量导出接口 HTTP 200 且 ok=true")
        export_data = exp["data"]
        assert_true("export_time" in export_data, "导出数据包含 export_time")
        assert_true("version" in export_data, "导出数据包含 version")
        assert_true("total_books" in export_data, "导出数据包含 total_books")
        assert_true("books" in export_data, "导出数据包含 books 列表")
        assert_true(export_data["total_books"] == 0, "空馆藏 total_books=0")
        assert_true(isinstance(export_data["books"], list), "books 是列表类型")

        section("场景 2：DRY-RUN 导入校验 - 不实际写入数据")

        import_data = create_sample_import_data()

        dry_result, dry_status = api(
            "POST", "/api/collection/import?dry_run=true", import_data
        )
        assert_true(dry_status == 200, "DRY-RUN 导入返回 HTTP 200")
        assert_true(dry_result["ok"], "DRY-RUN 校验通过，ok=true")
        assert_true(dry_result["dry_run"] is True, "返回 dry_run=true")
        assert_true(dry_result["imported_count"] == 3, "DRY-RUN 显示可导入 3 本书")

        books_after_dry, _ = api("GET", "/api/books")
        assert_true(len(books_after_dry["data"]) == 0, "DRY-RUN 不实际写入，书仍为 0 本")

        logs_dry, _ = api("GET", "/api/logs?limit=100")
        dry_logs = [l for l in logs_dry["data"] if l["action"] == "import_collection_dry_run"]
        assert_true(len(dry_logs) > 0, "DRY-RUN 操作有日志记录")
        assert_true(dry_logs[0]["success"] is True, "DRY-RUN 成功日志记录")

        section("场景 3：正式批量导入 - 成功导入多本书")

        import_result, import_status = api(
            "POST", "/api/collection/import?dry_run=false", import_data
        )
        assert_true(import_status == 200, "正式导入返回 HTTP 200")
        assert_true(import_result["ok"], "正式导入 ok=true")
        assert_true(import_result["dry_run"] is False, "返回 dry_run=false")
        assert_true(import_result["imported_count"] == 3, "成功导入 3 本书")

        books_after_import, _ = api("GET", "/api/books")
        book_ids = {b["book_id"] for b in books_after_import["data"]}
        expected_ids = {"IMPORT-B001", "IMPORT-B002", "IMPORT-B003"}
        assert_true(book_ids == expected_ids, f"导入的 book_id 正确: {book_ids}")

        for book in books_after_import["data"]:
            expected = next(b for b in import_data["books"] if b["book_id"] == book["book_id"])
            assert_true(book["title"] == expected["title"], f"{book['book_id']} title 正确")
            assert_true(book["total_copies"] == expected["total_copies"], f"{book['book_id']} total_copies 正确")
            assert_true(book["borrow_days"] == expected["borrow_days"], f"{book['book_id']} borrow_days 正确")
            assert_true(book["retain_hours"] == expected["retain_hours"], f"{book['book_id']} retain_hours 正确")

        logs_after_import, _ = api("GET", "/api/logs?limit=100")
        import_logs = [l for l in logs_after_import["data"] if l["action"] == "import_collection"]
        assert_true(len(import_logs) > 0, "批量导入操作有日志记录")
        assert_true(import_logs[0]["success"] is True, "批量导入成功日志记录")

        for bid in expected_ids:
            book_logs, _ = api("GET", f"/api/logs?book_id={bid}&limit=10")
            import_book_logs = [l for l in book_logs["data"] if l["action"] == "import_book"]
            assert_true(len(import_book_logs) == 1, f"按 book_id={bid} 可查到单本书导入日志")

        section("场景 4：批量导出完整馆藏 - 验证统计和队列摘要")

        api("POST", "/api/reserve", {"book_id": "IMPORT-B001", "reader_id": "R-TEST-01"})
        api("POST", "/api/reserve", {"book_id": "IMPORT-B001", "reader_id": "R-TEST-02"})
        api("POST", "/api/reserve", {"book_id": "IMPORT-B002", "reader_id": "R-TEST-01"})

        exp_full, status = api("GET", "/api/collection/export")
        assert_true(status == 200 and exp_full["ok"], "完整馆藏导出成功")
        full_data = exp_full["data"]
        assert_true(full_data["total_books"] == 3, "total_books=3")

        books_sorted = sorted(full_data["books"], key=lambda b: b["book_id"])
        assert_true(books_sorted[0]["book_id"] == "IMPORT-B001", "导出按 book_id 排序，顺序稳定")

        for book_export in full_data["books"]:
            bid = book_export["book_id"]
            assert_true("stats" in book_export, f"{bid} 包含 stats 字段")
            assert_true("queue_summary" in book_export, f"{bid} 包含 queue_summary 字段")
            stats = book_export["stats"]
            assert_true("available_copies" in stats, f"{bid} stats 包含 available_copies")
            assert_true("to_pick_count" in stats, f"{bid} stats 包含 to_pick_count")
            assert_true("waiting_count" in stats, f"{bid} stats 包含 waiting_count")
            assert_true("borrowed_count" in stats, f"{bid} stats 包含 borrowed_count")

            qs = book_export["queue_summary"]
            assert_true("total_active" in qs, f"{bid} queue_summary 包含 total_active")
            assert_true("waiting" in qs, f"{bid} queue_summary 包含 waiting")
            assert_true("available" in qs, f"{bid} queue_summary 包含 available")
            assert_true("borrowed" in qs, f"{bid} queue_summary 包含 borrowed")

        b001_export = next(b for b in full_data["books"] if b["book_id"] == "IMPORT-B001")
        assert_true(b001_export["stats"]["to_pick_count"] == 2, "IMPORT-B001 待取数=2（5副本，2人预约都进入待取）")
        assert_true(b001_export["stats"]["waiting_count"] == 0, "IMPORT-B001 等待数=0（副本充足）")
        assert_true(len(b001_export["queue_summary"]["available"]) == 2, "queue_summary available 列表长度正确")
        assert_true(len(b001_export["queue_summary"]["waiting"]) == 0, "queue_summary waiting 列表长度正确")

        export_time_1 = full_data["export_time"]

        section("场景 5：冲突检测 - 重复 book_id（无活跃预约）")

        api("POST", "/api/books", {
            "book_id": "DUP-TEST-01",
            "title": "已存在无预约的书",
            "total_copies": 2,
            "borrow_days": 7,
            "retain_hours": 1,
        })

        conflict_data_dup = {
            "books": [
                {
                    "book_id": "DUP-TEST-01",
                    "title": "冲突书-重复ID",
                    "total_copies": 1,
                    "borrow_days": 7,
                    "retain_hours": 1,
                },
                {
                    "book_id": "IMPORT-BNEW",
                    "title": "新书",
                    "total_copies": 2,
                    "borrow_days": 14,
                    "retain_hours": 2,
                },
            ]
        }

        dup_result, dup_status = api(
            "POST", "/api/collection/import?dry_run=false", conflict_data_dup
        )
        assert_true(dup_status == 409, "重复 book_id 返回 HTTP 409")
        assert_true(not dup_result["ok"], "重复 book_id 导入失败，ok=false")
        assert_true("conflicts" in dup_result, "返回 conflicts 列表")
        assert_true(len(dup_result["conflicts"]) == 1, "检测到 1 个冲突")
        assert_true(dup_result["conflicts"][0]["type"] == "duplicate_book_id", "冲突类型为 duplicate_book_id")
        assert_true(dup_result["conflicts"][0]["book_id"] == "DUP-TEST-01", "冲突 book_id 正确")
        assert_true("existing_config" in dup_result["conflicts"][0], "冲突包含 existing_config")
        assert_true("import_config" in dup_result["conflicts"][0], "冲突包含 import_config")

        books_after_dup, _ = api("GET", "/api/books")
        assert_true(len(books_after_dup["data"]) == 4, "冲突时回滚，书仍为 4 本，IMPORT-BNEW 未写入")

        section("场景 6：冲突检测 - 非法数值返回 conflicts 明细（409 而非 400）")

        conflict_data_copies = {
            "books": [
                {
                    "book_id": "IMPORT-BAD-01",
                    "title": "非法副本数",
                    "total_copies": 0,
                    "borrow_days": 7,
                    "retain_hours": 1,
                },
                {
                    "book_id": "IMPORT-BAD-02",
                    "title": "负副本数",
                    "total_copies": -5,
                    "borrow_days": 7,
                    "retain_hours": 1,
                },
                {
                    "book_id": "IMPORT-BAD-03",
                    "title": "非法借期",
                    "total_copies": 3,
                    "borrow_days": 0,
                    "retain_hours": 1,
                },
                {
                    "book_id": "IMPORT-BAD-04",
                    "title": "负保留时长",
                    "total_copies": 3,
                    "borrow_days": 7,
                    "retain_hours": -1,
                },
            ]
        }

        copies_result, copies_status = api(
            "POST", "/api/collection/import?dry_run=true", conflict_data_copies
        )
        assert_true(copies_status == 409, "非法数值返回 HTTP 409（冲突）而非 400")
        assert_true(not copies_result["ok"], "非法数值导入失败，ok=false")
        assert_true("conflicts" in copies_result, "返回 conflicts 列表")
        assert_true(len(copies_result["conflicts"]) == 4, f"检测到 4 个冲突，实际 {len(copies_result['conflicts'])}")

        conflict_types = {c["type"] for c in copies_result["conflicts"]}
        assert_true("invalid_copies" in conflict_types, "包含 invalid_copies 冲突类型")
        assert_true("invalid_borrow_days" in conflict_types, "包含 invalid_borrow_days 冲突类型")
        assert_true("invalid_retain_hours" in conflict_types, "包含 invalid_retain_hours 冲突类型")

        for c in copies_result["conflicts"]:
            assert_true("book_id" in c, "冲突包含 book_id")
            assert_true("index" in c, "冲突包含 index")
            assert_true("message" in c, "冲突包含 message")
            assert_true(c["type"] in ["invalid_copies", "invalid_borrow_days", "invalid_retain_hours"],
                       f"冲突类型正确，实际: {c['type']}")

        books_after_dry_bad, _ = api("GET", "/api/books")
        assert_true(len(books_after_dry_bad["data"]) == 4,
                   f"DRY-RUN 非法数值时不落库，书仍为 4 本，实际 {len(books_after_dry_bad['data'])}")

        section("场景 7：冲突检测 - 已有活跃预约的书目不能覆盖")

        conflict_data_active = {
            "books": [
                {
                    "book_id": "IMPORT-B001",
                    "title": "试图覆盖有活跃预约的书",
                    "total_copies": 10,
                    "borrow_days": 7,
                    "retain_hours": 1,
                },
            ]
        }

        active_result, active_status = api(
            "POST", "/api/collection/import?dry_run=false", conflict_data_active
        )
        assert_true(active_status == 409, "有活跃预约时返回 HTTP 409")
        assert_true(not active_result["ok"], "有活跃预约时导入失败")
        assert_true(len(active_result["conflicts"]) == 1, "检测到 1 个冲突")
        assert_true(
            active_result["conflicts"][0]["type"] == "has_active_reservations",
            f"冲突类型为 has_active_reservations，实际: {active_result['conflicts'][0]['type']}"
        )
        assert_true(
            "活跃预约" in active_result["conflicts"][0]["message"],
            f"错误信息包含'活跃预约'，实际: {active_result['conflicts'][0]['message']}"
        )

        section("场景 8：冲突检测 - 导入文件内部重复 book_id")

        conflict_data_internal = {
            "books": [
                {
                    "book_id": "IMPORT-DUP-IN-01",
                    "title": "重复1",
                    "total_copies": 1,
                    "borrow_days": 7,
                    "retain_hours": 1,
                },
                {
                    "book_id": "IMPORT-DUP-IN-01",
                    "title": "重复2",
                    "total_copies": 2,
                    "borrow_days": 14,
                    "retain_hours": 2,
                },
            ]
        }

        internal_result, internal_status = api(
            "POST", "/api/collection/import?dry_run=false", conflict_data_internal
        )
        assert_true(internal_status == 409, "内部重复返回 HTTP 409")
        assert_true(len(internal_result["conflicts"]) >= 1, "检测到内部重复冲突")
        conflict_types = {c["type"] for c in internal_result["conflicts"]}
        assert_true("duplicate_in_import" in conflict_types, "冲突类型包含 duplicate_in_import")

        books_after_internal, _ = api("GET", "/api/books")
        assert_true(len(books_after_internal["data"]) == 4, "内部重复时回滚，书仍为 4 本")

        section("场景 9：服务重启后导入的配置仍然存在")

        books_before_restart, _ = api("GET", "/api/books")
        all_book_ids_before = {b["book_id"] for b in books_before_restart["data"]}
        book_configs_before = {b["book_id"]: b for b in books_before_restart["data"]}

        stop_server(server_proc)
        time.sleep(1)
        server_proc = start_server()

        books_after_restart, _ = api("GET", "/api/books")
        all_book_ids_after = {b["book_id"] for b in books_after_restart["data"]}
        assert_true(
            all_book_ids_before == all_book_ids_after,
            f"重启后所有书目仍然存在：重启前 {all_book_ids_before}，重启后 {all_book_ids_after}"
        )

        for bid in all_book_ids_before:
            book_after = next(b for b in books_after_restart["data"] if b["book_id"] == bid)
            book_before = book_configs_before[bid]
            assert_true(book_after["title"] == book_before["title"], f"重启后 {bid} title 一致")
            assert_true(book_after["total_copies"] == book_before["total_copies"], f"重启后 {bid} total_copies 一致")
            assert_true(book_after["borrow_days"] == book_before["borrow_days"], f"重启后 {bid} borrow_days 一致")
            assert_true(book_after["retain_hours"] == book_before["retain_hours"], f"重启后 {bid} retain_hours 一致")

        exp_after_restart, _ = api("GET", "/api/collection/export")
        assert_true(exp_after_restart["ok"], "重启后批量导出正常")
        assert_true(exp_after_restart["data"]["total_books"] == 4, "重启后导出 total_books=4")

        section("场景 10：日志一致性 - 导入操作日志可按 book_id 查询")

        for bid in ["IMPORT-B001", "IMPORT-B002", "IMPORT-B003"]:
            logs_by_book, _ = api("GET", f"/api/logs?book_id={bid}&limit=50")
            actions = {l["action"] for l in logs_by_book["data"]}
            assert_true("import_book" in actions, f"按 book_id={bid} 可查到 import_book 日志")

        all_logs, _ = api("GET", "/api/logs?limit=1000")
        collection_logs = [l for l in all_logs["data"] if l["action"] == "import_collection"]
        success_imports = [l for l in collection_logs if l["success"]]
        failed_imports = [l for l in collection_logs if not l["success"]]
        assert_true(len(success_imports) >= 1, "有成功的批量导入日志")
        assert_true(len(failed_imports) >= 1, "有失败的批量导入日志（冲突场景）")

        dry_run_logs = [l for l in all_logs["data"] if l["action"] == "import_collection_dry_run"]
        assert_true(len(dry_run_logs) >= 1, "有 DRY-RUN 操作日志")

        section("场景 11：导出 JSON 稳定性 - 多次导出顺序一致")

        exp1, _ = api("GET", "/api/collection/export")
        time.sleep(0.1)
        exp2, _ = api("GET", "/api/collection/export")

        ids1 = [b["book_id"] for b in exp1["data"]["books"]]
        ids2 = [b["book_id"] for b in exp2["data"]["books"]]
        assert_true(ids1 == ids2, "多次导出的 book_id 顺序一致，JSON 输出稳定")

        for b1, b2 in zip(exp1["data"]["books"], exp2["data"]["books"]):
            for key in ["book_id", "title", "total_copies", "borrow_days", "retain_hours"]:
                assert_true(b1[key] == b2[key], f"多次导出的 {key} 一致")

        section("场景 12：DRY-RUN 与正式导入结果一致")

        new_import_data = {
            "books": [
                {
                    "book_id": "IMPORT-B004",
                    "title": "测试新书1",
                    "total_copies": 3,
                    "borrow_days": 7,
                    "retain_hours": 2,
                },
                {
                    "book_id": "IMPORT-B005",
                    "title": "测试新书2",
                    "total_copies": 5,
                    "borrow_days": 30,
                    "retain_hours": 24,
                },
            ]
        }

        dry2, _ = api("POST", "/api/collection/import?dry_run=true", new_import_data)
        assert_true(dry2["ok"] and dry2["imported_count"] == 2, "DRY-RUN 校验通过")

        real2, _ = api("POST", "/api/collection/import?dry_run=false", new_import_data)
        assert_true(real2["ok"] and real2["imported_count"] == 2, "正式导入成功，数量与 DRY-RUN 一致")

        books_final, _ = api("GET", "/api/books")
        assert_true(len(books_final["data"]) == 6, "最终馆藏共 6 本书（4本已有 + 2本新导入）")

        section("场景 13：导入数据格式校验 - 错误格式快速失败")

        bad_format_1 = "not a json object"
        bad_result_1, bad_status_1 = api("POST", "/api/collection/import", bad_format_1)
        assert_true(bad_status_1 == 400, "非对象格式返回 400")

        bad_format_2 = {"wrong_key": []}
        bad_result_2, bad_status_2 = api("POST", "/api/collection/import", bad_format_2)
        assert_true(bad_status_2 == 400, "缺少 books 字段返回 400")

        bad_format_3 = {"books": "not a list"}
        bad_result_3, bad_status_3 = api("POST", "/api/collection/import", bad_format_3)
        assert_true(bad_status_3 == 400, "books 非列表返回 400")

        bad_format_4 = {"books": []}
        bad_result_4, bad_status_4 = api("POST", "/api/collection/import", bad_format_4)
        assert_true(bad_status_4 == 400, "books 为空列表返回 400")

        print("\n" + "=" * 60)
        print("  所有批量导入导出测试全部通过!")
        print("=" * 60)

    finally:
        stop_server(server_proc)

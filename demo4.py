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


def get_book_count():
    r, _ = api("GET", "/api/books")
    return len(r["data"])


def get_logs_by_book(book_id):
    r, _ = api("GET", f"/api/logs?book_id={book_id}&limit=100")
    return r["data"]


if __name__ == "__main__":
    clear_data()
    server_proc = start_server()

    try:
        section("前置准备：创建一批合法书目作为基线数据")

        valid_import_data = {
            "books": [
                {"book_id": "BASE-B001", "title": "基线书目1", "total_copies": 5, "borrow_days": 30, "retain_hours": 24},
                {"book_id": "BASE-B002", "title": "基线书目2", "total_copies": 3, "borrow_days": 14, "retain_hours": 12},
                {"book_id": "BASE-B003", "title": "基线书目3", "total_copies": 2, "borrow_days": 21, "retain_hours": 6},
            ]
        }

        result, status = api("POST", "/api/collection/import?dry_run=false", valid_import_data)
        assert_true(status == 200 and result["ok"], "基线数据导入成功")
        assert_true(result["imported_count"] == 3, "成功导入 3 本基线书目")
        assert_true(get_book_count() == 3, "当前共 3 本书")

        baseline_books_before, _ = api("GET", "/api/books")
        baseline_book_ids_before = {b["book_id"] for b in baseline_books_before["data"]}

        logs_baseline_before = {}
        for bid in baseline_book_ids_before:
            logs_baseline_before[bid] = get_logs_by_book(bid)
            assert_true(len(logs_baseline_before[bid]) > 0, f"基线书目 {bid} 有导入日志")

        section("场景 1：DRY-RUN 遇到非法数值，返回 conflicts 明细且不落库")

        bad_import_data = {
            "books": [
                {"book_id": "NEW-GOOD-01", "title": "合法新书", "total_copies": 5, "borrow_days": 30, "retain_hours": 24},
                {"book_id": "NEW-BAD-01", "title": "非法副本数=0", "total_copies": 0, "borrow_days": 30, "retain_hours": 24},
                {"book_id": "NEW-BAD-02", "title": "非法副本数=-5", "total_copies": -5, "borrow_days": 30, "retain_hours": 24},
                {"book_id": "NEW-GOOD-02", "title": "合法新书2", "total_copies": 3, "borrow_days": 14, "retain_hours": 12},
                {"book_id": "NEW-BAD-03", "title": "非法借期=0", "total_copies": 3, "borrow_days": 0, "retain_hours": 12},
                {"book_id": "NEW-BAD-04", "title": "非法保留时长=-1", "total_copies": 3, "borrow_days": 14, "retain_hours": -1},
            ]
        }

        dry_result, dry_status = api(
            "POST", "/api/collection/import?dry_run=true", bad_import_data
        )

        assert_true(dry_status == 409, "DRY-RUN 返回 HTTP 409（冲突）")
        assert_true(not dry_result["ok"], "DRY-RUN ok=false")
        assert_true(dry_result["dry_run"] is True, "dry_run=true")
        assert_true("conflicts" in dry_result, "返回 conflicts 列表")
        assert_true(len(dry_result["conflicts"]) == 4,
                    f"检测到 4 个冲突（2个invalid_copies + 1个invalid_borrow_days + 1个invalid_retain_hours），实际 {len(dry_result['conflicts'])}")

        conflict_details = {}
        for c in dry_result["conflicts"]:
            conflict_details[c["book_id"]] = c
            assert_true("type" in c, "冲突包含 type 字段")
            assert_true("book_id" in c, "冲突包含 book_id 字段")
            assert_true("index" in c, "冲突包含 index 字段")
            assert_true("message" in c, "冲突包含 message 字段")
            print(f"    [冲突] {c['book_id']}: {c['type']} - {c['message']}")

        assert_true(conflict_details["NEW-BAD-01"]["type"] == "invalid_copies",
                   f"NEW-BAD-01 冲突类型正确，实际: {conflict_details['NEW-BAD-01']['type']}")
        assert_true(conflict_details["NEW-BAD-02"]["type"] == "invalid_copies",
                   f"NEW-BAD-02 冲突类型正确，实际: {conflict_details['NEW-BAD-02']['type']}")
        assert_true(conflict_details["NEW-BAD-03"]["type"] == "invalid_borrow_days",
                   f"NEW-BAD-03 冲突类型正确，实际: {conflict_details['NEW-BAD-03']['type']}")
        assert_true(conflict_details["NEW-BAD-04"]["type"] == "invalid_retain_hours",
                   f"NEW-BAD-04 冲突类型正确，实际: {conflict_details['NEW-BAD-04']['type']}")

        assert_true(get_book_count() == 3,
                   f"DRY-RUN 不落库，书目数量仍为 3，实际 {get_book_count()}")
        for bid in ["NEW-GOOD-01", "NEW-GOOD-02", "NEW-BAD-01", "NEW-BAD-02", "NEW-BAD-03", "NEW-BAD-04"]:
            book, _ = api("GET", f"/api/books/{bid}")
            assert_true(not book["ok"], f"DRY-RUN 后 {bid} 不存在")

        section("场景 2：正式导入遇到非法数值，整批回滚，不写半条数据")

        book_count_before = get_book_count()
        assert_true(book_count_before == 3, "导入前共 3 本书")

        real_result, real_status = api(
            "POST", "/api/collection/import?dry_run=false", bad_import_data
        )

        assert_true(real_status == 409, "正式导入返回 HTTP 409（冲突）")
        assert_true(not real_result["ok"], "正式导入 ok=false")
        assert_true(real_result["dry_run"] is False, "dry_run=false")
        assert_true("conflicts" in real_result, "返回 conflicts 列表")
        assert_true(len(real_result["conflicts"]) == 4,
                    f"检测到 4 个冲突，实际 {len(real_result['conflicts'])}")

        real_conflict_details = {c["book_id"]: c for c in real_result["conflicts"]}
        for bid in ["NEW-BAD-01", "NEW-BAD-02", "NEW-BAD-03", "NEW-BAD-04"]:
            assert_true(bid in real_conflict_details, f"冲突列表包含 {bid}")
            print(f"    [冲突] {bid}: {real_conflict_details[bid]['type']} - {real_conflict_details[bid]['message']}")

        assert_true(get_book_count() == 3,
                   f"整批回滚，书目数量仍为 3，实际 {get_book_count()}")
        for bid in ["NEW-GOOD-01", "NEW-GOOD-02"]:
            book, _ = api("GET", f"/api/books/{bid}")
            assert_true(not book["ok"], f"回滚后合法书 {bid} 也不应存在（原子性保证）")

        section("场景 3：验证已有分支（duplicate_book_id、has_active_reservations）未被破坏")

        api("POST", "/api/reserve", {"book_id": "BASE-B001", "reader_id": "R-TEST-001"})

        conflict_dup = {
            "books": [
                {"book_id": "BASE-B002", "title": "重复ID", "total_copies": 10, "borrow_days": 7, "retain_hours": 1},
            ]
        }
        r1, s1 = api("POST", "/api/collection/import?dry_run=false", conflict_dup)
        assert_true(s1 == 409, "重复 book_id 返回 409")
        assert_true(r1["conflicts"][0]["type"] == "duplicate_book_id",
                   f"冲突类型为 duplicate_book_id，实际: {r1['conflicts'][0]['type']}")

        conflict_active = {
            "books": [
                {"book_id": "BASE-B001", "title": "有活跃预约", "total_copies": 10, "borrow_days": 7, "retain_hours": 1},
            ]
        }
        r2, s2 = api("POST", "/api/collection/import?dry_run=false", conflict_active)
        assert_true(s2 == 409, "有活跃预约返回 409")
        assert_true(r2["conflicts"][0]["type"] == "has_active_reservations",
                   f"冲突类型为 has_active_reservations，实际: {r2['conflicts'][0]['type']}")

        assert_true(get_book_count() == 3, "冲突后书目数量仍为 3")

        section("场景 4：服务重启后，已有数据和日志保持不变")

        books_before_restart, _ = api("GET", "/api/books")
        book_ids_before = {b["book_id"] for b in books_before_restart["data"]}

        logs_before_restart = {}
        for bid in book_ids_before:
            logs_before_restart[bid] = get_logs_by_book(bid)

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
            logs_after = get_logs_by_book(bid)
            log_ids_before = {l["log_id"] for l in logs_before_restart[bid]}
            log_ids_after = {l["log_id"] for l in logs_after}
            assert_true(log_ids_before.issubset(log_ids_after),
                       f"重启后 {bid} 的日志完整保留")

            import_logs = [l for l in logs_after if l["action"] == "import_book"]
            assert_true(len(import_logs) >= 1, f"按 book_id={bid} 可查到 import_book 日志")

        section("场景 5：调用方确实能拿到可消费的冲突明细")

        mixed_conflict_data = {
            "books": [
                {"book_id": "BASE-B002", "title": "重复ID无预约", "total_copies": 10, "borrow_days": 7, "retain_hours": 1},
                {"book_id": "BASE-B001", "title": "重复ID有预约", "total_copies": 10, "borrow_days": 7, "retain_hours": 1},
                {"book_id": "MIX-BAD-01", "title": "非法副本", "total_copies": 0, "borrow_days": 7, "retain_hours": 1},
                {"book_id": "MIX-BAD-02", "title": "非法借期", "total_copies": 5, "borrow_days": -3, "retain_hours": 1},
            ]
        }

        mix_result, mix_status = api(
            "POST", "/api/collection/import?dry_run=true", mixed_conflict_data
        )

        assert_true(mix_status == 409, "混合冲突返回 409")
        assert_true(len(mix_result["conflicts"]) == 4, f"返回 4 个冲突，实际 {len(mix_result['conflicts'])}")

        print("\n  [调用方可用的冲突明细示例]")
        print("  " + "-" * 58)
        for c in mix_result["conflicts"]:
            print(f"  book_id: {c['book_id']:20s} type: {c['type']:30s} index: {c['index']}")
            print(f"    message: {c['message']}")
            if "existing_config" in c:
                print(f"    existing: {c['existing_config']}")
            if "import_config" in c:
                print(f"    import:   {c['import_config']}")
        print("  " + "-" * 58)

        conflict_by_type = {}
        for c in mix_result["conflicts"]:
            conflict_by_type.setdefault(c["type"], []).append(c)

        assert_true("duplicate_book_id" in conflict_by_type, "包含 duplicate_book_id 冲突")
        assert_true("has_active_reservations" in conflict_by_type, "包含 has_active_reservations 冲突")
        assert_true("invalid_copies" in conflict_by_type, "包含 invalid_copies 冲突")
        assert_true("invalid_borrow_days" in conflict_by_type, "包含 invalid_borrow_days 冲突")

        dup_conflict = conflict_by_type["duplicate_book_id"][0]
        assert_true(dup_conflict["book_id"] == "BASE-B002", "duplicate_book_id 冲突对应 BASE-B002（无活跃预约）")
        assert_true("existing_config" in dup_conflict, "duplicate_book_id 冲突包含 existing_config")
        assert_true("import_config" in dup_conflict, "duplicate_book_id 冲突包含 import_config")
        assert_true(dup_conflict["existing_config"]["title"] == "基线书目2", "existing_config 内容正确")
        assert_true(dup_conflict["import_config"]["title"] == "重复ID无预约", "import_config 内容正确")

        active_conflict = conflict_by_type["has_active_reservations"][0]
        assert_true(active_conflict["book_id"] == "BASE-B001", "has_active_reservations 冲突对应 BASE-B001（有活跃预约）")
        assert_true("existing_config" in active_conflict, "has_active_reservations 冲突包含 existing_config")
        assert_true("import_config" in active_conflict, "has_active_reservations 冲突包含 import_config")

        print("\n  [冲突明细可消费性验证通过]")
        print("  - 调用方可按 type 分类处理不同冲突")
        print("  - 调用方可按 book_id 定位具体哪本书")
        print("  - 调用方可按 index 定位导入文件中的位置")
        print("  - duplicate_book_id 冲突包含新旧配置对比")
        print("  - 所有冲突都有人类可读的 message")

        section("场景 6：类型错误仍然返回 400（区分类型错误和数值错误）")

        type_error_data = {
            "books": [
                {"book_id": "TYPE-ERR-01", "title": "字符串副本数", "total_copies": "5", "borrow_days": 30, "retain_hours": 24},
            ]
        }

        type_result, type_status = api(
            "POST", "/api/collection/import?dry_run=false", type_error_data
        )

        assert_true(type_status == 400, "类型错误返回 HTTP 400")
        assert_true(not type_result["ok"], "类型错误 ok=false")
        assert_true("error" in type_result, "返回 error 列表")
        assert_true(isinstance(type_result["error"], list), "error 是列表")
        assert_true(any("total_copies" in e and "整数" in e for e in type_result["error"]),
                   "错误信息包含类型检查提示")

        print("\n" + "=" * 60)
        print("  非法数值冲突回归测试全部通过!")
        print("=" * 60)
        print("\n  修复要点总结:")
        print("  1. _validate_book_config 只做类型检查，不做数值范围检查")
        print("  2. total_copies <= 0, borrow_days <= 0, retain_hours < 0 统一走 conflicts 分支")
        print("  3. 所有数值非法都返回 409 + 结构化 conflicts 明细")
        print("  4. 冲突时整批回滚，不写半条数据")
        print("  5. duplicate_book_id、has_active_reservations 分支不受影响")
        print("  6. 重启后数据和日志完整保留")

    finally:
        stop_server(server_proc)

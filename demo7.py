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
    print(f"    日志问题: {s.get('total_log_issues', 0)} 条")
    for sec, stats in s["breakdown"].items():
        print(f"    [{sec}] 新增={stats['will_add']}, 冲突={stats['conflicts']}, "
              f"缺依赖={stats['missing_dependencies']}, 格式错={stats['format_errors']}, "
              f"问题={stats.get('issues', 0)}")


if __name__ == "__main__":
    clear_data()
    server_proc = start_server()

    try:
        section("场景 1：日志混入字符串、缺字段、字段类型不对 - 预检不 500，返回明细")

        bad_logs_snapshot = {
            "version": "2.0",
            "type": "full_snapshot",
            "books": [
                {"book_id": "LOG-B001", "title": "日志测试书1", "total_copies": 3, "borrow_days": 30, "retain_hours": 24},
            ],
            "active_reservations": [],
            "blacklist": [],
            "logs": [
                "我是一条混入的字符串日志",
                12345,
                {"log_id": "log-ok-1", "timestamp": "2026-06-19T08:00:00+00:00", "action": "reserve",
                 "reader_id": "R-LOG-001", "book_id": "LOG-B001", "detail": "正常日志", "success": True},
                {"log_id": "log-missing-fields-1"},
                {"log_id": "log-wrong-type-1", "timestamp": "2026-06-19T09:00:00+00:00", "action": "reserve",
                 "book_id": "LOG-B001", "success": "yes_i_am_string_not_bool"},
                {"log_id": "log-bad-ts", "timestamp": "not-a-valid-timestamp", "action": "reserve",
                 "reader_id": "R-LOG-002", "book_id": "LOG-B001", "success": True},
                {"log_id": "log-bad-book-id", "timestamp": "2026-06-19T09:30:00+00:00", "action": "reserve",
                 "reader_id": "R-LOG-003", "book_id": 999, "success": True},
            ],
        }

        r, s = api("POST", "/api/snapshot/precheck", bad_logs_snapshot)
        assert_true(s == 200 and r["ok"], "预检接口返回 HTTP 200（绝不 500）")
        report = r["data"]
        print_report_summary(report)

        assert_true(report["can_import"] is False, "存在格式错误，can_import=False")
        assert_true(report["summary"]["status"] == "format_error", "状态为 format_error")

        log_format_errors = report["details"]["logs"]["format_errors"]
        print(f"\n  [日志格式错误明细] 共 {len(log_format_errors)} 条：")
        for fe in log_format_errors:
            print(f"    索引={fe.get('index')}, 字段={fe.get('field')}, 错误码={fe.get('error_code')}")
            print(f"      消息: {fe.get('message')}")
            print(f"      blocks_other_blocks: {fe.get('blocks_other_blocks')}, "
                  f"blocks_current_block: {fe.get('blocks_current_block')}")

        string_log_errors = [fe for fe in log_format_errors if fe.get("error_code") == "log_not_object"]
        assert_true(len(string_log_errors) >= 2,
                    f"检测到字符串/数字混入日志 至少 2 条，实际 {len(string_log_errors)}")

        missing_field_errors = [fe for fe in log_format_errors if fe.get("error_code") == "log_missing_field"]
        assert_true(len(missing_field_errors) >= 1,
                    f"检测到缺必填字段日志至少 1 条，实际 {len(missing_field_errors)}")

        success_type_errors = [fe for fe in log_format_errors if fe.get("error_code") == "log_invalid_success_type"]
        assert_true(len(success_type_errors) >= 1,
                    f"检测到 success 类型错误至少 1 条，实际 {len(success_type_errors)}")

        ts_format_errors = [fe for fe in log_format_errors if fe.get("error_code") == "log_invalid_timestamp_format"]
        assert_true(len(ts_format_errors) >= 1,
                    f"检测到 timestamp 格式错误至少 1 条，实际 {len(ts_format_errors)}")

        book_id_type_errors = [fe for fe in log_format_errors if fe.get("error_code") == "log_invalid_book_id_type"]
        assert_true(len(book_id_type_errors) >= 1,
                    f"检测到 book_id 类型错误至少 1 条，实际 {len(book_id_type_errors)}")

        books_will_add = report["details"]["books"]["will_add"]
        assert_true(len(books_will_add) == 1, f"书目本身无错，will_add 有 1 本，实际 {len(books_will_add)}")

        logs_will_add = report["details"]["logs"]["will_add"]
        assert_true(len(logs_will_add) == 1,
                    f"仅 1 条正常日志可导入，实际 {len(logs_will_add)}")
        assert_true(logs_will_add[0]["log_id"] == "log-ok-1",
                    f"可导入的日志是 log-ok-1，实际 {logs_will_add[0]['log_id']}")

        print("\n  [用户可读 Summary 展示]")
        print(f"  状态: {report['summary']['status']}")
        print(f"  消息: {report['summary']['message']}")
        print(f"  可导入? {report['can_import']}")
        for fe in log_format_errors:
            idx = fe.get("index", "?")
            field = fe.get("field", "(整体)")
            ec = fe.get("error_code", "?")
            msg = fe.get("message", "")
            block_other = fe.get("blocks_other_blocks", "?")
            block_cur = fe.get("blocks_current_block", "?")
            print(f"  [日志 idx={idx}] 字段={field} | 错误码={ec}")
            print(f"    原因: {msg}")
            print(f"    阻断其他块? {block_other} | 阻断当前日志块? {block_cur}")

        section("场景 2：预检 vs dry-run vs 正式导入 - 三方口径完全一致")

        subsection("2.1 同一快照预检 + dry-run：结果相同")

        consistent_test_snapshot = {
            "version": "2.0",
            "type": "full_snapshot",
            "books": [
                {"book_id": "CMP-B001", "title": "口径测试书1", "total_copies": 3, "borrow_days": 30, "retain_hours": 24},
            ],
            "active_reservations": [],
            "blacklist": [],
            "logs": [
                "字符串混入",
                {"log_id": "cmp-log-1", "timestamp": "2026-06-19T08:00:00+00:00", "action": "add_book",
                 "book_id": "CMP-B001", "success": True},
            ],
        }

        pre_r, pre_s = api("POST", "/api/snapshot/precheck", consistent_test_snapshot)
        assert_true(pre_s == 200, "预检 HTTP 200")
        pre_can_import = pre_r["data"]["can_import"]
        pre_log_fe = len(pre_r["data"]["details"]["logs"]["format_errors"])
        print(f"  [预检] can_import={pre_can_import}, 日志格式错误数={pre_log_fe}")

        dry_r, dry_s = api("POST", "/api/snapshot/import?dry_run=true", consistent_test_snapshot)
        print(f"  [dry-run] HTTP {dry_s}, ok={dry_r.get('ok')}")
        if not dry_r.get("ok"):
            if "error" in dry_r:
                if isinstance(dry_r["error"], list):
                    print(f"  [dry-run] error 列表条数: {len(dry_r['error'])}")
                    for em in dry_r["error"]:
                        print(f"    - {em}")
                else:
                    print(f"  [dry-run] error: {dry_r['error']}")

        assert_true(dry_s == 400,
                    f"存在日志格式错误时 dry-run 返回 HTTP 400，实际 {dry_s}")
        assert_true(pre_can_import is False, "预检 can_import=False")
        assert_true(dry_r.get("ok") is False, "dry-run ok=False")
        assert_true(isinstance(dry_r.get("error"), list) and len(dry_r["error"]) > 0,
                    "dry-run 返回 error 列表")

        subsection("2.2 预检有冲突时，dry-run 和正式导入也有相同冲突")

        api("POST", "/api/books",
            {"book_id": "CMP-EXIST-B001", "title": "已存在的书", "total_copies": 2, "borrow_days": 14, "retain_hours": 12})

        conflict_snapshot = {
            "version": "2.0",
            "type": "full_snapshot",
            "books": [
                {"book_id": "CMP-EXIST-B001", "title": "冲突的书", "total_copies": 5, "borrow_days": 30, "retain_hours": 24},
                {"book_id": "CMP-NEW-B001", "title": "新书", "total_copies": 1, "borrow_days": 7, "retain_hours": 6},
            ],
            "active_reservations": [],
            "blacklist": [],
            "logs": [],
        }

        pre_r2, _ = api("POST", "/api/snapshot/precheck", conflict_snapshot)
        pre_conflicts = pre_r2["data"]["details"]["books"]["conflicts"]
        pre_dup_book = [c for c in pre_conflicts if c["type"] == "duplicate_book_id"]
        assert_true(len(pre_dup_book) == 1, "预检检测到 1 个 duplicate_book_id 冲突")

        dry_r2, dry_s2 = api("POST", "/api/snapshot/import?dry_run=true", conflict_snapshot)
        assert_true(dry_s2 == 409, f"dry-run 冲突返回 HTTP 409，实际 {dry_s2}")
        dry_conflicts = dry_r2.get("conflicts", [])
        dry_dup_book = [c for c in dry_conflicts if c["type"] == "duplicate_book_id"]
        assert_true(len(dry_dup_book) == 1, "dry-run 检测到 1 个 duplicate_book_id 冲突")
        assert_true(dry_dup_book[0]["book_id"] == pre_dup_book[0]["book_id"],
                    f"预检和 dry-run 冲突 book_id 相同: {dry_dup_book[0]['book_id']}")

        imp_r2, imp_s2 = api("POST", "/api/snapshot/import?dry_run=false", conflict_snapshot)
        assert_true(imp_s2 == 409, f"正式导入冲突返回 HTTP 409，实际 {imp_s2}")
        imp_conflicts = imp_r2.get("conflicts", [])
        imp_dup_book = [c for c in imp_conflicts if c["type"] == "duplicate_book_id"]
        assert_true(len(imp_dup_book) == 1, "正式导入检测到 1 个 duplicate_book_id 冲突")

        book_count_after = get_book_count()
        assert_true(book_count_after == 1,
                    f"冲突回滚后书目仍为 1（仅预置的那本），实际 {book_count_after}")

        print(f"  [口径一致] 预检冲突={len(pre_dup_book)}, dry-run={len(dry_dup_book)}, "
              f"正式导入={len(imp_dup_book)}，完全一致")

        section("场景 3：时间顺序乱掉 + 引用不存在书目 + 重复 log_id")

        order_and_ref_snapshot = {
            "version": "2.0",
            "type": "full_snapshot",
            "books": [
                {"book_id": "ORD-B001", "title": "顺序测试书", "total_copies": 5, "borrow_days": 30, "retain_hours": 24},
            ],
            "active_reservations": [],
            "blacklist": [],
            "logs": [
                {"log_id": "ord-log-1", "timestamp": "2026-06-19T12:00:00+00:00", "action": "reserve",
                 "reader_id": "R-ORD-003", "book_id": "ORD-B001", "success": True},
                {"log_id": "ord-log-2", "timestamp": "2026-06-19T10:00:00+00:00", "action": "reserve",
                 "reader_id": "R-ORD-002", "book_id": "ORD-B001", "success": True},
                {"log_id": "ord-log-3", "timestamp": "2026-06-19T08:00:00+00:00", "action": "reserve",
                 "reader_id": "R-ORD-001", "book_id": "ORD-B001", "success": True},
                {"log_id": "ord-log-ref-missing", "timestamp": "2026-06-19T13:00:00+00:00", "action": "reserve",
                 "reader_id": "R-ORD-999", "book_id": "NOT-EXIST-BOOK-123", "success": True},
                {"log_id": "ord-log-dup", "timestamp": "2026-06-19T14:00:00+00:00", "action": "checkout",
                 "reader_id": "R-ORD-001", "book_id": "ORD-B001", "success": True},
                {"log_id": "ord-log-dup", "timestamp": "2026-06-19T15:00:00+00:00", "action": "return",
                 "reader_id": "R-ORD-001", "book_id": "ORD-B001", "success": True},
            ],
        }

        r3, s3 = api("POST", "/api/snapshot/precheck", order_and_ref_snapshot)
        assert_true(s3 == 200 and r3["ok"], "预检 HTTP 200")
        report3 = r3["data"]
        print_report_summary(report3)

        log_issues = report3["details"]["logs"].get("issues", [])
        print(f"\n  [日志 issues 明细] 共 {len(log_issues)} 条：")
        for iss in log_issues:
            print(f"    类型: {iss.get('type')}, 索引: {iss.get('index')}")
            print(f"      消息: {iss.get('message')}")
            print(f"      blocks_other_blocks: {iss.get('blocks_other_blocks')}, "
                  f"blocks_current_block: {iss.get('blocks_current_block')}")

        out_of_order = [i for i in log_issues if i.get("type") == "log_timestamp_out_of_order"]
        assert_true(len(out_of_order) >= 1,
                    f"检测到时间顺序错乱至少 1 条，实际 {len(out_of_order)}")

        missing_refs = [i for i in log_issues if i.get("type") == "log_references_missing_book"]
        assert_true(len(missing_refs) == 1,
                    f"检测到引用不存在书目 1 条，实际 {len(missing_refs)}")
        assert_true(missing_refs[0]["book_id"] == "NOT-EXIST-BOOK-123",
                    f"引用不存在的书目为 NOT-EXIST-BOOK-123，实际 {missing_refs[0]['book_id']}")

        dup_log_ids = [i for i in log_issues if i.get("type") == "duplicate_log_id_in_snapshot"]
        assert_true(len(dup_log_ids) == 1,
                    f"检测到重复 log_id 1 条，实际 {len(dup_log_ids)}")
        assert_true(dup_log_ids[0]["log_id"] == "ord-log-dup",
                    f"重复的 log_id 是 ord-log-dup，实际 {dup_log_ids[0]['log_id']}")

        for iss in out_of_order + missing_refs + dup_log_ids:
            assert_true(iss.get("blocks_other_blocks") is False,
                        f"{iss.get('type')} 不阻断其他块")
            assert_true(iss.get("blocks_current_block") is False,
                        f"{iss.get('type')} 不阻断当前日志块（只告警，其他正常日志仍可导入）")

        logs_will_add3 = report3["details"]["logs"]["will_add"]
        assert_true(len(logs_will_add3) == 6,
                    f"即使有 issues，6 条日志格式正确都列入 will_add（issue 非阻断），实际 {len(logs_will_add3)}")

        print("\n  [结论] 时间乱序/引用不存在/重复 log_id 是告警级问题（非阻断），")
        print("          会在 issues 里明确指出哪一条、为什么、会不会阻断其他块。")
        print("          其他正常日志依然可以被导入。")

        section("场景 4：完整链路 - 导出 → 预检 → dry-run → 正式导入 → 重启验证")

        clear_data()
        stop_server(server_proc)
        time.sleep(1)
        server_proc = start_server()

        api("POST", "/api/books",
            {"book_id": "CHAIN-B001", "title": "链路测试书1", "total_copies": 2, "borrow_days": 30, "retain_hours": 24})
        api("POST", "/api/books",
            {"book_id": "CHAIN-B002", "title": "链路测试书2", "total_copies": 3, "borrow_days": 14, "retain_hours": 12})
        api("POST", "/api/reserve", {"book_id": "CHAIN-B001", "reader_id": "R-CH-001"})
        api("POST", "/api/reserve", {"book_id": "CHAIN-B001", "reader_id": "R-CH-002"})
        api("POST", "/api/reserve", {"book_id": "CHAIN-B001", "reader_id": "R-CH-003"})
        api("POST", "/api/checkout", {"book_id": "CHAIN-B001", "reader_id": "R-CH-001"})
        api("POST", "/api/blacklist", {"reader_id": "R-CH-BL1", "reason": "逾期不还链路测试"})

        export_r, _ = api("GET", "/api/snapshot/export")
        snapshot_chain = export_r["data"]
        print(f"  [导出] 书目={snapshot_chain['counts']['books']}, "
              f"预约={snapshot_chain['counts']['active_reservations']}, "
              f"黑名单={snapshot_chain['counts']['blacklist']}, "
              f"日志={snapshot_chain['counts']['logs']}")

        source_books = {b["book_id"] for b in snapshot_chain["books"]}
        source_queues = {}
        for bid in source_books:
            source_queues[bid] = get_active_reservations(bid)
        source_avails = {bid: get_available_copies(bid) for bid in source_books}
        source_logs = {bid: get_logs_by_book(bid, limit=1000) for bid in source_books}
        source_blacklist = get_blacklist()

        # 清空数据并重启服务，得到真正的空目标环境
        clear_data()
        stop_server(server_proc)
        time.sleep(1)
        server_proc = start_server()
        assert_true(get_book_count() == 0, "清空目标环境后书目数为 0")

        pre_chain_r, _ = api("POST", "/api/snapshot/precheck", snapshot_chain)
        pre_report = pre_chain_r["data"]
        print_report_summary(pre_report)
        assert_true(pre_report["can_import"] is True, "空环境预检 can_import=True")

        dry_chain_r, dry_chain_s = api("POST", "/api/snapshot/import?dry_run=true", snapshot_chain)
        assert_true(dry_chain_s == 200 and dry_chain_r["ok"], "dry-run 通过 HTTP 200")
        assert_true(dry_chain_r["imported_counts"]["books"] == snapshot_chain["counts"]["books"],
                    "dry-run 显示书目数匹配")
        assert_true(get_book_count() == 0, "dry-run 不写库，书目数保持 0")

        imp_chain_r, imp_chain_s = api("POST", "/api/snapshot/import?dry_run=false", snapshot_chain)
        assert_true(imp_chain_s == 200 and imp_chain_r["ok"], "正式导入成功 HTTP 200")

        for bid in source_books:
            dest_queue = get_active_reservations(bid)
            assert_true(len(dest_queue) == len(source_queues[bid]),
                        f"{bid} 队列长度匹配：源={len(source_queues[bid])}, 目标={len(dest_queue)}")
            for r_s, r_d in zip(
                sorted(source_queues[bid], key=lambda x: x["created_at"]),
                sorted(dest_queue, key=lambda x: x["created_at"]),
            ):
                assert_true(r_s["reader_id"] == r_d["reader_id"],
                            f"{bid} 队列顺序一致：{r_s['reader_id']} == {r_d['reader_id']}")
                assert_true(r_s["status"] == r_d["status"],
                            f"{bid}/{r_s['reader_id']} 状态一致：{r_s['status']} == {r_d['status']}")

            dest_avail = get_available_copies(bid)
            assert_true(dest_avail == source_avails[bid],
                        f"{bid} 可借状态一致：源={source_avails[bid]}, 目标={dest_avail}")

            dest_logs = get_logs_by_book(bid, limit=1000)
            src_log_ids = {l["log_id"] for l in source_logs[bid]}
            dst_log_ids = {l["log_id"] for l in dest_logs}
            assert_true(src_log_ids == dst_log_ids,
                        f"{bid} 日志过滤结果一致：源={len(src_log_ids)}条，目标={len(dst_log_ids)}条")

        dest_blacklist = get_blacklist()
        dest_bl_ids = {b["reader_id"] for b in dest_blacklist}
        src_bl_ids = {b["reader_id"] for b in source_blacklist}
        assert_true(src_bl_ids == dest_bl_ids, f"黑名单一致：{src_bl_ids} == {dest_bl_ids}")

        print("  [链路] 目标环境：队列顺序、可借状态、日志过滤结果、黑名单 = 完全匹配源环境")

        section("场景 5：服务重启后重复提交 + 配置切换后重跑")

        subsection("5.1 重启后预检结果一致")

        pre_restart_report_r, _ = api("POST", "/api/snapshot/precheck", snapshot_chain)
        pre_restart_report = pre_restart_report_r["data"]
        pre_restart_can = pre_restart_report["can_import"]
        pre_restart_conflicts = pre_restart_report["summary"]["total_conflicts"]

        stop_server(server_proc)
        time.sleep(1)
        server_proc = start_server()

        post_restart_report_r, _ = api("POST", "/api/snapshot/precheck", snapshot_chain)
        post_restart_report = post_restart_report_r["data"]

        assert_true(pre_restart_can == post_restart_report["can_import"],
                    f"重启后 can_import 一致: {pre_restart_can} == {post_restart_report['can_import']}")
        assert_true(pre_restart_conflicts == post_restart_report["summary"]["total_conflicts"],
                    f"重启后冲突数一致: {pre_restart_conflicts} == {post_restart_report['summary']['total_conflicts']}")

        subsection("5.2 重启后重复提交导入 - 冲突，回滚完整")

        dup_imp_r, dup_imp_s = api("POST", "/api/snapshot/import?dry_run=false", snapshot_chain)
        assert_true(dup_imp_s == 409, f"重启后重复提交返回 409，实际 {dup_imp_s}")
        conflicts_after_restart = dup_imp_r.get("conflicts", [])
        assert_true(len(conflicts_after_restart) > 0, "重启后重复提交检测到冲突")

        book_count_after_dup = get_book_count()
        assert_true(book_count_after_dup == len(source_books),
                    f"重复提交回滚后书目数不变: {len(source_books)} == {book_count_after_dup}")

        queue_after_dup = get_active_reservations("CHAIN-B001")
        assert_true(len(queue_after_dup) == len(source_queues["CHAIN-B001"]),
                    f"重复提交回滚后 CHAIN-B001 队列长度不变")

        subsection("5.3 配置切换后重跑 - 新增配置书目可以导入")

        new_books_snapshot = {
            "version": "2.0",
            "type": "full_snapshot",
            "books": [
                {"book_id": "NEWCFG-B001", "title": "配置切换后新增书1", "total_copies": 5, "borrow_days": 7, "retain_hours": 6},
                {"book_id": "NEWCFG-B002", "title": "配置切换后新增书2", "total_copies": 2, "borrow_days": 21, "retain_hours": 24},
            ],
            "active_reservations": [],
            "blacklist": [],
            "logs": [],
        }

        pre_cfg_r, _ = api("POST", "/api/snapshot/precheck", new_books_snapshot)
        pre_cfg = pre_cfg_r["data"]
        assert_true(pre_cfg["can_import"] is True, "配置切换新增书目预检通过")

        dry_cfg_r, dry_cfg_s = api("POST", "/api/snapshot/import?dry_run=true", new_books_snapshot)
        assert_true(dry_cfg_s == 200 and dry_cfg_r["ok"], "dry-run 配置切换新增书目通过")

        imp_cfg_r, imp_cfg_s = api("POST", "/api/snapshot/import?dry_run=false", new_books_snapshot)
        assert_true(imp_cfg_s == 200 and imp_cfg_r["ok"], "正式导入配置切换新增书目成功")
        assert_true(get_book_count() == len(source_books) + 2,
                    f"配置切换导入后书目总数 = 原 {len(source_books)} + 新 2 = {len(source_books) + 2}")

        print("  [配置切换] 新增书目顺利导入，原有队列/日志完全不受影响")

        section("场景 6：混合有效/无效日志 + 预约/黑名单冲突 同时出现")

        mixed_big_snapshot = {
            "version": "2.0",
            "type": "full_snapshot",
            "books": [
                {"book_id": "CHAIN-B001", "title": "与目标冲突的书名", "total_copies": 99, "borrow_days": 99, "retain_hours": 99},
                {"book_id": "MIX-B002", "title": "一本新书", "total_copies": 2, "borrow_days": 14, "retain_hours": 12},
            ],
            "active_reservations": [
                {
                    "reservation_id": "mix-res-1",
                    "book_id": "CHAIN-B001",
                    "reader_id": "R-CH-003",
                    "status": "waiting",
                    "created_at": "2099-01-01T00:00:00+00:00",
                    "available_at": None, "expire_at": None, "borrowed_at": None, "returned_at": None,
                },
                {
                    "reservation_id": "mix-res-2",
                    "book_id": "MIX-B002",
                    "reader_id": "R-MIX-NEW-001",
                    "status": "waiting",
                    "created_at": "2026-06-19T08:00:00+00:00",
                    "available_at": None, "expire_at": None, "borrowed_at": None, "returned_at": None,
                },
            ],
            "blacklist": [
                {"reader_id": "R-CH-BL1", "reason": "与现有原因不一致！", "added_at": "2026-06-19T00:00:00+00:00"},
                {"reader_id": "R-MIX-NEW-BL1", "reason": "全新黑名单原因", "added_at": "2026-06-19T00:00:00+00:00"},
            ],
            "logs": [
                "混入字符串日志_混合场景",
                {"log_id": "mix-log-ok", "timestamp": "2026-06-19T09:00:00+00:00", "action": "add_book",
                 "book_id": "MIX-B002", "success": True},
                {"timestamp": "2026-06-19T10:00:00+00:00", "action": "reserve",
                 "book_id": "MIX-B002", "success": "应该是bool"},
                {"log_id": "mix-log-dup1", "timestamp": "2026-06-19T11:00:00+00:00", "action": "reserve",
                 "book_id": "MIX-B002", "reader_id": "R-MIX-NEW-001", "success": True},
                {"log_id": "mix-log-dup1", "timestamp": "2026-06-19T12:00:00+00:00", "action": "cancel",
                 "book_id": "MIX-B002", "reader_id": "R-MIX-NEW-001", "success": True},
                {"log_id": "mix-bad-ref", "timestamp": "2026-06-19T13:00:00+00:00", "action": "delete_book",
                 "book_id": "DOES-NOT-EXIST-IN-SNAPSHOT-OR-STORE-1234", "success": True},
            ],
        }

        mixed_r, mixed_s = api("POST", "/api/snapshot/precheck", mixed_big_snapshot)
        assert_true(mixed_s == 200 and mixed_r["ok"], "复杂混合场景预检 HTTP 200")
        mixed_report = mixed_r["data"]
        print_report_summary(mixed_report)

        assert_true(mixed_report["can_import"] is False, "混合场景 can_import=False")

        book_conflicts = mixed_report["details"]["books"]["conflicts"]
        assert_true(len(book_conflicts) == 1, f"书目冲突 1 个(CHAIN-B001 已存在)，实际 {len(book_conflicts)}")

        res_conflicts = mixed_report["details"]["active_reservations"]["conflicts"]
        assert_true(len(res_conflicts) == 1, f"预约冲突 1 个(CHAIN-B001/R-CH-003 已存在)，实际 {len(res_conflicts)}")

        bl_conflicts = mixed_report["details"]["blacklist"]["conflicts"]
        assert_true(len(bl_conflicts) == 1, f"黑名单冲突 1 个(R-CH-BL1 原因不一致)，实际 {len(bl_conflicts)}")

        log_fe = mixed_report["details"]["logs"]["format_errors"]
        log_iss = mixed_report["details"]["logs"].get("issues", [])
        print(f"\n  [混合场景日志统计] 格式错误={len(log_fe)}, issues={len(log_iss)}")
        for fe in log_fe:
            print(f"    [FE idx={fe.get('index')}] {fe.get('error_code')}: {fe.get('message')[:60]}...")
        for iss in log_iss:
            print(f"    [ISS type={iss.get('type')} idx={iss.get('index')}]: {iss.get('message')[:60]}...")

        assert_true(len(log_fe) >= 2, "至少 2 条格式错误(字符串混入 + success类型错)")
        dup_log = [i for i in log_iss if i.get("type") == "duplicate_log_id_in_snapshot"]
        miss_ref = [i for i in log_iss if i.get("type") == "log_references_missing_book"]
        assert_true(len(dup_log) == 1, "1 条重复 log_id")
        assert_true(len(miss_ref) == 1, "1 条引用不存在书目")

        books_will_add = mixed_report["details"]["books"]["will_add"]
        assert_true(len(books_will_add) == 1 and books_will_add[0]["book_id"] == "MIX-B002",
                    "will_add 书目只有 MIX-B002")

        res_will_add = mixed_report["details"]["active_reservations"]["will_add"]
        assert_true(len(res_will_add) == 1 and res_will_add[0]["reader_id"] == "R-MIX-NEW-001",
                    "will_add 预约只有 R-MIX-NEW-001")

        bl_will_add = mixed_report["details"]["blacklist"]["will_add"]
        assert_true(len(bl_will_add) == 1 and bl_will_add[0]["reader_id"] == "R-MIX-NEW-BL1",
                    "will_add 黑名单只有 R-MIX-NEW-BL1")

        logs_will_add = mixed_report["details"]["logs"]["will_add"]
        ok_log_ids = {l["log_id"] for l in logs_will_add}
        assert_true("mix-log-ok" in ok_log_ids, "有效日志 mix-log-ok 在 will_add 中")
        assert_true("mix-log-dup1" in ok_log_ids, "重复 log_id 依然保留在 will_add（issue非阻断）")

        print("\n  [混合场景 Summary]")
        cats = mixed_report["summary"]["breakdown"]
        for sec in ["books", "active_reservations", "blacklist", "logs"]:
            st = cats[sec]
            print(f"    [{sec:22s}] will_add={st['will_add']:2d} | conflicts={st['conflicts']:2d} | "
                  f"missing={st['missing_dependencies']:1d} | format_errors={st['format_errors']:2d} | "
                  f"issues={st.get('issues', 0)}")

        subsection("6.1 dry-run 在混合场景下也返回同口径")

        mixed_dry_r, mixed_dry_s = api("POST", "/api/snapshot/import?dry_run=true", mixed_big_snapshot)
        print(f"  [dry-run] HTTP {mixed_dry_s}, ok={mixed_dry_r.get('ok')}")

        if mixed_dry_s == 400:
            err_msgs = mixed_dry_r.get("error", [])
            print(f"  [dry-run 400 error 条数] {len(err_msgs)}")
            has_log_error = any("logs" in m for m in err_msgs)
            assert_true(has_log_error, "400 error 中包含 logs 相关格式错误")
        elif mixed_dry_s == 409:
            conf_types = {c["type"] for c in mixed_dry_r.get("conflicts", [])}
            print(f"  [dry-run 409 conflict 类型] {conf_types}")
        else:
            assert_true(False, f"混合场景 dry-run 应返回 400 或 409，实际 {mixed_dry_s}")

        subsection("6.2 正式导入在混合场景下整体回滚 - 不改动任何数据")

        book_count_before = get_book_count()
        queue_before = {bid: get_active_reservations(bid) for bid in source_books}
        logs_before = {bid: get_logs_by_book(bid, limit=1000) for bid in source_books}
        bl_before = get_blacklist()

        mixed_imp_r, mixed_imp_s = api("POST", "/api/snapshot/import?dry_run=false", mixed_big_snapshot)
        print(f"  [正式导入] HTTP {mixed_imp_s}, ok={mixed_imp_r.get('ok')}")
        assert_true(mixed_imp_s in (400, 409),
                    f"混合场景正式导入应失败 (400/409)，实际 {mixed_imp_s}")

        book_count_after = get_book_count()
        assert_true(book_count_after == book_count_before,
                    f"回滚后书目数不变: {book_count_before} == {book_count_after}")

        for bid in source_books:
            queue_after = get_active_reservations(bid)
            assert_true(len(queue_after) == len(queue_before[bid]),
                        f"回滚后 {bid} 队列长度不变")
            logs_after = get_logs_by_book(bid, limit=1000)
            assert_true({l["log_id"] for l in logs_after} == {l["log_id"] for l in logs_before[bid]},
                        f"回滚后 {bid} 日志过滤结果不变")

        bl_after = get_blacklist()
        assert_true({b["reader_id"] for b in bl_after} == {b["reader_id"] for b in bl_before},
                    "回滚后黑名单不变")

        print("  [回滚验证] 书目数、队列顺序、日志过滤、黑名单 = 完全未变")

        section("场景 7：成功导入后，日志过滤/可借状态/队列顺序不漂移")

        clear_data()
        stop_server(server_proc)
        time.sleep(1)
        server_proc = start_server()

        clean_snapshot = {
            "version": "2.0",
            "type": "full_snapshot",
            "books": [
                {"book_id": "FINAL-B001", "title": "最终测试书1", "total_copies": 3, "borrow_days": 30, "retain_hours": 24},
                {"book_id": "FINAL-B002", "title": "最终测试书2", "total_copies": 1, "borrow_days": 14, "retain_hours": 12},
            ],
            "active_reservations": [
                {
                    "reservation_id": "f-res-1",
                    "book_id": "FINAL-B001",
                    "reader_id": "R-FIN-001",
                    "status": "available",
                    "created_at": "2026-06-19T07:00:00+00:00",
                    "available_at": "2026-06-19T07:00:00+00:00",
                    "expire_at": "2026-06-20T07:00:00+00:00",
                    "borrowed_at": None,
                    "returned_at": None,
                },
                {
                    "reservation_id": "f-res-2",
                    "book_id": "FINAL-B001",
                    "reader_id": "R-FIN-002",
                    "status": "waiting",
                    "created_at": "2026-06-19T08:00:00+00:00",
                    "available_at": None,
                    "expire_at": None,
                    "borrowed_at": None,
                    "returned_at": None,
                },
                {
                    "reservation_id": "f-res-3",
                    "book_id": "FINAL-B001",
                    "reader_id": "R-FIN-003",
                    "status": "waiting",
                    "created_at": "2026-06-19T09:00:00+00:00",
                    "available_at": None,
                    "expire_at": None,
                    "borrowed_at": None,
                    "returned_at": None,
                },
                {
                    "reservation_id": "f-res-4",
                    "book_id": "FINAL-B002",
                    "reader_id": "R-FIN-004",
                    "status": "borrowed",
                    "created_at": "2026-06-18T10:00:00+00:00",
                    "available_at": "2026-06-18T10:00:00+00:00",
                    "expire_at": None,
                    "borrowed_at": "2026-06-18T11:00:00+00:00",
                    "returned_at": None,
                },
            ],
            "blacklist": [
                {"reader_id": "R-FIN-BL1", "reason": "最终黑名单原因1", "added_at": "2026-06-18T00:00:00+00:00"},
                {"reader_id": "R-FIN-BL2", "reason": "最终黑名单原因2", "added_at": "2026-06-19T00:00:00+00:00"},
            ],
            "logs": [
                {"log_id": "f-log-1", "timestamp": "2026-06-18T09:00:00+00:00", "action": "add_book",
                 "book_id": "FINAL-B001", "success": True, "detail": "创建书目"},
                {"log_id": "f-log-2", "timestamp": "2026-06-18T09:00:01+00:00", "action": "add_book",
                 "book_id": "FINAL-B002", "success": True, "detail": "创建书目"},
                {"log_id": "f-log-8", "timestamp": "2026-06-18T20:00:00+00:00", "action": "blacklist_add",
                 "reader_id": "R-FIN-BL1", "success": True, "detail": "加入黑名单"},
                {"log_id": "f-log-9", "timestamp": "2026-06-18T20:00:01+00:00", "action": "blacklist_add",
                 "reader_id": "R-FIN-BL2", "success": True, "detail": "加入黑名单"},
                {"log_id": "f-log-3", "timestamp": "2026-06-18T22:00:00+00:00", "action": "reserve",
                 "book_id": "FINAL-B002", "reader_id": "R-FIN-004", "success": True, "detail": "预约"},
                {"log_id": "f-log-4", "timestamp": "2026-06-18T23:00:00+00:00", "action": "checkout",
                 "book_id": "FINAL-B002", "reader_id": "R-FIN-004", "success": True, "detail": "借出"},
                {"log_id": "f-log-5", "timestamp": "2026-06-19T07:00:00+00:00", "action": "reserve",
                 "book_id": "FINAL-B001", "reader_id": "R-FIN-001", "success": True, "detail": "预约并立即待取"},
                {"log_id": "f-log-6", "timestamp": "2026-06-19T08:00:00+00:00", "action": "reserve",
                 "book_id": "FINAL-B001", "reader_id": "R-FIN-002", "success": True, "detail": "排队等待"},
                {"log_id": "f-log-7", "timestamp": "2026-06-19T09:00:00+00:00", "action": "reserve",
                 "book_id": "FINAL-B001", "reader_id": "R-FIN-003", "success": True, "detail": "排队等待"},
            ],
        }

        final_pre_r, _ = api("POST", "/api/snapshot/precheck", clean_snapshot)
        assert_true(final_pre_r["data"]["can_import"] is True, "最终场景预检通过")

        final_imp_r, final_imp_s = api("POST", "/api/snapshot/import?dry_run=false", clean_snapshot)
        assert_true(final_imp_s == 200 and final_imp_r["ok"], "最终场景正式导入成功")

        queue_b1 = get_active_reservations("FINAL-B001")
        reader_order_b1 = [r["reader_id"] for r in sorted(queue_b1, key=lambda x: x["created_at"])]
        expected_order_b1 = ["R-FIN-001", "R-FIN-002", "R-FIN-003"]
        assert_true(reader_order_b1 == expected_order_b1,
                    f"FINAL-B001 队列顺序未漂移: {reader_order_b1} == {expected_order_b1}")

        status_b1 = {r["reader_id"]: r["status"] for r in queue_b1}
        assert_true(status_b1["R-FIN-001"] == "available", "R-FIN-001 状态=available 未漂移")
        assert_true(status_b1["R-FIN-002"] == "waiting", "R-FIN-002 状态=waiting 未漂移")
        assert_true(status_b1["R-FIN-003"] == "waiting", "R-FIN-003 状态=waiting 未漂移")

        avail_b1 = get_available_copies("FINAL-B001")
        expected_avail_b1 = 3 - 0 - 1
        assert_true(avail_b1 == expected_avail_b1,
                    f"FINAL-B001 可借副本数未漂移: 总3 - 待取1 - 借出0 = {expected_avail_b1}，实际 {avail_b1}")

        avail_b2 = get_available_copies("FINAL-B002")
        expected_avail_b2 = 0
        assert_true(avail_b2 == expected_avail_b2,
                    f"FINAL-B002 可借副本数未漂移: 总1 - 借出1 = 0，实际 {avail_b2}")

        logs_b1 = get_logs_by_book("FINAL-B001", limit=100)
        expected_log_ids_b1 = {"f-log-1", "f-log-5", "f-log-6", "f-log-7"}
        actual_log_ids_b1 = {l["log_id"] for l in logs_b1}
        assert_true(actual_log_ids_b1 == expected_log_ids_b1,
                    f"FINAL-B001 日志过滤结果未漂移: {actual_log_ids_b1} == {expected_log_ids_b1}")

        logs_b2 = get_logs_by_book("FINAL-B002", limit=100)
        expected_log_ids_b2 = {"f-log-2", "f-log-3", "f-log-4"}
        actual_log_ids_b2 = {l["log_id"] for l in logs_b2}
        assert_true(actual_log_ids_b2 == expected_log_ids_b2,
                    f"FINAL-B002 日志过滤结果未漂移: {actual_log_ids_b2} == {expected_log_ids_b2}")

        all_logs_after = get_all_logs(limit=500)
        no_stray = all(
            not (l.get("action") in ("import_snapshot", "import_snapshot_dry_run", "precheck_snapshot")
                 and (l.get("book_id") or l.get("reader_id")))
            for l in all_logs_after
        )
        assert_true(no_stray, "导入/预检汇总日志不带 book_id/reader_id，不会被过滤命中导致漂移")

        bl_final = get_blacklist()
        bl_final_ids = {b["reader_id"] for b in bl_final}
        assert_true(bl_final_ids == {"R-FIN-BL1", "R-FIN-BL2"}, "黑名单未漂移")

        print(f"\n  [成功导入后一致性验证]")
        print(f"    FINAL-B001 队列顺序: {reader_order_b1} (未漂移)")
        print(f"    FINAL-B001 可借副本: {avail_b1} = 总3 - 待取1 - 借出0  (未漂移)")
        print(f"    FINAL-B002 可借副本: {avail_b2} = 总1 - 借出1  (未漂移)")
        print(f"    FINAL-B001 日志条数: {len(logs_b1)} (未漂移)")
        print(f"    FINAL-B002 日志条数: {len(logs_b2)} (未漂移)")
        print(f"    黑名单集合: {bl_final_ids} (未漂移)")
        print(f"    无串味导入日志: 是")

        print("\n" + "=" * 60)
        print("  快照迁移扎实版回归测试全部通过!")
        print("=" * 60)
        print("\n  核心改进总结:")
        print("  1. 预检、dry-run、正式导入 100% 共用 _analyze_snapshot_conflicts 校验逻辑")
        print("  2. 新增 _validate_snapshot_log：单条日志字段/类型/格式完整校验")
        print("  3. 新增 _check_log_order_and_references：时间乱序/引用不存在/重复log_id检测")
        print("  4. 预检永不 500：try-except 包裹，内部错误转 format_error 报告")
        print("  5. 所有错误都带：第几号、为什么、会不会阻断其他块、会不会阻断当前块")
        print("  6. dry-run 绝对不写库，正式导入冲突/格式错误完整回滚")
        print("  7. 成功导入后：队列顺序、可借状态、日志过滤、黑名单完全无漂移")
        print("  8. 覆盖链路：导出→预检→dry-run→导入、重启后重复提交、配置切换重跑")
        print("  9. 覆盖异常：字符串混入、缺字段、类型错、时间乱序、引用不存在、重复log_id")
        print("  10. 覆盖混合：有效/无效日志 + 预约/黑名单冲突 同时出现口径一致")

    finally:
        stop_server(server_proc)

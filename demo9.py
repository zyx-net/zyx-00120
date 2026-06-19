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


def assert_equal(actual, expected, msg):
    if actual != expected:
        print(f"  [FAIL] {msg}")
        print(f"    期望: {expected}")
        print(f"    实际: {actual}")
        sys.exit(1)
    print(f"  [PASS] {msg}")


def clear_data():
    if not os.path.isdir(DATA_DIR):
        os.makedirs(DATA_DIR, exist_ok=True)
        return
    for name in ["books", "reservations", "blacklist", "logs", "batches"]:
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


def get_file_hash(filename):
    p = os.path.join(DATA_DIR, filename)
    if not os.path.exists(p):
        return None
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def get_file_mtime(filename):
    p = os.path.join(DATA_DIR, filename)
    if not os.path.exists(p):
        return None
    return os.path.getmtime(p)


def create_test_snapshot(book_prefix="BATCH", res_prefix="R-BATCH", bl_prefix="BL-BATCH"):
    books = [
        {"book_id": f"{book_prefix}-001", "title": "批次测试书1", "total_copies": 5, "borrow_days": 30, "retain_hours": 24},
        {"book_id": f"{book_prefix}-002", "title": "批次测试书2", "total_copies": 3, "borrow_days": 14, "retain_hours": 12},
    ]
    reservations = [
        {
            "reservation_id": f"res-{book_prefix}-001-01",
            "book_id": f"{book_prefix}-001",
            "reader_id": f"{res_prefix}-001",
            "status": "waiting",
            "created_at": "2026-06-19T08:00:00+00:00",
            "available_at": None,
            "expire_at": None,
            "borrowed_at": None,
            "returned_at": None,
        },
        {
            "reservation_id": f"res-{book_prefix}-001-02",
            "book_id": f"{book_prefix}-001",
            "reader_id": f"{res_prefix}-002",
            "status": "available",
            "created_at": "2026-06-19T07:00:00+00:00",
            "available_at": "2026-06-19T07:00:00+00:00",
            "expire_at": "2026-06-20T07:00:00+00:00",
            "borrowed_at": None,
            "returned_at": None,
        },
    ]
    blacklist = [
        {"reader_id": f"{bl_prefix}-001", "reason": "逾期未还", "added_at": "2026-06-18T10:00:00+00:00"},
    ]
    logs = [
        {
            "log_id": f"log-{book_prefix}-001",
            "timestamp": "2026-06-19T07:00:00+00:00",
            "action": "add_book",
            "book_id": f"{book_prefix}-001",
            "detail": "添加书目 批次测试书1",
            "success": True,
        },
        {
            "log_id": f"log-{book_prefix}-002",
            "timestamp": "2026-06-19T08:00:00+00:00",
            "action": "reserve",
            "book_id": f"{book_prefix}-001",
            "reader_id": f"{res_prefix}-001",
            "detail": "预约成功，状态=waiting",
            "success": True,
        },
    ]
    return {
        "version": "2.0",
        "type": "full_snapshot",
        "books": books,
        "active_reservations": reservations,
        "blacklist": blacklist,
        "logs": logs,
    }


def main():
    section("批次管理完整回归测试 (demo9)")

    print("\n[准备] 清空数据并启动服务")
    clear_data()
    proc = start_server()

    try:
        section("测试1: 批次列表 API 存在且返回空列表")
        r, status = api("GET", "/api/batches")
        assert_equal(status, 200, "GET /api/batches 返回 200")
        assert_true(r.get("ok"), "响应 ok=true")
        assert_true(isinstance(r.get("data"), list), "data 是列表")
        assert_equal(len(r["data"]), 0, "初始批次列表为空")

        section("测试2: 正式导入快照后生成批次记录")
        snapshot = create_test_snapshot("BATCH-A")
        r, status = api("POST", "/api/snapshot/import?dry_run=false", snapshot)
        assert_equal(status, 200, "正式导入返回 200")
        assert_true(r.get("ok"), "导入成功 ok=true")
        assert_true("batch_id" in r, "响应包含 batch_id")
        batch_id = r["batch_id"]
        assert_true(batch_id and len(batch_id) > 0, "batch_id 非空")
        print(f"  [INFO] 生成的批次ID: {batch_id}")

        section("测试3: 批次列表展示导入的批次")
        r, status = api("GET", "/api/batches")
        assert_equal(status, 200, "GET /api/batches 返回 200")
        assert_equal(len(r["data"]), 1, "批次列表有 1 条记录")
        batch_info = r["data"][0]
        assert_equal(batch_info["batch_id"], batch_id, "批次ID匹配")
        assert_equal(batch_info["type"], "snapshot_import", "批次类型正确")
        assert_equal(batch_info["status"], "active", "批次状态为 active")
        assert_true("created_at" in batch_info, "包含创建时间")
        assert_equal(batch_info["summary"]["books"], 2, "summary 中 books 数量正确")
        assert_equal(batch_info["summary"]["active_reservations"], 2, "summary 中 reservations 数量正确")
        assert_equal(batch_info["summary"]["blacklist"], 1, "summary 中 blacklist 数量正确")
        assert_equal(batch_info["summary"]["logs"], 2, "summary 中 logs 数量正确")

        section("测试4: 批次详情包含完整导入明细")
        r, status = api("GET", f"/api/batches/{batch_id}")
        assert_equal(status, 200, "GET /api/batches/<id> 返回 200")
        assert_true(r.get("ok"), "响应 ok=true")
        batch_detail = r["data"]
        assert_equal(batch_detail["batch_id"], batch_id, "批次ID正确")
        assert_equal(batch_detail["status"], "active", "状态为 active")
        assert_true("imported_details" in batch_detail, "包含 imported_details")
        details = batch_detail["imported_details"]
        assert_equal(len(details["books"]), 2, "imported_details.books 有 2 条")
        assert_equal(len(details["active_reservations"]), 2, "imported_details.active_reservations 有 2 条")
        assert_equal(len(details["blacklist"]), 1, "imported_details.blacklist 有 1 条")
        assert_equal(len(details["logs"]), 2, "imported_details.logs 有 2 条")
        assert_equal(details["books"][0]["book_id"], "BATCH-A-001", "书籍明细正确")
        assert_equal(details["active_reservations"][0]["reader_id"], "R-BATCH-001", "预约明细正确")
        assert_equal(details["blacklist"][0]["reader_id"], "BL-BATCH-001", "黑名单明细正确")

        section("测试5: 批次导出功能 - 导出格式与快照一致")
        r, status = api("GET", f"/api/batches/{batch_id}/export")
        assert_equal(status, 200, "批次导出返回 200")
        assert_true(r.get("ok"), "导出成功 ok=true")
        exported = r["data"]
        assert_equal(exported["version"], "2.0", "导出版本正确")
        assert_equal(exported["type"], "full_snapshot", "导出类型正确")
        assert_equal(exported["source_batch_id"], batch_id, "source_batch_id 正确")
        assert_equal(len(exported["books"]), 2, "导出 books 数量正确")
        assert_equal(len(exported["active_reservations"]), 2, "导出 reservations 数量正确")
        assert_equal(len(exported["blacklist"]), 1, "导出 blacklist 数量正确")
        assert_equal(len(exported["logs"]), 2, "导出 logs 数量正确")
        assert_equal(exported["books"][0]["book_id"], "BATCH-A-001", "导出的书籍内容匹配")

        section("测试6: 回滚批次 - 成功回滚所有数据")
        books_before = api("GET", "/api/books")[0]["data"]
        assert_equal(len(books_before), 2, "回滚前有 2 本书")

        r, status = api("POST", f"/api/batches/{batch_id}/rollback")
        assert_equal(status, 200, "回滚返回 200")
        assert_true(r.get("ok"), "回滚成功 ok=true")
        assert_true(r.get("rollback_count", 0) > 0, "rollback_count > 0")
        assert_equal(r.get("already_rolled_back"), False, "首次回滚 already_rolled_back=false")
        assert_equal(r["batch"]["status"], "rolled_back", "批次状态变为 rolled_back")
        assert_true("rolled_back_at" in r["batch"], "包含 rolled_back_at")

        books_after = api("GET", "/api/books")[0]["data"]
        assert_equal(len(books_after), 0, "回滚后书目数量为 0")

        reservations_after = api("GET", "/api/queue/BATCH-A-001")[0]
        assert_true(reservations_after.get("ok"), "预约查询正常返回")
        assert_equal(len(reservations_after.get("data", [])), 0, "回滚后预约队列为空")

        blacklist_after = api("GET", "/api/blacklist")[0]["data"]
        assert_equal(len(blacklist_after), 0, "回滚后黑名单数量为 0")

        logs_after = api("GET", "/api/logs?limit=1000")[0]["data"]
        batch_log_count = sum(1 for l in logs_after if l.get("book_id") and l["book_id"].startswith("BATCH-A-"))
        assert_equal(batch_log_count, 0, "回滚后批次相关的业务日志被清除")

        section("测试7: 回滚幂等性 - 重复回滚不报错")
        r2, status2 = api("POST", f"/api/batches/{batch_id}/rollback")
        assert_equal(status2, 200, "第二次回滚也返回 200")
        assert_true(r2.get("ok"), "第二次回滚 ok=true")
        assert_equal(r2.get("already_rolled_back"), True, "第二次回滚 already_rolled_back=true")
        assert_equal(r2.get("rollback_count"), 0, "第二次回滚 rollback_count=0")
        assert_equal(r2["batch"]["status"], "rolled_back", "状态保持 rolled_back")

        logs_after_2 = api("GET", "/api/logs?limit=1000")[0]["data"]
        rollback_logs = [l for l in logs_after_2 if l.get("action") == "rollback_batch"]
        assert_equal(len(rollback_logs), 1, "重复回滚不新增 rollback_batch 日志（幂等）")

        section("测试8: 批次状态更新 - 回滚后列表和详情都显示 rolled_back")
        r_list, _ = api("GET", "/api/batches")
        assert_equal(r_list["data"][0]["status"], "rolled_back", "列表中状态为 rolled_back")

        r_detail, _ = api("GET", f"/api/batches/{batch_id}")
        assert_equal(r_detail["data"]["status"], "rolled_back", "详情中状态为 rolled_back")
        assert_true(r_detail["data"]["rolled_back_at"] is not None, "详情中 rolled_back_at 非空")
        assert_true(r_detail["data"]["rollback_log_id"] is not None, "详情中 rollback_log_id 非空")

        section("测试9: 不存在的批次返回 404")
        r, status = api("GET", "/api/batches/nonexistent-batch-id")
        assert_equal(status, 404, "不存在的批次详情返回 404")
        assert_true(r.get("error"), "包含错误信息")

        r, status = api("GET", "/api/batches/nonexistent-batch-id/export")
        assert_equal(status, 404, "不存在的批次导出返回 404")

        r, status = api("POST", "/api/batches/nonexistent-batch-id/rollback")
        assert_equal(status, 400, "不存在的批次回滚返回 400")

        section("测试10: 服务重启后批次数据持久化")
        print("  [INFO] 重启服务中...")
        stop_server(proc)
        proc = start_server()

        r_list, _ = api("GET", "/api/batches")
        assert_equal(len(r_list["data"]), 1, "重启后批次列表仍有 1 条记录")
        assert_equal(r_list["data"][0]["batch_id"], batch_id, "重启后批次ID不变")
        assert_equal(r_list["data"][0]["status"], "rolled_back", "重启后状态仍为 rolled_back")

        r_detail, _ = api("GET", f"/api/batches/{batch_id}")
        assert_equal(r_detail["data"]["status"], "rolled_back", "重启后详情状态正确")
        assert_equal(len(r_detail["data"]["imported_details"]["books"]), 2, "重启后明细数据完整")

        section("测试11: 配置切换后导入 - 新增批次与已有数据互不影响")
        clear_data()
        stop_server(proc)
        proc = start_server()

        snap1 = create_test_snapshot("CFG-1", "R-CFG1", "BL-CFG1")
        r1, _ = api("POST", "/api/snapshot/import?dry_run=false", snap1)
        batch1 = r1["batch_id"]

        snap2 = create_test_snapshot("CFG-2", "R-CFG2", "BL-CFG2")
        r2, _ = api("POST", "/api/snapshot/import?dry_run=false", snap2)
        batch2 = r2["batch_id"]

        r_list, _ = api("GET", "/api/batches")
        assert_equal(len(r_list["data"]), 2, "两个批次都在列表中")
        batch_ids = [b["batch_id"] for b in r_list["data"]]
        assert_true(batch1 in batch_ids, "批次1在列表中")
        assert_true(batch2 in batch_ids, "批次2在列表中")

        books_all = api("GET", "/api/books")[0]["data"]
        assert_equal(len(books_all), 4, "两个批次的书籍都存在，共 4 本")

        r_rb, _ = api("POST", f"/api/batches/{batch1}/rollback")
        assert_true(r_rb["ok"], "回滚批次1成功")

        books_after_rb = api("GET", "/api/books")[0]["data"]
        book_ids_after = [b["book_id"] for b in books_after_rb]
        assert_equal(len(books_after_rb), 2, "回滚批次1后剩 2 本书")
        assert_true("CFG-2-001" in book_ids_after, "批次2的书仍然存在")
        assert_true("CFG-2-002" in book_ids_after, "批次2的书仍然存在")
        assert_true("CFG-1-001" not in book_ids_after, "批次1的书已被回滚")
        assert_true("CFG-1-002" not in book_ids_after, "批次1的书已被回滚")

        r_list2, _ = api("GET", "/api/batches")
        status_map = {b["batch_id"]: b["status"] for b in r_list2["data"]}
        assert_equal(status_map[batch1], "rolled_back", "批次1状态为 rolled_back")
        assert_equal(status_map[batch2], "active", "批次2状态仍为 active")

        section("测试12: 回滚冲突检测 - 书目被修改后拦截回滚")
        clear_data()
        stop_server(proc)
        proc = start_server()

        snap_conflict = create_test_snapshot("CONFLICT", "R-CONF", "BL-CONF")
        r_import, _ = api("POST", "/api/snapshot/import?dry_run=false", snap_conflict)
        batch_conflict = r_import["batch_id"]

        api("PUT", "/api/books/CONFLICT-001", {"title": "修改后的书名"})

        r_rb, status_rb = api("POST", f"/api/batches/{batch_conflict}/rollback")
        assert_equal(status_rb, 409, "书目被修改后回滚返回 409")
        assert_true("conflicts" in r_rb, "响应包含 conflicts")
        assert_true(len(r_rb["conflicts"]) > 0, "冲突列表非空")

        book_conflicts = [c for c in r_rb["conflicts"] if c["section"] == "books"]
        assert_true(len(book_conflicts) > 0, "存在书目相关冲突")
        assert_equal(book_conflicts[0]["type"], "book_modified", "冲突类型为 book_modified")
        assert_equal(book_conflicts[0]["book_id"], "CONFLICT-001", "冲突书目ID正确")
        assert_true("changed_fields" in book_conflicts[0], "包含 changed_fields")
        assert_true(len(book_conflicts[0]["changed_fields"]) > 0, "有变更字段明细")
        assert_true("message" in book_conflicts[0], "包含可读的错误消息")
        assert_true("被修改过" in book_conflicts[0]["message"], "错误消息可读")

        books_after_conflict = api("GET", "/api/books")[0]["data"]
        assert_equal(len(books_after_conflict), 2, "回滚冲突时数据保持原状，不部分回滚")

        r_detail_conflict, _ = api("GET", f"/api/batches/{batch_conflict}")
        assert_equal(r_detail_conflict["data"]["status"], "active", "冲突回滚后批次状态仍为 active")

        section("测试13: 回滚冲突检测 - 预约状态变化后拦截")
        snap_res = create_test_snapshot("RES-CONF", "R-RESCONF", "BL-RESCONF")
        r2, _ = api("POST", "/api/snapshot/import?dry_run=false", snap_res)
        batch_res = r2["batch_id"]

        api("POST", "/api/checkout", {"book_id": "RES-CONF-001", "reader_id": "R-RESCONF-002"})

        r_rb, status_rb = api("POST", f"/api/batches/{batch_res}/rollback")
        assert_equal(status_rb, 409, "预约状态变化后回滚返回 409")
        assert_true("conflicts" in r_rb, "响应包含 conflicts")

        res_conflicts = [c for c in r_rb["conflicts"] if c["section"] == "active_reservations"]
        assert_true(len(res_conflicts) > 0, "存在预约相关冲突")
        assert_equal(res_conflicts[0]["type"], "reservation_modified", "冲突类型为 reservation_modified")
        assert_true("changed_fields" in res_conflicts[0], "包含 changed_fields")

        section("测试14: 混合有效/无效日志的批次导入和回滚")
        clear_data()
        stop_server(proc)
        proc = start_server()

        mixed_snapshot = create_test_snapshot("MIXED")
        mixed_snapshot["logs"].append("this is not a log object")
        mixed_snapshot["logs"].append({
            "log_id": "log-mixed-bad",
            "timestamp": "not-a-timestamp",
            "action": "test",
            "success": "not-boolean",
        })
        mixed_snapshot["logs"].append({
            "log_id": "log-mixed-valid",
            "timestamp": "2026-06-19T09:00:00+00:00",
            "action": "add_book",
            "book_id": "MIXED-002",
            "detail": "有效日志",
            "success": True,
        })

        r_pre, _ = api("POST", "/api/snapshot/precheck", mixed_snapshot)
        assert_true(r_pre.get("ok"), "预检成功")
        log_fe_count = len(r_pre["data"]["details"]["logs"]["format_errors"])
        assert_true(log_fe_count > 0, "预检检测到日志格式错误")

        r_import, status_import = api("POST", "/api/snapshot/import?dry_run=false", mixed_snapshot)
        assert_equal(status_import, 400, "混合无效日志导入返回 400")
        assert_true("batch_id" not in r_import, "格式错误时不生成批次")

        r_list, _ = api("GET", "/api/batches")
        assert_equal(len(r_list["data"]), 0, "格式错误时不创建批次记录")

        section("测试15: 带冲突的快照导入不生成批次")
        clear_data()
        stop_server(proc)
        proc = start_server()

        api("POST", "/api/books", {
            "book_id": "EXISTING-001",
            "title": "已存在的书",
            "total_copies": 2,
            "borrow_days": 7,
            "retain_hours": 1,
        })

        conflict_snap = {
            "version": "2.0",
            "type": "full_snapshot",
            "books": [
                {"book_id": "EXISTING-001", "title": "冲突书", "total_copies": 5, "borrow_days": 30, "retain_hours": 24},
            ],
            "active_reservations": [],
            "blacklist": [],
            "logs": [],
        }
        r_import, status_import = api("POST", "/api/snapshot/import?dry_run=false", conflict_snap)
        assert_equal(status_import, 409, "冲突导入返回 409")
        assert_true("batch_id" not in r_import, "冲突导入不生成批次")

        r_list, _ = api("GET", "/api/batches")
        assert_equal(len(r_list["data"]), 0, "冲突导入后批次列表仍为空")

        section("测试16: dry-run 导入不生成批次")
        clear_data()
        stop_server(proc)
        proc = start_server()

        snap_dry = create_test_snapshot("DRYRUN")
        r_dry, _ = api("POST", "/api/snapshot/import?dry_run=true", snap_dry)
        assert_true(r_dry.get("ok"), "dry-run 成功")
        assert_true("batch_id" not in r_dry, "dry-run 不返回 batch_id")

        r_list, _ = api("GET", "/api/batches")
        assert_equal(len(r_list["data"]), 0, "dry-run 后批次列表为空")

        books_dry = api("GET", "/api/books")[0]["data"]
        assert_equal(len(books_dry), 0, "dry-run 后实际数据为空")

        section("测试17: 批次数据与实际数据一致性核对")
        clear_data()
        stop_server(proc)
        proc = start_server()

        snap_final = create_test_snapshot("FINAL")
        r_imp, _ = api("POST", "/api/snapshot/import?dry_run=false", snap_final)
        batch_final = r_imp["batch_id"]

        r_detail, _ = api("GET", f"/api/batches/{batch_final}")
        details = r_detail["data"]["imported_details"]

        actual_books = api("GET", "/api/books")[0]["data"]
        actual_book_ids = sorted([b["book_id"] for b in actual_books])
        batch_book_ids = sorted([b["book_id"] for b in details["books"]])
        assert_equal(actual_book_ids, batch_book_ids, "批次中的书籍与实际书籍ID一致")

        actual_queues = {}
        for b in details["books"]:
            q, _ = api("GET", f"/api/queue/{b['book_id']}")
            if q.get("data"):
                actual_queues[b["book_id"]] = len(q["data"])
        batch_res_by_book = {}
        for r in details["active_reservations"]:
            bid = r["book_id"]
            batch_res_by_book[bid] = batch_res_by_book.get(bid, 0) + 1
        for bid, count in batch_res_by_book.items():
            assert_equal(actual_queues.get(bid, 0), count, f"书目 {bid} 的实际预约数与批次一致")

        actual_bl = api("GET", "/api/blacklist")[0]["data"]
        actual_bl_ids = sorted([b["reader_id"] for b in actual_bl])
        batch_bl_ids = sorted([b["reader_id"] for b in details["blacklist"]])
        assert_equal(actual_bl_ids, batch_bl_ids, "批次中的黑名单与实际黑名单一致")

        section("测试18: 回滚后日志文件和 JSON 数据一致")
        logs_before_rollback = api("GET", "/api/logs?limit=10000")[0]["data"]
        log_ids_before = {l["log_id"] for l in logs_before_rollback if l.get("log_id")}

        books_hash_before = get_file_hash("books.json")
        logs_hash_before = get_file_hash("logs.json")

        r_rb, _ = api("POST", f"/api/batches/{batch_final}/rollback")
        assert_true(r_rb["ok"], "回滚成功")

        logs_after_rollback = api("GET", "/api/logs?limit=10000")[0]["data"]
        log_ids_after = {l["log_id"] for l in logs_after_rollback if l.get("log_id")}

        batch_log_ids = {l["log_id"] for l in details["logs"] if l.get("log_id")}
        removed_log_ids = log_ids_before - log_ids_after
        assert_equal(removed_log_ids, batch_log_ids, "回滚移除的日志正好是批次导入的日志")

        rollback_logs = [l for l in logs_after_rollback if l.get("action") == "rollback_batch"]
        assert_equal(len(rollback_logs), 1, "恰好有一条 rollback_batch 日志")
        assert_true(rollback_logs[0]["success"], "回滚日志 success=true")
        assert_true(batch_final in rollback_logs[0]["detail"], "回滚日志包含批次ID")

        books_after = api("GET", "/api/books")[0]["data"]
        assert_equal(len(books_after), 0, "回滚后书籍数量为 0")

        with open(os.path.join(DATA_DIR, "batches.json"), "r", encoding="utf-8") as f:
            batches_file = json.load(f)
        batch_in_file = next((b for b in batches_file if b["batch_id"] == batch_final), None)
        assert_true(batch_in_file is not None, "批次记录在 JSON 文件中存在")
        assert_equal(batch_in_file["status"], "rolled_back", "JSON 文件中批次状态正确")

        section("测试19: 多个批次按时间倒序排列")
        clear_data()
        stop_server(proc)
        proc = start_server()

        snap_1 = create_test_snapshot("ORDER-1", "R-ORDER1", "BL-ORDER1")
        r1, _ = api("POST", "/api/snapshot/import?dry_run=false", snap_1)
        batch1 = r1["batch_id"]
        time.sleep(1)

        snap_2 = create_test_snapshot("ORDER-2", "R-ORDER2", "BL-ORDER2")
        r2, _ = api("POST", "/api/snapshot/import?dry_run=false", snap_2)
        batch2 = r2["batch_id"]
        time.sleep(1)

        snap_3 = create_test_snapshot("ORDER-3", "R-ORDER3", "BL-ORDER3")
        r3, _ = api("POST", "/api/snapshot/import?dry_run=false", snap_3)
        batch3 = r3["batch_id"]

        r_list, _ = api("GET", "/api/batches")
        assert_equal(len(r_list["data"]), 3, "有 3 个批次")
        assert_equal(r_list["data"][0]["batch_id"], batch3, "第一个是最新的批次")
        assert_equal(r_list["data"][1]["batch_id"], batch2, "第二个是中间的批次")
        assert_equal(r_list["data"][2]["batch_id"], batch1, "第三个是最早的批次")

        section("测试20: 批次 limit 参数")
        r_limit, _ = api("GET", "/api/batches?limit=2")
        assert_equal(len(r_limit["data"]), 2, "limit=2 时返回 2 条")
        assert_equal(r_limit["data"][0]["batch_id"], batch3, "最新的在前")

        print("\n" + "="*60)
        print("  所有测试通过 ✓")
        print("="*60)

    finally:
        stop_server(proc)


if __name__ == "__main__":
    main()

import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
import hashlib
import shutil

BASE = "http://127.0.0.1:5000"
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_DIR, "data")
SANDBOX_DIR = os.path.join(PROJECT_DIR, "sandbox")


def api(method, path, body=None):
    url = f"{BASE}{path}"
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json; charset=utf-8")
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode("utf-8")
            if not raw.strip():
                return {}, resp.status
            return json.loads(raw), resp.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        if not raw.strip():
            return {}, e.code
        return json.loads(raw), e.code


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


def clear_sandbox():
    if os.path.isdir(SANDBOX_DIR):
        shutil.rmtree(SANDBOX_DIR, ignore_errors=True)
    os.makedirs(SANDBOX_DIR, exist_ok=True)
    print("  [INFO] 已清空 sandbox/ 目录")


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


def get_file_hash(filename, base_dir=None):
    if base_dir is None:
        base_dir = DATA_DIR
    p = os.path.join(base_dir, filename)
    if not os.path.exists(p):
        return None
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def get_file_mtime(filename, base_dir=None):
    if base_dir is None:
        base_dir = DATA_DIR
    p = os.path.join(base_dir, filename)
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
    section("导入演练沙箱完整回归测试 (demo10)")

    print("\n[准备] 清空数据、沙箱目录并启动服务")
    clear_data()
    clear_sandbox()
    proc = start_server()

    sandbox_id_1 = None
    sandbox_id_2 = None

    try:
        section("测试1: 创建演练沙箱 API 存在")
        snapshot = create_test_snapshot("SANDBOX-A")
        r, status = api("POST", "/api/sandbox", {"snapshot": snapshot, "name": "测试演练A"})
        assert_equal(status, 201, "POST /api/sandbox 返回 201")
        assert_true(r.get("ok"), "响应 ok=true")
        assert_true("data" in r, "响应包含 data")
        data = r["data"]
        sandbox_id_1 = data["sandbox_id"]
        assert_true(sandbox_id_1 and len(sandbox_id_1) > 0, "sandbox_id 非空")
        assert_equal(data["status"], "ready", "初始状态为 ready")
        assert_equal(data["name"], "测试演练A", "名称正确")
        assert_equal(data["snapshot_counts"]["books"], 2, "snapshot_counts.books=2")
        assert_equal(data["snapshot_counts"]["active_reservations"], 2, "snapshot_counts.active_reservations=2")
        assert_equal(data["snapshot_counts"]["blacklist"], 1, "snapshot_counts.blacklist=1")
        assert_equal(data["snapshot_counts"]["logs"], 2, "snapshot_counts.logs=2")
        assert_true("snapshot_hash" in data, "包含 snapshot_hash")
        print(f"  [INFO] 创建的沙箱ID: {sandbox_id_1}")

        section("测试2: 沙箱目录与数据隔离 - 正式 data/ 未被污染")
        prod_books = api("GET", "/api/books")[0]["data"]
        assert_equal(len(prod_books), 0, "正式环境 books 仍为空（沙箱隔离）")
        prod_queues = api("GET", "/api/queue/SANDBOX-A-001")[0]
        assert_true(prod_queues.get("ok"), "正式环境队列查询正常返回")
        assert_equal(len(prod_queues.get("data", [])), 0, "正式环境预约队列为空")
        prod_bl = api("GET", "/api/blacklist")[0]["data"]
        assert_equal(len(prod_bl), 0, "正式环境黑名单为空")
        prod_logs = api("GET", "/api/logs?limit=1000")[0]["data"]
        sandbox_log_count = sum(1 for l in prod_logs if l.get("book_id") and l["book_id"].startswith("SANDBOX-"))
        assert_equal(sandbox_log_count, 0, "正式环境 logs 无沙箱相关业务日志")
        prod_batches = api("GET", "/api/batches")[0]["data"]
        assert_equal(len(prod_batches), 0, "正式环境 batches 为空")

        section("测试3: 相同快照重复创建被拦截")
        r2, status2 = api("POST", "/api/sandbox", {"snapshot": snapshot, "name": "重复尝试"})
        assert_equal(status2, 409, "相同快照重复创建返回 409")
        assert_true(not r2.get("ok"), "响应 ok=false")
        assert_true("已存在相同快照" in str(r2.get("error", "")), "错误信息说明重复")

        section("测试4: 沙箱列表 API")
        r_list, _ = api("GET", "/api/sandbox")
        assert_true(r_list.get("ok"), "列表 API ok=true")
        assert_equal(len(r_list["data"]), 1, "沙箱列表有 1 条记录")
        assert_equal(r_list["data"][0]["sandbox_id"], sandbox_id_1, "列表中的 sandbox_id 匹配")
        assert_equal(r_list["data"][0]["status"], "ready", "列表中状态为 ready")
        assert_true("config_stale" in r_list["data"][0], "列表包含 config_stale 字段")
        assert_equal(r_list["data"][0]["config_stale"], False, "配置未过期")

        section("测试5: 沙箱详情 API")
        r_detail, s_detail = api("GET", f"/api/sandbox/{sandbox_id_1}")
        assert_equal(s_detail, 200, "详情 API 返回 200")
        assert_true(r_detail.get("ok"), "详情 ok=true")
        detail = r_detail["data"]
        assert_equal(detail["sandbox_id"], sandbox_id_1, "详情 sandbox_id 匹配")
        assert_true("drill_results" in detail, "包含 drill_results")
        assert_true("data_counts" in detail, "包含 data_counts")
        assert_equal(detail["data_counts"]["books"], 0, "沙箱初始 books 数量为 0")
        assert_equal(detail["data_counts"]["reservations"], 0, "沙箱初始 reservations 数量为 0")
        assert_equal(detail["data_counts"]["blacklist"], 0, "沙箱初始 blacklist 数量为 0")
        assert_equal(detail["data_counts"]["logs"], 1, "沙箱 logs 有 1 条创建日志")
        assert_equal(detail["data_counts"]["batches"], 0, "沙箱 batches 数量为 0")

        section("测试6: 沙箱预检 API")
        books_before_hash = get_file_hash("books.json")
        logs_before_hash = get_file_hash("logs.json")
        batches_before_hash = get_file_hash("batches.json")

        r_pre, s_pre = api("POST", f"/api/sandbox/{sandbox_id_1}/precheck")
        assert_equal(s_pre, 200, "预检返回 200")
        assert_true(r_pre.get("ok"), "预检 ok=true")
        pre_report = r_pre["data"]
        assert_true("can_import" in pre_report, "预检报告包含 can_import")
        assert_equal(pre_report["can_import"], True, "预检 can_import=true")
        assert_equal(pre_report["summary"]["status"], "ready", "预检状态为 ready")
        assert_equal(pre_report["summary"]["total_will_add"], 7, "will_add 共 7 条 (2+2+1+2)")
        assert_equal(len(pre_report["details"]["books"]["will_add"]), 2, "books.will_add=2")
        assert_equal(len(pre_report["details"]["active_reservations"]["will_add"]), 2, "reservations.will_add=2")
        assert_equal(len(pre_report["details"]["blacklist"]["will_add"]), 1, "blacklist.will_add=1")

        assert_equal(get_file_hash("books.json"), books_before_hash, "预检不污染正式 books.json")
        assert_equal(get_file_hash("logs.json"), logs_before_hash, "预检不污染正式 logs.json")
        assert_equal(get_file_hash("batches.json"), batches_before_hash, "预检不污染正式 batches.json")

        r_detail2, _ = api("GET", f"/api/sandbox/{sandbox_id_1}")
        assert_true(r_detail2["data"]["drill_results"]["precheck_report"] is not None, "预检结果已落盘到 drill_results")

        section("测试7: 沙箱 Dry-Run API")
        r_dry, s_dry = api("POST", f"/api/sandbox/{sandbox_id_1}/dryrun")
        assert_equal(s_dry, 200, "Dry-Run 返回 200")
        assert_true(r_dry.get("ok"), "Dry-Run ok=true")
        dry_data = r_dry["data"]
        assert_true("counts" in dry_data, "包含 counts")
        assert_equal(dry_data["counts"]["books"], 2, "counts.books=2")
        assert_true("report" in dry_data, "包含 report")
        assert_equal(dry_data["report"]["can_import"], True, "Dry-Run report.can_import=true")

        prod_books_after_dry = api("GET", "/api/books")[0]["data"]
        assert_equal(len(prod_books_after_dry), 0, "Dry-Run 后正式 books 仍为空")

        r_detail3, _ = api("GET", f"/api/sandbox/{sandbox_id_1}")
        assert_true(r_detail3["data"]["drill_results"]["dryrun_report"] is not None, "Dry-Run 结果已落盘")

        section("测试8: 沙箱正式导入 API")
        books_before_imp_hash = get_file_hash("books.json")
        logs_before_imp_hash = get_file_hash("logs.json")
        batches_before_imp_hash = get_file_hash("batches.json")
        reservations_before_hash = get_file_hash("reservations.json")
        blacklist_before_hash = get_file_hash("blacklist.json")

        r_imp, s_imp = api("POST", f"/api/sandbox/{sandbox_id_1}/import")
        assert_equal(s_imp, 200, "正式导入返回 200")
        assert_true(r_imp.get("ok"), "正式导入 ok=true")
        imp_data = r_imp["data"]
        assert_equal(imp_data["counts"]["books"], 2, "导入 counts.books=2")
        assert_true("batch_id" in imp_data, "返回 batch_id")
        assert_true("report" in imp_data, "返回 report")
        print(f"  [INFO] 沙箱内部批次ID: {imp_data['batch_id']}")

        assert_equal(get_file_hash("books.json"), books_before_imp_hash, "沙箱导入不污染正式 books.json")
        assert_equal(get_file_hash("logs.json"), logs_before_imp_hash, "沙箱导入不污染正式 logs.json")
        assert_equal(get_file_hash("batches.json"), batches_before_imp_hash, "沙箱导入不污染正式 batches.json")
        assert_equal(get_file_hash("reservations.json"), reservations_before_hash, "沙箱导入不污染正式 reservations.json")
        assert_equal(get_file_hash("blacklist.json"), blacklist_before_hash, "沙箱导入不污染正式 blacklist.json")

        prod_books_after_imp = api("GET", "/api/books")[0]["data"]
        assert_equal(len(prod_books_after_imp), 0, "沙箱导入后正式 books 仍为空")
        prod_batches_after = api("GET", "/api/batches")[0]["data"]
        assert_equal(len(prod_batches_after), 0, "沙箱导入后正式 batches 仍为空")

        r_detail4, _ = api("GET", f"/api/sandbox/{sandbox_id_1}")
        assert_equal(r_detail4["data"]["status"], "imported", "导入后沙箱状态为 imported")
        assert_equal(r_detail4["data"]["data_counts"]["books"], 2, "沙箱内 books 数量=2")
        assert_equal(r_detail4["data"]["data_counts"]["reservations"], 2, "沙箱内 reservations 数量=2")
        assert_equal(r_detail4["data"]["data_counts"]["blacklist"], 1, "沙箱内 blacklist 数量=1")
        assert_equal(r_detail4["data"]["data_counts"]["batches"], 1, "沙箱内 batches 数量=1")
        dr = r_detail4["data"]["drill_results"]
        assert_equal(dr["final_conclusion"], "imported_success", "final_conclusion=imported_success")
        assert_true(dr["import_report"] is not None, "import_report 已落盘")
        assert_equal(dr["imported_counts"]["books"], 2, "imported_counts.books=2")

        section("测试9: 沙箱回滚 API")
        r_rb, s_rb = api("POST", f"/api/sandbox/{sandbox_id_1}/rollback")
        assert_equal(s_rb, 200, "回滚返回 200")
        assert_true(r_rb.get("ok"), "回滚 ok=true")
        assert_equal(r_rb.get("already_rolled_back"), False, "首次回滚 already_rolled_back=false")
        assert_true(r_rb.get("rollback_count", 0) > 0, "rollback_count > 0")

        prod_books_after_rb = api("GET", "/api/books")[0]["data"]
        assert_equal(len(prod_books_after_rb), 0, "回滚后正式 books 仍为空")

        r_detail5, _ = api("GET", f"/api/sandbox/{sandbox_id_1}")
        assert_equal(r_detail5["data"]["status"], "rolled_back", "回滚后沙箱状态为 rolled_back")
        assert_equal(r_detail5["data"]["data_counts"]["books"], 0, "回滚后沙箱 books=0")
        assert_equal(r_detail5["data"]["data_counts"]["reservations"], 0, "回滚后沙箱 reservations=0")
        assert_equal(r_detail5["data"]["data_counts"]["blacklist"], 0, "回滚后沙箱 blacklist=0")
        dr5 = r_detail5["data"]["drill_results"]
        assert_equal(dr5["final_conclusion"], "rolled_back_success", "final_conclusion=rolled_back_success")
        assert_true(dr5["rollback_result"] is not None, "rollback_result 已落盘")

        section("测试10: 沙箱回滚幂等性")
        r_rb2, s_rb2 = api("POST", f"/api/sandbox/{sandbox_id_1}/rollback")
        assert_equal(s_rb2, 200, "第二次回滚也返回 200")
        assert_true(r_rb2.get("ok"), "第二次回滚 ok=true")
        assert_equal(r_rb2.get("already_rolled_back"), True, "第二次回滚 already_rolled_back=true")
        assert_equal(r_rb2.get("rollback_count"), 0, "第二次回滚 rollback_count=0")

        section("测试11: 沙箱重启验证 API")
        r_rv, s_rv = api("POST", f"/api/sandbox/{sandbox_id_1}/restart-verify")
        assert_equal(s_rv, 200, "重启验证返回 200")
        assert_true(r_rv.get("ok"), "重启验证 ok=true")
        rv = r_rv["data"]
        assert_equal(rv["status"], "rolled_back", "验证状态为 rolled_back")
        assert_true("data_counts" in rv, "包含 data_counts")
        assert_true("verified_at" in rv, "包含 verified_at")
        assert_true("config_stale" in rv, "包含 config_stale")

        r_detail6, _ = api("GET", f"/api/sandbox/{sandbox_id_1}")
        assert_true(r_detail6["data"]["drill_results"]["restart_verification"] is not None, "重启验证结果已落盘")

        section("测试12: 沙箱导出演练结果 API")
        r_exp, s_exp = api("GET", f"/api/sandbox/{sandbox_id_1}/export")
        assert_equal(s_exp, 200, "导出返回 200")
        assert_true(r_exp.get("ok"), "导出 ok=true")
        exp = r_exp["data"]
        assert_equal(exp["sandbox_id"], sandbox_id_1, "导出 sandbox_id 正确")
        assert_equal(exp["status"], "rolled_back", "导出状态正确")
        assert_true("snapshot_counts" in exp, "包含 snapshot_counts")
        assert_true("data_counts" in exp, "包含 data_counts")
        assert_true("drill_results" in exp, "包含完整 drill_results")
        assert_equal(exp["drill_results"]["final_conclusion"], "rolled_back_success", "导出结论正确")

        section("测试13: 服务重启后沙箱记录完整保留")
        print("  [INFO] 重启服务中...")
        stop_server(proc)
        proc = start_server()

        r_list_after, _ = api("GET", "/api/sandbox")
        assert_equal(len(r_list_after["data"]), 1, "重启后沙箱列表仍有 1 条记录")
        assert_equal(r_list_after["data"][0]["sandbox_id"], sandbox_id_1, "重启后 sandbox_id 不变")
        assert_equal(r_list_after["data"][0]["status"], "rolled_back", "重启后状态仍为 rolled_back")

        r_detail_after, _ = api("GET", f"/api/sandbox/{sandbox_id_1}")
        assert_equal(r_detail_after["data"]["drill_results"]["final_conclusion"], "rolled_back_success",
                     "重启后 drill_results 完整保留")
        assert_true(r_detail_after["data"]["drill_results"]["import_report"] is not None,
                    "重启后 import_report 仍在")
        assert_true(r_detail_after["data"]["drill_results"]["rollback_result"] is not None,
                    "重启后 rollback_result 仍在")

        section("测试14: 重启后仍可继续查询和操作沙箱")
        r_rv_after, _ = api("POST", f"/api/sandbox/{sandbox_id_1}/restart-verify")
        assert_true(r_rv_after.get("ok"), "重启后重启验证 API 可用")
        assert_equal(r_rv_after["data"]["status"], "rolled_back", "重启后验证状态正确")

        r_exp_after, _ = api("GET", f"/api/sandbox/{sandbox_id_1}/export")
        assert_true(r_exp_after.get("ok"), "重启后导出 API 可用")

        section("测试15: 沙箱销毁 API")
        books_before_destroy = get_file_hash("books.json")
        logs_before_destroy = get_file_hash("logs.json")

        r_del, s_del = api("DELETE", f"/api/sandbox/{sandbox_id_1}")
        assert_equal(s_del, 200, "销毁返回 200")
        assert_true(r_del.get("ok"), "销毁 ok=true")

        r_get, s_get = api("GET", f"/api/sandbox/{sandbox_id_1}")
        assert_equal(s_get, 404, "销毁后查询返回 404")

        r_list_after_del, _ = api("GET", "/api/sandbox")
        assert_equal(len(r_list_after_del["data"]), 0, "销毁后列表为空")

        assert_equal(get_file_hash("books.json"), books_before_destroy, "销毁不影响正式 books.json")
        assert_equal(get_file_hash("logs.json"), logs_before_destroy, "销毁不影响正式 logs.json")

        sandbox_path = os.path.join(SANDBOX_DIR, sandbox_id_1)
        assert_true(not os.path.isdir(sandbox_path), "销毁后沙箱目录已删除")

        section("测试16: 正式配置切换后旧沙箱不可误用")
        snapshot_b = create_test_snapshot("CFG-STALE")
        r_sb, s_sb = api("POST", "/api/sandbox", {"snapshot": snapshot_b, "name": "配置过期测试"})
        assert_equal(s_sb, 201, "创建沙箱B成功")
        sandbox_id_b = r_sb["data"]["sandbox_id"]
        assert_equal(r_sb["data"]["config_stale"], False, "初始 config_stale=false")

        api("POST", "/api/books", {
            "book_id": "PROD-BOOK-001",
            "title": "正式环境新增的书",
            "total_copies": 5,
            "borrow_days": 30,
            "retain_hours": 24,
        })

        r_detail_b, _ = api("GET", f"/api/sandbox/{sandbox_id_b}")
        assert_equal(r_detail_b["data"]["config_stale"], True, "正式配置变更后 config_stale=true")
        assert_true("config_stale_detail" in r_detail_b["data"], "包含 config_stale_detail")

        r_pre_b, s_pre_b = api("POST", f"/api/sandbox/{sandbox_id_b}/precheck")
        assert_equal(s_pre_b, 410, "配置过期后预检返回 410")
        assert_true(r_pre_b.get("config_stale"), "响应标记 config_stale=true")
        assert_true("配置已变更" in str(r_pre_b.get("error", "")), "错误信息提示配置变更")

        r_dry_b, s_dry_b = api("POST", f"/api/sandbox/{sandbox_id_b}/dryrun")
        assert_equal(s_dry_b, 410, "配置过期后 Dry-Run 返回 410")
        assert_true(r_dry_b.get("config_stale"), "响应标记 config_stale=true")

        r_imp_b, s_imp_b = api("POST", f"/api/sandbox/{sandbox_id_b}/import")
        assert_equal(s_imp_b, 410, "配置过期后导入返回 410")
        assert_true(r_imp_b.get("config_stale"), "响应标记 config_stale=true")

        api("DELETE", f"/api/sandbox/{sandbox_id_b}")
        api("DELETE", "/api/books/PROD-BOOK-001")

        section("测试17: 带冲突快照的沙箱预检和 dry-run")
        conflict_snapshot = create_test_snapshot("CONFLICT-SB")
        conflict_snapshot["books"].append({
            "book_id": "CONFLICT-SB-001",
            "title": "重复书",
            "total_copies": 3,
            "borrow_days": 14,
            "retain_hours": 12,
        })
        r_sc, s_sc = api("POST", "/api/sandbox", {"snapshot": conflict_snapshot, "name": "冲突测试"})
        assert_equal(s_sc, 201, "冲突快照创建沙箱成功")
        sandbox_id_conflict = r_sc["data"]["sandbox_id"]

        r_prec, s_prec = api("POST", f"/api/sandbox/{sandbox_id_conflict}/precheck")
        assert_equal(s_prec, 200, "冲突快照预检返回 200")
        assert_equal(r_prec["data"]["can_import"], False, "预检 can_import=false")
        assert_equal(r_prec["data"]["summary"]["status"], "has_conflicts", "状态 has_conflicts")
        assert_equal(len(r_prec["data"]["details"]["books"]["conflicts"]), 1, "检测到 1 个 books 冲突")
        assert_equal(r_prec["data"]["details"]["books"]["conflicts"][0]["type"],
                     "duplicate_book_id_in_snapshot", "冲突类型正确")

        r_dryc, s_dryc = api("POST", f"/api/sandbox/{sandbox_id_conflict}/dryrun")
        assert_equal(s_dryc, 409, "冲突快照 Dry-Run 返回 409")
        assert_true("conflicts" in r_dryc, "响应包含 conflicts")
        assert_true(len(r_dryc["conflicts"]) > 0, "冲突列表非空")

        r_impc, s_impc = api("POST", f"/api/sandbox/{sandbox_id_conflict}/import")
        assert_equal(s_impc, 409, "冲突快照导入返回 409")
        assert_true("conflicts" in r_impc, "响应包含 conflicts")

        r_detailc, _ = api("GET", f"/api/sandbox/{sandbox_id_conflict}")
        assert_equal(r_detailc["data"]["status"], "failed", "冲突导入后状态为 failed")
        assert_equal(r_detailc["data"]["drill_results"]["final_conclusion"], "has_conflicts",
                     "final_conclusion=has_conflicts")
        assert_true(len(r_detailc["data"]["drill_results"]["conflicts"]) > 0, "conflicts 已落盘")

        api("DELETE", f"/api/sandbox/{sandbox_id_conflict}")

        section("测试18: 沙箱数据与正式数据完全隔离 - 多沙箱场景")
        snap_x = create_test_snapshot("SB-X")
        snap_y = create_test_snapshot("SB-Y", "R-SBY", "BL-SBY")
        r_x, _ = api("POST", "/api/sandbox", {"snapshot": snap_x, "name": "沙箱X"})
        sandbox_id_x = r_x["data"]["sandbox_id"]
        r_y, _ = api("POST", "/api/sandbox", {"snapshot": snap_y, "name": "沙箱Y"})
        sandbox_id_y = r_y["data"]["sandbox_id"]

        api("POST", f"/api/sandbox/{sandbox_id_x}/import")
        api("POST", f"/api/sandbox/{sandbox_id_y}/import")

        prod_books_multi = api("GET", "/api/books")[0]["data"]
        assert_equal(len(prod_books_multi), 0, "多沙箱导入后正式 books 仍为空")
        prod_logs_multi = api("GET", "/api/logs?limit=1000")[0]["data"]
        sb_log_count = sum(1 for l in prod_logs_multi
                          if l.get("book_id") and (l["book_id"].startswith("SB-X") or l["book_id"].startswith("SB-Y")))
        assert_equal(sb_log_count, 0, "多沙箱日志不串到正式 logs")

        r_dx, _ = api("GET", f"/api/sandbox/{sandbox_id_x}")
        assert_equal(r_dx["data"]["data_counts"]["books"], 2, "沙箱X books=2")
        book_ids_x = set()
        for fname in ["books", "reservations", "blacklist"]:
            p = os.path.join(SANDBOX_DIR, sandbox_id_x, f"{fname}.json")
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    items = json.load(f)
                    for it in items:
                        if "book_id" in it:
                            book_ids_x.add(it["book_id"])
        assert_true("SB-X-001" in book_ids_x, "沙箱X目录只有X的数据")
        assert_true("SB-Y-001" not in book_ids_x, "沙箱X目录没有Y的数据")

        api("DELETE", f"/api/sandbox/{sandbox_id_x}")
        r_dy_after, _ = api("GET", f"/api/sandbox/{sandbox_id_y}")
        assert_equal(r_dy_after["data"]["status"], "imported", "销毁沙箱X不影响沙箱Y")
        assert_equal(r_dy_after["data"]["data_counts"]["books"], 2, "沙箱Y数据仍完整")

        api("DELETE", f"/api/sandbox/{sandbox_id_y}")

        section("测试19: 非法快照格式被拦截")
        bad_snapshot = {"version": "1.0", "type": "wrong_type"}
        r_bad, s_bad = api("POST", "/api/sandbox", {"snapshot": bad_snapshot})
        assert_equal(s_bad, 400, "非法快照格式返回 400")
        assert_true(not r_bad.get("ok"), "响应 ok=false")

        bad_body = {"name": "缺少snapshot字段的请求"}
        r_bad2, s_bad2 = api("POST", "/api/sandbox", bad_body)
        assert_equal(s_bad2, 400, "缺少 snapshot 字段返回 400")

        section("测试20: 不存在的沙箱返回 404")
        r_ng, s_ng = api("GET", "/api/sandbox/nonexistent-id")
        assert_equal(s_ng, 404, "不存在的沙箱详情返回 404")
        r_ng2, s_ng2 = api("POST", "/api/sandbox/nonexistent-id/precheck")
        assert_equal(s_ng2, 404, "不存在的沙箱预检返回 404")
        r_ng3, s_ng3 = api("DELETE", "/api/sandbox/nonexistent-id")
        assert_equal(s_ng3, 404, "不存在的沙箱销毁返回 404")

        section("测试21: 沙箱完整生命周期 - 预检→dry-run→导入→验证→回滚→重启→导出→销毁")
        snap_full = create_test_snapshot("FULL-LC", "R-FULL", "BL-FULL")
        r_full, _ = api("POST", "/api/sandbox", {"snapshot": snap_full, "name": "完整生命周期测试"})
        sb_full_id = r_full["data"]["sandbox_id"]

        api("POST", f"/api/sandbox/{sb_full_id}/precheck")
        api("POST", f"/api/sandbox/{sb_full_id}/dryrun")
        r_imp_full, _ = api("POST", f"/api/sandbox/{sb_full_id}/import")
        assert_equal(r_imp_full.get("ok"), True, "正式导入成功")

        api("POST", f"/api/sandbox/{sb_full_id}/restart-verify")

        print("  [INFO] 重启服务中...")
        stop_server(proc)
        proc = start_server()

        r_detail_full, _ = api("GET", f"/api/sandbox/{sb_full_id}")
        assert_equal(r_detail_full["data"]["status"], "imported", "重启后状态仍为 imported")

        api("POST", f"/api/sandbox/{sb_full_id}/restart-verify")
        api("POST", f"/api/sandbox/{sb_full_id}/rollback")
        r_exp_full, _ = api("GET", f"/api/sandbox/{sb_full_id}/export")
        assert_equal(r_exp_full["data"]["drill_results"]["final_conclusion"], "rolled_back_success",
                     "完整生命周期最终结论正确")
        assert_true(r_exp_full["data"]["drill_results"]["precheck_report"] is not None, "precheck_report 存在")
        assert_true(r_exp_full["data"]["drill_results"]["dryrun_report"] is not None, "dryrun_report 存在")
        assert_true(r_exp_full["data"]["drill_results"]["import_report"] is not None, "import_report 存在")
        assert_true(r_exp_full["data"]["drill_results"]["rollback_result"] is not None, "rollback_result 存在")
        assert_true(r_exp_full["data"]["drill_results"]["restart_verification"] is not None, "restart_verification 存在")

        api("DELETE", f"/api/sandbox/{sb_full_id}")

        section("测试22: 沙箱演练结果独立落盘，不串正式环境")
        snap_sep = create_test_snapshot("SEPARATE")
        r_sep, _ = api("POST", "/api/sandbox", {"snapshot": snap_sep, "name": "独立落盘测试"})
        sb_sep_id = r_sep["data"]["sandbox_id"]
        api("POST", f"/api/sandbox/{sb_sep_id}/import")

        drill_path = os.path.join(SANDBOX_DIR, sb_sep_id, "drill_results.json")
        assert_true(os.path.exists(drill_path), "drill_results.json 存在于沙箱目录")
        with open(drill_path, "r", encoding="utf-8") as f:
            drill_file = json.load(f)
        assert_equal(drill_file["final_conclusion"], "imported_success", "文件中 final_conclusion 正确")
        assert_true(drill_file["imported_counts"] is not None, "文件中 imported_counts 存在")
        assert_true(drill_file["conflicts"] is not None, "文件中 conflicts 存在")

        prod_batches_file = os.path.join(DATA_DIR, "batches.json")
        if os.path.exists(prod_batches_file):
            with open(prod_batches_file, "r", encoding="utf-8") as f:
                prod_batches_data = json.load(f)
            sb_batch_count = sum(1 for b in prod_batches_data if b.get("type") == "sandbox_snapshot_import")
            assert_equal(sb_batch_count, 0, "正式 batches.json 不含沙箱批次")

        api("DELETE", f"/api/sandbox/{sb_sep_id}")

        section("测试23: 沙箱 limit 参数")
        for i in range(5):
            snap_i = create_test_snapshot(f"LIMIT-{i}")
            api("POST", "/api/sandbox", {"snapshot": snap_i, "name": f"limit测试{i}"})

        r_lim, _ = api("GET", "/api/sandbox?limit=3")
        assert_equal(len(r_lim["data"]), 3, "limit=3 返回 3 条")

        for sb in r_lim["data"]:
            api("DELETE", f"/api/sandbox/{sb['sandbox_id']}")
        r_all, _ = api("GET", "/api/sandbox")
        for sb in r_all["data"]:
            api("DELETE", f"/api/sandbox/{sb['sandbox_id']}")

        section("测试24: 已导入沙箱不能重复导入")
        snap_no_dup = create_test_snapshot("NO-DUP-IMP")
        r_nd, _ = api("POST", "/api/sandbox", {"snapshot": snap_no_dup, "name": "不重复导入测试"})
        sb_nd_id = r_nd["data"]["sandbox_id"]
        api("POST", f"/api/sandbox/{sb_nd_id}/import")

        r_nd2, s_nd2 = api("POST", f"/api/sandbox/{sb_nd_id}/import")
        assert_equal(s_nd2, 409, "重复导入返回 409")
        assert_true("已执行过正式导入" in str(r_nd2.get("error", "")), "错误信息说明已导入")

        api("DELETE", f"/api/sandbox/{sb_nd_id}")

        print("\n" + "="*60)
        print("  所有测试通过 ✓")
        print("="*60)

    finally:
        stop_server(proc)


if __name__ == "__main__":
    main()

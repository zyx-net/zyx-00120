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
CHECKUP_DIR = os.path.join(PROJECT_DIR, "checkup")


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
    if os.path.isdir(CHECKUP_DIR):
        for name in ["records", "logs", "conclusions"]:
            p = os.path.join(CHECKUP_DIR, f"{name}.json")
            if os.path.exists(p):
                os.remove(p)
    print("  [INFO] 已清空 data/ 和 checkup/ 目录")


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


def get_data_file_hash(filename):
    p = os.path.join(DATA_DIR, filename)
    if not os.path.exists(p):
        return None
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def create_valid_snapshot(prefix="CHK"):
    return {
        "version": "2.0",
        "type": "full_snapshot",
        "books": [
            {"book_id": f"{prefix}-001", "title": "体检测试书1", "total_copies": 5, "borrow_days": 30, "retain_hours": 24},
            {"book_id": f"{prefix}-002", "title": "体检测试书2", "total_copies": 3, "borrow_days": 14, "retain_hours": 12},
        ],
        "active_reservations": [
            {
                "reservation_id": f"res-{prefix}-001-01",
                "book_id": f"{prefix}-001",
                "reader_id": f"R-{prefix}-001",
                "status": "waiting",
                "created_at": "2026-06-19T08:00:00+00:00",
                "available_at": None,
                "expire_at": None,
                "borrowed_at": None,
                "returned_at": None,
            },
        ],
        "blacklist": [
            {"reader_id": f"BL-{prefix}-001", "reason": "逾期未还", "added_at": "2026-06-18T10:00:00+00:00"},
        ],
        "logs": [
            {
                "log_id": f"log-{prefix}-001",
                "timestamp": "2026-06-19T07:00:00+00:00",
                "action": "add_book",
                "book_id": f"{prefix}-001",
                "detail": "添加书目",
                "success": True,
            },
        ],
    }


def main():
    section("快照体检中心完整回归测试 (demo10)")

    print("\n[准备] 清空数据并启动服务")
    clear_data()
    proc = start_server()

    try:
        section("测试1: 创建体检记录 - 合法快照通过体检")
        snapshot = create_valid_snapshot("PASS")
        r, status = api("POST", "/api/checkup", {"snapshot": snapshot, "operator": "tester", "name": "合法快照体检"})
        assert_equal(status, 201, "创建体检记录返回 201")
        assert_true(r.get("ok"), "响应 ok=true")
        record = r["data"]
        assert_true("record_id" in record, "包含 record_id")
        assert_equal(record["status"], "passed", "体检状态为 passed")
        assert_equal(record["checkup_summary"]["passed"], True, "checkup_summary.passed=true")
        assert_equal(record["checkup_summary"]["total_blocking"], 0, "无阻断项")
        assert_equal(record["operator"], "tester", "操作者正确")
        assert_equal(record["name"], "合法快照体检", "名称正确")
        record_id = record["record_id"]
        print(f"  [INFO] 体检记录ID: {record_id}")

        section("测试2: 查询体检详情 - 只读查看")
        r, status = api("GET", f"/api/checkup/{record_id}")
        assert_equal(status, 200, "查询详情返回 200")
        assert_true(r.get("ok"), "响应 ok=true")
        detail = r["data"]
        assert_equal(detail["record_id"], record_id, "record_id 匹配")
        assert_equal(detail["status"], "passed", "状态为 passed")
        assert_true("conclusion" in detail, "包含 conclusion")
        assert_true("structural_errors" in detail["conclusion"], "conclusion 包含 structural_errors")
        assert_true("required_field_errors" in detail["conclusion"], "conclusion 包含 required_field_errors")
        assert_true("version_warnings" in detail["conclusion"], "conclusion 包含 version_warnings")
        assert_true("sensitive_warnings" in detail["conclusion"], "conclusion 包含 sensitive_warnings")

        section("测试3: 导出 JSON 报告")
        r, status = api("GET", f"/api/checkup/{record_id}/export")
        assert_equal(status, 200, "导出报告返回 200")
        assert_true(r.get("ok"), "响应 ok=true")
        report = r["data"]
        assert_equal(report["record_id"], record_id, "报告 record_id 匹配")
        assert_true("report_id" in report, "报告包含 report_id")
        assert_true("exported_at" in report, "报告包含 exported_at")
        assert_equal(report["config_stale"], False, "配置未过期")
        assert_true("conclusion" in report, "报告包含 conclusion")
        assert_equal(report["conclusion"]["passed"], True, "报告结论为通过")

        section("测试4: 同一快照重复提交被拦截")
        r2, status2 = api("POST", "/api/checkup", {"snapshot": snapshot, "operator": "tester2"})
        assert_equal(status2, 409, "重复提交返回 409")
        assert_true("已存在" in r2.get("error", ""), "错误信息提示已存在")

        section("测试5: 结构校验失败 - 缺少 version")
        bad_snapshot = create_valid_snapshot("BAD1")
        del bad_snapshot["version"]
        r, status = api("POST", "/api/checkup", {"snapshot": bad_snapshot})
        assert_equal(status, 201, "结构错误也创建记录（状态为 failed）")
        record_failed = r["data"]
        assert_equal(record_failed["status"], "failed", "体检状态为 failed")
        assert_equal(record_failed["checkup_summary"]["passed"], False, "checkup_summary.passed=false")
        assert_true(record_failed["checkup_summary"]["total_blocking"] > 0, "有阻断项")
        failed_id = record_failed["record_id"]

        detail_failed, _ = api("GET", f"/api/checkup/{failed_id}")
        struct_errors = detail_failed["data"]["conclusion"]["structural_errors"]
        assert_true(len(struct_errors) > 0, "conclusion 包含 structural_errors")
        assert_true(any(e["code"] == "version_mismatch" for e in struct_errors), "包含 version_mismatch 错误")

        section("测试6: 必填字段核对失败 - 缺少 book_id")
        bad_snapshot2 = create_valid_snapshot("BAD2")
        del bad_snapshot2["books"][0]["book_id"]
        r, status = api("POST", "/api/checkup", {"snapshot": bad_snapshot2})
        assert_equal(status, 201, "必填字段缺失也创建记录")
        record_bad2 = r["data"]
        assert_equal(record_bad2["status"], "failed", "体检状态为 failed")
        detail_bad2, _ = api("GET", f"/api/checkup/{record_bad2['record_id']}")
        required_errors = detail_bad2["data"]["conclusion"]["required_field_errors"]
        assert_true(len(required_errors) > 0, "conclusion 包含 required_field_errors")

        section("测试7: 版本兼容性检查 - 快照导出时间过旧")
        old_snapshot = create_valid_snapshot("OLD")
        old_snapshot["export_time"] = "2020-01-01T00:00:00+00:00"
        r, status = api("POST", "/api/checkup", {"snapshot": old_snapshot, "name": "旧快照"})
        assert_equal(status, 201, "旧快照创建记录")
        record_old = r["data"]
        assert_equal(record_old["status"], "passed", "旧快照仍可通过（告警非阻断）")
        assert_true(record_old["checkup_summary"]["version_warnings"] > 0, "有版本告警")
        detail_old, _ = api("GET", f"/api/checkup/{record_old['record_id']}")
        version_warnings = detail_old["data"]["conclusion"]["version_warnings"]
        assert_true(any(w["code"] == "snapshot_too_old" for w in version_warnings), "包含 snapshot_too_old 告警")

        section("测试8: 敏感配置检查 - total_copies=0 和 borrow_days=0")
        sensitive_snapshot = create_valid_snapshot("SENS")
        sensitive_snapshot["books"][0]["total_copies"] = 0
        sensitive_snapshot["books"][1]["borrow_days"] = 0
        r, status = api("POST", "/api/checkup", {"snapshot": sensitive_snapshot})
        assert_equal(status, 201, "敏感配置创建记录")
        record_sens = r["data"]
        assert_equal(record_sens["status"], "failed", "total_copies=0 导致体检失败")
        assert_true(record_sens["checkup_summary"]["sensitive_errors"] > 0, "有敏感配置错误")
        detail_sens, _ = api("GET", f"/api/checkup/{record_sens['record_id']}")
        sensitive_errors = detail_sens["data"]["conclusion"]["sensitive_errors"]
        sensitive_codes = [w["code"] for w in sensitive_errors]
        assert_true("sensitive_total_copies" in sensitive_codes, "包含 sensitive_total_copies")
        assert_true("sensitive_borrow_days" in sensitive_codes, "包含 sensitive_borrow_days")

        section("测试9: 手动作废体检记录")
        void_id = record_old["record_id"]
        r_void, status_void = api("POST", f"/api/checkup/{void_id}/void", {"operator": "admin"})
        assert_equal(status_void, 200, "作废返回 200")
        assert_true(r_void.get("ok"), "作废成功 ok=true")
        voided = r_void["data"]
        assert_equal(voided["status"], "voided", "状态变为 voided")
        assert_equal(voided["voided_by"], "admin", "作废操作者正确")
        assert_true("voided_at" in voided, "包含 voided_at")

        section("测试10: 重复作废被拦截")
        r_void2, status_void2 = api("POST", f"/api/checkup/{void_id}/void", {"operator": "admin"})
        assert_equal(status_void2, 409, "重复作废返回 409")
        assert_true("已作废" in r_void2.get("error", ""), "错误信息提示已作废")

        section("测试11: 查询不存在的记录返回 404")
        r, status = api("GET", "/api/checkup/nonexistent-id")
        assert_equal(status, 404, "查询不存在记录返回 404")

        section("测试12: 导出不存在的记录返回 404")
        r, status = api("GET", "/api/checkup/nonexistent-id/export")
        assert_equal(status, 404, "导出不存在记录返回 404")

        section("测试13: 作废不存在的记录返回 404")
        r, status = api("POST", "/api/checkup/nonexistent-id/void")
        assert_equal(status, 404, "作废不存在记录返回 404")

        section("测试14: 体检列表按时间倒序")
        r_list, status = api("GET", "/api/checkup")
        assert_equal(status, 200, "列表返回 200")
        assert_true(len(r_list["data"]) >= 4, "列表至少有 4 条记录")
        timestamps = [rec["created_at"] for rec in r_list["data"]]
        assert_true(timestamps == sorted(timestamps, reverse=True), "按时间倒序排列")

        section("测试15: 体检日志和结论单独落盘，不混入正式数据")
        prod_logs_before = api("GET", "/api/logs?limit=10000")[0]["data"]
        prod_log_ids = {l["log_id"] for l in prod_logs_before}

        new_snapshot = create_valid_snapshot("ISOLATE")
        r, _ = api("POST", "/api/checkup", {"snapshot": new_snapshot, "operator": "isolate-tester"})

        prod_logs_after = api("GET", "/api/logs?limit=10000")[0]["data"]
        prod_log_ids_after = {l["log_id"] for l in prod_logs_after}
        new_prod_log_ids = prod_log_ids_after - prod_log_ids
        checkup_log_count = sum(1 for lid in new_prod_log_ids
                                if any(l["log_id"] == lid and "checkup" in l.get("action", "")
                                       for l in prod_logs_after))
        assert_equal(checkup_log_count, 0, "体检日志不出现在正式操作日志中")

        checkup_logs_file = os.path.join(CHECKUP_DIR, "logs.json")
        assert_true(os.path.exists(checkup_logs_file), "checkup/logs.json 文件存在")
        with open(checkup_logs_file, "r", encoding="utf-8") as f:
            checkup_logs = json.load(f)
        assert_true(len(checkup_logs) > 0, "体检日志文件非空")

        checkup_conclusions_file = os.path.join(CHECKUP_DIR, "conclusions.json")
        assert_true(os.path.exists(checkup_conclusions_file), "checkup/conclusions.json 文件存在")
        with open(checkup_conclusions_file, "r", encoding="utf-8") as f:
            checkup_conclusions = json.load(f)
        assert_true(len(checkup_conclusions) > 0, "体检结论文件非空")

        section("测试16: 失败体检不污染正式数据")
        data_before = {}
        for fname in ["books", "reservations", "blacklist", "logs"]:
            data_before[fname] = get_data_file_hash(f"{fname}.json")

        bad_snap = {
            "version": "1.0",
            "type": "not_snapshot",
        }
        r_bad, _ = api("POST", "/api/checkup", {"snapshot": bad_snap})
        assert_equal(r_bad["data"]["status"], "failed", "错误快照体检失败")

        for fname, old_hash in data_before.items():
            assert_equal(get_data_file_hash(f"{fname}.json"), old_hash,
                         f"体检失败后 {fname}.json 未被修改")

        section("测试17: 服务重启后体检记录可继续查询")
        all_records = api("GET", "/api/checkup")[0]["data"]
        first_record_id = all_records[0]["record_id"]

        print("  [INFO] 重启服务中...")
        stop_server(proc)
        proc = start_server()

        r_after, status_after = api("GET", f"/api/checkup/{first_record_id}")
        assert_equal(status_after, 200, "重启后查询返回 200")
        assert_equal(r_after["data"]["record_id"], first_record_id, "重启后 record_id 匹配")
        assert_true("conclusion" in r_after["data"], "重启后 conclusion 仍在")

        r_list_after, _ = api("GET", "/api/checkup")
        assert_true(len(r_list_after["data"]) >= 4, "重启后列表至少有 4 条记录")

        r_export_after, _ = api("GET", f"/api/checkup/{first_record_id}/export")
        assert_equal(r_export_after["data"]["record_id"], first_record_id, "重启后导出 record_id 匹配")

        section("测试18: 配置切换后旧记录自动失效")
        clear_data()
        stop_server(proc)
        proc = start_server()

        snap_before = create_valid_snapshot("BEFORE")
        r1, _ = api("POST", "/api/checkup", {"snapshot": snap_before, "operator": "cfg-tester"})
        before_id = r1["data"]["record_id"]
        assert_equal(r1["data"]["status"], "passed", "切换前体检通过")

        api("POST", "/api/books", {
            "book_id": "NEW-BOOK",
            "title": "配置切换新书",
            "total_copies": 10,
            "borrow_days": 30,
            "retain_hours": 24,
        })

        print("  [INFO] 重启服务（触发配置变更检测）...")
        stop_server(proc)
        proc = start_server()

        r_check, _ = api("GET", f"/api/checkup/{before_id}")
        assert_equal(r_check["data"]["status"], "expired", "配置切换后旧记录状态变为 expired")
        assert_true(r_check["data"].get("config_stale"), "config_stale=true")

        r_export_stale, _ = api("GET", f"/api/checkup/{before_id}/export")
        assert_true("stale_warning" in r_export_stale["data"], "导出报告包含过期警告")

        section("测试19: 作废后同一快照可重新提交")
        snap_resubmit = create_valid_snapshot("RESUB")
        r_resub1, _ = api("POST", "/api/checkup", {"snapshot": snap_resubmit})
        resub_id = r_resub1["data"]["record_id"]

        r_resub_void, _ = api("POST", f"/api/checkup/{resub_id}/void", {"operator": "admin"})
        assert_equal(r_resub_void["data"]["status"], "voided", "作废成功")

        r_resub2, status2 = api("POST", "/api/checkup", {"snapshot": snap_resubmit})
        assert_equal(status2, 201, "作废后可重新提交")
        assert_true(r_resub2["data"]["record_id"] != resub_id, "新记录ID不同于旧记录")

        section("测试20: 权限区分 - 只读查看 vs 作废操作")
        snap_perm = create_valid_snapshot("PERM")
        r_perm, _ = api("POST", "/api/checkup", {"snapshot": snap_perm, "operator": "creator"})
        perm_id = r_perm["data"]["record_id"]

        r_view, status_view = api("GET", f"/api/checkup/{perm_id}")
        assert_equal(status_view, 200, "只读查看返回 200")
        assert_equal(r_view["data"]["status"], "passed", "查看不影响状态")

        r_export_perm, status_export = api("GET", f"/api/checkup/{perm_id}/export")
        assert_equal(status_export, 200, "导出报告返回 200")
        assert_equal(r_export_perm["data"]["status"], "passed", "导出报告不影响状态")

        r_void_perm, status_void = api("POST", f"/api/checkup/{perm_id}/void", {"operator": "voider"})
        assert_equal(status_void, 200, "作废操作返回 200")
        assert_equal(r_void_perm["data"]["status"], "voided", "作废改变状态")
        assert_equal(r_void_perm["data"]["voided_by"], "voider", "作废记录操作者")

        section("测试21: 并发占用 - 同一快照快速提交两次")
        snap_concurrent = create_valid_snapshot("CONC")
        r_conc1, _ = api("POST", "/api/checkup", {"snapshot": snap_concurrent})
        assert_true(r_conc1.get("ok"), "第一次提交成功")

        r_conc2, status_conc2 = api("POST", "/api/checkup", {"snapshot": snap_concurrent})
        assert_equal(status_conc2, 409, "并发提交同一快照返回 409")

        section("测试22: 体检记录 limit 参数")
        r_limit, _ = api("GET", "/api/checkup?limit=2")
        assert_true(len(r_limit["data"]) <= 2, "limit=2 时最多返回 2 条")

        section("测试23: 缺少 snapshot 字段返回 400")
        r_no_snap, status_no = api("POST", "/api/checkup", {"operator": "tester"})
        assert_equal(status_no, 400, "缺少 snapshot 返回 400")

        section("测试24: 保留时间=0 的敏感配置告警")
        retain_zero_snapshot = create_valid_snapshot("RH0")
        retain_zero_snapshot["books"][0]["retain_hours"] = 0
        r_rh0, _ = api("POST", "/api/checkup", {"snapshot": retain_zero_snapshot})
        detail_rh0, _ = api("GET", f"/api/checkup/{r_rh0['data']['record_id']}")
        sensitive_warns = detail_rh0["data"]["conclusion"]["sensitive_warnings"]
        has_retain_zero = any(w["code"] == "sensitive_retain_hours" for w in sensitive_warns)
        assert_true(has_retain_zero, "retain_hours=0 触发 sensitive_retain_hours 告警")

        section("测试25: 完整链路 - 创建→查询→导出→作废→重新提交")
        snap_e2e = create_valid_snapshot("E2E")
        r_e2e_create, _ = api("POST", "/api/checkup", {"snapshot": snap_e2e, "operator": "e2e-user", "name": "端到端测试"})
        e2e_id = r_e2e_create["data"]["record_id"]
        assert_equal(r_e2e_create["data"]["status"], "passed", "创建状态 passed")

        r_e2e_get, _ = api("GET", f"/api/checkup/{e2e_id}")
        assert_equal(r_e2e_get["data"]["status"], "passed", "查询状态 passed")
        assert_true("conclusion" in r_e2e_get["data"], "查询包含 conclusion")

        r_e2e_export, _ = api("GET", f"/api/checkup/{e2e_id}/export")
        assert_true("report_id" in r_e2e_export["data"], "导出包含 report_id")
        assert_equal(r_e2e_export["data"]["name"], "端到端测试", "导出名称正确")

        r_e2e_void, _ = api("POST", f"/api/checkup/{e2e_id}/void", {"operator": "e2e-admin"})
        assert_equal(r_e2e_void["data"]["status"], "voided", "作废成功")

        r_e2e_resub, _ = api("POST", "/api/checkup", {"snapshot": snap_e2e})
        assert_equal(r_e2e_resub["data"]["status"], "passed", "重新提交成功")

        print("\n" + "="*60)
        print("  所有测试通过 ✓")
        print("="*60)

    finally:
        stop_server(proc)


if __name__ == "__main__":
    main()

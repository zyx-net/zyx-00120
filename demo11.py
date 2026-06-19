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
REMIND_DIR = os.path.join(PROJECT_DIR, "remind")


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
    if os.path.isdir(REMIND_DIR):
        for name in ["orders", "logs"]:
            p = os.path.join(REMIND_DIR, f"{name}.json")
            if os.path.exists(p):
                os.remove(p)
    print("  [INFO] 已清空 data/ 和 remind/ 目录")


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


def main():
    section("预约履约催办中心完整回归测试 (demo11)")

    print("\n[准备] 清空数据并启动服务")
    clear_data()
    proc = start_server()

    try:
        section("测试1: 创建催办单 - 逾期未取 (overdue_pickup)")
        api("POST", "/api/books", {
            "book_id": "RM-B001", "title": "催办测试书1",
            "total_copies": 2, "borrow_days": 14, "retain_hours": 24,
        })
        r_res, _ = api("POST", "/api/reserve", {"book_id": "RM-B001", "reader_id": "RM-R001"})
        reservation_id = r_res["data"]["reservation_id"]
        r, status = api("POST", "/api/remind", {
            "reservation_id": reservation_id,
            "trigger_reason": "overdue_pickup",
            "operator": "admin1",
            "remark": "逾期3天未取书",
        })
        assert_equal(status, 201, "创建催办单返回 201")
        assert_true(r.get("ok"), "响应 ok=true")
        order = r["data"]
        assert_true("order_id" in order, "包含 order_id")
        assert_equal(order["status"], "pending", "催办单状态为 pending")
        assert_equal(order["trigger_reason"], "overdue_pickup", "触发原因为 overdue_pickup")
        assert_equal(order["operator"], "admin1", "操作者正确")
        assert_equal(order["remark"], "逾期3天未取书", "备注正确")
        assert_equal(order["reservation_id"], reservation_id, "预约ID匹配")
        assert_equal(order["book_id"], "RM-B001", "书目ID匹配")
        assert_equal(order["reader_id"], "RM-R001", "读者ID匹配")
        assert_true(len(order["timeline"]) >= 1, "时间线至少有1条")
        assert_equal(order["timeline"][0]["event"], "created", "时间线首条事件为 created")
        order_id = order["order_id"]
        print(f"  [INFO] 催办单ID: {order_id}")

        section("测试2: 同一预约重复催办被拦截")
        r_dup, status_dup = api("POST", "/api/remind", {
            "reservation_id": reservation_id,
            "trigger_reason": "manual",
            "operator": "admin2",
        })
        assert_equal(status_dup, 409, "重复催办返回 409")
        assert_true("已存在" in r_dup.get("error", ""), "错误信息提示已存在")

        section("测试3: 查看催办详情 - 只读查看")
        r_detail, status_detail = api("GET", f"/api/remind/{order_id}")
        assert_equal(status_detail, 200, "查看详情返回 200")
        assert_true(r_detail.get("ok"), "响应 ok=true")
        detail = r_detail["data"]
        assert_equal(detail["order_id"], order_id, "order_id 匹配")
        assert_equal(detail["status"], "pending", "状态仍为 pending（只读查看不影响状态）")
        assert_true("timeline" in detail, "包含 timeline")
        assert_equal(detail.get("config_stale"), False, "配置未过期")

        section("测试4: 导出 JSON 报告")
        r_export, status_export = api("GET", f"/api/remind/{order_id}/export")
        assert_equal(status_export, 200, "导出报告返回 200")
        assert_true(r_export.get("ok"), "响应 ok=true")
        report = r_export["data"]
        assert_true("report_id" in report, "报告包含 report_id")
        assert_equal(report["order_id"], order_id, "报告 order_id 匹配")
        assert_equal(report["trigger_reason"], "overdue_pickup", "报告触发原因正确")
        assert_equal(report["operator"], "admin1", "报告处理人正确")
        assert_true("timeline" in report, "报告包含时间线")
        assert_true(len(report["timeline"]) >= 1, "报告时间线至少有1条")
        assert_equal(report["final_status"], "pending", "报告最终状态为 pending")
        assert_equal(report["config_stale"], False, "报告配置未过期")
        assert_true("exported_at" in report, "报告包含导出时间")

        section("测试5: 撤销催办单")
        r_revoke, status_revoke = api("POST", f"/api/remind/{order_id}/revoke", {"operator": "admin2"})
        assert_equal(status_revoke, 200, "撤销返回 200")
        assert_true(r_revoke.get("ok"), "撤销成功 ok=true")
        revoked = r_revoke["data"]
        assert_equal(revoked["status"], "revoked", "状态变为 revoked")
        assert_equal(revoked["revoked_by"], "admin2", "撤销操作者正确")
        assert_true("revoked_at" in revoked, "包含 revoked_at")
        assert_equal(revoked["final_status"], "revoked", "最终状态为 revoked")
        timeline_events = [t["event"] for t in revoked["timeline"]]
        assert_true("revoked" in timeline_events, "时间线包含 revoked 事件")

        section("测试6: 重复撤销被拦截")
        r_revoke2, status_revoke2 = api("POST", f"/api/remind/{order_id}/revoke", {"operator": "admin2"})
        assert_equal(status_revoke2, 409, "重复撤销返回 409")
        assert_true("已撤销" in r_revoke2.get("error", ""), "错误信息提示已撤销")

        section("测试7: 撤销后同一预约可重新催办")
        r_new, status_new = api("POST", "/api/remind", {
            "reservation_id": reservation_id,
            "trigger_reason": "long_waiting",
            "operator": "admin3",
        })
        assert_equal(status_new, 201, "撤销后可重新催办")
        new_order_id = r_new["data"]["order_id"]
        assert_true(new_order_id != order_id, "新催办单ID不同于旧催办单")
        assert_equal(r_new["data"]["trigger_reason"], "long_waiting", "新催办触发原因为 long_waiting")

        section("测试8: 列表筛选 - 按状态筛选")
        r_list_pending, _ = api("GET", "/api/remind?status=pending")
        pending_orders = r_list_pending["data"]
        assert_true(len(pending_orders) >= 1, "至少有1条 pending 催办单")
        for o in pending_orders:
            assert_equal(o["status"], "pending", f"筛选结果状态为 pending: {o['order_id']}")

        r_list_revoked, _ = api("GET", "/api/remind?status=revoked")
        revoked_orders = r_list_revoked["data"]
        assert_true(len(revoked_orders) >= 1, "至少有1条 revoked 催办单")

        section("测试9: 列表筛选 - 按书目和读者筛选")
        r_list_book, _ = api("GET", "/api/remind?book_id=RM-B001")
        book_orders = r_list_book["data"]
        assert_true(len(book_orders) >= 2, "RM-B001 至少有2条催办记录")
        for o in book_orders:
            assert_equal(o["book_id"], "RM-B001", f"按书目筛选结果正确: {o['order_id']}")

        r_list_reader, _ = api("GET", "/api/remind?reader_id=RM-R001")
        reader_orders = r_list_reader["data"]
        assert_true(len(reader_orders) >= 2, "RM-R001 至少有2条催办记录")

        section("测试10: 列表筛选 - 按触发原因筛选")
        r_list_trigger, _ = api("GET", "/api/remind?trigger_reason=long_waiting")
        trigger_orders = r_list_trigger["data"]
        assert_true(len(trigger_orders) >= 1, "long_waiting 至少有1条")
        for o in trigger_orders:
            assert_equal(o["trigger_reason"], "long_waiting", f"按触发原因筛选正确: {o['order_id']}")

        section("测试11: 催办日志独立落盘，不混入正式日志")
        prod_logs_before = api("GET", "/api/logs?limit=10000")[0]["data"]
        prod_log_ids = {l["log_id"] for l in prod_logs_before}

        api("POST", "/api/books", {
            "book_id": "RM-B002", "title": "催办测试书2",
            "total_copies": 3, "borrow_days": 7, "retain_hours": 12,
        })
        r_res2, _ = api("POST", "/api/reserve", {"book_id": "RM-B002", "reader_id": "RM-R002"})
        res2_id = r_res2["data"]["reservation_id"]
        api("POST", "/api/remind", {
            "reservation_id": res2_id,
            "trigger_reason": "manual",
            "operator": "log-tester",
        })

        prod_logs_after = api("GET", "/api/logs?limit=10000")[0]["data"]
        prod_log_ids_after = {l["log_id"] for l in prod_logs_after}
        new_prod_log_ids = prod_log_ids_after - prod_log_ids
        remind_log_count = sum(1 for lid in new_prod_log_ids
                               if any(l["log_id"] == lid and "remind" in l.get("action", "")
                                      for l in prod_logs_after))
        assert_equal(remind_log_count, 0, "催办日志不出现在正式操作日志中")

        remind_logs_file = os.path.join(REMIND_DIR, "logs.json")
        assert_true(os.path.exists(remind_logs_file), "remind/logs.json 文件存在")
        with open(remind_logs_file, "r", encoding="utf-8") as f:
            remind_logs = json.load(f)
        assert_true(len(remind_logs) > 0, "催办日志文件非空")
        remind_log_actions = {l.get("action") for l in remind_logs}
        assert_true("remind_create" in remind_log_actions, "催办日志包含 remind_create")

        section("测试12: 失败催办不污染正式预约数据")
        data_before = {}
        for fname in ["books", "reservations", "logs"]:
            data_before[fname] = get_data_file_hash(f"{fname}.json")

        r_bad_res, _ = api("POST", "/api/remind", {
            "reservation_id": "nonexistent-reservation-id",
            "trigger_reason": "overdue_pickup",
        })
        assert_true(not r_bad_res.get("ok"), "不存在的预约创建催办失败")

        for fname, old_hash in data_before.items():
            assert_equal(get_data_file_hash(f"{fname}.json"), old_hash,
                         f"催办失败后 {fname}.json 未被修改")

        section("测试13: 不合法的触发原因被拦截")
        r_bad_reason, status_bad = api("POST", "/api/remind", {
            "reservation_id": res2_id,
            "trigger_reason": "invalid_reason",
        })
        assert_equal(status_bad, 400, "不合法触发原因返回 400")

        section("测试14: 缺少必填字段返回 400")
        r_no_res, status_no_res = api("POST", "/api/remind", {
            "trigger_reason": "manual",
        })
        assert_equal(status_no_res, 400, "缺少 reservation_id 返回 400")

        r_no_reason, status_no_reason = api("POST", "/api/remind", {
            "reservation_id": res2_id,
        })
        assert_equal(status_no_reason, 400, "缺少 trigger_reason 返回 400")

        section("测试15: 查看不存在的催办单返回 404")
        r_404, status_404 = api("GET", "/api/remind/nonexistent-id")
        assert_equal(status_404, 404, "查看不存在催办单返回 404")

        section("测试16: 导出不存在的催办单返回 404")
        r_exp_404, status_exp_404 = api("GET", "/api/remind/nonexistent-id/export")
        assert_equal(status_exp_404, 404, "导出不存在催办单返回 404")

        section("测试17: 撤销不存在的催办单返回 404")
        r_rev_404, status_rev_404 = api("POST", "/api/remind/nonexistent-id/revoke")
        assert_equal(status_rev_404, 404, "撤销不存在催办单返回 404")

        section("测试18: 只读查看 vs 撤销权限区别")
        api("POST", "/api/books", {
            "book_id": "RM-B003", "title": "权限测试书",
            "total_copies": 1, "borrow_days": 7, "retain_hours": 12,
        })
        r_perm_res, _ = api("POST", "/api/reserve", {"book_id": "RM-B003", "reader_id": "RM-R003"})
        perm_res_id = r_perm_res["data"]["reservation_id"]
        r_perm, _ = api("POST", "/api/remind", {
            "reservation_id": perm_res_id,
            "trigger_reason": "manual",
            "operator": "perm-tester",
        })
        perm_order_id = r_perm["data"]["order_id"]

        r_view, status_view = api("GET", f"/api/remind/{perm_order_id}")
        assert_equal(status_view, 200, "只读查看返回 200")
        assert_equal(r_view["data"]["status"], "pending", "查看不影响状态")

        r_exp_view, status_exp_view = api("GET", f"/api/remind/{perm_order_id}/export")
        assert_equal(status_exp_view, 200, "导出报告返回 200")
        assert_equal(r_exp_view["data"]["status"], "pending", "导出报告不影响状态")

        r_revoke_perm, status_revoke_perm = api("POST", f"/api/remind/{perm_order_id}/revoke", {"operator": "voider"})
        assert_equal(status_revoke_perm, 200, "撤销操作返回 200")
        assert_equal(r_revoke_perm["data"]["status"], "revoked", "撤销改变状态")
        assert_equal(r_revoke_perm["data"]["revoked_by"], "voider", "撤销记录操作者")

        section("测试19: 服务重启后催办记录可继续查询")
        all_orders = api("GET", "/api/remind")[0]["data"]
        first_order_id = all_orders[0]["order_id"]

        print("  [INFO] 重启服务中...")
        stop_server(proc)
        proc = start_server()

        r_after, status_after = api("GET", f"/api/remind/{first_order_id}")
        assert_equal(status_after, 200, "重启后查询返回 200")
        assert_equal(r_after["data"]["order_id"], first_order_id, "重启后 order_id 匹配")
        assert_true("timeline" in r_after["data"], "重启后时间线仍在")

        r_list_after, _ = api("GET", "/api/remind")
        assert_true(len(r_list_after["data"]) >= 3, "重启后列表至少有 3 条记录")

        r_export_after, _ = api("GET", f"/api/remind/{first_order_id}/export")
        assert_equal(r_export_after["data"]["order_id"], first_order_id, "重启后导出 order_id 匹配")
        assert_true("report_id" in r_export_after["data"], "重启后导出包含 report_id")

        section("测试20: 服务重启后 pending 催办单恢复为 processed")
        api("POST", "/api/books", {
            "book_id": "RM-B004", "title": "重启恢复测试书",
            "total_copies": 1, "borrow_days": 7, "retain_hours": 12,
        })
        r_restart_res, _ = api("POST", "/api/reserve", {"book_id": "RM-B004", "reader_id": "RM-R004"})
        restart_res_id = r_restart_res["data"]["reservation_id"]
        r_restart_remind, _ = api("POST", "/api/remind", {
            "reservation_id": restart_res_id,
            "trigger_reason": "overdue_pickup",
            "operator": "restart-tester",
        })
        restart_order_id = r_restart_remind["data"]["order_id"]
        assert_equal(r_restart_remind["data"]["status"], "pending", "重启前状态为 pending")

        print("  [INFO] 再次重启服务...")
        stop_server(proc)
        proc = start_server()

        r_restart_after, _ = api("GET", f"/api/remind/{restart_order_id}")
        assert_equal(r_restart_after["data"]["status"], "processed", "重启后 pending 恢复为 processed")
        timeline_after = r_restart_after["data"]["timeline"]
        timeline_events_after = [t["event"] for t in timeline_after]
        assert_true("recovered" in timeline_events_after, "时间线包含 recovered 事件")

        section("测试21: 馆藏配置变更后旧催办单自动失效")
        clear_data()
        stop_server(proc)
        proc = start_server()

        api("POST", "/api/books", {
            "book_id": "CFG-B001", "title": "配置变更测试书",
            "total_copies": 2, "borrow_days": 14, "retain_hours": 24,
        })
        r_cfg_res, _ = api("POST", "/api/reserve", {"book_id": "CFG-B001", "reader_id": "CFG-R001"})
        cfg_res_id = r_cfg_res["data"]["reservation_id"]
        r_cfg_remind, _ = api("POST", "/api/remind", {
            "reservation_id": cfg_res_id,
            "trigger_reason": "long_waiting",
            "operator": "cfg-tester",
        })
        cfg_order_id = r_cfg_remind["data"]["order_id"]
        assert_equal(r_cfg_remind["data"]["status"], "pending", "变更前催办状态为 pending")

        api("POST", "/api/books", {
            "book_id": "CFG-NEW", "title": "配置变更新书",
            "total_copies": 10, "borrow_days": 30, "retain_hours": 24,
        })

        print("  [INFO] 重启服务（触发配置变更检测）...")
        stop_server(proc)
        proc = start_server()

        r_cfg_check, _ = api("GET", f"/api/remind/{cfg_order_id}")
        assert_equal(r_cfg_check["data"]["status"], "expired", "配置变更后催办单状态变为 expired")
        assert_true(r_cfg_check["data"].get("config_stale"), "config_stale=true")

        r_cfg_export, _ = api("GET", f"/api/remind/{cfg_order_id}/export")
        assert_true("stale_warning" in r_cfg_export["data"], "导出报告包含过期警告")
        assert_equal(r_cfg_export["data"]["final_status"], "expired", "报告最终状态为 expired")

        section("测试22: 失效催办单不可撤销")
        r_rev_expired, status_rev_exp = api("POST", f"/api/remind/{cfg_order_id}/revoke", {"operator": "admin"})
        assert_equal(status_rev_exp, 409, "失效催办单撤销返回 409")
        assert_true("已失效" in r_rev_expired.get("error", ""), "错误信息提示已失效")

        section("测试23: 非活跃预约无法催办")
        api("POST", "/api/books", {
            "book_id": "RM-B005", "title": "取消预约测试书",
            "total_copies": 1, "borrow_days": 7, "retain_hours": 12,
        })
        r_cancel_res, _ = api("POST", "/api/reserve", {"book_id": "RM-B005", "reader_id": "RM-R005"})
        cancel_res_id = r_cancel_res["data"]["reservation_id"]

        api("DELETE", f"/api/reserve/{cancel_res_id}?reader_id=RM-R005")

        r_cancel_remind, status_cancel = api("POST", "/api/remind", {
            "reservation_id": cancel_res_id,
            "trigger_reason": "manual",
        })
        assert_equal(status_cancel, 400, "已取消预约无法催办返回 400")

        section("测试24: 并发冲突 - 同一预约快速提交两次催办")
        api("POST", "/api/books", {
            "book_id": "RM-B006", "title": "并发测试书",
            "total_copies": 1, "borrow_days": 7, "retain_hours": 12,
        })
        r_conc_res, _ = api("POST", "/api/reserve", {"book_id": "RM-B006", "reader_id": "RM-R006"})
        conc_res_id = r_conc_res["data"]["reservation_id"]

        r_conc1, _ = api("POST", "/api/remind", {
            "reservation_id": conc_res_id,
            "trigger_reason": "manual",
        })
        assert_true(r_conc1.get("ok"), "第一次催办成功")

        r_conc2, status_conc2 = api("POST", "/api/remind", {
            "reservation_id": conc_res_id,
            "trigger_reason": "overdue_pickup",
        })
        assert_equal(status_conc2, 409, "并发催办同一预约返回 409")

        section("测试25: 催办列表 limit 参数")
        r_limit, _ = api("GET", "/api/remind?limit=2")
        assert_true(len(r_limit["data"]) <= 2, "limit=2 时最多返回 2 条")

        section("测试26: 完整链路 - 创建→查询→导出→撤销→重新催办")
        api("POST", "/api/books", {
            "book_id": "RM-B007", "title": "端到端测试书",
            "total_copies": 1, "borrow_days": 7, "retain_hours": 12,
        })
        r_e2e_res, _ = api("POST", "/api/reserve", {"book_id": "RM-B007", "reader_id": "RM-R007"})
        e2e_res_id = r_e2e_res["data"]["reservation_id"]

        r_e2e_create, _ = api("POST", "/api/remind", {
            "reservation_id": e2e_res_id,
            "trigger_reason": "overdue_pickup",
            "operator": "e2e-user",
            "remark": "端到端催办",
        })
        e2e_id = r_e2e_create["data"]["order_id"]
        assert_equal(r_e2e_create["data"]["status"], "pending", "创建状态 pending")
        assert_equal(r_e2e_create["data"]["remark"], "端到端催办", "备注正确")

        r_e2e_get, _ = api("GET", f"/api/remind/{e2e_id}")
        assert_equal(r_e2e_get["data"]["status"], "pending", "查询状态 pending")
        assert_true("timeline" in r_e2e_get["data"], "查询包含时间线")

        r_e2e_export, _ = api("GET", f"/api/remind/{e2e_id}/export")
        assert_true("report_id" in r_e2e_export["data"], "导出包含 report_id")
        assert_equal(r_e2e_export["data"]["trigger_reason"], "overdue_pickup", "导出触发原因正确")
        assert_equal(r_e2e_export["data"]["operator"], "e2e-user", "导出处理人正确")
        assert_true(len(r_e2e_export["data"]["timeline"]) >= 1, "导出时间线至少有1条")
        assert_equal(r_e2e_export["data"]["final_status"], "pending", "导出最终状态为 pending")

        r_e2e_revoke, _ = api("POST", f"/api/remind/{e2e_id}/revoke", {"operator": "e2e-admin"})
        assert_equal(r_e2e_revoke["data"]["status"], "revoked", "撤销成功")
        assert_equal(r_e2e_revoke["data"]["final_status"], "revoked", "最终状态为 revoked")

        r_e2e_resub, _ = api("POST", "/api/remind", {
            "reservation_id": e2e_res_id,
            "trigger_reason": "long_waiting",
            "operator": "e2e-user2",
        })
        assert_equal(r_e2e_resub["data"]["status"], "pending", "重新催办成功")
        assert_equal(r_e2e_resub["data"]["trigger_reason"], "long_waiting", "重新催办触发原因正确")

        print("\n" + "="*60)
        print("  所有测试通过 ✓")
        print("="*60)

    finally:
        stop_server(proc)


if __name__ == "__main__":
    main()

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


if __name__ == "__main__":
    # ====== 前置：清空数据 + 启动服务 ======
    clear_data()
    server_proc = start_server()

    try:
        # ====== 场景 1：越队借出错误信息要包含队首读者 ======
        section("场景 1：越队借出 - 错误信息明确指出队首读者，且队列顺序不变")

        # 配置：B010 只有 1 副本
        api("POST", "/api/books", {
            "book_id": "B010", "title": "测试书目A",
            "total_copies": 1, "borrow_days": 14, "retain_hours": 2,
        })

        # R_A 先预约，直接 available（队首）
        r1, _ = api("POST", "/api/reserve", {"book_id": "B010", "reader_id": "R_A"})
        assert_true(r1["ok"] and r1["data"]["status"] == "available",
                    "R_A 预约后直接进入 available 状态")

        # R_B 后预约，进入 waiting
        r2, _ = api("POST", "/api/reserve", {"book_id": "B010", "reader_id": "R_B"})
        assert_true(r2["ok"] and r2["data"]["status"] == "waiting",
                    "R_B 预约后进入 waiting 状态")

        # R_C 再后预约，进入 waiting
        r3, _ = api("POST", "/api/reserve", {"book_id": "B010", "reader_id": "R_C"})
        assert_true(r3["ok"] and r3["data"]["status"] == "waiting",
                    "R_C 预约后进入 waiting 状态")

        # R_B 尝试越队借出 —— 应失败且错误信息包含"当前队首应借出的读者是 R_A"
        err, status = api("POST", "/api/checkout", {"book_id": "B010", "reader_id": "R_B"})
        assert_true(status == 409, "越队借出返回 HTTP 409")
        assert_true(not err["ok"], "越队借出 ok=false")
        assert_true("R_A" in err["error"],
                    f"错误信息包含队首 R_A，实际：{err['error']}")
        assert_true("当前队首应借出的读者是" in err["error"],
                    f"错误信息包含关键词'当前队首应借出的读者是'，实际：{err['error']}")

        # 验证队列顺序未变
        queue, _ = api("GET", "/api/queue/B010")
        readers = [r["reader_id"] for r in queue["data"]]
        assert_true(readers == ["R_A", "R_B", "R_C"],
                    f"队列顺序保持不变：应为 ['R_A','R_B','R_C']，实际 {readers}")

        # R_C 尝试越队借出 —— 同样应指出 R_A 是队首
        err2, _ = api("POST", "/api/checkout", {"book_id": "B010", "reader_id": "R_C"})
        assert_true("R_A" in err2["error"],
                    f"R_C 越队时错误信息也包含 R_A，实际：{err2['error']}")

        # 先让 R_A 借出，再让 R_B 越队应提示队首是 R_B? 不，R_B 此时仍 waiting.
        # R_A 正常借出
        ok_r, _ = api("POST", "/api/checkout", {"book_id": "B010", "reader_id": "R_A"})
        assert_true(ok_r["ok"] and ok_r["data"]["status"] == "borrowed",
                    "R_A 正常借出成功")

        # R_A 借出后 R_B 仍然 waiting（副本被借走），R_B 越队应提示当前 available 为空，但 R_B 自己是 waiting 第一个
        # 实际上此时 available 为空，waiting 第一个是 R_B，所以当 R_C 越队时队首应为 R_B
        err3, _ = api("POST", "/api/checkout", {"book_id": "B010", "reader_id": "R_C"})
        assert_true("R_B" in err3["error"],
                    f"R_A 借出后 R_C 越队应提示队首是 R_B，实际：{err3['error']}")

        # ====== 场景 2：导出接口包含完整操作历史 ======
        section("场景 2：导出接口包含完整操作历史（配置/预约/借出/归还/晋级）")

        # 先触发更多操作让 history 有内容：R_A 归还 → R_B 晋级
        ret, _ = api("POST", "/api/return", {"book_id": "B010", "reader_id": "R_A"})
        assert_true(ret["ok"], "R_A 归还成功")

        # 导出
        exp, status = api("GET", "/api/export/B010")
        assert_true(status == 200 and exp["ok"], "导出接口 HTTP 200 且 ok=true")

        # 必须有 history 字段
        assert_true("history" in exp["data"], "导出结果包含 history 字段")
        history = exp["data"]["history"]
        assert_true(isinstance(history, list) and len(history) > 0,
                    f"history 是非空列表，实际长度 {len(history) if isinstance(history, list) else type(history)}")

        # history 按时间正序
        timestamps = [h["timestamp"] for h in history]
        assert_true(timestamps == sorted(timestamps),
                    "history 按时间正序排列")

        # 检查关键 action 类型都在 history 中
        actions = {h["action"] for h in history}
        expected_actions = {"add_book", "reserve", "checkout", "return", "promote"}
        missing = expected_actions - actions
        assert_true(len(missing) == 0,
                    f"history 包含关键操作 {expected_actions}，缺失 {missing}")

        # history 中每条记录的 book_id 都应是 B010（或 book_id 为空的非书目动作如黑名单，这里 B010 没黑名单）
        for h in history:
            if h.get("book_id") is not None:
                assert_true(h["book_id"] == "B010",
                            f"history 中 book_id 正确，实际 {h.get('book_id')}")

        # ====== 场景 3：日志一致性 —— 导出的 history 与 /api/logs 按书目过滤结果一致 ======
        section("场景 3：日志一致性 —— 导出 history 与 /api/logs?book_id= 结果一致")

        logs, _ = api("GET", "/api/logs?book_id=B010&limit=1000")
        logs_sorted = sorted(logs["data"], key=lambda l: l["timestamp"])
        assert_true(len(logs_sorted) == len(history),
                    f"history 条数（{len(history)}）与 logs 过滤条数（{len(logs_sorted)}）一致")
        assert_true(
            all(h["log_id"] == l["log_id"] for h, l in zip(history, logs_sorted)),
            "每条记录的 log_id 一致"
        )

        # ====== 场景 4：服务重启后导出的 history 依然完整 ======
        section("场景 4：服务重启后导出的 history 依然完整持久化")

        # 记录重启前 history 的 log_id 集合
        log_ids_before = {h["log_id"] for h in history}
        queue_before = [r["reader_id"] for r in exp["data"]["queue"]]
        history_count_before = len(history)

        # 停止服务
        stop_server(server_proc)
        time.sleep(1)

        # 重启服务
        server_proc = start_server()

        # 重启后再导出
        exp2, status2 = api("GET", "/api/export/B010")
        assert_true(status2 == 200 and exp2["ok"], "重启后导出接口正常")
        history2 = exp2["data"]["history"]
        assert_true(isinstance(history2, list) and len(history2) >= history_count_before,
                    f"重启后 history 条数不减：重启前 {history_count_before}，重启后 {len(history2)}")

        log_ids_after = {h["log_id"] for h in history2}
        assert_true(log_ids_before.issubset(log_ids_after),
                    "重启前的所有 log_id 在重启后 history 中仍然存在")

        queue_after = [r["reader_id"] for r in exp2["data"]["queue"]]
        assert_true(queue_before == queue_after,
                    f"重启后队列顺序保持：重启前 {queue_before}，重启后 {queue_after}")

        # 重启后再执行一次预约，history 应该继续追加
        api("POST", "/api/reserve", {"book_id": "B010", "reader_id": "R_D"})
        exp3, _ = api("GET", "/api/export/B010")
        history3 = exp3["data"]["history"]
        reserve_d_actions = [h for h in history3 if h["action"] == "reserve" and h["reader_id"] == "R_D"]
        assert_true(len(reserve_d_actions) == 1 and reserve_d_actions[0]["success"],
                    "重启后新操作会追加到 history 中")

        print("\n" + "=" * 60)
        print("  所有回归测试全部通过!")
        print("=" * 60)

    finally:
        stop_server(server_proc)

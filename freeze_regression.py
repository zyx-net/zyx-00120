import os
import sys
import json
import time
import uuid
import shutil
import argparse
import subprocess
import signal
import urllib.request
import urllib.error

BASE_URL = "http://127.0.0.1:5000"
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_DIR, "data")
FREEZE_DIR = os.path.join(PROJECT_DIR, "freeze")

ARTIFACTS_ROOT = os.path.join(PROJECT_DIR, "_regression_artifacts")
RUNS_DIR = os.path.join(ARTIFACTS_ROOT, "runs")
EXPORTS_DIR = os.path.join(ARTIFACTS_ROOT, "exports")
LATEST_PTR = os.path.join(ARTIFACTS_ROOT, "LATEST")

_PASS = 0
_FAIL = 0
_LOG_LINES = []


class ArtifactManager:
    def __init__(self, keep_artifacts=False, export_samples=False,
                 export_dir=None, clean_before=False,
                 check_git_clean=False):
        self.keep_artifacts = keep_artifacts
        self.export_samples = export_samples
        self.export_dir = export_dir or PROJECT_DIR
        self.check_git_clean = check_git_clean

        self.run_id = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
        self.run_dir = os.path.join(RUNS_DIR, self.run_id)
        self.backup_dir = os.path.join(self.run_dir, "backup")
        self.logs_dir = os.path.join(self.run_dir, "logs")
        self.reports_dir = os.path.join(self.run_dir, "reports")
        self.diagnostics_dir = os.path.join(self.run_dir, "diagnostics")

        self.meta_path = os.path.join(self.run_dir, "RUN_META.json")
        self.log_file = os.path.join(self.logs_dir, "regression.log")
        self.pid_file = os.path.join(self.diagnostics_dir, "server_pid.txt")

        self.status = "created"
        self.started_at = None
        self.finished_at = None
        self.git_clean_before = None
        self.git_clean_after = None
        self._samples_to_export = {}

        if clean_before:
            self.clean_all_runs()

        if self.check_git_clean:
            self.git_clean_before = self._check_git_clean()

    def _ensure_dirs(self):
        for d in [ARTIFACTS_ROOT, RUNS_DIR, EXPORTS_DIR,
                  self.run_dir, self.backup_dir, self.logs_dir,
                  self.reports_dir, self.diagnostics_dir]:
            os.makedirs(d, exist_ok=True)

    def _write_meta(self, **extra):
        meta = {
            "run_id": self.run_id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "exit_code": None,
            "pass_count": None,
            "fail_count": None,
            "git_clean_before": self.git_clean_before,
            "git_clean_after": self.git_clean_after,
            "artifacts_kept": False,
            "samples_exported": False,
            "dirs": {
                "backup": os.path.relpath(self.backup_dir, PROJECT_DIR),
                "logs": os.path.relpath(self.logs_dir, PROJECT_DIR),
                "reports": os.path.relpath(self.reports_dir, PROJECT_DIR),
                "diagnostics": os.path.relpath(self.diagnostics_dir, PROJECT_DIR),
            }
        }
        meta.update(extra)
        try:
            with open(self.meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    @staticmethod
    def _run_git(args):
        try:
            result = subprocess.run(
                ["git"] + args,
                cwd=PROJECT_DIR,
                capture_output=True,
                text=True,
                timeout=15,
            )
            return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
        except FileNotFoundError:
            return None, "", "git 命令不可用"
        except Exception as e:
            return None, "", str(e)

    @staticmethod
    def _check_git_clean():
        ok, out, err = ArtifactManager._run_git(["status", "--porcelain"])
        if ok is None:
            return None
        clean_lines = []
        for line in out.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            parts = stripped.split(None, 1)
            path = parts[1] if len(parts) > 1 else parts[0]
            rel = os.path.relpath(os.path.join(PROJECT_DIR, path), PROJECT_DIR)
            if rel.startswith("_regression_artifacts") or rel == "_regression_artifacts":
                continue
            clean_lines.append(stripped)
        return len(clean_lines) == 0, clean_lines

    def mark_started(self):
        self._ensure_dirs()
        self.started_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        self.status = "running"
        self._write_meta()
        self._update_latest_ptr()

    def mark_finished(self, exit_code, pass_count, fail_count):
        self.finished_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        if exit_code == 0:
            self.status = "completed"
        else:
            self.status = "failed"
        self._write_meta(
            exit_code=exit_code,
            pass_count=pass_count,
            fail_count=fail_count,
        )

    def _update_latest_ptr(self):
        try:
            with open(LATEST_PTR, "w", encoding="utf-8") as f:
                f.write(self.run_id + "\n")
        except Exception:
            pass

    def backup_data(self, data_dirs):
        for d in data_dirs:
            if os.path.exists(d):
                name = os.path.basename(d)
                dst = os.path.join(self.backup_dir, name)
                if os.path.exists(dst):
                    shutil.rmtree(dst, ignore_errors=True)
                shutil.copytree(d, dst)
        log(f"已备份数据到 {os.path.relpath(self.backup_dir, PROJECT_DIR)}")

    def restore_data(self, data_dir_names):
        for name in data_dir_names:
            src = os.path.join(self.backup_dir, name)
            dst = os.path.join(PROJECT_DIR, name)
            if os.path.exists(dst):
                shutil.rmtree(dst, ignore_errors=True)
            if os.path.exists(src):
                shutil.copytree(src, dst)
        log("已恢复原始数据")

    def save_report_sample(self, name, data):
        path = os.path.join(self.reports_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        self._samples_to_export[name] = path
        log(f"  报告样例已保存: {os.path.relpath(path, PROJECT_DIR)}")

    def write_log_file(self):
        with open(self.log_file, "w", encoding="utf-8") as f:
            f.write("\n".join(_LOG_LINES))
        log(f"测试日志已保存: {os.path.relpath(self.log_file, PROJECT_DIR)}")

    def write_pid_file(self, pid):
        try:
            with open(self.pid_file, "w", encoding="utf-8") as f:
                f.write(str(pid) + "\n")
        except Exception:
            pass

    def do_export_samples(self):
        if not self.export_samples or not self._samples_to_export:
            return False
        os.makedirs(self.export_dir, exist_ok=True)
        for name, src_path in self._samples_to_export.items():
            base, ext = os.path.splitext(name)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            dst_name = f"{base}_{self.run_id}_{timestamp}{ext}"
            dst_path = os.path.join(self.export_dir, dst_name)
            shutil.copy2(src_path, dst_path)
            log(f"  已导出样例: {os.path.relpath(dst_path, PROJECT_DIR)}")
        export_meta = os.path.join(self.export_dir, f"EXPORT_{self.run_id}.json")
        with open(export_meta, "w", encoding="utf-8") as f:
            json.dump({
                "source_run": self.run_id,
                "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "samples": list(self._samples_to_export.keys()),
            }, f, ensure_ascii=False, indent=2)
        return True

    @staticmethod
    def clean_all_runs():
        removed = 0
        if os.path.isdir(RUNS_DIR):
            for entry in os.listdir(RUNS_DIR):
                full = os.path.join(RUNS_DIR, entry)
                if os.path.isdir(full):
                    shutil.rmtree(full, ignore_errors=True)
                    removed += 1
        if os.path.exists(LATEST_PTR):
            try:
                os.remove(LATEST_PTR)
            except Exception:
                pass
        if removed:
            print(f"[CLEAN] 已清理 {removed} 个历史运行目录")

    def finalize(self, exit_code, pass_count, fail_count):
        self.mark_finished(exit_code, pass_count, fail_count)
        self.write_log_file()

        exported = False
        if self.export_samples and exit_code == 0:
            exported = self.do_export_samples()

        kept = False
        if self.keep_artifacts:
            kept = True
        elif self.status == "failed":
            kept = True
            log(f"运行失败，工件已保留用于诊断: {os.path.relpath(self.run_dir, PROJECT_DIR)}")

        if not kept and os.path.isdir(self.run_dir):
            shutil.rmtree(self.run_dir, ignore_errors=True)
            if os.path.exists(LATEST_PTR):
                try:
                    with open(LATEST_PTR, "r", encoding="utf-8") as f:
                        latest = f.read().strip()
                    if latest == self.run_id:
                        os.remove(LATEST_PTR)
                except Exception:
                    pass

        if self.check_git_clean:
            result = self._check_git_clean()
            if result is not None:
                clean, dirty = result
                self.git_clean_after = (clean, dirty)
                if not clean:
                    log(f"[WARN] 运行后 git status 不干净: {dirty}", "WARN")
                else:
                    log("[OK] 运行后 git status 保持干净")

        self._write_meta(
            exit_code=exit_code,
            pass_count=pass_count,
            fail_count=fail_count,
            artifacts_kept=kept,
            samples_exported=exported,
        )
        return kept


_ART_MGR = None


def log(msg, level="INFO"):
    global _LOG_LINES
    line = f"[{time.strftime('%H:%M:%S')}] [{level}] {msg}"
    _LOG_LINES.append(line)
    print(line)


def assert_eq(actual, expected, desc):
    global _PASS, _FAIL
    if actual == expected:
        _PASS += 1
        log(f"PASS: {desc}")
        return True
    _FAIL += 1
    log(f"FAIL: {desc} | expected={expected!r} actual={actual!r}", "ERROR")
    return False


def assert_true(cond, desc):
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        log(f"PASS: {desc}")
        return True
    _FAIL += 1
    log(f"FAIL: {desc} | condition={cond}", "ERROR")
    return False


def http(method, path, body=None, headers=None, timeout=10):
    url = f"{BASE_URL}{path}"
    data = None
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        return e.code, json.loads(raw) if raw else {}
    except Exception as e:
        return -1, {"error": str(e)}


def wait_for_server(max_wait=30):
    log(f"等待服务器启动（最长 {max_wait}s）...")
    start = time.time()
    while time.time() - start < max_wait:
        try:
            st, data = http("GET", "/api/books", timeout=2)
            if st == 200:
                log(f"服务器已就绪，耗时 {int(time.time() - start)}s")
                return True
        except Exception:
            pass
        time.sleep(1)
    log(f"服务器在 {max_wait}s 内未就绪", "ERROR")
    return False


def backup_data():
    _ART_MGR.backup_data([DATA_DIR, FREEZE_DIR])


def restore_data():
    _ART_MGR.restore_data(["data", "freeze"])


def start_server():
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen(
        [sys.executable, os.path.join(PROJECT_DIR, "main.py")],
        cwd=PROJECT_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    log(f"启动服务器 PID={proc.pid}")
    _ART_MGR.write_pid_file(proc.pid)
    return proc


def stop_server(proc):
    if proc and proc.poll() is None:
        try:
            if os.name == "nt":
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                proc.terminate()
            time.sleep(1)
            if proc.poll() is None:
                proc.kill()
        except Exception:
            pass
    log("已停止服务器")


def setup_test_data():
    log("=== 准备测试数据 ===")
    st, r = http("POST", "/api/books", {
        "book_id": "FREEZE-TEST-001",
        "title": "冻结模块测试书目A",
        "total_copies": 2,
        "borrow_days": 14,
        "retain_hours": 24,
    })
    assert_eq(st, 201, f"创建书目 FREEZE-TEST-001 (st={st})")
    st, r = http("POST", "/api/books", {
        "book_id": "FREEZE-TEST-002",
        "title": "冻结模块测试书目B",
        "total_copies": 1,
        "borrow_days": 7,
        "retain_hours": 12,
    })
    assert_eq(st, 201, f"创建书目 FREEZE-TEST-002 (st={st})")
    for i, rid in enumerate(["R1001", "R1002", "R1003", "R1004"]):
        st, r = http("POST", "/api/reserve", {"book_id": "FREEZE-TEST-001", "reader_id": rid})
        assert_eq(st, 201, f"R{i+1} 预约 FREEZE-TEST-001 (rid={rid})")
    st, r = http("POST", "/api/reserve", {"book_id": "FREEZE-TEST-002", "reader_id": "R2001"})
    assert_eq(st, 201, "R2001 预约 FREEZE-TEST-002")


def run_tests():
    log("")
    log("===========================================")
    log("  预约冻结与恢复中心 - 一键回归测试")
    log("===========================================")
    log("")

    backup_data()
    try:
        setup_test_data()

        log("")
        log("=== [T1] 权限区分：viewer 不能创建冻结单 ===")
        st, r = http("POST", "/api/freeze", {
            "book_id": "FREEZE-TEST-001",
            "reason": "inventory_check",
            "operator": "librarian_A",
        }, headers={"X-Role": "viewer"})
        assert_eq(st, 403, f"viewer 创建被拒绝 (st={st})")
        assert_true("manager 权限" in r.get("error", ""), "错误消息包含权限提示")

        log("")
        log("=== [T2] 创建立即生效冻结单（幂等键 idem-001） ===")
        body = {
            "book_id": "FREEZE-TEST-001",
            "reason": "inventory_check",
            "remark": "年终盘点，馆内下架盘点",
            "idempotency_key": "idem-001",
            "operator": "librarian_A",
        }
        st, r = http("POST", "/api/freeze", body, headers={"X-Role": "manager"})
        assert_eq(st, 201, f"创建立即冻结单成功 (st={st})")
        assert_eq(r["data"]["status"], "frozen", "状态应为 frozen")
        assert_eq(r["data"]["reason"], "inventory_check", "冻结原因正确")
        assert_eq(r["data"]["operator"], "librarian_A", "操作者正确")
        FREEZE_ID_A = r["data"]["freeze_id"]
        log(f"  freeze_id = {FREEZE_ID_A}")
        before_summary = r["data"]["before_snapshot_summary"]
        assert_eq(before_summary["total_count"], 4, "冻结前队列应有 4 人")
        after_summary = r["data"]["after_snapshot_summary"]
        assert_true(after_summary is not None, "冻结后快照摘要已记录")
        assert_eq(after_summary["frozen_count"], 4, "应冻结 4 条预约")

        log("")
        log("=== [T3] 幂等性：使用相同 idempotency_key 再次请求 ===")
        st, r = http("POST", "/api/freeze", body, headers={"X-Role": "manager"})
        assert_eq(st, 201, f"幂等请求仍返回 201 (st={st})（幂等命中而非错误）")
        assert_true(r.get("idempotent_hit", False), "响应标记 idempotent_hit=true")
        assert_eq(r["data"]["freeze_id"], FREEZE_ID_A, "幂等命中返回同一 freeze_id")

        log("")
        log("=== [T4] 同一书目重复冻结冲突 ===")
        st, r = http("POST", "/api/freeze", {
            "book_id": "FREEZE-TEST-001",
            "reason": "maintenance",
            "idempotency_key": "idem-001-conflict",
        }, headers={"X-Role": "manager", "X-Operator": "librarian_B"})
        assert_eq(st, 409, f"重复冻结返回冲突 (st={st})")
        assert_true("已存在活跃冻结单" in r.get("error", ""), "错误消息提示已存在活跃冻结")

        log("")
        log("=== [T5] 查看冻结前后队列快照 ===")
        st, before = http("GET", f"/api/freeze/{FREEZE_ID_A}/snapshot/before",
                          headers={"X-Role": "viewer"})
        assert_eq(st, 200, f"查看冻结前快照 (st={st})")
        assert_eq(before["data"]["book_id"], "FREEZE-TEST-001", "快照书目正确")
        assert_eq(before["data"]["total_count"], 4, "快照总人数 4")
        readers = [r["reader_id"] for r in before["data"]["affected_readers"]]
        for rid in ["R1001", "R1002", "R1003", "R1004"]:
            assert_true(rid in readers, f"冻结前包含读者 {rid}")

        st, after = http("GET", f"/api/freeze/{FREEZE_ID_A}/snapshot/after_freeze",
                         headers={"X-Role": "viewer"})
        assert_eq(st, 200, f"查看冻结后快照 (st={st})")
        assert_true(after["data"] is not None, "冻结后快照存在")

        log("")
        log("=== [T6] 导出 JSON 报告 ===")
        st, r = http("GET", f"/api/freeze/{FREEZE_ID_A}/export", headers={"X-Role": "viewer"})
        assert_eq(st, 200, f"导出报告 (st={st})")
        rep = r["data"]
        assert_eq(rep["freeze_id"], FREEZE_ID_A, "报告 freeze_id 正确")
        assert_eq(rep["freeze_reason"], "inventory_check", "报告冻结原因正确")
        assert_eq(rep["operator"], "librarian_A", "报告操作者正确")
        assert_eq(rep["status"], "frozen", "报告状态 correct")
        impact = rep["impact_summary"]
        assert_eq(impact["total_affected_readers"], 4, "影响读者数 4")
        assert_eq(len(impact["affected_reader_ids"]), 4, "影响读者ID列表长度 4")
        assert_true(len(rep["timeline"]) >= 2, "时间线包含 created + frozen")
        assert_true("created" in [e["event"] for e in rep["timeline"]], "时间线含 created")
        assert_true("frozen" in [e["event"] for e in rep["timeline"]], "时间线含 frozen")
        assert_true(rep["snapshots"]["before_freeze"]["present"], "before 快照标记存在")
        assert_true(rep["snapshots"]["after_freeze"]["present"], "after_freeze 快照标记存在")
        audit_count = len(rep["audit_logs"])
        assert_true(audit_count >= 3, f"报告包含审计日志 >=3（实际 {audit_count}）")
        _ART_MGR.save_report_sample("freeze_report_sample.json", rep)

        log("")
        log("=== [T7] 按书目和原因筛选冻结单 ===")
        st, r = http("POST", "/api/freeze", {
            "book_id": "FREEZE-TEST-002",
            "reason": "maintenance",
            "remark": "书架维护",
            "idempotency_key": "idem-002",
            "operator": "librarian_B",
        }, headers={"X-Role": "manager"})
        assert_eq(st, 201, f"创建 FREEZE-TEST-002 冻结 (st={st})")
        FREEZE_ID_B = r["data"]["freeze_id"]

        st, r = http("GET", "/api/freeze?book_id=FREEZE-TEST-001&reason=inventory_check")
        assert_eq(st, 200, f"按书目+原因筛选 (st={st})")
        assert_eq(len(r["data"]), 1, "仅返回 1 条匹配记录")
        assert_eq(r["data"][0]["freeze_id"], FREEZE_ID_A, "匹配正确的冻结单")

        st, r = http("GET", "/api/freeze?reason=maintenance")
        assert_eq(len(r["data"]), 1, "按 maintenance 筛选得到 1 条")
        assert_eq(r["data"][0]["freeze_id"], FREEZE_ID_B, "匹配正确的冻结单")

        log("")
        log("=== [T7.5] 先恢复 FREEZE-TEST-002 冻结，为后续创建 pending 冻结清场 ===")
        st, r = http("POST", f"/api/freeze/{FREEZE_ID_B}/restore", {
            "operator": "librarian_B",
        }, headers={"X-Role": "manager"})
        assert_eq(st, 200, f"恢复 FREEZE-TEST-002 冻结 (st={st})")
        assert_eq(r["data"]["status"], "restored", "FREEZE-TEST-002 状态变为 restored")

        log("")
        log("=== [T8] 创建未生效（定时）冻结单 ===")
        from datetime import datetime, timezone, timedelta
        future = (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
        st, r = http("POST", "/api/freeze", {
            "book_id": "FREEZE-TEST-002",
            "reason": "abnormal_check",
            "remark": "明天排查异常",
            "effective_at": future,
            "idempotency_key": "idem-scheduled-001",
            "operator": "librarian_C",
        }, headers={"X-Role": "manager"})
        assert_eq(st, 201, f"创建定时未生效冻结 (st={st})")
        assert_eq(r["data"]["status"], "pending", "状态为 pending（未生效）")
        FREEZE_ID_SCHEDULED = r["data"]["freeze_id"]
        log(f"  pending_freeze_id = {FREEZE_ID_SCHEDULED}")

        log("")
        log("=== [T9] 撤销未生效冻结单 ===")
        st, r = http("POST", f"/api/freeze/{FREEZE_ID_SCHEDULED}/revoke", {
            "operator": "librarian_C",
        }, headers={"X-Role": "manager"})
        assert_eq(st, 200, f"撤销未生效冻结 (st={st})")
        assert_eq(r["data"]["status"], "revoked", "状态应为 revoked")
        assert_true(r["data"]["revoked_at"] is not None, "revoked_at 已记录")

        log("")
        log("=== [T10] 已生效冻结不能撤销 ===")
        st, r = http("POST", f"/api/freeze/{FREEZE_ID_A}/revoke", {
            "operator": "librarian_A",
        }, headers={"X-Role": "manager"})
        assert_eq(st, 409, f"已生效冻结拒绝撤销 (st={st})")
        assert_true("仅 pending" in r.get("error", ""), "错误消息正确提示仅 pending 可撤销")

        log("")
        log("=== [T11] 单人恢复：恢复 FREEZE-TEST-001 冻结 ===")
        st, r = http("POST", f"/api/freeze/{FREEZE_ID_A}/restore", {
            "operator": "librarian_A",
        }, headers={"X-Role": "manager"})
        assert_eq(st, 200, f"恢复冻结单 A (st={st})")
        assert_eq(r["data"]["status"], "restored", "状态应为 restored")
        assert_true(r["data"]["restored_at"] is not None, "restored_at 已记录")
        restore_summary = r["data"]["restore_summary"]
        assert_true(restore_summary is not None, "恢复摘要已生成")
        assert_eq(restore_summary["total_restored"], 4, "共恢复 4 条预约")

        log("")
        log("=== [T12] 验证恢复后队列是否正确 ===")
        st, r = http("GET", "/api/queue/FREEZE-TEST-001")
        assert_eq(st, 200, f"查询 FREEZE-TEST-001 队列 (st={st})")
        queue = r["data"]
        assert_eq(len(queue), 4, "恢复后队列仍有 4 人（状态回到 waiting/available）")
        statuses = [x["status"] for x in queue]
        has_frozen = any(s == "frozen" for s in statuses)
        assert_true(not has_frozen, "队列中不再存在 frozen 状态")

        log("")
        log("=== [T13] 批量恢复：先创建新冻结再批量恢复 ===")
        new_freeze_ids = []
        for i, (bid, reason, key) in enumerate([
            ("FREEZE-TEST-001", "inventory_check", "idem-batch-1"),
            ("FREEZE-TEST-002", "maintenance", "idem-batch-2"),
        ]):
            st, r = http("POST", "/api/freeze", {
                "book_id": bid, "reason": reason,
                "idempotency_key": key, "operator": "librarian_batch",
            }, headers={"X-Role": "manager"})
            assert_eq(st, 201, f"创建批量恢复测试冻结#{i} (st={st})")
            assert_eq(r["data"]["status"], "frozen", f"冻结#{i} 状态为 frozen")
            new_freeze_ids.append(r["data"]["freeze_id"])
        st, r = http("POST", "/api/freeze/batch-restore", {
            "freeze_ids": new_freeze_ids + [FREEZE_ID_A],
            "operator": "librarian_batch",
        }, headers={"X-Role": "manager"})
        assert_eq(st, 200, f"批量恢复 API (st={st})")
        batch = r["data"]
        assert_true(batch["total"] == 3, f"批量任务共 3 个（2 新 + 1 旧）")
        assert_true(len(batch["succeeded"]) == 2,
                    f"应成功 2 个新冻结（实际 succeeded={len(batch['succeeded'])}）")
        assert_true(len(batch["failed"]) == 1,
                    f"应失败 1 个旧冻结（实际 failed={len(batch['failed'])}）")
        total_restored = sum(s.get("restored_count", 0) for s in batch["succeeded"])
        assert_true(total_restored >= 5, f"批量共恢复预约数 >=5（实际 {total_restored}）")

        log("")
        log("=== [T14] 留痕审计：查询审计日志 ===")
        st, r = http("GET", f"/api/freeze/audit-logs?freeze_id={FREEZE_ID_A}&limit=50")
        assert_eq(st, 200, f"查询 {FREEZE_ID_A} 审计日志 (st={st})")
        logs = r["data"]
        actions = [l["action"] for l in logs]
        assert_true("freeze_create" in actions, "审计包含 freeze_create")
        assert_true("freeze_effective" in actions, "审计包含 freeze_effective")
        assert_true("freeze_restore" in actions, "审计包含 freeze_restore")
        assert_true("freeze_export_report" in actions, "审计包含 freeze_export_report")

        log("")
        log("=== [T15] 功能配置：viewer 可读 manager 可写 ===")
        st, r = http("GET", "/api/freeze/config", headers={"X-Role": "viewer"})
        assert_eq(st, 200, f"viewer 读取配置 (st={st})")
        assert_eq(r["data"]["enabled"], True, "默认功能开启")
        st, r = http("PUT", "/api/freeze/config", {"enabled": False}, headers={"X-Role": "viewer"})
        assert_eq(st, 403, f"viewer 修改配置被拒绝 (st={st})")

        log("")
        log("=== [T16] 配置关闭 + 创建未生效冻结 + 再关配置自动失效 ===")
        st, r = http("PUT", "/api/freeze/config", {
            "enabled": True,
            "operator": "admin",
        }, headers={"X-Role": "manager"})
        assert_eq(st, 200, "先确保配置开启")

        future2 = (datetime.now(timezone.utc) + timedelta(hours=8)).isoformat()
        st, r = http("POST", "/api/freeze", {
            "book_id": "FREEZE-TEST-002",
            "reason": "other",
            "remark": "测试自动失效",
            "effective_at": future2,
            "idempotency_key": "idem-auto-invalidate-001",
            "operator": "librarian_D",
        }, headers={"X-Role": "manager"})
        assert_eq(st, 201, f"创建第二个 pending 冻结 (st={st})")
        FREEZE_ID_PENDING2 = r["data"]["freeze_id"]
        assert_eq(r["data"]["status"], "pending", "pending 状态正确")

        st, r = http("PUT", "/api/freeze/config", {
            "enabled": False,
            "operator": "admin",
        }, headers={"X-Role": "manager"})
        assert_eq(st, 200, f"manager 关闭功能 (st={st})")
        assert_eq(r["data"]["config"]["enabled"], False, "配置已关闭")
        invalidated = r["data"].get("auto_invalidated_ids") or []
        assert_true(len(invalidated) >= 1, f"关闭功能时自动失效 {len(invalidated)} 个 pending 单")
        assert_true(FREEZE_ID_PENDING2 in invalidated, f"{FREEZE_ID_PENDING2} 已被自动失效")

        st, r = http("GET", f"/api/freeze/{FREEZE_ID_PENDING2}")
        assert_eq(r["data"]["status"], "auto_invalidated", f"冻结单状态变为 auto_invalidated")

        log("")
        log("=== [T17] 功能关闭时无法创建新冻结 ===")
        st, r = http("POST", "/api/freeze", {
            "book_id": "FREEZE-TEST-001",
            "reason": "inventory_check",
            "idempotency_key": "idem-disabled-001",
        }, headers={"X-Role": "manager"})
        assert_eq(st, 400, f"功能关闭时创建被拒绝 (st={st})")
        assert_true("已被系统管理员关闭" in r.get("error", ""), "提示功能已关闭")

        st, r = http("PUT", "/api/freeze/config", {
            "enabled": True,
            "operator": "admin",
        }, headers={"X-Role": "manager"})
        assert_eq(st, 200, "重新开启功能（为后续重启测试做准备）")

        log("")
        log("=== [T18] 重启恢复：冻结状态与待恢复任务不丢失 ===")
        future3 = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        st, r = http("POST", "/api/freeze", {
            "book_id": "FREEZE-TEST-001",
            "reason": "inventory_check",
            "remark": "重启前创建的冻结",
            "effective_at": future3,
            "idempotency_key": "idem-restart-001",
            "operator": "librarian_restart",
        }, headers={"X-Role": "manager"})
        assert_eq(st, 201, "重启前创建 pending 冻结")
        FREEZE_ID_RESTART_PENDING = r["data"]["freeze_id"]

        st, r = http("POST", "/api/freeze", {
            "book_id": "FREEZE-TEST-002",
            "reason": "maintenance",
            "idempotency_key": "idem-restart-002",
            "operator": "librarian_restart",
        }, headers={"X-Role": "manager"})
        assert_eq(st, 201, "重启前创建立即生效冻结")
        FREEZE_ID_RESTART_FROZEN = r["data"]["freeze_id"]
        assert_eq(r["data"]["status"], "frozen", "状态为 frozen")

        log("  已保存重启前冻结ID，准备重启服务器...")
        return {
            "freeze_id_a": FREEZE_ID_A,
            "freeze_id_b": FREEZE_ID_B,
            "freeze_id_scheduled": FREEZE_ID_SCHEDULED,
            "freeze_id_restart_pending": FREEZE_ID_RESTART_PENDING,
            "freeze_id_restart_frozen": FREEZE_ID_RESTART_FROZEN,
        }

    except Exception as e:
        log(f"测试发生异常: {e}", "ERROR")
        import traceback
        traceback.print_exc()
        return None


def run_post_restart_tests(ids):
    if not ids:
        return
    log("")
    log("=== [T18-续] 重启后验证 ===")
    st, r = http("GET", f"/api/freeze/{ids['freeze_id_restart_frozen']}")
    assert_eq(st, 200, "查询重启前的 frozen 冻结")
    assert_eq(r["data"]["status"], "frozen", "重启后 frozen 状态保持不变")
    assert_eq(r["data"]["operator"], "librarian_restart", "操作者信息保留")
    st, before = http("GET", f"/api/freeze/{ids['freeze_id_restart_frozen']}/snapshot/before")
    assert_eq(st, 200, "重启后快照文件仍可读取")
    assert_true(before["data"] is not None, "快照数据存在")

    st, r = http("GET", f"/api/freeze/{ids['freeze_id_restart_pending']}")
    assert_eq(st, 200, "查询重启前的 pending 冻结")
    assert_eq(r["data"]["status"], "pending", "重启后 pending 状态保持")

    log("")
    log("=== [T19] 重启后执行恢复 ===")
    st, r = http("POST", f"/api/freeze/{ids['freeze_id_restart_frozen']}/restore", {
        "operator": "librarian_after_restart",
    }, headers={"X-Role": "manager"})
    assert_eq(st, 200, "重启后恢复冻结成功")
    assert_eq(r["data"]["status"], "restored", "恢复后状态为 restored")
    assert_eq(r["data"]["restore_summary"]["total_restored"], 1, "应恢复 1 条预约（FREEZE-TEST-002）")

    log("")
    log("=== [T20] 重启后重新导出报告验证历史数据完整 ===")
    st, r = http("GET", f"/api/freeze/{ids['freeze_id_a']}/export")
    assert_eq(st, 200, "重启后导出报告")
    rep = r["data"]
    assert_eq(rep["impact_summary"]["total_affected_readers"], 4, "重启后报告影响人数仍为 4")
    assert_true(rep["audit_logs"], "重启后报告审计日志仍存在")

    log("")
    log("===========================================")
    log(f"  测试结束  通过: {_PASS}   失败: {_FAIL}")
    log("===========================================")
    return _FAIL == 0


def build_arg_parser():
    parser = argparse.ArgumentParser(
        description="预约冻结与恢复中心 - 一键回归测试",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
工件目录结构（默认全部 git-ignore）:
  _regression_artifacts/
  ├── runs/YYYYMMDD_HHMMSS_<rand>/   每次运行的独立目录
  │   ├── backup/                    测试前数据备份
  │   ├── logs/regression.log        完整执行日志
  │   ├── reports/                   报告样例
  │   ├── diagnostics/               PID 等诊断文件
  │   └── RUN_META.json              运行元数据
  ├── exports/                       --export-samples 显式导出的样例
  └── LATEST                         最近一次运行 ID 指针

默认策略：
  * 成功运行 → 自动清理工件目录，源码根保持干净
  * 失败运行 → 自动保留工件（backup/logs/reports/diagnostics）
  * --keep-artifacts → 无论成功失败都保留
  * --export-samples → 成功后把报告样例复制到 exports/ 或指定目录
  * --check-git-clean → 执行前后检查 git status 干净性
        """,
    )
    parser.add_argument("--keep-artifacts", action="store_true",
                        help="无论成功失败都保留运行工件目录")
    parser.add_argument("--export-samples", action="store_true",
                        help="运行成功后导出报告样例")
    parser.add_argument("--export-dir", metavar="PATH", default=None,
                        help="导出目录（默认 _regression_artifacts/exports/）")
    parser.add_argument("--clean-before", action="store_true",
                        help="运行前清理所有历史运行工件目录")
    parser.add_argument("--clean-only", action="store_true",
                        help="仅清理历史工件并退出，不执行回归")
    parser.add_argument("--check-git-clean", action="store_true",
                        help="执行前后检查 git status（忽略 _regression_artifacts/）")
    return parser


def main():
    global _ART_MGR
    parser = build_arg_parser()
    args = parser.parse_args()

    if args.clean_only:
        ArtifactManager.clean_all_runs()
        print("[DONE] 清理完成，未执行回归测试")
        return 0

    export_dir = args.export_dir
    if export_dir is None and args.export_samples:
        export_dir = EXPORTS_DIR

    _ART_MGR = ArtifactManager(
        keep_artifacts=args.keep_artifacts,
        export_samples=args.export_samples,
        export_dir=export_dir,
        clean_before=args.clean_before,
        check_git_clean=args.check_git_clean,
    )
    _ART_MGR.mark_started()

    log("开始执行预约冻结与恢复中心回归测试")
    log(f"项目目录: {PROJECT_DIR}")
    log(f"工件运行目录: {os.path.relpath(_ART_MGR.run_dir, PROJECT_DIR)}")
    if _ART_MGR.check_git_clean and _ART_MGR.git_clean_before is not None:
        clean, dirty = _ART_MGR.git_clean_before
        if clean:
            log("[OK] 运行前 git status 干净")
        else:
            log(f"[WARN] 运行前 git status 不干净: {dirty}", "WARN")

    proc = None
    exit_code = 1
    try:
        proc = start_server()
        if not wait_for_server():
            log("服务器未启动，退出", "ERROR")
            stop_server(proc)
            return 1

        ids = run_tests()
        if ids is None:
            stop_server(proc)
            return 1

        log("")
        log("=== 重启服务器以验证持久化恢复 ===")
        stop_server(proc)
        proc = None
        time.sleep(2)

        proc = start_server()
        if not wait_for_server():
            log("重启后服务器未就绪", "ERROR")
            return 1

        ok = run_post_restart_tests(ids)
        exit_code = 0 if ok else 1
        return exit_code
    finally:
        stop_server(proc)
        restore_data()
        _ART_MGR.finalize(exit_code, _PASS, _FAIL)
        rel_latest = os.path.relpath(os.path.join(RUNS_DIR, _ART_MGR.run_id), PROJECT_DIR)
        log(f"工件元数据: RUN_META.json @ {rel_latest}/ (若保留)")


if __name__ == "__main__":
    sys.exit(main())

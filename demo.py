import json
import sys
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:5000"


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


def pp(result, status):
    print(f"  [HTTP {status}]")
    print(f"  {json.dumps(result, ensure_ascii=False, indent=2)}")


def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


if __name__ == "__main__":
    section("1. 添加书目")
    r, s = api("POST", "/api/books", {
        "book_id": "B001", "title": "深入理解计算机系统",
        "total_copies": 2, "borrow_days": 30, "retain_hours": 48,
    })
    pp(r, s)
    r, s = api("POST", "/api/books", {
        "book_id": "B002", "title": "算法导论",
        "total_copies": 1, "borrow_days": 14, "retain_hours": 24,
    })
    pp(r, s)

    section("2. 列出所有书目")
    r, s = api("GET", "/api/books")
    pp(r, s)

    section("3. 查询单个书目")
    r, s = api("GET", "/api/books/B001")
    pp(r, s)

    section("4. 更新书目（B002 副本数改为 2）")
    r, s = api("PUT", "/api/books/B002", {"total_copies": 2})
    pp(r, s)

    section("5. 读者预约 B001（2 副本，前 2 人直接待取，第 3 人等待）")
    r, s = api("POST", "/api/reserve", {"book_id": "B001", "reader_id": "R001"})
    pp(r, s)
    r, s = api("POST", "/api/reserve", {"book_id": "B001", "reader_id": "R002"})
    pp(r, s)
    r, s = api("POST", "/api/reserve", {"book_id": "B001", "reader_id": "R003"})
    pp(r, s)

    section("6. 查看队列")
    r, s = api("GET", "/api/queue/B001")
    pp(r, s)

    section("7. 查看队列位置（R003 应在等待位置 1）")
    r, s = api("GET", "/api/position/B001/R003")
    pp(r, s)

    section("8. 借出（R001 是队首待取，可借出）")
    r, s = api("POST", "/api/checkout", {"book_id": "B001", "reader_id": "R001"})
    pp(r, s)

    section("9. R002 借出")
    r, s = api("POST", "/api/checkout", {"book_id": "B001", "reader_id": "R002"})
    pp(r, s)

    section("10. 归还 R001（触发 R003 晋级为待取）")
    r, s = api("POST", "/api/return", {"book_id": "B001", "reader_id": "R001"})
    pp(r, s)

    section("11. 归还后查看队列（R003 应已晋级为 available）")
    r, s = api("GET", "/api/queue/B001")
    pp(r, s)

    section("12. 冲突：同一读者重复占位")
    r, s = api("POST", "/api/reserve", {"book_id": "B001", "reader_id": "R002"})
    pp(r, s)

    section("13. 冲突：越过队首借出（R003 已是 available，但 R_BAD 在 waiting 不可借）")
    api("POST", "/api/reserve", {"book_id": "B001", "reader_id": "R_BAD"})
    r, s = api("POST", "/api/checkout", {"book_id": "B001", "reader_id": "R_BAD"})
    pp(r, s)

    section("14. 冲突：归还不存在的借阅")
    r, s = api("POST", "/api/return", {"book_id": "B001", "reader_id": "R999"})
    pp(r, s)

    section("15. 黑名单：加入黑名单")
    r, s = api("POST", "/api/blacklist", {"reader_id": "R_BAD", "reason": "恶意预约不取书"})
    pp(r, s)

    section("16. 黑名单：黑名单读者预约")
    r, s = api("POST", "/api/reserve", {"book_id": "B001", "reader_id": "R_BAD"})
    pp(r, s)

    section("17. 黑名单：移出黑名单")
    r, s = api("DELETE", "/api/blacklist/R_BAD")
    pp(r, s)

    section("18. 查看黑名单")
    r, s = api("GET", "/api/blacklist")
    pp(r, s)

    section("19. 取消预约")
    r, s = api("POST", "/api/reserve", {"book_id": "B002", "reader_id": "R004"})
    pp(r, s)
    if r.get("ok"):
        rid = r["data"]["reservation_id"]
        r2, s2 = api("DELETE", f"/api/reserve/{rid}?reader_id=R004")
        pp(r2, s2)

    section("20. 手动触发过期释放")
    r, s = api("POST", "/api/expire")
    pp(r, s)

    section("21. 查看操作日志（最近 10 条）")
    r, s = api("GET", "/api/logs?limit=10")
    pp(r, s)

    section("22. 按书目过滤日志")
    r, s = api("GET", "/api/logs?book_id=B001&limit=5")
    pp(r, s)

    section("23. 导出 B001 队列快照")
    r, s = api("GET", "/api/export/B001")
    pp(r, s)

    section("24. 删除书目 B002")
    r, s = api("DELETE", "/api/books/B002")
    pp(r, s)

    print("\n" + "=" * 60)
    print("  全部验证完成!")
    print("=" * 60)

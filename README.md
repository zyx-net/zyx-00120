# 图书预约排队后端服务

基于 Flask 的本地 HTTP API 服务，支持馆藏配置、预约队列、借出归还、过期释放、冲突处理、操作日志和队列快照导出。

## 本地运行

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

或直接安装：

```bash
pip install flask
```

### 2. 启动服务

```bash
python main.py
```

服务启动在 `http://127.0.0.1:5000`。启动时会自动：
- 检查 `data/` 目录是否存在（不存在则自动创建）
- 扫描并处理已过期的待取预约
- 启动后台定时过期扫描（每 10 秒一次）

### 3. 一键运行完整验证

基础全流程验证（包含正常链路和 4 类冲突场景）：

```bash
python demo.py
```

回归测试（专门覆盖本次修复的两个问题：导出历史、越队错误信息 + 重启后导出、日志一致性）：

```bash
python demo2.py
```

馆藏批量导入导出测试（覆盖导出、dry-run、冲突回滚、重启后读取、日志一致性）：

```bash
python demo3.py
```

非法数值冲突回归测试（验证 invalid_copies/invalid_borrow_days/invalid_retain_hours 返回 conflicts 明细而非 400 错误）：

```bash
python demo4.py
```

完整快照迁移回归测试（覆盖完整快照导出、dry-run 预检、冲突回滚、重启后队列顺序/可借状态/日志一致性）：

```bash
python demo5.py
```

迁移预检报告回归测试（覆盖空快照、混合冲突、重复预约、黑名单原因不一致、dry-run 不写入、正式导入回滚、队列顺序核对、可借状态核对、日志过滤核对、服务重启一致性）：

```bash
python demo6.py
```

快照迁移扎实版回归测试（覆盖：
- 日志异常：字符串混入 / 缺字段 / 类型错 / 时间乱序 / 引用不存在书目 / 重复 log_id
- 三方口径一致：预检 / dry-run / 正式导入，冲突判断 + summary 统计 + 日志过滤 完全一致
- 文件完整性：dry-run / 预检 后 data/ 下所有 JSON 文件的 SHA256 / 大小 / 修改时间 完全不变
- 完整链路：导出 → 预检 → dry-run → 正式导入 → 重启验证
- 队列顺序 / 可借状态 / 日志过滤 / 黑名单 四项一致性深度核对
- 服务重启后重复提交：冲突检测有效，回滚完整
- 配置切换后重跑：新增书目可正常导入，原有数据不被影响
- 混合场景：有效/无效日志 + 预约/黑名单冲突 同时出现，口径一致）：

```bash
python demo7.py
```

快照正式导入完整回归测试（覆盖：
- 正式导入成功（200）/ 冲突（409）/ 格式错误（400）三条路径均返回完整 report
- 三方口径一致：预检 / dry-run / 正式导入 report 结构和统计完全相同
- 空目标环境首次导入：report 内容与实际落库一致
- 混合有效无效日志：report 明细完整，dry-run 不落库
- 服务重启后重复提交：冲突判断一致，回滚完整
- 切换配置后重跑：新增可导入，原有不被影响
- 日志文件核对：import_snapshot 日志无串味
- 关键状态核对：队列顺序、可借状态、黑名单均正确）：

```bash
python demo8.py
```

批次管理完整回归测试（覆盖：
- 预检硬门槛：`borrow_days`、`retain_hours`、`total_copies` 配置值沿用普通导入限制，任一条不合规只产出冲突 report，批次/库存/借阅策略/日志 JSON 都不落盘
- 可靠撤销：已导入成功的批次支持完整回滚，回滚后批次状态、导出快照、API 日志、文件日志四方一致
- 幂等撤销：重复撤销返回已有结果，不新增汇总记录
- 覆盖场景：dry-run 后正式导入、带重复 ISBN 的快照、重启服务后撤销、切换配置再导入、有效记录夹着坏记录）：

```bash
python demo9.py
```

## 数据文件位置

所有持久化数据以 UTF-8 JSON 格式存储在项目目录下的 `data/` 文件夹，服务重启后完整恢复。

| 文件 | 内容 |
|------|------|
| `data/books.json` | 馆藏书目配置（book_id、书名、副本数、借期、保留时长） |
| `data/reservations.json` | 预约/借阅记录（状态：waiting / available / borrowed / returned / expired / cancelled） |
| `data/blacklist.json` | 黑名单（读者 ID、原因、加入时间） |
| `data/logs.json` | 所有操作日志（包含成功与失败，支持按书目、读者过滤） |
| `data/batches.json` | 导入批次记录（批次ID、状态、导入明细、回滚信息等） |

要完全重置数据，只需删除 `data/` 目录下的所有 `.json` 文件并重启服务。

## HTTP API 一览

基础 URL：`http://127.0.0.1:5000`，所有请求/响应均为 JSON。

### 馆藏管理

| 方法 | 路径 | 说明 | 请求体 |
|------|------|------|--------|
| POST | `/api/books` | 添加书目 | `{"book_id","title","total_copies","borrow_days","retain_hours"}` |
| PUT | `/api/books/<book_id>` | 修改书目（字段可选） | `{"title","total_copies","borrow_days","retain_hours"}` |
| DELETE | `/api/books/<book_id>` | 删除书目 | — |
| GET | `/api/books` | 列出所有书目 | — |
| GET | `/api/books/<book_id>` | 查询单个书目 | — |

### 预约队列

| 方法 | 路径 | 说明 | 请求体 / 参数 |
|------|------|------|---------------|
| POST | `/api/reserve` | 读者预约 | `{"book_id","reader_id"}` |
| GET | `/api/queue/<book_id>` | 查看某书完整队列（含位置） | — |
| GET | `/api/position/<book_id>/<reader_id>` | 查看读者在某书队列中的位置（0=已待取/已借出，≥1=等待位置，404=不在队列） | — |
| DELETE | `/api/reserve/<reservation_id>?reader_id=` | 取消预约 | query: reader_id |

### 借出归还

| 方法 | 路径 | 说明 | 请求体 |
|------|------|------|--------|
| POST | `/api/checkout` | 借出（仅 status=available 的读者可借，等待中越队会被拒绝并说明队首） | `{"book_id","reader_id"}` |
| POST | `/api/return` | 归还（归还后自动触发下一位晋级） | `{"book_id","reader_id"}` |

### 黑名单

| 方法 | 路径 | 说明 | 请求体 |
|------|------|------|--------|
| POST | `/api/blacklist` | 加入黑名单 | `{"reader_id","reason"}` |
| DELETE | `/api/blacklist/<reader_id>` | 移出黑名单 | — |
| GET | `/api/blacklist` | 查看黑名单 | — |

### 日志与导出

| 方法 | 路径 | 说明 | 参数 |
|------|------|------|------|
| GET | `/api/logs` | 查询操作日志 | `book_id`(可选)、`reader_id`(可选)、`limit`(可选，默认 100) |
| GET | `/api/export/<book_id>` | 导出某书队列快照 + 完整操作历史（含配置、预约、借出、归还、过期释放、晋级待取，按时间正序） | — |
| POST | `/api/expire` | 手动触发过期释放（同时自动晋级下一位） | — |

### 馆藏批量导入导出（v1.2 新增）

| 方法 | 路径 | 说明 | 参数 |
|------|------|------|------|
| GET | `/api/collection/export` | 批量导出全部馆藏配置、实时统计和队列摘要 | — |
| POST | `/api/collection/import` | 批量导入馆藏配置（支持 dry-run 预检） | `dry_run`(可选，`true`/`false`，默认 `false`) |

### 完整快照迁移（v2.0 新增）

| 方法 | 路径 | 说明 | 参数 |
|------|------|------|------|
| GET | `/api/snapshot/export` | 导出完整快照（书目配置 + 活跃预约 + 黑名单 + 相关状态日志） | — |
| POST | `/api/snapshot/import` | 导入完整快照（支持 dry-run 预检，整批回滚） | `dry_run`(可选，`true`/`false`，默认 `false`) |
| POST | `/api/snapshot/precheck` | 迁移预检报告（不落库，按书目/预约/黑名单/日志四块展示差异明细和可读摘要） | — |

### 导入批次管理（v3.0 新增）

| 方法 | 路径 | 说明 | 参数 |
|------|------|------|------|
| GET | `/api/batches` | 列出所有导入批次（按时间倒序） | `limit`(可选，默认 100) |
| GET | `/api/batches/<batch_id>` | 查询单个批次详情（含完整导入明细） | — |
| GET | `/api/batches/<batch_id>/export` | 导出某个批次的完整快照（与导入时一致） | — |
| POST | `/api/batches/<batch_id>/rollback` | 回滚指定批次（幂等，有冲突时拦截） | — |

### 导入演练沙箱（v4.0 新增）

| 方法 | 路径 | 说明 | 参数 |
|------|------|------|------|
| POST | `/api/sandbox` | 创建演练沙箱（基于快照，与正式数据完全隔离） | `{"snapshot": {...}, "name": 可选}` |
| GET | `/api/sandbox` | 列出所有演练沙箱 | `limit`(可选，默认 100) |
| GET | `/api/sandbox/<sandbox_id>` | 查询沙箱详情（含演练结果和数据统计） | — |
| POST | `/api/sandbox/<sandbox_id>/precheck` | 沙箱内运行预检（不落盘，仅产出报告） | — |
| POST | `/api/sandbox/<sandbox_id>/dryrun` | 沙箱内运行 Dry-Run（不改变正式数据） | — |
| POST | `/api/sandbox/<sandbox_id>/import` | 沙箱内执行正式导入（仅写入沙箱独立目录） | — |
| POST | `/api/sandbox/<sandbox_id>/rollback` | 沙箱内回滚导入（幂等，冲突时拦截） | — |
| POST | `/api/sandbox/<sandbox_id>/restart-verify` | 沙箱重启验证（数据一致性 + 配置过期检查） | — |
| GET | `/api/sandbox/<sandbox_id>/export` | 导出完整演练结果（含所有阶段报告和最终结论） | — |
| DELETE | `/api/sandbox/<sandbox_id>` | 销毁演练沙箱（清理独立目录和元数据） | — |

---

## 馆藏批量导入导出接口详解

### GET `/api/collection/export` - 批量导出馆藏

**功能说明**：导出所有书目的完整配置、当前可借/待取/等待统计和每本书的队列摘要。输出为稳定的 JSON 格式，按 `book_id` 排序，可用于环境迁移。

**请求示例**：
```bash
curl http://127.0.0.1:5000/api/collection/export
```

**响应示例**（HTTP 200）：
```json
{
  "ok": true,
  "data": {
    "export_time": "2026-06-19T08:30:00.123456+00:00",
    "version": "1.0",
    "total_books": 3,
    "books": [
      {
        "book_id": "IMPORT-B001",
        "title": "Python编程从入门到实践",
        "total_copies": 5,
        "borrow_days": 30,
        "retain_hours": 24,
        "stats": {
          "available_copies": 3,
          "to_pick_count": 1,
          "waiting_count": 1,
          "borrowed_count": 1
        },
        "queue_summary": {
          "total_active": 3,
          "waiting": [
            {"reader_id": "R-TEST-02", "position": 1, "created_at": "2026-06-19T08:25:00Z"}
          ],
          "available": [
            {"reader_id": "R-TEST-01", "expire_at": "2026-06-20T08:25:00Z", "created_at": "2026-06-19T08:20:00Z"}
          ],
          "borrowed": [
            {"reader_id": "R-TEST-03", "borrowed_at": "2026-06-18T10:00:00Z", "created_at": "2026-06-18T09:00:00Z"}
          ]
        }
      }
    ]
  }
}
```

**响应字段说明**：
- `export_time`: 导出时间（UTC ISO 格式）
- `version`: 导出格式版本
- `total_books`: 导出的书目总数
- `books[].stats`: 实时统计
  - `available_copies`: 当前可立即借出的副本数
  - `to_pick_count`: 待取状态（available）的预约数
  - `waiting_count`: 等待排队数
  - `borrowed_count`: 已借出数
- `books[].queue_summary`: 队列摘要（不含敏感或冗余信息）

---

### POST `/api/collection/import` - 批量导入馆藏

**功能说明**：批量导入多本书的馆藏配置。支持 `dry_run=true` 进行预检，不实际写入数据。遇到冲突时全部回滚，返回清晰的冲突列表。

**Query 参数**：
- `dry_run`: 可选，`true` 表示仅校验不写入，`false`（默认）表示正式导入

**请求体格式**：
```json
{
  "version": "1.0",
  "books": [
    {
      "book_id": "B001",
      "title": "书名",
      "total_copies": 5,
      "borrow_days": 30,
      "retain_hours": 24
    }
  ]
}
```

**必填字段校验**：
- `book_id`: 非空字符串，全局唯一
- `title`: 非空字符串
- `total_copies`: 正整数（≥1）
- `borrow_days`: 正整数（≥1）
- `retain_hours`: 非负整数（≥0）

#### 请求示例 - Dry-Run 预检

```bash
curl -X POST http://127.0.0.1:5000/api/collection/import?dry_run=true \
  -H "Content-Type: application/json" \
  -d '{
    "books": [
      {"book_id":"NEW-B001","title":"新书1","total_copies":3,"borrow_days":14,"retain_hours":12},
      {"book_id":"NEW-B002","title":"新书2","total_copies":5,"borrow_days":30,"retain_hours":24}
    ]
  }'
```

**Dry-Run 通过响应**（HTTP 200）：
```json
{
  "ok": true,
  "imported_count": 2,
  "dry_run": true
}
```

#### 请求示例 - 正式导入

```bash
curl -X POST http://127.0.0.1:5000/api/collection/import?dry_run=false \
  -H "Content-Type: application/json" \
  -d '{
    "books": [
      {"book_id":"NEW-B001","title":"新书1","total_copies":3,"borrow_days":14,"retain_hours":12},
      {"book_id":"NEW-B002","title":"新书2","total_copies":5,"borrow_days":30,"retain_hours":24}
    ]
  }'
```

**导入成功响应**（HTTP 200）：
```json
{
  "ok": true,
  "imported_count": 2,
  "dry_run": false
}
```

#### 冲突响应 - 重复 book_id（HTTP 409）

```json
{
  "ok": false,
  "error": "导入存在冲突",
  "conflicts": [
    {
      "type": "duplicate_book_id",
      "book_id": "B001",
      "index": 0,
      "message": "书目 B001 已存在",
      "existing_config": {
        "book_id": "B001",
        "title": "已存在的书",
        "total_copies": 2,
        "borrow_days": 7,
        "retain_hours": 1
      },
      "import_config": {
        "title": "冲突的书名",
        "total_copies": 5,
        "borrow_days": 30,
        "retain_hours": 24
      }
    }
  ],
  "dry_run": false
}
```

#### 冲突类型说明

| 冲突类型 | 说明 | HTTP 状态码 |
|----------|------|------------|
| `duplicate_in_import` | 导入文件内部存在重复的 `book_id` | 409 |
| `duplicate_book_id` | 要导入的 `book_id` 在系统中已存在 | 409 |
| `has_active_reservations` | 书目已有活跃预约（等待/待取/借阅中），不能覆盖 | 409 |
| `invalid_copies` | `total_copies` 非法（≤0） | 409 |
| `invalid_borrow_days` | `borrow_days` 非法（≤0） | 409 |
| `invalid_retain_hours` | `retain_hours` 非法（<0） | 409 |
| `race_condition` | 导入过程中并发创建了相同 `book_id` | 409 |
| `import_error` | 导入过程中发生异常，已全部回滚 | 409 |

**重要特性**：
- **原子性**：只要有一本书导入失败，所有书全部回滚，不会出现"写一半"的情况
- **并发安全**：正式导入时加锁，且导入前二次校验，防止并发冲突
- **日志完整**：每本书的导入都有单独日志（`action: import_book`），整个批量导入也有汇总日志（`action: import_collection`），均可按 `book_id` 查询

---

## 本地验证办法

### 1. 准备导出数据

先启动服务并创建几本书：

```bash
# 启动服务
python main.py &

# 添加几本书
curl -X POST http://127.0.0.1:5000/api/books \
  -H "Content-Type: application/json" \
  -d '{"book_id":"B001","title":"测试书1","total_copies":3,"borrow_days":14,"retain_hours":12}'

curl -X POST http://127.0.0.1:5000/api/books \
  -H "Content-Type: application/json" \
  -d '{"book_id":"B002","title":"测试书2","total_copies":5,"borrow_days":30,"retain_hours":24}'

# 预约几本书，制造队列数据
curl -X POST http://127.0.0.1:5000/api/reserve \
  -H "Content-Type: application/json" \
  -d '{"book_id":"B001","reader_id":"R001"}'
```

### 2. 导出馆藏

```bash
# 导出到文件
curl http://127.0.0.1:5000/api/collection/export | jq '.data' > collection_export.json

# 查看导出内容
cat collection_export.json
```

### 3. Dry-Run 预检导入

清空数据后，用导出的文件做预检：

```bash
# 清空 data 目录
rm -f data/*.json

# 重启服务
python main.py &

# Dry-Run 预检
curl -X POST http://127.0.0.1:5000/api/collection/import?dry_run=true \
  -H "Content-Type: application/json" \
  -d "$(cat collection_export.json)"

# 验证 dry-run 未实际写入
curl http://127.0.0.1:5000/api/books
# 应返回 []
```

### 4. 正式导入

```bash
# 正式导入
curl -X POST http://127.0.0.1:5000/api/collection/import?dry_run=false \
  -H "Content-Type: application/json" \
  -d "$(cat collection_export.json)"

# 验证导入成功
curl http://127.0.0.1:5000/api/books
# 应返回 2 本书
```

### 5. 验证冲突回滚

```bash
# 尝试重复导入（应有冲突）
curl -X POST http://127.0.0.1:5000/api/collection/import \
  -H "Content-Type: application/json" \
  -d '{"books":[{"book_id":"B001","title":"冲突书","total_copies":1,"borrow_days":7,"retain_hours":1}]}'

# 验证书目数量未变
curl http://127.0.0.1:5000/api/books | jq '.data | length'
# 应返回 2
```

### 6. 验证重启后数据持久化

```bash
# 停止服务后重启
# （先 kill 掉之前的进程，再重新启动）

# 验证书目仍在
curl http://127.0.0.1:5000/api/books | jq '.data | length'
# 应返回 2
```

### 7. 验证日志可查询

```bash
# 查询批量导入日志
curl "http://127.0.0.1:5000/api/logs?limit=50" | jq '.data[] | select(.action=="import_collection")'

# 按 book_id 查询单本书导入日志
curl "http://127.0.0.1:5000/api/logs?book_id=B001&limit=10" | jq '.data[] | select(.action=="import_book")'
```

### 8. 一键运行完整测试

```bash
python demo3.py
```

该脚本覆盖以下 13 个测试场景：
1. 批量导出空馆藏 - 验证导出格式
2. DRY-RUN 导入校验 - 不实际写入数据
3. 正式批量导入 - 成功导入多本书
4. 批量导出完整馆藏 - 验证统计和队列摘要
5. 冲突检测 - 重复 book_id
6. 冲突检测 - 非法副本数
7. 冲突检测 - 已有活跃预约的书目不能覆盖
8. 冲突检测 - 导入文件内部重复 book_id
9. 服务重启后导入的配置仍然存在
10. 日志一致性 - 导入操作日志可按 book_id 查询
11. 导出 JSON 稳定性 - 多次导出顺序一致
12. DRY-RUN 与正式导入结果一致
13. 导入数据格式校验 - 错误格式快速失败

## 状态流转

```
         有空闲副本            到期未取
waiting ──────────► available ──────────► expired
         自动晋级                │
                                 │ 读者在保留期内借出
                                 ▼
                              borrowed ────► returned
                                 读者归还
```

- 同一读者对同一书目只能有一条活跃记录（waiting/available/borrowed），重复预约会被拒绝。
- 黑名单读者的预约、借出操作都会被拒绝。
- 等待中的读者尝试越队借出会被拒绝，错误信息会明确告知当前队首应借出的读者。
- 队列顺序由 `created_at` 决定，任何失败操作都不会改变队列顺序。

## 本次修复要点（对应 v1.1）

**问题 1 修复**：`GET /api/export/<book_id>` 响应中新增 `history` 字段，包含该书目从配置、预约、借出、归还、过期释放到晋级待取的完整操作历史，按时间正序排列。服务重启后这些历史（来自 `data/logs.json`）依然能完整导出。

**问题 2 修复**：等待中的读者尝试越队借出时，错误信息会直接说明"当前队首应借出的读者是 XXX"，帮助调用方正确判断顺序，同时队列保持不变。

## 本次新增要点（对应 v1.2）

**馆藏批量导入导出能力**：

1. **批量导出** (`GET /api/collection/export`)
   - 生成稳定的 JSON 格式，按 `book_id` 排序，输出可预测
   - 包含完整书目配置（book_id、title、total_copies、borrow_days、retain_hours）
   - 包含实时统计（可借副本数、待取数、等待数、已借出数）
   - 包含每本书的队列摘要（等待/待取/借阅中状态，读者ID、位置、时间等）

2. **批量导入** (`POST /api/collection/import`)
   - 支持 `dry_run=true` 预检模式，只校验不写入
   - 冲突检测全面：重复 `book_id`、导入文件内部重复、非法副本数、已有活跃预约
   - **原子性保证**：只要有一本书冲突或出错，所有书全部回滚，绝不写一半数据
   - 冲突列表清晰：包含冲突类型、`book_id`、索引位置、现有配置、导入配置、错误信息
   - 并发安全：加锁 + 二次校验，防止并发创建冲突

3. **日志完整性**
   - 批量导入汇总日志 (`action: import_collection`)，记录成功/失败/回滚
   - 单本书导入日志 (`action: import_book`)，可按 `book_id` 查询
   - Dry-Run 操作也有日志记录 (`action: import_collection_dry_run`)

4. **持久化保证**
   - 导入的书目配置写入 `data/books.json`，服务重启后完整恢复
   - 所有操作日志写入 `data/logs.json`，重启后可追溯

5. **测试覆盖** (`demo3.py`)
   - 13 个测试场景，覆盖导出、dry-run、冲突回滚、重启读取、日志一致性
   - 一键运行：`python demo3.py`

---

## 完整快照迁移接口详解（v2.0 新增）

### GET `/api/snapshot/export` - 导出完整快照

**功能说明**：导出包含书目配置、活跃预约、黑名单和相关状态日志的完整快照。输出为稳定的 JSON 格式，按 `book_id` / `created_at` / `reader_id` 排序，可用于完整环境迁移。

**请求示例**：
```bash
curl http://127.0.0.1:5000/api/snapshot/export
```

**响应示例**（HTTP 200）：
```json
{
  "ok": true,
  "data": {
    "export_time": "2026-06-19T10:00:00.123456+00:00",
    "version": "2.0",
    "type": "full_snapshot",
    "counts": {
      "books": 3,
      "active_reservations": 4,
      "blacklist": 2,
      "logs": 25
    },
    "books": [
      {
        "book_id": "B001",
        "title": "Python编程",
        "total_copies": 5,
        "borrow_days": 30,
        "retain_hours": 24
      }
    ],
    "active_reservations": [
      {
        "reservation_id": "uuid-123",
        "book_id": "B001",
        "reader_id": "R001",
        "status": "waiting",
        "created_at": "2026-06-19T09:00:00+00:00",
        "available_at": null,
        "expire_at": null,
        "borrowed_at": null,
        "returned_at": null
      }
    ],
    "blacklist": [
      {
        "reader_id": "BLACK-001",
        "reason": "逾期未还",
        "added_at": "2026-06-18T10:00:00+00:00"
      }
    ],
    "logs": [
      {
        "log_id": "log-uuid-1",
        "timestamp": "2026-06-19T09:00:00+00:00",
        "action": "reserve",
        "reader_id": "R001",
        "book_id": "B001",
        "detail": "预约成功",
        "success": true
      }
    ]
  }
}
```

**导出内容说明**：
- `books`: 完整书目配置（与 collection/export 一致）
- `active_reservations`: 仅导出活跃状态的预约（waiting/available/borrowed），包含完整的 `reservation_id`、所有时间戳和状态
- `blacklist`: 完整黑名单列表
- `logs`: 相关操作日志（所有书目的操作日志 + 黑名单相关日志 + 快照导入导出日志）

---

### POST `/api/snapshot/import` - 导入完整快照

**功能说明**：导入完整快照到目标环境。支持 `dry_run=true` 进行预检，不实际写入数据。遇到任何冲突或错误时完整回滚，绝不写入半套数据。

**Query 参数**：
- `dry_run`: 可选，`true` 表示仅校验不写入，`false`（默认）表示正式导入

**请求体格式**：与 `GET /api/snapshot/export` 的响应格式完全一致

**必填字段校验**：
- `version`: 必须为 `"2.0"`
- `type`: 必须为 `"full_snapshot"`
- `books[*]`: `book_id`, `title`, `total_copies`, `borrow_days`, `retain_hours`
- `active_reservations[*]`: `reservation_id`, `book_id`, `reader_id`, `status`, `created_at`, `available_at`, `expire_at`, `borrowed_at`, `returned_at`
- `blacklist[*]`: `reader_id`, `reason`, `added_at`

#### 请求示例 - Dry-Run 预检

```bash
curl -X POST http://127.0.0.1:5000/api/snapshot/import?dry_run=true \
  -H "Content-Type: application/json" \
  -d "$(cat snapshot.json)"
```

**Dry-Run 通过响应**（HTTP 200）：
```json
{
  "ok": true,
  "imported_counts": {
    "books": 3,
    "active_reservations": 4,
    "blacklist": 2,
    "logs": 25
  },
  "dry_run": true,
  "report": {
    "dry_run": true,
    "can_import": true,
    "summary": { ... },
    "details": { ... }
  }
}
```

> **注意**：`report` 字段结构与 `POST /api/snapshot/precheck` 的响应完全一致，dry-run 与预检共用同一套校验逻辑，口径 100% 相同。

#### 请求示例 - 正式导入

```bash
curl -X POST http://127.0.0.1:5000/api/snapshot/import?dry_run=false \
  -H "Content-Type: application/json" \
  -d "$(cat snapshot.json)"
```

**导入成功响应**（HTTP 200）：
```json
{
  "ok": true,
  "imported_counts": {
    "books": 3,
    "active_reservations": 4,
    "blacklist": 2,
    "logs": 25
  },
  "dry_run": false,
  "report": {
    "dry_run": false,
    "can_import": true,
    "summary": {
      "status": "ready",
      "message": "预检通过，可以安全导入",
      "total_will_add": 34,
      "total_will_skip": 0,
      "total_will_block": 0,
      "total_conflicts": 0,
      "total_missing_dependencies": 0,
      "total_format_errors": 0,
      "breakdown": { ... }
    },
    "details": {
      "books": { "will_add": [...], "will_skip": [], "will_block": [], "conflicts": [], "missing_dependencies": [], "format_errors": [], "issues": [] },
      "active_reservations": { "will_add": [...], ... },
      "blacklist": { "will_add": [...], ... },
      "logs": { "will_add": [...], ... }
    }
  }
}
```

> **注意**：正式导入成功响应中也包含 `report` 字段，结构与预检报告完全一致，且 `report.dry_run = false`，可用于调用方核对导入结果与预期是否一致。

#### 冲突响应 - duplicate_book_id（HTTP 409）

```json
{
  "ok": false,
  "error": "快照导入存在冲突",
  "conflicts": [
    {
      "type": "duplicate_book_id",
      "book_id": "B001",
      "section": "books",
      "index": 0,
      "existing_config": {
        "book_id": "B001",
        "title": "已存在的书",
        "total_copies": 2,
        "borrow_days": 7,
        "retain_hours": 1
      },
      "import_config": {
        "title": "导入的书",
        "total_copies": 5,
        "borrow_days": 30,
        "retain_hours": 24
      },
      "message": "目标环境已存在书目 B001"
    }
  ],
  "dry_run": false,
  "report": {
    "dry_run": false,
    "can_import": false,
    "summary": { ... },
    "details": { ... }
  }
}
```

> **注意**：冲突响应中也包含 `report` 字段，结构与预检报告完全一致。格式错误响应（HTTP 400）同理，也会返回完整的 `report`。

#### 冲突类型说明

| 冲突类型 | 说明 | HTTP 状态码 |
|----------|------|------------|
| `duplicate_book_id_in_snapshot` | 快照内部存在重复的 `book_id` | 409 |
| `duplicate_book_id` | 目标环境已存在相同 `book_id` | 409 |
| `duplicate_reservation_in_snapshot` | 快照内部存在重复预约（同一 book_id + reader_id） | 409 |
| `duplicate_reservation` | 目标环境已存在相同的活跃预约 | 409 |
| `duplicate_blacklist_in_snapshot` | 快照内部存在重复黑名单 | 409 |
| `duplicate_blacklist` | 目标环境已存在相同黑名单（原因相同） | 409 |
| `blacklist_conflict` | 目标环境已存在相同黑名单但原因不同 | 409 |
| `missing_dependency` | 预约引用了快照中不存在的书目 | 409 |
| `snapshot_import_error` | 导入过程中发生异常，已完整回滚 | 409 |

**核心特性**：
- **原子性**：只要有任何冲突或错误，所有数据全部回滚，不会出现"写一半"的情况
- **顺序一致性**：队列顺序由 `created_at` 决定，导入后与源环境完全一致
- **状态一致性**：`status` 字段完整保留（waiting/available/borrowed），可借状态计算结果与源环境一致
- **日志一致性**：
  - 仅写入汇总日志（`action: import_snapshot`，不带 book_id / reader_id），不会被按书目/读者过滤命中
  - Dry-Run 预检日志（`action: import_snapshot_dry_run`，不带 book_id / reader_id）
  - 导入异常日志（`action: import_snapshot`，不带 book_id / reader_id）
  - **同口径查询一致**：同一份快照在源环境和导入环境，按相同条件（`book_id` / `reader_id`）查询，返回结果集合完全一致
  - 快照中携带的历史操作日志完整保留，导入后可按原条件追溯
- **并发安全**：加锁 + 导入前二次校验，防止并发冲突
- **持久化保证**：所有数据写入 JSON 文件，服务重启后完整恢复

---

## 完整快照迁移使用指南

### 典型场景：A 环境 → B 环境完整迁移

#### 1. 在 A 环境导出快照

```bash
# 启动 A 环境服务（如果未启动）
python main.py &

# 导出完整快照到文件
curl http://127.0.0.1:5000/api/snapshot/export | jq '.data' > full_snapshot.json

# 查看导出统计
cat full_snapshot.json | jq '.counts'
```

#### 2. 准备 B 环境（清空数据）

```bash
# 清空 B 环境数据目录
rm -f data/*.json

# 重启 B 环境服务
python main.py &
```

#### 3. Dry-Run 预检（强烈建议）

```bash
curl -X POST http://127.0.0.1:5000/api/snapshot/import?dry_run=true \
  -H "Content-Type: application/json" \
  -d "$(cat full_snapshot.json)"
```

如果返回 HTTP 200 且 `ok: true`，说明校验通过，可以正式导入。
如果返回 HTTP 409 且有 `conflicts` 列表，需要先解决冲突（如清空目标环境数据）。

#### 4. 正式导入

```bash
curl -X POST http://127.0.0.1:5000/api/snapshot/import?dry_run=false \
  -H "Content-Type: application/json" \
  -d "$(cat full_snapshot.json)"
```

#### 5. 验证导入结果

```bash
# 验证书目数量
curl http://127.0.0.1:5000/api/books | jq '.data | length'

# 验证某书队列
curl http://127.0.0.1:5000/api/queue/B001 | jq '.data'

# 验证黑名单
curl http://127.0.0.1:5000/api/blacklist | jq '.data'

# 验证可借状态
curl "http://127.0.0.1:5000/api/books/B001" | jq '.data.total_copies'

# 验证日志可查询
curl "http://127.0.0.1:5000/api/logs?book_id=B001&limit=10" | jq '.data'
```

#### 6. 验证重启后一致性

```bash
# 重启服务
# （先 kill 掉之前的进程，再重新启动）

# 再次验证所有数据
# 队列顺序、可借状态、日志查询结果应与重启前完全一致
```

### 一键运行完整测试

```bash
python demo5.py
```

该脚本覆盖以下 11 个测试场景：
1. 导出完整快照 - 验证格式和内容正确性
2. Dry-Run 导入 - 校验通过但不落库
3. 正式导入 - 验证数据完整且顺序一致
4. 冲突检测 - duplicate_book_id
5. 冲突检测 - duplicate_reservation
6. 冲突检测 - blacklist_conflict
7. 冲突检测 - missing_dependency
8. 混合冲突 - 多种冲突同时存在时全部返回
9. 服务重启后 - 队列顺序、可借状态、日志完全一致
10. 导入数据可正常使用 - 预约、借出功能正常
11. 完整迁移流程模拟 - A 环境导出 → B 环境导入

---

## 迁移预检报告接口详解（v2.1 新增）

### POST `/api/snapshot/precheck` - 迁移预检报告

**功能说明**：提交与 `/api/snapshot/import` 同格式的 JSON，获得不落库的详细差异报告。报告按书目、活跃预约、黑名单、日志四块分类，每块细分"将新增、冲突、缺依赖、格式错误"四类明细，并提供可读的 summary 摘要，帮助用户在正式导入前全面了解差异。

**核心特性**：
- **复用校验逻辑**：与正式导入共用同一套校验和冲突判断函数，口径完全一致，绝无"dry-run 通过但正式导入马上失败"的情况
- **四块分类**：书目、活跃预约、黑名单、日志，每块独立统计
- **三类明细**：
  - **will_add（将新增）**：格式正确且无冲突，会被导入的记录
  - **will_skip（将跳过）**：因冲突/依赖缺失等原因不会被导入的记录
  - **will_block（将拦下）**：因格式错误被拦下的记录
- **可读摘要**：summary 包含状态、消息、总数、分类统计
- **队列顺序核对**：按 `created_at` 展示每本书的队列顺序，方便核对
- **可借状态核对**：计算每本书的借出/待取/等待/可借数量，辅助验证状态一致性
- **完全不落库**：仅校验不写入，所有数据（含日志）保持原状
- **服务重启后一致**：预检依赖的数据与正式导入结果一致，重启后不变

**请求体格式**：与 `GET /api/snapshot/export` 的响应格式完全一致（即与 `POST /api/snapshot/import` 的请求格式相同）

**请求示例**：

```bash
curl -X POST http://127.0.0.1:5000/api/snapshot/precheck \
  -H "Content-Type: application/json" \
  -d "$(cat snapshot.json)"
```

**响应示例 - 预检通过（HTTP 200）**：

```json
{
  "ok": true,
  "data": {
    "dry_run": true,
    "can_import": true,
    "summary": {
      "status": "ready",
      "message": "预检通过，可以安全导入",
      "total_will_add": 10,
      "total_will_skip": 0,
      "total_will_block": 0,
      "total_conflicts": 0,
      "total_missing_dependencies": 0,
      "total_format_errors": 0,
      "total_log_issues": 0,
      "breakdown": {
        "books": { "will_add": 2, "will_skip": 0, "will_block": 0, "conflicts": 0, "missing_dependencies": 0, "format_errors": 0, "issues": 0 },
        "active_reservations": { "will_add": 4, "will_skip": 0, "will_block": 0, "conflicts": 0, "missing_dependencies": 0, "format_errors": 0, "issues": 0 },
        "blacklist": { "will_add": 1, "will_skip": 0, "will_block": 0, "conflicts": 0, "missing_dependencies": 0, "format_errors": 0, "issues": 0 },
        "logs": { "will_add": 3, "will_skip": 0, "will_block": 0, "conflicts": 0, "missing_dependencies": 0, "format_errors": 0, "issues": 0 }
      },
      "queue_order_check": {
        "B001": {
          "total_active": 3,
          "waiting_count": 2,
          "order_by_created_at": [
            {"reader_id": "R001", "status": "borrowed", "created_at": "2026-06-19T08:00:00+00:00"},
            {"reader_id": "R002", "status": "waiting", "created_at": "2026-06-19T09:00:00+00:00"}
          ],
          "is_ordered_by_created_at": true
        }
      },
      "availability_check": {
        "B001": {
          "total_copies": 5,
          "borrowed": 1,
          "to_pick": 1,
          "waiting": 2,
          "available_copies": 3,
          "has_overflow": false
        }
      }
    },
    "details": {
      "books": {
        "will_add": [
          {"book_id": "B001", "title": "Python编程", "total_copies": 5, "borrow_days": 30, "retain_hours": 24}
        ],
        "will_skip": [],
        "will_block": [],
        "conflicts": [],
        "missing_dependencies": [],
        "format_errors": [],
        "issues": []
      },
      "active_reservations": {
        "will_add": [
          {"reservation_id": "uuid-1", "book_id": "B001", "reader_id": "R001", "status": "borrowed", "created_at": "..."}
        ],
        "will_skip": [],
        "will_block": [],
        "conflicts": [],
        "missing_dependencies": [],
        "format_errors": [],
        "issues": []
      },
      "blacklist": {
        "will_add": [
          {"reader_id": "BLACK-001", "reason": "逾期未还", "added_at": "..."}
        ],
        "will_skip": [],
        "will_block": [],
        "conflicts": [],
        "missing_dependencies": [],
        "format_errors": [],
        "issues": []
      },
      "logs": {
        "will_add": [
          {"log_id": "log-1", "action": "reserve", "timestamp": "...", "book_id": "B001", "reader_id": "R001"}
        ],
        "will_skip": [],
        "will_block": [],
        "conflicts": [],
        "missing_dependencies": [],
        "format_errors": [],
        "issues": []
      }
    }
  }
}
```

**响应示例 - 有冲突（HTTP 200，注意：预检始终返回 200，冲突在报告内）**：

```json
{
  "ok": true,
  "data": {
    "dry_run": true,
    "can_import": false,
    "summary": {
      "status": "has_conflicts",
      "message": "存在冲突，需解决冲突后再导入",
      "total_will_add": 5,
      "total_conflicts": 2,
      "total_missing_dependencies": 1,
      "total_format_errors": 0,
      "breakdown": { ... }
    },
    "details": {
      "books": {
        "will_add": [...],
        "conflicts": [
          {
            "type": "duplicate_book_id",
            "book_id": "B001",
            "section": "books",
            "existing_config": { ... },
            "import_config": { ... },
            "message": "目标环境已存在书目 B001"
          }
        ],
        "missing_dependencies": [],
        "format_errors": []
      },
      "active_reservations": {
        "will_add": [...],
        "conflicts": [...],
        "missing_dependencies": [
          {
            "type": "missing_dependency",
            "book_id": "NONEXIST-B001",
            "reader_id": "R-TEST-001",
            "section": "active_reservations",
            "message": "预约记录引用了快照中不存在的书目 NONEXIST-B001"
          }
        ],
        "format_errors": []
      },
      ...
    }
  }
}
```

**summary.status 取值说明**：

| 状态 | 说明 | can_import |
|------|------|------------|
| `ready` | 预检通过，可以安全导入 | `true` |
| `has_conflicts` | 存在冲突，需解决后再导入 | `false` |
| `missing_dependency` | 存在缺失依赖，需补充数据 | `false` |
| `format_error` | 存在格式错误，需先修正数据格式 | `false` |

**冲突类型一览**：与 `POST /api/snapshot/import` 的冲突类型完全一致（共用同一套检测逻辑）

---

### 一键运行预检报告测试

```bash
python demo6.py
```

该脚本覆盖以下 13 个测试场景：
1. 预检报告 API 存在且可调用
2. 空快照预检 - 验证格式和零数据场景
3. 完整快照预检 - 全部新增场景，验证 will_add 明细
4. 混合冲突预检 - 书目冲突 + 预约冲突 + 黑名单冲突 + 缺依赖同时存在
5. 重复预约检测 - 快照内重复预约识别
6. 黑名单原因不一致检测
7. 格式错误预检 - 非法格式的识别与分类
8. 预检与正式导入口径一致 - 预测结果与实际导入完全匹配
9. 预检不落库验证 - dry-run 不写入任何数据
10. 正式导入冲突回滚验证 - 冲突时完整回滚
11. 队列顺序和可借状态核对 - 导出-导入链路一致性
12. 服务重启后预检结果一致
13. 日志过滤结果核对

---

## 本次新增要点（对应 v2.1）

**迁移预检报告能力**：

1. **预检报告 API** (`POST /api/snapshot/precheck`)
   - 提交与导入同格式的 JSON，获得不落库的详细差异报告
   - 完全复用正式导入的校验和冲突判断逻辑，口径 100% 一致
   - 绝无"预检通过但正式导入失败"的口径差

2. **四块四类清晰展示**
   - **四块**：书目、活跃预约、黑名单、日志
   - **四类**：will_add（将新增）、conflicts（冲突）、missing_dependencies（缺依赖）、format_errors（格式错误）
   - 每块独立统计，明细清晰可追溯

3. **可读摘要 summary**
   - 状态标识：ready / has_conflicts / missing_dependency / format_error
   - 人性化消息，一目了然
   - 总数统计 + 分类明细 breakdown
   - 队列顺序核对（queue_order_check）：按 created_at 展示每本书队列顺序
   - 可借状态核对（availability_check）：借出/待取/等待/可借数量计算

4. **一致性保证**
   - **口径一致**：预检与正式导入共用 `_analyze_snapshot_conflicts` 函数
   - **数据一致**：预检依赖的数据与正式导入结果一致，服务重启后不变
   - **导出-导入链路一致**：可用于核对队列顺序、可借状态、日志过滤结果

5. **完全不落库**
   - 预检仅做校验分析，不写入任何数据
   - `data/` 目录下所有 JSON 文件保持不变（包括 logs.json）

6. **测试覆盖** (`demo6.py`)
   - 13 个测试场景，覆盖空快照、混合冲突、重复预约、黑名单原因不一致、格式错误、dry-run 不写入、正式导入回滚、队列顺序核对、可借状态核对、日志过滤核对、服务重启一致性
   - 一键运行：`python demo6.py`

---

## 本次新增要点（对应 v2.0）

**完整快照迁移能力**：

1. **完整快照导出** (`GET /api/snapshot/export`)
   - 导出全部书目配置
   - 导出所有活跃预约（waiting/available/borrowed），包含完整 `reservation_id`、时间戳和状态
   - 导出完整黑名单
   - 导出相关操作日志
   - 稳定的 JSON 格式，按可预测的键排序

2. **完整快照导入** (`POST /api/snapshot/import`)
   - 支持 `dry_run=true` 预检模式，只校验不写入
   - 冲突检测全面：
     - `duplicate_book_id`: 目标已有相同书目
     - `duplicate_reservation`: 目标已有相同活跃预约
     - `blacklist_conflict`: 目标已有相同黑名单但原因不同
     - `missing_dependency`: 预约引用不存在的书目
     - 以及快照内部重复检测
   - **原子性保证**：只要有任何冲突或错误，所有数据全部回滚，绝不写半套数据
   - 并发安全：加锁 + 二次校验，防止并发冲突

3. **一致性保证**
   - **队列顺序一致**：按 `created_at` 排序，导入后与源环境完全一致，重启后保持不变
   - **可借状态一致**：`status` 字段完整保留，可借副本数计算结果与源环境一致
   - **日志查询一致**：导出相关日志，导入后可追溯，重启后可查询

4. **日志一致性**
   - 仅写入批量导入汇总日志 (`action: import_snapshot`，不带 book_id)，避免按 book_id 查询时串味
   - Dry-Run 操作日志 (`action: import_snapshot_dry_run`，不带 book_id)
   - 导入过程异常日志 (`action: import_snapshot`，不带 book_id)
   - **同口径查询一致**：同一份快照在源环境和导入环境，按 `book_id` / `reader_id` 查询日志，结果集合完全一致（不会多出导入相关记录）
   - 快照中携带的历史日志完整保留，导入后可按原条件追溯

5. **测试覆盖** (`demo5.py`)
   - 11 个测试场景，覆盖导出、dry-run、冲突回滚、重启一致性、功能可用性
   - 一键运行：`python demo5.py`

---

## 版本对比

| 功能 | v1.0 collection | v2.0 snapshot |
|------|-----------------|---------------|
| 导出书目配置 | ✅ | ✅ |
| 导出实时统计 | ✅ | ❌（专注迁移） |
| 导出队列摘要 | ✅ | ❌（专注迁移） |
| 导出完整预约 | ❌ | ✅（含 reservation_id、所有时间戳） |
| 导出黑名单 | ❌ | ✅ |
| 导出相关日志 | ❌ | ✅ |
| 导入 dry-run | ✅ | ✅ |
| 冲突回滚 | ✅ | ✅（更彻底，全量备份恢复） |
| 队列顺序一致 | ❌（仅配置） | ✅ |
| 可借状态一致 | ❌（仅配置） | ✅ |
| 适用场景 | 馆藏配置批量导入 | **完整环境迁移** |

---

## 本次新增要点（对应 v2.2）

**快照迁移扎实话 - 统一校验 + 日志健壮性 + 完整链路一致**

### 1. 预检、dry-run、正式导入 100% 共用一套校验逻辑
三方都调用同一个 `_analyze_snapshot_conflicts` 函数，返回值完全一致：
- 不会出现"预检 500 但 dry-run 说可导入"的口径差
- 不会出现"dry-run 通过但正式导入马上失败"的口径差
- 预检用 `can_import` 字段标示，dry-run/正式导入用 HTTP 400（格式错）或 409（冲突）标示，语义等价

### 2. 新增 `_validate_snapshot_log` - 单条日志完整校验

**必填字段**：`timestamp`、`action`、`success`

**单条日志错误码（format_errors 中）**：

| 错误码 | 含义 | 阻断当前日志 | 阻断其他块 |
|--------|------|-------------|-----------|
| `log_not_object` | 日志记录不是 JSON 对象（如字符串/数字混入） | ✅ 本条不导入 | ❌ 不影响 |
| `log_missing_field` | 缺少必填字段（timestamp/action/success） | ✅ 本条不导入 | ❌ 不影响 |
| `log_invalid_action_type` | action 不是非空字符串 | ✅ 本条不导入 | ❌ 不影响 |
| `log_invalid_success_type` | success 不是布尔值（true/false） | ✅ 本条不导入 | ❌ 不影响 |
| `log_invalid_timestamp_type` | timestamp 不是非空字符串 | ✅ 本条不导入 | ❌ 不影响 |
| `log_invalid_timestamp_format` | timestamp 不是合法 ISO 格式 | ✅ 本条不导入 | ❌ 不影响 |
| `log_invalid_log_id_type` | log_id 不是非空字符串 | ✅ 本条不导入 | ❌ 不影响 |
| `log_invalid_book_id_type` | book_id 不是非空字符串 | ✅ 本条不导入 | ❌ 不影响 |
| `log_invalid_reader_id_type` | reader_id 不是非空字符串 | ✅ 本条不导入 | ❌ 不影响 |
| `log_invalid_detail_type` | detail 不是字符串 | ✅ 本条不导入 | ❌ 不影响 |

**返回结构**（每条 format_error）：
```json
{
  "index": 3,
  "field": "success",
  "error_code": "log_invalid_success_type",
  "message": "日志记录 3 success 必须是布尔值（true/false），实际类型: str",
  "blocks_other_blocks": false,
  "blocks_current_block": true
}
```

### 3. 新增 `_check_log_order_and_references` - 日志块级告警（非阻断）

**issues 中返回的日志问题类型**：

| issue 类型 | 含义 | 阻断当前日志块 | 阻断其他块 |
|-----------|------|--------------|-----------|
| `log_timestamp_out_of_order` | 相邻两条日志 timestamp 顺序错乱（倒序） | ❌ 依然导入 | ❌ 不影响 |
| `log_references_missing_book` | 日志的 book_id 既不在快照 books 中，也不在目标环境 store 中 | ❌ 依然导入 | ❌ 不影响 |
| `duplicate_log_id_in_snapshot` | 快照中出现重复的 log_id | ❌ 依然导入 | ❌ 不影响 |

**阻断语义说明**：
- `blocks_other_blocks=true`：会影响书目/预约/黑名单/日志其他三大块导入
- `blocks_current_block=true`：仅本条记录不导入，同块其他记录仍然正常
- 所有日志级错误都是**非全局阻断**：不会影响书目、预约、黑名单块的正常导入

### 4. 预检接口永不返回 HTTP 500
- 内部异常全部被 try-except 捕获，转为 `status: "internal_error"` 的预检报告
- 始终返回 HTTP 200 + `ok:true`，错误细节在 `data.details.*.format_errors/issues` 内

### 5. 事务一致性保证
- **dry-run**：绝对不写库。只校验，不调用任何 save/backup 接口
- **正式导入格式错**：直接返回 error 列表，不进入写库分支
- **正式导入冲突**：直接返回 conflicts 列表，不进入写库分支
- **正式导入写库中异常**：用 `backup_all()` 备份，异常时 `restore_all()` 完整回滚，书目/预约/黑名单/日志四块一同还原

### 6. 成功后数据无漂移
- **队列顺序**：按 `created_at` 升序，导入前后完全一致，重启后不变
- **可借状态**：`available_copies = total_copies - borrowed - available`，结果与源环境一致
- **日志过滤**：按 `book_id`/`reader_id` 查询，源环境与导入环境 log_id 集合完全相等（不多不少）
- **无串味日志**：导入/预检汇总日志不带 `book_id`/`reader_id`，不会被条件过滤命中
- **黑名单**：reader_id 集合与原因，导入前后完全一致

### 7. 覆盖的关键链路
1. **导出 → 预检 → dry-run → 正式导入 → 重启验证**：队列/状态/日志/黑名单一致
2. **服务重启后重复提交**：冲突检测有效，回滚完整
3. **配置切换后重跑**：新增书目可正常导入，原有数据不被影响
4. **混合有效/无效日志 + 预约/黑名单冲突**：三方口径一致，错误明细完整
5. **各种日志异常场景**：字符串混入/缺字段/类型错/时间乱序/引用不存在/重复 log_id

---

## 本次新增要点（对应 v2.3）

**正式导入 report 全路径统一 - 成功/冲突/格式错误三条路径全部返回同口径 report**

### 1. 正式导入所有路径都返回完整 report

同一份快照，在以下 5 条路径中，都返回同一口径的 report：
- **预检** (`POST /api/snapshot/precheck`)：不落库，HTTP 200 + report
- **Dry-Run** (`POST /api/snapshot/import?dry_run=true`)：不落库，200/409/400 + report
- **正式导入成功** (`POST /api/snapshot/import?dry_run=false`)：落库，HTTP 200 + report
- **正式导入冲突**：回滚，HTTP 409 + report
- **正式导入格式错误**：回滚，HTTP 400 + report

所有 report 结构完全一致：包含 `summary`（摘要）和 `details`（明细），四块（books/active_reservations/blacklist/logs）六类（will_add/will_skip/will_block/conflicts/missing_dependencies/format_errors）。

### 2. report 中的 dry_run 字段能正确区分场景

- 预检：`report.dry_run = true`
- Dry-Run：`report.dry_run = true`
- 正式导入（成功/冲突/格式错误）：`report.dry_run = false`

调用方可以通过 `report.dry_run` 字段直接判断是模拟还是真实操作。

### 3. 三方口径一致性保证

预检、dry-run、正式导入 100% 共用 `_analyze_snapshot_conflicts` 校验逻辑：
- 冲突数一致：同一份快照，三者检测到的冲突数量和类型完全相同
- 统计口径一致：`will_add` / `will_skip` / `will_block` / `conflicts` / `format_errors` 计数完全一致
- 明细内容一致：每块的每条记录明细完全一致

### 4. 预检与 dry-run 绝对不落库

- **预检**：仅做校验分析，不写入任何数据
- **Dry-Run**：仅做校验分析，不写入任何数据
- **文件完整性**：预检和 dry-run 后，`data/` 目录下所有 JSON 文件（books.json / reservations.json / blacklist.json / logs.json）完全不变，包括文件大小、修改时间、内容

### 5. 正式导入落库完整

正式导入成功后，四块数据全部落到统一快照中：
- **books**：新增书目配置写入 `data/books.json`
- **active_reservations**：新增活跃预约写入 `data/reservations.json`，队列顺序与源环境一致
- **blacklist**：新增黑名单写入 `data/blacklist.json`
- **logs**：新增相关日志写入 `data/logs.json`，与源环境日志过滤结果一致

### 6. 关键链路全部补齐

1. **空目标环境首次导入**：report 内容与实际落库完全一致
2. **混合有效和无效日志**：report 明细完整，dry-run 不落库
3. **服务重启后重复提交**：冲突判断一致，回滚完整
4. **切换配置后重跑**：新增可导入，原有数据不被影响
5. **日志文件核对**：import_snapshot 日志无串味（不带 book_id/reader_id）
6. **关键状态核对**：队列顺序、可借状态、黑名单均正确

### 7. 测试覆盖

新增 `demo8.py` 回归测试脚本，覆盖 9 个核心场景：
1. 正式导入成功（200）返回完整 report
2. 正式导入冲突（409）返回完整 report
3. 正式导入格式错误（400）返回完整 report
4. 三方口径一致（预检 / dry-run / 正式导入）
5. 空目标环境首次导入
6. 混合有效和无效日志
7. 服务重启后重复提交
8. 切换配置后重跑
9. 日志文件和关键状态变化核对

一键运行：`python demo8.py`

---

## 导入批次管理接口详解（v3.0 新增）

每次成功的快照正式导入都会生成一条**批次记录**，记录导入的完整明细。你可以按批次查看详情、重新导出快照，以及安全地回滚整个批次带来的所有变化。

### 核心特性

1. **预检硬门槛**：正式写入前进行整包预检，`borrow_days`、`retain_hours`、`total_copies` 等配置值沿用普通导入的限制（`total_copies>=1`、`borrow_days>=1`、`retain_hours>=0`），任一条书目不合规时只产出冲突 report，**批次、库存、借阅策略和日志 JSON 都不落盘**（文件内容、哈希值、修改时间完全不变）
2. **批次可追溯**：每次正式导入都生成唯一批次 ID，包含完整导入明细
3. **可回滚**：一键撤销整个批次的所有数据变更（books/reservations/blacklist/logs）
4. **可靠撤销**：已导入成功的批次支持完整回滚，回滚后查批次、导出快照、看 API 日志和文件日志时，状态和数量都对得上（四方一致）
5. **冲突检测**：回滚前检查数据是否在导入后被修改过，有冲突则明确拦截并返回可读原因
6. **幂等回滚**：同一批次重复回滚返回已有结果，不新增汇总记录，不会重复生成日志或改变统计
7. **数据隔离**：回滚只影响本批次导入的数据，不影响批次之前已有的数据
8. **持久化**：批次记录写入 `data/batches.json`，服务重启后完整恢复
9. **可导出**：从批次记录重新导出与导入时完全一致的快照

---

### GET `/api/batches` - 批次列表

**功能说明**：列出所有导入批次，按创建时间倒序排列（最新的在前）。

**Query 参数**：
- `limit`: 可选，返回数量上限，默认 100

**请求示例**：
```bash
curl http://127.0.0.1:5000/api/batches
```

**响应示例**（HTTP 200）：
```json
{
  "ok": true,
  "data": [
    {
      "batch_id": "550e8400-e29b-41d4-a716-446655440000",
      "type": "snapshot_import",
      "status": "active",
      "created_at": "2026-06-19T10:00:00.123456+00:00",
      "rolled_back_at": null,
      "summary": {
        "books": 3,
        "active_reservations": 4,
        "blacklist": 2,
        "logs": 25
      }
    }
  ]
}
```

**状态说明**：

| 状态 | 说明 |
|------|------|
| `active` | 批次生效中，导入的数据在系统中 |
| `rolled_back` | 批次已回滚，导入的数据已被移除 |

---

### GET `/api/batches/<batch_id>` - 批次详情

**功能说明**：查询单个批次的完整信息，包括导入的全部明细数据。

**请求示例**：
```bash
curl http://127.0.0.1:5000/api/batches/550e8400-e29b-41d4-a716-446655440000
```

**响应示例**（HTTP 200）：
```json
{
  "ok": true,
  "data": {
    "batch_id": "550e8400-e29b-41d4-a716-446655440000",
    "type": "snapshot_import",
    "status": "active",
    "created_at": "2026-06-19T10:00:00.123456+00:00",
    "rolled_back_at": null,
    "summary": {
      "books": 2,
      "active_reservations": 2,
      "blacklist": 1,
      "logs": 2
    },
    "imported_details": {
      "books": [
        {"book_id": "B001", "title": "Python编程", "total_copies": 5, "borrow_days": 30, "retain_hours": 24}
      ],
      "active_reservations": [...],
      "blacklist": [...],
      "logs": [...]
    },
    "rollback_log_id": null
  }
}
```

**错误响应**（HTTP 404）：
```json
{
  "ok": false,
  "error": "批次不存在"
}
```

---

### GET `/api/batches/<batch_id>/export` - 导出批次快照

**功能说明**：从批次记录重新导出与导入时完全一致的完整快照，格式与 `GET /api/snapshot/export` 相同，并额外标注来源批次信息。

**请求示例**：
```bash
curl http://127.0.0.1:5000/api/batches/550e8400-e29b-41d4-a716-446655440000/export
```

**响应示例**（HTTP 200）：
```json
{
  "ok": true,
  "data": {
    "export_time": "2026-06-19T12:00:00.123456+00:00",
    "version": "2.0",
    "type": "full_snapshot",
    "source_batch_id": "550e8400-e29b-41d4-a716-446655440000",
    "source_created_at": "2026-06-19T10:00:00.123456+00:00",
    "counts": {
      "books": 2,
      "active_reservations": 2,
      "blacklist": 1,
      "logs": 2
    },
    "books": [...],
    "active_reservations": [...],
    "blacklist": [...],
    "logs": [...]
  }
}
```

---

### POST `/api/batches/<batch_id>/rollback` - 回滚批次

**功能说明**：撤销指定批次带来的所有数据变更。回滚是**幂等**的，同一批次多次回滚不会产生副作用。

回滚会移除本批次导入的：
- 书目配置（books）
- 活跃预约（active_reservations）
- 黑名单（blacklist）
- 相关日志（logs）

**回滚前冲突检测**：
在执行回滚前，系统会检查每一条批次导入的数据在导入后是否被修改过。如果有任何数据被后续操作修改过，回滚会被**拦截**，并返回清晰的冲突明细和可读原因。

**冲突类型**：

| 冲突类型 | 说明 |
|----------|------|
| `book_modified` | 书目配置在导入后被修改过 |
| `book_missing` | 书目已不存在（可能已被手动删除） |
| `reservation_modified` | 预约状态在导入后发生变化（如已借出、已取消） |
| `reservation_missing` | 预约记录已不存在 |
| `blacklist_modified` | 黑名单记录在导入后被修改过 |
| `blacklist_missing` | 黑名单记录已不存在（可能已被移出） |

**请求示例 - 成功回滚**：
```bash
curl -X POST http://127.0.0.1:5000/api/batches/550e8400-e29b-41d4-a716-446655440000/rollback
```

**成功响应**（HTTP 200）：
```json
{
  "ok": true,
  "rollback_count": 7,
  "already_rolled_back": false,
  "message": "成功回滚 7 条记录",
  "batch": {
    "batch_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "rolled_back",
    "rolled_back_at": "2026-06-19T12:00:00.123456+00:00"
  }
}
```

**请求示例 - 重复回滚（幂等）**：

第二次调用同一回滚接口也会返回 200，但不会实际操作数据，也不会新增日志：
```json
{
  "ok": true,
  "rollback_count": 0,
  "already_rolled_back": true,
  "message": "批次已回滚，重复操作无效",
  "batch": {
    "batch_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "rolled_back",
    "rolled_back_at": "2026-06-19T12:00:00.123456+00:00"
  }
}
```

**冲突响应**（HTTP 409）：
```json
{
  "ok": false,
  "message": "回滚存在冲突，部分数据在导入后被修改过",
  "conflicts": [
    {
      "type": "book_modified",
      "section": "books",
      "book_id": "B001",
      "changed_fields": [
        {
          "field": "title",
          "original": "Python编程",
          "current": "Python编程从入门到实践"
        }
      ],
      "message": "书目 B001 在批次导入后被修改过，无法直接回滚"
    },
    {
      "type": "reservation_modified",
      "section": "active_reservations",
      "reservation_id": "res-001",
      "book_id": "B001",
      "reader_id": "R001",
      "changed_fields": [
        {
          "field": "status",
          "original": "available",
          "current": "borrowed"
        }
      ],
      "message": "预约记录 res-001 在批次导入后状态发生变化，无法直接回滚"
    }
  ],
  "batch": {
    "batch_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "active"
  }
}
```

**重要保证**：
- **原子性**：要么全部回滚成功，要么一条都不回滚（有冲突时完全不执行回滚）
- **幂等性**：同一批次多次回滚，结果完全一致，不会重复生成日志
- **数据安全**：回滚只移除本批次导入的数据，不影响批次之前已存在的任何数据
- **日志一致**：回滚操作有独立日志（`action: rollback_batch`），不带 book_id/reader_id，不会被按书目/读者过滤命中

---

### 批次管理使用指南

#### 场景1：导入后发现有问题，需要撤销

```bash
# 1. 查看批次列表
curl http://127.0.0.1:5000/api/batches

# 2. 查看批次详情确认
curl http://127.0.0.1:5000/api/batches/<batch_id>

# 3. 执行回滚
curl -X POST http://127.0.0.1:5000/api/batches/<batch_id>/rollback
```

#### 场景2：需要重新导入同一批数据

```bash
# 1. 从旧批次导出快照
curl http://127.0.0.1:5000/api/batches/<batch_id>/export > snapshot.json

# 2. 用导出的快照重新导入
curl -X POST http://127.0.0.1:5000/api/snapshot/import \
  -H "Content-Type: application/json" \
  -d "$(cat snapshot.json | jq '.data')"
```

#### 场景3：配置切换后导入新批次，验证互不影响

```bash
# 导入批次A
curl -X POST http://127.0.0.1:5000/api/snapshot/import -d '...'
# 导入批次B
curl -X POST http://127.0.0.1:5000/api/snapshot/import -d '...'

# 回滚批次A，批次B的数据不受影响
curl -X POST http://127.0.0.1:5000/api/batches/<batch-a-id>/rollback
```

---

### 一键运行批次管理测试

```bash
python demo9.py
```

该脚本覆盖以下 20 个测试场景：
1. 批次列表 API 存在且返回空列表
2. 正式导入快照后生成批次记录
3. 批次列表展示导入的批次
4. 批次详情包含完整导入明细
5. 批次导出功能 - 导出格式与快照一致
6. 回滚批次 - 成功回滚所有数据
7. 回滚幂等性 - 重复回滚不报错
8. 批次状态更新 - 回滚后列表和详情都显示 rolled_back
9. 不存在的批次返回 404
10. 服务重启后批次数据持久化
11. 配置切换后导入 - 新增批次与已有数据互不影响
12. 回滚冲突检测 - 书目被修改后拦截回滚
13. 回滚冲突检测 - 预约状态变化后拦截
14. 混合有效/无效日志的批次导入和回滚
15. 带冲突的快照导入不生成批次
16. dry-run 导入不生成批次
17. 批次数据与实际数据一致性核对
18. 回滚后日志文件和 JSON 数据一致
19. 多个批次按时间倒序排列
20. 批次 limit 参数

---

## 本次新增要点（对应 v3.0）

**导入批次管理 - 可撤销的快照导入**

### 1. 批次记录

每次成功的正式快照导入都会生成一条批次记录，包含：
- 唯一批次 ID（UUID）
- 批次状态（active / rolled_back）
- 创建时间、回滚时间
- 数量统计摘要（books/reservations/blacklist/logs）
- **完整导入明细**：每本书、每条预约、每条黑名单、每条日志的原始数据

批次记录持久化在 `data/batches.json` 中，服务重启后完整恢复。

### 2. 批次查询与导出

- **批次列表** (`GET /api/batches`)：按时间倒序展示所有批次，支持 limit 分页
- **批次详情** (`GET /api/batches/<id>`)：查看批次完整信息，包括所有导入明细
- **批次导出** (`GET /api/batches/<id>/export`)：重新导出与导入时完全一致的快照，标注来源批次

### 3. 安全回滚机制

**回滚操作** (`POST /api/batches/<id>/rollback`)：

- **完整回滚**：同时回滚 books、reservations、blacklist、logs 四块数据
- **冲突检测**：回滚前检查每一条数据是否在导入后被修改过
  - 书目配置变更 → 拦截
  - 预约状态变化（借出/归还/取消/过期）→ 拦截
  - 黑名单修改 → 拦截
  - 数据已不存在 → 拦截
- **可读原因**：冲突响应包含变更字段明细（原值 vs 现值）和可读错误消息
- **原子性保证**：有冲突时完全不回滚，不会出现"回滚一半"的情况
- **幂等性**：同一批次多次回滚
  - 返回相同结果（already_rolled_back=true）
  - 不重复生成回滚日志
  - 不改变任何统计数据
- **数据隔离**：只移除本批次导入的数据，批次之前的已有数据完全不受影响

### 4. 日志一致性

- 回滚操作有独立日志（`action: rollback_batch`）
- 回滚日志不带 `book_id` / `reader_id`，不会被按书目/读者过滤命中
- 回滚移除的日志恰好是批次导入的日志，不多不少
- 重复回滚不新增日志，保证日志统计不被刷乱

### 5. 覆盖的关键场景

1. **配置切换后导入**：多个批次独立管理，回滚一个不影响另一个
2. **服务重启后**：批次记录、状态、明细完整恢复，回滚功能正常
3. **带冲突的回滚**：数据被修改后明确拦截，返回详细冲突明细
4. **混合有效/无效日志**：格式错误时不生成批次，冲突时也不生成批次
5. **幂等回滚**：重复调用结果一致，日志不重复，统计不漂移
6. **三方一致性**：report、日志文件、JSON 数据三处口径完全一致
7. **dry-run 不生成批次**：预检和 dry-run 操作不留下任何批次记录

### 6. 测试覆盖

新增 `demo9.py` 回归测试脚本，覆盖 20 个核心场景，验证：
- 批次明细完整性
- 撤销结果正确性
- 冲突状态准确性
- 重启后数据一致性
- 日志与 JSON 文件一致性

一键运行：`python demo9.py`

---

## 本次新增要点（对应 v3.1）

**馆藏快照导入迭代 - 预检硬门槛 + 可靠撤销**

### 1. 预检硬门槛（Hard Threshold）

正式写入前进行整包预检，所有配置值校验**不通过则完全不写入任何数据**：

- **配置值限制**：`borrow_days`、`retain_hours`、`total_copies` 沿用普通导入的限制：
  - `total_copies >= 1`（正整数）
  - `borrow_days >= 1`（正整数）
  - `retain_hours >= 0`（非负整数）
- **任一条不合规则全量拦截**：快照中只要有一本书不符合要求，**所有书都不导入**，即使其他书完全合法
- **零写入保证**：冲突/格式错误时，以下文件完全不变（内容、哈希、修改时间都不变）：
  - `data/books.json`（库存）
  - `data/reservations.json`（借阅策略）
  - `data/blacklist.json`（黑名单）
  - `data/logs.json`（日志）
  - `data/batches.json`（批次）
- **只产出冲突 report**：返回清晰的 conflicts 列表和完整的预检 report，明确告知哪条记录、哪个字段、什么原因不通过

### 2. 可靠撤销（Reliable Rollback）

已导入成功的批次支持完整回滚，回滚后**四方口径完全一致**：

- **批次状态一致**：`GET /api/batches` 和 `GET /api/batches/<id>` 都显示 `status=rolled_back`
- **导出快照一致**：`GET /api/batches/<id>/export` 仍然能导出完整的导入快照（批次记录保留）
- **API 日志一致**：`GET /api/logs` 中：
  - 批次导入的明细日志被移除
  - 批次导入的汇总日志（`import_snapshot`）被移除
  - 恰好有 1 条 `rollback_batch` 日志记录
- **文件日志一致**：`data/logs.json` 内容与 API 查询结果完全一致

### 3. 幂等撤销（Idempotent Rollback）

重复调用回滚接口不会产生副作用：

- **重复回滚返回已有结果**：第二次及以后调用回滚，返回 `already_rolled_back=true`
- **不新增汇总记录**：重复回滚不会产生新的 `rollback_batch` 日志
- **统计数据不变**：重复回滚不会改变任何计数（`rollback_count=0`）
- **状态保持一致**：批次状态始终为 `rolled_back`，不会被重复修改

### 4. 覆盖的关键场景（demo9.py 共 34 个测试）

1. **dry-run 后正式导入**：两次 dry-run 预检通过后正式导入成功，回滚后数据清零
2. **带重复 ISBN 的快照**：快照内存在重复 `book_id` 时全量拦截，无任何数据落盘
3. **重启服务后撤销**：导入后重启服务，批次记录和状态完整恢复，可正常回滚
4. **切换配置再导入**：多个批次独立管理，回滚批次 A 不影响批次 B 的数据
5. **有效记录夹着坏记录**：合法书 + 非法书（`total_copies=0`、`borrow_days=0`、`retain_hours=-1`）混合时，全部拦截，合法书也不写入
6. **三方口径一致**：预检、dry-run、正式导入的 report 和 conflicts 结构和统计完全相同
7. **文件完整性验证**：冲突时所有 JSON 文件的 SHA256 哈希和修改时间完全不变

### 5. 测试覆盖

`demo9.py` 覆盖 34 个核心场景，新增验证：

- 预检硬门槛拦截（测试 16、17）
- 文件哈希和修改时间零变化验证（测试 16、17）
- dry-run → dry-run → 正式导入链路（测试 19）
- 重复 ISBN 快照内检测（测试 16）
- 合法书与非法书混合全量拦截（测试 17、27）

一键运行：`python demo9.py`


---

## 导入演练沙箱接口详解（v4.0 新增）

在正式导入快照到生产环境之前，你可以先把完整快照导进**独立沙箱**里跑完整演练流程（预检 → Dry-Run → 正式导入 → 回滚 → 重启验证），确认一切正常后再决定是否动正式数据。沙箱与现有 `data/` 目录完全隔离，演练过程中的所有批次、冲突、日志摘要和最终结论都独立落盘，不会串进正式环境。

### 核心特性

1. **完全隔离**：每个沙箱有独立目录 `sandbox/{sandbox_id}/`，存放独立的 5 个 JSON 数据文件（books/reservations/blacklist/logs/batches）+ 演练结果 `drill_results.json`，与正式 `data/` 目录零交互
2. **完整演练链路**：预检、Dry-Run、正式导入、回滚、重启验证五阶段全流程闭环
3. **快照去重**：同一快照内容重复创建会被 409 拦截（SHA256 哈希比对）
4. **配置过期检测**：正式环境 books 配置变更后，旧沙箱标记为 stale，预检/Dry-Run/导入全部返回 410，防止基于过时配置的演练结论被误用
5. **并发控制**：每个沙箱独立的 `threading.RLock`，加全局锁管理沙箱元数据
6. **重启恢复**：服务启动时自动扫描异常中断状态（`running_*`）的沙箱，重置为 `ready`
7. **演练结果独立落盘**：`drill_results.json` 保存所有阶段的 report/conflicts/conclusion，不写入正式 logs/batches
8. **API 全生命周期管理**：创建、列表、详情、预检、Dry-Run、导入、回滚、重启验证、导出、销毁 10 个接口

### 沙箱状态机

| 状态 | 说明 |
|------|------|
| `ready` | 沙箱已创建，可执行预检/导入 |
| `running_precheck` | 正在执行预检 |
| `running_dryrun` | 正在执行 Dry-Run |
| `running_import` | 正在执行正式导入 |
| `has_conflicts` | 预检/Dry-Run 发现冲突，不可导入 |
| `imported` | 沙箱内已完成正式导入 |
| `rolled_back` | 沙箱内导入已回滚 |
| `failed` | 演练过程中出现错误 |
| `destroyed` | 沙箱已销毁（仅元数据短暂保留） |

---

### POST `/api/sandbox` - 创建演练沙箱

**功能说明**：基于完整快照创建一个独立演练沙箱，快照数据仅写入沙箱目录，不触碰正式 `data/`。

**请求体**：

```json
{
  "name": "可选的沙箱名称",
  "snapshot": {
    "version": "2.0",
    "type": "full_snapshot",
    "exported_at": "...",
    "books": [...],
    "active_reservations": [...],
    "blacklist": [...],
    "logs": [...]
  }
}
```

**成功响应**（HTTP 201）：

```json
{
  "ok": true,
  "data": {
    "sandbox_id": "uuid",
    "name": "演练测试1",
    "status": "ready",
    "created_at": "2026-...",
    "snapshot_hash": "sha256...",
    "config_signature": "sha256...",
    "config_stale": false,
    "snapshot_counts": {
      "books": 2,
      "active_reservations": 2,
      "blacklist": 1,
      "logs": 2
    },
    "data_counts": {"books": 0, "reservations": 0, "blacklist": 0, "logs": 1, "batches": 0},
    "drill_results": {
      "final_conclusion": "pending",
      "conflicts": [],
      "precheck_report": null,
      "dryrun_report": null,
      "import_report": null,
      "imported_counts": null,
      "rollback_result": null,
      "restart_verification": null
    }
  }
}
```

**错误响应**：
- HTTP 400：快照格式非法（返回 error 列表）
- HTTP 409：相同快照的沙箱已存在

---

### GET `/api/sandbox` - 列出所有演练沙箱

**Query 参数**：
- `limit`: 可选，返回数量上限，默认 100

**响应示例**（HTTP 200）：

```json
{
  "ok": true,
  "data": [
    {
      "sandbox_id": "uuid",
      "name": "演练测试1",
      "status": "ready",
      "created_at": "2026-...",
      "snapshot_counts": {...},
      "config_stale": false,
      "final_conclusion": "pending"
    }
  ]
}
```

---

### GET `/api/sandbox/<sandbox_id>` - 沙箱详情

返回沙箱完整信息，包括当前数据统计（`data_counts`）、完整演练结果（`drill_results`）、配置过期状态（`config_stale`）。

**错误响应**：HTTP 404 沙箱不存在

---

### POST `/api/sandbox/<sandbox_id>/precheck` - 沙箱预检

在沙箱内对快照执行预检，产出完整预检报告但**不落盘任何业务数据**。与正式 `POST /api/snapshot/precheck` 的报告结构完全一致。

**响应示例**（HTTP 200）：

```json
{
  "ok": true,
  "data": {
    "can_import": true,
    "status": "ready",
    "books": {"will_add": 2, "will_update": 0, "conflicts": []},
    "reservations": {...},
    "blacklist": {...},
    "logs": {...},
    "summary": {...}
  }
}
```

**错误响应**：
- HTTP 404：沙箱不存在
- HTTP 410：正式配置已变更（`config_stale=true`），此沙箱已过期不可用

---

### POST `/api/sandbox/<sandbox_id>/dryrun` - 沙箱 Dry-Run

在沙箱内模拟正式导入流程，执行完整冲突检测和校验，但**仅落盘演练结果**，不改变沙箱数据文件（除 drill_results.json）。

**成功响应**（HTTP 200）：

```json
{
  "ok": true,
  "data": {
    "counts": {"books": 2, "active_reservations": 2, "blacklist": 1, "logs": 2},
    "report": {...}
  }
}
```

**错误响应**：
- HTTP 400：快照格式错误
- HTTP 404：沙箱不存在
- HTTP 409：发现冲突，响应包含 `conflicts` 列表
- HTTP 410：正式配置已变更

---

### POST `/api/sandbox/<sandbox_id>/import` - 沙箱正式导入

在沙箱独立目录内执行完整正式导入：写入 books/reservations/blacklist/logs，并生成沙箱独立的批次记录（不写入正式 `data/batches.json`）。

**成功响应**（HTTP 200）：

```json
{
  "ok": true,
  "data": {
    "counts": {"books": 2, "active_reservations": 2, "blacklist": 1, "logs": 2},
    "report": {...},
    "batch_id": "沙箱内部批次ID-uuid",
    "final_conclusion": "imported_success"
  }
}
```

**错误响应**：
- HTTP 400：格式错误
- HTTP 404：沙箱不存在
- HTTP 409：冲突（含 conflicts 列表）或已执行过正式导入
- HTTP 410：正式配置已变更

---

### POST `/api/sandbox/<sandbox_id>/rollback` - 沙箱回滚

将沙箱内导入的数据全部回滚。支持幂等调用，回滚前检查沙箱内数据是否在导入后被修改过，有冲突则明确拦截。

**成功响应**（HTTP 200）：

```json
{
  "ok": true,
  "rollback_count": 7,
  "already_rolled_back": false,
  "status": "rolled_back",
  "final_conclusion": "rolled_back_success"
}
```

**错误响应**：
- HTTP 404：沙箱不存在
- HTTP 409：回滚冲突（数据在导入后被修改过），响应含 `conflicts` 列表

---

### POST `/api/sandbox/<sandbox_id>/restart-verify` - 沙箱重启验证

对沙箱数据执行一致性校验，确认导入/回滚后的各数据文件状态正确，并检查正式配置是否已变更。

**成功响应**（HTTP 200）：

```json
{
  "ok": true,
  "data": {
    "status": "imported",
    "verified_at": "2026-...",
    "config_stale": false,
    "data_counts": {"books": 2, "reservations": 2, "blacklist": 1, "logs": ..., "batches": 1},
    "consistency_ok": true
  }
}
```

**错误响应**：HTTP 404 沙箱不存在

---

### GET `/api/sandbox/<sandbox_id>/export` - 导出演练结果

导出沙箱的完整演练报告，包含所有阶段的执行结果、冲突明细、统计摘要和最终结论。可作为演练归档。

**响应示例**（HTTP 200）：

```json
{
  "ok": true,
  "data": {
    "sandbox_id": "uuid",
    "name": "演练测试1",
    "status": "imported",
    "created_at": "...",
    "snapshot_counts": {...},
    "data_counts": {...},
    "config_stale": false,
    "drill_results": {
      "final_conclusion": "imported_success",
      "precheck_report": {...},
      "dryrun_report": {...},
      "import_report": {...},
      "imported_counts": {...},
      "rollback_result": null,
      "restart_verification": {...},
      "conflicts": []
    }
  }
}
```

---

### DELETE `/api/sandbox/<sandbox_id>` - 销毁演练沙箱

删除沙箱独立目录下的所有数据文件和演练结果，同时从沙箱元数据中移除。**不可逆操作**。

**成功响应**（HTTP 200）：

```json
{
  "ok": true,
  "message": "沙箱 <id> 已销毁"
}
```

**错误响应**：HTTP 404 沙箱不存在

---

### 导入演练沙箱使用指南

#### 标准演练流程

```bash
# 1. 导出待迁移的源环境快照
curl http://源环境:5000/api/snapshot/export > snapshot.json

# 2. 在目标环境创建演练沙箱（不动正式数据）
curl -X POST http://目标环境:5000/api/sandbox \
  -H "Content-Type: application/json" \
  -d "{\"name\": \"生产迁移演练\", \"snapshot\": $(cat snapshot.json)}"

# 3. 预检
curl -X POST http://目标环境:5000/api/sandbox/<sandbox_id>/precheck

# 4. Dry-Run
curl -X POST http://目标环境:5000/api/sandbox/<sandbox_id>/dryrun

# 5. 沙箱内正式导入（确认各阶段报告无误后）
curl -X POST http://目标环境:5000/api/sandbox/<sandbox_id>/import

# 6. 重启验证
curl -X POST http://目标环境:5000/api/sandbox/<sandbox_id>/restart-verify

# 7. 确认没问题 → 销毁沙箱，然后正式导入
curl -X DELETE http://目标环境:5000/api/sandbox/<sandbox_id>
curl -X POST http://目标环境:5000/api/snapshot/import -d "$(cat snapshot.json)"

# 或者：演练发现问题 → 回滚 → 导出演练报告 → 销毁
curl -X POST http://目标环境:5000/api/sandbox/<sandbox_id>/rollback
curl http://目标环境:5000/api/sandbox/<sandbox_id>/export > drill-report.json
curl -X DELETE http://目标环境:5000/api/sandbox/<sandbox_id>
```

#### 目录结构

```
sandbox/
├── sandboxes.json              # 沙箱元数据总表
├── {sandbox_id}/
│   ├── books.json              # 沙箱独立馆藏（与 data/ 隔离）
│   ├── reservations.json       # 沙箱独立预约
│   ├── blacklist.json          # 沙箱独立黑名单
│   ├── logs.json               # 沙箱独立日志
│   ├── batches.json            # 沙箱独立批次
│   └── drill_results.json      # 演练全流程结果（所有阶段）
└── {另一个sandbox_id}/
    └── ...
```

**关键保证**：
- 沙箱内的 `books/reservations/blacklist/logs/batches` 与正式 `data/` 目录物理隔离，绝不互相写入
- 沙箱批次仅存在于 `sandbox/{id}/batches.json`，正式 `data/batches.json` 完全不受影响
- 沙箱日志仅存在于 `sandbox/{id}/logs.json`，正式 `data/logs.json` 完全不受影响
- `drill_results.json` 是演练结论的唯一真相来源，包含所有阶段报告和最终结论

---

### 一键运行沙箱模块测试

```bash
python demo10.py
```

该脚本覆盖以下 24 个测试场景：
1. 创建演练沙箱 API 存在（201 + 完整响应结构）
2. 沙箱目录与数据隔离 - 正式 data/ 未被污染
3. 相同快照重复创建被 409 拦截
4. 沙箱列表 API（含 config_stale 字段）
5. 沙箱详情 API（含 drill_results + data_counts）
6. 沙箱预检 API - 报告正确 + 不落盘正式数据 + drill_results 已落盘
7. 沙箱 Dry-Run API - 不改变正式数据
8. 沙箱正式导入 API - 沙箱内落盘，正式 data/ 哈希不变，final_conclusion 正确
9. 沙箱回滚 API - 数据清零，状态正确
10. 沙箱回滚幂等性 - 重复回滚返回 already_rolled_back
11. 沙箱重启验证 API - 数据一致性 + 配置过期检查
12. 沙箱导出演练结果 API - 完整报告归档
13. 服务重启后沙箱记录完整保留（元数据 + drill_results）
14. 重启后仍可继续查询和操作沙箱
15. 沙箱销毁 API - 目录删除，列表清空
16. 正式配置切换后旧沙箱不可误用（预检/Dry-Run/导入全部返回 410）
17. 带冲突快照的沙箱预检/Dry-Run/导入正确处理并落盘 final_conclusion=has_conflicts
18. 多沙箱互不影响，全部不污染正式数据
19. 非法快照格式被 400 拦截
20. 不存在的沙箱返回 404
21. 完整生命周期 end-to-end（预检→dryrun→导入→验证→重启→回滚→导出→销毁）
22. 演练结果 drill_results.json 独立落盘，正式 batches.json 不含沙箱批次
23. 沙箱列表 limit 参数
24. 已导入沙箱不能重复导入（409）

---

## 本次新增要点（对应 v4.0）

**导入演练沙箱 - 隔离环境中的完整导入预演**

### 1. 完全隔离的沙箱环境

每个演练沙箱拥有完全独立的目录 `sandbox/{sandbox_id}/`，内部存放：
- `books.json` / `reservations.json` / `blacklist.json` / `logs.json` / `batches.json`：5 个独立数据文件
- `drill_results.json`：演练全流程结果归档

沙箱数据与正式 `data/` 目录物理隔离，线程安全，并发演练互不影响。

### 2. 五阶段完整演练链路

1. **预检（precheck）**：不落盘，产出完整差异报告
2. **Dry-Run**：模拟正式导入，执行全量冲突检测，仅落盘演练结论
3. **正式导入（import）**：在沙箱内完整落盘 5 个数据文件 + 生成沙箱独立批次
4. **回滚（rollback）**：沙箱内原子回滚，幂等，有冲突时拦截
5. **重启验证（restart-verify）**：数据一致性校验 + 配置过期检查

### 3. 快照去重

对快照整体做 `SHA256(sorted JSON)`，创建前比对已有沙箱的 `snapshot_hash`，相同内容重复创建返回 HTTP 409。

### 4. 配置过期检测

创建沙箱时记录正式环境 `books` 列表的 SHA256 签名作为 `config_signature`。每次预检/Dry-Run/导入前比对，签名不一致时返回 HTTP 410（Gone），响应标记 `config_stale=true`，防止基于过时配置的演练结论被误用。

### 5. 重启恢复机制

- 沙箱元数据持久化在 `sandbox/sandboxes.json`
- 服务启动时自动扫描状态为 `running_precheck` / `running_dryrun` / `running_import` 的异常中断沙箱，统一重置为 `ready`
- `recover_sandboxes_on_startup()` 在 `main()` 中被调用，控制台打印恢复明细

### 6. 并发控制

- 全局 `_global_lock` 保护沙箱元数据（sandboxes.json）读写
- 每个沙箱独立的 `_sandbox_locks[sandbox_id] = threading.RLock()` 保护沙箱内操作
- 避免 monkey-patch 全局 DATA_DIR 带来的线程安全风险

### 7. 覆盖的关键场景

1. **标准演练流程**：预检 → Dry-Run → 导入 → 验证 → 回滚 → 导出 → 销毁，全链路闭环
2. **服务重启恢复**：异常中断的沙箱自动重置为 ready，演练记录完整保留
3. **配置切换隔离**：正式 books 变更后旧沙箱返回 410，所有写操作被拦截
4. **零污染保证**：全程 SHA256 比对正式 data/ 下 5 个 JSON 文件，确认哈希零变化
5. **冲突快照演练**：带冲突的快照在沙箱内预检/Dry-Run/导入正确处理，final_conclusion 落盘
6. **多沙箱并发**：多个沙箱同时运行互不影响，销毁一个不影响其他
7. **演练结果归档**：`drill_results.json` 独立持久化所有阶段结论，可导出用于审计

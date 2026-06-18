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

## 数据文件位置

所有持久化数据以 UTF-8 JSON 格式存储在项目目录下的 `data/` 文件夹，服务重启后完整恢复。

| 文件 | 内容 |
|------|------|
| `data/books.json` | 馆藏书目配置（book_id、书名、副本数、借期、保留时长） |
| `data/reservations.json` | 预约/借阅记录（状态：waiting / available / borrowed / returned / expired / cancelled） |
| `data/blacklist.json` | 黑名单（读者 ID、原因、加入时间） |
| `data/logs.json` | 所有操作日志（包含成功与失败，支持按书目、读者过滤） |

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

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

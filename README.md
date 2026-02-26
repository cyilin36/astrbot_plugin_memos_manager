# astrbot_plugin_memos_manager

`astrbot_plugin_memos_manager` 是一个面向 AstrBot 的 Memos 管理插件（当前定向适配 `usememos/memos v0.24`）。

它提供可被 LLM 自动调用的工具（LLM Tools），支持：

- 检索笔记（日期筛选 + 关键词搜索）
- 新增笔记
- 编辑笔记（内容/可见性/置顶）
- 删除笔记

---

## 实现方式

### 1) 结构

- `main.py`：插件入口、Tool 注册、搜索流水线、审计日志返回
- `memos_client.py`：Memos API 封装（鉴权、分页、CRUD、错误处理）
- `tool_models.py`：可见性映射与参数归一化
- `_conf_schema.json`：WebUI 配置项定义
- `metadata.yaml`：插件元数据（插件名、版本）

### 2) LLM Tools

- `memos_search`
- `memos_create`
- `memos_update`
- `memos_delete`

### 3) 可见性映射

插件参数中的可见性映射为 Memos v0.24 枚举：

- `workspace` -> `PROTECTED`
- `private` -> `PRIVATE`
- `public` -> `PUBLIC`

### 4) 搜索逻辑（当前版本）

`memos_search` 在一次调用内执行完整流程：

1. 日期筛选（可选）
2. 关键词匹配（可选）
3. 截断返回结果（最多 `search_max_count` 条）

即：`日期筛选 -> 关键词检索 -> 返回上限`。

> 这样 AI 只需调用一次 tool 就能拿到最终结果，减少 token 消耗和链路时间。

---

## 配置方法（WebUI）

在 AstrBot WebUI 中配置以下字段：

- `memos_base_url`：Memos 站点地址（示例：`https://memos.example.com`）
- `memos_token`：Memos Token（Bearer）
- `default_visibility`：`workspace` / `private` / `public`（默认 `workspace`）
- `search_max_count`：搜索最终最大返回条数（默认 `50`）
- `enable_ai_audit_log`：是否回传审计摘要给 AI（默认 `true`）
- `ai_audit_log_max_chars`：审计日志摘要最大长度（默认 `2000`）
- `log_level`：日志级别（`DEBUG`/`INFO`/`ERROR`）

`memos_base_url` 可填站点根地址，插件会自动补齐 `/api/v1`。

---

## 使用操作

### 1) memos_search

用于检索笔记，支持日期和关键词组合。

参数：

- `query`（可选）：关键词
- `start_date`（可选）：起始日期/时间
- `end_date`（可选）：结束日期/时间
- `date_field`（可选）：`display_time` / `create_time` / `update_time`，默认 `display_time`
- `include_archived`（可选）：是否检索归档，默认 `false`

日期格式支持：

- `YYYY-MM-DD`
- ISO8601（如 `2026-02-01T10:00:00Z`）

说明：

- 最终返回条数不超过 `search_max_count`
- 当 `query` 为空时，相当于“仅按日期筛选/仅按时间排序返回”

### 2) memos_create

创建新笔记。

参数：

- `content`（必填）
- `visibility`（可选，默认走 `default_visibility`）

### 3) memos_update

更新已有笔记。

参数：

- `name`（必填，格式如 `memos/xxxx`）
- `content`（可选）
- `visibility`（可选）
- `pinned`（可选）

### 4) memos_delete

删除笔记。

参数：

- `name`（必填，格式如 `memos/xxxx`）

---

## 返回格式与日志审计

每次 tool 调用统一返回：

- `ok`：是否成功
- `trace_id`：追踪 ID
- `result`：业务结果
- `audit`：精简执行日志（可选）
- `errors`：错误列表

`audit` 可回传给 AI 进行“任务是否完成”的判断。

---

## 注意事项

1. 当前版本只保证 `memos v0.24` 兼容。
2. 能搜索到哪些笔记受 token 权限和 Memos 可见性策略影响。
3. 不要在日志和对话中泄露 token。
4. 传入超大日期范围会导致更多分页请求，建议按需限制范围。
5. `search_max_count` 是“最终返回上限”，不是“初始候选池上限”。
6. 若写入成功但内容异常，优先查看 tool 返回中的 `trace_id` 与 `audit`。

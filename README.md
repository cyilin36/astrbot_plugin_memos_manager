# astrbot_plugin_memos_manager

`astrbot_plugin_memos_manager` 是一个面向 AstrBot 的插件，用于管理 `usememos/memos v0.24`。

- 当前版本：`0.2`
- 仓库地址：`https://github.com/cyilin36/astrbot_plugin_memos_manager`

## 插件能力

本插件提供以下 LLM tools：

- `memos_search`：按日期与关键词检索笔记
- `memos_create`：创建笔记
- `memos_update`：更新笔记内容/可见性/置顶
- `memos_delete`：删除笔记

## 功能实现方式

### 架构说明

- `main.py`：插件入口、工具注册、鉴权、搜索与审计逻辑
- `memos_client.py`：Memos API 调用封装
- `tool_models.py`：可见性映射与参数规范化
- `_conf_schema.json`：WebUI 配置定义
- `metadata.yaml`：插件元数据

### 可见性映射

- `workspace` -> `PROTECTED`
- `private` -> `PRIVATE`
- `public` -> `PUBLIC`

### 搜索流程

`memos_search` 在一次调用内完成：

1. 日期过滤
2. 关键词过滤（content/snippet/tags）
3. 按 `search_max_count` 截断最终结果

## WebUI 配置（中文）

- `memos_base_url`：Memos 服务地址
- `memos_token`：Memos 访问令牌
- `default_visibility`：默认可见性（workspace/private/public）
- `search_max_count`：搜索最终最大返回条数
- `enable_ai_audit_log`：是否回传精简审计日志
- `ai_audit_log_max_chars`：审计日志最大长度
- `log_level`：插件日志级别
- `enable_uid_auth`：是否启用 UID 白名单鉴权
- `allowed_uids`：允许使用插件的 UID 列表（逗号分隔，仅纯数字）

`allowed_uids` 的填写方式：

- 在聊天中先执行 `/sid` 获取 UID
- 将多个 UID 用英文逗号分隔填写到 `allowed_uids`

## UID 鉴权规则

当 `enable_uid_auth = false`：

- 所有用户都可以使用本插件 tools

当 `enable_uid_auth = true`：

- 若 `allowed_uids` 为空：全部拒绝
- 若当前用户 UID 不在白名单：拒绝
- 若当前用户 UID 在白名单：放行

鉴权失败返回：

- `ok=false`
- `errors=["当前用户无权限使用该工具"]`

返回内容不会暴露 UID、token 等敏感信息。

## 工具参数说明

### memos_search

- `query`：关键词（可选）
- `start_date`：起始时间（可选，支持 `YYYY-MM-DD` 或 ISO8601）
- `end_date`：结束时间（可选，支持 `YYYY-MM-DD` 或 ISO8601）
- `date_field`：过滤字段（`display_time/create_time/update_time`）
- `include_archived`：是否包含归档

### memos_create

- `content`（必填）
- `visibility`（可选）

### memos_update

- `name`（必填，形如 `memos/xxxx`）
- `content`（可选）
- `visibility`（可选）
- `pinned`（可选）

### memos_delete

- `name`（必填，形如 `memos/xxxx`）

## 注意事项

1. 本插件当前仅定向适配 `memos v0.24`。
2. 请勿在日志或对话中泄露 token。
3. 可见性与可读范围受 Memos 侧权限控制。
4. 启用 UID 鉴权后，白名单为空会导致全拒绝。
5. 搜索结果上限由 `search_max_count` 控制。

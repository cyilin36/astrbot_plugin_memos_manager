# Changelog

## v2.2.1 - 2026-09-26

`memos_file` 的 `list` 支持全局附件搜索：省略 `name` 时自动降级。

### 新增

- `memos_file` 在 `action=list` 且**省略 `name`** 时，自动降级为全局附件搜索，调用 `GET /api/v1/attachments`。
- 全局搜索新增三个筛选参数：
  - `query`：按文件名关键词匹配；
  - `image_only`：只返回 `image/*` 附件；
  - `unbound_only`：只返回未绑定到任何笔记的附件（`memo_id == null`）。
- 全局模式自动翻页，返回上限复用 `search_max_count`，结果带 `matched_count` 与 `truncated` 标记。

### 变更

- `memos_file` 的 `required` 从 `["action", "name"]` 调整为 `["action"]`；`name` 对 `upload`/`remove` 仍为必填，对 `list` 可省略。
- 在 `name` 已指定时同时传入筛选参数，会在结果中提示这些参数仅在全局搜索时生效（服务端不支持按 memo 筛选）。

### 说明

- **全局搜索只返回当前令牌用户自己创建的附件**：服务端在 `ListAttachments` 中把范围硬编码为附件创建者，实例管理员也看不到他人上传的文件。
- 全局搜索**不发送 `orderBy`**：Memos v0.31 虽在 proto/OpenAPI 中声明了该参数，但服务端实现完全忽略它，结果固定按更新时间倒序。

## v2.2.0 - 2026-09-25

新增独立的文件（附件）管理工具 `memos_file`，与 `memos_update` 的文字编辑职责分离。

### 新增

- 新工具 `memos_file`，支持三个动作：
  - `upload`：把图片上传并绑定到指定笔记；
  - `list`：列出笔记当前的附件；
  - `remove`：从笔记删除附件（默认关闭）。
- 上传图片来源：`url` / `path` 参数，或自动读取当前聊天消息中的图片（含被引用消息里的图片），多张图会全部上传到同一笔记。
- 新增配置项：
  - `enable_memos_file_delete_tool`：启用附件删除动作（默认 `false`）；
  - `file_upload_max_mb`：单张图片上传大小上限（默认 16 MB，服务端默认为 32 MB）；
  - `file_download_timeout_seconds`：下载远程图片的超时时间（默认 30 秒）。

### 变更

- `memos_search` / `memos_update` 等返回的 memo 现在包含 `attachments` 字段（`name` / `filename` / `type` / `size` / `memo` / `create_time`），便于定位附件资源名。
- 删除附件遇到 `412` 时返回明确提示，引导先用 `memos_update` 移除正文引用。

### 说明

- 文件工具**不修改笔记正文**：上传后的图片以附件区形式展示；如需正文内嵌，请用 `memos_update` 编辑正文。
- Memos v0.31 没有“仅解绑保留文件”的接口，从笔记移除附件即**永久删除文件**，故删除动作默认关闭。
- 服务端将附件删除限制为创建者本人，管理员也无法删除他人附件。

## v2.1.0 - 2026-09-24

适配 `usememos/memos v0.31`。本次为**破坏性更新**：不再兼容 v0.24，升级前请先升级 Memos 并重新生成令牌。

### 破坏性变更

- **列表接口迁移**：v0.31 已移除 `GET /api/v1/users/{user_id}/memos`，改用 `GET /api/v1/memos`；服务端按令牌用户身份自动收窄可读集合（PRIVATE 仅创建者、PROTECTED 所有登录用户、SPACE 仅该 Space 的 ACTIVE 成员）。插件不再需要从 JWT 中解析用户 ID。
- **查询参数迁移**：`sort` / `direction` / `oldFilter` 已被移除，改为 `orderBy` 与 CEL `filter` 表达式。日期与可见性过滤已下推到服务端。
- **令牌格式变更**：v0.31 的 access token 校验要求 `type == "access"`，旧式 JWT 会被拒绝。长期接入请使用 PAT（以 `memos_pat_` 开头）。

### 变更

- `display_time` 字段在 v0.31 已被删除，`date_field` 统一映射为 `create_time`（默认，`display_time` 作为兼容别名）或 `update_time`。
- 日期区间从闭区间改为**半开区间** `[start, end)`，避免边界记录重复计入。
- `memos_create` / `memos_update` 请求体对齐 v0.31：创建时请求体直接是 Memo，更新使用 `updateMask` 逗号分隔的 query 参数。
- 列表分页固定 `pageSize`，避免 `pageToken` 中编码的 limit 与请求参数不一致。
- `memos_search` 返回值新增 `property` / `space` / `parent` 字段，移除已废弃的 `display_time`。
- WebUI 配置文案更新：`default_visibility` 说明其同时决定检索可见性范围；`memos_token` 提示改用 PAT。

## v1.2.1 - 2026-09-07

- `allowed_uids` 改用 AstrBot 内置的 `list` 类型配置项：在 WebUI 中逐条添加 UID（支持批量导入，每行一个），不再需要逗号分隔填写。
- 自动迁移旧格式：插件加载时若发现存量配置仍是旧版逗号分隔字符串，会一次性拆成真正的 UID 列表并写回，避免 WebUI 列表编辑器把字符串逐字拆成条目。

## v1.2.0 - 2026-07-19

- 修复查询未按 `default_visibility` 过滤笔记的问题，并对已归档列表应用相同规则。

## v1.1 - 2026-07-18

- 修复 `memos_search` 和已归档查询无法读取当前用户 `PRIVATE` 笔记的问题。
- 列表查询改用 Memos 用户作用域接口，并从访问令牌的 JWT `sub` 字段识别用户 ID。
- 对无法识别用户 ID 的访问令牌返回明确的配置错误。

## v1.0 - 2026-03-04

- 优化 Memos API 错误提示可读性：按常见状态码返回更明确的中文错误信息。

## v0.9 - 2026-02-27

- 白名单机制升级：`allowed_uids` 支持任意 UID 字符串（不再限制纯数字）。

## v0.8 - 2026-02-27

- 移除未生效的配置项 `log_level`，避免 WebUI 出现无效设置。

## v0.7 - 2026-02-27

- `memos_search` 固定仅查询未归档笔记。
- 已归档笔记查询统一由 `memos_archive`（`action=list_archived`）提供。
- `memos_search` 与 `memos_archive` 查询返回条数统一受 `search_max_count` 控制。
- WebUI 配置文案将 `search_max_count` 更新为“搜索最多返回条数”。

## v0.6 - 2026-02-27

- 新增 `memos_archive` 的 `action=list_archived` 模式，可读取已归档笔记列表。
- 支持先查询已归档笔记，再通过 `action=set` + `archived=false` 执行取消归档。
- 同步更新用户文档与版本号至 `0.6`。

## v0.5 - 2026-02-27

- 新增 `memos_archive` 工具，支持将笔记归档或取消归档。
- `memos_archive` 参数 `archived` 默认值为 `true`，可通过 `false` 恢复为未归档。
- `memos_archive` 新增 `action=list_archived`，可直接查询已归档笔记列表以便后续反归档。

## v0.4 - 2026-02-27

- 新增配置项 `enable_memos_delete_tool`，默认关闭删除工具。
- 仅在 WebUI 打开 `enable_memos_delete_tool` 后注册 `memos_delete`。

## v0.3 - 2026-02-27

- 修复 `memos_update` 的 PATCH 请求体结构：移除外层 `memo` 包装。
- 将 `updateMask` 调整为 query 参数，兼容当前 Memos v0.24 接口行为。

## v0.2 - 2026-02-27

- 新增 UID 白名单鉴权能力，并作用于全部 tools。
- 新增鉴权配置项：`enable_uid_auth`、`allowed_uids`。
- WebUI 配置文案全部中文化。
- 更新插件元数据：中文描述与仓库地址。
- 完善核心代码注释，覆盖配置读取、鉴权流程、搜索流程与工具调用入口。

## v0.1 - 2026-02-26

- 首次发布 `memos_search`、`memos_create`、`memos_update`、`memos_delete` 四个工具。
- 完成 `usememos/memos v0.24` 的基础接入。
- 支持日期与关键词组合搜索，并统一返回审计日志结构。

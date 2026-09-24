# Changelog

## v2.0.0 - 2026-09-24

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
- 新增 `tests/test_v031.py`，覆盖可见性 CEL 映射、日期区间与请求形状。

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

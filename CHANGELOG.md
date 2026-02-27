# Changelog

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

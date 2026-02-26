# Changelog

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

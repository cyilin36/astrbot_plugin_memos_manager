# Changelog

## 2026-02-26

### fix：修复 Memos 创建请求体与筛选参数映射 (`50b8404`)

- 修复 `memos_create` 请求体结构，按 v0.24 要求直接发送 memo 本体，避免创建出空内容与错误可见性。
- 修复查询参数名，从 `old_filter` 调整为 `oldFilter`，确保日期筛选条件能正确下发。

### Add GNU AGPL v3 license (`4db306a`)

- 新增 GNU AGPL v3 许可证文件。

### feat：新增时间筛选功能 (`9b46d84`)

- 为 `memos_search` 增加日期筛选能力，并支持与关键词检索在同一轮调用内组合执行。

### first commit (`f03c338`)

- 初始化 `astrbot_plugin_memos_manager` 插件项目结构与基础能力。

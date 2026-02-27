# astrbot_plugin_memos_manager

`astrbot_plugin_memos_manager` 是一个面向 AstrBot 的插件，用于管理 `usememos/memos v0.24`。

- 当前版本：`0.6`

## 插件能力

- `memos_search`：按日期与关键词检索笔记
- `memos_create`：创建笔记
- `memos_update`：更新笔记内容/可见性/置顶
- `memos_archive`：归档管理（设置归档状态、查询已归档）
- `memos_delete`：删除笔记（默认关闭，需在 WebUI 启用）

## WebUI 配置

- `memos_base_url`：Memos 服务地址
- `memos_token`：Memos 访问令牌
- `enable_uid_auth`：是否启用 UID 白名单鉴权
- `allowed_uids`：允许使用插件的 UID 列表（逗号分隔，仅纯数字）
- `enable_memos_delete_tool`：是否启用 `memos_delete`（默认关闭）

`allowed_uids` 的填写方式：

- 在聊天中先执行 `/sid` 获取 UID
- 将多个 UID 用英文逗号分隔填写到 `allowed_uids`

## 使用示例

- “帮我创建一条 memo：今天完成了发布流程复盘。”
- “帮我搜索这周包含 ‘发布’ 的 memo。”
- “把这条 memo 置顶：memos/xxxx。”
- “先列出已归档 memo，再把这条恢复成未归档：memos/xxxx。”

## 注意事项

1. 本插件当前仅定向适配 `memos v0.24`。
2. 请勿在日志或对话中泄露 token。
3. 启用 UID 鉴权后，白名单为空会导致全部拒绝访问。

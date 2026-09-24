# astrbot_plugin_memos_manager

`astrbot_plugin_memos_manager` 是一个面向 AstrBot 的插件，用于管理 `usememos/memos v0.31+`。

## 插件能力

- `memos_search`：按日期与关键词检索当前用户的未归档笔记（包括 PRIVATE）
- `memos_create`：创建笔记
- `memos_update`：更新笔记内容/可见性/置顶
- `memos_archive`：查询已归档 / 设置归档状态
- `memos_delete`：删除笔记（默认关闭，需在 WebUI 启用）

## WebUI 配置

- `memos_base_url`：Memos 服务地址
- `memos_token`：Memos 访问令牌（**v0.31 请使用 PAT**）
- `default_visibility`：默认笔记可见性，同时决定检索时的可见性收窄范围
- `enable_uid_auth`：是否启用 UID 白名单鉴权
- `allowed_uids`：允许使用插件的 UID 列表
- `enable_memos_delete_tool`：是否启用 `memos_delete`（默认关闭）

### 如何获取令牌（v0.31）

Memos v0.31 的认证方式已变更：

1. 旧式 JWT（形如 `eyJ...`，payload 只有 `name/iss/sub/aud/iat`）**已不再被服务端接受**。
2. 请登录 Memos → **设置 → 访问令牌（Access Tokens）** → 新建，得到以 `memos_pat_` 开头的**个人访问令牌（PAT）**。
3. 把该 PAT 填入 `memos_token`。

> 登录会话签发的短期 access token 同样可用，但 15 分钟即过期，不适合长期配置，因此推荐 PAT。

`allowed_uids` 的填写方式：

- 在聊天中先执行 `/sid` 获取 UID
- 白名单按精确值匹配，区分大小写

## 使用示例

- “帮我创建一条 memo：今天完成了发布流程复盘。”
- “帮我搜索这周包含 ‘发布’ 的 memo。”
- “把这条 memo 置顶：memos/xxxx。”
- “先列出已归档 memo，再把这条恢复成未归档：memos/xxxx。”

- `memos_search` 仅查询未归档。
- 已归档请用 `memos_archive` 查询。
- 两者返回条数都受 `search_max_count` 控制。
- 查询使用当前 token 对应的用户作用域，可返回该用户的 PRIVATE、PROTECTED 和 PUBLIC 笔记。

## 可见性与日期语义（v0.31）

可见性档位同时用于「创建时的默认值」和「检索时的可读范围收窄」：

| `default_visibility` | 创建时的可见性 | 检索可读范围 |
| --- | --- | --- |
| `private` | PRIVATE | 本人全部可读（PRIVATE + PROTECTED + PUBLIC + 所属 Space） |
| `workspace`（默认） | PROTECTED | PROTECTED + PUBLIC |
| `public` | PUBLIC | 仅 PUBLIC |

日期看板说明：

- Memos v0.31 已移除 `display_time` 字段，插件将 `date_field` 映射为 `create_time`（默认，兼容别名 `display_time`）或 `update_time`。
- 日期区间为**半开区间** `[start, end)`：`start_date=2026-01-01` 表示本地 1 月 1 日 00:00 起；`end_date=2026-01-31` 表示本地 2 月 1 日 00:00 止（即包含 1 月 31 日全天）。

## 注意事项

1. 本插件仅定向适配 `usememos/memos v0.31+`；v0.24 及更早版本的路由与查询参数已被上游移除，无法同时兼容。
2. 请勿在日志或对话中泄露 token。
3. 启用 UID 鉴权后，白名单为空会导致全部拒绝访问。

# astrbot_plugin_memos_manager

`astrbot_plugin_memos_manager` 是一个面向 AstrBot 的插件，用于管理 `usememos/memos v0.31+`。

## 插件能力

- `memos_search`：按日期与关键词检索当前用户的未归档笔记（包括 PRIVATE）
- `memos_create`：创建笔记
- `memos_update`：更新笔记内容/可见性/置顶
- `memos_archive`：查询已归档 / 设置归档状态
- `memos_delete`：删除笔记（默认关闭，需在 WebUI 启用）
- `memos_file`：管理笔记的图片附件（上传/列出/删除）

## 文件（附件）管理

`memos_file` 专门负责图片附件，与 `memos_update` 的纯文字编辑**职责分离**：本工具只操作附件列表，**不会修改笔记正文**。编辑文字请使用 `memos_update`。

| `action` | 说明 |
| --- | --- |
| `upload` | 把图片上传并绑定到指定笔记 |
| `list` | 列出附件：指定 `name` 查该笔记；**省略 `name` 则在全部附件中搜索** |
| `remove` | 从笔记删除附件（默认关闭，需在 WebUI 启用） |

### list：指定笔记 vs 全局搜索

`list` 会根据是否提供 `name` 自动切换模式：

| 模式 | 触发条件 | 底层接口 |
| --- | --- | --- |
| 指定笔记 | 提供 `name`（如 `memos/xxxx`） | `GET /api/v1/memos/{memo}/attachments` |
| 全局搜索 | **省略 `name`** | `GET /api/v1/attachments` |

全局搜索支持的筛选参数（仅在省略 `name` 时生效）：

| 参数 | 说明 |
| --- | --- |
| `query` | 按文件名关键词匹配 |
| `image_only` | 只返回图片类附件（`image/*`） |
| `unbound_only` | 只返回未绑定到任何笔记的附件 |

返回条数受 `search_max_count` 控制，超出时会翻页并在结果中标记 `truncated=true`。

> **全局搜索的两个限制（服务端行为，非插件限制）**
> 1. **只返回当前 token 用户自己创建的附件**——即使实例管理员也看不到他人上传的文件。
> 2. 结果固定按更新时间倒序。接口虽接受 `orderBy` 参数，但 Memos v0.31 的服务端实现**完全忽略**它，因此插件不会发送该参数。

示例：

- “列出 memos/xxxx 的附件。”
- “我上传过哪些图片？”（全局，`image_only=true`）
- “找一下文件名里有 logo 的图片。”
- “有哪些附件还没挂到任何笔记？”（`unbound_only=true`）

上传图片来源，按优先级：

1. `url` 参数：http(s) 图片地址；
2. `path` 参数：服务器本地图片路径；
3. 两者都不填时，自动取**当前聊天消息中的图片**（含被引用消息里的图片），多张会全部上传到同一笔记。

示例：

- “把这张图传到 memos/xxxx。”（消息中带图）
- “把 https://example.com/a.png 传到 memos/xxxx。”
- “列出 memos/xxxx 的附件。”
- “把 memos/xxxx 上的 a.png 删掉。”

### 能力边界与注意事项

1. **删除即永久删除**：Memos v0.31 没有“仅从笔记解绑、保留文件”的接口，`remove` 会真正删除文件且不可恢复，因此默认关闭。
2. **删除被正文引用的图片会被服务端拒绝**。若正文里有 `![...](/file/attachments/xxxx)` 引用，请先用 `memos_update` 移除该引用，再删除附件。
3. **只能删除自己上传的附件**：服务端把 `DELETE` 范围限制在附件创建者本人；即使实例管理员也删不了别人的附件。
4. **只上传、不改正文**：上传后的图片以**附件区**形式展示在正文下方。若想在正文中内嵌图片，请用 `memos_update` 编辑正文并写入 `![名称](/file/attachments/{附件ID})`。
5. `remove` 需要提供 `attachment`（`attachments/xxxx`）或 `filename`；按文件名匹配到多个附件时会拒绝执行并提示改用资源名。
6. 删除前会先校验附件确实绑定在该笔记上，避免误删其它笔记的文件。
7. `upload` 与 `remove` **必须**指定 `name`，不会降级为全局操作。

## WebUI 配置

- `memos_base_url`：Memos 服务地址
- `memos_token`：Memos 访问令牌（**v0.31 请使用 PAT**）
- `default_visibility`：默认笔记可见性，同时决定检索时的可见性收窄范围
- `enable_uid_auth`：是否启用 UID 白名单鉴权
- `allowed_uids`：允许使用插件的 UID 列表
- `enable_memos_delete_tool`：是否启用 `memos_delete`（默认关闭）
- `enable_memos_file_delete_tool`：是否启用 `memos_file` 的删除附件动作（默认关闭）
- `file_upload_max_mb`：单张图片上传大小上限（MB，默认 16）
- `file_download_timeout_seconds`：下载远程图片的超时时间（秒，默认 30）

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

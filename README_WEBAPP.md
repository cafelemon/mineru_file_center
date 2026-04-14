# MinerU 局域网验证工具

这是一个包在当前 MinerU 环境外层的内部知识库文件管理系统，用于在局域网内上传 PDF 或 ZIP、选择所属知识库、调用 MinerU、保存规范命名后的原始 PDF，以及提取最终 Markdown。

当前版本支持在 Markdown 生成成功后，自动同步到 FastGPT 对应知识库创建文本集合并完成切片。

## 启动

1. 可选：编辑 `webapp/config.toml`
2. 启动服务：

```bash
env/bin/python -m webapp
```

默认监听 `0.0.0.0:7860`。

## 登录

- 默认账号：`admin`
- 默认密码：`change-me`

上线到局域网前请修改 `webapp/config.toml`，或改为环境变量：

```bash
export WEB_USERNAME='your-user'
export WEB_PASSWORD='your-password'
export WEB_SESSION_SECRET='a-random-secret'
```

## 目录

- `data/pdf_store/`：规范命名后的原始 PDF，文件名是 `<doc_id>.pdf`
- `data/output/`：最终 Markdown，文件名是 `<doc_id>.md`
- `data/tasks/<doc_id>/raw_output/`：MinerU 原始输出
- `data/tasks/<doc_id>/task.log`：单任务日志
- `data/app.db`：SQLite 任务记录
- `data/logs/webapp.log`：Web 服务日志
- `data/bridge_exports/`：可选，导出给 Bridge 的 manifest

## 页面

- `/`：上传页
- `/tasks`：任务列表
- `/files`：知识库文件管理页
- `/files/{doc_id}`：文件详情页，可生成并打开原始 PDF 受控访问链接
- `/files/{doc_id}`：也会展示 FastGPT 同步状态，并在失败时提供重试入口

上传时必须选择所属知识库。上传入口支持两种方式：

- 直接上传一个或多个 PDF
- 上传一个或多个 ZIP；ZIP 内多层目录会作为该知识库下的子目录保留，非 PDF 自动跳过

当前继续按单个 PDF 限制大小，默认上限 `200 MB`。ZIP 不额外施加整包业务限额，但其中每个 PDF 仍会单独校验。

系统首次启动会默认初始化：

- 通用知识库
- 高层知识库
- 质量体系部知识库
- 医疗注册部知识库

可在 `/files` 页面左侧知识库目录中新建知识库；选中空知识库后可输入当前登录密码删除。已有文件的知识库不能直接删除，避免历史文件失去归属。

选择某个知识库后，左侧会继续显示该知识库下的子目录树。点击目录时，文件表会展示该目录及其下级子目录中的文件。

## MinerU 调用

默认调用：

```bash
env/bin/mineru -p <stored_pdf> -o <task_raw_output_dir> -b pipeline -m auto -l ch
```

如未来 Linux 服务器上的 MinerU 命令位置不同，只需要改 `webapp/config.toml` 的 `[mineru].command`，或设置 `MINERU_COMMAND` 环境变量。

## FastGPT 自动同步

开启后，任务成功生成 Markdown 后会自动：

1. 读取文件中心知识库名称
2. 调用 FastGPT OpenAPI 查找同名知识库
3. 以 Markdown 文本创建集合并自动切片
4. 把成功返回的 `collectionId` 写回本地任务记录
5. 若已开启 Bridge PDF 导出，则尝试把 `collectionId` 回填到 Bridge PDF registry

配置示例：

```toml
[fastgpt_sync]
enabled = true
base_url = "http://127.0.0.1:3000"
api_key = "replace-with-fastgpt-global-api-key"
training_type = "chunk"
chunk_setting_mode = "auto"
chunk_size = 0
```

说明：

- `base_url` 填 FastGPT 根地址，不要带 `/api/v1`
- `api_key` 需要能访问知识库 OpenAPI 的全局 key
- 文件中心知识库名称需与 FastGPT 知识库名称完全一致
- 同步失败不会回滚 MinerU 成功状态，页面会单独显示 FastGPT 同步失败

历史成功任务可执行批量补同步：

```bash
cd /Users/jiafei/workspace/mineru_file_center
env/bin/python sync_fastgpt.py --failed-only
```

## 原始 PDF 受控访问链接

文件管理中心可基于 SQLite 中的 `doc_id` 生成短时效签名链接，只允许访问单个原始 PDF，不开放目录浏览，也不会在 URL 中暴露真实绝对路径。

```toml
[file_link]
enabled = true
secret = "replace-with-a-random-secret"
expire_seconds = 600
base_url = "http://127.0.0.1:7860"
```

也可通过环境变量覆盖：

- `FILE_LINK_ENABLED`
- `FILE_LINK_SECRET`
- `FILE_LINK_EXPIRE_SECONDS`
- `FILE_LINK_BASE_URL`

后续迁移到 Linux 内网服务器时，如果服务端口、域名或反向代理地址变化，通常只需要修改 `FILE_LINK_BASE_URL`；如果原始 PDF 存储根目录变化，修改 `[storage].data_root` 或 `WEB_DATA_ROOT` 等存储配置即可。

后续 Bridge 可调用轻量 API 获取链接：

```text
GET /api/files/pdf-link?doc_id=<doc_id>
```

返回字段包括 `doc_id`、`pdf_url`、`expires_in`、`expires_at`。
当前该接口按内部服务接口设计，便于 Bridge 直接调用；真正暴露到外部网络前，建议放在内网网关后或补充服务间 token。

## Bridge 最小联动

默认关闭。当前更推荐把它当作“兼容旧 Bridge 本地 PDF 导入流程”的可选项，而不是主链路。

如果你的 Bridge 和文件中心不在同一台服务器，通常可以保持 `enabled = false`，只配置 `api_base_url`，这样文件中心会在 FastGPT 同步成功后直接把轻映射回填给 Bridge，不再复制 PDF。

开启后，任务成功时会额外执行两件事：

1. 把原始 PDF 复制到 Bridge 目录：

```text
<bridge_export.pdf_root>/<app_code>/<knowledge_base_code>/<doc_id>.pdf
```

当前内置映射：

- `general -> general_common`
- `executive -> executive_all`
- `quality_system -> quality_system`
- `medical_reg -> regulatory_affairs`

Web 端新建的知识库默认使用自身 `knowledge_base_code` 作为 `app_code`。

2. 生成 Bridge 可导入的 manifest：

- 单文件 manifest：`data/bridge_exports/<doc_id>.json`
- 聚合 manifest：`data/bridge_exports/latest_manifest.json`

manifest 字段对齐 Bridge 的 `PdfManifestItem`，包括：

- `doc_id`
- `source_name`
- `origin_pdf_name`
- `pdf_abs_path`
- `source_pdf_path`
- `markdown_path`
- `kb_category`
- `perm_level`
- `app_code`
- `status`
- `sha256`

### 配置

```toml
[bridge_export]
enabled = false
pdf_root = "/Users/jiafei/workspace/feishu_fastgpt_bridge/data/pdf_store"
manifest_dir = "data/bridge_exports"
api_base_url = "http://127.0.0.1:8088"
```

也可通过环境变量覆盖：

- `BRIDGE_EXPORT_ENABLED`
- `BRIDGE_PDF_ROOT`
- `BRIDGE_MANIFEST_DIR`
- `BRIDGE_API_BASE_URL`

### Bridge 导入

Bridge 侧保持现有流程不变，直接导入聚合 manifest：

```bash
cd /Users/jiafei/workspace/feishu_fastgpt_bridge
python -m scripts.import_pdf_manifest \
  --manifest /Users/jiafei/workspace/mineru_file_center/data/bridge_exports/latest_manifest.json
```

### 手动回填

如果要把历史成功任务重新导出到 Bridge，可执行：

```bash
cd /Users/jiafei/workspace/mineru_file_center
env/bin/python export_to_bridge_manifest.py
```

如果已开启 FastGPT 自动同步，并且 `BRIDGE_API_BASE_URL` 已配置，则文件中心会在同步成功后自动调用 Bridge 的 `/admin/kb/register-pdf` 回填 `collectionId`、`doc_id` 和原文件名。这个回填现在不再依赖 Bridge 本地 PDF 文件存在。

# MinerU File Center

`mineru_file_center` 是一个部署在内网环境中的文件管理系统，用于承接 PDF 上传、调用 MinerU 解析、统一保存原始 PDF 和最终 Markdown，并把结果接到 FastGPT 与 Bridge 的后续链路。

## 当前能力

- Web 端上传 PDF，并选择所属知识库
- 异步执行 MinerU 解析任务，输出标准化 Markdown
- 动态管理知识库，可在 Web 端新建和删除空知识库
- 为原始 PDF 生成受控访问链接
- 可选导出 Bridge manifest 和 PDF 副本
- Markdown 生成成功后自动同步到 FastGPT 同名知识库，创建文本集合并切片
- FastGPT 同步成功后，自动把 `collectionId` 回填到 Bridge 的 PDF registry

## 目录说明

- `webapp/`：FastAPI 应用、模板、静态资源和服务逻辑
- `tests/`：文件中心新增能力的基础单测
- `deploy/`：部署所需依赖清单
- `trial-review-showcase/`：独立的前端展示项目
- `export_to_bridge_manifest.py`：把历史成功任务重新导出到 Bridge manifest
- `sync_fastgpt.py`：把历史成功任务重新同步到 FastGPT

## 本地启动

推荐先复制配置模板：

```bash
cp webapp/config.example.toml webapp/config.toml
```

然后启动：

```bash
env/bin/python -m webapp
```

默认端口是 `7860`。

## 关键配置

### MinerU

- `MINERU_COMMAND`
- `MINERU_BACKEND`
- `MINERU_METHOD`
- `MINERU_LANG`

### 文件中心访问

- `WEB_USERNAME`
- `WEB_PASSWORD`
- `WEB_SESSION_SECRET`
- `FILE_LINK_SECRET`
- `FILE_LINK_BASE_URL`

### FastGPT 自动同步

- `FASTGPT_SYNC_ENABLED`
- `FASTGPT_BASE_URL`
- `FASTGPT_API_KEY`
- `FASTGPT_TRAINING_TYPE`
- `FASTGPT_CHUNK_SETTING_MODE`
- `FASTGPT_CHUNK_SIZE`

注意：文件中心里的知识库名称需要和 FastGPT 知识库名称完全一致，自动同步会按名称精确匹配。

### Bridge 回填

- `BRIDGE_EXPORT_ENABLED`
- `BRIDGE_PDF_ROOT`
- `BRIDGE_MANIFEST_DIR`
- `BRIDGE_API_BASE_URL`

## 历史补处理

重新导出 Bridge manifest：

```bash
env/bin/python export_to_bridge_manifest.py
```

重试 FastGPT 同步：

```bash
env/bin/python sync_fastgpt.py --failed-only
```

更多细节见 [README_WEBAPP.md](README_WEBAPP.md)。

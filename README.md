# MinerU File Center

`mineru_file_center` 是一个部署在内网环境中的文件管理系统，用于承接 PDF、Word、Excel 上传，统一保存原始文件和最终 Markdown，并把结果接到 FastGPT 与 Bridge 的后续链路。

## 当前能力

- Web 端上传 PDF、`.docx`、`.xlsx`、`.xlsm`，并先选择所属知识库，再选择该知识库下的目标子目录
- 异步执行解析任务，PDF 走 MinerU，Word/Excel 走本地 Markdown 转换
- 动态管理知识库，可在 Web 端新建和删除空知识库
- `/files` 支持按 `20 / 50 / 100 / 200 / 500` 调整每页展示数量，分页参数会保留在 URL 中；页面顶部已拆分为筛选导出区和批量操作区，列表区保持固定高度并在表格内滚动
- 为原始文件生成受控访问链接
- 可选导出 Bridge PDF manifest 和 PDF 副本
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

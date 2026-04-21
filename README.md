# AutoPapers

AutoPapers 现在是一个前后端式的本地研究工作台：

- 支持从 arXiv、OpenReview、Google Scholar 检索论文。
- 只把可下载且可解析 PDF 的论文写入本地库，保持总结基于正文而不是只基于摘要。
- 会缓存并展示论文的收录信息、来源链接和 Google Scholar 引用数。
- 支持在界面内查看论文摘要、打开 PDF / Markdown、删除单篇论文，并手动刷新元数据。

## Requirements

- Python 3.10+
- MiniMax API key with access to `MiniMax-M2.7`
- Optional: `pypdf` for better PDF text extraction

## Setup

1. Copy `.env.example` to `.env`.
2. Fill in `MINIMAX_API_KEY`.
3. Confirm your local HTTP proxy is available at `http://127.0.0.1:7890` if you want AutoPapers to route outbound traffic through it.
4. Install the package if needed:

```bash
python -m pip install -e .
python -m pip install -e ".[pdf]"
```

## Web App

启动本地 Web 应用：

```bash
python -m autopapers serve
```

仓库根目录下可直接运行，不需要额外设置 `PYTHONPATH`。

如果你在 Windows 上直接用 `myrag` 环境启动，也可以双击或执行：

```bat
start_autopapers_myrag.bat
```

可选参数：

```bash
python -m autopapers serve --host 127.0.0.1 --port 8765
```

打开浏览器访问控制台输出的地址即可。

## CLI

仍然保留原来的 CLI 入口：

```bash
python -m autopapers run "帮我找最近关于多模态 Agent 的 arXiv 论文，并总结重点"
python -m autopapers rebuild-summaries
```

## UI Overview

- `Research Directory`: 展示一级方向、二级方向和论文条目，可过滤、选择、删除，并显示 venue / cited 次数。
- `Task Console`: 用对话框向 LLM 派发任务，任务完成后自动刷新目录。
- `Paper Detail Dock`: 显示选中论文的摘要、关键词、收录信息、引用信息、来源链接和 Markdown 预览。

## Directory Layout

```text
library/
  index.json
  README.md
  {major-topic}/
    README.md
    {minor-topic}/
      README.md
      {paper}.pdf
      {paper}.md
      {paper}.metadata.json
reports/
  YYYYMMDD-HHMMSS_{request}.md
```

## Architecture

- `src/autopapers/workflows.py`: 端到端论文工作流与多源候选融合
- `src/autopapers/library.py`: 本地论文库存储、目录树、删除与汇总维护
- `src/autopapers/web/server.py`: Web server 与 API
- `src/autopapers/web/jobs.py`: 后台任务队列
- `src/autopapers/web/static/`: 前端页面、样式和交互脚本
- `src/autopapers/llm/`: MiniMax 集成与请求规划
- `src/autopapers/arxiv.py`: arXiv 检索与 PDF 下载
- `src/autopapers/openreview.py`: OpenReview 检索与元数据解析
- `src/autopapers/scholar.py`: Google Scholar 检索与引用 / venue 抓取
- `src/autopapers/http_client.py`: 统一的 HTTP 打开器与代理配置

## Notes

- 如果 MiniMax key 无效，Web 界面仍可打开和浏览目录，但任务执行会失败并在界面里显示错误。
- 当前 `.env` 中需要你提供一个可用的 MiniMax key；之前提供的那个 key 在真实调用里返回了 `invalid api key`。
- 当前仓库默认把 `arXiv` 和 `MiniMax` 请求都走 `AUTOPAPERS_HTTP_PROXY=http://127.0.0.1:7890`。如果你本机没有这个代理，删掉或改掉该配置即可。

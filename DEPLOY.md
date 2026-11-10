# 赛事页发布

GitHub Actions 从 `main` 读取 `sports/data/`，运行测试，生成独立 HTML 和赛事索引，再把整个 `docs/` 部署到现有 GitHub Pages。赛事页使用原来的 URL，仓库根首页仍由 `docs/index.html` 提供。

Pages 的发布源应设为 **GitHub Actions**。工作流 `Validate tournaments and publish Pages` 先运行 `build`，成功后由 `deploy` 发布。PR 只验证，只有 `main` 能部署。

本地验证使用 Python 3.11+ 和 Node 22。

```sh
python -m pip install PyYAML==6.0.3
python -m unittest discover -s sports/tests -v
python sports/build.py
python sports/build.py --check
npm install --no-save --package-lock=false playwright@1.56.1
npx playwright install chromium
node sports/core/browser_check.cjs
```

自动发布以 Actions 的 `deploy` 和公开 URL 为准。仓库内的 HTML 可以作为离线快照下载。通过 JSON 或 YAML 更新数据时，Actions 会重新生成页面，详见 [赛事数据维护](sports/README.md)。

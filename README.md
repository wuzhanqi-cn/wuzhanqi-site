# wuzhanqi.cn 网站源码

义乌个人网站，包含每日新闻自动更新功能。

## 功能
- 每日自动抓取义乌新闻（义乌市政府门户 + 义乌新闻网）
- 自动部署到 Cloudflare Pages
- 新闻页面：https://wuzhanqi.cn/news

## 自动更新
通过 GitHub Actions 每天北京时间 23:30 自动抓取新闻并提交，Cloudflare Pages 监听仓库变更自动部署。

## 文件说明
- `fetch_news.py` - 新闻抓取脚本
- `news.json` - 新闻数据
- `*.html` - 网站页面
- `.github/workflows/daily-news.yml` - 定时任务配置

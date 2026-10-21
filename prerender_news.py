# -*- coding: utf-8 -*-
"""
把 news.json 的最新若干条渲染成静态 HTML，注入 news.html。

解决的问题：news.html 原本完全依赖 JS fetch('/news.json') 渲染，
搜索引擎爬虫（不执行 JS）只能看到「加载中」。注入后爬虫可直接读到内容，
JS 加载后仍会照常重渲染，交互与筛选功能不受影响。

幂等性：每次运行先清掉上次注入的内容再重新注入，因此可每天重复执行。
"""
import io, os, re, json, sys, html

REPO = os.path.dirname(os.path.abspath(__file__))
CONTAINER_ID = 'newsList'
LIMIT = 15

MONTH_NAMES = ['一月', '二月', '三月', '四月', '五月', '六月',
               '七月', '八月', '九月', '十月', '十一月', '十二月']

MARK_START = '<!--PRERENDERED:START-->'
MARK_END = '<!--PRERENDERED:END-->'


def load_news():
    p = os.path.join(REPO, 'news.json')
    if not os.path.exists(p):
        return []
    with io.open(p, encoding='utf-8') as f:
        d = json.load(f)
    if isinstance(d, list):
        return d
    if isinstance(d, dict) and 'news' in d:
        return d['news']
    return []


def format_date(d):
    """与 news.html 内的 formatDate 保持一致"""
    if not d:
        return ''
    parts = str(d).split('-')
    if len(parts) == 3:
        y, m, day = parts
        try:
            return '%s年%s%s日' % (y, MONTH_NAMES[int(m) - 1], str(int(day)))
        except (ValueError, IndexError):
            return d
    return d


def esc(s):
    return html.escape(str(s), quote=True)


def build_static(entries):
    """渲染前 LIMIT 条为静态 HTML，结构与 JS 渲染结果一致"""
    out = []
    last = ''
    for news in entries[:LIMIT]:
        date = news.get('date', '')
        show_date = date != last
        last = date

        if news.get('content'):
            body = '<div class="news-content">%s</div>' % news['content']
        else:
            cat = news.get('category')
            cat_tag = ''
            if cat:
                cat_tag = ('<span style="display:inline-block;background:rgba(255,255,255,.2);'
                           'border:1px solid rgba(255,255,255,.4);border-radius:10px;'
                           'padding:1px 10px;font-size:.75rem;margin-bottom:6px;">%s</span><br>'
                           % esc(cat))
            title = news.get('title') or '（无标题）'
            href = news.get('url') or '#'
            body = ('<div class="news-content">%s<a href="%s" target="_blank" rel="noopener" '
                    'style="color:#fff;text-decoration:underline;word-break:break-all;">%s</a></div>'
                    % (cat_tag, esc(href), esc(title)))

        date_block = ('<div class="news-date">%s</div>' % format_date(date)) if show_date else ''
        out.append('<div class="news-item">%s%s</div>' % (date_block, body))
    return '\n                    '.join(out)


def replace_container(src, container_id, new_inner):
    """整体替换 id=container_id 的 div 内部内容，正确处理嵌套的 </div>。"""
    open_re = re.compile(r'<div[^>]*\bid="%s"[^>]*>' % re.escape(container_id))
    m = open_re.search(src)
    if not m:
        return None
    tag_re = re.compile(r'<(/?)div\b[^>]*>')
    depth = 1
    pos = m.end()
    while depth > 0:
        t = tag_re.search(src, pos)
        if not t:
            return None
        depth += -1 if t.group(1) == '/' else 1
        pos = t.end()
    close_start = pos - len('</div>')
    return src[:m.end()] + new_inner + src[close_start:]


def main():
    path = os.path.join(REPO, 'news.html')
    if not os.path.exists(path):
        print('  news.html 不存在，跳过预渲染')
        return 0

    src = io.open(path, encoding='utf-8').read()
    original = src

    # 1. 清掉上次注入的内容（保证幂等）
    src = re.sub(re.escape(MARK_START) + r'.*?' + re.escape(MARK_END) + r'\s*',
                 '', src, flags=re.S)
    # 2. 清掉上次的 noscript 说明
    src = re.sub(r'<noscript><p style="padding:1rem;opacity:\.85;">本页新闻由 JavaScript.*?</p></noscript>\s*',
                 '', src, flags=re.S)

    entries = load_news()
    if not entries:
        print('  [预渲染] news.json 为空，跳过')
        return 0

    static = build_static(entries)
    inner = ('\n                    ' + MARK_START + '\n                    '
             + static + '\n                    ' + MARK_END + '\n                ')

    new_src = replace_container(src, CONTAINER_ID, inner)
    if new_src is None:
        print('  [警告] 未找到 #%s 容器，跳过注入' % CONTAINER_ID)
        return 1

    # 3. 在容器前插入 noscript 说明（找不到容器时才可能缺，此时已定位成功）
    m = re.search(r'<div[^>]*\bid="%s"' % re.escape(CONTAINER_ID), new_src)
    if m and '<noscript>' not in new_src[:m.start()][-400:]:
        noscript = ('<noscript><p style="padding:1rem;opacity:.85;">本页新闻由 JavaScript 提供筛选与翻页，'
                    '上方已显示最新条目，完整历史可访问 '
                    '<a href="/calendar.html" style="color:#fff;">新闻日历</a>。</p></noscript>\n        ')
        new_src = new_src[:m.start()] + noscript + new_src[m.start():]

    if new_src != original:
        io.open(path, 'w', encoding='utf-8', newline='').write(new_src)
        print('  [预渲染] 已注入 %d 条静态新闻到 news.html' % min(len(entries), LIMIT))
    else:
        print('  [预渲染] news.html 无变化')
    return 0


if __name__ == '__main__':
    sys.exit(main())
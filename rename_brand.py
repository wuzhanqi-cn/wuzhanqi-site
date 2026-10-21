# -*- coding: utf-8 -*-
"""
把站点品牌名从误写的「五战旗」改为「吴展旗」（域名 wuzhanqi.cn 的正确写法），
并移除首页上直接展示品牌名的 h1 文字（保留 h1 标签本身供 SEO 使用）。
"""
import io, os, re, glob

REPO = os.path.dirname(os.path.abspath(__file__))
OLD = '五战旗'
NEW = '吴展旗'

# 需要改名的文件（文本中出现 OLD 的全部替换）
targets = []
for ext in ('html', 'json'):
    targets += glob.glob(os.path.join(REPO, '**', '*.' + ext), recursive=True)
targets = [t for t in targets if not t.endswith('news.json')]  # 新闻数据不含品牌名

changed = []
for path in sorted(set(targets)):
    with io.open(path, encoding='utf-8') as f:
        src = f.read()
    if OLD not in src:
        continue

    # 首页 h1：去掉可见的品牌名，只保留域名（h1 标签保留）
    src = src.replace(
        '<h1 class="domain">%s <span>wuzhanqi.cn</span></h1>' % OLD,
        '<h1 class="domain">wuzhanqi.cn</h1>')

    # 其余一律改名
    src = src.replace(OLD, NEW)

    with io.open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(src)
    changed.append(os.path.basename(path))

print('=' * 58)
print('已改名 %s -> %s' % (OLD, NEW))
for c in changed:
    print('  ' + c)
print('=' * 58)
print('共 %d 个文件' % len(changed))

# 校验：不应再有残留
leftover = 0
for ext in ('html', 'json'):
    for p in glob.glob(os.path.join(REPO, '**', '*.' + ext), recursive=True):
        if p.endswith('news.json'):
            continue
        with io.open(p, encoding='utf-8') as f:
            leftover += f.read().count(OLD)
print('残留 %s : %d 处' % (OLD, leftover))

# 校验首页 h1
idx = io.open(os.path.join(REPO, 'index.html'), encoding='utf-8').read()
m = re.search(r'<h1[^>]*>(.*?)</h1>', idx, re.S)
print('首页 h1 内容: %r' % (m.group(1) if m else '(未找到)'))

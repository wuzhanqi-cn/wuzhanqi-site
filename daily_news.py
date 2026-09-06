#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日新闻摘要生成脚本
1. 抓取义乌本地新闻 + 国内/国际要闻标题
2. 调用 SiliconFlow AI 生成一段每日摘要（世界要闻 + 义乌本地）
3. 更新 news.json（一天一段格式，最新在前）
"""

import urllib.request
import urllib.parse
import json
import re
import os
import sys
import threading
from datetime import datetime, timezone, timedelta

# ============== 配置 ==============
OUTPUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'news.json')
SF_API_KEY = os.environ.get('SILICONFLOW_API_KEY', '')
SF_API_URL = 'https://api.siliconflow.cn/v1/chat/completions'
SF_MODEL = 'deepseek-ai/DeepSeek-V3'
MAX_ENTRIES = 120
BEIJING_TZ = timezone(timedelta(hours=8))

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9',
}

# ============== 工具函数 ==============
def fetch_url(url, timeout=12, referer=None, extra_headers=None):
    headers = dict(HEADERS)
    if referer:
        headers['Referer'] = referer
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()

# ============== 义乌新闻抓取（复用原有逻辑） ==============
YW_COLUMNS = [
    {'pageId': '1229187636', 'category': '义乌要闻'},
    {'pageId': '1229144443', 'category': '部门动态'},
    {'pageId': '1229144444', 'category': '镇街动态'},
    {'pageId': '1229187644', 'category': '公告公示'},
]
YW_API_URL = 'https://www.yw.gov.cn/api-gateway/jpaas-publish-server/front/page/build/unit'

def fetch_yw_column(page_id, category):
    params = {
        'parseType': 'bulidstatic', 'webId': '3549',
        'tplSetId': 'zfHuDn7pjzPV0dB1wLhu9', 'pageType': 'column',
        'tagId': '新闻列表', 'editType': 'null', 'pageId': page_id,
    }
    url = YW_API_URL + '?' + urllib.parse.urlencode(params)
    try:
        raw = fetch_url(url, referer=f'https://www.yw.gov.cn/col/col{page_id}/index.html',
                        extra_headers={'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'})
        data = json.loads(raw.decode('utf-8'))
        html = data.get('data', {}).get('html', '')
        pattern = r'<a[^>]*title="([^"]*)"[^>]*href="([^"]*)"[^>]*>[^<]*</a>\s*<span>(\d{4}-\d{2}-\d{2})</span>'
        results = []
        for title, href, date in re.findall(pattern, html):
            if href.startswith('/'):
                href = 'https://www.yw.gov.cn' + href
            results.append({'date': date, 'title': title.strip(), 'url': href})
        return results
    except Exception as e:
        print(f'  [yw] {category} 失败: {e}')
        return []

def fetch_yw_all():
    results = {}
    lock = threading.Lock()
    def worker(col):
        news = fetch_yw_column(col['pageId'], col['category'])
        with lock:
            results[col['category']] = news
        print(f'  [yw] {col["category"]}: {len(news)} 条')
    threads = [threading.Thread(target=worker, args=(c,)) for c in YW_COLUMNS]
    for t in threads: t.start()
    for t in threads: t.join(timeout=30)
    all_news = []
    for col in YW_COLUMNS:
        all_news.extend(results.get(col['category'], []))
    return all_news

def fetch_zgyww():
    try:
        raw = fetch_url('http://news.zgyww.cn/')
        html = raw.decode('gbk', errors='replace')
        pattern = r'href=["\']((?:http://news\.zgyww\.cn)?/system/\d{4}/\d{2}/\d{2}/\d+\.shtml)["\'][^>]*>([^<]+)<'
        seen, results = set(), []
        for href, title in re.findall(pattern, html):
            if href.startswith('/'):
                href = 'http://news.zgyww.cn' + href
            title = title.strip()
            if not title or len(title) < 4 or href in seen:
                continue
            seen.add(href)
            m = re.search(r'/system/(\d{4})/(\d{2})/(\d{2})/', href)
            date = f'{m.group(1)}-{m.group(2)}-{m.group(3)}' if m else datetime.now(BEIJING_TZ).strftime('%Y-%m-%d')
            results.append({'date': date, 'title': title, 'url': href})
        print(f'  [zgyww] {len(results)} 条')
        return results
    except Exception as e:
        print(f'  [zgyww] 失败: {e}')
        return []

# ============== 国内/国际要闻抓取 ==============
SKIP_WORDS = ['更多', '返回', '首页', '登录', '注册', '下载', '客户端', '微博', '微信',
              '视频', '图片', '直播', '专题', '滚动', '排行', '搜索', '关于我们', '联系方式',
              'ENGLISH', 'English', '简', '繁', '客户端下载', 'APP', '订阅', '投稿']

def extract_headlines(html, min_len=8, max_len=60):
    """从 HTML 中提取合理的新闻标题"""
    results = []
    # 匹配 <a ...>标题</a>
    for title in re.findall(r'<a[^>]*>([^<]{8,60})</a>', html):
        title = title.strip()
        if not title or len(title) < min_len or len(title) > max_len:
            continue
        if any(skip in title for skip in SKIP_WORDS):
            continue
        # 过滤纯英文/纯数字
        if not re.search(r'[\u4e00-\u9fff]', title):
            continue
        results.append(title)
    return results

def fetch_world_news():
    """从多个来源抓取国内/国际要闻标题"""
    headlines = []
    sources = [
        ('人民网', 'http://www.people.com.cn/'),
        ('央视新闻', 'https://news.cctv.com/'),
        ('中国新闻网', 'https://www.chinanews.com.cn/'),
        ('新华网', 'http://www.xinhuanet.com/'),
    ]
    for name, url in sources:
        if len(headlines) >= 15:
            break
        try:
            raw = fetch_url(url, timeout=10)
            html = raw.decode('utf-8', errors='replace')
            found = extract_headlines(html)
            for h in found:
                if h not in headlines:
                    headlines.append(h)
            print(f'  [{name}] {len(found)} 条, 累计 {len(headlines)} 条')
        except Exception as e:
            print(f'  [{name}] 失败: {e}')

    # 去重并限制
    seen = set()
    unique = []
    for h in headlines:
        if h not in seen:
            seen.add(h)
            unique.append(h)
    return unique[:20]

# ============== AI 生成摘要 ==============
def generate_summary(yiwu_news, world_headlines):
    """调用 SiliconFlow AI 生成每日新闻摘要"""
    today = datetime.now(BEIJING_TZ).strftime('%Y年%m月%d日')

    # 整理义乌新闻（取今天和昨天的）
    today_str = datetime.now(BEIJING_TZ).strftime('%Y-%m-%d')
    yesterday_str = (datetime.now(BEIJING_TZ) - timedelta(days=1)).strftime('%Y-%m-%d')
    recent_yiwu = [n for n in yiwu_news if n['date'] in (today_str, yesterday_str)]
    if not recent_yiwu:
        recent_yiwu = yiwu_news[:10]  #  fallback: 取最新10条

    yiwu_text = '\n'.join(f'- {n["title"]}' for n in recent_yiwu[:12])
    world_text = '\n'.join(f'- {h}' for h in world_headlines[:15])

    prompt = f"""今天是{today}。请根据以下新闻素材，写一段"每日要闻"摘要，用于个人网站展示。

要求：
1. 分两部分：先写"🌍 世界要闻"（3-5条国内国际重要新闻，用一段话概括），再写"🏛️ 义乌本地"（3-5条义乌重要新闻，用一段话概括）
2. 用 HTML <p> 标签分段，重要新闻标题用 <strong> 加粗
3. 语言简洁客观，每部分150-250字
4. 只基于提供的素材写，不要编造新闻；如果某部分素材不足就少写几条
5. 直接输出 HTML 内容，不要任何解释或 markdown 代码块标记

【国内/国际新闻素材】
{world_text if world_text else '（暂未获取到国际新闻素材）'}

【义乌本地新闻素材】
{yiwu_text if yiwu_text else '（暂未获取到义乌新闻素材）'}
"""

    body = json.dumps({
        'model': SF_MODEL,
        'messages': [
            {'role': 'system', 'content': '你是一个专业的新闻编辑，擅长把多条新闻标题整理成简洁的每日要闻摘要。'},
            {'role': 'user', 'content': prompt},
        ],
        'max_tokens': 800,
        'temperature': 0.5,
    }).encode('utf-8')

    req = urllib.request.Request(SF_API_URL, data=body, headers={
        'Authorization': f'Bearer {SF_API_KEY}',
        'Content-Type': 'application/json',
    })
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    content = data['choices'][0]['message']['content'].strip()
    # 清理可能的 markdown 代码块标记
    content = re.sub(r'^```html\s*', '', content)
    content = re.sub(r'\s*```$', '', content)
    return content

# ============== 主函数 ==============
def main():
    print('=' * 50)
    print('每日新闻摘要生成')
    print(f'时间: {datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")} (北京时间)')
    print('=' * 50)

    if not SF_API_KEY:
        print('错误: 未设置 SILICONFLOW_API_KEY 环境变量')
        return 1

    # 1. 抓取新闻
    print('\n[1/4] 抓取义乌本地新闻...')
    yw_news = fetch_yw_all()
    zgyww_news = fetch_zgyww()
    yiwu_all = yw_news + zgyww_news
    print(f'  义乌新闻共 {len(yiwu_all)} 条')

    print('\n[2/4] 抓取国内/国际要闻...')
    world_headlines = fetch_world_news()
    print(f'  国际/国内要闻共 {len(world_headlines)} 条')

    # 2. AI 生成摘要
    print('\n[3/4] AI 生成摘要...')
    try:
        summary = generate_summary(yiwu_all, world_headlines)
        print(f'  摘要生成成功 ({len(summary)} 字符)')
        print(f'  预览: {summary[:120]}...')
    except Exception as e:
        print(f'  AI 生成失败: {e}')
        return 1

    # 3. 更新 news.json
    print('\n[4/4] 更新 news.json...')
    today = datetime.now(BEIJING_TZ).strftime('%Y-%m-%d')

    # 读取现有数据
    existing = []
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, list):
            existing = data
        elif isinstance(data, dict) and 'news' in data:
            # 旧格式转换：跳过（已经是新格式了）
            existing = []

    # 移除今天已有的条目（重新生成）
    existing = [e for e in existing if e.get('date') != today]
    # 插入新条目到最前面
    new_entry = {'date': today, 'content': summary}
    result = [new_entry] + existing
    # 限制条数
    result = result[:MAX_ENTRIES]

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f'  已保存 {len(result)} 天的新闻到 {OUTPUT_FILE}')
    print(f'  今日条目: {today}')
    print('\n完成!')
    return 0

if __name__ == '__main__':
    sys.exit(main())

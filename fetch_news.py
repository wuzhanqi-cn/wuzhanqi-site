#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
义乌每日新闻抓取脚本
数据源：
  1. 义乌市政府门户网站 (yw.gov.cn) - 义乌要闻、部门动态、镇街动态、公告公示
  2. 义乌新闻网 (news.zgyww.cn) - 社会、资讯
输出：news.json (格式与现有网站兼容)
"""

import urllib.request
import urllib.parse
import json
import re
import os
import sys
import threading
from datetime import datetime

# ============== 配置 ==============
OUTPUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'news.json')
EXISTING_NEWS_URL = 'https://wuzhanqi.cn/news.json'

# yw.gov.cn 栏目配置
YW_COLUMNS = [
    {'pageId': '1229187636', 'category': '义乌要闻', 'colName': '义乌要闻'},
    {'pageId': '1229144443', 'category': '部门动态', 'colName': '部门动态'},
    {'pageId': '1229144444', 'category': '镇街动态', 'colName': '镇街动态'},
    {'pageId': '1229187644', 'category': '公告公示', 'colName': '公告公示'},
]

YW_API_URL = 'https://www.yw.gov.cn/api-gateway/jpaas-publish-server/front/page/build/unit'
YW_WEB_ID = '3549'
YW_TPL_SET_ID = 'zfHuDn7pjzPV0dB1wLhu9'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9',
}

# ============== 工具函数 ==============
def fetch_url(url, timeout=10, referer=None, extra_headers=None):
    """抓取 URL 内容，返回原始 bytes"""
    headers = dict(HEADERS)
    if referer:
        headers['Referer'] = referer
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()

def classify_zgyww_title(title):
    """根据标题简单分类 zgyww 新闻"""
    social_keywords = ['老人', '学生', '孩子', '市民', '村民', '居民', '骑手', '外卖',
                        '老兵', '退役军人', '创业', '生意', '市场', '商户', '老板',
                        '校园', '开学', '放学', '医院', '医生', '护士', '警',
                        '消防', '救援', '事故', '纠纷', '调解', '文化', '艺术',
                        '体育', '比赛', '篮球', '马拉松', '音乐', '演出', '电影',
                        '美食', '丰收', '乡村', '社区', '街道', '镇', '村']
    info_keywords = ['政策', '通知', '公告', '公示', '规定', '办法', '条例', '补贴',
                     '贴息', '贷款', '基金', '立项', '获批', '启用', '上线',
                     '实施', '执行', '发布', '出台', '规划', '计划', '数据',
                     '统计', '报告', '调研', '会议', '推进', '部署', '检查',
                     '督查', '考核', '评估', '认证', '标准', '规范', '试点']
    
    title_lower = title
    for kw in info_keywords:
        if kw in title_lower:
            return '资讯'
    for kw in social_keywords:
        if kw in title_lower:
            return '社会'
    return '资讯'  # 默认资讯

# ============== 抓取 yw.gov.cn ==============
def fetch_yw_column(page_id, category):
    """抓取义乌政府门户单个栏目"""
    params = {
        'parseType': 'bulidstatic',
        'webId': YW_WEB_ID,
        'tplSetId': YW_TPL_SET_ID,
        'pageType': 'column',
        'tagId': '新闻列表',
        'editType': 'null',
        'pageId': page_id,
    }
    url = YW_API_URL + '?' + urllib.parse.urlencode(params)
    referer = f'https://www.yw.gov.cn/col/col{page_id}/index.html'
    
    try:
        raw = fetch_url(url, referer=referer, extra_headers={
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'X-Requested-With': 'XMLHttpRequest',
        })
        data = json.loads(raw.decode('utf-8'))
        if not data.get('success'):
            print(f'  [yw] 栏目 {category} API 返回失败: {data.get("message")}')
            return []
        
        html = data.get('data', {}).get('html', '')
        # 解析 <li><a title="..." href="...">标题</a><span>日期</span></li>
        pattern = r'<a[^>]*title="([^"]*)"[^>]*href="([^"]*)"[^>]*>[^<]*</a>\s*<span>(\d{4}-\d{2}-\d{2})</span>'
        matches = re.findall(pattern, html)
        
        news_list = []
        for title, href, date in matches:
            if href.startswith('/'):
                href = 'https://www.yw.gov.cn' + href
            elif href.startswith('http'):
                pass
            else:
                href = 'https://www.yw.gov.cn/' + href
            news_list.append({
                'date': date,
                'title': title.strip(),
                'category': category,
                'url': href,
            })
        return news_list
    except Exception as e:
        print(f'  [yw] 栏目 {category} 抓取异常: {e}')
        return []

def fetch_yw_all():
    """抓取义乌政府门户所有栏目（并发）"""
    results = {}
    lock = threading.Lock()
    
    def fetch_one(col):
        try:
            print(f'  [yw] 抓取 {col["category"]} (pageId={col["pageId"]})...')
            news = fetch_yw_column(col['pageId'], col['category'])
            with lock:
                results[col['category']] = news
            print(f'    -> {col["category"]} 获取 {len(news)} 条')
        except Exception as e:
            print(f'    -> {col["category"]} 抓取失败: {e}')
            with lock:
                results[col['category']] = []
    
    threads = []
    for col in YW_COLUMNS:
        t = threading.Thread(target=fetch_one, args=(col,))
        threads.append(t)
        t.start()
    
    for t in threads:
        t.join(timeout=30)  # 单个栏目最多等30秒
    
    all_news = []
    for col in YW_COLUMNS:
        all_news.extend(results.get(col['category'], []))
    return all_news

# ============== 抓取 zgyww.cn ==============
def fetch_zgyww():
    """抓取义乌新闻网首页新闻"""
    print('  [zgyww] 抓取首页...')
    try:
        raw = fetch_url('http://news.zgyww.cn/')
        html = raw.decode('gbk', errors='replace')
        
        # 提取新闻链接
        pattern = r'href=["\']((?:http://news\.zgyww\.cn)?/system/\d{4}/\d{2}/\d{2}/\d+\.shtml)["\'][^>]*>([^<]+)<'
        matches = re.findall(pattern, html)
        
        news_list = []
        seen_urls = set()
        for href, title in matches:
            if href.startswith('/'):
                href = 'http://news.zgyww.cn' + href
            title = title.strip()
            if not title or len(title) < 4 or href in seen_urls:
                continue
            seen_urls.add(href)
            
            # 从 URL 提取日期: /system/2026/09/05/xxx.shtml
            date_match = re.search(r'/system/(\d{4})/(\d{2})/(\d{2})/', href)
            if date_match:
                date = f'{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}'
            else:
                date = datetime.now().strftime('%Y-%m-%d')
            
            category = classify_zgyww_title(title)
            news_list.append({
                'date': date,
                'title': title,
                'category': category,
                'url': href,
            })
        
        print(f'    -> 获取 {len(news_list)} 条')
        return news_list
    except Exception as e:
        print(f'  [zgyww] 抓取异常: {e}')
        return []

# ============== 合并与去重 ==============
def merge_news(existing, new_news):
    """合并新旧新闻，按 URL 去重，保留历史数据"""
    seen = {}
    # 先放已有数据
    for item in existing:
        url = item.get('url', '')
        if url and url not in seen:
            seen[url] = item
    # 再放新数据（新数据覆盖旧的同 URL 条目）
    for item in new_news:
        url = item.get('url', '')
        if url:
            seen[url] = item
    
    # 转为列表，按日期倒序
    result = list(seen.values())
    result.sort(key=lambda x: x.get('date', ''), reverse=True)
    return result

def load_existing_news():
    """从线上下载现有 news.json"""
    try:
        print('  下载现有 news.json...')
        raw = fetch_url(EXISTING_NEWS_URL, timeout=10)
        data = json.loads(raw.decode('utf-8'))
        if isinstance(data, dict) and 'news' in data:
            news = data['news']
        elif isinstance(data, list):
            news = data
        else:
            news = []
        print(f'    -> 现有 {len(news)} 条')
        return news
    except Exception as e:
        print(f'    -> 下载失败，将从零开始: {e}')
        return []

# ============== 主函数 ==============
def main():
    print('=' * 50)
    print('义乌每日新闻抓取脚本')
    print(f'开始时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print('=' * 50)
    
    # 1. 抓取新新闻
    print('\n[1/3] 抓取义乌市政府门户网站...')
    yw_news = fetch_yw_all()
    
    print('\n[2/3] 抓取义乌新闻网...')
    zgyww_news = fetch_zgyww()
    
    new_news = yw_news + zgyww_news
    print(f'\n本次共抓取 {len(new_news)} 条新闻')
    
    # 2. 加载现有数据并合并
    print('\n[3/3] 合并数据...')
    existing = load_existing_news()
    merged = merge_news(existing, new_news)
    print(f'合并后共 {len(merged)} 条新闻')
    
    # 3. 输出
    output = {
        'lastUpdate': datetime.now().astimezone().isoformat(timespec='seconds'),
        'source': '义乌市政府门户网站 & 义乌新闻网',
        'news': merged,
    }
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f'\n已保存到: {OUTPUT_FILE}')
    print(f'文件大小: {os.path.getsize(OUTPUT_FILE)} bytes')
    
    # 打印最新 5 条
    print('\n最新 5 条:')
    for item in merged[:5]:
        print(f'  [{item["date"]}] [{item["category"]}] {item["title"][:40]}')
    
    print('\n完成!')
    return 0

if __name__ == '__main__':
    sys.exit(main())

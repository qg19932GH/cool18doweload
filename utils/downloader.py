import os
import re
import time
import requests
from .parser import (
    get_page,
    parse_novel_name,
    parse_post_content,
    parse_search_results,
    parse_pagination,
)


def search_novel(novel_name, keywords, log_callback=None, delay=2):
    """
    使用多个关键词搜索小说，合并结果并按 tid 去重。
    """
    all_results = []
    seen_tids = set()

    for kw_idx, keyword in enumerate(keywords, 1):
        total_kw = len(keywords)
        if log_callback:
            log_callback(f"  正在使用关键词「{keyword}」搜索（{kw_idx}/{total_kw}）...")

        keyword_encoded = requests.utils.quote(keyword)
        first_url = f"https://www.cool18.com/search.php?keyword={keyword_encoded}&sa=全成人区搜索"

        try:
            soup = get_page(first_url)
        except Exception as e:
            if log_callback:
                log_callback(f"  关键词「{keyword}」搜索失败: {e}")
            continue

        page_results = parse_search_results(soup, novel_name)
        for title, url in page_results:
            tid_match = re.search(r"tid=(\d+)", url)
            tid = tid_match.group(1) if tid_match else url
            if tid not in seen_tids:
                seen_tids.add(tid)
                all_results.append((title, url))

        total_pages = parse_pagination(soup, first_url)
        if log_callback:
            log_callback(f"  关键词「{keyword}」共 {total_pages} 页搜索结果")

        for page in range(2, total_pages + 1):
            time.sleep(delay)
            page_url = f"https://www.cool18.com/search.php?keyword={keyword_encoded}&p={page}"
            try:
                soup = get_page(page_url)
            except Exception:
                break
            page_results = parse_search_results(soup, novel_name)
            for title, u in page_results:
                tid_match = re.search(r"tid=(\d+)", u)
                tid = tid_match.group(1) if tid_match else u
                if tid not in seen_tids:
                    seen_tids.add(tid)
                    all_results.append((title, u))

        if log_callback:
            log_callback(f"  关键词「{keyword}」累计找到 {len(all_results)} 个不重复帖子")

    from .parser import extract_sort_key
    all_results.sort(key=lambda x: extract_sort_key(x[0]))
    return all_results


def fetch_posts(posts, log_callback=None, delay=2, max_retries=3):
    """批量爬取帖子内容"""
    results = []
    total = len(posts)

    for i, (title, url) in enumerate(posts, 1):
        content = ""
        success = False

        for attempt in range(max_retries):
            try:
                soup = get_page(url)
                content = parse_post_content(soup)
                if content:
                    success = True
                break
            except Exception:
                if attempt < max_retries - 1:
                    time.sleep(2)

        results.append((title, url, content, success))

        if i < total:
            time.sleep(delay)

    return results


def save_to_txt(results, filepath):
    """将爬取结果保存为 TXT 文件"""
    dir_name = os.path.dirname(filepath)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("=" * 60 + "\n")
        success_count = sum(1 for r in results if r[3])
        f.write(f"共 {success_count} 个帖子\n")
        f.write("=" * 60 + "\n\n")

        for title, url, content, success in results:
            if success:
                f.write("=" * 60 + "\n")
                f.write(title + "\n")
                f.write("=" * 60 + "\n\n")
                f.write(content + "\n\n")

    return filepath
import os
import re
import time
import requests
from .parser import (
    get_page,
    parse_novel_name,
    parse_post_content,
    parse_post_links,
    is_index_post,
    parse_search_results,
    parse_pagination,
    extract_sort_key,
    get_max_chapter,
)


def search_and_find_posts(novel_name, keywords, log_callback=None, delay=2):
    """
    多关键词搜索 + 索引帖检测。
    1. 用所有关键词搜索，合并去重
    2. 检查每个搜索结果是否为索引帖
    3. 如果找到索引帖，从其内容中提取完整章节列表
    """
    all_results = []
    seen_tids = set()

    for kw_idx, keyword in enumerate(keywords, 1):
        total_kw = len(keywords)
        if log_callback:
            log_callback(f"  使用关键词「{keyword}」搜索（{kw_idx}/{total_kw}）...")

        keyword_encoded = requests.utils.quote(keyword)
        first_url = f"https://www.cool18.com/search.php?keyword={keyword_encoded}&sa=全成人区搜索"

        try:
            soup = get_page(first_url)
        except Exception as e:
            if log_callback:
                log_callback(f"  关键词「{keyword}」搜索失败: {e}")
            continue

        page_results = parse_search_results(soup, keywords)
        for title, url in page_results:
            tid_match = re.search(r"tid=(\d+)", url)
            tid = tid_match.group(1) if tid_match else url
            if tid not in seen_tids:
                seen_tids.add(tid)
                all_results.append((title, url))

        total_pages = parse_pagination(soup, first_url)
        if log_callback:
            log_callback(f"  共 {total_pages} 页搜索结果")

        for page in range(2, total_pages + 1):
            time.sleep(delay)
            page_url = f"https://www.cool18.com/search.php?keyword={keyword_encoded}&p={page}"
            try:
                soup = get_page(page_url)
            except Exception:
                break
            page_results = parse_search_results(soup, keywords)
            for title, u in page_results:
                tid_match = re.search(r"tid=(\d+)", u)
                tid = tid_match.group(1) if tid_match else u
                if tid not in seen_tids:
                    seen_tids.add(tid)
                    all_results.append((title, u))

        if log_callback:
            log_callback(f"  累计找到 {len(all_results)} 个不重复帖子")

    if not all_results:
        return [], "搜索无结果"

    # 检测索引帖
    if log_callback:
        log_callback(f"  正在检测索引帖（共 {len(all_results)} 个帖子）...")

    index_links = []
    index_source = None
    from .parser import is_chapter_link
    for title, url in all_results:
        try:
            soup = get_page(url)
            post_links = parse_post_links(soup, novel_name)
            chapter_links = [(t, u) for t, u in post_links if is_chapter_link(t, novel_name)]
            if is_index_post(chapter_links, threshold=5):
                seen_tids_local = set()
                for _, u in chapter_links:
                    m = re.search(r"tid=(\d+)", u)
                    if m:
                        seen_tids_local.add(m.group(1))
                chapter_count = len(seen_tids_local)
                if log_callback:
                    log_callback(f"  发现索引帖: {title[:60]} (包含 {chapter_count} 个章节链接)")
                if chapter_count > len(index_links):
                    index_links = chapter_links
                    index_source = title
        except Exception:
            continue
        time.sleep(1)

    if index_links:
        seen = set()
        unique_links = []
        for text, url in index_links:
            tid_match = re.search(r"tid=(\d+)", url)
            tid = tid_match.group(1) if tid_match else url
            if tid not in seen:
                seen.add(tid)
                unique_links.append((text, url))
        unique_links.sort(key=lambda x: extract_sort_key(x[0]))

        max_ch = get_max_chapter(unique_links)
        if log_callback:
            log_callback(f"  使用索引帖「{index_source[:40]}」作为章节来源")
            log_callback(f"  索引帖包含 {len(unique_links)} 个章节，最大章节: {max_ch}")

        index_tids = set(seen)
        for title, url in all_results:
            tid_match = re.search(r"tid=(\d+)", url)
            if tid_match and tid_match.group(1) not in index_tids:
                if log_callback:
                    log_callback(f"  索引帖外补充: {title[:60]}")
                unique_links.append((title, url))
        unique_links.sort(key=lambda x: extract_sort_key(x[0]))

        return unique_links, f"索引帖: {index_source}"

    all_results.sort(key=lambda x: extract_sort_key(x[0]))
    max_ch = get_max_chapter(all_results)
    if log_callback:
        log_callback(f"  未找到索引帖，使用搜索结果，最大章节: {max_ch}")
    return all_results, f"搜索结果（最大章节: {max_ch}）"


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


def save_to_txt(results, filepath, novel_name=""):
    """将爬取结果保存为 TXT 文件"""
    dir_name = os.path.dirname(filepath)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("=" * 60 + "\n")
        if novel_name:
            f.write(f"小说: {novel_name}\n")
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
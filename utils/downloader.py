import os
import re
import sys
import time
import requests
from .parser import (
    get_page,
    parse_post_content,
    parse_post_links,
    is_index_post,
    parse_search_results,
    parse_pagination,
    extract_sort_key,
    extract_content_chapter_range,
    get_max_chapter,
    smart_sort_posts,
)


def search_and_find_posts(novel_name, keywords, log_callback=None, delay=2, proxy_port=None):
    """多关键词搜索 + 索引帖检测 + 智能排序 + 去重"""
    all_results = []
    seen_tids = set()

    for kw_idx, keyword in enumerate(keywords, 1):
        total_kw = len(keywords)
        if log_callback:
            log_callback(f"  使用关键词「{keyword}」搜索（{kw_idx}/{total_kw}）...")

        keyword_encoded = requests.utils.quote(keyword)
        first_url = f"https://www.cool18.com/search.php?keyword={keyword_encoded}&sa=全成人区搜索"

        try:
            soup = get_page(first_url, proxy_port=proxy_port)
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
                soup = get_page(page_url, proxy_port=proxy_port)
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
    index_source_url = None
    index_source_title = None
    index_source_content = None
    index_tid = None
    for title, url in all_results:
        try:
            soup = get_page(url, proxy_port=proxy_port)
            post_links = parse_post_links(soup, novel_name)
            if is_index_post(post_links, threshold=5):
                seen_tids_local = set()
                for _, u in post_links:
                    m = re.search(r"tid=(\d+)", u)
                    if m:
                        seen_tids_local.add(m.group(1))
                chapter_count = len(seen_tids_local)
                if log_callback:
                    log_callback(f"  发现索引帖: {title[:60]} (包含 {chapter_count} 个章节链接)")
                if chapter_count > len(index_links):
                    index_links = post_links
                    index_source = title
                    index_source_url = url
                    index_source_title = title
                    index_source_content = parse_post_content(soup)
                    tid_match = re.search(r"tid=(\d+)", url)
                    index_tid = tid_match.group(1) if tid_match else None
        except Exception:
            continue
        time.sleep(1)

    if index_links:
        # 索引帖链接按 tid 去重
        seen = set()
        unique_index_links = []
        for text, url in index_links:
            tid_match = re.search(r"tid=(\d+)", url)
            tid = tid_match.group(1) if tid_match else url
            if tid not in seen:
                seen.add(tid)
                unique_index_links.append((text, url))

        if log_callback:
            log_callback(f"  使用索引帖「{index_source[:40]}」作为章节来源")
            log_callback(f"  索引帖包含 {len(unique_index_links)} 个章节链接")

        # 补充索引帖外且章节不重叠的搜索帖子
        index_tids = set(seen)
        index_chapters = set()
        for text, url in unique_index_links:
            start_ch, end_ch = extract_sort_key(text)
            if start_ch is not None:
                for ch in range(start_ch, end_ch + 1):
                    index_chapters.add(ch)

        for title, url in all_results:
            tid_match = re.search(r"tid=(\d+)", url)
            tid = tid_match.group(1) if tid_match else None
            # 跳过已在索引帖中的 tid，以及索引帖自己的 tid
            if tid in index_tids or tid == index_tid:
                continue
            # 跳过章节完全重叠的帖子
            start_ch, end_ch = extract_sort_key(title)
            if start_ch is not None:
                overlap = True
                for ch in range(start_ch, end_ch + 1):
                    if ch not in index_chapters:
                        overlap = False
                        break
                if overlap:
                    if log_callback:
                        log_callback(f"  跳过章节重叠: {title[:60]}")
                    continue

            if log_callback:
                log_callback(f"  补充帖子: {title[:60]}")
            unique_index_links.append((title, url))

        # 将索引帖本身加入列表（索引帖自身可能包含章节内容，如 01-05）
        # 从正文第一行提取实际章节范围（索引帖标题可能是目录范围，正文才是实际内容）
        content_range = extract_content_chapter_range(index_source_content)
        if content_range[0] is not None:
            # 用正文实际章节作为列表中的标题（用于排序/去重）
            first_line = index_source_content.split('\n')[0].strip()
            index_list_title = first_line
        else:
            content_range = extract_sort_key(index_source_title)
            index_list_title = index_source_title

        index_start, index_end = content_range
        index_included = False
        if index_start is not None:
            index_covered = all(ch in index_chapters for ch in range(index_start, index_end + 1))
            if not index_covered:
                if log_callback:
                    log_callback(f"  索引帖自身包含未覆盖章节 {index_start}-{index_end}: {index_source_title[:60]}")
                unique_index_links.append((index_list_title, index_source_url))
                index_included = True
            else:
                if log_callback:
                    log_callback(f"  索引帖自身章节 {index_start}-{index_end} 已被索引链接覆盖，跳过")
        else:
            unique_index_links.append((index_list_title, index_source_url))
            index_included = True

        max_ch = get_max_chapter(unique_index_links)
        if log_callback:
            log_callback(f"  合并后共 {len(unique_index_links)} 个帖子，最大章节: {max_ch}")

        # 智能排序 + 去重（如果索引帖已加入列表，不传入 index_tid 避免被排除）
        sort_index_tid = None if index_included else index_tid
        sorted_links = smart_sort_posts(
            unique_index_links, index_links, sort_index_tid, novel_name
        )
        return sorted_links, f"索引帖: {index_source}"

    # 没有索引帖，直接使用搜索结果
    sorted_results = smart_sort_posts(all_results, None, None, novel_name)
    max_ch = get_max_chapter(sorted_results)
    if log_callback:
        log_callback(f"  未找到索引帖，使用搜索结果，共 {len(sorted_results)} 个帖子，最大章节: {max_ch}")
    return sorted_results, f"搜索结果（最大章节: {max_ch}）"


def fetch_and_save_all(posts, novel_name, log_callback=None, delay=2, max_retries=3, proxy_port=None):
    """批量爬取所有章节并自动保存到 exe 同级目录"""
    results = []
    total = len(posts)

    for i, (title, url) in enumerate(posts, 1):
        content = ""
        success = False

        for attempt in range(max_retries):
            try:
                soup = get_page(url, proxy_port=proxy_port)
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

    # 自动保存
    exe_dir = get_exe_dir()
    safe_name = re.sub(r'[\\/:*?"<>|\r\n]+', '', novel_name) or "小说"
    filepath = os.path.join(exe_dir, f"{safe_name}.txt")
    save_to_txt(results, filepath, novel_name)
    file_size = os.path.getsize(filepath)
    return results, filepath, file_size


def get_exe_dir():
    """获取 exe 所在目录（打包后）或当前工作目录（开发时）"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.getcwd()


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

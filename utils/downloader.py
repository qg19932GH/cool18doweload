import os
import time
import re
import requests
from bs4 import BeautifulSoup
from .parser import (
    get_page,
    parse_novel_name,
    parse_post_content,
    parse_search_results,
    parse_pagination,
)


def search_novel(novel_name, delay=2):
    """
    Search for a novel on cool18 and return all related posts in 禁忌书屋 section.
    Returns list of (title, url) sorted by chapter order.
    """
    all_results = []
    search_url = "https://www.cool18.com/search.php?keyword={}&sa=全成人区搜索"
    keyword = requests.utils.quote(novel_name)
    first_url = search_url.format(keyword)

    try:
        soup = get_page(first_url)
    except Exception as e:
        raise RuntimeError(f"Failed to fetch search page: {e}")

    all_results.extend(parse_search_results(soup, novel_name))
    total_pages = parse_pagination(soup, first_url)

    for page in range(2, total_pages + 1):
        time.sleep(delay)
        url = f"https://www.cool18.com/search.php?keyword={keyword}&p={page}"
        try:
            soup = get_page(url)
        except Exception:
            break
        all_results.extend(parse_search_results(soup, novel_name))

    seen_urls = set()
    unique_results = []
    for title, url in all_results:
        tid_match = re.search(r"tid=(\d+)", url)
        tid = tid_match.group(1) if tid_match else url
        if tid not in seen_urls:
            seen_urls.add(tid)
            unique_results.append((title, url))

    return unique_results


def fetch_posts(urls, delay=2, max_retries=3):
    """
    Fetch content of all posts. Returns list of (title, url, content, success).
    """
    results = []
    for i, (title, url) in enumerate(urls):
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
        if i < len(urls) - 1:
            time.sleep(delay)
    return results


def save_to_txt(results, filepath):
    """
    Save all post contents to a txt file.
    results: list of (title, url, content, success)
    """
    os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else ".", exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        for title, url, content, success in results:
            if success:
                f.write(f"\n{'='*60}\n")
                f.write(f"{title}\n")
                f.write(f"{'='*60}\n\n")
                f.write(content)
                f.write("\n\n")
    return filepath

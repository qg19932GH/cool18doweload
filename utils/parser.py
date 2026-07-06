import re
import requests
from bs4 import BeautifulSoup


def get_page(url, timeout=15):
    """
    Request a page and return BeautifulSoup object.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.encoding = "utf-8"
    return BeautifulSoup(resp.text, "html.parser")


def parse_novel_name(soup):
    """
    Parse novel name from thread page.
    Title example: 【情话（我过分保守的妈妈）】（64-66）作者：小鹿不知归处（lzh1223）
    Extract: 情话（我过分保守的妈妈）
    """
    title_el = soup.select_one(".main-title")
    if not title_el:
        return None, None
    full_title = title_el.get_text(strip=True)
    match = re.search(r"【(.+?)】", full_title)
    if match:
        return match.group(1), full_title
    return full_title, full_title


def parse_post_content(soup):
    """
    Parse post content from thread page.
    """
    content_el = soup.select_one(".post-content")
    if not content_el:
        return ""
    text = content_el.get_text(separator="\n")
    lines = [line.strip() for line in text.split("\n")]
    lines = [line for line in lines if line]
    return "\n".join(lines)


def parse_search_results(soup, novel_name):
    """
    Parse search page for novel-related posts in 禁忌书屋 section.
    Returns list of (title, url, sort_key)
    """
    results = []
    items = soup.select(".search-content ul li a")
    for item in items:
        href = item.get("href", "")
        if "tid=" not in href:
            continue

        ps = item.select("p")
        if len(ps) < 2:
            continue

        section = ps[0].get_text(strip=True)
        title = ps[1].get_text(strip=True)

        if "禁忌书屋" not in section:
            continue
        if novel_name not in title:
            continue

        if not href.startswith("http"):
            href = "https://www.cool18.com" + href if href.startswith("/") else "https://www.cool18.com/bbs4/" + href

        sort_key = extract_sort_key(title)
        results.append((title, href, sort_key))

    results.sort(key=lambda x: x[2])
    return [(t, u) for t, u, _ in results]


def extract_sort_key(title):
    """
    Extract chapter number range for sorting.
    Example: 【情话（我过分保守的妈妈）】（64-66）作者：...
    Returns tuple of (start_chapter, end_chapter) for sorting.
    """
    match = re.search(r"（\s*(\d+)\s*-\s*(\d+)\s*）", title)
    if match:
        return (int(match.group(1)), int(match.group(2)))
    match = re.search(r"\((\d+)\s*[-~]\s*(\d+)\)", title)
    if match:
        return (int(match.group(1)), int(match.group(2)))
    match = re.search(r"(\d+)", title)
    if match:
        return (int(match.group(1)), int(match.group(1)))
    return (0, 0)


def parse_pagination(soup, base_url):
    """
    Parse total pages from search result pagination.
    """
    pages = soup.select(".search-page a")
    max_page = 1
    for page in pages:
        href = page.get("href", "")
        match = re.search(r"[&?]p=(\d+)", href)
        if match:
            max_page = max(max_page, int(match.group(1)))
    return max_page

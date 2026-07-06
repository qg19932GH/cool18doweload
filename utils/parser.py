import re
import requests
from bs4 import BeautifulSoup


def get_page(url, timeout=15):
    """请求页面并返回 BeautifulSoup 对象"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.encoding = "utf-8"
    return BeautifulSoup(resp.text, "html.parser")


def parse_novel_name(soup):
    """
    从帖子页面解析小说名称和搜索关键词。
    标题示例: 【情话（我过分保守的妈妈）】（64-66）作者：小鹿不知归处（lzh1223）
    返回: (小说名, 完整标题, 关键词列表)
    """
    title_el = soup.select_one(".main-title")
    if not title_el:
        return None, None, []
    full_title = title_el.get_text(strip=True)
    match = re.search(r"【(.+?)】", full_title)
    novel_name = match.group(1) if match else full_title
    keywords = extract_search_keywords(novel_name)
    return novel_name, full_title, keywords


def extract_search_keywords(novel_name):
    """
    从小说名中提取多个搜索关键词，按优先级排序。
    示例: "情话（我过分保守的妈妈）"
    -> ["我过分保守的妈妈", "情话（我过分保守的妈妈）"]
    策略: 先用短核心词搜索，再用完整名称搜索。
    """
    keywords = []

    inner = re.search(r"（(.+?)）", novel_name)
    if inner:
        core = inner.group(1).strip()
        if core and len(core) >= 2:
            keywords.append(core)

    clean = novel_name
    for prefix in ["情话", "故事", "小说", "传奇", "记"]:
        if clean.startswith(prefix):
            clean = clean[len(prefix):].strip("（）()")
            if clean and clean not in keywords:
                keywords.append(clean)

    if novel_name not in keywords:
        keywords.append(novel_name)

    return keywords


def parse_post_content(soup):
    """从帖子页面解析正文内容"""
    content_el = soup.select_one(".post-content")
    if not content_el:
        return ""
    text = content_el.get_text(separator="\n")
    lines = [line.strip() for line in text.split("\n")]
    lines = [line for line in lines if line]
    return "\n".join(lines)


def parse_post_links(soup, novel_name=""):
    """
    从帖子页面解析正文中包含的所有 tid= 链接。
    用于检测索引帖。
    返回: [(显示文本, url), ...]
    保留索引帖中的所有章节链接（包括特殊篇如"母亲节特别篇"）
    """
    content_el = soup.select_one(".post-content")
    if not content_el:
        return []
    links = []
    for a in content_el.find_all("a", href=True):
        href = a["href"]
        if "tid=" not in href:
            continue
        text = a.get_text(strip=True)
        if not text or len(text) < 3:
            continue
        skip_words = ["返回", "主帖", "首页", "投票", "举报", "分享", "回复", "管理", "联系"]
        if any(sw in text for sw in skip_words):
            continue
        if not href.startswith("http"):
            href = "https://www.cool18.com" + href if href.startswith("/") else "https://www.cool18.com/bbs4/" + href
        links.append((text, href))
    return links


def is_index_post(post_links, threshold=5):
    """
    判断帖子是否为索引帖（包含多个章节链接）。
    """
    seen_tids = set()
    for _, url in post_links:
        tid_match = re.search(r"tid=(\d+)", url)
        if tid_match:
            seen_tids.add(tid_match.group(1))
    return len(seen_tids) >= threshold


def parse_search_results(soup, keywords):
    """
    解析搜索页面，过滤出禁忌书屋版块的帖子。
    使用关键词列表进行匹配，任一关键词命中即可。
    返回: [(标题, url, 排序键), ...]
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

        # 任一关键词命中即可
        matched = False
        for kw in keywords:
            if kw in title:
                matched = True
                break
        if not matched:
            continue

        if not href.startswith("http"):
            href = "https://www.cool18.com" + href if href.startswith("/") else "https://www.cool18.com/bbs4/" + href

        sort_key = extract_sort_key(title)
        results.append((title, href, sort_key))

    results.sort(key=lambda x: x[2])
    return [(t, u) for t, u, _ in results]


def extract_sort_key(title):
    """
    从标题中提取章节编号范围，用于排序。
    示例: 【情话（我过分保守的妈妈）】（64-66）作者：...
    返回: (起始章, 结束章)
    """
    match = re.search(r"[（(]\s*(\d+)\s*[-~]+\s*(\d+)\s*[）)]", title)
    if match:
        return (int(match.group(1)), int(match.group(2)))
    match = re.search(r"[（(]\s*(\d+)\s*[）)]", title)
    if match:
        return (int(match.group(1)), int(match.group(1)))
    match = re.search(r"(\d+)", title)
    if match:
        return (int(match.group(1)), int(match.group(1)))
    return (0, 0)


def get_max_chapter(posts):
    """
    从帖子列表中获取最大章节号。
    """
    max_ch = 0
    for title, _ in posts:
        _, end = extract_sort_key(title)
        if end > max_ch:
            max_ch = end
    return max_ch


def parse_pagination(soup, base_url):
    """从搜索页面解析总页数"""
    pages = soup.select(".search-page a")
    max_page = 1
    for page in pages:
        href = page.get("href", "")
        match = re.search(r"[&?]p=(\d+)", href)
        if match:
            max_page = max(max_page, int(match.group(1)))
    return max_page
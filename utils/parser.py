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
    从小说名中提取多个搜索关键词。
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
    """判断帖子是否为索引帖（包含多个章节链接）"""
    seen_tids = set()
    for _, url in post_links:
        tid_match = re.search(r"tid=(\d+)", url)
        if tid_match:
            seen_tids.add(tid_match.group(1))
    return len(seen_tids) >= threshold


def parse_search_results(soup, keywords):
    """
    解析搜索页面，过滤出禁忌书屋版块的帖子。
    返回: [(标题, url), ...]
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

        if not any(kw in title for kw in keywords):
            continue

        if not href.startswith("http"):
            href = "https://www.cool18.com" + href if href.startswith("/") else "https://www.cool18.com/bbs4/" + href

        results.append((title, href))

    return results


def extract_sort_key(title):
    """
    从标题中提取章节编号范围。
    返回: (起始章, 结束章)，无编号返回 (None, None)
    """
    match = re.search(r"[（(]\s*(\d+)\s*[-~]+\s*(\d+)\s*[）)]", title)
    if match:
        return (int(match.group(1)), int(match.group(2)))
    match = re.search(r"[（(]\s*(\d+)\s*[）)]", title)
    if match:
        return (int(match.group(1)), int(match.group(1)))
    return (None, None)


def get_max_chapter(posts):
    """从帖子列表中获取最大章节号"""
    max_ch = 0
    for title, _ in posts:
        _, end = extract_sort_key(title)
        if end is not None and end > max_ch:
            max_ch = end
    return max_ch


def smart_sort_posts(posts, index_links=None):
    """
    智能排序帖子：
    1. 有编号的按章节号从小到大排序
    2. 索引帖中的无编号章节，根据索引帖中它前面的章节编号插入正确位置
    3. 搜索结果单独出现的无编号章节，放最后
    """
    # 构建索引帖的顺序映射
    index_tids = set()
    # 记录每个 tid 在索引帖中的位置（前面最后一个编号章节的结束编号）
    special_chapter_info = {}  # tid -> (标题, url, 前面的结束编号)

    if index_links:
        prev_end = 0
        for text, url in index_links:
            tid_match = re.search(r"tid=(\d+)", url)
            if not tid_match:
                continue
            tid = tid_match.group(1)
            index_tids.add(tid)

            start_ch, end_ch = extract_sort_key(text)
            if start_ch is not None:
                # 有编号
                prev_end = end_ch
            else:
                # 无编号（特殊章节），记录前面的编号
                special_chapter_info[tid] = (text, url, prev_end)

    # 分类帖子
    numbered_posts = []  # (标题, url, 起始章, 结束章)
    special_posts = []   # (标题, url, 应该插入的编号)
    extra_posts = []     # (标题, url)

    for title, url in posts:
        tid_match = re.search(r"tid=(\d+)", url)
        tid = tid_match.group(1) if tid_match else None
        start_ch, end_ch = extract_sort_key(title)

        if start_ch is not None:
            numbered_posts.append((title, url, start_ch, end_ch))
        elif tid and tid in special_chapter_info:
            # 索引帖中的无编号章节
            info = special_chapter_info[tid]
            special_posts.append((title, url, info[2]))  # 前面的结束编号
        else:
            # 搜索结果单独出现的无编号章节
            extra_posts.append((title, url))

    # 有编号的按章节号排序
    numbered_posts.sort(key=lambda x: x[2])

    # 合并：先放编号章节，再插入无编号章节到正确位置
    result = []
    special_inserted = set()

    for i, (title, url, start_ch, end_ch) in enumerate(numbered_posts):
        # 先插入应该在此章节之前的特殊章节
        for s_title, s_url, insert_after in special_posts:
            if insert_after < start_ch and s_title not in [r[0] for r in result]:
                result.append((s_title, s_url))
                special_inserted.add(s_title)
        result.append((title, url))

    # 剩余未插入的特殊章节（应该在最后）
    for s_title, s_url, _ in special_posts:
        if s_title not in special_inserted:
            result.append((s_title, s_url))

    # 搜索结果单独出现的无编号放最后
    for e_title, e_url in extra_posts:
        if e_title not in [r[0] for r in result]:
            result.append((e_title, e_url))

    return result


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
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
    """从帖子页面解析小说名称和搜索关键词"""
    title_el = soup.select_one(".main-title")
    if not title_el:
        return None, None, []
    full_title = title_el.get_text(strip=True)
    match = re.search(r"【(.+?)】", full_title)
    novel_name = match.group(1) if match else full_title
    keywords = extract_search_keywords(novel_name)
    return novel_name, full_title, keywords


def extract_search_keywords(novel_name):
    """从小说名中提取多个搜索关键词"""
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
    """从帖子页面解析正文中包含的所有 tid= 链接，只保留章节链接（含书名号）"""
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
        # 只保留有书名号的章节链接
        if "【" not in text or "】" not in text:
            continue
        if not href.startswith("http"):
            href = "https://www.cool18.com" + href if href.startswith("/") else "https://www.cool18.com/bbs4/" + href
        links.append((text, href))
    return links


def is_index_post(post_links, threshold=5):
    """判断帖子是否为索引帖"""
    seen_tids = set()
    for _, url in post_links:
        tid_match = re.search(r"tid=(\d+)", url)
        if tid_match:
            seen_tids.add(tid_match.group(1))
    return len(seen_tids) >= threshold


def parse_search_results(soup, keywords):
    """解析搜索页面，过滤出禁忌书屋版块的帖子"""
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
    """从标题中提取章节编号范围，返回 (起始章, 结束章)，无编号返回 (None, None)"""
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


def smart_dedup_posts(posts, index_tid=None):
    """
    基于章节覆盖范围去重：
    1. 按 tid 去重（同一帖子只保留一个）
    2. 按章节覆盖范围去重：如果新帖子的起始章节已被已有帖子覆盖则跳过
    3. 相同起始章节保留较长范围的那个
    4. 排除索引帖本身
    5. 有编号和无编号分开处理
    """
    # Step 1: 按 tid 去重
    seen_tids = set()
    unique_by_tid = []
    for title, url in posts:
        tid_match = re.search(r"tid=(\d+)", url)
        tid = tid_match.group(1) if tid_match else None

        # 排除索引帖本身
        if tid == index_tid:
            continue

        if tid and tid in seen_tids:
            continue
        if tid:
            seen_tids.add(tid)
        unique_by_tid.append((title, url))

    # Step 2: 分离有编号和无编号
    numbered = []
    unnumbered = []
    for title, url in unique_by_tid:
        start_ch, end_ch = extract_sort_key(title)
        if start_ch is not None:
            numbered.append((title, url, start_ch, end_ch))
        else:
            unnumbered.append((title, url))

    # Step 3: 有编号按起始章节排序，然后按覆盖范围去重
    numbered.sort(key=lambda x: (x[2], -x[3]))  # 按 start_ch 升序，end_ch 降序（长范围优先）
    deduped = []
    covered_until = -1  # 已覆盖到的最大章节号

    for title, url, start_ch, end_ch in numbered:
        if start_ch <= covered_until:
            # 起始章节已被覆盖，跳过
            continue
        # 保留这个帖子，更新覆盖范围
        deduped.append((title, url))
        covered_until = end_ch

    # Step 4: 无编号章节按 tid 去重后保留
    deduped_unnumbered = []
    seen_unnumbered_tids = set()
    for title, url in unnumbered:
        tid_match = re.search(r"tid=(\d+)", url)
        tid = tid_match.group(1) if tid_match else None
        if tid and tid in seen_unnumbered_tids:
            continue
        if tid:
            seen_unnumbered_tids.add(tid)
        deduped_unnumbered.append((title, url))

    return deduped, deduped_unnumbered


def smart_sort_posts(posts, index_links=None, index_tid=None, novel_name=""):
    """
    智能排序帖子：
    1. 先按 tid 和章节覆盖范围去重
    2. 有编号章节按章节号从小到大排序
    3. 索引帖中的无编号章节（如母亲节特别篇）按前后章节号插入正确位置
    4. 搜索结果单独出现的无编号章节放最后

    索引帖链接是倒序的（最新在前）：58-63, 53-57, 51-52, 50+间章, 44-49, ...
    无编号章节应插入在它后面最近的编号章节之后（即章节号更小的那个之后）
    例：母亲节特别篇(pos7) 在 38-39(pos6) 和 34-37(pos8) 之间
       → 插入在 34-37(end=37) 之后 → 最终在 34-37 和 38-39 之间
    """
    # ---- Step 1: 构建索引帖的顺序映射 ----
    numbered_in_index = []  # [(position, start_ch, end_ch, tid)]
    unnumbered_in_index = []  # [(position, tid, text, url)]
    index_tids = set()

    if index_links:
        for pos, (text, url) in enumerate(index_links):
            tid_match = re.search(r"tid=(\d+)", url)
            if not tid_match:
                continue
            tid = tid_match.group(1)
            index_tids.add(tid)
            start_ch, end_ch = extract_sort_key(text)
            if start_ch is not None:
                numbered_in_index.append((pos, start_ch, end_ch, tid))
            else:
                unnumbered_in_index.append((pos, tid, text, url))

    # 为索引帖中的无编号章节计算插入位置
    # 索引帖是倒序的：position 小的章节号大，position 大的章节号小
    # 无编号章节应插入在 "比它小的最近编号章节的 end" 之后
    special_insert = {}  # tid -> insert_after_chapter
    for pos, tid, text, url in unnumbered_in_index:
        # 索引帖倒序：pos 小=章节号大，pos 大=章节号小
        # 无编号章节应插入在"比它小的编号章节中，章节号最大的那个"之后
        # 例：母亲节(pos7) 在 38-39(pos6) 和 34-37(pos8) 之间
        #     → 插入在 34-37(end=37) 之后
        nearest_below_end = None  # position > pos 中 end 最大的（离它最近的下方编号章节）
        nearest_above_end = None  # position < pos 中 end 最小的（离它最近的上方编号章节）
        for p, s, e, t in numbered_in_index:
            if p < pos:
                if nearest_above_end is None or e < nearest_above_end:
                    nearest_above_end = e
            if p > pos:
                if nearest_below_end is None or e > nearest_below_end:
                    nearest_below_end = e
        # 插入到 nearest_below_end 之后
        if nearest_below_end is not None:
            special_insert[tid] = nearest_below_end
        elif nearest_above_end is not None:
            special_insert[tid] = nearest_above_end
        else:
            special_insert[tid] = 0

    # ---- Step 2: 去重 ----
    numbered_deduped, unnumbered_deduped = smart_dedup_posts(posts, index_tid)

    # ---- Step 3: 分类无编号章节 ----
    special_posts = []  # 索引帖中的无编号章节 [(title, url, insert_after_ch)]
    extra_special = []  # 搜索结果中的额外无编号

    for title, url in unnumbered_deduped:
        tid_match = re.search(r"tid=(\d+)", url)
        tid = tid_match.group(1) if tid_match else None
        if tid and tid in special_insert:
            insert_after = special_insert[tid]
            existing = [(t, u) for t, u, _ in special_posts]
            if (title, url) not in existing:
                special_posts.append((title, url, insert_after))
        else:
            # 检查是否为小说相关章节
            if "【" in title and "】" in title:
                core = re.search(r"（(.+?)）", novel_name)
                if core and core.group(1) in title:
                    extra_special.append((title, url))
                elif novel_name in title:
                    extra_special.append((title, url))

    # ---- Step 4: 合并排序 ----
    result = []

    # 插入特殊章节和编号章节
    for title, url in numbered_deduped:
        start_ch, end_ch = extract_sort_key(title)
        result.append((title, url))
        # 在此编号章节之后插入应该紧跟它的特殊章节
        for s_title, s_url, insert_after in special_posts:
            if insert_after == end_ch and (s_title, s_url) not in result:
                result.append((s_title, s_url))

    # 剩余特殊章节放最后
    for s_title, s_url, _ in special_posts:
        if (s_title, s_url) not in result:
            result.append((s_title, s_url))

    # 额外无编号放最后
    for e_title, e_url in extra_special:
        if (e_title, e_url) not in result:
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

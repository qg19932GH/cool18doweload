import os
import sys
import re
import time
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTextEdit, QListWidget, QListWidgetItem,
    QProgressBar, QMessageBox, QMenu, QCheckBox,
)
from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtGui import QFont, QColor

from utils.parser import get_page, parse_novel_name
from utils.downloader import search_and_find_posts, fetch_and_save_all


class CrawlerThread(QThread):
    """后台爬取线程"""
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, int)
    finished_signal = pyqtSignal(list, str, int)
    novel_info_signal = pyqtSignal(str, int, str)

    def __init__(self, mode, **kwargs):
        super().__init__()
        self.mode = mode
        self.proxy_port = kwargs.get("proxy_port")
        self.kwargs = kwargs
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            if self.mode == "search":
                self._do_search()
            elif self.mode == "download":
                self._do_download()
        except Exception as e:
            self.log_signal.emit(f"[错误] {str(e)}")

    def _do_search(self):
        url = self.kwargs.get("url", "")
        self.log_signal.emit("[信息] 正在获取帖子页面...")
        try:
            soup = get_page(url, proxy_port=self.proxy_port)
        except Exception as e:
            self.log_signal.emit(f"[错误] 获取页面失败: {e}")
            return

        self.log_signal.emit("[信息] 正在解析小说名称...")
        novel_name, full_title, keywords = parse_novel_name(soup)
        if not novel_name:
            self.log_signal.emit("[错误] 无法解析小说名称，请检查链接是否为有效的帖子链接")
            return

        self.log_signal.emit(f"[信息] 小说名称: {novel_name}")
        self.log_signal.emit(f"[信息] 搜索关键词: {' / '.join(keywords)}")
        self.novel_info_signal.emit(novel_name, 0, "")

        self.log_signal.emit(f"[信息] 正在搜索小说所有帖子...")
        try:
            results, source = search_and_find_posts(novel_name, keywords, log_callback=self.log_signal.emit, delay=2, proxy_port=self.proxy_port)
        except Exception as e:
            self.log_signal.emit(f"[错误] 搜索失败: {e}")
            return

        self.log_signal.emit(f"[成功] 共找到 {len(results)} 个帖子")
        self.log_signal.emit(f"[信息] 来源: {source}")
        self.novel_info_signal.emit(novel_name, len(results), source)
        self.finished_signal.emit(results, source, 0)

    def _do_download(self):
        posts = self.kwargs.get("posts", [])
        novel_name = self.kwargs.get("novel_name", "小说")
        if not posts:
            self.log_signal.emit("[错误] 没有可下载的帖子")
            return

        total = len(posts)
        self.log_signal.emit(f"[信息] 开始下载 {total} 个帖子...")
        results = []

        for i, (title, url) in enumerate(posts, 1):
            if self._stop:
                self.log_signal.emit("[信息] 用户取消下载")
                break

            self.log_signal.emit(f"[信息] ({i}/{total}) 正在下载: {title[:50]}...")
            try:
                soup = get_page(url, proxy_port=self.proxy_port)
                from utils.parser import parse_post_content
                content = parse_post_content(soup)
                success = bool(content)
                results.append((title, url, content, success))
                if success:
                    self.log_signal.emit(f"[成功] 已获取 {title[:50]} ({len(content)} 字符)")
                else:
                    self.log_signal.emit(f"[警告] 未获取到 {title[:50]} 的内容")
            except Exception as e:
                self.log_signal.emit(f"[错误] 下载 {title[:50]} 失败: {str(e)}")
                results.append((title, url, "", False))

            self.progress_signal.emit(i, total)
            if i < total:
                time.sleep(2)

        success_count = sum(1 for r in results if r[3])
        self.log_signal.emit(f"[成功] 下载完成! 成功 {success_count}/{len(results)}")

        # 自动保存
        self.log_signal.emit("[信息] 正在保存到 exe 同级目录...")
        from utils.downloader import save_to_txt, get_exe_dir
        exe_dir = get_exe_dir()
        safe_name = re.sub(r'[\\/:*?"<>|\r\n]+', '', novel_name) or "小说"
        filepath = os.path.join(exe_dir, f"{safe_name}.txt")
        save_to_txt(results, filepath, novel_name)
        file_size = os.path.getsize(filepath)
        self.log_signal.emit(f"[成功] 已保存到: {filepath}")
        self.log_signal.emit(f"[信息] 文件大小: {file_size / 1024:.1f} KB")

        self.finished_signal.emit(results, filepath, file_size)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.posts = []
        self.crawled_results = []
        self.novel_name = ""
        self.source_info = ""
        self.crawler_thread = None

        self.setWindowTitle("酷18小说下载器")
        self.setMinimumSize(850, 750)
        self._build_ui()
        self._load_styles()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 20, 20, 20)

        title = QLabel("酷18小说下载器")
        title.setFont(QFont("Microsoft YaHei", 20, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        input_layout = QHBoxLayout()
        label = QLabel("帖子链接:")
        label.setFont(QFont("Microsoft YaHei", 11))
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("在此粘贴帖子链接，例如 https://www.cool18.com/bbs4/index.php?...")
        self.url_input.setFont(QFont("Consolas", 10))
        self.url_input.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.url_input.customContextMenuRequested.connect(self._url_input_context_menu)
        input_layout.addWidget(label)
        input_layout.addWidget(self.url_input)
        layout.addLayout(input_layout)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        self.search_btn = QPushButton("搜索")
        self.download_btn = QPushButton("下载")
        self.stop_btn = QPushButton("停止")
        for btn in [self.search_btn, self.download_btn, self.stop_btn]:
            btn.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
            btn.setFixedSize(120, 40)
            btn_layout.addWidget(btn)
        self.download_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)

        # 代理开关
        self.proxy_check = QCheckBox("使用代理")
        self.proxy_check.setFont(QFont("Microsoft YaHei", 10))
        btn_layout.addWidget(self.proxy_check)
        self.proxy_port_input = QLineEdit("10808")
        self.proxy_port_input.setPlaceholderText("代理端口")
        self.proxy_port_input.setFont(QFont("Consolas", 10))
        self.proxy_port_input.setFixedSize(80, 32)
        btn_layout.addWidget(self.proxy_port_input)
        proxy_label = QLabel("端口")
        proxy_label.setFont(QFont("Microsoft YaHei", 10))
        btn_layout.addWidget(proxy_label)

        layout.addLayout(btn_layout)

        info_layout = QVBoxLayout()
        self.info_label = QLabel("小说名称: 未搜索")
        self.info_label.setFont(QFont("Microsoft YaHei", 11))
        info_layout.addWidget(self.info_label)
        self.source_label = QLabel("")
        self.source_label.setFont(QFont("Microsoft YaHei", 10))
        self.source_label.setStyleSheet("color: #89b4fa;")
        info_layout.addWidget(self.source_label)
        layout.addLayout(info_layout)

        list_layout = QVBoxLayout()
        list_label = QLabel("帖子列表:")
        list_label.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        list_layout.addWidget(list_label)
        self.post_list = QListWidget()
        self.post_list.setFont(QFont("Microsoft YaHei", 10))
        list_layout.addWidget(self.post_list)
        layout.addLayout(list_layout, stretch=2)

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        log_layout = QVBoxLayout()
        log_label = QLabel("运行日志:")
        log_label.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        log_layout.addWidget(log_label)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        log_layout.addWidget(self.log_text, stretch=1)
        layout.addLayout(log_layout, stretch=1)

        self.search_btn.clicked.connect(self.on_search)
        self.download_btn.clicked.connect(self.on_download)
        self.stop_btn.clicked.connect(self.on_stop)

    def _url_input_context_menu(self, pos):
        menu = QMenu(self)
        action_undo = menu.addAction("撤销")
        action_undo.triggered.connect(self.url_input.undo)
        menu.addSeparator()
        action_cut = menu.addAction("剪切")
        action_cut.triggered.connect(self.url_input.cut)
        action_copy = menu.addAction("复制")
        action_copy.triggered.connect(self.url_input.copy)
        action_paste = menu.addAction("粘贴")
        action_paste.triggered.connect(self.url_input.paste)
        menu.addSeparator()
        action_select_all = menu.addAction("全选")
        action_select_all.triggered.connect(self.url_input.selectAll)
        menu.exec(self.url_input.mapToGlobal(pos))

    def _load_styles(self):
        try:
            style_path = os.path.join(os.path.dirname(__file__), "ui", "styles.qss")
            if os.path.exists(style_path):
                with open(style_path, "r", encoding="utf-8") as f:
                    self.setStyleSheet(f.read())
        except Exception:
            pass

    def _append_log(self, msg):
        self.log_text.append(msg)
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum()
        )

    def on_search(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "提示", "请输入帖子链接")
            return
        if "cool18.com" not in url:
            QMessageBox.warning(self, "提示", "链接格式不正确，请输入 cool18.com 的帖子链接")
            return

        self.log_text.clear()
        self._append_log(f"[信息] 开始搜索: {url[:80]}...")
        if proxy_port:
            self._append_log(f"[信息] 已启用代理 127.0.0.1:{proxy_port}")
        self.search_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.post_list.clear()

        proxy_port = int(self.proxy_port_input.text()) if self.proxy_check.isChecked() else None
        self.crawler_thread = CrawlerThread(mode="search", url=url, proxy_port=proxy_port)
        self.crawler_thread.log_signal.connect(self._append_log)
        self.crawler_thread.novel_info_signal.connect(self._on_novel_info)
        self.crawler_thread.finished_signal.connect(self._on_search_finished)
        self.crawler_thread.start()

    def _on_novel_info(self, novel_name, count, source):
        self.novel_name = novel_name
        if count > 0:
            self.info_label.setText(f"小说名称: {novel_name} | 帖子数量: {count}")
            if source:
                self.source_label.setText(f"章节来源: {source[:60]}")

    def _on_search_finished(self, results, source, _):
        self.posts = results
        self.source_info = source
        self.search_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        if results:
            self.post_list.clear()
            for i, (title, url) in enumerate(results, 1):
                item = QListWidgetItem(f"[{i:02d}] {title[:80]}")
                item.setData(Qt.ItemDataRole.UserRole, (title, url))
                self.post_list.addItem(item)
            self.download_btn.setEnabled(True)

    def on_download(self):
        if not self.posts:
            QMessageBox.warning(self, "提示", "请先搜索小说")
            return

        self.post_list.clear()
        self.log_text.clear()
        self._append_log("[信息] 开始下载全部帖子...")
        if proxy_port:
            self._append_log(f"[信息] 已启用代理 127.0.0.1:{proxy_port}")
        self.download_btn.setEnabled(False)
        self.search_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.crawled_results = []

        proxy_port = int(self.proxy_port_input.text()) if self.proxy_check.isChecked() else None
        self.crawler_thread = CrawlerThread(mode="download", posts=self.posts, novel_name=self.novel_name, proxy_port=proxy_port)
        self.crawler_thread.log_signal.connect(self._append_log)
        self.crawler_thread.progress_signal.connect(self._on_progress)
        self.crawler_thread.finished_signal.connect(self._on_download_finished)
        self.crawler_thread.start()

    def _on_progress(self, current, total):
        pct = int(current / total * 100)
        self.progress_bar.setValue(pct)
        self.progress_bar.setFormat(f"{current}/{total} ({pct}%)")

        if self.post_list.count() == 0:
            for idx in range(current):
                if idx < len(self.posts):
                    title = self.posts[idx][0]
                    item = QListWidgetItem(f"[{idx+1:02d}] {title[:70]} [已下载]")
                    self.post_list.addItem(item)

    def _on_download_finished(self, results, filepath, file_size):
        self.crawled_results = results
        self.download_btn.setEnabled(False)
        self.search_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        success_count = sum(1 for r in results if r[3])
        fail_count = len(results) - success_count

        self.post_list.clear()
        for i, (title, url, content, success) in enumerate(results, 1):
            status = "[已下载]" if success else "[失败]"
            item = QListWidgetItem(f"[{i:02d}] {title[:70]} {status}")
            color = QColor("#4caf50") if success else QColor("#f44336")
            item.setForeground(color)
            self.post_list.addItem(item)

        self._append_log(f"[完成] 下载完成! 成功: {success_count}, 失败: {fail_count}")
        if success_count > 0:
            self.info_label.setText(
                f"小说名称: {self.novel_name} | 帖子数量: {len(results)} | 成功: {success_count}"
            )
            self._append_log(f"[信息] 文件已保存: {filepath}")

    def on_stop(self):
        if self.crawler_thread and self.crawler_thread.isRunning():
            self.crawler_thread.stop()
            self._append_log("[信息] 正在停止...")
            self.stop_btn.setEnabled(False)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
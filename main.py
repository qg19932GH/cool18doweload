import os
import sys
import time
import requests
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTextEdit, QListWidget, QListWidgetItem,
    QProgressBar, QFileDialog, QMessageBox,
)
from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtGui import QFont, QColor

from utils.parser import get_page, parse_novel_name
from utils.downloader import search_and_find_posts, fetch_posts, save_to_txt


class CrawlerThread(QThread):
    """后台爬取线程"""
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, int)
    finished_signal = pyqtSignal(list, str)
    novel_info_signal = pyqtSignal(str, int, str)

    def __init__(self, mode, **kwargs):
        super().__init__()
        self.mode = mode
        self.kwargs = kwargs
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            if self.mode == "search":
                self._do_search()
            elif self.mode == "crawl":
                self._do_crawl()
        except Exception as e:
            self.log_signal.emit(f"[错误] {str(e)}")

    def _do_search(self):
        url = self.kwargs.get("url", "")
        self.log_signal.emit("[信息] 正在获取帖子页面...")
        try:
            soup = get_page(url)
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
            results, source = search_and_find_posts(novel_name, keywords, log_callback=self.log_signal.emit, delay=2)
        except Exception as e:
            self.log_signal.emit(f"[错误] 搜索失败: {e}")
            return

        self.log_signal.emit(f"[成功] 共找到 {len(results)} 个帖子")
        self.log_signal.emit(f"[信息] 来源: {source}")
        self.novel_info_signal.emit(novel_name, len(results), source)
        self.finished_signal.emit(results, source)

    def _do_crawl(self):
        posts = self.kwargs.get("posts", [])
        if not posts:
            self.log_signal.emit("[错误] 没有可爬取的帖子")
            return

        total = len(posts)
        self.log_signal.emit(f"[信息] 开始爬取 {total} 个帖子...")
        results = []

        for i, (title, url) in enumerate(posts, 1):
            if self._stop:
                self.log_signal.emit("[信息] 用户取消爬取")
                break

            self.log_signal.emit(f"[信息] ({i}/{total}) 正在爬取: {title[:50]}...")
            try:
                soup = get_page(url)
                from utils.parser import parse_post_content
                content = parse_post_content(soup)
                success = bool(content)
                results.append((title, url, content, success))
                if success:
                    self.log_signal.emit(f"[成功] 已获取 {title[:50]} ({len(content)} 字符)")
                else:
                    self.log_signal.emit(f"[警告] 未获取到 {title[:50]} 的内容")
            except Exception as e:
                self.log_signal.emit(f"[错误] 爬取 {title[:50]} 失败: {str(e)}")
                results.append((title, url, "", False))

            self.progress_signal.emit(i, total)
            if i < total:
                time.sleep(2)

        success_count = sum(1 for r in results if r[3])
        self.log_signal.emit(f"[成功] 爬取完成! 成功 {success_count}/{len(results)}")
        self.finished_signal.emit(results, "")


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
        self.url_input.setPlaceholderText("粘贴一个该小说的帖子链接，例如 https://www.cool18.com/bbs4/index.php?...")
        self.url_input.setFont(QFont("Consolas", 10))
        input_layout.addWidget(label)
        input_layout.addWidget(self.url_input)
        layout.addLayout(input_layout)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        self.search_btn = QPushButton("搜索")
        self.crawl_btn = QPushButton("爬取")
        self.save_btn = QPushButton("保存")
        self.stop_btn = QPushButton("停止")
        for btn in [self.search_btn, self.crawl_btn, self.save_btn, self.stop_btn]:
            btn.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
            btn.setFixedSize(100, 40)
            btn_layout.addWidget(btn)
        self.crawl_btn.setEnabled(False)
        self.save_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
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
        self.crawl_btn.clicked.connect(self.on_crawl)
        self.save_btn.clicked.connect(self.on_save)
        self.stop_btn.clicked.connect(self.on_stop)

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
        self.search_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.post_list.clear()

        self.crawler_thread = CrawlerThread(mode="search", url=url)
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

    def _on_search_finished(self, results, source):
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
            self.crawl_btn.setEnabled(True)

    def on_crawl(self):
        if not self.posts:
            QMessageBox.warning(self, "提示", "请先搜索小说")
            return

        self.post_list.clear()
        self.log_text.clear()
        self._append_log("[信息] 开始批量爬取...")
        self.crawl_btn.setEnabled(False)
        self.search_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.crawled_results = []

        self.crawler_thread = CrawlerThread(mode="crawl", posts=self.posts)
        self.crawler_thread.log_signal.connect(self._append_log)
        self.crawler_thread.progress_signal.connect(self._on_progress)
        self.crawler_thread.finished_signal.connect(self._on_crawl_finished)
        self.crawler_thread.start()

    def _on_progress(self, current, total):
        pct = int(current / total * 100)
        self.progress_bar.setValue(pct)
        self.progress_bar.setFormat(f"{current}/{total} ({pct}%)")

        if self.post_list.count() == 0:
            for idx in range(current):
                if idx < len(self.posts):
                    title = self.posts[idx][0]
                    item = QListWidgetItem(f"[{idx+1:02d}] {title[:70]} [已爬取]")
                    self.post_list.addItem(item)

    def _on_crawl_finished(self, results, _):
        self.crawled_results = results
        self.crawl_btn.setEnabled(False)
        self.search_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        success_count = sum(1 for r in results if r[3])
        fail_count = len(results) - success_count

        self.post_list.clear()
        for i, (title, url, content, success) in enumerate(results, 1):
            status = "[已爬取]" if success else "[失败]"
            item = QListWidgetItem(f"[{i:02d}] {title[:70]} {status}")
            color = QColor("#4caf50") if success else QColor("#f44336")
            item.setForeground(color)
            self.post_list.addItem(item)

        self._append_log(f"[完成] 爬取完成! 成功: {success_count}, 失败: {fail_count}")
        if success_count > 0:
            self.save_btn.setEnabled(True)
            self.info_label.setText(
                f"小说名称: {self.novel_name} | 帖子数量: {len(results)} | 成功: {success_count}"
            )

    def on_save(self):
        if not self.crawled_results:
            QMessageBox.warning(self, "提示", "没有可保存的内容")
            return

        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "保存小说",
            f"{self.novel_name}.txt",
            "文本文件 (*.txt)",
        )
        if not filepath:
            return

        try:
            save_to_txt(self.crawled_results, filepath, self.novel_name)
            size = os.path.getsize(filepath)
            self._append_log(f"[成功] 已保存到: {filepath}")
            self._append_log(f"[信息] 文件大小: {size / 1024:.1f} KB")
            QMessageBox.information(self, "成功", f"小说已保存到:\n{filepath}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败: {e}")

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
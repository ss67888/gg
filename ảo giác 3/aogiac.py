from __future__ import annotations

import json
import wikipedia
import difflib
import re
import argparse
from pathlib import Path
from typing import Dict, Optional, TYPE_CHECKING
from threading import Thread

# runtime optional import (không bắt buộc lúc import module)
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    WATCHDOG_AVAILABLE = True
except Exception:
    WATCHDOG_AVAILABLE = False
    class FileSystemEventHandler:
        pass

# chỉ cho static type checkers (Pylance / mypy)
if TYPE_CHECKING:
    from watchdog.observers import Observer  # type: ignore

# Sử dụng thư viện wikidata.client để truy vấn facts
from wikidata.client import Client

# Không còn DEFAULT_FAQ; chương trình chỉ dùng faq.json nếu tồn tại.
FAQ_PATH = Path("faq.json")

# Cache để tránh đọc file liên tục; watcher sẽ cập nhật ngay khi file thay đổi.
_faq_cache = {
    "mtime": 0.0,
    "data": {}
}

def _load_faq_from_disk(path: Path = FAQ_PATH) -> Dict[str, str]:
    """
    Đọc faq.json từ đĩa. Nếu file hợp lệ và là dict trả về dict đó,
    ngược lại trả về dict rỗng.
    """
    try:
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return {}

def _load_faq_if_updated(path: Path = FAQ_PATH) -> Dict[str, str]:
    """
    Kiểm tra mtime và load lại nếu file thay đổi.
    Trả về dict FAQ (có thể rỗng nếu không có file hoặc file không hợp lệ).
    """
    global _faq_cache
    try:
        if path.exists():
            mtime = path.stat().st_mtime
            if mtime != _faq_cache["mtime"]:
                _faq_cache["data"] = _load_faq_from_disk(path)
                _faq_cache["mtime"] = mtime
        else:
            _faq_cache["data"] = {}
            _faq_cache["mtime"] = 0.0
    except Exception:
        pass
    return _faq_cache["data"]

# Watcher: cập nhật cache ngay khi file thay đổi
class FAQFileHandler(FileSystemEventHandler):
    def __init__(self, path: Path):
        super().__init__()
        self._path = path

    def on_modified(self, event):
        try:
            if Path(event.src_path).resolve() == self._path.resolve():
                _faq_cache["data"] = _load_faq_from_disk(self._path)
                _faq_cache["mtime"] = self._path.stat().st_mtime if self._path.exists() else 0.0
                print("[faq watcher] faq.json được cập nhật.")
        except Exception:
            pass

def start_faq_watcher(path: Path = FAQ_PATH) -> Optional["Observer"]:
    """
    Khởi chạy watchdog observer trong background.
    Trả về Observer (hoặc None nếu watchdog không có).
    """
    if not WATCHDOG_AVAILABLE:
        print("watchdog không được tìm thấy.")
        return None
    observer = Observer()
    # ...
    return observer
    # runtime: Observer được import trong try/except ở trên (nếu tồn tại)
    observer = Observer()
    handler = FAQFileHandler(path)
    observer.schedule(handler, path=path.parent.as_posix() or ".", recursive=False)
    observer.start()
    print("[faq watcher] Đang lắng nghe thay đổi ở", str(path))
    return observer

# --- Các hàm tra cứu (Wikidata / Wikipedia) ---
def tra_cuu_wikidata(cau_hoi: str) -> str:
    client = Client()
    try:
        if "thủ đô" in cau_hoi.lower():
            match = re.search(r"Thủ đô của (.+?) là gì", cau_hoi, re.IGNORECASE)
            if match:
                country = match.group(1).strip()
                entities = client.search(country, limit=1)
                for entity in entities:
                    try:
                        capital = entity['P36']
                        if hasattr(capital, 'label'):
                            return f"Thủ đô của {country} là {capital.label.text}."
                    except Exception:
                        continue
        if "tổng thống" in cau_hoi.lower() and "hoa kỳ" in cau_hoi.lower():
            usa = client.get('Q30', load=True)
            president = usa['P6']
            if hasattr(president, 'label'):
                return f"Tổng thống Hoa Kỳ hiện tại là {president.label.text}."
        if "nước sôi" in cau_hoi.lower():
            return "100°C"
    except Exception:
        pass
    return ""

def tra_cuu_wikipedia(cau_hoi: str, lang: str = "vi") -> str:
    wikipedia.set_lang(lang)
    try:
        search_results = wikipedia.search(cau_hoi)
        if not search_results:
            return ""
        best_title = max(
            search_results,
            key=lambda title: difflib.SequenceMatcher(None, cau_hoi.lower(), title.lower()).ratio()
        )
        if difflib.SequenceMatcher(None, cau_hoi.lower(), best_title.lower()).ratio() < 0.5:
            return ""
        try:
            summary = wikipedia.summary(best_title, sentences=2, auto_suggest=False)
            return summary
        except Exception:
            return ""
    except Exception:
        return ""

def tra_cuu_wikipedia_en(cau_hoi: str) -> str:
    return tra_cuu_wikipedia(cau_hoi, lang="en")

def tra_cuu_kien_thuc(cau_hoi: str) -> str:
    """
    Trật tự tra cứu:
      1) Wikidata (ưu tiên)
      2) FAQ từ faq.json (nếu tồn tại)
      3) Wikipedia tiếng Việt
      4) Wikipedia tiếng Anh
    Lưu ý: Nếu faq.json không tồn tại hoặc không chứa câu hỏi, sẽ bỏ qua bước 2.
    """
    kq_wikidata = tra_cuu_wikidata(cau_hoi)
    if kq_wikidata:
        return kq_wikidata

    faq = _load_faq_if_updated()
    if cau_hoi in faq:
        return faq[cau_hoi]

    ket_qua = tra_cuu_wikipedia(cau_hoi, lang="vi")
    if ket_qua:
        return ket_qua

    ket_qua_en = tra_cuu_wikipedia_en(cau_hoi)
    if ket_qua_en:
        return ket_qua_en

    return "Không có dữ liệu tham chiếu phù hợp."

def do_ao_giac(cau_tra_loi_llm: str, cau_tra_loi_tham_chieu: str) -> float:
    def normalize(text: str) -> str:
        return re.sub(r'\W+', '', text.lower())

    ans = cau_tra_loi_llm.strip()
    ref = cau_tra_loi_tham_chieu.strip()

    if len(ans.split()) <= 2:
        if normalize(ans) in normalize(ref):
            return 1.0
        ratio = difflib.SequenceMatcher(None, ans.lower(), ref.lower()).ratio()
        if ratio > 0.6:
            return ratio
        return 0.0

    return difflib.SequenceMatcher(None, ans.lower(), ref.lower()).ratio()

def _print_result(cau_hoi: str, llm_ans: str, tham_chieu: str, diem: float) -> None:
    print(f"Câu hỏi: {cau_hoi}")
    print(f"LLM trả lời: {llm_ans}")
    print(f"Tham chiếu từ nguồn: {tham_chieu}")
    print(f"Điểm giống nhau: {diem:.2f}")
    if diem < 0.7:
        print("Có thể có ảo giác!\n")
    else:
        print("Câu trả lời đúng với tham chiếu.\n")

def main():
    parser = argparse.ArgumentParser(description="Kiểm tra ảo giác: so sánh trả lời LLM với nguồn tham chiếu.")
    parser.add_argument("-q", "--question", help="Câu hỏi cần tra cứu (bao quanh bằng dấu ngoặc nếu có khoảng trắng).")
    parser.add_argument("-a", "--answer", help="Câu trả lời từ LLM để so sánh.")
    parser.add_argument("-i", "--interactive", action="store_true", help="Chạy chế độ tương tác (nhập câu hỏi và trả lời).")
    parser.add_argument("--watch", action="store_true", help="Chạy watcher để tự động reload faq.json khi thay đổi.")
    args = parser.parse_args()

    observer = None
    if args.watch:
        observer = start_faq_watcher(FAQ_PATH)

    try:
        if args.interactive:
            print("Chế độ tương tác. Gõ 'exit' hoặc 'quit' để thoát.")
            while True:
                q = input("Câu hỏi: ").strip()
                if q.lower() in ("exit", "quit"):
                    break
                ans = input("LLM trả lời: ").strip()
                tham_chieu = tra_cuu_kien_thuc(q)
                diem = do_ao_giac(ans, tham_chieu)
                _print_result(q, ans, tham_chieu, diem)
            return

        if args.question and args.answer is not None:
            tham_chieu = tra_cuu_kien_thuc(args.question)
            diem = do_ao_giac(args.answer, tham_chieu)
            _print_result(args.question, args.answer, tham_chieu, diem)
            return

        print("Không có câu hỏi mặc định trong file nữa.")
        print("Sử dụng:")
        print("  python aogiac.py -q \"Câu hỏi\" -a \"LLM trả lời\"")
        print("  python aogiac.py --interactive")
        print("  Thêm --watch để lắng nghe thay đổi faq.json và reload tự động.")
    finally:
        if observer is not None:
            observer.stop()
            observer.join()

if __name__ == "__main__":
    main()
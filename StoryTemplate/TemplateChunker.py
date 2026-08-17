from __future__ import annotations

import re
from dataclasses import dataclass

"""长文切块：识别中文卷/章/节/回标记，产出带 order_index 的 Chunk。

分层：卷/部/篇/集=大层（order 高位）；章/节/回/折=小层。以最细可用层切块；
完全无标记回退 ~chunk_size 字滑窗。楔子/序排最前，尾声/番外排最后。
只在行首独立匹配 + 标题长度上限，防正文误命中。
"""

_BIG = "卷部篇集"
_SMALL = "章节回折"
_NUM = "[0-9]+|[一二三四五六七八九十百千零两]+"
# 两种词序：数字在前（第37章 / 第一卷）或数字在后（卷二）。用具名组统一提取号与标记词。
_LINE = re.compile(
    rf"^\s*(?:第?\s*(?P<num1>{_NUM})\s*(?P<word1>[{_BIG}{_SMALL}])"
    rf"|(?P<word2>[{_BIG}{_SMALL}])\s*(?P<num2>{_NUM}))"
    rf"\s*([:：、.\-—]?\s*(?P<title>.*))?$"
)
_PROLOGUE = re.compile(r"^\s*(楔子|序|序章|序言)\s*$")
_EPILOGUE = re.compile(r"^\s*(尾声|番外|后记|终章)\s*$")
_TITLE_MAX = 30

_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000}


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    order_index: int
    text: str
    title: str


def _parse_number(raw: str) -> int | None:
    raw = raw.strip()
    if raw.isdigit():
        return int(raw)
    total, section, number = 0, 0, 0
    for ch in raw:
        if ch in _CN_DIGITS:
            number = _CN_DIGITS[ch]
        elif ch in _CN_UNITS:
            unit = _CN_UNITS[ch]
            section += (number or 1) * unit
            number = 0
        else:
            return None
    result = section + number
    return result or None


@dataclass
class _Marker:
    is_big: bool
    number: int | None
    title: str
    line_index: int


class TemplateChunker:
    def __init__(self, chunk_size: int = 2000) -> None:
        self._chunk_size = max(1, int(chunk_size))

    def chunk(self, text: str) -> list[Chunk]:
        lines = text.splitlines()
        markers = self._scan_markers(lines)
        # 所有卷/章标记都作切点：大层号仍并入复合排序高位，保证跨卷章号能全局排序，
        # 同时避免大层标题下、子章之前的正文被吞进上一块（如「卷二\n内容二」独立成块）。
        cut_markers = list(markers)
        prologue, epilogue = self._scan_special(lines)
        if not cut_markers and not prologue and not epilogue:
            return self._sliding_window(text)
        return self._cut_by_markers(lines, cut_markers, markers, prologue, epilogue)

    def _scan_markers(self, lines: list[str]) -> list[_Marker]:
        out: list[_Marker] = []
        for i, line in enumerate(lines):
            m = _LINE.match(line)
            if not m:
                continue
            title = (m.group("title") or "").strip()
            if len(line.strip()) > _TITLE_MAX and title:
                continue  # 标题行过长视为正文
            marker_word = m.group("word1") or m.group("word2")
            raw_num = m.group("num1") or m.group("num2")
            out.append(_Marker(
                is_big=marker_word in _BIG,
                number=_parse_number(raw_num),
                title=title,
                line_index=i,
            ))
        return out

    def _scan_special(self, lines: list[str]) -> tuple[int | None, int | None]:
        prologue = epilogue = None
        for i, line in enumerate(lines):
            if prologue is None and _PROLOGUE.match(line):
                prologue = i
            if _EPILOGUE.match(line):
                epilogue = i
        return prologue, epilogue

    def _sliding_window(self, text: str) -> list[Chunk]:
        body = text.strip()
        chunks: list[Chunk] = []
        for idx, start in enumerate(range(0, len(body), self._chunk_size)):
            piece = body[start:start + self._chunk_size]
            chunks.append(Chunk(chunk_id=f"win_{idx}", order_index=idx, text=piece, title=""))
        return chunks or [Chunk(chunk_id="win_0", order_index=0, text=body, title="")]

    def _cut_by_markers(
        self, lines, cut_markers, all_markers, prologue, epilogue,
    ) -> list[Chunk]:
        # 复合排序键：(卷号, 章号)。卷号取该切点之前最近的大层号。
        big_before: list[int] = []
        cur_big = 0
        big_by_line = {m.line_index: (m.number or 0) for m in all_markers if m.is_big}
        for m in cut_markers:
            for ln in range(0, m.line_index + 1):
                if ln in big_by_line:
                    cur_big = big_by_line[ln]
            big_before.append(cur_big)

        # 用切点行号把正文切段。
        cut_lines = [m.line_index for m in cut_markers]
        entries: list[tuple[tuple[int, int, int], str, str]] = []
        for idx, m in enumerate(cut_markers):
            start = m.line_index + 1
            end = cut_lines[idx + 1] if idx + 1 < len(cut_lines) else len(lines)
            text = "\n".join(lines[start:end]).strip()
            sort_key = (0, big_before[idx], m.number if m.number is not None else idx)
            entries.append((sort_key, m.title, text))

        # 楔子/序 → 最前（key 首位 -1）；尾声/番外 → 最后（key 首位 1）。
        if prologue is not None:
            end = cut_lines[0] if cut_lines else len(lines)
            entries.append(((-1, 0, 0), "楔子", "\n".join(lines[prologue + 1:end]).strip()))
        if epilogue is not None:
            entries.append(((1, 0, 0), "尾声", "\n".join(lines[epilogue + 1:]).strip()))

        entries.sort(key=lambda e: e[0])
        chunks: list[Chunk] = []
        for order, (_, title, text) in enumerate(entries):
            chunks.append(Chunk(chunk_id=f"ch_{order}", order_index=order, text=text, title=title))
        return chunks

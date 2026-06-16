"""响应内容语义连贯性检测（启发式，纯字符统计，无外部依赖）。

设计目的：
    识别 BlazeAI Kimi 2.6 那种"格式合规但内容崩溃"的回复：
        "为了不让对方撒谎，拥有什么有这个品牌的的声誉计划，虽然目前对于医美这样类..."
    这类回复 JSON 解析能过，但实际内容毫无意义。

判定信号（五个启发式维度）：
    1. 2-gram 重复率：相邻字符对（"的的"、"要要"）占比 > 5%
    2. 语种切换密度：字符语种频繁切换 > 30%
    3. 罕见字符占比：非常用 Unicode 块占比 > 15%
    4. 短拉丁片段突兀插入：CJK 主导文本中插入 ≥3 个 ≤3 字符拉丁短词（B/UF/nn 类）
    5. 长度健全性：< 5 字符响应直接判 incoherent

任一信号触发：suspicious；任意两个：incoherent。
"""
from __future__ import annotations

import re
import unicodedata


GRAM2_REPEAT_THRESHOLD = 0.05       # 2-gram 重复占比 > 5%
LANG_SWITCH_THRESHOLD = 0.30        # 语种切换密度 > 30%
RARE_CHAR_THRESHOLD = 0.15          # 罕见字符占比 > 15%
LATIN_BURST_THRESHOLD = 4           # CJK 主导文本中短拉丁片段 ≥4 个
SHORT_RESPONSE_LENGTH = 5           # < 5 字符响应视为无效


def _char_class(ch: str) -> str:
    """字符归类：cjk / latin / digit / punct / space / symbol / other。"""
    if ch.isspace():
        return "space"
    code = ord(ch)
    if 0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF:
        return "cjk"
    if 0x3040 <= code <= 0x30FF or 0xAC00 <= code <= 0xD7AF:
        return "cjk"
    if ch.isalpha() and code < 0x0250:
        return "latin"
    if ch.isdigit():
        return "digit"
    category = unicodedata.category(ch)
    if category.startswith("P") or ch in "，。！？、；：（）《》【】":
        return "punct"
    if category.startswith("S"):
        return "symbol"
    return "other"


def _gram2_repeat_rate(text: str) -> float:
    """相邻 2-gram 重复率（连续两字符相同）。"""
    if len(text) < 2:
        return 0.0
    repeats = 0
    for i in range(len(text) - 1):
        if text[i] == text[i + 1] and not text[i].isspace():
            repeats += 1
    return repeats / len(text)


def _lang_switch_density(text: str) -> float:
    """语种切换密度：相邻字符语种不同的次数 / 计入字符数。"""
    if len(text) < 2:
        return 0.0
    switches = 0
    prev = None
    count = 0
    for ch in text:
        cls = _char_class(ch)
        if cls in ("space", "punct"):
            continue
        count += 1
        if prev is not None and cls != prev:
            switches += 1
        prev = cls
    if count < 2:
        return 0.0
    return switches / count


def _rare_char_ratio(text: str) -> float:
    """罕见字符（symbol/other）占比。"""
    if not text:
        return 0.0
    rare = sum(1 for ch in text if _char_class(ch) in ("other", "symbol"))
    return rare / len(text)


def _latin_burst_count(text: str) -> int:
    """统计 CJK 主导文本中突兀插入的 ≤3 字符拉丁短词。

    特征样本：Kimi 乱码里的 "B港"、"UF"、"nn"、"PS"、"á" 这类无意义短词。
    仅当 CJK 字符占比 > 50% 时启用，避免误判英文文本。
    """
    cjk_count = sum(1 for ch in text if _char_class(ch) == "cjk")
    if cjk_count < len(text) * 0.4:
        return 0
    # 匹配前后非拉丁字母的 1-3 字符拉丁/带音标短片段
    bursts = re.findall(r"(?<![A-Za-zÀ-ÿ])([A-Za-zÀ-ÿ]{1,3})(?![A-Za-zÀ-ÿ])", text)
    return len(bursts)


def assess_coherence(text: str) -> tuple[str, str]:
    """评估文本的语义连贯性。

    Args:
        text: 待评估文本

    Returns:
        (quality, reason)
        quality ∈ {"coherent", "suspicious", "incoherent"}
    """
    text = (text or "").strip()

    if len(text) < SHORT_RESPONSE_LENGTH:
        return "incoherent", f"响应过短（{len(text)} 字符）"

    gram2 = _gram2_repeat_rate(text)
    lang_switch = _lang_switch_density(text)
    rare = _rare_char_ratio(text)
    latin_burst = _latin_burst_count(text)

    triggers: list[str] = []
    if gram2 > GRAM2_REPEAT_THRESHOLD:
        triggers.append(f"重复率 {gram2:.0%}")
    if lang_switch > LANG_SWITCH_THRESHOLD:
        triggers.append(f"语种切换 {lang_switch:.0%}")
    if rare > RARE_CHAR_THRESHOLD:
        triggers.append(f"罕见字符 {rare:.0%}")
    if latin_burst >= LATIN_BURST_THRESHOLD:
        triggers.append(f"拉丁短词突兀插入 {latin_burst} 个")

    if len(triggers) >= 2:
        return "incoherent", "; ".join(triggers)
    if len(triggers) == 1:
        return "suspicious", triggers[0]
    return "coherent", "通过"

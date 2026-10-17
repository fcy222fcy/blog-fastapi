"""User-Agent 解析。

逐分支复刻 Go 版 pkg/ua/uaparser.go：同一批关键词、同一优先级顺序、
同样的「未知」兜底与两段式版本号（`11` → `11.0`）。评论列表里展示的
系统/浏览器标签依赖这套输出，顺序写错就会让 Edge 被识别成 Chrome。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

UNKNOWN = "未知"

_NT10_BUILD_RE = re.compile(r"Windows NT 10\.0;[^)]*Build\s+(\d+)")


@dataclass(frozen=True)
class UAInfo:
    os: str = UNKNOWN
    os_version: str = ""
    browser: str = UNKNOWN
    browser_version: str = ""

    @property
    def os_text(self) -> str:
        if not self.os or self.os == UNKNOWN:
            return ""
        return f"{self.os} {self.os_version}".strip()

    @property
    def browser_text(self) -> str:
        if not self.browser or self.browser == UNKNOWN:
            return ""
        return f"{self.browser} {self.browser_version}".strip()


EMPTY = UAInfo()


def _two_part(ver: str) -> str:
    """把版本号统一成「主版本.次版本」。"""
    ver = (ver or "").strip()
    if not ver:
        return ""
    if not ver[0].isdigit():
        return ver
    # "14 (Sonoma)" / "iOS 150.1" 这类带后缀的
    idx = min((i for i in (ver.find(" "), ver.find("(")) if i > 0), default=-1)
    if idx > 0:
        num_part, suffix = ver[:idx].strip(), ver[idx:]
        two = _two_part(num_part)
        return f"{two}{suffix}" if two else ver
    if "." not in ver:
        return f"{ver}.0" if ver.isdigit() else ver
    major, rest = ver.split(".", 1)
    if not major.isdigit():
        return ver
    minor = ""
    for ch in rest:
        if ch.isdigit():
            minor += ch
        else:
            break
    return f"{major}.{minor or '0'}"


def _extract(ua: str, prefix: str, first_num_only: bool = False) -> str:
    """取 prefix 之后、空格/分号/右括号之前的版本串。"""
    idx = ua.find(prefix)
    if idx < 0:
        return ""
    rest = ua[idx + len(prefix) :]
    end = len(rest)
    for i, ch in enumerate(rest):
        if ch in (" ", ";", ")"):
            end = i
            break
    version = rest[:end].strip()
    if not version:
        return ""
    if first_num_only:
        dot = version.find(".")
        if dot > 0:
            return version[:dot]
    return version


def _parse_os(ua: str) -> tuple[str, str]:
    if "Windows" in ua:
        mapping = [
            ("Windows NT 6.3", "8.1"),
            ("Windows NT 6.2", "8"),
            ("Windows NT 6.1", "7"),
            ("Windows NT 6.0", "Vista"),
            ("Windows NT 5.1", "XP"),
        ]
        if "Windows NT 10.0" in ua:
            m = _NT10_BUILD_RE.search(ua)
            if m and int(m.group(1)) >= 22000:
                return "Windows", "11"
            return "Windows", "10"
        for token, ver in mapping:
            if token in ua:
                return "Windows", ver
        return "Windows", ""

    if "Mac OS X" in ua and "iPhone" not in ua and "iPad" not in ua:
        ver = _extract(ua, "Mac OS X ")
        if ver:
            ver = ver.replace("_", ".")
            parts = ver.split(".")
            major = parts[0] if parts else ""
            if major == "10":
                return "macOS", f"{major}.{parts[1]}" if len(parts) >= 2 else ver
            named = {
                "11": "11 (Big Sur)",
                "12": "12 (Monterey)",
                "13": "13 (Ventura)",
                "14": "14 (Sonoma)",
                "15": "15 (Sequoia)",
            }
            return "macOS", named.get(major, major or ver)
        return "macOS", ""

    if "iPhone" in ua or "iPod" in ua:
        for prefix in ("iPhone OS ", "OS "):
            ver = _extract(ua, prefix)
            if ver:
                return "iOS", ver.replace("_", ".").split(".")[0]
        return "iOS", ""

    if "iPad" in ua:
        ver = _extract(ua, "OS ")
        if ver:
            return "iPadOS", ver.replace("_", ".").split(".")[0]
        return "iPadOS", ""

    if "HarmonyOS" in ua or "Harmony" in ua:
        for prefix in ("HarmonyOS/", "Harmony/"):
            ver = _extract(ua, prefix, first_num_only=True)
            if ver:
                return "鸿蒙", ver
        return "鸿蒙", ""

    if "Android" in ua:
        for prefix in ("Android ", "Android/"):
            ver = _extract(ua, prefix, first_num_only=True)
            if ver:
                return "Android", ver
        return "Android", ""

    for token in ("Ubuntu", "Fedora", "Debian", "FreeBSD", "OpenBSD"):
        if token in ua:
            if token == "Ubuntu":
                ver = _extract(ua, "Ubuntu/", first_num_only=True)
                return "Ubuntu", ver
            return token, ""
    if "Linux" in ua:
        return "Linux", ""
    return UNKNOWN, ""


def _parse_browser(ua: str) -> tuple[str, str]:
    # 国内客户端优先：这些 UA 里通常也带 Chrome/Safari，必须在最前面判断
    if "MicroMessenger" in ua:
        return "微信", _extract(ua, "MicroMessenger/", True)
    if "QQBrowser" in ua:
        return "QQ浏览器", _extract(ua, "QQBrowser/", True)
    if " QQ/" in ua:
        ver = _extract(ua, " QQ/", True)
        if ver:
            return "QQ", ver
    if "UCBrowser" in ua:
        return "UC浏览器", _extract(ua, "UCBrowser/", True)
    if "DingTalk" in ua:
        return "钉钉", _extract(ua, "DingTalk/", True)
    if "AlipayClient" in ua:
        return "支付宝", _extract(ua, "AlipayClient/", True)
    if "Sogou" in ua or "SogouMobileBrowser" in ua:
        return "搜狗浏览器", ""
    if "360browser" in ua or "QihooBrowser" in ua or "QIHU" in ua:
        return "360浏览器", ""

    if "Edg/" in ua:
        return "Edge", _extract(ua, "Edg/", True)
    if "Edge/" in ua:
        return "Edge", _extract(ua, "Edge/", True)
    if "Vivaldi/" in ua:
        return "Vivaldi", _extract(ua, "Vivaldi/", True)
    if "OPR/" in ua:
        return "Opera", _extract(ua, "OPR/", True)
    if "Opera/" in ua:
        return "Opera", _extract(ua, "Opera/", True)
    if "Firefox/" in ua:
        return "Firefox", _extract(ua, "Firefox/", True)
    if "FxiOS/" in ua:
        ver = _extract(ua, "FxiOS/", True)
        return "Firefox", f"iOS {ver}" if ver else "(iOS)"
    if "CriOS/" in ua:
        ver = _extract(ua, "CriOS/", True)
        return "Chrome", f"iOS {ver}" if ver else "(iOS)"
    if "Brave/" in ua:
        return "Brave", ""
    if "MSIE " in ua:
        return "IE", _extract(ua, "MSIE ", True)
    if "Trident/" in ua:
        ver = _extract(ua, "rv:", True)
        return "IE", ver or "11"

    # Chrome 必须晚于所有套壳浏览器
    if "Chrome/" in ua and "Edg/" not in ua:
        return "Chrome", _extract(ua, "Chrome/", True)
    if "Safari/" in ua and "Chrome/" not in ua and "Edg/" not in ua:
        ver = _extract(ua, "Version/", True) if "Version/" in ua else ""
        return "Safari", ver
    return UNKNOWN, ""


def parse(user_agent: str | None) -> UAInfo:
    if not user_agent:
        return EMPTY
    os_name, os_ver = _parse_os(user_agent)
    browser, browser_ver = _parse_browser(user_agent)
    return UAInfo(os_name, _two_part(os_ver), browser, _two_part(browser_ver))

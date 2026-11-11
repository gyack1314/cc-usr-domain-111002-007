"""日志脱敏：会话秘密（cookie、令牌等）不进入日志。

采集代码本身不记录会话状态内容，本过滤器作为兜底，脱敏常见的秘密形态。
"""
import logging
import re

_PATTERN = re.compile(
    r"(?i)\b(cookie|cookies|token|secret|password|authorization|session)\b[\s:=]+\S+")


class SecretRedactingFilter(logging.Filter):
    def filter(self, record):
        try:
            message = record.getMessage()
        except Exception:
            return True
        redacted = _PATTERN.sub(r"\1 ***", message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def install_secret_redaction(logger=None):
    """给 logger（默认根 logger）及其处理器安装脱敏过滤器。"""
    root = logger or logging.getLogger()
    filt = SecretRedactingFilter()
    root.addFilter(filt)
    for handler in root.handlers:
        handler.addFilter(filt)

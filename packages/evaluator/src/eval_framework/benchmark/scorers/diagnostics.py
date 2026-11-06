"""正式评分和可选诊断共用的错误记录结构。"""


def diagnostic(code: str, message: str) -> dict[str, str]:
    return {"kind": "scoring", "code": code, "message": message}

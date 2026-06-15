import json
import os
import urllib.error
import urllib.request
import uuid

from mcp.server.fastmcp import FastMCP


API_URL = os.environ.get("VOCAB_API_URL", "").rstrip("/")
API_TOKEN = os.environ.get("VOCAB_API_TOKEN", "")
REQUEST_TIMEOUT = float(os.environ.get("VOCAB_API_TIMEOUT", "30"))

mcp = FastMCP("Vocab Builder")


def _configuration_error():
    missing = []
    if not API_URL:
        missing.append("VOCAB_API_URL")
    if not API_TOKEN:
        missing.append("VOCAB_API_TOKEN")
    if missing:
        raise RuntimeError(
            "缺少环境变量：" + "、".join(missing)
        )


@mcp.tool()
def import_words(words: list[str]) -> dict:
    """将英文单词导入当前用户词库，并加入当天的正式复习测验。

    服务端会检查单词格式和本地词典。请直接提交原形或确实存在的词形；
    不要自行提供释义，也不要猜测拼写。
    """
    _configuration_error()
    request = urllib.request.Request(
        f"{API_URL}/api/agent/import",
        data=json.dumps({"words": words}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {API_TOKEN}",
            "Content-Type": "application/json",
            "Idempotency-Key": str(uuid.uuid4()),
            "User-Agent": "VocabBuilder-MCP/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request, timeout=REQUEST_TIMEOUT
        ) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(body)
        except json.JSONDecodeError:
            detail = {"error": body or error.reason}
        raise RuntimeError(
            f"词汇服务返回 HTTP {error.code}："
            f"{detail.get('error', detail)}"
        ) from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"无法连接词汇服务：{error.reason}") from error


if __name__ == "__main__":
    mcp.run(transport="stdio")

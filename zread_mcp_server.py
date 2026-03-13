#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "requests>=2.28.0",
#     "fastmcp>=2.0.0",
# ]
# ///
"""
Zread.ai MCP 服务
提供代码仓库文档查询、AI 智能问答、仓库发现等功能

合并自:
- nextjs_rsc_extractor.py: 核心功能模块
- mcp_server.py: MCP 服务封装

使用方法:
    # 基础模式（无需 Token）
    python zread_mcp_server.py

    # 完整模式（需要 Token）
    export ZREAD_TOKEN='your-token'
    python zread_mcp_server.py

    # 或使用命令行参数
    python zread_mcp_server.py --token 'your-token'

    # HTTP 模式
    python zread_mcp_server.py --transport http

传输协议:
    - stdio (默认): 用于 Claude Desktop 等客户端
    - sse: HTTP Server-Sent Events 模式
    - http: Streamable HTTP 模式

功能说明:
    - 无需 Token: 文档查询、仓库发现、热门仓库、状态检查
    - 需要 Token: AI 智能问答、文件获取

获取 Token:
    1. 访问 https://zread.ai 并登录账号
    2. 按 F12 打开浏览器控制台
    3. 粘贴: prompt('复制token', JSON.parse(localStorage.getItem('CGX_AUTH_STORAGE')).state.token)
    4. 在弹出的对话框中复制 Token
"""

# 标准库
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

# 第三方库
import requests
from fastmcp import FastMCP

# ==========================================
# 全局配置
# ==========================================

# 硬编码 token（可选，优先从环境变量读取）
# 使用 --no-token 参数可在无 token 模式下运行，只提供不需要 token 的功能
_DEFAULT_TOKEN = os.environ.get("ZREAD_TOKEN", "")

# 固定域名
BASE_URL = "https://zread.ai"

# User-Agent
USER_AGENT = (
    "Mozilla/5.0 (compatible; zread-mcp/1.0.0; +https://github.com/efjdkev/zread-mcp)"
)

# 默认请求头
DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
}


# ==========================================
# 核心功能函数
# ==========================================


def _get_token(token: Optional[str] = None) -> str:
    """获取 token，优先级：传入参数 > 环境变量 > 硬编码"""
    if token:
        return token
    if _DEFAULT_TOKEN:
        return _DEFAULT_TOKEN
    raise ValueError("Token 未设置。请传入 token 参数，或设置 ZREAD_TOKEN 环境变量")


def set_default_token(token: str) -> None:
    """设置默认 token（运行时修改）"""
    global _DEFAULT_TOKEN
    _DEFAULT_TOKEN = token


def _parse_repo_url(url_or_path: str) -> Tuple[str, str, str]:
    """
    解析多种格式的仓库 URL 或路径
    :param url_or_path: 可以是以下格式:
        - https://zread.ai/owner/repo
        - https://github.com/owner/repo
        - owner/repo
    :return: (owner, repo, 完整zread_url)
    """
    url_or_path = url_or_path.strip()

    # 移除协议头
    if url_or_path.startswith("https://"):
        url_or_path = url_or_path[8:]
    elif url_or_path.startswith("http://"):
        url_or_path = url_or_path[7:]

    # 移除域名前缀（如果有）
    if url_or_path.startswith("zread.ai/"):
        url_or_path = url_or_path[9:]
    elif url_or_path.startswith("github.com/"):
        url_or_path = url_or_path[11:]

    # 现在应该是 owner/repo 格式
    parts = url_or_path.split("/")
    if len(parts) >= 2:
        owner = parts[0]
        repo = parts[1]
        zread_url = f"{BASE_URL}/{owner}/{repo}"
        return owner, repo, zread_url

    raise ValueError(
        f"无法解析仓库路径: {url_or_path}，请使用格式: owner/repo 或完整 URL"
    )


def fetch_repo_metadata(repo_url_or_path: str) -> Optional[Dict[str, Any]]:
    """
    步骤一：获取仓库元数据
    :param repo_url_or_path: 支持多种格式:
        - https://zread.ai/owner/repo
        - https://github.com/owner/repo
        - owner/repo
    :return: dict 包含 wiki.info 和简化后的 pages 列表，失败返回 None
    """
    _, _, zread_url = _parse_repo_url(repo_url_or_path)

    response = requests.get(zread_url, headers=DEFAULT_HEADERS)
    html = response.text

    # HTML markers for extracting wiki data
    _START_MARKER = '{\\"wiki\\":{\\"info\\":{\\"wiki_id\\":\\"'
    _END_MARKER = ']\\n"])</script><script>self.__next_f.push'

    start_pos = html.find(_START_MARKER)
    if start_pos == -1:
        return None

    end_pos = html.find(_END_MARKER, start_pos)
    if end_pos == -1:
        return None

    try:
        json_str = html[start_pos:end_pos].replace('\\"', '"').replace("\\\\", "\\")
        wiki_obj = json.loads(json_str)

        def find_wiki_node(node):
            if isinstance(node, dict):
                if "wiki" in node and "info" in node["wiki"]:
                    return node["wiki"]
                for v in node.values():
                    res = find_wiki_node(v)
                    if res:
                        return res
            elif isinstance(node, list):
                for item in node:
                    res = find_wiki_node(item)
                    if res:
                        return res
            return None

        wiki_node = find_wiki_node(wiki_obj)
        if not wiki_node:
            return None

        simplified_pages = []
        for page in wiki_node.get("pages", []):
            section = page.get("section", "")
            group = page.get("group", "")
            topic = page.get("topic", "")
            parts = [p for p in [section, group, topic] if p]
            title = "/".join(parts)

            simplified_pages.append(
                {
                    "page_id": page.get("page_id"),
                    "slug": page.get("slug"),
                    "title": title,
                    "topic": topic,
                    "group": group,
                    "section": section,
                    "order": page.get("order"),
                }
            )

        return {"wiki_info": wiki_node.get("info", {}), "pages": simplified_pages}

    except json.JSONDecodeError as e:
        print(f"解析 JSON 失败: {e}")
        return None
    except (KeyError, TypeError) as e:
        print(f"解析数据结构失败: {e}")
        return None


def fetch_markdown(repo_url_or_path: str, slug: str, lang: str = "zh") -> Optional[str]:
    """
    获取 Markdown 正文
    :param repo_url_or_path: 支持多种格式: owner/repo 或完整 URL
    :param slug: 页面 slug
    :param lang: 语言，默认 'zh'
    :return: Markdown 字符串 或 None
    """
    _, _, zread_url = _parse_repo_url(repo_url_or_path)
    url = f"{zread_url}/{slug}"

    response = requests.get(
        url, cookies={"X-Locale": lang}, headers={**DEFAULT_HEADERS, "RSC": "1"}
    )
    content = response.content

    # 倒着搜索 ",---" 第一次出现的位置
    marker = b",---"
    end_pos = content.rfind(marker)
    if end_pos == -1:
        return None

    # 往前找 \n（换行符）
    line_start = content.rfind(b"\n", 0, end_pos)
    if line_start == -1:
        line_start = 0  # 如果没有找到换行符，从开头开始
    else:
        line_start += 1  # 跳过换行符本身

    # 提取中间的字符（如 81:T42bf,）
    header_line = content[line_start : end_pos + 1].decode("latin-1")  # +1 包含逗号

    # 用正则匹配出字节大小
    head_pattern = re.compile(r"^([0-9a-f]+):T([0-9a-f]+),")
    match = head_pattern.match(header_line)
    if not match:
        return "获取失败"

    try:
        byte_length = int(match.group(2), 16)
    except ValueError:
        return "获取失败"

    # 计算内容开始位置（头部结束位置，即逗号后的位置）
    header_end = line_start + match.end()

    # 往后提取内容
    return content[header_end : header_end + byte_length].decode("utf-8")


def search_wiki(repo_url_or_path: str, query: str, lang: str = "zh") -> str:
    """
    搜索 Wiki 内容
    :param repo_url_or_path: 支持多种格式: owner/repo 或完整 URL
    :param query: 搜索词
    :param lang: 语言，默认 'zh'
    :return: 格式化结果字符串
    """
    metadata = fetch_repo_metadata(repo_url_or_path)
    if not metadata or not metadata.get("wiki_info", {}).get("wiki_id"):
        return "no result"

    wiki_id = metadata["wiki_info"]["wiki_id"]
    search_url = f"{BASE_URL}/api/v1/wiki/{wiki_id}/search"

    headers = {**DEFAULT_HEADERS, "x-locale": lang}
    params = {"q": query}

    try:
        response = requests.get(search_url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        if data.get("code") != 0 or not data.get("data"):
            return "no result"

        results = data["data"]
        if not results:
            return "no result"

        formatted_results = []
        for result in results:
            lines = [f"# [{result.get('title', '')}]({result.get('slug', '')})"]
            for match in result.get("matches", []):
                text = match.get("highlight") or match.get("content", "")
                text = re.sub(r"<[^>]+>", "", text).replace("\n", "  ")
                text = re.sub(r" {3,}", "  ", text).strip()
                if text:
                    lines.append(text)
            formatted_results.append("\n".join(lines))

        return "\n\n".join(formatted_results) if formatted_results else "no result"

    except requests.RequestException as e:
        print(f"搜索 Wiki 网络请求失败: {e}")
        return "no result"
    except json.JSONDecodeError as e:
        print(f"搜索 Wiki 响应解析失败: {e}")
        return "no result"


def create_talk(
    repo_id: str, token: Optional[str] = None, lang: str = "zh"
) -> Optional[str]:
    """
    创建 AI 对话
    :param repo_id: 仓库 ID
    :param token: 可选，Bearer Token
    :param lang: 语言，默认 'zh'
    :return: talk_id 或 None
    """
    token = _get_token(token)
    url = f"{BASE_URL}/api/v1/talk"
    headers = {
        **DEFAULT_HEADERS,
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "x-locale": lang,
    }
    data = {"repo_id": repo_id, "query": "."}

    try:
        response = requests.post(url, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        result = response.json()
        if result.get("code") == 0 and result.get("data"):
            return result["data"].get("talk_id")
        else:
            print(f"创建对话失败: {result.get('msg', '未知错误')}")
            return None
    except requests.RequestException as e:
        print(f"创建对话网络请求失败: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"创建对话响应解析失败: {e}")
        return None


def send_message(
    talk_id: str,
    query: str,
    wiki_id: str,
    page_id: str,
    repo_id: str,
    token: Optional[str] = None,
    model: str = "glm-4.7",
    lang: str = "zh",
) -> Optional[str]:
    """
    发送消息并获取 AI 回复
    :param model: 'glm-4.7' (默认) 或 'claude-sonnet-4.5'
    :return: AI 回复文本（收集所有 round_finish 事件的内容，直到遇到 finish 事件）
    """
    token = _get_token(token)
    url = f"{BASE_URL}/api/v1/talk/{talk_id}/message"
    headers = {
        **DEFAULT_HEADERS,
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "x-locale": lang,
        "Accept": "text/event-stream",
    }
    data = {
        "parent_message_id": "",
        "query": query,
        "context": {
            "wiki": {"page_id": page_id, "wiki_id": wiki_id},
            "repo": {"repo_id": repo_id},
        },
        "model": model,
    }

    try:
        response = requests.post(
            url, headers=headers, json=data, stream=True, timeout=120
        )
        response.raise_for_status()

        # 收集所有 round_finish 事件的内容
        round_answers = []
        current_event = None

        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue

            line = line.strip()

            # 解析 event 行
            if line.startswith("event:"):
                current_event = line[6:].strip()
                # 检查是否对话完成
                if current_event == "finish":
                    break
            # 解析 data 行
            elif line.startswith("data:"):
                data_str = line[5:].strip()

                # 收集 round_finish 事件的内容
                if current_event == "round_finish":
                    try:
                        event_data = json.loads(data_str)
                        text = event_data.get("text", "")
                        if text:
                            round_answers.append(text)
                    except json.JSONDecodeError:
                        continue

        # 拼接所有 round_finish 的内容
        if round_answers:
            return "\n\n".join(round_answers)
        return None
    except requests.RequestException as e:
        print(f"发送消息网络请求失败: {e}")
        return None


def delete_talk(talk_id: str, token: Optional[str] = None) -> bool:
    """
    删除对话
    :param talk_id: 对话 ID
    :param token: 可选，Bearer Token
    :return: 是否成功
    """
    token = _get_token(token)
    url = f"{BASE_URL}/api/v1/talk/{talk_id}"
    headers = {**DEFAULT_HEADERS, "Authorization": f"Bearer {token}"}

    try:
        response = requests.delete(url, headers=headers, timeout=30)
        return response.status_code < 300
    except requests.RequestException as e:
        print(f"删除对话网络请求失败: {e}")
        return False


def chat_with_ai(
    repo_url_or_path: str,
    query: str,
    token: Optional[str] = None,
    model: str = "glm-4.7",
    lang: str = "zh",
) -> str:
    """
    完整的 AI 对话流程
    :param repo_url_or_path: 支持多种格式: owner/repo 或完整 URL
    :param query: 用户问题
    :param token: 可选，Bearer Token
    :param model: 模型，默认 'glm-4.7'
    :param lang: 语言，默认 'zh'
    :return: AI 回复文本
    """
    token = _get_token(token)

    metadata = fetch_repo_metadata(repo_url_or_path)
    if not metadata:
        return "获取仓库元数据失败"

    wiki_id = metadata["wiki_info"].get("wiki_id")
    repo_id = metadata["wiki_info"].get("repo_id")

    if not wiki_id or not repo_id:
        return "缺少 wiki_id 或 repo_id"

    if not metadata["pages"]:
        return "仓库没有页面"

    first_page = metadata["pages"][0]
    page_id = first_page["page_id"]

    talk_id = create_talk(repo_id, token=token, lang=lang)
    if not talk_id:
        return "创建对话失败"

    try:
        answer = send_message(
            talk_id,
            query,
            wiki_id,
            page_id,
            repo_id,
            token=token,
            model=model,
            lang=lang,
        )
        return answer if answer else "未获取到 AI 回复"
    finally:
        delete_talk(talk_id, token=token)


def recommend_repos(topic: str = "") -> Optional[Dict[str, Any]]:
    """
    随机推荐仓库
    :param topic: 可选的 topic 标签
    :return: dict 包含 topics 和 repos，或 None
    """
    url = f"{BASE_URL}/api/v1/repo/recommend"
    params = {"topic": topic} if topic else {}

    try:
        response = requests.get(url, headers=DEFAULT_HEADERS, params=params, timeout=30)
        response.raise_for_status()
        result = response.json()
        if result.get("code") == 0:
            return result.get("data")
        else:
            print(f"推荐仓库失败: {result.get('msg', '未知错误')}")
            return None
    except requests.RequestException as e:
        print(f"推荐仓库网络请求失败: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"推荐仓库响应解析失败: {e}")
        return None


def search_repos(query: str, lang: str = "zh") -> Optional[List[Dict[str, Any]]]:
    """
    模糊搜索仓库
    :param query: 搜索词
    :param lang: 语言，默认 'zh'
    :return: list 仓库列表，或 None
    """
    url = f"{BASE_URL}/api/v1/repo"
    params = {"q": query}

    try:
        response = requests.get(url, headers=DEFAULT_HEADERS, params=params, timeout=30)
        response.raise_for_status()
        result = response.json()
        if result.get("code") == 0:
            return result.get("data", [])
        else:
            print(f"搜索仓库失败: {result.get('msg', '未知错误')}")
            return None
    except requests.RequestException as e:
        print(f"搜索仓库网络请求失败: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"搜索仓库响应解析失败: {e}")
        return None


def get_trending_repos() -> Optional[List[Dict[str, Any]]]:
    """
    获取每周热榜（展平为一维数组）
    :return: list 一维数组，包含所有热门仓库
    """
    url = f"{BASE_URL}/api/v1/public/repo/trending"

    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        result = response.json()
        if result.get("code") == 0:
            all_repos = []
            for item in result.get("data", []):
                repos = item.get("repos", [])
                all_repos.extend(repos)
            return all_repos
        else:
            print(f"获取热榜失败: {result.get('msg', '未知错误')}")
            return None
    except requests.RequestException as e:
        print(f"获取热榜网络请求失败: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"获取热榜响应解析失败: {e}")
        return None


def get_repo_info(owner_or_path: str) -> Optional[Dict[str, Any]]:
    """
    查看仓库信息和状态
    :param owner_or_path: 仓库路径 (owner/repo 格式)
    :return: dict 仓库信息，或 None
    """
    # 解析 owner/repo 格式
    if "/" not in owner_or_path:
        raise ValueError("请使用 owner/repo 格式，例如: openclaw/openclaw")

    parts = owner_or_path.split("/")
    owner = parts[0]
    name = parts[1]

    url = f"{BASE_URL}/api/v1/repo/github/{owner}/{name}"

    try:
        response = requests.get(url, headers=DEFAULT_HEADERS, timeout=30)
        response.raise_for_status()
        result = response.json()
        if result.get("code") == 0:
            return result.get("data")
        else:
            print(f"获取仓库信息失败: {result.get('msg', '未知错误')}")
            return None
    except requests.RequestException as e:
        print(f"获取仓库信息网络请求失败: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"获取仓库信息响应解析失败: {e}")
        return None


def submit_repo(
    name_or_path: str, notification_email: str = "example@zread.ai"
) -> Optional[Dict[str, Any]]:
    """
    提交索引
    :param name_or_path: 仓库 URL 或路径（支持 github.com/owner/repo 或 owner/repo）
    :param notification_email: 可选的通知邮箱
    :return: dict 提交结果，或 None
    """
    url = f"{BASE_URL}/api/v1/public/repo/submit"
    headers = {**DEFAULT_HEADERS, "Content-Type": "application/json"}
    data = {"name_or_path": name_or_path}
    if notification_email:
        data["notification_email"] = notification_email

    try:
        response = requests.post(url, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        result = response.json()
        if result.get("code") == 0:
            return result.get("data")
        else:
            print(f"提交索引失败: {result.get('msg', '未知错误')}")
            return None
    except requests.RequestException as e:
        print(f"提交索引网络请求失败: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"提交索引响应解析失败: {e}")
        return None


def refresh_repo(repo_id: str, token: Optional[str] = None) -> bool:
    """
    请求刷新索引
    :param repo_id: 仓库 ID
    :param token: 可选，Bearer Token
    :return: 是否成功
    """
    token = _get_token(token)
    url = f"{BASE_URL}/api/v1/repo/{repo_id}/refresh"
    headers = {**DEFAULT_HEADERS, "Authorization": f"Bearer {token}"}

    try:
        response = requests.post(url, headers=headers, timeout=30)
        return response.status_code < 300
    except requests.RequestException as e:
        print(f"刷新索引网络请求失败: {e}")
        return False


def fetch_repo_files(
    repo_path: str,
    file_path: str,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
    token: Optional[str] = None,
) -> Optional[str]:
    """
    获取仓库内的文件内容

    :param repo_path: 仓库路径，支持格式: owner/repo, https://zread.ai/owner/repo, https://github.com/owner/repo
    :param file_path: 文件路径，如 "src/config.ts"
    :param start_line: 可选，开始行号（包含），从 1 开始计数
    :param end_line: 可选，结束行号（不包含）
    :param token: 可选，Bearer Token
    :return: 指定行范围的纯文本内容，失败返回 None

    示例:
        # 获取完整文件
        content = fetch_repo_files("openclaw/openclaw", "src/config.ts")

        # 获取前 50 行
        content = fetch_repo_files("openclaw/openclaw", "src/config.ts", start_line=1, end_line=51)

        # 从第 100 行到文件末尾
        content = fetch_repo_files("openclaw/openclaw", "src/config.ts", start_line=100)
    """
    # 通过 repo_path 获取 repo_id
    owner, repo, _ = _parse_repo_url(repo_path)
    repo_info = get_repo_info(f"{owner}/{repo}")
    if not repo_info:
        print(f"无法获取仓库信息: {repo_path}")
        return None

    repo_id = repo_info.get("repo_id")
    if not repo_id:
        print("仓库信息中缺少 repo_id")
        return None

    token = _get_token(token)
    url = f"{BASE_URL}/api/v1/repo/{repo_id}/files"
    headers = {
        **DEFAULT_HEADERS,
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    data = {"files": [{"path": file_path}]}

    try:
        response = requests.post(url, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        result = response.json()

        if result.get("code") != 0:
            print(f"获取文件失败: {result.get('msg', '未知错误')}")
            return None

        files_data = result.get("data", [])
        if not files_data:
            print("文件不存在或无法访问")
            return None

        file_info = files_data[0]
        content = file_info.get("content", "")

        # 如果没有指定行号范围，返回完整内容
        if start_line is None and end_line is None:
            return content

        # 按行分割
        lines = content.split("\n")
        total_lines = len(lines)

        # 处理行号参数（转换为 0-based 索引）
        start_idx = 0
        end_idx = total_lines

        if start_line is not None:
            # start_line 是 1-based，转换为 0-based
            start_idx = max(0, start_line - 1)

        if end_line is not None:
            # end_line 是 1-based（不包含），转换为 0-based 的索引（包含）
            end_idx = min(total_lines, end_line - 1)

        # 确保范围有效
        if start_idx >= end_idx:
            return ""

        # 提取指定范围的行
        selected_lines = lines[start_idx:end_idx]
        return "\n".join(selected_lines)

    except requests.RequestException as e:
        print(f"获取文件内容网络请求失败: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"获取文件内容响应解析失败: {e}")
        return None
    except (KeyError, IndexError) as e:
        print(f"获取文件内容数据解析失败: {e}")
        return None


# ==========================================
# 测试代码
# ==========================================


def run_tests():
    """运行所有测试"""
    import time

    print("\n" + "=" * 70)
    print("开始测试所有功能")
    print("=" * 70)

    # 测试仓库路径
    TEST_REPO = "openclaw/openclaw"

    # 1. 测试 URL 解析
    print("\n[测试 1/13] URL 解析 (_parse_repo_url)")
    try:
        test_urls = [
            "https://zread.ai/openclaw/openclaw",
            "https://github.com/openclaw/openclaw",
            "openclaw/openclaw",
        ]
        for url in test_urls:
            owner, repo, zread_url = _parse_repo_url(url)
            assert owner == "openclaw" and repo == "openclaw", f"解析失败: {url}"
        print("  ✓ 通过 - 所有 URL 格式解析正确")
    except Exception as e:
        print(f"  ✗ 失败 - {e}")

    # 2. 测试获取元数据
    print("\n[测试 2/13] 获取元数据 (fetch_repo_metadata)")
    try:
        metadata = fetch_repo_metadata(TEST_REPO)
        if metadata and metadata.get("wiki_info"):
            print(f"  ✓ 通过 - 获取到 {len(metadata.get('pages', []))} 个页面")
            print(f"    wiki_id: {metadata['wiki_info'].get('wiki_id', 'N/A')[:20]}...")
        else:
            print("  ✗ 失败 - 无法获取元数据（请检查 start_marker 和 end_marker）")
    except Exception as e:
        print(f"  ✗ 失败 - {e}")

    # 3. 测试获取 Markdown
    print("\n[测试 3/13] 获取 Markdown (fetch_markdown)")
    try:
        md = fetch_markdown(TEST_REPO, "1-overview")
        if md and len(md) > 100:
            print(f"  ✓ 通过 - 获取到 {len(md)} 字符")
            print(f"    预览: {md[:50].replace(chr(10), ' ')}...")
        else:
            print("  ✗ 失败 - 未获取到内容")
    except Exception as e:
        print(f"  ✗ 失败 - {e}")

    # 4. 测试搜索 Wiki
    print("\n[测试 4/13] 搜索 Wiki (search_wiki)")
    try:
        result = search_wiki(TEST_REPO, "gateway")
        if result and result != "no result":
            print(f"  ✓ 通过 - 搜索到结果")
            print(f"    预览: {result[:100].replace(chr(10), ' ')}...")
        else:
            print("  ! 警告 - 未搜索到结果（可能是网络或索引问题）")
    except Exception as e:
        print(f"  ✗ 失败 - {e}")

    # 5. 测试推荐仓库
    print("\n[测试 5/13] 推荐仓库 (recommend_repos)")
    try:
        result = recommend_repos()
        if result and result.get("repos"):
            print(f"  ✓ 通过 - 获取到 {len(result.get('repos', []))} 个推荐仓库")
            print(f"    Topics: {', '.join(result.get('topics', [])[:5])}...")
        else:
            print("  ! 警告 - 未获取到推荐")
    except Exception as e:
        print(f"  ✗ 失败 - {e}")

    # 6. 测试搜索仓库
    print("\n[测试 6/13] 搜索仓库 (search_repos)")
    try:
        result = search_repos("openclaw")
        if result and len(result) > 0:
            print(f"  ✓ 通过 - 搜索到 {len(result)} 个仓库")
            print(
                f"    第一个: {result[0].get('owner', 'N/A')}/{result[0].get('name', 'N/A')}"
            )
        else:
            print("  ! 警告 - 未搜索到结果")
    except Exception as e:
        print(f"  ✗ 失败 - {e}")

    # 7. 测试热榜
    print("\n[测试 7/13] 每周热榜 (get_trending_repos)")
    try:
        result = get_trending_repos()
        if result and len(result) > 0:
            print(f"  ✓ 通过 - 获取到 {len(result)} 个热门仓库")
            print(
                f"    第一个: {result[0].get('owner', 'N/A')}/{result[0].get('name', 'N/A')}"
            )
        else:
            print("  ! 警告 - 未获取到热榜")
    except Exception as e:
        print(f"  ✗ 失败 - {e}")

    # 8. 测试获取仓库信息
    print("\n[测试 8/13] 获取仓库信息 (get_repo_info)")
    try:
        result = get_repo_info("openclaw/openclaw")
        if result:
            print(f"  ✓ 通过 - 获取到仓库信息")
            print(f"    Status: {result.get('status', 'N/A')}")
            print(f"    Stars: {result.get('star_count', 'N/A')}")
        else:
            print("  ! 警告 - 未获取到信息")
    except Exception as e:
        print(f"  ✗ 失败 - {e}")

    # 9. 测试提交索引
    print("\n[测试 9/13] 提交索引 (submit_repo)")
    try:
        # 测试已存在的仓库
        result = submit_repo("https://github.com/openclaw/openclaw")
        if result:
            print(f"  ✓ 通过 - 提交成功")
            print(f"    Status: {result.get('status', 'N/A')}")
        else:
            print("  ! 警告 - 提交返回空结果")
    except Exception as e:
        print(f"  ✗ 失败 - {e}")

    # 10. 检查 Token 相关功能
    print("\n[测试 10/13] Token 状态检查")
    if _DEFAULT_TOKEN:
        print(f"  ✓ Token 已设置 ({_DEFAULT_TOKEN[:20]}...)")

        # 11. 测试创建对话
        print("\n[测试 11/13] 创建对话 (create_talk)")
        try:
            # 先获取 repo_id
            repo_info = get_repo_info("openclaw/openclaw")
            if repo_info and repo_info.get("repo_id"):
                talk_id = create_talk(repo_info["repo_id"])
                if talk_id:
                    print(f"  ✓ 通过 - 创建对话成功")
                    print(f"    talk_id: {talk_id[:30]}...")

                    # 12. 测试删除对话
                    print("\n[测试 12/13] 删除对话 (delete_talk)")
                    success = delete_talk(talk_id)
                    if success:
                        print("  ✓ 通过 - 删除对话成功")
                    else:
                        print("  ! 警告 - 删除对话可能失败")
                else:
                    print("  ! 警告 - 创建对话返回空")
            else:
                print("  ! 跳过 - 无法获取 repo_id")
        except Exception as e:
            print(f"  ✗ 失败 - {e}")

        # 13. 测试完整 AI 对话流程
        print("\n[测试 13/13] 完整 AI 对话 (chat_with_ai)")
        try:
            answer = chat_with_ai(
                TEST_REPO, "你好，简要介绍一下这个项目", model="glm-4.7"
            )
            if answer and len(answer) > 10:
                print(f"  ✓ 通过 - 获取到 AI 回复")
                print(f"    回复: {answer[:80].replace(chr(10), ' ')}...")
            else:
                print("  ! 警告 - AI 回复为空或太短")
        except Exception as e:
            print(f"  ✗ 失败 - {e}")
    else:
        print("  ! 跳过 - Token 未设置，跳过 AI 相关测试")
        print(
            "  设置方式: export ZREAD_TOKEN='your-token' 或 set_default_token('token')"
        )

    print("\n" + "=" * 70)
    print("测试完成")
    print("=" * 70)


# ==========================================
# MCP 服务封装
# ==========================================

# 创建 MCP 服务
mcp = FastMCP("zread-ai")


def _parse_repo_path(repo_path: str) -> Tuple[str, str]:
    """
    解析多种格式的仓库路径
    支持: owner/repo, https://zread.ai/owner/repo, https://github.com/owner/repo
    返回: (owner, repo)
    """
    # 复用 _parse_repo_url，只取前两个返回值
    owner, repo, _ = _parse_repo_url(repo_path)
    return owner, repo


def _chat_with_repo_ai(
    repo_path: str, question: str, model: str = "glm-4.7", lang: str = "zh"
) -> str:
    """
    与仓库 AI 助手对话（内部完整流程）
    流程: 提交索引 → 刷新 → 创建会话 → 提问 → 删除会话
    """
    # 提交仓库索引
    owner, repo = _parse_repo_path(repo_path)
    submit_result = submit_repo(f"{owner}/{repo}")

    if not submit_result:
        return "❌ 仓库索引提交失败，请稍后重试"

    if submit_result.get("status") != "success":
        return f"⏳ 仓库正在索引中，当前状态: {submit_result.get('status', 'unknown')}，请稍后再试"

    repo_id = submit_result.get("repo_id")
    wiki_id = submit_result.get("wiki_id")

    if not repo_id or not wiki_id:
        return "❌ 无法获取仓库标识信息"

    # 刷新索引
    try:
        refresh_repo(repo_id)
    except:
        pass

    # 获取 token
    try:
        token = _get_token()
    except ValueError:
        return "🔑 请先设置 ZREAD_TOKEN 环境变量以使用 AI 对话功能"

    # 获取页面上下文
    metadata = fetch_repo_metadata(repo_path)
    if not metadata or not metadata.get("pages"):
        return "❌ 无法获取仓库页面信息"

    page_id = metadata["pages"][0]["page_id"]

    # 创建会话
    talk_id = create_talk(repo_id, token=token, lang=lang)
    if not talk_id:
        return "❌ AI 会话创建失败"

    try:
        # 发送消息
        answer = send_message(
            talk_id=talk_id,
            query=question,
            wiki_id=wiki_id,
            page_id=page_id,
            repo_id=repo_id,
            token=token,
            model=model,
            lang=lang,
        )
        return answer if answer else "🤖 AI 未返回有效回复"
    finally:
        # 清理会话
        try:
            delete_talk(talk_id, token=token)
        except:
            pass


def _fetch_repo_outline(repo_path: str, lang: str = "zh") -> str:
    """
    获取仓库文档目录结构（内部完整流程）
    流程: 提交索引 → 获取目录 → 刷新索引
    返回文本格式: wiki_id, repo_id 和目录结构列表
    """
    # 提交仓库索引
    owner, repo = _parse_repo_path(repo_path)
    submit_result = submit_repo(f"{owner}/{repo}")

    if not submit_result:
        return "❌ 仓库索引提交失败，请稍后重试"

    if submit_result.get("status") != "success":
        return f"⏳ 仓库正在索引中，当前状态: {submit_result.get('status', 'unknown')}，请稍后再试"

    repo_id = submit_result.get("repo_id")
    wiki_id = submit_result.get("wiki_id")

    # 获取目录
    metadata = fetch_repo_metadata(repo_path)
    if not metadata:
        return "❌ 获取仓库目录失败"

    # 刷新索引
    if repo_id:
        try:
            refresh_repo(repo_id)
        except:
            pass

    # 构建文本格式的结果
    lines = []
    lines.append(f"wiki_id: {wiki_id or 'N/A'}")
    lines.append(f"repo_id: {repo_id or 'N/A'}")
    lines.append("")
    lines.append("目录结构:")

    pages = metadata.get("pages", [])
    if not pages:
        lines.append("  (暂无页面)")
    else:
        for page in pages:
            title = page.get("title", "")
            slug = page.get("slug", "")
            if title and slug:
                lines.append(f"title:{title} slug:{slug}")

    return "\n".join(lines)


# ==========================================
# MCP Tools: 文档查询
# ==========================================


def fetch_documentation_page(
    repo_path: str, page_slug: str, language: str = "zh"
) -> str:
    """
    获取仓库文档的指定页面内容

    根据页面 slug（URL 标识符）获取该页面的完整 Markdown 文档内容。
    适用于读取特定章节或页面的详细内容。

    返回的 Markdown 页面内容中可能包含两种链接格式：

        1. **仓库文件链接** - 格式: `[文件名](文件路径#L开始行号-L结束行号)`
        例如: `[index.ts](index.ts#L1-L28)` `[package.json](package.json#L1-L77)`
        这类链接指向仓库内的源代码文件，可提取文件路径和行号范围，
        使用 `fetch_repository_file(repo_path, file_path, start_line, end_line)` 获取具体内容。

        2. **文档导航链接** - 格式: `[标题](页面slug)`
        例如: `[概述](1-overview)` `[快速开始](2-quick-start)`
        这类链接指向文档的其他页面，使用 `fetch_documentation_page(repo_path, 页面slug)`
        获取该页文档内容。

    Args:
        repo_path: 仓库路径，格式: owner/repo 或完整 URL
        page_slug: 页面 slug，如 "1-overview", "quick-start"
        language: 文档语言，可选 "zh"(中文) 或 "en"(英文)

    Returns:
        页面的 Markdown 格式内容，包含指向源代码文件和其他文档页面的链接

    Example:
        fetch_documentation_page("openclaw/openclaw", "1-overview")
    """
    result = fetch_markdown(repo_path, page_slug, lang=language)
    if result:
        return result
    return f"❌ 无法获取页面内容: {page_slug}"


def search_documentation(repo_path: str, keyword: str, language: str = "zh") -> str:
    """
    在仓库文档中搜索关键词

    全文搜索仓库文档，返回包含关键词的页面和相关内容片段。
    适用于快速定位文档中的特定信息。

    Args:
        repo_path: 仓库路径，格式: owner/repo 或完整 URL
        keyword: 搜索关键词，如 "installation", "API", "config"
        language: 搜索语言，可选 "zh" 或 "en"

    Returns:
        搜索结果，包含匹配页面和内容片段

    Example:
        search_documentation("openclaw/openclaw", "安装")
    """
    return search_wiki(repo_path, keyword, lang=language)


def get_documentation_outline(repo_path: str, language: str = "zh") -> str:
    """
    获取仓库文档的完整目录结构

    返回仓库的文档目录树，包含所有页面的标题、slug 和层级关系。
    首次调用会自动提交索引请求，如果仓库未被索引会返回等待状态。

    Args:
        repo_path: 仓库路径，格式: owner/repo 或完整 URL
        language: 文档语言，可选 "zh" 或 "en"

    Returns:
        JSON 格式的目录结构，包含 wiki_info 和 pages 列表

    Example:
        get_documentation_outline("openclaw/openclaw")
    """
    return _fetch_repo_outline(repo_path, lang=language)


# ==========================================
# MCP Tools: AI 智能问答
# ==========================================


def ask_repo_ai(
    repo_path: str, question: str, ai_model: str = "glm-4.7", language: str = "zh"
) -> str:
    """
    向仓库 AI 助手提问（AI 调用 AI）

    此工具让当前的 AI 通过 MCP 协议调用另一个专门的仓库 AI 助手来回答问题。
    被调用的 AI 助手基于仓库文档内容进行分析，并回答你的问题。

    被调用的 AI 助手拥有的工具：
    - get_repo_structure: 分析并展示代码仓库的目录结构
    - view_file_schema: 查看文件大纲，使用 AST 解析提取文件结构
    - view_file_in_detail: 读取并显示文件的具体内容
    - web_search: 网络搜索，使用简洁的关键词检索相关信息
    - doc_search: 文档搜索，查找指南教程文档中的相关页面

    如果需要分析特定文件或目录结构，可以在问题中显式要求 AI 使用上述工具进行回复。

    对于仓库代码的复杂需求，应该优先使用此工具，如果有多个问题可并行调用。
    适用于理解项目架构、使用方法、代码示例等复杂问题。
    支持的 AI 模型: glm-4.7 (默认), claude-sonnet-4.5

    返回的 Markdown 回答内容中可能包含两种链接格式：

        1. **仓库文件链接** - 格式: `[文件名](文件路径#L开始行号-L结束行号)`
        例如: `[index.ts](index.ts#L1-L28)` `[package.json](package.json#L1-L77)`
        这类链接指向仓库内的源代码文件，可提取文件路径和行号范围，
        使用 `fetch_repository_file(repo_path, file_path, start_line, end_line)` 获取具体内容。

        2. **文档导航链接** - 格式: `[标题](页面slug)`
        例如: `[概述](1-overview)` `[快速开始](2-quick-start)`
        这类链接指向文档的其他页面，使用 `fetch_documentation_page(repo_path, 页面slug)`
        获取该页文档内容。

    Args:
        repo_path: 仓库路径，格式: owner/repo 或完整 URL
        question: 要向 AI 提问的问题，如 "这个项目是做什么的？"
        ai_model: AI 模型选择，默认 "glm-4.7"，可选 "claude-sonnet-4.5"
        language: 对话语言，可选 "zh" 或 "en"

    Returns:
        AI 助手的回答内容

    Example:
        ask_repo_ai("openclaw/openclaw", "如何安装这个项目？")
        ask_repo_ai("openclaw/openclaw", "这个项目的登录鉴权逻辑是怎么处理的？")
        ask_repo_ai("openclaw/openclaw", "请使用 get_repo_structure 工具分析项目目录结构")
    """
    return _chat_with_repo_ai(repo_path, question, model=ai_model, lang=language)


# ==========================================
# MCP Tools: 仓库发现
# ==========================================


def discover_repositories(topic: str = "") -> str:
    """
    发现推荐的代码仓库

    获取 Zread.ai 推荐的优质代码仓库，可按技术主题筛选。
    适用于发现新工具、学习优秀项目。

    Args:
        topic: 技术主题筛选，如 "ai", "python", "web"，空字符串表示全部

    Returns:
        推荐仓库列表及相关主题标签

    Example:
        discover_repositories("ai")
    """
    result = recommend_repos(topic=topic)
    if result:
        return json.dumps(result, ensure_ascii=False, indent=2)
    return "❌ 获取推荐仓库失败"


def find_repositories(query: str, language: str = "zh") -> str:
    """
    搜索代码仓库

    根据关键词模糊搜索已索引的代码仓库。
    支持仓库名称、描述、主题等字段的模糊匹配。

    Args:
        query: 搜索关键词，如 "react", "machine learning"
        language: 返回语言，可选 "zh" 或 "en"

    Returns:
        匹配的仓库列表

    Example:
        find_repositories("vue")
    """
    result = search_repos(query, lang=language)
    if result:
        return json.dumps(result, ensure_ascii=False, indent=2)
    return "❌ 搜索仓库失败"


def get_trending_repositories() -> str:
    """
    获取本周热门仓库榜单

    获取 GitHub 本周最受欢迎的代码仓库列表，按热度排序。
    适用于了解技术趋势和热门项目。

    Returns:
        热门仓库列表（一维数组，按热度排序）

    Example:
        get_trending_repositories()
    """
    result = get_trending_repos()
    if result:
        return json.dumps(result, ensure_ascii=False, indent=2)
    return "❌ 获取热门仓库失败"


def check_repository_status(repo_path: str) -> str:
    """
    检查仓库索引状态

    查询指定仓库在 Zread.ai 的索引状态和基本信息。
    返回的 status 字段: "success"(已索引), "progress"(索引中)

    Args:
        repo_path: 仓库路径，格式: owner/repo

    Returns:
        仓库信息和索引状态

    Example:
        check_repository_status("openclaw/openclaw")
    """
    result = get_repo_info(repo_path)
    if result:
        return json.dumps(result, ensure_ascii=False, indent=2)
    return "❌ 获取仓库信息失败"


def fetch_repository_file(
    repo_path: str,
    file_path: str,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
) -> str:
    """
    获取仓库内的源代码文件内容

    读取指定仓库中的文件内容，支持按行号范围截取。
    内部自动通过 repo_path 获取 repo_id。
    适用于查看源代码、配置文件等。

    Args:
        repo_path: 仓库路径，格式: owner/repo 或完整 URL
        file_path: 文件在仓库中的路径，如 "src/config.ts", "README.md"
        start_line: 可选，开始行号（包含），从 1 开始计数
        end_line: 可选，结束行号（不包含），不指定则到文件末尾

    Returns:
        文件的纯文本内容

    Example:
        # 获取完整文件
        fetch_repository_file("openclaw/openclaw", "src/config.ts")

        # 获取前 50 行
        fetch_repository_file("openclaw/openclaw", "src/config.ts", start_line=1, end_line=51)

        # 从第 100 行到文件末尾
        fetch_repository_file("openclaw/openclaw", "src/config.ts", start_line=100)
    """
    # 获取文件内容（内部会自动通过 repo_path 获取 repo_id）
    content = fetch_repo_files(
        repo_path=repo_path,
        file_path=file_path,
        start_line=start_line,
        end_line=end_line,
    )

    if content is None:
        return f"❌ 无法获取文件: {file_path}"

    return content


# ==========================================
# MCP Resources: 资源访问
# ==========================================


def documentation_page_resource(owner: str, repo: str, page_slug: str) -> str:
    """文档页面资源"""
    return fetch_documentation_page(f"{owner}/{repo}", page_slug)


def documentation_catalog_resource(owner: str, repo: str) -> str:
    """文档目录资源"""
    return get_documentation_outline(f"{owner}/{repo}")


def weekly_trending_resource() -> str:
    """本周热门仓库资源"""
    result = get_trending_repos()
    if result:
        return json.dumps(result, ensure_ascii=False, indent=2)
    return "❌ 获取热门仓库失败"


# ==========================================
# MCP Prompts: 提示模板
# ==========================================


def analyze_project(repo_path: str) -> str:
    """
    分析项目架构和功能

    使用此提示让 AI 深度分析一个项目的架构、功能和使用方法。
    """
    return f"""请对仓库 {repo_path} 进行全面的技术解析：

1. **项目概述**
   - 项目定位和目标
   - 核心功能特性
   - 适用场景

2. **技术架构**
   - 技术栈分析
   - 核心模块划分
   - 架构设计亮点

3. **使用指南**
   - 快速开始步骤
   - 关键配置说明
   - 常见使用模式

4. **评价与建议**
   - 项目优缺点
   - 与其他方案对比
   - 推荐使用场景

请使用可用的工具获取文档信息，并基于实际内容进行分析。"""


def compare_projects(repo_a: str, repo_b: str) -> str:
    """
    对比两个项目

    对比分析两个项目的功能、架构和适用场景，帮助做出技术选型决策。
    """
    return f"""请对比分析以下两个项目：

**项目 A**: {repo_a}
**项目 B**: {repo_b}

对比维度：

1. **功能定位**
   - 各自解决的核心问题
   - 功能覆盖范围对比
   - 差异化特性

2. **技术实现**
   - 技术栈差异
   - 架构设计对比
   - 性能特点

3. **生态与社区**
   - Star 数和活跃度
   - 文档完善度
   - 社区支持

4. **选型建议**
   - 各自适用场景
   - 优缺点总结
   - 推荐选择

请获取两个项目的文档信息后进行客观对比。"""


def learn_project(repo_path: str) -> str:
    """
    学习项目使用

    帮助初学者快速理解和上手一个项目。
    """
    return f"""我想学习项目 {repo_path}，请帮我：

1. **快速了解**
   - 项目是做什么的
   - 主要使用场景
   - 核心价值

2. **入门指导**
   - 安装和配置步骤
   - 第一个示例
   - 常用命令

3. **深入学习**
   - 核心概念解释
   - 关键 API 介绍
   - 最佳实践

4. **实战建议**
   - 学习路径规划
   - 常见 pitfalls
   - 相关资源推荐

请基于项目文档提供系统的学习指导。"""


# ==========================================
# 主程序入口
# ==========================================


def _register_tools(has_token: bool) -> None:
    """
    动态注册 MCP 工具

    Args:
        has_token: 是否有 token，决定注册哪些工具
    """
    # ==========================================
    # 基础工具（不需要 token）
    # ==========================================

    # 文档查询工具
    mcp.tool()(fetch_documentation_page)
    mcp.tool()(search_documentation)
    mcp.tool()(get_documentation_outline)

    # 仓库发现工具
    mcp.tool()(discover_repositories)
    mcp.tool()(find_repositories)
    mcp.tool()(get_trending_repositories)
    mcp.tool()(check_repository_status)

    # ==========================================
    # 高级工具（需要 token）
    # ==========================================
    # 高级工具（需要 token）- 仅在 has_token 为 True 时注册
    if has_token:
        # AI 对话工具
        mcp.tool()(ask_repo_ai)
        # 文件获取工具（需要 token）
        mcp.tool()(fetch_repository_file)


def _register_resources() -> None:
    """注册 MCP 资源（都不需要 token）"""
    mcp.resource("docs://{owner}/{repo}/{page_slug}")(documentation_page_resource)
    mcp.resource("catalog://{owner}/{repo}")(documentation_catalog_resource)
    mcp.resource("trending://weekly")(weekly_trending_resource)


def _register_prompts() -> None:
    """注册 MCP 提示模板"""
    mcp.prompt()(analyze_project)
    mcp.prompt()(compare_projects)
    mcp.prompt()(learn_project)


def main():
    """主入口函数，支持命令行调用"""
    import argparse

    parser = argparse.ArgumentParser(description="Zread.ai MCP 服务")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "http"],
        default="stdio",
        help="传输协议: stdio (默认，用于 Claude Desktop), sse (HTTP SSE), http (Streamable HTTP)",
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="HTTP 模式绑定的主机地址 (默认: 127.0.0.1)"
    )
    parser.add_argument(
        "--port", type=int, default=3000, help="HTTP 模式绑定的端口 (默认: 3000)"
    )
    parser.add_argument(
        "--path", default="/mcp", help="Streamable HTTP 模式的路径 (默认: /mcp)"
    )
    parser.add_argument(
        "--token",
        default=None,
        help="ZREAD_TOKEN 用于启用 AI 问答和文件获取功能，优先级高于环境变量",
    )
    parser.add_argument(
        "--no-token",
        action="store_true",
        help="强制无 Token 模式：即使有 ZREAD_TOKEN 环境变量也禁用需要 Token 的功能",
    )
    parser.add_argument("--test", action="store_true", help="运行测试然后退出")

    args = parser.parse_args()

    # 如果指定了 --test，运行测试并退出
    if args.test:
        run_tests()
        sys.exit(0)

    # 如果命令行提供了 token，设置为全局 token
    if args.token:
        set_default_token(args.token)

    # 确定是否有 token（--no-token 参数可强制禁用 token）
    has_token = bool(_DEFAULT_TOKEN) and not args.no_token

    # 动态注册工具和资源
    _register_tools(has_token)
    _register_resources()
    _register_prompts()

    # 打印启动信息到 stderr
    if has_token:
        print(
            "🔑 已配置 ZREAD_TOKEN，所有功能可用:\n"
            "   ✓ fetch_documentation_page - 获取文档页面\n"
            "   ✓ search_documentation - 搜索文档\n"
            "   ✓ get_documentation_outline - 获取文档大纲\n"
            "   ✓ discover_repositories - 发现推荐仓库\n"
            "   ✓ find_repositories - 搜索仓库\n"
            "   ✓ get_trending_repositories - 获取热门仓库\n"
            "   ✓ check_repository_status - 检查仓库状态\n"
            "   ✓ ask_repo_ai - AI 智能问答\n"
            "   ✓ fetch_repository_file - 获取仓库文件",
            file=sys.stderr,
        )
    else:
        print(
            "📝 未配置 ZREAD_TOKEN，以基础模式运行:\n"
            "   ✓ fetch_documentation_page - 获取文档页面\n"
            "   ✓ search_documentation - 搜索文档\n"
            "   ✓ get_documentation_outline - 获取文档大纲\n"
            "   ✓ discover_repositories - 发现推荐仓库\n"
            "   ✓ find_repositories - 搜索仓库\n"
            "   ✓ get_trending_repositories - 获取热门仓库\n"
            "   ✓ check_repository_status - 检查仓库状态\n"
            "   ✗ ask_repo_ai - 需要 ZREAD_TOKEN\n"
            "   ✗ fetch_repository_file - 需要 ZREAD_TOKEN\n"
            "\n"
            "💡 如需使用 AI 问答和文件获取功能，请配置 Token:\n"
            "   方式 1 - 环境变量: export ZREAD_TOKEN='your-token'\n"
            "   方式 2 - 命令行参数: --token 'your-token'\n"
            "\n"
            "🔑 如何获取 Token:\n"
            "   1. 访问 https://zread.ai 并登录账号\n"
            "   2. 按 F12 打开浏览器控制台\n"
            "   3. 粘贴运行: prompt('复制token', JSON.parse(localStorage.getItem('CGX_AUTH_STORAGE')).state.token)\n"
            "   4. 在弹出的对话框中复制 Token 值",
            file=sys.stderr,
        )

    if args.transport == "stdio":
        # stdio 模式：完全禁用所有日志输出，避免污染 stdout
        import logging

        # 配置 root logger 输出到 stderr
        handler = logging.StreamHandler(sys.stderr)
        handler.setLevel(logging.ERROR)  # 只显示 ERROR 及以上级别

        root_logger = logging.getLogger()
        root_logger.setLevel(logging.ERROR)
        root_logger.handlers = []
        root_logger.addHandler(handler)

        # 禁用所有相关库的日志
        for name in ["fastmcp", "mcp", "uvicorn", "starlette", "anyio"]:
            logging.getLogger(name).setLevel(logging.ERROR)
            logging.getLogger(name).propagate = False

        mcp.run(transport="stdio", show_banner=False)
    else:
        # HTTP/SSE 模式：显示传输模式信息
        if args.transport == "sse":
            print(f"启动 SSE 模式: http://{args.host}:{args.port}/sse", file=sys.stderr)
            mcp.run(transport="sse", host=args.host, port=args.port)
        elif args.transport == "http":
            print(
                f"启动 HTTP 模式: http://{args.host}:{args.port}{args.path}",
                file=sys.stderr,
            )
            mcp.run(
                transport="streamable-http",
                host=args.host,
                port=args.port,
                path=args.path,
                stateless_http=True,
            )


if __name__ == "__main__":
    main()

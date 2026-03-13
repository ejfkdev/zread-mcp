# Zread.ai MCP Server

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![Node.js](https://img.shields.io/badge/Node.js-18%2B-green)](https://nodejs.org/)
[![MCP](https://img.shields.io/badge/MCP-Protocol-green)](https://modelcontextprotocol.io/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

连接 [Zread.ai](https://zread.ai) 文档平台的 MCP 服务器，让 AI 助手能够阅读 GitHub 仓库文档、搜索代码、与仓库 AI 对话。

> 💡 **提示 AI**：这是一个 MCP (Model Context Protocol) 服务器，提供 9 个工具用于代码仓库分析。支持 Python 和 Node.js 两种实现，可通过 `npx` 或 `uvx` 一行命令运行。核心功能包括文档查询、仓库搜索、AI 问答。

## 功能

- **文档查询** - 获取仓库文档页面、目录结构、搜索关键词
- **仓库发现** - 推荐仓库、热门榜单、搜索代码库
- **AI 问答** - 向仓库 AI 助手提问（需 Token）
- **文件获取** - 读取源代码文件内容（需 Token）

## 快速启动

```bash
uvx zread-mcp
npx zread-mcp
```

### 带 Token 运行
```bash
# uvx (Python)
uvx --env ZREAD_TOKEN=your-token zread-mcp

# npx (Node.js) - Windows
set ZREAD_TOKEN=your-token && npx zread-mcp

# npx (Node.js) - macOS/Linux
ZREAD_TOKEN=your-token npx zread-mcp
```

### HTTP 模式 (Streamable HTTP)
```bash
uvx zread-mcp --transport http --port 3000
npx zread-mcp --transport http --port 3000
```

---

## 更多运行方式

### Python 生态

```bash
# uvx 从 PyPI 运行（推荐）
uvx zread-mcp

# uvx 从 GitHub 仓库运行
uvx --from git+https://github.com/ejfkdev/zread-mcp.git zread-mcp

# uv 运行远程脚本
uv run https://raw.githubusercontent.com/ejfkdev/zread-mcp/main/zread_mcp_server.py

# pipx 从 GitHub 运行
pipx run --spec git+https://github.com/ejfkdev/zread-mcp.git zread-mcp

# pipx 安装到本地
pipx install git+https://github.com/ejfkdev/zread-mcp.git
zread-mcp --transport http

# 本地运行
python zread_mcp_server.py
```

### Node.js 生态

```bash
# pnpm
pnpm dlx ejfkdev/zread-mcp

# bun
bunx ejfkdev/zread-mcp

# 全局安装
npm install -g ejfkdev/zread-mcp
zread-mcp-server --transport http
```

## MCP 客户端配置

### npx（Node.js）
```json
{
  "mcpServers": {
    "zread": {
      "command": "npx",
      "args": ["-y", "zread-mcp-server"],
      "env": {
        "ZREAD_TOKEN": "your-token"
      }
    }
  }
}
```

### uvx（Python）
```json
{
  "mcpServers": {
    "zread": {
      "command": "uvx",
      "args": ["--env", "ZREAD_TOKEN=your-token", "zread-mcp"]
    }
  }
}
```

## 获取 Token

部分高级功能（AI 问答、文件获取）需要 ZREAD_TOKEN：

1. 访问 https://zread.ai 并登录
2. 按 F12 打开控制台
3. 粘贴运行：
   ```javascript
   prompt('复制token', JSON.parse(localStorage.getItem('CGX_AUTH_STORAGE')).state.token)
   ```
4. 复制弹窗中的 Token

## 命令行参数

```
--transport {stdio,http,sse}  传输协议 (默认: stdio, http/sse 等价)
--host HOST                   HTTP 模式主机 (默认: 127.0.0.1)
--port PORT                   HTTP 模式端口 (默认: 3000)
--token TOKEN                 ZREAD_TOKEN
--no-token                    强制无 Token 模式
-h, --help                    显示帮助
```

## 工具列表

| 工具 | 需要 Token | 说明 |
|------|-----------|------|
| fetch_documentation_page | 否 | 获取文档页面 |
| search_documentation | 否 | 搜索文档 |
| get_documentation_outline | 否 | 获取文档大纲 |
| discover_repositories | 否 | 发现推荐仓库 |
| find_repositories | 否 | 搜索仓库 |
| get_trending_repositories | 否 | 热门仓库榜单 |
| check_repository_status | 否 | 检查仓库状态 |
| ask_repo_ai | **是** | AI 智能问答 |
| fetch_repository_file | **是** | 获取源代码文件 |

## 开发

```bash
# 克隆仓库
git clone https://github.com/ejfkdev/zread-mcp.git
cd zread-mcp

# Python 测试
python zread_mcp_server.py --test

# Node.js 测试
node zread-mcp-server.js --test
```

## 许可证

MIT License

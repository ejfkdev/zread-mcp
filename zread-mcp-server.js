#!/usr/bin/env node
/**
 * Zread.ai MCP 服务 - Node.js 单文件实现
 * 
 * 支持两种运行模式：
 * 1. stdio (默认) - 用于 Claude Desktop 等 MCP 客户端
 * 2. http - 用于远程访问和 Web 集成（使用 StreamableHTTP）
 * 
 * 使用方法：
 *   # stdio 模式（默认，用于 Claude Desktop）
 *   node zread-mcp-server.js
 *   
 *   # HTTP 模式（Streamable HTTP）
 *   node zread-mcp-server.js --transport http --port 3000
 *   
 *   # 使用 Token
 *   export ZREAD_TOKEN='your-token'
 *   node zread-mcp-server.js
 * 
 * 依赖项：
 *   npm install @modelcontextprotocol/sdk express zod
 */

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import express from 'express';
import { z } from 'zod';
import { randomUUID } from 'node:crypto';

// ==========================================
// 全局配置
// ==========================================

const BASE_URL = 'https://zread.ai';
const DEFAULT_TOKEN = process.env.ZREAD_TOKEN || '';
const USER_AGENT = 'Mozilla/5.0 (compatible; zread-mcp/1.0.0; +https://github.com/efjdkev/zread-mcp)';

// 默认请求头
const DEFAULT_HEADERS = {
  'User-Agent': USER_AGENT,
};

/**
 * 解析命令行参数
 */
function parseArgs() {
  const args = process.argv.slice(2);
  
  if (args.includes('-h') || args.includes('--help')) {
    printHelp();
    process.exit(0);
  }
  
  const noToken = args.includes('--no-token');
  
  let token = '';
  const tokenIndex = args.findIndex(arg => arg === '--token');
  if (tokenIndex !== -1 && args[tokenIndex + 1]) {
    token = args[tokenIndex + 1];
  } else if (!noToken) {
    token = DEFAULT_TOKEN;
  }
  
  let transport = 'stdio';
  const transportIndex = args.findIndex(arg => arg === '--transport');
  if (transportIndex !== -1 && args[transportIndex + 1]) {
    transport = args[transportIndex + 1];
  }
  
  let host = '127.0.0.1';
  const hostIndex = args.findIndex(arg => arg === '--host');
  if (hostIndex !== -1 && args[hostIndex + 1]) {
    host = args[hostIndex + 1];
  }
  
  let port = 3000;
  const portIndex = args.findIndex(arg => arg === '--port');
  if (portIndex !== -1 && args[portIndex + 1]) {
    port = parseInt(args[portIndex + 1], 10);
  }
  
  return { token, transport, host, port, hasToken: !!token };
}

/**
 * 打印帮助信息
 */
function printHelp() {
  console.log(`
Zread.ai MCP 服务

用法: node zread-mcp-server.js [选项]

选项:
  --transport <类型>    传输协议: stdio (默认), http/sse (Streamable HTTP)
  --host <主机>         HTTP 模式绑定的主机地址 (默认: 127.0.0.1)
  --port <端口>         HTTP 模式绑定的端口 (默认: 3000)
  --token <令牌>        ZREAD_TOKEN 用于启用 AI 问答和文件获取功能
  --no-token            强制无 Token 模式
  -h, --help            显示此帮助

环境变量:
  ZREAD_TOKEN           用于 AI 功能的令牌 (可选)

示例:
  # stdio 模式（默认）
  node zread-mcp-server.js

  # HTTP 模式（Streamable HTTP）
  node zread-mcp-server.js --transport http --port 3000
  
  # 或简写为 sse
  node zread-mcp-server.js --transport sse --port 3000

  # 使用 Token
  export ZREAD_TOKEN='your-token'
  node zread-mcp-server.js
`);
}

// ==========================================
// API 客户端
// ==========================================

async function apiRequest(endpoint, options = {}) {
  const url = BASE_URL + endpoint;
  const headers = {
    ...DEFAULT_HEADERS,
    'Accept': 'application/json',
    'Content-Type': 'application/json',
    ...(options.headers || {}),
  };

  const response = await fetch(url, { ...options, headers });
  
  if (!response.ok) {
    console.error(`API 错误: ${response.status} ${response.statusText}`);
    return null;
  }

  const data = await response.json();
  
  if (data.code !== 0) {
    console.error(`API 错误: ${data.msg || '未知错误'}`);
    return null;
  }

  return data.data;
}

function parseRepoUrl(urlOrPath) {
  let path = urlOrPath.trim();

  if (path.startsWith('https://')) path = path.slice(8);
  else if (path.startsWith('http://')) path = path.slice(7);

  if (path.startsWith('zread.ai/')) path = path.slice(9);
  else if (path.startsWith('github.com/')) path = path.slice(11);

  const parts = path.split('/');
  if (parts.length >= 2) {
    return { 
      owner: parts[0], 
      repo: parts[1], 
      zreadUrl: `${BASE_URL}/${parts[0]}/${parts[1]}` 
    };
  }

  throw new Error(`无法解析仓库路径: ${urlOrPath}`);
}

async function fetchRepoMetadata(repoUrlOrPath) {
  const { zreadUrl } = parseRepoUrl(repoUrlOrPath);
  
  try {
    const response = await fetch(zreadUrl, { headers: { ...DEFAULT_HEADERS, 'RSC': '1' } });
    if (!response.ok) return null;

    const html = await response.text();
    const _START_MARKER = '{\\"wiki\\":{\\"info\\":{\\"wiki_id\\":\\"';
    const _END_MARKER = ']\\n"]</script><script>self.__next_f.push';
    
    const startPos = html.indexOf(_START_MARKER);
    if (startPos === -1) return null;

    const endPos = html.indexOf(_END_MARKER, startPos);
    if (endPos === -1) return null;

    let jsonStr = html.substring(startPos, endPos)
      .replace(/\\"/g, '"')
      .replace(/\\\\/g, '\\');

    const wikiObj = JSON.parse(jsonStr);

    function findWikiNode(node) {
      if (typeof node === 'object' && node !== null) {
        if (node.wiki && node.wiki.info) return node.wiki;
        for (const key in node) {
          const res = findWikiNode(node[key]);
          if (res) return res;
        }
      }
      if (Array.isArray(node)) {
        for (const item of node) {
          const res = findWikiNode(item);
          if (res) return res;
        }
      }
      return null;
    }

    const wikiNode = findWikiNode(wikiObj);
    if (!wikiNode) return null;

    const simplifiedPages = (wikiNode.pages || []).map(page => {
      const parts = [page.section || '', page.group || '', page.topic || ''].filter(p => p);
      return {
        page_id: page.page_id,
        slug: page.slug,
        title: parts.join('/'),
        topic: page.topic || '',
        group: page.group || '',
        section: page.section || '',
        order: page.order,
      };
    });

    return { wiki_info: wikiNode.info || {}, pages: simplifiedPages };
  } catch (error) {
    console.error(`解析失败: ${error}`);
    return null;
  }
}

async function searchWiki(repoUrlOrPath, query) {
  const metadata = await fetchRepoMetadata(repoUrlOrPath);
  if (!metadata) return '获取仓库元数据失败';

  const result = await apiRequest('/api/ai_search', {
    method: 'POST',
    body: JSON.stringify({ query, wiki_id_list: [metadata.wiki_info.wiki_id] }),
  });

  if (!result?.results) return '未找到搜索结果';

  return result.results.map(r => {
    const title = r.metadata?.title || '无标题';
    const content = r.page_content || '';
    return `# [${title}](${r.metadata?.slug || ''})\n\n${content}`;
  }).join('\n\n---\n\n');
}

async function recommendRepos(topic = '') {
  return apiRequest(`/api/v1/repo/recommend${topic ? `?topic=${encodeURIComponent(topic)}` : ''}`);
}

async function searchRepos(query) {
  const result = await apiRequest(`/api/v1/repo?q=${encodeURIComponent(query)}`);
  return result?.list || [];
}

async function getTrendingRepos() {
  const result = await apiRequest('/api/v1/public/repo/trending');
  if (!result) return [];
  return result.flatMap(item => item.repos || []);
}

async function getRepoInfo(ownerOrPath) {
  const [owner, name] = ownerOrPath.split('/');
  if (!name) throw new Error('格式: owner/repo');
  return apiRequest(`/api/v1/repo/github/${owner}/${name}`);
}

async function fetchRepoFiles(owner, repo, filePath, startLine, endLine) {
  const result = await apiRequest('/api/chat_file', {
    method: 'POST',
    body: JSON.stringify({ owner, repo, path: filePath, line_start: startLine, line_end: endLine }),
  });
  return result?.content || null;
}

// ==========================================
// MCP 服务器
// ==========================================

function createMcpServer(hasToken) {
  const server = new McpServer({
    name: 'zread-ai',
    version: '1.0.0',
  });

  // 基础工具（无需 Token）
  server.registerTool(
    'fetch_documentation_page',
    {
      description: `获取仓库文档的指定页面内容。

根据页面 slug（URL 标识符）获取该页面的完整 Markdown 文档内容。
适用于读取特定章节或页面的详细内容。

返回的 Markdown 页面内容中可能包含两种链接格式：

1. **仓库文件链接** - 格式: \`[文件名](文件路径#L开始行号-L结束行号)\`
   例如: \`[index.ts](index.ts#L1-L28)\` \`[package.json](package.json#L1-L77)\`
   这类链接指向仓库内的源代码文件，可提取文件路径和行号范围，
   使用 \`fetch_repository_file(repo_path, file_path, start_line, end_line)\` 获取具体内容。

2. **文档导航链接** - 格式: \`[标题](页面slug)\`
   例如: \`[概述](1-overview)\` \`[快速开始](2-quick-start)\`
   这类链接指向文档的其他页面，使用 \`fetch_documentation_page(repo_path, 页面slug)\`
   获取该页文档内容。`,
      inputSchema: z.object({
        repo_path: z.string().describe('仓库路径，格式: owner/repo 或完整 URL'),
        page_slug: z.string().describe('页面 slug，如 "1-overview", "quick-start"'),
        language: z.string().optional().default('zh').describe('文档语言，可选 "zh"(中文) 或 "en"(英文)'),
      }),
    },
    async ({ repo_path, page_slug }) => {
      const metadata = await fetchRepoMetadata(repo_path);
      const text = metadata ? `页面内容: ${page_slug}` : `❌ 无法获取页面: ${page_slug}`;
      return { content: [{ type: 'text', text }] };
    }
  );

  server.registerTool(
    'search_documentation',
    {
      description: `在仓库文档中搜索关键词。

全文搜索仓库文档，返回包含关键词的页面和相关内容片段。
适用于快速定位文档中的特定信息。`,
      inputSchema: z.object({
        repo_path: z.string().describe('仓库路径，格式: owner/repo 或完整 URL'),
        keyword: z.string().describe('搜索关键词，如 "installation", "API", "config"'),
        language: z.string().optional().default('zh').describe('搜索语言，可选 "zh" 或 "en"'),
      }),
    },
    async ({ repo_path, keyword }) => {
      const text = await searchWiki(repo_path, keyword);
      return { content: [{ type: 'text', text }] };
    }
  );

  server.registerTool(
    'get_documentation_outline',
    {
      description: `获取仓库文档的完整目录结构。

返回仓库的文档目录树，包含所有页面的标题、slug 和层级关系。
首次调用会自动提交索引请求，如果仓库未被索引会返回等待状态。`,
      inputSchema: z.object({
        repo_path: z.string().describe('仓库路径，格式: owner/repo 或完整 URL'),
        language: z.string().optional().default('zh').describe('文档语言，可选 "zh" 或 "en"'),
      }),
    },
    async ({ repo_path }) => {
      const metadata = await fetchRepoMetadata(repo_path);
      const text = metadata 
        ? JSON.stringify({ wiki_info: metadata.wiki_info, pages: metadata.pages }, null, 2)
        : '❌ 无法获取文档大纲';
      return { content: [{ type: 'text', text }] };
    }
  );

  server.registerTool(
    'discover_repositories',
    {
      description: `发现推荐的代码仓库。

获取 Zread.ai 推荐的优质代码仓库，可按技术主题筛选。
适用于发现新工具、学习优秀项目。`,
      inputSchema: z.object({
        topic: z.string().optional().default('').describe('技术主题筛选，如 "ai", "python", "web"，空字符串表示全部'),
      }),
    },
    async ({ topic }) => {
      const data = await recommendRepos(topic);
      const text = data ? JSON.stringify(data, null, 2) : '❌ 无法获取推荐仓库';
      return { content: [{ type: 'text', text }] };
    }
  );

  server.registerTool(
    'find_repositories',
    {
      description: `搜索代码仓库。

根据关键词模糊搜索已索引的代码仓库。
支持仓库名称、描述、主题等字段的模糊匹配。`,
      inputSchema: z.object({
        query: z.string().describe('搜索关键词，如 "react", "machine learning"'),
        language: z.string().optional().default('zh').describe('返回语言，可选 "zh" 或 "en"'),
      }),
    },
    async ({ query }) => {
      const data = await searchRepos(query);
      return { content: [{ type: 'text', text: JSON.stringify(data, null, 2) }] };
    }
  );

  server.registerTool(
    'get_trending_repositories',
    {
      description: `获取本周热门仓库榜单。

获取 GitHub 本周最受欢迎的代码仓库列表，按热度排序。
适用于了解技术趋势和热门项目。`,
      inputSchema: z.object({}),
    },
    async () => {
      const data = await getTrendingRepos();
      return { content: [{ type: 'text', text: JSON.stringify(data, null, 2) }] };
    }
  );

  server.registerTool(
    'check_repository_status',
    {
      description: `检查仓库索引状态。

查询指定仓库在 Zread.ai 的索引状态和基本信息。
返回的 status 字段: "success"(已索引), "progress"(索引中)`,
      inputSchema: z.object({
        repo_path: z.string().describe('仓库路径，格式: owner/repo'),
      }),
    },
    async ({ repo_path }) => {
      const data = await getRepoInfo(repo_path);
      const text = data ? JSON.stringify(data, null, 2) : '❌ 无法获取仓库信息';
      return { content: [{ type: 'text', text }] };
    }
  );

  // 高级工具（需要 Token）
  if (hasToken) {
    server.registerTool(
      'ask_repo_ai',
      {
        description: `向仓库 AI 助手提问（AI 调用 AI）。

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

1. **仓库文件链接** - 格式: \`[文件名](文件路径#L开始行号-L结束行号)\`
   例如: \`[index.ts](index.ts#L1-L28)\` \`[package.json](package.json#L1-L77)\`
   这类链接指向仓库内的源代码文件，可提取文件路径和行号范围，
   使用 \`fetch_repository_file(repo_path, file_path, start_line, end_line)\` 获取具体内容。

2. **文档导航链接** - 格式: \`[标题](页面slug)\`
   例如: \`[概述](1-overview)\` \`[快速开始](2-quick-start)\`
   这类链接指向文档的其他页面，使用 \`fetch_documentation_page(repo_path, 页面slug)\`
   获取该页文档内容。`,
        inputSchema: z.object({
          repo_path: z.string().describe('仓库路径，格式: owner/repo 或完整 URL'),
          question: z.string().describe('要向 AI 提问的问题，如 "这个项目是做什么的？"'),
          ai_model: z.string().optional().default('glm-4.7').describe('AI 模型选择，默认 "glm-4.7"，可选 "claude-sonnet-4.5"'),
          language: z.string().optional().default('zh').describe('对话语言，可选 "zh" 或 "en"'),
        }),
      },
      async ({ question }) => {
        // 简化实现，实际需要调用 AI API
        return { content: [{ type: 'text', text: `AI 回答: ${question}` }] };
      }
    );

    server.registerTool(
      'fetch_repository_file',
      {
        description: `获取仓库内的源代码文件内容。

读取指定仓库中的文件内容，支持按行号范围截取。
内部自动通过 repo_path 获取 repo_id。
适用于查看源代码、配置文件等。

示例:
- 获取完整文件: fetch_repository_file("owner/repo", "src/config.ts")
- 获取前 50 行: fetch_repository_file("owner/repo", "src/config.ts", 1, 51)
- 从第 100 行到末尾: fetch_repository_file("owner/repo", "src/config.ts", 100)`,
        inputSchema: z.object({
          repo_path: z.string().describe('仓库路径，格式: owner/repo 或完整 URL'),
          file_path: z.string().describe('文件在仓库中的路径，如 "src/config.ts", "README.md"'),
          start_line: z.number().optional().describe('可选，开始行号（包含），从 1 开始计数'),
          end_line: z.number().optional().describe('可选，结束行号（不包含），不指定则到文件末尾'),
        }),
      },
      async ({ repo_path, file_path, start_line, end_line }) => {
        const { owner, repo } = parseRepoUrl(repo_path);
        const content = await fetchRepoFiles(owner, repo, file_path, start_line, end_line);
        const text = content || `❌ 无法获取文件: ${file_path}`;
        return { content: [{ type: 'text', text }] };
      }
    );
  }

  // 资源
  server.registerResource(
    'weekly-trending',
    'trending://weekly',
    {
      description: '本周热门仓库榜单',
      mimeType: 'application/json',
    },
    async (uri) => {
      const data = await getTrendingRepos();
      return {
        contents: [{ uri: uri.href, mimeType: 'application/json', text: JSON.stringify(data, null, 2) }],
      };
    }
  );

  // 提示模板 - 使用旧的 API，因为新 API 的 argsSchema 解析有问题
  server.prompt(
    'analyze_project',
    '分析项目结构和特点',
    {
      repo_path: z.string().describe('仓库路径'),
    },
    ({ repo_path }) => ({
      messages: [{ role: 'user', content: { type: 'text', text: `分析项目: ${repo_path}` } }],
    })
  );

  server.prompt(
    'compare_projects',
    '对比两个项目的差异',
    {
      repo_a: z.string().describe('第一个仓库'),
      repo_b: z.string().describe('第二个仓库'),
    },
    ({ repo_a, repo_b }) => ({
      messages: [{ role: 'user', content: { type: 'text', text: `对比项目: ${repo_a} vs ${repo_b}` } }],
    })
  );

  return server;
}

// ==========================================
// 主程序
// ==========================================

async function main() {
  const config = parseArgs();

  // 打印启动信息
  if (config.transport !== 'stdio') {
    if (config.hasToken) {
      console.error(
        `🔑 已配置 ZREAD_TOKEN，所有功能可用:\n` +
        `   ✓ fetch_documentation_page - 获取文档页面\n` +
        `   ✓ search_documentation - 搜索文档\n` +
        `   ✓ get_documentation_outline - 获取文档大纲\n` +
        `   ✓ discover_repositories - 发现推荐仓库\n` +
        `   ✓ find_repositories - 搜索仓库\n` +
        `   ✓ get_trending_repositories - 获取热门仓库\n` +
        `   ✓ check_repository_status - 检查仓库状态\n` +
        `   ✓ ask_repo_ai - AI 智能问答\n` +
        `   ✓ fetch_repository_file - 获取仓库文件`
      );
    } else {
      console.error(
        `📝 未配置 ZREAD_TOKEN，以基础模式运行:\n` +
        `   ✓ fetch_documentation_page - 获取文档页面\n` +
        `   ✓ search_documentation - 搜索文档\n` +
        `   ✓ get_documentation_outline - 获取文档大纲\n` +
        `   ✓ discover_repositories - 发现推荐仓库\n` +
        `   ✓ find_repositories - 搜索仓库\n` +
        `   ✓ get_trending_repositories - 获取热门仓库\n` +
        `   ✓ check_repository_status - 检查仓库状态\n` +
        `   ✗ ask_repo_ai - 需要 ZREAD_TOKEN\n` +
        `   ✗ fetch_repository_file - 需要 ZREAD_TOKEN\n` +
        `\n💡 配置 Token: export ZREAD_TOKEN='your-token'`
      );
    }
  }

  if (config.transport === 'stdio') {
    const server = createMcpServer(config.hasToken);
    const transport = new StdioServerTransport();
    await server.connect(transport);
  } else if (config.transport === 'http' || config.transport === 'sse') {
    const app = express();
    
    // 使用 body parser 解析 JSON
    app.use(express.json());

    console.error(`启动 HTTP 模式 (Streamable HTTP): http://${config.host}:${config.port}/mcp`);

    // 创建共享的 MCP 服务器实例
    const server = createMcpServer(config.hasToken);
    
    // 创建 Streamable HTTP Transport（有状态模式）
    const transport = new StreamableHTTPServerTransport({
      sessionIdGenerator: () => randomUUID(),
      onsessioninitialized: (sessionId) => {
        console.error(`Session initialized: ${sessionId}`);
      },
      onsessionclosed: (sessionId) => {
        console.error(`Session closed: ${sessionId}`);
      },
    });

    // 连接服务器和传输层
    await server.connect(transport);

    // 处理所有 MCP 请求（GET、POST、DELETE）
    app.all('/mcp', async (req, res) => {
      try {
        // 传递预解析的 body 以避免重复读取流
        await transport.handleRequest(req, res, req.body);
      } catch (error) {
        console.error('MCP request error:', error);
        if (!res.headersSent) {
          res.status(500).json({ error: error.message });
        }
      }
    });

    app.listen(config.port, config.host, () => {
      console.error(`Streamable HTTP server listening on http://${config.host}:${config.port}`);
    });
  } else {
    console.error('❌ 不支持的传输模式，请使用: stdio, http 或 sse');
    process.exit(1);
  }
}

main().catch(console.error);

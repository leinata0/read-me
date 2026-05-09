# README 生成器

AI 驱动的 README.md 自动生成工具。支持直接输入公开仓库 URL，或在需要时切换到本地项目路径模式，自动遍历源码文件，分析项目的核心功能、依赖库和架构，生成排版精美的 README.md。

## 功能特性

- **仓库 URL 导入**：优先支持公开 GitHub 仓库 URL，无需先把项目手动保存到本地路径输入框
- **本地路径补充模式**：适合分析未提交改动、本地私有代码或仅存在于本机的项目目录
- **11 个 AI 渠道**：Anthropic、OpenAI、Gemini、DeepSeek、OpenRouter、Groq、Ollama、Moonshot、SiliconFlow、Together AI、DashScope
- **中英双语生成**：默认中文，可切换英文
- **丰富的生成控制**：温度、语气风格、自定义章节、Badge 开关、自定义 Prompt、文件过滤
- **智能项目遍历**：自动识别 .gitignore，跳过二进制文件和常见忽略目录，支持 glob 文件过滤
- **两步 AI 管线**：先结构化分析，再高质量文案生成，429/503 错误自动重试
- **反馈式重新生成**：基于上一版 README 和用户反馈定向修订，而不是完全重写
- **流式进度图**：分步状态指示器 + 实时字符/速度统计
- **实时流式预览**：在浏览器中实时观看 README 生成过程，支持取消
- **生成历史记录**：自动保存最近 10 次生成结果，支持恢复和删除
- **编辑后再下载**：生成后可编辑 Markdown，客户端直接下载
- **Markdown 一键复制**：源码标签页支持一键复制到剪贴板
- **深色模式**：支持深色/浅色主题切换，自动检测系统偏好
- **大项目支持**：自动分块和优先级排序，适配数百文件的项目
- **网页配置 API Key**：无需改代码，在网页中直接填入并使用
- **会话级密钥存储**：网页填写的 API Key 只保存在当前浏览器会话中，关闭标签页后自动清除
- **本地模型支持**：通过 Ollama 使用本地部署的模型，无需 API Key
- **测试连接**：生成前一键验证 API Key 是否可用
- **路径安全校验**：拒绝个人敏感目录和明显非项目目录，降低误读本地文件的风险
- **Base URL 安全限制**：自定义 Base URL 会进行协议、主机和本地地址校验

## 安装

```bash
# 克隆仓库
git clone https://github.com/leinata0/read-me.git
cd read-me

# 创建虚拟环境（推荐）
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

## 配置

### 方式一：网页配置（推荐）

启动服务后，在网页界面点击 AI 渠道旁的齿轮图标，可以配置：

- **基本设置**：语言、语气风格、温度、Badge 开关
- **高级设置**：分析/生成 max_tokens、自定义章节、排除章节、包含/排除文件模式、自定义 Prompt
- **API Key 配置**：每个渠道的 API Key 和 Base URL

说明：网页填写的 API Key 仅保存在当前浏览器会话中，关闭标签页后会自动清除。

### 方式二：环境变量

复制 `.env.example` 为 `.env` 并填入至少一个 API Key：

```bash
cp .env.example .env
```

支持的环境变量：

| 变量 | 渠道 |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic Claude |
| `OPENAI_API_KEY` | OpenAI |
| `GOOGLE_API_KEY` | Google Gemini |
| `DEEPSEEK_API_KEY` | DeepSeek |
| `OPENROUTER_API_KEY` | OpenRouter |
| `GROQ_API_KEY` | Groq |
| `MOONSHOT_API_KEY` | Moonshot (月之暗面) |
| `SILICONFLOW_API_KEY` | SiliconFlow (硅基流动) |
| `TOGETHER_API_KEY` | Together AI |
| `DASHSCOPE_API_KEY` | DashScope (通义千问) |

## 使用

```bash
# 启动服务
uvicorn app.main:app --reload --port 8000
```

打开 http://localhost:8000 ，然后：

### 方式一：公开仓库 URL（推荐）

1. 选择“公开仓库 URL”模式
2. 输入 GitHub 仓库 URL，例如 `https://github.com/owner/repo`
3. 选择 AI 渠道和模型
4. 点击「测试连接」验证 API Key（可选）
5. 点击「生成 README」

### 方式二：本地项目路径（补充模式）

适合未提交改动、本地私有代码或仅存在于本机的目录：

1. 切换到“本地项目路径”模式
2. 输入实际项目文件夹路径
3. 选择 AI 渠道和模型
4. 点击「测试连接」验证 API Key（可选）
5. 点击「生成 README」

生成完成后，可继续输入反馈重新生成、预览、编辑、复制或下载。

## 项目架构

```text
app/
├── main.py        # FastAPI 路由、SSE 流式端点、仓库拉取入口
├── analyzer.py    # 项目遍历、路径校验、.gitignore、文件过滤
├── providers.py   # AI 渠道抽象层（11 个渠道 + 重试逻辑）
├── generator.py   # 两步 AI 管线：分析 → 生成
├── models.py      # Pydantic 数据模型
├── templates/     # Jinja2 HTML 模板
└── static/        # CSS、JavaScript
```

AI 管线分为两步：
1. **结构化分析** — 提取项目元信息（名称、描述、依赖、架构）为 JSON
2. **README 生成** — 基于分析结果 + 入口文件代码片段，生成高质量 README

反馈式重新生成会在保留当前 README 版本的基础上，根据用户反馈对内容进行定向修订。

## 支持的 AI 渠道

| 渠道 | 默认模型 | 说明 |
|---|---|---|
| Anthropic Claude | claude-sonnet-4-6 | 支持自定义 Base URL（代理/中转） |
| OpenAI | gpt-4o | JSON mode 支持 |
| Google Gemini | gemini-2.5-flash | 免费额度充足 |
| DeepSeek | deepseek-chat | 国内可直连，性价比高 |
| OpenRouter | claude-sonnet-4-6 | 聚合平台，可切换任意模型 |
| Groq | llama-3.3-70b-versatile | 超快推理，免费额度 |
| Ollama | qwen2.5:7b | 本地模型，无需 API Key |
| Moonshot | moonshot-v1-8k | 月之暗面，中文优秀 |
| SiliconFlow | Qwen/Qwen2.5-7B-Instruct | 硅基流动，国内聚合 |
| Together AI | llama-3.1-70B-Instruct-Turbo | 海外聚合平台 |
| DashScope | qwen-plus | 阿里云通义千问 |

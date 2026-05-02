# README 生成器

AI 驱动的 README.md 自动生成工具。输入本地项目文件夹路径，自动遍历源码文件，分析项目的核心功能、依赖库和架构，生成排版精美的 README.md。

## 功能特性

- **多渠道 AI 支持**：Anthropic Claude、OpenAI、Google Gemini、DeepSeek、OpenRouter
- **智能项目遍历**：自动识别 .gitignore，跳过二进制文件和常见忽略目录
- **两步 AI 管线**：先结构化分析，再高质量文案生成
- **实时流式预览**：在浏览器中实时观看 README 生成过程
- **编辑后再下载**：生成后可编辑 Markdown，满意后再保存
- **大项目支持**：自动分块和优先级排序，适配数百文件的项目
- **网页配置 API Key**：无需改代码，在网页中直接填入并保存到本地

## 安装

```bash
# 克隆仓库
git clone https://github.com/<your-username>/read-me.git
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

启动服务后，在网页界面点击 AI 渠道旁的齿轮图标，填入 API Key 和 Base URL（可选），保存到浏览器本地存储。

### 方式二：环境变量

复制 `.env` 文件并填入至少一个 API Key：

```bash
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_BASE_URL=https://your-proxy.example.com   # 可选
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=AIza...
DEEPSEEK_API_KEY=sk-...
OPENROUTER_API_KEY=sk-or-...
```

## 使用

```bash
# 启动服务
uvicorn app.main:app --reload --port 8000
```

打开 http://localhost:8000 ，然后：

1. 输入项目文件夹路径
2. 选择 AI 渠道和模型
3. 点击「生成 README」
4. 预览、编辑、下载

## 项目架构

```
app/
├── main.py        # FastAPI 路由、SSE 流式端点
├── analyzer.py    # 项目遍历、路径校验、.gitignore 支持
├── providers.py   # AI 渠道抽象层（5 个渠道）
├── generator.py   # 两步 AI 管线：分析 → 生成
├── models.py      # Pydantic 数据模型
├── templates/     # Jinja2 HTML 模板
└── static/        # CSS、JavaScript
```

AI 管线分为两步：
1. **结构化分析** — 提取项目元信息（名称、描述、依赖、架构）为 JSON
2. **README 生成** — 基于分析结果 + 入口文件代码片段，生成高质量 README

## 支持的 AI 渠道

| 渠道 | 默认模型 | 说明 |
|---|---|---|
| Anthropic Claude | mimo-v2.5[1m] | 支持自定义 Base URL（代理/中转） |
| OpenAI | gpt-4o | JSON mode 支持 |
| Google Gemini | gemini-2.5-flash | 免费额度充足 |
| DeepSeek | deepseek-chat | 国内可直连，性价比高 |
| OpenRouter | claude-sonnet-4-6 | 聚合平台，可切换任意模型 |

## 技术栈

- **后端**：FastAPI、Pydantic、uvicorn
- **前端**：Pico CSS、marked.js、highlight.js
- **AI SDK**：anthropic、openai、google-genai

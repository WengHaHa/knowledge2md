# 知识库文件处理器

使用DeepSeek API将各种文件（PDF、Word、图片等）转换为结构化Markdown知识库笔记。

## 特性

- ✅ 支持多种文件格式：PDF、Word、图片、纯文本、Markdown
- ✅ 智能文件命名：以生成的主标题命名输出文件
- ✅ 结构化输出：严格遵循知识库笔记格式
- ✅ 独立提示词：提示词模板存储在独立文件夹
- ✅ 处理报告：自动生成处理统计报告

## 快速开始

### 1. 配置API密钥

**方法一：使用.env配置文件（推荐）**

```powershell
# 复制配置模板
copy .env.example .env

# 编辑.env文件，填入你的API密钥
# DEEPSEEK_API_KEY=your_deepseek_api_key_here
```

**方法二：使用环境变量**

```powershell
# 临时设置（仅当前会话）
$env:DEEPSEEK_API_KEY="your_deepseek_api_key_here"

# 或永久设置（Windows系统变量，需要重启终端生效）
setx DEEPSEEK_API_KEY "your_deepseek_api_key_here"
```

### 2. 安装依赖

```powershell
# 安装Python依赖包
python -m pip install -r requirements.txt
```

### 3. 创建知识库链接

```powershell
# 创建符号链接到你的知识库目录
mklink /D knowledge_base_link "D:\knowledge_base"
```

### 4. 一键运行

```powershell
# 使用PowerShell脚本（推荐）
.\process_knowledge.ps1

# 或直接使用Python脚本
python knowledge_processor.py
```

### 5. 查看结果

```powershell
# 查看生成的Markdown文件
dir processed_knowledge\

# 查看处理报告
Get-Content processed_knowledge\processing_report.md
```

## 配置说明

系统支持通过.env文件配置各种参数，无需修改代码：

```bash
# DeepSeek API密钥（必需）
DEEPSEEK_API_KEY=your_api_key_here

# 输入目录（可选，默认：knowledge_base_link）
INPUT_DIR=knowledge_base_link

# 输出目录（可选，默认：processed_knowledge）
OUTPUT_DIR=processed_knowledge

# API模型（可选，默认：deepseek-chat）
API_MODEL=deepseek-chat

# 最大Token数（可选，默认：4000）
MAX_TOKENS=4000

# 温度参数（可选，默认：0.3）
TEMPERATURE=0.3

# API调用间隔秒数（可选，默认：2）
API_DELAY=2

# 最大内容长度字符数（可选，默认：50000）
MAX_CONTENT_LENGTH=50000
```

## 文件格式支持

- **文本文件**：.txt, .md, .markdown
- **文档文件**：.pdf, .doc, .docx
- **图片文件**：.jpg, .jpeg, .png, .gif, .bmp

## 输出格式

每个处理后的文件将按照以下结构化格式输出：

```
# 主标题（从内容中提取）

主题概述
120-150字的概述...

结构化笔记
### 章节1
1. 要点1
2. 要点2

### 章节2
1. 要点1
2. 要点2

核心要点
- **要点1** 描述...
- **要点2** 描述...

行动步骤
1. 步骤1
2. 步骤2

推荐归档路径
领域/细分方向/核心主题

关联主题
- 主题1
- 主题2

复习提示
1. 提示1
2. 提示2

标签
#标签1 #标签2 #标签3
```

## 文件名规则

1. 处理器会自动从生成的Markdown中提取主标题
2. 清理标题中的非法字符（<>:"/\|?*等）
3. 空格和斜杠替换为下划线
4. 如果无法提取标题，使用原始文件名
5. 自动处理文件名冲突

## 提示词定制

如需修改处理逻辑，编辑 `prompts/knowledge_prompt.md` 文件。

## 处理报告

处理完成后会生成 `processed_knowledge/processing_report.md`，包含：
- 处理时间和统计
- 成功处理的文件列表
- 处理失败的文件列表

## 注意事项

1. **文件大小限制**：单个文件最大50MB
2. **API限制**：处理间隔2秒以避免限流
3. **输出目录**：`processed_knowledge/` 自动创建
4. **文件数量**：建议每次处理不超过100个文件

## 故障排除

### 常见问题

1. **PowerShell脚本乱码**：脚本已改用英文显示，避免中文编码问题
2. **API密钥错误**：确认已在.env文件中正确设置 `DEEPSEEK_API_KEY` 或设置了环境变量
3. **文件访问错误**：确认 `knowledge_base_link` 符号链接有效
4. **API调用失败**：检查网络连接和API配额
5. **Python依赖问题**：运行 `python -m pip install -r requirements.txt` 安装所需依赖
6. **.env文件未生效**：确保已安装python-dotenv包，并检查.env文件格式正确

### 日志输出示例

```powershell
Checking Python dependencies...
Prompt template loaded
API Model: deepseek-chat
Max Tokens: 4000
Temperature: 0.3
Found 2 files

==================================================
Processing file: 参考日推 138｜我们是如何感知时间的？.pdf
Extracting PDF text...
PDF text truncated to 50000 characters
Calling API to process: 参考日推 138｜我们是如何感知时间的？.pdf
Extracted title: 时间感知的神经机制与心理学研究
Saved as: 时间感知的神经机制与心理学研究.md

==================================================
Processing file: 参考日推 247｜实践本身就是目标.pdf
Extracting PDF text...
Calling API to process: 参考日推 247｜实践本身就是目标.pdf
Extracted title: 实践导向的生活哲学：在行动中寻找意义
Saved as: 实践导向的生活哲学：在行动中寻找意义.md

==================================================
Processing completed!
Output directory: processed_knowledge
Processing report: processed_knowledge\processing_report.md

Generated Markdown files:
  - 时间感知的神经机制与心理学研究.md
  - 实践导向的生活哲学：在行动中寻找意义.md
```

## 性能优化

- 大型PDF文件可能会分段处理
- 图片OCR通过DeepSeek多模态API完成
- 文本文件优先使用文本模式传输，避免base64开销
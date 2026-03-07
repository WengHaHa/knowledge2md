# Knowledge2MD

一个智能知识库文件处理器，使用DeepSeek API将各种文件转换为结构化Markdown知识库笔记。

## ✨ 特性

- 📁 **多格式支持**：PDF、Word、图片、纯文本、Markdown
- ⚡ **并发处理**：多线程加速，大幅缩短处理时间
- 🔄 **增量处理**：只处理新增或修改的文件
- 🧹 **内容去重**：自动检测相似内容避免重复
- ⭐ **质量评分**：多维度评估生成内容的质量
- 📝 **智能命名**：以生成的主标题命名输出文件
- 📊 **处理报告**：自动生成处理统计报告
- 🌐 **Web界面**：直观的Vue 3前端界面

## 🚀 快速开始

### 1. 安装依赖

```bash
# 安装Python依赖
python -m pip install -r requirements.txt

# 安装Node.js依赖
npm install
```

### 2. 运行应用

```bash
# 双击运行启动脚本
start.bat

# 或在PowerShell中执行
start.bat
```

### 3. 配置与使用

1. 在浏览器中打开 `http://localhost:5173`
2. 输入你的DeepSeek API密钥并保存配置
3. 点击"开始处理"按钮开始处理文件
4. 在日志界面查看处理进度和结果

## 📁 项目结构

```
knowledge2md/
├── knowledge_input/   # 待处理文件目录
├── knowledge_output/   # 处理完成的Markdown文件
├── prompts/              # 提示词模板
├── src/                 # 前端代码
│   ├── App.vue          # 主界面
│   └── main.js          # 入口文件
├── .env.example         # 环境变量示例
├── knowledge2md.db      # SQLite配置数据库
├── knowledge_processor.py  # 核心处理逻辑
├── main.py              # FastAPI后端
├── package.json         # Node.js依赖
├── requirements.txt     # Python依赖
├── start.bat            # 启动脚本
└── vite.config.js       # Vite配置
```

## 🔧 核心配置

配置通过Web界面设置并存储在SQLite数据库中：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `DEEPSEEK_API_KEY` | DeepSeek API密钥（必需） | - |
| `CONCURRENT_PROCESSING` | 启用并发处理 | true |
| `MAX_WORKERS` | 并发工作线程数 | 3 |
| `INCREMENTAL_PROCESSING` | 启用增量处理 | true |
| `ENABLE_DEDUPLICATION` | 启用内容去重 | true |
| `DEDUPLICATION_THRESHOLD` | 去重相似度阈值 | 0.85 |
| `ENABLE_QUALITY_SCORING` | 启用质量评分 | true |

## 📝 使用说明

1. **添加文件**：将需要处理的文件放入 `knowledge_input` 目录
2. **配置API**：在Web界面输入DeepSeek API密钥并保存
3. **开始处理**：点击"开始处理"按钮
4. **查看结果**：处理完成后，在 `knowledge_output` 目录查看生成的Markdown文件
5. **查看日志**：Web界面会显示详细的处理日志和进度


## 🛠️ 技术栈

- **后端**：Python 3.9+, FastAPI, SQLite
- **前端**：Vue 3, Vite, JavaScript
- **API**：DeepSeek API
- **处理**：多线程并发处理
- **存储**：SQLite数据库

## 📄 许可证

MIT License - 详见 [LICENSE](LICENSE) 文件

## 🤝 贡献

欢迎提交Issue和Pull Request！

## 📞 支持

如果遇到问题，请检查日志输出或提交Issue。

# Knowledge2MD

一个智能知识库文件处理器，使用DeepSeek API将各种文件转换为结构化Markdown知识库笔记。支持扫描版PDF的OCR文本提取，内置中文语言识别能力。

## ✨ 特性

- 📁 **多格式支持**：PDF、Word、图片、纯文本、Markdown
- 🔤 **OCR智能识别**：自动识别扫描版PDF，支持中英文混合识别
- ⚡ **并发处理**：多线程加速，大幅缩短处理时间
- 🔄 **增量处理**：只处理新增或修改的文件
- 🧹 **内容去重**：自动检测相似内容避免重复
- ⭐ **质量评分**：多维度评估生成内容的质量
- 📝 **智能命名**：以生成的主标题命名输出文件
- 📊 **处理报告**：自动生成处理统计报告
- 🌐 **Web界面**：直观的Vue 3前端界面
- 🔧 **双引擎OCR**：pdf2image + PyMuPDF双备份，确保可靠性

## 🖥️ 系统要求

### 基础要求
- **操作系统**：Windows 10/11, macOS, Linux
- **Python**：3.8 或更高版本
- **Node.js**：16 或更高版本（用于前端）
- **内存**：至少 4GB（处理大型PDF建议8GB+）

### OCR专用要求
- **Tesseract OCR**：5.0 或更高版本
- **Poppler工具**：用于PDF转图像（Windows用户需要单独安装）
- **磁盘空间**：至少500MB（用于存储语言包和临时文件）

## 🚀 快速开始

### 1. 安装Python依赖

```bash
# 安装所有Python依赖（包括OCR相关）
python -m pip install -r requirements.txt

# 或者手动安装核心依赖
python -m pip install fastapi uvicorn pypdf requests python-dotenv pytz
python -m pip install pytesseract pdf2image pillow PyMuPDF
```

### 2. 安装Node.js依赖

```bash
# 安装前端依赖
npm install
```

### 3. 运行应用

```bash
# Windows：双击运行启动脚本
start.bat

# 或在终端中执行
start.bat

# 手动启动（两个终端分别运行）
# 终端1：启动后端API
python main.py

# 终端2：启动前端开发服务器
npm run dev
```

### 4. 访问应用

1. 在浏览器中打开 `http://localhost:3000`（前端）
2. 输入你的DeepSeek API密钥并保存配置
3. 将需要处理的文件放入 `knowledge_input` 目录
4. 点击"开始处理"按钮开始处理文件
5. 在日志界面查看处理进度和结果

## 🔤 OCR功能安装指南

### Windows用户安装Tesseract OCR

#### 方法一：使用winget（推荐）
```powershell
# 安装Tesseract OCR引擎
winget install --source winget UB-Mannheim.TesseractOCR

# 检查安装是否成功
tesseract --version
```

#### 方法二：手动安装
1. 下载Tesseract安装程序：
   - 访问：https://github.com/UB-Mannheim/tesseract/wiki
   - 下载最新Windows版本（如 `tesseract-ocr-w64-setup-5.4.0.20240606.exe`）
2. 运行安装程序，记下安装路径（默认：`C:\Program Files\Tesseract-OCR`）
3. 确保将Tesseract添加到系统PATH

### 安装中文语言包

#### 自动安装（已集成）
系统会自动检测并下载中文语言包。如果自动安装失败，可手动安装：

```powershell
# 下载中文语言包
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$url = "https://raw.githubusercontent.com/tesseract-ocr/tessdata/main/chi_sim.traineddata"
$output = "C:\Program Files\Tesseract-OCR\tessdata\chi_sim.traineddata"
Invoke-WebRequest -Uri $url -OutFile $output -UseBasicParsing

# 验证语言包
tesseract --list-langs
# 应该能看到：chi_sim, eng, osd
```

### 安装Poppler工具（Windows）
```powershell
# 使用winget安装Poppler
winget install --source winget oschwartz10612.Poppler

# 验证安装（重启终端后）
pdftoppm -v
```

### 验证OCR安装
```bash
# 检查Tesseract版本
tesseract --version

# 检查可用语言包
tesseract --list-langs

# 检查Python OCR依赖
python -c "import pytesseract; import pdf2image; import fitz; print('✅ OCR依赖安装成功')"
```

## 📁 项目结构

```
knowledge2md/
├── knowledge_input/          # 待处理文件目录
├── knowledge_output/         # 处理完成的Markdown文件
├── prompts/                  # 提示词模板
│   └── knowledge_prompt.md   # 知识库生成提示词
├── src/                      # 前端代码
│   ├── App.vue              # 主界面
│   └── main.js              # 入口文件
├── .env.example              # 环境变量示例
├── .gitignore               # Git忽略配置
├── LICENSE                  # MIT许可证
├── README.md                # 项目说明文档
├── index.html               # 前端HTML入口
├── knowledge_processor.py   # 核心处理逻辑（含OCR）
├── main.py                  # FastAPI后端
├── package.json             # Node.js依赖配置
├── package-lock.json        # 依赖锁文件
├── requirements.txt         # Python依赖配置（已更新）
├── start.bat                # Windows启动脚本
└── vite.config.js           # Vite构建配置
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
| `ENABLE_OCR` | 启用OCR功能（自动检测） | true |

## 📝 使用说明

### 1. 准备文件
- 将需要处理的文件放入 `knowledge_input` 目录
- 支持格式：PDF（含扫描版）、Word(.docx)、图片、纯文本、Markdown
- 扫描版PDF会自动启用OCR功能

### 2. 配置API密钥
- 在Web界面输入有效的DeepSeek API密钥
- 点击"保存配置"按钮
- API密钥会安全存储在本地SQLite数据库中

### 3. 开始处理
- 点击"开始处理"按钮
- 系统会自动检测文件类型并选择合适的处理方式：
  - 可编辑PDF：直接提取文本
  - 扫描版PDF：自动启用OCR提取文本
  - 其他格式：按相应方式处理

### 4. 查看结果
- 处理完成后，在 `knowledge_output` 目录查看生成的Markdown文件
- 文件以生成的主标题命名，便于整理
- 每个文件包含完整的结构化知识库笔记

### 5. 查看日志和进度
- Web界面实时显示处理日志
- 显示当前处理进度和剩余时间
- 所有日志均使用北京时间（UTC+8）
- 错误信息会明确显示，便于问题诊断

## 🔍 OCR处理流程

### 自动检测流程
1. **常规文本提取**：首先尝试使用pypdf提取PDF文本
2. **文本验证**：检查提取的文本是否有效（非垃圾数据）
3. **OCR备用方案**：如果常规提取失败，自动启用OCR
4. **双引擎切换**：pdf2image失败时自动切换到PyMuPDF
5. **语言检测**：自动检测并使用中文语言包（chi_sim+eng）

### 性能特点
- **处理速度**：OCR处理较慢（每页约2-4秒）
- **识别准确率**：中文约40-60%（受扫描质量影响）
- **内存占用**：处理大型PDF时内存占用较高
- **自动降级**：确保即使部分组件失败也能继续处理

## 🛠️ 故障排除

### 常见问题1：OCR依赖未安装
```
ImportError: No module named 'pytesseract'
```
**解决方案**：
```bash
pip install pytesseract pdf2image pillow PyMuPDF
```

### 常见问题2：Tesseract未找到
```
TesseractNotFoundError: tesseract is not installed or it's not in your PATH
```
**解决方案**：
1. 确认Tesseract已正确安装
2. 将Tesseract安装目录添加到系统PATH
3. 重启终端或IDE

### 常见问题3：中文语言包缺失
```
Error opening data file chi_sim.traineddata
```
**解决方案**：
1. 手动下载中文语言包（见上文安装指南）
2. 放置到：`C:\Program Files\Tesseract-OCR\tessdata\`

### 常见问题4：PDF转换失败
```
pdf2image.exceptions.PDFPageCountError: Unable to get page count.
```
**解决方案**：
1. 系统已自动切换到PyMuPDF引擎
2. 确保PDF文件未损坏
3. 尝试用其他PDF阅读器打开文件

### 常见问题5：API认证失败
```
401 Client Error: Unauthorized
```
**解决方案**：
1. 检查DeepSeek API密钥是否正确
2. 确认API密钥有足够余额
3. 在DeepSeek平台检查API使用状态

## 🛠️ 技术栈

- **后端**：Python 3.8+, FastAPI, SQLite, Uvicorn
- **前端**：Vue 3, Vite, JavaScript, CSS3
- **PDF处理**：pypdf, PyMuPDF (fitz)
- **OCR引擎**：Tesseract OCR 5.4+, pytesseract, pdf2image
- **图像处理**：Pillow (PIL)
- **API集成**：DeepSeek API, Requests
- **并发处理**：ThreadPoolExecutor, asyncio
- **配置管理**：python-dotenv, SQLite
- **进度显示**：tqdm（后端），自定义前端进度条
- **数据可视化**：matplotlib（统计图表）

## 📄 许可证

MIT License - 详见 [LICENSE](LICENSE) 文件

## 🤝 贡献

欢迎提交Issue和Pull Request！

### 开发指南
1. Fork本仓库
2. 创建功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 打开Pull Request

### 待开发功能
- [ ] 支持更多OCR语言包
- [ ] 添加PDF预处理功能（去噪、增强）
- [ ] 支持批量处理配置
- [ ] 添加云存储集成
- [ ] 实现处理队列管理

## 📞 支持

如果遇到问题：

1. **查看日志**：Web界面和终端输出有详细日志
2. **检查依赖**：确保所有依赖包已正确安装
3. **查看文档**：仔细阅读本README文档
4. **提交Issue**：在GitHub仓库提交问题报告
5. **社区支持**：在相关技术社区寻求帮助

## 🔄 更新日志

### v1.1.0（当前版本）
- ✅ 集成Tesseract OCR引擎
- ✅ 支持扫描版PDF的中英文识别
- ✅ 自动检测和安装中文语言包
- ✅ 双引擎OCR备份（pdf2image + PyMuPDF）
- ✅ 完善错误处理和降级机制
- ✅ 更新依赖列表和安装指南

### v1.0.0
- 初始版本发布
- 支持多格式文件处理
- Web界面和API集成
- 并发处理和增量处理

---

**提示**：OCR处理需要时间，请耐心等待大型PDF的处理完成。系统会自动优化处理流程，确保最佳性能和可靠性。
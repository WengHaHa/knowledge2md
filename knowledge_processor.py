#!/usr/bin/env python3
"""
Knowledge Base File Processor - Enhanced version with concurrency, incremental processing, deduplication, and quality scoring
"""

import os
import sys

# 设置环境变量，确保print函数使用utf-8编码
os.environ['PYTHONIOENCODING'] = 'utf-8'

import base64
import json
import requests
import hashlib
from pathlib import Path
import time
import datetime
import pytz
import re
import pypdf
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO

# 获取北京地区的当前时间
def get_beijing_time():
    beijing_tz = pytz.timezone('Asia/Shanghai')
    return datetime.datetime.now(beijing_tz).strftime('%Y-%m-%d %H:%M:%S')

# 新增：进度条和图表库
try:
    from tqdm import tqdm
except ImportError:
    tqdm = None

# matplotlib 会在需要时动态导入
plt = None
matplotlib = None

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def read_prompt_template():
    # 使用绝对路径来确保找到提示词模板文件
    prompt_file = Path(__file__).parent / "prompts" / "knowledge_prompt.md"
    if not prompt_file.exists():
        # 安全输出，避免编码错误
        try:
            print(f"Error: Prompt file not found at {prompt_file}")
        except Exception:
            print("Error: Prompt file not found")
        return "请分析以下内容，提取关键信息，并按照Markdown格式组织成结构化的知识库文档。"
    
    with open(prompt_file, 'r', encoding='utf-8') as f:
        prompt_template = f.read()
    
    prompt_template = prompt_template.replace("请用Markdown代码块输出，即用三个反引号包裹你的整个回答。", "")
    return prompt_template.strip()


def extract_main_title(markdown_content):
    lines = markdown_content.splitlines()
    in_code_block = False
    
    for line in lines:
        if line.strip().startswith('```'):
            in_code_block = not in_code_block
            continue
        
        if not in_code_block:
            match = re.match(r'^#\s+(.+)$', line.strip())
            if match:
                title = match.group(1).strip()
                title = re.sub(r'[<>:"/\\|?*]', '', title)
                title = title.replace(' ', '_').replace('/', '_')
                if len(title) > 100:
                    title = title[:100]
                return title
    
    return None


def truncate_content(content, max_length, content_type):
    if len(content) > max_length:
        content = content[:max_length]
        print(f"{content_type} truncated to {len(content)} characters")
    return content


def extract_docx_text(file_content):
    try:
        from docx import Document
        doc = Document(BytesIO(file_content))
        text = []
        for para in doc.paragraphs:
            text.append(para.text)
        return '\n'.join(text)
    except ImportError:
        print("python-docx not installed, falling back to base64")
        return None
    except Exception as e:
        print("DOCX extraction failed:", e)
        return None


def process_image(image_content):
    try:
        from PIL import Image
        img = Image.open(BytesIO(image_content))
        return img
    except ImportError:
        print("Pillow not installed, using original image")
        return None
    except Exception as e:
        print("Image processing failed:", e)
        return None


def get_file_type(file_content):
    try:
        import magic
        mime = magic.Magic(mime=True)
        return mime.from_buffer(file_content)
    except ImportError:
        print("python-magic not installed, using file extension")
        return None
    except Exception:
        return None


def validate_extracted_text(text):
    """
    验证提取的文本是否有效（不是垃圾数据）
    检测base64占位符、重复字符等无效内容
    """
    if not text:
        return None
    
    text_lower = text.lower()
    
    # 检测base64相关标记
    if "data:application/pdf;base64" in text_lower:
        return None
    
    # 检测大量重复字符模式（base64特征）
    import re
    # 匹配连续重复的字符序列（如 AAAAA, aaaa, 0000）
    repeated_pattern = re.findall(r'(.)\1{20,}', text)
    if len(repeated_pattern) > 5:  # 超过5种重复字符模式
        return None
    
    # 检测base64特征字符比例
    base64_chars = set('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=')
    base64_count = sum(1 for c in text if c in base64_chars)
    if len(text) > 100 and base64_count / len(text) > 0.8:  # 超过80%是base64字符
        return None
    
    # 检查是否有实际的中文或英文单词
    chinese_chars = re.findall(r'[\u4e00-\u9fff]+', text)
    english_words = re.findall(r'[a-zA-Z]{3,}', text)
    
    # 如果既没有中文也没有英文单词，可能是垃圾
    if not chinese_chars and not english_words:
        return None
    
    return text


def extract_pdf_text_with_ocr(file_content, log_callback=None):
    """
    使用OCR提取PDF文本（扫描版PDF）
    """
    try:
        from PIL import Image
        import pytesseract
        from pdf2image import convert_from_bytes
        
        # 设置Tesseract可执行文件路径
        tesseract_path = os.environ.get('TESSERACT_PATH', 'C:\\Program Files\\Tesseract-OCR\\tesseract.exe')
        if os.path.exists(tesseract_path):
            pytesseract.pytesseract.tesseract_cmd = tesseract_path
        else:
            # 尝试在PATH中查找
            import shutil
            tesseract_cmd = shutil.which('tesseract')
            if tesseract_cmd:
                pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        
        # 检查中文语言包是否可用
        lang = 'eng'  # 默认英语
        try:
            # 尝试列出已安装的语言包
            import subprocess
            cmd = [pytesseract.pytesseract.tesseract_cmd, '--list-langs']
            result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore')
            if 'chi_sim' in result.stdout:
                lang = 'chi_sim+eng'
        except Exception:
            pass
        
        if log_callback:
            log_callback(f"[{get_beijing_time()}] 使用OCR提取PDF文本...")
        else:
            print(f"[{get_beijing_time()}] Using OCR to extract PDF text...")
        
        # 将PDF转换为图片
        # 设置Poppler路径
        poppler_path = os.environ.get('POPPLER_PATH')
        if not poppler_path:
            # 默认安装路径（winget安装）
            local_appdata = os.environ.get('LOCALAPPDATA', 'C:\\Users\\Administrator\\AppData\\Local')
            poppler_path = os.path.join(local_appdata, 'Microsoft', 'WinGet', 'Packages', 'oschwartz10612.Poppler_Microsoft.Winget.Source_8wekyb3d8bbwe', 'poppler-25.07.0', 'Library', 'bin')
            if not os.path.exists(poppler_path):
                poppler_path = None
        
        if poppler_path and os.path.exists(poppler_path):
            images = convert_from_bytes(file_content, poppler_path=poppler_path)
            if log_callback:
                log_callback(f"[{get_beijing_time()}] 使用Poppler路径: {poppler_path}")
        else:
            images = convert_from_bytes(file_content)
            if log_callback:
                log_callback(f"[{get_beijing_time()}] 使用系统PATH中的Poppler")
        
        full_text = ""
        for i, image in enumerate(images):
            if log_callback:
                log_callback(f"[{get_beijing_time()}] OCR识别第 {i+1}/{len(images)} 页...")
            
            text = pytesseract.image_to_string(image, lang=lang)
            full_text += f"\n--- Page {i+1} ---\n"
            full_text += text + "\n"
        
        return full_text.strip() if full_text.strip() else None
        
    except ImportError as e:
        if log_callback:
            log_callback(f"[{get_beijing_time()}] OCR依赖未安装: {e}")
        else:
            print(f"[{get_beijing_time()}] OCR dependency not installed: {e}")
        return None
    except Exception as e:
        if log_callback:
            log_callback(f"[{get_beijing_time()}] pdf2image OCR提取失败，尝试PyMuPDF: {str(e)}")
        else:
            print(f"[{get_beijing_time()}] pdf2image OCR extraction failed, trying PyMuPDF: {e}")
        # 尝试使用PyMuPDF进行OCR
        return extract_pdf_text_with_fitz_ocr(file_content, log_callback)


def extract_pdf_text_with_fitz_ocr(file_content, log_callback=None):
    """
    使用PyMuPDF (fitz) 和 OCR 提取PDF文本
    """
    try:
        import fitz  # PyMuPDF
        from PIL import Image
        import pytesseract
        
        # 设置Tesseract可执行文件路径
        tesseract_path = os.environ.get('TESSERACT_PATH', 'C:\\Program Files\\Tesseract-OCR\\tesseract.exe')
        if os.path.exists(tesseract_path):
            pytesseract.pytesseract.tesseract_cmd = tesseract_path
        else:
            import shutil
            tesseract_cmd = shutil.which('tesseract')
            if tesseract_cmd:
                pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        
        # 检查中文语言包是否可用
        lang = 'eng'  # 默认英语
        try:
            import subprocess
            cmd = [pytesseract.pytesseract.tesseract_cmd, '--list-langs']
            result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore')
            if 'chi_sim' in result.stdout:
                lang = 'chi_sim+eng'
        except Exception:
            pass
        
        if log_callback:
            log_callback(f"[{get_beijing_time()}] 使用PyMuPDF进行OCR提取...")
        
        # 打开PDF
        doc = fitz.open(stream=file_content, filetype="pdf")
        full_text = ""
        
        for page_num in range(len(doc)):
            if log_callback:
                log_callback(f"[{get_beijing_time()}] OCR识别第 {page_num+1}/{len(doc)} 页...")
            
            page = doc[page_num]
            # 渲染页面为图像（300 DPI）
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # 2倍缩放
            img_data = pix.tobytes("ppm")
            
            # 转换为PIL图像
            import io
            img = Image.open(io.BytesIO(img_data))
            
            # OCR识别
            text = pytesseract.image_to_string(img, lang=lang)
            full_text += f"\n--- Page {page_num+1} ---\n"
            full_text += text + "\n"
        
        doc.close()
        return full_text.strip() if full_text.strip() else None
        
    except ImportError as e:
        if log_callback:
            log_callback(f"[{get_beijing_time()}] PyMuPDF或OCR依赖未安装: {e}")
        return None
    except Exception as e:
        if log_callback:
            log_callback(f"[{get_beijing_time()}] PyMuPDF OCR提取失败: {str(e)}")
        return None


def extract_pdf_text(file_content):
    try:
        pdf_file = BytesIO(file_content)
        reader = pypdf.PdfReader(pdf_file)
        text = ""
        
        for page_num, page in enumerate(reader.pages):
            page_text = page.extract_text()
            if page_text:
                text += "\n--- Page " + str(page_num+1) + " ---.\n"
                text += page_text + "\n"
        
        return text.strip()
    except Exception as e:
        # 安全输出，避免编码错误
        try:
            print("PDF text extraction failed:", e)
        except Exception:
            print("PDF text extraction failed: [Error message encoding error]")
        return None


def handle_api_error(e, log_callback=None):
    error_msg = None
    try:
        if isinstance(e, requests.exceptions.HTTPError):
            if e.response.status_code == 401:
                error_msg = "API认证失败(401)，请检查API密钥是否有效"
            elif e.response.status_code == 429:
                error_msg = "API请求频率超限(429)，请稍后重试"
            else:
                # 安全处理响应文本，避免编码错误
                try:
                    response_text = e.response.text[:200]
                    # 尝试解析JSON错误信息
                    try:
                        error_json = e.response.json()
                        if isinstance(error_json, dict) and 'error' in error_json:
                            error_detail = error_json['error']
                            if isinstance(error_detail, dict) and 'message' in error_detail:
                                error_message = error_detail['message']
                                error_msg = f"API错误 HTTP {e.response.status_code}: {error_message}"
                                
                                # 针对特定错误类型提供更详细的解释
                                if 'Content Exists Risk' in error_message:
                                    error_msg += "\n可能原因：API认为内容存在风险（可能包含敏感内容）。\n建议：\n1. 检查PDF内容是否包含敏感信息\n2. 尝试处理其他PDF文件\n3. 或联系DeepSeek支持"
                                elif 'invalid_request_error' in error_message:
                                    error_msg += "\n可能原因：API请求格式错误。"
                                else:
                                    error_msg = f"API错误 HTTP {e.response.status_code}: {error_message}"
                            else:
                                error_msg = f"API错误 HTTP {e.response.status_code}: {response_text}"
                        else:
                            error_msg = f"API错误 HTTP {e.response.status_code}: {response_text}"
                    except Exception:
                        # 如果不是JSON，使用原始文本
                        error_msg = f"API错误 HTTP {e.response.status_code}: {response_text}"
                except Exception:
                    error_msg = f"API错误 HTTP {e.response.status_code}"
        else:
            # 安全处理错误信息，避免编码错误
            try:
                error_msg = str(e)
            except Exception:
                error_msg = "API请求发生错误"
    except Exception:
        error_msg = "API请求发生未知错误"
    
    # 输出错误信息
    if log_callback:
        log_callback(f"[{get_beijing_time()}] {error_msg}")
    else:
        try:
            print(f"[{get_beijing_time()}] {error_msg}")
        except Exception:
            print(f"[{get_beijing_time()}] API Error (encoding issue)")
    
    return error_msg


def compute_content_hash(content):
    return hashlib.md5(content.encode('utf-8')).hexdigest()


def compute_similarity(text1, text2):
    words1 = set(text1.lower().split())
    words2 = set(text2.lower().split())
    if not words1 or not words2:
        return 0.0
    intersection = len(words1.intersection(words2))
    union = len(words1.union(words2))
    return intersection / union


def load_processing_state(output_dir):
    state_file = Path(output_dir) / ".processing_state.json"
    if state_file.exists():
        try:
            with open(state_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {"processed_files": {}, "content_hashes": {}}


def save_processing_state(output_dir, state):
    state_file = Path(output_dir) / ".processing_state.json"
    with open(state_file, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def is_file_modified(file_path, state):
    file_info = state.get("processed_files", {}).get(str(file_path))
    if not file_info:
        return True
    mtime = Path(file_path).stat().st_mtime
    return mtime > file_info.get("processed_at", 0)


def is_duplicate_content(text_content, state, threshold=0.85):
    for existing_hash, existing_text in state.get("content_hashes", {}).items():
        similarity = compute_similarity(text_content, existing_text)
        if similarity >= threshold:
            return True, similarity
    return False, 0.0


def score_content_quality(markdown_content):
    scores = {}
    
    lines = markdown_content.splitlines()
    
    scores["structure"] = min(10, len([l for l in lines if l.strip().startswith('#')]) * 2)
    scores["completeness"] = min(10, len(lines) // 10)
    scores["readability"] = min(10, max(0, 10 - len([l for l in lines if len(l) > 200]) // 5))
    
    total_score = sum(scores.values())
    scores["overall"] = round(total_score / 3, 1)
    
    return scores


def generate_statistics_chart(all_files, skipped_files, processed_files, failed_files, output_dir, log_callback=None):
    """生成处理统计的可视化图表"""
    global plt, matplotlib
    
    # 动态导入 matplotlib
    if plt is None:
        try:
            import matplotlib.pyplot as plt
            import matplotlib
            # 设置中文字体
            matplotlib.rcParams['font.sans-serif'] = ['SimHei']  # 用来正常显示中文标签
            matplotlib.rcParams['axes.unicode_minus'] = False  # 用来正常显示负号
        except ImportError:
            if log_callback:
                log_callback(f"[{get_beijing_time()}] 警告: matplotlib 未安装，跳过图表生成")
            else:
                print(f"[{get_beijing_time()}] Warning: matplotlib not installed, skipping chart generation")
            return
    
    try:
        # 检查是否在主线程中
        import threading
        if threading.current_thread().name != 'MainThread':
            if log_callback:
                log_callback(f"[{get_beijing_time()}] 警告: 在非主线程中，跳过图表生成")
            else:
                print(f"[{get_beijing_time()}] Warning: Not in main thread, skipping chart generation")
            return
        
        labels = ['成功', '失败', '跳过']
        sizes = [len(processed_files), len(failed_files), len(skipped_files)]
        colors = ['#4CAF50', '#F44336', '#FFC107']
        explode = (0.1, 0, 0)
        
        plt.figure(figsize=(10, 6))
        
        # 饼图
        plt.subplot(121)
        plt.pie(sizes, explode=explode, labels=labels, colors=colors, autopct='%1.1f%%', shadow=True, startangle=140)
        plt.axis('equal')
        plt.title('处理结果分布')
        
        # 柱状图
        plt.subplot(122)
        categories = ['总文件数', '成功', '失败', '跳过']
        values = [len(all_files), len(processed_files), len(failed_files), len(skipped_files)]
        plt.bar(categories, values, color=['#2196F3', '#4CAF50', '#F44336', '#FFC107'])
        plt.ylabel('数量')
        plt.title('处理统计')
        plt.xticks(rotation=45)
        
        # 调整布局
        plt.tight_layout()
        
        # 保存图表（覆盖已存在的文件）
        chart_path = Path(output_dir) / "processing_statistics.png"
        # 确保目录存在
        chart_path.parent.mkdir(exist_ok=True)
        # 保存图表，覆盖已存在的文件
        plt.savefig(chart_path, dpi=100, bbox_inches='tight')
        plt.close()
        
        if log_callback:
            log_callback(f"[{get_beijing_time()}] 统计图表已保存: {chart_path}")
        else:
            print(f"[{get_beijing_time()}] \n统计图表已保存: {chart_path}")
        
    except Exception as e:
        if log_callback:
            log_callback(f"[{get_beijing_time()}] 生成图表失败: {e}")
        else:
            print(f"[{get_beijing_time()}] 生成图表失败: {e}")


def process_file_with_deepseek(api_key, file_path, prompt_template, api_model="deepseek-chat", max_tokens=4000, temperature=1.0, max_content_length=50000, log_callback=None):
    with open(file_path, 'rb') as f:
        file_content = f.read()
    
    file_ext = Path(file_path).suffix.lower()
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    extracted_text = None
    
    if file_ext == '.pdf':
        if log_callback:
            log_callback(f"[{get_beijing_time()}] 提取PDF文本...")
        else:
            print(f"[{get_beijing_time()}] Extracting PDF text...")
        pdf_text = extract_pdf_text(file_content)
        extracted_text = pdf_text
        
        # 检查PDF文本提取是否成功
        # 验证提取的内容是否是有效的文本（而非垃圾数据）
        pdf_text = validate_extracted_text(pdf_text)
        
        # 如果常规提取失败，尝试使用OCR
        if not pdf_text or pdf_text.strip() == "" or len(pdf_text.strip()) < 50:
            if log_callback:
                log_callback(f"[{get_beijing_time()}] 常规PDF文本提取失败，尝试使用OCR...")
            else:
                print(f"[{get_beijing_time()}] Regular PDF text extraction failed, trying OCR...")
            
            # 尝试使用OCR提取文本
            ocr_text = extract_pdf_text_with_ocr(file_content, log_callback)
            
            if ocr_text and len(ocr_text.strip()) >= 50:
                # OCR提取成功
                pdf_text = validate_extracted_text(ocr_text)
                if pdf_text:
                    if log_callback:
                        log_callback(f"[{get_beijing_time()}] OCR提取成功，长度: {len(pdf_text)} 字符")
                    else:
                        print(f"[{get_beijing_time()}] OCR extraction successful, length: {len(pdf_text)} chars")
                else:
                    # OCR提取的内容无效
                    if log_callback:
                        log_callback(f"[{get_beijing_time()}] OCR提取的内容无效")
                    else:
                        print(f"[{get_beijing_time()}] OCR extracted content invalid")
                    error_message = f"无法处理文件: {Path(file_path).name}\n原因: 无法提取PDF文本（扫描版PDF），OCR提取的内容无效\n解决方案:\n1. 安装OCR依赖: pip install pytesseract pdf2image pillow\n2. 下载Tesseract中文语言包\n3. 或手动转换为可编辑PDF"
                    return error_message, None
            else:
                # OCR提取失败或未安装
                if log_callback:
                    log_callback(f"[{get_beijing_time()}] 无法提取PDF文本，可能是扫描版PDF且OCR不可用")
                else:
                    print(f"[{get_beijing_time()}] Cannot extract PDF text, may be scanned PDF and OCR unavailable")
                error_message = f"无法处理文件: {Path(file_path).name}\n原因: 无法提取PDF文本（扫描版PDF）\n解决方案:\n1. 安装OCR依赖: pip install pytesseract pdf2image pillow\n2. 下载Tesseract中文语言包\n3. 或手动转换为可编辑PDF"
                return error_message, None
        
        # 无论通过常规提取还是OCR，继续处理有效的pdf_text
        pdf_text = truncate_content(pdf_text, max_content_length, "PDF text")
        if log_callback:
            log_callback(f"[{get_beijing_time()}] PDF文本提取成功，长度: {len(pdf_text)} 字符")
        else:
            print(f"[{get_beijing_time()}] PDF text extraction successful, length: {len(pdf_text)} chars")
        
        # 改进提示词，使用更清晰的消息结构
        # 系统消息：简化的指令，强调学术和非政治性
        system_message = """你是一个学术知识库笔记创建助手。你的任务是根据用户提供的文档内容，按照指定的格式要求创建结构化的知识库笔记。

请注意：
1. 这是一个纯粹的学术知识管理任务，不涉及任何政治立场或敏感话题
2. 文档内容仅用于个人知识库建设
3. 请专注于文档的信息结构和知识价值，不进行政治判断
4. 输出应专业、客观、中立

请根据文档内容创建知识库笔记。"""
        
        # 用户消息：使用传入的提示词模板，如果为空则使用默认格式
        if prompt_template and prompt_template.strip():
            # 使用传入的提示词模板
            user_message = f"{prompt_template}\n\n请分析以下文档内容，并严格按照上述格式创建知识库笔记：\n\n文档内容：\n{pdf_text}"
        else:
            # 使用简化的格式要求作为后备
            format_requirements = """请创建知识库笔记，严格遵循以下格式：

1. 主标题（精准概括核心内容）
2. 主题概述（120-150字，说明核心切入点、观点和结论）
3. 结构化笔记（按内容逻辑分章节，用列表拆解核心信息）
4. 核心要点（5-6条最具价值的结论或规律）
5. 行动步骤（4-5条具体可落地的实践指南）
6. 推荐归档路径（按「领域/细分方向/核心主题」层级格式）
7. 关联主题（5个左右相关延伸方向）
8. 复习提示（4条针对核心记忆点的快速回顾线索）
9. 标签（8-10个精准关键词，用#连接）

语言风格：专业、简洁、客观。输出纯Markdown格式。"""
            user_message = f"{format_requirements}\n\n请分析以下文档内容，并严格按照上述格式创建知识库笔记：\n\n文档内容：\n{pdf_text}"
        
        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message}
        ]
        
    elif file_ext in ['.docx', '.doc']:
        if log_callback:
            log_callback(f"[{get_beijing_time()}] 提取Word文档文本...")
        else:
            print(f"[{get_beijing_time()}] Extracting Word document text...")
        docx_text = extract_docx_text(file_content)
        extracted_text = docx_text
        
        if not docx_text or docx_text.strip() == "" or len(docx_text.strip()) < 50:
            if log_callback:
                log_callback(f"[{get_beijing_time()}] 无法提取Word文本或文本太短")
                log_callback(f"[{get_beijing_time()}] 提取到的文本长度: {len(docx_text) if docx_text else 0} 字符")
            else:
                print(f"[{get_beijing_time()}] Cannot extract Word text or text too short")
                print(f"[{get_beijing_time()}] Extracted text length: {len(docx_text) if docx_text else 0} chars")
            error_message = f"无法处理文件: {Path(file_path).name}\n原因: 无法提取Word文档文本或文本太短\n请尝试转换为其他格式后再处理"
            return error_message, None
        else:
            docx_text = truncate_content(docx_text, max_content_length, "Word text")
            if log_callback:
                log_callback(f"[{get_beijing_time()}] Word文本提取成功，长度: {len(docx_text)} 字符")
            else:
                print(f"[{get_beijing_time()}] Word text extraction successful, length: {len(docx_text)} chars")
            # 使用简化的系统消息
            system_message = "你是一个知识库笔记创建助手。请根据用户提供的文档内容，按照指定的格式要求创建结构化的知识库笔记。"
            
            # 用户消息：使用传入的提示词模板，如果为空则使用默认格式
            if prompt_template and prompt_template.strip():
                # 使用传入的提示词模板
                user_message = f"{prompt_template}\n\n请分析以下文档内容，并严格按照上述格式创建知识库笔记：\n\n文档内容：\n{docx_text}"
            else:
                # 使用简化的格式要求作为后备
                format_requirements = """请创建知识库笔记，严格遵循以下格式：

1. 主标题（精准概括核心内容）
2. 主题概述（120-150字，说明核心切入点、观点和结论）
3. 结构化笔记（按内容逻辑分章节，用列表拆解核心信息）
4. 核心要点（5-6条最具价值的结论或规律）
5. 行动步骤（4-5条具体可落地的实践指南）
6. 推荐归档路径（按「领域/细分方向/核心主题」层级格式）
7. 关联主题（5个左右相关延伸方向）
8. 复习提示（4条针对核心记忆点的快速回顾线索）
9. 标签（8-10个精准关键词，用#连接）

语言风格：专业、简洁、客观。输出纯Markdown格式。"""
                user_message = f"{format_requirements}\n\n请分析以下文档内容，并严格按照上述格式创建知识库笔记：\n\n文档内容：\n{docx_text}"
            
            messages = [
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message}
            ]
        
    elif file_ext in ['.txt', '.md']:
        text_content = file_content.decode('utf-8', errors='ignore')
        extracted_text = text_content
        
        # 检查文本是否有效
        if not text_content or text_content.strip() == "" or len(text_content.strip()) < 50:
            if log_callback:
                log_callback(f"[{get_beijing_time()}] 文本内容太短或为空")
                log_callback(f"[{get_beijing_time()}] 文本长度: {len(text_content) if text_content else 0} 字符")
            else:
                print(f"[{get_beijing_time()}] Text content too short or empty")
                print(f"[{get_beijing_time()}] Text length: {len(text_content) if text_content else 0} chars")
            error_message = f"无法处理文件: {Path(file_path).name}\n原因: 文本内容太短或为空\n请提供有效的文本内容"
            return error_message, None
        else:
            text_content = truncate_content(text_content, max_content_length, "Text content")
            if log_callback:
                log_callback(f"[{get_beijing_time()}] 文本内容有效，长度: {len(text_content)} 字符")
            else:
                print(f"[{get_beijing_time()}] Text content valid, length: {len(text_content)} chars")
            # 使用简化的系统消息
            system_message = "你是一个知识库笔记创建助手。请根据用户提供的文档内容，按照指定的格式要求创建结构化的知识库笔记。"
            
            # 用户消息：使用传入的提示词模板，如果为空则使用默认格式
            if prompt_template and prompt_template.strip():
                # 使用传入的提示词模板
                user_message = f"{prompt_template}\n\n请分析以下文档内容，并严格按照上述格式创建知识库笔记：\n\n文档内容：\n{text_content}"
            else:
                # 使用简化的格式要求作为后备
                format_requirements = """请创建知识库笔记，严格遵循以下格式：

1. 主标题（精准概括核心内容）
2. 主题概述（120-150字，说明核心切入点、观点和结论）
3. 结构化笔记（按内容逻辑分章节，用列表拆解核心信息）
4. 核心要点（5-6条最具价值的结论或规律）
5. 行动步骤（4-5条具体可落地的实践指南）
6. 推荐归档路径（按「领域/细分方向/核心主题」层级格式）
7. 关联主题（5个左右相关延伸方向）
8. 复习提示（4条针对核心记忆点的快速回顾线索）
9. 标签（8-10个精准关键词，用#连接）

语言风格：专业、简洁、客观。输出纯Markdown格式。"""
                user_message = f"{format_requirements}\n\n请分析以下文档内容，并严格按照上述格式创建知识库笔记：\n\n文档内容：\n{text_content}"
            
            messages = [
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message}
            ]
    
    elif file_ext in ['.jpg', '.jpeg', '.png']:
        if log_callback:
            log_callback(f"[{get_beijing_time()}] 处理图片...")
        else:
            print(f"[{get_beijing_time()}] Processing image...")
        process_image(file_content)
        
        base64_data = base64.b64encode(file_content).decode('utf-8')
        mime_type = 'image/jpeg' if file_ext in ['.jpg', '.jpeg'] else 'image/png'
        
        # 使用简化的系统消息
        system_message = "你是一个知识库笔记创建助手。请根据用户提供的图片内容，按照指定的格式要求创建结构化的知识库笔记。"
        
        # 用户消息：使用传入的提示词模板，如果为空则使用默认格式
        if prompt_template and prompt_template.strip():
            # 使用传入的提示词模板
            text_prompt = f"{prompt_template}\n\n请分析以下图片内容，并严格按照上述格式创建知识库笔记："
        else:
            # 使用简化的格式要求作为后备
            format_requirements = """请创建知识库笔记，严格遵循以下格式：

1. 主标题（精准概括核心内容）
2. 主题概述（120-150字，说明核心切入点、观点和结论）
3. 结构化笔记（按内容逻辑分章节，用列表拆解核心信息）
4. 核心要点（5-6条最具价值的结论或规律）
5. 行动步骤（4-5条具体可落地的实践指南）
6. 推荐归档路径（按「领域/细分方向/核心主题」层级格式）
7. 关联主题（5个左右相关延伸方向）
8. 复习提示（4条针对核心记忆点的快速回顾线索）
9. 标签（8-10个精准关键词，用#连接）

语言风格：专业、简洁、客观。输出纯Markdown格式。"""
            text_prompt = f"{format_requirements}\n\n请分析以下图片内容，并严格按照上述格式创建知识库笔记："
        
        user_content = [
            {"type": "text", "text": text_prompt},
            {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_data}"}}
        ]
        
        messages = [
            {"role": "system", "content": system_message},
            {
                "role": "user",
                "content": user_content
            }
        ]
        extracted_text = base64_data[:1000]
    
    else:
        if log_callback:
            log_callback(f"[{get_beijing_time()}] 不支持的文件类型: {file_ext}")
        else:
            print(f"[{get_beijing_time()}] Unsupported file type: {file_ext}")
        error_message = f"无法处理文件: {Path(file_path).name}\n原因: 不支持的文件类型 {file_ext}"
        return error_message, None
    
    payload = {
        "model": api_model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature
    }
    
    try:
        # 安全处理文件名，避免编码错误
        file_name = str(Path(file_path).name)
        if log_callback:
            log_callback(f"[{get_beijing_time()}] 调用API处理: {file_name}")
        else:
            # 安全输出，避免编码错误
            try:
                print(f"[{get_beijing_time()}] Calling API to process: {file_name}")
            except Exception:
                print(f"[{get_beijing_time()}] Calling API to process: [File name encoding error]")
        # 确保 payload 中的中文字符被正确编码
        import json
        response = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers=headers,
            data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
            timeout=120
        )
        response.raise_for_status()
        result = response.json()
        return result['choices'][0]['message']['content'], extracted_text
    except Exception as e:
        error_message = handle_api_error(e, log_callback)
        return error_message, None


def validate_config():
    config = {}
    
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        # 当作为模块使用时，不要退出，而是抛出异常
        # 这样调用者可以决定如何处理
        raise ValueError("DEEPSEEK_API_KEY not found in environment variables or .env file. Please set DEEPSEEK_API_KEY in .env file or environment variable.")
    config['api_key'] = api_key
    
    config['input_dir'] = os.environ.get("INPUT_DIR", "knowledge_input")
    config['output_dir'] = os.environ.get("OUTPUT_DIR", "knowledge_output")
    config['api_model'] = os.environ.get("API_MODEL", "deepseek-chat")
    
    try:
        config['max_tokens'] = int(os.environ.get("MAX_TOKENS", "4000"))
        config['temperature'] = float(os.environ.get("TEMPERATURE", "1.0"))
        config['api_delay'] = int(os.environ.get("API_DELAY", "2"))
        config['max_content_length'] = int(os.environ.get("MAX_CONTENT_LENGTH", "50000"))
        
        config['concurrent_processing'] = os.environ.get("CONCURRENT_PROCESSING", "false").lower() == "true"
        config['max_workers'] = int(os.environ.get("MAX_WORKERS", "3"))
        
        config['incremental_processing'] = os.environ.get("INCREMENTAL_PROCESSING", "true").lower() == "true"
        
        config['enable_deduplication'] = os.environ.get("ENABLE_DEDUPLICATION", "true").lower() == "true"
        config['deduplication_threshold'] = float(os.environ.get("DEDUPLICATION_THRESHOLD", "0.85"))
        
        config['enable_quality_scoring'] = os.environ.get("ENABLE_QUALITY_SCORING", "true").lower() == "true"
        
    except ValueError as e:
        raise ValueError(f"Invalid configuration value: {e}")
    
    if config['max_tokens'] < 100 or config['max_tokens'] > 16000:
        print("Warning: MAX_TOKENS should be between 100 and 16000")
    
    if config['temperature'] < 0 or config['temperature'] > 2:
        print("Warning: TEMPERATURE should be between 0 and 2")
    
    if config['api_delay'] < 0:
        print("Warning: API_DELAY should be non-negative")
    
    if config['max_content_length'] < 1000:
        print("Warning: MAX_CONTENT_LENGTH should be at least 1000")
    
    if config['max_workers'] < 1:
        print("Warning: MAX_WORKERS should be at least 1")
        config['max_workers'] = 1
    
    return config


def process_single_file_task(file_path, config, prompt_template, lock, log_callback=None):
    result = {
        "file_path": file_path,
        "success": False,
        "output_filename": None,
        "error": None,
        "quality_score": None
    }
    
    # 再次检查文件状态，避免重复处理
    state = load_processing_state(config['output_dir'])
    with lock:
        if config['incremental_processing'] and not is_file_modified(file_path, state):
            if log_callback:
                log_callback(f"跳过（已处理）: {file_path.name}")
            else:
                print(f"Skipping (already processed by another thread): {file_path.name}")
            result["error"] = "Already processed by another thread"
            return result
    
    try:
        # 安全处理文件名，避免编码错误
        file_name = str(file_path.name)
        if log_callback:
            log_callback(f"[{get_beijing_time()}] 处理中: {file_name}")
        else:
            print(f"[{get_beijing_time()}] Processing: {file_name}")
        
        api_result, extracted_text = process_file_with_deepseek(
            config['api_key'],
            str(file_path),
            prompt_template,
            config['api_model'],
            config['max_tokens'],
            config['temperature'],
            config['max_content_length'],
            log_callback
        )
        
        if not api_result:
            result["error"] = "No result from API"
            if log_callback:
                log_callback(f"[{get_beijing_time()}] 处理失败: {file_name} - No result from API")
            else:
                print(f"[{get_beijing_time()}] Processing failed: {file_name} - No result from API")
            return result
        
        # 检查api_result是否为错误信息
        if api_result.startswith("无法处理文件:"):
            # 这是错误信息，保存为错误文件
            filename = f"{file_path.stem}_error.md"
            output_path = Path(config['output_dir'])
            output_file = output_path / filename
            count = 1
            while output_file.exists():
                filename = f"{file_path.stem}_error_{count}.md"
                output_file = output_path / filename
                count += 1
            
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(api_result)
            
            result["success"] = False
            result["error"] = api_result
            result["output_filename"] = filename
            if log_callback:
                log_callback(f"[{get_beijing_time()}] 处理失败: {file_name} - 已保存错误信息")
            else:
                print(f"[{get_beijing_time()}] Processing failed: {file_name} - Error saved")
            return result
        
        title = extract_main_title(api_result)
        if title:
            filename = f"{title}.md"
        else:
            filename = f"{file_path.stem}_processed.md"
        
        output_path = Path(config['output_dir'])
        output_file = output_path / filename
        count = 1
        while output_file.exists():
            if title:
                filename = f"{title}_{count}.md"
            else:
                filename = f"{file_path.stem}_processed_{count}.md"
            output_file = output_path / filename
            count += 1
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(api_result)
        
        result["success"] = True
        result["output_filename"] = filename
        result["extracted_text"] = extracted_text
        
        if config['enable_quality_scoring']:
            result["quality_score"] = score_content_quality(api_result)
        
        if log_callback:
            log_callback(f"[{get_beijing_time()}] 成功处理: {file_name} - 保存为: {filename}")
        else:
            print(f"[{get_beijing_time()}] Successfully processed: {file_name} - Saved as: {filename}")
        
    except Exception as e:
        # 安全处理错误信息，避免编码错误
        try:
            error_msg = str(e)
        except Exception:
            error_msg = f"Error occurred but cannot convert to string: {type(e).__name__}"
        
        result["error"] = error_msg
        if log_callback:
            log_callback(f"[{get_beijing_time()}] 处理失败: {file_name} - {error_msg}")
        else:
            # 安全输出，避免编码错误
            try:
                print(f"[{get_beijing_time()}] Processing failed: {file_name} - {error_msg}")
            except Exception:
                print(f"[{get_beijing_time()}] Processing failed: {file_name} - [Error message encoding error]")
    
    return result


def main(log_callback=None, config=None):
    try:
        # 如果没有传入config，则从环境变量读取
        if config is None:
            config = validate_config()
        
        # 验证config是否包含必要字段
        required_fields = ['api_key', 'input_dir', 'output_dir', 'api_model', 'max_tokens', 
                          'temperature', 'api_delay', 'max_content_length', 'concurrent_processing',
                          'max_workers', 'incremental_processing', 'enable_deduplication',
                          'enable_quality_scoring']
        
        for field in required_fields:
            if field not in config:
                raise ValueError(f"Missing required config field: {field}")
        
        api_key = config['api_key']
        input_dir = config['input_dir']
        output_dir = config['output_dir']
        
        output_path = Path(output_dir)
        output_path.mkdir(exist_ok=True)
         
    except Exception as e:
        error_msg = f"配置错误: {str(e)}"
        if log_callback:
            log_callback(f"[{get_beijing_time()}] {error_msg}")
        else:
            print(f"[{get_beijing_time()}] {error_msg}")
        return
    
    prompt_template = read_prompt_template()
    if log_callback:
        log_callback(f"[{get_beijing_time()}] 提示词模板已加载")
        log_callback(f"[{get_beijing_time()}] API 模型: {config['api_model']}")
        log_callback(f"[{get_beijing_time()}] 最大 tokens: {config['max_tokens']}")
        log_callback(f"[{get_beijing_time()}] 温度: {config['temperature']}")
        log_callback(f"[{get_beijing_time()}] 并发处理: {'启用' if config['concurrent_processing'] else '禁用'}")
        if config['concurrent_processing']:
            log_callback(f"[{get_beijing_time()}] 最大工作线程: {config['max_workers']}")
        log_callback(f"[{get_beijing_time()}] 增量处理: {'启用' if config['incremental_processing'] else '禁用'}")
        log_callback(f"[{get_beijing_time()}] 去重: {'启用' if config['enable_deduplication'] else '禁用'}")
        log_callback(f"[{get_beijing_time()}] 质量评分: {'启用' if config['enable_quality_scoring'] else '禁用'}")
    else:
        print(f"[{get_beijing_time()}] Prompt template loaded")
        print(f"[{get_beijing_time()}] API Model: {config['api_model']}")
        print(f"[{get_beijing_time()}] Max Tokens: {config['max_tokens']}")
        print(f"[{get_beijing_time()}] Temperature: {config['temperature']}")
        print(f"[{get_beijing_time()}] Concurrent Processing: {'Enabled' if config['concurrent_processing'] else 'Disabled'}")
        if config['concurrent_processing']:
            print(f"[{get_beijing_time()}] Max Workers: {config['max_workers']}")
        print(f"[{get_beijing_time()}] Incremental Processing: {'Enabled' if config['incremental_processing'] else 'Disabled'}")
        print(f"[{get_beijing_time()}] Deduplication: {'Enabled' if config['enable_deduplication'] else 'Disabled'}")
        print(f"[{get_beijing_time()}] Quality Scoring: {'Enabled' if config['enable_quality_scoring'] else 'Disabled'}")
    
    state = load_processing_state(output_dir)
    
    processed_files = []
    failed_files = []
    skipped_files = []
    
    input_path = Path(input_dir)
    if not input_path.exists():
        if log_callback:
            log_callback(f"[{get_beijing_time()}] 错误: 输入目录不存在: {input_dir}")
        else:
            print(f"[{get_beijing_time()}] Error: Input directory does not exist: {input_dir}")
        return
    
    extensions = ['.pdf', '.md', '.txt', '.docx', '.doc', '.jpg', '.jpeg', '.png']
    
    all_files = []
    for ext in extensions:
        all_files.extend(list(input_path.glob(f"*{ext}")))
    
    if not all_files:
        if log_callback:
            log_callback(f"[{get_beijing_time()}] 没有找到需要处理的文件")
        else:
            print(f"[{get_beijing_time()}] No files found to process")
        return
    
    if log_callback:
        log_callback(f"[{get_beijing_time()}] 找到 {len(all_files)} 个文件")
    else:
        print(f"[{get_beijing_time()}] Found {len(all_files)} total files")
    
    lock = threading.Lock()
    
    files_to_process = []
    for file_path in all_files:
        # 安全处理文件名，避免编码错误
        file_name = str(file_path.name)
        with lock:
            if config['incremental_processing'] and not is_file_modified(file_path, state):
                if log_callback:
                    log_callback(f"[{get_beijing_time()}] 跳过（已处理）: {file_name}")
                else:
                    print(f"[{get_beijing_time()}] Skipping (already processed): {file_name}")
                skipped_files.append((file_name, "Already processed"))
                continue
            
            files_to_process.append(file_path)
    
    if log_callback:
        log_callback(f"[{get_beijing_time()}] 需要处理的文件: {len(files_to_process)}")
    else:
        print(f"[{get_beijing_time()}] Files to process: {len(files_to_process)}")
    
    if not files_to_process:
        if log_callback:
            log_callback(f"[{get_beijing_time()}] 没有新的或修改的文件需要处理")
        else:
            print(f"[{get_beijing_time()}] No new or modified files to process")
        # 生成处理报告
        report_path = output_path / "processing_report.md"
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write("# Knowledge Base Processing Report\n\n")
            f.write(f"Processing time: {get_beijing_time()}\n\n")
            
            if skipped_files:
                f.write("## Skipped files\n\n")
                for name, reason in skipped_files:
                    f.write(f"- {name} ({reason})\n")
            
            f.write("\n## Successfully processed files\n\n")
            f.write("- None\n")
            
            f.write("\n## Failed files\n\n")
            f.write("- None\n")
            
            f.write("\n## Statistics\n\n")
            f.write(f"- Total found: {len(all_files)} files\n")
            f.write(f"- Skipped: {len(skipped_files)} files\n")
            f.write(f"- Successfully processed: 0 files\n")
            f.write(f"- Failed: 0 files\n")
        
        # 生成统计图表
        generate_statistics_chart(all_files, skipped_files, [], [], output_dir, log_callback)
        
        if log_callback:
            log_callback(f"[{get_beijing_time()}] 处理完成！")
            log_callback(f"[{get_beijing_time()}] 输出目录: {output_dir}")
            log_callback(f"[{get_beijing_time()}] 处理报告: {report_path}")
        else:
            print(f"\n{'='*50}")
            print(f"[{get_beijing_time()}] Processing completed!")
            print(f"[{get_beijing_time()}] Output directory: {output_dir}")
            print(f"[{get_beijing_time()}] Processing report: {report_path}")
        
        if log_callback:
            log_callback(f"[{get_beijing_time()}] 没有文件被处理（所有文件都被跳过或没有找到新文件）")
        else:
            print(f"[{get_beijing_time()}] No files processed (all files were skipped or no new files found)")
        return
    
    if config['concurrent_processing'] and len(files_to_process) > 1:
        if log_callback:
            log_callback(f"[{get_beijing_time()}] 开始并发处理，使用 {config['max_workers']} 个工作线程...")
        else:
            print(f"[{get_beijing_time()}] Starting concurrent processing with {config['max_workers']} workers...")
        
        with ThreadPoolExecutor(max_workers=config['max_workers']) as executor:
            futures = {
                executor.submit(
                    process_single_file_task,
                    file_path,
                    config,
                    prompt_template,
                    lock,
                    log_callback
                ): file_path
                for file_path in files_to_process
            }
            
            # 新增：进度条
            # 使用log_callback输出进度，避免tqdm输出导致的编码问题
            processed_count = 0
            total_count = len(futures)
            
            for future in as_completed(futures):
                processed_count += 1
                progress_pct = int(processed_count / total_count * 100)
                progress_bar = "=" * int(progress_pct / 5) + ">" + " " * (20 - int(progress_pct / 5))
                
                progress_msg = f"Processing files: {progress_pct}%|[{progress_bar}]| {processed_count}/{total_count}"
                if log_callback:
                    log_callback(f"[{get_beijing_time()}] {progress_msg}")
                else:
                    print(f"[{get_beijing_time()}] {progress_msg}")
                    file_path = futures[future]
                    # 安全处理文件名，避免编码错误
                    file_name = str(file_path.name)
                    try:
                        result = future.result()
                        
                        if result["success"]:
                            if log_callback:
                                log_callback(f"[{get_beijing_time()}] 成功处理: {file_name}")
                                log_callback(f"[{get_beijing_time()}] 保存为: {result['output_filename']}")
                                if result.get("quality_score"):
                                    qs = result["quality_score"]
                                    log_callback(f"[{get_beijing_time()}] 质量评分: {qs['overall']}/10 (结构: {qs['structure']}, 完整性: {qs['completeness']}, 可读性: {qs['readability']})")
                            else:
                                print(f"\n{'='*50}")
                                print(f"[{get_beijing_time()}] Successfully processed: {file_name}")
                                print(f"[{get_beijing_time()}] Saved as: {result['output_filename']}")
                                
                                if result.get("quality_score"):
                                    qs = result["quality_score"]
                                    print(f"[{get_beijing_time()}] Quality Score: {qs['overall']}/10 (Structure: {qs['structure']}, Completeness: {qs['completeness']}, Readability: {qs['readability']})")
                            
                            processed_files.append((file_name, result["output_filename"], result.get("quality_score")))
                            
                            with lock:
                                state["processed_files"][str(file_path)] = {
                                    "processed_at": time.time(),
                                    "output_file": result["output_filename"]
                                }
                                
                                if result.get("extracted_text"):
                                    content_hash = compute_content_hash(result["extracted_text"])
                                    state["content_hashes"][content_hash] = result["extracted_text"][:5000]
                                
                                save_processing_state(output_dir, state)
                            
                        else:
                            if log_callback:
                                log_callback(f"[{get_beijing_time()}] 处理失败: {file_name} - {result['error']}")
                            else:
                                print(f"\n{'='*50}")
                                print(f"[{get_beijing_time()}] Failed to process: {file_name}")
                                print(f"[{get_beijing_time()}] Error: {result['error']}")
                            failed_files.append(file_name)
                            
                    except Exception as e:
                        if log_callback:
                            log_callback(f"[{get_beijing_time()}] 任务失败: {file_name} - {str(e)}")
                        else:
                            print(f"[{get_beijing_time()}] Task failed for {file_name}: {e}")
                        failed_files.append(file_name)
            else:
                # 没有 tqdm 时的处理
                for future in as_completed(futures):
                    file_path = futures[future]
                    # 安全处理文件名，避免编码错误
                    file_name = str(file_path.name)
                    try:
                        result = future.result()
                        
                        if result["success"]:
                            if log_callback:
                                log_callback(f"[{get_beijing_time()}] 成功处理: {file_name}")
                                log_callback(f"[{get_beijing_time()}] 保存为: {result['output_filename']}")
                                if result.get("quality_score"):
                                    qs = result["quality_score"]
                                    log_callback(f"[{get_beijing_time()}] 质量评分: {qs['overall']}/10 (结构: {qs['structure']}, 完整性: {qs['completeness']}, 可读性: {qs['readability']})")
                            else:
                                print(f"\n{'='*50}")
                                print(f"[{get_beijing_time()}] Successfully processed: {file_name}")
                                print(f"[{get_beijing_time()}] Saved as: {result['output_filename']}")
                                
                                if result.get("quality_score"):
                                    qs = result["quality_score"]
                                    print(f"[{get_beijing_time()}] Quality Score: {qs['overall']}/10 (Structure: {qs['structure']}, Completeness: {qs['completeness']}, Readability: {qs['readability']})")
                            
                            processed_files.append((file_name, result["output_filename"], result.get("quality_score")))
                            
                            with lock:
                                state["processed_files"][str(file_path)] = {
                                    "processed_at": time.time(),
                                    "output_file": result["output_filename"]
                                }
                                
                                if result.get("extracted_text"):
                                    content_hash = compute_content_hash(result["extracted_text"])
                                    state["content_hashes"][content_hash] = result["extracted_text"][:5000]
                                
                                save_processing_state(output_dir, state)
                            
                        else:
                            if log_callback:
                                log_callback(f"[{get_beijing_time()}] 处理失败: {file_name} - {result['error']}")
                            else:
                                print(f"\n{'='*50}")
                                print(f"[{get_beijing_time()}] Failed to process: {file_name}")
                                print(f"[{get_beijing_time()}] Error: {result['error']}")
                            failed_files.append(file_name)
                            
                    except Exception as e:
                        if log_callback:
                            log_callback(f"[{get_beijing_time()}] 任务失败: {file_name} - {str(e)}")
                        else:
                            print(f"[{get_beijing_time()}] Task failed for {file_name}: {e}")
                        failed_files.append(file_name)
    
    else:
        if log_callback:
            log_callback(f"[{get_beijing_time()}] 开始顺序处理...")
        else:
            print(f"[{get_beijing_time()}] Starting sequential processing...")
        
        # 新增：进度条
        # 使用log_callback输出进度，避免tqdm输出导致的编码问题
        processed_count = 0
        total_count = len(files_to_process)
        
        for file_path in files_to_process:
            processed_count += 1
            progress_pct = int(processed_count / total_count * 100)
            progress_bar = "=" * int(progress_pct / 5) + ">" + " " * (20 - int(progress_pct / 5))
            
            progress_msg = f"Processing files: {progress_pct}%|[{progress_bar}]| {processed_count}/{total_count}"
            if log_callback:
                log_callback(f"[{get_beijing_time()}] {progress_msg}")
            else:
                print(f"[{get_beijing_time()}] {progress_msg}")
                # 安全处理文件名，避免编码错误
                file_name = str(file_path.name)
                try:
                    if log_callback:
                        log_callback(f"[{get_beijing_time()}] 处理文件: {file_name}")
                    else:
                        print(f"\n{'='*50}")
                        print(f"[{get_beijing_time()}] Processing file: {file_name}")
                    
                    result = process_single_file_task(file_path, config, prompt_template, lock, log_callback)
                    
                    if result["success"]:
                        if log_callback:
                            log_callback(f"保存为: {result['output_filename']}")
                            if result.get("quality_score"):
                                qs = result["quality_score"]
                                log_callback(f"质量评分: {qs['overall']}/10 (结构: {qs['structure']}, 完整性: {qs['completeness']}, 可读性: {qs['readability']})")
                        else:
                            print(f"Saved as: {result['output_filename']}")
                            
                            if result.get("quality_score"):
                                qs = result["quality_score"]
                                print(f"Quality Score: {qs['overall']}/10 (Structure: {qs['structure']}, Completeness: {qs['completeness']}, Readability: {qs['readability']})")
                        
                        processed_files.append((file_name, result["output_filename"], result.get("quality_score")))
                        
                        state["processed_files"][str(file_path)] = {
                            "processed_at": time.time(),
                            "output_file": result["output_filename"]
                        }
                        
                        if result.get("extracted_text"):
                            content_hash = compute_content_hash(result["extracted_text"])
                            state["content_hashes"][content_hash] = result["extracted_text"][:5000]
                        
                        save_processing_state(output_dir, state)
                        
                    else:
                        if log_callback:
                            log_callback(f"处理失败: {file_name} - {result['error']}")
                        else:
                            print(f"Failed: {result['error']}")
                        failed_files.append(file_name)
                    
                    if not config['concurrent_processing']:
                        time.sleep(config['api_delay'])
                    
                except Exception as e:
                    if log_callback:
                        log_callback(f"处理失败: {file_name} - {str(e)}")
                    else:
                        print(f"Failed: {e}")
                    failed_files.append(file_name)
        else:
            # 没有 tqdm 时的处理
            for file_path in files_to_process:
                # 安全处理文件名，避免编码错误
                file_name = str(file_path.name)
                try:
                    if log_callback:
                        log_callback(f"[{get_beijing_time()}] 处理文件: {file_name}")
                    else:
                        print(f"\n{'='*50}")
                        print(f"[{get_beijing_time()}] Processing file: {file_name}")
                    
                    result = process_single_file_task(file_path, config, prompt_template, lock, log_callback)
                    
                    if result["success"]:
                        if log_callback:
                            log_callback(f"保存为: {result['output_filename']}")
                            if result.get("quality_score"):
                                qs = result["quality_score"]
                                log_callback(f"质量评分: {qs['overall']}/10 (结构: {qs['structure']}, 完整性: {qs['completeness']}, 可读性: {qs['readability']})")
                        else:
                            print(f"Saved as: {result['output_filename']}")
                            
                            if result.get("quality_score"):
                                qs = result["quality_score"]
                                print(f"Quality Score: {qs['overall']}/10 (Structure: {qs['structure']}, Completeness: {qs['completeness']}, Readability: {qs['readability']})")
                        
                        processed_files.append((file_name, result["output_filename"], result.get("quality_score")))
                        
                        state["processed_files"][str(file_path)] = {
                            "processed_at": time.time(),
                            "output_file": result["output_filename"]
                        }
                        
                        if result.get("extracted_text"):
                            content_hash = compute_content_hash(result["extracted_text"])
                            state["content_hashes"][content_hash] = result["extracted_text"][:5000]
                        
                        save_processing_state(output_dir, state)
                        
                    else:
                        if log_callback:
                            log_callback(f"处理失败: {file_name} - {result['error']}")
                        else:
                            print(f"Failed: {result['error']}")
                        failed_files.append(file_name)
                    
                    if not config['concurrent_processing']:
                        time.sleep(config['api_delay'])
                    
                except Exception as e:
                    if log_callback:
                        log_callback(f"处理失败: {file_name} - {str(e)}")
                    else:
                        print(f"Failed: {e}")
                    failed_files.append(file_name)
    
    # 生成处理报告
    report_path = output_path / "processing_report.md"
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write("# Knowledge Base Processing Report\n\n")
        f.write(f"Processing time: {get_beijing_time()}\n\n")
        
        if skipped_files:
            f.write("## Skipped files\n\n")
            for name, reason in skipped_files:
                f.write(f"- {name} ({reason})\n")
        
        if processed_files:
            f.write("\n## Successfully processed files\n\n")
            for input_name, output_name, qs in processed_files:
                f.write(f"- **{input_name}** → `{output_name}`")
                if qs:
                    f.write(f" (Quality: {qs['overall']}/10)")
                f.write("\n")
        
        if failed_files:
            f.write("\n## Failed files\n\n")
            for failed in failed_files:
                f.write(f"- {failed}\n")
        
        f.write("\n## Statistics\n\n")
        f.write(f"- Total found: {len(all_files)} files\n")
        f.write(f"- Skipped: {len(skipped_files)} files\n")
        f.write(f"- Successfully processed: {len(processed_files)} files\n")
        f.write(f"- Failed: {len(failed_files)} files\n")
    
    # 生成统计图表
    generate_statistics_chart(all_files, skipped_files, processed_files, failed_files, output_dir, log_callback)
    
    if log_callback:
        log_callback(f"[{get_beijing_time()}] 处理完成！")
        log_callback(f"[{get_beijing_time()}] 输出目录: {output_dir}")
        log_callback(f"[{get_beijing_time()}] 处理报告: {report_path}")
        
        if processed_files:
            log_callback(f"[{get_beijing_time()}] \n生成的 Markdown 文件:")
            for _, output_name, _ in processed_files:
                log_callback(f"[{get_beijing_time()}]   - {output_name}")
    else:
        print(f"\n{'='*50}")
        print(f"[{get_beijing_time()}] Processing completed!")
        print(f"[{get_beijing_time()}] Output directory: {output_dir}")
        print(f"[{get_beijing_time()}] Processing report: {report_path}")
        
        if processed_files:
            print(f"[{get_beijing_time()}] \nGenerated Markdown files:")
            for _, output_name, _ in processed_files:
                print(f"[{get_beijing_time()}]   - {output_name}")


def process_files(config, log_callback=None):
    """Process files with the given configuration"""
    main(log_callback, config)


if __name__ == "__main__":
    main()

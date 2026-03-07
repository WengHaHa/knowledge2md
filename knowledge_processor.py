#!/usr/bin/env python3
"""
Knowledge Base File Processor - Enhanced version with concurrency, incremental processing, deduplication, and quality scoring
"""

import os
import sys
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
        print(f"Error: Prompt file not found at {prompt_file}")
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
        print("PDF text extraction failed:", e)
        return None


def handle_api_error(e):
    if isinstance(e, requests.exceptions.HTTPError):
        if e.response.status_code == 401:
            print(f"API Error: Authentication failed (401 Unauthorized)")
            print(f"Please check your DEEPSEEK_API_KEY is valid")
        elif e.response.status_code == 429:
            print(f"API Error: Rate limit exceeded (429 Too Many Requests)")
        else:
            print(f"API Error: HTTP {e.response.status_code} - {e.response.text[:200]}")
    else:
        print(f"API Error: {e}")
    raise


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
        
        # 保存图表
        chart_path = Path(output_dir) / "processing_statistics.png"
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
        
        if not pdf_text:
            if log_callback:
                log_callback(f"[{get_beijing_time()}] 无法提取PDF文本，尝试base64编码")
            else:
                print(f"[{get_beijing_time()}] Cannot extract PDF text, trying base64 encoding")
            base64_data = base64.b64encode(file_content[:10000]).decode('utf-8')
            content_text = prompt_template + "\n\nBelow is PDF file content (base64 encoded, please decode first):\n\ndata:application/pdf;base64," + base64_data
        else:
            pdf_text = truncate_content(pdf_text, max_content_length, "PDF text")
            content_text = prompt_template + "\n\nBelow is PDF content:\n\n" + pdf_text
        
        messages = [{"role": "user", "content": content_text}]
        
    elif file_ext in ['.docx', '.doc']:
        if log_callback:
            log_callback(f"[{get_beijing_time()}] 提取Word文档文本...")
        else:
            print(f"[{get_beijing_time()}] Extracting Word document text...")
        docx_text = extract_docx_text(file_content)
        extracted_text = docx_text
        
        if not docx_text:
            if log_callback:
                log_callback(f"[{get_beijing_time()}] 无法提取Word文本，尝试base64编码")
            else:
                print(f"[{get_beijing_time()}] Cannot extract Word text, trying base64 encoding")
            base64_data = base64.b64encode(file_content[:10000]).decode('utf-8')
            content_text = prompt_template + "\n\nBelow is Word document content (base64 encoded, please decode first):\n\ndata:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64," + base64_data
        else:
            docx_text = truncate_content(docx_text, max_content_length, "Word text")
            content_text = prompt_template + "\n\nBelow is Word document content:\n\n" + docx_text
        
        messages = [{"role": "user", "content": content_text}]
        
    elif file_ext in ['.txt', '.md']:
        text_content = file_content.decode('utf-8', errors='ignore')
        extracted_text = text_content
        text_content = truncate_content(text_content, max_content_length, "Text content")
        content_text = prompt_template + "\n\nBelow is text content:\n\n" + text_content
        messages = [{"role": "user", "content": content_text}]
    
    elif file_ext in ['.jpg', '.jpeg', '.png']:
        if log_callback:
            log_callback(f"[{get_beijing_time()}] 处理图片...")
        else:
            print(f"[{get_beijing_time()}] Processing image...")
        process_image(file_content)
        
        base64_data = base64.b64encode(file_content).decode('utf-8')
        mime_type = 'image/jpeg' if file_ext in ['.jpg', '.jpeg'] else 'image/png'
        
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt_template},
                {"type": "text", "text": "Please analyze the following image content and organize it as required:"},
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_data}"}}
            ]
        }]
        extracted_text = base64_data[:1000]
    
    else:
        if log_callback:
            log_callback(f"[{get_beijing_time()}] 不支持的文件类型: {file_ext}")
        else:
            print(f"[{get_beijing_time()}] Unsupported file type: {file_ext}")
        return None, None
    
    payload = {
        "model": api_model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature
    }
    
    try:
        if log_callback:
            log_callback(f"[{get_beijing_time()}] 调用API处理: {Path(file_path).name}")
        else:
            print(f"[{get_beijing_time()}] Calling API to process: {Path(file_path).name}")
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
        handle_api_error(e)


def validate_config():
    config = {}
    
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("Error: DEEPSEEK_API_KEY not found in environment variables or .env file")
        print("Please set DEEPSEEK_API_KEY in .env file or environment variable")
        sys.exit(1)
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
        print(f"Error: Invalid configuration value: {e}")
        sys.exit(1)
    
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
        if log_callback:
            log_callback(f"[{get_beijing_time()}] 处理中: {file_path.name}")
        else:
            print(f"[{get_beijing_time()}] Processing: {file_path.name}")
        
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
        
    except Exception as e:
        result["error"] = str(e)
    
    return result


def main(log_callback=None, config=None):
    # 如果没有传入config，则从环境变量读取
    if config is None:
        config = validate_config()
    
    api_key = config['api_key']
    input_dir = config['input_dir']
    output_dir = config['output_dir']
    
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    
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
        with lock:
            if config['incremental_processing'] and not is_file_modified(file_path, state):
                if log_callback:
                    log_callback(f"[{get_beijing_time()}] 跳过（已处理）: {file_path.name}")
                else:
                    print(f"[{get_beijing_time()}] Skipping (already processed): {file_path.name}")
                skipped_files.append((file_path.name, "Already processed"))
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
            if tqdm:
                for future in tqdm(as_completed(futures), total=len(futures), desc="Processing files"):
                    file_path = futures[future]
                    try:
                        result = future.result()
                        
                        if result["success"]:
                            if log_callback:
                                log_callback(f"[{get_beijing_time()}] 成功处理: {file_path.name}")
                                log_callback(f"[{get_beijing_time()}] 保存为: {result['output_filename']}")
                                if result.get("quality_score"):
                                    qs = result["quality_score"]
                                    log_callback(f"[{get_beijing_time()}] 质量评分: {qs['overall']}/10 (结构: {qs['structure']}, 完整性: {qs['completeness']}, 可读性: {qs['readability']})")
                            else:
                                print(f"\n{'='*50}")
                                print(f"[{get_beijing_time()}] Successfully processed: {file_path.name}")
                                print(f"[{get_beijing_time()}] Saved as: {result['output_filename']}")
                                
                                if result.get("quality_score"):
                                    qs = result["quality_score"]
                                    print(f"[{get_beijing_time()}] Quality Score: {qs['overall']}/10 (Structure: {qs['structure']}, Completeness: {qs['completeness']}, Readability: {qs['readability']})")
                            
                            processed_files.append((file_path.name, result["output_filename"], result.get("quality_score")))
                            
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
                                log_callback(f"[{get_beijing_time()}] 处理失败: {file_path.name} - {result['error']}")
                            else:
                                print(f"\n{'='*50}")
                                print(f"[{get_beijing_time()}] Failed to process: {file_path.name}")
                                print(f"[{get_beijing_time()}] Error: {result['error']}")
                            failed_files.append(file_path.name)
                            
                    except Exception as e:
                        if log_callback:
                            log_callback(f"[{get_beijing_time()}] 任务失败: {file_path.name} - {str(e)}")
                        else:
                            print(f"[{get_beijing_time()}] Task failed for {file_path.name}: {e}")
                        failed_files.append(file_path.name)
            else:
                # 没有 tqdm 时的处理
                for future in as_completed(futures):
                    file_path = futures[future]
                    try:
                        result = future.result()
                        
                        if result["success"]:
                            if log_callback:
                                log_callback(f"[{get_beijing_time()}] 成功处理: {file_path.name}")
                                log_callback(f"[{get_beijing_time()}] 保存为: {result['output_filename']}")
                                if result.get("quality_score"):
                                    qs = result["quality_score"]
                                    log_callback(f"[{get_beijing_time()}] 质量评分: {qs['overall']}/10 (结构: {qs['structure']}, 完整性: {qs['completeness']}, 可读性: {qs['readability']})")
                            else:
                                print(f"\n{'='*50}")
                                print(f"[{get_beijing_time()}] Successfully processed: {file_path.name}")
                                print(f"[{get_beijing_time()}] Saved as: {result['output_filename']}")
                                
                                if result.get("quality_score"):
                                    qs = result["quality_score"]
                                    print(f"[{get_beijing_time()}] Quality Score: {qs['overall']}/10 (Structure: {qs['structure']}, Completeness: {qs['completeness']}, Readability: {qs['readability']})")
                            
                            processed_files.append((file_path.name, result["output_filename"], result.get("quality_score")))
                            
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
                                log_callback(f"[{get_beijing_time()}] 处理失败: {file_path.name} - {result['error']}")
                            else:
                                print(f"\n{'='*50}")
                                print(f"[{get_beijing_time()}] Failed to process: {file_path.name}")
                                print(f"[{get_beijing_time()}] Error: {result['error']}")
                            failed_files.append(file_path.name)
                            
                    except Exception as e:
                        if log_callback:
                            log_callback(f"[{get_beijing_time()}] 任务失败: {file_path.name} - {str(e)}")
                        else:
                            print(f"[{get_beijing_time()}] Task failed for {file_path.name}: {e}")
                        failed_files.append(file_path.name)
    
    else:
        if log_callback:
            log_callback(f"[{get_beijing_time()}] 开始顺序处理...")
        else:
            print(f"[{get_beijing_time()}] Starting sequential processing...")
        
        # 新增：进度条
        if tqdm:
            for file_path in tqdm(files_to_process, desc="Processing files"):
                try:
                    if log_callback:
                        log_callback(f"[{get_beijing_time()}] 处理文件: {file_path.name}")
                    else:
                        print(f"\n{'='*50}")
                        print(f"[{get_beijing_time()}] Processing file: {file_path.name}")
                    
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
                        
                        processed_files.append((file_path.name, result["output_filename"], result.get("quality_score")))
                        
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
                            log_callback(f"处理失败: {file_path.name} - {result['error']}")
                        else:
                            print(f"Failed: {result['error']}")
                        failed_files.append(file_path.name)
                    
                    if not config['concurrent_processing']:
                        time.sleep(config['api_delay'])
                    
                except Exception as e:
                    if log_callback:
                        log_callback(f"处理失败: {file_path.name} - {str(e)}")
                    else:
                        print(f"Failed: {e}")
                    failed_files.append(file_path.name)
        else:
            # 没有 tqdm 时的处理
            for file_path in files_to_process:
                try:
                    if log_callback:
                        log_callback(f"[{get_beijing_time()}] 处理文件: {file_path.name}")
                    else:
                        print(f"\n{'='*50}")
                        print(f"[{get_beijing_time()}] Processing file: {file_path.name}")
                    
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
                        
                        processed_files.append((file_path.name, result["output_filename"], result.get("quality_score")))
                        
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
                            log_callback(f"处理失败: {file_path.name} - {result['error']}")
                        else:
                            print(f"Failed: {result['error']}")
                        failed_files.append(file_path.name)
                    
                    if not config['concurrent_processing']:
                        time.sleep(config['api_delay'])
                    
                except Exception as e:
                    if log_callback:
                        log_callback(f"处理失败: {file_path.name} - {str(e)}")
                    else:
                        print(f"Failed: {e}")
                    failed_files.append(file_path.name)
    
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


if __name__ == "__main__":
    main()


def process_files(config, log_callback=None):
    """Process files with the given configuration"""
    main(log_callback, config)

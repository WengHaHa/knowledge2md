#!/usr/bin/env python3
"""
Knowledge Base File Processor - Fixed version
"""

import os
import sys
import base64
import json
import requests
from pathlib import Path
import time
import re
import pypdf
from io import BytesIO

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

def read_prompt_template():
    """Read prompt template from prompts folder"""
    prompt_file = Path("prompts/knowledge_prompt.md")
    if not prompt_file.exists():
        print("Error: Prompt file not found")
        sys.exit(1)
    
    with open(prompt_file, 'r', encoding='utf-8') as f:
        prompt_template = f.read()
    
    prompt_template = prompt_template.replace("请用Markdown代码块输出，即用三个反引号包裹你的整个回答。", "")
    return prompt_template.strip()

def extract_main_title(markdown_content):
    """Extract main title from Markdown content"""
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
    """Truncate content if it exceeds max length"""
    if len(content) > max_length:
        content = content[:max_length]
        print(f"{content_type} truncated to {len(content)} characters")
    return content

def extract_docx_text(file_content):
    """Extract text from Word document"""
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
    """Process image with Pillow"""
    try:
        from PIL import Image
        img = Image.open(BytesIO(image_content))
        # 可以添加图像处理逻辑，如 resize、压缩等
        return img
    except ImportError:
        print("Pillow not installed, using original image")
        return None
    except Exception as e:
        print("Image processing failed:", e)
        return None

def get_file_type(file_content):
    """Get file type using python-magic"""
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
    """Extract text from PDF file"""
    try:
        pdf_file = BytesIO(file_content)
        reader = pypdf.PdfReader(pdf_file)
        text = ""
        
        for page_num, page in enumerate(reader.pages):
            page_text = page.extract_text()
            if page_text:
                text += "\n--- Page " + str(page_num+1) + " ---\n"
                text += page_text + "\n"
        
        return text.strip()
    except Exception as e:
        print("PDF text extraction failed:", e)
        return None

def handle_api_error(e):
    """Handle API errors consistently"""
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

def process_file_with_deepseek(api_key, file_path, prompt_template, api_model="deepseek-chat", max_tokens=4000, temperature=0.3, max_content_length=50000):
    """Process single file using DeepSeek API"""
    
    with open(file_path, 'rb') as f:
        file_content = f.read()
    
    file_ext = Path(file_path).suffix.lower()
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    if file_ext == '.pdf':
        print("Extracting PDF text...")
        pdf_text = extract_pdf_text(file_content)
        
        if not pdf_text:
            print("Cannot extract PDF text, trying base64 encoding")
            base64_data = base64.b64encode(file_content[:10000]).decode('utf-8')
            content_text = prompt_template + "\n\nBelow is PDF file content (base64 encoded, please decode first):\n\ndata:application/pdf;base64," + base64_data
        else:
            pdf_text = truncate_content(pdf_text, max_content_length, "PDF text")
            content_text = prompt_template + "\n\nBelow is PDF content:\n\n" + pdf_text
        
        messages = [{"role": "user", "content": content_text}]
        
    elif file_ext in ['.docx', '.doc']:
        print("Extracting Word document text...")
        docx_text = extract_docx_text(file_content)
        
        if not docx_text:
            print("Cannot extract Word text, trying base64 encoding")
            base64_data = base64.b64encode(file_content[:10000]).decode('utf-8')
            content_text = prompt_template + "\n\nBelow is Word document content (base64 encoded, please decode first):\n\ndata:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64," + base64_data
        else:
            docx_text = truncate_content(docx_text, max_content_length, "Word text")
            content_text = prompt_template + "\n\nBelow is Word document content:\n\n" + docx_text
        
        messages = [{"role": "user", "content": content_text}]
        
    elif file_ext in ['.txt', '.md']:
        text_content = file_content.decode('utf-8', errors='ignore')
        text_content = truncate_content(text_content, max_content_length, "Text content")
        content_text = prompt_template + "\n\nBelow is text content:\n\n" + text_content
        messages = [{"role": "user", "content": content_text}]
    
    elif file_ext in ['.jpg', '.jpeg', '.png']:
        print("Processing image...")
        # 尝试处理图像
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
    
    else:
        print(f"Unsupported file type: {file_ext}")
        return None
    
    payload = {
        "model": api_model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature
    }
    
    try:
        print(f"Calling API to process: {Path(file_path).name}")
        response = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=60
        )
        response.raise_for_status()
        result = response.json()
        return result['choices'][0]['message']['content']
    except Exception as e:
        handle_api_error(e)

def validate_config():
    """Validate configuration parameters"""
    config = {}
    
    # Required parameters
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("Error: DEEPSEEK_API_KEY not found in environment variables or .env file")
        print("Please set DEEPSEEK_API_KEY in .env file or environment variable")
        sys.exit(1)
    config['api_key'] = api_key
    
    # Optional parameters with defaults
    config['input_dir'] = os.environ.get("INPUT_DIR", "knowledge_base_link")
    config['output_dir'] = os.environ.get("OUTPUT_DIR", "processed_knowledge")
    config['api_model'] = os.environ.get("API_MODEL", "deepseek-chat")
    
    # Numeric parameters with validation
    try:
        config['max_tokens'] = int(os.environ.get("MAX_TOKENS", "4000"))
        config['temperature'] = float(os.environ.get("TEMPERATURE", "0.3"))
        config['api_delay'] = int(os.environ.get("API_DELAY", "2"))
        config['max_content_length'] = int(os.environ.get("MAX_CONTENT_LENGTH", "50000"))
    except ValueError as e:
        print(f"Error: Invalid configuration value: {e}")
        sys.exit(1)
    
    # Validate numeric ranges
    if config['max_tokens'] < 100 or config['max_tokens'] > 16000:
        print("Warning: MAX_TOKENS should be between 100 and 16000")
    
    if config['temperature'] < 0 or config['temperature'] > 2:
        print("Warning: TEMPERATURE should be between 0 and 2")
    
    if config['api_delay'] < 0:
        print("Warning: API_DELAY should be non-negative")
    
    if config['max_content_length'] < 1000:
        print("Warning: MAX_CONTENT_LENGTH should be at least 1000")
    
    return config

def main():
    """Main function"""
    config = validate_config()
    api_key = config['api_key']
    input_dir = config['input_dir']
    output_dir = config['output_dir']
    api_model = config['api_model']
    max_tokens = config['max_tokens']
    temperature = config['temperature']
    api_delay = config['api_delay']
    max_content_length = config['max_content_length']
    
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    
    prompt_template = read_prompt_template()
    print("Prompt template loaded")
    print(f"API Model: {api_model}")
    print(f"Max Tokens: {max_tokens}")
    print(f"Temperature: {temperature}")
    
    processed_files = []
    failed_files = []
    
    input_path = Path(input_dir)
    if not input_path.exists():
        print(f"Error: Input directory does not exist: {input_dir}")
        return
    
    extensions = ['.pdf', '.md', '.txt', '.docx', '.doc', '.jpg', '.jpeg', '.png']
    
    all_files = []
    for ext in extensions:
        all_files.extend(list(input_path.glob(f"*{ext}")))
    
    if not all_files:
        print("No files found to process")
        return
    
    print(f"Found {len(all_files)} files")
    
    for file_path in all_files:
        try:
            print(f"\n{'='*50}")
            print(f"Processing file: {file_path.name}")
            
            result = process_file_with_deepseek(api_key, str(file_path), prompt_template, api_model, max_tokens, temperature, max_content_length)
            if not result:
                print("Skipping file")
                continue
            
            title = extract_main_title(result)
            if title:
                filename = f"{title}.md"
                print(f"Extracted title: {title}")
            else:
                filename = f"{file_path.stem}_processed.md"
                print("Using default filename")
            
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
                f.write(result)
            
            print(f"Saved as: {filename}")
            processed_files.append((file_path.name, filename))
            
            time.sleep(api_delay)
            
        except Exception as e:
            print(f"Failed: {e}")
            failed_files.append(file_path.name)
    
    report_path = output_path / "processing_report.md"
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write("# Knowledge Base Processing Report\n\n")
        f.write(f"Processing time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        if processed_files:
            f.write("## Successfully processed files\n\n")
            for input_name, output_name in processed_files:
                f.write(f"- **{input_name}** → `{output_name}`\n")
        
        if failed_files:
            f.write("\n## Failed files\n\n")
            for failed in failed_files:
                f.write(f"- {failed}\n")
        
        f.write("\n## Statistics\n\n")
        f.write(f"- Successfully processed: {len(processed_files)} files\n")
        f.write(f"- Failed: {len(failed_files)} files\n")
    
    print(f"\n{'='*50}")
    print("Processing completed!")
    print(f"Output directory: {output_dir}")
    print(f"Processing report: {report_path}")
    
    if processed_files:
        print("\nGenerated Markdown files:")
        for _, output_name in processed_files:
            print(f"  - {output_name}")

if __name__ == "__main__":
    main()
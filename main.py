#!/usr/bin/env python3
"""
Knowledge Base Processor - FastAPI Backend
"""

import os
import sys
import json
import asyncio
import sqlite3
from pathlib import Path
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import uvicorn
import datetime
import pytz

# 获取北京地区的当前时间
def get_beijing_time():
    beijing_tz = pytz.timezone('Asia/Shanghai')
    return datetime.datetime.now(beijing_tz).strftime('%Y-%m-%d %H:%M:%S')

# 导入处理器模块
from knowledge_processor import process_files

# 创建FastAPI应用
app = FastAPI(
    title="知识库处理器 API",
    description="用于处理知识库文件的API服务",
    version="1.0.0"
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 处理状态
processing_state = {
    "is_running": False,
    "progress": 0,
    "status": "就绪",
    "log": []
}

# 配置模型
class Config(BaseModel):
    apiKey: str
    inputDir: str = "knowledge_input"
    outputDir: str = "knowledge_output"
    concurrentProcessing: bool = False
    maxWorkers: int = 3
    incrementalProcessing: bool = True
    enableDeduplication: bool = True
    enableQualityScoring: bool = True

# 初始化数据库
def init_db():
    import os
    db_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge2md.db")
    conn = sqlite3.connect(db_file_path)
    cursor = conn.cursor()
    # 创建配置表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS config (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        api_key TEXT NOT NULL,
        input_dir TEXT DEFAULT 'knowledge_base_link',
        output_dir TEXT DEFAULT 'processed_knowledge',
        concurrent_processing BOOLEAN DEFAULT 0,
        max_workers INTEGER DEFAULT 3,
        incremental_processing BOOLEAN DEFAULT 1,
        enable_deduplication BOOLEAN DEFAULT 1,
        enable_quality_scoring BOOLEAN DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    # 创建处理记录表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS processing_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_name TEXT NOT NULL,
        status TEXT NOT NULL,
        error TEXT,
        quality_score REAL,
        processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    conn.commit()
    conn.close()

# 保存配置
@app.post("/api/config")
async def save_config(config: Config):
    # 使用线程池执行同步的数据库操作
    def save_to_db():
        import os
        db_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge2md.db")
        conn = sqlite3.connect(db_file_path)
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO config (api_key, input_dir, output_dir, concurrent_processing, max_workers, incremental_processing, enable_deduplication, enable_quality_scoring)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            config.apiKey,
            config.inputDir,
            config.outputDir,
            1 if config.concurrentProcessing else 0,
            config.maxWorkers,
            1 if config.incrementalProcessing else 0,
            1 if config.enableDeduplication else 0,
            1 if config.enableQualityScoring else 0
        ))
        conn.commit()
        conn.close()
    
    await asyncio.to_thread(save_to_db)
    return {"message": "配置保存成功"}

# 处理文件
async def process_files_background():
    global processing_state
    processing_state["is_running"] = True
    processing_state["progress"] = 0
    processing_state["status"] = "开始处理"
    processing_state["log"] = []
    
    print(f"[{get_beijing_time()}] 开始处理文件...")
    
    try:
        # 从数据库中读取最新配置
        import os
        db_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge2md.db")
        conn = sqlite3.connect(db_file_path)
        cursor = conn.cursor()
        cursor.execute('''
        SELECT api_key, input_dir, output_dir, concurrent_processing, max_workers, incremental_processing, enable_deduplication, enable_quality_scoring
        FROM config
        ORDER BY id DESC
        LIMIT 1
        ''')
        config_row = cursor.fetchone()
        conn.close()
        
        print(f"[{get_beijing_time()}] 读取配置: {config_row}")
        
        # 读取配置
        if config_row:
            config = {
                "api_key": config_row[0],
                "input_dir": config_row[1] or "knowledge_input",
                "output_dir": config_row[2] or "knowledge_output",
                "concurrent_processing": bool(config_row[3]),
                "max_workers": config_row[4] or 3,
                "incremental_processing": bool(config_row[5]),
                "enable_deduplication": bool(config_row[6]),
                "enable_quality_scoring": bool(config_row[7]),
                "api_model": "deepseek-chat",
                "max_tokens": 4000,
                "temperature": 1.0,
                "api_delay": 2,
                "max_content_length": 50000
            }
        else:
            # 如果数据库中没有配置，则使用默认配置
            config = {
                "api_key": os.getenv("DEEPSEEK_API_KEY"),
                "input_dir": "knowledge_input",
                "output_dir": "knowledge_output",
                "concurrent_processing": False,
                "max_workers": 3,
                "incremental_processing": True,
                "enable_deduplication": True,
                "enable_quality_scoring": True,
                "api_model": "deepseek-chat",
                "max_tokens": 4000,
                "temperature": 1.0,
                "api_delay": 2,
                "max_content_length": 50000
            }
        
        print(f"[{get_beijing_time()}] 配置: {config}")
        
        # 检查输入目录是否存在
        import os
        input_dir = config['input_dir']
        output_dir = config['output_dir']
        print(f"[{get_beijing_time()}] 输入目录: {input_dir}")
        print(f"[{get_beijing_time()}] 输入目录存在: {os.path.exists(input_dir)}")
        print(f"[{get_beijing_time()}] 输出目录: {output_dir}")
        print(f"[{get_beijing_time()}] 输出目录存在: {os.path.exists(output_dir)}")
        
        # 列出输入目录中的文件
        if os.path.exists(input_dir):
            files = os.listdir(input_dir)
            print(f"[{get_beijing_time()}] 输入目录中的文件: {files}")
        
        # 处理文件
        def log_callback(message):
            # 消息已经包含时间戳，直接添加
            processing_state["log"].append(message)
            print(f"[{get_beijing_time()}] 日志: {message}")
            # 简单的进度计算
            if "处理中" in message:
                processing_state["progress"] += 5
                if processing_state["progress"] > 100:
                    processing_state["progress"] = 100
            # 提取状态信息，只保留关键状态
            if message.startswith('['):
                # 移除时间戳，提取状态
                status_part = message.split('] ')[1]
                if ':' in status_part:
                    processing_state["status"] = status_part.split(':')[0]
                else:
                    processing_state["status"] = status_part
            else:
                processing_state["status"] = message.split(':')[0] if ':' in message else message
        
        # 调用处理器
        print(f"[{get_beijing_time()}] 调用process_files...")
        try:
            await asyncio.to_thread(process_files, config, log_callback)
            print(f"[{get_beijing_time()}] process_files 调用成功")
        except Exception as e:
            print(f"[{get_beijing_time()}] process_files 调用失败: {e}")
            import traceback
            traceback.print_exc()
            if log_callback:
                log_callback(f"处理失败: {str(e)}")
        
        processing_state["status"] = "处理完成"
        processing_state["progress"] = 100
    except Exception as e:
        processing_state["status"] = f"错误: {str(e)}"
        processing_state["log"].append(f"错误: {str(e)}")
    finally:
        processing_state["is_running"] = False

# 启动处理
@app.get("/api/process")
async def start_processing():
    global processing_state
    if processing_state["is_running"]:
        raise HTTPException(status_code=400, detail="处理已在进行中")
    
    # 启动后台任务
    asyncio.create_task(process_files_background())
    
    # 流式响应
    async def event_stream():
        # 发送初始消息
        yield f"data: {json.dumps({
            'log': '开始处理...',
            'progress': 0,
            'status': '开始处理',
            'completed': False
        })}\n\n"
        
        # 发送处理过程中的日志
        log_index = 0
        while processing_state["is_running"]:
            if len(processing_state['log']) > log_index:
                for log in processing_state['log'][log_index:]:
                    yield f"data: {json.dumps({
                        'log': log,
                        'progress': processing_state['progress'],
                        'status': processing_state['status'],
                        'completed': not processing_state['is_running']
                    })}\n\n"
                    await asyncio.sleep(0.1)
                log_index = len(processing_state['log'])
            await asyncio.sleep(0.5)
        
        # 发送剩余的日志
        if len(processing_state['log']) > log_index:
            for log in processing_state['log'][log_index:]:
                yield f"data: {json.dumps({
                    'log': log,
                    'progress': processing_state['progress'],
                    'status': processing_state['status'],
                    'completed': True
                })}\n\n"
                await asyncio.sleep(0.1)
        
        # 发送完成消息
        yield f"data: {json.dumps({
            'log': '处理完成',
            'progress': 100,
            'status': '处理完成',
            'completed': True
        })}\n\n"
    
    return StreamingResponse(event_stream(), media_type="text/event-stream")

# 停止处理
@app.post("/api/stop")
async def stop_processing():
    global processing_state
    processing_state["is_running"] = False
    processing_state["status"] = "已停止"
    return {"message": "处理已停止"}

# 获取处理状态
@app.get("/api/status")
async def get_status():
    return processing_state

# 根路径
@app.get("/")
async def read_root():
    return {"message": "知识库处理器 API 服务"}

if __name__ == "__main__":
    # 初始化数据库
    init_db()
    # 启动服务
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

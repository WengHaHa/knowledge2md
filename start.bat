@echo off
chcp 65001

echo 正在启动知识库处理器...

:: 安装Python依赖
echo 安装Python依赖...
pip install -r requirements.txt --upgrade

:: 安装前端依赖
echo 安装前端依赖...
npm install

:: 启动后端服务
echo 启动后端服务...
start "后端服务" python main.py

:: 等待后端服务启动
echo 等待后端服务启动...
timeout /t 3 /nobreak

:: 启动前端开发服务器
echo 启动前端服务...
start "前端服务" npm run dev

echo ====================================
echo 服务启动完成！
echo 前端地址: http://localhost:3000
echo 后端地址: http://localhost:8000
echo ====================================

echo 按任意键退出...
pause
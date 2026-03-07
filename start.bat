@echo on
chcp 65001

:: 启动脚本 - 知识库处理器

echo 正在启动知识库处理器...
echo ====================================

:: 检查Python是否安装
echo 检查Python是否安装...
python --version
if %errorlevel% neq 0 (
    echo 错误: Python未安装，请先安装Python 3.7+
    pause
    exit /b 1
)

:: 检查pip是否可用
echo 检查pip是否可用...
pip --version
if %errorlevel% neq 0 (
    echo 错误: pip不可用，请确保Python安装正确
    pause
    exit /b 1
)

:: 检查依赖是否安装
echo 检查依赖...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo 错误: 安装依赖失败
    pause
    exit /b 1
)

echo 依赖检查完成

:: 检查Node.js是否安装
echo 检查Node.js是否安装...
where npm >nul 2>&1
if %errorlevel% neq 0 (
    echo 错误: Node.js未安装，请先安装Node.js
    pause
    exit /b 1
)

:: 检查npm是否可用
echo 检查npm是否可用...
npm --version
if %errorlevel% neq 0 (
    echo 错误: npm不可用，请确保Node.js安装正确
    pause
    exit /b 1
)

:: 检查前端依赖是否安装
echo 检查前端依赖...
npm install
if %errorlevel% neq 0 (
    echo 错误: 安装前端依赖失败
    pause
    exit /b 1
)

echo 前端依赖检查完成

:: 启动后端服务
echo 启动后端服务...
start "后端服务" python main.py

:: 等待后端服务启动
echo 等待后端服务启动...
timeout /t 3 /nobreak >nul

:: 启动前端开发服务器
echo 启动前端服务...
start "前端服务" npm run dev

echo ====================================
echo 服务启动完成！
echo 前端地址: http://localhost:5173
echo 后端地址: http://localhost:8000
echo ====================================

echo 按任意键退出...
pause >nul

# Knowledge Base Processing Script - PowerShell Version (Fixed Encoding)

# Load .env file if exists
if (Test-Path ".env") {
    Write-Host "Loading configuration from .env file..." -ForegroundColor Cyan
    Get-Content ".env" | ForEach-Object {
        if (-not $_.Trim().StartsWith("#") -and $_.Trim() -ne "") {
            $key, $value = $_.Split("=", 2)
            if ($key -and $value) {
                $key = $key.Trim()
                $value = $value.Trim()
                [System.Environment]::SetEnvironmentVariable($key, $value, "Process")
            }
        }
    }
} else {
    Write-Host "Warning: .env file not found" -ForegroundColor Yellow
    Write-Host "Please create .env file from .env.example template" -ForegroundColor Yellow
    Write-Host ""
}

# Check environment variable
if (-not $env:DEEPSEEK_API_KEY) {
    Write-Host "Error: DEEPSEEK_API_KEY not found in .env file or environment variable" -ForegroundColor Red
    Write-Host "Please create .env file with your API key or run: `$env:DEEPSEEK_API_KEY = 'your-api-key'" -ForegroundColor Yellow
    exit 1
}

# Check Python dependencies
Write-Host "Checking Python dependencies..." -ForegroundColor Cyan
try {
    python -m pip show pypdf requests python-dotenv | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Installing dependencies..." -ForegroundColor Yellow
        python -m pip install pypdf requests python-dotenv -q
    }
} catch {
    Write-Host "Installing dependencies..." -ForegroundColor Yellow
    python -m pip install pypdf requests python-dotenv -q
}

# Check input directory
if (-not (Test-Path "knowledge_base_link")) {
    Write-Host "Error: Input directory 'knowledge_base_link' not found" -ForegroundColor Red
    Write-Host "Please create symbolic link: mklink /D knowledge_base_link D:\knowledge_base" -ForegroundColor Yellow
    exit 1
}

# Clear output directory
if (Test-Path "processed_knowledge") {
    Remove-Item -Path "processed_knowledge\*" -Recurse -Force -ErrorAction SilentlyContinue
}

# Run processor
Write-Host ""
Write-Host "Starting knowledge base processing..." -ForegroundColor Green
Write-Host ("=" * 50) -ForegroundColor Cyan

# Set console encoding to UTF-8 for Python output
$OutputEncoding = [System.Text.Encoding]::UTF8

# Run Python processor
python knowledge_processor.py

# Check results
if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host ("=" * 50) -ForegroundColor Green
    Write-Host "Processing completed successfully!" -ForegroundColor Green
    
    if (Test-Path "processed_knowledge\processing_report.md") {
        Write-Host ""
        Write-Host "Processing report summary:" -ForegroundColor Cyan
        
        # Read and display report safely
        try {
            $reportContent = Get-Content "processed_knowledge\processing_report.md" -Encoding UTF8
            # Display first 10 lines of report
            $reportContent | Select-Object -First 10 | ForEach-Object { Write-Host $_ }
        } catch {
            Write-Host "Report file exists but cannot be read properly" -ForegroundColor Yellow
        }
        
        $mdFiles = Get-ChildItem "processed_knowledge\*.md" -Exclude "processing_report.md"
        if ($mdFiles.Count -gt 0) {
            Write-Host ""
            Write-Host "Generated Markdown files ($($mdFiles.Count) files):" -ForegroundColor Cyan
            $mdFiles | ForEach-Object { Write-Host "  - $($_.Name)" -ForegroundColor Yellow }
        } else {
            Write-Host ""
            Write-Host "No Markdown files were generated" -ForegroundColor Yellow
        }
    }
} else {
    Write-Host ""
    Write-Host "Processing failed. Please check error messages above." -ForegroundColor Red
}

Write-Host ""
Write-Host "Output directory: processed_knowledge" -ForegroundColor Cyan

# Show final status
if (Test-Path "processed_knowledge\processing_report.md") {
    Write-Host "Processing report: processed_knowledge\processing_report.md" -ForegroundColor Cyan
}
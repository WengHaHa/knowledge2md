<template>
  <div class="app-container">
    <div class="header">
      <h1>📚 知识库处理器</h1>
    </div>
    <div class="main">
      <div class="card">
        <h2>配置设置</h2>
        <form @submit.prevent="submitForm">
          <div class="form-item">
            <label>DeepSeek API 密钥 *</label>
            <input type="password" v-model="form.apiKey" placeholder="请输入API密钥">
          </div>
          <div class="form-item">
            <label>输入目录</label>
            <input type="text" v-model="form.inputDir" placeholder="默认为 knowledge_input">
          </div>
          <div class="form-item">
            <label>输出目录</label>
            <input type="text" v-model="form.outputDir" placeholder="默认为 knowledge_output">
          </div>
          <div class="form-item">
            <label>启用并发处理</label>
            <input type="checkbox" v-model="form.concurrentProcessing">
          </div>
          <div class="form-item">
            <label>并发线程数</label>
            <input type="number" v-model="form.maxWorkers" min="1" max="10">
          </div>
          <div class="form-item">
            <label>启用增量处理</label>
            <input type="checkbox" v-model="form.incrementalProcessing">
          </div>
          <div class="form-item">
            <label>启用内容去重</label>
            <input type="checkbox" v-model="form.enableDeduplication">
          </div>
          <div class="form-item">
            <label>启用质量评分</label>
            <input type="checkbox" v-model="form.enableQualityScoring">
          </div>
          <div class="form-buttons">
            <button type="submit" class="primary-button">保存配置</button>
            <button type="button" @click="resetForm" class="secondary-button">重置</button>
          </div>
        </form>
      </div>

      <div class="card" v-if="configSaved">
        <h2>处理控制</h2>
        <div class="process-controls">
          <button @click="startProcessing" :disabled="isProcessing" class="primary-button">开始处理</button>
          <button @click="stopProcessing" :disabled="!isProcessing" class="danger-button">停止处理</button>
        </div>
        <div v-if="isProcessing || logContent">
          <h3>处理日志</h3>
          <div class="log-container">
            <pre>{{ logContent }}</pre>
          </div>
          <div class="progress-container">
            <div class="progress-bar">
              <div class="progress" :style="{ width: progress + '%' }"></div>
            </div>
            <div class="status-text">{{ statusText }}</div>
          </div>
        </div>
      </div>
    </div>
    <div class="footer">
      <p>© 2026 知识库处理器</p>
    </div>
  </div>
</template>

<script>
import axios from 'axios'

// 配置axios使用后端服务地址
axios.defaults.baseURL = 'http://localhost:8000'

export default {
  name: 'App',
  data() {
    return {
      form: {
        apiKey: '',
        inputDir: 'knowledge_input',
        outputDir: 'knowledge_output',
        concurrentProcessing: false,
        maxWorkers: 3,
        incrementalProcessing: true,
        enableDeduplication: true,
        enableQualityScoring: true
      },
      configSaved: false,
      isProcessing: false,
      logContent: '',
      progress: 0,
      statusText: ''
    }
  },
  methods: {
    submitForm() {
      console.log('submitForm方法被调用')
      console.log('提交配置:', this.form)
      console.log('axios.baseURL:', axios.defaults.baseURL)
      console.log('请求URL:', axios.defaults.baseURL + '/api/config')
      axios.post('/api/config', this.form)
        .then(response => {
          console.log('响应:', response)
          alert('配置保存成功！')
          this.configSaved = true
        })
        .catch(error => {
          console.error('错误:', error)
          console.error('错误详情:', error.response)
          alert('配置保存失败：' + error.message)
        })
    },
    resetForm() {
      this.form = {
        apiKey: '',
        inputDir: 'knowledge_input',
        outputDir: 'knowledge_output',
        concurrentProcessing: false,
        maxWorkers: 3,
        incrementalProcessing: true,
        enableDeduplication: true,
        enableQualityScoring: true
      }
    },
    startProcessing() {
      this.isProcessing = true
      this.logContent = '开始处理...\n'
      this.statusText = '处理中...'
      this.progress = 0
      
      // 用于去重的最后一条日志
      let lastLog = ''
      let fileCount = 0
      let processedCount = 0
      
      // 启动处理并获取实时日志
      const eventSource = new EventSource('/api/process')
      
      eventSource.onmessage = (event) => {
        const data = JSON.parse(event.data)
        if (data.log) {
          // 只添加非空日志且不重复
          const log = data.log.trim()
          if (log && log !== lastLog) {
            // 简化日志显示，只保留关键信息
            let simplifiedLog = log
            // 移除重复的时间戳（如果有）
            if (simplifiedLog.match(/\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] \[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]/)) {
              simplifiedLog = simplifiedLog.replace(/\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] \[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]/, '[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}]')
            }
            this.logContent += simplifiedLog + '\n'
            lastLog = log
            
            // 计算文件数量和处理进度
            if (simplifiedLog.includes('找到') && simplifiedLog.includes('个文件')) {
              const match = simplifiedLog.match(/找到 (\d+) 个文件/)
              if (match) {
                fileCount = parseInt(match[1])
              }
            } else if (simplifiedLog.includes('成功处理') || simplifiedLog.includes('处理失败')) {
              processedCount++
              if (fileCount > 0) {
                this.progress = Math.min(100, Math.round((processedCount / fileCount) * 100))
              }
            }
            
            // 滚动到日志底部
            setTimeout(() => {
              const logContainer = document.querySelector('.log-container')
              if (logContainer) {
                logContainer.scrollTop = logContainer.scrollHeight
              }
            }, 100)
          }
        }
        if (data.status) {
          // 简化状态显示，只保留关键状态
          let simplifiedStatus = data.status
          // 移除时间戳
          if (simplifiedStatus.startsWith('[')) {
            simplifiedStatus = simplifiedStatus.split('] ')[1]
          }
          // 只显示关键状态
          if (simplifiedStatus.includes('处理中') || simplifiedStatus.includes('成功') || simplifiedStatus.includes('失败') || simplifiedStatus.includes('完成')) {
            this.statusText = simplifiedStatus
          }
        }
        if (data.completed) {
          eventSource.close()
          this.isProcessing = false
          this.statusText = '处理完成'
          this.progress = 100
          // 不使用 alert，而是在日志中显示处理完成信息
          if (this.logContent.indexOf('处理完成！') === -1) {
            this.logContent += '处理完成！\n'
          }
          // 保存日志到本地存储，以便用户可以查看历史日志
          localStorage.setItem('processingLog', this.logContent)
        }
      }
      
      eventSource.onerror = () => {
        eventSource.close()
        this.isProcessing = false
        this.statusText = '处理失败'
        // 不使用 alert，而是在日志中显示错误信息
        if (this.logContent.indexOf('处理过程中发生错误') === -1) {
          this.logContent += '处理过程中发生错误\n'
        }
        // 保存日志到本地存储
        localStorage.setItem('processingLog', this.logContent)
      }
    },
    stopProcessing() {
      axios.post('/api/stop')
        .then(response => {
          this.logContent += '处理已停止\n'
          this.isProcessing = false
          this.statusText = '已停止'
        })
        .catch(error => {
          this.logContent += '停止处理失败：' + error.message + '\n'
        })
    }
  }
}
</script>

<style scoped>
.app-container {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background-color: #f5f7fa;
  font-family: Arial, sans-serif;
}

.header {
  background-color: #409eff;
  color: white;
  padding: 20px;
  text-align: center;
}

.header h1 {
  margin: 0;
  font-size: 24px;
}

.main {
  flex: 1;
  padding: 20px;
  max-width: 800px;
  margin: 0 auto;
  width: 100%;
}

.card {
  background-color: white;
  border-radius: 8px;
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.1);
  padding: 20px;
  margin-bottom: 20px;
}

.card h2 {
  margin-top: 0;
  margin-bottom: 20px;
  color: #333;
}

.form-item {
  margin-bottom: 15px;
}

.form-item label {
  display: block;
  margin-bottom: 5px;
  font-weight: bold;
  color: #666;
}

.form-item input {
  width: 100%;
  padding: 8px;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  font-size: 14px;
}

.form-item input[type="checkbox"] {
  width: auto;
  margin-right: 5px;
}

.form-buttons {
  margin-top: 20px;
  display: flex;
  gap: 10px;
}

.process-controls {
  margin-bottom: 20px;
  display: flex;
  gap: 10px;
}

button {
  padding: 10px 20px;
  border: none;
  border-radius: 4px;
  font-size: 14px;
  cursor: pointer;
}

.primary-button {
  background-color: #409eff;
  color: white;
}

.secondary-button {
  background-color: #606266;
  color: white;
}

.danger-button {
  background-color: #f56c6c;
  color: white;
}

button:disabled {
  background-color: #c0c4cc;
  cursor: not-allowed;
}

.log-container {
  background-color: #f0f0f0;
  padding: 10px;
  border-radius: 4px;
  max-height: 300px;
  overflow-y: auto;
  margin-bottom: 20px;
}

.log-container pre {
  margin: 0;
  font-family: Consolas, Monaco, 'Andale Mono', monospace;
  font-size: 12px;
  line-height: 1.4;
}

.progress-container {
  margin-top: 20px;
}

.progress-bar {
  width: 100%;
  height: 20px;
  background-color: #f0f0f0;
  border-radius: 10px;
  overflow: hidden;
  margin-bottom: 10px;
}

.progress {
  height: 100%;
  background-color: #409eff;
  border-radius: 10px;
  transition: width 0.3s ease;
}

.status-text {
  text-align: center;
  color: #666;
  font-size: 14px;
}

.footer {
  background-color: #f0f2f5;
  padding: 10px;
  text-align: center;
  color: #909399;
  font-size: 12px;
}
</style>
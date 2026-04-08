# RPA API 接口文档

## 概述

RPA API 服务提供 HTTP RESTful 接口，允许外部系统直接调用 RPA 自动化任务。通过 API 调用的任务会**直接放入 RPA 队列**执行，**跳过插件入口**，实现快速响应。

## 快速开始

### 1. 配置启用

在 `config.yaml` 中添加配置：

```yaml
rpa_api:
  enabled: true
  host: 0.0.0.0
  port: 8001
```

### 2. 安装依赖

```bash
pip install fastapi uvicorn
```

### 3. 启动服务

服务会在 Bot 启动时自动运行。

---

## 接口地址

| 项目 | 默认值 |
|------|--------|
| 服务地址 | `http://0.0.0.0:8001` |
| 基础路径 | `/api/v1/` |

---

## 接口列表

### 1. 发送文本消息

**POST** `/api/v1/send/text`

向指定联系人或群组发送文本消息。

**请求报文：**

```json
{
    "recipient_name": "张三",
    "message": "你好，这是一条测试消息",
    "at_user_name": null
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| recipient_name | string | 是 | 接收者名称（联系人或群名） |
| message | string | 是 | 消息内容 |
| at_user_name | string | 否 | @用户名称（仅群聊有效） |

**响应报文：**

```json
{
    "success": true,
    "message": "消息已提交到队列，等待发送",
    "task_id": "task_1712563200000_1",
    "data": {
        "recipient_name": "张三",
        "message_length": 12
    }
}
```

**cURL 示例：**

```bash
curl -X POST "http://localhost:8001/api/v1/send/text" \
  -H "Content-Type: application/json" \
  -d '{"recipient_name": "张三", "message": "你好，这是一条测试消息"}'
```

---

### 2. 发送文件

**POST** `/api/v1/send/file`

向指定联系人发送文件。

**请求报文：**

```json
{
    "recipient_name": "张三",
    "file_path": "C:/path/to/file.pdf"
}
```

**响应报文：**

```json
{
    "success": true,
    "message": "文件发送任务已提交到队列",
    "task_id": "task_1712563200000_2",
    "data": {
        "recipient_name": "张三",
        "file_path": "C:/path/to/file.pdf"
    }
}
```

---

### 3. 撤回消息

**POST** `/api/v1/recall/message`

撤回指定联系人或群组中的消息。

#### 方式一：按消息内容撤回

```json
{
    "contact_name": "张三",
    "message_text": "要撤回的消息内容",
    "similarity": 0.6
}
```

#### 方式二：按关键词撤回

```json
{
    "contact_name": "张三",
    "keyword": "关键词"
}
```

#### 方式三：撤回最新消息

```json
{
    "contact_name": "张三",
    "recall_latest": true
}
```

**参数说明：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| contact_name | string | 是 | 联系人或群组名称 |
| message_text | string | 否 | 要撤回的消息内容（精确匹配） |
| keyword | string | 否 | 关键词（模糊匹配） |
| recall_latest | boolean | 否 | 是否撤回最新消息 |
| similarity | float | 否 | 相似度阈值（0.0-1.0），默认 0.6 |

**注意：** 必须提供 `message_text`、`keyword` 或 `recall_latest` 中的一个。

**响应报文：**

```json
{
    "success": true,
    "message": "撤回任务已提交到队列",
    "task_id": "task_1712563200000_3",
    "data": {
        "contact_name": "张三",
        "recall_type": "text"
    }
}
```

**recall_type 取值：**
- `latest`: 撤回最新消息
- `text`: 按消息内容撤回
- `keyword`: 按关键词撤回

---

### 4. 健康检查

**GET** `/health`

```json
{
    "status": "healthy"
}
```

---

### 5. 队列状态

**GET** `/status`

```json
{
    "queue_size": 5,
    "task_counter": 123
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| queue_size | int | 当前队列中的任务数量 |
| task_counter | int | 累计处理的任务总数 |

---

## 完整示例

### Python

```python
import requests

base_url = "http://localhost:8001"

# 发送文本消息
requests.post(f"{base_url}/api/v1/send/text", json={
    "recipient_name": "张三",
    "message": "你好"
})

# 撤回最新消息
requests.post(f"{base_url}/api/v1/recall/message", json={
    "contact_name": "张三",
    "recall_latest": True
})

# 按关键词撤回
requests.post(f"{base_url}/api/v1/recall/message", json={
    "contact_name": "张三",
    "keyword": "测试"
})

# 查看队列状态
requests.get(f"{base_url}/status")
```

### JavaScript

```javascript
const baseUrl = 'http://localhost:8001';

// 发送文本消息
fetch(`${baseUrl}/api/v1/send/text`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
        recipient_name: '张三',
        message: '你好'
    })
});

// 撤回最新消息
fetch(`${baseUrl}/api/v1/recall/message`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
        contact_name: '张三',
        recall_latest: true
    })
});
```

---

## 工作流程

```
┌────────────────────────────────────────────────────────────────────┐
│                        消息监听流程（原有）                          │
│                                                                    │
│  数据库监听 ──► 消息队列 ──► 插件管理器 ──► 各插件处理                 │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│                        API 调用流程（新增）                          │
│                                                                    │
│  HTTP请求 ──► RPA API ──► RPA任务队列 ──► RPA执行器                   │
│                    │                        │                     │
│                    └── 跳过插件入口 ────────┘                     │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

---

## 注意事项

1. **任务队列共享**：API 调用和消息监听产生的任务共用同一个 RPA 队列，保证执行顺序
2. **跳过插件**：API 调用直接进入队列，不经过插件处理
3. **速率限制**：RPA 执行器内置速率限制，防止操作过快
4. **撤回限制**：微信消息只能在发送后 2 分钟内撤回

# RPA API 服务

## 概述

RPA API 服务提供 HTTP RESTful 接口，允许外部系统直接调用 RPA 自动化任务。所有通过 API 调用的任务会直接放入 RPA 任务队列执行，**跳过插件入口**，实现快速响应。

## 配置

在 `config.yaml` 中添加以下配置：

```yaml
rpa_api:
  enabled: true
  host: "0.0.0.0"
  port: 8001
```

## 接口地址

### 基础信息

| 项目 | 值 |
|------|-----|
| 服务地址 | `http://<host>:<port>` |
| 默认端口 | 8001 |
| 协议 | HTTP |
| 响应格式 | JSON |

### 端点列表

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 服务信息 |
| GET | `/health` | 健康检查 |
| GET | `/status` | 队列状态 |
| POST | `/api/v1/send/text` | 发送文本消息 |
| POST | `/api/v1/send/file` | 发送文件 |
| POST | `/api/v1/recall/message` | 撤回消息 |

---

## API 详情

### 健康检查

**GET** `/health`

检查服务是否正常运行。

**响应示例：**

```json
{
  "status": "healthy"
}
```

### 队列状态

**GET** `/status`

获取 RPA 任务队列的当前状态。

**响应示例：**

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

### 发送文本消息

**POST** `/api/v1/send/text`

向指定联系人或群组发送文本消息。

**请求头：**

```
Content-Type: application/json
```

**请求体：**

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

**响应示例：**

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

### 发送文件

**POST** `/api/v1/send/file`

向指定联系人发送文件。

**请求体：**

```json
{
  "recipient_name": "张三",
  "file_path": "C:/path/to/file.pdf"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| recipient_name | string | 是 | 接收者名称 |
| file_path | string | 是 | 文件路径（本地路径或 URL） |

**响应示例：**

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

**cURL 示例：**

```bash
curl -X POST "http://localhost:8001/api/v1/send/file" \
  -H "Content-Type: application/json" \
  -d '{"recipient_name": "张三", "file_path": "C:/path/to/file.pdf"}'
```

---

### 撤回消息

**POST** `/api/v1/recall/message`

撤回指定联系人或群组中的消息。支持三种撤回方式。

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

**请求参数：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| contact_name | string | 是 | 联系人或群组名称 |
| message_text | string | 否 | 要撤回的消息内容（精确匹配） |
| keyword | string | 否 | 关键词（模糊匹配） |
| recall_latest | boolean | 否 | 是否撤回最新消息 |
| similarity | float | 否 | 相似度阈值（0.0-1.0），默认 0.6 |

**注意：** 必须提供 `message_text`、`keyword` 或 `recall_latest` 中的一个。

**响应示例：**

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

**cURL 示例：**

```bash
# 撤回包含特定内容的消息
curl -X POST "http://localhost:8001/api/v1/recall/message" \
  -H "Content-Type: application/json" \
  -d '{"contact_name": "张三", "message_text": "测试消息", "similarity": 0.6}'

# 按关键词撤回
curl -X POST "http://localhost:8001/api/v1/recall/message" \
  -H "Content-Type: application/json" \
  -d '{"contact_name": "张三", "keyword": "关键词"}'

# 撤回最新消息
curl -X POST "http://localhost:8001/api/v1/recall/message" \
  -H "Content-Type: application/json" \
  -d '{"contact_name": "张三", "recall_latest": true}'
```

---

## 响应格式

所有 API 响应均为 JSON 格式：

```json
{
  "success": true,
  "message": "操作说明",
  "task_id": "任务ID（用于跟踪）",
  "data": {
    // 附加数据
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| success | boolean | 操作是否成功 |
| message | string | 操作结果描述 |
| task_id | string | 任务ID（可用于日志跟踪） |
| data | object | 附加数据（可选） |

---

## 错误处理

当操作失败时，响应中的 `success` 将为 `false`：

```json
{
  "success": false,
  "message": "错误原因描述",
  "task_id": null
}
```

常见错误：
- 参数缺失
- 联系人不存在
- 消息未找到（撤回时）
- 队列已满

---

## 使用流程

```
┌─────────────┐     HTTP POST      ┌──────────────┐     直接放入     ┌─────────────┐
│   外部系统   │ ─────────────────► │   RPA API    │ ───────────────► │  RPA队列    │
│  (HTTP调用)  │                    │   Service    │                  │             │
└─────────────┘                    └──────────────┘                  └──────┬──────┘
                                                                            │
                                                                            ▼
                                                                    ┌─────────────┐
                                                                    │ RPA执行器   │
                                                                    │ (顺序执行)  │
                                                                    └─────────────┘
```

---

## 依赖

需要安装以下依赖：

```toml
# pyproject.toml
dependencies = [
    "fastapi>=0.100.0",
    "uvicorn>=0.23.0",
]
```

如未安装，API 服务将不会启动，但不影响其他功能。

---

## 示例代码

### Python

```python
import requests

# 发送文本消息
response = requests.post(
    "http://localhost:8001/api/v1/send/text",
    json={
        "recipient_name": "张三",
        "message": "你好"
    }
)
print(response.json())

# 撤回消息
response = requests.post(
    "http://localhost:8001/api/v1/recall/message",
    json={
        "contact_name": "张三",
        "recall_latest": True
    }
)
print(response.json())
```

### JavaScript/Node.js

```javascript
// 发送文本消息
fetch('http://localhost:8001/api/v1/send/text', {
    method: 'POST',
    headers: {
        'Content-Type': 'application/json'
    },
    body: JSON.stringify({
        recipient_name: '张三',
        message: '你好'
    })
})
.then(res => res.json())
.then(data => console.log(data));
```

### cURL

```bash
# 发送消息
curl -X POST http://localhost:8001/api/v1/send/text \
  -H "Content-Type: application/json" \
  -d '{"recipient_name": "张三", "message": "测试消息"}'

# 查看队列状态
curl http://localhost:8001/status
```
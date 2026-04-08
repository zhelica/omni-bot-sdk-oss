# 消息撤回功能

本功能实现微信消息的自动化撤回，支持通过接口调用或直接 API 使用。

## 功能特性

- **三种撤回方式**：按消息内容、按关键词、撤回最新消息
- **OCR 识别**：自动识别聊天区域的消息内容
- **智能定位**：通过图像处理定位目标消息位置
- **右键菜单自动化**：模拟鼠标操作实现右键撤回

## 核心组件

### 1. MessageRecallController (`omni_bot_sdk/rpa/message_recall.py`)

消息撤回控制器，整合所有撤回相关操作。

```python
from omni_bot_sdk.rpa.message_recall import MessageRecallController

controller = MessageRecallController(window_manager)
```

### 2. MessageRecognizer

消息识别器，通过 OCR 扫描聊天区域识别消息。

```python
# 扫描消息
messages = recognizer.scan_messages(max_count=30)

# 按内容查找
message = recognizer.find_message_by_text(
    target_text="Hello",
    similarity_threshold=0.6,
    only_self=True
)
```

### 3. ContextMenuHandler

右键菜单处理器，处理菜单识别和点击。

```python
# 右键点击并撤回
handler.right_click(x, y)
handler.click_recall_option()
```

## API 使用

### MCP 接口

在支持 MCP 协议的工具中调用：

```python
# 撤回包含特定内容的消息
recall_message(
    contact_name="张三",
    message_text="Hello World"
)

# 通过关键词撤回
recall_message(
    contact_name="张三",
    keyword="测试"
)

# 撤回最新消息
recall_message(
    contact_name="张三",
    recall_latest=True
)

# 自定义相似度阈值
recall_message(
    contact_name="张三",
    message_text="Hello",
    similarity=0.8
)
```

### Python API

```python
from omni_bot_sdk.rpa.message_recall import MessageRecallController

# 初始化
controller = MessageRecallController(window_manager)

# 撤回特定消息
controller.recall_by_text(
    contact_name="联系人名称",
    message_text="消息内容",
    similarity_threshold=0.6,
    max_retries=2
)

# 撤回最新消息
controller.recall_latest_message(
    contact_name="联系人名称",
    max_retries=2
)

# 按关键词撤回
controller.recall_by_keyword(
    contact_name="联系人名称",
    keyword="关键词",
    max_retries=2
)

# 批量撤回
controller.recall_multiple_by_keyword(
    contact_name="联系人名称",
    keyword="关键词",
    max_count=10,
    interval=1.0
)
```

## 工作流程

```
┌─────────────────┐
│  1. 搜索联系人  │
│  切换到聊天界面 │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  2. OCR扫描消息  │
│  识别消息内容    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  3. 定位消息位置 │
│  过滤自己的消息  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  4. 右键点击    │
│  触发上下文菜单  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  5. OCR识别菜单  │
│  找到"撤回"选项  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  6. 点击撤回    │
│  完成操作        │
└─────────────────┘
```

## 配置参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| max_retries | int | 2 | 最大重试次数 |
| similarity_threshold | float | 0.6 | 消息文本相似度阈值 |
| menu_wait_time | float | 0.6 | 菜单出现等待时间（秒） |
| right_click_duration | float | 0.1 | 右键点击持续时间 |

## 注意事项

### 微信限制
- **时间限制**：普通消息只能在发送后 **2 分钟内** 撤回
- 超过 2 分钟的消息会撤回失败

### OCR 识别
- 依赖 RapidOCR 或远程 OCR 服务
- 建议在清晰、无遮挡的界面环境下使用
- 可调整 `similarity_threshold` 适应不同界面

### 消息过滤
- 默认只撤回**自己发送**的消息
- 他人消息的撤回选项不可用（微信限制）

## 错误处理

| 错误情况 | 处理方式 |
|---------|---------|
| 联系人不存在 | 切换会话失败，返回 False |
| 消息未找到 | 降低相似度阈值重试 |
| 右键菜单未出现 | 等待更长时间后重试 |
| 撤回选项未识别 | 保存截图供调试，关闭菜单 |
| 消息已超时 | 提示用户无法撤回 |

## 示例代码

完整示例请参考：`examples/message_recall_example.py`

```python
from omni_bot_sdk.rpa.message_recall import MessageRecallController

# 完整使用流程
def recall_message_example(window_manager, contact_name, message_text):
    controller = MessageRecallController(window_manager)

    success = controller.recall_by_text(
        contact_name=contact_name,
        message_text=message_text,
        similarity_threshold=0.7,
        max_retries=3
    )

    if success:
        print(f"消息 '{message_text}' 撤回成功")
    else:
        print(f"消息 '{message_text}' 撤回失败")

    return success
```

"""
消息撤回功能使用示例。

本模块展示如何通过 API 调用消息撤回功能。
"""

# ============================================================
# 方式一：通过 MCP 接口调用（推荐）
# ============================================================
#
# 在 MCP 客户端或支持 MCP 协议的工具中调用：
#
# 1. 撤回包含指定内容的消息
#    recall_message(
#        contact_name="张三",
#        message_text="Hello World"
#    )
#
# 2. 通过关键词撤回消息
#    recall_message(
#        contact_name="张三",
#        keyword="测试"
#    )
#
# 3. 撤回最新消息
#    recall_message(
#        contact_name="张三",
#        recall_latest=True
#    )
#
# 4. 自定义相似度阈值
#    recall_message(
#        contact_name="张三",
#        message_text="Hello",
#        similarity=0.8
#    )


# ============================================================
# 方式二：直接使用 Python API
# ============================================================
"""
from omni_bot_sdk.rpa.message_recall import MessageRecallController

# 假设你已经有了 window_manager 实例
recall_controller = MessageRecallController(window_manager)

# 撤回包含特定文本的消息
recall_controller.recall_by_text(
    contact_name="张三",
    message_text="Hello World"
)

# 撤回最新消息
recall_controller.recall_latest_message(
    contact_name="李四"
)

# 通过关键词撤回
recall_controller.recall_by_keyword(
    contact_name="王五",
    keyword="测试"
)

# 批量撤回（撤回所有匹配关键词的消息）
recall_controller.recall_multiple_by_keyword(
    contact_name="群名称",
    keyword="关键词",
    max_count=10,
    interval=1.0
)
"""


# ============================================================
# 方式三：通过 RPA 动作队列
# ============================================================
"""
from omni_bot_sdk.rpa.action_handlers import RecallMessageAction, RPAActionType

# 创建撤回动作
action = RecallMessageAction(
    contact_name="张三",
    message_text="要撤回的消息内容",
    similarity=0.6
)

# 将动作放入 RPA 任务队列
rpa_task_queue.put(action)
"""


# ============================================================
# 撤回限制说明
# ============================================================
"""
1. 微信消息撤回限制：
   - 普通消息：可在 2 分钟内撤回
   - 超过 2 分钟的消息无法撤回

2. 消息识别说明：
   - 使用 OCR 识别消息内容
   - 支持模糊匹配（相似度阈值可调）
   - 只撤回自己发送的消息

3. 右键菜单识别：
   - 微信界面可能因版本不同而有差异
   - OCR 可能受界面颜色干扰
   - 必要时可调整相似度阈值
"""

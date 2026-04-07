"""
窗口管理模块。
提供微信窗口的查找、激活、区域分析、会话切换等自动化能力。
"""

import logging
import time
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
import pyautogui
import win32gui
from omni_bot_sdk.rpa.image_processor import ImageProcessor
from omni_bot_sdk.rpa.ocr_processor import OCRProcessor
from omni_bot_sdk.utils.helpers import (
    get_bbox_center_exact,
    get_center_point,
    set_clipboard_text,
)
from omni_bot_sdk.utils.mouse import human_like_mouse_move
from omni_bot_sdk.utils.size_config import suggest_size

pyautogui.FAILSAFE = False


class MenuTypeEnum(Enum):
    """
    菜单类型
    """

    Chat = "聊天"
    Contact = "联系人"
    Favorite = "收藏"
    Friend = "朋友圈"

    FriendNotification = "朋友圈通知"
    FriendSend = "朋友圈发送"
    FrendRefresh = "朋友圈刷新"


class WindowTypeEnum(Enum):
    """
    对使用到的窗口进行归类，方便查找，只使用title不可靠
    似乎微信4.x 的类名都是 Qt51514QWindowIcon，切记不可直接用类名，万一更新Qt版本就完蛋拉~
    """

    MainWindow = "MainWindow"  # <Win32Window left="0", top="0", width="1008", height="1360", title="微信">
    InviteMemberWindow = "InviteMemberWindow"  # <Win32Window left="34", top="310", width="938", height="738", title="微信添加群成员">
    InviteConfirmWindow = "InviteConfirmWindow"  # <Win32Window left="298", top="536", width="413", height="288", title="Weixin">
    InviteResonWindow = "InviteResonWindow"  # <Win32Window left="298", top="505", width="413", height="350", title="Weixin">
    RemoveMemberWindow = "RemoveMemberWindow"  # <Win32Window left="34", top="310", width="938", height="738", title="微信移出群成员">
    AddFriendWindow = "AddFriendWindow"  # <Win32Window left="274", top="312", width="450", height="825", title="通过朋友验证">
    UnableInviteWindow = "UnableInviteWindow"  # <Win32Window left="298", top="559", width="413", height="243", title="Weixin">
    SearchHistoryWindow = "SearchHistoryWindow"  # <Win32Window left="214", top="372", width="913", height="800", title="搜索聊天记录">
    FriendWindow = "FriendWindow"  # <Win32Window left="1015", top="1", width="688", height="1358", title="朋友圈">
    PublicAnnouncementWindow = "PublicAnnouncementWindow"  # <Win32Window left="158", top="278", width="709", height="812", title="“微信 GUI RPA 开发群”的群公告">
    RoomInputConfirmBox = "RoomInputConfirmBox"  # 窗口类名: Qt51514QWindowIcon <Win32Window left="298", top="556", width="413", height="246", title="Weixin">
    MenuWindow = "MenuWindow"  # <Win32Window left="0", top="0", width="1008", height="1360", title="Weixin">
    # ToolSaveBitsWindow = "ToolSaveBitsWindow"  # 搜索联系人也是这个 <Win32Window left="61", top="61", width="460", height="128", title="Weixin">
    SearchContactWindow = "SearchContactWindow"  # <Win32Window left="61", top="61", width="460", height="128", title="Weixin">


class WindowManager:
    """窗口管理器，处理所有窗口相关的操作"""

    # TODO 重新登陆以后，需要重新初始化，否则的话，window都变了，操作无效
    def __init__(
        self,
        image_processor: ImageProcessor,
        ocr_processor: OCRProcessor,
        rpa_config: dict = None,
    ):
        self.logger = logging.getLogger(__name__)
        self.size_config = suggest_size()
        self.weixin_windows = {}
        self.current_window = None
        self.ROOM_SIDE_BAR_WIDTH = 0
        self.MSG_TOP_X = 0
        self.MSG_TOP_Y = 0
        self.MSG_WIDTH = 0
        self.MSG_HEIGHT = 0
        self.SIDE_BAR_WIDTH = 0
        self.SESSION_LIST_WIDTH = 0
        self.TITLE_BAR_HEIGHT = 0
        self.ICON_CONFIGS = {
            "send_button": {
                "name": "发送按钮",
                "color": "red",
                "position": None,
            },
            "search_icon": {
                "name": "搜索输入框",
                "color": "yellow",
                "position": None,
            },
        }
        self.image_processor = image_processor
        self.ocr_processor = ocr_processor
        self.last_switch_session = None
        self.last_switch_session_time = None
        self.rpa_config = rpa_config or {}
        # 直接将常用配置项赋值为实例属性，便于后续直接访问
        self.action_delay = self.rpa_config.get("action_delay", 0.3)
        self.side_bar_delay = self.rpa_config.get("side_bar_delay", 3)
        self.scroll_delay = self.rpa_config.get("scroll_delay", 1)
        self.switch_contact_delay = self.rpa_config.get("switch_contact_delay", 0.3)
        self.window_show_delay = self.rpa_config.get("window_show_delay", 1.5)
        self.window_margin = self.rpa_config.get("window_margin", 20)
        self.room_action_offset = tuple(
            self.rpa_config.get("room_action_offset", (0, -30))
        )
        self.search_contact_offset = tuple(
            self.rpa_config.get("search_contact_offset", (0, 40))
        )
        self.color_ranges = self.rpa_config.get("color_ranges", {})
        # 相对位置比例配置（适用于不同尺寸窗口）
        # 这些值会在初始化时自动校准，基于实际找到的元素位置计算
        self._position_ratios = {
            "search_box": {"x_ratio": 0.72, "y_ratio": 0.04},  # 搜索框相对位置（会动态校准）
            "send_button": {
                "x_offset": -80,
                "y_offset": -40,
                "base": "msg_area",  # 基准改为消息区域右下角
            },
            "input_box": {"x_offset": 50, "y_offset": 0},  # 输入框相对发送按钮
        }
        # 存储实际校准后的位置（用于计算真实比例）
        self._calibrated_positions = {}
        # 模板匹配阈值
        self._template_threshold = self.rpa_config.get("template_threshold", 0.8)
        # 缓存的模板图片（用于模板匹配）
        self._cached_templates = {}

    def activate_input_box(self, offset_x: int = 0) -> bool:
        """
        激活输入框
        这里的offset时为了处理多个窗口，目前没有使用
        点击两次是为了处理有可能的存在的侧边栏没有关闭的情况，暂时不使用vl模型解决
        """
        try:
            self.logger.info("激活输入框...")
            # 不要重新激活窗口，避免丢失焦点
            # switch_session 后窗口已经在前台，只需要点击输入框即可

            send_bbox = self.get_send_button_bbox()
            self.logger.info("发送按钮 bbox（已校验）: %s", send_bbox)
            send_x, send_y = get_bbox_center_exact(send_bbox)
            # 输入框在发送按钮上方约 30-40px，避免点击到按钮本身
            input_x = send_x - 70
            input_y = send_y - 35
            # 确保点击位置在消息区域内
            input_x = max(self.MSG_TOP_X + 30, min(input_x, self.size_config.width - 50))
            input_y = max(self.MSG_TOP_Y + 80, min(input_y, self.size_config.height - 100))

            self.logger.info("发送按钮中心: ({}, {}), 点击输入框位置: ({}, {})".format(
                send_x, send_y, input_x, input_y))
            # 搜索浮层关闭后，聊天已加载，等待一小段时间确保 UI 完全渲染
            time.sleep(0.25)
            pyautogui.click(input_x, input_y)
            # 仅单次点击，避免同位置两次点击被微信识别为双击导致弹出窗口
            time.sleep(self.action_delay)
            self.logger.info("输入框激活完成")
            return True

        except Exception as e:
            self.logger.error(f"激活输入框时出错: {str(e)}")
            return False

    def get_icon_position(self, icon_name: str) -> Optional[Dict]:
        """获取图标位置"""
        if icon_name in self.ICON_CONFIGS:
            return self.ICON_CONFIGS[icon_name]["position"]
        return None

    def _is_plausible_send_button_bbox(self, bbox: List[int]) -> bool:
        """过滤像素扫描失败产生的「竖条」或全窗错误框。"""
        if not bbox or len(bbox) != 4:
            return False
        x1, y1, x2, y2 = int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])
        w, h = x2 - x1, y2 - y1
        if w < 24 or h < 18:
            return False
        if w > 400 or h > 220:
            return False
        # 按钮应贴在窗口右下角：y2 接近窗口底部，y1 在窗口下半区偏上
        win_h = self.size_config.height
        win_w = self.size_config.width
        if y2 < int(win_h * 0.80):
            return False  # y2 必须在窗口下半
        if y1 < int(win_h * 0.60) or y1 > int(win_h * 0.97):
            return False  # y1 在窗口 60%~97% 之间才合理
        if x2 > win_w - 2 or x1 > win_w - 20:
            return False  # x2 必须贴右边缘
        return True

    def _fallback_send_button_bbox(self) -> List[int]:
        """
        通过白色输入框右边缘定位发送按钮，不依赖按钮颜色。
        策略：从消息区域底部截图，从下往上扫宽度>200px的白色行
        → 得到输入框右边缘 → 按钮中心=右边缘+43px。
        不受按钮灰色/侧边栏绿色干扰，不依赖缓存的 MSG_HEIGHT。
        """
        msg_x = self.MSG_TOP_X
        msg_y = max(self.MSG_TOP_Y, int(self.size_config.height * 0.65))
        msg_w = self.MSG_WIDTH if self.MSG_WIDTH > 0 else int(self.size_config.width * 0.58)
        msg_h = int(self.size_config.height * 0.35)

        try:
            screenshot = self.image_processor.take_screenshot(
                region=[msg_x, msg_y, msg_w, msg_h]
            )
            if not screenshot:
                raise ValueError("截图返回 None")

            pixels = screenshot.load()
            w, h = screenshot.size

            # 从截图底部往上扫，找宽度>200px的白色横条（输入框）
            white_min_x = None
            white_max_x = None
            white_max_y = None  # 白色区域最底行（截图内局部坐标）
            step = 2
            for ly in range(h - 1, max(0, h // 3), -step):
                row_min = None
                row_max = None
                for lx in range(step, w - step, step):
                    r, g, b = pixels[lx, ly]
                    if r > 240 and g > 240 and b > 240:
                        if row_min is None:
                            row_min = lx
                        row_max = lx
                if row_max is not None and (row_max - row_min) > 200:
                    white_min_x = row_min
                    white_max_x = row_max
                    white_max_y = ly
                    break

            if white_max_x is None or white_max_y is None:
                self.logger.warning("_fallback: 未找到宽度>200px的白色输入框")
                raise ValueError("白色输入框未找到")

            # 白色输入框右边缘（截图内局部）→ 绝对坐标
            input_right_abs = msg_x + white_max_x
            input_bottom_abs = msg_y + white_max_y

            self.logger.info(
                "_fallback: 输入框右边缘局部=%d 绝对=%d, 底部局部=%d 绝对=%d",
                white_max_x, input_right_abs, white_max_y, input_bottom_abs,
            )

            # 按钮紧贴在输入框右侧（留1~3px间距），约80~96px宽，30~44px高
            # 按钮中心 ≈ 输入框右边缘 + 43（half_w），居中于输入框中部
            button_center_x = input_right_abs + 43
            button_center_y = input_bottom_abs - 18

            half_w = 44
            half_h = 18
            x1 = int(max(msg_x + 24, button_center_x - half_w))
            y1 = int(max(msg_y, button_center_y - half_h))
            x2 = int(min(self.size_config.width - 6, button_center_x + half_w))
            y2 = int(min(self.size_config.height - 6, button_center_y + half_h))

            if x2 <= x1 + 10 or y2 <= y1:
                raise ValueError("bbox 无效")

            self.logger.info(
                "_fallback 成功: [x1=%d, y1=%d, x2=%d, y2=%d], 按钮中心=(%d,%d)",
                x1, y1, x2, y2, button_center_x, button_center_y,
            )
            return [x1, y1, x2, y2]

        except Exception as e:
            self.logger.warning("_fallback 失败: %s，使用比例估算", e)
            win_w = self.size_config.width
            win_h = self.size_config.height
            x2 = win_w - 8
            y2 = win_h - 8
            x1 = max(msg_x + 24, x2 - 88)
            y1 = max(int(win_h * 0.80), y2 - 36)
            return [x1, y1, x2, y2]

    def get_send_button_bbox(self) -> List[int]:
        """
        返回可信的发送按钮 [x1,y1,x2,y2]。

        策略：
        1. 先检查缓存是否有效
        2. 如果缓存无效，尝试 fallback 计算
        3. 如果 fallback 结果尺寸仍然不合理，使用初始化时的比例估算
        """
        raw = self.get_icon_position("send_button")

        # 检查缓存是否有效
        if raw and self._is_plausible_send_button_bbox(raw):
            return list(map(int, raw))

        # 缓存无效，尝试 fallback 计算
        try:
            fb = self._fallback_send_button_bbox()
            # 检查 fallback 结果是否合理
            if self._is_plausible_send_button_bbox(fb):
                self.ICON_CONFIGS["send_button"]["position"] = fb
                self.logger.info("fallback 计算的发送按钮有效: %s", fb)
                return list(map(int, fb))
            else:
                self.logger.warning("fallback 计算的发送按钮仍无效: %s，尝试比例估算", fb)
        except Exception as e:
            self.logger.warning("fallback 计算失败: %s，尝试比例估算", e)

        # fallback 失败或结果不合理，使用比例估算（基于窗口右下角）
        win_w = self.size_config.width
        win_h = self.size_config.height
        x2 = win_w - 8
        y2 = win_h - 8
        x1 = x2 - 80  # 按钮宽度约 80px
        y1 = y2 - 30  # 按钮高度约 30px

        # 验证比例估算结果
        estimated = [x1, y1, x2, y2]
        if self._is_plausible_send_button_bbox(estimated):
            self.ICON_CONFIGS["send_button"]["position"] = estimated
            self.logger.info("比例估算成功: %s", estimated)
            return estimated

        # 最后的兜底方案：返回之前 fallback 的结果（即使不完美也能用）
        self.logger.warning("所有方法都无法获得完美的发送按钮bbox，使用 fallback 结果")
        return fb if fb else estimated

    def get_send_button_center_exact(self) -> Tuple[int, int]:
        return get_bbox_center_exact(self.get_send_button_bbox())

    def init_chat_window(self, use_adaptive: bool = True) -> bool:
        """
        初始化聊天窗口
        TODO 核心，需要做好鲁棒性

        Args:
            use_adaptive: 是否使用自适应初始化（应对UI变化）
        """
        self.logger.info("开始初始化聊天窗口...")
        try:
            if self._is_wechat_foreground():
                time.sleep(self.scroll_delay)
                init_result = self._init_window_part_size()
                if init_result:
                    self.weixin_windows["微信"] = {
                        "window": pyautogui.getWindowsWithTitle("微信")[0],
                        "MSG_TOP_X": self.MSG_TOP_X,
                        "MSG_TOP_Y": self.MSG_TOP_Y,
                        "MSG_WIDTH": self.MSG_WIDTH,
                        "MSG_HEIGHT": self.MSG_HEIGHT,
                        "region": [
                            0,
                            0,
                            self.size_config.width,
                            self.size_config.height,
                        ],
                    }

                    # 如果启用了自适应初始化，尝试用多种方法定位元素
                    if use_adaptive:
                        self.adaptive_init_elements()

                    return True
                return False
            else:
                self.logger.info("微信窗口未激活，重新激活")
                return False
        except Exception as e:
            self.logger.error(f"初始化聊天窗口时出错: {str(e)}")
            return False

    def _init_window_part_size(self) -> bool:
        """
        直接扫描截图像素，分析功能区域
        需要增加 通讯录 和 朋友圈
        """
        self.logger.info(
            f"微信窗口预设尺寸：{self.size_config.width}, {self.size_config.height}"
        )
        pyautogui.moveTo(150, 150)
        pyautogui.scroll(10000)
        time.sleep(self.action_delay)
        pyautogui.click()
        time.sleep(self.scroll_delay)
        # 主窗口截图，初始化布局完全按照这个截图进行
        screenshot = self.image_processor.take_screenshot(
            region=[
                0,
                0,
                self.size_config.width,
                self.size_config.height,
            ],
        )

        # 读取图片
        # 获取像素数据
        pixels = screenshot.load()
        SIDE_BAR_WIDTH = 0
        SESSION_LIST_WIDTH = 0
        MSG_WIDTH = 0
        breakPoint = []
        # 第一个变化点是 侧边栏和会话列表，第二个变化点是会话列表右侧和聊天详情，每次变化产生两个点
        j = 10
        for i in range(10, self.size_config.width * 2 // 3):
            if i == 10:
                pass
            else:
                if pixels[i, j] != pixels[i - 1, j]:
                    breakPoint.append(i)
                    if len(breakPoint) == 4:
                        break
        SIDE_BAR_WIDTH = breakPoint[1]
        SESSION_LIST_WIDTH = breakPoint[3] - SIDE_BAR_WIDTH
        # 从 SIDE_BAR_WIDTH + SESSION_LIST_WIDTH + 1 开始，向下匹配，第一个变色就是标题栏的高度，第二个就是消息栏的区域
        self.MSG_TOP_X = breakPoint[3]
        breakPoint.clear()
        j = SIDE_BAR_WIDTH + SESSION_LIST_WIDTH + 3
        for i in range(10, 500):
            if pixels[j, i] != pixels[j, i - 1]:
                breakPoint.append(i)
                if len(breakPoint) == 4:
                    break
        TITLE_BAR_HEIGHT = breakPoint[0]
        self.MSG_TOP_Y = TITLE_BAR_HEIGHT

        breakPoint.clear()
        j = self.MSG_TOP_X + 2
        TITLE_BAR_HEIGHT = 0
        MSG_HEIGHT = 0
        for i in range(10, self.size_config.height - 10):
            if i == 10:
                pass
            else:
                if pixels[j, i] != pixels[j, i - 1]:
                    breakPoint.append(i)
                    if len(breakPoint) == 4:
                        break
        # 如果一路找下来，一片白板，明显就是右侧没有加载东西，是刚刚启动，还有一种情况，就是在公众号那些页面也有可能，其实这里是好弄的，主要是不在聊天页面，发送按钮不好找
        # TODO 用 yolo找头像，然后确定点击的位置更加好
        if len(breakPoint) < 3:
            # 主动去点击第一个存在的用户，让他切换一下
            # pyautogui.moveTo()
            # pyautogui.click()
            return False
        TITLE_BAR_HEIGHT = breakPoint[1]
        self.MSG_TOP_Y = TITLE_BAR_HEIGHT
        MSG_HEIGHT = breakPoint[3] - TITLE_BAR_HEIGHT - 2
        MSG_WIDTH = self.size_config.width - SIDE_BAR_WIDTH - SESSION_LIST_WIDTH - 2
        # 联系人区域的右上角，就是MSG_TOP的坐标，同时也是MSG的左上角，发送内容工具栏的右上角就是MSG区域的右下角
        self.MSG_WIDTH = MSG_WIDTH
        self.MSG_HEIGHT = MSG_HEIGHT
        self.logger.info(f"MSG_WIDTH: {self.MSG_WIDTH}, MSG_HEIGHT: {self.MSG_HEIGHT}")

        # 计算搜索框的坐标，直接取会话列表的中间位置，从上到下扫描高度范围内就行啦~
        # TODO 优化，找到上下边框，再从中点向左右两侧扫描，可以拿到更完整的区域，目前先这样
        search_box_point = [SIDE_BAR_WIDTH + SESSION_LIST_WIDTH // 2, 0]
        breakPoint.clear()

        # 扩大扫描范围，从标题栏顶部到底部区域
        scan_start = 10
        scan_end = TITLE_BAR_HEIGHT + 50  # 扩大到标题栏下方区域
        for i in range(scan_start, scan_end):
            if pixels[search_box_point[0], i] != pixels[search_box_point[0], i - 1]:
                breakPoint.append(i)
                if len(breakPoint) == 3:
                    break

        # 处理不同的情况
        if len(breakPoint) >= 2:
            if len(breakPoint) == 2:
                search_box_point[1] = (breakPoint[0] + breakPoint[1]) // 2
            elif len(breakPoint) == 3:
                search_box_point[1] = (breakPoint[1] + breakPoint[2]) // 2
            elif len(breakPoint) > 3:
                # 取中间位置的点
                search_box_point[1] = (breakPoint[len(breakPoint) // 2 - 1] + breakPoint[len(breakPoint) // 2]) // 2
        else:
            # 如果没找到，尝试使用相对位置计算
            self.logger.warning(f"搜索框像素扫描未找到，尝试OCR方法")
            search_pos = self.find_search_box_by_ocr()
            if search_pos:
                search_box_point = get_center_point(search_pos)
            else:
                # 最后使用相对比例计算
                x = int(self.size_config.width * 0.7)
                y = int(self.size_config.height * 0.035)
                search_box_point = [x, y]
                self.logger.warning(f"使用相对比例计算搜索框位置: {search_box_point}")

        self.logger.info(f"search_btn_bbox: {search_box_point}")

        # 计算发送按钮的坐标, 从右下角开始找，而不是左上角，只要斜向找到变色的元素就可以了，注意那个圆角, 第一个元素就是那个发送的右下角，然后查找一下发送按钮的高度和宽度就可以了
        # 这里实际上需要保留一下右下角的距离，这样的话，就不用管窗口的大小，直接用距离算就行了
        send_btn_bbox = [0, 0, 0, 0]
        # 扫描范围根据窗口大小动态调整，确保能覆盖右下角区域
        scan_range = min(300, self.size_config.width // 4)
        for i in range(20, scan_range):
            if (
                pixels[self.size_config.width - 1 - i, self.size_config.height - 1 - i]
                != pixels[
                    self.size_config.width - 1 - i, self.size_config.height - 1 - i - 1
                ]
            ):
                send_btn_bbox[2] = self.size_config.width - 1 - i
                send_btn_bbox[3] = self.size_config.height - 1 - i
                break

        button_right_x = send_btn_bbox[2] - 3
        button_right_y = send_btn_bbox[3] - 3
        # 从 button_right_x 向左侧扫描，根据窗口宽度动态调整扫描范围
        scan_width = min(300, self.size_config.width // 3)
        for i in range(0, scan_width):
            if (
                pixels[button_right_x - i, button_right_y]
                != pixels[button_right_x - i - 1, button_right_y]
            ):
                send_btn_bbox[0] = button_right_x - i
                break
            if (
                pixels[button_right_x, button_right_y - i]
                != pixels[button_right_x, button_right_y - i - 1]
            ):
                send_btn_bbox[1] = button_right_y - i

        self.logger.info(f"send_btn_bbox: {send_btn_bbox}")
        if not self._is_plausible_send_button_bbox(send_btn_bbox):
            self.logger.warning(
                "发送按钮像素扫描结果不可信（常见为 y1 未扫到仍为 0），改用比例估算"
            )
            send_btn_bbox = self._fallback_send_button_bbox()

        breakPoint.clear()
        icons = []
        for i in range(TITLE_BAR_HEIGHT, self.size_config.height // 2):
            if pixels[SIDE_BAR_WIDTH // 2, i] != pixels[SIDE_BAR_WIDTH // 2, i - 1]:
                breakPoint.append(i)
                if len(icons) == 0:
                    icons.append(i)
                if len(breakPoint) > 1:
                    if breakPoint[-1] - breakPoint[-2] > 30:
                        # self.logger.info(f"间隔 {breakPoint[-1] - breakPoint[-2]}")
                        icons.append(breakPoint[-2])
                        icons.append(breakPoint[-1])
        icons.append(breakPoint[-1])
        # self.logger.info(icons)
        # 两两一组，目前先关心前面两个是聊天和联系人
        all_result = []

        # 这里可能会出现多个菜单，数量不确定，所以要复杂处理
        menu_labels = [
            MenuTypeEnum.Chat.value,
            MenuTypeEnum.Contact.value,
            MenuTypeEnum.Favorite.value,
            MenuTypeEnum.Friend.value,
        ]

        for idx, i in enumerate(range(0, len(icons), 2)):
            bbox = [
                0,
                icons[i],
                SIDE_BAR_WIDTH,
                icons[i + 1],
            ]
            # 保存到 ICON_CONFIGS
            name = menu_labels[idx] if idx < len(menu_labels) else f"菜单{idx}"
            self.ICON_CONFIGS[name] = {
                "name": name,
                "color": None,
                "position": bbox,
            }
            all_result.append(
                {
                    "pixel_bbox": bbox,
                    "content": name,
                    "label": name,
                    "source": "动态计算",
                }
            )
        all_result.append(
            {
                "pixel_bbox": [
                    SIDE_BAR_WIDTH,
                    TITLE_BAR_HEIGHT,
                    SIDE_BAR_WIDTH + SESSION_LIST_WIDTH,
                    self.size_config.height,
                ],
                "content": "会话列表区域",
                "label": "会话列表区域",
                "source": "动态计算",
            }
        )
        all_result.append(
            {
                "pixel_bbox": [
                    self.MSG_TOP_X,
                    self.MSG_TOP_Y,
                    self.MSG_TOP_X + self.MSG_WIDTH,
                    self.MSG_TOP_Y + self.MSG_HEIGHT,
                ],
                "content": "消息区域",
                "label": "消息区域",
                "source": "动态计算",
            }
        )
        all_result.append(
            {
                "pixel_bbox": send_btn_bbox,
                "content": "发送按钮",
                "label": "发送按钮",
                "source": "动态计算",
            }
        )
        all_result.append(
            {
                "pixel_bbox": [
                    search_box_point[0] - 10,
                    search_box_point[1] - 10,
                    search_box_point[0] + 10,
                    search_box_point[1] + 10,
                ],
                "content": "搜索框",
                "label": "搜索框",
                "source": "动态计算",
            }
        )

        self.ICON_CONFIGS["search_icon"]["position"] = [
            search_box_point[0] - 10,
            search_box_point[1] - 10,
            search_box_point[0] + 10,
            search_box_point[1] + 10,
        ]
        self.ICON_CONFIGS["send_button"]["position"] = send_btn_bbox

        # 校准相对比例（基于实际找到的位置）
        self._calibrate_position_ratios()

        screenshot = self.image_processor.take_screenshot(
            region=[
                0,
                0,
                self.size_config.width,
                self.size_config.height,
            ],
        )
        self.SIDE_BAR_WIDTH = SIDE_BAR_WIDTH
        self.SESSION_LIST_WIDTH = SESSION_LIST_WIDTH
        self.TITLE_BAR_HEIGHT = TITLE_BAR_HEIGHT

        self.open_close_sidebar()
        # 先给他打开，然后从底部开始扫像素
        screenshot = self.image_processor.take_screenshot(
            region=[
                0,
                0,
                self.size_config.width,
                self.size_config.height,
            ],
        )
        # 读取图片
        # 获取像素数据
        pixels = screenshot.load()
        # Y从底部发送按钮相同位置开始，X从去掉侧边栏位置开始, 偏移50，防止遇到分割线
        startx = SIDE_BAR_WIDTH + SESSION_LIST_WIDTH + 50
        starty = get_center_point(send_btn_bbox)[1]
        for i in range(startx, self.size_config.width):
            if pixels[i, starty] != pixels[i - 1, starty]:
                self.ROOM_SIDE_BAR_WIDTH = self.size_config.width - i
                self.logger.info(f"侧边栏宽度: {self.ROOM_SIDE_BAR_WIDTH}")
                break
        self.open_close_sidebar(close=True)
        return True

    def find_element_by_template(
        self,
        template_name: str,
        region: Optional[List[int]] = None,
        template_path: Optional[str] = None,
    ) -> Optional[Tuple[int, int, int, int]]:
        """
        使用模板匹配查找元素位置

        Args:
            template_name: 模板名称，用于缓存
            region: 搜索区域 [x, y, width, height]
            template_path: 模板图片路径

        Returns:
            匹配到的位置 (x1, y1, x2, y2) 或 None
        """
        if region is None:
            region = [0, 0, self.size_config.width, self.size_config.height]

        # 截取搜索区域
        screenshot = self.image_processor.take_screenshot(region=region)
        screenshot_gray = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2GRAY)

        # 获取或加载模板
        if template_name in self._cached_templates:
            template = self._cached_templates[template_name]
        elif template_path:
            template = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
            if template is not None:
                self._cached_templates[template_name] = template
        else:
            return None

        if template is None:
            return None

        # 模板匹配
        try:
            result = cv2.matchTemplate(screenshot_gray, template, cv2.TM_CCOEFF_NORMED)
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

            if max_val >= self._template_threshold:
                h, w = template.shape
                x1 = region[0] + max_loc[0]
                y1 = region[1] + max_loc[1]
                x2 = x1 + w
                y2 = y1 + h
                self.logger.info(f"模板 '{template_name}' 匹配成功，位置: ({x1}, {y1}, {x2}, {y2}), 置信度: {max_val:.2f}")
                return (x1, y1, x2, y2)
            else:
                self.logger.warning(f"模板 '{template_name}' 匹配失败，最佳置信度: {max_val:.2f}")
                return None
        except Exception as e:
            self.logger.error(f"模板匹配出错: {str(e)}")
            return None

    def find_send_button_by_color(self, max_attempts: int = 3) -> Optional[List[int]]:
        """
        使用颜色特征查找发送按钮（适应UI变化）

        Args:
            max_attempts: 最大尝试次数

        Returns:
            发送按钮边界框 [x1, y1, x2, y2] 或 None
        """
        for attempt in range(max_attempts):
            try:
                screenshot = self.image_processor.take_screenshot(
                    region=[0, 0, self.size_config.width, self.size_config.height]
                )
                pixels = screenshot.load()
                width, height = screenshot.size

                # 从右下角开始向左上方向扫描，寻找颜色变化点
                # 微信发送按钮通常在右下角附近
                button_region = None

                # 扫描范围根据窗口大小动态调整
                scan_offset_x = min(300, width // 4)
                scan_offset_y = min(150, height // 5)

                # 扫描右下角区域
                for start_x in range(width - 20, width - 20 - scan_offset_x, -1):
                    for start_y in range(height - 20, height - 20 - scan_offset_y, -1):
                        center_color = pixels[start_x, start_y]
                        # 发送按钮通常是绿色或蓝色，有一定饱和度
                        if self._is_send_button_color(center_color):
                            # 确认按钮区域
                            button_region = self._scan_button_region(
                                screenshot, start_x, start_y, center_color
                            )
                            if button_region:
                                self.logger.info(f"发送按钮区域: {button_region}")
                                return button_region

                self.logger.warning(f"第 {attempt + 1} 次尝试未找到发送按钮")
                time.sleep(0.5)

            except Exception as e:
                self.logger.error(f"查找发送按钮时出错: {str(e)}")

        return None

    def _is_send_button_color(self, color: Tuple[int, int, int]) -> bool:
        """
        判断颜色是否符合发送按钮特征

        微信发送按钮通常是：
        - 绿色: RGB(87, 174, 86) 或类似
        - 或者蓝色（新版本）: RGB(66, 128, 246) 或类似
        """
        r, g, b = color
        # 绿色按钮
        if g > 100 and g > r * 1.2 and g > b * 1.2:
            return True
        # 蓝色按钮（新版微信）
        if b > 150 and b > r and b > g * 1.2:
            return True
        # 可能的浅绿色变体
        if g > 150 and r > 50 and r < 150 and b < 150:
            return True
        return False

    def _scan_button_region(
        self,
        screenshot,
        start_x: int,
        start_y: int,
        center_color: Tuple[int, int, int],
    ) -> Optional[List[int]]:
        """
        扫描并确定按钮区域
        """
        pixels = screenshot.load()
        width, height = screenshot.size

        x1, y1, x2, y2 = start_x, start_y, start_x, start_y

        # 向左扫描
        for x in range(start_x, max(0, start_x - 200), -1):
            if self._colors_similar(pixels[x, start_y], center_color, threshold=60):
                x1 = x
            else:
                break

        # 向右扫描
        for x in range(start_x, min(width, start_x + 200)):
            if self._colors_similar(pixels[x, start_y], center_color, threshold=60):
                x2 = x
            else:
                break

        # 向上扫描
        for y in range(start_y, max(0, start_y - 100), -1):
            if self._colors_similar(pixels[start_x, y], center_color, threshold=60):
                y1 = y
            else:
                break

        # 向下扫描
        for y in range(start_y, min(height, start_y + 100)):
            if self._colors_similar(pixels[start_x, y], center_color, threshold=60):
                y2 = y
            else:
                break

        # 验证按钮大小是否合理（发送按钮通常在 60-120 像素宽）
        if 40 < (x2 - x1) < 200 and 20 < (y2 - y1) < 80:
            return [x1, y1, x2, y2]
        return None

    def _colors_similar(
        self, color1: Tuple[int, int, int], color2: Tuple[int, int, int], threshold: int = 30
    ) -> bool:
        """判断两个颜色是否相似"""
        return all(abs(c1 - c2) <= threshold for c1, c2 in zip(color1, color2))

    def find_search_box_by_ocr(self) -> Optional[List[int]]:
        """
        使用OCR识别搜索框位置

        Returns:
            搜索框边界框 [x1, y1, x2, y2] 或 None
        """
        try:
            # 使用实际测量的侧边栏宽度，如果没有则使用比例计算
            side_bar_width = self.SIDE_BAR_WIDTH if self.SIDE_BAR_WIDTH > 0 else int(self.size_config.width * 0.07)
            session_list_width = self.SESSION_LIST_WIDTH if self.SESSION_LIST_WIDTH > 0 else int(self.size_config.width * 0.2)
            title_bar_height = self.TITLE_BAR_HEIGHT if self.TITLE_BAR_HEIGHT > 0 else int(self.size_config.height * 0.05)

            # 扫描会话列表上方的搜索区域
            search_region = [
                side_bar_width,
                10,
                side_bar_width + session_list_width,
                title_bar_height + 50,  # 扩展高度以覆盖搜索框
            ]
            screenshot = self.image_processor.take_screenshot(region=search_region)
            result = self.ocr_processor.process_image(image=screenshot)

            # 查找包含"搜索"文字的区域
            for item in result:
                label = item.get("label", "")
                if "搜索" in label or "search" in label.lower():
                    bbox = item.get("pixel_bbox", [])
                    if len(bbox) == 4:
                        # 转换为全局坐标
                        return [
                            bbox[0] + search_region[0],
                            bbox[1] + search_region[1],
                            bbox[2] + search_region[0],
                            bbox[3] + search_region[1],
                        ]

            self.logger.warning("OCR未找到搜索框")
            return None

        except Exception as e:
            self.logger.error(f"OCR查找搜索框时出错: {str(e)}")
            return None

    def get_position_by_ratio(
        self,
        element: str,
        reference: Optional[str] = None,
        reference_pos: Optional[List[int]] = None,
    ) -> Tuple[int, int]:
        """
        根据相对比例计算元素位置（适应窗口大小变化）

        Args:
            element: 元素名称 (search_box, send_button, input_box)
            reference: 参考元素名称
            reference_pos: 参考元素位置

        Returns:
            (x, y) 中心点坐标
        """
        if element == "search_box":
            x = int(self.size_config.width * self._position_ratios["search_box"]["x_ratio"])
            y = int(self.size_config.height * self._position_ratios["search_box"]["y_ratio"])
        elif element == "send_button":
            if reference_pos:
                x = reference_pos[0] + self._position_ratios["send_button"]["x_offset"]
                y = reference_pos[1] + self._position_ratios["send_button"]["y_offset"]
            else:
                # 发送按钮在消息区域右下角
                msg_right = self.MSG_TOP_X + self.MSG_WIDTH
                msg_bottom = self.MSG_TOP_Y + self.MSG_HEIGHT
                x = msg_right - 80
                y = msg_bottom - 40
        elif element == "input_box":
            if reference_pos:
                x = reference_pos[0] + self._position_ratios["input_box"]["x_offset"]
                y = reference_pos[1] + self._position_ratios["input_box"]["y_offset"]
            else:
                # 输入框在消息区域右下角
                msg_right = self.MSG_TOP_X + self.MSG_WIDTH
                msg_bottom = self.MSG_TOP_Y + self.MSG_HEIGHT
                x = msg_right - 30
                y = msg_bottom - 40
        else:
            x, y = 0, 0

        return (x, y)

    def _calibrate_position_ratios(self) -> None:
        """
        基于实际找到的元素位置，自动校准相对比例
        这样下次窗口大小变化时，可以使用更准确的估算位置
        """
        try:
            # 校准搜索框位置
            search_pos = self.ICON_CONFIGS.get("search_icon", {}).get("position")
            if search_pos and len(search_pos) == 4:
                center_x = (search_pos[0] + search_pos[2]) // 2
                center_y = (search_pos[1] + search_pos[3]) // 2
                x_ratio = center_x / self.size_config.width
                y_ratio = center_y / self.size_config.height
                self._position_ratios["search_box"]["x_ratio"] = round(x_ratio, 4)
                self._position_ratios["search_box"]["y_ratio"] = round(y_ratio, 4)
                self.logger.info(f"校准搜索框比例: x_ratio={x_ratio:.4f}, y_ratio={y_ratio:.4f}")

            # 校准发送按钮位置（记录相对右下角的偏移）
            send_pos = self.ICON_CONFIGS.get("send_button", {}).get("position")
            if send_pos and len(send_pos) == 4 and self._is_plausible_send_button_bbox(
                send_pos
            ):
                # 计算相对于右下角的偏移
                x_offset = self.size_config.width - send_pos[0]
                y_offset = self.size_config.height - send_pos[1]
                self._position_ratios["send_button"]["x_offset"] = -x_offset
                self._position_ratios["send_button"]["y_offset"] = -y_offset
                self.logger.info(f"校准发送按钮偏移: x_offset={-x_offset}, y_offset={-y_offset}")

            self.logger.info(f"校准后的相对比例: {self._position_ratios}")

        except Exception as e:
            self.logger.error(f"校准位置比例时出错: {str(e)}")

    def adaptive_init_elements(self) -> bool:
        """
        自适应初始化关键元素（搜索框、发送按钮）
        尝试多种方法找到元素位置，层层降级
        """
        self.logger.info("开始自适应初始化关键元素...")

        # 方法1: 尝试使用模板匹配（如果提供了模板）
        template_path = self.rpa_config.get("search_template_path")
        if template_path:
            pos = self.find_element_by_template("search_icon", template_path=template_path)
            if pos:
                self.ICON_CONFIGS["search_icon"]["position"] = pos
                self.logger.info("通过模板匹配找到搜索框")

        template_path = self.rpa_config.get("send_template_path")
        if template_path:
            pos = self.find_element_by_template("send_button", template_path=template_path)
            if pos:
                self.ICON_CONFIGS["send_button"]["position"] = pos
                self.logger.info("通过模板匹配找到发送按钮")

        # 方法2: 尝试使用颜色特征查找发送按钮
        if not self.ICON_CONFIGS["send_button"]["position"]:
            send_pos = self.find_send_button_by_color()
            if send_pos:
                self.ICON_CONFIGS["send_button"]["position"] = send_pos
                self.logger.info("通过颜色特征找到发送按钮")

        # 方法3: 使用OCR识别搜索框
        if not self.ICON_CONFIGS["search_icon"]["position"]:
            search_pos = self.find_search_box_by_ocr()
            if search_pos:
                self.ICON_CONFIGS["search_icon"]["position"] = search_pos
                self.logger.info("通过OCR找到搜索框")

        # 方法4: 使用相对比例计算
        search_ratio_pos = self.get_position_by_ratio("search_box")
        if not self.ICON_CONFIGS["search_icon"]["position"]:
            self.ICON_CONFIGS["search_icon"]["position"] = [
                search_ratio_pos[0] - 10,
                search_ratio_pos[1] - 10,
                search_ratio_pos[0] + 10,
                search_ratio_pos[1] + 10,
            ]
            self.logger.info("使用相对比例计算搜索框位置")

        send_ratio_pos = self.get_position_by_ratio("send_button")
        if not self.ICON_CONFIGS["send_button"]["position"]:
            self.ICON_CONFIGS["send_button"]["position"] = [
                send_ratio_pos[0] - 60,
                send_ratio_pos[1] - 20,
                send_ratio_pos[0] + 10,
                send_ratio_pos[1] + 10,
            ]
            self.logger.info("使用相对比例计算发送按钮位置")

        return bool(
            self.ICON_CONFIGS["search_icon"]["position"]
            and self.ICON_CONFIGS["send_button"]["position"]
        )

    def init_split_sessions(self):
        """初始化分割的会话"""
        windows = pyautogui.getAllWindows()
        for window in windows:
            if "元宝" in window.title:
                self.logger.info("元宝窗口独立设置")
                self.weixin_windows[window.title] = {
                    "window": window,
                    "MSG_TOP_X": self.size_config.width,
                    "MSG_TOP_Y": self.MSG_TOP_Y,
                    "MSG_WIDTH": self.size_config.width,
                    "MSG_HEIGHT": self.MSG_HEIGHT,
                    "region": [
                        self.size_config.width,
                        self.MSG_TOP_Y,
                        self.size_config.width,
                        self.MSG_HEIGHT,
                    ],
                }
                window.size = (self.size_config.width, self.size_config.height)
                window.topleft = (self.size_config.width, 0)

    def init_pyq_window(self) -> bool:
        """初始化朋友圈窗口"""
        friend_window = self.open_friend_window()
        if friend_window:
            # 这里宽度是固定的无所谓，高度设置为和主窗口一样，方便处理
            friend_window.size = (10, self.size_config.height)
            friend_window.left = self.size_config.width
            friend_window.top = 0
            time.sleep(self.scroll_delay)
            human_like_mouse_move(
                friend_window.left + friend_window.width // 2,
                friend_window.top + friend_window.height // 2,
            )
            time.sleep(self.scroll_delay)
            pyautogui.scroll(-friend_window.height // 2)
            time.sleep(self.scroll_delay)
            # 这里就需要查找顶部的控件了，1. 移动到窗口然后向下滚动，把顶部的banner滚掉 2 查找title高度，取中点 3. 从左侧开始向右遍历 50%宽度 4. 找到三个控件
            screenshot = self.image_processor.take_screenshot(
                region=[
                    friend_window.left,
                    friend_window.top,
                    friend_window.width,
                    friend_window.height,
                ],
            )
            # 读取图片
            # 获取像素数据
            pixels = screenshot.load()
            # 从上到下扫描高度范围内，找到第一个变化的像素，就是标题栏的高度
            title_bar_height = 0
            for i in range(10, 100):
                if pixels[10, i] != pixels[10, i - 1]:
                    title_bar_height = i
                    break
            if title_bar_height > 0:
                self.logger.info(f"朋友圈窗口标题栏高度: {title_bar_height}")
            else:
                self.logger.error("朋友圈窗口标题栏高度未找到，请检查微信是否正常运行")
                return None
            # 参考主菜单查找的方式，这里还是采用间隔法吧？这里其实写死都可以？就怕分辨率导致不同？
            breakPoint = []
            breakPoint.clear()
            icons = []
            for i in range(10, friend_window.width // 3):
                if (
                    pixels[i, title_bar_height // 2]
                    != pixels[i - 1, title_bar_height // 2]
                ):
                    breakPoint.append(i)
                    if len(icons) == 0:
                        icons.append(i)
                    if len(breakPoint) > 1:
                        if breakPoint[-1] - breakPoint[-2] > 30:
                            # self.logger.info(f"间隔 {breakPoint[-1] - breakPoint[-2]}")
                            icons.append(breakPoint[-2])
                            icons.append(breakPoint[-1])
            icons.append(breakPoint[-1])
            # self.logger.info(icons)
            # 两两一组，目前先关心前面两个是聊天和联系人
            all_result = []

            # 这里可能会出现多个菜单，数量不确定，所以要复杂处理
            menu_labels = [
                MenuTypeEnum.FriendNotification.value,
                MenuTypeEnum.FriendSend.value,
                MenuTypeEnum.FrendRefresh.value,
            ]

            for idx, i in enumerate(range(0, len(icons), 2)):
                bbox = [
                    icons[i] + friend_window.left,
                    title_bar_height // 3,
                    icons[i + 1] + friend_window.left,
                    title_bar_height // 3 * 2,
                ]
                # 保存到 ICON_CONFIGS, 这里保存的位置其实已经计算好了，所以下面要重新偏移
                name = menu_labels[idx] if idx < len(menu_labels) else f"菜单{idx}"
                self.ICON_CONFIGS[name] = {
                    "name": name,
                    "color": None,
                    "position": bbox,
                }
                all_result.append(
                    {
                        "pixel_bbox": bbox,
                        "content": name,
                        "label": name,
                        "source": "动态计算",
                    }
                )
            self.image_processor.draw_boxes_on_screen(
                screenshot,
                all_result,
                start=(-friend_window.left, -friend_window.top),
                output_path="runtime_images/friend_window.png",
            )
            return True
        else:
            self.logger.error("朋友圈窗口未找到，请检查微信是否正常运行")
            return None

    def _is_wechat_foreground(self, reposition=True) -> bool:
        """检查微信主窗口是否在前台"""
        # TODO 重构
        windows = pyautogui.getAllWindows()
        for window in windows:
            if window.title == "预览":
                window.close()
        chat_window = pyautogui.getWindowsWithTitle("微信")[0]
        if chat_window:
            self._activate_window("微信")
            if reposition:
                chat_window.topleft = (0, 0)
            # 这里出现的问题，可能就是宽度有最小值，有可能会比最小值大
            chat_window.size = (self.size_config.width, self.size_config.height)
            if (
                chat_window.size.width < self.size_config.width
                or chat_window.size.height < self.size_config.height
            ):
                self.logger.warn("微信窗口大小不匹配，重新调整大小")
                return False
            else:
                self.logger.info("微信窗口大小匹配")
                self.size_config.width = chat_window.size.width
                self.size_config.height = chat_window.size.height
            return True
        else:
            self.logger.error("微信窗口未找到，请检查微信是否正常运行")
            return False

    def _activate_window(self, title: str = "微信"):
        """激活微信窗口"""
        try:
            window = pyautogui.getWindowsWithTitle(title)[0]
            window.activate()
            return True
        except Exception as e:
            if window:
                window.restore()
                return True
            self.logger.error(f"激活窗口时出错: {str(e)}")
            return False

    def get_window_region(self) -> Optional[Tuple[int, int, int, int]]:
        """获取指定窗口的区域"""
        if self.current_window:
            return self.current_window["region"]
        return None

    def get_message_region(self) -> Optional[Tuple[int, int, int, int]]:
        """获取消息区域"""
        if self.current_window:
            return [
                self.current_window.get("MSG_TOP_X"),
                self.current_window.get("MSG_TOP_Y"),
                self.current_window.get("MSG_WIDTH"),
                self.current_window.get("MSG_HEIGHT"),
            ]
        return None

    _SEARCH_CATEGORY_KEYS = ("联系人", "群聊", "功能")

    @staticmethod
    def _normalize_ocr_category_text(lab: str) -> str:
        """去掉首尾空白与常见空格，避免「功 能」类 OCR 拆字；不做子串匹配以免「…已读功能」误判为分类。"""
        return (lab or "").strip().replace(" ", "").replace("\u3000", "")

    def _collect_ocr_category_labels(self, result: list) -> list:
        """从 OCR 结果中筛出「联系人」「群聊」「功能」分类标签（须整段等于其一，不能仅为包含关系）。"""
        picked = []
        for r in result:
            lab = (r.get("label") or "").strip()
            if not lab:
                continue
            norm = self._normalize_ocr_category_text(lab)
            if lab in self._SEARCH_CATEGORY_KEYS or norm in self._SEARCH_CATEGORY_KEYS:
                picked.append(r)
        return picked

    def _pick_search_result_via_ocr(self, target: str) -> bool:
        """
        搜索框已输入关键词后：截图搜索浮层，OCR 找「联系人/群聊/功能」，
        取最靠上的一条分类标签，在其下方点击首条结果行（避免回车点到「搜索网络」等）。
        """
        row_offset = int(self.rpa_config.get("search_category_to_row_offset", 40))
        time.sleep(max(self.action_delay, 0.4))
        self.logger.info("在搜索结果中为「%s」选择分类下首条结果", target)

        # 截图区域：优先使用独立搜索窗口；否则在主窗口左上区域（侧边栏+会话列表+搜索框）
        search_window = self.wait_for_window(
            WindowTypeEnum.SearchContactWindow, timeout=4
        )
        if search_window:
            region = [
                search_window.left,
                search_window.top,
                search_window.width,
                search_window.height,
            ]
            self.logger.info(
                "使用独立搜索窗口截图 OCR: left=%s top=%s w=%s h=%s",
                region[0], region[1], region[2], region[3],
            )
        else:
            # 主窗口左上区域，覆盖侧边栏+会话列表+搜索框浮层
            # 使用实际测量的 SIDE_BAR_WIDTH + SESSION_LIST_WIDTH，而不是固定比例
            search_region_width = self.SIDE_BAR_WIDTH + self.SESSION_LIST_WIDTH
            search_region_height = self.TITLE_BAR_HEIGHT * 5 if self.TITLE_BAR_HEIGHT > 0 else int(self.size_config.height * 0.2)
            # 如果实际测量值无效，使用比例作为后备
            if search_region_width <= 0:
                search_region_width = int(self.size_config.width * 0.42)
            if search_region_height <= 0:
                search_region_height = int(self.size_config.height * 0.55)
            region = [0, 0, search_region_width, search_region_height]
            self.logger.info(
                "使用实际测量区域截图 OCR: SIDE_BAR=%s SESSION_LIST=%s w=%s h=%s",
                self.SIDE_BAR_WIDTH, self.SESSION_LIST_WIDTH,
                search_region_width, search_region_height,
            )

        screenshot = self.image_processor.take_screenshot(region=region)
        if not screenshot:
            self.logger.error("搜索区域截图失败")
            return False

        result = self.ocr_processor.process_image(image=screenshot)
        self.logger.info("OCR 返回 %d 个识别结果", len(result))
        for r in result:
            self.logger.info(
                "  OCR label='%s' bbox=%s",
                r.get("label", ""),
                r.get("pixel_bbox", []),
            )
        try:
            self.image_processor.draw_boxes_on_screen(
                screenshot,
                result,
                output_path="runtime_images/search_contact_result.png",
            )
        except Exception:
            pass

        labels = self._collect_ocr_category_labels(result)
        self.logger.info("OCR 匹配到分类标签 %d 个: %s", len(labels), [l.get("label") for l in labels])
        if not labels:
            return False

        labels.sort(key=lambda x: x.get("pixel_bbox", [0, 9999])[1])
        category_label = labels[0]
        bbox = category_label.get("pixel_bbox")
        if not bbox or len(bbox) != 4:
            self.logger.error("分类标签 bbox 无效")
            return False

        ox, oy = region[0], region[1]
        category_bottom = bbox[3] + oy

        # 找分类标签下方最近的搜索结果（排除"搜索网络结果"和标签本身）
        excluded_keywords = ["搜索网络", "搜索", "六", "Q"]
        candidates = []
        for r in result:
            r_bbox = r.get("pixel_bbox", [])
            if len(r_bbox) != 4:
                continue
            r_label = r.get("label", "")
            # 跳过排除项和标签本身
            if any(kw in r_label for kw in excluded_keywords):
                continue
            if r_label == category_label.get("label"):
                continue
            # 跳过纯数字（如未读消息数量 "2"）或纯符号
            if r_label.strip().isdigit():
                continue
            # 只选择位于分类标签下方的条目
            r_top = r_bbox[1] + oy
            r_bottom = r_bbox[3] + oy
            if r_top >= category_bottom:
                # 计算该条目的大致中心点
                candidates.append({
                    "label": r_label,
                    "bbox": r_bbox,
                    "center_x": (r_bbox[0] + r_bbox[2]) / 2 + ox,
                    "center_y": (r_bbox[1] + r_bbox[3]) / 2 + oy,
                    "top": r_top,
                })

        if not candidates:
            self.logger.warning("未找到分类标签下方的搜索结果，使用默认偏移")
            cx = (bbox[0] + bbox[2]) / 2 + ox
            click_y = bbox[3] + row_offset + oy
            off_x, off_y = self.search_contact_offset
            final_x = int(cx + off_x)
            final_y = int(click_y + off_y)
        else:
            # 选择最靠上的候选结果
            candidates.sort(key=lambda x: x["top"])
            first_result = candidates[0]
            final_x = int(first_result["center_x"])
            final_y = int(first_result["center_y"])
            self.logger.info(
                "找到分类「%s」下方搜索结果: 「%s」, bbox=%s",
                category_label.get("label"), first_result["label"], first_result["bbox"],
            )
        self.logger.info(
            "OCR 选中分类「%s」(y=%s)，点击位置: (%d, %d)",
            category_label.get("label"), bbox[3], final_x, final_y,
        )
        pyautogui.click(final_x, final_y)
        time.sleep(self.switch_contact_delay)

        color = self.image_processor.get_pixel_color(
            self.SIDE_BAR_WIDTH + self.SESSION_LIST_WIDTH + 10,
            self.TITLE_BAR_HEIGHT - 5,
        )
        if color == (255, 255, 255):
            self.logger.warning("点击后搜索态仍在（标题区仍为白），切换可能失败")
            return False
        self.logger.info("搜索浮层已关闭，假定已进入会话")
        return True

    def switch_session(self, target: str) -> bool:
        """
        切换会话
        这里要区分切换会话和切换窗口，如果是分离的对话，那么直接切换，也可能是切换别的窗口
        """
        now = time.time()
        # 超过3分钟未切换会话，清除缓存
        if self.last_switch_session_time and now - self.last_switch_session_time > 180:
            self.last_switch_session = None
            self.last_switch_session_time = None
            self.logger.info("会话缓存已超时，清除缓存")

        self.logger.info(f"切换会话: {target}")
        if target in self.weixin_windows:
            self.switch_window(target)
            return True
        else:
            # 激活微信窗口
            self.switch_window("微信")

            # 如果当前已经在目标会话中，且缓存未超时，直接返回
            if self.last_switch_session == target:
                self.logger.info(f"已经切换到: {target}，缓存有效，直接返回True")
                return True

            # 缓存失效或切换到新会话，执行搜索切换流程
            self.logger.info(f"使用搜索切换到: {target}")
            time.sleep(self.action_delay)
            pyautogui.hotkey("ctrl", "f")
            time.sleep(self.action_delay)
            if not set_clipboard_text(target):
                return False
            time.sleep(self.action_delay)
            pyautogui.hotkey("ctrl", "v")
            self.logger.info(f"正在搜索联系人: {target}")

            if self._pick_search_result_via_ocr(target):
                # OCR 点击成功后会检测搜索浮层是否关闭，不需要额外按 ESC
                time.sleep(max(self.action_delay, 0.15))
                self.last_switch_session = target
                self.last_switch_session_time = time.time()
                return True

            self.logger.warning("OCR 点击选择失败，尝试回车作为兜底")
            time.sleep(self.action_delay)
            pyautogui.press("enter")
            time.sleep(self.switch_contact_delay)
            color = self.image_processor.get_pixel_color(
                self.SIDE_BAR_WIDTH + self.SESSION_LIST_WIDTH + 10,
                self.TITLE_BAR_HEIGHT - 5,
            )
            if color == (255, 255, 255):
                self.logger.error("回车兜底后仍处于搜索态，切换失败")
                return False
            time.sleep(max(self.action_delay, 0.15))
            time.sleep(0.5)  # 加长等待
            # 检查是否还在搜索态
            if color == (255, 255, 255):
                self.logger.warning("仍处于搜索态，再次尝试 ESC")
                pyautogui.press("escape")
                time.sleep(0.3)
            self.last_switch_session = target
            self.last_switch_session_time = time.time()
            return True

    def switch_window(self, target: str) -> bool:
        """
        激活窗口
        这里要区分激活窗口和激活对话，如果是分离的对话，那么直接激活，也可能是激活别的窗口
        """
        self.logger.info(f"激活窗口: {target}")
        if target in self.weixin_windows:
            self.current_window = self.weixin_windows[target]
        else:
            self.current_window = self.weixin_windows.get("微信")
            if not self.current_window:
                self.logger.error("微信主窗口未初始化")
                return False

        try:
            # 避免触发窗口最大化等默认行为
            window = self.current_window["window"]
            # 先记录当前状态
            current_rect = (window.left, window.top, window.width, window.height)
            # 使用 win32gui 直接激活，不触发最大化等行为
            import win32con
            import win32gui
            hwnd = window._hWnd
            # 恢复窗口（如果最小化）
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            # 设置到前台
            win32gui.SetForegroundWindow(hwnd)
            time.sleep(0.2)
            # 确保窗口位置正确，不使用 .activate() 因为它可能触发双击行为
            # 直接用 SetWindowPos 设置位置
            win32gui.SetWindowPos(
                hwnd,
                win32con.HWND_TOP,
                current_rect[0],
                current_rect[1],
                current_rect[2],
                current_rect[3],
                win32con.SWP_NOACTIVATE | win32con.SWP_NOSIZE | win32con.SWP_NOMOVE
            )
            return True
        except Exception as e:
            self.logger.warning(f"窗口激活异常: {str(e)}，尝试备用方法")
            try:
                self.current_window["window"].restore()
                time.sleep(0.3)
            except Exception:
                pass
            return True

    def long_press_menu(self, target: str, duration: int = 1, clear_session_cache: bool = False) -> bool:
        """
        长按菜单

        Args:
            target: 菜单名称
            duration: 长按时长（秒）
            clear_session_cache: 是否清除会话缓存。
                - True: 点击了会话列表中的其他联系人，需要清除缓存
                - False: 只是在当前聊天中操作（如长按消息），保持缓存避免重复搜索
        """
        menu = self.ICON_CONFIGS.get(target)
        if not menu:
            self.logger.error("菜单不存在")
            return False

        if clear_session_cache:
            self.last_switch_session = None
            self.last_switch_session_time = None
            self.logger.info("长按菜单操作会切换会话，清除会话缓存")
        else:
            self.logger.info("长按菜单操作保持在当前会话，保持会话缓存")

        center_point = get_center_point(menu.get("position"))
        human_like_mouse_move(target_x=center_point[0], target_y=center_point[1])
        pyautogui.mouseDown(button="left")
        time.sleep(duration)
        pyautogui.mouseUp(button="left")
        return True

    def switch_menu(self, target: str, clear_session_cache: bool = False) -> bool:
        """
        切换菜单

        Args:
            target: 菜单名称（聊天、联系人、收藏、朋友圈等）
            clear_session_cache: 是否清除会话缓存。
                - True: 点击了左侧菜单栏切换到其他标签页，需要清除缓存
                - False: 只是在当前聊天页面点击菜单（如查看联系人资料），保持缓存避免重复搜索
        """
        self.logger.info(f"切换菜单{target}")
        menu = self.ICON_CONFIGS.get(target)
        if not menu:
            self.logger.error("菜单不存在")
            return False

        if clear_session_cache:
            self.last_switch_session = None
            self.last_switch_session_time = None
            self.logger.info("切换菜单会切换会话，清除会话缓存")
        else:
            self.logger.info("切换菜单保持在当前会话，保持会话缓存")

        center_point = get_center_point(menu.get("position"))
        human_like_mouse_move(target_x=center_point[0], target_y=center_point[1])
        pyautogui.click()
        return True

    def get_window(
        self, windowType: WindowTypeEnum, all: bool = False
    ) -> Optional[pyautogui.Window]:
        """
        获取不同的窗口，不同的窗口有不同的判断条件
        args:
            all: 是否获取全部窗口，默认False，只获取微信的窗口
        """
        windows = pyautogui.getAllWindows()
        # 这里保留全部符合的窗口
        filter_windows = []
        if all:
            filter_windows = windows
        else:
            for window in windows:
                # 对所有的窗口进行过滤，排除掉不可见的，尺寸为0的
                if window.visible and window.width > 0 and window.height > 0:
                    # 这一步要过滤一下非微信的窗口
                    class_name = win32gui.GetClassName(window._hWnd)
                    if class_name.startswith("Qt5"):
                        filter_windows.append(window)
                    else:
                        pass
                        # self.logger.info(f"窗口类名: {class_name}{window.title}")
        if windowType == WindowTypeEnum.MainWindow:
            for window in filter_windows:
                if window.title == "微信":
                    return window
        elif windowType == WindowTypeEnum.AddFriendWindow:
            # 添加好友的窗口，判断规则：标题是 通过朋友验证，同时窗口的位置，应该在主窗口的内部
            for window in filter_windows:
                if window.title == "通过朋友验证":
                    # 这个位置关系不能确定，是浮动的，可以在屏幕的任意位置，但是肯定是可见的，而且明显不会很小
                    # 也有可能是一个很小的微信窗口，title： 微信，真的是吵了小龙的吗了
                    return window
            for window in filter_windows:
                if window.title == "微信":
                    # <Win32Window left="22", top="17", width="450", height="356", title="微信">
                    # 第一轮没有找到，第二轮直接用微信标签找，但是一定要判大小，否则返回主窗口就尴尬了
                    if window.width < 600 and window.height < 500:
                        return window
        elif windowType == WindowTypeEnum.InviteMemberWindow:
            for window in filter_windows:
                if window.title == "微信添加群成员":
                    # 这个位置关系不能确定，是浮动的，可以在屏幕的任意位置，但是肯定是可见的，而且明显不会很小
                    return window
        elif windowType == WindowTypeEnum.RemoveMemberWindow:
            for window in filter_windows:
                if window.title == "微信移出群成员":
                    # 这个位置关系不能确定，是浮动的，可以在屏幕的任意位置，但是肯定是可见的，而且明显不会很小
                    return window
        elif windowType == WindowTypeEnum.InviteConfirmWindow:
            for window in filter_windows:
                if window.title == "Weixin":
                    if (
                        window.left + window.width < self.size_config.width
                        and window.top + window.height < self.size_config.height
                    ):
                        return window
        elif windowType == WindowTypeEnum.InviteResonWindow:
            for window in filter_windows:
                if window.title == "Weixin":
                    if (
                        window.left + window.width < self.size_config.width
                        and window.top + window.height < self.size_config.height
                    ):
                        return window
        elif windowType == WindowTypeEnum.SearchHistoryWindow:
            for window in filter_windows:
                if window.title == "搜索聊天记录":
                    return window
        elif windowType == WindowTypeEnum.FriendWindow:
            for window in filter_windows:
                if window.title == "朋友圈":
                    return window
        elif windowType == WindowTypeEnum.PublicAnnouncementWindow:
            for window in filter_windows:
                if window.title.endswith("的群公告"):
                    return window
        elif windowType == WindowTypeEnum.RoomInputConfirmBox:
            for window in filter_windows:
                if window.title == "Weixin":
                    if (
                        window.left + window.width < self.size_config.width
                        and window.top + window.height < self.size_config.height
                    ):
                        return window
        elif windowType == WindowTypeEnum.MenuWindow:
            for window in filter_windows:
                if window.title == "Weixin":
                    if window.width < 300:
                        return window
        elif windowType == WindowTypeEnum.SearchContactWindow:
            for window in filter_windows:
                if window.title == "Weixin":
                    # 这里固定在左上角，所以要判断以下开始位置在左上角
                    if (
                        window.left < self.SIDE_BAR_WIDTH
                        and window.top < self.TITLE_BAR_HEIGHT
                    ):
                        return window
                    else:
                        pass
        return None

    def open_friend_window(self) -> Optional[pyautogui.Window]:
        """
        打开朋友圈窗口
        """
        self.switch_menu(MenuTypeEnum.Friend.value, clear_session_cache=True)
        time.sleep(self.scroll_delay)
        # 调用gerwindow方法检查是否存在，如果存在，需要把friend这个窗口移到边上去，防止覆盖
        friend_window = self.get_window(WindowTypeEnum.FriendWindow)
        if friend_window:
            return friend_window
        else:
            self.switch_menu(MenuTypeEnum.Friend.value, clear_session_cache=True)
            return None

    def open_friend_send_window(
        self, is_text: bool = False
    ) -> Optional[pyautogui.Window]:
        """
        打开朋友圈发送窗口
        """
        if is_text:
            self.long_press_menu(MenuTypeEnum.FriendSend.value, duration=2)
        else:
            self.switch_menu(MenuTypeEnum.FriendSend.value)
        time.sleep(self.scroll_delay)
        # 这里需要用到OCR了，使用OCR来判断指定的控件是否存在，如果存在就认为是打开了发送的窗口，如果不存在那么就是没打开
        # 稳定性堪忧
        friend_window = self.get_window(WindowTypeEnum.FriendWindow)
        if not friend_window:
            self.logger.error("朋友圈窗口未找到，请检查微信是否正常运行")
            return None
        if not is_text:
            return friend_window
        friend_window.activate()
        time.sleep(self.scroll_delay)
        screenshot = self.image_processor.take_screenshot(
            region=[
                friend_window.left,
                friend_window.top,
                friend_window.width,
                friend_window.height,
            ],
        )
        result = self.ocr_processor.process_image(image=screenshot)
        if result:
            # 这里只要确认打开就可以了，后面发送朋友圈才需要用到识别吧，毕竟
            find_count = 0
            for r in result:
                label = r.get("label")
                if label and label.startswith("这一刻的想法"):
                    find_count += 1
                elif label == "发表":
                    find_count += 1
                elif label == "取消":
                    find_count += 1
                elif label == "提醒谁看":
                    find_count += 1
                elif label == "谁可以看":
                    find_count += 1
                elif label == "公开":
                    find_count += 1
                elif label == "发表":
                    find_count += 1
            if find_count > 4:
                return friend_window
            else:
                self.logger.error("朋友圈发送窗口未找到，请检查微信是否正常运行")
                return None

    def close_all_windows(self):
        """
        关闭所有窗口
        """
        windows = pyautogui.getAllWindows()
        # 这里保留全部符合的窗口
        for window in windows:
            # 对所有的窗口进行过滤，排除掉不可见的，尺寸为0的
            if window.visible and window.width > 0 and window.height > 0:
                # 这一步要过滤一下非微信的窗口
                class_name = win32gui.GetClassName(window._hWnd)
                if class_name.startswith("Qt5"):
                    if window.title != "微信":
                        window.close()

    def open_close_sidebar(self, close: bool = False) -> bool:
        """
        打开或者关闭侧边栏，默认打开
        # 现在这里可以判断了，直接按照像素颜色是否是纯白色来匹配
        args:
            close: 关闭
        """
        color = self.image_processor.get_pixel_color(
            self.size_config.width - 20, self.size_config.height - 20
        )
        if color == (255, 255, 255):
            CLOSED = False
        else:
            CLOSED = True

        if close and CLOSED:
            return True
        elif not close and not CLOSED:
            return True
        else:
            x = self.SIDE_BAR_WIDTH + self.SESSION_LIST_WIDTH + 50
            y = self.ICON_CONFIGS.get("search_icon").get("position")[1]
            human_like_mouse_move(target_x=x, target_y=y)
            pyautogui.click()
            time.sleep(self.rpa_config.get("side_bar_delay", 3))
            return True

    def reinitialize_elements(self) -> bool:
        """
        重新初始化元素位置
        当检测到微信客户端更新后调用此方法重新定位关键元素
        """
        self.logger.info("重新初始化元素位置...")
        # 重新截取屏幕
        pyautogui.moveTo(150, 150)
        pyautogui.scroll(10000)
        time.sleep(self.action_delay)
        pyautogui.click()
        time.sleep(self.scroll_delay)

        # 清除缓存的模板
        self._cached_templates.clear()

        # 重新自适应初始化
        return self.adaptive_init_elements()

    def validate_element_positions(self) -> Dict[str, bool]:
        """
        验证元素位置是否仍然有效

        Returns:
            各元素的有效性字典
        """
        validation = {}
        for name, config in self.ICON_CONFIGS.items():
            pos = config.get("position")
            if pos and len(pos) == 4:
                # 验证该位置的颜色是否合理（白色区域或其他预期颜色）
                x, y = get_center_point(pos)
                color = self.image_processor.get_pixel_color(x, y)
                # 如果是完全透明(0,0,0)或者异常颜色，认为位置可能失效
                validation[name] = color != (0, 0, 0)
            else:
                validation[name] = False
        return validation

    def wait_for_window(
        self, window_type: WindowTypeEnum, all: bool = False, timeout: int = 5
    ) -> Optional[Any]:
        """
        轮询查找指定标题的窗口，直到出现或超时。

        Args:
            title (str): 窗口标题。
            timeout (int): 超时时间（秒）。

        Returns:
            Optional[Any]: 窗口对象或None。
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            window = self.get_window(window_type, all)
            if window:
                return window
            time.sleep(0.2)
        self.logger.warning(f"未在{timeout}秒内找到窗口: {window_type.value}")
        return None

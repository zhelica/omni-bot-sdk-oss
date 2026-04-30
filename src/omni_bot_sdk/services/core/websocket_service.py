"""
WebSocket 服务模块。
提供 WebSocket 连接认证和消息转发服务。
"""

import asyncio
import json
import logging
from queue import Queue
from typing import Any, Dict, Optional

try:
    import websockets
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False


class WebSocketService:
    """
    WebSocket 服务类。
    客户端连接后需先发送认证消息进行身份验证。
    """
    
    AUTH_SUCCESS_RESPONSE = {"type": "auth_success"}
    AUTH_FAILED_RESPONSE = {"type": "auth_failed", "reason": "认证失败"}
    
    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8002,
        secret_key: str = "",
        app_key: str = "",
        app_secret: str = "",
        guid: str = "",
        auth_callback: Optional[callable] = None,
    ):
        """
        初始化 WebSocket 服务。

        Args:
            host: 监听地址
            port: 监听端口
            secret_key: 认证密钥（可选）
            app_key: 应用密钥
            app_secret: 应用密钥
            guid: 设备GUID
            auth_callback: 认证成功后的回调函数，接收 (app_key, app_secret, guid) 参数
        """
        self.host = host
        self.port = port
        self.secret_key = secret_key
        self.app_key = app_key
        self.app_secret = app_secret
        self.guid = guid
        self.auth_callback = auth_callback
        self.logger = logging.getLogger(__name__)
        self.server = None
        self.connected_clients: Dict[str, Any] = {}
        self._running = False
    
    def setup(self):
        """检查依赖是否安装"""
        if not WEBSOCKETS_AVAILABLE:
            raise ImportError("websockets 库未安装，请运行: pip install websockets")
    
    async def _start_server(self):
        """异步启动 WebSocket 服务器"""
        try:
            self.logger.info(f"正在启动 WebSocket 服务器: ws://{self.host}:{self.port}")
            self.server = await websockets.serve(
                self._handle_client,
                self.host,
                self.port
            )
            self.logger.info(f"WebSocket 服务已启动: ws://{self.host}:{self.port}")
            self._running = True
            await asyncio.Future()
        except OSError as e:
            self.logger.error(f"WebSocket 端口被占用或无法绑定: {e}")
            self._running = False
        except Exception as e:
            self.logger.error(f"WebSocket 服务启动失败: {e}")
            self._running = False
    
    async def _handle_client(self, websocket):
        """处理客户端连接"""
        client_id = f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
        self.logger.info(f"客户端连接: {client_id}")
        
        try:
            # 等待客户端发送认证消息
            try:
                auth_message = await asyncio.wait_for(
                    websocket.recv(),
                    timeout=30
                )
            except asyncio.TimeoutError:
                self.logger.warning(f"客户端 {client_id} 认证超时")
                return
            
            # 解析认证消息
            try:
                data = json.loads(auth_message)
            except json.JSONDecodeError:
                self.logger.warning(f"客户端 {client_id} 发送了无效的 JSON 数据")
                await websocket.send(json.dumps(self.AUTH_FAILED_RESPONSE))
                return
            
            # 验证认证消息格式
            if data.get("type") != "auth":
                self.logger.warning(f"客户端 {client_id} 未发送认证消息")
                await websocket.send(json.dumps(self.AUTH_FAILED_RESPONSE))
                return
            
            app_key = data.get("app_key")
            app_secret = data.get("app_secret")
            guid = data.get("guid")
            
            if not all([app_key, app_secret, guid]):
                self.logger.warning(f"客户端 {client_id} 认证信息不完整")
                await websocket.send(json.dumps({
                    "type": "auth_failed",
                    "reason": "认证信息不完整"
                }))
                return
            
            # 认证成功
            self.logger.info(f"客户端 {client_id} 认证成功: app_key={app_key}, guid={guid}")
            await websocket.send(json.dumps(self.AUTH_SUCCESS_RESPONSE))
            
            # 调用认证回调
            if self.auth_callback:
                try:
                    self.auth_callback(app_key, app_secret, guid)
                except Exception as e:
                    self.logger.error(f"认证回调执行失败: {e}")
            
            # 将客户端添加到已连接列表
            self.connected_clients[client_id] = {
                "websocket": websocket,
                "app_key": app_key,
                "guid": guid
            }
            
            # 保持连接并处理后续消息
            try:
                async for message in websocket:
                    await self._handle_message(client_id, message)
            except websockets.exceptions.ConnectionClosed:
                pass
                
        except Exception as e:
            self.logger.error(f"处理客户端 {client_id} 时出错: {e}")
        finally:
            # 移除断开的客户端
            if client_id in self.connected_clients:
                del self.connected_clients[client_id]
            self.logger.info(f"客户端断开连接: {client_id}")

    async def _handle_message(self, client_id: str, message: str):
        """处理客户端消息"""
        try:
            data = json.loads(message)
            self.logger.debug(f"收到客户端 {client_id} 消息: {data}")

            # ✅ 广播给其他已连接的客户端（排除发送者）
            for cid, client_info in self.connected_clients.items():
                if cid != client_id:  # 不发回给发送者
                    try:
                        asyncio.create_task(client_info["websocket"].send(message))
                    except Exception as e:
                        self.logger.error(f"向客户端 {cid} 发送消息失败: {e}")
        except json.JSONDecodeError:
            self.logger.warning(f"客户端 {client_id} 发送了无效的 JSON 数据")
    
    def stop(self):
        """停止 WebSocket 服务"""
        self._running = False
        if self.server:
            self.server.close()
            self.logger.info("WebSocket 服务已停止")
    
    def broadcast(self, message: Dict[str, Any]):
        """
        广播消息给所有已认证的客户端。
        
        Args:
            message: 要发送的消息字典
        """
        if not self.connected_clients:
            return
        
        message_str = json.dumps(message)
        disconnected = []
        
        for client_id, client_info in self.connected_clients.items():
            try:
                websocket = client_info["websocket"]
                asyncio.create_task(websocket.send(message_str))
            except Exception as e:
                self.logger.error(f"向客户端 {client_id} 发送消息失败: {e}")
                disconnected.append(client_id)
        
        # 清理断开的客户端
        for client_id in disconnected:
            del self.connected_clients[client_id]
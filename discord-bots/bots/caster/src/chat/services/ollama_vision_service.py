# -*- coding: utf-8 -*-
"""
Ollama Vision 服务类，使用本地视觉模型将图片转换为文字描述

支持的模型：
- qwen3.5:0.8b - 轻量级视觉模型

注意：视觉模型的 Token 消耗与图片像素成正比。
大图片会消耗大量 KV Cache 内存，因此默认会压缩图片到合理尺寸。
"""

import base64
import httpx
import io
import logging
from typing import Optional, Tuple

from PIL import Image

from src.chat.config.chat_config import OLLAMA_VISION_CONFIG

log = logging.getLogger(__name__)

# 默认最大图片边长（像素）
# 768px 对应约 3000 个视觉 Token，平衡了细节保留和内存占用
DEFAULT_MAX_IMAGE_SIZE = 768


class OllamaVisionService:
    """Ollama Vision 服务类，使用本地视觉模型识别图片内容"""

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        max_image_size: int = DEFAULT_MAX_IMAGE_SIZE,
    ):
        """
        初始化 Ollama Vision 服务

        Args:
            base_url: Ollama 服务地址，默认从配置文件读取
            model: 使用的视觉模型名称，默认从配置文件读取
            max_image_size: 图片最大边长（像素），超过会被压缩。默认 768
        """
        self.base_url = base_url or OLLAMA_VISION_CONFIG["BASE_URL"]
        self.model = model or OLLAMA_VISION_CONFIG["MODEL"]
        self.max_image_size = max_image_size

    def _resize_image(self, image_bytes: bytes, max_size: int) -> Tuple[bytes, str]:
        """
        缩放图片到指定最大边长

        Args:
            image_bytes: 原始图片二进制数据
            max_size: 最大边长（像素）

        Returns:
            (缩放后的图片数据, MIME 类型)
        """
        img = Image.open(io.BytesIO(image_bytes))
        original_size = img.size

        # 如果图片已经足够小，直接返回
        if max(img.size) <= max_size:
            fmt = img.format or "PNG"
            mime_type = self._get_mime_type(fmt)
            return image_bytes, mime_type

        # 计算缩放比例，保持宽高比
        ratio = max_size / max(img.size)
        new_size = (int(img.width * ratio), int(img.height * ratio))

        # 高质量缩放 - 使用 Resampling.LANCZOS (Pillow >= 9.0)
        try:
            resample = Image.Resampling.LANCZOS
        except AttributeError:
            # 兼容旧版本 Pillow
            resample = Image.LANCZOS  # type: ignore

        img_resized = img.resize(new_size, resample)

        # 转回 bytes
        output = io.BytesIO()
        # 保存原始格式，如果没有格式则使用 PNG
        save_format = img.format or "PNG"
        img_resized.save(output, format=save_format, quality=95)

        mime_type = self._get_mime_type(save_format)

        log.info(
            f"图片已压缩: {original_size[0]}x{original_size[1]} → "
            f"{new_size[0]}x{new_size[1]}, 格式: {mime_type}"
        )

        return output.getvalue(), mime_type

    @staticmethod
    def _get_mime_type(image_format: str) -> str:
        """根据图片格式获取 MIME 类型"""
        mime_map = {
            "PNG": "image/png",
            "JPEG": "image/jpeg",
            "JPG": "image/jpeg",
            "GIF": "image/gif",
            "WEBP": "image/webp",
            "BMP": "image/bmp",
        }
        return mime_map.get(image_format.upper(), "image/png")

    async def describe_image(
        self,
        image_bytes: bytes,
        prompt: str = "请用中文描述这张图片的内容。",
        mime_type: str = "image/png",
        skip_resize: bool = False,
    ) -> Optional[str]:
        """
        使用 Ollama 视觉模型描述图片内容

        Args:
            image_bytes: 图片的二进制数据
            prompt: 提示词，告诉模型如何描述图片
            mime_type: 图片的 MIME 类型（压缩后会被更新）
            skip_resize: 是否跳过图片压缩（默认 False，会自动压缩）

        Returns:
            图片的文字描述，失败时返回 None
        """
        try:
            # 压缩图片以减少 Token 消耗和内存占用
            if not skip_resize:
                image_bytes, mime_type = self._resize_image(
                    image_bytes, self.max_image_size
                )

            # 将图片转换为 base64
            image_base64 = base64.b64encode(image_bytes).decode("utf-8")

            # 构建 Ollama API 请求
            # Ollama 的 /api/generate 端点支持图片输入
            timeout = httpx.Timeout(120.0, connect=10.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                url = f"{self.base_url}/api/generate"
                log.debug(f"正在请求 Ollama Vision API: {url}, 模型: {self.model}")

                response = await client.post(
                    url,
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "images": [image_base64],
                    },
                )
                response.raise_for_status()
                result = response.json()

                # 提取响应文本
                description = result.get("response", "")
                if description:
                    log.info(
                        f"Ollama Vision 成功识别图片，描述长度: {len(description)}"
                    )
                    return description.strip()

                log.warning("Ollama Vision 返回空描述")
                return None

        except httpx.HTTPStatusError as e:
            log.error(
                f"Ollama Vision API HTTP 错误: {e.response.status_code} - {e.response.text}"
            )
            log.error(f"请求 URL: {self.base_url}/api/generate")
            log.error(f"模型: {self.model}")
        except httpx.RequestError as e:
            log.error(f"Ollama Vision API 请求错误: {e}")
            log.error(f"请求 URL: {self.base_url}/api/generate")
        except Exception as e:
            log.error(f"图片识别失败: {e}", exc_info=True)
        return None

    async def check_connection(self) -> bool:
        """
        检查 Ollama 服务是否可用

        Returns:
            服务是否可用
        """
        try:
            timeout = httpx.Timeout(5.0, connect=5.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                if response.status_code == 200:
                    # 检查是否有可用的视觉模型
                    models = response.json().get("models", [])
                    model_names = [m.get("name", "") for m in models]
                    # 检查配置的模型或任何视觉模型
                    has_vision_model = any(
                        self.model in name
                        or "qwen" in name.lower()
                        or "llava" in name.lower()
                        for name in model_names
                    )
                    if not has_vision_model:
                        log.warning(
                            f"未找到视觉模型 {self.model}，可用模型: {model_names}"
                        )
                    return True
                return False
        except Exception as e:
            log.error(f"检查 Ollama 连接失败: {e}")
            return False

    async def ensure_model_available(self) -> bool:
        """
        确保视觉模型可用，如果不存在则尝试拉取

        Returns:
            模型是否可用
        """
        try:
            timeout = httpx.Timeout(300.0, connect=10.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                # 先检查模型是否已存在
                response = await client.get(f"{self.base_url}/api/tags")
                if response.status_code == 200:
                    models = response.json().get("models", [])
                    model_names = [m.get("name", "") for m in models]
                    if any(self.model in name for name in model_names):
                        log.info(f"视觉模型 {self.model} 已存在")
                        return True

                # 模型不存在，尝试拉取
                log.info(f"正在拉取视觉模型 {self.model}...")
                response = await client.post(
                    f"{self.base_url}/api/pull",
                    json={"name": self.model, "stream": False},
                )
                if response.status_code == 200:
                    log.info(f"成功拉取视觉模型 {self.model}")
                    return True
                else:
                    log.error(f"拉取模型失败: {response.text}")
                    return False

        except Exception as e:
            log.error(f"确保模型可用失败: {e}")
            return False


# 全局实例
ollama_vision_service = OllamaVisionService()

#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
@Time        : 2024/12/12 18:10
@Author      : SiYuan
@Email       : 863909694@qq.com
@File        : MemoTrace-emoji_parser.py
@Description :
"""
import base64
import html
import re
import traceback

import xmltodict
from google.protobuf.json_format import MessageToDict

from .util.protocbuf import emoji_desc_pb2


def parser_emoji(xml_content):
    result = {"md5": 0, "url": "", "width": 0, "height": 0, "desc": ""}

    def extract_msg(text):
        pattern = r"(<msg>.*?</msg>)"
        match = re.search(pattern, text, re.DOTALL)
        return match.group(0) if match else ""

    print(f"[parser_emoji] 输入类型: {type(xml_content)}, 长度: {len(xml_content) if xml_content else 0}")
    if xml_content and isinstance(xml_content, bytes):
        print(f"[parser_emoji] 原始数据前100字节: {xml_content[:100]}")
    elif xml_content:
        print(f"[parser_emoji] 内容前200字符: {str(xml_content)[:200]}")

    xml_dict = {}
    try:
        xml_dict = xmltodict.parse(xml_content)
    except Exception as e:
        try:
            xml_content = extract_msg(xml_content)
            xml_dict = xmltodict.parse(xml_content)
        except Exception as e2:
            print(f"[parser_emoji] 第二次解析失败: {e2}")

    try:
        emoji_dic = xml_dict.get("msg", {}).get("emoji", {})
        if "@androidmd5" in emoji_dic:
            md5 = emoji_dic.get("@androidmd5", "")
        else:
            md5 = emoji_dic.get("@md5", "")
        desc_bs64 = emoji_dic.get("@desc", "")
        desc = ""
        if desc_bs64:
            desc_bytes_proto = base64.b64decode(desc_bs64)
            message = emoji_desc_pb2.EmojiDescData()
            message.ParseFromString(desc_bytes_proto)
            dict_output = MessageToDict(message)
            for item in dict_output.get("descItem", []):
                desc = item.get("desc", "")
                if desc:
                    break
        url = emoji_dic.get("@cdnurl", "")
        if url:
            url = html.unescape(url)
        result = {
            "md5": md5,
            "url": url,
            "width": emoji_dic.get("@width", 0),
            "height": emoji_dic.get("@height", 0),
            "desc": desc,
        }
    except Exception as e:
        print(xml_content)
    finally:
        return result


if __name__ == "__main__":
    pass

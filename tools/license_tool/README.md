# 本地秘钥工具（两个 exe）

## 产物目录

`tools/license_tool/dist/`

| 文件 | 给谁 | 说明 |
|------|------|------|
| `show-machine-code.exe`（查看机器码） | 客户 | 显示并复制本机机器码 |
| `issue-license.exe`（生成激活码） | 仅你 | 填机器码+过期日生成激活码 |
| `private_key.pem` | 仅你 | 必须与 `issue-license.exe` 放同目录 |

## 打包

```powershell
powershell -ExecutionPolicy Bypass -File tools/license_tool/build_exes.ps1
```

## 使用

1. 把 `show-machine-code.exe` 发给客户  
2. 客户打开后点「复制机器码」发给你  
3. 你打开 `issue-license.exe`，填机器码和过期日（如 `2026-12-31`），生成并复制激活码  
4. 客户写入 `config.yaml`：

```yaml
license:
  key: "整串激活码"
```

## 注意

- `private_key.pem` 严禁发给客户  
- 激活码绑定机器；过期填到某天；客户端每 2 小时本地复查  

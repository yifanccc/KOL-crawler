# Data Sources

## X

本机执行已验证命令：`opencli twitter tweets <handle> --limit <n> --format json`。首次登录使用 `opencli twitter login`；Chrome profile 与 Cookie 永不上传。登录/验证失败时 Provider 返回 `login_required`，不推进 checkpoint。

验证登录态：

```bash
opencli twitter --help
opencli twitter tweets senerity --limit 1 --format json
```

X snowflake checkpoint 按整数比较，过滤重复后按时间从旧到新进入 Outbox。Provider 同时兼容 ISO 时间和 OpenCLI v1.8.5 的 `Sat Jul 11 10:45:46 +0000 2026` 格式，并按真实字段把 `author` 作为 handle、`name` 作为显示名。超时、命令缺失或畸形 JSON 只改变 provider 健康状态，不输出环境变量、Cookie、Authorization header 或 profile 路径。

## Binance Square

`binance_square` 只解析公开页面，默认模板为 `https://www.binance.com/en/square/profile/{handle}`，可通过 `BINANCE_SQUARE_PROFILE_URL` 覆盖。它使用独立 checkpoint；HTTP 失败或页面结构变化记录为 `failed`，不阻塞 X、Outbox 上传或心跳。

系统只识别 A 股代码/名称与其它标的标签，不采集 A 股社区内容。

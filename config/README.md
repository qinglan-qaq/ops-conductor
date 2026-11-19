# 平台配置与凭据

`config/platforms.toml` 只保存非密钥配置：adapter、平台、店铺、能力、限额和
`credential_ref`。密钥值不进入本目录、Git、Docker 镜像、日志、trace、Run
payload 或前端。

## 本地开发

1. 把密钥写入仓库根的 `.env`（已被 `.gitignore` 忽略）或 OS 环境变量：

   ```bash
   TIKTOK_SHOP_US_TOKEN=本地密钥
   ```

2. `.env.example` 只列变量名和空值，不提交真实密钥。
3. 配置中的 `credential_ref` 必须是环境变量名，例如
   `credential_ref = "TIKTOK_SHOP_US_TOKEN"`。

## CI

GitHub Actions 使用 repository secrets，并在 job 中以环境变量注入。不要在
workflow 里 `echo` 密钥，也不要把密钥写入构建产物。

## 生产

生产环境由后续切片的 `CredentialProvider` 适配器从 Vault / AWS Secrets
Manager / GCP Secret Manager 读取；`credential_ref` 不变，只换提供方。
本期只实现 `EnvCredentialProvider`，不接真实平台。

## 轮换

修改密钥存储中的值即可，`credential_ref` 不变。本期的进程启动时读取，轮换后
需要重启；不做热加载或自动轮换。

## 校验规则

- 未知字段直接拒绝；字段中不允许出现 `api_key`、`token`、`secret`、`password`。
- 同一 `adapter_id` 或 `(platform, shop_id)` 不得重复。
- `mode = "mock"` 时 `credential_ref` 必须为空。
- `mode = "live"` 时 `credential_ref` 必须非空；本期 `enabled = true` 会启动失败。
- 能力必须是 `IntegrationCapability` 的合法值；限额必须为正。

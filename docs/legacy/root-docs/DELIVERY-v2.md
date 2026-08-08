# 公司交付包流程

用于把方寸 skill 打包成统一交付 ZIP。交付包只包含 `skills/fangcun/` 和交付元数据，不包含客户素材、项目产物、日志、数据库、token、私钥或 OpenClaw 主 Agent 配置。

> 当前公司版不再区分任何版本档位；所有客户交付同一套方寸能力。公司私有定制仍通过公司分支或私有仓库隔离，但不再在公开交付流程里做档位分层。

## 一键生成

```bash
python3 skills/fangcun/tools/build_company_delivery.py \
  --company acme \
  --smoke-test
```

可指定版本：

```bash
python3 skills/fangcun/tools/build_company_delivery.py \
  --company acme \
  --version v20260708-r1
```

输出：

```text
deliveries/fangcun-acme-vYYYYMMDD-r1/
deliveries/fangcun-acme-vYYYYMMDD-r1.zip
```

交付目录内包含：

```text
skills/fangcun/        # skill 主体
DELIVERY_MANIFEST.json # 交付清单：公司、版本、commit、文件列表
CHECKSUMS.sha256       # 文件校验
README_DELIVERY.md     # 客户安装说明
```

## 公司分支初始化

创建长期公司分支、写非敏感公司 profile，并可生成首个交付包：

```bash
python3 skills/fangcun/tools/init_company_branch.py \
  --company acme \
  --build-delivery \
  --smoke-test
```

只预览不改仓库：

```bash
python3 skills/fangcun/tools/init_company_branch.py \
  --company acme \
  --dry-run
```

默认分支名：

```text
company/<company-slug>
```

## 多公司分发建议

- `main`：公共源版本。
- `company/<name>`：公司长期分支。
- 公司私有能力只进入对应公司分支，不进入 `main`。
- 从公司分支出私有包，避免把客户定制能力泄露给其他公司。

## 验收

推荐直接运行 smoke test：

```bash
python3 skills/fangcun/tools/smoke_test_delivery.py \
  deliveries/fangcun-acme-vYYYYMMDD-r1.zip \
  --expected-company acme \
  --check-isolation
```

它会检查：

- zip 完整性
- `DELIVERY_MANIFEST.json` 必要字段
- `CHECKSUMS.sha256` 校验
- manifest 文件清单 sha256
- 是否混入缓存、数据库、日志、secret/key/pem、项目产物等违禁文件
- 核心 Python 工具是否可编译
- 公司私有配置隔离：不得混入其他公司的 `company-profiles/` 或 `company-private/`

单独检查隔离：

```bash
python3 skills/fangcun/tools/check_private_isolation.py \
  deliveries/fangcun-acme-vYYYYMMDD-r1.zip \
  --mode delivery \
  --expected-company acme
```

检查 `main` 是否误带公司私有目录：

```bash
python3 skills/fangcun/tools/check_private_isolation.py . --mode main
```

也可以手工检查：

```bash
unzip -t deliveries/fangcun-acme-vYYYYMMDD-r1.zip
cat deliveries/fangcun-acme-vYYYYMMDD-r1/DELIVERY_MANIFEST.json
cat deliveries/fangcun-acme-vYYYYMMDD-r1/CHECKSUMS.sha256 | head
```

## 禁止进入交付包

- 客户原文/素材
- 项目输出
- runtime state
- logs
- databases
- tokens/secrets/private keys
- OpenClaw 主 Agent 配置与身份文件

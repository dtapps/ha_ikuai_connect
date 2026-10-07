.PHONY: sync upstream push push-force 

# ==================== 更新 / 拉取 ====================

sync: ## 拉取 origin 最新并以 fast-forward 合并（保留本地未提交改动）
	git fetch origin
	git merge --ff-only origin/main
	@echo "已同步 origin/main 最新代码，本地未提交改动已保留"

upstream: ## 跟上上游(PraxiGEN)：拉取上游最新并合并 upstream/main 到当前分支
	git fetch upstream
	git merge upstream/main --no-edit
	@echo "已合并 upstream/main 到当前分支"

# ==================== 推送 ====================

push: ## 推送到所有远程仓库
	git push origin HEAD
	@echo "推送完成！"

push-force: ## 强制推送到所有远程仓库（忽略冲突）
	git push --force origin HEAD
	@echo "强制推送完成！"

# ==================== 代码格式化 ====================

# Python 格式化（ruff 独立二进制，无需 venv/pip；已用官方脚本装到 ~/.local/bin）
format-py:
	"$$HOME/.local/bin/ruff" format .

# JSON / Markdown / YAML 格式化（prettier，npx 自动拉取）
format-web:
	npx --yes prettier --write "**/*.{json,md,yaml,yml}"

# TOML 格式化（taplo，npx 自动拉取）
format-toml:
	npx --yes @taplo/cli format "**/*.toml"

# 纯文本：去除行尾空白、确保文件以换行结尾
format-txt:
	@find . -type f -name '*.txt' -not -path './.git/*' -not -path './.venv/*' -not -path './node_modules/*' -exec sh -c 'for f; do sed -i "" -e "s/[[:space:]]*$$//" "$$f"; last=$$(tail -c1 "$$f" | od -An -tx1 | tr -d " "); [ "$$last" = "0a" ] || printf "\n" >> "$$f"; done' _ {} +

# 一键格式化全部
format: format-py format-web format-toml format-txt
	@echo "✅ 格式化完成"
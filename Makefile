.PHONY: sync upstream push push-force test format format-py format-web \
        format-toml format-txt format-markdown help

# 直接 `make` 打菜单
.DEFAULT_GOAL := help

# ==================== 帮助 ====================

help: ## 显示所有可用目标
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

# ==================== 代码格式化 ====================

# 一键格式化全部
format: format-py format-web format-toml format-txt format-markdown format-json ## 一键格式化全部
	@echo "✅ 格式化完成"

# Python 格式化（ruff 独立二进制，无需 venv/pip；已用官方脚本装到 ~/.local/bin）
format-py: ## Python 格式化（ruff）
	"$$HOME/.local/bin/ruff" format .

# JSON / Markdown / YAML 格式化（prettier，npx 自动拉取）
format-web: ## JSON / Markdown / YAML 格式化（prettier）
	npx --yes prettier --write "**/*.{json,md,yaml,yml}"

# TOML 格式化（taplo，npx 自动拉取）
format-toml: ## TOML 格式化（taplo）
	npx --yes @taplo/cli format "**/*.toml"

# 纯文本：去除行尾空白、确保文件以换行结尾
format-txt: ## 纯文本去行尾空白 / 补末尾换行
	@find . -type f -name '*.txt' -not -path './.git/*' -not -path './.venv/*' -not -path './node_modules/*' -exec sh -c 'for f; do sed -i "" -e "s/[[:space:]]*$$//" "$$f"; last=$$(tail -c1 "$$f" | od -An -tx1 | tr -d " "); [ "$$last" = "0a" ] || printf "\n" >> "$$f"; done' _ {} +

# 格式化 Markdown 文件
.PHONY: format-markdown
format-markdown:
	@echo "[Format] 格式化文档 (Markdown)…"
	@command -v markdownfmt >/dev/null 2>&1 || { \
		echo "⚠️  markdownfmt 未安装，跳过 Markdown 格式化。" ; \
		echo "   提示: 可通过运行 'go install github.com/Kunde21/markdownfmt/v3/cmd/markdownfmt@latest' 安装" ; \
		exit 0 ; \
	}
	@echo "[Format] 使用 markdownfmt 格式化 Markdown..."
	@for f in $(shell find . -type f -name '*.md' \
		-not -path '*/.pytest_cache/*' \
		-not -path './.ruff_cache/*' \
		-not -path './.venv/*'); do \
		[ -f "$$f" ] || continue; \
		markdownfmt -w "$$f" || { echo "❌ markdownfmt 格式化失败: $$f"; exit 1; }; \
	done
	@echo "[Format] Markdown 格式化完成（markdownfmt）。"

# 格式化 JSON 文件
#
# 注意：gojq 默认按字母序重排 key（它没有 -S，因为总是排序）。
# 但 hassfest 要求 manifest.json 的 key 顺序为 domain、name 打头，其余字母序，
# 所以 manifest.json 不交给 gojq，改由下面的 python 步骤按 hassfest 规则排序。
.PHONY: format-json
format-json:
	@echo "[Format] 格式化 JSON 文件..."
	@command -v gojq >/dev/null 2>&1 || { \
		echo "⚠️  gojq 未安装，跳过 JSON 格式化。" ; \
		echo "   提示: 可通过运行 'go install github.com/itchyny/gojq/cmd/gojq@latest' 安装" ; \
		exit 0 ; \
	}
	@echo "[Format] 使用 gojq 格式化 JSON..."
	@for f in $(shell find custom_components -type f -name '*.json' ! -name 'manifest.json'); do \
		[ -f "$$f" ] || continue; \
		if gojq . "$$f" > "$$f.tmp" 2>/dev/null; then \
			mv "$$f.tmp" "$$f"; \
		else \
			echo "❌ gojq 格式化失败: $$f"; rm -f "$$f.tmp"; exit 1; \
		fi; \
	done
	@echo "[Format] 按 hassfest 规则排序 manifest.json（domain、name 打头）..."
	@for f in $(shell find custom_components -type f -name 'manifest.json'); do \
		python3 -c 'import json,sys; p=sys.argv[1]; d=json.load(open(p,encoding="utf-8")); rest=sorted(k for k in d if k not in ("domain","name")); o={k:d[k] for k in (["domain","name"]+rest) if k in d}; fh=open(p,"w",encoding="utf-8"); json.dump(o,fh,ensure_ascii=False,indent=2); fh.write("\n")' "$$f" || { echo "❌ manifest 排序失败: $$f"; exit 1; }; \
	done
	@echo "[Format] JSON 格式化完成（gojq + manifest 顺序修正）。"

# ==================== 测试 ====================

# 测试栈是 pytest-homeassistant-custom-component，会带入整个 Home Assistant。
# 依赖锁在 requirements_test.txt，CI 用的是同一个文件，本地和 CI 跑的是同一套。
PY := .venv/bin/python

test: .venv/.test-deps ## 跑测试（缺环境会自动装，首次约 3 分钟）
	$(PY) -m pytest -q $(PYTEST_ARGS)

# 只跑一部分：make test PYTEST_ARGS="tests/test_config_flow.py -k scan"
.venv/.test-deps: requirements_test.txt
	@echo "准备测试环境（首次会拉 Home Assistant，约 3 分钟）…"
	python3 -m venv .venv
	.venv/bin/pip install -q --upgrade pip
	.venv/bin/pip install -q -r requirements_test.txt
	@touch .venv/.test-deps

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

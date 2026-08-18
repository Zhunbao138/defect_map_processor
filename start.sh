#!/usr/bin/env bash
# ============================================================
# 缺陷图谱处理系统 — 启动脚本
# ============================================================
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$APP_DIR/.venv"
HOST_DEFAULT="127.0.0.1"
PORT_DEFAULT=5000
PID_FILE="$APP_DIR/.server.pid"
LOG_FILE="$APP_DIR/.server.log"

# ── 颜色 ──────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; NC='\033[0m'

info()  { echo -e "${GREEN}✓${NC} $1"; }
warn()  { echo -e "${YELLOW}⚠${NC} $1"; }
err()   { echo -e "${RED}✗${NC} $1" >&2; }
title() { echo -e "\n${CYAN}┌─ $1 ─────────────────────────────┐${NC}"; }
hr()    { echo -e "${CYAN}└────────────────────────────────────┘${NC}"; }

# ── 检查虚拟环境 ──────────────────────────────────────────
activate_venv() {
    if [ -d "$VENV_DIR" ]; then
        # shellcheck disable=SC1091
        source "$VENV_DIR/bin/activate"
        info "虚拟环境已激活: $VENV_DIR"
    else
        warn "未找到虚拟环境 (.venv)，使用系统 Python"
    fi
}

# ── 检查系统依赖 ──────────────────────────────────────────
check_deps() {
    if ! command -v tesseract &>/dev/null; then
        warn "tesseract-ocr 未安装，OCR 功能不可用"
        echo "  安装: sudo apt install -y tesseract-ocr tesseract-ocr-chi-sim"
    fi
}

# ── 获取服务状态 ──────────────────────────────────────────
get_status() {
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        return 0
    else
        return 1
    fi
}

# ── 子命令: serve ─────────────────────────────────────────
cmd_serve() {
    local host="$1" port="$2"
    title "启动 Web 服务"
    echo "  地址: http://$host:$port"
    echo "  登录: $(cat "$APP_DIR/.auth" 2>/dev/null || echo '无 .auth 文件')"
    hr
    cd "$APP_DIR"
    exec python cli.py serve --host "$host" --port "$port"
}

# ── 子命令: daemon (后台 + 外网) ───────────────────────────
cmd_daemon() {
    local port="${1:-$PORT_DEFAULT}"
    if get_status; then
        warn "服务已在运行 (PID $(cat "$PID_FILE"))"
        echo "  地址: http://0.0.0.0:$port"
        return 0
    fi
    title "后台启动 (外网可访问)"
    cd "$APP_DIR"
    nohup python cli.py serve --host 0.0.0.0 --port "$port" \
        >> "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    sleep 2
    if get_status; then
        info "已启动 (PID $(cat "$PID_FILE"))"
        echo "  地址: http://0.0.0.0:$port"
        echo "  日志: $LOG_FILE"
        echo "  停止: ./start.sh stop"
    else
        err "启动失败，查看日志: $LOG_FILE"
        rm -f "$PID_FILE"
        exit 1
    fi
    hr
}

# ── 子命令: stop ──────────────────────────────────────────
cmd_stop() {
    if ! get_status; then
        warn "服务未运行"
        rm -f "$PID_FILE"
        return 0
    fi
    local pid; pid=$(cat "$PID_FILE")
    title "停止服务"
    kill "$pid" 2>/dev/null
    sleep 1
    if kill -0 "$pid" 2>/dev/null; then
        warn "优雅关闭失败，强制终止..."
        kill -9 "$pid" 2>/dev/null
    fi
    rm -f "$PID_FILE"
    info "已停止 (PID $pid)"
    hr
}

# ── 子命令: restart ───────────────────────────────────────
cmd_restart() {
    cmd_stop
    sleep 1
    cmd_daemon "$1"
}

# ── 子命令: status ────────────────────────────────────────
cmd_status() {
    local port="${1:-$PORT_DEFAULT}"
    title "服务状态"
    if get_status; then
        local pid; pid=$(cat "$PID_FILE")
        info "运行中 (PID $pid)"
        echo "  地址: http://0.0.0.0:$port"
        echo "  日志: tail -f $LOG_FILE"
    else
        warn "未运行"
        rm -f "$PID_FILE"
    fi
    hr
}

# ── 子命令: process ───────────────────────────────────────
cmd_process() {
    local input="$1"; shift
    if [ -z "$input" ]; then
        err "请指定输入文件: ./start.sh process <文件> [选项]"
        echo "  示例: ./start.sh process input/sample.xlsx -t cscan"
        exit 1
    fi
    if [ ! -f "$input" ]; then
        err "文件不存在: $input"
        exit 1
    fi
    title "处理文件"
    echo "  输入: $input"
    hr
    cd "$APP_DIR"
    exec python cli.py process "$input" "$@"
}

# ── 子命令: info ──────────────────────────────────────────
cmd_info() {
    title "项目信息"
    echo "  目录:     $APP_DIR"
    echo "  Python:   $(python3 --version 2>/dev/null || echo 'N/A')"
    echo "  .venv:    $([ -d "$VENV_DIR" ] && echo '存在' || echo '未创建')"
    echo "  Tesseract: $(tesseract --version 2>&1 | head -1 || echo '未安装')"
    echo "  数据输入: $APP_DIR/input/"
    echo "  数据输出: $APP_DIR/output/"
    if get_status; then
        info "服务运行中 (PID $(cat "$PID_FILE"))"
    else
        warn "服务未运行"
    fi
    hr
}

# ── 主入口 ─────────────────────────────────────────────────
main() {
    cd "$APP_DIR"
    activate_venv
    check_deps

    case "${1:-help}" in
        daemon)
            shift
            cmd_daemon "${1:-$PORT_DEFAULT}"
            ;;
        stop)
            cmd_stop
            ;;
        restart)
            shift
            cmd_restart "${1:-$PORT_DEFAULT}"
            ;;
        status)
            shift
            cmd_status "${1:-$PORT_DEFAULT}"
            ;;
        serve)
            shift
            cmd_serve "${1:-$HOST_DEFAULT}" "${2:-$PORT_DEFAULT}"
            ;;
        serve:public)
            cmd_serve "0.0.0.0" "${2:-$PORT_DEFAULT}"
            ;;
        process)
            shift
            cmd_process "$@"
            ;;
        info)
            cmd_info
            ;;
        help|--help|-h)
            echo "用法: ./start.sh <命令> [参数]"
            echo ""
            echo "命令:"
            echo "  daemon [port]           后台启动，外网可访问 (0.0.0.0)"
            echo "  stop                    停止后台服务"
            echo "  restart [port]          重启后台服务"
            echo "  status [port]           查看服务状态"
            echo "  serve [host] [port]     前台启动 (默认 127.0.0.1:5000)"
            echo "  serve:public [port]     前台启动，监听 0.0.0.0"
            echo "  process <文件> [选项]    处理 Excel 文件"
            echo "    -t cscan              指定为模板二"
            echo "    -t kuanhouban         指定为模板三"
            echo "    --no-ocr              跳过 OCR"
            echo "    -o <目录>             指定输出目录"
            echo "  info                    查看项目环境信息"
            echo "  help                    显示此帮助"
            echo ""
            echo "常用:"
            echo "  ./start.sh daemon        # 后台启动，外网访问"
            echo "  ./start.sh stop          # 停止"
            echo "  ./start.sh restart       # 重启"
            echo "  ./start.sh status        # 查看状态"
            echo "  tail -f .server.log      # 查看日志"
            ;;
        *)
            err "未知命令: $1"
            echo "用法: ./start.sh <daemon|stop|restart|status|serve|process|info|help>"
            exit 1
            ;;
    esac
}

main "$@"

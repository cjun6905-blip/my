#!/bin/bash

# 类脑娘邀请脚本
# 让类脑娘来帮你配置一切吧～

# 移除 set -e，避免 read 命令返回非零状态时脚本意外退出
# 改用手动错误处理

# 颜色定义 - 类脑娘的配色
PINK='\033[38;5;213m'
PEACH='\033[38;5;217m'
SKY='\033[38;5;117m'
CYAN='\033[38;5;159m'
LILAC='\033[38;5;183m'
MINT='\033[38;5;120m'
SUN='\033[38;5;220m'
HEART='\033[38;5;204m'
CORAL='\033[38;5;209m'
GOLD='\033[38;5;221m'

# 暖色渐变 - Warm Gradient
WARM_1='\033[38;5;226m' # Bright Yellow
WARM_2='\033[38;5;214m' # Orange
WARM_3='\033[38;5;209m' # Salmon
WARM_4='\033[38;5;203m' # Dark Pink
WARM_5='\033[38;5;198m' # Hot Pink
WARM_6='\033[38;5;163m' # Purple
NC='\033[0m'

# 打印带颜色的消息 - 类脑娘风格
say_hello() {
    echo -e "${PINK}💕 $1${NC}"
}

say_success() {
    echo -e "${MINT}✨ $1${NC}"
}

say_wait() {
    echo -e "${SKY}🌸 $1${NC}"
}

say_warning() {
    echo -e "${SUN}💫 $1${NC}"
}

say_oops() {
    echo -e "${HEART}😅 $1${NC}"
}

# 打印欢迎信息 - 类脑娘来迎接你啦
print_welcome() {
    clear
    echo ""
    echo ""
    echo -e "   ${WARM_1}██████╗ ██████╗  █████╗ ██╗███╗   ██╗      ██████╗ ██╗██████╗ ██╗${NC}"
    echo -e "   ${WARM_2}██╔══██╗██╔══██╗██╔══██╗██║████╗  ██║     ██╔════╝ ██║██╔══██╗██║${NC}"
    echo -e "   ${WARM_3}██████╔╝██████╔╝███████║██║██╔██╗ ██║     ██║  ███╗██║██████╔╝██║${NC}"
    echo -e "   ${WARM_4}██╔══██╗██╔══██╗██╔══██║██║██║╚██╗██║     ██║   ██║██║██╔══██╗██║${NC}"
    echo -e "   ${WARM_5}██████╔╝██║  ██║██║  ██║██║██║ ╚████║     ╚██████╔╝██║██║  ██║███████╗${NC}"
    echo -e "   ${WARM_6}╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝      ╚═════╝ ╚═╝╚═╝  ╚═╝╚══════╝${NC}"
    echo ""
    echo -e "          ${WARM_4}✨ 欢迎来到类脑娘家！让我来帮你配置一切吧～ ✨${NC}"
    echo ""
    echo ""
}

# 检查 .env 文件是否存在
check_env_file() {
    if [ -f ".env" ]; then
        say_warning "哎呀～检测到 .env 文件已经存在啦！"
        echo ""
        say_hello "类脑娘可能已经在这里住过了，要重新装修一下吗？"
        local reply=""
        printf "是否重新配置？(y/N): "
        read -r reply < /dev/tty
        echo ""
        if [[ ! "$reply" =~ ^[Yy]$ ]]; then
            say_success "好哒～那就保持现状！"
            return 1
        fi
        say_wait "备份一下旧配置..."
        cp .env .env.backup.$(date +%Y%m%d_%H%M%S)
        say_success "备份完成～"
    fi
    return 0
}

# 读取用户输入
ask_question() {
    local question="$1"
    local default="$2"
    local required="$3"
    local input=""

    # 所有提示信息输出到 stderr，避免被命令替换捕获
    echo "" >&2
    if [ -n "$default" ]; then
        echo -e "${PINK}💕 $question [默认: $default]${NC}" >&2
        echo -n "你的回答: " >&2
        read -r input < /dev/tty
        if [ -z "$input" ]; then
            input="$default"
        fi
        # 只有最终结果输出到 stdout
        printf '%s\n' "$input"
    else
        while true; do
            echo -e "${PINK}💕 $question${NC}" >&2
            echo -n "你的回答: " >&2
            read -r input < /dev/tty
            if [ -n "$input" ]; then
                printf '%s\n' "$input"
                return 0
            fi
            if [ "$required" = "true" ]; then
                echo -e "${HEART}😅 这个必须要填哦～${NC}" >&2
            else
                printf '\n'
                return 0
            fi
        done
    fi
}

# 配置必需项
configure_required() {
    say_wait "首先来配置一些必要的信息～"
    echo "────────────────────────────────────────"

    DISCORD_TOKEN="YOUR_DISCORD_TOKEN"

    echo ""
    say_hello "接下来是 Google Gemini API 密钥～"
    say_wait "用于RAG检索功能（世界书、论坛搜索等）"
    say_wait "可以输入多个密钥哦，每个占一行，输入空行结束"
    say_hello "获取地址: https://makersuite.google.com/app/apikey"
    say_warning "如果留空，RAG检索功能将被禁用，但AI对话仍可使用"

    GOOGLE_API_KEYS="YOUR_GOOGLE_API_KEYS"
    key_count=0
    local key=""
    while true; do
        # 输出提示到 stderr，避免干扰 stdout
        printf "  密钥 #%d (直接回车跳过): " "$((key_count + 1))" >&2
        read -r key < /dev/tty
        if [ -z "$key" ]; then
            if [ $key_count -eq 0 ]; then
                say_warning "跳过 Gemini API 密钥配置～"
                say_warning "RAG检索功能将被禁用"
                SKIP_RAG=true
            fi
            break
        fi
        if [ -n "$GOOGLE_API_KEYS" ]; then
            GOOGLE_API_KEYS="YOUR_GOOGLE_API_KEYS"
        else
            GOOGLE_API_KEYS="YOUR_GOOGLE_API_KEYS"
        fi
        key_count=$((key_count + 1))
    done
}

# 配置自定义 Gemini 端点
configure_gemini_endpoint() {
    echo ""
    say_hello "（可选）自定义 Gemini API 端点"
    say_wait "用于AI对话功能"
    say_warning "如果不配置，将无法使用AI对话功能"
    
    CUSTOM_GEMINI_URL=$(ask_question "自定义端点 URL" "" "true")
    CUSTOM_GEMINI_API_KEY="YOUR_CUSTOM_GEMINI_API_KEY"
}

# 配置数据库
configure_database() {
    echo ""
    say_wait "接下来配置 PostgreSQL 数据库～"
    echo "────────────────────────────────────────"

    POSTGRES_DB=$(ask_question "数据库名称" "braingirl_db" "false")
    POSTGRES_USER=$(ask_question "数据库用户名" "user" "false")
    POSTGRES_PASSWORD="YOUR_POSTGRES_PASSWORD"
    DB_PORT=$(ask_question "数据库端口" "5432" "false")
}

# 配置 Discord
configure_discord() {
    echo ""
    say_wait "配置 Discord 相关设置～"
    echo "────────────────────────────────────────"

    say_hello "（可选）开发服务器 ID，用于快速同步命令"
    say_wait "留空则进行全局同步（可能需要一小时）"
    GUILD_ID=$(ask_question "开发服务器 ID" "" "false")

    DEVELOPER_USER_IDS=$(ask_question "开发者用户 ID（多个用逗号分隔）" "" "false")
    ADMIN_ROLE_IDS=$(ask_question "管理员角色 ID（多个用逗号分隔）" "" "false")
}

# 配置功能开关
configure_features() {
    echo ""
    say_wait "配置一些功能开关～"
    echo "────────────────────────────────────────"

    local reply=""
    printf "启用聊天功能？(Y/n): "
    read -r reply < /dev/tty
    echo ""
    if [[ "$reply" =~ ^[Nn]$ ]]; then
        CHAT_ENABLED="False"
        say_warning "聊天功能已关闭～"
    else
        CHAT_ENABLED="True"
        say_success "聊天功能已开启～"
    fi

    printf "记录 AI 完整上下文（用于调试）？(y/N): "
    read -r reply < /dev/tty
    echo ""
    if [[ "$reply" =~ ^[Yy]$ ]]; then
        LOG_AI_FULL_CONTEXT="true"
        say_success "调试日志已开启～"
    else
        LOG_AI_FULL_CONTEXT="false"
    fi
}

# 配置其他选项
configure_other() {
    echo ""
    say_wait "还有一些其他选项～"
    echo "────────────────────────────────────────"

    DISABLED_TOOLS=$(ask_question "禁用的工具（多个用逗号分隔）" "get_yearly_summary" "false")
    say_hello "（可选）论坛搜索频道 ID，用于论坛搜索功能"
    say_wait "留空则不启用论坛搜索"
    FORUM_SEARCH_CHANNEL_IDS=$(ask_question "论坛搜索频道 ID（多个用逗号分隔）" "" "false")
    say_hello "类脑币奖励服务器 ID，用于类脑币奖励功能"
    say_wait "留空则默认使用开发服务器 ID"
    COIN_REWARD_GUILD_IDS=$(ask_question "类脑币奖励服务器 ID（多个用逗号分隔）" "$GUILD_ID" "false")
}

# 生成 .env 文件
generate_env_file() {
    echo ""
    say_wait "正在生成配置文件..."

    cat > .env << EOF
# 类脑娘的环境配置文件
# 由类脑娘亲手为你生成哦～

# Discord 机器人令牌
DISCORD_TOKEN="YOUR_DISCORD_TOKEN"

# 开发服务器 ID（用于快速同步命令）
GUILD_ID="$GUILD_ID"

# 权限控制
DEVELOPER_USER_IDS="$DEVELOPER_USER_IDS"
ADMIN_ROLE_IDS="$ADMIN_ROLE_IDS"

# Gemini AI 配置
# 自定义端点（用于AI对话）
CUSTOM_GEMINI_URL="$CUSTOM_GEMINI_URL"
CUSTOM_GEMINI_API_KEY="YOUR_CUSTOM_GEMINI_API_KEY"

# RAG检索用的API密钥
GOOGLE_API_KEYS_LIST="$GOOGLE_API_KEYS"

# PostgreSQL 数据库配置
POSTGRES_DB="$POSTGRES_DB"
POSTGRES_USER="$POSTGRES_USER"
POSTGRES_PASSWORD="YOUR_POSTGRES_PASSWORD"
DB_PORT=$DB_PORT

# 功能开关
CHAT_ENABLED=$CHAT_ENABLED
LOG_AI_FULL_CONTEXT=$LOG_AI_FULL_CONTEXT

# 工具禁用列表
DISABLED_TOOLS="$DISABLED_TOOLS"

# 类脑币系统
COIN_REWARD_GUILD_IDS="$COIN_REWARD_GUILD_IDS"

# 论坛搜索频道
FORUM_SEARCH_CHANNEL_IDS="$FORUM_SEARCH_CHANNEL_IDS"

# Discord OAuth（可选）
VITE_DISCORD_CLIENT_ID=""
DISCORD_CLIENT_SECRET="YOUR_DISCORD_CLIENT_SECRET"

# Gemini 调试
LOG_DETAILED_GEMINI_PROCESS=True

# ComfyUI 图像生成配置
COMFYUI_SERVER_ADDRESS=""
COMFYUI_WORKFLOW_PATH=""
EOF

    say_success "配置文件生成完成～"
}

# 询问是否启动服务
ask_start_service() {
    echo ""
    say_hello "配置文件已经准备好啦！"
    say_wait "要不要现在就让类脑娘住进来呢？"
    local reply=""
    printf "现在启动服务吗？(Y/n): "
    read -r reply < /dev/tty
    echo ""
    if [[ ! "$reply" =~ ^[Nn]$ ]]; then
        return 0
    fi
    return 1
}

# 等待数据库就绪
wait_for_db() {
    local max_attempts=30
    local attempt=1
    local db_host="db"
    local db_port="5432"

    say_wait "等待数据库启动..."
    echo ""

    while [ $attempt -le $max_attempts ]; do
        if docker compose exec -T db pg_isready -h $db_host -p $db_port > /dev/null 2>&1; then
            say_success "数据库已就绪～"
            echo ""
            return 0
        fi

        printf "\r  等待中... ($attempt/$max_attempts)" >&2
        sleep 2
        attempt=$((attempt + 1))
    done

    echo ""
    say_oops "数据库启动超时，请检查 Docker 容器状态"
    docker compose ps db
    exit 1
}

# 启动服务
start_service() {
    echo ""
    say_wait "开始准备类脑娘的新家..."
    echo ""

    # 检查 Docker 是否运行
    if ! docker info > /dev/null 2>&1; then
        say_oops "Docker 好像没启动呢～请先启动 Docker 再试一次"
        exit 1
    fi

    # 停止现有容器
    say_wait "清理一下旧环境..."
    docker compose down 2>/dev/null || true

    # 构建镜像
    say_wait "正在准备类脑娘的房间（构建镜像）..."
    say_hello "这可能需要几分钟，耐心等待哦～"
    if docker compose build; then
        say_success "房间准备好了～"
    else
        say_oops "房间装修出问题了..."
        exit 1
    fi

    # 启动服务
    say_wait "让类脑娘住进来..."
    if docker compose up -d; then
        say_success "类脑娘已经住进来了～"
    else
        say_oops "搬家过程出问题了..."
        exit 1
    fi

    # 等待数据库就绪
    wait_for_db

    # 初始化数据库
    say_wait "帮类脑娘整理一下房间（初始化数据库）..."
    if docker compose exec -T bot_app alembic upgrade head; then
        say_success "房间整理完毕～"
    else
        say_oops "整理房间出问题了..."
        exit 1
    fi

    # 显示状态
    echo ""
    say_wait "看看类脑娘的状态～"
    docker compose ps
    echo ""

    echo ""
    echo -e "${PINK}╔══════════════════════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${PINK}║${NC}                                                                                      ${PINK}║${NC}"
    echo -e "${PINK}║${NC}     ${CYAN}🌸 耶！类脑娘已经准备好啦！快去 Discord 里 @类脑娘 打招呼吧～ 🌸${NC}             ${PINK}║${NC}"
    echo -e "${PINK}║${NC}                                                                                      ${PINK}║${NC}"
    echo -e "${PINK}╚══════════════════════════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    say_hello "常用命令："
    echo "  查看日志: docker compose logs -f bot_app"
    echo "  停止服务: docker compose down"
    echo "  重启服务: docker compose restart"
    echo ""
}

# 主函数
main() {
    print_welcome

    # 检查 .env 文件
    if ! check_env_file; then
        ask_start_service && start_service
        exit 0
    fi

    # 配置各项
    configure_required
    configure_gemini_endpoint
    configure_database
    configure_discord
    configure_features
    configure_other

    # 生成 .env 文件
    generate_env_file

    # 询问是否启动服务
    if ask_start_service; then
        start_service
    else
        say_success "配置文件已经准备好啦～"
        echo ""
        say_hello "想找类脑娘的时候，运行这些命令就好："
        echo ""
        echo -e "${CYAN}  docker compose build${NC}"
        echo -e "${CYAN}  docker compose up -d${NC}"
        echo -e "${CYAN}  docker compose exec bot_app alembic upgrade head${NC}"
        echo ""
    fi
}

# 运行主函数
main


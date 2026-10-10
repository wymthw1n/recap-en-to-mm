#!/usr/bin/env bash
# ==============================================================================
# Interactive One-Click Deployer & Manager | Recap English -> Myanmar (RC)
# ==============================================================================
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# ANSI Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m' # No Color

SERVICE_NAME="recap-en-to-mm"
PYTHON_BIN="$DIR/.venv/bin/python3"
PIP_BIN="$DIR/.venv/bin/pip"

# Check root privilege
check_root() {
  if [ "$(id -u)" -ne 0 ]; then
    echo -e "${RED}❌ Please run this deploy script with root privileges (sudo ./deploy.sh)${NC}"
    exit 1
  fi
}

# Print Header Banner
print_banner() {
  echo -e "${BOLD}${CYAN}======================================================================${NC}"
  echo -e "${BOLD}${CYAN}   🎬 RECAP EN → MM (RC)  |  Interactive One-Click Deployer          ${NC}"
  echo -e "${BOLD}${CYAN}   Subtitles · Demucs Vocal Separation · Smart Sync Video Engine      ${NC}"
  echo -e "${BOLD}${CYAN}======================================================================${NC}\n"
}

# Find an available local port
find_free_port() {
  local port=8005
  while :; do
    if ! ss -tulpn 2>/dev/null | grep -q ":$port " && ! lsof -i :$port >/dev/null 2>&1; then
      if python3 -c "import socket; s = socket.socket(); s.bind(('127.0.0.1', $port)); s.close()" 2>/dev/null; then
        echo "$port"
        return
      fi
    fi
    port=$((port + 1))
    if [ "$port" -gt 8999 ]; then
      echo "8080"
      return
    fi
  done
}

# Detect Public IP
detect_public_ip() {
  local ip
  ip=$(curl -s -m 5 https://api.ipify.org 2>/dev/null || curl -s -m 5 https://ifconfig.me 2>/dev/null || curl -s -m 5 https://icanhazip.com 2>/dev/null || echo "127.0.0.1")
  echo "$ip" | tr -d '[:space:]'
}

# 1. System Dependencies Setup
step_system_dependencies() {
  echo -e "${BLUE}${BOLD}[1/7] Checking & installing system dependencies...${NC}"
  local packages=(ffmpeg ffprobe caddy python3 python3-venv python3-pip curl git fontconfig fonts-noto-core fonts-sil-padauk fonts-noto-extra)
  local missing=()
  for pkg in "${packages[@]}"; do
    if ! dpkg -s "$pkg" &>/dev/null && ! command -v "$pkg" &>/dev/null; then
      missing+=("$pkg")
    fi
  done

  if [ ${#missing[@]} -gt 0 ]; then
    echo -e "${YELLOW}Installing required packages: ${missing[*]}...${NC}"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq "${missing[@]}"
  fi
  fc-cache -f >/dev/null 2>&1 || true
  echo -e "${GREEN}✓ Core tools & Burmese fonts verified (ffmpeg, caddy, python3, Noto Sans Myanmar)${NC}"
}

# 2. Virtual Environment & Python Packages
step_python_environment() {
  echo -e "\n${BLUE}${BOLD}[2/7] Setting up Python virtual environment (.venv)...${NC}"
  if [ ! -d ".venv" ]; then
    python3 -m venv .venv
  fi

  echo -e "${DIM}Updating pip and installing requirements.txt...${NC}"
  "$PIP_BIN" install --upgrade pip -q
  "$PIP_BIN" install -r requirements.txt -q
  
  if [ -f "$DIR/.venv/bin/playwright" ]; then
    echo -e "${DIM}Ensuring Playwright browser binaries are present...${NC}"
    "$DIR/.venv/bin/playwright" install chromium 2>/dev/null || true
  fi
  echo -e "${GREEN}✓ Python packages installed successfully${NC}"
}

# 3. Pre-caching AI Models for All-Ready Stage
step_precache_models() {
  echo -e "\n${BLUE}${BOLD}[3/7] Pre-caching AI models (Whisper + Demucs ONNX vocal remover)...${NC}"
  if [ -f "$DIR/scripts/prewarm_models.py" ]; then
    "$PYTHON_BIN" "$DIR/scripts/prewarm_models.py"
  elif [ -f "$DIR/scripts/download_whisper.py" ]; then
    "$PYTHON_BIN" "$DIR/scripts/download_whisper.py"
  fi
  echo -e "${GREEN}✓ AI Models pre-warmed for zero-latency execution${NC}"
}

# 4. Interactive Configuration (Port, Domain, API Keys)
step_interactive_configuration() {
  local auto_mode="$1"
  echo -e "\n${BLUE}${BOLD}[4/7] Configuring network, domain, and API settings...${NC}"
  
  local default_port
  default_port=$(find_free_port)
  local public_ip
  public_ip=$(detect_public_ip)
  local default_domain="rc.${public_ip}.sslip.io"

  if [ "$auto_mode" = "true" ] || [ ! -t 0 ]; then
    CHOSEN_PORT="$default_port"
    CHOSEN_DOMAIN="$default_domain"
    echo -e "${GREEN}✓ Using auto port: ${BOLD}${CHOSEN_PORT}${NC}"
    echo -e "${GREEN}✓ Using auto domain: ${BOLD}${CHOSEN_DOMAIN}${NC}"
  else
    # Interactive Port Prompt
    read -r -p "$(echo -e "${CYAN}Enter local port [default: ${BOLD}${default_port}${NC}${CYAN}]: ${NC}")" input_port
    CHOSEN_PORT="${input_port:-$default_port}"

    # Interactive Domain Prompt
    read -r -p "$(echo -e "${CYAN}Enter public domain [default: ${BOLD}${default_domain}${NC}${CYAN}]: ${NC}")" input_domain
    CHOSEN_DOMAIN="${input_domain:-$default_domain}"

    # Interactive Gemini API Key Prompt
    local current_gemini=""
    if [ -f "$DIR/.env" ]; then
      current_gemini=$(grep -E "^GEMINI_API_KEY=" "$DIR/.env" | cut -d'=' -f2- | tr -d '"' | tr -d "'")
    fi
    if [ -z "$current_gemini" ]; then
      read -r -p "$(echo -e "${CYAN}Enter Gemini API Key (optional, press Enter to set in Web UI later): ${NC}")" input_gemini
      if [ -n "$input_gemini" ]; then
        echo "GEMINI_API_KEY=\"$input_gemini\"" >> "$DIR/.env"
        echo -e "${GREEN}✓ Gemini API key saved to .env${NC}"
      fi
    else
      echo -e "${GREEN}✓ Existing Gemini API key detected in .env${NC}"
    fi

    # Interactive HF Token Prompt
    local current_hf=""
    if [ -f "$DIR/.env" ]; then
      current_hf=$(grep -E "^HF_TOKEN=" "$DIR/.env" | cut -d'=' -f2- | tr -d '"' | tr -d "'")
    fi
    if [ -z "$current_hf" ]; then
      read -r -p "$(echo -e "${CYAN}Enter HuggingFace Token (optional, press Enter to skip): ${NC}")" input_hf
      if [ -n "$input_hf" ]; then
        echo "HF_TOKEN=\"$input_hf\"" >> "$DIR/.env"
        echo -e "${GREEN}✓ HuggingFace token saved to .env${NC}"
      fi
    fi
  fi
}

# 5. Caddy Reverse Proxy Setup
step_caddy_proxy() {
  echo -e "\n${BLUE}${BOLD}[5/7] Configuring Caddy reverse proxy...${NC}"
  local caddyfile="/etc/caddy/Caddyfile"
  mkdir -p /etc/caddy
  [ -f "$caddyfile" ] || touch "$caddyfile"

  # Backup
  cp "$caddyfile" "${caddyfile}.bak.$(date +%s)"

  local start_mark="# === RECAP_MM_MANAGED_BLOCK_START ==="
  local end_mark="# === RECAP_MM_MANAGED_BLOCK_END ==="

  local managed_block
  managed_block=$(cat <<EOF
$start_mark
$CHOSEN_DOMAIN {
	encode zstd gzip

	request_body {
		max_size 4GB
	}

	reverse_proxy 127.0.0.1:$CHOSEN_PORT
}
$end_mark
EOF
)

  # Replace existing block or append safely
  if grep -q "$start_mark" "$caddyfile"; then
    sed -i "/$start_mark/,/$end_mark/d" "$caddyfile"
  fi

  echo "" >> "$caddyfile"
  echo "$managed_block" >> "$caddyfile"

  # Validate and reload Caddy
  if caddy validate --config "$caddyfile" &>/dev/null; then
    systemctl reload caddy 2>/dev/null || systemctl restart caddy
    echo -e "${GREEN}✓ Caddy reverse proxy configured: ${BOLD}${CHOSEN_DOMAIN}${NC} → 127.0.0.1:${CHOSEN_PORT}${NC}"
  else
    echo -e "${RED}⚠️ Caddy validation failed. Restoring backup.${NC}"
    cp "${caddyfile}.bak."* "$caddyfile" 2>/dev/null || true
    systemctl reload caddy 2>/dev/null || true
  fi
}

# 6. Systemd Service Deployment
step_systemd_service() {
  echo -e "\n${BLUE}${BOLD}[6/7] Configuring and launching background service...${NC}"
  local service_file="/etc/systemd/system/${SERVICE_NAME}.service"

  cat <<EOF > "$service_file"
[Unit]
Description=Recap English to Myanmar Web Engine (RC)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$DIR
ExecStart=$DIR/.venv/bin/uvicorn web.main:app --host 127.0.0.1 --port $CHOSEN_PORT --log-level info
Restart=always
RestartSec=3
Environment=PYTHONIOENCODING=utf-8
Environment=PYTHONUTF8=1

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable "${SERVICE_NAME}.service" --now >/dev/null 2>&1
  systemctl restart "${SERVICE_NAME}.service"
  echo -e "${GREEN}✓ Systemd service '${SERVICE_NAME}' active and enabled on boot${NC}"
}

# 7. Health Check Verification
step_health_verification() {
  echo -e "\n${BLUE}${BOLD}[7/7] Verifying live service health...${NC}"
  local healthy=false
  for _ in {1..25}; do
    if curl -s -f "http://127.0.0.1:${CHOSEN_PORT}/api/health" &>/dev/null || curl -s -f "http://127.0.0.1:${CHOSEN_PORT}/" &>/dev/null; then
      healthy=true
      break
    fi
    sleep 0.5
  done

  if [ "$healthy" = true ]; then
    echo -e "${GREEN}✓ Web application is responsive and healthy!${NC}"
  else
    echo -e "${YELLOW}⚠️ Server is initializing. Check live logs if needed.${NC}"
  fi
}

# Print Deployment Complete Summary
print_summary() {
  echo -e "\n${BOLD}${GREEN}======================================================================${NC}"
  echo -e "${BOLD}${GREEN}   🎉 DEPLOYMENT COMPLETE — ALL-READY STAGE REACHED!                  ${NC}"
  echo -e "${BOLD}${GREEN}======================================================================${NC}"
  echo -e "${BOLD}🌐 Public Web App URL :${NC} ${BOLD}${CYAN}https://${CHOSEN_DOMAIN}${NC}"
  echo -e "${BOLD}🔌 Local Port Address :${NC} http://127.0.0.1:${CHOSEN_PORT}"
  echo -e "${BOLD}⚙️  Systemd Service   :${NC} ${SERVICE_NAME}.service"
  echo -e ""
  echo -e "${BOLD}Handy Management Commands:${NC}"
  echo -e "  • Check Status : ${BOLD}systemctl status ${SERVICE_NAME}${NC}"
  echo -e "  • View Live Log: ${BOLD}journalctl -u ${SERVICE_NAME} -f${NC}"
  echo -e "  • Restart App  : ${BOLD}systemctl restart ${SERVICE_NAME}${NC}"
  echo -e "  • Stop App     : ${BOLD}systemctl stop ${SERVICE_NAME}${NC}"
  echo -e "${BOLD}${GREEN}======================================================================${NC}\n"
}

# Main Full Deployment Workflow
run_full_deployment() {
  local auto_mode="${1:-false}"
  check_root
  step_system_dependencies
  step_python_environment
  step_interactive_configuration "$auto_mode"
  step_precache_models
  step_caddy_proxy
  step_systemd_service
  step_health_verification
  print_summary
}

# Show Service Status
show_status() {
  echo -e "\n${CYAN}--- Service Status ---${NC}"
  systemctl status "${SERVICE_NAME}" --no-pager || true
  echo ""
}

# View Live Logs
view_logs() {
  echo -e "\n${CYAN}Tailing live logs for ${SERVICE_NAME}... (Press Ctrl+C to exit)${NC}"
  journalctl -u "${SERVICE_NAME}" -f
}

# Restart Service
restart_app() {
  check_root
  echo -e "\n${YELLOW}Restarting ${SERVICE_NAME} and Caddy...${NC}"
  systemctl restart "${SERVICE_NAME}"
  systemctl reload caddy 2>/dev/null || true
  echo -e "${GREEN}✓ Restart complete.${NC}"
  show_status
}

# Stop Service
stop_app() {
  check_root
  echo -e "\n${YELLOW}Stopping ${SERVICE_NAME}...${NC}"
  systemctl stop "${SERVICE_NAME}"
  echo -e "${GREEN}✓ Service stopped.${NC}"
}

# Interactive Menu
interactive_menu() {
  while :; do
    print_banner
    echo -e "Please select an action:"
    echo -e "  ${BOLD}1)${NC} ${GREEN}Deploy / Update & Start Service (Recommended - All-Ready Stage)${NC}"
    echo -e "  ${BOLD}2)${NC} Pre-cache AI Models (Whisper + Demucs ONNX)"
    echo -e "  ${BOLD}3)${NC} Check Status & Health"
    echo -e "  ${BOLD}4)${NC} View Live Logs (journalctl)"
    echo -e "  ${BOLD}5)${NC} Restart Service"
    echo -e "  ${BOLD}6)${NC} Stop Service"
    echo -e "  ${BOLD}0)${NC} Exit"
    echo ""
    read -r -p "$(echo -e "${CYAN}Enter choice [1-6, 0]: ${NC}")" choice
    case "$choice" in
      1)
        run_full_deployment "false"
        break
        ;;
      2)
        check_root
        step_python_environment
        step_precache_models
        ;;
      3)
        show_status
        ;;
      4)
        view_logs
        ;;
      5)
        restart_app
        ;;
      6)
        stop_app
        ;;
      0)
        echo "Exiting."
        exit 0
        ;;
      *)
        echo -e "${RED}Invalid option. Please try again.${NC}\n"
        ;;
    esac
    read -r -p "Press Enter to continue..." _
  done
}

# Entrypoint argument parsing
case "$1" in
  --yes|-y|--auto)
    print_banner
    run_full_deployment "true"
    ;;
  --precache|-p)
    print_banner
    check_root
    step_python_environment
    step_precache_models
    ;;
  --status|-s)
    show_status
    ;;
  --logs|-l)
    view_logs
    ;;
  --restart|-r)
    restart_app
    ;;
  --stop)
    stop_app
    ;;
  *)
    if [ -t 0 ]; then
      interactive_menu
    else
      print_banner
      run_full_deployment "true"
    fi
    ;;
esac

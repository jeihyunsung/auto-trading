# Google Cloud Platform 배포 가이드

Auto Trading Bot을 Google Cloud Compute Engine에서 실행하는 방법입니다.

## 목차

1. [사전 준비](#1-사전-준비)
2. [VM 인스턴스 생성](#2-vm-인스턴스-생성)
3. [VM 환경 설정](#3-vm-환경-설정)
4. [프로젝트 배포](#4-프로젝트-배포)
5. [서비스 등록 및 실행](#5-서비스-등록-및-실행)
6. [모니터링 및 관리](#6-모니터링-및-관리)
7. [문제 해결](#7-문제-해결)

---

## 1. 사전 준비

### 1.1 Google Cloud CLI 설치

**macOS:**
```bash
brew install google-cloud-sdk
```

**Ubuntu/Debian:**
```bash
sudo apt-get install google-cloud-cli
```

### 1.2 GCP 프로젝트 설정

```bash
# 로그인
gcloud auth login

# 프로젝트 목록 확인
gcloud projects list

# 프로젝트 설정
gcloud config set project YOUR_PROJECT_ID

# 현재 설정 확인
gcloud config list
```

### 1.3 Compute Engine API 활성화

```bash
gcloud services enable compute.googleapis.com
```

---

## 2. VM 인스턴스 생성

### 2.1 CLI로 생성

```bash
gcloud compute instances create trading-bot \
    --zone=asia-northeast3-a \
    --machine-type=e2-small \
    --image-family=ubuntu-2204-lts \
    --image-project=ubuntu-os-cloud \
    --boot-disk-size=20GB \
    --tags=trading-bot
```

### 2.2 권장 사양

| 머신 타입 | vCPU | 메모리 | 월 예상 비용 | 용도 |
|-----------|------|--------|-------------|------|
| e2-micro | 0.25 | 1GB | 무료 (Free Tier) | 테스트용 |
| **e2-small** | 0.5 | 2GB | ~$15 | **권장** |
| e2-medium | 1 | 4GB | ~$30 | 여유있는 운영 |

### 2.3 리전 선택

| 리전 | 위치 | 지연시간 |
|------|------|---------|
| `asia-northeast3-a` | 서울 | 최소 |
| `asia-northeast1-a` | 도쿄 | 낮음 |
| `us-central1-a` | 미국 중부 | 높음 |

### 2.4 GCP Console에서 생성 (대안)

1. https://console.cloud.google.com/compute/instances 접속
2. "인스턴스 만들기" 클릭
3. 설정:
   - 이름: `trading-bot`
   - 리전: `asia-northeast3 (서울)`
   - 머신 유형: `e2-small`
   - 부팅 디스크: Ubuntu 22.04 LTS, 20GB

---

## 3. VM 환경 설정

### 3.1 SSH 접속

```bash
gcloud compute ssh trading-bot --zone=asia-northeast3-a
```

### 3.2 시스템 업데이트

```bash
sudo apt update && sudo apt upgrade -y
```

### 3.3 Python 3.12 설치

```bash
sudo apt install -y software-properties-common
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt install -y python3.12 python3.12-venv python3.12-dev
```

### 3.4 uv 설치 (패키지 관리자)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc

# 설치 확인
uv --version
```

### 3.5 Git 설치

```bash
sudo apt install -y git
```

---

## 4. 프로젝트 배포

### 4.1 방법 A: Git Clone (권장)

```bash
cd ~
git clone https://github.com/YOUR_USERNAME/auto-trading.git
cd auto-trading
uv sync
```

### 4.2 방법 B: 로컬에서 직접 업로드

**로컬 터미널에서:**
```bash
# 프로젝트 폴더 업로드
gcloud compute scp --recurse \
    /path/to/auto-trading \
    trading-bot:~/ \
    --zone=asia-northeast3-a
```

**VM에서:**
```bash
cd ~/auto-trading
uv sync
```

### 4.3 환경변수 설정

```bash
cat > ~/auto-trading/.env << 'EOF'
# Required
UPBIT_ACCESS_KEY=your_upbit_access_key
UPBIT_SECRET_KEY=your_upbit_secret_key
OPENAI_API_KEY=your_openai_api_key

# Trading Mode
TRADING_MODE=paper
OPENAI_MODEL=gpt-4o-mini

# News System
NEWS_MEMORY_ENABLED=true
NEWS_MEMORY_TTL_HOURS=4.0
NEWS_DECAY_HALF_LIFE_HOURS=1.0

# Optional
# CMC_API_KEY=your_coinmarketcap_key
EOF
```

### 4.4 설정 검증

```bash
cd ~/auto-trading
uv run python -m trading.main --validate-only
```

예상 출력:
```
Validating configuration...
  Trading mode: paper
  Max daily loss: 3.0%
  Max position: 50.0%
  LLM model: gpt-4o-mini
Configuration OK
```

---

## 5. 서비스 등록 및 실행

### 5.1 Systemd 서비스 설치

```bash
cd ~/auto-trading
chmod +x scripts/*.sh
sudo ./scripts/install-service.sh
```

### 5.2 서비스 시작

```bash
sudo systemctl start trading-bot
```

### 5.3 서비스 명령어

| 명령어 | 설명 |
|--------|------|
| `sudo systemctl start trading-bot` | 시작 |
| `sudo systemctl stop trading-bot` | 중지 |
| `sudo systemctl restart trading-bot` | 재시작 |
| `sudo systemctl status trading-bot` | 상태 확인 |
| `sudo systemctl enable trading-bot` | 부팅 시 자동 시작 |
| `sudo systemctl disable trading-bot` | 자동 시작 해제 |

### 5.4 Interval 변경

```bash
# 60초 간격으로 재설치
sudo ./scripts/uninstall-service.sh
sudo INTERVAL=60 ./scripts/install-service.sh
sudo systemctl start trading-bot
```

---

## 6. 모니터링 및 관리

### 6.1 로그 확인

```bash
# 실시간 로그
sudo journalctl -u trading-bot -f

# 최근 100줄
sudo journalctl -u trading-bot -n 100

# 오늘 로그만
sudo journalctl -u trading-bot --since today
```

### 6.2 성과 리포트 확인

```bash
# 상태 스크립트 사용
./scripts/bot-status.sh          # 요약
./scripts/bot-status.sh logs     # 실시간 로그
./scripts/bot-status.sh report   # 최신 리포트

# 직접 확인
cat ~/auto-trading/logs/daily_report_*.md
cat ~/auto-trading/logs/performance_metrics.json
```

### 6.3 성과 데이터 다운로드 (로컬에서)

```bash
# 로그 폴더 전체 다운로드
gcloud compute scp --recurse \
    trading-bot:~/auto-trading/logs \
    ./downloaded-logs/ \
    --zone=asia-northeast3-a

# 특정 파일만
gcloud compute scp \
    trading-bot:~/auto-trading/logs/daily_report_20260202.md \
    ./ \
    --zone=asia-northeast3-a
```

### 6.4 코드 업데이트

```bash
# VM에서
cd ~/auto-trading
git pull
uv sync
sudo systemctl restart trading-bot
```

---

## 7. 문제 해결

### 7.1 서비스가 시작 안 될 때

```bash
# 상세 에러 확인
sudo journalctl -u trading-bot -n 50 --no-pager

# 수동 실행으로 테스트
cd ~/auto-trading
uv run python -m trading.main --mode single
```

### 7.2 uv 캐시 권한 에러

에러 메시지:
```
failed to open file `/home/user/.cache/uv/...`: Read-only file system
```

해결:
```bash
sudo sed -i '/ProtectSystem\|ProtectHome\|ReadWritePaths/d' \
    /etc/systemd/system/trading-bot.service
sudo systemctl daemon-reload
sudo systemctl restart trading-bot
```

### 7.3 API 키 에러

```bash
# .env 파일 확인
cat ~/auto-trading/.env

# 설정 검증
cd ~/auto-trading
uv run python -m trading.main --validate-only
```

### 7.4 메모리 부족

```bash
# 메모리 확인
free -h

# 스왑 추가 (필요시)
sudo fallocate -l 1G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# 영구 적용
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### 7.5 VM 재시작 후 봇이 안 켜질 때

```bash
# 서비스 활성화 확인
sudo systemctl is-enabled trading-bot

# 활성화 안 되어있으면
sudo systemctl enable trading-bot
```

---

## 부록

### A. SSH 접속 정보 (IDE/SFTP용)

```bash
# 외부 IP 확인
gcloud compute instances describe trading-bot \
    --zone=asia-northeast3-a \
    --format='get(networkInterfaces[0].accessConfigs[0].natIP)'
```

| 항목 | 값 |
|------|-----|
| Host | 위 명령어 결과 IP |
| Port | 22 |
| Username | `gcloud compute ssh` 첫 접속 시 확인 |
| SSH Key | `~/.ssh/google_compute_engine` |

### B. 비용 관리

```bash
# VM 중지 (비용 절감, 디스크 비용만 발생)
gcloud compute instances stop trading-bot --zone=asia-northeast3-a

# VM 시작
gcloud compute instances start trading-bot --zone=asia-northeast3-a

# VM 삭제 (모든 데이터 삭제됨)
gcloud compute instances delete trading-bot --zone=asia-northeast3-a
```

### C. 유용한 alias 설정

로컬 `~/.bashrc` 또는 `~/.zshrc`에 추가:

```bash
# Trading Bot 관리
alias tb-ssh='gcloud compute ssh trading-bot --zone=asia-northeast3-a'
alias tb-logs='gcloud compute ssh trading-bot --zone=asia-northeast3-a -- journalctl -u trading-bot -f'
alias tb-status='gcloud compute ssh trading-bot --zone=asia-northeast3-a -- systemctl status trading-bot'
alias tb-restart='gcloud compute ssh trading-bot --zone=asia-northeast3-a -- sudo systemctl restart trading-bot'
```

사용:
```bash
tb-ssh       # SSH 접속
tb-logs      # 로그 보기
tb-status    # 상태 확인
tb-restart   # 재시작
```

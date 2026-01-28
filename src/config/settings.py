"""
환경 변수 설정 모듈

책임:
- .env 파일에서 환경 변수 로드
- 설정 값 검증 및 기본값 제공
- 타입 변환 및 경로 처리
"""

import os
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv

# 프로젝트 루트 디렉토리
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# .env 파일 로드
load_dotenv(BASE_DIR / ".env")


@dataclass
class KISSettings:
    """한국투자증권 API 설정"""
    app_key: str
    app_secret: str
    account_no: str
    base_url: str = "https://openapi.koreainvestment.com:9443"
    hts_id: Optional[str] = None
    
    def __post_init__(self):
        # Streamlit Cloud 등 대시보드 전용 모드에서는 API 키 불필요
        if os.getenv("DASHBOARD_ONLY", "").lower() == "true":
            return
        if not self.app_key or not self.app_secret:
            raise ValueError("KIS_APP_KEY와 KIS_APP_SECRET은 필수입니다.")


@dataclass
class DiscordSettings:
    """디스코드 웹훅 설정"""
    webhook_url: str
    enabled: bool = True
    
    def __post_init__(self):
        # DASHBOARD_ONLY 모드에서는 Discord 검증 스킵
        if os.getenv("DASHBOARD_ONLY", "").lower() == "true":
            self.enabled = False
            return
        # 활성화 상태에서만 webhook 필수 검증
        if self.enabled and not self.webhook_url:
            raise ValueError("DISCORD_WEBHOOK_URL이 설정되지 않았습니다.")


@dataclass
class EmailSettings:
    """이메일 알림 설정"""
    enabled: bool = False
    smtp_server: str = "smtp.gmail.com"
    smtp_port: int = 587
    sender: str = ""
    password: str = ""
    receiver: str = ""


@dataclass
class DatabaseSettings:
    """데이터베이스 설정"""
    path: Path
    
    def __post_init__(self):
        # 디렉토리가 없으면 생성
        self.path.parent.mkdir(parents=True, exist_ok=True)


@dataclass
class ScreeningSettings:
    """스크리닝 설정"""
    min_trading_value: float = 200.0  # 억원 (v4.0: 200억으로 변경, 그리드 서치 최적)
    screening_time_main: str = "15:00"
    screening_time_preview: str = "12:30"
    learning_time: str = "16:00"
    top_n_count: int = 5  # TOP N 종목 수 (기본 5)
    
    # Rate Limit (안정성 우선)
    api_call_interval: float = 0.12  # 초당 8회


@dataclass
class AISettings:
    """AI 분석 설정"""
    model: str = "gemini-2.5-flash"
    max_output_tokens: int = 8192
    temperature: float = 0.3


@dataclass
class Settings:
    """전체 설정"""
    kis: KISSettings
    discord: DiscordSettings
    email: EmailSettings
    database: DatabaseSettings
    screening: ScreeningSettings
    ai: AISettings
    
    # 로깅
    log_level: str = "INFO"
    log_path: Path = BASE_DIR / "logs" / "screener.log"
    
    def __post_init__(self):
        # 로그 디렉토리 생성
        self.log_path.parent.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    """환경 변수에서 설정 로드"""
    
    # KIS 설정
    kis = KISSettings(
        app_key=os.getenv("KIS_APP_KEY", "").strip('"'),
        app_secret=os.getenv("KIS_APP_SECRET", "").strip('"'),
        account_no=os.getenv("KIS_ACCOUNT_NO", "").strip('"'),
        base_url=os.getenv("KIS_BASE_URL", "https://openapi.koreainvestment.com:9443"),
        hts_id=os.getenv("KIS_HTS_ID") or os.getenv("hts_id", "").strip() or None,
    )
    
    # Discord 설정 (DASHBOARD_ONLY면 자동 비활성화)
    discord_enabled = os.getenv("DISCORD_ENABLED", "true").lower() == "true"
    if os.getenv("DASHBOARD_ONLY", "").lower() == "true":
        discord_enabled = False
    
    discord = DiscordSettings(
        webhook_url=os.getenv("DISCORD_WEBHOOK_URL", "").strip('"'),
        enabled=discord_enabled,
    )
    
    # Email 설정
    email = EmailSettings(
        enabled=os.getenv("EMAIL_ENABLED", "false").lower() == "true",
        smtp_server=os.getenv("EMAIL_SMTP_SERVER", "smtp.gmail.com"),
        smtp_port=int(os.getenv("EMAIL_SMTP_PORT", "587")),
        sender=os.getenv("EMAIL_SENDER", ""),
        password=os.getenv("EMAIL_PASSWORD", "").strip('"'),
        receiver=os.getenv("EMAIL_RECEIVER", ""),
    )
    
    # Database 설정
    db_path = os.getenv("DB_PATH", str(BASE_DIR / "data" / "screener.db"))
    database = DatabaseSettings(path=Path(db_path))
    
    # Screening 설정
    screening = ScreeningSettings(
        min_trading_value=float(os.getenv("MIN_TRADING_VALUE", "200")),
        screening_time_main=os.getenv("SCREENING_TIME_2", "15:00"),
        screening_time_preview=os.getenv("SCREENING_TIME_1", "12:30"),
        learning_time=os.getenv("LEARNING_TIME", "16:00"),
        top_n_count=int(os.getenv("TOP_N_COUNT", "5")),
        api_call_interval=float(os.getenv("API_CALL_INTERVAL", "0.12")),
    )
    
    # AI 설정
    ai = AISettings(
        model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        max_output_tokens=int(os.getenv("GEMINI_MAX_TOKENS", "8192")),
        temperature=float(os.getenv("GEMINI_TEMPERATURE", "0.3")),
    )
    
    return Settings(
        kis=kis,
        discord=discord,
        email=email,
        database=database,
        screening=screening,
        ai=ai,
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        log_path=Path(os.getenv("LOG_PATH", str(BASE_DIR / "logs" / "screener.log"))),
    )


# 싱글톤 설정 인스턴스
settings = load_settings()


if __name__ == "__main__":
    # 설정 확인용
    print(f"KIS App Key: {settings.kis.app_key[:10]}...")
    print(f"Discord Webhook: {settings.discord.webhook_url[:50]}...")
    print(f"DB Path: {settings.database.path}")
    print(f"Min Trading Value: {settings.screening.min_trading_value}억원")
    print(f"API Call Interval: {settings.screening.api_call_interval}초")
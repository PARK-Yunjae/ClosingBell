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
class KiwoomSettings:
    """키움증권 REST API 설정"""
    app_key: str
    secret_key: str
    base_url: str = "https://api.kiwoom.com"
    use_mock: bool = False  # True면 모의투자 도메인 사용
    
    def __post_init__(self):
        # Streamlit Cloud 등 대시보드 전용 모드에서는 API 키 불필요
        if os.getenv("DASHBOARD_ONLY", "").lower() == "true" or os.getenv("STREAMLIT_SERVER_HEADLESS", "").lower() == "true":
            return
        if not self.app_key or not self.secret_key:
            raise ValueError("KIWOOM_APPKEY와 KIWOOM_SECRETKEY는 필수입니다.")
        
        # 모의투자 도메인 적용
        if self.use_mock:
            self.base_url = "https://mockapi.kiwoom.com"


@dataclass
class DiscordSettings:
    """디스코드 웹훅 설정"""
    webhook_url: str
    enabled: bool = True
    layout: str = "detailed"
    
    def __post_init__(self):
        # DASHBOARD_ONLY 모드에서는 Discord 검증 스킵
        if os.getenv("DASHBOARD_ONLY", "").lower() == "true" or os.getenv("STREAMLIT_SERVER_HEADLESS", "").lower() == "true":
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
class ScheduleSettings:
    """v8.0: 스케줄 시간 설정 (.env에서 오버라이드 가능)"""
    ohlcv_time: str = "16:00"
    global_data_time: str = "16:10"
    nomad_collect_time: str = "16:32"
    company_crawl_time: str = "16:37"
    news_collect_time: str = "16:39"
    nomad_ai_time: str = "16:40"
    top5_ai_time: str = "16:45"
    git_commit_time: str = "17:00"
    auto_shutdown_time: str = "17:30"


@dataclass
class BrokerSettings:
    """v8.0: 거래원 스캔 설정"""
    scan_top_n: int = 20           # 상위 N개 종목만 스캔
    api_delay: float = 0.15        # ka10040 호출 간격 (초)
    neutral_score: float = 6.0     # 조회불가/프리뷰 기본 점수


@dataclass
class VolumeProfileSettings:
    """v9.0: 매물대(Volume Profile) 설정"""
    source: str = "auto"           # auto | kiwoom | local
    cycle: int = 100               # 50~300 (??
    bands: int = 10                # 매물대 수
    cur_entry: int = 0             # 0: 현재가 밴드 제외, 1: 포함
    concentration_rate: int = 70   # 매물대집중비율(%)
    market: str = "000"            # 000:??, 001:???, 101:???
    stex_tp: str = "3"             # 1:KRX, 2:NXT, 3:??
    api_id: str = "ka10025"        # ??????? TR ID (?? ??)
    trde_qty_tp: str = "0"         # (?? ???) ??? ??
    endpoint: str = ""             # ??? ? ?? ??? ??



@dataclass
class Settings:
    """전체 설정 v8.0"""
    kiwoom: KiwoomSettings  # 키움 REST API (메인)
    discord: DiscordSettings
    email: EmailSettings
    database: DatabaseSettings
    screening: ScreeningSettings
    ai: AISettings
    schedule: ScheduleSettings       # 🆕 v8.0
    broker: BrokerSettings           # 🆕 v8.0
    vp: VolumeProfileSettings        # v9.0
    
    # 로깅
    log_level: str = "INFO"
    log_path: Path = BASE_DIR / "logs" / "screener.log"
    
    def __post_init__(self):
        # 로그 디렉토리 생성
        self.log_path.parent.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    """환경 변수에서 설정 로드"""
    
    # 키움 설정 (메인 브로커)
    kiwoom = KiwoomSettings(
        app_key=os.getenv("KIWOOM_APPKEY", "").strip('"'),
        secret_key=os.getenv("KIWOOM_SECRETKEY", "").strip('"'),
        base_url=os.getenv("KIWOOM_BASE_URL", "https://api.kiwoom.com"),
        use_mock=os.getenv("KIWOOM_USE_MOCK", "false").lower() == "true",
    )
    
    # Discord 설정 (DASHBOARD_ONLY면 자동 비활성화)
    discord_enabled = os.getenv("DISCORD_ENABLED", "true").lower() == "true"
    if os.getenv("DASHBOARD_ONLY", "").lower() == "true" or os.getenv("STREAMLIT_SERVER_HEADLESS", "").lower() == "true":
        discord_enabled = False
    
    discord_layout = os.getenv("DISCORD_LAYOUT", "detailed").strip('"').lower()
    if discord_layout not in {"compact", "detailed"}:
        discord_layout = "detailed"
    discord = DiscordSettings(
        webhook_url=os.getenv("DISCORD_WEBHOOK_URL", "").strip('"'),
        enabled=discord_enabled,
        layout=discord_layout,
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
    
    # v8.0: 스케줄 설정
    schedule = ScheduleSettings(
        ohlcv_time=os.getenv("SCHEDULE_OHLCV_TIME", "16:00"),
        global_data_time=os.getenv("SCHEDULE_GLOBAL_DATA_TIME", "16:10"),
        nomad_collect_time=os.getenv("SCHEDULE_NOMAD_COLLECT_TIME", "16:32"),
        company_crawl_time=os.getenv("SCHEDULE_COMPANY_CRAWL_TIME", "16:37"),
        news_collect_time=os.getenv("SCHEDULE_NEWS_COLLECT_TIME", "16:39"),
        nomad_ai_time=os.getenv("SCHEDULE_NOMAD_AI_TIME", "16:40"),
        top5_ai_time=os.getenv("SCHEDULE_TOP5_AI_TIME", "16:45"),
        git_commit_time=os.getenv("SCHEDULE_GIT_COMMIT_TIME", "17:00"),
        auto_shutdown_time=os.getenv("SCHEDULE_AUTO_SHUTDOWN_TIME", "17:30"),
    )
    
    # v8.0: 거래원 설정
    broker = BrokerSettings(
        scan_top_n=int(os.getenv("BROKER_SCAN_TOP_N", "20")),
        api_delay=float(os.getenv("BROKER_API_DELAY", "0.15")),
        neutral_score=float(os.getenv("BROKER_NEUTRAL_SCORE", "6.0")),
    )

    # v9.0: 매물대 설정
    vp = VolumeProfileSettings(
        source=os.getenv("VP_SOURCE", "auto").lower(),
        cycle=int(os.getenv("VP_CYCLE", "100")),
        bands=int(os.getenv("VP_BANDS", "10")),
        cur_entry=int(os.getenv("VP_CUR_ENTRY", "0")),
        concentration_rate=int(os.getenv("VP_CNCTR_RT", "70")),
        market=os.getenv("VP_MRKT_TP", "000"),
        stex_tp=os.getenv("VP_STEX_TP", "3"),
        api_id=os.getenv("VP_API_ID", "ka10025"),
        trde_qty_tp=os.getenv("VP_TRDE_QTY_TP", "0"),
        endpoint=os.getenv("VP_ENDPOINT", "").strip(),
    )
    
    return Settings(
        kiwoom=kiwoom,
        discord=discord,
        email=email,
        database=database,
        screening=screening,
        ai=ai,
        schedule=schedule,
        broker=broker,
        vp=vp,
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        log_path=Path(os.getenv("LOG_PATH", str(BASE_DIR / "logs" / "screener.log"))),
    )


# 싱글톤 설정 인스턴스
settings = load_settings()


if __name__ == "__main__":
    # 설정 확인용
    print(f"Kiwoom App Key: {'설정됨' if settings.kiwoom.app_key else '미설정'}")
    print(f"Kiwoom Base URL: {settings.kiwoom.base_url}")
    print(f"Discord Webhook: {'설정됨' if settings.discord.webhook_url else '미설정'}")
    print(f"DB Path: {settings.database.path}")
    print(f"Min Trading Value: {settings.screening.min_trading_value}억원")
    print(f"API Call Interval: {settings.screening.api_call_interval}초")

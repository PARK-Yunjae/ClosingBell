"""
설정 검증 모듈

책임:
- 시작 시 모든 필수 설정값 검증
- 누락된 설정 있으면 명확한 에러 메시지 출력
- 설정 값 형식 검증

사용법:
    from src.config.validator import validate_settings
    
    # 애플리케이션 시작 시
    validate_settings()  # 실패 시 ConfigValidationError 발생
"""

import re
import logging
from typing import List
from dataclasses import dataclass, field
from enum import Enum

from src.config.settings import settings, BASE_DIR

logger = logging.getLogger(__name__)


class ValidationSeverity(Enum):
    """검증 실패 심각도"""
    ERROR = "error"      # 필수 - 실행 불가
    WARNING = "warning"  # 권장 - 실행 가능하지만 기능 제한


@dataclass
class ValidationResult:
    """검증 결과"""
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    def add_error(self, message: str):
        self.errors.append(message)
        self.valid = False
    
    def add_warning(self, message: str):
        self.warnings.append(message)


class ConfigValidationError(Exception):
    """설정 검증 실패 예외"""
    
    def __init__(self, result: ValidationResult):
        self.result = result
        super().__init__(self._format_message())
    
    def _format_message(self) -> str:
        lines = ["설정 검증 실패:"]
        
        if self.result.errors:
            lines.append("\n[필수 설정 누락 - 실행 불가]")
            for err in self.result.errors:
                lines.append(f"  ❌ {err}")
        
        if self.result.warnings:
            lines.append("\n[권장 설정 누락 - 일부 기능 제한]")
            for warn in self.result.warnings:
                lines.append(f"  ⚠️ {warn}")
        
        lines.append("\n💡 .env.example 파일을 참고하여 .env 파일을 설정해주세요.")
        
        return "\n".join(lines)


def validate_kis_settings(result: ValidationResult):
    """KIS API 설정 검증"""
    # 필수: APP_KEY
    if not settings.kis.app_key or settings.kis.app_key == "your_app_key_here":
        result.add_error(
            "KIS_APP_KEY 미설정 - 한국투자증권 개발자센터에서 발급받으세요."
        )
    
    # 필수: APP_SECRET
    if not settings.kis.app_secret or settings.kis.app_secret == "your_app_secret_here":
        result.add_error(
            "KIS_APP_SECRET 미설정 - 한국투자증권 개발자센터에서 발급받으세요."
        )
    
    # 권장: ACCOUNT_NO (조회 기능에는 필요 없음)
    if not settings.kis.account_no or settings.kis.account_no == "12345678-01":
        result.add_warning(
            "KIS_ACCOUNT_NO 미설정 - 실제 계좌번호를 입력하세요 (조회만 할 경우 필요 없음)."
        )
    
    # BASE_URL 형식 검증
    if not settings.kis.base_url.startswith("https://"):
        result.add_error(
            f"KIS_BASE_URL 형식 오류 - https://로 시작해야 합니다: {settings.kis.base_url}"
        )


def validate_discord_settings(result: ValidationResult):
    """Discord 설정 검증"""
    webhook_url = settings.discord.webhook_url
    
    if not webhook_url:
        result.add_warning(
            "DISCORD_WEBHOOK_URL 미설정 - Discord 알림을 사용하려면 설정하세요."
        )
    elif "your_webhook" in webhook_url.lower():
        result.add_warning(
            "DISCORD_WEBHOOK_URL이 예시 값입니다 - 실제 웹훅 URL을 입력하세요."
        )
    elif not re.match(r'^https://discord\.com/api/webhooks/\d+/.+$', webhook_url):
        result.add_warning(
            f"DISCORD_WEBHOOK_URL 형식이 올바르지 않습니다: {webhook_url[:50]}..."
        )


def validate_database_settings(result: ValidationResult):
    """데이터베이스 설정 검증"""
    db_path = settings.database.path
    
    # 디렉토리 존재 확인
    if not db_path.parent.exists():
        try:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            logger.info(f"DB 디렉토리 생성: {db_path.parent}")
        except Exception as e:
            result.add_error(f"DB 디렉토리 생성 실패: {e}")


def validate_log_settings(result: ValidationResult):
    """로깅 설정 검증"""
    log_path = settings.log_path
    
    # 로그 디렉토리 존재 확인
    if not log_path.parent.exists():
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            logger.info(f"로그 디렉토리 생성: {log_path.parent}")
        except Exception as e:
            result.add_error(f"로그 디렉토리 생성 실패: {e}")
    
    # 로그 레벨 검증
    valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    if settings.log_level.upper() not in valid_levels:
        result.add_warning(
            f"LOG_LEVEL 값이 올바르지 않습니다: {settings.log_level}. "
            f"유효한 값: {', '.join(valid_levels)}"
        )


def validate_screening_settings(result: ValidationResult):
    """스크리닝 설정 검증"""
    # 최소 거래대금 검증
    if settings.screening.min_trading_value < 0:
        result.add_error(
            f"MIN_TRADING_VALUE는 0 이상이어야 합니다: {settings.screening.min_trading_value}"
        )
    
    # 시간 형식 검증
    time_pattern = r'^\d{1,2}:\d{2}$'
    
    if not re.match(time_pattern, settings.screening.screening_time_main):
        result.add_error(
            f"SCREENING_TIME_2 형식 오류 (HH:MM): {settings.screening.screening_time_main}"
        )
    
    if not re.match(time_pattern, settings.screening.screening_time_preview):
        result.add_error(
            f"SCREENING_TIME_1 형식 오류 (HH:MM): {settings.screening.screening_time_preview}"
        )
    
    # API 호출 간격 검증
    if settings.screening.api_call_interval < 0.05:
        result.add_warning(
            f"API_CALL_INTERVAL이 너무 짧습니다 (Rate Limit 주의): {settings.screening.api_call_interval}초"
        )


def validate_env_file_exists(result: ValidationResult):
    """.env 파일 존재 확인"""
    env_path = BASE_DIR / ".env"
    env_example_path = BASE_DIR / ".env.example"
    
    if not env_path.exists():
        if env_example_path.exists():
            result.add_error(
                ".env 파일이 없습니다. .env.example을 복사하여 생성하세요:\n"
                "    cp .env.example .env"
            )
        else:
            result.add_error(
                ".env 파일이 없습니다. 환경 변수 설정이 필요합니다."
            )


def validate_settings(raise_on_error: bool = True) -> ValidationResult:
    """모든 설정 검증
    
    Args:
        raise_on_error: True면 에러 발생 시 예외를 던짐
        
    Returns:
        검증 결과
        
    Raises:
        ConfigValidationError: 필수 설정 누락 시 (raise_on_error=True인 경우)
    """
    result = ValidationResult(valid=True)
    
    # .env 파일 확인
    validate_env_file_exists(result)
    
    # 각 설정 그룹 검증
    validate_kis_settings(result)
    validate_discord_settings(result)
    validate_database_settings(result)
    validate_log_settings(result)
    validate_screening_settings(result)
    
    # 결과 로깅
    if result.valid:
        if result.warnings:
            logger.warning(f"설정 검증 경고 {len(result.warnings)}개")
            for warn in result.warnings:
                logger.warning(f"  ⚠️ {warn}")
        else:
            logger.info("✅ 모든 설정 검증 통과")
    else:
        logger.error(f"❌ 설정 검증 실패: 에러 {len(result.errors)}개, 경고 {len(result.warnings)}개")
    
    # 에러 발생 시 예외
    if raise_on_error and not result.valid:
        raise ConfigValidationError(result)
    
    return result


def print_settings_summary():
    """현재 설정 요약 출력"""
    print("\n" + "=" * 60)
    print("📋 현재 설정 요약")
    print("=" * 60)
    
    # KIS 설정
    print("\n[KIS API]")
    print(f"  APP_KEY: {'설정됨' if settings.kis.app_key else '미설정'}")
    print(f"  APP_SECRET: {'설정됨' if settings.kis.app_secret else '미설정'}")
    print(f"  BASE_URL: {settings.kis.base_url}")
    
    # Discord 설정
    print("\n[Discord]")
    webhook = settings.discord.webhook_url
    print(f"  WEBHOOK_URL: {'설정됨' if webhook and 'your_webhook' not in webhook.lower() else '미설정'}")
    
    # 스크리닝 설정
    print("\n[스크리닝]")
    print(f"  최소 거래대금: {settings.screening.min_trading_value}억원")
    print(f"  프리뷰 시간: {settings.screening.screening_time_preview}")
    print(f"  메인 시간: {settings.screening.screening_time_main}")
    
    # 기타
    print("\n[기타]")
    print(f"  DB 경로: {settings.database.path}")
    print(f"  로그 레벨: {settings.log_level}")
    
    print("\n" + "=" * 60)


if __name__ == "__main__":
    # 테스트
    logging.basicConfig(level=logging.INFO)
    
    print("설정 검증 테스트...")
    
    try:
        result = validate_settings(raise_on_error=False)
        
        print(f"\n검증 결과: {'통과' if result.valid else '실패'}")
        print(f"에러: {len(result.errors)}개")
        print(f"경고: {len(result.warnings)}개")
        
        if result.errors:
            print("\n[에러]")
            for err in result.errors:
                print(f"  ❌ {err}")
        
        if result.warnings:
            print("\n[경고]")
            for warn in result.warnings:
                print(f"  ⚠️ {warn}")
        
        # 설정 요약 출력
        print_settings_summary()
        
    except ConfigValidationError as e:
        print(str(e))

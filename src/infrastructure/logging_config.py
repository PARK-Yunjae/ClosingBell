"""
로깅 설정 모듈

책임:
- 일별 로그 파일 분리 (logs/YYYY-MM-DD.log)
- 콘솔 + 파일 동시 로깅
- 에러 발생 시 상세 traceback 저장
- API 호출 성능 로깅

의존성:
- logging
- pathlib
"""

import logging
import traceback
import time
import re
from datetime import datetime
from pathlib import Path
from functools import wraps
from typing import Any, Callable, Optional
from logging.handlers import TimedRotatingFileHandler

from src.config.settings import BASE_DIR, settings


class DailyRotatingFileHandler(TimedRotatingFileHandler):
    """일별 로그 파일 핸들러
    
    logs/YYYY-MM-DD.log 형식으로 자동 분리
    """
    
    def __init__(self, log_dir: Path, encoding: str = 'utf-8'):
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # 오늘 날짜 기준 파일명
        filename = self._get_log_filename()
        
        super().__init__(
            filename=filename,
            when='midnight',
            interval=1,
            backupCount=30,  # 30일 보관
            encoding=encoding,
        )
        
        # namer를 오버라이드하여 파일명 형식 지정
        self.namer = self._custom_namer
        self.rotator = self._custom_rotator
    
    def _get_log_filename(self) -> str:
        """현재 날짜 기준 로그 파일명 반환"""
        today = datetime.now().strftime('%Y-%m-%d')
        return str(self.log_dir / f"{today}.log")
    
    def _custom_namer(self, default_name: str) -> str:
        """로테이션 후 파일명 지정"""
        # 기본 형식: YYYY-MM-DD.log.YYYY-MM-DD
        # 원하는 형식: YYYY-MM-DD.log (이미 날짜별이므로)
        return default_name
    
    def _custom_rotator(self, source: str, dest: str):
        """로테이션 시 파일 이동"""
        import os
        if os.path.exists(source):
            os.rename(source, dest)
    
    def doRollover(self):
        """자정에 로그 파일 교체"""
        # 새로운 날짜의 파일로 변경
        self.baseFilename = self._get_log_filename()
        super().doRollover()


class TracebackFormatter(logging.Formatter):
    """상세 traceback을 포함한 포매터"""
    
    def formatException(self, exc_info):
        """예외 정보를 상세하게 포맷"""
        return ''.join(traceback.format_exception(*exc_info))
    
    def format(self, record):
        """레코드 포맷 (traceback 포함)"""
        # 기본 포맷
        formatted = super().format(record)
        
        # 에러 레벨에서 추가 정보 포함
        if record.exc_info and record.levelno >= logging.ERROR:
            # 구분선 추가
            formatted += "\n" + "=" * 60 + "\n"
            formatted += "TRACEBACK DETAIL:\n"
            formatted += self.formatException(record.exc_info)
            formatted += "=" * 60
        
        return formatted

class RedactingFilter(logging.Filter):
    """???? ??? ??"""
    _patterns = [
        re.compile(r"(Bearer\s+)[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE),
        re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)([^\s]+)"),
        re.compile(r"(?i)(secret\s*[:=]\s*)([^\s]+)"),
        re.compile(r"(https?://[^\s]+)"),
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = str(record.getMessage())
            redacted = msg
            for pattern in self._patterns:
                redacted = pattern.sub(r"\1<REDACTED>", redacted)
            if redacted != msg:
                record.msg = redacted
                record.args = ()
        except Exception:
            pass
        return True



def setup_logging(
    log_level: str = "INFO",
    log_dir: Optional[Path] = None,
) -> logging.Logger:
    """로깅 설정
    
    Args:
        log_level: 로그 레벨 (DEBUG, INFO, WARNING, ERROR)
        log_dir: 로그 디렉토리 경로
        
    Returns:
        루트 로거
    """
    log_dir = log_dir or (BASE_DIR / "logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # 포맷 설정
    console_format = '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    file_format = '%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s'
    
    # 콘솔 핸들러
    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    console_handler.setFormatter(logging.Formatter(console_format))
    
    # 일별 파일 핸들러
    file_handler = DailyRotatingFileHandler(log_dir)
    file_handler.setLevel(logging.DEBUG)  # 파일에는 모든 레벨 기록
    file_handler.setFormatter(TracebackFormatter(file_format))
    
    # 에러 전용 파일 핸들러 (errors.log)
    error_handler = logging.FileHandler(
        log_dir / "errors.log",
        encoding='utf-8',
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(TracebackFormatter(file_format))
    
    # 루트 로거 설정
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    
    # 기존 핸들러 제거
    root_logger.handlers.clear()
    
    # 핸들러 추가
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(error_handler)
    
    # 외부 라이브러리 로깅 레벨 조정
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('apscheduler').setLevel(logging.WARNING)
    logging.getLogger('requests').setLevel(logging.WARNING)
    
    return root_logger


def log_api_call(
    api_name: str = "API",
    include_args: bool = False,
) -> Callable:
    """API 호출 로깅 데코레이터
    
    Args:
        api_name: API 이름 (로그에 표시)
        include_args: 인자 로깅 여부
        
    Usage:
        @log_api_call("KIS/일봉조회")
        def get_daily_prices(self, stock_code: str, ...):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            logger = logging.getLogger(func.__module__)
            
            # 시작 로그
            start_time = time.time()
            
            # 종목코드/이름 추출 시도
            stock_info = ""
            if 'stock_code' in kwargs:
                stock_info = f" [{kwargs['stock_code']}]"
            elif len(args) > 1 and isinstance(args[1], str) and len(args[1]) <= 10:
                stock_info = f" [{args[1]}]"
            
            try:
                result = func(*args, **kwargs)
                
                # 성공 로그
                elapsed = time.time() - start_time
                logger.debug(
                    f"{api_name}{stock_info} 호출 완료 (소요시간: {elapsed:.3f}초)"
                )
                
                return result
                
            except Exception as e:
                # 실패 로그
                elapsed = time.time() - start_time
                logger.error(
                    f"{api_name}{stock_info} 호출 실패 (소요시간: {elapsed:.3f}초): {e}",
                    exc_info=True,
                )
                raise
        
        return wrapper
    return decorator


def log_execution_time(
    operation_name: str = "작업",
) -> Callable:
    """실행 시간 로깅 데코레이터
    
    Args:
        operation_name: 작업명 (로그에 표시)
        
    Usage:
        @log_execution_time("스크리닝")
        def run_screening(self):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            logger = logging.getLogger(func.__module__)
            
            start_time = time.time()
            logger.info(f"▶ {operation_name} 시작")
            
            try:
                result = func(*args, **kwargs)
                
                elapsed = time.time() - start_time
                logger.info(f"◀ {operation_name} 완료 (소요시간: {elapsed:.1f}초)")
                
                return result
                
            except Exception as e:
                elapsed = time.time() - start_time
                logger.error(
                    f"✕ {operation_name} 실패 (소요시간: {elapsed:.1f}초): {e}",
                    exc_info=True,
                )
                raise
        
        return wrapper
    return decorator


def log_error_with_context(
    logger: logging.Logger,
    error: Exception,
    context: str = "",
    extra_info: Optional[dict] = None,
):
    """에러를 컨텍스트와 함께 상세 로깅
    
    Args:
        logger: 로거 인스턴스
        error: 예외 객체
        context: 에러 발생 컨텍스트
        extra_info: 추가 정보 딕셔너리
    """
    # 에러 메시지 구성
    msg_parts = [
        f"에러 발생: {context}" if context else "에러 발생",
        f"에러 타입: {type(error).__name__}",
        f"에러 메시지: {str(error)}",
    ]
    
    if extra_info:
        msg_parts.append("추가 정보:")
        for key, value in extra_info.items():
            msg_parts.append(f"  {key}: {value}")
    
    # 상세 traceback
    tb = traceback.format_exc()
    msg_parts.append("Traceback:")
    msg_parts.append(tb)
    
    logger.error("\n".join(msg_parts))


# 전역 로깅 설정 함수 (main.py에서 호출)
def init_logging():
    """애플리케이션 시작 시 로깅 초기화"""
    return setup_logging(
        log_level=settings.log_level,
        log_dir=BASE_DIR / "logs",
    )


if __name__ == "__main__":
    # 테스트
    init_logging()
    
    logger = logging.getLogger(__name__)
    
    logger.debug("디버그 메시지")
    logger.info("정보 메시지")
    logger.warning("경고 메시지")
    
    try:
        raise ValueError("테스트 에러")
    except Exception as e:
        log_error_with_context(
            logger,
            e,
            context="테스트 중 에러 발생",
            extra_info={"stock_code": "005930", "api": "get_daily_prices"},
        )
    
    print(f"\n로그 파일 위치: {BASE_DIR / 'logs'}")

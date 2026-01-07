#!/usr/bin/env python
"""
카카오 OAuth 토큰 발급 헬퍼

카카오톡 "나에게 보내기" 기능 사용을 위한 토큰 발급 유틸리티

사용법:
  python tools/kakao_token_helper.py --init     # 최초 토큰 발급
  python tools/kakao_token_helper.py --refresh  # 토큰 갱신
  python tools/kakao_token_helper.py --status   # 토큰 상태 확인

참고:
  - 카카오 액세스 토큰 유효기간: 6시간 (21600초)
  - 리프레시 토큰 유효기간: 2달 (5184000초)
  - scope: talk_message (나에게 보내기)
"""

import os
import sys
import argparse
import webbrowser
import requests
from pathlib import Path
from urllib.parse import urlencode
from datetime import datetime, timedelta
from dotenv import load_dotenv, set_key

# 프로젝트 루트 경로
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"

# .env 로드
load_dotenv(ENV_PATH)


class KakaoTokenHelper:
    """카카오 OAuth 토큰 헬퍼"""
    
    # 카카오 OAuth 엔드포인트
    AUTHORIZE_URL = "https://kauth.kakao.com/oauth/authorize"
    TOKEN_URL = "https://kauth.kakao.com/oauth/token"
    TOKEN_INFO_URL = "https://kapi.kakao.com/v1/user/access_token_info"
    
    def __init__(self):
        self.rest_api_key = os.getenv("KAKAO_REST_API_KEY", "").strip('"')
        self.client_secret = os.getenv("KAKAO_CLIENT_SECRET", "UeLXRKLFeKldrSF7DL6alWsjNVcBqsug").strip('"')
        self.redirect_uri = os.getenv("KAKAO_REDIRECT_URI", "http://localhost:3000/oauth")
        self.access_token = os.getenv("KAKAO_ACCESS_TOKEN", "").strip('"').split('#')[0].strip()
        self.refresh_token = os.getenv("KAKAO_REFRESH_TOKEN", "").strip('"')
        
        if not self.rest_api_key:
            print("❌ KAKAO_REST_API_KEY가 .env에 설정되지 않았습니다.")
            sys.exit(1)
    
    def get_authorize_url(self) -> str:
        """인가코드 요청 URL 생성"""
        params = {
            "client_id": self.rest_api_key,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "talk_message",
        }
        return f"{self.AUTHORIZE_URL}?{urlencode(params)}"
    
    def get_token_with_code(self, auth_code: str) -> dict:
        """인가코드로 토큰 발급"""
        data = {
            "grant_type": "authorization_code",
            "client_id": self.rest_api_key,
            "redirect_uri": self.redirect_uri,
            "code": auth_code,
            "client_secret": self.client_secret,
        }
        
        response = requests.post(self.TOKEN_URL, data=data, timeout=10)
        
        if response.status_code != 200:
            print(f"❌ 토큰 발급 실패: {response.text}")
            return {}
        
        return response.json()
    
    def refresh_access_token(self) -> dict:
        """리프레시 토큰으로 액세스 토큰 갱신"""
        if not self.refresh_token:
            print("❌ 리프레시 토큰이 없습니다. --init으로 먼저 토큰을 발급받으세요.")
            return {}
        
        data = {
            "grant_type": "refresh_token",
            "client_id": self.rest_api_key,
            "refresh_token": self.refresh_token,
            "client_secret": self.client_secret,
        }
        
        response = requests.post(self.TOKEN_URL, data=data, timeout=10)
        
        if response.status_code != 200:
            print(f"❌ 토큰 갱신 실패: {response.text}")
            return {}
        
        return response.json()
    
    def get_token_info(self) -> dict:
        """토큰 정보 조회"""
        if not self.access_token:
            return {}
        
        headers = {"Authorization": f"Bearer {self.access_token}"}
        
        try:
            response = requests.get(self.TOKEN_INFO_URL, headers=headers, timeout=10)
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 401:
                return {"error": "토큰 만료 또는 유효하지 않음"}
            else:
                return {"error": response.text}
        except Exception as e:
            return {"error": str(e)}
    
    def save_tokens_to_env(self, token_data: dict) -> bool:
        """토큰을 .env 파일에 저장"""
        try:
            if "access_token" in token_data:
                set_key(str(ENV_PATH), "KAKAO_ACCESS_TOKEN", token_data["access_token"])
                print(f"✅ KAKAO_ACCESS_TOKEN 저장 완료")
            
            if "refresh_token" in token_data:
                set_key(str(ENV_PATH), "KAKAO_REFRESH_TOKEN", token_data["refresh_token"])
                print(f"✅ KAKAO_REFRESH_TOKEN 저장 완료")
            
            return True
        except Exception as e:
            print(f"❌ .env 저장 실패: {e}")
            return False
    
    def init_token(self, auto_open: bool = True):
        """최초 토큰 발급 프로세스"""
        print("\n" + "=" * 60)
        print("  🔑 카카오 OAuth 토큰 발급")
        print("=" * 60)
        
        # 1. 인가코드 URL 출력
        auth_url = self.get_authorize_url()
        print(f"\n1️⃣ 아래 URL을 브라우저에서 열고 로그인하세요:")
        print(f"\n   {auth_url}\n")
        
        if auto_open:
            print("   (자동으로 브라우저를 엽니다...)")
            webbrowser.open(auth_url)
        
        print("\n2️⃣ 로그인 후 리다이렉트된 URL에서 'code=' 뒤의 값을 복사하세요.")
        print("   예: http://localhost:3000/oauth?code=XXXXX")
        print("        → 'XXXXX' 부분만 복사")
        
        # 2. 인가코드 입력
        print("\n3️⃣ 인가코드를 입력하세요:")
        auth_code = input("   code = ").strip()
        
        if not auth_code:
            print("❌ 인가코드가 입력되지 않았습니다.")
            return
        
        # 3. 토큰 발급
        print("\n4️⃣ 토큰 발급 중...")
        token_data = self.get_token_with_code(auth_code)
        
        if not token_data:
            return
        
        # 4. 결과 출력
        print("\n" + "=" * 60)
        print("  ✅ 토큰 발급 성공!")
        print("=" * 60)
        
        access_token = token_data.get("access_token", "")
        refresh_token = token_data.get("refresh_token", "")
        expires_in = token_data.get("expires_in", 0)
        
        print(f"\n📌 Access Token: {access_token[:30]}...")
        print(f"📌 Refresh Token: {refresh_token[:30]}...")
        print(f"⏰ Access Token 만료: {expires_in}초 ({expires_in // 3600}시간)")
        
        # 5. .env 저장 여부 확인
        print("\n5️⃣ .env 파일에 토큰을 저장하시겠습니까? (권장)")
        save = input("   저장 (y/n): ").strip().lower()
        
        if save == 'y':
            self.save_tokens_to_env(token_data)
            print("\n🎉 완료! 이제 카카오톡 알림을 사용할 수 있습니다.")
        else:
            print("\n📋 수동으로 .env 파일에 아래 값을 추가하세요:")
            print(f"   KAKAO_ACCESS_TOKEN={access_token}")
            print(f"   KAKAO_REFRESH_TOKEN={refresh_token}")
    
    def do_refresh(self, auto_save: bool = True):
        """토큰 갱신"""
        print("\n" + "=" * 60)
        print("  🔄 카카오 액세스 토큰 갱신")
        print("=" * 60)
        
        if not self.refresh_token:
            print("\n❌ 리프레시 토큰이 없습니다.")
            print("   --init 옵션으로 먼저 토큰을 발급받으세요.")
            return
        
        print(f"\n현재 리프레시 토큰: {self.refresh_token[:30]}...")
        print("토큰 갱신 중...")
        
        token_data = self.refresh_access_token()
        
        if not token_data:
            return
        
        access_token = token_data.get("access_token", "")
        new_refresh = token_data.get("refresh_token")  # 리프레시 토큰이 갱신될 수도 있음
        expires_in = token_data.get("expires_in", 0)
        
        print("\n" + "=" * 60)
        print("  ✅ 토큰 갱신 성공!")
        print("=" * 60)
        
        print(f"\n📌 새 Access Token: {access_token[:30]}...")
        print(f"⏰ 만료: {expires_in}초 ({expires_in // 3600}시간)")
        
        if new_refresh:
            print(f"📌 새 Refresh Token: {new_refresh[:30]}...")
        
        if auto_save:
            self.save_tokens_to_env(token_data)
            print("\n🎉 토큰이 갱신되어 .env에 저장되었습니다.")
    
    def show_status(self):
        """토큰 상태 확인"""
        print("\n" + "=" * 60)
        print("  📊 카카오 토큰 상태")
        print("=" * 60)
        
        print(f"\n📌 REST API Key: {self.rest_api_key[:15]}...")
        print(f"📌 Redirect URI: {self.redirect_uri}")
        
        if self.access_token:
            print(f"📌 Access Token: {self.access_token[:30]}...")
            
            # 토큰 정보 조회
            token_info = self.get_token_info()
            
            if "error" in token_info:
                print(f"⚠️  상태: {token_info['error']}")
            else:
                expires_in = token_info.get("expires_in", 0)
                expire_time = datetime.now() + timedelta(seconds=expires_in)
                
                print(f"✅ 상태: 유효")
                print(f"⏰ 남은 시간: {expires_in}초 ({expires_in // 60}분)")
                print(f"⏰ 만료 예정: {expire_time.strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            print("❌ Access Token: 없음")
        
        if self.refresh_token:
            print(f"📌 Refresh Token: {self.refresh_token[:30]}...")
        else:
            print("❌ Refresh Token: 없음")
        
        # 카카오톡 알림 활성화 상태
        print("\n" + "-" * 40)
        if self.access_token:
            token_info = self.get_token_info()
            if "error" not in token_info:
                print("🔔 카카오톡 알림: 활성화 가능")
            else:
                print("⚠️  카카오톡 알림: 토큰 갱신 필요 (--refresh)")
        else:
            print("❌ 카카오톡 알림: 비활성화 (--init으로 토큰 발급 필요)")


def main():
    parser = argparse.ArgumentParser(
        description="카카오 OAuth 토큰 발급 헬퍼",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python tools/kakao_token_helper.py --init      # 최초 토큰 발급
  python tools/kakao_token_helper.py --refresh   # 토큰 갱신
  python tools/kakao_token_helper.py --status    # 상태 확인
        """
    )
    
    parser.add_argument(
        "--init",
        action="store_true",
        help="최초 토큰 발급 (브라우저에서 인가코드 획득)"
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="리프레시 토큰으로 액세스 토큰 갱신"
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="현재 토큰 상태 확인"
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="브라우저 자동 열기 비활성화 (--init 시)"
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help=".env 자동 저장 비활성화 (--refresh 시)"
    )
    
    args = parser.parse_args()
    
    helper = KakaoTokenHelper()
    
    if args.init:
        helper.init_token(auto_open=not args.no_browser)
    elif args.refresh:
        helper.do_refresh(auto_save=not args.no_save)
    elif args.status:
        helper.show_status()
    else:
        # 기본: 상태 확인
        helper.show_status()
        print("\n" + "=" * 60)
        print("💡 도움말: python tools/kakao_token_helper.py --help")


if __name__ == "__main__":
    main()

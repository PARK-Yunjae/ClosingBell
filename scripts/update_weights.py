"""
가중치 수동 업데이트 스크립트

백테스트 결과 (v2.1 최적화):
- cci_value: 0.50
- cci_slope: 2.50
- ma20_slope: 2.50
- candle: 2.50
- change: 0.50
"""

import sys
from pathlib import Path

# 프로젝트 루트 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.infrastructure.database import init_database
from src.infrastructure.repository import get_weight_repository


# 백테스트 최적화 결과 (v2.1)
NEW_WEIGHTS = {
    'cci_value': 0.50,
    'cci_slope': 2.50,
    'ma20_slope': 2.50,
    'candle': 2.50,
    'change': 0.50,
}

REASON = "백테스트 v2.1 최적화 결과 적용 (2016-2025 데이터 기반)"


def main():
    # DB 초기화
    init_database()
    
    repo = get_weight_repository()
    
    # 현재 가중치 확인
    current = repo.get_weights()
    print("\n" + "=" * 60)
    print("📊 현재 가중치")
    print("=" * 60)
    for indicator, weight in current.to_dict().items():
        print(f"  • {indicator}: {weight}")
    
    # 변경 내용 미리보기
    print("\n" + "=" * 60)
    print("🔄 변경 예정 가중치 (백테스트 v2.1 최적화)")
    print("=" * 60)
    for indicator, new_weight in NEW_WEIGHTS.items():
        old_weight = current.to_dict().get(indicator, 1.0)
        change = "↑" if new_weight > old_weight else "↓" if new_weight < old_weight else "="
        print(f"  • {indicator}: {old_weight} → {new_weight} {change}")
    
    print(f"\n📝 변경 사유: {REASON}")
    
    # 확인
    print("\n" + "=" * 60)
    confirm = input("✅ 가중치를 변경하시겠습니까? (y/n): ").strip().lower()
    
    if confirm != 'y':
        print("❌ 취소되었습니다.")
        return
    
    # 가중치 업데이트
    print("\n🔧 가중치 업데이트 중...")
    for indicator, new_weight in NEW_WEIGHTS.items():
        repo.update_weight(
            indicator=indicator,
            new_weight=new_weight,
            reason=REASON,
        )
        print(f"  ✓ {indicator}: {new_weight}")
    
    # 변경 후 확인
    updated = repo.get_weights()
    print("\n" + "=" * 60)
    print("✅ 변경 완료! 새 가중치")
    print("=" * 60)
    for indicator, weight in updated.to_dict().items():
        print(f"  • {indicator}: {weight}")
    
    # 이력 확인
    print("\n" + "=" * 60)
    print("📜 최근 변경 이력")
    print("=" * 60)
    history = repo.get_weight_history(days=1)
    for h in history[:5]:
        print(f"  • {h['indicator']}: {h['old_weight']} → {h['new_weight']}")
    
    print("\n✨ 가중치 변경이 완료되었습니다!")
    print("   다음 스크리닝(15시)부터 새 가중치가 적용됩니다.")


if __name__ == "__main__":
    main()

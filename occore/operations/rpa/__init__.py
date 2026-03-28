"""
OpenRPA 연동 모듈

자동화 시나리오:
- 반복 주문 조정 스크립트
- 일일 리포트 자동 다운로드
"""

from .automation import RPAAutomation, AutomationTask

__all__ = ["RPAAutomation", "AutomationTask"]

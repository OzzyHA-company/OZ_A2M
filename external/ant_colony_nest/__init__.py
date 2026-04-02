"""
Ant Colony Nest - Python package wrapper
실제 파일은 external/ant-colony-nest/ 에 위치
hyphen → underscore 패키지 브릿지
"""
import sys
from pathlib import Path

# ant-colony-nest 실제 경로를 sys.path에 추가
_nest_path = Path(__file__).parent.parent / "ant-colony-nest"
if str(_nest_path) not in sys.path:
    sys.path.insert(0, str(_nest_path))

# openclaw 스킬 경로도 추가
_skill_path = Path.home() / ".openclaw" / "skills" / "oz-a2m-ant-colony-nest" / "scripts"
if str(_skill_path) not in sys.path:
    sys.path.insert(0, str(_skill_path))
